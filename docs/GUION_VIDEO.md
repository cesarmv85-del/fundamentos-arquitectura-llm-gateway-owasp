# Guion del video (≤ 30 minutos)

> **Video generado:** `entregables/Video_Gateway_LLM_OWASP.mp4` (22 min 40 s, 1080p) con subtítulos en `entregables/Video_Gateway_LLM_OWASP.srt`.
> Las demos de terminal son ejecuciones reales del gateway (`uvicorn` + `curl`) capturadas y animadas; la narración usa voz sintética en español.
> Este guion sirve para regrabar el video con voz propia o en pantalla en vivo.

Duración objetivo: **26 min** (4 min de holgura). Pantalla dividida: terminal 1 = gateway, terminal 2 = ataques, editor con el código a la derecha.

## Preparación (antes de grabar)

```bash
pip install -r requirements.txt
cp .env.example .env
python scripts/generar_clave_cliente.py equipo_soporte   # copiar clave → GW_KEY; hash → .env
python scripts/generar_clave_cliente.py equipo_ventas    # copiar clave → GW_KEY_2; hash → .env (separado por coma)
export GW_KEY=gw_...  GW_KEY_2=gw_...
pytest -q                                                 # confirmar 63 passed
```
Tener abiertos: `docs/MAPEO_OWASP.md`, `gateway/sanitizacion.py`, `gateway/salida.py`, `gateway/logging_seguro.py`.

> **Tip:** reinicie el gateway antes de la demo de LLM10: las solicitudes bloqueadas por LLM01 también consumen cuota (es intencional).

---

## Bloque 1 · Contexto y elección de categorías — 0:00 a 4:00  → **Pregunta 1**

- Qué es el gateway: el único punto de salida hacia los proveedores (mostrar diagrama de `docs/ARQUITECTURA.md` y `test_solo_proveedores_py_contacta_a_los_proveedores`).
- **¿Qué categorías y por qué son las más relevantes para un gateway?**
  - LLM01 y LLM07: el gateway es quien arma el prompt → único lugar para una política uniforme de entrada y salida.
  - LLM02: es el único componente que conoce las keys de todos los proveedores → radio de impacto máximo.
  - LLM10: concentra el gasto de toda la organización.
- Mencionar las descartadas y por qué (tabla §1 del mapeo).
- Mostrar los 5 hallazgos del repositorio del curso (§2): "diseñamos pensando como atacante primero".

## Bloque 2 · LLM01 en vivo — 4:00 a 9:00  → **Pregunta 2** (burlada → bloqueada) ★

1. Terminal 1: `make linea-base M=LLM01`
2. Terminal 2: `./scripts/ataques_en_vivo.sh llm01` → **HTTP 200 "devoluciones en 365 días con reembolso doble"**. Explicar el impacto de negocio.
3. Terminal 1: `Ctrl+C` → `make protegido`
4. Terminal 2: mismo comando → **HTTP 400** en el ataque directo y en la variante zero-width; **200** en la consulta legítima.
5. `tail -n 3 logs/gateway.jsonl` → `resultado: bloqueado_llm01`, `categorias_bloqueo`, **sin el texto**.
6. Recorrer las 4 capas de `sanitizacion.py` (1 min) y el riesgo residual.

## Bloque 3 · LLM07 en vivo — 9:00 a 12:30  → **Pregunta 2**

1. `MITIGACION_LLM01=false MITIGACION_LLM07=false uvicorn gateway.main:app --port 8000`
2. `./scripts/ataques_en_vivo.sh llm07` → el system prompt completo, con el canario.
3. Reiniciar con solo `MITIGACION_LLM01=false` → respuesta reemplazada; log `fuga_bloqueada_llm07` con `motivo_fuga: canario`.
4. Explicar por qué se apaga LLM01 para esta demo: **defensa en profundidad**, la salida atrapa lo que la entrada deja pasar.

## Bloque 4 · LLM10 en vivo — 12:30 a 16:00  → **Pregunta 2**

1. `make linea-base M=LLM10` → `./scripts/ataques_en_vivo.sh llm10` → 8× `200` y `max_tokens=50000` aceptado.
2. `make protegido` → 5× `200`, 3× `429` con `Retry-After`; **otra clave desde la misma IP → 200**; `max_tokens=50000` → `422`.
3. Mostrar `pytest tests/test_llm10_rate_limit.py -k "por_ip" -v`: el contraejemplo del límite por IP (error común #2).

## Bloque 5 · LLM02 en vivo — 16:00 a 21:00  → **Preguntas 2 y 3**

1. `MITIGACION_LLM02=false SIMULAR_FALLA_UPSTREAM=error_con_clave GOOGLE_API_KEY="AIza$(openssl rand -hex 18)" uvicorn gateway.main:app --port 8000`
2. `./scripts/ataques_en_vivo.sh llm02` → la key del proveedor en la respuesta **y** el prompt con DNI + `Authorization` en el log. Señalar que es el mismo patrón de `session_4/backend/main.py` (`detail=f"...{e}"`) + `session_5` (`?key=`).
3. Reiniciar sin `MITIGACION_LLM02=false` → `503` genérico con `request_id`; log limpio pero útil.
4. **¿Qué decidimos NO registrar y por qué?** (tabla §7.1 del mapeo): prompt, respuesta, cabeceras, keys, system prompt/canario, detalle de errores. Argumento: el log tiene más lectores, copias y retención que la base de negocio; loguear "por si acaso" convierte la observabilidad en una fuga (exactamente lo que advierte LLM02). Se depura con `request_id` + `longitud_mensaje` + categorías.
5. Mostrar `logging_seguro.py`: allowlist (denegar por defecto) + redacción como red de seguridad.
6. `python scripts/escanear_secretos.py` → limpio en código, historial git y logs.

## Bloque 6 · Degradación controlada — 21:00 a 23:00

1. `make falla-upstream F=error_500` → `503` sin traza.
2. `SIMULAR_FALLA_UPSTREAM=timeout PROVEEDOR_RESPALDO=simulado_respaldo uvicorn …` → `200` con `degradado: true`.
3. `ENTORNO=produccion MITIGACION_LLM01=false uvicorn …` → el gateway **se niega a arrancar**.

## Bloque 7 · Evidencia automatizada y cierre — 23:00 a 26:00  → **Pregunta 4**

1. `pytest -v` (63 en verde) y `python scripts/demo_antes_despues.py` (tabla antes/después + reporte).
2. **Quinta mitigación con más tiempo**: presupuesto de **tokens/costo por clave** (el rate limit cuenta solicitudes, pero el costo lo definen los tokens), y luego LLM05 (salida como texto no confiable).
3. Cierre: diferencia entre mitigación "de papel" y mitigación demostrada — cada control de este gateway tiene una prueba que falla si se apaga.
