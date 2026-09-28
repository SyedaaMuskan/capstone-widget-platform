from __future__ import annotations

import json

from sqlalchemy.engine import Engine

from app.errors import AppError
from app.repositories import WidgetRepo
from app.schemas import WidgetCreate, WidgetUpdate
from app.utils import new_widget_id, now_iso


def snippet_for(base_url: str, widget_id: str) -> str:
    return f'<script src="{base_url}/widget.js?id={widget_id}" async></script>'


class WidgetService:
    def __init__(self, engine: Engine, public_base_url: str):
        self.engine, self.base = engine, public_base_url

    def _owner_view(self, row: dict) -> dict:
        return {
            "id": row["id"], "type": row["type"], "title": row["title"], "description": row["description"],
            "button_text": row["button_text"], "fields": json.loads(row["fields_json"]),
            "options": json.loads(row["options_json"]), "version": row["version"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "embed_snippet": snippet_for(self.base, row["id"]),
        }

    def create(self, tenant_id: str, data: WidgetCreate, widget_id: str | None = None) -> dict:
        row = {
            "id": widget_id or new_widget_id(), "tenant_id": tenant_id, "type": data.type, "title": data.title,
            "description": data.description, "button_text": data.button_text,
            "fields_json": json.dumps([f.model_dump() for f in data.fields]),
            "options_json": json.dumps(data.options.model_dump()), "now": now_iso(),
        }
        with self.engine.begin() as conn:
            WidgetRepo.insert(conn, row)
            return self._owner_view(WidgetRepo.get_for_tenant(conn, row["id"], tenant_id))

    def list(self, tenant_id: str) -> list[dict]:
        with self.engine.begin() as conn:
            return [self._owner_view(r) for r in WidgetRepo.list_for_tenant(conn, tenant_id)]

    def get(self, tenant_id: str, widget_id: str) -> dict:
        with self.engine.begin() as conn:
            row = WidgetRepo.get_for_tenant(conn, widget_id, tenant_id)
        if not row:  # 404 (not 403): don't reveal that another tenant's widget exists
            raise AppError(404, "widget_not_found", "Widget not found")
        return self._owner_view(row)

    def update(self, tenant_id: str, widget_id: str, data: WidgetUpdate) -> dict:
        changes: dict = {}
        raw = data.model_dump(exclude_unset=True)
        for key in ("type", "title", "description", "button_text"):
            if key in raw and raw[key] is not None:
                changes[key] = raw[key]
        if raw.get("fields") is not None:
            changes["fields_json"] = json.dumps(raw["fields"])
        if raw.get("options") is not None:
            changes["options_json"] = json.dumps(raw["options"])
        with self.engine.begin() as conn:
            if not WidgetRepo.update(conn, widget_id, tenant_id, changes, now_iso()):
                raise AppError(404, "widget_not_found", "Widget not found")
            return self._owner_view(WidgetRepo.get_for_tenant(conn, widget_id, tenant_id))

    def delete(self, tenant_id: str, widget_id: str) -> None:
        with self.engine.begin() as conn:
            if not WidgetRepo.delete(conn, widget_id, tenant_id):
                raise AppError(404, "widget_not_found", "Widget not found")

    def public_config(self, widget_id: str) -> dict | None:
        """Small payload for the browser: only what is needed to render."""
        with self.engine.begin() as conn:
            row = WidgetRepo.get_public(conn, widget_id)
        if not row:
            return None
        return {
            "id": row["id"], "version": row["version"], "type": row["type"], "title": row["title"],
            "description": row["description"], "button_text": row["button_text"],
            "fields": [{k: f[k] for k in ("name", "label", "type", "required", "max_length")} for f in json.loads(row["fields_json"])],
            "options": json.loads(row["options_json"]),
        }
