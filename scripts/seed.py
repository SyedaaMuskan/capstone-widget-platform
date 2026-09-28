"""Seed demo data (idempotent): a demo owner + the widget used by demo/index.html.
Run:  python -m scripts.seed      (or)  docker compose run --rm api python -m scripts.seed
"""
from app.config import Settings
from app.db import make_engine, run_migrations
from app.errors import AppError
from app.repositories import UserRepo, WidgetRepo
from app.schemas import WidgetCreate
from app.services.auth import AuthService
from app.services.widgets import WidgetService

DEMO_EMAIL, DEMO_PASSWORD, DEMO_WIDGET_ID = "demo@example.com", "demo-password-123", "demo-widget"


def main() -> None:
    s = Settings.from_env()
    engine = make_engine(s.database_url)
    run_migrations(engine)
    try:
        AuthService(engine).register(DEMO_EMAIL, DEMO_PASSWORD)
        print(f"created demo owner {DEMO_EMAIL}")
    except AppError:
        print(f"demo owner {DEMO_EMAIL} already exists")
    with engine.begin() as conn:
        user = UserRepo.get_by_email(conn, DEMO_EMAIL)
        exists = WidgetRepo.get_public(conn, DEMO_WIDGET_ID)
    if exists:
        print(f"demo widget {DEMO_WIDGET_ID} already exists")
    else:
        WidgetService(engine, s.public_base_url).create(user["id"], WidgetCreate.model_validate({
            "type": "signup_form", "title": "Join our newsletter", "description": "Fresh bread news, weekly.",
            "button_text": "Sign me up",
            "fields": [{"name": "name", "label": "Your name", "required": True},
                       {"name": "email", "label": "Email", "type": "email", "required": True},
                       {"name": "message", "label": "Anything else?", "type": "textarea", "max_length": 500}],
            "options": {"success_message": "You're on the list!"},
        }), widget_id=DEMO_WIDGET_ID)
        print(f"created demo widget {DEMO_WIDGET_ID}")
    print(f"\nEmbed snippet:\n  <script src=\"{s.public_base_url}/widget.js?id={DEMO_WIDGET_ID}\" async></script>")
    print(f"\nDashboard login: POST {s.public_base_url}/auth/login  (email {DEMO_EMAIL}, local demo account)")
    print("Customer site:   http://localhost:5500/  (serve ./demo on another port)")


if __name__ == "__main__":
    main()
