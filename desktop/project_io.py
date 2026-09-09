from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from timelapse_core import FrameItem, ProjectSettings, normalize_crop

SCHEMA_VERSION = 1


def _stored_path(path: str, project_dir: Path) -> str:
    source = Path(path).resolve()
    try:
        return str(source.relative_to(project_dir.resolve())).replace("\\", "/")
    except ValueError:
        return str(source)


def save_project(path: str | Path, items: list[FrameItem], settings: ProjectSettings) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "frames": [{**asdict(item), "path": _stored_path(item.path, destination.parent)} for item in items],
        "settings": asdict(settings),
    }
    payload["settings"]["crop"] = list(settings.crop) if settings.crop else None
    fd, temporary = tempfile.mkstemp(prefix=destination.name, suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    return destination


def load_project(path: str | Path) -> tuple[list[FrameItem], ProjectSettings]:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Phiên bản project không được hỗ trợ")
    frames = []
    for raw in data.get("frames", []):
        stored = Path(str(raw.get("path", "")))
        resolved = stored if stored.is_absolute() else source.parent / stored
        frames.append(FrameItem(path=str(resolved.resolve()),
                                rotation=int(raw.get("rotation", 0)) % 360,
                                status="pending", message=""))
    allowed = ProjectSettings.__dataclass_fields__
    settings_raw = {key: value for key, value in data.get("settings", {}).items() if key in allowed}
    if settings_raw.get("crop"):
        settings_raw["crop"] = normalize_crop(tuple(float(v) for v in settings_raw["crop"]))
    settings = ProjectSettings(**settings_raw)
    return frames, settings
