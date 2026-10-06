#!/usr/bin/env python3
"""Unit cases for the plan stage: the order `route()` tries its branches in,
and the WHO/WHAT columns `visual_columns()` renders beside them.

An `overrides` entry names a DAY. Until LL-PHO-96 it was evaluated before
every per-file classifier, so an overridden day's screenshots, its files whose
real format could not be read, and its G-2 screen-size candidates all went
straight into the trip folder — untagged, so the plan report counted none of
them and nothing said it had happened.

The golden harness cannot see this. It replays four frozen dumps, and in every
one of them the set of overridden days and the set of files any classifier
would have caught do not intersect: routing them in either order reproduces
the same rows. So a green replay says nothing about the ordering, and these
cases are the only thing that holds it.

`visual_columns()` has the same problem from the other end: it reads the
subject REGISTRY, and no golden fixture carries one that exercises it — the
frozen dumps were planned before the see stage existed, so every replay takes
the `no labels -> None` branch and the whole registry half of the function is
unrun. The cases below build a synthetic pack from the shipped template and
put the states that matter into it by hand. ⛔ Deliberately NOT
`tests/golden/index.json`: that file records what one owner's drive actually
holds, and a test that needs a tombstone in it would be asking a fixture to
carry a state its owner never had.

  python3 tests/photo_plan_cases.py [-v]

Exit 0 = pass. Every row is written out here; nothing on a drive is read.
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_evidence  # noqa: E402
import photo_plan  # noqa: E402
import photo_name  # noqa: E402
import photo_profile  # noqa: E402
import photo_subjects  # noqa: E402

EN = {"language": "en"}
MSG = photo_profile.messages(EN)
DEST_ROOT = "/sorted"
OV_DAY = "2026-01-01"
OV_PATH = "/sorted/20260101_conference"
# A plan whose destination is a trip folder, with the whole of OV_DAY sent
# somewhere else. `legs` overlaps the same day on purpose: the override has to
# keep beating the leg branch, which is the thing it is actually for.
PLAN = {"dest": {"mode": "new", "path": "/sorted/20260101_trip"},
        "legs": [{"name": "day1", "from": OV_DAY, "to": OV_DAY}],
        "overrides": [{"dates": [OV_DAY], "dest": OV_PATH,
                       "reason": "conference, not the trip"}]}
# 1290x2796 is a phone screen; a file at that size with no camera tags is what
# G-2 calls a candidate.
SCREEN = photo_plan.screen_candidate_dims({("1290", "2796")})

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def row(name, ftype="JPEG", w=4032, h=3024, make="Apple", model="iPhone 15",
        day=OV_DAY):
    return {"FileName": name, "SourceFile": f"/raw/{name}", "FileType": ftype,
            "ImageWidth": str(w), "ImageHeight": str(h), "Make": make,
            "Model": model, "_day": day, "GPSPosition": "-",
            "DateTimeOriginal": day.replace("-", ":") + " 10:00:00"}


def route(r, dupes=None, format_known=True):
    return photo_plan.route(r, PLAN, DEST_ROOT, dupes or {}, MSG,
                            format_known=format_known, profile=EN,
                            screen_candidates=SCREEN)


@case
def an_ordinary_photo_on_an_overridden_day_still_follows_the_override():
    """The override's whole job, and the thing every case below must not
    break: an override that stopped applying would be a worse bug than the
    one this ordering fixes."""
    action, dest, note, tags = route(row("IMG_100.JPG"))
    return (action == "copy" and dest == OV_PATH and not tags
            and note == "conference, not the trip"), \
        f"{action} {dest} {tags} {note!r}"


@case
def the_override_still_beats_the_leg_it_overlaps():
    """`legs` covers the same day. Whichever leg would have claimed the file,
    the override is the more specific instruction and wins."""
    _a, dest, _n, _t = route(row("IMG_101.JPG"))
    return dest == OV_PATH, f"{dest} (leg dest would be .../day1)"


@case
def a_screenshot_on_an_overridden_day_goes_to_the_screenshots_bucket():
    """D13: a screenshot is a screenshot whatever else was happening that
    day. Before the reorder it landed in OV_PATH with an empty tag set, so
    the plan report's screenshot count did not include it."""
    _a, dest, _n, tags = route(
        row("Screenshot_20260101_101010.png", ftype="PNG", w=1290, h=2796,
            make="-", model="-"))
    return (dest == f"{DEST_ROOT}/20260100_Screenshots"
            and tags == {"screenshot"}), f"{dest} {tags}"


@case
def a_file_whose_format_is_unreadable_goes_to_others_on_an_overridden_day():
    """D13 clause 1. `format_known=False` means exiftool could not say what
    the file really is — that needs a human, and an override date is not a
    statement about the file's format."""
    _a, dest, _n, tags = route(row("IMG_102.JPG"), format_known=False)
    return (dest == f"{DEST_ROOT}/20260100_others"
            and tags == {"unknown_format"}), f"{dest} {tags}"


@case
def a_screen_size_candidate_on_an_overridden_day_reaches_triage():
    """G-2. The size is unconfirmed, so the file goes to human triage rather
    than into the trip — an override must not launder it into the folder."""
    _a, dest, note, tags = route(
        row("IMG_103.PNG", ftype="PNG", w=1290, h=2796, make="-", model="-"))
    return (dest == f"{DEST_ROOT}/20260100_To-be-checked"
            and tags == {"screen_candidate"} and "1290x2796" in note), \
        f"{dest} {tags} {note}"


@case
def a_camera_tagged_photo_at_a_candidate_size_still_follows_the_override():
    """The G-2 branch only claims files with no camera tags. One that has
    them is an ordinary photo of the overridden day, and still goes to the
    override — the reorder must not have widened the classifier."""
    _a, dest, _n, tags = route(row("IMG_104.JPG", w=1290, h=2796))
    return dest == OV_PATH and not tags, f"{dest} {tags}"


@case
def a_duplicate_on_an_overridden_day_is_still_skipped():
    """Copy-only reversibility (SPEC Q7) outranks everything, override
    included: the file already exists on the drive, so nothing is written.
    The note is now the dedupe's own sentence rather than the override's
    reason — the reason explained a copy that no longer happens."""
    r = row("IMG_105.JPG")
    action, dest, note, tags = route(r, dupes={r["SourceFile"]: "/sorted/old/IMG_105.JPG"})
    return (action == "skip_dupe" and dest == "/sorted/old/IMG_105.JPG"
            and note == MSG["note_already_in_existing_folder"] and not tags), \
        f"{action} {dest} {note!r} {tags}"


@case
def an_unoverridden_day_is_untouched_by_any_of_this():
    """The control: a day the override does not name routes by leg exactly as
    before."""
    _a, dest, _n, tags = route(row("IMG_106.JPG", day="2026-01-02"))
    return dest == "/sorted/20260101_trip" and not tags, f"{dest} {tags}"


@case
def an_override_dest_may_be_a_bare_string_or_a_dict():
    """`plans.json` has shipped both shapes. Neither is a classifier question,
    but the branch that unwraps them moved, so both are re-proved here."""
    plan = dict(PLAN, overrides=[{"dates": [OV_DAY],
                                  "dest": {"mode": "new", "path": OV_PATH},
                                  "reason": "r"}])
    _a, dest, _n, _t = photo_plan.route(
        row("IMG_107.JPG"), plan, DEST_ROOT, {}, MSG, profile=EN,
        screen_candidates=SCREEN)
    return dest == OV_PATH, f"{dest}"


# ---------------------------------------------------------------------------
# A6 — visual_columns(): WHO is rendered from the REGISTRY at write time, not
# from the see-label. Every case below turns on a registry state, which is the
# half no golden replay reaches.
# ---------------------------------------------------------------------------

TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"
CLASSES = photo_profile.scene_classes(EN)
RMSG = photo_profile.review_messages(EN)


def subject_record(sid, **kw):
    """One registry record, written by hand. `status` is always stated rather
    than left to Subject.status's derivation — a case about the draft marker
    must not depend on how a missing status is guessed."""
    return {"subject_id": sid, "exemplars": [], **kw}


def confirmed(sid, name, kind="cat"):
    return subject_record(sid, name=name, who=name, kind=kind,
                          status=photo_subjects.STATUS_CONFIRMED)


def drafted(sid, kind="cat", name="Whiskers"):
    """A draft CARRIES a proposed name — that is what makes the `is_draft`
    guard load-bearing. A nameless draft would take the same branch whether
    the guard was there or not."""
    return subject_record(sid, kind=kind, name=name,
                          status=photo_subjects.STATUS_DRAFT)


def tombstone(sid, winner):
    return subject_record(sid, status=photo_subjects.STATUS_MERGED_INTO,
                          merged_into=winner)


def label(path, subject=None, provenance=photo_evidence.VIEWED,
          subject_provenance=photo_evidence.VIEWED, what="a cat on a wall"):
    """A see-label in the PRE-R4 shape — one `subject` object, or None.

    ⛔ Kept in the old shape on purpose, and every case above it still uses
    it. Those cases are the guarantee that a label file written before R4 —
    which is every `see-labels.json` under `tests/golden/`, and every one in
    an owner's existing work dirs — still resolves a name. Rewriting them
    into the new shape would have deleted that guarantee while showing 28
    green."""
    return {"path": path, "label": what, "provenance": provenance,
            "subject": subject, "subject_provenance": subject_provenance}


def label_r4(path, subjects, provenance=photo_evidence.VIEWED,
             subject_provenance=photo_evidence.VIEWED, what="a cat on a wall"):
    """A see-label in the R4 shape — `subjects`, a list, one entry per
    detected animal."""
    return {"path": path, "label": what, "provenance": provenance,
            "subjects": subjects, "subject_provenance": subject_provenance}


def build(root, subjects, batches, owner="fixture-owner", defaults=None):
    """A synthetic pack plus a work dir holding see-stage output.
    -> (workdir, profile, pack). The pack is copied from the shipped template
    so the layout is the one a real owner gets; only `subjects.json` is
    written by hand."""
    pack_dir = Path(root) / owner
    shutil.copytree(TEMPLATE, pack_dir)
    for path in list(pack_dir.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", owner)))
    profile_path = pack_dir / "photo-profile.json"
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8")
        .replace("{{SLUG}}", owner).replace("{{DISPLAY}}", owner),
        encoding="utf-8")
    write_registry(pack_dir, subjects, defaults)
    workdir = Path(root) / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    for n, entries in batches.items():
        batch_dir = workdir / "classify" / f"batch-{n:02d}"
        batch_dir.mkdir(parents=True)
        (batch_dir / "see-labels.json").write_text(
            json.dumps({"labels": entries}), encoding="utf-8")
    return workdir, pack_dir


def write_registry(pack_dir, subjects, defaults=None):
    """`defaults` is the pack's threshold block — the route N-9's `{3}` cap
    travels by, and the reason it is reachable from a case at all."""
    path = pack_dir / "photo-subjects" / "subjects.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["subjects"] = subjects
    if defaults is not None:
        data["defaults"] = {**(data.get("defaults") or {}), **defaults}
    path.write_text(json.dumps(data), encoding="utf-8")


def render(workdir, pack_dir, batch_numbers=(1,)):
    pack = photo_profile.resolve_pack(
        explicit=pack_dir / "photo-profile.json")
    return photo_plan.visual_columns(workdir, list(batch_numbers),
                                     pack.profile, pack)


@case
def a_plan_with_no_see_stage_output_gets_no_visual_columns():
    """The invariant the whole feature rests on: a dump classified without the
    see stage produces the same seven CSV columns it always produced, so every
    golden replay stays a comparison against the shipped decision."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")], {})
        return render(wd, pack) is None, "expected None"


@case
def a_batch_outside_this_plan_is_not_read():
    """Labels are collected per plan, not per work dir. A batch the plan does
    not name belongs to a different plan's CSV."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {2: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        return render(wd, pack, [1]) is None, "expected None"


@case
def a_confirmed_subject_prints_the_name_the_registry_holds_now():
    """N-6 / N-10a. The see-label stores only the id, so a subject renamed
    after this tree was sorted prints its CURRENT name — proved by renaming it
    between two renders of the same label file, not by reading one."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        before = render(wd, pack)["/raw/a.jpg"]
        write_registry(pack, [confirmed("subj-0001", "Bao")])
        after = render(wd, pack)["/raw/a.jpg"]
    return (before["who"] == "Lotus" and after["who"] == "Bao"
            and after["who_provenance"] == photo_evidence.VIEWED), \
        f"{before} then {after}"


@case
def an_unconfirmed_subject_prints_its_class_word_and_a_draft_marker():
    """V2-5: the operator has to see at a glance which names rest on
    unconfirmed memory. The subject HAS a proposed name and the cell must
    still not print it — an unconfirmed name in a plan CSV is indistinguishable
    from a confirmed one. The word printed instead comes from the pack's scene
    vocabulary; the engine holds no class names of its own."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [drafted("subj-0001", kind="cat")],
                         {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return (cell["who"] == CLASSES["cat"]
            and cell["who_provenance"] == photo_evidence.DRAFT + photo_evidence.VIEWED), \
        f"{cell}"


@case
def an_id_the_registry_has_never_seen_falls_back_to_the_labels_own_kind():
    """A see-label can outlive the record it named — a pack restored from an
    older copy, a subject deleted by hand. The cell must still say what the
    detector saw, marked draft, rather than printing an empty WHO."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {1: [label("/raw/a.jpg", {"subject_id": "subj-0404",
                                                   "subject_kind": "dog"})]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return (cell["who"] == CLASSES["dog"]
            and cell["who_provenance"] == photo_evidence.DRAFT + photo_evidence.VIEWED), \
        f"{cell}"


@case
def an_unknown_kind_still_prints_a_word():
    """kind_word()'s last branch. A subject whose species nobody named is not
    an empty cell."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [], {1: [label("/raw/a.jpg", {"subject_id": "subj-0404"})]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return cell["who"] == RMSG["review_kind_unknown"], f"{cell}"


@case
def a_folded_subject_id_prints_the_winners_name_with_no_draft_marker():
    """SNS-14. A label written before the fold still names the loser; `get()`
    follows `merged_into`, so this function needed no change of its own — and
    that is exactly what could regress here unnoticed. The tombstone itself is
    not confirmed, so a resolution that stopped at it would print the class
    word with a `draft:` marker instead of the winner's name."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp,
                         [confirmed("subj-0001", "Lotus"),
                          tombstone("subj-0002", "subj-0001")],
                         {1: [label("/raw/a.jpg", {"subject_id": "subj-0002"})]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return (cell["who"] == "Lotus"
            and cell["who_provenance"] == photo_evidence.VIEWED), f"{cell}"


@case
def a_sighting_with_no_id_at_all_prints_its_class_word():
    """The detector saw an animal and the identity space refused to name it.
    There is no id to look up, and the cell is still a draft."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [], {1: [label("/raw/a.jpg", {"subject_kind": "cat"})]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return (cell["who"] == CLASSES["cat"]
            and cell["who_provenance"] == photo_evidence.DRAFT + photo_evidence.VIEWED), \
        f"{cell}"


@case
def an_absent_subject_provenance_never_becomes_a_bare_draft_marker():
    """`draft:` is a prefix on a provenance claim, not a claim by itself. A
    cell with nothing to qualify must stay empty — `draft:` alone would read
    as evidence that does not exist.

    Both branches that build the prefix are here: the id that resolved to an
    unconfirmed record, and the sighting that has no id at all. They are two
    copies of the same line, so one case over one of them leaves the other
    free to drift."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [drafted("subj-0001")],
                         {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"},
                                    subject_provenance=None),
                              label("/raw/b.jpg", {"subject_kind": "cat"},
                                    subject_provenance=None)]})
        cells = render(wd, pack)
    return (all(c["who"] == CLASSES["cat"] for c in cells.values())
            and all(c["who_provenance"] == "" for c in cells.values())), \
        f"{cells}"


@case
def a_file_with_no_subject_gets_the_what_columns_and_an_empty_who():
    """Most rows are this one: a label, no animal in it. WHAT passes straight
    through from the see-label; WHO is absent rather than guessed."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {1: [label("/raw/a.jpg", None, subject_provenance=None,
                                    provenance=photo_evidence.CLIP_PROPAGATED,
                                    what="a harbour at dusk")]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return (cell["what"] == "a harbour at dusk"
            and cell["what_provenance"] == photo_evidence.CLIP_PROPAGATED
            and cell.get("who", "") == "" and cell["who_provenance"] == ""), \
        f"{cell}"


@case
def every_batch_in_the_plan_contributes_its_labels():
    """One plan spans several batches and one CSV covers all of them."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})],
                          3: [label("/raw/b.jpg", {"subject_id": "subj-0001"})]})
        cells = render(wd, pack, [1, 3])
    return (sorted(cells) == ["/raw/a.jpg", "/raw/b.jpg"]
            and all(c["who"] == "Lotus" for c in cells.values())), f"{sorted(cells)}"


@case
def every_who_provenance_is_a_claim_the_evidence_module_recognises():
    """The CSV's provenance vocabulary is closed (photo_evidence
    .PLAN_PROVENANCE). A cell holding anything else is not auditable, which is
    the entire purpose of the column."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp,
                         [confirmed("subj-0001", "Lotus"), drafted("subj-0002")],
                         {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"}),
                              label("/raw/b.jpg", {"subject_id": "subj-0002"},
                                    subject_provenance=photo_evidence.CLIP_PROPAGATED),
                              label("/raw/c.jpg", None, subject_provenance=None)]})
        cells = render(wd, pack)
    bad = {p: c["who_provenance"] for p, c in cells.items()
           if c["who_provenance"] not in ("",) + photo_evidence.PLAN_PROVENANCE}
    return not bad, f"{bad}"


# ---------------------------------------------------------------------------
# R1 — vision before plan.
#
# ⭐ REPRODUCTION, not a guard. Measured in UAT01 (20260904): all 11 plan CSVs
# were rendered at 13:47 and the see stage wrote its labels at 14:03-14:17, so
# `visual_columns()` took its `no labels -> None` branch every time. The plans
# rendered, the CSVs silently lost their WHO/WHAT columns, the files were
# copied at 13:49-13:53, and every folder was named `YYYYMMDD_cat`. Exit 0,
# no warning, 11 of 11.
#
# ⛔ The golden harness cannot hold this. Its four frozen dumps were planned
# BEFORE the see stage existed, so every replay takes the same None branch --
# a green replay is what the defect looks like, not evidence against it. That
# is stated in this file's own docstring and it is why the gate needs cases of
# its own.


@case
def an_unseen_batch_is_named_by_the_vision_gate():
    """The UAT01 condition itself: a plan whose batches have no see-stage
    output at all."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, _ = build(tmp, [confirmed("subj-0001", "Lotus")], {})
        unseen = photo_plan.batches_without_vision(wd, [1, 2])
        return unseen == [1, 2], f"expected [1, 2], got {unseen}"


@case
def a_seen_batch_clears_the_vision_gate():
    with tempfile.TemporaryDirectory() as tmp:
        wd, _ = build(tmp, [confirmed("subj-0001", "Lotus")],
                      {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        unseen = photo_plan.batches_without_vision(wd, [1])
        return unseen == [], f"expected [], got {unseen}"


@case
def a_plan_mixing_seen_and_unseen_batches_names_only_the_unseen():
    """The case a bool would lose. `visual_columns()` returns a dict as soon
    as ONE batch has labels, so a mixed plan looks served while half its files
    silently carry no WHO/WHAT -- worse than the all-unseen case, because
    nothing about the CSV looks wrong."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        unseen = photo_plan.batches_without_vision(wd, [1, 2, 3])
        served = render(wd, pack, [1, 2, 3]) is not None
        return unseen == [2, 3] and served, \
            f"unseen={unseen} columns_rendered={served}"


@case
def the_gate_reads_the_same_file_visual_columns_does():
    """If these two ever disagree the gate passes a plan that then renders no
    columns -- the exact silence R1 exists to end."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {4: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        gate_ok = photo_plan.batches_without_vision(wd, [4]) == []
        cols_ok = render(wd, pack, [4]) is not None
        return gate_ok == cols_ok, f"gate={gate_ok} columns={cols_ok}"


def runnable_workdir(root, seen_batches):
    """A work dir complete enough for `photo_plan.py --plan 1` to render:
    pack, batches.json, plans.json, manifest.csv. `seen_batches` decides which
    batches get see-stage output, so the same builder makes both the UAT01
    condition and its fix."""
    wd, pack = build(root, [confirmed("subj-0001", "Lotus")], seen_batches)
    (wd / "batches.json").write_text(json.dumps({
        "source": "/raw", "main_files": 1, "no_exif_date": 0, "batches": [
        {"batch": 1, "from": "2026-01-01", "to": "2026-01-02",
         "status": "classified", "label": "day out"}]}), encoding="utf-8")
    (wd / "plans.json").write_text(json.dumps({
        "dest_root": str(Path(root) / "sorted"),
        "plans": [{"plan": 1, "title": "B1", "batches": [1],
                   "dest": {"mode": "new",
                            "path": str(Path(root) / "sorted" / "20260101_x")}}]
    }), encoding="utf-8")
    (wd / "manifest.csv").write_text(
        "SourceFile,FileName,FileType,FileSize,DateTimeOriginal,CreateDate,"
        "GPSPosition,Make,Model,Software,ImageWidth,ImageHeight,Duration,"
        "UserComment\n"
        "/raw/a.jpg,a.jpg,JPEG,100,2026:01:01 10:00:00,-,-,Apple,-,-,"
        "4032,3024,-,-\n", encoding="utf-8")
    return wd, pack


def plan_run(wd, pack, *extra):
    env = dict(os.environ)
    env[photo_profile.ENV_VAR] = str(pack / "photo-profile.json")
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "photo_plan.py"), str(wd),
         "--plan", "1", *extra],
        capture_output=True, text=True, env=env)


@case
def planning_an_unseen_batch_is_refused_and_the_message_says_why():
    """⭐ THE UAT01 REPRODUCTION. On the unfixed engine this exits 0 and writes
    a CSV with no WHO/WHAT columns -- which is how 11 of 11 folders were named
    `YYYYMMDD_cat` with nothing reported. The refusal has to name the batch and
    the consequence, not just stop: a gate that says only `refused` reproduces
    the silence it replaces in a different tone."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = runnable_workdir(tmp, {})
        r = plan_run(wd, pack)
        text = r.stdout + r.stderr
        csv_written = (wd / "plan" / "plan_P1-files.csv").exists()
        return (r.returncode != 0 and "B1" in text and "photo_see" in text
                and not csv_written), \
            f"rc={r.returncode} csv={csv_written} out={text[:300]!r}"


@case
def a_printed_command_survives_spaces_in_both_paths():
    """⭐ REPRODUCTION (K3). The refusal's commands printed the interpreter and
    the script unquoted, so a product folder with a space broke the line when
    it was copied. Run from a copy of the scripts under `my product/`, on a
    work dir under `my dumps/`: every path in the printed command is quoted."""
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        prod = Path(tmp).resolve() / "my product"
        shutil.copytree(SCRIPTS, prod / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        wd, pack = runnable_workdir(Path(tmp).resolve() / "my dumps", {})
        env = dict(os.environ)
        env[photo_profile.ENV_VAR] = str(pack / "photo-profile.json")
        r = subprocess.run(
            [sys.executable, str(prod / "scripts" / "photo_plan.py"), str(wd),
             "--plan", "1"], capture_output=True, text=True, env=env)
        text = r.stdout + r.stderr
        see = [ln.strip() for ln in text.splitlines() if "photo_see.py" in ln]
        want = f'"{prod / "scripts" / "photo_see.py"}" "{wd}" --batch <N>'
        return (r.returncode != 0 and len(see) == 1
                and see[0].startswith('"') and see[0].endswith(want)), \
            f"rc={r.returncode} see={see!r}"


@case
def planning_a_seen_batch_still_renders():
    """The guard on the other side: the gate must not block the ordinary path.
    A CSV that now carries the WHO/WHAT columns is the whole point of R1."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = runnable_workdir(
            tmp, {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        r = plan_run(wd, pack)
        csv_path = wd / "plan" / "plan_P1-files.csv"
        header = csv_path.read_text().splitlines()[0] if csv_path.exists() else ""
        return r.returncode == 0 and "who" in header, \
            f"rc={r.returncode} header={header!r} err={r.stderr[:300]!r}"


@case
def no_vision_plans_anyway():
    """The escape hatch is deliberate and must keep working -- a metadata-only
    dump (screenshots, no-date files, no subjects) has nothing to see."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = runnable_workdir(tmp, {})
        r = plan_run(wd, pack, "--no-vision")
        return (r.returncode == 0
                and (wd / "plan" / "plan_P1-files.csv").exists()), \
            f"rc={r.returncode} err={r.stderr[:300]!r}"



# ---------------------------------------------------------------------------
# R4 — the wire between a confirmed subject and a folder name.
#
# ⭐ REPRODUCTION. `visual_columns()` read ONE `subject` object per label,
# because `best_animal_box()` returned one box per file. R3a made a frame
# yield one detection per animal, so a decision can now name two — and every
# one of those names arrived at a reader that could see only the first key of
# a dict it no longer had. The cell rendered EMPTY: not the class word, not a
# draft marker, nothing, because `entry.get("subject")` was None and both
# branches were skipped. A folder named from that CSV loses `[who]` entirely
# and looks, in the plan document, exactly like a photograph with no animal
# in it.


@case
def a_label_naming_its_subjects_as_a_list_still_resolves_a_name():
    """⭐ THE R4 REPRODUCTION. One subject, expressed the R4 way. Deliberately
    ONE and not two: the two-name rendering is R5's, and a case that needed
    both would pass or fail for two reasons at once."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {1: [label_r4("/raw/a.jpg", [{"subject_id": "subj-0001"}])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return (cell["who"] == "Lotus"
            and cell["who_provenance"] == photo_evidence.VIEWED), f"{cell}"


@case
def a_pre_r4_label_and_an_r4_label_render_the_same_cell():
    """The compatibility claim, stated as an equality rather than as two
    separate expectations — which is the only form that catches the two
    shapes drifting apart later. Both files describe the same photograph of
    the same animal, so anything but an identical cell is a defect."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {1: [label("/raw/old.jpg", {"subject_id": "subj-0001"}),
                              label_r4("/raw/new.jpg",
                                       [{"subject_id": "subj-0001"}])]})
        cells = render(wd, pack)
    return cells["/raw/old.jpg"] == cells["/raw/new.jpg"], f"{cells}"


@case
def an_empty_subject_list_is_a_photograph_with_no_animal_in_it():
    """`subjects: []` is a POSITIVE statement — the see stage looked and named
    nobody — and `subject: null` says the same thing in the old shape. Neither
    may invent a WHO, and neither may leave a bare `draft:` behind.

    ⛔ The boundary that matters is empty-versus-absent, and an empty list is
    falsy: a reader written as `entry.get("subjects") or entry.get("subject")`
    would fall through to the old key on exactly this input and answer from
    whichever one happened to be there."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {1: [label_r4("/raw/a.jpg", []),
                              label_r4("/raw/b.jpg", [],
                                       subject_provenance=None)]})
        cells = render(wd, pack)
    return (all(c.get("who", "") == "" for c in cells.values())
            and all(c["who_provenance"] == "" for c in cells.values())), f"{cells}"


@case
def an_unconfirmed_subject_anywhere_in_the_list_marks_the_whole_cell():
    """One `draft:` per CELL, not per name. The cell makes ONE provenance
    claim, so the weaker of the two names has to govern it — a cell reading
    `Lotus` at plain `viewed-image:` while half of it rests on unconfirmed
    memory is precisely the reassurance V2-5's column exists to withhold.

    R5 renders both names; what R4 fixes is the marker, and it is already
    wrong with one confirmed name beside one draft."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp,
                         [confirmed("subj-0001", "Lotus"), drafted("subj-0002")],
                         {1: [label_r4("/raw/a.jpg", [{"subject_id": "subj-0001"},
                                                      {"subject_id": "subj-0002"}])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return cell["who_provenance"] == photo_evidence.DRAFT + photo_evidence.VIEWED, \
        f"{cell}"


@case
def a_list_entry_naming_nothing_is_dropped_not_rendered():
    """A `{}` or a `null` inside the list is not a subject. It must vanish, as
    `subject: null` always has — an entry that reached `kind_word()` would
    print the unknown-class word and claim an animal nobody detected."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {1: [label_r4("/raw/a.jpg", [None, {},
                                                      {"subject_id": "subj-0001"}])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return cell["who"] == "Lotus", f"{cell}"



# ---------------------------------------------------------------------------
# R5 — `[who]` is a REPEATABLE slot.
#
# ⛔ It is NEVER capped at one (SPEC v0.7 as amended by the owner, 20260904:
# three names in one folder name is normal). R4 carried the second animal as
# far as the CSV; until R5 the cell held one string and it stopped there.
#
# The joiner is `+`, the same one multi-`[where]` uses, because the SPEC's
# reason for the cap is that it must be checkable by READING a name.


@case
def two_confirmed_subjects_render_two_names():
    """⭐ THE R5 REPRODUCTION. The whole point of the card, and the exit
    criterion the plan states: at least one folder carries TWO names."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus"),
                               confirmed("subj-0002", "Bao")],
                         {1: [label_r4("/raw/a.jpg", [{"subject_id": "subj-0001"},
                                                      {"subject_id": "subj-0002"}])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return cell["who"] == "Lotus+Bao", f"{cell}"


@case
def the_order_the_decision_gave_is_the_order_rendered():
    """Detection order is the caller's statement about the frame — the
    highest-scoring animal first — and it is the only ordering anything
    downstream has. Sorting the names would silently replace it with an
    alphabetical one that no longer describes the photograph."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Zephyr"),
                               confirmed("subj-0002", "Aster")],
                         {1: [label_r4("/raw/a.jpg", [{"subject_id": "subj-0001"},
                                                      {"subject_id": "subj-0002"}])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return cell["who"] == "Zephyr+Aster", f"{cell}"


@case
def three_names_is_the_shipped_cap_and_still_a_list():
    """The boundary value itself, in the fixture (not one either side of it).
    `{3}` is the cap, so three names must still RENDER as three names — an
    off-by-one here turns the ordinary household case into a collective."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed(f"subj-000{i}", n) for i, n in
                               enumerate(["Lotus", "Bao", "Pim"], start=1)],
                         {1: [label_r4("/raw/a.jpg",
                                       [{"subject_id": f"subj-000{i}"}
                                        for i in (1, 2, 3)])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return cell["who"] == "Lotus+Bao+Pim", f"{cell}"


@case
def past_the_cap_a_collective_noun_replaces_the_names():
    """N-9: beyond `{names_per_folder}`, a collective noun.

    ⛔ NOT a truncation to the first three. `Lotus+Bao+Pim` on a folder of
    four animals is a complete, well-formed, FALSE statement about what is in
    it, and nothing downstream could detect it. The collective is true and is
    visibly not a list of names."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed(f"subj-000{i}", n) for i, n in
                               enumerate(["Lotus", "Bao", "Pim", "Nori"], start=1)],
                         {1: [label_r4("/raw/a.jpg",
                                       [{"subject_id": f"subj-000{i}"}
                                        for i in (1, 2, 3, 4)])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    expected = RMSG["review_who_many"].format(kind=CLASSES["cat"])
    return cell["who"] == expected and "+" not in cell["who"], \
        f"{cell} (expected {expected!r})"


@case
def the_cap_is_a_pack_parameter_not_a_constant():
    """⛔ `{3}` is a `{n}`. A household with four animals raises it in the
    pack's `defaults` and nothing in the engine moves — same registry, same
    label file, same call, one number.

    Proved by rendering the SAME four subjects twice, so the only difference
    between the two answers is the parameter."""
    with tempfile.TemporaryDirectory() as tmp:
        subjects = [confirmed(f"subj-000{i}", n) for i, n in
                    enumerate(["Lotus", "Bao", "Pim", "Nori"], start=1)]
        labels = {1: [label_r4("/raw/a.jpg", [{"subject_id": f"subj-000{i}"}
                                              for i in (1, 2, 3, 4)])]}
        wd, pack = build(tmp, subjects, labels)
        shipped = render(wd, pack)["/raw/a.jpg"]["who"]
        write_registry(pack, subjects, {"names_per_folder": 4})
        raised = render(wd, pack)["/raw/a.jpg"]["who"]
    return (shipped == RMSG["review_who_many"].format(kind=CLASSES["cat"])
            and raised == "Lotus+Bao+Pim+Nori"), f"{shipped!r} then {raised!r}"


@case
def a_mixed_group_past_the_cap_names_no_species():
    """The collective has to be TRUE. Four cats are `cats`; three cats and a
    dog share no species, so the noun falls back to the unknown-kind word.
    ⛔ Taking the first subject's kind would print `cats` over a group that
    is not all cats — the same false-but-readable failure truncation makes,
    one field along."""
    with tempfile.TemporaryDirectory() as tmp:
        subjects = [confirmed("subj-0001", "Lotus"), confirmed("subj-0002", "Bao"),
                    confirmed("subj-0003", "Pim"),
                    confirmed("subj-0004", "Nori", kind="dog")]
        wd, pack = build(tmp, subjects,
                         {1: [label_r4("/raw/a.jpg",
                                       [{"subject_id": f"subj-000{i}"}
                                        for i in (1, 2, 3, 4)])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    expected = RMSG["review_who_many"].format(kind=RMSG["review_kind_unknown"])
    return cell["who"] == expected, f"{cell} (expected {expected!r})"


@case
def the_collective_reads_the_species_the_registry_holds_now():
    """The kind resolves through the REGISTRY, exactly as the name does. A
    see-label written before the owner corrected a subject's species still
    carries the old one, and the collective must say what the pack believes
    now — otherwise the same folder is `dogs` in the CSV and `cats` in the
    review table."""
    with tempfile.TemporaryDirectory() as tmp:
        subjects = [confirmed(f"subj-000{i}", n, kind="dog") for i, n in
                    enumerate(["Lotus", "Bao", "Pim", "Nori"], start=1)]
        wd, pack = build(tmp, subjects,
                         {1: [label_r4("/raw/a.jpg",
                                       [{"subject_id": f"subj-000{i}",
                                         "subject_kind": "cat"}
                                        for i in (1, 2, 3, 4)])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    expected = RMSG["review_who_many"].format(kind=CLASSES["dog"])
    return cell["who"] == expected, f"{cell} (expected {expected!r})"


@case
def one_name_still_renders_exactly_as_it_always_did():
    """⚠️ A GUARD, and the one that matters most: every folder an owner
    already has was named through the single-name path, and a joiner that
    leaked into it would rename all of them."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus")],
                         {1: [label("/raw/old.jpg", {"subject_id": "subj-0001"}),
                              label_r4("/raw/new.jpg",
                                       [{"subject_id": "subj-0001"}])]})
        cells = render(wd, pack)
    return (cells["/raw/old.jpg"]["who"] == "Lotus"
            and cells["/raw/new.jpg"]["who"] == "Lotus"), f"{cells}"


@case
def an_unconfirmed_subject_beside_a_confirmed_one_renders_both():
    """A draft prints its class word rather than its proposed name (V2-5),
    and it still occupies a slot — the frame held two animals and the cell
    has to say so. The `draft:` marker on the cell is what says one of the
    two rests on unconfirmed memory."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(tmp, [confirmed("subj-0001", "Lotus"),
                               drafted("subj-0002")],
                         {1: [label_r4("/raw/a.jpg", [{"subject_id": "subj-0001"},
                                                      {"subject_id": "subj-0002"}])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    return (cell["who"] == f"Lotus+{CLASSES['cat']}"
            and cell["who_provenance"] == photo_evidence.DRAFT + photo_evidence.VIEWED), \
        f"{cell}"



# ---------------------------------------------------------------------------
# R6 — `[what]` is keywords and short phrases, gated by N-4 and bounded by N-2.
#
# ⛔ NOT the 11-word `[type]` taxonomy. `photo_classify_set.py --type` carries
# no `choices=` because the two fields were never the same thing, and in
# UAT01 every label was a class word — so every folder said the species and
# nothing about the day.
#
# The gate does two jobs with one rule. A `clip-matched:` phrase is the
# zero-shot classifier's own output, drawn from the pack's class vocabulary,
# and so is a `clip-propagated:` label that inherited from an unviewed cluster
# medoid. Excluding both is what keeps `[what]` from collapsing back into the
# taxonomy it is not.
#
# ⚠️ AMENDED BY D-F10 — a `clip-propagated:` label that inherited a PHRASE
# from a file somebody opened now names a folder. See the D-F10 block further
# down; the cases here were written when the gate was `viewed-image:` alone
# and every one of them still holds, because none of their cells traces back
# to a look.


def what_cell(what, provenance=photo_evidence.VIEWED):
    """One `visual_columns()` output cell, which is what `name_phrase()`
    consumes. Built directly rather than rendered through the registry: this
    function's input is the CSV column, and a case that had to build a pack to
    reach it would be testing two things."""
    return {"what": what, "what_provenance": provenance,
            "who": "", "who_provenance": ""}


@case
def the_folders_what_is_not_the_commonest_label_in_it():
    """⭐ THE R6 BEHAVIOUR PROOF, and it is written this way on purpose.

    `name_phrase()` is a function that did not exist, so every case below
    fails on the unfixed engine with an AttributeError — which proves a symbol
    is new and NOTHING about what the stage does. This one computes the answer
    that WAS available before R6, in the case itself, and shows the two
    disagree.

    The batch is the ordinary one: a cluster of eleven photographs, one of
    which a model actually opened. Its label is a phrase; the other ten
    inherited a zero-shot class word from the pack's own scene vocabulary.

      before — the commonest `what` in the folder    -> the class word,
               taken from ten files nobody looked at, which is both an N-4
               violation and the taxonomy wearing the `[what]` slot's clothes
      after  — the only phrase N-4 permits            -> the phrase

    That is UAT01's naming failure in one assertion: the majority answer is
    always the propagated one, because propagation is what makes it a
    majority."""
    cells = {f"/raw/{i}.jpg": what_cell(CLASSES["cat"],
                                        photo_evidence.CLIP_PROPAGATED)
             for i in range(10)}
    cells["/raw/looked.jpg"] = what_cell("coffee time by the window")

    commonest = max({c["what"] for c in cells.values()},
                    key=lambda w: sum(1 for c in cells.values()
                                      if c["what"] == w))
    picked = photo_plan.name_phrase(cells)
    return (commonest == CLASSES["cat"]
            and picked["what"] == "coffee time by the window"
            and picked["provenance"] == photo_evidence.VIEWED), \
        f"before={commonest!r} after={picked['what']!r}"


@case
def a_viewed_phrase_names_the_folder():
    """⭐ THE R6 REPRODUCTION, and exit criterion 3: at least one folder
    carries a `[what]` phrase from a `viewed-image:` source."""
    picked = photo_plan.name_phrase({"/raw/a.jpg": what_cell("coffee time")})
    return (picked["what"] == "coffee time"
            and picked["why"] == photo_plan.WHAT_OK
            and picked["provenance"] == photo_evidence.VIEWED), f"{picked}"


@case
def a_propagated_phrase_with_nothing_behind_it_never_names_a_folder():
    """⛔ AMENDED BY D-F10 (signed 20260906) and still true — read the cells,
    not the title. Neither of these traces back to a look: the propagated one
    carries no `WHAT_VIEWED_SOURCE`, so it inherited a cluster medoid's
    zero-shot class rather than a phrase somebody returned, and the
    clip-matched one IS the zero-shot classifier's own output.

    ⛔ The case was named `a_propagated_phrase_never_names_a_folder` when the
    gate was the prefix alone. That sentence is no longer the rule — a
    propagated phrase that inherited from a viewed file DOES name a folder
    now — and a case whose name states a superseded rule is how the next
    reader learns the wrong one."""
    picked = photo_plan.name_phrase(
        {"/raw/a.jpg": what_cell("coffee time", photo_evidence.CLIP_PROPAGATED),
         "/raw/b.jpg": what_cell("coffee time", photo_evidence.CLIP_MATCHED)})
    return (picked["what"] is None
            and picked["why"] == photo_plan.WHAT_NOTHING_VIEWED), f"{picked}"


@case
def a_drafted_look_is_not_a_look():
    """`draft:viewed-image:` is a real look attributed to an unconfirmed
    subject. `is_view_confirmed()` refuses it for memorizing and must refuse
    it here for the same reason: the string is one `draft:` away from the one
    that means a bare look, and a `in` test would accept it."""
    picked = photo_plan.name_phrase({"/raw/a.jpg": what_cell(
        "coffee time", photo_evidence.DRAFT + photo_evidence.VIEWED)})
    return picked["why"] == photo_plan.WHAT_NOTHING_VIEWED, f"{picked}"


@case
def one_viewed_file_among_propagated_ones_still_names_it():
    """The ordinary shape of a batch: one look, a whole cluster labelled. The
    gate must not need a majority — one viewed source is what N-4 asks for,
    and the carve-out exists to guarantee exactly one."""
    picked = photo_plan.name_phrase({
        "/raw/a.jpg": what_cell("sunset", photo_evidence.CLIP_PROPAGATED),
        "/raw/b.jpg": what_cell("sunset", photo_evidence.CLIP_PROPAGATED),
        "/raw/c.jpg": what_cell("sunset")})
    return picked["what"] == "sunset" and picked["why"] == photo_plan.WHAT_OK, \
        f"{picked}"


@case
def the_best_supported_viewed_phrase_wins_and_ties_are_deterministic():
    """Ranked by how many files carry it, then by text. The tie-break is not
    cosmetic: without it the same batch names the same folder differently on
    two runs, and a re-run would look like a re-decision."""
    cells = {"/raw/a.jpg": what_cell("sunset"), "/raw/b.jpg": what_cell("sunset"),
             "/raw/c.jpg": what_cell("hiking")}
    winner = photo_plan.name_phrase(cells)["what"]
    tie = photo_plan.name_phrase({"/raw/a.jpg": what_cell("sunset"),
                                  "/raw/b.jpg": what_cell("hiking")})["what"]
    return winner == "sunset" and tie == "hiking", f"{winner!r} then {tie!r}"


@case
def a_viewed_file_with_no_phrase_is_not_a_phrase():
    """⛔ `nothing-viewed` and `no-phrase` are DIFFERENT answers and must never
    render the same. One says N-4 was not satisfied; the other says it was and
    the model returned nothing to say. They have different repairs — raise the
    see-rate, or ask a better question — and a single token would hide which."""
    picked = photo_plan.name_phrase({"/raw/a.jpg": what_cell(""),
                                     "/raw/b.jpg": what_cell(None)})
    return picked["why"] == photo_plan.WHAT_NO_PHRASE, f"{picked}"


@case
def no_files_at_all_is_nothing_viewed_not_a_crash():
    """A folder whose plan named no seen batch. It must answer, not raise."""
    picked = photo_plan.name_phrase({})
    return (picked["what"] is None
            and picked["why"] == photo_plan.WHAT_NOTHING_VIEWED), f"{picked}"


@case
def n2_counts_who_and_what_together_and_charges_no_separator():
    """N-2 bounds `[who]` + `[what]` as one budget. `[period]` and `[where]`
    are fixed cost and are never charged, and the `+` between two names is
    punctuation — so a folder naming two subjects is not billed for joining
    them."""
    picked = photo_plan.name_phrase({"/raw/a.jpg": what_cell("play in grass")},
                                    who="Lotus+Bao")
    return picked["units"] == 5, f"{picked}"


@case
def a_phrase_that_busts_the_hard_cap_gives_way_to_one_that_fits():
    """⛔ Walking on rather than refusing outright. A folder losing `[what]`
    entirely because its best-supported phrase ran a unit long — while a
    shorter phrase with almost as many files sat right behind it — is a worse
    answer than the shorter phrase, and N-2's hard cap is a refusal point for
    the NAME, not for the slot.

    The BOUNDARY is in the fixture, not either side of it: at hard=3 the
    four-word phrase is one over and the three-word one sits exactly ON the
    cap. So this proves `<=` and not `<` at the same time as it proves the
    walk — bracketing a threshold is not testing it."""
    cells = {"/raw/a.jpg": what_cell("play in the grass"),
             "/raw/b.jpg": what_cell("play in the grass"),
             "/raw/c.jpg": what_cell("play in grass")}
    picked = photo_plan.name_phrase(cells, hard=3, soft=2)
    return (picked["what"] == "play in grass" and picked["units"] == 3
            and picked["why"] == photo_plan.WHAT_OK), f"{picked}"


@case
def every_viewed_phrase_over_the_cap_is_a_refusal_that_says_so():
    """When nothing fits, the folder gets no `[what]` and the reason is a
    token the caller can render — never a silently empty slot, which reads
    exactly like a batch nobody looked at."""
    picked = photo_plan.name_phrase(
        {"/raw/a.jpg": what_cell("play in the long wet grass")}, hard=3, soft=2)
    return (picked["what"] is None
            and picked["why"] == photo_plan.WHAT_OVER_BUDGET
            and picked["candidates"][0]["units"] == 6), f"{picked}"


@case
def the_soft_target_warns_and_never_refuses():
    """⛔ Soft and hard are different verbs. A run that refused at the soft
    target would make `{12}` the real cap and `{20}` decoration — and the SPEC
    is explicit that the generator AIMS for the soft one."""
    picked = photo_plan.name_phrase(
        {"/raw/a.jpg": what_cell("play in the grass")}, hard=10, soft=2)
    return (picked["what"] == "play in the grass" and picked["over_soft"] is True
            and picked["why"] == photo_plan.WHAT_OK), f"{picked}"


@case
def the_budget_comes_from_the_pack_not_from_the_constant():
    """📐 `{20}`/`{12}` are `{n}` parameters. ⛔ Reading
    `photo_name.DEFAULT_NAME_BUDGET_*` from a caller is how a pack's value
    silently stops being consulted — D-07's exact shape, where one module held
    its own idea of an owner fact while another read the pack, and a whole
    dump lost its place names at exit 0."""
    import photo_name
    shipped = photo_profile.name_budget(EN)
    declared = photo_profile.name_budget(
        {**EN, "naming_spec": {"name_budget": {"hard": 9, "soft": 4}}})
    return (shipped == (photo_name.DEFAULT_NAME_BUDGET_HARD,
                        photo_name.DEFAULT_NAME_BUDGET_SOFT)
            and declared == (9, 4)), f"{shipped} then {declared}"


@case
def a_malformed_budget_falls_back_rather_than_stopping_the_run():
    """A budget that is not a positive integer is a broken pack, not a reason
    to stop naming folders — and the shipped numbers are the SPEC's own, so
    falling back lands on the right answer rather than on an arbitrary one.
    ⛔ Zero is in the fixture because it is falsy: a guard written as
    `value or fallback` would treat a deliberate 0 and a missing key alike,
    and 0 is the value that would refuse every name there is."""
    import photo_name
    shipped = (photo_name.DEFAULT_NAME_BUDGET_HARD,
               photo_name.DEFAULT_NAME_BUDGET_SOFT)
    bad = [{"hard": 0, "soft": 0}, {"hard": -3}, {"hard": "twenty"},
           {"hard": None}, {}]
    got = [photo_profile.name_budget({**EN, "naming_spec": {"name_budget": b}})
           for b in bad]
    return all(g == shipped for g in got), f"{got}"


# ---------------------------------------------------------------------------
# D-F10 — what `[what]` may rest on, signed by the owner 20260906.
#
#   | slot     | evidence                                                   |
#   |----------|------------------------------------------------------------|
#   | `[who]`  | `viewed-image:` ONLY — naming an INDIVIDUAL on a guess is   |
#   |          | how identities get corrupted                                |
#   | `[what]` | `viewed-image:` **or** a `clip-propagated:` phrase that     |
#   |          | inherited from a file somebody opened                      |
#
# Measured basis: on the 990-file dump the vision pass covered 980 files, but
# only 126 were genuinely VIEWED and 480 were `clip-propagated:`. Restricting
# `[what]` to viewed evidence leaves 87% of files contributing nothing, and
# `[what]` is near-constant inside a Where-About (batch-13: the same word on
# 181 of 206 files) — so a propagated phrase is still a claim about the same
# scene the model looked at. Who is IN the frame is not constant that way,
# which is why the two slots differ.
#
# ⛔ THE PREFIX IS NOT THE GATE, and this is the part a reader must not skip.
# `clip-propagated:` names TWO populations. One inherits a viewed PHRASE
# (`photo_see.apply_decisions()`); the other inherits a cluster medoid's
# zero-shot SCENE CLASS (`photo_see.provisional_labels()`) — a `[type]` word
# nobody looked at. Opening the slot on the prefix alone admits the second,
# and then `[what]` re-prints `[type]`, which is the defect R6 closed and
# D-F11 forbids. The gate reads the label's SOURCE.
# ---------------------------------------------------------------------------


def propagated_from(what, source, viewed_source=True):
    """A `clip-propagated:` cell, with or without the trace back to a look."""
    cell = what_cell(what, photo_evidence.CLIP_PROPAGATED)
    if viewed_source:
        cell[photo_plan.WHAT_VIEWED_SOURCE] = source
    return cell


@case
def a_propagated_phrase_that_inherited_a_look_names_the_folder():
    """⭐ THE D-F10 REPRODUCTION. The ordinary shape of a real batch: one file
    opened, its phrase propagated across the visual cluster — and then the
    plan is written for a set of files that does NOT include the one that was
    looked at, because plans and see-batches do not have to line up.

    Before D-F10 this folder got no `[what]` at all. Nothing was wrong with
    the evidence: a model opened `/raw/looked.jpg`, said `coffee time`, and
    every file here is in that file's own visual cluster. 480 of 990 files on
    the real dump are in exactly this position."""
    cells = {f"/raw/{i}.jpg": propagated_from("coffee time", "/raw/looked.jpg")
             for i in range(6)}
    picked = photo_plan.name_phrase(cells)
    return (picked["what"] == "coffee time"
            and picked["why"] == photo_plan.WHAT_OK
            and picked["provenance"] == photo_evidence.CLIP_PROPAGATED), \
        f"{picked}"


@case
def a_propagated_class_word_still_never_names_a_folder():
    """⛔ THE GUARD ON THE WRONG FIX, and the wrong fix is the small one: gate
    on the provenance string and be done.

    These ten files carry `clip-propagated:` too, and their label is a word
    out of the pack's own scene vocabulary — the zero-shot classifier's guess,
    propagated from a cluster medoid nobody opened. A prefix-only gate accepts
    them, and because propagation is what MAKES a label a majority, the class
    word then outranks the one phrase a model actually returned. `[what]`
    becomes `[type]` with extra steps.

    The fixture is built so the wrong fix loses LOUDLY rather than by one
    vote: ten class words against one viewed phrase."""
    cells = {f"/raw/{i}.jpg": propagated_from(CLASSES["cat"], "/raw/medoid.jpg",
                                              viewed_source=False)
             for i in range(10)}
    cells["/raw/looked.jpg"] = what_cell("coffee time by the window")
    picked = photo_plan.name_phrase(cells)
    return (picked["what"] == "coffee time by the window"
            and picked["provenance"] == photo_evidence.VIEWED), f"{picked}"


@case
def nothing_at_all_to_inherit_from_is_still_nothing_viewed():
    """The other half of the same rule, on its own: a batch whose only labels
    are propagated class words has no `[what]`, and the reason token still
    says `nothing-viewed` rather than `no-phrase`. The two have different
    repairs — raise the see rate, or ask a better question — so they must
    never render the same."""
    cells = {f"/raw/{i}.jpg": propagated_from("scenery", "/raw/medoid.jpg",
                                              viewed_source=False)
             for i in range(4)}
    cells["/raw/x.jpg"] = what_cell("scenery", photo_evidence.CLIP_MATCHED)
    picked = photo_plan.name_phrase(cells)
    return (picked["what"] is None
            and picked["why"] == photo_plan.WHAT_NOTHING_VIEWED), f"{picked}"


@case
def the_picked_provenance_never_claims_a_look_that_did_not_happen():
    """⛔ The answer says which evidence it actually rests on. Before D-F10
    the winner was always stamped `viewed-image:` because nothing else could
    win; keeping that constant would now put a look in the plan CSV that
    nobody performed — the same class of overstatement
    `photo_see.assert_no_fabrication()` exists to stop one stage upstream.

    Both phrases here are supported. `sunset` has more files and only
    propagated evidence; `hiking` has one file and a real look. The winner is
    `sunset` on count, and it must say `clip-propagated:`."""
    cells = {"/raw/a.jpg": propagated_from("sunset", "/raw/looked.jpg"),
             "/raw/b.jpg": propagated_from("sunset", "/raw/looked.jpg"),
             "/raw/c.jpg": what_cell("hiking")}
    picked = photo_plan.name_phrase(cells)
    stronger = photo_plan.name_phrase(
        {**cells, "/raw/d.jpg": what_cell("sunset")})
    return (picked["what"] == "sunset"
            and picked["provenance"] == photo_evidence.CLIP_PROPAGATED
            and stronger["provenance"] == photo_evidence.VIEWED), \
        f"{picked['provenance']} then {stronger['provenance']}"


@case
def visual_columns_traces_a_propagated_label_to_the_file_it_came_from():
    """⭐ The end-to-end half, read off a real `see-labels.json`, because the
    cells above are hand-built and a rule can be right in the picker while the
    field feeding it is never populated.

    Both propagated entries here carry a `from`. One names a file this labels
    file records as `viewed-image:`; the other names a medoid it records as
    `clip-matched:`. That difference is the ONLY thing distinguishing an
    inherited phrase from an inherited class word, and it is read off what the
    see stage actually wrote rather than guessed from the label's text."""
    with tempfile.TemporaryDirectory() as tmp:
        entries = [
            {"path": "/raw/looked.jpg", "label": "coffee time",
             "provenance": photo_evidence.VIEWED, "sample": "s1.jpg"},
            {"path": "/raw/inherits.jpg", "label": "coffee time",
             "provenance": photo_evidence.CLIP_PROPAGATED,
             "from": "/raw/looked.jpg"},
            {"path": "/raw/medoid.jpg", "label": CLASSES["cat"],
             "provenance": photo_evidence.CLIP_MATCHED},
            {"path": "/raw/guesses.jpg", "label": CLASSES["cat"],
             "provenance": photo_evidence.CLIP_PROPAGATED,
             "from": "/raw/medoid.jpg"},
        ]
        wd, pack = build(tmp, [], {1: entries})
        cells = render(wd, pack)
        traced = {path: cell.get(photo_plan.WHAT_VIEWED_SOURCE)
                  for path, cell in cells.items()}
        picked = photo_plan.name_phrase(cells)
        return (traced["/raw/inherits.jpg"] == "/raw/looked.jpg"
                and traced["/raw/guesses.jpg"] is None
                and traced["/raw/medoid.jpg"] is None
                and picked["what"] == "coffee time"), f"{traced} -> {picked}"


@case
def the_trace_is_not_a_csv_column_and_not_a_ninth_provenance_string():
    """⛔ The plan CSV keeps its four visual columns and its eight legal
    provenance strings. A ninth prefix meaning "propagated from a look" would
    be a second vocabulary for a fact the existing two already carry between
    them — and it would reach `photo_execute`, which reads the CSV by field
    name, and `photo_classify_validate`, which refuses anything outside
    `PLAN_PROVENANCE`."""
    with tempfile.TemporaryDirectory() as tmp:
        entries = [
            {"path": "/raw/looked.jpg", "label": "coffee time",
             "provenance": photo_evidence.VIEWED, "sample": "s1.jpg"},
            {"path": "/raw/inherits.jpg", "label": "coffee time",
             "provenance": photo_evidence.CLIP_PROPAGATED,
             "from": "/raw/looked.jpg"},
        ]
        wd, pack = build(tmp, [], {1: entries})
        cells = render(wd, pack)
        row = [cells["/raw/inherits.jpg"].get(k, "")
               for k in photo_plan.VISUAL_FIELDS]
        problems = []
        for path, cell in cells.items():
            problems += photo_evidence.plan_provenance_problems(
                cell.get("what_provenance"), f"{path} what")
        return (len(photo_plan.VISUAL_FIELDS) == 4
                and row == ["", "", "coffee time",
                            photo_evidence.CLIP_PROPAGATED]
                and photo_plan.WHAT_VIEWED_SOURCE not in photo_plan.VISUAL_FIELDS
                and not problems), f"{row} {problems}"


@case
def the_pack_what_list_never_reaches_the_picker():
    """⛔ D-F11 — the owner's list is a REFERENCE, never a BOUNDARY, so a
    phrase the owner has never written before must win exactly as easily as
    one they have. This is the picker-side half of
    `photo_name_cases::the_what_slot_is_never_checked_against_a_list`: that
    one guards the validator, this one guards the ranker.

    The pack below declares two phrases. The model returned a third, on more
    files. The third wins, and `name_phrase()` is handed no pack at all —
    which is the structural reason it cannot do otherwise."""
    with tempfile.TemporaryDirectory() as tmp:
        entries = [
            {"path": "/raw/a.jpg", "label": "an unrecorded phrase",
             "provenance": photo_evidence.VIEWED, "sample": "s1.jpg"},
            {"path": "/raw/b.jpg", "label": "an unrecorded phrase",
             "provenance": photo_evidence.VIEWED, "sample": "s2.jpg"},
            {"path": "/raw/c.jpg", "label": "coffee time",
             "provenance": photo_evidence.VIEWED, "sample": "s3.jpg"},
        ]
        wd, pack_dir = build(tmp, [], {1: entries})
        (pack_dir / "photo-entities.json").write_text(json.dumps(
            {"scenes": ["coffee time", "hiking"]}), encoding="utf-8")
        pack = photo_profile.resolve_pack(
            explicit=pack_dir / "photo-profile.json")
        declared = photo_profile.what_reference(pack)
        picked = photo_plan.name_phrase(render(wd, pack_dir))
        import inspect
        params = set(inspect.signature(photo_plan.name_phrase).parameters)
        return (declared == ["coffee time", "hiking"]
                and picked["what"] == "an unrecorded phrase"
                and not (params & {"pack", "profile", "vocabulary",
                                   "what_reference", "allowed"})), \
            f"pack says {declared}, the folder is named {picked['what']!r}"


# ---------------------------------------------------------------------------
# W2B-2 / F14 — the plan document shows what backs a name.
#
# ⭐ REPRODUCTION (UAT01-4, 20260910): the CSV carried `who` on 115 of 330
# files with correct provenance, and `plan_P12.md` held zero occurrences of
# `draft:`. The owner signs the document, not the CSV, so a name in the folder
# could not be checked against its evidence without opening the file list.


def evidence_workdir(root, subjects, labels, files, language=None):
    """A runnable work dir with one manifest row per name in `files`, all in
    batch 1 and all seen through `labels`. `language` rewrites the pack's."""
    wd, pack = build(root, subjects, {1: labels})
    if language is not None:
        path = pack / "photo-profile.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["language"] = language
        path.write_text(json.dumps(data), encoding="utf-8")
    (wd / "batches.json").write_text(json.dumps({
        "source": "/raw", "main_files": len(files), "no_exif_date": 0,
        "batches": [{"batch": 1, "from": "2026-01-01", "to": "2026-01-01",
                     "status": "classified", "label": "day out"}]}),
        encoding="utf-8")
    (wd / "plans.json").write_text(json.dumps({
        "dest_root": str(Path(root) / "sorted"),
        "plans": [{"plan": 1, "title": "B1", "batches": [1],
                   "dest": {"mode": "new",
                            "path": str(Path(root) / "sorted" / "20260101_x")}}]
    }), encoding="utf-8")
    lines = ["SourceFile,FileName,FileType,FileSize,DateTimeOriginal,"
             "CreateDate,GPSPosition,Make,Model,Software,ImageWidth,"
             "ImageHeight,Duration,UserComment"]
    for i, name in enumerate(files):
        lines.append(f"/raw/{name},{name},JPEG,100,2026:01:01 10:0{i}:00,-,-,"
                     "Apple,-,-,4032,3024,-,-")
    (wd / "manifest.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return wd, pack


def plan_md(wd):
    path = wd / "plan" / "plan_P1.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


EN_MSG = photo_profile.messages(EN)


def en(key, **kw):
    """The English line for `key`, or a marker no document can contain. On an
    engine without the key the case then fails on WHAT the document says, not
    on a KeyError, and a guard case still passes there as a guard should."""
    line = EN_MSG.get(key)
    return f"\x00missing:{key}" if line is None else line.format(**kw)


@case
def the_plan_document_shows_who_the_files_show():
    """⭐ THE F14 REPRODUCTION. A confirmed name, a draft and a file with no
    animal: all three must be readable in the document the owner approves,
    each with its count and provenance. Unfixed, the document says nothing
    about any of them."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = evidence_workdir(
            tmp, [confirmed("subj-0001", "Lotus"), drafted("subj-0002")],
            [label("/raw/a.jpg", {"subject_id": "subj-0001"}),
             label("/raw/b.jpg", {"subject_id": "subj-0002"}),
             label("/raw/c.jpg", None)],
            ["a.jpg", "b.jpg", "c.jpg"])
        r = plan_run(wd, pack)
        md = plan_md(wd)
        cat = photo_memory_kind_word("cat")
        want = [en("plan_h_who_evidence"),
                "| Lotus | `viewed-image:` | 1 |",
                f"| {cat} | `draft:viewed-image:` | 1 |",
                en("plan_who_evidence_none", n=1)]
        missing = [w for w in want if w not in md]
        return r.returncode == 0 and not missing, \
            f"rc={r.returncode} missing={missing} err={r.stderr[:200]!r}"


def photo_memory_kind_word(kind):
    import photo_memory
    return photo_memory.kind_word(kind, EN, RMSG)


@case
def a_confirmed_animal_beside_a_draft_is_still_shown_as_confirmed():
    """Two subjects in one frame are two names to log. The CSV cell carries
    ONE marker, the weaker, so it reads `draft:` for the pair — the document
    must not inherit that and hide the confirmed animal's own evidence."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = evidence_workdir(
            tmp, [confirmed("subj-0001", "Lotus"), drafted("subj-0002")],
            [label_r4("/raw/a.jpg", [{"subject_id": "subj-0001"},
                                     {"subject_id": "subj-0002"}])],
            ["a.jpg"])
        r = plan_run(wd, pack)
        md = plan_md(wd)
        ok = ("| Lotus | `viewed-image:` | 1 |" in md
              and "| Lotus | `draft:" not in md)
        return r.returncode == 0 and ok, \
            f"rc={r.returncode} md-tail={md[-600:]!r}"


@case
def a_file_the_see_stage_never_labelled_is_counted_apart():
    """A file with no label is not a file with no animal. Folding the two
    together would say "nothing here" about photographs nobody looked at."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = evidence_workdir(
            tmp, [confirmed("subj-0001", "Lotus")],
            [label("/raw/a.jpg", {"subject_id": "subj-0001"})],
            ["a.jpg", "b.jpg"])
        r = plan_run(wd, pack)
        md = plan_md(wd)
        ok = (en("plan_who_evidence_unseen", n=1) in md
              and en("plan_who_evidence_none", n=0) in md)
        return r.returncode == 0 and ok, f"rc={r.returncode} md={md[-500:]!r}"


@case
def the_evidence_section_is_written_in_the_owners_language():
    """Rule 8: the heading resolves through the owner's table, never a literal."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = evidence_workdir(
            tmp, [confirmed("subj-0001", "Lotus")],
            [label("/raw/a.jpg", {"subject_id": "subj-0001"})],
            ["a.jpg"], language="zh-TW")
        r = plan_run(wd, pack)
        md = plan_md(wd)
        zh = photo_profile.messages({"language": "zh-TW"})
        ok = (zh.get("plan_h_who_evidence", "\x00missing") in md
              and en("plan_h_who_evidence") not in md)
        return r.returncode == 0 and ok, f"rc={r.returncode}"


@case
def no_vision_writes_no_evidence_section():
    """Guard only. With nothing seen there is nothing to show, and a section
    of zeros would read as "we looked and found no animal"."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = runnable_workdir(tmp, {})
        r = plan_run(wd, pack, "--no-vision")
        md = plan_md(wd)
        return (r.returncode == 0 and md
                and en("plan_h_who_evidence") not in md), \
            f"rc={r.returncode}"


@case
def the_per_subject_evidence_is_not_a_csv_column():
    """Guard only: the plan CSV keeps exactly its four visual columns, so
    `photo_execute` and every golden baseline read the file they always did."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = evidence_workdir(
            tmp, [confirmed("subj-0001", "Lotus")],
            [label("/raw/a.jpg", {"subject_id": "subj-0001"})], ["a.jpg"])
        plan_run(wd, pack)
        header = (wd / "plan" / "plan_P1-files.csv").read_text().splitlines()[0]
        want = ",".join(["SourceFile", "FileName", "batch", "date", "action",
                         "destination", "note"] + photo_plan.VISUAL_FIELDS)
        return header == want, f"header={header!r}"


# ---------------------------------------------------------------------------
# W2B-1 / F12 — a subject's name must be backed by evidence before it
# reaches a folder.
#
# ⭐ REPRODUCTION (UAT01-4, 20260910): the tester typed
# `20241125_Wexmoor_Lotus+Birk_the old harbour` into plans.json for a batch
# whose cats had been REJECTED at the checkpoint. Its twelve files showed Cat
# at `draft:` and no animal at all; `photo_plan` answered
# `plan P12: 12 files = 12 copy`, exit 0.


def named_workdir(root, subjects, labels, files, folder, legs=None,
                  language=None):
    """`evidence_workdir()` with the destination folder named `folder`, and
    optionally legs as (name, day) pairs, one file per day in file order."""
    wd, pack = evidence_workdir(root, subjects, labels, files, language)
    days = [f"2026-01-0{i + 1}" for i in range(len(files))]
    lines = (wd / "manifest.csv").read_text().splitlines()
    lines = [lines[0]] + [
        line.replace("2026:01:01 10:0", f"2026:01:0{i + 1} 10:0", 1)
        for i, line in enumerate(lines[1:])]
    (wd / "manifest.csv").write_text("\n".join(lines) + "\n")
    batches = json.loads((wd / "batches.json").read_text())
    batches["batches"][0]["to"] = days[-1]
    (wd / "batches.json").write_text(json.dumps(batches))
    plans = json.loads((wd / "plans.json").read_text())
    dest = plans["plans"][0]["dest"]
    dest["path"] = str(Path(dest["path"]).parent / folder)
    if legs:
        plans["plans"][0]["legs"] = [{"from": day, "to": day, "name": name}
                                     for name, day in legs]
    (wd / "plans.json").write_text(json.dumps(plans))
    return wd, pack


PETS = [confirmed("subj-0001", "Lotus"), confirmed("subj-0002", "Birk")]


def refused(r, wd):
    """-> (refused cleanly, detail): non-zero, and nothing written or moved."""
    csv_written = (wd / "plan" / "plan_P1-files.csv").exists()
    md_written = (wd / "plan" / "plan_P1.md").exists()
    status = json.loads((wd / "batches.json").read_text())["batches"][0]["status"]
    ok = (r.returncode != 0 and not csv_written and not md_written
          and status == "classified")
    return ok, (f"rc={r.returncode} csv={csv_written} md={md_written} "
                f"status={status} err={r.stderr[-400:]!r}")


@case
def a_pet_name_no_file_backs_is_refused_and_nothing_is_written():
    """⭐ THE F12 REPRODUCTION, the tester's own shape. The refusal names the
    folder, both names and what the files actually hold."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, PETS + [drafted("subj-0003", name=None)],
            [label("/raw/a.jpg", {"subject_id": "subj-0003"}),
             label("/raw/b.jpg", {"subject_id": "subj-0003"},
                   subject_provenance=photo_evidence.CLIP_PROPAGATED),
             label("/raw/c.jpg", None)],
            ["a.jpg", "b.jpg", "c.jpg"],
            "20260101-0103_Wexmoor_Lotus+Birk_the old harbour")
        r = plan_run(wd, pack)
        ok, detail = refused(r, wd)
        said = all(w in r.stderr for w in (
            "20260101-0103_Wexmoor_Lotus+Birk_the old harbour", "Lotus, Birk",
            "draft:viewed-image:", en("plan_unbacked_no_animal", n=1)))
        return ok and said, detail


@case
def one_viewed_file_of_a_confirmed_pet_backs_its_name():
    """Guard: UAT01-4's four real pet folders each rested on ONE such file."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, PETS,
            [label("/raw/a.jpg", {"subject_id": "subj-0001"}),
             label("/raw/b.jpg", None)],
            ["a.jpg", "b.jpg"], "20260101-0102_Home_Lotus_at home")
        r = plan_run(wd, pack)
        return r.returncode == 0, f"rc={r.returncode} err={r.stderr[-300:]!r}"


@case
def two_animals_in_one_frame_back_two_names():
    """Guard: one frame, two confirmed animals, two names — never refused."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, PETS,
            [label_r4("/raw/a.jpg", [{"subject_id": "subj-0001"},
                                     {"subject_id": "subj-0002"}])],
            ["a.jpg"], "20260101_Home_Lotus+Birk")
        r = plan_run(wd, pack)
        return r.returncode == 0, f"rc={r.returncode} err={r.stderr[-300:]!r}"


@case
def a_name_only_clip_ever_saw_is_not_backed():
    """A confirmed pet recognised by propagation, never looked at: SKILL's
    rule is `viewed-image:` only."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, PETS,
            [label("/raw/a.jpg", {"subject_id": "subj-0001"},
                   subject_provenance=photo_evidence.CLIP_PROPAGATED)],
            ["a.jpg"], "20260101_Home_Lotus")
        return refused(plan_run(wd, pack), wd)


@case
def a_drafts_proposed_name_is_not_backed():
    """A draft may carry a proposed name; the folder may not, until the owner
    confirms it — a real look at an unconfirmed animal is still a guess."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, [drafted("subj-0001", name="Whiskers")],
            [label("/raw/a.jpg", {"subject_id": "subj-0001"})],
            ["a.jpg"], "20260101_Home_Whiskers")
        return refused(plan_run(wd, pack), wd)


@case
def the_evidence_must_be_inside_the_folder_that_carries_the_name():
    """A leg is its own folder. Lotus seen on day 1 does not back a leg that
    holds only day 2, even though the plan as a whole holds Lotus."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, PETS,
            [label("/raw/a.jpg", {"subject_id": "subj-0001"}),
             label("/raw/b.jpg", None)],
            ["a.jpg", "b.jpg"], "20260101-0102_Trip",
            legs=[("0101_Harbour", "2026-01-01"),
                  ("0102_Hill_Lotus", "2026-01-02")])
        ok, detail = refused(plan_run(wd, pack), wd)
        return ok and "0102_Hill_Lotus" in detail, detail


@case
def a_trip_parent_is_backed_by_its_legs_files():
    """Guard: every file of a trip with legs lands in a leg, so the parent
    must count what is under it or no parent could ever carry a name."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, PETS,
            [label("/raw/a.jpg", {"subject_id": "subj-0001"}),
             label("/raw/b.jpg", None)],
            ["a.jpg", "b.jpg"], "20260101-0102_Trip_Lotus",
            legs=[("0101_Harbour", "2026-01-01"), ("0102_Hill", "2026-01-02")])
        r = plan_run(wd, pack)
        return r.returncode == 0, f"rc={r.returncode} err={r.stderr[-300:]!r}"


@case
def a_name_written_in_another_case_is_still_the_name():
    """`lotus` is Lotus. A lowercase spelling slipping past is the hole; a
    false match here would be a loud refusal, never a silent pass."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, PETS, [label("/raw/a.jpg", None)], ["a.jpg"],
            "20260101_Home_lotus")
        return refused(plan_run(wd, pack), wd)


@case
def no_vision_cannot_back_a_name():
    """With the see stage skipped nothing can back a name, so a name is
    refused rather than waved through on no evidence at all."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(tmp, PETS, [], ["a.jpg"], "20260101_Home_Lotus")
        r = plan_run(wd, pack, "--no-vision")
        ok, detail = refused(r, wd)
        return ok and "--no-vision" in r.stderr, detail


@case
def a_word_the_registry_does_not_hold_is_never_checked():
    """Guard: the pack's records are the only authority on what a name is.
    A word that is no subject's name — here in `[what]` — is free text, and
    a pet's name inside a longer phrase is not a whole `[who]` piece."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, PETS, [label("/raw/a.jpg", None)], ["a.jpg"],
            "20260101_Home_walk up birk hill+Tama")
        r = plan_run(wd, pack)
        return r.returncode == 0, f"rc={r.returncode} err={r.stderr[-300:]!r}"


@case
def a_folder_that_receives_no_file_is_not_judged():
    """⭐ REPRODUCTION (found in review, not in the round). An override that
    takes every day leaves the parent folder empty, and `photo_execute`
    creates only folders a copy lands in, so the parent's name reaches no
    tree. Refusing it refused the whole plan, the correctly backed override
    folder included."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, PETS, [label("/raw/a.jpg", {"subject_id": "subj-0001"})],
            ["a.jpg"], "20260101_Home_Birk")
        plans = json.loads((wd / "plans.json").read_text())
        target = str(Path(tmp) / "sorted" / "20260101_Park_Lotus")
        plans["plans"][0]["overrides"] = [
            {"dates": ["2026-01-01"], "dest": target, "reason": "moved"}]
        (wd / "plans.json").write_text(json.dumps(plans))
        r = plan_run(wd, pack)
        return r.returncode == 0, f"rc={r.returncode} err={r.stderr[-300:]!r}"


@case
def the_refusal_is_in_the_owners_language():
    """Rule 8, one source (LL-PHO-188): the refusal reads the owner's table."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = named_workdir(
            tmp, PETS, [label("/raw/a.jpg", None)], ["a.jpg"],
            "20260101_Home_Lotus", language="zh-TW")
        r = plan_run(wd, pack)
        zh = photo_profile.messages({"language": "zh-TW"})
        line = zh.get("plan_refused_unbacked", "\x00missing").format(plan=1)
        return r.returncode != 0 and line in r.stderr, \
            f"rc={r.returncode} err={r.stderr[-300:]!r}"


# ---------------------------------------------------------------------------
# W2C / ADR 0005 — financial or official paperwork is kept out of the folders.
#
# ⭐ REPRODUCTION: before W2C a photographed receipt (measured on a real dump,
# a camera still) was routed into the trip folder like any holiday photo. The
# scores are written by hand here — photo_embed's own cases hold the CLIP
# half — and no real document or image is used anywhere.

PAPER_SCORES = "paperwork-scores.json"
PAPER_IDENTITY = {"model_id": "ViT-B-32", "pretrained_tag": "test-tag",
                  "preprocess_fingerprint": "sha256:test"}
TBC = photo_profile.buckets(EN)["to_be_checked"]
SHOTS = photo_profile.buckets(EN)["screenshots"]


def paper_workdir(root, files, scores=None, identity=None, overrides=None,
                  language=None):
    """`files` is [(name, FileType, Make)], all on 2026-01-01 in batch 1 and
    all seen. `scores` maps a name to its paperwork score; None writes no
    score file at all. `identity` overrides the score file's model fields."""
    names = [n for n, _t, _m in files]
    wd, pack = evidence_workdir(root, [], [label(f"/raw/{n}", None) for n in names],
                                names, language)
    lines = ["SourceFile,FileName,FileType,FileSize,DateTimeOriginal,"
             "CreateDate,GPSPosition,Make,Model,Software,ImageWidth,"
             "ImageHeight,Duration,UserComment"]
    for i, (name, ftype, make) in enumerate(files):
        model = "-" if make == "-" else "iPhone 15"
        lines.append(f"/raw/{name},{name},{ftype},100,2026:01:01 10:0{i}:00,"
                     f"-,-,{make},{model},-,4032,3024,-,-")
    (wd / "manifest.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if overrides:
        plans = json.loads((wd / "plans.json").read_text())
        plans["plans"][0]["overrides"] = overrides
        (wd / "plans.json").write_text(json.dumps(plans))
    if scores is not None:
        embed = wd / "embed"
        embed.mkdir()
        (embed / "embeddings-meta.json").write_text(json.dumps(PAPER_IDENTITY))
        (embed / PAPER_SCORES).write_text(json.dumps({
            **PAPER_IDENTITY, **(identity or {}),
            "scores": {f"/raw/{n}": v for n, v in scores.items()}}))
    return wd, pack


def routed(wd):
    path = wd / "plan" / "plan_P1-files.csv"
    if not path.exists():
        return {}
    return {r["FileName"]: r for r in csv.DictReader(open(path, newline=""))}


def lands_in(row, bucket):
    return row.get("destination", "").endswith(f"00_{bucket}")


@case
def a_photo_of_a_bill_goes_to_the_to_be_checked_bucket():
    """⭐ THE W2C REPRODUCTION: a camera still scoring above the cut. It lands
    in the review inbox, with its note, and the document names it."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = paper_workdir(tmp, [("bill.jpg", "JPEG", "Apple"),
                                       ("view.jpg", "JPEG", "Apple")],
                                 scores={"bill.jpg": 0.09, "view.jpg": -0.2})
        r = plan_run(wd, pack)
        rows, md = routed(wd), plan_md(wd)
        ok = (r.returncode == 0 and lands_in(rows.get("bill.jpg", {}), TBC)
              and rows["bill.jpg"]["note"] == en("note_paperwork")
              and not lands_in(rows.get("view.jpg", {}), TBC)
              and en("plan_h_paperwork") in md and "`bill.jpg`" in md
              and en("plan_paperwork_intro", n=1, bucket=TBC) in r.stderr)
        return ok, f"rc={r.returncode} rows={ {k: v['destination'][-30:] for k, v in rows.items()} }"


@case
def a_paperwork_screenshot_goes_to_the_inbox_not_to_screenshots():
    """Lead ruling 20260911 (a): a Screenshots bucket is sorted output, not a
    review inbox — the one real tax notice measured was a screenshot."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = paper_workdir(
            tmp, [("Screenshot_20260101_100000_Word.jpg", "JPEG", "-")],
            scores={"Screenshot_20260101_100000_Word.jpg": 0.09})
        r = plan_run(wd, pack)
        row = routed(wd).get("Screenshot_20260101_100000_Word.jpg", {})
        return r.returncode == 0 and lands_in(row, TBC), \
            f"rc={r.returncode} dest={row.get('destination')!r}"


@case
def an_override_date_does_not_bypass_the_paperwork_check():
    """⛔ The A5 lesson: an override names a DAY, and a day cannot answer a
    question about a file."""
    with tempfile.TemporaryDirectory() as tmp:
        target = str(Path(tmp) / "sorted" / "20260101_Elsewhere")
        wd, pack = paper_workdir(
            tmp, [("bill.jpg", "JPEG", "Apple")], scores={"bill.jpg": 0.09},
            overrides=[{"dates": ["2026-01-01"], "dest": target, "reason": "r"}])
        r = plan_run(wd, pack)
        row = routed(wd).get("bill.jpg", {})
        return r.returncode == 0 and lands_in(row, TBC), \
            f"rc={r.returncode} dest={row.get('destination')!r}"


@case
def a_video_is_never_moved_by_a_score():
    """⛔ Stills only (Lead ruling): a video scoring far above the cut stays
    in the folder, and a video is never counted as unchecked either."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = paper_workdir(tmp, [("clip.mp4", "MP4", "Apple")],
                                 scores={"clip.mp4": 0.5})
        r = plan_run(wd, pack)
        row = routed(wd).get("clip.mp4", {})
        moved_ok = r.returncode == 0 and not lands_in(row, TBC)
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = paper_workdir(tmp, [("clip.mp4", "MP4", "Apple")])
        r = plan_run(wd, pack)
        silent = (r.returncode == 0 and bool(plan_md(wd))
                  and en("plan_paperwork_reason_missing") not in plan_md(wd))
    return moved_ok and silent, f"dest={row.get('destination')!r} silent={silent}"


@case
def a_score_at_or_below_the_cut_stays_in_the_folder():
    """Guard: the cut is exceeded, not met."""
    cut = getattr(photo_profile, "PAPERWORK_MARGIN_DEFAULT", 0.03)
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = paper_workdir(tmp, [("a.jpg", "JPEG", "Apple"),
                                       ("b.jpg", "JPEG", "Apple")],
                                 scores={"a.jpg": cut, "b.jpg": cut - 0.001})
        r = plan_run(wd, pack)
        rows = routed(wd)
        return (r.returncode == 0 and rows
                and not any(lands_in(v, TBC) for v in rows.values())), \
            f"rc={r.returncode}"


@case
def the_cut_is_read_off_the_pack():
    """📐 A pack's `routing.paperwork_margin` beats the default."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = paper_workdir(tmp, [("bill.jpg", "JPEG", "Apple")],
                                 scores={"bill.jpg": 0.09})
        path = pack / "photo-profile.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["routing"] = {"paperwork_margin": 0.1}
        path.write_text(json.dumps(data), encoding="utf-8")
        r = plan_run(wd, pack)
        row = routed(wd).get("bill.jpg", {})
        return r.returncode == 0 and row and not lands_in(row, TBC), \
            f"rc={r.returncode} dest={row.get('destination')!r}"


@case
def paperwork_margin_is_one_fact():
    """The away_km lesson: the template must resolve to the one default in
    code, and a malformed value falls back to it."""
    reader = getattr(photo_profile, "paperwork_margin", None)
    if reader is None:
        return False, "photo_profile has no paperwork_margin()"
    d = photo_profile.PAPERWORK_MARGIN_DEFAULT
    shipped = json.loads((TEMPLATE / "photo-profile.json").read_text(
        encoding="utf-8").replace("{{SLUG}}", "x").replace("{{DISPLAY}}", "x"))
    ok = (reader(shipped) == d and reader({}) == d
          and reader({"routing": {"paperwork_margin": "x"}}) == d
          and reader({"routing": {"paperwork_margin": 0.05}}) == 0.05)
    return ok, f"default={d} template={reader(shipped)}"


@case
def with_no_scores_every_file_routes_as_today_and_the_plan_says_so():
    """⭐ REPRODUCTION for the disclosure: routing cannot fail closed, so it
    routes as it always did — and it SAYS the check did not run, how many
    stills and why, in the document and on stderr."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = paper_workdir(tmp, [("a.jpg", "JPEG", "Apple"),
                                       ("b.jpg", "JPEG", "Apple")])
        r = plan_run(wd, pack)
        line = en("plan_paperwork_not_run", n=2,
                  reason=en("plan_paperwork_reason_missing"))
        rows = routed(wd)
        ok = (r.returncode == 0 and rows
              and not any(lands_in(v, TBC) for v in rows.values())
              and line in plan_md(wd) and line in r.stderr)
        return ok, f"rc={r.returncode} err={r.stderr[-300:]!r}"


@case
def scores_from_another_model_are_not_used():
    """A number is only comparable to the cut it was measured against."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = paper_workdir(tmp, [("bill.jpg", "JPEG", "Apple")],
                                 scores={"bill.jpg": 0.09},
                                 identity={"model_id": "another-model"})
        r = plan_run(wd, pack)
        row = routed(wd).get("bill.jpg", {})
        line = en("plan_paperwork_not_run", n=1,
                  reason=en("plan_paperwork_reason_model"))
        return (r.returncode == 0 and row and not lands_in(row, TBC)
                and line in plan_md(wd)), f"rc={r.returncode}"


@case
def the_paperwork_disclosure_is_in_the_owners_language():
    """Rule 8, one source (LL-PHO-188)."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = paper_workdir(tmp, [("bill.jpg", "JPEG", "Apple")],
                                 scores={"bill.jpg": 0.09}, language="zh-TW")
        r = plan_run(wd, pack)
        zh = photo_profile.messages({"language": "zh-TW"})
        row = routed(wd).get("bill.jpg", {})
        return (r.returncode == 0
                and row.get("note") == zh.get("note_paperwork", "\x00")
                and zh.get("plan_h_paperwork", "\x00") in plan_md(wd)), \
            f"rc={r.returncode} note={row.get('note')!r}"


@case
def finish_says_how_many_went_to_the_inbox_across_every_plan():
    """The banner sums the per-plan counts, in the owner's language."""
    import contextlib
    import io
    import photo_run
    printer = getattr(photo_run, "print_paperwork_checkpoint", None)
    if printer is None:
        return False, "photo_run has no paperwork checkpoint"
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = paper_workdir(tmp, [("bill.jpg", "JPEG", "Apple")])
        (wd / "plan").mkdir(exist_ok=True)
        (wd / "plan" / "paperwork-moved.json").write_text(
            json.dumps({"1": 2, "2": 1, "3": 0}))
        env_before = os.environ.get(photo_profile.ENV_VAR)
        os.environ[photo_profile.ENV_VAR] = str(pack / "photo-profile.json")
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                printer(wd)
        finally:
            if env_before is None:
                os.environ.pop(photo_profile.ENV_VAR, None)
            else:
                os.environ[photo_profile.ENV_VAR] = env_before
        want = en("run_paperwork_banner", n=3, bucket=TBC)
        return want in out.getvalue(), f"out={out.getvalue()!r}"


# ---------------------------------------------------------------------------
# Wave 3 G3 — the per-subject entries carry kind + id; settle_rows()
# ---------------------------------------------------------------------------

@case
def who_subjects_carry_each_subjects_kind_and_resolved_id():
    """REPRODUCTION. ⛔ FAILS on e56226c: an entry held only name, confirmed
    and provenance, so a FOLDER gathering subjects from several files could
    not pick `render_who()`'s collective noun, and the index had no id to
    store. A folded loser's id resolves to the winner, as its name does."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = build(
            tmp, [confirmed("subj-0001", "Lotus", kind="cat"),
                  tombstone("subj-0003", "subj-0001"),
                  drafted("subj-0002", kind="dog")],
            {1: [label_r4("/raw/a.jpg", [{"subject_id": "subj-0003"},
                                         {"subject_id": "subj-0002"}])]})
        cell = render(wd, pack)["/raw/a.jpg"]
    got = [(s["name"], s.get("kind"), s.get("subject_id"))
           for s in cell[photo_plan.WHO_SUBJECTS]]
    return got[0] == ("Lotus", "cat", "subj-0001") and got[1][1:] == (
        "dog", "subj-0002"), f"got={got}"

def tree_state(root):
    """-> {relative path: bytes} for every file under `root`."""
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


def settle(wd, pack):
    loaded = photo_profile.resolve_pack(explicit=pack / "photo-profile.json")
    config = json.loads((wd / "plans.json").read_text())
    plan = config["plans"][0]
    batches = json.loads((wd / "batches.json").read_text())["batches"]
    return photo_plan.settle_rows(
        wd, plan, batches, config["dest_root"], loaded.profile,
        photo_profile.messages(loaded.profile))


@case
def settle_rows_writes_nothing_and_moves_no_status():
    """REPRODUCTION. ⛔ FAILS on e56226c: the routes existed only inside
    `main()`, which writes the plan documents and advances batches.json, so
    nothing could ask where a file lands without doing both."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = runnable_workdir(
            tmp, {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        before = tree_state(tmp)
        rows, _cand, _paper, _why = settle(wd, pack)
        after = tree_state(tmp)
    got = [(r["FileName"], r["_action"], Path(r["_dest"]).name) for r in rows]
    return (before == after and got == [("a.jpg", "copy", "20260101_x")]), \
        f"changed={sorted(set(after) ^ set(before))} got={got}"


@case
def settle_rows_is_what_main_writes():
    """GUARD. `main()` now calls `settle_rows()`; every CSV row it writes is
    the row settled here — action, destination and file name."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = runnable_workdir(
            tmp, {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        rows, _cand, _paper, _why = settle(wd, pack)
        r = plan_run(wd, pack)
        written = [(x["SourceFile"], x["FileName"], x["action"], x["destination"])
                   for x in csv.DictReader(open(wd / "plan" / "plan_P1-files.csv"))]
    settled = [(x["SourceFile"], x["_name"], x["_action"], x["_dest"]) for x in rows]
    return r.returncode == 0 and written == settled, f"{written} != {settled}"


@case
def settle_no_date_rows_writes_nothing_and_matches_the_no_date_plan():
    """REPRODUCTION. ⛔ FAILS on d6c4105: the no-date routes existed only
    inside `write_no_date_plan()`, which writes the plan documents. Settled
    here with no write, they are exactly the rows the no-date CSV carries."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = runnable_workdir(
            tmp, {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        (wd / "no-date-files.csv").write_text(
            "SourceFile,FileName,FileType,FileSize,Make,Model\n"
            "/raw/n.jpg,n.jpg,JPEG,10,-,-\n/raw/n2.png,n.jpg,JPEG,10,-,-\n",
            encoding="utf-8")
        loaded = photo_profile.resolve_pack(explicit=pack / "photo-profile.json")
        before = tree_state(tmp)
        rows, _counts, _root = photo_plan.settle_no_date_rows(
            wd, "/sorted", loaded.profile,
            photo_profile.messages(loaded.profile))
        after = tree_state(tmp)
        r = plan_run(wd, pack, "--no-date")
        path = wd / "plan" / "plan_no-date-files.csv"
        written = [(x["SourceFile"], x["FileName"], Path(x["destination"]).name)
                   for x in csv.DictReader(open(path))] if path.exists() else []
    settled = [(x["SourceFile"], x["_name"], Path(x["_dest"]).name) for x in rows]
    return (before == after and r.returncode == 0 and written == settled
            and settled[1][1] != settled[0][1]), f"{written} != {settled}"


@case
def a_manifest_with_no_file_date_keeps_todays_no_date_bucket():
    """GUARD — and stated as one on purpose: M14's per-file year is NOT BUILT
    when this case is written, so there is no fixed code for it to fail
    against yet. It pins the CONTRACT that code must keep.

    ⛔ The contract. Every golden manifest predates any filesystem-date column
    (measured: all 7 are 14 columns, none carries `FileModifyDate`). A
    per-file year cannot be computed from a manifest that has no per-file
    date, so the ONLY thing M14 may do there is what the engine does today:
    ONE no-date bucket per dump, named from the dump. That is what keeps all
    seven goldens byte-identical without a waiver.

    What would break it is the tempting shortcut — reading
    `row.get("FileModifyDate")`, getting nothing, and falling to a year of
    zero, or to the machine's clock, or to the dump's month per ROW. Any of
    those splits one bucket into several or renames it, and this fails.
    """
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = runnable_workdir(
            tmp, {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        # exactly the golden shape: no FileModifyDate / FileCreateDate column
        (wd / "no-date-files.csv").write_text(
            "SourceFile,FileName,FileType,FileSize,Make,Model\n"
            "/raw/s1.jpg,s1.jpg,JPEG,10,-,-\n"
            "/raw/v1.mp4,v1.mp4,MP4,10,-,-\n"
            "/raw/s2.png,s2.png,PNG,10,-,-\n",
            encoding="utf-8")
        loaded = photo_profile.resolve_pack(explicit=pack / "photo-profile.json")
        rows, _counts, root = photo_plan.settle_no_date_rows(
            wd, "/sorted", loaded.profile,
            photo_profile.messages(loaded.profile))
        today = f"/sorted/{photo_plan.dump_yyyymm(wd)}"
        today = today + "00" if photo_plan.dump_yyyymm(wd).isdigit() else today
    buckets = {Path(r["_dest"]).name for r in rows}
    return (root == today and len(buckets) == 1
            and all(r["_dest"].startswith(today + "_") for r in rows)), \
        f"root={root!r} want={today!r} buckets={sorted(buckets)}"


# ---------------------------------------------------------------------------
# M14 (owner rulings Q8/Q9/Q10, 20260922) — where a no-date file lands.
#
#   EXIF date                 -> unchanged, never reaches this path
#   no-EXIF VIDEO (real type) -> YYYY00_<bucket>, the year from FileModifyDate
#   no-EXIF STILL             -> _<bucket>/<import>/  — ONE top bucket, NO year
#   FileCreateDate            -> never read for a year
#
# ⛔ "No folder may claim a year it cannot support." Measured: FileModifyDate
# is right ~96-100% for no-EXIF video and 0 of 75 for no-EXIF stills.

M14_HEADER = ("SourceFile,FileName,FileType,FileSize,Make,Model,"
              "FileModifyDate,FileCreateDate\n")


def m14_settle(tmp, body):
    """-> (rows by FileName, the work dir, the resolved bucket words)."""
    wd, pack = runnable_workdir(
        tmp, {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
    (wd / "no-date-files.csv").write_text(M14_HEADER + body, encoding="utf-8")
    loaded = photo_profile.resolve_pack(explicit=pack / "photo-profile.json")
    rows, _counts, _root = photo_plan.settle_no_date_rows(
        wd, "/sorted", loaded.profile, photo_profile.messages(loaded.profile))
    return ({r["FileName"]: r for r in rows}, wd,
            photo_profile.buckets(loaded.profile))


@case
def m14_a_no_exif_video_goes_to_its_modify_year():
    """REPRODUCTION. Today every no-date file lands in ONE bucket named from
    the DUMP, so a video from 2009 is filed under the month it was imported."""
    with tempfile.TemporaryDirectory() as tmp:
        rows, _wd, names = m14_settle(tmp,
            "/raw/v.mp4,v.mp4,MP4,10,-,-,2009:04:05 10:00:00+08:00,"
            "2025:09:04 12:00:00+08:00\n")
    want = f"/sorted/200900_{names['to_be_checked']}"
    return rows["v.mp4"]["_dest"] == want, rows["v.mp4"]["_dest"]


@case
def m14_a_no_exif_still_claims_no_year_and_lands_under_its_import():
    """REPRODUCTION. A no-EXIF still's timestamp is when it reached the disk
    (0 of 75 right), so it gets ONE undated top bucket with a subfolder per
    import beneath it — named after the import, NEVER a date derived from it."""
    with tempfile.TemporaryDirectory() as tmp:
        rows, wd, names = m14_settle(tmp,
            "/raw/s.jpg,s.jpg,JPEG,10,-,-,2023:01:01 10:00:00+08:00,-\n")
    want = f"/sorted/_{names['to_be_checked']}/{wd.name}"
    dest = rows["s.jpg"]["_dest"]
    # ⛔ and no year anywhere in it — the modify year was 2023
    return dest == want and "2023" not in dest, dest


@case
def m14_3gp_is_a_video():
    """REPRODUCTION. `photo_sample.VIDEO_TYPES` was {MOV, MP4}; 3GP — named
    in the ruling, measured 8/8 — was treated as a still and lost its year."""
    with tempfile.TemporaryDirectory() as tmp:
        rows, _wd, names = m14_settle(tmp,
            "/raw/c.3gp,c.3gp,3GP,10,-,-,2011:06:01 09:00:00+08:00,-\n")
    want = f"/sorted/201100_{names['to_be_checked']}"
    return rows["c.3gp"]["_dest"] == want, rows["c.3gp"]["_dest"]


@case
def m14_video_is_decided_by_real_type_never_the_extension():
    """REPRODUCTION, the mislabeled case. Measured on real manifests: 14 files
    named like stills are really video (`.PNG`->MOV, `.HEIC`->MP4 …) and 361
    named like video are really stills (`.MOV`->HEIC ×346). The extension is
    what D13 renames at copy precisely because it cannot be trusted."""
    with tempfile.TemporaryDirectory() as tmp:
        rows, wd, names = m14_settle(tmp,
            "/raw/looks.png,looks.png,MOV,10,-,-,2012:02:02 09:00:00+08:00,-\n"
            "/raw/looks.mov,looks.mov,HEIC,10,-,-,2013:03:03 09:00:00+08:00,-\n")
    video = rows["looks.png"]["_dest"]
    still = rows["looks.mov"]["_dest"]
    return (video == f"/sorted/201200_{names['to_be_checked']}"
            and still == f"/sorted/_{names['to_be_checked']}/{wd.name}"), \
        f"png-named MOV -> {video} | mov-named HEIC -> {still}"


@case
def m14_file_create_date_is_never_read_for_a_year():
    """GUARD. FileCreateDate is the copy-to-drive stamp — 0 of 418 right,
    measured independently twice. A video with no usable FileModifyDate must
    claim NO year, never fall back to the create date."""
    with tempfile.TemporaryDirectory() as tmp:
        rows, wd, names = m14_settle(tmp,
            "/raw/v.mp4,v.mp4,MP4,10,-,-,-,2025:09:04 12:00:00+08:00\n")
    dest = rows["v.mp4"]["_dest"]
    return ("2025" not in dest
            and dest == f"/sorted/_{names['to_be_checked']}/{wd.name}"), dest


@case
def m14_an_import_name_a_drive_refuses_is_refused_not_rewritten():
    """REPRODUCTION-in-kind. There was no sanitiser for a folder built from an
    import's name, because no-date buckets were never built from anything but
    a date. ⛔ REFUSED rather than rewritten: a sanitiser turning `a:b` into
    `a_b` could make two different imports share one subfolder — the very
    collision the per-import subfolder exists to prevent.
    Measured on 20 real source names: none carries such a character."""
    bad = []
    # ⛔ `..` and not `.`: Path("/work/.") normalises to "work", so a work dir
    # named `.` cannot reach this at all; `..` survives Path and is guarded.
    # `a\\b` only where a backslash can be in a name: on Windows it is a
    # separator, the work dir's name is `b`, and there is nothing to refuse.
    names = ["a:b", "a*b", 'a"b', "a|b", "a?b", "a<b", "a>b", "a\x01b", ".."]
    if os.sep == "/":
        names.append("a\\b")
    for name in names:
        try:
            photo_plan.import_folder("/work/" + name)
        except SystemExit:
            continue
        bad.append(repr(name))
    for good in ("202602__", "2024-25 S24U-mix2", "2020-2022"):
        try:
            if photo_plan.import_folder("/work/" + good) != good:
                bad.append("rewrote " + good)
        except SystemExit:
            bad.append("refused a safe name " + good)
    return not bad, "; ".join(bad)


@case
def m14_every_route_it_writes_passes_the_bucket_check():
    """GUARD. The routes above only ever build the three accepted forms, so the
    check wired into them can fire only if a route regresses. It is here so a
    future route cannot put an unchecked name on the drive without failing."""
    with tempfile.TemporaryDirectory() as tmp:
        rows, _wd, names = m14_settle(tmp,
            "/raw/v.mp4,v.mp4,MP4,10,-,-,2009:04:05 10:00:00+08:00,-\n"
            "/raw/s.jpg,s.jpg,JPEG,10,-,-,2023:01:01 10:00:00+08:00,-\n"
            "/raw/n.mp4,n.mp4,MP4,10,-,-,-,-\n")
    bad = [r["_dest"] for r in rows.values()
           if photo_name.bucket_form(
               Path(r["_dest"]).relative_to("/sorted").parts[0],
               names["to_be_checked"]) is None]
    return not bad, bad


@case
def settle_rows_keeps_the_dedupe_stop():
    """GUARD. OA-3: a plan that declares `refs` with no dedupe results stops
    in `settle_rows()` itself, so no caller can route past it."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = runnable_workdir(
            tmp, {1: [label("/raw/a.jpg", {"subject_id": "subj-0001"})]})
        config = json.loads((wd / "plans.json").read_text())
        config["plans"][0]["refs"] = [str(Path(tmp) / "elsewhere")]
        (wd / "plans.json").write_text(json.dumps(config))
        try:
            settle(wd, pack)
        except SystemExit as exc:
            return "OA-3" in str(exc.code), str(exc.code)
    return False, "no stop"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    failures = []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
        # A case that RAISES is a failure with a reason, not a crash that
        # takes the tally with it: without this the first exception ends the
        # run and the remaining cases report nothing at all.
        try:
            ok, detail = fn()
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  "
                  f"{fn.__name__.replace('_', ' ').ljust(width)}"
                  + (f"   {detail}" if not ok else ""))

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} photo_plan cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
