# CC-CEDICT Snapshot

This directory contains the pinned CC-CEDICT source snapshot used by the local
deck build.

The upstream MDBG export URL is mutable, so the build vendors the exact source
archive needed for reproducible APKG generation instead of downloading the
latest file during `nix-build`.

To update the snapshot from the latest upstream export, run:

```sh
nix-shell --run "python custom_update_cc_cedict_snapshot.py"
```

The update command downloads the current archive from the URL below, validates
it, and rewrites this directory. Then rebuild and commit the changed snapshot,
manifest, and reports if the new data is intentional.

- Source URL: `https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip`
- Snapshot date from file header: `2026-05-19T07:10:24Z`
- Entries from file header: `124934`
- Publisher from file header: `MDBG`
- SHA256: `5ae885402b7873dea15f3f905bd4ac0e078d9cf68ddd873f0065fd7119154856`
- License: https://creativecommons.org/licenses/by-sa/4.0/
