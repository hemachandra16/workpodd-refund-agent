"""Small in-memory rate limiter for demo/runtime abuse protection."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request, WebSocket, status

from app.config import get_settings


WindowName = Literal["chat", "voice", "admin"]


@dataclass
class Bucket:
    reset_at: float
    count: int = 0


_buckets: dict[tuple[str, str], Bucket] = {}


def parse_limit(limit: str) -> tuple[int, int]:
    amount, _, window = limit.partition("/")
    max_requests = int(amount.strip())
    window = window.strip().lower()
    if window.startswith("second"):
        return max_requests, 1
    if window.startswith("hour"):
        return max_requests, 3600
    return max_requests, 60


def _limit_for(name: WindowName) -> str:
    settings = get_settings()
    return {
        "chat": settings.rate_limit_chat,
        "voice": settings.rate_limit_voice,
        "admin": settings.rate_limit_admin,
    }[name]


def _check(name: WindowName, identity: str) -> None:
    max_requests, seconds = parse_limit(_limit_for(name))
    now = time.monotonic()
    key = (name, identity)
    bucket = _buckets.get(key)
    if bucket is None or bucket.reset_at <= now:
        _buckets[key] = Bucket(reset_at=now + seconds, count=1)
        return
    bucket.count += 1
    if bucket.count > max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limit_exceeded",
        )


def client_identity(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def websocket_identity(websocket: WebSocket) -> str:
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return websocket.client.host if websocket.client else "unknown"


def enforce_rate_limit(name: WindowName, request: Request) -> None:
    _check(name, client_identity(request))


def enforce_ws_rate_limit(name: WindowName, websocket: WebSocket) -> None:
    _check(name, websocket_identity(websocket))


def reset_rate_limits() -> None:
    _buckets.clear()
