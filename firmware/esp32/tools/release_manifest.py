#!/usr/bin/env python3
import argparse, hashlib, json
from datetime import UTC, datetime
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--version', required=True)
parser.add_argument('--git-sha', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path('build')
parts = [
    ('0x0', root / 'bootloader' / 'bootloader.bin', 'bootloader.bin'),
    ('0x8000', root / 'partition_table' / 'partition-table.bin', 'partition-table.bin'),
    ('0x10000', root / 'metech_capture.bin', 'metech_capture.bin'),
]
out = args.output
out.mkdir(parents=True, exist_ok=True)
manifest_parts = []
for offset, source, name in parts:
    payload = source.read_bytes()
    (out / name).write_bytes(payload)
    manifest_parts.append({'offset': offset, 'file': name, 'sha256': hashlib.sha256(payload).hexdigest(), 'size': len(payload)})
(out / 'release.json').write_text(json.dumps({
    'version': args.version, 'git_sha': args.git_sha, 'built_at': datetime.now(UTC).replace(microsecond=0).isoformat(),
    'chip': 'ESP32-S3', 'parts': manifest_parts,
}, indent=2) + '\n', encoding='utf-8')
