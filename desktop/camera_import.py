"""Safe, dependency-free LAN importer for Metech Camera JPEG files."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

IMAGE_NAME = re.compile(r"^C\d{6}\.JPG$")
DEFAULT_CAMERA_URL = "http://192.168.1.27"


@dataclass(frozen=True)
class ImportResult:
    downloaded: list[Path]
    skipped: list[Path]
    failures: list[str]


def camera_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        raise ValueError("Nhập địa chỉ camera")
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    if "/" in value.split("://", 1)[1]:
        raise ValueError("Chỉ nhập địa chỉ camera, ví dụ 192.168.1.27")
    return value


def _json(url: str, timeout: float) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(url, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"Camera trả HTTP {response.status}")
                return json.load(response)
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Không kết nối được camera: {last_error}") from last_error


def gallery(camera: str = DEFAULT_CAMERA_URL, timeout: float = 8.0) -> list[str]:
    root = camera_url(camera)
    status = _json(root + "/api/status", timeout)
    if not status.get("sd_ready"):
        raise RuntimeError("microSD camera chưa sẵn sàng")
    payload = _json(root + "/api/gallery", timeout)
    images = payload.get("images")
    if not isinstance(images, list) or any(not isinstance(name, str) or not IMAGE_NAME.fullmatch(name) for name in images):
        raise RuntimeError("Danh sách ảnh từ camera không hợp lệ")
    return sorted(set(images))


def _is_jpeg(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return file.read(2) == b"\xff\xd8" and path.stat().st_size > 4
    except OSError:
        return False


def download_images(camera: str, destination: Path, progress: Callable[[str, int, int], None] | None = None,
                    timeout: float = 15.0) -> ImportResult:
    root = camera_url(camera)
    names = gallery(root, timeout)
    destination.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    skipped: list[Path] = []
    failures: list[str] = []
    for index, name in enumerate(names, 1):
        if progress:
            progress(name, index, len(names))
        target = destination / name
        if _is_jpeg(target):
            skipped.append(target)
            continue
        partial = target.with_suffix(".part")
        partial.unlink(missing_ok=True)
        try:
            with urlopen(root + "/image/" + name, timeout=timeout) as response:
                if response.status != 200 or response.headers.get_content_type() != "image/jpeg":
                    raise RuntimeError(f"HTTP {response.status}, không phải JPEG")
                with partial.open("wb") as file:
                    while chunk := response.read(64 * 1024):
                        file.write(chunk)
            if not _is_jpeg(partial):
                raise RuntimeError("tệp tải về không phải JPEG hợp lệ")
            partial.replace(target)
            downloaded.append(target)
        except (HTTPError, URLError, OSError, RuntimeError) as exc:
            partial.unlink(missing_ok=True)
            failures.append(f"{name}: {exc}")
    return ImportResult(downloaded, skipped, failures)
