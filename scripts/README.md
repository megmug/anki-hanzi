# Scripts

These scripts are the current source-of-truth build pipeline for this fork's
hanzi APKG.

Run the full build with:

```sh
nix-build
```

Pipeline stages:

- `build_cc_cedict_master_db.py`: build the compact CC-CEDICT master lexicon
  from the pinned snapshot in `deck_inputs/cc-cedict/`.
- `enrich_hanzi_db.py`: attach hanzi study targets from the deck input
  word lists to the master lexicon.
- `meaning_html.py`: render hanzi-style Meaning HTML from structured word
  and form data.
- `deck_build_common.py`: shared template, media, model, and stable-id helpers.
- `generate_hanzi_deck.py`: generate the APKG from the enriched JSON
  database. It reads `deck_inputs/deck_config.json` to select which hanzi
  study targets become notes.
- `migrate-*.py`: stateful Anki Debug Console migration scripts. A filename
  `migrate-<old-hash>.py` migrates from that old build hash to the target APKG
  it is released with.
- `verify_apkg_hash.py`: enforce or record the generated APKG hash against
  `deck_inputs/apkg_build_invariant.json`.
- `update_cc_cedict_snapshot.py`: refresh the pinned CC-CEDICT snapshot when an
  intentional source-data update is needed.
