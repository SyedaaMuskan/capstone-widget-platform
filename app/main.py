from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import auth, dashboard, public, submissions, widgets
from app.config import Settings
from app.container import build_container
from app.db import make_engine, run_migrations
from app.errors import register_error_handlers


def create_app(settings: Settings | None = None, email_sender=None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = make_engine(settings.database_url)
    run_migrations(engine)
    container = build_container(settings, engine, email_sender)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.worker_enabled:
            container.worker.start()
        yield
        container.worker.stop()
        engine.dispose()

    app = FastAPI(title="Embeddable Widget & Lead-Capture Platform", version="1.0.0", lifespan=lifespan)
    app.state.c = container

    # CORS: the API is public and uses bearer tokens (no cookies), so any origin may call it.
    # The middleware also answers preflight OPTIONS requests.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key", "If-None-Match"],
        expose_headers=["ETag", "Retry-After"], max_age=600,
    )
    register_error_handlers(app)

    @app.get("/health", tags=["meta"])
    def health():
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    for r in (auth.router, widgets.router, public.router, submissions.router, dashboard.router):
        app.include_router(r)
    if settings.enable_debug:
        from app.api import debug
        app.include_router(debug.router)
    return app
