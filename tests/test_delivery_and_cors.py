import re

from tests.conftest import create_widget, good_submission, register

ORIGIN = "http://localhost:5500"


def test_config_is_small_public_and_cacheable(client):
    w = create_widget(client, register(client))
    r = client.get(f"/widgets/{w['id']}/config")
    assert r.status_code == 200
    assert "max-age=60" in r.headers["cache-control"] and "public" in r.headers["cache-control"]
    assert len(r.content) < 2000
    assert "tenant_id" not in r.text and "created_at" not in r.text  # nothing internal leaks
    again = client.get(f"/widgets/{w['id']}/config", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    client.patch(f"/widgets/{w['id']}", json={"title": "Changed"}, headers=register(client))  # other tenant: no effect
    assert client.get(f"/widgets/{w['id']}/config", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_edit_busts_config_etag(client):
    h = register(client)
    w = create_widget(client, h)
    etag = client.get(f"/widgets/{w['id']}/config").headers["etag"]
    client.patch(f"/widgets/{w['id']}", json={"title": "Changed"}, headers=h)
    r = client.get(f"/widgets/{w['id']}/config", headers={"If-None-Match": etag})
    assert r.status_code == 200 and r.json()["title"] == "Changed" and r.headers["etag"] != etag


def test_unknown_widget_config_404(client):
    r = client.get("/widgets/doesnotexist/config")
    assert r.status_code == 404 and r.json()["error"]["code"] == "widget_not_found"


def test_loader_and_versioned_bundle(client):
    loader = client.get("/widget.js", params={"id": "abc123"})
    assert loader.status_code == 200 and "javascript" in loader.headers["content-type"]
    assert "max-age=300" in loader.headers["cache-control"]
    url = re.search(r"/assets/widget\.([0-9a-f]{10})\.js", loader.text)
    assert url, "loader must point at the content-hashed bundle"
    bundle = client.get(url.group(0))
    assert bundle.status_code == 200
    assert "max-age=31536000" in bundle.headers["cache-control"] and "immutable" in bundle.headers["cache-control"]
    assert client.get("/assets/widget.0000000000.js").status_code == 404
    assert client.get("/widget.js", params={"id": "bad id!"}).status_code == 400


def test_cors_preflight_and_actual_request(client):
    w = create_widget(client, register(client))
    pre = client.options("/submissions", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,idempotency-key"})
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == "*"
    assert "POST" in pre.headers["access-control-allow-methods"]
    assert "idempotency-key" in pre.headers["access-control-allow-headers"].lower()
    r = client.post("/submissions", json=good_submission(w["id"]), headers={"Origin": ORIGIN})
    assert r.status_code == 201 and r.headers["access-control-allow-origin"] == "*"
    cfg = client.get(f"/widgets/{w['id']}/config", headers={"Origin": ORIGIN})
    assert cfg.headers["access-control-allow-origin"] == "*"
