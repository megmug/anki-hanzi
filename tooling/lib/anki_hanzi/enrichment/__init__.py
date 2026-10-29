"""Top-level lexicon enrichment orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki_hanzi.enrichment.bct import (
    BCT_LEVELS,
    apply_bct_enrichment_to_state,
)
from anki_hanzi.enrichment.erhua import apply_erhua_definition_enrichment_to_state
from anki_hanzi.enrichment.frequency import (
    TOP_FREQUENCY_THRESHOLDS,
    apply_frequency_enrichment_to_state,
)
from anki_hanzi.enrichment.hsk import (
    HANZI_DEDUPE_KEY,
    apply_hsk_enrichment_to_state,
)
from anki_hanzi.enrichment.model import (
    EnrichmentStageResult,
    merge_stage_summaries,
    stage_reports_by_name,
)
from anki_hanzi.enrichment.yct import (
    YCT_LEVELS,
    apply_yct_enrichment_to_state,
)
from anki_hanzi.json_io import write_json
from anki_hanzi.lexicon import (
    LexiconBaseSnapshot,
    LexiconEnrichmentMetadata,
    LexiconState,
)


@dataclass(frozen=True)
class LexiconEnrichmentResult:
    enrichment_report: dict[str, Any]
    matching_report: dict[str, Any]


def build_lexicon_enrichment_report(
    *,
    input_label: str,
    output_path: Path | None,
    summary: dict[str, Any],
    stages: tuple[EnrichmentStageResult, ...],
) -> dict[str, Any]:
    stage_reports = stage_reports_by_name(stages)
    hsk_report = stage_reports["hsk_enrichment"]
    return {
        "schema": "hanzi-enrichment-report-v1",
        "input": input_label,
        "output": str(output_path) if output_path is not None else None,
        "summary": summary,
        **stage_reports,
        "samples": hsk_report["samples"],
    }


def enrich_state(
    master_state: LexiconState,
    input_label: str,
    output_path: Path | None,
    hsk_data_dir: Path,
    frequency_list_path: Path,
    yct_data_dir: Path,
    bct_data_dir: Path,
) -> LexiconEnrichmentResult:
    base_snapshot = LexiconBaseSnapshot.from_state(master_state)

    hsk_result = apply_hsk_enrichment_to_state(
        master_state,
        input_label=input_label,
        hsk_data_dir=hsk_data_dir,
    )
    frequency_result = apply_frequency_enrichment_to_state(master_state, frequency_list_path)
    yct_result = apply_yct_enrichment_to_state(master_state, yct_data_dir)
    bct_result = apply_bct_enrichment_to_state(master_state, bct_data_dir)
    erhua_result = apply_erhua_definition_enrichment_to_state(master_state)

    stage_results = (
        hsk_result.stage,
        frequency_result,
        yct_result,
        bct_result,
        erhua_result,
    )
    summary = merge_stage_summaries(stage_results)
    report = build_lexicon_enrichment_report(
        input_label=input_label,
        output_path=output_path,
        summary=summary,
        stages=stage_results,
    )

    if output_path is not None:
        enrichment_metadata = LexiconEnrichmentMetadata(
            name="hanzi lexicon enrichment",
            fields=("hsk", "frequency", "yct", "bct", "erhua"),
            hsk_data_dir=hsk_data_dir,
            frequency_list=frequency_list_path,
            frequency_tags=tuple(f"freq:top{threshold}" for threshold in TOP_FREQUENCY_THRESHOLDS),
            yct_data_dir=yct_data_dir,
            yct_tags=tuple(f"yct:{level}" for level in YCT_LEVELS),
            bct_data_dir=bct_data_dir,
            bct_tags=tuple(f"bct:{level}" for level in BCT_LEVELS),
            dedupe_key=HANZI_DEDUPE_KEY,
        )
        enriched = master_state.to_enriched_json(
            base=base_snapshot,
            enrichment=enrichment_metadata,
            summary=summary,
        )
        write_json(output_path, enriched)
    return LexiconEnrichmentResult(
        enrichment_report=report,
        matching_report=hsk_result.matching_report,
    )


__all__ = [
    "HANZI_DEDUPE_KEY",
    "LexiconEnrichmentResult",
    "enrich_state",
]
