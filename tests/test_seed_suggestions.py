"""Unit tests for the seed-suggestions parser in server.py.

The endpoint is a thin wrapper around a single LLM call, so the
parser is the only piece with non-trivial logic worth testing. We
exercise it directly so we don't need a running LLM.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from tests._helpers import PROJECT_ROOT


class TestSeedParser(unittest.TestCase):
    def test_parses_clean_json_array(self):
        from server import _parse_seed_response
        raw = json.dumps([
            {"title": "The Iron Bell", "description": "A bell that never rings.",
             "style": "dark fantasy", "tone": "dark", "characters": "Mira, bell-ringer"},
            {"title": "Saltwater Crown", "description": "Pirates of the inland sea.",
             "style": "cinematic", "tone": "epic", "characters": ""},
        ])
        out = _parse_seed_response(raw, 2)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["title"], "The Iron Bell")
        self.assertEqual(out[0]["style"], "dark fantasy")
        self.assertEqual(out[1]["characters"], "")

    def test_strips_markdown_fences(self):
        from server import _parse_seed_response
        raw = "```json\n[{\"title\": \"X\", \"description\": \"y\"}]\n```"
        out = _parse_seed_response(raw, 1)
        self.assertEqual(out[0]["title"], "X")

    def test_strips_surrounding_prose(self):
        from server import _parse_seed_response
        raw = "Here you go:\n[{\"title\": \"X\", \"description\": \"y\"}]\nEnjoy!"
        out = _parse_seed_response(raw, 1)
        self.assertEqual(out[0]["title"], "X")

    def test_handles_trailing_commas(self):
        from server import _parse_seed_response
        raw = '[{"title": "X", "description": "y",},]'
        out = _parse_seed_response(raw, 1)
        self.assertEqual(out[0]["title"], "X")

    def test_strips_quotes_from_title(self):
        from server import _parse_seed_response
        # LLM sometimes returns title fields wrapped in stray quotes.
        # Build the raw string with proper JSON escaping so the parser
        # sees a real JSON value containing literal quote chars.
        raw = json.dumps([{"title": '"The Iron Bell"', "description": "y"}])
        out = _parse_seed_response(raw, 1)
        self.assertEqual(out[0]["title"], "The Iron Bell")

    def test_truncates_oversized_fields(self):
        from server import _parse_seed_response
        long_desc = "x" * 400
        long_title = "y" * 100
        raw = json.dumps([{"title": long_title, "description": long_desc}])
        out = _parse_seed_response(raw, 1)
        self.assertLessEqual(len(out[0]["title"]), 80)
        self.assertLessEqual(len(out[0]["description"]), 320)

    def test_pads_to_expected_count(self):
        from server import _parse_seed_response
        # LLM returns only 1 seed but we wanted 4
        raw = json.dumps([{"title": "Only", "description": "d"}])
        out = _parse_seed_response(raw, 4)
        self.assertEqual(len(out), 4)
        # The 3 extra ones should be fallback placeholders
        for seed in out[1:]:
            self.assertIn(seed["title"], ("Seed 2", "Seed 3", "Seed 4"))

    def test_truncates_to_expected_count(self):
        from server import _parse_seed_response
        raw = json.dumps([{"title": f"S{i}", "description": "d"} for i in range(5)])
        out = _parse_seed_response(raw, 2)
        self.assertEqual(len(out), 2)

    def test_skips_non_dict_items(self):
        from server import _parse_seed_response
        raw = '[{"title": "X"}, "garbage", null, {"title": "Y"}]'
        out = _parse_seed_response(raw, 2)
        titles = [s["title"] for s in out]
        self.assertIn("X", titles)
        self.assertIn("Y", titles)

    def test_rejects_non_array(self):
        from server import _parse_seed_response
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            _parse_seed_response('{"title": "X"}', 1)


class TestCoerceSeedItem(unittest.TestCase):
    def test_defaults_for_missing_keys(self):
        from server import _coerce_seed_item
        out = _coerce_seed_item({})
        self.assertEqual(out["title"], "Untitled Seed")
        self.assertEqual(out["style"], "fantasy painterly")
        self.assertEqual(out["tone"], "dramatic")

    def test_normalizes_case(self):
        from server import _coerce_seed_item
        out = _coerce_seed_item({"title": "X", "style": "CINEMATIC", "tone": "EPIC"})
        self.assertEqual(out["style"], "cinematic")
        self.assertEqual(out["tone"], "epic")


if __name__ == "__main__":
    unittest.main()
