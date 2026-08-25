import base64
import asyncio
from collections import OrderedDict
import datetime
import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx
import jwt
from fastapi import APIRouter, Cookie, Depends, File, Header, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field

from team_storage import build_image_thumbnail, delete_team_asset_file, read_team_asset_file, save_team_asset, safe_filename


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("YISHU_DATA_DIR", os.path.join(BASE_DIR, "data"))
LOCAL_TEAM_STORE = os.path.join(DATA_DIR, "team_cloud.json")

TEAM_ROLES = {"owner", "admin", "member"}
VISIBILITY_VALUES = {"private", "team"}
TEAM_ASSET_MAX_BYTES = int(os.getenv("TEAM_ASSET_MAX_BYTES", str(50 * 1024 * 1024)))
TEAM_POINTS_DEFAULT_BALANCE = int(os.getenv("TEAM_POINTS_DEFAULT_BALANCE", "16050"))
TEAM_SESSION_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("TEAM_SESSION_HEARTBEAT_INTERVAL_SECONDS", "60"))
TEAM_SESSION_ONLINE_WINDOW_SECONDS = int(os.getenv("TEAM_SESSION_ONLINE_WINDOW_SECONDS", "300"))
TEAM_CONFIG_CACHE_SECONDS = int(os.getenv("TEAM_CONFIG_CACHE_SECONDS", "60"))
TEAM_ADMIN_USAGE_LIMIT = int(os.getenv("TEAM_ADMIN_USAGE_LIMIT", "1000"))
TEAM_AUTH_VERIFICATION_RESEND_SECONDS = int(os.getenv("TEAM_AUTH_VERIFICATION_RESEND_SECONDS", "60"))
TEAM_AUTH_USERNAME_CACHE_SECONDS = int(os.getenv("TEAM_AUTH_USERNAME_CACHE_SECONDS", "600"))
TEAM_AUTH_USERNAME_CACHE_MAX_ENTRIES = int(os.getenv("TEAM_AUTH_USERNAME_CACHE_MAX_ENTRIES", "512"))

DEFAULT_OPERATION_POINTS = {
    "image": 0,
    "upscale": 0,
    "chat": 0,
    "video": 0,
    "workflow": 0,
}

DEFAULT_MODEL_BILLING_PRICES = [
    {"provider_id": provider_id, "model": model, "operation_type": "image", "points_cost": points, "provider_points_cost": points * 100, "note": "grsai screenshot preset"}
    for provider_id in ("grsai", "custom-api")
    for model, points in (
        ("gpt-image-2", 6),
        ("gpt-image-2-vip", 20),
        ("nano-banana-pro", 18),
        ("nano-banana-2", 12),
    )
]

DEFAULT_PROVIDER_RECHARGES = [
    {
        "provider_id": "grsai",
        "amount_cny": 100,
        "provider_points_received": 1605000,
        "app_points_received": 16050,
        "note": "Initial grsai recharge baseline",
    }
]


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
    cloudflare_access_enabled: bool = os.getenv("TEAM_AUTH_CLOUDFLARE_ACCESS_ENABLED", "").lower() in {"1", "true", "yes", "on"}
    cloudflare_access_team_domain: str = os.getenv("TEAM_AUTH_CLOUDFLARE_ACCESS_TEAM_DOMAIN", "").rstrip("/")
    cloudflare_access_audience: str = os.getenv("TEAM_AUTH_CLOUDFLARE_ACCESS_AUD", "")
    cloudflare_access_default_team_id: str = os.getenv("TEAM_AUTH_CLOUDFLARE_ACCESS_DEFAULT_TEAM_ID", "")
    cloudflare_access_default_role: str = os.getenv("TEAM_AUTH_CLOUDFLARE_ACCESS_DEFAULT_ROLE", "member")
    team_api_secret_key: str = os.getenv("TEAM_API_SECRET_KEY", "")

    @property
    def supabase_ready(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def auth_ready(self) -> bool:
        cloudflare_ready = bool(
            self.cloudflare_access_enabled
            and self.cloudflare_access_team_domain
            and self.cloudflare_access_audience
        )
        return bool(self.supabase_jwt_secret or (self.supabase_url and self.supabase_anon_key)) or self.dev_bypass or cloudflare_ready


settings = TeamCloudSettings()
router = APIRouter(prefix="/api/team-cloud", tags=["team-cloud"])
CF_ACCESS_CERTS_CACHE_TTL = 60 * 60
_cf_access_certs_cache: Dict[str, Any] = {"expires_at": 0.0, "keys": []}
_verification_resend_times: Dict[str, float] = {}
_username_email_cache: "OrderedDict[str, Tuple[str, float]]" = OrderedDict()
_supabase_auth_client: Optional[httpx.AsyncClient] = None
_supabase_auth_client_lock = asyncio.Lock()


class CurrentUser(BaseModel):
    id: str
    email: str = ""
    username: str = ""
    display_name: str = ""
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
    email: Optional[str] = Field(None, min_length=3, max_length=254)
    identifier: Optional[str] = Field(None, min_length=3, max_length=254)
    username: Optional[str] = Field(None, min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)


class AuthSignupVerifyRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    token: str = Field(..., min_length=4, max_length=16)


class AuthVerificationResendRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class AuthPasswordUpdateRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class AuthRecoverRequest(BaseModel):
    identifier: Optional[str] = Field(None, min_length=3, max_length=254)
    email: Optional[str] = Field(None, min_length=3, max_length=254)


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
    image_models: List[str] = Field(default_factory=list)
    chat_models: List[str] = Field(default_factory=list)
    video_models: List[str] = Field(default_factory=list)


class TeamApiProviderModelsRequest(BaseModel):
    label: str = Field("API", max_length=80)
    base_url: str = Field("", max_length=500)
    protocol: str = Field("openai", max_length=40)
    api_key: str = Field("", max_length=4096)
    wallet_api_key: str = Field("", max_length=4096)


class TeamUsageLogRequest(BaseModel):
    team_id: str = Field(..., min_length=1)
    project_id: str = ""
    canvas_id: str = ""
    operation_type: str = "image"
    provider_id: str = ""
    model: str = ""
    status: str = "succeeded"
    points_charged: Optional[int] = None
    request_count: int = 1
    image_count: int = 0
    video_count: int = 0
    latency_ms: int = 0
    request_summary: Dict[str, Any] = Field(default_factory=dict)
    result_summary: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class PointsAdjustRequest(BaseModel):
    team_id: str = ""
    delta: int = 0
    mode: str = Field("adjust", pattern="^(adjust|set|reset)$")
    note: str = Field("", max_length=500)


class ModelBillingPriceRequest(BaseModel):
    team_id: str = ""
    provider_id: str = Field(..., min_length=1, max_length=80)
    model: str = Field(..., min_length=1, max_length=200)
    operation_type: str = "image"
    points_cost: int = Field(0, ge=0, le=1000000)
    enabled: bool = True
    note: str = Field("", max_length=500)


class ProviderRechargeRequest(BaseModel):
    team_id: str = ""
    provider_id: str = Field(..., min_length=1, max_length=80)
    amount_cny: float = Field(0, ge=0)
    provider_points_received: int = Field(0, ge=0)
    app_points_received: int = Field(0, ge=0)
    note: str = Field("", max_length=500)


class SessionHeartbeatRequest(BaseModel):
    team_id: str = ""
    session_id: str = ""
    page: str = Field("", max_length=200)


def now_ms() -> int:
    return int(time.time() * 1000)


def normalize_email(value: str) -> str:
    return value.strip().lower()


USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")


def normalize_username(value: str) -> str:
    username = str(value or "").strip().lower()
    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=400, detail="账号名只能使用小写字母、数字、下划线或短横线，长度 3-32 位")
    return username


def auth_identifier(payload: AuthEmailPasswordRequest | AuthRecoverRequest) -> str:
    return str(payload.identifier or payload.email or "").strip()


def auth_email_required(value: Optional[str]) -> str:
    email = normalize_email(value or "")
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=400, detail="请输入有效邮箱")
    return email


def looks_like_email(value: str) -> bool:
    return "@" in value


def public_config() -> Dict[str, Any]:
    return {
        "auth_provider": "supabase",
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
        "auth_ready": settings.auth_ready,
        "supabase_ready": settings.supabase_ready,
        "dev_bypass": settings.dev_bypass,
        "cookie_auth": True,
        "cloudflare_access_auth": bool(settings.cloudflare_access_enabled),
    }


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        raw = float(value)
        return raw / 1000.0 if raw > 10_000_000_000 else raw
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.isdigit():
        return parse_timestamp(int(text))
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def normalize_operation_type(value: Any) -> str:
    operation = str(value or "image").strip().lower()
    return operation if operation in DEFAULT_OPERATION_POINTS else "image"


def default_points_for_operation(operation_type: str) -> int:
    return int(DEFAULT_OPERATION_POINTS.get(normalize_operation_type(operation_type), 1))


def normalize_billing_provider_id(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_billing_model(value: str) -> str:
    return str(value or "").strip()


def billing_price_key(provider_id: str, model: str, operation_type: str) -> Tuple[str, str, str]:
    return (
        normalize_billing_provider_id(provider_id),
        normalize_billing_model(model).lower(),
        normalize_operation_type(operation_type),
    )


def billing_price_public(record: Dict[str, Any]) -> Dict[str, Any]:
    points_cost = max(0, int(record.get("points_cost") or 0))
    provider_points_cost = max(0, int(record.get("provider_points_cost") or points_cost * 100))
    return {
        "id": str(record.get("id") or ""),
        "team_id": str(record.get("team_id") or ""),
        "provider_id": normalize_billing_provider_id(record.get("provider_id")),
        "model": normalize_billing_model(record.get("model")),
        "operation_type": normalize_operation_type(record.get("operation_type")),
        "points_cost": points_cost,
        "provider_points_cost": provider_points_cost,
        "enabled": bool(record.get("enabled", True)),
        "note": str(record.get("note") or ""),
        "updated_at": record.get("updated_at"),
    }


def default_billing_price_rows(team_id: str) -> List[Dict[str, Any]]:
    now = utc_now_iso()
    return [
        {
            "id": f"default:{team_id}:{item['provider_id']}:{item['operation_type']}:{item['model']}",
            "team_id": team_id,
            "provider_id": item["provider_id"],
            "model": item["model"],
            "operation_type": item["operation_type"],
            "points_cost": item["points_cost"],
            "provider_points_cost": item.get("provider_points_cost") or item["points_cost"] * 100,
            "enabled": True,
            "note": item.get("note") or "",
            "updated_at": now,
        }
        for item in DEFAULT_MODEL_BILLING_PRICES
    ]


def default_recharge_rows(team_id: str) -> List[Dict[str, Any]]:
    now = utc_now_iso()
    return [
        {
            "id": f"default:{team_id}:{item['provider_id']}",
            "team_id": team_id,
            "provider_id": item["provider_id"],
            "amount_cny": float(item.get("amount_cny") or 0),
            "provider_points_received": int(item.get("provider_points_received") or 0),
            "app_points_received": int(item.get("app_points_received") or 0),
            "note": item.get("note") or "",
            "recharged_at": now,
            "created_at": now,
        }
        for item in DEFAULT_PROVIDER_RECHARGES
    ]


def merged_billing_prices(team_id: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for row in default_billing_price_rows(team_id):
        by_key[billing_price_key(row.get("provider_id"), row.get("model"), row.get("operation_type"))] = row
    for row in rows or []:
        by_key[billing_price_key(row.get("provider_id"), row.get("model"), row.get("operation_type"))] = row
    return [billing_price_public(row) for row in sorted(by_key.values(), key=lambda item: (str(item.get("provider_id") or ""), str(item.get("model") or ""), str(item.get("operation_type") or "")))]


def billing_quote_from_prices(prices: List[Dict[str, Any]], provider_id: str, model: str, operation_type: str, units: int = 1) -> Dict[str, Any]:
    units = max(1, int(units or 1))
    key = billing_price_key(provider_id, model, operation_type)
    price = next((item for item in prices if billing_price_key(item.get("provider_id"), item.get("model"), item.get("operation_type")) == key and item.get("enabled") is not False), None)
    unit_points = int(price.get("points_cost") or 0) if price else 0
    unit_provider_points = int(price.get("provider_points_cost") or unit_points * 100) if price else unit_points * 100
    return {
        "provider_id": normalize_billing_provider_id(provider_id),
        "model": normalize_billing_model(model),
        "operation_type": normalize_operation_type(operation_type),
        "units": units,
        "unit_points": unit_points,
        "required_points": unit_points * units,
        "unit_provider_points": unit_provider_points,
        "provider_points_charged": unit_provider_points * units,
        "configured": bool(price),
        "enabled": bool(price.get("enabled", True)) if price else True,
    }


def recharge_cost_summary(recharges: List[Dict[str, Any]]) -> Dict[str, Any]:
    amount = sum(float(item.get("amount_cny") or 0) for item in recharges or [])
    app_points = sum(int(item.get("app_points_received") or 0) for item in recharges or [])
    provider_points = sum(int(item.get("provider_points_received") or 0) for item in recharges or [])
    cost_per_point = amount / app_points if app_points else 0
    return {
        "amount_cny": round(amount, 4),
        "app_points_received": app_points,
        "provider_points_received": provider_points,
        "cost_per_point_cny": round(cost_per_point, 6),
    }


def usage_points(payload: Dict[str, Any]) -> int:
    explicit = payload.get("points_charged")
    if explicit is not None:
        try:
            return max(0, int(explicit))
        except (TypeError, ValueError):
            return 0
    operation = normalize_operation_type(payload.get("operation_type"))
    unit_count = 1
    if operation == "image":
        unit_count = max(1, int(payload.get("image_count") or payload.get("request_count") or 1))
    elif operation == "video":
        unit_count = max(1, int(payload.get("video_count") or payload.get("request_count") or 1))
    return default_points_for_operation(operation) * unit_count


def public_member_user(member: Dict[str, Any], profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    profile = profile or {}
    return {
        "user_id": member.get("user_id") or profile.get("user_id") or "",
        "email": profile.get("email") or member.get("email") or "",
        "username": profile.get("username") or "",
        "display_name": profile.get("display_name") or profile.get("username") or member.get("email") or member.get("user_id") or "",
        "role": member.get("role") or "member",
        "team_id": member.get("team_id") or "",
        "joined_at": member.get("created_at"),
    }


def online_status_from_last_seen(last_seen_at: Any) -> bool:
    last_seen = parse_timestamp(last_seen_at)
    return bool(last_seen and time.time() - last_seen <= TEAM_SESSION_ONLINE_WINDOW_SECONDS)


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


async def get_supabase_auth_client() -> httpx.AsyncClient:
    global _supabase_auth_client
    if _supabase_auth_client and not _supabase_auth_client.is_closed:
        return _supabase_auth_client
    async with _supabase_auth_client_lock:
        if not _supabase_auth_client or _supabase_auth_client.is_closed:
            _supabase_auth_client = httpx.AsyncClient(timeout=20)
    return _supabase_auth_client


async def close_supabase_auth_client() -> None:
    global _supabase_auth_client
    client = _supabase_auth_client
    _supabase_auth_client = None
    if client and not client.is_closed:
        await client.aclose()


async def fetch_supabase_user(token: str) -> CurrentUser:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Supabase Auth 未配置")
    client = await get_supabase_auth_client()
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


def cloudflare_access_issuer() -> str:
    issuer = settings.cloudflare_access_team_domain.rstrip("/")
    if not issuer:
        raise HTTPException(status_code=503, detail="Cloudflare Access 团队域名未配置")
    if not issuer.startswith(("https://", "http://")):
        issuer = f"https://{issuer}"
    return issuer


async def fetch_cloudflare_access_keys() -> List[Dict[str, Any]]:
    now = time.time()
    if _cf_access_certs_cache["keys"] and float(_cf_access_certs_cache["expires_at"]) > now:
        return list(_cf_access_certs_cache["keys"])
    issuer = cloudflare_access_issuer()
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{issuer}/cdn-cgi/access/certs")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Cloudflare Access 证书读取失败")
    data = response.json()
    keys = data.get("keys") if isinstance(data, dict) else None
    if not keys:
        raise HTTPException(status_code=502, detail="Cloudflare Access 证书为空")
    _cf_access_certs_cache["keys"] = keys
    _cf_access_certs_cache["expires_at"] = now + CF_ACCESS_CERTS_CACHE_TTL
    return list(keys)


def decode_cloudflare_access_token(token: str, keys: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not settings.cloudflare_access_audience:
        raise HTTPException(status_code=503, detail="Cloudflare Access AUD 未配置")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Cloudflare Access 登录凭证无效") from exc
    kid = str(header.get("kid") or "")
    issuer = cloudflare_access_issuer()
    errors: List[Exception] = []
    for jwk in keys:
        if kid and str(jwk.get("kid") or "") != kid:
            continue
        try:
            key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
            return jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=settings.cloudflare_access_audience,
                issuer=issuer,
            )
        except jwt.PyJWTError as exc:
            errors.append(exc)
    if errors:
        raise HTTPException(status_code=401, detail="Cloudflare Access 登录凭证校验失败") from errors[-1]
    raise HTTPException(status_code=401, detail="Cloudflare Access 登录凭证证书不匹配")


def cloudflare_user_id(payload: Dict[str, Any]) -> str:
    subject = str(payload.get("sub") or payload.get("email") or "")
    if not subject:
        raise HTTPException(status_code=401, detail="Cloudflare Access 登录凭证缺少用户 ID")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"cloudflare-access:{cloudflare_access_issuer()}:{subject}"))


async def authenticate_cloudflare_access_token(token: Optional[str]) -> Optional[CurrentUser]:
    if not (settings.cloudflare_access_enabled and token):
        return None
    keys = await fetch_cloudflare_access_keys()
    payload = decode_cloudflare_access_token(token.strip(), keys)
    email = auth_email_required(str(payload.get("email") or ""))
    return CurrentUser(
        id=cloudflare_user_id(payload),
        email=email,
        username=email.split("@", 1)[0].lower(),
        display_name=email,
        provider="cloudflare-access",
    )


async def ensure_default_team_membership(user: CurrentUser) -> None:
    team_id = settings.cloudflare_access_default_team_id.strip()
    if not team_id or user.provider != "cloudflare-access":
        return
    role = settings.cloudflare_access_default_role if settings.cloudflare_access_default_role in TEAM_ROLES else "member"
    store = active_store()
    ensure = getattr(store, "ensure_team_member", None)
    if ensure:
        await maybe_await(ensure(user, team_id, role))


async def reconcile_supabase_email_identity(user: CurrentUser) -> None:
    if user.provider != "supabase" or not normalize_email(user.email):
        return
    reconcile = getattr(active_store(), "reconcile_email_identity", None)
    if reconcile:
        await maybe_await(reconcile(user))


async def resolve_current_user(
    authorization: Optional[str] = None,
    team_cloud_access_token: Optional[str] = None,
    cf_access_jwt_assertion: Optional[str] = None,
) -> CurrentUser:
    if authorization and authorization.lower().startswith("bearer "):
        user = await authenticate_supabase_token(authorization[7:].strip())
        await reconcile_supabase_email_identity(user)
        return user
    if team_cloud_access_token:
        user = await authenticate_supabase_token(team_cloud_access_token)
        await reconcile_supabase_email_identity(user)
        return user
    cf_user = await authenticate_cloudflare_access_token(cf_access_jwt_assertion)
    if cf_user:
        await ensure_default_team_membership(cf_user)
        return cf_user
    if settings.dev_bypass:
        return CurrentUser(
            id=os.getenv("TEAM_AUTH_DEV_USER_ID", "local-dev-user"),
            email=os.getenv("TEAM_AUTH_DEV_EMAIL", "dev@local.team"),
            provider="dev-bypass",
        )
    raise HTTPException(status_code=401, detail="请先登录")


async def require_user(
    authorization: Optional[str] = Header(default=None),
    team_cloud_access_token: Optional[str] = Cookie(default=None, alias=settings.cookie_name),
    cf_access_jwt_assertion: Optional[str] = Header(default=None, alias="Cf-Access-Jwt-Assertion"),
) -> CurrentUser:
    return await resolve_current_user(authorization, team_cloud_access_token, cf_access_jwt_assertion)


async def optional_current_user(request: Request) -> Optional[CurrentUser]:
    try:
        return await resolve_current_user(
            request.headers.get("Authorization"),
            request.cookies.get(settings.cookie_name),
            request.headers.get("Cf-Access-Jwt-Assertion"),
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return None
        raise


async def require_user_or_query_token(
    authorization: Optional[str] = Header(default=None),
    team_cloud_access_token: Optional[str] = Cookie(default=None, alias=settings.cookie_name),
    cf_access_jwt_assertion: Optional[str] = Header(default=None, alias="Cf-Access-Jwt-Assertion"),
    access_token: Optional[str] = Query(default=None),
) -> CurrentUser:
    if access_token:
        return await authenticate_supabase_token(access_token.strip())
    return await resolve_current_user(authorization, team_cloud_access_token, cf_access_jwt_assertion)


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
    client = await get_supabase_auth_client()
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
    client = await get_supabase_auth_client()
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


async def supabase_verify_signup_otp(email: str, token: str) -> Dict[str, Any]:
    return await supabase_auth_request("verify", {
        "type": "signup",
        "email": email,
        "token": str(token or "").strip(),
    })


async def supabase_resend_signup_otp(email: str) -> Dict[str, Any]:
    return await supabase_auth_request("resend", {
        "type": "signup",
        "email": email,
    })


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


def supabase_user_email_confirmed(user: Dict[str, Any]) -> bool:
    return bool(
        user.get("email_confirmed_at")
        or user.get("confirmed_at")
        or user.get("confirmation_sent_at") is None
    )


def user_metadata_username(user: Dict[str, Any]) -> str:
    metadata = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
    return normalize_username(str(metadata.get("username") or ""))


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


def normalize_model_list(values: Any, limit: int = 200) -> List[str]:
    result: List[str] = []
    seen = set()
    if not isinstance(values, list):
        return result
    for value in values:
        model = str(value or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        result.append(model)
        if len(result) >= limit:
            break
    return result


def classify_openai_model(model: str) -> str:
    value = model.lower()
    if any(term in value for term in ("image", "dall-e", "flux", "sdxl", "stable-diffusion", "jimeng", "seedream")):
        return "image_models"
    if any(term in value for term in ("video", "sora", "wan", "kling", "hailuo", "minimax")):
        return "video_models"
    return "chat_models"


def openai_models_from_response(payload: Dict[str, Any]) -> Dict[str, List[str]]:
    models = {"image_models": [], "chat_models": [], "video_models": []}
    for item in payload.get("data") or []:
        model = str((item or {}).get("id") if isinstance(item, dict) else item).strip()
        if not model:
            continue
        bucket = classify_openai_model(model)
        if model not in models[bucket]:
            models[bucket].append(model)
    return models


def require_api_admin(member: Dict[str, Any]) -> None:
    if member.get("role") not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only team owners and admins can manage API keys")


def require_team_admin(member: Dict[str, Any]) -> None:
    if member.get("role") not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only team owners and admins can delete projects and canvases")


def require_team_owner(member: Dict[str, Any]) -> None:
    if member.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only the team owner can delete this team")


def normalize_visibility(value: Any, default: str = "private") -> str:
    visibility = str(value or default).strip().lower()
    return visibility if visibility in VISIBILITY_VALUES else default


def record_is_visible_to_user(record: Dict[str, Any], user: CurrentUser, member: Dict[str, Any]) -> bool:
    if member.get("role") in {"owner", "admin"}:
        return True
    if normalize_visibility(record.get("visibility")) == "team":
        return True
    return record.get("created_by") == user.id


def require_visible_record(record: Dict[str, Any], user: CurrentUser, member: Dict[str, Any], detail: str) -> None:
    if not record_is_visible_to_user(record, user, member):
        raise HTTPException(status_code=404, detail=detail)


def require_publish_permission(record: Dict[str, Any], user: CurrentUser, member: Dict[str, Any]) -> None:
    if member.get("role") in {"owner", "admin"}:
        return
    if record.get("created_by") == user.id:
        return
    raise HTTPException(status_code=403, detail="Only the owner or a team admin can publish this item")


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
        "image_models": normalize_model_list(payload.image_models),
        "chat_models": normalize_model_list(payload.chat_models),
        "video_models": normalize_model_list(payload.video_models),
    }


def team_api_models_config_from_payload(payload: TeamApiProviderModelsRequest, current: Dict[str, Any] = None) -> Dict[str, Any]:
    current = current or {}
    return {
        "base_url": normalize_team_api_base_url(payload.base_url or current.get("base_url") or ""),
        "protocol": normalize_team_api_protocol(payload.protocol or current.get("protocol") or "openai"),
        "api_key": payload.api_key.strip() or str(current.get("api_key") or ""),
        "wallet_api_key": payload.wallet_api_key.strip() or str(current.get("wallet_api_key") or ""),
    }


async def fetch_team_api_models_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    protocol = normalize_team_api_protocol(config.get("protocol") or "openai")
    if protocol != "openai":
        raise HTTPException(status_code=400, detail="当前只支持 OpenAI 兼容协议自动拉取模型")
    base_url = normalize_team_api_base_url(config.get("base_url") or "")
    if not base_url:
        raise HTTPException(status_code=400, detail="请先填写请求地址")
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"模型接口请求失败：{exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"模型接口验证失败：HTTP {response.status_code} {response.text[:200]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="模型接口返回的不是 JSON") from exc

    models = openai_models_from_response(payload if isinstance(payload, dict) else {})
    return {
        "ok": True,
        "model_count": sum(len(items) for items in models.values()),
        "models": models,
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
        "image_models": normalize_model_list(config.get("image_models")),
        "chat_models": normalize_model_list(config.get("chat_models")),
        "video_models": normalize_model_list(config.get("video_models")),
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
            return {
                "teams": [],
                "members": [],
                "invitations": [],
                "projects": [],
                "canvases": [],
                "canvas_versions": [],
                "assets": [],
                "api_providers": [],
                "billing_prices": [],
                "provider_recharges": [],
                "generation_logs": [],
                "api_usage_logs": [],
                "user_points": [],
                "point_ledger": [],
                "user_sessions": [],
            }
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
            "billing_prices": data.get("billing_prices") or [],
            "provider_recharges": data.get("provider_recharges") or [],
            "generation_logs": data.get("generation_logs") or [],
            "api_usage_logs": data.get("api_usage_logs") or [],
            "user_points": data.get("user_points") or [],
            "point_ledger": data.get("point_ledger") or [],
            "user_sessions": data.get("user_sessions") or [],
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

    def reconcile_email_identity(self, user: CurrentUser) -> List[str]:
        email = normalize_email(user.email)
        if not email:
            return []
        with self.lock:
            data = self._read()
            migrated_team_ids: List[str] = []
            for member in data["members"]:
                legacy_user_id = str(member.get("user_id") or "")
                team_id = str(member.get("team_id") or "")
                if (
                    not team_id
                    or legacy_user_id == user.id
                    or normalize_email(str(member.get("email") or "")) != email
                    or any(item.get("team_id") == team_id and item.get("user_id") == user.id for item in data["members"])
                ):
                    continue
                member["user_id"] = user.id
                member["email"] = email
                legacy_points = next(
                    (item for item in data["user_points"] if item.get("team_id") == team_id and item.get("user_id") == legacy_user_id),
                    None,
                )
                current_points = next(
                    (item for item in data["user_points"] if item.get("team_id") == team_id and item.get("user_id") == user.id),
                    None,
                )
                if legacy_points and not current_points:
                    legacy_points["user_id"] = user.id
                    legacy_points["updated_at"] = now_ms()
                migrated_team_ids.append(team_id)
            if migrated_team_ids:
                self._write(data)
            return migrated_team_ids

    def ensure_team_member(self, user: CurrentUser, team_id: str, role: str) -> Dict[str, Any]:
        if role not in TEAM_ROLES:
            role = "member"
        with self.lock:
            data = self._read()
            team = next((item for item in data["teams"] if item.get("id") == team_id), None)
            if not team:
                raise HTTPException(status_code=404, detail="默认团队不存在")
            member = next((item for item in data["members"] if item.get("team_id") == team_id and item.get("user_id") == user.id), None)
            if member:
                return member
            member = {
                "id": str(uuid.uuid4()),
                "team_id": team_id,
                "user_id": user.id,
                "email": user.email,
                "role": role,
                "created_at": now_ms(),
            }
            data["members"].append(member)
            self._write(data)
            return member

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
            data["api_usage_logs"] = [item for item in data["api_usage_logs"] if item.get("team_id") != team_id]
            data["user_points"] = [item for item in data["user_points"] if item.get("team_id") != team_id]
            data["point_ledger"] = [item for item in data["point_ledger"] if item.get("team_id") != team_id]
            data["user_sessions"] = [item for item in data["user_sessions"] if item.get("team_id") != team_id]
            data["billing_prices"] = [item for item in data["billing_prices"] if item.get("team_id") != team_id]
            data["provider_recharges"] = [item for item in data["provider_recharges"] if item.get("team_id") != team_id]
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
            member = self._require_member(data, user.id, team_id)
            projects = [p for p in data["projects"] if p.get("team_id") == team_id and not p.get("archived_at")]
            if member.get("role") in {"owner", "admin"}:
                return projects
            visible_project_ids = {
                canvas.get("project_id")
                for canvas in data["canvases"]
                if canvas.get("team_id") == team_id and record_is_visible_to_user(canvas, user, member)
            }
            return [
                project
                for project in projects
                if project.get("created_by") == user.id or project.get("id") in visible_project_ids
            ]

    def workspace(
        self,
        user: CurrentUser,
        team_id: str,
        member: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            member = member or self._require_member(data, user.id, team_id)
            visible_canvases = [
                canvas
                for canvas in data["canvases"]
                if canvas.get("team_id") == team_id and record_is_visible_to_user(canvas, user, member)
            ]
            visible_project_ids = {canvas.get("project_id") for canvas in visible_canvases}
            projects = [
                project
                for project in data["projects"]
                if project.get("team_id") == team_id
                and not project.get("archived_at")
                and (
                    member.get("role") in {"owner", "admin"}
                    or project.get("created_by") == user.id
                    or project.get("id") in visible_project_ids
                )
            ]
            return {
                "projects": projects,
                "canvases": [self._canvas_summary(canvas) for canvas in visible_canvases],
                "trash_count": 0,
            }

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
            member = self._require_member(data, user.id, project["team_id"])
            return [
                self._canvas_summary(canvas)
                for canvas in data["canvases"]
                if canvas.get("project_id") == project["id"]
                and record_is_visible_to_user(canvas, user, member)
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
                "kind": str((canvas_data or {}).get("kind") or "classic"),
                "node_count": len((canvas_data or {}).get("nodes") or []) if isinstance((canvas_data or {}).get("nodes"), list) else 0,
                "version": 1,
                "visibility": "private",
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
            require_visible_record(canvas, user, member, "Canvas not found")
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
            member = self._require_member(data, user.id, canvas["team_id"])
            require_visible_record(canvas, user, member, "Canvas not found")
            return canvas

    def save_canvas(self, user: CurrentUser, canvas_id: str, payload: CanvasSaveRequest) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            canvas = self._find_canvas(data, canvas_id)
            if not canvas:
                raise HTTPException(status_code=404, detail="画布不存在")
            member = self._require_member(data, user.id, canvas["team_id"])
            require_visible_record(canvas, user, member, "Canvas not found")
            if payload.base_version is not None and payload.base_version != canvas.get("version"):
                raise HTTPException(status_code=409, detail={"message": "画布已被更新，请刷新后再保存", "canvas": canvas})
            canvas["data"] = payload.data or {}
            canvas["kind"] = str(canvas["data"].get("kind") or canvas.get("kind") or "classic")
            canvas["node_count"] = len(canvas["data"].get("nodes") or []) if isinstance(canvas["data"].get("nodes"), list) else 0
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
            member = self._require_member(data, user.id, canvas["team_id"])
            require_visible_record(canvas, user, member, "Canvas not found")
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
            member = self._require_member(data, user.id, canvas["team_id"])
            require_visible_record(canvas, user, member, "Canvas not found")
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

    def publish_canvas(self, user: CurrentUser, canvas_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            canvas = self._find_canvas(data, canvas_id)
            if not canvas:
                raise HTTPException(status_code=404, detail="Canvas not found")
            member = self._require_member(data, user.id, canvas["team_id"])
            require_visible_record(canvas, user, member, "Canvas not found")
            require_publish_permission(canvas, user, member)
            canvas["visibility"] = "team"
            canvas["updated_by"] = user.id
            canvas["updated_at"] = now_ms()
            self._write(data)
            return {"canvas": canvas}

    def list_assets(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            member = self._require_member(data, user.id, team_id)
            return [
                asset
                for asset in data["assets"]
                if asset.get("team_id") == team_id
                and record_is_visible_to_user(asset, user, member)
            ]

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
                "visibility": normalize_visibility(asset.get("visibility")),
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
            require_visible_record(asset, user, member, "Team asset not found")
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

    def publish_asset(self, user: CurrentUser, team_id: str, asset_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            member = self._require_member(data, user.id, team_id)
            asset = self._find_asset(data, team_id, asset_id)
            if not asset:
                raise HTTPException(status_code=404, detail="Team asset not found")
            require_visible_record(asset, user, member, "Team asset not found")
            require_publish_permission(asset, user, member)
            asset["visibility"] = "team"
            self._write(data)
            return {"asset": asset}

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

    def require_api_admin_member(self, user: CurrentUser, team_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            member = self._require_member(data, user.id, team_id)
            require_api_admin(member)
            return member

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

    def bootstrap(self, user: CurrentUser, team_id: str = "", project_id: str = "") -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            memberships = [m for m in data["members"] if m.get("user_id") == user.id]
            teams_by_id = {team["id"]: team for team in data["teams"]}
            teams = [{**teams_by_id[m["team_id"]], "role": m.get("role", "member")} for m in memberships if m.get("team_id") in teams_by_id]
            selected_team_id = team_id if any(team.get("id") == team_id for team in teams) else (teams[0].get("id") if teams else "")
            members: List[Dict[str, Any]] = []
            projects: List[Dict[str, Any]] = []
            canvases: List[Dict[str, Any]] = []
            providers: List[Dict[str, Any]] = []
            logs: List[Dict[str, Any]] = []
            summary = generation_log_summary([])
            points = None
            admin = False
            selected_project_id = ""
            if selected_team_id:
                member = self._require_member(data, user.id, selected_team_id)
                admin = member.get("role") in {"owner", "admin"}
                members = [m for m in data["members"] if m.get("team_id") == selected_team_id]
                projects = [p for p in data["projects"] if p.get("team_id") == selected_team_id and not p.get("archived_at")]
                projects.sort(key=lambda item: int(item.get("updated_at") or 0), reverse=True)
                selected_project_id = project_id if any(p.get("id") == project_id for p in projects) else (projects[0].get("id") if projects else "")
                if selected_project_id:
                    canvases = [
                        self._canvas_summary(canvas)
                        for canvas in data["canvases"]
                        if canvas.get("project_id") == selected_project_id and record_is_visible_to_user(canvas, user, member)
                    ]
                if admin:
                    providers = [
                        public_team_api_provider(record)
                        for record in data["api_providers"]
                        if record.get("team_id") == selected_team_id
                    ]
                    providers.sort(key=lambda item: item.get("provider_id") or "")
                logs = [item for item in data["generation_logs"] if item.get("team_id") == selected_team_id]
                logs.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
                logs = logs[:100]
                summary = generation_log_summary(logs)
                points = self._ensure_points_record(data, selected_team_id, user.id)
                self._write(data)
            return {
                "user": user.model_dump(),
                "teams": teams,
                "selected_team_id": selected_team_id,
                "selected_project_id": selected_project_id,
                "members": members,
                "projects": projects,
                "canvases": canvases,
                "api_providers": providers,
                "generation_logs": logs,
                "generation_summary": summary,
                "points": points,
                "can_manage_team": admin,
            }

    def get_user_points(self, user: CurrentUser, team_id: str, target_user_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            actor = self._require_member(data, user.id, team_id)
            if target_user_id != user.id:
                require_team_admin(actor)
            points = self._ensure_points_record(data, team_id, target_user_id)
            self._write(data)
            return points

    def list_billing_prices(self, user: CurrentUser, team_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            prices = merged_billing_prices(team_id, [item for item in data["billing_prices"] if item.get("team_id") == team_id])
            return {"prices": prices}

    def save_billing_price(self, user: CurrentUser, team_id: str, payload: ModelBillingPriceRequest) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            actor = self._require_member(data, user.id, team_id)
            require_team_admin(actor)
            key = billing_price_key(payload.provider_id, payload.model, payload.operation_type)
            record = next((item for item in data["billing_prices"] if item.get("team_id") == team_id and billing_price_key(item.get("provider_id"), item.get("model"), item.get("operation_type")) == key), None)
            now = now_ms()
            values = {
                "id": record.get("id") if record else str(uuid.uuid4()),
                "team_id": team_id,
                "provider_id": normalize_billing_provider_id(payload.provider_id),
                "model": normalize_billing_model(payload.model),
                "operation_type": normalize_operation_type(payload.operation_type),
                "points_cost": max(0, int(payload.points_cost)),
                "provider_points_cost": max(0, int(payload.points_cost)) * 100,
                "enabled": bool(payload.enabled),
                "note": payload.note,
                "updated_at": now,
                "updated_by": user.id,
            }
            if record:
                record.update(values)
            else:
                data["billing_prices"].append(values)
            self._write(data)
            return {"price": billing_price_public(values)}

    def list_provider_recharges(self, user: CurrentUser, team_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            actor = self._require_member(data, user.id, team_id)
            require_team_admin(actor)
            rows = [item for item in data["provider_recharges"] if item.get("team_id") == team_id]
            rows = sorted(rows, key=lambda item: parse_timestamp(item.get("recharged_at") or item.get("created_at")), reverse=True)
            return {"recharges": rows or default_recharge_rows(team_id), "summary": recharge_cost_summary(rows or default_recharge_rows(team_id))}

    def save_provider_recharge(self, user: CurrentUser, team_id: str, payload: ProviderRechargeRequest) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            actor = self._require_member(data, user.id, team_id)
            require_team_admin(actor)
            now = now_ms()
            row = {
                "id": str(uuid.uuid4()),
                "team_id": team_id,
                "provider_id": normalize_billing_provider_id(payload.provider_id),
                "amount_cny": round(float(payload.amount_cny), 4),
                "provider_points_received": max(0, int(payload.provider_points_received)),
                "app_points_received": max(0, int(payload.app_points_received or round(payload.provider_points_received / 100))),
                "note": payload.note,
                "recharged_at": now,
                "created_at": now,
                "created_by": user.id,
            }
            data["provider_recharges"].append(row)
            self._write(data)
            rows = [item for item in data["provider_recharges"] if item.get("team_id") == team_id]
            return {"recharge": row, "summary": recharge_cost_summary(rows)}

    def billing_quote(self, user: CurrentUser, team_id: str, provider_id: str, model: str, operation_type: str, units: int = 1) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            prices = merged_billing_prices(team_id, [item for item in data["billing_prices"] if item.get("team_id") == team_id])
            quote = billing_quote_from_prices(prices, provider_id, model, operation_type, units)
            points = self._ensure_points_record(data, team_id, user.id)
            recharges = [item for item in data["provider_recharges"] if item.get("team_id") == team_id] or default_recharge_rows(team_id)
            quote["balance"] = int(points.get("balance") or 0)
            quote["estimated_cost_cny"] = round(quote["required_points"] * recharge_cost_summary(recharges)["cost_per_point_cny"], 4)
            return quote

    def assert_points_available(self, user: CurrentUser, team_id: str, operation_type: str, provider_id: str = "", model: str = "", units: int = 1) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            prices = merged_billing_prices(team_id, [item for item in data["billing_prices"] if item.get("team_id") == team_id])
            quote = billing_quote_from_prices(prices, provider_id, model, operation_type, units)
            required = quote["required_points"]
            points = self._ensure_points_record(data, team_id, user.id)
            if int(points.get("balance") or 0) < required:
                raise HTTPException(status_code=402, detail=f"点数不足：本次需要 {required} 点，当前余额 {points.get('balance') or 0} 点")
            self._write(data)
            return {**quote, "points": points}

    def create_usage_log(self, user: CurrentUser, team_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        operation_type = normalize_operation_type(payload.get("operation_type"))
        status = str(payload.get("status") or "succeeded")
        with self.lock:
            data = self._read()
            self._require_member(data, user.id, team_id)
            prices = merged_billing_prices(team_id, [item for item in data["billing_prices"] if item.get("team_id") == team_id])
            units = max(1, int(payload.get("image_count") or payload.get("video_count") or payload.get("request_count") or 1))
            quote = billing_quote_from_prices(prices, payload.get("provider_id"), payload.get("model"), operation_type, units)
            if status == "succeeded" and payload.get("points_charged") is not None:
                try:
                    points = max(0, int(payload.get("points_charged")))
                except (TypeError, ValueError):
                    points = 0
            else:
                points = quote["required_points"] if status == "succeeded" else 0
            recharges = [item for item in data["provider_recharges"] if item.get("team_id") == team_id] or default_recharge_rows(team_id)
            cost_per_point = recharge_cost_summary(recharges)["cost_per_point_cny"]
            record = {
                "id": str(uuid.uuid4()),
                "team_id": team_id,
                "project_id": str(payload.get("project_id") or ""),
                "canvas_id": str(payload.get("canvas_id") or ""),
                "user_id": user.id,
                "operation_type": operation_type,
                "provider_id": str(payload.get("provider_id") or ""),
                "model": str(payload.get("model") or ""),
                "status": status,
                "points_charged": points,
                "provider_points_charged": quote["unit_provider_points"] * units if status == "succeeded" else 0,
                "estimated_cost_cny": round(points * cost_per_point, 4),
                "request_count": max(1, int(payload.get("request_count") or 1)),
                "image_count": max(0, int(payload.get("image_count") or 0)),
                "video_count": max(0, int(payload.get("video_count") or 0)),
                "latency_ms": max(0, int(payload.get("latency_ms") or 0)),
                "request_summary": payload.get("request_summary") if isinstance(payload.get("request_summary"), dict) else {},
                "result_summary": payload.get("result_summary") if isinstance(payload.get("result_summary"), dict) else {},
                "error": str(payload.get("error") or "")[:1000],
                "created_at": now_ms(),
                "finished_at": now_ms() if status in {"succeeded", "failed"} else None,
            }
            data["api_usage_logs"].append(record)
            if points:
                point_record = self._ensure_points_record(data, team_id, user.id)
                point_record["balance"] = int(point_record.get("balance") or 0) - points
                point_record["updated_at"] = now_ms()
                data["point_ledger"].append({
                    "id": str(uuid.uuid4()),
                    "team_id": team_id,
                    "user_id": user.id,
                    "delta": -points,
                    "reason": f"usage:{operation_type}",
                    "source_log_id": record["id"],
                    "created_by": user.id,
                    "note": "",
                    "created_at": now_ms(),
                })
            self._write(data)
            return record

    def heartbeat_session(self, user: CurrentUser, payload: SessionHeartbeatRequest, request: Optional[Request] = None) -> Dict[str, Any]:
        team_id = str(payload.team_id or "").strip()
        session_id = str(payload.session_id or "").strip() or str(uuid.uuid4())
        now = now_ms()
        user_agent_hash = ""
        if request:
            ua = request.headers.get("user-agent", "")
            user_agent_hash = hashlib.sha1(ua.encode("utf-8")).hexdigest()[:16] if ua else ""
        with self.lock:
            data = self._read()
            if team_id:
                self._require_member(data, user.id, team_id)
            session = next((item for item in data["user_sessions"] if item.get("session_id") == session_id and item.get("user_id") == user.id), None)
            if not session:
                session = {
                    "id": str(uuid.uuid4()),
                    "session_id": session_id,
                    "team_id": team_id,
                    "user_id": user.id,
                    "started_at": now,
                    "last_seen_at": now,
                    "page": payload.page,
                    "user_agent_hash": user_agent_hash,
                }
                data["user_sessions"].append(session)
            else:
                session["team_id"] = team_id or session.get("team_id") or ""
                session["last_seen_at"] = now
                session["page"] = payload.page
                if user_agent_hash:
                    session["user_agent_hash"] = user_agent_hash
            self._write(data)
            return {**session, "online": True}

    def adjust_user_points(self, user: CurrentUser, team_id: str, target_user_id: str, payload: PointsAdjustRequest) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            actor = self._require_member(data, user.id, team_id)
            require_team_admin(actor)
            self._require_member(data, target_user_id, team_id)
            points = self._ensure_points_record(data, team_id, target_user_id)
            old_balance = int(points.get("balance") or 0)
            if payload.mode in {"set", "reset"}:
                new_balance = max(0, int(payload.delta or 0))
                delta = new_balance - old_balance
            else:
                delta = int(payload.delta or 0)
                new_balance = max(0, old_balance + delta)
                delta = new_balance - old_balance
            points["balance"] = new_balance
            points["updated_at"] = now_ms()
            data["point_ledger"].append({
                "id": str(uuid.uuid4()),
                "team_id": team_id,
                "user_id": target_user_id,
                "delta": delta,
                "reason": f"admin:{payload.mode}",
                "source_log_id": "",
                "created_by": user.id,
                "note": payload.note,
                "created_at": now_ms(),
            })
            self._write(data)
            return {"points": points, "delta": delta}

    def admin_overview(self, user: CurrentUser, team_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            member = self._require_member(data, user.id, team_id)
            require_team_admin(member)
            logs = [item for item in data["api_usage_logs"] if item.get("team_id") == team_id]
            sessions = [item for item in data["user_sessions"] if item.get("team_id") == team_id]
            return build_admin_overview(team_id, logs, sessions)

    def admin_users(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        with self.lock:
            data = self._read()
            member = self._require_member(data, user.id, team_id)
            require_team_admin(member)
            return build_admin_users(
                team_id,
                [m for m in data["members"] if m.get("team_id") == team_id],
                [],
                [p for p in data["user_points"] if p.get("team_id") == team_id],
                [l for l in data["api_usage_logs"] if l.get("team_id") == team_id],
                [s for s in data["user_sessions"] if s.get("team_id") == team_id],
            )

    def admin_user_detail(self, user: CurrentUser, team_id: str, target_user_id: str) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            member = self._require_member(data, user.id, team_id)
            require_team_admin(member)
            members = [m for m in data["members"] if m.get("team_id") == team_id]
            if not any(m.get("user_id") == target_user_id for m in members):
                raise HTTPException(status_code=404, detail="用户不在该团队")
            logs = [l for l in data["api_usage_logs"] if l.get("team_id") == team_id and l.get("user_id") == target_user_id]
            logs.sort(key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
            sessions = [s for s in data["user_sessions"] if s.get("team_id") == team_id and s.get("user_id") == target_user_id]
            points = self._ensure_points_record(data, team_id, target_user_id)
            return build_admin_user_detail(target_user_id, points, logs, sessions)

    def admin_usage_logs(self, user: CurrentUser, team_id: str, filters: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            data = self._read()
            member = self._require_member(data, user.id, team_id)
            require_team_admin(member)
            logs = [item for item in data["api_usage_logs"] if item.get("team_id") == team_id]
            return filter_usage_logs(logs, filters)

    def _ensure_points_record(self, data: Dict[str, Any], team_id: str, user_id: str) -> Dict[str, Any]:
        record = next((item for item in data["user_points"] if item.get("team_id") == team_id and item.get("user_id") == user_id), None)
        if record:
            return record
        record = {
            "id": str(uuid.uuid4()),
            "team_id": team_id,
            "user_id": user_id,
            "balance": TEAM_POINTS_DEFAULT_BALANCE,
            "monthly_quota": TEAM_POINTS_DEFAULT_BALANCE,
            "created_at": now_ms(),
            "updated_at": now_ms(),
        }
        data["user_points"].append(record)
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
        summary = {key: canvas.get(key) for key in (
            "id",
            "team_id",
            "project_id",
            "title",
            "version",
            "visibility",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        )}
        data = canvas.get("data") if isinstance(canvas.get("data"), dict) else {}
        summary["kind"] = str(canvas.get("kind") or data.get("kind") or "classic")
        summary["node_count"] = int(
            canvas.get("node_count")
            if canvas.get("node_count") is not None
            else len(data.get("nodes") or []) if isinstance(data.get("nodes"), list) else 0
        )
        return summary

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
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()

    async def _request(self, method: str, path: str, *, json_body: Any = None) -> Any:
        client = await self._get_client()
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

    @staticmethod
    def _is_missing_table_error(exc: HTTPException, table: str) -> bool:
        detail = str(getattr(exc, "detail", "") or "")
        return (
            getattr(exc, "status_code", None) == 502
            and "PGRST205" in detail
            and f"public.{table}" in detail
        )

    async def _optional_table_request(self, table: str, method: str, path: str, *, json_body: Any = None, fallback: Any = None) -> Any:
        try:
            return await self._request(method, path, json_body=json_body)
        except HTTPException as exc:
            if self._is_missing_table_error(exc, table):
                return [] if fallback is None else fallback
            raise

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client and not self._client.is_closed:
            return self._client
        async with self._client_lock:
            if not self._client or self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=15)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def list_user_teams(self, user: CurrentUser) -> List[Dict[str, Any]]:
        rows = await self._request(
            "GET",
            f"/team_members?select=role,teams(id,name,owner_id,created_at,updated_at)&user_id=eq.{user.id}",
        )
        return [{**row["teams"], "role": row["role"]} for row in rows if row.get("teams")]

    async def reconcile_email_identity(self, user: CurrentUser) -> List[str]:
        email = normalize_email(user.email)
        if not email:
            return []
        legacy_memberships = await self._request(
            "GET",
            f"/team_members?email=eq.{quote(email, safe='')}&user_id=neq.{quote(user.id, safe='')}&select=*",
        )
        migrated_team_ids: List[str] = []
        for member in legacy_memberships or []:
            team_id = str(member.get("team_id") or "")
            legacy_user_id = str(member.get("user_id") or "")
            if not team_id or not legacy_user_id:
                continue
            current_memberships = await self._request(
                "GET",
                f"/team_members?team_id=eq.{quote(team_id, safe='')}&user_id=eq.{quote(user.id, safe='')}&select=id",
            )
            if current_memberships:
                continue
            await self._request(
                "PATCH",
                f"/team_members?id=eq.{quote(str(member.get('id') or ''), safe='')}",
                json_body={"user_id": user.id, "email": email},
            )
            legacy_points = await self._optional_table_request(
                "user_points",
                "GET",
                f"/user_points?team_id=eq.{quote(team_id, safe='')}&user_id=eq.{quote(legacy_user_id, safe='')}&select=id",
            )
            current_points = await self._optional_table_request(
                "user_points",
                "GET",
                f"/user_points?team_id=eq.{quote(team_id, safe='')}&user_id=eq.{quote(user.id, safe='')}&select=id",
            )
            if legacy_points and not current_points:
                await self._optional_table_request(
                    "user_points",
                    "PATCH",
                    f"/user_points?id=eq.{quote(str(legacy_points[0].get('id') or ''), safe='')}",
                    json_body={"user_id": user.id, "updated_at": utc_now_iso()},
                )
            migrated_team_ids.append(team_id)
        return migrated_team_ids

    async def ensure_team_member(self, user: CurrentUser, team_id: str, role: str) -> Dict[str, Any]:
        if role not in TEAM_ROLES:
            role = "member"
        teams = await self._request("GET", f"/teams?id=eq.{quote(team_id, safe='')}&select=id")
        if not teams:
            raise HTTPException(status_code=404, detail="默认团队不存在")
        rows = await self._request(
            "GET",
            f"/team_members?team_id=eq.{quote(team_id, safe='')}&user_id=eq.{quote(user.id, safe='')}&select=*",
        )
        if rows:
            return rows[0]
        created = await self._request(
            "POST",
            "/team_members",
            json_body=[{
                "team_id": team_id,
                "user_id": user.id,
                "email": user.email,
                "role": role,
            }],
        )
        return created[0] if created else {}

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
        member = await self._require_member(user.id, team_id)
        projects = await self._request(
            "GET",
            f"/projects?team_id=eq.{team_id}&archived_at=is.null&order=updated_at.desc&select=*",
        )
        if member.get("role") in {"owner", "admin"}:
            return projects or []
        visible_canvases = await self._request(
            "GET",
            f"/canvases?team_id=eq.{team_id}&or=(visibility.eq.team,created_by.eq.{quote(user.id, safe='')})&select=project_id",
        )
        visible_project_ids = {row.get("project_id") for row in visible_canvases or []}
        return [
            project
            for project in projects or []
            if project.get("created_by") == user.id or project.get("id") in visible_project_ids
        ]

    async def workspace(
        self,
        user: CurrentUser,
        team_id: str,
        member: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        member = member or await self._require_member(user.id, team_id)
        visibility_filter = ""
        if member.get("role") not in {"owner", "admin"}:
            visibility_filter = f"&or=(visibility.eq.team,created_by.eq.{quote(user.id, safe='')})"
        projects, canvases = await asyncio.gather(
            self._request(
                "GET",
                f"/projects?team_id=eq.{quote(team_id, safe='')}&archived_at=is.null&order=updated_at.desc&select=*",
            ),
            self._request(
                "GET",
                f"/canvases?team_id=eq.{quote(team_id, safe='')}{visibility_filter}&order=updated_at.desc&select=id,team_id,project_id,title,version,visibility,kind,node_count,created_by,updated_by,created_at,updated_at",
            ),
        )
        if member.get("role") not in {"owner", "admin"}:
            visible_project_ids = {canvas.get("project_id") for canvas in canvases or []}
            projects = [
                project
                for project in projects or []
                if project.get("created_by") == user.id or project.get("id") in visible_project_ids
            ]
        return {"projects": projects or [], "canvases": canvases or [], "trash_count": 0}

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
        member = await self._require_member(user.id, project["team_id"])
        visibility_filter = ""
        if member.get("role") not in {"owner", "admin"}:
            visibility_filter = f"&or=(visibility.eq.team,created_by.eq.{quote(user.id, safe='')})"
        return await self._request(
            "GET",
            f"/canvases?team_id=eq.{project['team_id']}&project_id=eq.{project_id}{visibility_filter}&order=updated_at.desc&select=id,team_id,project_id,title,version,visibility,kind,node_count,created_by,updated_by,created_at,updated_at",
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
                "kind": str((canvas_data or {}).get("kind") or "classic"),
                "node_count": len((canvas_data or {}).get("nodes") or []) if isinstance((canvas_data or {}).get("nodes"), list) else 0,
                "version": 1,
                "visibility": "private",
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
        member = await self._require_member(user.id, canvas["team_id"])
        require_visible_record(canvas, user, member, "Canvas not found")
        return canvas

    async def save_canvas(self, user: CurrentUser, canvas_id: str, payload: CanvasSaveRequest) -> Dict[str, Any]:
        canvas = await self.get_canvas(user, canvas_id)
        if payload.base_version is not None and payload.base_version != canvas.get("version"):
            raise HTTPException(status_code=409, detail={"message": "画布已被更新，请刷新后再保存", "canvas": canvas})
        next_version = int(canvas.get("version") or 1) + 1
        patch = {
            "data": payload.data or {},
            "kind": str((payload.data or {}).get("kind") or canvas.get("kind") or "classic"),
            "node_count": len((payload.data or {}).get("nodes") or []) if isinstance((payload.data or {}).get("nodes"), list) else 0,
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

    async def publish_canvas(self, user: CurrentUser, canvas_id: str) -> Dict[str, Any]:
        canvas = await self.get_canvas(user, canvas_id)
        member = await self._require_member(user.id, canvas["team_id"])
        require_publish_permission(canvas, user, member)
        rows = await self._request(
            "PATCH",
            f"/canvases?id=eq.{canvas_id}",
            json_body={
                "visibility": "team",
                "updated_by": user.id,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        return {"canvas": (rows or [canvas])[0]}

    async def list_assets(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        member = await self._require_member(user.id, team_id)
        visibility_filter = ""
        if member.get("role") not in {"owner", "admin"}:
            visibility_filter = f"&or=(visibility.eq.team,created_by.eq.{quote(user.id, safe='')})"
        return await self._request(
            "GET",
            f"/assets?team_id=eq.{team_id}{visibility_filter}&order=created_at.desc&select=*",
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
            "visibility": normalize_visibility(asset.get("visibility")),
            "created_by": user.id,
        }
        if asset.get("thumbnail_storage_key"):
            body["thumbnail_storage_key"] = asset.get("thumbnail_storage_key")
        while True:
            try:
                rows = await self._request("POST", "/assets", json_body=[body])
                break
            except HTTPException as exc:
                match = re.search(r"column assets\.([a-zA-Z0-9_]+) does not exist", str(exc.detail))
                missing_column = match.group(1) if match else ""
                if not missing_column or missing_column not in body:
                    raise
                body.pop(missing_column, None)
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
        require_visible_record(asset, user, member, "Team asset not found")
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

    async def publish_asset(self, user: CurrentUser, team_id: str, asset_id: str) -> Dict[str, Any]:
        member = await self._require_member(user.id, team_id)
        assets = await self._request(
            "GET",
            f"/assets?team_id=eq.{team_id}&id=eq.{asset_id}&select=*",
        )
        if not assets:
            raise HTTPException(status_code=404, detail="Team asset not found")
        asset = assets[0]
        require_visible_record(asset, user, member, "Team asset not found")
        require_publish_permission(asset, user, member)
        rows = await self._request(
            "PATCH",
            f"/assets?team_id=eq.{team_id}&id=eq.{asset_id}",
            json_body={"visibility": "team"},
        )
        return {"asset": (rows or [asset])[0]}

    async def list_api_providers(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        await self._require_member(user.id, team_id)
        rows = await self._request("GET", f"/api_providers?team_id=eq.{team_id}&order=provider_id.asc&select=*")
        return [public_team_api_provider(row) for row in rows or []]

    async def require_api_admin_member(self, user: CurrentUser, team_id: str) -> Dict[str, Any]:
        member = await self._require_member(user.id, team_id)
        require_api_admin(member)
        return member

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

    async def bootstrap(self, user: CurrentUser, team_id: str = "", project_id: str = "") -> Dict[str, Any]:
        teams = await self.list_user_teams(user)
        selected_team_id = team_id if any(team.get("id") == team_id for team in teams) else (teams[0].get("id") if teams else "")
        if not selected_team_id:
            return {
                "user": user.model_dump(),
                "teams": teams,
                "selected_team_id": "",
                "selected_project_id": "",
                "members": [],
                "projects": [],
                "canvases": [],
                "api_providers": [],
                "generation_logs": [],
                "generation_summary": generation_log_summary([]),
                "points": None,
                "can_manage_team": False,
            }
        member = await self._require_member(user.id, selected_team_id)
        can_manage = member.get("role") in {"owner", "admin"}
        members_task = self._request("GET", f"/team_members?team_id=eq.{selected_team_id}&select=*")
        projects_task = self._request("GET", f"/projects?team_id=eq.{selected_team_id}&archived_at=is.null&order=updated_at.desc&select=*")
        logs_task = self.list_generation_logs(user, selected_team_id, 100)
        providers_task = self.list_api_providers(user, selected_team_id) if can_manage else asyncio.sleep(0, result=[])
        points_task = self.get_user_points(user, selected_team_id, user.id)
        members, projects, logs, providers, points = await asyncio.gather(
            members_task,
            projects_task,
            logs_task,
            providers_task,
            points_task,
        )
        selected_project_id = project_id if any(project.get("id") == project_id for project in projects or []) else ((projects or [{}])[0].get("id") or "")
        canvases = await self.list_canvases(user, selected_project_id) if selected_project_id else []
        return {
            "user": user.model_dump(),
            "teams": teams,
            "selected_team_id": selected_team_id,
            "selected_project_id": selected_project_id,
            "members": members or [],
            "projects": projects or [],
            "canvases": canvases,
            "api_providers": providers or [],
            "generation_logs": logs or [],
            "generation_summary": generation_log_summary(logs or []),
            "points": points,
            "can_manage_team": can_manage,
        }

    async def get_user_points(self, user: CurrentUser, team_id: str, target_user_id: str) -> Dict[str, Any]:
        actor = await self._require_member(user.id, team_id)
        if target_user_id != user.id:
            require_team_admin(actor)
        return await self._ensure_points_record(team_id, target_user_id)

    async def list_billing_prices(self, user: CurrentUser, team_id: str) -> Dict[str, Any]:
        await self._require_member(user.id, team_id)
        try:
            rows = await self._request("GET", f"/billing_prices?team_id=eq.{team_id}&order=provider_id.asc&select=*")
        except HTTPException as exc:
            if self._is_missing_table_error(exc, "billing_prices"):
                rows = await self._billing_prices_from_provider_configs(team_id)
            else:
                raise
        return {"prices": merged_billing_prices(team_id, rows or [])}

    async def save_billing_price(self, user: CurrentUser, team_id: str, payload: ModelBillingPriceRequest) -> Dict[str, Any]:
        actor = await self._require_member(user.id, team_id)
        require_team_admin(actor)
        provider_id = normalize_billing_provider_id(payload.provider_id)
        model = normalize_billing_model(payload.model)
        operation_type = normalize_operation_type(payload.operation_type)
        try:
            rows = await self._request(
                "GET",
                f"/billing_prices?team_id=eq.{team_id}&provider_id=eq.{quote(provider_id, safe='')}&model=eq.{quote(model, safe='')}&operation_type=eq.{operation_type}&select=*",
            )
        except HTTPException as exc:
            if self._is_missing_table_error(exc, "billing_prices"):
                record = await self._save_billing_price_to_provider_config(user, team_id, provider_id, model, operation_type, payload)
                return {"price": billing_price_public(record)}
            raise
        body = {
            "team_id": team_id,
            "provider_id": provider_id,
            "model": model,
            "operation_type": operation_type,
            "points_cost": max(0, int(payload.points_cost)),
            "provider_points_cost": max(0, int(payload.points_cost)) * 100,
            "enabled": bool(payload.enabled),
            "note": payload.note,
            "updated_at": utc_now_iso(),
            "updated_by": user.id,
        }
        if rows:
            updated = await self._optional_table_request(
                "billing_prices",
                "PATCH",
                f"/billing_prices?team_id=eq.{team_id}&provider_id=eq.{quote(provider_id, safe='')}&model=eq.{quote(model, safe='')}&operation_type=eq.{operation_type}",
                json_body=body,
                fallback=[body],
            )
            record = updated[0] if updated else body
        else:
            created = await self._optional_table_request("billing_prices", "POST", "/billing_prices", json_body=[body], fallback=[body])
            record = created[0] if created else body
        return {"price": billing_price_public(record)}

    async def list_provider_recharges(self, user: CurrentUser, team_id: str) -> Dict[str, Any]:
        actor = await self._require_member(user.id, team_id)
        require_team_admin(actor)
        try:
            rows = await self._request("GET", f"/provider_recharges?team_id=eq.{team_id}&order=recharged_at.desc&select=*")
        except HTTPException as exc:
            if self._is_missing_table_error(exc, "provider_recharges"):
                rows = await self._provider_recharges_from_provider_configs(team_id)
            else:
                raise
        recharges = rows or default_recharge_rows(team_id)
        return {"recharges": recharges, "summary": recharge_cost_summary(recharges)}

    async def save_provider_recharge(self, user: CurrentUser, team_id: str, payload: ProviderRechargeRequest) -> Dict[str, Any]:
        actor = await self._require_member(user.id, team_id)
        require_team_admin(actor)
        body = {
            "team_id": team_id,
            "provider_id": normalize_billing_provider_id(payload.provider_id),
            "amount_cny": round(float(payload.amount_cny), 4),
            "provider_points_received": max(0, int(payload.provider_points_received)),
            "app_points_received": max(0, int(payload.app_points_received or round(payload.provider_points_received / 100))),
            "note": payload.note,
            "recharged_at": utc_now_iso(),
            "created_by": user.id,
        }
        try:
            created = await self._request("POST", "/provider_recharges", json_body=[body])
            rows = await self._request("GET", f"/provider_recharges?team_id=eq.{team_id}&select=*")
        except HTTPException as exc:
            if self._is_missing_table_error(exc, "provider_recharges"):
                created = [await self._save_provider_recharge_to_provider_config(user, team_id, body)]
                rows = await self._provider_recharges_from_provider_configs(team_id)
            else:
                raise
        return {"recharge": (created[0] if created else body), "summary": recharge_cost_summary(rows or [])}

    async def billing_quote(self, user: CurrentUser, team_id: str, provider_id: str, model: str, operation_type: str, units: int = 1) -> Dict[str, Any]:
        await self._require_member(user.id, team_id)
        rows, points, recharges = await asyncio.gather(
            self._billing_price_rows(team_id),
            self._ensure_points_record(team_id, user.id),
            self._provider_recharge_rows(team_id),
        )
        quote = billing_quote_from_prices(merged_billing_prices(team_id, rows or []), provider_id, model, operation_type, units)
        quote["balance"] = int(points.get("balance") or 0)
        quote["estimated_cost_cny"] = round(quote["required_points"] * recharge_cost_summary(recharges or default_recharge_rows(team_id))["cost_per_point_cny"], 4)
        return quote

    async def assert_points_available(self, user: CurrentUser, team_id: str, operation_type: str, provider_id: str = "", model: str = "", units: int = 1) -> Dict[str, Any]:
        await self._require_member(user.id, team_id)
        rows = await self._billing_price_rows(team_id)
        quote = billing_quote_from_prices(merged_billing_prices(team_id, rows or []), provider_id, model, operation_type, units)
        required = quote["required_points"]
        points = await self._ensure_points_record(team_id, user.id)
        if int(points.get("balance") or 0) < required:
            raise HTTPException(status_code=402, detail=f"点数不足：本次需要 {required} 点，当前余额 {points.get('balance') or 0} 点")
        return {**quote, "points": points}

    async def create_usage_log(self, user: CurrentUser, team_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        await self._require_member(user.id, team_id)
        operation_type = normalize_operation_type(payload.get("operation_type"))
        status = str(payload.get("status") or "succeeded")
        rows, recharges = await asyncio.gather(
            self._billing_price_rows(team_id),
            self._provider_recharge_rows(team_id),
        )
        units = max(1, int(payload.get("image_count") or payload.get("video_count") or payload.get("request_count") or 1))
        quote = billing_quote_from_prices(merged_billing_prices(team_id, rows or []), payload.get("provider_id"), payload.get("model"), operation_type, units)
        if status == "succeeded" and payload.get("points_charged") is not None:
            try:
                points = max(0, int(payload.get("points_charged")))
            except (TypeError, ValueError):
                points = 0
        else:
            points = quote["required_points"] if status == "succeeded" else 0
        cost_per_point = recharge_cost_summary(recharges or default_recharge_rows(team_id))["cost_per_point_cny"]
        body = {
            "team_id": team_id,
            "project_id": payload.get("project_id") or None,
            "canvas_id": payload.get("canvas_id") or None,
            "user_id": user.id,
            "operation_type": operation_type,
            "provider_id": str(payload.get("provider_id") or ""),
            "model": str(payload.get("model") or ""),
            "status": status,
            "points_charged": points,
            "provider_points_charged": quote["provider_points_charged"] if status == "succeeded" else 0,
            "estimated_cost_cny": round(points * cost_per_point, 4),
            "request_count": max(1, int(payload.get("request_count") or 1)),
            "image_count": max(0, int(payload.get("image_count") or 0)),
            "video_count": max(0, int(payload.get("video_count") or 0)),
            "latency_ms": max(0, int(payload.get("latency_ms") or 0)),
            "request_summary": payload.get("request_summary") if isinstance(payload.get("request_summary"), dict) else {},
            "result_summary": payload.get("result_summary") if isinstance(payload.get("result_summary"), dict) else {},
            "error": str(payload.get("error") or "")[:1000],
            "finished_at": utc_now_iso() if status in {"succeeded", "failed"} else None,
        }
        try:
            created = await self._optional_table_request("api_usage_logs", "POST", "/api_usage_logs", json_body=[body], fallback=[body])
        except HTTPException as exc:
            detail = str(getattr(exc, "detail", "") or "")
            if "provider_points_charged" not in detail and "estimated_cost_cny" not in detail:
                raise
            legacy_body = {key: value for key, value in body.items() if key not in {"provider_points_charged", "estimated_cost_cny"}}
            created = await self._optional_table_request("api_usage_logs", "POST", "/api_usage_logs", json_body=[legacy_body], fallback=[legacy_body])
        record = created[0] if created else body
        if points:
            point_record = await self._ensure_points_record(team_id, user.id)
            next_balance = max(0, int(point_record.get("balance") or 0) - points)
            await self._optional_table_request(
                "user_points",
                "PATCH",
                f"/user_points?team_id=eq.{team_id}&user_id=eq.{user.id}",
                json_body={"balance": next_balance, "updated_at": utc_now_iso()},
            )
            await self._optional_table_request("point_ledger", "POST", "/point_ledger", json_body=[{
                "team_id": team_id,
                "user_id": user.id,
                "delta": -points,
                "reason": f"usage:{operation_type}",
                "source_log_id": record.get("id"),
                "created_by": user.id,
                "note": "",
            }])
        return record

    async def heartbeat_session(self, user: CurrentUser, payload: SessionHeartbeatRequest, request: Optional[Request] = None) -> Dict[str, Any]:
        team_id = str(payload.team_id or "").strip()
        if team_id:
            await self._require_member(user.id, team_id)
        session_id = str(payload.session_id or "").strip() or str(uuid.uuid4())
        user_agent_hash = ""
        if request:
            ua = request.headers.get("user-agent", "")
            user_agent_hash = hashlib.sha1(ua.encode("utf-8")).hexdigest()[:16] if ua else ""
        rows = await self._optional_table_request(
            "user_sessions",
            "GET",
            f"/user_sessions?session_id=eq.{quote(session_id, safe='')}&user_id=eq.{quote(user.id, safe='')}&select=*",
        )
        body = {
            "team_id": team_id or None,
            "last_seen_at": utc_now_iso(),
            "page": payload.page,
            "user_agent_hash": user_agent_hash,
        }
        if rows:
            updated = await self._optional_table_request(
                "user_sessions",
                "PATCH",
                f"/user_sessions?session_id=eq.{quote(session_id, safe='')}&user_id=eq.{quote(user.id, safe='')}",
                json_body=body,
            )
            session = updated[0] if updated else {**rows[0], **body}
        else:
            created = await self._optional_table_request("user_sessions", "POST", "/user_sessions", json_body=[{
                "session_id": session_id,
                "team_id": team_id or None,
                "user_id": user.id,
                "started_at": utc_now_iso(),
                "last_seen_at": utc_now_iso(),
                "page": payload.page,
                "user_agent_hash": user_agent_hash,
            }])
            session = created[0] if created else {"session_id": session_id, **body}
        return {**session, "online": True}

    async def adjust_user_points(self, user: CurrentUser, team_id: str, target_user_id: str, payload: PointsAdjustRequest) -> Dict[str, Any]:
        actor = await self._require_member(user.id, team_id)
        require_team_admin(actor)
        await self._require_member(target_user_id, team_id)
        points = await self._ensure_points_record(team_id, target_user_id)
        old_balance = int(points.get("balance") or 0)
        if payload.mode in {"set", "reset"}:
            new_balance = max(0, int(payload.delta or 0))
            delta = new_balance - old_balance
        else:
            delta = int(payload.delta or 0)
            new_balance = max(0, old_balance + delta)
            delta = new_balance - old_balance
        updated = await self._optional_table_request(
            "user_points",
            "PATCH",
            f"/user_points?team_id=eq.{team_id}&user_id=eq.{target_user_id}",
            json_body={"balance": new_balance, "updated_at": utc_now_iso()},
            fallback=[{**points, "balance": new_balance}],
        )
        await self._optional_table_request("point_ledger", "POST", "/point_ledger", json_body=[{
            "team_id": team_id,
            "user_id": target_user_id,
            "delta": delta,
            "reason": f"admin:{payload.mode}",
            "source_log_id": None,
            "created_by": user.id,
            "note": payload.note,
        }])
        return {"points": (updated[0] if updated else {**points, "balance": new_balance}), "delta": delta}

    async def admin_overview(self, user: CurrentUser, team_id: str) -> Dict[str, Any]:
        member = await self._require_member(user.id, team_id)
        require_team_admin(member)
        logs, sessions = await asyncio.gather(
            self._optional_table_request("api_usage_logs", "GET", f"/api_usage_logs?team_id=eq.{team_id}&order=created_at.desc&limit={TEAM_ADMIN_USAGE_LIMIT}&select=*"),
            self._optional_table_request("user_sessions", "GET", f"/user_sessions?team_id=eq.{team_id}&order=last_seen_at.desc&limit=1000&select=*"),
        )
        return build_admin_overview(team_id, logs or [], sessions or [])

    async def admin_users(self, user: CurrentUser, team_id: str) -> List[Dict[str, Any]]:
        member = await self._require_member(user.id, team_id)
        require_team_admin(member)
        members, points, logs, sessions = await asyncio.gather(
            self._request("GET", f"/team_members?team_id=eq.{team_id}&select=*"),
            self._optional_table_request("user_points", "GET", f"/user_points?team_id=eq.{team_id}&select=*"),
            self._optional_table_request("api_usage_logs", "GET", f"/api_usage_logs?team_id=eq.{team_id}&order=created_at.desc&limit={TEAM_ADMIN_USAGE_LIMIT}&select=*"),
            self._optional_table_request("user_sessions", "GET", f"/user_sessions?team_id=eq.{team_id}&order=last_seen_at.desc&limit=1000&select=*"),
        )
        user_ids = [str(item.get("user_id") or "") for item in members or [] if item.get("user_id")]
        profiles = await self._profiles_for_user_ids(user_ids)
        return build_admin_users(team_id, members or [], profiles, points or [], logs or [], sessions or [])

    async def admin_user_detail(self, user: CurrentUser, team_id: str, target_user_id: str) -> Dict[str, Any]:
        member = await self._require_member(user.id, team_id)
        require_team_admin(member)
        await self._require_member(target_user_id, team_id)
        points, logs, sessions = await asyncio.gather(
            self._ensure_points_record(team_id, target_user_id),
            self._optional_table_request("api_usage_logs", "GET", f"/api_usage_logs?team_id=eq.{team_id}&user_id=eq.{target_user_id}&order=created_at.desc&limit=500&select=*"),
            self._optional_table_request("user_sessions", "GET", f"/user_sessions?team_id=eq.{team_id}&user_id=eq.{target_user_id}&order=last_seen_at.desc&limit=100&select=*"),
        )
        return build_admin_user_detail(target_user_id, points, logs or [], sessions or [])

    async def admin_usage_logs(self, user: CurrentUser, team_id: str, filters: Dict[str, Any]) -> Dict[str, Any]:
        member = await self._require_member(user.id, team_id)
        require_team_admin(member)
        logs = await self._optional_table_request(
            "api_usage_logs",
            "GET",
            f"/api_usage_logs?team_id=eq.{team_id}&order=created_at.desc&limit={TEAM_ADMIN_USAGE_LIMIT}&select=*",
        )
        return filter_usage_logs(logs or [], filters)

    async def _billing_price_rows(self, team_id: str) -> List[Dict[str, Any]]:
        try:
            return await self._request("GET", f"/billing_prices?team_id=eq.{team_id}&select=*")
        except HTTPException as exc:
            if self._is_missing_table_error(exc, "billing_prices"):
                return await self._billing_prices_from_provider_configs(team_id)
            raise

    async def _provider_recharge_rows(self, team_id: str) -> List[Dict[str, Any]]:
        try:
            return await self._request("GET", f"/provider_recharges?team_id=eq.{team_id}&select=*")
        except HTTPException as exc:
            if self._is_missing_table_error(exc, "provider_recharges"):
                return await self._provider_recharges_from_provider_configs(team_id)
            raise

    async def _billing_prices_from_provider_configs(self, team_id: str) -> List[Dict[str, Any]]:
        providers = await self._request("GET", f"/api_providers?team_id=eq.{team_id}&select=*")
        rows: List[Dict[str, Any]] = []
        for provider in providers or []:
            config = decrypt_team_api_config(provider.get("encrypted_config"))
            for item in config.get("billing_prices") or []:
                if isinstance(item, dict):
                    rows.append({**item, "team_id": team_id, "provider_id": item.get("provider_id") or provider.get("provider_id") or ""})
        return rows

    async def _provider_recharges_from_provider_configs(self, team_id: str) -> List[Dict[str, Any]]:
        providers = await self._request("GET", f"/api_providers?team_id=eq.{team_id}&select=*")
        rows: List[Dict[str, Any]] = []
        for provider in providers or []:
            config = decrypt_team_api_config(provider.get("encrypted_config"))
            for item in config.get("provider_recharges") or []:
                if isinstance(item, dict):
                    rows.append({**item, "team_id": team_id, "provider_id": item.get("provider_id") or provider.get("provider_id") or ""})
        return rows

    async def _save_billing_price_to_provider_config(self, user: CurrentUser, team_id: str, provider_id: str, model: str, operation_type: str, payload: ModelBillingPriceRequest) -> Dict[str, Any]:
        rows = await self._request("GET", f"/api_providers?team_id=eq.{team_id}&provider_id=eq.{quote(provider_id, safe='')}&select=*")
        if not rows:
            raise HTTPException(status_code=404, detail="请先在 API 设置里添加该平台，再设置模型积分")
        provider = rows[0]
        config = decrypt_team_api_config(provider.get("encrypted_config"))
        prices = [item for item in (config.get("billing_prices") or []) if isinstance(item, dict)]
        key = billing_price_key(provider_id, model, operation_type)
        record = {
            "id": f"provider-config:{provider_id}:{operation_type}:{model}",
            "team_id": team_id,
            "provider_id": provider_id,
            "model": model,
            "operation_type": operation_type,
            "points_cost": max(0, int(payload.points_cost)),
            "provider_points_cost": max(0, int(payload.points_cost)) * 100,
            "enabled": bool(payload.enabled),
            "note": payload.note,
            "updated_at": utc_now_iso(),
        }
        prices = [item for item in prices if billing_price_key(item.get("provider_id") or provider_id, item.get("model"), item.get("operation_type")) != key]
        prices.append(record)
        config["billing_prices"] = prices
        await self._request(
            "PATCH",
            f"/api_providers?team_id=eq.{team_id}&provider_id=eq.{quote(provider_id, safe='')}",
            json_body={"encrypted_config": encrypt_team_api_config(config), "updated_by": user.id, "updated_at": utc_now_iso()},
        )
        return record

    async def _save_provider_recharge_to_provider_config(self, user: CurrentUser, team_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        provider_id = normalize_billing_provider_id(body.get("provider_id"))
        rows = await self._request("GET", f"/api_providers?team_id=eq.{team_id}&provider_id=eq.{quote(provider_id, safe='')}&select=*")
        if not rows:
            raise HTTPException(status_code=404, detail="请先在 API 设置里添加该平台，再记录充值")
        provider = rows[0]
        config = decrypt_team_api_config(provider.get("encrypted_config"))
        recharges = [item for item in (config.get("provider_recharges") or []) if isinstance(item, dict)]
        row = {**body, "id": str(uuid.uuid4()), "created_at": utc_now_iso()}
        recharges.append(row)
        config["provider_recharges"] = recharges
        await self._request(
            "PATCH",
            f"/api_providers?team_id=eq.{team_id}&provider_id=eq.{quote(provider_id, safe='')}",
            json_body={"encrypted_config": encrypt_team_api_config(config), "updated_by": user.id, "updated_at": utc_now_iso()},
        )
        return row

    async def _ensure_points_record(self, team_id: str, user_id: str) -> Dict[str, Any]:
        fallback = {
            "team_id": team_id,
            "user_id": user_id,
            "balance": TEAM_POINTS_DEFAULT_BALANCE,
            "monthly_quota": TEAM_POINTS_DEFAULT_BALANCE,
        }
        rows = await self._optional_table_request(
            "user_points",
            "GET",
            f"/user_points?team_id=eq.{team_id}&user_id=eq.{user_id}&select=*",
        )
        if rows:
            return rows[0]
        created = await self._optional_table_request("user_points", "POST", "/user_points", json_body=[{
            "team_id": team_id,
            "user_id": user_id,
            "balance": TEAM_POINTS_DEFAULT_BALANCE,
            "monthly_quota": TEAM_POINTS_DEFAULT_BALANCE,
        }], fallback=[fallback])
        return created[0] if created else fallback

    async def _profiles_for_user_ids(self, user_ids: List[str]) -> List[Dict[str, Any]]:
        ids = [quote(str(item), safe="") for item in user_ids if str(item or "").strip()]
        if not ids:
            return []
        joined = ",".join(ids)
        try:
            return await self._request("GET", f"/user_profiles?user_id=in.({joined})&select=user_id,email,username,display_name")
        except HTTPException:
            return []

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


def team_cloud_version() -> str:
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), "r", encoding="utf-8") as handle:
            return (handle.read().strip().splitlines() or [""])[0]
    except OSError:
        return ""


def require_profile_store() -> SupabaseTeamStore:
    if not supabase_store:
        raise HTTPException(status_code=503, detail="Supabase 用户资料表未配置")
    return supabase_store


async def get_user_profile_by_username(username: str) -> Optional[Dict[str, Any]]:
    store = require_profile_store()
    rows = await store._request(
        "GET",
        f"/user_profiles?username=eq.{quote(username, safe='')}&select=user_id,email,username,display_name&limit=1",
    )
    return rows[0] if rows else None


async def get_user_profile_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not supabase_store:
        return None
    rows = await supabase_store._request(
        "GET",
        f"/user_profiles?email=eq.{quote(normalize_email(email), safe='')}&select=user_id,email,username,display_name&limit=1",
    )
    return rows[0] if rows else None


async def get_user_profile_by_user_id(user_id: str) -> Optional[Dict[str, Any]]:
    if not supabase_store:
        return None
    rows = await supabase_store._request(
        "GET",
        f"/user_profiles?user_id=eq.{quote(user_id, safe='')}&select=user_id,email,username,display_name&limit=1",
    )
    return rows[0] if rows else None


async def pending_profile_request(method: str, path: str, *, json_body: Any = None) -> Any:
    if not supabase_store:
        return None
    try:
        return await supabase_store._request(method, path, json_body=json_body)
    except HTTPException as exc:
        # New deployments can run before the optional pending table migration is applied.
        detail = str(exc.detail or "")
        if "pending_user_profiles" in detail or "schema cache" in detail or "Could not find" in detail:
            return None
        raise


async def get_pending_profile_by_email(email: str) -> Optional[Dict[str, Any]]:
    rows = await pending_profile_request(
        "GET",
        f"/pending_user_profiles?email=eq.{quote(normalize_email(email), safe='')}&select=*&limit=1",
    )
    return rows[0] if rows else None


async def get_pending_profile_by_username(username: str) -> Optional[Dict[str, Any]]:
    rows = await pending_profile_request(
        "GET",
        f"/pending_user_profiles?username=eq.{quote(normalize_username(username), safe='')}&select=*&limit=1",
    )
    return rows[0] if rows else None


async def save_pending_user_profile(user_id: str, email: str, username: str) -> None:
    if not supabase_store:
        return
    email = normalize_email(email)
    username = normalize_username(username)
    existing = await get_pending_profile_by_email(email)
    payload = {
        "user_id": user_id,
        "email": email,
        "username": username,
        "display_name": username,
        "updated_at": utc_now_iso(),
    }
    if existing:
        await pending_profile_request(
            "PATCH",
            f"/pending_user_profiles?email=eq.{quote(email, safe='')}",
            json_body=payload,
        )
        return
    await pending_profile_request("POST", "/pending_user_profiles", json_body=[payload])


async def mark_pending_user_profile_verified(email: str, user_id: str) -> None:
    await pending_profile_request(
        "PATCH",
        f"/pending_user_profiles?email=eq.{quote(normalize_email(email), safe='')}",
        json_body={"user_id": user_id, "verified_at": utc_now_iso(), "updated_at": utc_now_iso()},
    )


async def create_user_profile(user_id: str, email: str, username: str) -> Dict[str, Any]:
    store = require_profile_store()
    rows = await store._request(
        "POST",
        "/user_profiles",
        json_body=[{
            "user_id": user_id,
            "email": email,
            "username": username,
            "display_name": username,
        }],
    )
    return rows[0] if rows else {}


async def ensure_user_profile(user_id: str, email: str, username: str) -> Dict[str, Any]:
    profile = await get_user_profile_by_user_id(user_id)
    if profile:
        return profile
    existing_email = await get_user_profile_by_email(email)
    if existing_email and existing_email.get("user_id") != user_id:
        raise HTTPException(status_code=409, detail="该邮箱已绑定其他账号")
    existing_username = await get_user_profile_by_username(username)
    if existing_username and existing_username.get("user_id") != user_id:
        raise HTTPException(status_code=409, detail="账号名已被使用")
    return await create_user_profile(user_id, email, username)


async def ensure_confirmed_auth_profile(user_id: str, email: str) -> Dict[str, Any]:
    username = normalize_username(str(email or "").split("@", 1)[0])
    if not username:
        username = f"user-{str(user_id or '')[:8]}"
    try:
        return await ensure_user_profile(user_id, email, username)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        fallback = normalize_username(f"{username}-{str(user_id or '')[:8]}")
        return await ensure_user_profile(user_id, email, fallback)


async def resolve_auth_identifier_email(identifier: str) -> str:
    identifier = str(identifier or "").strip()
    if looks_like_email(identifier):
        return auth_email_required(identifier)
    username = normalize_username(identifier)
    now = time.monotonic()
    cached = _username_email_cache.get(username)
    if cached and cached[1] > now:
        _username_email_cache.move_to_end(username)
        return cached[0]
    if cached:
        _username_email_cache.pop(username, None)
    profile = await get_user_profile_by_username(username)
    if not profile or not profile.get("email"):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    email = normalize_email(profile["email"])
    _username_email_cache[username] = (email, now + TEAM_AUTH_USERNAME_CACHE_SECONDS)
    _username_email_cache.move_to_end(username)
    while len(_username_email_cache) > TEAM_AUTH_USERNAME_CACHE_MAX_ENTRIES:
        _username_email_cache.popitem(last=False)
    return email


async def legacy_admin_login_without_email_verification(user_id: str, email: str, profile: Optional[Dict[str, Any]]) -> bool:
    """Allow existing owner/admin accounts through after the email OTP rollout."""
    if not user_id or not profile:
        return False
    current = CurrentUser(
        id=str(user_id),
        email=normalize_email(email),
        username=str(profile.get("username") or ""),
        display_name=str(profile.get("display_name") or profile.get("username") or ""),
        provider="supabase",
    )
    try:
        teams = await maybe_await(active_store().list_user_teams(current))
    except Exception:
        return False
    return any(str(team.get("role") or "").lower() in {"owner", "admin"} for team in teams or [])


async def enrich_user_profile(user: CurrentUser) -> CurrentUser:
    try:
        profile = await get_user_profile_by_user_id(user.id)
    except HTTPException:
        profile = None
    if profile:
        user.username = str(profile.get("username") or "")
        user.display_name = str(profile.get("display_name") or user.username)
        if not user.email:
            user.email = str(profile.get("email") or "")
    return user


async def resolve_team_api_provider_config(user: CurrentUser, team_id: str, provider_id: str) -> Dict[str, Any]:
    return await maybe_await(active_store().get_api_provider_config(user, team_id, provider_id))


async def record_team_generation_log(user: CurrentUser, team_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return await maybe_await(active_store().create_generation_log(user, team_id, payload))


async def assert_team_points_available(
    user: CurrentUser,
    team_id: str,
    operation_type: str,
    provider_id: str = "",
    model: str = "",
    units: int = 1,
) -> Dict[str, Any]:
    checker = getattr(active_store(), "assert_points_available", None)
    if not checker:
        return {"required_points": 0, "points": None}
    return await maybe_await(checker(user, team_id, operation_type, provider_id, model, units))


async def record_team_usage_log(user: CurrentUser, team_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    writer = getattr(active_store(), "create_usage_log", None)
    if not writer:
        return {}
    return await maybe_await(writer(user, team_id, payload))


async def list_team_billing_prices(user: CurrentUser, team_id: str) -> Dict[str, Any]:
    reader = getattr(active_store(), "list_billing_prices", None)
    if not reader:
        return {"prices": []}
    return await maybe_await(reader(user, team_id))


async def save_team_billing_price(user: CurrentUser, team_id: str, payload: ModelBillingPriceRequest) -> Dict[str, Any]:
    writer = getattr(active_store(), "save_billing_price", None)
    if not writer:
        return {"price": {}}
    return await maybe_await(writer(user, team_id, payload))


async def list_team_provider_recharges(user: CurrentUser, team_id: str) -> Dict[str, Any]:
    reader = getattr(active_store(), "list_provider_recharges", None)
    if not reader:
        return {"recharges": [], "summary": {"amount_cny": 0, "app_points_received": 0, "provider_points_received": 0, "cost_per_point_cny": 0}}
    return await maybe_await(reader(user, team_id))


async def save_team_provider_recharge(user: CurrentUser, team_id: str, payload: ProviderRechargeRequest) -> Dict[str, Any]:
    writer = getattr(active_store(), "save_provider_recharge", None)
    if not writer:
        return {"recharge": {}, "summary": {}}
    return await maybe_await(writer(user, team_id, payload))


async def quote_team_billing(user: CurrentUser, team_id: str, provider_id: str, model: str, operation_type: str, units: int = 1) -> Dict[str, Any]:
    reader = getattr(active_store(), "billing_quote", None)
    if not reader:
        return billing_quote_from_prices([], provider_id, model, operation_type, units)
    return await maybe_await(reader(user, team_id, provider_id, model, operation_type, units))


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


def usage_summary(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "total": len(logs),
        "succeeded": 0,
        "failed": 0,
        "image_count": 0,
        "video_count": 0,
        "points_charged": 0,
        "provider_points_charged": 0,
        "estimated_cost_cny": 0,
        "slow_count": 0,
        "models": {},
        "providers": {},
        "operations": {},
    }
    for log in logs:
        status = str(log.get("status") or "")
        if status == "succeeded":
            summary["succeeded"] += 1
        elif status == "failed":
            summary["failed"] += 1
        summary["image_count"] += int(log.get("image_count") or 0)
        summary["video_count"] += int(log.get("video_count") or 0)
        summary["points_charged"] += int(log.get("points_charged") or 0)
        summary["provider_points_charged"] += int(log.get("provider_points_charged") or 0)
        summary["estimated_cost_cny"] = round(float(summary["estimated_cost_cny"]) + float(log.get("estimated_cost_cny") or 0), 4)
        if int(log.get("latency_ms") or 0) >= 500:
            summary["slow_count"] += 1
        for key, field in (("models", "model"), ("providers", "provider_id"), ("operations", "operation_type")):
            name = str(log.get(field) or "unknown")
            summary[key][name] = int(summary[key].get(name) or 0) + 1
    return summary


def build_admin_overview(team_id: str, logs: List[Dict[str, Any]], sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    now = time.time()
    today_start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    month_start = datetime.datetime.now(datetime.timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    today_logs = [log for log in logs if parse_timestamp(log.get("created_at")) >= today_start]
    month_logs = [log for log in logs if parse_timestamp(log.get("created_at")) >= month_start]
    active_user_ids = {
        str(session.get("user_id") or "")
        for session in sessions
        if now - parse_timestamp(session.get("last_seen_at")) <= TEAM_SESSION_ONLINE_WINDOW_SECONDS
    }
    active_user_ids.discard("")
    total = len(today_logs)
    failed = sum(1 for log in today_logs if str(log.get("status") or "") == "failed")
    return {
        "team_id": team_id,
        "today": usage_summary(today_logs),
        "month": usage_summary(month_logs),
        "all_time": usage_summary(logs),
        "active_users": len(active_user_ids),
        "error_rate": (failed / total) if total else 0,
        "online_window_seconds": TEAM_SESSION_ONLINE_WINDOW_SECONDS,
    }


def build_admin_users(
    team_id: str,
    members: List[Dict[str, Any]],
    profiles: List[Dict[str, Any]],
    points_rows: List[Dict[str, Any]],
    logs: List[Dict[str, Any]],
    sessions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    profiles_by_id = {str(item.get("user_id") or ""): item for item in profiles}
    points_by_user = {str(item.get("user_id") or ""): item for item in points_rows}
    rows = []
    for member in members:
        user_id = str(member.get("user_id") or "")
        user_logs = [log for log in logs if str(log.get("user_id") or "") == user_id]
        user_sessions = [session for session in sessions if str(session.get("user_id") or "") == user_id]
        last_seen = max((parse_timestamp(session.get("last_seen_at")) for session in user_sessions), default=0)
        active_seconds = 0
        for session in user_sessions:
            started = parse_timestamp(session.get("started_at"))
            seen = parse_timestamp(session.get("last_seen_at"))
            if started and seen and seen >= started:
                active_seconds += min(int(seen - started), 24 * 60 * 60)
        profile = profiles_by_id.get(user_id, {})
        point_record = points_by_user.get(user_id) or {
            "team_id": team_id,
            "user_id": user_id,
            "balance": TEAM_POINTS_DEFAULT_BALANCE,
            "monthly_quota": TEAM_POINTS_DEFAULT_BALANCE,
        }
        rows.append({
            **public_member_user(member, profile),
            "points": point_record,
            "usage": usage_summary(user_logs),
            "last_seen_at": datetime.datetime.fromtimestamp(last_seen, datetime.timezone.utc).isoformat().replace("+00:00", "Z") if last_seen else None,
            "online": online_status_from_last_seen(last_seen),
            "active_seconds": active_seconds,
        })
    rows.sort(key=lambda item: (not item.get("online"), -(parse_timestamp(item.get("last_seen_at")) or 0), item.get("email") or item.get("user_id") or ""))
    return rows


def build_admin_user_detail(target_user_id: str, points: Dict[str, Any], logs: List[Dict[str, Any]], sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    day_counts: Dict[str, int] = {}
    for log in logs:
        ts = parse_timestamp(log.get("created_at"))
        if not ts:
            continue
        day = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")
        day_counts[day] = day_counts.get(day, 0) + 1
    return {
        "user_id": target_user_id,
        "points": points,
        "usage": usage_summary(logs),
        "daily": [{"date": day, "count": count} for day, count in sorted(day_counts.items())[-30:]],
        "recent_logs": sorted(logs, key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)[:100],
        "sessions": [
            {**session, "online": online_status_from_last_seen(session.get("last_seen_at"))}
            for session in sorted(sessions, key=lambda item: parse_timestamp(item.get("last_seen_at")), reverse=True)[:20]
        ],
    }


def filter_usage_logs(logs: List[Dict[str, Any]], filters: Dict[str, Any]) -> Dict[str, Any]:
    user_id = str(filters.get("user_id") or "").strip()
    provider_id = str(filters.get("provider_id") or "").strip()
    model = str(filters.get("model") or "").strip()
    status = str(filters.get("status") or "").strip()
    operation_type = str(filters.get("operation_type") or "").strip()
    try:
        limit = max(1, min(500, int(filters.get("limit") or 100)))
    except (TypeError, ValueError):
        limit = 100
    try:
        offset = max(0, int(filters.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0
    since = parse_timestamp(filters.get("since"))
    until = parse_timestamp(filters.get("until"))
    filtered = []
    for log in logs:
        ts = parse_timestamp(log.get("created_at"))
        if user_id and str(log.get("user_id") or "") != user_id:
            continue
        if provider_id and str(log.get("provider_id") or "") != provider_id:
            continue
        if model and str(log.get("model") or "") != model:
            continue
        if status and str(log.get("status") or "") != status:
            continue
        if operation_type and str(log.get("operation_type") or "") != operation_type:
            continue
        if since and ts < since:
            continue
        if until and ts > until:
            continue
        filtered.append(log)
    filtered.sort(key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
    return {
        "logs": filtered[offset:offset + limit],
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "summary": usage_summary(filtered),
    }


@router.get("/config")
async def team_cloud_config() -> Dict[str, Any]:
    return public_config()


async def start_email_password_signup(payload: AuthEmailPasswordRequest) -> Dict[str, Any]:
    email = auth_email_required(payload.email)
    username = normalize_username(payload.username or "")
    if await get_user_profile_by_username(username):
        raise HTTPException(status_code=409, detail="账号名已被使用")
    if await get_user_profile_by_email(email):
        raise HTTPException(status_code=409, detail="邮箱已注册，请直接登录或找回密码")
    pending_email = await get_pending_profile_by_email(email)
    if pending_email and pending_email.get("username") and pending_email.get("username") != username:
        raise HTTPException(status_code=409, detail="该邮箱正在等待验证，请使用原账号名完成验证")
    pending_username = await get_pending_profile_by_username(username)
    if pending_username and pending_username.get("email") and normalize_email(pending_username.get("email")) != email:
        raise HTTPException(status_code=409, detail="账号名已被使用")
    data = await supabase_auth_request("signup", {
        "email": email,
        "password": payload.password,
        "data": {
            "username": username,
            "display_name": username,
        },
    })
    user = data.get("user") or {}
    user_id = str(user.get("id") or "")
    if user_id:
        await save_pending_user_profile(user_id, email, username)
    return {
        "ok": True,
        "verification_required": True,
        "session_ready": False,
        "email": email,
        "username": username,
        "message": "验证码已发送，请查看邮箱并完成验证。",
    }


@router.post("/auth/signup/start")
async def signup_start(payload: AuthEmailPasswordRequest) -> Dict[str, Any]:
    return await start_email_password_signup(payload)


@router.post("/auth/signup")
async def signup(payload: AuthEmailPasswordRequest) -> Dict[str, Any]:
    return await start_email_password_signup(payload)


@router.post("/auth/signup/verify")
async def signup_verify(payload: AuthSignupVerifyRequest, response: Response) -> Dict[str, Any]:
    email = auth_email_required(payload.email)
    data = await supabase_verify_signup_otp(email, payload.token)
    if not data.get("access_token"):
        raise HTTPException(status_code=401, detail="验证码无效或已过期")
    user = data.get("user") or {}
    user_id = str(user.get("id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="验证码已通过，但登录凭证缺少用户 ID")
    pending = await get_pending_profile_by_email(email)
    username = str((pending or {}).get("username") or "")
    if not username:
        try:
            username = user_metadata_username(user)
        except HTTPException:
            username = email.split("@", 1)[0].lower()
            username = re.sub(r"[^a-z0-9_-]+", "-", username).strip("-_")[:32] or f"user-{user_id[:8]}"
            if len(username) < 3:
                username = f"user-{user_id[:8]}"
    username = normalize_username(username)
    await ensure_user_profile(user_id, email, username)
    await mark_pending_user_profile_verified(email, user_id)
    set_auth_cookie(response, data["access_token"])
    payload_out = sanitize_auth_payload(data)
    payload_out["user"]["username"] = username
    payload_out["user"]["display_name"] = username
    payload_out["verification_required"] = False
    return payload_out


@router.post("/auth/verification/resend")
async def verification_resend(payload: AuthVerificationResendRequest, request: Request) -> Dict[str, Any]:
    email = auth_email_required(payload.email)
    key = f"{email}:{request.client.host if request.client else ''}"
    now = time.time()
    last = float(_verification_resend_times.get(key) or 0)
    if now - last < TEAM_AUTH_VERIFICATION_RESEND_SECONDS:
        wait = int(TEAM_AUTH_VERIFICATION_RESEND_SECONDS - (now - last)) + 1
        raise HTTPException(status_code=429, detail=f"验证码发送太频繁，请 {wait} 秒后再试")
    _verification_resend_times[key] = now
    await supabase_resend_signup_otp(email)
    return {"ok": True, "message": "验证码已重新发送。"}


def record_request_timing(request: Optional[Request], name: str, started: float) -> None:
    if not request:
        return
    timings = getattr(getattr(request, "state", None), "server_timings", None)
    if isinstance(timings, list):
        timings.append(f"{name};dur={(time.perf_counter() - started) * 1000:.1f}")


@router.post("/auth/login")
async def login(
    payload: AuthEmailPasswordRequest,
    response: Response,
    request: Request = None,
) -> Dict[str, Any]:
    login_started = time.perf_counter()
    stage_started = time.perf_counter()
    email = await resolve_auth_identifier_email(auth_identifier(payload))
    record_request_timing(request, "auth_identifier", stage_started)
    stage_started = time.perf_counter()
    data = await supabase_auth_request("token?grant_type=password", {
        "email": email,
        "password": payload.password,
    })
    record_request_timing(request, "supabase_auth", stage_started)
    if not data.get("access_token"):
        raise HTTPException(status_code=401, detail="登录失败")
    user = data.get("user") or {}
    user_id = str(user.get("id") or "")
    stage_started = time.perf_counter()
    if not supabase_user_email_confirmed(user):
        profile = await get_user_profile_by_user_id(user_id)
        if profile and await legacy_admin_login_without_email_verification(user_id, email, profile):
            set_auth_cookie(response, data["access_token"])
            payload_out = sanitize_auth_payload(data)
            payload_out["legacy_email_verification_bypassed"] = True
            payload_out["user"]["username"] = profile.get("username") or ""
            payload_out["user"]["display_name"] = profile.get("display_name") or profile.get("username") or ""
            record_request_timing(request, "auth_profile", stage_started)
            record_request_timing(request, "auth_response", login_started)
            return payload_out
        clear_auth_cookie(response)
        raise HTTPException(status_code=403, detail="请先完成邮箱验证码验证")

    metadata = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
    metadata_username = str(metadata.get("username") or "").strip().lower()
    if not USERNAME_PATTERN.fullmatch(metadata_username):
        metadata_username = ""
    metadata_display_name = str(metadata.get("display_name") or metadata_username).strip()
    profile = None
    if not metadata_username:
        profile = await get_user_profile_by_user_id(user_id)
        if not profile:
            profile = await ensure_confirmed_auth_profile(user_id, email)
        if not profile:
            clear_auth_cookie(response)
            raise HTTPException(status_code=403, detail="请先完成邮箱验证码验证")
    set_auth_cookie(response, data["access_token"])
    payload_out = sanitize_auth_payload(data)
    if metadata_username:
        payload_out["user"]["username"] = metadata_username
        payload_out["user"]["display_name"] = metadata_display_name or metadata_username
    elif profile:
        payload_out["user"]["username"] = profile.get("username") or ""
        payload_out["user"]["display_name"] = profile.get("display_name") or profile.get("username") or ""
    record_request_timing(request, "auth_profile", stage_started)
    record_request_timing(request, "auth_response", login_started)
    return payload_out


@router.post("/auth/recover")
async def recover_password(payload: AuthRecoverRequest) -> Dict[str, Any]:
    try:
        email = await resolve_auth_identifier_email(auth_identifier(payload))
    except HTTPException:
        return {"ok": True, "message": "如果账号存在，将发送找回密码邮件。"}
    try:
        await supabase_auth_request("recover", {"email": email})
    except HTTPException:
        return {"ok": True, "message": "如果账号存在，将发送找回密码邮件。"}
    return {"ok": True}


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
    user = await enrich_user_profile(user)
    teams = await maybe_await(active_store().list_user_teams(user))
    return {"user": user.model_dump(), "teams": teams}


@router.get("/workspace")
async def team_cloud_workspace(
    team_id: str = "",
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    user, teams = await asyncio.gather(
        enrich_user_profile(user),
        maybe_await(active_store().list_user_teams(user)),
    )
    selected_team = next((team for team in teams if str(team.get("id") or "") == team_id), None)
    if not selected_team:
        selected_team = teams[0] if teams else None
    if not selected_team:
        return {
            "user": user.model_dump(),
            "teams": [],
            "selected_team": None,
            "projects": [],
            "canvases": [],
            "trash_count": 0,
            "version": team_cloud_version(),
        }
    workspace = await maybe_await(
        active_store().workspace(user, str(selected_team.get("id") or ""), selected_team)
    )
    return {
        "user": user.model_dump(),
        "teams": teams,
        "selected_team": selected_team,
        "projects": workspace.get("projects") or [],
        "canvases": workspace.get("canvases") or [],
        "trash_count": int(workspace.get("trash_count") or 0),
        "version": team_cloud_version(),
    }


async def workbench_account_summary(request: Request) -> Dict[str, Any]:
    user = await optional_current_user(request)
    if not user:
        return {"user": None, "teams": [], "points": None}
    user, teams = await asyncio.gather(
        enrich_user_profile(user),
        maybe_await(active_store().list_user_teams(user)),
    )
    selected_team_id = str((teams[0] if teams else {}).get("id") or "")
    points = None
    if selected_team_id:
        getter = getattr(active_store(), "get_user_points", None)
        if getter:
            points = await maybe_await(getter(user, selected_team_id, user.id))
    return {
        "user": user.model_dump(),
        "teams": teams,
        "points": points,
    }


@router.get("/bootstrap")
async def team_cloud_bootstrap(
    team_id: str = "",
    project_id: str = "",
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    user = await enrich_user_profile(user)
    bootstrap = getattr(active_store(), "bootstrap", None)
    if not bootstrap:
        teams = await maybe_await(active_store().list_user_teams(user))
        return {"user": user.model_dump(), "teams": teams}
    return await maybe_await(bootstrap(user, team_id, project_id))


@router.post("/sessions/heartbeat")
async def team_session_heartbeat(
    payload: SessionHeartbeatRequest,
    request: Request,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    heartbeat = getattr(active_store(), "heartbeat_session", None)
    if not heartbeat:
        return {"ok": True, "session": {"session_id": payload.session_id or "", "online": True}}
    session = await maybe_await(heartbeat(user, payload, request))
    return {"ok": True, "session": session}


async def resolve_admin_team(user: CurrentUser, team_id: str = "") -> Tuple[str, List[Dict[str, Any]]]:
    teams = await maybe_await(active_store().list_user_teams(user))
    admin_teams = [team for team in teams if team.get("role") in {"owner", "admin"}]
    if team_id:
        if not any(team.get("id") == team_id for team in admin_teams):
            raise HTTPException(status_code=403, detail="只有团队 owner/admin 可以访问后台")
        return team_id, teams
    if not admin_teams:
        raise HTTPException(status_code=403, detail="没有可管理的团队")
    return str(admin_teams[0].get("id") or ""), teams


async def resolve_user_team(user: CurrentUser, team_id: str = "") -> Tuple[str, List[Dict[str, Any]]]:
    teams = await maybe_await(active_store().list_user_teams(user))
    if team_id:
        if not any(team.get("id") == team_id for team in teams):
            raise HTTPException(status_code=403, detail="没有访问该团队的权限")
        return team_id, teams
    if not teams:
        raise HTTPException(status_code=403, detail="当前账户还没有团队")
    return str(teams[0].get("id") or ""), teams


@router.get("/admin/overview")
async def admin_overview(team_id: str = "", user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    user = await enrich_user_profile(user)
    selected_team_id, teams = await resolve_admin_team(user, team_id)
    overview = await maybe_await(active_store().admin_overview(user, selected_team_id))
    return {"team_id": selected_team_id, "teams": teams, "overview": overview}


@router.get("/admin/users")
async def admin_users(team_id: str = "", user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    user = await enrich_user_profile(user)
    selected_team_id, teams = await resolve_admin_team(user, team_id)
    users = await maybe_await(active_store().admin_users(user, selected_team_id))
    return {"team_id": selected_team_id, "teams": teams, "users": users}


@router.get("/admin/users/{target_user_id}")
async def admin_user_detail(
    target_user_id: str,
    team_id: str = "",
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    selected_team_id, _teams = await resolve_admin_team(user, team_id)
    detail = await maybe_await(active_store().admin_user_detail(user, selected_team_id, target_user_id))
    return {"team_id": selected_team_id, "detail": detail}


@router.post("/admin/users/{target_user_id}/points")
async def admin_adjust_user_points(
    target_user_id: str,
    payload: PointsAdjustRequest,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    selected_team_id, _teams = await resolve_admin_team(user, payload.team_id)
    return await maybe_await(active_store().adjust_user_points(user, selected_team_id, target_user_id, payload))


@router.get("/billing/model-prices")
async def billing_model_prices(team_id: str = "", user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    user = await enrich_user_profile(user)
    selected_team_id, teams = await resolve_user_team(user, team_id)
    data = await list_team_billing_prices(user, selected_team_id)
    return {"team_id": selected_team_id, "teams": teams, **data}


@router.get("/billing/quote")
async def billing_quote(
    team_id: str = "",
    provider_id: str = "",
    model: str = "",
    operation_type: str = "image",
    units: int = 1,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    user = await enrich_user_profile(user)
    selected_team_id, _teams = await resolve_user_team(user, team_id)
    return await quote_team_billing(user, selected_team_id, provider_id, model, operation_type, units)


@router.post("/admin/billing/model-prices")
async def admin_save_billing_model_price(payload: ModelBillingPriceRequest, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    user = await enrich_user_profile(user)
    selected_team_id, teams = await resolve_admin_team(user, payload.team_id)
    data = await save_team_billing_price(user, selected_team_id, payload)
    return {"team_id": selected_team_id, "teams": teams, **data}


@router.get("/admin/billing/recharges")
async def admin_provider_recharges(team_id: str = "", user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    user = await enrich_user_profile(user)
    selected_team_id, teams = await resolve_admin_team(user, team_id)
    data = await list_team_provider_recharges(user, selected_team_id)
    return {"team_id": selected_team_id, "teams": teams, **data}


@router.post("/admin/billing/recharges")
async def admin_save_provider_recharge(payload: ProviderRechargeRequest, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    user = await enrich_user_profile(user)
    selected_team_id, teams = await resolve_admin_team(user, payload.team_id)
    data = await save_team_provider_recharge(user, selected_team_id, payload)
    return {"team_id": selected_team_id, "teams": teams, **data}


@router.get("/admin/usage/logs")
async def admin_usage_logs(
    team_id: str = "",
    user_id: str = "",
    provider_id: str = "",
    model: str = "",
    status: str = "",
    operation_type: str = "",
    since: str = "",
    until: str = "",
    limit: int = 100,
    offset: int = 0,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    selected_team_id, teams = await resolve_admin_team(user, team_id)
    data = await maybe_await(active_store().admin_usage_logs(user, selected_team_id, {
        "user_id": user_id,
        "provider_id": provider_id,
        "model": model,
        "status": status,
        "operation_type": operation_type,
        "since": since,
        "until": until,
        "limit": limit,
        "offset": offset,
    }))
    return {"team_id": selected_team_id, "teams": teams, **data}


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


@router.post("/canvases/{canvas_id}/publish")
async def publish_team_canvas(canvas_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    return await maybe_await(active_store().publish_canvas(user, canvas_id))


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
        "visibility": "team",
        "width": image_meta.get("width"),
        "height": image_meta.get("height"),
        **stored,
    }))
    return {"asset": asset}


@router.get("/teams/{team_id}/assets/{asset_id}/content")
async def get_team_asset_content(
    team_id: str,
    asset_id: str,
    thumbnail: bool = False,
    user: CurrentUser = Depends(require_user_or_query_token),
) -> Response:
    assets = await maybe_await(active_store().list_assets(user, team_id))
    asset = next((item for item in assets if item.get("id") == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail="团队素材不存在")
    key = str(asset.get("thumbnail_storage_key") or "") if thumbnail else ""
    key = key or str(asset.get("storage_key") or "")
    if not key:
        raise HTTPException(status_code=404, detail="团队素材文件不存在")
    try:
        stored = read_team_asset_file(key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="团队素材文件不存在") from exc
    content_type = stored.get("content_type") or asset.get("mime_type") or "application/octet-stream"
    return Response(
        content=stored.get("content") or b"",
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.delete("/teams/{team_id}/assets/{asset_id}")
async def delete_team_asset(
    team_id: str,
    asset_id: str,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    return await maybe_await(active_store().delete_asset(user, team_id, asset_id))


@router.post("/teams/{team_id}/assets/{asset_id}/publish")
async def publish_team_asset(
    team_id: str,
    asset_id: str,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    return await maybe_await(active_store().publish_asset(user, team_id, asset_id))


@router.get("/teams/{team_id}/api-providers")
async def list_team_api_providers(team_id: str, user: CurrentUser = Depends(require_user)) -> Dict[str, Any]:
    providers = await maybe_await(active_store().list_api_providers(user, team_id))
    return {"providers": providers}


async def team_api_provider_models_config(
    user: CurrentUser,
    team_id: str,
    provider_id: str,
    payload: TeamApiProviderModelsRequest,
) -> Dict[str, Any]:
    await maybe_await(active_store().require_api_admin_member(user, team_id))
    current: Dict[str, Any] = {}
    try:
        current = await maybe_await(active_store().get_api_provider_config(user, team_id, provider_id))
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    return team_api_models_config_from_payload(payload, current)


@router.put("/teams/{team_id}/api-providers/{provider_id}")
async def save_team_api_provider(
    team_id: str,
    provider_id: str,
    payload: TeamApiProviderSaveRequest,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    provider = await maybe_await(active_store().upsert_api_provider(user, team_id, provider_id, payload))
    return {"provider": provider}


@router.post("/teams/{team_id}/api-providers/{provider_id}/validate")
async def validate_team_api_provider(
    team_id: str,
    provider_id: str,
    payload: TeamApiProviderModelsRequest,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    config = await team_api_provider_models_config(user, team_id, provider_id, payload)
    result = await fetch_team_api_models_from_config(config)
    return {"ok": True, "model_count": result["model_count"]}


@router.post("/teams/{team_id}/api-providers/{provider_id}/models")
async def fetch_team_api_provider_models(
    team_id: str,
    provider_id: str,
    payload: TeamApiProviderModelsRequest,
    user: CurrentUser = Depends(require_user),
) -> Dict[str, Any]:
    config = await team_api_provider_models_config(user, team_id, provider_id, payload)
    return await fetch_team_api_models_from_config(config)


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
