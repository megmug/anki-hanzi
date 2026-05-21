# Scripts

These scripts are the current source-of-truth build pipeline for the custom
xiehanzi APKG.

Run the full build with:

```sh
nix-build --out-link result
```

Pipeline stages:

- `build_cc_cedict_master_db.py`: build the compact CC-CEDICT master lexicon
  from the pinned snapshot in `deck_inputs/cc-cedict/`.
- `enrich_xiehanzi_db.py`: attach xiehanzi study targets from the deck input
  word lists to the master lexicon.
- `deck_build_common.py`: shared template, media, model, and stable-id helpers.
- `generate_xiehanzi_deck.py`: generate the APKG from the enriched JSON
  database. It reads `deck_inputs/deck_config.json` to select which xiehanzi
  study targets become notes.
- `verify_apkg_hash.py`: enforce or record the generated APKG hash against
  `deck_inputs/apkg_build_invariant.json`.
- `update_cc_cedict_snapshot.py`: refresh the pinned CC-CEDICT snapshot when an
  intentional source-data update is needed.
