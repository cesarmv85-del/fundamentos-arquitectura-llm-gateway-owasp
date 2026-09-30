"""
auth.py — Autenticación de CLIENTES del gateway
=================================================

Cada aplicación interna que consume el gateway recibe su propia clave
(`gw_...`). El gateway:
  1. NUNCA guarda la clave en claro: compara SHA-256 en tiempo constante
     (hmac.compare_digest) contra GATEWAY_CLIENT_KEYS_SHA256.
  2. Deriva un `cliente_id` estable y NO reversible (nombre del cliente +
     prefijo del hash) que se usa para:
       - rate limiting POR CLAVE (LLM10) — no por IP;
       - auditoría en logs (LLM02) — el log nunca ve la clave.

Esto separa dos secretos que el backend de la Sesión 4 no distinguía:
  - la key del PROVEEDOR (OpenAI/Anthropic/Google) → nunca sale del gateway;
  - la key del CLIENTE (gw_...) → identifica a quién cobrar/limitar.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Request

PREFIJO_CLAVE = "gw_"


@dataclass(frozen=True)
class Cliente:
    nombre: str
    cliente_id: str  # ej. "equipo_soporte#3fa2c1" — seguro para logs


class ErrorAutenticacion(Exception):
    """Se traduce a 401 genérico en errores.py (no revela si la clave existe)."""


def hash_clave(clave: str) -> str:
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def extraer_bearer(request: Request) -> Optional[str]:
    cabecera = request.headers.get("authorization", "")
    esquema, _, token = cabecera.partition(" ")
    if esquema.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def identificar_cliente(token: Optional[str], claves_sha256: dict[str, str]) -> Cliente:
    if not token or not token.startswith(PREFIJO_CLAVE):
        raise ErrorAutenticacion()
    digest = hash_clave(token)
    for digest_valido, nombre in claves_sha256.items():
        if hmac.compare_digest(digest, digest_valido):
            return Cliente(nombre=nombre, cliente_id=f"{nombre}#{digest[:6]}")
    raise ErrorAutenticacion()
