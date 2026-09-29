#!/usr/bin/env python3
"""Cases for photo_see.py (VS-2) — the priority ladder's fill order, the
floor/cap budget, determinism, cluster-label propagation, and the 2026-07-20
fabrication guard.

Every fixture is synthetic: vectors are hand-built in a 32-dimensional toy
space, the "photos" are manifest rows that never existed, and the handful of
cases that need a real thumbnail generate a flat-colour JPEG with Pillow at
run time. Nothing here is a real photo, a real vector or a real place — the
same rule photo_embed_cases.py and photo_recurrence_cases.py follow.

Needs **numpy** (and Pillow for the thumbnail cases), which live in the repo
.venv — but NOT torch: photo_see.py loads no model, and this suite would fail
loudly if it ever started to.

  ./.venv/bin/python3 tests/photo_see_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import contextlib
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import photo_evidence  # noqa: E402
import photo_see as ps  # noqa: E402
import view_fixture  # noqa: E402

VERBOSE = False
DIM = 32
# The interpreter for subprocess cases. The repo's .venv is gitignored, so it is
# absent in a fresh clone and in every git worktree — a hardcoded path there gave
# 13 false failures across three suites that read as code defects (D-29). Fall back
# to the interpreter actually running this file.
PY = str(ROOT / ".venv" / "bin" / "python3")
if not Path(PY).exists():
    PY = sys.executable
SCRIPT = str(ROOT / "scripts" / "photo_see.py")

IDENTITY = {"model_id": "ViT-B-32", "pretrained_tag": "laion2b_s34b_b79k",
            "embed_dim": DIM, "preprocess_fingerprint": "sha256:testfixture0000"}

# The identity space (VS-3b) is its own toy space with its own dimension — a
# separate model, so a fixture that shared DIM would hide a swapped store.
ID_DIM = 6
ID_SPACE = {"space": "subject-identity", "detector_id": "det-fixture",
            "model_id": "id-fixture", "embed_dim": ID_DIM, "normalized": True,
            "zero_vector_means_no_subject": True}


def log(msg):
    if VERBOSE:
        print(f"  {msg}")


def unit(v):
    return np.asarray(v, dtype=np.float32) / float(np.linalg.norm(v))


def basis(i):
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


RNG = np.random.RandomState(11)


def orth(base):
    v = RNG.normal(size=DIM).astype(np.float32)
    return unit(v - float(v @ base) * np.asarray(base, dtype=np.float32))


def near(base, direction, jitter=0.10):
    return unit(np.asarray(base, dtype=np.float32) + jitter * np.asarray(direction))


def blend(base, direction, cos):
    return unit(cos * np.asarray(base, dtype=np.float32)
                + float(np.sqrt(1 - cos * cos)) * np.asarray(direction))


def sha_of(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


class Fixture:
    """One synthetic work dir that looks exactly like photo_scan + photo_embed
    left it: manifest.csv, batches.json and an embed/ index."""

    def __init__(self):
        self.files = []

    def add(self, vec, name=None, hour=9, day=3, make="Apple", filetype="JPEG",
            dims=("4032", "3024"), status="embedded", real_image=False):
        i = len(self.files)
        self.files.append({
            "name": name or f"IMG_{i:04d}.JPG", "vec": np.asarray(vec, dtype=np.float32),
            "when": datetime(2026, 5, day, hour, (i * 7) % 60), "make": make,
            "filetype": filetype, "dims": dims, "status": status,
            "real_image": real_image})
        return self

    def many(self, vec, n, spread_dir=None, **kw):
        for k in range(n):
            self.add(near(vec, basis(20 + k % 8) if spread_dir is None else spread_dir),
                     **kw)
        return self

    def write(self, root, name="dump", with_labels=True, classes=None,
              identity=None, real_images=False):
        workdir = Path(root) / name
        (workdir / "embed").mkdir(parents=True, exist_ok=True)
        with open(workdir / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "SourceFile", "FileName", "FileType", "DateTimeOriginal",
                "GPSPosition", "Make", "Model", "ImageWidth", "ImageHeight"])
            w.writeheader()
            for rec in self.files:
                path = workdir / rec["name"]
                if rec["real_image"] or real_images:
                    make_real_jpeg(path)
                w.writerow({
                    "SourceFile": str(path), "FileName": rec["name"],
                    "FileType": rec["filetype"],
                    "DateTimeOriginal": rec["when"].strftime("%Y:%m:%d %H:%M:%S"),
                    "GPSPosition": "25.0 121.5", "Make": rec["make"],
                    "Model": "iPhone" if rec["make"] != "-" else "-",
                    "ImageWidth": rec["dims"][0], "ImageHeight": rec["dims"][1]})
        (workdir / "batches.json").write_text(json.dumps({"batches": [
            {"batch": 1, "label": "synthetic", "from": "2026-05-01",
             "to": "2026-05-31", "files": len(self.files), "type": "爬山"}]}))
        with open(workdir / "embed" / "embeddings.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["SourceFile", "sha256", "kind",
                                              "status", "size", "mtime", "error"])
            w.writeheader()
            for rec in self.files:
                w.writerow({"SourceFile": str(workdir / rec["name"]),
                            "sha256": sha_of(rec["name"]), "kind": "image",
                            "status": rec["status"], "size": 100, "mtime": "1.0",
                            "error": ""})
        vecs = np.stack([rec["vec"] if rec["status"] == "embedded" else np.zeros(DIM)
                         for rec in self.files]).astype(np.float32)
        with open(workdir / "embed" / "embeddings.npy", "wb") as f:
            np.save(f, vecs)
        meta = dict(IDENTITY)
        meta["normalized"] = True
        (workdir / "embed" / "embeddings-meta.json").write_text(json.dumps(meta))
        if with_labels:
            write_labels(workdir / "embed", classes, identity)
        return workdir


def write_labels(embed_dir, classes=None, identity=None):
    """A scene-label file whose class vectors are basis directions, so a test
    can put a file exactly on one class and know what it must score."""
    classes = classes or list(ps.scene_label_set({})[0])
    meta = dict(identity or IDENTITY)
    meta.update({"kind": "scene-labels", "classes": classes,
                 "prompts": {c: [f"a photo of {c}"] for c in classes},
                 "prompt_language": "en", "label_set_source": "test fixture"})
    (embed_dir / "scene-labels.json").write_text(json.dumps(meta, ensure_ascii=False))
    vecs = np.stack([basis(i) for i in range(len(classes))]).astype(np.float32)
    with open(embed_dir / "scene-labels.npy", "wb") as f:
        np.save(f, vecs)


def make_real_jpeg(path):
    from PIL import Image
    Image.new("RGB", (64, 48), (120, 30, 30)).save(path, "JPEG")


def run_see(workdir, *args, expect_fail=False):
    env = dict(os.environ)
    env.pop("PHOTO_PROFILE", None)
    proc = subprocess.run([PY, SCRIPT, str(workdir), "--batch", "1", *args],
                          capture_output=True, text=True, env=env)
    if expect_fail:
        assert proc.returncode != 0, f"expected failure, got 0\n{proc.stdout}"
    else:
        assert proc.returncode == 0, f"exit {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    return proc


def report_of(workdir):
    return json.loads((workdir / "classify" / "batch-01" / "see-report.json").read_text())


def build(workdir, rate=0.10, tau=ps.SEE_TAU, profile=None, thumbnails=False,
          pack=None):
    """The library path — same code the CLI runs, minus argparse.

    `pack` defaults to None, exactly as build_report's own parameter does, so
    every case that does not ask for an owner pack exercises the empty-registry
    path — which is the one the benchmark runs on."""
    profile = profile or {}
    classes, source = ps.scene_label_set(profile)
    batch = ps.load_batch(workdir, 1)
    rows = ps.load_rows(workdir, batch)
    index, identity = ps.load_index(workdir)
    matrix, encoded, meta = ps.load_scene_labels(
        workdir / "embed" / "scene-labels.json", identity, list(classes))
    report = ps.build_report(workdir, batch, rows, index, matrix,
                             encoded or list(classes), meta, identity,
                             ps.visual_sorting_config(profile), rate, "first_sort",
                             tau, profile, source, "test", pack=pack)
    if thumbnails:
        ps.make_samples(report, workdir / "classify" / "batch-01")
    return report


def two_class_profile(*names):
    """An owner pack that declares its own two-class label set (ONB-10), so a
    fixture can put a file exactly on one class and know the answer."""
    return {"visual_sorting": {"scene_labels": {n: [f"a photo of {n}"] for n in names}}}


def run_case(name, fn):
    try:
        fn()
        print(f"  ok    {name}")
        return True
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        return False
    except Exception as e:                                      # noqa: BLE001
        # Anything other than an AssertionError used to escape main() and end
        # the run with NO TALLY AT ALL — every case after it never ran, and
        # nothing said so. Measured on this suite 2026-08-31: 25 `ok` lines,
        # a traceback, and no count. That is worse than a wrong count, which
        # is the shape LL-PHO-115 is about; the same fix landed for the
        # exiftool suite in `4a9091f`.
        print(f"  ERROR {name}: {type(e).__name__}: {e}")
        return False


# --------------------------------------------------------------- geometry ---
# Three well-separated visual groups plus loners, so cluster membership and
# the ladder's ordering are known in advance rather than observed.
A, B, C = basis(0), basis(1), basis(2)


def three_group_fixture(loners=3):
    RNG.seed(11)
    f = Fixture()
    f.many(A, 20)                       # biggest cluster
    f.many(B, 10)
    f.many(C, 4)
    for k in range(loners):             # far from everything, incl. each other
        f.add(blend(basis(9 + k), orth(basis(9 + k)), 0.99))
    return f


# ------------------------------------------------------------------ cases ---


def case_budget_floor_cap_and_pool(tmp):
    cfg = ps.DEFAULT_VISUAL_SORTING
    assert ps.budget_for(30, 0.10, cfg) == 5, "floor must lift a small batch to 5"
    assert ps.budget_for(1000, 0.10, cfg) == 40, "cap must hold a huge batch at 40"
    assert ps.budget_for(200, 0.10, cfg) == 20, "in between it is just the rate"
    assert ps.budget_for(3, 0.10, cfg) == 3, "the floor may never exceed the pool"
    assert ps.budget_for(200, 0.05, cfg) == 10, "second_sort rate"


def case_see_rate_is_actually_met(tmp):
    wd = three_group_fixture().write(tmp)
    report = build(wd, rate=0.10)
    budget = report["config"]["budget"]
    assert budget == 5, budget                      # 37 files -> floor
    assert len(report["selected"]) == budget, (len(report["selected"]), budget)
    result = ps.validate(report, [], wd / "classify" / "batch-01" / "samples")
    assert "see-rate not met" not in " ".join(result["problems"]), result


def case_ladder_fills_in_priority_order(tmp):
    wd = three_group_fixture(loners=3).write(tmp)
    report = build(wd, rate=0.50)                   # 37 files -> budget 19
    rungs = [e["rung"] for e in report["selected"]]
    assert rungs == sorted(rungs), rungs
    trace = {t["rung"]: t for t in report["ladder"]}
    assert trace[1]["picked"] == trace[1]["available"], trace[1]
    assert trace[1]["unfilled"] == 0, trace[1]
    # every cluster got its representative, so the loners are already taken by
    # rung 1; rung 3 has nothing left and rung 5 spends the rest
    assert trace[3]["picked"] + trace[5]["picked"] + trace[1]["picked"] == \
        report["config"]["budget"], trace
    assert trace[5]["picked"] > 0, "diversity fill should spend the leftover budget"
    log(f"ladder {[(t['rung'], t['picked']) for t in report['ladder']]}")


def case_rung1_takes_biggest_clusters_first(tmp):
    """37 files in clusters of 20/10/4/1/1/1 and a budget of 5.

    REWRITTEN for F2/B1 (was: "the five biggest clusters get a look and the
    sixth does not"). That assertion described the pre-quota ladder, in which
    rung 1 spent the whole budget whenever clusters outnumbered it — the
    degeneration the quota exists to stop. What survives is the ORDER: rung 1
    still takes its clusters largest first. What changed is how many it may
    take.

    Both halves are asserted here, against the same fixture: at
    `rung1_share=1.0` (the old ladder, reproduced exactly) rung 1 takes 5 and
    starves everything below it; at the shipped share it takes fewer and
    leaves the remainder to the rungs below.

    Asserted against `rung1_quota(budget)`, NOT against a literal — the share
    is a calibrated `{n}`, and a test that hardcodes its arithmetic fails on
    the next calibration for no reason. What is actually under test is the
    ORDER and the attribution, both of which hold at any share.
    """
    wd = three_group_fixture().write(tmp)
    index, _identity = ps.load_index(wd)
    batch = ps.load_batch(wd, 1)
    rows = ps.load_rows(wd, batch)
    paths = sorted((r["SourceFile"] for r in rows), key=lambda p: index[p][0])
    shas = [index[p][0] for p in paths]
    X = np.stack([index[p][1] for p in paths]).astype(np.float32)
    from photo_recurrence import cluster as _cluster
    labels, _ = _cluster(X, shas, ps.SEE_TAU)
    size_of = Counter(int(lid) for lid in labels)

    # the old ladder: share 1.0 puts no cap on rung 1
    old_sel, old_trace = ps.run_ladder(X, labels, shas, 5, True, rung1_share=1.0)
    old = {t["rung"]: t for t in old_trace}
    assert old[1]["available"] == 6 and old[1]["picked"] == 5, old[1]
    assert sorted((size_of[int(labels[i])] for i, _r, _w in old_sel),
                  reverse=True) == [20, 10, 4, 1, 1]
    assert old[3]["picked"] == 0 and old[5]["picked"] == 0, \
        "with no quota, a starved rung 1 leaves nothing for the rungs below it"

    # the shipped ladder, through the report so the config is the real one
    report = build(wd, rate=0.01)                   # budget 5 (floor), 6 clusters
    trace = {t["rung"]: t for t in report["ladder"]}
    q = ps.rung1_quota(5)
    assert report["config"]["budget"] == 5, report["config"]
    assert trace[1]["available"] == 6, trace[1]
    assert trace[1]["picked"] == report["config"]["rung1_quota"] == q, trace[1]
    # 6 clusters, budget 5: the quota held back the ones the budget alone
    # would have admitted; anything past the budget was out either way. The
    # two causes of `unfilled` are attributed apart so a quota never reads as
    # starvation.
    assert trace[1]["quota_capped"] == min(6, 5) - q, trace[1]
    assert trace[1]["unfilled"] == 6 - q, trace[1]
    sizes = sorted((e["cluster_size"] for e in report["selected"] if e["rung"] == 1),
                   reverse=True)
    assert sizes == [20, 10, 4, 1, 1][:q], sizes   # still largest-first
    assert trace[3]["picked"] + trace[5]["picked"] == 5 - q, trace
    log(f"quota {trace[1]['quota']}: rung1 {trace[1]['picked']}, "
        f"rung3 {trace[3]['picked']}, rung5 {trace[5]['picked']}")


def case_rung1_quota_is_a_share_of_the_budget(tmp):
    """The quota arithmetic itself (F2/B1). It is a SHARE, floored at 1 so a
    see_floor-sized batch still gets coverage, and never above the budget."""
    assert ps.rung1_quota(0) == 0
    assert ps.rung1_quota(5, 0.65) == 3            # the see_floor case
    assert ps.rung1_quota(40, 0.65) == 26
    assert ps.rung1_quota(20, 0.60) == 12
    assert ps.rung1_quota(1, 0.65) == 1, "never zero while there is a budget"
    assert ps.rung1_quota(40, 1.0) == 40, "share 1.0 reproduces the old ladder"
    assert 0.50 <= ps.RUNG1_BUDGET_SHARE <= 0.90, \
        "0.85 is the OA-12-calibrated value, but the sweep found the parameter " \
        "FLAT (minority 68-77/126 across 0.30-1.00, non-monotonic), so this is " \
        "a 'neither inert nor unbounded' band, not a tight one: below ~0.5 " \
        "rung 1 starves and the ladder loses cluster coverage; at 1.0 the " \
        "F2/B1 quota is inert and rungs 3/5 can never fire"


def case_the_odd_file_out_is_seen(tmp):
    """The screenshot-inside-a-trip case: one file unlike anything else must
    get a look. It does — but at **rung 1**, not rung 3, because an embedding
    outlier is by construction its own singleton cluster and rung 1 gives
    every cluster a representative. Asserted on the rung, not just on the
    pick, so this stays honest about which rung is doing the work."""
    RNG.seed(11)
    f = Fixture()
    f.many(A, 30)                                   # one big cluster
    odd = blend(basis(15), orth(basis(15)), 0.99)
    f.add(odd, name="ODD_0001.JPG")
    wd = f.write(tmp)
    report = build(wd, rate=0.10)                   # 31 files -> budget 5
    picked = {Path(e["path"]).name: e["rung"] for e in report["selected"]}
    assert picked.get("ODD_0001.JPG") == 1, picked


def case_rung3_fires_once_rung1_is_capped(tmp):
    """REPLACES `case_rung3_is_structurally_unreachable`, which pinned the
    pre-quota finding: 396 candidates, 0 picks over 77 real batches.

    Two claims are separated here, because the old test and the old docstring
    ran them together (F7):

      geometry — a rung-3 candidate is a SUBSET of the singleton clusters,
                 never a multi-member one. Still true, still asserted. What is
                 NOT true is "exactly the singletons": a singleton near a big
                 cluster's centroid scores above OUTLIER_MAX_SIM and is no
                 candidate at all (0 of 12 on the real batch the review
                 measured).
      budget   — the load-bearing reason rung 3 never fired. At
                 `rung1_share=1.0` it still picks 0 at every budget; at the
                 shipped share the reserved remainder reaches it.
    """
    RNG.seed(11)
    f = Fixture()
    f.many(A, 30)
    for k in range(4):
        f.add(blend(basis(12 + k), orth(basis(12 + k)), 0.99))
    wd = f.write(tmp)

    index, _identity = ps.load_index(wd)
    batch = ps.load_batch(wd, 1)
    rows = ps.load_rows(wd, batch)
    paths = sorted((r["SourceFile"] for r in rows), key=lambda p: index[p][0])
    shas = [index[p][0] for p in paths]
    X = np.stack([index[p][1] for p in paths]).astype(np.float32)
    from photo_recurrence import cluster as _cluster
    labels, _ = _cluster(X, shas, ps.SEE_TAU)
    sizes = Counter(int(lid) for lid in labels)

    candidates = ps.outliers(X, labels, shas, set())
    assert candidates, "the fixture must produce outlier candidates at all"
    assert all(sizes[int(labels[i])] == 1 for i in candidates), \
        "a rung-3 candidate that is NOT a singleton would break the geometry"
    assert len(candidates) <= sum(1 for lid, n in sizes.items() if n == 1), \
        "candidates are a subset of the singletons, not all of them (F7)"

    for budget in (5, len(sizes), len(paths)):
        _sel, trace = ps.run_ladder(X, labels, shas, budget, True, rung1_share=1.0)
        rung3 = next(t for t in trace if t["rung"] == 3)
        assert rung3["picked"] == 0, ("uncapped rung 1 must still starve rung 3",
                                      budget, rung3)

    _sel, trace = ps.run_ladder(X, labels, shas, 5, True)
    rung1, rung3 = trace[0], trace[2]
    assert rung1["picked"] == ps.rung1_quota(5), rung1
    assert rung3["picked"] > 0, ("the reserved remainder must reach rung 3", rung3)
    log(f"{len(candidates)} candidates: 0 picked uncapped, {rung3['picked']} picked "
        f"with the quota")


def geometry_of(wd, tau=None):
    """(paths, shas, X, cluster labels) for a written fixture — the same
    vectors photo_see would load."""
    index, _identity = ps.load_index(wd)
    batch = ps.load_batch(wd, 1)
    rows = ps.load_rows(wd, batch)
    paths = sorted((r["SourceFile"] for r in rows), key=lambda p: index[p][0])
    shas = [index[p][0] for p in paths]
    X = np.stack([index[p][1] for p in paths]).astype(np.float32)
    from photo_recurrence import cluster as _cluster
    labels, _ = _cluster(X, shas, tau or ps.SEE_TAU)
    return paths, shas, X, labels


def case_carve_out_cluster_keeps_its_look_outside_the_quota(tmp):
    """N-4: a cluster that becomes its own output folder keeps its rung-1
    pick unconditionally. The quota applies to the remaining candidates only.

    The fixture is the starvation case the carve-out exists for: the target
    cluster is one the quota drops, and it is the one that becomes a folder.
    Without the carve-out it gets no look and no `viewed-image:` source, so
    N-4 forbids its name.

    The target is taken FROM THE PLAIN RUN, not guessed as "the smallest" —
    which cluster the quota drops depends on the calibrated share, and this
    case is about the carve-out, not about the arithmetic."""
    wd = three_group_fixture().write(tmp)           # 20/10/4/1/1/1, budget 5
    paths, shas, X, labels = geometry_of(wd)

    plain, _t = ps.run_ladder(X, labels, shas, 5, True)
    looked_at = {int(labels[i]) for i, r, _w in plain if r == 1}
    missed = sorted(set(int(l) for l in labels) - looked_at)
    assert missed, \
        "fixture no longer reproduces the starvation case the carve-out is for"
    smallest = missed[0]

    guaranteed = ps.guaranteed_picks(X, labels, shas, {smallest: []})
    sel, trace = ps.run_ladder(X, labels, shas, 5, True, guaranteed=guaranteed)
    rung1 = trace[0]
    assert rung1["guaranteed"] == 1, rung1
    assert rung1["picked"] == 1 + ps.rung1_quota(5), \
        ("the carve-out pick is outside the quota, not inside it", rung1)
    by_cluster = {int(labels[i]): rung for i, rung, _w in sel}
    assert by_cluster.get(smallest) == 1, (smallest, by_cluster)
    assert len(sel) <= 5, "the carve-out stays inside the total budget"
    assert rung1["guaranteed_dropped"] == 0, rung1

    # A caller that does not floor the budget CAN drop a carve-out pick, and
    # N-4 says those are unconditional — so the trace publishes the violation
    # instead of swallowing it. build_report floors the budget (see
    # case_carve_out_lifts_the_budget_and_the_see_rate_still_holds).
    every = {int(lid): [] for lid in set(int(l) for l in labels)}
    many = ps.guaranteed_picks(X, labels, shas, every)
    _sel2, trace2 = ps.run_ladder(X, labels, shas, 2, True, guaranteed=many)
    assert trace2[0]["guaranteed"] == 2, trace2[0]
    assert trace2[0]["guaranteed_dropped"] == len(many) - 2, trace2[0]
    assert "unconditional" in trace2[0]["note"], trace2[0]["note"]


def case_carve_out_pick_contains_the_named_subject(tmp):
    """The sharper form: where the folder name carries `[who]`, the guaranteed
    pick must be a photo CONTAINING that subject. A landscape medoid from the
    same cluster satisfies rung 1 and satisfies nothing about naming.

    The fixture is a cluster whose bulk is scenery and whose two subject
    frames sit at its edge, so the cluster medoid is provably NOT one of
    them."""
    RNG.seed(11)
    f = Fixture()
    f.many(A, 12)                                   # scenery: the cluster's bulk
    f.add(near(A, basis(5), jitter=0.55), name="WHO_0001.JPG")
    f.add(near(A, basis(5), jitter=0.50), name="WHO_0002.JPG")
    wd = f.write(tmp)
    paths, shas, X, labels = geometry_of(wd)
    lid = int(labels[0])
    assert len(set(int(l) for l in labels)) == 1, "the fixture must be one cluster"
    subject = [i for i, p in enumerate(paths) if Path(p).name.startswith("WHO_")]
    assert len(subject) == 2, subject

    plain = ps.guaranteed_picks(X, labels, shas, {lid: []})[lid]
    assert plain not in subject, \
        "fixture broken: the cluster medoid must not already be a subject frame"

    with_who = ps.guaranteed_picks(X, labels, shas, {lid: subject})[lid]
    assert with_who in subject, (with_who, subject)
    # deterministic: the medoid OF THE SUBJECT SET, not just any member
    assert with_who == ps.medoid(X, shas, subject)
    log(f"cluster medoid {Path(paths[plain]).name} -> subject medoid "
        f"{Path(paths[with_who]).name}")


def case_carve_out_lifts_the_budget_and_the_see_rate_still_holds(tmp):
    """Naming is a second consumer of the budget: every folder needs >= 1
    viewed image, so guaranteed picks are a FLOOR on the budget rather than an
    overflow of it — `validate()` hard-fails on selected != budget, and both
    readings had to be considered. The report carries the count as the cost
    figure the DESIGN asks for."""
    wd = three_group_fixture().write(tmp)           # 6 clusters, rate budget 5
    _paths, _shas, _X, labels = geometry_of(wd)
    every = {int(lid): [] for lid in set(int(l) for l in labels)}
    original = ps.folder_bound_clusters
    try:
        ps.folder_bound_clusters = lambda *a, **k: every
        report = build(wd, rate=0.01)
    finally:
        ps.folder_bound_clusters = original
    cfg = report["config"]
    assert cfg["budget_from_rate"] == 5, cfg
    assert cfg["budget"] == 6, ("the budget floors at one look per folder", cfg)
    assert cfg["naming_carve_out"]["guaranteed_folder_picks"] == 6, cfg
    assert cfg["naming_carve_out"]["budget_lifted_by"] == 1, cfg
    assert len(report["selected"]) == cfg["budget"], report["config"]
    result = ps.validate(report, [], wd / "classify" / "batch-01" / "samples")
    assert "see-rate not met" not in " ".join(result["problems"]), result
    # every cluster now has a look — which is the whole point of the carve-out
    assert {e["cluster"] for e in report["selected"]} == set(every), report["selected"]


def case_carve_out_is_a_no_op_without_a_registry(tmp):
    """The carve-out reads the PACK REGISTRY and nothing else — not the
    recurrence census. No pack, no registry, no picks: an unbound run must
    produce exactly the ladder it produced before VS-3 existed."""
    assert ps.folder_bound_clusters() == {}
    assert ps.folder_bound_clusters(["a"], [0], {}) == {}
    assert ps.folder_bound_clusters(["a"], [0], None, [{"verdict": "accept"}]) == {}
    wd = three_group_fixture().write(tmp)
    report = build(wd, rate=0.10)
    carve = report["config"]["naming_carve_out"]
    assert carve["guaranteed_folder_picks"] == 0, carve
    assert carve["with_named_subject"] == 0, carve
    assert report["config"]["subject_registry"]["subjects"] == 0, report["config"]
    assert report["ladder"][0]["guaranteed"] == 0, report["ladder"][0]


def write_subject_registry(pack_dir, subjects):
    """A VS-3 subject registry inside an existing pack.

    `subjects` is a list of {name, active, vectors, forms_folder?,
    identity_vectors?}. Every value is invented — the engine ships with zero
    owner facts and so does its test suite. Exemplars are written through the
    real add_exemplar(), so they can only enter under `viewed-image`
    provenance here too.

    `identity_vectors` is parallel to `vectors` when given, and an entry of
    None is the frame photo_identity called `no-subject`: a zero row, which
    the registry refuses as identity evidence while keeping the exemplar. It
    is written as a real zero vector rather than skipped, so the fixture goes
    down the same path the defect does."""
    import photo_subjects as psub

    registry = psub.Registry(directory=Path(pack_dir) / "photo-subjects")
    for spec in subjects:
        subject = registry.create_subject(name=spec.get("name"),
                                          who="relation-word", kind="class-word",
                                          active=spec.get("active"))
        if "forms_folder" in spec:
            subject.record["forms_folder"] = spec["forms_folder"]
        id_vectors = spec.get("identity_vectors")
        for j, vec in enumerate(spec["vectors"]):
            source = f"/raw/{subject.subject_id}-{j}.HEIC"
            # VS-4: a promotion must SHOW the look, so the fixture writes the
            # see-report and thumbnail a real one leaves behind.
            evidence = view_fixture.make_look(
                Path(pack_dir).parent / "_look", source,
                batch=int(subject.subject_id.split("-")[1]) * 100 + j)
            id_vec = None if id_vectors is None else id_vectors[j]
            if id_vectors is not None and id_vec is None:
                id_vec = np.zeros(ID_DIM, dtype=np.float32)
            registry.add_exemplar(subject.subject_id, vec,
                                  f"sha256:{subject.subject_id}-{j}", source,
                                  confirmed_by="viewed-image", identity=IDENTITY,
                                  evidence=evidence, identity_vector=id_vec,
                                  identity_space=(ID_SPACE if id_vectors is not None
                                                  else None))
    registry.save()
    return registry


def pack_with_subjects(tmp, subjects, owner="betauser00"):
    """-> a resolved Pack whose registry holds `subjects`."""
    import photo_profile

    pack_dir = write_pack(tmp / "packs", owner)
    write_subject_registry(pack_dir, subjects)
    return photo_profile.resolve_pack(explicit=pack_dir / "photo-profile.json")


def write_pack(root, owner, profile=None, entities=None, exemplars=0):
    """A memory pack on disk, the shape photo_profile.resolve_pack expects.
    Every value here is invented: the engine ships with zero owner facts and
    so does its test suite."""
    pack = Path(root) / owner
    (pack / "photo-subjects").mkdir(parents=True, exist_ok=True)
    (pack / f"photo-owner-{owner}.md").write_text(f"# {owner}\n")
    (pack / "photo-profile.json").write_text(json.dumps(profile if profile is not None
                                                        else BLANK_PROFILE))
    if entities is not None:
        (pack / "photo-entities.json").write_text(json.dumps(entities))
    for k in range(exemplars):
        (pack / "photo-subjects" / f"exemplar-{k}.json").write_text("{}")
    return pack


# What a pack created from templates/photo-memory/_template holds before the
# owner has answered anything: identity, a language, engine thresholds.
BLANK_PROFILE = {
    "_comment": "template scaffolding",
    "owner": {"slug": "betauser00", "display": "Beta User"},
    "language": "en",
    "own_camera_makes": [],
    "home_locations": [],
    "pets": [],
    "naming_spec": {"types": []},
    "cluster_defaults": {"away_km": 3, "away_km_answered": False,
                         "jump_km": 30, "gap_days": 30, "max_batch": 300},
    "sampling": {"gps_pct": 0.10, "no_gps_pct": 0.05, "min_samples": 10,
                 "max_samples": 40},
}


def case_benchmark_refuses_a_pack_that_is_not_blank(tmp):
    """tests/see_replay.py --benchmark scores a COLD START. If any owner fact
    leaked into the pack, the number it produces looks like the cold-start
    number and is not one, so the assertion is a hard failure, never a
    warning."""
    import photo_profile
    import see_replay as sr

    def resolve(pack_dir):
        return photo_profile.resolve_pack(explicit=pack_dir / "photo-profile.json")

    blank = resolve(write_pack(tmp / "packs", sr.BENCHMARK_OWNER))
    assert blank.owner == sr.BENCHMARK_OWNER, blank.owner
    assert sr.owner_facts_in(blank) == [], sr.owner_facts_in(blank)
    assert sr.assert_blank_sheet(blank, sr.BENCHMARK_OWNER) is True

    def must_fail(pack, why, expect):
        try:
            sr.assert_blank_sheet(pack, sr.BENCHMARK_OWNER)
        except AssertionError as exc:
            assert expect in str(exc), (why, exc)
        else:
            raise AssertionError(f"a benchmark accepted {why}")

    must_fail(photo_profile.Pack(), "no pack at all", "named cold-start owner")
    must_fail(resolve(write_pack(tmp / "other", "SomeoneElse")),
              "another owner's pack", "hidden ground truth")

    # each leak channel, one at a time
    leaked = dict(BLANK_PROFILE, home_locations=[{"name": "somewhere"}])
    must_fail(resolve(write_pack(tmp / "p1", sr.BENCHMARK_OWNER, leaked)),
              "a home location", "home_locations")
    vocab = dict(BLANK_PROFILE, naming_spec={"types": ["invented-type"]})
    must_fail(resolve(write_pack(tmp / "p2", sr.BENCHMARK_OWNER, vocab)),
              "naming vocabulary", "naming_spec")
    labels = dict(BLANK_PROFILE,
                  visual_sorting={"scene_labels": {"x": ["a photo of x"]}})
    must_fail(resolve(write_pack(tmp / "p3", sr.BENCHMARK_OWNER, labels)),
              "an owner label set", "visual_sorting.scene_labels")
    must_fail(resolve(write_pack(tmp / "p4", sr.BENCHMARK_OWNER,
                                 entities={"pets": [{"name": "invented"}]})),
              "a pack entity", "photo-entities.json:pets")
    must_fail(resolve(write_pack(tmp / "p5", sr.BENCHMARK_OWNER, exemplars=2)),
              "visual exemplars", "photo-subjects/")
    # empty containers are not facts
    assert sr.owner_facts_in(resolve(write_pack(
        tmp / "p6", sr.BENCHMARK_OWNER, entities={"pets": [], "people": []}))) == []


def case_replay_header_states_which_pack_it_ran_against(tmp):
    """Every report says which pack produced its numbers — in both modes, not
    only the benchmark one."""
    import photo_profile
    import see_replay as sr

    state, line = sr.pack_state(photo_profile.Pack(), benchmark=False)
    assert "pack:" in line and "NONE" in line, line
    assert state["owner"] is None and state["blank_sheet"] is False, state
    assert state["mode"] == "as-configured", state

    pack = photo_profile.resolve_pack(
        explicit=write_pack(tmp / "packs", sr.BENCHMARK_OWNER) / "photo-profile.json")
    state, line = sr.pack_state(pack, benchmark=True)
    assert sr.BENCHMARK_OWNER in line and "BLANK SHEET verified" in line, line
    assert "benchmark" in line, line
    assert state["blank_sheet"] is True and state["owner_facts"] == [], state
    assert state["snapshot"]["files"] >= 2, state          # profile + owner file

    loaded = photo_profile.resolve_pack(explicit=write_pack(
        tmp / "loaded", "SomeoneElse",
        dict(BLANK_PROFILE, pets=[{"name": "invented"}])) / "photo-profile.json")
    state, line = sr.pack_state(loaded, benchmark=False)
    assert "1 owner fact(s)" in line, line
    assert state["blank_sheet"] is False, state


def case_a_run_type_is_supplied_and_never_guessed(tmp):
    """EV-9 names the run type as part of the header, so `pack_state()` takes
    it as an explicit argument with NO default. A caller that omits it gets a
    TypeError, and a caller that invents one gets a ValueError — neither can
    reach a reader as a header that quietly names the wrong tier."""
    import pack_state as pks
    import photo_profile

    pack = photo_profile.resolve_pack(
        explicit=write_pack(tmp / "packs", pks.BENCHMARK_OWNER)
        / "photo-profile.json")

    try:
        pks.pack_state(pack, benchmark=False)
    except TypeError:
        pass
    else:
        raise AssertionError("pack_state() ran without a run type — a tier "
                             "that can be omitted is a tier that gets guessed")

    for bogus in ("tier 2", "replay", None, "", "TIER2_REPLAY"):
        try:
            pks.pack_state(pack, benchmark=False, run_type=bogus)
        except ValueError as exc:
            assert "unknown run type" in str(exc), (bogus, exc)
        except Exception as exc:                    # noqa: BLE001 — see below
            # A VALIDATED set refuses with an explanation naming the run type.
            # Without the check the same call still blows up, but on whatever
            # the formatting happens to hit — a KeyError deep in the header
            # builder, which tells a reader nothing about which tiers exist.
            raise AssertionError(
                f"run type {bogus!r} was not refused cleanly — "
                f"{type(exc).__name__}: {exc}") from None
        else:
            raise AssertionError(f"pack_state() accepted run type {bogus!r}")

    # the three tiers of the Evaluation SPEC, and only those three
    assert set(pks.RUN_TYPES) == {pks.TIER1_FIXTURE, pks.TIER2_REPLAY,
                                  pks.TIER3_DUMP}, sorted(pks.RUN_TYPES)
    for key, label in pks.RUN_TYPES.items():
        _state, line = pks.pack_state(pack, benchmark=False, run_type=key)
        assert label in line, (key, line)


def case_the_header_carries_every_field_ev9_names(tmp):
    """The four things EV-9 requires in a report header — run type, pack slug,
    whether the pack was empty, snapshot id — for a pack that has facts and a
    pack that does not. A header missing any of them describes a run nobody
    can compare with the one beside it."""
    import pack_state as pks
    import photo_profile

    blank_dir = write_pack(tmp / "blank", pks.BENCHMARK_OWNER)
    blank = photo_profile.resolve_pack(
        explicit=blank_dir / "photo-profile.json")
    state, line = pks.pack_state(blank, benchmark=True,
                                 run_type=pks.TIER3_DUMP)
    assert pks.RUN_TYPES[pks.TIER3_DUMP] in line, line          # run type
    assert pks.BENCHMARK_OWNER in line, line                    # pack slug
    assert "BLANK SHEET verified" in line, line                 # empty?
    assert state["snapshot"]["id"] in line, line                # snapshot id
    assert state["run_type"] == pks.TIER3_DUMP, state
    assert state["run_type_label"] == pks.RUN_TYPES[pks.TIER3_DUMP], state

    loaded = photo_profile.resolve_pack(explicit=write_pack(
        tmp / "loaded", "SomeoneElse",
        dict(BLANK_PROFILE, pets=[{"name": "invented"}],
             home_locations=[{"name": "somewhere"}])) / "photo-profile.json")
    state, line = pks.pack_state(loaded, benchmark=False,
                                 run_type=pks.TIER1_FIXTURE)
    assert pks.RUN_TYPES[pks.TIER1_FIXTURE] in line, line
    assert "SomeoneElse" in line, line
    assert "2 owner fact(s)" in line, line     # NOT empty, and how far from it
    assert state["snapshot"]["id"] in line, line
    assert state["blank_sheet"] is False, state

    # ⛔ The tier and EV-1's benchmark/owner split are two axes, and the header
    # carries both. A Tier 1 fixture run is not a benchmark run, and reading
    # one as the other is the substitution the tier framing exists to prevent.
    assert state["mode"] == "as-configured", state
    assert pks.RUN_TYPES[pks.TIER1_FIXTURE] not in state["mode"], state


def case_the_benchmark_label_and_its_guard_are_one_call(tmp):
    """A pack that is not a blank sheet RAISES when the run is labelled a
    benchmark — from `pack_state()` itself, not from a separate assertion a
    later edit could drop while keeping the label. The header and the guard
    fail together or not at all."""
    import pack_state as pks
    import photo_profile
    import see_replay as sr

    leaked = photo_profile.resolve_pack(explicit=write_pack(
        tmp / "leaked", pks.BENCHMARK_OWNER,
        dict(BLANK_PROFILE, home_locations=[{"name": "somewhere"}]))
        / "photo-profile.json")

    # not a benchmark: the facts are reported, and that is all
    state, line = pks.pack_state(leaked, benchmark=False,
                                 run_type=pks.TIER2_REPLAY)
    assert "1 owner fact(s)" in line and state["blank_sheet"] is False, line

    # labelled a benchmark: refused, with the leak named
    for call in (lambda: pks.pack_state(leaked, benchmark=True,
                                        run_type=pks.TIER2_REPLAY),
                 lambda: sr.pack_state(leaked, benchmark=True)):
        try:
            call()
        except AssertionError as exc:
            assert "NOT a blank sheet" in str(exc), exc
            assert "home_locations" in str(exc), exc
        else:
            raise AssertionError("a benchmark header was produced over a pack "
                                 "holding owner facts")

    # ...and there is ONE implementation of all of it. see_replay re-exports
    # the shared module rather than keeping a copy that can drift.
    for name in ("BENCHMARK_OWNER", "BLANK_SHEET_ALLOWED",
                 "BLANK_SHEET_NESTED_FACTS", "has_content", "owner_facts_in",
                 "assert_blank_sheet"):
        assert getattr(sr, name) is getattr(pks, name), name
    assert sr.pack_state(leaked, benchmark=False)[0]["run_type"] == \
        pks.TIER2_REPLAY, "see_replay is a Tier 2 replay and says so"


def case_the_timeline_gate_reads_exif_not_the_dump_name(tmp):
    """The trap the benchmark keeps 7 stray files for: a matcher that infers
    the era from the FOLDER it is sorting rather than from each file's own
    EXIF date. Here the dump is named for one era and every file in it was
    captured in another; the subject active in the FILES' era must match, and
    the subject active in the FOLDER'S era must not."""
    wd = three_group_fixture(loners=0).write(tmp, "2023")   # files are 2026-05
    assert wd.name == "2023"
    pack = pack_with_subjects(tmp, [
        {"name": "Name-One", "active": ["2026-05", "2026-05"],
         "vectors": [A], "forms_folder": False},
        {"name": "Name-Two", "active": ["2023-01", "2023-12"],
         "vectors": [B], "forms_folder": False}])

    report = build(wd, rate=0.30, pack=pack)
    verdicts = report["diagnostics"]["subject_verdicts"]
    assert report["config"]["subject_registry"]["subjects"] == 2, report["config"]
    assert verdicts["accept"] == 20, verdicts        # cluster A, all of it
    assert verdicts["gray"] == 0, verdicts
    log(f"dump named {wd.name}, files dated 2026-05: {verdicts}")

    # the subject whose range matches the FOLDER name matched nothing, even
    # though its own cluster (B, 10 files) is right there in the batch
    matched = {r["path"] for r in report["selected"] if r["rung"] == 2}
    assert not matched, matched


def case_a_gray_zone_match_reaches_rung_2(tmp):
    """Rung 2 with a registry behind it. A file the registry half-recognises is
    exactly the file a pair of eyes settles, so it is picked before outliers
    and before the diversity fill."""
    wd = three_group_fixture(loners=0).write(tmp)
    # the exemplar sits 0.75 from cluster A: between gray_low and accept, so
    # every A file is half-recognised and nothing else is recognised at all
    pack = pack_with_subjects(tmp, [
        {"name": "Name-One", "active": ["2026-05", "2026-05"],
         "vectors": [blend(A, basis(15), 0.75)], "forms_folder": False}])

    report = build(wd, rate=0.20, pack=pack)
    trace = {t["rung"]: t for t in report["ladder"]}
    assert trace[2]["status"] == "filled", trace[2]
    assert trace[2]["registry_subjects"] == 1, trace[2]
    assert report["diagnostics"]["subject_verdicts"]["gray"] == 20, \
        report["diagnostics"]["subject_verdicts"]
    picked = [r for r in report["selected"] if r["rung"] == 2]
    assert picked, trace[2]
    assert all(r["cluster_size"] == 20 for r in picked), picked
    # rung 2 is served before outliers and before the diversity fill
    assert trace[3]["picked"] == 0 and trace[5]["picked"] == 0, trace

    # gray_zone_always_seen switches the rung off, and only that rung
    off = build(wd, rate=0.20, pack=pack,
                profile={"visual_sorting": {"gray_zone_always_seen": False}})
    off_trace = {t["rung"]: t for t in off["ladder"]}
    assert off_trace[2]["picked"] == 0, off_trace[2]
    assert off_trace[2]["status"] == "off", off_trace[2]
    assert off_trace[2]["available"] == 20, off_trace[2]
    assert off_trace[1]["picked"] == trace[1]["picked"], "rung 1 must not move"


def case_the_carve_out_fires_for_a_folder_forming_subject(tmp):
    """The N-4 carve-out, end to end and from the PACK REGISTRY — the only
    sanctioned source. The cluster that carries the named subject keeps a
    rung-1 look outside the quota, and the look is a photo containing it."""
    RNG.seed(11)
    f = Fixture()
    f.many(A, 20)                                    # the big cluster
    f.many(B, 4)                                     # the subject's cluster
    wd = f.write(tmp)
    pack = pack_with_subjects(tmp, [
        {"name": "Name-One", "active": ["2026-05", None], "vectors": [B]}])

    report = build(wd, rate=0.10, pack=pack)
    carve = report["config"]["naming_carve_out"]
    assert carve["guaranteed_folder_picks"] == 1, carve
    assert carve["with_named_subject"] == 1, carve
    assert report["ladder"][0]["guaranteed"] == 1, report["ladder"][0]

    guaranteed = [r for r in report["selected"]
                  if r["rung"] == 1 and "carve-out" in r["reason"]]
    assert len(guaranteed) == 1, guaranteed
    # the guaranteed look is a photo of the subject, not a frame from the
    # biggest cluster: N-4 needs a behaviour to read off it
    assert guaranteed[0]["cluster_size"] == 4, guaranteed[0]

    # an owner who does not want that subject foldered turns the carve-out off
    without = build(wd, rate=0.10, pack=pack_with_subjects(
        tmp / "b", [{"name": "Name-One", "active": ["2026-05", None],
                     "vectors": [B], "forms_folder": False}]))
    assert without["config"]["naming_carve_out"]["guaranteed_folder_picks"] == 0, \
        without["config"]["naming_carve_out"]
    log("carve-out fires from the registry, and only for a folder-forming subject")


def case_rung_4_fires_once_a_registry_can_be_asked(tmp):
    """The conjunction becomes askable. One cluster, so rung 3 has no
    candidates; a registry that recognises none of these files; scene vectors
    nowhere near them — so every file is 'no subject AND no scene'."""
    RNG.seed(11)
    wd = Fixture().many(basis(25), 12).write(tmp)
    pack = pack_with_subjects(tmp, [
        {"name": "Name-One", "active": ["2026-05", None], "vectors": [A],
         "forms_folder": False}])

    report = build(wd, rate=0.10, pack=pack)
    trace = {t["rung"]: t for t in report["ladder"]}
    assert trace[4]["status"] == "filled", trace[4]
    assert trace[4]["available"] == 12, trace[4]
    assert trace[4]["picked"] >= 1, trace[4]
    assert report["diagnostics"]["subject_verdicts"]["none"] == 12, \
        report["diagnostics"]["subject_verdicts"]

    # and it is a CONJUNCTION: the same files with a registry that recognises
    # them are no longer 'unknown', even though the scene half is unchanged
    known = build(wd, rate=0.10, pack=pack_with_subjects(
        tmp / "b", [{"name": "Name-One", "active": ["2026-05", None],
                     "vectors": [basis(25)], "forms_folder": False}]))
    known_trace = {t["rung"]: t for t in known["ladder"]}
    assert known_trace[4]["available"] == 0, known_trace[4]
    assert known["diagnostics"]["no_scene_signal"] == \
        report["diagnostics"]["no_scene_signal"], "the scene half must be unchanged"


def case_rung_4_needs_an_eligible_subject_not_just_a_record(tmp):
    """A registry that HOLDS records but could not LOOK must leave rung 4
    inert. Gating on the record count instead fires the whole rung on a pack
    that cannot recognise anything, and rung 4 sits above rung 5, so it would
    displace the diversity fill across the batch.

    Two packs look loaded and recognise nothing: a pack of unconfirmed drafts
    (records, no exemplars — the normal state after the recurrence census
    drafts candidates and before the first vision confirmation) and a pack
    whose subjects are all out of era. Both report `eligible == 0`, which is
    UNKNOWN, not 'no subject'."""
    quiet = [{"signal": False}]

    # 1. no registry answer at all
    assert ps.unknown_files([None], quiet) == []
    # 2. records, no exemplars -> could not look
    assert ps.unknown_files([{"verdict": "none", "eligible": 0}], quiet) == []
    # 3. exemplars, but none eligible at this file's date -> could not look
    assert ps.unknown_files([{"verdict": "none", "eligible": 0}], quiet) == []
    # 4. a subject WAS eligible and matched nobody -> genuinely no subject
    assert ps.unknown_files([{"verdict": "none", "eligible": 1}], quiet) == [0]
    # a named match is never 'unknown', however eligible it was
    assert ps.unknown_files([{"verdict": "accept", "eligible": 1}], quiet) == []

    RNG.seed(11)
    wd = Fixture().many(basis(25), 12).write(tmp)

    # end to end: a pack of drafts with no exemplars leaves the ladder exactly
    # where an absent pack leaves it
    drafts = build(wd, rate=0.10, pack=pack_with_subjects(
        tmp / "drafts", [{"name": None, "active": [None, None], "vectors": []}]))
    unbound = build(wd, rate=0.10)
    for rung in (2, 4):
        drafted = {t["rung"]: t for t in drafts["ladder"]}[rung]
        assert drafted["status"] == "inert", drafted
        assert drafted["available"] == 0, drafted
        assert drafted["registry_subjects"] == 0 if rung == 2 else True, drafted
    assert [r["path"] for r in drafts["selected"]] == \
        [r["path"] for r in unbound["selected"]], \
        "a pack that cannot recognise anything moved the selection"

    # and the same fixture with an out-of-era subject: exemplars it may not use
    stale = build(wd, rate=0.10, pack=pack_with_subjects(
        tmp / "stale", [{"name": "Name-One", "active": ["2019-01", "2019-12"],
                         "vectors": [basis(25)], "forms_folder": False}]))
    stale_trace = {t["rung"]: t for t in stale["ladder"]}
    assert stale_trace[4]["available"] == 0, stale_trace[4]
    assert [r["path"] for r in stale["selected"]] == \
        [r["path"] for r in unbound["selected"]], \
        "an out-of-era registry moved the selection"
    log("records without eligibility leave rungs 2 and 4 inert")


def case_lookalike_subjects_are_a_question_in_the_report(tmp):
    """Two subjects the registry cannot tell apart on one file: the report
    carries ONE question for the pair, with a contact sheet, and nothing in
    this stage merges them."""
    RNG.seed(11)
    wd = three_group_fixture(loners=0).write(tmp)
    pack = pack_with_subjects(tmp, [
        {"name": "Name-One", "active": ["2026-05", None], "vectors": [A],
         "forms_folder": False},
        {"name": "Name-Two", "active": ["2026-05", None],
         "vectors": [near(A, basis(7), jitter=0.02)], "forms_folder": False}])

    report = build(wd, rate=0.10, pack=pack)
    questions = report["diagnostics"]["subject_questions"]
    assert len(questions) == 1, questions
    q = questions[0]
    assert q["auto_merge"] is False and q["resolved_by"] == "human", q
    assert q["subject_ids"] == ["subj-0001", "subj-0002"], q
    assert q["files"] == 20 and len(q["contact_sheet"]) == 4, q
    assert report["diagnostics"]["subject_verdicts"]["question"] == 20, \
        report["diagnostics"]["subject_verdicts"]
    # a question is not an accept: an ambiguous file may not claim a folder
    assert report["config"]["naming_carve_out"]["guaranteed_folder_picks"] == 0
    log(f"one question for {q['subject_ids']} over {q['files']} files")


def id_unit(i):
    v = np.zeros(ID_DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def case_a_confirmed_subject_the_identity_space_cannot_use_is_reported(tmp):
    """The omission this report exists for: the owner confirmed a subject, its
    confirmed frames held no detected subject, and it therefore leaves
    `identity_recognisers` at MATCH time. `attach_exemplars()` spoke when the
    vector was refused, which is a different run from the one that needed it,
    so until now a reader saw only a `recognising` count one lower than the
    number of subjects they had confirmed.

    The report names it by id, and the run is otherwise untouched: no refusal,
    no exception, and the same files selected."""
    RNG.seed(11)
    wd = Fixture().many(basis(25), 12).write(tmp)
    pack = pack_with_subjects(tmp, [
        {"name": "Name-One", "active": ["2026-05", None], "vectors": [A],
         "identity_vectors": [id_unit(0)], "forms_folder": False},
        # confirmed on a frame with no animal in it -> a zero row, refused as
        # identity evidence while the exemplar itself stands
        {"name": "Name-Two", "active": ["2026-05", None], "vectors": [basis(9)],
         "identity_vectors": [None], "forms_folder": False}])

    report = build(wd, rate=0.10, pack=pack)
    block = report["config"]["subject_identity"]
    assert report["config"]["subject_registry"]["recognising"] == 2, block
    assert block["recognising"] == 1, block
    assert block["silent_recognisers"] == {"count": 1,
                                           "subjects": ["subj-0002"]}, block
    # true, so this one subject is a defect the owner can act on rather than a
    # pack that never ran the stage
    assert block["pack_speaks_identity"] is True, block

    # ⛔ a REPORT and nothing else. The same fixture with no identity vectors
    # anywhere selects exactly the same files — this run has no identity index
    # for its own files either way, so the identity space decided nothing and
    # must go on deciding nothing.
    plain = build(wd, rate=0.10, pack=pack_with_subjects(tmp / "b", [
        {"name": "Name-One", "active": ["2026-05", None], "vectors": [A],
         "forms_folder": False},
        {"name": "Name-Two", "active": ["2026-05", None], "vectors": [basis(9)],
         "forms_folder": False}]))
    assert [r["path"] for r in plain["selected"]] == \
        [r["path"] for r in report["selected"]], "the report moved the selection"

    # ...and there the SAME two subjects are silent for the ordinary reason,
    # which is what the sibling key is for.
    other = plain["config"]["subject_identity"]
    assert other["silent_recognisers"] == {"count": 2,
                                           "subjects": ["subj-0001", "subj-0002"]}, other
    assert other["pack_speaks_identity"] is False, other
    assert other["index"] is None, other
    log("a confirmed subject with no identity vector is named in the report")


def case_rungs_2_and_4_are_a_no_op_without_a_registry(tmp):
    """Hard constraint: with no `photo-subjects/` entries the two registry
    rungs must return exactly what they returned before VS-3 — nothing — and
    say `inert` rather than `empty`, because "this file has no subject" is
    UNKNOWN with no registry, not false."""
    wd = three_group_fixture().write(tmp)
    report = build(wd, rate=0.50)
    trace = {t["rung"]: t for t in report["ladder"]}
    assert set(trace) == {1, 2, 3, 4, 5}, sorted(trace)
    for rung in (2, 4):
        assert trace[rung]["status"] == "inert", trace[rung]
        assert trace[rung]["picked"] == 0, trace[rung]
        assert trace[rung]["available"] == 0, trace[rung]
    assert ps.subject_matches() == [] and ps.unknown_files() == []
    # rung 4 is a conjunction: the scene half alone must not fire it
    assert ps.unknown_files([None], [{"signal": False}]) == []
    assert report["diagnostics"]["subject_verdicts"] == {
        "accept": 0, "gray": 0, "question": 0, "none": 0}
    # the scene half of rung 4 is reported as a statistic and steers nothing
    assert "no_scene_signal" in report["diagnostics"]


def case_selection_is_deterministic(tmp):
    wd = three_group_fixture().write(tmp)
    first = build(wd, rate=0.30)
    second = build(wd, rate=0.30)
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == \
        json.dumps(second, ensure_ascii=False, sort_keys=True), \
        "two runs over the same input must be byte-identical"


def case_cli_rerun_is_byte_identical_modulo_run_id(tmp):
    wd = three_group_fixture().write(tmp)
    run_see(wd, "--no-thumbnails")
    first = report_of(wd)
    run_see(wd, "--no-thumbnails", "--force")
    second = report_of(wd)
    first.pop("run_id"), second.pop("run_id")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def case_cli_refuses_overwrite(tmp):
    wd = three_group_fixture().write(tmp)
    run_see(wd, "--no-thumbnails")
    proc = run_see(wd, "--no-thumbnails", expect_fail=True)
    assert "--force" in proc.stdout + proc.stderr


def case_cluster_labels_propagate(tmp):
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    samples = wd / "classify" / "batch-01" / "samples"
    biggest = max(report["clusters"], key=lambda c: c["size"])
    rep = biggest["representative"]
    entries = ps.apply_decisions(report, {rep: "爬山"}, samples)
    by_path = {e["path"]: e for e in entries}
    assert by_path[rep]["provenance"] == "viewed-image:", by_path[rep]
    others = [m for m in biggest["members"] if m != rep]
    assert others, biggest
    for m in others:
        assert by_path[m]["label"] == "爬山", by_path[m]
        assert by_path[m]["provenance"] == "clip-propagated:", by_path[m]
        assert by_path[m]["from"] == rep
    log(f"one look labeled {1 + len(others)} files")


def case_cluster_label_conflict_is_flagged_not_dropped(tmp):
    """F12. Two viewed files in one visual cluster returning different labels
    is not a rare race — rung 5 only runs when every cluster already has a
    representative, so every rung-5 pick is a second look at a represented
    cluster. The winner stays deterministic (lowest-sorted path) so
    propagation does not change; what must not happen is the disagreement
    disappearing without a word."""
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    samples = wd / "classify" / "batch-01" / "samples"
    biggest = max(report["clusters"], key=lambda c: c["size"])
    seen = {e["path"] for e in report["selected"]}
    members = sorted(m for m in biggest["members"] if m in seen)
    if len(members) < 2:                 # force the second look rung 5 produces
        extra = next(m for m in sorted(biggest["members"]) if m not in seen)
        report["selected"].append({"path": extra, "sha256": "x", "rung": 5,
                                   "reason": "farthest-point diversity fill",
                                   "cluster": biggest["cluster"],
                                   "cluster_size": biggest["size"],
                                   "time": "2026-05-03 09:00", "scene": None,
                                   "sample": None})
        members = sorted([members[0], extra]) if members else sorted(
            [extra, next(m for m in sorted(biggest["members"]) if m in seen)])
    first, second = members[0], members[1]

    entries = ps.apply_decisions(report, {first: "爬山", second: "聚餐"}, samples)
    conflicts = report["cluster_label_conflicts"]
    assert len(conflicts) == 1, conflicts
    c = conflicts[0]
    assert c["cluster"] == biggest["cluster"], c
    assert (c["propagated"], c["disagreeing"]) == ("爬山", "聚餐"), c
    assert c["from"] == first and c["seen_as"] == second, c

    by_path = {e["path"]: e for e in entries}
    assert by_path[first]["label"] == "爬山", by_path[first]
    assert by_path[second]["label"] == "聚餐", \
        "the second look keeps its own viewed-image: label"
    assert by_path[second]["provenance"] == "viewed-image:", by_path[second]
    result = ps.validate(report, entries, samples)
    assert any("cluster_label_conflicts" in w for w in result["warnings"]), result
    assert result["cluster_label_conflicts"] == conflicts

    # agreement must NOT be reported as a conflict
    agree = ps.apply_decisions(report, {first: "爬山", second: "爬山"}, samples)
    assert report["cluster_label_conflicts"] == [], report["cluster_label_conflicts"]
    assert len(agree) == len(entries)


def case_a_label_without_provenance_is_caught(tmp):
    """F10 — "provenance present" is the DESIGN's fourth validator check and
    was the only one not implemented: it held by construction and nothing
    asserted it. The invariant is a biconditional; an unlabeled file
    (label None, provenance None) is the legal third state."""
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    samples = wd / "classify" / "batch-01" / "samples"
    rep = max(report["clusters"], key=lambda c: c["size"])["representative"]
    entries = ps.apply_decisions(report, {rep: "爬山"}, samples)

    clean = ps.validate(report, entries, samples)
    assert clean["checked"]["provenance_present"] is True, clean
    assert not clean["problems"], clean
    assert any(e["label"] is None and e["provenance"] is None
               for e in report["provisional"]), \
        "unlabeled files must exist in this fixture, and must stay legal"

    victim = next(e for e in entries if e["provenance"] == "clip-propagated:")
    victim["provenance"] = None
    broken = ps.validate(report, entries, samples)
    assert broken["ok"] is False and broken["checked"]["provenance_present"] is False
    assert any("no provenance prefix" in p for p in broken["problems"]), broken

    victim["provenance"], victim["label"] = "clip-propagated:", None
    other = ps.validate(report, entries, samples)
    assert other["ok"] is False, other
    assert any("with no label" in p for p in other["problems"]), other


def case_clip_label_can_never_claim_viewed_image(tmp):
    """The 2026-07-20 guard. A propagated label rewritten to claim the model
    looked at it must be caught mechanically, not by review."""
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    samples = wd / "classify" / "batch-01" / "samples"
    biggest = max(report["clusters"], key=lambda c: c["size"])
    rep = biggest["representative"]
    entries = ps.apply_decisions(report, {rep: "爬山"}, samples)

    victim = next(e for e in entries if e["provenance"] == "clip-propagated:")
    victim["provenance"] = "viewed-image:"
    try:
        ps.assert_no_fabrication(entries, {e["path"] for e in report["selected"]},
                                 samples)
    except AssertionError as exc:
        assert "never selected it" in str(exc) or "fabrication" in str(exc), exc
    else:
        raise AssertionError("a clip-propagated label was promoted to viewed-image "
                             "and nothing objected")


def case_viewed_image_needs_a_real_thumbnail(tmp):
    """A file the controller DID select, but whose thumbnail is not on disk,
    still may not claim viewed-image — nothing was there to look at."""
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    samples = wd / "classify" / "batch-01" / "samples"
    rep = report["selected"][0]["path"]
    entries = ps.apply_decisions(report, {rep: "爬山"}, samples)
    entry = next(e for e in entries if e["path"] == rep)
    for f in samples.iterdir():
        f.unlink()
    try:
        ps.assert_no_fabrication(entries, {rep}, samples)
    except AssertionError as exc:
        assert "nothing was there to look at" in str(exc), exc
    else:
        raise AssertionError("viewed-image: was accepted with no thumbnail on disk")
    assert entry["provenance"] == "viewed-image:"


def case_apply_rejects_a_decision_for_an_unselected_file(tmp):
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    samples = wd / "classify" / "batch-01" / "samples"
    chosen = {e["path"] for e in report["selected"]}
    stranger = next(p["path"] for p in report["provisional"] if p["path"] not in chosen)
    try:
        ps.apply_decisions(report, {stranger: "爬山"}, samples)
    except AssertionError as exc:
        assert "never selected" in str(exc), exc
    else:
        raise AssertionError("a decision was accepted for a file nobody looked at")


def case_apply_names_the_right_key_for_a_video_sample(tmp):
    """U3-28 REPRODUCTION. A video's sample is a qlmanage .png, so an agent
    that keys its decisions off `samples/` hands `--apply` a path that differs
    from the source only by extension. The refusal is correct; the bare
    "never selected" message is not, because the controller DID select the
    file. The message must name the key to use."""
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    picked = report["selected"][0]["path"]
    as_thumbnail = str(Path(picked).with_suffix(".png"))
    try:
        ps.apply_decisions(report, {as_thumbnail: "爬山"},
                           wd / "classify" / "batch-01" / "samples")
    except AssertionError as exc:
        msg = str(exc)
        assert "never selected" in msg, msg
        assert picked in msg, f"the correct path is not named: {msg}"
        assert "selected[].path" in msg, f"the fix is not stated: {msg}"
        assert "AMBIGUOUS" not in msg, f"one source, one answer: {msg}"
    else:
        raise AssertionError("a sample-derived key was accepted")


def case_apply_recognises_a_verbatim_sample_filename(tmp):
    """U3-28 REPRODUCTION, the other direction. The sample name is
    time-prefixed as well as re-extensioned, so it matches `selected[].sample`
    and not `selected[].path` -- both lookups are needed."""
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    entry = next(e for e in report["selected"] if e.get("sample"))
    assert Path(entry["sample"]).stem != Path(entry["path"]).stem, \
        "fixture no longer exercises the time-prefixed sample name"
    try:
        ps.apply_decisions(report, {entry["sample"]: "爬山"},
                           wd / "classify" / "batch-01" / "samples")
    except AssertionError as exc:
        msg = str(exc)
        assert "never selected" in msg, msg
        assert entry["path"] in msg, f"the correct path is not named: {msg}"
    else:
        raise AssertionError("a verbatim sample filename was accepted")


def case_a_genuine_stranger_gets_no_sample_hint(tmp):
    """U3-28 GUARD (passes on unfixed code). A file nobody looked at is not a
    mis-keyed sample, and must not be dressed up as one -- the hint fires on a
    stem match or not at all."""
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    chosen = {e["path"] for e in report["selected"]}
    stranger = next(p["path"] for p in report["provisional"] if p["path"] not in chosen)
    try:
        ps.apply_decisions(report, {stranger: "爬山"},
                           wd / "classify" / "batch-01" / "samples")
    except AssertionError as exc:
        msg = str(exc)
        assert "never selected" in msg, msg
        assert "SAMPLE filenames" not in msg, f"a stranger was called a sample: {msg}"
    else:
        raise AssertionError("a decision was accepted for a file nobody looked at")


def case_an_ambiguous_stem_is_never_resolved(tmp):
    """U3-28 REPRODUCTION, and a guard against over-fixing. Two selected
    files sharing a stem cannot be told apart from a sample name, so the hint
    must say so rather than pick one -- naming a single file there would be
    the wrong-file bug the refusal exists to prevent. It fails on unfixed
    code (no diagnostic at all) AND on a fix that resolves the collision."""
    RNG.seed(11)
    f = Fixture()
    f.many(A, 20)
    f.add(basis(5), name="IMG_TWIN.JPG")
    f.add(near(basis(5), basis(21)), name="IMG_TWIN.MOV")
    wd = f.write(tmp, real_images=True)
    report = build(wd, rate=1.0, thumbnails=True)
    picked = {e["path"] for e in report["selected"]}
    twins = sorted(q for q in picked if Path(q).stem == "IMG_TWIN")
    assert len(twins) == 2, f"fixture did not select both twins: {twins}"
    try:
        ps.apply_decisions(report, {str(Path(twins[0]).with_suffix(".png")): "爬山"},
                           wd / "classify" / "batch-01" / "samples")
    except AssertionError as exc:
        msg = str(exc)
        assert "AMBIGUOUS" in msg, f"a colliding stem was resolved anyway: {msg}"
        for t in twins:
            assert t in msg, f"{t} missing from the ambiguity list: {msg}"
    else:
        raise AssertionError("an ambiguous sample-derived key was accepted")


def case_confident_zero_shot_is_clip_matched_never_viewed(tmp):
    """A file sitting exactly on a class vector is clip-matched: — a label with
    no eyes behind it, and its prefix says so."""
    profile = two_class_profile("爬山", "小貓")
    classes = list(profile["visual_sorting"]["scene_labels"])
    RNG.seed(11)
    f = Fixture()
    f.many(basis(0), 12)                       # on class 0 -> confident
    f.many(unit(basis(0) + basis(1)), 12)      # equidistant -> no margin
    wd = f.write(tmp, classes=classes)
    report = build(wd, rate=0.10, profile=profile)
    chosen = {e["path"] for e in report["selected"]}
    matched = [p for p in report["provisional"]
               if p["provenance"] == "clip-matched:"]
    assert matched, report["diagnostics"]
    for entry in matched:
        assert entry["path"] not in chosen
        assert entry["label"] in classes
    unlabeled = [p for p in report["provisional"] if p["state"] == "unlabeled"]
    assert unlabeled, "the equidistant group must produce no scene signal"
    assert all(p["provenance"] != "viewed-image:" for p in report["provisional"])


def case_exif_screenshot_rule_is_not_weakened(tmp):
    """ONB-12's filename rule decides the file BEFORE the ladder sees it: a
    Screenshot_* file never enters the see pool and never loses its routing."""
    RNG.seed(11)
    f = Fixture()
    f.many(A, 12)
    f.add(near(A, basis(21)), name="Screenshot_20260504-101112.jpg", make="-")
    wd = f.write(tmp)
    report = build(wd, rate=0.50)
    names = {Path(p["path"]).name for p in report["provisional"]}
    assert "Screenshot_20260504-101112.jpg" not in names, names
    assert report["coverage"]["preclass"].get("screenshot") == 1, \
        report["coverage"]["preclass"]
    assert report["coverage"]["pool"] == 12, report["coverage"]


def case_screenshot_suspects_are_flagged_never_routed(tmp):
    """The second detector annotates; it does not move anything (ONB-10)."""
    profile = two_class_profile("截圖", "爬山")
    RNG.seed(11)
    f = Fixture()
    f.many(basis(0), 8)                        # zero-shot says 截圖
    f.many(basis(1), 8)
    wd = f.write(tmp, classes=list(profile["visual_sorting"]["scene_labels"]))
    report = build(wd, rate=0.10, profile=profile)
    suspects = report["diagnostics"]["screenshot_suspects"]
    assert suspects, report["diagnostics"]
    assert "moves nothing" in report["diagnostics"]["screenshot_suspects_note"]
    for path in suspects:
        entry = next(p for p in report["provisional"] if p["path"] == path)
        assert entry["provenance"] in (None, "clip-matched:", "clip-propagated:"), entry


def case_label_file_from_another_model_is_refused(tmp):
    wd = three_group_fixture().write(tmp)
    write_labels(wd / "embed", identity={**IDENTITY, "pretrained_tag": "openai"})
    proc = run_see(wd, "--no-thumbnails", "--force", expect_fail=True)
    assert "different model" in proc.stdout + proc.stderr


def case_label_file_with_other_classes_is_refused(tmp):
    wd = three_group_fixture().write(tmp)
    write_labels(wd / "embed", classes=["爬山", "小貓"])
    proc = run_see(wd, "--no-thumbnails", "--force", expect_fail=True)
    assert "holds classes" in proc.stdout + proc.stderr


def case_no_label_file_still_selects(tmp):
    """The scene axis is optional: rungs 1/3/5 are pure geometry."""
    wd = three_group_fixture().write(tmp, with_labels=False)
    report = build(wd, rate=0.30)
    assert report["scene_labels"]["encoded"] is False
    assert "scene axis is OFF" in report["scene_labels"]["note"]
    assert len(report["selected"]) == report["config"]["budget"] > 0
    assert all(p["provenance"] is None for p in report["provisional"])


def case_a_missing_label_file_warns_the_operator(tmp):
    """D3: the axis being off was stated only inside see-report.json, so a run
    with no matrix wrote a valid report, printed `0 clip-matched` and read as a
    finished result. The operator's channel is stdout, so the warning has to
    fire there — and NOT fire when the axis is on, or it teaches nothing."""
    wd = three_group_fixture().write(tmp, with_labels=False)
    off = run_see(wd, "--no-thumbnails")
    assert "scene axis is OFF" in off.stdout, \
        f"nothing on stdout says the axis is off:\n{off.stdout}"
    assert "--scene-labels" in off.stdout, \
        f"the warning names no remedy:\n{off.stdout}"
    write_labels(wd / "embed")
    on = run_see(wd, "--no-thumbnails", "--force")
    assert "scene axis is OFF" not in on.stdout, \
        f"warned with the label file present:\n{on.stdout}"


def write_identity_index(workdir, dim=6):
    """A synthetic VS-3b index over every embedded row of an existing work
    dir, in the real file layout so `photo_identity.load_index` reads it the
    way it reads a real one."""
    import csv as _csv
    import photo_identity
    embed = Path(workdir) / "embed"
    rows = list(_csv.DictReader(open(embed / "embeddings.csv", newline="")))
    out = [{"SourceFile": r["SourceFile"], "sha256": r.get("sha256", ""),
            "status": photo_identity.STATUS_OK, "kind": "cat",
            "det_score": 0.9, "box": "0,0,10,10", "box_share": "0.5",
            "error": ""} for r in rows]
    with open(embed / "identity.csv", "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=photo_identity.CSV_FIELDS)
        w.writeheader()
        w.writerows(out)
    with open(embed / "identity.npy", "wb") as f:
        np.save(f, np.zeros((len(out), dim), dtype=np.float32))
    (embed / "identity-meta.json").write_text(json.dumps(
        {**photo_identity.meta_identity(dim), "created_at": "2029-01-01 00:00"}))


def case_a_missing_identity_index_warns_the_operator(tmp):
    """⭐ R2 REPRODUCTION. The report ALREADY carried this fact --
    `config.subject_identity.index` is None when photo_identity never ran, and
    the comment beside it is careful to distinguish that from "0 recognised".
    UAT01 (20260904) wrote that None into every see-report of the run and
    nobody read it, so every subject verdict was CLIP, one confirmed subject's
    exemplar bank ended up 60% another animal (D-24), and the pack recorded no
    reason (LL-PHO-105).

    A JSON field is not the operator's channel; stdout is. And it must NOT
    fire when the index is present, or it teaches nothing."""
    wd = three_group_fixture().write(tmp)
    off = run_see(wd, "--no-thumbnails")
    assert "no identity index" in off.stdout, \
        f"nothing on stdout says the identity index is missing:\n{off.stdout}"
    assert "photo_identity.py" in off.stdout, \
        f"the warning names no remedy:\n{off.stdout}"
    write_identity_index(wd)
    on = run_see(wd, "--no-thumbnails", "--force")
    assert "no identity index" not in on.stdout, \
        f"warned with the identity index present:\n{on.stdout}"


def case_failed_rows_are_reported_not_silently_dropped(tmp):
    RNG.seed(11)
    f = Fixture()
    f.many(A, 10)
    f.add(np.zeros(DIM), name="BROKEN_01.JPG", status="failed")
    wd = f.write(tmp)
    report = build(wd, rate=0.50)
    assert report["coverage"]["unembedded_in_pool"] == 1, report["coverage"]
    assert any(p.endswith("BROKEN_01.JPG")
               for p in report["coverage"]["unembedded_paths"])
    assert report["coverage"]["pool"] == 10


def case_validate_catches_a_missing_thumbnail(tmp):
    wd = three_group_fixture().write(tmp)
    report = build(wd, rate=0.30, thumbnails=False)
    result = ps.validate(report, [], wd / "classify" / "batch-01" / "samples")
    assert result["ok"] is False
    assert any("no thumbnail" in p for p in result["problems"]), result


def case_residual_unlabeled_is_a_warning_not_a_failure(tmp):
    """VS-2 labels what the index can carry, which is 64-89% of a real batch.
    The rest fall through to the batch-level classify decision, so a residual
    must be REPORTED, not fatal — a hard failure here would block every run."""
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    samples = wd / "classify" / "batch-01" / "samples"
    rep = report["selected"][0]["path"]
    entries = ps.apply_decisions(report, {rep: "爬山"}, samples)
    assert any(not e.get("label") for e in entries), "fixture should leave a residual"
    result = ps.validate(report, entries, samples)
    assert result["ok"] is True, result
    assert result["problems"] == [], result
    assert any("carry no visual label" in w for w in result["warnings"]), result


def case_owner_pack_supplies_the_label_set(tmp):
    """ONB-10: the label set is owner data. A pack that names its own classes
    wins over the engine's fallback, and the engine's fallback stays zh-TW."""
    default, source = ps.scene_label_set({})
    assert source == "engine fallback"
    assert "爬山" in default and "截圖" in default
    packed, source = ps.scene_label_set(
        {"visual_sorting": {"scene_labels": {"貓": ["a cat"], "山": ["a hill"]}}})
    assert source == "owner pack" and list(packed) == ["貓", "山"], packed
    english, _ = ps.scene_label_set({"language": "en"})
    assert "Screenshots" in english and "截圖" not in english, list(english)


def case_a_non_assertion_crash_is_counted(tmp):
    """The harness testing itself, which is the only way this one can be
    tested: a case that really crashed would report ERROR and fail the suite.

    What is asserted is the DIFFERENCE between the two failures. An
    AssertionError is a case saying "the answer was wrong"; anything else is a
    case that never delivered an answer at all, and until now the second kind
    escaped main(), ended the run and printed no tally — so a suite that had
    executed 25 of 60 cases looked, from its exit code alone, like one broken
    thing."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        crashed = run_case("injected", lambda: 1 / 0)
        asserted = run_case("injected", lambda: (_ for _ in ()).throw(
            AssertionError("wrong answer")))
        fine = run_case("injected", lambda: None)
    lines = out.getvalue().splitlines()
    log(f"harness said: {lines}")
    assert crashed is False, "a crash must count as a failure, not a pass"
    assert asserted is False and fine is True, "the other two verdicts moved"
    assert any(line.startswith("  ERROR") for line in lines), \
        f"a crash is not reported as ERROR: {lines}"
    assert any(line.startswith("  FAIL") for line in lines), \
        f"a wrong answer no longer reports FAIL: {lines}"
    # and the crash says WHICH exception — "it broke" is not a bug report
    assert "ZeroDivisionError" in out.getvalue(), \
        f"the exception type is not named: {lines}"


# =============================================================== R4 ========
# The wire between a confirmed subject and a folder name.
#
# ⭐ Measured in UAT01 (20260904): every see-label the run wrote carried
# `{"subject_kind": "cat"}` and no `subject_id`, so `photo_plan`'s resolver —
# built, working, and covered by its own cases — took its class-word branch on
# all 128 subject-attributed files in one batch alone and every folder was
# named for the species. The id existed the whole time: `registry.match()`
# computes it for every pool file, `folder_bound_clusters()` reads it, and
# then the report kept only a tally.


def write_detection_index(workdir, per_file, dim=6):
    """R3a's index shape — one row per DETECTION, written with photo_identity's
    own field list and read back by its own loader, so the case cannot pass by
    two hand-rolled things agreeing with each other.

    `per_file`: {path: [(det_index, det_count)]}. `det_count` may be "" — that
    is a PRE-R3a row, and it is the blind spot this fixture exists to reach:
    such an index holds the highest-scoring box only, so its single row means
    "an animal was found", never "one animal was there"."""
    import photo_identity
    embed = Path(workdir) / "embed"
    embed.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(per_file):
        for det_index, det_count in per_file[path]:
            rows.append({"SourceFile": path, "sha256": f"sha-{det_index}",
                         "status": photo_identity.STATUS_OK,
                         "det_index": det_index, "det_count": det_count,
                         "kind": "cat", "det_score": 0.9, "box": "0,0,10,10",
                         "box_share": "0.4", "error": ""})
    with open(embed / "identity.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=photo_identity.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    with open(embed / "identity.npy", "wb") as f:
        np.save(f, np.zeros((len(rows), dim), dtype=np.float32))
    (embed / "identity-meta.json").write_text(json.dumps(
        {**photo_identity.meta_identity(dim), "created_at": "2029-01-01 00:00"}))


def kinds_in(entry):
    """-> the subject kinds one written label carries, in order."""
    return [s.get("subject_kind") for s in photo_evidence.subject_list(entry)]


def ids_in(entry):
    """-> every subject id the written label carries, in order.

    ⛔ Read out of the SERIALISED entry rather than off a named key on
    purpose. A case that asserted `entry["subjects"]` would fail on the
    unfixed engine with a KeyError, which proves a key was renamed and
    nothing about what the stage does. This fails there because the ids are
    NOT THERE — the behaviour R4 changes."""
    import re
    return re.findall(r"subj-\d{4,}", json.dumps(entry))


def see_fixture_for_apply(tmp):
    """-> (report, samples_dir, the representative of the biggest cluster)."""
    wd = three_group_fixture().write(tmp, real_images=True)
    report = build(wd, rate=0.30, thumbnails=True)
    samples = wd / "classify" / "batch-01" / "samples"
    rep = max(report["clusters"], key=lambda c: c["size"])["representative"]
    return wd, report, samples, rep


def case_a_decision_names_every_animal_in_the_frame(tmp):
    """⭐ THE R4 REPRODUCTION. A frame holding two animals is two names to log,
    never a frame to refuse (owner decision, 20260904). Before R4 the decision
    could not say it: `apply_decisions` copied at most one `subject_id` off
    the value, so the second animal was dropped between the model's answer and
    the file it was written to — silently, at exit 0, with a valid-looking
    label file as the evidence."""
    _wd, report, samples, rep = see_fixture_for_apply(tmp)
    entries = ps.apply_decisions(report, {rep: {
        "label": "A cat and a dog on a sofa",
        "subjects": [{"subject_kind": "cat"},
                     {"subject_kind": "dog"}]}}, samples)
    by_path = {e["path"]: e for e in entries}
    kinds = kinds_in(by_path[rep])
    assert kinds == ["cat", "dog"], by_path[rep]
    log(f"both animals reached the label: {kinds}")


def case_both_names_propagate_to_the_whole_cluster(tmp):
    """WHO travels with the label and by the same rules. A cluster's members
    are the same scene, so a representative holding two animals claims two for
    its members — at `clip-propagated:` strength, which is what says nobody
    looked at them.

    ⛔ The count is asserted, not just the presence: propagating the FIRST id
    and dropping the second is the failure this case exists for, and a member
    carrying one id looks entirely normal on its own."""
    _wd, report, samples, rep = see_fixture_for_apply(tmp)
    biggest = max(report["clusters"], key=lambda c: c["size"])
    entries = ps.apply_decisions(report, {rep: {
        "label": "A cat and a dog",
        "subjects": [{"subject_kind": "cat"},
                     {"subject_kind": "dog"}]}}, samples)
    by_path = {e["path"]: e for e in entries}
    others = [m for m in biggest["members"] if m != rep]
    assert others, biggest
    for m in others:
        assert kinds_in(by_path[m]) == ["cat", "dog"], by_path[m]
        assert by_path[m]["subject_provenance"] == "clip-propagated:", by_path[m]
    assert by_path[rep]["subject_provenance"] == "viewed-image:", by_path[rep]
    log(f"one look carried 2 names onto {1 + len(others)} files")


def case_a_decision_may_not_say_who_is_in_the_frame_twice(tmp):
    """⛔ REPRODUCTION of a SILENT DROP, not a guard. Before R4 the singular
    key was the only one read, so a decision carrying both shapes lost its
    whole `subjects` list without a word — and the label it wrote was
    well-formed, so nothing downstream could tell. Refusing is the only
    outcome that cannot be mistaken for an answer: the two keys may name
    different animals and this stage has no way to choose."""
    _wd, report, samples, rep = see_fixture_for_apply(tmp)
    try:
        ps.apply_decisions(report, {rep: {
            "label": "Cat", "subject_kind": "cat",
            "subjects": [{"subject_kind": "dog"}]}}, samples)
    except AssertionError as exc:
        assert "subjects" in str(exc) and "subj" not in str(exc).split("carries")[0], exc
        log(f"refused: {exc}")
        return
    raise AssertionError("a decision saying WHO two different ways was accepted, "
                         "and one of the two statements went nowhere")


def case_a_malformed_subjects_list_is_refused_not_absorbed(tmp):
    """Every entry names an id or a kind. An entry naming neither is not an
    empty subject, it is a decision nobody can act on, and absorbing it would
    put a `{}` on the label where a reader has to guess what was meant."""
    _wd, report, samples, rep = see_fixture_for_apply(tmp)
    for bad in ({"subjects": {"subject_id": "subj-0003"}},   # a dict, not a list
                {"subjects": [{"label": "Cat"}]},            # names no subject
                {"subjects": ["subj-0003"]}):                # a bare string
        try:
            ps.apply_decisions(report, {rep: {"label": "Cat", **bad}}, samples)
        except AssertionError:
            continue
        raise AssertionError(f"accepted a malformed subjects list: {bad}")
    log("3 malformed lists refused")


def case_the_singular_form_still_means_a_one_entry_list(tmp):
    """The shape every existing caller writes, and the shape the SKILL has
    documented since VS-4. It must keep working and must land in the same
    place the list does — an engine that read only the new form would break
    every decision file an owner has on disk."""
    _wd, report, samples, rep = see_fixture_for_apply(tmp)
    listed = ps.apply_decisions(report, {rep: {
        "label": "Cat", "subjects": [{"subject_kind": "cat"}]}}, samples)
    singular = ps.apply_decisions(report, {rep: {
        "label": "Cat", "subject_kind": "cat"}}, samples)
    assert listed == singular, "the two spellings of one subject diverged"
    assert any(kinds_in(e) == ["cat"] for e in listed), listed
    log("`subject_kind: X` and `subjects: [{subject_kind: X}]` render identically")


def case_a_decision_naming_a_subject_id_is_refused(tmp):
    """⭐ REPRODUCTION (G7 item 5). ⛔ FAILS on 91ca5e6, where a decision's
    `subject_id` reached the label at `viewed-image:` with no recognition and
    no record — measured on a real dump, a street cat named after a pet and
    promoted to its exemplars. Both spellings are refused, nothing is written,
    and the refusal says where a pet IS named."""
    _wd, report, samples, rep = see_fixture_for_apply(tmp)
    for value in ({"label": "Cat", "subject_id": "subj-0003"},
                  {"label": "Cat", "subjects": [{"subject_kind": "cat"},
                                                {"subject_id": "subj-0007"}]}):
        try:
            ps.apply_decisions(report, {rep: value}, samples)
        except AssertionError as exc:
            assert "photo_index.py identify" in str(exc), exc
            continue
        raise AssertionError(f"a decision naming a pet was applied: {value}")
    log("both spellings of a named decision refused, pointing to identify")


def case_a_bare_label_still_decides_no_subject(tmp):
    """⚠️ A GUARD, not a reproduction — it holds before and after R4, and it
    is here because the commonest decision there is must not become collateral
    of a change to the rare one. A bare label names nobody; the entry says so
    with an empty list and no subject provenance to qualify."""
    _wd, report, samples, rep = see_fixture_for_apply(tmp)
    entries = ps.apply_decisions(report, {rep: "爬山"}, samples)
    by_path = {e["path"]: e for e in entries}
    assert not photo_evidence.subject_list(by_path[rep]), by_path[rep]
    assert by_path[rep]["subject_provenance"] is None, by_path[rep]
    assert ids_in({"labels": entries}) == [], entries


def case_the_report_names_the_subject_the_registry_already_accepts(tmp):
    """⭐ THE OTHER HALF of the R4 reproduction, and §2.1's actual root cause.

    `registry.match()` decided `accept` on these files and named the
    `subject_id`. The report then published a TALLY of the verdicts and threw
    the ids away, so the agent writing decisions.json had no id to name and
    the only honest thing it could say was the species. This carries the id to
    the one place the decision is written.

    ⛔ EVIDENCE, never a decision. Nothing here writes a subject onto a label:
    an accept that absorbed itself would be A19 — 24 sightings written onto a
    confirmed subject with nothing asked, 5 of them wrong — moved one stage
    earlier, where it would name folders instead of counters."""
    wd = three_group_fixture(loners=0).write(tmp)
    pack = pack_with_subjects(tmp, [
        {"name": "Name-One", "active": ["2026-05", "2026-05"],
         "vectors": [A], "forms_folder": False}])
    report = build(wd, rate=0.20, pack=pack)
    assert report["diagnostics"]["subject_verdicts"]["accept"] == 20, \
        report["diagnostics"]["subject_verdicts"]
    matched = [r for r in report["selected"] if r.get("subject_match")]
    assert matched, "not one selected row says which subject was accepted"
    ids = {r["subject_match"]["subject_id"] for r in matched}
    assert ids == {"subj-0001"}, ids
    one = matched[0]["subject_match"]
    assert one["space"] == "clip" and one["score"] is not None, one
    assert "not a decision" in one["note"], one
    # and a file the registry did NOT accept says nothing at all
    unmatched = [r for r in report["selected"] if r.get("subject_match") is None]
    assert len(matched) + len(unmatched) == len(report["selected"])
    log(f"{len(matched)} selected rows carry an accepted subject_id")


def case_a_run_with_no_registry_names_no_subject(tmp):
    """⚠️ A GUARD. The blank sheet is every benchmark run and every first
    dump, and Rule 7 makes it the shape the engine is measured in. A field
    that arrived carrying a null id would read as a match that FAILED rather
    than as a registry holding nothing to match against."""
    wd = three_group_fixture().write(tmp)
    report = build(wd, rate=0.20)
    assert all(r.get("subject_match") is None for r in report["selected"]), \
        [r for r in report["selected"] if r.get("subject_match")]


def case_the_report_says_how_many_animals_a_frame_holds(tmp):
    """The count is what tells the agent how long the `subjects` list should
    be. Nothing else in the report says a second animal is there — and the
    owner decision it serves is that the second animal is a name to log."""
    wd = three_group_fixture().write(tmp)
    paths = [r["SourceFile"] for r in
             csv.DictReader(open(wd / "embed" / "embeddings.csv", newline=""))]
    shared, solo = paths[0], paths[1]
    write_detection_index(wd, {shared: [(0, 2), (1, 2)], solo: [(0, 1)]})
    report = build(wd, rate=1.0)
    rows = {r["path"]: r for r in report["selected"]}
    assert rows[shared]["detections"]["count"] == 2, rows[shared]["detections"]
    assert rows[solo]["detections"]["count"] == 1, rows[solo]["detections"]
    # ⛔ absent is not zero. A file the identity stage never indexed has
    # nothing to say; a file it indexed and found nothing in has a finding.
    unindexed = [r for r in report["selected"] if r["path"] not in (shared, solo)]
    assert unindexed and all(r["detections"] is None for r in unindexed), unindexed
    log(f"{rows[shared]['detections']} vs {rows[solo]['detections']}")


def case_a_pre_r3a_index_never_claims_a_frame_holds_one_animal(tmp):
    """⛔ THE BLIND SPOT. An index written before R3a holds the
    highest-scoring box only and states no `det_count`. Answering 1 there
    would be a claim it cannot support, and it is indistinguishable
    downstream from a real solo frame — so the agent would write a one-entry
    list about a frame nothing has counted.

    `len(rows)` is the tempting substitute and it is exactly wrong: the index
    has one row per file BECAUSE it kept one box, not because one animal was
    there. None is the only honest answer, and it is not zero either."""
    wd = three_group_fixture().write(tmp)
    paths = [r["SourceFile"] for r in
             csv.DictReader(open(wd / "embed" / "embeddings.csv", newline=""))]
    write_detection_index(wd, {paths[0]: [(0, "")]})
    report = build(wd, rate=1.0)
    row = {r["path"]: r for r in report["selected"]}[paths[0]]
    assert row["detections"] is not None, "a legacy row is still indexed"
    assert row["detections"]["count"] is None, row["detections"]
    assert row["detections"]["kinds"] == ["cat"], row["detections"]
    assert "cannot say how many" in row["detections"]["note"], row["detections"]


def case_photo_run_step_2b_records_what_it_selects(tmp):
    """F8. `photo-run/SKILL.md` is the path people follow, and its visual
    pass listed `photo_see.py` as "look + label". Alone it selects and labels
    nothing: no `see-labels.json`, exit 0, and the plan then refuses the batch
    as unseen. The `--apply` line lived only in `photo-see/SKILL.md`."""
    text = (ROOT / "photo-run" / "SKILL.md").read_text(encoding="utf-8")
    fence = text[text.index("The VISUAL pass"):].split("```")[1].replace("\\\n", " ")
    see = [line for line in fence.splitlines() if "photo_see.py" in line]
    assert any("--apply" in line for line in see), \
        f"step 2b runs photo_see with no --apply: {see}"
    selecting = [line for line in see if "--apply" not in line]
    assert not any("label" in line.split("#", 1)[-1].lower()
                   for line in selecting), \
        f"the selection-only line still claims to label: {selecting}"


# ---- Card 4: a batch with nothing viewable stops ---------------------------

def see_env():
    env = dict(os.environ)
    env.pop("PHOTO_PROFILE", None)
    env["PHOTO_PREVIEW_BACKEND"] = "pillow"
    return env


def case_nothing_viewable_stops_the_batch(tmp):
    """Every selected file failed its preview: photo_see used to exit 0 with
    no sample to look at, the setting of the 2026-07-20 fabrication incident.
    Now exit 3, the report still written, each cause counted on stderr."""
    wd = three_group_fixture(loners=0).write(tmp)          # no file on disk
    proc = subprocess.run([PY, SCRIPT, str(wd), "--batch", "1"],
                          capture_output=True, text=True, env=see_env())
    assert proc.returncode == 3, f"exit {proc.returncode}\n{proc.stderr[-600:]}"
    assert "source_missing" in proc.stderr and "NONE got a viewable" in proc.stderr, \
        proc.stderr[-600:]
    report = report_of(wd)
    assert report["selected"] and report["sample_failures_by_cause"], report.keys()


def case_one_viewable_sample_keeps_the_batch_going(tmp):
    """A partial failure — an L17 movie among good stills — stays exit 0 and
    is named in the report, so it never turns an archive run red."""
    f = three_group_fixture(loners=0)
    wd = f.write(tmp)
    proc = subprocess.run([PY, SCRIPT, str(wd), "--batch", "1", "--no-thumbnails"],
                          capture_output=True, text=True, env=see_env())
    assert proc.returncode == 0, proc.stderr[-400:]
    selected = [e["path"] for e in report_of(wd)["selected"]]
    make_real_jpeg(Path(selected[0]))                      # one of them is real
    proc = subprocess.run([PY, SCRIPT, str(wd), "--batch", "1", "--force"],
                          capture_output=True, text=True, env=see_env())
    assert proc.returncode == 0, f"exit {proc.returncode}\n{proc.stderr[-600:]}"
    report = report_of(wd)
    assert sum(1 for e in report["selected"] if e.get("sample")) == 1, report["selected"]
    assert report["sample_failures_by_cause"].get("source_missing") == len(selected) - 1


def case_no_thumbnails_never_stops(tmp):
    wd = three_group_fixture(loners=0).write(tmp)
    run_see(wd, "--no-thumbnails")


# ------------------------------------------- F-jj: pending screen sizes (Card 6)

# Not the engine fallback size (1170x2532), which already routes as a
# screenshot with no pack: this is a second phone the pack does not list.
SCREEN = ("1179", "2556")


def screenshot_fixture(camera=20, shots=6):
    """UAT02-02 unit 2's shape: camera photos plus no-camera PNGs at one
    phone-screen size, named IMG_*.PNG (no screenshot filename), with no
    screen_dims in the pack."""
    RNG.seed(5)
    f = Fixture()
    f.many(A, camera)
    for k in range(shots):
        f.add(near(B, basis(20 + k)), name=f"IMG_{900 + k:04d}.PNG", make="-",
              filetype="PNG", dims=SCREEN if k % 2 else SCREEN[::-1])
    return f


def picked_names(report):
    return {Path(e["path"]).name for e in report["selected"]}


def case_fjj_an_unanswered_screen_size_stays_out_of_vision(tmp):
    """REPRODUCES F-jj: at c5b6f99 the six went into the pool and some were
    picked for the vision model."""
    wd = screenshot_fixture().write(tmp)
    report = build(wd, rate=1.0)
    assert report["coverage"]["pool"] == 20, report["coverage"]["pool"]
    assert report["coverage"]["held_from_vision"] == {"pending_screen_size": 6, "document": 0}, \
        report["coverage"]["held_from_vision"]
    assert not any(n.endswith(".PNG") for n in picked_names(report)), picked_names(report)


def case_fjj_a_declined_size_is_not_held(tmp):
    """GUARD — the owner said this size is not a screen: back in the pool."""
    wd = screenshot_fixture().write(tmp)
    profile = {"declined_screen_dims": [[int(SCREEN[0]), int(SCREEN[1])]]}
    report = build(wd, rate=1.0, profile=profile)
    assert report["coverage"]["pool"] == 26, report["coverage"]
    assert report["coverage"]["held_from_vision"]["pending_screen_size"] == 0


def case_fjj_a_camera_photo_at_that_size_is_not_held(tmp):
    """GUARD — the rule is for no-camera stills only."""
    f = screenshot_fixture(shots=2)
    f.add(near(A, basis(28)), make="Apple", dims=SCREEN)
    wd = f.write(tmp)
    report = build(wd, rate=1.0)
    assert report["coverage"]["pool"] == 21, report["coverage"]
    assert report["coverage"]["held_from_vision"]["pending_screen_size"] == 2


def case_fjj_a_batch_of_only_held_files_is_not_a_stop(tmp):
    """GUARD — every file held leaves nothing to view: the run says so and
    exits 0, never B1's exit 3 (which is for previews that FAILED)."""
    wd = screenshot_fixture(camera=0, shots=4).write(tmp)
    proc = run_see(wd)
    assert "held out of vision" in proc.stdout and "4 pending screen size" in proc.stdout, \
        proc.stdout
    report = report_of(wd)
    assert report["selected"] == [] and report["coverage"]["pool"] == 0, report["coverage"]



def case_fjj_a_document_flagged_still_stays_out_of_vision(tmp):
    """REPRODUCES F-jj (a): a still the U3-06 check flagged at embed — a camera
    photo included (owner ruling Q-a) — was still a vision candidate."""
    RNG.seed(9)
    f = Fixture().many(A, 10)
    wd = f.write(tmp)
    docs = {str(wd / f.files[i]["name"]): True for i in (0, 1, 2)}
    flags = {str(wd / r["name"]): False for r in f.files}
    flags.update(docs)
    (wd / "embed" / "document-flags.json").write_text(json.dumps({"document": flags}))
    report = build(wd, rate=1.0)
    assert not set(docs) & {e["path"] for e in report["selected"]}, "a document was picked"
    assert report["coverage"]["pool"] == 7, report["coverage"]["pool"]
    assert report["coverage"]["held_from_vision"]["document"] == 3, report["coverage"]


def case_fjj_an_unchecked_still_is_named_not_hidden(tmp):
    """GUARD — an index built before the check: nothing is held on a guess,
    and the run says which stills were never checked and how to fill it."""
    RNG.seed(9)
    wd = Fixture().many(A, 6).write(tmp, real_images=True)
    proc = run_see(wd)
    assert "never checked for documents" in proc.stdout, proc.stdout
    report = report_of(wd)
    assert len(report["coverage"]["document_check_missing"]) == 6, report["coverage"]


CASES = [
    ("F-jj: a document-flagged still stays out of vision (REPRO)",
     case_fjj_a_document_flagged_still_stays_out_of_vision),
    ("F-jj: an unchecked still is named, not hidden (GUARD)",
     case_fjj_an_unchecked_still_is_named_not_hidden),
    ("F-jj: an unanswered screen size stays out of vision (REPRO)",
     case_fjj_an_unanswered_screen_size_stays_out_of_vision),
    ("F-jj: a declined size is not held (GUARD)", case_fjj_a_declined_size_is_not_held),
    ("F-jj: a camera photo at that size is not held (GUARD)",
     case_fjj_a_camera_photo_at_that_size_is_not_held),
    ("F-jj: a batch of only held files is not a stop (GUARD)",
     case_fjj_a_batch_of_only_held_files_is_not_a_stop),
    ("budget honours floor, cap, rate and pool size", case_budget_floor_cap_and_pool),
    ("the see-rate is actually met", case_see_rate_is_actually_met),
    ("the ladder fills in priority order", case_ladder_fills_in_priority_order),
    ("rung 1 takes the biggest clusters first, and the quota caps how many",
     case_rung1_takes_biggest_clusters_first),
    ("the rung-1 quota is a share of the budget (F2/B1)",
     case_rung1_quota_is_a_share_of_the_budget),
    ("the odd file out is seen — at rung 1, not rung 3", case_the_odd_file_out_is_seen),
    ("rung 3 fires once rung 1 is capped (F7 wording, F2 cause)",
     case_rung3_fires_once_rung1_is_capped),
    ("a folder-bound cluster keeps its look outside the quota (N-4)",
     case_carve_out_cluster_keeps_its_look_outside_the_quota),
    ("where the name carries [who], the guaranteed pick contains the subject",
     case_carve_out_pick_contains_the_named_subject),
    ("the carve-out floors the budget and the see-rate still holds",
     case_carve_out_lifts_the_budget_and_the_see_rate_still_holds),
    ("the naming carve-out is a no-op with no subject registry",
     case_carve_out_is_a_no_op_without_a_registry),
    ("the benchmark refuses a pack that is not a blank sheet",
     case_benchmark_refuses_a_pack_that_is_not_blank),
    ("the replay header states which pack it ran against",
     case_replay_header_states_which_pack_it_ran_against),
    ("EV-9 — the run type is supplied, never guessed",
     case_a_run_type_is_supplied_and_never_guessed),
    ("EV-9 — the header carries run type, slug, blank verdict, snapshot",
     case_the_header_carries_every_field_ev9_names),
    ("EV-9 — the benchmark label and its blank-sheet guard are one call",
     case_the_benchmark_label_and_its_guard_are_one_call),
    ("rungs 2 and 4 are a no-op with no subject registry",
     case_rungs_2_and_4_are_a_no_op_without_a_registry),
    ("the timeline gate reads EXIF, never the dump name",
     case_the_timeline_gate_reads_exif_not_the_dump_name),
    ("a gray-zone subject match reaches rung 2",
     case_a_gray_zone_match_reaches_rung_2),
    ("the carve-out fires for a folder-forming subject",
     case_the_carve_out_fires_for_a_folder_forming_subject),
    ("rung 4 fires once a registry can be asked",
     case_rung_4_fires_once_a_registry_can_be_asked),
    ("rung 4 needs an eligible subject, not just a record",
     case_rung_4_needs_an_eligible_subject_not_just_a_record),
    ("lookalike subjects are a question in the report",
     case_lookalike_subjects_are_a_question_in_the_report),
    ("VS-3b — a confirmed subject the identity space cannot use is reported",
     case_a_confirmed_subject_the_identity_space_cannot_use_is_reported),
    ("selection is deterministic", case_selection_is_deterministic),
    ("a CLI re-run is byte-identical modulo run_id",
     case_cli_rerun_is_byte_identical_modulo_run_id),
    ("the CLI refuses to overwrite without --force", case_cli_refuses_overwrite),
    ("one look labels a whole visual cluster", case_cluster_labels_propagate),
    ("two looks that disagree are flagged, not silently dropped (F12)",
     case_cluster_label_conflict_is_flagged_not_dropped),
    ("a label with no provenance prefix is caught (F10)",
     case_a_label_without_provenance_is_caught),
    ("a clip-* label can never claim viewed-image:",
     case_clip_label_can_never_claim_viewed_image),
    ("viewed-image: requires a thumbnail that exists",
     case_viewed_image_needs_a_real_thumbnail),
    ("a decision for an unselected file is rejected",
     case_apply_rejects_a_decision_for_an_unselected_file),
    ("U3-28: a video's sample-derived key is refused, naming the right path",
     case_apply_names_the_right_key_for_a_video_sample),
    ("U3-28: a verbatim sample filename is recognised and mapped back",
     case_apply_recognises_a_verbatim_sample_filename),
    ("U3-28: a genuine stranger is not dressed up as a mis-keyed sample",
     case_a_genuine_stranger_gets_no_sample_hint),
    ("U3-28: two selected files sharing a stem are AMBIGUOUS, never resolved",
     case_an_ambiguous_stem_is_never_resolved),
    ("a confident zero-shot match is clip-matched:, never viewed-image:",
     case_confident_zero_shot_is_clip_matched_never_viewed),
    ("ONB-12's filename rule is not weakened", case_exif_screenshot_rule_is_not_weakened),
    ("screenshot suspects are flagged, never routed",
     case_screenshot_suspects_are_flagged_never_routed),
    ("a label file from another model is refused",
     case_label_file_from_another_model_is_refused),
    ("a label file with other classes is refused",
     case_label_file_with_other_classes_is_refused),
    ("with no label file the geometry rungs still work", case_no_label_file_still_selects),
    ("with no label file the operator is told the axis is off",
     case_a_missing_label_file_warns_the_operator),
    ("with no identity index the operator is told (R2)",
     case_a_missing_identity_index_warns_the_operator),
    ("failed rows are reported, not silently dropped",
     case_failed_rows_are_reported_not_silently_dropped),
    ("validate() catches a missing thumbnail", case_validate_catches_a_missing_thumbnail),
    ("residual unlabeled files are a warning, not a failure",
     case_residual_unlabeled_is_a_warning_not_a_failure),
    ("the owner pack supplies the label set (ONB-10/ONB-9)",
     case_owner_pack_supplies_the_label_set),
    ("a non-assertion crash is counted, not swallowed with the tally",
     case_a_non_assertion_crash_is_counted),

    # R4 — the wire between a confirmed subject and a folder name
    ("R4 — a decision names every animal in the frame",
     case_a_decision_names_every_animal_in_the_frame),
    ("R4 — both names propagate to the whole cluster",
     case_both_names_propagate_to_the_whole_cluster),
    ("R4 — a decision may not say WHO two different ways",
     case_a_decision_may_not_say_who_is_in_the_frame_twice),
    ("R4 — a malformed subjects list is refused, not absorbed",
     case_a_malformed_subjects_list_is_refused_not_absorbed),
    ("R4 — the singular form still means a one-entry list",
     case_the_singular_form_still_means_a_one_entry_list),
    ("G7 — a decision naming a subject_id is refused, pointing to identify",
     case_a_decision_naming_a_subject_id_is_refused),
    ("R4 — a bare label still decides no subject (GUARD)",
     case_a_bare_label_still_decides_no_subject),
    ("R4 — the report names the subject the registry accepts",
     case_the_report_names_the_subject_the_registry_already_accepts),
    ("R4 — a run with no registry names no subject (GUARD)",
     case_a_run_with_no_registry_names_no_subject),
    ("R4 — the report says how many animals a frame holds",
     case_the_report_says_how_many_animals_a_frame_holds),
    ("R4 — a pre-R3a index never claims a frame holds one animal",
     case_a_pre_r3a_index_never_claims_a_frame_holds_one_animal),
    ("F8 — photo-run's visual pass records what it selects (REPRODUCTION)",
     case_photo_run_step_2b_records_what_it_selects),
    ("Card 4 — a batch with NOTHING viewable exits 3 and names the causes",
     case_nothing_viewable_stops_the_batch),
    ("Card 4 — one viewable sample keeps the batch at exit 0",
     case_one_viewable_sample_keeps_the_batch_going),
    ("Card 4 — --no-thumbnails never stops on previews",
     case_no_thumbnails_never_stops),
]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    passed = 0
    for name, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="photo_see_test_"))
        try:
            passed += 1 if run_case(name, lambda: fn(tmp)) else 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{passed}/{len(CASES)} photo_see cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
