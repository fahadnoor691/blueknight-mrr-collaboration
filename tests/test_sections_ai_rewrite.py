from __future__ import annotations

from sqlalchemy import select, text

from app.enums import EditSource
from app.models import ReportSection, ReportSectionEdit


async def test_ai_rewrite_happy_path(client, seed, db, llm_stub):
    r = await client.post(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}/ai-rewrite",
        headers={**seed.editor.auth, "If-Match": '"1"'},
        json={"instruction": "make it punchier"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 2
    assert body["content"] == {"text": "MAKE IT PUNCHIER"}
    assert llm_stub.call_count == 1

    edit = (
        await db.execute(
            select(ReportSectionEdit).where(
                ReportSectionEdit.report_id == seed.report_id,
                ReportSectionEdit.section_key == seed.overview_key,
            )
        )
    ).scalar_one()
    assert edit.source == EditSource.ai_rewrite
    assert edit.version_before == 1
    assert edit.version_after == 2


async def test_ai_rewrite_llm_failure_502_zero_writes(client, seed, db, llm_stub):
    s_before = (
        await db.execute(
            select(ReportSection).where(
                ReportSection.report_id == seed.report_id,
                ReportSection.section_key == seed.overview_key,
            )
        )
    ).scalar_one()
    version_before = s_before.version
    content_before = dict(s_before.content)
    edits_before = (
        await db.execute(text("SELECT count(*) FROM report_section_edits"))
    ).scalar_one()

    llm_stub.raise_on_call = RuntimeError("provider exploded")

    r = await client.post(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}/ai-rewrite",
        headers={**seed.editor.auth, "If-Match": '"1"'},
        json={"instruction": "rewrite"},
    )
    assert r.status_code == 502
    assert r.json()["error"] == "llm_call_failed"
    assert llm_stub.call_count == 1

    await db.rollback()

    s_after = (
        await db.execute(
            select(ReportSection).where(
                ReportSection.report_id == seed.report_id,
                ReportSection.section_key == seed.overview_key,
            )
        )
    ).scalar_one()
    assert s_after.version == version_before
    assert s_after.content == content_before

    edits_after = (
        await db.execute(text("SELECT count(*) FROM report_section_edits"))
    ).scalar_one()
    assert edits_after == edits_before


async def test_ai_rewrite_stale_if_match_short_circuits_before_llm(
    client, seed, db, llm_stub
):
    r = await client.post(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}/ai-rewrite",
        headers={**seed.editor.auth, "If-Match": '"99"'},
        json={"instruction": "anything"},
    )
    assert r.status_code == 412
    assert r.json()["error"] == "version_mismatch"
    assert llm_stub.call_count == 0

    n = (
        await db.execute(text("SELECT count(*) FROM report_section_edits"))
    ).scalar_one()
    assert n == 0


async def test_ai_rewrite_unknown_section_returns_404(client, seed, llm_stub):
    r = await client.post(
        f"/reports/{seed.report_id}/sections/nope/ai-rewrite",
        headers={**seed.editor.auth, "If-Match": '"1"'},
        json={"instruction": "anything"},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "section_not_found"
    assert llm_stub.call_count == 0
