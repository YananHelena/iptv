#!/usr/bin/env python3
import json
import sys
from pathlib import Path

DIRECTIVES = ("#EXTVLCOPT:", "#EXTHTTP:", "#KODIPROP:")

path = Path(sys.argv[1] if len(sys.argv) > 1 else "playlist.m3u")
data = path.read_bytes()

if data.startswith(b"\xef\xbb\xbf"):
    raise SystemExit("HATA: UTF-8 BOM bulundu")
if b"\r" in data:
    raise SystemExit("HATA: CR/CRLF satır sonu bulundu; LF kullanılmalı")

text = data.decode("utf-8")
lines = [line.strip() for line in text.splitlines() if line.strip()]

if not lines or lines[0] != "#EXTM3U":
    raise SystemExit("HATA: İlk satır #EXTM3U değil")

i = 1
channels = 0

while i < len(lines):
    if not lines[i].startswith("#EXTINF:"):
        raise SystemExit(f"HATA: EXTINF bekleniyordu: {lines[i]}")
    i += 1

    while i < len(lines) and lines[i].startswith(DIRECTIVES):
        if lines[i].startswith("#EXTHTTP:"):
            try:
                obj = json.loads(lines[i][len("#EXTHTTP:"):])
            except json.JSONDecodeError as exc:
                raise SystemExit(f"HATA: Geçersiz EXTHTTP JSON: {exc}")
            if not isinstance(obj, dict):
                raise SystemExit("HATA: EXTHTTP JSON object olmalı")
        i += 1

    if i >= len(lines):
        raise SystemExit("HATA: Son kanalın URL'si yok")

    url = lines[i]
    if not url.startswith(("http://", "https://")):
        raise SystemExit(f"HATA: Geçersiz URL: {url}")

    channels += 1
    i += 1

print(f"OK: {channels} kanal, UTF-8/LF, geçerli M3U yapısı: {path}")
