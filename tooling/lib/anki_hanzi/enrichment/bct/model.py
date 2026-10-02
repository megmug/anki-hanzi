"""Data model for BCT tag matching."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anki_hanzi.lexicon import LexiconState
    from anki_hanzi.lexicon.state import LexiconForm, LexiconWord


@dataclass(frozen=True)
class BctSourceEntry:
    level: str
    index: str
    word: str
    path: str
    line_number: int

    def to_report(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "index": self.index,
            "word": self.word,
            "path": self.path,
            "line_number": self.line_number,
        }


@dataclass(frozen=True)
class BctSourceTerm:
    word: str
    entries: tuple[BctSourceEntry, ...]

    @property
    def levels(self) -> tuple[str, ...]:
        return tuple(sorted({entry.level for entry in self.entries}))

    def tags(self) -> list[str]:
        return [f"bct:{level}" for level in self.levels]

    def to_report(self) -> dict[str, Any]:
        return {
            "word": self.word,
            "levels": list(self.levels),
            "entries": [entry.to_report() for entry in self.entries],
        }


@dataclass(frozen=True)
class BctTargetMatch:
    word: LexiconWord
    forms: tuple[LexiconForm, ...]
    tag_word: bool
    report: dict[str, Any] = field(default_factory=dict)

    def to_report(self) -> dict[str, Any]:
        return {
            "word": self.word.simplified,
            "tag_word": self.tag_word,
            "forms": [
                {
                    "pinyin": form.pinyin_reading_string,
                    "tags": list(form.tags),
                }
                for form in self.forms
            ],
            **self.report,
        }


@dataclass(frozen=True)
class BctBucketMatch:
    source: BctSourceTerm
    method: str
    targets: tuple[BctTargetMatch, ...]
    report: dict[str, Any] = field(default_factory=dict)

    def to_report(self) -> dict[str, Any]:
        return {
            **self.source.to_report(),
            "method": self.method,
            "targets": [target.to_report() for target in self.targets],
            **self.report,
        }


@dataclass(frozen=True)
class BctUnresolvedTerm:
    source: BctSourceTerm
    reason: str
    report: dict[str, Any] = field(default_factory=dict)

    def to_report(self) -> dict[str, Any]:
        return {
            **self.source.to_report(),
            "reason": self.reason,
            **self.report,
        }


BctMatchingFunction = Callable[["LexiconState", BctSourceTerm], BctBucketMatch | None]


@dataclass(frozen=True)
class BctConsumptionResult:
    tags_applied: bool


BctConsumptionFunction = Callable[[BctBucketMatch], BctConsumptionResult]


@dataclass(frozen=True)
class BctMatchingRuleDefinition:
    name: str
    description: str
    match: BctMatchingFunction


@dataclass(frozen=True)
class BctBucketDefinition:
    name: str
    priority: int
    description: str
    report_items: bool
    matching_rule: BctMatchingRuleDefinition | None = None
    consumption_rule: BctConsumptionFunction | None = None
