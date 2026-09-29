---
name: photo-classify
description: >
  Stage 3 of the photo-manager pipeline (photo-scan -> photo-classify ->
  photo-plan -> photo-execute) — the ONLY stage that needs a vision model.
  For each pending batch in batches.json: sample images, LOOK at them, assign
  a [type] from the SPEC's taxonomy, generate [where] candidates (Overpass
  peaks+trails for local hikes, zoom-13 city for overseas), and record the
  result. Trigger when the owner asks to classify batches, assign types,
  name a hike/trip, or continue sorting after photo-scan (e.g. "classify
  batch 4", "what is this batch?").
---

# photo-classify — vision typing + [where] naming

Version: 0.1 (Phase 3 build)

## What it does

Turns each `pending` batch into a `classified` one: [type] assigned, [where]
candidates generated, routing notes recorded. Read-only on the drive; writes
only under the work dir (`classify/batch-NN/`, batches.json fields).

## Configuration

| | |
|---|---|
| Scripts | `scripts/photo_sample.py`, `scripts/photo_where.py`, `scripts/photo_classify_set.py` |
| [type] taxonomy | ⛔ **`--type` takes the owner's RESOLVED word, not the id below.** The engine's stable ids are `hiking`, `dining`, `overseas_trip`, `day_trip`, `cat`, `dog`, `home`, `screenshot`, `ai_generated`, `others` — but `photo_classify_set.py` validates against what those resolve to for THIS owner, which is language-dependent (`overseas_trip` resolves to `overseas-trip` in English and to a Chinese word for a Chinese pack). Never type an id. Run the command and it prints the exact list it will accept: `type must be one of: …`, and the owner pack's `naming_spec.types` overrides the lot |
| Home locations | read by `photo_where.py` from the owner pack's `home_locations` — nothing is passed by hand, and every entry is a never-name zone whether or not the owner has labelled it. `--anchor <lat,lon>` (`12.3456,98.7654` is an example only) ADDS one more anchor for a run with no pack; it never replaces the pack's |
| Requires | vision model (this skill only), Python 3 stdlib, and the preview libraries in the repo `.venv` (Pillow + pillow-heif + ffmpeg; or macOS sips + qlmanage with `PHOTO_PREVIEW_BACKEND=sips`) |

## Workflow (per batch, smallest first is fine)

1. **Sample + EXIF pre-classify**:
   `python3 scripts/photo_sample.py "<workdir>" --batch N --max-samples 12`
   Pure-EXIF rules already settle routing for `screenshot` / `screen_record`
   (tier T1) and `shared` vs `own` (D-B) — the vision step only looks at
   `own` captures. Check `preclass` counts. ⛔ These are ROUTING words, not
   `[type]` words: `preclassify()` answers `own`/`shared`, the tier answers
   `screenshot`/`screen_record`, and `AI-images` is a destination BUCKET.
   None of them is a valid `--type` argument.
   ⛔ **Exit 3 = NOT ONE sample could be made** (stderr names each cause and
   its count; `sample-report.json` is still written). There is nothing to
   look at: do NOT label this batch — fix the named cause and re-run. A
   partial failure exits 0 and lists each failed file with its `cause`.
2. **LOOK at every sample** in `classify/batch-NN/samples/` (vision). Assign
   ONE [type] by the dominant cluster (D-D: >=80% rules; small tails ride
   along, note where tails should route instead). Read summit signs / venue
   signage when present — that is the OSM-name-gap mitigation.
3. **[where] candidates**:
   `python3 scripts/photo_where.py "<workdir>" --batch N`
   Local legs -> Overpass peaks+trails ranking; overseas -> zoom-13 city
   names. Cross-check against what you saw in step 2; prefer the owner's
   naming style (their existing hand-named folders are the reference — D6).
   Never name home coordinates (privacy rule — the script reads the pack's
   `home_locations` itself and skips them; don't undo it, and don't re-add a
   day it marked `"mode": "home"` under a name of your own).
   ⛔ A day with `"mode": "moving"` carries its home evidence one level down,
   in `stops[].mode` — the DAY is not marked home even when it began or ended
   at one. Read every stop before naming such a day: a stop marked `"home"`
   must not be named from the photos either, however clearly they show the
   place. `"names": []` on a moving day means every stop was a home or too
   brief to name — it is an answer, not a gap for you to fill.
   A stop marked `"unnamed"` was counted deliberately (too few points to name
   from); it is not a failure and needs no name.
   A stop marked `"named"` sits at a place the owner named (`frequent_places`
   in `photo-entities.json`): its name is the owner's own word, so use it as
   written. It never appears on a home stop.
4. **Record**:
   `python3 scripts/photo_classify_set.py "<workdir>" --batch N --type X --where Y --note "..."`
   Never hand-edit batches.json. Notes carry routing decisions (stray files
   to their real event folder, pets to the recurring-pet folder, tails to the
   monthly `others` bucket) — photo-plan consumes them. All notes, labels and
   names are written in the owner pack's language, and only that language.
5. **No-date sweep** (once per source folder):
   `python3 scripts/photo_sample.py "<workdir>" --no-date`
   pre-classifies `no-date-files.csv` (the AI-image rule etc.). These files
   are NEVER auto-sorted — they go to the plan for manual review.
6. **Present** the classified batch table to the owner before moving to
   photo-plan.

## Rules

- Only `own` captures drive GPS naming; `shared` files (other cameras,
  chat-app saves) sort with the same destination but by date only (D-B).
- AI content with a clear subject stays with the subject (D-C); the
  AI-image EXIF rule cannot tell AI output from stripped web-saves —
  spot-check visually before the plan stage.
- Folder-name proposals follow the SPEC's grammar; [period] #1, [where] #2,
  [type] #3 (D-F), in the pack's language only.
- A pet-dominant batch shot at home is `type=cat`/`type=dog` with a
  CITY-level [where], not `others` — the destination stays the recurring pet
  folder, and the exact home coordinates are still never named.
- A video's sample is one frame from its MIDDLE (ffmpeg; qlmanage only with
  `PHOTO_PREVIEW_BACKEND=sips`); QuickTime dates are UTC while photo
  EXIF is local — do not trust cross-media time ordering inside a day.

## Validation baseline

Recorded per validated dump, not restated here. A replay must reproduce, for
each of its reference batches: the assigned [type], the ranked [where]
candidates the Overpass pass returned, the routing notes for stray files and
tails, and the no-date sweep's hit rate against the AI-image EXIF rule. The
shape of a baseline entry:

```
B1  0427-0501 (147 files)  hiking
    where -> <peak>/<rock>/<ridge>, matching the owner's existing folder style
    04-27 stray routed to the 20240427_<event> shell
    vision confirmed: ropes, ridge line, coastal colour boundary
B3  0503-0505 (37 files)   day-trip, <venue> (wall sign read by vision —
    the SPEC's D-D example); 05-04/05 tails -> 20240100_others
no-date sweep: 79/79 hit the AI-image EXIF rule
```
