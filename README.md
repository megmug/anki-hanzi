# Anki-xiehanzi Custom Deck Fork

This repository is a personal fork of
[krmanik/Anki-xiehanzi](https://github.com/krmanik/Anki-xiehanzi). The original
project provides the upstream Anki-xiehanzi deck, website, and browser-based
deck generator. This fork keeps the parts needed for my own Mandarin study deck
and has diverged intentionally.

The current build produces one custom APKG:

- `Anki-xiehanzi - New HSK (2025).apkg`

The filename is kept for compatibility with the inherited deck lineage, but the
fork is focused on the current HSK 3.0 / 2026-oriented study setup rather than
the older upstream deck matrix.

## What Is Different

Compared with upstream, this fork currently:

- builds only the custom New HSK / HSK 3.0 deck, not the full upstream set of
  deck variants;
- removes sentence cards and the separate audio-only card type;
- keeps Meaning, Pinyin, and Write cards;
- defaults the templates to Simplified Chinese and Pinyin, with Traditional
  characters and Zhuyin disabled;
- adds a HanziWriter-based scoring panel for Write cards;
- builds from a Python/Nix pipeline instead of the old website generator;
- uses a compact CC-CEDICT-derived JSON database enriched with xiehanzi HSK
  study targets;
- checks the generated APKG against a pinned last-known-good hash by default.

This is not intended to remain a cleanly syncable fork of upstream. The upstream
repository remains useful as historical reference and source attribution.

## Build

Initialize submodules first:

```sh
git submodule update --init --recursive
```

Then build the APKG with Nix:

```sh
nix-build
```

`nix-build` creates the default `result` symlink. The APKG and build reports are
written there.

The default build is invariant: it verifies that the APKG hash still matches the
pin in `deck_inputs/apkg_build_invariant.json`. If an intentional deck-output
change is made, update that pin deliberately after reviewing the diff.

## Repository Layout

- `deck_inputs/`: committed source inputs for the deck build, including card
  templates, deck config, the pinned CC-CEDICT snapshot, extra words, audio
  inputs, and the HSK/xiehanzi word-list submodule.
- `scripts/`: the Python source-of-truth build pipeline.
- `_migrator-repo/`: Anki Debug Console migration tooling used to migrate an
  existing local collection to the generated deck while preserving scheduling
  state.
- `.github/workflows/`: CI build workflow that runs the Nix build and uploads
  artifacts.

Generated JSON databases, reports, and APKGs should stay in build output
directories such as `result`, not in the repository root.

## Updating Source Data

The normal build is offline and uses the committed CC-CEDICT snapshot. To update
that snapshot intentionally, run:

```sh
nix-shell --run "python scripts/update_cc_cedict_snapshot.py"
```

Then run `nix-build`, review the changed data and generated APKG, and commit the
updated snapshot and hash pin only if the change is intended.

## Safety

Before importing or migrating Anki decks, make a full Anki backup.
There is currently no generally usable migration path from upstream xie hanzi decks.

## Acknowledgements

This fork builds on the original
[Anki-xiehanzi](https://github.com/krmanik/Anki-xiehanzi) project by Mani
(`krmanik`).

The writing component uses
[HanziWriter](https://github.com/chanind/hanzi-writer). HanziWriter's character
and stroke-order data is derived from
[Make Me a Hanzi](https://github.com/skishore/makemeahanzi).

The lexical base data uses a pinned
[CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cedict) snapshot from
MDBG. See `deck_inputs/cc-cedict/README.md` for snapshot details.

## License

This fork preserves the upstream license files and third-party license notices.
See `License.md` and the license files in the vendored input directories.

## AI-Generated Code Notice

Some code and documentation in this fork was produced or edited with AI
assistance. Human review is still required before trusting generated deck output.
