"""
Pruebas de ARQUITECTURA (se ejecutan en CI):
  1. Punto único de salida: solo gateway/proveedores.py habla con proveedores.
  2. Ningún secreto con forma de API key en el código fuente del repositorio.
"""
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

HOSTS_Y_SDKS = re.compile(
    r"(api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com|/api/generate|/api/chat"
    r"|^\s*(import|from)\s+(openai|anthropic|google\.generativeai|httpx|requests)\b)",
    re.MULTILINE,
)


def test_solo_proveedores_py_contacta_a_los_proveedores():
    infractores = []
    for archivo in (RAIZ / "gateway").glob("*.py"):
        if archivo.name == "proveedores.py":
            continue
        if HOSTS_Y_SDKS.search(archivo.read_text(encoding="utf-8")):
            infractores.append(archivo.name)
    assert infractores == [], f"Llamadas directas a proveedores fuera del gateway: {infractores}"


def test_no_hay_secretos_en_el_codigo_fuente():
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "escanear_secretos.py"), "--solo-archivos"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RAIZ)
    assert r.returncode == 0, r.stdout + r.stderr
