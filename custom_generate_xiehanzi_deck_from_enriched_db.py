#!/usr/bin/env python

"""
Build the customized xiehanzi APKG from the enriched JSON database.

This is a reproduction generator. It should produce the same deck content as
`custom_generate_xiehanzi_deck.py`, but it must read word/card data only from
`master_db_output/cc_cedict_xiehanzi_enriched.json`.

The older TSV-based generator intentionally remains unchanged as the reference
implementation until this generator can reproduce it.

Run from the repository root inside the Nix shell:

    nix-shell --run "python custom_generate_xiehanzi_deck_from_enriched_db.py"
"""

from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import edge_tts
import genanki

import custom_generate_xiehanzi_deck as reference


DEFAULT_ENRICHED_DB = Path("master_db_output/cc_cedict_xiehanzi_enriched.json")
DEFAULT_OUTPUT_APKG = Path("Anki-xiehanzi - New HSK (2025) from enriched.apkg")
DEFAULT_REPORT_PATH = Path("custom_generate_xiehanzi_from_enriched_report.json")
DEFAULT_GENANKI_TIMESTAMP = 1779251987.6
DEFAULT_GENERATED_ZIP_DATETIME = (2026, 5, 20, 6, 39, 48)
DEFAULT_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)
GENERATED_ZIP_MEMBERS = {"collection.anki2", "media"}


@dataclass(frozen=True)
class EnrichedWordEntry:
    simplified: str
    traditional: str
    pinyin: str
    zhuyin: str
    level: str
    pos: str
    frequency: str
    definition_html: str
    source: str
    audio_filename: str
    deck_order: int

    @property
    def audio_ref(self) -> str:
        return f"[sound:{self.audio_filename}]"

    def fields(self) -> list[str]:
        return [
            self.simplified,
            self.traditional,
            self.pinyin,
            self.zhuyin,
            self.pos,
            self.definition_html,
            self.audio_ref,
        ]


def load_enriched_entries(enriched_db_path: Path) -> tuple[dict[str, list[EnrichedWordEntry]], list[EnrichedWordEntry], dict[str, Any]]:
    database = json.loads(enriched_db_path.read_text(encoding="utf-8"))
    by_level: dict[str, list[EnrichedWordEntry]] = {level: [] for level in reference.LEVELS}
    extra_entries: list[EnrichedWordEntry] = []

    for word in database.get("words", []):
        for raw_entry in (word.get("xiehanzi") or {}).get("deck_entries", []):
            entry = EnrichedWordEntry(
                simplified=str(raw_entry["simplified"]),
                traditional=str(raw_entry["traditional"]),
                pinyin=str(raw_entry["pinyin"]),
                zhuyin=str(raw_entry["zhuyin"]),
                level=str(raw_entry["raw_level"]),
                pos=str(raw_entry["pos"]),
                frequency="" if raw_entry.get("frequency") is None else str(raw_entry["frequency"]),
                definition_html=str(raw_entry["meaning_html"]),
                source=str(raw_entry["source"]),
                audio_filename=str(raw_entry["audio_filename"]),
                deck_order=int(raw_entry["deck_order"]),
            )

            if raw_entry["deck_level"] == "Extra":
                extra_entries.append(entry)
            else:
                by_level[str(raw_entry["deck_level"])].append(entry)

    for entries in [*by_level.values(), extra_entries]:
        entries.sort(key=lambda entry: entry.deck_order)

    return by_level, extra_entries, database


def find_audio_path(entry: EnrichedWordEntry) -> Path | None:
    candidates = [
        reference.AUDIO_DIR / entry.audio_filename,
        reference.EXTRA_AUDIO_DIR / entry.audio_filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def generated_audio_path(entry: EnrichedWordEntry) -> Path:
    return reference.EXTRA_AUDIO_DIR / entry.audio_filename


def generate_missing_audio(entries: list[EnrichedWordEntry]) -> tuple[list[str], list[dict[str, str]], list[str]]:
    removed_zero_length = reference.remove_zero_length_audio_files()
    generated: list[str] = []
    failed: list[dict[str, str]] = []
    seen_filenames: set[str] = set()

    for entry in entries:
        if find_audio_path(entry):
            continue
        if not entry.simplified.strip() or entry.audio_filename in seen_filenames:
            continue
        seen_filenames.add(entry.audio_filename)

        output_path = generated_audio_path(entry)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            communicate = edge_tts.Communicate(entry.simplified.strip(), reference.VOICE)
            communicate.save_sync(str(output_path))
            if output_path.exists() and output_path.stat().st_size > 0:
                generated.append(str(output_path))
            else:
                failed.append({
                    "word": entry.simplified,
                    "file": str(output_path),
                    "error": "edge-tts produced no audio data",
                })
        except Exception as exc:
            failed.append({
                "word": entry.simplified,
                "file": str(output_path),
                "error": str(exc),
            })

    return generated, failed, removed_zero_length


def collect_media(entries: list[EnrichedWordEntry]) -> tuple[list[str], list[str]]:
    media = list(reference.STATIC_MEDIA)
    missing_audio: list[str] = []
    seen_media_names = {Path(path).name for path in media}

    for entry in entries:
        audio_path = find_audio_path(entry)
        if audio_path:
            media_name = audio_path.name
            if media_name not in seen_media_names:
                seen_media_names.add(media_name)
                media.append(str(audio_path))
        else:
            missing_audio.append(entry.audio_filename)

    return media, sorted(set(missing_audio))


def copy_zip_info(reference_info: zipfile.ZipInfo, filename: str | None = None) -> zipfile.ZipInfo:
    output_info = zipfile.ZipInfo(filename or reference_info.filename, reference_info.date_time)
    output_info.compress_type = reference_info.compress_type
    output_info.external_attr = reference_info.external_attr
    output_info.internal_attr = reference_info.internal_attr
    output_info.comment = reference_info.comment
    output_info.extra = reference_info.extra
    output_info.create_system = reference_info.create_system
    return output_info


def normalize_zip_file(source: Path, output: Path, zip_datetime: tuple[int, int, int, int, int, int]) -> None:
    with zipfile.ZipFile(source) as source_zip, zipfile.ZipFile(output, "w") as output_zip:
        for info in source_zip.infolist():
            data = source_zip.read(info.filename)
            output_info = copy_zip_info(info)
            output_info.date_time = zip_datetime
            output_info.extra = b""
            output_zip.writestr(output_info, data)


def rewrite_generated_zip_datetimes(
    source: Path,
    output: Path,
    generated_datetime: tuple[int, int, int, int, int, int],
) -> None:
    with zipfile.ZipFile(source) as source_zip, zipfile.ZipFile(output, "w") as output_zip:
        for info in source_zip.infolist():
            data = source_zip.read(info.filename)
            output_info = copy_zip_info(info)
            if info.filename in GENERATED_ZIP_MEMBERS:
                output_info.date_time = generated_datetime
            output_zip.writestr(output_info, data)


def parse_zip_datetime(value: str) -> tuple[int, int, int, int, int, int]:
    try:
        date_part, time_part = value.replace("T", " ").split()
        year, month, day = (int(part) for part in date_part.split("-"))
        hour, minute, second = (int(part) for part in time_part.split(":"))
    except Exception as exc:
        raise argparse.ArgumentTypeError(
            "Expected datetime in YYYY-MM-DDTHH:MM:SS format"
        ) from exc
    return year, month, day, hour, minute, second


def write_package(
    package: genanki.Package,
    output_apkg: Path,
    timestamp: float | None,
    deterministic_zip: bool,
    zip_generated_datetime: tuple[int, int, int, int, int, int] | None,
) -> None:
    if zip_generated_datetime is None and not deterministic_zip:
        if timestamp is None:
            package.write_to_file(str(output_apkg))
        else:
            package.write_to_file(str(output_apkg), timestamp=timestamp)
        return

    with tempfile.NamedTemporaryFile(suffix=".apkg", delete=False) as handle:
        temporary_path = Path(handle.name)

    try:
        if timestamp is None:
            package.write_to_file(str(temporary_path))
        else:
            package.write_to_file(str(temporary_path), timestamp=timestamp)

        if zip_generated_datetime is not None:
            rewrite_generated_zip_datetimes(
                source=temporary_path,
                output=output_apkg,
                generated_datetime=zip_generated_datetime,
            )
        else:
            normalize_zip_file(temporary_path, output_apkg, DEFAULT_ZIP_DATETIME)
    finally:
        temporary_path.unlink(missing_ok=True)


def build_package(
    enriched_db: Path,
    output_apkg: Path,
    report_path: Path,
    timestamp: float | None,
    deterministic_zip: bool,
    zip_generated_datetime: tuple[int, int, int, int, int, int] | None,
) -> dict[str, Any]:
    hsk_entries, extra_entries, database = load_enriched_entries(enriched_db)
    all_entries = [entry for level in reference.LEVELS for entry in hsk_entries[level]] + extra_entries

    generated_audio, failed_audio_generation, removed_zero_length_audio = generate_missing_audio(all_entries)
    models = reference.create_models()
    decks = reference.build_decks(models, hsk_entries, extra_entries)
    media_files, missing_audio = collect_media(all_entries)

    package = genanki.Package(decks, media_files=media_files)
    write_package(
        package=package,
        output_apkg=output_apkg,
        timestamp=timestamp,
        deterministic_zip=deterministic_zip,
        zip_generated_datetime=zip_generated_datetime,
    )

    report = {
        "output": str(output_apkg),
        "report": str(report_path),
        "enriched_db": str(enriched_db),
        "source_schema": database.get("schema"),
        "deck_root": reference.DECK_ROOT,
        "card_types": reference.CARD_TYPES,
        "dedupe_key": database.get("enrichment", {}).get("dedupe_key"),
        "hsk_words_after_dedupe": sum(len(hsk_entries[level]) for level in reference.LEVELS),
        "extra_words": len(extra_entries),
        "total_words": len(all_entries),
        "total_cards": len(all_entries) * len(reference.CARD_TYPES),
        "decks": len(decks),
        "audio_files_packaged": len(media_files) - len(reference.STATIC_MEDIA),
        "audio_voice": reference.VOICE,
        "hanzi_writer_version": reference.read_hanzi_writer_package_version(),
        "hanzi_writer_bundle": str(reference.HANZI_WRITER_BUNDLE),
        "timestamp": timestamp,
        "deterministic_zip": deterministic_zip,
        "zip_datetime": DEFAULT_ZIP_DATETIME if deterministic_zip and zip_generated_datetime is None else None,
        "zip_generated_datetime": zip_generated_datetime,
        "generated_audio_files": generated_audio,
        "failed_audio_generation": failed_audio_generation,
        "removed_zero_length_audio_files": removed_zero_length_audio,
        "dropped_duplicate_occurrences": len(database.get("xiehanzi", {}).get("dropped_duplicates", [])),
        "dropped_duplicates": database.get("xiehanzi", {}).get("dropped_duplicates", []),
        "skipped_extra_duplicate_occurrences": len(database.get("xiehanzi", {}).get("skipped_extra_duplicates", [])),
        "skipped_extra_duplicates": database.get("xiehanzi", {}).get("skipped_extra_duplicates", []),
        "missing_audio_files": missing_audio,
        "hsk_counts": {level: len(hsk_entries[level]) for level in reference.LEVELS},
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enriched-db", type=Path, default=DEFAULT_ENRICHED_DB, help="Input enriched JSON database.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_APKG, help="Output APKG path.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH, help="Output report JSON path.")
    parser.add_argument(
        "--timestamp",
        type=float,
        default=DEFAULT_GENANKI_TIMESTAMP,
        help="Fixed genanki timestamp for hermetic builds.",
    )
    parser.add_argument(
        "--deterministic-zip",
        action="store_true",
        help="Rewrite the APKG zip with fixed member timestamps for byte-reproducible output.",
    )
    parser.add_argument(
        "--zip-generated-datetime",
        type=parse_zip_datetime,
        default=DEFAULT_GENERATED_ZIP_DATETIME,
        help="Set ZIP timestamps for generated members collection.anki2 and media. Format: YYYY-MM-DDTHH:MM:SS.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.enriched_db.exists():
        print(f"missing enriched DB: {args.enriched_db}")
        return 2

    report = build_package(
        enriched_db=args.enriched_db,
        output_apkg=args.output,
        report_path=args.report,
        timestamp=args.timestamp,
        deterministic_zip=args.deterministic_zip,
        zip_generated_datetime=args.zip_generated_datetime,
    )
    console_report = {
        key: value
        for key, value in report.items()
        if key not in {"dropped_duplicates", "skipped_extra_duplicates"}
    }
    print(json.dumps(console_report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
