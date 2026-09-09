"""Metech Timelapse v1.1 — trình biên tập timelapse ảnh in 3D cho Windows."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageTk

from project_io import load_project, save_project
from camera_import import DEFAULT_CAMERA_URL, download_images
from timelapse_core import (EXTS, FrameItem, ProjectSettings, calculate_timing,
                            make_thumbnail, natural_key, normalize_crop,
                            render_video, scan_frames)

FILETYPES = [("Ảnh", "*.jpg *.jpeg *.png *.heic *.heif *.avif *.webp *.bmp *.tif *.tiff"),
             ("Tất cả", "*.*")]
CACHE = Path(tempfile.gettempdir()) / "metech-timelapse-v3"


def selftest() -> None:
    assert sorted(["IMG_10.jpg", "IMG_2.jpg"], key=natural_key) == ["IMG_2.jpg", "IMG_10.jpg"]
    assert normalize_crop((-1, .2, 2, .9)) == (0.0, .2, 1.0, .8)
    fps, repeats, actual = calculate_timing(120, ProjectSettings(speed_mode="fps", fps=24))
    assert (fps, repeats) == (24, 1) and actual == 7.0
    print("OK")


def gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App:
        ITEM_HEIGHT = 132

        def __init__(self, root: tk.Tk):
            self.root = root
            self.items: list[FrameItem] = []
            self.selected: set[int] = set()
            self.anchor: int | None = None
            self.undo_state: list[FrameItem] | None = None
            self.project_path: Path | None = None
            self.dirty = False
            self.cancel_event = threading.Event()
            self.worker: threading.Thread | None = None
            self.thumb_images: dict[int, ImageTk.PhotoImage] = {}
            self.thumb_pool = ThreadPoolExecutor(max_workers=2)
            self.thumb_pending: set[int] = set()
            self.preview_image: ImageTk.PhotoImage | None = None
            self.preview_box: tuple[int, int, int, int] | None = None
            self.crop_start: tuple[int, int] | None = None
            self.crop_rect: int | None = None
            self.cache = CACHE
            self.cache.mkdir(parents=True, exist_ok=True)
            self._build()
            self.root.protocol("WM_DELETE_WINDOW", self.close)
            self._title()

        def _build(self):
            self.root.geometry("1280x780")
            self.root.minsize(980, 640)
            toolbar = ttk.Frame(self.root, padding=(8, 7))
            toolbar.pack(fill="x")
            for text, command in (("Project mới", self.new_project), ("Mở", self.open_project),
                                  ("Lưu", self.save), ("Lưu thành", self.save_as),
                                  ("Tải từ camera", self.import_camera), ("Thêm thư mục", self.add_folder),
                                  ("Thêm ảnh", self.add_files)):
                ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=2)
            ttk.Button(toolbar, text="Quét lỗi", command=self.start_scan).pack(side="right", padx=2)
            ttk.Button(toolbar, text="Xóa cache", command=self.clear_cache).pack(side="right", padx=2)

            paned = ttk.Panedwindow(self.root, orient="horizontal")
            paned.pack(fill="both", expand=True, padx=8)
            left = ttk.Frame(paned, width=330)
            right = ttk.Frame(paned)
            paned.add(left, weight=1)
            paned.add(right, weight=3)

            ttk.Label(left, text="Timeline ảnh").pack(anchor="w")
            timeline_box = ttk.Frame(left)
            timeline_box.pack(fill="both", expand=True, pady=(4, 4))
            self.timeline = tk.Canvas(timeline_box, bg="#20242b", highlightthickness=0,
                                      width=330, takefocus=True)
            scrollbar = ttk.Scrollbar(timeline_box, orient="vertical", command=self.timeline.yview)
            self.timeline.configure(yscrollcommand=scrollbar.set)
            self.timeline.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            self.timeline.bind("<Button-1>", self.timeline_click)
            self.timeline.bind("<MouseWheel>", self.timeline_wheel)
            self.timeline.bind("<Configure>", lambda event: self.draw_timeline())
            self.timeline.bind("<Delete>", lambda event: self.remove_selected())
            self.timeline.bind("<Control-a>", self.select_all)
            self.timeline.bind("<Control-z>", lambda event: self.undo())

            row = ttk.Frame(left)
            row.pack(fill="x")
            for text, command in (("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1)),
                                  ("Đầu", lambda: self.move_edge(True)), ("Cuối", lambda: self.move_edge(False)),
                                  ("Xóa", self.remove_selected), ("Undo", self.undo)):
                ttk.Button(row, text=text, width=6, command=command).pack(side="left", padx=1)
            row2 = ttk.Frame(left)
            row2.pack(fill="x", pady=(4, 0))
            ttk.Button(row2, text="Tên A→Z", command=self.sort_items).pack(side="left", padx=1)
            ttk.Button(row2, text="Xoay nhóm 90°", command=self.rotate_selected).pack(side="left", padx=1)
            self.filter_var = tk.StringVar(value="Tất cả")
            filter_box = ttk.Combobox(row2, textvariable=self.filter_var,
                                      values=("Tất cả", "Lỗi", "Cảnh báo"), width=10, state="readonly")
            filter_box.pack(side="right")
            filter_box.bind("<<ComboboxSelected>>", lambda event: self.draw_timeline())

            self.preview = tk.Canvas(right, bg="#111317", highlightthickness=0, cursor="crosshair")
            self.preview.pack(fill="both", expand=True)
            self.preview.bind("<Configure>", lambda event: self.show_preview())
            self.preview.bind("<ButtonPress-1>", self.crop_begin)
            self.preview.bind("<B1-Motion>", self.crop_drag)
            self.preview.bind("<ButtonRelease-1>", self.crop_end)

            info_row = ttk.Frame(right)
            info_row.pack(fill="x", pady=(5, 3))
            self.info = ttk.Label(info_row, text="Chưa có ảnh")
            self.info.pack(side="left")
            ttk.Button(info_row, text="Đặt lại crop", command=self.reset_crop).pack(side="right")
            ttk.Label(info_row, text="Kéo trên preview để crop chung").pack(side="right", padx=8)

            settings = ttk.LabelFrame(right, text="Thiết lập video", padding=8)
            settings.pack(fill="x")
            self.mode = tk.StringVar(value="fps")
            self.fps = tk.IntVar(value=24)
            self.duration = tk.DoubleVar(value=15.0)
            self.resolution = tk.StringVar(value="1080p")
            self.crf = tk.IntVar(value=20)
            self.hold_start = tk.DoubleVar(value=0.0)
            self.hold_end = tk.DoubleVar(value=2.0)
            self.reverse = tk.BooleanVar(value=False)
            ttk.Radiobutton(settings, text="FPS", variable=self.mode, value="fps", command=self.update_stats).grid(row=0, column=0, sticky="w")
            ttk.Spinbox(settings, from_=1, to=60, textvariable=self.fps, width=7, command=self.update_stats).grid(row=0, column=1)
            ttk.Radiobutton(settings, text="Thời lượng (giây)", variable=self.mode, value="duration", command=self.update_stats).grid(row=0, column=2, padx=(14, 0))
            ttk.Spinbox(settings, from_=1, to=3600, increment=1, textvariable=self.duration, width=8, command=self.update_stats).grid(row=0, column=3)
            ttk.Label(settings, text="Độ phân giải").grid(row=0, column=4, padx=(14, 0))
            ttk.Combobox(settings, values=("720p", "1080p", "1440p", "4K"), textvariable=self.resolution, width=8, state="readonly").grid(row=0, column=5)
            ttk.Label(settings, text="CRF").grid(row=1, column=0, sticky="w", pady=(6, 0))
            ttk.Spinbox(settings, from_=14, to=32, textvariable=self.crf, width=7).grid(row=1, column=1, pady=(6, 0))
            ttk.Label(settings, text="Giữ đầu").grid(row=1, column=2, pady=(6, 0))
            ttk.Spinbox(settings, from_=0, to=30, increment=.5, textvariable=self.hold_start, width=8).grid(row=1, column=3, pady=(6, 0))
            ttk.Label(settings, text="Giữ cuối").grid(row=1, column=4, pady=(6, 0))
            ttk.Spinbox(settings, from_=0, to=30, increment=.5, textvariable=self.hold_end, width=8).grid(row=1, column=5, pady=(6, 0))
            ttk.Checkbutton(settings, text="Video ngược", variable=self.reverse).grid(row=1, column=6, padx=10, pady=(6, 0))

            output_row = ttk.Frame(right)
            output_row.pack(fill="x", pady=(7, 3))
            self.output = tk.StringVar(value=str(Path.home() / "Videos" / "timelapse.mp4"))
            ttk.Entry(output_row, textvariable=self.output).pack(side="left", fill="x", expand=True)
            ttk.Button(output_row, text="Lưu ở…", command=self.choose_output).pack(side="left", padx=4)

            action = ttk.Frame(right)
            action.pack(fill="x")
            self.render_button = ttk.Button(action, text="Render", command=self.start_render)
            self.render_button.pack(side="left")
            self.cancel_button = ttk.Button(action, text="Hủy", command=self.cancel, state="disabled")
            self.cancel_button.pack(side="left", padx=4)
            self.progress = ttk.Progressbar(action, maximum=100)
            self.progress.pack(side="left", fill="x", expand=True, padx=6)
            self.status = ttk.Label(action, text="Sẵn sàng")
            self.status.pack(side="right")
            self.log = tk.Text(right, height=5, state="disabled", wrap="word")
            self.log.pack(fill="x", pady=(4, 8))

        def _title(self):
            name = self.project_path.name if self.project_path else "Chưa lưu"
            self.root.title(f"{'*' if self.dirty else ''}Metech Timelapse v1.1 — {name}")

        def mark_dirty(self):
            self.dirty = True
            self._title()

        def settings(self) -> ProjectSettings:
            crop = getattr(self, "crop", None)
            return ProjectSettings(self.mode.get(), int(self.fps.get()), float(self.duration.get()),
                                   self.resolution.get(), int(self.crf.get()), float(self.hold_start.get()),
                                   float(self.hold_end.get()), bool(self.reverse.get()), crop, self.output.get())

        def apply_settings(self, settings: ProjectSettings):
            self.mode.set(settings.speed_mode); self.fps.set(settings.fps); self.duration.set(settings.duration)
            self.resolution.set(settings.resolution); self.crf.set(settings.crf)
            self.hold_start.set(settings.hold_start); self.hold_end.set(settings.hold_end)
            self.reverse.set(settings.reverse); self.output.set(settings.output or self.output.get())
            self.crop = settings.crop

        def visible_indices(self) -> list[int]:
            mode = self.filter_var.get()
            return [i for i, item in enumerate(self.items)
                    if mode == "Tất cả" or (mode == "Lỗi" and item.status == "error")
                    or (mode == "Cảnh báo" and item.status == "warning")]

        def draw_timeline(self):
            self.timeline.delete("all")
            indices = self.visible_indices()
            width = max(280, self.timeline.winfo_width())
            self.timeline.configure(scrollregion=(0, 0, width, len(indices) * self.ITEM_HEIGHT))
            if not indices:
                self.timeline.create_text(width // 2, 30, text="Chưa có ảnh", fill="#d7dce2")
                return
            top = max(0, int(self.timeline.canvasy(0) // self.ITEM_HEIGHT) - 1)
            bottom = min(len(indices), top + max(3, self.timeline.winfo_height() // self.ITEM_HEIGHT + 3))
            for row in range(top, bottom):
                index = indices[row]
                item = self.items[index]
                y = row * self.ITEM_HEIGHT
                selected = index in self.selected
                self.timeline.create_rectangle(3, y + 3, width - 4, y + self.ITEM_HEIGHT - 3,
                                               fill="#355f8a" if selected else "#2b3038", outline="#6ba6df" if selected else "#454c57")
                self.timeline.create_text(9, y + 10, anchor="nw", text=f"{index + 1:04d}", fill="#cbd4de")
                if index in self.thumb_images:
                    self.timeline.create_image(50, y + 10, image=self.thumb_images[index], anchor="nw")
                else:
                    self.timeline.create_rectangle(50, y + 10, 230, y + 122, fill="#242a32", outline="#3d4652")
                    self.timeline.create_text(140, y + 66, text="Đang tải…", fill="#aeb7c2")
                    self.load_thumbnail(index)
                name = Path(item.path).name
                self.timeline.create_text(238, y + 15, anchor="nw", width=max(40, width - 248), text=name, fill="white")
                badge = {"error": "LỖI", "warning": "CẢNH BÁO", "ok": "OK", "pending": "CHƯA QUÉT"}[item.status]
                color = {"error": "#ff7474", "warning": "#ffd166", "ok": "#7bd88f", "pending": "#aeb7c2"}[item.status]
                self.timeline.create_text(238, y + 83, anchor="nw", text=f"{badge} · xoay {item.rotation}°", fill=color)
            self.update_stats()

        def load_thumbnail(self, index):
            if index in self.thumb_pending or not 0 <= index < len(self.items):
                return
            self.thumb_pending.add(index)
            item = replace(self.items[index])
            identity = (item.path, item.rotation)
            future = self.thumb_pool.submit(make_thumbnail, item, self.cache)
            future.add_done_callback(lambda done, i=index, expected=identity:
                                     self.root.after(0, self.thumbnail_done, i, expected, done))

        def thumbnail_done(self, index, expected, future):
            self.thumb_pending.discard(index)
            if (not 0 <= index < len(self.items)
                    or (self.items[index].path, self.items[index].rotation) != expected):
                return
            try:
                with Image.open(future.result()) as image:
                    self.thumb_images[index] = ImageTk.PhotoImage(image.copy())
            except Exception as exc:
                self.items[index].status, self.items[index].message = "error", str(exc)
            self.draw_timeline()

        def timeline_wheel(self, event):
            self.timeline.yview_scroll(-1 if event.delta > 0 else 1, "units")
            self.root.after_idle(self.draw_timeline)

        def timeline_click(self, event):
            self.timeline.focus_set()
            indices = self.visible_indices()
            row = int(self.timeline.canvasy(event.y) // self.ITEM_HEIGHT)
            if not 0 <= row < len(indices): return
            index = indices[row]
            ctrl = bool(event.state & 0x0004); shift = bool(event.state & 0x0001)
            if shift and self.anchor is not None:
                low, high = sorted((self.anchor, index)); self.selected = set(range(low, high + 1))
            elif ctrl:
                self.selected.symmetric_difference_update({index}); self.anchor = index
            else:
                self.selected = {index}; self.anchor = index
            self.draw_timeline(); self.show_preview()

        def select_all(self, event=None):
            self.selected = set(range(len(self.items))); self.draw_timeline(); return "break"

        def show_preview(self):
            self.preview.delete("all")
            if not self.selected: return
            index = min(self.selected); item = self.items[index]
            try:
                source = make_thumbnail(item, self.cache, (1100, 650))
                image = Image.open(source).convert("RGB")
                available = (max(1, self.preview.winfo_width() - 20), max(1, self.preview.winfo_height() - 20))
                image.thumbnail(available, Image.Resampling.LANCZOS)
                self.preview_image = ImageTk.PhotoImage(image)
                x = (self.preview.winfo_width() - image.width) // 2
                y = (self.preview.winfo_height() - image.height) // 2
                self.preview_box = (x, y, image.width, image.height)
                self.preview.create_image(x, y, image=self.preview_image, anchor="nw")
                if getattr(self, "crop", None):
                    cx, cy, cw, ch = self.crop
                    self.crop_rect = self.preview.create_rectangle(x + cx * image.width, y + cy * image.height,
                                                                    x + (cx + cw) * image.width, y + (cy + ch) * image.height,
                                                                    outline="#31d6c4", width=2)
                self.info.config(text=f"[{index + 1}/{len(self.items)}] {Path(item.path).name} · {item.message or item.status}")
            except Exception as exc:
                self.info.config(text=f"Lỗi preview: {exc}")

        def crop_begin(self, event):
            if self.preview_box and self.selected:
                self.crop_start = (event.x, event.y)

        def crop_drag(self, event):
            if not self.crop_start: return
            if self.crop_rect: self.preview.delete(self.crop_rect)
            self.crop_rect = self.preview.create_rectangle(*self.crop_start, event.x, event.y, outline="#31d6c4", width=2)

        def crop_end(self, event):
            if not self.crop_start or not self.preview_box: return
            x, y, width, height = self.preview_box
            x1, y1 = self.crop_start; x2, y2 = event.x, event.y
            left, right = sorted((max(x, min(x + width, x1)), max(x, min(x + width, x2))))
            top, bottom = sorted((max(y, min(y + height, y1)), max(y, min(y + height, y2))))
            if right - left > 10 and bottom - top > 10:
                self.crop = normalize_crop(((left - x) / width, (top - y) / height,
                                            (right - left) / width, (bottom - top) / height))
                self.mark_dirty()
            self.crop_start = None; self.show_preview()

        def reset_crop(self):
            self.crop = None; self.mark_dirty(); self.show_preview()

        def snapshot(self):
            self.undo_state = [replace(item) for item in self.items]

        def undo(self):
            if self.undo_state is None: return
            current = self.items; self.items = self.undo_state; self.undo_state = current
            self.selected.clear(); self.thumb_images.clear(); self.mark_dirty(); self.draw_timeline(); self.show_preview()

        def add_paths(self, paths):
            existing = {item.path for item in self.items}
            added = [FrameItem(str(Path(path).resolve())) for path in paths if str(Path(path).resolve()) not in existing and Path(path).suffix.lower() in EXTS]
            if not added: return
            self.snapshot(); self.items.extend(added); self.items.sort(key=lambda item: natural_key(item.path))
            self.selected = {0}; self.thumb_images.clear(); self.mark_dirty(); self.draw_timeline(); self.show_preview(); self.start_scan()

        def import_camera(self):
            dialog = tk.Toplevel(self.root)
            dialog.title("Tải ảnh từ Metech Camera")
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.resizable(False, False)
            body = ttk.Frame(dialog, padding=12)
            body.pack(fill="both", expand=True)
            camera = tk.StringVar(value=DEFAULT_CAMERA_URL)
            folder = tk.StringVar(value=str(Path.home() / "Pictures" / "Metech Camera"))
            add_after = tk.BooleanVar(value=True)
            ttk.Label(body, text="Địa chỉ camera").grid(row=0, column=0, sticky="w")
            ttk.Entry(body, textvariable=camera, width=42).grid(row=0, column=1, padx=(8, 0), sticky="ew")
            ttk.Label(body, text="Thư mục trên Windows").grid(row=1, column=0, sticky="w", pady=(8, 0))
            ttk.Entry(body, textvariable=folder, width=42).grid(row=1, column=1, padx=(8, 0), pady=(8, 0), sticky="ew")
            def choose_folder():
                chosen = filedialog.askdirectory(title="Chọn thư mục nhận ảnh", initialdir=folder.get())
                if chosen:
                    folder.set(chosen)
            ttk.Button(body, text="Chọn…", command=choose_folder).grid(row=1, column=2, padx=(6, 0), pady=(8, 0))
            ttk.Checkbutton(body, text="Tự thêm ảnh tải được vào timeline", variable=add_after).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
            note = ttk.Label(body, text="Chỉ sao chép ảnh về Windows. Không xóa ảnh trên microSD.", wraplength=450)
            note.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
            progress = ttk.Label(body, text="Sẵn sàng")
            progress.grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))
            buttons = ttk.Frame(body)
            buttons.grid(row=5, column=0, columnspan=3, sticky="e", pady=(12, 0))
            start = ttk.Button(buttons, text="Tải ảnh")
            start.pack(side="left")
            ttk.Button(buttons, text="Đóng", command=dialog.destroy).pack(side="left", padx=(6, 0))

            def begin():
                start.config(state="disabled")
                def update(name, done, total):
                    self.root.after(0, lambda: progress.config(text=f"Đang tải {done}/{total}: {name}"))
                def job():
                    try:
                        result = download_images(camera.get(), Path(folder.get()), update)
                        self.root.after(0, lambda: finished(result, None))
                    except Exception as exc:
                        self.root.after(0, lambda: finished(None, exc))
                threading.Thread(target=job, daemon=True).start()

            def finished(result, error):
                start.config(state="normal")
                if error:
                    progress.config(text=f"Lỗi: {error}")
                    return
                if add_after.get() and result.downloaded:
                    self.add_paths(result.downloaded)
                summary = f"Đã tải {len(result.downloaded)} ảnh; đã có {len(result.skipped)} ảnh."
                if result.failures:
                    summary += f" Lỗi {len(result.failures)} ảnh."
                    self.say("Tải camera: " + " | ".join(result.failures))
                progress.config(text=summary)
                self.say("Tải camera: " + summary)
                messagebox.showinfo("Tải từ camera", summary)

            start.config(command=begin)

        def add_folder(self):
            folder = filedialog.askdirectory(title="Chọn thư mục ảnh")
            if folder: self.add_paths(path for path in Path(folder).iterdir() if path.suffix.lower() in EXTS)

        def add_files(self):
            paths = filedialog.askopenfilenames(title="Chọn ảnh", filetypes=FILETYPES)
            if paths: self.add_paths(paths)

        def remove_selected(self):
            if not self.selected: return
            self.snapshot(); self.items = [item for i, item in enumerate(self.items) if i not in self.selected]
            self.selected.clear(); self.thumb_images.clear(); self.mark_dirty(); self.draw_timeline(); self.show_preview()

        def move(self, delta):
            if not self.selected: return
            self.snapshot(); order = sorted(self.selected, reverse=delta > 0); moved = set()
            for index in order:
                target = index + delta
                if 0 <= target < len(self.items) and target not in self.selected:
                    self.items[index], self.items[target] = self.items[target], self.items[index]; moved.add(target)
                else: moved.add(index)
            self.selected = moved; self.thumb_images.clear(); self.mark_dirty(); self.draw_timeline()

        def move_edge(self, first):
            if not self.selected: return
            self.snapshot(); chosen = [item for i, item in enumerate(self.items) if i in self.selected]
            rest = [item for i, item in enumerate(self.items) if i not in self.selected]
            self.items = chosen + rest if first else rest + chosen
            start = 0 if first else len(rest); self.selected = set(range(start, start + len(chosen)))
            self.thumb_images.clear(); self.mark_dirty(); self.draw_timeline()

        def rotate_selected(self):
            for index in self.selected: self.items[index].rotation = (self.items[index].rotation + 90) % 360
            self.thumb_images.clear(); self.mark_dirty(); self.draw_timeline(); self.show_preview()

        def sort_items(self):
            self.snapshot(); self.items.sort(key=lambda item: natural_key(item.path)); self.selected.clear(); self.thumb_images.clear(); self.mark_dirty(); self.draw_timeline()

        def busy(self, value, text=""):
            self.render_button.config(state="disabled" if value else "normal")
            self.cancel_button.config(state="normal" if value else "disabled")
            self.status.config(text=text or ("Đang xử lý" if value else "Sẵn sàng"))

        def start_scan(self):
            if not self.items or (self.worker and self.worker.is_alive()): return
            self.cancel_event.clear(); self.busy(True, "Đang quét ảnh")
            def progress(done, total): self.root.after(0, self.set_progress, "Quét", done, total)
            def job():
                scan_frames(self.items, self.cache, self.cancel_event, progress)
                self.root.after(0, self.scan_done)
            self.worker = threading.Thread(target=job, daemon=True); self.worker.start()

        def scan_done(self):
            self.busy(False); self.draw_timeline()

        def set_progress(self, phase, done, total):
            self.progress["value"] = done / max(1, total) * 100; self.status.config(text=f"{phase}: {done}/{total}")

        def update_stats(self):
            errors = sum(item.status == "error" for item in self.items); warnings = sum(item.status == "warning" for item in self.items)
            try: duration = calculate_timing(len(self.items), self.settings())[2] if self.items else 0
            except Exception: duration = 0
            self.status.config(text=f"{len(self.items)} ảnh · {errors} lỗi · {warnings} cảnh báo · ~{duration:.1f}s")

        def choose_output(self):
            path = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4", "*.mp4")])
            if path: self.output.set(path); self.mark_dirty()

        def start_render(self):
            if len(self.items) < 2: messagebox.showwarning("Thiếu ảnh", "Cần ít nhất 2 ảnh."); return
            errors = [item for item in self.items if item.status == "error"]
            if errors: messagebox.showerror("Có ảnh lỗi", "Hãy xử lý các ảnh có badge LỖI trước khi render."); return
            warnings = sum(item.status == "warning" for item in self.items)
            if warnings and not messagebox.askyesno("Còn cảnh báo", f"Có {warnings} ảnh cảnh báo. Vẫn render?"): return
            settings = self.settings(); items = [replace(item) for item in self.items]; output = Path(settings.output)
            if output.exists() and not messagebox.askyesno("Ghi đè", f"Ghi đè {output.name}?"): return
            self.cancel_event.clear(); self.busy(True, "Chuẩn bị render")
            def progress(phase, done, total): self.root.after(0, self.set_progress, "Chuẩn bị" if phase == "prepare" else "Render", done, total)
            def job():
                try:
                    metadata = render_video(items, settings, self.cache, output, self.cancel_event, progress)
                    self.root.after(0, self.render_done, metadata, None)
                except Exception as exc: self.root.after(0, self.render_done, None, exc)
            self.worker = threading.Thread(target=job, daemon=True); self.worker.start()

        def render_done(self, metadata, error):
            self.busy(False); self.progress["value"] = 0
            if error: self.say(f"Lỗi: {error}"); messagebox.showerror("Render thất bại", str(error)); return
            self.say(f"Xong: {metadata['path']} · {metadata['codec']} · {metadata['size'][0]}×{metadata['size'][1]} · {metadata['duration']:.2f}s")
            messagebox.showinfo("Hoàn tất", f"Đã tạo video:\n{metadata['path']}")
            if hasattr(os, "startfile"): os.startfile(Path(metadata["path"]).parent)

        def cancel(self): self.cancel_event.set(); self.status.config(text="Đang hủy…")

        def say(self, text):
            self.log.config(state="normal"); self.log.insert("end", str(text) + "\n"); self.log.see("end"); self.log.config(state="disabled")

        def confirm_discard(self):
            return not self.dirty or messagebox.askyesno("Chưa lưu", "Bỏ các thay đổi chưa lưu?")

        def new_project(self):
            if not self.confirm_discard(): return
            self.items.clear(); self.selected.clear(); self.project_path = None; self.crop = None; self.dirty = False
            self.draw_timeline(); self.show_preview(); self._title()

        def open_project(self):
            if not self.confirm_discard(): return
            path = filedialog.askopenfilename(filetypes=[("Metech Timelapse", "*.metech-timelapse.json"), ("JSON", "*.json")])
            if not path: return
            try:
                self.items, settings = load_project(path); self.apply_settings(settings); self.project_path = Path(path)
                self.selected = {0} if self.items else set(); self.dirty = False; self._title(); self.draw_timeline(); self.show_preview(); self.start_scan()
            except Exception as exc: messagebox.showerror("Không mở được project", str(exc))

        def save(self):
            if not self.project_path: return self.save_as()
            try: save_project(self.project_path, self.items, self.settings()); self.dirty = False; self._title()
            except Exception as exc: messagebox.showerror("Không lưu được", str(exc))

        def save_as(self):
            path = filedialog.asksaveasfilename(defaultextension=".metech-timelapse.json", filetypes=[("Metech Timelapse", "*.metech-timelapse.json")])
            if path: self.project_path = Path(path); self.save()

        def clear_cache(self):
            if self.worker and self.worker.is_alive(): return
            shutil.rmtree(self.cache, ignore_errors=True); self.cache.mkdir(parents=True, exist_ok=True)
            self.thumb_images.clear(); self.say("Đã xóa cache."); self.draw_timeline(); self.show_preview()

        def close(self):
            if not self.confirm_discard(): return
            self.cancel_event.set(); self.thumb_pool.shutdown(wait=False, cancel_futures=True); self.root.destroy()

    root = tk.Tk(); App(root); root.mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv: selftest()
    else: gui()
