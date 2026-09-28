"""Settings loaded from environment variables (see .env.example). No secrets in code."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./dev.db"
    public_base_url: str = "http://localhost:8000"
    max_body_bytes: int = 10_240

    rate_ip_capacity: float = 10
    rate_ip_refill_per_sec: float = 2
    rate_widget_capacity: float = 100
    rate_widget_refill_per_sec: float = 5
    trust_proxy: bool = False

    geo_mode: str = "live"  # live | mock
    geo_timeout_seconds: float = 2.0

    email_backend: str = "console"  # console | smtp
    email_from: str = "widgets@example.com"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False

    worker_enabled: bool = True
    job_max_attempts: int = 4
    job_backoff_base_seconds: float = 2.0
    worker_poll_seconds: float = 1.0

    config_cache_seconds: int = 60
    loader_cache_seconds: int = 300

    enable_debug: bool = False
    debug_token: str = ""

    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            public_base_url=os.getenv("PUBLIC_BASE_URL", cls.public_base_url).rstrip("/"),
            max_body_bytes=_int("MAX_BODY_BYTES", cls.max_body_bytes),
            rate_ip_capacity=_float("RATE_IP_CAPACITY", cls.rate_ip_capacity),
            rate_ip_refill_per_sec=_float("RATE_IP_REFILL_PER_SEC", cls.rate_ip_refill_per_sec),
            rate_widget_capacity=_float("RATE_WIDGET_CAPACITY", cls.rate_widget_capacity),
            rate_widget_refill_per_sec=_float("RATE_WIDGET_REFILL_PER_SEC", cls.rate_widget_refill_per_sec),
            trust_proxy=_bool("TRUST_PROXY", cls.trust_proxy),
            geo_mode=os.getenv("GEO_MODE", cls.geo_mode).lower(),
            geo_timeout_seconds=_float("GEO_TIMEOUT_SECONDS", cls.geo_timeout_seconds),
            email_backend=os.getenv("EMAIL_BACKEND", cls.email_backend).lower(),
            email_from=os.getenv("EMAIL_FROM", cls.email_from),
            smtp_host=os.getenv("SMTP_HOST", cls.smtp_host),
            smtp_port=_int("SMTP_PORT", cls.smtp_port),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_starttls=_bool("SMTP_STARTTLS", cls.smtp_starttls),
            worker_enabled=_bool("WORKER_ENABLED", cls.worker_enabled),
            job_max_attempts=_int("JOB_MAX_ATTEMPTS", cls.job_max_attempts),
            job_backoff_base_seconds=_float("JOB_BACKOFF_BASE_SECONDS", cls.job_backoff_base_seconds),
            worker_poll_seconds=_float("WORKER_POLL_SECONDS", cls.worker_poll_seconds),
            config_cache_seconds=_int("CONFIG_CACHE_SECONDS", cls.config_cache_seconds),
            loader_cache_seconds=_int("LOADER_CACHE_SECONDS", cls.loader_cache_seconds),
            enable_debug=_bool("ENABLE_DEBUG", cls.enable_debug),
            debug_token=os.getenv("DEBUG_TOKEN", ""),
            log_level=os.getenv("LOG_LEVEL", cls.log_level).upper(),
        )
