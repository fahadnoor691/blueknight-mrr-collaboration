# BlueKnight MRR Collaboration

Backend API for collaborative editing of market research reports — sharing, section-level versioning, full audit history, revert, and AI-assisted rewriting.

FastAPI · SQLAlchemy 2.0 (async) · asyncpg · Alembic · PostgreSQL · Python 3.12.

---

## Setup

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                # adjust DATABASE_URL / JWT_SECRET if needed
docker-compose up -d postgres       # local Postgres on :5432
alembic upgrade head                # creates base schema + the three feature tables
python -m app.seed                  # 6 users across 2 orgs + 1 seeded report
```

## Running the app

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` for the generated OpenAPI explorer.

All endpoints expect `Authorization: Bearer <jwt>`. The JWT carries `sub` (user id) and `org_id`. Issuance is out of scope; mint tokens with the same `JWT_SECRET` for local exploration.

## Running tests

```bash
pytest
```

Tests run against the real Postgres from `docker-compose`, apply migrations per session, and truncate between cases. No mocks for the DB; the LLM is stubbed via `InMemoryLLMClient` (uppercases the last user message, supports injected failure).

---

## Schema overview

Three new tables under [app/models.py](app/models.py); migration in `alembic/versions/06ce2c7c131b_add_feature_tables.py`.

### `report_sections`
The current state of each section. One row per `(report_id, section_key)`. Carries `content` (JSONB), `version` (int, monotonic), `updated_at`, `updated_by_user_id`. Unique constraint on `(report_id, section_key)`. Cascade-deletes with the parent report.

### `report_section_edits`
Append-only audit log. One row per write — human PATCH, AI rewrite, or revert. Records `version_before`/`version_after`, `content_before`/`content_after` (both JSONB), `editor_user_id`, `source` (`edit_source` enum: `human` | `ai_rewrite` | `revert`), `ts`. Composite index `report_section_edits_history_idx` on `(report_id, section_key, ts DESC)` powers the paginated history endpoint.

### `report_shares`
Who has access to which report. `target_user_id`, `granted_by_user_id`, `permission` (`share_permission` enum: `view` | `edit`), `created_at`, `revoked_at`. Partial unique index `report_shares_active_uniq` on `(report_id, target_user_id) WHERE revoked_at IS NULL` — guarantees at most one active share per `(report, user)` pair at the database level, so duplicate-creation races resolve cleanly to 409.

---

## Design Notes

### Auth

Bearer JWTs decoded by `python-jose` in [app/dependencies.py](app/dependencies.py) yield a `CurrentUser(user_id, org_id)`. JWT issuance (login, refresh) is out of scope. Access enforcement lives at the **router boundary** via FastAPI `Depends`: `require_view_access` for reads, `require_edit_access` for writes, owner-only check in the shares service. Each access dep runs before the handler body, calls `repository` directly for the lookup, and returns a verified `ReportMeta` "proof-of-access token" that services accept by parameter — services don't re-check, and they also can't be invoked without the dep producing the object. Cross-org sharing is rejected at the create boundary (target user's `org_id` must match the actor's). The access deps live in the router files because they're HTTP infrastructure, but they touch zero SQLAlchemy types directly — `repository` remains the only layer that imports `sqlalchemy`.

### Concurrency

Section writes use optimistic concurrency: clients send `If-Match: "<version>"`, and the server runs an UPDATE with `version = :expected_version` in the WHERE clause — the predicate is the source of truth, never application code. The PATCH and AI-rewrite write paths use a single-statement CTE in [app/repository/sections.py](app/repository/sections.py) that combines the UPDATE, the audit-row INSERT, and the prior-content SELECT. The audit row's existence is structurally tied to the UPDATE's success via a CROSS JOIN — torn states are impossible. PostgreSQL's row-level tuple lock plus EvalPlanQual re-evaluation under READ COMMITTED ensures that when two writers race at the same expected version, the loser's UPDATE finds zero rows after re-reading and 412s cleanly. Revert deliberately skips `If-Match` per spec; to keep audit `content_before` truthful under concurrent reverts, its CTE uses `SELECT ... FOR UPDATE` on the prior row so the loser blocks until the winner commits, then reads post-commit state. AI rewrite commits its read transaction *before* the LLM call so the request never holds idle-in-transaction during multi-second provider round-trips, and the LLM call sits outside any DB transaction — failure leaves zero writes structurally, not by convention.

### Audit log

Every section write — human, AI rewrite, revert — appends one row to `report_section_edits` recording the before/after version, the before/after content, the editor, the source, and the timestamp. Historical rows are never mutated or deleted; revert reads `content_before` from a target edit row and writes a *new* audit row with `source='revert'`. The history endpoint walks the `(report_id, section_key, ts DESC)` index using a `(ts, id)` tuple cursor — `id` as the tiebreak because `func.now()` returns transaction-start time, so multiple edits in the same transaction (AI batches, future backfills) genuinely share `ts`. Each write also emits one structured JSON log line carrying `request_id` (from the middleware ContextVar), `user_id`, `report_id`, `section_key`, `version_before`/`version_after`, `operation`, and `source`. Reads emit nothing.

---

## Intentionally cut for time

- **JWT issuance** — no login / refresh endpoints; tokens must be minted out-of-band against `JWT_SECRET`.
- **Real LLM provider** — `InMemoryLLMClient` is the only implementation. Switching to Anthropic/OpenAI is a single-file change plus `Settings` additions.
- **Shares access dep** — `routers/shares.py` still goes through `services/shares.py._assert_owner` rather than a `require_owner_access` dep. The sections side was refactored to deps; shares wasn't, to keep the diff bounded.
- **Backfill for legacy JSONB sections** — `MarketResearchReport.sections` (the JSONB column) is not migrated into `report_sections` rows. Seeded reports therefore return `"sections": []` from `GET /reports/{id}` until written to.
- **Section creation endpoint** — PATCH on a missing `(report_id, section_key)` returns 404 rather than auto-creating.
- **Bounds on AI rewrite `instruction`** — `min_length=1` only; no `max_length` ceiling.
- **Observability** — logs go to stdlib `logging` only; no JSON aggregator config, no metrics, no tracing.
- **Rate limiting** — no per-user / per-org caps on AI rewrite (cost guard would matter with a real provider).

## What I would do next

1. **Wire a real LLM provider** behind the existing `LLMClient` Protocol — `app/llm_client.py` already declares the surface; add `AnthropicLLMClient` + config in `Settings`, swap the `get_llm_client` dep's default.
2. **Section creation endpoint** — `PUT /reports/{report_id}/sections/{section_key}` for first-write semantics. Reuse the write CTE with an `ON CONFLICT DO NOTHING` path or a separate INSERT-only function.
3. **Shares access dep** — finish the router-boundary refactor for shares (one new dep + ~25 lines deleted from the service).
4. **Backfill migration** — one-time script that materializes legacy JSONB `sections` into `report_sections` rows at version 1, with a synthetic initial audit row per section.
5. **Rate limit AI rewrite** — token-bucket per user (or per org), surfaced as 429 before the LLM call.
6. **Observability** — JSON log formatter wired into stdlib logging, request-scoped trace IDs honored across the LLM call, basic Prometheus counters for write rate and LLM error rate.
7. **Settings hardening** — minimum JWT secret length, allowed JWT algorithms, mandatory `JWT_SECRET` from env (not the `.env` default).
