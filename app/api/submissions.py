"""The public, hostile-internet-facing endpoint. Order matters: cheap checks first."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.deps import client_ip, get_container, throttle
from app.errors import AppError, validation_details
from app.schemas import SubmissionIn

router = APIRouter(tags=["submissions"])


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise AppError(413, "payload_too_large", f"Request body must be at most {limit} bytes")
    chunks, size = [], 0
    async for chunk in request.stream():  # enforce the limit even when Content-Length lies / is absent
        size += len(chunk)
        if size > limit:
            raise AppError(413, "payload_too_large", f"Request body must be at most {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/submissions")
async def create_submission(request: Request):
    c = get_container(request)
    ip = client_ip(request)

    throttle(c.ip_limiter, f"ip:{ip}")                                   # 1. per-IP rate limit (before reading the body)
    if "application/json" not in request.headers.get("content-type", ""):
        raise AppError(415, "unsupported_media_type", "Content-Type must be application/json")
    raw = await _read_body(request, c.settings.max_body_bytes)            # 2. size limit
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise AppError(400, "invalid_json", "Request body is not valid JSON")
    try:
        body = SubmissionIn.model_validate(payload)                       # 3. shape validation
    except ValidationError as exc:
        raise AppError(422, "validation_error", "Request validation failed", validation_details(exc.errors()))

    throttle(c.widget_limiter, f"widget:{body.widget_id}")                # 4. per-widget rate limit
    result = await run_in_threadpool(                                     # 5. honeypot, field validation, idempotency, geo, store, enqueue
        c.submissions.submit,
        widget_id=body.widget_id, data=body.data, honeypot=body.hp,
        idempotency_key=request.headers.get("idempotency-key") or body.idempotency_key,
        ip=ip, user_agent=request.headers.get("user-agent", ""), origin=request.headers.get("origin", ""),
    )
    return JSONResponse(result.body, status_code=result.status)
