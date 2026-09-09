import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from camera_import import download_images, gallery
from project_io import load_project, save_project
from timelapse_core import (FrameItem, ProjectSettings, build_filelist, build_video_filter,
                            cache_key, calculate_timing, normalize_crop, validate_frame)


class CoreTests(unittest.TestCase):
    def test_crop_clamps(self):
        self.assertEqual(normalize_crop((-1, .2, 3, .9)), (0.0, .2, 1.0, .8))

    def test_fps_timing(self):
        fps, repeats, actual = calculate_timing(120, ProjectSettings(fps=24, hold_end=2))
        self.assertEqual((fps, repeats), (24, 1))
        self.assertAlmostEqual(actual, 7)

    def test_duration_rejects_holds(self):
        with self.assertRaises(ValueError):
            calculate_timing(10, ProjectSettings(speed_mode="duration", duration=2, hold_end=2))

    def test_filter_even_size(self):
        settings = ProjectSettings(crop=(.1, .1, .7, .7))
        value, width, height = build_video_filter((4031, 3023), settings)
        self.assertIn("crop=", value)
        self.assertEqual(width % 2, 0)
        self.assertEqual(height % 2, 0)

    def test_filelist_unicode_and_quote(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "list.txt"
            build_filelist([Path(folder) / "ảnh '1.jpg"], 25, 1, 0, 2, destination)
            text = destination.read_text(encoding="utf-8")
            self.assertIn("ảnh", text)
            self.assertIn("duration 2.000000", text)

    def test_project_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); image = root / "ảnh.jpg"; image.write_bytes(b"x")
            path = root / "job.metech-timelapse.json"
            settings = ProjectSettings(crop=(.1, .2, .5, .6), output="out.mp4")
            save_project(path, [FrameItem(str(image), rotation=90)], settings)
            items, loaded = load_project(path)
            self.assertEqual(items[0].rotation, 90)
            self.assertEqual(loaded.crop, settings.crop)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["frames"][0]["path"], "ảnh.jpg")

    def test_black_white_normal_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); cache = root / "cache"
            cases = [("black.png", (0, 0, 0), "warning"),
                     ("white.png", (255, 255, 255), "warning"),
                     ("normal.png", (100, 100, 100), "ok")]
            for name, color, expected in cases:
                path = root / name; Image.new("RGB", (40, 40), color).save(path)
                status, _ = validate_frame(FrameItem(str(path)), cache)
                self.assertEqual(status, expected)

    def test_cache_changes_with_transform(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "x.jpg"; path.write_bytes(b"x")
            self.assertNotEqual(cache_key(path, "0"), cache_key(path, "90"))

    def test_camera_import_validates_and_skips_existing_file(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        image = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(image, "JPEG")
        jpeg = image.getvalue()

        class Camera(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                body = {"/api/status": b'{"sd_ready":true}',
                        "/api/gallery": b'{"images":["C000002.JPG","C000001.JPG"]}',
                        "/image/C000001.JPG": jpeg,
                        "/image/C000002.JPG": jpeg}.get(self.path)
                if body is None:
                    self.send_error(404); return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg" if self.path.startswith("/image/") else "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Camera)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder); (root / "C000001.JPG").write_bytes(jpeg)
                result = download_images(f"http://127.0.0.1:{server.server_port}", root)
                self.assertEqual([path.name for path in result.downloaded], ["C000002.JPG"])
                self.assertEqual([path.name for path in result.skipped], ["C000001.JPG"])
                self.assertFalse(list(root.glob("*.part")))
        finally:
            server.shutdown(); server.server_close()

    def test_camera_gallery_rejects_unsafe_filename(self):
        with patch("camera_import._json", side_effect=[{"sd_ready": True}, {"images": ["../../x.JPG"]}]):
            with self.assertRaisesRegex(RuntimeError, "không hợp lệ"):
                gallery("http://camera")


if __name__ == "__main__":
    unittest.main()
