"""Submission pipeline: honeypot -> validate -> idempotency -> geo enrich -> store -> enqueue side effect."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.errors import AppError
from app.repositories import SubmissionRepo, WidgetRepo
from app.schemas import EMAIL_RE
from app.services.geo import GeoChain
from app.services.jobs import JobRunner
from app.utils import new_id, now_iso, today

logger = logging.getLogger(__name__)
TEL_RE = re.compile(r"^[0-9+()\-.\s]{5,30}$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class SubmitResult:
    status: int
    body: dict


def validate_payload(fields: list[dict], data: dict) -> dict:
    """Validate submitted data against the widget's field definitions. Raises 422 with per-field messages."""
    errors: list[dict] = []
    known = {f["name"]: f for f in fields}
    for key in data:
        if key not in known:
            errors.append({"field": str(key)[:50], "message": "unknown field"})
    cleaned: dict[str, str] = {}
    for name, f in known.items():
        raw = data.get(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if f["required"]:
                errors.append({"field": name, "message": "this field is required"})
            continue
        if not isinstance(raw, str):
            errors.append({"field": name, "message": "must be a string"})
            continue
        value = raw.strip()
        if len(value) > f["max_length"]:
            errors.append({"field": name, "message": f"must be at most {f['max_length']} characters"})
        elif CONTROL_RE.search(value) or (f["type"] != "textarea" and ("\n" in value or "\r" in value)):
            errors.append({"field": name, "message": "contains invalid characters"})
        elif f["type"] == "email" and (len(value) > 254 or not EMAIL_RE.match(value)):
            errors.append({"field": name, "message": "must be a valid email address"})
        elif f["type"] == "tel" and not TEL_RE.match(value):
            errors.append({"field": name, "message": "must be a valid phone number"})
        else:
            cleaned[name] = value
    if errors:
        raise AppError(422, "validation_error", "Submission validation failed", errors)
    return cleaned


class SubmissionService:
    def __init__(self, engine: Engine, geo: GeoChain, jobs: JobRunner):
        self.engine, self.geo, self.jobs = engine, geo, jobs

    def widget_exists(self, widget_id: str) -> bool:
        with self.engine.begin() as conn:
            return WidgetRepo.get_public(conn, widget_id) is not None

    def submit(self, *, widget_id: str, data: dict, honeypot, idempotency_key: Optional[str],
               ip: Optional[str], user_agent: str, origin: str) -> SubmitResult:
        with self.engine.begin() as conn:
            widget = WidgetRepo.get_public(conn, widget_id)
        if not widget:
            raise AppError(404, "widget_not_found", "Widget not found")

        # Spam control #1: honeypot. Bots fill hidden fields; humans can't see them.
        # Respond as if it worked so the bot learns nothing, but store nothing.
        if honeypot not in ("", None):
            logger.info("honeypot triggered for widget %s from %s", widget_id, ip)
            return SubmitResult(202, {"ok": True})

        cleaned = validate_payload(json.loads(widget["fields_json"]), data)

        if idempotency_key:  # retried request -> return the original result, do nothing twice
            with self.engine.begin() as conn:
                existing = SubmissionRepo.find_by_idempotency(conn, widget_id, idempotency_key)
            if existing:
                return SubmitResult(200, {"ok": True, "id": existing["id"], "duplicate": True})

        geo = None
        try:  # enrichment is best-effort: it may degrade the row, never the request
            geo = self.geo.enrich(ip)
        except Exception:
            logger.exception("geo enrichment crashed; continuing without geo")

        now = now_iso()
        row = {
            "id": new_id(), "widget_id": widget_id, "tenant_id": widget["tenant_id"], "data_json": json.dumps(cleaned),
            "ip": ip, "user_agent": (user_agent or "")[:300], "origin": (origin or "")[:200],
            "geo_country": geo.country if geo else None, "geo_country_code": geo.country_code if geo else None,
            "geo_region": geo.region if geo else None, "geo_city": geo.city if geo else None,
            "geo_provider": geo.provider if geo else None, "idempotency_key": idempotency_key,
            "created_at": now, "created_date": today(),
        }
        try:
            with self.engine.begin() as conn:
                SubmissionRepo.insert(conn, row)
        except IntegrityError:  # two identical retries raced; the unique index made one win
            with self.engine.begin() as conn:
                existing = SubmissionRepo.find_by_idempotency(conn, widget_id, idempotency_key or "")
            if existing:
                return SubmitResult(200, {"ok": True, "id": existing["id"], "duplicate": True})
            raise

        # Safe side effect: enqueue for the background worker. Even if enqueueing itself fails,
        # the submission is already committed and the visitor still gets success.
        try:
            self.jobs.enqueue("send_confirmation", {"submission_id": row["id"]}, tenant_id=widget["tenant_id"])
        except Exception:
            logger.exception("could not enqueue confirmation job for submission %s", row["id"])

        return SubmitResult(201, {"ok": True, "id": row["id"], "enriched": geo is not None, "geo_provider": geo.provider if geo else None})
