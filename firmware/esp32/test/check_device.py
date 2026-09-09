#!/usr/bin/env python3
"""Verify approved MetechCamA1 firmware APIs without unsafe device operations."""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SAFE_IMAGE = re.compile(r"^C\d{6}\.JPG$")
JPEG_SOF = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))


class CheckFailure(RuntimeError):
    pass


class DeviceCheck:
    def __init__(self, base_url: str, output: Path, timeout: float) -> None:
        self.base_url, self.output, self.timeout = base_url.rstrip("/"), output, timeout
        self.failures: list[str] = []
        self.output.parent.mkdir(parents=True, exist_ok=True)

    def log(self, check: str, ok: bool, **fields: object) -> None:
        with self.output.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": time.time(), "check": check, "ok": ok, **fields}, sort_keys=True) + "\n")

    def request(self, method: str, path: str, form: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        data = urlencode(form).encode("ascii") if form is not None else None
        headers = {"Content-Type": "application/x-www-form-urlencoded"} if data else {}
        started = time.monotonic()
        try:
            with urlopen(Request(self.base_url + path, data=data, headers=headers, method=method), timeout=self.timeout) as response:
                status, response_headers, body = response.status, dict(response.headers.items()), response.read()
        except HTTPError as error:
            status, response_headers, body = error.code, dict(error.headers.items()), error.read()
        except (URLError, TimeoutError, OSError) as error:
            raise CheckFailure(f"{method} {path}: {error}") from error
        self.log("http", status < 400, method=method, path=path, status=status, bytes=len(body), elapsed_ms=round((time.monotonic() - started) * 1000, 1))
        return status, response_headers, body

    def expect(self, method: str, path: str, status: int, form: dict[str, str] | None = None) -> bytes:
        actual, _, body = self.request(method, path, form)
        if actual != status:
            raise CheckFailure(f"{method} {path}: expected HTTP {status}, got {actual}: {body[:160]!r}")
        return body

    def json_get(self, path: str) -> dict[str, object]:
        return self.json_body(self.expect("GET", path, 200), f"GET {path}")

    @staticmethod
    def json_body(body: bytes, label: str) -> dict[str, object]:
        try:
            value = json.loads(body)
        except json.JSONDecodeError as error:
            raise CheckFailure(f"{label}: invalid JSON: {error}") from error
        if not isinstance(value, dict):
            raise CheckFailure(f"{label}: expected JSON object")
        return value

    def post_json(self, path: str, form: dict[str, str]) -> dict[str, object]:
        return self.json_body(self.expect("POST", path, 200, form), f"POST {path}")

    @staticmethod
    def require(value: dict[str, object], fields: dict[str, type], label: str) -> None:
        for name, expected in fields.items():
            if not isinstance(value.get(name), expected):
                raise CheckFailure(f"{label}: {name!r} must be {expected.__name__}")

    @staticmethod
    def jpeg_dimensions(data: bytes) -> tuple[int, int]:
        if len(data) < 4 or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
            raise CheckFailure("JPEG requires SOI and EOI markers")
        index = 2
        while index + 4 <= len(data):
            if data[index] != 0xFF:
                raise CheckFailure("invalid JPEG marker alignment")
            while index < len(data) and data[index] == 0xFF:
                index += 1
            marker, index = data[index], index + 1
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                continue
            if index + 2 > len(data):
                break
            length = struct.unpack(">H", data[index:index + 2])[0]
            if length < 2 or index + length > len(data):
                raise CheckFailure("invalid JPEG segment length")
            if marker in JPEG_SOF:
                if length < 8:
                    raise CheckFailure("short JPEG frame header")
                height, width = struct.unpack(">HH", data[index + 3:index + 7])
                if not width or not height:
                    raise CheckFailure("zero JPEG dimensions")
                return width, height
            index += length
        raise CheckFailure("JPEG has no supported SOF marker")

    def readonly(self) -> None:
        status = self.json_get("/api/status")
        self.require(status, {"width": int, "height": int, "captures": int, "wifi": str, "ip": str, "ssid": str, "ap": dict, "lan": dict, "sd": str, "sd_ready": bool, "sd_retry_count": int, "sd_last_retry_s": int, "saved": int, "images": int, "sd_free_bytes": int, "sd_total_bytes": int, "estimated_images_left": int, "preview": dict}, "/api/status")
        self.require(status["ap"], {"ssid": str, "ip": str}, "/api/status.ap")
        self.require(status["lan"], {"state": str, "ssid": str, "ip": str}, "/api/status.lan")
        self.require(status["preview"], {"mode": str, "delay_ms": int, "fps_x10": int}, "/api/status.preview")
        if status["sd_free_bytes"] > status["sd_total_bytes"]:
            raise CheckFailure("/api/status: storage free bytes exceed total bytes")
        if status["sd_retry_count"] < 1 or status["sd_last_retry_s"] > status["uptime_s"]:
            raise CheckFailure("/api/status: invalid SD retry telemetry")
        self.require(self.json_get("/api/timelapse"), {"active": bool, "interval_s": int, "limit": int, "taken": int, "next_s": int, "state": str, "error": str}, "/api/timelapse")
        events = self.json_get("/api/events")
        if not isinstance(events.get("events"), list):
            raise CheckFailure("/api/events: events must be a list")
        for event in events["events"]:
            if not isinstance(event, dict):
                raise CheckFailure("/api/events: event must be an object")
            self.require(event, {"at_s": int, "text": str}, "/api/events item")
        for path in ("/snapshot.jpg", "/still.jpg"):
            last_error = ""
            for attempt in range(3):
                code, headers, image = self.request("GET", path)
                if code == 200 and headers.get("Content-Type", "").lower().startswith("image/jpeg"):
                    width, height = self.jpeg_dimensions(image)
                    self.log("jpeg", True, path=path, bytes=len(image), width=width, height=height, attempt=attempt + 1)
                    break
                last_error = f"HTTP {code} {headers.get('Content-Type', '')}"
                time.sleep(1)
            else:
                raise CheckFailure(f"GET {path}: no image/jpeg after 3 attempts ({last_error})")

    def gallery(self) -> tuple[int, set[str]]:
        gallery = self.json_get("/api/gallery")
        self.require(gallery, {"images": list, "total": int}, "/api/gallery")
        names = set(gallery["images"])
        if len(names) != len(gallery["images"]) or any(not isinstance(name, str) or not SAFE_IMAGE.fullmatch(name) for name in names):
            raise CheckFailure("/api/gallery: image names must be unique C######.JPG names")
        return gallery["total"], names

    def stop(self) -> None:
        try:
            self.expect("POST", "/api/timelapse/stop", 200, {})
            self.log("timelapse_stop", True)
        except CheckFailure as error:
            self.failures.append(f"mandatory stop failed: {error}")
            self.log("timelapse_stop", False, error=str(error))

    def capture(self, soak_seconds: int | None) -> None:
        preview = self.json_get("/api/preview")
        self.require(preview, {"mode": str}, "/api/preview")
        original_mode = preview["mode"]
        if original_mode not in {"eco", "normal", "smooth", "fast"}:
            raise CheckFailure(f"/api/preview: unknown current mode {original_mode!r}")
        if self.json_get("/api/timelapse").get("active"):
            raise CheckFailure("refusing capture test: device already has active timelapse")
        before_total, before_names = self.gallery()
        started = False
        try:
            self.expect("POST", "/api/preview", 400, {"mode": "invalid"})
            for payload in ({"interval": "6", "limit": "3"}, {"interval": "5", "limit": "-1"}, {"interval": "5", "limit": "4294967296"}, {"interval": "5", "limit": "three"}, {"interval": "5", "limit": "3", "unknown": "x"}):
                self.expect("POST", "/api/timelapse/start", 400, payload)
            if soak_seconds is None:
                interval, limit, timeout = 5, 3, 50.0
            else:
                interval, limit, timeout = 60, min(61, max(1, (soak_seconds + 59) // 60)), soak_seconds + 75.0
            response = self.post_json("/api/timelapse/start", {"interval": str(interval), "limit": str(limit)})
            started = True
            self.require(response, {"active": bool, "interval_s": int, "limit": int, "taken": int, "state": str}, "timelapse start")
            if response["interval_s"] != interval or response["limit"] != limit:
                raise CheckFailure("timelapse start did not retain requested bounds")
            self.expect("POST", "/api/timelapse/start", 409, {"interval": str(interval), "limit": str(limit)})
            deadline, last = time.monotonic() + timeout, {}
            while time.monotonic() < deadline:
                last = self.json_get("/api/timelapse")
                self.log("timelapse_poll", True, active=last.get("active"), taken=last.get("taken"), state=last.get("state"), next_s=last.get("next_s"))
                if last.get("state") == "error":
                    raise CheckFailure(f"timelapse error: {last.get('error')}")
                if not last.get("active") and last.get("state") == "complete" and last.get("taken") == limit:
                    break
                time.sleep(1)
            else:
                raise CheckFailure(f"timelapse did not complete in {timeout:.0f}s: {last}")
        finally:
            if started:
                self.stop()
            try:
                if self.post_json("/api/preview", {"mode": original_mode}).get("mode") != original_mode:
                    raise CheckFailure("preview restore returned wrong mode")
                self.log("preview_restore", True, mode=original_mode)
            except CheckFailure as error:
                self.failures.append(f"preview restore failed: {error}")
                self.log("preview_restore", False, error=str(error))
        if soak_seconds is None:
            after_total, after_names = self.gallery()
            if after_total != before_total + 3 or len(after_names - before_names) < 3:
                raise CheckFailure(f"capture must add exactly three images; total {before_total} to {after_total}")

    def standby(self) -> None:
        if self.json_get("/api/timelapse").get("active"):
            raise CheckFailure("refusing standby test: device has active timelapse")
        status = self.json_get("/api/status")
        if status.get("camera_state") != "active":
            raise CheckFailure(f"standby test requires active camera, got {status.get('camera_state')!r}")
        sleeping = False
        try:
            self.expect("POST", "/api/camera/standby", 200, {})
            sleeping = True
            status = self.json_get("/api/status")
            if status.get("camera_state") != "standby" or status.get("wifi") != "connected":
                raise CheckFailure("camera standby did not retain Wi-Fi or report standby")
            self.expect("GET", "/snapshot.jpg", 500)
            self.expect("POST", "/api/timelapse/start", 409, {"interval": "5", "limit": "1"})
            self.log("camera_standby", True)
        finally:
            if sleeping:
                self.expect("POST", "/api/camera/wake", 200, {})
                time.sleep(2)
                status = self.json_get("/api/status")
                if status.get("camera_state") != "active":
                    raise CheckFailure("camera did not return active after wake")
                code, headers, image = self.request("GET", "/snapshot.jpg")
                if code != 200 or not headers.get("Content-Type", "").lower().startswith("image/jpeg"):
                    raise CheckFailure("camera JPEG did not return after wake")
                self.jpeg_dimensions(image)
                self.log("camera_wake", True)

    def run(self, capture: bool, soak_seconds: int | None, standby: bool) -> int:
        try:
            self.readonly()
            if standby:
                self.standby()
            if capture:
                self.capture(soak_seconds)
        except CheckFailure as error:
            self.failures.append(str(error))
            self.log("failure", False, error=str(error))
        for failure in self.failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        if not self.failures:
            print("PASS: device checks completed")
        return int(bool(self.failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="Device base URL, e.g. http://192.168.4.1")
    parser.add_argument("--capture", action="store_true", help="Permit bounded timelapse verification")
    parser.add_argument("--standby", action="store_true", help="Permit camera standby/wake lifecycle verification")
    parser.add_argument("--soak-seconds", type=int, metavar="SECONDS", help="Explicit 1..3600 endurance run; requires --capture")
    parser.add_argument("--output", type=Path, required=True, help="JSONL metrics output path")
    parser.add_argument("--timeout", type=float, default=10, help="Per-request timeout seconds")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.soak_seconds is not None:
        if not args.capture:
            parser.error("--soak-seconds requires --capture")
        if not 1 <= args.soak_seconds <= 3600:
            parser.error("--soak-seconds must be between 1 and 3600")
    return DeviceCheck(args.base_url, args.output, args.timeout).run(args.capture, args.soak_seconds, args.standby)


if __name__ == "__main__":
    raise SystemExit(main())
