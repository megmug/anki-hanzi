# CC-CEDICT Snapshot

This directory contains the pinned CC-CEDICT source snapshot used by the local
deck build.

The upstream MDBG export URL is mutable, so the build vendors the exact
CC-CEDICT text file needed for reproducible APKG generation instead of
downloading the latest file during `nix-build`.

To update the snapshot from the latest upstream export, run:

```sh
nix-shell --run "python tooling/utilities/update_cc_cedict_snapshot.py"
```

The update command downloads the current archive from the URL below, validates
it, extracts `cedict_ts.u8`, and rewrites this directory. Then rebuild
and commit the changed snapshot, manifest, and reports if the new data is
intentional.

- Source URL: `https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip`
- Snapshot date from file header: `2026-09-27T12:50:23Z`
- Entries from file header: `125127`
- Publisher from file header: `MDBG`
- Snapshot file: `cedict_ts.u8`
- Snapshot SHA256: `bd688366ed8e5edc6c109cdaac1c61767ba742aa85e45cab61c0817cf5303696`
- License: https://creativecommons.org/licenses/by-sa/4.0/
