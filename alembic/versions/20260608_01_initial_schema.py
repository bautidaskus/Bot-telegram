"""Crea el esquema inicial.

Revision ID: 20260608_01
Revises:
Create Date: 2026-06-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260608_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crea las tablas e índices del tracker."""

    op.create_table(
        "ejercicio",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nombre_canonico", sa.String(length=100), nullable=False),
        sa.Column("grupo_muscular", sa.String(length=50), nullable=True),
        sa.Column("alias_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre_canonico"),
    )
    op.create_table(
        "error_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tipo", sa.String(length=100), nullable=True),
        sa.Column("mensaje", sa.Text(), nullable=True),
        sa.Column("contexto_json", sa.Text(), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "gym_sesion",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=True),
        sa.Column("duracion_min", sa.Integer(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("mensaje_original", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "pendiente",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("mensaje_original", sa.Text(), nullable=False),
        sa.Column("transcripcion", sa.Text(), nullable=True),
        sa.Column("intentos", sa.Integer(), nullable=False),
        sa.Column("sugerencias_json", sa.Text(), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "peso",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("kg", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("kg > 0", name="ck_peso_positivo"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fecha"),
    )
    op.create_table(
        "preview",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("mensaje_original", sa.Text(), nullable=False),
        sa.Column("transcripcion", sa.Text(), nullable=True),
        sa.Column("operaciones_json", sa.Text(), nullable=False),
        sa.Column("resultados_json", sa.Text(), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expira_en", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "salud",
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("sueno_horas", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("sueno_calidad", sa.Integer(), nullable=True),
        sa.Column("animo", sa.Integer(), nullable=True),
        sa.Column("energia", sa.Integer(), nullable=True),
        sa.Column("agua_l", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.Column(
            "actualizado_en",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("animo BETWEEN 1 AND 10", name="ck_salud_animo"),
        sa.CheckConstraint("energia BETWEEN 1 AND 10", name="ck_salud_energia"),
        sa.CheckConstraint("sueno_calidad BETWEEN 1 AND 10", name="ck_salud_sueno_calidad"),
        sa.PrimaryKeyConstraint("fecha"),
    )
    op.create_table(
        "transaccion",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("tipo", sa.String(length=10), nullable=False),
        sa.Column("monto", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("metodo_pago", sa.String(length=30), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("mensaje_original", sa.Text(), nullable=True),
        sa.CheckConstraint("monto > 0", name="ck_transaccion_monto_positivo"),
        sa.CheckConstraint("tipo IN ('gasto', 'ingreso')", name="ck_transaccion_tipo"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_trans_categoria", "transaccion", ["categoria"])
    op.create_index("idx_trans_fecha", "transaccion", ["fecha"])
    op.create_table(
        "gym_set",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sesion_id", sa.Integer(), nullable=False),
        sa.Column("ejercicio_id", sa.Integer(), nullable=False),
        sa.Column("serie_num", sa.Integer(), nullable=False),
        sa.Column("peso_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("rpe", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.CheckConstraint("serie_num > 0", name="ck_gym_set_serie_positiva"),
        sa.ForeignKeyConstraint(["ejercicio_id"], ["ejercicio.id"]),
        sa.ForeignKeyConstraint(["sesion_id"], ["gym_sesion.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_set_ejercicio", "gym_set", ["ejercicio_id"])
    op.create_index("idx_set_sesion", "gym_set", ["sesion_id"])


def downgrade() -> None:
    """Elimina el esquema inicial en orden de dependencias."""

    op.drop_index("idx_set_sesion", table_name="gym_set")
    op.drop_index("idx_set_ejercicio", table_name="gym_set")
    op.drop_table("gym_set")
    op.drop_index("idx_trans_fecha", table_name="transaccion")
    op.drop_index("idx_trans_categoria", table_name="transaccion")
    op.drop_table("transaccion")
    op.drop_table("salud")
    op.drop_table("preview")
    op.drop_table("peso")
    op.drop_table("pendiente")
    op.drop_table("gym_sesion")
    op.drop_table("error_log")
    op.drop_table("ejercicio")
