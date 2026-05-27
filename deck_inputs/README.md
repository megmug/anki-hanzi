# Deck Inputs

This directory contains source inputs that are read to build this fork's APKG.
Generated reports, generated master JSON files, package caches, and final APKGs
should stay outside this directory.

## Contents

- `hsk-3.0-words-list/`: upstream HSK/xiehanzi word-list submodule, including
  prepared hanzi TSV files and source audio.
- `cc-cedict/`: pinned CC-CEDICT snapshot used to generate the compact master
  lexicon before enrichment.
- `deck_config.json`: first-pass deck selection config. It selects which
  enriched hanzi study targets become generated notes, such as all HSK
  levels plus specific Simplified words. It can also include an optional
  `card_settings` object to bake card display settings into the generated
  templates per card type and side. Supported card types are `Meaning`,
  `Pinyin`, and `Write`; supported sides are `front` and `back`.
- `apkg_build_invariant.json`: last-known-good APKG size and SHA256 used by the
  default invariant build.
- `extra_audio/`: committed/generated audio files for selected entries.
- `card_templates/`: active Anki card HTML/CSS templates and static media
  packaged into the APKG. The active template subdirectories are `meaning/`,
  `pinyin/`, and `write/`.

Example `card_settings` override:

```json
{
  "card_settings": {
    "Write": {
      "front": {
        "practice": "simplified",
        "show_pinyin": true,
        "show_meaning": true,
        "show_simplified": false,
        "show_traditional": false,
        "show_grid": true,
        "show_outline": false,
        "stroke_tone_color": true,
        "grid_size": 400,
        "stroke_width": 64,
        "hint_after_misses": 0
      }
    }
  }
}
```
