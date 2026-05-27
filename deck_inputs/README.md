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
  levels plus specific Simplified words.
- `apkg_build_invariant.json`: last-known-good APKG size and SHA256 used by the
  default invariant build.
- `extra_audio/`: committed/generated audio files for selected entries.
- `card_templates/`: active Anki card HTML/CSS templates and static media
  packaged into the APKG. The active template subdirectories are `meaning/`,
  `pinyin/`, and `write/`.
