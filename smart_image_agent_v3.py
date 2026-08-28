import datetime
import json
import os
import secrets
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import HTTPException
from pydantic import BaseModel, Field

from smart_image_agent import (
    ImageAgentMessageCreate,
    ImageAgentPlanCreate,
    ImageAgentPlanUpdate,
    SMART_IMAGE_AGENT_ACTIONS,
    infer_image_action,
    normalize_message_context,
    utc_now,
)
from team_cloud import CurrentUser


SMART_IMAGE_AGENT_V3_PROTOCOL_VERSION = "1"
SMART_IMAGE_AGENT_V3_POLICY_VERSION = "v3-initial"
SMART_IMAGE_AGENT_V3_EVENT_TYPES = {
    "context.ready",
    "plan.proposed",
    "plan.updated",
    "approval.requested",
    "approval.decided",
    "tool.started",
    "tool.progressed",
    "tool.completed",
    "tool.failed",
    "tool.cancelled",
    "artifact.created",
    "execution.completed",
}
SMART_IMAGE_AGENT_V3_EXECUTION_STATES = {
    "awaiting_confirmation",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
}


def is_smart_image_agent_v3_rollout_enabled(team_id: str, enabled_teams: str, allow_all: bool) -> bool:
    if allow_all:
        return True
    teams = {item.strip() for item in str(enabled_teams or "").split(",") if item.strip()}
    return str(team_id or "") in teams


class ImageAgentV3ExecutionCreate(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=12000)
    context: Dict[str, Any] = Field(default_factory=dict)
    action: str = Field("", max_length=80)
    prompt: str = Field("", max_length=12000)
    ratio: str = Field("auto", max_length=20)
    resolution: str = Field("1k", max_length=8)
    count: int = Field(1, ge=1, le=8)
    quality: str = Field("standard", pattern="^(standard|pro|vip)$")
    model: Optional[str] = Field(None, max_length=120)


class ImageAgentV3PlanUpdate(BaseModel):
    prompt: Optional[str] = Field(None, min_length=1, max_length=12000)
    ratio: Optional[str] = Field(None, max_length=20)
    resolution: Optional[str] = Field(None, max_length=8)
    count: Optional[int] = Field(None, ge=1, le=8)
    quality: Optional[str] = Field(None, pattern="^(standard|pro|vip)$")
    model: Optional[str] = Field(None, max_length=120)


class ImageAgentV3Approval(BaseModel):
    idempotency_key: str = Field(..., min_length=16, max_length=200)


class ImageAgentV3FeedbackCreate(BaseModel):
    kind: str = Field(..., pattern="^(adopted|plan_edited|dismissed|cancelled|retried|rated|continued|failed)$")
    rating: Optional[int] = Field(None, ge=1, le=5)
    reason: str = Field("", max_length=2000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class AgentCapability:
    id: str
    input_schema: Dict[str, Any]
    approval: str
    idempotency_scope: str

    def build_preview(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "action": plan["action"],
            "prompt": plan["prompt"],
            "references": plan.get("references") or [],
            "model": plan["model"],
            "ratio": plan["ratio"],
            "resolution": plan["resolution"],
            "count": plan["count"],
            "estimated_points": plan["estimated_points"],
        }

    def execute(self, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"dispatch": "smart_canvas_bridge", "run_ids": [item["id"] for item in runs]}

    def result_renderer(self, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: result[key]
            for key in ("url", "preview_url", "target_node_id", "asset_id")
            if result.get(key)
        }


class CapabilityRegistry:
    def __init__(self):
        image_capabilities = {
            "generate_image",
            "edit_image",
            "compose_images",
            "create_variants",
            "expand_image",
            "generate_image_set",
        }
        asset_capabilities = {"upload_reference", "add_asset_reference", "save_generated_result"}
        canvas_capabilities = {"focus_result", "fit_all", "zoom_in", "zoom_out", "reset_zoom", "arrange_selection"}
        self._items = {
            capability_id: AgentCapability(
                id=capability_id,
                input_schema={"type": "object"},
                approval="plan_confirmation" if capability_id in image_capabilities else "none",
                idempotency_scope="execution" if capability_id in image_capabilities else "canvas_action",
            )
            for capability_id in image_capabilities | asset_capabilities | canvas_capabilities
        }

    def get(self, capability_id: str) -> AgentCapability:
        capability = self._items.get(str(capability_id or ""))
        if not capability:
            raise HTTPException(status_code=422, detail="Unsupported Smart Image Agent v3 capability")
        return capability

    def ids(self) -> List[str]:
        return sorted(self._items)


class ContextBuilder:
    def build(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return normalize_message_context(context)


class Planner:
    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def build_plan(self, payload: ImageAgentV3ExecutionCreate, context: Dict[str, Any]) -> ImageAgentPlanCreate:
        action = str(payload.action or "").strip() or infer_image_action(payload.message, context)
        if not payload.action and payload.count > 1 and action == "generate_image":
            action = "generate_image_set"
        if action not in SMART_IMAGE_AGENT_ACTIONS:
            raise HTTPException(status_code=422, detail="Unsupported image Agent action")
        self.registry.get(action)
        return ImageAgentPlanCreate(
            session_id=payload.session_id,
            message=payload.message,
            context=context,
            action=action,
            prompt=payload.prompt,
            ratio=payload.ratio,
            resolution=payload.resolution,
            count=payload.count,
            quality=payload.quality,
            model=payload.model,
        )


class ApprovalGate:
    @staticmethod
    def require(execution: Dict[str, Any], idempotency_key: str) -> None:
        expected = str(execution.get("approval_key") or "")
        if not expected or not secrets.compare_digest(expected, str(idempotency_key or "")):
            raise HTTPException(status_code=409, detail="Invalid Smart Image Agent v3 approval key")


class OrchestratorAdapter:
    """Reserved boundary for future long-running orchestration; no runtime dependency today."""

    def dispatch(self, execution: Dict[str, Any], runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"execution_id": execution["id"], "run_ids": [item["id"] for item in runs]}


def build_smart_image_agent_v3_metrics(
    executions: List[Dict[str, Any]],
    feedback: List[Dict[str, Any]],
) -> Dict[str, Any]:
    total = len(executions)
    confirmed = [item for item in executions if item.get("approved_idempotency_key")]
    terminal = [item for item in executions if item.get("status") in {"succeeded", "failed", "cancelled"}]
    feedback_counts: Dict[str, int] = {}
    for item in feedback:
        kind = str(item.get("kind") or "")
        if kind:
            feedback_counts[kind] = feedback_counts.get(kind, 0) + 1
    model_costs: Dict[str, Dict[str, Any]] = {}
    run_counts: Dict[str, int] = {}
    for item in confirmed:
        billing = item.get("billing_intent") if isinstance(item.get("billing_intent"), dict) else {}
        model = str(billing.get("model") or "")
        if model:
            summary = model_costs.setdefault(model, {"model": model, "estimated_points": 0, "executions": 0})
            summary["estimated_points"] += int(billing.get("estimated_points") or 0)
            summary["executions"] += 1
        for run_id in billing.get("run_ids") or []:
            key = str(run_id or "")
            if key:
                run_counts[key] = run_counts.get(key, 0) + 1
    duplicate_charge_count = sum(count - 1 for count in run_counts.values() if count > 1)
    succeeded = sum(1 for item in executions if item.get("status") == "succeeded")
    return {
        "total_executions": total,
        "confirmed_executions": len(confirmed),
        "terminal_executions": len(terminal),
        "confirmation_rate": len(confirmed) / total if total else 0.0,
        "failure_rate": sum(1 for item in executions if item.get("status") == "failed") / total if total else 0.0,
        "cancellation_rate": sum(1 for item in executions if item.get("status") == "cancelled") / total if total else 0.0,
        "retry_rate": feedback_counts.get("retried", 0) / total if total else 0.0,
        "duplicate_charge_count": duplicate_charge_count,
        "result_continue_rate": feedback_counts.get("continued", 0) / succeeded if succeeded else 0.0,
        "model_costs": sorted(model_costs.values(), key=lambda item: (-item["estimated_points"], item["model"])),
        "feedback_counts": feedback_counts,
    }


class LocalSmartImageAgentV3Store:
    def __init__(self, path: str, agent_store: Any, registry: Optional[CapabilityRegistry] = None):
        self.path = path
        self.agent_store = agent_store
        self.registry = registry or CapabilityRegistry()
        self.context_builder = ContextBuilder()
        self.planner = Planner(self.registry)
        self.approval_gate = ApprovalGate()
        self.orchestrator = OrchestratorAdapter()
        self.lock = threading.RLock()

    def _read(self) -> Dict[str, List[Dict[str, Any]]]:
        if not os.path.exists(self.path):
            return {"executions": [], "events": [], "feedback": []}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            data = {}
        return {
            "executions": data.get("executions") or [],
            "events": data.get("events") or [],
            "feedback": data.get("feedback") or [],
        }

    def _write(self, data: Dict[str, List[Dict[str, Any]]]) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.path)

    @staticmethod
    def _record(data: Dict[str, List[Dict[str, Any]]], execution_id: str, user: CurrentUser) -> Dict[str, Any]:
        execution = next(
            (item for item in data["executions"] if item.get("id") == execution_id and item.get("user_id") == user.id),
            None,
        )
        if not execution:
            raise HTTPException(status_code=404, detail="Image Agent v3 execution not found")
        return execution

    def _append_event(self, data: Dict[str, List[Dict[str, Any]]], execution: Dict[str, Any], event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if event_type not in SMART_IMAGE_AGENT_V3_EVENT_TYPES:
            raise ValueError(f"Unsupported Smart Image Agent v3 event: {event_type}")
        sequence = int(execution.get("next_sequence") or 1)
        event = {
            "id": str(uuid.uuid4()),
            "protocol_version": SMART_IMAGE_AGENT_V3_PROTOCOL_VERSION,
            "execution_id": execution["id"],
            "user_id": execution["user_id"],
            "sequence": sequence,
            "type": event_type,
            "occurred_at": utc_now(),
            "payload": payload,
        }
        data["events"].append(event)
        execution["next_sequence"] = sequence + 1
        execution["updated_at"] = event["occurred_at"]
        return event

    def _runs(self, user: CurrentUser, execution: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            item for item in self.agent_store.list_runs(user, session_id=execution["session_id"])
            if item.get("plan_id") == execution["plan_id"]
        ]

    def _payload(self, user: CurrentUser, execution: Dict[str, Any]) -> Dict[str, Any]:
        plan = self.agent_store.get_plan(user, execution["plan_id"])
        return {
            **{key: value for key, value in execution.items() if key not in {"user_id", "next_sequence"}},
            "plan": plan,
            "runs": self._runs(user, execution),
        }

    def create_execution(self, user: CurrentUser, payload: ImageAgentV3ExecutionCreate) -> Dict[str, Any]:
        with self.lock:
            context = self.context_builder.build(payload.context)
            plan_payload = self.planner.build_plan(payload, context)
            self.agent_store.add_message(user, payload.session_id, ImageAgentMessageCreate(content=payload.message, context=context))
            plan = self.agent_store.create_plan(user, plan_payload)
            now = utc_now()
            execution = {
                "id": str(uuid.uuid4()),
                "user_id": user.id,
                "session_id": plan["session_id"],
                "plan_id": plan["id"],
                "team_id": plan.get("team_id") or "",
                "project_id": plan.get("project_id") or "",
                "canvas_id": plan["canvas_id"],
                "original_intent": payload.message,
                "context": context,
                "protocol_version": SMART_IMAGE_AGENT_V3_PROTOCOL_VERSION,
                "policy_version": SMART_IMAGE_AGENT_V3_POLICY_VERSION,
                "status": "awaiting_confirmation",
                "approval_key": str(uuid.uuid4()),
                "approved_idempotency_key": "",
                "run_ids": [],
                "artifact_run_ids": [],
                "billing_intent": {},
                "next_sequence": 1,
                "created_at": now,
                "updated_at": now,
                "approved_at": None,
                "completed_at": None,
            }
            data = self._read()
            data["executions"].append(execution)
            self._append_event(data, execution, "context.ready", {"context": context})
            self._append_event(data, execution, "plan.proposed", {"plan": self.registry.get(plan["action"]).build_preview(plan)})
            self._append_event(data, execution, "approval.requested", {"estimated_points": plan["estimated_points"]})
            self._write(data)
            return self._payload(user, execution)

    def get_execution(self, user: CurrentUser, execution_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            execution = self._record(data, execution_id, user)
            self._reconcile(data, user, execution)
            self._write(data)
            return self._payload(user, execution)

    def update_plan(self, user: CurrentUser, execution_id: str, payload: ImageAgentV3PlanUpdate) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            execution = self._record(data, execution_id, user)
            if execution.get("status") != "awaiting_confirmation":
                raise HTTPException(status_code=409, detail="Confirmed Smart Image Agent v3 executions cannot be edited")
            plan = self.agent_store.update_plan(user, execution["plan_id"], ImageAgentPlanUpdate(**payload.model_dump(exclude_none=True)))
            self._append_event(data, execution, "plan.updated", {"plan": self.registry.get(plan["action"]).build_preview(plan)})
            self._write(data)
            return self._payload(user, execution)

    def approve(self, user: CurrentUser, execution_id: str, payload: ImageAgentV3Approval) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            execution = self._record(data, execution_id, user)
            self.approval_gate.require(execution, payload.idempotency_key)
            if execution.get("approved_idempotency_key"):
                if secrets.compare_digest(execution["approved_idempotency_key"], payload.idempotency_key):
                    return self._payload(user, execution)
                raise HTTPException(status_code=409, detail="Smart Image Agent v3 execution was already approved")
            if execution.get("status") != "awaiting_confirmation":
                raise HTTPException(status_code=409, detail="Smart Image Agent v3 execution is not awaiting confirmation")
            confirmed = self.agent_store.confirm_plan(user, execution["plan_id"])
            runs = confirmed["runs"]
            plan = confirmed["plan"]
            now = utc_now()
            execution["status"] = "queued"
            execution["approved_idempotency_key"] = payload.idempotency_key
            execution["run_ids"] = [item["id"] for item in runs]
            execution["approved_at"] = now
            execution["billing_intent"] = {
                "id": str(uuid.uuid4()),
                "status": "pending_provider_charge",
                "estimated_points": plan["estimated_points"],
                "model": plan["model"],
                "run_ids": execution["run_ids"],
            }
            self._append_event(data, execution, "approval.decided", {"decision": "approved", "run_ids": execution["run_ids"]})
            dispatch = self.registry.get(plan["action"]).execute(runs)
            self.orchestrator.dispatch(execution, runs)
            self._append_event(data, execution, "tool.started", {"capability_id": plan["action"], **dispatch})
            self._write(data)
            return self._payload(user, execution)

    def cancel(self, user: CurrentUser, execution_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            execution = self._record(data, execution_id, user)
            if execution.get("status") != "awaiting_confirmation":
                raise HTTPException(status_code=409, detail="Only unapproved Smart Image Agent v3 executions can be cancelled safely")
            self.agent_store.update_plan(user, execution["plan_id"], ImageAgentPlanUpdate(status="cancelled"))
            execution["status"] = "cancelled"
            execution["completed_at"] = utc_now()
            self._append_event(data, execution, "tool.cancelled", {"reason": "user_cancelled_before_approval"})
            self._append_event(data, execution, "execution.completed", {"status": "cancelled"})
            self._write(data)
            return self._payload(user, execution)

    def add_feedback(self, user: CurrentUser, execution_id: str, payload: ImageAgentV3FeedbackCreate) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            execution = self._record(data, execution_id, user)
            feedback = {
                "id": str(uuid.uuid4()),
                "execution_id": execution["id"],
                "user_id": user.id,
                "kind": payload.kind,
                "rating": payload.rating,
                "reason": payload.reason,
                "metadata": payload.metadata,
                "created_at": utc_now(),
            }
            data["feedback"].append(feedback)
            self._write(data)
            return feedback

    def list_events(self, user: CurrentUser, execution_id: str, after_sequence: int = 0) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            execution = self._record(data, execution_id, user)
            self._reconcile(data, user, execution)
            self._write(data)
            return [
                dict(item) for item in data["events"]
                if item.get("execution_id") == execution_id and int(item.get("sequence") or 0) > after_sequence
            ]

    def metrics(self, team_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            executions = [item for item in data["executions"] if item.get("team_id") == team_id]
            execution_ids = {item["id"] for item in executions}
            feedback = [item for item in data["feedback"] if item.get("execution_id") in execution_ids]
            return build_smart_image_agent_v3_metrics(executions, feedback)

    def _reconcile(self, data: Dict[str, List[Dict[str, Any]]], user: CurrentUser, execution: Dict[str, Any]) -> None:
        if execution.get("status") not in {"queued", "running"}:
            return
        plan = self.agent_store.get_plan(user, execution["plan_id"])
        status = str(plan.get("status") or "")
        if status not in SMART_IMAGE_AGENT_V3_EXECUTION_STATES or status == execution.get("status"):
            return
        execution["status"] = status
        runs = self._runs(user, execution)
        emitted = set(execution.get("artifact_run_ids") or [])
        for run in runs:
            if run.get("status") == "succeeded" and run.get("result") and run["id"] not in emitted:
                self._append_event(data, execution, "artifact.created", {
                    "run_id": run["id"],
                    "artifact": self.registry.get(plan["action"]).result_renderer(run["result"]),
                })
                emitted.add(run["id"])
        execution["artifact_run_ids"] = sorted(emitted)
        if status == "succeeded":
            self._append_event(data, execution, "tool.completed", {"run_ids": execution.get("run_ids") or []})
        elif status == "failed":
            self._append_event(data, execution, "tool.failed", {"run_ids": execution.get("run_ids") or []})
        elif status == "cancelled":
            self._append_event(data, execution, "tool.cancelled", {"run_ids": execution.get("run_ids") or []})
        if status in {"succeeded", "failed", "cancelled"}:
            execution["completed_at"] = utc_now()
            self._append_event(data, execution, "execution.completed", {"status": status})


class SupabaseSmartImageAgentV3Store:
    """Supabase persistence. Approval uses the migration RPC to keep runs and events atomic."""

    def __init__(self, client: Any, agent_store: Any, registry: Optional[CapabilityRegistry] = None):
        self.client = client
        self.agent_store = agent_store
        self.registry = registry or CapabilityRegistry()
        self.context_builder = ContextBuilder()
        self.planner = Planner(self.registry)
        self.approval_gate = ApprovalGate()

    async def _record(self, user: CurrentUser, execution_id: str) -> Dict[str, Any]:
        rows = await self.client._request(
            "GET",
            f"/smart_image_agent_executions?id=eq.{quote(execution_id, safe='')}&user_id=eq.{quote(user.id, safe='')}&select=*&limit=1",
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Image Agent v3 execution not found")
        return rows[0]

    async def _payload(self, user: CurrentUser, execution: Dict[str, Any]) -> Dict[str, Any]:
        plan = await self.agent_store.get_plan(user, execution["plan_id"])
        runs = await self.agent_store.list_runs(user, session_id=execution["session_id"])
        return {
            **{key: value for key, value in execution.items() if key not in {"user_id", "next_sequence"}},
            "plan": plan,
            "runs": [item for item in runs if item.get("plan_id") == execution["plan_id"]],
        }

    async def _append_event(self, execution: Dict[str, Any], event_type: str, payload: Dict[str, Any]) -> None:
        if event_type not in SMART_IMAGE_AGENT_V3_EVENT_TYPES:
            raise ValueError(f"Unsupported Smart Image Agent v3 event: {event_type}")
        sequence = int(execution.get("next_sequence") or 1)
        now = utc_now()
        await self.client._request("POST", "/smart_image_agent_events", json_body={
            "id": str(uuid.uuid4()),
            "execution_id": execution["id"],
            "user_id": execution["user_id"],
            "protocol_version": SMART_IMAGE_AGENT_V3_PROTOCOL_VERSION,
            "sequence": sequence,
            "type": event_type,
            "occurred_at": now,
            "payload": payload,
        })
        execution["next_sequence"] = sequence + 1
        execution["updated_at"] = now
        rows = await self.client._request(
            "PATCH",
            f"/smart_image_agent_executions?id=eq.{quote(execution['id'], safe='')}&user_id=eq.{quote(execution['user_id'], safe='')}",
            json_body={"next_sequence": execution["next_sequence"], "updated_at": now},
        )
        if rows:
            execution.update(rows[0])

    async def create_execution(self, user: CurrentUser, payload: ImageAgentV3ExecutionCreate) -> Dict[str, Any]:
        context = self.context_builder.build(payload.context)
        plan_payload = self.planner.build_plan(payload, context)
        await self.agent_store.add_message(user, payload.session_id, ImageAgentMessageCreate(content=payload.message, context=context))
        plan = await self.agent_store.create_plan(user, plan_payload)
        now = utc_now()
        execution = {
            "id": str(uuid.uuid4()),
            "user_id": user.id,
            "session_id": plan["session_id"],
            "plan_id": plan["id"],
            "team_id": plan.get("team_id") or None,
            "project_id": plan.get("project_id") or None,
            "canvas_id": plan["canvas_id"],
            "original_intent": payload.message,
            "context": context,
            "protocol_version": SMART_IMAGE_AGENT_V3_PROTOCOL_VERSION,
            "policy_version": SMART_IMAGE_AGENT_V3_POLICY_VERSION,
            "status": "awaiting_confirmation",
            "approval_key": str(uuid.uuid4()),
            "approved_idempotency_key": None,
            "run_ids": [],
            "artifact_run_ids": [],
            "billing_intent": {},
            "next_sequence": 1,
            "created_at": now,
            "updated_at": now,
        }
        try:
            rows = await self.client._request("POST", "/smart_image_agent_executions", json_body=execution)
            if rows:
                execution.update(rows[0])
            await self._append_event(execution, "context.ready", {"context": context})
            await self._append_event(execution, "plan.proposed", {"plan": self.registry.get(plan["action"]).build_preview(plan)})
            await self._append_event(execution, "approval.requested", {"estimated_points": plan["estimated_points"]})
        except Exception:
            await self.agent_store.update_plan(user, plan["id"], ImageAgentPlanUpdate(status="cancelled"))
            raise
        return await self._payload(user, execution)

    async def get_execution(self, user: CurrentUser, execution_id: str) -> Dict[str, Any]:
        execution = await self._record(user, execution_id)
        execution = await self._reconcile(user, execution)
        return await self._payload(user, execution)

    async def update_plan(self, user: CurrentUser, execution_id: str, payload: ImageAgentV3PlanUpdate) -> Dict[str, Any]:
        execution = await self._record(user, execution_id)
        if execution.get("status") != "awaiting_confirmation":
            raise HTTPException(status_code=409, detail="Confirmed Smart Image Agent v3 executions cannot be edited")
        plan = await self.agent_store.update_plan(user, execution["plan_id"], ImageAgentPlanUpdate(**payload.model_dump(exclude_none=True)))
        await self._append_event(execution, "plan.updated", {"plan": self.registry.get(plan["action"]).build_preview(plan)})
        return await self._payload(user, execution)

    async def approve(self, user: CurrentUser, execution_id: str, payload: ImageAgentV3Approval) -> Dict[str, Any]:
        execution = await self._record(user, execution_id)
        self.approval_gate.require(execution, payload.idempotency_key)
        await self.client._request("POST", "/rpc/smart_image_agent_v3_approve_execution", json_body={
            "p_execution_id": execution_id,
            "p_user_id": user.id,
            "p_idempotency_key": payload.idempotency_key,
        })
        return await self.get_execution(user, execution_id)

    async def cancel(self, user: CurrentUser, execution_id: str) -> Dict[str, Any]:
        execution = await self._record(user, execution_id)
        if execution.get("status") != "awaiting_confirmation":
            raise HTTPException(status_code=409, detail="Only unapproved Smart Image Agent v3 executions can be cancelled safely")
        await self.agent_store.update_plan(user, execution["plan_id"], ImageAgentPlanUpdate(status="cancelled"))
        rows = await self.client._request(
            "PATCH",
            f"/smart_image_agent_executions?id=eq.{quote(execution_id, safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body={"status": "cancelled", "completed_at": utc_now(), "updated_at": utc_now()},
        )
        if rows:
            execution.update(rows[0])
        await self._append_event(execution, "tool.cancelled", {"reason": "user_cancelled_before_approval"})
        await self._append_event(execution, "execution.completed", {"status": "cancelled"})
        return await self._payload(user, execution)

    async def add_feedback(self, user: CurrentUser, execution_id: str, payload: ImageAgentV3FeedbackCreate) -> Dict[str, Any]:
        await self._record(user, execution_id)
        feedback = {
            "id": str(uuid.uuid4()),
            "execution_id": execution_id,
            "user_id": user.id,
            "kind": payload.kind,
            "rating": payload.rating,
            "reason": payload.reason,
            "metadata": payload.metadata,
            "created_at": utc_now(),
        }
        rows = await self.client._request("POST", "/smart_image_agent_feedback", json_body=feedback)
        return rows[0] if rows else feedback

    async def list_events(self, user: CurrentUser, execution_id: str, after_sequence: int = 0) -> List[Dict[str, Any]]:
        execution = await self._record(user, execution_id)
        await self._reconcile(user, execution)
        return await self.client._request(
            "GET",
            f"/smart_image_agent_events?execution_id=eq.{quote(execution_id, safe='')}&user_id=eq.{quote(user.id, safe='')}&sequence=gt.{max(0, after_sequence)}&select=*&order=sequence.asc",
        ) or []

    async def metrics(self, team_id: str) -> Dict[str, Any]:
        executions = await self.client._request(
            "GET",
            f"/smart_image_agent_executions?team_id=eq.{quote(team_id, safe='')}&select=*",
        ) or []
        execution_ids = [str(item.get("id") or "") for item in executions if item.get("id")]
        if not execution_ids:
            return build_smart_image_agent_v3_metrics([], [])
        filters = ",".join(quote(item, safe="") for item in execution_ids)
        feedback = await self.client._request(
            "GET",
            f"/smart_image_agent_feedback?execution_id=in.({filters})&select=*",
        ) or []
        return build_smart_image_agent_v3_metrics(executions, feedback)

    async def _reconcile(self, user: CurrentUser, execution: Dict[str, Any]) -> Dict[str, Any]:
        if execution.get("status") not in {"queued", "running"}:
            return execution
        plan = await self.agent_store.get_plan(user, execution["plan_id"])
        status = str(plan.get("status") or "")
        if status not in SMART_IMAGE_AGENT_V3_EXECUTION_STATES or status == execution.get("status"):
            return execution
        runs = [
            item for item in await self.agent_store.list_runs(user, session_id=execution["session_id"])
            if item.get("plan_id") == execution["plan_id"]
        ]
        emitted = set(execution.get("artifact_run_ids") or [])
        for run in runs:
            if run.get("status") == "succeeded" and run.get("result") and run["id"] not in emitted:
                await self._append_event(execution, "artifact.created", {
                    "run_id": run["id"],
                    "artifact": self.registry.get(plan["action"]).result_renderer(run["result"]),
                })
                emitted.add(run["id"])
        if status == "running":
            await self._append_event(execution, "tool.progressed", {"run_ids": execution.get("run_ids") or []})
        elif status == "succeeded":
            await self._append_event(execution, "tool.completed", {"run_ids": execution.get("run_ids") or []})
            await self._append_event(execution, "execution.completed", {"status": status})
        elif status == "failed":
            await self._append_event(execution, "tool.failed", {"run_ids": execution.get("run_ids") or []})
            await self._append_event(execution, "execution.completed", {"status": status})
        elif status == "cancelled":
            await self._append_event(execution, "tool.cancelled", {"run_ids": execution.get("run_ids") or []})
            await self._append_event(execution, "execution.completed", {"status": status})
        changes: Dict[str, Any] = {
            "status": status,
            "artifact_run_ids": sorted(emitted),
            "updated_at": utc_now(),
        }
        if status in {"succeeded", "failed", "cancelled"}:
            changes["completed_at"] = utc_now()
        rows = await self.client._request(
            "PATCH",
            f"/smart_image_agent_executions?id=eq.{quote(execution['id'], safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body=changes,
        )
        return rows[0] if rows else {**execution, **changes}
