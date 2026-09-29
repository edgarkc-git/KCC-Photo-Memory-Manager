---
name: photo-recurrence
description: >
  VS-1b of the photo-manager v2 Visual Sorting module. Runs the recurrence
  census (photo_recurrence.py) over a whole collection's VS-1 embedding
  indexes: scores every visual cluster on mass / spread / persistence /
  place-boundness, infers (and suppresses) residences, and writes ranked
  `ai-drafted` candidates for photo-proposals.md with a blast radius each.
  Drafts everything, names nothing. Trigger when the owner asks what keeps
  coming back in a collection, for a cold-start memory draft, for the
  recurrence census, or before a Phase C bootstrap ("run the census",
  "which subjects recur").
---

# photo-recurrence — recurrence census (VS-1b)

Version: 0.1 (VS-1b build)

## What it does

Answers one question over a whole collection: **what keeps coming back?**
Recurrence *is* the definition of "matters to this owner" — nobody configures
importance (Visual-Sorting DESIGN §2).

It reads the VS-1 indexes (`photo_embed.py`) plus each work dir's
`manifest.csv`, clusters the vectors, scores each cluster on four axes, and
writes ranked draft candidates. It is the hard prerequisite for Phase C's
memory bootstrap: EXIF statistics cannot produce "something appears heavily
across seven months at one home" — that is a *visual* claim.

No vision-model call happens here, and no pack is loaded. Runs on any text
model.

| Axis | What it measures |
|---|---|
| mass | how many files |
| spread | distinct days / distinct months |
| persistence | first-seen → last-seen span, and any drop-off |
| place-boundness | share of its GPS members sitting on one area |

**Blast radius** = the candidate's own members + the leftover files nearest
it (in no candidate and in no substantial cluster of their own, within
`tau − 0.05`). That is how many files a human answer would relabel, and it is
the ranking key (V2-7).

## Configuration

| | |
|---|---|
| Script | `scripts/photo_recurrence.py` |
| Env | the repo `.venv` — **numpy only**, no torch (the census loads no model) |
| Input | two or more work dirs, each with `embed/` (VS-1) and `manifest.csv` |
| Output | `<out>/recurrence-census.json` + `<out>/photo-proposals-draft.md` |
| Default `<out>` | `<parent of the first work dir>/recurrence` |
| Tests | `./.venv/bin/python3 tests/photo_recurrence_cases.py` (15 cases) |

On Windows the interpreter is `.venv\Scripts\python.exe` wherever this says `./.venv/bin/python3`.

## Workflow

    ./.venv/bin/python3 scripts/photo_recurrence.py \
        "<Working Files>/202401" "<Working Files>/202402" ... --force

Deterministic and fast — 1.5 s over 9,906 files — so there is nothing to
resume. It refuses to overwrite an existing census without `--force`;
`--force` **carries the previous census forward** (ids and `obs_count`),
`--force --reset` discards it.

Candidate kinds, all cold-derived and all unnamed:

| Kind | Meaning |
|---|---|
| `residence_area` | a GPS area that behaves like a home (see below) |
| `residence_bound_pattern` | recurs at exactly one residence — a subject that lives there **or** a view/habit (the sunset/night-view class). The census does not claim which: that needs VS-2 |
| `place_bound_pattern` | recurs at one non-residence area |
| `recurring_subject_or_scene` | recurs but travels — not tied to one place |
| `bulk_no_camera_class` | look-alike files with no camera EXIF (screenshots, forwarded, saved) |

## Hard rules

- **It drafts anything; it names nothing (V2-6).** Every candidate is
  `ai-drafted` / `ai-reinforced`, `noticed_by: agent`, never `confirmed_by`.
  Labels are descriptions and opaque area ids, never a name.
- **Pack-blind by construction.** The census runs *before* a pack exists, so
  it must never resolve one. `tests/photo_recurrence_cases.py` monkeypatches
  `photo_profile.resolve_pack` / `load_profile` / `get` to raise and fails the
  build if the census ever calls them. Clear `PHOTO_PROFILE` for a real run.
- **A residence is inferred only so it can be suppressed.** An area
  photographed on ≥ 8 distinct days across ≥ 3 months with ≥ 25% of it after
  dark is treated as a home or regular base. It gets an opaque `residence-A`
  id, **no coordinates anywhere**, and any area within 5 km of it is folded
  into it rather than published separately — a 1.6 km fragment of somebody's
  home is still their home. Absorbed areas are re-stated into the home's own
  axes (or it under-reports the days and nights it is ranked on), but the
  residence flag is never revisited: absorbing fragments can dilute
  `night_share` below the threshold, and un-flagging a home afterwards would
  publish its coordinates. An inferred residence is never reverse-geocoded.
- **The markdown draft carries no coordinates and no directory names.** Folder
  names in a sorted collection *are* place names (for example
  `202512_Lakeside_cat_resort`), so the draft emits file basenames only. `scrub()` re-checks the rendered markdown
  against every source directory component and every area coordinate, and
  raises rather than shipping. Full paths and 1-decimal (~11 km, city-level)
  coordinates for **non-residence** areas live in the machine JSON only.
- **Cluster identity is the dedupe key.** A candidate re-observed later bumps
  `obs_count` and re-tags `ai-reinforced` instead of forking a second draft.
  Two mechanisms: the id is the sha256 of the sorted sha256s of its exemplars
  (stable while the core is stable, independent of run order), and a new
  candidate whose centroid is within 0.85 of a previous census's candidate
  **inherits that id** even if it grew.
- **The `kind` column of `embeddings.csv` is never read.** A reclaimed row can
  carry the manifest's uncorrected kind (known VS-1 defect: the sha256 reclaim
  path runs before the magic-byte check). The vector is right, the column can
  lie — so the census takes no image/video split at all and derives everything
  else from `manifest.csv`.
- **Failed rows are excluded twice over** — `status == "embedded"` *and*
  `‖v‖ > 0.5`. A failed file is an all-zero vector at the same row index; a
  zero vector has no cosine and would silently poison one cluster.
- **The same content in two dumps is counted once** (sha256). Raw dumps are
  separate collections for copying, but a census that counted one photo twice
  would report a recurrence that never happened.
- **Two models' indexes are never mixed** — the model identity of every source
  index must match, or the run hard-fails, exactly as `photo_embed.py` does.

## The clustering threshold

Greedy leader clustering on unit-norm vectors (cosine = dot product), points
ordered by neighbour count within `tau` and tie-broken by sha256, each
unassigned point claiming every unassigned point within `tau`. Density order,
not arrival order — so the result does not depend on which work dirs were
listed first. No refinement pass: the invariant "every member is within `tau`
of its leader" is what makes a cluster defensible as one thing.

`tau = 0.80`, derived from a real 7-dump index (9,915 embedded files over
seven months), not guessed:

| tau | clusters | largest | singletons | ≥3 months | ≥3mo & mass ≥10 |
|---|---|---|---|---|---|
| 0.75 | 1817 | 751 (7.6%) | 902 | 86 | 55 |
| **0.80** | **2764** | **539 (5.4%)** | **1541** | **68** | **34** |
| 0.85 | 4003 | 342 (3.4%) | 2424 | 40 | 23 |
| 0.90 | 5729 | 107 (1.1%) | 4060 | 17 | 5 |

0.90 destroys recurrence (5 usable multi-month clusters in 9,915 files); 0.75
holds together but its clusters start mixing visibly different content. 0.80
keeps the largest cluster at 5.4% — one 5-day landscape burst, not a
mega-cluster — while the top multi-month cluster is 215 files over 61 days and
7 months. Reproduce the sweep by re-running with `--tau` and reading
`coverage.clusters` plus the candidate axes.

## Not in this stage

The **zero-shot class axis** (interests / not_important / digital-trash) needs
VS-2's scene label set, which does not exist yet. The census reports
`zero_shot_class_distribution: null` with the reason rather than guessing, and
offers `bulk_no_camera_class` — the one bulk signal the index plus
`manifest.csv` can honestly support — marked as the cold proxy it is.

`--index-root` (the global index over a sorted tree) is not accepted as a
source: that index has no exiftool pass, so it carries no capture date and no
GPS, and three of the four axes need both. Point the census at work dirs.

## Exit criteria (VS-1b, from the Visual-Sorting-DESIGN doc)

Real run over one owner's raw dumps, **pack hidden** (`PHOTO_PROFILE`
cleared; the census cannot read a pack at all): 7 consecutive monthly dumps,
9,906 files after sha256 dedupe, a seven-month capture window, 2,764
clusters, 221 GPS areas, 50 candidates, **1.5 s**.

- **Homes** — 2 residences inferred and suppressed. `residence-A`: 517 files,
  95 distinct days across 7 months, 50% after dark → rank 1 by blast radius.
  `residence-B`: 182 files, 13 days, 4 months, 24% after dark → rank 3.
- **Recurring subject** — rank 2: 215 files, 61 distinct days, 7 months,
  74% place-bound, appearing at *both* residences → a subject that travels
  between homes, correctly not called a place pattern.
- **The sunset/night-view class** — `rc-8dea6aa0bfea`, 18 files, 4 days over
  2 months,
  100% bound to `residence-A`, "mostly late afternoon", ranked 45 of 50 (it
  is genuinely small). Verified by eye to be sunset views from the residence.
- **Drop-off** — 4 candidates carry one. ⚠️ The available window is seven
  months, so any known long-horizon timeline (a home change years earlier, a
  pet that stopped appearing) is *structurally* outside it. This criterion is
  only partly testable until older dumps are embedded.
- **Names** — zero. Every label is a kind, a description or an opaque area id.
