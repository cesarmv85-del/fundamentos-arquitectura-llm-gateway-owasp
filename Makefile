# Atajos para desarrollo y para grabar el video.
# Uso: make instalar | make protegido | make linea-base M=LLM01 | make test | make evidencia | make secretos

PY ?= python3
PUERTO ?= 8000
M ?= LLM01

instalar:
	$(PY) -m pip install -r requirements.txt

protegido:          ## Gateway con TODAS las mitigaciones activas
	uvicorn gateway.main:app --port $(PUERTO)

linea-base:         ## Gateway con UNA mitigación apagada: make linea-base M=LLM07
	MITIGACION_$(M)=false uvicorn gateway.main:app --port $(PUERTO)

falla-upstream:     ## Proveedor simulado caído (F=timeout|error_500|error_con_clave)
	SIMULAR_FALLA_UPSTREAM=$(or $(F),timeout) uvicorn gateway.main:app --port $(PUERTO)

test:
	$(PY) -m pytest -v

evidencia:          ## Genera docs/evidencias/REPORTE_EVIDENCIA.md
	$(PY) scripts/demo_antes_despues.py

secretos:           ## Código + historial git + logs/
	$(PY) scripts/escanear_secretos.py

.PHONY: instalar protegido linea-base falla-upstream test evidencia secretos
