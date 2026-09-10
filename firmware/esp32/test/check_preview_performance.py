from pathlib import Path
s=Path(__file__).resolve().parents[1].joinpath("main/app_main.c").read_text(encoding="utf-8")
u=Path(__file__).resolve().parents[1].joinpath("main/web_ui.h").read_text(encoding="utf-8")
assert "preview_size = FRAMESIZE_VGA" in s and "preview_delay_ms = 1000" in s
assert "PREVIEW_CACHE_CAP" in s and "PREVIEW_CACHE_TTL_US" in s
assert "esp_camera_fb_return(frame); sensor->set_framesize(sensor, preview_size); xSemaphoreGive(camera_lock);" in s
assert "lru_purge_enable=true" in s and "send_wait_timeout=5" in s
assert "poll();next();setTimeout(settings,1200)" in u
assert "poll,2000" not in u
print("PASS: preview performance contracts")
