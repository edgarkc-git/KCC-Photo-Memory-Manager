---
name: photo-scan
description: >
  Stage 1-2 of the photo-manager pipeline (photo-scan -> photo-classify ->
  photo-plan -> photo-execute). Bulk-scans one source folder on the photo
  drive with exiftool into manifest.csv, then detects day/GPS legs into
  batches.json — the roadmap every later stage works from. Strictly read-only
  on the drive. Trigger when the owner asks to scan a photo folder, build a
  manifest, detect legs/batches, or start sorting a new raw dump (e.g. "scan
  202402", "build batches for ...").
---

# photo-scan — EXIF scan + leg detection

Version: 0.1 (Phase 2 build)

## What it does

Turns one source folder (a raw dump like `202401`, or a populated hand-named
folder for dedupe manifests) into state files that all later pipeline stages
read. No vision model needed — any text model can drive this skill.

## Configuration

| | |
|---|---|
| Scripts | `scripts/photo_scan.py`, `scripts/photo_cluster.py` |
| State files | `<workspace>/Working Files/<source-folder-name>/` |
| Shared geocode cache | `Working Files/geocode-cache.json` (Nominatim, 1 req/s) |
| Source drive | the owner's photo drive, e.g. `/Volumes/EXAMPLE_DRIVE` — **read-only, always** |
| Requires | exiftool (`brew install exiftool`), Python 3 stdlib only |

Pipeline scope (D-G): the raw dump folders under the collection's source
root, plus populated hand-named folders on the drive root when a dedupe
manifest is needed (OA-3).

## Workflow

1. **Scan** (long-running for big folders — run in background):
   ```
   python3 scripts/photo_scan.py "/Volumes/EXAMPLE_DRIVE/<source-root>/202401"
   ```
   Writes `manifest.csv`, `scan-summary.json`, `scan-errors.log`.
   ⛔ **Exit 3 = the scan read fewer photos and videos than the folder lists**
   (F04; seen on a network drive). No manifest is written and the census
   refuses to run. Tell the owner the count it printed, and that copying the
   photos to a local disk is the fix. Never carry on with the stages after it.
2. **Sanity-check counts** from the printed summary before clustering. The
   summary names every exclusion so the arithmetic closes exactly:
   `main_files + aae_ignored + appledouble_ignored = total_files_seen`. Check
   that identity, then that `total_files_seen` matches a Finder count of the
   folder, then that GPS coverage and the date range look plausible. If
   `scan-errors.log` is non-empty, read it and report before continuing.

   ⚠️ **Finder counts entries; the manifest counts media.** A folder showing
   more files than `main_files` is the ordinary case whenever the volume
   carries `.AAE` or `._*` AppleDouble sidecars — `total_files_seen` and the
   two `*_ignored` counts are what let you say so instead of guessing. Never
   report the gap as lost photos until the identity above fails to hold.
2b. **Check a manifest is still true** before trusting one that was written a
   while ago (A41) — folders get re-split and renamed on the drive and nothing
   downstream notices:
   ```
   python3 scripts/photo_scan.py --verify --workdir "<Working Files>/202401"
   ```
   Report-only: it never re-scans and never rewrites the manifest, because
   regenerating one reflows `batches.json`. Read `moved` before `gone` —
   measured on a real corpus, 27% of rows were stale while only 1.0% were
   actually missing; the rest had moved when folders were re-split, so
   staleness is **not** data loss. Its `indexed` block says how many files the
   walk actually saw and what it left out, which is what makes the
   `present of rows` ratio checkable against a folder listing.
3. **Cluster**:
   ```
   python3 scripts/photo_cluster.py "<Working Files>/202401"
   ```
   Writes `batches.json` (+ `no-date-files.csv` if any). Refuses to overwrite
   an existing `batches.json` without `--force` — never wipe batch statuses
   that later stages already advanced.
4. **Review batch boundaries** (the agent's real job): read `batches.json`,
   check the legs make sense (trip start/end days, away-trips split out,
   no batch > ~1,000 files unless flagged `oversize_day`). Adjust by editing
   `batches.json` directly or re-running with different `--max-batch` /
   `--away-km`. Present the batch table to the owner.
5. **Translate leftover labels into the pack's language.** All labels,
   reports and eventual folder names are written in the owner pack's
   `language` — never a mix. The script best-efforts a localised name via the
   OSM name tags for that language; where OSM has no such name (e.g. some
   administrative areas), the agent edits the `label` fields in `batches.json`
   into the pack's language before presenting. `status`/`flags` values stay as
   machine codes — they are pipeline state, not display text.

## Rules the scripts encode (do not undo by hand)

- Dates come from EXIF `DateTimeOriginal`/`CreateDate` only, never Finder
  dates; no `-fast2` (video dates sit at end of file). Files with no EXIF
  date go to `no-date-files.csv` for manual review — never auto-sorted.
- `.AAE` sidecars ignored entirely (D4) — counted in the summary, excluded
  from the manifest. Detected by FileType, not extension (some sidecars carry
  `.MP4` names).
- `._*` AppleDouble sidecars likewise — macOS metadata, not media, so they are
  excluded from the manifest and reported as `appledouble_ignored`. Do not
  remove the exclusion; the count beside it is what stops the exclusion being
  invisible.
- Batch labels are **provisional** (zoom-10 city reverse-geocode in the pack's
  language, traditional/regional variant preferred where the language has one)
  — real `[where]` naming is photo-classify's job (Overpass peaks+trails
  method).
- Batch status lifecycle: `pending -> classified -> planned -> approved -> done`.
  photo-scan only ever creates `pending`.

## Validation baseline

A regenerated run must reproduce the recorded counts for the dump it is
replayed against and find the same trip boundaries. The reference numbers for
a validated dump are: files seen = main files + AAE sidecars, a fixed no-date
count, and a human ground-truth batch table stored beside the dump as
`batches_phase1-groundtruth.json`.
