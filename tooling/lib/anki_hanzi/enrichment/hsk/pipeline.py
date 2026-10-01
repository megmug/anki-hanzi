"""
Apply the xiehanzi New HSK source to the CC-CEDICT lexicon state.

This module owns only the HSK/xiehanzi matching and state-consumption rules.
Other enrichment stages, such as frequency and YCT tags, are orchestrated by
the top-level enrichment pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki_hanzi.enrichment.model import EnrichmentStageResult
from anki_hanzi.lexicon import LexiconState
from anki_hanzi.enrichment.hsk.buckets import (
    bucket_definitions_by_phase,
    bucket_definitions_by_priority,
)
from anki_hanzi.enrichment.hsk.consumption import (
    apply_pipeline_enrichment_to_state,
)
from anki_hanzi.enrichment.hsk.model import (
    BucketResult,
    HskMatchingPair,
    HskSourceForm,
    PairConsumption,
    PairPipelineResult,
    SourcePreludeConsumption,
    SourcePreludePipelineResult,
    empty_pair_consumption,
    empty_source_prelude_consumption,
    pair_pipeline_bucket_result,
    source_prelude_bucket_result,
)
from anki_hanzi.enrichment.hsk.source import (
    dedupe_entries,
    load_hanzi_entries,
)
from anki_hanzi.enrichment.hsk.matching import (
    TargetFormRef,
    build_source_forms,
    build_target_form_index,
    materialize_simplified_match_pairs,
)
from anki_hanzi.enrichment.hsk.reports import (
    build_enrichment_report,
    build_enrichment_summary,
    build_matching_report,
)


@dataclass(frozen=True)
class HskEnrichmentResult:
    stage: EnrichmentStageResult
    matching_report: dict[str, Any]
    dropped_duplicates: list[dict[str, Any]]


def apply_source_prelude_rules(
    source_forms_by_id: dict[int, HskSourceForm],
    target_form_index: dict[str, list[TargetFormRef]],
) -> SourcePreludePipelineResult:
    remaining_source_form_ids = set(source_forms_by_id)
    bucket_results: dict[str, BucketResult] = {}
    consumed_by_source_form: dict[int, str] = {}

    for definition in bucket_definitions_by_phase("source_prelude"):
        selected_items: list[HskSourceForm] = []
        input_source_form_count = len(remaining_source_form_ids)
        unassigned_source_form_ids = set(remaining_source_form_ids)

        for rule in definition.matching_rules:
            result = rule.match_source_prelude(
                source_forms_by_id,
                target_form_index,
                unassigned_source_form_ids,
                definition.name,
            )
            selected_items.extend(result["selected_items"])
            unassigned_source_form_ids.difference_update(result["selected_source_form_ids"])

        consumption_rule = definition.consumption_rule
        consumption: SourcePreludeConsumption = (
            consumption_rule.consume_source_prelude(selected_items, remaining_source_form_ids)
            if consumption_rule is not None
            else empty_source_prelude_consumption(remaining_source_form_ids)
        )
        for source_form_id in consumption["consumed_source_form_ids"]:
            consumed_by_source_form[source_form_id] = definition.name

        bucket_results[definition.name] = source_prelude_bucket_result(
            bucket=definition.name,
            phase=definition.phase,
            input_source_form_count=input_source_form_count,
            selected_items=selected_items,
            consumption=consumption,
        )

    return {
        "remaining_source_form_ids": remaining_source_form_ids,
        "bucket_results": bucket_results,
        "consumed_by_source_form": consumed_by_source_form,
    }


def apply_pair_pipeline_rules(working_pairs: list[HskMatchingPair]) -> PairPipelineResult:
    remaining_items = list(working_pairs)
    bucket_results: dict[str, BucketResult] = {}
    consumed_by_source_form: dict[int, str] = {}

    for definition in bucket_definitions_by_phase("pair_pipeline"):
        input_items = remaining_items
        selected_items: list[HskMatchingPair] = []

        for rule in definition.matching_rules:
            result = rule.match_pairs(remaining_items, definition.name)
            selected_items.extend(result["selected_items"])
            remaining_items = result["remaining_items"]

        consumption_rule = definition.consumption_rule
        consumption: PairConsumption = (
            consumption_rule.consume_pairs(selected_items, remaining_items)
            if consumption_rule is not None
            else empty_pair_consumption(remaining_items)
        )
        remaining_items = consumption["remaining_items"]
        for source_form_id in consumption["consumed_source_form_ids"]:
            consumed_by_source_form[source_form_id] = definition.name

        bucket_results[definition.name] = pair_pipeline_bucket_result(
            bucket=definition.name,
            phase=definition.phase,
            input_items=input_items,
            selected_items=selected_items,
            consumption=consumption,
        )

    for definition in bucket_definitions_by_phase("terminal"):
        input_items = remaining_items
        selected_items: list[HskMatchingPair] = []
        for rule in definition.matching_rules:
            result = rule.match_pairs(remaining_items, definition.name)
            selected_items.extend(result["selected_items"])
            remaining_items = result["remaining_items"]
        consumption_rule = definition.consumption_rule
        consumption: PairConsumption = (
            consumption_rule.consume_pairs(selected_items, remaining_items)
            if consumption_rule is not None
            else empty_pair_consumption(remaining_items)
        )
        remaining_items = consumption["remaining_items"]
        for source_form_id in consumption["consumed_source_form_ids"]:
            consumed_by_source_form[source_form_id] = definition.name

        bucket_results[definition.name] = pair_pipeline_bucket_result(
            bucket=definition.name,
            phase=definition.phase,
            input_items=input_items,
            selected_items=selected_items,
            consumption=consumption,
            items_after_consumption=selected_items,
        )

    return {
        "bucket_results": bucket_results,
        "consumed_by_source_form": consumed_by_source_form,
        "remaining_items": remaining_items,
    }


def validate_pair_pipeline(
    initial_matching_pair_count: int,
    bucket_results: dict[str, BucketResult],
) -> None:
    consumed_matching_pair_count = sum(
        result["consumed_matching_pair_count"]
        for result in bucket_results.values()
        if result["phase"] == "pair_pipeline"
    )
    terminal_matching_pair_count = sum(
        result["selected_matching_pair_count"] for result in bucket_results.values() if result["phase"] == "terminal"
    )
    if consumed_matching_pair_count + terminal_matching_pair_count != initial_matching_pair_count:
        raise ValueError(
            "Pair pipeline did not account for every materialized matching pair: "
            f"{consumed_matching_pair_count=} {terminal_matching_pair_count=} {initial_matching_pair_count=}"
        )


def build_matching_pipeline(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    target_form_index = build_target_form_index(state)
    dictionary_word_count = len(state.sorted_words())
    dictionary_form_count = sum(len(target_refs) for target_refs in target_form_index.values())
    source_forms_by_id = build_source_forms(deck_entries)

    source_prelude_result = apply_source_prelude_rules(source_forms_by_id, target_form_index)
    materialization_result = materialize_simplified_match_pairs(
        source_forms_by_id,
        target_form_index,
        source_prelude_result["remaining_source_form_ids"],
    )
    working_pairs = materialization_result["working_pairs"]
    pair_pipeline_result = apply_pair_pipeline_rules(working_pairs)

    bucket_results = {
        **source_prelude_result["bucket_results"],
        **pair_pipeline_result["bucket_results"],
    }
    validate_pair_pipeline(len(working_pairs), pair_pipeline_result["bucket_results"])

    consumed_by_source_form = {
        **source_prelude_result["consumed_by_source_form"],
        **pair_pipeline_result["consumed_by_source_form"],
    }

    return {
        "target_form_index": target_form_index,
        "dictionary_word_count": dictionary_word_count,
        "dictionary_form_count": dictionary_form_count,
        "source_forms_by_id": source_forms_by_id,
        "source_prelude_result": source_prelude_result,
        "materialization_result": materialization_result,
        "working_pairs": working_pairs,
        "pair_pipeline_result": pair_pipeline_result,
        "bucket_results": bucket_results,
        "consumed_by_source_form": consumed_by_source_form,
    }


def apply_hsk_enrichment_to_state(
    master_state: LexiconState,
    input_label: str,
    hsk_data_dir: Path,
) -> HskEnrichmentResult:
    base_words = list(master_state.sorted_words())
    base_word_index = {word.simplified: word for word in master_state.sorted_words()}

    raw_entries = load_hanzi_entries(hsk_data_dir=hsk_data_dir)
    deck_entries, dropped_duplicates = dedupe_entries(raw_entries)
    matching_pipeline = build_matching_pipeline(master_state, deck_entries)
    matching_report = build_matching_report(
        raw_entries=raw_entries,
        deck_entries=deck_entries,
        dropped_duplicates=dropped_duplicates,
        pipeline=matching_pipeline,
    )

    missing_raw_entries = [entry for entry in raw_entries if entry["simplified"] not in base_word_index]
    state_consumption_rules = tuple(
        definition.state_consumption_rule
        for definition in bucket_definitions_by_priority()
        if definition.state_consumption_rule is not None
    )
    pipeline_enrichment = apply_pipeline_enrichment_to_state(
        master_state,
        deck_entries,
        matching_pipeline,
        state_consumption_rules,
    )
    missing_deck_entries = pipeline_enrichment["missing_deck_entries"]
    synthetic_words = pipeline_enrichment["synthetic_words"]
    form_stats = pipeline_enrichment["form_stats"]
    master_state.hanzi_dropped_duplicates = dropped_duplicates

    summary = build_enrichment_summary(
        base_words=base_words,
        total_words=len(master_state.words),
        synthetic_words=synthetic_words,
        raw_entries=raw_entries,
        deck_entries=deck_entries,
        dropped_duplicates=dropped_duplicates,
        missing_raw_entries=missing_raw_entries,
        missing_deck_entries=missing_deck_entries,
        form_stats=form_stats,
    )

    report = build_enrichment_report(
        input_label=input_label,
        summary=summary,
        matching_report=matching_report,
        pipeline_enrichment=pipeline_enrichment,
        missing_raw_entries=missing_raw_entries,
        missing_deck_entries=missing_deck_entries,
        synthetic_words=synthetic_words,
        form_stats=form_stats,
        dropped_duplicates=dropped_duplicates,
    )

    return HskEnrichmentResult(
        stage=EnrichmentStageResult(
            name="hsk_enrichment",
            summary=summary,
            report=report,
        ),
        matching_report=matching_report,
        dropped_duplicates=dropped_duplicates,
    )
