#!/usr/bin/env python3
"""
Update the vendored CC-CEDICT snapshot.

Usage:

    python scripts/update_cc_cedict_snapshot.py

The normal build is intentionally offline and reads the committed text snapshot
from deck_inputs/cc-cedict. This script downloads the latest archive from the
stable MDBG export URL, validates its structure, extracts the CC-CEDICT text
member, and refreshes the vendored text file, manifest, and README.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_SOURCE_URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip"
DEFAULT_VENDOR_DIR = Path("deck_inputs/cc-cedict")
DEFAULT_VENDOR_TEXT = DEFAULT_VENDOR_DIR / "cedict_ts.u8"
DEFAULT_MANIFEST = DEFAULT_VENDOR_DIR / "snapshot.json"
DEFAULT_README = DEFAULT_VENDOR_DIR / "README.md"
EXPECTED_MEMBER = "cedict_ts.u8"

HEADER_RE = re.compile(r"^#!\s*([^=\s]+)=(.*)$")


def read_snapshot_text(zip_path: Path) -> tuple[bytes, dict[str, str], dict[str, Any]]:
    with zipfile.ZipFile(zip_path) as archive:
        info = archive.getinfo(EXPECTED_MEMBER)
        raw = archive.read(EXPECTED_MEMBER)

    header: dict[str, str] = {}
    for line in raw.decode("utf-8-sig").splitlines():
        if not line.startswith("#"):
            break
        match = HEADER_RE.match(line.strip())
        if match:
            header[match.group(1)] = match.group(2).strip()

    member = {
        "name": EXPECTED_MEMBER,
        "uncompressed_size": info.file_size,
        "compressed_size": info.compress_size,
        "zip_timestamp": "%04d-%02d-%02dT%02d:%02d:%02d" % info.date_time,
    }
    return raw, header, member


def build_manifest(source_text: bytes, header: dict[str, str], member: dict[str, Any], source_url: str) -> dict[str, Any]:
    return {
        "schema": "hanzi-cc-cedict-snapshot-v2",
        "source_url": source_url,
        "source_filename": DEFAULT_VENDOR_TEXT.name,
        "sha256": hashlib.sha256(source_text).hexdigest(),
        "cc_cedict_header": header,
        "upstream_zip_member": member,
    }


def download_snapshot(source_url: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(source_url) as response:
        output.write_bytes(response.read())


def render_readme(manifest: dict[str, Any]) -> str:
    header = manifest.get("cc_cedict_header", {})
    release_date = header.get("date", "unknown")
    entries = header.get("entries", "unknown")
    publisher = header.get("publisher", "CC-CEDICT/MDBG")
    license_name = header.get("license", "Creative Commons Attribution-ShareAlike 4.0 International")

    return f"""# CC-CEDICT Snapshot

This directory contains the pinned CC-CEDICT source snapshot used by the local
deck build.

The upstream MDBG export URL is mutable, so the build vendors the exact
CC-CEDICT text file needed for reproducible APKG generation instead of
downloading the latest file during `nix-build`.

To update the snapshot from the latest upstream export, run:

```sh
nix-shell --run "python scripts/update_cc_cedict_snapshot.py"
```

The update command downloads the current archive from the URL below, validates
it, extracts `{manifest["source_filename"]}`, and rewrites this directory. Then rebuild
and commit the changed snapshot, manifest, and reports if the new data is
intentional.

- Source URL: `{manifest["source_url"]}`
- Snapshot date from file header: `{release_date}`
- Entries from file header: `{entries}`
- Publisher from file header: `{publisher}`
- Snapshot file: `{manifest["source_filename"]}`
- Snapshot SHA256: `{manifest["sha256"]}`
- License: {license_name}
"""


def write_snapshot(source_text: bytes, manifest: dict[str, Any], dry_run: bool) -> None:
    if dry_run:
        return

    DEFAULT_VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_VENDOR_TEXT.write_bytes(source_text)
    DEFAULT_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    DEFAULT_README.write_text(render_readme(manifest), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source_zip",
        type=Path,
        nargs="?",
        help="Optional local CC-CEDICT ZIP archive. If omitted, download the latest upstream archive.",
    )
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL, help="Source URL recorded in the manifest.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report metadata without writing files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    source_zip = args.source_zip
    if source_zip is None:
        temp_dir = tempfile.TemporaryDirectory()
        source_zip = Path(temp_dir.name) / "cedict_1_0_ts_utf-8_mdbg.zip"
        download_snapshot(args.source_url, source_zip)
    elif not source_zip.exists():
        print(f"missing source zip: {source_zip}", file=sys.stderr)
        return 2

    try:
        source_text, header, member = read_snapshot_text(source_zip)
        manifest = build_manifest(source_text, header, member, args.source_url)
    except KeyError as error:
        print(f"invalid CC-CEDICT archive: missing {error}", file=sys.stderr)
        if temp_dir is not None:
            temp_dir.cleanup()
        return 2
    except zipfile.BadZipFile:
        print(f"invalid zip archive: {source_zip}", file=sys.stderr)
        if temp_dir is not None:
            temp_dir.cleanup()
        return 2

    write_snapshot(source_text, manifest, args.dry_run)
    if temp_dir is not None:
        temp_dir.cleanup()
    action = "validated" if args.dry_run else "updated"
    print(f"CC-CEDICT snapshot {action}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
