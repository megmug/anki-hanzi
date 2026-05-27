#!/usr/bin/env python

"""Shared helpers for building the custom hanzi APKG."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import genanki


DECK_ROOT = "汉字 (Hànzì)"
OUTPUT_APKG = Path("anki-hanzi.apkg")
DECK_INPUTS_DIR = Path("deck_inputs")
CARD_TEMPLATES_DIR = DECK_INPUTS_DIR / "card_templates"
AUDIO_DIR = DECK_INPUTS_DIR / "hsk-3.0-words-list/New HSK (2025)/Audio"
EXTRA_AUDIO_DIR = DECK_INPUTS_DIR / "extra_audio"
HANZI_WRITER_PACKAGE_JSON = Path("node_modules/hanzi-writer/package.json")
HANZI_WRITER_BUNDLE = Path("node_modules/hanzi-writer/dist/hanzi-writer.min.js")
HANZI_WRITER_DATA_DIR = Path("node_modules/hanzi-writer-data")
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
    {"name": "NoteID"},
    {"name": "BuildID"},
]

TEMPLATE_FILES = {
    "Meaning": (CARD_TEMPLATES_DIR / "meaning/front.html", CARD_TEMPLATES_DIR / "meaning/back.html"),
    "Pinyin": (CARD_TEMPLATES_DIR / "pinyin/front.html", CARD_TEMPLATES_DIR / "pinyin/back.html"),
    "Write": (CARD_TEMPLATES_DIR / "write/front.html", CARD_TEMPLATES_DIR / "write/back.html"),
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


DEFAULT_CONFIG_PATH = DECK_INPUTS_DIR / "deck_config.json"


# Hardcoded voice pools — not configurable per deck to keep builds predictable
KOKORO_FEMALE_VOICES = ("zf_xiaoxiao", "zf_xiaoni", "zf_xiaobei", "zf_xiaoyi")
KOKORO_MALE_VOICES = ("zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang")
# edge-tts: only voices verified to actually return audio (many zh-CN voices fail)
EDGE_TTS_FEMALE_VOICES = (
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-XiaoyiNeural",
)
EDGE_TTS_MALE_VOICES = (
    "zh-CN-YunjianNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunxiaNeural",
)
AUDIO_FILENAME_FEMALE = "cmn-{simplified}_f.mp3"
AUDIO_FILENAME_MALE = "cmn-{simplified}_m.mp3"


@dataclass(frozen=True)
class AudioConfig:
    engine: str = "kokoro"  # "kokoro" or "edge_tts"


DEFAULT_CARD_SETTINGS: dict[str, dict[str, dict[str, Any]]] = {
    "Meaning": {
        "front": {
            "show_pinyin": True,
            "show_zhuyin": False,
            "show_meaning": True,
            "show_simplified": True,
            "show_traditional": False,
        },
        "back": {
            "show_pinyin": True,
            "show_zhuyin": False,
            "show_meaning": True,
            "show_simplified": True,
            "show_traditional": False,
        },
    },
    "Pinyin": {
        "front": {
            "show_pinyin": True,
            "show_zhuyin": False,
            "show_meaning": True,
            "show_simplified": True,
            "show_traditional": False,
        },
        "back": {
            "show_pinyin": True,
            "show_zhuyin": False,
            "show_meaning": True,
            "show_simplified": True,
            "show_traditional": False,
        },
    },
    "Write": {
        "front": {
            "practice": "simplified",
            "show_pinyin": True,
            "show_meaning": True,
            "show_simplified": False,
            "show_traditional": False,
            "show_grid": False,
            "show_outline": False,
            "stroke_tone_color": True,
            "grid_size": 400,
            "stroke_width": 64,
            "hint_after_misses": 0,
        },
        "back": {
            "practice": "simplified",
            "show_pinyin": True,
            "show_meaning": True,
            "show_simplified": True,
            "show_traditional": False,
            "show_grid": False,
            "show_outline": False,
            "stroke_tone_color": True,
            "grid_size": 400,
            "stroke_width": 64,
            "hint_after_misses": 0,
        },
    },
}


def default_card_settings() -> dict[str, dict[str, dict[str, Any]]]:
    return deepcopy(DEFAULT_CARD_SETTINGS)


@dataclass(frozen=True)
class DeckConfig:
    card_types: tuple[str, ...] = tuple(CARD_TYPES)
    audio: AudioConfig = field(default_factory=AudioConfig)
    card_settings: dict[str, dict[str, dict[str, Any]]] = field(default_factory=default_card_settings)
    mode: str = ""
    tags: tuple[str, ...] = ()
    individual_simplified: frozenset[str] = frozenset()

    def audio_filenames(self, simplified: str) -> tuple[str, str]:
        return (
            AUDIO_FILENAME_FEMALE.format(simplified=simplified),
            AUDIO_FILENAME_MALE.format(simplified=simplified),
        )

    def template_files(self, card_type: str) -> tuple[Path, Path]:
        mapping = {
            "Meaning": (CARD_TEMPLATES_DIR / "meaning/front.html", CARD_TEMPLATES_DIR / "meaning/back.html"),
            "Pinyin": (CARD_TEMPLATES_DIR / "pinyin/front.html", CARD_TEMPLATES_DIR / "pinyin/back.html"),
            "Write": (CARD_TEMPLATES_DIR / "write/front.html", CARD_TEMPLATES_DIR / "write/back.html"),
        }
        if card_type not in mapping:
            raise ValueError(f"unknown card type: {card_type}")
        return mapping[card_type]

    def static_media(self) -> list[str]:
        return [
            str(CARD_TEMPLATES_DIR / "fonts/_MaterialIcons-Regular.woff"),
            str(CARD_TEMPLATES_DIR / "fonts/_MaterialIcons-Regular.woff2"),
            str(CARD_TEMPLATES_DIR / "files/_pleco.png"),
            str(CARD_TEMPLATES_DIR / "files/_youdao.png"),
            str(CARD_TEMPLATES_DIR / "files/_rtega.png"),
            str(CARD_TEMPLATES_DIR / "files/_tatoeba.png"),
            str(CARD_TEMPLATES_DIR / "files/_hanzicraft.png"),
            str(CARD_TEMPLATES_DIR / "files/_characterpop.svg"),
        ]

    def card_settings_json(self, card_type: str) -> str:
        return json.dumps(
            self.card_settings.get(card_type, {}),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def load_deck_config(path: Path | None = None) -> DeckConfig:
    if path is None:
        path = DEFAULT_CONFIG_PATH
    if not path.exists():
        return DeckConfig()

    raw = json.loads(path.read_text(encoding="utf-8"))
    selection = raw.get("selection", {})

    individual_simplified: frozenset[str] = frozenset()
    raw_individual = selection.get("individual_simplified", [])
    if isinstance(raw_individual, list):
        individual_simplified = frozenset(
            s for s in (str(item).strip() for item in raw_individual) if s
        )

    tags_raw = selection.get("tags", [])
    if isinstance(tags_raw, str):
        tags = (tags_raw,)
    elif isinstance(tags_raw, list):
        tags = tuple(str(t) for t in tags_raw)
    else:
        tags = ()

    audio_raw = raw.get("audio")
    if audio_raw is None:
        audio = AudioConfig(engine="off")
    else:
        audio = AudioConfig(
            engine=str(audio_raw.get("engine", AudioConfig.engine)),
        )

    return DeckConfig(
        card_types=tuple(raw.get("card_types", CARD_TYPES)),
        audio=audio,
        card_settings=merge_card_settings(raw.get("card_settings")),
        mode=str(selection.get("mode", "")),
        tags=tags,
        individual_simplified=individual_simplified,
    )


def parse_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"deck config {field_name} must be boolean")


def parse_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"deck config {field_name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"deck config {field_name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"deck config {field_name} must be between {minimum} and {maximum}")
    return parsed


def normalize_card_setting(value: Any, field_name: str) -> Any:
    if field_name.endswith(".practice"):
        practice = str(value).strip().casefold()
        if practice not in {"simplified", "traditional"}:
            raise ValueError(f"deck config {field_name} must be 'simplified' or 'traditional'")
        return practice
    if field_name.endswith(".grid_size"):
        return parse_int(value, field_name, 100, 1000)
    if field_name.endswith(".stroke_width"):
        return parse_int(value, field_name, 2, 100)
    if field_name.endswith(".hint_after_misses"):
        return parse_int(value, field_name, 0, 10)
    return parse_bool(value, field_name)


def merge_card_settings(raw: Any) -> dict[str, dict[str, dict[str, Any]]]:
    settings = default_card_settings()
    if raw is None:
        return settings
    if not isinstance(raw, dict):
        raise ValueError("deck config card_settings must be an object")

    for card_type, card_settings in raw.items():
        if card_type not in settings:
            raise ValueError(f"deck config card_settings has unknown card type: {card_type}")
        if not isinstance(card_settings, dict):
            raise ValueError(f"deck config card_settings.{card_type} must be an object")
        for side, side_settings in card_settings.items():
            if side not in settings[card_type]:
                raise ValueError(f"deck config card_settings.{card_type} has unknown side: {side}")
            if not isinstance(side_settings, dict):
                raise ValueError(f"deck config card_settings.{card_type}.{side} must be an object")
            for key, value in side_settings.items():
                if key not in settings[card_type][side]:
                    raise ValueError(
                        f"deck config card_settings.{card_type}.{side} has unknown setting: {key}"
                    )
                field_name = f"card_settings.{card_type}.{side}.{key}"
                settings[card_type][side][key] = normalize_card_setting(value, field_name)

    return settings


class NoteEntry(Protocol):
    def fields(self, card_type: str, build_id: str) -> list[str]:
        ...

    @property
    def tags(self) -> tuple[str, ...]:
        ...


def stable_id(label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    return (int.from_bytes(digest[:4], "big") % (1 << 30)) + (1 << 30)


def stable_hex_id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def normalized_note_pinyin(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def stable_note_id(card_type: str, simplified: str, pinyin: str) -> str:
    return stable_hex_id(
        f"{card_type}\0{str(simplified or '').strip()}\0{normalized_note_pinyin(pinyin)}"
    )


def stable_note_guid(note_id: str) -> str:
    return genanki.guid_for(str(note_id or "").strip())


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


def inject_hanzi_data_bundle(template: str, bundle_path: Path) -> str:
    """Inject hanzi-writer-data JS bundle directly into the template as inline script."""
    if not bundle_path.exists():
        return template
    
    bundle = bundle_path.read_text(encoding="utf-8")
    # Find a good insertion point - after the hanzi-writer bundle script
    marker = "</script>"
    # Find the 3rd </script> (after Persistence, hanzi-writer bundle, and colorize-pinyin)
    pos = 0
    for _ in range(3):
        pos = template.find(marker, pos)
        if pos < 0:
            break
        pos += len(marker)
    
    if pos < 0:
        # Fallback: insert before </body> or at the end
        pos = template.find("</body>")
        if pos < 0:
            pos = len(template)
    
    inline_script = f"\n<script>\n{bundle}\n</script>\n"
    return template[:pos] + inline_script + template[pos:]


def inject_card_settings(template: str, card_type: str, config: DeckConfig) -> str:
    return template.replace("__HANZI_CARD_SETTINGS__", config.card_settings_json(card_type))


def read_template(
    card_type: str,
    path: str | Path,
    config: DeckConfig,
    hw_data_bundle: Path | None = None,
) -> str:
    template = read_text(path)
    template = inject_card_settings(template, card_type, config)
    if card_type == "Write" and "/*! Hanzi Writer v" in template:
        template = inject_hanzi_writer_bundle(template)
        if hw_data_bundle:
            template = inject_hanzi_data_bundle(template, hw_data_bundle)
    return template


def create_models(config: DeckConfig | None = None, hw_data_bundle: Path | None = None) -> dict[str, genanki.Model]:
    if config is None:
        config = DeckConfig()
    css = read_text(CARD_TEMPLATES_DIR / "styling-hanzi-3.0.css")
    models: dict[str, genanki.Model] = {}

    for card_type in config.card_types:
        front_path, back_path = config.template_files(card_type)
        model_name = f"{DECK_ROOT}::{card_type}"
        models[card_type] = genanki.Model(
            model_id=stable_id(f"model:{model_name}"),
            name=model_name,
            fields=FIELDS,
            templates=[
                {
                    "name": f"Card 1 - {card_type}",
                    "qfmt": read_template(card_type, front_path, config, hw_data_bundle),
                    "afmt": read_template(card_type, back_path, config),
                }
            ],
            css=css,
        )

    return models


def create_deck(
    deck_name: str,
    card_type: str,
    model: genanki.Model,
    entries: list[NoteEntry],
    build_id: str,
) -> genanki.Deck:
    deck = genanki.Deck(stable_id(f"deck:{deck_name}"), deck_name)
    for entry in entries:
        fields = entry.fields(card_type, build_id)
        note_id = fields[7]
        deck.add_note(
            genanki.Note(
                model=model,
                fields=fields,
                tags=list(entry.tags),
                guid=stable_note_guid(note_id),
            )
        )
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
