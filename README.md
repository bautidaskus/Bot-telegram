# Gym Tracker Bot

Bot de Telegram para registrar entrenamientos mientras entrenás, que corre en tu
PC con Windows. Le mandás mensajes cortos entre serie y serie y cada una se
guarda al instante: no hay preview ni confirmación en el medio.

- **Captura:** parser determinístico, sin LLM en el camino crítico.
- **Ejercicios nuevos:** los canoniza Groq (`openai/gpt-oss-120b`) vía SDK de OpenAI.
- **Persistencia:** SQLite local (modo WAL) con SQLAlchemy 2.0 + Alembic.
- **Single-user:** solo responde al `chat_id` autorizado.

## Requisitos

- Python 3.11+ en el PATH.
- Cuenta gratis en [console.groq.com](https://console.groq.com) → API key.
- Bot de Telegram creado con [@BotFather](https://t.me/BotFather) → token.

## Setup (Windows / PowerShell)

```powershell
git clone https://github.com/bautidaskus/Bot-telegram.git
cd "Bot registro cosas"

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt        # o requirements-dev.txt para correr tests

copy .env.example .env
# Editá .env: pegá TELEGRAM_BOT_TOKEN y GROQ_API_KEY.
# Dejá ALLOWED_CHAT_ID vacío la primera vez (ver más abajo).

alembic upgrade head                    # crea data/tracker.db
python -m src.main
```

## Dashboard web local

La versión 1.1 incluye un dashboard Flask de solo lectura para consultar la misma
base SQLite que usa el bot. Escucha únicamente en `http://127.0.0.1:5000`: no se
expone a otros equipos de la red y no tiene endpoints de escritura.

Con la base migrada y el entorno instalado, abrí dos terminales:

```powershell
# Terminal 1: bot de Telegram
start_bot.bat

# Terminal 2: dashboard local
start_web.bat
```

También podés iniciarlo con `python -m src.web`. Bot y dashboard pueden ejecutarse
al mismo tiempo: SQLite usa WAL, el bot escribe y cada request web abre una sesión
breve de lectura que se cierra al terminar.

El dashboard incluye:

- Resumen mensual por moneda, último peso, salud reciente, gimnasio y actividad.
- Finanzas por mes y moneda, con flujo diario, categorías y movimientos.
- Progresión por ejercicio con peso máximo y 1RM estimado.
- Historial de 30, 90 o 365 días para peso, sueño, ánimo, energía y agua.

Los gráficos usan Chart.js 4.5.1 desde CDN, por lo que necesitan conexión a internet
al cargar la página. El resto del dashboard y todos los datos permanecen locales.

### Descubrir tu `chat_id`

Mandale cualquier mensaje al bot. En la consola / `logs/tracker.log` vas a ver:

```
WARNING | chat_id no autorizado: 123456789
```

Copiá ese número a `ALLOWED_CHAT_ID` en `.env` y reiniciá el bot.

### Arranque automático con Windows

Está incluido `start_bot.bat` (activa el venv y arranca el bot). Para que arranque
con la sesión, creá un acceso directo al `.bat` dentro de la carpeta que abre
`shell:startup` (Win+R → `shell:startup`). Alternativa robusta: registrarlo como
servicio con [`nssm`](https://nssm.cc/).

## Uso

El primer mensaje abre la sesión y su texto queda como etiqueta. A partir de ahí,
cada mensaje se interpreta según su forma:

| Mandás | Pasa |
|--------|------|
| `espalda biceps` (sin sesión abierta) | Abre la sesión con esa etiqueta. |
| `remo t 60` | Cambia de ejercicio y fija el peso en 60 kg. |
| `dominadas` | Cambia de ejercicio, sin peso. |
| `10` | Una serie de 10 reps al peso vigente. |
| `10 8 6` o `10,8,6` | Tres series, una por número. |
| `60x10` | Serie con peso explícito; no cambia el peso vigente. |
| `deshacer` | Borra la última serie registrada. |
| `fin` | Cierra la sesión y muestra el resumen. |

Sesión típica: `espalda biceps` → `dominadas` → `7` → `6` → `remo t 60` → `10` → `fin`.

El bot repite lo que entendió en cada respuesta (`remo_t: 60x10`), así un match
equivocado se ve al instante. Si volvés a un ejercicio que ya hiciste en la
sesión, recupera el último peso que usaste con él. Una sesión sin actividad por
3 horas se cierra sola y te avisa.

A las 22:00 llega el check-in del día: puntaje, ánimo, energía, hora de acostarte
y lo mejor del día, todo respondible con taps. Si a las 23:00 sigue pendiente,
llega un único recordatorio.

### Comandos

| Comando | Qué hace |
|---------|----------|
| `/start`, `/help` | Introducción y sintaxis de captura. |
| `/hoy` | Sesión del día y estado del check-in. |
| `/gym [ejercicio]` | Última sesión, o progresión de un ejercicio con 1RM estimado. |
| `/sesiones [n]` | Últimas N sesiones (default 5). |
| `/estado` | Sesión abierta y cuántas series lleva. |
| `/cancelar` | Descarta la sesión abierta sin guardarla. |
| `/editar <tipo> <id>` | Edición guiada de un registro. |
| `/borrar <tipo> <id>` | Borra con confirmación inline. |
| `/export` | Manda un snapshot de la base como adjunto. |
| `/backup` | Fuerza un backup manual a `data/backups/`. |

`<tipo>` es `sesion` o `set`. Además hay un backup automático nocturno a la hora
definida en `BACKUP_DAILY_HOUR`.

## Tests

```powershell
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                 # el test marcado --live (Groq) se saltea sin API key
ruff check .
ruff format --check .
```

Para correr el smoke test real contra Groq, configurá `GROQ_API_KEY` y pasá
`--live`.

## Troubleshooting

| Síntoma | Causa probable / solución |
|---------|---------------------------|
| El bot no responde a tus mensajes | `ALLOWED_CHAT_ID` mal cargado. Mirá el warning con tu `chat_id` real en `logs/tracker.log` y corregilo. |
| Un mensaje abrió una sesión que no querías | `/cancelar` la descarta sin guardar nada. |
| `alembic: command not found` o la DB no se crea | El venv no está activado o faltan deps. Activá `.venv` y `pip install -r requirements.txt`. |
| Errores 401 / "invalid api key" al dar de alta un ejercicio | `GROQ_API_KEY` o `TELEGRAM_BOT_TOKEN` vacíos o mal pegados en `.env`. |
| `database is locked` | Otra instancia del bot abierta sobre el mismo `tracker.db`. Cerrá la duplicada; SQLite usa WAL + busy_timeout pero no soporta dos escritores. |
| El dashboard muestra un error 500 | Ejecutá `alembic upgrade head`, verificá `DB_PATH` y revisá que el bot y la web apunten al mismo archivo. |
| Los gráficos no aparecen | Verificá la conexión a internet y que el navegador pueda cargar Chart.js desde `cdn.jsdelivr.net`. Las tablas siguen disponibles sin el CDN. |
| No abre `127.0.0.1:5000` | Confirmá que `start_web.bat` siga abierto y que otro proceso no esté usando el puerto 5000. |

## Estructura

```
src/
├── main.py            # wiring + arranque (long polling)
├── config.py          # Settings (Pydantic)
├── logging_setup.py   # loguru a archivo, secretos enmascarados
├── backup.py          # snapshot + retención
├── ai/                # parser y canonizador de ejercicios (Groq LLM)
├── bot/               # gym_handlers, checkin, commands, maintenance, backup_commands, auth
├── gym/               # matcher difuso, parser de captura, servicio de sesión
├── db/                # models, session (WAL), repositories
├── domain/            # schemas Pydantic
├── utils/             # parsing de fechas
└── web/               # Flask, consultas analíticas, templates y assets
```

Ver `CHANGELOG.md` para el detalle de hitos y `personal-tracker-spec.md` para la
especificación completa.
