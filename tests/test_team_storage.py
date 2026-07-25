import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import team_storage


class TeamStorageTests(unittest.TestCase):
    def test_safe_filename_removes_path_and_invalid_chars(self):
        self.assertEqual(team_storage.safe_filename("../bad:name.png"), "bad_name.png")

    def test_local_save_stays_under_team_asset_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(team_storage, "ASSETS_DIR", str(root / "assets")), \
                 patch.object(team_storage, "TEAM_ASSET_DIR", str(root / "assets" / "team-assets")):
                result = team_storage.save_team_asset_local(
                    b"image",
                    key="team-assets/team-1/asset.png",
                )

                self.assertEqual(result["storage_provider"], "local")
                self.assertEqual(result["public_url"], "/assets/team-assets/team-1/asset.png")
                self.assertTrue((root / "assets" / "team-assets" / "team-1" / "asset.png").exists())

                self.assertTrue(team_storage.delete_team_asset_file("team-assets/team-1/asset.png"))
                self.assertFalse((root / "assets" / "team-assets" / "team-1" / "asset.png").exists())
                self.assertFalse(team_storage.delete_team_asset_file("../outside.png"))

    def test_require_r2_blocks_local_fallback(self):
        with patch.object(team_storage.settings, "r2_endpoint_url", ""), \
             patch.object(team_storage.settings, "r2_bucket", ""), \
             patch.object(team_storage.settings, "r2_access_key_id", ""), \
             patch.object(team_storage.settings, "r2_secret_access_key", ""), \
             patch.object(team_storage.settings, "require_r2", True):
            with self.assertRaises(RuntimeError):
                team_storage.save_team_asset(
                    b"image",
                    team_id="team-1",
                    filename="asset.png",
                )

    def test_generated_save_uses_safe_local_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(team_storage, "ASSETS_DIR", str(root / "assets")), \
                 patch.object(team_storage, "GENERATED_ASSET_DIR", str(root / "assets" / "generated")), \
                 patch.object(team_storage.settings, "r2_endpoint_url", ""), \
                 patch.object(team_storage.settings, "r2_bucket", ""), \
                 patch.object(team_storage.settings, "r2_access_key_id", ""), \
                 patch.object(team_storage.settings, "r2_secret_access_key", ""):
                result = team_storage.save_generated_file(
                    b"image",
                    filename="../result:image.png",
                    category="../output",
                    asset_id="../gen-1",
                )

                self.assertEqual(result["storage_provider"], "local")
                self.assertEqual(result["storage_key"], "generated/output/gen-1.png")
                self.assertEqual(result["public_url"], "/assets/generated/output/gen-1.png")
                self.assertTrue((root / "assets" / "generated" / "output" / "gen-1.png").exists())

    def test_generated_save_rejects_unsafe_key(self):
        with self.assertRaises(ValueError):
            team_storage.save_generated_file_local(
                b"image",
                key="team-assets/not-generated/file.png",
            )

    def test_build_image_thumbnail_returns_metadata(self):
        from PIL import Image

        raw = BytesIO()
        Image.new("RGB", (640, 320), (255, 0, 0)).save(raw, format="PNG")
        result = team_storage.build_image_thumbnail(raw.getvalue(), max_size=128)

        self.assertEqual(result["content_type"], "image/jpeg")
        self.assertEqual(result["width"], 640)
        self.assertEqual(result["height"], 320)
        self.assertGreater(len(result["content"]), 0)


if __name__ == "__main__":
    unittest.main()
