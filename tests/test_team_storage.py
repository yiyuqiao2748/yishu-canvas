import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
