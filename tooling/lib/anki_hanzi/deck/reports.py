"""Build report assembly for the customized hanzi APKG."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki_hanzi.audio.api import AudioGenerationResult
from anki_hanzi.deck import common
from anki_hanzi.deck.entries import EnrichedWordEntry
from anki_hanzi.deck.templates import read_hanzi_writer_package_version


@dataclass(frozen=True)
class DeckBuildReportInput:
    output_apkg: Path
    report_path: Path
    migrator_addon_output: Path
    master_db_output: Path | None
    enriched_db_output: Path | None
    source_database_report: dict[str, Any]
    enriched_lexicon: dict[str, Any]
    enrichment_report: dict[str, Any]
    matching_report: dict[str, Any]
    selection_report: dict[str, Any]
    source_schema: str
    build_id: str
    card_types: tuple[str, ...]
    card_settings: dict[str, dict[str, dict[str, Any]]]
    dedupe_key: str
    entries_by_card_type: Mapping[str, Sequence[EnrichedWordEntry]]
    all_entries: Sequence[EnrichedWordEntry]
    total_cards: int
    decks_count: int
    media_files: Sequence[str]
    static_media: Sequence[str]
    audio_engine: str
    audio_voices: dict[str, dict[str, str]]
    audio_result: AudioGenerationResult
    timestamp: float | None
    deterministic_zip: bool
    default_zip_datetime: tuple[int, int, int, int, int, int]
    zip_generated_datetime: tuple[int, int, int, int, int, int] | None
    dropped_duplicates: Sequence[dict[str, Any]]
    missing_audio_files: Sequence[str]


def _unique_word_count(entries: Sequence[EnrichedWordEntry]) -> int:
    return len({entry.simplified.strip() for entry in entries if entry.simplified.strip()})


def selected_enrichment_samples(samples: Mapping[str, Any]) -> dict[str, Any]:
    diagnostic_sample_keys = (
        "missing_raw_entries",
        "missing_deck_entries",
        "synthetic_words",
        "manual_pinyin_override_entries",
        "exact_definition_also_pr_added_readings",
        "semicolon_split_exact_definition_also_pr_added_readings",
        "html_subform_definition_cover_targets",
        "source_see_colloquial_pr_added_readings",
        "hanzi_non_exact_definition_mismatches",
        "hanzi_non_exact_definition_mismatches_by_type",
        "dropped_duplicates",
    )
    return {key: samples[key] for key in diagnostic_sample_keys if key in samples}


def build_deck_report(data: DeckBuildReportInput) -> dict[str, Any]:
    matching_summary = data.matching_report["summary"]
    enrichment_summary = data.enrichment_report["summary"]
    hsk_report = data.enrichment_report["hsk_enrichment"]
    entries_by_card_type = {card_type: len(entries) for card_type, entries in data.entries_by_card_type.items()}
    total_words = _unique_word_count(data.all_entries)
    audio_files_packaged = len(data.media_files) - len(data.static_media)
    diagnostic_databases = {}
    if data.master_db_output is not None:
        diagnostic_databases["master"] = str(data.master_db_output)
    if data.enriched_db_output is not None:
        diagnostic_databases["enriched"] = str(data.enriched_db_output)
    artifacts = {
        "apkg": str(data.output_apkg),
        "build_report": str(data.report_path),
        "migrator_addon": str(data.migrator_addon_output),
    }
    if diagnostic_databases:
        artifacts["diagnostic_databases"] = diagnostic_databases

    return {
        "schema": "hanzi-build-report-v2",
        "summary": {
            "build_id": data.build_id,
            "deck_root": common.DECK_ROOT,
            "total_words": total_words,
            "total_cards": data.total_cards,
            "entries_by_card_type": entries_by_card_type,
            "decks": data.decks_count,
            "dropped_duplicate_occurrences": len(data.dropped_duplicates),
            "unresolved_source_forms": matching_summary["unresolved_source_forms"],
            "default_unresolved_matching_pair_count": matching_summary["default_unresolved_matching_pair_count"],
            "audio_engine": data.audio_engine,
            "audio_files_packaged": audio_files_packaged,
            "generated_audio_files_count": len(data.audio_result.generated),
            "failed_audio_generation_count": len(data.audio_result.failed),
            "missing_audio_files_count": len(data.missing_audio_files),
        },
        "artifacts": artifacts,
        "stages": {
            "source_database": data.source_database_report,
            "lexicon_enrichment": {
                "schema": data.enrichment_report["schema"],
                "enriched_lexicon_schema": data.enriched_lexicon.get("schema"),
                "input": data.enrichment_report["input"],
                "output": data.enrichment_report.get("output"),
                "summary": enrichment_summary,
                "hsk_enrichment": {
                    "schema": hsk_report["schema"],
                    "input": hsk_report["input"],
                    "summary": hsk_report["summary"],
                    "matching": {
                        "schema": data.matching_report["schema"],
                        "description": data.matching_report["description"],
                        "summary": matching_summary,
                        "bucket_summary": data.matching_report["bucket_summary"],
                        "pair_materialization": data.matching_report["pair_materialization"],
                        "candidate_generation": data.matching_report["candidate_generation"],
                        "detailed_buckets": data.matching_report["buckets"],
                    },
                    "pipeline_enrichment": hsk_report["pipeline_enrichment"],
                },
                "frequency_enrichment": data.enrichment_report["frequency_enrichment"],
                "yct_enrichment": data.enrichment_report["yct_enrichment"],
                "bct_enrichment": data.enrichment_report["bct_enrichment"],
                "erhua_definition_enrichment": data.enrichment_report["erhua_definition_enrichment"],
                "samples": selected_enrichment_samples(data.enrichment_report["samples"]),
            },
            "deck_selection": {
                **data.selection_report,
                "source_schema": data.source_schema,
                "dedupe_key": data.dedupe_key,
                "card_types": list(data.card_types),
                "card_settings": data.card_settings,
                "entries_by_card_type": entries_by_card_type,
                "total_words": total_words,
                "total_cards": data.total_cards,
            },
            "audio": {
                "engine": data.audio_engine,
                "voices": data.audio_voices,
                "audio_files_packaged": audio_files_packaged,
                "generated_audio_files_count": len(data.audio_result.generated),
                "failed_audio_generation": data.audio_result.report_failed(),
                "skipped_audio_generation": data.audio_result.report_skipped(),
                "removed_zero_length_audio_files": data.audio_result.removed_zero_length,
                "missing_audio_files": list(data.missing_audio_files),
            },
            "hanzi_writer": {
                "version": read_hanzi_writer_package_version(),
                "bundle": str(common.HANZI_WRITER_BUNDLE),
            },
            "package": {
                "output": str(data.output_apkg),
                "timestamp": data.timestamp,
                "deterministic_zip": data.deterministic_zip,
                "zip_datetime": data.default_zip_datetime
                if data.deterministic_zip and data.zip_generated_datetime is None
                else None,
                "zip_generated_datetime": data.zip_generated_datetime,
            },
        },
    }
