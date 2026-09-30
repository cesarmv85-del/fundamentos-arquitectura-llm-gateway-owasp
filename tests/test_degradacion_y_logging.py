"""
Requisitos no funcionales:
  - Degradación controlada ante fallos upstream (sin trazas internas al cliente).
  - Logging JSON estructurado con allowlist + redacción.
"""
import json
import logging

from gateway.logging_seguro import FormateadorJSONSeguro, redactar
from tests.conftest import CLAVE_OPENAI_FALSA, cabeceras, eventos


def test_timeout_upstream_devuelve_504_claro(fabrica):
    cliente, _ = fabrica(simular_falla_upstream="timeout")
    r = cliente.post("/v1/chat", json={"mensaje": "hola"}, headers=cabeceras())
    assert r.status_code == 504
    assert r.json()["error"] == "upstream_timeout" and "Intente nuevamente" in r.json()["mensaje"]


def test_linea_base_error_500_expone_traza(fabrica):
    cliente, _ = fabrica(mitigacion_llm02=False, simular_falla_upstream="error_500")
    r = cliente.post("/v1/chat", json={"mensaje": "hola"}, headers=cabeceras())
    assert "Traceback" in r.text


def test_error_500_upstream_no_expone_traza(fabrica):
    cliente, log = fabrica(simular_falla_upstream="error_500")
    r = cliente.post("/v1/chat", json={"mensaje": "hola"}, headers=cabeceras())
    assert r.status_code == 503 and "Traceback" not in r.text
    ev = [e for e in eventos(log) if e.get("resultado") == "error_upstream"][0]
    assert ev["tipo_error"] == "no_disponible" and "Traceback" not in json.dumps(ev)


def test_fallback_a_proveedor_de_respaldo(fabrica):
    cliente, log = fabrica(simular_falla_upstream="timeout", proveedor_respaldo="simulado_respaldo")
    r = cliente.post("/v1/chat", json={"mensaje": "¿Puedo devolver algo?"}, headers=cabeceras())
    assert r.status_code == 200 and r.json()["degradado"] is True
    assert r.json()["proveedor"] == "simulado_respaldo"
    ev = [e for e in eventos(log) if e.get("degradado")][0]
    assert ev["proveedor_fallido"] == "simulado" and ev["tipo_error"] == "timeout"


def test_sin_clave_de_cliente_401_generico(fabrica):
    cliente, _ = fabrica()
    r = cliente.post("/v1/chat", json={"mensaje": "hola"})
    assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "Bearer"
    r2 = cliente.post("/v1/chat", json={"mensaje": "hola"}, headers=cabeceras("gw_inexistente123456"))
    assert r2.status_code == 401 and r2.json()["mensaje"] == r.json()["mensaje"]  # no revela si la clave existe


def test_toda_respuesta_lleva_request_id(fabrica):
    cliente, _ = fabrica()
    r = cliente.post("/v1/chat", json={"mensaje": "hola"}, headers=cabeceras())
    assert r.headers["X-Request-ID"] == r.json()["request_id"]


# ── Formateador ────────────────────────────────────────────────────────────

def _formatear(campos: dict) -> dict:
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "evento", None, None)
    rec.campos = campos
    return json.loads(FormateadorJSONSeguro().format(rec))


def test_allowlist_descarta_campos_no_permitidos():
    salida = _formatear({"evento": "x", "prompt": "secreto", "respuesta_modelo": "y", "headers": {"a": 1}, "latencia_ms": 5})
    assert "prompt" not in salida and "respuesta_modelo" not in salida and "headers" not in salida
    assert salida["latencia_ms"] == 5


def test_redaccion_de_patrones_de_secretos():
    texto = f"fallo con {CLAVE_OPENAI_FALSA} y Bearer abcdefghijkl y ?key=XYZ123 y ana@x.pe"
    red = redactar(texto)
    assert CLAVE_OPENAI_FALSA not in red and "abcdefghijkl" not in red and "XYZ123" not in red and "ana@x.pe" not in red
