"""Fault-injection endpoints used to PROVE resilience (probes 4 & 5). Only registered when ENABLE_DEBUG=true."""
import hmac
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_container
from app.errors import AppError
from app.services.geo import MockProvider

router = APIRouter(prefix="/debug", tags=["debug"])


class Faults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    geo_a_down: Optional[bool] = None
    geo_b_down: Optional[bool] = None
    email_fail: Optional[bool] = None


def _guard(request: Request):
    c = get_container(request)
    given = request.headers.get("x-debug-token", "")
    if not c.settings.debug_token or not hmac.compare_digest(given, c.settings.debug_token):
        raise AppError(403, "forbidden", "Invalid debug token")
    return c


def _state(c) -> dict:
    p = c.geo.providers
    return {"geo_mode": c.settings.geo_mode,
            "geo_a_down": getattr(p[0], "down", False), "geo_b_down": getattr(p[1], "down", False),
            "email_fail": c.faults.email_fail}


@router.get("/faults")
def get_faults(request: Request):
    return _state(_guard(request))


@router.put("/faults")
def set_faults(body: Faults, request: Request):
    c = _guard(request)
    if (body.geo_a_down is not None or body.geo_b_down is not None) and not all(isinstance(p, MockProvider) for p in c.geo.providers):
        raise AppError(409, "not_mock_mode", "Geo faults can only be toggled when GEO_MODE=mock")
    if body.geo_a_down is not None:
        c.geo.providers[0].down = body.geo_a_down
    if body.geo_b_down is not None:
        c.geo.providers[1].down = body.geo_b_down
    if body.email_fail is not None:
        c.faults.email_fail = body.email_fail
    return _state(c)


@router.post("/run-jobs")
def run_jobs(request: Request):
    """Run due background jobs right now (deterministic proofs; the worker thread does this automatically)."""
    return {"ran": _guard(request).jobs.run_once()}
