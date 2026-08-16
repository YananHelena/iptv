#!/usr/bin/env python3
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bp", ROOT / "build_playlist.py")
bp = importlib.util.module_from_spec(spec)
sys.modules["bp"] = bp
spec.loader.exec_module(bp)

SOURCE = """#EXTM3U
#EXTINF:-1 tvg-id="TV8.tr@SD" tvg-logo="http://example.com/tv8.png",TV 8 (1080p)
#EXTVLCOPT:http-user-agent=SourceAgent/1.0
https://example.test/tv8.m3u8
#EXTINF:-1 tvg-id="A2TV.tr@SD",A2TV (720p)
https://example.test/a2.m3u8
#EXTINF:-1 tvg-id="HaberturkTV.tr@HD",Habertürk TV (1080p)
https://example.test/haberturk.m3u8
#EXTINF:-1 tvg-id="TV100.tr@SD",TV 100 (1080p)
https://example.test/tv100.m3u8
#EXTINF:-1 tvg-id="TV85.tr@SD",TV 8.5 (720p)
https://example.test/tv85.m3u8
"""

class BuilderTests(unittest.TestCase):
    def test_canonical_id_ignores_feed_suffix(self):
        entries = bp.parse_m3u(SOURCE)
        cfg = {"name": "TV8", "aliases": ["TV8"], "tvg_ids": ["TV8.tr"]}
        hit = bp.pick_entry(entries, cfg)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.tvg_id, "TV8.tr@SD")

    def test_spacing_and_punctuation_name_match(self):
        entries = bp.parse_m3u(SOURCE)
        cfg = {"name": "TV8.5", "aliases": ["TV8.5"], "tvg_ids": ["wrong.tr"]}
        hit = bp.pick_entry(entries, cfg)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.url, "https://example.test/tv85.m3u8")

    def test_preserves_source_header_directives(self):
        entries = bp.parse_m3u(SOURCE)
        tv8 = entries[0]
        self.assertIn("#EXTVLCOPT:http-user-agent=SourceAgent/1.0", tv8.directives)

    def test_custom_headers_do_not_mutate_url(self):
        custom = {
            "tvg_id": "DMAX.HD.tr",
            "logo": "http://example.com/logo.png",
            "url": "https://example.test/dmax?m3u8",
            "headers": {
                "User-Agent": "VLC/3.0.21 LibVLC/3.0.21",
                "Referer": "https://example.test/"
            }
        }
        block = bp.render_entry("DMAX", "Eğlence", custom=custom, include_headers=True)
        self.assertEqual(block[-1], "https://example.test/dmax?m3u8")
        self.assertTrue(any(x.startswith("#EXTVLCOPT:http-user-agent=") for x in block))
        self.assertTrue(any(x.startswith("#EXTHTTP:") for x in block))

    def test_enhanced_and_plain_validate(self):
        cfg = {
            "channels": [
                {"name":"TV8","group":"Ulusal","aliases":["TV8"],"tvg_ids":["TV8.tr"]},
                {"name":"DMAX","group":"Eğlence","custom":{
                    "tvg_id":"DMAX.HD.tr",
                    "logo":"https://example.test/d.png",
                    "url":"https://example.test/dmax.m3u8",
                    "headers":{"User-Agent":"VLC/3.0.21","Referer":"https://example.test/"}
                }}
            ]
        }
        enhanced, missing = bp.build(cfg, SOURCE, include_headers=True)
        plain, _ = bp.build(cfg, SOURCE, include_headers=False)
        self.assertFalse(missing)
        self.assertEqual(bp.validate_output(enhanced), 2)
        self.assertEqual(bp.validate_output(plain), 2)
        self.assertIn("#EXTVLCOPT:", enhanced)
        self.assertNotIn("#EXTVLCOPT:", plain)

if __name__ == "__main__":
    unittest.main(verbosity=2)
