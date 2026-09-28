from __future__ import annotations

from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.errors import AppError
from app.repositories import UserRepo
from app.security import hash_password, hash_token, new_api_key, verify_password
from app.utils import new_id, now_iso

_DUMMY_HASH = hash_password("dummy-password-for-timing")


class AuthService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def register(self, email: str, password: str) -> dict:
        user_id, token = new_id(), new_api_key()
        try:
            with self.engine.begin() as conn:
                UserRepo.create(conn, user_id, email, hash_password(password), now_iso())
                UserRepo.add_api_key(conn, hash_token(token), user_id, now_iso())
        except IntegrityError:
            raise AppError(409, "email_taken", "An account with this email already exists")
        return {"user_id": user_id, "email": email, "api_key": token}

    def login(self, email: str, password: str) -> dict:
        email = email.strip().lower()
        with self.engine.begin() as conn:
            user = UserRepo.get_by_email(conn, email)
            ok = verify_password(password, user["password_hash"] if user else _DUMMY_HASH)  # constant-ish time
            if not user or not ok:
                raise AppError(401, "invalid_credentials", "Invalid email or password")
            token = new_api_key()
            UserRepo.add_api_key(conn, hash_token(token), user["id"], now_iso())
        return {"user_id": user["id"], "email": user["email"], "api_key": token}

    def authenticate(self, token: str) -> Optional[dict]:
        with self.engine.begin() as conn:
            return UserRepo.get_by_token_hash(conn, hash_token(token))
