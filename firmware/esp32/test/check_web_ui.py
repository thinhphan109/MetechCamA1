#!/usr/bin/env python3
"""Static safeguards for the self-contained ESP32 dashboard."""
from pathlib import Path
import re

source = (Path(__file__).parents[1] / "main" / "web_ui.h").read_text(encoding="utf-8")
assert source.startswith("#pragma once\n")
assert len(source.encode()) < 20_000
assert not re.search(r"(?:src|href)=[\"']https?://|@import|<link\b", source)
for token in ("id=\"cam\"", "id=\"sdretry\"", "id=\"standby\"", "id=\"wake\"", "src=\"/logo.png\"", "id=\"wifiscan\"", "id=\"lightbox\"", "/api/status", "/api/sd/retry", "/api/wifi/scan", "prefers-reduced-motion"):
    assert token in source, token
script = re.search(r"<script>(.*?)</script>", source, re.S)
assert script and "document.querySelector" in script.group(1)
for codepoints in ((0x47, 0xF3, 0x63, 0x20, 0x6E, 0x68, 0xEC, 0x6E, 0x20, 0x74, 0x72, 0x1EF1, 0x63, 0x20, 0x74, 0x69, 0x1EBF, 0x70), (0x110, 0x1ED9, 0x20, 0x73, 0xE1, 0x6E, 0x67), (0x110, 0x61, 0x6E, 0x67, 0x20, 0x6B, 0x1EBF, 0x74, 0x20, 0x6E, 0x1ED1, 0x69), (0x43, 0x61, 0x6D, 0x65, 0x72, 0x61, 0x20, 0x26, 0x20, 0x6E, 0x68, 0x69, 0x1EC7, 0x74), (0x110, 0xE3, 0x20, 0x6C, 0x1B0, 0x75, 0x3A, 0x20), (0x4C, 0x1ED7, 0x69, 0x3A, 0x20)):
    assert "".join(map(chr, codepoints)) in source, codepoints
for bad in ("?ang", "ho?t", "L?i", "G?c nh?n"):
    assert bad not in source, bad
print("PASS: embedded dashboard structure")
