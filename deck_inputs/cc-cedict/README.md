# CC-CEDICT Snapshot

This directory contains the pinned CC-CEDICT source snapshot used by the local
deck build.

The upstream MDBG export URL is mutable, so the build vendors the exact
CC-CEDICT text file needed for reproducible APKG generation instead of
downloading the latest file during `nix-build`.

To update the snapshot from the latest upstream export, run:

```sh
nix-shell --run "python scripts/update_cc_cedict_snapshot.py"
```

The update command downloads the current archive from the URL below, validates
it, extracts `cedict_ts.u8`, and rewrites this directory. Then rebuild
and commit the changed snapshot, manifest, and reports if the new data is
intentional.

- Source URL: `https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip`
- Snapshot date from file header: `2026-05-27T08:03:59Z`
- Entries from file header: `124970`
- Publisher from file header: `MDBG`
- Snapshot file: `cedict_ts.u8`
- Snapshot SHA256: `ad88e061638da798d7c659a82300e5f38df40732f6503bce61a3212f2093ef83`
- License: https://creativecommons.org/licenses/by-sa/4.0/
