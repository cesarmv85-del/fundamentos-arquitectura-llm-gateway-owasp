"""
logging_seguro.py — Logging JSON de auditoría sin fugas (OWASP LLM02)
=======================================================================

Principio: el sistema de logs es, en sí mismo, un almacén de datos que otras
personas (SRE, soporte, proveedores de observabilidad) pueden leer. Todo lo
que se escribe aquí se trata como potencialmente expuesto.

Dos barreras independientes:

  1. ALLOWLIST DE CAMPOS — el formateador descarta cualquier campo que no esté
     en CAMPOS_PERMITIDOS. Si mañana un desarrollador hace
     `log.info("x", extra={"campos": {"prompt": texto}})`, el campo `prompt`
     simplemente no se escribe. Es "denegar por defecto", no "recordar borrar".
  2. REDACCIÓN POR PATRONES — incluso en campos permitidos, cualquier valor que
     parezca una credencial (sk-…, sk-ant-…, AIza…, Bearer …, gw_…, ?key=…) o un
     correo electrónico se reemplaza por [REDACTADO]. Red de seguridad por si
     un mensaje de error externo trae un secreto embebido.

Qué SÍ se registra (útil para auditoría): timestamp, request_id, endpoint,
método, estado HTTP, resultado, latencia, cliente_id (hash, no la clave),
proveedor, modelo, tokens, longitud del mensaje y CATEGORÍAS de bloqueo.

Qué NO se registra jamás: contenido del prompt, contenido de la respuesta,
cabeceras HTTP, API keys (de proveedor o de cliente), system prompt, token
canario, IP completa, ni el detalle interno de errores upstream.

`FormateadorIngenuo` reproduce el anti-patrón "loguear todo por si acaso"
(error común #3 del enunciado) y solo se usa con MITIGACION_LLM02=false para
la línea base.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

CAMPOS_PERMITIDOS = frozenset({
    "timestamp", "nivel", "evento", "request_id", "endpoint", "metodo",
    "estado_http", "resultado", "latencia_ms", "cliente_id", "proveedor",
    "modelo", "tokens_entrada", "tokens_salida", "longitud_mensaje",
    "categorias_bloqueo", "puntaje_inyeccion", "motivo_fuga", "tipo_error",
    "degradado", "proveedor_fallido", "mitigaciones_activas", "limite",
})

PATRONES_SECRETOS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-(proj-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"gw_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)([?&](key|api_key|apikey|token)=)[^&\s'\"]+"),
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
]


def redactar(valor):
    if isinstance(valor, str):
        for patron in PATRONES_SECRETOS:
            valor = patron.sub("[REDACTADO]", valor)
        return valor
    if isinstance(valor, list):
        return [redactar(v) for v in valor]
    if isinstance(valor, dict):
        return {k: redactar(v) for k, v in valor.items()}
    return valor


class FormateadorJSONSeguro(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        campos = dict(getattr(record, "campos", {}) or {})
        campos.setdefault("evento", record.getMessage())
        campos["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        campos["nivel"] = record.levelname
        filtrado = {k: redactar(v) for k, v in campos.items() if k in CAMPOS_PERMITIDOS}
        return json.dumps(filtrado, ensure_ascii=False, sort_keys=True)


class FormateadorIngenuo(logging.Formatter):
    """LÍNEA BASE INSEGURA — escribe todo lo que recibe, sin filtrar."""

    def format(self, record: logging.LogRecord) -> str:
        campos = dict(getattr(record, "campos", {}) or {})
        campos.setdefault("evento", record.getMessage())
        campos["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        campos["nivel"] = record.levelname
        return json.dumps(campos, ensure_ascii=False, default=str)


NOMBRE_LOGGER = "gateway.auditoria"


def configurar_logger(archivo: str, seguro: bool, consola: bool = True) -> logging.Logger:
    logger = logging.getLogger(NOMBRE_LOGGER)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    formateador = FormateadorJSONSeguro() if seguro else FormateadorIngenuo()
    if consola:
        sh = logging.StreamHandler()
        sh.setFormatter(formateador)
        logger.addHandler(sh)
    if archivo:
        Path(archivo).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(archivo, encoding="utf-8")
        fh.setFormatter(formateador)
        logger.addHandler(fh)
    return logger


def registrar(evento: str, nivel: int = logging.INFO, **campos) -> None:
    logging.getLogger(NOMBRE_LOGGER).log(nivel, evento, extra={"campos": {"evento": evento, **campos}})
