#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "channels.json"

ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
QUALITY_PAREN_RE = re.compile(
    r"\s*\((?:2160p|1440p|1080p|720p|576p|540p|480p|360p|240p|4K|UHD|FHD|HD|SD)\)\s*",
    re.I,
)
SUPPORTED_DIRECTIVES = ("#EXTVLCOPT:", "#EXTHTTP:", "#KODIPROP:")


@dataclass
class Entry:
    extinf: str
    url: str
    name: str
    tvg_id: str
    logo: str
    directives: list[str] = field(default_factory=list)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("ı", "i")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def compact_normalize(value: str) -> str:
    return normalize(value).replace(" ", "")


def canonical_tvg_id(value: str) -> str:
    # iptv-org feed/profile suffixes: TV8.tr@SD, NTV.tr@HD, ...
    return value.strip().casefold().split("@", 1)[0]


def clean_display_name(name: str) -> str:
    name = QUALITY_PAREN_RE.sub(" ", name)
    # Remove bracket notes commonly used by generated playlists.
    name = re.sub(r"\s*\[[^\]]+\]\s*", " ", name)
    return " ".join(name.split()).strip()


def parse_m3u(text: str) -> list[Entry]:
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    entries: list[Entry] = []

    pending_extinf: str | None = None
    pending_directives: list[str] = []

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("#EXTINF:"):
            pending_extinf = line
            pending_directives = []
            continue

        if pending_extinf and line.startswith(SUPPORTED_DIRECTIVES):
            # Preserve per-stream headers/properties already supplied by iptv-org.
            pending_directives.append(line)
            continue

        if line.startswith("#"):
            continue

        if pending_extinf and line.startswith(("http://", "https://")):
            attrs = dict(ATTR_RE.findall(pending_extinf))
            display = pending_extinf.split(",", 1)[1].strip() if "," in pending_extinf else ""
            entries.append(
                Entry(
                    extinf=pending_extinf,
                    url=line,
                    name=clean_display_name(display),
                    tvg_id=attrs.get("tvg-id", ""),
                    logo=attrs.get("tvg-logo", ""),
                    directives=list(pending_directives),
                )
            )
            pending_extinf = None
            pending_directives = []

    return entries


def fetch_text(url: str, timeout: int = 45) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "turkiye-iptv-builder/2.0",
            "Accept": "application/x-mpegURL,application/vnd.apple.mpegurl,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return raw.decode("utf-8-sig", errors="replace")


def candidate_score(entry: Entry) -> int:
    blob = f"{entry.extinf} {entry.name}".casefold()
    score = 0

    if entry.url.startswith("https://"):
        score += 50

    if "2160p" in blob or "4k" in blob or "uhd" in blob:
        score += 40
    elif "1440p" in blob:
        score += 35
    elif "1080p" in blob or "fhd" in blob:
        score += 30
    elif "720p" in blob or "(hd)" in blob:
        score += 20
    elif "576p" in blob or "540p" in blob:
        score += 8

    if "not 24/7" in blob:
        score -= 60
    if "geo-blocked" in blob or "geoblocked" in blob:
        score -= 35
    if "@sd" in entry.tvg_id.casefold() or "(sd)" in blob:
        score -= 8

    return score


def matches(entry: Entry, spec: dict) -> bool:
    wanted_ids = {
        canonical_tvg_id(x)
        for x in spec.get("tvg_ids", [])
        if x
    }
    entry_id = canonical_tvg_id(entry.tvg_id)

    if entry_id and entry_id in wanted_ids:
        return True

    aliases = spec.get("aliases", []) or [spec["name"]]

    normalized_aliases = {normalize(x) for x in aliases}
    if normalize(entry.name) in normalized_aliases:
        return True

    compact_aliases = {compact_normalize(x) for x in aliases}
    return compact_normalize(entry.name) in compact_aliases


def pick_entry(entries: Iterable[Entry], spec: dict) -> Entry | None:
    found = [entry for entry in entries if matches(entry, spec)]
    return max(found, key=candidate_score) if found else None


def closest_names(entries: Iterable[Entry], spec: dict, limit: int = 3) -> list[str]:
    aliases = spec.get("aliases", []) or [spec["name"]]
    wanted = compact_normalize(aliases[0])
    names = sorted({entry.name for entry in entries})
    key_to_name = {compact_normalize(name): name for name in names}
    hits = difflib.get_close_matches(wanted, list(key_to_name), n=limit, cutoff=0.55)
    return [key_to_name[x] for x in hits]


def escape_attr(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def header_directives(headers: dict[str, str]) -> list[str]:
    if not headers:
        return []

    lines: list[str] = []

    user_agent = headers.get("User-Agent")
    referer = headers.get("Referer")
    origin = headers.get("Origin")

    # VLC/Kodi/TiviMate-style directives. Unknown # lines are safely ignored by
    # players that do not support them.
    if user_agent:
        lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")
    if referer:
        lines.append(f"#EXTVLCOPT:http-referrer={referer}")
    if origin:
        lines.append(f"#EXTVLCOPT:http-origin={origin}")

    # OTT Navigator and some other players understand JSON header metadata.
    # Keeping this as a separate # directive is safer than appending |headers
    # to the URL: unsupported players still receive the original clean URL.
    lines.append("#EXTHTTP:" + json.dumps(headers, ensure_ascii=False, separators=(",", ":")))
    return lines


def render_entry(
    name: str,
    group: str,
    *,
    entry: Entry | None = None,
    custom: dict | None = None,
    include_headers: bool = True,
) -> list[str]:
    if custom is not None:
        tvg_id = custom.get("tvg_id", "")
        logo = custom.get("logo", "")
        url = custom["url"].strip()
        directives = header_directives(custom.get("headers", {})) if include_headers else []
    elif entry is not None:
        tvg_id = entry.tvg_id
        logo = entry.logo
        url = entry.url.strip()
        directives = list(entry.directives) if include_headers else []
    else:
        raise ValueError("entry veya custom gerekli")

    attrs: list[str] = []
    if tvg_id:
        attrs.append(f'tvg-id="{escape_attr(tvg_id)}"')

    if logo:
        if logo.startswith("http://"):
            logo = "https://" + logo[len("http://"):]
        attrs.append(f'tvg-logo="{escape_attr(logo)}"')

    attrs.append(f'group-title="{escape_attr(group)}"')

    return [
        f'#EXTINF:-1 {" ".join(attrs)},{name}',
        *directives,
        url,
    ]


def build(
    config: dict,
    source_text: str,
    *,
    include_headers: bool = True,
    only_custom: bool = False,
) -> tuple[str, list[tuple[str, list[str]]]]:
    source_entries = parse_m3u(source_text)
    output = ["#EXTM3U"]
    missing: list[tuple[str, list[str]]] = []
    seen_urls: set[str] = set()

    for spec in config["channels"]:
        custom = spec.get("custom")

        if only_custom and not custom:
            continue

        if custom:
            block = render_entry(
                spec["name"],
                spec["group"],
                custom=custom,
                include_headers=include_headers,
            )
        else:
            entry = pick_entry(source_entries, spec)
            if not entry:
                missing.append((spec["name"], closest_names(source_entries, spec)))
                continue
            block = render_entry(
                spec["name"],
                spec["group"],
                entry=entry,
                include_headers=include_headers,
            )

        url = block[-1].strip()
        if url in seen_urls:
            continue
        seen_urls.add(url)
        output.extend(block)

    return "\n".join(output).rstrip() + "\n", missing


def validate_output(text: str) -> int:
    if text.startswith("\ufeff"):
        raise ValueError("Çıktıda UTF-8 BOM olmamalı")
    if "\r" in text:
        raise ValueError("Çıktı LF satır sonu kullanmalı")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        raise ValueError("İlk satır #EXTM3U olmalı")

    channels = 0
    i = 1

    while i < len(lines):
        if not lines[i].startswith("#EXTINF:"):
            raise ValueError(f"EXTINF bekleniyordu: {lines[i]}")
        i += 1

        while i < len(lines) and lines[i].startswith(SUPPORTED_DIRECTIVES):
            if lines[i].startswith("#EXTHTTP:"):
                payload = lines[i][len("#EXTHTTP:"):]
                parsed = json.loads(payload)
                if not isinstance(parsed, dict):
                    raise ValueError("#EXTHTTP JSON object olmalı")
            i += 1

        if i >= len(lines) or not lines[i].startswith(("http://", "https://")):
            raise ValueError("EXTINF/directive satırlarından sonra geçerli HTTP(S) URL yok")

        channels += 1
        i += 1

    return channels


def write_utf8_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="iptv-org Türkçe listesinden temiz ve sıralı Türkiye playlist'i üretir."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--source", help="Kaynak M3U URL'sini geçersiz kıl")
    parser.add_argument("--source-file", help="Test için yerel M3U kaynağı kullan")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source_url = args.source or config["source"]

    if args.source_file:
        source_text = Path(args.source_file).read_text(encoding="utf-8-sig")
    else:
        print(f"Kaynak indiriliyor: {source_url}")
        source_text = fetch_text(source_url)

    enhanced, missing = build(config, source_text, include_headers=True)
    plain, _ = build(config, source_text, include_headers=False)
    special, _ = build(config, source_text, include_headers=True, only_custom=True)

    enhanced_count = validate_output(enhanced)
    plain_count = validate_output(plain)
    special_count = validate_output(special)

    output = Path(config.get("output", "playlist.m3u"))
    plain_output = Path(config.get("plain_output", "playlist_plain.m3u"))
    special_output = Path(config.get("special_output", "special-test.m3u"))

    write_utf8_lf(output, enhanced)
    write_utf8_lf(plain_output, plain)
    write_utf8_lf(special_output, special)

    print(f"{output}: {enhanced_count} kanal")
    print(f"{plain_output}: {plain_count} kanal")
    print(f"{special_output}: {special_count} özel kanal")

    if missing:
        print("\nKaynakta eşleşmeyen / atlanan kanallar:", file=sys.stderr)
        for name, suggestions in missing:
            suffix = f" | yakın kayıtlar: {', '.join(suggestions)}" if suggestions else ""
            print(f"  - {name}{suffix}", file=sys.stderr)

    print("\nÖzel yayınlar playlist.m3u içinde URL'yi değiştirmeden HTTP header direktifleriyle yazıldı.")
    print("playlist_plain.m3u ise aynı yayınların çıplak URL'li yedek sürümüdür.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
