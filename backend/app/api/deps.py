from collections.abc import AsyncGenerator

from fastapi import Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config import settings
from app.infrastructure.db.session import get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


async def get_tenant_id(x_tenant_id: str | None = Header(default=None)) -> str:
    """Resuelve el tenant activo. En produccion vendria de auth/API key;
    para el laboratorio aceptamos override por header para poder probar
    multi-tenant sin login."""
    return x_tenant_id or settings.default_tenant_id
