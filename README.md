# anki-hanzi Deck

This repository is a personal project originally forked from [krmanik/Anki-xiehanzi](https://github.com/krmanik/Anki-xiehanzi).
The original project provides the upstream Anki-xiehanzi deck, website, and browser-based deck generator.
This fork keeps the parts needed for my own Mandarin study deck and has diverged intentionally.

## What Is Different

Compared with upstream, this fork currently:

- builds an APKG from the current CC-CEDICT snapshot, with the default config selecting the New HSK (2025) / HSK 3.0 word list;
- generates only the active Meaning, Pinyin, and Write card families, without sentence cards or a separate audio-only card type;
- keeps note fields deliberately small: Simplified, Pinyin, Meaning, Audio, NoteID, and BuildID - no Zhuyin, no Traditional;
- adds tags such as `hanzi::hsk::1` and `hanzi::freq::top2500`, and uses one subdeck per card type;
- makes deck generation configurable so any set of tagged cards or individual words from the CC-CEDICT snapshot can be included, up to and including a full CC-CEDICT deck of roughly 360k cards, if so desired (not recommended);
- deduplicates the original data to avoid redundancy;
- makes the Write cards score your performance and recommend Again, Hard, Good, or Easy;
- packages HanziWriter and the required stroke data for offline Write cards, including scoring and configurable recognition leniency;
- makes Pinyin and Meaning cards generally more usable, fair, and less redundant;
- bakes deck display settings into the generated templates instead of exposing the old xiehanzi sidebar toggles inside Anki;
- keeps customization possible by rebuilding the deck with custom options and then using the migration script to import it into Anki, which is more robust than the original xiehanzi approach;
- allows upgrading the deck to newer versions or other configurations through a migration script that you paste into the Anki debug console, covering a workflow Anki does not handle well by default;
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
nix-build --no-sandbox
```
Depending on your Nix configuration, `--no-sandbox` may require your account to be a trusted user.
Refer to the Nix documentation if you need to configure this.

On a Linux machine with an NVIDIA GPU, Nix can install CUDA-capable PyTorch for you.
It puts PyTorch into the build's isolated temporary `pip` prefix, so there is no need to clean up afterward:
```sh
nix-build --arg enableCuda true --no-sandbox
```
`nix-build` creates the default `result` symlink.
The build result contains the hash-named APKG, generated reports, and any checked-in migration scripts.

## Repository Layout

- `deck_inputs/`: committed source inputs for the deck build, including card templates, deck config, the pinned CC-CEDICT snapshot, and the HSK/xiehanzi word-list submodule.
- `scripts/`: the Python build pipeline.
- `.github/workflows/`: CI build workflow that runs the Nix build, uploads artifacts, and generates releases.
- `result/`: where the build artifacts land.

## Updating Source Data

The build uses the committed CC-CEDICT snapshot.
To update that snapshot, run:

```sh
nix-shell --run "python scripts/update_cc_cedict_snapshot.py"
```

Run this from the project root.
Then run `nix-build`, review the changed data and generated APKG, and commit the updated snapshot only if the change is intended.

## Migrating from a Previous Version

Each release that changes deck identity includes a migration script under `scripts/`.
The script name is `migrate-<hash>.py`, where `<hash>` is the short commit hash of the **previous** version you are upgrading from.

Example: to upgrade a deck built from commit `e7eeb8e` to the current version, use `scripts/migrate-e7eeb8e.py`.

### How to migrate

1. **Build the new APKG**: run `nix-build` in this repo and keep the `result/` symlink, or download the new deck with default settings from GitHub Releases.
2. **Backup your Anki collection**: export a full `.colpkg` from the profile that contains your current deck.
3. **Adjust the script**: open the migration script and edit the values in the `CONFIGURATION` block at the top:
   - `APKG_PATH` — absolute path to the newly built/downloaded APKG.
   - `DECK_ROOT` — the name of the deck root in your existing Anki collection.
   - `TARGET_PRESET_NAME` — the deck options preset to apply (if unsure, check which preset your current deck uses and use that value).
4. **Test in a throw-away profile**: copy the script contents into Anki's *Debug Console* (Help → Debug Console) and run it. Inspect the report.
5. **Verify**: check deck name, note types, suspended cards, review counts, and deck preset before syncing.

The migration script:
- snapshots scheduler state + review history from your old deck,
- deletes the old deck root,
- imports the new APKG,
- default-suspends every generated target card,
- matches only learned/touched old cards to new cards by stable NoteID/GUID where possible and by controlled loose keys when card identity changed,
- copies full scheduler state, suspended state, and revlog for those learned cards,
- leaves untouched generated cards in their default suspended state.

### Keeping migration scripts

Migration scripts are kept permanently in `scripts/`.
When you later upgrade to a newer commit, use the matching `migrate-<hash>.py` for the commit you are upgrading from.
You might need to migrate multiple times in a row, using the appropriate migration scripts, to catch up to the latest version.

## Safety

Before importing or migrating Anki decks, make a full Anki backup.
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
