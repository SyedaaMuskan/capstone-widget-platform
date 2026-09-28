# flyrank-capstone-widgetplatform

Embeddable **widget & lead-capture platform**: a customer defines a widget, pastes **one `<script>` line** on any website, and the platform safely catches whatever the public internet sends back — validated, rate-limited, spam-filtered, geo-enriched, stored, and shown in an owner dashboard.

Stack: **Python 3.12 · FastAPI · SQLAlchemy Core · PostgreSQL (SQLite for tests) · Docker** — all free, no credit card.

## Architecture

```
 Widget Owner (Bearer API key)                Customer website (any origin)            Website visitor
        |                                              |                                     |
        v                                              v                                     v
 POST/GET/PATCH/DELETE /widgets            <script src=".../widget.js?id=abc">      POST /submissions  (public, CORS)
        |  (tenant-scoped queries)                     |                                     |
        v                                    GET /widget.js  (loader, max-age=300)           |  1. per-IP token bucket -> 429
 +--------------+                                      |                                     |  2. body size cap        -> 413
 |  widgets DB  |<-- GET /widgets/{id}/config ---------+  loads                              |  3. JSON + schema check  -> 400/422
 +--------------+    (public, max-age=60, ETag)        v                                     |  4. per-widget bucket    -> 429
        ^            GET /assets/widget.<hash>.js      renders form, submits ---------------->  5. honeypot           -> silently dropped
        |            (immutable, 1 year)                                                     |  6. field validation vs the widget's schema
        |                                                                                    |  7. idempotency key      -> retry = same row
 Dashboard API  <----------- submissions table <---------------------------------------------  8. geo: provider A -> B -> none (never fails)
 GET /dashboard/submissions                                                                  |  9. INSERT (tenant + widget linked)
 GET /dashboard/stats                                                                        | 10. enqueue email job  (outbox table)
 GET /dashboard/jobs/failed  <---- jobs table <-- background worker: retries + backoff + ALERT log on permanent failure
```

Layers: `app/api/` (HTTP) → `app/services/` (logic) → `app/repositories.py` (SQL) → `migrations/` (schema). Wiring lives in `app/container.py`.

## Run it (one command + seed)

```bash
cp .env.example .env            # optional; compose has safe local defaults
docker compose up --build -d    # Postgres + API (:8000) + customer-site (:5500)
docker compose run --rm api python -m scripts.seed
```

Then open **http://localhost:5500/** — that page is on a *different origin* than the API and contains the one-line embed. Submit the form, then open **http://localhost:5500/dashboard.html** (demo login is pre-filled) to see the row, stats and geo breakdown.

Prove the six behaviours with real HTTP against the running stack:

```bash
pip install httpx && python -m scripts.probes http://localhost:8000 dev-debug-token http://localhost:5500
```

### Without Docker
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
export GEO_MODE=mock ENABLE_DEBUG=true DEBUG_TOKEN=dev-debug-token TRUST_PROXY=true
python -m scripts.seed
uvicorn app.main:create_app --factory --port 8000        # SQLite file dev.db by default
python -m http.server 5500 --directory demo               # second origin
pytest -q                                                 # 24 tests, deterministic, no network
```
Optional local mail catcher: `docker compose --profile mail up -d mailpit` and `EMAIL_BACKEND=smtp` (inbox at :8025). Default is a console "fake email".

## API

| Who | Endpoint | Notes |
|---|---|---|
| owner | `POST /auth/register`, `POST /auth/login` | returns `api_key` → `Authorization: Bearer <key>` |
| owner | `POST/GET /widgets`, `GET/PATCH/DELETE /widgets/{id}` | tenant-isolated; other tenant's id → **404** |
| owner | `GET /widgets/{id}/snippet` | `{"snippet": "<script src=\"…/widget.js?id=…\" async></script>"}` |
| public | `GET /widget.js?id=` | loader, `Cache-Control: public, max-age=300` |
| public | `GET /assets/widget.<hash>.js` | content-hashed bundle, `max-age=31536000, immutable` |
| public | `GET /widgets/{id}/config` | small JSON, `max-age=60`, `ETag`, `304` on `If-None-Match`; edits bump the ETag |
| public | `POST /submissions` | CORS + preflight. Body `{"widget_id","data":{…},"hp":""}`; optional `Idempotency-Key` header |
| owner | `GET /dashboard/submissions?widget_id=&limit=&offset=` | paginated |
| owner | `GET /dashboard/stats?widget_id=&days=` | per-widget totals, counts per day, geo breakdown |
| owner | `GET /dashboard/jobs/failed` | background jobs that exhausted retries (alert surface) |
| ops | `GET/PUT /debug/faults`, `POST /debug/run-jobs` | only when `ENABLE_DEBUG=true`, needs `X-Debug-Token`. Toggles `geo_a_down`, `geo_b_down`, `email_fail` |

Errors always look like `{"error": {"code": "...", "message": "...", "details": [...]}}`.
Status codes: 400 bad JSON · 401 no/invalid key · 404 unknown widget · 413 too big · 415 wrong content type · 422 invalid fields · 429 rate limited (with `Retry-After`) · never 500 for bad input.

## Design decisions worth knowing
- **CORS is `*` without credentials** — safe because auth is a bearer header, not a cookie. Preflight is answered by the middleware.
- **Rate limiting = token bucket** (burst 10, refill 2/s per IP; burst 100, 5/s per widget by default). A flood gets 429s while other visitors and `/health` are unaffected, and the flooder recovers as tokens refill.
- **Spam control = honeypot** hidden input `hp`; bots get a fake `202 {"ok": true}` and nothing is stored.
- **Geo chain**: `ip-api.com` → `ipapi.co` → store without geo. Private/loopback IPs are skipped in live mode. `GEO_MODE=mock` swaps in two deterministic providers you can switch off via `/debug/faults`.
- **Safe side effects**: the submission row is committed first, then an email job is written to a `jobs` table. A worker thread sends it with retries + exponential backoff; after the last attempt it logs `ALERT …` and the job shows up in `/dashboard/jobs/failed`. Email failing can never fail a submission.
- **Idempotency**: a unique index on `(widget_id, idempotency_key)`; the widget script reuses one key per form so retries store once and send one email.
- **Secrets**: environment only (`.env` is git-ignored, `.env.example` committed); API keys and passwords are stored hashed (SHA-256 / scrypt) and never logged.

## Limitations (honest)
- Rate-limit buckets live in process memory: correct for one API instance; multiple instances would need a shared store (e.g. Redis).
- Timestamps are ISO-8601 `TEXT` so the same migrations run on Postgres and SQLite; production Postgres would use `timestamptz`.
- The migration runner is a minimal forward-only SQL runner, not Alembic.
- The job worker runs inside the API process (fine for this scope; a separate worker process is the next step).
- Visitor IPs are stored raw (needed for the geo demo); a real product would need a retention/GDPR policy (stretch goal).
- `docker-compose.yml` enables the debug endpoints and mock geo **by default so the acceptance probes are reproducible** — set `ENABLE_DEBUG=false GEO_MODE=live` for anything public.
- The live geo providers (`ip-api.com`, `ipapi.co`) and the SMTP path are implemented but were not exercised in automated proofs (mocks are used on purpose).

## Repo map
`app/` code · `migrations/` schema · `tests/` pytest · `scripts/seed.py` demo data · `scripts/probes.py` live acceptance probes · `demo/` second-origin customer site + dashboard · `DESIGN.md` · `EVIDENCE.md` · `BUILDLOG.md` · `capstone.yaml`
