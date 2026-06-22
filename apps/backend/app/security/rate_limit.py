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


# --- Login brute-force protection ---------------------------------------
# A separate, stricter counter for failed login attempts per (username, IP).
# After MAX_FAILED_LOGIN_ATTEMPTS failures in the window, the account is
# locked out for LOCKOUT_SECONDS before another attempt is allowed. A
# successful login clears the counter. This runs in addition to the general
# per-window rate limit, because 120 admin requests/minute is far too loose
# for a login endpoint.
MAX_FAILED_LOGIN_ATTEMPTS = 5
FAILED_LOGIN_WINDOW_SECONDS = 300  # 5 min rolling window for counting failures
LOCKOUT_SECONDS = 60               # how long a locked-out identity must wait


@dataclass
class LoginFailureBucket:
    fail_count: int
    window_reset_at: float          # when the failure counter resets
    locked_until: float             # 0 if not locked


_login_failures: dict[str, LoginFailureBucket] = {}


def _login_key(username: str, ip: str) -> str:
    return f"{username.lower()}@{ip}"


def enforce_login_throttle(username: str, request: Request) -> None:
    """Raise 429 if this (username, IP) is currently locked out."""
    ip = client_identity(request)
    key = _login_key(username, ip)
    now = time.monotonic()
    bucket = _login_failures.get(key)
    if bucket and bucket.locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="account_temporarily_locked",
            headers={"Retry-After": str(int(bucket.locked_until - now) + 1)},
        )


def record_login_failure(username: str, request: Request) -> None:
    """Record a failed login attempt; lock out after the threshold is exceeded."""
    ip = client_identity(request)
    key = _login_key(username, ip)
    now = time.monotonic()
    bucket = _login_failures.get(key)
    if bucket is None or bucket.window_reset_at <= now:
        bucket = LoginFailureBucket(
            fail_count=0,
            window_reset_at=now + FAILED_LOGIN_WINDOW_SECONDS,
            locked_until=0.0,
        )
        _login_failures[key] = bucket
    bucket.fail_count += 1
    if bucket.fail_count >= MAX_FAILED_LOGIN_ATTEMPTS:
        bucket.locked_until = now + LOCKOUT_SECONDS


def record_login_success(username: str, request: Request) -> None:
    """Clear the failure counter on a successful login."""
    ip = client_identity(request)
    key = _login_key(username, ip)
    _login_failures.pop(key, None)


def reset_login_throttle() -> None:
    """Clear all login-throttle state (used by tests)."""
    _login_failures.clear()

