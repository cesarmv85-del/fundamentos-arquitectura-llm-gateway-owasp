# Mismo patrón que session_4/gcp_agent_platform/sin_adk_docker/Dockerfile
FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway/ gateway/
COPY scripts/generar_clave_cliente.py scripts/

# Las API keys NO se copian a la imagen: se inyectan en tiempo de ejecución
# (--env-file, Docker secrets montados en /run/secrets + *_FILE, o Secret Manager en Cloud Run).
ENV ENTORNO=produccion \
    PORT=8080 \
    LOG_ARCHIVO=/tmp/gateway.jsonl

RUN useradd --create-home appuser
USER appuser
EXPOSE 8080
CMD ["sh", "-c", "uvicorn gateway.main:app --host 0.0.0.0 --port ${PORT} --no-server-header"]
