import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import get_settings
from .database import Base, SessionLocal, engine
from .middleware import (
    BodySizeLimitMiddleware,
    InMemoryRateLimitMiddleware,
    RequestGuardMiddleware,
    SecurityHeadersMiddleware,
)
from .routers import admin, auth, conversations, health, recognition, scenarios
from .routers import settings as settings_router
from .seed import seed_reference_data
from .services import cleanup_maintenance

settings = get_settings()
logger = logging.getLogger(__name__)


def run_maintenance() -> None:
    with SessionLocal() as db:
        cleanup_maintenance(db)


async def maintenance_loop() -> None:
    while True:
        await asyncio.sleep(settings.cleanup_interval_seconds)
        try:
            await asyncio.to_thread(run_maintenance)
        except Exception:
            logger.exception("Scheduled maintenance failed; retrying next interval")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Production schemas are changed only through Alembic, never implicitly on API startup.
    if settings.env != "production":
        Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_reference_data(db)
    maintenance_task = asyncio.create_task(maintenance_loop())
    try:
        yield
    finally:
        maintenance_task.cancel()
        with suppress(asyncio.CancelledError):
            await maintenance_task


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    docs_url="/docs" if settings.env != "production" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.env != "production" else None,
    lifespan=lifespan,
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
)
app.add_middleware(InMemoryRateLimitMiddleware)
app.add_middleware(RequestGuardMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)

app.include_router(health.router)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(scenarios.router, prefix=settings.api_prefix)
app.include_router(conversations.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(settings_router.router, prefix=settings.api_prefix)
app.include_router(recognition.router, prefix=settings.api_prefix)
