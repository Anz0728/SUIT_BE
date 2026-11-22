from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import get_settings
from .database import Base, SessionLocal, engine
from .middleware import (
    InMemoryRateLimitMiddleware,
    RequestGuardMiddleware,
    SecurityHeadersMiddleware,
)
from .routers import admin, auth, conversations, health, recognition, scenarios
from .seed import seed_reference_data

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # MVP convenience. Replace create_all with Alembic migrations in production deployment.
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_reference_data(db)
    yield


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

app.include_router(health.router)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(scenarios.router, prefix=settings.api_prefix)
app.include_router(conversations.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(recognition.router, prefix=settings.api_prefix)
