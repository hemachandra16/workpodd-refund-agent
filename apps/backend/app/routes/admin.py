"""Auth-gated admin routes for reasoning logs and decisions."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.db import SessionLocal
from app.models import ReasoningEvent
from app.security.auth import (
    ADMIN_COOKIE,
    ADMIN_COOKIE_MAX_AGE,
    create_admin_token,
    verify_admin_password,
    verify_admin_token,
)
from app.security.rate_limit import (
    enforce_login_throttle,
    enforce_rate_limit,
    record_login_failure,
    record_login_success,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminLoginRequest(BaseModel):
    # Reject unexpected fields (mass-assignment defense).
    model_config = {"extra": "forbid"}

    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


def admin_rate_limit(request: Request) -> None:
    enforce_rate_limit("admin", request)


def require_admin(token: str | None = Cookie(default=None, alias=ADMIN_COOKIE)) -> str:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin_auth_required")
    username = verify_admin_token(token)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin_auth_required")
    return username


@router.post("/login", dependencies=[Depends(admin_rate_limit)])
async def login(login_request: AdminLoginRequest, raw_request: Request, response: Response) -> dict[str, str]:
    # Stricter per-(username, IP) lockout than the general admin rate limit.
    enforce_login_throttle(login_request.username, raw_request)

    if not verify_admin_password(login_request.username, login_request.password):
        record_login_failure(login_request.username, raw_request)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    record_login_success(login_request.username, raw_request)

    # The Secure flag must be set whenever we run over HTTPS (production).
    # In dev (localhost, http) Secure would prevent the browser from storing
    # the cookie at all, so it is gated on the environment.
    secure_cookie = get_settings().is_production
    response.set_cookie(
        ADMIN_COOKIE,
        create_admin_token(login_request.username),
        max_age=ADMIN_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure_cookie,
    )
    return {"status": "ok", "username": login_request.username}


@router.post("/logout", dependencies=[Depends(admin_rate_limit)])
async def logout(response: Response, _admin: str = Depends(require_admin)) -> dict[str, str]:
    response.delete_cookie(ADMIN_COOKIE)
    return {"status": "ok"}


@router.get("/me", dependencies=[Depends(admin_rate_limit)])
async def me(admin: str = Depends(require_admin)) -> dict[str, str]:
    return {"username": admin}


@router.get("/sessions", dependencies=[Depends(admin_rate_limit)])
async def sessions(_admin: str = Depends(require_admin)) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(ReasoningEvent).order_by(ReasoningEvent.id.desc()).limit(500)
        ).all()

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = grouped.setdefault(
            row.session_id,
            {
                "session_id": row.session_id,
                "latest_event_id": row.id,
                "latest_summary": row.summary,
                "latest_status": row.status,
                "latest_tool": row.tool_called,
                "event_count": 0,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            },
        )
        item["event_count"] += 1
    return list(grouped.values())


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    _limit: None = Depends(admin_rate_limit),
    _admin: str = Depends(require_admin),
) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(ReasoningEvent)
            .where(ReasoningEvent.session_id == session_id)
            .order_by(ReasoningEvent.sequence.asc(), ReasoningEvent.id.asc())
        ).all()
    return [json.loads(row.event_json) for row in rows]


@router.get("/events/stream")
async def events_stream(
    after_id: int = 0,
    _limit: None = Depends(admin_rate_limit),
    _admin: str = Depends(require_admin),
):
    async def generator():
        last_id = after_id
        idle = 0
        while idle < 120:
            with SessionLocal() as db:
                rows = db.scalars(
                    select(ReasoningEvent)
                    .where(ReasoningEvent.id > last_id)
                    .order_by(ReasoningEvent.id.asc())
                    .limit(50)
                ).all()
            if rows:
                idle = 0
                for row in rows:
                    last_id = row.id
                    payload = json.loads(row.event_json)
                    payload["id"] = row.id
                    payload["session_id"] = row.session_id
                    yield {"event": "reasoning", "data": json.dumps(payload, default=str)}
            else:
                idle += 1
                yield {"event": "heartbeat", "data": json.dumps({"last_id": last_id})}
                await asyncio.sleep(1)

    return EventSourceResponse(generator())
