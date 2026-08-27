import unittest
from unittest.mock import AsyncMock, patch

import main
from team_cloud import CurrentUser


class GptImageOutputCapTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_gpt_image_request_explicitly_sets_n_one(self):
        class FakeResponse:
            status_code = 200
            text = '{"data":[{"url":"https://example.test/first.png"}]}'

            def json(self):
                return {"data": [{"url": "https://example.test/first.png"}]}

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self):
                self.post_body = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, _url, **kwargs):
                self.post_body = kwargs["json"]
                return FakeResponse()

        provider = {
            "id": "custom-api",
            "base_url": "https://example.test/v1",
            "protocol": "openai",
            "api_key": "test-key",
        }
        fake_client = FakeClient()

        with patch.object(main, "upstream_async_client", return_value=fake_client):
            await main.generate_ai_image(
                "一只橙色小猫",
                "1024x1024",
                "standard",
                "gpt-image-2",
                [],
                "custom-api",
                provider_config=provider,
            )

        self.assertEqual(fake_client.post_body["n"], 1)

    async def test_single_generation_persists_only_first_upstream_image(self):
        provider = {
            "id": "custom-api",
            "name": "Provider E2E Test",
            "base_url": "https://example.test/v1",
            "protocol": "openai",
            "image_models": ["gpt-image-2"],
        }
        user = CurrentUser(id="test-user", email="test@example.test", provider="test")
        first_image = {"type": "url", "value": "https://example.test/first.png"}
        upstream_raw = {
            "data": [
                {"url": "https://example.test/first.png"},
                {"url": "https://example.test/second.png"},
            ]
        }
        save_image = AsyncMock(side_effect=["/output/first.png", "/output/second.png"])

        with patch.object(main, "request_api_provider", new=AsyncMock(return_value=(provider, user))), \
             patch.object(main, "generate_ai_image", new=AsyncMock(return_value=(first_image, upstream_raw))), \
             patch.object(main, "save_ai_image_to_output", new=save_image), \
             patch.object(main, "save_to_history"), \
             patch.object(main, "log_team_generation", new=AsyncMock()):
            result = await main.build_online_image_result(
                main.OnlineImageRequest(
                    prompt="一只橙色小猫",
                    provider_id="custom-api",
                    model="gpt-image-2",
                    n=1,
                ),
                user=user,
            )

        self.assertEqual(result["images"], ["/output/first.png"])
        save_image.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
