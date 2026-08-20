from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_TZ_DATETIME = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class Trade(Base):
    """Individual executed trades, as pushed by Binance's ``<symbol>@trade`` stream."""

    __tablename__ = "trades"

    time: Mapped[datetime] = mapped_column(_TZ_DATETIME, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    # Binance 체결 ID는 이미 int32를 넘었다 — BigInteger로 고정해야 하며,
    # 마이그레이션(0001)도 같은 타입이다.
    trade_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    price: Mapped[float] = mapped_column(Numeric)
    qty: Mapped[float] = mapped_column(Numeric)
    quote_qty: Mapped[float] = mapped_column(Numeric)
    is_buyer_maker: Mapped[bool] = mapped_column(Boolean)


class Candle1m(Base):
    """1-minute OHLCV candles, upserted directly from Binance's ``kline_1m`` stream."""

    __tablename__ = "candles_1m"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    open_time: Mapped[datetime] = mapped_column(_TZ_DATETIME, primary_key=True)
    close_time: Mapped[datetime] = mapped_column(_TZ_DATETIME)
    open: Mapped[float] = mapped_column(Numeric)
    high: Mapped[float] = mapped_column(Numeric)
    low: Mapped[float] = mapped_column(Numeric)
    close: Mapped[float] = mapped_column(Numeric)
    volume: Mapped[float] = mapped_column(Numeric)
    quote_volume: Mapped[float] = mapped_column(Numeric)
    trade_count: Mapped[int] = mapped_column(Integer)
    is_closed: Mapped[bool] = mapped_column(Boolean)


class PipelineStatus(Base):
    """One row per symbol tracking ingestion health for the ops dashboard."""

    __tablename__ = "pipeline_status"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    ws_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_trade_at: Mapped[datetime | None] = mapped_column(_TZ_DATETIME, nullable=True)
    last_backfill_at: Mapped[datetime | None] = mapped_column(_TZ_DATETIME, nullable=True)
    backfill_covered_from: Mapped[datetime | None] = mapped_column(_TZ_DATETIME, nullable=True)
    reconnect_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(_TZ_DATETIME, nullable=True)
