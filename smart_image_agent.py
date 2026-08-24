import datetime
import json
import os
import threading
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import HTTPException
from pydantic import BaseModel, Field

from team_cloud import CurrentUser


SMART_IMAGE_AGENT_ACTIONS = {
    "generate_image",
    "edit_image",
    "compose_images",
    "create_variants",
    "expand_image",
    "generate_image_set",
    "organize_results",
}
SMART_IMAGE_AGENT_RATIOS = {"auto", "1:1", "16:9", "9:16", "4:3", "3:4", "4:5", "5:4", "21:9"}
SMART_IMAGE_AGENT_RUN_STATES = {"queued", "running", "succeeded", "failed", "cancelled"}
SMART_IMAGE_AGENT_PLAN_STATES = {
    "draft",
    "awaiting_confirmation",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
}
SMART_IMAGE_AGENT_PROVIDER = "custom-api"
SMART_IMAGE_AGENT_STANDARD_MODEL = "nano-banana-2"
SMART_IMAGE_AGENT_PRO_MODEL = "nano-banana-pro"
SMART_IMAGE_AGENT_STANDARD_POINTS = 12
SMART_IMAGE_AGENT_PRO_POINTS = 18
SMART_IMAGE_AGENT_MODELS = {
    "gpt-image-2": {"provider_id": "custom-api", "quality": "standard", "unit_points": 6},
    "nano-banana-2": {"provider_id": "custom-api", "quality": "standard", "unit_points": 12},
    "nano-banana-pro": {"provider_id": "custom-api", "quality": "pro", "unit_points": 18},
    "gpt-image-2-vip": {"provider_id": "custom-api", "quality": "vip", "unit_points": 20},
}
SMART_IMAGE_AGENT_MAX_REFERENCES = 10
SMART_IMAGE_AGENT_REFERENCE_ROLES = {"primary", "reference", "edit_target"}


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ImageAgentSessionCreate(BaseModel):
    canvas_id: str = Field(..., min_length=1, max_length=200)
    project_id: str = Field("", max_length=200)
    team_id: str = Field("", max_length=200)
    title: str = Field("", max_length=120)


class ImageAgentSessionUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=120)
    archived: Optional[bool] = None


class ImageAgentMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=12000)
    context: Dict[str, Any] = Field(default_factory=dict)


class ImageAgentPlanCreate(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=12000)
    context: Dict[str, Any] = Field(default_factory=dict)
    action: str = Field("", max_length=80)
    prompt: str = Field("", max_length=12000)
    ratio: str = Field("auto", max_length=20)
    count: int = Field(1, ge=1, le=8)
    quality: str = Field("standard", pattern="^(standard|pro)$")
    model: Optional[str] = Field(None, max_length=120)


class ImageAgentPlanUpdate(BaseModel):
    prompt: Optional[str] = Field(None, min_length=1, max_length=12000)
    ratio: Optional[str] = Field(None, max_length=20)
    count: Optional[int] = Field(None, ge=1, le=8)
    quality: Optional[str] = Field(None, pattern="^(standard|pro)$")
    model: Optional[str] = Field(None, max_length=120)
    status: Optional[str] = Field(None, pattern="^cancelled$")


class ImageAgentRunUpdate(BaseModel):
    status: str = Field(..., pattern="^(running|succeeded|failed|cancelled)$")
    result: Dict[str, Any] = Field(default_factory=dict)
    error: str = Field("", max_length=4000)
    progress_stage: str = Field("", max_length=40)


def resolve_smart_image_agent_model(model: Optional[str], quality: Optional[str]) -> tuple[str, str, str, int]:
    requested_model = str(model or "").strip()
    if requested_model:
        policy = SMART_IMAGE_AGENT_MODELS.get(requested_model)
        if policy is None:
            raise HTTPException(status_code=422, detail="Unsupported image Agent model")
        return requested_model, policy["provider_id"], policy["quality"], policy["unit_points"]
    legacy_model = SMART_IMAGE_AGENT_PRO_MODEL if quality == "pro" else SMART_IMAGE_AGENT_STANDARD_MODEL
    policy = SMART_IMAGE_AGENT_MODELS[legacy_model]
    return legacy_model, policy["provider_id"], policy["quality"], policy["unit_points"]


def infer_image_action(message: str, context: Dict[str, Any]) -> str:
    text = str(message or "").strip().lower()
    selected = context.get("selected_images") if isinstance(context, dict) else []
    reference_count = len(selected) if isinstance(selected, list) else 0
    if any(word in text for word in ("扩图", "补背景", "扩展画面", "换画幅", "outpaint")):
        return "expand_image"
    if any(word in text for word in ("变体", "多个版本", "不同版本", "variants")):
        return "create_variants"
    if reference_count > 1 or any(word in text for word in ("合成", "融合", "拼合", "compose")):
        return "compose_images"
    if any(word in text for word in ("一组", "套图", "系列", "批量", "小红书", "社媒")):
        return "generate_image_set"
    if reference_count:
        return "edit_image"
    return "generate_image"


def _safe_image_dimension(value: Any) -> int:
    try:
        return max(0, min(100000, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _persistable_reference_url(value: Any) -> str:
    url = str(value or "").strip()[:4000]
    if url.lower().startswith(("data:", "blob:", "javascript:")):
        raise HTTPException(status_code=422, detail="Image Agent references must use a stored image URL")
    return url


def _session_title(value: Any) -> str:
    return " ".join(str(value or "").split())[:120]


def normalize_references(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = context.get("selected_images") if isinstance(context, dict) else []
    references = raw if isinstance(raw, list) else []
    if len(references) > SMART_IMAGE_AGENT_MAX_REFERENCES:
        raise HTTPException(status_code=422, detail=f"A task can reference at most {SMART_IMAGE_AGENT_MAX_REFERENCES} images")
    cleaned: List[Dict[str, Any]] = []
    for item in references:
        if not isinstance(item, dict):
            continue
        reference = {
            "node_id": str(item.get("node_id") or item.get("id") or "")[:200],
            "asset_id": str(item.get("asset_id") or "")[:200],
            "url": _persistable_reference_url(item.get("url") or item.get("original_url")),
            "preview_url": _persistable_reference_url(item.get("preview_url") or item.get("thumbnail")),
            "width": _safe_image_dimension(item.get("width")),
            "height": _safe_image_dimension(item.get("height")),
            "prompt": str(item.get("prompt") or "")[:4000],
            "role": str(item.get("role") or "").strip().lower(),
        }
        if reference["node_id"] or reference["asset_id"] or reference["url"]:
            cleaned.append(reference)
    return cleaned


def assign_reference_roles(references: List[Dict[str, Any]], action: str) -> List[Dict[str, Any]]:
    assigned = [dict(item) for item in references]
    for index, reference in enumerate(assigned):
        role = reference.get("role")
        if role not in SMART_IMAGE_AGENT_REFERENCE_ROLES:
            if action in {"edit_image", "expand_image"}:
                role = "edit_target" if index == 0 else "reference"
            elif index == 0:
                role = "primary"
            else:
                role = "reference"
        reference["role"] = role
    return assigned


def normalize_message_context(context: Dict[str, Any]) -> Dict[str, Any]:
    source = context if isinstance(context, dict) else {}
    cleaned: Dict[str, Any] = {
        "canvas_id": str(source.get("canvas_id") or source.get("canvasId") or "")[:200],
        "project_id": str(source.get("project_id") or source.get("projectId") or "")[:200],
        "team_id": str(source.get("team_id") or source.get("teamId") or "")[:200],
        "cloud": bool(source.get("cloud")),
        "node_count": _safe_image_dimension(source.get("node_count")),
        "selected_images": normalize_references(source),
    }
    viewport = source.get("viewport") if isinstance(source.get("viewport"), dict) else {}
    cleaned["viewport"] = {
        key: float(viewport.get(key) or default)
        for key, default in (("x", 0), ("y", 0), ("scale", 1))
        if isinstance(viewport.get(key, default), (int, float))
    }
    settings = source.get("settings") if isinstance(source.get("settings"), dict) else {}
    cleaned["settings"] = {
        key: str(settings.get(key) or "")[:80]
        for key in ("ratio", "resolution")
        if settings.get(key) is not None
    }
    return cleaned


def validate_session_context(session: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_message_context(context)
    if normalized.get("canvas_id") != session.get("canvas_id"):
        raise HTTPException(status_code=422, detail="Image Agent context must match its Smart Canvas")
    return normalized


class LocalSmartImageAgentStore:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()

    def _read(self) -> Dict[str, List[Dict[str, Any]]]:
        if not os.path.exists(self.path):
            return {"sessions": [], "messages": [], "plans": [], "runs": []}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            data = {}
        return {
            "sessions": data.get("sessions") or [],
            "messages": data.get("messages") or [],
            "plans": data.get("plans") or [],
            "runs": data.get("runs") or [],
        }

    def _write(self, data: Dict[str, List[Dict[str, Any]]]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.path)

    @staticmethod
    def _record(data: Dict[str, Any], bucket: str, record_id: str, user: CurrentUser) -> Dict[str, Any]:
        record = next(
            (item for item in data[bucket] if item.get("id") == record_id and item.get("user_id") == user.id),
            None,
        )
        if not record:
            raise HTTPException(status_code=404, detail=f"Image Agent {bucket[:-1]} not found")
        return record

    def _session_record(self, data: Dict[str, Any], session_id: str, user: CurrentUser, canvas_id: str = "") -> Dict[str, Any]:
        session = self._record(data, "sessions", session_id, user)
        if canvas_id and session.get("canvas_id") != canvas_id:
            raise HTTPException(status_code=404, detail="Image Agent session not found")
        return session

    def create_session(self, user: CurrentUser, payload: ImageAgentSessionCreate) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            now = utc_now()
            session = {
                "id": str(uuid.uuid4()),
                "user_id": user.id,
                "canvas_id": payload.canvas_id,
                "project_id": payload.project_id,
                "team_id": payload.team_id,
                "title": _session_title(payload.title),
                "created_at": now,
                "updated_at": now,
                "last_activity_at": now,
                "archived_at": None,
            }
            data["sessions"].append(session)
            self._write(data)
            return dict(session)

    @staticmethod
    def _session_summary(session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: session.get(key)
            for key in (
                "id", "canvas_id", "project_id", "team_id", "title", "created_at",
                "updated_at", "last_activity_at", "archived_at",
            )
        }

    @staticmethod
    def _touch_session(session: Dict[str, Any], now: Optional[str] = None) -> None:
        timestamp = now or utc_now()
        session["updated_at"] = timestamp
        session["last_activity_at"] = timestamp

    def list_sessions(self, user: CurrentUser, canvas_id: str, include_archived: bool = False) -> List[Dict[str, Any]]:
        with self.lock:
            sessions = [
                item for item in self._read()["sessions"]
                if item.get("user_id") == user.id and item.get("canvas_id") == canvas_id
                and (include_archived or not item.get("archived_at"))
            ]
            return [self._session_summary(item) for item in sorted(
                sessions,
                key=lambda item: item.get("last_activity_at") or item.get("updated_at") or "",
                reverse=True,
            )]

    def update_session(self, user: CurrentUser, session_id: str, payload: ImageAgentSessionUpdate, canvas_id: str = "") -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            session = self._session_record(data, session_id, user, canvas_id)
            now = utc_now()
            if payload.title is not None:
                session["title"] = _session_title(payload.title)
            if payload.archived is not None:
                session["archived_at"] = now if payload.archived else None
            self._touch_session(session, now)
            self._write(data)
            return dict(session)

    def get_session(self, user: CurrentUser, session_id: str, canvas_id: str = "") -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            session = self._session_record(data, session_id, user, canvas_id)
            return {
                **session,
                "messages": [item for item in data["messages"] if item.get("session_id") == session_id and item.get("user_id") == user.id],
                "plans": [item for item in data["plans"] if item.get("session_id") == session_id and item.get("user_id") == user.id],
            }

    def add_message(self, user: CurrentUser, session_id: str, payload: ImageAgentMessageCreate) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            session = self._record(data, "sessions", session_id, user)
            context = validate_session_context(session, payload.context)
            now = utc_now()
            message = {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "user_id": user.id,
                "canvas_id": session["canvas_id"],
                "role": "user",
                "content": payload.content,
                "context": context,
                "created_at": now,
            }
            data["messages"].append(message)
            if not session.get("title"):
                session["title"] = _session_title(payload.content)
            self._touch_session(session, now)
            self._write(data)
            return dict(message)

    def create_plan(self, user: CurrentUser, payload: ImageAgentPlanCreate) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            session = self._record(data, "sessions", payload.session_id, user)
            context = validate_session_context(session, payload.context)
            references = context["selected_images"]
            action = payload.action.strip() or infer_image_action(payload.message, context)
            if not payload.action and payload.count > 1 and action == "generate_image":
                action = "generate_image_set"
            if action not in SMART_IMAGE_AGENT_ACTIONS:
                raise HTTPException(status_code=422, detail="Unsupported image Agent action")
            active_plan = next(
                (
                    item for item in data["plans"]
                    if item.get("canvas_id") == session["canvas_id"] and item.get("user_id") == user.id
                    and item.get("status") == "awaiting_confirmation"
                ),
                None,
            )
            if active_plan:
                raise HTTPException(status_code=409, detail="Finish or dismiss the current image plan before creating another")
            if payload.ratio not in SMART_IMAGE_AGENT_RATIOS:
                raise HTTPException(status_code=422, detail="Unsupported image ratio")
            references = assign_reference_roles(references, action)
            model, provider_id, quality, unit_points = resolve_smart_image_agent_model(payload.model, payload.quality)
            now = utc_now()
            plan = {
                "id": str(uuid.uuid4()),
                "session_id": session["id"],
                "user_id": user.id,
                "team_id": session.get("team_id") or "",
                "project_id": session.get("project_id") or "",
                "canvas_id": session["canvas_id"],
                "action": action,
                "message": payload.message,
                "prompt": payload.prompt.strip() or payload.message.strip(),
                "references": references,
                "source_node_ids": [item["node_id"] for item in references if item.get("node_id")],
                "ratio": payload.ratio,
                "count": payload.count,
                "quality": quality,
                "provider_id": provider_id,
                "model": model,
                "fallback_used": False,
                "unit_points": unit_points,
                "estimated_points": unit_points * payload.count,
                "status": "awaiting_confirmation",
                "created_at": now,
                "updated_at": now,
                "confirmed_at": None,
            }
            data["plans"].append(plan)
            self._touch_session(session, now)
            self._write(data)
            return dict(plan)

    def get_plan(self, user: CurrentUser, plan_id: str) -> Dict[str, Any]:
        with self.lock:
            return dict(self._record(self._read(), "plans", plan_id, user))

    def update_plan(self, user: CurrentUser, plan_id: str, payload: ImageAgentPlanUpdate) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            plan = self._record(data, "plans", plan_id, user)
            if payload.status == "cancelled" and plan.get("status") in {"draft", "awaiting_confirmation"}:
                plan["status"] = "cancelled"
                plan["updated_at"] = utc_now()
                self._write(data)
                return dict(plan)
            if plan.get("status") not in {"draft", "awaiting_confirmation"}:
                raise HTTPException(status_code=409, detail="Confirmed image Agent plans cannot be edited")
            changes = payload.model_dump(exclude_none=True)
            if "ratio" in changes and changes["ratio"] not in SMART_IMAGE_AGENT_RATIOS:
                raise HTTPException(status_code=422, detail="Unsupported image ratio")
            for key in ("prompt", "ratio", "count"):
                if key in changes:
                    plan[key] = changes[key]
            selected_model = (
                changes["model"]
                if "model" in changes
                else None
                if "quality" in changes
                else plan.get("model")
            )
            model, provider_id, quality, unit_points = resolve_smart_image_agent_model(
                selected_model, changes.get("quality", plan.get("quality") or "standard")
            )
            plan["model"] = model
            plan["provider_id"] = provider_id
            plan["quality"] = quality
            plan["unit_points"] = unit_points
            plan["estimated_points"] = plan["unit_points"] * plan["count"]
            plan["updated_at"] = utc_now()
            self._write(data)
            return dict(plan)

    def confirm_plan(self, user: CurrentUser, plan_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            plan = self._record(data, "plans", plan_id, user)
            existing = [item for item in data["runs"] if item.get("plan_id") == plan_id and item.get("user_id") == user.id]
            if existing:
                return {"plan": dict(plan), "runs": sorted((dict(item) for item in existing), key=lambda item: item["sequence"])}
            if plan.get("status") != "awaiting_confirmation":
                raise HTTPException(status_code=409, detail="Image Agent plan is not awaiting confirmation")
            now = utc_now()
            runs = []
            for sequence in range(1, int(plan["count"]) + 1):
                run = {
                    "id": str(uuid.uuid4()),
                    "plan_id": plan_id,
                    "session_id": plan["session_id"],
                    "user_id": user.id,
                    "team_id": plan.get("team_id") or "",
                    "canvas_id": plan["canvas_id"],
                    "sequence": sequence,
                    "attempt": 1,
                    "status": "queued",
                    "progress_stage": "queued",
                    "provider_id": plan["provider_id"],
                    "model": plan["model"],
                    "result": {},
                    "error": "",
                    "created_at": now,
                    "updated_at": now,
                    "started_at": None,
                    "finished_at": None,
                }
                data["runs"].append(run)
                runs.append(run)
            plan["status"] = "queued"
            plan["confirmed_at"] = now
            plan["updated_at"] = now
            self._touch_session(session := self._record(data, "sessions", plan["session_id"], user), now)
            self._write(data)
            return {"plan": dict(plan), "runs": [dict(item) for item in runs]}

    def list_runs(self, user: CurrentUser, canvas_id: str = "", session_id: str = "") -> List[Dict[str, Any]]:
        with self.lock:
            runs = [item for item in self._read()["runs"] if item.get("user_id") == user.id]
            if canvas_id:
                runs = [item for item in runs if item.get("canvas_id") == canvas_id]
            if session_id:
                runs = [item for item in runs if item.get("session_id") == session_id]
            return [dict(item) for item in sorted(runs, key=lambda item: item.get("created_at") or "", reverse=True)]

    def _refresh_plan_status(self, data: Dict[str, Any], plan_id: str) -> None:
        plan = next((item for item in data["plans"] if item.get("id") == plan_id), None)
        runs = [item for item in data["runs"] if item.get("plan_id") == plan_id]
        if not plan or not runs:
            return
        statuses = {item.get("status") for item in runs}
        if "running" in statuses:
            plan["status"] = "running"
        elif "queued" in statuses:
            plan["status"] = "queued"
        elif statuses == {"succeeded"}:
            plan["status"] = "succeeded"
        elif statuses == {"cancelled"}:
            plan["status"] = "cancelled"
        else:
            plan["status"] = "failed"
        plan["updated_at"] = utc_now()

    def update_run(self, user: CurrentUser, run_id: str, payload: ImageAgentRunUpdate) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            run = self._record(data, "runs", run_id, user)
            current = run.get("status")
            allowed = {
                "queued": {"running", "cancelled"},
                "running": {"running", "succeeded", "failed", "cancelled"},
            }
            if payload.status not in allowed.get(current, set()):
                raise HTTPException(status_code=409, detail=f"Cannot change image Agent run from {current} to {payload.status}")
            now = utc_now()
            run["status"] = payload.status
            run["result"] = payload.result if payload.status == "succeeded" else {}
            run["error"] = payload.error if payload.status == "failed" else ""
            if payload.progress_stage:
                run["progress_stage"] = payload.progress_stage
            elif payload.status in {"succeeded", "failed", "cancelled"}:
                run["progress_stage"] = payload.status
            run["updated_at"] = now
            if payload.status == "running":
                run["started_at"] = run.get("started_at") or now
            if payload.status in {"succeeded", "failed", "cancelled"}:
                run["finished_at"] = now
            self._refresh_plan_status(data, run["plan_id"])
            self._touch_session(self._record(data, "sessions", run["session_id"], user), now)
            self._write(data)
            return dict(run)

    def cancel_run(self, user: CurrentUser, run_id: str) -> Dict[str, Any]:
        return self.update_run(user, run_id, ImageAgentRunUpdate(status="cancelled"))

    def retry_run(self, user: CurrentUser, run_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            run = self._record(data, "runs", run_id, user)
            if run.get("status") not in {"failed", "cancelled"}:
                raise HTTPException(status_code=409, detail="Only failed or cancelled image Agent runs can be retried")
            run["status"] = "queued"
            run["attempt"] = int(run.get("attempt") or 1) + 1
            run["result"] = {}
            run["error"] = ""
            run["started_at"] = None
            run["finished_at"] = None
            run["progress_stage"] = "queued"
            run["updated_at"] = utc_now()
            self._refresh_plan_status(data, run["plan_id"])
            self._write(data)
            return dict(run)

    def list_results(self, user: CurrentUser, session_id: str, canvas_id: str = "") -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            self._session_record(data, session_id, user, canvas_id)
            return [
                {
                    "run_id": item["id"],
                    "plan_id": item["plan_id"],
                    "session_id": item["session_id"],
                    "sequence": item["sequence"],
                    **(item.get("result") or {}),
                    "created_at": item.get("finished_at") or item.get("updated_at"),
                }
                for item in data["runs"]
                if item.get("session_id") == session_id
                and item.get("user_id") == user.id
                and item.get("status") == "succeeded"
                and item.get("result")
            ]


class SupabaseSmartImageAgentStore:
    def __init__(self, client: Any):
        self.client = client

    async def _get_record(self, table: str, record_id: str, user: CurrentUser) -> Dict[str, Any]:
        rows = await self.client._request(
            "GET",
            f"/{table}?id=eq.{quote(record_id, safe='')}&user_id=eq.{quote(user.id, safe='')}&select=*&limit=1",
        )
        if not rows:
            label = table.replace("smart_image_agent_", "").rstrip("s")
            raise HTTPException(status_code=404, detail=f"Image Agent {label} not found")
        return rows[0]

    async def _get_session(self, user: CurrentUser, session_id: str, canvas_id: str = "") -> Dict[str, Any]:
        session = await self._get_record("smart_image_agent_sessions", session_id, user)
        if canvas_id and session.get("canvas_id") != canvas_id:
            raise HTTPException(status_code=404, detail="Image Agent session not found")
        return session

    async def create_session(self, user: CurrentUser, payload: ImageAgentSessionCreate) -> Dict[str, Any]:
        now = utc_now()
        body = {
            "id": str(uuid.uuid4()),
            "user_id": user.id,
            "canvas_id": payload.canvas_id,
            "project_id": payload.project_id or None,
            "team_id": payload.team_id or None,
            "title": _session_title(payload.title),
            "created_at": now,
            "updated_at": now,
            "last_activity_at": now,
            "archived_at": None,
        }
        rows = await self.client._request("POST", "/smart_image_agent_sessions", json_body=[body])
        return rows[0] if rows else body

    async def list_sessions(self, user: CurrentUser, canvas_id: str, include_archived: bool = False) -> List[Dict[str, Any]]:
        filters = [
            f"user_id=eq.{quote(user.id, safe='')}",
            f"canvas_id=eq.{quote(canvas_id, safe='')}",
            "select=*",
            "order=last_activity_at.desc",
        ]
        if not include_archived:
            filters.append("archived_at=is.null")
        return await self.client._request("GET", "/smart_image_agent_sessions?" + "&".join(filters)) or []

    async def update_session(self, user: CurrentUser, session_id: str, payload: ImageAgentSessionUpdate, canvas_id: str = "") -> Dict[str, Any]:
        session = await self._get_session(user, session_id, canvas_id)
        now = utc_now()
        changes: Dict[str, Any] = {"updated_at": now, "last_activity_at": now}
        if payload.title is not None:
            changes["title"] = _session_title(payload.title)
        if payload.archived is not None:
            changes["archived_at"] = now if payload.archived else None
        rows = await self.client._request(
            "PATCH",
            f"/smart_image_agent_sessions?id=eq.{quote(session_id, safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body=changes,
        )
        return rows[0] if rows else {**session, **changes}

    async def get_session(self, user: CurrentUser, session_id: str, canvas_id: str = "") -> Dict[str, Any]:
        session = await self._get_session(user, session_id, canvas_id)
        encoded_id = quote(session_id, safe="")
        messages = await self.client._request(
            "GET",
            f"/smart_image_agent_messages?session_id=eq.{encoded_id}&user_id=eq.{quote(user.id, safe='')}&select=*&order=created_at.asc",
        )
        plans = await self.client._request(
            "GET",
            f"/smart_image_agent_plans?session_id=eq.{encoded_id}&user_id=eq.{quote(user.id, safe='')}&select=*&order=created_at.asc",
        )
        return {**session, "messages": messages or [], "plans": plans or []}

    async def add_message(self, user: CurrentUser, session_id: str, payload: ImageAgentMessageCreate) -> Dict[str, Any]:
        session = await self._get_record("smart_image_agent_sessions", session_id, user)
        context = validate_session_context(session, payload.context)
        now = utc_now()
        body = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "user_id": user.id,
            "canvas_id": session["canvas_id"],
            "role": "user",
            "content": payload.content,
            "context": context,
            "created_at": now,
        }
        rows = await self.client._request("POST", "/smart_image_agent_messages", json_body=[body])
        session_changes = {"updated_at": now, "last_activity_at": now}
        if not session.get("title"):
            session_changes["title"] = _session_title(payload.content)
        await self.client._request(
            "PATCH",
            f"/smart_image_agent_sessions?id=eq.{quote(session_id, safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body=session_changes,
        )
        return rows[0] if rows else body

    async def create_plan(self, user: CurrentUser, payload: ImageAgentPlanCreate) -> Dict[str, Any]:
        session = await self._get_record("smart_image_agent_sessions", payload.session_id, user)
        context = validate_session_context(session, payload.context)
        references = context["selected_images"]
        action = payload.action.strip() or infer_image_action(payload.message, context)
        if not payload.action and payload.count > 1 and action == "generate_image":
            action = "generate_image_set"
        if action not in SMART_IMAGE_AGENT_ACTIONS:
            raise HTTPException(status_code=422, detail="Unsupported image Agent action")
        active = await self.client._request(
            "GET",
            f"/smart_image_agent_plans?canvas_id=eq.{quote(session['canvas_id'], safe='')}&user_id=eq.{quote(user.id, safe='')}&status=eq.awaiting_confirmation&select=id&limit=1",
        )
        if active:
            raise HTTPException(status_code=409, detail="Finish or dismiss the current image plan before creating another")
        if payload.ratio not in SMART_IMAGE_AGENT_RATIOS:
            raise HTTPException(status_code=422, detail="Unsupported image ratio")
        references = assign_reference_roles(references, action)
        model, provider_id, quality, unit_points = resolve_smart_image_agent_model(payload.model, payload.quality)
        now = utc_now()
        body = {
            "id": str(uuid.uuid4()),
            "session_id": session["id"],
            "user_id": user.id,
            "team_id": session.get("team_id"),
            "project_id": session.get("project_id"),
            "canvas_id": session["canvas_id"],
            "action": action,
            "message": payload.message,
            "prompt": payload.prompt.strip() or payload.message.strip(),
            "references": references,
            "source_node_ids": [item["node_id"] for item in references if item.get("node_id")],
            "ratio": payload.ratio,
            "count": payload.count,
            "quality": quality,
            "provider_id": provider_id,
            "model": model,
            "fallback_used": False,
            "unit_points": unit_points,
            "estimated_points": unit_points * payload.count,
            "status": "awaiting_confirmation",
            "created_at": now,
            "updated_at": now,
            "confirmed_at": None,
        }
        rows = await self.client._request("POST", "/smart_image_agent_plans", json_body=[body])
        await self.client._request(
            "PATCH",
            f"/smart_image_agent_sessions?id=eq.{quote(session['id'], safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body={"updated_at": now, "last_activity_at": now},
        )
        return rows[0] if rows else body

    async def get_plan(self, user: CurrentUser, plan_id: str) -> Dict[str, Any]:
        return await self._get_record("smart_image_agent_plans", plan_id, user)

    async def update_plan(self, user: CurrentUser, plan_id: str, payload: ImageAgentPlanUpdate) -> Dict[str, Any]:
        plan = await self.get_plan(user, plan_id)
        if payload.status == "cancelled" and plan.get("status") in {"draft", "awaiting_confirmation"}:
            changes = {"status": "cancelled", "updated_at": utc_now()}
            rows = await self.client._request(
                "PATCH",
                f"/smart_image_agent_plans?id=eq.{quote(plan_id, safe='')}&user_id=eq.{quote(user.id, safe='')}",
                json_body=changes,
            )
            return rows[0] if rows else {**plan, **changes}
        if plan.get("status") not in {"draft", "awaiting_confirmation"}:
            raise HTTPException(status_code=409, detail="Confirmed image Agent plans cannot be edited")
        changes = payload.model_dump(exclude_none=True)
        if "ratio" in changes and changes["ratio"] not in SMART_IMAGE_AGENT_RATIOS:
            raise HTTPException(status_code=422, detail="Unsupported image ratio")
        quality = changes.get("quality", plan.get("quality") or "standard")
        count = int(changes.get("count", plan.get("count") or 1))
        selected_model = (
            changes["model"]
            if "model" in changes
            else None
            if "quality" in changes
            else plan.get("model")
        )
        model, provider_id, quality, unit_points = resolve_smart_image_agent_model(selected_model, quality)
        changes.update({
            "model": model,
            "provider_id": provider_id,
            "quality": quality,
            "unit_points": unit_points,
            "estimated_points": unit_points * count,
            "updated_at": utc_now(),
        })
        rows = await self.client._request(
            "PATCH",
            f"/smart_image_agent_plans?id=eq.{quote(plan_id, safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body=changes,
        )
        return rows[0] if rows else {**plan, **changes}

    async def confirm_plan(self, user: CurrentUser, plan_id: str) -> Dict[str, Any]:
        plan = await self.get_plan(user, plan_id)
        existing = await self.client._request(
            "GET",
            f"/smart_image_agent_runs?plan_id=eq.{quote(plan_id, safe='')}&user_id=eq.{quote(user.id, safe='')}&select=*&order=sequence.asc",
        )
        if existing:
            return {"plan": plan, "runs": existing}
        if plan.get("status") != "awaiting_confirmation":
            raise HTTPException(status_code=409, detail="Image Agent plan is not awaiting confirmation")
        now = utc_now()
        runs = [{
            "id": str(uuid.uuid4()),
            "plan_id": plan_id,
            "session_id": plan["session_id"],
            "user_id": user.id,
            "team_id": plan.get("team_id"),
            "canvas_id": plan["canvas_id"],
            "sequence": sequence,
            "attempt": 1,
            "status": "queued",
            "progress_stage": "queued",
            "provider_id": plan["provider_id"],
            "model": plan["model"],
            "result": {},
            "error": "",
            "created_at": now,
            "updated_at": now,
        } for sequence in range(1, int(plan["count"]) + 1)]
        created = await self.client._request("POST", "/smart_image_agent_runs", json_body=runs)
        plan_rows = await self.client._request(
            "PATCH",
            f"/smart_image_agent_plans?id=eq.{quote(plan_id, safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body={"status": "queued", "confirmed_at": now, "updated_at": now},
        )
        await self.client._request(
            "PATCH",
            f"/smart_image_agent_sessions?id=eq.{quote(plan['session_id'], safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body={"updated_at": now, "last_activity_at": now},
        )
        return {"plan": plan_rows[0] if plan_rows else {**plan, "status": "queued", "confirmed_at": now}, "runs": created or runs}

    async def list_runs(self, user: CurrentUser, canvas_id: str = "", session_id: str = "") -> List[Dict[str, Any]]:
        filters = [f"user_id=eq.{quote(user.id, safe='')}", "select=*", "order=created_at.desc"]
        if canvas_id:
            filters.append(f"canvas_id=eq.{quote(canvas_id, safe='')}")
        if session_id:
            filters.append(f"session_id=eq.{quote(session_id, safe='')}")
        return await self.client._request("GET", "/smart_image_agent_runs?" + "&".join(filters)) or []

    async def _refresh_plan_status(self, user: CurrentUser, plan_id: str) -> None:
        runs = await self.client._request(
            "GET",
            f"/smart_image_agent_runs?plan_id=eq.{quote(plan_id, safe='')}&user_id=eq.{quote(user.id, safe='')}&select=status",
        )
        statuses = {item.get("status") for item in runs or []}
        if "running" in statuses:
            status = "running"
        elif "queued" in statuses:
            status = "queued"
        elif statuses == {"succeeded"}:
            status = "succeeded"
        elif statuses == {"cancelled"}:
            status = "cancelled"
        else:
            status = "failed"
        await self.client._request(
            "PATCH",
            f"/smart_image_agent_plans?id=eq.{quote(plan_id, safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body={"status": status, "updated_at": utc_now()},
        )

    async def update_run(self, user: CurrentUser, run_id: str, payload: ImageAgentRunUpdate) -> Dict[str, Any]:
        run = await self._get_record("smart_image_agent_runs", run_id, user)
        allowed = {"queued": {"running", "cancelled"}, "running": {"running", "succeeded", "failed", "cancelled"}}
        if payload.status not in allowed.get(run.get("status"), set()):
            raise HTTPException(status_code=409, detail=f"Cannot change image Agent run from {run.get('status')} to {payload.status}")
        now = utc_now()
        changes: Dict[str, Any] = {
            "status": payload.status,
            "result": payload.result if payload.status == "succeeded" else {},
            "error": payload.error if payload.status == "failed" else "",
            "updated_at": now,
        }
        if payload.progress_stage:
            changes["progress_stage"] = payload.progress_stage
        elif payload.status in {"succeeded", "failed", "cancelled"}:
            changes["progress_stage"] = payload.status
        if payload.status == "running":
            changes["started_at"] = run.get("started_at") or now
        if payload.status in {"succeeded", "failed", "cancelled"}:
            changes["finished_at"] = now
        rows = await self.client._request(
            "PATCH",
            f"/smart_image_agent_runs?id=eq.{quote(run_id, safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body=changes,
        )
        await self._refresh_plan_status(user, run["plan_id"])
        await self.client._request(
            "PATCH",
            f"/smart_image_agent_sessions?id=eq.{quote(run['session_id'], safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body={"updated_at": now, "last_activity_at": now},
        )
        return rows[0] if rows else {**run, **changes}

    async def cancel_run(self, user: CurrentUser, run_id: str) -> Dict[str, Any]:
        return await self.update_run(user, run_id, ImageAgentRunUpdate(status="cancelled"))

    async def retry_run(self, user: CurrentUser, run_id: str) -> Dict[str, Any]:
        run = await self._get_record("smart_image_agent_runs", run_id, user)
        if run.get("status") not in {"failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="Only failed or cancelled image Agent runs can be retried")
        changes = {
            "status": "queued",
            "attempt": int(run.get("attempt") or 1) + 1,
            "result": {},
            "error": "",
            "started_at": None,
            "finished_at": None,
            "progress_stage": "queued",
            "updated_at": utc_now(),
        }
        rows = await self.client._request(
            "PATCH",
            f"/smart_image_agent_runs?id=eq.{quote(run_id, safe='')}&user_id=eq.{quote(user.id, safe='')}",
            json_body=changes,
        )
        await self._refresh_plan_status(user, run["plan_id"])
        return rows[0] if rows else {**run, **changes}

    async def list_results(self, user: CurrentUser, session_id: str, canvas_id: str = "") -> List[Dict[str, Any]]:
        await self._get_session(user, session_id, canvas_id)
        rows = await self.client._request(
            "GET",
            f"/smart_image_agent_runs?session_id=eq.{quote(session_id, safe='')}&user_id=eq.{quote(user.id, safe='')}&status=eq.succeeded&select=*&order=finished_at.desc",
        )
        return [{
            "run_id": item["id"],
            "plan_id": item["plan_id"],
            "session_id": item["session_id"],
            "sequence": item["sequence"],
            **(item.get("result") or {}),
            "created_at": item.get("finished_at") or item.get("updated_at"),
        } for item in rows or [] if item.get("result")]
