"""Gestión persistente de previews y aclaraciones."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Pendiente, Preview
from src.db.repositories import (
    FinanceRepository,
    GymRepository,
    HealthRepository,
    WeightRepository,
)
from src.domain.schemas import ParsedOperation, ParserResponse
from src.utils.dates import parse_spanish_date


class PreviewStateError(ValueError):
    """Indica que un preview no admite la transición solicitada."""


class PreviewExpiredError(PreviewStateError):
    """Indica que un preview ya expiró."""


class AmbiguousOperationsError(ValueError):
    """Indica que un lote necesita aclaración antes del preview."""


@dataclass(frozen=True)
class SavedRecord:
    """Referencia estable a un registro guardado."""

    kind: str
    identifier: str


@dataclass(frozen=True)
class ClarificationContext:
    """Datos necesarios para reprocesar una aclaración."""

    original_text: str
    transcription: str | None
    hint: str


class PreviewService:
    """Coordina estados interactivos y persistencia atómica."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        chat_id: int,
        message_id: int | None,
        original_text: str,
        parsed: ParserResponse,
        now: datetime,
        transcription: str | None = None,
    ) -> Preview:
        """Persiste un preview válido durante diez minutos."""

        if any(
            operation.tipo == "ambiguo" or operation.confianza < 0.7
            for operation in parsed.operaciones
        ):
            raise AmbiguousOperationsError("El lote requiere aclaración")
        preview = Preview(
            id=str(uuid4()),
            chat_id=chat_id,
            message_id=message_id,
            mensaje_original=original_text,
            transcripcion=transcription,
            operaciones_json=parsed.model_dump_json(),
            estado="pendiente",
            expira_en=now + timedelta(minutes=10),
        )
        self.session.add(preview)
        self.session.flush()
        return preview

    def confirm(self, preview_id: str, *, now: datetime) -> list[SavedRecord]:
        """Guarda todas las operaciones de un preview como una unidad."""

        preview = self.session.get_one(Preview, preview_id)
        if preview.estado == "guardado":
            return self._load_results(preview)
        self._require_pending(preview, now)
        parsed = ParserResponse.model_validate_json(preview.operaciones_json)
        saved = [
            self._save_operation(
                operation,
                parse_spanish_date(operation.fecha, now=now),
                preview.mensaje_original,
            )
            for operation in parsed.operaciones
        ]
        preview.resultados_json = json.dumps([asdict(item) for item in saved])
        preview.estado = "guardado"
        self.session.flush()
        return saved

    def cancel(self, preview_id: str, *, now: datetime) -> Preview:
        """Descarta un preview pendiente."""

        preview = self.session.get_one(Preview, preview_id)
        self._require_pending(preview, now)
        preview.estado = "cancelado"
        self.session.flush()
        return preview

    def correct(self, preview_id: str, parsed: ParserResponse, *, now: datetime) -> Preview:
        """Reemplaza las operaciones de un preview aún pendiente."""

        preview = self.session.get_one(Preview, preview_id)
        self._require_pending(preview, now)
        preview.operaciones_json = parsed.model_dump_json()
        preview.expira_en = now + timedelta(minutes=10)
        self.session.flush()
        return preview

    def expire_pending(self, *, now: datetime) -> list[Preview]:
        """Marca como expirados los previews cuyo plazo terminó."""

        statement = select(Preview).where(Preview.estado == "pendiente", Preview.expira_en <= now)
        previews = list(self.session.scalars(statement))
        for preview in previews:
            preview.estado = "expirado"
        self.session.flush()
        return previews

    def store_ambiguity(
        self,
        *,
        chat_id: int,
        original_text: str,
        parsed: ParserResponse,
        transcription: str | None = None,
    ) -> Pendiente:
        """Guarda una operación ambigua para su aclaración posterior."""

        suggestions: list[str] = []
        for operation in parsed.operaciones:
            if operation.tipo == "ambiguo":
                suggestions.extend(operation.datos.sugerencias)
            elif operation.confianza < 0.7:
                suggestions.append(operation.tipo)
        pending = Pendiente(
            chat_id=chat_id,
            mensaje_original=original_text,
            transcripcion=transcription,
            sugerencias_json=json.dumps(suggestions, ensure_ascii=False),
        )
        self.session.add(pending)
        self.session.flush()
        return pending

    def store_failure(
        self,
        *,
        chat_id: int,
        original_text: str,
        transcription: str | None = None,
    ) -> Pendiente:
        """Guarda un mensaje que no se pudo procesar por indisponibilidad del LLM."""

        pending = Pendiente(
            chat_id=chat_id,
            mensaje_original=original_text,
            transcripcion=transcription,
            sugerencias_json=None,
        )
        self.session.add(pending)
        self.session.flush()
        return pending

    def resolve_ambiguity(self, pending_id: int, *, hint: str) -> ClarificationContext:
        """Cierra un pendiente y devuelve el contexto para reprocesarlo."""

        pending = self.session.get_one(Pendiente, pending_id)
        if pending.estado != "pendiente":
            raise PreviewStateError(f"La aclaración está {pending.estado}")
        suggestions = json.loads(pending.sugerencias_json or "[]")
        if hint not in suggestions:
            raise PreviewStateError("El hint no pertenece a las sugerencias")
        pending.estado = "resuelto"
        self.session.flush()
        return ClarificationContext(
            original_text=pending.mensaje_original,
            transcription=pending.transcripcion,
            hint=hint,
        )

    def get_ambiguity_context(self, pending_id: int, *, hint: str) -> ClarificationContext:
        """Lee una aclaración válida sin cambiar su estado."""

        pending = self.session.get_one(Pendiente, pending_id)
        if pending.estado != "pendiente":
            raise PreviewStateError(f"La aclaración está {pending.estado}")
        suggestions = json.loads(pending.sugerencias_json or "[]")
        if hint not in suggestions:
            raise PreviewStateError("El hint no pertenece a las sugerencias")
        return ClarificationContext(
            original_text=pending.mensaje_original,
            transcription=pending.transcripcion,
            hint=hint,
        )

    def attach_message(self, preview_id: str, message_id: int) -> Preview:
        """Asocia el mensaje de Telegram que contiene el preview."""

        preview = self.session.get_one(Preview, preview_id)
        preview.message_id = message_id
        self.session.flush()
        return preview

    def _require_pending(self, preview: Preview, now: datetime) -> None:
        if preview.estado == "expirado" or preview.expira_en <= now:
            if preview.estado == "pendiente":
                preview.estado = "expirado"
                self.session.flush()
            raise PreviewExpiredError("El preview expiró")
        if preview.estado != "pendiente":
            raise PreviewStateError(f"El preview está {preview.estado}")

    def _save_operation(
        self, operation: ParsedOperation, resolved_date: date, original_text: str
    ) -> SavedRecord:
        data = operation.datos.model_dump(exclude_none=True)
        if operation.tipo in {"gasto", "ingreso"}:
            record = FinanceRepository(self.session).create(
                fecha=resolved_date,
                tipo=operation.tipo,
                mensaje_original=original_text,
                **data,
            )
            return SavedRecord(operation.tipo, str(record.id))
        if operation.tipo == "gym":
            record = GymRepository(self.session).create_session(
                fecha=resolved_date,
                exercises=data.pop("ejercicios"),
                mensaje_original=original_text,
                **data,
            )
            return SavedRecord("gym", str(record.id))
        if operation.tipo == "peso":
            record = WeightRepository(self.session).save(resolved_date, **data)
            return SavedRecord("peso", str(record.id))
        if operation.tipo == "salud":
            HealthRepository(self.session).upsert(resolved_date, **data)
            return SavedRecord("salud", resolved_date.isoformat())
        raise PreviewStateError("Una operación ambigua no puede confirmarse")

    def _load_results(self, preview: Preview) -> list[SavedRecord]:
        if preview.resultados_json is None:
            raise PreviewStateError("El preview guardado no tiene resultados")
        return [SavedRecord(**item) for item in json.loads(preview.resultados_json)]
