"""Modelos persistentes del Personal Tracker."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base declarativa compartida por los modelos."""


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


class Ejercicio(Base):
    """Ejercicio canónico reconocido por el sistema."""

    __tablename__ = "ejercicio"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre_canonico: Mapped[str] = mapped_column(String(100), unique=True)
    grupo_muscular: Mapped[str | None] = mapped_column(String(50))
    alias_json: Mapped[str | None] = mapped_column(Text)
    sets: Mapped[list[GymSet]] = relationship(back_populates="ejercicio")


class GymSet(Base):
    """Serie ejecutada dentro de una sesión de gimnasio."""

    __tablename__ = "gym_set"
    __table_args__ = (
        CheckConstraint("serie_num > 0", name="ck_gym_set_serie_positiva"),
        Index("idx_set_sesion", "sesion_id"),
        Index("idx_set_ejercicio", "ejercicio_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sesion_id: Mapped[int] = mapped_column(ForeignKey("gym_sesion.id", ondelete="CASCADE"))
    ejercicio_id: Mapped[int] = mapped_column(ForeignKey("ejercicio.id"))
    serie_num: Mapped[int]
    peso_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    reps: Mapped[int | None]
    rpe: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    nota: Mapped[str | None] = mapped_column(Text)
    sesion: Mapped[GymSesion] = relationship(back_populates="sets")
    ejercicio: Mapped[Ejercicio] = relationship(back_populates="sets")


class Pendiente(Base):
    """Mensaje que requiere aclaración o reprocesamiento."""

    __tablename__ = "pendiente"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int]
    mensaje_original: Mapped[str] = mapped_column(Text)
    transcripcion: Mapped[str | None] = mapped_column(Text)
    intentos: Mapped[int] = mapped_column(default=0)
    sugerencias_json: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class Preview(Base):
    """Lote validado pendiente de confirmación interactiva."""

    __tablename__ = "preview"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[int]
    message_id: Mapped[int | None]
    mensaje_original: Mapped[str] = mapped_column(Text)
    transcripcion: Mapped[str | None] = mapped_column(Text)
    operaciones_json: Mapped[str] = mapped_column(Text)
    resultados_json: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    expira_en: Mapped[datetime] = mapped_column(DateTime)


class ErrorLog(Base):
    """Error operativo persistido para diagnóstico."""

    __tablename__ = "error_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tipo: Mapped[str | None] = mapped_column(String(100))
    mensaje: Mapped[str | None] = mapped_column(Text)
    contexto_json: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


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
