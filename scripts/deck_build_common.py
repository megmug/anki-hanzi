#!/usr/bin/env python

"""Shared helpers for building the custom xiehanzi APKG."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

import genanki


DECK_ROOT = "Anki Xiehanzi - New HSK (2025)"
OUTPUT_APKG = Path("Anki-xiehanzi - New HSK (2025).apkg")
DECK_INPUTS_DIR = Path("deck_inputs")
CARD_TEMPLATES_DIR = DECK_INPUTS_DIR / "card_templates"
AUDIO_DIR = DECK_INPUTS_DIR / "hsk-3.0-words-list/New HSK (2025)/Audio"
EXTRA_AUDIO_DIR = DECK_INPUTS_DIR / "extra_audio"
HANZI_WRITER_PACKAGE_JSON = Path("node_modules/hanzi-writer/package.json")
HANZI_WRITER_BUNDLE = Path("node_modules/hanzi-writer/dist/hanzi-writer.min.js")
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


class NoteEntry(Protocol):
    def fields(self) -> list[str]:
        ...


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


def create_deck(deck_name: str, model: genanki.Model, entries: list[NoteEntry]) -> genanki.Deck:
    deck = genanki.Deck(stable_id(f"deck:{deck_name}"), deck_name)
    for entry in entries:
        deck.add_note(genanki.Note(model=model, fields=entry.fields()))
    return deck


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
