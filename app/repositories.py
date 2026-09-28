"""Data layer: all SQL lives here. Every tenant-scoped query takes tenant_id explicitly."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection


def _one(result) -> Optional[dict]:
    row = result.first()
    return dict(row._mapping) if row else None


def _all(result) -> list[dict]:
    return [dict(r._mapping) for r in result]


class UserRepo:
    @staticmethod
    def create(conn: Connection, id: str, email: str, password_hash: str, created_at: str) -> None:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash, created_at) VALUES (:id, :email, :ph, :ca)"),
            {"id": id, "email": email, "ph": password_hash, "ca": created_at},
        )

    @staticmethod
    def get_by_email(conn: Connection, email: str) -> Optional[dict]:
        return _one(conn.execute(text("SELECT id, email, password_hash FROM users WHERE email = :e"), {"e": email}))

    @staticmethod
    def add_api_key(conn: Connection, token_hash: str, user_id: str, created_at: str) -> None:
        conn.execute(
            text("INSERT INTO api_keys (token_hash, user_id, created_at) VALUES (:h, :u, :c)"),
            {"h": token_hash, "u": user_id, "c": created_at},
        )

    @staticmethod
    def get_by_token_hash(conn: Connection, token_hash: str) -> Optional[dict]:
        return _one(conn.execute(
            text("SELECT u.id AS id, u.email AS email FROM api_keys k JOIN users u ON u.id = k.user_id WHERE k.token_hash = :h"),
            {"h": token_hash},
        ))


class WidgetRepo:
    _COLS = "id, tenant_id, type, title, description, button_text, fields_json, options_json, version, created_at, updated_at"
    # whitelist: column names are never taken from user input
    _UPDATABLE = {"type", "title", "description", "button_text", "fields_json", "options_json"}

    @staticmethod
    def insert(conn: Connection, row: dict) -> None:
        conn.execute(text(
            "INSERT INTO widgets (id, tenant_id, type, title, description, button_text, fields_json, options_json, version, created_at, updated_at) "
            "VALUES (:id, :tenant_id, :type, :title, :description, :button_text, :fields_json, :options_json, 1, :now, :now)"
        ), row)

    @staticmethod
    def get_for_tenant(conn: Connection, widget_id: str, tenant_id: str) -> Optional[dict]:
        return _one(conn.execute(
            text(f"SELECT {WidgetRepo._COLS} FROM widgets WHERE id = :id AND tenant_id = :t"), {"id": widget_id, "t": tenant_id}))

    @staticmethod
    def get_public(conn: Connection, widget_id: str) -> Optional[dict]:
        return _one(conn.execute(text(f"SELECT {WidgetRepo._COLS} FROM widgets WHERE id = :id"), {"id": widget_id}))

    @staticmethod
    def list_for_tenant(conn: Connection, tenant_id: str) -> list[dict]:
        return _all(conn.execute(
            text(f"SELECT {WidgetRepo._COLS} FROM widgets WHERE tenant_id = :t ORDER BY created_at DESC"), {"t": tenant_id}))

    @staticmethod
    def update(conn: Connection, widget_id: str, tenant_id: str, changes: dict[str, Any], now: str) -> bool:
        cols = [c for c in changes if c in WidgetRepo._UPDATABLE]
        sets = ", ".join(f"{c} = :{c}" for c in cols)
        sql = f"UPDATE widgets SET {sets + ', ' if sets else ''}version = version + 1, updated_at = :now WHERE id = :id AND tenant_id = :t"
        params = {**{c: changes[c] for c in cols}, "now": now, "id": widget_id, "t": tenant_id}
        return conn.execute(text(sql), params).rowcount == 1

    @staticmethod
    def delete(conn: Connection, widget_id: str, tenant_id: str) -> bool:
        conn.execute(text("DELETE FROM submissions WHERE widget_id = :id AND tenant_id = :t"), {"id": widget_id, "t": tenant_id})
        return conn.execute(text("DELETE FROM widgets WHERE id = :id AND tenant_id = :t"), {"id": widget_id, "t": tenant_id}).rowcount == 1


class SubmissionRepo:
    @staticmethod
    def insert(conn: Connection, row: dict) -> None:
        conn.execute(text(
            "INSERT INTO submissions (id, widget_id, tenant_id, data_json, ip, user_agent, origin, geo_country, geo_country_code, "
            "geo_region, geo_city, geo_provider, idempotency_key, created_at, created_date) VALUES "
            "(:id, :widget_id, :tenant_id, :data_json, :ip, :user_agent, :origin, :geo_country, :geo_country_code, "
            ":geo_region, :geo_city, :geo_provider, :idempotency_key, :created_at, :created_date)"
        ), row)

    @staticmethod
    def find_by_idempotency(conn: Connection, widget_id: str, key: str) -> Optional[dict]:
        return _one(conn.execute(
            text("SELECT id, geo_provider FROM submissions WHERE widget_id = :w AND idempotency_key = :k"), {"w": widget_id, "k": key}))

    @staticmethod
    def get(conn: Connection, submission_id: str) -> Optional[dict]:
        return _one(conn.execute(text("SELECT * FROM submissions WHERE id = :id"), {"id": submission_id}))

    @staticmethod
    def list_for_tenant(conn: Connection, tenant_id: str, widget_id: Optional[str], limit: int, offset: int) -> tuple[list[dict], int]:
        where, params = "tenant_id = :t", {"t": tenant_id}
        if widget_id:
            where += " AND widget_id = :w"
            params["w"] = widget_id
        total = conn.execute(text(f"SELECT COUNT(*) FROM submissions WHERE {where}"), params).scalar_one()
        rows = _all(conn.execute(text(
            f"SELECT id, widget_id, data_json, geo_country, geo_country_code, geo_region, geo_city, geo_provider, origin, created_at "
            f"FROM submissions WHERE {where} ORDER BY created_at DESC, id DESC LIMIT :l OFFSET :o"
        ), {**params, "l": limit, "o": offset}))
        return rows, int(total)

    @staticmethod
    def stats(conn: Connection, tenant_id: str, widget_id: Optional[str], since: str) -> dict:
        extra_s = " AND s.widget_id = :w" if widget_id else ""
        extra_w = " AND w.id = :w" if widget_id else ""
        params: dict[str, Any] = {"t": tenant_id, "since": since}
        if widget_id:
            params["w"] = widget_id
        per_widget = _all(conn.execute(text(
            "SELECT w.id AS widget_id, w.title AS title, COUNT(s.id) AS submissions "
            "FROM widgets w LEFT JOIN submissions s ON s.widget_id = w.id AND s.created_date >= :since "
            f"WHERE w.tenant_id = :t{extra_w} GROUP BY w.id, w.title ORDER BY submissions DESC"
        ), params))
        over_time = _all(conn.execute(text(
            "SELECT s.created_date AS day, COUNT(*) AS submissions FROM submissions s "
            f"WHERE s.tenant_id = :t AND s.created_date >= :since{extra_s} GROUP BY s.created_date ORDER BY s.created_date"
        ), params))
        geo = _all(conn.execute(text(
            "SELECT COALESCE(s.geo_country, 'Unknown') AS country, COUNT(*) AS submissions FROM submissions s "
            f"WHERE s.tenant_id = :t AND s.created_date >= :since{extra_s} "
            "GROUP BY COALESCE(s.geo_country, 'Unknown') ORDER BY submissions DESC LIMIT 20"
        ), params))
        return {"per_widget": per_widget, "over_time": over_time, "geo": geo}


class JobRepo:
    @staticmethod
    def enqueue(conn: Connection, id: str, tenant_id: Optional[str], type: str, payload_json: str, max_attempts: int, now: str) -> None:
        conn.execute(text(
            "INSERT INTO jobs (id, tenant_id, type, payload_json, status, attempts, max_attempts, next_run_at, created_at, updated_at) "
            "VALUES (:id, :t, :type, :p, 'pending', 0, :m, :now, :now, :now)"
        ), {"id": id, "t": tenant_id, "type": type, "p": payload_json, "m": max_attempts, "now": now})

    @staticmethod
    def claim_due(conn: Connection, now: str, limit: int) -> list[dict]:
        due = _all(conn.execute(text(
            "SELECT id, type, payload_json, attempts, max_attempts FROM jobs "
            "WHERE status = 'pending' AND next_run_at <= :now ORDER BY next_run_at LIMIT :l"
        ), {"now": now, "l": limit}))
        claimed = []
        for job in due:  # optimistic claim: only one worker wins each row
            n = conn.execute(text("UPDATE jobs SET status = 'running', updated_at = :now WHERE id = :id AND status = 'pending'"),
                             {"now": now, "id": job["id"]}).rowcount
            if n == 1:
                claimed.append(job)
        return claimed

    @staticmethod
    def mark_done(conn: Connection, job_id: str, now: str) -> None:
        conn.execute(text("UPDATE jobs SET status = 'done', updated_at = :now WHERE id = :id"), {"now": now, "id": job_id})

    @staticmethod
    def mark_retry(conn: Connection, job_id: str, attempts: int, next_run_at: str, error: str, now: str) -> None:
        conn.execute(text(
            "UPDATE jobs SET status = 'pending', attempts = :a, next_run_at = :n, last_error = :e, updated_at = :now WHERE id = :id"
        ), {"a": attempts, "n": next_run_at, "e": error, "now": now, "id": job_id})

    @staticmethod
    def mark_failed(conn: Connection, job_id: str, attempts: int, error: str, now: str) -> None:
        conn.execute(text(
            "UPDATE jobs SET status = 'failed', attempts = :a, last_error = :e, updated_at = :now WHERE id = :id"
        ), {"a": attempts, "e": error, "now": now, "id": job_id})

    @staticmethod
    def requeue_stuck(conn: Connection, now: str) -> int:
        return conn.execute(text("UPDATE jobs SET status = 'pending', updated_at = :now WHERE status = 'running'"), {"now": now}).rowcount

    @staticmethod
    def list_failed(conn: Connection, tenant_id: str, limit: int = 50) -> list[dict]:
        return _all(conn.execute(text(
            "SELECT id, type, attempts, max_attempts, last_error, updated_at FROM jobs "
            "WHERE status = 'failed' AND tenant_id = :t ORDER BY updated_at DESC LIMIT :l"
        ), {"t": tenant_id, "l": limit}))

    @staticmethod
    def counts(conn: Connection) -> dict[str, int]:
        return {r[0]: int(r[1]) for r in conn.execute(text("SELECT status, COUNT(*) FROM jobs GROUP BY status"))}
