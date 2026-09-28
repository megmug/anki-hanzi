# Tooling

This directory contains the Python build pipeline, project utilities, and shared helper code.

Run the full build with:

```sh
nix-build
```

## Build

`default.nix` invokes one build entry point during the normal APKG build.

- `build/generate_hanzi_deck.py`: build the typed lexicon state, generate the APKG, and package the migrator add-on.
  The build writes one stage-oriented `build_reports/build_report.json` with source, enrichment, matching, selection,
  audio, HanziWriter, and package summaries.
  Full diagnostic lexicon JSON dumps are off by default; pass `--master-db-output` and/or `--enriched-db-output`
  when running the CLI directly, or build with `nix-build --arg writeDiagnosticDatabases true` to include them under
  `result/diagnostics/`.

## Utilities

These programs are run manually for maintenance, analysis, or upgrades.

- `utilities/diff_apkg.py`: compare two APKG files semantically and write a Markdown diff report.
- `utilities/anki_hanzi_migrator/`: stateless Anki add-on that plans a BuildID migration route and migrates a selected
  existing Hanzi deck through step-specific preflight/apply/result phases to a selected target APKG.
- `utilities/update_cc_cedict_snapshot.py`: refresh the pinned CC-CEDICT snapshot when an intentional source-data update is needed.

## Formatting

Run `nix-shell --run "treefmt"` to format maintained Python and Nix code.
Treefmt uses Ruff for Python and nixfmt for Nix.
Vendored deck inputs are excluded.

## Library

These modules are imported by build programs and are not direct entry points.

- `lib/anki_hanzi/deck/build.py`: typed lexicon-to-APKG build orchestration.
- `lib/anki_hanzi/deck/common.py`: shared paths and genanki deck assembly helpers.
- `lib/anki_hanzi/deck/config.py`: deck configuration data structures and parser.
- `lib/anki_hanzi/deck/entries.py`: enriched lexicon state to card-entry selection.
- `lib/anki_hanzi/deck/identity.py`: stable deck, note, model, and tag identity helpers.
- `lib/anki_hanzi/deck/reports.py`: build report assembly.
- `lib/anki_hanzi/deck/template_generation.py`: Meaning, Pinyin, and Write template composition and validation.
- `lib/anki_hanzi/deck/templates.py`: template resource loading and marker injection.
- `lib/anki_hanzi/deck/workspace.py`: isolated workspace for generated media and intermediate build artifacts.
- `lib/anki_hanzi/enrichment/`: HSK/xiehanzi, frequency, YCT, BCT, and erhua enrichment stages.
  HSK and BCT matching use explicit ordered buckets and consumption rules; their terminal unresolved buckets must be
  empty for the build to succeed.
- `lib/anki_hanzi/json_io.py`: stable JSON formatting and file output helpers.
- `lib/anki_hanzi/lexicon/`: internal lexicon state and CC-CEDICT source parser.
- `lib/anki_hanzi/paths.py`: shared paths to committed project inputs.
- `lib/anki_hanzi/rendering/meaning_html.py`: render hanzi-style Meaning HTML from structured word and form data.
- `lib/anki_hanzi/audio/`: provider-neutral audio generation plus Kokoro and edge-tts backends.

## Card Layout

All three card types share the shell, prompts, touch controls, and responsive styling in
`lib/anki_hanzi/deck/template_generation.py` and `lib/anki_hanzi/deck/template_resources/`. Definitions scroll independently
beside the practice area on wider screens and below it on phones. Card data and note identities
are independent of this layout.

On wider screens, Write cards reserve 60% of the layout for practice, score, and controls;
definitions occupy the remaining 40%. On phones, definitions, score, and controls sit below
the writing area in that order.
Writer Pinyin appears only in the definitions panel, with the separate prompt retained as a
fallback when definitions are hidden by configuration.

The entire Write card surface is `tappable`, opting out of AnkiMobile's tap-to-answer gestures.
Use Anki's native **Show Answer** control (keep the bottom bar enabled on AnkiMobile).
The template does not emulate a tap zone or grade a card. Other card types retain their normal
tap behaviour. Hint targets are larger, with a slower stroke animation. Resizing the Writer
updates existing instances without starting the quiz again.
