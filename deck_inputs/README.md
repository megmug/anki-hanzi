# Deck Inputs

This directory contains source inputs that are read to build this fork's APKG.

## Contents

- `hsk-3.0-words-list/`: upstream HSK/xiehanzi word-list submodule.
  The active build reads the prepared New HSK (2025) hanzi TSV files and frequency list.
- `cc-cedict/`: pinned CC-CEDICT snapshot used to generate the compact master lexicon before enrichment.
- `deck_config.json`: first-pass deck selection config.
  It selects which enriched hanzi study targets become generated notes, such as all HSK levels plus specific Simplified words.
  It can also include an optional `card_settings` object to bake card display settings into the generated templates per card type and side.
- `card_templates/`: active Anki card HTML/CSS templates and static media packaged into the APKG.
  The active template subdirectories are `meaning/`, `pinyin/`, and `write/`.

## `deck_config.json`

The deck config is a JSON object.
The generator requires a `selection` object.
Every other top-level key is optional and overrides built-in defaults.
Unknown card types, sides, audio settings, or card display settings fail the build instead of being ignored.

Minimal HSK 1 config:

```json
{
  "selection": {
    "mode": "tagged",
    "tags": ["hsk:1"]
  }
}
```

Full no-audio config:

```json
{
  "selection": {
    "mode": "all"
  },
  "card_types": ["Meaning", "Pinyin", "Write"],
  "audio": {
    "engine": "off"
  }
}
```

### Selection

`selection.mode` controls how words and forms are selected.
`"tagged"` selects entries that match at least one configured tag.
`"all"` selects every enriched entry and ignores `selection.tags`.

`selection.tags` may be a string or a list of strings.
Configured tags use the compact source form, such as `hsk:1` or `freq:top2500`.
Generated Anki notes namespace those tags under `hanzi::`, such as `hanzi::hsk::1`.

Common selection tags:

- `hsk:1` through `hsk:6`
- `hsk:7-9`
- `freq:top500`
- `freq:top2500`
- `freq:top10000`
- `source:xiehanzi`
- `source:cc-cedict`

`selection.individual_simplified` is an optional list of Simplified words that are always included.
It is useful for adding a few specific words without broadening the tag selection.

Example:

```json
{
  "selection": {
    "mode": "tagged",
    "tags": ["hsk:1", "freq:top500"],
    "individual_simplified": ["大学", "中文"]
  }
}
```

Meaning cards are generated per selected reading group.
Pinyin and Write cards are generated at word level, so selecting any tagged form includes all readings for that word.
This keeps tag combinations additive.

### Card Types

`card_types` selects which card families are emitted.
The default is all three card types.
The supported values are `Meaning`, `Pinyin`, and `Write`.

Example:

```json
{
  "selection": {
    "mode": "tagged",
    "tags": ["hsk:1"]
  },
  "card_types": ["Meaning", "Pinyin"]
}
```

### Audio

`audio.engine` controls generated audio.
The default is `off`.
Supported values are `off`, `kokoro`, and `edge_tts`.
`edge-tts` is also accepted and normalized to `edge_tts`.

Example:

```json
{
  "selection": {
    "mode": "tagged",
    "tags": ["hsk:1"]
  },
  "audio": {
    "engine": "kokoro"
  }
}
```

### Card Settings

`card_settings` bakes template behavior into the generated cards.
Settings are grouped by card type and side.
Supported card types are `Meaning`, `Pinyin`, and `Write`.
Supported sides are `front` and `back`.
Only settings listed below are accepted.

Meaning and Pinyin settings:

- `show_pinyin`: boolean, default `true`
- `show_meaning`: boolean, default `true`
- `show_simplified`: boolean, default `true`

Write settings:

- `show_pinyin`: boolean, default `true`
- `show_meaning`: boolean, default `true`
- `show_simplified`: boolean, default `false` on the front and `true` on the back
- `show_grid`: boolean, default `false`
- `show_outline`: boolean, default `false`
- `stroke_tone_color`: boolean, default `true`
- `grid_size`: integer from `100` to `1000`, default `400`
- `stroke_width`: integer from `2` to `100`, default `64`
- `hint_after_misses`: integer from `0` to `10`, default `0`
- `stroke_leniency`: number from `0.1` to `2.0`, default `0.8`
- `easy_score_min`: integer from `0` to `100`, default `95`

Example `card_settings` override:

```json
{
  "selection": {
    "mode": "tagged",
    "tags": ["hsk:1"]
  },
  "card_settings": {
    "Write": {
      "front": {
        "show_pinyin": true,
        "show_meaning": true,
        "show_simplified": false,
        "show_grid": false,
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
