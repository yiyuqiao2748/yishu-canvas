import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


class CanvasLogCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.generated = self.assets / "output"
        self.inputs = self.assets / "input"
        self.legacy = self.root / "output"
        self.data = self.root / "data"
        self.canvases = self.data / "canvases"
        self.conversations = self.data / "conversations"
        self.previews = self.data / "media_previews"
        for path in (self.generated, self.inputs, self.legacy, self.canvases, self.conversations, self.previews):
            path.mkdir(parents=True, exist_ok=True)
        self.history = self.root / "history.json"
        self.global_config = self.root / "global_config.json"
        self.asset_library = self.data / "asset_library.json"
        self.history.write_text("[]", encoding="utf-8")
        self.global_config.write_text("{}", encoding="utf-8")
        self.patches = [
            patch.object(main, "ASSETS_DIR", str(self.assets)),
            patch.object(main, "OUTPUT_OUTPUT_DIR", str(self.generated)),
            patch.object(main, "OUTPUT_DIR", str(self.legacy)),
            patch.object(main, "DATA_DIR", str(self.data)),
            patch.object(main, "CANVAS_DIR", str(self.canvases)),
            patch.object(main, "CONVERSATION_DIR", str(self.conversations)),
            patch.object(main, "MEDIA_PREVIEW_DIR", str(self.previews)),
            patch.object(main, "HISTORY_FILE", str(self.history)),
            patch.object(main, "GLOBAL_CONFIG_FILE", str(self.global_config)),
            patch.object(main, "ASSET_LIBRARY_PATH", str(self.asset_library)),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def write_canvas(self, canvas_id, logs, nodes=None, updated_at=0):
        value = {
            "id": canvas_id,
            "title": "test",
            "logs": logs,
            "nodes": nodes or [],
            "connections": [],
            "viewport": {"x": 0, "y": 0, "scale": 1},
            "updated_at": updated_at,
        }
        (self.canvases / f"{canvas_id}.json").write_text(json.dumps(value), encoding="utf-8")

    def generated_file(self, name="result.png", content=b"image"):
        path = self.generated / name
        path.write_bytes(content)
        return path, f"/assets/output/{name}"

    def test_healthz_reports_deployment_readiness_without_secrets(self):
        with patch.object(main.team_cloud_settings, "supabase_url", "https://supabase.example"), \
             patch.object(main.team_cloud_settings, "supabase_anon_key", "anon-secret"), \
             patch.object(main.team_cloud_settings, "supabase_service_role_key", "service-secret"), \
             patch.object(main.team_cloud_settings, "team_api_secret_key", "team-secret"), \
             patch.object(main.team_cloud_settings, "dev_bypass", False), \
             patch.object(main.team_storage_settings, "r2_endpoint_url", "https://r2.example"), \
             patch.object(main.team_storage_settings, "r2_bucket", "bucket"), \
             patch.object(main.team_storage_settings, "r2_access_key_id", "r2-key"), \
             patch.object(main.team_storage_settings, "r2_secret_access_key", "r2-secret"), \
             patch.object(main.team_storage_settings, "r2_public_base_url", "https://assets.example"), \
             patch.object(main.team_storage_settings, "require_r2", True):
            payload = main.deployment_health_config()

        self.assertTrue(payload["auth_ready"])
        self.assertTrue(payload["supabase_ready"])
        self.assertFalse(payload["dev_bypass"])
        self.assertTrue(payload["team_api_secret_ready"])
        self.assertTrue(payload["storage"]["r2_ready"])
        self.assertTrue(payload["storage"]["r2_public_url_ready"])
        self.assertTrue(payload["storage"]["require_r2"])
        self.assertNotIn("team-secret", json.dumps(payload))
        self.assertNotIn("r2-secret", json.dumps(payload))
        self.assertNotIn("service-secret", json.dumps(payload))

    def test_deployment_installs_websocket_runtime(self):
        requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
        packages = {line.strip().split("==", 1)[0].lower() for line in requirements.splitlines() if line.strip()}

        self.assertTrue(
            {"uvicorn[standard]", "websockets", "wsproto"} & packages,
            "Uvicorn needs a WebSocket runtime for /ws/stats instead of returning 404 on upgrade.",
        )

    def test_output_public_url_uses_local_url_without_r2(self):
        path, url = self.generated_file()
        with patch.object(main.team_storage_settings, "r2_endpoint_url", ""), \
             patch.object(main.team_storage_settings, "r2_bucket", ""), \
             patch.object(main.team_storage_settings, "r2_access_key_id", ""), \
             patch.object(main.team_storage_settings, "r2_secret_access_key", ""):
            self.assertEqual(
                main.output_public_url_for_saved_file("result.png", str(path), "output", "image/png"),
                url,
            )

    def test_output_public_url_uses_generated_storage_when_r2_ready(self):
        path, _url = self.generated_file()
        with patch.object(main.team_storage_settings, "r2_endpoint_url", "https://r2.example"), \
             patch.object(main.team_storage_settings, "r2_bucket", "bucket"), \
             patch.object(main.team_storage_settings, "r2_access_key_id", "key"), \
             patch.object(main.team_storage_settings, "r2_secret_access_key", "secret"), \
             patch.object(main, "save_generated_file_from_path", return_value={"public_url": "https://cdn.example/generated/output/result.png"}) as save_mock:
            self.assertEqual(
                main.output_public_url_for_saved_file("result.png", str(path), "output", "image/png"),
                "https://cdn.example/generated/output/result.png",
            )
            save_mock.assert_called_once_with(
                str(path),
                content_type="image/png",
                category="output",
                asset_id="result",
            )

    def test_collects_nested_local_media_only(self):
        value = {
            "items": [
                {"url": "/assets/output/a.png"},
                "https://example.com/remote.png",
                {"nested": "/output/b.png?x=1"},
            ]
        }
        self.assertEqual(
            main.collect_local_media_urls(value),
            ["/assets/output/a.png", "/output/b.png?x=1"],
        )

    def test_generated_path_rejects_input_files(self):
        generated_path, generated_url = self.generated_file()
        input_path = self.inputs / "reference.png"
        input_path.write_bytes(b"input")
        self.assertEqual(main.generated_media_path_from_url(generated_url), str(generated_path.resolve()))
        self.assertIsNone(main.generated_media_path_from_url("/assets/input/reference.png"))

    def test_output_url_resolves_only_to_output_mount(self):
        generated_collision = self.generated / "same.png"
        legacy_output = self.legacy / "same.png"
        generated_collision.write_bytes(b"generated")
        legacy_output.write_bytes(b"mounted-output")

        self.assertEqual(main.generated_media_path_from_url("/output/same.png"), str(legacy_output.resolve()))

    async def test_record_only_keeps_media(self):
        path, url = self.generated_file()
        self.write_canvas("record_only", [{"id": "log-1", "outputs": [url]}])

        result = await main.delete_canvas_log(
            "record_only",
            main.DeleteCanvasLogRequest(log_id="log-1", delete_unreferenced_media=False),
        )

        self.assertTrue(path.exists())
        self.assertEqual(result["removed_files"], [])
        self.assertEqual(result["canvas"]["logs"], [])

    async def test_cleanup_keeps_media_referenced_by_a_node(self):
        path, url = self.generated_file()
        self.write_canvas(
            "referenced",
            [{"id": "log-1", "outputs": [{"url": url}]}],
            nodes=[{"id": "node-1", "generatedOutputs": [url]}],
        )

        result = await main.delete_canvas_log(
            "referenced",
            main.DeleteCanvasLogRequest(log_id="log-1", delete_unreferenced_media=True),
        )

        self.assertTrue(path.exists())
        self.assertEqual(result["removed_files"], [])
        self.assertEqual(result["skipped_referenced"], [path.name])

    async def test_forced_cleanup_resets_result_node_and_removes_media(self):
        path, url = self.generated_file("node-owned.png")
        self.write_canvas(
            "remove_node",
            [{"id": "log-1", "outputs": [{"url": url}]}],
            nodes=[
                {"id": "prompt", "type": "smart-prompt"},
                {
                    "id": "result",
                    "type": "smart-image",
                    "images": [{"url": url}],
                    "promptDraftText": "keep this prompt",
                    "runInputRefs": [{"url": "/assets/input/reference.png"}],
                    "runSettings": {"model": "test-model"},
                    "runFinishedAt": 999,
                },
            ],
        )
        stored = json.loads((self.canvases / "remove_node.json").read_text(encoding="utf-8"))
        stored["connections"] = [{"id": "edge", "from": "prompt", "to": "result"}]
        (self.canvases / "remove_node.json").write_text(json.dumps(stored), encoding="utf-8")

        result = await main.delete_canvas_log(
            "remove_node",
            main.DeleteCanvasLogRequest(
                log_id="log-1",
                delete_unreferenced_media=True,
                reset_referencing_nodes=True,
            ),
        )

        self.assertFalse(path.exists())
        self.assertEqual([node["id"] for node in result["canvas"]["nodes"]], ["prompt", "result"])
        reset = result["canvas"]["nodes"][1]
        self.assertEqual(reset["images"], [])
        self.assertEqual(reset["pending"], 0)
        self.assertFalse(reset["running"])
        self.assertEqual(reset["promptDraftText"], "keep this prompt")
        self.assertEqual(reset["runInputRefs"], [{"url": "/assets/input/reference.png"}])
        self.assertEqual(reset["runSettings"], {"model": "test-model"})
        self.assertNotIn("runFinishedAt", reset)
        self.assertEqual(result["canvas"]["connections"], [{"id": "edge", "from": "prompt", "to": "result"}])
        self.assertEqual(result["reset_node_ids"], ["result"])

    async def test_forced_cleanup_clears_classic_output_comparison_refs(self):
        path, url = self.generated_file("classic-output.png")
        self.write_canvas(
            "classic_output",
            [{"id": "log-1", "outputs": [url]}],
            nodes=[
                {"id": "generator", "type": "online", "prompt": "keep", "generatedOutputs": [url]},
                {
                    "id": "output",
                    "type": "output",
                    "images": [{"url": url}],
                    "_pending": [{"url": url}],
                    "imageComparisons": {"before": url},
                },
            ],
        )
        stored = json.loads((self.canvases / "classic_output.json").read_text(encoding="utf-8"))
        stored["connections"] = [{"id": "edge", "from": "generator", "to": "output"}]
        (self.canvases / "classic_output.json").write_text(json.dumps(stored), encoding="utf-8")

        result = await main.delete_canvas_log(
            "classic_output",
            main.DeleteCanvasLogRequest(
                log_id="log-1",
                delete_unreferenced_media=True,
                reset_referencing_nodes=True,
            ),
        )

        self.assertFalse(path.exists())
        generator, reset = result["canvas"]["nodes"]
        self.assertEqual(generator["prompt"], "keep")
        self.assertEqual(generator["generatedOutputs"], [])
        self.assertEqual(reset["images"], [])
        self.assertEqual(reset["_pending"], [])
        self.assertEqual(reset["imageComparisons"], {})
        self.assertEqual(result["canvas"]["connections"], [{"id": "edge", "from": "generator", "to": "output"}])

    async def test_reset_clears_all_generated_results_but_keeps_reference_preview(self):
        first, first_url = self.generated_file("first-result.png")
        second, second_url = self.generated_file("second-result.png")
        reference = self.inputs / "reference.png"
        reference.write_bytes(b"reference")
        reference_url = "/assets/input/reference.png"
        self.write_canvas(
            "multi_result",
            [{"id": "log-1", "outputs": [first_url]}],
            nodes=[{
                "id": "result",
                "type": "smart-image",
                "images": [
                    {"url": first_url, "generatedResult": True},
                    {"url": second_url, "generatedResult": True},
                    {"url": reference_url, "loopInputPreview": True},
                ],
                "promptDraftText": "keep prompt",
                "runFinishedAt": 999,
            }],
        )

        result = await main.delete_canvas_log(
            "multi_result",
            main.DeleteCanvasLogRequest(
                log_id="log-1",
                delete_unreferenced_media=True,
                reset_referencing_nodes=True,
            ),
        )

        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertTrue(reference.exists())
        reset = result["canvas"]["nodes"][0]
        self.assertEqual(reset["images"], [{"url": reference_url, "loopInputPreview": True}])
        self.assertEqual(reset["promptDraftText"], "keep prompt")
        self.assertNotIn("runFinishedAt", reset)

    async def test_reference_only_downstream_node_does_not_expand_deletion(self):
        source, source_url = self.generated_file("source-result.png")
        downstream, downstream_url = self.generated_file("downstream-result.png")
        self.write_canvas(
            "reference_only",
            [{"id": "log-1", "outputs": [source_url]}],
            nodes=[{
                "id": "downstream",
                "type": "smart-image",
                "images": [
                    {"url": source_url, "loopInputPreview": True},
                    {"url": downstream_url, "generatedResult": True},
                ],
                "runInputRefs": [{"url": source_url}],
                "promptDraftText": "keep downstream",
            }],
        )

        result = await main.delete_canvas_log(
            "reference_only",
            main.DeleteCanvasLogRequest(
                log_id="log-1",
                delete_unreferenced_media=True,
                reset_referencing_nodes=True,
            ),
        )

        self.assertTrue(source.exists())
        self.assertTrue(downstream.exists())
        node = result["canvas"]["nodes"][0]
        self.assertEqual(node["images"], [
            {"url": source_url, "loopInputPreview": True},
            {"url": downstream_url, "generatedResult": True},
        ])
        self.assertEqual(node["promptDraftText"], "keep downstream")
        self.assertEqual(result["reset_node_ids"], [])

    async def test_cleanup_deletes_unreferenced_media_and_preview(self):
        path, url = self.generated_file()
        preview = Path(main.media_preview_cache_paths(str(path), 256)[0])
        preview.write_bytes(b"preview")
        self.write_canvas("unreferenced", [{"id": "log-1", "outputs": [url]}])

        result = await main.delete_canvas_log(
            "unreferenced",
            main.DeleteCanvasLogRequest(log_id="log-1", delete_unreferenced_media=True),
        )

        self.assertFalse(path.exists())
        self.assertFalse(preview.exists())
        self.assertEqual(result["removed_files"], [path.name])
        self.assertEqual(result["removed_previews"], 1)

    async def test_generation_history_does_not_pin_deleted_log_media(self):
        path, url = self.generated_file("history-only.png")
        self.history.write_text(
            json.dumps([{"timestamp": 123, "url": url, "images": [url]}]),
            encoding="utf-8",
        )
        self.write_canvas("history_only", [{"id": "log-1", "outputs": [url]}])

        result = await main.delete_canvas_log(
            "history_only",
            main.DeleteCanvasLogRequest(log_id="log-1", delete_unreferenced_media=True),
        )

        self.assertFalse(path.exists())
        self.assertEqual(result["removed_files"], [path.name])
        self.assertEqual(json.loads(self.history.read_text(encoding="utf-8")), [])

    def test_agent_plain_text_reply_is_preserved(self):
        plan = main._normalize_agent_plan("我可以继续帮你优化提示词。", "帮我看看")

        self.assertEqual(plan["action"], "chat")
        self.assertEqual(plan["reply"], "我可以继续帮你优化提示词。")
        self.assertEqual(plan["cards"], [])

    def test_agent_default_routes_avoid_unverified_runninghub_fallback(self):
        providers = [
            {"id": "runninghub", "enabled": True, "chat_models": []},
            {"id": "agnes-ai", "enabled": True, "chat_models": ["agnes-2.5-flash"]},
            {"id": "custom-api", "enabled": True, "image_models": ["nano-banana-2", "nano-banana-pro"]},
        ]

        chat_route = main.resolve_agent_model_route("chat", {}, providers)
        image_route = main.resolve_agent_model_route("generate_image", {}, providers)

        self.assertEqual(chat_route["provider_id"], "agnes-ai")
        self.assertEqual(chat_route["model"], "agnes-2.5-flash")
        self.assertTrue(chat_route["fallback_used"])
        self.assertNotEqual(chat_route["provider_id"], "runninghub")
        self.assertEqual(image_route["provider_id"], "custom-api")
        self.assertEqual(image_route["model"], "nano-banana-2")

    def test_agent_chat_route_prefers_modelscope_when_available(self):
        providers = [
            {"id": "modelscope", "enabled": True, "chat_models": ["Qwen/Qwen3-235B-A22B"]},
            {"id": "agnes-ai", "enabled": True, "chat_models": ["agnes-2.5-flash"]},
        ]

        route = main.resolve_agent_model_route("chat", {"model": "nano-banana-2"}, providers)

        self.assertEqual(route["provider_id"], "modelscope")
        self.assertEqual(route["model"], "Qwen/Qwen3-235B-A22B")
        self.assertFalse(route["fallback_used"])

    def test_agent_chat_route_requires_credentials_before_fallback(self):
        providers = [
            {"id": "modelscope", "enabled": True, "chat_models": ["Qwen/Qwen3-235B-A22B"]},
            {"id": "agnes-ai", "enabled": True, "chat_models": ["agnes-2.5-flash"]},
        ]

        with self.assertRaises(main.HTTPException) as raised:
            main.resolve_agent_model_route("chat", {}, providers, require_credentials=True)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("modelscope/Qwen/Qwen3-235B-A22B", str(raised.exception.detail))
        self.assertIn("Agnes fallback is also missing an API key", str(raised.exception.detail))

    def test_agent_chat_route_uses_agnes_fallback_only_with_key(self):
        providers = [
            {"id": "modelscope", "enabled": True, "chat_models": ["Qwen/Qwen3-235B-A22B"]},
            {"id": "agnes-ai", "enabled": True, "api_key": "sk-test", "chat_models": ["agnes-2.5-flash"]},
        ]

        route = main.resolve_agent_model_route("chat", {}, providers, require_credentials=True)

        self.assertEqual(route["provider_id"], "agnes-ai")
        self.assertEqual(route["model"], "agnes-2.5-flash")
        self.assertTrue(route["fallback_used"])

    def test_agent_image_route_detection_uses_user_request_not_chat_reply(self):
        plan = {
            "action": "chat",
            "reply": "\u6211\u4f1a\u5e2e\u4f60\u68b3\u7406\u8fd9\u4e2a\u8bbe\u8ba1\u9879\u76ee\u7684\u4e0b\u4e00\u6b65\u3002",
            "prompt_text": "\u5982\u9700\u751f\u6210\u56fe\u7247\uff0c\u53ef\u4ee5\u518d\u660e\u786e\u63d0\u51fa\u3002",
        }

        self.assertFalse(main._agent_plan_needs_image_route(
            "\u8bb0\u4f4f\u6211\u521a\u624d\u8bf4\u7684\u9879\u76ee\u540d\u53eb\u6668\u661f\uff0c\u4e0b\u4e00\u53e5\u53ea\u56de\u7b54\u8fd9\u4e2a\u9879\u76ee\u540d\u662f\u4ec0\u4e48\u3002",
            plan,
        ))
        self.assertTrue(main._agent_plan_needs_image_route(
            "\u751f\u6210\u4e00\u5f20\u9910\u5385\u5f00\u4e1a\u6d77\u62a5\uff0c\u6696\u8272\u706f\u5149\uff0c\u9002\u5408\u516c\u4f17\u53f7\u9996\u56fe\u3002",
            {"action": "chat", "reply": "\u597d\u7684\u3002"},
        ))

    async def test_cleanup_preserves_media_when_json_is_unreadable(self):
        path, url = self.generated_file()
        (self.canvases / "being-written.json").write_text("{", encoding="utf-8")
        self.write_canvas("unreadable_owner", [{"id": "log-1", "outputs": [url]}])

        result = await main.delete_canvas_log(
            "unreadable_owner",
            main.DeleteCanvasLogRequest(log_id="log-1", delete_unreferenced_media=True),
        )

        self.assertTrue(path.exists())
        self.assertEqual(result["skipped_referenced"], [path.name])

    async def test_stale_delete_is_rejected_without_changing_canvas(self):
        path, url = self.generated_file()
        self.write_canvas("stale", [{"id": "log-1", "outputs": [url]}], updated_at=200)

        with self.assertRaises(main.HTTPException) as caught:
            await main.delete_canvas_log(
                "stale",
                main.DeleteCanvasLogRequest(
                    log_id="log-1",
                    delete_unreferenced_media=True,
                    base_updated_at=100,
                ),
            )

        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue(path.exists())
        stored = json.loads((self.canvases / "stale.json").read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in stored["logs"]], ["log-1"])

    async def test_saved_version_advances_when_clock_is_unchanged(self):
        _, url = self.generated_file()
        self.write_canvas("monotonic", [{"id": "log-1", "outputs": [url]}], updated_at=200)

        with patch.object(main, "now_ms", return_value=200):
            result = await main.delete_canvas_log(
                "monotonic",
                main.DeleteCanvasLogRequest(log_id="log-1", base_updated_at=200),
            )

        self.assertEqual(result["canvas"]["updated_at"], 201)


    def test_agnes_ai_provider_is_available_as_builtin_api_node(self):
        providers = main.merge_default_api_providers([], inject_missing=True)
        agnes = next(item for item in providers if item["id"] == "agnes-ai")

        self.assertEqual(agnes["name"], "Agnes AI")
        self.assertEqual(agnes["base_url"], main.AGNES_DEFAULT_BASE_URL)
        self.assertEqual(agnes["protocol"], "openai")
        self.assertEqual(agnes["image_request_mode"], "openai-json")
        self.assertIn("agnes-image-2.1-flash", agnes["image_models"])
        self.assertIn("agnes-video-v2.0", agnes["video_models"])
        self.assertEqual(main.effective_image_request_mode(agnes, "agnes-image-2.1-flash"), "openai-json")

    def test_legacy_agnes_provider_is_migrated_to_stable_builtin_id(self):
        providers = main.merge_default_api_providers([
            {
                "id": "agnes",
                "name": "Agnes AI old",
                "base_url": "https://apihub.agnes-ai.com/v1",
                "protocol": "openai",
                "image_models": ["agnes-image-2.0-flash"],
                "video_models": [],
            }
        ], inject_missing=True)
        agnes_items = [item for item in providers if item.get("id") == "agnes-ai"]

        self.assertEqual(len(agnes_items), 1)
        self.assertEqual(agnes_items[0]["base_url"], "https://apihub.agnes-ai.com/v1")
        self.assertEqual(agnes_items[0]["image_request_mode"], "openai-json")
        self.assertIn("agnes-image-2.1-flash", agnes_items[0]["image_models"])
        self.assertIn("agnes-video-v2.0", agnes_items[0]["video_models"])

    def test_grsai_provider_uses_documented_image_endpoint_and_models(self):
        provider = {
            "id": "custom-api",
            "base_url": "https://grsai.dakka.com.cn/v1",
            "protocol": "openai",
            "model_protocols": {"nano-banana-pro": "gemini"},
        }

        self.assertTrue(main.is_grsai_provider(provider))
        self.assertEqual(main.effective_protocol(provider, "nano-banana-pro"), "openai")
        self.assertEqual(main.grsai_endpoint_url(provider, "/api/generate"), "https://grsai.dakka.com.cn/v1/api/generate")

        payload = main.grsai_models_payload()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["protocol"], "openai")
        self.assertIn("gpt-image-2", payload["image_models"])
        self.assertIn("nano-banana-pro", payload["image_models"])
        self.assertEqual(main.grsai_image_size("4096x4096", ""), "4K")
        self.assertEqual(main.grsai_image_size("3840x2160", ""), "4K")
        self.assertEqual(main.grsai_image_size("2048x1152", ""), "2K")
        self.assertEqual(main.grsai_image_size("1024x1024", "4k"), "4K")

    async def test_grsai_provider_routes_to_documented_generate_api(self):
        provider = {
            "id": "custom-api",
            "name": "grsai",
            "base_url": "https://grsai.dakka.com.cn/v1",
            "protocol": "openai",
            "model_protocols": {"nano-banana-2": "gemini"},
        }
        route = AsyncMock(return_value=({"type": "url", "value": "https://example.test/out.png"}, {"status": "succeeded"}))

        with patch.object(main, "generate_grsai_provider_image", route):
            result = await main.generate_ai_image(
                "一只狗",
                "4096x4096",
                "",
                "nano-banana-2",
                [],
                "custom-api",
                "1:1",
                "4k",
                provider_config=provider,
            )

        self.assertEqual(result[0]["type"], "url")
        route.assert_awaited_once_with("一只狗", "4096x4096", "nano-banana-2", [], provider, "1:1", "4k")

    async def test_grsai_four_k_uses_async_without_switching_model(self):
        class FakeResponse:
            def __init__(self, payload, status_code=200):
                self.payload = payload
                self.status_code = status_code
                self.text = json.dumps(payload)

            def json(self):
                return self.payload

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self):
                self.post_body = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, _url, headers=None, json=None):
                self.post_body = json
                return FakeResponse({"id": "task-1", "status": "running"})

            async def get(self, _url, headers=None, params=None):
                return FakeResponse({"status": "succeeded", "results": [{"url": "https://example.test/out.png"}]})

        provider = {
            "id": "custom-api",
            "name": "grsai",
            "base_url": "https://grsai.dakka.com.cn/v1",
            "protocol": "openai",
            "api_key": "test-key",
        }
        fake_client = FakeClient()

        with patch.object(main, "upstream_async_client", return_value=fake_client), \
             patch.object(main, "IMAGE_POLL_INTERVAL", 0):
            image, raw = await main.generate_grsai_provider_image(
                "一只狗",
                "4096x4096",
                "nano-banana-2",
                [],
                provider,
                "1:1",
                "4k",
            )

        self.assertEqual(fake_client.post_body["model"], "nano-banana-2")
        self.assertEqual(fake_client.post_body["imageSize"], "4K")
        self.assertEqual(fake_client.post_body["replyType"], "async")
        self.assertEqual(image["value"], "https://example.test/out.png")

    async def test_grsai_async_accepts_documented_numeric_task_id(self):
        class FakeResponse:
            def __init__(self, payload, status_code=200):
                self.payload = payload
                self.status_code = status_code
                self.text = json.dumps(payload)

            def json(self):
                return self.payload

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self):
                self.poll_params = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, _url, headers=None, json=None):
                return FakeResponse({"id": "6-f671fc51-d5d7-4eff-a1c7-26e612fe08ab", "status": "running"})

            async def get(self, _url, headers=None, params=None):
                self.poll_params = params
                return FakeResponse({"status": "succeeded", "results": [{"url": "https://example.test/out.png"}]})

        provider = {
            "id": "custom-api",
            "name": "grsai",
            "base_url": "https://grsai.dakka.com.cn/v1",
            "protocol": "openai",
            "api_key": "test-key",
        }
        fake_client = FakeClient()

        with patch.object(main, "upstream_async_client", return_value=fake_client), \
             patch.object(main, "IMAGE_POLL_INTERVAL", 0):
            image, _raw = await main.generate_grsai_provider_image(
                "一只狗",
                "4096x4096",
                "nano-banana-2",
                [],
                provider,
                "1:1",
                "4k",
            )

        self.assertEqual(fake_client.poll_params, {"id": "6-f671fc51-d5d7-4eff-a1c7-26e612fe08ab"})
        self.assertEqual(image["value"], "https://example.test/out.png")

    async def test_team_canvas_uses_global_api_provider_config(self):
        class Payload:
            team_id = "team-1"

        user = object()
        global_provider = {
            "id": "grsai",
            "name": "grsai",
            "base_url": "https://grsai.dakka.com.cn/v1",
            "api_key": "global-key",
        }

        with patch.object(main, "get_api_provider", return_value=global_provider) as get_provider:
            with patch.object(main, "resolve_team_api_provider_config") as team_provider:
                provider, resolved_user = await main.request_api_provider("grsai", Payload(), None, user)

        get_provider.assert_called_once_with("grsai")
        team_provider.assert_not_called()
        self.assertEqual(provider["api_key"], "global-key")
        self.assertIs(resolved_user, user)


if __name__ == "__main__":
    unittest.main()
