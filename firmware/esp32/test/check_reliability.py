from pathlib import Path
h = (Path(__file__).parents[1] / "main" / "metech_reliability.h").read_text(encoding="ascii")
c = (Path(__file__).parents[1] / "main" / "metech_reliability.c").read_text(encoding="ascii")
a = (Path(__file__).parents[1] / "main" / "app_main.c").read_text(encoding="utf-8")
for token in ("METECH_JOB_RUNNING", "METECH_JOB_COOLDOWN", "metech_retry_delay_ms", "metech_json_append_string"):
    assert token in h and token in c, token
for token in ("WIFI_SCAN_TYPE_PASSIVE", "metech_job_begin(&wifi_scan_job)", "metech_retry_delay_ms(scan.attempts", "ESP_ERR_TIMEOUT"):
    assert token in a, token
assert "wifi_scan_pending" not in a
print("PASS: reliability contracts")
