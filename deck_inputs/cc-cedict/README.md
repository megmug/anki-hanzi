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
it, extracts `cedict_ts.u8`, and rewrites this directory. Then rebuild and
commit the changed snapshot, manifest, and reports if the new data is
intentional.

- Source URL: `https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip`
- Snapshot date from file header: `2026-05-19T07:10:24Z`
- Entries from file header: `124934`
- Publisher from file header: `MDBG`
- Snapshot file: `cedict_ts.u8`
- Snapshot SHA256: `676c0ebe5354ac79469d850e67e85adfd42b0c2e07b88b0f3c58e24eae87dd24`
- License: https://creativecommons.org/licenses/by-sa/4.0/
