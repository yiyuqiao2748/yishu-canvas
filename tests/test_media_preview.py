import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image

import main


def png_bytes(width=1200, height=800):
    output = io.BytesIO()
    Image.new("RGB", (width, height), (48, 86, 120)).save(output, format="PNG")
    return output.getvalue()


class RemoteMediaPreviewTests(unittest.TestCase):
    def tearDown(self):
        main.wait_for_media_preview_tasks(timeout=10)

    def test_r2_generated_key_requires_exact_configured_origin_and_generated_prefix(self):
        with patch.object(main.team_storage_settings, "r2_public_base_url", "https://cdn.example/base"):
            self.assertEqual(
                main.r2_generated_key_from_public_url("https://cdn.example/base/generated/output/a.png"),
                "generated/output/a.png",
            )
            self.assertIsNone(main.r2_generated_key_from_public_url("https://cdn.example.evil/base/generated/output/a.png"))
            self.assertIsNone(main.r2_generated_key_from_public_url("https://cdn.example/base/team-assets/team/a.png"))
            self.assertIsNone(main.r2_generated_key_from_public_url("https://cdn.example/base/generated/../team-assets/a.png"))

    def test_remote_r2_preview_uses_standard_size_and_cache(self):
        client = MagicMock()
        client.head_object.return_value = {
            "ContentLength": len(png_bytes()),
            "ContentType": "image/png",
            "ETag": '"etag-1"',
        }
        client.get_object.return_value = {
            "Body": io.BytesIO(png_bytes()),
            "ContentType": "image/png",
        }
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(main, "MEDIA_PREVIEW_DIR", tmp), \
             patch.object(main.team_storage_settings, "r2_public_base_url", "https://cdn.example"), \
             patch.object(main.team_storage_settings, "r2_endpoint_url", "https://r2.example"), \
             patch.object(main.team_storage_settings, "r2_bucket", "bucket"), \
             patch.object(main.team_storage_settings, "r2_access_key_id", "key"), \
             patch.object(main.team_storage_settings, "r2_secret_access_key", "secret"), \
             patch.object(main, "r2_client", return_value=client):
            app = TestClient(main.app)
            url = "https://cdn.example/generated/output/a.png"
            first = app.get("/api/media-preview", params={"url": url, "w": 700})
            second = app.get("/api/media-preview", params={"url": url, "w": 700})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["content-type"], "image/webp")
        self.assertEqual(Image.open(io.BytesIO(first.content)).width, 1024)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(client.get_object.call_count, 1)

    def test_remote_r2_preview_rejects_large_object_before_download(self):
        client = MagicMock()
        client.head_object.return_value = {
            "ContentLength": main.MEDIA_PREVIEW_REMOTE_MAX_BYTES + 1,
            "ContentType": "image/png",
            "ETag": '"etag-large"',
        }
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(main, "MEDIA_PREVIEW_DIR", tmp), \
             patch.object(main.team_storage_settings, "r2_public_base_url", "https://cdn.example"), \
             patch.object(main.team_storage_settings, "r2_endpoint_url", "https://r2.example"), \
             patch.object(main.team_storage_settings, "r2_bucket", "bucket"), \
             patch.object(main.team_storage_settings, "r2_access_key_id", "key"), \
             patch.object(main.team_storage_settings, "r2_secret_access_key", "secret"), \
             patch.object(main, "r2_client", return_value=client):
            response = TestClient(main.app).get(
                "/api/media-preview",
                params={"url": "https://cdn.example/generated/output/large.png", "w": 512},
            )

        self.assertEqual(response.status_code, 413)
        client.get_object.assert_not_called()

    def test_image_output_meta_uses_persisted_local_copy_for_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "result.png"
            image_path.write_bytes(png_bytes(1600, 900))
            with patch.object(main, "output_url_for", return_value="/assets/output/result.png"), \
                 patch.object(main, "output_file_from_url", side_effect=lambda value: str(image_path) if value == "/assets/output/result.png" else None):
                item = main.image_output_meta("https://cdn.example/generated/output/result.png")

        self.assertEqual(item["width"], 1600)
        self.assertEqual(item["height"], 900)
        self.assertIn("/api/media-preview", item["preview_url"])

    def test_background_preview_tasks_can_be_drained_before_source_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            source.write_bytes(png_bytes())
            with patch.object(main, "MEDIA_PREVIEW_DIR", str(Path(tmp) / "previews")):
                main.schedule_media_preview_warm(str(source))
                self.assertTrue(main.wait_for_media_preview_tasks(timeout=10))
                source.unlink()

            self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()
