"""
OWASP LLM02:2025 Sensitive Information Disclosure — evidencia ANTES / DESPUÉS.

Casos de ataque / mal uso:
  A. El proveedor upstream falla y su mensaje de error trae la API key en la
     URL (patrón real de httpx con `?key=`, como en session_5/proveedores.py).
     El backend de la Sesión 4 hace `HTTPException(502, detail=f"...{e}")`
     → la key del PROVEEDOR llega al CLIENTE.
  B. "Loguear todo por si acaso": el log guarda cabeceras (Authorization con la
     clave gw_ del cliente) y el prompt completo (datos personales).
"""
from pydantic import SecretStr

from gateway.config import Configuracion, _secreto
from tests.conftest import CLAVE_GOOGLE_FALSA, CLAVE_SOPORTE, cabeceras, leer_log

PROMPT_CON_PII = "Soy Juana Pérez, DNI 45678912, correo juana.perez@correo.pe. ¿Dónde está mi pedido?"


# ── A. Fuga de la key del proveedor por mensajes de error ───────────────────

def test_linea_base_error_upstream_expone_la_api_key_al_cliente_y_al_log(fabrica):
    cliente, log = fabrica(mitigacion_llm02=False, simular_falla_upstream="error_con_clave")
    r = cliente.post("/v1/chat", json={"mensaje": "hola"}, headers=cabeceras())
    assert CLAVE_GOOGLE_FALSA in r.text          # la key del proveedor llegó al cliente
    assert CLAVE_GOOGLE_FALSA in leer_log(log)   # y quedó escrita en el log


def test_con_mitigacion_error_upstream_no_expone_la_api_key(fabrica):
    cliente, log = fabrica(mitigacion_llm02=True, simular_falla_upstream="error_con_clave")
    r = cliente.post("/v1/chat", json={"mensaje": "hola"}, headers=cabeceras())
    assert r.status_code == 503
    assert CLAVE_GOOGLE_FALSA not in r.text and "googleapis" not in r.text
    assert CLAVE_GOOGLE_FALSA not in leer_log(log)
    assert "request_id" in r.json()  # correlación para soporte, sin detalles internos


# ── B. Fuga por logging excesivo ────────────────────────────────────────────

def test_linea_base_log_contiene_prompt_pii_y_clave_del_cliente(fabrica):
    cliente, log = fabrica(mitigacion_llm02=False)
    cliente.post("/v1/chat", json={"mensaje": PROMPT_CON_PII}, headers=cabeceras())
    contenido = leer_log(log)
    assert "45678912" in contenido and "juana.perez@correo.pe" in contenido
    assert CLAVE_SOPORTE in contenido


def test_con_mitigacion_log_no_contiene_prompt_pii_ni_claves(fabrica):
    cliente, log = fabrica(mitigacion_llm02=True)
    cliente.post("/v1/chat", json={"mensaje": PROMPT_CON_PII}, headers=cabeceras())
    contenido = leer_log(log)
    for prohibido in ("45678912", "juana.perez", "Juana", CLAVE_SOPORTE, CLAVE_GOOGLE_FALSA, "Authorization"):
        assert prohibido not in contenido, prohibido
    # …pero sigue siendo útil para auditoría
    for util in ('"latencia_ms"', '"estado_http": 200', '"cliente_id": "soporte#', '"longitud_mensaje"'):
        assert util in contenido, util


# ── Manejo de credenciales en código ────────────────────────────────────────

def test_secretstr_no_revela_la_key_en_repr_ni_str():
    cfg = Configuracion(openai_api_key=SecretStr("valor-super-secreto"))
    assert "valor-super-secreto" not in repr(cfg)
    assert "valor-super-secreto" not in str(cfg.openai_api_key)


def test_la_key_se_puede_leer_desde_archivo_montado(tmp_path, monkeypatch):
    archivo = tmp_path / "openai_key"
    archivo.write_text("desde-secret-manager\n")
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(archivo))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _secreto("OPENAI_API_KEY").get_secret_value() == "desde-secret-manager"


def test_proveedor_real_sin_key_degrada_con_mensaje_generico(fabrica):
    cliente, _ = fabrica(proveedor_principal="openai", openai_api_key=None)
    r = cliente.post("/v1/chat", json={"mensaje": "hola"}, headers=cabeceras())
    assert r.status_code == 502 and "API key" not in r.text


def test_produccion_no_arranca_con_mitigaciones_apagadas():
    import pytest
    with pytest.raises(RuntimeError):
        Configuracion(entorno="produccion", mitigacion_llm02=False, claves_cliente_sha256={"x" * 64: "a"}).validar_para_produccion()
