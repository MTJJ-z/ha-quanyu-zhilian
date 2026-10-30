"""Package only deployable integration sources and installation instructions."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parent
component = root / "custom_components" / "quanyu_zhilian"
version = json.loads((component / "manifest.json").read_text(encoding="utf-8"))["version"]
destination = root / "dist" / f"quanyu_zhilian-{version}.zip"
destination.parent.mkdir(exist_ok=True)
with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for source in sorted(component.rglob("*")):
        if source.is_file() and (source.suffix in (".py", ".js", ".json", ".yaml", ".sqlite3", ".md") or source.name == "FLIPPER_IRDB_LICENSE"):
            archive.write(source, source.relative_to(root).as_posix())
    archive.write(root / "README.md", "README.md")
    archive.write(root / "docs" / "COMPONENT_PROTOCOL.md", "docs/COMPONENT_PROTOCOL.md")
    archive.write(root / "docs" / "OFFLINE_IR_LIBRARY.md", "docs/OFFLINE_IR_LIBRARY.md")
digest = hashlib.sha256(destination.read_bytes()).hexdigest()
destination.with_suffix(".sha256").write_text(
    f"{digest}  {destination.name}\n", encoding="utf-8"
)
print(destination)
print(f"SHA256 {digest}")

# HACS extracts a release asset directly into custom_components/<domain>.
# Its ZIP must therefore contain manifest.json at the root, not custom_components/.
hacs_destination = destination.parent / "quanyu_zhilian.zip"
with ZipFile(hacs_destination, "w", ZIP_DEFLATED) as archive:
    for source in sorted(component.rglob("*")):
        if source.is_file() and (source.suffix in (".py", ".js", ".json", ".yaml", ".sqlite3", ".md") or source.name == "FLIPPER_IRDB_LICENSE"):
            archive.write(source, source.relative_to(component).as_posix())
hacs_digest = hashlib.sha256(hacs_destination.read_bytes()).hexdigest()
hacs_destination.with_suffix(".sha256").write_text(
    f"{hacs_digest}  {hacs_destination.name}\n", encoding="utf-8"
)
print(f"HACS {hacs_destination}")
