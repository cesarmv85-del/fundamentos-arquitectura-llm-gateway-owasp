#!/usr/bin/env bash
# instalar.sh — Instalación automática del Gateway LLM en Linux.
#
# Uso (desde la raíz del repositorio):
#     bash scripts/instalar.sh                 # instala, configura, emite una clave y ejecuta las pruebas
#     bash scripts/instalar.sh --sin-pruebas   # omite las pruebas
#     CLIENTE=equipo_ventas bash scripts/instalar.sh   # nombre del primer cliente (por defecto: equipo_demo)
#     PYTHON=python3.11 bash scripts/instalar.sh       # forzar un intérprete concreto
#
# Es IDEMPOTENTE: se puede ejecutar varias veces. No sobrescribe un .env
# existente ni emite una clave nueva si ya hay clientes configurados.
#
# Qué hace:
#   1. Comprueba los prerrequisitos (Linux, Python 3.10+, módulo venv, git, curl).
#   2. Crea el entorno virtual venv/ e instala requirements.txt.
#   3. Crea .env a partir de .env.example.
#   4. Emite la primera clave de cliente, escribe su hash en .env y guarda la
#      clave en .gw_key (permisos 600, ignorado por git) — solo si no hay clientes.
#   5. Ejecuta las 63 pruebas y el escáner de secretos.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
CLIENTE="${CLIENTE:-equipo_demo}"
PRUEBAS=1
[[ "${1:-}" == "--sin-pruebas" ]] && PRUEBAS=0

ok()    { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
info()  { printf '\033[1;34m→\033[0m %s\n' "$*"; }
falla() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── 1. Prerrequisitos ────────────────────────────────────────────────────────
info "Comprobando prerrequisitos"
[[ "$(uname -s)" == "Linux" ]] || falla "Este instalador es para Linux (detectado: $(uname -s))."

PY=""
for candidato in ${PYTHON:-} python3.12 python3.13 python3.11 python3.10 python3; do
  if command -v "$candidato" >/dev/null 2>&1 \
     && "$candidato" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$candidato"; break
  fi
done
[[ -n "$PY" ]] || falla "Se requiere Python 3.10 o superior. En Ubuntu/Debian: sudo apt-get install -y python3 python3-venv python3-pip"
"$PY" -c 'import venv, ensurepip' 2>/dev/null \
  || falla "Falta el módulo venv de Python. En Ubuntu/Debian: sudo apt-get install -y python3-venv"
for herramienta in git curl; do
  command -v "$herramienta" >/dev/null 2>&1 || falla "Falta '$herramienta'. En Ubuntu/Debian: sudo apt-get install -y $herramienta"
done
ok "$("$PY" --version) · git $(git --version | awk '{print $3}') · curl disponible"

# ── 2. Entorno virtual y dependencias ────────────────────────────────────────
if [[ ! -x venv/bin/python ]]; then
  info "Creando entorno virtual en venv/"
  "$PY" -m venv venv
fi
info "Instalando dependencias (requirements.txt)"
venv/bin/python -m pip install --quiet --upgrade pip
venv/bin/python -m pip install --quiet -r requirements.txt
ok "Dependencias instaladas en venv/"

# ── 3. Configuración ─────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  ok "Archivo .env creado a partir de .env.example"
else
  ok "Se conserva el archivo .env existente"
fi

# ── 4. Primera clave de cliente ──────────────────────────────────────────────
hash_en_env="$(grep -E '^GATEWAY_CLIENT_KEYS_SHA256=' .env | cut -d= -f2- || true)"
if [[ -n "${GATEWAY_CLIENT_KEYS_SHA256:-}" ]]; then
  ok "Clientes definidos por variable de entorno (por ejemplo, un secreto de Codespaces)"
elif [[ -n "$hash_en_env" ]]; then
  ok "Ya hay clientes configurados en .env; no se emite una clave nueva"
else
  salida="$(venv/bin/python scripts/generar_clave_cliente.py "$CLIENTE")"
  clave="$(printf '%s\n' "$salida" | grep -oE 'gw_[A-Za-z0-9]+' | head -n 1)"
  linea="$(printf '%s\n' "$salida" | grep -oE "^ *${CLIENTE}:[0-9a-f]{64}" | tr -d ' ')"
  [[ -n "$clave" && -n "$linea" ]] || falla "No se pudo generar la clave de cliente."
  sed -i "s|^GATEWAY_CLIENT_KEYS_SHA256=.*|GATEWAY_CLIENT_KEYS_SHA256=${linea}|" .env
  ( umask 177; printf '%s\n' "$clave" > .gw_key )
  ok "Clave emitida para '${CLIENTE}': hash en .env, clave en .gw_key (permisos 600, ignorado por git)"
fi

# ── 5. Verificación ──────────────────────────────────────────────────────────
if [[ "$PRUEBAS" == "1" ]]; then
  info "Ejecutando las pruebas"
  venv/bin/python -m pytest -o addopts="" -q -p no:cacheprovider 2>&1 | tail -n 1
  venv/bin/python scripts/escanear_secretos.py
fi

cat <<'FIN'

Instalación completa. Siguientes pasos:

  source venv/bin/activate                    # activar el entorno en esta terminal
  uvicorn gateway.main:app --port 8000        # arrancar el gateway   (o: make protegido)

En otra terminal:

  export GW_KEY=$(cat .gw_key)
  curl -s http://localhost:8000/health
  curl -s -X POST http://localhost:8000/v1/chat \
    -H "Authorization: Bearer $GW_KEY" -H "Content-Type: application/json" \
    -d '{"mensaje":"¿Puedo devolver un producto que compré hace 20 días?"}'
FIN
