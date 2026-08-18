"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "trades",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("symbol", sa.String(20), primary_key=True),
        sa.Column("trade_id", sa.BigInteger(), primary_key=True),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("qty", sa.Numeric(), nullable=False),
        sa.Column("quote_qty", sa.Numeric(), nullable=False),
        sa.Column("is_buyer_maker", sa.Boolean(), nullable=False),
    )
    op.execute("SELECT create_hypertable('trades', 'time', if_not_exists => TRUE)")

    op.create_table(
        "candles_1m",
        sa.Column("symbol", sa.String(20), primary_key=True),
        sa.Column("open_time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.Numeric(), nullable=False),
        sa.Column("quote_volume", sa.Numeric(), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False),
    )
    op.execute("SELECT create_hypertable('candles_1m', 'open_time', if_not_exists => TRUE)")

    op.create_table(
        "pipeline_status",
        sa.Column("symbol", sa.String(20), primary_key=True),
        sa.Column("ws_connected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_trade_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_backfill_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backfill_covered_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconnect_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("pipeline_status")
    op.drop_table("candles_1m")
    op.drop_table("trades")
