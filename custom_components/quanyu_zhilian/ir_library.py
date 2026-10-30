"""Offline, read-only infrared catalogue. No network or HA dependencies."""

import json
import math
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path

DATABASE = Path(__file__).parent / "data" / "ir_library.sqlite3"


class LibraryError(ValueError):
    """A catalogue record cannot be used as requested."""


def parse_flipper(text: str) -> list[dict[str, str]]:
    """Keep raw and parsed entries without guessing encodings or dropping fields."""
    signals = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key == "name":
            if current:
                signals.append(current)
            current = {"name": value}
        elif current:
            if key in current:
                raise LibraryError(f"Duplicate field: {key}")
            current[key] = value
    if current:
        signals.append(current)
    return signals


def raw_parameters(signal: dict[str, str]) -> dict:
    """Preflight against CYD 0.2.1–0.3.0; never truncate or clamp a waveform."""
    if signal.get("type") != "raw":
        raise LibraryError("PARSED_PROTOCOL_NOT_SUPPORTED: record needs protocol encoding")
    try:
        frequency = int(signal["frequency"])
        duty = float(signal["duty_cycle"])
        raw = [int(value) for value in signal["data"].split()]
    except (KeyError, ValueError) as err:
        raise LibraryError("INVALID_RAW_RECORD") from err
    if not 30000 <= frequency <= 60000 or frequency % 1000:
        raise LibraryError("UNSUPPORTED_FREQUENCY: CYD requires whole kHz from 30 to 60")
    # IRremoteESP8266 sendRaw currently uses its default 50% duty cycle.
    if not math.isfinite(duty) or abs(duty - 0.5) > 0.000001:
        raise LibraryError("UNSUPPORTED_DUTY_CYCLE: current CYD uses 50%; original is preserved")
    if not 2 <= len(raw) <= 100:
        raise LibraryError(f"RAW_LENGTH_NOT_SUPPORTED: {len(raw)} timings; CYD maximum is 100")
    if any(not 100 <= value <= 30000 for value in raw):
        raise LibraryError("RAW_TIMING_NOT_SUPPORTED: CYD range is 100–30000 us")
    return {"raw": raw, "frequency_khz": frequency // 1000}


class InfraredLibrary:
    """Open a connection per worker operation; never load the entire library into RAM."""

    def __init__(self, path: Path = DATABASE) -> None:
        self.path = path

    def _connect(self):
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def search(self, query: str = "", category: str = "", limit: int = 20, offset: int = 0):
        if not 1 <= limit <= 100 or offset < 0:
            raise LibraryError("INVALID_PAGE")
        # Escape LIKE wildcards so model names containing _ or % stay literal.
        needle = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where = "search_text LIKE ? ESCAPE '\\' AND (? = '' OR category = ?)"
        params = (needle, category, category)
        with closing(self._connect()) as db:
            total = db.execute(f"SELECT count(*) FROM profiles WHERE {where}", params).fetchone()[0]
            rows = db.execute(
                f"SELECT id, category, brand, model, path, signal_count FROM profiles WHERE {where} ORDER BY path LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            metadata = dict(db.execute("SELECT key, value FROM metadata"))
        return {"total": total, "offset": offset, "profiles": [dict(row) for row in rows], "source": metadata}

    def profile(self, profile_id: str):
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
            if row is None:
                raise LibraryError("UNKNOWN_PROFILE")
            result = dict(row)
            result.pop("source_text")
            result.pop("search_text")
            signals = db.execute("SELECT ordinal, data FROM signals WHERE profile_id = ? ORDER BY ordinal", (profile_id,)).fetchall()
        result["signals"] = []
        for item in signals:
            signal = json.loads(zlib.decompress(item["data"]))
            try:
                raw_parameters(signal)
                reason = None
            except LibraryError as err:
                reason = str(err)
            result["signals"].append({"index": item["ordinal"], "name": signal.get("name", ""), "format": signal.get("type"), "protocol": signal.get("protocol"), "cyd_sendable": reason is None, "limitation": reason})
        return result

    def signal(self, profile_id: str, index: int):
        with closing(self._connect()) as db:
            row = db.execute("SELECT data FROM signals WHERE profile_id = ? AND ordinal = ?", (profile_id, index)).fetchone()
        if row is None:
            raise LibraryError("UNKNOWN_SIGNAL")
        return json.loads(zlib.decompress(row[0]))
