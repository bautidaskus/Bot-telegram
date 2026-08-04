# Rediseño: tracker gym-only con captura conversacional y check-in nocturno

Fecha: 2026-08-04
Estado: aprobado, pendiente de plan de implementación

## Contexto

El bot actual registra finanzas, peso, salud y gimnasio. Cada mensaje pasa por un LLM que
devuelve operaciones tipadas, se muestra un preview y se guarda al confirmar.

El uso real es solo gimnasio, y el flujo de un mensaje autocontenido por sesión no encaja
con anotar en el momento entre series. Este rediseño reduce el dominio a gimnasio, cambia
la captura a un flujo conversacional con estado, y agrega un check-in nocturno.

## Objetivos

1. Registrar una sesión de gimnasio mandando mensajes cortos e incrementales.
2. Reconocer nombres de ejercicios escritos de cualquier forma, sin exigir el nombre exacto.
3. Capturar un registro diario liviano a la noche, respondible con taps.
4. Sacar del sistema finanzas, peso y salud.

## No objetivos

- Multi-usuario. Sigue siendo single-user con `ALLOWED_CHAT_ID`.
- Planificación de rutinas o prescripción de entrenamiento. Solo registro.
- Registro de audio. Se elimina.

## Decisiones tomadas

| Decisión | Elegido | Alternativas descartadas |
|---|---|---|
| Peso en las series | Pegajoso por ejercicio: se fija una vez, después solo reps | `80x8` en cada serie; no registrar peso |
| Sesión sin cerrar | Autocierre por inactividad de 3h | Cierre a medianoche; queda abierta indefinidamente |
| Datos viejos | Backup del `.db` y drop de las tablas | Dejar tablas muertas; exportar a CSV |
| Motor de captura | Híbrido: determinístico primero, LLM de fallback | LLM siempre; determinístico puro |
| Audios | Se eliminan | Mantener Whisper |
| Check-in | 22:00, recordatorio 23:00 | Sin recordatorio; expira a medianoche |

## Modelo de datos

### Tablas eliminadas

`transaccion`, `peso`, `salud`. Se hace un backup del `.db` a `data/backups/` antes de la
migración, reutilizando `src/backup.py`.

### `gym_sesion` (modificada)

La captura es una máquina de estados cuyo estado vive en la base, no en memoria, para que
sobreviva a reinicios del bot.

| Columna | Cambio |
|---|---|
| `etiqueta` | Nueva. Texto libre (`"espalda biceps"`). Reemplaza a `tipo`, que estaba limitado al catálogo cerrado `TIPOS_SESION` |
| `estado` | Nueva. `abierta` / `cerrada` |
| `ejercicio_actual_id` | Nueva. FK nullable a `ejercicio`. Puntero de captura |
| `peso_actual` | Nueva. `Numeric(7,2)` nullable. Peso pegajoso vigente |
| `ultima_actividad` | Nueva. `DateTime`. Base del autocierre |
| `cerrada_en` | Nueva. `DateTime` nullable |
| `tipo` | Se elimina (reemplazada por `etiqueta`) |

Invariante: como máximo una sesión con `estado = 'abierta'` a la vez.

### `ejercicio` (sin cambios de estructura)

`alias_json` y `grupo_muscular` existen pero nunca se usaron. Ahora se usan: `alias_json`
guarda la lista de alias aprendidos, `grupo_muscular` lo completa el LLM al dar de alta un
ejercicio nuevo. Las 6 filas existentes se conservan.

### `gym_set` (sin cambios)

Ya tiene `serie_num`, `peso_kg`, `reps`, `rpe`, `nota`. `serie_num` es correlativo por
ejercicio dentro de la sesión.

### `checkin` (nueva)

| Columna | Tipo |
|---|---|
| `fecha` | `Date`, PK |
| `puntaje_dia` | `int` 1-10, nullable |
| `animo` | `int` 1-10, nullable |
| `energia` | `int` 1-5, nullable |
| `hora_acostado` | `String(11)` nullable. Rango: `<22`, `22-23`, `23-00`, `00-01`, `01-02`, `+02` |
| `mejor_del_dia` | `Text` nullable |
| `estado` | `String(20)`: `pendiente` / `completo` |
| `creado_en`, `actualizado_en` | `DateTime` |

`puntaje_dia` mide qué tan bien salió el día (logros, productividad); `animo` mide el estado
emocional. Se separan a propósito: pueden divergir y ese contraste es el dato interesante.

## Captura del gym

### Apertura

Sin sesión abierta, cualquier mensaje de texto abre una sesión usando el texto como
`etiqueta`. El bot confirma (`Sesión abierta: espalda biceps`) para que el estado sea
visible y un arranque accidental se detecte al instante. `/cancelar` descarta.

### Router de mensajes con sesión abierta

Se evalúa en este orden; el primero que matchea gana:

| Patrón | Acción |
|---|---|
| `fin`, `listo`, `terminé`, `terminar` | Cierra la sesión, muestra resumen |
| `deshacer`, `borrar` | Elimina la última serie registrada |
| Un entero (`7`) | Una serie de 7 reps al `peso_actual` |
| Varios enteros (`10 8 6`, `10,8,6`) | Una serie por número |
| `<peso>x<reps>` (`60x10`) | Serie explícita; no altera `peso_actual` |
| Texto + número final (`remo t 60`) | Cambia de ejercicio y fija `peso_actual = 60` |
| Texto solo (`dominadas`) | Cambia de ejercicio, `peso_actual = NULL` |
| Cualquier otra cosa | Fallback al LLM |

`deshacer` es obligatorio: un typo (`77` en vez de `7`) tiene que ser corregible desde el
chat, sin abrir la base.

### Persistencia

Cada serie se escribe en el momento, junto con `ultima_actividad`. El autocierre solo
cambia `estado` a `cerrada`; no es el momento del guardado. Un corte de luz pierde como
mucho la marca de cierre, nunca series.

### Autocierre

Job repetitivo (reusando el `run_repeating` que hoy expira previews) que cierra sesiones
con `ultima_actividad` de más de 3h y avisa por mensaje.

### Respuestas del bot

Cortas y con estado explícito (`remo_t: 60x10, 60x8`). El eco es la red de seguridad ante
un match equivocado: lo ves en la respuesta en vez de descubrirlo semanas después.

## Matching de ejercicios

Pipeline, en orden:

1. **Normalización**: minúsculas, sin acentos, `_` ↔ espacio, espacios colapsados.
2. **Match exacto** contra nombre canónico o cualquier alias en `alias_json`.
3. **Match difuso** con `difflib.get_close_matches`, cutoff `0.8`, contra canónicos y alias.
   `dominasas` ≈ `dominadas` (ratio ≈ 0.88) matchea. Si el texto de entrada difiere del
   canónico, se guarda como alias nuevo: la segunda vez resuelve por el paso 2.
4. **Alta vía LLM**: si nada matchea, el LLM canoniza a `snake_case` sin acentos e infiere
   `grupo_muscular`. Se crea la fila y el bot avisa `nuevo ejercicio: remo_t`.

`difflib` es stdlib: cero dependencias nuevas. Para un catálogo personal de decenas de
ejercicios alcanza. Si la precisión no rinde, `rapidfuzz` es el upgrade natural.

Riesgo conocido: el paso 3 podría colapsar `remo` con `remo_unilateral`. Mitigado porque el
match exacto corre primero y por el eco del bot.

## Check-in nocturno

Job diario a las 22:00; si a las 23:00 sigue en `pendiente`, un único recordatorio.

Secuencia sobre **un solo mensaje que se va editando** con teclados inline, para no llenar
el chat:

1. Puntaje del día → botones 1-10
2. Ánimo → botones 1-10
3. Energía → botones 1-5
4. ¿A qué hora te acostaste anoche? → rangos
5. Lo mejor del día → `[Escribir]` / `[Saltear]`

"Anoche" es la noche que terminó esa mañana. Cada respuesta se persiste al recibirse, así
un abandono en el paso 3 conserva los pasos 1 y 2.

El paso 5 pone al bot a esperar texto libre. Ese router tiene que tener prioridad sobre la
captura de gym, siguiendo el patrón que ya existe en `maintenance.handle_edit_value`
(handler en `group=-1` que corta con `ApplicationHandlerStop`).

## Superficie del bot

**Comandos eliminados**: `/balance`, `/gastos`, `/ingresos`, `/ultimos`, `/peso`, `/salud`.

**Comandos nuevos**: `/cancelar` (descarta la sesión abierta), `/estado` (muestra la sesión
en curso).

**Rehecho**: `/hoy` pasa a mostrar la sesión del día y el check-in. `/editar` y `/borrar`
hoy aceptan `<tipo>` en `transaccion|peso|salud|sesion`; se reducen a `sesion` y `set`.

**Se conservan**: `/start`, `/help`, `/gym`, `/sesiones`, `/export`, `/backup`.

**Se elimina**: todo el manejo de audio (`src/ai/whisper_client.py`,
`src/ai/audio_converter.py`, el handler de voz) y las dependencias `pydub` y `ffmpeg`.

## Rol del LLM

Se reduce a dos usos, ambos poco frecuentes:

1. Canonizar un ejercicio nuevo.
2. Fallback cuando el router determinístico no entiende un mensaje.

`prompts/parser.txt` se reescribe entero para el dominio gym-only. Esto elimina de raíz dos
de los tres bugs de prompt detectados en el benchmark previo (`tipo_sesion` sin listar,
`sueno_calidad` sin tipar), que pertenecían a dominios que ahora desaparecen.

Se adopta `openai/gpt-oss-120b` como `GROQ_LLM_MODEL` (16/18 contra 14/18 de
`llama-3.3-70b-versatile` en el benchmark). Al salir del camino crítico, su mayor latencia
deja de importar.

## Dashboard web

`/finanzas` y `/salud` rompen con el drop de tablas: se eliminan junto a sus templates y a
las consultas correspondientes de `src/web/queries.py`.

Se conservan el índice y `/gym`. Se agrega `/checkin` con las series temporales y los cruces
que justifican el registro nocturno: puntaje promedio en días con gimnasio vs. sin, horas de
sueño vs. volumen levantado, frecuencia semanal.

## Testing

Se eliminan los tests de finanzas, peso y salud.

Nuevos, todos offline salvo el fallback del LLM (que se mockea):

- **Matcher difuso**: tabla de casos con typos reales (`dominasas`, `remo t`, `press banka`),
  incluyendo casos negativos que no deben matchear.
- **Router de captura**: tabla de entrada → efecto, cubriendo cada fila de la tabla del router.
- **Máquina de estados**: apertura, cambio de ejercicio, peso pegajoso, `deshacer` sobre
  sesión vacía, cierre.
- **Autocierre**: sesión con `ultima_actividad` vieja se cierra; una reciente no.
- **Check-in**: avance paso a paso, persistencia parcial ante abandono, recordatorio que
  dispara solo si sigue pendiente.
- **Migración**: upgrade sobre una base con datos, verificando que los ejercicios y sesiones
  existentes sobrevivan.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Sesión abierta por accidente al mandar un mensaje suelto | El bot confirma la apertura; `/cancelar` la descarta |
| Match difuso agresivo (`remo` → `remo_unilateral`) | Match exacto primero, cutoff conservador, eco del bot |
| El router del check-in y el de gym se pisan | Prioridad explícita vía `group=-1` y `ApplicationHandlerStop` |
| Pérdida de datos en la migración | Backup automático del `.db` antes del upgrade |

## Fases

1. Migración: backup, drop de tablas, cambios en `gym_sesion`, tabla `checkin`.
2. Matcher de ejercicios (con su suite de tests).
3. Router y máquina de estados de captura, más el autocierre.
4. Limpieza de superficie: comandos, audio, prompt del parser, modelo.
5. Check-in nocturno.
6. Dashboard: sacar finanzas/salud, agregar `/checkin`.

La fase 6 es recortable sin romper nada si se decide cortar antes.
