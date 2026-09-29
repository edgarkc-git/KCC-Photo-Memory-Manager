# SKILL — photo-format-check

Version: 0.1 (initial — wraps `photo_rename_mismatches.py`)

Check a folder (recursively) for **extension-mislabeled files — above all
`.HEIC` files that are really QuickTime movies** — and rename them in place to
their true extension (mostly `.HEIC` → `.MOV`). Standalone maintenance skill:
run it on any destination / hand-named folder on demand, no pipeline state
needed. Trigger when the owner says "check formats", "fix HEIC", "extension
mislabeled", "photo-format-check", or points at a folder where photos won't
open / show as the wrong kind.

Runs on any text model. Requires: Python 3 (stdlib only), exiftool, the Unix
`file` command, the shared `scripts/` folder.

## Why this exists (L17)

exiftool's `FileType`/`FileTypeExtension` misreports some HEIC-named
QuickTime movies (Live Photo video components) as genuine HEIC — both formats
share the ISO-BMFF container and exiftool's brand-atom heuristic gets
confused. `scripts/photo_rename_mismatches.py` therefore runs TWO passes:

1. exiftool `FileTypeExtension` vs extension — all files, all formats
2. magic-byte sniff (`file --mime-type`) on **every `.HEIC`** —
   `video/quicktime` → `.MOV`, `video/mp4` → `.MP4`

Real cases measured on two shipped folders: 66 mislabeled `.HEIC` in a
17-day overseas trip folder (the exiftool pass alone said 0), and 17 in a
one-day trip folder.

## Hard rules

- **Never run on raw source dumps** (`202401`, `202402`, … as they arrive off
  the phone) — those are originals; renaming there violates the copy-only
  policy. Destination folders under the collection's `dest_root` and
  hand-named folders on the drive root are fine (they hold copies).
- `.AAE` sidecars are skipped entirely (D4).
- **Never overwrite**: if the corrected name already exists (e.g. a real
  `IMG_1234.MOV` next to a mislabeled `IMG_1234.HEIC`), the renamed file gets
  a `_dup2`/`_dup3`… suffix (L12). Different content is preserved, always.
- Dry-run is the default; nothing is renamed without `--go`.

## Workflow

**1. Dry-run and review** (recursive, sub-folders included):

    python3 scripts/photo_rename_mismatches.py "<folder>" [<folder> ...]

Review the `[would rename]` list. Sanity checks worth doing on a sample:
`file -b <path>` on a flagged file should confirm the new extension;
a flagged count wildly out of line with the folder size deserves a look
before proceeding.

**2. Rename**:

    python3 scripts/photo_rename_mismatches.py "<folder>" --go

**3. Verify** — re-run the dry-run: it must report `0 mismatched file(s)`.
Report to the owner: files renamed, any `_dup2` collisions, zero-remaining
confirmation.

## Revert

Renames only — no file content is ever touched. To revert, rename the file
back (the `--go` output logs every `old → new` pair; keep the transcript).

## Eval record

- One 5-day trip folder under `dest_root` (1,027 files, 5 leg sub-folders):
  **45 mislabeled files found and renamed** — 34 `.HEIC`→`.MOV` (all caught
  by the magic-byte pass, exiftool said HEIC), 9 `.HEIC`→`.PNG`, 2
  `.HEIC`→`.JPG`; 4/4 magic-byte spot-checks confirmed before `--go`; 0
  collisions (`_dup2` never needed); re-run after = 0 mismatches; file count
  unchanged (1,027). The rename log is kept in that folder's work dir as
  `format-check-renames_<date>.log`.
