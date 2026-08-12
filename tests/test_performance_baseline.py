import unittest

from tools.performance_baseline import DEFAULT_PATHS, build_canvas_fixture, percentile
from tools.prewarm_deployment import build_prewarm_urls


class PerformanceBaselineTests(unittest.TestCase):
    def test_build_canvas_fixture_has_stable_pressure_shape(self):
        fixture = build_canvas_fixture(
            [f"/assets/perf/image-{index:02d}.jpg" for index in range(50)]
        )

        self.assertEqual(len(fixture["nodes"]), 100)
        self.assertEqual(
            sum(1 for node in fixture["nodes"] if node.get("type") == "image"),
            50,
        )
        self.assertEqual(len({node["id"] for node in fixture["nodes"]}), 100)
        self.assertEqual(fixture["viewport"], {"x": 0, "y": 0, "scale": 1})

    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(percentile([100, 10, 50, 20], 75), 50)
        self.assertEqual(percentile([], 75), 0)

    def test_performance_paths_measure_built_assets(self):
        self.assertIn("/static/dist/js/workbench.min.js", DEFAULT_PATHS)
        self.assertIn("/static/dist/js/canvas.min.js", DEFAULT_PATHS)
        self.assertIn("/static/dist/tailwind.css", DEFAULT_PATHS)
        self.assertNotIn("/static/js/workbench.js", DEFAULT_PATHS)
        self.assertNotIn("/static/js/canvas.js", DEFAULT_PATHS)

    def test_prewarm_urls_cover_shell_and_built_assets(self):
        urls = build_prewarm_urls("https://canvas.example/")

        self.assertIn("https://canvas.example/", urls)
        self.assertIn("https://canvas.example/static/workbench.html", urls)
        self.assertIn("https://canvas.example/static/dist/tailwind.css", urls)
        self.assertIn("https://canvas.example/static/dist/lucide-subset.js", urls)
        self.assertIn("https://canvas.example/static/dist/js/canvas.min.js", urls)
        self.assertEqual(len(urls), len(set(urls)))


if __name__ == "__main__":
    unittest.main()
