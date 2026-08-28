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
        batch.add_column(
            sa.Column("estado", sa.String(10), nullable=False, server_default="cerrada")
        )
        batch.add_column(
            sa.Column(
                "ejercicio_actual_id",
                sa.Integer,
                sa.ForeignKey("ejercicio.id", name="fk_gym_sesion_ejercicio_actual_id"),
            )
        )
        batch.add_column(sa.Column("peso_actual", sa.Numeric(7, 2)))
        batch.add_column(sa.Column("ultima_actividad", sa.DateTime))
        batch.add_column(sa.Column("cerrada_en", sa.DateTime))

    op.execute("UPDATE gym_sesion SET etiqueta = tipo, ultima_actividad = creado_en")

    with op.batch_alter_table("gym_sesion") as batch:
        batch.drop_column("tipo")
        batch.alter_column("ultima_actividad", existing_type=sa.DateTime, nullable=False)
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
        sa.Column(
            "creado_en", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.CheckConstraint("puntaje_dia BETWEEN 1 AND 10", name="ck_checkin_puntaje"),
        sa.CheckConstraint("animo BETWEEN 1 AND 10", name="ck_checkin_animo"),
        sa.CheckConstraint("energia BETWEEN 1 AND 5", name="ck_checkin_energia"),
    )


def downgrade() -> None:
    raise NotImplementedError("Migración irreversible: dropea tablas con datos")
