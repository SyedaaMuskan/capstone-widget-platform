import dataclasses
import itertools

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.notifications import MemoryEmailSender

DEBUG = {"X-Debug-Token": "test-token"}
_counter = itertools.count()


def make_settings(tmp_path, **overrides) -> Settings:
    base = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db", geo_mode="mock", worker_enabled=False, enable_debug=True,
        debug_token="test-token", trust_proxy=True, rate_ip_capacity=1000, rate_ip_refill_per_sec=1000,
        rate_widget_capacity=1000, rate_widget_refill_per_sec=1000, job_backoff_base_seconds=0.0, job_max_attempts=3,
    )
    return dataclasses.replace(base, **overrides)


@pytest.fixture
def make_client(tmp_path):
    clients = []

    def _make(**overrides):
        sender = MemoryEmailSender()
        client = TestClient(create_app(make_settings(tmp_path, **overrides), email_sender=sender))
        client.__enter__()
        clients.append(client)
        client.sender = sender
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def register(client, email=None):
    email = email or f"owner{next(_counter)}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "correct-horse-battery"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['api_key']}"}


WIDGET = {
    "type": "contact_form", "title": "Contact us", "button_text": "Send",
    "fields": [
        {"name": "name", "label": "Name", "required": True, "max_length": 50},
        {"name": "email", "label": "Email", "type": "email", "required": True},
        {"name": "message", "label": "Message", "type": "textarea", "max_length": 200},
    ],
}


def create_widget(client, headers, **over):
    r = client.post("/widgets", json={**WIDGET, **over}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def good_submission(widget_id, **extra):
    return {"widget_id": widget_id, "data": {"name": "Ada", "email": "ada@example.com", "message": "hi"}, **extra}
