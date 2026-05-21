#!/usr/bin/env python

"""Render xiehanzi Meaning HTML from enriched lexicon word data."""

from __future__ import annotations

import re
import html
from typing import Any

from colorize_pinyin import colorized_HTML_string_from_string
from dragonmapper import transcriptions


TONE_CLASSES = ["text-color5", "text-color1", "text-color2", "text-color3", "text-color4"]
PINYIN_TOKEN_RE = re.compile(r"[A-Za-züÜv:]+[1-5]?")


def normalize_numbered_pinyin_token(value: str) -> str:
    """Normalize CC-CEDICT's `u:` spelling before accent conversion."""

    return value.replace("u:", "ü").replace("U:", "Ü")


def numbered_to_xiehanzi_display(value: str) -> str:
    """Convert numbered pinyin to the display form used by xiehanzi HTML.

    Keep the inherited `r5` quirk intact. The old generated HTML renders erhua
    finals as `<span ...>r</span>5`, so normalizing `r5` to plain `r` would
    change cards that still need legacy-perfect output.
    """

    parts: list[str] = []
    for part in re.split(r"(\s+)", value or ""):
        if not part or part.isspace():
            parts.append(part)
            continue
        if part.lower() == "r5":
            parts.append(part.lower())
            continue
        if re.search(r"\d", part):
            try:
                parts.append(transcriptions.numbered_to_accented(
                    normalize_numbered_pinyin_token(part)
                ))
                continue
            except ValueError:
                pass
        parts.append(part)
    return "".join(parts)


def pinyin_html(value: str) -> str:
    display = numbered_to_xiehanzi_display(value)
    colored = colorized_HTML_string_from_string(
        display,
        "pinYinWrapper",
        TONE_CLASSES,
    )
    if colored is not None:
        return colored
    return f'<span class="pinYinWrapper"><span class="text-color5">{display}</span></span>'


def tone_from_numbered_syllable(value: str) -> int:
    match = re.search(r"([1-5])$", value or "")
    if not match:
        return 5
    tone = int(match.group(1))
    return 5 if tone == 5 else tone


def pinyin_syllables(value: str) -> list[str]:
    return PINYIN_TOKEN_RE.findall(value or "")


def colored_characters(value: str, pinyin: str) -> str:
    characters = list(value or "")
    syllables = pinyin_syllables(pinyin)
    if len(characters) == len(syllables):
        return "".join(
            f'<span class="text-color{tone_from_numbered_syllable(syllable)}">{character}</span>'
            for character, syllable in zip(characters, syllables)
        )

    fallback_tone = tone_from_numbered_syllable(syllables[0]) if syllables else 5
    return "".join(
        f'<span class="text-color{fallback_tone}">{character}</span>'
        for character in characters
    )


def rendered_definitions(form: dict[str, Any]) -> list[str]:
    definitions: list[str] = []
    seen: set[str] = set()
    for definition in form.get("definitions", []):
        for part in re.split(r";\s*", str(definition)):
            value = part.strip()
            if not value or value in seen:
                continue
            definitions.append(value)
            seen.add(value)
    return definitions


def render_meaning_form(word: dict[str, Any], form: dict[str, Any]) -> str:
    simplified = str(word.get("simplified") or "")
    traditional_variants = form.get("traditional_variants") or word.get("traditional_variants") or []
    traditional = str(traditional_variants[0]) if traditional_variants else simplified
    pinyin = str(form.get("pinyin") or "")

    output = [
        '<div class="char">  ',
        f'<span id="char-sim-id">{colored_characters(simplified, pinyin)} </span>',
    ]
    if traditional and traditional != simplified:
        output.extend([
            ' <span class="sep">〔</span>',
            f'<span id="char-trad-id">  {colored_characters(traditional, pinyin)} </span>',
            '<span class="sep">〕</span></div>',
        ])
    else:
        output.append(" </div>")

    output.extend([
        " ",
        pinyin_html(pinyin),
        " <ul>",
    ])
    for definition in rendered_definitions(form):
        output.append(f"  <li>{html.escape(definition, quote=False)}</li>")
    output.append(" </ul>  ")
    return "".join(output)


def render_meaning_html(word: dict[str, Any]) -> str:
    return "".join(
        render_meaning_form(word, form)
        for form in word.get("forms", [])
    )
