import os
import re
import uuid
from io import BytesIO
from dataclasses import dataclass
from typing import Any, Dict


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.getenv("YISHU_ASSETS_DIR", os.path.join(BASE_DIR, "assets"))
TEAM_ASSET_DIR = os.path.join(ASSETS_DIR, "team-assets")
GENERATED_ASSET_DIR = os.path.join(ASSETS_DIR, "generated")


@dataclass
class TeamStorageSettings:
    r2_endpoint_url: str = os.getenv("R2_ENDPOINT_URL", "")
    r2_bucket: str = os.getenv("R2_BUCKET", "")
    r2_access_key_id: str = os.getenv("R2_ACCESS_KEY_ID", "")
    r2_secret_access_key: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
    r2_public_base_url: str = os.getenv("R2_PUBLIC_BASE_URL", "").rstrip("/")
    require_r2: bool = os.getenv("TEAM_ASSET_REQUIRE_R2", "").lower() in {"1", "true", "yes", "on"}

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


def safe_storage_segment(value: str, fallback: str = "files") -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or fallback)).strip("-")
    return text[:80] or fallback


def make_generated_storage_key(filename: str, *, category: str = "output", asset_id: str = "") -> str:
    clean_category = safe_storage_segment(category, "output")
    clean_asset_id = safe_storage_segment(asset_id or str(uuid.uuid4()), "file")
    return f"generated/{clean_category}/{clean_asset_id}{file_ext(filename)}"


def save_team_asset(content: bytes, *, team_id: str, filename: str, content_type: str = "", asset_id: str = "") -> Dict[str, str]:
    key = make_storage_key(team_id, filename, asset_id)
    if settings.r2_ready:
        return save_team_asset_to_r2(content, key=key, content_type=content_type)
    if settings.require_r2:
        raise RuntimeError("TEAM_ASSET_REQUIRE_R2 is enabled, but R2 storage is not fully configured")
    return save_team_asset_local(content, key=key)


def build_image_thumbnail(content: bytes, max_size: int = 512) -> Dict[str, Any]:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return {}
    try:
        with Image.open(BytesIO(content)) as img:
            img.load()
            width, height = img.size
            resample = getattr(Image, "Resampling", Image).LANCZOS
            thumb = ImageOps.exif_transpose(img)
            thumb.thumbnail((max_size, max_size), resample=resample)
            if thumb.mode in ("RGBA", "LA") or (thumb.mode == "P" and "transparency" in thumb.info):
                rgba = thumb.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                thumb = bg
            else:
                thumb = thumb.convert("RGB")
            output = BytesIO()
            thumb.save(output, format="JPEG", quality=84, optimize=True)
            return {
                "content": output.getvalue(),
                "content_type": "image/jpeg",
                "width": int(width),
                "height": int(height),
            }
    except Exception:
        return {}


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


def delete_team_asset_file(key: str) -> bool:
    clean_key = str(key or "").replace("\\", "/").lstrip("/")
    if not clean_key.startswith("team-assets/"):
        return False
    if settings.r2_ready:
        try:
            client = r2_client()
            client.delete_object(Bucket=settings.r2_bucket, Key=clean_key)
            return True
        except Exception as exc:
            print(f"删除 R2 团队素材失败：{exc}")
            return False
    target = os.path.abspath(os.path.join(ASSETS_DIR, clean_key.replace("/", os.sep)))
    root = os.path.abspath(TEAM_ASSET_DIR)
    try:
        if not target.startswith(root + os.sep):
            return False
        if os.path.isfile(target):
            os.remove(target)
            return True
    except OSError as exc:
        print(f"删除本地团队素材失败：{exc}")
    return False


def save_generated_file(content: bytes, *, filename: str, content_type: str = "", category: str = "output", asset_id: str = "") -> Dict[str, str]:
    key = make_generated_storage_key(filename, category=category, asset_id=asset_id)
    if settings.r2_ready:
        return save_team_asset_to_r2(content, key=key, content_type=content_type)
    return save_generated_file_local(content, key=key)


def save_generated_file_from_path(path: str, *, content_type: str = "", category: str = "output", asset_id: str = "") -> Dict[str, str]:
    filename = os.path.basename(path)
    with open(path, "rb") as fh:
        return save_generated_file(
            fh.read(),
            filename=filename,
            content_type=content_type,
            category=category,
            asset_id=asset_id,
        )


def save_generated_file_local(content: bytes, *, key: str) -> Dict[str, str]:
    target = os.path.abspath(os.path.join(ASSETS_DIR, key.replace("/", os.sep)))
    root = os.path.abspath(GENERATED_ASSET_DIR)
    if not target.startswith(root + os.sep):
        raise ValueError("unsafe generated storage key")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(content)
    return {
        "storage_provider": "local",
        "storage_key": key,
        "public_url": f"/assets/{key}",
    }


def save_team_asset_to_r2(content: bytes, *, key: str, content_type: str = "") -> Dict[str, str]:
    client = r2_client()
    extra = {"ContentType": content_type} if content_type else {}
    client.put_object(Bucket=settings.r2_bucket, Key=key, Body=content, **extra)
    public_url = f"{settings.r2_public_base_url}/{key}" if settings.r2_public_base_url else key
    return {
        "storage_provider": "r2",
        "storage_key": key,
        "public_url": public_url,
    }


def r2_client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for R2 storage") from exc

    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )
