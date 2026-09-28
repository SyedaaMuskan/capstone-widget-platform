from fastapi import APIRouter, Request

from app.api.deps import client_ip, get_container, throttle
from app.schemas import LoginIn, RegisterIn

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request):
    c = get_container(request)
    throttle(c.auth_limiter, f"auth:{client_ip(request)}")
    return c.auth.register(body.email, body.password)


@router.post("/login")
def login(body: LoginIn, request: Request):
    c = get_container(request)
    throttle(c.auth_limiter, f"auth:{client_ip(request)}")
    return c.auth.login(body.email, body.password)
