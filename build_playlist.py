#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "channels.json"

QUALITY_RE = re.compile(r"\s*(?:\((?:\d{3,4}p|SD|HD|FHD|4K)\)|\[(?:[^\]]+)\])\s*", re.I)
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


@dataclass
class Entry:
    extinf: str
    url: str
    name: str
    tvg_id: str
    logo: str


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = value.replace("ı", "i")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def clean_display_name(name: str) -> str:
    name = QUALITY_RE.sub(" ", name)
    return " ".join(name.split()).strip()


def parse_m3u(text: str) -> list[Entry]:
    # UTF-8 BOM ve CRLF gibi kaynak farklılıklarını güvenli biçimde tolere et.
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]

    entries: list[Entry] = []
    pending_extinf: str | None = None

    for line in lines:
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            pending_extinf = line
            continue
        if line.startswith("#"):
            continue
        if pending_extinf and (line.startswith("http://") or line.startswith("https://")):
            attrs = dict(ATTR_RE.findall(pending_extinf))
            display = pending_extinf.split(",", 1)[1].strip() if "," in pending_extinf else ""
            entries.append(
                Entry(
                    extinf=pending_extinf,
                    url=line,
                    name=clean_display_name(display),
                    tvg_id=attrs.get("tvg-id", ""),
                    logo=attrs.get("tvg-logo", ""),
                )
            )
            pending_extinf = None
    return entries


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "turkiye-iptv-builder/1.0 (+GitHub Actions; public playlist builder)",
            "Accept": "application/x-mpegURL,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return raw.decode("utf-8-sig", errors="replace")


def candidate_score(entry: Entry) -> int:
    blob = f"{entry.extinf} {entry.name}".casefold()
    score = 0
    if entry.url.startswith("https://"):
        score += 40
    if "2160p" in blob or "4k" in blob:
        score += 35
    elif "1080p" in blob:
        score += 30
    elif "720p" in blob:
        score += 20
    elif "576p" in blob or "540p" in blob:
        score += 5
    if "not 24/7" in blob:
        score -= 45
    if "geo-blocked" in blob or "geoblocked" in blob:
        score -= 20
    if "@sd" in entry.tvg_id.casefold() or "(sd)" in blob:
        score -= 10
    return score


def matches(entry: Entry, spec: dict) -> bool:
    ids = {x.casefold() for x in spec.get("tvg_ids", [])}
    if entry.tvg_id.casefold() in ids:
        return True

    wanted = {normalize(x) for x in spec.get("aliases", [])}
    if not wanted:
        wanted = {normalize(spec["name"])}

    # Exact normalized name match avoids ATV -> ATV Avrupa gibi yanlış eşleşmeleri.
    return normalize(entry.name) in wanted


def pick_entry(entries: Iterable[Entry], spec: dict) -> Entry | None:
    found = [entry for entry in entries if matches(entry, spec)]
    if not found:
        return None
    return max(found, key=candidate_score)


def escape_attr(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_entry(name: str, group: str, entry: Entry | None = None, custom: dict | None = None) -> str:
    if custom:
        tvg_id = custom.get("tvg_id", "")
        logo = custom.get("logo", "")
        url = custom["url"].strip()
    elif entry:
        tvg_id = entry.tvg_id
        logo = entry.logo
        url = entry.url.strip()
    else:
        raise ValueError("entry veya custom gerekli")

    attrs = []
    if tvg_id:
        attrs.append(f'tvg-id="{escape_attr(tvg_id)}"')
    if logo:
        # Logo için mümkünse HTTPS kullan; mixed-content sorunu çıkarmaz.
        if logo.startswith("http://"):
            logo = "https://" + logo[len("http://"):]
        attrs.append(f'tvg-logo="{escape_attr(logo)}"')
    attrs.append(f'group-title="{escape_attr(group)}"')

    return f'#EXTINF:-1 {" ".join(attrs)},{name}\n{url}'


def build(config: dict, source_text: str) -> tuple[str, list[str]]:
    source_entries = parse_m3u(source_text)
    output = ["#EXTM3U"]
    missing: list[str] = []
    seen_urls: set[str] = set()

    for spec in config["channels"]:
        custom = spec.get("custom")
        if custom:
            block = render_entry(spec["name"], spec["group"], custom=custom)
        else:
            entry = pick_entry(source_entries, spec)
            if not entry:
                missing.append(spec["name"])
                continue
            block = render_entry(spec["name"], spec["group"], entry=entry)

        url = block.splitlines()[-1].strip()
        if url in seen_urls:
            continue
        seen_urls.add(url)
        output.append(block)

    return "\n".join(output).rstrip() + "\n", missing


def validate_output(text: str) -> None:
    if text.startswith("\ufeff"):
        raise ValueError("Çıktıda UTF-8 BOM olmamalı")
    if "\r" in text:
        raise ValueError("Çıktı LF satır sonu kullanmalı")
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if not lines or lines[0] != "#EXTM3U":
        raise ValueError("İlk satır #EXTM3U olmalı")

    i = 1
    while i < len(lines):
        if not lines[i].startswith("#EXTINF:"):
            raise ValueError(f"Beklenmeyen satır: {lines[i]}")
        if i + 1 >= len(lines) or not lines[i + 1].startswith(("http://", "https://")):
            raise ValueError(f"EXTINF sonrası geçerli URL yok: {lines[i]}")
        i += 2


def main() -> int:
    parser = argparse.ArgumentParser(description="iptv-org Türkçe listesinden sade Türkiye playlist'i üretir.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--source", help="Kaynak M3U URL'sini geçersiz kıl")
    parser.add_argument("--source-file", help="İnternet yerine yerel M3U dosyası kullan (test için)")
    parser.add_argument("--output", help="Çıktı dosyası")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source_url = args.source or config["source"]
    output_path = Path(args.output or config.get("output", "playlist.m3u"))

    if args.source_file:
        source_text = Path(args.source_file).read_text(encoding="utf-8-sig")
    else:
        print(f"Kaynak indiriliyor: {source_url}")
        source_text = fetch_text(source_url)

    playlist, missing = build(config, source_text)
    validate_output(playlist)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(playlist, encoding="utf-8", newline="\n")

    count = playlist.count("#EXTINF:")
    print(f"{output_path} oluşturuldu: {count} kanal")
    if missing:
        print("Kaynakta bulunamayan ve atlanan kanallar:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        # Kaynaktaki isim değişiklikleri tüm playlist'i bozmasın; Action başarılı kalsın.
        print("channels.json içindeki aliases/tvg_ids alanlarını güncelleyebilirsin.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
