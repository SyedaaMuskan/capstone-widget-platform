"""Owner-only widget management (tenant isolated by construction: every call carries user['id'])."""
from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import current_user, get_container
from app.schemas import WidgetCreate, WidgetUpdate
from app.services.widgets import snippet_for

router = APIRouter(prefix="/widgets", tags=["widgets"])


@router.post("", status_code=201)
def create_widget(body: WidgetCreate, request: Request, user: dict = Depends(current_user)):
    return get_container(request).widgets.create(user["id"], body)


@router.get("")
def list_widgets(request: Request, user: dict = Depends(current_user)):
    return {"items": get_container(request).widgets.list(user["id"])}


@router.get("/{widget_id}")
def get_widget(widget_id: str, request: Request, user: dict = Depends(current_user)):
    return get_container(request).widgets.get(user["id"], widget_id)


@router.patch("/{widget_id}")
def update_widget(widget_id: str, body: WidgetUpdate, request: Request, user: dict = Depends(current_user)):
    return get_container(request).widgets.update(user["id"], widget_id, body)


@router.delete("/{widget_id}", status_code=204)
def delete_widget(widget_id: str, request: Request, user: dict = Depends(current_user)):
    get_container(request).widgets.delete(user["id"], widget_id)
    return Response(status_code=204)


@router.get("/{widget_id}/snippet")
def get_snippet(widget_id: str, request: Request, user: dict = Depends(current_user)):
    c = get_container(request)
    c.widgets.get(user["id"], widget_id)  # 404 unless the caller owns it
    return {"widget_id": widget_id, "snippet": snippet_for(c.settings.public_base_url, widget_id)}
