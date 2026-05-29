from __future__ import annotations


async def test_owner_can_read_report(client, seed):
    r = await client.get(f"/reports/{seed.report_id}", headers=seed.owner.auth)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == seed.report_id
    assert body["company_name"] == "Acme"
    assert body["company_url"] == "https://acme.example.com"
    keys = sorted(s["section_key"] for s in body["sections"])
    assert keys == ["financials", "overview"]
    assert all(s["version"] == 1 for s in body["sections"])


async def test_view_share_can_read_report(client, seed):
    r = await client.get(f"/reports/{seed.report_id}", headers=seed.viewer.auth)
    assert r.status_code == 200
    assert r.json()["id"] == seed.report_id


async def test_get_section_returns_etag(client, seed):
    r = await client.get(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}",
        headers=seed.owner.auth,
    )
    assert r.status_code == 200
    assert r.headers["ETag"] == '"1"'
    body = r.json()
    assert body["section_key"] == "overview"
    assert body["version"] == 1
    assert body["content"] == {"text": "initial overview"}
    assert body["updated_by_user_id"] == seed.owner.id


async def test_get_unknown_section_returns_404(client, seed):
    r = await client.get(
        f"/reports/{seed.report_id}/sections/nonexistent",
        headers=seed.owner.auth,
    )
    assert r.status_code == 404
    assert r.json()["error"] == "section_not_found"


async def test_section_history_empty(client, seed):
    r = await client.get(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}/history",
        headers=seed.owner.auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["edits"] == []
    assert body["next_cursor"] is None
