"""Public, cacheable delivery: loader (short cache), versioned bundle (immutable), widget config (short cache + ETag)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.deps import get_container
from app.errors import AppError

router = APIRouter(tags=["public"])
BUNDLE_SRC = (Path(__file__).resolve().parent.parent / "static" / "widget.js").read_bytes()
BUNDLE_HASH = hashlib.sha256(BUNDLE_SRC).hexdigest()[:10]  # content hash => new content = new URL
LOADER = (
    "(function(){var s=document.currentScript;if(!s)return;var u=new URL(s.src);var id=u.searchParams.get('id');if(!id)return;"
    "var b=document.createElement('script');b.src=u.origin+'/assets/widget." + BUNDLE_HASH + ".js';b.async=true;"
    "b.setAttribute('data-widget-id',id);b.setAttribute('data-api',u.origin);document.head.appendChild(b);})();"
).encode()
ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,32}$")


@router.get("/widget.js")
def loader(request: Request, id: str = Query(...)):
    """The one line customers paste points here. Tiny, cached for minutes; it loads the immutable bundle."""
    if not ID_RE.match(id):
        raise AppError(400, "invalid_widget_id", "Invalid widget id")
    ttl = get_container(request).settings.loader_cache_seconds
    return Response(LOADER, media_type="application/javascript", headers={
        "Cache-Control": f"public, max-age={ttl}", "ETag": f'"loader-{BUNDLE_HASH}"', "X-Content-Type-Options": "nosniff"})


@router.get("/assets/widget.{version}.js")
def bundle(version: str):
    """Versioned bundle: safe to cache for a year because the URL changes when the content does."""
    if version != BUNDLE_HASH:
        raise AppError(404, "not_found", "Unknown bundle version")
    return Response(BUNDLE_SRC, media_type="application/javascript", headers={
        "Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})


@router.get("/widgets/{widget_id}/config")
def widget_config(widget_id: str, request: Request):
    c = get_container(request)
    cfg = c.widgets.public_config(widget_id) if ID_RE.match(widget_id) else None
    if cfg is None:
        raise AppError(404, "widget_not_found", "Widget not found", headers={"Cache-Control": "no-store"})
    etag = f'W/"{cfg["id"]}-v{cfg["version"]}"'  # version bumps on every edit
    headers = {"Cache-Control": f"public, max-age={c.settings.config_cache_seconds}", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(cfg, headers=headers)
