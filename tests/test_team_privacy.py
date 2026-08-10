import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi import HTTPException

from team_cloud import CurrentUser, LocalTeamStore, SupabaseTeamStore


class TeamPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LocalTeamStore(str(Path(self.temp.name) / "team_cloud.json"))
        self.owner = CurrentUser(id="owner-1", email="owner@example.com", provider="test")
        self.admin = CurrentUser(id="admin-1", email="admin@example.com", provider="test")
        self.member = CurrentUser(id="member-1", email="member@example.com", provider="test")
        self.other_member = CurrentUser(id="member-2", email="member2@example.com", provider="test")
        self.team = self.store.create_team(self.owner, "Design Lab")
        self.project = self.store.create_project(self.owner, self.team["id"], "Launch Board")
        data = self.store._read()
        data["members"].append({
            "id": "member-row",
            "team_id": self.team["id"],
            "user_id": self.member.id,
            "email": self.member.email,
            "role": "member",
            "created_at": 1,
        })
        data["members"].append({
            "id": "member-row-2",
            "team_id": self.team["id"],
            "user_id": self.other_member.id,
            "email": self.other_member.email,
            "role": "member",
            "created_at": 1,
        })
        data["members"].append({
            "id": "admin-row",
            "team_id": self.team["id"],
            "user_id": self.admin.id,
            "email": self.admin.email,
            "role": "admin",
            "created_at": 1,
        })
        self.store._write(data)

    def tearDown(self):
        self.temp.cleanup()

    def test_private_canvas_is_creator_and_admin_only_until_published(self):
        canvas = self.store.create_canvas(self.owner, self.project["id"], "Private draft", {"nodes": []})

        self.assertEqual(canvas["visibility"], "private")
        self.assertEqual(self.store.list_canvases(self.owner, self.project["id"])[0]["id"], canvas["id"])
        self.assertEqual(self.store.list_canvases(self.admin, self.project["id"])[0]["id"], canvas["id"])
        self.assertEqual(self.store.list_canvases(self.member, self.project["id"]), [])

        with self.assertRaises(HTTPException) as open_error:
            self.store.get_canvas(self.member, canvas["id"])
        self.assertEqual(open_error.exception.status_code, 404)

        published = self.store.publish_canvas(self.owner, canvas["id"])["canvas"]

        self.assertEqual(published["visibility"], "team")
        self.assertEqual(self.store.list_canvases(self.member, self.project["id"])[0]["id"], canvas["id"])
        self.assertEqual(self.store.get_canvas(self.member, canvas["id"])["id"], canvas["id"])

    def test_member_private_canvas_is_hidden_from_other_members_but_visible_to_admins(self):
        canvas = self.store.create_canvas(self.member, self.project["id"], "Member draft", {"nodes": []})

        self.assertEqual([item["id"] for item in self.store.list_canvases(self.member, self.project["id"])], [canvas["id"]])
        self.assertEqual([item["id"] for item in self.store.list_canvases(self.owner, self.project["id"])], [canvas["id"]])
        self.assertEqual([item["id"] for item in self.store.list_canvases(self.admin, self.project["id"])], [canvas["id"]])
        self.assertEqual(self.store.list_canvases(self.other_member, self.project["id"]), [])
        self.assertEqual(self.store.get_canvas(self.owner, canvas["id"])["id"], canvas["id"])
        self.assertEqual(self.store.get_canvas(self.admin, canvas["id"])["id"], canvas["id"])
        with self.assertRaises(HTTPException) as error:
            self.store.get_canvas(self.other_member, canvas["id"])
        self.assertEqual(error.exception.status_code, 404)

        published = self.store.publish_canvas(self.member, canvas["id"])["canvas"]
        self.assertEqual(published["visibility"], "team")
        self.assertEqual(self.store.get_canvas(self.other_member, canvas["id"])["id"], canvas["id"])

    def test_member_project_list_hides_projects_with_only_other_users_private_canvases(self):
        self.assertEqual(self.store.list_projects(self.member, self.team["id"]), [])
        self.assertEqual([item["id"] for item in self.store.list_projects(self.owner, self.team["id"])], [self.project["id"]])
        self.assertEqual([item["id"] for item in self.store.list_projects(self.admin, self.team["id"])], [self.project["id"]])

        canvas = self.store.create_canvas(self.member, self.project["id"], "Member draft", {"nodes": []})
        self.assertEqual([item["id"] for item in self.store.list_projects(self.member, self.team["id"])], [self.project["id"]])
        self.assertEqual(self.store.list_projects(self.other_member, self.team["id"]), [])

        self.store.publish_canvas(self.member, canvas["id"])
        self.assertEqual([item["id"] for item in self.store.list_projects(self.other_member, self.team["id"])], [self.project["id"]])

    def test_private_asset_is_owner_only_until_published(self):
        asset = self.store.create_asset(self.owner, self.team["id"], {
            "id": "asset-private",
            "name": "private.png",
            "kind": "image",
            "storage_key": "team-assets/team/private.png",
            "public_url": "/assets/team-assets/team/private.png",
        })

        self.assertEqual(asset["visibility"], "private")
        self.assertEqual(self.store.list_assets(self.owner, self.team["id"])[0]["id"], asset["id"])
        self.assertEqual(self.store.list_assets(self.member, self.team["id"]), [])

        published = self.store.publish_asset(self.owner, self.team["id"], asset["id"])["asset"]

        self.assertEqual(published["visibility"], "team")
        self.assertEqual(self.store.list_assets(self.member, self.team["id"])[0]["id"], asset["id"])


class SupabasePrivacyQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_canvas_list_query_includes_all_private_records(self):
        store = SupabaseTeamStore("https://example.supabase.co", "service-key")
        store._require_project_member = AsyncMock(return_value={"id": "project-1", "team_id": "team-1"})
        store._require_member = AsyncMock(return_value={"role": "owner"})
        store._request = AsyncMock(return_value=[])
        user = CurrentUser(id="owner-1", email="owner@example.com")

        await store.list_canvases(user, "project-1")

        request_path = store._request.await_args.args[1]
        self.assertNotIn("or=(visibility.eq.team,created_by.eq.owner-1)", request_path)

    async def test_member_canvas_list_query_limits_private_records_to_creator(self):
        store = SupabaseTeamStore("https://example.supabase.co", "service-key")
        store._require_project_member = AsyncMock(return_value={"id": "project-1", "team_id": "team-1"})
        store._require_member = AsyncMock(return_value={"role": "member"})
        store._request = AsyncMock(return_value=[])
        user = CurrentUser(id="member-1", email="member@example.com")

        await store.list_canvases(user, "project-1")

        request_path = store._request.await_args.args[1]
        self.assertIn("or=(visibility.eq.team,created_by.eq.member-1)", request_path)

    async def test_member_project_list_filters_out_unrelated_private_projects(self):
        store = SupabaseTeamStore("https://example.supabase.co", "service-key")
        store._require_member = AsyncMock(return_value={"role": "member"})
        store._request = AsyncMock(side_effect=[
            [
                {"id": "own-project", "created_by": "member-1"},
                {"id": "shared-project", "created_by": "member-2"},
                {"id": "private-project", "created_by": "member-2"},
            ],
            [{"project_id": "shared-project"}],
        ])
        user = CurrentUser(id="member-1", email="member@example.com")

        projects = await store.list_projects(user, "team-1")

        self.assertEqual([project["id"] for project in projects], ["own-project", "shared-project"])


if __name__ == "__main__":
    unittest.main()
