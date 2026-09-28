"""Composition root: builds every dependency once."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import Engine

from app.config import Settings
from app.ratelimit import TokenBucketLimiter
from app.services.auth import AuthService
from app.services.dashboard import DashboardService
from app.services.geo import GeoChain, build_geo_chain
from app.services.jobs import JobRunner, Worker
from app.services.notifications import DebugFaults, NotificationService, build_email_sender
from app.services.submissions import SubmissionService
from app.services.widgets import WidgetService


@dataclass
class Container:
    settings: Settings
    engine: Engine
    ip_limiter: TokenBucketLimiter
    widget_limiter: TokenBucketLimiter
    auth_limiter: TokenBucketLimiter
    geo: GeoChain
    faults: DebugFaults
    email_sender: Any
    auth: AuthService
    widgets: WidgetService
    submissions: SubmissionService
    dashboard: DashboardService
    jobs: JobRunner
    worker: Worker


def build_container(s: Settings, engine: Engine, email_sender=None) -> Container:
    faults = DebugFaults()
    sender = email_sender or build_email_sender(s)
    notifications = NotificationService(engine, sender, faults)
    jobs = JobRunner(engine, s, {"send_confirmation": notifications.send_confirmation})
    geo = build_geo_chain(s.geo_mode, s.geo_timeout_seconds)
    return Container(
        settings=s, engine=engine,
        ip_limiter=TokenBucketLimiter(s.rate_ip_capacity, s.rate_ip_refill_per_sec),
        widget_limiter=TokenBucketLimiter(s.rate_widget_capacity, s.rate_widget_refill_per_sec),
        auth_limiter=TokenBucketLimiter(10, 0.2),
        geo=geo, faults=faults, email_sender=sender,
        auth=AuthService(engine), widgets=WidgetService(engine, s.public_base_url),
        submissions=SubmissionService(engine, geo, jobs), dashboard=DashboardService(engine),
        jobs=jobs, worker=Worker(jobs, s.worker_poll_seconds),
    )
