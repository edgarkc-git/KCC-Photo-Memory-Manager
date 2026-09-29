# SKILL SPEC — Photo Manager Folder/Sub-folder Naming & Auto-Sort

Version: 0.3 — taxonomy sampling campaign complete; owner decisions D-A..D-G
recorded (D-F field priority, D-G scope). Supersedes 0.2-draft. **Signed off.**
Amended: monthly-bucket folders renamed `YYYYMM_` → `YYYYMM00_` (trailing `00`
= day field) so they sort inside the same month group as daily `YYYYMMDD_`
folders — resolves OA-6.

> **Bucket and type names below are written with the ENGLISH defaults.** They
> are not literals. Every displayed name — `Screenshots`, `To-be-checked`,
> `others`, `AI-images`, and every `[type]` — resolves from the owner pack's
> `language` at run time (`scripts/photo_profile.py`). The engine holds the
> ASCII class **ids**; the owner's pack holds the words.
>
> Place names, folder names and dates in the examples are **synthetic**.

---

## Status

**Signed off → Phase 2 (`photo-scan` build) started.** Nothing implemented
before sign-off; all drive access to date read-only. Copy-only policy in force
(D2): originals never moved/deleted.

---

## Naming grammar (final draft)

```
Single-day event:    YYYYMMDD_[where]_[type]
Multi-day trip:      YYYYMMDD-MMDD_[where1+where2...]_[type]   (end date in full MMDD; sub-folders by leg)
Recurring subject:   YYYY_MM-MM_[subject]                      (pets, recurring people)
Non-capture content: YYYY_[category]                           (subject-less AI output etc.)
Screenshots:         YYYYMM00_Screenshots                      (ONE folder per month — D7; 00-suffix later)
Orphan/misc:         YYYYMM00_others                           (ONE folder per month; since D7: PLACEHOLDER for human-attention items only — rule-classifiable content never lands here)
Trip-leg sub-folder: MMDD-MMDD_[where]                         (inside multi-day trip folders — D8)
```

**Field priority (D-F): [period] is #1, [where] is #2** — the date period
leads every folder name and is the primary grouping key; `[where]` second;
`[type]` third. When information is uncertain or space-limited, period and
where must be right; type may be omitted/flagged for review. (The full `MMDD`
end form also fixes the cross-month ambiguity the old `-DD` form had, e.g.
`20240429-0503`.)

**Language: always the owner pack's language, never a mix** — including
overseas place names, which are written in that language rather than left in
the local one.

**Monthly-bucket day field (resolves OA-6):** every one-folder-per-month
bucket (screenshots, others, to-be-checked, AI-images, and the pet folders)
uses `YYYYMM00_` — the trailing `00` fills the day field so the folder sorts
inside the same month group as daily `YYYYMMDD_` folders. Folders created
before this amendment keep their old `YYYYMM_` names unless renamed by hand.

Note: `[type]` is a proposed field — most existing hand-made folder names are
where-only.

## [type] taxonomy (final draft)

Class ids are the engine's; the displayed name comes from the pack.

| [type] id | Detection | Notes |
|---|---|---|
| `hiking` | GPS track on mountain trails + visual | dominant category in most existing names |
| `dining` | visual (restaurant/gathering) + venue GPS | the folder may carry the venue name (`<host>'s place hot-pot + karaoke` pattern) |
| `overseas_trip` | GPS outside the home country / airport day + trip date span | absorbs meals/wildlife/scenery within trip dates; sub-folders by leg |
| `day_trip` | single-day outing, non-mountain (museum, coast, family visit with a venue) | e.g. `20240503_Northgate-Museum_day_trip` |
| `cat` / `dog` | recurring-subject folder | `YYYY_MM-MM_<pet>`; subject beats origin (D-C); a pet-dominant home batch gets `type=cat`/`type=dog` plus a **city-level** `[where]` — city granularity does not violate the privacy rule, and the exact home coordinates still never surface |
| `screenshots` | **pure EXIF rule**: PNG + exact screen dims (the sizes the owner pack confirms) + no camera tags | 121/123 in the reference test dump; odd-dimension no-EXIF PNGs are saved images, NOT screenshots |
| `ai_images` | **pure EXIF rule**: no Make/Model + no EXIF date + no GPS | only subject-less AI output → `YYYY_AI...`; AI content with a clear subject stays with the subject (D-C) |
| `others` | fails the D-A significance test | one folder per month: `YYYYMM00_others` (D-E) |

**Origin flag (orthogonal to [type], D-B):** own capture (Make on the pack's
`own_camera_makes`) / shared-3rd-party (Make off that list, or a random
`XXXX9999` name — chat-app and AirDrop saves) / screen-record (video + no
camera tags + screen dims) / non-capture. Shared files sort into the same
destination as own captures but skip GPS clustering (date-only).

## Decisions log

- **D-A threshold**: count + significance — a recurring friend or occasion ⇒
  its own folder; an ordinary meal ⇒ others. Same/nearby location on the same
  date always groups into one folder (never split a day's co-located
  content). Ambiguous cases surface in `plan_batch-N.md` for approval (the
  existing gate).
- **D-B origin**: shared/3rd-party files → the same destination as own
  captures; date-only clustering.
- **D-C AI placement**: subject-ful AI stays with the subject; subject-less →
  `YYYY_AI...`.
- **D-D multi-activity days**: type by dominant cluster (≥80%); small tails
  ride along; split only when two clusters are both substantial. (Real
  examples from the campaign: a hike plus an errand, an errands-only day, and
  a day trip to a museum.)
- **D-E mixed stretches**: extract events, rest → monthly `YYYYMM00_others`.
  **Amended (D7 in the build plan): screenshots split out to monthly
  `YYYYMM00_Screenshots`; `YYYYMM00_others` holds ONLY items awaiting the
  owner's attention.**
- **D-F field priority**: `[period]` #1 (full `YYYYMMDD-MMDD` for multi-day),
  `[where]` #2, `[type]` #3 — see the naming grammar.
- **D-G pipeline scope**: work ONLY on the raw dump folders the collection
  declares in `collection.json`. Everything outside that list — older
  archives, other devices' exports — is out of scope until the owner says
  otherwise.
- (Earlier) merge-don't-duplicate into existing folders; copy-only (D2);
  state files in the workspace's `Working Files/`.

## [where] algorithm (replaces the zoom-18-only method)

**Hikes (`hiking`):**
1. Day-cluster GPS points from own captures; drop outliers >3 km from the
   median.
2. One Overpass query per cluster bbox (+500 m): `natural=peak/saddle` +
   named viewpoints + named trails (`highway=path/footway/track/steps`).
3. Rank peaks by #track-points within 400 m, then min distance; keep
   `min_d < 350 m`.
4. When peaks are missing or unnamed, extract mountain names from
   trail/viewpoint names (strip the trail-word suffixes in `TRAIL_SUFFIXES`
   and any parentheticals).
5. Concatenate the top 2–4 distinct names in first-touch order.

Test results over three hikes: one exact match via trail extraction (the
summit has no named OSM peak node); one partial — the algorithm returned the
three named peaks on the ridge but not the human editorial grouping name for
the whole traverse, and one peak is unnamed in OSM; one partial — one of the
two named peaks is missing from OSM entirely. **Known limitation: OSM name
gaps on minor local peaks. Mitigation: owners photograph summit signs —
`photo-classify` (the vision step) reads them to fill or confirm names. The
final name is human-confirmed at the plan-approval gate anyway.**

**Overseas trips (`overseas_trip`):** Nominatim reverse at **zoom 13** (city
level) per leg → city / airport style names, which is what hand-named folders
use. POI zoom 18 is rejected for naming (it returns trails and hotels, not
landmarks).

**Privacy rule (re-confirmed):** home and private GPS never surfaces as a
place name — no usable POI at home coordinates ⇒ fall back to subject naming.

**No-GPS fallback order:** (1) inherit the day-cluster location from
surrounding own-capture GPS; (2) carry over the existing folder name when
merging; (3) flag for manual naming in the plan. **Correction to v0.2:** the
overseas trip folder that was thought to have zero GPS actually has GPS on
332/374 files — the earlier finding sampled only shared/exported files.
GPS-less files are handled by D-B.

## Drive-structure findings (changes `photo-plan` assumptions)

- **Hand-named folders are mostly empty shells** — a naming skeleton the
  owner created and never filled. Of the hike folders sampled, only one held
  any files (36). Large trip folders show the same pattern.
- Real content sits in the raw monthly dumps under the source root, not in
  the hand-named folders.
- `photo-plan` treats an existing empty folder as a **name template to fill**;
  populated ones still need dedupe (filename+size, hash on collision).
- A partially hand-sorted trip folder (374 files, mostly one day of the trip)
  is normal — the rest of that trip is still in the monthly dumps.

## Scan-stage technical rules (validated)

- Dates: EXIF `DateTimeOriginal` → `CreateDate` (QuickTime) → `FileModifyDate`
  as a last resort (flag for review). Never trust Finder folder dates. Never
  use `-fast2`.
- Video GPS: read `Composite:GPSPosition` (it normalizes the EXIF-GPS group
  against QuickTime `Keys:GPSCoordinates` — both occur in phone MOVs).
- `.AAE` sidecars are **ignored entirely** (supersedes the earlier
  travel-with-pair rule): not counted, not classified, never copied — the
  media will not return to the phone; the owner deletes `.AAE` files manually
  once everything is allocated. (2,857 of them in the reference dump.)
- Video visual sampling: `qlmanage -t` thumbnails (no ffmpeg needed); videos
  inherit their cluster's `[type]`.
- Nominatim ~1 req/s + cache (`geocode-cache.json`); Overpass one query per
  day-cluster with retry/backoff (504s observed).

## Sub-folder rule (unchanged, still low confidence)

Multi-day trips get leg/location sub-folders; single-day folders stay flat;
non-photo utility folders (bookkeeping, receipts) are recognized and skipped.
Validate during Phase 4.

## Remaining open items (none block Phase 2)

1. Geocoding service: Nominatim + Overpass confirmed workable and free; a
   paid POI service is optional later if overseas coverage disappoints.
2. OSM name gaps on minor peaks: vision summit-sign reading in Phase 3; the
   plan-approval gate is the backstop.
3. Sub-folder rule confirmation: Phase 4.

---

## Evidence trail

- A 3-pass test run over the reference dump (batch table, dedupe discovery) —
  session transcript plus v0.2 of this SPEC.
- The taxonomy campaign, Sessions A+B — 6 folders sampled read-only, 13
  cluster rows, EXIF rules confirmed, the `[where]` algorithm tested on three
  hikes and one overseas trip. The full log lives in the workspace's
  `Working Files/type-sampling-worksheet.md`, not in this repo.
