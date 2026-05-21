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
- `generate_xiehanzi_deck.py`: reference generator from the prepared xiehanzi
  TSV inputs.
- `generate_xiehanzi_deck_from_enriched_db.py`: reproduction generator from the
  enriched JSON database. It reads `deck_inputs/deck_config.json` to select
  which xiehanzi study targets become notes.
- `verify_xiehanzi_apkg_build.py`: compare both generated APKGs.
- `update_cc_cedict_snapshot.py`: refresh the pinned CC-CEDICT snapshot when an
  intentional source-data update is needed.
