#!/usr/bin/env python3
"""FIX7 (U7-1) cases — `photo_subjects.py review --detach <draft> [--into]`.

A checkpoint `same` answer joins a draft to a confirmed pet and writes the
pet's id onto the photos the owner picked. Render names the folder from that
id, and it outranks the agent's own `identify` agree on the same photo. In
UAT01-7 a wrong pick kept two folders on the wrong pet after `--prune --drop`,
because nothing took the id back (LL-PHO-202). A detach does.

Every fixture is synthetic: invented names (`Name-One`), invented paths, a
pack copied from the shipped template.

  ./.venv/bin/python3 tests/detach_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import photo_evidence  # noqa: E402
import photo_plan  # noqa: E402
import photo_profile  # noqa: E402
import photo_subjects as psub  # noqa: E402

PY = str(ROOT / ".venv" / "bin" / "python3")
if not Path(PY).exists():
    PY = sys.executable
SCRIPT = str(ROOT / "scripts" / "photo_subjects.py")
TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

WINNER, AGREE, DRAFT, OTHER = "subj-0001", "subj-0002", "subj-0003", "subj-0004"
SWEPT = "subj-0005"
REF_C, KEPT_SOURCE = "c" * 64, "/raw/IMG_0009.HEIC"
# shares REF_A's first 12 characters — the short ref `review` prints
REF_D, TWIN_SOURCE = "a" * 12 + "d" * 52, "/raw/IMG_0010.HEIC"
REF_A, REF_B = "a" * 64, "b" * 64
PICKED, UNPICKED, ELSEWHERE = ("/raw/IMG_0001.HEIC", "/raw/IMG_0002.HEIC",
                               "/raw/IMG_0003.HEIC")
VERBOSE = False
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def log(msg):
    if VERBOSE:
        print(f"      {msg}")


def make_pack(root, owner="someone"):
    pack_dir = Path(root) / owner
    shutil.copytree(TEMPLATE, pack_dir)
    for path in list(pack_dir.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", owner)))
    pf = pack_dir / photo_profile.PROFILE_NAME
    pf.write_text(pf.read_text(encoding="utf-8").replace("{{SLUG}}", owner)
                  .replace("{{DISPLAY}}", owner), encoding="utf-8")
    return pack_dir


def look(wd, path, ref, sample):
    return {"path": path, "sample": sample, "provenance": photo_evidence.VIEWED,
            "label": "a cat", "vec_ref": ref, "captured": "2031-03-01 10:00",
            "see_report": str(wd / "classify" / "batch-01" / "see-report.json"),
            "workdir": str(wd), "batch": 1, "run_id": "see-test"}


def entry(path, sample, subject_id, identified=()):
    out = {"path": path, "sample": sample, "provenance": photo_evidence.VIEWED,
           "label": "a cat", "subject_provenance": photo_evidence.VIEWED,
           "subjects": [{"subject_kind": "cat", "subject_id": subject_id}]}
    if identified:
        out["identified"] = [{"subject_id": s, "view": v} for s, v in identified]
    return out


def build(tmp, agree=True):
    """The state a wrong `same` pick leaves: DRAFT joined to WINNER, its picked
    photo recorded as WINNER, while the agent had agreed AGREE on it. ->
    (workspace, work dir, pack dir)."""
    workspace = Path(tmp) / "workspace"
    working = workspace / "Working Files"
    working.mkdir(parents=True)
    pack_dir = make_pack(working / "photo-memory")
    (working / "collection.json").write_text(json.dumps({
        "collection": "TESTBOX", "owner": "someone",
        "memory_root": str(working / "photo-memory")}))
    wd = working / "203103__"
    bdir = wd / "classify" / "batch-01"
    (bdir / "samples").mkdir(parents=True)
    samples = {PICKED: "a.jpg", UNPICKED: "b.jpg", ELSEWHERE: "c.jpg"}
    for name in samples.values():
        (bdir / "samples" / name).write_bytes(PNG)
    (bdir / "see-report.json").write_text(json.dumps({
        "engine": "test", "batch": 1, "clusters": [], "provisional": [],
        "selected": [{"path": p, "sample": s} for p, s in samples.items()]}))
    (bdir / "see-labels.json").write_text(json.dumps({
        "engine": "test", "batch": 1, "labels": [
            entry(PICKED, "a.jpg", WINNER,
                  [(AGREE, "I-0001")] if agree else ()),
            entry(UNPICKED, "b.jpg", WINNER, [(WINNER, "I-0002")]),
            entry(ELSEWHERE, "c.jpg", WINNER)]}))
    look_a, look_b = look(wd, PICKED, REF_A, "a.jpg"), look(wd, UNPICKED, REF_B, "b.jpg")
    evidence = {"batch": 1, "unit": "203103__", "run_id": "see-test",
                "state": "new", "files": 2, "looks": [look_a, look_b]}
    carried = {k: v for k, v in evidence.items() if k != "looks"}
    carried.update(files=1, looks=[dict(look_a)])
    own = {"batch": 1, "unit": "203103__", "run_id": "see-test", "state": "new",
           "files": 5, "looks": [look(wd, KEPT_SOURCE, REF_C, "z.jpg")]}
    exemplars = [{"vec_ref": ref, "source": src, "added": "2031-03-02",
                  "captured": "2031-03-01 10:00", "confirmed_by": "viewed-image"}
                 for ref, src in ((REF_A, PICKED), (REF_C, KEPT_SOURCE))]
    subjects = [
        {"subject_id": WINNER, "name": "Name-One", "who": "Name-One",
         "kind": "cat", "status": psub.STATUS_CONFIRMED, "exemplars": exemplars,
         "evidence": [own, carried],
         "absorbed_drafts": [{"subject_id": DRAFT, "files": 2, "score": None,
                              "at": "2031-03-02"},
                             {"subject_id": SWEPT, "files": 1, "score": 0.9,
                              "at": "2031-03-02"}]},
        {"subject_id": SWEPT, "name": None, "kind": "cat", "files": 1,
         "status": psub.STATUS_ABSORBED, "absorbed_by": WINNER,
         "absorbed_at_score": 0.9, "exemplars": []},
        {"subject_id": AGREE, "name": "Name-Two", "who": "Name-Two",
         "kind": "cat", "status": psub.STATUS_CONFIRMED,
         "exemplars": [{"vec_ref": REF_D, "source": TWIN_SOURCE,
                        "added": "2031-03-02", "captured": "2031-03-01 11:00",
                        "confirmed_by": "viewed-image"}]},
        {"subject_id": DRAFT, "name": None, "kind": "cat", "files": 2,
         "status": psub.STATUS_ABSORBED, "absorbed_by": WINNER,
         "absorbed": {"at": "2031-03-02", "answered": True,
                      "src": "memory-review_C2.md Q1", "was": "ai-drafted"},
         "exemplars": [], "evidence": [evidence]},
        {"subject_id": OTHER, "name": "Name-Three", "who": "Name-Three",
         "kind": "cat", "status": psub.STATUS_CONFIRMED, "exemplars": []},
    ]
    reg = pack_dir / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text(encoding="utf-8"))
    data["subjects"] = subjects
    reg.write_text(json.dumps(data))
    import numpy as np
    (reg.parent / psub.VECTORS_DIRNAME).mkdir(exist_ok=True)
    np.save(reg.parent / psub.VECTORS_DIRNAME / f"{WINNER}.npy",
            np.eye(2, 8, dtype=np.float32))
    np.save(reg.parent / psub.VECTORS_DIRNAME / f"{AGREE}.npy",
            np.eye(1, 8, dtype=np.float32))
    (reg.parent / psub.IDENTITY_VECTORS_DIRNAME).mkdir(exist_ok=True)
    np.savez(reg.parent / psub.IDENTITY_VECTORS_DIRNAME / f"{WINNER}.npz",
             **{REF_A: np.ones(4, np.float32), REF_C: np.zeros(4, np.float32)})
    (reg.parent / "memorize-audit.jsonl").write_text(json.dumps({
        "at": "2031-03-02", "by": "Claude User", "decision": "attached",
        "into": WINNER, "looks": 1, "reason": "memory-review_C2.md Q1",
        "subject_id": DRAFT, "vec_refs": [REF_A], "was": "ai-drafted"}) + "\n")
    return workspace, wd, pack_dir


def clean_env():
    return {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}


def review(cwd, *args, env=None):
    return subprocess.run([PY, SCRIPT, "review", *args], capture_output=True,
                          text=True, cwd=str(cwd), env=env or clean_env())


def labels(wd):
    doc = json.loads((wd / "classify" / "batch-01" / "see-labels.json").read_text())
    return {e["path"]: e for e in doc["labels"]}


def named(wd, path):
    return photo_evidence.subject_list(labels(wd)[path])[0].get("subject_id")


# ---------------------------------------------------------------------------

@case
def a_detach_restores_the_agents_agree(tmp):
    """REPRODUCTION. The UAT01-7 shape: the picked photo names the wrong pet
    and the agent's agree on it is still on disk. On `b58f0fd` there is no
    `--detach` and the photo keeps the wrong id."""
    _, wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    assert named(wd, PICKED) == AGREE, (named(wd, PICKED), got.stdout)
    pack = photo_profile.resolve_pack(explicit=pack_dir / photo_profile.PROFILE_NAME)
    cols = photo_plan.visual_columns(wd, [1], pack.profile, pack)[PICKED]
    assert cols.get("who") == "Name-Two", cols
    log(f"picked photo -> {named(wd, PICKED)}, who {cols.get('who')}")


@case
def photos_the_join_did_not_pick_keep_their_name(tmp):
    """GUARD. A photo on the draft that nobody picked (the agent agreed the
    pet on it) and a photo off the draft both keep the pet."""
    _, wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    assert named(wd, UNPICKED) == WINNER and named(wd, ELSEWHERE) == WINNER, \
        (named(wd, UNPICKED), named(wd, ELSEWHERE))
    entry_a = labels(wd)[PICKED]
    assert entry_a["provenance"] == photo_evidence.VIEWED and "preserved" not in entry_a
    assert entry_a["identified"] == [{"subject_id": AGREE, "view": "I-0001"}]


@case
def with_no_agree_the_photo_goes_back_to_the_draft(tmp):
    """GUARD. No agree and no replaced id recorded: the released draft."""
    _, wd, pack_dir = build(tmp, agree=False)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    assert named(wd, PICKED) == DRAFT, named(wd, PICKED)


@case
def with_no_agree_the_id_the_confirm_replaced_comes_back(tmp):
    """REPRODUCTION. A confirm that overwrote an earlier id audits it
    (`see-label replaced`); with no agree on the photo that id is restored,
    not the draft."""
    _, wd, pack_dir = build(tmp, agree=False)
    audit = pack_dir / "photo-subjects" / "memorize-audit.jsonl"
    with audit.open("a") as fh:
        fh.write(json.dumps({"decision": "see-label replaced",
                             "subject_id": WINNER, "replaced": OTHER,
                             "path": PICKED, "at": "2031-03-02"}) + "\n")
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    assert named(wd, PICKED) == OTHER, (named(wd, PICKED), got.stdout)


@case
def into_names_the_photo_as_another_pet(tmp):
    """REPRODUCTION (new capability). `--into` beats the agree."""
    _, wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT,
                 "--into", OTHER, "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    assert named(wd, PICKED) == OTHER, named(wd, PICKED)


def registry_of(pack_dir):
    pack = photo_profile.resolve_pack(explicit=pack_dir / photo_profile.PROFILE_NAME)
    return psub.load(pack=pack)


@case
def a_detach_releases_that_one_draft_and_no_other(tmp):
    """REPRODUCTION. The joined draft is a draft again, askable, off the
    winner's list; the other draft the winner absorbed stays absorbed."""
    _, _wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    reg = registry_of(pack_dir)
    draft, winner, swept = (reg.get_literal(DRAFT), reg.get_literal(WINNER),
                            reg.get_literal(SWEPT))
    assert draft.status == psub.STATUS_DRAFT and not draft.record.get("absorbed_by"), \
        draft.record
    assert draft.record.get(psub.REOPENED_FLAG) is True, draft.record
    rows = [r["subject_id"] for r in winner.record.get("absorbed_drafts") or []]
    assert rows == [SWEPT], rows
    assert swept.status == psub.STATUS_ABSORBED and \
        swept.record.get("absorbed_by") == WINNER, swept.record
    assert winner.status == psub.STATUS_CONFIRMED and winner.name == "Name-One"


@case
def a_detach_drops_the_exemplar_that_join_memorized(tmp):
    """REPRODUCTION. The picked photo's exemplar leaves the pet with its CLIP
    row and its identity vector; the pet's other exemplar stays, and no cap
    runs."""
    import numpy as np
    _, _wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    reg = registry_of(pack_dir)
    winner = reg.get_literal(WINNER)
    assert [e["vec_ref"] for e in winner.exemplars] == [REF_C], winner.exemplars
    V = np.load(reg.vectors_path(WINNER))
    assert V.shape == (1, 8) and float(V[0][1]) == 1.0, V
    with np.load(reg.identity_vectors_path(WINNER)) as store:
        assert list(store.files) == [REF_C], store.files


@case
def the_looks_that_join_carried_leave_the_pets_evidence(tmp):
    """REPRODUCTION. The carried look goes and its emptied entry with it; the
    pet's own entry from the same batch keeps its look and its count."""
    _, _wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    evidence = registry_of(pack_dir).get_literal(WINNER).record["evidence"]
    assert [[l["vec_ref"] for l in e["looks"]] for e in evidence] == [[REF_C]], evidence
    assert evidence[0]["files"] == 5, evidence


@case
def into_joins_the_draft_to_the_named_pet(tmp):
    """REPRODUCTION (new capability). `--into` re-joins the released draft to
    the named confirmed subject, with the picked look carried across."""
    _, _wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT,
                 "--into", OTHER, "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    reg = registry_of(pack_dir)
    draft, other = reg.get_literal(DRAFT), reg.get_literal(OTHER)
    assert draft.status == psub.STATUS_ABSORBED and \
        draft.record.get("absorbed_by") == OTHER, draft.record
    assert [r["subject_id"] for r in other.record.get("absorbed_drafts") or []] \
        == [DRAFT], other.record
    looks = [l["vec_ref"] for e in other.record.get("evidence") or []
             for l in e.get("looks") or []]
    assert looks == [REF_A], looks


@case
def a_detach_writes_one_detached_audit_row(tmp):
    """REPRODUCTION. One `detached` row names the draft, where it came from,
    the photos restored and what was dropped."""
    _, _wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT,
                 "--reason", "wrong cat", "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    rows = [r for r in registry_of(pack_dir).audit_trail()
            if r.get("decision") == "detached"]
    assert len(rows) == 1, rows
    row = rows[0]
    assert (row["subject_id"], row["from"], row["into"]) == (DRAFT, WINNER, None), row
    assert row["see_labels"] == [{"path": PICKED, "old": WINNER, "new": AGREE}], row
    assert row["exemplars_dropped"] == [REF_A] and row["evidence_looks_removed"] == 1, row
    assert row["reason"] == "wrong cat", row


@case
def a_detach_dry_run_says_the_reason_it_would_record(tmp):
    """REPRODUCTION (FIX8 F8-3, UAT01-8 F6). The dry run never mentioned
    `--reason`, so a reason passed there read as silently dropped."""
    _, _wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT,
                 "--reason", "the tabby is not this pet")
    assert got.returncode == 0, got.stdout + got.stderr
    assert 'reason: "the tabby is not this pet"' in got.stdout, got.stdout


@case
def a_detach_with_no_reason_says_none_is_recorded(tmp):
    """REPRODUCTION (F8-3). Dry run and --go both say it; --go still writes."""
    _, wd, pack_dir = build(tmp)
    notice = "no --reason given — the audit row will record none"
    dry = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT)
    assert dry.returncode == 0 and notice in dry.stdout, dry.stdout
    go = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert go.returncode == 0 and notice in go.stdout, go.stdout
    assert named(wd, PICKED) == AGREE, go.stdout


@case
def review_help_lists_detach_among_the_verbs_that_record_a_reason(tmp):
    """REPRODUCTION (F8-3). The help said --unconfirm/--revive/--merge only."""
    got = review(tmp, "--help")
    text = " ".join(got.stdout.split())
    start = text.rindex("--reason REASON")
    assert "--detach" in text[start:start + 120], text[start:start + 120]


@case
def detach_into_states_one_outcome(tmp):
    """REPRODUCTION (FIX8 F8-4, UAT01-8 F5). With --into the output said the
    draft "is asked about at the next checkpoint" AND that it joins another
    pet — two opposite end states, on the dry run and on --go."""
    _, _wd, pack_dir = build(tmp)
    for extra, verb in (((), "would move"), (("--go",), "moved")):
        got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT,
                     "--into", OTHER, *extra)
        assert got.returncode == 0, got.stdout + got.stderr
        assert "asked about at the next checkpoint" not in got.stdout, got.stdout
        assert "is a draft again" not in got.stdout, got.stdout
        assert f"{verb} {DRAFT} from {WINNER} to {OTHER}" in got.stdout, got.stdout


@case
def detach_without_into_still_says_the_draft_is_asked_again(tmp):
    """GUARD (F8-4). The plain detach keeps its draft line."""
    _, _wd, pack_dir = build(tmp)
    dry = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT)
    assert (f"would release {DRAFT} from {WINNER}: it becomes a draft again "
            "and is asked about at the next checkpoint") in dry.stdout, dry.stdout
    go = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert (f"released {DRAFT} from {WINNER}: it is a draft again and is "
            "asked about at the next checkpoint") in go.stdout, go.stdout


@case
def a_draft_moved_into_another_pet_can_be_detached_again(tmp):
    """GUARD. After `--into`, the new join is the one a second detach reads,
    so the photo can come back out of that pet too."""
    _, wd, pack_dir = build(tmp)
    first = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT,
                   "--into", OTHER, "--go")
    assert first.returncode == 0 and named(wd, PICKED) == OTHER, first.stdout
    again = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert again.returncode == 0, again.stdout + again.stderr
    assert named(wd, PICKED) == AGREE, (named(wd, PICKED), again.stdout)
    assert registry_of(pack_dir).get_literal(DRAFT).status == psub.STATUS_DRAFT


@case
def a_detach_is_a_dry_run_until_go(tmp):
    """GUARD. The dry run names the file and the change, and writes nothing."""
    _, wd, pack_dir = build(tmp)
    path = wd / "classify" / "batch-01" / "see-labels.json"
    before = path.read_bytes()
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT)
    assert got.returncode == 0, got.stdout + got.stderr
    assert path.read_bytes() == before, "a dry run wrote see-labels"
    assert "would restore 1 photo(s)" in got.stdout, got.stdout
    assert f"IMG_0001.HEIC: {WINNER} -> {AGREE}" in got.stdout, got.stdout
    assert "dry run" in got.stdout, got.stdout


@case
def the_dry_run_lists_every_write_and_changes_nothing(tmp):
    """REPRODUCTION (U7-3's rule on this verb). The release, the exemplar by
    its short ref, the carried look, the --into join and the audit row are
    all said; no pack file moves."""
    _, _wd, pack_dir = build(tmp)
    subjects_dir = pack_dir / "photo-subjects"
    before = {p: p.read_bytes() for p in subjects_dir.rglob("*") if p.is_file()}
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT,
                 "--into", OTHER)
    assert got.returncode == 0, got.stdout + got.stderr
    said = got.stdout
    for want in (
                 f"would drop 1 exemplar(s) that join memorized ({REF_A[:12]})",
                 "remove 1 look(s)",
                 f"would move {DRAFT} from {WINNER} to {OTHER}: it stays "
                 f"joined, now to {OTHER}, and is not asked about again",
                 "would write one `detached` row", "dry run"):
        assert want in said, (want, said)
    after = {p: p.read_bytes() for p in subjects_dir.rglob("*") if p.is_file()}
    assert after == before, "a dry run moved the pack"


@case
def a_detach_prints_its_plan_and_not_the_whole_listing(tmp):
    """REPRODUCTION (Lead, 20260916). The plan was followed by the listing
    every `review` prints — one block per subject, ~490 lines on the tester's
    pack — so the plan scrolled away. `review` on its own is unchanged, and
    `--json` still holds the full report."""
    _, _wd, pack_dir = build(tmp)
    out = Path(tmp) / "review.json"
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT,
                 "--json", str(out))
    assert got.returncode == 0, got.stdout + got.stderr
    assert "subject registry:" not in got.stdout, got.stdout
    assert "would restore 1 photo(s)" in got.stdout, got.stdout
    assert "review` on its own prints the full listing" in got.stdout, got.stdout
    assert len(got.stdout.splitlines()) < 20, got.stdout
    doc = json.loads(out.read_text())
    assert len(doc["subjects"]) == 5, doc["count"]
    plain = review(tmp, "--profile", str(pack_dir))
    assert "subject registry:" in plain.stdout, plain.stdout
    assert f"absorbed draft {DRAFT}" in plain.stdout, plain.stdout


@case
def a_refused_detach_exits_2_and_writes_nothing(tmp):
    """GUARD. Not a joined draft; `--into` a subject that is not confirmed;
    `--into` the subject it is already in."""
    _, wd, pack_dir = build(tmp)
    path = wd / "classify" / "batch-01" / "see-labels.json"
    before = path.read_bytes()
    for argv in (["--detach", AGREE], ["--detach", DRAFT, "--into", DRAFT],
                 ["--detach", DRAFT, "--into", WINNER], ["--into", OTHER]):
        got = review(tmp, "--profile", str(pack_dir), *argv, "--go")
        assert got.returncode == 2, (argv, got.returncode, got.stdout)
    assert path.read_bytes() == before, "a refused detach wrote see-labels"


@case
def a_work_dir_that_does_not_hold_the_photo_is_refused_by_path(tmp):
    """GUARD (L7). A named work dir that is not where the look was seen: the
    labels there are not this work dir's to write."""
    _, wd, pack_dir = build(tmp)
    other = Path(tmp) / "elsewhere"
    other.mkdir()
    path = wd / "classify" / "batch-01" / "see-labels.json"
    before = path.read_bytes()
    got = review(tmp, str(other), "--profile", str(pack_dir), "--detach", DRAFT,
                 "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    assert path.read_bytes() == before, "wrote outside the named work dir"
    assert "not inside the work dir" in got.stdout, got.stdout


# -- U7-2: review shows the ids the repair verbs take ----------------------

@case
def review_lists_each_absorbed_draft_and_each_exemplar(tmp):
    """REPRODUCTION (U7-2). The SKILL said `review` shows each exemplar's
    vec_ref; on b58f0fd text and --json held 0. Each absorbed draft is listed
    with its photos and a crop, each exemplar with its ref and photo."""
    _, wd, pack_dir = build(tmp)
    crop = wd / "review-crops" / f"{REF_A}_d0.jpg"
    crop.parent.mkdir()
    crop.write_bytes(PNG)
    out = Path(tmp) / "review.json"
    got = review(tmp, "--profile", str(pack_dir), "--json", str(out))
    assert got.returncode == 0, got.stdout + got.stderr
    said = got.stdout
    assert (f"absorbed draft {DRAFT}: IMG_0001.HEIC, IMG_0002.HEIC  crop: {crop}"
            in said), said
    assert f"absorbed draft {SWEPT}: (no photo on record)" in said, said
    assert f"exemplar {REF_A[:12]}  IMG_0001.HEIC" in said, said
    doc = json.loads(out.read_text())
    winner = [s for s in doc["subjects"] if s["subject_id"] == WINNER][0]
    assert {"vec_ref": REF_A, "file": "IMG_0001.HEIC"} in winner["exemplar_refs"], winner
    listed = winner["absorbed_drafts"][0]
    assert listed["subject_id"] == DRAFT and listed["crops"][0] == str(crop), listed


@case
def the_crop_folder_is_the_one_review_pages_write(tmp):
    """GUARD. `photo_subjects` spells the crop folder because photo_memory
    imports it; the two must not drift."""
    import photo_memory
    assert psub.CROP_DIR == photo_memory.CROP_DIR, (psub.CROP_DIR, photo_memory.CROP_DIR)


# -- U7-2: --drop takes the ref review prints -------------------------------

@case
def drop_takes_the_short_ref_review_prints(tmp):
    """REPRODUCTION (Lead ruling 20260916). `review` prints 12 characters and
    `--drop` matched the full ref only, so the listing could not be used."""
    _, _wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--prune",
                 "--drop", REF_C[:12], "--go")
    assert got.returncode == 0, got.stdout + got.stderr
    kept = [e["vec_ref"] for e in registry_of(pack_dir).get_literal(WINNER).exemplars]
    assert kept == [REF_A], kept


@case
def an_ambiguous_drop_prefix_is_refused_with_its_candidates(tmp):
    """REPRODUCTION. Two exemplars share those 12 characters: which to drop
    has not been said, so both are named and nothing is written."""
    _, _wd, pack_dir = build(tmp)
    reg_file = pack_dir / "photo-subjects" / "subjects.json"
    before = reg_file.read_bytes()
    got = review(tmp, "--profile", str(pack_dir), "--prune",
                 "--drop", REF_A[:12], "--go")
    assert got.returncode == 2, (got.returncode, got.stdout)
    assert "matches 2 exemplars" in got.stdout, got.stdout
    for want in (WINNER, AGREE, "IMG_0001.HEIC", "IMG_0010.HEIC"):
        assert want in got.stdout, (want, got.stdout)
    assert reg_file.read_bytes() == before, "a refused --drop wrote the registry"


@case
def a_short_or_unknown_drop_ref_is_refused(tmp):
    """GUARD. Under 8 characters is a guess whatever it matches; a prefix
    nothing starts with is said, never silently ignored."""
    _, _wd, pack_dir = build(tmp)
    short = review(tmp, "--profile", str(pack_dir), "--prune",
                   "--drop", REF_A[:6], "--go")
    assert short.returncode == 2 and "shorter than 8 characters" in short.stdout, short.stdout
    unknown = review(tmp, "--profile", str(pack_dir), "--prune",
                     "--drop", "e" * 12, "--go")
    assert unknown.returncode == 2 and "no exemplar starts with" in unknown.stdout, \
        unknown.stdout


# -- U7-3: the --unconfirm dry run says what it releases ---------------------

@case
def the_unconfirm_dry_run_lists_the_drafts_it_would_release(tmp):
    """REPRODUCTION (U7-3). On b58f0fd only --go named the released drafts
    (UAT01-7: subj-0098 appeared only after the write). The dry run lists
    both drafts under the name and says `check` will refuse agrees on it."""
    _, _wd, pack_dir = build(tmp)
    reg_file = pack_dir / "photo-subjects" / "subjects.json"
    before = reg_file.read_bytes()
    got = review(tmp, "--profile", str(pack_dir), "--unconfirm", WINNER)
    assert got.returncode == 0, got.stdout + got.stderr
    assert (f"2 draft(s) joined or absorbed under that name would be released "
            f"and asked about again: {DRAFT}, {SWEPT}") in got.stdout, got.stdout
    assert "fails `photo_index.py check`" in got.stdout, got.stdout
    assert reg_file.read_bytes() == before, "a dry run wrote the registry"


# -- one case per pack route (Operational Rule 6, LL-PHO-132) ---------------

@case
def route_profile_flag(tmp):
    _, wd, pack_dir = build(tmp)
    got = review(tmp, "--profile", str(pack_dir), "--detach", DRAFT, "--go")
    assert got.returncode == 0 and named(wd, PICKED) == AGREE, got.stdout + got.stderr


@case
def route_photo_profile_env(tmp):
    _, wd, pack_dir = build(tmp)
    env = {**clean_env(), "PHOTO_PROFILE": str(pack_dir)}
    got = review(tmp, "--detach", DRAFT, "--go", env=env)
    assert got.returncode == 0 and named(wd, PICKED) == AGREE, got.stdout + got.stderr


@case
def route_collection_json_via_work_dir(tmp):
    workspace, wd, _ = build(tmp)
    got = review(workspace, str(wd), "--detach", DRAFT, "--go")
    assert got.returncode == 0 and named(wd, PICKED) == AGREE, got.stdout + got.stderr


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose
    passed = 0
    for fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="detach_"))
        try:
            fn(tmp)
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"  ok    {fn.__name__}")
            passed += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{passed}/{len(CASES)} detach cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
