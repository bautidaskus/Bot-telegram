# Personal Tracker Bot — Especificación Técnica

**Versión:** 1.0
**Autor:** bau
**Fecha:** 2026-06-08
**Audiencia:** Claude Code (implementación) + el propio autor

---

## 1. Visión general

Sistema de tracking personal accesible vía bot de Telegram que permite registrar:

- **Finanzas:** gastos e ingresos con categoría
- **Gimnasio:** sesiones, ejercicios, series, repeticiones, peso levantado
- **Peso corporal:** medición diaria
- **Salud diaria:** sueño, ánimo, energía, agua

El usuario interactúa enviando **mensajes de texto o audios en lenguaje natural** (en español). El sistema transcribe los audios, interpreta el contenido con un LLM, lo convierte en datos estructurados y los persiste en una base de datos SQLite local.

El bot corre en la PC del usuario (Windows). Cuando la PC está apagada, Telegram retiene los mensajes hasta 24h y el bot los procesa cuando se reconecta vía long polling.

**No-objetivos del MVP:**

- No incluye dashboard web (queda para v1.1)
- No incluye reporte PDF mensual (v1.2)
- No incluye integración automática con MercadoPago (v1.3, vía Gmail)
- No es multi-usuario: solo responde al chat ID autorizado

---

## 2. Stack tecnológico

| Capa | Tecnología | Justificación |
|------|------------|---------------|
| Lenguaje | Python 3.11+ | Ecosistema maduro para bots + IA |
| Bot framework | `python-telegram-bot` v21+ | Estándar de facto, soporta long polling y audio |
| Transcripción | Groq Whisper API (`whisper-large-v3`) | Gratis, rápida, sin tarjeta de crédito |
| LLM parser | Groq `llama-3.3-70b-versatile` | Gratis, suficiente para extracción estructurada |
| Cliente LLM | `openai` SDK apuntando a Groq | Groq usa endpoint compatible con OpenAI |
| Base de datos | SQLite 3 (modo WAL) | Cero configuración, archivo único |
| ORM | SQLAlchemy 2.0 | Tipado, integra con Alembic |
| Migraciones | Alembic | Para evolución del esquema |
| Validación | Pydantic v2 | Validar JSON del LLM antes de persistir |
| Logging | `loguru` | Logs rotados a archivo |
| Config | `python-dotenv` | Variables de entorno desde `.env` |
| Fechas | `dateparser` | Parsing de "ayer", "el lunes pasado" en español |
| Audio | `pydub` + `ffmpeg` | Conversión de formatos si hace falta |

**SO de ejecución:** Windows 10/11
**Zona horaria por defecto:** America/Argentina/Buenos_Aires
**Moneda por defecto:** ARS

---

## 3. Arquitectura

```
┌───────────────────────┐
│   Usuario (Telegram)  │
└──────────┬────────────┘
           │ texto / audio / comando
           ▼
┌──────────────────────────────────────┐
│   Telegram Bot (long polling)        │
│   - Recibe updates                   │
│   - Verifica chat_id autorizado      │
│   - Despacha por tipo                │
└─────┬──────────────┬─────────────────┘
      │ audio        │ texto
      ▼              │
┌──────────────┐     │
│  Whisper     │     │
│  (Groq API)  │     │
│  → texto     │     │
└──────┬───────┘     │
       │             │
       └──────┬──────┘
              ▼
┌─────────────────────────────┐
│  LLM Parser (Llama 3.3 70B) │
│  - System prompt + texto    │
│  - Devuelve JSON estructurado│
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────┐
│  Validador (Pydantic)   │
│  → Modelo tipado        │
└──────┬──────────────────┘
       │
       ▼
┌─────────────────────┐
│   SQLite (tracker.db)│
└──────┬──────────────┘
       │
       ▼
┌─────────────────────────┐
│  Respuesta al usuario   │
│  con confirmación + IDs │
└─────────────────────────┘
```

---

## 4. Módulos funcionales

### 4.1 Finanzas

**Campos por transacción:**

- `tipo`: `gasto` | `ingreso`
- `monto`: decimal > 0
- `moneda`: por defecto `ARS`, soporta `USD`, `EUR`
- `categoria`: enum extensible
- `descripcion`: texto libre opcional
- `metodo_pago`: opcional (`efectivo`, `debito`, `credito`, `transferencia`, `mercadopago`)
- `fecha`: por defecto hoy, parseable desde lenguaje natural

**Categorías iniciales:**

- Gastos: `alimentos`, `transporte`, `ocio`, `salud`, `servicios`, `alquiler`, `ropa`, `educacion`, `regalos`, `tecnologia`, `otros`
- Ingresos: `sueldo`, `freelance`, `regalo`, `venta`, `inversion`, `otros`

**Ejemplos de input:**

- "Gasté 1500 en el súper"
- "Pagué 25000 de luz ayer con débito"
- "Cobré 250000 del sueldo"
- "Compré una pizza a 8000 con MP"

**Comandos de consulta:**

- `/balance [mes] [año]` — balance del mes (default actual)
- `/gastos [categoria]` — top categorías o detalle de una
- `/ingresos [mes] [año]`
- `/ultimos [n]` — últimas N transacciones (default 5)

### 4.2 Gimnasio

**Modelo:**

- Una `gym_sesion` por entrenamiento: fecha, tipo (`push` / `pull` / `piernas` / `full_body` / `cardio` / `libre`), duración opcional, notas.
- Una `gym_set` por serie ejecutada: enlazada a la sesión y al ejercicio canónico. Campos: peso_kg opcional, reps opcional, RPE opcional, nota.

**Catálogo de ejercicios:** arranca **vacío**. Se va llenando con el uso. El LLM genera el nombre canónico (snake_case, en español, sin acentos) normalizando alias comunes ("bench press" → `press_banca`, "squat" → `sentadilla`, etc.). Cuando aparece un ejercicio nuevo, el repositorio lo inserta automáticamente en la tabla `ejercicio` y queda disponible para futuras menciones. La normalización futura puede mejorarse haciendo que el LLM reciba la lista actual de ejercicios canónicos como contexto.

**Ejemplos de input:**

- "Hice push: bench 80 por 8, 8 y 6. Press militar 30x10 tres series. Fondos 12, 10, 8."
- "Sesión de piernas: sentadilla 100 kilos 5 reps 5 series, peso muerto rumano 80 8 reps 4 series."

**Comandos:**

- `/gym` — resumen de la última sesión
- `/gym [ejercicio]` — progresión histórica (peso máx por fecha, mejor 1RM estimado)
- `/sesiones [n]` — últimas N sesiones

### 4.3 Peso corporal

**Campos:** fecha (única por día), kg, nota opcional.

**Ejemplos:** "Peso 78.4", "Hoy pesé 78,4 kilos".

**Comandos:**

- `/peso` — último registro + tendencia últimas 4 semanas (media móvil 7 días)
- `/peso historial` — últimos 30 registros

### 4.4 Salud diaria

Una fila por día (UPSERT por fecha). Todos los campos opcionales:

- `sueno_horas`: decimal
- `sueno_calidad`: 1-10
- `animo`: 1-10
- `energia`: 1-10
- `agua_l`: decimal (litros)
- `nota`: texto libre

**Ejemplos:**

- "Dormí 7 horas, calidad 4"
- "Ánimo 3, energía 4, tomé 2 litros de agua"

**Comandos:**

- `/hoy` — resumen multidominio del día
- `/salud` — promedios últimos 7 días

---

## 5. Flujo de procesamiento

### 5.1 Entrada de texto

1. Usuario envía texto al bot.
2. Bot verifica `update.message.chat.id == ALLOWED_CHAT_ID`. Si no, se ignora silenciosamente y se loguea como warning.
3. Si empieza con `/` → router de comandos (sección 7).
4. Si no:
   1. Texto + system prompt → Groq LLM.
   2. LLM devuelve **un array** `operaciones` (uno o más objetos, cada uno con `tipo`, `confianza`, `fecha`, `datos`, `razonamiento`). Esto permite que un solo mensaje genere varios registros (ej: "dormí 7 horas y pesé 78" → 2 operaciones).
   3. Si alguna operación tiene `tipo == "ambiguo"` o `confianza < 0.7` → ir a flujo de aclaración (5.4) **para esa operación específica**; las demás siguen su curso.
   4. Validar cada operación con Pydantic.
   5. **Mostrar preview** al usuario con todo lo entendido y botones `✅ Guardar` / `❌ Cancelar` / `✏️ Corregir` (sección 5.3).
   6. Solo si el usuario confirma → insertar en DB.
   7. Responder con confirmación final incluyendo IDs y comandos `/editar` / `/borrar`.

### 5.2 Entrada de audio

1. Usuario envía voice message o file de audio.
2. Bot descarga el archivo (`.ogg` típicamente).
3. Si no es formato aceptado por Whisper, convertir con `pydub` (requiere `ffmpeg`).
4. Enviar a Groq Whisper API (`whisper-large-v3`, `language="es"`).
5. El texto transcripto entra al flujo de 5.1 desde el paso 4.i.
6. La respuesta al usuario **incluye la transcripción** para que pueda verificar lo entendido.

### 5.3 Confirmación interactiva (preview antes de guardar)

**El bot NO guarda automáticamente.** Tras parsear y validar el mensaje, muestra un preview de lo que entendió y espera confirmación del usuario. Esto vale tanto para texto como para audio (en este último caso el preview también incluye la transcripción).

**Ejemplo de preview — mensaje único:**

```
🔍 Esto fue lo que entendí:

💸 Gasto
   Monto: $1.500
   Categoría: alimentos
   Método: débito
   Fecha: hoy (2026-06-08)

[ ✅ Guardar ]  [ ❌ Cancelar ]  [ ✏️ Corregir ]
```

**Ejemplo de preview — múltiples operaciones en un mismo mensaje** (ej: "dormí 7 horas, calidad 8, y pesé 78.4"):

```
🔍 Esto fue lo que entendí (2 operaciones):

1. 😴 Salud
   Sueño: 7 h, calidad 8/10
   Fecha: hoy

2. ⚖️ Peso
   78.4 kg
   Fecha: hoy

[ ✅ Guardar todo ]  [ ❌ Cancelar ]  [ ✏️ Corregir ]
```

**Comportamiento de los botones:**

- **Guardar / Guardar todo:** persiste todo dentro de una transacción. Si una operación falla, se hace rollback del lote completo. Responde con los IDs asignados.
- **Cancelar:** descarta sin guardar.
- **Corregir:** abre un mini-diálogo guiado para editar campos antes de guardar (ver sección 7, `/editar` reutiliza el mismo componente).

**Expiración:** si el usuario no responde en **10 minutos**, el preview expira. El bot edita el mensaje a "⌛ Preview expirado, reenviá el mensaje si querés registrarlo" y descarta los datos pendientes.

**Confirmación final post-guardado:**

```
✅ Guardado

1. 😴 Salud  🆔 #58    /editar 58  /borrar 58
2. ⚖️ Peso   🆔 #21    /editar 21  /borrar 21
```

### 5.4 Manejo de ambigüedad

Si `confianza < 0.7` o el modelo devolvió `ambiguo`:

- Guardar el mensaje original (y transcripción si aplicaba) en `pendiente`.
- Responder con botones inline ofreciendo las opciones más probables que sugirió el LLM ("¿gasto o ingreso?", "¿gimnasio o salud?").
- Cuando el usuario elige, reprocesar el mensaje añadiendo el hint y proceder normalmente.

---

## 6. Esquema de base de datos

```sql
-- Transacciones financieras
CREATE TABLE transaccion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha DATE NOT NULL,
    tipo TEXT NOT NULL CHECK(tipo IN ('gasto', 'ingreso')),
    monto REAL NOT NULL CHECK(monto > 0),
    moneda TEXT NOT NULL DEFAULT 'ARS',
    categoria TEXT NOT NULL,
    descripcion TEXT,
    metodo_pago TEXT,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mensaje_original TEXT
);
CREATE INDEX idx_trans_fecha ON transaccion(fecha);
CREATE INDEX idx_trans_categoria ON transaccion(categoria);

-- Sesiones de gimnasio
CREATE TABLE gym_sesion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha DATE NOT NULL,
    tipo TEXT,
    duracion_min INTEGER,
    notas TEXT,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mensaje_original TEXT
);

-- Catálogo de ejercicios (se llena dinámicamente)
CREATE TABLE ejercicio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_canonico TEXT UNIQUE NOT NULL,
    grupo_muscular TEXT,
    alias_json TEXT  -- JSON array: ["bench press", "press banca"]
);

-- Sets ejecutados
CREATE TABLE gym_set (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id INTEGER NOT NULL REFERENCES gym_sesion(id) ON DELETE CASCADE,
    ejercicio_id INTEGER NOT NULL REFERENCES ejercicio(id),
    serie_num INTEGER NOT NULL,
    peso_kg REAL,
    reps INTEGER,
    rpe REAL,
    nota TEXT
);
CREATE INDEX idx_set_sesion ON gym_set(sesion_id);
CREATE INDEX idx_set_ejercicio ON gym_set(ejercicio_id);

-- Peso corporal
CREATE TABLE peso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha DATE NOT NULL UNIQUE,
    kg REAL NOT NULL CHECK(kg > 0),
    nota TEXT,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Salud diaria (1 fila por día, UPSERT)
CREATE TABLE salud (
    fecha DATE PRIMARY KEY,
    sueno_horas REAL,
    sueno_calidad INTEGER CHECK(sueno_calidad BETWEEN 1 AND 10),
    animo INTEGER CHECK(animo BETWEEN 1 AND 10),
    energia INTEGER CHECK(energia BETWEEN 1 AND 10),
    agua_l REAL,
    nota TEXT,
    actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Mensajes pendientes de aclaración
CREATE TABLE pendiente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    mensaje_original TEXT NOT NULL,
    transcripcion TEXT,
    intentos INTEGER DEFAULT 0,
    sugerencias_json TEXT,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Log de errores
CREATE TABLE error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT,
    mensaje TEXT,
    contexto_json TEXT,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 7. Comandos del bot

### Sistema

- `/start` — saludo + lista breve de comandos
- `/help` — ayuda detallada
- `/hoy` — resumen multidominio del día

### Finanzas

- `/balance [mes] [año]`
- `/gastos [categoria]`
- `/ingresos [mes] [año]`
- `/ultimos [n]`

### Gym

- `/gym`
- `/gym [ejercicio]`
- `/sesiones [n]`

### Peso

- `/peso`
- `/peso historial`

### Salud

- `/salud`

### Mantenimiento

- `/editar <id>` — abre diálogo guiado con botones por campo
- `/borrar <id>` — pide confirmación inline
- `/export` — manda `tracker.db` como adjunto al chat
- `/backup` — fuerza backup manual a `data/backups/`

---

## 8. Interpretación con LLM

### 8.1 System prompt del parser

Archivo: `prompts/parser.txt`. Contenido base:

```
Sos un asistente que extrae información estructurada de mensajes en español
sobre actividades personales. El usuario te habla en lenguaje natural sobre
gastos, ingresos, ejercicios del gimnasio, peso corporal o estado de salud.

Un solo mensaje puede contener VARIAS operaciones (ej: "dormí 7 horas y pesé 78"
son dos operaciones independientes: una de salud y una de peso).

Devolvé SIEMPRE un único objeto JSON válido con esta forma:

{
  "operaciones": [
    {
      "tipo": "gasto" | "ingreso" | "gym" | "peso" | "salud" | "ambiguo",
      "confianza": 0.0-1.0,
      "fecha": "hoy" | "ayer" | "anteayer" | "lunes" | "DD/MM" | "YYYY-MM-DD",
      "datos": { ... según tipo ... },
      "razonamiento": "breve explicación"
    },
    ...
  ]
}

Reglas:
1. Si no podés determinar el tipo con confianza > 0.7, devolvé "ambiguo"
   y en "datos" un array "sugerencias" con los tipos posibles.
2. Los montos vienen en pesos argentinos por defecto.
3. Para gym, generá el nombre canónico del ejercicio en snake_case, en español,
   sin acentos. Normalizá alias comunes: "bench press"/"press banca" →
   "press_banca", "squat" → "sentadilla", "deadlift" → "peso_muerto".
4. Las fechas relativas mantenelas como string ("ayer", "lunes") — se parsean después.
5. NO inventes datos que no estén en el mensaje. Si falta un dato, omitilo.
6. Si el mensaje tiene una sola intención, devolvé un array de UNA operación.

Schemas por tipo (campos en `datos`):
- gasto/ingreso: { monto: number, categoria: string, descripcion?: string, metodo_pago?: string }
- gym: { tipo_sesion?: string, ejercicios: [{ nombre: string, sets: [{peso_kg?: number, reps?: number, rpe?: number}] }] }
- peso: { kg: number }
- salud: { sueno_horas?: number, sueno_calidad?: 1-10, animo?: 1-10, energia?: 1-10, agua_l?: number }

Catálogo de ejercicios canónicos conocidos: <se inyecta dinámicamente desde la
tabla `ejercicio` en cada llamada; arranca vacío y crece con el uso>.

Categorías de gasto: alimentos, transporte, ocio, salud, servicios, alquiler,
ropa, educacion, regalos, tecnologia, otros

Categorías de ingreso: sueldo, freelance, regalo, venta, inversion, otros
```

### 8.2 Validación

Modelos Pydantic en `src/domain/schemas.py`. Si el JSON no valida → reintentar hasta 2 veces incluyendo el error de validación como mensaje del LLM. Si sigue fallando → se guarda en `pendiente` y se pide aclaración al usuario.

### 8.3 Parseo de fechas

Después de validar el JSON, las fechas en formato relativo (`"ayer"`, `"lunes"`) se parsean con:

```python
dateparser.parse(
    raw,
    languages=["es"],
    settings={
        "TIMEZONE": "America/Argentina/Buenos_Aires",
        "RETURN_AS_TIMEZONE_AWARE": False,
        "PREFER_DATES_FROM": "past",
    },
)
```

---

## 9. Estructura de proyecto

```
personal-tracker/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── pyproject.toml
├── alembic.ini
├── alembic/
│   └── versions/
├── data/
│   ├── tracker.db                 # se crea en runtime
│   └── backups/
├── logs/
│   └── tracker.log
├── prompts/
│   └── parser.txt
├── src/
│   ├── __init__.py
│   ├── main.py                    # entry point
│   ├── config.py                  # carga .env
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── handlers.py            # text + voice handlers
│   │   ├── commands.py            # /balance, /gym, etc.
│   │   ├── callbacks.py           # botones inline (aclaración, borrar)
│   │   └── auth.py                # filtro de chat_id
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── whisper_client.py
│   │   └── parser.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── session.py
│   │   └── repository.py          # CRUD por módulo
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── schemas.py             # Pydantic
│   │   └── catalogo.py            # ejercicios, categorías
│   ├── utils/
│   │   ├── dates.py
│   │   └── formato.py
│   └── backup.py
└── tests/
    ├── test_parser.py
    ├── test_repository.py
    └── fixtures/
        └── mensajes.json
```

---

## 10. Variables de entorno

`.env.example`:

```ini
# Telegram
TELEGRAM_BOT_TOKEN=
ALLOWED_CHAT_ID=                  # tu chat_id; se descubre logueando el primer mensaje

# Groq — https://console.groq.com
GROQ_API_KEY=
GROQ_LLM_MODEL=llama-3.3-70b-versatile
GROQ_WHISPER_MODEL=whisper-large-v3
GROQ_BASE_URL=https://api.groq.com/openai/v1

# General
TIMEZONE=America/Argentina/Buenos_Aires
DEFAULT_CURRENCY=ARS
DB_PATH=./data/tracker.db
LOG_LEVEL=INFO

# Backups
BACKUP_DIR=./data/backups
BACKUP_RETENTION_DAYS=30
BACKUP_DAILY_HOUR=3               # hora local del backup automático
```

---

## 11. Instalación y ejecución (Windows)

### Pre-requisitos

- Python 3.11+ instalado y en el PATH
- `ffmpeg` instalado y en el PATH (`winget install ffmpeg`)
- Cuenta gratis en https://console.groq.com → generar API key
- Bot creado vía [@BotFather](https://t.me/BotFather) → guardar token

### Pasos

```powershell
git clone <repo>
cd personal-tracker

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt

copy .env.example .env
# Editar .env: pegar TELEGRAM_BOT_TOKEN y GROQ_API_KEY
# Dejar ALLOWED_CHAT_ID vacío la primera vez

alembic upgrade head
python -m src.main
```

### Descubrir el chat_id

Al primer mensaje que mandes al bot, este loguea:

```
WARNING | chat_id no autorizado: 123456789. Agregalo a ALLOWED_CHAT_ID si sos vos.
```

Copiás ese número a `.env` y reiniciás.

### Arranque automático con Windows

`start_bot.bat`:

```bat
@echo off
cd /d C:\ruta\al\proyecto\personal-tracker
call .venv\Scripts\activate.bat
python -m src.main
```

Acceso directo al `.bat` en `shell:startup`. Alternativa robusta: registrar como servicio con `nssm`.

---

## 12. Manejo de errores y edge cases

| Caso | Comportamiento |
|------|----------------|
| LLM devuelve JSON inválido | Reintentar 2 veces. Si falla, ir a `pendiente` y pedir aclaración. |
| Audio sin habla / silencio | Whisper → texto vacío → "No entendí el audio, ¿podés reescribirlo?" |
| Mensaje irrelevante ("hola") | LLM devuelve `ambiguo` → bot responde con ayuda corta. |
| Fecha futura detectada | Pedir confirmación inline. |
| Monto negativo o cero | Rechazar, pedir aclaración. |
| Peso fuera de rango (30-300 kg) | Pedir confirmación. |
| Sueño > 16h o < 1h | Pedir confirmación. |
| `chat_id` no autorizado | Ignorar; log warning. |
| Groq API caída | Reintento con backoff exponencial (3 intentos, base 2s). Si falla, guardar en `pendiente` y avisar al usuario. |
| DB locked | SQLite en `WAL` + retry con timeout. |
| Audio > 25 MB (límite Whisper) | Rechazar con mensaje claro. |
| Mensajes acumulados al arrancar | Procesar en orden, throttling 1 mensaje/segundo. |
| Preview sin respuesta en 10 min | Expirar, editar mensaje del bot a "⌛ Preview expirado", descartar datos pendientes. |
| Lote de operaciones con una que falla en DB | Rollback de toda la transacción, avisar cuál falló. |
| Inserción exitosa, falla la respuesta a Telegram | Marcar OK en DB pero loguear el error de envío. |

---

## 13. Seguridad y privacidad

- **Whitelist por `chat_id`:** el bot solo responde al ID configurado.
- **Secretos:** `.env` en `.gitignore`. Solo se versiona `.env.example`.
- **Logs sanitizados:** filtro de `loguru` enmascara `GROQ_API_KEY` y `TELEGRAM_BOT_TOKEN` si aparecen accidentalmente.
- **Datos locales:** la DB nunca sale de la PC. Solo se mandan a Groq el texto y el audio para procesamiento.
- **Backups locales:** rotación de 30 días en `data/backups/`.
- **Export controlado:** `/export` solo se ejecuta para el chat autorizado.

---

## 14. Roadmap futuro

- **v1.1** — Dashboard web local (Flask + Chart.js), corriendo en `localhost:5000`
- **v1.2** — Reporte PDF mensual automático (reutilizar stack ReportLab del autor)
- **v1.3** — Integración con Gmail API para parsear mails de MercadoPago y bancos
- **v1.4** — Recordatorios programados ("¿registraste tu peso hoy?")
- **v1.5** — Detección de patrones y anomalías (gasto inusual, ánimo bajo sostenido)
- **v1.6** — Multimoneda con conversión automática (API de Bluelytics o similar)
- **v1.7** — Hábitos con rachas (streaks) y métricas de adherencia

---

## 15. Decisiones tomadas y preguntas restantes

### Decisiones confirmadas con el autor

- ✅ **Confirmación antes de guardar:** el bot muestra preview con botones `Guardar` / `Cancelar` / `Corregir`. No persiste hasta que el usuario confirma. (sección 5.3)
- ✅ **Escala 1-10** para sueño, ánimo y energía. (secciones 4.4 y 6)
- ✅ **Múltiples operaciones por mensaje:** el LLM devuelve un array `operaciones` y el bot las muestra todas en el mismo preview. (secciones 5.1 y 8.1)
- ✅ **Catálogo de ejercicios:** arranca vacío, se llena con el uso. (sección 4.2)
- ✅ **`/export`:** archivo `.db` plano, sin cifrar. Los datos no son críticamente sensibles y el canal de Telegram ya está cifrado en tránsito.

### Preguntas restantes (menores, se pueden decidir al implementar)

1. **Categorías de gastos** — ¿la lista de la sección 4.1 funciona? ¿agregar / quitar?
2. **Edición (`/editar 142`)** — ¿diálogo guiado con botones por campo, o sintaxis inline tipo `/editar 142 monto=1800`?
3. **Backup automático** — ¿corre cada noche a las 3 AM además del `/backup` manual, o solo manual?
4. **Logs verbosos** — ¿guardar transcripción y JSON del LLM en `logs/tracker.log` para debug, o solo nivel INFO mínimo?
5. **Alembic desde día 1** — recomendado sí; alternativa es `Base.metadata.create_all()` y migrar a Alembic cuando aparezca el primer cambio.
6. **Pendientes permanentes** — un mensaje en `pendiente` que tras N intentos sigue sin clasificarse: ¿descartar, o conservar para revisión manual en el dashboard futuro?
7. **Detección de duplicados** — si registrás "gasté 1500 en el súper" dos veces seguidas, ¿asumir que son dos transacciones distintas (recomendado, menos fricción) o preguntar?

---

## Apéndice A — Dependencias (`requirements.txt`)

```
python-telegram-bot>=21.0
openai>=1.40.0              # cliente compatible Groq
sqlalchemy>=2.0
alembic>=1.13
pydantic>=2.6
python-dotenv>=1.0
loguru>=0.7
dateparser>=1.2
pydub>=0.25
httpx>=0.27
```

## Apéndice B — Comandos rápidos para Claude Code

Al implementar, seguir este orden:

1. Scaffold de carpetas + `requirements.txt` + `.env.example` + `.gitignore`
2. `src/config.py` + `src/db/models.py` + migración inicial Alembic
3. `src/domain/schemas.py` (Pydantic) + `src/domain/catalogo.py`
4. `src/ai/whisper_client.py` + `src/ai/parser.py`
5. `src/db/repository.py` (CRUD por módulo)
6. `src/bot/auth.py` + `src/bot/handlers.py` (texto y audio)
7. `src/bot/commands.py` (consultas y mantenimiento)
8. `src/bot/callbacks.py` (botones de aclaración / borrar)
9. `src/backup.py` (job nocturno con APScheduler o similar)
10. `src/main.py` (wiring final + arranque)
11. `tests/test_parser.py` con fixtures de mensajes reales en español
12. `README.md` con quickstart de Windows

---

*Fin del documento.*
