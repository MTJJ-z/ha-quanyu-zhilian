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
    send_parameters,
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
        self.assertEqual(raw_parameters(records[1]), {"raw": [9000, 4500, 560], "frequency_khz": 38, "duty_cycle": 50})
        self.assertEqual(send_parameters(records[0]), {
            "mode": "parsed", "protocol": "NEC", "address": 1,
            "command": 2, "bits": 32,
        })

    def test_parsed_protocol_aliases_and_unsupported_variants(self):
        base = {"type": "parsed", "protocol": "NECext", "address": "20 9F 00 00", "command": "11 00 00 00"}
        self.assertEqual(send_parameters(base), {
            "mode": "parsed", "protocol": "NECEXT", "address": 0x9F20,
            "command": 0x11, "bits": 32,
        })
        for protocol in ("Kaseikyo", "SIRC15-extra"):
            with self.subTest(protocol=protocol), self.assertRaisesRegex(LibraryError, "UNSUPPORTED_PARSED_PROTOCOL"):
                send_parameters({**base, "protocol": protocol})
        with self.assertRaisesRegex(LibraryError, "UNSUPPORTED_PARSED_FIELDS"):
            send_parameters({**base, "address": "00 00 01 00"})

        nec42 = {**base, "protocol": "NEC42", "address": "34 12 00 00", "command": "56 00 00 00"}
        self.assertEqual(send_parameters(nec42), {
            "mode": "parsed", "protocol": "NEC42", "address": 0x1234,
            "command": 0x56, "bits": 42,
        })

    def test_supported_protocol_bit_lengths(self):
        examples = {
            "NEC": ("00 00 00 00", "00 00 00 00", "NEC", 32),
            "NEC42ext": ("00 00 00 00", "00 00 00 00", "NEC42EXT", 42),
            "Samsung32": ("01 00 00 00", "02 00 00 00", "SAMSUNG", 32),
            "RC5": ("01 00 00 00", "02 00 00 00", "RC5", 14),
            "RC5X": ("01 00 00 00", "42 00 00 00", "RC5X", 14),
            "RC6": ("01 00 00 00", "02 00 00 00", "RC6", 21),
            "SIRC": ("01 00 00 00", "02 00 00 00", "SONY", 12),
            "SIRC15": ("01 00 00 00", "02 00 00 00", "SONY", 15),
            "SIRC20": ("01 00 00 00", "02 00 00 00", "SONY", 20),
            "Pioneer": ("01 00 00 00", "02 00 00 00", "PIONEER", 33),
        }
        for source, (address, command, protocol, bits) in examples.items():
            with self.subTest(protocol=source):
                payload = send_parameters({
                    "type": "parsed", "protocol": source,
                    "address": address, "command": command,
                })
                self.assertEqual((payload["protocol"], payload["bits"]), (protocol, bits))

    def test_does_not_truncate_raw(self):
        base = {"type": "raw", "frequency": "38000", "duty_cycle": "0.5", "data": "9000 4500"}
        for overrides, reason in [
            ({"data": " ".join(["560"] * 501)}, "RAW_LENGTH"),
            ({"data": "70000 560"}, "RAW_TIMING"),
            ({"data": "560 1000001"}, "RAW_TIMING"),
            ({"frequency": "61000"}, "FREQUENCY"),
            ({"duty_cycle": "0.1"}, "DUTY_CYCLE"),
            ({"duty_cycle": "NaN"}, "DUTY_CYCLE"),
            ({"data": "560 abc"}, "INVALID_RAW"),
        ]:
            with self.subTest(reason=reason), self.assertRaisesRegex(LibraryError, reason):
                raw_parameters({**base, **overrides})
        self.assertEqual(len(raw_parameters({**base, "data": " ".join(["560"] * 500)})["raw"]), 500)
        self.assertEqual(raw_parameters({**base, "data": "560 70000"})["raw"], [560, 70000])

    def test_search_pagination_filters_and_safe_queries(self):
        first = self.library.search("", "ACs", limit=2)
        second = self.library.search("", "ACs", limit=2, offset=2)
        self.assertGreater(first["total"], 4)
        self.assertTrue(all(row["category"] == "ACs" for row in first["profiles"]))
        self.assertFalse({r["id"] for r in first["profiles"]} & {r["id"] for r in second["profiles"]})
        self.assertEqual(self.library.search("' OR 1=1 --")["total"], 0)
        self.assertEqual(self.library.search("%_no_such_remote")["total"], 0)

    def test_real_tcl_record_preserves_long_gap_and_is_sendable(self):
        results = self.library.search("ACs/TCL/Tcl.ir")["profiles"]
        self.assertEqual(len(results), 1)
        profile = self.library.profile(results[0]["id"])
        self.assertEqual(profile["signals"][0]["name"], "Power")
        record = self.library.signal(results[0]["id"], 0)
        self.assertIn("44227", record["data"])
        self.assertTrue(profile["signals"][0]["cyd_sendable"])
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
