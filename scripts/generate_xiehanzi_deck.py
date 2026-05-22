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
from deck_build_common import DeckConfig, GroupDef
from dragonmapper import transcriptions
from meaning_html import numbered_to_xiehanzi_display, render_meaning_html


DEFAULT_ENRICHED_DB = Path("master_db_output/cc_cedict_xiehanzi_enriched.json")
DEFAULT_DECK_CONFIG = Path("deck_inputs/deck_config.json")
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
    definition_html: str
    audio_filename: str

    @property
    def audio_ref(self) -> str:
        return f"[sound:{self.audio_filename}]"

    def fields(self) -> list[str]:
        return [
            self.simplified,
            self.traditional,
            self.pinyin,
            self.zhuyin,
            "",
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


def parse_hsk_levels(raw_levels: Any, known_levels: tuple[str, ...]) -> tuple[str, ...]:
    if raw_levels is None or raw_levels == "all":
        return known_levels

    if isinstance(raw_levels, str):
        raw_levels = [raw_levels]

    if not isinstance(raw_levels, list):
        raise ValueError("deck config selection.hsk_levels must be \"all\" or a list")

    levels: list[str] = []
    for raw_level in raw_levels:
        level = str(raw_level).strip()
        if level == "all":
            return known_levels
        if level not in known_levels:
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


def _deck_levels_from_config(config: DeckConfig) -> tuple[str, ...]:
    levels: list[str] = []
    for group in config.groups:
        if group.tag_pattern.startswith("hsk:"):
            level = group.tag_pattern[len("hsk:"):]
            if level and level not in levels:
                levels.append(level)
    return tuple(levels)


def load_deck_selection(config_path: Path | None, config: DeckConfig) -> DeckSelection:
    known_levels = _deck_levels_from_config(config)

    if config_path is None or not config_path.exists():
        return DeckSelection(
            hsk_levels=known_levels,
            additional_simplified=frozenset(),
            include_all_extra=True,
            config_path=str(config_path) if config_path is not None else None,
            config_found=False,
        )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    selection = raw.get("selection", raw)
    if not isinstance(selection, dict):
        raise ValueError("deck config selection must be an object")

    return DeckSelection(
        hsk_levels=parse_hsk_levels(selection.get("hsk_levels", "all"), known_levels),
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
    return deck_level.lower() == "extra" and selection.include_all_extra


def build_decks(
    config: DeckConfig,
    models: dict[str, genanki.Model],
    group_entries: dict[str, list[EnrichedWordEntry]],
) -> list[genanki.Deck]:
    decks: list[genanki.Deck] = []

    for group in config.groups:
        entries = group_entries.get(group.tag_pattern, [])
        if not entries:
            continue
        for card_type in config.card_types:
            decks.append(
                common.create_deck(
                    deck_name=config.resolve_deck_name(group.name, card_type),
                    model=models[card_type],
                    entries=entries,
                )
            )

    return decks


def _select_groups_for_word(
    word: dict[str, Any],
    config: DeckConfig,
    selection: DeckSelection,
) -> dict[str, list[tuple[dict[str, Any], GroupDef]]]:
    result: dict[str, list[tuple[dict[str, Any], GroupDef]]] = {}
    simplified = normalize_simplified(word.get("simplified", ""))

    for form in word.get("forms", []):
        form_tags = set(form.get("tags", []))
        for group in config.groups:
            level_str = group.tag_pattern.replace("hsk:", "") if group.tag_pattern.startswith("hsk:") else group.tag_pattern
            if not should_include_target(simplified, level_str, selection):
                continue
            if group.tag_pattern in form_tags:
                result.setdefault(group.tag_pattern, []).append((form, group))
                break  # Only assign to the first/lowest matching group

    return result


def _resolve_display_pinyin(form: dict[str, Any]) -> str:
    return numbered_to_xiehanzi_display(str(form.get("pinyin", "")))


def _resolve_zhuyin(display_pinyin: str) -> str:
    try:
        return transcriptions.pinyin_to_zhuyin(display_pinyin)
    except (ValueError, Exception):
        return ""


def load_enriched_entries(
    enriched_db_path: Path,
    selection: DeckSelection,
    config: DeckConfig,
) -> tuple[dict[str, list[EnrichedWordEntry]], dict[str, Any], dict[str, Any]]:
    database = json.loads(enriched_db_path.read_text(encoding="utf-8"))
    group_entries: dict[str, list[EnrichedWordEntry]] = {
        group.tag_pattern: [] for group in config.groups
    }
    matched_additional_simplified: set[str] = set()
    rendered_meaning_html_used = 0
    extra_group_tag = "extra"

    for word in database.get("words", []):
        simplified = normalize_simplified(word["simplified"])

        is_additional = simplified in selection.additional_simplified

        has_any_target = any(
            group.tag_pattern in form.get("tags", [])
            for form in word.get("forms", [])
            for group in config.groups
        )
        if not has_any_target and not is_additional:
            continue

        rendered_definition_html = render_meaning_html(word)

        form_groups = _select_groups_for_word(word, config, selection)

        for group_tag, form_group_pairs in form_groups.items():
            for form, group in form_group_pairs:
                if is_additional:
                    matched_additional_simplified.add(simplified)

                traditional_variants = form.get("traditional_variants") or word.get("traditional_variants") or []
                traditional = traditional_variants[0] if traditional_variants else simplified

                rendered_meaning_html_used += 1

                display_pinyin = _resolve_display_pinyin(form)
                zhuyin = _resolve_zhuyin(display_pinyin)

                entry = EnrichedWordEntry(
                    simplified=simplified,
                    traditional=str(traditional),
                    pinyin=display_pinyin,
                    zhuyin=zhuyin,
                    definition_html=rendered_definition_html,
                    audio_filename=config.audio_filename(simplified),
                )

                group_entries[group_tag].append(entry)

        if is_additional and not form_groups and extra_group_tag in group_entries:
            matched_additional_simplified.add(simplified)

            for form in word.get("forms", []):
                traditional_variants = form.get("traditional_variants") or word.get("traditional_variants") or []
                traditional = traditional_variants[0] if traditional_variants else simplified

                rendered_meaning_html_used += 1

                display_pinyin = _resolve_display_pinyin(form)
                zhuyin = _resolve_zhuyin(display_pinyin)

                entry = EnrichedWordEntry(
                    simplified=simplified,
                    traditional=str(traditional),
                    pinyin=display_pinyin,
                    zhuyin=zhuyin,
                    definition_html=rendered_definition_html,
                    audio_filename=config.audio_filename(simplified),
                )

                group_entries[extra_group_tag].append(entry)

    for entries in group_entries.values():
        entries.sort(key=lambda entry: entry.simplified)

    selection_report = {
        **selection.report(),
        "matched_additional_simplified": sorted(matched_additional_simplified),
        "unmatched_additional_simplified": sorted(
            selection.additional_simplified - matched_additional_simplified
        ),
        "meaning_html": {
            "rendered_from_data": rendered_meaning_html_used,
        },
    }

    return group_entries, database, selection_report


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


def generate_missing_audio(entries: list[EnrichedWordEntry], voice: str) -> tuple[list[str], list[dict[str, str]], list[str]]:
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
            communicate = edge_tts.Communicate(entry.simplified.strip(), voice)
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


def collect_media(entries: list[EnrichedWordEntry], static_media: list[str]) -> tuple[list[str], list[str]]:
    media = list(static_media)
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
    deck_config_path: Path | None,
    output_apkg: Path,
    report_path: Path,
    timestamp: float | None,
    deterministic_zip: bool,
    zip_generated_datetime: tuple[int, int, int, int, int, int] | None,
) -> dict[str, Any]:
    config = common.load_deck_config(deck_config_path)
    selection = load_deck_selection(deck_config_path, config)
    group_entries, database, selection_report = load_enriched_entries(enriched_db, selection, config)
    all_entries = [entry for entries in group_entries.values() for entry in entries]

    static_media = config.static_media()
    generated_audio, failed_audio_generation, removed_zero_length_audio = generate_missing_audio(all_entries, config.audio.voice)
    models = common.create_models(config)
    decks = build_decks(config, models, group_entries)
    media_files, missing_audio = collect_media(all_entries, static_media)

    package = genanki.Package(decks, media_files=media_files)
    write_package(
        package=package,
        output_apkg=output_apkg,
        timestamp=timestamp,
        deterministic_zip=deterministic_zip,
        zip_generated_datetime=zip_generated_datetime,
    )

    group_counts = {group.tag_pattern: len(group_entries.get(group.tag_pattern, [])) for group in config.groups}

    report = {
        "output": str(output_apkg),
        "report": str(report_path),
        "enriched_db": str(enriched_db),
        "deck_config": selection_report,
        "source_schema": database.get("schema"),
        "deck_root": config.deck_name,
        "card_types": list(config.card_types),
        "dedupe_key": database.get("enrichment", {}).get("dedupe_key"),
        "hsk_words_after_dedupe": sum(
            len(group_entries.get(g.tag_pattern, []))
            for g in config.groups
            if g.tag_pattern.startswith("hsk:")
        ),
        "extra_words": len(group_entries.get("extra", [])),
        "total_words": len(all_entries),
        "total_cards": len(all_entries) * len(config.card_types),
        "decks": len(decks),
        "audio_files_packaged": len(media_files) - len(static_media),
        "audio_voice": config.audio.voice,
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
        "hsk_counts": {
            g.tag_pattern.replace("hsk:", ""): count
            for g, count in ((g, group_counts.get(g.tag_pattern, 0)) for g in config.groups)
            if g.tag_pattern.startswith("hsk:")
        },
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
    parser.add_argument("--output", type=Path, default=None, help="Output APKG path.")
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

    output_apkg = args.output
    if output_apkg is None:
        config = common.load_deck_config(args.config)
        output_apkg = config.output_apkg_path

    report = build_package(
        enriched_db=args.enriched_db,
        deck_config_path=args.config,
        output_apkg=output_apkg,
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
