"""Diagnostic report builders for the xiehanzi enrichment pipeline."""

from __future__ import annotations

from collections import Counter
from typing import Any

from anki_hanzi.enrichment.hsk.buckets import (
    BUCKET_DEFINITIONS,
    BucketDefinition,
    bucket_definitions_by_priority,
)
from anki_hanzi.enrichment.hsk.matching import (
    candidate_count_bucket,
    candidate_count_buckets_for_source_forms,
)
from anki_hanzi.enrichment.hsk.model import (
    BucketItem,
    bucket_matching_pair_count,
    bucket_source_form_ids,
)
from anki_hanzi.enrichment.hsk.source import LEVELS, entry_summary


def selected_source_form_count_after_consumption(result: dict[str, Any], definition: BucketDefinition) -> int:
    if definition.consumption_rule is None:
        return result["selected_source_form_count"]
    return 0


def selected_matching_pair_count_after_consumption(result: dict[str, Any], definition: BucketDefinition) -> int:
    if definition.consumption_rule is None:
        return result["selected_matching_pair_count"]
    return 0


def compact_report_item(item: BucketItem) -> dict[str, Any]:
    item_report = item.to_report()
    source = item_report["source"]
    context = item_report.get("context", {})
    source_label = f"{source['simplified']} {source['pinyin']} [{source['deck_level']}]"
    if source.get("raw_pinyin") and source["raw_pinyin"] != source["pinyin"]:
        source_label = f"{source_label} raw:{source['raw_pinyin']}"
    report: dict[str, Any] = {
        "source_form_id": context.get("source_form_id"),
        "source": source_label,
    }

    dictionary = item_report.get("dictionary")
    if dictionary is not None:
        report["target"] = dictionary["pinyin"]
        report["definitions"] = {
            "source": item_report.get("source_definitions", []),
            "dictionary": dictionary.get("definitions", []),
        }

    if context.get("candidate_count_for_source") is not None:
        report["candidate"] = f"{context.get('candidate_index_for_source')}/{context['candidate_count_for_source']}"

    for extra_key in (
        "manual_pinyin_override",
        "spoken_tone_variant",
        "exact_definition_also_pr",
        "semicolon_split_exact_definition_also_pr",
        "html_subform_definition_cover",
        "source_see_colloquial_pr",
    ):
        if extra_key in context:
            report[extra_key] = context[extra_key]

    return report


def matching_rule_report(rule: Any) -> dict[str, Any]:
    report = {
        "name": rule.name,
        "scope": rule.scope,
        "requires": list(rule.requires),
    }
    if rule.selected_pair is not None:
        report["selected_pair"] = rule.selected_pair
    return report


def consumption_rule_report(rule: Any | None) -> dict[str, Any] | None:
    if rule is None:
        return None
    return {
        "name": rule.name,
        "report_only_effect": rule.report_only_effect,
        "enrichment_effect": rule.enrichment_effect,
    }


def bucket_result(pipeline: dict[str, Any], definition: BucketDefinition) -> dict[str, Any]:
    return pipeline["bucket_results"][definition.name]


def report_bucket_items(
    pipeline: dict[str, Any],
    bucket: str,
    bucket_item_limit: int | None,
) -> list[dict[str, Any]]:
    if not BUCKET_DEFINITIONS[bucket].report_items:
        return []
    items = pipeline["bucket_results"][bucket]["selected_items"]
    if bucket_item_limit is not None:
        items = items[:bucket_item_limit]
    return [compact_report_item(item) for item in items]


def bucket_summary_item(pipeline: dict[str, Any], definition: BucketDefinition) -> dict[str, Any]:
    result = bucket_result(pipeline, definition)
    return {
        "priority": definition.priority,
        "phase": definition.phase,
        "bucket": definition.name,
        "description": definition.description,
        "matching_rules": [matching_rule_report(rule) for rule in definition.matching_rules],
        "consumption_rule": consumption_rule_report(definition.consumption_rule),
        "step_input_source_form_count": result["input_source_form_count"],
        "step_input_matching_pair_count": result["input_matching_pair_count"],
        "source_form_count_before_consumption": result["selected_source_form_count"],
        "source_form_count_after_consumption": selected_source_form_count_after_consumption(result, definition),
        "matching_pair_count_before_consumption": result["selected_matching_pair_count"],
        "matching_pair_count_after_consumption": selected_matching_pair_count_after_consumption(result, definition),
        "consumed_source_form_count": result["consumed_source_form_count"],
        "consumed_matching_pair_count": result["consumed_matching_pair_count"],
        "removed_from_remaining_matching_pair_count": result["removed_from_remaining_matching_pair_count"],
        "remaining_source_form_count_after_step": result["remaining_source_form_count_after_consumption"],
        "remaining_matching_pair_count_after_step": result["remaining_matching_pair_count_after_consumption"],
        "has_consumption_rule": definition.consumption_rule is not None,
        "report_items": definition.report_items,
    }


def bucket_report_item(
    pipeline: dict[str, Any],
    definition: BucketDefinition,
    bucket_item_limit: int | None,
) -> dict[str, Any]:
    result = bucket_result(pipeline, definition)
    return {
        "description": definition.description,
        "matching_rules": [matching_rule_report(rule) for rule in definition.matching_rules],
        "item_count": result["selected_matching_pair_count"],
        "items": report_bucket_items(pipeline, definition.name, bucket_item_limit),
    }


def bucket_count_map(pipeline: dict[str, Any], key: str) -> dict[str, int]:
    return {
        definition.name: bucket_result(pipeline, definition)[key] for definition in bucket_definitions_by_priority()
    }


def source_form_bucket_counts_after_consumption(pipeline: dict[str, Any]) -> dict[str, int]:
    return {
        definition.name: selected_source_form_count_after_consumption(bucket_result(pipeline, definition), definition)
        for definition in bucket_definitions_by_priority()
    }


def matching_pair_bucket_counts_after_consumption(pipeline: dict[str, Any]) -> dict[str, int]:
    return {
        definition.name: selected_matching_pair_count_after_consumption(bucket_result(pipeline, definition), definition)
        for definition in bucket_definitions_by_priority()
    }


def build_matching_report(
    raw_entries: list[dict[str, Any]],
    deck_entries: list[dict[str, Any]],
    dropped_duplicates: list[dict[str, Any]],
    *,
    pipeline: dict[str, Any],
    bucket_item_limit: int | None = None,
) -> dict[str, Any]:
    dictionary_form_count = pipeline["dictionary_form_count"]
    source_forms_by_id = pipeline["source_forms_by_id"]
    materialization_result = pipeline["materialization_result"]
    working_pairs = pipeline["working_pairs"]
    bucket_results = pipeline["bucket_results"]
    consumed_by_source_form = pipeline["consumed_by_source_form"]
    default_items = bucket_results["default_unresolved"]["selected_items"]
    default_source_form_ids_after_consumption = bucket_source_form_ids(default_items)

    initial_candidate_count_buckets = Counter(
        candidate_count_bucket(source_form.candidate_count) for source_form in source_forms_by_id.values()
    )
    default_candidate_count_buckets = candidate_count_buckets_for_source_forms(
        source_forms_by_id,
        default_source_form_ids_after_consumption,
    )

    bucket_source_form_counts_before_consumption = bucket_count_map(pipeline, "selected_source_form_count")
    bucket_matching_pair_counts_before_consumption = bucket_count_map(pipeline, "selected_matching_pair_count")

    return {
        "schema": "hanzi-matching-report-v1",
        "bucket_summary": [
            bucket_summary_item(pipeline, definition) for definition in bucket_definitions_by_priority()
        ],
        "description": (
            "Diagnostic xiehanzi-to-CC-CEDICT matching pipeline. "
            "Source prelude rules consume source forms before the pair pipeline starts. "
            "Pair rules then split a shrinking working set before consumption removes source-form redundancies. "
            "All buckets include overview counts; buckets configured with report_items contain detailed matching "
            "pairs for rule design."
        ),
        "summary": {
            "raw_source_entries": len(raw_entries),
            "deduped_source_entries": len(deck_entries),
            "dropped_duplicate_entries": len(dropped_duplicates),
            "dictionary_words": pipeline["dictionary_word_count"],
            "dictionary_forms": dictionary_form_count,
            "source_form_bucket_counts_before_consumption": dict(
                sorted(bucket_source_form_counts_before_consumption.items())
            ),
            "source_form_bucket_counts_after_consumption": dict(
                sorted(source_form_bucket_counts_after_consumption(pipeline).items())
            ),
            "matching_pair_bucket_counts_before_consumption": dict(
                sorted(bucket_matching_pair_counts_before_consumption.items())
            ),
            "matching_pair_bucket_counts_after_consumption": dict(
                sorted(matching_pair_bucket_counts_after_consumption(pipeline).items())
            ),
            "resolved_source_forms": len(consumed_by_source_form),
            "unresolved_source_forms": bucket_results["default_unresolved"]["selected_source_form_count"],
            "virtual_start_matching_pair_count": len(deck_entries) * dictionary_form_count,
            "virtual_pair_pipeline_start_matching_pair_count": materialization_result["virtual_pair_count"],
            "virtual_simplified_mismatch_pair_count": materialization_result["simplified_mismatch_pair_count"],
            "initial_matching_pair_count": len(working_pairs),
            "default_unresolved_matching_pair_count": bucket_matching_pair_count(default_items),
            "initial_candidate_count_buckets": dict(sorted(initial_candidate_count_buckets.items())),
            "default_candidate_count_buckets": dict(sorted(default_candidate_count_buckets.items())),
            "bucket_item_limit": bucket_item_limit,
        },
        "pair_materialization": {
            "virtual_start_bucket": {
                "description": "Logical source-form x dictionary-form universe; never materialized.",
                "source_form_count": len(deck_entries),
                "target_form_count": dictionary_form_count,
                "virtual_matching_pair_count": len(deck_entries) * dictionary_form_count,
                "materialized": False,
            },
            "source_prelude_remaining_sources": {
                "description": "Source forms that survived source-level prelude rules.",
                "source_form_count": materialization_result["source_form_count"],
            },
            "simplified_match_working_set": {
                "description": "Materialized pairs whose exact Simplified values match.",
                "matching_rule": "simplified_match",
                "source_form_count": materialization_result["source_form_count"],
                "target_form_count": materialization_result["target_form_count"],
                "virtual_input_matching_pair_count": materialization_result["virtual_pair_count"],
                "matching_pair_count": materialization_result["simplified_match_pair_count"],
                "materialized": True,
            },
            "simplified_mismatch": {
                "description": "Virtual rejected pairs whose exact Simplified values do not match.",
                "matching_rule": "simplified_mismatch",
                "matching_pair_count": materialization_result["simplified_mismatch_pair_count"],
                "materialized": False,
            },
        },
        "candidate_generation": {
            "source_prelude": "missing_dictionary_word removes source forms with no exact Simplified target key.",
            "pair_materialization": "simplified_match materializes only exact Simplified-compatible pairs.",
            "virtual_rejection": "simplified_mismatch is counted as a virtual aggregate and is not stored as items.",
        },
        "buckets": {
            definition.name: bucket_report_item(pipeline, definition, bucket_item_limit)
            for definition in bucket_definitions_by_priority()
            if definition.report_items
        },
    }


def summarize_by_level(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {level: 0 for level in LEVELS}
    for entry in entries:
        counts[entry["deck_level"]] = counts.get(entry["deck_level"], 0) + 1
    return counts


def group_non_exact_matches(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "format_variant": [],
        "case_variant": [],
    }
    for record in records:
        groups.setdefault(record["match_type"], []).append(record)
    return groups


def pipeline_report_item(result: dict[str, Any]) -> dict[str, Any]:
    omitted_keys = {"added_readings", "entries", "form_stats", "matched_targets"}
    return {key: value for key, value in result.items() if key not in omitted_keys}


def build_enrichment_summary(
    *,
    base_words: list[Any],
    total_words: int,
    synthetic_words: list[Any],
    raw_entries: list[dict[str, Any]],
    deck_entries: list[dict[str, Any]],
    dropped_duplicates: list[dict[str, Any]],
    missing_raw_entries: list[dict[str, Any]],
    missing_deck_entries: list[dict[str, Any]],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "base_words": len(base_words),
        "synthetic_hanzi_words": len(synthetic_words),
        "total_words": total_words,
        "raw_hanzi_entries": len(raw_entries),
        "deck_entries_after_dedupe": len(deck_entries),
        "dropped_duplicate_entries": len(dropped_duplicates),
        "raw_entries_missing_base_word": len(missing_raw_entries),
        "deck_entries_missing_base_word": len(missing_deck_entries),
        "deck_entries_by_level": summarize_by_level(deck_entries),
        "hanzi_form_targets": form_stats["matched"],
        "hanzi_form_matches": form_stats["matched"],
        "hanzi_form_exact_matches": form_stats["match_types"]["exact"],
        "hanzi_form_format_variant_matches": form_stats["match_types"]["format_variant"],
        "hanzi_form_case_variant_matches": form_stats["match_types"]["case_variant"],
        "hanzi_form_spoken_tone_variant_matches": form_stats["match_types"]["spoken_tone_variant"],
        "hanzi_form_exact_definition_matches": form_stats["match_types"]["exact_definition"],
        "hanzi_form_exact_definition_also_pr_matches": form_stats["match_types"]["exact_definition_also_pr"],
        "hanzi_form_semicolon_split_exact_definition_also_pr_matches": form_stats["match_types"][
            "semicolon_split_exact_definition_also_pr"
        ],
        "hanzi_form_html_subform_definition_cover_matches": form_stats["match_types"]["html_subform_definition_cover"],
        "hanzi_form_source_see_colloquial_pr_matches": form_stats["match_types"]["source_see_colloquial_pr"],
        "hanzi_non_exact_matches": len(form_stats["non_exact_matches"]),
        "hanzi_non_exact_definition_mismatches": len(form_stats["non_exact_definition_mismatches"]),
        "hanzi_pinyin_case_preserved": len(form_stats["pinyin_case_preserved"]),
        "hanzi_pinyin_whitespace_only": len(form_stats["pinyin_whitespace_only"]),
        "hanzi_pinyin_substantive": len(form_stats["pinyin_substantive"]),
    }


def build_enrichment_report(
    *,
    input_label: str,
    summary: dict[str, Any],
    matching_report: dict[str, Any],
    pipeline_enrichment: dict[str, Any],
    missing_raw_entries: list[dict[str, Any]],
    missing_deck_entries: list[dict[str, Any]],
    synthetic_words: list[Any],
    form_stats: dict[str, Any],
    dropped_duplicates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "hanzi-hsk-enrichment-report-v1",
        "input": input_label,
        "summary": summary,
        "matching_summary": matching_report["summary"],
        "pipeline_enrichment": {
            definition.name: pipeline_report_item(pipeline_enrichment[definition.name])
            for definition in bucket_definitions_by_priority()
            if definition.name in pipeline_enrichment
        },
        "samples": {
            "missing_raw_entries": [entry_summary(entry) for entry in missing_raw_entries[:25]],
            "missing_deck_entries": [entry_summary(entry) for entry in missing_deck_entries[:25]],
            "synthetic_words": [word.to_enriched_json() for word in synthetic_words[:25]],
            "perfect_match_entries": pipeline_enrichment["perfect_match"]["entries"][:25],
            "manual_pinyin_override_entries": pipeline_enrichment["manual_pinyin_override"]["entries"][:25],
            "format_variant_unique_entries": pipeline_enrichment["format_variant_unique"]["entries"][:25],
            "exact_definition_also_pr_added_readings": pipeline_enrichment["exact_definition_also_pr"][
                "added_readings"
            ][:25],
            "exact_definition_also_pr_entries": pipeline_enrichment["exact_definition_also_pr"]["entries"][:25],
            "exact_definition_entries": pipeline_enrichment["exact_definition"]["entries"][:25],
            "semicolon_split_exact_definition_also_pr_added_readings": pipeline_enrichment[
                "semicolon_split_exact_definition_also_pr"
            ]["added_readings"][:25],
            "semicolon_split_exact_definition_also_pr_entries": pipeline_enrichment[
                "semicolon_split_exact_definition_also_pr"
            ]["entries"][:25],
            "html_subform_definition_cover_entries": pipeline_enrichment["html_subform_definition_cover"]["entries"][
                :25
            ],
            "html_subform_definition_cover_targets": pipeline_enrichment["html_subform_definition_cover"][
                "matched_targets"
            ][:25],
            "source_see_colloquial_pr_added_readings": pipeline_enrichment["source_see_colloquial_pr"][
                "added_readings"
            ][:25],
            "hanzi_non_exact_definition_mismatches": form_stats["non_exact_definition_mismatches"],
            "hanzi_non_exact_definition_mismatches_by_type": group_non_exact_matches(
                form_stats["non_exact_definition_mismatches"]
            ),
            "dropped_duplicates": dropped_duplicates[:25],
        },
    }
