# anki-hanzi Deck

This repository is a personal project originally forked from [krmanik/Anki-xiehanzi](https://github.com/krmanik/Anki-xiehanzi).
The original project provides the upstream Anki-xiehanzi deck, website, and browser-based deck generator.
This fork keeps the parts needed for my own Mandarin study deck and has diverged intentionally.

## What Is Different

Compared with upstream, this fork currently:

- builds an APKG from the current CC-CEDICT snapshot; by default it selects all levels of the pinned HSK 3.0 / New HSK late-2025 word-list revision used for the current 2026 deck, YCT levels 1-4, BCT levels A-B, and the top 10,000 Mandarin frequency words;
- generates only the active Meaning, Pinyin, and Write card families, without sentence cards or a separate audio-only card type;
- adds tags such as `hanzi::hsk::1` and `hanzi::freq::top2500`, and uses one subdeck per card type;
- makes deck generation configurable so any set of tagged cards or individual words from the CC-CEDICT snapshot can be included, up to and including a full CC-CEDICT deck of roughly 360k cards, if so desired (not recommended);
- deduplicates the original data to avoid redundancy;
- makes the Write cards score your performance and recommend Again, Hard, Good, or Easy;
- packages HanziWriter and the required stroke data for offline Write cards, including scoring and configurable recognition leniency;
- makes Pinyin and Meaning cards generally more usable, fair, and less redundant;
- bakes deck display settings into the generated templates instead of exposing the old xiehanzi sidebar toggles inside Anki;
- keeps customization possible by rebuilding the deck with custom options and then using the migrator add-on to import it into Anki, which is more robust than the original xiehanzi approach;
- allows upgrading the deck to newer versions or other configurations through a bundled migrator add-on with preflight checks and a final verification report, covering a workflow Anki does not handle well by default;
- can optionally generate audio with Kokoro or edge-tts, but defaults to an audio-free build;
- builds from a much more reproducible Python/Nix pipeline and CI release workflow.

## How To Use

This deck is not intended to replace immersion or other established methods of acquiring Chinese, and it cannot provide meaningful reading comprehension, listening comprehension, or production ability by itself.
It is intended to be a low-maintenance, comprehensive, up-to-date, and free companion to your Chinese learning journey.
Its main purpose is to help you learn 汉字, the Chinese characters, as well as words built from them, by writing them yourself and associating them with pinyin, optionally audio, and meaning.

In its default configuration, the deck is huge, and with custom configuration it can cover the entire dictionary.
After a fresh import, you should therefore suspend all cards and only activate those that you are actively trying to memorize.
As you learn new characters and words that you want to memorize, you can activate more and more cards, covering a larger and larger part of the material.
Do not use the deck to learn new characters and words from scratch - use it to reinforce what you have already learned elsewhere.

As updates to the dictionary or to other aspects of the deck become available, you can migrate to newer versions and benefit from the improvements without losing your learning progress.

To start, either choose a recent release and download the deck from GitHub Releases (https://github.com/megmug/anki-hanzi/releases), or build it yourself with the instructions below.

## Build

System requirements:
- Linux or macOS (on Windows, you will need to use WSL2)
- Nix package manager

After cloning the repo, initialize submodules first:
```sh
git submodule update --init --recursive
```

Then build the APKG with Nix:
```sh
nix-build
```

On a Linux machine with an NVIDIA GPU and `audio.engine` set to `kokoro`, Nix probes for a usable CUDA driver and can install CUDA-capable PyTorch into the build's isolated temporary `pip` prefix.
If no NVIDIA driver is available, or on macOS, the build uses CPU PyTorch.
Audio builds that need network access for model downloads may require a relaxed Nix sandbox configuration.

`nix-build` creates the default `result` symlink.
The build result contains the hash-named APKG, a matching hash-named migrator add-on, and one stage-oriented `build_report.json`.

## Repository Layout

- `deck_inputs/`: committed source inputs for the deck build, including the deck config, pinned CC-CEDICT snapshot, and HSK/xiehanzi word-list submodule.
- `tooling/`: Python build, utility, shared helper, and card-template code.
- `.github/workflows/`: CI build workflow that runs the Nix build, uploads artifacts, and generates releases.
- `result/`: where the build artifacts land.

## Updating Source Data

The build uses the committed CC-CEDICT snapshot.
To update that snapshot, run:

```sh
nix-shell --run "python tooling/utilities/update_cc_cedict_snapshot.py"
```

Run this from the project root.
Then run `nix-build`, review the changed data and generated APKG, and commit the updated snapshot only if the change is intended.

## Migrating from a Previous Version

Each build includes a stateless Anki add-on named `anki-hanzi-migrator-<hash>.ankiaddon`, where `<hash>` is the target build ID.
Install that add-on in Anki when you want to migrate an existing Hanzi deck to the matching APKG.

### How to migrate

1. **Build the new artifacts**: run `nix-build` in this repo and keep the `result/` symlink, or download the APKG and matching migrator add-on from GitHub Releases.
2. **Install the migrator add-on**: in Anki, install the generated `.ankiaddon` file.
3. **Backup your Anki collection**: export a full `.colpkg` from the profile that contains your current deck.
4. **Run the migrator**: use *Tools → Anki Hanzi Migrator → Migrate Deck...*, select the existing deck root, and choose the target APKG.
5. **Review the route and preflight**: select any intermediate APKGs requested by the route planner, then review each preflight dialog before applying the step.
6. **Verify**: check deck name, note types, suspended cards, review counts, and deck preset before syncing.

The migrator add-on:
- snapshots scheduler state + review history from your old deck,
- deletes the old deck root,
- imports the new APKG,
- default-suspends every generated target card,
- matches only learned/touched old cards to new cards by stable NoteID/GUID where possible and by controlled loose keys when card identity changed,
- copies full scheduler state, suspended state, and revlog for those learned cards,
- leaves untouched generated cards in their default suspended state,
- verifies after every step that database records outside the migrated deck tree and all deck presets are unchanged.

## Safety

Before importing or migrating Anki decks, make a full Anki backup.
The database preservation check covers cards, notes, review history, deck records, note types, fields, templates,
and presets. It excludes collection-wide bookkeeping (such as sync metadata and tag caches) and media files.
Any mismatch or verification error stops the migration route; this detects damage but does not automatically roll it back.
Restore the collection backup if a migration step fails.
There is currently no generally usable migration path from upstream xiehanzi decks.

## Acknowledgements

This fork builds on the original [Anki-xiehanzi](https://github.com/krmanik/Anki-xiehanzi) project by Mani (`krmanik`).

The writing component uses [HanziWriter](https://github.com/chanind/hanzi-writer).
HanziWriter's character and stroke-order data is derived from [Make Me a Hanzi](https://github.com/skishore/makemeahanzi).

The lexical base data uses a pinned [CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cedict) snapshot from MDBG.
See `deck_inputs/cc-cedict/README.md` for snapshot details.

## License

This fork preserves the upstream license files and third-party license notices.
See `License.md` and the license files in the vendored input directories.

## AI-Generated Code Notice

Some code and documentation in this fork was produced or edited with AI assistance.
Human review is still required before trusting generated deck output.
