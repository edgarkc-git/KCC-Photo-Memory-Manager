#!/usr/bin/env python3
"""VS-2 exit test — does 10% embedding-guided seeing reproduce the shipped
classify decisions, and what does it cost against the old sampler?

    "golden-dump replay: 10% embedding-guided seeing reproduces the shipped
     classify decisions on >=2 done dumps; token cost vs old sampler measured
     and reported."   — Visual-Sorting DESIGN, Build stages, VS-2

Unlike `golden_replay.py` this is a MEASUREMENT, not a pass/fail suite, and it
cannot live on frozen fixtures: it needs the VS-1 embedding indexes, which are
built from the real image bytes. It therefore runs against the live work dirs
under `Working Files/` and is not part of the five-suite chain.

    ./.venv/bin/python3 tests/see_replay.py "<Working Files>" --dump 202401 202402
    ./.venv/bin/python3 tests/see_replay.py "<Working Files>"        # all dumps found

## What is being measured, stated plainly

**The vision model is never called here.** In its place sits an ORACLE: any
file the controller elects to see returns that file's shipped decision. That
is the standard way to score a selection policy offline, and it is the only
honest way to compare two selection policies on data whose labels are already
fixed. It measures the LADDER, not Opus. A real run's accuracy is bounded
above by these numbers and will be lower wherever the model itself errs.

## Ground truth = where the file was actually copied

Per file, from the shipped `plan/plan_P*-files.csv`:

  * the destination folder's trailing field when it is one of the SPEC's
    classes (`..._hiking`, `20240100_Screenshots`, `202402_Lakeside_cat`),
    else
  * that file's batch `type` in `batches.json` — also a shipped classify
    decision, written by the agent with a `classified_at` stamp.

The fallback is doing real work: on one measured dump 93% of the copy rows
land in folders the owner hand-named (D6 ground-truth shells and trip legs
like `0513-0517_Rivertown`), which carry no `_type` suffix at all. Rows the plan marks
`skip_dupe`, and pool files no plan CSV mentions, have no shipped decision and
are excluded from every denominator in both arms.

## The two arms, and the baseline that should worry you

  see       photo_see.py's ladder at the configured rate
  sampler   photo_sample.py's per-day `spread()` at the same budget formula
  majority  no seeing at all: predict each batch's most common shipped class

Both arms get the SAME oracle and the SAME propagation rule (a seen file's
label fills its whole visual cluster), so the only difference is which files
were picked. `majority` costs zero tokens and cannot be run in production —
it needs the answer in advance — but it is printed because it is the number
that says how much of "reproduces the shipped decisions" is real. A batch
whose files nearly all went to one folder is reproduced by predicting one
label, and most batches are like that.

`minority rows` — rows whose shipped class is NOT their batch's most common —
are the ones where seeing has to earn its place, and they are scored
separately.

## Which pack a run scored against is part of its result

Every report prints a **pack-state line**. A number produced with an owner's
accumulated knowledge in the pack and a number produced cold are different
numbers, and a report that does not say which it is cannot be compared with
the one beside it.

`--benchmark` is the cold-start arm: the run resolves a NAMED owner
(`BetaUser00` by default) whose pack must be **verifiably empty**, and
`assert_blank_sheet()` hard-fails if any owner fact leaked into it. Named
rather than anonymous because "no pack at all" and "a new owner's empty pack"
are deliberately different cases in `photo_profile.buckets()`; the benchmark
must be the second. The real owner's pack is hidden ground truth, scored after
the run, never loaded into it.

⚠️ **A benchmark dump's scene labels must be encoded UNDER the benchmark
pack.** The label set is owner data (ONB-10) and the class NAMES follow the
pack's language (ONB-9), so a template pack (`"language": "en"`) resolves
`Screenshots` where a dump encoded under a different-language pack holds that
pack's own word for it, and `photo_see.load_scene_labels` refuses the pair — correctly: those vectors were
encoded for a different class list. Re-encode first:

    ./.venv/bin/python3 scripts/photo_embed.py "<dump>" --scene-labels \
        --profile <benchmark pack> --force
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import photo_profile  # noqa: E402
import photo_see  # noqa: E402
import photo_sample  # noqa: E402
import photo_subjects  # noqa: E402
from photo_recurrence import cluster  # noqa: E402

# EV-9's pack-state mechanism lives in scripts/pack_state.py so that every
# replay states its pack under one set of rules. Re-exported here under the
# names this file has always used: `see_replay.BENCHMARK_OWNER`,
# `see_replay.assert_blank_sheet(...)` and friends are the surface
# tests/photo_see_cases.py already asserts against, and a refactor does not
# get to move a test's call sites.
from pack_state import (                                        # noqa: E402
    BENCHMARK_OWNER, BLANK_SHEET_ALLOWED, BLANK_SHEET_NESTED_FACTS,
    TIER2_REPLAY, assert_blank_sheet, has_content, owner_facts_in)
import pack_state as _pack_state                                # noqa: E402

# Classes a destination folder name can end in. Everything else falls back to
# the batch type. Derived from the declared locale tables rather than spelled
# out here: a shipped folder was named in whatever language its owner's pack
# resolved at the time, so every locale's spelling has to be recognised, and
# restating one of them here would be a second copy that can drift.
DEST_CLASSES = {name
                for table in (photo_profile.SCENE_CLASS_VOCAB,
                              photo_profile.BUCKET_VOCAB)
                for names in table.values()
                for name in names.values()}
# ...plus one retired bucket that no table holds any more: older dumps shipped
# before D13/D14 renamed it.
DEST_CLASSES.add("Misc")

# One 1280px-long-edge JPEG costs roughly (w*h)/750 input tokens; a 1280x960
# preview is ~1,640. Used for the cost column only — the file COUNT is the
# measured quantity, the token number is that count times this constant.
TOKENS_PER_IMAGE = 1640


def pack_state(pack, benchmark, run_type=TIER2_REPLAY,
               benchmark_owner=BENCHMARK_OWNER):
    """`pack_state.pack_state()` with this script's tier already bound.

    The shared function has NO default run type on purpose — a caller must say
    which tier of evidence its numbers belong to. This wrapper is not that
    caller forgetting: `see_replay.py` is a Tier 2 replay measurement and
    cannot be anything else, so binding the tier here states a fact about the
    script rather than hiding a choice. Every other caller passes its own."""
    return _pack_state.pack_state(pack, benchmark, run_type, benchmark_owner)


def ground_truth(workdir):
    """-> ({path: class}, stats). Shipped decisions only."""
    batches = json.loads((workdir / "batches.json").read_text())["batches"]
    btype = {b["batch"]: b.get("type") for b in batches}
    gt, skipped, unresolved = {}, 0, 0
    for csv_path in sorted((workdir / "plan").glob("plan_P*-files.csv")):
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("action") != "copy":
                    skipped += 1
                    continue
                tail = os.path.basename(row["destination"]).split("_")[-1]
                cls = tail if tail in DEST_CLASSES else None
                if cls is None:
                    cls = btype.get(int(row["batch"])) if row["batch"].isdigit() else None
                if cls is None:
                    unresolved += 1
                    continue
                gt[row["SourceFile"]] = cls
    return gt, {"rows_not_copied": skipped, "rows_unresolved": unresolved}


def batch_pool(workdir, batch, index, profile):
    """The see pool for one batch: own/shared files that actually embedded."""
    rows = photo_see.load_rows(workdir, batch)
    pool = []
    for row in rows:
        if photo_see.preclassify(row, profile) not in photo_see.SEE_POOL_CLASSES:
            continue
        # the same T2/T3 guard the engine applies — a harness that rebuilt the
        # pool from the class alone would silently disagree with it (A34a)
        if photo_see.tier_of(row, profile)[0] in photo_see.SEE_POOL_EXCLUDED_TIERS:
            continue
        if row["SourceFile"] in index:
            pool.append(row)
    pool.sort(key=lambda r: index[r["SourceFile"]][0])
    return rows, pool


def sampler_picks(rows, pool_paths, budget, profile):
    """photo_sample.py's selection, re-expressed over the same pool.

    Its shape is per-DAY: each day gets a share of the budget proportional to
    its file count, and `spread()` takes an evenly spaced slice of that day's
    stills in time order. Re-implemented here rather than imported because the
    original lives inside `main()`; the two functions that carry the policy
    (`sample_budget`, `spread`) ARE imported, so the numbers below are the
    shipped formula's, not a paraphrase of it."""
    pool = set(pool_paths)
    per_day = defaultdict(list)
    for row in rows:
        if row["SourceFile"] in pool:
            per_day[row["_dt"].date().isoformat()].append(row)
    picks = []
    total = len(pool)
    for day in sorted(per_day):
        own = sorted(per_day[day], key=lambda r: (r["_dt"], r["SourceFile"]))
        stills = [r for r in own if r.get("FileType") in photo_sample.IMAGE_TYPES] or own
        if not stills:
            continue
        k = max(1, round(budget * len(own) / max(total, 1)))
        for r in photo_sample.spread(stills, min(k, budget)):
            picks.append(r["SourceFile"])
    return picks[:budget]


def shipped_sample_cost(workdir):
    """What the old sampler ACTUALLY cost on this dump — counted off the
    `sample-report.json` files the shipped classify runs left behind.

    Read this number with its caveat attached: those runs pre-date VS-1's
    conversion fixes and the operator escalated/reduced batches by hand with
    `--max-samples`, so several large batches show 2-5 samples and 1-4
    `sample_failures` where the formula asks for 40. It is the historical
    truth of what Opus was shown, not what `photo_sample.py` would emit today
    — which is why `sampler_formula_cost` below is reported beside it."""
    total, batches, failures = 0, 0, 0
    for report in sorted((workdir / "classify").glob("batch-*/sample-report.json")):
        data = json.loads(report.read_text())
        total += len(data.get("samples", []))
        failures += len(data.get("sample_failures", []))
        batches += 1
    return {"images": total, "batches": batches, "thumbnail_failures": failures,
            "est_input_tokens": total * TOKENS_PER_IMAGE}


def score(labels, gt, majority_of, pool_paths):
    """-> coverage/accuracy overall and on minority rows."""
    scored = [p for p in pool_paths if p in gt]
    minority = [p for p in scored if gt[p] != majority_of[p]]
    def one(paths):
        labeled = [p for p in paths if labels.get(p)]
        correct = [p for p in labeled if labels[p] == gt[p]]
        return {"rows": len(paths), "labeled": len(labeled), "correct": len(correct),
                "coverage": round(len(labeled) / len(paths), 4) if paths else None,
                "accuracy": round(len(correct) / len(labeled), 4) if labeled else None}
    return {"all": one(scored), "minority": one(minority)}


def replay_batch(workdir, batch, index, identity, matrix, classes, profile, rate,
                 tau, use_clip_matched, registry=None):
    rows, pool = batch_pool(workdir, batch, index, profile)
    if not pool:
        return None
    import numpy as np

    paths = [r["SourceFile"] for r in pool]
    shas = [index[p][0] for p in paths]
    X = np.stack([index[p][1] for p in paths]).astype(np.float32)
    scenes = photo_see.zero_shot(X, matrix, classes)
    cluster_labels, _ = cluster(X, shas, tau)
    budget = photo_see.budget_for(len(paths), rate, photo_see.DEFAULT_VISUAL_SORTING)

    # VS-3's registry-derived ladder inputs, wired exactly as `photo_see.py`
    # wires them on the real path. The replay previously passed NONE of them,
    # so the carve-out measured 0 whatever the pack held and rungs 2 and 4 were
    # inert — a ladder that is not the shipped ladder, which is the whole thing
    # this harness exists to rule out (LL-PHO-41).
    #
    # All four must move together. `guaranteed` alone fires the carve-out but
    # leaves rungs 2/4 dead, which would calibrate RUNG1_BUDGET_SHARE against a
    # ladder no owner ever runs.
    #
    # The date handed to the timeline gate is each file's OWN capture time
    # (`_dt`, parsed from its EXIF by load_rows) — never the folder path.
    guaranteed, gray, unknown, usable_subjects = {}, None, None, 0
    if registry is not None and registry.subjects and len(X):
        # A subject with no exemplars is a record, not a recogniser.
        usable_subjects = sum(1 for s in registry.subjects if s.exemplars)
        dates = [row["_dt"] for row in pool]
        try:
            verdicts = registry.match(X, dates, identity)
        except ValueError as exc:                 # e.g. a cross-model registry
            sys.exit(str(exc))
        folder_bound = photo_see.folder_bound_clusters(
            paths, cluster_labels, registry, verdicts)
        guaranteed = photo_see.guaranteed_picks(X, cluster_labels, shas, folder_bound)
        gray = photo_see.subject_matches(verdicts, shas)
        unknown = photo_see.unknown_files(verdicts, scenes)

    # Naming is a second consumer of the budget: every folder needs >= 1 viewed
    # image, so the guaranteed picks are a FLOOR on the budget, not an overflow
    # of it. Same expression photo_see.py uses. With no guaranteed picks this is
    # a no-op, which keeps unbound and blank-pack runs byte-identical.
    budget = min(len(paths), max(budget, len(guaranteed)))

    selected, trace = photo_see.run_ladder(X, cluster_labels, shas, budget, True,
                                           guaranteed=guaranteed, gray=gray,
                                           unknown=unknown,
                                           registry_subjects=usable_subjects)
    see_paths = [paths[i] for i, _r, _w in selected]
    smp_paths = sampler_picks(rows, paths, budget, profile)

    # What photo_sample.py's OWN budget formula asks for on this batch
    # (min_samples 10 / max_samples 40, 10% with GPS and 5% without, over the
    # `own` files only). The A/B above equalizes budgets so it measures
    # selection; this is the cost side of the exit test.
    own = [r for r in pool if r["_preclass"] == "own"] if "_preclass" in pool[0] \
        else [r for r in pool if photo_sample.preclassify(r, profile) == "own"]
    has_gps = any(r.get("GPSPosition", "-") not in ("-", "") for r in rows)
    formula_budget = photo_sample.sample_budget(len(own) or len(pool), has_gps, profile)

    members = defaultdict(list)
    for i, lid in enumerate(cluster_labels):
        members[int(lid)].append(paths[i])
    cluster_of = {paths[i]: int(lid) for i, lid in enumerate(cluster_labels)}
    scene_of = {paths[i]: scenes[i] for i in range(len(paths))}

    def arm(picks, gt):
        """Oracle + identical propagation. Returns {path: label}."""
        labels = {}
        if use_clip_matched:
            for p in paths:
                s = scene_of[p]
                if s and s["confident"]:
                    labels[p] = s["class"]
        for p in picks:                                   # viewed-image:
            if p in gt:
                labels[p] = gt[p]
        for p in picks:                                   # clip-propagated:
            if p not in gt:
                continue
            for m in members[cluster_of[p]]:
                if m not in picks:
                    labels[m] = gt[p]
        return labels

    return {"paths": paths, "see": see_paths, "sampler": smp_paths, "budget": budget,
            "trace": trace, "arm": arm, "scenes": scene_of,
            "formula_budget": formula_budget, "clusters": len(members)}


def replay_dump(work_root, dump, rate, tau, use_clip_matched, profile=None,
                pack=None):
    workdir = (work_root / dump).resolve()
    index, identity = photo_see.load_index(workdir)
    profile = profile or {}
    # Resolved once per dump, not per batch: the pack is the run's, and an
    # unbound run gets an empty registry that makes every rung behave exactly
    # as it did before VS-3 existed.
    registry = photo_subjects.load(pack=pack) if pack is not None \
        else photo_subjects.Registry(source="no pack")
    classes, _src = photo_see.scene_label_set(profile)
    matrix, encoded, _meta = photo_see.load_scene_labels(
        workdir / "embed" / "scene-labels.json", identity, list(classes))
    if matrix is None:
        sys.exit(f"{workdir}/embed/scene-labels.json missing — run "
                 f"photo_embed.py \"{workdir}\" --scene-labels")
    gt, gt_stats = ground_truth(workdir)
    batches = json.loads((workdir / "batches.json").read_text())["batches"]

    totals = {a: {"seen": 0} for a in ("see", "sampler")}
    all_labels = {a: {} for a in ("see", "sampler", "majority")}
    pool_all, majority_of, starved, cluster_total = [], {}, 0, 0
    formula_cost = quota_capped = quota_held = guaranteed = 0
    zs_hits = Counter()
    batch_type = {a: {"agree": 0, "scored": 0} for a in ("see", "sampler")}
    for batch in batches:
        out = replay_batch(workdir, batch, index, identity, matrix, encoded, profile,
                           rate, tau, use_clip_matched, registry)
        if out is None:
            continue
        scored = [p for p in out["paths"] if p in gt]
        if not scored:
            continue
        top = Counter(gt[p] for p in scored).most_common(1)[0][0]
        for p in out["paths"]:
            majority_of[p] = top
        pool_all += out["paths"]
        cluster_total += out["clusters"]
        formula_cost += out["formula_budget"]
        rung1 = out["trace"][0]
        # `unfilled` now has two causes and they mean different things: more
        # clusters than budget (the old, only meaning) and the F2 rung-1 quota
        # deliberately holding clusters back for rungs 3/5. Counted apart, or
        # the quota would read as starvation.
        if rung1["unfilled"] > rung1.get("quota_capped", 0):
            starved += 1
        if rung1.get("quota_capped"):
            quota_capped += 1
        quota_held += rung1.get("quota_capped", 0)
        guaranteed += rung1.get("guaranteed", 0)
        for a in ("see", "sampler"):
            totals[a]["seen"] += len(out[a])
            all_labels[a].update(out["arm"](out[a], gt))
            # Batch-level agreement: the shipped decision WAS per batch — the
            # agent looked at the samples and set batch["type"]. So ask the
            # same question of each arm: does the commonest shipped class
            # among the files it chose to look at equal the type that shipped?
            looked = [gt[p] for p in out[a] if p in gt]
            if batch.get("type") and looked:
                batch_type[a]["scored"] += 1
                batch_type[a]["agree"] += \
                    Counter(looked).most_common(1)[0][0] == batch["type"]
        for p in out["paths"]:
            all_labels["majority"][p] = top
        for p in scored:
            s = out["scenes"][p]
            if s and s["confident"]:
                zs_hits[(s["class"], gt[p])] += 1

    result = {
        "dump": dump, "pool": len(pool_all),
        "with_ground_truth": sum(1 for p in pool_all if p in gt),
        "no_ground_truth": sum(1 for p in pool_all if p not in gt),
        "ground_truth_stats": gt_stats, "batches": len(batches),
        "clusters": cluster_total, "batches_with_unrepresented_clusters": starved,
        "rung1_quota": {"share": photo_see.RUNG1_BUDGET_SHARE,
                        "batches_capped": quota_capped,
                        "clusters_held_for_lower_rungs": quota_held,
                        "note": "F2/B1, swept on this replay; measured flat"},
        "naming_carve_out_looks": guaranteed,
        # Reported next to the looks so a 0 is readable: no folder-forming
        # subject in the pack and 0 looks is correct behaviour, whereas
        # subjects present and 0 looks means nothing reached accept level.
        "folder_forming_subjects": sum(
            1 for s in registry.subjects if s.forms_own_folder()),
        "arms": {}, "batch_type_agreement": batch_type,
        "old_sampler_shipped_cost": shipped_sample_cost(workdir),
        "old_sampler_formula_cost": {"images": formula_cost,
                                     "est_input_tokens": formula_cost * TOKENS_PER_IMAGE},
        "zero_shot_confusion": {f"{k[0]} -> {k[1]}": v
                                for k, v in sorted(zs_hits.items(),
                                                   key=lambda kv: -kv[1])},
    }
    for a in ("see", "sampler", "majority"):
        s = score(all_labels[a], gt, majority_of, pool_all)
        s["seen"] = totals.get(a, {}).get("seen", 0)
        s["est_input_tokens"] = s["seen"] * TOKENS_PER_IMAGE
        result["arms"][a] = s
    return result


def pct(v):
    return "  n/a " if v is None else f"{v:6.1%}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_root", help="the Working Files dir holding the dumps")
    ap.add_argument("--dump", nargs="*", help="dump dir names (default: every one "
                                              "with embed/ + plan/ + batches.json)")
    ap.add_argument("--see-rate", type=float, default=0.10)
    ap.add_argument("--tau", type=float, default=photo_see.SEE_TAU)
    ap.add_argument("--clip-matched", action="store_true",
                    help="also credit unseen files with a confident zero-shot class "
                         "(off by default: the label set has 4 utility classes the "
                         "shipped vocabulary does not contain, so this can only "
                         "lose accuracy — measured either way)")
    ap.add_argument("--profile", help="owner pack to run against (default: none, "
                                      "engine defaults only)")
    ap.add_argument("--benchmark", action="store_true",
                    help="cold-start arm: resolve a named owner whose pack must be "
                         "verifiably empty, and fail loudly if it is not. The dump's "
                         "scene-labels.json must have been encoded under THIS pack "
                         "(photo_embed.py --scene-labels --profile ... --force) — the "
                         "class names follow the pack's language")
    ap.add_argument("--benchmark-owner", default=BENCHMARK_OWNER,
                    help=f"the cold-start owner (default {BENCHMARK_OWNER})")
    ap.add_argument("--json", help="write the full result to this path")
    args = ap.parse_args()

    root = Path(args.work_root).resolve()
    pack = photo_profile.resolve_pack(workdir=root / (args.dump or [""])[0],
                                      explicit=args.profile) \
        if (args.profile or args.benchmark) else photo_profile.Pack()
    # ⛔ No separate assert_blank_sheet() call here. pack_state() enforces the
    # blank sheet as part of labelling the run a benchmark — one call that
    # cannot be half-applied, where a check standing beside a print can be
    # dropped in one edit and leave the label behind (EV-9).
    state, state_line = pack_state(pack, args.benchmark,
                                   benchmark_owner=args.benchmark_owner)
    dumps = args.dump or sorted(
        p.name for p in root.iterdir()
        if (p / "embed" / "embeddings.npy").exists() and (p / "batches.json").exists()
        and any((p / "plan").glob("plan_P*-files.csv")))

    results = []
    for dump in dumps:
        results.append(replay_dump(root, dump, args.see_rate, args.tau,
                                   args.clip_matched, pack.profile, pack))

    print(f"\nVS-2 replay — see-rate {args.see_rate:.0%}, tau {args.tau}, "
          f"clip-matched {'ON' if args.clip_matched else 'OFF'}, oracle-substituted "
          f"vision")
    print(state_line + "\n")
    head = (f"{'dump':10s} {'arm':9s} {'seen':>6s} {'tokens':>9s} {'rows':>6s} "
            f"{'cover':>7s} {'acc':>7s} | {'min.rows':>8s} {'cover':>7s} {'acc':>7s}")
    print(head)
    print("-" * len(head))
    for r in results:
        for a in ("see", "sampler", "majority"):
            s = r["arms"][a]
            print(f"{r['dump'] if a == 'see' else '':10s} {a:9s} {s['seen']:6d} "
                  f"{s['est_input_tokens']:9,d} {s['all']['rows']:6d} "
                  f"{pct(s['all']['coverage'])} {pct(s['all']['accuracy'])} | "
                  f"{s['minority']['rows']:8d} {pct(s['minority']['coverage'])} "
                  f"{pct(s['minority']['accuracy'])}")
        bt = r["batch_type_agreement"]
        print(f"{'':10s} pool {r['pool']}, with shipped decision "
              f"{r['with_ground_truth']}, without {r['no_ground_truth']}; "
              f"{r['clusters']} clusters over {r['batches']} batches, "
              f"{r['batches_with_unrepresented_clusters']} batches had more clusters "
              f"than budget")
        q = r["rung1_quota"]
        print(f"{'':10s} rung-1 quota {q['share']:.0%} held "
              f"{q['clusters_held_for_lower_rungs']} cluster(s) back in "
              f"{q['batches_capped']} batch(es) for rungs 3/5; naming carve-out "
              f"guaranteed {r['naming_carve_out_looks']} look(s) from "
              f"{r['folder_forming_subjects']} folder-forming subject(s) in the pack")
        print(f"{'':10s} batch type reproduced: see "
              f"{bt['see']['agree']}/{bt['see']['scored']}, sampler "
              f"{bt['sampler']['agree']}/{bt['sampler']['scored']}; "
              f"old sampler: {r['old_sampler_formula_cost']['images']} images by "
              f"its own formula, {r['old_sampler_shipped_cost']['images']} as "
              f"actually shipped "
              f"({r['old_sampler_shipped_cost']['thumbnail_failures']} thumbnail "
              f"failures)")
        print()

    tot = {a: sum(r["arms"][a]["seen"] for r in results) for a in ("see", "sampler")}
    shipped = sum(r["old_sampler_shipped_cost"]["images"] for r in results)
    formula = sum(r["old_sampler_formula_cost"]["images"] for r in results)
    print(f"token cost, equal-budget A/B: see {tot['see']} images "
          f"(~{tot['see'] * TOKENS_PER_IMAGE:,} input tokens) vs sampler "
          f"{tot['sampler']} (~{tot['sampler'] * TOKENS_PER_IMAGE:,}) "
          f"over {len(results)} dumps")
    print(f"token cost vs the old sampler's OWN formula: see {tot['see']} images "
          f"(~{tot['see'] * TOKENS_PER_IMAGE:,}) vs {formula} "
          f"(~{formula * TOKENS_PER_IMAGE:,}) — "
          f"{(tot['see'] - formula) / max(formula, 1):+.1%}")
    print(f"token cost vs what the old sampler ACTUALLY shipped: see {tot['see']} "
          f"images vs {shipped} — {(tot['see'] - shipped) / max(shipped, 1):+.1%} "
          f"(that run was hand-reduced and lost thumbnails; see the docstring)")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"pack_state": state, "dumps": results}, ensure_ascii=False, indent=1))
        print(f"full result -> {args.json}")


if __name__ == "__main__":
    main()
