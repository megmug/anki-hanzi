"""Internal lexicon state used by the deck build pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anki_hanzi.lexicon.definitions import (
    DefinitionItem,
    definition_item_to_json,
    parse_definitions,
)
from anki_hanzi.pinyin import normalize_single_pinyin, sorted_pinyin_readings, split_pinyin_readings


ENRICHED_LEXICON_SCHEMA = "hanzi-enriched-lexicon-v2"


def normalized_tags(values: list[str]) -> list[str]:
    return sorted({tag for value in values if (tag := str(value).strip()) and not tag.startswith("source:")})


@dataclass(frozen=True)
class LexiconSource:
    name: str
    url: str
    sha256: str
    path: Path
    comment_header: tuple[str, ...] = ()

    def to_master_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "sha256": self.sha256,
            "path": str(self.path),
            "comment_header": list(self.comment_header),
        }


@dataclass(frozen=True)
class ParseSummary:
    source_entries: int
    comments: int
    rejected_lines: int
    skipped_missing_ideograph_placeholder_entries: int


@dataclass(frozen=True)
class LexiconBaseSnapshot:
    schema: str
    source: LexiconSource
    summary: dict[str, int]

    @classmethod
    def from_state(cls, state: "LexiconState") -> "LexiconBaseSnapshot":
        return cls(
            schema=state.schema,
            source=state.source,
            summary=state.summary(),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source": self.source.to_master_json(),
            "summary": dict(self.summary),
        }


@dataclass(frozen=True)
class LexiconEnrichmentMetadata:
    name: str
    fields: tuple[str, ...]
    hsk_data_dir: Path
    frequency_list: Path
    frequency_tags: tuple[str, ...]
    yct_data_dir: Path
    yct_tags: tuple[str, ...]
    bct_data_dir: Path
    bct_tags: tuple[str, ...]
    dedupe_key: str

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "fields": list(self.fields),
            "hsk_data_dir": str(self.hsk_data_dir),
            "frequency_list": str(self.frequency_list),
            "frequency_tags": list(self.frequency_tags),
            "yct_data_dir": str(self.yct_data_dir),
            "yct_tags": list(self.yct_tags),
            "bct_data_dir": str(self.bct_data_dir),
            "bct_tags": list(self.bct_tags),
            "dedupe_key": self.dedupe_key,
        }


@dataclass
class LexiconForm:
    pinyin: str
    pinyin_readings: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    definition_items: list[DefinitionItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        primary_reading = normalize_single_pinyin(self.pinyin)
        extra_readings = split_pinyin_readings(self.pinyin_readings)
        all_readings = ([primary_reading] if primary_reading else []) + extra_readings
        self.pinyin = primary_reading or (extra_readings[0] if extra_readings else "")
        self.pinyin_readings = sorted_pinyin_readings(all_readings)
        self.definition_items = list(self.definition_items)
        self.tags = normalized_tags(self.tags)

    @property
    def definitions(self) -> list[str]:
        return [item.text for item in self.definition_items]

    def replace_pinyin(self, value: str) -> None:
        reading = normalize_single_pinyin(value)
        self.pinyin = reading
        self.pinyin_readings = [reading] if reading else []

    def add_pinyin_readings(self, value: str) -> list[str]:
        added: list[str] = []
        readings = list(self.pinyin_readings)
        for reading in split_pinyin_readings(value):
            if reading in readings:
                continue
            readings.append(reading)
            added.append(reading)
        self.pinyin_readings = sorted_pinyin_readings(readings)
        if not self.pinyin and self.pinyin_readings:
            self.pinyin = self.pinyin_readings[0]
        return added

    def pinyin_sort_key(self) -> tuple[list[str], str]:
        return (list(self.pinyin_readings), self.pinyin)

    @property
    def pinyin_reading_string(self) -> str:
        return " / ".join(self.pinyin_readings or [self.pinyin])

    def append_definitions(self, definitions: list[str]) -> None:
        seen = set(self.definitions)
        for definition in definitions:
            if definition in seen:
                continue
            self.definition_items.extend(parse_definitions([definition]))
            seen.add(definition)

    def add_tags(self, tags: list[str]) -> None:
        self.tags = normalized_tags(self.tags + tags)

    def to_json(self) -> dict[str, Any]:
        data = {
            "definitions": list(self.definitions),
            "pinyin": self.pinyin,
            "tags": list(self.tags),
        }
        if any(getattr(item, "resolved_definitions", []) for item in self.definition_items):
            data["definition_items"] = [definition_item_to_json(item) for item in self.definition_items]
        if len(self.pinyin_readings) > 1:
            data["pinyin_readings"] = list(self.pinyin_readings)
        return data


@dataclass
class LexiconWord:
    simplified: str
    forms: dict[str, LexiconForm] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    frequency_rank: int | None = None
    hanzi_frequency: int | None = None
    has_hanzi_frequency: bool = False

    def __post_init__(self) -> None:
        self.tags = normalized_tags(self.tags)

    def add_entry(self, pinyin: str, definitions: list[str]) -> None:
        form = self.forms.get(pinyin)
        if form is None:
            form = LexiconForm(pinyin=pinyin)
            self.forms[pinyin] = form

        form.append_definitions(definitions)

    def add_tags(self, tags: list[str]) -> None:
        self.tags = normalized_tags(self.tags + tags)

    def set_hanzi_frequency_once(self, frequency: int | None) -> None:
        if self.has_hanzi_frequency:
            return
        self.hanzi_frequency = frequency
        self.has_hanzi_frequency = True

    def sorted_forms(self) -> list[LexiconForm]:
        return sorted(self.forms.values(), key=lambda form: form.pinyin_sort_key())

    def forms_in_order(self) -> list[LexiconForm]:
        return list(self.forms.values())

    def sort_forms_by_pinyin(self) -> None:
        self.forms = dict(sorted(self.forms.items(), key=lambda item: item[1].pinyin_sort_key()))

    def to_json(
        self,
        *,
        include_enrichment: bool = False,
        preserve_form_order: bool = False,
    ) -> dict[str, Any]:
        forms = self.forms_in_order() if preserve_form_order else self.sorted_forms()
        data = {
            "forms": [form.to_json() for form in forms],
            "simplified": self.simplified,
            "tags": list(self.tags),
        }
        if include_enrichment and self.frequency_rank is not None:
            data["frequency"] = {"rank": self.frequency_rank}
        if include_enrichment and self.has_hanzi_frequency:
            data["hanzi"] = {"frequency": self.hanzi_frequency}
        return data

    def to_enriched_json(self) -> dict[str, Any]:
        return self.to_json(include_enrichment=True, preserve_form_order=True)


@dataclass
class LexiconState:
    source: LexiconSource
    words: dict[str, LexiconWord]
    parse_summary: ParseSummary
    schema: str = "hanzi-master-lexicon-cc-cedict-v3"
    hanzi_dropped_duplicates: list[dict[str, Any]] = field(default_factory=list)

    def sorted_words(self) -> list[LexiconWord]:
        return [self.words[key] for key in sorted(self.words)]

    def sort_forms_by_pinyin(self) -> None:
        for word in self.words.values():
            word.sort_forms_by_pinyin()

    def summary(self) -> dict[str, int]:
        words = self.sorted_words()
        forms_count = sum(len(word.forms) for word in words)
        return {
            "comments": self.parse_summary.comments,
            "entries": self.parse_summary.source_entries,
            "forms": forms_count,
            "max_forms_per_word": max((len(word.forms) for word in words), default=0),
            "rejected_lines": self.parse_summary.rejected_lines,
            "skipped_missing_ideograph_placeholder_entries": (
                self.parse_summary.skipped_missing_ideograph_placeholder_entries
            ),
            "words": len(words),
            "words_with_multiple_forms": sum(1 for word in words if len(word.forms) > 1),
        }

    def to_master_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source": self.source.to_master_json(),
            "summary": self.summary(),
            "words": self.words_json(),
        }

    def words_json(self, *, include_enrichment: bool = False) -> list[dict[str, Any]]:
        return [
            word.to_json(
                include_enrichment=include_enrichment,
                preserve_form_order=include_enrichment,
            )
            for word in self.sorted_words()
        ]

    def to_enriched_json(
        self,
        *,
        base: LexiconBaseSnapshot,
        enrichment: LexiconEnrichmentMetadata,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema": ENRICHED_LEXICON_SCHEMA,
            "base": base.to_json(),
            "enrichment": enrichment.to_json(),
            "summary": dict(summary),
            "words": self.words_json(include_enrichment=True),
            "hanzi": {
                "study_targets_location": "words[].forms[].tags",
                "dropped_duplicates": list(self.hanzi_dropped_duplicates),
            },
        }
