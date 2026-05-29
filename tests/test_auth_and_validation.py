from __future__ import annotations

from jose import jwt

from app.config import settings


async def test_missing_authorization_returns_401(client, seed):
    r = await client.get(f"/reports/{seed.report_id}")
    assert r.status_code == 401
    assert r.json() == {
        "error": "missing_token",
        "message": "Authorization bearer token required",
    }


async def test_non_bearer_authorization_returns_401(client, seed):
    r = await client.get(
        f"/reports/{seed.report_id}",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_token"


async def test_malformed_jwt_returns_401(client, seed):
    r = await client.get(
        f"/reports/{seed.report_id}",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


async def test_jwt_wrong_signature_returns_401(client, seed):
    bad = jwt.encode(
        {"sub": str(seed.owner.id), "org_id": seed.owner.org_id},
        "wrong-secret",
        algorithm=settings.jwt_algorithm,
    )
    r = await client.get(
        f"/reports/{seed.report_id}",
        headers={"Authorization": f"Bearer {bad}"},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


async def test_jwt_missing_org_id_returns_401(client, seed):
    bad = jwt.encode(
        {"sub": str(seed.owner.id)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    r = await client.get(
        f"/reports/{seed.report_id}",
        headers={"Authorization": f"Bearer {bad}"},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


async def test_patch_section_without_if_match_returns_400(client, seed):
    r = await client.patch(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}",
        headers=seed.editor.auth,
        json={"content": {"text": "new"}},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "if_match_required"


async def test_patch_section_unquoted_if_match_returns_400(client, seed):
    r = await client.patch(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}",
        headers={**seed.editor.auth, "If-Match": "1"},
        json={"content": {"text": "new"}},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_if_match"


async def test_patch_section_non_integer_if_match_returns_400(client, seed):
    r = await client.patch(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}",
        headers={**seed.editor.auth, "If-Match": '"abc"'},
        json={"content": {"text": "new"}},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_if_match"


async def test_create_share_target_user_id_zero_returns_422(client, seed):
    r = await client.post(
        f"/reports/{seed.report_id}/shares",
        headers=seed.owner.auth,
        json={"target_user_id": 0, "permission": "view"},
    )
    assert r.status_code == 422


async def test_ai_rewrite_empty_instruction_returns_422(client, seed, llm_stub):
    r = await client.post(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}/ai-rewrite",
        headers={**seed.editor.auth, "If-Match": '"1"'},
        json={"instruction": ""},
    )
    assert r.status_code == 422
    assert llm_stub.call_count == 0


async def test_outsider_get_report_returns_403(client, seed):
    r = await client.get(
        f"/reports/{seed.report_id}",
        headers=seed.outsider_same_org.auth,
    )
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


async def test_viewer_cannot_patch_section_returns_403(client, seed):
    r = await client.patch(
        f"/reports/{seed.report_id}/sections/{seed.overview_key}",
        headers={**seed.viewer.auth, "If-Match": '"1"'},
        json={"content": {"text": "new"}},
    )
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


async def test_unknown_report_returns_404(client, seed):
    r = await client.get("/reports/999999", headers=seed.owner.auth)
    assert r.status_code == 404
    assert r.json()["error"] == "report_not_found"
