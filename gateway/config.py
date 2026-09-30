"""
config.py — Configuración centralizada del gateway
=====================================================

Toda la configuración se lee de variables de entorno (patrón del curso desde
la Sesión 1b: os.getenv() + .env, nunca valores hardcodeados).

Decisiones de seguridad (OWASP LLM02 — Sensitive Information Disclosure):
- Las API keys de los proveedores se envuelven en `SecretStr` de Pydantic:
  su repr/str muestra '**********', así que un print(), un log accidental o
  una traza de excepción NO revelan el valor.
- Se admite la variante `<VAR>_FILE` (ej. OPENAI_API_KEY_FILE=/run/secrets/openai)
  para leer la key desde un archivo montado por Docker secrets, Kubernetes o
  Google Secret Manager — así la key ni siquiera vive en el entorno del proceso.
- Las claves de CLIENTE del gateway nunca se guardan en claro: solo su
  SHA-256 (ver auth.py y scripts/generar_clave_cliente.py).

Los interruptores MITIGACION_* existen SOLO para demostrar el comportamiento
"antes/después" que exige el proyecto. En producción deben estar todos en true
(y `validar_para_produccion()` lo exige cuando ENTORNO=produccion).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import SecretStr

load_dotenv()


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None or valor.strip() == "":
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def _int(nombre: str, defecto: int) -> int:
    valor = os.getenv(nombre)
    return int(valor) if valor and valor.strip() else defecto


def _secreto(nombre: str) -> Optional[SecretStr]:
    """Lee un secreto desde NOMBRE_FILE (preferido) o desde NOMBRE."""
    ruta = os.getenv(f"{nombre}_FILE")
    if ruta and Path(ruta).is_file():
        valor = Path(ruta).read_text(encoding="utf-8").strip()
    else:
        valor = (os.getenv(nombre) or "").strip()
    return SecretStr(valor) if valor else None


def _claves_cliente() -> dict[str, str]:
    """
    GATEWAY_CLIENT_KEYS_SHA256="equipo_ventas:<sha256>,equipo_soporte:<sha256>"
    Devuelve {sha256: nombre_cliente}.
    """
    crudo = os.getenv("GATEWAY_CLIENT_KEYS_SHA256", "")
    resultado: dict[str, str] = {}
    for par in filter(None, (p.strip() for p in crudo.split(","))):
        nombre, _, digest = par.partition(":")
        if nombre and len(digest) == 64:
            resultado[digest.lower()] = nombre
    return resultado


@dataclass
class Configuracion:
    entorno: str = field(default_factory=lambda: os.getenv("ENTORNO", "desarrollo"))

    # ── Proveedores upstream ──────────────────────────────────────────────
    proveedor_principal: str = field(default_factory=lambda: os.getenv("PROVEEDOR_PRINCIPAL", "simulado"))
    proveedor_respaldo: str = field(default_factory=lambda: os.getenv("PROVEEDOR_RESPALDO", ""))
    modelo_openai: str = field(default_factory=lambda: os.getenv("MODELO_OPENAI", "gpt-4o-mini"))
    modelo_anthropic: str = field(default_factory=lambda: os.getenv("MODELO_ANTHROPIC", "claude-haiku-4-5"))
    modelo_google: str = field(default_factory=lambda: os.getenv("MODELO_GOOGLE", "gemini-2.5-flash"))
    modelo_ollama: str = field(default_factory=lambda: os.getenv("MODELO_OLLAMA", "llama3.2"))
    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    openai_api_key: Optional[SecretStr] = field(default_factory=lambda: _secreto("OPENAI_API_KEY"))
    anthropic_api_key: Optional[SecretStr] = field(default_factory=lambda: _secreto("ANTHROPIC_API_KEY"))
    google_api_key: Optional[SecretStr] = field(default_factory=lambda: _secreto("GOOGLE_API_KEY"))
    timeout_upstream_seg: float = field(default_factory=lambda: float(os.getenv("TIMEOUT_UPSTREAM_SEG", "20")))
    # Solo para demos: fuerza un fallo del proveedor "simulado"
    # (vacío | timeout | error_500 | error_con_clave)
    simular_falla_upstream: str = field(default_factory=lambda: os.getenv("SIMULAR_FALLA_UPSTREAM", ""))

    # ── Clientes del gateway ─────────────────────────────────────────────
    claves_cliente_sha256: dict[str, str] = field(default_factory=_claves_cliente)

    # ── LLM10: Unbounded Consumption ─────────────────────────────────────
    rate_limit: str = field(default_factory=lambda: os.getenv("RATE_LIMIT", "5/minute"))
    rate_limit_por: str = field(default_factory=lambda: os.getenv("RATE_LIMIT_POR", "clave"))  # clave | ip
    rate_limit_storage_uri: str = field(default_factory=lambda: os.getenv("RATE_LIMIT_STORAGE_URI", "memory://"))
    max_tokens_techo: int = field(default_factory=lambda: _int("MAX_TOKENS_TECHO", 512))
    max_caracteres_mensaje: int = field(default_factory=lambda: _int("MAX_CARACTERES_MENSAJE", 4000))
    max_bytes_body: int = field(default_factory=lambda: _int("MAX_BYTES_BODY", 16_384))

    # ── Logging ──────────────────────────────────────────────────────────
    log_archivo: str = field(default_factory=lambda: os.getenv("LOG_ARCHIVO", "logs/gateway.jsonl"))
    log_consola: bool = field(default_factory=lambda: _bool("LOG_CONSOLA", True))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
    )

    # ── Interruptores de mitigación (demo antes/después) ─────────────────
    mitigacion_llm01: bool = field(default_factory=lambda: _bool("MITIGACION_LLM01", True))  # sanitización
    mitigacion_llm02: bool = field(default_factory=lambda: _bool("MITIGACION_LLM02", True))  # logs/errores sin secretos
    mitigacion_llm07: bool = field(default_factory=lambda: _bool("MITIGACION_LLM07", True))  # fuga de system prompt
    mitigacion_llm10: bool = field(default_factory=lambda: _bool("MITIGACION_LLM10", True))  # rate limit + techos

    def estado_mitigaciones(self) -> dict[str, bool]:
        return {
            "LLM01_prompt_injection": self.mitigacion_llm01,
            "LLM02_sensitive_information_disclosure": self.mitigacion_llm02,
            "LLM07_system_prompt_leakage": self.mitigacion_llm07,
            "LLM10_unbounded_consumption": self.mitigacion_llm10,
        }

    def validar_para_produccion(self) -> None:
        """En producción no se permite arrancar con ninguna mitigación apagada."""
        if self.entorno == "produccion":
            apagadas = [k for k, v in self.estado_mitigaciones().items() if not v]
            if apagadas:
                raise RuntimeError(f"Mitigaciones desactivadas en producción: {apagadas}")
            if self.simular_falla_upstream:
                raise RuntimeError("SIMULAR_FALLA_UPSTREAM no está permitido en producción")
            if not self.claves_cliente_sha256:
                raise RuntimeError("No hay claves de cliente configuradas (GATEWAY_CLIENT_KEYS_SHA256)")
