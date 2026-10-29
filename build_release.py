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
        if source.is_file() and source.suffix in (".py", ".json", ".yaml"):
            archive.write(source, source.relative_to(root).as_posix())
    archive.write(root / "README.md", "README.md")
    archive.write(root / "docs" / "COMPONENT_PROTOCOL.md", "docs/COMPONENT_PROTOCOL.md")
digest = hashlib.sha256(destination.read_bytes()).hexdigest()
destination.with_suffix(".sha256").write_text(
    f"{digest}  {destination.name}\n", encoding="utf-8"
)
print(destination)
print(f"SHA256 {digest}")
