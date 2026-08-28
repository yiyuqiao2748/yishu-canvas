import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


PATH = "/api/smart-image-agent/v3/admin/chat-route"
PROVIDERS = [
    {
        "id": "gateway",
        "name": "OAIREGBOX",
        "enabled": True,
        "chat_models": ["gemini-3.5-flash-fast"],
        "api_key": "server-only-key",
    },
    {
        "id": "disabled",
        "name": "Disabled provider",
        "enabled": False,
        "chat_models": ["chat-x"],
        "api_key": "server-only-key",
    },
    {
        "id": "no-key",
        "name": "No key provider",
        "enabled": True,
        "chat_models": ["chat-y"],
        "api_key": "",
    },
]


class AgentChatRouteAdminApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app, raise_server_exceptions=False)
        self.user = SimpleNamespace(id="owner-1", email="owner@example.test")
        self.env_updates = []
        self.patches = [
            patch.object(main, "load_api_providers", return_value=PROVIDERS),
            patch.object(main, "resolve_admin_team", AsyncMock(return_value=("team-1", [{"id": "team-1", "role": "owner"}]))),
            patch.object(main, "update_env_values", side_effect=self.env_updates.append),
            patch.object(main, "reload_env_globals"),
        ]
        for item in self.patches:
            item.start()
        main.app.dependency_overrides[main.require_user] = lambda: self.user

    def tearDown(self):
        self.client.close()
        main.app.dependency_overrides.clear()
        for item in reversed(self.patches):
            item.stop()

    def test_get_returns_only_safe_selectable_provider_fields(self):
        response = self.client.get(PATH)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["providers"],
            [{
                "id": "gateway",
                "name": "OAIREGBOX",
                "chat_models": ["gemini-3.5-flash-fast"],
                "has_key": True,
            }],
        )
        self.assertNotIn("api_key", response.text)
        self.assertNotIn("server-only-key", response.text)

    def test_put_persists_valid_provider_and_model_without_returning_key(self):
        response = self.client.put(PATH, json={"provider_id": "gateway", "model": "gemini-3.5-flash-fast"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.env_updates, [{"AGENT_CHAT_PROVIDER": "gateway", "AGENT_CHAT_MODEL": "gemini-3.5-flash-fast"}])
        self.assertNotIn("server-only-key", response.text)

    def test_put_rejects_unknown_disabled_unlisted_and_keyless_routes(self):
        for payload in [
            {"provider_id": "missing", "model": "chat-x"},
            {"provider_id": "disabled", "model": "chat-x"},
            {"provider_id": "gateway", "model": "not-imported"},
            {"provider_id": "no-key", "model": "chat-y"},
        ]:
            with self.subTest(payload=payload):
                response = self.client.put(PATH, json=payload)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.env_updates, [])

    def test_get_rejects_non_admin(self):
        with patch.object(main, "resolve_admin_team", AsyncMock(side_effect=HTTPException(status_code=403, detail="forbidden"))):
            response = self.client.get(PATH)

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
