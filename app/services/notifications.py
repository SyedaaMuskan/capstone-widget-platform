"""Email side effect. It runs in the background job worker, so a failure can never break a submission."""
from __future__ import annotations

import json
import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage

from sqlalchemy.engine import Engine

from app.config import Settings
from app.repositories import SubmissionRepo, WidgetRepo

logger = logging.getLogger(__name__)


class ConsoleEmailSender:
    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("[fake email] to=%s subject=%s\n%s", to, subject, body)


class MemoryEmailSender:
    """Used by tests to assert what would have been sent."""

    def __init__(self):
        self.outbox: list[dict] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.outbox.append({"to": to, "subject": subject, "body": body})


class SmtpEmailSender:
    def __init__(self, s: Settings):
        self.s = s

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.email_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=10) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)


def build_email_sender(s: Settings):
    return SmtpEmailSender(s) if s.email_backend == "smtp" else ConsoleEmailSender()


@dataclass
class DebugFaults:
    email_fail: bool = False


class NotificationService:
    def __init__(self, engine: Engine, sender, faults: DebugFaults):
        self.engine, self.sender, self.faults = engine, sender, faults

    def send_confirmation(self, payload: dict) -> str:
        if self.faults.email_fail:
            raise RuntimeError("email provider unavailable (forced by debug fault)")
        with self.engine.begin() as conn:
            sub = SubmissionRepo.get(conn, payload["submission_id"])
            widget = WidgetRepo.get_public(conn, sub["widget_id"]) if sub else None
        if not sub or not widget:
            return "skipped: submission or widget no longer exists"
        data = json.loads(sub["data_json"])
        to = next((data[f["name"]] for f in json.loads(widget["fields_json"]) if f["type"] == "email" and data.get(f["name"])), None)
        if not to:
            return "skipped: no email field"
        title = widget["title"].replace("\r", " ").replace("\n", " ")
        self.sender.send(to, f"Thanks - we received your message ({title})", f"Hi,\n\nThanks for reaching out via \"{title}\". We received your submission.\n")
        return "sent"
