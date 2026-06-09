# Changelog

Todas las versiones notables de Personal Tracker Bot.

## [1.0.0] — 2026-06-09

Primera versión funcional del MVP. Bot de Telegram single-user que registra
finanzas, gimnasio, peso corporal y salud diaria a partir de texto o audio en
lenguaje natural, con confirmación previa antes de persistir.

### Hitos completados

- **Infra** — scaffold del proyecto, `pyproject.toml`, `ruff`, dependencias y `.env.example`.
- **Config + DB** — `Settings` con Pydantic, modelos SQLAlchemy 2.0 y migración inicial Alembic (modo WAL).
- **Dominio** — schemas Pydantic del parser y catálogos (categorías, métodos de pago, tipos de sesión).
- **IA** — parser estructurado contra Groq (`llama-3.3-70b-versatile`) con reintentos de validación y transcripción Whisper (`whisper-large-v3`).
- **Audio** — descarga, conversión a OGG con `ffmpeg`/`pydub` y transcripción.
- **Repositorios** — CRUD transaccional por módulo, alta automática de ejercicios canónicos.
- **Bot — texto** — flujo autenticado por `chat_id`, preview persistente con botones `Guardar`/`Cancelar`/`Corregir` y expiración a 10 minutos.
- **Bot — consultas** — `/balance`, `/gastos`, `/ingresos`, `/ultimos`, `/gym`, `/sesiones`, `/peso`, `/salud`, `/hoy`.
- **Bot — mantenimiento** — `/editar` y `/borrar` guiados con confirmación inline.
- **Backups** — `src/backup.py` con snapshot consistente vía `sqlite3.backup`, retención por días, comandos `/backup` y `/export`, y job nocturno con `JobQueue`.
- **Logging** — `loguru` a `logs/tracker.log` con rotación y enmascarado de secretos.
- **Robustez (§12)** — backoff exponencial ante caída de Groq (3 intentos, base 2s) con fallback a `pendiente` y aviso al usuario; throttling de 1 msg/seg para el backlog acumulado al arrancar; advertencia en el preview ante fecha futura y valores de peso (30-300 kg) o sueño (1-16 h) fuera de rango; límite de audio alineado a 25 MB.

### Pruebas

- 87 tests unitarios pasando; 2 tests `--live` (Groq) se saltan sin API key.
- Lint y formato `ruff` limpios.
