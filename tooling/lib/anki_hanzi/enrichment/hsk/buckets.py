"""Bucket specifications for the xiehanzi enrichment pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from anki_hanzi.enrichment.hsk.consumption import (
    ASSERT_DEFAULT_UNRESOLVED_BUCKET_EMPTY_RULE,
    ASSERT_DEFAULT_UNRESOLVED_EMPTY_RULE,
    CONSUME_CASE_VARIANT_EXACT_DEFINITION_BUCKET_RULE,
    CONSUME_EXACT_DEFINITION_ALSO_PR_BUCKET_RULE,
    CONSUME_EXACT_DEFINITION_BUCKET_RULE,
    CONSUME_FORMAT_VARIANT_BUCKET_RULE,
    CONSUME_HTML_SUBFORM_DEFINITION_COVER_BUCKET_RULE,
    CONSUME_MANUAL_PINYIN_OVERRIDE_BUCKET_RULE,
    CONSUME_MISSING_DICTIONARY_WORD_BUCKET_RULE,
    CONSUME_PERFECT_MATCH_BUCKET_RULE,
    CONSUME_SEMICOLON_SPLIT_EXACT_DEFINITION_ALSO_PR_BUCKET_RULE,
    CONSUME_SOURCE_SEE_COLLOQUIAL_PR_BUCKET_RULE,
    CONSUME_SPOKEN_TONE_VARIANT_BUCKET_RULE,
    CONSUME_SPOKEN_TONE_VARIANT_SOURCE_FORM_PAIRS_RULE,
    ConsumptionRuleDefinition,
    DROP_CASE_VARIANT_EXACT_DEFINITION_SOURCE_FORM_PAIRS_RULE,
    DROP_EXACT_DEFINITION_ALSO_PR_SOURCE_FORM_PAIRS_RULE,
    DROP_EXACT_DEFINITION_SOURCE_FORM_PAIRS_RULE,
    DROP_FORMAT_VARIANT_SOURCE_FORM_PAIRS_RULE,
    DROP_HTML_SUBFORM_DEFINITION_COVER_SOURCE_FORM_PAIRS_RULE,
    DROP_MANUAL_PINYIN_OVERRIDE_SOURCE_FORM_PAIRS_RULE,
    DROP_MISSING_DICTIONARY_WORD_SOURCE_FORMS_RULE,
    DROP_PERFECT_MATCH_SOURCE_FORM_PAIRS_RULE,
    DROP_SEMICOLON_SPLIT_EXACT_DEFINITION_ALSO_PR_SOURCE_FORM_PAIRS_RULE,
    DROP_SOURCE_SEE_COLLOQUIAL_PR_SOURCE_FORM_PAIRS_RULE,
    StateConsumptionRuleDefinition,
)
from anki_hanzi.enrichment.hsk.matching import (
    CASE_VARIANT_EXACT_DEFINITION_UNIQUE_RULE,
    DEFAULT_UNRESOLVED_RULE,
    EXACT_DEFINITION_ALSO_PR_UNIQUE_RULE,
    EXACT_DEFINITION_UNIQUE_RULE,
    FORMAT_VARIANT_UNIQUE_RULE,
    HTML_SUBFORM_DEFINITION_COVER_UNIQUE_RULE,
    MANUAL_PINYIN_OVERRIDE_UNIQUE_RULE,
    MatchingRuleDefinition,
    MISSING_DICTIONARY_WORD_RULE,
    SEMICOLON_SPLIT_EXACT_DEFINITION_ALSO_PR_UNIQUE_RULE,
    SOURCE_SEE_COLLOQUIAL_PR_UNIQUE_RULE,
    SPOKEN_TONE_VARIANT_UNIQUE_RULE,
    STRICT_PINYIN_EXACT_UNIQUE_RULE,
)


BUCKET_DESCRIPTIONS = {
    "perfect_match": (
        "A source form has exactly one remaining dictionary candidate with the same complete strict numbered "
        "preserve-case Pinyin reading list. The source form is resolved and all of its candidate pairs are consumed."
    ),
    "manual_pinyin_override": (
        "A configured manual Pinyin correction has exactly one remaining strict or format-variant dictionary "
        "candidate. The source form is resolved with the corrected Pinyin value."
    ),
    "format_variant_unique": (
        "A source form has exactly one remaining dictionary candidate whose complete compact preserve-case Pinyin "
        "reading list matches after spacing and separator differences. The source form is resolved without changing "
        "dictionary Pinyin or definitions."
    ),
    "spoken_tone_variant": (
        "A source form has exactly one remaining dictionary candidate whose toneless Pinyin matches. Every tone "
        "difference between source and dictionary Pinyin is fully explained by recognized spoken variants: 一 "
        "sandhi, 不 sandhi, or neutral-tone differences with matching reading and syllable structure. The source "
        "form is consumed by adding the source tones in dictionary Pinyin format as an accepted reading on the "
        "selected dictionary form."
    ),
    "case_variant_exact_definition": (
        "A source form has exactly one remaining dictionary candidate whose Pinyin differs by case after spacing "
        "and separator normalization, and whose complete normalized definition set matches exactly. The source form "
        "is resolved by applying tags and metadata to the selected dictionary form without changing dictionary "
        "Pinyin or definitions."
    ),
    "exact_definition_also_pr": (
        "A source form has exactly one remaining dictionary candidate whose complete normalized definition set "
        "matches exactly. Every source Pinyin reading is either already on the dictionary form or explicitly listed "
        "in the dictionary definitions as also pr., and at least one source reading is such an extra also-pr reading. "
        "The source form is resolved by applying tags and metadata directly and adding the explicitly attested "
        "also-pr readings to the selected dictionary form."
    ),
    "exact_definition": (
        "A source form has exactly one remaining dictionary candidate whose complete normalized definition set "
        "matches exactly. The source form is resolved by applying tags and metadata directly to the selected "
        "dictionary form without changing dictionary Pinyin or definitions."
    ),
    "semicolon_split_exact_definition_also_pr": (
        "A source form has exactly one remaining dictionary candidate whose complete normalized definition set "
        "matches after rule-local semicolon splitting. Every source Pinyin reading is either already on the "
        "dictionary form or explicitly listed in the dictionary definitions as also pr., and at least one source "
        "reading is such an extra also-pr reading. The source form is resolved by applying tags and metadata "
        "directly and adding the explicitly attested also-pr readings to the selected dictionary form."
    ),
    "html_subform_definition_cover": (
        "A remaining source form is internally split by xiehanzi HTML Pinyin/definition blocks. Each HTML subform "
        "has exactly one strict numbered preserve-case Pinyin dictionary candidate whose normalized definition set "
        "matches after rule-local semicolon splitting, and the matched subforms cover all remaining dictionary "
        "candidates exactly once. The source form is resolved by applying tags and metadata directly to every "
        "covered dictionary form without changing dictionary Pinyin or definitions."
    ),
    "source_see_colloquial_pr": (
        "A source form has a single reading and exactly one same-Simplified dictionary candidate with a different "
        "single reading. Its HTML has exactly two Pinyin/definition blocks, one per reading, covering all source "
        "definitions. The source-reading block contains only an exact see-reference to that dictionary form, "
        "which reciprocally lists the source reading exactly once in standalone colloquial-pr declarations. "
        "Reading comparisons use strict numbered preserve-case equality. The source form is consumed by applying "
        "tags and metadata and adding only the attested source reading in dictionary spelling. The primary "
        "dictionary reading and definitions stay unchanged; no other listed pronunciation is imported."
    ),
    "missing_dictionary_word": (
        "No exact Simplified target key exists in CC-CEDICT. The source form is resolved by creating synthetic "
        "words/forms from the xiehanzi source entry."
    ),
    "default_unresolved": (
        "No higher-priority bucket resolved the source form. This bucket must stay empty; the build aborts if any "
        "matching pairs reach it."
    ),
}


@dataclass(frozen=True)
class BucketDefinition:
    name: str
    priority: int
    phase: str
    description: str
    report_items: bool
    matching_rules: tuple[MatchingRuleDefinition, ...] = ()
    consumption_rule: ConsumptionRuleDefinition | None = None
    state_consumption_rule: StateConsumptionRuleDefinition | None = None


def _bucket(
    name: str,
    *,
    priority: int,
    phase: str,
    report_items: bool,
    matching_rules: tuple[MatchingRuleDefinition, ...],
    consumption_rule: ConsumptionRuleDefinition,
    state_consumption_rule: StateConsumptionRuleDefinition,
) -> BucketDefinition:
    return BucketDefinition(
        name=name,
        priority=priority,
        phase=phase,
        description=BUCKET_DESCRIPTIONS[name],
        report_items=report_items,
        matching_rules=matching_rules,
        consumption_rule=consumption_rule,
        state_consumption_rule=state_consumption_rule,
    )


BUCKET_DEFINITIONS = {
    "missing_dictionary_word": _bucket(
        "missing_dictionary_word",
        priority=10,
        phase="source_prelude",
        report_items=False,
        matching_rules=(MISSING_DICTIONARY_WORD_RULE,),
        consumption_rule=DROP_MISSING_DICTIONARY_WORD_SOURCE_FORMS_RULE,
        state_consumption_rule=CONSUME_MISSING_DICTIONARY_WORD_BUCKET_RULE,
    ),
    "perfect_match": _bucket(
        "perfect_match",
        priority=20,
        phase="pair_pipeline",
        report_items=False,
        matching_rules=(STRICT_PINYIN_EXACT_UNIQUE_RULE,),
        consumption_rule=DROP_PERFECT_MATCH_SOURCE_FORM_PAIRS_RULE,
        state_consumption_rule=CONSUME_PERFECT_MATCH_BUCKET_RULE,
    ),
    "manual_pinyin_override": _bucket(
        "manual_pinyin_override",
        priority=30,
        phase="pair_pipeline",
        report_items=False,
        matching_rules=(MANUAL_PINYIN_OVERRIDE_UNIQUE_RULE,),
        consumption_rule=DROP_MANUAL_PINYIN_OVERRIDE_SOURCE_FORM_PAIRS_RULE,
        state_consumption_rule=CONSUME_MANUAL_PINYIN_OVERRIDE_BUCKET_RULE,
    ),
    "format_variant_unique": _bucket(
        "format_variant_unique",
        priority=40,
        phase="pair_pipeline",
        report_items=False,
        matching_rules=(FORMAT_VARIANT_UNIQUE_RULE,),
        consumption_rule=DROP_FORMAT_VARIANT_SOURCE_FORM_PAIRS_RULE,
        state_consumption_rule=CONSUME_FORMAT_VARIANT_BUCKET_RULE,
    ),
    "spoken_tone_variant": _bucket(
        "spoken_tone_variant",
        priority=50,
        phase="pair_pipeline",
        report_items=False,
        matching_rules=(SPOKEN_TONE_VARIANT_UNIQUE_RULE,),
        consumption_rule=CONSUME_SPOKEN_TONE_VARIANT_SOURCE_FORM_PAIRS_RULE,
        state_consumption_rule=CONSUME_SPOKEN_TONE_VARIANT_BUCKET_RULE,
    ),
    "case_variant_exact_definition": _bucket(
        "case_variant_exact_definition",
        priority=60,
        phase="pair_pipeline",
        report_items=False,
        matching_rules=(CASE_VARIANT_EXACT_DEFINITION_UNIQUE_RULE,),
        consumption_rule=DROP_CASE_VARIANT_EXACT_DEFINITION_SOURCE_FORM_PAIRS_RULE,
        state_consumption_rule=CONSUME_CASE_VARIANT_EXACT_DEFINITION_BUCKET_RULE,
    ),
    "exact_definition_also_pr": _bucket(
        "exact_definition_also_pr",
        priority=65,
        phase="pair_pipeline",
        report_items=False,
        matching_rules=(EXACT_DEFINITION_ALSO_PR_UNIQUE_RULE,),
        consumption_rule=DROP_EXACT_DEFINITION_ALSO_PR_SOURCE_FORM_PAIRS_RULE,
        state_consumption_rule=CONSUME_EXACT_DEFINITION_ALSO_PR_BUCKET_RULE,
    ),
    "exact_definition": _bucket(
        "exact_definition",
        priority=70,
        phase="pair_pipeline",
        report_items=False,
        matching_rules=(EXACT_DEFINITION_UNIQUE_RULE,),
        consumption_rule=DROP_EXACT_DEFINITION_SOURCE_FORM_PAIRS_RULE,
        state_consumption_rule=CONSUME_EXACT_DEFINITION_BUCKET_RULE,
    ),
    "semicolon_split_exact_definition_also_pr": _bucket(
        "semicolon_split_exact_definition_also_pr",
        priority=75,
        phase="pair_pipeline",
        report_items=False,
        matching_rules=(SEMICOLON_SPLIT_EXACT_DEFINITION_ALSO_PR_UNIQUE_RULE,),
        consumption_rule=DROP_SEMICOLON_SPLIT_EXACT_DEFINITION_ALSO_PR_SOURCE_FORM_PAIRS_RULE,
        state_consumption_rule=CONSUME_SEMICOLON_SPLIT_EXACT_DEFINITION_ALSO_PR_BUCKET_RULE,
    ),
    "html_subform_definition_cover": _bucket(
        "html_subform_definition_cover",
        priority=80,
        phase="pair_pipeline",
        report_items=False,
        matching_rules=(HTML_SUBFORM_DEFINITION_COVER_UNIQUE_RULE,),
        consumption_rule=DROP_HTML_SUBFORM_DEFINITION_COVER_SOURCE_FORM_PAIRS_RULE,
        state_consumption_rule=CONSUME_HTML_SUBFORM_DEFINITION_COVER_BUCKET_RULE,
    ),
    "source_see_colloquial_pr": _bucket(
        "source_see_colloquial_pr",
        priority=900,
        phase="pair_pipeline",
        report_items=True,
        matching_rules=(SOURCE_SEE_COLLOQUIAL_PR_UNIQUE_RULE,),
        consumption_rule=DROP_SOURCE_SEE_COLLOQUIAL_PR_SOURCE_FORM_PAIRS_RULE,
        state_consumption_rule=CONSUME_SOURCE_SEE_COLLOQUIAL_PR_BUCKET_RULE,
    ),
    "default_unresolved": _bucket(
        "default_unresolved",
        priority=1000,
        phase="terminal",
        report_items=True,
        matching_rules=(DEFAULT_UNRESOLVED_RULE,),
        consumption_rule=ASSERT_DEFAULT_UNRESOLVED_EMPTY_RULE,
        state_consumption_rule=ASSERT_DEFAULT_UNRESOLVED_BUCKET_EMPTY_RULE,
    ),
}


def bucket_definitions_by_priority() -> list[BucketDefinition]:
    return sorted(BUCKET_DEFINITIONS.values(), key=lambda definition: definition.priority)


def bucket_definitions_by_phase(phase: str) -> list[BucketDefinition]:
    return [definition for definition in bucket_definitions_by_priority() if definition.phase == phase]


def validate_bucket_definitions() -> None:
    priorities = [definition.priority for definition in BUCKET_DEFINITIONS.values()]
    if len(priorities) != len(set(priorities)):
        raise ValueError("xiehanzi bucket priorities must be unique")

    for bucket, definition in BUCKET_DEFINITIONS.items():
        if bucket != definition.name:
            raise ValueError(f"xiehanzi bucket key/name mismatch: {bucket!r} != {definition.name!r}")
        if definition.state_consumption_rule is None:
            raise ValueError(f"xiehanzi bucket lacks state consumption rule: {definition.name}")
        if definition.state_consumption_rule.bucket != definition.name:
            raise ValueError(
                "xiehanzi bucket/state-consumption mismatch: "
                f"{definition.name!r} != {definition.state_consumption_rule.bucket!r}"
            )
        if definition.consumption_rule is None:
            raise ValueError(f"xiehanzi bucket lacks report consumption rule: {definition.name}")
        for rule in definition.matching_rules:
            if rule.scope != definition.phase:
                raise ValueError(
                    "xiehanzi bucket/matching-rule phase mismatch: "
                    f"{definition.name!r} phase={definition.phase!r} rule={rule.name!r} scope={rule.scope!r}"
                )


validate_bucket_definitions()
