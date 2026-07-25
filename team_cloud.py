import base64
import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
import jwt
from fastapi import APIRouter, Cookie, Depends, File, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from team_storage import build_image_thumbnail, delete_team_asset_file, save_team_asset, safe_filename


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
    team_api_secret_key: str = os.getenv("TEAM_API_SECRET_KEY", "")

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


class AuthPasswordUpdateRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class MemberInviteRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    role: str = Field("member", pattern="^(owner|admin|member)$")


class RoleUpdateRequest(BaseModel):
    role: str = Field(..., pattern="^(owner|admin|member)$")


class TeamApiProviderSaveRequest(BaseModel):
    label: str = Field("API", min_length=1, max_length=80)
    base_url: str = Field("", max_length=500)
    protocol: str = Field("openai", max_length=40)
    enabled: bool = True
    api_key: str = Field("", max_length=4096)
    wallet_api_key: str = Field("", max_length=4096)
    clear_api_key: bool = False
    clear_wallet_api_key: bool = False


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
        try:
            return decode_supabase_token(token)
        except HTTPException as exc:
            if exc.status_code != 401 or not (settings.supabase_url and settings.supabase_anon_key):
                raise
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


async def supabase_update_password(access_token: str, password: str) -> Dict[str, Any]:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Supabase Auth 未配置")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.put(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"password": password},
        )
    if response.status_code >= 400:
        detail = "密码更新失败"
        try:
            body = response.json()
            detail = body.get("msg") or body.get("message") or body.get("error_description") or detail
        except ValueError:
            detail = response.text[:200] or detail
        raise HTTPException(status_code=response.status_code, detail=detail)
    return response.json()


def sanitize_auth_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    user = data.get("user") or {}
    access_token = str(data.get("access_token") or "")
    session_ready = bool(data.get("access_token"))
    payload = {
        "session_ready": session_ready,
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "created_at": user.get("created_at"),
        },
    }
    if access_token:
        payload["access_token"] = access_token
    return payload


def asset_reference_terms(asset: Dict[str, Any]) -> List[str]:
    return [
        str(asset.get(key) or "").strip()
        for key in ("public_url", "storage_key", "thumbnail_url", "thumbnail_storage_key")
        if str(asset.get(key) or "").strip()
    ]


def data_references_asset(value: Any, terms: List[str]) -> bool:
    if not terms:
        return False
    if isinstance(value, str):
        return value in terms
    if isinstance(value, dict):
        return any(data_references_asset(item, terms) for item in value.values())
    if isinstance(value, list):
        return any(data_references_asset(item, terms) for item in value)
    return False


def canvas_asset_references(canvases: List[Dict[str, Any]], asset: Dict[str, Any]) -> List[Dict[str, Any]]:
    terms = asset_reference_terms(asset)
    return [
        {
            "id": canvas.get("id"),
            "title": canvas.get("title") or "未命名画布",
            "project_id": canvas.get("project_id"),
        }
        for canvas in canvases
        if data_references_asset(canvas.get("data"), terms)
    ]


def require_asset_delete_permission(member: Dict[str, Any], user: CurrentUser, asset: Dict[str, Any]) -> None:
    if member.get("role") in {"owner", "admin"}:
        return
    if asset.get("created_by") == user.id:
        return
    raise HTTPException(status_code=403, detail="只有管理员或素材上传者可以删除该素材")

def normalize_provider_id(value: str) -> str:
    provider_id = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", provider_id):
        raise HTTPException(status_code=400, detail="Invalid provider id")
    return provider_id


def normalize_team_api_base_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Base URL must start with http:// or https://")
    return url


def normalize_team_api_protocol(value: str) -> str:
    protocol = str(value or "openai").strip().lower()
    allowed = {"openai", "runninghub", "volcengine", "gemini", "apimart"}
    if protocol not in allowed:
        raise HTTPException(status_code=400, detail="Invalid API protocol")
    return protocol


def require_api_admin(member: Dict[str, Any]) -> None:
    if member.get("role") not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only team owners and admins can manage API keys")


def require_team_admin(member: Dict[str, Any]) -> None:
    if member.get("role") not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only team owners and admins can delete projects and canvases")


def require_team_owner(member: Dict[str, Any]) -> None:
    if member.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only the team owner can delete this team")


def team_api_secret_material() -> str:
    if settings.team_api_secret_key:
        return settings.team_api_secret_key
    if settings.supabase_service_role_key:
        return settings.supabase_service_role_key
    if settings.dev_bypass:
        return "local-dev-team-api-secret"
    raise HTTPException(status_code=503, detail="TEAM_API_SECRET_KEY is not configured")


def team_api_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Missing cryptography dependency") from exc
    digest = hashlib.sha256(team_api_secret_material().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_team_api_config(config: Dict[str, Any]) -> Dict[str, Any]:
    raw = json.dumps(config or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = team_api_fernet().encrypt(raw).decode("ascii")
    return {"v": 1, "alg": "fernet-sha256", "ciphertext": token}


def decrypt_team_api_config(encrypted: Any) -> Dict[str, Any]:
    if not encrypted:
        return {}
    if isinstance(encrypted, str):
        try:
            encrypted = json.loads(encrypted)
        except ValueError:
            return {}
    if not isinstance(encrypted, dict):
        return {}
    token = str(encrypted.get("ciphertext") or "")
    if not token:
        return {}
    try:
        raw = team_api_fernet().decrypt(token.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def mask_team_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    tail = text[-4:] if len(text) > 4 else text
    return f"********{tail}"


def team_api_config_from_payload(payload: TeamApiProviderSaveRequest, current: Dict[str, Any] = None) -> Dict[str, Any]:
    current = current or {}
    api_key = str(current.get("api_key") or "")
    wallet_api_key = str(current.get("wallet_api_key") or "")
    if payload.clear_api_key:
        api_key = ""
    elif payload.api_key.strip():
        api_key = payload.api_key.strip()
    if payload.clear_wallet_api_key:
        wallet_api_key = ""
    elif payload.wallet_api_key.strip():
        wallet_api_key = payload.wallet_api_key.strip()
    return {
        "base_url": normalize_team_api_base_url(payload.base_url),
        "protocol": normalize_team_api_protocol(payload.protocol),
        "enabled": bool(payload.enabled),
        "api_key": api_key,
        "wallet_api_key": wallet_api_key,
    }


def public_team_api_provider(record: Dict[str, Any]) -> Dict[str, Any]:
    config = decrypt_team_api_config(record.get("encrypted_config"))
    api_key = str(config.get("api_key") or "")
    wallet_api_key = str(config.get("wallet_api_key") or "")
    return {
        "id": record.get("provider_id") or record.get("id") or "",
        "team_id": record.get("team_id") or "",
        "provider_id": record.get("provider_id") or "",
        "label": record.get("label") or record.get("provider_id") or "API",
        "base_url": config.get("base_url") or "",
        "protocol": config.get("protocol") or "openai",
        "enabled": bool(config.get("enabled", True)),
        "has_api_key": bool(api_key),
        "api_key_preview": mask_team_secret(api_key),
        "has_wallet_api_key": bool(wallet_api_key),
        "wallet_api_key_preview": mask_team_secret(wallet_api_key),
        "created_by": record.get("created_by") or "",
        "updated_by": record.get("updated_by") or "",
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


class LocalTeamStore:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()

    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {"teams": [], "members": [], "invitations": [], "projects": [], "canvases": [], "canvas_versions": [], "assets": [], "api_providers": [], "generation_logs": []}
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
            "api_providers": data.get("api_providers") or [],
            "generation_logs": data.get("generation_logs") or [],
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

    def delete_team(self, user: CurrentUser, team_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            team = next((item for item in data["teams"] if item.get("id") == team_id), None)
            if not team:
                raise HTTPException(status_code=404, detail="Team not found")
            member = self._require_member(data, user.id, team_id)
            require_team_owner(member)
            canvas_ids = {item.get("id") for item in data["canvases"] if item.get("team_id") == team_id}
            asset_records = [item for item in data["assets"] if item.get("team_id") == team_id]
            data["teams"] = [item for item in data["teams"] if item.get("id") != team_id]
            data["members"] = [item for item in data["members"] if item.get("team_id") != team_id]
            data["invitations"] = [item for item in data["invitations"] if item.get("team_id") != team_id]
            data["projects"] = [item for item in data["projects"] if item.get("team_id") != team_id]
            data["canvases"] = [item for item in data["canvases"] if item.get("team_id") != team_id]
            data["canvas_versions"] = [
                item for item in data["canvas_versions"] if item.get("canvas_id") not in canvas_ids
            ]
            data["assets"] = [item for item in data["assets"] if item.get("team_id") != team_id]
            data["api_providers"] = [item for item in data["api_providers"] if item.get("team_id") != team_id]
            data["generation_logs"] = [item for item in data["generation_logs"] if item.get("team_id") != team_id]
            self._write(data)
        removed_files = [
            key
            for asset in asset_records
            for key in (asset.get("storage_key"), asset.get("thumbnail_storage_key"))
            if key and delete_team_asset_file(str(key))
        ]
        return {"team": {**team, "role": member.get("role")}, "removed_files": removed_files}

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

    def delete_project(self, user: CurrentUser, project_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            project = self._require_project_member(data, user.id, project_id)
            member = self._require_member(data, user.id, project["team_id"])
            require_team_admin(member)
            canvas_ids = {item.get("id") for item in data["canvases"] if item.get("project_id") == project_id}
            data["projects"] = [item for item in data["projects"] if item.get("id") != project_id]
            data["canvases"] = [item for item in data["canvases"] if item.get("project_id") != project_id]
            data["canvas_versions"] = [
                item for item in data["canvas_versions"] if item.get("canvas_id") not in canvas_ids
            ]
            for asset in data["assets"]:
                if asset.get("project_id") == project_id:
                    asset["project_id"] = None
                if asset.get("canvas_id") in canvas_ids:
                    asset["canvas_id"] = None
            for log in data["generation_logs"]:
                if log.get("project_id") == project_id:
                    log["project_id"] = ""
                if log.get("canvas_id") in canvas_ids:
                    log["canvas_id"] = ""
            self._write(data)
            return {"project": project}

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

    def delete_canvas(self, user: CurrentUser, canvas_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            canvas = self._find_canvas(data, canvas_id)
            if not canvas:
                raise HTTPException(status_code=404, detail="Canvas not found")
            member = self._require_member(data, user.id, canvas["team_id"])
            require_team_admin(member)
            data["canvases"] = [item for item in data["canvases"] if item.get("id") != canvas_id]
            data["canvas_versions"] = [
                item for item in data["canvas_versions"] if item.get("canvas_id") != canvas_id
            ]
            for asset in data["assets"]:
                if asset.get("canvas_id") == canvas_id:
                    asset["canvas_id"] = None
            for log in data["generation_logs"]:
                if log.get("canvas_id") == canvas_id:
                    log["canvas_id"] = ""
            self._write(data)
            return {"canvas": self._canvas_summary(canvas)}

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

    def list_canvas_versions(self, user: CurrentUser, canvas_id: str) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            canvas = self._find_canvas(data, canvas_id)
            if not canvas:
                raise HTTPException(status_code=404, detail="Canvas not found")
            self._require_member(data, user.id, canvas["team_id"])
            versions = [
                self._canvas_version_summary(row)
                for row in data["canvas_versions"]
                if row.get("canvas_id") == canvas_id
            ]
            return sorted(versions, key=lambda item: int(item.get("version") or 0), reverse=True)

    def restore_canvas_version(self, user: CurrentUser, canvas_id: str, version: int) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            canvas = self._find_canvas(data, canvas_id)
            if not canvas:
                raise HTTPException(status_code=404, detail="Canvas not found")
            self._require_member(data, user.id, canvas["team_id"])
            source = next(
                (
                    row
                    for row in data["canvas_versions"]
                    if row.get("canvas_id") == canvas_id and int(row.get("version") or 0) == int(version)
                ),
                None,
            )
            if not source:
                raise HTTPException(status_code=404, detail="Canvas version not found")
            restored_data = json.loads(json.dumps(source.get("data") or {}, ensure_ascii=False))
            canvas["data"] = restored_data
            canvas["title"] = str(restored_data.get("title") or canvas.get("title") or "Untitled canvas").strip() or "Untitled canvas"
            canvas["version"] = int(canvas.get("version") or 1) + 1
            canvas["updated_by"] = user.id
            canvas["updated_at"] = now_ms()
            data["canvas_versions"].append(self._canvas_version_row(canvas))
            self._write(data)
            return {"canvas": canvas, "restored_version": self._canvas_version_summary(source)}

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
                "storage_key": asset.get("storage_key") or "",
                "public_url": asset.get("public_url") or "",
                "thumbnail_url": asset.get("thumbnail_url") or "",
                "thumbnail_storage_key": asset.get("thumbnail_storage_key") or "",
                "mime_type": asset.get("mime_type") or "",
                "byte_size": int(asset.get("byte_size") or 0),
                "width": asset.get("width"),
                "height": asset.get("height"),
                "storage_provider": asset.get("storage_provider") or "local",
                "created_by": user.id,
                "created_at": now_ms(),
            }
            data["assets"].append(record)
            self._write(data)
            return record

    def delete_asset(self, user: CurrentUser, team_id: str, asset_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            member = self._require_member(data, user.id, team_id)
            asset = self._find_asset(data, team_id, asset_id)
            if not asset:
                raise HTTPException(status_code=404, detail="团队素材不存在")
            require_asset_delete_permission(member, user, asset)
            references = canvas_asset_references(
                [canvas for canvas in data["canvases"] if canvas.get("team_id") == team_id],
                asset,
            )
            if references:
                raise HTTPException(
                    status_code=409,
                    detail={"message": "素材仍被画布使用，无法删除", "references": references},
                )
            data["assets"] = [
                item
                for item in data["assets"]
                if not (item.get("team_id") == team_id and item.get("id") == asset_id)
            ]
            self._write(data)
        removed_files = [
            key
            for key in (asset.get("storage_key"), asset.get("thumbnail_storage_key"))
            if key and delete_team_asset_file(str(key))
        ]
        return {"asset": asset, "removed_files": removed_files, "references": []}

    def list_api_providers(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            providers = [
                public_team_api_provider(record)
                for record in data["api_providers"]
                if record.get("team_id") == team_id
            ]
            return sorted(providers, key=lambda item: item.get("provider_id") or "")

    def upsert_api_provider(self, user: CurrentUser, team_id: str, provider_id: str, payload: TeamApiProviderSaveRequest) -> Dict[str, Any]:
        provider_id = normalize_provider_id(provider_id)
        with self.lock:
            data = self._read()
            member = self._require_member(data, user.id, team_id)
            require_api_admin(member)
            current = self._find_api_provider(data, team_id, provider_id)
            current_config = decrypt_team_api_config((current or {}).get("encrypted_config"))
            encrypted_config = encrypt_team_api_config(team_api_config_from_payload(payload, current_config))
            if current:
                current["label"] = payload.label.strip()
                current["encrypted_config"] = encrypted_config
                current["updated_by"] = user.id
                current["updated_at"] = now_ms()
                record = current
            else:
                record = {
                    "id": str(uuid.uuid4()),
                    "team_id": team_id,
                    "provider_id": provider_id,
                    "label": payload.label.strip(),
                    "encrypted_config": encrypted_config,
                    "created_by": user.id,
                    "updated_by": user.id,
                    "created_at": now_ms(),
                    "updated_at": now_ms(),
                }
                data["api_providers"].append(record)
            self._write(data)
            return public_team_api_provider(record)

    def delete_api_provider(self, user: CurrentUser, team_id: str, provider_id: str) -> Dict[str, Any]:
        provider_id = normalize_provider_id(provider_id)
        with self.lock:
            data = self._read()
            member = self._require_member(data, user.id, team_id)
            require_api_admin(member)
            record = self._find_api_provider(data, team_id, provider_id)
            if not record:
                raise HTTPException(status_code=404, detail="Team API provider is not configured")
            data["api_providers"] = [
                item
                for item in data["api_providers"]
                if not (item.get("team_id") == team_id and item.get("provider_id") == provider_id)
            ]
            self._write(data)
            return {"provider": public_team_api_provider(record)}

    def get_api_provider_config(self, user: CurrentUser, team_id: str, provider_id: str) -> Dict[str, Any]:
        provider_id = normalize_provider_id(provider_id)
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            record = self._find_api_provider(data, team_id, provider_id)
            if not record:
                raise HTTPException(status_code=404, detail="Team API provider is not configured")
            config = decrypt_team_api_config(record.get("encrypted_config"))
            if not bool(config.get("enabled", True)):
                raise HTTPException(status_code=400, detail="Team API provider is disabled")
            return {
                **public_team_api_provider(record),
                "api_key": str(config.get("api_key") or ""),
                "wallet_api_key": str(config.get("wallet_api_key") or ""),
            }

    def create_generation_log(self, user: CurrentUser, team_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            record = {
                "id": str(uuid.uuid4()),
                "team_id": team_id,
                "project_id": str(payload.get("project_id") or ""),
                "canvas_id": str(payload.get("canvas_id") or ""),
                "user_id": user.id,
                "provider_id": str(payload.get("provider_id") or ""),
                "model": str(payload.get("model") or ""),
                "status": str(payload.get("status") or "pending"),
                "request_summary": payload.get("request_summary") if isinstance(payload.get("request_summary"), dict) else {},
                "result_summary": payload.get("result_summary") if isinstance(payload.get("result_summary"), dict) else {},
                "error": str(payload.get("error") or ""),
                "created_at": now_ms(),
                "finished_at": now_ms() if str(payload.get("status") or "") in {"succeeded", "failed"} else None,
            }
            data["generation_logs"].append(record)
            self._write(data)
            return record

    def list_generation_logs(self, user: CurrentUser, team_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            logs = [item for item in data["generation_logs"] if item.get("team_id") == team_id]
            logs.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
            return logs[:max(1, min(200, int(limit or 100)))]

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

    def _find_asset(self, data: Dict[str, Any], team_id: str, asset_id: str) -> Optional[Dict[str, Any]]:
        for asset in data["assets"]:
            if asset.get("team_id") == team_id and asset.get("id") == asset_id:
                return asset
        return None

    def _find_api_provider(self, data: Dict[str, Any], team_id: str, provider_id: str) -> Optional[Dict[str, Any]]:
        for provider in data["api_providers"]:
            if provider.get("team_id") == team_id and provider.get("provider_id") == provider_id:
                return provider
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

    def _canvas_version_summary(self, row: Dict[str, Any]) -> Dict[str, Any]:
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        return {
            "id": row.get("id") or "",
            "canvas_id": row.get("canvas_id") or "",
            "version": row.get("version"),
            "title": data.get("title") or "",
            "node_count": len(data.get("nodes") or []) if isinstance(data.get("nodes"), list) else 0,
            "connection_count": len(data.get("connections") or []) if isinstance(data.get("connections"), list) else 0,
            "created_by": row.get("created_by") or "",
            "created_at": row.get("created_at"),
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

    async def delete_team(self, user: CurrentUser, team_id: str) -> Dict[str, Any]:
        member = await self._require_member(user.id, team_id)
        require_team_owner(member)
        teams = await self._request("GET", f"/teams?id=eq.{team_id}&select=*")
        if not teams:
            raise HTTPException(status_code=404, detail="Team not found")
        assets = await self._request(
            "GET",
            f"/assets?team_id=eq.{team_id}&select=*",
        )
        await self._request("DELETE", f"/teams?id=eq.{team_id}")
        removed_files = [
            key
            for asset in (assets or [])
            for key in (asset.get("storage_key"), asset.get("thumbnail_storage_key"))
            if key and delete_team_asset_file(str(key))
        ]
        return {"team": {**teams[0], "role": member.get("role")}, "removed_files": removed_files}

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

    async def delete_project(self, user: CurrentUser, project_id: str) -> Dict[str, Any]:
        project = await self._require_project_member(user.id, project_id)
        member = await self._require_member(user.id, project["team_id"])
        require_team_admin(member)
        rows = await self._request("DELETE", f"/projects?id=eq.{project_id}")
        return {"project": (rows or [project])[0]}

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

    async def delete_canvas(self, user: CurrentUser, canvas_id: str) -> Dict[str, Any]:
        canvas = await self.get_canvas(user, canvas_id)
        member = await self._require_member(user.id, canvas["team_id"])
        require_team_admin(member)
        rows = await self._request("DELETE", f"/canvases?id=eq.{canvas_id}")
        return {"canvas": (rows or [canvas])[0]}

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

    async def list_canvas_versions(self, user: CurrentUser, canvas_id: str) -> List[Dict[str, Any]]:
        canvas = await self.get_canvas(user, canvas_id)
        rows = await self._request(
            "GET",
            f"/canvas_versions?canvas_id=eq.{canvas['id']}&order=version.desc&select=id,canvas_id,version,data,created_by,created_at",
        )
        return [self._canvas_version_summary(row) for row in rows or []]

    async def restore_canvas_version(self, user: CurrentUser, canvas_id: str, version: int) -> Dict[str, Any]:
        canvas = await self.get_canvas(user, canvas_id)
        rows = await self._request(
            "GET",
            f"/canvas_versions?canvas_id=eq.{canvas['id']}&version=eq.{int(version)}&select=*",
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Canvas version not found")
        source = rows[0]
        restored_data = source.get("data") if isinstance(source.get("data"), dict) else {}
        next_version = int(canvas.get("version") or 1) + 1
        patch = {
            "data": restored_data,
            "title": str(restored_data.get("title") or canvas.get("title") or "Untitled canvas").strip() or "Untitled canvas",
            "version": next_version,
            "updated_by": user.id,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        updated = (await self._request("PATCH", f"/canvases?id=eq.{canvas_id}", json_body=patch))[0]
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
        return {"canvas": updated, "restored_version": self._canvas_version_summary(source)}

    async def list_assets(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        await self._require_member(user.id, team_id)
        return await self._request(
            "GET",
            f"/assets?team_id=eq.{team_id}&order=created_at.desc&select=*",
        )

    async def create_asset(self, user: CurrentUser, team_id: str, asset: Dict[str, Any]) -> Dict[str, Any]:
        await self._require_member(user.id, team_id)
        body = {
            "id": asset.get("id"),
            "team_id": team_id,
            "project_id": asset.get("project_id"),
            "canvas_id": asset.get("canvas_id"),
            "kind": asset.get("kind") or "file",
            "name": asset.get("name") or "asset",
            "storage_key": asset.get("storage_key") or "",
            "public_url": asset.get("public_url") or "",
            "thumbnail_url": asset.get("thumbnail_url") or "",
            "mime_type": asset.get("mime_type") or "",
            "byte_size": int(asset.get("byte_size") or 0),
            "width": asset.get("width"),
            "height": asset.get("height"),
            "created_by": user.id,
        }
        if asset.get("thumbnail_storage_key"):
            body["thumbnail_storage_key"] = asset.get("thumbnail_storage_key")
        try:
            rows = await self._request("POST", "/assets", json_body=[body])
        except HTTPException as exc:
            if "thumbnail_storage_key" not in str(exc.detail):
                raise
            body.pop("thumbnail_storage_key", None)
            rows = await self._request("POST", "/assets", json_body=[body])
        return rows[0]

    async def delete_asset(self, user: CurrentUser, team_id: str, asset_id: str) -> Dict[str, Any]:
        member = await self._require_member(user.id, team_id)
        assets = await self._request(
            "GET",
            f"/assets?team_id=eq.{team_id}&id=eq.{asset_id}&select=*",
        )
        if not assets:
            raise HTTPException(status_code=404, detail="团队素材不存在")
        asset = assets[0]
        require_asset_delete_permission(member, user, asset)
        canvases = await self._request(
            "GET",
            f"/canvases?team_id=eq.{team_id}&select=id,title,project_id,data",
        )
        references = canvas_asset_references(canvases or [], asset)
        if references:
            raise HTTPException(
                status_code=409,
                detail={"message": "素材仍被画布使用，无法删除", "references": references},
            )
        await self._request("DELETE", f"/assets?team_id=eq.{team_id}&id=eq.{asset_id}")
        removed_files = [
            key
            for key in (asset.get("storage_key"), asset.get("thumbnail_storage_key"))
            if key and delete_team_asset_file(str(key))
        ]
        return {"asset": asset, "removed_files": removed_files, "references": []}

    async def list_api_providers(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        await self._require_member(user.id, team_id)
        rows = await self._request("GET", f"/api_providers?team_id=eq.{team_id}&order=provider_id.asc&select=*")
        return [public_team_api_provider(row) for row in rows or []]

    async def upsert_api_provider(self, user: CurrentUser, team_id: str, provider_id: str, payload: TeamApiProviderSaveRequest) -> Dict[str, Any]:
        provider_id = normalize_provider_id(provider_id)
        member = await self._require_member(user.id, team_id)
        require_api_admin(member)
        rows = await self._request("GET", f"/api_providers?team_id=eq.{team_id}&provider_id=eq.{provider_id}&select=*")
        current = rows[0] if rows else None
        current_config = decrypt_team_api_config((current or {}).get("encrypted_config"))
        body = {
            "label": payload.label.strip(),
            "encrypted_config": encrypt_team_api_config(team_api_config_from_payload(payload, current_config)),
            "updated_by": user.id,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if current:
            updated = await self._request("PATCH", f"/api_providers?team_id=eq.{team_id}&provider_id=eq.{provider_id}", json_body=body)
            record = updated[0]
        else:
            created = await self._request("POST", "/api_providers", json_body=[{
                "team_id": team_id,
                "provider_id": provider_id,
                "label": payload.label.strip(),
                "encrypted_config": body["encrypted_config"],
                "created_by": user.id,
                "updated_by": user.id,
            }])
            record = created[0]
        return public_team_api_provider(record)

    async def delete_api_provider(self, user: CurrentUser, team_id: str, provider_id: str) -> Dict[str, Any]:
        provider_id = normalize_provider_id(provider_id)
        member = await self._require_member(user.id, team_id)
        require_api_admin(member)
        rows = await self._request("GET", f"/api_providers?team_id=eq.{team_id}&provider_id=eq.{provider_id}&select=*")
        if not rows:
            raise HTTPException(status_code=404, detail="Team API provider is not configured")
        await self._request("DELETE", f"/api_providers?team_id=eq.{team_id}&provider_id=eq.{provider_id}")
        return {"provider": public_team_api_provider(rows[0])}

    async def get_api_provider_config(self, user: CurrentUser, team_id: str, provider_id: str) -> Dict[str, Any]:
        provider_id = normalize_provider_id(provider_id)
        await self._require_member(user.id, team_id)
        rows = await self._request("GET", f"/api_providers?team_id=eq.{team_id}&provider_id=eq.{provider_id}&select=*")
        if not rows:
            raise HTTPException(status_code=404, detail="Team API provider is not configured")
        record = rows[0]
        config = decrypt_team_api_config(record.get("encrypted_config"))
        if not bool(config.get("enabled", True)):
            raise HTTPException(status_code=400, detail="Team API provider is disabled")
        return {
            **public_team_api_provider(record),
            "api_key": str(config.get("api_key") or ""),
            "wallet_api_key": str(config.get("wallet_api_key") or ""),
        }

    async def create_generation_log(self, user: CurrentUser, team_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        await self._require_member(user.id, team_id)
        created = await self._request("POST", "/generation_logs", json_body=[{
            "team_id": team_id,
            "project_id": payload.get("project_id") or None,
            "canvas_id": payload.get("canvas_id") or None,
            "user_id": user.id,
            "provider_id": str(payload.get("provider_id") or ""),
            "model": str(payload.get("model") or ""),
            "status": str(payload.get("status") or "pending"),
            "request_summary": payload.get("request_summary") if isinstance(payload.get("request_summary"), dict) else {},
            "result_summary": payload.get("result_summary") if isinstance(payload.get("result_summary"), dict) else {},
            "error": str(payload.get("error") or ""),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) if str(payload.get("status") or "") in {"succeeded", "failed"} else None,
        }])
        return created[0]

    async def list_generation_logs(self, user: CurrentUser, team_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        await self._require_member(user.id, team_id)
        safe_limit = max(1, min(200, int(limit or 100)))
        return await self._request(
            "GET",
            f"/generation_logs?team_id=eq.{team_id}&order=created_at.desc&limit={safe_limit}&select=*",
        )

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

    def _canvas_version_summary(self, row: Dict[str, Any]) -> Dict[str, Any]:
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        return {
            "id": row.get("id") or "",
            "canvas_id": row.get("canvas_id") or "",
            "version": row.get("version"),
            "title": data.get("title") or "",
            "node_count": len(data.get("nodes") or []) if isinstance(data.get("nodes"), list) else 0,
            "connection_count": len(data.get("connections") or []) if isinstance(data.get("connections"), list) else 0,
            "created_by": row.get("created_by") or "",
            "created_at": row.get("created_at"),
        }


local_store = LocalTeamStore(LOCAL_TEAM_STORE)
supabase_store = SupabaseTeamStore(settings.supabase_url, settings.supabase_service_role_key) if settings.supabase_ready else None


def active_store():
    return supabase_store or local_store


async def resolve_team_api_provider_config(user: CurrentUser, team_id: str, provider_id: str) -> Dict[str, Any]:
    return await maybe_await(active_store().get_api_provider_config(user, team_id, provider_id))


async def record_team_generation_log(user: CurrentUser, team_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return await maybe_await(active_store().create_generation_log(user, team_id, payload))


def generation_log_summary(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {"total": len(logs), "succeeded": 0, "failed": 0, "providers": {}}
    for log in logs:
        status = str(log.get("status") or "")
        if status == "succeeded":
            summary["succeeded"] += 1
        elif status == "failed":
            summary["failed"] += 1
        provider_id = str(log.get("provider_id") or "unknown")
        summary["providers"][provider_id] = int(summary["providers"].get(provider_id) or 0) + 1
    return summary


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


@router.post("/auth/password")
async def update_password(
    payload: AuthPasswordUpdateRequest,
    response: Response,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少密码恢复凭证")
    access_token = authorization[7:].strip()
    if not access_token:
        raise HTTPException(status_code=401, detail="缺少密码恢复凭证")
    data = await supabase_update_password(access_token, payload.password)
    set_auth_cookie(response, access_token)
    return {
        "ok": True,
        "access_token": access_token,
        "user": {
            "id": data.get("id"),
            "email": data.get("email"),
            "updated_at": data.get("updated_at"),
        },
    }


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


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    return await maybe_await(active_store().delete_team(user, team_id))


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


@router.delete("/projects/{project_id}")
async def delete_team_project(project_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    return await maybe_await(active_store().delete_project(user, project_id))


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


@router.delete("/canvases/{canvas_id}")
async def delete_team_canvas(canvas_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    return await maybe_await(active_store().delete_canvas(user, canvas_id))


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


@router.get("/canvases/{canvas_id}/versions")
async def list_team_canvas_versions(canvas_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    versions = await maybe_await(active_store().list_canvas_versions(user, canvas_id))
    return {"versions": versions}


@router.post("/canvases/{canvas_id}/versions/{version}/restore")
async def restore_team_canvas_version(
    canvas_id: str,
    version: int,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    return await maybe_await(active_store().restore_canvas_version(user, canvas_id, version))


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
    try:
        stored = save_team_asset(
            content,
            team_id=team_id,
            filename=filename,
            content_type=file.content_type or "",
            asset_id=asset_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="团队素材云存储未配置，请先配置 Cloudflare R2") from exc
    image_meta = build_image_thumbnail(content) if (file.content_type or "").startswith("image/") else {}
    thumbnail_url = ""
    thumbnail_storage_key = ""
    if image_meta.get("content"):
        try:
            thumb_stored = save_team_asset(
                image_meta["content"],
                team_id=team_id,
                filename=f"{os.path.splitext(filename)[0]}_thumb.jpg",
                content_type=image_meta.get("content_type") or "image/jpeg",
                asset_id=f"{asset_id}-thumb",
            )
            thumbnail_url = thumb_stored.get("public_url") or ""
            thumbnail_storage_key = thumb_stored.get("storage_key") or ""
        except Exception as exc:
            print(f"生成团队素材缩略图失败：{exc}")
    asset = await maybe_await(active_store().create_asset(user, team_id, {
        "id": asset_id,
        "kind": "image" if (file.content_type or "").startswith("image/") else "file",
        "name": filename,
        "mime_type": file.content_type or "",
        "byte_size": len(content),
        "thumbnail_url": thumbnail_url,
        "thumbnail_storage_key": thumbnail_storage_key,
        "width": image_meta.get("width"),
        "height": image_meta.get("height"),
        **stored,
    }))
    return {"asset": asset}


@router.delete("/teams/{team_id}/assets/{asset_id}")
async def delete_team_asset(
    team_id: str,
    asset_id: str,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    return await maybe_await(active_store().delete_asset(user, team_id, asset_id))


@router.get("/teams/{team_id}/api-providers")
async def list_team_api_providers(team_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    providers = await maybe_await(active_store().list_api_providers(user, team_id))
    return {"providers": providers}


@router.put("/teams/{team_id}/api-providers/{provider_id}")
async def save_team_api_provider(
    team_id: str,
    provider_id: str,
    payload: TeamApiProviderSaveRequest,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    provider = await maybe_await(active_store().upsert_api_provider(user, team_id, provider_id, payload))
    return {"provider": provider}


@router.delete("/teams/{team_id}/api-providers/{provider_id}")
async def delete_team_api_provider(
    team_id: str,
    provider_id: str,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    return await maybe_await(active_store().delete_api_provider(user, team_id, provider_id))


@router.get("/teams/{team_id}/generation-logs")
async def list_team_generation_logs(
    team_id: str,
    limit: int = 100,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    logs = await maybe_await(active_store().list_generation_logs(user, team_id, limit))
    return {"logs": logs, "summary": generation_log_summary(logs)}


async def maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
