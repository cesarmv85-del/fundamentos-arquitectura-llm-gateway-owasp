# Manual de instalación

Versión 1.0 · Octubre 2026 · Autor: César · Repositorio: `github.com/cesarmv85-del/fundamentos-arquitectura-llm-gateway-owasp`

Este manual explica cómo instalar, configurar y verificar el Gateway LLM en un equipo local, cómo conectarlo a un proveedor real de modelos y qué se necesita para llevarlo a producción. Está dirigido a quien administra el gateway. Para el uso diario (enviar consultas, leer los registros, emitir claves) consulte el **Manual de usuario**.

## 1. Qué se instala

El gateway es un servicio web (FastAPI) que recibe todas las consultas a modelos de lenguaje de la organización por un único punto de entrada, `POST /v1/chat`, y aplica cuatro controles de seguridad del marco OWASP Top 10 for LLM Applications 2025 antes y después de llamar al proveedor.

| Componente | Descripción |
|---|---|
| `gateway/` | Código del servicio |
| `scripts/` | Emisión de claves, demostración antes/después, escáner de secretos |
| `tests/` | 63 pruebas automáticas |
| `.env` | Configuración local (se crea durante la instalación; nunca se sube a GitHub) |
| `logs/gateway.jsonl` | Registro de auditoría (se crea al arrancar) |

La instalación básica no requiere API keys ni conexión a ningún proveedor: usa un **proveedor simulado** que permite comprobar todo el funcionamiento sin costo.

## 2. Requisitos previos

| Requisito | Detalle |
|---|---|
| Sistema operativo | Linux, macOS o Windows 10/11 |
| Python | 3.11 o 3.12 |
| Git | Cualquier versión reciente (en Windows incluye **Git Bash**) |
| Espacio en disco | 150 MB aproximadamente |
| Red | Acceso a internet para descargar las dependencias |
| Puerto | 8000 libre (se puede cambiar) |

Opcionales, según el uso:

| Opcional | Para qué |
|---|---|
| API key de OpenAI, Anthropic o Google | Usar un modelo real en lugar del simulado |
| Ollama | Usar un modelo local sin costo |
| Docker | Ejecutar el gateway como contenedor |
| Redis | Compartir el contador de cuotas entre varias réplicas |

**Plataformas verificadas:** la instalación, las pruebas y los ejemplos de este manual se ejecutaron en Linux (Ubuntu) con Python 3.11 y 3.12. En Windows y macOS se usan los comandos equivalentes que se indican en cada paso.

Compruebe los requisitos antes de empezar:

```bash
python --version
git --version
```

> **Nota para Windows:** si `python` no se reconoce, instale Python desde python.org y marque la casilla "Add python.exe to PATH". En Linux y macOS el comando puede ser `python3` o `python3.12`.

## 3. Instalación paso a paso

Hay tres terminales posibles. Use siempre la misma durante toda la instalación.

| Terminal | Cuándo usarla |
|---|---|
| Linux / macOS | Terminal del sistema |
| Windows · Git Bash | **Recomendada en Windows**: acepta los mismos comandos que Linux y permite ejecutar el script de demostración `.sh` |
| Windows · PowerShell | Alternativa; algunos comandos cambian |

### Paso 1 · Obtener el código

```bash
git clone https://github.com/cesarmv85-del/fundamentos-arquitectura-llm-gateway-owasp.git
cd fundamentos-arquitectura-llm-gateway-owasp
```

Sin Git: en la página del repositorio, botón **Code → Download ZIP**, y descomprima la carpeta.

### Paso 2 · Crear el entorno virtual e instalar dependencias

El entorno virtual aísla las librerías del gateway de las del resto del equipo.

Linux / macOS:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Windows · Git Bash:

```bash
python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt
```

Windows · PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> **Nota:** si PowerShell bloquea la activación por la política de ejecución de scripts, ejecute antes `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` y repita el comando.

Al terminar, el indicador de la terminal muestra `(venv)`. Cada vez que abra una terminal nueva debe **activar de nuevo** el entorno con el segundo comando.

### Paso 3 · Crear el archivo de configuración

Linux / macOS / Git Bash:

```bash
cp .env.example .env
```

Windows · PowerShell:

```powershell
Copy-Item .env.example .env
```

El archivo `.env` ya trae valores válidos para funcionar con el proveedor simulado. Solo falta agregar una clave de cliente (paso siguiente).

### Paso 4 · Emitir la primera clave de cliente

Toda aplicación que consuma el gateway necesita su propia clave. El gateway **no guarda la clave**, solo su huella (hash SHA-256).

```bash
python scripts/generar_clave_cliente.py equipo_soporte
```

Salida:

```text
Clave para 'equipo_soporte' (guárdela ahora, no se vuelve a mostrar):
  gw_ZCrh1e…

Agregue a GATEWAY_CLIENT_KEYS_SHA256 en .env (separar clientes con coma):
  equipo_soporte:84d6c15ce47267c4…
```

Haga dos cosas con esa salida:

- **Guarde la clave** `gw_…` en un lugar seguro (un gestor de contraseñas). Es la que usará la aplicación cliente.
- **Copie la última línea completa** (`equipo_soporte:…`) en el archivo `.env`, a la derecha de `GATEWAY_CLIENT_KEYS_SHA256=`.

El resultado en `.env` debe quedar así, en una sola línea y sin espacios:

```text
GATEWAY_CLIENT_KEYS_SHA256=equipo_soporte:84d6c15ce47267c4…(64 caracteres en total)
```

Para editar el archivo: `nano .env` (Linux/macOS) o `notepad .env` (Windows).

### Paso 5 · Arrancar el gateway

```bash
uvicorn gateway.main:app --port 8000
```

Salida esperada:

```text
{"evento": "gateway_iniciado", "mitigaciones_activas": {"LLM01_prompt_injection": true, "LLM02_sensitive_information_disclosure": true, "LLM07_system_prompt_leakage": true, "LLM10_unbounded_consumption": true}, "nivel": "INFO", "proveedor": "simulado", ...}
INFO:     Started server process [967]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

La primera línea confirma que las **cuatro mitigaciones están activas**. Deje esta terminal abierta: el gateway corre mientras esté abierta. Para detenerlo, pulse `Ctrl + C`.

### Paso 6 · Verificar la instalación

Abra una **segunda terminal** en la misma carpeta y active el entorno virtual.

**a) El servicio responde.** Abra `http://localhost:8000/health` en el navegador, o ejecute:

```bash
curl http://localhost:8000/health
```

Respuesta: `{"status":"ok"}`

**b) Primera consulta con la clave.** Guarde la clave en una variable y envíe una consulta.

Linux / macOS / Git Bash:

```bash
export GW_KEY=gw_...su_clave...
curl -s -X POST http://localhost:8000/v1/chat \
  -H "Authorization: Bearer $GW_KEY" -H "Content-Type: application/json" \
  -d '{"mensaje":"¿Puedo devolver un producto que compré hace 20 días?"}'
```

Windows · PowerShell:

```powershell
$env:GW_KEY = "gw_...su_clave..."
$cabeceras = @{ Authorization = "Bearer $env:GW_KEY" }
$cuerpo = @{ mensaje = "¿Puedo devolver un producto que compré hace 20 días?" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/v1/chat -Method Post -Headers $cabeceras `
  -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($cuerpo))
```

Respuesta:

```text
{"request_id":"91250ba8f5ee4766","respuesta":"Puedes devolver tu producto dentro de 30 días desde la compra, con boleta y sin uso.","proveedor":"simulado","modelo":"modelo-ingenuo-v1","simulado":true,"degradado":false,"tokens_entrada":148,"tokens_salida":21,"latencia_ms":0}
```

**c) Las pruebas automáticas pasan.**

```bash
python -m pytest
python scripts/escanear_secretos.py
```

Resultado esperado: `63 passed` (puede añadir `1 warning`, que es inofensivo) y `✓ Sin secretos detectados en archivos + historial git + logs/`.

**d) Documentación interactiva.** En `http://localhost:8000/docs` puede probar la API desde el navegador: pulse **Authorize** y pegue su clave. Solo está disponible fuera de producción y necesita conexión a internet para cargar.

Si los cuatro puntos funcionan, la instalación está completa.

## 4. Configuración

Toda la configuración está en el archivo `.env`. **Reinicie el gateway** después de cada cambio (`Ctrl + C` y volver a arrancar).

### 4.1 Proveedores

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `PROVEEDOR_PRINCIPAL` | `simulado` | `simulado`, `openai`, `anthropic`, `google` u `ollama` |
| `PROVEEDOR_RESPALDO` | (vacío) | Proveedor al que se recurre si el principal falla |
| `OPENAI_API_KEY` · `ANTHROPIC_API_KEY` · `GOOGLE_API_KEY` | (vacío) | Clave del proveedor correspondiente |
| `MODELO_OPENAI` | `gpt-4o-mini` | Modelo a usar con OpenAI |
| `MODELO_ANTHROPIC` | `claude-haiku-4-5` | Modelo a usar con Anthropic |
| `MODELO_GOOGLE` | `gemini-2.5-flash` | Modelo a usar con Google |
| `MODELO_OLLAMA` | `llama3.2` | Modelo local de Ollama |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Dirección del servidor Ollama |
| `TIMEOUT_UPSTREAM_SEG` | `20` | Segundos de espera máxima al proveedor |

### 4.2 Clientes y límites de consumo

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `GATEWAY_CLIENT_KEYS_SHA256` | (vacío) | Clientes autorizados: `nombre:hash`, separados por coma |
| `RATE_LIMIT` | `5/minute` | Solicitudes permitidas por clave. Otros ejemplos: `100/hour`, `20/minute` |
| `RATE_LIMIT_POR` | `clave` | Deje `clave`. El valor `ip` existe solo para demostrar por qué no conviene |
| `RATE_LIMIT_STORAGE_URI` | `memory://` | Dónde se guarda el contador. Con varias réplicas use `redis://servidor:6379` |
| `MAX_TOKENS_TECHO` | `512` | Máximo de tokens de salida que puede pedir una solicitud |
| `MAX_CARACTERES_MENSAJE` | `4000` | Largo máximo del mensaje |
| `MAX_BYTES_BODY` | `16384` | Tamaño máximo de la solicitud completa |

### 4.3 Registros, navegador y entorno

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `ENTORNO` | `desarrollo` | Con `produccion` se activan las exigencias de la sección 7 |
| `LOG_ARCHIVO` | `logs/gateway.jsonl` | Archivo del registro de auditoría |
| `LOG_CONSOLA` | `true` | Mostrar también los registros en la terminal |
| `CORS_ORIGINS` | `http://localhost:5173` | Sitios web autorizados a llamar al gateway desde un navegador |

### 4.4 Interruptores de demostración

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `MITIGACION_LLM01` · `LLM02` · `LLM07` · `LLM10` | `true` | Apagar una mitigación para mostrar el ataque sin protección |
| `SIMULAR_FALLA_UPSTREAM` | (vacío) | `timeout`, `error_500` o `error_con_clave`: simula una caída del proveedor |

> **Importante:** estos interruptores existen solo para la demostración antes/después. Con `ENTORNO=produccion` el gateway se niega a arrancar si alguno está apagado.

## 5. Conectar un proveedor real

Edite `.env`, indique el proveedor y su clave, y reinicie.

OpenAI:

```text
PROVEEDOR_PRINCIPAL=openai
OPENAI_API_KEY=su_clave_de_openai
```

Anthropic:

```text
PROVEEDOR_PRINCIPAL=anthropic
ANTHROPIC_API_KEY=su_clave_de_anthropic
```

Google Gemini:

```text
PROVEEDOR_PRINCIPAL=google
GOOGLE_API_KEY=su_clave_de_google
```

Ollama (local, sin clave). Instale Ollama, descargue el modelo con `ollama pull llama3.2` y configure:

```text
PROVEEDOR_PRINCIPAL=ollama
```

Recomendaciones:

- **Configure un respaldo.** Por ejemplo `PROVEEDOR_RESPALDO=ollama`: si el principal falla, el gateway responde con el respaldo y marca la respuesta con `degradado: true`.
- **No escriba la clave en el código ni la suba a GitHub.** El archivo `.env` ya está excluido por `.gitignore`.
- **En servidores, prefiera un archivo de secreto.** En lugar de la variable, indique la ruta: `OPENAI_API_KEY_FILE=/run/secrets/openai_api_key`. Así la clave no queda en el entorno del proceso.

Si la clave falta o es inválida, el gateway **no** responde con datos simulados: devuelve un error `502` con un mensaje claro, para que el fallo no pase desapercibido.

## 6. Instalación con Docker

Alternativa a los pasos 2 y 5. Requiere Docker instalado y el archivo `.env` ya preparado (pasos 3 y 4).

```bash
docker build -t gateway-llm .
docker run --rm -p 8080:8080 --env-file .env gateway-llm
```

El gateway queda disponible en `http://localhost:8080`. Características de la imagen:

- **Arranca en modo producción** (`ENTORNO=produccion`), por lo que exige todas las mitigaciones activas y al menos una clave de cliente.
- **Se ejecuta con un usuario sin privilegios** (no root).
- **No contiene claves:** el archivo `.env` no se copia a la imagen; se entrega al arrancar con `--env-file`.

> **Nota:** el modo producción y el comando de arranque del contenedor se verificaron ejecutándolos directamente. La construcción de la imagen con `docker build` no pudo ejecutarse en el entorno donde se preparó este manual, por lo que conviene probarla antes de un uso real.

## 7. Preparación para producción

Con `ENTORNO=produccion` el gateway aplica estas reglas al arrancar:

| Regla | Si no se cumple |
|---|---|
| Las cuatro mitigaciones deben estar activas | No arranca: `Mitigaciones desactivadas en producción: [...]` |
| `SIMULAR_FALLA_UPSTREAM` debe estar vacío | No arranca |
| Debe existir al menos una clave de cliente | No arranca: `No hay claves de cliente configuradas` |
| La documentación `/docs` se desactiva | Responde `404` |

Además, antes de exponer el servicio:

- **Use un proveedor real**, no el simulado.
- **Publique el gateway detrás de HTTPS** (balanceador o proxy inverso). El gateway no cifra por sí mismo.
- **Con más de una réplica, use Redis** para el contador de cuotas. Instale el paquete y configure la dirección:

```bash
pip install redis
```

```text
RATE_LIMIT_STORAGE_URI=redis://servidor:6379
```

Sin Redis, cada réplica llevaría su propia cuenta y el límite real sería mayor al configurado. Con Redis, el límite se comparte: en una prueba con dos réplicas y límite de 5 por minuto, pasaron exactamente 5 solicitudes entre ambas.

- **Guarde las claves de los proveedores en un gestor de secretos** y móntelas como archivo (`*_FILE`).
- **Envíe `logs/gateway.jsonl` a un sistema central de registros** y defina alertas sobre los resultados `bloqueado_llm01`, `fuga_bloqueada_llm07` y `rate_limit_excedido`.
- **Limite `CORS_ORIGINS`** a los sitios reales que consumirán el gateway.

El diagrama `docs/arquitectura/06_despliegue_produccion.png` muestra una propuesta completa sobre Google Cloud.

## 8. Actualización y desinstalación

Actualizar a la última versión:

```bash
git pull
pip install -r requirements.txt
python -m pytest
```

Reinicie el gateway al terminar. El archivo `.env` y los registros no se modifican.

Desinstalar: detenga el gateway y elimine la carpeta del proyecto. No se instala nada fuera de ella. Antes de borrar, respalde `.env` si desea conservar la configuración, y recuerde que las claves `gw_` emitidas dejan de funcionar.

## 9. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `python` o `git` no se reconoce | No está instalado o no está en el PATH | Instálelo y abra una terminal nueva |
| `uvicorn` no se reconoce | El entorno virtual no está activo | Active el entorno (paso 2) |
| `address already in use` al arrancar | El puerto 8000 está ocupado | Use otro puerto: `--port 8001` |
| Todas las consultas devuelven `401` | La clave no está en `.env`, se copió incompleta o falta el prefijo `Bearer` | Revise el paso 4 y reinicie |
| `401` después de editar `.env` | No se reinició el gateway | `Ctrl + C` y arrancar de nuevo |
| `429` al poco de empezar | Se superó el límite de 5 solicitudes por minuto | Espere un minuto o aumente `RATE_LIMIT` |
| `422` | La solicitud no cumple el formato o supera los límites | Revise el campo indicado en `detalles` |
| `502` con un proveedor real | Falta la API key o es inválida | Revise la clave del proveedor en `.env` |
| `503` con Ollama | Ollama no está en ejecución o el modelo no se descargó | Inicie Ollama y ejecute `ollama pull llama3.2` |
| `504` | El proveedor tardó más que `TIMEOUT_UPSTREAM_SEG` | Aumente el valor o configure un respaldo |
| Error `'redis' prerequisite not available` | Se configuró `redis://` sin instalar el paquete | `pip install redis` |
| El gateway no arranca en producción | Falta una clave de cliente o hay un interruptor apagado | Lea el mensaje `RuntimeError` y corrija `.env` |
| PowerShell no deja activar el entorno | Política de ejecución de scripts | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| El script `ataques_en_vivo.sh` no corre en Windows | PowerShell no ejecuta scripts de shell | Úselo desde **Git Bash** |
| Acentos mal mostrados en la terminal de Windows | Codificación de la consola | Ejecute antes `chcp 65001` o use Git Bash |

Cada respuesta de error incluye un `request_id`. Búsquelo en `logs/gateway.jsonl` para ver qué ocurrió con esa solicitud.

## 10. Lista de verificación final

- [ ] `python --version` muestra 3.11 o 3.12
- [ ] El entorno virtual está activo: la terminal muestra `(venv)`
- [ ] `.env` existe y contiene al menos un cliente en `GATEWAY_CLIENT_KEYS_SHA256`
- [ ] Al arrancar, la primera línea muestra las cuatro mitigaciones en `true`
- [ ] `http://localhost:8000/health` responde `{"status":"ok"}`
- [ ] Una consulta con la clave devuelve `200` y una respuesta
- [ ] Una consulta sin clave devuelve `401`
- [ ] `python -m pytest` termina con `63 passed`
- [ ] `python scripts/escanear_secretos.py` no encuentra secretos
- [ ] La clave `gw_` está guardada en un lugar seguro y **no** está en el repositorio
