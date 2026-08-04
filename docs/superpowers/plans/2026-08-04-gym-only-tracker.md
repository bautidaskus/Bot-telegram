# Gym-Only Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir el Personal Tracker Bot en un tracker exclusivo de gimnasio con captura conversacional incremental, matching difuso de ejercicios y un check-in nocturno respondible con taps.

**Architecture:** La captura es una máquina de estados cuyo estado vive en `gym_sesion` (no en memoria), de modo que sobrevive reinicios. Un parser puro convierte cada mensaje en un comando tipado sin tocar la base; un servicio aplica ese comando. El LLM sale del camino crítico y queda solo para dar de alta ejercicios nuevos y como fallback de mensajes no reconocidos.

**Tech Stack:** Python 3.11, python-telegram-bot 21.x (job-queue), SQLAlchemy 2.0, Alembic, Pydantic 2, Flask 3, `difflib` (stdlib), pytest, ruff, loguru.

**Spec:** `docs/superpowers/specs/2026-08-04-gym-only-tracker-design.md`

## Global Constraints

- Single-user: todo handler valida `is_authorized(update, allowed_chat_id)` antes de actuar.
- Idioma de código, docstrings y mensajes al usuario: español. Docstrings de una línea, estilo del repo.
- `ruff check .` y `ruff format --check .` deben pasar limpios. Línea máxima según `pyproject.toml`.
- Sin dependencias nuevas. `difflib` es stdlib; `pydub` se elimina.
- Cada serie se persiste al recibirse. Ningún flujo acumula datos en memoria a la espera de un "guardar".
- Como máximo una `gym_sesion` con `estado = 'abierta'` a la vez.
- Autocierre de sesión: 3 horas sin actividad.
- Check-in: 22:00, recordatorio único a las 23:00 si sigue `pendiente`.
- Los tests no hacen llamadas de red: el LLM se mockea siempre.

## File Structure

**Nuevos:**
- `src/gym/__init__.py` — paquete
- `src/gym/matcher.py` — normalización y matching difuso de ejercicios (puro, sin I/O)
- `src/gym/capture.py` — parseo de un mensaje a comando tipado (puro, sin I/O)
- `src/gym/session_service.py` — aplica comandos sobre la base
- `src/bot/gym_handlers.py` — glue de Telegram para la captura
- `src/bot/checkin.py` — flujo del check-in nocturno
- `alembic/versions/20260804_02_gym_only.py` — migración
- `src/web/templates/checkin.html` — página de check-in

**Modificados:**
- `src/db/models.py` — dropea 3 modelos, extiende `GymSesion`, agrega `Checkin`
- `src/db/repositories.py` — dropea 3 repos, extiende `GymRepository`, agrega `CheckinRepository`
- `src/bot/callbacks.py` — agrega callbacks de check-in
- `src/bot/commands.py` — dropea comandos financieros/salud, rehace `/hoy`
- `src/bot/maintenance.py` — reduce tipos a `sesion` y `set`
- `src/bot/handlers.py` — queda solo el fallback LLM; sale el audio
- `src/main.py` — rewiring de handlers y jobs
- `src/web/__init__.py`, `src/web/queries.py` — saca finanzas/salud, agrega check-in
- `prompts/parser.txt` — reescrito para dominio gym-only
- `.env.example`, `requirements.txt`, `README.md`

**Eliminados:**
- `src/ai/whisper_client.py`, `src/ai/audio_converter.py`
- `src/web/templates/finances.html`, `src/web/templates/health.html`
- `tests/test_audio_converter.py`, `tests/test_audio_handler.py`, `tests/test_whisper_client.py`

---

### Task 1: Modelos y migración

**Files:**
- Modify: `src/db/models.py`
- Create: `alembic/versions/20260804_02_gym_only.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Consumes: nada (primera tarea)
- Produces: `GymSesion` con `etiqueta: str`, `estado: str`, `ejercicio_actual_id: int | None`, `peso_actual: Decimal | None`, `ultima_actividad: datetime`, `cerrada_en: datetime | None`. `Checkin` con PK `fecha: date` y campos `puntaje_dia`, `animo`, `energia`, `hora_acostado`, `mejor_del_dia`, `estado`.

- [ ] **Step 1: Escribir el test de migración que falla**

En `tests/test_migrations.py`, agregar:

```python
def test_upgrade_drops_finance_and_adds_checkin(tmp_path: Path) -> None:
    db_path = tmp_path / "migrate.db"
    _run_alembic(db_path, "upgrade", "20260608_01")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO gym_sesion (fecha, tipo) VALUES ('2026-08-01', 'push')"
        )
        connection.commit()

    _run_alembic(db_path, "upgrade", "head")

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"transaccion", "peso", "salud"}.isdisjoint(tables)
        assert "checkin" in tables
        columns = {row[1] for row in connection.execute("PRAGMA table_info(gym_sesion)")}
        assert {"etiqueta", "estado", "ejercicio_actual_id", "peso_actual", "ultima_actividad"} <= columns
        assert "tipo" not in columns
        assert connection.execute("SELECT COUNT(*) FROM gym_sesion").fetchone()[0] == 1
```

Si `_run_alembic` no existe en el archivo, agregarlo:

```python
def _run_alembic(db_path: Path, *args: str) -> None:
    environment = {**os.environ, "DB_PATH": str(db_path)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `pytest tests/test_migrations.py::test_upgrade_drops_finance_and_adds_checkin -v`
Expected: FAIL — no existe la revisión `20260804_02`, `checkin` no está entre las tablas.

- [ ] **Step 3: Actualizar los modelos**

En `src/db/models.py`: borrar las clases `Transaccion`, `Peso` y `Salud`. Reemplazar `GymSesion` por:

```python
class GymSesion(Base):
    """Entrenamiento, abierto durante la captura y cerrado al terminar."""

    __tablename__ = "gym_sesion"
    __table_args__ = (
        CheckConstraint("estado IN ('abierta', 'cerrada')", name="ck_gym_sesion_estado"),
        Index("idx_sesion_estado", "estado"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fecha: Mapped[date] = mapped_column(Date)
    etiqueta: Mapped[str | None] = mapped_column(String(100))
    estado: Mapped[str] = mapped_column(String(10), default="abierta")
    ejercicio_actual_id: Mapped[int | None] = mapped_column(ForeignKey("ejercicio.id"))
    peso_actual: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    duracion_min: Mapped[int | None]
    notas: Mapped[str | None] = mapped_column(Text)
    ultima_actividad: Mapped[datetime] = mapped_column(DateTime)
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    mensaje_original: Mapped[str | None] = mapped_column(Text)
    sets: Mapped[list[GymSet]] = relationship(
        back_populates="sesion", cascade="all, delete", order_by="GymSet.id"
    )
```

El `order_by` es necesario: sin él, el orden de `sesion.sets` no está garantizado y los tests
que verifican la secuencia de series serían intermitentes.

Agregar al final del archivo:

```python
class Checkin(Base):
    """Registro nocturno del día, respondido con taps."""

    __tablename__ = "checkin"
    __table_args__ = (
        CheckConstraint("puntaje_dia BETWEEN 1 AND 10", name="ck_checkin_puntaje"),
        CheckConstraint("animo BETWEEN 1 AND 10", name="ck_checkin_animo"),
        CheckConstraint("energia BETWEEN 1 AND 5", name="ck_checkin_energia"),
    )

    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    puntaje_dia: Mapped[int | None]
    animo: Mapped[int | None]
    energia: Mapped[int | None]
    hora_acostado: Mapped[str | None] = mapped_column(String(11))
    mejor_del_dia: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
```

- [ ] **Step 4: Escribir la migración**

Crear `alembic/versions/20260804_02_gym_only.py`:

```python
"""Reduce el dominio a gimnasio y agrega el check-in nocturno."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260804_02"
down_revision = "20260608_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("transaccion")
    op.drop_table("peso")
    op.drop_table("salud")

    with op.batch_alter_table("gym_sesion") as batch:
        batch.add_column(sa.Column("etiqueta", sa.String(100)))
        batch.add_column(sa.Column("estado", sa.String(10), nullable=False, server_default="cerrada"))
        batch.add_column(sa.Column("ejercicio_actual_id", sa.Integer, sa.ForeignKey("ejercicio.id")))
        batch.add_column(sa.Column("peso_actual", sa.Numeric(7, 2)))
        batch.add_column(sa.Column("ultima_actividad", sa.DateTime))
        batch.add_column(sa.Column("cerrada_en", sa.DateTime))

    op.execute("UPDATE gym_sesion SET etiqueta = tipo, ultima_actividad = creado_en")

    with op.batch_alter_table("gym_sesion") as batch:
        batch.drop_column("tipo")
        batch.create_check_constraint("ck_gym_sesion_estado", "estado IN ('abierta', 'cerrada')")
    op.create_index("idx_sesion_estado", "gym_sesion", ["estado"])

    op.create_table(
        "checkin",
        sa.Column("fecha", sa.Date, primary_key=True),
        sa.Column("puntaje_dia", sa.Integer),
        sa.Column("animo", sa.Integer),
        sa.Column("energia", sa.Integer),
        sa.Column("hora_acostado", sa.String(11)),
        sa.Column("mejor_del_dia", sa.Text),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("creado_en", sa.DateTime, server_default=sa.func.current_timestamp()),
        sa.Column("actualizado_en", sa.DateTime, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("puntaje_dia BETWEEN 1 AND 10", name="ck_checkin_puntaje"),
        sa.CheckConstraint("animo BETWEEN 1 AND 10", name="ck_checkin_animo"),
        sa.CheckConstraint("energia BETWEEN 1 AND 5", name="ck_checkin_energia"),
    )


def downgrade() -> None:
    raise NotImplementedError("Migración irreversible: dropea tablas con datos")
```

Las sesiones preexistentes quedan en `estado = 'cerrada'` (el `server_default`), que es lo correcto: son entrenamientos ya terminados.

- [ ] **Step 5: Correr el test para verificar que pasa**

Run: `pytest tests/test_migrations.py -v`
Expected: PASS

- [ ] **Step 6: Backup real y aplicar la migración a la base de producción**

```bash
.venv/Scripts/python.exe -c "from pathlib import Path; from src.backup import crear_backup; print(crear_backup(Path('data/tracker.db'), Path('data/backups')))"
.venv/Scripts/python.exe -m alembic upgrade head
```

Verificar que el backup existe en `data/backups/` **antes** de correr el upgrade. Si `src.backup` expone otro nombre de función, usar el que exista (leer `src/backup.py`).

- [ ] **Step 7: Commit**

```bash
git add src/db/models.py alembic/versions/20260804_02_gym_only.py tests/test_migrations.py
git commit -m "feat(db): reducir el dominio a gimnasio y agregar check-in"
```

---

### Task 2: Repositorios

**Files:**
- Modify: `src/db/repositories.py`
- Test: `tests/test_repositories.py`

**Interfaces:**
- Consumes: `GymSesion`, `Checkin`, `Ejercicio`, `GymSet` de Task 1
- Produces:
  - `GymRepository.open_session(fecha, etiqueta, now) -> GymSesion`
  - `GymRepository.get_open_session() -> GymSesion | None`
  - `GymRepository.set_current_exercise(sesion_id, ejercicio_id, peso_kg) -> None`
  - `GymRepository.append_set(sesion_id, ejercicio_id, reps, peso_kg, now) -> GymSet`
  - `GymRepository.undo_last_set(sesion_id) -> GymSet | None`
  - `GymRepository.close_session(sesion_id, now) -> GymSesion`
  - `GymRepository.list_stale_open_sessions(cutoff) -> list[GymSesion]`
  - `GymRepository.get_or_create_exercise(canonical, grupo_muscular) -> Ejercicio`
  - `GymRepository.add_alias(ejercicio_id, alias) -> None`
  - `CheckinRepository.get_or_create(fecha) -> Checkin`, `.update(fecha, **changes) -> Checkin`

- [ ] **Step 1: Escribir los tests que fallan**

Reemplazar `tests/test_repositories.py` (los tests de finanzas/peso/salud se borran) por:

```python
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, GymSet
from src.db.repositories import CheckinRepository, GymRepository
from src.db.session import create_sqlite_engine

NOW = datetime(2026, 8, 4, 19, 0)


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "repository.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_open_session_is_unique_and_findable(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        opened = repository.open_session(fecha=NOW.date(), etiqueta="espalda biceps", now=NOW)
        session.commit()

        assert opened.estado == "abierta"
        assert repository.get_open_session() is opened


def test_append_and_undo_sets(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        gym_session = repository.open_session(fecha=NOW.date(), etiqueta="pull", now=NOW)
        exercise = repository.get_or_create_exercise("dominadas")
        session.commit()

        first = repository.append_set(
            sesion_id=gym_session.id, ejercicio_id=exercise.id, reps=7, peso_kg=None, now=NOW
        )
        second = repository.append_set(
            sesion_id=gym_session.id, ejercicio_id=exercise.id, reps=6, peso_kg=None, now=NOW
        )
        session.commit()

        assert (first.serie_num, second.serie_num) == (1, 2)
        assert repository.undo_last_set(gym_session.id) is not None
        session.commit()
        remaining = session.scalars(
            select(GymSet).where(GymSet.sesion_id == gym_session.id)
        ).all()
        assert len(remaining) == 1


def test_undo_on_empty_session_returns_none(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        gym_session = repository.open_session(fecha=NOW.date(), etiqueta="pull", now=NOW)
        session.commit()

        assert repository.undo_last_set(gym_session.id) is None


def test_stale_sessions_only_include_inactive_open_ones(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        stale = repository.open_session(
            fecha=NOW.date(), etiqueta="vieja", now=NOW - timedelta(hours=4)
        )
        session.commit()
        cutoff = NOW - timedelta(hours=3)

        assert repository.list_stale_open_sessions(cutoff) == [stale]

        repository.close_session(stale.id, now=NOW)
        session.commit()
        assert repository.list_stale_open_sessions(cutoff) == []


def test_aliases_accumulate_without_duplicates(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        exercise = repository.get_or_create_exercise("dominadas")
        session.commit()

        repository.add_alias(exercise.id, "dominasas")
        repository.add_alias(exercise.id, "dominasas")
        session.commit()

        assert repository.aliases_for(exercise.id) == ["dominasas"]


def test_checkin_partial_updates_persist(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = CheckinRepository(session)
        repository.get_or_create(NOW.date())
        session.commit()

        repository.update(NOW.date(), puntaje_dia=8)
        session.commit()
        repository.update(NOW.date(), animo=6, estado="completo")
        session.commit()

        stored = repository.get_or_create(NOW.date())
        assert (stored.puntaje_dia, stored.animo, stored.estado) == (8, 6, "completo")
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_repositories.py -v`
Expected: FAIL con `ImportError: cannot import name 'CheckinRepository'`

- [ ] **Step 3: Implementar los repositorios**

En `src/db/repositories.py`: borrar `FinanceRepository`, `WeightRepository`, `HealthRepository` y `WeightAlreadyExistsError`. Ajustar el import a `from src.db.models import Checkin, Ejercicio, GymSesion, GymSet`. Reemplazar `GymRepository` por:

```python
class GymRepository:
    """Persistencia de sesiones, ejercicios y series."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def open_session(self, *, fecha: date, etiqueta: str, now: datetime) -> GymSesion:
        gym_session = GymSesion(
            fecha=fecha, etiqueta=etiqueta, estado="abierta", ultima_actividad=now
        )
        self.session.add(gym_session)
        self.session.flush()
        return gym_session

    def get_open_session(self) -> GymSesion | None:
        return self.session.scalar(select(GymSesion).where(GymSesion.estado == "abierta"))

    def set_current_exercise(
        self, sesion_id: int, ejercicio_id: int, peso_kg: Decimal | None
    ) -> None:
        gym_session = self.session.get_one(GymSesion, sesion_id)
        gym_session.ejercicio_actual_id = ejercicio_id
        gym_session.peso_actual = peso_kg
        self.session.flush()

    def append_set(
        self,
        *,
        sesion_id: int,
        ejercicio_id: int,
        reps: int,
        peso_kg: Decimal | None,
        now: datetime,
    ) -> GymSet:
        last = self.session.scalar(
            select(func.max(GymSet.serie_num)).where(
                GymSet.sesion_id == sesion_id, GymSet.ejercicio_id == ejercicio_id
            )
        )
        gym_set = GymSet(
            sesion_id=sesion_id,
            ejercicio_id=ejercicio_id,
            serie_num=(last or 0) + 1,
            reps=reps,
            peso_kg=peso_kg,
        )
        self.session.add(gym_set)
        self.session.get_one(GymSesion, sesion_id).ultima_actividad = now
        self.session.flush()
        return gym_set

    def undo_last_set(self, sesion_id: int) -> GymSet | None:
        gym_set = self.session.scalar(
            select(GymSet).where(GymSet.sesion_id == sesion_id).order_by(GymSet.id.desc()).limit(1)
        )
        if gym_set is not None:
            self.session.delete(gym_set)
            self.session.flush()
        return gym_set

    def close_session(self, sesion_id: int, *, now: datetime) -> GymSesion:
        gym_session = self.session.get_one(GymSesion, sesion_id)
        gym_session.estado = "cerrada"
        gym_session.cerrada_en = now
        self.session.flush()
        return gym_session

    def list_stale_open_sessions(self, cutoff: datetime) -> list[GymSesion]:
        statement = select(GymSesion).where(
            GymSesion.estado == "abierta", GymSesion.ultima_actividad < cutoff
        )
        return list(self.session.scalars(statement))

    def get_session(self, session_id: int) -> GymSesion | None:
        return self.session.get(GymSesion, session_id)

    def list_sessions(self, limit: int = 5) -> list[GymSesion]:
        statement = select(GymSesion).order_by(GymSesion.fecha.desc(), GymSesion.id.desc())
        return list(self.session.scalars(statement.limit(limit)))

    def list_exercises(self) -> list[Ejercicio]:
        statement = select(Ejercicio).order_by(Ejercicio.nombre_canonico)
        return list(self.session.scalars(statement))

    def get_or_create_exercise(
        self, canonical_name: str, grupo_muscular: str | None = None
    ) -> Ejercicio:
        exercise = self.session.scalar(
            select(Ejercicio).where(Ejercicio.nombre_canonico == canonical_name)
        )
        if exercise is None:
            exercise = Ejercicio(nombre_canonico=canonical_name, grupo_muscular=grupo_muscular)
            self.session.add(exercise)
            self.session.flush()
        return exercise

    def aliases_for(self, ejercicio_id: int) -> list[str]:
        exercise = self.session.get_one(Ejercicio, ejercicio_id)
        return json.loads(exercise.alias_json) if exercise.alias_json else []

    def add_alias(self, ejercicio_id: int, alias: str) -> None:
        exercise = self.session.get_one(Ejercicio, ejercicio_id)
        aliases = json.loads(exercise.alias_json) if exercise.alias_json else []
        if alias not in aliases:
            aliases.append(alias)
            exercise.alias_json = json.dumps(aliases, ensure_ascii=False)
            self.session.flush()

    def update_session(self, session_id: int, **changes: Any) -> GymSesion:
        gym_session = self.session.get_one(GymSesion, session_id)
        for field, value in changes.items():
            setattr(gym_session, field, value)
        self.session.flush()
        return gym_session

    def delete_session(self, session_id: int) -> None:
        self.session.delete(self.session.get_one(GymSesion, session_id))


class CheckinRepository:
    """Persistencia del registro nocturno, actualizado paso a paso."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(self, fecha: date) -> Checkin:
        checkin = self.session.get(Checkin, fecha)
        if checkin is None:
            checkin = Checkin(fecha=fecha)
            self.session.add(checkin)
            self.session.flush()
        return checkin

    def update(self, fecha: date, **changes: Any) -> Checkin:
        checkin = self.get_or_create(fecha)
        for field, value in changes.items():
            setattr(checkin, field, value)
        self.session.flush()
        return checkin

    def list_recent(self, limit: int = 30) -> list[Checkin]:
        statement = select(Checkin).order_by(Checkin.fecha.desc()).limit(limit)
        return list(self.session.scalars(statement))
```

Agregar `import json` y `from datetime import date, datetime` arriba, y `from sqlalchemy import func, select`.

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_repositories.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/db/repositories.py tests/test_repositories.py
git commit -m "feat(db): repositorios de sesion abierta y check-in"
```

---

### Task 3: Matcher difuso de ejercicios

**Files:**
- Create: `src/gym/__init__.py`, `src/gym/matcher.py`
- Test: `tests/test_matcher.py`

**Interfaces:**
- Consumes: nada (módulo puro)
- Produces:
  - `normalize(text: str) -> str`
  - `CatalogEntry(exercise_id: int, canonical: str, aliases: list[str])` — dataclass frozen
  - `MatchResult(exercise_id: int, canonical: str, learned_alias: str | None)` — dataclass frozen
  - `match_exercise(raw: str, catalog: list[CatalogEntry], cutoff: float = 0.8) -> MatchResult | None`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_matcher.py`:

```python
from __future__ import annotations

import pytest

from src.gym.matcher import CatalogEntry, match_exercise, normalize

CATALOG = [
    CatalogEntry(exercise_id=1, canonical="dominadas", aliases=[]),
    CatalogEntry(exercise_id=2, canonical="remo_unilateral", aliases=["remo uni"]),
    CatalogEntry(exercise_id=3, canonical="press_banca", aliases=[]),
]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Dominadas", "dominadas"),
        ("  DOMINADAS  ", "dominadas"),
        ("press banca", "press banca"),
        ("press_banca", "press banca"),
        ("Bíceps", "biceps"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_exact_match_on_canonical_learns_nothing() -> None:
    result = match_exercise("press banca", CATALOG)
    assert result is not None
    assert (result.exercise_id, result.canonical, result.learned_alias) == (3, "press_banca", None)


def test_exact_match_on_alias() -> None:
    result = match_exercise("remo uni", CATALOG)
    assert result is not None
    assert result.exercise_id == 2
    assert result.learned_alias is None


def test_typo_matches_and_learns_alias() -> None:
    result = match_exercise("dominasas", CATALOG)
    assert result is not None
    assert result.canonical == "dominadas"
    assert result.learned_alias == "dominasas"


def test_unknown_exercise_returns_none() -> None:
    assert match_exercise("remo t", CATALOG) is None


def test_short_unrelated_input_does_not_match() -> None:
    assert match_exercise("curl", CATALOG) is None
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_matcher.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.gym'`

- [ ] **Step 3: Implementar el matcher**

Crear `src/gym/__init__.py` vacío y `src/gym/matcher.py`:

```python
"""Resolución de nombres de ejercicios escritos de cualquier forma."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from difflib import get_close_matches


@dataclass(frozen=True)
class CatalogEntry:
    """Ejercicio conocido con sus alias aprendidos."""

    exercise_id: int
    canonical: str
    aliases: list[str]


@dataclass(frozen=True)
class MatchResult:
    """Ejercicio resuelto y, si hubo que aproximar, el alias a aprender."""

    exercise_id: int
    canonical: str
    learned_alias: str | None


def normalize(text: str) -> str:
    """Baja a minúsculas, saca acentos y unifica guiones bajos con espacios."""

    decomposed = unicodedata.normalize("NFD", text.strip().lower())
    without_accents = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return " ".join(without_accents.replace("_", " ").split())


def match_exercise(
    raw: str, catalog: list[CatalogEntry], cutoff: float = 0.8
) -> MatchResult | None:
    """Resuelve un nombre por coincidencia exacta y, si falla, por distancia de edición."""

    needle = normalize(raw)
    if not needle:
        return None
    index: dict[str, CatalogEntry] = {}
    for entry in catalog:
        index[normalize(entry.canonical)] = entry
        for alias in entry.aliases:
            index.setdefault(normalize(alias), entry)
    if needle in index:
        entry = index[needle]
        return MatchResult(entry.exercise_id, entry.canonical, learned_alias=None)
    approximations = get_close_matches(needle, list(index), n=1, cutoff=cutoff)
    if not approximations:
        return None
    entry = index[approximations[0]]
    return MatchResult(entry.exercise_id, entry.canonical, learned_alias=needle)
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_matcher.py -v`
Expected: PASS (10 tests contando los parametrizados)

Si `test_short_unrelated_input_does_not_match` falla porque `curl` se acerca demasiado a alguna entrada, subir `cutoff` a `0.85` y volver a correr toda la suite.

- [ ] **Step 5: Commit**

```bash
git add src/gym/__init__.py src/gym/matcher.py tests/test_matcher.py
git commit -m "feat(gym): matcher difuso de ejercicios con aprendizaje de alias"
```

---

### Task 4: Parser de mensajes de captura

**Files:**
- Create: `src/gym/capture.py`
- Test: `tests/test_capture.py`

**Interfaces:**
- Consumes: nada (módulo puro)
- Produces:
  - `SetInput(reps: int, peso_kg: Decimal | None)` — dataclass frozen
  - `FinishSession()`, `UndoLastSet()`, `AddSets(sets: list[SetInput])`, `SwitchExercise(raw_name: str, peso_kg: Decimal | None)`, `Unrecognized(text: str)` — dataclasses frozen
  - `CaptureCommand` — alias de la unión
  - `parse_capture_message(text: str) -> CaptureCommand`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_capture.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest

from src.gym.capture import (
    AddSets,
    FinishSession,
    SetInput,
    SwitchExercise,
    UndoLastSet,
    Unrecognized,
    parse_capture_message,
)


@pytest.mark.parametrize("text", ["fin", "FIN", "listo", "terminé", "terminar"])
def test_finish_keywords(text: str) -> None:
    assert parse_capture_message(text) == FinishSession()


@pytest.mark.parametrize("text", ["deshacer", "borrar", "Deshacer"])
def test_undo_keywords(text: str) -> None:
    assert parse_capture_message(text) == UndoLastSet()


def test_single_number_is_one_set_at_current_weight() -> None:
    assert parse_capture_message("7") == AddSets([SetInput(reps=7, peso_kg=None)])


@pytest.mark.parametrize("text", ["10 8 6", "10,8,6", "10, 8, 6"])
def test_multiple_numbers_are_multiple_sets(text: str) -> None:
    assert parse_capture_message(text) == AddSets(
        [SetInput(reps=10, peso_kg=None), SetInput(reps=8, peso_kg=None), SetInput(reps=6, peso_kg=None)]
    )


def test_explicit_weight_by_reps() -> None:
    assert parse_capture_message("60x10") == AddSets([SetInput(reps=10, peso_kg=Decimal("60"))])


def test_mixed_explicit_and_bare_sets() -> None:
    assert parse_capture_message("60x10 8") == AddSets(
        [SetInput(reps=10, peso_kg=Decimal("60")), SetInput(reps=8, peso_kg=None)]
    )


def test_exercise_with_trailing_weight() -> None:
    assert parse_capture_message("remo t 60") == SwitchExercise(
        raw_name="remo t", peso_kg=Decimal("60")
    )


def test_exercise_with_decimal_weight() -> None:
    assert parse_capture_message("press banca 62.5") == SwitchExercise(
        raw_name="press banca", peso_kg=Decimal("62.5")
    )


def test_exercise_without_weight() -> None:
    assert parse_capture_message("dominadas") == SwitchExercise(raw_name="dominadas", peso_kg=None)


def test_prose_with_interleaved_numbers_is_unrecognized() -> None:
    assert parse_capture_message("hice 3 series de 10 con 60") == Unrecognized(
        "hice 3 series de 10 con 60"
    )


def test_empty_message_is_unrecognized() -> None:
    assert parse_capture_message("   ") == Unrecognized("   ")
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_capture.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.gym.capture'`

- [ ] **Step 3: Implementar el parser**

Crear `src/gym/capture.py`:

```python
"""Traducción de un mensaje suelto a un comando de captura, sin tocar la base."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

FINISH_WORDS = {"fin", "listo", "termine", "terminé", "terminar", "fin."}
UNDO_WORDS = {"deshacer", "borrar", "undo"}
_SET_PATTERN = re.compile(r"^(?:(\d+(?:[.,]\d+)?)[x*])?(\d+)$")


@dataclass(frozen=True)
class SetInput:
    """Serie a registrar; `peso_kg` en None usa el peso vigente del ejercicio."""

    reps: int
    peso_kg: Decimal | None


@dataclass(frozen=True)
class FinishSession:
    """Cierra la sesión abierta."""


@dataclass(frozen=True)
class UndoLastSet:
    """Elimina la última serie registrada."""


@dataclass(frozen=True)
class AddSets:
    """Agrega una o más series al ejercicio actual."""

    sets: list[SetInput]


@dataclass(frozen=True)
class SwitchExercise:
    """Cambia el ejercicio actual y opcionalmente fija su peso."""

    raw_name: str
    peso_kg: Decimal | None


@dataclass(frozen=True)
class Unrecognized:
    """Mensaje que el router determinístico no supo interpretar."""

    text: str


CaptureCommand = FinishSession | UndoLastSet | AddSets | SwitchExercise | Unrecognized


def parse_capture_message(text: str) -> CaptureCommand:
    """Interpreta un mensaje dentro de una sesión abierta."""

    stripped = text.strip()
    lowered = stripped.lower()
    if lowered in FINISH_WORDS:
        return FinishSession()
    if lowered in UNDO_WORDS:
        return UndoLastSet()
    tokens = lowered.replace(",", " ").split()
    if not tokens:
        return Unrecognized(text)

    sets = _parse_sets(tokens)
    if sets is not None:
        return AddSets(sets)

    weight = _parse_decimal(tokens[-1])
    if weight is not None:
        name_tokens = tokens[:-1]
        if name_tokens and all(token.isalpha() for token in name_tokens):
            return SwitchExercise(raw_name=" ".join(name_tokens), peso_kg=weight)
        return Unrecognized(text)
    if all(token.isalpha() for token in tokens):
        return SwitchExercise(raw_name=" ".join(tokens), peso_kg=None)
    return Unrecognized(text)


def _parse_sets(tokens: list[str]) -> list[SetInput] | None:
    """Devuelve las series si todos los tokens son `reps` o `pesoxreps`."""

    parsed: list[SetInput] = []
    for token in tokens:
        match = _SET_PATTERN.match(token)
        if match is None:
            return None
        weight = _parse_decimal(match.group(1)) if match.group(1) else None
        parsed.append(SetInput(reps=int(match.group(2)), peso_kg=weight))
    return parsed


def _parse_decimal(token: str | None) -> Decimal | None:
    if token is None:
        return None
    try:
        return Decimal(token.replace(",", "."))
    except InvalidOperation:
        return None
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_capture.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gym/capture.py tests/test_capture.py
git commit -m "feat(gym): parser deterministico de mensajes de captura"
```

---

### Task 5: Servicio de sesión

**Files:**
- Create: `src/gym/session_service.py`
- Test: `tests/test_session_service.py`

**Interfaces:**
- Consumes: `GymRepository` (Task 2), `match_exercise`/`CatalogEntry` (Task 3), `parse_capture_message` y comandos (Task 4)
- Produces:
  - `CanonicalizerProtocol.canonicalize(raw: str) -> tuple[str, str | None]` — devuelve `(nombre_snake_case, grupo_muscular)`
  - `GymSessionService(session, canonicalizer, now)` con `handle(text: str) -> str` (devuelve el texto de respuesta) y `close_stale(cutoff: datetime) -> list[int]`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_session_service.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base
from src.db.repositories import GymRepository
from src.gym.session_service import GymSessionService
from src.db.session import create_sqlite_engine

NOW = datetime(2026, 8, 4, 19, 0)


class FakeCanonicalizer:
    """Canonizador determinístico que reemplaza al LLM en los tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def canonicalize(self, raw: str) -> tuple[str, str | None]:
        self.calls.append(raw)
        return raw.replace(" ", "_"), "dorsal"


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "service.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _service(session: Session) -> GymSessionService:
    return GymSessionService(session, canonicalizer=FakeCanonicalizer(), now=lambda: NOW)


def test_first_message_opens_session(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        reply = _service(session).handle("espalda biceps")
        session.commit()

        assert "espalda biceps" in reply
        assert GymRepository(session).get_open_session() is not None


def test_full_capture_flow(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = _service(session)
        service.handle("espalda biceps")
        service.handle("dominadas")
        service.handle("7")
        service.handle("6")
        service.handle("remo t 60")
        service.handle("10")
        reply = service.handle("fin")
        session.commit()

        repository = GymRepository(session)
        assert repository.get_open_session() is None
        stored = repository.list_sessions(1)[0]
        assert len(stored.sets) == 3
        assert "2 ejercicios" in reply


def test_sticky_weight_applies_to_bare_reps(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = _service(session)
        service.handle("pull")
        service.handle("remo t 60")
        service.handle("10")
        session.commit()

        stored = GymRepository(session).get_open_session()
        assert stored.sets[0].peso_kg == 60


def test_explicit_set_does_not_change_sticky_weight(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        service = _service(session)
        service.handle("pull")
        service.handle("remo t 60")
        service.handle("80x5")
        service.handle("10")
        session.commit()

        stored = GymRepository(session).get_open_session()
        assert [item.peso_kg for item in stored.sets] == [80, 60]


def test_undo_removes_last_set(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = _service(session)
        service.handle("pull")
        service.handle("dominadas")
        service.handle("77")
        service.handle("deshacer")
        session.commit()

        assert GymRepository(session).get_open_session().sets == []


def test_reps_without_exercise_are_rejected(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = _service(session)
        service.handle("pull")
        reply = service.handle("7")
        session.commit()

        assert "ejercicio" in reply.lower()
        assert GymRepository(session).get_open_session().sets == []


def test_typo_matches_known_exercise_without_llm(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        canonicalizer = FakeCanonicalizer()
        service = GymSessionService(session, canonicalizer=canonicalizer, now=lambda: NOW)
        service.handle("pull")
        service.handle("dominadas")
        service.handle("dominasas")
        session.commit()

        assert canonicalizer.calls == ["dominadas"]


def test_close_stale_closes_only_inactive(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = GymSessionService(
            session, canonicalizer=FakeCanonicalizer(), now=lambda: NOW - timedelta(hours=4)
        )
        service.handle("vieja")
        session.commit()

        closed = GymSessionService(
            session, canonicalizer=FakeCanonicalizer(), now=lambda: NOW
        ).close_stale(NOW - timedelta(hours=3))
        session.commit()

        assert len(closed) == 1
        assert GymRepository(session).get_open_session() is None
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_session_service.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.gym.session_service'`

- [ ] **Step 3: Implementar el servicio**

Crear `src/gym/session_service.py`:

```python
"""Aplicación de comandos de captura sobre una sesión de gimnasio."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from src.db.models import GymSesion
from src.db.repositories import GymRepository
from src.gym.capture import (
    AddSets,
    FinishSession,
    SwitchExercise,
    UndoLastSet,
    Unrecognized,
    parse_capture_message,
)
from src.gym.matcher import CatalogEntry, match_exercise


class CanonicalizerProtocol(Protocol):
    """Da de alta un ejercicio desconocido a partir de texto libre."""

    def canonicalize(self, raw: str) -> tuple[str, str | None]:
        """Devuelve el nombre snake_case y el grupo muscular inferido."""


class GymSessionService:
    """Orquesta el ciclo de vida de la sesión y la escritura de series."""

    def __init__(
        self,
        session: Session,
        *,
        canonicalizer: CanonicalizerProtocol,
        now: Callable[[], datetime],
    ) -> None:
        self.repository = GymRepository(session)
        self.canonicalizer = canonicalizer
        self.now = now

    def handle(self, text: str) -> str:
        """Procesa un mensaje y devuelve la respuesta a mostrar."""

        open_session = self.repository.get_open_session()
        if open_session is None:
            etiqueta = text.strip()
            self.repository.open_session(
                fecha=self.now().date(), etiqueta=etiqueta, now=self.now()
            )
            return f"Sesión abierta: {etiqueta}"

        command = parse_capture_message(text)
        if isinstance(command, FinishSession):
            return self._finish(open_session.id)
        if isinstance(command, UndoLastSet):
            removed = self.repository.undo_last_set(open_session.id)
            return "Borré la última serie." if removed else "No hay series para borrar."
        if isinstance(command, SwitchExercise):
            return self._switch(open_session.id, command)
        if isinstance(command, AddSets):
            return self._add_sets(open_session, command)
        return self._fallback(open_session.id, command)

    def close_stale(self, cutoff: datetime) -> list[int]:
        """Cierra las sesiones sin actividad desde `cutoff` y devuelve sus ids."""

        stale = self.repository.list_stale_open_sessions(cutoff)
        for gym_session in stale:
            self.repository.close_session(gym_session.id, now=self.now())
        return [gym_session.id for gym_session in stale]

    def _catalog(self) -> list[CatalogEntry]:
        return [
            CatalogEntry(
                exercise_id=exercise.id,
                canonical=exercise.nombre_canonico,
                aliases=self.repository.aliases_for(exercise.id),
            )
            for exercise in self.repository.list_exercises()
        ]

    def _switch(self, sesion_id: int, command: SwitchExercise) -> str:
        match = match_exercise(command.raw_name, self._catalog())
        if match is None:
            canonical, grupo = self.canonicalizer.canonicalize(command.raw_name)
            exercise = self.repository.get_or_create_exercise(canonical, grupo)
            self.repository.set_current_exercise(sesion_id, exercise.id, command.peso_kg)
            suffix = f" @ {command.peso_kg}kg" if command.peso_kg is not None else ""
            return f"nuevo ejercicio: {canonical}{suffix}"
        if match.learned_alias is not None:
            self.repository.add_alias(match.exercise_id, match.learned_alias)
        self.repository.set_current_exercise(sesion_id, match.exercise_id, command.peso_kg)
        suffix = f" @ {command.peso_kg}kg" if command.peso_kg is not None else " (sin peso)"
        return f"→ {match.canonical}{suffix}"

    def _add_sets(self, open_session: GymSesion, command: AddSets) -> str:
        exercise_id = open_session.ejercicio_actual_id
        if exercise_id is None:
            return "Decime primero qué ejercicio estás haciendo."
        rendered: list[str] = []
        for item in command.sets:
            weight = item.peso_kg if item.peso_kg is not None else open_session.peso_actual
            self.repository.append_set(
                sesion_id=open_session.id,
                ejercicio_id=exercise_id,
                reps=item.reps,
                peso_kg=weight,
                now=self.now(),
            )
            rendered.append(f"{weight:g}x{item.reps}" if weight is not None else str(item.reps))
        name = next(
            item.nombre_canonico
            for item in self.repository.list_exercises()
            if item.id == exercise_id
        )
        return f"{name}: {', '.join(rendered)}"

    def _finish(self, sesion_id: int) -> str:
        closed = self.repository.close_session(sesion_id, now=self.now())
        exercises = {item.ejercicio_id for item in closed.sets}
        return f"Guardado: {len(exercises)} ejercicios, {len(closed.sets)} series."

    def _fallback(self, sesion_id: int, command: Unrecognized) -> str:
        return f"No entendí «{command.text}». Mandá reps (7), peso (remo t 60) o «fin»."
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_session_service.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gym/session_service.py tests/test_session_service.py
git commit -m "feat(gym): servicio de sesion con peso pegajoso y deshacer"
```

---

### Task 6: Fallback LLM y canonizador

**Files:**
- Modify: `src/ai/parser.py`, `prompts/parser.txt`
- Create: `prompts/canonicalizer.txt`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `CanonicalizerProtocol` (Task 5)
- Produces: `LLMCanonicalizer(client, model, prompt_path)` con `.canonicalize(raw) -> tuple[str, str | None]`, y `create_groq_canonicalizer(settings) -> LLMCanonicalizer`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_parser.py`:

```python
def test_canonicalizer_returns_snake_case_and_group() -> None:
    client = FakeClient(['{"nombre": "remo_t", "grupo_muscular": "dorsal"}'])
    canonicalizer = LLMCanonicalizer(
        client=client, model="test", prompt_path=Path("prompts/canonicalizer.txt")
    )

    assert canonicalizer.canonicalize("remo t") == ("remo_t", "dorsal")


def test_canonicalizer_falls_back_to_slug_on_invalid_output() -> None:
    client = FakeClient(["no soy json", "sigo sin serlo"])
    canonicalizer = LLMCanonicalizer(
        client=client, model="test", prompt_path=Path("prompts/canonicalizer.txt")
    )

    assert canonicalizer.canonicalize("remo t") == ("remo_t", None)
```

Reusar el doble de cliente que ya exista en el archivo; si se llama distinto, adaptar el nombre.

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_parser.py -v`
Expected: FAIL con `NameError: name 'LLMCanonicalizer' is not defined`

- [ ] **Step 3: Escribir el prompt del canonizador**

Crear `prompts/canonicalizer.txt`:

```
Convertís el nombre de un ejercicio de gimnasio escrito en español informal a un nombre
canónico.

Devolvé únicamente un objeto JSON con dos claves:
- "nombre": el nombre en snake_case, sin acentos, sin números, en singular cuando aplique.
- "grupo_muscular": uno de pecho, espalda, dorsal, hombro, biceps, triceps, pierna, gluteo,
  core, cardio, o null si no lo podés determinar.

Ejemplos:
"remo t" -> {{"nombre": "remo_t", "grupo_muscular": "dorsal"}}
"press banca inclinado" -> {{"nombre": "press_banca_inclinado", "grupo_muscular": "pecho"}}
"bici" -> {{"nombre": "bicicleta", "grupo_muscular": "cardio"}}

Ejercicios ya conocidos, reusá el nombre exacto si corresponde: {exercise_catalog}
```

- [ ] **Step 4: Implementar el canonizador**

Agregar a `src/ai/parser.py`:

```python
class LLMCanonicalizer:
    """Da de alta ejercicios nuevos a partir de texto libre."""

    def __init__(
        self,
        *,
        client: ClientProtocol,
        model: str,
        prompt_path: Path,
        catalog: list[str] | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.prompt = prompt_path.read_text(encoding="utf-8").format(
            exercise_catalog=", ".join(catalog or []) or "(vacío)"
        )

    def canonicalize(self, raw: str) -> tuple[str, str | None]:
        """Devuelve el nombre canónico y el grupo muscular, con fallback local."""

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.prompt},
                    {"role": "user", "content": raw},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            payload = json.loads(completion.choices[0].message.content or "")
            name = str(payload["nombre"])
            if not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", name):
                raise ValueError("nombre no canónico")
            grupo = payload.get("grupo_muscular")
            return name, str(grupo) if grupo else None
        except (TRANSIENT_ERRORS, json.JSONDecodeError, KeyError, ValueError, TypeError):
            return _slugify(raw), None


def _slugify(raw: str) -> str:
    """Fallback local cuando el LLM no está disponible o responde mal."""

    normalized = normalize(raw)
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_") or "ejercicio"


def create_groq_canonicalizer(
    settings: Settings,
    catalog: list[str] | None = None,
    prompt_path: Path = Path("prompts/canonicalizer.txt"),
) -> LLMCanonicalizer:
    """Construye el canonizador con el cliente compatible de Groq."""

    client = OpenAI(
        api_key=settings.groq_api_key.get_secret_value(), base_url=settings.groq_base_url
    )
    return LLMCanonicalizer(
        client=client, model=settings.groq_llm_model, prompt_path=prompt_path, catalog=catalog
    )
```

Agregar `import re` y `from src.gym.matcher import normalize` a los imports. `except (TRANSIENT_ERRORS, ...)` debe escribirse como `except (*TRANSIENT_ERRORS, json.JSONDecodeError, KeyError, ValueError, TypeError)`.

- [ ] **Step 5: Reescribir el prompt del parser para dominio gym-only**

Reemplazar `prompts/parser.txt` completo:

```
Sos un extractor de información estructurada para un tracker de gimnasio. Interpretás
mensajes en español rioplatense sobre series de ejercicios.

Devolvé siempre un único objeto JSON válido con una lista no vacía llamada "operaciones".
Cada operación tiene:
- "tipo": siempre "gym".
- "confianza": número entre 0 y 1.
- "fecha": texto original de fecha, por defecto "hoy".
- "datos": objeto con "ejercicios", lista no vacía.
- "explicacion": descripción breve, sin razonamiento interno.

Cada ejercicio lleva "nombre" canónico en snake_case sin acentos, y "sets": lista no vacía
donde cada elemento puede tener "peso_kg", "reps", "rpe" y "nota". No inventes valores
ausentes: omití las claves que no aparezcan en el mensaje.

"80 por 8, 8 y 6" son tres series de 8, 8 y 6 reps con 80 kg.
"100x5x3" son tres series de 5 reps con 100 kg.

Catálogo canónico existente, reusá estos nombres si corresponde: {exercise_catalog}
```

Actualizar `src/domain/schemas.py`: borrar `FinanceData`, `GastoData`, `IngresoData`, `PesoData`,
`SaludData`, `AmbiguoData` y sus `Operation` correspondientes, dejando `GymSetData`,
`GymExerciseData`, `GymData`, `GymOperation` y `ParserResponse`. En `GymData`, borrar el
validador `validate_session_type` y el campo `tipo_sesion`. Actualizar `src/domain/catalogo.py`
dejando solo lo que se siga usando (borrar `CATEGORIAS_GASTO`, `CATEGORIAS_INGRESO`,
`METODOS_PAGO`, `TIPOS_SESION`); si queda vacío, borrar el archivo y sus imports.

- [ ] **Step 6: Cambiar el modelo por defecto**

En `.env.example` y en el `.env` local, poner `GROQ_LLM_MODEL=openai/gpt-oss-120b`.

- [ ] **Step 7: Correr los tests**

Run: `pytest tests/test_parser.py tests/test_schemas.py -v`
Expected: PASS. Borrar de `tests/test_schemas.py` los casos de gasto/ingreso/peso/salud.

- [ ] **Step 8: Commit**

```bash
git add src/ai/parser.py prompts/ src/domain/ tests/test_parser.py tests/test_schemas.py .env.example
git commit -m "feat(ai): canonizador de ejercicios y prompt gym-only"
```

---

### Task 7: Handlers de Telegram y autocierre

**Files:**
- Create: `src/bot/gym_handlers.py`
- Test: `tests/test_gym_handlers.py`

**Interfaces:**
- Consumes: `GymSessionService` (Task 5), `create_groq_canonicalizer` (Task 6), `is_authorized`
- Produces: `GymBotHandlers(allowed_chat_id, session_factory, canonicalizer, now)` con `handle_text(update, context)`, `cancelar(update, context)`, `estado(update, context)`, `close_stale_sessions(context)`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_gym_handlers.py`, siguiendo el estilo de dobles que ya usa `tests/test_bot_handlers.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.bot.gym_handlers import GymBotHandlers
from src.db.models import Base
from src.db.repositories import GymRepository
from src.db.session import create_sqlite_engine

NOW = datetime(2026, 8, 4, 19, 0)
CHAT_ID = 123


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_: object) -> object:
        self.replies.append(text)
        return self


class FakeUpdate:
    def __init__(self, text: str, chat_id: int = CHAT_ID) -> None:
        self.effective_message = FakeMessage(text)
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.effective_user = type("User", (), {"id": chat_id})()


class FakeCanonicalizer:
    def canonicalize(self, raw: str) -> tuple[str, str | None]:
        return raw.replace(" ", "_"), None


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "handlers.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _handlers(session_factory: sessionmaker[Session]) -> GymBotHandlers:
    return GymBotHandlers(
        allowed_chat_id=CHAT_ID,
        session_factory=session_factory,
        canonicalizer=FakeCanonicalizer(),
        now=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_unauthorized_chat_is_ignored(session_factory: sessionmaker[Session]) -> None:
    update = FakeUpdate("espalda biceps", chat_id=999)
    await _handlers(session_factory).handle_text(update, None)

    assert update.effective_message.replies == []
    with session_factory() as session:
        assert GymRepository(session).get_open_session() is None


@pytest.mark.asyncio
async def test_capture_flow_replies_and_persists(
    session_factory: sessionmaker[Session],
) -> None:
    handlers = _handlers(session_factory)
    for text in ["espalda biceps", "dominadas", "7"]:
        update = FakeUpdate(text)
        await handlers.handle_text(update, None)

    with session_factory() as session:
        assert len(GymRepository(session).get_open_session().sets) == 1


@pytest.mark.asyncio
async def test_cancelar_discards_open_session(session_factory: sessionmaker[Session]) -> None:
    handlers = _handlers(session_factory)
    await handlers.handle_text(FakeUpdate("pull"), None)
    update = FakeUpdate("/cancelar")
    await handlers.cancelar(update, None)

    with session_factory() as session:
        assert GymRepository(session).get_open_session() is None
    assert "cancel" in update.effective_message.replies[-1].lower()


@pytest.mark.asyncio
async def test_estado_without_session(session_factory: sessionmaker[Session]) -> None:
    update = FakeUpdate("/estado")
    await _handlers(session_factory).estado(update, None)

    assert "no hay" in update.effective_message.replies[-1].lower()


@pytest.mark.asyncio
async def test_stale_session_is_closed_and_notified(
    session_factory: sessionmaker[Session],
) -> None:
    handlers = GymBotHandlers(
        allowed_chat_id=CHAT_ID,
        session_factory=session_factory,
        canonicalizer=FakeCanonicalizer(),
        now=lambda: NOW - timedelta(hours=4),
    )
    await handlers.handle_text(FakeUpdate("pull"), None)

    sent: list[tuple[int, str]] = []

    class FakeBot:
        async def send_message(self, chat_id: int, text: str) -> None:
            sent.append((chat_id, text))

    context = type("Context", (), {"bot": FakeBot()})()
    fresh = _handlers(session_factory)
    await fresh.close_stale_sessions(context)

    with session_factory() as session:
        assert GymRepository(session).get_open_session() is None
    assert sent and sent[0][0] == CHAT_ID
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_gym_handlers.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.bot.gym_handlers'`

- [ ] **Step 3: Implementar los handlers**

Crear `src/bot/gym_handlers.py`:

```python
"""Handlers de Telegram para la captura de sesiones de gimnasio."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker
from telegram.error import TelegramError

from src.bot.auth import is_authorized
from src.gym.session_service import CanonicalizerProtocol, GymSessionService

INACTIVITY_LIMIT = timedelta(hours=3)


class GymBotHandlers:
    """Traduce mensajes de Telegram a operaciones sobre la sesión abierta."""

    def __init__(
        self,
        *,
        allowed_chat_id: int | None,
        session_factory: sessionmaker[Session],
        canonicalizer: CanonicalizerProtocol,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.allowed_chat_id = allowed_chat_id
        self.session_factory = session_factory
        self.canonicalizer = canonicalizer
        self.now = now

    def _service(self, session: Session) -> GymSessionService:
        return GymSessionService(session, canonicalizer=self.canonicalizer, now=self.now)

    async def handle_text(self, update: Any, _: Any) -> None:
        """Procesa un mensaje de captura y responde el estado resultante."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        message = update.effective_message
        if message is None or not message.text:
            return
        with self.session_factory() as session:
            reply = self._service(session).handle(message.text)
            session.commit()
        await message.reply_text(reply)

    async def cancelar(self, update: Any, _: Any) -> None:
        """Descarta la sesión abierta sin guardarla."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        with self.session_factory() as session:
            service = self._service(session)
            open_session = service.repository.get_open_session()
            if open_session is None:
                reply = "No hay ninguna sesión abierta."
            else:
                service.repository.delete_session(open_session.id)
                reply = "Sesión cancelada, no se guardó nada."
            session.commit()
        await update.effective_message.reply_text(reply)

    async def estado(self, update: Any, _: Any) -> None:
        """Muestra la sesión en curso y su último ejercicio."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        with self.session_factory() as session:
            open_session = self._service(session).repository.get_open_session()
            if open_session is None:
                reply = "No hay ninguna sesión abierta."
            else:
                reply = (
                    f"Sesión: {open_session.etiqueta}\n"
                    f"Series registradas: {len(open_session.sets)}"
                )
        await update.effective_message.reply_text(reply)

    async def close_stale_sessions(self, context: Any) -> None:
        """Cierra sesiones sin actividad y avisa al usuario."""

        cutoff = self.now() - INACTIVITY_LIMIT
        with self.session_factory() as session:
            closed = self._service(session).close_stale(cutoff)
            session.commit()
        if not closed or self.allowed_chat_id is None:
            return
        try:
            await context.bot.send_message(
                chat_id=self.allowed_chat_id,
                text="Cerré la sesión de gimnasio por inactividad y guardé lo registrado.",
            )
        except TelegramError as error:
            logger.warning("No pude avisar el cierre por inactividad: {}", error)
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_gym_handlers.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bot/gym_handlers.py tests/test_gym_handlers.py
git commit -m "feat(bot): captura conversacional y autocierre por inactividad"
```

---

### Task 8: Check-in nocturno

**Files:**
- Create: `src/bot/checkin.py`
- Modify: `src/bot/callbacks.py`
- Test: `tests/test_checkin.py`

**Interfaces:**
- Consumes: `CheckinRepository` (Task 2)
- Produces:
  - `build_checkin_callback(campo: str, valor: str) -> str`, `CheckinCallback(campo, valor)` en `callbacks.py`
  - `CheckinFlow(allowed_chat_id, session_factory, now)` con `send_prompt(context)`, `send_reminder(context)`, `handle_callback(update, context)`, `handle_free_text(update, context) -> bool`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_checkin.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.bot.checkin import STEPS, CheckinFlow
from src.bot.callbacks import CheckinCallback, build_checkin_callback, parse_callback
from src.db.models import Base
from src.db.repositories import CheckinRepository
from src.db.session import create_sqlite_engine

NOW = datetime(2026, 8, 4, 22, 0)
CHAT_ID = 123


class FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.edits: list[str] = []
        self.message = type("Message", (), {"message_id": 1})()

    async def answer(self) -> None:
        return None

    async def edit_message_text(self, text: str, **_: object) -> None:
        self.edits.append(text)


class FakeUpdate:
    def __init__(self, data: str) -> None:
        self.callback_query = FakeQuery(data)
        self.effective_chat = type("Chat", (), {"id": CHAT_ID})()
        self.effective_user = type("User", (), {"id": CHAT_ID})()
        self.effective_message = None


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, chat_id: int, text: str, **_: object) -> object:
        self.sent.append(text)
        return type("Message", (), {"message_id": len(self.sent)})()


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "checkin.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _flow(session_factory: sessionmaker[Session]) -> CheckinFlow:
    return CheckinFlow(
        allowed_chat_id=CHAT_ID, session_factory=session_factory, now=lambda: NOW
    )


def test_callback_roundtrip() -> None:
    assert parse_callback(build_checkin_callback("puntaje_dia", "8")) == CheckinCallback(
        campo="puntaje_dia", valor="8"
    )


def test_steps_cover_every_question() -> None:
    assert [step.campo for step in STEPS] == [
        "puntaje_dia",
        "animo",
        "energia",
        "hora_acostado",
        "mejor_del_dia",
    ]


@pytest.mark.asyncio
async def test_prompt_creates_pending_checkin(session_factory: sessionmaker[Session]) -> None:
    context = type("Context", (), {"bot": FakeBot()})()
    await _flow(session_factory).send_prompt(context)

    with session_factory() as session:
        assert CheckinRepository(session).get_or_create(NOW.date()).estado == "pendiente"
    assert context.bot.sent


@pytest.mark.asyncio
async def test_answers_persist_incrementally(session_factory: sessionmaker[Session]) -> None:
    flow = _flow(session_factory)
    await flow.handle_callback(FakeUpdate(build_checkin_callback("puntaje_dia", "8")), None)
    await flow.handle_callback(FakeUpdate(build_checkin_callback("animo", "6")), None)

    with session_factory() as session:
        stored = CheckinRepository(session).get_or_create(NOW.date())
        assert (stored.puntaje_dia, stored.animo) == (8, 6)
        assert stored.estado == "pendiente"


@pytest.mark.asyncio
async def test_skipping_last_step_completes(session_factory: sessionmaker[Session]) -> None:
    flow = _flow(session_factory)
    await flow.handle_callback(FakeUpdate(build_checkin_callback("mejor_del_dia", "-")), None)

    with session_factory() as session:
        stored = CheckinRepository(session).get_or_create(NOW.date())
        assert stored.estado == "completo"
        assert stored.mejor_del_dia is None


@pytest.mark.asyncio
async def test_reminder_only_when_pending(session_factory: sessionmaker[Session]) -> None:
    flow = _flow(session_factory)
    context = type("Context", (), {"bot": FakeBot()})()
    await flow.send_reminder(context)
    assert context.bot.sent

    with session_factory() as session:
        CheckinRepository(session).update(NOW.date(), estado="completo")
        session.commit()

    quiet = type("Context", (), {"bot": FakeBot()})()
    await flow.send_reminder(quiet)
    assert quiet.bot.sent == []
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_checkin.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.bot.checkin'`

- [ ] **Step 3: Agregar el callback de check-in**

En `src/bot/callbacks.py`: agregar el dataclass y las funciones, y extender `parse_callback`.

```python
CHECKIN_FIELDS = {"puntaje_dia", "animo", "energia", "hora_acostado", "mejor_del_dia"}


@dataclass(frozen=True)
class CheckinCallback:
    """Respuesta elegida en un paso del check-in."""

    campo: str
    valor: str


def build_checkin_callback(campo: str, valor: str) -> str:
    """Construye callback_data para una respuesta del check-in."""

    if campo not in CHECKIN_FIELDS:
        raise CallbackDataError("Campo de check-in inválido")
    return _check_size(f"k:{campo}:{valor}")
```

En `parse_callback`, antes del `raise` final:

```python
        if len(parts) == 3 and parts[0] == "k":
            if parts[1] not in CHECKIN_FIELDS:
                raise ValueError
            return CheckinCallback(campo=parts[1], valor=parts[2])
```

Y actualizar la anotación de retorno a `PreviewCallback | ClarificationCallback | CheckinCallback`.
Borrar `ClarificationHint`/`VALID_HINTS` de finanzas: dejar `VALID_HINTS = {"gym"}` o eliminar el
flujo de clarificación si ya no se usa (verificar con grep antes de borrar).

- [ ] **Step 4: Implementar el flujo**

Crear `src/bot/checkin.py`:

```python
"""Check-in nocturno respondido con taps sobre un único mensaje."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from src.bot.auth import is_authorized
from src.bot.callbacks import CheckinCallback, build_checkin_callback, parse_callback
from src.db.repositories import CheckinRepository

SKIP = "-"


@dataclass(frozen=True)
class Step:
    """Una pregunta del check-in y sus opciones."""

    campo: str
    pregunta: str
    opciones: list[str]


STEPS = [
    Step("puntaje_dia", "¿Qué puntaje le das al día?", [str(n) for n in range(1, 11)]),
    Step("animo", "¿Cómo estuvo tu ánimo?", [str(n) for n in range(1, 11)]),
    Step("energia", "¿Y tu energía?", [str(n) for n in range(1, 6)]),
    Step(
        "hora_acostado",
        "¿A qué hora te acostaste anoche?",
        ["<22", "22-23", "23-00", "00-01", "01-02", "+02"],
    ),
    Step("mejor_del_dia", "Lo mejor del día (opcional)", [SKIP]),
]
NUMERIC_FIELDS = {"puntaje_dia", "animo", "energia"}


class CheckinFlow:
    """Envía, avanza y persiste el check-in nocturno."""

    def __init__(
        self,
        *,
        allowed_chat_id: int | None,
        session_factory: sessionmaker[Session],
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.allowed_chat_id = allowed_chat_id
        self.session_factory = session_factory
        self.now = now
        self._awaiting_text = False

    async def send_prompt(self, context: Any) -> None:
        """Abre el check-in del día con la primera pregunta."""

        if self.allowed_chat_id is None:
            return
        with self.session_factory() as session:
            CheckinRepository(session).get_or_create(self.now().date())
            session.commit()
        await self._send(context, STEPS[0])

    async def send_reminder(self, context: Any) -> None:
        """Reenvía el check-in solo si sigue pendiente."""

        if self.allowed_chat_id is None:
            return
        with self.session_factory() as session:
            checkin = CheckinRepository(session).get_or_create(self.now().date())
            pending = checkin.estado == "pendiente"
            session.commit()
        if pending:
            await self._send(context, STEPS[0], prefix="Te quedó pendiente el check-in.\n")

    async def handle_callback(self, update: Any, _: Any) -> None:
        """Guarda la respuesta y edita el mensaje con la pregunta siguiente."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        query = update.callback_query
        callback = parse_callback(query.data)
        if not isinstance(callback, CheckinCallback):
            return
        await query.answer()
        index = next(i for i, step in enumerate(STEPS) if step.campo == callback.campo)
        self._store(callback)
        if index + 1 < len(STEPS):
            step = STEPS[index + 1]
            await query.edit_message_text(step.pregunta, reply_markup=_keyboard(step))
            return
        await query.edit_message_text("Listo, gracias. Buenas noches.")

    async def handle_free_text(self, update: Any, _: Any) -> bool:
        """Consume el texto libre del último paso; devuelve True si lo tomó."""

        if not self._awaiting_text or not is_authorized(update, self.allowed_chat_id):
            return False
        self._awaiting_text = False
        with self.session_factory() as session:
            CheckinRepository(session).update(
                self.now().date(),
                mejor_del_dia=update.effective_message.text,
                estado="completo",
            )
            session.commit()
        await update.effective_message.reply_text("Anotado. Buenas noches.")
        return True

    def _store(self, callback: CheckinCallback) -> None:
        changes: dict[str, Any] = {}
        if callback.campo == "mejor_del_dia":
            if callback.valor == SKIP:
                changes = {"estado": "completo"}
            else:
                self._awaiting_text = True
                return
        elif callback.campo in NUMERIC_FIELDS:
            changes = {callback.campo: int(callback.valor)}
        else:
            changes = {callback.campo: callback.valor}
        with self.session_factory() as session:
            CheckinRepository(session).update(self.now().date(), **changes)
            session.commit()

    async def _send(self, context: Any, step: Step, prefix: str = "") -> None:
        try:
            await context.bot.send_message(
                chat_id=self.allowed_chat_id,
                text=prefix + step.pregunta,
                reply_markup=_keyboard(step),
            )
        except TelegramError as error:
            logger.warning("No pude mandar el check-in: {}", error)


def _keyboard(step: Step) -> InlineKeyboardMarkup:
    if step.campo == "mejor_del_dia":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Escribir", callback_data=build_checkin_callback(step.campo, "w")
                    ),
                    InlineKeyboardButton(
                        "Saltear", callback_data=build_checkin_callback(step.campo, SKIP)
                    ),
                ]
            ]
        )
    buttons = [
        InlineKeyboardButton(option, callback_data=build_checkin_callback(step.campo, option))
        for option in step.opciones
    ]
    rows = [buttons[index : index + 5] for index in range(0, len(buttons), 5)]
    return InlineKeyboardMarkup(rows)
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `pytest tests/test_checkin.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add src/bot/checkin.py src/bot/callbacks.py tests/test_checkin.py
git commit -m "feat(bot): check-in nocturno con teclados inline"
```

---

### Task 9: Limpieza de superficie y wiring

**Files:**
- Modify: `src/main.py`, `src/bot/commands.py`, `src/bot/maintenance.py`, `src/bot/handlers.py`, `requirements.txt`, `README.md`
- Delete: `src/ai/whisper_client.py`, `src/ai/audio_converter.py`, `tests/test_audio_converter.py`, `tests/test_audio_handler.py`, `tests/test_whisper_client.py`
- Test: `tests/test_main.py`, `tests/test_commands.py`

**Interfaces:**
- Consumes: `GymBotHandlers` (Task 7), `CheckinFlow` (Task 8), `create_groq_canonicalizer` (Task 6)
- Produces: `build_application(settings)` registrando los handlers y jobs finales

- [ ] **Step 1: Escribir el test de wiring que falla**

Reemplazar el test de registro en `tests/test_main.py` por:

```python
def test_registered_commands_are_gym_only() -> None:
    settings = _settings()
    application = build_application(settings)

    registered = {
        handler.commands.copy().pop()
        for group in application.handlers.values()
        for handler in group
        if isinstance(handler, CommandHandler)
    }
    assert registered == {
        "start", "help", "hoy", "gym", "sesiones", "estado",
        "cancelar", "editar", "borrar", "export", "backup",
    }


def test_audio_support_is_gone() -> None:
    assert importlib.util.find_spec("src.ai.whisper_client") is None
    assert importlib.util.find_spec("src.ai.audio_converter") is None
```

Reusar el helper `_settings()` que ya exista en el archivo y agregar `import importlib.util`.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `pytest tests/test_main.py -v`
Expected: FAIL — todavía están registrados `balance`, `gastos`, `ingresos`, `ultimos`, `peso`, `salud`.

- [ ] **Step 3: Borrar el audio**

```bash
git rm src/ai/whisper_client.py src/ai/audio_converter.py
git rm tests/test_audio_converter.py tests/test_audio_handler.py tests/test_whisper_client.py
```

Sacar `pydub>=0.25,<1.0` de `requirements.txt`. En `src/bot/handlers.py`, borrar `handle_audio`, los protocolos `WhisperProtocol` y `AudioConverterProtocol`, los parámetros `whisper`/`audio_converter`/`temp_dir` del constructor, y los imports de `src.ai.whisper_client`. Borrar también `_collect_warnings`, `_render_warnings`, `PESO_MIN/PESO_MAX/SUENO_MIN/SUENO_MAX` y las ramas de `_render_preview` para gasto/ingreso/peso/salud.

- [ ] **Step 4: Recortar los comandos**

En `src/bot/commands.py`: borrar `balance`, `gastos`, `ingresos`, `ultimos`, `weight`, `health` y sus helpers privados. Reescribir `today` para que muestre la sesión del día y el check-in:

```python
    async def today(self, update: Any, _: Any) -> None:
        """Resume la sesión de gimnasio y el check-in del día."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        current_day = self.today_date()
        with self.session_factory() as session:
            sessions = [
                item for item in GymRepository(session).list_sessions(5)
                if item.fecha == current_day
            ]
            checkin = CheckinRepository(session).get_or_create(current_day)
            lines = [f"Hoy {current_day.isoformat()}"]
            if sessions:
                for item in sessions:
                    lines.append(f"Gimnasio: {item.etiqueta} — {len(item.sets)} series")
            else:
                lines.append("Gimnasio: sin registro")
            if checkin.puntaje_dia is not None:
                lines.append(f"Día: {checkin.puntaje_dia}/10, ánimo {checkin.animo}")
            else:
                lines.append("Check-in: pendiente")
            session.commit()
        await update.effective_message.reply_text("\n".join(lines))
```

En `src/bot/maintenance.py`: reducir el mapa de tipos a `sesion` y `set`, borrando las ramas de `transaccion`, `peso` y `salud`. Actualizar el texto de `/help` en `commands.py` con la lista nueva de comandos y el flujo de captura.

- [ ] **Step 5: Rewiring en main.py**

En `src/main.py`, reemplazar `build_application` y `register_handlers`:

```python
def register_handlers(
    application: Application[Any, Any, Any, Any, Any, Any],
    gym: GymBotHandlers,
    checkin: CheckinFlow,
    commands: BotCommands,
    maintenance: BotMaintenance,
    backup: BotBackup,
) -> None:
    """Registra los flujos del bot en orden de prioridad."""

    async def priority_router(update: Any, context: Any) -> None:
        if await checkin.handle_free_text(update, context):
            raise ApplicationHandlerStop
        if await maintenance.handle_edit_value(update, context):
            raise ApplicationHandlerStop

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, priority_router), group=-1
    )
    for name, callback in (
        ("start", commands.start),
        ("help", commands.help),
        ("hoy", commands.today),
        ("gym", commands.gym),
        ("sesiones", commands.sessions),
        ("estado", gym.estado),
        ("cancelar", gym.cancelar),
        ("editar", maintenance.edit),
        ("borrar", maintenance.delete),
        ("backup", backup.backup),
        ("export", backup.export),
    ):
        application.add_handler(CommandHandler(name, callback))
    application.add_handler(CallbackQueryHandler(maintenance.handle_callback, pattern=r"^m:"))
    application.add_handler(CallbackQueryHandler(checkin.handle_callback, pattern=r"^k:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gym.handle_text))
```

En `build_application`, construir `GymBotHandlers` con `create_groq_canonicalizer(settings)` y `CheckinFlow`, y reemplazar los jobs:

```python
    application.job_queue.run_daily(
        backup.scheduled_backup, time=time(hour=settings.backup_daily_hour, tzinfo=timezone)
    )
    application.job_queue.run_daily(checkin.send_prompt, time=time(hour=22, tzinfo=timezone))
    application.job_queue.run_daily(checkin.send_reminder, time=time(hour=23, tzinfo=timezone))
    application.job_queue.run_repeating(gym.close_stale_sessions, interval=600, first=30)
```

- [ ] **Step 6: Correr la suite completa**

Run: `pytest -v`
Expected: PASS. Borrar los tests que referencien dominios eliminados (`test_bot_handlers.py`, `test_commands.py`, `test_preview_service.py`, `test_callbacks.py`, `test_database.py` tienen casos de finanzas/peso/salud que hay que sacar).

Run: `ruff check . && ruff format --check .`
Expected: sin errores. Corregir imports muertos que reporte ruff.

- [ ] **Step 7: Actualizar el README**

Reescribir las secciones "Uso", "Comandos", "Estructura" y "Troubleshooting" para el dominio gym-only: sacar las filas de finanzas/peso/salud y ffmpeg, documentar el flujo de captura (`espalda biceps` → `dominadas` → `7` → `fin`), `deshacer`, `/cancelar`, `/estado` y el check-in nocturno.

- [ ] **Step 8: Commit**

```bash
git add -u
git add src/main.py
git commit -m "refactor: dejar el bot gym-only y cablear check-in"
```

- [ ] **Step 9: Verificación con el bot real**

```bash
.venv/Scripts/python.exe -m src.main
```

Desde Telegram: mandar `espalda biceps`, `dominadas`, `7`, `6`, `remo t 60`, `10`, `deshacer`, `/estado`, `fin`. Confirmar que cada respuesta refleja el estado esperado y que `/hoy` muestra la sesión. Documentar el resultado antes de cerrar la tarea.

---

### Task 10: Dashboard web

**Files:**
- Modify: `src/web/__init__.py`, `src/web/queries.py`
- Create: `src/web/templates/checkin.html`
- Delete: `src/web/templates/finances.html`, `src/web/templates/health.html`
- Test: `tests/test_web_app.py`, `tests/test_web_integration.py`

**Interfaces:**
- Consumes: `Checkin`, `GymSesion`, `GymSet` (Task 1), `CheckinRepository` (Task 2)
- Produces: rutas `/`, `/gym`, `/checkin`, `/healthz`; `DashboardQueries.checkin_history(days)` y `.checkin_vs_gym(days)`

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_web_app.py`, reemplazar los tests de rutas por:

```python
def test_routes_are_gym_only(client) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/gym").status_code == 200
    assert client.get("/checkin").status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/finanzas").status_code == 404
    assert client.get("/salud").status_code == 404


def test_checkin_vs_gym_splits_by_training_day(session_factory) -> None:
    with session_factory() as session:
        repository = CheckinRepository(session)
        repository.update(date(2026, 8, 1), puntaje_dia=8, estado="completo")
        repository.update(date(2026, 8, 2), puntaje_dia=4, estado="completo")
        GymRepository(session).open_session(
            fecha=date(2026, 8, 1), etiqueta="pull", now=datetime(2026, 8, 1, 19, 0)
        )
        session.commit()

        result = DashboardQueries(session).checkin_vs_gym(days=30)

    assert result["con_gym"] == 8.0
    assert result["sin_gym"] == 4.0
```

Reusar las fixtures `client` y `session_factory` que ya existan en el archivo, adaptándolas al schema nuevo.

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_web_app.py -v`
Expected: FAIL — `/checkin` devuelve 404 y `checkin_vs_gym` no existe.

- [ ] **Step 3: Limpiar y extender las consultas**

En `src/web/queries.py`: borrar `month_summary`, `finance_month`, `latest_weight`, `health_averages` y sus helpers. Agregar:

```python
    def checkin_history(self, days: int = 30) -> list[dict[str, Any]]:
        """Serie diaria de puntaje, ánimo y energía."""

        cutoff = self.today() - timedelta(days=days)
        statement = (
            select(Checkin).where(Checkin.fecha >= cutoff).order_by(Checkin.fecha)
        )
        return [
            {
                "fecha": item.fecha.isoformat(),
                "puntaje": item.puntaje_dia,
                "animo": item.animo,
                "energia": item.energia,
                "hora_acostado": item.hora_acostado,
            }
            for item in self.session.scalars(statement)
        ]

    def checkin_vs_gym(self, days: int = 30) -> dict[str, float | None]:
        """Puntaje promedio en días con y sin entrenamiento."""

        cutoff = self.today() - timedelta(days=days)
        trained = set(
            self.session.scalars(select(GymSesion.fecha).where(GymSesion.fecha >= cutoff))
        )
        scores = {"con_gym": [], "sin_gym": []}
        statement = select(Checkin).where(
            Checkin.fecha >= cutoff, Checkin.puntaje_dia.is_not(None)
        )
        for item in self.session.scalars(statement):
            key = "con_gym" if item.fecha in trained else "sin_gym"
            scores[key].append(item.puntaje_dia)
        return {
            key: (sum(values) / len(values) if values else None)
            for key, values in scores.items()
        }
```

Ajustar `recent_activity` y `gym_summary` para usar `etiqueta` en vez de `tipo`.

- [ ] **Step 4: Actualizar las rutas y templates**

En `src/web/__init__.py`: borrar las rutas `finances` y `health` junto a los helpers `parse_month`, `select_currency` y `format_number` si quedan sin uso (verificar con grep). Reescribir `index` para mostrar la sesión reciente y el check-in. Agregar:

```python
    @app.get("/checkin")
    def checkin() -> str:
        days = parse_days(request.args.get("days"))
        with session_factory() as session:
            queries = DashboardQueries(session)
            return render_template(
                "checkin.html",
                active="checkin",
                days=days,
                history=queries.checkin_history(days),
                comparison=queries.checkin_vs_gym(days),
            )
```

Borrar `src/web/templates/finances.html` y `health.html`. Crear `checkin.html` siguiendo la estructura de los templates existentes (mismo `base.html`, mismo patrón de Chart.js), con una serie temporal de puntaje/ánimo/energía y una tarjeta con el contraste `con_gym` / `sin_gym`. Actualizar la navegación en `base.html`.

- [ ] **Step 5: Correr los tests**

Run: `pytest tests/test_web_app.py tests/test_web_integration.py -v`
Expected: PASS

- [ ] **Step 6: Verificación en navegador**

```bash
.venv/Scripts/python.exe -m src.web
```

Abrir `http://127.0.0.1:5000/`, `/gym` y `/checkin`. Confirmar que los tres cargan sin error y que los gráficos renderizan. Guardar capturas en `.claude/screenshots/` si se usa playwright.

- [ ] **Step 7: Suite completa y commit**

Run: `pytest && ruff check . && ruff format --check .`
Expected: todo verde.

```bash
git add -u
git add src/web/templates/checkin.html
git commit -m "feat(web): dashboard gym-only con panel de check-in"
```

---

## Notas de ejecución

- Las tareas 1→9 son secuenciales: cada una depende de las interfaces de la anterior. La 10 es
  independiente de la 8 salvo por el modelo `Checkin`, y es la fase recortable.
- Después de la Task 1 la base de producción queda migrada. Si algo sale mal, restaurar desde
  `data/backups/`.
- El conteo de tests va a bajar antes de subir: se borran ~40 tests de dominios eliminados y se
  agregan ~35 nuevos. No tomar la caída como regresión.
