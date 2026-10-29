"""genanki model construction for the hanzi deck."""

from __future__ import annotations

from pathlib import Path

import genanki

from anki_hanzi.deck.config import DeckConfig
from anki_hanzi.deck.template_generation import HanziTemplateGenerator


def create_models(config: DeckConfig | None = None, hw_data_bundle: Path | None = None) -> dict[str, genanki.Model]:
    if config is None:
        config = DeckConfig()
    generator = HanziTemplateGenerator()
    return {
        card_type: spec.to_genanki_model()
        for card_type, spec in generator.model_specs(config, hw_data_bundle).items()
    }
