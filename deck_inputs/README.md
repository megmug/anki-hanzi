# Deck Inputs

This directory contains source inputs that are read to build this fork's APKG.

## Contents

- `hsk-3.0-words-list/`: upstream HSK/xiehanzi word-list submodule.
  The active build reads its prepared New HSK (2025), YCT, and BCT lists plus its Mandarin frequency list.
- `cc-cedict/`: pinned CC-CEDICT snapshot used to build the internal lexicon state.
- `deck_config.json`: deck selection config.
  It selects which enriched hanzi study targets become generated notes, such as HSK, YCT, BCT, and frequency-tagged words plus specific Simplified words.
  It can also include an optional `card_settings` object to bake display, Writer difficulty, and scoring settings into the generated templates.

Card-template code and resources live under `tooling/lib/anki_hanzi/deck/` because they are part of the generator rather than source data.

## `deck_config.json`

The deck config is a JSON object.
The generator requires a `selection` object.
Every other top-level key is optional and overrides built-in defaults.
Unknown card types, card-setting sections, audio settings, or card settings fail the build instead of being ignored.

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
Other mode values and unknown selection settings fail the build.

`selection.tags` may be a string or a list of strings.
Configured tags use the compact source form, such as `hsk:1` or `freq:top2500`.
Generated Anki notes namespace those tags under `hanzi::`, such as `hanzi::hsk::1`.

Common selection tags:

- `hsk:1` through `hsk:6`
- `hsk:7-9`
- `yct:1` through `yct:4`
- `bct:a` and `bct:b`
- `freq:top500`
- `freq:top2500`
- `freq:top10000`

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
The configured list must not be empty or contain duplicates.

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
Supported card types are `Meaning`, `Pinyin`, and `Write`.
Meaning and Pinyin group display settings under `front` and `back`.
All Writer settings live directly under `card_settings.Write`, without side-specific or scoring subsections.
Only settings listed below are accepted.
All settings are optional; omitted values keep their defaults. The checked-in Writer settings explicitly show the current defaults for experimentation.
Settings for card types not included in `card_types` do not generate additional cards.

Meaning and Pinyin settings:

- `show_pinyin`: boolean, default `true`
- `show_meaning`: boolean, default `true`
- `show_simplified`: boolean, default `true`

Write settings:

- `show_pinyin`: boolean, default `true`
- `show_meaning`: boolean, default `true`
- `show_grid`: boolean, default `false`
- `show_outline`: boolean, default `false`
- `stroke_tone_color`: boolean, default `true`
- `grid_size`: integer from `100` to `1000`, default `400`
- `stroke_width`: integer from `2` to `100`, default `64`. Visual pen width, not stroke-acceptance tolerance.
- `hint_after_misses`: integer from `0` to `10`, default `0`. `0` disables automatic hints; otherwise hints start after this many mistakes on the current stroke.
- `stroke_leniency`: number from `0.1` to `2.0`, default `0.8`. Lower is stricter, higher is more forgiving. This scales Hanzi Writer's stroke-matching tolerances, not the score penalty. Try small changes around `0.8` or `1.0` first.
- `accept_backwards_strokes`: boolean, default `false`. When `true`, an otherwise matching stroke may be drawn in the reverse direction. Stroke order is still required.
- `hint_animation_speed`: number from `0.1` to `5.0`, default `0.5`. Smaller values show the hint more slowly. This changes timing only, not the hint penalty.
- `mistake_penalty_stroke_ratio`: number from `0` to `5`, default `1.0`. Deduction per rejected stroke, as a multiple of one stroke's score value.
- `hint_penalty_stroke_ratio`: number from `0` to `5`, default `2.0`. Deduction per hinted stroke, as a multiple of one stroke's score value.
- `hard_min_score`: integer from `0` to `99`, default `65`. Minimum score for the `Hard` suggestion.
- `good_min_score`: integer from `1` to `100`, default `80`. Minimum score for the `Good` suggestion. Must be greater than `hard_min_score`.

Practice options map to the pinned [Hanzi Writer API](https://hanziwriter.org/docs.html#api).
Automatic acceptance after repeated mistakes remains disabled: a stroke must still match.
`show_outline` is a continuous visual aid; enabling it does not itself deduct points.
The written answer stays hidden during practice and appears after completion or on the answer side; this is template behavior, not a separate setting.

#### Score Calculation

One stroke's value is `100 / N`, where `N` is the total number of strokes across the entire word, not just the current character.
For `C` correctly completed strokes, `M` mistakes, and `H` hinted strokes:

```text
score = round(100 * C/N
              - M * (100/N) * mistake_penalty_stroke_ratio
              - H * (100/N) * hint_penalty_stroke_ratio)
```

The result is limited to `0` through `100`; no loaded strokes means a base score of `0`.
Manual and automatic hints share the same counter: each stroke is charged only once, even if hinted repeatedly.
A mistake that triggers an automatic hint incurs both deductions.
With ten total strokes and the defaults, one mistake costs ten points and one hinted stroke costs twenty points.
Setting a penalty to `0` removes that deduction, but the mistake or hint is still recorded.

`Easy` remains reserved for a score of `100` with every stroke completed and no mistakes or assists.
Otherwise the suggestion is `Good`, then `Hard`, then `Again`, according to the two thresholds.
These are suggestions only; the settings do not press Anki's answer buttons or change its scheduling.
Changing them updates the Write template, not note contents or note IDs. Rebuild and migrate the APKG to apply them.

Example `card_settings` override:

```json
{
  "selection": {
    "mode": "tagged",
    "tags": ["hsk:1"]
  },
  "card_settings": {
    "Write": {
      "show_pinyin": true,
      "show_meaning": true,
      "show_grid": false,
      "show_outline": false,
      "stroke_tone_color": true,
      "grid_size": 400,
      "stroke_width": 64,
      "hint_after_misses": 0,
      "stroke_leniency": 0.8,
      "accept_backwards_strokes": false,
      "hint_animation_speed": 0.5,
      "mistake_penalty_stroke_ratio": 1.0,
      "hint_penalty_stroke_ratio": 2.0,
      "hard_min_score": 65,
      "good_min_score": 80
    }
  }
}
```
