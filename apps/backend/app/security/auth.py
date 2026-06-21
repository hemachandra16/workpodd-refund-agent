"""Admin authentication helpers for protected reasoning-log routes."""

from __future__ import annotations

from hmac import compare_digest

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext
from passlib.exc import PasswordValueError

from app.config import get_settings


ADMIN_COOKIE = "worpodd_admin"
ADMIN_COOKIE_MAX_AGE = 60 * 60 * 8
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.admin_session_secret, salt="worpodd-admin")


def verify_admin_password(username: str, password: str) -> bool:
    settings = get_settings()
    if not compare_digest(username, settings.admin_username):
        return False
    if settings.admin_password_hash and settings.admin_password_hash.startswith("$2"):
        try:
            return bool(_pwd.verify(password, settings.admin_password_hash))
        except (ValueError, PasswordValueError):
            if settings.is_production:
                return False
    if settings.is_production:
        return False
    return compare_digest(password, "admin")


def create_admin_token(username: str) -> str:
    return _serializer().dumps({"sub": username})


def verify_admin_token(token: str) -> str | None:
    try:
        payload = _serializer().loads(token, max_age=ADMIN_COOKIE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    username = payload.get("sub")
    if username == get_settings().admin_username:
        return username
    return None
