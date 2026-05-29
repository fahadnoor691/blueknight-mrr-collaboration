from __future__ import annotations

from sqlalchemy import select

from app.enums import EditSource
from app.models import ReportSection, ReportSectionEdit


async def test_revert_creates_new_audit_row_without_mutating_old(client, seed, db):
    r = await client.patch(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}",
        headers={**seed.editor.auth, "If-Match": '"1"'},
        json={"content": {"text": "v2 content"}},
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2

    await db.rollback()
    e1 = (
        await db.execute(
            select(ReportSectionEdit).where(
                ReportSectionEdit.report_id == seed.report_id,
                ReportSectionEdit.section_key == seed.overview_key,
            )
        )
    ).scalar_one()
    snapshot = {
        "id": e1.id,
        "version_before": e1.version_before,
        "version_after": e1.version_after,
        "content_before": dict(e1.content_before),
        "content_after": dict(e1.content_after),
        "editor_user_id": e1.editor_user_id,
        "source": e1.source,
        "ts": e1.ts,
    }

    r = await client.post(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}/revert/{e1.id}",
        headers=seed.editor.auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 3
    assert body["content"] == {"text": "initial overview"}

    await db.rollback()

    s = (
        await db.execute(
            select(ReportSection).where(
                ReportSection.report_id == seed.report_id,
                ReportSection.section_key == seed.overview_key,
            )
        )
    ).scalar_one()
    assert s.version == 3
    assert s.content == {"text": "initial overview"}

    e1_after = (
        await db.execute(
            select(ReportSectionEdit).where(ReportSectionEdit.id == snapshot["id"])
        )
    ).scalar_one()
    assert e1_after.version_before == snapshot["version_before"]
    assert e1_after.version_after == snapshot["version_after"]
    assert e1_after.content_before == snapshot["content_before"]
    assert e1_after.content_after == snapshot["content_after"]
    assert e1_after.editor_user_id == snapshot["editor_user_id"]
    assert e1_after.source == snapshot["source"]
    assert e1_after.ts == snapshot["ts"]

    rows = (
        await db.execute(
            select(ReportSectionEdit)
            .where(
                ReportSectionEdit.report_id == seed.report_id,
                ReportSectionEdit.section_key == seed.overview_key,
            )
            .order_by(ReportSectionEdit.id)
        )
    ).scalars().all()
    assert len(rows) == 2
    revert_edit = rows[1]
    assert revert_edit.source == EditSource.revert
    assert revert_edit.version_before == 2
    assert revert_edit.version_after == 3
    assert revert_edit.content_before == {"text": "v2 content"}
    assert revert_edit.content_after == {"text": "initial overview"}
    assert revert_edit.editor_user_id == seed.editor.id


async def test_revert_unknown_edit_returns_404(client, seed, db):
    r = await client.post(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}/revert/999999",
        headers=seed.editor.auth,
    )
    assert r.status_code == 404
    assert r.json()["error"] == "edit_not_found"

    s = (
        await db.execute(
            select(ReportSection).where(
                ReportSection.report_id == seed.report_id,
                ReportSection.section_key == seed.overview_key,
            )
        )
    ).scalar_one()
    assert s.version == 1


async def test_revert_requires_edit_access(client, seed):
    r = await client.post(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}/revert/1",
        headers=seed.viewer.auth,
    )
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"
