import threading
import time
import uuid
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import get_settings


class BodySizeLimitMiddleware:
    """Buffer only up to the limit before downstream parsing, including chunked bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Requests with a declared size are rejected by RequestGuardMiddleware. Avoid
        # pre-consuming those bodies here because BaseHTTPMiddleware expects to own
        # the receive stream on recent Starlette versions. This buffer is only for
        # genuinely streamed/chunked bodies where Content-Length is absent.
        headers = dict(scope.get("headers", []))
        method = scope.get("method", "GET").upper()
        if b"content-length" in headers or method in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        limit = get_settings().max_request_bytes
        buffered: list[Message] = []
        received = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": "Request body is too large"},
                    )
                    await response(scope, receive, send)
                    return
                more_body = bool(message.get("more_body", False))
            buffered.append(message)

        index = 0

        async def replay_receive() -> Message:
            nonlocal index
            if index < len(buffered):
                message = buffered[index]
                index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        if get_settings().env == "production":
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            )
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
        if not get_settings().rate_limit_enabled:
            return await call_next(request)
        minute = int(time.time() // 60)
        client = request.client.host if request.client else "unknown"
        path = request.url.path
        rules: list[tuple[str, int]] = [
            ("/auth/bootstrap", 3),
            ("/auth/login", 10),
            ("/recognition/", 30),
            ("/admin/", 120),
        ]
        group, limit = "general", 300
        for suffix, candidate_limit in rules:
            if suffix in path:
                group, limit = suffix, candidate_limit
                break
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

