# BlueKnight MRR Collaboration — CLAUDE.md

## Project Overview
BlueKnight is a market research platform that generates structured reports for companies. This repo adds collaborative editing to those reports: sharing with colleagues, section-level editing with version control, full audit history, revert, and AI-assisted rewriting.

## Stack
- Python 3.12
- FastAPI
- SQLAlchemy 2.0 (async) with asyncpg
- Alembic for migrations
- PostgreSQL
- pytest + pytest-asyncio for tests
- Docker + docker-compose for local dev

## Architecture — Three Layer Split (STRICT)
- routers/ — HTTP only, no SQLAlchemy imports, no business logic
- services/ — business logic only, no HTTP imports, no SQLAlchemy imports
- repository/ — all SQL queries, returns domain objects
- Circular imports between any two layers are strictly forbidden

## Code Style
- Async everywhere — async def on all routes and db calls
- Type hints on all functions, no untyped code
- Clean error responses: {"error": "snake_case_code", "message": "human readable"}
- Timestamps as ISO-8601 UTC in all responses
- Small meaningful commits — no single mega-commit

## Key Engineering Rules
- Optimistic concurrency on section writes — version check must live inside the UPDATE predicate, not application code
- ETag on every section read, If-Match required on every section write
- All LLM calls go through the LLMClient Protocol — no provider-specific code in routes or services
- LLMClient failure must leave zero DB writes
- request_id via ContextVar — set by middleware, passed to LLMClient, present in every log line
- One structured JSON log line per write with request_id, user_id, report_id, section_key, version
- No N+1 queries

## What NOT To Do
- No SQL in routers or services
- No HTTP logic in services or repository
- No sync SQLAlchemy
- No provider-specific LLM code outside llm_client.py
- No features outside scope: no WebSockets, no Redis, no JWT issuance, no cross-org sharing