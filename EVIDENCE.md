# EVIDENCE

One proof per Requirements checkbox (Section 6). Everything below is **real output** captured while building this repo:

* `pytest -v` — 24 deterministic tests (SQLite, mock geo, in-memory email; no network).
* `python -m scripts.probes` — the six acceptance probes run over real HTTP against a live `uvicorn` server, with the "customer site" served from a second origin (`http://localhost:5500` vs API `http://localhost:8000`). Captured against **PostgreSQL 16** (17/17 checks passed; the same script also passed on SQLite).
* A jsdom run that loaded `http://localhost:5500/index.html`, executed the one-line embed, rendered the widget, and submitted it (see Widget delivery).

Reproduce: `docker compose up --build -d && docker compose run --rm api python -m scripts.seed && python -m scripts.probes` and `pytest -q`.

## Widget management
- [x] **Authenticated CRUD; requests without valid auth are rejected.**
  Tests: `test_requires_auth`, `test_crud_and_snippet`, `test_widget_validation`
```
tests/test_widgets_and_tenancy.py::test_requires_auth PASSED
tests/test_widgets_and_tenancy.py::test_crud_and_snippet PASSED
tests/test_widgets_and_tenancy.py::test_widget_validation PASSED
tests/test_widgets_and_tenancy.py::test_login_roundtrip PASSED
```
- [x] **Multi-tenant isolation (tenant A cannot read/modify tenant B's widgets or submissions).**
  `test_tenant_isolation` asserts 404 on GET/PATCH/DELETE/snippet, empty lists, and 404 on dashboard/stats filtered by another tenant's widget id.
```
tests/test_widgets_and_tenancy.py::test_tenant_isolation PASSED
```

## Widget delivery
- [x] **Embed snippet generated per widget.**
```
   embed snippet: <script src="http://localhost:8000/widget.js?id=5039f0f3fb" async></script>
tests/test_widgets_and_tenancy.py::test_crud_and_snippet PASSED
```
- [x] **Public config: small payload + correct cache headers.**  (`test_config_is_small_public_and_cacheable`: payload < 2 KB, no internal fields)
```
== Delivery: cached config, loader, versioned bundle
   -> HTTP 200  cache-control: public, max-age=60  etag: W/"5039f0f3fb-v1"  access-control-allow-origin: *
      {"id":"5039f0f3fb","version":1,"type":"contact_form","title":"Probe form","description":"","button_text":"Submit","fields":[{"name":"name","label":"Name","type":"text","required":true,"max_length":50},{"name":"email","label":"Email","type":"email","required":true,"max_length":500}],"options":{"theme
   [PASS] config has Cache-Control max-age + ETag
   -> HTTP 304  
   [PASS] conditional GET -> 304
   -> HTTP 200  cache-control: public, max-age=300  content-type: application/javascript
   -> HTTP 200  cache-control: public, max-age=31536000, immutable
   [PASS] bundle URL is content-hashed and immutable
tests/test_delivery_and_cors.py::test_config_is_small_public_and_cacheable PASSED
tests/test_delivery_and_cors.py::test_edit_busts_config_etag PASSED
```
- [x] **Versioned bundle** — URL contains a content hash (`/assets/widget.<hash>.js`), served `public, max-age=31536000, immutable`; the loader (`/widget.js?id=`) is a tiny separate file cached for 5 minutes. `test_loader_and_versioned_bundle` also checks an unknown hash → 404.
- [x] **Widget renders on a page served from a different origin.** jsdom loaded `http://localhost:5500/index.html` (API on :8000), ran the single `<script>` embed, and submitted the form:
```
widget rendered: true | title: Join our newsletter
mounted inside #flyrank-widget: true
fields: name, email, message, hp
status message after submit: "You're on the list!"
```
  (jsdom does not enforce CORS; real CORS behaviour is proven by the preflight transcript below. A manual check in a real browser is described in README → "Run it".)

## Public submission API
- [x] **Cross-origin submissions work: CORS headers + preflight handled.**
```
== CORS preflight from the customer origin
   -> HTTP 200  access-control-allow-origin: *  access-control-allow-methods: GET, POST, PATCH, DELETE, OPTIONS  access-control-allow-headers: Accept, Accept-Language, Authorization, Content-Language, Content-Type, Idempotency-Key, If-None-Match
   [PASS] preflight OPTIONS answered with CORS headers
```
```
tests/test_delivery_and_cors.py::test_cors_preflight_and_actual_request PASSED
```
- [x] **PROBE 1 — valid submission from the second origin → stored, 2xx, visible via dashboard.**
```
== PROBE 1: valid cross-origin submission -> stored, 2xx, visible in dashboard
   -> HTTP 201  access-control-allow-origin: *
      {"ok":true,"id":"bf1494fcec5c4408b725a7e34bd11dd7","enriched":true,"geo_provider":"mock-a"}
   [PASS] 2xx + CORS header
   dashboard: 1 row(s); first: {'name': 'Ada', 'email': 'ada@example.com'} {'country': 'United States', 'country_code': 'US', 'region': 'Mock Region', 'city': 'Austin', 'provider': 'mock-a'}
   [PASS] visible via dashboard API
tests/test_submission_pipeline.py::test_valid_submission_visible_in_dashboard PASSED
```
- [x] **PROBE 2 — malformed and oversized payloads → clean 4xx JSON, never 500.**
```
== PROBE 2: malformed + oversized payloads -> clean 4xx JSON, never 500
   -> HTTP 400  
      {"error":{"code":"invalid_json","message":"Request body is not valid JSON"}}
   [PASS] malformed JSON -> 400
   -> HTTP 422  
      {"error":{"code":"validation_error","message":"Submission validation failed","details":[{"field":"name","message":"must be at most 50 characters"},{"field":"email","message":"must be a valid email address"}]}}
   [PASS] invalid fields -> 422 with details
   -> HTTP 413  
      {"error":{"code":"payload_too_large","message":"Request body must be at most 10240 bytes"}}
   [PASS] oversized -> 413
tests/test_submission_pipeline.py::test_malformed_and_invalid_payloads_are_4xx_json_never_500 PASSED
tests/test_submission_pipeline.py::test_oversized_payload_rejected_413 PASSED
tests/test_submission_pipeline.py::test_unexpected_errors_are_json_500_without_stack_trace PASSED
```
  The malformed-payload test runs 15 hostile inputs (bad JSON, invalid UTF-8, `[]`, `null`, wrong types, unknown fields, control characters, wrong Content-Type, unknown widget …) and asserts a JSON `error` body each time.
- [x] **Valid submissions stored safely, linked to the right widget and tenant.** Shown above (`widget_id` in the dashboard row) and by `test_tenant_isolation` (submission appears only for the owning tenant). Rows carry both `widget_id` and `tenant_id`.

## Abuse protection
- [x] **PROBE 3 — burst → 429s, and a normal request right after still succeeds.**
```
== PROBE 3: burst of rapid submissions -> 429s, then normal traffic recovers
   status codes: {201: 11, 429: 29}
   [PASS] 429s appear during the burst
   [PASS] health still OK during/after flood
   -> HTTP 201  
      {"ok":true,"id":"e28749c37113435f8db391ed10c40af6","enriched":true,"geo_provider":"mock-a"}
   [PASS] a normal request right after still succeeds
tests/test_submission_pipeline.py::test_rate_limit_burst_then_recovery PASSED
tests/test_submission_pipeline.py::test_per_widget_rate_limit PASSED
tests/test_submission_pipeline.py::test_rate_limiter_unit PASSED
```
- [x] **PROBE 6 — honeypot filled like a bot → dropped, not stored.**
```
== PROBE 6: honeypot filled like a bot
   -> HTTP 202  
      {"ok":true}
   [PASS] bot submission dropped (not stored)
tests/test_submission_pipeline.py::test_honeypot_blocks_bots PASSED
```

## Enrichment & safe side effects
- [x] **PROBE 4 — provider A down → B answers → enriched; both down → stored anyway.**
```
== PROBE 4: geo fallback chain
   provider A down:
   -> HTTP 201  
      {"ok":true,"id":"53e40bdd8f634e888ba7644deea2e07d","enriched":true,"geo_provider":"mock-b"}
   [PASS] A down -> enriched by provider B
   providers A and B down:
   -> HTTP 201  
      {"ok":true,"id":"934d80aee8b242949738c0758b0f1c6c","enriched":false,"geo_provider":null}
   [PASS] both down -> stored anyway, without geo
tests/test_submission_pipeline.py::test_geo_fallback_chain PASSED
tests/test_submission_pipeline.py::test_debug_endpoints_require_token_and_can_be_disabled PASSED
```
- [x] **PROBE 5 — failing email/webhook does not prevent the submission from being stored.** The email is sent by a background job with retries; after the last attempt the failure is logged as `ALERT` and listed at `/dashboard/jobs/failed`.
```
== PROBE 5: email/webhook side effect throws
   -> HTTP 201  
      {"ok":true,"id":"ca47898bbce948baa875682dc6471ed0","enriched":true,"geo_provider":"mock-a"}
   [PASS] submission succeeds and is stored while email fails
   waiting for the worker to exhaust its retries (exponential backoff)...
   failed-job alert surface: [{'id': '0f9eca2a34134f82a7ca1c8fad963f46', 'type': 'send_confirmation', 'attempts': 4, 'max_attempts': 4, 'last_error': 'RuntimeError: email provider unavailable (forced by debug fault)', 'updated_at': '2026-09-28T19:56:59.475283Z'}]
   [PASS] permanently failed job is surfaced for alerting
tests/test_submission_pipeline.py::test_email_side_effect_failure_never_breaks_submission PASSED
tests/test_submission_pipeline.py::test_email_is_sent_by_background_job_when_healthy PASSED
tests/test_submission_pipeline.py::test_job_recovers_after_transient_failure PASSED
```
  Server log lines produced during that probe:
```
ALERT job <id> (send_confirmation) permanently failed after 4 attempts: RuntimeError: email provider unavailable (forced by debug fault)
```

## Shared requirements
- [x] **Idempotency** — retried action happens once (one row, one email): `tests/test_submission_pipeline.py::test_idempotency_key_makes_retries_safe PASSED`
- [x] **Background job with retries + failure alert** — see PROBE 5 and `test_job_recovers_after_transient_failure`.
- [x] **Persistence** — SQL migrations in `migrations/`, indexes listed in `DESIGN.md`; verified on PostgreSQL 16 and SQLite.
- [x] **Secrets clean** — `.env` git-ignored, `.env.example` committed; only hashes of passwords/API keys stored.
- [x] **Layered architecture** — `app/api` → `app/services` → `app/repositories.py`.
- n/a **Cost tracking** — no AI calls are made by this system.

## Documentation
- [x] README with architecture diagram, setup, API docs, limitations · `DESIGN.md` · `capstone.yaml` · `BUILDLOG.md` · `.env.example`

## Full test run
```
tests/test_delivery_and_cors.py::test_config_is_small_public_and_cacheable PASSED
tests/test_delivery_and_cors.py::test_edit_busts_config_etag PASSED
tests/test_delivery_and_cors.py::test_unknown_widget_config_404 PASSED
tests/test_delivery_and_cors.py::test_loader_and_versioned_bundle PASSED
tests/test_delivery_and_cors.py::test_cors_preflight_and_actual_request PASSED
tests/test_submission_pipeline.py::test_valid_submission_visible_in_dashboard PASSED
tests/test_submission_pipeline.py::test_malformed_and_invalid_payloads_are_4xx_json_never_500 PASSED
tests/test_submission_pipeline.py::test_oversized_payload_rejected_413 PASSED
tests/test_submission_pipeline.py::test_rate_limit_burst_then_recovery PASSED
tests/test_submission_pipeline.py::test_per_widget_rate_limit PASSED
tests/test_submission_pipeline.py::test_honeypot_blocks_bots PASSED
tests/test_submission_pipeline.py::test_geo_fallback_chain PASSED
tests/test_submission_pipeline.py::test_debug_endpoints_require_token_and_can_be_disabled PASSED
tests/test_submission_pipeline.py::test_email_side_effect_failure_never_breaks_submission PASSED
tests/test_submission_pipeline.py::test_email_is_sent_by_background_job_when_healthy PASSED
tests/test_submission_pipeline.py::test_job_recovers_after_transient_failure PASSED
tests/test_submission_pipeline.py::test_idempotency_key_makes_retries_safe PASSED
tests/test_submission_pipeline.py::test_unexpected_errors_are_json_500_without_stack_trace PASSED
tests/test_submission_pipeline.py::test_rate_limiter_unit PASSED
tests/test_widgets_and_tenancy.py::test_requires_auth PASSED
tests/test_widgets_and_tenancy.py::test_crud_and_snippet PASSED
tests/test_widgets_and_tenancy.py::test_widget_validation PASSED
tests/test_widgets_and_tenancy.py::test_tenant_isolation PASSED
tests/test_widgets_and_tenancy.py::test_login_roundtrip PASSED
======================== 24 passed, 1 warning in 1.89s =========================
```
