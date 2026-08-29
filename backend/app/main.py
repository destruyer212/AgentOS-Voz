import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.domain.services import close_stale_web_conversations
from app.infrastructure.config import settings
from app.infrastructure.db.session import AsyncSessionLocal, init_db
from app.infrastructure.seed import seed_demo_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


async def _stale_conversation_sweeper() -> None:
    """Corre en segundo plano mientras la app este viva: cada
    `stale_conversation_sweep_interval_seconds` cierra conversaciones web
    abandonadas hace mas de `stale_conversation_timeout_minutes`. Ver
    close_stale_web_conversations() para el porque (bug real de ago 2026:
    conversaciones de prueba/abandonadas quedaban "active" para siempre).
    """
    while True:
        try:
            async with AsyncSessionLocal() as session:
                closed = await close_stale_web_conversations(
                    session, timeout_minutes=settings.stale_conversation_timeout_minutes
                )
                if closed:
                    logger.info("Cerradas %d conversaciones web inactivas: %s", len(closed), closed)
        except Exception:
            logger.exception("Error en el barrido de conversaciones inactivas")
        await asyncio.sleep(settings.stale_conversation_sweep_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_demo_data()
    sweeper_task = asyncio.create_task(_stale_conversation_sweeper())
    try:
        yield
    finally:
        sweeper_task.cancel()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API modular para agentes de voz, workflows, tools y core restaurante.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
