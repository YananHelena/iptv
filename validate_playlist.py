#!/usr/bin/env python3
from pathlib import Path
import sys

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

channels = 0
i = 1
while i < len(lines):
    if not lines[i].startswith("#EXTINF:"):
        raise SystemExit(f"HATA: EXTINF bekleniyordu: {lines[i]}")
    if i + 1 >= len(lines):
        raise SystemExit("HATA: Son EXTINF'in URL'si yok")
    url = lines[i + 1]
    if not url.startswith(("http://", "https://")):
        raise SystemExit(f"HATA: Geçersiz URL: {url}")
    channels += 1
    i += 2

print(f"OK: {channels} kanal, UTF-8/LF, geçerli M3U yapısı")
