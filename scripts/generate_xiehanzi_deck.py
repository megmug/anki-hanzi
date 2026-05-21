#!/usr/bin/env python

"""
Build the customized xiehanzi APKG from the enriched JSON database.

The generator reads word/card data from
`master_db_output/cc_cedict_xiehanzi_enriched.json` and uses the shared deck
build helpers in `scripts/deck_build_common.py` for templates, media, and stable
Anki ids.

`deck_inputs/deck_config.json` controls which enriched xiehanzi study targets
are emitted as notes. This first config layer selects target words only; card
types are still the fixed Meaning, Pinyin, and Write set.

Run from the repository root inside the Nix shell:

    nix-shell --run "python scripts/generate_xiehanzi_deck.py"
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

import deck_build_common as common


DEFAULT_ENRICHED_DB = Path("master_db_output/cc_cedict_xiehanzi_enriched.json")
DEFAULT_DECK_CONFIG = Path("deck_inputs/deck_config.json")
DEFAULT_OUTPUT_APKG = common.OUTPUT_APKG
DEFAULT_REPORT_PATH = Path("build_reports/generate_xiehanzi_report.json")
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


@dataclass(frozen=True)
class DeckSelection:
    hsk_levels: tuple[str, ...]
    additional_simplified: frozenset[str]
    include_all_extra: bool
    config_path: str | None
    config_found: bool

    def report(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "config_found": self.config_found,
            "hsk_levels": list(self.hsk_levels),
            "additional_simplified": sorted(self.additional_simplified),
            "include_all_extra": self.include_all_extra,
        }


def normalize_simplified(value: Any) -> str:
    return str(value or "").strip()


def parse_hsk_levels(raw_levels: Any) -> tuple[str, ...]:
    if raw_levels is None or raw_levels == "all":
        return tuple(common.LEVELS)

    if isinstance(raw_levels, str):
        raw_levels = [raw_levels]

    if not isinstance(raw_levels, list):
        raise ValueError("deck config selection.hsk_levels must be \"all\" or a list")

    levels: list[str] = []
    for raw_level in raw_levels:
        level = str(raw_level).strip()
        if level == "all":
            return tuple(common.LEVELS)
        if level not in common.LEVELS:
            raise ValueError(f"unknown HSK level in deck config: {level}")
        if level not in levels:
            levels.append(level)

    return tuple(levels)


def parse_simplified_list(value: Any, field_name: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, list):
        raise ValueError(f"deck config selection.{field_name} must be a list")
    return frozenset(
        simplified
        for simplified in (normalize_simplified(item) for item in value)
        if simplified
    )


def load_deck_selection(config_path: Path | None) -> DeckSelection:
    if config_path is None or not config_path.exists():
        return DeckSelection(
            hsk_levels=tuple(common.LEVELS),
            additional_simplified=frozenset(),
            include_all_extra=True,
            config_path=str(config_path) if config_path is not None else None,
            config_found=False,
        )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    selection = config.get("selection", config)
    if not isinstance(selection, dict):
        raise ValueError("deck config selection must be an object")

    return DeckSelection(
        hsk_levels=parse_hsk_levels(selection.get("hsk_levels", "all")),
        additional_simplified=parse_simplified_list(
            selection.get("additional_simplified", []),
            "additional_simplified",
        ),
        include_all_extra=bool(selection.get("include_all_extra", False)),
        config_path=str(config_path),
        config_found=True,
    )


def should_include_target(simplified: str, deck_level: str, selection: DeckSelection) -> bool:
    if deck_level in selection.hsk_levels:
        return True
    if simplified in selection.additional_simplified:
        return True
    return deck_level == "Extra" and selection.include_all_extra


def build_decks(
    models: dict[str, genanki.Model],
    hsk_entries: dict[str, list[EnrichedWordEntry]],
    extra_entries: list[EnrichedWordEntry],
) -> list[genanki.Deck]:
    decks: list[genanki.Deck] = []

    for level in common.LEVELS:
        entries = hsk_entries[level]
        if not entries:
            continue
        for card_type in common.CARD_TYPES:
            decks.append(
                common.create_deck(
                    deck_name=f"{common.DECK_ROOT}::HSK {level}::{card_type}",
                    model=models[card_type],
                    entries=entries,
                )
            )

    if extra_entries:
        for card_type in common.CARD_TYPES:
            decks.append(
                common.create_deck(
                    deck_name=f"{common.DECK_ROOT}::Extra::{card_type}",
                    model=models[card_type],
                    entries=extra_entries,
                )
            )

    return decks


def load_enriched_entries(
    enriched_db_path: Path,
    selection: DeckSelection,
) -> tuple[dict[str, list[EnrichedWordEntry]], list[EnrichedWordEntry], dict[str, Any], dict[str, Any]]:
    database = json.loads(enriched_db_path.read_text(encoding="utf-8"))
    by_level: dict[str, list[EnrichedWordEntry]] = {level: [] for level in common.LEVELS}
    extra_entries: list[EnrichedWordEntry] = []
    matched_additional_simplified: set[str] = set()
    skipped_targets = 0

    for word in database.get("words", []):
        simplified = normalize_simplified(word["simplified"])
        xiehanzi = word.get("xiehanzi") or {}
        frequency = xiehanzi.get("frequency")
        form_entries = [
            (form, raw_entry)
            for form in word.get("forms", [])
            for raw_entry in (
                (form.get("xiehanzi") or {}).get("study_targets")
                or (form.get("xiehanzi") or {}).get("deck_entries", [])
            )
        ]
        raw_entries = form_entries or [
            (None, raw_entry)
            for raw_entry in (xiehanzi.get("study_targets", []) or xiehanzi.get("deck_entries", []))
        ]

        for form, raw_entry in raw_entries:
            deck_level = str(raw_entry["deck_level"])
            if not should_include_target(simplified, deck_level, selection):
                skipped_targets += 1
                continue

            if simplified in selection.additional_simplified:
                matched_additional_simplified.add(simplified)

            traditional = raw_entry.get("traditional")
            if traditional is None:
                variants = []
                if form is not None:
                    variants = form.get("traditional_variants") or []
                if not variants:
                    variants = word.get("traditional_variants") or []
                traditional = variants[0] if variants else simplified

            entry = EnrichedWordEntry(
                simplified=simplified,
                traditional=str(traditional),
                pinyin=str(raw_entry["pinyin"]),
                zhuyin=str(raw_entry["zhuyin"]),
                level=str(raw_entry["raw_level"]),
                pos=str(raw_entry["pos"]),
                frequency="" if frequency is None else str(frequency),
                definition_html=str(raw_entry["meaning_html"]),
                source="Extra" if deck_level == "Extra" else f"HSK {deck_level}",
                audio_filename=f"cmn-{simplified}.mp3",
                deck_order=int(raw_entry["deck_order"]),
            )

            if deck_level == "Extra":
                extra_entries.append(entry)
            else:
                by_level[deck_level].append(entry)

    for entries in [*by_level.values(), extra_entries]:
        entries.sort(key=lambda entry: entry.deck_order)

    selection_report = {
        **selection.report(),
        "matched_additional_simplified": sorted(matched_additional_simplified),
        "unmatched_additional_simplified": sorted(
            selection.additional_simplified - matched_additional_simplified
        ),
        "skipped_study_targets": skipped_targets,
    }

    return by_level, extra_entries, database, selection_report


def find_audio_path(entry: EnrichedWordEntry) -> Path | None:
    candidates = [
        common.AUDIO_DIR / entry.audio_filename,
        common.EXTRA_AUDIO_DIR / entry.audio_filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def generated_audio_path(entry: EnrichedWordEntry) -> Path:
    return common.EXTRA_AUDIO_DIR / entry.audio_filename


def generate_missing_audio(entries: list[EnrichedWordEntry]) -> tuple[list[str], list[dict[str, str]], list[str]]:
    removed_zero_length = common.remove_zero_length_audio_files()
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
            communicate = edge_tts.Communicate(entry.simplified.strip(), common.VOICE)
            communicate.save_sync(str(output_path))
            if output_path.exists() and output_path.stat().st_size > 0:
                generated.append(str(output_path))
            else:
                common.remove_failed_audio_output(output_path)
                failed.append({
                    "word": entry.simplified,
                    "file": str(output_path),
                    "error": "edge-tts produced no audio data",
                })
        except Exception as exc:
            common.remove_failed_audio_output(output_path)
            failed.append({
                "word": entry.simplified,
                "file": str(output_path),
                "error": str(exc),
            })

    return generated, failed, removed_zero_length


def collect_media(entries: list[EnrichedWordEntry]) -> tuple[list[str], list[str]]:
    media = list(common.STATIC_MEDIA)
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
    deck_config: Path | None,
    output_apkg: Path,
    report_path: Path,
    timestamp: float | None,
    deterministic_zip: bool,
    zip_generated_datetime: tuple[int, int, int, int, int, int] | None,
) -> dict[str, Any]:
    selection = load_deck_selection(deck_config)
    hsk_entries, extra_entries, database, selection_report = load_enriched_entries(enriched_db, selection)
    all_entries = [entry for level in common.LEVELS for entry in hsk_entries[level]] + extra_entries

    generated_audio, failed_audio_generation, removed_zero_length_audio = generate_missing_audio(all_entries)
    models = common.create_models()
    decks = build_decks(models, hsk_entries, extra_entries)
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
        "deck_config": selection_report,
        "source_schema": database.get("schema"),
        "deck_root": common.DECK_ROOT,
        "card_types": common.CARD_TYPES,
        "dedupe_key": database.get("enrichment", {}).get("dedupe_key"),
        "hsk_words_after_dedupe": sum(len(hsk_entries[level]) for level in common.LEVELS),
        "extra_words": len(extra_entries),
        "total_words": len(all_entries),
        "total_cards": len(all_entries) * len(common.CARD_TYPES),
        "decks": len(decks),
        "audio_files_packaged": len(media_files) - len(common.STATIC_MEDIA),
        "audio_voice": common.VOICE,
        "hanzi_writer_version": common.read_hanzi_writer_package_version(),
        "hanzi_writer_bundle": str(common.HANZI_WRITER_BUNDLE),
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
        "hsk_counts": {level: len(hsk_entries[level]) for level in common.LEVELS},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enriched-db", type=Path, default=DEFAULT_ENRICHED_DB, help="Input enriched JSON database.")
    parser.add_argument("--config", type=Path, default=DEFAULT_DECK_CONFIG, help="Deck selection JSON config.")
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
        deck_config=args.config,
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
