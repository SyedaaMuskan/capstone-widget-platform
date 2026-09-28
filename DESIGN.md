# Design doc (Phase 1 gate)

**Problem.** Let a customer create an embeddable widget (signup / contact form, CTA popover), install it with one `<script>` line on any site, and safely receive submissions from the open internet: validated, abuse-protected, geo-enriched, stored, and visible in a dashboard.

**Three request paths (kept separate in code):**
1. *Owner* (authenticated): widget CRUD, snippet, dashboard.
2. *Customer site* (public, cached, CORS): `widget.js` loader → versioned bundle → `/widgets/{id}/config`.
3. *Visitor* (public, CORS, protected): `POST /submissions`.

**Data model.** `users` 1─* `api_keys` (hash only) · `users` 1─* `widgets` (`tenant_id`, `fields_json`, `options_json`, `version`) · `widgets` 1─* `submissions` (`tenant_id` copied onto each row, geo columns, `idempotency_key`, `created_date`) · `jobs` (outbox: `status`, `attempts`, `next_run_at`, `last_error`).
Indexes: `widgets(tenant_id)`, `submissions(tenant_id, created_at)`, `submissions(widget_id, created_at)`, `submissions(tenant_id, created_date)`, unique `submissions(widget_id, idempotency_key)`, `jobs(status, next_run_at)`.
Tenant isolation: every owner query takes `tenant_id` explicitly (`WHERE id=:id AND tenant_id=:t`); foreign ids return 404.

**Submission pipeline (cheap checks first):** per-IP bucket → size cap → JSON/schema → per-widget bucket → honeypot → validate against the widget's own field definitions → idempotency lookup → geo chain (never raises) → insert → enqueue email job (failure swallowed and logged).

**Caching.** Loader 5 min; bundle URL contains a content hash so it is `immutable` for a year; config 60 s with `ETag = widget id + version`, and the version increments on each edit.

**Layers.** `api` (HTTP only) → `services` (logic) → `repositories` (SQL) → `migrations`. Composition root: `container.py`.

**API contracts.** See README table. One error envelope for every failure.

**Explicit non-goal.** No real CDN, hosting, custom domains or form-builder UI: the "customer site" is a static HTML file on a second local port, the widget UI is deliberately minimal, and email is a console log (or Mailpit).
