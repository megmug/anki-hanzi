"""Deck configuration data structures and parser."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anki_hanzi.deck import common
from anki_hanzi.paths import DEFAULT_DECK_CONFIG


SUPPORTED_SELECTION_MODES = {"all", "tagged"}
SUPPORTED_SELECTION_FIELDS = {"individual_simplified", "mode", "tags"}


@dataclass(frozen=True)
class AudioConfig:
    engine: str = "off"  # "kokoro", "edge_tts", or "off"


@dataclass(frozen=True)
class DeckSelection:
    mode: str = ""
    tags: tuple[str, ...] = ()
    individual_simplified: frozenset[str] = frozenset()
    config_path: str | None = None
    config_found: bool = False

    def report(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "config_found": self.config_found,
            "mode": self.mode,
            "tags": list(self.tags),
            "individual_simplified": sorted(self.individual_simplified),
        }


DEFAULT_CARD_SETTINGS: dict[str, dict[str, dict[str, Any]]] = {
    "Meaning": {
        "front": {
            "show_pinyin": True,
            "show_meaning": True,
            "show_simplified": True,
        },
        "back": {
            "show_pinyin": True,
            "show_meaning": True,
            "show_simplified": True,
        },
    },
    "Pinyin": {
        "front": {
            "show_pinyin": True,
            "show_meaning": True,
            "show_simplified": True,
        },
        "back": {
            "show_pinyin": True,
            "show_meaning": True,
            "show_simplified": True,
        },
    },
    "Write": {
        "front": {
            "show_pinyin": True,
            "show_meaning": True,
            "show_simplified": False,
            "show_grid": False,
            "show_outline": False,
            "stroke_tone_color": True,
            "grid_size": 400,
            "stroke_width": 64,
            "hint_after_misses": 0,
            "stroke_leniency": 0.8,
        },
        "back": {
            "show_pinyin": True,
            "show_meaning": True,
            "show_simplified": True,
            "show_grid": False,
            "show_outline": False,
            "stroke_tone_color": True,
            "grid_size": 400,
            "stroke_width": 64,
            "hint_after_misses": 0,
            "stroke_leniency": 0.8,
        },
    },
}


def default_card_settings() -> dict[str, dict[str, dict[str, Any]]]:
    return deepcopy(DEFAULT_CARD_SETTINGS)


@dataclass(frozen=True)
class DeckConfig:
    card_types: tuple[str, ...] = tuple(common.CARD_TYPES)
    audio: AudioConfig = field(default_factory=AudioConfig)
    card_settings: dict[str, dict[str, dict[str, Any]]] = field(default_factory=default_card_settings)
    selection: DeckSelection = field(default_factory=DeckSelection)

    def card_settings_json(self, card_type: str) -> str:
        return json.dumps(
            self.card_settings.get(card_type, {}),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def load_deck_config(path: Path | None = None) -> DeckConfig:
    if path is None:
        path = DEFAULT_DECK_CONFIG
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("deck config must be an object")
    defaults = DeckConfig()
    selection = raw.get("selection")
    if selection is None:
        raise ValueError("deck config must define a 'selection' object")
    if not isinstance(selection, dict):
        raise ValueError("deck config selection must be an object")

    return DeckConfig(
        card_types=merge_card_types(raw.get("card_types"), defaults.card_types),
        audio=merge_audio_config(raw.get("audio"), defaults.audio),
        card_settings=merge_card_settings(raw.get("card_settings"), defaults.card_settings),
        selection=parse_deck_selection(selection, path),
    )


def parse_deck_selection(raw: dict[str, Any], config_path: Path) -> DeckSelection:
    unknown_keys = sorted(set(raw) - SUPPORTED_SELECTION_FIELDS)
    if unknown_keys:
        raise ValueError(f"deck config selection has unknown setting: {', '.join(unknown_keys)}")

    mode = raw.get("mode")
    if not isinstance(mode, str) or mode not in SUPPORTED_SELECTION_MODES:
        raise ValueError(
            f"deck config selection.mode must be one of: {', '.join(sorted(SUPPORTED_SELECTION_MODES))}"
        )

    tags_raw = raw.get("tags", [])
    if isinstance(tags_raw, str):
        tags = (tags_raw,)
    elif isinstance(tags_raw, list):
        if not all(isinstance(tag, str) for tag in tags_raw):
            raise ValueError("deck config selection.tags must be a string or a list of strings")
        tags = tuple(tags_raw)
    else:
        raise ValueError("deck config selection.tags must be a string or a list of strings")

    return DeckSelection(
        mode=mode,
        tags=tags,
        individual_simplified=parse_simplified_list(
            raw.get("individual_simplified", []),
            "individual_simplified",
        ),
        config_path=str(config_path),
        config_found=True,
    )


def parse_simplified_list(value: Any, field_name: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, list):
        raise ValueError(f"deck config selection.{field_name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"deck config selection.{field_name} must be a list of strings")
    return frozenset(simplified for simplified in (item.strip() for item in value) if simplified)


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
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"deck config {field_name} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"deck config {field_name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"deck config {field_name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"deck config {field_name} must be between {minimum} and {maximum}")
    return parsed


def parse_float(value: Any, field_name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"deck config {field_name} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"deck config {field_name} must be a number") from exc
    if not math.isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise ValueError(f"deck config {field_name} must be between {minimum} and {maximum}")
    return parsed


SUPPORTED_AUDIO_ENGINES = {"off", "kokoro", "edge_tts"}


def normalize_audio_engine(value: Any, field_name: str) -> str:
    engine = str(value or "").strip().casefold().replace("-", "_")
    if engine not in SUPPORTED_AUDIO_ENGINES:
        raise ValueError(f"deck config {field_name} must be one of: {', '.join(sorted(SUPPORTED_AUDIO_ENGINES))}")
    return engine


def merge_audio_config(raw: Any, default: AudioConfig) -> AudioConfig:
    if raw is None:
        return default
    if not isinstance(raw, dict):
        raise ValueError("deck config audio must be an object")

    unknown_keys = sorted(set(raw) - {"engine"})
    if unknown_keys:
        raise ValueError(f"deck config audio has unknown setting: {', '.join(unknown_keys)}")

    return AudioConfig(
        engine=normalize_audio_engine(raw.get("engine", default.engine), "audio.engine"),
    )


def merge_card_types(raw: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return default
    if not isinstance(raw, list):
        raise ValueError("deck config card_types must be a list")
    if not raw:
        raise ValueError("deck config card_types must not be empty")
    if not all(isinstance(card_type, str) for card_type in raw):
        raise ValueError("deck config card_types must be a list of strings")

    card_types = tuple(raw)
    unknown_card_types = sorted(set(card_types) - set(common.CARD_TYPES))
    if unknown_card_types:
        raise ValueError(f"deck config card_types has unknown card type: {', '.join(unknown_card_types)}")
    if len(card_types) != len(set(card_types)):
        raise ValueError("deck config card_types must not contain duplicates")
    return card_types


def normalize_card_setting(value: Any, field_name: str) -> Any:
    if field_name.endswith(".grid_size"):
        return parse_int(value, field_name, 100, 1000)
    if field_name.endswith(".stroke_width"):
        return parse_int(value, field_name, 2, 100)
    if field_name.endswith(".hint_after_misses"):
        return parse_int(value, field_name, 0, 10)
    if field_name.endswith(".stroke_leniency"):
        return parse_float(value, field_name, 0.1, 2.0)
    return parse_bool(value, field_name)


def merge_card_settings(
    raw: Any,
    default: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    settings = deepcopy(default) if default is not None else default_card_settings()
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
                    raise ValueError(f"deck config card_settings.{card_type}.{side} has unknown setting: {key}")
                field_name = f"card_settings.{card_type}.{side}.{key}"
                settings[card_type][side][key] = normalize_card_setting(value, field_name)

    return settings
