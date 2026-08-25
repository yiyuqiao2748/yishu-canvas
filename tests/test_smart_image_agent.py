import asyncio
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from smart_image_agent import (
    ImageAgentMessageCreate,
    ImageAgentPlanCreate,
    ImageAgentPlanUpdate,
    ImageAgentRunUpdate,
    ImageAgentSessionCreate,
    ImageAgentSessionUpdate,
    LocalSmartImageAgentStore,
    SMART_IMAGE_AGENT_MODELS,
    resolve_smart_image_agent_model,
)
from team_cloud import CurrentUser, DEFAULT_MODEL_BILLING_PRICES


class SmartImageAgentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "smart_image_agent.json"
        self.store = LocalSmartImageAgentStore(str(self.path))
        self.user = CurrentUser(id="user-1", email="artist@example.com", provider="test")
        self.other_user = CurrentUser(id="user-2", email="other@example.com", provider="test")
        self.session = self.store.create_session(
            self.user,
            ImageAgentSessionCreate(canvas_id="canvas-1", project_id="project-1", team_id="team-1"),
        )

    def tearDown(self):
        self.temp.cleanup()

    def create_plan(self, **overrides):
        values = {
            "session_id": self.session["id"],
            "message": "生成一张东方茶饮海报",
            "context": {"canvas_id": "canvas-1", "selected_images": []},
        }
        values.update(overrides)
        return self.store.create_plan(self.user, ImageAgentPlanCreate(**values))

    def test_plan_defaults_to_confirmed_nano_banana_route_without_creating_runs(self):
        plan = self.create_plan()

        self.assertEqual(plan["action"], "generate_image")
        self.assertEqual(plan["provider_id"], "custom-api")
        self.assertEqual(plan["model"], "nano-banana-2")
        self.assertEqual(plan["status"], "awaiting_confirmation")
        self.assertEqual(plan["estimated_points"], 12)
        self.assertEqual(self.store.list_runs(self.user, canvas_id="canvas-1"), [])

    def test_model_policy_contains_exactly_four_verified_routes(self):
        self.assertEqual(
            SMART_IMAGE_AGENT_MODELS,
            {
                "gpt-image-2": {"provider_id": "custom-api", "quality": "standard", "unit_points": 6},
                "nano-banana-2": {"provider_id": "custom-api", "quality": "standard", "unit_points": 12},
                "nano-banana-pro": {"provider_id": "custom-api", "quality": "pro", "unit_points": 18},
                "gpt-image-2-vip": {"provider_id": "custom-api", "quality": "vip", "unit_points": 20},
            },
        )

    def test_plan_resolution_is_validated_persisted_and_editable(self):
        plan = self.create_plan(resolution="2k")
        self.assertEqual(plan["resolution"], "2k")

        updated = self.store.update_plan(
            self.user,
            plan["id"],
            ImageAgentPlanUpdate(resolution="4k"),
        )
        self.assertEqual(updated["resolution"], "4k")

        with self.assertRaises(HTTPException) as raised:
            self.store.update_plan(
                self.user,
                plan["id"],
                ImageAgentPlanUpdate(resolution="8k"),
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_resolver_preserves_legacy_quality_defaults_when_model_is_absent(self):
        self.assertEqual(resolve_smart_image_agent_model(None, "standard"), ("nano-banana-2", "custom-api", "standard", 12))
        self.assertEqual(resolve_smart_image_agent_model(None, "pro"), ("nano-banana-pro", "custom-api", "pro", 18))

    def test_explicit_model_is_resolved_and_persisted(self):
        plan = self.create_plan(model="gpt-image-2-vip", quality="standard")

        self.assertEqual(plan["model"], "gpt-image-2-vip")
        self.assertEqual(plan["provider_id"], "custom-api")
        self.assertEqual(plan["quality"], "vip")
        self.assertEqual(plan["unit_points"], 20)

    def test_unknown_model_is_rejected_with_unprocessable_entity(self):
        with self.assertRaises(HTTPException) as error:
            self.create_plan(model="unknown-model")

        self.assertEqual(error.exception.status_code, 422)

    def test_updating_model_re_resolves_quality_provider_and_points(self):
        plan = self.create_plan()
        updated = self.store.update_plan(
            self.user,
            plan["id"],
            ImageAgentPlanUpdate(model="gpt-image-2"),
        )

        self.assertEqual(
            {updated["model"], updated["provider_id"], updated["quality"], updated["unit_points"]},
            {"gpt-image-2", "custom-api", "standard", 6},
        )

    def test_updating_vip_prompt_only_retains_existing_model_policy(self):
        plan = self.create_plan(model="gpt-image-2-vip")
        updated = self.store.update_plan(
            self.user,
            plan["id"],
            ImageAgentPlanUpdate(prompt="Make the lighting warmer"),
        )

        self.assertEqual(updated["model"], "gpt-image-2-vip")
        self.assertEqual(updated["quality"], "vip")
        self.assertEqual(updated["unit_points"], 20)
        self.assertEqual(updated["estimated_points"], 20)

    def test_high_quality_plan_uses_pro_model_and_never_an_image_fallback(self):
        plan = self.create_plan(quality="pro", count=2)

        self.assertEqual(plan["provider_id"], "custom-api")
        self.assertEqual(plan["model"], "nano-banana-pro")
        self.assertFalse(plan["fallback_used"])
        self.assertEqual(plan["estimated_points"], 36)

    def test_confirm_creates_one_queued_run_per_requested_image(self):
        plan = self.create_plan(count=3)

        confirmed = self.store.confirm_plan(self.user, plan["id"])

        self.assertEqual(confirmed["plan"]["status"], "queued")
        self.assertEqual(len(confirmed["runs"]), 3)
        self.assertEqual({run["status"] for run in confirmed["runs"]}, {"queued"})
        self.assertEqual([run["sequence"] for run in confirmed["runs"]], [1, 2, 3])

        repeated = self.store.confirm_plan(self.user, plan["id"])
        self.assertEqual([run["id"] for run in repeated["runs"]], [run["id"] for run in confirmed["runs"]])

    def test_plan_can_be_edited_before_confirmation_but_not_after(self):
        plan = self.create_plan()
        updated = self.store.update_plan(
            self.user,
            plan["id"],
            ImageAgentPlanUpdate(count=4, ratio="4:5", quality="pro"),
        )

        self.assertEqual(updated["count"], 4)
        self.assertEqual(updated["ratio"], "4:5")
        self.assertEqual(updated["model"], "nano-banana-pro")
        self.assertEqual(updated["estimated_points"], 72)

        self.store.confirm_plan(self.user, plan["id"])
        with self.assertRaises(HTTPException) as error:
            self.store.update_plan(self.user, plan["id"], ImageAgentPlanUpdate(count=2))
        self.assertEqual(error.exception.status_code, 409)

    def test_selected_image_context_infers_edit_and_reference_limit_is_enforced(self):
        plan = self.create_plan(
            message="改成雨夜霓虹环境",
            context={
                "canvas_id": "canvas-1",
                "selected_images": [{"node_id": "image-1", "url": "/image.png", "width": 1024, "height": 1024}],
            },
        )
        self.assertEqual(plan["action"], "edit_image")
        self.assertEqual(plan["source_node_ids"], ["image-1"])

        too_many = [{"node_id": f"image-{index}", "url": f"/{index}.png"} for index in range(11)]
        with self.assertRaises(HTTPException) as error:
            self.create_plan(context={"canvas_id": "canvas-1", "selected_images": too_many})
        self.assertEqual(error.exception.status_code, 422)

    def test_cancel_retry_and_result_state_transitions_are_strict(self):
        plan = self.create_plan()
        run = self.store.confirm_plan(self.user, plan["id"])["runs"][0]

        cancelled = self.store.cancel_run(self.user, run["id"])
        self.assertEqual(cancelled["status"], "cancelled")

        retried = self.store.retry_run(self.user, run["id"])
        self.assertEqual(retried["status"], "queued")
        self.assertEqual(retried["attempt"], 2)

        running = self.store.update_run(
            self.user,
            run["id"],
            ImageAgentRunUpdate(status="running"),
        )
        self.assertEqual(running["status"], "running")

        succeeded = self.store.update_run(
            self.user,
            run["id"],
            ImageAgentRunUpdate(
                status="succeeded",
                result={"url": "/result.png", "preview_url": "/result-512.webp", "target_node_id": "node-result"},
            ),
        )
        self.assertEqual(succeeded["status"], "succeeded")
        self.assertEqual(succeeded["result"]["target_node_id"], "node-result")
        self.assertEqual(len(self.store.list_results(self.user, self.session["id"])), 1)

        with self.assertRaises(HTTPException) as error:
            self.store.cancel_run(self.user, run["id"])
        self.assertEqual(error.exception.status_code, 409)

    def test_sessions_and_runs_are_scoped_by_user_and_canvas(self):
        plan = self.create_plan()
        self.store.confirm_plan(self.user, plan["id"])

        with self.assertRaises(HTTPException) as session_error:
            self.store.get_session(self.other_user, self.session["id"])
        self.assertEqual(session_error.exception.status_code, 404)

        self.assertEqual(self.store.list_runs(self.user, canvas_id="canvas-2"), [])
        self.assertEqual(len(self.store.list_runs(self.user, canvas_id="canvas-1")), 1)

    def test_message_context_keeps_only_persistable_image_references(self):
        message = self.store.add_message(
            self.user,
            self.session["id"],
            ImageAgentMessageCreate(
                content="继续修改",
                context={
                    "canvas_id": "canvas-1",
                    "unexpected": {"raw": "do-not-store"},
                    "selected_images": [{"node_id": "image-1", "url": "/assets/image.png", "width": "1024"}],
                },
            ),
        )

        self.assertNotIn("unexpected", message["context"])
        self.assertEqual(message["context"]["selected_images"][0]["width"], 1024)

        with self.assertRaises(HTTPException) as error:
            self.store.add_message(
                self.user,
                self.session["id"],
                ImageAgentMessageCreate(
                    content="继续修改",
                    context={"selected_images": [{"node_id": "image-2", "url": "data:image/png;base64,AAAA"}]},
                ),
            )
        self.assertEqual(error.exception.status_code, 422)

    def test_sessions_have_titles_can_be_archived_and_stay_scoped_to_canvas(self):
        self.store.add_message(
            self.user,
            self.session["id"],
            ImageAgentMessageCreate(content="Create a premium tea poster", context={"canvas_id": "canvas-1"}),
        )
        other_canvas = self.store.create_session(self.user, ImageAgentSessionCreate(canvas_id="canvas-2"))
        other_user = self.store.create_session(self.other_user, ImageAgentSessionCreate(canvas_id="canvas-1"))

        sessions = self.store.list_sessions(self.user, "canvas-1")
        self.assertEqual([item["id"] for item in sessions], [self.session["id"]])
        self.assertEqual(sessions[0]["title"], "Create a premium tea poster")
        self.assertNotIn(other_canvas["id"], [item["id"] for item in sessions])
        self.assertNotIn(other_user["id"], [item["id"] for item in sessions])

        archived = self.store.update_session(
            self.user,
            self.session["id"],
            ImageAgentSessionUpdate(archived=True),
        )
        self.assertTrue(archived["archived_at"])
        self.assertEqual(self.store.list_sessions(self.user, "canvas-1"), [])
        self.assertEqual(self.store.list_sessions(self.user, "canvas-1", include_archived=True)[0]["id"], self.session["id"])

    def test_plan_assigns_reference_roles_and_requires_one_decision_at_a_time(self):
        plan = self.create_plan(
            message="Edit this image into a rainy neon scene",
            context={"canvas_id": "canvas-1", "selected_images": [
                {"node_id": "image-1", "url": "/one.png"},
                {"node_id": "image-2", "url": "/two.png"},
            ]},
        )
        self.assertEqual(plan["action"], "compose_images")
        self.assertEqual([item["role"] for item in plan["references"]], ["primary", "reference"])

        with self.assertRaises(HTTPException) as error:
            self.create_plan(message="Make another plan")
        self.assertEqual(error.exception.status_code, 409)

        dismissed = self.store.update_plan(self.user, plan["id"], ImageAgentPlanUpdate(status="cancelled"))
        self.assertEqual(dismissed["status"], "cancelled")
        replacement = self.create_plan(message="Make another plan")
        self.assertEqual(replacement["status"], "awaiting_confirmation")

    def test_pending_plan_and_session_access_are_scoped_to_the_same_canvas(self):
        self.create_plan(message="Create a first plan")
        second_session = self.store.create_session(self.user, ImageAgentSessionCreate(canvas_id="canvas-1"))
        with self.assertRaises(HTTPException) as plan_error:
            self.store.create_plan(self.user, ImageAgentPlanCreate(
                session_id=second_session["id"], message="Create a competing plan", context={"canvas_id": "canvas-1"},
            ))
        self.assertEqual(plan_error.exception.status_code, 409)

        with self.assertRaises(HTTPException) as get_error:
            self.store.get_session(self.user, self.session["id"], canvas_id="canvas-2")
        self.assertEqual(get_error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as update_error:
            self.store.update_session(self.user, self.session["id"], ImageAgentSessionUpdate(title="wrong canvas"), canvas_id="canvas-2")
        self.assertEqual(update_error.exception.status_code, 404)


class SmartImageAgentApiTests(unittest.TestCase):
    def setUp(self):
        import main

        self.main = main
        self.temp = tempfile.TemporaryDirectory()
        self.store = LocalSmartImageAgentStore(str(Path(self.temp.name) / "agent.json"))
        self.user = CurrentUser(id="api-user", email="api@example.com", provider="test")
        self.original_store = main.SMART_IMAGE_AGENT_STORE
        main.SMART_IMAGE_AGENT_STORE = self.store
        main.app.dependency_overrides[main.require_user] = lambda: self.user
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        self.main.app.dependency_overrides.clear()
        self.main.SMART_IMAGE_AGENT_STORE = self.original_store
        self.temp.cleanup()

    def test_api_requires_confirmation_before_runs_exist(self):
        session_response = self.client.post(
            "/api/smart-image-agent/sessions",
            json={"canvas_id": "canvas-api", "project_id": "project-api"},
        )
        self.assertEqual(session_response.status_code, 200)
        session = session_response.json()

        message_response = self.client.post(
            f"/api/smart-image-agent/sessions/{session['id']}/messages",
            json={"content": "做四张餐饮封面", "context": {"canvas_id": "canvas-api"}},
        )
        self.assertEqual(message_response.status_code, 200)

        plan_response = self.client.post(
            "/api/smart-image-agent/plans",
            json={
                "session_id": session["id"],
                "message": "做四张餐饮封面",
                "count": 4,
                "ratio": "4:5",
                "context": {"canvas_id": "canvas-api"},
            },
        )
        self.assertEqual(plan_response.status_code, 200)
        plan = plan_response.json()
        self.assertEqual(plan["status"], "awaiting_confirmation")
        self.assertEqual(plan["action"], "generate_image_set")

        runs_before = self.client.get("/api/smart-image-agent/runs?canvas_id=canvas-api").json()
        self.assertEqual(runs_before, {"runs": []})

        confirmed = self.client.post(f"/api/smart-image-agent/plans/{plan['id']}/confirm")
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(len(confirmed.json()["runs"]), 4)

    def test_api_confirms_all_four_policy_models_as_queued_runs(self):
        expected = {
            "gpt-image-2": 6,
            "nano-banana-2": 12,
            "nano-banana-pro": 18,
            "gpt-image-2-vip": 20,
        }

        for model, unit_points in expected.items():
            with self.subTest(model=model):
                canvas_id = f"canvas-{model}"
                session = self.client.post(
                    "/api/smart-image-agent/sessions",
                    json={"canvas_id": canvas_id},
                ).json()
                plan_response = self.client.post(
                    "/api/smart-image-agent/plans",
                    json={
                        "session_id": session["id"],
                        "message": f"Create with {model}",
                        "context": {"canvas_id": canvas_id},
                        "model": model,
                        "count": 2,
                    },
                )
                self.assertEqual(plan_response.status_code, 200)
                plan = plan_response.json()
                self.assertEqual(plan["provider_id"], "custom-api")
                self.assertEqual(plan["estimated_points"], unit_points * 2)

                confirmed = self.client.post(f"/api/smart-image-agent/plans/{plan['id']}/confirm")

                self.assertEqual(confirmed.status_code, 200)
                payload = confirmed.json()
                self.assertEqual(payload["plan"]["status"], "queued")
                self.assertEqual(len(payload["runs"]), 2)
                self.assertTrue(all(run["status"] == "queued" for run in payload["runs"]))
                self.assertTrue(all(run["provider_id"] == "custom-api" for run in payload["runs"]))
                self.assertTrue(all(run["model"] == model for run in payload["runs"]))

    def test_smart_image_policy_matches_shared_default_billing(self):
        expected = {
            model: policy["unit_points"]
            for model, policy in SMART_IMAGE_AGENT_MODELS.items()
        }

        for provider_id in ("custom-api", "grsai"):
            with self.subTest(provider_id=provider_id):
                actual = {
                    item["model"]: item["points_cost"]
                    for item in DEFAULT_MODEL_BILLING_PRICES
                    if item["provider_id"] == provider_id and item["operation_type"] == "image"
                }
                self.assertEqual(actual, expected)

    def test_capabilities_expose_models_points_and_resolutions(self):
        response = self.client.get("/api/smart-image-agent/capabilities")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_model"], "nano-banana-2")
        self.assertEqual(payload["default_resolution"], "1k")
        self.assertEqual(
            {item["id"]: item["unit_points"] for item in payload["models"]},
            {
                "gpt-image-2": 6,
                "nano-banana-2": 12,
                "nano-banana-pro": 18,
                "gpt-image-2-vip": 20,
            },
        )
        self.assertTrue(all(item["resolutions"] == ["1k", "2k", "4k"] for item in payload["models"]))

    def test_api_accepts_vip_quality_for_create_update_and_dismissal(self):
        session = self.client.post(
            "/api/smart-image-agent/sessions",
            json={"canvas_id": "canvas-api"},
        ).json()
        vip_payload = {"model": "gpt-image-2-vip", "quality": "vip"}
        created = self.client.post(
            "/api/smart-image-agent/plans",
            json={
                "session_id": session["id"],
                "message": "Create a VIP product image",
                "context": {"canvas_id": "canvas-api"},
                **vip_payload,
            },
        )
        self.assertEqual(created.status_code, 200)
        plan = created.json()
        self.assertEqual((plan["model"], plan["quality"], plan["unit_points"], plan["estimated_points"]),
                         ("gpt-image-2-vip", "vip", 20, 20))

        updated = self.client.patch(
            f"/api/smart-image-agent/plans/{plan['id']}",
            json={"prompt": "Make the lighting warmer", **vip_payload},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual((updated.json()["model"], updated.json()["unit_points"]), ("gpt-image-2-vip", 20))

        dismissed = self.client.patch(
            f"/api/smart-image-agent/plans/{plan['id']}",
            json={"status": "cancelled", **vip_payload},
        )
        self.assertEqual(dismissed.status_code, 200)
        self.assertEqual((dismissed.json()["status"], dismissed.json()["model"], dismissed.json()["estimated_points"]),
                         ("cancelled", "gpt-image-2-vip", 20))

    def test_api_run_updates_are_scoped_and_results_are_restored(self):
        session = self.client.post(
            "/api/smart-image-agent/sessions",
            json={"canvas_id": "canvas-api"},
        ).json()
        plan = self.client.post(
            "/api/smart-image-agent/plans",
            json={"session_id": session["id"], "message": "生成一张海报", "context": {"canvas_id": "canvas-api"}},
        ).json()
        run = self.client.post(f"/api/smart-image-agent/plans/{plan['id']}/confirm").json()["runs"][0]

        started = self.client.patch(
            f"/api/smart-image-agent/runs/{run['id']}",
            json={"status": "running"},
        )
        self.assertEqual(started.status_code, 200)
        completed = self.client.patch(
            f"/api/smart-image-agent/runs/{run['id']}",
            json={"status": "succeeded", "result": {"url": "/result.png", "target_node_id": "node-1"}},
        )
        self.assertEqual(completed.status_code, 200)

        results = self.client.get(f"/api/smart-image-agent/sessions/{session['id']}/results?canvas_id=canvas-api")
        self.assertEqual(results.status_code, 200)
        self.assertEqual(results.json()["results"][0]["target_node_id"], "node-1")

    def test_api_lists_and_updates_canvas_sessions(self):
        first = self.client.post(
            "/api/smart-image-agent/sessions",
            json={"canvas_id": "canvas-api", "title": "First concept"},
        ).json()
        second = self.client.post(
            "/api/smart-image-agent/sessions",
            json={"canvas_id": "canvas-api", "title": "Second concept"},
        ).json()

        listed = self.client.get("/api/smart-image-agent/sessions?canvas_id=canvas-api")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.json()["sessions"]], [second["id"], first["id"]])

        archived = self.client.patch(
            f"/api/smart-image-agent/sessions/{second['id']}?canvas_id=canvas-api",
            json={"archived": True},
        )
        self.assertEqual(archived.status_code, 200)
        remaining = self.client.get("/api/smart-image-agent/sessions?canvas_id=canvas-api").json()["sessions"]
        self.assertEqual([item["id"] for item in remaining], [first["id"]])

    def test_api_rejects_cross_canvas_session_access(self):
        session = self.client.post("/api/smart-image-agent/sessions", json={"canvas_id": "canvas-api"}).json()
        wrong_get = self.client.get(f"/api/smart-image-agent/sessions/{session['id']}?canvas_id=other-canvas")
        self.assertEqual(wrong_get.status_code, 404)
        wrong_patch = self.client.patch(
            f"/api/smart-image-agent/sessions/{session['id']}?canvas_id=other-canvas",
            json={"archived": True},
        )
        self.assertEqual(wrong_patch.status_code, 404)
        wrong_results = self.client.get(
            f"/api/smart-image-agent/sessions/{session['id']}/results?canvas_id=other-canvas",
        )
        self.assertEqual(wrong_results.status_code, 404)


class SmartImageAgentStaticIsolationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def test_smart_canvas_uses_isolated_loader_while_classic_keeps_legacy_agent(self):
        smart_html = (self.root / "static" / "smart-canvas.html").read_text(encoding="utf-8")
        classic_html = (self.root / "static" / "canvas.html").read_text(encoding="utf-8")

        self.assertIn("/static/css/smart-image-agent.css", smart_html)
        self.assertIn("/static/js/smart-image-agent/loader.js", smart_html)
        self.assertNotIn('<script src="/static/js/canvas-agent-loader.js', smart_html)
        self.assertIn('<script src="/static/js/canvas-agent-loader.js', classic_html)
        self.assertNotIn("smart-image-agent", classic_html)

    def test_smart_bridge_exposes_only_stable_canvas_operations(self):
        smart_script = (self.root / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("window.SmartImageAgentBridge", smart_script)
        for method in (
            "getCanvasContext",
            "getSelection",
            "subscribeSelection",
            "createGenerationGroup",
            "runImageTask",
            "placeResults",
            "focusNode",
            "saveCanvas",
        ):
            self.assertIn(f"{method}:", smart_script)

    def test_new_agent_is_image_only_and_requires_explicit_confirmation(self):
        loader = (self.root / "static" / "js" / "smart-image-agent" / "loader.js").read_text(encoding="utf-8")
        app = (self.root / "static" / "js" / "smart-image-agent" / "app.js").read_text(encoding="utf-8")

        self.assertIn("image_agent", loader)
        self.assertIn("canvas-agent-loader.js", loader)
        self.assertIn("/api/smart-image-agent/plans", app)
        self.assertIn("/confirm", app)
        self.assertIn("SmartImageAgentBridge.runImageTask", app)
        self.assertNotIn("canvas-agent/suggest", app)
        self.assertNotIn("generate_video", app)
        self.assertNotIn("agnes-video", app.lower())

    def test_create_plan_waits_for_session_initialization(self):
        app = (self.root / "static" / "js" / "smart-image-agent" / "app.js").read_text(encoding="utf-8")

        self.assertIn("data-create disabled", app)
        self.assertIn("if(!state.session) await ensureSession();", app)
        self.assertNotIn("panel-right-close", app)
        self.assertNotIn("panel-right-open", app)

    def test_hidden_agent_controls_cannot_be_forced_visible_by_component_styles(self):
        styles = (self.root / "static" / "css" / "smart-image-agent.css").read_text(encoding="utf-8")

        self.assertIn(".smart-image-agent [hidden]", styles)
        self.assertIn("display:none!important", styles.replace(" ", ""))

    def test_fixed_composer_uses_the_four_model_policy_and_keeps_activity_scrollable(self):
        app = (self.root / "static" / "js" / "smart-image-agent" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "static" / "css" / "smart-image-agent.css").read_text(encoding="utf-8")

        self.assertIn('class="sia-activity"', app)
        self.assertIn('class="sia-composer"', app)
        self.assertIn('model:els.model.value', app)
        self.assertIn('model:field === \'model\' ? value : state.currentPlan.model', app)
        self.assertEqual(
            re.findall(r"\{id:'([^']+)', label:'([^']+)', cost:(\d+), quality:'([^']+)'\}", app),
            [
                ("gpt-image-2", "GPT Image 2", "6", "standard"),
                ("nano-banana-2", "Nano Banana 2", "12", "standard"),
                ("nano-banana-pro", "Nano Banana Pro", "18", "pro"),
                ("gpt-image-2-vip", "GPT Image 2 VIP", "20", "vip"),
            ],
        )
        self.assertIn('.sia-activity { flex:1; min-height:0; overflow:auto;', styles)
        self.assertIn('.sia-composer { flex:0 0 auto;', styles)
        self.assertIn('.sia-notice { position:absolute; left:12px; right:12px; bottom:calc(100% + 12px);', styles)

    def test_reference_limit_is_reported_instead_of_silently_truncating_inputs(self):
        app = (self.root / "static" / "js" / "smart-image-agent" / "app.js").read_text(encoding="utf-8")
        bridge = (self.root / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("if(references.length > 10)", app)
        self.assertNotIn("}).slice(0, 10);", app)
        self.assertNotIn("return references.slice(0, 10);", bridge)
        self.assertNotIn("filter(item => item.kind === 'image').slice(0, 10)", bridge)

    def test_agent_composer_adds_selected_canvas_images_and_resolution(self):
        app = (self.root / "static" / "js" / "smart-image-agent" / "app.js").read_text(encoding="utf-8")
        smart = (self.root / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("data-add-selection", app)
        self.assertIn("data-resolution", app)
        self.assertIn("resolution:plan.resolution", smart)
        self.assertIn("resolution:plan.resolution || '1k'", smart)

    def test_smart_image_agent_generation_guard_allows_exact_policy_models(self):
        smart_script = (self.root / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")
        guard = re.search(
            r"async function smartImageAgentRunImageTask\(run, plan, options=\{\}\)\{\s*"
            r"if\(plan\?\.provider_id !== 'custom-api' \|\| (?P<models>.*?)\)\{",
            smart_script,
            re.DOTALL,
        )
        self.assertIsNotNone(guard)
        self.assertEqual(
            set(re.findall(r"'([^']+)'", guard.group("models"))),
            {"gpt-image-2", "nano-banana-2", "nano-banana-pro", "gpt-image-2-vip"},
        )
        self.assertIn("图片 Agent 仅支持已配置的四个图片模型", smart_script)

    def test_smart_bridge_exposes_only_verified_canvas_controls(self):
        smart = (self.root / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")
        app = (self.root / "static" / "js" / "smart-image-agent" / "app.js").read_text(encoding="utf-8")
        expected = {"fitAll", "zoomIn", "zoomOut", "resetZoom", "arrangeSelection"}
        bridge = re.search(
            r"canvasControls:Object\.freeze\(\{(?P<body>.*?)^\s*\}\),",
            smart,
            re.DOTALL | re.MULTILINE,
        )

        self.assertIsNotNone(bridge)
        self.assertEqual(
            set(re.findall(r"^\s*(\w+)\s*:", bridge.group("body"), re.MULTILINE)),
            expected,
        )
        self.assertEqual(
            re.findall(r'data-canvas-control="([^"]+)"', app),
            ["fitAll", "zoomIn", "zoomOut", "resetZoom", "arrangeSelection"],
        )
        self.assertEqual(set(re.findall(r"canvasControls\.(\w+)", app)), expected)

        classic = (self.root / "static" / "canvas.html").read_text(encoding="utf-8")
        self.assertNotIn("canvasControls", classic)

    def test_canvas_controls_preserve_viewport_center_when_zooming(self):
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv.at(-1), 'utf8');

function extractFunction(name) {
    const start = source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `missing ${name}`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for(let index = open; index < source.length; index++) {
        if(source[index] === '{') depth++;
        if(source[index] === '}' && --depth === 0) return source.slice(start, index + 1);
    }
    throw new Error(`unclosed ${name}`);
}
function extractCanvasControls() {
    const start = source.indexOf('canvasControls:Object.freeze({');
    assert.notEqual(start, -1, 'missing canvasControls');
    const open = source.indexOf('{', start);
    let depth = 0;
    for(let index = open; index < source.length; index++) {
        if(source[index] === '{') depth++;
        if(source[index] === '}' && --depth === 0) return source.slice(open + 1, index);
    }
    throw new Error('unclosed canvasControls');
}

const context = {
    assert,
    viewport:{x:140, y:-80, scale:0.8},
    shell:{clientWidth:1000, clientHeight:600},
    applyViewport(){},
    scheduleSave(){},
    fitAllNodesViewport(){},
    arrangeSelectedSmartNodes(){}
};
vm.createContext(context);
vm.runInContext(`${extractFunction('viewportCenter')}\n${extractFunction('centerViewportOnWorldPoint')}\nconst canvasControls = Object.freeze({${extractCanvasControls()}});`, context);
vm.runInContext(`
    const center = () => ({
        x:(shell.clientWidth / 2 - viewport.x) / viewport.scale,
        y:(shell.clientHeight / 2 - viewport.y) / viewport.scale
    });
    const assertStableCenter = (action, expectedScale) => {
        const before = center();
        action();
        assert.ok(Math.abs(viewport.scale - expectedScale) < 1e-9, 'unexpected zoom scale');
        const after = center();
        assert.ok(Math.abs(after.x - before.x) < 1e-9, 'world x at viewport center changed');
        assert.ok(Math.abs(after.y - before.y) < 1e-9, 'world y at viewport center changed');
    };
    assertStableCenter(canvasControls.zoomIn, 0.92);
    assertStableCenter(canvasControls.zoomOut, 0.8);
    assertStableCenter(canvasControls.resetZoom, 1);
`, context);
'''
        completed = subprocess.run(
            ["node", "-e", script, str(self.root / "static" / "js" / "smart-canvas.js")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_arrange_selection_repositions_two_selected_nodes(self):
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv.at(-1), 'utf8');

function extractFunction(name) {
    const start = source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `missing ${name}`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for(let index = open; index < source.length; index++) {
        if(source[index] === '{') depth++;
        if(source[index] === '}' && --depth === 0) return source.slice(start, index + 1);
    }
    throw new Error(`unclosed ${name}`);
}

const context = {
    assert,
    nodes:[
        {id:'source', x:520, y:320, w:180, h:110},
        {id:'result', x:40, y:740, w:180, h:110}
    ],
    canvas:{connections:[{from:'source', to:'result'}]},
    selectedNodeIds:() => ['source', 'result'],
    smartArrangeAtomicIds:ids => ids,
    connectedSmartClusterIds:id => [id],
    nodeRect:node => ({x:node.x, y:node.y, width:node.w, height:node.h}),
    translateSmartNodeWithMembers:(node, dx, dy) => { node.x += dx; node.y += dy; },
    pushUndo(){},
    render(){},
    scheduleSave(){},
    toast(){}
};
vm.createContext(context);
vm.runInContext(`${extractFunction('moveSmartNodeAtom')}\n${extractFunction('arrangeSmartIdsByConnections')}\n${extractFunction('arrangeSelectedSmartNodes')}`, context);
vm.runInContext(`
    const before = nodes.map(({id, x, y}) => ({id, x, y}));
    arrangeSelectedSmartNodes();
    assert.notDeepEqual(nodes.map(({id, x, y}) => ({id, x, y})), before);
    assert.equal(JSON.stringify(nodes.map(({id, x, y}) => ({id, x, y}))), JSON.stringify([
        {id:'source', x:40, y:320},
        {id:'result', x:400, y:320}
    ]));
`, context);
'''
        completed = subprocess.run(
            ["node", "-e", script, str(self.root / "static" / "js" / "smart-canvas.js")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_session_restore_only_resumes_runs_with_loaded_plans(self):
        app = (self.root / "static" / "js" / "smart-image-agent" / "app.js").read_text(encoding="utf-8")

        self.assertIn("/api/smart-image-agent/runs?session_id=", app)
        self.assertNotIn("/api/smart-image-agent/runs?canvas_id=", app)

    def test_session_transitions_clear_transient_composer_state(self):
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv.at(-1), 'utf8');

function extractFunction(name) {
    const asyncStart = source.indexOf(`async function ${name}(`);
    const start = asyncStart >= 0 ? asyncStart : source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `missing ${name}`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for(let index = open; index < source.length; index++) {
        if(source[index] === '{') depth++;
        if(source[index] === '}' && --depth === 0) return source.slice(start, index + 1);
    }
    throw new Error(`unclosed ${name}`);
}

const state = {
    session:{id:'session-old'}, plans:new Map([['plan-old', {}]]), currentPlan:{id:'plan-old'},
    runs:[{id:'run-old'}], results:[{run_id:'result-old'}], manualRefs:[{url:'old-ref'}],
    referenceRoles:new Map([['old-ref', 'edit_target']]), selectedResultGroup:[{run_id:'result-old'}],
    pendingAction:'create_variants'
};
const els = {
    sessionHistory:{hidden:false}, input:{value:'old prompt', focus(){}},
};
const context = {
    state, els,
    writeSetting(){},
    async loadSession(){ state.session = {id:'session-new'}; },
    renderReferences(){}, renderPlan(){}, renderTasks(){}, renderResults(){}, notify(){}
};
vm.createContext(context);
vm.runInContext([
    extractFunction('resetSessionTransientState'),
    extractFunction('switchSession'),
    extractFunction('createNewSession')
].join('\n'), context);

function seedTransientState() {
    state.manualRefs = [{url:'old-ref'}];
    state.referenceRoles = new Map([['old-ref', 'edit_target']]);
    state.selectedResultGroup = [{run_id:'result-old'}];
    state.pendingAction = 'create_variants';
}
function assertTransientStateCleared() {
    assert.equal(state.manualRefs.length, 0);
    assert.equal(state.referenceRoles.size, 0);
    assert.equal(state.selectedResultGroup.length, 0);
    assert.equal(state.pendingAction, '');
}

(async () => {
    await vm.runInContext(`switchSession('session-new')`, context);
    assertTransientStateCleared();

    seedTransientState();
    state.session = {id:'session-new'};
    await vm.runInContext('createNewSession()', context);
    assertTransientStateCleared();
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        completed = subprocess.run(
            ["node", "-e", script, str(self.root / "static" / "js" / "smart-image-agent" / "app.js")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_completed_run_does_not_append_result_to_a_different_session(self):
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv.at(-1), 'utf8');

function extractFunction(name) {
    const asyncStart = source.indexOf(`async function ${name}(`);
    const start = asyncStart >= 0 ? asyncStart : source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `missing ${name}`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for(let index = open; index < source.length; index++) {
        if(source[index] === '{') depth++;
        if(source[index] === '}' && --depth === 0) return source.slice(start, index + 1);
    }
    throw new Error(`unclosed ${name}`);
}

const oldRun = {id:'run-old', plan_id:'plan-old', session_id:'session-old', status:'queued'};
const state = {
    session:{id:'session-old'}, plans:new Map([['plan-old', {id:'plan-old'}]]),
    runs:[oldRun], results:[], activeRuns:0, cancelled:new Set()
};
let renderedResults = 0;
const context = {
    state,
    async api(_path, options={}) {
        return {...oldRun, ...JSON.parse(options.body || '{}')};
    },
    renderTasks(){},
    renderResults(){ renderedResults += 1; },
    processQueue(){},
    global:{SmartImageAgentBridge:{
        async runImageTask() {
            state.session = {id:'session-new'};
            state.runs = [];
            state.results = [{run_id:'result-new', session_id:'session-new'}];
            return {url:'old-result.png'};
        },
        async saveCanvas() {}
    }}
};
vm.createContext(context);
vm.runInContext(extractFunction('processRun'), context);

(async () => {
    await vm.runInContext('processRun(state.runs[0])', context);
    assert.deepEqual(state.results, [{run_id:'result-new', session_id:'session-new'}]);
    assert.equal(renderedResults, 0);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        completed = subprocess.run(
            ["node", "-e", script, str(self.root / "static" / "js" / "smart-image-agent" / "app.js")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_backend_namespace_and_supabase_schema_are_isolated(self):
        main_source = (self.root / "main.py").read_text(encoding="utf-8")
        service_source = (self.root / "smart_image_agent.py").read_text(encoding="utf-8")
        schema = (self.root / "docs" / "supabase" / "team_cloud_schema.sql").read_text(encoding="utf-8")
        migration = (self.root / "docs" / "supabase" / "smart_image_agent_v2.sql").read_text(encoding="utf-8")

        for path in (
            "/api/smart-image-agent/sessions",
            "/api/smart-image-agent/plans",
            "/api/smart-image-agent/runs",
        ):
            self.assertIn(path, main_source)
        for table in (
            "smart_image_agent_sessions",
            "smart_image_agent_messages",
            "smart_image_agent_plans",
            "smart_image_agent_runs",
        ):
            self.assertIn(f"create table if not exists public.{table}", schema)
            self.assertIn(f"grant all on table public.{table} to service_role", schema)
            self.assertIn(f"create table if not exists public.{table}", migration)
        self.assertIn('"references" jsonb not null default \'[]\'::jsonb', schema)
        self.assertIn('"references" jsonb not null default \'[]\'::jsonb', migration)
        self.assertIn('SMART_IMAGE_AGENT_PROVIDER = "custom-api"', service_source)
        self.assertIn('SMART_IMAGE_AGENT_STANDARD_MODEL = "nano-banana-2"', service_source)
        self.assertIn('SMART_IMAGE_AGENT_PRO_MODEL = "nano-banana-pro"', service_source)
        self.assertNotIn("AGENT_FALLBACK_PROVIDER", service_source)

    def test_v2_creation_path_includes_sessions_roles_and_single_plan_focus(self):
        main_source = (self.root / "main.py").read_text(encoding="utf-8")
        service_source = (self.root / "smart_image_agent.py").read_text(encoding="utf-8")
        app = (self.root / "static" / "js" / "smart-image-agent" / "app.js").read_text(encoding="utf-8")
        migration = (self.root / "docs" / "supabase" / "smart_image_agent_v2.sql").read_text(encoding="utf-8")

        self.assertIn('"/api/smart-image-agent/sessions"', main_source)
        self.assertIn('ImageAgentSessionUpdate', service_source)
        self.assertIn('assign_reference_roles', service_source)
        self.assertIn('data-session-history', app)
        self.assertIn('data-dismiss-plan', app)
        self.assertIn('data-reference-role', app)
        self.assertIn('canvas_id=${encodeURIComponent(context.canvas_id)}', app)
        self.assertLess(migration.index('add column if not exists last_activity_at'), migration.index('idx_smart_image_agent_sessions_history'))


if __name__ == "__main__":
    unittest.main()
