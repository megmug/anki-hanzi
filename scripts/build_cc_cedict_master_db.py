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
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_SNAPSHOT_MANIFEST = Path("deck_inputs/cc-cedict/snapshot.json")
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


def load_snapshot_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing snapshot manifest: {path}")

    manifest = json.loads(path.read_text(encoding="utf-8"))
    missing_fields = [
        field
        for field in ["archive_filename", "sha256", "source_url"]
        if not manifest.get(field)
    ]
    if missing_fields:
        raise ValueError(f"snapshot manifest is missing required fields: {', '.join(missing_fields)}")
    return manifest


def resolve_source_zip(manifest_path: Path, manifest: dict[str, Any], override: Path | None) -> Path:
    if override is not None:
        return override
    return manifest_path.parent / manifest["archive_filename"]


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
        "schema": "hanzi-master-lexicon-cc-cedict-v2",
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
    parser.add_argument(
        "--snapshot-manifest",
        type=Path,
        default=DEFAULT_SNAPSHOT_MANIFEST,
        help="Snapshot manifest with the pinned source filename, SHA256, and source URL.",
    )
    parser.add_argument("--source-zip", type=Path, default=None, help="Optional pinned CC-CEDICT zip override.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output master JSON path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = load_snapshot_manifest(args.snapshot_manifest)
    except (FileNotFoundError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2

    source_zip = resolve_source_zip(args.snapshot_manifest, manifest, args.source_zip)
    if not source_zip.exists():
        print(f"missing source zip: {source_zip}", file=sys.stderr)
        return 2

    database = build_database(
        source_zip=source_zip,
        url=manifest["source_url"],
        expected_sha256=manifest["sha256"],
        output_path=args.output,
    )
    print("CC-CEDICT master JSON generated")
    print(f"source zip: {source_zip}")
    print(f"output: {args.output}")
    print(json.dumps(database["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
