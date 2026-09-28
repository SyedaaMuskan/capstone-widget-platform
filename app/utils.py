from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime(_FMT)


def iso_in(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime(_FMT)


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def new_id() -> str:
    return uuid.uuid4().hex


def new_widget_id() -> str:
    return secrets.token_hex(5)
