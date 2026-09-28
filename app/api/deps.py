from __future__ import annotations

from fastapi import Request

from app.container import Container
from app.errors import AppError


def get_container(request: Request) -> Container:
    return request.app.state.c


def client_ip(request: Request) -> str | None:
    if get_container(request).settings.trust_proxy:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def throttle(limiter, key: str) -> None:
    allowed, retry_after = limiter.allow(key)
    if not allowed:
        raise AppError(429, "rate_limited", "Too many requests, slow down", headers={"Retry-After": str(max(1, retry_after))})


def current_user(request: Request) -> dict:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    unauthorized = AppError(401, "unauthorized", "Missing or invalid API key", headers={"WWW-Authenticate": "Bearer"})
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized
    user = get_container(request).auth.authenticate(token.strip())
    if not user:
        raise unauthorized
    return user
