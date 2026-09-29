---
name: photo-embed
description: >
  VS-1 of the photo-manager v2 Visual Sorting module. Builds a local CLIP
  embedding index (photo_embed.py) for one work dir, or refreshes a global
  index over an already-sorted tree. Every image is embedded directly; every
  video contributes one representative frame. Never sampled — every eligible
  file is embedded. This is what later Visual Sorting stages (VS-1b recurrence census, VS-3
  subject matching) read from. Trigger when the owner asks to embed a dump,
  build a visual index, or refresh the global recurrence index (e.g. "embed
  202401", "build the visual index", "refresh the global photo index").
---

# photo-embed — CLIP embedding index (VS-1)

Version: 0.3 (VS-1 build + code-review fixes E-1..E-7 + L17 magic-byte coverage fix)

## What it does

Turns manifest.csv into a local visual index: one L2-normalized CLIP vector
per file. It answers no questions on its own — recognition (VS-3), scene
labels (VS-2) and the recurrence census (VS-1b) all read this index rather
than touching pixels a second time.

Runs on any text model — no vision model call happens here. It needs the
`.venv` (below), not Opus.

## Configuration

| | |
|---|---|
| Script | `scripts/photo_embed.py` |
| Model | OpenCLIP `ViT-B-32` / `laion2b_s34b_b79k` — local, MPS-accelerated on Apple Silicon |
| Env | `.venv/` in the repo root (`torch`, `open_clip_torch`, `numpy`, `pillow`) — not the system Python |
| Reused from photo-classify | `photo_sample.IMAGE_TYPES` / `VIDEO_TYPES` only |
| Previews | `convert_to_thumbnail`, the engine's ONE converter (photo_sample, photo_see, identity, memory and the onboarding page all call it). Picks by exiftool `FileType`, never the filename suffix. Backend from `$PHOTO_PREVIEW_BACKEND`: **`pillow`** (default, every machine — Pillow, plus `pillow-heif` for HEIC, and ffmpeg for one video frame: a system `ffmpeg` on PATH first, else the one `imageio-ffmpeg` ships) or **`sips`** (macOS `sips` + `qlmanage`, kept as the fallback). The backend is stamped into `embeddings-meta.json` and one index never mixes two |
| Output (per-workdir mode) | `<workdir>/embed/embeddings.npy` + `embeddings.csv` + `embeddings-meta.json` + `embed-errors.log` + `paperwork-scores.json` (one paperwork score per embedded still, read by `photo_plan`; a plain re-run fills it in for an older index) |
| Output (`--index-root` mode) | `<root>/.photo-embed-index/` — same shape, plus `folder-centroids.json` |

## Workflow

**1. Per-workdir (the normal case, after `photo-scan`):**

    ./.venv/bin/python3 scripts/photo_embed.py "<Working Files>/202401"

On Windows the interpreter is `.venv\Scripts\python.exe` wherever this says `./.venv/bin/python3`.

Reads `manifest.csv`; skips AAE sidecars and anything that isn't an image or
video by exiftool `FileType`. Resumable by default — re-running skips any
file whose (size, mtime) already matches what was last recorded, and only
(re)embeds new or changed files. `--force` rebuilds the whole index (needed
after a model change — see below).

The summary is one fixed shape on every path:

    files_seen · total_in_index · already_embedded · newly_embedded ·
    reclaimed · failed · skipped_ineligible · skipped_missing · pruned ·
    magic_corrected · failed_by_cause · preview_backend · device

⛔ **Exit 3 means some files got no preview.** The index is saved (a failed
file keeps a zero vector and is retried on the next run), and stderr prints
one line per cause with its count — `no_ffmpeg (…)`, `no_heif_decoder (…)`,
`no_sips (…)`, `decode_failed`, `no_video_frame`, `timeout`,
`source_missing`. Most causes name what to install. An unattended run treats
it as a stop, not a warning: a file with no vector is invisible to every
later stage. Exit 1 with a message about `sips`/`pillow` previews means the
index was built with the other backend — rebuild with `--force`, or set
`PHOTO_PREVIEW_BACKEND` to the one it names.

`skipped_ineligible` (not an image/video) and `skipped_missing` (in the
manifest but gone from disk at embed time — e.g. a D13 extension correction
renamed it after the scan) are the two ways a manifest row legitimately
never reaches the index; the arithmetic closes, so a silent disappearance is
now visible. `magic_corrected` sits outside that arithmetic — it counts
files whose image/video kind the magic-byte check overruled, not a
disposition. `device` is `null` when the run had nothing to do and never
loaded the model.

**2. Global index over a sorted tree (VS-1b prerequisite, optional, run by
hand — not wired into `photo_execute.py`):**

    ./.venv/bin/python3 scripts/photo_embed.py --index-root "/Volumes/EXAMPLE_DRIVE/_Photo_Manager"

Walks the tree, embeds every file (FileType inferred from extension — no
exiftool pass), and writes per-folder centroids alongside the per-file index.
This is a separate, deliberately un-automated step: the golden-dump harness
covers the PLAN stage only, so a hook into execute would ship un-guarded.

⚠️ **This mode starts from the suffix, so the magic-byte check below is the
only thing standing between it and a D13-style mismatch.** With no exiftool
pass, `kind_of()` and the dispatch extension would otherwise both come from
the same lying filename and the mismatch would never become visible — the
`dest_root` tree contains exactly the files this bit us on in per-workdir
mode (that's where they get copied to). The magic-byte check
runs here too, but the residual is wider than in per-workdir mode: it only
sees files that already reached the pending list, so a suffix `kind_of()`
can't place at all (a `.HEIF` name, say) is skipped before magic bytes get
a vote. An exiftool pass first (`photo_scan.py`) is still the safer route
for a tree known to hold mismatches.

## Hard rules

- **Model identity is guarded.** `embeddings-meta.json` records `model_id`,
  `pretrained_tag`, `embed_dim`, `normalized`, and a preprocess fingerprint.
  A run that would mix a different model's vectors into an existing index
  hard-fails with the mismatch named — cosine similarity and every VS-3/VS-4
  stored threshold are only meaningful within one model + preprocess regime.
  Pass `--force` only once you mean to invalidate the whole index (and
  everything downstream that referenced its vectors, e.g. exemplar
  `vec_ref`s in a subject registry).
- **Never sampled** — every eligible file is embedded. Sampling belongs to
  the see controller (VS-2), not here. Actual coverage is whatever survives
  conversion and is reported honestly in the summary (99.85% on the
  reference dump — see the exit criteria), never rounded up to "100%".
- **The index only ever describes files that exist.** A row whose file is
  gone is pruned before saving; without that, a folder rename counted the
  same photo twice and left a centroid for a folder that no longer exists —
  which is exactly what VS-1b's recurrence census reads. A file that only
  moved keeps its vector (matched by sha256 against the pruned rows, gated
  on a size match so an unchanged run hashes nothing). If every indexed file
  is missing and nothing is pending, the run assumes an unmounted drive and
  leaves the index untouched rather than emptying it.
- **A failed file is a zero vector, not a missing row.** `.npy` row *i* is
  always `.csv` row *i*; failures keep their slot with an all-zero vector and
  `status: failed`. `embeddings-meta.json` states this as
  `"zero_vector_means_failed": true` — a reader that indexes the `.npy` by
  row position must filter on it (or on the CSV `status`), or those files
  will look like real photos that match nothing.
- **`embed-errors.log` is regenerated from the index on every save**, so it
  always lists exactly the currently-failed files, and is deleted when there
  are none.
- One row per FILE, never per frame — a video's frame(s) collapse to one
  vector before being written, because the cluster-identity dedupe key (VS-1b)
  and every later stage operate at file granularity.
- `torch`/`open_clip` are imported lazily inside the script, never at import
  time elsewhere — `golden_replay.py` / `fresh_owner_smoke.py` /
  `preclassify_cases.py` must stay green with no ML deps installed at all.
- **Conversion dispatches on the manifest's FileType, never the filename
  suffix.** `qlmanage` resolves its Quick Look generator from the file
  EXTENSION, not content, and hangs 90s+ on a mismatch in either direction
  — found running VS-1's exit test on a real 4,819-file dump (4.2 hours
  instead of ~14 minutes, until fixed). A video-kind file whose extension
  isn't already `mov`/`mp4` gets copied to a corrected-extension temp path
  first — a symlink does NOT work here, `qlmanage` resolves through it to
  the real name.
- **Magic bytes overrule FileType (L17).** exiftool itself misreports some
  HEIC-named QuickTime movies as FileType HEIC — 216 of the reference
  dump's 3,836 HEIC-typed files (5.6%). Every *pending* file is sniffed with
  `file --mime-type`, exactly as D13 point 1 does at copy time, and its kind
  is corrected when the two disagree about image-vs-video. Three deliberate
  limits: only pending files are checked (a no-op resume must not pay for
  it — measured unchanged at 0.11s), a mime `file` doesn't recognize never
  overrides anything, and a disagreement that leaves the image/video kind
  unchanged is ignored, since kind is all the dispatch uses. Both directions
  are checked, not just image-typed rows — an image carrying a video
  FileType is the other half of the same mismatch and would go to qlmanage.

## Exit criteria (VS-1, from the Visual-Sorting-DESIGN doc) — MET

- Embeds a full done dump (the 4,819-file reference dump) in acceptable wall
  time: **16m08s** on MPS, from a real external drive. (An earlier run without the
  FileType-dispatch fix above took 4.2 hours on the same dump — same file
  count, same machine.)
- Resumable: re-running the finished reference index is a true no-op — no
  failed rows are left to retry, so the model never loads and the run only
  `stat()`s each file: **0.11s over 4,812 rows**, measured identical with
  and without the magic-byte check.
- **Coverage: 4,812/4,819 = 99.85%, 0 failed.** The 7 that never reach the
  index are not conversion failures and not sampling: 6 are AppleDouble
  `._` sidecars (exiftool `FileType: MacOS`, `skipped_ineligible`) and 1 is
  `IMG_4620.MOV`, which no longer exists on the drive (`skipped_missing`).
  Every file that exists and is media is embedded.
- **The old 95.4% L17 gap is closed.** 216/4,819 files —
  HEIC-named QuickTime movies that exiftool reports as FileType HEIC — used
  to be sent to `sips`, correctly refused, and recorded as failed. Magic
  bytes now overrule FileType (hard rule above): all 216 embed, verified
  both in isolation (216/216, fresh index) and in the full clean run
  (`magic_corrected: 216`, `failed: 0`). The check found exactly those 216
  across all 4,813 eligible files — no false overrides.
