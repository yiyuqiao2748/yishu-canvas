import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from team_cloud import CurrentUser, LocalTeamStore


class TeamPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LocalTeamStore(str(Path(self.temp.name) / "team_cloud.json"))
        self.owner = CurrentUser(id="owner-1", email="owner@example.com", provider="test")
        self.member = CurrentUser(id="member-1", email="member@example.com", provider="test")
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
        self.store._write(data)

    def tearDown(self):
        self.temp.cleanup()

    def test_private_canvas_is_owner_only_until_published(self):
        canvas = self.store.create_canvas(self.owner, self.project["id"], "Private draft", {"nodes": []})

        self.assertEqual(canvas["visibility"], "private")
        self.assertEqual(self.store.list_canvases(self.owner, self.project["id"])[0]["id"], canvas["id"])
        self.assertEqual(self.store.list_canvases(self.member, self.project["id"]), [])

        with self.assertRaises(HTTPException) as open_error:
            self.store.get_canvas(self.member, canvas["id"])
        self.assertEqual(open_error.exception.status_code, 404)

        published = self.store.publish_canvas(self.owner, canvas["id"])["canvas"]

        self.assertEqual(published["visibility"], "team")
        self.assertEqual(self.store.list_canvases(self.member, self.project["id"])[0]["id"], canvas["id"])
        self.assertEqual(self.store.get_canvas(self.member, canvas["id"])["id"], canvas["id"])

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


if __name__ == "__main__":
    unittest.main()
