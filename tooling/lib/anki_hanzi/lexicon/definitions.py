"""Structured definition items for CC-CEDICT-derived lexicon forms."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, TypeAlias


ERHUA_VARIANT_RE = re.compile(
    r"^erhua variant of (?P<traditional>[^|\[\];,]+)"
    r"(?:\|(?P<simplified>[^\[\];,]+))?"
    r"\[(?P<pinyin>[A-Za-z0-9: ]+)\]$"
)


@dataclass
class PlainDefinition:
    text: str

    @property
    def kind(self) -> str:
        return "plain"


@dataclass
class ErhuaVariantDefinition:
    text: str
    target_traditional: str
    target_simplified: str
    target_pinyin: str
    resolved_definitions: list["DefinitionItem"] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return "erhua_variant"


DefinitionItem: TypeAlias = PlainDefinition | ErhuaVariantDefinition


def split_definition_text(value: str) -> list[str]:
    return [part.strip() for part in re.split(r";\s*", value) if part.strip()]


def parse_definition(value: str) -> DefinitionItem:
    text = str(value).strip()
    match = ERHUA_VARIANT_RE.match(text)
    if match is None:
        return PlainDefinition(text=text)

    traditional = match.group("traditional").strip()
    simplified = (match.group("simplified") or traditional).strip()
    return ErhuaVariantDefinition(
        text=text,
        target_traditional=traditional,
        target_simplified=simplified,
        target_pinyin=match.group("pinyin").strip(),
    )


def parse_definitions(values: list[str]) -> list[DefinitionItem]:
    return [parse_definition(value) for value in values]


def clone_definition_item(item: DefinitionItem, *, include_resolved: bool = True) -> DefinitionItem:
    if isinstance(item, PlainDefinition):
        return PlainDefinition(text=item.text)
    resolved_definitions = (
        [clone_definition_item(child, include_resolved=include_resolved) for child in item.resolved_definitions]
        if include_resolved
        else []
    )
    return ErhuaVariantDefinition(
        text=item.text,
        target_traditional=item.target_traditional,
        target_simplified=item.target_simplified,
        target_pinyin=item.target_pinyin,
        resolved_definitions=resolved_definitions,
    )


def definition_display_texts(items: list[DefinitionItem]) -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()
    for item in items:
        for part in split_definition_text(item.text):
            if part in seen:
                continue
            seen.add(part)
            texts.append(part)
    return texts


def definition_item_to_json(item: DefinitionItem) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": item.kind,
        "text": item.text,
    }
    if isinstance(item, ErhuaVariantDefinition):
        data.update(
            {
                "target": {
                    "traditional": item.target_traditional,
                    "simplified": item.target_simplified,
                    "pinyin": item.target_pinyin,
                },
            }
        )
        if item.resolved_definitions:
            data["resolved_definitions"] = [definition_item_to_json(child) for child in item.resolved_definitions]
    return data
