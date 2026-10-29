"""Typed source forms and matching pairs for the xiehanzi pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any, TypedDict


PairId = tuple[int, int]


@dataclass
class HskSourceForm:
    source_form_id: int
    entry: dict[str, Any]
    candidate_count: int = 0
    bucket: str | None = None
    matching_rule: str | None = None

    @property
    def source_key(self) -> str:
        return str(self.entry["simplified"])

    def assigned_to(self, *, bucket: str, matching_rule: str) -> HskSourceForm:
        return replace(self, bucket=bucket, matching_rule=matching_rule)

    def source_report(self) -> dict[str, Any]:
        report = {
            "simplified": self.entry["simplified"],
            "pinyin": self.entry["pinyin"],
            "deck_level": self.entry["deck_level"],
            "raw_level": self.entry["raw_level"],
            "source": self.entry["source"],
            "tags": list(self.entry["tags"]),
        }
        raw_pinyin = self.entry.get("raw_pinyin")
        if raw_pinyin and raw_pinyin != self.entry["pinyin"]:
            report["raw_pinyin"] = raw_pinyin
        return report

    def to_report(self) -> dict[str, Any]:
        return {
            "source": self.source_report(),
            "context": {
                "source_form_id": self.source_form_id,
                "candidate_count_for_source": self.candidate_count,
            },
            "bucket": self.bucket,
            "matching_rule": self.matching_rule,
        }


@dataclass
class HskMatchingPair:
    source_form: HskSourceForm
    target_word_key: str
    target_form_key: str
    dictionary_simplified: str
    dictionary_pinyin: str
    dictionary_primary_pinyin: str
    dictionary_pinyin_readings: tuple[str, ...]
    dictionary_tags: tuple[str, ...]
    dictionary_definitions: tuple[str, ...]
    source_definitions: tuple[str, ...]
    candidate_index: int
    bucket: str
    matching_rule: str
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def source_form_id(self) -> int:
        return self.source_form.source_form_id

    @property
    def identity(self) -> PairId:
        return self.source_form_id, self.candidate_index

    def assigned_to(
        self,
        *,
        bucket: str,
        matching_rule: str,
        context_name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> HskMatchingPair:
        updated_context = dict(self.context)
        if context_name is not None and context is not None:
            updated_context[context_name] = context
        return replace(
            self,
            bucket=bucket,
            matching_rule=matching_rule,
            context=updated_context,
        )

    def target_report(self) -> dict[str, str]:
        return {
            "word_key": self.target_word_key,
            "form_key": self.target_form_key,
        }

    def dictionary_report(self) -> dict[str, Any]:
        return {
            "simplified": self.dictionary_simplified,
            "pinyin": self.dictionary_pinyin,
            "primary_pinyin": self.dictionary_primary_pinyin,
            "pinyin_readings": list(self.dictionary_pinyin_readings),
            "tags": list(self.dictionary_tags),
            "definitions": list(self.dictionary_definitions),
        }

    def to_report(self) -> dict[str, Any]:
        return {
            "source": self.source_form.source_report(),
            "target": self.target_report(),
            "dictionary": self.dictionary_report(),
            "source_definitions": list(self.source_definitions),
            "source_meaning_html": self.source_form.entry["meaning_html"],
            "context": {
                "source_form_id": self.source_form_id,
                "candidate_count_for_source": self.source_form.candidate_count,
                "candidate_index_for_source": self.candidate_index,
                **self.context,
            },
            "bucket": self.bucket,
            "matching_rule": self.matching_rule,
        }


BucketItem = HskSourceForm | HskMatchingPair


class MatchingRuleResult(TypedDict):
    selected_items: list[HskMatchingPair]
    remaining_items: list[HskMatchingPair]


class SourcePreludeRuleResult(TypedDict):
    selected_items: list[HskSourceForm]
    selected_source_form_ids: set[int]


class SourcePreludeConsumption(TypedDict):
    consumed_source_form_ids: set[int]
    consumed_source_form_count: int
    consumed_matching_pair_count: int
    remaining_source_form_count: int


class PairConsumption(TypedDict):
    consumed_source_form_ids: set[int]
    consumed_source_form_count: int
    consumed_matching_pair_count: int
    removed_from_remaining_matching_pair_count: int
    remaining_items: list[HskMatchingPair]


class BucketResult(TypedDict):
    phase: str
    bucket: str
    input_source_form_count: int
    input_matching_pair_count: int
    selected_items: list[BucketItem]
    selected_source_form_count: int
    selected_matching_pair_count: int
    consumed_source_form_count: int
    consumed_matching_pair_count: int
    removed_from_remaining_matching_pair_count: int
    remaining_source_form_count_after_consumption: int
    remaining_matching_pair_count_after_consumption: int


class SourcePreludePipelineResult(TypedDict):
    remaining_source_form_ids: set[int]
    bucket_results: dict[str, BucketResult]
    consumed_by_source_form: dict[int, str]


class PairPipelineResult(TypedDict):
    bucket_results: dict[str, BucketResult]
    consumed_by_source_form: dict[int, str]
    remaining_items: list[HskMatchingPair]


def item_source_form_id(item: BucketItem) -> int:
    return item.source_form_id


def matching_pair_identity(item: HskMatchingPair) -> PairId:
    return item.identity


def bucket_source_form_ids(items: Iterable[BucketItem]) -> set[int]:
    return {item_source_form_id(item) for item in items}


def bucket_matching_pair_count(items: Iterable[BucketItem]) -> int:
    return sum(isinstance(item, HskMatchingPair) for item in items)


def group_pairs_by_source_form(working_pairs: list[HskMatchingPair]) -> dict[int, list[HskMatchingPair]]:
    pairs_by_source_form: dict[int, list[HskMatchingPair]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair.source_form_id, []).append(pair)
    return pairs_by_source_form


def empty_source_prelude_consumption(remaining_source_form_ids: set[int]) -> SourcePreludeConsumption:
    return {
        "consumed_source_form_ids": set(),
        "consumed_source_form_count": 0,
        "consumed_matching_pair_count": 0,
        "remaining_source_form_count": len(remaining_source_form_ids),
    }


def empty_pair_consumption(remaining_items: list[HskMatchingPair]) -> PairConsumption:
    return {
        "consumed_source_form_ids": set(),
        "consumed_source_form_count": 0,
        "consumed_matching_pair_count": 0,
        "removed_from_remaining_matching_pair_count": 0,
        "remaining_items": remaining_items,
    }


def source_prelude_bucket_result(
    *,
    bucket: str,
    phase: str,
    input_source_form_count: int,
    selected_items: list[HskSourceForm],
    consumption: SourcePreludeConsumption,
) -> BucketResult:
    return {
        "phase": phase,
        "bucket": bucket,
        "input_source_form_count": input_source_form_count,
        "input_matching_pair_count": 0,
        "selected_items": selected_items,
        "selected_source_form_count": len(bucket_source_form_ids(selected_items)),
        "selected_matching_pair_count": 0,
        "consumed_source_form_count": consumption["consumed_source_form_count"],
        "consumed_matching_pair_count": consumption["consumed_matching_pair_count"],
        "removed_from_remaining_matching_pair_count": 0,
        "remaining_source_form_count_after_consumption": consumption["remaining_source_form_count"],
        "remaining_matching_pair_count_after_consumption": 0,
    }


def pair_pipeline_bucket_result(
    *,
    bucket: str,
    phase: str,
    input_items: list[HskMatchingPair],
    selected_items: list[HskMatchingPair],
    consumption: PairConsumption,
) -> BucketResult:
    remaining_items = consumption["remaining_items"]
    return {
        "phase": phase,
        "bucket": bucket,
        "input_source_form_count": len(bucket_source_form_ids(input_items)),
        "input_matching_pair_count": bucket_matching_pair_count(input_items),
        "selected_items": selected_items,
        "selected_source_form_count": len(bucket_source_form_ids(selected_items)),
        "selected_matching_pair_count": bucket_matching_pair_count(selected_items),
        "consumed_source_form_count": consumption["consumed_source_form_count"],
        "consumed_matching_pair_count": consumption["consumed_matching_pair_count"],
        "removed_from_remaining_matching_pair_count": consumption["removed_from_remaining_matching_pair_count"],
        "remaining_source_form_count_after_consumption": len(bucket_source_form_ids(remaining_items)),
        "remaining_matching_pair_count_after_consumption": bucket_matching_pair_count(remaining_items),
    }
