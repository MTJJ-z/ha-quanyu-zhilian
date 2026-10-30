"""Build the full offline catalogue from an explicitly supplied local IRDB checkout."""

import argparse
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPONENT = ROOT / "custom_components" / "quanyu_zhilian"
spec = importlib.util.spec_from_file_location("ir_library", COMPONENT / "ir_library.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def build(source: Path, destination: Path):
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_suffix(".building")
    staging.unlink(missing_ok=True)
    problems = []
    count = signals = 0
    with sqlite3.connect(staging) as db:
        db.executescript("""
            CREATE TABLE profiles(id TEXT PRIMARY KEY, category TEXT, brand TEXT, model TEXT,
                path TEXT UNIQUE, signal_count INTEGER, search_text TEXT, source_text TEXT);
            CREATE TABLE signals(profile_id TEXT, ordinal INTEGER, data TEXT,
                PRIMARY KEY(profile_id, ordinal));
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
        """)
        files = sorted(source.rglob("*.ir"))
        for path in files:
            relative = path.relative_to(source).as_posix()
            if ".git" in path.relative_to(source).parts:
                continue
            # Store original bytes as a BLOB, even when a file cannot be parsed.
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig", errors="replace")
            try:
                records = module.parse_flipper(text)
            except module.LibraryError as err:
                records = []
                problems.append({"path": relative, "error": str(err)})
            if not records:
                if not any(p["path"] == relative for p in problems):
                    problems.append({"path": relative, "error": "No named signals"})
            profile_id = hashlib.sha256(relative.encode()).hexdigest()[:24]
            parts = path.relative_to(source).parts
            category = parts[0] if len(parts) > 1 else "Other"
            brand = parts[1] if len(parts) > 2 else "Unknown"
            db.execute("INSERT INTO profiles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (profile_id, category, brand, path.stem, relative, len(records), relative, zlib.compress(raw)))
            db.executemany("INSERT INTO signals VALUES (?, ?, ?)",
                           [(profile_id, i, zlib.compress(json.dumps(record, ensure_ascii=False).encode())) for i, record in enumerate(records)])
            count += 1
            signals += len(records)
        metadata = {"repository": "https://github.com/Lucaslhm/Flipper-IRDB",
                    "revision": revision, "profiles": str(count), "signals": str(signals),
                    "unparsed_profiles": str(len(problems)), "format_version": "1-zlib"}
        db.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
        db.commit()
        db.execute("VACUUM")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Catalogue integrity check failed")
    db.close()
    staging.replace(destination)
    for name in ("LICENSE", "README.md"):
        shutil.copyfile(source / name, destination.parent / ("FLIPPER_IRDB_" + name))
    (destination.parent / "ir_library_manifest.json").write_text(
        json.dumps({**metadata, "database_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                    "parse_issues": problems}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=COMPONENT / "data" / "ir_library.sqlite3")
    args = parser.parse_args()
    build(args.source, args.output)
