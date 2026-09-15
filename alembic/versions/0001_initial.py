"""Inicial: linhas, pontos e horarios

Revision ID: 0001_initial
Revises: 
Create Date: 2026-09-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "linhas",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("codigo", sa.String(20), nullable=False, unique=True),
        sa.Column("nome", sa.Text, nullable=False),
        sa.Column("origem", sa.Text),
        sa.Column("destino", sa.Text),
        sa.Column("cor", sa.String(7)),
    )
    op.create_index("ix_linhas_codigo", "linhas", ["codigo"])

    op.create_table(
        "pontos",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("codigo", sa.String(20), nullable=False, unique=True),
        sa.Column("latitude", sa.Numeric(10, 8), nullable=False),
        sa.Column("longitude", sa.Numeric(11, 8), nullable=False),
        sa.Column("descricao", sa.Text),
        sa.Column("linha_id", sa.Integer, sa.ForeignKey("linhas.id", ondelete="CASCADE")),
    )
    op.create_index("ix_pontos_codigo", "pontos", ["codigo"])
    op.create_index("idx_pontos_lat_lng", "pontos", ["latitude", "longitude"])

    op.create_table(
        "horarios",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ponto_id", sa.Integer, sa.ForeignKey("pontos.id", ondelete="CASCADE")),
        sa.Column("dia_semana", sa.String(10), nullable=False),
        sa.Column("hora", sa.String(8), nullable=False),
        # Unique constraint for idempotent upsert via ON CONFLICT
        sa.UniqueConstraint("ponto_id", "dia_semana", "hora", name="uq_horarios_ponto_dia_hora"),
    )


def downgrade() -> None:
    op.drop_table("horarios")
    op.drop_table("pontos")
    op.drop_table("linhas")