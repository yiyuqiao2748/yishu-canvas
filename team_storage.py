import os
import re
import uuid
from dataclasses import dataclass
from typing import Dict


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
TEAM_ASSET_DIR = os.path.join(ASSETS_DIR, "team-assets")


@dataclass
class TeamStorageSettings:
    r2_endpoint_url: str = os.getenv("R2_ENDPOINT_URL", "")
    r2_bucket: str = os.getenv("R2_BUCKET", "")
    r2_access_key_id: str = os.getenv("R2_ACCESS_KEY_ID", "")
    r2_secret_access_key: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
    r2_public_base_url: str = os.getenv("R2_PUBLIC_BASE_URL", "").rstrip("/")

    @property
    def r2_ready(self) -> bool:
        return bool(
            self.r2_endpoint_url
            and self.r2_bucket
            and self.r2_access_key_id
            and self.r2_secret_access_key
        )


settings = TeamStorageSettings()


def safe_filename(name: str) -> str:
    text = os.path.basename(str(name or "").strip()) or "asset"
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120] or "asset"


def file_ext(name: str) -> str:
    ext = os.path.splitext(safe_filename(name))[1].lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", ext or ""):
        return ".bin"
    return ext


def make_storage_key(team_id: str, filename: str, asset_id: str = "") -> str:
    clean_team = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(team_id or "team")).strip("-") or "team"
    clean_asset_id = asset_id or str(uuid.uuid4())
    return f"team-assets/{clean_team}/{clean_asset_id}{file_ext(filename)}"


def save_team_asset(content: bytes, *, team_id: str, filename: str, content_type: str = "", asset_id: str = "") -> Dict[str, str]:
    key = make_storage_key(team_id, filename, asset_id)
    if settings.r2_ready:
        return save_team_asset_to_r2(content, key=key, content_type=content_type)
    return save_team_asset_local(content, key=key)


def save_team_asset_local(content: bytes, *, key: str) -> Dict[str, str]:
    target = os.path.abspath(os.path.join(ASSETS_DIR, key.replace("/", os.sep)))
    root = os.path.abspath(TEAM_ASSET_DIR)
    if not target.startswith(root + os.sep):
        raise ValueError("unsafe storage key")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(content)
    return {
        "storage_provider": "local",
        "storage_key": key,
        "public_url": f"/assets/{key}",
    }


def save_team_asset_to_r2(content: bytes, *, key: str, content_type: str = "") -> Dict[str, str]:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for R2 storage") from exc

    client = boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )
    extra = {"ContentType": content_type} if content_type else {}
    client.put_object(Bucket=settings.r2_bucket, Key=key, Body=content, **extra)
    public_url = f"{settings.r2_public_base_url}/{key}" if settings.r2_public_base_url else key
    return {
        "storage_provider": "r2",
        "storage_key": key,
        "public_url": public_url,
    }
