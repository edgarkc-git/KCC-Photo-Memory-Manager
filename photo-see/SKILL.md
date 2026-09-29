---
name: photo-see
description: >
  VS-2 of the photo-manager v2 Visual Sorting module. The see controller
  (photo_see.py): scene zero-shot classification, in-batch visual clustering,
  and a priority-filled ladder that picks the handful of files an Opus-class
  vision model actually has to look at, at a configurable see-rate. Supersedes
  photo_sample.py's random-stratified sampling. Trigger when preparing a batch
  for classify, when asked which files the model should see, to raise or lower
  the see-rate, or to check the fabrication guard ("pick the samples",
  "see controller", "which files should the model see", "10% seeing").

  ALSO the home of subject naming (`--memorize`, the VS-4 loop): recognising a
  recurring subject — a pet, an animal that keeps appearing — across a whole
  collection, asking the owner what it is called, remembering that name in the
  owner pack, and putting it into folder names as the `[who]` slot. Trigger for
  that too ("name my pets", "recognise my cat", "remember this animal",
  "who is in these photos", "name the subjects", "subject identity",
  "why are my pets not named"). The registry those names live in is inspected
  and repaired with `photo_subjects.py review` — see photo-run/SKILL.md.
---

# photo-see — the see controller (VS-2)

Version: 0.2 (VS-2 + F2/B1 rung-1 quota, N-4 naming carve-out, F7/F10/F12 fixes)

## What it does

Answers one question per batch: **of these N files, which handful needs
eyes?** Everything else takes its label from the VS-1 embedding index — a
high-confidence zero-shot scene match, or propagation from the representative
of its own visual cluster — so a confident CLIP match costs no vision call.
(It does not yet shrink the BUDGET, though: see *Measured*.)

It replaces `photo_sample.py`'s per-day `spread()` sampling. The frozen
Claude-Skills v1 copy keeps the old sampler.

`<repo>` is the folder holding `scripts/` and `.venv/`; `photo_run.py status`
prints these lines with it filled in.
On Windows the interpreter is `<repo>\.venv\Scripts\python.exe` wherever these lines say `<repo>/.venv/bin/python3`.

```bash
<repo>/.venv/bin/python3 <repo>/scripts/photo_embed.py "<workdir>" --scene-labels   # once
<repo>/.venv/bin/python3 <repo>/scripts/photo_see.py   "<workdir>" --batch 1
#   -> classify/batch-01/see-report.json + samples/
#   ⛔ exit 3 = NOT ONE selected file got a viewable sample (causes on stderr and in
#      sample_failures_by_cause). Nothing to look at: do NOT write decisions for
#      this batch; fix the cause and re-run with --force. Some failed = exit 0.
# agent looks at samples/, writes {selected[].path: label} into decisions.json
<repo>/.venv/bin/python3 <repo>/scripts/photo_see.py "<workdir>" --batch 1 --apply decisions.json
#   -> classify/batch-01/see-labels.json, validated
<repo>/.venv/bin/python3 <repo>/scripts/photo_see.py "<workdir>" --batch 1 \
    --apply decisions.json --memorize            # VS-4, needs an owner pack
```

⛔ **The decision key is `see-report.json`'s `selected[].path`, copied
verbatim — NEVER derived from the sample's filename.** A sample name is built
twice over: `make_samples` prefixes the capture time and then gives the file
whichever extension the converter actually produced — `.jpg` for every still
it converts (a `.HEIC` or `.PNG` source included), `.png` for a video's
thumbnail. So `IMG_1234.MP4` is sampled as `2026-05-03_0900_IMG_1234.png`, and
there is no route back from that name to the source path for any file type.
Read `selected[]`, and take `path` and `sample` from the SAME entry: `sample`
says which picture to look at, `path` is what you key the decision on.

⛔ `--apply` **refuses** a key that is not on the see-list rather than guessing
which file you meant. If it names a key it recognises as a sample name, it
tells you the correct `path` — use that, do not rename the sample.

`--see-rate 0.15 --reason "no-GPS batch"` raises it per run; `--pass
second_sort` uses the 5% re-sort rate; `--tau`, `--profile`,
`--no-thumbnails`, `--validate`, `--force` behave as everywhere else in the
engine.

## What a `label` should say — the `[what]` vocabulary (R6, N-2, N-4)

A decision's `label` becomes the folder name's **`[what]`** slot. Write it as
**keywords or a short phrase**:

    hiking · sunset · scenery · coffee time · meals · dinner
    play in grass · play in beach · enjoy sunshine by the window

⭐ **Those are illustrations, not a vocabulary.** The engine ships no `[what]`
words in any language. What the OWNER has confirmed is in the see report under
`what_reference` (from the pack, `photo-entities.json` → `scenes`) — read it to
match their phrasing. ⛔ It is a **REFERENCE, never a BOUNDARY** (D-F11): a
phrase that is not in it is equally valid, nothing validates a label against
it, and an empty list is the correct state for an owner who has confirmed none
yet. Write in the owner's language.

⛔ **This is NOT the 11-word `[type]` taxonomy.** That is a different field,
decided per batch, and `photo_classify_set.py --type` deliberately carries no
`choices=`. A label reading only `Cat` or `Hiking` is a class word: it is a
legal label and a poor one, because it tells a reader of the folder name
nothing the `[type]` field did not already say. In the last user test every
label was a class word and every folder was named for the species.

Keep it inside the **N-2 budget**: `{20}` units hard, `{16}` soft (D-F13), and the
count covers **`[who]` + `[what]` only** — `[period]` and `[where]` are fixed
cost and are never charged. Full-width script counts per CHARACTER, narrow
script per WORD (`play in Central park` = 4), and the separators `_` and `+`
consume nothing. `photo_name.budget_units()` is the one implementation of
that rule; the numbers come from the owner pack
(`naming_spec.name_budget`), never from the constants.

⛔ **N-4, as amended by D-F10 — where a folder's `[what]` may come from.** A
`viewed-image:` phrase may name a folder, and so may a `clip-propagated:` label
that inherited that phrase from a file somebody opened: your one look labels
its whole visual cluster, and that is the point of the stage. What may **not**
name a folder is a `clip-matched:` label — the zero-shot classifier's own
output, drawn from the pack's closed class vocabulary — or a
`clip-propagated:` label that inherited *that* rather than a phrase. Both are
useful on a file; neither says anything the `[type]` field did not, which is
why excluding them is what keeps `[what]` out of the taxonomy.

⛔ **`[who]` is NOT amended and stays `viewed-image:` only.** Naming an
individual on a propagated guess is how identities get corrupted. The stage
guarantees a folder-forming cluster gets a viewed representative (the N-4
carve-out, below), so this costs no folder its name.

## `--memorize` — the VS-4 loop (needs an owner pack; no-op without one)

⭐ **What it does on a dump with an index:** it records what the look saw as
draft observations — no exemplar and no name (measured on a real 58-batch dump:
0 exemplars, draft observations only). The owner names those drafts on the
batch pages, and the agent names a confirmed pet on other photos through
`photo_index.py identify` (see `photo-run/SKILL.md` step 3).

A decision may be an object instead of a bare label, and then it says
something about WHO as well as WHAT:

```json
{"/raw/IMG_0042.HEIC": {"label": "Cat", "subject_kind": "cat"},
 "/raw/IMG_0107.HEIC": {"label": "Two cats on a sofa",
                        "subjects": [{"subject_kind": "cat"},
                                     {"subject_kind": "cat"}]}}
```

**`subjects` is a LIST — one entry per animal in the frame (R4).** A frame
holding two animals is **two names to log, never a frame to refuse** (owner
decision, 20260904), and the folder it names carries both. Each entry takes
`subject_kind`, and the order is the one the folder name renders in.

⛔ **A decision never names a pet (G7).** A `subject_id` in a decision —
singular or in `subjects` — is REFUSED at `--apply` and nothing is written:
measured on a real dump, it put a pet's name on a street cat, named the folder
and trained the pet's exemplars, with no recognition and no record. A pet's
name reaches a label only through the owner's pages or `photo_index.py
identify` (see photo-run: recognition proposes, you view and agree, the view
is recorded, nothing is learned).

The singular `subject_kind` still works and means a one-entry list. ⛔ A decision carrying `subjects` **and** a singular key is refused, not
merged — those are two statements about who is in the frame and the stage
will not choose between them.

**How to know a second animal is there, and what to call the first:** the
see-report's `selected` rows now carry two fields written for this decision
and for nothing else.

* `detections` — `{"count": 2, "kinds": ["cat", "cat"]}`, from the identity
  index. `count: 0` means the detector looked and found no animal; `null`
  (either the whole field or the count) means nothing counted this frame, and
  it is **not** the same answer.
* `subject_match` — the subject the registry already accepts for this file,
  with its `subject_id`, score and space. ⛔ **Evidence, never a decision** —
  and never copied into a decision. An accept that wrote itself onto a label
  would be A19 — 24 sightings absorbed onto a confirmed subject with nothing
  asked, 5 of them wrong — moved one stage earlier, where it names folders.

⛔ **A frame holding two animals banks NO exemplar in any space**, whether the
owner names one of them or both on a page (G6-6 G1): the exemplar store keys
on the file's content sha — one photograph, one key, one subject — so the
vector would carry both animals (D-24).

* `subject_kind` — the model saw a subject it could not identify. The file's
  visual cluster centroid goes to the DRAFT store, which bumps an existing
  draft's `obs_count`, opens a new one, or — when it matches a subject the
  owner has already confirmed — records the sighting there and opens nothing
  (F14: no second record, no repeat question, and no merge either). Drafts
  never gain exemplars, and the next confirm checkpoint asks a human for `who`
  + `name` once, not once per batch.

Each draft observation also records the LOOKS behind it — the selected files,
their thumbnails and the provenance the labels file applied. `photo_memory.py
confirm` promotes those through the same gates once a human names the subject,
which is what keeps the subject recognisable on the next dump.

Every attempt lands in `photo-subjects/memorize-audit.jsonl`, refusals
included. The drafts are mirrored into the pack's `photo-proposals.md`.

## The ladder

| Rung | What | State |
|---|---|---|
| 1 | one representative per in-batch visual cluster | live, biggest clusters first, **capped at `RUNG1_BUDGET_SHARE`** |
| 2 | all gray-zone subject matches | live — reads the **VS-3** subject registry |
| 3 | embedding outliers | live — reachable since the cap (F2/B1) |
| 4 | files with no subject and no scene signal | live — reads the **VS-3** subject registry |
| 5 | farthest-point diversity fill | live, spends what rungs 1/3 leave |

Rungs 2 and 4 read the subject registry (`photo-subjects/` in the owner pack,
VS-3) and nothing else. A run whose pack holds no subjects gets an empty
registry and both return nothing — the same ladder this stage ran before VS-3,
which is the correct answer and not a fallback: rung 4 is a conjunction, and
with no registry "this file has no subject" is *unknown*, not false. Asserting
it would be the same class of move as a `clip-*` label claiming
`viewed-image:`. The scene half stays published as
`diagnostics.no_scene_signal` and steers nothing on its own.

`gray_zone_always_seen: false` switches rung 2 off. `true` means "always seen,
budget permitting" — gray picks are spent inside the budget, not floored like
the carve-out, because the gray zone is unbounded and one badly-set threshold
must not be able to spend arbitrary vision budget. A starved rung 2 shows in
the ladder trace.

**Rung 1 used to eat the whole budget on almost every real batch.** Measured
over 6 done dumps, 77 batches with a non-empty see pool: rung 1 took 785
picks, rung 5 took 28, rung 3 took **0**; rung 1 was starved (more clusters
than budget) in 48 of the 77. Rung 1's demand is *number of clusters*, which
grows with the data, while the budget is a fixed percentage of the pool — so
a strict priority fill degenerates to "the medoids of the N biggest clusters".

**`RUNG1_BUDGET_SHARE` (F2 / option B1, signed 2026-08-07) caps rung 1's
ordinary picks at a share of the budget** and reserves the rest for rungs 3
and 5. The value is **0.85**, swept 0.30–1.00 on the `2023` benchmark replay
with the carve-out below in place. ⚠️ Read it as a *policy choice with a
measured floor*, not a tuned optimum: the sweep found the parameter flat
(minority-row reproduction moved only 68–77 of 126 across the whole range, and
non-monotonically), cost identical at every share, and the replay structurally
cannot score what the quota is for — its coverage metric is rung 1's own
objective, and its oracle treats each shipped decision as truth, so a rung-3/5
look that *corrects* a shipped label can never register as a win. Settling
that needs a run where the vision model is really called.

**Naming carve-out (N-4, signed 2026-08-08).** A cluster that becomes its own
output folder keeps its rung-1 look *unconditionally, outside the quota* —
N-4 requires every name phrase to rest on a `viewed-image:` source, and rung 1
is what supplies one, so a cap alone would starve exactly the clusters that
become folders. Where the folder name carries `[who]`, the guaranteed pick is
the medoid of the files **containing that subject**, not the cluster medoid.
`folder_bound_clusters()` is the input, and the **pack registry is its only
source** — a cluster is folder-bound when it holds an `accept`-level match to
a subject that forms its own folder (a confirmed name plus a declared `active`
start, which under N-10a is exactly the recurring-subject / D9 class). Reading
the recurrence census's centroids instead would put a collection-level file
dependency inside a batch-level stage, and that is not built. Guaranteed picks are a **floor on the budget**, not
an overflow of it, and the count is reported as
`config.naming_carve_out.guaranteed_folder_picks`.

**Rung 3's candidate set is a SUBSET of the singleton clusters** — not
"exactly the singletons" as this file previously said (F7). A member of a
multi-member cluster sits within tau of its leader and therefore ~0.83 from
its own centroid, above `OUTLIER_MAX_SIM = 0.70`; but a singleton near a big
cluster's centroid also scores above it and is no candidate (0 of 12 on the
one real batch the review measured). The load-bearing reason rung 3 fired 0
times was budget exhaustion by rung 1, and the cap removes it:
`case_rung3_fires_once_rung1_is_capped` asserts both — 0 picks at
`rung1_share=1.0` (the old ladder, reproduced exactly), non-zero at the
shipped share.

## Provenance

`viewed-image:` (the model looked) · `clip-matched:` (confident zero-shot, not
seen) · `clip-propagated:` (inherited from a cluster representative).
`--apply` stamps `viewed-image:` only for a file on the see-list **whose
thumbnail is on disk**; `assert_no_fabrication()` is the mechanical check and
`tests/photo_see_cases.py` fails the build if it stops holding (2026-07-20).

`draft:` is the fourth prefix and it is a MEMORY prefix, not a visual one — it
composes in front of a visual one in the plan CSV (`draft:clip-matched:`) to
say "nobody looked, and the subject this name rests on is unconfirmed too".
`draft:viewed-image:` is a legal plan cell and is never valid memorize
evidence.

**Hardened at VS-4.** `is_file()` on the thumbnail was the whole test, and it
passes for an empty file, a text file with a `.jpg` name, a symlink pointing
anywhere, a `../` escape, and one thumbnail reused as evidence for a whole
batch. `photo_evidence.py` now holds the rules — selected, recorded for THIS
file, bare filename, inside `samples/`, regular file, non-empty, image magic
bytes, not shared — and the memorize loop and `photo_classify_validate.py`
apply the same ones, because a look good enough to label a file is a look good
enough to become a permanent exemplar.

## The screenshot class is a SECOND detector and moves nothing

`preclassify()`'s ONB-12 filename rule and the screen-dimension rule stay
exactly as they are, and the files they decide never enter the see pool. The
zero-shot `screenshots` class is the complement for what they miss (Samsung
JPEG screenshots, the Group 6 lesson). It produces a FLAG in
`diagnostics.screenshot_suspects`, never a route.

⚠️ **Unvalidated on available data.** Across the 6 embedded dumps the EXIF
rules already caught 355 of 356 shipped screenshots, so the second detector
had essentially nothing to find, and the 4 files it did flag with confidence
were all false positives. `group3` (the Samsung dump) is a golden fixture
with no image bytes, so the case this class exists for cannot be replayed
here yet.

## Labels are owner data (ONB-10)

`visual_sorting.scene_labels` in the pack wins; the engine fallback is the
DESIGN's 11 classes and stays deliberately narrow. Its class KEYS are stable
ASCII ids; the displayed name resolves at call time — `screenshots` through
`photo_profile.buckets()`, the other named classes through
`photo_profile.scene_classes()` — so an English-language owner gets
`Screenshots` (ONB-9) and a run with no pack keeps emitting exactly what it
emitted before the ids existed. **Prompts stay English** —
`ViT-B-32/laion2b_s34b_b79k` is an English-text CLIP and a non-English prompt
scores noise.

The text tower runs once, in `photo_embed.py --scene-labels`, so `photo_see`
stays numpy-only like `photo_recurrence.py`. The label file carries the same
model identity as the image index and is refused when the two disagree.

⚠️ **A bound owner with no pack is now a hard exit** (VS-3). The subject
registry is a directory *inside* the pack, so this stage resolves the whole
pack (`photo_profile.resolve_pack()`) where it used to take the profile dict
alone (`load_profile()`). A missing profile was never an error there — the
engine simply used generic defaults. `resolve_pack()` refuses instead: if
`collection.json` names an owner and no pack exists at that path, the run
stops rather than silently sorting one person's photos with nobody's memory.
`photo_execute.py` made the same move for the same reason. An **unbound**
collection is unaffected and still runs on engine defaults — that is what
every benchmark run does.

## Measured — 6 done dumps, oracle-substituted vision

`tests/see_replay.py` — see its docstring for the method and its caveats.
At 10%, equal budget in both arms, oracle labels, identical propagation:

Dumps are six consecutive monthly dumps from one owner's collection, listed
oldest first and referred to here as A–F.

| dump | see cover / acc | sampler cover / acc | minority rows: see vs sampler |
|---|---|---|---|
| A | 78.5% / 97.6% | 62.1% / 97.2% | 53.3% @ 100% vs 48.9% @ 81.8% |
| B | 71.8% / 100% | 55.1% / 100% | 2 rows, neither reached |
| C | 65.1% / 99.3% | 47.6% / 99.3% | 52.1% @ 92.0% vs 37.5% @ 91.7% |
| D | 73.7% / 100% | 55.1% / 100% | 100% @ 100% vs 50% @ 100% |
| E | 89.3% / 100% | 67.7% / 100% | 84.6% @ 100% vs 100% @ 100% |
| F | 64.0% / 100% | 54.9% / 100% | 3 rows, neither reached |

⚠️ **This table was measured with the pre-quota ladder** (`rung1_share` = 1.0
in today's code). Re-measured after F2/B1 on the two dumps whose indexes were
still available, same budgets, same oracle: dump F coverage 64.0% → **58.1%**
with minority coverage 0% → **33.3% @ 100% accuracy**; dump D coverage 73.7% →
**68.0%**, minority unchanged at 100% @ 100%. Seen-image count is unchanged
(457 over the pair), so the trade is bulk propagation coverage for
minority-row reach at **zero token cost** — which is what the quota is for.
The full 6-dump table is not re-measurable without the other four indexes, and
the numbers to calibrate against are the `2023` benchmark's, not these.

- **Coverage is the win, and it is partly mechanical**: +9 to +22 points at
  identical budget — but the ladder picks cluster medoids and is then scored
  on a rule that fills clusters from their medoid, so it selects the files
  that maximize its own propagation. Read it as "the mechanism works", not as
  independent validation. The informative half is that **accuracy is a wash**:
  visual clusters at tau 0.80 are 97.6–100% label-pure against the shipped
  decisions, which is what makes propagating from one look safe at all.
- **Token cost is about the same, not lower.** 813 images vs the old sampler's
  own formula at 963 (−15.6% over 6 dumps; −10.6% over the dump D + dump F
  pair alone — the figure moves with the dump set). Against what the 2026-07 runs
  *actually* showed Opus (426 images) it is +90.8%, but those runs were
  hand-reduced with `--max-samples` and lost 135 thumbnails to conversion
  failures VS-1 later fixed.
  ⚠️ **The DESIGN's saving mechanism is not in these numbers.** "High-
  confidence CLIP matches consume zero vision budget" is true of the labels
  but not of the budget: `budget_for()` is computed from pool size before any
  zero-shot confidence is consulted, so a batch that is 90% clip-matched
  still gets a full 10% budget. Making the budget shrink with confident
  coverage is the obvious next lever and was **not** built — it is not in
  VS-2's scope line and it changes how much a run sees.
- **The number that should worry you**: predicting each batch's most common
  shipped class — no seeing at all — reproduces 88.8–99.9% of the per-file
  decisions. Per-file reproduction is a weak bar on this data.
- **Zero-shot quality** against the shipped taxonomy, confident predictions
  only: `hiking` 82.5% precision (n=388), `dining` 92.9% (14), `cat` 72.5%
  (436), `dog` 38.2% (34), **`day_trip` 7.9% (329)**. Overall exact match
  47.5%. `day_trip` vs `overseas_trip` is a WHERE question, not a scene
  question, and the numbers say so. `clip-matched` is therefore OFF by
  default in the replay.

## Open questions for the owner

1. ~~**Rung 3 can never fire, and rung 5 nearly never.**~~ **Closed** — the
   owner chose the reserved per-rung quota (F2 / option B1) on 2026-08-07 and
   it is built, together with the N-4 naming carve-out. The **calibration** of
   `RUNG1_BUDGET_SHARE` was taken on the `2023` benchmark replay with the
   carve-out live and the value set to 0.85 — but the sweep found the
   parameter flat and the replay unable to score the quota's actual purpose,
   so what remains open is a **real vision-model run** to settle F2/B1.
2. **Should the budget shrink when the batch is confidently clip-matched?**
   Today it does not, so the predicted token saving does not materialize.
3. **`day_trip` / `overseas_trip` in the label set.** Not visually decidable. Keep
   them (and read them as scene evidence only), or drop them from the set?
4. ~~**`AI-image-suspect` vs the unbuilt G-3 `ai_gen` rename.**~~ **Closed**
   by G-3: `preclassify()`'s class is now `no_exif`, named for the evidence
   it actually has. The two names no longer overlap — one is an EXIF verdict,
   the other a visual one.
