"""
generar_clave_cliente.py — Emite una clave de cliente del gateway.

    python scripts/generar_clave_cliente.py equipo_soporte

Imprime:
  - la CLAVE (entregarla una sola vez al equipo consumidor; el gateway no la guarda)
  - la línea para GATEWAY_CLIENT_KEYS_SHA256 en .env (solo el hash SHA-256)
"""
import hashlib
import re
import secrets
import sys

if len(sys.argv) != 2 or not re.fullmatch(r"[a-z0-9_]{3,32}", sys.argv[1]):
    sys.exit("Uso: python scripts/generar_clave_cliente.py <nombre_cliente>  (a-z, 0-9, _)")

nombre = sys.argv[1]
clave = "gw_" + secrets.token_urlsafe(32).replace("-", "").replace("_", "")[:40]
digest = hashlib.sha256(clave.encode()).hexdigest()
print(f"Clave para '{nombre}' (guárdela ahora, no se vuelve a mostrar):\n  {clave}\n")
print("Agregue a GATEWAY_CLIENT_KEYS_SHA256 en .env (separar clientes con coma):")
print(f"  {nombre}:{digest}")
