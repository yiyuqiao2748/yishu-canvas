import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from unittest.mock import patch

import team_cloud
from team_cloud import CanvasSaveRequest, CurrentUser, LocalTeamStore, TeamApiProviderSaveRequest, current_user_from_supabase_payload


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


if __name__ == "__main__":
    unittest.main()
