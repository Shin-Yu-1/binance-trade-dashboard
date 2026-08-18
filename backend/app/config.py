from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    symbols: str = "BTCUSDT,ETHUSDT"
    backfill_hours: int = 24
    binance_ws_url: str = "wss://stream.binance.com:9443/stream"
    binance_rest_url: str = "https://api.binance.com"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/binance"

    trade_flush_interval_seconds: float = 0.5
    trade_flush_batch_size: int = 200
    ws_reconnect_min_seconds: float = 1.0
    ws_reconnect_max_seconds: float = 30.0
    status_update_interval_seconds: float = 1.0

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.symbols.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
