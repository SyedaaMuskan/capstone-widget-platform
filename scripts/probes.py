"""Runs the six acceptance probes against a LIVE server and prints a transcript (paste into EVIDENCE.md).
Needs: GEO_MODE=mock ENABLE_DEBUG=true DEBUG_TOKEN=<token>.
Usage: python -m scripts.probes [BASE_URL] [DEBUG_TOKEN] [CUSTOMER_ORIGIN]
"""
import sys
import time
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else "dev-debug-token"
ORIGIN = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:5500"
DBG = {"X-Debug-Token": TOKEN}
failures = []


def check(label: str, ok: bool) -> None:
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        failures.append(label)


def show(r: httpx.Response, *headers: str) -> None:
    print(f"   -> HTTP {r.status_code}  " + "  ".join(f"{h}: {r.headers[h]}" for h in headers if h in r.headers))
    if r.content and "json" in r.headers.get("content-type", ""):
        print(f"      {r.text[:300]}")


c = httpx.Client(base_url=BASE, timeout=15)
print(f"== Setup: owner + widget on {BASE}")
email = f"probe-{uuid.uuid4().hex[:8]}@example.com"
key = c.post("/auth/register", json={"email": email, "password": "probe-password-1"}).json()["api_key"]
H = {"Authorization": f"Bearer {key}"}
w = c.post("/widgets", headers=H, json={"type": "contact_form", "title": "Probe form", "fields": [
    {"name": "name", "label": "Name", "required": True, "max_length": 50},
    {"name": "email", "label": "Email", "type": "email", "required": True}]}).json()
wid = w["id"]
print("   embed snippet:", w["embed_snippet"])
good = {"widget_id": wid, "data": {"name": "Ada", "email": "ada@example.com"}}
c.put("/debug/faults", headers=DBG, json={"geo_a_down": False, "geo_b_down": False, "email_fail": False})

print("\n== Delivery: cached config, loader, versioned bundle")
r = c.get(f"/widgets/{wid}/config", headers={"Origin": ORIGIN}); show(r, "cache-control", "etag", "access-control-allow-origin")
check("config has Cache-Control max-age + ETag", "max-age" in r.headers["cache-control"] and "etag" in r.headers)
r2 = c.get(f"/widgets/{wid}/config", headers={"If-None-Match": r.headers["etag"]}); show(r2)
check("conditional GET -> 304", r2.status_code == 304)
r = c.get("/widget.js", params={"id": wid}); show(r, "cache-control", "content-type")
bundle_path = r.text.split("/assets/")[1].split("'")[0]
r = c.get("/assets/" + bundle_path); show(r, "cache-control")
check("bundle URL is content-hashed and immutable", "immutable" in r.headers["cache-control"] and "max-age=31536000" in r.headers["cache-control"])

print("\n== CORS preflight from the customer origin")
r = c.options("/submissions", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                                        "Access-Control-Request-Headers": "content-type,idempotency-key"})
show(r, "access-control-allow-origin", "access-control-allow-methods", "access-control-allow-headers")
check("preflight OPTIONS answered with CORS headers", r.status_code == 200 and "access-control-allow-origin" in r.headers)

print("\n== PROBE 1: valid cross-origin submission -> stored, 2xx, visible in dashboard")
r = c.post("/submissions", json=good, headers={"Origin": ORIGIN}); show(r, "access-control-allow-origin")
check("2xx + CORS header", r.status_code == 201 and "access-control-allow-origin" in r.headers)
items = c.get("/dashboard/submissions", headers=H, params={"widget_id": wid}).json()
print("   dashboard:", items["total"], "row(s); first:", items["items"][0]["data"], items["items"][0]["geo"])
check("visible via dashboard API", items["total"] == 1)

print("\n== PROBE 2: malformed + oversized payloads -> clean 4xx JSON, never 500")
r = c.post("/submissions", content=b"{oops", headers={"Content-Type": "application/json"}); show(r)
check("malformed JSON -> 400", r.status_code == 400)
r = c.post("/submissions", json={"widget_id": wid, "data": {"name": "x" * 60, "email": "bad"}}); show(r)
check("invalid fields -> 422 with details", r.status_code == 422 and r.json()["error"]["details"])
r = c.post("/submissions", json={"widget_id": wid, "data": {"name": "A", "email": "a@b.co", "message": "x" * 100_000}}); show(r)
check("oversized -> 413", r.status_code == 413)

print("\n== PROBE 6: honeypot filled like a bot")
r = c.post("/submissions", json={**good, "hp": "http://buy-pills.example"}); show(r)
total = c.get("/dashboard/submissions", headers=H, params={"widget_id": wid}).json()["total"]
check("bot submission dropped (not stored)", r.status_code in (202, 400, 422) and total == 1)

print("\n== PROBE 4: geo fallback chain")
print("   provider A down:")
c.put("/debug/faults", headers=DBG, json={"geo_a_down": True})
r = c.post("/submissions", json=good); show(r)
check("A down -> enriched by provider B", r.status_code == 201 and r.json()["geo_provider"] == "mock-b")
print("   providers A and B down:")
c.put("/debug/faults", headers=DBG, json={"geo_b_down": True})
r = c.post("/submissions", json=good); show(r)
check("both down -> stored anyway, without geo", r.status_code == 201 and r.json()["enriched"] is False)
c.put("/debug/faults", headers=DBG, json={"geo_a_down": False, "geo_b_down": False})

print("\n== PROBE 5: email/webhook side effect throws")
c.put("/debug/faults", headers=DBG, json={"email_fail": True})
before = c.get("/dashboard/submissions", headers=H).json()["total"]
r = c.post("/submissions", json=good); show(r)
after = c.get("/dashboard/submissions", headers=H).json()["total"]
check("submission succeeds and is stored while email fails", r.status_code == 201 and after == before + 1)
print("   waiting for the worker to exhaust its retries (exponential backoff)...")
failed = []
for _ in range(60):  # up to ~30s
    c.post("/debug/run-jobs", headers=DBG)
    failed = c.get("/dashboard/jobs/failed", headers=H).json()["items"]
    if failed:
        break
    time.sleep(0.5)
print("   failed-job alert surface:", failed[:1])
check("permanently failed job is surfaced for alerting", len(failed) >= 1)
c.put("/debug/faults", headers=DBG, json={"email_fail": False})

print("\n== PROBE 3: burst of rapid submissions -> 429s, then normal traffic recovers")
codes = [httpx.post(f"{BASE}/submissions", json=good, headers={"X-Forwarded-For": "203.0.113.7"}).status_code for _ in range(40)]
print("   status codes:", {k: codes.count(k) for k in sorted(set(codes))})
check("429s appear during the burst", 429 in codes)
check("health still OK during/after flood", c.get("/health").status_code == 200)
time.sleep(1.5)
r = c.post("/submissions", json=good); show(r)
check("a normal request right after still succeeds", r.status_code == 201)

print("\n" + ("ALL PROBES PASSED" if not failures else f"FAILED: {failures}"))
sys.exit(1 if failures else 0)
