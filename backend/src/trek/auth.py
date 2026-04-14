import hashlib
import hmac
import secrets
import time
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

from trek.config import settings

_sessions: dict[str, float] = {}


class LoginRequest(BaseModel):
    password: str


def _verify_password(plain: str) -> bool:
    if not settings.password_hash:
        return False
    expected = settings.password_hash.encode()
    candidate = hashlib.sha256(plain.encode()).hexdigest().encode()
    return hmac.compare_digest(candidate, expected)


def _create_session(response: Response) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time()
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.session_max_age,
    )
    return token


def _prune_expired() -> None:
    now = time.time()
    expired = [k for k, v in _sessions.items() if now - v > settings.session_max_age]
    for k in expired:
        del _sessions[k]


def require_auth(session: Annotated[str | None, Cookie()] = None) -> str:
    if session is None or session not in _sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    created = _sessions[session]
    if time.time() - created > settings.session_max_age:
        del _sessions[session]
        raise HTTPException(status_code=401, detail="Session expired")
    return session


RequireAuth = Annotated[str, Depends(require_auth)]


def login(body: LoginRequest, response: Response) -> dict:
    if not _verify_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    _prune_expired()
    token = _create_session(response)
    return {"status": "ok", "session": token}


def logout(session: RequireAuth, response: Response) -> dict:
    _sessions.pop(session, None)
    response.delete_cookie("session")
    return {"status": "logged_out"}
