from __future__ import annotations

import asyncio

from sqlalchemy import text


async def test_two_concurrent_patches_one_412(client, seed, db):
    headers = {**seed.editor.auth, "If-Match": '"1"'}
    path = f"/reports/{seed.report_id}/sections/{seed.overview_key}"

    r1, r2 = await asyncio.gather(
        client.patch(path, headers=headers, json={"content": {"text": "A"}}),
        client.patch(path, headers=headers, json={"content": {"text": "B"}}),
    )
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 412], f"got {statuses}; race produced two winners"

    winner = r1 if r1.status_code == 200 else r2
    loser = r2 if r1.status_code == 200 else r1
    assert winner.json()["version"] == 2
    assert winner.headers["ETag"] == '"2"'
    assert loser.json()["error"] == "version_mismatch"

    n = (
        await db.execute(
            text(
                "SELECT count(*) FROM report_section_edits "
                "WHERE report_id=:r AND section_key=:k"
            ),
            {"r": seed.report_id, "k": seed.overview_key},
        )
    ).scalar_one()
    assert n == 1


async def test_sequential_same_if_match_one_412(client, seed):
    headers = {**seed.editor.auth, "If-Match": '"1"'}
    path = f"/reports/{seed.report_id}/sections/{seed.overview_key}"

    r1 = await client.patch(path, headers=headers, json={"content": {"text": "A"}})
    assert r1.status_code == 200
    assert r1.json()["version"] == 2

    r2 = await client.patch(path, headers=headers, json={"content": {"text": "B"}})
    assert r2.status_code == 412
    assert r2.json()["error"] == "version_mismatch"
