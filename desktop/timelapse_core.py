from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from PIL import Image, ImageOps, ImageStat
import pillow_heif

pillow_heif.register_heif_opener()

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".avif", ".webp", ".bmp", ".tif", ".tiff"}
JPEGISH = {".jpg", ".jpeg"}
CACHE_VERSION = "v4"
LONG_EDGE = {"720p": 1280, "1080p": 1920, "1440p": 2560, "4K": 3840}
ROTATE_FILTER = {0: None, 90: "transpose=1", 180: "transpose=1,transpose=1", 270: "transpose=2"}


@dataclass
class FrameItem:
    path: str
    rotation: int = 0
    status: str = "pending"
    message: str = ""


@dataclass
class ProjectSettings:
    speed_mode: str = "fps"
    fps: int = 24
    duration: float = 15.0
    resolution: str = "1080p"
    crf: int = 20
    hold_start: float = 0.0
    hold_end: float = 2.0
    reverse: bool = False
    crop: tuple[float, float, float, float] | None = None
    output: str = ""


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, errors="replace",
                          creationflags=CREATE_NO_WINDOW, **kwargs)


def natural_key(path: str | Path):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", Path(path).name.lower())]


def probe_size(path: str | Path) -> tuple[int, int]:
    result = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)])
    try:
        width, height = result.stdout.strip().split(",")[:2]
        return int(width), int(height)
    except (ValueError, TypeError):
        return 0, 0


def cache_key(path: str | Path, transform: str = "") -> str:
    source = Path(path)
    stamp = source.stat().st_mtime_ns if source.exists() else 0
    raw = f"{CACHE_VERSION}|{source.resolve()}|{stamp}|{transform}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_image(path: str | Path, cache: Path) -> Path:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    if source.suffix.lower() in JPEGISH:
        return source
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"normalized-{cache_key(source)}.jpg"
    if target.exists() and target.stat().st_size:
        return target
    try:
        with Image.open(source) as image:
            ImageOps.exif_transpose(image).convert("RGB").save(target, "JPEG", quality=92)
    except Exception as pillow_error:
        result = run(["ffmpeg", "-y", "-v", "error", "-i", str(source),
                      "-frames:v", "1", "-q:v", "2", str(target)])
        if result.returncode or not target.exists() or not target.stat().st_size:
            target.unlink(missing_ok=True)
            raise ValueError(result.stderr.strip() or str(pillow_error) or f"Không đọc được {source.name}")
    return target


def make_thumbnail(item: FrameItem, cache: Path, size: tuple[int, int] = (180, 112)) -> Path:
    target = cache / f"thumb-{cache_key(item.path, f'{item.rotation}|{size}')}.png"
    if target.exists() and target.stat().st_size:
        return target
    source = normalize_image(item.path, cache)
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if item.rotation:
            image = image.rotate(-item.rotation, expand=True)
        image.thumbnail(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", size, "#20242b")
        canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
        canvas.save(target)
    return target


def validate_frame(item: FrameItem, cache: Path) -> tuple[str, str]:
    try:
        source = normalize_image(item.path, cache)
        with Image.open(source) as image:
            image.thumbnail((160, 160), Image.Resampling.BILINEAR)
            gray = image.convert("L")
            stat = ImageStat.Stat(gray)
            mean, deviation = stat.mean[0], stat.stddev[0]
            if mean < 20 and deviation < 5:
                return "warning", "Ảnh gần như hoàn toàn đen"
            if mean >= 235 and deviation < 5:
                return "warning", "Ảnh gần như hoàn toàn trắng"
            if image.width < 2 or image.height < 2:
                return "error", "Kích thước ảnh không hợp lệ"
        return "ok", ""
    except Exception as exc:
        return "error", str(exc)


def scan_frames(items: list[FrameItem], cache: Path, cancel: Event | None = None,
                progress: Callable[[int, int], None] | None = None) -> None:
    cancel = cancel or Event()
    workers = min(4, os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(validate_frame, item, cache): item for item in items}
        completed = 0
        for future in as_completed(futures):
            if cancel.is_set():
                for pending in futures:
                    pending.cancel()
                return
            item = futures[future]
            item.status, item.message = future.result()
            completed += 1
            if progress:
                progress(completed, len(items))


def calculate_timing(frame_count: int, settings: ProjectSettings) -> tuple[int, int, float]:
    if frame_count < 1:
        raise ValueError("Không có frame")
    hold = max(0.0, settings.hold_start) + max(0.0, settings.hold_end)
    if settings.speed_mode == "fps":
        fps = max(1, min(60, int(settings.fps)))
        repeats = 1
    else:
        active = settings.duration - hold
        if active <= 0:
            raise ValueError("Thời lượng phải lớn hơn tổng thời gian giữ đầu và cuối")
        candidates = []
        for candidate_fps in range(1, 61):
            candidate_repeats = max(1, round(active * candidate_fps / frame_count))
            candidate_duration = frame_count * candidate_repeats / candidate_fps
            candidates.append((abs(candidate_duration - active), candidate_fps,
                               candidate_repeats, candidate_duration))
        _, fps, repeats, active_actual = min(candidates)
    actual = (active_actual if settings.speed_mode == "duration" else frame_count * repeats / fps) + hold
    return fps, repeats, actual


def normalize_crop(crop: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
    if not crop:
        return None
    x, y, width, height = crop
    x, y = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
    width, height = max(0.01, min(1.0 - x, width)), max(0.01, min(1.0 - y, height))
    return x, y, width, height


def build_video_filter(source_size: tuple[int, int], settings: ProjectSettings,
                       rotation: int = 0) -> tuple[str, int, int]:
    source_width, source_height = source_size
    filters: list[str] = []
    rotate = ROTATE_FILTER.get(rotation)
    if rotate:
        filters.append(rotate)
    if rotation in {90, 270}:
        source_width, source_height = source_height, source_width
    crop = normalize_crop(settings.crop)
    if crop:
        x, y, width, height = crop
        crop_width = max(2, int(source_width * width) // 2 * 2)
        crop_height = max(2, int(source_height * height) // 2 * 2)
        crop_x = min(source_width - crop_width, int(source_width * x) // 2 * 2)
        crop_y = min(source_height - crop_height, int(source_height * y) // 2 * 2)
        filters.append(f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y}")
        source_width, source_height = crop_width, crop_height
    edge = LONG_EDGE[settings.resolution]
    if source_width >= source_height:
        output_width = edge
        output_height = max(2, round(edge * source_height / source_width / 2) * 2)
    else:
        output_height = edge
        output_width = max(2, round(edge * source_width / source_height / 2) * 2)
    filters += [f"scale={output_width}:{output_height}:force_original_aspect_ratio=decrease",
                f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2:black",
                "format=yuv420p"]
    return ",".join(filters), output_width, output_height


def _quote_concat(path: str | Path) -> str:
    return str(Path(path).resolve()).replace("\\", "/").replace("'", "'\\''")


def build_filelist(paths: list[Path], fps: int, repeats: int, hold_start: float,
                   hold_end: float, destination: Path) -> Path:
    duration = repeats / fps
    lines: list[str] = []
    if hold_start > 0:
        lines += [f"file '{_quote_concat(paths[0])}'", f"duration {hold_start:.6f}"]
    for path in paths:
        lines += [f"file '{_quote_concat(path)}'", f"duration {duration:.6f}"]
    if hold_end > 0:
        lines += [f"file '{_quote_concat(paths[-1])}'", f"duration {hold_end:.6f}"]
    lines.append(f"file '{_quote_concat(paths[-1])}'")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def prepare_frame(item: FrameItem, cache: Path) -> Path:
    source = normalize_image(item.path, cache)
    if not item.rotation:
        return source
    target = cache / f"rotated-{cache_key(item.path, str(item.rotation))}.jpg"
    if target.exists() and target.stat().st_size:
        return target
    with Image.open(source) as image:
        image.convert("RGB").rotate(-item.rotation, expand=True).save(target, "JPEG", quality=92)
    return target


def prepare_frames(items: list[FrameItem], cache: Path, cancel: Event,
                   progress: Callable[[int, int], None] | None = None) -> list[Path]:
    result: list[Path | None] = [None] * len(items)
    workers = min(4, os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(prepare_frame, item, cache): index
                   for index, item in enumerate(items)}
        completed = 0
        for future in as_completed(futures):
            if cancel.is_set():
                for pending in futures:
                    pending.cancel()
                raise InterruptedError("Đã hủy")
            result[futures[future]] = future.result()
            completed += 1
            if progress:
                progress(completed, len(items))
    return [path for path in result if path is not None]


def verify_video(path: Path, expected_size: tuple[int, int]) -> dict:
    result = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=codec_name,width,height:format=duration",
                  "-of", "json", str(path)])
    if result.returncode:
        raise ValueError(result.stderr.strip())
    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise ValueError("Video không có video stream")
    stream = data["streams"][0]
    size = (int(stream["width"]), int(stream["height"]))
    if size != expected_size or float(data.get("format", {}).get("duration", 0)) <= 0:
        raise ValueError(f"Video đầu ra không hợp lệ: {size}")
    return {"codec": stream.get("codec_name", ""), "size": size,
            "duration": float(data["format"]["duration"])}


def render_video(items: list[FrameItem], settings: ProjectSettings, cache: Path,
                 output: Path, cancel: Event,
                 progress: Callable[[str, int, int], None] | None = None) -> dict:
    ordered = list(reversed(items)) if settings.reverse else list(items)
    prepared = prepare_frames(ordered, cache, cancel,
                              lambda done, total: progress and progress("prepare", done, total))
    fps, repeats, _ = calculate_timing(len(prepared), settings)
    source_size = probe_size(prepared[0])
    video_filter, width, height = build_video_filter(source_size, settings, 0)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".partial" + output.suffix)
    partial.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="metech-render-") as temp:
        filelist = build_filelist(prepared, fps, repeats, settings.hold_start,
                                  settings.hold_end, Path(temp) / "frames.ffconcat")
        command = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(filelist),
                   "-vf", video_filter, "-r", str(fps), "-c:v", "libx264",
                   "-crf", str(settings.crf), "-preset", "medium", "-pix_fmt", "yuv420p",
                   "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(partial)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, errors="replace", creationflags=CREATE_NO_WINDOW)
        expected_frames = max(1, round((len(prepared) * repeats / fps + settings.hold_start + settings.hold_end) * fps))
        stderr_lines: list[str] = []
        def drain_stderr():
            if process.stderr:
                for error_line in process.stderr:
                    stderr_lines.append(error_line.rstrip())
                    if len(stderr_lines) > 200:
                        del stderr_lines[:100]
        stderr_thread = __import__("threading").Thread(target=drain_stderr, daemon=True)
        stderr_thread.start()
        while process.poll() is None:
            if cancel.is_set():
                process.terminate()
                process.wait(timeout=5)
                partial.unlink(missing_ok=True)
                raise InterruptedError("Đã hủy")
            line = process.stdout.readline() if process.stdout else ""
            if line.startswith("frame=") and progress:
                progress("render", min(int(line.split("=", 1)[1]), expected_frames), expected_frames)
        stderr_thread.join(timeout=2)
        if process.returncode:
            partial.unlink(missing_ok=True)
            raise RuntimeError("\n".join(stderr_lines[-20:]))
    metadata = verify_video(partial, (width, height))
    os.replace(partial, output)
    metadata.update({"fps": fps, "frames": len(prepared), "path": str(output)})
    return metadata
