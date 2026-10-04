#!/usr/bin/env python3
"""VS-4 cases — the memorize loop, new-subject discovery, the hardened
fabrication guard, and the memory review table's write / parse-back round
trip.

The four exit tests from the Visual-Sorting DESIGN's build-stages table are
each a named case here:

  1. the registry grows ONLY from vision-confirmed matches, and the AUDIT LOG
     proves it — every exemplar in the pack traces to a `memorized` line that
     names the see-report, batch and thumbnail that confirmed it;
  2. the fabrication guard passes an ADVERSARIAL test — eleven forgeries, each
     a plausible one-line edit, each refused;
  3. a subject spanning K batches yields EXACTLY ONE question, and it stays
     one across checkpoints and across the confirm that closes it;
  4. a checkpoint replay is DETERMINISTIC against a pinned pack snapshot id.

Every fixture is synthetic: 32-dimensional hand-built vectors, invented paths,
invented class words, four bytes of JPEG header. No photo, no drive, no model,
no pack of any real owner.

Needs numpy (repo .venv). No torch, no network.

  ./.venv/bin/python3 tests/photo_memory_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import contextlib
import csv
import inspect
import io
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import golden_replay  # noqa: E402
import photo_embed  # noqa: E402
import photo_evidence  # noqa: E402
import photo_memory as pm  # noqa: E402
import photo_profile  # noqa: E402
import photo_see as ps  # noqa: E402
import photo_subjects as psub  # noqa: E402
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
TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"

IDENTITY = {"model_id": "ViT-B-32", "pretrained_tag": "laion2b_s34b_b79k",
            "embed_dim": DIM, "preprocess_fingerprint": "sha256:testfixture0000"}


def log(msg):
    if VERBOSE:
        print(f"      {msg}")


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / float(np.linalg.norm(v))


def basis(i):
    v = np.zeros(DIM, dtype=np.float32)
    v[i % DIM] = 1.0
    return v


def near(base, i, jitter=0.05):
    return unit(np.asarray(base, dtype=np.float32) + jitter * basis(i + 7))


# ------------------------------------------------------------- the fixture --

# SNS-4's cadence, turned OFF for every fixture that is not about it. A floor
# of 0 fires a round at every checkpoint, which is what `review` did before the
# cadence existed, so a case written to exercise the question SHAPE keeps
# asking its question. ⛔ Not a default the engine holds anywhere — the shipped
# values are `photo_memory.DEFAULT_NEW_FSS_FLOOR` / `DEFAULT_SNS_ROUNDS_PER_DUMP`
# and the cases that test the cadence build a pack that carries them.
CADENCE_OFF = {"new_fss_floor": 0, "sns_rounds_per_dump": 9999}


# Q8-a: a sighting is filed onto a confirmed subject only near a home, so the
# default fixture pack has one and `batch_fixture` photographs at it. A case
# about a sighting AWAY from home says so with `batch_fixture(..., gps=...)`.
FIXTURE_HOME = {"id": "home-01", "label": None, "lat": 10.5, "lon": 20.25}
AT_HOME = "10.5 20.25"


def make_pack(root, owner="betauser00", language="en", cadence=CADENCE_OFF):
    pack_dir = Path(root) / owner
    shutil.copytree(TEMPLATE, pack_dir)
    for path in list(pack_dir.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", owner)))
    for name in ("photo-profile.json", "photo-entities.json"):
        path = pack_dir / name
        path.write_text(path.read_text().replace("{{SLUG}}", owner)
                        .replace("{{DISPLAY}}", owner))
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["language"] = language
    profile["home_locations"] = [dict(FIXTURE_HOME)]
    if cadence is not None:
        profile["memory"] = dict(cadence)
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))
    return pack_dir


def open_pack(pack_dir):
    return photo_profile.resolve_pack(explicit=Path(pack_dir) / "photo-profile.json")


def write_embed_index(workdir, index):
    """Add this batch's vectors to the dump's `embed/` index.

    Written by `photo_embed.save_index()` itself, and read back by
    `photo_embed.load_existing()`, so the fixture cannot agree on a file shape
    that the code under test disagrees with — the confirm-time loader is the
    thing being exercised, and a hand-rolled index would only prove that two
    hand-rolled things match."""
    embed_dir = Path(workdir) / "embed"
    rows, vectors, _meta = photo_embed.load_existing(embed_dir)
    rows = list(rows)
    vecs = [np.asarray(v, dtype=np.float32)
            for v in (vectors if vectors is not None else [])]
    known = {r["SourceFile"] for r in rows}
    for path in sorted(index):
        if path in known:
            continue
        sha, vec = index[path]
        rows.append({"SourceFile": path, "sha256": sha, "kind": "image",
                     "status": "embedded", "size": 1, "mtime": 0, "error": ""})
        vecs.append(np.asarray(vec, dtype=np.float32))
    photo_embed.save_index(embed_dir, rows, vecs, dict(IDENTITY, normalized=True))


def batch_fixture(workdir, batch, subjects, month="2029-03", gps=AT_HOME):
    """One batch's worth of see-stage output, without running the see stage.

    `subjects` is a list of (vector, n_members). Each becomes one visual
    cluster whose representative is the file the model looked at, with a real
    thumbnail on disk. -> (report, index, samples_dir).
    """
    out = Path(workdir) / "classify" / f"batch-{batch:02d}"
    samples = out / "samples"
    samples.mkdir(parents=True, exist_ok=True)

    index, clusters, selected = {}, [], []
    for c, (vec, count) in enumerate(subjects):
        members = []
        for k in range(count):
            path = str(Path(workdir) / f"B{batch}_C{c}_{k:03d}.JPG")
            index[path] = (f"sha256:{batch}-{c}-{k}", near(vec, k))
            members.append(path)
        rep = members[0]
        sample = f"B{batch}_C{c}.jpg"
        (samples / sample).write_bytes(view_fixture.JPEG)
        clusters.append({"cluster": c, "size": count, "representative": rep,
                         "members": sorted(members)})
        selected.append({"path": rep, "sha256": index[rep][0], "rung": 1,
                         "reason": "cluster representative", "cluster": c,
                         "cluster_size": count,
                         "time": f"{month}-04 10:0{c}", "sample": sample})

    report = {"engine": "photo_see.py (VS-2 see controller)", "batch": batch,
              "workdir": str(workdir), "clusters": clusters,
              "selected": selected, "samples_dir": str(samples),
              "provisional": [{"path": p, "label": None, "provenance": None,
                               "state": "unlabeled"} for p in sorted(index)]}
    (out / "see-report.json").write_text(json.dumps(report, ensure_ascii=False))
    write_embed_index(workdir, index)
    manifest = Path(workdir) / "manifest.csv"
    new = not manifest.exists()
    with open(manifest, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["SourceFile", "DateTimeOriginal",
                                          "GPSPosition"])
        if new:
            w.writeheader()
        for path in sorted(index):
            w.writerow({"SourceFile": path,
                        "DateTimeOriginal": month.replace("-", ":") + ":04 10:00:00",
                        "GPSPosition": gps})
    return report, index, samples


def apply_and_memorize(workdir, pack, report, index, samples, decisions,
                       provenance="viewed-image:"):
    """Write the applied labels the way `--apply` does, then memorize."""
    out = Path(samples).parent
    sample_of = {e["path"]: e["sample"] for e in report["selected"]}
    entries = [{"path": path, "label": (value.get("label") if isinstance(value, dict)
                                        else value),
                "provenance": provenance, "sample": sample_of.get(path)}
               for path, value in sorted(decisions.items())]
    (out / "see-labels.json").write_text(json.dumps(
        {"batch": report["batch"], "labels": entries}, ensure_ascii=False))
    return ps.memorize_batch(report, decisions, entries, index, IDENTITY, pack,
                             samples, run_id="see-test", workdir=workdir)


def write_batches(workdir, count, files_each=4):
    Path(workdir).mkdir(parents=True, exist_ok=True)
    (Path(workdir) / "batches.json").write_text(json.dumps({"batches": [
        {"batch": n, "label": "synthetic", "from": f"2029-03-0{n}",
         "to": f"2029-03-0{n}", "files": files_each} for n in range(1, count + 1)]}))


PICK_ROW = "`pick:` ______   `who:` ______   `name:` ______"


def frames_of(text, tiles, question=0):
    """-> the GLOBAL frame numbers the page gave the photographs of these
    TILES, as a comma string ready to type onto a `pick:` or `skip:` row.

    SNS-1 moved the owner's unit from the tile to the frame, and most fixtures
    here still mean "this whole group" — so they say which tiles and this says
    which numbers those tiles turned into. A fixture that typed tile numbers
    onto a `pick:` row would answer about whichever photographs happen to sit
    at those positions on the page, which on a multi-frame tile is a different
    subject."""
    block = pm.parse_review(text)[question]
    wanted = {block["tiles"][t] for t in tiles if t in block["tiles"]}
    return ",".join(str(n) for n in sorted(block["frames"])
                    if block["frames"][n]["subject_id"] in wanted)


def fill_pick(text, tiles, who="pet", name="Name-Two", count=1, frames=None):
    """What an owner types on one answer row: the FRAME numbers that are one
    subject, plus who they are and what they are called.

    THREE fields on ONE line, which is what the signed TEMPLATE shows and what
    a one-key-per-line parser reads as `pick` = "1,3   `who:` pet   `name:`
    Rex" with who and name empty — a silent no-op that every one-field-per-
    line fixture in this file would have passed straight through.

    `tiles` says which groups the answer covers and the frames are looked up;
    `frames` overrides that with numbers typed directly, which is what a split
    or a merge looks like."""
    numbers = frames if frames is not None else frames_of(text, tiles)
    row = f"`pick:` {numbers}   `who:` {who}   `name:` {name}"
    assert PICK_ROW in text, "no blank `pick:` row to answer"
    return text.replace(PICK_ROW, row, count)


def fill_group(text, tiles, who="pet", name="Name-Two", count=1):
    """The SUPERSEDED verb, typed onto a page that no longer offers it.

    `group:` takes TILE numbers and no renderer emits its row any more (SNS-1);
    this is what a work dir with history holds, and what decision A requires to
    parse and be refused."""
    row = f"`group:` {tiles}   `who:` {who}   `name:` {name}"
    assert PICK_ROW in text, "no answer row to overwrite"
    return text.replace(PICK_ROW, row, count)


def fill_skip(text, tiles, armed=True, frames=None):
    """The one row that takes two gestures — numbers AND the word `confirm`.

    Frame numbers now, like every other answer row (SNS-1). `armed=False`
    writes what a slip of the keyboard looks like: numbers on the permanent
    row with nothing to say they were meant."""
    numbers = frames if frames is not None else frames_of(text, tiles)
    assert "`skip:` ______" in text, "no `skip:` row"
    row = f"`skip:` {numbers} confirm" if armed else f"`skip:` {numbers}"
    return text.replace("`skip:` ______", row, 1)


class Skipped(Exception):
    """A case that could not run is neither a pass nor a failure, and must not
    be printed or counted as either — the same rule fresh_owner_smoke.py
    follows for its private-term-list check. Raise it with the reason, naming
    what was missing."""


def run_case(name, fn):
    """-> True (passed), False (failed) or None (skipped)."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fn(Path(tmp))
        print(f"  ok    {name}")
        return True
    except Skipped as why:
        print(f"  skip  {name}: {why}")
        return None
    except AssertionError as exc:
        print(f"  FAIL  {name}: {exc}")
        return False
    except Exception as exc:                                # noqa: BLE001
        print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        if VERBOSE:
            import traceback
            traceback.print_exc()
        return False


# =========================================================== exit test 1 ====

def case_the_registry_grows_only_from_confirmed_matches(tmp):
    """EXIT TEST 1. Two decisions attribute the same subject; one file was
    looked at and one was not. Only the look becomes an exemplar, and the
    audit log — not this assertion — is what shows why."""
    pack_dir = make_pack(tmp)
    pack = open_pack(pack_dir)
    registry = psub.Registry(directory=pack_dir / "photo-subjects")
    subject = registry.create_subject(name="Name-One", who="relation-word",
                                      kind="cat", active=["2029-01", None])
    registry.save()

    workdir = tmp / "dump"
    report, index, samples = batch_fixture(workdir, 1, [(basis(0), 3),
                                                        (basis(1), 2)])
    looked, unlooked = report["selected"][0]["path"], report["clusters"][0]["members"][1]
    # The unlooked file is not on the see-list at all; a caller attributing it
    # to the subject is exactly the drift this rule exists to stop.
    index[unlooked] = index[unlooked]
    decisions = {looked: {"label": "Cat", "subject_id": subject.subject_id},
                 unlooked: {"label": "Cat", "subject_id": subject.subject_id}}
    summary = apply_and_memorize(workdir, pack, report, index, samples, decisions)

    assert summary["ran"], summary
    assert len(summary["memorized"]) == 1, summary["memorized"]
    assert summary["memorized"][0]["path"] == looked
    assert len(summary["refused"]) == 1, summary["refused"]
    assert unlooked in summary["refused"][0]["path"]

    reloaded = psub.load(pack=open_pack(pack_dir))
    exemplars = reloaded.get(subject.subject_id).exemplars
    assert len(exemplars) == 1, exemplars

    # THE PROOF: every exemplar in the pack has a `memorized` audit line that
    # names the see-report, the batch and the thumbnail behind it.
    trail = reloaded.audit_trail()
    memorized = [r for r in trail if r["decision"] == "memorized"]
    refused = [r for r in trail if r["decision"] == "refused"]
    assert len(memorized) == 1 and len(refused) == 1, trail
    assert refused[0]["gate"] == "evidence", refused[0]
    proof = memorized[0]["evidence"]
    assert proof["path"] == looked and proof["batch"] == 1
    assert Path(proof["see_report"]).is_file()
    assert (Path(samples) / proof["sample"]).is_file()
    for exemplar in exemplars:
        assert any(r["vec_ref"] == exemplar["vec_ref"] for r in memorized), exemplar
    log(f"1 memorized, 1 refused at the {refused[0]['gate']} gate; "
        f"audit log {reloaded.audit_path}")


def case_a_draft_never_becomes_an_exemplar(tmp):
    """Draft containment. An unidentified cluster is drafted for a human to
    name; it may group files and propose a name, and it may never become
    recognition evidence."""
    pack_dir = make_pack(tmp)
    pack = open_pack(pack_dir)
    workdir = tmp / "dump"
    report, index, samples = batch_fixture(workdir, 1, [(basis(0), 4)])
    rep = report["selected"][0]["path"]
    summary = apply_and_memorize(workdir, pack, report, index, samples,
                                 {rep: {"label": "Cat", "subject_kind": "cat"}})
    assert len(summary["drafted"]) == 1, summary
    assert summary["memorized"] == [], summary

    registry = psub.load(pack=open_pack(pack_dir))
    draft = registry.drafts[0]
    assert draft.exemplars == [], draft.exemplars
    assert draft.status == psub.STATUS_DRAFT and draft.name is None
    assert registry.draft_centroid(draft.subject_id) is not None
    assert not registry.vectors_path(draft.subject_id).exists()
    # ...and it is inert in the see controller, which counts recognisers.
    assert sum(1 for s in registry.subjects if s.exemplars) == 0
    log(f"{draft.subject_id} holds a centroid and no exemplar")


# =========================================================== exit test 2 ====

def case_the_fabrication_guard_is_adversarial(tmp):
    """EXIT TEST 2. Eleven forgeries, each one a plausible edit somebody could
    make by hand, each refused. `is_file()` — the whole test before VS-4 —
    passes five of them."""
    pack_dir = make_pack(tmp)
    pack = open_pack(pack_dir)
    registry = psub.Registry(directory=pack_dir / "photo-subjects")
    subject = registry.create_subject(name="Name-One", who="relation-word",
                                      kind="cat", active=["2029-01", None])
    registry.save()
    workdir = tmp / "dump"
    report, index, samples = batch_fixture(workdir, 1, [(basis(0), 3)])
    rep = report["selected"][0]["path"]
    good = {"see_report": str(Path(samples).parent / "see-report.json"),
            "batch": 1, "path": rep, "sample": report["selected"][0]["sample"]}
    outside = tmp / "outside.jpg"
    outside.write_bytes(view_fixture.JPEG)

    def forge(**overrides):
        return {**good, **overrides}

    (Path(samples) / "empty.jpg").write_bytes(b"")
    (Path(samples) / "text.jpg").write_text("this is not a photograph")
    try:
        (Path(samples) / "link.jpg").symlink_to(outside)
    except OSError:                                        # pragma: no cover
        pass

    forgeries = [
        ("a file the controller never selected",
         forge(path=str(Path(workdir) / "B1_C0_002.JPG"))),
        ("no thumbnail named at all", forge(sample=None)),
        ("a thumbnail that is not there", forge(sample="ghost.jpg")),
        ("an empty thumbnail", forge(sample="empty.jpg")),
        ("a text file wearing a .jpg name", forge(sample="text.jpg")),
        ("a symlink pointing outside samples/", forge(sample="link.jpg")),
        ("a path escape in the sample name",
         forge(sample=f"../../{outside.name}")),
        ("a see-report that is not there",
         forge(see_report=str(tmp / "gone" / "see-report.json"))),
        ("a see-report for another batch", forge(batch=2)),
        ("evidence describing a different file",
         forge(path=str(Path(workdir) / "B1_C0_001.JPG"),
               sample=report["selected"][0]["sample"])),
    ]
    for label, evidence in forgeries:
        problems = photo_evidence.evidence_problems(evidence,
                                                    expect_path=evidence["path"])
        assert problems, f"{label} was accepted as proof of a look"
        try:
            registry.add_exemplar(subject.subject_id, basis(0), f"sha256:{label}",
                                  evidence["path"], confirmed_by="viewed-image",
                                  identity=IDENTITY, evidence=evidence)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{label} was memorized")

    # 11th: the see controller picked the file, but the applied label says a
    # clip match — the run stopped before the vision call.
    (Path(samples).parent / "see-labels.json").write_text(json.dumps(
        {"batch": 1, "labels": [{"path": rep, "label": "Cat",
                                 "provenance": "clip-propagated:",
                                 "sample": good["sample"]}]}))
    assert photo_evidence.evidence_problems(good, expect_path=rep), \
        "a selected file carrying a clip-propagated label passed as a look"

    # ...and the batch-level guard refuses the same class of forgery.
    entries = [{"path": rep, "label": "Cat", "provenance": "viewed-image:",
                "sample": "text.jpg"}]
    try:
        ps.assert_no_fabrication(entries, {rep}, samples, report=report)
    except AssertionError:
        pass
    else:
        raise AssertionError("assert_no_fabrication accepted a text file")

    shared = [{"path": rep, "label": "Cat", "provenance": "viewed-image:",
               "sample": good["sample"]},
              {"path": report["clusters"][0]["members"][1], "label": "Cat",
               "provenance": "viewed-image:", "sample": good["sample"]}]
    try:
        ps.assert_no_fabrication(shared, {e["path"] for e in shared}, samples)
    except AssertionError as exc:
        assert "same thumbnail" in str(exc), exc
    else:
        raise AssertionError("one thumbnail was allowed to back two looks")

    assert subject.exemplars == [], subject.exemplars
    gates = {r["gate"] for r in registry.audit_trail()
             if r["decision"] == "refused"}
    assert gates == {"evidence"}, gates
    log(f"{len(forgeries) + 1} forgeries refused, all at the evidence gate")


# =========================================================== exit test 3 ====

def k_batch_run(tmp, k=6, pack_dir=None):
    """One unidentified subject photographed in K batches. Returns the pack."""
    pack_dir = pack_dir or make_pack(tmp)
    pack = open_pack(pack_dir)
    workdir = tmp / "dump"
    write_batches(workdir, k)
    for batch in range(1, k + 1):
        report, index, samples = batch_fixture(
            workdir, batch, [(basis(0), 4), (basis(5 + batch), 2)],
            month=f"2029-0{batch}")
        rep = report["selected"][0]["path"]
        apply_and_memorize(workdir, pack, report, index, samples,
                           {rep: {"label": "Cat", "subject_kind": "cat"}})
    return pack_dir, workdir


def case_one_subject_over_k_batches_is_one_question(tmp):
    """EXIT TEST 3, on the mechanism. Six batches, the same animal in each.

    Three suppression layers have to hold together: embedding identity within
    the run, the previous checkpoint's file across checkpoints, and the memory
    log across runs."""
    k = 6
    pack_dir, workdir = k_batch_run(tmp, k)
    registry = psub.load(pack=open_pack(pack_dir))
    drafts = registry.drafts
    assert len(drafts) == 1, [d.subject_id for d in drafts]
    draft = drafts[0]
    assert draft.obs_count == k, draft.record
    assert draft.observed_in == list(range(1, k + 1)), draft.observed_in

    # layer 2: one question at C1, none at C2 with no new evidence
    rc = pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    assert rc == 0
    first = (workdir / "memory-review_C1.md").read_text()
    blocks = pm.parse_review(first)
    assert len(blocks) == 1, [b["n"] for b in blocks]
    assert blocks[0]["subject_ids"] == [draft.subject_id]

    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=2, out=None))
    second = (workdir / "memory-review_C2.md").read_text()
    assert pm.parse_review(second) == [], "the same subject was asked twice"
    assert "no new evidence" in second

    # ...and it comes back only when the evidence grows (TEMPLATE rule 5)
    pack = open_pack(pack_dir)
    report, index, samples = batch_fixture(workdir, k + 1, [(basis(0), 4)],
                                           month="2029-09")
    write_batches(workdir, k + 1)
    apply_and_memorize(workdir, pack, report, index, samples,
                       {report["selected"][0]["path"]:
                        {"label": "Cat", "subject_kind": "cat"}})
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=3, out=None))
    third = (workdir / "memory-review_C3.md").read_text()
    assert len(pm.parse_review(third)) == 1, "new evidence did not reopen it"
    assert "already asked" in third

    log(f"{k + 1} batches, obs_count {draft.obs_count + 1}, one draft, "
        "one question, asked once")


def answer_the_question(pack_dir, workdir, who="pet", name="Name-Two",
                        checkpoint=1, go=True):
    """review -> put tile 1 in a group with a who+name -> confirm, the way an
    owner answers a one-tile `Group it` question. -> (subject_id, exit code)."""
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=checkpoint, out=None))
    path = workdir / f"memory-review_C{checkpoint}.md"
    blocks = pm.parse_review(path.read_text())
    assert len(blocks) == 1, [b["subject_ids"] for b in blocks]
    path.write_text(fill_pick(path.read_text(), [1], who=who, name=name))
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=checkpoint,
        file=None, sync=False, by="Test Operator", go=go))
    return blocks[0]["subject_ids"][0], rc


def photograph_again(tmp, pack_dir, name="dump2", vec=None, batch=1,
                     month="2029-07", members=3):
    """A LATER dump: a new work dir, the same subject in front of the camera.
    -> the memorize summary."""
    later = tmp / name
    write_batches(later, batch)
    report, index, samples = batch_fixture(later, batch,
                                           [(vec if vec is not None else basis(0),
                                             members)], month=month)
    summary = apply_and_memorize(
        later, open_pack(pack_dir), report, index, samples,
        {report["selected"][0]["path"]: {"label": "Cat", "subject_kind": "cat"}})
    return later, summary


def case_a_confirmed_subject_is_recognised_on_the_next_dump(tmp):
    """F14, and clause 2 of ONB-13a's exit test — the clause that matters.

    Answering the question has to STOP the question. Before this, `confirm`
    moved the subject out of the draft pool and wrote no exemplar, so on the
    next dump the same animal matched nothing, was drafted under a new
    `subject_id`, and was asked about again forever. Two dumps, end to end:
    the answer must attach exemplars through the real memorize rule, and the
    re-sighting must produce no new id and no question."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    subject_id, rc = answer_the_question(pack_dir, workdir)
    assert rc == 0

    registry = psub.load(pack=open_pack(pack_dir))
    subject = registry.get(subject_id)
    assert subject.status == psub.STATUS_CONFIRMED
    assert subject.exemplars, "confirm attached no exemplar — F14 is not fixed"
    # ...and they arrived through the REAL add_exemplar(), which is what the
    # audit log is for: no exemplar exists that the log does not account for.
    memorized = [r for r in registry.audit_trail() if r["decision"] == "memorized"]
    assert {e["vec_ref"] for e in subject.exemplars} \
        <= {r["vec_ref"] for r in memorized}, memorized
    for exemplar in subject.exemplars:
        assert exemplar["confirmed_by"] == psub.MEMORIZE_PROVENANCE, exemplar
        assert Path(exemplar["evidence"]["see_report"]).is_file(), exemplar
    before = {s.subject_id for s in registry.subjects}

    later, summary = photograph_again(tmp, pack_dir)
    assert summary["drafted"] == [], summary["drafted"]
    assert [r["subject_id"] for r in summary["recognised"]] == [subject_id], summary

    after = psub.load(pack=open_pack(pack_dir))
    assert {s.subject_id for s in after.subjects} == before, \
        "the same subject was drafted again under a new id"
    assert after.drafts == [], [d.subject_id for d in after.drafts]
    # a. no new id  b. no question, from the builder and from the table
    pack = open_pack(pack_dir)
    questions, _suppressed, _over, _held = pm.build_questions(
        after, later, pack, pack.profile,
        photo_profile.review_messages(pack.profile))
    assert questions == [], questions
    pm.cmd_review(argparse.Namespace(
        workdir=str(later), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    assert pm.parse_review((later / "memory-review_C1.md").read_text()) == []
    # the suppression is legible afterwards: the sighting is on the confirmed
    # record, with the score it was taken at, and nothing else moved.
    seen_again = after.get(subject_id)
    assert seen_again.record["evidence"][-1]["suppressed_at"] >= 0.85
    assert seen_again.name == "Name-Two" and seen_again.who == "pet"
    log(f"{subject_id}: {len(subject.exemplars)} exemplar(s) at confirm, "
        "recognised on dump 2, zero questions")


def case_a_look_nobody_took_is_refused_at_confirm(tmp):
    """The refusal direction. A cluster member labelled `clip-matched:` or
    `draft:viewed-image:` was attributed by the registry's own output or to an
    unconfirmed draft — not by a look — so naming the subject may not turn it
    into recognition evidence. The consequence is honest and visible: with no
    exemplar the subject is drafted again next dump, which is F14's own
    symptom, not a workaround for it."""
    for provenance in ("clip-matched:", "draft:viewed-image:"):
        pack_dir = make_pack(tmp, owner=f"betauser00-{len(provenance)}")
        pack = open_pack(pack_dir)
        workdir = tmp / f"dump-{len(provenance)}"
        write_batches(workdir, 1)
        report, index, samples = batch_fixture(workdir, 1, [(basis(0), 3)])
        apply_and_memorize(workdir, pack, report, index, samples,
                           {report["selected"][0]["path"]:
                            {"label": "Cat", "subject_kind": "cat"}},
                           provenance=provenance)
        subject_id, _rc = answer_the_question(pack_dir, workdir)

        registry = psub.load(pack=open_pack(pack_dir))
        assert registry.get(subject_id).exemplars == [], provenance
        refused = [r for r in registry.audit_trail() if r["decision"] == "refused"]
        assert [r["gate"] for r in refused] == ["provenance"], refused
        assert provenance.rstrip(":") in refused[0]["reason"] \
            or "none" in refused[0]["reason"], refused[0]["reason"]

        _later, summary = photograph_again(tmp, pack_dir,
                                           name=f"later-{len(provenance)}")
        assert summary["recognised"] == [], summary
        assert summary["drafted"] and summary["drafted"][0]["state"] == "new"
        log(f"{provenance} refused at the provenance gate; the subject is "
            "drafted again, which is what an unproved look costs")


def write_identity_index(workdir, rows, dim=6):
    """A synthetic VS-3b identity index over an existing work dir.

    `rows` is {SourceFile: (status, box_share, vector)}. Written in the real
    file layout so `photo_identity.load_index` reads it exactly as it reads a
    real one — the point of the case below is that `attach_exemplars` walks
    the production path, not a stub."""
    import csv as _csv
    import photo_identity

    embed = Path(workdir) / "embed"
    embed.mkdir(parents=True, exist_ok=True)
    out, vecs = [], []
    for source, (status, share, vec) in rows.items():
        out.append({"SourceFile": source, "sha256": "", "status": status,
                    "kind": "cat", "det_score": 0.9,
                    "box": "0,0,10,10", "box_share": share, "error": ""})
        vecs.append(vec)
    with open(embed / "identity.csv", "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=photo_identity.CSV_FIELDS)
        w.writeheader()
        w.writerows(out)
    with open(embed / "identity.npy", "wb") as f:
        np.save(f, np.stack(vecs).astype(np.float32))
    (embed / "identity-meta.json").write_text(json.dumps(
        {**photo_identity.meta_identity(dim), "created_at": "2029-01-01 00:00"}))


def case_a_confirm_attaches_identity_evidence_and_says_what_it_refused(tmp):
    """VS-3b through the PRODUCTION confirm path.

    `attach_exemplars()` is the only code that will ever build a real owner's
    identity bank, and every other case in this file exercises it with no
    identity index on disk — so they all take the "absent" branch and prove
    nothing about the present one. This one puts a real index in the work dir.

    Two looks, deliberately different:
      * one with the subject filling the frame — becomes identity evidence;
      * one where the subject is a speck — the 20260821 paw-close-up shape.
        The owner's yes still stands and the exemplar is still gained; it just
        never joins the bank the matcher scores against, and the caller is
        TOLD, because an owner wondering why recognition has not improved
        should be able to read the reason rather than infer it.
    """
    import photo_identity

    pack_dir, workdir = k_batch_run(tmp, 2)
    registry = psub.load(pack=open_pack(pack_dir))
    subject = registry.drafts[0]
    subject.record.update({"name": "Name-Two", "who": "pet",
                           "status": psub.STATUS_CONFIRMED})
    looks = [look for entry in subject.record["evidence"]
             for look in entry["looks"]]
    assert len(looks) == 2, looks

    def idv(i):
        v = np.zeros(6, dtype=np.float32)
        v[i] = 1.0
        return v

    write_identity_index(workdir, {
        looks[0]["path"]: (photo_identity.STATUS_OK, 0.44, idv(0)),
        looks[1]["path"]: (photo_identity.STATUS_OK, 0.001, idv(1)),
    })

    refs = [look["vec_ref"] for look in looks]
    gained, notes = pm.attach_exemplars(registry, subject, refs)

    assert gained == 2, (gained, notes)
    assert len(subject.exemplars) == 2, subject.exemplars

    V = registry.identity_vectors_for(subject.subject_id)
    assert V is not None and V.shape == (1, 6), None if V is None else V.shape
    assert registry.identity_embedding["model_id"] == photo_identity.EMBED_ID, \
        registry.identity_embedding

    spoken = [n for n in notes if "not as identity evidence" in n]
    assert len(spoken) == 1, notes
    assert "too little of it is in the picture" in spoken[0], spoken

    # ...and it survives the round trip, still keyed to the right exemplar.
    registry.save()
    reloaded = psub.load(pack=open_pack(pack_dir))
    again = reloaded.identity_vectors_for(subject.subject_id)
    assert again is not None and again.shape == (1, 6), \
        None if again is None else again.shape
    assert float(again[0] @ idv(0)) > 0.99, again[0]
    log("confirm attaches identity evidence, refuses a speck, and says so")


def case_promotion_is_per_look_and_never_implicit(tmp):
    """SNS-1b. The owner picks FRAMES, and until this signature existed the
    engine promoted the whole record: an owner who picked two frames out of a
    five-frame tile promoted all five, plus every look behind them nobody
    rendered. That is OA-15's mechanism, and it survives making the frame the
    unit in the question unless promotion is per look.

    `only_refs` is required and `None` is not a sentinel for "everything".
    Both halves are the test: a default or a None-means-all fallback would be
    an implicit-promotion path that keeps every case in this file green while
    promoting frames nobody saw."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    registry = psub.load(pack=open_pack(pack_dir))
    subject = registry.drafts[0]
    # What `confirm` writes when the owner answers — done here so this case
    # tests the selector rather than the parser.
    subject.record.update({"name": "Name-Two", "who": "pet",
                           "status": psub.STATUS_CONFIRMED})
    refs = [look["vec_ref"] for entry in subject.record["evidence"]
            for look in entry["looks"]]
    assert len(refs) == 2, refs

    assert inspect.signature(pm.attach_exemplars).parameters["only_refs"] \
        .default is inspect.Parameter.empty, "only_refs must have no default"
    for bad, why in ((), "missing"), ((None,), "None"):
        try:
            pm.attach_exemplars(registry, subject, *bad)
        except TypeError as exc:
            log(f"{why}: {exc}")
        else:
            raise AssertionError(f"{why} only_refs promoted something")
    assert subject.exemplars == [], subject.exemplars

    gained, notes = pm.attach_exemplars(registry, subject, refs[:1])
    assert gained == 1 and not notes, (gained, notes)
    held = [e["vec_ref"] for e in subject.exemplars]
    assert held == refs[:1], held
    assert refs[1] not in held, "an unpicked look was promoted anyway"
    # SNS-10, through the whole path: the photograph's own time, not today's
    assert subject.exemplars[0]["captured"] == "2029-01-04 10:00", \
        subject.exemplars[0]
    assert subject.exemplars[0]["added"] != subject.exemplars[0]["captured"]

    gained, notes = pm.attach_exemplars(registry, subject, ["sha256:nobody"])
    assert gained == 0 and len(notes) == 1, (gained, notes)
    assert "sha256:nobody" in notes[0] and "no look" in notes[0], notes
    refused = [r for r in registry.audit_trail() if r.get("gate") == "picked-ref"]
    assert len(refused) == 1 and refused[0]["vec_ref"] == "sha256:nobody", refused
    log("one of two looks promoted; a ref naming no look is refused out loud")


def case_un_confirm_puts_the_subject_back_in_a_question(tmp):
    """SNS-5 / Pattern 6. A confirmation the owner takes back has to become a
    QUESTION again, and the status flip alone does not do it: `is_draft` would
    let the subject into the loop while `settled_subjects()` kept reading the
    `human-confirmed` line that closed it — withdrawn and invisible at once.

    ⚠️ The third layer is the work dir's own, and the second half of this case
    used to PIN THE GAP: a review file that asked about this subject at C1
    still exists, and `asked_before()` went on suppressing it there until its
    evidence grew — which is exactly what a subject named wrongly and never
    photographed again can never do. Step 4 closes it
    (`photo_subjects.REOPENED_FLAG`), so the assertion is inverted: the
    withdrawn subject is asked in the work dir that already asked. What the
    exemption must NOT do — disarm the bar for everybody — is a case of its
    own, `case_a_withdrawal_reaches_the_work_dir_that_already_asked`."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    subject_id, _rc = answer_the_question(pack_dir, workdir)
    pack = open_pack(pack_dir)
    registry = psub.load(pack=pack)
    rmsg = photo_profile.review_messages(pack.profile)
    fresh = tmp / "later-dump"
    write_batches(fresh, 1)

    assert pm.settled_subjects(pack).get(subject_id) == "human-confirmed"
    questions, _suppressed, _over, _held = pm.build_questions(registry, fresh, pack,
                                                pack.profile, rmsg)
    assert not questions, "a confirmed subject is asked about again"
    assert registry.get(subject_id).exemplars, "nothing was promoted to withdraw"

    result = registry.get(subject_id) and registry.unconfirm(
        subject_id, by="Test Operator", reason="the wrong name")
    registry.save()
    log_path, buckets = pm.record_unconfirm(pack, [result], by="Test Operator")
    assert buckets[subject_id] == "pets", buckets
    entities = json.loads((Path(pack_dir) / "photo-entities.json").read_text())
    assert not [r for r in entities["pets"] if r["subject_id"] == subject_id], \
        "the entities twin still asserts the identity the owner took back"

    pack = open_pack(pack_dir)
    registry = psub.load(pack=pack)
    assert subject_id not in pm.settled_subjects(pack), log_path.read_text()
    questions, _suppressed, _over, _held = pm.build_questions(registry, fresh, pack,
                                                pack.profile, rmsg)
    assert [q["subject_ids"] for q in questions] == [[subject_id]], questions
    assert questions[0]["tiles"][0]["contact_sheet"], "asked with no frame"

    same, suppressed, _over, _held = pm.build_questions(registry, workdir, pack,
                                          pack.profile, rmsg)
    assert subject_id not in dict(suppressed), \
        ("the work dir that asked at C1 still holds the withdrawal shut",
         suppressed)
    assert [q["subject_ids"] for q in same] == [[subject_id]], same
    assert registry.get(subject_id).record[psub.REOPENED_FLAG] is True
    log("all three layers re-open the question: the status, the memory log, "
        "and the work dir that already asked")


def case_a_withdrawn_yes_cannot_be_promoted_onto(tmp):
    """The hole un-confirm would have left open. A withdrawn subject keeps its
    evidence (owner's decision, 2026-08-16) — FROZEN, and this is what freezes it. The
    labels already on disk still say a bare `viewed-image:`, truthfully,
    because a model really did look, and they were written while the subject
    was confirmed. So re-running the memorize step over a batch whose decision
    names the withdrawn id GREW the exemplar set with no live yes behind it,
    on a record the derived-status rule reads back as confirmed the moment
    anything writes a name.

    The provenance prefix cannot cover this: it is applied when the LABEL is
    written, and the withdrawal happens afterwards. So the status is checked
    at the write point, where the other two gates are."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    subject_id, _rc = answer_the_question(pack_dir, workdir)
    pack = open_pack(pack_dir)
    registry = psub.load(pack=pack)
    result = registry.unconfirm(subject_id, by="Test Operator")
    registry.save()
    pm.record_unconfirm(pack, [result], by="Test Operator")

    report, index, samples = batch_fixture(workdir, 3, [(basis(0), 3)],
                                           month="2029-05")
    summary = apply_and_memorize(
        workdir, open_pack(pack_dir), report, index, samples,
        {report["selected"][0]["path"]: {"label": "Cat",
                                         "subject_id": subject_id}})
    assert summary["memorized"] == [], summary["memorized"]
    assert len(summary["refused"]) == 1, summary["refused"]
    assert "not human-confirmed" in summary["refused"][0]["why"], summary

    after = psub.load(pack=open_pack(pack_dir))
    kept = len(result["exemplars_retained"])
    assert len(after.get(subject_id).exemplars) == kept, \
        "the frozen set moved — it may be kept, it may not grow"
    assert after.get(subject_id).is_draft
    assert after.recognisers == [], "and it attributes nothing meanwhile"
    gates = {r.get("gate") for r in after.audit_trail()
             if r["decision"] == "refused"}
    assert "unconfirmed" in gates, gates
    log("a decision naming a withdrawn subject is refused at the write point")


def case_a_forged_thumbnail_is_still_refused_at_confirm(tmp):
    """Gate 2 does not soften by running at confirm instead of at memorize.
    The thumbnail is hollowed out between the look and the answer — exactly
    the window a promotion deferred to a human opens — and the promotion is
    refused on the evidence it can no longer show."""
    pack_dir, workdir = k_batch_run(tmp, 1)
    for sample in (workdir / "classify").glob("batch-*/samples/*.jpg"):
        sample.write_text("this is not a photograph")
    subject_id, _rc = answer_the_question(pack_dir, workdir)

    registry = psub.load(pack=open_pack(pack_dir))
    assert registry.get(subject_id).exemplars == []
    gates = {r.get("gate") for r in registry.audit_trail()
             if r["decision"] == "refused"}
    assert gates == {"evidence"}, gates
    log("a look whose thumbnail stopped being a photograph is not memorized")


def case_a_re_embedded_file_is_not_promoted_under_its_old_ref(tmp):
    """The vector is re-derived from the dump's own index at confirm, so the
    index could have moved under it. `vec_ref` IS the file's sha256 — if the
    index now holds a different one for that path, the vector on offer is not
    the one that was looked at, and it is refused rather than memorized under
    a ref that no longer describes it."""
    pack_dir, workdir = k_batch_run(tmp, 1)
    index_csv = workdir / "embed" / "embeddings.csv"
    import csv as csvlib
    with open(index_csv, newline="") as fh:
        rows = list(csvlib.DictReader(fh))
        fields = list(rows[0].keys())
    for row in rows:
        row["sha256"] = "sha256:re-embedded"
    with open(index_csv, "w", newline="") as fh:
        writer = csvlib.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    subject_id, _rc = answer_the_question(pack_dir, workdir)
    registry = psub.load(pack=open_pack(pack_dir))
    assert registry.get(subject_id).exemplars == []
    assert not [r for r in registry.audit_trail() if r["decision"] == "memorized"]
    log("a moved sha256 refuses the promotion instead of memorizing the "
        "wrong vector")


def case_a_confirmed_subject_is_never_asked_again(tmp):
    """Layer 3. Once the log says human-confirmed, no later checkpoint — and
    no later run, in any work dir — may ask about that subject."""
    pack_dir, workdir = k_batch_run(tmp, 3)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    subject_id = pm.parse_review(path.read_text())[0]["subject_ids"][0]
    path.write_text(fill_pick(path.read_text(), [1]))

    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
        sync=False, by="Test Operator", go=True))
    assert rc == 0

    registry = psub.load(pack=open_pack(pack_dir))
    subject = registry.get(subject_id)
    assert subject.name == "Name-Two" and subject.who == "pet"
    assert subject.status == psub.STATUS_CONFIRMED
    entities = json.loads((pack_dir / "photo-entities.json").read_text())
    assert [r["subject_id"] for r in entities["pets"]] == [subject_id], entities
    assert entities["pets"][0]["kind"] == "cat"
    log_text = (pack_dir / "photo-memory-log.md").read_text()
    assert "human-confirmed" in log_text and subject_id in log_text
    assert "Test Operator" in log_text

    # a wholly new work dir: only the log can suppress the question now
    fresh = tmp / "dump2"
    write_batches(fresh, 1)
    pm.cmd_review(argparse.Namespace(workdir=str(fresh), profile=profile_arg,
                                     checkpoint=1, out=None))
    assert pm.parse_review((fresh / "memory-review_C1.md").read_text()) == []
    log("confirmed once; never asked again, even in a new work dir")


def case_who_and_name_are_one_answer(tmp):
    """ONB-13. Half an identity is refused rather than half written: a name
    with no relation cannot be used by the naming step, and asking for the
    other half later is the second interview the SPEC forbids."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    path.write_text(path.read_text().replace("`name:` ______", "`name:` Name-Two"))
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
        sync=False, by="Test Operator", go=True))
    assert rc == 1, "a half answer was accepted"
    registry = psub.load(pack=open_pack(pack_dir))
    assert registry.drafts and registry.drafts[0].name is None
    entities = json.loads((pack_dir / "photo-entities.json").read_text())
    assert entities["pets"] == [] and entities["people"] == [], entities
    log("name without who refused; nothing written")


def case_skipping_is_free_and_a_rejection_is_final(tmp):
    pack_dir, workdir = k_batch_run(tmp, 2)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    subject_id = pm.parse_review(path.read_text())[0]["subject_ids"][0]
    path.write_text(fill_skip(path.read_text(), [1]))
    pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
        sync=False, by="Test Operator", go=True))
    registry = psub.load(pack=open_pack(pack_dir))
    assert registry.get(subject_id).status == psub.STATUS_REJECTED
    assert "rejected" in (pack_dir / "photo-memory-log.md").read_text()
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=2, out=None))
    assert pm.parse_review((workdir / "memory-review_C2.md").read_text()) == []
    log("a rejected draft is logged and never proposed again")


# =========================================================== exit test 4 ====

def case_a_checkpoint_replay_is_deterministic(tmp):
    """EXIT TEST 4. Same pack, same work dir, byte-identical table — and the
    header names the snapshot it ran under, so a table produced against a
    different memory state cannot be mistaken for a reproduction."""
    pack_dir, workdir = k_batch_run(tmp, 4)
    profile_arg = str(pack_dir / "photo-profile.json")
    before = open_pack(pack_dir).snapshot()

    first = tmp / "one.md"
    second = tmp / "two.md"
    for out in (first, second):
        pm.cmd_review(argparse.Namespace(workdir=str(workdir),
                                         profile=profile_arg, checkpoint=1,
                                         out=str(out)))
    assert first.read_bytes() == second.read_bytes(), "the table is not stable"
    assert before["id"] in first.read_text(), "the snapshot id is not pinned"

    after = open_pack(pack_dir).snapshot()
    assert after == before, "review wrote into the pack — replay is unprovable"

    # confirm DOES move the pack, and the next table says so.
    path = workdir / "memory-review_C1.md"
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path.write_text(fill_pick(path.read_text(), [1]))
    pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
        sync=False, by="Test Operator", go=True))
    moved = open_pack(pack_dir).snapshot()
    assert moved["id"] != before["id"], "confirm did not move the snapshot"
    third, fourth = tmp / "three.md", tmp / "four.md"
    for out in (third, fourth):
        pm.cmd_review(argparse.Namespace(workdir=str(workdir),
                                         profile=profile_arg, checkpoint=9,
                                         out=str(out)))
    assert moved["id"] in third.read_text()
    # ...and the SNS-5 section is inside the same guarantee. It scores frames
    # with numpy and formats a similarity, either of which is a way to write a
    # number that differs between two renders of one pack.
    header = photo_profile.review_messages(
        open_pack(pack_dir).profile)["review_remembered_header"]
    assert header in third.read_text(), third.read_text()
    assert third.read_bytes() == fourth.read_bytes(), \
        "the re-presentation section is not stable"
    log(f"stable at {before['id']}, moved to {moved['id']} by confirm, and "
        "stable again with a remembered subject on the page")


# ------------------------------------------------------------ the table -----

def case_the_table_shows_the_gap_never_a_guessed_name(tmp):
    """TEMPLATE column rule 5, the honesty marker. An unnamed subject reads as
    a class word that comes from the OWNER PACK, never as a guess and never as
    a literal chosen by the renderer."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    text = (workdir / "memory-review_C1.md").read_text()
    pack = open_pack(pack_dir)
    rmsg = photo_profile.review_messages(pack.profile)
    word = photo_profile.scene_classes(pack.profile)["cat"]
    marker = rmsg["review_unnamed_subject"].format(kind=word)
    assert marker in text, (marker, text)
    assert "**Effect if answered:**" in text or \
        rmsg["review_effect_line"].split("{")[0].strip() in text
    assert "`who:`" in text and "`name:`" in text
    assert "saw" in text

    # the same table in an owner's own vocabulary, from the pack alone
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["review_messages"] = {"review_unnamed_subject": "one unnamed {kind}"}
    profile["naming_spec"] = {"types": []}
    profile["visual_sorting"] = {}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=5, out=None))
    assert "one unnamed" in (workdir / "memory-review_C5.md").read_text()
    log(f"unnamed subject rendered as {marker!r}, overridable from the pack")


def case_every_contact_sheet_image_is_on_disk(tmp):
    """TEMPLATE validator rule 3. A contact sheet that points at a file which
    is not there is the fabrication incident in the review artifact."""
    pack_dir, workdir = k_batch_run(tmp, 3)
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    text = (workdir / "memory-review_C1.md").read_text()
    import re
    images = re.findall(r"!\[\]\(([^)]+)\)", text)
    assert images, "no contact sheet at all"
    for rel in images:
        path = workdir / rel
        assert path.is_file(), f"{rel} is not on disk"
        assert not photo_evidence.sample_problems(path.name, path.parent), rel
    log(f"{len(images)} contact-sheet image(s), all real")


def case_the_proposals_block_is_idempotent(tmp):
    """Discovery writes its drafts into photo-proposals.md between markers, so
    a re-run replaces its own block and never duplicates it or eats the
    census's."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    proposals = pack_dir / "photo-proposals.md"
    text = proposals.read_text()
    assert text.count(pm.DRAFTS_BEGIN) == 1, text
    assert "ai-drafted" in text
    registry = psub.load(pack=open_pack(pack_dir))
    assert registry.drafts[0].subject_id in text
    pm.write_subject_drafts(open_pack(pack_dir), registry,
                            open_pack(pack_dir).profile)
    again = proposals.read_text()
    assert again.count(pm.DRAFTS_BEGIN) == 1
    assert again == text, "re-running discovery changed the block"
    assert "Promotion happens only at a memory checkpoint" in again, \
        "the template's own text was clobbered"
    log("one block, replaced in place")


def case_sync_pairs_the_registry_with_the_entities_twin(tmp):
    """One subject model, not two. A confirmed registry subject must exist in
    photo-entities.json under the SAME subject_id, or the claim the two design
    docs make is not held up by anything in the pack."""
    pack_dir = make_pack(tmp)
    registry = psub.Registry(directory=pack_dir / "photo-subjects")
    subject = registry.create_subject(name="Name-One", who="pet", kind="cat",
                                      active=["2029-03", None])
    subject.record["status"] = psub.STATUS_CONFIRMED
    registry.save()
    workdir = tmp / "dump"
    write_batches(workdir, 1)
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, file=None, sync=True, by="Test Operator", go=True))
    assert rc == 0
    entities = json.loads((pack_dir / "photo-entities.json").read_text())
    assert [r["subject_id"] for r in entities["pets"]] == [subject.subject_id]
    assert entities["pets"][0]["name"] == "Name-One"
    log("subject_id present on both halves of the pack")


def case_the_named_subject_count_is_said_and_never_capped(tmp):
    """SNS-9. There is NO cap on how many subjects may be remembered — the
    `{10}` this case used to assert was protecting a context cost that does not
    exist, and it was enforced at the one place a name is written. What is left
    is a count, said out loud past a soft warning, which refuses nothing.

    ⛔ And a pack still carrying the retired `named_subject_budget` must not
    quietly go on enforcing it. That is the exact shape of the defect this
    replaces: a signed decision left contradicted by a live constant, green
    the whole time because no test asserted the thing that changed."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    registry = psub.load(pack=open_pack(pack_dir))
    defaults = registry.data.setdefault("defaults", {})
    defaults["named_subject_budget"] = 1
    defaults["named_subjects_warn_at"] = 2
    filler = registry.create_subject(name="Name-Nine", who="friend",
                                     kind="person", active=["2029-01", None])
    filler.record["status"] = psub.STATUS_CONFIRMED
    registry.save()

    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    path.write_text(fill_pick(path.read_text(), [1]))
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
            sync=False, by="Test Operator", go=True))
    said = spoken.getvalue()
    assert rc == 0, said
    after = psub.load(pack=open_pack(pack_dir))
    assert sorted(s.name for s in after.subjects if s.name) == ["Name-Nine",
                                                               "Name-Two"]
    assert "2 remembered name(s)" in said, said
    assert "Nothing is refused" in said, said
    assert "no longer read" in said, said
    log("the second name past a warning bar of 2 is written, said out loud, "
        "and a retired `named_subject_budget` in the pack enforces nothing")


def case_a_blank_pack_memorizes_nothing_and_says_so(tmp):
    """The blank sheet. A run with no pack at all is not an error and is not a
    silent no-op — it reports that it had nowhere to memorize into."""
    workdir = tmp / "dump"
    report, index, samples = batch_fixture(workdir, 1, [(basis(0), 3)])
    rep = report["selected"][0]["path"]
    summary = apply_and_memorize(workdir, photo_profile.Pack(), report, index,
                                 samples, {rep: {"label": "Cat",
                                                 "subject_kind": "cat"}})
    assert summary["ran"] is False and "no owner pack" in summary["why"]
    log(summary["why"])


def case_two_lookalike_drafts_are_two_tiles_in_one_question(tmp):
    """F16 / ONB-13a. Cardinality is still never auto-resolved — what changed
    is WHO resolves it and in what shape. Two drafts too close to ignore and
    too far to merge are no longer an extra pair question; they are two
    numbered tiles inside the one `Group it` question their kind gets, and the
    owner decides whether they are one subject or two."""
    pack_dir, workdir, ids = two_lookalike_drafts(tmp)
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    text = (workdir / "memory-review_C1.md").read_text()
    blocks = pm.parse_review(text)
    assert len(blocks) == 1, [b["subject_ids"] for b in blocks]
    assert blocks[0]["subject_ids"] == ids, blocks[0]["subject_ids"]
    assert blocks[0]["tiles"] == {1: ids[0], 2: ids[1]}, blocks[0]["tiles"]
    assert "wrong merge" in text
    log(f"two lookalike drafts -> tiles 1 and 2 of one question, no merge")


def two_lookalike_drafts(tmp, owner="betauser00"):
    """Two drafts too close to ignore and too far to merge, each with its own
    looks on disk. -> (pack_dir, workdir, [subject_id, subject_id])."""
    pack_dir = make_pack(tmp, owner=owner)
    pack = open_pack(pack_dir)
    workdir = tmp / "dump"
    write_batches(workdir, 2)
    close = unit(basis(0) + 0.67 * basis(1))
    for batch, vec in ((1, basis(0)), (2, close)):
        report, index, samples = batch_fixture(workdir, batch, [(vec, 3)],
                                               month=f"2029-0{batch}")
        apply_and_memorize(workdir, pack, report, index, samples,
                           {report["selected"][0]["path"]:
                            {"label": "Cat", "subject_kind": "cat"}})
    registry = psub.load(pack=open_pack(pack_dir))
    ids = sorted(d.subject_id for d in registry.drafts)
    assert len(ids) == 2, ids
    return pack_dir, workdir, ids


def legacy_count_table(ids, answer="two", obs=0):
    """A pre-F16 `Count it` block, hand-written because the renderer no longer
    emits one. Trap 4: a work dir that already has history holds files in this
    shape, and `parse_review` has to keep reading them."""
    return (f"**Q1 · Count it** — affects 6 file(s) / 2 batch(es) · "
            f"similarity 0.83\n"
            "> Two drafts look alike. One subject or two?\n"
            "> **Effect if answered:** decides whether these files belong to "
            "one subject or two.\n"
            f"> `subjects:` {', '.join(ids)}\n"
            f"> `obs_count:` {obs}\n"
            f"> - `answer:` {answer}\n"
            "> - `skip:` [ ]\n"
            "```\n")


def case_one_answer_settles_every_member_id_and_only_what_it_answers(tmp):
    """F15, both halves — and both read back through `settled_subjects()` from
    the LOG ON DISK, because the log is the only dedupe layer that survives a
    new work dir and it is where the defect lived.

    Half 1, a CARDINALITY answer in the PRE-F16 shape. It says how many
    subjects are in front of the camera and nothing about who either of them
    is, so it settles neither of them. The log line used to say
    `human-confirmed` and name two ids, and the reader took the first: that
    member was closed forever although nobody had named it. F16 no longer
    renders this question — the grouping IS the cardinality answer — so the
    table is written by hand, which is also what proves the old shape still
    confirms out of a work dir that has one.

    Half 2, a GROUPED NAMING answer over the same two ids, on ONE line with
    three fields, which is the shape ONB-13a puts in front of an owner. One
    answer must settle EVERY member: name, relation, entities record,
    exemplars, and all of the ids on the log's maturity line where layer 3 can
    read them."""
    pack_dir, workdir, ids = two_lookalike_drafts(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")

    # -- half 1: a cardinality answer settles cardinality, not identity ------
    # Kept OUT of the work dir (--file) so this legacy table cannot also act as
    # a layer-2 record and suppress half 2 for a reason half 2 is not testing.
    legacy = tmp / "legacy_C1.md"
    legacy.write_text(legacy_count_table(ids))
    parsed = pm.parse_review(legacy.read_text())
    assert len(parsed) == 1 and parsed[0]["subject_ids"] == ids, parsed
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=1,
        file=str(legacy), sync=False, by="Test Operator", go=True))
    assert rc == 0, "the cardinality answer was refused"

    registry = psub.load(pack=open_pack(pack_dir))
    for subject_id in ids:
        assert registry.get(subject_id).record["cardinality_answer"] == "two"
    log_text = (pack_dir / "photo-memory-log.md").read_text()
    assert "cardinality" in log_text and all(i in log_text for i in ids)
    settled = pm.settled_subjects(open_pack(pack_dir))
    assert not [i for i in ids if i in settled], \
        f"a cardinality answer settled {settled} — F15 is not fixed"

    # ...so both are still askable, in this work dir and in a fresh one where
    # the log is the only layer left.
    fresh = tmp / "dump2"
    write_batches(fresh, 1)
    pack = open_pack(pack_dir)
    questions, _suppressed, _over, _held = pm.build_questions(
        psub.load(pack=pack), fresh, pack, pack.profile,
        photo_profile.review_messages(pack.profile))
    still_asked = {i for q in questions for i in q["subject_ids"]}
    assert still_asked == set(ids), still_asked

    # -- half 2: a grouped naming answer settles every member ----------------
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=2, out=None))
    second = workdir / "memory-review_C2.md"
    assert pm.parse_review(second.read_text())[0]["subject_ids"] == ids
    # what a human does under `Group it`: the two tiles are one animal, so
    # both numbers go on one `group:` row with the who and the name beside
    # them. Three fields, one line.
    second.write_text(fill_pick(second.read_text(), [1, 2]))
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=2, file=None,
        sync=False, by="Test Operator", go=True))
    assert rc == 0, "the grouped answer was refused"

    after = psub.load(pack=open_pack(pack_dir))
    for subject_id in ids:
        subject = after.get(subject_id)
        assert subject.status == psub.STATUS_CONFIRMED, subject.record
        assert subject.name == "Name-Two" and subject.who == "pet", subject.record
        assert subject.exemplars, f"{subject_id} was named but holds no exemplar"
    entities = json.loads((pack_dir / "photo-entities.json").read_text())
    assert sorted(r["subject_id"] for r in entities["pets"]) == ids, entities

    settled = pm.settled_subjects(open_pack(pack_dir))
    assert all(settled.get(i) == psub.STATUS_CONFIRMED for i in ids), settled
    # the ids have to be on the MATURITY line itself — the reader works one
    # physical line at a time, so an id on the `evidence:` continuation is an
    # id whose question comes back.
    maturity = [ln for ln in (pack_dir / "photo-memory-log.md").read_text()
                .splitlines() if ln.lstrip().startswith("| human-confirmed |")]
    assert len(maturity) == 1 and all(i in maturity[0] for i in ids), maturity

    # and nothing asks about either of them again, in a work dir that has
    # never seen a review file
    third = tmp / "dump3"
    write_batches(third, 1)
    pm.cmd_review(argparse.Namespace(workdir=str(third), profile=profile_arg,
                                     checkpoint=1, out=None))
    assert pm.parse_review((third / "memory-review_C1.md").read_text()) == []
    log(f"cardinality answer settled neither of {ids}; the grouped naming "
        "answer settled both, with exemplars")


def case_a_grouped_answer_is_one_name_in_the_count(tmp):
    """The count is of distinct NAMES, not subjects (F15's loop bug). One
    animal photographed as two drafts is ONE remembered name; counting it twice
    would have the warning fire a name early, and under the cap this replaces
    it could refuse a group part way through — member 1 named, member 2
    refused, one answer half applied."""
    pack_dir, workdir, ids = two_lookalike_drafts(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    registry.data.setdefault("defaults", {})["named_subjects_warn_at"] = 3
    filler = registry.create_subject(name="Name-Nine", who="friend",
                                     kind="person", active=["2029-01", None])
    filler.record["status"] = psub.STATUS_CONFIRMED
    registry.save()

    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    path.write_text(fill_pick(path.read_text(), [1, 2]))
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
            sync=False, by="Test Operator", go=True))
    said = spoken.getvalue()
    assert rc == 0, said
    after = psub.load(pack=open_pack(pack_dir))
    assert sorted({s.name for s in after.subjects if s.name}) == ["Name-Nine",
                                                                  "Name-Two"]
    assert all(after.get(i).status == psub.STATUS_CONFIRMED for i in ids)
    assert "remembered name(s)" not in said, \
        "two member ids under one name were counted as two names"
    log("a 2-member group is one name in the count, not two")


# =============================================================== F16 ========

def four_drafts(tmp, owner="betauser00", rendered=3):
    """Four separate drafts of ONE kind, with distinct blast radii so the tile
    order is a total order. -> (pack_dir, workdir, [id by descending files]).

    `rendered` caps `drafts_rendered_per_question` so the smallest one is
    never put in front of the owner at all — the case Trap 3 is about."""
    pack_dir = make_pack(tmp, owner=owner)
    pack = open_pack(pack_dir)
    workdir = tmp / "dump"
    write_batches(workdir, 4)
    for batch, (vec, members) in enumerate(
            ((basis(0), 6), (basis(4), 5), (basis(8), 4), (basis(12), 3)), 1):
        report, index, samples = batch_fixture(workdir, batch, [(vec, members)],
                                               month=f"2029-0{batch}")
        apply_and_memorize(workdir, pack, report, index, samples,
                           {report["selected"][0]["path"]:
                            {"label": "Cat", "subject_kind": "cat"}})
    registry = psub.load(pack=open_pack(pack_dir))
    registry.data.setdefault("defaults", {})["drafts_rendered_per_question"] = \
        rendered
    registry.save()
    ranked = sorted(registry.drafts,
                    key=lambda s: (-int(s.record.get("files", 0)),
                                   s.subject_id))
    assert len(ranked) == 4, [d.subject_id for d in ranked]
    return pack_dir, workdir, [d.subject_id for d in ranked]


def case_one_grouped_question_per_kind_with_a_parsed_tile_map(tmp):
    """ONB-13a's shape. One question for the kind, its drafts as numbered
    tiles ranked by blast radius, and — Trap 2 — a tile-number -> subject_id
    map that is WRITTEN DOWN and read back, not inferred from the order of a
    flat list. Nothing else can turn `group:` 1,3 into storage keys."""
    pack_dir, workdir, ranked = four_drafts(tmp)
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    text = (workdir / "memory-review_C1.md").read_text()
    blocks = pm.parse_review(text)
    assert len(blocks) == 1, [b["n"] for b in blocks]
    block = blocks[0]
    assert block["tiles"] == {1: ranked[0], 2: ranked[1], 3: ranked[2]}, \
        block["tiles"]
    # ...and each tile carries its OWN obs_count, which is what layer 2 reads.
    assert set(block["obs_by_id"]) == set(ranked[:3]), block["obs_by_id"]

    # TRAP 3. The fourth draft is named in the suppression comment — engine
    # deferrals are legible, not hidden — and NOWHERE a parser reads, so layer
    # 2 records nothing for a draft nobody was ever shown.
    assert ranked[3] not in block["subject_ids"], block["subject_ids"]
    assert f"     {ranked[3]}: not rendered" in text, text
    assert ranked[3] not in pm.asked_before(workdir), \
        "an unrendered draft was booked as asked"
    log(f"one question, tiles {sorted(block['tiles'])}, "
        f"{ranked[3]} deferred by the engine")


def case_layer_2_records_each_members_own_obs_count(tmp):
    """TRAP 6, read straight off `asked_before()`.

    The block used to hand ITS obs_count to every id on it. Under `Group it`
    every block is multi-member by construction, so each member's deferral bar
    became the whole group's evidence and C2 would look beautifully suppressed
    for the wrong reason — the LL-PHO-43 failure, silently. Each id must carry
    its own number, and a pre-F16 block with one scalar must still resolve."""
    workdir = tmp / "dump"
    workdir.mkdir(parents=True)
    (workdir / "memory-review_C1.md").write_text(
        "**Q1 · Group it — cat** — affects 20 file(s) / 3 batch(es) · a → b\n"
        "> 3 group(s) of photos look like a cat.\n"
        "> `subjects:` 1=subj-0001, 2=subj-0002, 3=subj-0003\n"
        "> `obs_count:` 1=7, 2=2, 3=1\n"
        "> - `group:` ______   `who:` ______   `name:` ______\n"
        "> - `skip:` ______\n"
        "```\n")
    (workdir / "memory-review_C2.md").write_text(
        legacy_count_table(["subj-0004", "subj-0005"], obs=9))

    seen = pm.asked_before(workdir)
    assert seen["subj-0001"] == (1, 7), seen
    assert seen["subj-0002"] == (1, 2), seen
    assert seen["subj-0003"] == (1, 1), seen
    # Trap 4: the pre-F16 shape in the same work dir still reaches layer 2. It
    # can only offer one scalar for both ids, which is all it ever recorded.
    assert seen["subj-0004"] == (2, 9) and seen["subj-0005"] == (2, 9), seen
    log(f"{len(seen)} id(s), each with its own bar where the file has one")


def case_grouped_deferred_and_skipped_never_collapse(tmp):
    """THE F16 CASE. Four drafts, three rendered, and the owner answers for
    one, says `skip:` to one, and leaves one alone.

    The C2 assertions read WHY each draft was or was not asked, never how many
    questions there are — "one question per kind" is true by construction and
    proves nothing, and suppression arriving from the wrong layer is exactly
    the defect (Trap 6). So:

      * the ANSWERED member is settled by layer 3, the log on disk — and it
        holds an exemplar, or it comes back next dump under a new id (F14);
      * the SKIPPED member is `rejected`, permanently;
      * the DEFERRED member — rendered, left out of every row — is still
        `ai-drafted` and comes back once its evidence grows. Under the old
        combined bar its bar would have been the whole group's obs_count and
        it would NOT return: that is Trap 6, measured behaviourally;
      * the NEVER-RENDERED draft comes back with no new evidence at all,
        because it was never in front of anybody and must never be recorded
        as asked.

    And no suppression anywhere may read `asked at C1`."""
    pack_dir, workdir, ranked = four_drafts(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")
    answered, deferred, skipped, unrendered = ranked

    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    text = fill_skip(fill_pick(path.read_text(), [1]), [3])
    path.write_text(text)
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
        sync=False, by="Test Operator", go=True))
    assert rc == 0, "the grouped answer was refused"

    registry = psub.load(pack=open_pack(pack_dir))
    assert registry.get(answered).status == psub.STATUS_CONFIRMED
    assert registry.get(answered).exemplars, \
        "the confirmed member holds no exemplar — it returns as a new id"
    assert registry.get(skipped).status == psub.STATUS_REJECTED
    for still_open in (deferred, unrendered):
        assert registry.get(still_open).status == psub.STATUS_DRAFT, \
            f"{still_open} was retired without anybody saying so"

    settled = pm.settled_subjects(open_pack(pack_dir))
    assert settled.get(answered) == psub.STATUS_CONFIRMED, settled
    assert settled.get(skipped) == psub.STATUS_REJECTED, settled
    assert deferred not in settled and unrendered not in settled, settled

    # the deferred member's evidence grows; the unrendered one's does not
    pack = open_pack(pack_dir)
    before = registry.get(deferred).obs_count
    report, index, samples = batch_fixture(workdir, 5, [(basis(4), 2)],
                                           month="2029-05")
    write_batches(workdir, 5)
    apply_and_memorize(workdir, pack, report, index, samples,
                       {report["selected"][0]["path"]:
                        {"label": "Cat", "subject_kind": "cat"}})
    grown = psub.load(pack=open_pack(pack_dir))
    assert grown.get(deferred).obs_count == before + 1, grown.get(deferred).record

    pack = open_pack(pack_dir)
    questions, suppressed, _over, _held = pm.build_questions(
        psub.load(pack=pack), workdir, pack, pack.profile,
        photo_profile.review_messages(pack.profile))
    asked = {i for q in questions for i in q["subject_ids"]}
    why = dict(suppressed)

    # ⚠️ THE assertion. An answered member leaves the draft pool, so it is
    # absent from the builder's loop rather than suppressed inside it — the
    # reason string `already human-confirmed` is unreachable for it. What must
    # be true is the conjunction: layer 3 closed it (read back from the log on
    # disk, above), it is not in the draft pool, it is not asked — and layer 2
    # never got the chance, because no suppression anywhere names an inflated
    # `asked at C1` bar.
    assert answered not in asked and skipped not in asked, asked
    assert answered not in {d.subject_id for d in grown.drafts}
    stale = {sid: reason for sid, reason in why.items() if "asked at C" in reason}
    assert not stale, f"layer 2's bar did the suppressing, not the owner: {stale}"
    assert deferred in asked, \
        (f"{deferred} was deferred, its evidence grew, and it did not come "
         f"back — its bar was the group's, not its own: {why.get(deferred)}")
    assert unrendered in asked, \
        (f"{unrendered} was never rendered and did not come back: "
         f"{why.get(unrendered)}")
    log(f"answered {answered} settled by the log; {skipped} rejected; "
        f"{deferred} and {unrendered} both back, neither behind an old bar")


def case_a_blank_row_is_not_a_rejection(tmp):
    """Trap 5, at the parser. A block whose only content is `pick:` rows must
    read as ANSWERED, and the rows the owner left blank must reach nothing —
    silence is never rejection, and it has to hold here rather than in
    doctrine. Frames named on more than one row are refused, not guessed."""
    pack_dir, workdir, ranked = four_drafts(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    blocks = pm.parse_review(fill_pick(path.read_text(), [1]))
    assert blocks[0]["answered"], "a `pick:`-only answer read as unanswered"
    assert len(blocks[0]["picks"]) == 1, blocks[0]["picks"]
    unit = blocks[0]["picks"][0]
    assert unit["verb"] == "pick" and unit["numbers"] == [1], unit
    assert unit["who"] == "pet" and unit["name"] == "Name-Two", unit
    assert unit["subject_ids"] == [ranked[0]] and unit["unknown"] == [], unit
    # the row carries the STORAGE KEY of every frame it picked, grouped by the
    # subject each one belongs to — that map is what promotion is gated on
    assert list(unit["refs"]) == [ranked[0]] and unit["refs"][ranked[0]], unit
    assert not blocks[0]["skip_numbers"] and not blocks[0]["skip"]

    # frame 1 on a pick row AND on the skip row: a contradiction the engine
    # refuses rather than resolves, and it must not reject anything.
    # ⛔ Frame 1 on a `pick:` row AND on the `skip:` row: BOTH rows go, and
    # neither answer is written. Before the two rows shared one numbering the
    # skip loop simply ran first, so the permanent answer won a contradiction
    # the owner was never told about — and the refusal they did see was about
    # the other row.
    path.write_text(fill_skip(fill_pick(path.read_text(), [1]), [1, 2]))
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
            sync=False, by="Test Operator", go=True))
    said = spoken.getvalue()
    assert rc == 1, "a frame claimed by two rows was applied anyway"
    assert "opposite things" in said, said
    after = psub.load(pack=open_pack(pack_dir))
    assert after.get(ranked[0]).status == psub.STATUS_DRAFT, \
        "the contested frame's subject was named anyway"
    assert after.get(ranked[0]).name is None, after.get(ranked[0]).record
    assert after.get(ranked[1]).status == psub.STATUS_DRAFT, \
        ("the `skip:` row was honoured for its other number — a contradiction "
         "refused half way is the half the owner cannot see")
    assert after.get(ranked[2]).status == psub.STATUS_DRAFT, \
        "a tile nobody named was rejected"
    log("blank rows reach nothing; a frame on `pick:` and `skip:` refuses both")


def case_an_unarmed_skip_rejects_nothing(tmp):
    """`skip:` is the only answer no later checkpoint can reach, so numbers
    alone are not it. Tile numbers with no `confirm` beside them are refused
    OUT LOUD and reject nothing — the two wrong moves being ruled out are
    honouring it quietly and dropping it quietly, because the owner who typed
    those numbers meant something and neither reading may be guessed."""
    pack_dir, workdir, ranked = four_drafts(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    path.write_text(fill_skip(path.read_text(), [2], armed=False))
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
        sync=False, by="Test Operator", go=True))
    assert rc == 1, "an unarmed `skip:` passed without a word said"
    after = psub.load(pack=open_pack(pack_dir))
    assert after.get(ranked[1]).status == psub.STATUS_DRAFT, \
        "an unarmed `skip:` rejected a subject anyway"

    # ...and the same numbers, typed on purpose, still work. Re-rendered at C1
    # rather than at C2 because layer 2 reads the review files in the work dir:
    # leaving C1's behind would suppress the very tiles this half needs, and
    # the assertion would then pass for the wrong reason.
    path.unlink()
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    assert pm.parse_review(path.read_text())[0]["tiles"][2] == ranked[1]
    path.write_text(fill_skip(path.read_text(), [2]))
    pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
        sync=False, by="Test Operator", go=True))
    after = psub.load(pack=open_pack(pack_dir))
    assert after.get(ranked[1]).status == psub.STATUS_REJECTED, \
        "an armed `skip:` did not reject"
    log("tile numbers alone reject nothing; the same numbers plus `confirm` do")


def case_a_subject_with_no_frames_is_never_asked(tmp):
    """Frames are the ONLY mechanism by which an owner can notice that one
    cluster holds two subjects. A tile with none invites a name typed blind, so
    it is not rendered at all — and it is DEFERRED, not rejected: the reason
    line has to say it is still askable, or this gate becomes a silent way to
    lose a subject."""
    pack_dir, workdir, ranked = four_drafts(tmp, rendered=4)
    registry = psub.load(pack=open_pack(pack_dir))
    blind = ranked[0]
    registry.get(blind).record["contact_sheet"] = []
    registry.save()

    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    text = (workdir / "memory-review_C1.md").read_text()
    block = pm.parse_review(text)[0]
    assert blind not in block["tiles"].values(), \
        "a subject with no example photo was put in front of the owner"
    assert set(block["tiles"].values()) == set(ranked[1:]), block["tiles"]
    assert f"{blind}: no example photo on disk" in text, \
        "the gate fired without saying so"
    assert "still askable" in text, \
        "a frameless subject was dropped without saying it comes back"
    log(f"{blind} has no frame, so it is not asked — and not retired either")


def case_the_classify_validator_reads_the_per_file_record(tmp):
    """The validator extension. The old check read one NOTE; a batch that went
    through the see stage now also has its seen-list cross-checked against the
    real thumbnails, under the same rules the memorize loop uses."""
    workdir = tmp / "dump"
    report, _index, samples = batch_fixture(workdir, 1, [(basis(0), 3)])
    write_batches(workdir, 1)
    batches = json.loads((workdir / "batches.json").read_text())
    batches["batches"][0].update({"status": "classified",
                                  "note": "viewed-image: a synthetic batch"})
    (workdir / "batches.json").write_text(json.dumps(batches))
    batch_dir = Path(samples).parent
    rep = report["selected"][0]["path"]
    other = report["clusters"][0]["members"][1]

    assert pm.load_json(batch_dir / "see-report.json") is not None
    assert not __import__("photo_classify_validate").see_stage_problems(batch_dir)

    pcv = __import__("photo_classify_validate")
    # a propagated label promoted to a look
    (batch_dir / "see-labels.json").write_text(json.dumps({"labels": [
        {"path": other, "label": "Cat", "provenance": "viewed-image:",
         "sample": report["selected"][0]["sample"]}]}))
    problems = pcv.see_stage_problems(batch_dir)
    assert any("never selected it" in p for p in problems), problems

    # a look with a hollowed-out thumbnail
    (Path(samples) / report["selected"][0]["sample"]).write_bytes(b"")
    (batch_dir / "see-labels.json").write_text(json.dumps({"labels": [
        {"path": rep, "label": "Cat", "provenance": "viewed-image:",
         "sample": report["selected"][0]["sample"]}]}))
    problems = pcv.see_stage_problems(batch_dir)
    assert any("empty" in p for p in problems), problems
    assert any("selected" in p for p in problems), problems
    log(f"{len(problems)} problem(s) found in the per-file record")


def case_the_plan_csv_records_who_and_what_provenance(tmp):
    """Deliverable 4. The four columns appear only when a plan's batches went
    through the see stage — that conditionality is what keeps every golden
    replay a comparison against the shipped decision — and when they appear,
    an unconfirmed subject's WHO carries the `draft:` prefix in front of its
    visual one, so a plan review shows which names rest on unconfirmed memory.
    """
    import csv as csvlib
    import photo_plan

    # The ONE case here that needs a frozen dump. Same resolver as the replay
    # harness (flag > $PHOTO_GOLDEN_FIXTURES > tests/golden) so a checkout
    # without fixtures skips this one case with a reason, rather than failing
    # the suite or — worse — passing quietly over a fixture that is not there.
    fixture = golden_replay.fixture_root() / "202602" / "input"
    if not fixture.is_dir():
        raise Skipped(f"no fixture at {fixture} — point "
                      f"${golden_replay.ENV_FIXTURES} at a fixture set")
    work = tmp / "dump"
    shutil.copytree(fixture, work)
    (work / "plan").mkdir(exist_ok=True)
    pack_dir = make_pack(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")
    env = dict(os.environ)
    env.pop("PHOTO_PROFILE", None)

    plan_py = [PY, str(ROOT / "scripts" / "photo_plan.py"), str(work),
               "--plan", "1", "--no-status"]
    # R1: the first half of this case IS the unseen condition, so it must say
    # so explicitly. The second half deliberately drops --no-vision -- that is
    # what proves the gate lets a seen batch through, and it is the reason
    # this case is not simply flagged --no-vision throughout.
    proc = subprocess.run(plan_py + ["--no-vision"],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with open(work / "plan" / "plan_P1-files.csv", newline="") as f:
        before = list(csvlib.DictReader(f))
    assert not any(k in before[0] for k in photo_plan.VISUAL_FIELDS), before[0]

    # now give batch 1 a see-stage record: one file looked at, its cluster
    # propagated, and the subject an unconfirmed draft
    paths = [r["SourceFile"] for r in before[:3]]
    out = work / "classify" / "batch-01"
    out.mkdir(parents=True, exist_ok=True)
    (out / "see-labels.json").write_text(json.dumps({"batch": 1, "labels": [
        {"path": paths[0], "label": "Cat", "provenance": "viewed-image:",
         "sample": "x.jpg", "subject": {"subject_kind": "cat"},
         "subject_provenance": "viewed-image:"},
        {"path": paths[1], "label": "Cat", "provenance": "clip-propagated:",
         "subject": {"subject_kind": "cat"},
         "subject_provenance": "clip-propagated:"},
        {"path": paths[2], "label": "Hiking", "provenance": "clip-matched:"},
    ]}, ensure_ascii=False))

    env["PHOTO_PROFILE"] = profile_arg
    proc = subprocess.run(plan_py, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with open(work / "plan" / "plan_P1-files.csv", newline="") as f:
        after = {r["SourceFile"]: r for r in csvlib.DictReader(f)}
    assert all(k in after[paths[0]] for k in photo_plan.VISUAL_FIELDS)
    assert after[paths[0]]["who_provenance"] == "draft:viewed-image:"
    assert after[paths[1]]["who_provenance"] == "draft:clip-propagated:"
    assert after[paths[2]]["who"] == "" and after[paths[2]]["who_provenance"] == ""
    assert after[paths[2]]["what_provenance"] == "clip-matched:"
    for row in after.values():
        for field, value in (("who_provenance", row["who_provenance"]),
                             ("what_provenance", row["what_provenance"])):
            assert not photo_evidence.plan_provenance_problems(value, field), value
    # WHO renders the class word from the pack, never a guessed name
    pack = open_pack(pack_dir)
    assert after[paths[0]]["who"] == photo_profile.scene_classes(pack.profile)["cat"]
    log("four columns, only when the see stage ran; draft: composes in front")


def case_the_cli_runs_end_to_end(tmp):
    """The wiring, through argparse and a real subprocess: see -> apply
    --memorize -> review -> confirm."""
    pack_dir = make_pack(tmp)
    sys.path.insert(0, str(ROOT / "tests"))
    import photo_see_cases as sc

    fixture = sc.Fixture()
    fixture.many(sc.basis(0), 6, real_image=True)
    fixture.many(sc.basis(1), 4, real_image=True)
    # the label file has to speak the pack's language, or photo_see refuses it
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    workdir = fixture.write(tmp, name="dump", real_images=True,
                            classes=list(ps.scene_label_set(profile)[0]))

    env = dict(os.environ)
    env.pop("PHOTO_PROFILE", None)
    profile_arg = str(pack_dir / "photo-profile.json")
    see = [PY, str(ROOT / "scripts" / "photo_see.py"), str(workdir), "--batch", "1",
           "--profile", profile_arg]
    proc = subprocess.run(see, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    report = json.loads((workdir / "classify" / "batch-01" /
                         "see-report.json").read_text())
    decisions = {e["path"]: {"label": "Cat", "subject_kind": "cat"}
                 for e in report["selected"][:1]}
    (tmp / "decisions.json").write_text(json.dumps(decisions))
    proc = subprocess.run(see + ["--apply", str(tmp / "decisions.json"),
                                 "--memorize"],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "memorize:" in proc.stdout, proc.stdout

    proc = subprocess.run([PY, str(ROOT / "scripts" / "photo_memory.py"),
                           "review", str(workdir), "--profile", profile_arg],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (workdir / "memory-review_C1.md").is_file()
    assert "checkpoint C1" in proc.stdout

    proc = subprocess.run([PY, str(ROOT / "scripts" / "photo_memory.py"),
                           "confirm", str(workdir), "--profile", profile_arg,
                           "--checkpoint", "1"],
                          capture_output=True, text=True, env=env)
    assert "dry run" in proc.stdout, proc.stdout
    assert "look(s) would be offered" not in proc.stdout, \
        "an unanswered question offered looks to the memorize rule"

    # ...and then answered for real. Everything above this line was written by
    # the see stage itself — the see-report, the applied labels and the embed
    # index are the pipeline's own files, not this suite's fixtures — so this
    # is where F14's promotion is proved against production shapes rather than
    # against a fixture that was built to agree with it.
    table = workdir / "memory-review_C1.md"
    assert pm.parse_review(table.read_text())[0]["subject_ids"], table.read_text()
    table.write_text(fill_pick(table.read_text(), [1]))
    proc = subprocess.run([PY, str(ROOT / "scripts" / "photo_memory.py"),
                           "confirm", str(workdir), "--profile", profile_arg,
                           "--checkpoint", "1", "--go"],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "exemplar(s) memorized" in proc.stdout, proc.stdout
    assert "NO exemplar" not in proc.stdout, proc.stdout
    # ⭐ R2, on the production path. This fixture has no identity index -- no
    # test runs photo_identity, and neither did UAT01 -- so every exemplar
    # just promoted is a whole-image CLIP vector. cmd_confirm already spoke
    # when a frame FAILED the quality bar and said nothing when there was no
    # bar at all, which is how a confirmed subject's bank ended up 60% another
    # animal with nothing reported (D-24 / LL-PHO-105). ⛔ A note, never a
    # refusal: the owner's answer must land whether or not a second model ran.
    assert "no identity index" in proc.stdout, proc.stdout
    assert "photo_identity.py" in proc.stdout, proc.stdout

    registry = psub.load(pack=open_pack(pack_dir))
    confirmed = [s for s in registry.subjects if not s.is_draft]
    assert len(confirmed) == 1 and confirmed[0].exemplars, [s.record for s in
                                                            registry.subjects]
    for exemplar in confirmed[0].exemplars:
        assert exemplar["confirmed_by"] == psub.MEMORIZE_PROVENANCE, exemplar
        assert Path(exemplar["evidence"]["see_report"]).is_file(), exemplar
    log("see -> apply --memorize -> review -> confirm --go, through the CLI; "
        f"{len(confirmed[0].exemplars)} exemplar(s) off the pipeline's own files")


# ------------------------------------------- SNS-1b: the split, end to end --

def split_a_draft(tmp, rows=((0, 2), (1,))):
    """K batches of one animal, then the owner partitions its frames.

    -> (pack_dir, workdir, registry, parent_id, result). `rows` indexes the
    parent's own frames in batch order, so `((0, 2), (1,))` is "frames 1 and 3
    are one subject, frame 2 is another" — the split OA-15 says cannot be
    expressed."""
    pack_dir, workdir = k_batch_run(tmp, 3)
    registry = psub.load(pack=open_pack(pack_dir))
    parent = registry.drafts[0]
    frames = [look["vec_ref"] for entry in parent.record["evidence"]
              for look in entry["looks"]]
    assert len(frames) == 3, frames

    # The centroids are computed by the CALLER, from the vectors behind the
    # frames each row picked — the registry holds no per-look vector and may
    # not reuse the parent's (SNS-1b's first ⛔).
    index, _identity = pm.load_embed_index(workdir)
    by_ref = {sha: vec for sha, vec in index.values()}
    groups = [{"vec_refs": [frames[i] for i in row],
               "centroid": unit(np.mean([by_ref[frames[i]] for i in row], axis=0))}
              for row in rows]
    result = registry.partition_subject(parent.subject_id, groups,
                                        by="Test Operator",
                                        reason="two subjects in one tile")
    return pack_dir, workdir, registry, parent.subject_id, result


def case_a_split_child_promotes_only_its_own_frames(tmp):
    """SNS-1b, both halves in one place: the surgery mints the children, and
    step 1's `only_refs` is what stops each of them promoting the other's
    frames. This is OA-15's mechanism, tested where it actually bites.

    The ORDER is not a convention. `add_exemplar()`'s third gate refuses a
    subject that is not `human-confirmed`, so a child is minted, then named,
    and only then promoted onto — the same order `confirm` itself uses."""
    pack_dir, workdir, registry, parent_id, result = split_a_draft(tmp)
    assert result["case"] == "split", result

    for n, spec in enumerate(result["children"]):
        child = registry.get(spec["subject_id"])
        # before the yes: refused, and the refusal is a note rather than a
        # silent skip
        gained, notes = attach_exemplars_named(registry, child, spec["vec_refs"])
        assert gained == 0 and notes, (gained, notes)
        assert any(psub.STATUS_DRAFT in note for note in notes), notes

        child.record.update({"name": f"Name-{n}", "who": "pet",
                             "status": psub.STATUS_CONFIRMED,
                             "confirmed_by": "Test Operator"})
        gained, notes = attach_exemplars_named(registry, child, spec["vec_refs"])
        assert gained == len(spec["vec_refs"]), (gained, notes)
        assert {e["vec_ref"] for e in child.exemplars} == set(spec["vec_refs"])

    first, second = (registry.get(c["subject_id"]) for c in result["children"])
    assert len(first.exemplars) == 2 and len(second.exemplars) == 1
    assert not ({e["vec_ref"] for e in first.exemplars}
                & {e["vec_ref"] for e in second.exemplars}), \
        "a child promoted a frame the owner gave to its sibling"
    # ...and the parent gained nothing at all: it is superseded, so gate 3
    # refuses it, and it recognises nothing on the evidence it still holds.
    parent = registry.get(parent_id)
    assert parent.exemplars == [], parent.exemplars
    assert parent not in registry.recognisers
    registry.save()
    reloaded = psub.load(pack=open_pack(pack_dir))
    assert {s.subject_id for s in reloaded.recognisers} == \
        {first.subject_id, second.subject_id}
    log(f"{parent_id} -> {first.subject_id} (2 frames) + "
        f"{second.subject_id} (1 frame), no crossover")


def attach_exemplars_named(registry, subject, refs):
    """`attach_exemplars` with `only_refs` spelled out, so a reader of these
    cases sees the argument that closed the bulk-promotion hole."""
    return pm.attach_exemplars(registry, subject, only_refs=list(refs))


def case_a_superseded_parent_leaves_the_question_loop(tmp):
    """SNS-1b's ⭐ claim, proved rather than asserted: `superseded` costs
    nothing to enforce because `is_draft` is a status whitelist, so
    `build_questions()` needs no change.

    ⚠️ A replay proves a rule does not misfire; only a written case proves it
    fires. No golden fixture holds a superseded record, so this is the only
    thing that would notice if the whitelist became a blacklist."""
    pack_dir, workdir, registry, parent_id, result = split_a_draft(tmp)
    children = [c["subject_id"] for c in result["children"]]
    registry.save()

    pack = open_pack(pack_dir)
    after = psub.load(pack=pack)
    assert parent_id not in {d.subject_id for d in after.drafts}
    questions, suppressed, _over, _held = pm.build_questions(
        after, workdir, pack, pack.profile,
        photo_profile.review_messages(pack.profile))
    asked = {i for q in questions for i in q["subject_ids"]}
    assert parent_id not in asked, asked
    assert parent_id not in dict(suppressed), suppressed
    # not suppressed INSIDE the loop — it never enters it, which is what "zero
    # changes to build_questions()" means and what makes the cost claim true
    assert set(children) <= asked, (children, asked)
    # each child is askable on its OWN inherited frames, not the parent's
    for question in questions:
        for tile in question["tiles"]:
            if tile["subject_id"] in children:
                assert tile["contact_sheet"], tile
                assert tile["files"] <= 4, \
                    ("a child was rendered with the parent's file count", tile)
    log(f"{parent_id} is out of the loop; {len(children)} children are asked")


def case_the_unseen_remainder_inherits_nothing(tmp):
    """SNS-1b item 4, verified rather than assumed — the SPEC's "no new code"
    claim rests entirely on a split parent being an UNNAMED draft.

    `photo_plan.py:131` gates on `known.name and not known.is_draft`, and
    `superseded` is outside the `is_draft` whitelist, so `not is_draft` is
    TRUE. The only thing standing between a superseded record and a name
    rendered as a confirmed answer is that it holds no name — which
    `partition_subject()` refuses to let it do."""
    import photo_plan

    pack_dir, workdir, registry, parent_id, result = split_a_draft(tmp)
    child_id = result["children"][0]["subject_id"]
    child = registry.get(child_id)
    child.record.update({"name": "Name-Zero", "who": "pet",
                         "status": psub.STATUS_CONFIRMED})
    registry.save()

    # a batch whose files were attributed to the parent's cluster: the ~200
    # nobody looked at, and one frame the owner did pick
    out = workdir / "classify" / "batch-09"
    out.mkdir(parents=True, exist_ok=True)
    remainder, picked = "/dump/unseen.JPG", "/dump/picked.JPG"
    (out / "see-labels.json").write_text(json.dumps({"batch": 9, "labels": [
        {"path": remainder, "label": "Cat", "provenance": "clip-propagated:",
         "subject": {"subject_id": parent_id, "subject_kind": "cat"},
         "subject_provenance": "clip-propagated:"},
        {"path": picked, "label": "Cat", "provenance": "viewed-image:",
         "subject": {"subject_id": child_id}, "sample": "x.jpg",
         "subject_provenance": "viewed-image:"},
    ]}, ensure_ascii=False))

    pack = open_pack(pack_dir)
    columns = photo_plan.visual_columns(workdir, [9], pack.profile, pack)
    class_word = photo_profile.scene_classes(pack.profile)["cat"]
    assert columns[remainder]["who"] == class_word, columns[remainder]
    assert columns[remainder]["who_provenance"] == "draft:clip-propagated:", \
        ("a superseded parent's files rendered as a confirmed answer",
         columns[remainder])
    assert columns[remainder]["who"] != "Name-Zero", \
        "the remainder inherited the child's name it never earned"
    # the frame the owner DID pick renders the name, with no draft: marker —
    # so the assertion above is about the remainder and not about the pack
    assert columns[picked]["who"] == "Name-Zero", columns[picked]
    assert columns[picked]["who_provenance"] == "viewed-image:", columns[picked]
    log(f"the remainder renders {class_word!r} with draft: provenance; "
        "the picked frame renders the name")


def stale_naming_table(subject_id, name="Name-Stale", skip=False):
    """A review block naming ONE id, in the flat pre-F16 shape a work dir with
    history still holds. Written by hand because the point is that it was
    rendered BEFORE the split and no renderer would emit it now."""
    # The pre-F16 whole-question skip box, which is the shape a stale file
    # holds. NOT tile numbers: those are refused by the "names a tile this
    # question never rendered" gate first, and the superseded gate — the one
    # under test — would never run.
    rows = ("> - `skip:` [x]\n" if skip else
            f"> - `who:` pet\n> - `name:` {name}\n")
    return (f"**Q1 · Name it** — affects 12 file(s) / 3 batch(es)\n"
            f"> `subjects:` {subject_id}\n" + rows + "```\n")


def case_a_stale_review_cannot_confirm_a_superseded_parent(tmp):
    """The hole the independent review of this build found, closed at the
    write point rather than promised at the mint point.

    A review file rendered BEFORE a split still names the parent and still
    parses — SNS-1b item 1's pinned-pack check is step 5, and `--go` only
    PRINTS the snapshot today. `cmd_confirm` checked that the id existed and
    nothing else, so the parent took `name` + `human-confirmed` + exemplars
    and came back a recogniser holding the same looks as its own children,
    where it competes with them in `match()` and ties or wins.

    `partition_subject()`'s refusal cannot reach this: it fires at the split,
    and this write happens afterwards. Both of `cmd_confirm`'s write paths are
    tested, because the `skip:` path flips the same record to `rejected`."""
    pack_dir, workdir, registry, parent_id, result = split_a_draft(tmp)
    child_ids = [c["subject_id"] for c in result["children"]]
    registry.save()
    profile_arg = str(pack_dir / "photo-profile.json")

    for skip in (False, True):
        stale = tmp / f"stale_{int(skip)}.md"
        stale.write_text(stale_naming_table(parent_id, skip=skip))
        # The refusal TEXT is asserted, not just the return code. `rc == 1` is
        # what any refusal returns — a parser regression that stopped reading
        # `subjects:` would refuse for its own reason, leave the parent
        # untouched, and let this case pass while testing nothing. That is the
        # wrong-reason trap the `skip:` half already fell into once.
        spoken = io.StringIO()
        with contextlib.redirect_stdout(spoken):
            rc = pm.cmd_confirm(argparse.Namespace(
                workdir=str(workdir), profile=profile_arg, checkpoint=1,
                file=str(stale), sync=False, by="Test Operator", go=True))
        assert rc == 1, f"a stale review reached a superseded parent (skip={skip})"
        said = spoken.getvalue()
        assert "superseded by a split" in said, (skip, said)
        assert all(c in said for c in child_ids), (skip, said)

        after = psub.load(pack=open_pack(pack_dir))
        parent = after.get(parent_id)
        assert parent.status == psub.STATUS_SUPERSEDED, parent.record
        assert parent.name is None, "a stale review named a superseded parent"
        assert parent.exemplars == [], "a superseded parent gained exemplars"
        assert parent_id not in {s.subject_id for s in after.recognisers}, \
            "a superseded parent came back as a recogniser"
        assert parent.record.get("split_into") == child_ids, parent.record

    log("a stale review file refuses on both write paths; the parent stays "
        "superseded, unnamed and unrecognised")


def case_a_stale_skip_cannot_reject_a_confirmed_subject(tmp):
    """⭐ OA-16, demonstrated live before it was fixed: the `skip:` path
    checked that the id existed and that it was not a split parent, and wrote
    `rejected` onto anything else — including a subject confirmed since the
    review was rendered. rc was 0. No refusal was spoken.

    What that left behind is the failure this build spent three refusals on
    one status along: `rejected` is outside `is_draft`, so the record kept its
    name and `photo_plan.py:132` went on printing it as a confirmed `who` with
    no `draft:` marker — while `recognisers` dropped it, so the name was being
    rendered by a record that recognises nothing and the files behind it
    quietly stopped being matched.

    The refusal TEXT is asserted, not just the return code: `rc == 1` is what
    any refusal returns, and a parser regression would refuse for its own
    reason and let this case pass while testing nothing."""
    pack_dir, workdir = k_batch_run(tmp, 3)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    subject_id = pm.parse_review(path.read_text())[0]["subject_ids"][0]
    # the file, kept as it was rendered — before the confirmation below
    stale = tmp / "stale_skip.md"
    stale.write_text(stale_naming_table(subject_id, skip=True))

    path.write_text(fill_pick(path.read_text(), [1]))
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
        sync=False, by="Test Operator", go=True))
    assert rc == 0
    before = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    assert before.status == psub.STATUS_CONFIRMED and before.name
    exemplars = len(before.exemplars)
    assert exemplars, "the fixture proves nothing without exemplars to keep"

    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=profile_arg, checkpoint=1,
            file=str(stale), sync=False, by="Test Operator", go=True))
    said = spoken.getvalue()
    assert rc == 1, f"a stale skip rejected a confirmed subject silently: {said}"
    assert "is confirmed as" in said and "--unconfirm" in said, said

    after = psub.load(pack=open_pack(pack_dir))
    subject = after.get(subject_id)
    assert subject.status == psub.STATUS_CONFIRMED, subject.record
    assert subject.name == before.name, "a stale file moved a confirmed name"
    assert len(subject.exemplars) == exemplars, "exemplars were lost"
    assert subject_id in {s.subject_id for s in after.recognisers}, \
        "the subject stopped recognising its own files"
    # the invariant the refusal exists for, read the way photo_plan reads it
    for record in after.subjects:
        if record.name and not record.is_draft:
            assert record.status == psub.STATUS_CONFIRMED, record.record
    log("a stale `skip:` refuses out loud; the confirmed subject keeps its "
        "name, its exemplars and its recognition")


def case_a_rejection_survives_a_dump_boundary_and_is_revivable(tmp):
    """OA-14 end to end, through the two files that carry a decision between
    runs — the registry and the memory log.

    ONB-13a:255 promised `rejected` was permanent. It was not: the record left
    the draft pool, held no exemplars, and so was invisible to BOTH
    suppression layers — the next dump minted a new id and asked the same
    question again. The retained centroid is what makes the promise true, and
    `--revive` is what keeps a promise that strong from also being a door with
    no handle."""
    pack_dir, workdir = k_batch_run(tmp, 3)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    text = path.read_text()
    subject_id = pm.parse_review(text)[0]["subject_ids"][0]
    path.write_text(fill_skip(text, [1]))

    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=profile_arg, checkpoint=1, file=None,
        sync=False, by="Test Operator", go=True))
    assert rc == 0
    registry = psub.load(pack=open_pack(pack_dir))
    subject = registry.get(subject_id)
    assert subject.status == psub.STATUS_REJECTED, subject.record
    assert subject.record["rejected"]["by"] == "Test Operator", subject.record
    assert registry.draft_centroid(subject_id) is not None, \
        "the rejection kept no centroid — nothing suppresses next dump"

    # a wholly new dump of the same animal: no new record, no new question
    fresh = tmp / "dump2"
    write_batches(fresh, 1)
    report, index, samples = batch_fixture(fresh, 1, [(basis(0), 4)],
                                           month="2030-01")
    rep = report["selected"][0]["path"]
    apply_and_memorize(fresh, open_pack(pack_dir), report, index, samples,
                       {rep: {"label": "Cat", "subject_kind": "cat"}})
    after = psub.load(pack=open_pack(pack_dir))
    assert [s.subject_id for s in after.subjects] == [subject_id], \
        "the rejected subject came back under a new id"
    assert after.drafts == [], "a rejection re-entered the draft pool"
    pm.cmd_review(argparse.Namespace(workdir=str(fresh), profile=profile_arg,
                                     checkpoint=1, out=None))
    assert pm.parse_review((fresh / "memory-review_C1.md").read_text()) == [], \
        "the rejected subject was asked about again"

    # and the way back reaches both layers: the status AND the log
    assert pm.settled_subjects(open_pack(pack_dir)).get(subject_id) == "rejected"
    after.revive(subject_id, by="Test Operator", reason="a mistake")
    after.save()
    pm.record_revive(open_pack(pack_dir), [{"subject_id": subject_id,
                                            "exemplars_retained": [],
                                            "draft_centroid": True}],
                     by="Test Operator", reason="a mistake")
    assert pm.settled_subjects(open_pack(pack_dir)).get(subject_id) is None, \
        "the log still closes a question the owner re-opened"
    third = tmp / "dump3"
    write_batches(third, 1)
    pm.cmd_review(argparse.Namespace(workdir=str(third), profile=profile_arg,
                                     checkpoint=1, out=None))
    revived = pm.parse_review((third / "memory-review_C1.md").read_text())
    assert revived and revived[0]["subject_ids"] == [subject_id], revived
    log("a rejection survives the dump boundary, and one verb re-opens it in "
        "both places at once")


def case_a_rejection_with_no_centroid_says_so(tmp):
    """The half of OA-14 that can still be missing after this build, said out
    loud rather than discovered next dump.

    `rejected_match()` suppresses on a retained draft centroid, and some
    records have never had one: a subject created already-named was never a
    draft, so nothing ever wrote one — and `--unconfirm` turns exactly that
    into a draft the owner can then reject. Every pack written before this
    commit is in the same position.

    The rejection is still honoured, so this is F14's WARNING channel and not
    a refusal: rc stays 0, the status is written, and what the operator is
    told is which promise the pack cannot keep."""
    pack_dir, workdir = k_batch_run(tmp, 1)
    pack = open_pack(pack_dir)
    registry = psub.load(pack=pack)
    # never a draft: no centroid was ever written for it
    subject = registry.create_subject(name="Name-Nine", who="pet", kind="cat",
                                      active=["2029-03", None])
    subject_id = subject.subject_id
    registry.unconfirm(subject_id, by="Test Operator")
    registry.save()
    assert registry.get(subject_id).is_draft
    assert registry.draft_centroid(subject_id) is None

    review = tmp / "skip_it.md"
    review.write_text(stale_naming_table(subject_id, skip=True))
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=1, file=str(review), sync=False, by="Test Operator",
            go=True))
    said = spoken.getvalue()
    assert rc == 0, f"an honoured rejection was reported as refused: {said}"
    assert "NO draft centroid" in said and "under a new id" in said, said
    after = psub.load(pack=open_pack(pack_dir))
    assert after.get(subject_id).status == psub.STATUS_REJECTED
    log("a rejection that cannot survive the dump boundary says so at the "
        "moment it is taken")


# ============================================ SNS-5 — the path back in =====

def fill_recheck(text, subject_id, answer):
    """What an owner types on a re-presentation row. The row is rendered with
    the id already on it — machine plumbing (SNS-8) — and a blank beside it.

    `answer` is a gesture, or a name, or a name with `same`/`distinct` after
    it: one grammar, and this helper does not know which of them was passed,
    which is the point. Every case below types into a row `render_review()`
    actually wrote."""
    row = f"`{pm.RECHECK_KEY}:` {subject_id} ______"
    assert row in text, f"no `{pm.RECHECK_KEY}:` row for {subject_id}"
    return text.replace(row, f"`{pm.RECHECK_KEY}:` {subject_id} {answer}", 1)


def log_text(pack):
    """The pack's memory log, or "" before anything has written one."""
    path = pm.log_path(pack)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def review_text(pack_dir, workdir, checkpoint=1):
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=checkpoint, out=None))
    return workdir / f"memory-review_C{checkpoint}.md"


def confirm(pack_dir, workdir, checkpoint=1, go=True):
    """-> (exit code, everything the run said out loud)."""
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=checkpoint, file=None, sync=False, by="Test Operator",
            go=go))
    return rc, spoken.getvalue()


def two_looks_apart(tmp, promote=(0,), owner="betauser00", frames=1):
    """A confirmed subject whose two remembered sightings do NOT look alike.

    `near(vec, 0)` returns the SAME vector for every batch's representative, so
    a fixture built by photographing one cluster twice gives every look an
    identical score and cannot tell a worst frame from a best one. Batch 2's
    cluster is rotated far enough to score differently and not so far that the
    draft dedupe forks a second record.

    `promote` is which looks become exemplars — the rest are what the check
    can actually see, since a look that IS an exemplar scores itself 1.000.
    -> (pack dir, work dir, subject_id, [vec_ref])."""
    pack_dir = make_pack(tmp, owner=owner)
    pack = open_pack(pack_dir)
    workdir = tmp / f"dump-{owner}"
    write_batches(workdir, 2)
    for batch, vec in enumerate((basis(0), unit(basis(0) + 0.35 * basis(1))), 1):
        report, index, samples = batch_fixture(workdir, batch, [(vec, 3)],
                                               month=f"2029-0{batch}")
        apply_and_memorize(workdir, pack, report, index, samples,
                           {report["selected"][0]["path"]:
                            {"label": "Cat", "subject_kind": "cat"}})
    registry = psub.load(pack=open_pack(pack_dir))
    assert len(registry.drafts) == 1, [d.subject_id for d in registry.drafts]
    subject = registry.drafts[0]
    subject.record.update({"name": "Name-Two", "who": "pet",
                           "status": psub.STATUS_CONFIRMED})
    refs = [look["vec_ref"] for entry in subject.record["evidence"]
            for look in entry["looks"]]
    assert len(refs) == 2, refs
    pm.attach_exemplars(registry, subject, [refs[i] for i in promote])
    # ...and the frame budget comes from the PACK, not from the engine (SNS-9).
    registry.data.setdefault("defaults", {})["frames_per_reconfirmation"] = frames
    registry.save()
    return pack_dir, workdir, subject.subject_id, refs


def rendered_frames(text, rmsg=None):
    """Every image the re-presentation section put on the page — never the
    question's own contact sheet, which is a different builder."""
    import re as _re
    header = (rmsg or photo_profile.REVIEW_VOCAB["en"])[
        "review_remembered_header"]
    return _re.findall(r"!\[\]\(([^)]+)\)", text.split(header)[-1])


def case_a_remembered_subject_comes_back_with_no_new_evidence(tmp):
    """SNS-5, the whole point of the word *unconditional*. A confirmed subject
    is unreachable today: `is_draft` keeps it out of `build_questions()` and
    `settled_subjects()` closes it for every later run — so a subject named
    wrongly and never photographed again is invisible forever, which is when
    the mistake is worst.

    The round has to reach it with NO new evidence at all: a work dir with no
    batches, no drafts and no questions still shows the name, a frame and the
    row that takes the name back. An evidence-gated re-presentation would
    preserve exactly the hole it was built to close."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    subject_id, rc = answer_the_question(pack_dir, workdir)
    assert rc == 0
    pack = open_pack(pack_dir)
    rmsg = photo_profile.review_messages(pack.profile)

    fresh = tmp / "a-dump-with-nothing-in-it"
    write_batches(fresh, 0)
    registry = psub.load(pack=pack)
    questions, _suppressed, _over, _held = pm.build_questions(registry, fresh, pack,
                                                pack.profile, rmsg)
    assert questions == [], "a confirmed subject was asked as a question"
    assert registry.drafts == [], [d.subject_id for d in registry.drafts]

    text = review_text(pack_dir, fresh).read_text()
    assert rmsg["review_remembered_header"] in text, text
    assert "Name-Two" in text, "the owner sees the NAME, not the id (SNS-8)"
    assert f"`{pm.RECHECK_KEY}:` {subject_id} ______" in text, text
    assert rendered_frames(text), "re-presented with no frame at all"

    # ⛔ and it is NOT a question: nothing here books the subject into layer 2,
    # or a re-presentation would suppress the draft question it is not.
    assert pm.parse_review(text) == [], pm.parse_review(text)
    assert subject_id not in pm.asked_before(fresh), pm.asked_before(fresh)
    # ...nor does it widen the status whitelists steps 2 and 3 rest on.
    assert not registry.get(subject_id).is_draft
    log(f"{subject_id} is re-presented in a round with no batches, no drafts "
        "and no questions")


def case_the_frame_shown_is_the_worst_scoring_one(tmp):
    """SNS-6 / Fable 5's finding 3, and the reason a one-frame glance can be a
    check at all: a subject shown by its BEST-matching frame looks correct
    every round even when it has absorbed a second animal, and the glance-yes
    then reinforces the error.

    Two sightings that do not look alike, and the exemplar set is what decides
    which is which — so the same fixture run twice, promoting the other look,
    must show the OTHER frame. A renderer that picked first, or
    representative, or best would pass one half of this and fail the other."""
    pack_dir, workdir, subject_id, refs = two_looks_apart(tmp, promote=(0,))
    text = review_text(pack_dir, tmp / "round-one").read_text()
    shown = rendered_frames(text)
    assert len(shown) == 1, ("frames_per_reconfirmation is read from the pack",
                             shown)
    assert "B2_C0.jpg" in shown[0], shown
    assert "B1_C0.jpg" not in shown[0], "the promoted look scored itself 1.000"

    other = two_looks_apart(tmp, promote=(1,), owner="betauser01")[0]
    flipped = rendered_frames(review_text(other, tmp / "round-two").read_text())
    assert len(flipped) == 1 and "B1_C0.jpg" in flipped[0], flipped

    # the number is on the page, because it saturates: right after a confirm
    # every look IS an exemplar and scores itself, and a bare "least certain"
    # with no score would read as a passed check.
    import re as _re
    scores = [float(s) for s in _re.findall(r"\b0\.\d{3}\b", text)]
    assert scores and max(scores) < 1.0, (scores, text)
    log(f"worst-scoring frame at {scores[0]}, and promoting the other look "
        "flips which frame is shown")


def case_an_unscoreable_frame_says_so_and_never_falls_back(tmp):
    """⛔ The single thing this build would be worth least without. Three
    failures are reachable — the look's work dir has been cleaned away, the
    index sha no longer matches the look's `vec_ref`, the subject holds no
    exemplar — and in each of them the honest answer is to show the frames
    there are and SAY the score could not be computed.

    A silent fallback to a representative or first or best frame would make
    SNS-6's drift check decoration while every other case in this file stayed
    green, because a frame nobody could score looks exactly like one that
    scored well."""
    pack = open_pack(make_pack(tmp, owner="vocab"))
    rmsg = photo_profile.review_messages(pack.profile)
    claim = rmsg["review_worst_frame_note"].split("{")[0].strip()

    def render(owner, wreck):
        pack_dir, workdir, subject_id, refs = two_looks_apart(
            tmp, promote=(0,), owner=owner, frames=2)
        wreck(pack_dir, workdir, subject_id, refs)
        return review_text(pack_dir, tmp / f"round-{owner}").read_text()

    def gone(pack_dir, workdir, subject_id, refs):
        shutil.rmtree(workdir / "embed")

    def moved(pack_dir, workdir, subject_id, refs):
        registry = psub.load(pack=open_pack(pack_dir))
        for entry in registry.get(subject_id).record["evidence"]:
            for look in entry["looks"]:
                look["vec_ref"] = "sha256:re-embedded-since"
        registry.save()

    def bare(pack_dir, workdir, subject_id, refs):
        registry = psub.load(pack=open_pack(pack_dir))
        registry.prune([subject_id], drop_refs=refs)
        assert registry.get(subject_id).exemplars == []
        registry.save()

    def torn(pack_dir, workdir, subject_id, refs):
        # `vectors_for()` REFUSES a record that disagrees with its `.npy`, and
        # `confirmed_match()` deliberately lets that raise so a suppression can
        # never fail in silence. A page is the other case: it is caught here,
        # because a table saying the score is unavailable beats no table.
        registry = psub.load(pack=open_pack(pack_dir))
        np.save(registry.vectors_path(subject_id),
                np.zeros((3, DIM), dtype=np.float32))

    for owner, wreck, key in (("gone", gone, "review_frame_why_no_index"),
                              ("moved", moved, "review_frame_why_re_embedded"),
                              ("bare", bare, "review_frame_why_no_exemplar"),
                              ("torn", torn,
                               "review_frame_why_vectors_broken")):
        text = render(owner, wreck)
        assert rmsg[key] in text, (owner, text)
        assert claim not in text, (owner, "a frame was called least-certain "
                                          "with no score behind it")
        assert rmsg["review_frames_unscored"].split("{")[0].strip() in text, \
            (owner, text)
        # the frames are still shown — the owner keeps what can be shown, and
        # is told what it does not prove.
        assert rendered_frames(text), (owner, "an honest gap became no frames")
        log(f"{owner}: {rmsg[key]}")


def case_a_frame_renders_relative_to_the_work_dir_being_reviewed(tmp):
    """TEMPLATE validator rule 3, for the section that needs it most.

    The table is written INTO the work dir, and a draft tile's contact sheet
    is stored work-dir-relative for exactly that reason: the link resolves
    where the file sits. An absolute link is treated as root-relative by
    common markdown previewers and shows a blank — and a blank frame beside
    "leave blank if it is still right" is a glance-yes against nothing, which
    is the failure SNS-6's worst-frame rule exists to prevent. The frames are
    the whole point of this section; if they do not render it is inert.

    Absolute is still the right answer for a look from an EARLIER dump, whose
    photos are nowhere near the work dir being reviewed. Both forms are
    pinned, so neither can be simplified into the other."""
    pack_dir, workdir, subject_id, refs = two_looks_apart(tmp, promote=(0,),
                                                          frames=2)
    shown = rendered_frames(review_text(pack_dir, workdir,
                                        checkpoint=5).read_text())
    assert len(shown) == 2, shown
    for rel in shown:
        assert not Path(rel).is_absolute(), \
            (rel, "an in-work-dir frame is absolute and will not render")
        path = workdir / rel
        assert path.is_file(), rel
        assert not photo_evidence.sample_problems(path.name, path.parent), rel

    # a later dump reviewing the same pack: those photos are somewhere else,
    # and only an absolute link can reach them.
    elsewhere = tmp / "a-later-dump"
    write_batches(elsewhere, 0)
    away = rendered_frames(review_text(pack_dir, elsewhere).read_text())
    assert len(away) == 2, away
    for path in away:
        assert Path(path).is_absolute() and Path(path).is_file(), path
    log("frames render relative inside the work dir and absolute from another")


def case_a_re_presentation_promotes_nothing(tmp):
    """SNS-6 — re-confirmation promotes only the frames the owner PICKED, and
    there is no `pick:` grammar until step 5. So this path promotes nothing at
    all: wiring "re-confirming promotes its shown frames" would widen the
    human yes onto a one-frame glance, which is the hole `only_refs` exists to
    close.

    Also the silence test for the whole section. Every row is rendered with a
    hint that names the gestures, so a parser reading the raw line would find
    `withdraw` on every row the engine itself wrote — a file nobody touched
    would withdraw the profile. Confirmed untouched: zero changes, zero
    refusals, and a pack that has not moved."""
    pack_dir, workdir, subject_id, refs = two_looks_apart(tmp, promote=(0,))
    before = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    held = [e["vec_ref"] for e in before.exemplars]
    assert len(held) == 1, held
    snapshot = open_pack(pack_dir).snapshot()["id"]

    review_text(pack_dir, workdir, checkpoint=7)
    rc, said = confirm(pack_dir, workdir, checkpoint=7, go=True)
    assert rc == 0, said
    assert "0 change(s)" in said or "wrote 0 change(s)" in said, said

    after = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    assert [e["vec_ref"] for e in after.exemplars] == held, \
        "a re-presentation promoted an exemplar"
    assert after.status == psub.STATUS_CONFIRMED and after.name == "Name-Two"
    assert open_pack(pack_dir).snapshot()["id"] == snapshot, \
        "an untouched review moved the pack"
    assert pm.parse_representations(
        (workdir / "memory-review_C7.md").read_text()) == [], \
        "the hint's own words were read as an answer"
    log("an untouched round writes nothing and promotes nothing")


def case_a_rejection_is_re_presented_without_frames_and_revived(tmp):
    """OA-14's remaining half. A rejection now ACTIVELY suppresses
    (`rejected_match()` on the retained centroid), so it must be visible and
    reachable without a CLI — and compact, because a rejection is a question
    the owner closed and re-showing its photos is asking it again.

    The way back has to reach all three layers at once: the status, the
    memory log's `rejected` line, and the work dir that already asked."""
    pack_dir, workdir = k_batch_run(tmp, 3)
    path = review_text(pack_dir, workdir, checkpoint=1)
    subject_id = pm.parse_review(path.read_text())[0]["subject_ids"][0]
    path.write_text(fill_skip(path.read_text(), [1]))
    rc, said = confirm(pack_dir, workdir, checkpoint=1)
    assert rc == 0, said
    pack = open_pack(pack_dir)
    rmsg = photo_profile.review_messages(pack.profile)
    assert pm.settled_subjects(pack).get(subject_id) == "rejected"

    text = review_text(pack_dir, workdir, checkpoint=2).read_text()
    assert rmsg["review_rejected_header"] in text, text
    listed = text.split(rmsg["review_rejected_header"])[-1]
    assert subject_id in listed, listed
    assert "![](" not in listed, "a rejection was re-presented WITH its frames"
    assert f"`{pm.RECHECK_KEY}:` {subject_id} ______" in listed, listed
    # untouched, the section says nothing — the rejection's own line carries a
    # date and the word `rejected`, and neither may read as a gesture.
    assert pm.parse_representations(text) == [], pm.parse_representations(text)

    second = workdir / "memory-review_C2.md"
    second.write_text(fill_recheck(second.read_text(), subject_id,
                                   pm.GESTURE_REVIVE))
    rc, said = confirm(pack_dir, workdir, checkpoint=2)
    assert rc == 0, said
    pack = open_pack(pack_dir)
    registry = psub.load(pack=pack)
    assert registry.get(subject_id).status == psub.STATUS_DRAFT
    assert f"| {pm.REVIVED} |" in log_text(pack), log_text(pack)
    assert pm.settled_subjects(pack).get(subject_id) is None, log_text(pack)
    questions, suppressed, _over, _held = pm.build_questions(
        registry, workdir, pack, pack.profile, rmsg)
    assert [q["subject_ids"] for q in questions] == [[subject_id]], \
        (questions, suppressed)

    # ...and answering it again spends the exemption, on the `rejected` path
    # as well as the confirmed one.
    third = review_text(pack_dir, workdir, checkpoint=3)
    third.write_text(fill_skip(third.read_text(), [1]))
    rc, said = confirm(pack_dir, workdir, checkpoint=3)
    assert rc == 0, said
    again = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    assert again.status == psub.STATUS_REJECTED, again.record
    assert psub.REOPENED_FLAG not in again.record, again.record
    log("a rejection is one line with no frames, revivable from the round, "
        "and the revival reaches the status, the log and the work dir")


def case_a_withdrawal_reaches_the_work_dir_that_already_asked(tmp):
    """Step 4's third deliverable, and the half that can go wrong by being too
    broad. Layer 2 books every id a review file rendered; a withdrawal has to
    clear it for THAT subject and for nobody else.

    Two drafts, both rendered at C1. One is named and the name is withdrawn;
    the other is simply left alone. The withdrawn one comes back, the deferred
    one stays deferred behind the bar it always had — an exemption that
    disabled the bar for everyone would pass a one-subject test."""
    pack_dir = make_pack(tmp)
    pack = open_pack(pack_dir)
    workdir = tmp / "dump"
    write_batches(workdir, 2)
    for batch in (1, 2):
        report, index, samples = batch_fixture(
            workdir, batch, [(basis(0), 4), (basis(3), 3)],
            month=f"2029-0{batch}")
        reps = [c["representative"] for c in report["clusters"]]
        apply_and_memorize(workdir, pack, report, index, samples,
                           {reps[0]: {"label": "Cat", "subject_kind": "cat"},
                            reps[1]: {"label": "Cat", "subject_kind": "cat"}})
    rmsg = photo_profile.review_messages(pack.profile)
    path = review_text(pack_dir, workdir, checkpoint=1)
    tiles = pm.parse_review(path.read_text())[0]["tiles"]
    assert len(tiles) == 2, tiles
    a_id, b_id = tiles[1], tiles[2]
    path.write_text(fill_pick(path.read_text(), [1]))
    rc, said = confirm(pack_dir, workdir, checkpoint=1)
    assert rc == 0, said

    pack = open_pack(pack_dir)
    registry = psub.load(pack=pack)
    result = registry.unconfirm(a_id, by="Test Operator", reason="wrong name")
    registry.save()
    pm.record_unconfirm(pack, [result], by="Test Operator")

    pack = open_pack(pack_dir)
    registry = psub.load(pack=pack)
    questions, suppressed, _over, _held = pm.build_questions(registry, workdir, pack,
                                               pack.profile, rmsg)
    asked = [s for q in questions for s in q["subject_ids"]]
    assert asked == [a_id], (asked, suppressed)
    assert "asked at C1" in dict(suppressed).get(b_id, ""), suppressed

    # the exemption is spent by the answer, not permanent: A named again holds
    # no flag, so the next checkpoint treats it like B.
    second = review_text(pack_dir, workdir, checkpoint=2)
    second.write_text(fill_pick(second.read_text(), [1], name="Name-Three"))
    rc, said = confirm(pack_dir, workdir, checkpoint=2)
    assert rc == 0, said
    answered = psub.load(pack=open_pack(pack_dir)).get(a_id)
    assert answered.status == psub.STATUS_CONFIRMED, answered.record
    assert psub.REOPENED_FLAG not in answered.record, answered.record
    log(f"{a_id} withdrawn and asked again in the same work dir; {b_id} stays "
        "behind the bar it earned")


def case_stop_asking_about_this_one_is_refused_out_loud(tmp):
    """⛔ The gesture `cmd_confirm`'s OA-16 refusal promised step 4 would carry
    — and neither step 4 nor step 5 carries it, out loud.

    ⚠️ Step 5 supplied the freshness proof this refusal was first written
    against (the pinned-snapshot check), and the refusal stands anyway,
    because staleness was only half of it. A rejection may never be written
    onto a record that still holds a name — and a re-presented subject holds
    one by definition, or it would not be in the remembered section at all. So
    the gesture is withdraw-then-reject however fresh the page is, and a row
    carries one gesture, so it cannot be both at once.

    The refusal's OWN words and the id it names are asserted, not `rc == 1`:
    an unknown-gesture or no-such-subject gate firing first would return the
    same code while testing nothing."""
    pack_dir, workdir, subject_id, refs = two_looks_apart(tmp, promote=(0,))
    before = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    held = [e["vec_ref"] for e in before.exemplars]
    log_before = log_text(open_pack(pack_dir))

    path = review_text(pack_dir, workdir, checkpoint=4)
    path.write_text(fill_recheck(path.read_text(), subject_id,
                                 pm.GESTURE_REJECT))
    rc, said = confirm(pack_dir, workdir, checkpoint=4)
    assert rc == 1, f"a rejection was typed onto a named subject: {said}"
    assert subject_id in said and "--unconfirm" in said, said
    assert "withdraw-then-reject" in said, said
    assert "`skip:`" in said, "the refusal does not say where the answer goes"

    after = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    assert after.status == psub.STATUS_CONFIRMED, after.record
    assert after.name == "Name-Two", after.record
    assert [e["vec_ref"] for e in after.exemplars] == held, "exemplars moved"
    assert "rejected" not in after.record, after.record
    assert log_text(open_pack(pack_dir)) == log_before, "the log was written"
    log("the permanent gesture is refused by name, and points at --unconfirm")


def case_a_gesture_is_a_dry_run_until_go(tmp):
    """`review` never writes the pack and `confirm` does — and a dry run is
    still a dry run when the gesture is a withdrawal. `unconfirm()` appends to
    the memorize audit log at the decision point, so calling it without `--go`
    would move the pack snapshot from a run that promised to write nothing.
    Same reason `attach_exemplars()` is deferred to `--go`."""
    pack_dir, workdir, subject_id, refs = two_looks_apart(tmp, promote=(0,))
    snapshot = open_pack(pack_dir).snapshot()["id"]
    path = review_text(pack_dir, workdir, checkpoint=3)
    path.write_text(fill_recheck(path.read_text(), subject_id,
                                 pm.GESTURE_WITHDRAW))

    rc, said = confirm(pack_dir, workdir, checkpoint=3, go=False)
    assert rc == 0, said
    assert "dry run" in said and "withdrawn" in said, said
    assert open_pack(pack_dir).snapshot()["id"] == snapshot, \
        "a dry run moved the pack"
    still = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    assert still.status == psub.STATUS_CONFIRMED and still.name == "Name-Two"

    # ...and a dry run has to predict `--go`. Two rows for one record would
    # report two changes and then deliver one change and a refusal, because
    # the second row's verb reads the status the first one moved.
    doubled = path.read_text().replace(
        f"`{pm.RECHECK_KEY}:` {subject_id} {pm.GESTURE_WITHDRAW}",
        f"`{pm.RECHECK_KEY}:` {subject_id} {pm.GESTURE_WITHDRAW}\n"
        f"> - `{pm.RECHECK_KEY}:` {subject_id} {pm.GESTURE_WITHDRAW}", 1)
    (workdir / "twice.md").write_text(doubled)
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=3, file=str(workdir / "twice.md"), sync=False,
            by="Test Operator", go=False))
    said = spoken.getvalue()
    assert rc == 1 and "more than one row" in said, said
    assert "1 change(s) would be written" in said, said

    rc, said = confirm(pack_dir, workdir, checkpoint=3, go=True)
    assert rc == 0, said
    pack = open_pack(pack_dir)
    withdrawn = psub.load(pack=pack).get(subject_id)
    assert withdrawn.is_draft and withdrawn.name is None, withdrawn.record
    assert withdrawn.previous_names == ["Name-Two"], withdrawn.record
    assert f"| {pm.UNCONFIRMED} |" in log_text(pack), log_text(pack)
    assert subject_id not in pm.settled_subjects(pack), log_text(pack)
    entities = json.loads((pack_dir / "photo-entities.json").read_text())
    assert not [r for r in entities.get("pets") or []
                if r["subject_id"] == subject_id], \
        "the entities twin still asserts the identity the owner took back"
    log("withdraw is inert without --go, and reaches all three files with it")


def one_page_two_sections(tmp, frames=2):
    """A page carrying BOTH a remembered subject and a live draft question.

    Two builders write those sections and step 4 kept them apart on purpose;
    the numbering is the one thing that has to cross between them (SNS-8), so
    a fixture that holds only one of them cannot see the fold at all.
    -> (pack dir, work dir, the rendered text, the remembered subject_id)."""
    pack_dir, workdir, subject_id, _refs = two_looks_apart(tmp, frames=frames)
    pack = open_pack(pack_dir)
    write_batches(workdir, 3)
    report, index, samples = batch_fixture(workdir, 3, [(basis(9), 3)],
                                           month="2029-05")
    apply_and_memorize(workdir, pack, report, index, samples,
                       {report["selected"][0]["path"]:
                        {"label": "Cat", "subject_kind": "cat"}})
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    return (pack_dir, workdir,
            (workdir / "memory-review_C1.md").read_text(), subject_id)


def frame_markers(text):
    """The frame numbers the page printed beside its photographs, in order."""
    import re as _re
    marker = photo_profile.REVIEW_VOCAB["en"]["review_frame_number"]
    return [int(n) for n in _re.findall(
        _re.escape(marker).replace(r"\{n\}", r"(\d+)"), text)]


def case_the_frames_line_maps_every_frame_and_is_never_inferred(tmp):
    """SNS-1b item 1. Every photograph on a question carries a NUMBER the owner
    can type and a `frames:` entry that turns it into a storage key.

    The assertion that matters is the pairing: one entry per rendered image,
    in the same order, each naming the tile's own subject and a `vec_ref` that
    subject's evidence actually holds. A map with more entries than images
    offers a frame nobody saw; one with fewer renders a number that promotes
    nothing — and both look identical on the page."""
    _pack_dir, _workdir, text, _remembered = one_page_two_sections(tmp)
    questions = text.split(
        photo_profile.REVIEW_VOCAB["en"]["review_remembered_header"])[0]
    import re as _re
    images = _re.findall(r"!\[\]\(([^)]+)\)", questions)
    block = pm.parse_review(text)[0]
    assert block["frames"], "no `frames:` line was parsed back"
    assert len(block["frames"]) == len(images), (block["frames"], images)
    assert sorted(block["frames"]) == list(range(1, len(images) + 1)), \
        block["frames"]
    assert [block["frames"][n]["path"] for n in sorted(block["frames"])] \
        == images, "the map and the page disagree about which photo is which"

    registry = psub.load(pack=open_pack(_pack_dir))
    for n, entry in block["frames"].items():
        subject = registry.get(entry["subject_id"])
        assert subject is not None, entry
        assert entry["subject_id"] in block["tiles"].values(), (n, entry)
        held = {pm.short_ref(look["vec_ref"])
                for look in pm.subject_looks(subject)}
        assert entry["ref"] in held, (entry, held)
    log(f"{len(images)} frame(s), each numbered, each keyed to a look")


def case_one_numbering_spans_the_whole_page(tmp):
    """SNS-8, and step 4 recorded it as this step's debt in as many words: the
    `recheck:` rows must draw their frame numbers from the ONE global sequence
    rather than survive beside it.

    ⛔ And the remembered frames get a number and NO `frames:` entry. A
    re-presentation promotes nothing (SNS-5, SNS-6), so a mapping line under
    that section would build the promotion path this step is required not to
    have — the absence of the map is the guarantee, not a check on it."""
    _pack_dir, _workdir, text, _remembered = one_page_two_sections(tmp)
    header = photo_profile.REVIEW_VOCAB["en"]["review_remembered_header"]
    questions, remembered = text.split(header)[0], text.split(header)[-1]

    asked = frame_markers(questions)
    rechecked = frame_markers(remembered)
    assert asked and rechecked, (asked, rechecked)
    assert not set(asked) & set(rechecked), \
        "a remembered subject numbered its frames beside the questions, not in "
    assert asked + rechecked == list(range(1, len(asked) + len(rechecked) + 1)), \
        (asked, rechecked)
    assert "`frames:`" not in remembered, \
        "a re-presented frame was given a promotion key"
    log(f"frames {asked} ask, frames {rechecked} re-check, one sequence")


def case_a_partial_pick_promotes_only_the_picked_frames(tmp):
    """⭐ OA-15, at the line it was open on. Five frames of one draft on the
    page, two of them picked: TWO exemplars, not five.

    The count is the finding and the refs are the proof. Before this the call
    site enumerated every look the record held and the answer was 5 — so a
    tile holding two animals promoted both on one name, and F14 then
    suppressed the second one forever. A test that only checked "some
    exemplars were gained" passed then and would pass now.

    ⚠️ Asserted on what the REGISTRY holds, never on what was handed to
    `attach_exemplars()`. Intercepting the call would prove the caller's
    intention; reading the record proves the write."""
    pack_dir, workdir = k_batch_run(tmp, 5)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    block = pm.parse_review(path.read_text())[0]
    subject_id = block["subject_ids"][0]
    assert sorted(block["frames"]) == [1, 2, 3, 4, 5], block["frames"]
    assert len(pm.subject_looks(psub.load(pack=open_pack(pack_dir))
                                .get(subject_id))) == 5, \
        "the fixture proves nothing unless the record holds more looks than " \
        "the owner picks"

    path.write_text(fill_pick(path.read_text(), None, frames="2,4"))
    rc, said = confirm(pack_dir, workdir, checkpoint=1)
    assert rc == 0, said

    subject = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    assert len(subject.exemplars) == 2, \
        (f"{len(subject.exemplars)} exemplar(s) from a 2-of-5 pick — the "
         "answer promoted frames the owner did not choose")
    picked = {block["frames"][n]["ref"] for n in (2, 4)}
    assert {pm.short_ref(e["vec_ref"]) for e in subject.exemplars} == picked, \
        [e["vec_ref"] for e in subject.exemplars]
    # ...and the three frames left out are DEFERRED, not rejected: the looks
    # are still on the record, and nothing about them was written down.
    assert len(pm.subject_looks(subject)) == 5, subject.record
    assert "rejected" not in subject.record, subject.record
    log(f"5 look(s) on the record, 2 frame(s) picked, "
        f"{len(subject.exemplars)} exemplar(s) — was 5 before this step")


def one_draft_three_unlike_frames(tmp, owner="betauser00"):
    """One draft whose three frames do NOT look alike. -> (pack dir, work dir).

    `k_batch_run()` photographs the same cluster every batch, so every one of
    its frames carries the identical vector — which is fine for counting
    exemplars and useless for a split, where the question is whether the two
    children were built out of their OWN frames or out of the parent. Each
    batch here is rotated far enough to be a different photograph and not so
    far that the draft dedupe forks a second record."""
    pack_dir = make_pack(tmp, owner=owner)
    pack = open_pack(pack_dir)
    workdir = tmp / f"dump-{owner}"
    write_batches(workdir, 3)
    for batch, vec in enumerate((basis(0),
                                 unit(basis(0) + 0.30 * basis(1)),
                                 unit(basis(0) + 0.30 * basis(2))), 1):
        report, index, samples = batch_fixture(workdir, batch, [(vec, 4)],
                                               month=f"2029-0{batch}")
        apply_and_memorize(workdir, pack, report, index, samples,
                           {report["selected"][0]["path"]:
                            {"label": "Cat", "subject_kind": "cat"}})
    registry = psub.load(pack=open_pack(pack_dir))
    assert len(registry.drafts) == 1, [d.subject_id for d in registry.drafts]
    return pack_dir, workdir


def case_two_pick_rows_split_one_draft_through_the_confirm(tmp):
    """SNS-1b item 3, end to end and through the owner's own gesture —
    `partition_subject()`'s FIRST caller. Two rows naming frames of one draft
    is the split OA-15 says cannot be expressed.

    Four things have to be true together, and each of them is a way this could
    be wrong on its own: two children exist, the parent is `superseded` and
    holds no name, each child's exemplars are exactly its own row's frames,
    and NEITHER child's identity vector is the parent's. The last one is the
    ⛔ SNS-1b puts first: re-using the parent's centroid builds both children
    out of the grouping the split just disproved, and an obliging
    `or parent_centroid` would do it in one keystroke."""
    pack_dir, workdir = one_draft_three_unlike_frames(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    block = pm.parse_review(path.read_text())[0]
    parent_id = block["subject_ids"][0]
    before = psub.load(pack=open_pack(pack_dir))
    parent_vector = before.draft_centroid(parent_id)
    assert parent_vector is not None, "the fixture's parent has no centroid"

    # "frames 1 and 3 are one animal; frame 2 is another" — one draft, two rows
    text = fill_pick(path.read_text(), None, frames="1,3", name="Name-A")
    text = fill_pick(text, None, frames="2", name="Name-B")
    path.write_text(text)

    # the dry run predicts it and writes nothing at all
    snapshot = open_pack(pack_dir).snapshot()["id"]
    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=False)
    assert rc == 0 and "split into 2 subject(s)" in said, said
    assert open_pack(pack_dir).snapshot()["id"] == snapshot, \
        "the dry run moved the pack — the split ran without --go"

    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=True)
    assert rc == 0, said

    after = psub.load(pack=open_pack(pack_dir))
    parent = after.get(parent_id)
    assert parent.status == psub.STATUS_SUPERSEDED, parent.record
    assert parent.name is None, "a split parent kept a name"
    children = parent.record.get("split_into") or []
    assert len(children) == 2, parent.record
    assert after.draft_centroid(parent_id) is not None, \
        "the parent's own vector was deleted — it is the audit trail"

    wanted = {"Name-A": {block["frames"][n]["ref"] for n in (1, 3)},
              "Name-B": {block["frames"][2]["ref"]}}
    for child_id in children:
        child = after.get(child_id)
        assert child.status == psub.STATUS_CONFIRMED, child.record
        assert child.who == "pet" and child.name in wanted, child.record
        assert {pm.short_ref(e["vec_ref"]) for e in child.exemplars} \
            == wanted[child.name], (child.name, child.exemplars)
        vector = after.draft_centroid(child_id)
        assert vector is not None, f"{child_id} was minted with no centroid"
        assert not np.allclose(vector, parent_vector), \
            (f"{child_id} inherited the parent's centroid — the split is "
             "built out of the grouping it disproved")
    assert not np.allclose(after.draft_centroid(children[0]),
                           after.draft_centroid(children[1])), \
        "both children were given the same identity vector"
    log(f"{parent_id} -> {children[0]} (2 frames) + {children[1]} (1 frame), "
        "each on its own centroid")


def case_a_subset_skip_splits_before_it_rejects(tmp):
    """SNS-1b item 5, signed: split-then-reject. `skip:` naming SOME of a
    subject's frames says *the thing in these photographs — never ask*, which
    is not *this record — never ask*.

    ⛔ Two widenings are ruled out here and they fail in opposite directions.
    Rejecting the whole record retires frames the owner said nothing about.
    Splitting off only the skipped frames leaves the rest inside a
    `superseded` parent — outside `is_draft`, so out of the question loop, so
    retired without anybody saying so, which is the same loss with a longer
    receipt.

    So the assertion is not that the leftover frames stayed where they were:
    they move to a child, which is the point. It is that they are STILL ASKED
    ABOUT — the record that holds them is a live draft with a contact sheet,
    and the next round renders it."""
    pack_dir, workdir = one_draft_three_unlike_frames(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    block = pm.parse_review(path.read_text())[0]
    parent_id = block["subject_ids"][0]
    assert sorted(block["frames"]) == [1, 2, 3], block["frames"]

    # "the thing in frame 2 is not a subject" — and frames 1 and 3 are left
    # alone, which is not an answer about them at all
    path.write_text(fill_skip(path.read_text(), None, frames="2"))
    snapshot = open_pack(pack_dir).snapshot()["id"]
    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=False)
    assert rc == 0 and "one of them rejected" in said, said
    assert "frames you left alone" in said, \
        "the dry run did not say the leftover frames keep their own record"
    assert open_pack(pack_dir).snapshot()["id"] == snapshot, \
        "the dry run moved the pack — the split ran without --go"

    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=True)
    assert rc == 0, said

    after = psub.load(pack=open_pack(pack_dir))
    parent = after.get(parent_id)
    assert parent.status == psub.STATUS_SUPERSEDED, parent.record
    children = parent.record.get("split_into") or []
    assert len(children) == 2, parent.record

    skipped, kept = (after.get(c) for c in children)
    assert skipped.status == psub.STATUS_REJECTED, skipped.record
    assert skipped.name is None, "a rejected record holds no name"
    assert skipped.exemplars == [], "a rejection gained recognition evidence"
    assert {pm.short_ref(look["vec_ref"])
            for look in pm.subject_looks(skipped)} \
        == {block["frames"][2]["ref"]}, skipped.record
    assert after.draft_centroid(skipped.subject_id) is not None, \
        "the rejection kept nothing to suppress on — OA-14's whole point"
    assert pm.settled_subjects(open_pack(pack_dir)).get(
        skipped.subject_id) == "rejected"

    # ...and the frames the owner left alone are STILL A QUESTION
    assert kept.status == psub.STATUS_DRAFT, kept.record
    assert kept.name is None, kept.record
    assert {pm.short_ref(look["vec_ref"]) for look in pm.subject_looks(kept)} \
        == {block["frames"][n]["ref"] for n in (1, 3)}, kept.record
    assert parent_id not in pm.settled_subjects(open_pack(pack_dir)), \
        "the parent was settled by an answer that was only about one frame"

    pack = open_pack(pack_dir)
    questions, suppressed, _over, _held = pm.build_questions(
        psub.load(pack=pack), workdir, pack, pack.profile,
        photo_profile.review_messages(pack.profile))
    asked = {i for q in questions for i in q["subject_ids"]}
    assert kept.subject_id in asked, \
        ("the frames the owner left alone were retired by a `skip:` that "
         f"never named them: {dict(suppressed)}")
    assert skipped.subject_id not in asked, asked
    assert parent_id not in asked, asked
    log(f"{parent_id} -> {skipped.subject_id} rejected (1 frame) + "
        f"{kept.subject_id} still asked (2 frames)")


def case_a_pick_cannot_reach_a_frame_this_question_never_rendered(tmp):
    """One numbering across the page (SNS-8) means a number the owner types is
    unambiguous — and it also means a number can name a photograph that is not
    this question's to promote.

    A remembered subject's frames are numbered and carry no `frames:` entry,
    so `pick:` on one resolves to nothing and is refused. ⛔ That is
    structural rather than a check: a re-presentation promotes zero exemplars
    (SNS-5, SNS-6), and there is no map under that section for a promotion to
    travel through."""
    pack_dir, workdir, text, remembered = one_page_two_sections(tmp)
    header = photo_profile.REVIEW_VOCAB["en"]["review_remembered_header"]
    theirs = frame_markers(text.split(header)[-1])
    assert theirs, "the fixture rendered no remembered frame"

    path = workdir / "memory-review_C1.md"
    path.write_text(fill_pick(text, None, frames=str(theirs[0])))
    rc, said = confirm(pack_dir, workdir, checkpoint=1)
    assert rc == 1, said
    assert f"never rendered" in said, said
    assert pm.RECHECK_KEY in said, "the refusal did not say where that frame " \
                                   "is answered instead"
    subject = psub.load(pack=open_pack(pack_dir)).get(remembered)
    assert len(subject.exemplars) == 1, \
        ("a re-presented frame was promoted through a pick row",
         subject.exemplars)
    log(f"frame {theirs[0]} belongs to the remembered section; picking it is "
        "refused and promotes nothing")


def case_a_name_collision_asks_and_never_merges(tmp):
    """SNS-7. The owner types a name the pack already remembers, and the
    engine RAISES the question rather than answering it.

    ⛔ Never merged on the string match: a name is not an identity (N-10a),
    and it is in a language the owner chose, so matching the letters is both a
    guess and a locale-dependent one. Fragmentation makes this ordinary rather
    than exotic — the first rounds name the same animal more than once before
    its exemplar set is broad enough to catch itself.

    The armed answer is the other half: `distinct` forces a separate slot, and
    the two subjects then share a rendered name and nothing else. That is
    already how the storage works — `subject_id` is the key — so what the
    token buys is the owner having SAID so."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    profile_arg = str(pack_dir / "photo-profile.json")
    first, rc = answer_the_question(pack_dir, workdir, name="Name-Shared")
    assert rc == 0

    # a second animal, a later dump, and the owner reaches for the same name
    later, _summary = photograph_again(tmp, pack_dir, name="dump2",
                                       vec=basis(11), month="2030-02")
    pm.cmd_review(argparse.Namespace(workdir=str(later), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = later / "memory-review_C1.md"
    second = pm.parse_review(path.read_text())[0]["subject_ids"][0]
    assert second != first, "the fixture drafted no second subject"

    path.write_text(fill_pick(path.read_text(), [1], name="Name-Shared"))
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(later), profile=profile_arg, checkpoint=1, file=None,
            sync=False, by="Test Operator", go=True))
    said = spoken.getvalue()
    assert rc == 1, f"a name collision was resolved by the engine: {said}"
    assert first in said, "the refusal did not say which subject already holds it"
    assert pm.DISTINCT_TOKEN in said, "the refusal did not offer the way on"
    after = psub.load(pack=open_pack(pack_dir))
    assert after.get(second).name is None, after.get(second).record
    assert after.get(second).is_draft, "a refused row confirmed the subject"

    # the same row, armed: a separate slot, and NOTHING moved between the two
    # Re-rendered at C1 rather than at C2, because layer 2 reads the review
    # files in this work dir: leaving the refused page behind would suppress
    # the very tile the second half needs, and nothing about a REFUSED row
    # should book a question as asked.
    held = [e["vec_ref"] for e in after.get(first).exemplars]
    path.unlink()
    pm.cmd_review(argparse.Namespace(workdir=str(later), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = later / "memory-review_C1.md"
    path.write_text(fill_pick(path.read_text(), [1],
                              name=f"Name-Shared {pm.DISTINCT_TOKEN}"))
    rc, said = confirm(pack_dir, later, checkpoint=1)
    assert rc == 0, said

    final = psub.load(pack=open_pack(pack_dir))
    assert final.get(second).status == psub.STATUS_CONFIRMED
    assert final.get(second).name == "Name-Shared", \
        ("the armed token was written into the name", final.get(second).record)
    assert final.get(second).subject_id != first, "two ids became one"
    assert [e["vec_ref"] for e in final.get(first).exemplars] == held, \
        "the first subject gained or lost evidence from the second's answer"
    # Compared on the SOURCE file, not the `vec_ref`: this fixture's refs are
    # invented per (batch, cluster, member) and repeat across work dirs, so a
    # ref comparison here would fail on the fixture rather than on the code.
    assert not ({e["source"] for e in final.get(first).exemplars}
                & {e["source"] for e in final.get(second).exemplars}), \
        "the two subjects share an exemplar — the engine merged after all"
    log(f"{first} and {second} share the name {'Name-Shared'!r} and nothing "
        "else")


def case_two_rows_one_name_asks_before_the_pack_moves(tmp):
    """SNS-7, on the half `held` cannot see: BOTH rows are on this page.

    ⭐ The collision that matters most is the one inside a single round. The
    registry check reads the pack, and the two-pass split writes nothing until
    every row has been judged — so the second row of a pair looks at a pack
    that has not moved, and without `pending` the ask never happens. A round
    answered by naming two fragments of one cluster the same thing is exactly
    what fragmentation produces, which is what this step was told to expect in
    the first real rounds.

    ⛔ It is not cosmetic that two ids end up sharing a name.
    `photo_recurrence.subject_folder()` keys on identity (N-10a) but renders
    `folder_name` off the NAME, so two keys become ONE folder on disk: the
    registry stays honest and the drive does not.

    Asserted on the registry, and on the row that DID survive — the refusal is
    per row (SNS-11), so the first row's answer is still written."""
    pack_dir, workdir = one_draft_three_unlike_frames(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    text = fill_pick(path.read_text(), None, name="Name-Twice", frames="1")
    path.write_text(fill_pick(text, None, name="Name-Twice", frames="2"))
    rc, said = confirm(pack_dir, workdir, checkpoint=1)

    assert rc == 1, f"two rows took one name with no question asked: {said}"
    assert "earlier row" in said, \
        ("the refusal blamed the pack for a collision that is on the page", said)
    assert pm.DISTINCT_TOKEN in said, "the refusal did not offer the way on"
    after = psub.load(pack=open_pack(pack_dir))
    named = [s for s in after.subjects if s.name == "Name-Twice"]
    assert len(named) == 1, \
        (f"{len(named)} subjects hold one name — they render one folder_name "
         "and land in one directory", [s.subject_id for s in named])
    # ...and the surviving row was still applied: a refusal on row 2 must not
    # discard the answer the owner got right on row 1.
    assert named[0].status == psub.STATUS_CONFIRMED, named[0].record
    # No split, either. One row survived, so there was never a partition to
    # perform — a superseded parent here would mean the surgery ran on an
    # answer that was half refused.
    assert not [s for s in after.subjects
                if s.status == psub.STATUS_SUPERSEDED], \
        "a refused row still split its draft"

    # The armed answer — on its own fixture, because the round above CONFIRMED
    # the draft it was asked about and a confirmed subject asks nothing.
    pack_dir, workdir = one_draft_three_unlike_frames(tmp / "armed")
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    text = fill_pick(path.read_text(), None, name="Name-Twice", frames="1")
    path.write_text(fill_pick(text, None, frames="2",
                              name=f"Name-Twice {pm.DISTINCT_TOKEN}"))
    rc, said = confirm(pack_dir, workdir, checkpoint=1)
    assert rc == 0, said
    final = psub.load(pack=open_pack(pack_dir))
    slots = sorted(s.subject_id for s in final.subjects
                   if s.name == "Name-Twice")
    assert len(slots) == 2, (slots, said)
    assert not ({e["source"] for e in final.get(slots[0]).exemplars}
                & {e["source"] for e in final.get(slots[1]).exemplars}), \
        "the two slots share an exemplar — the engine merged after all"
    log(f"two rows, one name: refused; armed, {slots[0]} and {slots[1]} share "
        "the name and nothing else")


def case_a_legacy_group_row_is_parsed_and_refused(tmp):
    """Decision A. A work dir with history holds review files written with
    `group:` on TILE numbers, and they still parse — `asked_before()` globs
    every one of them, so a parser that stopped reading the old shape would
    blind layer 2 in exactly the work dirs that have history.

    ⛔ What such a row may DO is nothing. A tile is a whole record, so
    honouring one promotes every look behind it — OA-15's mechanism, kept
    alive in the only work dirs old enough to hit it. The refusal names the
    fix, and the fix is one cheap command."""
    pack_dir, workdir = k_batch_run(tmp, 3)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    subject_id = pm.parse_review(path.read_text())[0]["subject_ids"][0]
    # what a pre-step-5 page looks like: the old verb, and no frame map
    legacy = fill_group(path.read_text(), "1")
    legacy = "\n".join(line for line in legacy.splitlines()
                       if "`frames:`" not in line)
    (workdir / "legacy.md").write_text(legacy)

    block = pm.parse_review(legacy)[0]
    assert block["answered"] and block["groups"], block
    assert not block["frames"], "the fixture still carries a frame map"

    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=profile_arg, checkpoint=1,
            file=str(workdir / "legacy.md"), sync=False, by="Test Operator",
            go=True))
    said = spoken.getvalue()
    assert rc == 1, said
    assert "`group:`" in said and subject_id in said, said
    assert "review" in said, "the refusal did not name the way out"

    after = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    assert after.is_draft and after.name is None, after.record
    assert after.exemplars == [], \
        "a legacy row promoted the whole record's looks — OA-15, surviving"
    log("a `group:` row parses, is refused whole, and names `review` as the fix")


def case_a_review_older_than_the_pack_is_refused_whole(tmp):
    """SNS-1b item 1. The page pins the pack it was rendered against; the pack
    moves; `confirm` applies NOTHING.

    ⚠️ The assertion that matters is the word WHOLE. `confirm` applies per row
    everywhere else (SNS-11), so a check that merely refused the rows it could
    not resolve would pass a weaker test and still write the rows that happen
    to still parse — under numbers that no longer mean what the page says they
    mean. So the answered row here is one that would SUCCEED against a fresh
    page: if anything is written, the gate is per-row and the case fails."""
    pack_dir, workdir = k_batch_run(tmp, 3)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    subject_id = pm.parse_review(path.read_text())[0]["subject_ids"][0]
    pinned = pm.pinned_snapshot(path.read_text())
    assert pinned, "review wrote no snapshot id into its header"

    # the pack moves under the page: another dump, the same animal, one more
    # observation written into the registry
    photograph_again(tmp, pack_dir, name="a-later-dump")
    moved = open_pack(pack_dir).snapshot()["id"]
    assert moved != pinned, "the fixture did not move the pack"

    path.write_text(fill_pick(path.read_text(), [1]))
    for go in (False, True):
        spoken = io.StringIO()
        with contextlib.redirect_stdout(spoken):
            rc = pm.cmd_confirm(argparse.Namespace(
                workdir=str(workdir), profile=profile_arg, checkpoint=1,
                file=None, sync=False, by="Test Operator", go=go))
        said = spoken.getvalue()
        assert rc == 1, (go, said)
        assert pinned in said and moved in said, said
        assert "review" in said, "the refusal did not name the way out"
    after = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    assert after.name is None, "a stale page named a subject"
    assert after.is_draft, after.record
    assert after.exemplars == [], "a stale page promoted an exemplar"
    assert pm.settled_subjects(open_pack(pack_dir)) == {}, \
        "a stale page closed the question in the memory log"
    log(f"the page pinned {pinned}, the pack moved to {moved}, nothing applied")


# =========================================== SNS-4: the round cadence =======

def review(pack_dir, workdir, checkpoint, final=False):
    """One `review` run, with its console line captured. -> (text, said)."""
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        pm.cmd_review(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=checkpoint, out=None, final=final))
    return (workdir / f"memory-review_C{checkpoint}.md").read_text(), \
        spoken.getvalue()


def review_rc(pack_dir, workdir, checkpoint, final=False, pre_plan=False):
    """One `review` run, keeping its EXIT CODE. -> (rc, text, said).

    Separate from `review()` above rather than a wider return on it: only the
    pre-plan checkpoint has an rc that means anything, and every other case in
    this file would then be carrying a value it does not read."""
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_review(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=checkpoint, out=None, final=final, pre_plan=pre_plan))
    return rc, (workdir / f"memory-review_C{checkpoint}.md").read_text(), \
        spoken.getvalue()


def case_a_pre_plan_round_says_it_asked_and_is_charged_once(tmp):
    """U-2. The naming round moved BEFORE `plan`, so the conductor has to know
    whether a question was actually put — it has to hold the copy until the
    answer is in, and it cannot see the registry or the pages to work that out.
    `--pre-plan` answers exactly that, as an exit code.

    ⛔ An ORDINARY round, not `--final`: it is charged, and the guaranteed
    end-of-dump round must still fire afterwards. Two of four, never three —
    the pre-plan round spends one, the final round spends none of the budget
    but still writes a page that `rounds_fired()` counts."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=1)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"new_fss_floor": 1, "sns_rounds_per_dump": 4}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))

    rc, text, said = review_rc(pack_dir, workdir, 1, pre_plan=True)
    assert len(pm.parse_review(text)) == 1, "the pre-plan round did not fire"
    assert rc == pm.PRE_PLAN_ROUND_FIRED_RC, f"rc {rc}"
    assert "a question was put to the owner" in said, said
    # ⛔ NOT the final round: it is charged, and it says the floor is why.
    assert "not charged" not in text, text
    assert pm.rounds_fired(workdir) == 1

    # The dump ends as it always did, and the guaranteed round still asks.
    _rc, third, _said = review_rc(pack_dir, workdir, 2, final=True)
    assert len(pm.parse_review(third)) == 1, "the last round did not fire"
    assert pm.rounds_fired(workdir) == 2, "2 of 4, not 3"
    log("a pre-plan round asks, reports rc "
        f"{pm.PRE_PLAN_ROUND_FIRED_RC}, is charged once, and the guaranteed "
        "final round still fires — 2 of 4")


def case_a_pre_plan_round_that_withheld_reports_nothing_to_hold_for(tmp):
    """GUARD. ⛔ The rc means *a question was put*, never *the flag was
    passed*. Below the floor nothing is asked, nothing is booked, and the
    conductor must go straight on to planning — a checkpoint that held the
    copy every time it ran would be the blocking gate U-2 must not become."""
    pack_dir, workdir, _ids = two_lookalike_drafts(tmp)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile.pop("memory", None)
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))

    rc, text, said = review_rc(pack_dir, workdir, 1, pre_plan=True)
    assert pm.parse_review(text) == [], "a withheld round rendered its block"
    assert rc == 0, f"rc {rc} — a withheld round asked the caller to stop"
    assert "a question was put to the owner" not in said, said
    assert pm.rounds_fired(workdir) == 0, "a withheld round was charged"
    log("a withheld pre-plan round returns 0 and books nothing")


def case_a_plain_review_never_returns_the_pre_plan_code(tmp):
    """GUARD. `finish` reads a non-zero `review` as *no page was written* and
    warns. ⛔ So the rc belongs to `--pre-plan` alone: were it returned by
    every firing checkpoint, the guaranteed end-of-dump round would print that
    warning every time it did its job."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=1)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"new_fss_floor": 1, "sns_rounds_per_dump": 4}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))

    rc, text, _said = review_rc(pack_dir, workdir, 1)
    assert len(pm.parse_review(text)) == 1, "the round did not fire"
    assert rc == 0, f"a plain review returned {rc}"
    rc, _text, _said = review_rc(pack_dir, workdir, 2, final=True)
    assert rc == 0, f"the final round returned {rc}"
    log("a firing round returns 0 unless --pre-plan asked for the answer")


def case_a_round_two_pre_plan_stop_names_the_page_it_wrote(tmp):
    """U5-06 (REPRODUCTION). ⛔ FAILS on 5826436, whose line printed
    `confirm <work dir> --go`: `confirm` defaults to checkpoint 1, so from the
    second page on the owner's paste opened the round-1 page, which the pinned
    check refuses as stale — nothing written, twice in UAT01-5. The page number
    comes from the default (`--checkpoint` not passed), as on a real run."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=1)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"new_fss_floor": 1, "sns_rounds_per_dump": 4}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))
    (workdir / "memory-review_C1.md").write_text("an earlier page\n",
                                                 encoding="utf-8")

    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_review(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=None, out=None, final=False, pre_plan=True))
    said = spoken.getvalue()
    assert rc == pm.PRE_PLAN_ROUND_FIRED_RC, f"rc {rc}"
    assert (workdir / "memory-review_C2.md").exists(), "no page 2 was written"
    assert "answer memory-review_C2.md" in said, said
    assert f'confirm "{workdir.resolve()}" --checkpoint 2 --go' in said, said
    log("a round-2 pre-plan stop prints `confirm ... --checkpoint 2 --go`")


def case_a_pre_plan_stop_written_elsewhere_names_the_file(tmp):
    """U5-06 (GUARD). `confirm` finds its page from `--checkpoint` alone, so a
    page written with `--out` to any other path must be named by `--file` too,
    or the printed command opens the wrong page."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=1)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"new_fss_floor": 1, "sns_rounds_per_dump": 4}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))
    out = tmp / "elsewhere" / "page.md"

    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_review(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=3, out=str(out), final=False, pre_plan=True))
    said = spoken.getvalue()
    assert rc == pm.PRE_PLAN_ROUND_FIRED_RC, f"rc {rc}"
    assert f'--checkpoint 3 --file "{out}" --go' in said, said
    log("a page written with --out is named by --file in the printed command")


def case_a_round_is_withheld_below_the_floor_and_says_so(tmp):
    """SNS-4. Two newly-seen subjects do not reach the floor of 3, so no round
    fires — and the page SAYS which of the two reasons it was, because an
    owner who is told nothing cannot tell a decision from a fault.

    ⛔ And the withheld question block does not reach the file at all. A page
    that printed its `subjects:` map without asking would book those ids into
    layer 2 (`asked_before()` reads every review file in the work dir), so the
    drafts would be withheld and suppressed at once."""
    pack_dir, workdir, ids = two_lookalike_drafts(tmp)
    # the engine's own numbers, not the fixture's cadence-off ones
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile.pop("memory", None)
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))

    text, said = review(pack_dir, workdir, 1)
    assert pm.parse_review(text) == [], "a withheld round rendered its block"
    assert "no SNS round here" in text, text
    assert f"the floor is {pm.DEFAULT_NEW_FSS_FLOOR}" in text, text
    assert "2 subject(s) are waiting" in text, text
    assert "withheld" in said and "none booked as asked" in said, said
    assert pm.asked_before(workdir) == {}, "a withheld round booked an id"
    assert pm.rounds_fired(workdir) == 0, "a withheld round was charged"

    # ...and nothing is rejected: the last round of the dump asks about them.
    text, said = review(pack_dir, workdir, 2, final=True)
    block = pm.parse_review(text)
    assert len(block) == 1 and sorted(block[0]["subject_ids"]) == ids, block
    # N17: the header claims only the checkpoint the dump starts itself.
    assert "last checkpoint this dump starts on its own" in text, text
    assert "FIRED" in said, said
    assert sorted(pm.asked_before(workdir)) == ids
    log("2 new subjects under a floor of 3 wait, booked as nothing, and the "
        "guaranteed final round asks about both")


def case_the_final_page_does_not_promise_the_next_dump(tmp):
    """N17 (Release B) — WORDING ONLY. ⛔ `sns_round()` is NOT changed and
    SNS-4's "demoted, judged on the floor" clause is NOT changed; the owner
    ruled on 20260920 that a re-run MAY still ask in the same dump, against
    both the builder's and the Lead's recommendation.

    What was wrong was the SENTENCE. The final page told the owner a
    suppressed draft "is asked at the next dump's first round" because "this
    dump has no checkpoint left" — and then a re-run of `finish --go` passed
    `--final` again, SNS-4 demoted it to an ordinary round, and the engine
    asked about drafts it had just promised to the next dump.

    ⛔ The page may claim only what it controls: this is the last round the
    dump starts BY ITSELF, and a re-run here may ask again.
    """
    pack_dir, workdir, ids = four_drafts(tmp, rendered=3)
    # one tile per round, so the other three drafts fall past the ceiling and
    # take the "still askable" sentence this case is about
    registry = psub.load(pack=open_pack(pack_dir))
    registry.data.setdefault("defaults", {})["tiles_per_round"] = 1
    registry.save()
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"new_fss_floor": 1, "sns_rounds_per_dump": 1}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))

    text, _said = review(pack_dir, workdir, 1, final=True)
    assert "tile ceiling" in text, text[-800:]
    # ⛔ the claim the engine cannot keep: that the dump is FINISHED asking.
    assert "this dump has no checkpoint left" not in text, text[-800:]
    # ⛔ "asked at the next dump's first round" is NOT banned — it is still
    # true of a dump nobody re-runs, and deleting it would leave the owner not
    # knowing when the draft comes back. What it may not be is UNQUALIFIED.
    # So wherever that phrase appears, the re-run caveat must appear with it.
    for line in text.splitlines():
        if "next dump's first round" in line:
            assert "finish --go" in line and "ask again" in line, line
    # ⛔ and it still says what DOES happen — a removal is not a fix
    assert "starts on its own" in text, text[-800:]
    assert "finish --go" in text and "ask again" in text, text[-800:]
    log("the final page claims only the round the dump starts by itself")


def case_the_budget_stops_the_floor_and_never_the_last_round(tmp):
    """SNS-4's soft cap. Past the budget the engine stops interrupting ON THE
    FLOOR — it is a UX budget, so it withholds and says the budget is why. The
    last round of the dump still fires, is not charged against it, and picks up
    everything the budget held back."""
    pack_dir, workdir, ids = four_drafts(tmp, rendered=1)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"new_fss_floor": 1, "sns_rounds_per_dump": 1}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))

    first, _said = review(pack_dir, workdir, 1)
    assert len(pm.parse_review(first)) == 1, "the first round did not fire"
    assert "SNS round 1 of 1" in first, first
    assert pm.rounds_fired(workdir) == 1

    second, said = review(pack_dir, workdir, 2)
    assert pm.parse_review(second) == [], "the budget did not hold"
    assert "1 round(s) asked already" in second, second
    assert "budget for this dump is 1" in second, second
    # `waiting` is what the LAST ROUND will ask about, which is the sentence
    # this number stands beside: the one tile this round would have put on the
    # page (`rendered=1`), plus the one layer 2 shut after C1 asked it.
    #
    # ⭐ Doc 8 amendment (b), 2026-08-27. The per-question deferrals are still
    # reported separately and still excluded, and the difference is not
    # cosmetic: an engine-deferred draft comes back at the NEXT checkpoint by
    # itself, where a layer-2 draft comes back only at the last round — so it
    # is the layer-2 ones this promise is actually about. Neither is booked as
    # asked.
    assert "2 subject(s) are waiting" in second, second

    third, said = review(pack_dir, workdir, 3, final=True)
    assert len(pm.parse_review(third)) == 1, "the last round did not fire"
    assert "not charged against the budget of 1" in third, third
    assert pm.rounds_fired(workdir) == 2, "the final round was charged"
    log("round 1 asks, round 2 is withheld by the budget and says so, and the "
        "last round of the dump asks anyway")


def case_a_checkpoint_page_is_never_rewritten_with_another_round(tmp):
    """FIX8 F8-10 REPRODUCTION (C102-measured). `review --checkpoint 2` run
    again while memory-review_C2.md exists wrote the NEXT round's tiles under
    the same name, so an answer typed for one round joined different drafts.
    Refused now, nothing written, and the refusal says to move the old page
    OUT of the work dir (a rename inside it is still globbed)."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=1)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"new_fss_floor": 1, "sns_rounds_per_dump": 4}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))

    first, _said = review(pack_dir, workdir, 2)
    asked = [b["subject_ids"] for b in pm.parse_review(first)]
    assert asked, "round 2 did not fire"
    page = workdir / "memory-review_C2.md"
    try:
        review(pack_dir, workdir, 2)
    except SystemExit as stop:
        said = str(stop.code)
    else:
        raise AssertionError("a second round was written over "
                             f"{page.name}: {[b['subject_ids'] for b in pm.parse_review(page.read_text())]}")
    assert page.read_text() == first, "the refused run changed the page"
    assert "memory-review_C2.md" in said and "out of the work dir" in said, said
    assert "rename" in said, said

    # Moved out, the same checkpoint number writes again.
    page.rename(tmp / "archived-C2.md")
    again, _said = review(pack_dir, workdir, 2)
    assert pm.parse_review(again), "the moved-out page did not free the name"
    log(f"C2 held {asked}; a second round under that name is refused")


def case_an_exact_repeat_of_a_checkpoint_page_is_allowed(tmp):
    """GUARD (F8-10). A re-run that puts the same tiles on the page is not a
    different round: a withheld checkpoint run twice writes twice."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=1)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"new_fss_floor": 99, "sns_rounds_per_dump": 4}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))
    first, _said = review(pack_dir, workdir, 1)
    second, _said = review(pack_dir, workdir, 1)
    assert pm.parse_review(first) == pm.parse_review(second) == [], second


def case_the_last_round_asks_what_layer_two_shut(tmp):
    """⛔ MEASURED 20260827, Tier 3 round 1 defect D7 — doc 8 amendment (b),
    signed the same evening.

    C2's header read *0 subject(s) are waiting, none of them counted as asked
    — the last round of the dump asks about them*, and its own suppression
    block twelve lines below listed seven ids as *asked at C1, no new
    evidence*. Both cannot be true: the dump was fully processed, so `no new
    evidence` is a condition that could never be met again, and C2, C3, C4 and
    C5 were identical pages carrying no question at all. The guaranteed final
    round fired into an empty page, and seven drafts the owner had a complete
    answer for were unaskable for the life of that work dir.

    So layer 2 comes down on the checkpoint that ENDS the dump — once, on the
    same predicate that demotes a second `--final` — and the number beside the
    promise counts the drafts the promise is about.

    ⛔ ONCE per dump, asserted here and not only in
    `case_the_guaranteed_round_asks_once_per_dump_not_once_per_run`: a bar
    that came down on every `finish --go` re-run would re-ask a settled
    question for as long as the operator kept running the conductor."""
    pack_dir, workdir, ids = four_drafts(tmp, rendered=4)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"new_fss_floor": 1, "sns_rounds_per_dump": 4}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))

    first, _said = review(pack_dir, workdir, 1)
    assert len(pm.parse_review(first)[0]["subject_ids"]) == 4, \
        "C1 asked nothing"

    # ---- the state D7 measured: nothing new, so nothing is asked -----------
    second, _said = review(pack_dir, workdir, 2)
    assert pm.parse_review(second) == [], "a round fired with no new evidence"
    for subject_id in ids:
        assert f"{subject_id}: asked at C1, no new evidence" in second, second
    # ...and the promise is now beside a number that counts the drafts it is
    # about. It read `0 subject(s) are waiting` on the measured run.
    assert "4 subject(s) are waiting" in second, second
    assert "the last round of the dump asks about them" in second, second

    # ---- and the last round keeps it ---------------------------------------
    third, said = review(pack_dir, workdir, 3, final=True)
    block = pm.parse_review(third)
    assert len(block) == 1, "the last round of the dump asked nothing"
    asked = set(block[0]["subject_ids"])
    assert asked == set(ids), (asked, ids)
    assert "not charged against the budget" in third, third
    assert "FIRED" in said, said

    # ⛔ Once per DUMP. `finish --go` is re-runnable and passes `--final` every
    # time, so the second one is demoted and layer 2 is back up with it.
    fourth, _said = review(pack_dir, workdir, 4, final=True)
    assert pm.parse_review(fourth) == [], \
        "a re-run of the conductor re-asked a question the last round closed"
    assert "no new evidence" in fourth, fourth
    log("layer 2 comes down on the checkpoint that ends the dump — once — and "
        "the four drafts it shut are asked one last time")


def case_the_header_counts_only_what_the_owner_confirmed(tmp):
    """The review header's `memory age` line. `not is_draft` is not the same
    test as `human-confirmed`: three statuses sit outside the draft whitelist
    without anybody having confirmed anything, so the header told the owner
    their memory held subjects they had refused."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    registry = psub.load(pack=open_pack(pack_dir))
    kept = registry.create_subject(name="Name-One", who="friend",
                                   kind="person", active=["2029-01", None])
    kept.record["status"] = psub.STATUS_CONFIRMED
    for status in (psub.STATUS_REJECTED, psub.STATUS_SUPERSEDED,
                   psub.STATUS_ABSORBED):
        registry.create_subject(kind="person").record["status"] = status
    registry.save()

    text, _said = review(pack_dir, workdir, 1)
    rmsg = photo_profile.review_messages(open_pack(pack_dir).profile)
    assert rmsg["review_age_line"].format(confirmed=1, drafts=1) in text, text
    log("one confirmed subject beside a rejected, a superseded and an "
        "absorbed one reads as 1, not 4")


# ============================================= SNS-15: the post-confirm =====

def case_the_sweep_absorbs_the_drafts_the_answer_explained(tmp):
    """SNS-15. `confirmed_match()` scores INCOMING clusters only, so the other
    draft records of the animal just named used to come back at every later
    checkpoint — each one now colliding with the name that was typed.

    What absorption may write is the whole decision: no name, no exemplar, no
    timeline. It declines to ask a question whose answer the owner gave, which
    is F14's suppression argument exactly, and that is what makes it cheap to
    reverse."""
    pack_dir, workdir, ids = two_lookalike_drafts(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    # ⚠️ Its OWN parameter. `confirmed_suppress_tau` is left at its default
    # here on purpose: if the sweep read that one instead, this fixture would
    # absorb nothing and the case would fail.
    registry.data.setdefault("defaults", {})["sweep_absorb_tau"] = 0.80
    registry.save()

    before = {i: list(psub.load(pack=open_pack(pack_dir)).get(i)
                      .record["active"]) for i in ids}
    named, rc = answer_the_question(pack_dir, workdir, name="Name-Two")
    assert rc == 0
    other = [i for i in ids if i != named][0]
    after = psub.load(pack=open_pack(pack_dir))
    swept = after.get(other)
    assert swept.status == psub.STATUS_ABSORBED, swept.record
    assert swept.record["absorbed_by"] == named, swept.record
    assert swept.record["absorbed_at_score"] >= 0.80, swept.record
    assert swept.name is None and swept.exemplars == [], swept.record
    assert swept not in after.drafts and other not in {
        d.subject_id for d in after.drafts}
    winner = after.get(named)
    assert [row["subject_id"] for row in winner.record["absorbed_drafts"]] \
        == [other]
    assert winner.record["active"] == before[named], \
        "the sweep widened a confirmed timeline on geometry"
    # ⛔ NOT settled in the memory log: absorption suppresses on the status
    # alone, so releasing the status is enough to reopen the question.
    assert other not in pm.settled_subjects(open_pack(pack_dir)), \
        "the sweep closed a question in a layer the release cannot reach"

    text, _said = review(pack_dir, workdir, 2)
    # The batch table still records that the sighting happened — history is
    # not rewritten. What must not come back is the QUESTION.
    assert all(other not in block["subject_ids"]
               for block in pm.parse_review(text)), \
        "an absorbed draft was asked about again"
    log(f"{other} absorbed into {named} at "
        f"{swept.record['absorbed_at_score']}, holding no name and no "
        "exemplar, and out of the question loop")


def case_withdrawing_the_name_releases_what_the_sweep_absorbed(tmp):
    """SNS-15's other half, and the reason the sweep may write at all. Every
    absorbed draft stopped being asked about BECAUSE of one yes; with the yes
    withdrawn the suppression has no ground left. A sweep with no way back
    would be a one-way door built out of a reversible decision."""
    pack_dir, workdir, ids = two_lookalike_drafts(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    registry.data.setdefault("defaults", {})["sweep_absorb_tau"] = 0.80
    registry.save()
    named, rc = answer_the_question(pack_dir, workdir, name="Name-Two")
    assert rc == 0
    other = [i for i in ids if i != named][0]

    registry = psub.load(pack=open_pack(pack_dir))
    result = registry.unconfirm(named, by="Test Operator", reason="wrong name")
    registry.save()
    assert result["released_absorbed"] == [other], result

    after = psub.load(pack=open_pack(pack_dir))
    released = after.get(other)
    assert released.status == psub.STATUS_DRAFT, released.record
    assert "absorbed_by" not in released.record, released.record
    assert released.record[psub.REOPENED_FLAG] is True, released.record
    assert "absorbed_drafts" not in after.get(named).record
    log(f"{other} was released by the withdrawal of {named}'s name, flagged "
        "so the work dir that already asked cannot hold it shut")


def fold_page(subject_id, ref, name, token=None, path="classify/batch-01/"
                                                     "samples/x.jpg"):
    """A HAND-WRITTEN review block whose `frames:` map names a subject that is
    already confirmed, with an armed token after the typed name.

    ⚠️ **This is the `pick:`-row grammar, and only that.** A freshly rendered
    page never maps a confirmed subject's frames — `build_questions()` tiles
    drafts, and `number_frames()` gives a re-presented frame a number and no
    `frames:` entry (SNS-5/SNS-6: giving it one would build the promotion path
    this design forbids). So a page shaped like this one is a page written
    BEFORE its subject was confirmed, which is a real thing to find in a work
    dir with history and is what these cases cover.

    ⛔ It is no longer standing in for the live round, and must not be used as
    if it were. The owner-facing door into SNS-14 is the `recheck:` row on a
    page `render_review()` actually produced —
    `case_a_rendered_round_reaches_the_fold` drives it end to end. For a whole
    build step this fixture WAS the only fold test, and a fold reachable from
    no page the engine can render looked exactly like a working feature."""
    armed = f"{name} {token}" if token else name
    return (f"**Q1 · Name it** — affects 6 file(s) / 2 batch(es)\n"
            f"> `subjects:` 1={subject_id}\n"
            f"> `frames:` 1={subject_id} {ref} {path}\n"
            f"> - `pick:` 1  `who:` pet  `name:` {armed}\n"
            "```\n")


def two_remembered_subjects(tmp):
    """One pack, two subjects the owner has each already named — the state
    SNS-14 is about, and the only state a fold is legal in.
    -> (pack dir, work dir, first id, its refs, second id)."""
    pack_dir, workdir, first, refs = two_looks_apart(tmp, promote=(0,))
    registry = psub.load(pack=open_pack(pack_dir))
    second = registry.create_subject(name="Name-Other", who="pet", kind="cat",
                                     active=["2029-04", "2029-06"])
    second.record["status"] = psub.STATUS_CONFIRMED
    second.record["files"] = 9
    registry.save()
    return pack_dir, workdir, first, refs, second.subject_id


# The sentence BOTH doors into SNS-7's ask must speak, character for
# character. Not a paraphrase of it: the two rows are typed in different
# syntaxes and each says its own way on, but the reason a collision is a
# question and not a merge is one reason, and an owner who meets it twice must
# not meet two explanations of it.
COLLISION_BODY = (
    "because whether that is the same one is yours to say and not the "
    "engine's — two animals can share a name, and answering it by matching "
    "the letters is how two subjects quietly become one. Three ways on: type "
    "a different name; or, if this really is a separate subject that happens "
    "to share the name, write ")


def case_a_rendered_round_reaches_the_fold(tmp):
    """⭐ SNS-14 END TO END, off a page `render_review()` actually wrote.

    This is the case the fold did not have. Step 7 built the verb, the
    tombstone, the alias following, the ledger precedence and four refusals,
    and every one of them was reachable only from `fold_page()` — a `pick:`
    block naming a confirmed subject's frames, which no live round renders.
    The feature was complete and unreachable, which reads exactly like a
    feature that works.

    So nothing here is hand-written. `review` renders the round, the answer is
    typed into the blank on the `recheck:` row it rendered, and `confirm` reads
    the same file back. If the door closes again, this fails."""
    pack_dir, workdir, first, refs, second = two_remembered_subjects(tmp)
    before = psub.load(pack=open_pack(pack_dir)).get_literal(first)
    held_refs = [e["vec_ref"] for e in before.exemplars]
    assert before.name == "Name-Two" and first < second, (first, second)

    path = review_text(pack_dir, workdir, checkpoint=3)
    # ⛔ Untouched, the rendered page is not an answer — including the hint,
    # which now spells `same` and `distinct` out loud. Comments are stripped
    # before the row is read, and this is what proves it.
    assert pm.parse_representations(path.read_text()) == [], \
        pm.parse_representations(path.read_text())
    path.write_text(fill_recheck(path.read_text(), first,
                                 f"Name-Other {pm.SAME_TOKEN}"))

    # the dry run predicts the fold and writes nothing
    snapshot = open_pack(pack_dir).snapshot()["id"]
    rc, said = confirm(pack_dir, workdir, checkpoint=3, go=False)
    assert rc == 0, said
    assert "would be folded" in said, said
    assert open_pack(pack_dir).snapshot()["id"] == snapshot, \
        "a dry run moved the pack"
    assert psub.load(pack=open_pack(pack_dir)).get_literal(second).status \
        == psub.STATUS_CONFIRMED, "a dry run folded"

    rc, said = confirm(pack_dir, workdir, checkpoint=3, go=True)
    assert rc == 0, said

    after = psub.load(pack=open_pack(pack_dir))
    assert after.get_literal(second).status == psub.STATUS_MERGED_INTO, said
    assert after.get_literal(second).record["merged_into"] == first
    assert after.get_literal(second).name is None, "the alias kept a name"
    assert after.get(second).subject_id == first, "the alias resolves nowhere"
    assert after.get_literal(first).name == "Name-Other", \
        after.get_literal(first).record
    # BOTH names the pack ever held resolve to the winner — N-10a across the
    # fold, which is what keeps folders already on disk findable.
    ledger = after.rename_ledger()
    assert ledger["Name-Two"] == first and ledger["Name-Other"] == first, ledger
    assert "keep those names on disk" in said, said
    assert "| merged |" in log_text(open_pack(pack_dir))

    # ⛔ A `recheck:` row promotes ZERO exemplars, on every branch. The winner
    # holds what the two records already held and not one look more: a
    # re-presentation is a glance, and SNS-6 promotes only picked frames.
    assert [e["vec_ref"] for e in after.get_literal(first).exemplars] \
        == held_refs, "the fold promoted a frame off a re-presentation"
    # ...and the rename never books the id into layer 2. `asked_before()` reads
    # `subjects:` lines; a re-presented id lands on none, or it would suppress
    # the draft question it is not.
    assert first not in pm.asked_before(workdir), pm.asked_before(workdir)

    entities = json.loads((pack_dir / pm.ENTITIES_NAME).read_text())
    records = {r["subject_id"]: r for b in ("people", "pets")
               for r in entities.get(b) or []}
    assert second not in records, ("the twin still carries the alias", records)
    assert records[first]["name"] == "Name-Other", records[first]
    log(f"a rendered round folded {second} into {first}; the door SNS-14 "
        "specifies is open")


def case_a_name_on_a_recheck_row_renames_a_remembered_subject(tmp):
    """The plain case, and the one that has to stay cheap: the name is wrong,
    the owner types the right one on the row the round already showed them.

    ⛔ Three things it must NOT do. It must not promote an exemplar — a rename
    is not new evidence (SNS-5/SNS-6). It must not book the id into layer 2 —
    `parse_representations()` is a separate parse from `parse_review()` exactly
    so a re-presented id never reaches `asked_before()`. And it must not leave
    the entities twin asserting the old name, because `--sync` cannot repair
    that: its loop only adds and updates."""
    pack_dir, workdir, subject_id, refs = two_looks_apart(tmp, promote=(0,))
    before = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    held_refs = [e["vec_ref"] for e in before.exemplars]
    booked = dict(pm.asked_before(workdir))

    # a blank row still writes nothing — the property every branch added here
    # has to leave standing
    path = review_text(pack_dir, workdir, checkpoint=3)
    snapshot = open_pack(pack_dir).snapshot()["id"]
    rc, said = confirm(pack_dir, workdir, checkpoint=3, go=True)
    assert rc == 0, said
    assert open_pack(pack_dir).snapshot()["id"] == snapshot, \
        "an untouched round wrote"

    path.write_text(fill_recheck(path.read_text(), subject_id, "Name-Corrected"))
    rc, said = confirm(pack_dir, workdir, checkpoint=3, go=False)
    assert rc == 0, said
    assert "renamed from" in said and "Name-Corrected" in said, said
    assert open_pack(pack_dir).snapshot()["id"] == snapshot, \
        "a dry run moved the pack"
    assert psub.load(pack=open_pack(pack_dir)).get(subject_id).name \
        == "Name-Two", "a dry run renamed"

    rc, said = confirm(pack_dir, workdir, checkpoint=3, go=True)
    assert rc == 0, said
    after = psub.load(pack=open_pack(pack_dir))
    renamed = after.get(subject_id)
    assert renamed.name == "Name-Corrected", renamed.record
    assert renamed.status == psub.STATUS_CONFIRMED, renamed.record
    assert "Name-Two" in renamed.previous_names, renamed.record
    assert after.rename_ledger()["Name-Two"] == subject_id, \
        after.rename_ledger()
    assert [e["vec_ref"] for e in renamed.exemplars] == held_refs, \
        "a rename promoted an exemplar"
    assert dict(pm.asked_before(workdir)) == booked, \
        "a renamed id was booked into layer 2"

    entities = json.loads((pack_dir / pm.ENTITIES_NAME).read_text())
    twin = {r["subject_id"]: r for b in ("people", "pets")
            for r in entities.get(b) or []}
    assert twin[subject_id]["name"] == "Name-Corrected", twin[subject_id]

    # ...and typing the name it now holds says exactly what a blank row says.
    # Not a change and not a refusal: nothing about it was wrong.
    snapshot = open_pack(pack_dir).snapshot()["id"]
    again = review_text(pack_dir, workdir, checkpoint=4)
    again.write_text(fill_recheck(again.read_text(), subject_id,
                                  "Name-Corrected"))
    rc, said = confirm(pack_dir, workdir, checkpoint=4, go=True)
    assert rc == 0, said
    assert "0 change(s)" in said, said
    assert open_pack(pack_dir).snapshot()["id"] == snapshot, \
        "re-typing the same name wrote"
    log(f"{subject_id} renamed from the round itself; nothing promoted, "
        "nothing booked, the twin followed")


def case_a_recheck_collision_asks_in_the_same_words_as_a_pick_row(tmp):
    """SNS-7 has two doors now, and it must have ONE set of words.

    The owner's mistake is the same mistake — a name typed that the pack
    already holds — so the paragraph explaining why the engine will not decide
    it is asserted character for character across both rows. What differs is
    the syntax each answer is typed in, and it has to: a `recheck:` row told to
    answer on a `name:` row is being sent to a row that is not on its page."""
    pack_dir, workdir, first, refs, second = two_remembered_subjects(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")

    path = review_text(pack_dir, workdir, checkpoint=3)
    path.write_text(fill_recheck(path.read_text(), first, "Name-Other"))
    snapshot = open_pack(pack_dir).snapshot()["id"]
    rc, recheck_said = confirm(pack_dir, workdir, checkpoint=3, go=True)
    assert rc == 1, recheck_said
    assert COLLISION_BODY in recheck_said, recheck_said
    assert second in recheck_said and first in recheck_said, recheck_said
    assert f"{pm.RECHECK_KEY}: {first} Name-Other {pm.SAME_TOKEN}" \
        in recheck_said, "the refusal does not say how to answer HERE"
    assert open_pack(pack_dir).snapshot()["id"] == snapshot, \
        "a refused collision wrote"
    assert psub.load(pack=open_pack(pack_dir)).get_literal(first).name \
        == "Name-Two", "a refused collision renamed"

    # the same paragraph, from the `pick:` row — one helper, two doors
    page = tmp / "pick.md"
    page.write_text(fold_page(first, refs[0], "Name-Other"))
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=profile_arg, checkpoint=1,
            file=str(page), sync=False, by="Test Operator", go=True))
    pick_said = spoken.getvalue()
    assert rc == 1, pick_said
    assert COLLISION_BODY in pick_said, pick_said
    assert f"`name: Name-Other {pm.DISTINCT_TOKEN}`" in pick_said, pick_said

    # ...and `distinct` forces the slot: two remembered subjects, one name,
    # no fold. ⛔ The engine may raise the question and never answer it.
    path = review_text(pack_dir, workdir, checkpoint=4)
    path.write_text(fill_recheck(path.read_text(), first,
                                 f"Name-Other {pm.DISTINCT_TOKEN}"))
    rc, said = confirm(pack_dir, workdir, checkpoint=4, go=True)
    assert rc == 0, said
    after = psub.load(pack=open_pack(pack_dir))
    assert after.get_literal(first).name == "Name-Other"
    assert after.get_literal(second).name == "Name-Other"
    assert after.get_literal(second).status == psub.STATUS_CONFIRMED, \
        "`distinct` folded"
    assert after.get_literal(first).status == psub.STATUS_CONFIRMED
    log("one collision paragraph on both rows; `distinct` keeps two subjects "
        "under one name and folds nothing")


def case_a_recheck_row_is_one_answer(tmp):
    """Everything this row refuses, and each on its own words.

    ⛔ A name AND a gesture — one row is one answer, and a name that happens to
    contain a gesture word lands here rather than being quietly read as the
    gesture. ⛔ `same` and `distinct` together, the two opposite answers to one
    question. ⛔ An armed token with no name in front of it, and one with no
    other half to be armed against: a token that silently did nothing is
    indistinguishable from one that worked. ⛔ Two rows for one record.

    ⚠️ And the refusal a DRY RUN has to reach without writing: a rejected
    record may not be renamed, and `rename()` audits its refusals at the
    decision point into a file that sits inside the pack snapshot. That is why
    the guards are read through `rename_refusal()` — a dry run that asked the
    verb would move the pack it promised not to touch."""
    pack_dir, workdir, subject_id, refs = two_looks_apart(tmp, promote=(0,))

    def answer(checkpoint, typed):
        path = review_text(pack_dir, workdir, checkpoint=checkpoint)
        path.write_text(fill_recheck(path.read_text(), subject_id, typed))
        return confirm(pack_dir, workdir, checkpoint=checkpoint, go=True)

    rc, said = answer(3, f"Rex {pm.GESTURE_REVIVE}")
    assert rc == 1, said
    assert "one row is one answer" in said, said
    assert "'Rex'" in said and pm.GESTURE_REVIVE in said, said

    rc, said = answer(4, f"Rex {pm.SAME_TOKEN} {pm.DISTINCT_TOKEN}")
    assert rc == 1, said
    assert "opposite" in said, said

    rc, said = answer(5, pm.SAME_TOKEN)
    assert rc == 1, said
    assert "no name in front of it" in said, said

    rc, said = answer(6, f"Name-Nobody-Holds {pm.SAME_TOKEN}")
    assert rc == 1, said
    assert "no other half" in said, said

    unchanged = psub.load(pack=open_pack(pack_dir)).get(subject_id)
    assert unchanged.name == "Name-Two", unchanged.record
    assert unchanged.status == psub.STATUS_CONFIRMED, unchanged.record

    # one record, one answer per round — and the rename rows count, or which
    # of two answers survived would depend on the order they were typed in
    path = review_text(pack_dir, workdir, checkpoint=7)
    row = f"`{pm.RECHECK_KEY}:` {subject_id} ______"
    path.write_text(path.read_text().replace(
        row, f"`{pm.RECHECK_KEY}:` {subject_id} Name-A\n"
             f"> - `{pm.RECHECK_KEY}:` {subject_id} Name-B", 1))
    rc, said = confirm(pack_dir, workdir, checkpoint=7, go=True)
    assert rc == 1 and "more than one row" in said, said
    assert psub.load(pack=open_pack(pack_dir)).get(subject_id).name == "Name-A"

    # ⛔ a stale page is refused WHOLE, before any recheck row applies
    path = review_text(pack_dir, workdir, checkpoint=8)
    text = fill_recheck(path.read_text(), subject_id, "Name-Never-Written")
    path.write_text(text)
    moved = psub.load(pack=open_pack(pack_dir))
    moved.create_subject(kind="dog")
    moved.save()
    rc, said = confirm(pack_dir, workdir, checkpoint=8, go=True)
    assert rc == 1 and "NOTHING in the file was applied" in said, said
    assert psub.load(pack=open_pack(pack_dir)).get(subject_id).name == "Name-A"

    # ...and a rejected record's row refuses in the DRY RUN, without writing
    # the audit line that would move the pack
    rejected_pack, rejected_dir = k_batch_run(
        tmp, 3, pack_dir=make_pack(tmp, owner="betauser02"))
    first = review_text(rejected_pack, rejected_dir, checkpoint=1)
    rejected_id = pm.parse_review(first.read_text())[0]["subject_ids"][0]
    first.write_text(fill_skip(first.read_text(), [1]))
    rc, said = confirm(rejected_pack, rejected_dir, checkpoint=1)
    assert rc == 0, said
    second = review_text(rejected_pack, rejected_dir, checkpoint=2)
    second.write_text(fill_recheck(second.read_text(), rejected_id, "Name-X"))
    snapshot = open_pack(rejected_pack).snapshot()["id"]
    rc, said = confirm(rejected_pack, rejected_dir, checkpoint=2, go=False)
    assert rc == 1, said
    assert "may not be renamed" in said and "--revive" in said, said
    assert open_pack(rejected_pack).snapshot()["id"] == snapshot, \
        "a dry-run refusal wrote the audit log and moved the pack"
    log("a recheck row is one answer; a stale page is refused whole; a "
        "refusal a dry run predicts writes nothing")


def case_a_same_row_folds_two_remembered_subjects(tmp):
    """SNS-14 on the `pick:` grammar — a page written before its subject was
    confirmed, which is what a work dir with history holds. The owner-facing
    door is `case_a_rendered_round_reaches_the_fold`; this one keeps the older
    shape working.

    The owner types a name the pack remembers, the engine asks, and `same` is
    the answer that says *the same one*.

    The earlier id keeps the name and the exemplars; the later one stays as an
    alias so every folder and plan row already written under it still resolves
    (N-10a across the fold). ⛔ Nothing on disk is moved, and the confirm says
    so by name."""
    pack_dir, workdir, first, refs, second = two_remembered_subjects(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")
    page = tmp / "fold.md"
    page.write_text(fold_page(first, refs[0], "Name-Other",
                              token=pm.SAME_TOKEN))

    # the dry run predicts it and writes nothing
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=profile_arg, checkpoint=1,
            file=str(page), sync=False, by="Test Operator", go=False))
    said = spoken.getvalue()
    assert rc == 0, said
    assert "would be folded" in said, said
    assert psub.load(pack=open_pack(pack_dir)).get_literal(second).status \
        == psub.STATUS_CONFIRMED, "a dry run folded"

    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        rc = pm.cmd_confirm(argparse.Namespace(
            workdir=str(workdir), profile=profile_arg, checkpoint=1,
            file=str(page), sync=False, by="Test Operator", go=True))
    said = spoken.getvalue()
    assert rc == 0, said

    after = psub.load(pack=open_pack(pack_dir))
    winner, loser = sorted([first, second])
    assert after.get_literal(loser).status == psub.STATUS_MERGED_INTO, said
    assert after.get_literal(loser).record["merged_into"] == winner
    assert after.get_literal(loser).name is None, "the alias kept a name"
    assert after.get(loser).subject_id == winner, "the alias resolves nowhere"
    assert after.get_literal(winner).name == "Name-Other", \
        after.get_literal(winner).record
    assert after.rename_ledger()["Name-Two"] == winner, after.rename_ledger()
    # the advisory the SPEC asks for: it names the folders and moves nothing
    assert "keep those names on disk" in said, said
    assert "Name-Two" in said, said
    assert "| merged |" in log_text(open_pack(pack_dir)), \
        log_text(open_pack(pack_dir))[-500:]
    # ⛔ `merged` is not one of `settled_subjects()`'s maturity tokens, so the
    # line records the fold without closing anything in the LOG layer — which
    # is what keeps the winner's own withdrawal reachable afterwards.
    assert "merged" not in pm.settled_subjects(open_pack(pack_dir)).values()

    # ⚠️ The entities twin follows, or the file a human reads asserts two
    # identities where the registry holds one — and `--sync` cannot repair it,
    # because its loop only ever adds and updates.
    entities = json.loads((pack_dir / pm.ENTITIES_NAME).read_text())
    records = {r["subject_id"]: r for b in ("people", "pets")
               for r in entities.get(b) or []}
    assert loser not in records, ("the twin still carries the alias", records)
    assert records[winner]["name"] == "Name-Other", records[winner]
    log(f"{loser} folded into {winner}; the ledger still resolves both names")


def case_a_same_row_needs_two_subjects_the_owner_already_named(tmp):
    """The refusals around the fold, each on its own words.

    ⛔ `same` + `distinct` — the two opposite answers to one question, so
    neither is guessed. ⛔ `same` with nothing to be the same as — an armed
    token that silently did nothing is indistinguishable from one that
    worked."""
    pack_dir, workdir, first, refs, second = two_remembered_subjects(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")

    def confirm_page(text):
        page = tmp / "row.md"
        page.write_text(text)
        spoken = io.StringIO()
        with contextlib.redirect_stdout(spoken):
            rc = pm.cmd_confirm(argparse.Namespace(
                workdir=str(workdir), profile=profile_arg, checkpoint=1,
                file=str(page), sync=False, by="Test Operator", go=True))
        return rc, spoken.getvalue()

    rc, said = confirm_page(fold_page(
        first, refs[0], "Name-Other",
        token=f"{pm.SAME_TOKEN} {pm.DISTINCT_TOKEN}"))
    assert rc == 1, said
    assert pm.SAME_TOKEN in said and pm.DISTINCT_TOKEN in said, said
    assert "opposite" in said, said

    rc, said = confirm_page(fold_page(first, refs[0], "Name-Nobody-Holds",
                                      token=pm.SAME_TOKEN))
    assert rc == 1, said
    assert "no other half" in said, said

    after = psub.load(pack=open_pack(pack_dir))
    assert after.get_literal(second).status == psub.STATUS_CONFIRMED
    assert after.get_literal(first).name == "Name-Two", "a refused row wrote"

    # ⚠️ A DRAFT member is no longer one of them. It used to be the third
    # refusal here — *"which nobody has named yet"* — and it was refusing the
    # exact row the collision message tells the owner to type. That direction
    # is SNS-16 (step 9, item 3) and it is a PROMOTION, not a fold; the cases
    # that assert it live with the other SNS-16 cases.
    log("same+distinct and an unheld name are each refused by name")


def case_a_folded_id_still_names_the_winner_in_the_plan(tmp):
    """SNS-14's reason for putting alias following in `get()` at all:
    `photo_plan.visual_columns()` holds `subject_id`s off see-labels written
    before the fold, and it must print the name the subject holds NOW — with no
    change of its own, and with no `draft:` marker, because what it resolves to
    is a confirmed record."""
    import photo_plan

    pack_dir, workdir, first, refs, second = two_remembered_subjects(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    result = registry.fold_subjects([first, second], name="Name-Other",
                                    who="pet", by="Test Operator")
    registry.save()
    loser = result["folded"][0]["subject_id"]

    out = workdir / "classify" / "batch-01"
    out.mkdir(parents=True, exist_ok=True)
    (out / "see-labels.json").write_text(json.dumps({"batch": 1, "labels": [
        {"path": "/raw/IMG_0001.HEIC", "label": "Cat",
         "provenance": "viewed-image:", "sample": "x.jpg",
         "subject": {"subject_id": loser, "subject_kind": "cat"},
         "subject_provenance": "viewed-image:"}]}, ensure_ascii=False))

    pack = open_pack(pack_dir)
    columns = photo_plan.visual_columns(workdir, [1], pack.profile, pack)
    cell = columns["/raw/IMG_0001.HEIC"]
    assert cell["who"] == "Name-Other", cell
    assert cell["who_provenance"] == "viewed-image:", \
        ("a folded id rendered as a draft", cell)
    log(f"a see-label naming {loser} prints the winner's name with no draft "
        "marker")


def case_the_remembered_line_states_the_ungated_share(tmp):
    """A19 item 3, on the page the owner actually reads.

    The header used to present one total — the weight of evidence behind a
    name — that silently included sightings no timeline gate ever approved.
    Measured on one owner dump, 53 of a subject's 81 files were ungated and
    the page said nothing.

    ⛔ APPENDED, never substituted. `{files}` still means what it always
    meant, so no pack needs re-translating and a subject with none of these
    renders the line it rendered before — asserted as its own half below,
    because a change that quietly moved the existing number would be the same
    class of defect this card is about."""
    pack_dir, workdir, subject_id, refs = two_looks_apart(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    subject = registry.get_literal(subject_id)
    subject.record["files"] = 20
    subject.record["files_ungated"] = 12
    registry.save()

    rmsg = photo_profile.REVIEW_VOCAB["en"]
    text = review_text(pack_dir, workdir,
                       checkpoint=1).read_text(encoding="utf-8")
    assert registry.display_files_ungated(subject) == 12
    assert rmsg["review_remembered_ungated"].format(files=12) in text, \
        ("the ungated share is not on the page", text[-1200:])
    # The total is untouched: still every file, ungated ones included.
    assert subject.record["files"] == 20


def case_a_subject_with_no_ungated_sightings_renders_the_old_line(tmp):
    """The other half of A19 item 3, and the one that keeps the fixtures
    honest: a pack that has never taken an ungated sighting must render
    exactly the line it rendered before the card."""
    pack_dir, workdir, subject_id, refs = two_looks_apart(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    subject = registry.get_literal(subject_id)
    subject.record["files"] = 20
    registry.save()

    rmsg = photo_profile.REVIEW_VOCAB["en"]
    text = review_text(pack_dir, workdir,
                       checkpoint=1).read_text(encoding="utf-8")
    assert registry.display_files_ungated(subject) == 0
    # ⚠️ NOT `.split("{")[0]` — that is " — ", which the page uses elsewhere.
    # A marker loose enough to match other text proves nothing.
    marker = rmsg["review_remembered_ungated"].split("}")[-1].strip()
    assert marker and marker not in text, \
        "an ungated clause appeared with nothing to report"


def case_the_remembered_line_shows_what_the_sweep_absorbed(tmp):
    """SNS-15's read-time sum, on the page the owner actually reads.

    ✅ The owner's decision, 2026-08-19 — the counts aggregate at DISPLAY
    time and never in
    storage, so `review_remembered_line` takes the number it always took and
    no vocabulary key moves. What changes is where the number comes from."""
    pack_dir, workdir, subject_id, refs = two_looks_apart(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    subject = registry.get_literal(subject_id)
    subject.record["files"] = 20
    absorbed = registry.create_subject(kind="cat")
    absorbed.record.update({"status": psub.STATUS_ABSORBED, "files": 8,
                            "absorbed_by": subject_id,
                            "absorbed_at_score": 0.91})
    subject.record["absorbed_drafts"] = [
        {"subject_id": absorbed.subject_id, "files": 8, "score": 0.91,
         "at": "2029-05-01"}]
    registry.save()

    rmsg = photo_profile.REVIEW_VOCAB["en"]
    text = review_text(pack_dir, workdir,
                       checkpoint=1).read_text(encoding="utf-8")
    line = rmsg["review_remembered_line"].format(subject="", files=28,
                                                 batches=2).lstrip("* ")
    assert line.split("·")[-1].strip() in text, \
        ("the remembered line did not show the summed count", text[-1200:])
    assert registry.display_files(subject) == 28
    assert subject.record["files"] == 20, "the sum reached storage"

    # ...and the release takes it back apart, in storage terms the page reads
    registry.release_absorbed(subject_id)
    assert registry.display_files(subject) == 20
    assert "absorbed_drafts" not in subject.record
    log("20 + 8 renders 28 on the page, and nothing stored says 28")


def case_the_guaranteed_round_asks_once_per_dump_not_once_per_run(tmp):
    """SNS-4's guaranteed round, against the fact that `finish --go` is
    re-runnable.

    A plan whose batches are already done is skipped, so re-running `finish` on
    a dump is a normal, safe thing to do — and the conductor passes `--final`
    every time. Each run therefore said *the dump is over* about the same dump.
    Fired unconditionally each time, three re-runs would spend three of the
    four rounds in `{sns_rounds_per_dump}` and every later floor-triggered
    round would be withheld against a budget the owner never saw spent.

    So the second `--final` is DEMOTED to an ordinary checkpoint and judged on
    the floor and the budget like any other. ⛔ The demotion is a cadence
    decision and is asserted here, in `sns_round()`'s own suite, because that
    is where it lives — the conductor only knows that the dump ended."""
    pack_dir, workdir, ids = four_drafts(tmp, rendered=3)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    # A floor nothing can reach, so the ONLY thing that can fire a round here
    # is `--final`. Any round after the first is the bug this case is about.
    profile["memory"] = {"new_fss_floor": 99, "sns_rounds_per_dump": 4}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))

    first, said = review(pack_dir, workdir, 1, final=True)
    assert len(pm.parse_review(first)) == 1, "the guaranteed round did not fire"
    assert pm.FINAL_MARKER in first, "the page carries no machine-readable trace"
    assert "FIRED" in said, said
    assert pm.rounds_fired(workdir) == 1

    # The same dump, over for the second time.
    second, said = review(pack_dir, workdir, 2, final=True)
    assert pm.parse_review(second) == [], \
        "a re-run of `finish --go` fired a second guaranteed round"
    assert pm.FINAL_MARKER not in second, "a demoted round left a final trace"
    assert pm.rounds_fired(workdir) == 1, \
        "the re-run charged a round against the dump's budget"
    assert "--final" in said and "already asked" in said, said
    # ...and the demotion is a DEMOTION, not a silencing: the floor is what
    # withheld it, which is what any other checkpoint would have said.
    assert pm.sns_round(workdir, [], {}, psub.Registry(), profile,
                        final=True)["why"] == "floor"

    # ⛔ The owner's page is not where this is said. Nothing about how many
    # times a conductor ran belongs in front of them, and the marker is an
    # HTML comment so it never renders either.
    assert "--final" not in second, second
    log("the guaranteed round asks once per DUMP — a re-run of `finish --go` "
        "is demoted to an ordinary checkpoint and charges nothing")


def case_a_preview_decides_as_the_round_does_and_writes_nothing(tmp):
    """⭐ REPRODUCTION (M1, UAT01-9 F11). ⛔ FAILS on 4739665 (no --preview):
    a `finish` dry run could not say that `--go` would put a new page to the
    owner. `review --final --preview` decides as `review --final` does —
    first run asks, a re-run is demoted and asks nothing — and writes no page
    and charges no round either time."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=3)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"new_fss_floor": 99, "sns_rounds_per_dump": 4}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))

    def preview(checkpoint):
        spoken = io.StringIO()
        with contextlib.redirect_stdout(spoken):
            rc = pm.cmd_review(argparse.Namespace(
                workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
                checkpoint=checkpoint, out=None, final=True, preview=True))
        return rc, spoken.getvalue()

    rc1, said1 = preview(1)
    assert rc1 == pm.PRE_PLAN_ROUND_FIRED_RC, said1
    assert "would ask the owner about" in said1, said1
    assert not (workdir / "memory-review_C1.md").exists(), "a preview wrote a page"
    assert pm.rounds_fired(workdir) == 0
    first, _said = review(pack_dir, workdir, 1, final=True)
    assert len(pm.parse_review(first)) == 1, "the round the preview promised did not ask"

    rc2, said2 = preview(2)
    assert rc2 == 0 and "would ask the owner nothing" in said2, said2
    assert not (workdir / "memory-review_C2.md").exists(), "a preview wrote a page"
    second, _said = review(pack_dir, workdir, 2, final=True)
    assert pm.parse_review(second) == [], "the re-run asked what the preview said it would not"
    log("a preview decides as the round does and writes nothing")


def case_the_guaranteed_final_round_has_a_caller(tmp):
    """SNS-4's last clause, which had no caller until this step: *the last
    round fires at the end of the dump, whether or not the floor was met*.

    The flag, the decision and the printed reason all shipped in step 6 and
    nothing in the repo invoked `review`, so the guaranteed round was
    REACHABLE and not GUARANTEED. `finish` is where a dump ends, so that is
    where the one fact crosses — and it crosses as a fact, never as a decision:
    ⛔ no floor, no cap and no round counting may appear in the conductor.

    Asserted on the conductor's source, because the alternative is a fixture
    that copies a whole dump to prove one subprocess argument."""
    import inspect
    import photo_run

    source = inspect.getsource(photo_run.cmd_finish)
    assert '"--final"' in source, "nothing in `finish` asks for the last round"
    assert '"photo_memory.py", "review"' in source, \
        "the round is not invoked through the stage-script helper"
    # ⛔ the cadence stays in `sns_round()`: the conductor cannot see the
    # registry, so a floor or a budget here would be decided on evidence it
    # does not hold
    conductor = inspect.getsource(photo_run)
    assert "import photo_memory" not in conductor, \
        "the conductor imports the module that holds the decision"
    for leaked in ("new_fss_floor", "sns_rounds_per_dump"):
        assert leaked not in conductor, leaked
    # `--go` only: a dry run writing a real question block would book a round
    # the owner never saw, because `rounds_fired()` counts pages with a block
    final = source.index('"--final"')
    guard = source.rindex("if args.go:", 0, final)
    assert source.index("photo_memory.py", guard) < final, source[guard:final]
    # and a pack-less dump is a no-op, not a failure — `fresh_owner_smoke`
    # runs an owner with no subjects at all
    assert "pack.dir is None" in source, \
        "`finish` gained a hard dependency on an owner pack"
    assert "flagged.append" not in source[guard:], \
        "a missing review page changed what `finish` exits with"

    # the decision itself is unchanged and still not charged
    state = pm.sns_round(tmp, [], {}, psub.Registry(), {}, final=True)
    assert state["fire"] is True and state["why"] == "final", state
    assert state["rounds"] == 0 and state["round"] == 1, state
    log("`finish --go` passes one fact — this is the last checkpoint — and no "
        "decision")


# ======================================================= step 9, item 1 ====
#
# A REFUSED row is not a DEFERRED one. Doc 4 v4's fourth outcome, signed
# 2026-08-20 off the first owner-answered round: *a refused row leaves its
# drafts exactly as they were before the page was rendered — not booked into
# layer 2, and re-asked at the next round. A refusal is the engine's failure,
# never the owner's silence.*

def two_drafts_one_question(tmp, owner="betauser00", cadence=CADENCE_OFF):
    """Two drafts of one kind, both rendered by one question.
    -> (pack dir, work dir, [id by descending files]).

    Small on purpose: with exactly two tiles on the page, "one row applied and
    one row refused" is the whole page, so what the next checkpoint asks about
    is a statement about the refusal and not about a tail of drafts that were
    never in front of anybody."""
    pack_dir = make_pack(tmp, owner=owner, cadence=cadence)
    pack = open_pack(pack_dir)
    workdir = tmp / f"dump-{owner}"
    write_batches(workdir, 2)
    for batch, (vec, members) in enumerate(((basis(0), 6), (basis(4), 5)), 1):
        report, index, samples = batch_fixture(workdir, batch, [(vec, members)],
                                               month=f"2029-0{batch}")
        apply_and_memorize(workdir, pack, report, index, samples,
                           {report["selected"][0]["path"]:
                            {"label": "Cat", "subject_kind": "cat"}})
    registry = psub.load(pack=open_pack(pack_dir))
    ranked = sorted(registry.drafts,
                    key=lambda s: (-int(s.record.get("files", 0)),
                                   s.subject_id))
    assert len(ranked) == 2, [d.subject_id for d in ranked]
    return pack_dir, workdir, [d.subject_id for d in ranked]


def case_a_refused_row_comes_back_as_a_question(tmp):
    """⛔ MEASURED 2026-08-20, defect D. The owner answered, the engine
    refused, and the drafts on that row were booked `asked at C1` — the same
    state a tile the owner never mentioned is left in. On a closed dump their
    evidence never grows, so *"returns if its evidence grew"* means never, and
    the answer is lost.

    Three things are asserted together, and each one is a different way this
    can still be broken:

      * the refused draft is rendered again as a QUESTION, not suppressed with
        the words `asked at C1, no new evidence`;
      * the round FIRES for it under a real cadence. `sns_round()` counts a
        tile as new when it is absent from layer 2, so a fix that only moved
        the bar in `build_questions()` would render the question into a round
        that is withheld — 0 questions on the fresh page, which is the
        measured symptom verbatim;
      * ⛔ the row the owner got RIGHT is untouched. A refusal is per row, and
        a page-wide rollback would answer one mistake by discarding an answer
        that worked (FINDINGS finding 6: refusals are whole, never half
        applied)."""
    pack_dir, workdir, ranked = two_drafts_one_question(
        tmp, cadence={"new_fss_floor": 1, "sns_rounds_per_dump": 4})
    applied, refused = ranked
    profile_arg = str(pack_dir / "photo-profile.json")

    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    block = pm.parse_review(path.read_text())[0]
    assert set(block["subject_ids"]) == set(ranked), block["subject_ids"]

    # One page, two rows: tile 1 answered properly, tile 2 answered with half
    # an identity — ONB-13's refusal, and one no later step turns into a
    # success.
    text = fill_pick(path.read_text(), [1], who="pet", name="Name-Applied")
    text = fill_pick(text, [2], who="pet", name="")
    path.write_text(text)

    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=True)
    assert rc == 1, ("the half-identified row was not refused", said)
    assert "one answer" in said, said

    after = psub.load(pack=open_pack(pack_dir))
    assert after.get(applied).status == psub.STATUS_CONFIRMED, \
        ("the applied row was rolled back by the refusal beside it", said)
    assert after.get(applied).exemplars, "the applied row promoted nothing"
    assert after.get(refused).is_draft, "a refused row wrote a status"

    # layer 2 itself, read before another page is written over it: the C1
    # booking must simply not be there
    pack = open_pack(pack_dir)
    questions, suppressed, _over, _held = pm.build_questions(
        psub.load(pack=pack), workdir, pack, pack.profile,
        photo_profile.review_messages(pack.profile))
    stale = [why for sid, why in suppressed
             if sid == refused and "asked at C" in why]
    assert not stale, ("the refused draft is held shut by layer 2: " +
                       "; ".join(stale))
    assert refused in {i for q in questions for i in q["subject_ids"]}, \
        suppressed
    assert refused not in pm.asked_before(workdir), pm.asked_before(workdir)
    assert applied in pm.asked_before(workdir), \
        "the applied row's booking was thrown away with the refused one"

    # C2 — the fresh page the refusal tells the owner to run
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=2, out=None))
    second = (workdir / "memory-review_C2.md").read_text()
    blocks = pm.parse_review(second)
    asked = {i for b in blocks for i in b["subject_ids"]}
    assert asked, ("the fresh page carries 0 questions — the round was "
                   "withheld because a refused draft is not counted as "
                   "waiting", second)
    assert refused in asked, ("the refused row's draft was not asked again",
                              asked)
    assert applied not in asked, ("the applied row came back", asked)
    log(f"{refused} was refused at C1 and is asked again at C2; {applied} "
        "stayed confirmed")


def a_split_and_a_share(tmp, owner="betauser00"):
    """One draft photographed three times from three angles, and a second
    draft beside it in every batch. -> (pack dir, work dir).

    ⭐ The state behind the measured dry-run divergence: it takes a draft with
    enough frames to be picked apart by two rows, and a NEIGHBOUR for one of
    those rows to also name."""
    pack_dir = make_pack(tmp, owner=owner)
    pack = open_pack(pack_dir)
    workdir = tmp / f"dump-{owner}"
    write_batches(workdir, 3)
    for batch, vec in enumerate((basis(0),
                                 unit(basis(0) + 0.30 * basis(1)),
                                 unit(basis(0) + 0.30 * basis(2))), 1):
        report, index, samples = batch_fixture(
            workdir, batch, [(vec, 4), (basis(20), 2)], month=f"2029-0{batch}")
        apply_and_memorize(
            workdir, pack, report, index, samples,
            {report["selected"][0]["path"]: {"label": "Cat",
                                             "subject_kind": "cat"},
             report["selected"][1]["path"]: {"label": "Cat",
                                             "subject_kind": "cat"}})
    registry = psub.load(pack=open_pack(pack_dir))
    assert len(registry.drafts) == 2, [d.subject_id for d in registry.drafts]
    return pack_dir, workdir


def split_and_share_page(pack_dir, workdir, checkpoint=1):
    """Render a round and type the answer that splits one draft and shares a
    name across another. -> (the page, the split draft, the shared draft)."""
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=checkpoint, out=None))
    path = workdir / f"memory-review_C{checkpoint}.md"
    block = pm.parse_review(path.read_text())[0]
    by_subject = block["frames_by_subject"]
    split = max(by_subject, key=lambda s: (len(by_subject[s]), s))
    other = [s for s in by_subject if s != split][0]
    assert len(by_subject[split]) >= 2, by_subject
    # row 1 — one of the split draft's frames AND the whole of the other
    # draft: a shared name. row 2 — the rest of the split draft: a split.
    first = ",".join(str(n) for n in
                     [by_subject[split][0]] + list(by_subject[other]))
    rest = ",".join(str(n) for n in by_subject[split][1:])
    text = fill_pick(path.read_text(), None, frames=first, name="Name-Shared")
    text = fill_pick(text, None, frames=rest, name="Name-Split")
    path.write_text(text)
    return path, split, other


def mixed_groups(pack_dir):
    """U2-6 — the row a page can no longer send (it is read as two rows
    first), built as storage sees it: one row of the split draft that also
    names the other draft, and one row of the rest. -> (registry, split id,
    groups)."""
    reg = psub.load(pack=open_pack(pack_dir))
    split = max(reg.drafts, key=lambda s: (len(s.record.get("evidence") or []),
                                           s.subject_id))
    other = [d for d in reg.drafts if d is not split][0]
    refs = [l["vec_ref"] for e in split.record["evidence"] for l in e["looks"]]
    refs = list(dict.fromkeys(refs))
    return reg, split.subject_id, [
        {"vec_refs": refs[:1], "shared_with": [other.subject_id], "centroid": [1.0]},
        {"vec_refs": refs[1:], "shared_with": [], "centroid": [1.0]}]


def follow_stale_instruction(said, workdir, away):
    """Do what the stale-page refusal says to the page, literally: move the
    page it names out of the work dir, if it says so. -> True when it did."""
    import re as _re
    import shutil as _shutil
    found = _re.search(r"Move (\S+\.md) OUT of the work dir", said)
    if not found:
        return False
    away.mkdir(parents=True, exist_ok=True)
    _shutil.move(str(workdir / found.group(1)), str(away / found.group(1)))
    return True


def case_a_stale_page_refusal_leads_to_a_page_that_asks(tmp):
    """⭐ M7 (REPRODUCTION, UAT01-9 F4b). ⛔ FAILS on 6edab52: the refusal said
    "run `review` again … writes a fresh page you can type the same answers
    onto", and that page asked NOTHING — the stale page still booked its
    drafts as asked and, with the round budget spent, as a round. Followed
    literally, the new instruction ends on a page asking the same question,
    with a budget of ONE round already spent."""
    pack_dir, workdir = k_batch_run(tmp, 3)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["memory"] = {"sns_rounds_per_dump": 1, "new_fss_floor": 0}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile))
    page = review_text(pack_dir, workdir)
    asked = pm.parse_review(page.read_text())[0]["subject_ids"]
    reg = pack_dir / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text())
    data["subjects"].append({"subject_id": "subj-0950", "name": "Other",
                             "who": "pet", "kind": "cat",
                             "status": psub.STATUS_CONFIRMED, "exemplars": []})
    reg.write_text(json.dumps(data))
    page.write_text(fill_pick(page.read_text(), [1], name="Name-A"))
    rc, said = confirm(pack_dir, workdir)
    assert rc == 1 and "NOTHING in the file was applied" in said, said
    follow_stale_instruction(said, workdir, Path(tmp) / "set-aside")
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        pm.cmd_review(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=None, out=None))
    pages = sorted(workdir.glob("memory-review_C*.md"))
    again = [i for b in pm.parse_review(pages[-1].read_text())
             for i in b["subject_ids"]]
    assert set(asked) <= set(again), (asked, again, said[-400:], spoken.getvalue())


def case_a_refused_go_leaves_the_pinned_page_valid(tmp):
    """⛔ MEASURED 2026-08-20, the second half of defect D. A refused `--go`
    writes nothing to the registry and still moves the pack, because
    `partition_subject()` audits its refusal and `memorize-audit.jsonl` sits
    inside the directory the pack snapshot hashes. The pinned snapshot on the
    page it just refused no longer matches, so the next `confirm` refuses the
    WHOLE page before reading a row of it — and the refusal's own advice, to
    run `review` again and type the same answers, produced a page with no
    questions on it.

    ⛔ The audit line must still be WRITTEN: a refusal nobody can trace is
    worse than one that moves a hash. What changes is that provenance stops
    counting as state — the same reason `photo-memory-log.md` was excluded
    from the snapshot when it was written."""
    # ⭐ U2-6 (owner ruling 20261001): the page answer of this shape is read
    # as two rows and accepted, so the refused --go is made at storage, the
    # one place this gate still bites, and the pinned page is then confirmed.
    pack_dir, workdir = a_split_and_a_share(tmp)
    path, split, other = split_and_share_page(pack_dir, workdir)
    pinned = pm.pinned_snapshot(path.read_text())
    assert pinned, "the page pinned no snapshot"
    assert pinned == open_pack(pack_dir).snapshot()["id"]
    trail = len(psub.load(pack=open_pack(pack_dir)).audit_trail())

    reg, sid, groups = mixed_groups(pack_dir)
    try:
        reg.partition_subject(sid, groups, by="Test Operator")
        refused = None
    except ValueError as err:
        refused = str(err)
    assert refused and "both splits this subject and names" in refused, refused

    grown = psub.load(pack=open_pack(pack_dir)).audit_trail()
    assert len(grown) > trail, "the refusal left no trace in the audit log"
    assert pinned == open_pack(pack_dir).snapshot()["id"], \
        ("a refused partition moved the pack — the page it was pinned to can "
         "no longer be confirmed at all")

    # ...and the proof that matters to the owner: the same file is still
    # readable after the refusal.
    rc, again = confirm(pack_dir, workdir, checkpoint=1, go=True)
    assert "NOTHING in the file was applied" not in again, again
    assert rc == 0, again

    # ⭐ ...and doc 4 v4 on a refusal a PAGE can still reach inside
    # `partition_picks()` (measured 20261001): a split whose picked frame no
    # longer has its vector (the work dir was re-embedded after the page was
    # written). The draft on the refused rows must not stay booked as asked,
    # and it is asked again at the next checkpoint.
    import csv as _csv
    pack_dir, workdir, split, other, _b = u26_page(tmp / "booking", lambda s, o: [
        ([s[0]], "Name-A"), (s[1:], "Name-B")])
    victim = [l for e in psub.load(pack=open_pack(pack_dir)).get_literal(split)
              .record["evidence"] for l in e["looks"]][0]
    emb = Path(victim["workdir"]) / "embed" / "embeddings.csv"
    rows = list(_csv.DictReader(open(emb)))
    for row in rows:
        if row["SourceFile"] == victim["path"]:
            row["sha256"] = "0" * 64
    with open(emb, "w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=True)
    assert rc == 1 and "was picked apart by" in said, said
    assert split not in set(pm.asked_before(workdir)), \
        "the draft on the refused rows is still booked as asked"
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=2, out=None))
    asked = {i for b in pm.parse_review(
        (workdir / "memory-review_C2.md").read_text()) for i in b["subject_ids"]}
    assert split in asked, ("the refused answer's draft did not come back: "
                            f"{asked}")
    log("a refused partition audits, the page pinned before it still "
        "confirms, and a refused split's draft is asked again")

# ======================================================= step 9, item 2 ====

def spoken_counts(said, go):
    """-> (changes, refusals) as the run itself reported them.

    The dry run prints both numbers; `--go` prints the changes it wrote and
    speaks each refusal on its own `!` line. Read off the OWNER-FACING words
    on purpose — a comparison of two internal lists could agree while the two
    sentences the owner reads disagree, which is the defect."""
    import re as _re
    refused = len([line for line in said.splitlines()
                   if line.startswith("  ! ")])
    if go:
        found = _re.search(r"wrote (\d+) change\(s\)", said)
        return (int(found.group(1)) if found else 0), refused
    found = _re.search(r"dry run — (\d+) change\(s\) would be written, "
                       r"(\d+) refused", said)
    assert found, said
    return int(found.group(1)), int(found.group(2))


def case_the_dry_run_predicts_the_go_it_refuses(tmp):
    """⛔ MEASURED 2026-08-20, defect C — the most dangerous of the five.

        dry run — 21 change(s) would be written, 0 refused.
        --go    -> wrote 0 change(s), 1 refused

    A `pick:` row that both SPLITS one draft and SHARES a name across another
    is refused by `partition_subject()`, and that verb ran under `--go` only —
    so the dry run walked a different decision sequence, predicted the split it
    would never perform, and reported the twenty other writes that the refusal
    then took down with it. **The owner is told their answer is fine, and then
    it is not**, against this file's own rule that *a dry run that does not
    predict `--go` is worth less than no dry run*.

    Both directions are asserted, because they fail independently: the dry run
    must not over-predict CHANGES and must not under-predict REFUSALS."""
    pack_dir, workdir = a_split_and_a_share(tmp)
    path, split, other = split_and_share_page(pack_dir, workdir)
    before = open_pack(pack_dir).snapshot()["id"]

    rc_dry, dry = confirm(pack_dir, workdir, checkpoint=1, go=False)
    dry_changes, dry_refused = spoken_counts(dry, go=False)
    assert open_pack(pack_dir).snapshot()["id"] == before, \
        "the dry run moved the pack"

    rc_go, said = confirm(pack_dir, workdir, checkpoint=1, go=True)
    go_changes, go_refused = spoken_counts(said, go=True)

    assert (dry_changes, dry_refused) == (go_changes, go_refused), (
        f"the dry run said {dry_changes} change(s) / {dry_refused} refused "
        f"and --go delivered {go_changes} / {go_refused}\n--- dry ---\n{dry}"
        f"\n--- go ---\n{said}")
    # ⭐ U2-6 (owner ruling 20261001): this row is now read as one row per
    # draft before storage, in BOTH modes, so the agreement is asserted on
    # the accepted answer — still both directions, still the same numbers.
    assert rc_dry == rc_go == 0, (rc_dry, rc_go, dry, said)
    assert go_refused == 0 and go_changes > 0, (said,)
    assert "so it was read as two rows" in dry and "so it was read as two rows" in said
    after = psub.load(pack=open_pack(pack_dir))
    assert after.get_literal(other).name == "Name-Shared", after.get_literal(other).record
    log(f"dry run and --go both say {go_changes} change(s) / {go_refused} "
        "refused")


def case_the_two_row_remedy_the_refusal_teaches_is_performed(tmp):
    """OA-19 — the other half of a refusal that teaches. `partition_subject()`
    now tells the owner to write the split and the cross-subject naming as two
    separate rows, and a refusal that prescribes a remedy the engine will not
    perform is worse than one that prescribes nothing.

    So the same fixture that produces the refusal is answered the way the
    refusal asks for: the split draft's frames on rows of their own, the other
    draft's naming on a row of its own. Both go in the SAME answer, the dry
    run predicts it, and `--go` performs it with nothing refused.

    ⚠️ Three rows on a page that renders two, which the renderer allows in
    words ("an owner who needs a third row copies one") and is asserted here
    because the remedy needs it."""
    pack_dir, workdir = a_split_and_a_share(tmp)
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    by_subject = pm.parse_review(path.read_text())[0]["frames_by_subject"]
    split = max(by_subject, key=lambda s: (len(by_subject[s]), s))
    other = [s for s in by_subject if s != split][0]

    text = path.read_text()
    blank = next(line for line in text.splitlines() if PICK_ROW in line)
    text = text.replace(blank, blank + "\n" + blank, 1)
    text = fill_pick(text, None, frames=str(by_subject[split][0]),
                     name="Name-Split-A")
    text = fill_pick(text, None,
                     frames=",".join(str(n) for n in by_subject[split][1:]),
                     name="Name-Split-B")
    text = fill_pick(text, None,
                     frames=",".join(str(n) for n in by_subject[other]),
                     name="Name-Other")
    path.write_text(text)

    rc_dry, dry = confirm(pack_dir, workdir, checkpoint=1, go=False)
    dry_changes, dry_refused = spoken_counts(dry, go=False)
    assert (rc_dry, dry_refused) == (0, 0), dry
    rc_go, said = confirm(pack_dir, workdir, checkpoint=1, go=True)
    go_changes, go_refused = spoken_counts(said, go=True)
    assert (rc_go, go_refused) == (0, 0), said
    assert (dry_changes, dry_refused) == (go_changes, go_refused), (dry, said)

    after = psub.load(pack=open_pack(pack_dir))
    parent = after.get_literal(split)
    assert parent.status == psub.STATUS_SUPERSEDED, parent.record
    assert len(parent.record.get("split_into") or []) == 2, parent.record
    # ...and the naming row kept the id it named, which is the whole reason
    # the two halves cannot share a row.
    named = after.get_literal(other)
    assert named.status == psub.STATUS_CONFIRMED, named.record
    assert named.name == "Name-Other", named.record
    log("the split and the naming, written as separate rows in one answer")


def case_a_split_row_and_a_naming_row_share_one_name(tmp):
    """⛔ MEASURED 20260827, Tier 3 round 1 defect D6 — doc 8 amendment (a),
    signed the same evening.

    The owner's true answer was ONE subject whose frames lived partly inside a
    draft they were also splitting and partly in whole drafts beside it, and
    the page refused every form of it:

      * one row doing both — refused by `partition_subject()`'s shared gate,
        which prescribed *say it as TWO rows*;
      * exactly those two rows — refused by the page-local name collision,
        which prescribed *put all of its frames on ONE `pick:` row*.

    Each message prescribed the other's forbidden form. The third door the
    second one offered — `distinct` — means *a separate subject that happens
    to share the name*, so an owner who takes it at face value to get unstuck
    writes the duplicate the whole checkpoint exists to prevent.

    ⭐ The invariant, and not the special case: **a refusal must never
    prescribe a row another gate would refuse.** So the two rows may share a
    name, and what they produce is what a row naming several tiles already
    produces — one name over member ids that keep their own records (F15).

    ⛔ The narrow case stays refused, and `case_two_rows_one_name_asks_before_
    the_pack_moves` is where that is asserted: rows that name ONE draft
    between them merge into one row that splits nothing, so the remedy exists
    and the collision is still a question."""
    # First, the refusal that starts the loop — it must now teach a form that
    # works, which is the half of D6 that is a message and not a gate.
    # U2-6 (owner ruling 20261001): a page answer of this shape is now read
    # as two rows before storage, so the teaching is read off the gate itself.
    taught_dir, taught_workdir = a_split_and_a_share(tmp)
    _reg, _split, groups = mixed_groups(taught_dir)
    taught = _reg.partition_refusal(_split, groups)
    assert taught, "the storage gate no longer refuses a mixed row"
    assert "TWO rows" in taught, taught
    assert "share a name" in taught, \
        ("the shared-row refusal still sends the owner to a door the "
         "collision check closes", taught)

    pack_dir, workdir = a_split_and_a_share(tmp / "shared-name")
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    by_subject = pm.parse_review(path.read_text())[0]["frames_by_subject"]
    split = max(by_subject, key=lambda s: (len(by_subject[s]), s))
    other = [s for s in by_subject if s != split][0]

    text = path.read_text()
    blank = next(line for line in text.splitlines() if PICK_ROW in line)
    text = text.replace(blank, blank + "\n" + blank, 1)
    # Row 1 and row 3 are ONE subject: some frames of the draft being split,
    # and the whole of the draft beside it. Row 2 is the rest of the split.
    text = fill_pick(text, None, frames=str(by_subject[split][0]),
                     name="Name-One")
    text = fill_pick(text, None,
                     frames=",".join(str(n) for n in by_subject[split][1:]),
                     name="Name-Two")
    text = fill_pick(text, None,
                     frames=",".join(str(n) for n in by_subject[other]),
                     name="Name-One")
    path.write_text(text)

    rc_dry, dry = confirm(pack_dir, workdir, checkpoint=1, go=False)
    _dry_changes, dry_refused = spoken_counts(dry, go=False)
    assert (rc_dry, dry_refused) == (0, 0), \
        ("the dry run refused an answer `--go` accepts", dry)
    rc_go, said = confirm(pack_dir, workdir, checkpoint=1, go=True)
    _go_changes, go_refused = spoken_counts(said, go=True)
    assert (rc_go, go_refused) == (0, 0), said
    assert pm.DISTINCT_TOKEN not in said, \
        ("the owner was still offered the door that writes two subjects under "
         "one name", said)

    after = psub.load(pack=open_pack(pack_dir))
    parent = after.get_literal(split)
    assert parent.status == psub.STATUS_SUPERSEDED, parent.record
    children = list(parent.record.get("split_into") or [])
    assert len(children) == 2, parent.record
    # The split's first child and the whole draft beside it are ONE name...
    one = sorted(s.subject_id for s in after.subjects if s.name == "Name-One")
    assert one == sorted([children[0], other]), (one, children, other)
    for subject_id in one:
        assert after.get_literal(subject_id).status == psub.STATUS_CONFIRMED, \
            after.get_literal(subject_id).record
    # ...and the other child is the other name, which is what makes this a
    # split and not a merge.
    two = [s.subject_id for s in after.subjects if s.name == "Name-Two"]
    assert two == [children[1]], (two, children)
    log("one subject over a split child and the draft beside it, answered on "
        "two rows of one page and written as one name")


def case_a_shared_name_is_a_question_again_without_its_split_row(tmp):
    """Amendment (a)'s first guard, and it is a DIFFERENT cause from the one
    below: here the split never happens at all.

    ⛔ The exemption is decided off the PARSED rows, because the collision
    check runs per row and cannot see that a later row also picks the same
    parent. So a row refused in that same pass — a missing `who`, a frame
    clash, anything doc 4 v4 refuses — still counted towards the split it
    named. Without it the parent takes the one-row in-place branch, nothing is
    partitioned, and the merged row the collision message asks for would have
    been accepted: the remedy exists after all.

    Left unchecked that writes two ids under one name with no question asked,
    and `photo_recurrence.subject_folder()` renders ONE folder off the name —
    the merge SNS-7 exists to prevent, arriving at the layer the owner
    actually looks at."""
    pack_dir, workdir = a_split_and_a_share(tmp)
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    by_subject = pm.parse_review(path.read_text())[0]["frames_by_subject"]
    split = max(by_subject, key=lambda s: (len(by_subject[s]), s))
    other = [s for s in by_subject if s != split][0]

    text = path.read_text()
    blank = next(line for line in text.splitlines() if PICK_ROW in line)
    text = text.replace(blank, blank + "\n" + blank, 1)
    text = fill_pick(text, None, frames=str(by_subject[split][0]),
                     name="Name-One")
    # The row that makes it a split, refused for a reason of its own (ONB-13).
    text = fill_pick(text, None, who="",
                     frames=",".join(str(n) for n in by_subject[split][1:]),
                     name="Name-Two")
    text = fill_pick(text, None,
                     frames=",".join(str(n) for n in by_subject[other]),
                     name="Name-One")
    path.write_text(text)

    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=True)
    assert rc == 1, said
    assert "`who` and `name` are one answer" in said, said
    assert "'Name-One' was answered on 2 rows" in said, said
    assert "refused above" in said, said
    after = psub.load(pack=open_pack(pack_dir))
    assert not [s for s in after.subjects if s.name], \
        ("two ids took one name on a page that split nothing",
         [(s.subject_id, s.name) for s in after.subjects if s.name])
    assert after.get_literal(split).is_draft, after.get_literal(split).record
    assert after.get_literal(other).is_draft, after.get_literal(other).record
    log("the exemption is withdrawn when the row it rested on is refused, and "
        "the collision is a question again")


def case_a_shared_name_is_refused_whole_when_its_split_dies(tmp):
    """Amendment (a)'s half-applied path, closed deliberately.

    Two rows sharing one name are ONE answer about ONE subject — that is the
    whole reason the collision check stood down for them. So a split that dies
    inside `partition_picks()` must not leave the other half of that name
    written: the whole drafts confirmed, the frames the split would have
    carried unnamed, and a subject that is a fraction of what the owner
    described, with nothing in the pack to say so.

    The split is killed the way a real one dies — the embed index the child's
    own centroid is computed from is gone, which is `frames_centroid()`'s
    refusal and the one `partition_picks()` turns into `dead += rows`."""
    pack_dir, workdir = a_split_and_a_share(tmp)
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    by_subject = pm.parse_review(path.read_text())[0]["frames_by_subject"]
    split = max(by_subject, key=lambda s: (len(by_subject[s]), s))
    other = [s for s in by_subject if s != split][0]

    text = path.read_text()
    blank = next(line for line in text.splitlines() if PICK_ROW in line)
    text = text.replace(blank, blank + "\n" + blank, 1)
    text = fill_pick(text, None, frames=str(by_subject[split][0]),
                     name="Name-One")
    text = fill_pick(text, None,
                     frames=",".join(str(n) for n in by_subject[split][1:]),
                     name="Name-Two")
    text = fill_pick(text, None,
                     frames=",".join(str(n) for n in by_subject[other]),
                     name="Name-One")
    path.write_text(text)
    (workdir / "embed" / "embeddings.npy").unlink()

    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=True)
    assert rc == 1, said
    assert "'Name-One' was answered on 2 rows" in said, said
    after = psub.load(pack=open_pack(pack_dir))
    assert not [s for s in after.subjects if s.name], \
        ("half of one name was written after its split was refused",
         [(s.subject_id, s.name) for s in after.subjects if s.name])
    assert after.get_literal(other).is_draft, after.get_literal(other).record
    log("a name answered on two rows is refused whole when its split dies")


def case_a_predicted_split_still_runs_under_go(tmp):
    """⛔ The over-correction the fix must not make. Predicting a refusal from
    the same gates the verb takes is only right if the gates are the SAME
    gates: a prediction that refused a legal split would close the verb SNS-1b
    exists for, and every assertion in this file about `--go` would still pass.

    So the neighbouring case is asserted here: two rows, no shared name, dry
    run predicts the split and `--go` performs it."""
    pack_dir, workdir = one_draft_three_unlike_frames(tmp)
    profile_arg = str(pack_dir / "photo-profile.json")
    pm.cmd_review(argparse.Namespace(workdir=str(workdir), profile=profile_arg,
                                     checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    text = fill_pick(path.read_text(), None, frames="1,3", name="Name-A")
    path.write_text(fill_pick(text, None, frames="2", name="Name-B"))

    rc, dry = confirm(pack_dir, workdir, checkpoint=1, go=False)
    assert rc == 0, dry
    assert "split into 2 subject(s)" in dry, dry
    assert spoken_counts(dry, go=False)[1] == 0, dry

    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=True)
    assert rc == 0, said
    assert spoken_counts(said, go=True)[1] == 0, said
    parent = pm.parse_review(path.read_text())[0]["subject_ids"][0]
    after = psub.load(pack=open_pack(pack_dir))
    assert after.get_literal(parent).status == psub.STATUS_SUPERSEDED, said
    log("a legal split is still predicted and still performed")


# ======================================================= step 9, item 3 ====
#
# SNS-16, signed 2026-08-20: a draft the owner recognises as a subject the
# pack ALREADY knows. Not a fold (both sides confirmed — SNS-14), not a new
# record (SNS-1b), and — ⭐ the substance of the signature — with NO
# SIMILARITY BAR.

def a_remembered_subject_and_a_new_draft(tmp, vec=None, name="Name-Shared"):
    """The state SNS-16 is about, and the one that arrives on every dump
    after the first: a subject the owner named, and a NEW draft of it that the
    geometry failed to match. -> (pack dir, later work dir, target id, draft
    id)."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    target, rc = answer_the_question(pack_dir, workdir, name=name)
    assert rc == 0, "the fixture could not name its subject"
    # TWO batches, so the draft carries more than one frame: a row that picks
    # some of them and a row that picks the rest is what the refusals below
    # are about, and a one-frame draft cannot express it.
    #
    # ⚠️ Batches 3 and 4, never 1 and 2. `batch_fixture()` mints its vec_refs
    # as `sha256:<batch>-<cluster>-<n>`, so re-using a batch number across two
    # dumps hands the later dump the EARLIER one's content sha — and a
    # promotion of a ref the subject already holds comes back `already-held`,
    # which is a fixture collision reading exactly like a working promotion.
    for batch in (3, 4):
        later, _summary = photograph_again(
            tmp, pack_dir, name="dump2", batch=batch,
            vec=basis(11) if vec is None else vec, month=f"2030-0{batch}")
    pm.cmd_review(argparse.Namespace(
        workdir=str(later), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    page = later / "memory-review_C1.md"
    drafts = pm.parse_review(page.read_text())[0]["subject_ids"]
    assert len(drafts) == 1, drafts
    return pack_dir, later, target, drafts[0]


def frame_score(pack_dir, workdir, subject_id, ref):
    """The cosine the engine would have measured, if SNS-16 had a bar: this
    frame's vector against the subject's whole exemplar set, `confirmed_match()`
    shape. -> float."""
    registry = psub.load(pack=open_pack(pack_dir))
    V = registry.vectors_for(subject_id)
    assert V is not None and len(V), f"{subject_id} holds no exemplar"
    look = [l for l in pm.subject_looks(registry.get_literal(ref[0]))
            if l["vec_ref"] == ref[1]]
    assert len(look) == 1, ref
    index, _identity = pm.load_embed_index(look[0]["workdir"])
    row = index.get(look[0]["path"])
    assert row is not None, look[0]
    return float(np.max(V @ row[1]))


def case_a_draft_joins_the_subject_the_pack_already_knows(tmp):
    """⭐ SNS-16, end to end and through the row the round rendered.

    The owner picks the frames of a draft, types the name of a subject the
    pack already holds, and answers the SNS-7 collision with `same`. That is a
    PROMOTION INTO that subject:

      * the picked frames' looks become the existing subject's exemplars —
        `attach_exemplars(..., only_refs=<picked>)`, so SNS-1b's per-look rule
        governs it exactly as it governs a first confirm;
      * the member draft becomes `absorbed` — bookkeeping only, no name, no
        exemplars of its own, no contact sheet — and `release_absorbed()`
        reverses it;
      * the confirmed subject gains exemplars and NOTHING else: its name, its
        `who` and its first-sighting centroid are untouched."""
    pack_dir, later, target, draft = a_remembered_subject_and_a_new_draft(tmp)
    before = psub.load(pack=open_pack(pack_dir))
    kept = dict(before.get_literal(target).record)
    held = [e["vec_ref"] for e in before.get_literal(target).exemplars]
    centroid = before.draft_centroid(target)

    page = later / "memory-review_C1.md"
    block = pm.parse_review(page.read_text())[0]
    picked = sorted(block["frames_by_subject"][draft])[:1]
    page.write_text(fill_pick(
        page.read_text(), None,
        frames=",".join(str(n) for n in picked),
        name=f"Name-Shared {pm.SAME_TOKEN}"))

    rc, dry = confirm(pack_dir, later, checkpoint=1, go=False)
    assert rc == 0, dry
    assert target in dry and draft in dry, dry
    assert psub.load(pack=open_pack(pack_dir)).get_literal(draft).is_draft, \
        "a dry run absorbed the draft"

    rc, said = confirm(pack_dir, later, checkpoint=1, go=True)
    assert rc == 0, said

    after = psub.load(pack=open_pack(pack_dir))
    grown = after.get_literal(target)
    picked_refs = {block["frames"][n]["ref"] for n in picked}
    gained = [e["vec_ref"] for e in grown.exemplars
              if e["vec_ref"] not in held]
    assert gained, ("the subject gained no exemplar — the answer promoted "
                    "nothing", said)
    assert {pm.short_ref(r) for r in gained} == picked_refs, \
        ("frames nobody picked were promoted", gained, picked_refs)

    # ...and NOTHING else moved
    assert grown.name == kept["name"] and grown.who == kept["who"], grown.record
    assert grown.record.get("files") == kept.get("files"), grown.record
    assert grown.record.get("active") == kept.get("active"), grown.record
    assert np.allclose(after.draft_centroid(target), centroid), \
        "the first-sighting centroid was recomputed"

    absorbed = after.get_literal(draft)
    assert absorbed.status == psub.STATUS_ABSORBED, absorbed.record
    assert absorbed.record.get("absorbed_by") == target, absorbed.record
    assert not absorbed.name, "an absorbed draft took a name"
    assert not absorbed.exemplars, "an absorbed draft kept exemplars of its own"
    assert absorbed not in after.drafts, "an absorbed draft is still asked about"

    # reversible, through the verb that already exists
    released = after.release_absorbed(target, by="Test Operator",
                                      reason="test")
    assert released == [draft], released
    assert after.get_literal(draft).is_draft, after.get_literal(draft).record
    assert after.get_literal(draft).record.get(psub.REOPENED_FLAG), \
        "the released draft cannot reach a work dir that already asked"
    log(f"{draft} joined {target}: {len(gained)} exemplar(s) gained, nothing "
        "else moved, and the release takes it back")


def case_the_promotion_has_no_similarity_bar(tmp):
    """⭐⭐ THE SIGNED DECISION, in executable form. SNS-16 accepts the
    promotion on the owner's yes ALONE — the engine does not score the picked
    frames against the subject's exemplars first, and there is no `{n}` here
    to tune.

    Two measurements are behind that signature, and both say a bar would
    reject correct answers rather than catch wrong ones:

      1. at C1 on 2026-08-20 a confirmed subject scored **0.832** against its
         own photograph — below the 0.85 every other threshold in the engine
         uses. A bar meant to protect it would have refused a real photo of
         it;
      2. photographs of one animal across a year score 0.60–0.85 against each
         other, which is the finding that killed cross-batch embedding dedupe.

    So this asserts the frame the owner picked scores BELOW that bar and is
    promoted anyway. ⛔ If a future build adds a threshold here, this is the
    test that has to be deleted to do it — which is the point of writing it."""
    pack_dir, later, target, draft = a_remembered_subject_and_a_new_draft(tmp)
    page = later / "memory-review_C1.md"
    block = pm.parse_review(page.read_text())[0]
    picked = sorted(block["frames_by_subject"][draft])[:1]
    full_ref = [look["vec_ref"] for look in pm.subject_looks(
        psub.load(pack=open_pack(pack_dir)).get_literal(draft))
        if pm.short_ref(look["vec_ref"]) == block["frames"][picked[0]]["ref"]]
    assert len(full_ref) == 1, full_ref

    score = frame_score(pack_dir, later, target, (draft, full_ref[0]))
    bar = psub.DEFAULT_THRESHOLDS["confirmed_suppress_tau"]
    assert bar == 0.85, bar
    assert score < bar, (
        f"the fixture is not the case being asserted: the picked frame scores "
        f"{score:.3f}, at or above the {bar} bar every other decision uses")

    page.write_text(fill_pick(
        page.read_text(), None, frames=",".join(str(n) for n in picked),
        name=f"Name-Shared {pm.SAME_TOKEN}"))
    rc, said = confirm(pack_dir, later, checkpoint=1, go=True)
    assert rc == 0, said

    after = psub.load(pack=open_pack(pack_dir))
    assert full_ref[0] in [e["vec_ref"] for e in
                           after.get_literal(target).exemplars], (
        f"a frame scoring {score:.3f} was refused — SNS-16 has grown a "
        "similarity bar, and a bar would have refused a real photograph of "
        "the right animal", said)
    assert after.get_literal(draft).status == psub.STATUS_ABSORBED, said
    log(f"the picked frame scores {score:.3f} against the subject it joined, "
        "and the owner's yes is the whole of the decision")


def case_one_draft_joins_two_remembered_pets_frame_by_frame(tmp):
    """⭐ B2 (REPRODUCTION, UAT02-01 — hit on 3 of 5 pages). ⛔ FAILS on
    6edab52: the owner named frame A of one draft as one remembered pet and
    frame B as another, and BOTH rows were refused with "answer the other on
    the next round". Now the draft is split by rows and each child joins its
    own pet: each pet gains exactly its own frame, nothing is refused, and no
    frame is promoted into the wrong pet."""
    pack_dir, later, target, draft = a_remembered_subject_and_a_new_draft(tmp)
    kind = psub.load(pack=open_pack(pack_dir)).get_literal(target).kind
    reg_path = pack_dir / "photo-subjects" / "subjects.json"
    data = json.loads(reg_path.read_text())
    data["subjects"].append({"subject_id": "subj-0900", "name": "Name-Second",
                             "who": "pet", "kind": kind,
                             "status": psub.STATUS_CONFIRMED, "exemplars": []})
    reg_path.write_text(json.dumps(data))
    (later / "memory-review_C1.md").unlink()
    page = review_text(pack_dir, later)
    block = pm.parse_review(page.read_text())[0]
    a, b = sorted(block["frames_by_subject"][draft])[:2]
    text = fill_pick(page.read_text(), None, frames=str(a),
                     name=f"Name-Shared {pm.SAME_TOKEN}")
    page.write_text(fill_pick(text, None, frames=str(b),
                              name=f"Name-Second {pm.SAME_TOKEN}"))
    rc, dry = confirm(pack_dir, later, go=False)
    assert rc == 0 and "would be superseded by a split" in dry and ", 0 refused" in dry, dry
    rc, said = confirm(pack_dir, later)
    assert rc == 0, said
    after = psub.load(pack=open_pack(pack_dir))
    held = {sid: {pm.short_ref(e["vec_ref"]) for e in after.get_literal(sid).exemplars}
            for sid in (target, "subj-0900")}
    ref_a, ref_b = block["frames"][a]["ref"], block["frames"][b]["ref"]
    assert ref_a in held[target] and ref_b not in held[target], held
    assert held["subj-0900"] == {ref_b}, held
    assert after.get_literal(draft).status == psub.STATUS_SUPERSEDED, said
    assert "next round" not in said, said


def change_counts(dry, said):
    import re as _re
    return (_re.findall(r"dry run — (\d+) change", dry),
            _re.findall(r"wrote (\d+) change", said))


def case_a_dry_run_counts_what_go_writes_when_no_look_is_kept(tmp):
    """⭐ N16 (REPRODUCTION, UAT02-01: "dry run said 8, --go wrote 7"). ⛔ FAILS
    on 6edab52: the dry run prints a line for the subject that gains the
    picked looks before it can know how many, and `--go` printed it only when
    at least one was kept. Measured with every look refused, on BOTH paths —
    a join (SNS-16) and a first confirm."""
    orig = pm.attach_exemplars
    try:
        pm.attach_exemplars = lambda reg, subj, refs: (0, ["look refused (test)"])
        pack_dir, later, _target, draft = a_remembered_subject_and_a_new_draft(
            Path(tmp) / "join")
        page = later / "memory-review_C1.md"
        n = sorted(pm.parse_review(page.read_text())[0]["frames_by_subject"][draft])[0]
        page.write_text(fill_pick(page.read_text(), None, frames=str(n),
                                  name=f"Name-Shared {pm.SAME_TOKEN}"))
        _rc, dry = confirm(pack_dir, later, go=False)
        _rc, said = confirm(pack_dir, later)
        joined = change_counts(dry, said)

        pack_dir, workdir = k_batch_run(Path(tmp) / "first", 2)
        page = review_text(pack_dir, workdir)
        page.write_text(fill_pick(page.read_text(), [1], name="Name-A"))
        _rc, dry = confirm(pack_dir, workdir, go=False)
        _rc, said = confirm(pack_dir, workdir)
        first = change_counts(dry, said)
    finally:
        pm.attach_exemplars = orig
    assert first[0] and first[0] == first[1], ("first confirm", first)
    assert joined[0] and joined[0] == joined[1], ("join", joined)


def case_a_promotion_row_is_one_answer(tmp):
    """The refusals SNS-16 needs, and each of them is a way the storage would
    otherwise be left saying two things at once.

    ⭐ B2 (owner decision 20260918) NARROWED the first clause: a draft named by
    a promotion row AND by another row is no longer refused — it is SPLIT by
    rows, each child keeps its own row's frames, and the promotion joins its
    own child (the other row names its). ⛔ Still refused: a row mixing drafts
    with a subject the owner already confirmed (a promotion and a fold on one
    gesture), and a promotion across `kind`."""
    pack_dir, later, target, draft = a_remembered_subject_and_a_new_draft(tmp)
    page = later / "memory-review_C1.md"
    original = page.read_text()
    block = pm.parse_review(original)[0]
    numbers = sorted(block["frames_by_subject"][draft])
    assert len(numbers) >= 2, numbers

    # the same draft on a promotion row and on a naming row: split, both land
    text = fill_pick(original, None, frames=str(numbers[0]),
                     name=f"Name-Shared {pm.SAME_TOKEN}")
    text = fill_pick(text, None, frames=str(numbers[1]), name="Name-Other")
    page.write_text(text)
    rc, said = confirm(pack_dir, later, checkpoint=1, go=True)
    assert rc == 0, said
    after = psub.load(pack=open_pack(pack_dir))
    assert after.get_literal(draft).status == psub.STATUS_SUPERSEDED, said
    other = [s for s in after.subjects if s.name == "Name-Other"]
    own = {pm.short_ref(e["vec_ref"]) for e in other[0].exemplars} if other else None
    assert len(other) == 1 and own == {block["frames"][numbers[1]]["ref"]}, \
        ("the naming row's child is not exactly its own frame", own, said)
    joined = {pm.short_ref(e["vec_ref"]) for e in after.get_literal(target).exemplars}
    assert block["frames"][numbers[0]]["ref"] in joined, (joined, said)
    assert block["frames"][numbers[1]]["ref"] not in joined, \
        ("the join took the other row's frame", joined, said)

    # across kinds — its own fixture, because the draft above was split. The
    # kind edit moves the pack, so the page is written again after it.
    pack_dir, later, target, draft = a_remembered_subject_and_a_new_draft(
        Path(tmp) / "kinds")
    registry = psub.load(pack=open_pack(pack_dir))
    registry.get_literal(draft).record["kind"] = "dog"
    registry.save()
    (later / "memory-review_C1.md").unlink()
    pm.cmd_review(argparse.Namespace(
        workdir=str(later), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    page = later / "memory-review_C1.md"
    numbers = sorted(pm.parse_review(page.read_text())[0]
                     ["frames_by_subject"][draft])
    page.write_text(fill_pick(page.read_text(), None,
                              frames=str(numbers[0]),
                              name=f"Name-Shared {pm.SAME_TOKEN}"))
    rc, said = confirm(pack_dir, later, checkpoint=1, go=True)
    assert rc == 1, said
    assert "kind" in said or "species" in said, said
    assert psub.load(pack=open_pack(pack_dir)).get_literal(draft).is_draft, said
    log("a promotion row that says two things is refused whole")


# ======================================================= step 9, item 4 ====

def the_instruction(said, key):
    """The row a refusal told the owner to type, lifted out of its own words.
    -> the text between the backticks, e.g. `name: Name-Shared same`.

    ⭐ Read from the message rather than written into the test, which is the
    whole method: a refusal that instructs a row the next handler refuses is
    invisible to any test that types what the AUTHOR meant. Measured
    2026-08-20 as defect A, and this is the general shape of it — every
    instruction the engine gives has to be followable."""
    import re as _re
    found = [m for m in _re.findall(r"`([^`\n]+)`", said)
             if m.startswith(f"{key}:") and pm.SAME_TOKEN in m]
    assert len(found) == 1, (f"the refusal named no single `{key}:` row to "
                             f"type: {found}", said)
    return found[0]


def case_the_collision_instruction_is_a_row_that_works(tmp):
    """⛔ MEASURED 2026-08-20, defect A: *`same` is instructed by one message
    and refused by the next.* The SNS-7 collision ask told the owner *"if it
    is genuinely the same one, write `name: X same`"*, and the handler for
    that row answered *"a fold joins two subjects the owner has each already
    confirmed, and this one is not one of them."*

    So this follows the instruction VERBATIM — the row is lifted out of the
    engine's own sentence, never typed from what this test thinks it says —
    and asserts it succeeds. Both doors are walked, because one message serves
    both and only one of them was ever true.

    ⛔ Defect B is asserted here too: the refusal used to offer *"leave these
    frames unpicked and the sweep absorbs them into subj-NNNN by itself"*,
    which cannot work — `sweep_absorb()` rides only on ids confirmed in the
    same run and re-presentation promotes nothing, so an already-confirmed
    subject is never in the sweep set. Verified empirically: nothing was
    absorbed. The sentence is gone; ⛔ the sweep itself is unchanged."""
    pack_dir, later, target, draft = a_remembered_subject_and_a_new_draft(tmp)
    page = later / "memory-review_C1.md"
    numbers = sorted(pm.parse_review(page.read_text())[0]
                     ["frames_by_subject"][draft])[:1]
    page.write_text(fill_pick(page.read_text(), None,
                              frames=",".join(str(n) for n in numbers),
                              name="Name-Shared"))

    rc, said = confirm(pack_dir, later, checkpoint=1, go=True)
    assert rc == 1, ("the collision was not raised", said)
    assert "already taken" in said, said
    # ⛔ the escape route that could not work
    assert "the sweep that runs after this confirm" not in said, said
    assert "leave these frames unpicked" not in said, said
    # ...and the promise has to be the OUTCOME. These frames are a draft, so
    # what `same` does here is SNS-16's promotion — nothing is folded, no id
    # becomes an alias, and a message that says otherwise is defect A one
    # sentence along: the owner types the row and gets a different thing.
    assert "alias" not in said, ("the `pick:` row is promised a fold, and a "
                                 "draft row does not fold", said)
    assert "exemplar" in said, said

    row = the_instruction(said, "name")
    typed = row.split(":", 1)[1].strip()
    page.write_text(fill_pick(page.read_text().replace(
        f"`pick:` {numbers[0]}   `who:` pet   `name:` Name-Shared", PICK_ROW),
        None, frames=str(numbers[0]), name=typed))

    rc, said = confirm(pack_dir, later, checkpoint=1, go=True)
    assert rc == 0, (f"the engine refused the row it told the owner to type: "
                     f"{row}", said)
    after = psub.load(pack=open_pack(pack_dir))
    assert after.get_literal(draft).status == psub.STATUS_ABSORBED, said
    assert len(after.get_literal(target).exemplars) > 1, said

    log("the `pick:` row the collision message instructs is a row that works")


def case_the_recheck_collision_instruction_is_a_row_that_works(tmp):
    """The other door into SNS-7's one sentence. `name_collision_refusal()`
    speaks for both rows and passes the way on in, so each door has to be
    walked separately or a change to one of them lands untested in the other.

    Here the way on is SNS-14's fold, and it was already true — which is
    exactly why it is asserted beside the `pick:` row rather than instead of
    it: one message, two instructions, and only one of them was false."""
    pack2, work2, first, _refs, second = two_remembered_subjects(tmp)
    path = review_text(pack2, work2, checkpoint=3)
    path.write_text(fill_recheck(path.read_text(), first, "Name-Other"))
    rc, said = confirm(pack2, work2, checkpoint=3, go=True)
    assert rc == 1 and "already taken" in said, said

    row = the_instruction(said, pm.RECHECK_KEY)
    path = review_text(pack2, work2, checkpoint=4)
    body = row.split(":", 1)[1].strip()
    assert body.startswith(first), (row, first)
    path.write_text(fill_recheck(path.read_text(), first,
                                 body[len(first):].strip()))
    rc, said = confirm(pack2, work2, checkpoint=4, go=True)
    assert rc == 0, (f"the engine refused the row it told the owner to type: "
                     f"{row}", said)
    assert psub.load(pack=open_pack(pack2)).get_literal(second).status \
        == psub.STATUS_MERGED_INTO, said
    log("the `recheck:` row the collision message instructs folds, as it says")


# ------------------------------------- step 8: the whole-dump ask count ---

MULTIKIND = {"kind-a": 4, "kind-b": 3, "kind-c": 1}
PER_QUESTION = 2


def multikind_dump(tmp):
    """A work dir shaped exactly as `photo_scan` + `photo_embed` + v1's
    `photo_sample` leave one, carrying THREE classes instead of one.

    One batch per subject, two files per batch, each batch's pair sitting on
    its own basis direction so no batch dedupes into another and the draft
    count per kind is `MULTIKIND`'s. Class words are invented ASCII — the
    engine reads them off `batches.json` at run time and holds none of them.

    ⛔ No `see-report.json` is written anywhere in here. The thumbnails are v1
    samples, exactly as on the benchmark dump, and `memorize_replay` claims
    `provenance: None` for them; a see-report would forge the evidence gate
    (`photo_evidence.evidence_problems()`) rather than satisfy it."""
    workdir = Path(tmp) / "multikind"
    (workdir / "embed").mkdir(parents=True)
    rows, vecs, batches, n = [], [], [], 0
    for kind, count in MULTIKIND.items():
        for _ in range(count):
            n += 1
            base = basis(n)
            first, batch_files = len(rows), []
            for k in range(2):
                name = f"IMG_{len(rows):04d}.JPG"
                rows.append({
                    "SourceFile": str(workdir / name), "FileName": name,
                    "FileType": "JPEG",
                    "DateTimeOriginal": f"2026:01:{n:02d} 09:0{k}:00",
                    "GPSPosition": "", "Make": "Apple", "Model": "iPhone",
                    "ImageWidth": "4032", "ImageHeight": "3024"})
                vecs.append(near(base, len(rows)))
                batch_files.append(rows[-1])
            batches.append({"batch": n, "label": "synthetic",
                            "from": f"2026-01-{n:02d}", "to": f"2026-01-{n:02d}",
                            "files": 2, "type": kind})
            out = view_fixture.batch_dir(workdir, n) / "samples"
            out.mkdir(parents=True)
            samples = []
            for row in batch_files:
                sample = Path(row["FileName"]).stem + ".jpg"
                (out / sample).write_bytes(view_fixture.JPEG)
                samples.append({"source": row["SourceFile"], "sample": sample,
                                "time": row["DateTimeOriginal"]})
            (out.parent / "sample-report.json").write_text(
                json.dumps({"batch": n, "samples": samples}))
            assert first + 2 == len(rows)

    with open(workdir / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (workdir / "batches.json").write_text(json.dumps({"batches": batches}))
    with open(workdir / "embed" / "embeddings.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["SourceFile", "sha256", "kind",
                                          "status", "size", "mtime", "error"])
        w.writeheader()
        for i, row in enumerate(rows):
            w.writerow({"SourceFile": row["SourceFile"],
                        "sha256": f"{i:064x}", "kind": "image",
                        "status": "embedded", "size": 100, "mtime": "1.0",
                        "error": ""})
    np.save(workdir / "embed" / "embeddings.npy",
            np.stack(vecs).astype(np.float32))
    meta = dict(IDENTITY)
    meta["normalized"] = True
    (workdir / "embed" / "embeddings-meta.json").write_text(json.dumps(meta))
    return workdir


def replay(workdir, *args):
    env = dict(os.environ)
    env.pop("PHOTO_PROFILE", None)
    proc = subprocess.run(
        [PY, str(ROOT / "tests" / "memorize_replay.py"), str(workdir), *args],
        capture_output=True, text=True, env=env)
    return proc


def case_the_whole_dump_replays_every_kind_in_one_round(tmp):
    """Step 8 — the replay covers a DUMP, not one shipped class, and it says
    the three numbers separately.

    Until 2026-08-21 `--type` was `required=True`, so every recorded number
    came off one class — and under the per-kind question shape one class is
    one kind is one question, which made the headline "1 question" true by
    construction and unable to be anything else. That is the defect this case
    pins: run with no `--type` at all and it must replay every class the dump
    ships, through ONE draft store.

    Asserted as an INVARIANT, not as the shipped constant: with
    `{drafts_rendered_per_question}` set to 2, a round of K kinds renders
    `sum(min(drafts_in_kind, 2))` tiles — 5 here, more than the clamp, in ONE
    round.

    ⚠️ Amended 2026-08-21, and the amendment is the point. This case used to
    assert the run SAID it had no round-level ceiling; `{tiles_per_round}` is
    now built, so it asserts the ceiling is stated instead. The 5 is unchanged
    because 5 is under the shipped ceiling of 12 — the fixture measures the
    per-kind clamp, and the case that exercises the ceiling itself is
    `case_a_multi_kind_round_is_bounded_by_the_tile_ceiling`. What is asserted
    here now is the accounting: the deferred figure is printed SPLIT by cause,
    and the identity `rendered + deferred + frameless = offered` holds, which
    is the only line that can catch a dropped draft.

    ⛔ Silent-owner path: nothing is answered, nothing is promoted, and no look
    claims `viewed-image:`. This is OA-13 exit-test clause (1) only."""
    workdir = multikind_dump(tmp)
    proc = replay(workdir, "--drafts-per-question", str(PER_QUESTION))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    said = proc.stdout

    kinds = len(MULTIKIND)
    drafts = sum(MULTIKIND.values())
    tiles = sum(min(n, PER_QUESTION) for n in MULTIKIND.values())
    deferred = drafts - tiles

    assert f"filed as {kinds} shipped class(es)" in said, said
    assert f"-> {drafts} draft record(s)" in said, said
    assert f"checkpoint C1 renders {kinds} question(s) carrying {tiles} " \
           "tile(s)" in said, said
    # one interruption, not K
    assert "rounds     1 fired" in said, said
    assert f"tiles      {tiles} " in said, said
    assert f"deferred   {deferred} draft(s)" in said, said
    assert "frameless  0 cluster(s)" in said, said
    # the ceiling, in the run's own words, and the deferral split by CAUSE —
    # here every deferred draft is the per-question clamp's, because 5 tiles
    # never reached the ceiling of 12
    assert "against the {tiles_per_round} ceiling of 12" in said, said
    assert f"0 beyond {{tiles_per_round}} = 12" in said, said
    assert f"+ {deferred} past {{drafts_rendered_per_question}} = " \
           f"{PER_QUESTION}" in said, said
    assert "ROUND CEILING EXCEEDED" not in said, said
    # ⛔ the identity — the only line that can catch a DROPPED draft
    assert f"= {tiles} + {deferred} + 0 = {drafts} = {drafts} draft " \
           "record(s) offered" in said, said
    # every kind is its own row, and no kind was dropped or merged into another
    for kind, count in MULTIKIND.items():
        assert f"{min(count, PER_QUESTION):>5} " \
               f"{count - min(count, PER_QUESTION):>8} " \
               f"{0:>9}  {kind!r}" in said, (kind, said)
    assert "MATCHES the page" in said, said
    assert "no look may claim viewed-image:" in said, said
    assert "No number this script prints closes OA-13." in said, said
    log(f"{kinds} kinds, {drafts} drafts -> 1 round, {tiles} tiles, "
        f"{deferred} deferred")


def case_one_type_still_replays_exactly_that_class(tmp):
    """The other half of making `--type` optional: it must still take one.

    A single `--type` selects the same batches the pre-multi-kind filter did,
    and the run then behaves as every number recorded in `memorize_replay`'s
    header was measured — one kind, one question, and the tile count that
    kind's clamp. Without this, "the flag is optional now" could quietly mean
    "the flag is ignored now" and every historical figure would be
    unreproducible."""
    workdir = multikind_dump(tmp)
    # ⛔ No `--drafts-per-question` here: the clamp is what the other case
    # exercises, and squeezing this run to 2 tiles would drop it under SNS-4's
    # new-subject floor, so the round would be WITHHELD and the case would be
    # asserting on a page that was never put in front of anyone.
    proc = replay(workdir, "--type", "kind-a")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    said = proc.stdout

    count = MULTIKIND["kind-a"]
    assert "filed as 'kind-a'" in said, said
    assert f"{count} cluster(s) offered from {count} batch(es) " \
           f"-> {count} draft record(s)" in said, said
    assert f"checkpoint C1 renders 1 question(s) carrying {count} " \
           f"tile(s), for {count} batch(es) of 'kind-a'" in said, said
    # ⛔ the single-class caveat is still the one that ships, word for word
    assert "with a single --type the question count is 1 by construction" \
        in said, said
    # ...and the three numbers are printed for a one-kind run too. A slice is
    # still rounds/tiles/deferred, and reporting it as one figure is the habit
    # LL-PHO-48 / 54 / 62 were written about.
    assert "rounds     1 fired" in said, said
    assert f"tiles      {count} — the owner-decision unit" in said, said
    assert "deferred   0 draft(s)" in said, said
    assert "frameless  0 cluster(s)" in said, said
    assert f"  {count:>7} {count:>7} {count:>6} {count:>5} {0:>8} {0:>9}" \
           "  'kind-a'" in said, said
    # a round of one kind cannot walk into the missing ceiling, and must not
    # claim it does
    assert "NO ROUND-LEVEL TILE CEILING" not in said, said
    for other in ("kind-b", "kind-c"):
        assert other not in said, (other, said)
    log(f"one --type -> {count} batches of one class, 1 question, "
        f"{count} tiles")


def case_a_class_the_dump_does_not_ship_is_reported(tmp):
    """A requested class that is not in the dump is NAMED, never silently
    dropped — a typo would otherwise read as "this class contributes
    nothing", which is a measurement rather than a mistake."""
    workdir = multikind_dump(tmp)
    proc = replay(workdir, "--type", "kind-a", "--type", "kind-absent")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no batch in this dump is filed as 'kind-absent'" in proc.stdout, \
        proc.stdout
    assert "filed as 1 shipped class(es)" in proc.stdout, proc.stdout

    only = replay(workdir, "--type", "kind-absent")
    assert only.returncode != 0, only.stdout
    assert "no batch in this dump is filed as 'kind-absent'" in \
        only.stdout + only.stderr, only.stdout + only.stderr
    log("an unshipped class is named, and alone it is a hard exit")


# ------------------------------- SNS-4: the round-level tile ceiling -------

# Nine drafts over three kinds, with distinct blast radii that INTERLEAVE the
# kinds: ranked on `(-files, subject_id)` the order is alpha, beta, alpha,
# gamma, beta, alpha, gamma, beta, gamma. A per-kind ranking cannot produce
# that sequence, so a test that pins the survivors pins the SCALE and not just
# the count. Class words are invented ASCII; the engine reads a draft's `kind`
# off the label the see stage applied and holds none of them.
RANKED = [("alpha", 9), ("beta", 8), ("alpha", 7), ("gamma", 6), ("beta", 5),
          ("alpha", 4), ("gamma", 3), ("beta", 2), ("gamma", 1)]
CEILING = 3


def ranked_kinds(tmp, ceiling=CEILING, owner="betauser00"):
    """-> (pack_dir, workdir, [subject_id in blast-radius order]).

    `{tiles_per_round}` set to `ceiling`; `{drafts_rendered_per_question}` left
    at the shipped 12 ON PURPOSE, so nothing but the round ceiling can cut this
    page and a tile count of `ceiling` cannot be the per-kind clamp wearing a
    new name."""
    pack_dir = make_pack(tmp, owner=owner)
    pack = open_pack(pack_dir)
    workdir = tmp / "dump"
    write_batches(workdir, len(RANKED))
    for batch, (kind, members) in enumerate(RANKED, 1):
        report, index, samples = batch_fixture(
            workdir, batch, [(basis(batch * 3), members)],
            month=f"2029-{batch:02d}")
        apply_and_memorize(workdir, pack, report, index, samples,
                           {report["selected"][0]["path"]:
                            {"label": kind.title(), "subject_kind": kind}})
    registry = psub.load(pack=open_pack(pack_dir))
    registry.data.setdefault("defaults", {})["tiles_per_round"] = ceiling
    registry.save()
    ranked = sorted(registry.drafts,
                    key=lambda s: (-int(s.record.get("files", 0)),
                                   s.subject_id))
    assert [int(d.record["files"]) for d in ranked] == \
        [n for _kind, n in RANKED], [d.record["files"] for d in ranked]
    return pack_dir, workdir, [d.subject_id for d in ranked]


def case_a_multi_kind_round_is_bounded_by_the_tile_ceiling(tmp):
    """SNS-4's `{tiles_per_round}` — the defect, not the parameter.

    Before 2026-08-21 the only clamp was per KIND, so a round of K kinds put up
    to `{drafts_rendered_per_question}` x K tiles in front of the owner and was
    still charged as ONE interruption. Nine drafts over three kinds rendered
    all nine. Here the ceiling is 3, and what must hold is the ROUND total
    across every question — with the per-question clamp left at 12 so it cannot
    be the thing doing the cutting.

    The survivors are the global top three, which straddles two kinds and shuts
    the third out completely. That is the accepted cost of one scale: a kind
    can be absent from a round. It is safe because being cut is a DEFERRAL —
    asserted below on the suppression sentence and on `asked_before()`."""
    pack_dir, workdir, ranked = ranked_kinds(tmp)
    pack = open_pack(pack_dir)
    registry = psub.load(pack=pack)
    profile = pack.profile
    questions, suppressed, over, _held = pm.build_questions(
        registry, workdir, pack, profile,
        photo_profile.review_messages(profile))

    tiles = [t["subject_id"] for q in questions for t in q["tiles"]]
    assert len(tiles) == CEILING, (len(tiles), tiles)
    # ...and they are the top three ON ONE SCALE, not the top of each kind.
    # ⚠️ Compared as a SET. This list is read question by question, so it
    # arrives GROUPED BY KIND, while `ranked` is the global scale the ceiling
    # cut on — here the top three straddle two kinds, so the two orders differ
    # by construction. Grouping is what a question IS; what this asserts is
    # WHICH drafts survived the cut, and pinning the print order instead would
    # be pinning the page layout while calling it the ranking.
    assert sorted(tiles) == sorted(ranked[:CEILING]), (tiles, ranked)
    assert over == len(RANKED) - CEILING, over

    kinds = [q["kind"] for q in questions]
    assert kinds == ["alpha", "beta"], kinds
    # the shut-out kind, said as its own assertion because it is the part of
    # the decision that had to be signed rather than derived
    assert "gamma" not in kinds, kinds
    log(f"{len(RANKED)} drafts over 3 kinds -> {len(tiles)} tile(s) in "
        f"{len(questions)} question(s); 'gamma' rendered nothing")


def case_a_round_deferred_draft_is_not_booked_as_asked(tmp):
    """The guarantee that makes shutting a kind out survivable.

    A draft the ceiling cut was never in front of the owner, so it must not
    reach layer 2 (`asked_before()`), and it must be recorded in `suppressed`
    with a reason — in the ROUND-level words, not the per-question ones,
    because the two have different repairs and an operator reading "one
    question was full" would go looking for a clamp that never bound."""
    pack_dir, workdir, ranked = ranked_kinds(tmp)
    pack = open_pack(pack_dir)
    profile = pack.profile
    _questions, suppressed, over, _held = pm.build_questions(
        psub.load(pack=pack), workdir, pack, profile,
        photo_profile.review_messages(profile))

    cut = dict(suppressed)
    assert over == len(ranked) - CEILING, over
    for sid in ranked[CEILING:]:
        assert sid in cut, (sid, suppressed)
        assert cut[sid].startswith("beyond this round's tile ceiling"), cut[sid]
        assert "per question" not in cut[sid], cut[sid]
        assert "still askable" in cut[sid], cut[sid]
    for sid in ranked[:CEILING]:
        assert sid not in cut, (sid, suppressed)

    # now write the page and read layer 2 back off it, which is the only book
    # that decides whether a subject has been asked
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    booked = pm.asked_before(workdir)
    assert sorted(booked) == sorted(ranked[:CEILING]), sorted(booked)
    for sid in ranked[CEILING:]:
        assert sid not in booked, sid

    # and the page says so to the OWNER, in a sentence the pack can override
    text = (workdir / "memory-review_C1.md").read_text()
    rmsg = photo_profile.review_messages(profile)
    said = rmsg["review_more_deferred_round"].format(n=over, cap=CEILING)
    assert said in text, text
    # ⛔ never the per-question sentence standing in for it
    assert rmsg["review_more_deferred"].format(n=over) not in text, text
    log(f"{over} draft(s) cut by the ceiling: suppressed with their own "
        "sentence, none booked as asked")


def case_the_ceiling_keeps_the_page_byte_identical(tmp):
    """Determinism, which the ceiling could have broken and did not.

    The cut is a slice of a list already in the total order
    `(-files, subject_id)` — the same key the per-kind slice and the question
    sort use — so no new ordering is introduced. Two renders of ONE checkpoint
    over one pack and one work dir must be byte-identical.

    ⚠️ Both pages are written OUTSIDE the work dir's review glob. A page
    written into the work dir is input to the next run (`asked_before()` reads
    every review file there), so the second render would legitimately differ
    and the comparison would be measuring the harness."""
    pack_dir, workdir, _ranked = ranked_kinds(tmp)
    pages = []
    for name in ("first.md", "second.md"):
        out = tmp / name
        pm.cmd_review(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=1, out=str(out)))
        pages.append(out.read_bytes())
    assert pages[0] == pages[1], "two renders of one checkpoint differ"
    text = pages[0].decode()
    ids = [t for q in pm.parse_review(text) for t in q["subject_ids"]]
    assert len(ids) == CEILING, ids
    log(f"two renders, {len(pages[0])} bytes each, identical; "
        f"{len(ids)} tile(s)")


def case_the_per_question_clamp_still_binds_under_the_ceiling(tmp):
    """`{drafts_rendered_per_question}` is not dead — it is SECOND.

    The ceiling binds first, so at the shipped 12/12 a kind can hold at most 12
    of the top 12 and the per-kind slice is provably the whole list. That is
    the two defaults lining up, not a retired parameter: set the clamp BELOW
    the ceiling and it bounds one question again, while the ceiling still
    bounds the round. Both numbers are checked here on one page."""
    pack_dir, workdir, ranked = ranked_kinds(tmp, ceiling=6)
    registry = psub.load(pack=open_pack(pack_dir))
    registry.data.setdefault("defaults", {})["tiles_per_round"] = 6
    registry.data["defaults"]["drafts_rendered_per_question"] = 1
    registry.save()

    pack = open_pack(pack_dir)
    profile = pack.profile
    questions, suppressed, over, _held = pm.build_questions(
        psub.load(pack=pack), workdir, pack, profile,
        photo_profile.review_messages(profile))
    # The ceiling admitted the global top six — which is alpha x3, beta x2,
    # gamma x1, NOT two of each. That asymmetry is the point of ranking on one
    # scale: the kinds are not entitled to equal shares, they compete.
    assert over == len(RANKED) - 6, over
    # ...and then the clamp cut each question to one tile
    assert [len(q["tiles"]) for q in questions] == [1, 1, 1], \
        [len(q["tiles"]) for q in questions]
    assert sorted(q["kind"] for q in questions) == ["alpha", "beta", "gamma"]
    # Questions sort by (-files, kind) and each renders its own widest draft,
    # so the order is alpha(9), beta(8), gamma(6) and what each still owes is
    # what the ceiling let in minus the one tile it showed: 3-1, 2-1, 1-1.
    assert [q["deferred"] for q in questions] == [2, 1, 0], \
        [q["deferred"] for q in questions]

    reasons = dict(suppressed)
    by_round = [s for s, why in suppressed
                if why.startswith("beyond this round's tile ceiling")]
    by_question = [s for s, why in suppressed
                   if why.startswith("not rendered at this checkpoint")]
    assert len(by_round) == 3 and len(by_question) == 3, \
        (by_round, by_question)
    # ⛔ nothing lost: rendered + round-deferred + question-deferred = offered
    assert 3 + len(by_round) + len(by_question) == len(ranked), reasons
    log("ceiling 6 then clamp 1 -> 3 tiles, 3 cut by the round, 3 by their "
        "question")



# ---- R3b: the tile shows the crop, and says when a frame is shared --------

def write_detection_index(workdir, per_file, dim=8, vectors=None):
    """R3a's index shape, one row per DETECTION.

    ⛔ A second, differently-shaped writer beside `write_identity_index()`
    above, and deliberately named apart from it: that one takes one row per
    FILE and is what every pre-R3a case wants. Two helpers with one name is
    how the last one defined silently becomes everybody's.

    `vectors`: {path: [vec, ...]} aligned with that file's detections, for
    the cases that need the rows to DISAGREE. ⛔ Without it every row is the
    same vector, which is right for the cases that only care about counts and
    useless for any case about how far apart two frames sit (U2-12).

    `per_file`: {path: [(det_index, det_count, box_string)]}. Written with
    photo_identity's own CSV_FIELDS and read back by its own loader, for the
    reason `write_embed_index` gives: a hand-rolled index would only prove
    that two hand-rolled things agree.

    F22: a frame with a detection and no crop is REFUSED at render, so every
    source here is made a real image (40 px) unless it already is one."""
    import photo_identity
    from PIL import Image as _Image
    for path in per_file:
        try:
            _Image.open(path).verify()
        except Exception:                                  # noqa: BLE001
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            _Image.new("RGB", (40, 40), (200, 90, 40)).save(path, "JPEG")
    embed = Path(workdir) / "embed"
    embed.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(per_file):
        for det_index, det_count, box in per_file[path]:
            rows.append({"SourceFile": path, "sha256": f"sha-{det_index}",
                         "status": photo_identity.STATUS_OK,
                         "det_index": det_index, "det_count": det_count,
                         "kind": "cat", "det_score": 0.9, "box": box,
                         "box_share": 0.4, "error": ""})
    with open(embed / "identity.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=photo_identity.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    if vectors is None:
        grid = [[1.0] * dim for _ in rows]
    else:
        used = {}
        grid = []
        for row in rows:
            path = row["SourceFile"]
            n = used.get(path, 0)
            used[path] = n + 1
            grid.append(list(vectors[path][n]))
    np.save(embed / "identity.npy", np.array(grid, dtype=np.float32))
    (embed / "identity-meta.json").write_text(json.dumps(
        {**photo_identity.meta_identity(dim), "created_at": "2029-01-01 00:00"}))
    return rows


def draft_look_paths(pack_dir):
    """-> every source path the drafts' looks name, in record order."""
    registry = psub.load(pack=open_pack(pack_dir))
    return [look.get("path")
            for draft in sorted(registry.drafts, key=lambda d: d.subject_id)
            for look in pm.subject_looks(draft)]


def one_draft_two_frames(tmp, owner="betauser00"):
    """ONE draft carrying TWO frames — the same cluster seen in two batches,
    which is `reinforced` and therefore one subject, one question, two
    photographs on the contact sheet.

    ⛔ Not `two_lookalike_drafts`: that makes two drafts of ONE frame each,
    and a group can only disagree with itself if it holds more than one
    frame. -> (pack_dir, workdir, subject_id)."""
    pack_dir = make_pack(tmp, owner=owner)
    pack = open_pack(pack_dir)
    workdir = tmp / "dump"
    write_batches(workdir, 2)
    for batch in (1, 2):
        report, index, samples = batch_fixture(workdir, batch,
                                               [(basis(0), 3)],
                                               month=f"2029-0{batch}")
        apply_and_memorize(workdir, pack, report, index, samples,
                           {report["selected"][0]["path"]:
                            {"label": "Cat", "subject_kind": "cat"}})
    registry = psub.load(pack=open_pack(pack_dir))
    ids = sorted(d.subject_id for d in registry.drafts)
    assert len(ids) == 1, f"one reinforced draft expected, got {ids}"
    return pack_dir, workdir, ids[0]


def case_a_group_that_disagrees_with_itself_says_so(tmp):
    """⭐ THE U2-12 REPRODUCTION, on the page. A tile is a claim that these
    photographs are ONE subject. Its frames are gathered by scoring each
    against the group's FIRST centroid and never against each other, so a
    group can hold two animals and every warning the page had — all of them
    per-FRAME — stays silent.

    ⛔ FAILS on the pre-C11 engine, which renders the tile with nothing said."""
    pack_dir, workdir, subject_id = one_draft_two_frames(tmp)
    paths = draft_look_paths(pack_dir)
    assert len(paths) == 2, f"the fixture must give the draft 2 frames: {paths}"
    apart = {paths[0]: [[1.0] + [0.0] * 7], paths[1]: [[0.0, 1.0] + [0.0] * 6]}
    write_detection_index(workdir,
                          {p: [(0, 1, "1.0,1.0,9.0,9.0")] for p in paths},
                          vectors=apart)
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    text = (workdir / "memory-review_C1.md").read_text()
    marker = photo_profile.REVIEW_VOCAB["en"]["review_group_incoherent"][:40]
    assert marker in text, \
        ("a tile holding two different animals reached the owner with "
         "nothing said about the group")
    log("an incoherent group is marked on the page before the owner answers")


def case_a_group_that_agrees_with_itself_stays_quiet(tmp):
    """GUARD, and the expensive direction. Two frames of ONE animal must draw
    no warning: a page that flags every group teaches the owner to scroll
    past the flag, which costs the one group that needed it."""
    pack_dir, workdir, subject_id = one_draft_two_frames(tmp)
    paths = draft_look_paths(pack_dir)
    together = {paths[0]: [[1.0] + [0.0] * 7],
                paths[1]: [[0.97, 0.24] + [0.0] * 6]}
    write_detection_index(workdir,
                          {p: [(0, 1, "1.0,1.0,9.0,9.0")] for p in paths},
                          vectors=together)
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    text = (workdir / "memory-review_C1.md").read_text()
    marker = photo_profile.REVIEW_VOCAB["en"]["review_group_incoherent"][:40]
    assert marker not in text, \
        "two frames of one animal were flagged as two animals"


def case_a_shared_frame_says_so_on_the_page(tmp):
    """⭐ THE R3b REPRODUCTION, and it is LL-PHO-136 stated as a test.

    The page renders a tile as one claim — *these photographs are one
    subject* — and offers a frame-level verb to refute it. In UAT01 it
    supplied no per-frame evidence at all: no score, no outlier mark, and no
    multi-animal flag. The owner opened the first frame, recognised the cat,
    and confirmed all five; three were wrong, two of them because the frame
    held both cats. Nothing on the page could have told them.

    ⛔ The frame is still PICKABLE and still names its group — two subjects in
    one frame is two names to log, never a frame to refuse. What it may not do
    is enter the exemplar bank, and the page now says which of those two
    things is happening."""
    pack_dir, workdir, ids = two_lookalike_drafts(tmp)
    paths = draft_look_paths(pack_dir)
    assert paths, "fixture produced no looks"
    write_detection_index(workdir, {paths[0]: [(0, 2, "1.0,1.0,9.0,9.0"),
                                               (1, 2, "9.0,9.0,19.0,19.0")]})
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    text = (workdir / "memory-review_C1.md").read_text()
    shared = re.search(r"`animals:` (\d+)=2", text).group(1)
    expected = photo_profile.REVIEW_VOCAB["en"]["review_frame_shared"].format(
        n=2, frame=shared)
    assert expected in text, \
        "a frame holding two animals reached the owner with nothing said"
    assert text.count(expected) == 1, \
        "only the shared frame carries the warning, not every frame"
    log("a shared frame is marked on the page before the owner answers")


def shared_frame_page(tmp):
    """A checkpoint page whose first draft look holds two animals.
    -> (pack_dir, workdir, page path, text, the shared frame's number)."""
    pack_dir, workdir, _ids = two_lookalike_drafts(tmp)
    paths = draft_look_paths(pack_dir)
    write_detection_index(workdir, {paths[0]: [(0, 2, "1.0,1.0,9.0,9.0"),
                                               (1, 2, "9.0,9.0,19.0,19.0")]})
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    page = workdir / "memory-review_C1.md"
    text = page.read_text()
    shared = int(re.search(r"`animals:` (\d+)=2", text).group(1))
    return pack_dir, workdir, page, text, shared


def review_with_thumbnails(pack_dir, workdir, make):
    """cmd_review with the preview conversion able (`make`) or unable to open
    the photo, as a python without pillow-heif is on a HEIC. -> what stopped
    it, or None."""
    import photo_embed
    saved = photo_embed.convert_to_thumbnail

    def thumb(src, dst_dir, stem, kind, filetype):
        if not make:
            return None, "decode_failed"
        out = Path(dst_dir) / f"{stem}.jpg"
        from PIL import Image as _Image
        _Image.new("RGB", (40, 40), (200, 90, 40)).save(out, "JPEG")
        return out, None
    photo_embed.convert_to_thumbnail = thumb
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_review(argparse.Namespace(
                workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
                checkpoint=1, out=None))
    except SystemExit as stop:
        return str(stop.code)
    finally:
        photo_embed.convert_to_thumbnail = saved
    return None


def case_a_frame_whose_crop_cannot_be_made_is_refused(tmp):
    """REPRODUCTION (F22). ⛔ FAILS on 5b320fb: the index found an animal in
    the frame, the crop could not be made (measured: a HEIC under a python
    without pillow-heif), and the page showed the WHOLE photo without a word."""
    pack_dir, workdir, _ids = two_lookalike_drafts(tmp)
    paths = draft_look_paths(pack_dir)
    write_detection_index(workdir, {paths[0]: [(0, 2, "1.0,1.0,9.0,9.0"),
                                               (1, 2, "9.0,9.0,19.0,19.0")]})
    stopped = review_with_thumbnails(pack_dir, workdir, make=False)
    page = workdir / "memory-review_C1.md"
    assert not page.exists(), "the page was written with the whole photo"
    assert stopped and "was not written" in stopped \
        and Path(paths[0]).name in stopped and ".venv" in stopped, stopped


def case_a_frame_whose_crop_is_made_still_renders(tmp):
    """GUARD (F22). The same frame, the crop made: the page is written."""
    pack_dir, workdir, _ids = two_lookalike_drafts(tmp)
    paths = draft_look_paths(pack_dir)
    write_detection_index(workdir, {paths[0]: [(0, 2, "1.0,1.0,9.0,9.0"),
                                               (1, 2, "9.0,9.0,19.0,19.0")]})
    stopped = review_with_thumbnails(pack_dir, workdir, make=True)
    assert stopped is None, stopped
    assert pm.CROP_DIR + "/" in (workdir / "memory-review_C1.md").read_text()


def case_a_frame_the_index_does_not_cover_renders_whole(tmp):
    """GUARD (F22), a DECISION (Lead 20260929), not a gap: a frame this dump's
    index says nothing about (another dump's sighting, F14) never had a crop to
    lose, so it renders whole as before, even when no crop could be made."""
    pack_dir, workdir, _ids = two_lookalike_drafts(tmp)
    other = tmp / "elsewhere" / "OTHER.JPG"
    write_detection_index(workdir, {str(other): [(0, 1, "1.0,1.0,9.0,9.0")]})
    stopped = review_with_thumbnails(pack_dir, workdir, make=False)
    assert stopped is None, stopped
    text = (workdir / "memory-review_C1.md").read_text()
    assert "[frame 1]" in text and pm.CROP_DIR + "/" not in text, text[-800:]


def case_a_crop_ref_on_pick_is_not_two_frames(tmp):
    """REPRODUCTION (F26). ⛔ FAILS on 5b320fb: `pick: 3.1` was read as frames
    3 AND 1, which would have filed another animal under the name."""
    text = ("**Q1 · Group it — Dog** — affects 2 file(s) / 1 batch(es)\n"
            "> - `pick:` 3.1   `who:` pet   `name:` Name-One\n")
    unit = pm.parse_review(text)[0]["picks"][0]
    assert 1 not in unit["numbers"], unit
    assert "one row per name" in (unit.get("crop_refusal") or ""), unit


def case_confirm_refuses_a_crop_ref_on_pick(tmp):
    """REPRODUCTION (F26). ⛔ FAILS on 5b320fb: `pick: 1.2` was read as frames
    1 AND 2, and --go named BOTH drafts `Name-Crop` (measured on 5b320fb)."""
    pack_dir, workdir, page, text, shared = shared_frame_page(tmp)
    page.write_text(text.replace(
        PICK_ROW, f"`pick:` {shared}.2   `who:` pet   `name:` Name-Crop", 1))
    _rc_dry, said_dry = confirm_page(pack_dir, workdir, go=False)
    _rc, said = confirm_page(pack_dir, workdir, go=True)
    assert "Name-Crop" not in json.dumps(
        [json.loads(p.read_text()) for p in
         (pack_dir / "photo-subjects").glob("*.json")]), "the name was written"
    assert "one row per name" in said_dry, said_dry[-600:]
    assert "one row per name" in said, said[-600:]


def case_one_photo_on_two_rows_parses_as_that_photo(tmp):
    """GUARD (F26). The working form: the same photo number on one row per
    name. Both rows keep the number, and neither is refused."""
    _pack_dir, _workdir, _page, text, shared = shared_frame_page(tmp)
    two = (f"`pick:` {shared}   `who:` pet   `name:` Name-A\n> - "
           f"`pick:` {shared}   `who:` pet   `name:` Name-B")
    units = pm.parse_review(text.replace(PICK_ROW, two, 1))[0]["picks"]
    got = [(u["numbers"], u["name"], u.get("crop_refusal")) for u in units]
    assert got == [([shared], "Name-A", None), ([shared], "Name-B", None)], got


def case_the_page_teaches_the_two_row_form(tmp):
    """REPRODUCTION (F26 wording). ⛔ FAILS on 5b320fb: the page said "one row
    per animal" beside `skip: 3.2`, and never showed the photo number on two
    rows, so the owner typed `pick: 3.1`."""
    _pack_dir, _workdir, _page, text, shared = shared_frame_page(tmp)
    assert f"`pick: {shared}` with one name, and a second row `pick: {shared}`" \
        in text, text[-1500:]
    assert "same photo number" in text, text[-800:]


def case_the_tile_shows_the_crop_not_the_whole_frame(tmp):
    """R3b — what the owner is asked is *which animal is this*, and the room
    around it is exactly the part that cannot answer that.

    ⛔ The crop REPLACES the frame rather than sitting beside it. Two images
    for one frame number would make the number ambiguous, and the number is
    what `pick:` takes."""
    pack_dir, workdir, ids = two_lookalike_drafts(tmp)
    paths = draft_look_paths(pack_dir)
    # The look's own source file, which the fixture never puts on disk: the
    # crop is re-derived through the SAME conversion photo_identity cropped,
    # so it needs a real image to convert. ⛔ Not `view_fixture.JPEG` — that
    # is a 68-byte stub that stands in for "a file exists here", and sips
    # returns nothing for it, which reads on the page as "this platform
    # cannot crop".
    from PIL import Image as _Image
    _Image.new("RGB", (200, 200), (90, 140, 200)).save(paths[0], "JPEG")
    write_detection_index(workdir, {paths[0]: [(0, 1, "10.0,10.0,120.0,120.0")]})
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    import re as _re
    text = (workdir / "memory-review_C1.md").read_text()
    linked = _re.findall(r"!\[\]\(([^)]+)\)", text)
    crops = [i for i in linked if i.startswith(pm.CROP_DIR + "/")]
    if not crops:
        # convert_to_thumbnail shells to sips/qlmanage and is macOS-only by
        # design (A22). Where it cannot run there is no crop to assert, and a
        # green tick would be a lie — so this half SKIPS, visibly.
        raise Skipped("no thumbnail conversion available on this platform")
    assert len(crops) == 1, crops
    assert not Path(crops[0]).is_absolute(), \
        "the page is written INTO the work dir; an absolute link renders blank"
    assert (workdir / crops[0]).is_file(), crops[0]
    frame_sample = [i for i in linked if i.endswith("B1_C0.jpg")]
    assert not frame_sample, \
        f"the whole frame is still linked beside its crop: {frame_sample}"
    log(f"the tile renders {crops[0]}, not the room around the animal")



# ---- R4: a shared frame logs every name and banks none of them ------------

def case_a_shared_frame_logs_both_names_and_banks_neither(tmp):
    """⭐ THE R4 MEMORIZE REPRODUCTION, and it is D-24 held at the write point.

    Two subjects in one frame is two names to log, never a frame to refuse
    (owner decision, 20260904). But `add_exemplar()` keys on `vec_ref`, the
    file's content sha — one photograph, one key, one subject — so promoting
    the same whole-frame vector under both ids puts each animal into the
    other's bank. That is exactly how 3 of the 5 exemplars an owner confirmed
    in UAT01 came out wrong.

    Both halves are asserted, and BOTH are the point:
      * every named subject gains an OBSERVATION, so the sighting is on the
        record and the folder can carry both names
      * no named subject gains an EXEMPLAR, and the audit says why

    ⛔ Before R4 this decision could not even be expressed: `apply_decisions`
    and `memorize_batch` read one `subject_id` off the value, so the second
    name was dropped and the FIRST one banked the shared frame silently — the
    contaminated-bank case with nothing in the audit to find it by."""
    pack_dir = make_pack(tmp)
    pack = open_pack(pack_dir)
    registry = psub.Registry(directory=pack_dir / "photo-subjects")
    one = registry.create_subject(name="Name-One", who="relation-word",
                                  kind="cat", active=["2029-01", None])
    two = registry.create_subject(name="Name-Two", who="relation-word",
                                  kind="cat", active=["2029-01", None])
    registry.save()

    workdir = tmp / "dump"
    report, index, samples = batch_fixture(workdir, 1, [(basis(0), 3),
                                                        (basis(1), 2)])
    shared = report["selected"][0]["path"]
    summary = apply_and_memorize(workdir, pack, report, index, samples,
                                 {shared: {"label": "Two cats",
                                           "subjects": [{"subject_id": one.subject_id},
                                                        {"subject_id": two.subject_id}]}})

    assert summary["ran"], summary
    assert summary["memorized"] == [], summary["memorized"]
    refused = {r["subject_id"] for r in summary["refused"]}
    assert refused == {one.subject_id, two.subject_id}, summary["refused"]
    assert all("cannot bank" in r["why"] for r in summary["refused"]), \
        summary["refused"]

    reloaded = psub.load(pack=open_pack(pack_dir))
    for sid in (one.subject_id, two.subject_id):
        subject = reloaded.get(sid)
        assert subject.exemplars == [], \
            f"{sid} banked a frame it shares with another subject: {subject.exemplars}"
        assert 1 in subject.record.get("observed_in", []), subject.record
        assert subject.record.get("obs_count") == 1, subject.record
    log("2 names logged, 0 exemplars banked, and the audit says which key "
        "could not hold both")


def case_a_solo_frame_still_banks_its_one_exemplar(tmp):
    """⛔ THE CONTROL, and without it the case above proves nothing: a
    memorize loop that had simply stopped banking would pass it. Same pack,
    same batch, same code path — one name instead of two."""
    pack_dir = make_pack(tmp)
    pack = open_pack(pack_dir)
    registry = psub.Registry(directory=pack_dir / "photo-subjects")
    only = registry.create_subject(name="Name-One", who="relation-word",
                                   kind="cat", active=["2029-01", None])
    registry.save()

    workdir = tmp / "dump"
    report, index, samples = batch_fixture(workdir, 1, [(basis(0), 3),
                                                        (basis(1), 2)])
    looked = report["selected"][0]["path"]
    summary = apply_and_memorize(
        workdir, pack, report, index, samples,
        {looked: {"label": "Cat", "subjects": [{"subject_id": only.subject_id}]}})
    assert len(summary["memorized"]) == 1, summary
    assert summary["refused"] == [], summary["refused"]
    reloaded = psub.load(pack=open_pack(pack_dir))
    assert len(reloaded.get(only.subject_id).exemplars) == 1, \
        reloaded.get(only.subject_id).exemplars
    log("one name, one exemplar — the bank still works")


def case_two_unnamed_animals_open_one_draft_not_two(tmp):
    """A cluster has ONE centroid, and a draft is opened from it. Two unnamed
    animals in one frame therefore still open one draft — drafting the same
    geometry twice would put one cloud of vectors in the store under two
    records and ask the owner the same question twice.

    ⚠️ STATED, not hidden: the second animal is not separable yet. It is on
    the label, it names the folder, and it becomes its own draft when the
    composite key `<sha>#<det_index>` lands (R3b's own card). Bounded on
    purpose — a case that expected two drafts would be asking for a mechanism
    nobody has built."""
    pack_dir = make_pack(tmp)
    pack = open_pack(pack_dir)
    workdir = tmp / "dump"
    report, index, samples = batch_fixture(workdir, 1, [(basis(0), 3),
                                                        (basis(1), 2)])
    rep = report["selected"][0]["path"]
    summary = apply_and_memorize(workdir, pack, report, index, samples,
                                 {rep: {"label": "Two cats",
                                        "subjects": [{"subject_kind": "cat"},
                                                     {"subject_kind": "cat"}]}})
    assert summary["drafts_total"] == 1, summary
    assert len(summary["drafted"]) == 1, summary["drafted"]
    log("2 unidentified animals, 1 draft, 1 question")



# ------------------------------------------------- D-21: label a draft ------
#
# The measured failure: eleven groups of one species all rendered
# `an unnamed Cat` — in the tile list, and up to seventeen times inside a
# single Scene cell — and the owner could only hold them apart by position in
# a list, while the engine held a first-seen date it did not print.
#
# ⛔ These cases assert a DISCRIMINATOR, never a guessed name. A case that
# made the label say what the animal is would be the opposite fix.


def two_drafts_over_months(tmp):
    """Two recurring subjects of one kind, first seen two months apart.

    Subject A is in batches 1-2, subject B in batches 2-3, so both are drafts
    with more than one sighting and their `active` ranges start on different
    months — which is the only thing that can tell them apart on the page."""
    pack_dir = make_pack(tmp)
    pack = open_pack(pack_dir)
    workdir = tmp / "dump"
    write_batches(workdir, 3)
    members = {1: [(basis(0), 4)],
               2: [(basis(0), 4), (basis(1), 4)],
               3: [(basis(1), 4)]}
    for batch in (1, 2, 3):
        report, index, samples = batch_fixture(
            workdir, batch, members[batch], month=f"2029-0{batch}")
        apply_and_memorize(
            workdir, pack, report, index, samples,
            {e["path"]: {"label": "Cat", "subject_kind": "cat"}
             for e in report["selected"]})
    return pack_dir, workdir




def case_two_drafts_of_one_kind_do_not_share_one_label(tmp):
    """The reproduction. Before D-21 both tiles read the same seven
    characters and the owner had list position and nothing else."""
    pack_dir, workdir = two_drafts_over_months(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    drafts = registry.drafts
    assert len(drafts) == 2, [d.subject_id for d in drafts]
    starts = {(d.record.get("active") or [None])[0] for d in drafts}
    assert len(starts) == 2, starts

    pack = open_pack(pack_dir)
    rmsg = photo_profile.review_messages(pack.profile)
    shown = [pm.subject_display(d, pack.profile, rmsg) for d in drafts]
    assert len(set(shown)) == 2, shown
    assert all(any(start in label for start in starts) for label in shown), shown

    text = review_text(pack_dir, workdir, checkpoint=3).read_text()
    tiles = [ln for ln in text.splitlines() if "file(s) /" in ln and "**" in ln]
    assert len(tiles) >= 2, text
    labels = [ln.split("·")[1].strip() for ln in tiles]
    assert len(set(labels)) == len(labels), labels
    log(f"two drafts, two labels: {shown}")


def case_the_scene_column_distinguishes_its_subjects(tmp):
    """The half the tile line could not fix. A tile already printed its file
    and batch counts; the Scene cell prints the label ALONE, which is why the
    discriminator had to go into the label rather than beside it."""
    pack_dir, workdir = two_drafts_over_months(tmp)
    pack = open_pack(pack_dir)
    rmsg = photo_profile.review_messages(pack.profile)
    registry = psub.load(pack=pack)
    rows = pm.build_rows(workdir, registry, pack.profile, rmsg)
    both = [r for r in rows if r["scene"].count("unnamed") > 1]
    assert both, [r["scene"] for r in rows]
    for row in both:
        # the two subjects in one cell are two different strings
        parts = [p.strip() for p in row["scene"].split(" · ")[0].split(", ")]
        assert len(parts) == len(set(parts)), row["scene"]
    log(f"scene cell holds distinct labels: {both[0]['scene']}")


def case_a_draft_with_no_capture_date_keeps_the_bare_marker(tmp):
    """A control, and a real case rather than a hypothetical: `active` stays
    open when nothing in a group carried a capture date. Inventing a date to
    fill the slot is the one thing an honesty marker may never do."""
    pack_dir, workdir = two_drafts_over_months(tmp)
    pack = open_pack(pack_dir)
    rmsg = photo_profile.review_messages(pack.profile)
    registry = psub.load(pack=pack)
    draft = registry.drafts[0]
    draft.record["active"] = [None, None]
    word = photo_profile.scene_classes(pack.profile)["cat"]
    bare = rmsg["review_unnamed_subject"].format(kind=word)
    got = pm.subject_display(draft, pack.profile, rmsg)
    assert got == bare, (got, bare)
    log(f"a dateless draft renders {got!r}")


def case_the_evidence_wraps_the_packs_own_marker(tmp):
    """⛔ The rule that decided the shape. The evidence WRAPS the pack's
    marker instead of restating it, so a pack that translated
    `review_unnamed_subject` — and nothing else — keeps its own word. A
    second copy of the marker inside the new string would silently
    untranslate every pack that answered the first one."""
    pack_dir, workdir = two_drafts_over_months(tmp)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["review_messages"] = {"review_unnamed_subject": "one unnamed {kind}"}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))
    pack = open_pack(pack_dir)
    rmsg = photo_profile.review_messages(pack.profile)
    registry = psub.load(pack=pack)
    shown = [pm.subject_display(d, pack.profile, rmsg) for d in registry.drafts]
    assert all(label.startswith("one unnamed") for label in shown), shown
    assert all("first seen" in label for label in shown), shown
    log(f"the pack's own marker survives the evidence: {shown}")



# ------------------------------------- D-23: the page keeps its promise -----
#
# MEASURED before this was built, and the measurement decided the fix. A page
# suppressed two drafts for the tile ceiling, named both in writing as "still
# ai-drafted, still askable", promised in its own paragraph that "nothing was
# decided about them" — and the post-confirm sweep then absorbed both. The
# defect log offered two repairs: stop the sweep touching a suppressed draft,
# or stop the page promising it will not.
#
# ⛔ The SWEEP is not the defect, and the fixture below is why. At a tile
# ceiling the drafts the sweep exists to close are exactly the ones the page
# suppressed — a rendered draft gets answered instead — so here it absorbs 2
# of 2 suppressed and 0 rendered. Refuse it those and it absorbs nothing,
# which is the state OA-26 recorded as the gap. So the PAGE was changed: the
# promise now says what can still change, and the next page lists what did.


def three_drafts_one_tile(tmp):
    """Three drafts close enough for the sweep, far enough to stay separate,
    and a tile ceiling of 1 — so answering the page leaves two open drafts
    that the page has told the owner it did not decide about."""
    pack_dir = make_pack(tmp)
    pack = open_pack(pack_dir)
    workdir = tmp / "dump"
    write_batches(workdir, 3)
    vecs = [basis(0),
            unit(basis(0) + 0.67 * basis(1)),
            unit(basis(0) + 0.67 * basis(2))]
    for batch, vec in enumerate(vecs, 1):
        report, index, samples = batch_fixture(workdir, batch, [(vec, 3)],
                                               month=f"2029-0{batch}")
        apply_and_memorize(workdir, pack, report, index, samples,
                           {report["selected"][0]["path"]:
                            {"label": "Cat", "subject_kind": "cat"}})
    registry = psub.load(pack=open_pack(pack_dir))
    assert len(registry.drafts) == 3, [d.subject_id for d in registry.drafts]
    registry.data.setdefault("defaults", {})["tiles_per_round"] = 1
    registry.data["defaults"]["sweep_absorb_tau"] = 0.80
    registry.save()
    return pack_dir, workdir


def case_the_page_does_not_promise_what_the_sweep_can_undo(tmp):
    """The REPRODUCTION, on the sentence. Before D-23 the page said
    "Nothing was decided about them and nothing was skipped" over drafts the
    confirm was about to close."""
    pack_dir, workdir = three_drafts_one_tile(tmp)
    text, _said = review(pack_dir, workdir, 1)
    deferred = [ln for ln in text.splitlines()
                if "not on this page at all" in ln]
    assert len(deferred) == 1, text
    assert "Nothing was decided about them" not in deferred[0], deferred[0]
    pack = open_pack(pack_dir)
    rmsg = photo_profile.review_messages(pack.profile)
    assert rmsg["review_deferred_sweep_note"] in text, text
    # and the per-subject comment carries the same qualification
    comment = [ln for ln in text.splitlines() if "tile ceiling" in ln]
    assert len(comment) == 2, comment
    assert all("which the next checkpoint lists" in ln for ln in comment), comment
    log("the deferred paragraph and both suppression lines say what can change")


def case_a_suppressed_draft_the_sweep_closed_is_listed_next_time(tmp):
    """The REPRODUCTION, on the record. The two drafts this page suppressed
    are absorbed by the confirm, and the NEXT page names them, says where each
    went and says how to get them back. Before D-23 the only trace outside the
    audit trail was one console line at confirm time."""
    pack_dir, workdir = three_drafts_one_tile(tmp)
    text, _said = review(pack_dir, workdir, 1)
    rendered = [i for b in pm.parse_review(text) for i in b["subject_ids"]]
    assert len(rendered) == 1, rendered
    comment = text.split("<!--")[-1]
    suppressed = sorted({token for token in comment.replace("\n", " ").split()
                         if token.rstrip(":").startswith("subj-")})
    suppressed = [sid.rstrip(":") for sid in suppressed]
    assert len(suppressed) == 2 and rendered[0] not in suppressed, suppressed

    path = workdir / "memory-review_C1.md"
    path.write_text(fill_pick(path.read_text(), [1], who="pet", name="Named"))
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, file=None, sync=False, by="Test Operator", go=True))
    assert rc == 0
    after = psub.load(pack=open_pack(pack_dir))
    absorbed = sorted(s.subject_id for s in after.subjects
                      if s.status == psub.STATUS_ABSORBED)
    # ⭐ the measurement the fix turns on: every absorb is a SUPPRESSED draft
    assert absorbed == suppressed, (absorbed, suppressed)

    later, _said = review(pack_dir, workdir, 2)
    assert "Recognised without asking" in later, later
    assert "checkpoint C1" in later, later
    for sid in absorbed:
        assert sid in later, (sid, later)
    assert rendered[0] in later, later          # where they went
    assert "withdraw the name" in later, later  # and how to undo it
    log(f"{len(absorbed)} silent absorb(s) listed on the next page, "
        "with their destination and the undo")


def case_the_absorbed_list_is_one_checkpoint_not_a_ledger(tmp):
    """A guard on the shape. The section reports the LAST answer's sweep, not
    every absorb the pack holds — a list that accumulated would re-raise a
    decision the owner has already read and let go, and by C10 the page would
    open with nine rounds of settled bookkeeping."""
    pack_dir, workdir = three_drafts_one_tile(tmp)
    review(pack_dir, workdir, 1)
    path = workdir / "memory-review_C1.md"
    path.write_text(fill_pick(path.read_text(), [1], who="pet", name="Named"))
    pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, file=None, sync=False, by="Test Operator", go=True))
    registry = psub.load(pack=open_pack(pack_dir))
    at, rows = pm.absorbed_since(registry, checkpoint=2)
    assert at == 1 and len(rows) == 2, (at, rows)
    # C1 is not "earlier than C1", so the page that caused the absorb never
    # reports it — that page was written before the confirm ran
    assert pm.absorbed_since(registry, checkpoint=1) == (None, []), \
        "the page that caused the absorb reported it"
    log(f"C2 lists C1's {len(rows)} absorb(s); C1 lists none")


def case_a_page_with_no_sweep_behind_it_shows_no_section(tmp):
    """A guard: the section is a report, so it stays away when there is
    nothing to report. An owner shown an empty "recognised without asking"
    heading learns a false thing about their own memory."""
    pack_dir, workdir = k_batch_run(tmp, 2)
    text, _said = review(pack_dir, workdir, 1)
    assert "Recognised without asking" not in text, text
    registry = psub.load(pack=open_pack(pack_dir))
    assert pm.absorbed_since(registry, checkpoint=9) == (None, []), "reported"
    log("no sweep, no section")



# --------------------------- card (c): an absorb says which space decided it -
#
# LL-PHO-105 — an accept an owner reads is never quoted without its space.
# `subject_verdict_spaces` said `clip` for everything until 3d229f0, and every
# subject verdict in the first user test was CLIP while being read as
# identity. The absorb list D-23 added is a surface an owner reads accepts
# from, so it has to carry one.
#
# ⛔ MEASURED, and it changes how the output reads: `sweep_absorb` is
# CLIP-ONLY — `vectors_for()` + `draft_centroid()`, no identity branch.
# `confirmed_match` has one (`_confirmed_match_identity`) and is a DIFFERENT
# function, so A19's "the absorption path IS the identity space" is about
# incoming clusters and not about this sweep. The first thing this ships is
# the word `clip` on every new row: the truth becoming visible, not a change.


def swept_pack(tmp):
    """Run the D-23 fixture through to a real sweep. -> (pack_dir, workdir,
    [the absorbed subject ids])."""
    pack_dir, workdir = three_drafts_one_tile(tmp)
    review(pack_dir, workdir, 1)
    path = workdir / "memory-review_C1.md"
    path.write_text(fill_pick(path.read_text(), [1], who="pet", name="Named"))
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, file=None, sync=False, by="Test Operator", go=True))
    assert rc == 0, rc
    registry = psub.load(pack=open_pack(pack_dir))
    ids = sorted(s.subject_id for s in registry.subjects
                 if s.status == psub.STATUS_ABSORBED)
    # ⛔ ASSERT THE FIXTURE WORKED before asserting anything about behaviour.
    # A sweep that absorbed nothing would make every case below vacuously
    # true, and a fixture that silently does nothing is a null result in test
    # clothing.
    assert len(ids) == 2, f"the fixture swept nothing: {ids}"
    return pack_dir, workdir, ids


def case_a_swept_absorb_names_the_space_it_was_decided_in(tmp):
    """The REPRODUCTION. Before card (c) the row said what was absorbed and
    where it went, and nothing at all about what decided it."""
    pack_dir, workdir, ids = swept_pack(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    # the fixture's own precondition: the STORAGE half really recorded a space
    stored = {i: psub.absorbed_space(registry.get_literal(i).record) for i in ids}
    assert set(stored.values()) == {psub.SPACE_CLIP}, stored

    at, rows = pm.absorbed_since(registry, checkpoint=2)
    assert at == 1 and len(rows) == 2, (at, rows)
    assert all(r["space"] == psub.SPACE_CLIP for r in rows), rows

    pack = open_pack(pack_dir)
    rmsg = photo_profile.review_messages(pack.profile)
    text, _said = review(pack_dir, workdir, 2)
    word = rmsg["review_absorbed_space_clip"]
    assert text.count(word) == 2, (word, text)
    assert rmsg["review_absorbed_space_unrecorded"] not in text, text
    log(f"both swept rows carry {word!r}")


def case_an_unrecorded_space_is_a_word_not_a_dash(tmp):
    """⛔ The rule the card turns on. A row written before the space was
    stored cannot be given one, and a dash reads as a field that failed to
    render — which leaves the reader exactly where LL-PHO-105 found them."""
    pack_dir, workdir, ids = swept_pack(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    for i in ids:
        registry.get_literal(i).record["absorbed"].pop("space", None)
    registry.save()
    # the precondition, asserted: the space really is gone from the record
    reloaded = psub.load(pack=open_pack(pack_dir))
    stored = {i: psub.absorbed_space(reloaded.get_literal(i).record) for i in ids}
    assert set(stored.values()) == {None}, stored

    pack = open_pack(pack_dir)
    rmsg = photo_profile.review_messages(pack.profile)
    text, _said = review(pack_dir, workdir, 2)
    unrecorded = rmsg["review_absorbed_space_unrecorded"]
    assert text.count(unrecorded) == 2, (unrecorded, text)
    assert rmsg["review_absorbed_space_clip"] not in text, \
        "an unrecorded space was rendered as clip"
    # ⚠️ the ROWS, not every line holding the words: the intro paragraph says
    # "withdraw the name it went to" and would be counted as a third row
    body = [ln for ln in text.splitlines()
            if ln.startswith("> **") and "went to" in ln]
    assert len(body) == 2 and all("(—)" not in ln for ln in body), body
    log(f"an unrecorded space renders {unrecorded!r}")


def case_the_space_word_is_never_guessed(tmp):
    """The MUTANT guard, at the unit. The wrong fix this card names is
    resolving a missing space to `clip` because it probably was — a space
    nobody measured, presented as if somebody had."""
    pack_dir, _workdir = three_drafts_one_tile(tmp)
    rmsg = photo_profile.review_messages(open_pack(pack_dir).profile)
    got = {value: pm.space_word(value, rmsg)
           for value in (psub.SPACE_CLIP, psub.SPACE_IDENTITY, None, "", "nonsense")}
    assert got[psub.SPACE_CLIP] == rmsg["review_absorbed_space_clip"], got
    assert got[psub.SPACE_IDENTITY] == rmsg["review_absorbed_space_identity"], got
    # ⛔ every shape that is not one of the two known spaces says so, and
    # none of them borrows the other's word
    for value in (None, "", "nonsense"):
        assert got[value] == rmsg["review_absorbed_space_unrecorded"], (value, got)
    assert len({got[psub.SPACE_CLIP], got[psub.SPACE_IDENTITY],
                got[None]}) == 3, got
    log(f"space words: {got}")


def case_an_identity_absorb_would_say_identity(tmp):
    """A guard on the OTHER value, which today's sweep cannot produce —
    `sweep_absorb` is CLIP-only. Written against the stored field rather than
    a fake identity branch: the renderer's job is to say what the row says,
    and an identity-capable sweep must not need this file changed as well.

    ⛔ NOT a claim that identity absorbs happen. It is a claim that if one is
    ever recorded, the page will not call it clip."""
    pack_dir, workdir, ids = swept_pack(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    registry.get_literal(ids[0]).record["absorbed"]["space"] = psub.SPACE_IDENTITY
    registry.save()
    reloaded = psub.load(pack=open_pack(pack_dir))
    assert psub.absorbed_space(reloaded.get_literal(ids[0]).record) \
        == psub.SPACE_IDENTITY, "the fixture did not take"

    rmsg = photo_profile.review_messages(open_pack(pack_dir).profile)
    text, _said = review(pack_dir, workdir, 2)
    assert text.count(rmsg["review_absorbed_space_identity"]) == 1, text
    assert text.count(rmsg["review_absorbed_space_clip"]) == 1, text
    log("one identity row and one clip row, told apart")


def case_the_space_words_come_from_the_pack(tmp):
    """Rule 8, and the reason these are three KEYS rather than three literals
    in the renderer: a pack that translated `review_absorbed_row` would
    otherwise get an English space interpolated into its own translated
    sentence — a half-translated line, which reads as deliberate."""
    pack_dir, workdir, _ids = swept_pack(tmp)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["review_messages"] = {"review_absorbed_space_clip": "SPACE-WORD"}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))
    text, _said = review(pack_dir, workdir, 2)
    assert text.count("SPACE-WORD") == 2, text
    assert "clip space" not in text, text
    log("the space word is the pack's to translate")


def case_an_owner_answered_absorb_is_never_in_this_section(tmp):
    """⛔ It has no space BECAUSE NO GEOMETRY RAN, which is a different thing
    from a space nobody recorded — and this section is about decisions nobody
    typed, so the row does not belong here at all.

    ⛔ The exclusion is EXPLICIT, on `answered`, and this case exists because
    it used to be accidental. SNS-16 writes `src` as `"<page>.md Q<n>"`, which
    DOES carry the page; only the `$` anchor on CHECKPOINT_IN_NAME kept it
    out. The two assertions below measure exactly that: the src matches when
    the anchor is dropped, and the row is skipped anyway."""
    pack_dir, workdir, ids = swept_pack(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    typed = registry.get_literal(ids[0])
    typed.record["absorbed"] = {"at": "2029-04-01", "by": "Test Operator",
                                "src": "memory-review_C1.md Q1",
                                "was": psub.STATUS_DRAFT, "answered": True}
    typed.record.pop("absorbed_at_score", None)
    registry.save()
    reloaded = psub.load(pack=open_pack(pack_dir))
    record = reloaded.get_literal(ids[0]).record

    # the fixture's preconditions, both measured rather than assumed
    assert psub.absorbed_space(record) is None, record
    assert "memory-review_C1.md" in record["absorbed"]["src"], \
        "the fixture's src does not carry a page — the case proves nothing"
    assert pm.CHECKPOINT_IN_NAME.search(record["absorbed"]["src"]) is None, \
        "the anchored pattern now matches; the explicit test is all that is left"

    at, rows = pm.absorbed_since(reloaded, checkpoint=2)
    assert [r["subject_id"] for r in rows] == [ids[1]], rows
    text, _said = review(pack_dir, workdir, 2)
    assert ids[0] not in text.split("Recognised without asking")[-1], text
    log("an owner-answered absorb stays out, on `answered` and not on a regex")



# ------------------- D-27: the name qualifier, said before it is needed -----
#
# `confirm` refuses a repeated name until `same` or `distinct` is supplied,
# and that requirement is SOUND and stays: a repeated name genuinely is
# ambiguous — the same animal, or a second animal with the same name? — and
# only the owner can say. The defect was that the page offered a blank
# `name:` row, said nothing about it, and the owner discovered the rule by
# having their answer refused.
#
# ⛔ These cases assert the NOTICE, never a relaxed refusal. A case that let
# a bare repeated name through would be the opposite fix.


def named_then_still_asking(tmp):
    """A pack holding one confirmed name, and a page that still has questions
    on it. -> (pack_dir, workdir, the name).

    ⚠️ The sweep is held off deliberately (`sweep_absorb_tau` 0.99): left at
    its default it absorbs the two remaining drafts, the next checkpoint has
    nothing to ask, and a notice that only renders beside answer rows would
    have nowhere to appear — the fixture, not the engine, would decide the
    result."""
    pack_dir, workdir = three_drafts_one_tile(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    registry.data["defaults"]["sweep_absorb_tau"] = 0.99
    registry.save()
    review(pack_dir, workdir, 1)
    path = workdir / "memory-review_C1.md"
    path.write_text(fill_pick(path.read_text(), [1], who="pet", name="Named"))
    rc = pm.cmd_confirm(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, file=None, sync=False, by="Test Operator", go=True))
    assert rc == 0, rc
    # ⛔ both preconditions asserted: a name really is taken, and the next
    # page really does still ask something
    registry = psub.load(pack=open_pack(pack_dir))
    # ⛔ read from the REGISTRY, not through `taken_names()`. The precondition
    # has to hold on the unfixed engine too, or the reproduction reports a
    # missing function instead of the behaviour that was wrong.
    confirmed = sorted({s.name for s in registry.subjects
                        if s.name and s.status == psub.STATUS_CONFIRMED})
    assert confirmed == ["Named"], confirmed
    assert len(registry.drafts) == 2, [d.subject_id for d in registry.drafts]
    return pack_dir, workdir, "Named"


def case_the_page_states_the_qualifier_before_the_owner_needs_it(tmp):
    """The REPRODUCTION. The rule was only ever stated in the refusal, which
    arrives after the answer has been written and submitted."""
    pack_dir, workdir, name = named_then_still_asking(tmp)
    text, _said = review(pack_dir, workdir, 2)
    assert pm.parse_review(text), "the fixture's page asks nothing"
    line = [ln for ln in text.splitlines() if "Already the name of" in ln]
    assert len(line) == 1, text
    # the name, and BOTH answers, on the page and before any answer is typed
    assert name in line[0], line[0]
    assert f"{name} {pm.SAME_TOKEN}" in line[0], line[0]
    assert f"{name} {pm.DISTINCT_TOKEN}" in line[0], line[0]
    log(f"the page says it up front: {line[0][:80]}...")


def case_a_pack_with_no_confirmed_name_is_not_warned(tmp):
    """⛔ The MUTANT guard, and the reason the notice is conditional. With
    nothing to collide with the rule cannot fire, so an unconditional notice
    is noise on the one page a new owner already finds longest — and it warns
    about a refusal they cannot earn."""
    pack_dir, workdir = three_drafts_one_tile(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    # the precondition, asserted, and without the new API for the reason above
    assert not [s for s in registry.subjects
                if s.name and s.status == psub.STATUS_CONFIRMED]
    text, _said = review(pack_dir, workdir, 1)
    assert pm.parse_review(text), "the fixture's page asks nothing"
    assert "Already the name of" not in text, text
    log("a first run is not warned about a collision it cannot have")


def case_only_confirmed_names_are_called_taken(tmp):
    """`taken_names()` reads a POSITIVE whitelist, for the reason the header
    count does: `is_draft` covers two statuses out of five, so its negation
    counts `rejected`, `superseded` and `absorbed` records as names the owner
    chose. A rejected record holds no name at all, and warning about a name
    nobody can collide with is the noise this notice exists to avoid."""
    pack_dir, workdir, name = named_then_still_asking(tmp)
    registry = psub.load(pack=open_pack(pack_dir))
    before = pm.taken_names(registry)
    assert before == [name], before
    # withdraw it: the subject stops being confirmed, so the name stops being
    # taken and the notice has nothing left to warn about
    subject = next(s for s in registry.subjects if s.name == name)
    subject.record["status"] = psub.STATUS_REJECTED
    registry.save()
    after = psub.load(pack=open_pack(pack_dir))
    assert pm.taken_names(after) == [], pm.taken_names(after)
    text, _said = review(pack_dir, workdir, 3)
    assert "Already the name of" not in text, text
    log("a name that is no longer confirmed is no longer taken")


def case_the_notice_is_the_packs_sentence(tmp):
    """Rule 8. The sentence is the owner's language and the two TOKENS are
    not: `same` and `distinct` are parsed, so they are ASCII and arrive as
    fields — a pack translates around them and never spells them."""
    pack_dir, workdir, _name = named_then_still_asking(tmp)
    profile = json.loads((pack_dir / "photo-profile.json").read_text())
    profile["review_messages"] = {
        "review_name_taken": "TAKEN {names} :: {example} {same} / {distinct}"}
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile, indent=1))
    text, _said = review(pack_dir, workdir, 2)
    line = [ln for ln in text.splitlines() if ln.startswith("TAKEN ")]
    assert len(line) == 1, text
    assert pm.SAME_TOKEN in line[0] and pm.DISTINCT_TOKEN in line[0], line[0]
    assert "Already the name of" not in text, text
    log(f"the pack's own sentence, engine tokens intact: {line[0]}")



def case_a_rejection_states_why_it_was_typed(workdir):
    """⭐ THE U2-10 REPRODUCTION. `skip:` was the only rejection, so a bonfire
    the detector scored as a cat and a neighbour's cat that simply is not the
    owner's were recorded IDENTICALLY. They are two facts with opposite
    futures. The owner must be able to say which one they mean.

    ⛔ FAILS on the pre-C12 parser, which reads no basis off the row."""
    page = ("**Q1 · a Cat**\n"
            "> `skip:` 3,4 confirm not-a-subject\n")
    block = pm.parse_review(page)[0]
    assert block["skip_armed"], "the arming word must still be required"
    assert block["skip_numbers"] == [3, 4], \
        f"the token must not eat the frame numbers, got {block['skip_numbers']}"
    assert block["skip_basis"] == pm.BASIS_NOT_A_SUBJECT, \
        f"'not an animal at all' must be readable, got {block['skip_basis']!r}"


def case_a_plain_rejection_is_the_weaker_claim(workdir):
    """GUARD, and the direction that matters: a `skip:` row with no token
    means *not mine*, the claim every rejection written before this made.
    Reading a bare row as the STRONGER claim would invent a judgement the
    owner never made, on every record already on disk."""
    block = pm.parse_review("**Q1 · a Cat**\n> `skip:` 3 confirm\n")[0]
    assert block["skip_basis"] == pm.BASIS_NOT_MINE, \
        f"an unqualified rejection is 'not mine', got {block['skip_basis']!r}"
    no_skip = pm.parse_review("**Q1 · a Cat**\n> `pick:` 1 `who:` pet\n")[0]
    assert no_skip["skip_basis"] is None, \
        "no skip row at all states nothing — a third state, not a default"


def case_the_arming_word_is_still_required(workdir):
    """GUARD. The basis QUALIFIES a rejection; it can never arm one. A row
    carrying the basis but not `confirm` is still an unarmed row, or the new
    token becomes a second way to reject by accident."""
    block = pm.parse_review("**Q1 · a Cat**\n> `skip:` 3 not-a-subject\n")[0]
    assert not block["skip_armed"], \
        "the basis must not arm a rejection on its own"
    assert block["skip_basis"] == pm.BASIS_NOT_A_SUBJECT


def case_an_old_rejection_reads_as_not_mine(workdir):
    """GUARD for every pack already on disk. A `rejected` record written
    before this build states no basis; the renderer must read it as the
    weaker claim rather than as missing data."""
    rmsg = photo_profile.review_messages({})
    old = {"subject_id": "subj-0001", "files": 12, "batches": 1,
           "at": "2029-01-01", "centroid": True,
           "basis": pm.BASIS_NOT_MINE}
    fire = {**old, "subject_id": "subj-0002",
            "basis": pm.BASIS_NOT_A_SUBJECT}
    page = "\n".join(pm.render_representations(
        {"remembered": [], "rejected": [old, fire]}, rmsg))
    assert rmsg["review_rejected_basis_not_mine"] in page, \
        "an unqualified rejection must say what it was"
    assert rmsg["review_rejected_basis_not_a_subject"] in page, \
        "a 'not an animal' rejection must render DIFFERENTLY — the whole "\
        "defect is that the two read identically"
    assert (rmsg["review_rejected_basis_not_mine"]
            != rmsg["review_rejected_basis_not_a_subject"])


# =============================================================== F10 ========

def write_manifest(workdir, rows):
    """A scan's `manifest.csv`, holding only the columns the page reads."""
    with open(Path(workdir) / "manifest.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["SourceFile", "DateTimeOriginal",
                                               "GPSPosition"])
        writer.writeheader()
        for path, gps in rows.items():
            writer.writerow({"SourceFile": path,
                             "DateTimeOriginal": "2029:03:04 10:00:00",
                             "GPSPosition": gps})


def add_homes(pack_dir, homes):
    path = Path(pack_dir) / "photo-profile.json"
    profile = json.loads(path.read_text())
    profile["home_locations"] = homes
    path.write_text(json.dumps(profile, indent=1))


def where_by_batch(text):
    """-> {batch number: the phrase on its frame's line}, read through the
    rendered page's own `RE_IMG` — so the case proves the markdown AND the
    parse. (Not through `frames:`: this file's refs are not hex.)"""
    import re as _re
    import photo_review_page as rp
    out = {}
    for line in text.split("### Remembered")[0].splitlines():
        found = rp.RE_IMG.match(line)
        if found:
            batch = int(_re.search(r"batch-(\d+)", found.group(1)).group(1))
            out[batch] = (_re.sub(r"\s*<!-- web: .*? -->", "", found.group(3))
                          if found.lastindex >= 3 and found.group(3) else None)
    return out


def web_by_batch(text):
    """-> {batch number: the web word marked on its frame's line}."""
    import re as _re
    import photo_review_page as rp
    out = {}
    for line in text.split("### Remembered")[0].splitlines():
        found = rp.RE_IMG.match(line)
        if found:
            batch = int(_re.search(r"batch-(\d+)", found.group(1)).group(1))
            out[batch] = rp.web_where(found.group(3))
    return out


HOMES_F10 = [{"label": "Home-A", "lat": 10.0, "lon": 20.0},
             {"lat": 11.0, "lon": 21.0},
             # Not yet lived in on the photo's date: must not be measured from.
             {"label": "Home-Later", "lat": 10.5, "lon": 20.0,
              "valid_from": "2030"}]


def case_every_frame_says_where_it_was_taken(tmp):
    """F10. Each frame carries its OWN place: the owner's label for the home it
    was taken at, or the distance from the nearest one — never the batch's,
    never a coordinate. UAT01-4 nearly named a relative's lookalike cat and
    two village strays because the page said nothing about place."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=4)
    add_homes(pack_dir, HOMES_F10)
    raw = {str(workdir / "B1_C0_000.JPG"): "10.0010 20.0010",
           str(workdir / "B2_C0_000.JPG"): "11.0010 21.0000",
           str(workdir / "B3_C0_000.JPG"): "10.5000 20.0000",
           # Samsung's no-fix video: null island is no location, not a place.
           str(workdir / "B4_C0_000.JPG"): "0 0"}
    write_manifest(workdir, raw)
    text = review_text(pack_dir, workdir).read_text()
    got = where_by_batch(text)
    assert len(got) == 4 and all(got.values()), \
        f"a frame on the page says nothing about where it was taken: {got}"
    rmsg = photo_profile.REVIEW_VOCAB["en"]
    want = {1: rmsg["review_frame_where_home"].format(home="Home-A"),
            # the NEAREST home has no label: said so, never Home-A's name
            2: rmsg["review_frame_where_home_unlabelled"],
            # Home-Later sits on this point but is not in force in 2029
            3: rmsg["review_frame_where_away"].format(km="55.6", home="Home-A"),
            4: rmsg["review_frame_where_none"]}
    assert got == want, got
    for value in raw.values():
        for part in value.split():
            if part != "0":
                assert part not in text, f"coordinate {part} on the page"


def case_a_represented_frame_says_where_too(tmp):
    """F10 on the other frame surface — a remembered subject's worst frame is
    a name check, and the same lookalike trap applies. With no scan in the
    look's work dir the answer is its own sentence, never a borrowed place."""
    import photo_review_page as rp
    pack_dir, workdir, _sid, _refs = two_looks_apart(tmp)
    # The fixture memorized at home (Q8-a); the scan goes for this half.
    (workdir / "manifest.csv").unlink()
    text = review_text(pack_dir, workdir).read_text()
    shown = rp.parse_review(text)["recheck"]
    assert shown and shown[0].get("where"), \
        f"the re-presented frame says nothing about where it was taken: {shown}"
    rmsg = photo_profile.REVIEW_VOCAB["en"]
    assert list(shown[0]["where"].values()) == \
        [rmsg["review_frame_where_unknown"]], shown
    add_homes(pack_dir, HOMES_F10)
    write_manifest(workdir, {str(workdir / f"B{b}_C0_000.JPG"): "10.5000 20.0000"
                             for b in (1, 2)})
    text = review_text(pack_dir, workdir, checkpoint=2).read_text()
    shown = rp.parse_review(text)["recheck"]
    assert rmsg["review_frame_where_away"].format(km="55.6", home="Home-A") \
        in text.split("### Remembered")[1], text
    # U2-13 — the web page reads only the home/away word.
    assert list(shown[0].get("where", {}).values()) == \
        [rmsg["review_frame_where_web_away"]], shown


# =============================================================== F11 ========

def case_split_children_keep_their_picked_frames(tmp):
    """F11. A split is the checkpoint's own recommended remedy, and it used to
    cost the name: `confirm` recorded each picked frame under the PARENT draft
    id, the parent is superseded by the split, and every picked frame of a
    split draft was dropped from `see-labels.json` without a word. Measured on
    7b74570: 0 of 3 recorded.

    Both children are checked by NAME, so the case proves per-child
    attribution, not merely that something was written — and the frame the
    owner left alone (the remainder child, still a draft) gains nothing."""
    pack_dir, workdir = k_batch_run(tmp, 4)
    page = review_text(pack_dir, workdir)
    text = page.read_text()
    block = pm.parse_review(text)[0]
    nums = sorted(block["frames"])
    assert len(nums) == 4 and len({block["frames"][n]["subject_id"]
                                   for n in nums}) == 1, block["frames"]
    text = fill_pick(text, None, name="Name-A", frames=f"{nums[0]},{nums[2]}")
    text = fill_pick(text, None, name="Name-B", frames=str(nums[1]))
    page.write_text(text)
    rc, said = confirm(pack_dir, workdir)
    assert rc == 0, said
    registry = psub.load(pack=open_pack(pack_dir))
    held = {s.name: s.subject_id for s in registry.subjects if s.name}
    assert set(held) == {"Name-A", "Name-B"}, held

    def recorded(n):
        batch = Path(block["frames"][n]["path"]).parent.parent
        doc = json.loads((workdir / batch / "see-labels.json").read_text())
        return sorted({s.get("subject_id") for e in doc["labels"]
                       for s in photo_evidence.subject_list(e)} - {None})

    got = {n: recorded(n) for n in nums}
    assert got == {nums[0]: [held["Name-A"]], nums[1]: [held["Name-B"]],
                   nums[2]: [held["Name-A"]], nums[3]: []}, got
    assert "recorded 3 owner-picked frame(s)" in said, said


def case_a_confirm_audits_the_id_it_replaced(tmp):
    """FIX7 (U7-1). A photo that already named a subject (an identify agree
    leaves one) loses that id when the owner picks it for another name. The
    confirm now audits each replaced id, which is what a detach restores when
    the photo has no agree. On b58f0fd no such row is written."""
    pack_dir, workdir = k_batch_run(tmp, 4)
    page = review_text(pack_dir, workdir)
    text = page.read_text()
    block = pm.parse_review(text)[0]
    nums = sorted(block["frames"])
    for doc_path in workdir.glob("classify/batch-*/see-labels.json"):
        doc = json.loads(doc_path.read_text())
        for e in doc["labels"]:
            if len(photo_evidence.subject_list(e)) <= 1:
                e["subjects"] = [{"subject_kind": "cat", "subject_id": "subj-0900"}]
                e.pop("subject", None)
        doc_path.write_text(json.dumps(doc))
    page.write_text(fill_pick(text, None, name="Name-A",
                              frames=f"{nums[0]},{nums[1]}"))
    rc, said = confirm(pack_dir, workdir)
    assert rc == 0, said
    rows = [r for r in psub.load(pack=open_pack(pack_dir)).audit_trail()
            if r.get("decision") == "see-label replaced"]
    assert len(rows) == 2 and {r["replaced"] for r in rows} == {"subj-0900"}, rows
    held = {s.name: s.subject_id for s in psub.load(pack=open_pack(pack_dir)).subjects}
    assert {r["subject_id"] for r in rows} == {held["Name-A"]}, rows


# =============================================================== FIX8 F8-1 ==

OLD_ID = "subj-0900"


def a_photo_already_named(tmp, held):
    """K-batch pack whose registry also holds a confirmed `Name-Old`, and whose
    single-subject see-labels are set to `held(entry, frame draft)` -> list of
    subject records. -> (pack dir, work dir, page, block)."""
    pack_dir, workdir = k_batch_run(tmp, 4)
    reg = pack_dir / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text(encoding="utf-8"))
    data["subjects"].append({"subject_id": OLD_ID, "name": "Name-Old",
                             "who": "Name-Old", "kind": "cat",
                             "status": psub.STATUS_CONFIRMED, "exemplars": []})
    reg.write_text(json.dumps(data))
    page = review_text(pack_dir, workdir)
    block = pm.parse_review(page.read_text())[0]
    for doc_path in workdir.glob("classify/batch-*/see-labels.json"):
        doc = json.loads(doc_path.read_text())
        for e in doc["labels"]:
            if len(photo_evidence.subject_list(e)) <= 1:
                e["subjects"] = held(e)
                e.pop("subject", None)
        doc_path.write_text(json.dumps(doc))
    return pack_dir, workdir, page, block


def source_of_frame(workdir, block, n):
    rel = Path(block["frames"][n]["path"])
    report = json.loads((workdir / rel.parent.parent / "see-report.json").read_text())
    return next(e["path"] for e in report["selected"] if e.get("sample") == rel.name)


def case_a_confirm_says_the_name_it_displaces(tmp):
    """FIX8 F8-1 (REPRODUCTION). UAT01-8: one answer on two photos took Birk
    off both, the audit knew, and neither the dry run nor --go said so. Each
    photo now reads `<photo>: Name-Old -> Name-A` on both sides. On 99ca388
    neither output names Name-Old."""
    pack_dir, workdir, page, block = a_photo_already_named(
        tmp, lambda e: [{"subject_kind": "cat", "subject_id": OLD_ID}])
    nums = sorted(block["frames"])[:2]
    page.write_text(fill_pick(page.read_text(), None, name="Name-A",
                              frames=",".join(map(str, nums))))
    want = [f"{Path(source_of_frame(workdir, block, n)).name}: Name-Old -> Name-A"
            for n in nums]
    rc, dry = confirm(pack_dir, workdir, go=False)
    assert rc == 0 and all(w in dry for w in want), (want, dry)
    rc, said = confirm(pack_dir, workdir)
    assert rc == 0 and all(w in said for w in want), (want, said)


def case_the_page_shows_the_name_a_frame_already_carries(tmp):
    """⭐ B4 (REPRODUCTION, UAT01-9 F2 / UAT01-10 F1, rated HIGH). ⛔ FAILS on
    6edab52: a frame whose photo already carried a confirmed name showed only
    its number, so a displacement surfaced at the confirm, after answering.
    The page now says it under the frame and in a `named:` line the web page
    reads (display only); a photo carrying only a draft says nothing."""
    import photo_review_page as rp
    pack_dir, workdir, page, block = a_photo_already_named(
        tmp, lambda e: [{"subject_kind": "cat", "subject_id": OLD_ID}])
    page.unlink()
    text = review_text(pack_dir, workdir).read_text()
    nums = sorted(block["frames"])
    assert all(f"frame {n} is already named Name-Old" in text for n in nums), text[-1500:]
    parsed = rp.parse_review(text)
    named = {n: v for q in parsed["questions"] for n, v in (q.get("named") or {}).items()}
    assert named and set(named.values()) == {"Name-Old"}, named


def case_a_frame_holding_only_a_draft_says_nothing(tmp):
    """GUARD (B4). A draft has no name — it is the question itself."""
    pack_dir, workdir, page, _block = a_photo_already_named(tmp, lambda e: e.get("subjects") or [])
    page.unlink()
    text = review_text(pack_dir, workdir).read_text()
    assert "is already named" not in text and "`named:`" not in text, text[-800:]


def case_the_displaced_line_names_the_photo_not_its_sample(tmp):
    """GUARD. A video is looked at through a still sample; the owner has only
    the video. The line names the SOURCE file."""
    pack_dir, workdir, page, block = a_photo_already_named(
        tmp, lambda e: [{"subject_kind": "cat", "subject_id": OLD_ID}])
    n = sorted(block["frames"])[0]
    page.write_text(fill_pick(page.read_text(), None, name="Name-A", frames=str(n)))
    sample = Path(block["frames"][n]["path"]).name
    source = Path(source_of_frame(workdir, block, n)).name
    assert sample != source, (sample, source)
    rc, dry = confirm(pack_dir, workdir, go=False)
    assert f"{source}: " in dry and f"{sample}: " not in dry, dry


def case_the_displaced_line_for_nothing_a_draft_and_two_animals(tmp):
    """GUARD. Nothing held reads `—`; a draft reads as its id; a photo holding
    two subjects keeps both, because the writer ADDS there (D6)."""
    pack_dir, workdir, page, block = a_photo_already_named(
        tmp, lambda e: [{"subject_kind": "cat"}])
    n = sorted(block["frames"])[0]
    page.write_text(fill_pick(page.read_text(), None, name="Name-A", frames=str(n)))
    source = Path(source_of_frame(workdir, block, n)).name
    rc, dry = confirm(pack_dir, workdir, go=False)
    assert f"{source}: — -> Name-A" in dry, dry

    other = tmp / "draft"
    other.mkdir()
    pack_dir, workdir, page, block = a_photo_already_named(
        other, lambda e: [{"subject_kind": "cat", "subject_id": "subj-0901"}])
    page.write_text(fill_pick(page.read_text(), None, name="Name-A", frames=str(n)))
    source = Path(source_of_frame(workdir, block, n)).name
    rc, dry = confirm(pack_dir, workdir, go=False)
    assert f"{source}: subj-0901 -> Name-A" in dry, dry

    two = tmp / "two"
    two.mkdir()
    pack_dir, workdir, page, block = a_photo_already_named(
        two, lambda e: [{"subject_kind": "cat", "subject_id": OLD_ID},
                        {"subject_kind": "cat", "subject_id": "subj-0901"}])
    page.write_text(fill_pick(page.read_text(), None, name="Name-A", frames=str(n)))
    source = Path(source_of_frame(workdir, block, n)).name
    want = f"{source}: Name-Old + subj-0901 -> Name-Old + subj-0901 + Name-A"
    rc, dry = confirm(pack_dir, workdir, go=False)
    assert want in dry, (want, dry)
    rc, said = confirm(pack_dir, workdir)
    assert rc == 0 and want in said, (want, said)


def case_the_same_name_says_no_change_and_a_refused_row_says_nothing(tmp):
    """GUARD. `Name-Old same` on a photo already Name-Old changes nothing and
    says so; a repeated name with neither token is refused and prints no
    per-photo line, because nothing will be written."""
    pack_dir, workdir, page, block = a_photo_already_named(
        tmp, lambda e: [{"subject_kind": "cat", "subject_id": OLD_ID}])
    n = sorted(block["frames"])[0]
    text = page.read_text()
    source = Path(source_of_frame(workdir, block, n)).name
    page.write_text(fill_pick(text, None, name="Name-Old", frames=str(n)))
    rc, dry = confirm(pack_dir, workdir, go=False)
    assert rc == 1 and f"{source}: " not in dry, dry
    page.write_text(fill_pick(text, None, name=f"Name-Old {pm.SAME_TOKEN}",
                              frames=str(n)))
    want = f"{source}: Name-Old -> Name-Old (no change)"
    rc, dry = confirm(pack_dir, workdir, go=False)
    assert rc == 0 and want in dry, (want, dry)
    rc, said = confirm(pack_dir, workdir)
    assert rc == 0 and want in said, (want, said)


def case_a_join_dry_run_says_what_go_writes(tmp):
    """FIX7 (U7-3). UAT01-7: the confirm dry run said 4 changes and --go
    wrote 7, because a join was one grouped line before --go and one line per
    draft plus a memorized line after it; and no dry run named the see-label
    write that names the folders. Now one line per draft on both sides, the
    counts agree, and the dry run names the frames it would record."""
    import re
    pack_dir, later, target, draft = a_remembered_subject_and_a_new_draft(tmp)
    page = later / "memory-review_C1.md"
    block = pm.parse_review(page.read_text())[0]
    picked = sorted(block["frames_by_subject"][draft])[:1]
    page.write_text(fill_pick(page.read_text(), None,
                              frames=",".join(str(n) for n in picked),
                              name=f"Name-Shared {pm.SAME_TOKEN}"))
    rc, dry = confirm(pack_dir, later, checkpoint=1, go=False)
    assert rc == 0, dry
    assert f"{draft} -> would join {target}" in dry, dry
    assert "would record 1 owner-picked frame(s) into see-labels.json" in dry, dry
    rc, said = confirm(pack_dir, later, checkpoint=1, go=True)
    assert rc == 0, said
    n_dry = int(re.findall(r"(\d+) change\(s\)", dry)[-1])
    n_go = int(re.findall(r"(\d+) change\(s\)", said)[-1])
    assert n_dry == n_go, (n_dry, n_go, dry, said)
    assert "recorded 1 owner-picked frame(s)" in said, said


def case_the_near_name_measure_is_script_neutral_and_list_free(tmp):
    """FIX7 (U7-4) GUARD on the measure itself, on invented names. NFKC and
    casefold first, then one edit: a name of fewer than 4 characters is only
    ever matched at distance 0, which is the documented CJK limit."""
    def near(a, b):
        return [(sid, other, d) for sid, other, d
                in pm.near_names(a, [("subj-0001", b)])]
    warned = [("Pippa", "Pipa"), ("Kiko", "Kika"), ("Pippa", "PIPPA"),
              ("ﬁona", "Fiona"), ("Pip pa", "Pippa")]
    quiet = [("Pippa", "Rex"), ("Bo", "Bu"), ("Max", "Mac"), ("Kiko", "Kiwi")]
    for a, b in warned:
        assert near(a, b), (a, b)
    for a, b in quiet:
        assert not near(a, b), (a, b, near(a, b))
    assert near("Pippa", "PIPPA")[0][2] == 0, near("Pippa", "PIPPA")
    assert near("Pippa", "Pipa")[0][2] == 1, near("Pippa", "Pipa")


def case_a_near_typo_of_a_held_name_is_warned_never_refused(tmp):
    """FIX7 (U7-4) REPRODUCTION. UAT01-7: a name one letter from a confirmed
    one was accepted with 0 refused and not a word said. It is still
    accepted — two animals may have close names — and now it is said, on the
    dry run and on --go."""
    pack_dir, later, target, draft = a_remembered_subject_and_a_new_draft(tmp)
    page = later / "memory-review_C1.md"
    block = pm.parse_review(page.read_text())[0]
    picked = sorted(block["frames_by_subject"][draft])[:1]
    page.write_text(fill_pick(page.read_text(), None,
                              frames=",".join(str(n) for n in picked),
                              name="Name-Sharedd"))
    rc, dry = confirm(pack_dir, later, checkpoint=1, go=False)
    assert rc == 0, dry
    assert "'Name-Sharedd' is one letter away from it" in dry, dry
    assert f"'Name-Shared' ({target})" in dry, dry
    rc, said = confirm(pack_dir, later, checkpoint=1, go=True)
    assert rc == 0, said
    assert "is one letter away from it" in said, said
    names = {s.name for s in psub.load(pack=open_pack(pack_dir)).subjects}
    assert {"Name-Shared", "Name-Sharedd"} <= names, names


# ======================================================= F13 / ADR 0004 =====

def name_three_drafts(pack_dir, workdir, name):
    page = review_text(pack_dir, workdir)
    text = page.read_text()
    page.write_text(fill_pick(text, None, name=name,
                              frames=frames_of(text, [1, 2, 3])))
    return confirm(pack_dir, workdir)


def case_a_declared_name_takes_its_frames_without_same(tmp):
    """ADR 0004 (iv). The owner declared the animal at setup, so a plain
    `name:` over frames from three drafts joins THAT record — one name, one
    record — instead of refusing and asking the question the owner already
    answered. Measured on 7b74570: refused (rc 1), and only a retyped
    `name: X same` joined."""
    import photo_onboard_page as pob
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=4)
    [(declared, _name, made)] = pob.declare_pets(str(pack_dir), ["Name-Decl"])
    assert made == "created", made
    rc, said = name_three_drafts(pack_dir, workdir, "Name-Decl")
    assert rc == 0, said
    registry = psub.load(pack=open_pack(pack_dir))
    holders = [s.subject_id for s in registry.subjects
               if s.name == "Name-Decl"
               and s.status == psub.STATUS_CONFIRMED]
    assert holders == [declared], holders
    assert said.count(f"-> joined {declared}") == 3, said


def case_an_undeclared_holder_still_gets_the_ask(tmp):
    """The other side of (iv): a same-named record the owner did NOT declare
    at setup — any pack older than the marker — keeps SNS-7's question.
    "Declared" is never guessed."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=4)
    registry = psub.load(pack=open_pack(pack_dir))
    older = registry.create_subject(name="Name-Decl", who="pet")
    registry.save()
    rc, said = name_three_drafts(pack_dir, workdir, "Name-Decl")
    assert rc == 1 and "already taken" in said, said
    assert "joined" not in said, said
    registry = psub.load(pack=open_pack(pack_dir))
    assert [s.subject_id for s in registry.subjects
            if s.name == "Name-Decl"] == [older.subject_id]


def answer_next(pack_dir, workdir, checkpoint, name, go=True, text=None):
    """Render checkpoint N (or reuse its text), answer tile 1 with `name`."""
    page = workdir / f"memory-review_C{checkpoint}.md"
    if text is None:
        text = review_text(pack_dir, workdir, checkpoint=checkpoint).read_text()
    page.write_text(fill_pick(text, None, name=name, frames=frames_of(text, [1])))
    rc, said = confirm(pack_dir, workdir, checkpoint=checkpoint, go=go)
    return rc, said, text


def confirmed_named(pack_dir, name):
    registry = psub.load(pack=open_pack(pack_dir))
    return sorted(s.subject_id for s in registry.subjects if s.name == name
                  and s.status == psub.STATUS_CONFIRMED)


def case_same_over_several_holders_folds_them(tmp):
    """F13 (iii)(b), the UAT01-4 shape. C1's one answer over three drafts
    leaves three records sharing a name (amendment (a), signed). At C2 the
    owner says `same`, and on 7b74570 that was refused with "rename one of
    them first" — the product asking the owner to rename their pet. Now the
    unstamped holders are FOLDED and the frames join the one that keeps the
    name, and the dry run says exactly what `--go` then does."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=3)
    rc, said = name_three_drafts(pack_dir, workdir, "Name-M")
    assert rc == 0, said
    holders = confirmed_named(pack_dir, "Name-M")
    assert len(holders) == 3, holders
    rc_dry, dry, text = answer_next(pack_dir, workdir, 2, "Name-M same",
                                    go=False)
    rc_go, went, _ = answer_next(pack_dir, workdir, 2, "Name-M same",
                                 text=text)
    assert rc_dry == 0 and rc_go == 0, (dry, went)
    told = [line for line in dry.splitlines() if "folds them" in line]
    assert len(told) == 1 and all(h in told[0] for h in holders), dry
    assert told == [line for line in went.splitlines()
                    if "folds them" in line], (told, went)
    assert confirmed_named(pack_dir, "Name-M") == [holders[0]]
    registry = psub.load(pack=open_pack(pack_dir))
    aliases = sorted(s.subject_id for s in registry.subjects
                     if s.status == psub.STATUS_MERGED_INTO
                     and s.record.get("merged_into") == holders[0])
    assert aliases == holders[1:], aliases
    assert f"-> joined {holders[0]}" in went, went


def case_a_distinct_pair_is_refused_and_says_which_row_to_type(tmp):
    """F13 (iii)(b), the other half. Two records share a name BECAUSE the
    owner answered `distinct` — two animals. `same` must not fold them: it is
    refused, and the refusal prints the exact row for each holder with a fact
    to tell them apart. `name: X same subj-NNNN` then joins that one record
    and nothing else. The stamp is written only by the typed `distinct`."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=1)
    assert answer_next(pack_dir, workdir, 1, "Name-M")[0] == 0
    first = confirmed_named(pack_dir, "Name-M")
    rc, said, _ = answer_next(pack_dir, workdir, 2, "Name-M distinct")
    assert rc == 0, said
    both = confirmed_named(pack_dir, "Name-M")
    [second] = [sid for sid in both if sid not in first]
    registry = psub.load(pack=open_pack(pack_dir))
    assert registry.get_literal(second).record.get(psub.DISTINCT_FLAG) \
        == "Name-M"
    assert not registry.get_literal(first[0]).record.get(psub.DISTINCT_FLAG)

    rc, said, text = answer_next(pack_dir, workdir, 3, "Name-M same")
    assert rc == 1 and "named as a DIFFERENT animal" in said, said
    for sid in both:
        assert f"`name: Name-M same {sid}`" in said, said
    assert "Rename one of them" not in said, said
    assert confirmed_named(pack_dir, "Name-M") == both, "a distinct pair folded"

    rc, said, _ = answer_next(pack_dir, workdir, 3, "Name-M same subj-9999",
                              text=text)
    assert rc == 1 and "there is no subj-9999" in said, said
    rc, said, _ = answer_next(pack_dir, workdir, 3, f"Name-M same {second}",
                              text=text)
    assert rc == 0 and f"-> joined {second}" in said, said
    assert confirmed_named(pack_dir, "Name-M") == both


def case_the_recheck_door_never_folds_a_distinct_pair(tmp):
    """F13 (iii)(b), the `recheck:` door. A remembered subject typed onto the
    name `X same` while X is held by two records, one of them named as a
    DIFFERENT animal (`distinct`), would fold [id] + ALL holders — both
    animals. It is refused, and nothing is folded."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=1)
    assert answer_next(pack_dir, workdir, 1, "Name-M")[0] == 0
    assert answer_next(pack_dir, workdir, 2, "Name-M distinct")[0] == 0
    assert answer_next(pack_dir, workdir, 3, "Name-Other")[0] == 0
    [third] = confirmed_named(pack_dir, "Name-Other")
    holders = confirmed_named(pack_dir, "Name-M")
    assert len(holders) == 2, holders
    page = review_text(pack_dir, workdir, checkpoint=4)
    page.write_text(fill_recheck(page.read_text(), third,
                                 f"Name-M {pm.SAME_TOKEN}"))
    rc, said = confirm(pack_dir, workdir, checkpoint=4)
    assert rc == 1 and "named as a DIFFERENT animal" in said, said
    registry = psub.load(pack=open_pack(pack_dir))
    assert not [s.subject_id for s in registry.subjects
                if s.status == psub.STATUS_MERGED_INTO], "a fold happened"
    assert confirmed_named(pack_dir, "Name-M") == holders
    assert confirmed_named(pack_dir, "Name-Other") == [third]


def case_the_rename_your_pet_remedy_is_gone(tmp):
    """GUARD: the :4410 sentence that told an owner to rename their own pet so
    the engine could tell two records apart is unreachable — it is not in the
    module at all."""
    assert "Rename one of them" not in Path(pm.__file__).read_text()


def case_the_old_name_tokens_parse_as_before(tmp):
    """GUARD for the new `same subj-NNNN` form: `X same` and `X distinct`
    parse exactly as they did, and the new form carries its id."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=4)
    text = review_text(pack_dir, workdir).read_text()
    two = fill_pick(fill_pick(text, None, name="Name-X same", frames="1"),
                    None, name="Name-Y distinct", frames="2")
    units = [(u["name"], u["same"], u["distinct"], u.get("same_as"))
             for u in pm.parse_review(two)[0]["picks"] if u["verb"] == "pick"]
    assert units == [("Name-X", True, False, None),
                     ("Name-Y", False, True, None)], units
    one = fill_pick(text, None, name="Name-Z same subj-0009", frames="1")
    units = [(u["name"], u["same"], u["distinct"], u.get("same_as"))
             for u in pm.parse_review(one)[0]["picks"] if u["verb"] == "pick"]
    assert units == [("Name-Z", True, False, "subj-0009")], units


def labelled_ids(workdir):
    """-> {batch dir: sorted subject ids its see-labels carry}."""
    out = {}
    for path in sorted(Path(workdir).glob("classify/batch-*/see-labels.json")):
        doc = json.loads(path.read_text())
        out[path.parent.name] = sorted(
            {s.get("subject_id") for e in doc["labels"]
             for s in photo_evidence.subject_list(e)} - {None})
    return out


def case_joined_frames_reach_see_labels(tmp):
    """F11's gap one verb along. A declared-name join (iv) or a `same` join
    (iii) leaves each picked draft as `absorbed` bookkeeping, and the
    write-back used to skip it — measured on the branch: 0 of 3 picked frames
    recorded after a declared join, no "recorded" line, so `[who]` could not
    reach a folder from the path the owner will use by default."""
    import photo_onboard_page as pob
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=4)
    [(declared, _n, _m)] = pob.declare_pets(str(pack_dir), ["Name-Decl"])
    rc, said = name_three_drafts(pack_dir, workdir, "Name-Decl")
    assert rc == 0, said
    got = labelled_ids(workdir)
    assert got == {"batch-01": [declared], "batch-02": [declared],
                   "batch-03": [declared], "batch-04": []}, got
    assert "recorded 3 owner-picked frame(s)" in said, said

    other = tmp / "fold"
    other.mkdir()
    pack_dir, workdir, _ids = four_drafts(other, rendered=3)
    assert name_three_drafts(pack_dir, workdir, "Name-M")[0] == 0
    keeper = confirmed_named(pack_dir, "Name-M")[0]
    rc, said, _ = answer_next(pack_dir, workdir, 2, "Name-M same")
    assert rc == 0, said
    assert labelled_ids(workdir)["batch-04"] == [keeper], labelled_ids(workdir)


# ======================================================== W2A-4 rename =====

def two_named(tmp):
    """One draft split by the owner into two confirmed subjects, Name-A and
    Name-B. -> (pack_dir, workdir, id of Name-A, id of Name-B)."""
    pack_dir, workdir = k_batch_run(tmp, 3)
    page = review_text(pack_dir, workdir)
    text = fill_pick(page.read_text(), None, name="Name-A", frames="1,3")
    page.write_text(fill_pick(text, None, name="Name-B", frames="2"))
    assert confirm(pack_dir, workdir)[0] == 0
    held = {s.name: s.subject_id
            for s in psub.load(pack=open_pack(pack_dir)).subjects if s.name}
    return pack_dir, workdir, held["Name-A"], held["Name-B"]


def names_of(pack_dir, *ids):
    registry = psub.load(pack=open_pack(pack_dir))
    return [registry.get_literal(sid).name for sid in ids]


def case_a_rename_dry_run_says_what_go_does(tmp):
    """W2A-4. Two `recheck:` rows that swap two names: on 7b74570 the dry run
    refused the second row (rc 1, "1 would be written, 1 refused") because it
    judged it against a pack it had not moved, and `--go` then applied both
    (rc 0). Every name row is now judged against the END state."""
    pack_dir, workdir, a, b = two_named(tmp)
    page = review_text(pack_dir, workdir, checkpoint=2)
    page.write_text(page.read_text()
                    + f"\n> - `{pm.RECHECK_KEY}:` {a} Name-B distinct"
                      f"\n> - `{pm.RECHECK_KEY}:` {b} Name-A\n")
    rc_dry, dry = confirm(pack_dir, workdir, checkpoint=2, go=False)
    rc_go, went = confirm(pack_dir, workdir, checkpoint=2, go=True)
    assert (rc_dry, rc_go) == (0, 0), (dry, went)
    assert "2 change(s) would be written, 0 refused" in dry, dry
    assert "wrote 2 change(s)" in went, went
    assert names_of(pack_dir, a, b) == ["Name-B", "Name-A"]


def rename_cli(workdir, pack_dir, *args):
    return subprocess.run(
        [PY, str(ROOT / "scripts" / "photo_memory.py"), "rename", str(workdir),
         "--profile", str(pack_dir / "photo-profile.json"), *args],
        capture_output=True, text=True)


def case_the_rename_verb_swaps_two_names_in_one_command(tmp):
    """ADR 0004's rename verb, NEW. A confirmed name is corrected with no
    checkpoint page, and a swap — the earlier round's two swapped names — is
    ONE command. It renames records only: the work dir is not touched, and
    the old names stay resolvable (`previous_names`, the ledger)."""
    pack_dir, workdir, a, b = two_named(tmp)
    listing = lambda: sorted((str(p.relative_to(workdir)), p.stat().st_mtime_ns)
                             for p in workdir.rglob("*"))
    before = listing()
    dry = rename_cli(workdir, pack_dir, f"{a}=Name-B", f"{b}=Name-A")
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "2 change(s) would be written, 0 refused" in dry.stdout, dry.stdout
    assert names_of(pack_dir, a, b) == ["Name-A", "Name-B"], "dry run wrote"
    went = rename_cli(workdir, pack_dir, f"{a}=Name-B", f"{b}=Name-A", "--go")
    assert went.returncode == 0 and "wrote 2 change(s)" in went.stdout, \
        went.stdout + went.stderr
    assert names_of(pack_dir, a, b) == ["Name-B", "Name-A"]
    registry = psub.load(pack=open_pack(pack_dir))
    assert "Name-A" in registry.get_literal(a).previous_names
    assert log_text(open_pack(pack_dir)).count("| renamed |") == 2
    assert listing() == before, "the rename verb touched the work dir"


def case_the_rename_verb_refuses_in_its_own_words(tmp):
    """NEW verb, its refusals: a collision is asked (with THIS verb's syntax
    in the way on), a draft is not renamed here, a malformed pair says so —
    and a refused command writes nothing."""
    pack_dir, workdir, a, b = two_named(tmp)
    said = rename_cli(workdir, pack_dir, f"{a}=Name-B", "--go")
    assert said.returncode == 1 and "already taken" in said.stdout, said.stdout
    assert f"`{a}=Name-B distinct`" in said.stdout, said.stdout
    registry = psub.load(pack=open_pack(pack_dir))
    draft = registry.create_subject(kind="cat")
    registry.save()
    said = rename_cli(workdir, pack_dir, f"{draft.subject_id}=Name-C",
                      "not-a-pair", "--go")
    assert said.returncode == 1, said.stdout
    assert "a draft is named at the checkpoint" in said.stdout, said.stdout
    assert "is not `subj-NNNN=Name`" in said.stdout, said.stdout
    assert names_of(pack_dir, a, b, draft.subject_id) == \
        ["Name-A", "Name-B", None]


# ======================================================= G6-1 batch pages ===

def batch_page(pack_dir, workdir, batch=1):
    """Write batch N's page under its own name, the way `review` writes one.
    -> its path. The name is spelled here, not taken from
    `pm.batch_page_name()`, so the cases also run on code without it."""
    path = workdir / f"P-B{int(batch):02d}.md"
    assert getattr(pm, "batch_page_name", lambda b: path.name)(batch) == path.name
    with contextlib.redirect_stdout(io.StringIO()):
        pm.cmd_review(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=None, out=str(path)))
    return path


def confirm_page(pack_dir, workdir, page=None, file=None, go=True):
    """-> (exit code, everything said). A `sys.exit` comes back as its message,
    so a case run on code without `--page` fails instead of stopping the run."""
    spoken = io.StringIO()
    with contextlib.redirect_stdout(spoken):
        try:
            rc = pm.cmd_confirm(argparse.Namespace(
                workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
                checkpoint=1, file=file, page=page, sync=False,
                by="Test Operator", go=go))
        except SystemExit as stop:
            rc = f"exit: {stop}"
    return rc, spoken.getvalue()


def case_a_batch_page_is_booked_and_never_charged(tmp):
    """REPRODUCTION (G6-1). A `P-B01.md` page puts a question to the owner, so
    layer 2 must book it — or the next page asks the same draft again. It is
    not a round: the batch pages have their own count, so it spends nothing
    from `sns_rounds_per_dump` and takes no checkpoint number.
    ⛔ FAILS on ce4eb56: the page carried no mark and booked 0 ids."""
    pack_dir, workdir = k_batch_run(tmp, 4)
    text = batch_page(pack_dir, workdir, 1).read_text()
    blocks = pm.parse_review(text)
    assert len(blocks) == 1 and len(blocks[0]["subject_ids"]) == 1, blocks
    draft = blocks[0]["subject_ids"][0]
    assert "<!-- sns-page: P-B01 -->" in text, "the page does not say its name"

    seen = pm.asked_before(workdir)
    assert seen.get(draft, (None,))[0] == "P-B01", \
        ("a batch page's question was not booked", seen)
    assert pm.rounds_fired(workdir) == 0, "a batch page was charged as a round"
    assert pm.next_checkpoint(workdir) == 1, "a batch page took a checkpoint number"

    with contextlib.redirect_stdout(io.StringIO()):
        pm.cmd_review(argparse.Namespace(
            workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
            checkpoint=None, out=None))
    after = (workdir / "memory-review_C1.md").read_text()
    assert pm.parse_review(after) == [], "the checkpoint asked the draft again"
    assert "asked at P-B01, no new evidence" in after, after
    log(f"{draft} booked at P-B01; 0 rounds charged; C1 says where it was asked")


def case_a_refused_row_on_a_batch_page_comes_back(tmp):
    """REPRODUCTION (G6-1). The refusal channel un-books the drafts of a row
    `confirm` refused, so the question comes back. It was keyed on the
    checkpoint NUMBER in the page's name, so on a batch page it booked nothing:
    the refused draft stayed shut by the booking beside it.
    ⛔ FAILS on ce4eb56: no `memory-refused.jsonl` row, and (the page itself not
    being booked) the applied row's booking is missing too."""
    pack_dir, workdir, ranked = two_drafts_one_question(
        tmp, cadence={"new_fss_floor": 1, "sns_rounds_per_dump": 4})
    applied, refused = ranked
    path = batch_page(pack_dir, workdir, 1)
    text = fill_pick(path.read_text(), [1], who="pet", name="Name-Applied")
    path.write_text(fill_pick(text, [2], who="pet", name=""))

    rc, said = confirm_page(pack_dir, workdir, file=str(path))
    assert rc == 1, ("the half-identified row was not refused", said)
    rows = [json.loads(line) for line in
            (workdir / pm.REFUSED_NAME).read_text().splitlines()] \
        if (workdir / pm.REFUSED_NAME).exists() else []
    assert [(r.get("page"), r["subject_ids"]) for r in rows] == \
        [("P-B01", [refused])], ("the refusal was not booked to the page", rows)
    seen = pm.asked_before(workdir)
    assert refused not in seen, ("the refused draft is still booked", seen)
    assert seen.get(applied, (None,))[0] == "P-B01", \
        ("the applied row's booking is missing", seen)
    log(f"{refused} un-booked at P-B01, {applied} stays booked there")


def case_a_batch_page_whose_pack_moved_is_refused_whole(tmp):
    """GUARD (G6-1; passes on ce4eb56 too). The pinned-pack check reads the
    page text, never its name, so a batch page is refused whole once the pack
    moved after it was written."""
    pack_dir, workdir = k_batch_run(tmp, 4)
    path = batch_page(pack_dir, workdir, 1)
    pinned = pm.pinned_snapshot(path.read_text())
    path.write_text(fill_pick(path.read_text(), [1]))
    profile_path = pack_dir / "photo-profile.json"
    profile = json.loads(profile_path.read_text())
    profile["g6_moved"] = True
    profile_path.write_text(json.dumps(profile, indent=1))
    assert open_pack(pack_dir).snapshot()["id"] != pinned, "the pack did not move"

    rc, said = confirm_page(pack_dir, workdir, file=str(path))
    assert rc == 1 and "NOTHING in the file was applied" in said, (rc, said)
    assert all(s.is_draft for s in psub.load(pack=open_pack(pack_dir)).subjects
               if not s.record.get(psub.DECLARED_FLAG)), "a stale page promoted"
    log("a batch page written before the pack moved applied nothing")


def case_a_page_confirmed_under_another_name_is_refused(tmp):
    """REPRODUCTION (G6-1, U5-06). A batch page is confirmed BY ITS NAME, and a
    page handed in under another name is refused whole: its answers would be
    booked against the wrong page, or against none.
    ⛔ FAILS on ce4eb56: there is no `--page`, and a copy under any name applied."""
    pack_dir, workdir = k_batch_run(tmp, 4)
    path = batch_page(pack_dir, workdir, 1)
    answered = fill_pick(path.read_text(), [1])
    path.write_text(answered)
    (workdir / "P-B02.md").write_text(answered)
    (workdir / "answers.md").write_text(answered)
    (workdir / "P-B03.md").write_text(answered.replace("<!-- sns-page: P-B01 -->", ""))

    def still_draft():
        return all(s.is_draft for s in psub.load(pack=open_pack(pack_dir)).subjects
                   if not s.record.get(psub.DECLARED_FLAG))

    for kind, page, file in (("wrong batch page", "P-B02", None),
                             ("copy", None, str(workdir / "answers.md")),
                             ("no mark", "P-B03", None)):
        rc, said = confirm_page(pack_dir, workdir, page=page, file=file)
        assert rc == 1 and "NOTHING in the file was applied" in said, (kind, rc, said)
        assert still_draft(), f"the {kind} applied a row"
    rc, said = confirm_page(pack_dir, workdir, page="plans.json")
    assert str(rc).startswith("exit:") and "not a review page name" in str(rc), (rc, said)
    assert "--page P-B01" in confirm_page(pack_dir, workdir, page="P-B02", go=False)[1]

    rc, said = confirm_page(pack_dir, workdir, page="P-B01")
    assert rc == 0, (rc, said)
    assert not still_draft(), ("the page under its own name applied nothing", said)
    log("P-B02, a copy and an unmarked page refused; P-B01 by its name applied")


# ============================================================ U2-6 ======

def u26_page(tmp, rows):
    """The split-and-share fixture, answered with `rows`: [(frames, name)],
    frames as page numbers. -> (pack dir, work dir, split, other, by_subject)."""
    pack_dir, workdir = a_split_and_a_share(tmp)
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    by_subject = pm.parse_review(path.read_text())[0]["frames_by_subject"]
    split = max(by_subject, key=lambda s: (len(by_subject[s]), s))
    other = [s for s in by_subject if s != split][0]
    text = path.read_text()
    for frames, name in rows(by_subject[split], by_subject[other]):
        if PICK_ROW not in text:
            text = text.replace("> - `skip:`", "> - " + PICK_ROW + "\n> - `skip:`", 1)
        text = fill_pick(text, None, frames=",".join(map(str, frames)), name=name)
    path.write_text(text)
    return pack_dir, workdir, split, other, by_subject


def u26_outcome(pack_dir):
    """The registry as an owner sees it, ids aside: per name, the status and
    the exemplar and look refs; and which drafts were superseded."""
    reg = psub.load(pack=open_pack(pack_dir))
    named = {}
    for s in reg.subjects:
        if s.name:
            named.setdefault(s.name, []).append((
                s.status,
                tuple(sorted(e.get("vec_ref") for e in s.exemplars)),
                tuple(sorted(l["vec_ref"] for e in s.record.get("evidence") or []
                             for l in e.get("looks") or []))))
    return ({k: sorted(v) for k, v in named.items()},
            sorted(len(s.record.get("evidence") or []) for s in reg.subjects
                   if s.status == psub.STATUS_SUPERSEDED))


def case_u26_a_row_that_splits_and_names_is_read_as_two(tmp):
    """⭐ REPRO U2-6 (owner ruling 20261001, supersedes OA-19 for this case).
    UAT2, S24U P-B01: Step 1 followed exactly gave a named row whose photos
    held two drafts, one of them split by another row, and confirm refused it
    in storage words. The row is now read as one row per draft with the same
    name — the two-row form the refusal itself taught — said in owner words,
    and the result matches that typed two-row form field by field."""
    mixed = u26_page(tmp / "mixed", lambda s, o: [
        ([s[0]] + list(o), "Name-Lotus"), (s[1:], "Name-Birk")])
    rc_dry, dry = confirm(mixed[0], mixed[1], checkpoint=1, go=False)
    rc, said = confirm(mixed[0], mixed[1], checkpoint=1, go=True)
    typed = u26_page(tmp / "typed", lambda s, o: [
        ([s[0]], "Name-Lotus"), (s[1:], "Name-Birk"), (list(o), "Name-Lotus")])
    rc_t, said_t = confirm(typed[0], typed[1], checkpoint=1, go=True)
    assert rc_t == 0, said_t
    assert rc_dry == 0 and rc == 0, (dry, said)
    for out in (dry, said):
        assert "Row 1 had photos of two cat groups, so it was read as two rows, " \
               "both named Name-Lotus" in out, out
        assert mixed[2] not in out.split("read as two rows")[1].split("\n")[0], out
    assert u26_outcome(mixed[0]) == u26_outcome(typed[0]), (
        u26_outcome(mixed[0]), u26_outcome(typed[0]))


def case_u26_a_mixed_row_with_no_name_is_not_rewritten(tmp):
    """GUARD U2-6 — the rewrite needs the owner's name; a nameless row is
    never read as anything and is refused as before."""
    pack_dir, workdir, split, other, _b = u26_page(tmp, lambda s, o: [
        ([s[0]] + list(o), ""), (s[1:], "Name-Birk")])
    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=False)
    assert "was read as two rows" not in said, said
    assert rc == 1, said


def case_u26_the_storage_gate_still_refuses_a_mixed_row(tmp):
    """GUARD U2-6 — OA-19's gate in partition_subject() is unchanged: a mixed
    row reaching storage from any other caller is still refused."""
    pack_dir, workdir = a_split_and_a_share(tmp)
    reg = psub.load(pack=open_pack(pack_dir))
    split = max(reg.drafts, key=lambda s: (len(s.record.get("evidence") or []), s.subject_id))
    other = [d for d in reg.drafts if d is not split][0]
    refs = [l["vec_ref"] for e in split.record["evidence"] for l in e["looks"]]
    why = reg.partition_refusal(split.subject_id, [
        {"vec_refs": refs[:1], "shared_with": [other.subject_id], "centroid": [1.0]},
        {"vec_refs": refs[1:], "shared_with": [], "centroid": [1.0]}])
    assert why and "both splits this subject and names" in why, why


def case_u26_a_join_that_splits_nothing_is_not_rewritten(tmp):
    """GUARD U2-6 — one row naming two drafts and splitting neither is the
    SNS-16 join, unchanged: not read as two rows."""
    pack_dir, workdir, split, other, _b = u26_page(tmp, lambda s, o: [
        (list(s) + list(o), "Name-Lotus")])
    rc, said = confirm(pack_dir, workdir, checkpoint=1, go=False)
    assert "was read as two rows" not in said, said
    assert rc == 0, said


# ============================================================ K24 ======

def k24_page(tmp, q1_skip=None, q2_skip=None, q2_pick=None, extra=""):
    """A two-question page: Q1 a cat draft (frames 1-3), Q2 a dog draft
    (frames 4-6). Each question's `skip:` row (and Q2's first `pick:` row)
    filled as given. -> (pack dir, work dir, the dog draft id)."""
    pack_dir, workdir = a_split_and_a_share(tmp)
    reg = psub.load(pack=open_pack(pack_dir))
    dog = reg.drafts[1].subject_id
    reg.get_literal(dog).record["kind"] = "dog"
    reg.save()
    pm.cmd_review(argparse.Namespace(
        workdir=str(workdir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    path = workdir / "memory-review_C1.md"
    q1, q2 = path.read_text().split("**Q2 ·", 1)
    q2 = "**Q2 ·" + q2
    blocks = pm.parse_review(path.read_text())
    assert [sorted(b["frames"]) for b in blocks] == [[1, 2, 3], [4, 5, 6]], \
        [sorted(b["frames"]) for b in blocks]
    if q1_skip:
        q1 = q1.replace("> - `skip:` ______", "> - `skip:` " + q1_skip, 1)
    if q2_skip:
        q2 = q2.replace("> - `skip:` ______", "> - `skip:` " + q2_skip, 1)
    if q2_pick:
        q2 = q2.replace("> - `pick:` ______   `who:` ______   `name:` ______",
                        "> - `pick:` " + q2_pick, 1)
    if extra:
        q2 = q2.replace("\n```\nLeaving", "\n" + extra + "\n```\nLeaving", 1)
    path.write_text(q1 + q2)
    return pack_dir, workdir, dog


def case_k24_a_skip_under_the_wrong_question_is_filed_by_frame(tmp):
    """⭐ REPRO K24 (U2-5/9) — frame numbers run through the whole page; a
    `skip:` row typed under Q1 naming Q2's frames was refused. It is filed
    under Q2, the question that owns the frames, and said in the dry run and
    under --go alike."""
    pack_dir, workdir, dog = k24_page(tmp, q1_skip="4,5,6 confirm")
    said_line = ("skip 4 was under Question 1; frame 4 is in Question 2 — "
                 "filed there.")
    rc_dry, dry = confirm(pack_dir, workdir, go=False)
    assert rc_dry == 0 and said_line in dry, dry
    assert psub.load(pack=open_pack(pack_dir)).get_literal(dog).is_draft, dry
    rc, said = confirm(pack_dir, workdir, go=True)
    assert rc == 0 and said_line in said, said
    assert "never rendered" not in said, said
    assert psub.load(pack=open_pack(pack_dir)).get_literal(dog).status \
        == psub.STATUS_REJECTED, said


def case_k24_a_crop_skip_under_the_wrong_question_is_filed_by_frame(tmp):
    """⭐ REPRO K24 — a crop skip `N.M not-a-subject` under the wrong
    question was refused "there is no frame N on this question"; it is filed
    under the question that owns frame N, said in the dry run and --go."""
    pack_dir, workdir, _dog = k24_page(tmp, q1_skip="4.1 not-a-subject")
    blocks = pm.parse_review((workdir / "memory-review_C1.md").read_text())
    assert blocks[0]["skip_animals"] == [], blocks[0]["skip_animals"]
    assert blocks[1]["skip_animals"] == [(4, 1)] \
        and blocks[1]["skip_animals_armed"], blocks[1]["skip_animals"]
    said_line = ("skip 4.1 was under Question 1; frame 4 is in Question 2 — "
                 "filed there.")
    for go in (False, True):
        _rc, said = confirm(pack_dir, workdir, go=go)
        assert said_line in said, said
        assert "there is no frame 4" not in said, said


def case_k24_a_frame_on_no_question_is_refused_without_the_recheck_hint(tmp):
    """⭐ REPRO K24 — the token-benchmark refusal sent the owner to the
    remembered section for a frame that was not there. A number on no
    question is still refused, and now says so."""
    pack_dir, workdir, dog = k24_page(tmp, q1_skip="99 confirm")
    rc, said = confirm(pack_dir, workdir, go=True)
    assert rc == 1, said
    assert "Frame 99 is on no question of this page" in said, said
    assert "remembered section" not in said, said
    assert psub.load(pack=open_pack(pack_dir)).get_literal(dog).is_draft, said


def case_k24_a_remembered_frame_keeps_the_recheck_hint(tmp):
    """GUARD K24 — a skip naming a frame shown in the remembered section
    still points at its `recheck:` row and is not filed anywhere."""
    pack_dir, workdir, _dog = k24_page(
        tmp, q1_skip="7 confirm", extra="> `shown:` subj-0009 7=9-9-9")
    rc, said = confirm(pack_dir, workdir, go=False)
    assert rc == 1 and "remembered section" in said, said
    assert "filed there" not in said, said


def case_k24_a_frame_two_questions_hold_is_refused(tmp):
    """GUARD K24 — a number held by two or more other questions is not
    moved: it cannot be told which was meant, and the refusal names them."""
    page = ("**Q1 · Group it — Cat**\n"
            "> `frames:` 1=subj-0001 aa classify/a.jpg\n"
            "> - `skip:` 9 confirm\n\n"
            "**Q2 · Group it — Dog**\n"
            "> `frames:` 9=subj-0002 bb classify/b.jpg\n\n"
            "**Q3 · Group it — Dog**\n"
            "> `frames:` 9=subj-0003 cc classify/c.jpg\n")
    blocks = pm.parse_review(page)
    assert blocks[0]["skip_ambiguous"] == [(9, [2, 3])], blocks[0]
    assert all(9 not in b["skip_numbers"] for b in blocks), blocks
    assert blocks[0]["answered"] is False or blocks[0]["skip_ambiguous"]
    pack_dir, workdir, dog = k24_page(tmp, q1_skip="4 confirm")
    path = workdir / "memory-review_C1.md"
    text = path.read_text()
    q3 = "**Q3 · Group it — Dog**\n> `frames:` 4=subj-0002 x classify/x.jpg\n\n"
    path.write_text(text.replace("```\nLeaving", q3 + "```\nLeaving", 1))
    rc, said = confirm(pack_dir, workdir, go=False)
    assert rc == 1 and "which is in Question 2 and Question 3" in said, said
    assert "filed there" not in said, said


def case_k24_a_skip_that_disagrees_with_the_target_row_is_refused(tmp):
    """GUARD K24 — Q2's own `skip:` row says not-mine; a number filed from
    Q1 saying not-a-subject would change its meaning, so it is refused and
    Q2's own row stands."""
    pack_dir, workdir, _dog = k24_page(
        tmp, q1_skip="4 confirm not-a-subject", q2_skip="5 confirm")
    rc, said = confirm(pack_dir, workdir, go=False)
    assert rc == 1, said
    assert ("which is in Question 2, and Question 2's own `skip:` row says "
            "something different") in said, said
    assert "filed there" not in said, said


def case_k24_a_filed_skip_and_a_pick_on_one_frame_are_both_refused(tmp):
    """GUARD K24 — a filed skip lands beside Q2's pick on the same frame:
    the existing pick+skip contradiction refuses both rows, in Q2."""
    pack_dir, workdir, dog = k24_page(
        tmp, q1_skip="4 confirm", q2_pick="4,5,6   `who:` pet   `name:` Birk")
    rc, said = confirm(pack_dir, workdir, go=True)
    assert rc == 1 and "Q2: frame(s) 4 are named on a `pick:` row AND on the " \
        "`skip:` row" in said, said
    assert psub.load(pack=open_pack(pack_dir)).get_literal(dog).is_draft, said


def case_k24_a_skip_under_its_own_question_is_unchanged(tmp):
    """GUARD K24 — a skip under the question that owns its frames is read
    exactly as before: no notice, rejected."""
    pack_dir, workdir, dog = k24_page(tmp, q2_skip="4,5,6 confirm")
    rc, said = confirm(pack_dir, workdir, go=True)
    assert rc == 0 and "filed there" not in said, said
    assert psub.load(pack=open_pack(pack_dir)).get_literal(dog).status \
        == psub.STATUS_REJECTED, said


def case_k24_a_filed_skip_without_confirm_is_still_refused(tmp):
    """GUARD K24 — filing carries the row's own words: with no `confirm`,
    Q2 refuses it the way it refuses its own unarmed row."""
    pack_dir, workdir, dog = k24_page(tmp, q1_skip="4,5,6")
    rc, said = confirm(pack_dir, workdir, go=True)
    assert rc == 1 and "Q2: `skip:` names frame(s) 4,5,6 without" in said, said
    assert psub.load(pack=open_pack(pack_dir)).get_literal(dog).is_draft, said


def case_w27_a_several_animal_photo_says_what_the_name_is_for(tmp):
    """⭐ REPRO W2-7 — beside a 2+ animal photo the page says, in one plain
    line, that the name is logged for the photo and never teaches the pet's
    look (D-24); the web page gets the same sentence. Only that frame."""
    import photo_review_page as rp
    _pack, workdir, page, text, _shared = shared_frame_page(tmp)
    line = ("Several animals: your name is logged for this photo, but it is "
            "never used to teach the pet's look.")
    assert text.count(line) == 1, text
    assert f"> {line} <!-- several -->" in text, text
    out = workdir / "page.html"
    rp.main(["render", str(page), "-o", str(out)])
    html = out.read_text(encoding="utf-8")
    key = '<script id="round-data" type="application/json">'
    data = json.loads(html.split(key, 1)[1].split("</script>", 1)[0]
                      .replace("<\\/", "</"))
    assert data.get("several") == line, data.get("several")


def case_w27_the_several_line_is_never_an_answer(tmp):
    """GUARD W2-7 — the marked line is display: neither `parse_review` nor
    `apply` reads it as an answer row, and an untouched page answers
    nothing."""
    import photo_review_page as rp
    _pack, _workdir, _page, text, _shared = shared_frame_page(tmp)
    assert "<!-- several -->" in text, text
    assert all(not b["answered"] and not b["picks"] and not b["skip_numbers"]
               for b in pm.parse_review(text)), pm.parse_review(text)
    line = [ln for ln in text.splitlines() if "<!-- several -->" in ln][0]
    assert not rp.RE_ANSWER_ROW.match(line), line
    assert rp.apply_answer(text, [line]) == text
    assert not pm.parse_representations(text)


def case_w27_an_older_page_keeps_its_sentence(tmp):
    """GUARD W2-7 — a page written before the line has no `several`, and the
    web badge falls back to the sentence it was published with."""
    import photo_review_page as rp
    _pack, _workdir, _page, text, _shared = shared_frame_page(tmp)
    older = "\n".join(ln for ln in text.splitlines()
                      if "<!-- several -->" not in ln)
    assert rp.parse_review(older).get("several") == ""
    tpl = Path(rp.TEMPLATE).read_text(encoding="utf-8")
    assert ('(D.several || "It names them, and is never kept as an example '
            'of either.")') in tpl, "the web badge lost its fallback"


def case_u213_a_web_page_says_only_home_or_away(tmp):
    """⭐ REPRO U2-13 — a web page may be published, so a crop's place is
    only "at home" or "away from home" there, decided by the same away_km
    test; the km and the home label stay on the text page. The written
    HTML file is checked whole."""
    import re as _re
    import photo_review_page as rp
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=4)
    add_homes(pack_dir, HOMES_F10)
    write_manifest(workdir, {str(workdir / "B1_C0_000.JPG"): "10.0010 20.0010",
                             str(workdir / "B2_C0_000.JPG"): "11.0010 21.0000",
                             str(workdir / "B3_C0_000.JPG"): "10.5000 20.0000",
                             str(workdir / "B4_C0_000.JPG"): "0 0"})
    page = review_text(pack_dir, workdir)
    text = page.read_text()
    rmsg = photo_profile.REVIEW_VOCAB["en"]
    assert "taken 55.6 km from Home-A" in text, text
    assert web_by_batch(text) == {1: "at home", 2: "at home",
                                  3: "away from home",
                                  4: rmsg["review_frame_where_none"]}, \
        web_by_batch(text)
    # This fixture's refs are not hex, so the web page embeds no frame; the
    # web words are read through the page parser the render uses, and the
    # embedded-frame HTML is checked in review_page_cases.
    wheres = rp.parse_review(text)["questions"][0]["where"]
    assert sorted(wheres.values()) == sorted(
        ["at home", "at home", "away from home",
         rmsg["review_frame_where_none"]]), wheres
    out = workdir / "page.html"
    rp.main(["render", str(page), "-o", str(out)])
    html = out.read_text(encoding="utf-8")
    assert not _re.search(r"\d\s*km\b", html), \
        _re.findall(r".{40}\d\s*km\b.{10}", html)[:3]
    assert "Home-A" not in html, "a home label reached the web page"


def case_u213_a_pack_away_km_decides_the_web_word(tmp):
    """GUARD U2-13 — no new threshold: the pack's away_km beats 3 for the web
    word exactly as it does for the text phrase."""
    pack_dir, workdir, _ids = four_drafts(tmp, rendered=4)
    add_homes(pack_dir, HOMES_F10)
    path = Path(pack_dir) / "photo-profile.json"
    profile = json.loads(path.read_text())
    profile.setdefault("cluster_defaults", {})["away_km"] = 60
    path.write_text(json.dumps(profile, indent=1))
    write_manifest(workdir, {str(workdir / "B3_C0_000.JPG"): "10.5000 20.0000"})
    text = review_text(pack_dir, workdir).read_text()
    assert where_by_batch(text)[3] == "taken at Home-A", where_by_batch(text)
    assert web_by_batch(text)[3] == "at home", web_by_batch(text)


CASES = [
    ("F22 — a frame whose crop cannot be made is refused (REPRODUCTION)",
     case_a_frame_whose_crop_cannot_be_made_is_refused),
    ("F22 — a frame whose crop is made still renders",
     case_a_frame_whose_crop_is_made_still_renders),
    ("F22 — a frame the index does not cover renders whole (decision)",
     case_a_frame_the_index_does_not_cover_renders_whole),
    ("F26 — a crop ref on pick is not two frames (REPRODUCTION)",
     case_a_crop_ref_on_pick_is_not_two_frames),
    ("F26 — confirm refuses a crop ref on pick (REPRODUCTION)",
     case_confirm_refuses_a_crop_ref_on_pick),
    ("F26 — one photo on two rows parses as that photo",
     case_one_photo_on_two_rows_parses_as_that_photo),
    ("F26 — the page teaches the two-row form (REPRODUCTION)",
     case_the_page_teaches_the_two_row_form),
    ("FIX8 F8-10 — a checkpoint page is never rewritten with another round "
     "(REPRODUCTION)",
     case_a_checkpoint_page_is_never_rewritten_with_another_round),
    ("FIX8 F8-10 — an exact repeat of a checkpoint page is allowed",
     case_an_exact_repeat_of_a_checkpoint_page_is_allowed),
    ("U2-10 — a rejection states why it was typed (REPRODUCTION)",
     case_a_rejection_states_why_it_was_typed),
    ("U2-10 — an unqualified rejection is the weaker claim",
     case_a_plain_rejection_is_the_weaker_claim),
    ("U2-10 — the basis qualifies a rejection, it cannot arm one",
     case_the_arming_word_is_still_required),
    ("U2-10 — the two rejections render differently",
     case_an_old_rejection_reads_as_not_mine),
    ("U2-12 — an incoherent group says so on the page (REPRODUCTION)",
     case_a_group_that_disagrees_with_itself_says_so),
    ("U2-12 — a coherent group stays quiet",
     case_a_group_that_agrees_with_itself_stays_quiet),
    ("VS-3b — a confirm attaches identity evidence and says what it refused",
     case_a_confirm_attaches_identity_evidence_and_says_what_it_refused),
    ("SNS-4 — a multi-kind round is bounded by {tiles_per_round}",
     case_a_multi_kind_round_is_bounded_by_the_tile_ceiling),
    ("SNS-4 — a round-deferred draft is not booked as asked",
     case_a_round_deferred_draft_is_not_booked_as_asked),
    ("SNS-4 — the ceiling keeps one checkpoint byte-identical",
     case_the_ceiling_keeps_the_page_byte_identical),
    ("SNS-4 — the per-question clamp still binds under the ceiling",
     case_the_per_question_clamp_still_binds_under_the_ceiling),
    ("step 8 — the whole dump replays every kind, in one round",
     case_the_whole_dump_replays_every_kind_in_one_round),
    ("step 8 — one --type still replays exactly that class",
     case_one_type_still_replays_exactly_that_class),
    ("step 8 — a class the dump does not ship is reported, never dropped",
     case_a_class_the_dump_does_not_ship_is_reported),
    ("SNS-7 — the `pick:` collision instruction is a row that works",
     case_the_collision_instruction_is_a_row_that_works),
    ("SNS-7 — the `recheck:` collision instruction is a row that works",
     case_the_recheck_collision_instruction_is_a_row_that_works),
    ("SNS-16 — a draft joins the subject the pack already knows",
     case_a_draft_joins_the_subject_the_pack_already_knows),
    ("SNS-16 — the promotion has NO similarity bar",
     case_the_promotion_has_no_similarity_bar),
    ("SNS-16 — a promotion row is one answer",
     case_a_promotion_row_is_one_answer),
    ("N16 — a dry run counts what --go writes when no look is kept "
     "(REPRODUCTION)", case_a_dry_run_counts_what_go_writes_when_no_look_is_kept),
    ("M7 — a stale page's refusal leads to a page that asks (REPRODUCTION)",
     case_a_stale_page_refusal_leads_to_a_page_that_asks),
    ("B2 — one draft joins two remembered pets, frame by frame (REPRODUCTION)",
     case_one_draft_joins_two_remembered_pets_frame_by_frame),
    ("step 9 — the dry run predicts the `--go` it refuses",
     case_the_dry_run_predicts_the_go_it_refuses),
    ("step 9 — a legal split is still predicted and still performed",
     case_a_predicted_split_still_runs_under_go),
    ("U2-6 — a row that splits and names is read as two (REPRODUCTION)",
     case_u26_a_row_that_splits_and_names_is_read_as_two),
    ("U2-6 — a mixed row with no name is not rewritten (GUARD)",
     case_u26_a_mixed_row_with_no_name_is_not_rewritten),
    ("U2-6 — the storage gate still refuses a mixed row (GUARD)",
     case_u26_the_storage_gate_still_refuses_a_mixed_row),
    ("U2-6 — a join that splits nothing is not rewritten (GUARD)",
     case_u26_a_join_that_splits_nothing_is_not_rewritten),
    ("OA-19 — the two-row remedy the refusal teaches is performed",
     case_the_two_row_remedy_the_refusal_teaches_is_performed),
    ("D6 — a split row and a naming row may share one name",
     case_a_split_row_and_a_naming_row_share_one_name),
    ("D6 — a shared name is a question again without its split row",
     case_a_shared_name_is_a_question_again_without_its_split_row),
    ("D6 — a shared name is refused whole when its split dies",
     case_a_shared_name_is_refused_whole_when_its_split_dies),
    ("step 9 — a refused row is not booked as asked, and comes back",
     case_a_refused_row_comes_back_as_a_question),
    ("step 9 — a refused --go leaves the page it refused still valid",
     case_a_refused_go_leaves_the_pinned_page_valid),
    ("SNS-1b — the `frames:` line maps every frame, and is never inferred",
     case_the_frames_line_maps_every_frame_and_is_never_inferred),
    ("SNS-8 — one frame numbering spans the questions and the re-presentations",
     case_one_numbering_spans_the_whole_page),
    ("OA-15 — a 2-of-5 pick promotes 2 exemplars, not 5",
     case_a_partial_pick_promotes_only_the_picked_frames),
    ("SNS-1b — two pick rows split one draft, through the confirm",
     case_two_pick_rows_split_one_draft_through_the_confirm),
    ("SNS-1b — a subset `skip:` splits before it rejects, and the rest still "
     "gets asked",
     case_a_subset_skip_splits_before_it_rejects),
    ("SNS-8 — a pick cannot reach a frame this question never rendered",
     case_a_pick_cannot_reach_a_frame_this_question_never_rendered),
    ("SNS-7 — a name collision asks, and `distinct` forces a separate slot",
     case_a_name_collision_asks_and_never_merges),
    ("SNS-7 — two rows on one page cannot quietly take one name",
     case_two_rows_one_name_asks_before_the_pack_moves),
    ("SNS-1 — a legacy `group:` row parses and is refused for promotion",
     case_a_legacy_group_row_is_parsed_and_refused),
    ("SNS-1b — a review older than the pack is refused whole, not per row",
     case_a_review_older_than_the_pack_is_refused_whole),
    ("EXIT 1 — the registry grows only from vision-confirmed matches",
     case_the_registry_grows_only_from_confirmed_matches),
    ("a drafted subject never becomes an exemplar",
     case_a_draft_never_becomes_an_exemplar),
    ("EXIT 2 — the fabrication guard passes an adversarial test",
     case_the_fabrication_guard_is_adversarial),
    ("EXIT 3 — one subject over K batches is exactly one question",
     case_one_subject_over_k_batches_is_one_question),
    ("F14 — a confirmed subject is recognised on the next dump, not re-asked",
     case_a_confirmed_subject_is_recognised_on_the_next_dump),
    ("a look nobody took is refused at confirm, not memorized",
     case_a_look_nobody_took_is_refused_at_confirm),
    ("SNS-1b — promotion is per look, and never implicit",
     case_promotion_is_per_look_and_never_implicit),
    ("SNS-5 — un-confirm puts the subject back in a question",
     case_un_confirm_puts_the_subject_back_in_a_question),
    ("a withdrawn yes cannot be promoted onto by a stale label",
     case_a_withdrawn_yes_cannot_be_promoted_onto),
    ("a forged thumbnail is still refused when the promotion runs at confirm",
     case_a_forged_thumbnail_is_still_refused_at_confirm),
    ("a re-embedded file is not promoted under its old vec_ref",
     case_a_re_embedded_file_is_not_promoted_under_its_old_ref),
    ("a confirmed subject is never asked again, in any work dir",
     case_a_confirmed_subject_is_never_asked_again),
    ("who and name are one answer, or nothing is written (ONB-13)",
     case_who_and_name_are_one_answer),
    ("skipping is free and a rejection is final",
     case_skipping_is_free_and_a_rejection_is_final),
    ("EXIT 4 — a checkpoint replay is deterministic on a pinned snapshot",
     case_a_checkpoint_replay_is_deterministic),
    ("the table shows the gap, never a guessed name",
     case_the_table_shows_the_gap_never_a_guessed_name),
    ("every contact-sheet image is a real file on disk",
     case_every_contact_sheet_image_is_on_disk),
    ("the proposals block is replaced in place, never duplicated",
     case_the_proposals_block_is_idempotent),
    ("--sync pairs the registry with the entities twin",
     case_sync_pairs_the_registry_with_the_entities_twin),
    ("SNS-9 — the remembered-name count is said, never capped",
     case_the_named_subject_count_is_said_and_never_capped),
    ("a blank pack memorizes nothing and says so",
     case_a_blank_pack_memorizes_nothing_and_says_so),
    ("two lookalike drafts are two tiles of one question, never a merge",
     case_two_lookalike_drafts_are_two_tiles_in_one_question),
    ("F16 — one grouped question per kind, with a parsed tile -> id map",
     case_one_grouped_question_per_kind_with_a_parsed_tile_map),
    ("F16 — layer 2 records each member's OWN obs_count, not the block's",
     case_layer_2_records_each_members_own_obs_count),
    ("F16 — grouped, deferred and skipped never collapse into each other",
     case_grouped_deferred_and_skipped_never_collapse),
    ("F16 — a blank answer row is not a rejection",
     case_a_blank_row_is_not_a_rejection),
    ("SNS-13 — an unarmed `skip:` rejects nothing and says so",
     case_an_unarmed_skip_rejects_nothing),
    ("SNS-12 — a subject with no frames is never asked, and not retired",
     case_a_subject_with_no_frames_is_never_asked),
    ("F15 — a cardinality answer settles neither id; a naming answer settles "
     "every member",
     case_one_answer_settles_every_member_id_and_only_what_it_answers),
    ("F15 — a grouped answer is one name in the count, not N",
     case_a_grouped_answer_is_one_name_in_the_count),
    ("the plan CSV records WHO/WHAT provenance, only when the see stage ran",
     case_the_plan_csv_records_who_and_what_provenance),
    ("the classify validator reads the per-file see record, not just the note",
     case_the_classify_validator_reads_the_per_file_record),
    ("the CLI runs see -> apply --memorize -> review -> confirm",
     case_the_cli_runs_end_to_end),
    ("SNS-1b — a split child promotes its own frames and no sibling's",
     case_a_split_child_promotes_only_its_own_frames),
    ("SNS-1b — a superseded parent leaves the question loop for free",
     case_a_superseded_parent_leaves_the_question_loop),
    ("SNS-1b — the unseen remainder inherits nothing",
     case_the_unseen_remainder_inherits_nothing),
    ("SNS-1b — a stale review cannot confirm a superseded parent",
     case_a_stale_review_cannot_confirm_a_superseded_parent),
    ("OA-16 — a stale `skip:` cannot reject a confirmed subject",
     case_a_stale_skip_cannot_reject_a_confirmed_subject),
    ("OA-14 — a rejection survives a dump boundary, and is revivable",
     case_a_rejection_survives_a_dump_boundary_and_is_revivable),
    ("a rejection with no centroid says so", case_a_rejection_with_no_centroid_says_so),
    ("SNS-5 — a remembered subject comes back with no new evidence at all",
     case_a_remembered_subject_comes_back_with_no_new_evidence),
    ("SNS-6 — the frame re-presented is the WORST-scoring sighting",
     case_the_frame_shown_is_the_worst_scoring_one),
    ("SNS-6 — a frame that cannot be scored says so, and never falls back",
     case_an_unscoreable_frame_says_so_and_never_falls_back),
    ("SNS-6 — a frame renders relative to the work dir being reviewed",
     case_a_frame_renders_relative_to_the_work_dir_being_reviewed),
    ("SNS-5 — a re-presentation promotes nothing, and silence writes nothing",
     case_a_re_presentation_promotes_nothing),
    ("OA-14 — a rejection is re-presented with no frames, and revived there",
     case_a_rejection_is_re_presented_without_frames_and_revived),
    ("SNS-5 — a withdrawal reaches the work dir that already asked, and only "
     "that subject",
     case_a_withdrawal_reaches_the_work_dir_that_already_asked),
    ("SNS-5 — stop-asking-about-this-one is refused out loud, by name",
     case_stop_asking_about_this_one_is_refused_out_loud),
    ("SNS-5 — a `recheck:` gesture is a dry run until --go",
     case_a_gesture_is_a_dry_run_until_go),
    ("SNS-4 — a round below the floor is withheld, says so, and books nothing",
     case_a_round_is_withheld_below_the_floor_and_says_so),
    ("SNS-4 — the budget stops the floor and never the last round",
     case_the_budget_stops_the_floor_and_never_the_last_round),
    ("N17 — the final page does not promise the next dump",
     case_the_final_page_does_not_promise_the_next_dump),
    ("D7 — the last round asks what layer 2 shut",
     case_the_last_round_asks_what_layer_two_shut),
    ("the review header counts only what the owner confirmed",
     case_the_header_counts_only_what_the_owner_confirmed),
    ("SNS-15 — the sweep absorbs the drafts the answer explained",
     case_the_sweep_absorbs_the_drafts_the_answer_explained),
    ("SNS-15 — withdrawing the name releases what the sweep absorbed",
     case_withdrawing_the_name_releases_what_the_sweep_absorbed),
    ("SNS-14 — a rendered round reaches the fold",
     case_a_rendered_round_reaches_the_fold),
    ("SNS-14 — a name on a `recheck:` row renames a remembered subject",
     case_a_name_on_a_recheck_row_renames_a_remembered_subject),
    ("SNS-7 — a `recheck:` collision asks in the same words as a `pick:` row",
     case_a_recheck_collision_asks_in_the_same_words_as_a_pick_row),
    ("SNS-14 — a `recheck:` row is one answer",
     case_a_recheck_row_is_one_answer),
    ("SNS-14 — a `same` row folds two remembered subjects",
     case_a_same_row_folds_two_remembered_subjects),
    ("SNS-14 — a `same` row needs two subjects the owner already named",
     case_a_same_row_needs_two_subjects_the_owner_already_named),
    ("SNS-14 — a folded id still names the winner in the plan",
     case_a_folded_id_still_names_the_winner_in_the_plan),
    ("A19 — the remembered line states the ungated share",
     case_the_remembered_line_states_the_ungated_share),
    ("A19 — a subject with no ungated sightings renders the old line",
     case_a_subject_with_no_ungated_sightings_renders_the_old_line),
    ("SNS-15 — the remembered line shows what the sweep absorbed",
     case_the_remembered_line_shows_what_the_sweep_absorbed),
    ("M1 — a preview decides as the round does and writes nothing (REPRODUCTION)",
     case_a_preview_decides_as_the_round_does_and_writes_nothing),
    ("SNS-4 — the guaranteed final round has a caller",
     case_the_guaranteed_final_round_has_a_caller),
    ("SNS-4 — the guaranteed round asks once per dump, not once per run",
     case_the_guaranteed_round_asks_once_per_dump_not_once_per_run),
    ("R3b — a shared frame says so on the page (REPRODUCTION)",
     case_a_shared_frame_says_so_on_the_page),
    ("R3b — the tile shows the crop, not the whole frame",
     case_the_tile_shows_the_crop_not_the_whole_frame),
    ("R4 — a shared frame logs both names and banks neither (REPRODUCTION)",
     case_a_shared_frame_logs_both_names_and_banks_neither),
    ("R4 — a solo frame still banks its one exemplar (CONTROL)",
     case_a_solo_frame_still_banks_its_one_exemplar),
    ("R4 — two unnamed animals open one draft, not two",
     case_two_unnamed_animals_open_one_draft_not_two),
    ("D-21 — two drafts of one kind are told apart (REPRODUCTION)",
     case_two_drafts_of_one_kind_do_not_share_one_label),
    ("D-21 — the batch table's Scene column is told apart too (REPRODUCTION)",
     case_the_scene_column_distinguishes_its_subjects),
    ("D-21 — a dateless draft keeps the bare marker (CONTROL)",
     case_a_draft_with_no_capture_date_keeps_the_bare_marker),
    ("D-21 — a pack that translated the marker keeps its word (CONTROL)",
     case_the_evidence_wraps_the_packs_own_marker),
    ("D-23 — the page does not promise what the sweep can undo (REPRODUCTION)",
     case_the_page_does_not_promise_what_the_sweep_can_undo),
    ("D-23 — a suppressed draft the sweep closed is listed next time (REPRODUCTION)",
     case_a_suppressed_draft_the_sweep_closed_is_listed_next_time),
    ("D-23 — the absorbed list is one checkpoint, not a ledger (CONTROL)",
     case_the_absorbed_list_is_one_checkpoint_not_a_ledger),
    ("D-23 — a page with no sweep behind it shows no section (CONTROL)",
     case_a_page_with_no_sweep_behind_it_shows_no_section),
    ("card (c) — a swept absorb names its space (REPRODUCTION)",
     case_a_swept_absorb_names_the_space_it_was_decided_in),
    ("card (c) — an unrecorded space is a word, not a dash (REPRODUCTION)",
     case_an_unrecorded_space_is_a_word_not_a_dash),
    ("card (c) — the space word is never guessed (MUTANT GUARD)",
     case_the_space_word_is_never_guessed),
    ("card (c) — an identity absorb would say identity (GUARD)",
     case_an_identity_absorb_would_say_identity),
    ("card (c) — the space words come from the pack (GUARD)",
     case_the_space_words_come_from_the_pack),
    ("card (c) — an owner-answered absorb is never in this section (GUARD)",
     case_an_owner_answered_absorb_is_never_in_this_section),
    ("D-27 — the page states the qualifier before it is needed (REPRODUCTION)",
     case_the_page_states_the_qualifier_before_the_owner_needs_it),
    ("D-27 — a pack with no confirmed name is not warned (MUTANT GUARD)",
     case_a_pack_with_no_confirmed_name_is_not_warned),
    ("D-27 — only confirmed names are called taken (GUARD)",
     case_only_confirmed_names_are_called_taken),
    ("D-27 — the notice is the pack's sentence (GUARD)",
     case_the_notice_is_the_packs_sentence),
    ("U-2 — a pre-plan round says it asked, and is charged once (REPRODUCTION)",
     case_a_pre_plan_round_says_it_asked_and_is_charged_once),
    ("U-2 — a withheld pre-plan round holds nothing (GUARD)",
     case_a_pre_plan_round_that_withheld_reports_nothing_to_hold_for),
    ("U-2 — a plain review never returns the pre-plan code (GUARD)",
     case_a_plain_review_never_returns_the_pre_plan_code),
    ("U5-06 — a round-2 pre-plan stop names the page it wrote (REPRODUCTION)",
     case_a_round_two_pre_plan_stop_names_the_page_it_wrote),
    ("U5-06 — a page written with --out is named by --file (GUARD)",
     case_a_pre_plan_stop_written_elsewhere_names_the_file),
    ("F10 — every frame says where it was taken, by label or distance "
     "(REPRODUCTION)", case_every_frame_says_where_it_was_taken),
    ("F10 — a re-presented frame says where too; no scan is its own answer "
     "(REPRODUCTION)", case_a_represented_frame_says_where_too),
    ("F11 — split children keep their picked frames in see-labels "
     "(REPRODUCTION)", case_split_children_keep_their_picked_frames),
    ("FIX7 — a confirm audits the see-label id it replaced (REPRODUCTION)",
     case_a_confirm_audits_the_id_it_replaced),
    ("FIX8 F8-1 — a confirm says the name it displaces (REPRODUCTION)",
     case_a_confirm_says_the_name_it_displaces),
    ("B4 — the page shows the name a frame already carries (REPRODUCTION)",
     case_the_page_shows_the_name_a_frame_already_carries),
    ("B4 — a frame holding only a draft says nothing",
     case_a_frame_holding_only_a_draft_says_nothing),
    ("FIX8 F8-1 — the line names the photo, not its sample",
     case_the_displaced_line_names_the_photo_not_its_sample),
    ("FIX8 F8-1 — nothing, a draft, and two animals",
     case_the_displaced_line_for_nothing_a_draft_and_two_animals),
    ("FIX8 F8-1 — same says no change; a refused row says nothing",
     case_the_same_name_says_no_change_and_a_refused_row_says_nothing),
    ("FIX7 U7-3 — a join dry run says what --go writes (REPRODUCTION)",
     case_a_join_dry_run_says_what_go_writes),
    ("FIX7 U7-4 — the near-name measure is script-neutral and list-free",
     case_the_near_name_measure_is_script_neutral_and_list_free),
    ("FIX7 U7-4 — a near-typo of a held name is warned, never refused "
     "(REPRODUCTION)", case_a_near_typo_of_a_held_name_is_warned_never_refused),
    ("F13 (iv) — a declared name takes its frames without `same` "
     "(REPRODUCTION)", case_a_declared_name_takes_its_frames_without_same),
    ("F13 (iv) — an undeclared same-named holder still gets the ask (GUARD)",
     case_an_undeclared_holder_still_gets_the_ask),
    ("F13 (iii) — `same` over several unstamped holders folds them, dry run "
     "= go (REPRODUCTION)", case_same_over_several_holders_folds_them),
    # Not a reproduction: on 7b74570 no stamp exists, so the scenario cannot
    # even be built there. The dead end's reproduction is the fold case above.
    ("F13 (iii) — a distinct pair is refused and says which row to type "
     "(GUARD, new behaviour)",
     case_a_distinct_pair_is_refused_and_says_which_row_to_type),
    ("F13 (iii) — the recheck door never folds a distinct pair (GUARD)",
     case_the_recheck_door_never_folds_a_distinct_pair),
    ("F13 (iii) — the rename-your-pet remedy is unreachable (GUARD)",
     case_the_rename_your_pet_remedy_is_gone),
    ("F13 (iii) — `X same` / `X distinct` parse as before (GUARD)",
     case_the_old_name_tokens_parse_as_before),
    ("F11 — frames joined by `same` or a declared name reach see-labels "
     "(REPRODUCTION)", case_joined_frames_reach_see_labels),
    ("W2A-4 — a rename dry run says what --go does (REPRODUCTION)",
     case_a_rename_dry_run_says_what_go_does),
    ("W2A-4 — the rename verb swaps two names in one command (NEW VERB)",
     case_the_rename_verb_swaps_two_names_in_one_command),
    ("W2A-4 — the rename verb refuses in its own words (NEW VERB)",
     case_the_rename_verb_refuses_in_its_own_words),
    ("G6-1 — a batch page is booked and never charged (REPRODUCTION)",
     case_a_batch_page_is_booked_and_never_charged),
    ("G6-1 — a refused row on a batch page comes back (REPRODUCTION)",
     case_a_refused_row_on_a_batch_page_comes_back),
    ("G6-1 — a batch page whose pack moved is refused whole (GUARD)",
     case_a_batch_page_whose_pack_moved_is_refused_whole),
    ("G6-1 — a page confirmed under another name is refused (REPRODUCTION)",
     case_a_page_confirmed_under_another_name_is_refused),
    ("K24 — a skip under the wrong question is filed by frame (REPRODUCTION)",
     case_k24_a_skip_under_the_wrong_question_is_filed_by_frame),
    ("K24 — a crop skip under the wrong question is filed by frame "
     "(REPRODUCTION)", case_k24_a_crop_skip_under_the_wrong_question_is_filed_by_frame),
    ("K24 — a frame on no question is refused without the recheck hint "
     "(REPRODUCTION)", case_k24_a_frame_on_no_question_is_refused_without_the_recheck_hint),
    ("K24 — a remembered frame keeps the recheck hint (GUARD)",
     case_k24_a_remembered_frame_keeps_the_recheck_hint),
    ("K24 — a frame two questions hold is refused (GUARD)",
     case_k24_a_frame_two_questions_hold_is_refused),
    ("K24 — a skip that disagrees with the target row is refused (GUARD)",
     case_k24_a_skip_that_disagrees_with_the_target_row_is_refused),
    ("K24 — a filed skip and a pick on one frame are both refused (GUARD)",
     case_k24_a_filed_skip_and_a_pick_on_one_frame_are_both_refused),
    ("K24 — a skip under its own question is unchanged (GUARD)",
     case_k24_a_skip_under_its_own_question_is_unchanged),
    ("K24 — a filed skip without confirm is still refused (GUARD)",
     case_k24_a_filed_skip_without_confirm_is_still_refused),
    ("W2-7 — a several-animal photo says what the name is for (REPRODUCTION)",
     case_w27_a_several_animal_photo_says_what_the_name_is_for),
    ("W2-7 — the several line is never an answer (GUARD)",
     case_w27_the_several_line_is_never_an_answer),
    ("W2-7 — an older page keeps its sentence (GUARD)",
     case_w27_an_older_page_keeps_its_sentence),
    ("U2-13 — a web page says only home or away (REPRODUCTION)",
     case_u213_a_web_page_says_only_home_or_away),
    ("U2-13 — a pack away_km decides the web word (GUARD)",
     case_u213_a_pack_away_km_decides_the_web_word),
]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    VERBOSE = args.verbose

    results = [run_case(name, fn) for name, fn in CASES]
    passed = sum(1 for r in results if r is True)
    skipped = sum(1 for r in results if r is None)
    ran = len(CASES) - skipped
    print(f"\n{passed}/{ran} photo_memory (VS-4) cases passed"
          + (f", {skipped} skipped" if skipped else ""))
    sys.exit(0 if passed == ran else 1)


if __name__ == "__main__":
    main()
