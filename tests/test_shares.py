from __future__ import annotations

from sqlalchemy import select

from app.models import ReportShare


async def test_create_share_201(client, seed):
    r = await client.post(
        f"/reports/{seed.report_id}/shares",
        headers=seed.owner.auth,
        json={
            "target_user_id": seed.outsider_same_org.id,
            "permission": "view",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["target_user_id"] == seed.outsider_same_org.id
    assert body["permission"] == "view"
    assert body["granted_by_user_id"] == seed.owner.id
    assert body["report_id"] == seed.report_id


async def test_create_duplicate_share_returns_409(client, seed):
    r = await client.post(
        f"/reports/{seed.report_id}/shares",
        headers=seed.owner.auth,
        json={"target_user_id": seed.editor.id, "permission": "edit"},
    )
    assert r.status_code == 409
    assert r.json()["error"] == "share_already_exists"


async def test_create_share_cross_org_forbidden(client, seed):
    r = await client.post(
        f"/reports/{seed.report_id}/shares",
        headers=seed.owner.auth,
        json={
            "target_user_id": seed.outsider_other_org.id,
            "permission": "view",
        },
    )
    assert r.status_code == 403
    assert r.json()["error"] == "cross_org_share_forbidden"


async def test_create_share_non_owner_forbidden(client, seed):
    r = await client.post(
        f"/reports/{seed.report_id}/shares",
        headers=seed.editor.auth,
        json={
            "target_user_id": seed.outsider_same_org.id,
            "permission": "view",
        },
    )
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


async def test_create_share_target_user_not_found(client, seed):
    r = await client.post(
        f"/reports/{seed.report_id}/shares",
        headers=seed.owner.auth,
        json={"target_user_id": 999999, "permission": "view"},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "target_user_not_found"


async def test_delete_share_idempotent_204_twice(client, seed, db):
    share_id = seed.editor_share_id

    r1 = await client.delete(
        f"/reports/{seed.report_id}/shares/{share_id}",
        headers=seed.owner.auth,
    )
    assert r1.status_code == 204
    assert r1.text == ""

    r2 = await client.delete(
        f"/reports/{seed.report_id}/shares/{share_id}",
        headers=seed.owner.auth,
    )
    assert r2.status_code == 204
    assert r2.text == ""

    await db.rollback()
    rows = (
        await db.execute(select(ReportShare).where(ReportShare.id == share_id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].revoked_at is not None


async def test_delete_unknown_share_returns_404(client, seed):
    r = await client.delete(
        f"/reports/{seed.report_id}/shares/999999",
        headers=seed.owner.auth,
    )
    assert r.status_code == 404
    assert r.json()["error"] == "share_not_found"


async def test_delete_share_non_owner_forbidden(client, seed):
    r = await client.delete(
        f"/reports/{seed.report_id}/shares/{seed.viewer_share_id}",
        headers=seed.editor.auth,
    )
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


async def test_list_shares_returns_active_only(client, seed):
    await client.delete(
        f"/reports/{seed.report_id}/shares/{seed.editor_share_id}",
        headers=seed.owner.auth,
    )

    r = await client.get(
        f"/reports/{seed.report_id}/shares",
        headers=seed.owner.auth,
    )
    assert r.status_code == 200
    shares = r.json()
    assert len(shares) == 1
    assert shares[0]["id"] == seed.viewer_share_id
    assert shares[0]["permission"] == "view"


async def test_list_shares_non_owner_forbidden(client, seed):
    r = await client.get(
        f"/reports/{seed.report_id}/shares",
        headers=seed.editor.auth,
    )
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"
