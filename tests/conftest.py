"""
Fixtures compartidas. Cada prueba construye su PROPIA app con `crear_app(cfg)`,
de modo que la misma prueba puede ejecutarse con la mitigación APAGADA (línea
base) y ENCENDIDA (protegido) — ese contraste es la evidencia que pide el
proyecto.

Las claves falsas se ARMAN EN TIEMPO DE EJECUCIÓN (concatenando) para que el
propio código fuente de las pruebas no contenga nada con forma de API key y el
escáner de secretos (scripts/escanear_secretos.py) quede limpio.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway.config import Configuracion  # noqa: E402
from gateway.main import crear_app  # noqa: E402

CLAVE_SOPORTE = "gw_" + "soporte" + "0123456789abcdef"
CLAVE_VENTAS = "gw_" + "ventas" + "fedcba9876543210"
CLAVE_GOOGLE_FALSA = "AIza" + "Sy" + "FALSA" + "0" * 28
CLAVE_OPENAI_FALSA = "sk-" + "proj-" + "FALSA" + "1" * 30


def _sha(c: str) -> str:
    return hashlib.sha256(c.encode()).hexdigest()


@pytest.fixture
def fabrica(tmp_path):
    """fabrica(**overrides) -> (TestClient, ruta_log)"""

    def _crear(**overrides):
        from pydantic import SecretStr
        log = tmp_path / f"gateway_{len(list(tmp_path.iterdir()))}.jsonl"
        base = dict(
            entorno="pruebas",
            proveedor_principal="simulado",
            proveedor_respaldo="",
            claves_cliente_sha256={_sha(CLAVE_SOPORTE): "soporte", _sha(CLAVE_VENTAS): "ventas"},
            google_api_key=SecretStr(CLAVE_GOOGLE_FALSA),
            openai_api_key=None,
            anthropic_api_key=None,
            rate_limit="5/minute",
            rate_limit_por="clave",
            log_archivo=str(log),
            log_consola=False,
            simular_falla_upstream="",
        )
        base.update(overrides)
        cfg = Configuracion(**base)
        return TestClient(crear_app(cfg), raise_server_exceptions=False), log

    return _crear


def cabeceras(clave: str = CLAVE_SOPORTE) -> dict:
    return {"Authorization": f"Bearer {clave}"}


def leer_log(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8") if ruta.exists() else ""


def eventos(ruta: Path) -> list[dict]:
    return [json.loads(linea) for linea in leer_log(ruta).splitlines() if linea.strip()]
