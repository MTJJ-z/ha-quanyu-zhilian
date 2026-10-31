"""Offline, read-only infrared catalogue. No network or HA dependencies."""

import json
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path

DATABASE = Path(__file__).parent / "data" / "ir_library.sqlite3"


class LibraryError(ValueError):
    """A catalogue record cannot be used as requested."""


PARSED_PROTOCOLS = {
    "NEC": ("NEC", 32),
    "NECext": ("NECEXT", 32),
    "NEC42": ("NEC42", 42),
    "NEC42ext": ("NEC42EXT", 42),
    "Samsung32": ("SAMSUNG", 32),
    "RC5": ("RC5", 14),
    "RC5X": ("RC5X", 14),
    "RC6": ("RC6", 21),
    "SIRC": ("SONY", 12),
    "SIRC15": ("SONY", 15),
    "SIRC20": ("SONY", 20),
    "Pioneer": ("PIONEER", 33),
}


def _parsed_parameters(signal: dict[str, str]) -> dict:
    protocol = signal.get("protocol", "")
    mapping = PARSED_PROTOCOLS.get(protocol)
    if mapping is None:
        raise LibraryError(f"UNSUPPORTED_PARSED_PROTOCOL: {protocol or 'missing protocol'}")
    try:
        address_bytes = bytes.fromhex(signal["address"])
        command_bytes = bytes.fromhex(signal["command"])
    except (KeyError, ValueError) as err:
        raise LibraryError("INVALID_PARSED_RECORD") from err
    if len(address_bytes) > 4 or len(command_bytes) > 4:
        raise LibraryError("INVALID_PARSED_RECORD")
    address = int.from_bytes(address_bytes, "little")
    command = int.from_bytes(command_bytes, "little")
    protocol_id, bits = mapping
    limits = {
        "NEC": (0xFF, 0xFF), "NECEXT": (0xFFFF, 0xFFFF),
        "NEC42": (0x1FFF, 0xFF), "NEC42EXT": (0x3FFFFFF, 0xFFFF),
        "SAMSUNG": (0xFF, 0xFF),
        "RC5": (0x1F, 0x3F), "RC5X": (0x1F, 0x7F),
        "RC6": (0xFF, 0xFF), "SONY": (0x1FFF, 0x7F),
        "PIONEER": (0xFF, 0xFF),
    }
    max_address, max_command = limits[protocol_id]
    if address > max_address or command > max_command:
        raise LibraryError(f"UNSUPPORTED_PARSED_FIELDS: {protocol}")
    return {"protocol": protocol_id, "address": address, "command": command, "bits": bits}


def send_parameters(signal: dict[str, str]) -> dict:
    """Return a firmware command for a validated parsed or raw catalogue entry."""
    if signal.get("type") == "parsed":
        return {"mode": "parsed", **_parsed_parameters(signal)}
    return {"mode": "raw", **raw_parameters(signal)}


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
    """Preflight a raw waveform against the CYD raw transmitter limits."""
    if signal.get("type") != "raw":
        raise LibraryError("PARSED_PROTOCOL_NOT_SUPPORTED: record needs protocol encoding")
    try:
        frequency = int(signal["frequency"])
        duty = float(signal["duty_cycle"])
        raw = [int(value) for value in signal["data"].split()]
    except (KeyError, ValueError) as err:
        raise LibraryError("INVALID_RAW_RECORD") from err
    if not 30000 <= frequency <= 60000:
        raise LibraryError("UNSUPPORTED_FREQUENCY: CYD supports 30 to 60 kHz")
    if not 0.2 <= duty <= 0.5:
        raise LibraryError("UNSUPPORTED_DUTY_CYCLE: CYD supports 20% to 50%")
    if not 2 <= len(raw) <= 500:
        raise LibraryError(f"RAW_LENGTH_NOT_SUPPORTED: {len(raw)} timings; CYD maximum is 500")
    if any(value < 100 or (index % 2 == 0 and value > 65535)
           or (index % 2 == 1 and value > 1_000_000)
           for index, value in enumerate(raw)):
        raise LibraryError("RAW_TIMING_NOT_SUPPORTED: marks 100–65535 us; spaces 100–1000000 us")
    return {"raw": raw, "frequency_khz": round(frequency / 1000), "duty_cycle": round(duty * 100)}


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
                parameters = send_parameters(signal)
                reason = None
            except LibraryError as err:
                parameters = None
                reason = str(err)
            result["signals"].append({
                "index": item["ordinal"], "name": signal.get("name", ""),
                "format": signal.get("type"), "protocol": signal.get("protocol"),
                "send_mode": parameters["mode"] if parameters else None,
                "cyd_sendable": reason is None,
                "limitation": reason,
            })
        return result

    def signal(self, profile_id: str, index: int):
        with closing(self._connect()) as db:
            row = db.execute("SELECT data FROM signals WHERE profile_id = ? AND ordinal = ?", (profile_id, index)).fetchone()
        if row is None:
            raise LibraryError("UNKNOWN_SIGNAL")
        return json.loads(zlib.decompress(row[0]))
