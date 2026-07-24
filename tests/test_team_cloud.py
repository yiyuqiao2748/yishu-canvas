import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from team_cloud import CurrentUser, LocalTeamStore


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


if __name__ == "__main__":
    unittest.main()
