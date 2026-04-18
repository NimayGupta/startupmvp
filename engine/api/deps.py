from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from engine.config import settings
from engine.db.session import get_db

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DbSession = Annotated[AsyncSession, Depends(get_db)]

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(settings.redis_url, decode_responses=True)
    yield _redis_pool


RedisClient = Annotated[aioredis.Redis, Depends(get_redis)]

# ---------------------------------------------------------------------------
# Internal service-to-service authentication
# Bearer token must match INTERNAL_API_KEY environment variable.
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_internal_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)],
) -> None:
    if not settings.internal_api_key:
        # Key not configured — allow in development, block in production
        if settings.python_env == "production":
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="INTERNAL_API_KEY not set")
        return
    if credentials is None or credentials.credentials != settings.internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


RequireInternalAuth = Depends(verify_internal_api_key)
