#!/usr/bin/env python3
"""VS-2 — the see controller: which files the vision model actually looks at.

Supersedes `photo_sample.py`'s random-stratified sampling. Reads the VS-1
embedding index plus manifest.csv/batches.json and answers one question per
batch: **of these N files, which handful does an Opus-class model need to
open its eyes on?** Everything else gets its label from the index — either a
high-confidence zero-shot scene match or propagation from the representative
of its own visual cluster, so a confident CLIP match costs no vision call
(Visual-Sorting DESIGN §4). Note what that does NOT yet do: `budget_for()`
reads the pool size before any zero-shot confidence is consulted, so a batch
that is 90% clip-matched still gets a full 10% budget. Measured token cost
against the old sampler's own formula is -10% to -16%, not the step change
the DESIGN's wording implies — photo-see/SKILL.md carries the numbers.

Three things happen here, in this order:

  1. scene zero-shot   every embedded file scored against the label set
  2. in-batch clustering  greedy leader over the same vectors, tau below
  3. the see controller   a priority-filled ladder, never random

Writes into the work dir only, refusing to overwrite without --force:
  classify/batch-NN/see-report.json   the selection, its ladder trace, the
                                      zero-shot scores, the clusters
  classify/batch-NN/samples/          downscaled viewables for the picks
  classify/batch-NN/see-labels.json   written by --apply: the per-file label,
                                      its provenance prefix, and `subjects` —
                                      a LIST, one entry per detected subject
                                      (R4). Files written before R4 carry a
                                      single `subject` and are still read;
                                      `photo_evidence.subject_list()` is the
                                      one place either shape is understood

## The ladder (Visual-Sorting DESIGN §4), and what is inert today

  1. one representative per in-batch visual cluster   (coverage guarantee,
                                                       CAPPED — see below)
  2. all gray-zone subject matches                    (VS-3 registry)
  3. embedding outliers                               (reserved budget)
  4. files with no subject and no scene signal        (VS-3 registry)
  5. farthest-point diversity fill                    (spends what is left)

**Rung 1 is capped at a share of the budget (F2 / option B1, signed
2026-08-07).** A pure priority fill degenerates to one rung: rung 1's demand
is `number of clusters`, which grows with the data, while the budget is a
fixed percentage of the pool, so whenever clusters outnumber the budget —
the normal case — rung 1 absorbs everything and "priority-filled ladder"
means "the medoids of the N biggest clusters". Measured over 77 real batches:
rung 1 took 785 of 813 picks (96.6%), rung 3 fired 0 times against 396
candidates, and on one measured dump 14 of 16 batches had more clusters
than budget.
`RUNG1_BUDGET_SHARE` reserves the remainder for rungs 3 and 5. The rung-3
case — the screenshot inside a trip batch — is precisely the file a
cluster-medoid pass never reaches, and it is why the ladder has more than
one rung.

**The naming carve-out (DESIGN 2026-08-08, N-4).** A cluster that will
become its own output folder keeps its rung-1 pick *unconditionally, outside
the quota*: N-4 requires every name phrase to rest on a `viewed-image:`
source, and rung 1 is the mechanism that supplies one seen photo per cluster,
so a cap alone would starve exactly the clusters that become folders. Where
the folder name will carry `[who]`, the guaranteed pick must be a photo
CONTAINING that subject — a landscape medoid from the same cluster satisfies
rung 1 and satisfies nothing about naming.

**Rungs 2 and 4 and the carve-out read VS-3's subject registry** (`photo_
subjects.py`, `photo-subjects/` in the owner pack), and the registry is the
ONLY thing they read: inferring folder-bound clusters from the recurrence
census's centroids would put a collection-level file dependency and a new
failure mode inside a batch-level stage on nobody's sign-off.

A run whose pack holds no subjects — every benchmark run, and every run before
a first memory checkpoint — gets an empty registry, and then all three answer
with nothing and this stage behaves exactly as it did before VS-3. That is not
a fallback, it is the correct answer: with no registry, "this file has no
subject" is not FALSE, it is UNKNOWN, and asserting it would be the same class
of mistake as a `clip-*` label claiming `viewed-image:`. The count of files
with no scene signal stays published as a plain statistic
(`diagnostics.no_scene_signal`) and steers nothing on its own.

⚠️ "Can the registry answer?" is a per-FILE question, not a pack-level one,
and rung 4 asks it as `eligible > 0` — the number of subjects that could
recognise at all AND passed the timeline gate for that file. A pack of
unconfirmed drafts holds records but no exemplars; a subject whose
confirmation was withdrawn holds exemplars but no live yes; a pack whose
subjects are all out of era holds both and may use neither here. All look
like a loaded registry and none can recognise anything, so gating on the
record count would fire rung
4 across a whole batch and displace rung 5's diversity fill.

## Provenance is load-bearing (2026-07-20 fabrication incident)

  viewed-image:      the vision model actually looked at this file
  clip-matched:      high-confidence zero-shot, NOT seen
  clip-propagated:   inherited from the representative of its visual cluster

`--apply` will stamp `viewed-image:` on a file only when that file is in the
see-list AND its downscaled thumbnail is on disk — the seen-list is
cross-checked against real thumbnails, exactly as the DESIGN's validator
line requires. A `clip-*` label can never be promoted to `viewed-image:`;
`assert_no_fabrication()` is the mechanical check and `tests/photo_see_cases.py`
fails the build if it stops holding.

## The screenshot class is a SECOND detector, and it never moves a file

`photo_sample.preclassify()`'s filename rule (ONB-12, signed off) and screen-
dimension rule stay exactly as they are, and files they decide are removed
from the see pool before the ladder runs — this stage cannot weaken them.
The zero-shot `screenshots` class is the complement for what they miss (a
Samsung JPEG screenshot at a size nobody registered — the Group 6 lesson).
What it produces is a FLAG in `diagnostics.screenshot_suspects` and a raised
see priority, never a route: ONB-10 requires saying whether a proposal moves
files or only annotates, and moving files on an unswept-out zero-shot class
has no sign-off. The operator sees the flag; the vision model decides.

## Labels are owner data, not an engine table (ONB-10)

`visual_sorting.scene_labels` in the owner pack wins; the fallback below is
the DESIGN's set and is deliberately narrow rather than generous.

Its KEYS are stable ASCII class ids and the displayed name is resolved at call
time — `screenshots` through `photo_profile.buckets()`, every other named
class through `photo_profile.scene_classes()`. A class name is a string a
human reads, so an English-language owner gets `Screenshots` and not somebody
else's language (ONB-9); a run with no pack at all resolves to the legacy
table and emits exactly what it emitted yesterday, which is what keeps every
replay comparison against a shipped decision meaningful.

The PROMPTS stay English because the shipped model (`laion2b_s34b_b79k`) is
an English-text CLIP; a non-English prompt scores noise.
That asymmetry is deliberate and is recorded in the report as
`scene_labels.prompt_language`.

## Two classes in this set are not visually decidable

`day_trip` and `overseas_trip` differ by WHERE, not by what the picture looks
like — a temple is a temple at home and abroad. They are in the set because
the DESIGN's label list puts them there, and the replay measures what that
costs; see `tests/see_replay.py` for the per-class numbers. Treat a zero-shot
`overseas_trip` as evidence about the scene, never about the country.

## Dependencies

numpy only, like `photo_recurrence.py` — no torch. The text side of CLIP
runs once, in `photo_embed.py --scene-labels`, and lands as
`embed/scene-labels.npy`; this stage only takes dot products against it. The
label file carries the same model identity as the image index and is refused
when the two disagree, because a text vector from another model is not
comparable to these image vectors.

Usage:
  python3 photo_see.py "<Working Files>/202401" --batch 1
  python3 photo_see.py "<Working Files>/202401" --batch 1 --see-rate 0.15 --force
  python3 photo_see.py "<Working Files>/202401" --batch 1 --apply decisions.json
  python3 photo_see.py "<Working Files>/202401" --batch 1 --validate
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import photo_embed  # noqa: E402
import photo_evidence  # noqa: E402
import photo_identity
import photo_platform  # noqa: E402
import photo_profile  # noqa: E402
import photo_subjects  # noqa: E402
from photo_cluster import parse_date  # noqa: E402
from photo_recurrence import META_IDENTITY, TEXT_IDENTITY, cluster  # noqa: E402
from photo_sample import preclassify, tier_of  # noqa: E402
import photo_census  # noqa: E402

# In-batch clustering inherits VS-1b's threshold and its sweep: 0.80 was
# picked off a real 9,915-file index (photo_recurrence.py docstring)
# and the same function does the clustering here, so a second, differently
# tuned tau would mean two definitions of "the same thing" in one pipeline.
# What a batch changes is the population, not the geometry. Override --tau.
SEE_TAU = 0.80

# See-rate (DESIGN §4 config block). first_sort = a new dump, registry thin;
# second_sort = re-sorts, to-be-checked passes, mature registry.
DEFAULT_VISUAL_SORTING = {
    "see_rate": {"first_sort": 0.10, "second_sort": 0.05},
    "see_floor": 5,
    "see_cap": 40,
    "gray_zone_always_seen": True,
}

# Only these preclasses reach the ladder. screenshot/screen_record are already
# decided by rules that ship and are signed off (ONB-12), and `no_exif` is
# D13's no-date/no-GPS route to the to-be-checked bucket for human triage.
# Spending vision budget on files whose destination is already fixed buys
# nothing, and it is
# also what photo_sample sampled, which keeps the replay an A/B of SELECTION.
SEE_POOL_CLASSES = ("own", "shared")

# ⛔ A34a widened `shared` — T2 (the messenger named the file) and T3 (the
# messenger's compression ladder) now land there, which on this corpus is
# 1,773 files that used to be `no_exif`. They must NOT enter the pool on that
# alone: the Non-EXIF SPEC v1.2 section 7 sends T2/T3 to VI only where the
# workdir holds SEVERAL events, and that condition is not built — the
# day-to-folder mapping A38 stops short of is the same missing piece. Enrolling
# them unconditionally would spend vision budget on files whose destination is
# already decided, silently, on a gate nobody signed.
#
# Written as tiers rather than as a class list because the class is exactly
# what stopped discriminating: T2/T3 and an ordinary AirDrop save are all
# `shared` now, and only the tier says which is which.
SEE_POOL_EXCLUDED_TIERS = ("T2", "T3")

# Zero-shot acceptance. `sim` is the raw cosine to the class vector and
# `margin` is best-minus-second. Cosines from this model sit in a narrow band
# (~0.15-0.30) and are not comparable across classes, so the MARGIN is what
# decides; sim is reported but not gated on. Both numbers were swept against
# the shipped per-file decisions of 6 done dumps — see tests/see_replay.py
# --sweep and the numbers recorded in photo-see/SKILL.md.
SCENE_MARGIN_ACCEPT = 0.05   # >= this: clip-matched, spends no vision budget
SCENE_MARGIN_SIGNAL = 0.01   # < this: no scene signal at all (diagnostic only)

OUTLIER_MAX_SIM = 0.70       # rung 3: nothing in the batch looks like this file

# F2 / option B1: the share of the budget rung 1 may spend on its ORDINARY
# (non-carve-out) candidates. The remainder is reserved for rungs 3 and 5.
#
# Swept 0.30-1.00 in 0.05 steps on the `2023` benchmark replay with the naming
# carve-out live, and the sweep's honest finding is that THE PARAMETER IS FLAT:
# minority-row reproduction ranged only 68-77 of 126 across the whole sweep and
# was non-monotonic in the middle (0.70 -> 76, 0.75 -> 73, 0.80 -> 75), i.e.
# boundary effects, not a trend. Cost was identical at every share — the
# see-rate fixes the total budget and this only splits it between rungs, so
# there is no cost/accuracy trade-off here. 0.85 is the joint peak on that
# metric while still holding real budget back for rungs 3 and 5.
#
# ⚠️ Treat this as a POLICY CHOICE WITH A MEASURED FLOOR, not a tuned optimum.
# The replay cannot adjudicate F2/B1: every pick propagates its label to its
# whole cluster, and rung 1 picks one representative per distinct cluster, so
# the score function IS rung 1's objective and any sweep on that harness will
# favour giving rung 1 more. The oracle also returns each file's SHIPPED
# decision as truth, so a rung-3/5 look that CORRECTS a shipped label can never
# score as a win — the value B1 was bought for is invisible to the instrument.
# Settling it needs a run where the vision model is really called. Until then,
# do not read the sweep as licence to approach 1.0: that makes the quota inert.
# Note also that batch granularity changes which constraint binds — archive-era
# batches average 15-71 files and mostly sit on `see_floor`, where rung-1
# starvation looks different from the 2026 dumps.
RUNG1_BUDGET_SHARE = 0.85

PROVENANCE = photo_evidence.VISUAL_PROVENANCE

# Engine fallback label set — the DESIGN's list, English prompts (see the
# module docstring), narrow by ONB-10. An owner pack overrides it wholesale
# via visual_sorting.scene_labels.
#
# The KEYS are stable ASCII class ids, and what a human reads is resolved at
# call time (`scene_label_set()` below) — an owner's language decides the
# displayed name, never this table. Utility classes have no owner-facing name
# to resolve and stand as they are.
# ⛔ 11 entries, and this is NOT a longer `[type]` list — see the three-list
# note above `photo_profile.SCENE_CLASS_VOCAB`. These are CLIP prompt sets:
# the 6 nameable scene classes plus 5 utility detectors that exist to
# recognise an image and never to name a folder.
DEFAULT_SCENE_LABELS = {
    "hiking": ["a photo of hiking on a mountain trail",
               "a mountain ridge seen from a hiking trail",
               "hikers climbing a rocky peak"],
    "overseas_trip": ["a photo taken while travelling in a foreign country",
                      "a famous tourist landmark abroad",
                      "a foreign city street seen by a tourist"],
    "day_trip": ["a photo from a day trip to a nearby town",
                 "a local sightseeing spot",
                 "a walk around a city park"],
    "dining": ["a photo of people eating together at a restaurant",
               "a group of friends around a dinner table"],
    "cat": ["a photo of a cat", "a kitten resting at home"],
    "dog": ["a photo of a dog", "a puppy outdoors"],
    "screenshots": ["a screenshot of a phone screen",
                    "a screenshot of a mobile app user interface",
                    "a screenshot of a web page"],
    "document": ["a scanned document", "a photo of a printed page of text",
                 "a photo of a paper receipt"],
    "whiteboard": ["a photo of a whiteboard covered in writing",
                   "handwritten notes on a whiteboard"],
    "food": ["a close-up photo of a plate of food",
             "a dish of food served on a table"],
    "AI-image-suspect": ["an AI generated image", "a digital illustration",
                         "computer generated artwork"],
}
# The one class in the set that is also a folder the ENGINE invents. It
# resolves through buckets() rather than through the scene-class table so
# there is ONE string for it and not two that can drift apart (ONB-9).
BUCKET_BACKED_CLASSES = {"screenshots": "screenshots"}


def scene_label_set(profile=None):
    """-> (ordered dict class -> prompts, source). Owner pack first (ONB-10).

    The fallback set's ids are resolved to displayed names here, so a run with
    no pack keeps emitting exactly the strings it emitted before the ids
    existed (`photo_profile.LEGACY_SCENE_CLASS_LANGUAGE`) and an owner in any
    other language gets their own."""
    packed = photo_profile.get(profile, "visual_sorting", "scene_labels", default=None)
    if packed:
        return {str(k): [str(p) for p in v] for k, v in packed.items()}, "owner pack"
    buckets = photo_profile.buckets(profile)
    vocabulary = photo_profile.scene_classes(profile)
    out = {}
    for class_id, prompts in DEFAULT_SCENE_LABELS.items():
        bucket = BUCKET_BACKED_CLASSES.get(class_id)
        name = buckets[bucket] if bucket else vocabulary.get(class_id, class_id)
        out[name] = list(prompts)
    return out, "engine fallback"


def visual_sorting_config(profile=None):
    cfg = {**DEFAULT_VISUAL_SORTING,
           **(photo_profile.get(profile, "visual_sorting", default={}) or {})}
    cfg["see_rate"] = {**DEFAULT_VISUAL_SORTING["see_rate"],
                       **(cfg.get("see_rate") or {})}
    return cfg


def budget_for(pool_size, rate, cfg):
    """floor/cap keep tiny and huge batches sane, and neither may exceed the
    pool: a floor of 5 over a 3-file batch means "see all three"."""
    n = round(pool_size * rate)
    n = max(int(cfg["see_floor"]), min(int(cfg["see_cap"]), n))
    return max(0, min(n, pool_size))


# ---------------------------------------------------------------- inputs ----

def load_batch(workdir, batch_no):
    batches_path = workdir / "batches.json"
    if not batches_path.exists():
        sys.exit(f"no batches.json in {workdir} — run photo_cluster.py first")
    batches = json.loads(batches_path.read_text())
    batch = next((b for b in batches["batches"] if b["batch"] == batch_no), None)
    if batch is None:
        sys.exit(f"batch {batch_no} not in {batches_path}")
    return batch


def load_rows(workdir, batch):
    """The batch's manifest rows, in manifest order (which photo_scan wrote in
    a stable order) — every downstream ordering is by sha256 or by path, so
    this only has to be reproducible."""
    rows = []
    with open(workdir / "manifest.csv", newline="") as f:
        for row in csv.DictReader(f):
            dt = parse_date(row)
            if dt and batch["from"] <= dt.date().isoformat() <= batch["to"]:
                row["_dt"] = dt
                rows.append(row)
    return rows


def load_index(workdir):
    """-> ({SourceFile: (sha256, vector)}, identity). Failed rows are all-zero
    vectors at the same row index (`zero_vector_means_failed`), and a zero
    vector has no cosine, so they are dropped here rather than poisoning a
    cluster — the count reaches the report as `unembedded`."""
    import numpy as np

    embed_dir = workdir / "embed"
    for required in ("embeddings.csv", "embeddings.npy", "embeddings-meta.json"):
        if not (embed_dir / required).exists():
            sys.exit(f"{embed_dir / required} is missing — run photo_embed.py on "
                     f"{workdir} first")
    meta = json.loads((embed_dir / "embeddings-meta.json").read_text())
    with open(embed_dir / "embeddings.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    arr = np.load(embed_dir / "embeddings.npy")
    index = {}
    for row, vec in zip(rows, arr):
        if row.get("status") != "embedded":
            continue
        norm = float(np.linalg.norm(vec))
        if norm < 0.5:
            continue
        index[row["SourceFile"]] = (row["sha256"], vec / norm)
    return index, photo_embed.space_view(meta, META_IDENTITY)


def load_scene_labels(path, identity, classes):
    """-> (matrix (C, D), class list, meta) or (None, [], None) when absent.

    Refuses a label file built under another model for the same reason
    photo_recurrence refuses two indexes: a text vector from another CLIP is
    not comparable to these image vectors, and the failure would be silent —
    every file would just get a slightly wrong class."""
    import numpy as np

    path = Path(path)
    if not path.exists():
        return None, [], None
    meta = json.loads(path.read_text())
    vec_path = path.with_suffix(".npy")
    if not vec_path.exists():
        sys.exit(f"{path} exists but {vec_path} does not — re-run "
                 "photo_embed.py --scene-labels")
    theirs = {k: meta.get(k) for k in TEXT_IDENTITY}
    if theirs != {k: (identity or {}).get(k) for k in TEXT_IDENTITY}:
        sys.exit(f"{path} was encoded with a different model/preprocess ({theirs}) "
                 f"than this work dir's image index ({identity}). Text and image "
                 "vectors are only comparable within one model — re-run "
                 "photo_embed.py --scene-labels.")
    if list(meta["classes"]) != list(classes):
        sys.exit(f"{path} holds classes {list(meta['classes'])} but this run resolves "
                 f"{list(classes)} (the owner pack changed, or the language did) — "
                 "re-run photo_embed.py --scene-labels.")
    return np.load(vec_path), list(meta["classes"]), meta


# ------------------------------------------------------------- zero-shot ----

def zero_shot(X, L, classes):
    """-> list of {class, sim, margin, confident, signal} per row of X."""
    import numpy as np

    if L is None or not len(X):
        return [None] * len(X)
    sims = X @ L.T
    order = np.argsort(-sims, axis=1)
    out = []
    for i in range(len(X)):
        best, second = int(order[i][0]), int(order[i][1]) if sims.shape[1] > 1 else None
        margin = float(sims[i][best] - (sims[i][second] if second is not None else 0.0))
        out.append({
            "class": classes[best],
            "sim": round(float(sims[i][best]), 4),
            "margin": round(margin, 4),
            "confident": margin >= SCENE_MARGIN_ACCEPT,
            "signal": margin >= SCENE_MARGIN_SIGNAL,
        })
    return out


# ------------------------------------------------------------ the ladder ----

def medoid(X, shas, members):
    """The member most like the rest of the given set — what a single look has
    to stand for. Ties go to the lower sha256 so a cluster of identical burst
    frames still picks the same file every run. Called with a whole cluster
    (rung 1) and with the subject-containing subset of one (the carve-out)."""
    sub = X[members]
    totals = (sub @ sub.T).sum(axis=1)
    best = min(range(len(members)),
               key=lambda j: (-float(totals[j]), shas[members[j]]))
    return members[best]


def representatives(X, labels, shas):
    """-> [(cluster_id, member_indices, medoid_index)], biggest cluster first."""
    groups = {}
    for i, lid in enumerate(labels):
        groups.setdefault(int(lid), []).append(i)
    out = []
    for lid in sorted(groups):
        members = groups[lid]
        out.append((lid, members, medoid(X, shas, members)))
    # Largest clusters first: one look at a 60-file cluster buys 60 files of
    # coverage, one look at a singleton buys one. A batch with more clusters
    # than budget therefore leaves its smallest clusters unrepresented, and
    # the report says so (`ladder[0].unfilled`).
    out.sort(key=lambda t: (-len(t[1]), shas[t[2]]))
    return out


def subject_matches(verdicts=None, shas=None):
    """Rung 2 — gray-zone subject matches: the registry thinks it knows who
    this is and is not sure enough to say so (`gray_low` <= score < `accept`),
    or two subjects are indistinguishable on this file. Both are the same kind
    of file — one a machine cannot settle and a pair of eyes can.

    `verdicts` come from `photo_subjects.Registry.match()`, one per pool index.
    No registry means no verdicts means NOTHING is gray: with no exemplars, no
    thresholds and no timeline there is nothing to be uncertain about, and a
    proxy would be an invention. -> pool indices, most confident first."""
    if not verdicts:
        return []
    gray = (photo_subjects.VERDICT_GRAY, photo_subjects.VERDICT_QUESTION)
    picks = [(i, v) for i, v in enumerate(verdicts)
             if v and v.get("verdict") in gray]
    picks.sort(key=lambda t: (-(t[1].get("score") or 0.0),
                              shas[t[0]] if shas else str(t[0])))
    return [i for i, _v in picks]


def unknown_files(verdicts=None, scenes=None):
    """Rung 4 — files with **no subject and no scene** signal.

    The rung is a CONJUNCTION, and that is why it stayed inert through VS-2:
    the scene half was computable, but with no registry to ask, "this file has
    no subject" is UNKNOWN, not false, and treating unknown as false is the
    same move that produced the 2026-07-20 fabrication.

    ⚠️ The condition is per-FILE, and it is `eligible`, not "a registry
    exists". `eligible` counts the subjects that were actually comparable
    against THIS file — they may recognise at all (`Registry.recognisers`)
    AND they pass the timeline gate — so it separates the two things a bare
    `none` verdict conflates:

      eligible == 0  the registry could not look. A pack of unconfirmed drafts
                     has records but no exemplars; a withdrawn subject has
                     exemplars but no live yes; a pack whose subjects are all
                     out of era has both and may use neither here. None of
                     them is evidence the file has no subject — all are
                     UNKNOWN.
      eligible >  0  the registry looked and found nobody. That IS "no
                     subject", and it is what this rung is for.

    Gating on the registry's record count instead would fire the whole rung on
    a pack that cannot recognise anything, displacing rung 5 across a batch.

    The scene half stays published as `diagnostics.no_scene_signal` so it is
    visible without steering anything.

    -> pool indices in sha order (the pool is sha-sorted upstream)."""
    if not verdicts:
        return []
    out = []
    for i, verdict in enumerate(verdicts):
        if not verdict:
            continue                      # no registry answer at all -> UNKNOWN
        if verdict.get("verdict") != photo_subjects.VERDICT_NONE:
            continue                      # the registry named someone
        if not (verdict.get("eligible") or 0):
            continue                      # it could not look -> UNKNOWN, not false
        scene = scenes[i] if scenes is not None and i < len(scenes) else None
        if scene and scene.get("signal"):
            continue
        out.append(i)
    return out


def folder_bound_clusters(paths=None, labels=None, registry=None, verdicts=None):
    """The naming carve-out's input (DESIGN, N-4): which in-batch clusters will
    become their **own output folder**, and — where that folder's name will
    carry `[who]` — which files in the cluster actually CONTAIN that subject.

    -> {cluster_id: [pool indices containing the subject]}; an empty list
    means "this cluster becomes a folder, but no subject is named on it", so
    the ordinary cluster medoid is the guaranteed pick.

    **The pack registry is the only sanctioned source.** Guessing it from the
    recurrence census's centroids would put a collection-level file dependency
    and a new failure mode inside a batch-level stage on nobody's sign-off —
    this stage reads the pack it already resolves, and nothing else.

    A cluster is folder-bound when it holds at least one **accept-level** match
    to a subject that forms its own folder (`Subject.forms_own_folder()`: a
    confirmed name plus a declared `active` start, which under N-10a is exactly
    the recurring-subject / D9 class). A gray-zone match does not qualify: a
    guaranteed look is a naming commitment and N-4 will not rest a folder name
    on a maybe — those files are rung 2's job instead.
    """
    if not registry or not verdicts or labels is None:
        return {}
    forming = {s.subject_id for s in registry.subjects if s.forms_own_folder()}
    if not forming:
        return {}
    out = {}
    for i, verdict in enumerate(verdicts):
        if not verdict or verdict.get("verdict") != photo_subjects.VERDICT_ACCEPT:
            continue
        if verdict.get("subject_id") not in forming:
            continue
        out.setdefault(int(labels[i]), []).append(i)
    return {lid: sorted(members) for lid, members in sorted(out.items())}


def guaranteed_picks(X, labels, shas, folder_bound):
    """-> {cluster_id: index}: the carve-out picks, taken before the rung-1
    quota and exempt from it.

    Where the folder name will carry `[who]`, the pick is the medoid of the
    SUBJECT-CONTAINING members, not of the whole cluster — N-4 needs a photo
    the model can read a `[behaviour]` off, and a landscape frame from the
    same cluster is not that photo. With no subject members named, the
    ordinary cluster medoid stands."""
    if not folder_bound:
        return {}
    groups = {}
    for i, lid in enumerate(labels):
        groups.setdefault(int(lid), []).append(i)
    out = {}
    for lid, subject_members in sorted(folder_bound.items()):
        members = groups.get(int(lid))
        if not members:
            continue                      # a cluster id this batch does not have
        subject = [i for i in (subject_members or []) if i in set(members)]
        out[int(lid)] = medoid(X, shas, subject or members)
    return out


def outliers(X, labels, shas, exclude):
    """Rung 3 — files nothing else in the batch looks like. Score = the best
    cosine to any MULTI-member cluster centroid; a low score means the batch
    has no mass anywhere near this file (the screenshot inside a trip).

    A member of a multi-member cluster is within tau of its leader, which puts
    it around 0.83 from its own centroid — above OUTLIER_MAX_SIM — so the
    candidate set is a SUBSET of the singleton clusters, not all of them: a
    singleton sitting near a big cluster's centroid scores above the threshold
    and is no candidate at all (measured on one real batch: 0 of 12 singletons
    qualified). The subset claim is what the geometry supports; the earlier
    "exactly the singletons" wording overstated it (F7).

    That subset relation is also NOT why rung 3 used to fire 0 times. The
    load-bearing reason was budget exhaustion by rung 1 (F2) — every candidate
    was either already claimed as a cluster representative or arrived after
    the budget was gone. With `RUNG1_BUDGET_SHARE` reserving budget below
    rung 1, this rung is reachable."""
    import numpy as np

    groups = {}
    for i, lid in enumerate(labels):
        groups.setdefault(int(lid), []).append(i)
    centroids = []
    for lid in sorted(groups):
        if len(groups[lid]) < 2:
            continue
        c = X[groups[lid]].mean(axis=0)
        n = float(np.linalg.norm(c))
        centroids.append(c / n if n else c)
    if not centroids:
        best = np.zeros(len(X), dtype=np.float32)
    else:
        best = (X @ np.stack(centroids).T).max(axis=1)
    picks = [(float(best[i]), shas[i], i) for i in range(len(X))
             if i not in exclude and float(best[i]) < OUTLIER_MAX_SIM]
    picks.sort()
    return [i for _, _, i in picks]


def diversity_fill(X, shas, chosen, k):
    """Rung 5 — farthest-point: repeatedly take the file least like anything
    already chosen. Deterministic: no random seed anywhere, ties by sha256,
    and an empty `chosen` starts from the file least like the batch mean."""
    import numpy as np

    if k <= 0:
        return []
    remaining = [i for i in range(len(X)) if i not in chosen]
    if not remaining:
        return []
    picked = list(chosen)
    out = []
    if not picked:
        mean = X.mean(axis=0)
        norm = float(np.linalg.norm(mean))
        mean = mean / norm if norm else mean
        sims = X @ mean
        first = min(remaining, key=lambda i: (float(sims[i]), shas[i]))
        out.append(first)
        picked.append(first)
        remaining.remove(first)
    while remaining and len(out) < k:
        sims = (X[remaining] @ X[picked].T).max(axis=1)
        j = min(range(len(remaining)), key=lambda t: (float(sims[t]), shas[remaining[t]]))
        out.append(remaining[j])
        picked.append(remaining[j])
        remaining.pop(j)
    return out[:k]


def rung1_quota(budget, share=RUNG1_BUDGET_SHARE):
    """How many ORDINARY rung-1 picks the budget allows (F2 / option B1).

    Carve-out picks are not counted here — they are outside the quota by
    rule. Rounded, then floored at 1 so a `see_floor`-sized batch still gets
    coverage: at budget 5 and share 0.65 the quota is 3, leaving 2 for the
    rungs below. `share=1.0` reproduces the pre-quota ladder exactly, which is
    how the tests measure what the quota changed."""
    if budget <= 0:
        return 0
    return max(1, min(int(budget), int(round(budget * float(share)))))


def run_ladder(X, labels, shas, budget, gray_zone_always_seen,
               guaranteed=None, rung1_share=RUNG1_BUDGET_SHARE,
               gray=None, unknown=None, registry_subjects=0):
    """-> (selected [(index, rung, reason)], ladder trace).

    Priority-filled in the DESIGN's order, with rung 1 capped at
    `rung1_share` of the budget (F2 / option B1) so it can no longer absorb
    the whole ladder. A rung that would overflow the budget is truncated and
    the trace records what each rung wanted, so a starved rung is visible
    rather than invisible.

    `guaranteed` is `{cluster_id: index}` from `guaranteed_picks()` — the
    naming carve-out. Those picks are taken FIRST and are exempt from the
    quota; taking them first matters, because a small subject cluster is
    exactly what `representatives()`' largest-first order would drop. They are
    still inside the total budget: the caller lifts the budget to at least
    `len(guaranteed)` (`build_report`), which is the DESIGN's "a floor of ~93
    seen files exists before any other rung is served" read as a floor on the
    budget rather than an overflow of it.

    `gray` (rung 2) and `unknown` (rung 4) are pool indices the caller computed
    from the subject registry — VS-3. They are passed IN rather than fetched
    here so this function stays a pure function of its arguments, and so a
    caller with no pack (see_replay) gets the pre-VS-3 ladder by default. Both
    are spent INSIDE the budget: unlike the carve-out, whose size is bounded by
    the number of output folders N-4 requires, the gray zone is unbounded, and
    flooring the budget on it would let one badly-set threshold spend arbitrary
    vision budget. A starved rung 2 is recorded in the trace instead.
    """
    chosen, selected, trace = set(), [], []
    guaranteed = dict(guaranteed or {})

    reps = representatives(X, labels, shas)
    size_of = {lid: len(members) for lid, members, _medoid in reps}
    picks, kept = [], []
    for lid in sorted(guaranteed, key=lambda l: (-size_of.get(l, 0), l)):
        idx = guaranteed[lid]
        # A dropped carve-out pick is an N-4 violation, so it is COUNTED and
        # published rather than silently skipped. It cannot happen through
        # build_report, which floors the budget at len(guaranteed); it can
        # happen to any other caller that passes a budget of its own.
        if idx in {i for i, _w in picks} or len(picks) >= budget:
            continue
        kept.append(lid)
        picks.append((idx, f"cluster {lid} ({size_of.get(lid, 0)} files) — this "
                           "cluster becomes its own output folder, so its look is "
                           "outside the quota (N-4 naming carve-out)"))
    quota = rung1_quota(budget, rung1_share)
    would_fit = budget - len(kept)      # what the UNCAPPED ladder would have taken
    quota_dropped = 0
    for rank, (lid, members, med) in enumerate(
            [r for r in reps if r[0] not in kept]):
        if rank < quota and len(picks) < budget:
            picks.append((med, f"cluster {lid} ({len(members)} files)"))
        elif rank < would_fit:
            # the quota held this one back; the budget alone would have taken it
            quota_dropped += 1
    for idx, why in picks:
        chosen.add(idx)
        selected.append((idx, 1, f"representative of {why}"))
    unrepresented = len(reps) - len(picks)
    trace.append({"rung": 1, "name": "one representative per visual cluster",
                  "status": "filled" if picks else "empty",
                  "available": len(reps), "picked": len(picks),
                  "unfilled": unrepresented,
                  "guaranteed": len(kept), "quota": quota,
                  "quota_share": round(float(rung1_share), 4),
                  "quota_capped": quota_dropped,
                  "guaranteed_dropped": len(guaranteed) - len(kept),
                  "note": ("clusters are taken largest first, carve-out clusters "
                           "before them; " +
                           (f"⚠️ {len(guaranteed) - len(kept)} carve-out pick(s) did "
                            "not fit the budget — N-4 says they are unconditional, so "
                            "the caller must floor the budget at the number of "
                            "folder-bound clusters. "
                            if len(guaranteed) - len(kept) else "") +
                           (f"{quota_dropped} cluster(s) that the budget alone would "
                            f"have admitted were held back by the "
                            f"{float(rung1_share):.0%} rung-1 quota so rungs 3 and 5 "
                            "keep a share of the budget (F2). "
                            if quota_dropped else "") +
                           ("the batch has more clusters than budget, so the "
                            "smallest are unrepresented"
                            if unrepresented else "every cluster has a look"))})

    # gray_zone_always_seen=false switches the rung OFF: the config line exists
    # to say whether an uncertain subject match is worth a look at all, and
    # "always seen, budget permitting" is what every other rung already means.
    gray = list(gray if gray is not None else subject_matches())
    taken_gray = []
    if gray_zone_always_seen:
        for idx in gray:
            if idx not in chosen and len(chosen) < budget:
                chosen.add(idx)
                taken_gray.append(idx)
                selected.append((idx, 2, "gray-zone subject match — the registry "
                                         "is not sure who this is, and that is "
                                         "exactly what eyes settle"))
    trace.append({"rung": 2, "name": "gray-zone subject matches",
                  "status": ("filled" if taken_gray else
                             "off" if gray and not gray_zone_always_seen else
                             "starved" if gray else
                             "empty" if registry_subjects else "inert"),
                  "available": len(gray), "picked": len(taken_gray),
                  "unfilled": len(gray) - len(taken_gray),
                  "registry_subjects": int(registry_subjects),
                  "note": (f"gray_zone_always_seen={bool(gray_zone_always_seen)}; "
                           + (f"{registry_subjects} subject(s) with exemplars in "
                              "the owner pack's registry" if registry_subjects else
                              "nothing in this run's pack can recognise a subject "
                              "(no registry, or only drafts with no exemplars), so "
                              "there is nothing to be uncertain about and the rung "
                              "is inert rather than empty"))})

    room = budget - len(chosen)
    out = outliers(X, labels, shas, chosen)
    take = out[:max(0, room)]
    for idx in take:
        chosen.add(idx)
        selected.append((idx, 3, "embedding outlier — nothing in this batch looks "
                                 "like it"))
    trace.append({"rung": 3, "name": "embedding outliers", "status":
                  "filled" if take else ("starved" if out else "empty"),
                  "available": len(out), "picked": len(take),
                  "unfilled": len(out) - len(take),
                  "note": f"max cosine to any multi-member cluster < {OUTLIER_MAX_SIM}"})

    unknown = list(unknown if unknown is not None else unknown_files())
    taken_unknown = []
    for idx in unknown:
        if idx not in chosen and len(chosen) < budget:
            chosen.add(idx)
            taken_unknown.append(idx)
            selected.append((idx, 4, "no subject and no scene signal"))
    trace.append({"rung": 4, "name": "no subject and no scene signal",
                  "status": ("filled" if taken_unknown else
                             "starved" if unknown else
                             "empty" if registry_subjects else "inert"),
                  "available": len(unknown), "picked": len(taken_unknown),
                  "unfilled": len(unknown) - len(taken_unknown),
                  "note": ("both halves asked, per file: a subject was eligible at "
                           "the file's own date and matched nobody, and no scene "
                           "margin. A file no subject was ELIGIBLE for is UNKNOWN "
                           "and is not counted here" if registry_subjects else
                           "inert — nothing in this pack can recognise a subject, "
                           "so 'no subject' is UNKNOWN, not false; see "
                           "diagnostics.no_scene_signal for the scene half alone")})

    room = budget - len(chosen)
    fill = diversity_fill(X, shas, chosen, room)
    for idx in fill:
        chosen.add(idx)
        selected.append((idx, 5, "farthest-point diversity fill"))
    trace.append({"rung": 5, "name": "farthest-point diversity fill",
                  "status": "filled" if fill else "empty",
                  "available": len(X) - (len(chosen) - len(fill)),
                  "picked": len(fill), "unfilled": 0,
                  "note": "spends whatever the rungs above left"})

    selected.sort(key=lambda t: (t[1], shas[t[0]]))
    return selected, trace


# ---------------------------------------------------------- propagation -----

def provisional_labels(paths, labels, scenes, seen_idx, medoid_of):
    """What every unseen file is worth BEFORE the vision model runs.

    A file is `clip-matched:` when its own zero-shot margin clears
    SCENE_MARGIN_ACCEPT, `clip-propagated:` when its cluster's representative
    has a confident class, and unlabeled otherwise. Nothing here may say
    `viewed-image:` — that prefix belongs to --apply and only after a
    thumbnail proves the model had something to look at."""
    out = []
    for i, path in enumerate(paths):
        if i in seen_idx:
            out.append({"path": path, "label": None, "provenance": None,
                        "state": "pending-view"})
            continue
        scene = scenes[i]
        if scene and scene["confident"]:
            out.append({"path": path, "label": scene["class"],
                        "provenance": "clip-matched:", "state": "provisional",
                        "margin": scene["margin"]})
            continue
        rep = medoid_of.get(int(labels[i]))
        rep_scene = scenes[rep] if rep is not None else None
        if rep is not None and rep != i and rep_scene and rep_scene["confident"]:
            out.append({"path": path, "label": rep_scene["class"],
                        "provenance": "clip-propagated:", "state": "provisional",
                        "from": paths[rep], "margin": rep_scene["margin"]})
            continue
        out.append({"path": path, "label": None, "provenance": None,
                    "state": "unlabeled"})
    return out


def assert_no_fabrication(entries, seen_paths, samples_dir, report=None):
    """The 2026-07-20 guard, mechanical: `viewed-image:` may be claimed only
    by a file the controller put on the see-list AND whose downscaled
    thumbnail is really there. A `clip-*` label reaching this prefix is the
    exact failure mode the incident produced — a label that reads as evidence
    when nobody looked. Raises rather than returning a flag: there is no safe
    way to continue past it.

    **Hardened at VS-4.** `(samples_dir / sample).is_file()` was the whole
    thumbnail test, and it passes for an empty file, a text file with a .jpg
    name, a symlink pointing anywhere on the disk, a `../` escape, and one
    thumbnail reused as evidence for a whole batch. Each of those is a
    one-line forgery and each is now refused — `photo_evidence` holds the
    rules, so the memorize loop and `photo_classify_validate.py` apply exactly
    the same ones. Pass `report` to additionally require that the thumbnail a
    claim names is the thumbnail the see controller recorded FOR THAT FILE."""
    problems = photo_evidence.viewed_claim_problems(entries, seen_paths,
                                                    samples_dir, report=report)
    if problems:
        raise AssertionError(problems[0] if len(problems) == 1
                             else "; ".join(problems))
    return True


# -------------------------------------------------------------- reporting ---

def pending_screen_sizes(workdir, profile):
    """-> the unanswered screen sizes of the WHOLE dump (the census counts
    across every batch, so one batch alone could fall under its threshold).
    A work dir with no manifest holds nothing back."""
    manifest = Path(workdir) / "manifest.csv"
    if not manifest.exists():
        return set()
    with open(manifest, newline="") as f:
        return photo_census.pending_screen_sizes(list(csv.DictReader(f)), profile)


def build_report(workdir, batch, rows, index, labels_matrix, classes, label_meta,
                 identity, cfg, rate, pass_name, tau, profile, label_source,
                 rate_source, pack=None, held_sizes=None, document_flags=None):
    """`pack` is the resolved owner pack, and it defaults to None on purpose:
    a caller that does not hand one over gets the empty registry and therefore
    the pre-VS-3 ladder, byte for byte. `tests/see_replay.py` is that caller —
    its blank-sheet guarantee stays a property of the signature rather than of
    a literal it remembers to pass."""
    import numpy as np

    if held_sizes is None:
        held_sizes = pending_screen_sizes(workdir, profile)
    if document_flags is None:
        document_flags = photo_embed.load_document_flags(Path(workdir) / "embed")
    exif_class, pool_rows, unembedded = {}, [], []
    held = {"pending_screen_size": 0, "document": 0}
    document_unchecked = []
    for row in rows:
        cls = preclassify(row, profile)
        row["_preclass"] = cls
        exif_class[cls] = exif_class.get(cls, 0) + 1
        if cls not in SEE_POOL_CLASSES:
            continue
        if tier_of(row, profile)[0] in SEE_POOL_EXCLUDED_TIERS:
            continue
        # F-jj — probably a screenshot the owner has not been asked about yet.
        if photo_census.at_pending_screen_size(row, held_sizes):
            held["pending_screen_size"] += 1
            continue
        # F-jj — the U3-06 document check, scored at embed (owner ruling
        # Q-a: every still, camera photos included).
        if row.get("FileType") in photo_embed.IMAGE_TYPES:
            flag = document_flags.get(row["SourceFile"])
            if flag:
                held["document"] += 1
                continue
            if flag is None and row["SourceFile"] in index:
                document_unchecked.append(row["SourceFile"])
        if row["SourceFile"] not in index:
            unembedded.append(row["SourceFile"])
            continue
        pool_rows.append(row)

    pool_rows.sort(key=lambda r: index[r["SourceFile"]][0])   # sha order: stable
    paths = [r["SourceFile"] for r in pool_rows]
    shas = [index[p][0] for p in paths]
    X = (np.stack([index[p][1] for p in paths]).astype(np.float32) if paths
         else np.zeros((0, 1), dtype=np.float32))

    scenes = zero_shot(X, labels_matrix, classes)
    if len(X):
        cluster_labels, _leaders = cluster(X, shas, tau)
    else:
        cluster_labels = np.zeros(0, dtype=np.int64)

    reps = representatives(X, cluster_labels, shas) if len(X) else []
    medoid_of = {lid: med for lid, _members, med in reps}

    # VS-3. The registry is the owner's, so an unbound run gets an empty one and
    # every rung below behaves exactly as it did before VS-3 existed. The date
    # handed to the timeline gate is each file's OWN capture time, parsed from
    # its EXIF by load_rows() — never the folder path, which is a different
    # claim and a wrong one for any file that strayed into another era's dump.
    registry = photo_subjects.load(pack=pack)
    # What the ladder's inert/empty distinction turns on: a subject that cannot
    # attribute a file is a record, not a recogniser. A pack of unconfirmed
    # drafts can no more answer "who is this" than an absent pack can — and
    # neither can a subject whose confirmation was withdrawn, though it still
    # holds the evidence. `recognisers` is `match()`'s own test, read from
    # there rather than restated, so the report cannot claim a capacity the
    # matcher does not have.
    usable_subjects = len(registry.recognisers)
    dates = [row["_dt"] for row in pool_rows]

    # VS-3b. The identity index is a SECOND index over the same work dir and
    # is optional: absent, every row below is None and `match()` scores in the
    # CLIP space exactly as it always did. Rows are built in `paths` order so
    # row i means the same file in both matrices — the one invariant the two
    # spaces have to share.
    id_index, id_space = photo_identity.load_index(workdir / "embed", pack)
    # R4 — every detection, not only the primary one. `load_index()` answers
    # one row per FILE, which is the right shape for the score matrix below
    # (row i is file i) and the wrong one for telling the agent HOW MANY
    # animals a frame holds. That count is what says whether the `subjects`
    # list it writes back should have one entry or two.
    detections, _det_space = photo_identity.load_detections(workdir / "embed",
                                                            pack)
    X_identity = None
    identity_rows = 0
    if id_index:
        X_identity = np.zeros((len(paths), id_space["embed_dim"]), dtype=np.float32)
        for i, path in enumerate(paths):
            row = id_index.get(path)
            if row is None:
                continue
            meta_row, vec = row
            if meta_row.get("status") == photo_identity.STATUS_OK:
                X_identity[i] = vec
                identity_rows += 1

    try:
        verdicts = registry.match(X, dates, identity, X_identity=X_identity,
                                  identity_space=id_space) if len(X) else []
    except ValueError as exc:
        sys.exit(str(exc))

    # The naming carve-out (N-4) — see folder_bound_clusters().
    folder_bound = folder_bound_clusters(paths, cluster_labels, registry, verdicts)
    guaranteed = guaranteed_picks(X, cluster_labels, shas, folder_bound) if len(X) else {}
    gray = subject_matches(verdicts, shas)
    unknown = unknown_files(verdicts, scenes)
    rate_budget = budget_for(len(paths), rate, cfg)
    # Naming is a second consumer of the see-budget: every folder needs >= 1
    # viewed image, so the guaranteed picks are a FLOOR on the budget, not an
    # overflow of it (they stay inside the total, exempt only from rung 1's
    # quota). Reported as a cost figure below.
    budget = min(len(paths), max(rate_budget, len(guaranteed)))
    selected, trace = run_ladder(X, cluster_labels, shas, budget,
                                 cfg.get("gray_zone_always_seen", True),
                                 guaranteed=guaranteed, gray=gray,
                                 unknown=unknown,
                                 registry_subjects=usable_subjects)
    seen_idx = {i for i, _rung, _why in selected}
    row_of = {r["SourceFile"]: r for r in pool_rows}

    silent_recognisers = registry.identity_silent_recognisers

    screenshot_bucket = photo_profile.buckets(profile)["screenshots"]
    # Read from the PACK this run already resolved, never re-resolved here:
    # the isolation invariant is one owner's pack per run, and a second
    # lookup is a second chance to load a different one.
    what_reference = photo_profile.what_reference(pack)
    suspects = [paths[i] for i in range(len(paths))
                if scenes[i] and scenes[i]["confident"]
                and scenes[i]["class"] == screenshot_bucket]

    return {
        "engine": "photo_see.py (VS-2 see controller)",
        "workdir": str(workdir),
        "batch": batch["batch"],
        "label": batch.get("label"),
        "from": batch["from"], "to": batch["to"],
        "index_identity": identity,
        "config": {
            "see_rate": rate, "pass": pass_name, "see_rate_source": rate_source,
            "see_floor": cfg["see_floor"], "see_cap": cfg["see_cap"],
            "gray_zone_always_seen": bool(cfg.get("gray_zone_always_seen", True)),
            "tau": tau, "budget": budget,
            "budget_from_rate": rate_budget,
            "rung1_budget_share": RUNG1_BUDGET_SHARE,
            "rung1_quota": rung1_quota(budget),
            "rung1_quota_note": (
                "F2/B1, swept on the benchmark replay with the naming carve-out "
                "live; the parameter measured flat, so this is a policy choice "
                "with a measured floor, not a tuned optimum"),
            "naming_carve_out": {
                "guaranteed_folder_picks": len(guaranteed),
                "with_named_subject": sum(1 for v in folder_bound.values() if v),
                "budget_lifted_by": max(0, budget - rate_budget),
                "note": ("clusters that become their own output folder keep a "
                         "rung-1 look outside the quota (N-4); the count is the "
                         "naming cost figure the DESIGN asks the replay to "
                         "report. 0 whenever the run's pack holds no subject "
                         "that forms its own folder"),
            },
            "scene_margin_accept": SCENE_MARGIN_ACCEPT,
            "outlier_max_sim": OUTLIER_MAX_SIM,
            "subject_registry": {
                "source": registry.source,
                "subjects": len(registry),
                "with_exemplars": sum(1 for s in registry.subjects if s.exemplars),
                # Not the same number since un-confirm: a withdrawn subject
                # keeps its evidence and recognises nothing with it.
                "recognising": len(registry.recognisers),
                "forms_own_folder": sum(1 for s in registry.subjects
                                        if s.forms_own_folder()),
                "thresholds": {k: registry.defaults[k] for k in
                               ("accept", "gray_low", "timeline_tolerance_days")},
                "note": ("accept/gray_low are the DESIGN's STARTING values "
                         "pending replay calibration, not tuned numbers; the "
                         "timeline gate reads each file's own EXIF capture date"),
            },
            # VS-3b. Reported whether or not it ran, and the two zero cases are
            # DIFFERENT: no index at all means this dump was never put through
            # photo_identity.py, while an index with no recognising subject
            # means the owner has confirmed nobody in the identity space yet.
            # A reader seeing "0 recognised" needs to know which.
            "subject_identity": {
                "index": (None if not id_index else
                          {"files": len(id_index),
                           "with_a_subject_in_frame": identity_rows,
                           "model": id_space.get("model_id"),
                           "detector": id_space.get("detector_id")}),
                "recognising": len(registry.identity_recognisers),
                # The other half of that number, and the run's only chance to
                # say it: these subjects the owner confirmed, and the identity
                # space cannot use any of them. Nothing else speaks at MATCH
                # time — `attach_exemplars()` speaks when an exemplar is
                # PROMOTED, which is the moment the identity vector was
                # refused, not the moment recognition needed it.
                #
                # By id, because a re-confirmation on a better frame is
                # addressed to an id; never a name, which would put an owner
                # fact in a report the engine writes.
                #
                # ⚠️ `pack_speaks_identity` is a sibling key and NOT a field
                # inside the list, because the cause is a PACK fact: with it
                # false, every recogniser is silent and that is ordinary (a
                # pack predating VS-3b, or one whose identity stage never
                # ran). With it true, a silent subject is the owner-actionable
                # defect. That is the finest split the records support —
                # `identity_embedding` is written the first time ANY exemplar
                # in the pack attaches a vector, and an exemplar whose vector
                # was refused records the refusal only in the memorize audit
                # log. ⛔ Never a refusal or a warning: the CLIP fallback is
                # the design, and a report that failed a run over it would
                # break every pre-VS-3b pack.
                "silent_recognisers": {
                    "count": len(silent_recognisers),
                    "subjects": [s.subject_id for s in silent_recognisers],
                },
                "pack_speaks_identity": bool(registry.identity_embedding),
                "thresholds": {k: registry.defaults.get(
                    k, photo_subjects.DEFAULT_THRESHOLDS[k])
                    for k in ("identity_floor", "identity_margin")},
                "note": ("the identity space decides RELATIVELY — a floor plus "
                         "a margin over the runner-up — where the CLIP space "
                         "uses one absolute cosine. Every verdict names the "
                         "`space` it was decided in; scores from the two are "
                         "not comparable. Absent index = the CLIP space alone, "
                         "which is the pre-VS-3b behaviour. `silent_recognisers` "
                         "are confirmed subjects the identity space holds no "
                         "vector for; read it with `pack_speaks_identity` — "
                         "false means this pack has no identity exemplars at "
                         "all and they are all silent for that reason, true "
                         "means these subjects' confirmed frames held no "
                         "detected subject and a re-confirmation on a clearer "
                         "frame is what fixes them"),
            },
        },
        "scene_labels": {
            "source": label_source, "classes": list(classes),
            "encoded": bool(labels_matrix is not None),
            "prompt_language": (label_meta or {}).get("prompt_language", "en"),
            "note": (None if labels_matrix is not None else
                     "no embed/scene-labels.json — the scene axis is OFF for this "
                     "run; rungs 1/3/5 still work. Run photo_embed.py "
                     "--scene-labels to switch it on."),
        },
        # D-F7 / D-F11 — the owner's own `[what]` phrases, put in front of
        # whoever writes this batch's labels.
        #
        # ⛔ DELIBERATELY BESIDE `scene_labels` AND NOT INSIDE IT, because the
        # contrast is the point. `scene_labels` is a CLOSED class set: a file
        # scores against it and the winner becomes a `clip-matched:` label,
        # which is a `[type]` word. This is an OPEN reference: it says how the
        # owner phrases things and constrains nothing. A reader who merged the
        # two would have rebuilt the defect — `[what]` re-printing `[type]`.
        #
        # ⛔ EMPTY IS THE CORRECT ANSWER FOR A NEW OWNER, and the note says so
        # in the report rather than only in a docstring: an empty list here is
        # not a missing dependency to go and fix (compare `scene_labels.note`
        # one key up, which IS one). No starter list ships, in any language —
        # that is what stops U2-06 recurring.
        "what_reference": {
            "phrases": what_reference,
            "source": ("owner pack (photo-entities.json: scenes)"
                       if what_reference else "none — the pack declares none"),
            "note": ("a REFERENCE, never a BOUNDARY (D-F11). A label is free "
                     "text and a phrase absent from this list is equally "
                     "valid; nothing validates `[what]` against it and "
                     "nothing may be added that does. Empty is correct for an "
                     "owner who has not confirmed any phrasing yet — the "
                     "engine ships no `[what]` vocabulary of its own, in any "
                     "language."),
        },
        "coverage": {
            "batch_files": len(rows), "preclass": exif_class,
            "pool": len(paths), "unembedded_in_pool": len(unembedded),
            "held_from_vision": held,
            "held_from_vision_note": (
                "kept out of the vision pool, never moved (F-jj): a no-camera "
                "still at a screen size the owner has not answered yet, or a "
                "still the document check flagged (a statement, a ticket, a "
                "form). Still copied and named with its batch."),
            "document_check_missing": sorted(document_unchecked),
            "unembedded_paths": sorted(unembedded),
            "clusters": len(reps),
            "exif_decided_note": (
                "screenshot/screen_record/no_exif files are decided by rules that "
                "already ship (ONB-12 filename, screen dimensions, D13) and never "
                "enter the see pool; this stage cannot weaken them"),
        },
        "clusters": [
            {"cluster": lid, "size": len(members),
             "representative": paths[medoid],
             "members": sorted(paths[m] for m in members)}
            for lid, members, medoid in reps],
        "selected": [
            {"path": paths[i], "sha256": shas[i], "rung": rung, "reason": why,
             "cluster": int(cluster_labels[i]),
             "cluster_size": int((cluster_labels == cluster_labels[i]).sum()),
             "time": row_of[paths[i]]["_dt"].strftime("%Y-%m-%d %H:%M"),
             "filetype": row_of[paths[i]].get("FileType"),
             "scene": scenes[i], "sample": None,
             "subject_match": accepted_match(verdicts[i] if i < len(verdicts)
                                             else None),
             "detections": detections_seen(detections, paths[i])}
            for i, rung, why in selected],
        "ladder": trace,
        "provisional": provisional_labels(paths, cluster_labels, scenes, seen_idx,
                                          medoid_of),
        "diagnostics": {
            "no_scene_signal": sum(1 for s in scenes if s and not s["signal"]),
            "clip_matched": sum(1 for s in scenes if s and s["confident"]),
            "screenshot_suspects": sorted(suspects),
            "screenshot_suspects_note": (
                f"zero-shot says {screenshot_bucket} on files the filename/dimension "
                "rules did not catch (Group 6 lesson). This is a FLAG for the "
                "operator and a raised see priority — it moves nothing (ONB-10: say "
                "whether a proposal moves files or only annotates)."),
            "scene_class_counts": count_classes(scenes),
            "subject_verdicts": count_verdicts(verdicts),
            # Which space each verdict was decided in. Reported beside the
            # verdicts and never folded into them: "0 accepts" means something
            # completely different when every file was judged in the CLIP
            # space, and the counts alone cannot say which happened.
            "subject_verdict_spaces": count_spaces(verdicts),
            "subject_questions": subject_questions(paths, verdicts),
            "subject_questions_note": (
                "cardinality is never auto-resolved — two subjects that both "
                "clear `accept` on one file are a 'one subject or two?' question "
                "with a contact sheet, never a merge. Answering them is the "
                "memory checkpoint's job, not this stage's."),
        },
        "samples_dir": None,
    }


def accepted_match(verdict):
    """-> what the registry already decided about this file, or None (R4).

    ⭐ This is the missing half of §2.1. `registry.match()` runs on every pool
    file and, when a confirmed subject clears its floor, the verdict names the
    `subject_id` — the exact string a decision has to carry for `[who]` to
    reach a folder name. Before R4 it reached `folder_bound_clusters()`, was
    counted in `diagnostics.subject_verdicts`, and was then dropped. In UAT01
    the agent had no per-file id to write back, so every decision it could
    honestly make said `subject_kind` and every folder said the class word.

    ⛔ REPORTED, never applied. Nothing here writes a subject onto a label,
    and since G7 no decision may either: a name reaches a label only through
    `photo_index.py identify`, where the agent views the photo and agrees and
    the view is recorded (L4). An accept that absorbed itself would be
    A19 — 24 sightings written onto a confirmed subject with nothing asked, 5
    of them wrong — moved one stage earlier, where it would name folders.

    Only ACCEPT is carried. `gray` and `question` already have their own
    channels (rung 2 and `subject_questions`), and a rejected or unmatched
    file has nothing to say."""
    if not verdict or verdict.get("verdict") != photo_subjects.VERDICT_ACCEPT:
        return None
    return {"subject_id": verdict.get("subject_id"),
            "name": verdict.get("name"), "kind": verdict.get("kind"),
            "score": verdict.get("score"), "space": verdict.get("space"),
            "note": ("the registry accepts this match. It is evidence, not a "
                     "decision: never write this subject_id into a decision — "
                     "a pet is named through `photo_index.py identify`, where "
                     "you view the photo and agree")}


def detections_seen(detections, path):
    """-> {"count": n, "kinds": [...]} for one file, or None when this file has
    no row in the identity index at all (R4).

    ⛔ None and `count: 0` are DIFFERENT answers and are never rendered the
    same. None is "the identity stage never looked at this file" — the
    ordinary state of a run with no `.venv` models. Zero is "it looked and
    found no animal", which is a real finding about the photograph.

    The count is what tells the agent how long the `subjects` list should be:
    a frame with two animals is two names to log (owner decision, 20260904),
    and nothing else in the report says a second one is there."""
    rows = detections.get(path)
    if rows is None:
        return None
    identified = [r for r, _vec in rows
                  if r.get("status") == photo_identity.STATUS_OK]
    kinds = [r.get("kind") for r in identified if r.get("kind")]
    if not identified:
        return {"count": 0, "kinds": []}
    # ⛔ A pre-R3a index states no `det_count`, and `len(identified)` is not a
    # substitute for it: that index holds the highest-scoring box only, so its
    # one row means "an animal was found", never "one animal was there".
    # Answering 1 would tell the agent to write a one-entry list about a frame
    # nothing has counted — the same wrong answer as a real solo frame, and
    # indistinguishable from it downstream. `photo_identity.load_existing()`
    # blanks the field for exactly this reason and re-detects on the next run.
    stated = identified[0].get("det_count")
    if stated in (None, ""):
        return {"count": None, "kinds": kinds,
                "note": ("this identity index predates per-detection rows and "
                         "cannot say how many animals the frame holds; "
                         "photo_identity.py re-detects the dump on its next run")}
    return {"count": int(stated), "kinds": kinds}


def count_spaces(verdicts):
    out = {}
    for v in verdicts:
        if v:
            key = v.get("space") or "clip"
            out[key] = out.get(key, 0) + 1
    return out


def count_verdicts(verdicts):
    """A flat tally, so the operator can see what the registry did without
    reading per-file rows. All zeros on an unbound run."""
    counts = {photo_subjects.VERDICT_ACCEPT: 0, photo_subjects.VERDICT_GRAY: 0,
              photo_subjects.VERDICT_QUESTION: 0, photo_subjects.VERDICT_NONE: 0}
    for verdict in verdicts or []:
        if verdict:
            counts[verdict["verdict"]] = counts.get(verdict["verdict"], 0) + 1
    return counts


def subject_questions(paths, verdicts):
    """One question per indistinguishable subject PAIR, not per file — a
    subject spanning many files must yield one question, not many. The files
    that raised it become its contact sheet."""
    grouped = {}
    for i, verdict in enumerate(verdicts or []):
        question = (verdict or {}).get("question")
        if not question:
            continue
        key = tuple(question["subject_ids"])
        entry = grouped.setdefault(key, {**question, "contact_sheet": []})
        entry["contact_sheet"].append(paths[i])
    for entry in grouped.values():
        entry["files"] = len(entry["contact_sheet"])
        entry["contact_sheet"] = sorted(entry["contact_sheet"])[:4]
    return [grouped[k] for k in sorted(grouped)]


def count_classes(scenes):
    counts = {}
    for s in scenes:
        if s:
            counts[s["class"]] = counts.get(s["class"], 0) + 1
    return dict(sorted(counts.items()))


def make_samples(report, out_dir):
    """Downscaled viewables for the picks — ONB-11: proportional downscale into
    the work dir, no crop, no aspect change, nothing written back to any file
    the owner keeps. The engine's one converter (`photo_embed.
    convert_to_thumbnail`), dispatched on the manifest FileType the entry
    carries — never on the filename suffix."""
    smp_dir = out_dir / "samples"
    smp_dir.mkdir(parents=True, exist_ok=True)
    failures, causes = [], {}
    for entry in report["selected"]:
        src = Path(entry["path"])
        stem = f"{entry['time'].replace(' ', '_').replace(':', '')}_{src.stem}"
        filetype = entry.get("filetype")
        made, cause = photo_embed.convert_to_thumbnail(
            entry["path"], smp_dir, stem, photo_embed.kind_of(filetype), filetype)
        entry["sample"] = made.name if made else None
        if made is None:
            failures.append(entry["path"])
            causes[cause] = causes.get(cause, 0) + 1
    report["samples_dir"] = str(smp_dir)
    report["sample_failures"] = sorted(failures)
    report["sample_failures_by_cause"] = dict(sorted(causes.items()))
    return report


# ------------------------------------------------------------------ apply ---

def decision_subjects(value, path=None):
    """-> the subjects ONE decision names, as a list, in the order given (R4).

    Three shapes, and deliberately only three:

      "a cat on a wall"                         a bare label decides no subject
      {"label": ..., "subject_id": "subj-0003"} one subject   (pre-R4, legal)
      {"label": ..., "subject_kind": "cat"}     one subject   (pre-R4, legal)
      {"label": ..., "subjects": [{...}, ...]}  one entry per DETECTED subject

    The list is what R3a's multi-box detection made expressible: a frame
    holding two animals is two subjects to name, never a frame to refuse
    (owner decision, 20260904). Order is the caller's and is preserved --
    `photo_plan` renders `[who]` in it.

    ⛔ A decision carrying `subjects` AND one of the singular keys is refused,
    not merged. Merging would have to pick an order between two statements
    that may name different animals, and the failure that produces -- a second
    animal quietly dropped, or one counted twice -- renders as a perfectly
    ordinary folder name. Refusing is loud; guessing is not."""
    if not isinstance(value, dict):
        return []
    listed, singular = value.get("subjects"), [k for k in photo_evidence.SUBJECT_KEYS
                                               if value.get(k)]
    where = f" for {path}" if path else ""
    if listed is not None and singular:
        raise AssertionError(
            f"decision{where} carries both `subjects` and {singular[0]!r}; these "
            "are two ways of saying who is in the frame and this stage will not "
            "choose between them. Use `subjects` alone.")
    if listed is None:
        listed = [{k: value[k] for k in photo_evidence.SUBJECT_KEYS
                   if value.get(k)}] if singular else []
    if not isinstance(listed, list):
        raise AssertionError(
            f"decision{where}: `subjects` is {type(listed).__name__}, not a list. "
            "One entry per detected subject, even when there is one.")
    out = []
    for item in listed:
        if not isinstance(item, dict) or not any(item.get(k)
                                                 for k in photo_evidence.SUBJECT_KEYS):
            raise AssertionError(
                f"decision{where}: every entry in `subjects` names a subject_id or "
                f"a subject_kind; got {item!r}")
        out.append({k: item[k] for k in photo_evidence.SUBJECT_KEYS if item.get(k)})
    return out


# A45 — how a re-apply decides between what it just computed and what the
# labels file already held. ⛔ Ranked, not boolean: the rule is "a weaker claim
# never overwrites a stronger one", and `viewed-image:` outranks everything
# because it is the only prefix that says a model actually opened the file.
PROVENANCE_STRENGTH = {photo_evidence.VIEWED: 3,
                       photo_evidence.CLIP_PROPAGATED: 2}


def claim_strength(entry):
    """How strong an entry's provenance claim is. -> int, higher is stronger.

    An unlabelled entry (`provenance: None`) is 0 — the third legal state, not
    a claim. Any other known prefix (`clip-matched:`) is 1."""
    prov = entry.get("provenance")
    return 0 if prov is None else PROVENANCE_STRENGTH.get(prov, 1)


def sample_key_hint(unknown, selected):
    """-> a diagnostic tail for decision keys that are really SAMPLE names.

    U3-28. `make_samples` names a sample `{time}_{src.stem}` and gives it the
    extension `photo_embed.convert_to_thumbnail` actually produced -- `.jpg` for
    every still it converts, `.png` for a video's frame -- so a
    sample filename is derived TWICE over and is never the source's own name.
    An agent that keys its decisions off `samples/` therefore hands us a path
    the see-list has never heard of, and the bare "never selected" message
    blames the SELECTION, which is the one thing that is not wrong: the
    controller did pick that file.

    We still refuse -- accepting a key whose extension does not match would be
    guessing which file was meant, the silent wrong-file class this engine
    refuses everywhere -- but we refuse ACCURATELY, naming the key to use. A
    stem that matches two selected files (`IMG_1.MOV` beside `IMG_1.JPG`) is
    reported as ambiguous rather than resolved, for the same reason."""
    by_stem = {}
    for entry in selected:
        for cand in (entry["path"], entry.get("sample")):
            if cand:
                by_stem.setdefault(Path(cand).stem.lower(), set()).add(entry["path"])
    lines = []
    for key in unknown:
        hits = sorted(by_stem.get(Path(key).stem.lower(), ()))
        if len(hits) == 1:
            lines.append(f"{key} -> {hits[0]}")
        elif hits:
            lines.append(f"{key} -> AMBIGUOUS, matches: " + ", ".join(hits))
    if not lines:
        return ""
    # Truncated at the same 5 as the message this appends to: an agent that
    # keyed EVERY decision off samples/ mis-keys the whole see-list, and one
    # half of a message disagreeing with the other about truncation is its
    # own small lie.
    extra = len(lines) - 5
    lines = lines[:5] + ([f"(+{extra} more)"] if extra > 0 else [])
    return ("\nThose look like SAMPLE filenames, not source paths. A decision "
            "key MUST be see-report.json's `selected[].path`, verbatim: a "
            "sample's name is time-prefixed and carries the THUMBNAIL's "
            "extension (.jpg for stills, .png for video), so it cannot be "
            "turned back into a source path. Use instead:\n  "
            + "\n  ".join(lines))


def apply_decisions(report, decisions, samples_dir, existing=None):
    """Merge what the vision model said back onto the batch.

    `decisions` is {path: label} (or {path: {"label": ..., "note": ...}}) for
    files the model actually looked at. Only see-list paths with a thumbnail
    on disk may become `viewed-image:`; a decision for anything else is
    rejected loudly rather than absorbed. Every cluster member of a viewed
    file inherits its label as `clip-propagated:` — one look, a whole cluster
    labeled, which is the whole point of the stage.

    **Two looks at one cluster that disagree are FLAGGED, not dropped (F12).**
    This is not a rare race: rung 5 only runs when every cluster already has a
    representative, so every rung-5 pick is a second look at an
    already-represented cluster (all 28 of the VS-2 build's 28). The winner is
    still deterministic — the lowest-sorted path, as before, so propagation
    does not change — but each losing label lands in
    `report["cluster_label_conflicts"]` and in the --apply output. Each file
    that WAS looked at keeps its own `viewed-image:` label either way; what
    used to be discarded silently is the disagreement itself, which is exactly
    the signal a second look was spent to obtain.

    **A45 — `existing` makes a re-apply NON-DESTRUCTIVE.** This function builds
    one entry per POOL FILE from the CURRENT report, so a second `--apply` on a
    batch whose selection has moved used to overwrite the labels of frames that
    fell off the new see-list. Measured on a real dump: a `viewed-image:` frame
    carrying the agent's own phrase came back as `clip-matched:` holding a
    zero-shot class word, at exit 0, and `[who]` is only legal under N-4
    because a model looked — so the downgrade removed the evidence that permits
    a name while leaving a plausible label in place. ⛔ And it is unrepairable:
    the assertion above refuses a decision for a path the current report did
    not select, so the lost look cannot be re-stamped.

    Pass the labels file's current entries as `existing` and a prior claim is
    kept whenever the newly computed one is STRICTLY WEAKER (`claim_strength`).
    Two consequences, both deliberate:

      * **a fresh decision always wins**, including a re-look that disagrees —
        equal or stronger replaces, so re-applying is still how a label is
        corrected. Only a WEAKER claim is refused;
      * ⛔ **a `clip-matched:` entry can never overwrite a `viewed-image:` one.**
        That single case is this whole defect.

    A kept entry is stamped `preserved: True`. ⛔ NOT a new provenance prefix:
    `photo_evidence.VISUAL_PROVENANCE` is a closed vocabulary of three and
    `photo_plan` refuses a fourth by name, so the fact travels as its own key
    and every existing reader is unaffected.

    ⚠️ Only paths in the CURRENT pool are preserved. A file that left the pool
    changed tier or class, and silently resurrecting its label would be a
    different defect from this one."""
    seen = {e["path"]: e for e in report["selected"]}
    # ⛔ G7 (item 5, closed) — a decision may not NAME a pet. Measured on a real
    # dump: a `subject_id` written here landed on a stranger's label at
    # `viewed-image:`, named its folder, passed check and, with --memorize,
    # became the pet's exemplar — no recognition, no record. A name reaches a
    # label only through `photo_index.py identify` (views, records, trains
    # nothing) or the owner's own pages. `subject_kind` is unchanged.
    naming = sorted(path for path, value in decisions.items()
                    if isinstance(value, dict) and (
                        value.get("subject_id") or any(
                            isinstance(s, dict) and s.get("subject_id")
                            for s in (value.get("subjects")
                                      if isinstance(value.get("subjects"), list)
                                      else []))))
    if naming:
        raise AssertionError(
            "decisions name a subject_id for " + ", ".join(naming[:5])
            + (f" (+{len(naming) - 5} more)" if len(naming) > 5 else "")
            + " — nothing was written. A pet's name is never written by a "
            "decision: write `subject_kind` here, and name pets through "
            "`photo_index.py identify <work dir>`, which proposes the name from "
            "recognition, has you view the photo and agree, and records the view.")
    unknown = sorted(set(decisions) - set(seen))
    if unknown:
        raise AssertionError(
            "decisions name files the see controller never selected, so nothing "
            "looked at them: " + ", ".join(unknown[:5])
            + (f" (+{len(unknown) - 5} more)" if len(unknown) > 5 else "")
            + sample_key_hint(unknown, report["selected"]))

    cluster_of = {}
    for c in report["clusters"]:
        for member in c["members"]:
            cluster_of[member] = c["cluster"]
    label_by_cluster, viewed, conflicts = {}, {}, []
    subject_by_cluster = {}
    for path, value in sorted(decisions.items()):
        label = value["label"] if isinstance(value, dict) else value
        note = value.get("note") if isinstance(value, dict) else None
        # WHO travels with the label, and by the same rules: what the model
        # said about the file it looked at, propagated to that file's visual
        # cluster and marked as propagated. A subject the model could not
        # identify carries its class only — never an invented name.
        #
        # R4: a LIST, one entry per detected subject, because R3a made a frame
        # able to hold more than one. The whole list propagates together — a
        # cluster's members are the same scene, so if the representative held
        # two animals its members are claimed to hold the same two, at the
        # same `clip-propagated:` strength the label already travels at.
        subjects = decision_subjects(value, path)
        viewed[path] = {"label": label, "note": note,
                        "sample": seen[path].get("sample"), "subjects": subjects}
        cid = cluster_of.get(path)
        if cid is not None and subjects and cid not in subject_by_cluster:
            subject_by_cluster[cid] = (subjects, path)
        if cid is None:
            continue
        if cid not in label_by_cluster:
            label_by_cluster[cid] = (label, path)
            continue
        won_label, won_path = label_by_cluster[cid]
        if won_label != label:
            conflicts.append({
                "cluster": cid, "propagated": won_label, "from": won_path,
                "disagreeing": label, "seen_as": path,
                "rung": seen[path].get("rung"),
                "note": ("two viewed files in one visual cluster returned "
                         "different labels; the lower-sorted path propagates and "
                         "both keep their own viewed-image: label. The cluster "
                         "may be two things (F12)")})
    conflicts.sort(key=lambda c: (c["cluster"], c["seen_as"]))
    report["cluster_label_conflicts"] = conflicts

    entries = []
    for prov in report["provisional"]:
        path = prov["path"]
        cid = cluster_of.get(path)
        subjects, subject_provenance = [], None
        if cid in subject_by_cluster:
            subjects, source = subject_by_cluster[cid]
            subject_provenance = (photo_evidence.VIEWED if source == path
                                  else photo_evidence.CLIP_PROPAGATED)
        if path in viewed:
            entries.append({"path": path, "label": viewed[path]["label"],
                            "provenance": photo_evidence.VIEWED,
                            "sample": viewed[path]["sample"],
                            "note": viewed[path]["note"],
                            "subjects": subjects,
                            "subject_provenance": subject_provenance})
            continue
        if cid in label_by_cluster:
            label, source = label_by_cluster[cid]
            entries.append({"path": path, "label": label,
                            "provenance": photo_evidence.CLIP_PROPAGATED,
                            "from": source, "subjects": subjects,
                            "subject_provenance": subject_provenance})
            continue
        entries.append({"path": path, "label": prov["label"],
                        "provenance": prov["provenance"],
                        "from": prov.get("from"), "subjects": subjects,
                        "subject_provenance": subject_provenance})
    if existing:
        prior = {e.get("path"): e for e in existing}
        kept = []
        for entry in entries:
            was = prior.get(entry["path"])
            if was is not None and claim_strength(was) > claim_strength(entry):
                entry = {**was, "preserved": True}
            elif was is not None:
                entry = carry_recorded_names(was, entry)
            kept.append(entry)
        entries = kept
    entries.sort(key=lambda e: e["path"])
    # A preserved claim is allowed past the see-list test and NOTHING else:
    # `viewed_claim_problems` still requires its thumbnail to be present, to be
    # a real image, and not to be another file's. See that function for why the
    # thumbnail is the load-bearing evidence once the see-list has moved.
    assert_no_fabrication(entries, set(seen), samples_dir, report=report)
    return entries


def carry_recorded_names(was, entry):
    """G7 (the Lead's A45 addition) — a re-apply keeps the names already
    RECORDED on a frame: the owner's page picks (U-3's `subject_id` /
    `subject_ids`) and the agent's viewed agreements (`identified`).

    Measured on a real dump before this existed: re-applying a batch's own
    decisions after its page was confirmed dropped every recorded name, at
    exit 0 — `[who]` gone from the folder with a valid label left in place.
    A decision never carries a `subject_id` (G7 closed that route), so any id
    on the prior entry is a recorded decision, and a fresh look at the frame
    has no way to restate it. Only on a frame that is still VIEWED: a name is
    never carried onto a propagated label."""
    if not photo_evidence.is_view_confirmed(entry.get("provenance")):
        return entry
    ids = [s.get("subject_id") for s in photo_evidence.subject_list(was)
           if s.get("subject_id")]
    picked, marks = was.get("subject_ids"), was.get("identified")
    if not (ids or picked or marks):
        return entry
    entry = dict(entry)
    if ids and not any(s.get("subject_id")
                       for s in photo_evidence.subject_list(entry)):
        subjects = [dict(s) for s in entry.get("subjects") or []]
        for i, subject_id in enumerate(ids):
            if i < len(subjects):
                subjects[i]["subject_id"] = subject_id
            else:
                subjects.append({"subject_id": subject_id})
        entry["subjects"] = subjects
        entry.pop("subject", None)
    if picked:
        entry["subject_ids"] = list(picked)
    if marks:
        entry["identified"] = list(marks)
    # G7h — a carried name rests on the view, even where the fresh look's
    # cluster left the subject at `clip-propagated:`.
    entry["subject_provenance"] = photo_evidence.VIEWED
    return entry


def record_confirmed_subject_ids(workdir, picks, views=None):
    """U-3 — write the owner's own naming decision onto the frames it was about.

    `picks` is [(sample path relative to the work dir, subject_id)] — exactly
    the frames the owner picked on a review page, and nothing else. Returns a
    report; writes only when something changed.

    ⭐ **This RECORDS a decision, it does not MAKE one.** No matching runs, no
    selection moves, no model is called. The frames are already in
    `see-labels.json` carrying `viewed-image:`, so the only thing missing on
    those rows is which subject the owner said they are.

    ⛔ **Why it lives here and not in `photo_memory`.** A45 established that
    `apply_decisions()` is the SOLE WRITER of `see-labels.json`, and
    `photo_evidence.viewed_claim_problems()` states that as the constraint its
    `preserved` exemption rests on. A second writer in another module would
    have broken it. This function is that writer, kept inside `photo_see` so
    the file still has one owning module — and ⛔ it NEVER sets `preserved`,
    never touches `provenance`, `label`, `sample` or `from`, and writes only
    to rows that already exist: the name, the agent's view ids, and (G7h) a
    `subject_provenance` of bare `viewed-image:` on a VIEWED frame, because the
    name now rests on that view.

    ⛔ **A frame naming MORE THAN ONE subject is SKIPPED, not guessed.** The
    owner picked a FRAME, and a frame holding two animals does not say which
    of them they meant: `vec_ref` is the file's content sha with no
    per-detection key (C10), so there is nothing to attribute it to. Guessing
    the first detection would be A19 at one-frame scale, and it would be
    guessing in the one place the owner had just been explicit. Reported
    instead.
    """
    workdir = Path(workdir)
    views = {(str(Path(k[0])), k[1]): v for k, v in (views or {}).items()}
    wanted = {}
    for sample_rel, subject_id in picks:
        rel = Path(sample_rel)
        # `<batch dir>/samples/<file>` — the batch dir is what names the pair
        # of artifacts, so it is read off the path rather than parsed out of
        # the file name (which is the owner's photo, and formats vary).
        if rel.parent.name != "samples":
            continue
        # A LIST per frame: one frame picked on two rows is two names (R6).
        ids = wanted.setdefault(rel.parent.parent, {}).setdefault(rel.name, [])
        if subject_id not in ids:
            ids.append(subject_id)

    written, skipped_multi, unresolved, outside = [], [], [], []
    replaced = []
    root = workdir.resolve()
    for batch_rel, by_sample in sorted(wanted.items()):
        batch_dir = workdir / batch_rel
        # ⛔ L7 (G7) — a page's `frames:` line can hold an ABSOLUTE sample path
        # (`photo_memory.look_image()` when the look was memorized in another
        # work dir), and `workdir / <absolute>` IS that absolute path. On a
        # copied work dir this wrote the owner's names into the SOURCE's
        # labels and left the copy's own unchanged, silently. Refused, by path.
        try:
            batch_dir.resolve().relative_to(root)
        except ValueError:
            outside += [f"{batch_rel}/samples/{s}" for s in sorted(by_sample)]
            continue
        report_path, labels_path = (batch_dir / "see-report.json",
                                    batch_dir / "see-labels.json")
        if not (report_path.is_file() and labels_path.is_file()):
            unresolved += [f"{batch_rel}/samples/{s}" for s in sorted(by_sample)]
            continue
        report = json.loads(report_path.read_text())
        # sample -> the SOURCE file it was made from. The see report is the
        # only thing that knows this pairing; the labels file is keyed by
        # source path and the review page names the sample.
        source_of = {e.get("sample"): e.get("path")
                     for e in report.get("selected") or [] if e.get("sample")}
        doc = json.loads(labels_path.read_text())
        entries = doc.get("labels") or []
        by_path = {e.get("path"): e for e in entries}
        changed = False
        for sample, subject_ids in sorted(by_sample.items()):
            source = source_of.get(sample)
            entry = by_path.get(source) if source else None
            if entry is None:
                unresolved.append(f"{batch_rel}/samples/{sample}")
                continue
            subjects = photo_evidence.subject_list(entry)
            if len(subjects) > 1 or len(subject_ids) > 1:
                # ⭐ G6 R6 (owner amendment 20260904): two subjects in one frame
                # is TWO NAMES TO LOG, never a frame to refuse. Every name the
                # owner picked for this frame is written at FRAME level
                # (`subject_ids`), never bound to a detection box — which box
                # is which animal is exactly what the frame cannot say (C10).
                # ⛔ Only the picked names; nothing is matched. The exemplar
                # refusal on `det_count > 1` is untouched.
                have = list(entry.get("subject_ids") or [])
                merged = have + [s for s in subject_ids if s not in have]
                if merged != have:
                    entry["subject_ids"] = merged
                    written.extend((source, s) for s in subject_ids
                                   if s not in have)
                    changed = True
                continue
            subject_id = subject_ids[0]
            current = dict(subjects[0]) if subjects else {}
            if current.get("subject_id") == subject_id:
                continue                        # idempotent — already recorded
            if current.get("subject_id"):
                # FIX7 (U7-1) — the id this write replaces is otherwise lost;
                # the caller audits it so a detach can put it back.
                replaced.append({"path": source, "replaced": current["subject_id"],
                                 "subject_id": subject_id,
                                 "sample": f"{batch_rel}/samples/{sample}"})
            current["subject_id"] = subject_id
            # ⛔ Written into the R4 `subjects` list, and the pre-R4 `subject`
            # key is dropped in the same move. `subject_list()` reads
            # `subjects` FIRST, so leaving both would keep a stale singular
            # around that nothing reads and that disagrees with what is read.
            entry["subjects"] = [current]
            entry.pop("subject", None)
            written.append((source, subject_id))
            changed = True
        for sample, subject_ids in sorted(by_sample.items()):
            # G7 — a name the AGENT agreed to after viewing carries its view
            # record's id (`identified`). Provenance stays bare (L1): the key
            # is what render and check read, never a prefix.
            source = source_of.get(sample)
            entry = by_path.get(source) if source else None
            if entry is None or not views:
                continue
            marks = list(entry.get("identified") or [])
            for subject_id in subject_ids:
                view = views.get((str(Path(batch_rel) / "samples" / sample), subject_id))
                if view and not any(m.get("view") == view for m in marks):
                    marks.append({"subject_id": subject_id, "view": view})
            if marks != list(entry.get("identified") or []):
                entry["identified"] = marks
                changed = True
        for sample in by_sample:
            # G7h — a name recorded on a VIEWED frame rests on that view (N-4),
            # by the owner's pick or the agent's agreement alike. A cluster
            # conflict can leave the entry's `subject_provenance` at
            # `clip-propagated:`, and render's gate then dropped the name from
            # `[who]` in silence (measured on mix1: F019, both paths).
            source = source_of.get(sample)
            entry = by_path.get(source) if source else None
            if (entry is not None
                    and photo_evidence.is_view_confirmed(entry.get("provenance"))
                    and entry.get("subject_provenance") != photo_evidence.VIEWED):
                entry["subject_provenance"] = photo_evidence.VIEWED
                changed = True
        if changed:
            doc["labels"] = entries
            doc["subject_ids_recorded_at"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M")
            labels_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    return {"written": written, "skipped_multi_subject": skipped_multi,
            "unresolved": unresolved, "outside_workdir": outside,
            "replaced": replaced}


def subjects_held(workdir, sample_rels):
    """FIX8 F8-1 — what each picked frame's photo names NOW, read only.

    -> {sample rel: (source path, [subject ids])}, resolved exactly as
    `record_confirmed_subject_ids()` resolves a pick; a frame that writer would
    skip (outside the work dir, no see output, no entry) is left out, so a line
    is never printed for a write that will not happen."""
    workdir = Path(workdir)
    root = workdir.resolve()
    out, reports, labels = {}, {}, {}
    for sample_rel in sample_rels:
        rel = Path(sample_rel)
        if rel.parent.name != "samples":
            continue
        batch_dir = workdir / rel.parent.parent
        try:
            batch_dir.resolve().relative_to(root)
        except ValueError:
            continue
        if batch_dir not in reports:
            report_path, labels_path = (batch_dir / "see-report.json",
                                        batch_dir / "see-labels.json")
            if not (report_path.is_file() and labels_path.is_file()):
                reports[batch_dir] = None
            else:
                reports[batch_dir] = {
                    e.get("sample"): e.get("path") for e in
                    json.loads(report_path.read_text()).get("selected") or []
                    if e.get("sample")}
                labels[batch_dir] = {
                    e.get("path"): e for e in
                    json.loads(labels_path.read_text()).get("labels") or []}
        if reports[batch_dir] is None:
            continue
        source = reports[batch_dir].get(rel.name)
        entry = labels[batch_dir].get(source) if source else None
        if entry is None:
            continue
        ids = [s.get("subject_id") for s in photo_evidence.subject_list(entry)
               if s.get("subject_id")]
        ids += [s for s in entry.get("subject_ids") or [] if s not in ids]
        out[sample_rel] = (source, ids)
    return out


def restore_choice(entry, from_id, draft_id, into=None, prior=None):
    """-> (subject_id, why) for one frame a detach takes back from `from_id`.

    The order is the ruling's: `--into` when the owner named one; else the
    agent's own agree on this frame (`identified`), which the confirm
    overwrote but never removed; else the id the confirm replaced, read off
    the memorize audit; else the released draft itself. ⛔ Two different
    agrees on one frame are not chosen between — that falls through, said,
    never guessed."""
    if into:
        return into, "the subject named with --into"
    agreed = []
    for mark in entry.get("identified") or []:
        sid = mark.get("subject_id")
        if sid and sid != from_id and sid not in [a[0] for a in agreed]:
            agreed.append((sid, mark.get("view")))
    if len(agreed) == 1:
        return agreed[0][0], f"the agent's agree ({agreed[0][1]})"
    if prior and prior != from_id:
        return prior, "the id the confirm replaced"
    return draft_id, "the released draft"


def restore_detached_subject_ids(looks, from_id, draft_id, into=None,
                                 replaced=None, workdir=None, dry_run=False):
    """FIX7 (U7-1) — take back what `record_confirmed_subject_ids()` wrote for
    ONE wrongly joined draft. -> a report; writes only when not `dry_run`.

    `looks` are the draft's looks the owner PICKED on the joining row (the
    memorize audit's `attached` vec_refs), each carrying the work dir, batch
    and source path it was seen at. Only an entry that still names `from_id`
    is touched: one that has moved on since is reported and left alone.

    ⛔ Lives here for `record_confirmed_subject_ids()`'s reason: every writer
    of `see-labels.json` stays in this module (A45,
    `photo_evidence.viewed_claim_problems()`). It sets a `subject_id` and
    nothing else — never `preserved`, `provenance`, `label`, `sample` or
    `from`, and it removes no view record.

    ⛔ L7's guard, one verb along: a batch dir outside `workdir` (or, with no
    work dir named, outside the look's own) is refused by path, so a copied
    work dir never writes into the source's labels."""
    replaced = replaced or {}
    by_labels, unresolved, outside = {}, [], []
    for look in looks:
        source = look.get("path")
        base = workdir or look.get("workdir")
        if look.get("see_report"):
            batch_dir = Path(look["see_report"]).parent
        elif look.get("workdir") and look.get("batch") is not None:
            batch_dir = (Path(look["workdir"]) / "classify"
                         / f"batch-{int(look['batch']):02d}")
        else:
            unresolved.append(source)
            continue
        if base is None:
            unresolved.append(source)
            continue
        try:
            batch_dir.resolve().relative_to(Path(base).resolve())
        except ValueError:
            outside.append(str(batch_dir / "see-labels.json"))
            continue
        labels_path = batch_dir / "see-labels.json"
        if not labels_path.is_file():
            unresolved.append(source)
            continue
        by_labels.setdefault(labels_path, []).append(source)

    restored, moved_on = [], []
    for labels_path, sources in sorted(by_labels.items()):
        doc = json.loads(labels_path.read_text())
        entries = doc.get("labels") or []
        by_path = {e.get("path"): e for e in entries}
        changed = False
        for source in sources:
            entry = by_path.get(source)
            if entry is None:
                unresolved.append(source)
                continue
            picked = list(entry.get("subject_ids") or [])
            if from_id in picked:
                # A frame with 2+ animals holds the owner's names at FRAME
                # level (R6); only the wrong one leaves, nothing is chosen.
                kept = [s for s in picked if s != from_id]
                if into and into not in kept:
                    kept.append(into)
                entry["subject_ids"] = kept
                restored.append({"labels": str(labels_path), "path": source,
                                 "old": from_id, "new": into,
                                 "why": "a name on a photo with 2+ animals"})
                changed = True
                continue
            subjects = photo_evidence.subject_list(entry)
            if not subjects or subjects[0].get("subject_id") != from_id:
                moved_on.append({"labels": str(labels_path), "path": source,
                                 "now": subjects[0].get("subject_id")
                                 if subjects else None})
                continue
            new_id, why = restore_choice(entry, from_id, draft_id, into,
                                         replaced.get(source))
            current = dict(subjects[0])
            current["subject_id"] = new_id
            entry["subjects"] = [current] + [dict(s) for s in subjects[1:]]
            entry.pop("subject", None)
            restored.append({"labels": str(labels_path), "path": source,
                             "old": from_id, "new": new_id, "why": why})
            changed = True
        if changed and not dry_run:
            doc["labels"] = entries
            doc["subject_ids_restored_at"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M")
            labels_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    return {"restored": restored, "moved_on": moved_on,
            "unresolved": unresolved, "outside_workdir": outside}


def identify_proposals(workdir, pack, decided=()):
    """G7 (D-I11) — what recognition PROPOSES for the agent to view. -> (offered,
    not_offered), both lists of rows; nothing is written.

    Only a VIEWED frame is looked at: a see-list entry whose thumbnail is on
    disk and whose label carries a bare `viewed-image:` — the evidence N-4
    needs under a name. A frame already naming a CONFIRMED subject has been
    spoken for (a page or an earlier identify) and is skipped, and so is a
    (file, subject) in `decided`: any verdict the agent recorded before.

    ⭐ Scored PER DETECTION, not per file: `photo_identity.load_detections()`
    holds a vector for every box, and a frame with two animals can propose two
    names (L6). Two boxes proposing the SAME name offer it once, on the
    higher-scoring box; the other box stays unnamed.

    ⛔ Offered: an ACCEPT decided in the IDENTITY space, nothing else. A `clip`
    accept, a `gray` and a `question` are listed in `not_offered` with their
    space and never put to the agent — measured on a real dump, a stranger's
    score sits inside a pet's band in identity space, so the view is the
    guard, and a weaker space would hand it more strangers to catch.
    ⛔ Nothing here is an exemplar, and nothing moves a record (L3)."""
    import numpy as np

    workdir = Path(workdir)
    registry = photo_subjects.load(pack=pack)
    if not registry.recognisers:
        return [], []
    index, identity = load_index(workdir)
    detections, id_space = photo_identity.load_detections(workdir / "embed",
                                                          pack)
    decided = set(decided)
    skipped_on = owner_skipped(registry)
    offered, not_offered = [], []
    for bdir in sorted((workdir / "classify").glob("batch-*")):
        report_path, labels_path = bdir / "see-report.json", bdir / "see-labels.json"
        if not (report_path.is_file() and labels_path.is_file()):
            continue
        report = json.loads(report_path.read_text())
        labels = {e.get("path"): e for e in
                  json.loads(labels_path.read_text()).get("labels") or []}
        batch = int(report.get("batch") or bdir.name.split("-")[1])
        for sel in report.get("selected") or []:
            path, sample = sel.get("path"), sel.get("sample")
            entry = labels.get(path)
            if (not sample or not (bdir / "samples" / sample).is_file()
                    or path not in index or entry is None
                    or not photo_evidence.is_view_confirmed(entry.get("provenance"))):
                continue
            named = list(entry.get("subject_ids") or []) + [
                s.get("subject_id") for s in photo_evidence.subject_list(entry)
                if s.get("subject_id")]
            if any((registry.get(sid) is not None and
                    registry.get(sid).status == photo_subjects.STATUS_CONFIRMED)
                   for sid in named):
                continue
            try:
                when = datetime.strptime(sel.get("time") or "", "%Y-%m-%d %H:%M")
            except ValueError:
                when = None
            boxes = [(r, v) for r, v in detections.get(path, [])
                     if r.get("status") == photo_identity.STATUS_OK]
            if boxes:
                X = np.stack([index[path][1]] * len(boxes)).astype(np.float32)
                verdicts = registry.match(
                    X, [when] * len(boxes), identity,
                    X_identity=np.stack([v for _r, v in boxes]).astype(np.float32),
                    identity_space=id_space)
                count = boxes[0][0].get("det_count")
                det_count = int(count) if count not in (None, "") else len(boxes)
                scored = [(int(r.get("det_index") or 0), v)
                          for (r, _v), v in zip(boxes, verdicts)]
            else:
                verdicts = registry.match(index[path][1][None, :].astype(np.float32),
                                          [when], identity)
                det_count = 0 if path in detections else None
                scored = [(None, verdicts[0])]
            best = {}
            for det_index, v in scored:
                if (not v or not v.get("subject_id")
                        or v["verdict"] == photo_subjects.VERDICT_NONE):
                    continue
                row = {"batch": batch, "path": path,
                       "sample": f"classify/{bdir.name}/samples/{sample}",
                       "subject_id": v["subject_id"], "name": v.get("name"),
                       "verdict": v["verdict"], "space": v.get("space"),
                       "score": v.get("score"), "lead": v.get("lead"),
                       "runner_up": v.get("runner_up"), "det_index": det_index,
                       "det_count": det_count}
                if not (v["verdict"] == photo_subjects.VERDICT_ACCEPT
                        and v.get("space") == "identity"):
                    not_offered.append(row)
                    continue
                # F-q (Card 6, Lead ruling 20260924): a sighting the owner
                # SKIPPED on a page is `rejected`, basis not-mine — "this is
                # not my animal". A one-animal photo IS that animal: never
                # offered, listed with the reason. A photo with 2+ animals is
                # still offered PER ANIMAL (D-24 / G6-6): the skip was recorded
                # per photo (vec_ref, no det_index — C10), so it cannot say
                # which animal was meant, and the row says so instead.
                page = skipped_on.get(path)
                if page and det_count == 1:
                    row["reason"] = f"the owner skipped this animal on {page}"
                    not_offered.append(row)
                    continue
                if page:
                    row["skipped_on"] = page
                if (path, v["subject_id"]) in decided:
                    continue
                held = best.get(v["subject_id"])
                if held is None or (row["score"] or 0) > (held["score"] or 0):
                    best[v["subject_id"]] = row
            offered.extend(sorted(best.values(), key=lambda r: r["det_index"] or 0))
    return offered, not_offered


def owner_skipped(registry):
    """-> {file path: the page it was skipped on} for every look of a subject
    the owner REJECTED (a page `skip:`). A revived subject is a draft again
    and drops out of this by its status alone."""
    out = {}
    for subject in registry.subjects:
        if subject.status != photo_subjects.STATUS_REJECTED:
            continue
        src = ((subject.record.get("rejected") or {}).get("src") or "").split(".md")[0]
        for block in subject.record.get("evidence") or []:
            for look in block.get("looks") or []:
                if look.get("path"):
                    out.setdefault(look["path"], src or "a page")
    return out


def batches_with_labels(workdir):
    """U-3's second half — every batch that holds applied see-labels.

    ⚠️ The caller subtracts the batches this confirmation just wrote into, and
    reports the rest: those hold labels that predate the naming, so any file
    the owner did not pick keeps its class word. Reported so partial coverage
    is VISIBLE — without it an empty `[who]` reads as a defect rather than as
    the system declining to guess.

    ⛔ Deliberately NOT a timestamp comparison. Every labels file on disk was
    written before any confirmation that follows it, so "older than now" is
    true of all of them and says nothing; what the owner needs to know is
    which batches gained nothing THIS time. -> sorted batch directory names."""
    return sorted(path.parent.name for path
                  in Path(workdir).glob("classify/batch-*/see-labels.json"))


# ---------------------------------------------------------- the memorize ----

def away_gate(workdir, profile):
    """Q8-a — -> a function (member paths) -> True when those photos must be
    ASKED about rather than filed onto a confirmed subject.

    A cluster is near home when ANY member's OWN GPS sits within the home
    range of ANY registered home on its own capture day — `home_range: false`
    homes included, because a relative's house is still somewhere the owner's
    pets are. Everything else is asked, and that includes a cluster with no
    GPS at all: a question is the visible failure, a silent file the hidden
    one, and the batch's place is never borrowed for a file that has none
    (F-12 — a no-GPS home video inside a trip batch is exactly the trap).

    The range is the one this RUN cut its batches with (`batches.json`), so
    the gate cannot disagree with the day types beside it; the pack's value,
    then the shipped default, only when the run recorded none."""
    import photo_cluster
    rows = {}
    for name in ("manifest.csv", "no-date-files.csv"):
        path = Path(workdir) / name
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                rows.update((r["SourceFile"], r) for r in csv.DictReader(f))
    km = None
    batches = Path(workdir) / "batches.json"
    if batches.exists():
        km = json.loads(batches.read_text(encoding="utf-8")).get("away_km")
    if km is None:
        km = photo_profile.get(profile, "cluster_defaults", "away_km",
                               default=photo_cluster.AWAY_KM_DEFAULT)
    km = float(km)
    homes = photo_profile.home_points(profile)

    def asks(members):
        for member in members:
            row = rows.get(member)
            point = photo_cluster.parse_gps(row) if row else None
            if point is None:
                continue
            when = parse_date(row)
            day = when.date().isoformat() if when else ""
            if photo_cluster.within_home_range(point, day, homes, km):
                return False
        return True
    return asks


def memorize_batch(report, decisions, entries, index, identity, pack,
                   samples_dir, run_id=None, workdir=None):
    """VS-4's memorize loop, run at `--apply` because this is the one moment
    the evidence is all in one place.

    Two things happen, and only one of them touches the exemplar store:

      * a decision naming a `subject_id` is a vision-confirmed MATCH → the
        file's vector is promoted to that subject's exemplars (⛔ since G7
        `--apply` refuses such a decision before this runs, so from the CLI
        this branch is unreachable; callers that pass one directly remain), carrying the
        see-report, batch and thumbnail that prove the look. `add_exemplar()`
        re-derives every part of that from disk and refuses the promotion if
        any of it fails, so a wrong caller cannot memorize a `clip-*` file.
      * a decision naming a `subject_kind` with no id is an UNIDENTIFIED
        recurring subject → its visual cluster's centroid is offered to the
        draft store, which either bumps an existing draft's `obs_count`, opens
        a new one, or — F14 — recognises it as a subject the owner already
        confirmed and records the sighting there. Drafts never gain exemplars.
        That is the whole anti-drift rule: the registry grows from looks, the
        draft store grows from geometry, and geometry is never evidence.

    ## What a draft observation carries, and why (F14)

    Each observation records the LOOKS behind it: for every cluster member the
    see controller actually selected, its path, thumbnail, `vec_ref`, the
    see-report that proves the look and the applied provenance — READ off the
    labels, never assumed. That is the material `photo_memory.confirm` needs to
    promote exemplars once a human names the subject, and capturing it here is
    the only moment it is all in one place.

    Nothing in the list is evidence yet: a look sitting in a draft's record has
    been attributed to that draft by geometry alone. `add_exemplar()` re-derives
    every part of it from disk at confirm time and refuses a provenance that is
    not a bare `viewed-image:` — which is why the provenance is copied rather
    than defaulted. Defaulting it would restate the 2026-07-20 incident: a
    claim that a model looked, written by code that did not check.

    -> a summary dict; `{"ran": False}` when the run has no pack, which is
    every benchmark run. The blank sheet stays a property of the signature."""
    import numpy as np

    registry = photo_subjects.load(pack=pack)
    if registry.dir is None:
        return {"ran": False, "why": "this run has no owner pack — nothing to "
                                     "memorize into"}

    batch = int(report["batch"])
    unit = Path(workdir).name if workdir else None
    seen = {e["path"]: e for e in report["selected"]}
    label_of = {e["path"]: e for e in (entries or [])}
    cluster_members = {c["cluster"]: list(c["members"]) for c in report["clusters"]}
    cluster_of = {m: c["cluster"] for c in report["clusters"] for m in c["members"]}
    date_of = {e["path"]: (e.get("time") or "")[:7] for e in report["selected"]}

    def vectors_for(paths):
        rows = [index[p][1] for p in paths if p in index]
        return np.stack(rows).astype(np.float32) if rows else None

    id_index, id_space = photo_identity.load_index(Path(workdir) / "embed"
                                                   if workdir else Path("."),
                                                   pack)

    def identity_vector_for(path):
        """-> this file's identity vector, or None.

        A row whose status is not `identified` returns None, and the caller
        then falls back to the CLIP space rather than declining to score.

        ⚠️ That fallback is a DELIBERATE recall net, not an oversight, and it
        is the one place this design knowingly keeps the weaker signal. A
        detector miss is not proof the frame holds no subject: in the 20260821
        trial 2 of 23 frames of a real animal got no box (a paw filling the
        frame at a vet visit, twice). Treating `no-subject` as "do not score"
        would make every such miss a silent refusal to recognise, with no
        second chance and nothing in the report to notice it by.
        ⛔ The cost is real and is accepted with open eyes: those files are
        judged in the space this project measured as unable to tell two
        subjects apart, so they will mostly produce a question. A question is
        the safe failure — `space` is reported per file, so a run where the
        fallback is doing the work can be seen doing it.
        """
        row = id_index.get(path)
        if row is None:
            return None
        meta_row, vec = row
        return vec if meta_row.get("status") == photo_identity.STATUS_OK else None

    def identity_centroid_for(paths):
        """The cluster's identity centroid, over the members that HAVE one.

        ⛔ Members without a detected subject are skipped, never counted as a
        zero row. Averaging zeros in would shrink the centroid toward the
        origin in proportion to how many members happened to be photographs of
        the room, which would make the suppression decision depend on framing
        luck rather than on who is in the picture."""
        rows = [v for v in (identity_vector_for(p) for p in paths) if v is not None]
        if not rows:
            return None
        centroid = np.stack(rows).astype(np.float32).mean(axis=0)
        norm = float(np.linalg.norm(centroid))
        return centroid / norm if norm >= 0.5 else None

    see_report_path = str(Path(samples_dir).parent / "see-report.json")
    workdir_path = str(Path(workdir).resolve()) if workdir else None
    asks_away = away_gate(workdir, pack.profile) if workdir else (lambda _m: False)

    def looks_in(members):
        """The vision-confirmed looks behind one cluster, for `confirm` to
        promote later. Only files the see controller SELECTED are here — the
        rest have no thumbnail, so there is nothing anybody could have opened
        — and each carries the provenance the labels file actually applied.

        SNS-10: `captured` is the file's OWN capture time, carried whole. It
        is the same field `date_of` reads, and deliberately not the same
        value: that one is truncated to a month for the draft's active range,
        which is too coarse to argue about a subject's life coverage with. A
        file the see report gave no time keeps None all the way to the
        exemplar — a promotion date standing in for a capture date would read
        downstream as the real thing."""
        out = []
        for member in sorted(members):
            picked = seen.get(member)
            if not picked or not picked.get("sample") or member not in index:
                continue
            entry = label_of.get(member) or {}
            out.append({"path": member, "sample": picked.get("sample"),
                        "provenance": entry.get("provenance"),
                        "label": entry.get("label"), "vec_ref": index[member][0],
                        "captured": picked.get("time") or None,
                        "see_report": see_report_path, "workdir": workdir_path,
                        "batch": batch, "run_id": run_id})
        return out

    memorized, refused, drafted, recognised, rejected = [], [], [], [], []
    asked_away = []
    for path in sorted(decisions):
        value = decisions[path]
        if not isinstance(value, dict):
            continue                      # a bare label decides no subject
        evidence = {"see_report": see_report_path,
                    "batch": batch, "path": path,
                    "sample": seen.get(path, {}).get("sample"),
                    "label": value.get("label"), "run_id": run_id}

        subjects = decision_subjects(value, path)
        named = [s["subject_id"] for s in subjects if s.get("subject_id")]
        if named:
            entry = label_of.get(path) or {}
            vec = index[path][1] if path in index else None
            # R4 — a SHARED frame logs every name and banks none of them.
            #
            # `add_exemplar()` keys on `vec_ref`, the file's content sha: one
            # photograph, one key, one subject. Promoting the same whole-frame
            # vector under two ids would make each animal's bank contain the
            # other, which is D-24 restated with the owner's yes behind it
            # instead of a detector's guess. So both names still reach the
            # label, the observation and the folder — nothing is refused, the
            # owner is asked nothing extra — and neither one gains evidence.
            # ⛔ The end state is the composite key `<sha>#<det_index>` (R3b's
            # own card); until it exists this is the honest half.
            shared = len(named) > 1
            for subject_id in named:
                if shared:
                    refused.append({"path": path, "subject_id": subject_id,
                                    "why": "the frame names "
                                           f"{len(named)} subjects and one vec_ref "
                                           "cannot bank a vector for each; the "
                                           "sighting is logged, no exemplar is"})
                    note_observation(registry, subject_id, batch, unit, run_id,
                                     "known", evidence)
                    continue
                if vec is None:
                    refused.append({"path": path, "subject_id": subject_id,
                                    "why": "no embedding for this file"})
                    continue
                try:
                    id_row = id_index.get(path)
                    added, dropped = registry.add_exemplar(
                        subject_id, vec, index[path][0], path,
                        confirmed_by=entry.get("provenance", photo_evidence.VIEWED),
                        identity=identity, evidence=evidence,
                        captured=seen.get(path, {}).get("time") or None,
                        identity_vector=identity_vector_for(path),
                        identity_space=id_space,
                        identity_quality=(photo_identity.exemplar_quality(id_row[0])
                                          if id_row is not None else None))
                except ValueError as exc:
                    refused.append({"path": path, "subject_id": subject_id,
                                    "why": str(exc)})
                    continue
                note_observation(registry, subject_id, batch, unit, run_id,
                                 "known", evidence)
                memorized.append({"path": path, "subject_id": subject_id,
                                  "added": added, "dropped_for_cap": dropped})
            continue

        # An UNIDENTIFIED subject drafts from its visual cluster's CENTROID,
        # and a cluster has exactly one. Two unnamed animals in one frame
        # therefore still open ONE draft — drafting the same centroid twice
        # would put one geometry in the store under two records and ask the
        # owner the same question twice. The second animal is not lost: it is
        # on the label, it names the folder, and it becomes separable when the
        # composite key lands. Bounded on purpose, like R3b.
        kind = next((s["subject_kind"] for s in subjects if s.get("subject_kind")),
                    None)
        if not kind:
            continue
        members = cluster_members.get(cluster_of.get(path), [path])
        centroid = vectors_for(members)
        if centroid is None:
            refused.append({"path": path, "kind": kind,
                            "why": "no embedding for this cluster"})
            continue
        centroid = centroid.mean(axis=0)
        away = asks_away(members)
        subject, state = registry.observe_draft_subject(
            centroid, identity_centroid=identity_centroid_for(members),
            kind=kind, batch=batch, files=len(members),
            dates=[date_of.get(path)], identity=identity,
            evidence={"batch": batch, "unit": unit, "run_id": run_id,
                      "files": len(members), "state": None,
                      "looks": looks_in(members),
                      "seen": [f"classify/batch-{batch:02d}/samples/"
                               f"{seen.get(path, {}).get('sample')}"]},
            seen_on=[f"classify/batch-{batch:02d}/samples/"
                     f"{seen.get(path, {}).get('sample')}"],
            ask_away=away)
        subject.record["evidence"][-1]["state"] = state
        observation = {"path": path, "subject_id": subject.subject_id,
                       "state": state, "kind": kind,
                       "files": len(members), "obs_count": subject.obs_count}
        # F14: a recognised subject is not a draft, and counting it as one
        # would make the CLI report drafts this run never opened. OA-14 adds
        # the third bucket for the same reason: a cluster suppressed by a
        # REJECTION opened no record either, and reporting it as a draft would
        # show the operator a question nobody is ever going to be asked.
        {"known": recognised, "rejected": rejected}.get(
            state, drafted).append(observation)
        if away and state in ("new", "reinforced"):
            asked_away.append(observation)

    registry.save()
    import photo_memory
    proposals = photo_memory.write_subject_drafts(pack, registry, pack.profile)
    return {"ran": True, "memorized": memorized, "refused": refused,
            "drafted": drafted, "recognised": recognised,
            "asked_away": asked_away,
            "rejected_suppressed": rejected,
            "audit_log": str(registry.audit_path),
            "proposals": str(proposals),
            "drafts_total": len(registry.drafts),
            "note": ("only a bare `viewed-image:` label with a verifiable "
                     "thumbnail becomes an exemplar; every attempt, refusals "
                     "included, is a line in the audit log")}


def note_observation(registry, subject_id, batch, unit, run_id, state, evidence):
    """Record that a CONFIRMED subject was seen in this batch, so the review
    table's `known` rows rest on the registry rather than on a re-derivation.

    ⚠️ `files` here counts individually memorized files, while on a DRAFT the
    same field counts attributed cluster members. F14 added a THIRD writer with
    the draft's meaning on a confirmed record — a suppressed observation in
    `observe_draft_subject()` — and OA-14 a FOURTH, the same suppressed write
    on a REJECTED record. Nothing reads `files` for a non-draft — the
    checkpoint threshold and the question bodies both iterate `registry.drafts`
    — so the meanings still never meet. If anything ever reads it for a
    confirmed or rejected subject, split the field rather than reconciling the
    meanings."""
    # LITERAL (SNS-14). This appends an observation to whatever record it is
    # handed, and the only way a folded id reaches here is a see-label written
    # before the fold — a stale attribution, which must not grow the live
    # winner's counters. The tombstone takes it, where nothing reads it.
    subject = registry.get_literal(subject_id)
    if subject is None:
        return
    record = subject.record
    if batch not in record.setdefault("observed_in", []):
        record["observed_in"].append(batch)
    record["obs_count"] = int(record.get("obs_count", 0)) + 1
    record["files"] = int(record.get("files", 0)) + 1
    record.setdefault("evidence", []).append(
        {"batch": batch, "unit": unit, "run_id": run_id, "files": 1,
         "state": state, "seen": [evidence.get("sample")]})


def validate(report, entries, samples_dir):
    """Mechanical checks, no LLM (DESIGN's per-batch flow). Returns a dict; the
    caller exits non-zero when `ok` is False."""
    problems = []
    seen_paths = {e["path"] for e in report["selected"]}
    try:
        assert_no_fabrication(entries or report["provisional"], seen_paths,
                              samples_dir, report=report)
    except AssertionError as exc:
        problems.append(str(exc))

    missing = [e["path"] for e in report["selected"]
               if not e.get("sample")
               or not (Path(samples_dir) / e["sample"]).is_file()]
    if missing:
        problems.append(f"{len(missing)} selected file(s) have no thumbnail on disk — "
                        "the vision model would have nothing to look at: "
                        + ", ".join(sorted(missing)[:3]))

    # F10 — "provenance present" is the DESIGN's fourth validator check and was
    # the one that held only by construction. The invariant is a BICONDITIONAL:
    # a label carries a provenance prefix, and a provenance prefix carries a
    # label. `label: None, provenance: None` (an unlabeled file) stays legal —
    # that is the third state, not a violation. Checked here rather than in
    # assert_no_fabrication, which deliberately skips provenance-less entries.
    provenance_ok = True
    for e in (entries or report["provisional"]):
        if e.get("label") and not e.get("provenance"):
            provenance_ok = False
            problems.append(f"{e['path']} carries a label ({e['label']!r}) with no "
                            "provenance prefix — a label whose source cannot be "
                            "named is the 2026-07-20 failure mode one step earlier")
        elif e.get("provenance") and not e.get("label"):
            provenance_ok = False
            problems.append(f"{e['path']} carries provenance {e['provenance']!r} "
                            "with no label — nothing was actually decided")

    budget = report["config"]["budget"]
    picked = len(report["selected"])
    if picked != budget:
        problems.append(f"see-rate not met: budget {budget}, selected {picked}")

    # Residual unlabeled files are a WARNING, not a failure. VS-2 labels what
    # the index can carry — a viewed file, its cluster, and confident zero-shot
    # matches — and on the 6 replayed dumps that reaches 64-89% of a batch. The
    # rest still get the batch-level classify decision downstream, exactly as
    # they did before this stage existed. Failing here would block every real
    # batch; the DESIGN's "every file labeled" line describes the pipeline's
    # end state, not this one stage's output.
    warnings = []
    conflicts = report.get("cluster_label_conflicts") or []
    if conflicts:
        warnings.append(
            f"{len(conflicts)} visual cluster(s) had two viewed files return "
            "different labels; the lower-sorted path propagated and the "
            "disagreement is listed in cluster_label_conflicts (F12)")
    if entries:
        labeled = [e for e in entries if e.get("label")]
        if len(labeled) != len(entries):
            warnings.append(
                f"{len(entries) - len(labeled)} of {len(entries)} file(s) carry no "
                f"visual label ({len(labeled) / len(entries):.0%} covered) — they fall "
                "through to the batch-level classify decision")
    return {"ok": not problems, "problems": problems, "warnings": warnings,
            "cluster_label_conflicts": conflicts,
            "checked": {"selected": picked, "budget": budget,
                        "labeled": len(entries) if entries else 0,
                        "provenance_present": provenance_ok}}


# ------------------------------------------------------------------- main ---

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir")
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--see-rate", type=float, default=None,
                    help="override the configured rate for this run (0-1)")
    ap.add_argument("--pass", dest="pass_name", choices=["first_sort", "second_sort"],
                    default="first_sort",
                    help="first_sort = new dump (default 10%%); second_sort = "
                         "re-sort / mature registry (5%%)")
    ap.add_argument("--tau", type=float, default=SEE_TAU,
                    help=f"in-batch cluster threshold ({SEE_TAU})")
    ap.add_argument("--reason", help="log why the rate was raised for this batch")
    ap.add_argument("--profile", help="owner pack (else collection.json / PHOTO_PROFILE)")
    ap.add_argument("--scene-labels", help="path to scene-labels.json "
                                           "(default: <workdir>/embed/scene-labels.json)")
    ap.add_argument("--no-thumbnails", action="store_true",
                    help="select only, generate no viewables (measurement runs)")
    ap.add_argument("--apply", help="JSON of {path: label} the vision model "
                                    "returned. A value may also be an object: "
                                    "{\"label\": ..., \"subject_id\": ...} is a "
                                    "confirmed match, {\"label\": ..., "
                                    "\"subject_kind\": ...} an unidentified one")
    ap.add_argument("--memorize", action="store_true",
                    help="with --apply: promote vision-confirmed matches to "
                         "registry exemplars and draft unmatched subjects "
                         "(VS-4). No-op without an owner pack.")
    ap.add_argument("--validate", action="store_true",
                    help="re-run the mechanical checks over what is already written")
    ap.add_argument("--force", action="store_true", help="overwrite an existing report")
    ap.add_argument("--json", action="store_true", help="print the report to stdout")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    # The whole pack, not just the profile dict: `load_profile()` throws away
    # `.dir`, and VS-3's subject registry is a DIRECTORY inside the pack. Every
    # existing consumer keeps taking `profile` and is untouched.
    pack = photo_profile.resolve_pack(workdir=workdir, explicit=args.profile)
    profile = pack.profile
    out_dir = workdir / "classify" / f"batch-{args.batch:02d}"
    report_path = out_dir / "see-report.json"
    labels_path = out_dir / "see-labels.json"
    samples_dir = out_dir / "samples"

    if args.validate or args.apply:
        if not report_path.exists():
            sys.exit(f"{report_path} does not exist — run the selection first")
        report = json.loads(report_path.read_text())
        entries = json.loads(labels_path.read_text())["labels"] \
            if labels_path.exists() else []
        if args.apply:
            decisions = json.loads(Path(args.apply).read_text())
            # A45: `entries` here is what the labels file already holds — it
            # was read three lines up and then thrown away, which IS the
            # defect. Hand it over so a re-apply can keep what it must.
            try:
                entries = apply_decisions(report, decisions, samples_dir,
                                          existing=entries)
            except AssertionError as exc:
                sys.exit(f"--apply refused: {exc}")
            labels_path.write_text(json.dumps(
                {"engine": report["engine"], "batch": report["batch"],
                 "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "viewed": len(decisions), "labels": entries,
                 "cluster_label_conflicts": report["cluster_label_conflicts"]},
                ensure_ascii=False, indent=1))
            if args.memorize:
                # Deliberately AFTER the labels file is written: the memorize
                # rule reads the applied provenance back off disk, so a file
                # the controller picked but that ended up carrying a clip-*
                # label cannot be promoted.
                index, identity = load_index(workdir)
                report["memorize"] = memorize_batch(
                    report, decisions, entries, index, identity, pack,
                    samples_dir, run_id=report.get("run_id"), workdir=workdir)
                summary = report["memorize"]
                if summary["ran"]:
                    print(f"memorize: {len(summary['memorized'])} exemplar(s), "
                          f"{len(summary['drafted'])} draft observation(s), "
                          f"{len(summary['recognised'])} already-confirmed "
                          f"subject(s), "
                          f"{len(summary['asked_away'])} asked instead "
                          "(away from every home), "
                          f"{len(summary['rejected_suppressed'])} suppressed "
                          "by a rejection, "
                          f"{len(summary['refused'])} refused -> "
                          f"{summary['audit_log']}")
                else:
                    print(f"memorize: skipped — {summary['why']}")
            # F12: the disagreement belongs in the report too, not only in the
            # labels file — the report is what the operator reads.
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1))
        result = validate(report, entries, samples_dir)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        sys.exit(0 if result["ok"] else 1)

    if report_path.exists() and not args.force:
        sys.exit(f"{report_path} already exists — pass --force to redo the selection")

    cfg = visual_sorting_config(profile)
    if args.see_rate is not None:
        rate, rate_source = args.see_rate, f"--see-rate ({args.reason or 'no reason given'})"
    else:
        rate = cfg["see_rate"][args.pass_name]
        rate_source = ("owner pack" if photo_profile.get(profile, "visual_sorting",
                                                         "see_rate") else "engine default")
    classes, label_source = scene_label_set(profile)
    batch = load_batch(workdir, args.batch)
    rows = load_rows(workdir, batch)
    index, identity = load_index(workdir)
    scene_path = Path(args.scene_labels) if args.scene_labels \
        else workdir / "embed" / "scene-labels.json"
    matrix, encoded_classes, label_meta = load_scene_labels(scene_path, identity,
                                                            list(classes))

    report = build_report(workdir, batch, rows, index, matrix,
                          encoded_classes or list(classes), label_meta, identity,
                          cfg, rate, args.pass_name, args.tau, profile, label_source,
                          rate_source, pack=pack)
    report["run_id"] = datetime.now().strftime("see-%Y%m%d-%H%M")
    if args.reason:
        report["config"]["reason"] = args.reason

    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_thumbnails:
        make_samples(report, out_dir)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    trace = {t["rung"]: t["picked"] for t in report["ladder"]}
    print(f"batch {report['batch']} ({report['label']}): {report['coverage']['pool']} "
          f"files in the see pool, {report['coverage']['clusters']} clusters, budget "
          f"{report['config']['budget']} at {rate:.0%} -> selected "
          f"{len(report['selected'])} (rungs {trace}); "
          f"{report['diagnostics']['clip_matched']} clip-matched -> {report_path}")
    held = {k: n for k, n in report["coverage"]["held_from_vision"].items() if n}
    if held:
        print("held out of vision (still copied and named with the batch): "
              + ", ".join(f"{n} {why.replace('_', ' ')}" for why, n in held.items()))
    unchecked = report["coverage"]["document_check_missing"]
    if unchecked:
        print(f"⚠️  {len(unchecked)} still(s) in the pool were never checked for "
              "documents (an index built before this check). Run photo_embed.py "
              "on this work dir once — it fills the gap without --force:")
        print(f"    {photo_platform.run_line(photo_platform.venv_python(), Path(__file__).resolve().parent / 'photo_embed.py')}"
              f" \"{workdir}\"")
    # ⭐ The axis being off is an OPERATOR fact, and it was only ever stated
    # inside the report's `scene_labels.note`. A run without the matrix writes a
    # valid report, prints `0 clip-matched` and reads as a clean result — the
    # shape of a missing dependency that nobody notices, because nothing that is
    # empty looks broken. Printed last, after the summary the line qualifies.
    # ⛔ A warning and nothing else: the axis is optional by design (rungs 1/3/5
    # are pure geometry), so the exit code and what this stage computes are
    # unchanged. `matrix is None` means ABSENT — a mismatched or stale label
    # file already exits inside load_scene_labels().
    if matrix is None:
        print(f"⚠️  no {scene_path} — the scene axis is OFF for this run: every "
              "file's scene class stays empty and nothing can be clip-matched "
              "(rungs 1/3/5 still work). Encode the label set once with:")
        print(f"    {photo_platform.run_line(photo_platform.venv_python(), Path(__file__).resolve().parent / 'photo_embed.py')}"
              f" \"{workdir}\" --scene-labels")
    # R2 — the same failure shape, one stage over. The report ALREADY says this
    # (`subject_identity.index` is None when photo_identity never ran, and the
    # comment there is careful to distinguish it from "0 recognised"), but a
    # JSON field is not read at the moment it matters: UAT01 (20260904) carried
    # that None in every report and nobody saw it, so every subject verdict in
    # the run was CLIP and the pack recorded no reason (LL-PHO-105). ⛔ A
    # warning only — VS-3b is optional by design and `match()` scores in CLIP
    # exactly as it always did; the exit code is unchanged.
    # ⛔ `subject_identity` sits under `config`, not at the top level and not
    # under `diagnostics` — the top-level `index_identity` is the CLIP index's
    # fingerprint, a different thing with a confusingly similar name.
    if report["config"]["subject_identity"]["index"] is None:
        print("⚠️  no identity index — every subject verdict in this run is "
              "CLIP, not identity, and an exemplar promoted from here is a "
              "WHOLE-IMAGE vector (a frame holding two animals carries both). "
              "Build it once with:")
        print(f"    {photo_platform.run_line(photo_platform.venv_python(), Path(__file__).resolve().parent / 'photo_identity.py')}"
              f" \"{workdir}\"")
    # Last, after the report is written and every warning is out.
    if not args.no_thumbnails:
        photo_embed.exit_if_nothing_viewable(
            "photo_see", len(report["selected"]),
            sum(1 for e in report["selected"] if e.get("sample")),
            report["sample_failures_by_cause"])


if __name__ == "__main__":
    main()
