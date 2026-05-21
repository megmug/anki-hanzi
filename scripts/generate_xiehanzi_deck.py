#!/usr/bin/env python

"""
Build a customized xiehanzi APKG from the prepared New HSK (2025) word files.

Differences from the notebook release build:
- does not generate Audio cards/decks
- keeps Meaning, Pinyin, and Write cards
- still packages audio files because the remaining card templates use `{{Audio}}`
- generates missing audio with edge-tts, matching the notebook's voice
- deduplicates HSK entries by Simplified + Pinyin, keeping the lowest HSK level
- adds optional Extra entries from `deck_inputs/extra_words.tsv`

`deck_inputs/extra_words.tsv` uses the same eight columns as the prepared HSK files:
Simplified, Traditional, Pinyin, Zhuyin, Level, PoS, Frequency, Meaning HTML.
Generated/custom audio is cached in `deck_inputs/extra_audio/cmn-<Simplified>.mp3`.

Run from the repository root inside the Nix shell:

    nix-shell --run "python scripts/generate_xiehanzi_deck.py"
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import genanki


DECK_ROOT = "Anki Xiehanzi - New HSK (2025)"
OUTPUT_APKG = Path("Anki-xiehanzi - New HSK (2025).apkg")
REPORT_PATH = Path("build_reports/generate_xiehanzi_report.json")
DECK_INPUTS_DIR = Path("deck_inputs")
CARD_TEMPLATES_DIR = DECK_INPUTS_DIR / "card_templates"
HSK_DATA_DIR = DECK_INPUTS_DIR / "hsk-3.0-words-list/New HSK (2025)/Anki xiehanzi"
AUDIO_DIR = DECK_INPUTS_DIR / "hsk-3.0-words-list/New HSK (2025)/Audio"
EXTRA_AUDIO_DIR = DECK_INPUTS_DIR / "extra_audio"
EXTRA_WORDS_PATH = DECK_INPUTS_DIR / "extra_words.tsv"
HANZI_WRITER_PACKAGE_JSON = Path("node_modules/hanzi-writer/package.json")
HANZI_WRITER_BUNDLE = Path("node_modules/hanzi-writer/dist/hanzi-writer.min.js")
VOICE = "zh-CN-XiaoxiaoNeural"
GENERATED_ZIP_MEMBERS = {"collection.anki2", "media"}

LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
CARD_TYPES = ["Meaning", "Pinyin", "Write"]

FIELDS = [
    {"name": "Simplified"},
    {"name": "Traditional"},
    {"name": "Pinyin"},
    {"name": "Zhuyin"},
    {"name": "PoS"},
    {"name": "Meaning"},
    {"name": "Audio"},
]

TEMPLATE_FILES = {
    "Meaning": (CARD_TEMPLATES_DIR / "Card 1/front.html", CARD_TEMPLATES_DIR / "Card 1/back.html"),
    "Pinyin": (CARD_TEMPLATES_DIR / "Card 2/front.html", CARD_TEMPLATES_DIR / "Card 2/back.html"),
    "Write": (CARD_TEMPLATES_DIR / "Card 5/front-xiehanzi-3.0.html", CARD_TEMPLATES_DIR / "Card 5/back.html"),
}

STATIC_MEDIA = [
    str(CARD_TEMPLATES_DIR / "fonts/_MaterialIcons-Regular.woff"),
    str(CARD_TEMPLATES_DIR / "fonts/_MaterialIcons-Regular.woff2"),
    str(CARD_TEMPLATES_DIR / "files/_pleco.png"),
    str(CARD_TEMPLATES_DIR / "files/_youdao.png"),
    str(CARD_TEMPLATES_DIR / "files/_rtega.png"),
    str(CARD_TEMPLATES_DIR / "files/_tatoeba.png"),
    str(CARD_TEMPLATES_DIR / "files/_hanzicraft.png"),
    str(CARD_TEMPLATES_DIR / "files/_characterpop.svg"),
]


@dataclass(frozen=True)
class WordEntry:
    simplified: str
    traditional: str
    pinyin: str
    zhuyin: str
    level: str
    pos: str
    frequency: str
    definition_html: str
    source: str

    @property
    def audio_ref(self) -> str:
        return f"[sound:cmn-{self.simplified}.mp3]"

    @property
    def audio_path(self) -> Path:
        return AUDIO_DIR / f"cmn-{self.simplified}.mp3"

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


def stable_id(label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    return (int.from_bytes(digest[:4], "big") % (1 << 30)) + (1 << 30)


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_hanzi_writer_package_version() -> str:
    package_data = json.loads(HANZI_WRITER_PACKAGE_JSON.read_text(encoding="utf-8"))
    return str(package_data["version"])


def read_hanzi_writer_bundle() -> str:
    version = read_hanzi_writer_package_version()
    bundle = HANZI_WRITER_BUNDLE.read_text(encoding="utf-8").strip()
    return "\n".join([
        f"/*! Hanzi Writer v{version} injected from npm package */",
        bundle,
    ])


def inject_hanzi_writer_bundle(template: str) -> str:
    start_marker = "    /*! Hanzi Writer v"
    script_start = template.find(start_marker)
    if script_start < 0:
        raise ValueError("Could not find embedded Hanzi Writer bundle start marker")

    script_end_marker = "\n</script>"
    script_end = template.find(script_end_marker, script_start)
    if script_end < 0:
        raise ValueError("Could not find embedded Hanzi Writer bundle end marker")

    injected_bundle = read_hanzi_writer_bundle()
    indented_bundle = "\n".join(
        f"    {line}" if line else ""
        for line in injected_bundle.splitlines()
    )
    return template[:script_start] + indented_bundle + template[script_end:]


def read_template(card_type: str, path: str | Path) -> str:
    template = read_text(path)
    if card_type == "Write":
        return inject_hanzi_writer_bundle(template)
    return template


def normalize_field(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", "", value).strip().lower()


def dedupe_key(entry: WordEntry) -> tuple[str, str]:
    return normalize_field(entry.simplified), normalize_field(entry.pinyin)


def read_word_file(path: Path, source: str) -> list[WordEntry]:
    entries: list[WordEntry] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if not row:
                continue
            if row[0].startswith("#"):
                continue
            if len(row) < 8:
                raise ValueError(f"Expected at least 8 TSV columns in {path}, got {len(row)}: {row!r}")
            entries.append(
                WordEntry(
                    simplified=row[0],
                    traditional=row[1],
                    pinyin=row[2],
                    zhuyin=row[3],
                    level=row[4],
                    pos=row[5],
                    frequency=row[6],
                    definition_html=row[7],
                    source=source,
                )
            )
    return entries


def load_hsk_entries() -> tuple[dict[str, list[WordEntry]], set[tuple[str, str]], list[dict[str, str]]]:
    kept_by_key: dict[tuple[str, str], WordEntry] = {}
    kept_by_level: dict[str, list[WordEntry]] = {level: [] for level in LEVELS}
    dropped_duplicates: list[dict[str, str]] = []

    for level in LEVELS:
        path = HSK_DATA_DIR / f"HSK_Level_{level}.txt"
        for entry in read_word_file(path, source=f"HSK {level}"):
            key = dedupe_key(entry)
            existing = kept_by_key.get(key)
            if existing:
                dropped_duplicates.append(
                    {
                        "simplified": entry.simplified,
                        "pinyin": entry.pinyin,
                        "dropped_source": entry.source,
                        "dropped_level": entry.level,
                        "kept_source": existing.source,
                        "kept_level": existing.level,
                        "dropped_pinyin": entry.pinyin,
                        "kept_pinyin": existing.pinyin,
                    }
                )
                continue
            kept_by_key[key] = entry
            kept_by_level[level].append(entry)

    return kept_by_level, set(kept_by_key), dropped_duplicates


def load_extra_entries(hsk_keys: set[tuple[str, str]]) -> tuple[list[WordEntry], list[dict[str, str]]]:
    if not EXTRA_WORDS_PATH.exists():
        return [], []

    entries: list[WordEntry] = []
    skipped_duplicates: list[dict[str, str]] = []
    seen_extra_keys: set[tuple[str, str]] = set()

    for entry in read_word_file(EXTRA_WORDS_PATH, source="Extra"):
        key = dedupe_key(entry)
        if key in hsk_keys or key in seen_extra_keys:
            skipped_duplicates.append(
                {
                    "simplified": entry.simplified,
                    "pinyin": entry.pinyin,
                    "level": entry.level,
                    "reason": "already present in HSK data" if key in hsk_keys else "duplicate Extra entry",
                }
            )
            continue
        seen_extra_keys.add(key)
        entries.append(entry)

    return entries, skipped_duplicates


def create_models() -> dict[str, genanki.Model]:
    css = read_text(CARD_TEMPLATES_DIR / "styling-xiehanzi-3.0.css")
    models: dict[str, genanki.Model] = {}

    for card_type in CARD_TYPES:
        front_path, back_path = TEMPLATE_FILES[card_type]
        model_name = f"Basic - New HSK (2025) - {card_type.lower()}"
        models[card_type] = genanki.Model(
            model_id=stable_id(f"model:{model_name}"),
            name=model_name,
            fields=FIELDS,
            templates=[
                {
                    "name": f"Card 1 - {card_type}",
                    "qfmt": read_template(card_type, front_path),
                    "afmt": read_text(back_path),
                }
            ],
            css=css,
        )

    return models


def create_deck(deck_name: str, model: genanki.Model, entries: list[WordEntry]) -> genanki.Deck:
    deck = genanki.Deck(stable_id(f"deck:{deck_name}"), deck_name)
    for entry in entries:
        deck.add_note(genanki.Note(model=model, fields=entry.fields()))
    return deck


def build_decks(models: dict[str, genanki.Model], hsk_entries: dict[str, list[WordEntry]], extra_entries: list[WordEntry]) -> list[genanki.Deck]:
    decks: list[genanki.Deck] = []

    for level in LEVELS:
        entries = hsk_entries[level]
        for card_type in CARD_TYPES:
            decks.append(
                create_deck(
                    deck_name=f"{DECK_ROOT}::HSK {level}::{card_type}",
                    model=models[card_type],
                    entries=entries,
                )
            )

    if extra_entries:
        for card_type in CARD_TYPES:
            decks.append(
                create_deck(
                    deck_name=f"{DECK_ROOT}::Extra::{card_type}",
                    model=models[card_type],
                    entries=extra_entries,
                )
            )

    return decks


def find_audio_path(entry: WordEntry) -> Path | None:
    candidates = [
        AUDIO_DIR / f"cmn-{entry.simplified}.mp3",
        EXTRA_AUDIO_DIR / f"cmn-{entry.simplified}.mp3",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def generated_audio_path(entry: WordEntry) -> Path:
    return EXTRA_AUDIO_DIR / f"cmn-{entry.simplified}.mp3"


def remove_zero_length_audio_files() -> list[str]:
    removed: list[str] = []
    for folder in (AUDIO_DIR, EXTRA_AUDIO_DIR):
        if not folder.exists():
            continue
        for path in folder.glob("*.mp3"):
            if path.stat().st_size == 0:
                path.unlink()
                removed.append(str(path))
    return removed


def remove_failed_audio_output(path: Path) -> None:
    if path.exists() and path.stat().st_size == 0:
        path.unlink()


def generate_missing_audio(entries: list[WordEntry]) -> tuple[list[str], list[dict[str, str]], list[str]]:
    removed_zero_length = remove_zero_length_audio_files()
    generated: list[str] = []
    failed: list[dict[str, str]] = []
    seen_words: set[str] = set()

    for entry in entries:
        if find_audio_path(entry):
            continue
        word = entry.simplified.strip()
        if not word or word in seen_words:
            continue
        seen_words.add(word)

        output_path = generated_audio_path(entry)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            communicate = edge_tts.Communicate(word, VOICE)
            communicate.save_sync(str(output_path))
            if output_path.exists() and output_path.stat().st_size > 0:
                generated.append(str(output_path))
            else:
                remove_failed_audio_output(output_path)
                failed.append({
                    "word": word,
                    "file": str(output_path),
                    "error": "edge-tts produced no audio data",
                })
        except Exception as exc:
            remove_failed_audio_output(output_path)
            failed.append({
                "word": word,
                "file": str(output_path),
                "error": str(exc),
            })

    return generated, failed, removed_zero_length


def collect_media(entries: list[WordEntry]) -> tuple[list[str], list[str]]:
    media = list(STATIC_MEDIA)
    missing_audio: list[str] = []
    seen_media_names = {Path(path).name for path in media}

    for entry in entries:
        audio_path = find_audio_path(entry)
        if audio_path:
            audio = str(audio_path)
            media_name = audio_path.name
            if media_name not in seen_media_names:
                seen_media_names.add(media_name)
                media.append(audio)
        else:
            missing_audio.append(f"cmn-{entry.simplified}.mp3")

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
    zip_generated_datetime: tuple[int, int, int, int, int, int] | None,
) -> None:
    if zip_generated_datetime is None:
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

        rewrite_generated_zip_datetimes(
            source=temporary_path,
            output=output_apkg,
            generated_datetime=zip_generated_datetime,
        )
    finally:
        temporary_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timestamp",
        type=float,
        default=None,
        help="Optional fixed genanki timestamp for deterministic comparison builds.",
    )
    parser.add_argument(
        "--zip-generated-datetime",
        type=parse_zip_datetime,
        default=None,
        help="Optionally set ZIP timestamps for generated members collection.anki2 and media. Format: YYYY-MM-DDTHH:MM:SS.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    hsk_entries, hsk_keys, dropped_duplicates = load_hsk_entries()
    extra_entries, skipped_extra_duplicates = load_extra_entries(hsk_keys)
    all_entries = [entry for level in LEVELS for entry in hsk_entries[level]] + extra_entries

    generated_audio, failed_audio_generation, removed_zero_length_audio = generate_missing_audio(all_entries)
    models = create_models()
    decks = build_decks(models, hsk_entries, extra_entries)
    media_files, missing_audio = collect_media(all_entries)

    write_package(
        genanki.Package(decks, media_files=media_files),
        output_apkg=OUTPUT_APKG,
        timestamp=args.timestamp,
        zip_generated_datetime=args.zip_generated_datetime,
    )

    report = {
        "output": str(OUTPUT_APKG),
        "report": str(REPORT_PATH),
        "deck_root": DECK_ROOT,
        "card_types": CARD_TYPES,
        "dedupe_key": "Simplified + normalized Pinyin",
        "hsk_words_after_dedupe": sum(len(hsk_entries[level]) for level in LEVELS),
        "extra_words": len(extra_entries),
        "total_words": len(all_entries),
        "total_cards": len(all_entries) * len(CARD_TYPES),
        "decks": len(decks),
        "audio_files_packaged": len(media_files) - len(STATIC_MEDIA),
        "audio_voice": VOICE,
        "hanzi_writer_version": read_hanzi_writer_package_version(),
        "hanzi_writer_bundle": str(HANZI_WRITER_BUNDLE),
        "generated_audio_files": generated_audio,
        "failed_audio_generation": failed_audio_generation,
        "removed_zero_length_audio_files": removed_zero_length_audio,
        "dropped_duplicate_occurrences": len(dropped_duplicates),
        "dropped_duplicates": dropped_duplicates,
        "skipped_extra_duplicate_occurrences": len(skipped_extra_duplicates),
        "skipped_extra_duplicates": skipped_extra_duplicates,
        "missing_audio_files": missing_audio,
        "hsk_counts": {level: len(hsk_entries[level]) for level in LEVELS},
        "timestamp": args.timestamp,
        "zip_generated_datetime": args.zip_generated_datetime,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    console_report = {
        key: value
        for key, value in report.items()
        if key not in {"dropped_duplicates", "skipped_extra_duplicates"}
    }
    print(json.dumps(console_report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
