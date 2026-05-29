---
description: Review staged changes against project requirements and engineering standards
---

You are a senior backend engineer reviewing staged changes for this repository.

## Steps

1. **Fetch staged changes**
   - `git diff --staged`
   - `git status`

2. **Review against CLAUDE.md rules**
   - Three layer split honored — no SQL in routers/services, no HTTP in repository
   - No circular imports between any two layers
   - Async everywhere, no sync SQLAlchemy
   - Type hints on all functions, no untyped code
   - Clean error responses: {"error": "snake_case_code", "message": "human readable"}
   - Timestamps as ISO-8601 UTC in all responses

3. **Review against engineering rules**
   - Optimistic concurrency: version check must be inside the UPDATE predicate, not in application code
   - ETag present on every section read response
   - If-Match required on every section write — missing header returns 400
   - LLMClient Protocol used for all LLM calls — no provider-specific code in routes or services
   - LLMClient failure leaves zero DB writes — check transaction boundaries
   - request_id set by middleware via ContextVar, passed to LLMClient.call(), present in every log line
   - One structured JSON log line per write with request_id, user_id, report_id, section_key, version
   - No N+1 queries — single query for sections, single query for shares on GET /reports/{report_id}

4. **Review against API contract**
   - Correct status codes: 400 missing If-Match, 401 unauthenticated, 403 no access or cross-org, 404 not found, 409 duplicate share, 412 version mismatch, 502 LLMClient failure
   - Access model enforced at router boundary: owner only for shares CRUD, owner or editor for writes/revert/ai-rewrite, any access for reads
   - Shares are within same org only — cross-org returns 403
   - DELETE share is idempotent — 204 both times, only first call sets revoked_at
   - Revert writes a new edit row with source='revert', never mutates or deletes historical rows
   - History endpoint uses cursor pagination with ?limit=&cursor=
   - AI rewrite calls LLMClient before opening write transaction — on exception return 502 with zero DB writes

5. **Review against schema rules**
   - Partial unique index on report_shares (report_id, target_user_id) WHERE revoked_at IS NULL
   - report_section_edits_history_idx on (report_id, section_key, ts DESC)
   - edit_source enum values: human, ai_rewrite, revert
   - share_permission enum values: view, edit
   - Migration is idempotent — running twice must not throw or duplicate rows
   - Downgrade drops all three tables cleanly

6. **Review tests**
   - Tests use real PostgreSQL, not mocks
   - Concurrent write scenario covered — two PATCHes on same version, one must 412
   - LLMClient failure scenario covered — 502 returned, zero rows written
   - Idempotent DELETE covered — 204 twice
   - Revert does not mutate historical rows

7. **Report findings**
   Group by severity, skip empty sections.

   ```
   ### Blocking
   - file.py:LN — what is wrong · why it matters · suggested fix

   ### Should Fix
   - ...

   ### Nits
   - ...

   ### Looks Good
   - what was done well
   ```

   Cite file:line for every finding. Be specific about the fix.

8. **Do not modify any files.** This is a read-only review.