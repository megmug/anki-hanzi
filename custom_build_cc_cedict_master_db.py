#!/usr/bin/env python3
"""
Build a pinned CC-CEDICT master JSON database.

This is a prototype importer for the longer-term data pipeline:

    pinned CC-CEDICT zip -> master JSON -> enrichment overlays -> deck generator

The output is intentionally a compact lexical projection. It can be rebuilt from
the pinned source zip, so it avoids storing raw source lines and other debug
provenance that is not needed by the deck generator.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_CEDICT_URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip"
DEFAULT_CEDICT_SHA256 = "5ae885402b7873dea15f3f905bd4ac0e078d9cf68ddd873f0065fd7119154856"
DEFAULT_SOURCE_ZIP = Path("master_db_output/sources/cedict_1_0_ts_utf-8_mdbg.zip")
DEFAULT_OUTPUT = Path("master_db_output/cc_cedict_master.json")
EXPECTED_ZIP_MEMBER = "cedict_ts.u8"

LINE_RE = re.compile(r"^(?P<traditional>\S+)\s+(?P<simplified>\S+)\s+\[(?P<pinyin>.+?)\]\s+/(?P<definitions>.*)/$")


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pinyin(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def split_definitions(definitions_blob: str) -> list[str]:
    return [part.strip() for part in definitions_blob.split("/") if part.strip()]


def build_lexical_words(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_words: dict[str, dict[str, Any]] = {}

    for entry in entries:
        simplified = entry["simplified"]
        word = grouped_words.get(simplified)
        if word is None:
            word = {
                "simplified": simplified,
                "traditional_variants": [],
                "forms": {},
                "tags": ["source:cc-cedict"],
            }
            grouped_words[simplified] = word

        if entry["traditional"] not in word["traditional_variants"]:
            word["traditional_variants"].append(entry["traditional"])

        form_key = entry["pinyin"]
        form = word["forms"].get(form_key)
        if form is None:
            form = {
                "traditional_variants": [],
                "pinyin": entry["pinyin"],
                "definitions": [],
                "tags": ["source:cc-cedict"],
            }
            word["forms"][form_key] = form

        if entry["traditional"] not in form["traditional_variants"]:
            form["traditional_variants"].append(entry["traditional"])

        append_definitions(form["definitions"], entry)

    words: list[dict[str, Any]] = []
    for word in grouped_words.values():
        forms = list(word.pop("forms").values())
        forms.sort(key=lambda form: form["pinyin"])
        word["forms"] = forms
        words.append(word)

    words.sort(key=lambda word: word["simplified"])
    return words


def append_definitions(target: list[str], entry: dict[str, Any]) -> None:
    seen = set(target)
    for definition in entry["definitions"]:
        if definition in seen:
            continue
        target.append(definition)
        seen.add(definition)


def parse_cedict_text(text: str) -> tuple[list[str], list[dict[str, Any]], int]:
    comments: list[str] = []
    entries: list[dict[str, Any]] = []
    rejected_count = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            comments.append(line)
            continue

        match = LINE_RE.match(line)
        if not match:
            rejected_count += 1
            continue

        definitions = split_definitions(match.group("definitions"))
        pinyin = parse_pinyin(match.group("pinyin"))
        traditional = match.group("traditional")
        simplified = match.group("simplified")

        entries.append(
            {
                "traditional": traditional,
                "simplified": simplified,
                "pinyin": pinyin,
                "definitions": definitions,
                "tags": ["source:cc-cedict"],
            }
        )

    return comments, entries, rejected_count


def download_if_needed(url: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        return
    with urllib.request.urlopen(url) as response:
        output.write_bytes(response.read())


def read_cedict_member(zip_path: Path, member_name: str) -> tuple[str, dict[str, Any]]:
    with zipfile.ZipFile(zip_path) as archive:
        info = archive.getinfo(member_name)
        raw = archive.read(member_name)

    member_metadata = {
        "name": member_name,
        "uncompressed_size": info.file_size,
        "compressed_size": info.compress_size,
        "zip_timestamp": "%04d-%02d-%02dT%02d:%02d:%02d" % info.date_time,
    }
    return raw.decode("utf-8-sig"), member_metadata


def build_database(source_zip: Path, url: str, expected_sha256: str, output_path: Path) -> dict[str, Any]:
    actual_sha256 = sha256_file(source_zip)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"CC-CEDICT zip hash mismatch: expected {expected_sha256}, got {actual_sha256}. "
            "Update the pin intentionally if this is a new desired snapshot."
        )

    text, member_metadata = read_cedict_member(source_zip, EXPECTED_ZIP_MEMBER)
    comments, entries, rejected_count = parse_cedict_text(text)
    words = build_lexical_words(entries)
    forms_count = sum(len(word["forms"]) for word in words)

    database = {
        "schema": "xiehanzi-master-lexicon-cc-cedict-v2",
        "source": {
            "name": "CC-CEDICT",
            "url": url,
            "zip_sha256": actual_sha256,
            "zip_path": str(source_zip),
            "zip_member": member_metadata,
            "comment_header": comments,
        },
        "summary": {
            "entries": len(entries),
            "words": len(words),
            "forms": forms_count,
            "comments": len(comments),
            "rejected_lines": rejected_count,
            "words_with_multiple_forms": sum(1 for word in words if len(word["forms"]) > 1),
            "max_forms_per_word": max((len(word["forms"]) for word in words), default=0),
        },
        "words": words,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(database, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_CEDICT_URL, help="CC-CEDICT zip URL to download.")
    parser.add_argument("--source-zip", type=Path, default=DEFAULT_SOURCE_ZIP, help="Pinned CC-CEDICT zip path.")
    parser.add_argument("--sha256", default=DEFAULT_CEDICT_SHA256, help="Expected SHA256 for the pinned zip.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output master JSON path.")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Do not download; fail if --source-zip does not already exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.no_download:
        download_if_needed(args.url, args.source_zip)
    if not args.source_zip.exists():
        print(f"missing source zip: {args.source_zip}", file=sys.stderr)
        return 2

    database = build_database(
        source_zip=args.source_zip,
        url=args.url,
        expected_sha256=args.sha256,
        output_path=args.output,
    )
    print("CC-CEDICT master JSON generated")
    print(f"source zip: {args.source_zip}")
    print(f"output: {args.output}")
    print(json.dumps(database["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
