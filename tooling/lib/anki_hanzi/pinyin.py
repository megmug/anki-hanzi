"""Shared Pinyin normalization, tokenization, and display helpers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from dragonmapper import transcriptions


PINYIN_SEPARATOR_RE = re.compile(r"[\s'’·-]+")
PINYIN_NUMBERED_TOKEN_RE = re.compile(r"[A-Za-züÜv:]+[1-5]?")


@dataclass(frozen=True)
class CanonicalPinyinReading:
    spaced: str
    compact: str
    lower_compact: str


def normalize_single_pinyin(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def split_pinyin_readings(value: Any) -> list[str]:
    readings: list[str] = []
    values = value if isinstance(value, list) else [value]

    for item in values:
        for part in re.split(r"/", str(item or "")):
            reading = normalize_single_pinyin(part)
            if reading and reading not in readings:
                readings.append(reading)
    return readings


def sorted_pinyin_readings(values: list[str]) -> list[str]:
    return sorted(dict.fromkeys(values), key=lambda value: (value.casefold(), value))


def normalize_pinyin_u_variants(value: str) -> str:
    return value.replace("ü", "v").replace("Ü", "V").replace("u:", "v").replace("U:", "V")


def strict_numbered_preserve_case(value: str) -> str:
    value = unicodedata.normalize("NFC", normalize_single_pinyin(value))
    if not value:
        return ""
    return normalize_pinyin_u_variants(numbered_pinyin(value))


def numbered_pinyin(value: str) -> str:
    if re.search(r"\d", value):
        return normalize_pinyin_u_variants(value)
    try:
        return transcriptions.accented_to_numbered(value)
    except ValueError:
        return value


def numbered_pinyin_part(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value or "").strip())
    if not value:
        return ""
    return normalize_pinyin_u_variants(numbered_pinyin(value))


def canonical_pinyin_readings(value: str) -> list[CanonicalPinyinReading]:
    readings: list[CanonicalPinyinReading] = []
    for part in re.split(r"/", value or ""):
        numbered = numbered_pinyin_part(part)
        if not numbered:
            continue

        spaced = PINYIN_SEPARATOR_RE.sub(" ", numbered).strip()
        spaced = re.sub(r"\s+", " ", spaced)
        compact = spaced.replace(" ", "")
        if compact:
            readings.append(
                CanonicalPinyinReading(
                    spaced=spaced,
                    compact=compact,
                    lower_compact=compact.lower(),
                )
            )
    return readings


def numbered_pinyin_token_strings(value: str) -> list[str]:
    return PINYIN_NUMBERED_TOKEN_RE.findall(numbered_pinyin_part(value))


def numbered_pinyin_token_pairs(value: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for token in PINYIN_NUMBERED_TOKEN_RE.findall(value or ""):
        match = re.match(r"(.+?)([1-5])?$", token)
        if match is None:
            continue
        base = normalize_pinyin_u_variants(match.group(1)).casefold()
        tone = match.group(2) or ""
        tokens.append((base, tone))
    return tokens


def split_numbered_pinyin_token(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"([A-Za-züÜv:]+)([1-5]?)", value)
    if match is None:
        raise ValueError(f"Invalid numbered Pinyin token: {value!r}")
    return match.group(1), match.group(2)


def pinyin_base_key(value: str) -> str:
    return normalize_pinyin_u_variants(value).casefold()


def source_tone_on_reference_base(source_token: str, reference_token: str) -> str:
    source_base, source_tone = split_numbered_pinyin_token(source_token)
    reference_base, _ = split_numbered_pinyin_token(reference_token)
    if pinyin_base_key(source_base) != pinyin_base_key(reference_base):
        raise ValueError(
            f"Cannot align spoken-tone Pinyin token {source_token!r} with dictionary token {reference_token!r}"
        )
    return f"{reference_base}{source_tone}"


def source_pinyin_in_dictionary_format(source_pinyin: str, dictionary_pinyin: str) -> str:
    source_parts = [part for part in re.split(r"/", str(source_pinyin or "")) if part.strip()]
    dictionary_parts = [part for part in re.split(r"/", str(dictionary_pinyin or "")) if part.strip()]
    if len(source_parts) != len(dictionary_parts):
        raise ValueError(
            f"Cannot align spoken-tone Pinyin readings {source_pinyin!r} with dictionary readings {dictionary_pinyin!r}"
        )

    formatted_readings: list[str] = []
    for source_part, dictionary_part in zip(source_parts, dictionary_parts):
        source_tokens = numbered_pinyin_token_strings(source_part)
        dictionary_tokens = numbered_pinyin_token_strings(dictionary_part)
        if len(source_tokens) != len(dictionary_tokens):
            raise ValueError(
                f"Cannot align spoken-tone Pinyin syllables {source_part!r} with dictionary syllables "
                f"{dictionary_part!r}"
            )
        formatted_readings.append(
            " ".join(
                source_tone_on_reference_base(source_token, dictionary_token)
                for source_token, dictionary_token in zip(source_tokens, dictionary_tokens)
            )
        )

    return " / ".join(formatted_readings)


def pinyin_formatting_key(value: str) -> str:
    return "/".join(reading.compact for reading in canonical_pinyin_readings(value))


def apply_reference_pinyin_case(source_pinyin: str, reference_pinyin: str) -> str:
    reference_by_key = {
        reading.lower_compact: reading.compact for reading in canonical_pinyin_readings(reference_pinyin)
    }
    cased_tokens: list[str] = []

    for source_part in re.split(r"(/)", source_pinyin or ""):
        if source_part == "/":
            cased_tokens.append(source_part)
            continue

        leading_space = re.match(r"\s*", source_part).group(0)
        trailing_space = re.search(r"\s*$", source_part).group(0)
        stripped_source = source_part.strip()
        if not stripped_source:
            cased_tokens.append(source_part)
            continue

        numbered_source = numbered_pinyin_part(stripped_source)
        source_readings = canonical_pinyin_readings(numbered_source)
        if not source_readings:
            cased_tokens.append(source_part)
            continue

        reference_compact = reference_by_key.get(source_readings[0].lower_compact)
        if not reference_compact:
            cased_tokens.append(f"{leading_space}{numbered_source}{trailing_space}")
            continue

        chars = list(numbered_source)
        reference_index = 0
        for index, char in enumerate(chars):
            if PINYIN_SEPARATOR_RE.fullmatch(char):
                continue
            if reference_index >= len(reference_compact):
                break

            reference_char = reference_compact[reference_index]
            if char.isalpha() and reference_char.isalpha() and char.lower() == reference_char.lower():
                chars[index] = char.upper() if reference_char.isupper() else char.lower()
            reference_index += 1

        cased_tokens.append(f"{leading_space}{''.join(chars)}{trailing_space}")

    return "".join(cased_tokens)


def pinyin_reading_in_reference_spacing(reading: str, reference_pinyin: str) -> str:
    source_tokens = numbered_pinyin_token_strings(reading)
    if not source_tokens:
        return numbered_pinyin_part(reading)

    for reference_part in re.split(r"/", str(reference_pinyin or "")):
        reference_tokens = numbered_pinyin_token_strings(reference_part)
        if len(reference_tokens) != len(source_tokens):
            continue
        try:
            return " ".join(
                source_tone_on_reference_base(source_token, reference_token)
                for source_token, reference_token in zip(source_tokens, reference_tokens)
            )
        except ValueError:
            return " ".join(source_tokens)

    return " ".join(source_tokens)


def normalize_numbered_pinyin_token_for_display(value: str) -> str:
    return value.replace("u:", "ü").replace("U:", "Ü")


def numbered_to_display(value: str) -> str:
    """Convert numbered Pinyin to the display form used by hanzi HTML."""

    parts: list[str] = []
    for part in re.split(r"(\s+)", value or ""):
        if not part or part.isspace():
            parts.append(part)
            continue
        if part.lower() == "r5":
            if parts and parts[-1].isspace():
                parts.pop()
            if parts:
                parts[-1] = f"{parts[-1]}r"
            else:
                parts.append("r")
            continue
        if re.search(r"\d", part):
            try:
                parts.append(transcriptions.numbered_to_accented(normalize_numbered_pinyin_token_for_display(part)))
                continue
            except ValueError:
                pass
        parts.append(part)
    return "".join(parts)


def tone_from_numbered_syllable(value: str) -> int:
    match = re.search(r"([1-5])$", value or "")
    if not match:
        return 5
    tone = int(match.group(1))
    return 5 if tone == 5 else tone


def pinyin_syllables(value: str) -> list[str]:
    return PINYIN_NUMBERED_TOKEN_RE.findall(value or "")
