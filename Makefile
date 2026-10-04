# Atajos para Linux. Usan el entorno virtual venv/ si existe.
#
#   make instalar                 instala todo (scripts/instalar.sh)
#   make protegido                arranca el gateway con todas las mitigaciones
#   make linea-base M=LLM01       arranca con UNA mitigación apagada (LLM01, LLM02, LLM07, LLM10)
#   make falla-upstream F=timeout simula una caída del proveedor (timeout | error_500 | error_con_clave)
#   make iniciar / detener / estado   gateway en segundo plano
#   make verificar                prueba de humo: arranca, consulta y detiene
#   make test / evidencia / secretos  pruebas, reporte antes/después y escáner

BIN    := $(if $(wildcard venv/bin/python),venv/bin/,)
PY     := $(BIN)python$(if $(BIN),,3)
PUERTO ?= 8000
HOST   ?= 127.0.0.1
M      ?= LLM01
F      ?= timeout

instalar:
	bash scripts/instalar.sh

protegido:
	$(BIN)uvicorn gateway.main:app --host $(HOST) --port $(PUERTO)

linea-base:
	MITIGACION_$(M)=false $(BIN)uvicorn gateway.main:app --host $(HOST) --port $(PUERTO)

falla-upstream:
	SIMULAR_FALLA_UPSTREAM=$(F) $(BIN)uvicorn gateway.main:app --host $(HOST) --port $(PUERTO)

iniciar:
	@mkdir -p logs
	@nohup $(BIN)uvicorn gateway.main:app --host $(HOST) --port $(PUERTO) > logs/servidor.out 2>&1 & echo $$! > .gateway.pid
	@sleep 2 && echo "Gateway en segundo plano (PID $$(cat .gateway.pid)) · salida en logs/servidor.out"

detener:
	@if [ -f .gateway.pid ]; then pid=$$(cat .gateway.pid); kill $$pid 2>/dev/null; \
	  for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 $$pid 2>/dev/null || break; sleep 0.5; done; \
	  rm -f .gateway.pid; echo "Gateway detenido"; \
	else echo "No hay un gateway iniciado con 'make iniciar'"; fi

estado:
	@curl -s --max-time 3 http://localhost:$(PUERTO)/health || echo "El gateway no responde en el puerto $(PUERTO)"
	@echo

test:
	$(PY) -m pytest -v

evidencia:
	$(PY) scripts/demo_antes_despues.py

secretos:
	$(PY) scripts/escanear_secretos.py

verificar:
	bash scripts/prueba_humo.sh

.PHONY: instalar protegido linea-base falla-upstream iniciar detener estado test evidencia secretos verificar
