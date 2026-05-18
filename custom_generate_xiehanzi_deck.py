#!/usr/bin/env python

"""
Build a customized xiehanzi APKG from the prepared New HSK (2025) word files.

Differences from the notebook release build:
- does not generate Audio cards/decks
- keeps Meaning, Pinyin, and Write cards
- still packages audio files because the remaining card templates use `{{Audio}}`
- generates missing audio with edge-tts, matching the notebook's voice
- deduplicates HSK entries by Simplified + Pinyin, keeping the lowest HSK level
- adds optional Extra entries from `extra_words.tsv`

`extra_words.tsv` uses the same eight columns as the prepared HSK files:
Simplified, Traditional, Pinyin, Zhuyin, Level, PoS, Frequency, Meaning HTML.
Generated/custom audio is cached in `extra_audio/cmn-<Simplified>.mp3`.

Run from the repository root inside the Nix shell:

    nix-shell --run "python custom_generate_xiehanzi_deck.py"
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import genanki


DECK_ROOT = "Anki Xiehanzi - New HSK (2025)"
OUTPUT_APKG = Path("Anki-xiehanzi - New HSK (2025).apkg")
REPORT_PATH = Path("custom_generate_xiehanzi_report.json")
HSK_DATA_DIR = Path("HSK-3.0-words-list/New HSK (2025)/Anki xiehanzi")
AUDIO_DIR = Path("HSK-3.0-words-list/New HSK (2025)/Audio")
EXTRA_AUDIO_DIR = Path("extra_audio")
EXTRA_WORDS_PATH = Path("extra_words.tsv")
VOICE = "zh-CN-XiaoxiaoNeural"

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
    "Meaning": ("card templates/Card 1/front.html", "card templates/Card 1/back.html"),
    "Pinyin": ("card templates/Card 2/front.html", "card templates/Card 2/back.html"),
    "Write": ("card templates/Card 5/front-xiehanzi-3.0.html", "card templates/Card 5/back.html"),
}

STATIC_MEDIA = [
    "card templates/fonts/_MaterialIcons-Regular.woff",
    "card templates/fonts/_MaterialIcons-Regular.woff2",
    "card templates/files/_pleco.png",
    "card templates/files/_youdao.png",
    "card templates/files/_rtega.png",
    "card templates/files/_tatoeba.png",
    "card templates/files/_hanzicraft.png",
    "card templates/files/_characterpop.svg",
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
    css = read_text("card templates/styling-xiehanzi-3.0.css")
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
                    "qfmt": read_text(front_path),
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
                failed.append({
                    "word": word,
                    "file": str(output_path),
                    "error": "edge-tts produced no audio data",
                })
        except Exception as exc:
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


def main() -> None:
    hsk_entries, hsk_keys, dropped_duplicates = load_hsk_entries()
    extra_entries, skipped_extra_duplicates = load_extra_entries(hsk_keys)
    all_entries = [entry for level in LEVELS for entry in hsk_entries[level]] + extra_entries

    generated_audio, failed_audio_generation, removed_zero_length_audio = generate_missing_audio(all_entries)
    models = create_models()
    decks = build_decks(models, hsk_entries, extra_entries)
    media_files, missing_audio = collect_media(all_entries)

    genanki.Package(decks, media_files=media_files).write_to_file(str(OUTPUT_APKG))

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
        "generated_audio_files": generated_audio,
        "failed_audio_generation": failed_audio_generation,
        "removed_zero_length_audio_files": removed_zero_length_audio,
        "dropped_duplicate_occurrences": len(dropped_duplicates),
        "dropped_duplicates": dropped_duplicates,
        "skipped_extra_duplicate_occurrences": len(skipped_extra_duplicates),
        "skipped_extra_duplicates": skipped_extra_duplicates,
        "missing_audio_files": missing_audio,
        "hsk_counts": {level: len(hsk_entries[level]) for level in LEVELS},
    }
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
