"""
main.py — Gateway LLM con seguridad OWASP (Proyecto Final · Opción 4)
=======================================================================

ÚNICO punto de entrada hacia los LLM:  POST /v1/chat

Flujo de una solicitud (cada paso vive en su propio módulo):

  cliente ─► [LímiteBody ASGI] ─► [auth.py: clave gw_ → cliente_id]
          ─► [Pydantic: longitud máx., techo max_tokens]     LLM10  (422 no consume cuota)
          ─► [slowapi: RATE_LIMIT por cliente_id]            LLM10
          ─► [sanitizacion.py: normaliza/detecta/encapsula]  LLM01
          ─► [proveedores.py: único egress + respaldo]       degradación controlada
          ─► [salida.py: canario + n-gramas]                 LLM07
          ─► respuesta ─► [middleware auditoría → logging_seguro.py]  LLM02

Ejecutar:
    uvicorn gateway.main:app --port 8000
"""

import logging
import time
import uuid
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import proveedores
from .auth import Cliente, ErrorAutenticacion, extraer_bearer, identificar_cliente
from .config import Configuracion
from .logging_seguro import configurar_logger, registrar
from .salida import construir_system_prompt, generar_canario, verificar_salida
from .sanitizacion import encapsular, sanitizar

# ─── Mensajes al cliente: claros, accionables y SIN detalles internos ──────────

MENSAJES_ERROR = {
    "timeout": (504, "El proveedor de IA no respondió a tiempo. Intente nuevamente en unos segundos."),
    "saturado": (503, "El proveedor de IA está saturado en este momento. Intente nuevamente en un minuto."),
    "no_disponible": (503, "El servicio de IA no está disponible temporalmente. Intente más tarde."),
    "configuracion": (502, "El gateway no pudo completar la solicitud por un problema de configuración. Contacte al equipo de plataforma con el request_id."),
}


def _json_error(request: Request, estado: int, codigo: str, mensaje: str, headers: Optional[dict] = None) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    return JSONResponse(status_code=estado, content={"error": codigo, "mensaje": mensaje, "request_id": rid}, headers=headers)


class LimiteBody:
    """Middleware ASGI puro (LLM10): corta cuerpos mayores a MAX_BYTES_BODY
    mientras se reciben, sin cargarlos completos en memoria."""

    def __init__(self, app, max_bytes: int, activo: bool):
        self.app, self.max_bytes, self.activo = app, max_bytes, activo

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.activo:
            return await self.app(scope, receive, send)
        cabeceras = dict(scope.get("headers") or [])
        declarado = cabeceras.get(b"content-length")
        if declarado and declarado.isdigit() and int(declarado) > self.max_bytes:
            return await self._rechazar(send)
        recibido = 0

        async def receive_limitado():
            nonlocal recibido
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                recibido += len(mensaje.get("body", b""))
                if recibido > self.max_bytes:
                    raise _CuerpoDemasiadoGrande()
            return mensaje

        try:
            await self.app(scope, receive_limitado, send)
        except _CuerpoDemasiadoGrande:
            await self._rechazar(send)

    @staticmethod
    async def _rechazar(send):
        cuerpo = b'{"error":"cuerpo_demasiado_grande","mensaje":"La solicitud excede el tamano maximo permitido."}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(cuerpo)).encode())]})
        await send({"type": "http.response.body", "body": cuerpo})


class _CuerpoDemasiadoGrande(Exception):
    pass


def crear_app(cfg: Optional[Configuracion] = None) -> FastAPI:
    cfg = cfg or Configuracion()
    cfg.validar_para_produccion()
    configurar_logger(cfg.log_archivo, seguro=cfg.mitigacion_llm02, consola=cfg.log_consola)

    canario = generar_canario()
    system_prompt = construir_system_prompt(canario)

    es_prod = cfg.entorno == "produccion"
    app = FastAPI(
        title="Gateway LLM — Seguridad OWASP",
        description="Proyecto Final Opción 4 · Fundamentos de Arquitectura LLM (BSG)",
        version="1.0.0",
        docs_url=None if es_prod else "/docs",
        redoc_url=None,
        openapi_url=None if es_prod else "/openapi.json",
    )
    app.state.cfg = cfg

    # ── LLM10: rate limiting POR CLAVE DE CLIENTE (no por IP) ──────────────
    def clave_rate_limit(request: Request) -> str:
        cliente: Optional[Cliente] = getattr(request.state, "cliente", None)
        if cfg.rate_limit_por == "clave" and cliente:
            return f"cliente:{cliente.cliente_id}"
        return f"ip:{get_remote_address(request)}"

    limiter = Limiter(key_func=clave_rate_limit, storage_uri=cfg.rate_limit_storage_uri,
                      enabled=cfg.mitigacion_llm10, headers_enabled=False)
    app.state.limiter = limiter

    # Límites de tamaño: con LLM10 apagado se usan valores "sin techo" (línea base)
    max_chars = cfg.max_caracteres_mensaje if cfg.mitigacion_llm10 else 1_000_000
    max_tok = cfg.max_tokens_techo if cfg.mitigacion_llm10 else 100_000

    class SolicitudChat(BaseModel):
        mensaje: str = Field(..., min_length=1, max_length=max_chars)
        max_tokens: int = Field(256, ge=1, le=max_tok)
        temperature: float = Field(0.2, ge=0.0, le=1.5)
        proveedor: Optional[Literal[proveedores.PROVEEDORES_SOPORTADOS]] = None  # type: ignore[valid-type]

    class RespuestaChat(BaseModel):
        request_id: str
        respuesta: str
        proveedor: str
        modelo: str
        simulado: bool
        degradado: bool
        tokens_entrada: int
        tokens_salida: int
        latencia_ms: int

    # ── Middlewares ──────────────────────────────────────────────────────
    @app.middleware("http")
    async def auditoria(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:16]
        request.state.auditoria = {}
        inicio = time.perf_counter()
        try:
            respuesta = await call_next(request)
        except Exception as exc:  # red de seguridad: nunca una traza al cliente
            request.state.auditoria.update(resultado="error_interno", tipo_error=type(exc).__name__)
            respuesta = _json_error(request, 500, "error_interno",
                                    "Ocurrió un error interno. Contacte al equipo de plataforma con el request_id.")
        latencia = int((time.perf_counter() - inicio) * 1000)
        cliente = getattr(request.state, "cliente", None)
        estado = respuesta.status_code
        campos = {
            "request_id": request.state.request_id,
            "endpoint": request.url.path,
            "metodo": request.method,
            "estado_http": estado,
            "resultado": request.state.auditoria.pop("resultado", "ok" if estado < 400 else "error"),
            "latencia_ms": latencia,
            "cliente_id": cliente.cliente_id if cliente else None,
            **request.state.auditoria,
        }
        if not cfg.mitigacion_llm02:
            # LÍNEA BASE INSEGURA: "loguear todo por si acaso".
            campos["headers"] = dict(request.headers)
        registrar("solicitud", logging.WARNING if estado >= 400 else logging.INFO, **campos)
        respuesta.headers["X-Request-ID"] = request.state.request_id
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=False)
    app.add_middleware(LimiteBody, max_bytes=cfg.max_bytes_body, activo=cfg.mitigacion_llm10)

    # ── Manejadores de error: degradación controlada, sin trazas ──────────
    @app.exception_handler(ErrorAutenticacion)
    async def _auth(request: Request, exc: ErrorAutenticacion):
        request.state.auditoria["resultado"] = "no_autorizado"
        return _json_error(request, 401, "no_autorizado", "Credenciales del gateway inválidas o ausentes.",
                           {"WWW-Authenticate": "Bearer"})

    @app.exception_handler(RateLimitExceeded)
    async def _rate(request: Request, exc: RateLimitExceeded):
        request.state.auditoria.update(resultado="rate_limit_excedido", limite=str(exc.detail))
        return _json_error(request, 429, "limite_excedido",
                           f"Superó el límite de solicitudes de su clave ({exc.detail}). Reintente más tarde.",
                           {"Retry-After": "60"})

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError):
        # FastAPI por defecto devuelve el campo "input" con el valor recibido:
        # eso reflejaría el prompt completo. Solo se devuelve campo + regla.
        errores = [{"campo": ".".join(str(p) for p in e.get("loc", [])[1:]), "regla": e.get("type")} for e in exc.errors()]
        request.state.auditoria["resultado"] = "validacion_fallida"
        rid = request.state.request_id
        return JSONResponse(status_code=422, content={"error": "solicitud_invalida", "mensaje": "La solicitud no cumple el esquema o excede los límites.", "detalles": errores, "request_id": rid})

    @app.exception_handler(proveedores.ErrorProveedor)
    async def _upstream(request: Request, exc: proveedores.ErrorProveedor):
        estado, mensaje = MENSAJES_ERROR.get(exc.tipo, MENSAJES_ERROR["no_disponible"])
        request.state.auditoria.update(resultado="error_upstream", tipo_error=exc.tipo, proveedor_fallido=exc.proveedor)
        if not cfg.mitigacion_llm02:
            # LÍNEA BASE INSEGURA — idéntico a session_4/backend/main.py:
            #   raise HTTPException(502, detail=f"Error al llamar al modelo: {e}")
            request.state.auditoria["error_detalle"] = exc.detalle_interno
            return JSONResponse(status_code=502, content={"detail": f"Error al llamar al modelo: {exc.detalle_interno}"})
        return _json_error(request, estado, f"upstream_{exc.tipo}", mensaje)

    @app.exception_handler(Exception)
    async def _generico(request: Request, exc: Exception):
        request.state.auditoria.update(resultado="error_interno", tipo_error=type(exc).__name__)
        return _json_error(request, 500, "error_interno", "Ocurrió un error interno. Contacte al equipo de plataforma con el request_id.")

    # ── Dependencia de autenticación ──────────────────────────────────────
    async def cliente_autenticado(request: Request) -> Cliente:
        cliente = identificar_cliente(extraer_bearer(request), cfg.claves_cliente_sha256)
        request.state.cliente = cliente
        return cliente

    # ── Endpoints ─────────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/v1/seguridad/estado")
    async def estado_seguridad(cliente: Cliente = Depends(cliente_autenticado)):
        return {"mitigaciones": cfg.estado_mitigaciones(), "rate_limit": cfg.rate_limit if cfg.mitigacion_llm10 else None,
                "rate_limit_por": cfg.rate_limit_por, "max_tokens_techo": max_tok, "max_caracteres_mensaje": max_chars}

    @app.post("/v1/chat", response_model=RespuestaChat)
    @limiter.limit(cfg.rate_limit)
    async def chat(request: Request, solicitud: SolicitudChat, cliente: Cliente = Depends(cliente_autenticado)):
        inicio = time.perf_counter()
        aud = request.state.auditoria
        aud["longitud_mensaje"] = len(solicitud.mensaje)
        if not cfg.mitigacion_llm02:
            aud["prompt_usuario"] = solicitud.mensaje  # LÍNEA BASE INSEGURA

        # LLM01 — sanitización antes de que el texto llegue al prompt
        if cfg.mitigacion_llm01:
            res = sanitizar(solicitud.mensaje, max_chars)
            if res.bloqueado:
                aud.update(resultado="bloqueado_llm01", categorias_bloqueo=res.categorias, puntaje_inyeccion=res.puntaje)
                return _json_error(request, 400, "solicitud_rechazada",
                                   "La solicitud fue rechazada por las políticas de seguridad del gateway (posible prompt injection).")
            contenido_usuario = encapsular(res.texto)
        else:
            contenido_usuario = solicitud.mensaje

        nombre_proveedor = solicitud.proveedor or cfg.proveedor_principal
        r, degradado, errores = await proveedores.completar_con_respaldo(
            cfg, nombre_proveedor, system_prompt, contenido_usuario, solicitud.max_tokens, solicitud.temperature)
        if degradado:
            aud.update(degradado=True, proveedor_fallido=errores[0].proveedor, tipo_error=errores[0].tipo)

        # LLM07 — la respuesta no puede contener el system prompt
        texto = r.texto
        if cfg.mitigacion_llm07:
            verif = verificar_salida(texto, system_prompt, canario)
            if verif.fuga_detectada:
                aud.update(resultado="fuga_bloqueada_llm07", motivo_fuga=verif.motivo)
                texto = verif.texto
        if not cfg.mitigacion_llm02:
            aud["respuesta_modelo"] = texto  # LÍNEA BASE INSEGURA

        aud.update(proveedor=r.proveedor, modelo=r.modelo, tokens_entrada=r.tokens_entrada, tokens_salida=r.tokens_salida)
        return RespuestaChat(request_id=request.state.request_id, respuesta=texto, proveedor=r.proveedor,
                             modelo=r.modelo, simulado=r.simulado, degradado=degradado,
                             tokens_entrada=r.tokens_entrada, tokens_salida=r.tokens_salida,
                             latencia_ms=int((time.perf_counter() - inicio) * 1000))

    registrar("gateway_iniciado", mitigaciones_activas=cfg.estado_mitigaciones(), proveedor=cfg.proveedor_principal)
    return app


def __getattr__(nombre: str):
    """`uvicorn gateway.main:app` — la app se crea recién cuando se pide,
    así importar crear_app() en pruebas no levanta un gateway adicional."""
    if nombre == "app":
        instancia = crear_app()
        globals()["app"] = instancia
        return instancia
    raise AttributeError(nombre)
