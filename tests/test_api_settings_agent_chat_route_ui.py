import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "static" / "api-settings.html"
JS_PATH = ROOT / "static" / "js" / "api-settings.js"


class ApiSettingsAgentChatRouteUiTests(unittest.TestCase):
    def test_api_settings_exposes_an_admin_only_agent_chat_route_block(self):
        html = HTML_PATH.read_text(encoding="utf-8")

        self.assertIn('id="agentChatRouteBlock"', html)
        self.assertIn('id="agentChatProviderInput"', html)
        self.assertIn('id="agentChatModelInput"', html)
        self.assertIn('id="saveAgentChatRouteBtn"', html)

    def test_agent_chat_route_uses_safe_admin_endpoint_and_provider_chat_models(self):
        source = JS_PATH.read_text(encoding="utf-8")

        self.assertIn("/api/smart-image-agent/v3/admin/chat-route", source)
        self.assertIn("renderAgentChatRouteModels", source)
        self.assertIn("teamAuthHeaders({'Content-Type':'application/json'})", source)
        self.assertIn(".chat_models", source)
        self.assertNotIn("provider.api_key", source)


if __name__ == "__main__":
    unittest.main()
