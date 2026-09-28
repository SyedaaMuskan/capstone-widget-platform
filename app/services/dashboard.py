from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.engine import Engine

from app.errors import AppError
from app.repositories import JobRepo, SubmissionRepo, WidgetRepo
from app.utils import days_ago


class DashboardService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def _assert_owns(self, conn, tenant_id: str, widget_id: Optional[str]) -> None:
        if widget_id and not WidgetRepo.get_for_tenant(conn, widget_id, tenant_id):
            raise AppError(404, "widget_not_found", "Widget not found")

    def submissions(self, tenant_id: str, widget_id: Optional[str], limit: int, offset: int) -> dict:
        with self.engine.begin() as conn:
            self._assert_owns(conn, tenant_id, widget_id)
            rows, total = SubmissionRepo.list_for_tenant(conn, tenant_id, widget_id, limit, offset)
        items = [{
            "id": r["id"], "widget_id": r["widget_id"], "data": json.loads(r["data_json"]),
            "geo": {"country": r["geo_country"], "country_code": r["geo_country_code"], "region": r["geo_region"],
                    "city": r["geo_city"], "provider": r["geo_provider"]} if r["geo_provider"] else None,
            "origin": r["origin"], "created_at": r["created_at"],
        } for r in rows]
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    def stats(self, tenant_id: str, widget_id: Optional[str], days: int) -> dict:
        with self.engine.begin() as conn:
            self._assert_owns(conn, tenant_id, widget_id)
            s = SubmissionRepo.stats(conn, tenant_id, widget_id, days_ago(days - 1))
        return {"days": days, "total": sum(r["submissions"] for r in s["over_time"]), **s}

    def failed_jobs(self, tenant_id: str) -> list[dict]:
        with self.engine.begin() as conn:
            return JobRepo.list_failed(conn, tenant_id)
