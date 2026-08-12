"""Prewarm public shell assets after deployment."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any


PREWARM_PATHS = (
    "/",
    "/static/workbench.html",
    "/static/canvas.html",
    "/static/smart-canvas.html",
    "/static/dist/tailwind.css",
    "/static/dist/lucide-subset.js",
    "/static/dist/js/index.min.js",
    "/static/dist/js/workbench.min.js",
    "/static/dist/js/canvas.min.js",
    "/static/dist/js/smart-canvas.min.js",
)


def build_prewarm_urls(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    return list(dict.fromkeys(f"{base}{path}" for path in PREWARM_PATHS))


def prewarm(base_url: str, timeout: float = 30) -> list[dict[str, Any]]:
    results = []
    for url in build_prewarm_urls(base_url):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "yishu-canvas-deploy-prewarm/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response.read()
                results.append({
                    "url": url,
                    "status": response.status,
                    "cache": response.headers.get("CF-Cache-Status", ""),
                })
        except urllib.error.HTTPError as exc:
            results.append({"url": url, "status": exc.code, "cache": ""})
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://canvas.yiyuqiaoai.uk")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    results = prewarm(args.base_url, args.timeout)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if any(item["status"] >= 400 for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
