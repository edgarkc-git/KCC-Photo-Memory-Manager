#!/usr/bin/env python3
"""VS-1b — recurrence census over a whole collection.

Reads the VS-1 embedding indexes built by photo_embed.py (one per work dir)
plus each work dir's manifest.csv for EXIF date and GPS, and asks one
question: **what keeps coming back?** Recurrence is the definition of "matters
to this owner" — nobody configures importance (Visual-Sorting DESIGN §2).

Every visual cluster is scored on four axes:

  mass             how many files
  spread           distinct days / distinct months it appears in
  persistence      first-seen -> last-seen span, and any drop-off
  place-boundness  does it sit on one GPS area

and every candidate carries a **blast radius** — how many files a human
answer would relabel. That is the ranking key (V2-7).

Writes, refusing to overwrite without --force:
  <out>/recurrence-census.json    machine record: axes, areas, clusters,
                                  candidate centroids (the dedupe key)
  <out>/photo-proposals-draft.md  the `ai-drafted` candidate block, ready to
                                  append to a pack's photo-proposals.md

Candidate kinds, all cold-derived: `residence_area` (a GPS area that behaves
like a home), `residence_bound_pattern` (recurs at exactly one residence —
either a subject that lives there or a view/habit, and the census does not
claim which), `place_bound_pattern` (recurs at one non-residence area),
`recurring_subject_or_scene` (recurs but travels), `bulk_no_camera_class`.

## It drafts; it never names (V2-6)

No candidate carries a name, and nothing here reads an owner pack — the
census is the thing that runs BEFORE there is a pack. It must therefore stay
pack-blind by construction: this module imports no profile resolution, and
`tests/photo_recurrence_cases.py` fails the build if it ever starts.

That still holds after the `subject_folder()` block below, which is folder
KEYING, not naming: it lives here because the pre-confirmation half of the
identity it keys on is the census's own `candidate_id`. It resolves no pack —
its caller is `photo_subjects.Registry.folder_for()`, which holds the
confirmed entry and passes it in. The import runs one way only (subjects ->
recurrence), which is what keeps the census pack-blind.

## Privacy — a residence never becomes a place name

A GPS area photographed on many distinct days across many months, much of it
after dark, is somebody's home. The census infers those areas precisely so it
can SUPPRESS them: a residence area gets an opaque `residence-A` id, no
coordinates anywhere, and any other area within HOME_SUPPRESS_KM of it is
folded into it rather than published as a place of its own (a 1.6 km
fragment of the same home is still the home). The markdown draft carries no
coordinates at all — not even rounded ones — and no filesystem paths, because
paths in a sorted collection are named after places (for example
`202512_Lakeside_cat_resort`). Coordinates live in the machine JSON only,
at 1 decimal (~11 km, city level)
and never for a residence. An inferred residence is never reverse-geocoded.

## Clustering — greedy leader, cosine, tau=0.80

Vectors are unit-norm, so cosine is a dot product. Points are ordered by how
many neighbours they have within tau (blockwise matmul), ties broken by
sha256, and each unassigned point in that order claims every unassigned point
within tau. Density order, not arrival order: the result does not depend on
which work dirs were listed first, and re-running on the same input gives the
same clusters and the same ids. No refinement pass — the invariant "every
member is within tau of its leader" is worth more here than tighter
centroids, because it is what makes a cluster defensible as one thing.

tau=0.80 was picked off a real 7-dump index (9,915 embedded files spanning
seven months), sweeping for the shape the census needs — real
multi-month clusters, no cluster swallowing the collection:

  tau    clusters  largest      singletons  >=3 months  >=3mo & mass>=10
  0.75      1817   751 (7.6%)         902          86                55
  0.80      2764   539 (5.4%)        1541          68                34
  0.85      4003   342 (3.4%)        2424          40                23
  0.90      5729   107 (1.1%)        4060          17                 5

0.90 destroys recurrence (5 usable multi-month clusters out of 9,915 files);
0.75 still holds together but its clusters start mixing visibly different
content. 0.80 keeps the largest cluster at 5.4% — a single 5-day landscape
burst, not a mega-cluster — while the top multi-month cluster is 215 files
over 61 days and 7 months. Override with --tau; the sweep and the real-run
numbers are recorded in photo-recurrence/SKILL.md.

## Cluster identity is the dedupe key

A candidate re-observed in a later census bumps `obs_count` and re-tags to
`ai-reinforced` instead of becoming a second draft (Memory-System DESIGN).
Two mechanisms, deliberately separate:

  id      sha256 over the sorted sha256s of the candidate's exemplars (the
          members closest to its centroid). Stable while the cluster's core
          is stable, and independent of run order.
  match   a new candidate whose centroid is within DEDUPE_TAU of a previous
          census's candidate INHERITS that id, whatever its exemplars now
          are — so growth (new members, a shifted medoid) reinforces the
          existing draft instead of forking it.

--force therefore carries the previous census forward. --reset discards it
and starts obs_count at 1 again.

## What this stage does NOT do

The zero-shot class axis (interests / not_important / digital-trash) needs
the scene label set from VS-2, which does not exist yet. The census does not
guess it: it reports `zero_shot_class_distribution: null` with the reason,
and offers instead the one bulk-class signal the index and manifest alone can
support — clusters whose members carry no camera EXIF at all
(screenshots / forwarded / saved images), marked as the cold proxy it is.

`kind` in embeddings.csv is not read. A reclaimed row can carry the
manifest's uncorrected kind (known VS-1 defect: the sha256 reclaim path runs
before the magic-byte check) — the vector is right, the column can lie. The
census needs no image/video split, so it takes none, and derives everything
else from manifest.csv.

Deterministic and fast (1.5 s over 9,906 files), so there is nothing to resume.

Usage:
  python3 photo_recurrence.py "<Working Files>/202511__" "<Working Files>/202512__" ...
  python3 photo_recurrence.py "<Working Files>"/2026*__ --out /tmp/census --force
"""

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from photo_cluster import haversine_km, parse_date, parse_gps  # noqa: E402
import photo_embed  # noqa: E402

TAU = 0.80                 # cluster threshold (see docstring sweep)
NEAR_TAU_MARGIN = 0.05     # blast radius reaches files this much looser than tau
DEDUPE_TAU = 0.85          # centroid match against a previous census
EXEMPLARS = 5              # members nearest the centroid; also the id material

MIN_MASS = 8               # a candidate must be worth a human's attention
MIN_DAYS = 4
MIN_MONTHS = 2

CELL = 0.01                # ~1.1 km GPS grid
AREA_MERGE_KM = 2.0        # cells within this of an area seed join it
HOME_SUPPRESS_KM = 5.0     # any area this close to a residence IS the residence
RESIDENCE_MIN_DAYS = 8
RESIDENCE_MIN_MONTHS = 3
RESIDENCE_NIGHT_SHARE = 0.25
NIGHT_HOURS = set(range(19, 24)) | set(range(0, 7))

PLACE_BOUND = 0.60         # share of GPS members in one area
DROPOFF_MONTHS = 2         # absent from this many trailing months = a drop-off
NO_CAMERA_SHARE = 0.80     # cluster is a bulk no-camera class above this

META_IDENTITY = ("model_id", "pretrained_tag", "embed_dim", "preprocess_fingerprint",
                 "preview_backend")
# The scene-label TEXT vectors carry no preview, so their check leaves it out:
# requiring it would ask for a re-encode that could never match.
TEXT_IDENTITY = tuple(k for k in META_IDENTITY if k != "preview_backend")


def load_sources(workdirs):
    """-> (vectors, records). One record per usable file, joined manifest-side.

    A row is usable when it embedded AND its vector is non-zero: a failed row
    is an all-zero vector at the same index (`zero_vector_means_failed`), and
    a zero vector has no cosine — it would silently poison one cluster.
    Content seen in two dumps is counted once; raw dumps are separate
    collections for copying, but a census that counted the same photo twice
    would report a recurrence that never happened."""
    import numpy as np

    vectors, records, identity, seen = [], [], None, set()
    for workdir in workdirs:
        workdir = Path(workdir).resolve()
        embed_dir = workdir / "embed"
        manifest_path = workdir / "manifest.csv"
        for required in (embed_dir / "embeddings.csv", embed_dir / "embeddings.npy",
                         embed_dir / "embeddings-meta.json", manifest_path):
            if not required.exists():
                sys.exit(f"{required} is missing — run photo_embed.py on {workdir} first")
        meta = json.loads((embed_dir / "embeddings-meta.json").read_text())
        this = photo_embed.space_view(meta, META_IDENTITY)
        if identity is None:
            identity = this
        elif this != identity:
            sys.exit(f"{workdir}: its index was built with a different model/preprocess "
                     f"({this}) than the earlier sources ({identity}). Vectors from two "
                     "models are not comparable — re-embed with one model.")
        with open(manifest_path, newline="") as f:
            manifest = {r["SourceFile"]: r for r in csv.DictReader(f)}
        with open(embed_dir / "embeddings.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        arr = np.load(embed_dir / "embeddings.npy")
        for row, vec in zip(rows, arr):
            if row.get("status") != "embedded":
                continue
            norm = float(np.linalg.norm(vec))
            if norm < 0.5:
                continue
            manifest_row = manifest.get(row["SourceFile"])
            if manifest_row is None or row["sha256"] in seen:
                continue
            seen.add(row["sha256"])
            vectors.append(vec / norm)
            records.append({
                "source": workdir.name,
                "path": row["SourceFile"],
                "name": Path(row["SourceFile"]).name,
                "sha256": row["sha256"],
                "date": parse_date(manifest_row),
                "gps": parse_gps(manifest_row),
                "has_camera": manifest_row.get("Make", "-") not in ("-", ""),
            })
    return np.asarray(vectors, dtype=np.float32), records, identity


def cluster(X, shas, tau):
    """Greedy leader clustering in density order -> (labels, leader indices)."""
    import numpy as np

    counts = np.zeros(len(X), dtype=np.int64)
    for i in range(0, len(X), 1024):
        counts[i:i + 1024] = (X[i:i + 1024] @ X.T >= tau).sum(axis=1)
    order = sorted(range(len(X)), key=lambda i: (-int(counts[i]), shas[i]))

    labels = np.full(len(X), -1, dtype=np.int64)
    leaders = []
    for idx in order:
        if labels[idx] != -1:
            continue
        lid = len(leaders)
        leaders.append(idx)
        labels[(X @ X[idx] >= tau) & (labels == -1)] = lid
    return labels, leaders


def area_stats(area, records):
    dates = [records[i]["date"] for i in area["members"]]
    area["files"] = len(area["members"])
    area["days"] = len({d.date() for d in dates})
    area["months"] = sorted({d.strftime("%Y-%m") for d in dates})
    area["night_share"] = sum(d.hour in NIGHT_HOURS for d in dates) / len(dates)
    area["first_seen"] = min(dates).strftime("%Y-%m-%d")
    area["last_seen"] = max(dates).strftime("%Y-%m-%d")
    return area


def find_areas(records):
    """GPS areas, with the residences among them flagged for suppression.

    Cells of ~1 km are absorbed into the densest seed within AREA_MERGE_KM.
    An area is a residence when it was photographed on many distinct days
    across many months and a real share of that was after dark — a home, or a
    regular base like a family house. Anything within HOME_SUPPRESS_KM of one
    is folded in rather than published separately."""
    cells = defaultdict(list)
    for i, r in enumerate(records):
        if r["gps"] and r["date"]:
            cells[(round(r["gps"][0] / CELL) * CELL, round(r["gps"][1] / CELL) * CELL)].append(i)

    areas, used = [], set()
    for seed, _ in sorted(cells.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if seed in used:
            continue
        members = []
        for cell, idxs in cells.items():
            if cell not in used and haversine_km(seed, cell) <= AREA_MERGE_KM:
                used.add(cell)
                members.extend(idxs)
        areas.append({"seed": seed, "members": sorted(members)})

    for area in areas:
        area_stats(area, records)
        area["residence"] = (area["days"] >= RESIDENCE_MIN_DAYS
                             and len(area["months"]) >= RESIDENCE_MIN_MONTHS
                             and area["night_share"] >= RESIDENCE_NIGHT_SHARE)

    residences = [a for a in areas if a["residence"]]
    kept = []
    for area in areas:
        if area["residence"]:
            kept.append(area)
            continue
        home = next((h for h in residences
                     if haversine_km(h["seed"], area["seed"]) <= HOME_SUPPRESS_KM), None)
        if home is None:
            kept.append(area)
        else:  # a fragment of somebody's home is still their home
            home["members"] = sorted(home["members"] + area["members"])
            home["absorbed"] = home.get("absorbed", 0) + 1
    for area in kept:
        # Re-stat after absorption, or a home reports the days and nights of
        # only its densest cell — understating the very axes it is ranked on.
        # The residence flag itself is NOT revisited: absorbing fragments can
        # dilute night_share, and un-flagging a home post-hoc would publish
        # its coordinates.
        if area.get("absorbed"):
            area_stats(area, records)
    kept.sort(key=lambda a: (-a["files"], a["seed"]))

    letters, n = {}, 0
    for area in kept:
        if area["residence"]:
            area["area_id"] = f"residence-{chr(ord('A') + len(letters))}"
            letters[area["area_id"]] = True
        else:
            n += 1
            area["area_id"] = f"area-{n}"
    return kept


def candidate_id(shas):
    return "rc-" + hashlib.sha256("|".join(sorted(shas)).encode()).hexdigest()[:12]


# ------------------------------------ recurring-subject / D9 folder keying ---
#
# N-10a (naming SPEC v0.5, signed 2026-08-08): on recurring-subject and D9 pet
# folders a confirmed name REPLACES the routing class word — a folder named
# for the routing class becomes one named for the subject. That makes the
# folder's own name mutable, and a mutable name is not a merge key: the first
# rename would make the next run fail to find the folder and FORK it into two.
# Lesson LL-PHO-39.
#
# So the key is the subject's stable identity and the name is a display
# attribute hanging off it. Identity has two lives, exactly as the SPEC's
# "Folder merging" section sets out: before confirmation it is the visual
# cluster the census already assigns (`candidate_id`, itself centroid-matched
# forward across censuses so growth reinforces rather than forks); after
# confirmation it is the registry entry's own `subject_id`. The rename ledger
# (N-6) maps an OLD RENDERED NAME back to an identity, so a tree sorted before
# a rename still resolves after it.
#
# The caller is VS-3's subject registry: `photo_subjects.Registry.folder_for()`
# holds the confirmed entry and `rename_ledger()` builds the ledger below.
# These functions live here rather than there because the identity they key on
# BEFORE confirmation is this module's `candidate_id`, and because the census
# must never import the registry — the dependency runs subjects -> recurrence,
# never back, which is what keeps the census pack-blind.
SUBJECT_KEY_PREFIX = "subject:"


def subject_identity(candidate=None, registry_entry=None):
    """-> the stable identity string. Registry entry wins once a subject is
    confirmed; the census candidate carries it before that."""
    if registry_entry and registry_entry.get("subject_id"):
        return str(registry_entry["subject_id"])
    if candidate and candidate.get("candidate_id"):
        return str(candidate["candidate_id"])
    raise ValueError("a recurring-subject folder needs an identity — either a "
                     "confirmed registry entry (subject_id) or a census "
                     "candidate (candidate_id). Keying it on the rendered name "
                     "is the LL-PHO-39 fork.")


def subject_folder(period, candidate=None, registry_entry=None, fallback_word=None):
    """The folder record for one recurring-subject / D9 folder.

    `period` is the folder's period field, supplied by the caller because the
    engine holds no naming vocabulary of its own. `fallback_word` is the
    routing class word to render while the subject has no confirmed name —
    owner vocabulary, so it is passed in, never embedded here; with neither
    name nor fallback the folder simply has no rendered name yet, which is
    V2-6's "drafts, never names".

    `key` is what a merge/lookup compares. `display_name` and `folder_name`
    are what a human reads, and a change to either MUST NOT change `key`."""
    identity = subject_identity(candidate, registry_entry)
    display = (registry_entry or {}).get("name") or fallback_word
    previous = list((registry_entry or {}).get("previous_names", []))
    return {
        "key": f"{period}/{SUBJECT_KEY_PREFIX}{identity}",
        "identity": identity,
        "identity_source": ("registry" if registry_entry
                            and registry_entry.get("subject_id") else "census candidate"),
        "period": period,
        "display_name": display,
        "folder_name": f"{period}_{display}" if display else None,
        "previous_names": previous,
        "keyed_on": ("subject identity (N-10a) — the rendered name is a display "
                     "attribute and never a key (LL-PHO-39)"),
    }


def resolve_subject_key(period, rendered_name, ledger):
    """A tree sorted BEFORE a rename still has to resolve after it (N-6).

    `ledger` maps a rendered display name to the identity it belonged to
    (`photo_subjects.Registry.rename_ledger()`); the key it returns is the
    same key `subject_folder()` produces today, so the old folder is found and
    merged into rather than forked. Unknown name -> None: an unresolvable
    folder is a question for a human, never a new one created on a guess."""
    identity = (ledger or {}).get(rendered_name)
    if identity is None:
        return None
    return f"{period}/{SUBJECT_KEY_PREFIX}{identity}"


def month_index(months, month):
    return months.index(month) if month in months else -1


def describe_cluster(members, records, area_of, all_months):
    dates = [records[i]["date"] for i in members if records[i]["date"]]
    if not dates:
        return None
    months = sorted({d.strftime("%Y-%m") for d in dates})
    days = sorted({d.date() for d in dates})
    placed = [area_of[i] for i in members if area_of.get(i)]
    area_counts = Counter(placed)
    top_area, top_n = area_counts.most_common(1)[0] if area_counts else (None, 0)
    gps_members = len(placed)
    residence_share = (sum(n for a, n in area_counts.items() if a.startswith("residence-"))
                       / gps_members) if gps_members else 0.0
    return {
        "mass": len(members),
        "spread_days": len(days),
        "spread_months": len(months),
        "months": months,
        "month_coverage": round(len(months) / len(all_months), 3) if all_months else 0.0,
        "first_seen": min(dates).strftime("%Y-%m-%d"),
        "last_seen": max(dates).strftime("%Y-%m-%d"),
        "persistence_span_days": (max(dates).date() - min(dates).date()).days,
        "night_share": round(sum(d.hour in NIGHT_HOURS for d in dates) / len(dates), 3),
        "time_of_day": time_of_day(dates),
        "gps_members": gps_members,
        "place_boundness": round(top_n / gps_members, 3) if gps_members else 0.0,
        "bound_area": top_area,
        "bound_area_kind": ("residence" if top_area and top_area.startswith("residence-")
                            else "place" if top_area else None),
        "residence_areas": sorted({a for a in area_counts if a.startswith("residence-")}),
        "residence_share": round(residence_share, 3),
        "no_camera_share": round(sum(not records[i]["has_camera"] for i in members)
                                 / len(members), 3),
    }


# The hour band a pattern happens in. "mostly daylight" was too coarse to be
# useful: the sunset-at-home class sits at 16-18h, which is neither night nor
# midday, and calling it daylight hid exactly the pattern the census is for.
HOUR_BANDS = ((7, 11, "mostly morning"), (11, 15, "mostly midday"),
              (15, 19, "mostly late afternoon"))


def time_of_day(dates):
    hours = sorted(d.hour for d in dates)
    median_hour = hours[len(hours) // 2]
    for low, high, name in HOUR_BANDS:
        if low <= median_hour < high:
            return name
    return "mostly after dark"


def classify_candidate(axes):
    """The kind of draft this cluster supports, on cold evidence only."""
    if axes["no_camera_share"] >= NO_CAMERA_SHARE:
        return "bulk_no_camera_class"
    bound = axes["place_boundness"] >= PLACE_BOUND
    if bound and axes["bound_area_kind"] == "residence" and len(axes["residence_areas"]) == 1:
        return "residence_bound_pattern"
    if bound and axes["bound_area_kind"] == "place":
        return "place_bound_pattern"
    return "recurring_subject_or_scene"


def label_hint(kind, axes):
    """Descriptive, never a name (V2-6) and never a place (privacy rule)."""
    when = f"{axes['time_of_day']}"
    if 0.35 <= axes["night_share"] <= 0.65:
        # "mostly midday, 52% after dark" is self-contradicting prose; a
        # bimodal pattern deserves to be described as bimodal.
        when = "split between daylight and after dark"
    elif axes["night_share"] > 0.65 and axes["time_of_day"] != "mostly after dark":
        when += f" ({axes['night_share']:.0%} of it after dark)"
    rhythm = (f"{axes['spread_days']} days over {axes['spread_months']} months")
    if kind == "residence_bound_pattern":
        return (f"a recurring pattern bound to one residence ({axes['bound_area']}) — "
                f"{rhythm}, {when}. This is either a subject that lives there or a "
                "recurring view/habit (the sunset / night-view class); telling those two "
                "apart needs VS-2's scene labels, so the census does not claim which.")
    if kind == "place_bound_pattern":
        return (f"a recurring pattern bound to one non-residence area "
                f"({axes['bound_area']}) — {rhythm}, {when}")
    if kind == "bulk_no_camera_class":
        return (f"{axes['mass']} look-alike files with no camera EXIF — screenshots, "
                f"forwarded or saved images; {rhythm}")
    where = (f"appears at {len(axes['residence_areas'])} residence areas"
             if len(axes["residence_areas"]) > 1 else
             "not tied to one place" if axes["gps_members"] else "no GPS")
    return f"a recurring subject or scene — {rhythm}, {where}, {when}"


def build_candidates(labels, X, records, areas, tau):
    import numpy as np

    area_of = {}
    for area in areas:
        for i in area["members"]:
            area_of[i] = area["area_id"]

    all_months = sorted({r["date"].strftime("%Y-%m") for r in records if r["date"]})
    by_cluster = defaultdict(list)
    for i, lid in enumerate(labels):
        by_cluster[int(lid)].append(i)

    kept = []
    for lid, members in sorted(by_cluster.items()):
        axes = describe_cluster(members, records, area_of, all_months)
        if axes is None:
            continue
        if not (axes["mass"] >= MIN_MASS and axes["spread_days"] >= MIN_DAYS
                and axes["spread_months"] >= MIN_MONTHS):
            continue
        centroid = X[members].mean(axis=0)
        norm = float(np.linalg.norm(centroid))
        centroid = centroid / norm if norm else centroid
        order = sorted(members, key=lambda i: (-float(X[i] @ centroid), records[i]["sha256"]))
        exemplars = order[:EXEMPLARS]
        kept.append({"members": members, "axes": axes, "centroid": centroid,
                     "exemplars": exemplars, "kind": classify_candidate(axes)})

    # Blast radius: answering a candidate relabels its own members plus the
    # LEFTOVERS nearest to it — files in no candidate and in no substantial
    # cluster of their own, within a threshold looser than the clustering.
    # Restricting reach to leftovers is what keeps the number honest: without
    # it, a one-event burst of 539 trip photos (its own coherent cluster, just
    # not a recurring one) was donating its whole mass to whichever small
    # candidate happened to sit nearest, and ranked a 24-file cluster above
    # the 215-file subject that recurs on 61 days.
    reach = Counter()
    if kept:
        C = np.stack([c["centroid"] for c in kept])
        sizes = Counter(int(lid) for lid in labels)
        eligible = np.array([sizes[int(lid)] < MIN_MASS for lid in labels])
        for c in kept:
            eligible[c["members"]] = False
        sims = X @ C.T
        best = sims.argmax(axis=1)
        for i in np.nonzero(eligible & (sims.max(axis=1) >= tau - NEAR_TAU_MARGIN))[0]:
            reach[int(best[i])] += 1
    for j, c in enumerate(kept):
        c["blast_radius"] = c["axes"]["mass"] + reach[j]
        c["near_miss_files"] = reach[j]

    # A residence is a candidate in its own right — "is this where you live,
    # and from when to when?" is the single highest-blast question at cold
    # start, and the answer relabels every file taken there.
    for area in areas:
        if not area["residence"]:
            continue
        members = area["members"]
        dates = [records[i]["date"] for i in members]
        exemplars = sorted(members, key=lambda i: records[i]["sha256"])[:EXEMPLARS]
        kept.append({
            "members": members, "exemplars": exemplars, "centroid": None,
            "kind": "residence_area", "blast_radius": len(members), "near_miss_files": 0,
            "axes": {"mass": len(members), "spread_days": area["days"],
                     "spread_months": len(area["months"]), "months": area["months"],
                     "month_coverage": round(len(area["months"]) / len(all_months), 3)
                     if all_months else 0.0,
                     "first_seen": area["first_seen"], "last_seen": area["last_seen"],
                     "persistence_span_days": (max(dates).date() - min(dates).date()).days,
                     "night_share": round(area["night_share"], 3),
                     "time_of_day": time_of_day(dates),
                     "gps_members": len(members), "place_boundness": 1.0,
                     "bound_area": area["area_id"], "bound_area_kind": "residence",
                     "residence_areas": [area["area_id"]], "residence_share": 1.0,
                     "no_camera_share": round(sum(not records[i]["has_camera"]
                                                  for i in members) / len(members), 3)},
        })
        kept[-1]["label_hint"] = (
            f"{area['area_id']}: photographed on {area['days']} distinct days across "
            f"{len(area['months'])} months, {round(100 * area['night_share'])}% of it after "
            "dark — this behaves like a home or a regular base. Its coordinates are "
            "deliberately not printed.")

    for c in kept:
        c.setdefault("label_hint", label_hint(c["kind"], c["axes"]))
        last_month = c["axes"]["last_seen"][:7]
        trailing = len(all_months) - 1 - month_index(all_months, last_month)
        c["drop_off"] = None
        if c["axes"]["spread_months"] >= 3 and trailing >= DROPOFF_MONTHS:
            c["drop_off"] = {"last_seen": c["axes"]["last_seen"],
                             "months_absent_since": trailing,
                             "note": (f"present in {c['axes']['spread_months']} months, then "
                                      f"absent for the last {trailing} months of the window — "
                                      "a drop-off is itself a draftable fact")}
    kept.sort(key=lambda c: (-c["blast_radius"], c["axes"]["first_seen"]))
    return kept


def apply_prior(candidates, prior, run_id):
    """Carry ids and obs_count forward from a previous census (the dedupe
    key). Matched by centroid cosine, greedily, best pair first — a candidate
    that grew must reinforce its draft, not fork a second one."""
    import numpy as np

    for c in candidates:
        c["candidate_id"] = candidate_id(c["exemplars_sha"])
        c["obs_count"] = 1
        c["status"] = "ai-drafted"
        c["noticed_by"] = "agent"
        c["run_id"] = run_id

    prior_by_id = {p["candidate_id"]: p for p in prior}
    prior_vecs = [(p, np.asarray(p["centroid"], dtype=np.float32))
                  for p in prior if p.get("centroid")]
    pairs = []
    for j, c in enumerate(candidates):
        if c["centroid"] is None:
            continue
        for p, pv in prior_vecs:
            sim = float(c["centroid"] @ pv)
            if sim >= DEDUPE_TAU:
                pairs.append((sim, j, p["candidate_id"]))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    taken_new, taken_old = set(), set()
    for sim, j, old_id in pairs:
        if j in taken_new or old_id in taken_old:
            continue
        taken_new.add(j)
        taken_old.add(old_id)
        candidates[j]["candidate_id"] = old_id

    # An id that simply recurred (same exemplars, no centroid drift) is the
    # other half of the same dedupe: it must reinforce too.
    for c in candidates:
        p = prior_by_id.get(c["candidate_id"])
        if p is None:
            continue
        c["obs_count"] = int(p.get("obs_count", 1)) + 1
        c["status"] = "ai-reinforced"
        c["first_observed_in_census"] = p.get("first_observed_in_census", p.get("run_id"))
    return candidates


def render_markdown(census):
    """The `ai-drafted` block for photo-proposals.md.

    Counts, dates and file basenames only: no paths (this project's folder
    names ARE place names), no coordinates, no names of anything."""
    c = census["coverage"]
    out = [
        "## ai-drafted — recurrence census (VS-1b)",
        "",
        f"Run `{census['run_id']}` over {c['files']} embedded files from "
        f"{len(census['sources'])} source(s), {c['first_seen']} → {c['last_seen']} "
        f"({len(c['months'])} months). Nothing here is named and nothing is confirmed: "
        "these are cold-derived facts ranked by **blast radius** — how many files a "
        "human answer would relabel.",
        "",
        "Residence areas are inferred only so they can be suppressed: they appear as "
        "`residence-A`/`residence-B`, never as a place name, and never with coordinates.",
        "",
    ]
    for c_ in census["candidates"]:
        a = c_["axes"]
        out.append(f"### {c_['candidate_id']} — {c_['kind']}  ·  blast radius "
                   f"**{c_['blast_radius']}**")
        out.append("")
        out.append(f"- provenance: `{c_['status']}` · obs_count {c_['obs_count']} · "
                   f"noticed_by agent · run `{c_['run_id']}`")
        out.append(f"- axes: mass {a['mass']} · spread {a['spread_days']} days / "
                   f"{a['spread_months']} months ({a['month_coverage']:.0%} of the window) · "
                   f"persistence {a['first_seen']} → {a['last_seen']} "
                   f"({a['persistence_span_days']} days) · place-boundness "
                   f"{a['place_boundness']:.0%}"
                   + (f" to {a['bound_area']}" if a["bound_area"] else " (unplaced)"))
        out.append(f"- active: {a['months'][0]} → {a['months'][-1]}")
        out.append(f"- label_hint: {c_['label_hint']}")
        if c_["drop_off"]:
            out.append(f"- ⚠️ drop-off: {c_['drop_off']['note']}")
        if c_["near_miss_files"]:
            out.append(f"- reach: {a['mass']} members + {c_['near_miss_files']} near-miss "
                       "files that would inherit the same answer")
        out.append(f"- exemplars: {', '.join(c_['exemplar_names'])}")
        out.append("")
    out.append("### not drafted here")
    out.append("")
    out.append(census["zero_shot_note"])
    out.append("")
    return "\n".join(out)


def scrub(markdown, records, areas):
    """Last line of defence for the privacy rule: the markdown must carry no
    directory name and no coordinate. Cheap, and it fails loudly rather than
    shipping. File basenames are fine (`IMG_4772.HEIC`); the FOLDERS above
    them are the leak — `202512_Lakeside_cat_resort` names a residence."""
    for record in records:
        for part in Path(record["path"]).parent.parts:
            if len(part) >= 3 and part not in ("/",) and part in markdown:
                raise AssertionError(f"census markdown contains the directory name {part!r} — "
                                     "paths in this project are named after places; emit "
                                     "file basenames only")
    for area in areas:
        for value in area["seed"]:
            for text in (f"{value:.4f}", f"{value:.3f}", f"{value:.2f}"):
                if text in markdown:
                    raise AssertionError(f"census markdown contains the coordinate {text}")
    return markdown


def build(workdirs, tau, prior, run_id):
    import numpy as np

    X, records, identity = load_sources(workdirs)
    if not len(X):
        sys.exit("no usable embedded vectors in those work dirs")
    labels, leaders = cluster(X, [r["sha256"] for r in records], tau)
    areas = find_areas(records)
    candidates = build_candidates(labels, X, records, areas, tau)
    for c in candidates:
        c["exemplars_sha"] = [records[i]["sha256"] for i in c["exemplars"]]
        c["exemplar_names"] = [records[i]["name"] for i in c["exemplars"]]
    candidates = apply_prior(candidates, prior, run_id)

    dated = [r["date"] for r in records if r["date"]]
    months = sorted({d.strftime("%Y-%m") for d in dated})
    census = {
        "engine": "photo_recurrence.py (VS-1b recurrence census)",
        "run_id": run_id,
        "tau": tau,
        "dedupe_tau": DEDUPE_TAU,
        "sources": [str(Path(w).resolve()) for w in workdirs],
        "index_identity": identity,
        "coverage": {
            "files": len(records),
            "with_date": len(dated),
            "with_gps": sum(1 for r in records if r["gps"]),
            "months": months,
            "first_seen": min(dated).strftime("%Y-%m-%d") if dated else None,
            "last_seen": max(dated).strftime("%Y-%m-%d") if dated else None,
            "clusters": len(leaders),
        },
        "areas": [{"area_id": a["area_id"], "kind": "residence" if a["residence"] else "place",
                   "files": a["files"], "days": a["days"], "months": a["months"],
                   "night_share": round(a["night_share"], 3),
                   "first_seen": a["first_seen"], "last_seen": a["last_seen"],
                   # A residence never carries coordinates, anywhere.
                   "approx_center": None if a["residence"]
                   else [round(a["seed"][0], 1), round(a["seed"][1], 1)],
                   "absorbed_nearby_areas": a.get("absorbed", 0)}
                  for a in areas],
        "zero_shot_class_distribution": None,
        "zero_shot_note": (
            "The zero-shot class axis (interests / not_important / digital-trash) is "
            "**not** in this census: it needs VS-2's scene label set, which does not exist "
            "yet, and guessing it from the embedding index alone would be fabrication. The "
            "one bulk-class signal the index plus manifest.csv can honestly support is "
            "`bulk_no_camera_class` above — look-alike clusters whose files carry no camera "
            "EXIF (screenshots, forwarded and saved images). Treat it as a cold proxy, not "
            "as a classified label."),
        "candidates": [{
            "candidate_id": c["candidate_id"], "kind": c["kind"], "status": c["status"],
            "obs_count": c["obs_count"], "noticed_by": c["noticed_by"], "run_id": c["run_id"],
            "first_observed_in_census": c.get("first_observed_in_census", c["run_id"]),
            "blast_radius": c["blast_radius"], "near_miss_files": c["near_miss_files"],
            "axes": c["axes"], "drop_off": c["drop_off"], "label_hint": c["label_hint"],
            "exemplars": c["exemplars_sha"], "exemplar_names": c["exemplar_names"],
            "members": [records[i]["path"] for i in c["members"]],
            "centroid": (np.asarray(c["centroid"]).round(5).tolist()
                         if c["centroid"] is not None else None),
        } for c in candidates],
    }
    return census, records, areas


def read_prior(out_dir, reset):
    path = out_dir / "recurrence-census.json"
    if reset or not path.exists():
        return []
    return json.loads(path.read_text()).get("candidates", [])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdirs", nargs="+", help="work dirs holding embed/ and manifest.csv")
    ap.add_argument("--out", help="output dir (default: <parent of first workdir>/recurrence)")
    ap.add_argument("--tau", type=float, default=TAU, help=f"cosine cluster threshold ({TAU})")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing census, carrying its ids and obs_count forward")
    ap.add_argument("--reset", action="store_true",
                    help="with --force: discard the previous census instead of carrying it")
    ap.add_argument("--json", action="store_true", help="print the census to stdout too")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve() if args.out \
        else Path(args.workdirs[0]).resolve().parent / "recurrence"
    json_path = out_dir / "recurrence-census.json"
    md_path = out_dir / "photo-proposals-draft.md"
    if json_path.exists() and not args.force:
        sys.exit(f"{json_path} already exists — pass --force to overwrite it "
                 "(ids and obs_count are carried forward), or --force --reset to start over")

    run_id = datetime.now().strftime("census-%Y%m%d-%H%M")
    prior = read_prior(out_dir, args.reset)
    census, records, areas = build(args.workdirs, args.tau, prior, run_id)
    markdown = scrub(render_markdown(census), records, areas)

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(census, indent=1, ensure_ascii=False))
    md_path.write_text(markdown)

    if args.json:
        print(json.dumps(census, ensure_ascii=False, indent=1))
    print(f"{census['coverage']['files']} files, {census['coverage']['clusters']} clusters, "
          f"{len(census['areas'])} GPS areas "
          f"({sum(a['kind'] == 'residence' for a in census['areas'])} inferred residence), "
          f"{len(census['candidates'])} candidates -> {out_dir}")


if __name__ == "__main__":
    main()
