"""
escanear_secretos.py — Verifica el punto 3 de la "Definición de terminado":
"Ninguna API key ni dato sensible aparece en el código fuente, en el historial
de git, ni en los logs generados durante las pruebas."

Es una versión educativa de lo que hacen gitleaks / truffleHog (mismo espíritu
que verificar_api_key_no_hardcodeada() de session_4/ejemplos/01). En un
pipeline real se recomienda además gitleaks como pre-commit hook.

Uso:
    python scripts/escanear_secretos.py                 # archivos + historial git + logs/
    python scripts/escanear_secretos.py --solo-archivos # solo árbol de trabajo
Código de salida 0 = limpio, 1 = hallazgos.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Windows: la consola o una salida redirigida pueden no ser UTF-8 (cp1252).
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

RAIZ = Path(__file__).resolve().parent.parent

PATRONES = {
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai_key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{20,}"),
    "google_key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "clave_gateway": re.compile(r"gw_[A-Za-z0-9]{24,}"),
    "asignacion_literal": re.compile(r"(?i)(api_key|apikey|secret|token)\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
}
EXCLUIR_DIRS = {".git", "venv", ".venv", "node_modules", "__pycache__", ".pytest_cache", "logs"}
EXTENSIONES = {".py", ".md", ".txt", ".toml", ".yml", ".yaml", ".json", ".example", ".cfg", ".ini", ".sh", ".http", ""}


def _archivos() -> list[Path]:
    try:
        salida = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                                cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
        return [RAIZ / linea for linea in salida.splitlines() if linea]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [p for p in RAIZ.rglob("*") if p.is_file() and not (set(p.relative_to(RAIZ).parts) & EXCLUIR_DIRS)
                and p.name not in {".env", ".gw_key"}]


def _buscar(texto: str, origen: str) -> list[str]:
    hallazgos = []
    for n, linea in enumerate(texto.splitlines(), 1):
        for nombre, patron in PATRONES.items():
            if patron.search(linea):
                hallazgos.append(f"{origen}:{n}  [{nombre}]")
    return hallazgos


def escanear_archivos() -> list[str]:
    hallazgos = []
    for p in _archivos():
        if p.suffix not in EXTENSIONES and p.name not in {"Dockerfile", ".gitignore"}:
            continue
        try:
            hallazgos += _buscar(p.read_text(encoding="utf-8"), str(p.relative_to(RAIZ)))
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    return hallazgos


def escanear_historial_git() -> list[str]:
    try:
        log = subprocess.run(["git", "log", "-p", "--all", "--no-color"], cwd=RAIZ,
                             capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    lineas_agregadas = "\n".join(l[1:] for l in log.splitlines() if l.startswith("+") and not l.startswith("+++"))
    return _buscar(lineas_agregadas, "historial_git")


def escanear_logs() -> list[str]:
    hallazgos = []
    for p in (RAIZ / "logs").glob("*.jsonl"):
        hallazgos += _buscar(p.read_text(encoding="utf-8"), f"logs/{p.name}")
    return hallazgos


def main() -> int:
    solo_archivos = "--solo-archivos" in sys.argv
    hallazgos = escanear_archivos()
    if not solo_archivos:
        hallazgos += escanear_historial_git() + escanear_logs()
    if hallazgos:
        print("✗ Posibles secretos encontrados (no se imprime el valor):")
        for h in hallazgos:
            print("  -", h)
        return 1
    alcance = "archivos" if solo_archivos else "archivos + historial git + logs/"
    print(f"✓ Sin secretos detectados en {alcance}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
