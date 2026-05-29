from __future__ import annotations

from sqlalchemy import select, text

from app.enums import EditSource
from app.models import ReportSection, ReportSectionEdit


async def test_patch_section_success(client, seed, db):
    r = await client.patch(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}",
        headers={**seed.editor.auth, "If-Match": '"1"'},
        json={"content": {"text": "edited"}},
    )
    assert r.status_code == 200
    assert r.headers["ETag"] == '"2"'
    body = r.json()
    assert body["version"] == 2
    assert body["content"] == {"text": "edited"}
    assert body["updated_by_user_id"] == seed.editor.id

    s = (
        await db.execute(
            select(ReportSection).where(
                ReportSection.report_id == seed.report_id,
                ReportSection.section_key == seed.overview_key,
            )
        )
    ).scalar_one()
    assert s.version == 2
    assert s.content == {"text": "edited"}
    assert s.updated_by_user_id == seed.editor.id

    edit = (
        await db.execute(
            select(ReportSectionEdit).where(
                ReportSectionEdit.report_id == seed.report_id,
                ReportSectionEdit.section_key == seed.overview_key,
            )
        )
    ).scalar_one()
    assert edit.version_before == 1
    assert edit.version_after == 2
    assert edit.content_before == {"text": "initial overview"}
    assert edit.content_after == {"text": "edited"}
    assert edit.editor_user_id == seed.editor.id
    assert edit.source == EditSource.human


async def test_patch_section_stale_if_match_returns_412(client, seed, db):
    r = await client.patch(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}",
        headers={**seed.editor.auth, "If-Match": '"99"'},
        json={"content": {"text": "edited"}},
    )
    assert r.status_code == 412
    assert r.json()["error"] == "version_mismatch"

    n = (
        await db.execute(
            text(
                "SELECT count(*) FROM report_section_edits "
                "WHERE report_id=:r AND section_key=:k"
            ),
            {"r": seed.report_id, "k": seed.overview_key},
        )
    ).scalar_one()
    assert n == 0



async def test_patch_unknown_section_returns_404(client, seed):
    r = await client.patch(
        f"/reports/{seed.report_id}/sections/nope",
        headers={**seed.editor.auth, "If-Match": '"1"'},
        json={"content": {"text": "x"}},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "section_not_found"


async def test_patch_owner_can_edit_without_share(client, seed):
    r = await client.patch(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}",
        headers={**seed.owner.auth, "If-Match": '"1"'},
        json={"content": {"text": "owner edit"}},
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2
