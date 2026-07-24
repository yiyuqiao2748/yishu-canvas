import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
import jwt
from fastapi import APIRouter, Cookie, Depends, File, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from team_storage import save_team_asset, safe_filename


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("YISHU_DATA_DIR", os.path.join(BASE_DIR, "data"))
LOCAL_TEAM_STORE = os.path.join(DATA_DIR, "team_cloud.json")

TEAM_ROLES = {"owner", "admin", "member"}
TEAM_ASSET_MAX_BYTES = int(os.getenv("TEAM_ASSET_MAX_BYTES", str(50 * 1024 * 1024)))


@dataclass
class TeamCloudSettings:
    supabase_url: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    supabase_jwt_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")
    supabase_jwt_audience: str = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    dev_bypass: bool = os.getenv("TEAM_AUTH_DEV_BYPASS", "").lower() in {"1", "true", "yes", "on"}
    cookie_secure: bool = os.getenv("TEAM_AUTH_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}
    cookie_name: str = os.getenv("TEAM_AUTH_COOKIE_NAME", "team_cloud_access_token")

    @property
    def supabase_ready(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def auth_ready(self) -> bool:
        return bool(self.supabase_jwt_secret or (self.supabase_url and self.supabase_anon_key)) or self.dev_bypass


settings = TeamCloudSettings()
router = APIRouter(prefix="/api/team-cloud", tags=["team-cloud"])


class CurrentUser(BaseModel):
    id: str
    email: str = ""
    provider: str = "supabase"


class TeamCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)


class CanvasCreateRequest(BaseModel):
    title: str = Field("未命名画布", min_length=1, max_length=120)
    data: Dict[str, Any] = Field(default_factory=dict)


class CanvasSaveRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    data: Dict[str, Any] = Field(default_factory=dict)
    base_version: Optional[int] = Field(None, ge=1)


class AuthEmailPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=6, max_length=128)


class MemberInviteRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    role: str = Field("member", pattern="^(owner|admin|member)$")


class RoleUpdateRequest(BaseModel):
    role: str = Field(..., pattern="^(owner|admin|member)$")


def now_ms() -> int:
    return int(time.time() * 1000)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def public_config() -> Dict[str, Any]:
    return {
        "auth_provider": "supabase",
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
        "auth_ready": settings.auth_ready,
        "supabase_ready": settings.supabase_ready,
        "dev_bypass": settings.dev_bypass,
        "cookie_auth": True,
    }


def decode_supabase_token(token: str) -> CurrentUser:
    if not settings.supabase_jwt_secret:
        raise HTTPException(status_code=503, detail="SUPABASE_JWT_SECRET 未配置")
    decode_kwargs = {
        "algorithms": ["HS256"],
        "audience": settings.supabase_jwt_audience,
    }
    if not settings.supabase_jwt_audience:
        decode_kwargs.pop("audience")
        decode_kwargs["options"] = {"verify_aud": False}
    try:
        payload = jwt.decode(token, settings.supabase_jwt_secret, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="登录凭证无效") from exc

    user_id = str(payload.get("sub") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="登录凭证缺少用户 ID")
    return CurrentUser(
        id=user_id,
        email=str(payload.get("email") or ""),
        provider="supabase",
    )


def current_user_from_supabase_payload(payload: Dict[str, Any]) -> CurrentUser:
    user_id = str(payload.get("id") or payload.get("sub") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="登录凭证缺少用户 ID")
    return CurrentUser(
        id=user_id,
        email=str(payload.get("email") or ""),
        provider="supabase",
    )


async def fetch_supabase_user(token: str) -> CurrentUser:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Supabase Auth 未配置")
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {token}",
            },
        )
    if resp.status_code in {401, 403}:
        raise HTTPException(status_code=401, detail="登录凭证无效")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Supabase Auth 请求失败: {resp.text}")
    return current_user_from_supabase_payload(resp.json())


async def authenticate_supabase_token(token: str) -> CurrentUser:
    if settings.supabase_jwt_secret:
        return decode_supabase_token(token)
    return await fetch_supabase_user(token)


async def require_user(
    authorization: Optional[str] = Header(default=None),
    team_cloud_access_token: Optional[str] = Cookie(default=None, alias=settings.cookie_name),
) -> CurrentUser:
    if authorization and authorization.lower().startswith("bearer "):
        return await authenticate_supabase_token(authorization[7:].strip())
    if team_cloud_access_token:
        return await authenticate_supabase_token(team_cloud_access_token)
    if settings.dev_bypass:
        return CurrentUser(
            id=os.getenv("TEAM_AUTH_DEV_USER_ID", "local-dev-user"),
            email=os.getenv("TEAM_AUTH_DEV_EMAIL", "dev@local.team"),
            provider="dev-bypass",
        )
    raise HTTPException(status_code=401, detail="请先登录")


def set_auth_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        settings.cookie_name,
        access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=60 * 60,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(settings.cookie_name, path="/")


async def supabase_auth_request(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Supabase Auth 未配置")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{settings.supabase_url}/auth/v1/{path}",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {settings.supabase_anon_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 400:
        detail = "登录服务请求失败"
        try:
            body = response.json()
            detail = body.get("msg") or body.get("message") or body.get("error_description") or detail
        except ValueError:
            detail = response.text[:200] or detail
        raise HTTPException(status_code=response.status_code, detail=detail)
    return response.json()


def sanitize_auth_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    user = data.get("user") or {}
    session_ready = bool(data.get("access_token"))
    return {
        "session_ready": session_ready,
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "created_at": user.get("created_at"),
        },
    }


class LocalTeamStore:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()

    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {"teams": [], "members": [], "invitations": [], "projects": [], "canvases": [], "canvas_versions": [], "assets": []}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            data = {}
        return {
            "teams": data.get("teams") or [],
            "members": data.get("members") or [],
            "invitations": data.get("invitations") or [],
            "projects": data.get("projects") or [],
            "canvases": data.get("canvases") or [],
            "canvas_versions": data.get("canvas_versions") or [],
            "assets": data.get("assets") or [],
        }

    def _write(self, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)

    def list_user_teams(self, user: CurrentUser) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            memberships = [m for m in data["members"] if m.get("user_id") == user.id]
            teams = {team["id"]: team for team in data["teams"]}
            result = []
            for member in memberships:
                team = teams.get(member.get("team_id"))
                if team:
                    result.append({**team, "role": member.get("role", "member")})
            return result

    def create_team(self, user: CurrentUser, name: str) -> Dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise HTTPException(status_code=400, detail="团队名称不能为空")
        with self.lock:
            data = self._read()
            team = {
                "id": str(uuid.uuid4()),
                "name": clean_name,
                "owner_id": user.id,
                "created_at": now_ms(),
                "updated_at": now_ms(),
            }
            data["teams"].append(team)
            data["members"].append({
                "id": str(uuid.uuid4()),
                "team_id": team["id"],
                "user_id": user.id,
                "email": user.email,
                "role": "owner",
                "created_at": now_ms(),
            })
            self._write(data)
            return {**team, "role": "owner"}

    def list_members(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            return [m for m in data["members"] if m.get("team_id") == team_id]

    def invite_member(self, user: CurrentUser, team_id: str, email: str, role: str) -> Dict[str, Any]:
        if role not in TEAM_ROLES:
            raise HTTPException(status_code=400, detail="成员角色无效")
        with self.lock:
            data = self._read()
            actor = self._require_member(data, user.id, team_id)
            if actor.get("role") not in {"owner", "admin"}:
                raise HTTPException(status_code=403, detail="没有邀请成员的权限")
            invitation = {
                "id": str(uuid.uuid4()),
                "team_id": team_id,
                "email": normalize_email(email),
                "role": role,
                "status": "pending",
                "invited_by": user.id,
                "created_at": now_ms(),
            }
            data["invitations"].append(invitation)
            self._write(data)
            return invitation

    def list_projects(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            return [p for p in data["projects"] if p.get("team_id") == team_id and not p.get("archived_at")]

    def create_project(self, user: CurrentUser, team_id: str, name: str, description: str = "") -> Dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise HTTPException(status_code=400, detail="项目名称不能为空")
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            project = {
                "id": str(uuid.uuid4()),
                "team_id": team_id,
                "name": clean_name,
                "description": description.strip(),
                "created_by": user.id,
                "archived_at": None,
                "created_at": now_ms(),
                "updated_at": now_ms(),
            }
            data["projects"].append(project)
            self._write(data)
            return project

    def list_canvases(self, user: CurrentUser, project_id: str) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            project = self._require_project_member(data, user.id, project_id)
            return [
                self._canvas_summary(canvas)
                for canvas in data["canvases"]
                if canvas.get("project_id") == project["id"]
            ]

    def create_canvas(self, user: CurrentUser, project_id: str, title: str, canvas_data: Dict[str, Any]) -> Dict[str, Any]:
        clean_title = title.strip() or "未命名画布"
        with self.lock:
            data = self._read()
            project = self._require_project_member(data, user.id, project_id)
            canvas = {
                "id": str(uuid.uuid4()),
                "team_id": project["team_id"],
                "project_id": project["id"],
                "title": clean_title,
                "data": canvas_data or {},
                "version": 1,
                "created_by": user.id,
                "updated_by": user.id,
                "created_at": now_ms(),
                "updated_at": now_ms(),
            }
            data["canvases"].append(canvas)
            data["canvas_versions"].append(self._canvas_version_row(canvas))
            self._write(data)
            return canvas

    def get_canvas(self, user: CurrentUser, canvas_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            canvas = self._find_canvas(data, canvas_id)
            if not canvas:
                raise HTTPException(status_code=404, detail="画布不存在")
            self._require_member(data, user.id, canvas["team_id"])
            return canvas

    def save_canvas(self, user: CurrentUser, canvas_id: str, payload: CanvasSaveRequest) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            canvas = self._find_canvas(data, canvas_id)
            if not canvas:
                raise HTTPException(status_code=404, detail="画布不存在")
            self._require_member(data, user.id, canvas["team_id"])
            if payload.base_version is not None and payload.base_version != canvas.get("version"):
                raise HTTPException(status_code=409, detail={"message": "画布已被更新，请刷新后再保存", "canvas": canvas})
            canvas["data"] = payload.data or {}
            if payload.title is not None:
                canvas["title"] = payload.title.strip() or canvas["title"]
            canvas["version"] = int(canvas.get("version") or 1) + 1
            canvas["updated_by"] = user.id
            canvas["updated_at"] = now_ms()
            data["canvas_versions"].append(self._canvas_version_row(canvas))
            self._write(data)
            return canvas

    def list_assets(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            return [asset for asset in data["assets"] if asset.get("team_id") == team_id]

    def create_asset(self, user: CurrentUser, team_id: str, asset: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            record = {
                "id": asset.get("id") or str(uuid.uuid4()),
                "team_id": team_id,
                "project_id": asset.get("project_id"),
                "canvas_id": asset.get("canvas_id"),
                "kind": asset.get("kind") or "file",
                "name": asset.get("name") or "asset",
                "storage_provider": asset.get("storage_provider") or "r2",
                "storage_key": asset.get("storage_key") or "",
                "public_url": asset.get("public_url") or "",
                "mime_type": asset.get("mime_type") or "",
                "byte_size": int(asset.get("byte_size") or 0),
                "storage_provider": asset.get("storage_provider") or "local",
                "created_by": user.id,
                "created_at": now_ms(),
            }
            data["assets"].append(record)
            self._write(data)
            return record

    def _require_member(self, data: Dict[str, Any], user_id: str, team_id: str) -> Dict[str, Any]:
        for member in data["members"]:
            if member.get("team_id") == team_id and member.get("user_id") == user_id:
                return member
        raise HTTPException(status_code=403, detail="没有访问该团队的权限")

    def _require_project_member(self, data: Dict[str, Any], user_id: str, project_id: str) -> Dict[str, Any]:
        for project in data["projects"]:
            if project.get("id") == project_id and not project.get("archived_at"):
                self._require_member(data, user_id, project["team_id"])
                return project
        raise HTTPException(status_code=404, detail="项目不存在")

    def _find_canvas(self, data: Dict[str, Any], canvas_id: str) -> Optional[Dict[str, Any]]:
        for canvas in data["canvases"]:
            if canvas.get("id") == canvas_id:
                return canvas
        return None

    def _canvas_summary(self, canvas: Dict[str, Any]) -> Dict[str, Any]:
        return {key: canvas.get(key) for key in (
            "id",
            "team_id",
            "project_id",
            "title",
            "version",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        )}

    def _canvas_version_row(self, canvas: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "canvas_id": canvas["id"],
            "version": canvas["version"],
            "data": canvas.get("data") or {},
            "created_by": canvas["updated_by"],
            "created_at": now_ms(),
        }


class SupabaseTeamStore:
    def __init__(self, base_url: str, service_key: str):
        self.rest_url = f"{base_url}/rest/v1"
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, *, json_body: Any = None) -> Any:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(
                method,
                f"{self.rest_url}{path}",
                headers={**self.headers, "Prefer": "return=representation"},
                json=json_body,
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Supabase 请求失败：{response.text[:200]}")
        if not response.content:
            return None
        return response.json()

    async def list_user_teams(self, user: CurrentUser) -> List[Dict[str, Any]]:
        rows = await self._request(
            "GET",
            f"/team_members?select=role,teams(id,name,owner_id,created_at,updated_at)&user_id=eq.{user.id}",
        )
        return [{**row["teams"], "role": row["role"]} for row in rows if row.get("teams")]

    async def create_team(self, user: CurrentUser, name: str) -> Dict[str, Any]:
        team_rows = await self._request(
            "POST",
            "/teams",
            json_body=[{"name": name.strip(), "owner_id": user.id}],
        )
        team = team_rows[0]
        await self._request(
            "POST",
            "/team_members",
            json_body=[{
                "team_id": team["id"],
                "user_id": user.id,
                "email": user.email,
                "role": "owner",
            }],
        )
        return {**team, "role": "owner"}

    async def list_members(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        await self._require_member(user.id, team_id)
        return await self._request("GET", f"/team_members?team_id=eq.{team_id}&select=*")

    async def invite_member(self, user: CurrentUser, team_id: str, email: str, role: str) -> Dict[str, Any]:
        actor = await self._require_member(user.id, team_id)
        if actor.get("role") not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="没有邀请成员的权限")
        rows = await self._request(
            "POST",
            "/invitations",
            json_body=[{
                "team_id": team_id,
                "email": normalize_email(email),
                "role": role,
                "invited_by": user.id,
                "status": "pending",
            }],
        )
        return rows[0]

    async def list_projects(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        await self._require_member(user.id, team_id)
        return await self._request(
            "GET",
            f"/projects?team_id=eq.{team_id}&archived_at=is.null&order=updated_at.desc&select=*",
        )

    async def create_project(self, user: CurrentUser, team_id: str, name: str, description: str = "") -> Dict[str, Any]:
        await self._require_member(user.id, team_id)
        rows = await self._request(
            "POST",
            "/projects",
            json_body=[{
                "team_id": team_id,
                "name": name.strip(),
                "description": description.strip(),
                "created_by": user.id,
            }],
        )
        return rows[0]

    async def list_canvases(self, user: CurrentUser, project_id: str) -> List[Dict[str, Any]]:
        project = await self._require_project_member(user.id, project_id)
        return await self._request(
            "GET",
            f"/canvases?team_id=eq.{project['team_id']}&project_id=eq.{project_id}&order=updated_at.desc&select=id,team_id,project_id,title,version,created_by,updated_by,created_at,updated_at",
        )

    async def create_canvas(self, user: CurrentUser, project_id: str, title: str, canvas_data: Dict[str, Any]) -> Dict[str, Any]:
        project = await self._require_project_member(user.id, project_id)
        rows = await self._request(
            "POST",
            "/canvases",
            json_body=[{
                "team_id": project["team_id"],
                "project_id": project_id,
                "title": title.strip() or "未命名画布",
                "data": canvas_data or {},
                "version": 1,
                "created_by": user.id,
                "updated_by": user.id,
            }],
        )
        canvas = rows[0]
        await self._request(
            "POST",
            "/canvas_versions",
            json_body=[{
                "canvas_id": canvas["id"],
                "version": canvas["version"],
                "data": canvas.get("data") or {},
                "created_by": user.id,
            }],
        )
        return canvas

    async def get_canvas(self, user: CurrentUser, canvas_id: str) -> Dict[str, Any]:
        rows = await self._request("GET", f"/canvases?id=eq.{canvas_id}&select=*")
        if not rows:
            raise HTTPException(status_code=404, detail="画布不存在")
        canvas = rows[0]
        await self._require_member(user.id, canvas["team_id"])
        return canvas

    async def save_canvas(self, user: CurrentUser, canvas_id: str, payload: CanvasSaveRequest) -> Dict[str, Any]:
        canvas = await self.get_canvas(user, canvas_id)
        if payload.base_version is not None and payload.base_version != canvas.get("version"):
            raise HTTPException(status_code=409, detail={"message": "画布已被更新，请刷新后再保存", "canvas": canvas})
        next_version = int(canvas.get("version") or 1) + 1
        patch = {
            "data": payload.data or {},
            "version": next_version,
            "updated_by": user.id,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if payload.title is not None:
            patch["title"] = payload.title.strip() or canvas.get("title") or "未命名画布"
        rows = await self._request(
            "PATCH",
            f"/canvases?id=eq.{canvas_id}",
            json_body=patch,
        )
        updated = rows[0]
        await self._request(
            "POST",
            "/canvas_versions",
            json_body=[{
                "canvas_id": canvas_id,
                "version": updated["version"],
                "data": updated.get("data") or {},
                "created_by": user.id,
            }],
        )
        return updated

    async def list_assets(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        await self._require_member(user.id, team_id)
        return await self._request(
            "GET",
            f"/assets?team_id=eq.{team_id}&order=created_at.desc&select=*",
        )

    async def create_asset(self, user: CurrentUser, team_id: str, asset: Dict[str, Any]) -> Dict[str, Any]:
        await self._require_member(user.id, team_id)
        rows = await self._request(
            "POST",
            "/assets",
            json_body=[{
                "id": asset.get("id"),
                "team_id": team_id,
                "project_id": asset.get("project_id"),
                "canvas_id": asset.get("canvas_id"),
                "kind": asset.get("kind") or "file",
                "name": asset.get("name") or "asset",
                "storage_key": asset.get("storage_key") or "",
                "public_url": asset.get("public_url") or "",
                "mime_type": asset.get("mime_type") or "",
                "byte_size": int(asset.get("byte_size") or 0),
                "created_by": user.id,
            }],
        )
        return rows[0]

    async def _require_member(self, user_id: str, team_id: str) -> Dict[str, Any]:
        rows = await self._request(
            "GET",
            f"/team_members?team_id=eq.{team_id}&user_id=eq.{user_id}&select=*",
        )
        if not rows:
            raise HTTPException(status_code=403, detail="没有访问该团队的权限")
        return rows[0]

    async def _require_project_member(self, user_id: str, project_id: str) -> Dict[str, Any]:
        rows = await self._request(
            "GET",
            f"/projects?id=eq.{project_id}&archived_at=is.null&select=*",
        )
        if not rows:
            raise HTTPException(status_code=404, detail="项目不存在")
        project = rows[0]
        await self._require_member(user_id, project["team_id"])
        return project


local_store = LocalTeamStore(LOCAL_TEAM_STORE)
supabase_store = SupabaseTeamStore(settings.supabase_url, settings.supabase_service_role_key) if settings.supabase_ready else None


def active_store():
    return supabase_store or local_store


@router.get("/config")
async def team_cloud_config() -> Dict[str, Any]:
    return public_config()


@router.post("/auth/signup")
async def signup(payload: AuthEmailPasswordRequest, response: Response) -> Dict[str, Any]:
    data = await supabase_auth_request("signup", {
        "email": normalize_email(payload.email),
        "password": payload.password,
    })
    if data.get("access_token"):
        set_auth_cookie(response, data["access_token"])
    return sanitize_auth_payload(data)


@router.post("/auth/login")
async def login(payload: AuthEmailPasswordRequest, response: Response) -> Dict[str, Any]:
    data = await supabase_auth_request("token?grant_type=password", {
        "email": normalize_email(payload.email),
        "password": payload.password,
    })
    if not data.get("access_token"):
        raise HTTPException(status_code=401, detail="登录失败")
    set_auth_cookie(response, data["access_token"])
    return sanitize_auth_payload(data)


@router.post("/auth/logout")
async def logout(response: Response) -> Dict[str, Any]:
    clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me")
async def team_cloud_me(user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    teams = await maybe_await(active_store().list_user_teams(user))
    return {"user": user.model_dump(), "teams": teams}


@router.get("/teams")
async def list_teams(user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    teams = await maybe_await(active_store().list_user_teams(user))
    return {"teams": teams}


@router.post("/teams")
async def create_team(payload: TeamCreateRequest, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    team = await maybe_await(active_store().create_team(user, payload.name))
    return {"team": team}


@router.get("/teams/{team_id}/members")
async def list_team_members(team_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    members = await maybe_await(active_store().list_members(user, team_id))
    return {"members": members}


@router.post("/teams/{team_id}/invitations")
async def invite_team_member(
    team_id: str,
    payload: MemberInviteRequest,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    invitation = await maybe_await(active_store().invite_member(user, team_id, payload.email, payload.role))
    return {"invitation": invitation}


@router.get("/teams/{team_id}/projects")
async def list_team_projects(team_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    projects = await maybe_await(active_store().list_projects(user, team_id))
    return {"projects": projects}


@router.post("/teams/{team_id}/projects")
async def create_team_project(
    team_id: str,
    payload: ProjectCreateRequest,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    project = await maybe_await(active_store().create_project(user, team_id, payload.name, payload.description))
    return {"project": project}


@router.get("/projects/{project_id}/canvases")
async def list_project_canvases(project_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    canvases = await maybe_await(active_store().list_canvases(user, project_id))
    return {"canvases": canvases}


@router.post("/projects/{project_id}/canvases")
async def create_project_canvas(
    project_id: str,
    payload: CanvasCreateRequest,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    canvas = await maybe_await(active_store().create_canvas(user, project_id, payload.title, payload.data))
    return {"canvas": canvas}


@router.get("/canvases/{canvas_id}")
async def get_team_canvas(canvas_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    canvas = await maybe_await(active_store().get_canvas(user, canvas_id))
    return {"canvas": canvas}


@router.patch("/canvases/{canvas_id}")
async def save_team_canvas(
    canvas_id: str,
    payload: CanvasSaveRequest,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    canvas = await maybe_await(active_store().save_canvas(user, canvas_id, payload))
    return {"canvas": canvas}


@router.get("/teams/{team_id}/assets")
async def list_team_assets(team_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    assets = await maybe_await(active_store().list_assets(user, team_id))
    return {"assets": assets}


@router.post("/teams/{team_id}/assets")
async def upload_team_asset(
    team_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    content = await file.read()
    if len(content) > TEAM_ASSET_MAX_BYTES:
        raise HTTPException(status_code=413, detail="素材文件过大")
    asset_id = str(uuid.uuid4())
    filename = safe_filename(file.filename or asset_id)
    stored = save_team_asset(
        content,
        team_id=team_id,
        filename=filename,
        content_type=file.content_type or "",
        asset_id=asset_id,
    )
    asset = await maybe_await(active_store().create_asset(user, team_id, {
        "id": asset_id,
        "kind": "image" if (file.content_type or "").startswith("image/") else "file",
        "name": filename,
        "mime_type": file.content_type or "",
        "byte_size": len(content),
        **stored,
    }))
    return {"asset": asset}


async def maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
