"""Build the customized hanzi APKG from the typed lexicon pipeline."""

from __future__ import annotations

import os
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import genanki

from anki_hanzi.audio.generation import AudioGenerator
from anki_hanzi.deck import common
from anki_hanzi.deck.config import DeckConfig, load_deck_config
from anki_hanzi.deck.entries import (
    EnrichedWordEntry,
    build_entries_from_state,
    flatten_entries_by_card_type,
    unique_audio_entries,
)
from anki_hanzi.deck.hanzi_writer import build_hanzi_writer_bundle, is_writable_hanzi
from anki_hanzi.deck.migrator_addon import build_migrator_addon
from anki_hanzi.deck.models import create_models
from anki_hanzi.deck.reports import DeckBuildReportInput, build_deck_report
from anki_hanzi.deck.template_generation import HanziTemplateGenerator
from anki_hanzi.deck.workspace import temporary_build_workspace
from anki_hanzi.enrichment import (
    HANZI_DEDUPE_KEY,
    enrich_state,
)
from anki_hanzi.json_io import write_json
from anki_hanzi.lexicon import ENRICHED_LEXICON_SCHEMA, LexiconState
from anki_hanzi.lexicon.cc_cedict import load_cedict_state, load_snapshot_manifest, resolve_source_file
from anki_hanzi.paths import DEFAULT_AUDIO_EXCEPTIONS


DEFAULT_REPORT_PATH = Path("build_reports/build_report.json")
DEFAULT_MIGRATOR_ADDON_SOURCE = Path("tooling/utilities/anki_hanzi_migrator")
DEFAULT_MIGRATOR_ADDON_OUTPUT = Path("anki-hanzi-migrator.ankiaddon")
DEFAULT_GENANKI_TIMESTAMP = 1779251987.6
DEFAULT_GENERATED_ZIP_DATETIME = (2026, 5, 20, 6, 39, 48)
DEFAULT_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)
GENERATED_ZIP_MEMBERS = {"collection.anki2", "media"}


@dataclass(frozen=True)
class EnrichedStateBuildResult:
    state: LexiconState
    source_database_report: dict[str, Any]
    enrichment_report: dict[str, Any]
    matching_report: dict[str, Any]


def build_decks(
    config: DeckConfig,
    models: dict[str, genanki.Model],
    entries_by_card_type: dict[str, list[EnrichedWordEntry]],
    build_id: str,
) -> list[genanki.Deck]:
    decks: list[genanki.Deck] = []

    for card_type in config.card_types:
        card_entries = entries_by_card_type.get(card_type, [])
        if card_type == "Write":
            card_entries = [entry for entry in card_entries if is_writable_hanzi(entry.simplified)]
        decks.append(
            common.create_deck(
                deck_name=f"{common.DECK_ROOT}::{card_type}",
                card_type=card_type,
                model=models[card_type],
                entries=card_entries,
                build_id=build_id,
            )
        )

    return decks


def resolve_build_id() -> str:
    env_build_id = os.environ.get("ANKI_HANZI_BUILD_ID", "").strip()
    if env_build_id:
        return env_build_id
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def resolve_known_build_ids(current_build_id: str) -> list[str]:
    env_build_ids = os.environ.get("ANKI_HANZI_KNOWN_BUILD_IDS", "").strip()
    if env_build_ids:
        build_ids = [item.strip() for item in env_build_ids.replace(",", "\n").splitlines() if item.strip()]
    else:
        try:
            output = subprocess.check_output(
                ["git", "rev-list", "--first-parent", "--reverse", "--abbrev-commit", "--abbrev=7", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            build_ids = [line.strip() for line in output.splitlines() if line.strip()]
        except Exception:
            build_ids = []

    if current_build_id and current_build_id not in build_ids:
        build_ids.append(current_build_id)
    return list(dict.fromkeys(build_ids))


def collect_media(
    entries: list[EnrichedWordEntry],
    static_media: list[str],
    audio_dir: Path,
) -> tuple[list[str], list[str]]:
    media = list(static_media)
    missing_audio: list[str] = []
    seen_media_names = {Path(path).name for path in media}

    for entry in entries:
        for filename in entry.audio_filenames:
            if not filename:
                continue
            path = audio_dir / filename
            if path.exists():
                if filename not in seen_media_names:
                    seen_media_names.add(filename)
                    media.append(str(path))
            else:
                missing_audio.append(filename)

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


def build_enriched_state(
    snapshot_manifest: Path,
    source_file: Path | None,
    master_db_output: Path | None,
    enriched_db_output: Path | None,
    hsk_data_dir: Path,
    frequency_list: Path,
    yct_data_dir: Path,
    bct_data_dir: Path,
) -> EnrichedStateBuildResult:
    manifest = load_snapshot_manifest(snapshot_manifest)
    resolved_source_file = resolve_source_file(snapshot_manifest, manifest, source_file)
    if not resolved_source_file.exists():
        raise FileNotFoundError(f"missing CC-CEDICT source file: {resolved_source_file}")

    state = load_cedict_state(
        source_file=resolved_source_file,
        url=manifest["source_url"],
        expected_sha256=manifest["sha256"],
    )
    state.sort_forms_by_pinyin()
    source_summary = state.summary()
    if master_db_output is not None:
        write_json(master_db_output, state.to_master_json())

    enrichment_result = enrich_state(
        master_state=state,
        input_label=str(master_db_output) if master_db_output is not None else "in-memory cc-cedict master state",
        output_path=enriched_db_output,
        hsk_data_dir=hsk_data_dir,
        frequency_list_path=frequency_list,
        yct_data_dir=yct_data_dir,
        bct_data_dir=bct_data_dir,
    )
    source_report = state.source.to_master_json()
    source_report["comment_header_lines"] = len(source_report.pop("comment_header", []))
    source_database_report = {
        "schema": state.schema,
        "snapshot_manifest": str(snapshot_manifest),
        "source_file": str(resolved_source_file),
        "source": source_report,
        "summary": source_summary,
    }
    if master_db_output is not None:
        source_database_report["diagnostic_output"] = str(master_db_output)
    return EnrichedStateBuildResult(
        state=state,
        source_database_report=source_database_report,
        enrichment_report=enrichment_result.enrichment_report,
        matching_report=enrichment_result.matching_report,
    )


def build_package(
    snapshot_manifest: Path,
    source_file: Path | None,
    master_db_output: Path | None,
    enriched_db_output: Path | None,
    hsk_data_dir: Path,
    frequency_list: Path,
    yct_data_dir: Path,
    bct_data_dir: Path,
    deck_config_path: Path | None,
    output_apkg: Path,
    report_path: Path,
    migrator_addon_output: Path,
    timestamp: float | None,
    deterministic_zip: bool,
    zip_generated_datetime: tuple[int, int, int, int, int, int] | None,
) -> dict[str, Any]:
    config = load_deck_config(deck_config_path)
    with temporary_build_workspace() as workspace:
        audio_generator = AudioGenerator(
            config.audio.engine,
            audio_dir=workspace.audio_dir,
            exceptions_path=DEFAULT_AUDIO_EXCEPTIONS,
        )
        enriched_state_result = build_enriched_state(
            snapshot_manifest=snapshot_manifest,
            source_file=source_file,
            master_db_output=master_db_output,
            enriched_db_output=enriched_db_output,
            hsk_data_dir=hsk_data_dir,
            frequency_list=frequency_list,
            yct_data_dir=yct_data_dir,
            bct_data_dir=bct_data_dir,
        )
        state = enriched_state_result.state
        entries_by_card_type, selection_report = build_entries_from_state(
            state,
            config.selection,
            audio_generator,
        )
        all_deck_entries = flatten_entries_by_card_type(entries_by_card_type)
        audio_deck_entries = unique_audio_entries(all_deck_entries)
        audio_jobs = audio_generator.jobs_for_texts(entry.simplified for entry in audio_deck_entries)
        build_id = resolve_build_id()
        known_build_ids = resolve_known_build_ids(build_id)
        build_migrator_addon(
            source_dir=DEFAULT_MIGRATOR_ADDON_SOURCE,
            output_path=migrator_addon_output,
            build_id=build_id,
            known_build_ids=known_build_ids,
            zip_datetime=zip_generated_datetime or DEFAULT_ZIP_DATETIME,
        )

        static_media = HanziTemplateGenerator().static_media()
        audio_result = audio_generator.generate(audio_jobs)

        write_entries = [
            entry for entry in entries_by_card_type.get("Write", []) if is_writable_hanzi(entry.simplified)
        ]
        build_hanzi_writer_bundle(write_entries, workspace.hanzi_writer_bundle)

        models = create_models(config, workspace.hanzi_writer_bundle)
        decks = build_decks(config, models, entries_by_card_type, build_id)

        media_files, missing_audio = collect_media(
            audio_deck_entries,
            static_media,
            workspace.audio_dir,
        )

        package = genanki.Package(decks, media_files=media_files)
        write_package(
            package=package,
            output_apkg=output_apkg,
            timestamp=timestamp,
            deterministic_zip=deterministic_zip,
            zip_generated_datetime=zip_generated_datetime,
        )

        report = build_deck_report(
            DeckBuildReportInput(
                output_apkg=output_apkg,
                report_path=report_path,
                migrator_addon_output=migrator_addon_output,
                master_db_output=master_db_output,
                enriched_db_output=enriched_db_output,
                source_database_report=enriched_state_result.source_database_report,
                enrichment_report=enriched_state_result.enrichment_report,
                matching_report=enriched_state_result.matching_report,
                selection_report=selection_report,
                source_schema=ENRICHED_LEXICON_SCHEMA,
                build_id=build_id,
                card_types=config.card_types,
                card_settings=config.card_settings,
                dedupe_key=HANZI_DEDUPE_KEY,
                entries_by_card_type=entries_by_card_type,
                all_entries=all_deck_entries,
                total_cards=sum(len(deck.notes) for deck in decks),
                decks_count=len(decks),
                media_files=media_files,
                static_media=static_media,
                audio_engine=config.audio.engine,
                audio_voices=audio_generator.voice_report(),
                audio_result=audio_result,
                timestamp=timestamp,
                deterministic_zip=deterministic_zip,
                default_zip_datetime=DEFAULT_ZIP_DATETIME,
                zip_generated_datetime=zip_generated_datetime,
                dropped_duplicates=state.hanzi_dropped_duplicates,
                missing_audio_files=missing_audio,
            )
        )
        write_json(report_path, report)
        return report
