import time

from tests.conftest import DEBUG, create_widget, good_submission, make_settings, register


def test_valid_submission_visible_in_dashboard(client):
    h = register(client)
    w = create_widget(client, h)
    r = client.post("/submissions", json=good_submission(w["id"]), headers={"Origin": "http://localhost:5500"})
    assert r.status_code == 201 and r.json()["ok"] is True
    items = client.get("/dashboard/submissions", headers=h).json()["items"]
    assert len(items) == 1 and items[0]["data"]["email"] == "ada@example.com"
    assert items[0]["origin"] == "http://localhost:5500" and items[0]["widget_id"] == w["id"]
    stats = client.get("/dashboard/stats", headers=h).json()
    assert stats["total"] == 1 and stats["per_widget"][0]["submissions"] == 1
    assert stats["over_time"][0]["submissions"] == 1 and stats["geo"][0]["country"] == "United States"


def test_malformed_and_invalid_payloads_are_4xx_json_never_500(client):
    w = create_widget(client, register(client))
    hdr = {"Content-Type": "application/json"}
    cases = [
        (dict(content=b"{not json", headers=hdr), 400),
        (dict(content=b"\xff\xfe\x00", headers=hdr), 400),
        (dict(content=b"[]", headers=hdr), 422),
        (dict(content=b"null", headers=hdr), 422),
        (dict(content=b'{"widget_id":"x"}', headers=hdr), 422),
        (dict(content=b"hello", headers={"Content-Type": "text/plain"}), 415),
        (dict(json={"widget_id": "nope-nope", "data": {}}), 404),
        (dict(json=good_submission(w["id"], hp={"nested": 1}, extra_key=1)), 422),
        (dict(json={"widget_id": w["id"], "data": {"name": "A"}}), 422),                                   # missing email
        (dict(json={"widget_id": w["id"], "data": {"name": "A", "email": "not-an-email"}}), 422),
        (dict(json={"widget_id": w["id"], "data": {"name": "A", "email": "a@b.co", "evil": "x"}}), 422),   # unknown field
        (dict(json={"widget_id": w["id"], "data": {"name": "A" * 51, "email": "a@b.co"}}), 422),           # over max_length
        (dict(json={"widget_id": w["id"], "data": {"name": 123, "email": "a@b.co"}}), 422),                # wrong type
        (dict(json={"widget_id": w["id"], "data": {"name": "A\x00", "email": "a@b.co"}}), 422),            # control char
        (dict(json={"widget_id": w["id"], "data": "string"}), 422),
    ]
    for kwargs, expected in cases:
        r = client.post("/submissions", **kwargs)
        assert r.status_code == expected, (kwargs, r.status_code, r.text)
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["error"]["code"] and r.json()["error"]["message"]


def test_oversized_payload_rejected_413(client):
    w = create_widget(client, register(client))
    big = {"widget_id": w["id"], "data": {"name": "A", "email": "a@b.co", "message": "x" * 50_000}}
    r = client.post("/submissions", json=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    # a lying/absent Content-Length is still capped while streaming
    def gen():
        for _ in range(50):
            yield b"x" * 1024
    assert client.post("/submissions", content=gen(), headers={"Content-Type": "application/json"}).status_code == 413


def test_rate_limit_burst_then_recovery(make_client):
    c = make_client(rate_ip_capacity=5, rate_ip_refill_per_sec=20)
    w = create_widget(c, register(c))
    codes = [c.post("/submissions", json=good_submission(w["id"]), headers={"X-Forwarded-For": "9.9.9.9"}).status_code for _ in range(30)]
    assert 201 in codes and 429 in codes
    r = c.post("/submissions", json=good_submission(w["id"]), headers={"X-Forwarded-For": "9.9.9.9"})
    if r.status_code == 429:
        assert int(r.headers["retry-after"]) >= 1 and r.json()["error"]["code"] == "rate_limited"
    # other visitors are unaffected while one IP is flooding, and the service is still healthy
    assert c.post("/submissions", json=good_submission(w["id"]), headers={"X-Forwarded-For": "8.8.4.4"}).status_code == 201
    assert c.get("/health").status_code == 200
    time.sleep(0.4)  # bucket refills: the flooding IP is served again
    assert c.post("/submissions", json=good_submission(w["id"]), headers={"X-Forwarded-For": "9.9.9.9"}).status_code == 201


def test_per_widget_rate_limit(make_client):
    c = make_client(rate_widget_capacity=3, rate_widget_refill_per_sec=0.01)
    h = register(c)
    w1, w2 = create_widget(c, h), create_widget(c, h)
    codes = [c.post("/submissions", json=good_submission(w1["id"]), headers={"X-Forwarded-For": f"1.1.1.{i}"}).status_code for i in range(8)]
    assert codes.count(201) == 3 and codes.count(429) == 5   # many different IPs, still capped per widget
    assert c.post("/submissions", json=good_submission(w2["id"])).status_code == 201


def test_honeypot_blocks_bots(client):
    h = register(client)
    w = create_widget(client, h)
    r = client.post("/submissions", json=good_submission(w["id"], hp="http://spam.example"))
    assert r.status_code == 202 and r.json() == {"ok": True}          # bot is told nothing
    assert client.get("/dashboard/submissions", headers=h).json()["total"] == 0
    assert client.post("/submissions", json=good_submission(w["id"], hp="")).status_code == 201


def test_geo_fallback_chain(client):
    h = register(client)
    w = create_widget(client, h)
    def sub():
        r = client.post("/submissions", json=good_submission(w["id"]))
        assert r.status_code == 201, r.text
        return r.json()
    assert sub()["geo_provider"] == "mock-a"
    assert client.put("/debug/faults", json={"geo_a_down": True}, headers=DEBUG).json()["geo_a_down"] is True
    b = sub()
    assert b["geo_provider"] == "mock-b" and b["enriched"] is True          # A down -> B answers
    client.put("/debug/faults", json={"geo_b_down": True}, headers=DEBUG)
    none = sub()
    assert none["enriched"] is False and none["geo_provider"] is None        # all down -> stored anyway
    rows = client.get("/dashboard/submissions", headers=h).json()
    assert rows["total"] == 3
    assert sorted((i["geo"] or {}).get("provider") or "none" for i in rows["items"]) == ["mock-a", "mock-b", "none"]


def test_debug_endpoints_require_token_and_can_be_disabled(client, make_client):
    assert client.put("/debug/faults", json={"email_fail": True}).status_code == 403
    assert client.put("/debug/faults", json={"email_fail": True}, headers={"X-Debug-Token": "wrong"}).status_code == 403
    off = make_client(enable_debug=False)
    assert off.get("/debug/faults", headers=DEBUG).status_code == 404


def test_email_side_effect_failure_never_breaks_submission(make_client):
    c = make_client()
    h = register(c)
    w = create_widget(c, h)
    c.put("/debug/faults", json={"email_fail": True}, headers=DEBUG)
    r = c.post("/submissions", json=good_submission(w["id"]))
    assert r.status_code == 201                                             # visitor still gets success
    assert c.get("/dashboard/submissions", headers=h).json()["total"] == 1  # ...and the row is stored
    for _ in range(3):                                                      # worker retries, then gives up loudly
        c.post("/debug/run-jobs", headers=DEBUG)
    failed = c.get("/dashboard/jobs/failed", headers=h).json()["items"]
    assert len(failed) == 1 and failed[0]["attempts"] == 3 and "forced by debug fault" in failed[0]["last_error"]
    assert c.sender.outbox == []


def test_email_is_sent_by_background_job_when_healthy(client):
    h = register(client)
    w = create_widget(client, h)
    assert client.post("/submissions", json=good_submission(w["id"])).status_code == 201
    assert client.sender.outbox == []                                       # nothing sent on the request path
    assert client.post("/debug/run-jobs", headers=DEBUG).json()["ran"] == 1
    assert [m["to"] for m in client.sender.outbox] == ["ada@example.com"]
    assert client.post("/debug/run-jobs", headers=DEBUG).json()["ran"] == 0  # done jobs don't run again


def test_job_recovers_after_transient_failure(client):
    h = register(client)
    w = create_widget(client, h)
    client.put("/debug/faults", json={"email_fail": True}, headers=DEBUG)
    client.post("/submissions", json=good_submission(w["id"]))
    client.post("/debug/run-jobs", headers=DEBUG)                           # attempt 1 fails
    client.put("/debug/faults", json={"email_fail": False}, headers=DEBUG)
    client.post("/debug/run-jobs", headers=DEBUG)                           # attempt 2 succeeds
    assert len(client.sender.outbox) == 1
    assert client.get("/dashboard/jobs/failed", headers=h).json()["items"] == []


def test_idempotency_key_makes_retries_safe(client):
    h = register(client)
    w = create_widget(client, h)
    hdr = {"Idempotency-Key": "retry-key-12345"}
    first = client.post("/submissions", json=good_submission(w["id"]), headers=hdr)
    second = client.post("/submissions", json=good_submission(w["id"]), headers=hdr)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["duplicate"] is True and second.json()["id"] == first.json()["id"]
    assert client.get("/dashboard/submissions", headers=h).json()["total"] == 1
    assert client.post("/debug/run-jobs", headers=DEBUG).json()["ran"] == 1   # one email, not two
    assert len(client.sender.outbox) == 1


def test_unexpected_errors_are_json_500_without_stack_trace(client):
    @client.app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")
    from fastapi.testclient import TestClient
    r = TestClient(client.app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"
    assert "secret" not in r.text


def test_rate_limiter_unit():
    from app.ratelimit import TokenBucketLimiter
    t = [0.0]
    lim = TokenBucketLimiter(2, 1, clock=lambda: t[0])
    assert lim.allow("k")[0] and lim.allow("k")[0]
    ok, retry = lim.allow("k")
    assert not ok and retry >= 1
    assert lim.allow("other")[0]
    t[0] += 1.0
    assert lim.allow("k")[0]
