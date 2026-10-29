"""Render hanzi Meaning HTML from enriched lexicon state data."""

from __future__ import annotations

import html

from anki_hanzi.lexicon.definitions import (
    DefinitionItem,
    ErhuaVariantDefinition,
    split_definition_text,
)
from anki_hanzi.lexicon import LexiconForm, LexiconWord
from anki_hanzi.pinyin import numbered_to_display, pinyin_syllables, tone_from_numbered_syllable
from colorize_pinyin import colorized_HTML_string_from_string


TONE_CLASSES = ["tone0", "tone1", "tone2", "tone3", "tone4"]


def tone_class_from_numbered_syllable(value: str) -> str:
    tone = tone_from_numbered_syllable(value)
    return "tone0" if tone == 5 else f"tone{tone}"


def pinyin_html(value: str) -> str:
    display = numbered_to_display(value)
    colored = colorized_HTML_string_from_string(
        display,
        "pinYinWrapper",
        TONE_CLASSES,
    )
    if colored is not None:
        return colored
    return f'<span class="pinYinWrapper"><span class="tone0">{display}</span></span>'


def colored_characters(value: str, pinyin: str) -> str:
    characters = list(value or "")
    syllables = pinyin_syllables(pinyin)
    if len(characters) == len(syllables):
        return "".join(
            f'<span class="{tone_class_from_numbered_syllable(syllable)}">{character}</span>'
            for character, syllable in zip(characters, syllables)
        )

    fallback_class = tone_class_from_numbered_syllable(syllables[0]) if syllables else "tone0"
    return "".join(f'<span class="{fallback_class}">{character}</span>' for character in characters)


def render_definition_item(item: DefinitionItem) -> str:
    children = getattr(item, "resolved_definitions", [])
    if not children:
        return html.escape(item.text, quote=False)

    output = [html.escape(item.text, quote=False), ' <ul class="derived-definitions derived-definitions--erhua">']
    for child in children:
        for part in split_definition_text(child.text):
            output.append(f"  <li>{html.escape(part, quote=False)}</li>")
    output.append(" </ul>")
    return "".join(output)


def render_definition_items(form: LexiconForm) -> list[str]:
    rendered: list[str] = []
    seen: set[str] = set()
    for item in form.definition_items:
        if isinstance(item, ErhuaVariantDefinition) and item.resolved_definitions:
            rendered.append(render_definition_item(item))
            seen.update(split_definition_text(item.text))
            continue

        for part in split_definition_text(item.text):
            if part in seen:
                continue
            seen.add(part)
            rendered.append(html.escape(part, quote=False))
    return rendered


def render_meaning_form(word: LexiconWord, form: LexiconForm) -> str:
    simplified = word.simplified
    primary_pinyin = form.pinyin
    pinyin = form.pinyin_reading_string

    output = [
        '<div class="char">  ',
        f'<span id="char-sim-id">{colored_characters(simplified, primary_pinyin)} </span>',
        " </div>",
    ]

    output.extend(
        [
            " ",
            pinyin_html(pinyin),
            " <ul>",
        ]
    )
    for definition in render_definition_items(form):
        output.append(f"  <li>{definition}</li>")
    output.append(" </ul>  ")
    return "".join(output)


def render_meaning_html(word: LexiconWord) -> str:
    return "".join(render_meaning_form(word, form) for form in word.forms_in_order())
