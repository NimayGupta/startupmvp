from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from engine.api.router import api_router
from engine.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    # Startup: initialise Sentry if configured
    if settings.sentry_dsn:
        import sentry_sdk  # type: ignore[import-untyped]

        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.python_env)

    yield

    # Shutdown: close any open connections
    # (SQLAlchemy async engine disposes automatically; Redis pool closes on GC)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Discount Optimizer Engine",
        description="Decision engine for the Shopify Discount Optimization System.",
        version="0.1.0",
        docs_url="/docs" if settings.python_env != "production" else None,
        redoc_url="/redoc" if settings.python_env != "production" else None,
        lifespan=lifespan,
    )

    # CORS: only the Remix app needs to call this service directly.
    # In production, ENGINE_URL is internal and never exposed publicly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.python_env == "development" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    return app


app = create_app()
