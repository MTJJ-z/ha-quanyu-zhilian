"""Offline catalogue integrity, pagination and fail-closed send validation."""

import json
import sqlite3
import sys
import types
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).parents[1]
package = types.ModuleType("quanyu_zhilian")
package.__path__ = [str(ROOT / "custom_components" / "quanyu_zhilian")]
sys.modules.setdefault("quanyu_zhilian", package)

from quanyu_zhilian.ir_library import (  # noqa: E402
    DATABASE,
    InfraredLibrary,
    LibraryError,
    parse_flipper,
    raw_parameters,
)


class InfraredTests(unittest.TestCase):
    def setUp(self):
        self.library = InfraredLibrary()

    def test_parse_preserves_duplicate_names_and_parsed_fields(self):
        records = parse_flipper("""Filetype: IR signals file
Version: 1
# source attribution
name: Power
type: parsed
protocol: NEC
address: 01 00 00 00
command: 02 00 00 00
#
name: Power
type: raw
frequency: 38000
duty_cycle: 0.500000
data: 9000 4500 560
""")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["command"], "02 00 00 00")
        self.assertEqual(raw_parameters(records[1]), {"raw": [9000, 4500, 560], "frequency_khz": 38})

    def test_does_not_guess_parsed_protocol_or_truncate_raw(self):
        with self.assertRaisesRegex(LibraryError, "PARSED_PROTOCOL"):
            raw_parameters({"type": "parsed", "protocol": "NEC"})
        base = {"type": "raw", "frequency": "38000", "duty_cycle": "0.5", "data": "9000 4500"}
        for overrides, reason in [
            ({"data": " ".join(["560"] * 101)}, "RAW_LENGTH"),
            ({"data": "560 44227"}, "RAW_TIMING"),
            ({"frequency": "38500"}, "FREQUENCY"),
            ({"duty_cycle": "0.33"}, "DUTY_CYCLE"),
            ({"duty_cycle": "NaN"}, "DUTY_CYCLE"),
            ({"data": "560 abc"}, "INVALID_RAW"),
        ]:
            with self.subTest(reason=reason), self.assertRaisesRegex(LibraryError, reason):
                raw_parameters({**base, **overrides})

    def test_search_pagination_filters_and_safe_queries(self):
        first = self.library.search("", "ACs", limit=2)
        second = self.library.search("", "ACs", limit=2, offset=2)
        self.assertGreater(first["total"], 4)
        self.assertTrue(all(row["category"] == "ACs" for row in first["profiles"]))
        self.assertFalse({r["id"] for r in first["profiles"]} & {r["id"] for r in second["profiles"]})
        self.assertEqual(self.library.search("' OR 1=1 --")["total"], 0)
        self.assertEqual(self.library.search("%_no_such_remote")["total"], 0)

    def test_real_tcl_record_preserves_unsupported_long_gap(self):
        results = self.library.search("ACs/TCL/Tcl.ir")["profiles"]
        self.assertEqual(len(results), 1)
        profile = self.library.profile(results[0]["id"])
        self.assertEqual(profile["signals"][0]["name"], "Power")
        record = self.library.signal(results[0]["id"], 0)
        self.assertIn("44227", record["data"])
        self.assertFalse(profile["signals"][0]["cyd_sendable"])
        with self.assertRaises(LibraryError):
            self.library.signal(results[0]["id"], 999999)

    def test_complete_snapshot_integrity_and_source_retention(self):
        with sqlite3.connect(DATABASE) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            metadata = dict(db.execute("SELECT key, value FROM metadata"))
            self.assertEqual(db.execute("SELECT count(*) FROM profiles").fetchone()[0], int(metadata["profiles"]))
            self.assertEqual(db.execute("SELECT count(*) FROM signals").fetchone()[0], int(metadata["signals"]))
            self.assertEqual(int(metadata["unparsed_profiles"]), 0)
            total = 0
            for source, count in db.execute("SELECT source_text, signal_count FROM profiles"):
                records = parse_flipper(zlib.decompress(source).decode("utf-8-sig", errors="replace"))
                self.assertEqual(len(records), count)
                total += count
            self.assertEqual(total, 301915)
            # Every compressed record must remain valid JSON.
            for (blob,) in db.execute("SELECT data FROM signals"):
                self.assertIsInstance(json.loads(zlib.decompress(blob)), dict)


if __name__ == "__main__":
    unittest.main()
