import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.eventbus import EventBus
from app.api.routes_rest import router as rest_router
from app.api.routes_ws import router as ws_router
from app.config import get_settings
from app.ingestion.backfill import BackfillService
from app.ingestion.pipeline import IngestionPipeline
from app.storage.db import session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.event_bus = EventBus()
    app.state.http_client = httpx.AsyncClient()

    backfill_service = BackfillService(
        app.state.http_client, settings.binance_rest_url, settings.backfill_hours
    )
    pipeline = IngestionPipeline(
        session_factory=session_factory,
        backfill_service=backfill_service,
        event_bus=app.state.event_bus,
        symbols=settings.symbol_list,
        ws_url=settings.binance_ws_url,
        trade_batch_size=settings.trade_flush_batch_size,
        trade_flush_interval=settings.trade_flush_interval_seconds,
        ws_min_backoff=settings.ws_reconnect_min_seconds,
        ws_max_backoff=settings.ws_reconnect_max_seconds,
    )
    app.state.pipeline = pipeline
    pipeline_task = asyncio.create_task(pipeline.run())

    try:
        yield
    finally:
        pipeline.stop()
        pipeline_task.cancel()
        try:
            await pipeline_task
        except asyncio.CancelledError:
            pass
        await app.state.http_client.aclose()


app = FastAPI(title="Binance Ops Dashboard", lifespan=lifespan)
app.include_router(rest_router)
app.include_router(ws_router)

# check_dir=False: the frontend build only exists at ./static inside the
# `runtime` Docker image (see Dockerfile). Dev/test contexts don't need it.
app.mount("/", StaticFiles(directory="static", html=True, check_dir=False), name="static")
