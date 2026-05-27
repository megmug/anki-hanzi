#!/usr/bin/env python

"""
Build the customized hanzi APKG from the enriched JSON database.

The generator reads word/card data from
`master_db_output/cc_cedict_hanzi_enriched.json` and uses the shared deck
build helpers in `scripts/deck_build_common.py` for templates, media, and stable
Anki ids.

`deck_inputs/deck_config.json` controls which tagged hanzi forms are emitted
as notes, which card types are generated, and optional per-card display
settings that are baked into the templates.

Run from the repository root inside the Nix shell:

    nix-shell --run "python scripts/generate_hanzi_deck.py"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import edge_tts
import genanki

import deck_build_common as common
from deck_build_common import DeckConfig
from meaning_html import numbered_to_display, render_meaning_html


DEFAULT_ENRICHED_DB = Path("master_db_output/cc_cedict_hanzi_enriched.json")
DEFAULT_DECK_CONFIG = Path("deck_inputs/deck_config.json")
DEFAULT_AUDIO_EXCEPTIONS = Path("deck_inputs/audio_generation_exceptions.json")
DEFAULT_REPORT_PATH = Path("build_reports/generate_hanzi_report.json")
DEFAULT_GENANKI_TIMESTAMP = 1779251987.6
DEFAULT_GENERATED_ZIP_DATETIME = (2026, 5, 20, 6, 39, 48)
DEFAULT_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)
GENERATED_ZIP_MEMBERS = {"collection.anki2", "media"}


@dataclass(frozen=True)
class EnrichedWordEntry:
    simplified: str
    pinyin: str
    definition_html: str
    audio_filename_female: str
    audio_filename_male: str
    tags: tuple[str, ...] = ()

    @property
    def audio_ref(self) -> str:
        if not self.audio_filename_female and not self.audio_filename_male:
            return ""
        return (
            f"[sound:{self.audio_filename_female}]"
            f"[sound:{self.audio_filename_male}]"
        )

    @property
    def audio_filenames(self) -> tuple[str, str]:
        return (self.audio_filename_female, self.audio_filename_male)

    def fields(self, card_type: str, build_id: str) -> list[str]:
        note_id = common.stable_note_id(card_type, self.simplified, self.pinyin)
        return [
            self.simplified,
            self.pinyin,
            self.definition_html,
            self.audio_ref,
            note_id,
            build_id,
        ]


@dataclass(frozen=True)
class DeckSelection:
    mode: str
    tags: tuple[str, ...]
    individual_simplified: frozenset[str]
    config_path: str | None
    config_found: bool

    def report(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "config_found": self.config_found,
            "mode": self.mode,
            "tags": list(self.tags),
            "individual_simplified": sorted(self.individual_simplified),
        }


def normalize_simplified(value: Any) -> str:
    return str(value or "").strip()


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
        raise ValueError("deck config file is required but not found")

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    selection = raw.get("selection")
    if selection is None:
        raise ValueError("deck config must define a 'selection' object")
    if not isinstance(selection, dict):
        raise ValueError("deck config selection must be an object")

    tags_raw = selection.get("tags", [])
    if isinstance(tags_raw, str):
        tags = (tags_raw,)
    elif isinstance(tags_raw, list):
        tags = tuple(str(t) for t in tags_raw)
    else:
        tags = ()

    return DeckSelection(
        mode=str(selection.get("mode", "")),
        tags=tags,
        individual_simplified=parse_simplified_list(
            selection.get("individual_simplified", []),
            "individual_simplified",
        ),
        config_path=str(config_path),
        config_found=True,
    )


def _is_hanzi_char(char: str) -> bool:
    code = ord(char)
    return (
        (0x4E00 <= code <= 0x9FFF)
        or (0x3400 <= code <= 0x4DBF)
        or (0x20000 <= code <= 0x2EBEF)
    )


def _has_hanzi_writer_data(char: str) -> bool:
    if not _is_hanzi_char(char):
        return False
    data_file = common.HANZI_WRITER_DATA_DIR / f"{char}.json"
    return data_file.exists()


def _is_writable_hanzi(text: str) -> bool:
    if not text:
        return False
    return all(_has_hanzi_writer_data(c) for c in text)


def build_decks(
    config: DeckConfig,
    models: dict[str, genanki.Model],
    entries: list[EnrichedWordEntry],
    build_id: str,
) -> list[genanki.Deck]:
    decks: list[genanki.Deck] = []

    for card_type in config.card_types:
        if card_type == "Write":
            card_entries = [e for e in entries if _is_writable_hanzi(e.simplified)]
        else:
            card_entries = entries
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


def build_hanzi_writer_bundle(
    write_entries: list[EnrichedWordEntry],
    output_path: Path,
) -> str:
    """Build a single JS file with all hanzi-writer data needed by the Write deck.

    Returns the path to the generated file.
    """
    unique_chars: set[str] = set()
    for entry in write_entries:
        for char in entry.simplified:
            if _has_hanzi_writer_data(char):
                unique_chars.add(char)

    data: dict[str, Any] = {}
    for char in unique_chars:
        data_file = common.HANZI_WRITER_DATA_DIR / f"{char}.json"
        if data_file.exists():
            data[char] = json.loads(data_file.read_text(encoding="utf-8"))

    bundle_js = "window.hanziWriterData = " + json.dumps(data, ensure_ascii=False) + ";\n"
    output_path.write_text(bundle_js, encoding="utf-8")
    return str(output_path)


def _resolve_display_pinyin(form: dict[str, Any]) -> str:
    return numbered_to_display(str(form.get("pinyin", "")))


def load_enriched_entries(
    enriched_db_path: Path,
    selection: DeckSelection,
    config: DeckConfig,
) -> tuple[list[EnrichedWordEntry], dict[str, Any], dict[str, Any]]:
    database = json.loads(enriched_db_path.read_text(encoding="utf-8"))
    entries: list[EnrichedWordEntry] = []
    matched_individual_simplified: set[str] = set()
    rendered_meaning_html_used = 0
    seen_entry_keys: set[tuple[str, str]] = set()
    selection_tags = set(selection.tags)

    for word in database.get("words", []):
        simplified = normalize_simplified(word["simplified"])

        is_individual = simplified in selection.individual_simplified
        mode = selection.mode

        rendered_definition_html = render_meaning_html(word)

        forms = word.get("forms", [])
        if not forms:
            forms = [{}]

        word_entry_count = 0
        for form in forms:
            form_tags = set(form.get("tags", []))
            fallback_tags = set(word.get("tags", []))
            effective_tags = form_tags or fallback_tags

            if mode == "tagged" and not (effective_tags & selection_tags) and not is_individual:
                continue
            if mode not in {"all", "tagged"} and not is_individual:
                continue

            display_pinyin = _resolve_display_pinyin(form)
            entry_key = (simplified, common.normalized_note_pinyin(display_pinyin))
            if not entry_key[1] or entry_key in seen_entry_keys:
                continue
            seen_entry_keys.add(entry_key)

            if is_individual:
                matched_individual_simplified.add(simplified)

            include_audio = config.audio.engine.lower().replace("-", "_") != "off"
            entry = EnrichedWordEntry(
                simplified=simplified,
                pinyin=display_pinyin,
                definition_html=rendered_definition_html,
                audio_filename_female=config.audio_filenames(simplified)[0] if include_audio else "",
                audio_filename_male=config.audio_filenames(simplified)[1] if include_audio else "",
                tags=tuple(sorted(effective_tags | {"source:xiehanzi"})),
            )
            entries.append(entry)
            word_entry_count += 1

        if word_entry_count:
            rendered_meaning_html_used += 1

    entries.sort(key=lambda entry: entry.simplified)

    selection_report = {
        **selection.report(),
        "matched_individual_simplified": sorted(matched_individual_simplified),
        "unmatched_individual_simplified": sorted(
            selection.individual_simplified - matched_individual_simplified
        ),
        "meaning_html": {
            "rendered_from_data": rendered_meaning_html_used,
        },
    }

    return entries, database, selection_report


def _prepare_audio_dir() -> list[str]:
    """Remove stale extra-audio files so nothing leaks between builds."""
    removed: list[str] = []
    if common.EXTRA_AUDIO_DIR.exists():
        for path in common.EXTRA_AUDIO_DIR.glob("*"):
            if path.is_file():
                path.unlink()
                removed.append(str(path))
    common.EXTRA_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    return removed


def load_audio_generation_exceptions(path: Path = DEFAULT_AUDIO_EXCEPTIONS) -> dict[str, str]:
    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    words = raw.get("words", [])
    if not isinstance(words, list):
        raise ValueError(f"{path} field 'words' must be a list")

    exceptions: dict[str, str] = {}
    for item in words:
        if isinstance(item, str):
            simplified = item.strip()
            reason = "listed in audio generation exceptions"
        elif isinstance(item, dict):
            simplified = str(item.get("simplified", "")).strip()
            reason = str(item.get("reason", "listed in audio generation exceptions"))
        else:
            continue
        if simplified:
            exceptions[simplified] = reason
    return exceptions


def _skip_audio_exception(
    skipped: list[dict[str, str]],
    word: str,
    gender: str,
    voice: str,
    reason: str,
) -> None:
    print(
        f"  Audio skipped by exception DB: word={word!r} gender={gender} voice={voice!r}: {reason}",
        flush=True,
    )
    skipped.append({
        "word": word,
        "gender": gender,
        "voice": voice,
        "reason": reason,
    })


def _is_audio_input_error(exc: Exception) -> bool:
    message = str(exc)
    return (
        "normal_pinyin" in message
        or "Final couldn't be detected" in message
    )


def _torch_cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _resolve_kokoro_device() -> str:
    return "cuda" if _torch_cuda_available() else "cpu"


def _create_kokoro_pipeline(KPipeline: type, device: str) -> Any:
    import inspect

    kwargs: dict[str, Any] = {"lang_code": "z"}
    try:
        parameters = inspect.signature(KPipeline).parameters
    except (TypeError, ValueError):
        parameters = {}
    supports_device = "device" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    if supports_device:
        kwargs["device"] = device
    elif device != "cpu":
        print("  Kokoro KPipeline does not expose device=; using package default", flush=True)
    return KPipeline(**kwargs)


def _generate_audio_kokoro(
    entries: list[EnrichedWordEntry],
    config: common.DeckConfig,
    removed: list[str],
    audio_exceptions: dict[str, str],
) -> tuple[list[str], list[dict[str, str]], list[str], list[dict[str, str]]]:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    device = _resolve_kokoro_device()
    try:
        pipeline = _create_kokoro_pipeline(KPipeline, device)
    except Exception:
        if device != "cpu":
            print("  Kokoro audio device: failed to initialize cuda; falling back to cpu", flush=True)
            device = "cpu"
            try:
                pipeline = _create_kokoro_pipeline(KPipeline, device)
            except Exception:
                import traceback
                return [], [{"error": f"Failed to load Kokoro pipeline:\n{traceback.format_exc()}"}], removed, []
        else:
            import traceback
            return [], [{"error": f"Failed to load Kokoro pipeline:\n{traceback.format_exc()}"}], removed, []

    print(f"  Kokoro audio device: {device}", flush=True)

    fallback_to_cpu = device != "cpu"

    def synthesize(word: str, voice: str, gender: str) -> list[Any]:
        nonlocal device, fallback_to_cpu, pipeline
        try:
            return list(pipeline(word, voice=voice, speed=1.0))
        except Exception as exc:
            if _is_audio_input_error(exc):
                raise
            if not fallback_to_cpu:
                raise
            print(
                "  Kokoro audio device: cuda generation failed; "
                f"word={word!r} gender={gender} voice={voice!r}; falling back to cpu ({exc})",
                flush=True,
            )
            fallback_to_cpu = False
            device = "cpu"
            pipeline = _create_kokoro_pipeline(KPipeline, device)
            return list(pipeline(word, voice=voice, speed=1.0))


    generated: list[str] = []
    failed: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    seen_words: set[str] = set()

    total_words = len({e.simplified.strip() for e in entries if e.simplified.strip()})
    progress_interval = max(1, total_words // 100)

    for entry in entries:
        word = entry.simplified.strip()
        if not word or word in seen_words:
            continue
        seen_words.add(word)

        female_voice = common.KOKORO_FEMALE_VOICES[0]
        male_voice = common.KOKORO_MALE_VOICES[0]

        for gender, voice, filename in [
            ("female", female_voice, entry.audio_filename_female),
            ("male", male_voice, entry.audio_filename_male),
        ]:
            exception_reason = audio_exceptions.get(word)
            if exception_reason is not None:
                _skip_audio_exception(skipped, word, gender, voice, exception_reason)
                continue

            output_path = common.EXTRA_AUDIO_DIR / filename
            try:
                results = synthesize(word, voice, gender)
                segments = [r.audio for r in results if r.audio is not None]
                if not segments:
                    failed.append({
                        "word": word,
                        "gender": gender,
                        "voice": voice,
                        "error": "Kokoro produced no audio",
                    })
                    continue
                audio = np.concatenate(segments)
                sf.write(output_path, audio, 24000)
                generated.append(str(output_path))
            except Exception as exc:
                print(
                    f"  Kokoro audio failed: word={word!r} gender={gender} voice={voice!r}: {exc}",
                    flush=True,
                )
                failed.append({
                    "word": word,
                    "gender": gender,
                    "voice": voice,
                    "error": str(exc),
                })

        if len(seen_words) % progress_interval == 0:
            pct = len(seen_words) * 100 // total_words
            print(f"  Audio progress: {len(seen_words)}/{total_words} words ({pct}%)", flush=True)

    print(f"  Audio generation complete: {len(generated)} files, {len(failed)} failures")
    return generated, failed, removed, skipped


def _generate_audio_edge_tts(
    entries: list[EnrichedWordEntry],
    config: common.DeckConfig,
    removed: list[str],
    audio_exceptions: dict[str, str],
) -> tuple[list[str], list[dict[str, str]], list[str], list[dict[str, str]]]:
    import time
    import edge_tts

    generated: list[str] = []
    failed: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    seen_words: set[str] = set()

    total_words = len({e.simplified.strip() for e in entries if e.simplified.strip()})
    progress_interval = max(1, total_words // 100)

    def _generate_one(word: str, voice: str, output_path: Path) -> str | None:
        """Try to generate audio with retries. Returns error string or None on success."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                communicate = edge_tts.Communicate(word, voice)
                communicate.save_sync(str(output_path))
                if output_path.exists() and output_path.stat().st_size > 0:
                    return None
                common.remove_failed_audio_output(output_path)
                return "edge-tts produced no audio data"
            except Exception as exc:
                common.remove_failed_audio_output(output_path)
                if attempt < max_retries - 1:
                    delay = 2 ** (attempt + 1)  # 2s, 4s, 8s
                    print(f"    Retry {attempt + 1}/{max_retries} for '{word}' ({voice}) after {delay}s: {exc}", flush=True)
                    time.sleep(delay)
                else:
                    return str(exc)
        return "max retries exceeded"

    for entry in entries:
        word = entry.simplified.strip()
        if not word or word in seen_words:
            continue
        seen_words.add(word)

        female_voice = common.EDGE_TTS_FEMALE_VOICES[0]
        male_voice = common.EDGE_TTS_MALE_VOICES[0]

        for gender, voice, filename in [
            ("female", female_voice, entry.audio_filename_female),
            ("male", male_voice, entry.audio_filename_male),
        ]:
            exception_reason = audio_exceptions.get(word)
            if exception_reason is not None:
                _skip_audio_exception(skipped, word, gender, voice, exception_reason)
                continue

            output_path = common.EXTRA_AUDIO_DIR / filename
            error = _generate_one(word, voice, output_path)
            if error is None:
                generated.append(str(output_path))
            else:
                failed.append({
                    "word": word,
                    "gender": gender,
                    "voice": voice,
                    "error": error,
                })

        if len(seen_words) % progress_interval == 0:
            pct = len(seen_words) * 100 // total_words
            print(f"  Audio progress: {len(seen_words)}/{total_words} words ({pct}%)", flush=True)

    print(f"  Audio generation complete: {len(generated)} files, {len(failed)} failures")
    return generated, failed, removed, skipped


def generate_audio(
    entries: list[EnrichedWordEntry],
    config: common.DeckConfig,
) -> tuple[list[str], list[dict[str, str]], list[str], list[dict[str, str]]]:
    """Generate fresh dual-voice audio for all entries.

    Always regenerates every audio file so builds are self-contained.
    Uses fixed voices (first in the hardcoded voice lists).
    Backend is controlled by config.audio.engine ("kokoro", "edge_tts", or "off").
    """
    removed = _prepare_audio_dir()
    audio_exceptions = load_audio_generation_exceptions()

    engine = config.audio.engine.lower().replace("-", "_")
    if engine == "off":
        print("  Audio generation disabled (engine: off)")
        return [], [], removed, []
    if engine == "edge_tts":
        return _generate_audio_edge_tts(entries, config, removed, audio_exceptions)
    return _generate_audio_kokoro(entries, config, removed, audio_exceptions)


def collect_media(entries: list[EnrichedWordEntry], static_media: list[str]) -> tuple[list[str], list[str]]:
    media = list(static_media)
    missing_audio: list[str] = []
    seen_media_names = {Path(path).name for path in media}

    for entry in entries:
        for filename in entry.audio_filenames:
            if not filename:
                continue
            path = common.EXTRA_AUDIO_DIR / filename
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
    selection = load_deck_selection(deck_config_path)
    entries, database, selection_report = load_enriched_entries(enriched_db, selection, config)
    build_id = resolve_build_id()

    static_media = config.static_media()
    (
        generated_audio,
        failed_audio_generation,
        removed_zero_length_audio,
        skipped_audio_generation,
    ) = generate_audio(entries, config)

    # Build hanzi-writer JS bundle for offline Write deck usage
    write_entries = [e for e in entries if _is_writable_hanzi(e.simplified)]
    hw_bundle_path = Path(common.EXTRA_AUDIO_DIR) / "hanzi-writer-data.js"
    hw_bundle_path.parent.mkdir(parents=True, exist_ok=True)
    build_hanzi_writer_bundle(write_entries, hw_bundle_path)

    models = common.create_models(config, hw_bundle_path if hw_bundle_path.exists() else None)
    decks = build_decks(config, models, entries, build_id)

    media_files, missing_audio = collect_media(entries, static_media)

    package = genanki.Package(decks, media_files=media_files)
    write_package(
        package=package,
        output_apkg=output_apkg,
        timestamp=timestamp,
        deterministic_zip=deterministic_zip,
        zip_generated_datetime=zip_generated_datetime,
    )

    total_cards = sum(len(d.notes) for d in decks)
    report = {
        "output": str(output_apkg),
        "report": str(report_path),
        "enriched_db": str(enriched_db),
        "deck_config": selection_report,
        "source_schema": database.get("schema"),
        "deck_root": common.DECK_ROOT,
        "build_id": build_id,
        "card_types": list(config.card_types),
        "card_settings": config.card_settings,
        "dedupe_key": database.get("enrichment", {}).get("dedupe_key"),
        "total_words": len(entries),
        "total_cards": total_cards,
        "decks": len(decks),
        "audio_files_packaged": len(media_files) - len(static_media),
        "audio_engine": config.audio.engine,
        "audio_female_voices": list(common.KOKORO_FEMALE_VOICES if config.audio.engine == "kokoro" else common.EDGE_TTS_FEMALE_VOICES),
        "audio_male_voices": list(common.KOKORO_MALE_VOICES if config.audio.engine == "kokoro" else common.EDGE_TTS_MALE_VOICES),
        "hanzi_writer_version": common.read_hanzi_writer_package_version(),
        "hanzi_writer_bundle": str(common.HANZI_WRITER_BUNDLE),
        "timestamp": timestamp,
        "deterministic_zip": deterministic_zip,
        "zip_datetime": DEFAULT_ZIP_DATETIME if deterministic_zip and zip_generated_datetime is None else None,
        "zip_generated_datetime": zip_generated_datetime,
        "generated_audio_files_count": len(generated_audio),
        "failed_audio_generation": failed_audio_generation,
        "skipped_audio_generation": skipped_audio_generation,
        "removed_zero_length_audio_files": removed_zero_length_audio,
        "dropped_duplicate_occurrences": len(database.get("hanzi", {}).get("dropped_duplicates", [])),
        "dropped_duplicates": database.get("hanzi", {}).get("dropped_duplicates", []),
        "missing_audio_files": missing_audio,
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
        output_apkg = common.OUTPUT_APKG

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
        if key != "dropped_duplicates"
    }
    print(json.dumps(console_report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
