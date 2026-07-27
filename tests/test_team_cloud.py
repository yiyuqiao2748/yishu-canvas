import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException, Response

from unittest.mock import AsyncMock, patch

import team_cloud
from team_cloud import AuthPasswordUpdateRequest, CanvasSaveRequest, CurrentUser, LocalTeamStore, TeamApiProviderModelsRequest, TeamApiProviderSaveRequest, current_user_from_supabase_payload


class TeamCloudStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store_path = Path(self.temp.name) / "team_cloud.json"
        self.store = LocalTeamStore(str(self.store_path))
        self.owner = CurrentUser(id="owner-1", email="owner@example.com", provider="test")
        self.outsider = CurrentUser(id="outsider-1", email="outsider@example.com", provider="test")

    def tearDown(self):
        self.temp.cleanup()

    def test_create_team_adds_owner_membership(self):
        team = self.store.create_team(self.owner, "Design Lab")

        self.assertEqual(team["name"], "Design Lab")
        self.assertEqual(team["role"], "owner")
        self.assertEqual(self.store.list_user_teams(self.owner)[0]["id"], team["id"])

        members = self.store.list_members(self.owner, team["id"])
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]["role"], "owner")
        self.assertEqual(members[0]["user_id"], self.owner.id)

    def test_owner_can_invite_member(self):
        team = self.store.create_team(self.owner, "Design Lab")

        invitation = self.store.invite_member(
            self.owner,
            team["id"],
            "New.Member@Example.com",
            "member",
        )

        self.assertEqual(invitation["email"], "new.member@example.com")
        self.assertEqual(invitation["role"], "member")
        self.assertEqual(invitation["status"], "pending")

    def test_outsider_cannot_list_or_invite_members(self):
        team = self.store.create_team(self.owner, "Design Lab")

        with self.assertRaises(HTTPException) as list_error:
            self.store.list_members(self.outsider, team["id"])
        self.assertEqual(list_error.exception.status_code, 403)

        with self.assertRaises(HTTPException) as invite_error:
            self.store.invite_member(self.outsider, team["id"], "person@example.com", "member")
        self.assertEqual(invite_error.exception.status_code, 403)

    def test_project_and_canvas_lifecycle(self):
        team = self.store.create_team(self.owner, "Design Lab")
        project = self.store.create_project(self.owner, team["id"], "Launch Board", "shared work")

        self.assertEqual(project["team_id"], team["id"])
        self.assertEqual(self.store.list_projects(self.owner, team["id"])[0]["name"], "Launch Board")

        canvas = self.store.create_canvas(
            self.owner,
            project["id"],
            "Storyboard",
            {"nodes": [], "connections": []},
        )

        self.assertEqual(canvas["version"], 1)
        self.assertEqual(self.store.list_canvases(self.owner, project["id"])[0]["title"], "Storyboard")
        self.assertEqual(self.store.get_canvas(self.owner, canvas["id"])["data"], {"nodes": [], "connections": []})

        saved = self.store.save_canvas(
            self.owner,
            canvas["id"],
            CanvasSaveRequest(
                title="Storyboard v2",
                data={"nodes": [{"id": "n1"}], "connections": []},
                base_version=1,
            ),
        )

        self.assertEqual(saved["title"], "Storyboard v2")
        self.assertEqual(saved["version"], 2)
        self.assertEqual(saved["data"]["nodes"], [{"id": "n1"}])

    def test_delete_canvas_requires_admin_and_removes_versions(self):
        team = self.store.create_team(self.owner, "Design Lab")
        project = self.store.create_project(self.owner, team["id"], "Launch Board")
        canvas = self.store.create_canvas(self.owner, project["id"], "Storyboard", {})
        member = CurrentUser(id="member-1", email="member@example.com", provider="test")
        data = self.store._read()
        data["members"].append({
            "id": "member-row",
            "team_id": team["id"],
            "user_id": member.id,
            "email": member.email,
            "role": "member",
            "created_at": 1,
        })
        self.store._write(data)

        with self.assertRaises(HTTPException) as member_error:
            self.store.delete_canvas(member, canvas["id"])
        self.assertEqual(member_error.exception.status_code, 403)

        deleted = self.store.delete_canvas(self.owner, canvas["id"])

        self.assertEqual(deleted["canvas"]["id"], canvas["id"])
        self.assertEqual(self.store.list_canvases(self.owner, project["id"]), [])
        stored = self.store._read()
        self.assertEqual([row for row in stored["canvas_versions"] if row.get("canvas_id") == canvas["id"]], [])

    def test_delete_project_requires_admin_and_removes_canvases(self):
        team = self.store.create_team(self.owner, "Design Lab")
        project = self.store.create_project(self.owner, team["id"], "Launch Board")
        canvas = self.store.create_canvas(self.owner, project["id"], "Storyboard", {})

        deleted = self.store.delete_project(self.owner, project["id"])

        self.assertEqual(deleted["project"]["id"], project["id"])
        self.assertEqual(self.store.list_projects(self.owner, team["id"]), [])
        stored = self.store._read()
        self.assertEqual([row for row in stored["canvases"] if row.get("id") == canvas["id"]], [])
        self.assertEqual([row for row in stored["canvas_versions"] if row.get("canvas_id") == canvas["id"]], [])

    def test_delete_team_requires_owner_and_removes_related_records(self):
        team = self.store.create_team(self.owner, "Design Lab")
        project = self.store.create_project(self.owner, team["id"], "Launch Board")
        canvas = self.store.create_canvas(self.owner, project["id"], "Storyboard", {})
        admin = CurrentUser(id="admin-1", email="admin@example.com", provider="test")
        data = self.store._read()
        data["members"].append({
            "id": "admin-row",
            "team_id": team["id"],
            "user_id": admin.id,
            "email": admin.email,
            "role": "admin",
            "created_at": 1,
        })
        self.store._write(data)

        with self.assertRaises(HTTPException) as admin_error:
            self.store.delete_team(admin, team["id"])
        self.assertEqual(admin_error.exception.status_code, 403)

        deleted = self.store.delete_team(self.owner, team["id"])

        self.assertEqual(deleted["team"]["id"], team["id"])
        stored = self.store._read()
        self.assertEqual(stored["teams"], [])
        self.assertEqual(stored["members"], [])
        self.assertEqual([row for row in stored["canvases"] if row.get("id") == canvas["id"]], [])
        self.assertEqual([row for row in stored["canvas_versions"] if row.get("canvas_id") == canvas["id"]], [])

    def test_canvas_save_rejects_stale_version(self):
        team = self.store.create_team(self.owner, "Design Lab")
        project = self.store.create_project(self.owner, team["id"], "Launch Board")
        canvas = self.store.create_canvas(self.owner, project["id"], "Storyboard", {})

        self.store.save_canvas(
            self.owner,
            canvas["id"],
            CanvasSaveRequest(data={"ok": True}, base_version=1),
        )

        with self.assertRaises(HTTPException) as stale_error:
            self.store.save_canvas(
                self.owner,
                canvas["id"],
                CanvasSaveRequest(data={"stale": True}, base_version=1),
            )
        self.assertEqual(stale_error.exception.status_code, 409)

    def test_canvas_versions_can_be_listed_and_restored(self):
        team = self.store.create_team(self.owner, "Design Lab")
        project = self.store.create_project(self.owner, team["id"], "Launch Board")
        canvas = self.store.create_canvas(
            self.owner,
            project["id"],
            "Storyboard",
            {"title": "v1", "nodes": [{"id": "old"}], "connections": []},
        )
        self.store.save_canvas(
            self.owner,
            canvas["id"],
            CanvasSaveRequest(
                title="Storyboard v2",
                data={"title": "v2", "nodes": [{"id": "new"}], "connections": [{"from": "old", "to": "new"}]},
                base_version=1,
            ),
        )

        versions = self.store.list_canvas_versions(self.owner, canvas["id"])
        self.assertEqual([item["version"] for item in versions], [2, 1])
        self.assertEqual(versions[0]["node_count"], 1)
        self.assertEqual(versions[0]["connection_count"], 1)

        restored = self.store.restore_canvas_version(self.owner, canvas["id"], 1)

        self.assertEqual(restored["canvas"]["version"], 3)
        self.assertEqual(restored["canvas"]["data"]["nodes"], [{"id": "old"}])
        self.assertEqual(restored["restored_version"]["version"], 1)
        self.assertEqual([item["version"] for item in self.store.list_canvas_versions(self.owner, canvas["id"])], [3, 2, 1])
        with self.assertRaises(HTTPException) as outsider_error:
            self.store.list_canvas_versions(self.outsider, canvas["id"])
        self.assertEqual(outsider_error.exception.status_code, 403)

    def test_outsider_cannot_access_project_canvases(self):
        team = self.store.create_team(self.owner, "Design Lab")
        project = self.store.create_project(self.owner, team["id"], "Launch Board")

        with self.assertRaises(HTTPException) as project_error:
            self.store.list_canvases(self.outsider, project["id"])
        self.assertEqual(project_error.exception.status_code, 403)

    def test_team_assets_are_member_scoped(self):
        team = self.store.create_team(self.owner, "Design Lab")
        asset = self.store.create_asset(self.owner, team["id"], {
            "name": "sample.png",
            "kind": "image",
            "storage_key": "team-assets/team/sample.png",
            "public_url": "/assets/team-assets/team/sample.png",
            "thumbnail_url": "/assets/team-assets/team/sample-thumb.jpg",
            "mime_type": "image/png",
            "byte_size": 12,
            "width": 640,
            "height": 320,
            "storage_provider": "local",
        })

        self.assertEqual(asset["team_id"], team["id"])
        self.assertEqual(asset["thumbnail_url"], "/assets/team-assets/team/sample-thumb.jpg")
        self.assertEqual(asset["width"], 640)
        self.assertEqual(asset["height"], 320)
        self.assertEqual(self.store.list_assets(self.owner, team["id"])[0]["name"], "sample.png")

        with self.assertRaises(HTTPException) as asset_error:
            self.store.list_assets(self.outsider, team["id"])
        self.assertEqual(asset_error.exception.status_code, 403)

    def test_delete_team_asset_blocks_canvas_references(self):
        team = self.store.create_team(self.owner, "Design Lab")
        project = self.store.create_project(self.owner, team["id"], "Launch Board")
        asset = self.store.create_asset(self.owner, team["id"], {
            "id": "asset-1",
            "name": "sample.png",
            "kind": "image",
            "storage_key": "team-assets/team/sample.png",
            "public_url": "/assets/team-assets/team/sample.png",
            "mime_type": "image/png",
            "byte_size": 12,
            "storage_provider": "local",
        })
        canvas = self.store.create_canvas(
            self.owner,
            project["id"],
            "Storyboard",
            {"nodes": [{"id": "node-1", "images": [{"url": asset["public_url"]}]}]},
        )

        with self.assertRaises(HTTPException) as delete_error:
            self.store.delete_asset(self.owner, team["id"], asset["id"])

        self.assertEqual(delete_error.exception.status_code, 409)
        self.assertEqual(delete_error.exception.detail["references"][0]["id"], canvas["id"])

        self.store.save_canvas(
            self.owner,
            canvas["id"],
            CanvasSaveRequest(data={"nodes": []}, base_version=1),
        )
        deleted = self.store.delete_asset(self.owner, team["id"], asset["id"])

        self.assertEqual(deleted["asset"]["id"], asset["id"])
        self.assertEqual(self.store.list_assets(self.owner, team["id"]), [])

    def test_team_api_provider_encrypts_and_masks_keys(self):
        team = self.store.create_team(self.owner, "Design Lab")

        with patch.object(team_cloud.settings, "team_api_secret_key", "test-secret"):
            provider = self.store.upsert_api_provider(
                self.owner,
                team["id"],
                "openai",
                TeamApiProviderSaveRequest(
                    label="OpenAI",
                    base_url="https://api.openai.com/v1",
                    protocol="openai",
                    api_key="sk-test-secret",
                ),
            )

            self.assertEqual(provider["provider_id"], "openai")
            self.assertTrue(provider["has_api_key"])
            self.assertEqual(provider["api_key_preview"], "********cret")
            self.assertNotIn("api_key", provider)
            self.assertNotIn("sk-test-secret", self.store_path.read_text(encoding="utf-8"))

            updated = self.store.upsert_api_provider(
                self.owner,
                team["id"],
                "openai",
                TeamApiProviderSaveRequest(
                    label="OpenAI Team",
                    base_url="https://api.openai.com/v1",
                    protocol="openai",
                    api_key="",
                ),
            )
            self.assertTrue(updated["has_api_key"])
            self.assertEqual(updated["label"], "OpenAI Team")
            self.assertEqual(self.store.list_api_providers(self.owner, team["id"])[0]["api_key_preview"], "********cret")

    def test_team_api_provider_saves_manual_model_lists(self):
        team = self.store.create_team(self.owner, "Design Lab")

        with patch.object(team_cloud.settings, "team_api_secret_key", "test-secret"):
            provider = self.store.upsert_api_provider(
                self.owner,
                team["id"],
                "openai",
                TeamApiProviderSaveRequest(
                    label="OpenAI",
                    base_url="https://api.example.com/v1",
                    protocol="openai",
                    api_key="sk-test-secret",
                    image_models=["gpt-image-1", " gpt-image-1 ", ""],
                    chat_models=["gpt-4o", "claude-proxy"],
                    video_models=["wan-video"],
                ),
            )

        self.assertEqual(provider["image_models"], ["gpt-image-1"])
        self.assertEqual(provider["chat_models"], ["gpt-4o", "claude-proxy"])
        self.assertEqual(provider["video_models"], ["wan-video"])

    def test_parse_openai_models_splits_known_model_types(self):
        payload = {
            "data": [
                {"id": "gpt-image-1"},
                {"id": "gpt-4o"},
                {"id": "wan-video"},
                {"id": ""},
            ]
        }

        models = team_cloud.openai_models_from_response(payload)

        self.assertEqual(models["image_models"], ["gpt-image-1"])
        self.assertEqual(models["chat_models"], ["gpt-4o"])
        self.assertEqual(models["video_models"], ["wan-video"])

    def test_team_api_provider_management_requires_admin(self):
        team = self.store.create_team(self.owner, "Design Lab")
        member = CurrentUser(id="member-1", email="member@example.com", provider="test")
        data = self.store._read()
        data["members"].append({
            "id": "member-row",
            "team_id": team["id"],
            "user_id": member.id,
            "email": member.email,
            "role": "member",
            "created_at": 1,
        })
        self.store._write(data)

        with patch.object(team_cloud.settings, "team_api_secret_key", "test-secret"):
            self.store.upsert_api_provider(
                self.owner,
                team["id"],
                "openai",
                TeamApiProviderSaveRequest(label="OpenAI", api_key="sk-owner"),
            )
            self.assertEqual(len(self.store.list_api_providers(member, team["id"])), 1)
            with self.assertRaises(HTTPException) as save_error:
                self.store.upsert_api_provider(
                    member,
                    team["id"],
                    "openai",
                    TeamApiProviderSaveRequest(label="OpenAI", api_key="sk-member"),
                )
            self.assertEqual(save_error.exception.status_code, 403)

    def test_generation_logs_are_team_scoped(self):
        team = self.store.create_team(self.owner, "Design Lab")
        log = self.store.create_generation_log(self.owner, team["id"], {
            "provider_id": "openai",
            "model": "gpt-image-1",
            "status": "succeeded",
            "request_summary": {"prompt_length": 12},
            "result_summary": {"image_count": 1},
        })

        logs = self.store.list_generation_logs(self.owner, team["id"])

        self.assertEqual(logs[0]["id"], log["id"])
        self.assertEqual(logs[0]["provider_id"], "openai")
        self.assertEqual(logs[0]["result_summary"]["image_count"], 1)
        with self.assertRaises(HTTPException) as outsider_error:
            self.store.list_generation_logs(self.outsider, team["id"])
        self.assertEqual(outsider_error.exception.status_code, 403)

    def test_supabase_user_payload_maps_to_current_user(self):
        user = current_user_from_supabase_payload({
            "id": "user-123",
            "email": "person@example.com",
        })

        self.assertEqual(user.id, "user-123")
        self.assertEqual(user.email, "person@example.com")
        self.assertEqual(user.provider, "supabase")

    def test_auth_payload_includes_access_token_when_session_ready(self):
        payload = team_cloud.sanitize_auth_payload({
            "access_token": "session-token",
            "user": {
                "id": "user-123",
                "email": "person@example.com",
            },
        })

        self.assertTrue(payload["session_ready"])
        self.assertEqual(payload["access_token"], "session-token")
        self.assertEqual(payload["user"]["email"], "person@example.com")


class TeamCloudAuthRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_auth_identifier_accepts_email_without_profile_lookup(self):
        email = await team_cloud.resolve_auth_identifier_email("User@Example.com")

        self.assertEqual(email, "user@example.com")

    async def test_resolve_auth_identifier_maps_username_to_email(self):
        async def fake_profile(username):
            self.assertEqual(username, "yiwei")
            return {"email": "Yiwei@Example.com", "username": username}

        with patch.object(team_cloud, "get_user_profile_by_username", fake_profile):
            email = await team_cloud.resolve_auth_identifier_email("YiWei")

        self.assertEqual(email, "yiwei@example.com")

    async def test_team_api_model_fetch_requires_key(self):
        with self.assertRaises(HTTPException) as error:
            await team_cloud.fetch_team_api_models_from_config({
                "base_url": "https://api.example.com/v1",
                "protocol": "openai",
                "api_key": "",
            })

        self.assertEqual(error.exception.status_code, 400)

    async def test_cloudflare_access_disabled_does_not_accept_header(self):
        with patch.object(team_cloud.settings, "cloudflare_access_enabled", False), \
             patch.object(team_cloud.settings, "dev_bypass", False):
            with self.assertRaises(HTTPException) as error:
                await team_cloud.resolve_current_user(cf_access_jwt_assertion="token")

        self.assertEqual(error.exception.status_code, 401)

    async def test_cloudflare_access_token_maps_to_current_user(self):
        with patch.object(team_cloud.settings, "cloudflare_access_enabled", True), \
             patch.object(team_cloud.settings, "cloudflare_access_team_domain", "https://tight-king-c7fe.cloudflareaccess.com"), \
             patch.object(team_cloud.settings, "cloudflare_access_audience", "app-aud"), \
             patch.object(team_cloud, "fetch_cloudflare_access_keys", AsyncMock(return_value=[{"kid": "test"}])), \
             patch.object(team_cloud, "decode_cloudflare_access_token", return_value={
                 "sub": "cf-user-1",
                 "email": "Person@Example.com",
             }):
            user = await team_cloud.authenticate_cloudflare_access_token("access-token")

        self.assertIsNotNone(user)
        self.assertEqual(user.email, "person@example.com")
        self.assertEqual(user.provider, "cloudflare-access")
        self.assertEqual(len(user.id), 36)

    async def test_cloudflare_access_user_auto_joins_default_team(self):
        temp = tempfile.TemporaryDirectory()
        try:
            store = LocalTeamStore(str(Path(temp.name) / "team_cloud.json"))
            owner = CurrentUser(id="owner-1", email="owner@example.com", provider="test")
            team = store.create_team(owner, "Design Lab")
            user = CurrentUser(
                id="59670b3e-7f42-52e6-9b87-7f9f2f87c68c",
                email="person@example.com",
                provider="cloudflare-access",
            )

            with patch.object(team_cloud.settings, "cloudflare_access_default_team_id", team["id"]), \
                 patch.object(team_cloud.settings, "cloudflare_access_default_role", "member"), \
                 patch.object(team_cloud, "active_store", return_value=store):
                await team_cloud.ensure_default_team_membership(user)

            teams = store.list_user_teams(user)
            self.assertEqual(len(teams), 1)
            self.assertEqual(teams[0]["id"], team["id"])
            self.assertEqual(teams[0]["role"], "member")
        finally:
            temp.cleanup()

    async def test_update_password_requires_recovery_token(self):
        with self.assertRaises(HTTPException) as error:
            await team_cloud.update_password(
                AuthPasswordUpdateRequest(password="new-secret"),
                Response(),
                authorization=None,
            )

        self.assertEqual(error.exception.status_code, 401)

    async def test_update_password_sets_team_cookie(self):
        response = Response()
        update_mock = AsyncMock(return_value={
            "id": "user-1",
            "email": "person@example.com",
            "updated_at": "2026-07-25T12:00:00Z",
        })

        with patch.object(team_cloud, "supabase_update_password", update_mock):
            payload = await team_cloud.update_password(
                AuthPasswordUpdateRequest(password="new-secret"),
                response,
                authorization="Bearer recovery-token",
            )

        update_mock.assert_awaited_once_with("recovery-token", "new-secret")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["access_token"], "recovery-token")
        self.assertEqual(payload["user"]["email"], "person@example.com")
        self.assertIn("team_cloud_access_token=recovery-token", response.headers["set-cookie"])

    async def test_authenticate_token_falls_back_to_supabase_when_jwt_decode_rejects(self):
        fallback_user = CurrentUser(id="user-1", email="person@example.com", provider="supabase")

        with patch.object(team_cloud.settings, "supabase_jwt_secret", "wrong-secret"), \
             patch.object(team_cloud.settings, "supabase_url", "https://supabase.example"), \
             patch.object(team_cloud.settings, "supabase_anon_key", "anon-key"), \
             patch.object(team_cloud, "decode_supabase_token", side_effect=HTTPException(status_code=401, detail="bad token")), \
             patch.object(team_cloud, "fetch_supabase_user", AsyncMock(return_value=fallback_user)) as fetch_mock:
            user = await team_cloud.authenticate_supabase_token("access-token")

        fetch_mock.assert_awaited_once_with("access-token")
        self.assertEqual(user.email, "person@example.com")


class TeamCloudStaticUiTests(unittest.TestCase):
    def test_team_api_page_exposes_row_model_management(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "static" / "team-cloud.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "team-cloud.js").read_text(encoding="utf-8")

        self.assertIn('data-api-model-add="image"', html)
        self.assertIn('data-api-model-add="chat"', html)
        self.assertIn('data-api-model-add="video"', html)
        self.assertIn("function addTeamApiModel", script)
        self.assertIn("function updateTeamApiModel", script)
        self.assertIn("function removeTeamApiModel", script)
        self.assertIn("function renderTeamApiModelRows", script)
        self.assertIn("function escapeAttr", script)

    def test_team_api_fetch_models_merges_with_manual_rows(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "static" / "js" / "team-cloud.js").read_text(encoding="utf-8")

        self.assertIn("function mergeTeamApiModelRows", script)
        self.assertIn('mergeTeamApiModelRows("image"', script)
        self.assertIn('mergeTeamApiModelRows("chat"', script)
        self.assertIn('mergeTeamApiModelRows("video"', script)

    def test_team_api_page_is_admin_only_in_the_ui(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "static" / "team-cloud.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "team-cloud.js").read_text(encoding="utf-8")

        self.assertIn('id="teamApiPanel"', html)
        self.assertIn('id="teamApiMemberNotice"', html)
        self.assertIn('function currentTeamRole', script)
        self.assertIn('function canManageTeamApi', script)
        self.assertIn('function renderTeamApiAccess', script)
        self.assertIn('teamApiPanel', script)
        self.assertIn('teamApiMemberNotice', script)

    def test_smart_canvas_asset_drag_is_captured_by_window(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("function hasSmartAssetDrag", script)
        self.assertIn("function setSmartAssetDragData", script)
        self.assertIn("application/x-smart-asset", script)
        self.assertIn("text/plain", script)
        self.assertIn("window.addEventListener('dragover'", script)
        self.assertIn("window.addEventListener('drop'", script)
        self.assertIn("hasSmartAssetDrag(event.dataTransfer)", script)
        self.assertIn("bindAssetItemDragGuard(assetGrid, '.asset-item'", script)
        self.assertIn("window.addEventListener('drop', event => {", script)
        self.assertIn("}, {capture:true});", script)

    def test_canvas_asset_drag_uses_safe_text_payload(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "static" / "js" / "canvas.js").read_text(encoding="utf-8")

        self.assertIn("function hasCanvasAssetDrag", script)
        self.assertIn("function setCanvasAssetDragData", script)
        self.assertIn("application/x-canvas-asset", script)
        self.assertIn("text/plain", script)
        self.assertIn("hasCanvasAssetDrag(event.dataTransfer)", script)
        self.assertIn("bindAssetItemDragGuard(canvasAssetGrid, '.canvas-asset-item'", script)

    def test_cloud_canvas_kind_is_per_canvas_and_defaults_classic(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "static" / "js" / "canvas-list.js").read_text(encoding="utf-8")

        self.assertIn("function normalizeCloudCanvasKind", script)
        self.assertIn("kind: normalizeCloudCanvasKind(data.kind)", script)
        self.assertNotIn("kind: data.kind || 'smart'", script)

    def test_asset_preview_images_do_not_start_native_url_drag(self):
        root = Path(__file__).resolve().parents[1]
        canvas_script = (root / "static" / "js" / "canvas.js").read_text(encoding="utf-8")
        smart_script = (root / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn('data-native-drag-guard="true"', canvas_script)
        self.assertIn('data-native-drag-guard="true"', smart_script)

    def test_supabase_visibility_migration_adds_constraints_for_existing_tables(self):
        root = Path(__file__).resolve().parents[1]
        schema = (root / "docs" / "supabase" / "team_cloud_schema.sql").read_text(encoding="utf-8")

        self.assertIn("alter table public.canvases add constraint canvases_visibility_check", schema)
        self.assertIn("alter table public.assets add constraint assets_visibility_check", schema)
        self.assertIn("visibility in ('private', 'team')", schema)

    def test_canvas_list_exposes_private_canvas_visibility_controls(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "static" / "canvas-list.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "canvas-list.js").read_text(encoding="utf-8")

        self.assertIn('data-visibility-filter="private"', html)
        self.assertIn('data-visibility-filter="team"', html)
        self.assertIn("function normalizeCloudCanvasVisibility", script)
        self.assertIn("visibility: normalizeCloudCanvasVisibility", script)
        self.assertIn("function publishCanvasToTeam", script)
        self.assertIn("/publish", script)

    def test_canvas_list_visibility_filter_stays_responsive_when_scale_is_disabled(self):
        root = Path(__file__).resolve().parents[1]
        css = (root / "static" / "css" / "canvas-list.css").read_text(encoding="utf-8")

        self.assertIn("html[data-studio-scale=\"off\"].studio-scale-managed .workspace {\n        flex-direction:column;", css)
        self.assertIn("html[data-studio-scale=\"off\"].studio-scale-managed .ws-sidebar {\n        flex:0 0 auto;\n        width:auto;", css)
        self.assertIn("html[data-studio-scale=\"off\"].studio-scale-managed .ws-board-empty .ws-primary-btn span {\n        display:inline;", css)


if __name__ == "__main__":
    unittest.main()
