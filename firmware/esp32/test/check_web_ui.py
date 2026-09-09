#!/usr/bin/env python3
"""Static safeguards for the self-contained ESP32 dashboard."""
from pathlib import Path
import re

ui = Path(__file__).parents[1] / "main" / "web_ui.h"
source = ui.read_text(encoding="utf-8")
assert source.startswith("#pragma once\n")
assert len(source.encode()) < 20_000
assert not re.search(r"(?:src|href)=[\"']https?://|@import|<link\b", source)
for token in ("id=\"cam\"", "id=\"sdretry\"", "id=\"standby\"", "id=\"wake\"", "/api/status", "/api/sd/retry", "prefers-reduced-motion"):
    assert token in source, token
script = re.search(r"<script>(.*?)</script>", source, re.S)
assert script and "document.querySelector" in script.group(1)
print("PASS: embedded dashboard structure")
