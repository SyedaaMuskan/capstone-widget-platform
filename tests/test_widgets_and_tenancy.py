from tests.conftest import WIDGET, create_widget, good_submission, register


def test_requires_auth(client):
    assert client.get("/widgets").status_code == 401
    assert client.post("/widgets", json=WIDGET).status_code == 401
    assert client.get("/widgets", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/dashboard/stats").status_code == 401


def test_crud_and_snippet(client):
    h = register(client)
    w = create_widget(client, h)
    assert w["embed_snippet"] == f'<script src="http://localhost:8000/widget.js?id={w["id"]}" async></script>'
    assert client.get(f"/widgets/{w['id']}/snippet", headers=h).json()["snippet"] == w["embed_snippet"]
    r = client.patch(f"/widgets/{w['id']}", json={"title": "New title"}, headers=h)
    assert r.status_code == 200 and r.json()["title"] == "New title" and r.json()["version"] == 2
    assert len(client.get("/widgets", headers=h).json()["items"]) == 1
    assert client.delete(f"/widgets/{w['id']}", headers=h).status_code == 204
    assert client.get(f"/widgets/{w['id']}", headers=h).status_code == 404


def test_widget_validation(client):
    h = register(client)
    assert client.post("/widgets", json={**WIDGET, "type": "banana"}, headers=h).status_code == 422
    dup = [{"name": "a", "label": "A"}, {"name": "a", "label": "A2"}]
    assert client.post("/widgets", json={**WIDGET, "fields": dup}, headers=h).status_code == 422
    assert client.post("/widgets", json={**WIDGET, "fields": [{"name": "hp", "label": "x"}]}, headers=h).status_code == 422
    assert client.post("/widgets", json={**WIDGET, "evil": 1}, headers=h).status_code == 422


def test_tenant_isolation(client):
    a, b = register(client), register(client)
    wa = create_widget(client, a)
    client.post("/submissions", json=good_submission(wa["id"]))
    # B can't read, edit, delete, snippet or list A's widget (404, not 403: existence isn't revealed)
    assert client.get(f"/widgets/{wa['id']}", headers=b).status_code == 404
    assert client.patch(f"/widgets/{wa['id']}", json={"title": "pwn"}, headers=b).status_code == 404
    assert client.delete(f"/widgets/{wa['id']}", headers=b).status_code == 404
    assert client.get(f"/widgets/{wa['id']}/snippet", headers=b).status_code == 404
    assert client.get("/widgets", headers=b).json()["items"] == []
    # ...nor A's submissions / stats
    assert client.get("/dashboard/submissions", headers=b).json()["total"] == 0
    assert client.get("/dashboard/submissions", params={"widget_id": wa["id"]}, headers=b).status_code == 404
    assert client.get("/dashboard/stats", params={"widget_id": wa["id"]}, headers=b).status_code == 404
    assert client.get("/dashboard/stats", headers=b).json()["total"] == 0
    # A still sees everything
    assert client.get("/dashboard/submissions", headers=a).json()["total"] == 1
    assert client.get(f"/widgets/{wa['id']}", headers=a).json()["title"] == "Contact us"


def test_login_roundtrip(client):
    client.post("/auth/register", json={"email": "Me@Example.com", "password": "correct-horse-battery"})
    assert client.post("/auth/register", json={"email": "me@example.com", "password": "correct-horse-battery"}).status_code == 409
    assert client.post("/auth/login", json={"email": "me@example.com", "password": "wrong-password"}).status_code == 401
    r = client.post("/auth/login", json={"email": "ME@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 200
    assert client.get("/widgets", headers={"Authorization": f"Bearer {r.json()['api_key']}"}).status_code == 200
