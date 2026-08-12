"""Measure public endpoints and generate a repeatable canvas pressure fixture."""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PATHS = (
    "/",
    "/static/workbench.html",
    "/static/dist/tailwind.css",
    "/static/dist/lucide-subset.js",
    "/static/dist/js/workbench.min.js",
    "/static/canvas.html",
    "/static/dist/js/canvas.min.js",
    "/static/css/canvas.css",
    "/api/canvases",
)


def percentile(values: Iterable[float], rank: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0
    index = max(0, min(len(ordered) - 1, math.ceil((rank / 100) * len(ordered)) - 1))
    return ordered[index]


def build_canvas_fixture(image_urls: list[str]) -> dict[str, Any]:
    urls = list(image_urls[:50])
    while len(urls) < 50:
        urls.append(f"/assets/perf/image-{len(urls):02d}.jpg")

    nodes: list[dict[str, Any]] = []
    for index in range(100):
        col = index % 10
        row = index // 10
        common = {
            "id": f"perf-node-{index:03d}",
            "x": col * 420,
            "y": row * 420,
            "w": 320,
            "h": 320 if index < 50 else 220,
        }
        if index < 50:
            nodes.append({
                **common,
                "type": "image",
                "name": f"2K/4K fixture {index + 1}",
                "url": urls[index],
                "natural_w": 3840,
                "natural_h": 2160,
            })
        else:
            nodes.append({
                **common,
                "type": "prompt",
                "text": f"Performance fixture prompt {index - 49}",
            })

    return {
        "id": "performance-pressure-100",
        "title": "Performance Pressure 100",
        "kind": "classic",
        "nodes": nodes,
        "connections": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }


def _request(url: str, *, bypass_cache: bool) -> dict[str, Any]:
    headers = {"User-Agent": "yishu-canvas-performance-baseline/1.0"}
    if bypass_cache:
        headers["Cache-Control"] = "no-cache"
    request = urllib.request.Request(url, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            status = response.status
            response_headers = response.headers
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        response_headers = exc.headers
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "status": status,
        "duration_ms": elapsed_ms,
        "bytes": len(body),
        "cache_control": response_headers.get("Cache-Control", ""),
        "content_encoding": response_headers.get("Content-Encoding", ""),
        "cf_cache_status": response_headers.get("CF-Cache-Status", ""),
        "request_id": response_headers.get("X-Request-ID", ""),
        "server_timing": response_headers.get("Server-Timing", ""),
    }


def measure(base_url: str, paths: Iterable[str], repeats: int) -> dict[str, Any]:
    base = base_url.rstrip("/")
    report: dict[str, Any] = {
        "base_url": base,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repeats": repeats,
        "paths": {},
    }
    for path in paths:
        clean_path = "/" + str(path).lstrip("/")
        cold_url = f"{base}{clean_path}"
        separator = "&" if "?" in cold_url else "?"
        cold = _request(f"{cold_url}{separator}perf_bust={uuid.uuid4().hex}", bypass_cache=True)
        hot = [_request(cold_url, bypass_cache=False) for _ in range(max(1, repeats))]
        report["paths"][clean_path] = {
            "cold": cold,
            "hot": hot,
            "hot_p50_ms": percentile([item["duration_ms"] for item in hot], 50),
            "hot_p75_ms": percentile([item["duration_ms"] for item in hot], 75),
            "hot_p95_ms": percentile([item["duration_ms"] for item in hot], 95),
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://canvas.yiyuqiaoai.uk")
    parser.add_argument("--path", action="append", dest="paths")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fixture-output", type=Path)
    parser.add_argument("--image-url", action="append", default=[])
    args = parser.parse_args()

    if args.fixture_output:
        args.fixture_output.parent.mkdir(parents=True, exist_ok=True)
        args.fixture_output.write_text(
            json.dumps(build_canvas_fixture(args.image_url), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    report = measure(args.base_url, args.paths or DEFAULT_PATHS, max(1, args.repeats))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
