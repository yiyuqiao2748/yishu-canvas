import subprocess
import unittest


class ReleasePackagingTests(unittest.TestCase):
    def test_v3_runtime_module_is_tracked_for_deployment(self):
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "smart_image_agent_v3.py"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
