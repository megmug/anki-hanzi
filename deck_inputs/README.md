# Deck Inputs

This directory contains source inputs that are read to build this fork's APKG.
Generated reports, generated master JSON files, package caches, and final APKGs should stay outside this directory.

## Contents

- `hsk-3.0-words-list/`: upstream HSK/xiehanzi word-list submodule.
  The active build reads the prepared New HSK (2025) hanzi TSV files and frequency list.
- `cc-cedict/`: pinned CC-CEDICT snapshot used to generate the compact master lexicon before enrichment.
- `deck_config.json`: first-pass deck selection config.
  It selects which enriched hanzi study targets become generated notes, such as all HSK levels plus specific Simplified words.
  It can also include an optional `card_settings` object to bake card display settings into the generated templates per card type and side.
  Supported card types are `Meaning`, `Pinyin`, and `Write`; supported sides are `front` and `back`.
- `card_templates/`: active Anki card HTML/CSS templates and static media packaged into the APKG.
  The active template subdirectories are `meaning/`, `pinyin/`, and `write/`.

Example `card_settings` override:

```json
{
  "card_settings": {
    "Write": {
      "front": {
        "show_pinyin": true,
        "show_meaning": true,
        "show_simplified": false,
        "show_grid": true,
        "show_outline": false,
        "stroke_tone_color": true,
        "grid_size": 400,
        "stroke_width": 64,
        "hint_after_misses": 0,
        "stroke_leniency": 0.8,
        "easy_score_min": 95
      }
    }
  }
}
```
