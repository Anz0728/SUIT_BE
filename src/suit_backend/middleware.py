import threading
import time
import uuid
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class RequestGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body is too large", "request_id": request_id},
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length", "request_id": request_id},
                )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """MVP single-instance limiter. Replace with Redis before horizontal scaling."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str, int], int] = defaultdict(int)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        minute = int(time.time() // 60)
        client = request.client.host if request.client else "unknown"
        group = "login" if request.url.path.endswith("/auth/login") else "general"
        limit = 10 if group == "login" else 300
        key = (client, group, minute)
        with self._lock:
            self._hits[key] += 1
            count = self._hits[key]
            if len(self._hits) > 10_000:
                self._hits = defaultdict(
                    int,
                    {
                        stored: value
                        for stored, value in self._hits.items()
                        if stored[2] >= minute - 1
                    },
                )
        if count > limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": "60"},
            )
        return await call_next(request)

