"""
OWASP LLM10:2025 Unbounded Consumption — evidencia ANTES / DESPUÉS.

Casos de ataque:
  A. Ráfaga: un cliente envía 12 solicitudes en segundos (abuso de costo / DoS).
  B. Tokens: pide max_tokens=50000 para inflar la factura de una sola llamada.
  C. Cuerpo gigante: envía 1 MB de texto.
  D. (Error común del enunciado) Rate limit por IP: dos equipos detrás del
     mismo NAT/proxy corporativo se bloquean mutuamente; y un solo abusador
     con varias IP evade el límite. Por eso el límite es POR CLAVE.
"""
from tests.conftest import CLAVE_VENTAS, cabeceras

MSG = {"mensaje": "¿Cuál es el horario de atención?"}


def test_linea_base_sin_rate_limit_todas_las_solicitudes_pasan(fabrica):
    cliente, _ = fabrica(mitigacion_llm10=False)
    codigos = [cliente.post("/v1/chat", json=MSG, headers=cabeceras()).status_code for _ in range(12)]
    assert codigos == [200] * 12


def test_con_rate_limit_la_sexta_solicitud_es_rechazada(fabrica):
    cliente, log = fabrica(mitigacion_llm10=True, rate_limit="5/minute")
    codigos = [cliente.post("/v1/chat", json=MSG, headers=cabeceras()).status_code for _ in range(6)]
    assert codigos == [200] * 5 + [429]
    r = cliente.post("/v1/chat", json=MSG, headers=cabeceras())
    assert r.headers["Retry-After"] == "60"
    assert r.json()["error"] == "limite_excedido"
    assert "rate_limit_excedido" in log.read_text()


def test_rate_limit_es_por_clave_no_por_ip(fabrica):
    """Mismo IP (TestClient), dos claves: agotar 'soporte' NO afecta a 'ventas'."""
    cliente, _ = fabrica(rate_limit="5/minute", rate_limit_por="clave")
    for _ in range(5):
        cliente.post("/v1/chat", json=MSG, headers=cabeceras())
    assert cliente.post("/v1/chat", json=MSG, headers=cabeceras()).status_code == 429
    assert cliente.post("/v1/chat", json=MSG, headers=cabeceras(CLAVE_VENTAS)).status_code == 200


def test_contraejemplo_rate_limit_por_ip_bloquea_a_otro_equipo(fabrica):
    """Demuestra el error común: con límite por IP, 'ventas' paga el abuso de 'soporte'."""
    cliente, _ = fabrica(rate_limit="5/minute", rate_limit_por="ip")
    for _ in range(5):
        cliente.post("/v1/chat", json=MSG, headers=cabeceras())
    assert cliente.post("/v1/chat", json=MSG, headers=cabeceras(CLAVE_VENTAS)).status_code == 429


def test_linea_base_acepta_max_tokens_desmedido(fabrica):
    cliente, _ = fabrica(mitigacion_llm10=False)
    r = cliente.post("/v1/chat", json={**MSG, "max_tokens": 50000}, headers=cabeceras())
    assert r.status_code == 200


def test_con_mitigacion_max_tokens_sobre_el_techo_es_rechazado(fabrica):
    cliente, _ = fabrica(mitigacion_llm10=True, max_tokens_techo=512)
    r = cliente.post("/v1/chat", json={**MSG, "max_tokens": 50000}, headers=cabeceras())
    assert r.status_code == 422
    assert r.json()["detalles"][0]["campo"] == "max_tokens"


def test_con_mitigacion_cuerpo_gigante_es_rechazado_con_413(fabrica):
    cliente, _ = fabrica(mitigacion_llm10=True, max_bytes_body=16384)
    r = cliente.post("/v1/chat", json={"mensaje": "x" * 1_000_000}, headers=cabeceras())
    assert r.status_code == 413


def test_error_422_no_refleja_el_input_del_usuario(fabrica):
    cliente, _ = fabrica(mitigacion_llm10=True, max_caracteres_mensaje=100)
    secreto = "DATO-PERSONAL-" + "z" * 200
    r = cliente.post("/v1/chat", json={"mensaje": secreto}, headers=cabeceras())
    assert r.status_code == 422 and "DATO-PERSONAL" not in r.text
