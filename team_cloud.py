import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOCAL_TEAM_STORE = os.path.join(DATA_DIR, "team_cloud.json")

TEAM_ROLES = {"owner", "admin", "member"}


@dataclass
class TeamCloudSettings:
    supabase_url: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    supabase_jwt_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")
    supabase_jwt_audience: str = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    dev_bypass: bool = os.getenv("TEAM_AUTH_DEV_BYPASS", "").lower() in {"1", "true", "yes", "on"}

    @property
    def supabase_ready(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def auth_ready(self) -> bool:
        return bool(self.supabase_jwt_secret) or self.dev_bypass


settings = TeamCloudSettings()
router = APIRouter(prefix="/api/team-cloud", tags=["team-cloud"])


class CurrentUser(BaseModel):
    id: str
    email: str = ""
    provider: str = "supabase"


class TeamCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


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


async def require_user(authorization: Optional[str] = Header(default=None)) -> CurrentUser:
    if authorization and authorization.lower().startswith("bearer "):
        return decode_supabase_token(authorization[7:].strip())
    if settings.dev_bypass:
        return CurrentUser(
            id=os.getenv("TEAM_AUTH_DEV_USER_ID", "local-dev-user"),
            email=os.getenv("TEAM_AUTH_DEV_EMAIL", "dev@local.team"),
            provider="dev-bypass",
        )
    raise HTTPException(status_code=401, detail="请先登录")


class LocalTeamStore:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()

    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {"teams": [], "members": [], "invitations": []}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            data = {}
        return {
            "teams": data.get("teams") or [],
            "members": data.get("members") or [],
            "invitations": data.get("invitations") or [],
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

    def _require_member(self, data: Dict[str, Any], user_id: str, team_id: str) -> Dict[str, Any]:
        for member in data["members"]:
            if member.get("team_id") == team_id and member.get("user_id") == user_id:
                return member
        raise HTTPException(status_code=403, detail="没有访问该团队的权限")


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

    async def _require_member(self, user_id: str, team_id: str) -> Dict[str, Any]:
        rows = await self._request(
            "GET",
            f"/team_members?team_id=eq.{team_id}&user_id=eq.{user_id}&select=*",
        )
        if not rows:
            raise HTTPException(status_code=403, detail="没有访问该团队的权限")
        return rows[0]


local_store = LocalTeamStore(LOCAL_TEAM_STORE)
supabase_store = SupabaseTeamStore(settings.supabase_url, settings.supabase_service_role_key) if settings.supabase_ready else None


def active_store():
    return supabase_store or local_store


@router.get("/config")
async def team_cloud_config() -> Dict[str, Any]:
    return public_config()


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


async def maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
