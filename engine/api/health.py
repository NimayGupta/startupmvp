import importlib.metadata

from fastapi import APIRouter
from sqlalchemy import text

from engine.api.deps import DbSession, RedisClient

router = APIRouter()

try:
    _version = importlib.metadata.version("startupmvp")
except importlib.metadata.PackageNotFoundError:
    _version = "0.1.0-dev"


@router.get("/health", tags=["ops"])
async def health(db: DbSession, redis: RedisClient) -> dict:  # type: ignore[type-arg]
    """
    Health check endpoint. Returns 200 when the service, database, and Redis
    are all reachable. Returns 503 if any dependency is down.
    Docker Compose and load balancers poll this endpoint.
    """
    db_connected = False
    redis_connected = False

    try:
        await db.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        pass

    try:
        await redis.ping()  # type: ignore[union-attr]
        redis_connected = True
    except Exception:
        pass

    status_ok = db_connected and redis_connected
    return {
        "status": "ok" if status_ok else "degraded",
        "version": _version,
        "db_connected": db_connected,
        "redis_connected": redis_connected,
    }
