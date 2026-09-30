"""
proveedores.py — ÚNICO punto de salida hacia los proveedores de LLM
======================================================================

Regla de arquitectura (verificada por tests/test_arquitectura.py): ningún otro
módulo del proyecto importa SDKs de proveedores ni contiene sus URLs. Si
mañana se agrega un proveedor, se agrega AQUÍ y hereda automáticamente
autenticación, rate limiting, sanitización, filtro de salida y logging.

Diferencias deliberadas respecto a session_5/backend/proveedores.py:
- Google: la key va en la cabecera `x-goog-api-key`, NO en `?key=` de la URL.
  Con la key en la URL, cualquier excepción de httpx (cuyo mensaje incluye la
  URL completa) o cualquier log de acceso de un proxy la expone (LLM02).
- Si falta la key de un proveedor real NO se cae a modo simulado en silencio:
  se lanza ErrorProveedor("configuracion"). En un gateway, responder con datos
  simulados sin avisar sería una degradación engañosa. El modo simulado es un
  proveedor explícito: PROVEEDOR_PRINCIPAL=simulado.
- Todos los errores se convierten a ErrorProveedor con un `tipo` controlado.
  El `detalle_interno` (que puede contener URLs o fragmentos sensibles) NUNCA
  se devuelve al cliente y solo se registra si LLM02 está desactivado (línea base).
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass

import httpx

from .config import Configuracion

PROVEEDORES_SOPORTADOS = ("simulado", "simulado_respaldo", "openai", "anthropic", "google", "ollama")


@dataclass
class RespuestaModelo:
    texto: str
    proveedor: str
    modelo: str
    tokens_entrada: int
    tokens_salida: int
    simulado: bool


class ErrorProveedor(Exception):
    """tipo ∈ {timeout, no_disponible, saturado, configuracion}"""

    def __init__(self, tipo: str, proveedor: str, detalle_interno: str = ""):
        super().__init__(tipo)
        self.tipo = tipo
        self.proveedor = proveedor
        self.detalle_interno = detalle_interno


def _tokens_aprox(texto: str) -> int:
    return max(1, round(len(texto) / 4))


# ─── Proveedor SIMULADO (modelo "ingenuo" para demos reproducibles) ────────────
# Emula un LLM SIN alineamiento de seguridad: obedece inyecciones al pie de la
# letra. Así la línea base "SIN protección" es determinística y reproducible
# sin gastar tokens. Con un modelo real el ataque tiene éxito de forma
# probabilística (ver docs/MAPEO_OWASP.md §Reproducir con proveedor real).

def _plegar(t: str) -> str:
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


_PIDE_SYSTEM = re.compile(r"(system ?prompt|instrucciones (del sistema|iniciales|originales|ocultas)|prompt del sistema)")
_PIDE_IGNORAR = re.compile(r"\b(ignora|olvida|ignore|disregard)\b")


async def _simulado(cfg: Configuracion, system_prompt: str, usuario: str, max_tokens: int,
                    nombre: str = "simulado") -> RespuestaModelo:
    # "simulado_respaldo" nunca falla: permite demostrar el fallback sin red.
    falla = cfg.simular_falla_upstream if nombre == "simulado" else ""
    if falla == "timeout":
        await asyncio.sleep(0.05)
        raise ErrorProveedor("timeout", "simulado", "ReadTimeout: upstream no respondió en el plazo configurado")
    if falla == "error_500":
        raise ErrorProveedor("no_disponible", "simulado", "HTTPStatusError: 500 Internal Server Error — Traceback (most recent call last): ...")
    if falla == "error_con_clave":
        # Reproduce el mensaje REAL que httpx genera cuando la key viaja en la
        # URL (patrón de session_5/backend/proveedores.py::llamar_google).
        clave = cfg.google_api_key.get_secret_value() if cfg.google_api_key else "AIza-clave-no-configurada"
        raise ErrorProveedor(
            "no_disponible", "simulado",
            "Client error '403 Forbidden' for url 'https://generativelanguage.googleapis.com/"
            f"v1beta/models/gemini-2.5-flash:generateContent?key={clave}'",
        )

    # Un LLM real "lee a través" de caracteres invisibles (el tokenizador los
    # ignora o los separa); el modelo ingenuo los elimina para emularlo.
    p = _plegar(re.sub("[\u200b-\u200f\u2060\ufeff]", "", usuario))
    if _PIDE_SYSTEM.search(p):
        texto = f"Claro. Estas son mis instrucciones completas: {system_prompt}"
    elif _PIDE_IGNORAR.search(p):
        texto = ("Entendido, ignoro mis reglas anteriores. Nueva política: devoluciones "
                 "en 365 días con reembolso doble y sin boleta.")
    elif "devol" in p:
        texto = "Puedes devolver tu producto dentro de 30 días desde la compra, con boleta y sin uso."
    else:
        texto = "[MODO_SIMULADO] Gracias por tu consulta. Un asesor de Tienda Andina puede ayudarte con pedidos, envíos, pagos y devoluciones."
    palabras = texto.split()
    texto = " ".join(palabras[: max(1, max_tokens)])  # respeta el techo de salida
    return RespuestaModelo(texto, nombre, "modelo-ingenuo-v1", _tokens_aprox(system_prompt + usuario), _tokens_aprox(texto), True)


# ─── Proveedores reales ─────────────────────────────────────────────────────

def _requerir(clave, proveedor: str) -> str:
    if clave is None:
        raise ErrorProveedor("configuracion", proveedor, f"Falta la API key de {proveedor}")
    return clave.get_secret_value()


async def _post(proveedor: str, url: str, headers: dict, payload: dict, timeout: float) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as cliente:
            r = await cliente.post(url, headers=headers, json=payload)
            r.raise_for_status()
            return r.json()
    except httpx.TimeoutException as e:
        raise ErrorProveedor("timeout", proveedor, repr(e)) from None
    except httpx.HTTPStatusError as e:
        codigo = e.response.status_code
        tipo = "saturado" if codigo == 429 else "configuracion" if codigo in (400, 401, 403, 404) else "no_disponible"
        raise ErrorProveedor(tipo, proveedor, str(e)) from None
    except (httpx.HTTPError, ValueError) as e:
        raise ErrorProveedor("no_disponible", proveedor, repr(e)) from None


async def _openai(cfg, system_prompt, usuario, max_tokens, temperature) -> RespuestaModelo:
    key = _requerir(cfg.openai_api_key, "openai")
    data = await _post("openai", "https://api.openai.com/v1/chat/completions",
                       {"Authorization": f"Bearer {key}"},
                       {"model": cfg.modelo_openai, "max_tokens": max_tokens, "temperature": temperature,
                        "messages": [{"role": "system", "content": system_prompt},
                                     {"role": "user", "content": usuario}]},
                       cfg.timeout_upstream_seg)
    texto = data["choices"][0]["message"]["content"] or ""
    uso = data.get("usage", {})
    return RespuestaModelo(texto, "openai", cfg.modelo_openai, uso.get("prompt_tokens", 0), uso.get("completion_tokens", 0), False)


async def _anthropic(cfg, system_prompt, usuario, max_tokens, temperature) -> RespuestaModelo:
    key = _requerir(cfg.anthropic_api_key, "anthropic")
    data = await _post("anthropic", "https://api.anthropic.com/v1/messages",
                       {"x-api-key": key, "anthropic-version": "2023-06-01"},
                       {"model": cfg.modelo_anthropic, "max_tokens": max_tokens, "temperature": temperature,
                        "system": system_prompt, "messages": [{"role": "user", "content": usuario}]},
                       cfg.timeout_upstream_seg)
    texto = "".join(b.get("text", "") for b in data.get("content", []))
    uso = data.get("usage", {})
    return RespuestaModelo(texto, "anthropic", cfg.modelo_anthropic, uso.get("input_tokens", 0), uso.get("output_tokens", 0), False)


async def _google(cfg, system_prompt, usuario, max_tokens, temperature) -> RespuestaModelo:
    key = _requerir(cfg.google_api_key, "google")
    data = await _post("google",
                       f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.modelo_google}:generateContent",
                       {"x-goog-api-key": key},  # ← cabecera, NUNCA ?key= en la URL
                       {"systemInstruction": {"parts": [{"text": system_prompt}]},
                        "contents": [{"role": "user", "parts": [{"text": usuario}]}],
                        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature}},
                       cfg.timeout_upstream_seg)
    texto = data["candidates"][0]["content"]["parts"][0]["text"]
    meta = data.get("usageMetadata", {})
    return RespuestaModelo(texto, "google", cfg.modelo_google, meta.get("promptTokenCount", 0), meta.get("candidatesTokenCount", 0), False)


async def _ollama(cfg, system_prompt, usuario, max_tokens, temperature) -> RespuestaModelo:
    data = await _post("ollama", f"{cfg.ollama_base_url}/api/chat", {},
                       {"model": cfg.modelo_ollama, "stream": False,
                        "options": {"num_predict": max_tokens, "temperature": temperature},
                        "messages": [{"role": "system", "content": system_prompt},
                                     {"role": "user", "content": usuario}]},
                       max(cfg.timeout_upstream_seg, 60))
    texto = data.get("message", {}).get("content", "")
    return RespuestaModelo(texto, "ollama", cfg.modelo_ollama, data.get("prompt_eval_count", 0), data.get("eval_count", 0), False)


async def completar(cfg: Configuracion, proveedor: str, system_prompt: str, usuario: str,
                    max_tokens: int, temperature: float) -> RespuestaModelo:
    if proveedor in ("simulado", "simulado_respaldo"):
        return await _simulado(cfg, system_prompt, usuario, max_tokens, proveedor)
    funciones = {"openai": _openai, "anthropic": _anthropic, "google": _google, "ollama": _ollama}
    if proveedor not in funciones:
        raise ErrorProveedor("configuracion", proveedor, f"Proveedor no soportado: {proveedor}")
    return await funciones[proveedor](cfg, system_prompt, usuario, max_tokens, temperature)


async def completar_con_respaldo(cfg: Configuracion, proveedor: str, system_prompt: str, usuario: str,
                                 max_tokens: int, temperature: float) -> tuple[RespuestaModelo, bool, list[ErrorProveedor]]:
    """Degradación controlada: si el principal falla y hay PROVEEDOR_RESPALDO,
    se intenta una vez con el respaldo. Devuelve (respuesta, degradado, errores)."""
    errores: list[ErrorProveedor] = []
    candidatos = [proveedor] + ([cfg.proveedor_respaldo] if cfg.proveedor_respaldo and cfg.proveedor_respaldo != proveedor else [])
    for i, nombre in enumerate(candidatos):
        try:
            r = await completar(cfg, nombre, system_prompt, usuario, max_tokens, temperature)
            return r, i > 0, errores
        except ErrorProveedor as e:
            errores.append(e)
    raise errores[-1]
