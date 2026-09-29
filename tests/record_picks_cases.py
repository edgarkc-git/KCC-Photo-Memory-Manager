#!/usr/bin/env python3
"""U-3 cases — the owner's naming decision reaches the frames it was about.

`photo_plan.visual_columns()` resolves `[who]` from the registry BY
`subject_id`. A first dump's see-labels carry none: the see stage runs before
the naming checkpoint, because it is what drafts the subjects, so at label-
writing time nothing is confirmed and `subject_kind` is the only honest thing
to write. Confirming a name afterwards did not rewrite those labels, so a
folder kept the class word with `draft:` even though the owner had just named
the cat — measured end to end, `who` 0/15 in UAT01-3.

U-3 writes the `subject_id` onto EXACTLY the frames the owner picked, at
`confirm --go`. ⭐ It RECORDS a decision; it does not MAKE one. No matching
runs, no selection moves, no model is called.

⛔ THE MOST IMPORTANT CASE HERE IS NOT THE REPRODUCTION. It is
`a_frame_the_owner_did_not_pick_gains_nothing`: widening coverage by matching
is what U-3 v1.0 proposed, and it was measured to offer a HOME cat's id for
five street-cat frames at score 1.0 in identity space. A folder holding none
of the picked frames correctly gets no `[who]`, and that is the safe
direction, not a gap to close.

⛔ FIXTURE FROM A REAL ARTIFACT (LL-PHO-176). The golden fixture set's
`tier3cat/…/see-labels.json` is a file the engine wrote (no fixture set →
every case skips, naming `$PHOTO_GOLDEN_FIXTURES`); it carries the pre-R4 `subject`
shape and no `subject_id`, which is exactly the state U-3 exists to move.

⚠️ NO PACK-ROUTE CASES: `record_confirmed_subject_ids()` takes no pack,
resolves none and reads none. The route a pack arrives by is `require_pack`'s
question and is covered where that is tested; a route case here would assert
nothing.

  python3 tests/record_picks_cases.py [-v]

Exit 0 = pass. Everything is built in a temp dir; no drive is read.
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))
import golden_replay  # noqa: E402
import photo_evidence  # noqa: E402
import photo_plan  # noqa: E402
import photo_profile  # noqa: E402
import photo_see  # noqa: E402
import photo_subjects  # noqa: E402

TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

CASES = []


class Skipped(Exception):
    """No fixture set to read. Neither a pass nor a failure — printed with its
    reason and counted apart, the photo_memory_cases.py rule."""


def fixture(*parts):
    """-> a path under the golden fixture root, resolved by the replay
    harness's ONE resolver (--fixtures > $PHOTO_GOLDEN_FIXTURES >
    tests/golden). Raises Skipped when that file is not there."""
    path = golden_replay.fixture_root().joinpath(*parts)
    if not path.is_file():
        raise Skipped(f"no fixture at {path} — point "
                      f"${golden_replay.ENV_FIXTURES} at a fixture set")
    return path


def case(fn):
    CASES.append(fn)
    return fn


def real_entries():
    path = fixture("tier3cat", "input", "classify", "batch-01", "see-labels.json")
    return json.loads(path.read_text(encoding="utf-8"))["labels"]


def viewed(entries):
    return [e for e in entries
            if e.get("provenance") == photo_evidence.VIEWED and e.get("sample")]


def build_workdir(root, entries, batch="batch-01"):
    """A work dir holding the REAL labels file and the see-report that pairs
    each sample with its source file. -> (workdir, batch dir)."""
    workdir = Path(root) / "work"
    bdir = workdir / "classify" / batch
    (bdir / "samples").mkdir(parents=True)
    for e in entries:
        if e.get("sample"):
            (bdir / "samples" / e["sample"]).write_bytes(PNG)
    (bdir / "see-report.json").write_text(json.dumps({
        "engine": "test", "batch": 1,
        "selected": [{"path": e["path"], "sample": e["sample"]}
                     for e in viewed(entries)],
        "clusters": [], "provisional": []}, ensure_ascii=False),
        encoding="utf-8")
    (bdir / "see-labels.json").write_text(json.dumps(
        {"engine": "test", "batch": 1, "applied_at": "2026-01-01 00:00",
         "labels": entries}, ensure_ascii=False), encoding="utf-8")
    return workdir, bdir


def labels_of(bdir):
    return json.loads((bdir / "see-labels.json").read_text())["labels"]


def entry_for(bdir, path):
    return [e for e in labels_of(bdir) if e["path"] == path][0]


def rel_sample(batch, entry):
    return f"classify/{batch}/samples/{entry['sample']}"


def make_pack(root, subjects):
    pack_dir = Path(root) / "photo-memory" / "fixture-owner"
    pack_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE, pack_dir)
    for path in list(pack_dir.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", "fixture-owner")))
    pf = pack_dir / photo_profile.PROFILE_NAME
    pf.write_text(pf.read_text(encoding="utf-8")
                  .replace("{{SLUG}}", "fixture-owner")
                  .replace("{{DISPLAY}}", "fixture-owner"), encoding="utf-8")
    reg = pack_dir / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text(encoding="utf-8"))
    data["subjects"] = subjects
    reg.write_text(json.dumps(data), encoding="utf-8")
    return photo_profile.resolve_pack(explicit=pf)


def confirmed(sid, name):
    return {"subject_id": sid, "exemplars": [], "name": name, "who": name,
            "kind": "cat", "status": photo_subjects.STATUS_CONFIRMED}


def drafted(sid, name="Whiskers"):
    return {"subject_id": sid, "exemplars": [], "name": name, "kind": "cat",
            "status": photo_subjects.STATUS_DRAFT}


# ---------------------------------------------------------------------------
# the fixture, first (LL-PHO-176)
# ---------------------------------------------------------------------------

@case
def the_fixture_is_a_real_first_dump_artifact():
    """⛔ The state U-3 exists to move, asserted rather than assumed: a real
    applied labels file carries `viewed-image:` rows and NO `subject_id`. U-2
    shipped two green tests whose hand-built labels already had one."""
    entries = real_entries()
    ids = [s for e in entries for s in photo_evidence.subject_list(e)
           if s.get("subject_id")]
    kinds = [s for e in entries for s in photo_evidence.subject_list(e)
             if s.get("subject_kind")]
    return (not ids and kinds and len(viewed(entries)) >= 2), \
        f"ids={len(ids)}, kinds={len(kinds)}, viewed={len(viewed(entries))}"


# ---------------------------------------------------------------------------
# what U-3 writes
# ---------------------------------------------------------------------------

@case
def a_picked_frame_gains_the_subject_id():
    """REPRODUCTION. ⚠️ A new capability, so it is stated honestly: on
    `d977d77` no code writes this field at all, and the case asserts the field
    arrives — not that an old code path behaved differently."""
    entries = real_entries()
    pick = viewed(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        wd, bdir = build_workdir(tmp, entries)
        out = photo_see.record_confirmed_subject_ids(
            wd, [(rel_sample("batch-01", pick), "subj-0001")])
        got = photo_evidence.subject_list(entry_for(bdir, pick["path"]))
    return (len(out["written"]) == 1 and len(got) == 1
            and got[0].get("subject_id") == "subj-0001"), \
        f"written={out['written']}, subjects={got}"


@case
def the_name_then_reaches_the_plan_csv_with_no_draft_marker():
    """The end the whole card is for: with the id recorded, the renderer that
    was always correct prints the owner's name and drops `draft:`."""
    entries = real_entries()
    pick = viewed(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        wd, bdir = build_workdir(tmp, entries)
        pack = make_pack(tmp, [confirmed("subj-0001", "Lotus")])
        before = photo_plan.visual_columns(wd, [1], pack.profile, pack)
        photo_see.record_confirmed_subject_ids(
            wd, [(rel_sample("batch-01", pick), "subj-0001")])
        after = photo_plan.visual_columns(wd, [1], pack.profile, pack)
    b, a = before[pick["path"]], after[pick["path"]]
    return (a.get("who") == "Lotus"
            and not a["who_provenance"].startswith(photo_evidence.DRAFT)
            and b.get("who") != "Lotus"), \
        f"before={b.get('who')!r}/{b['who_provenance']!r} -> " \
        f"after={a.get('who')!r}/{a['who_provenance']!r}"


@case
def the_viewed_provenance_is_untouched():
    """GUARD (trap 1). One field is added; the claim that makes `[who]` legal
    under N-4 must be exactly as it was."""
    entries = real_entries()
    pick = viewed(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        wd, bdir = build_workdir(tmp, entries)
        photo_see.record_confirmed_subject_ids(
            wd, [(rel_sample("batch-01", pick), "subj-0001")])
        after = entry_for(bdir, pick["path"])
    return (after["provenance"] == pick["provenance"]
            and after["label"] == pick["label"]
            and after["sample"] == pick["sample"]
            and not after.get("preserved")), f"{after}"


# ---------------------------------------------------------------------------
# ⛔ the anti-A19 case — the most important one in the file
# ---------------------------------------------------------------------------

@case
def a_frame_the_owner_did_not_pick_gains_nothing():
    """⛔ THE CASE THAT MATTERS MOST. U-3 v1.0 would have written ids from the
    registry's own matches; measured, those offered a HOME cat's id for five
    street-cat frames at score 1.0 in identity space. Only picked frames are
    touched — an unpicked frame keeps its class word and its `draft:`, and a
    folder made of them correctly gets no `[who]`."""
    entries = real_entries()
    v = viewed(entries)
    picked, other = v[0], v[1]
    with tempfile.TemporaryDirectory() as tmp:
        wd, bdir = build_workdir(tmp, entries)
        pack = make_pack(tmp, [confirmed("subj-0001", "Lotus")])
        photo_see.record_confirmed_subject_ids(
            wd, [(rel_sample("batch-01", picked), "subj-0001")])
        cells = photo_plan.visual_columns(wd, [1], pack.profile, pack)
        got = photo_evidence.subject_list(entry_for(bdir, other["path"]))
    cell = cells[other["path"]]
    return (not any(s.get("subject_id") for s in got)
            and cell.get("who") != "Lotus"
            and cell["who_provenance"].startswith(photo_evidence.DRAFT)), \
        f"subjects={got}, who={cell.get('who')!r}/{cell['who_provenance']!r}"


def two_animal_entries():
    entries = [dict(e) for e in real_entries()]
    pick = viewed(entries)[0]
    for e in entries:
        if e["path"] == pick["path"]:
            e.pop("subject", None)
            e["subjects"] = [{"subject_kind": "cat"}, {"subject_kind": "dog"}]
    return entries, pick


@case
def a_frame_with_two_animals_logs_every_name_the_owner_picked():
    """⭐ REPRODUCTION (G6 R6). ⛔ FAILS on 4c8e639: the frame was SKIPPED, so
    neither name reached it. Owner amendment 20260904: two subjects in one
    frame is two names to log, never a frame to refuse. Both picked names are
    written at FRAME level, and ⛔ no detection box gains an id — which box is
    which animal is what the frame cannot say (C10)."""
    entries, pick = two_animal_entries()
    with tempfile.TemporaryDirectory() as tmp:
        wd, bdir = build_workdir(tmp, entries)
        out = photo_see.record_confirmed_subject_ids(
            wd, [(rel_sample("batch-01", pick), "subj-0001"),
                 (rel_sample("batch-01", pick), "subj-0002")])
        entry = entry_for(bdir, pick["path"])
        pack = make_pack(tmp, [confirmed("subj-0001", "Lotus"),
                               confirmed("subj-0002", "Birk")])
        cell = photo_plan.visual_columns(wd, [1], pack.profile, pack)[pick["path"]]
    boxes = photo_evidence.subject_list(entry)
    return (entry.get("subject_ids") == ["subj-0001", "subj-0002"]
            and not any(s.get("subject_id") for s in boxes)
            and sorted(cell.get("who", "").split("+")) == ["Birk", "Lotus"]
            and not cell["who_provenance"].startswith(photo_evidence.DRAFT)
            and not out["skipped_multi_subject"]), \
        f"out={out} entry={entry} who={cell.get('who')!r}/{cell['who_provenance']!r}"


@case
def a_two_animal_frame_with_one_name_picked_keeps_the_other_unnamed():
    """GUARD (G6 R6). ⛔ Only the names the owner PICKED. One name on a frame
    of two animals names one; the other stays its class word, marked draft."""
    entries, pick = two_animal_entries()
    with tempfile.TemporaryDirectory() as tmp:
        wd, bdir = build_workdir(tmp, entries)
        photo_see.record_confirmed_subject_ids(
            wd, [(rel_sample("batch-01", pick), "subj-0001")])
        entry = entry_for(bdir, pick["path"])
        pack = make_pack(tmp, [confirmed("subj-0001", "Lotus")])
        cell = photo_plan.visual_columns(wd, [1], pack.profile, pack)[pick["path"]]
    names = cell.get("who", "").split("+")
    return (entry.get("subject_ids") == ["subj-0001"] and "Lotus" in names
            and len(names) == 2
            and cell["who_provenance"].startswith(photo_evidence.DRAFT)), \
        f"entry={entry} who={cell.get('who')!r}/{cell['who_provenance']!r}"


# ---------------------------------------------------------------------------
# the rest of the traps
# ---------------------------------------------------------------------------

@case
def recording_twice_changes_nothing_the_second_time():
    """GUARD (trap 3). Confirming twice must not duplicate or corrupt. The id
    is written, never the NAME, so a later rename is carried by the registry
    and this file does not go stale (N-10a)."""
    entries = real_entries()
    pick = viewed(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        wd, bdir = build_workdir(tmp, entries)
        rel = rel_sample("batch-01", pick)
        photo_see.record_confirmed_subject_ids(wd, [(rel, "subj-0001")])
        first = (bdir / "see-labels.json").read_text()
        again = photo_see.record_confirmed_subject_ids(wd, [(rel, "subj-0001")])
        second = (bdir / "see-labels.json").read_text()
    return (not again["written"] and first == second), \
        f"second pass wrote {again['written']}"


@case
def the_id_a_pick_replaces_is_reported():
    """REPRODUCTION (FIX7, U7-1). A second pick overwrites the first id; the
    report says which id went, so the caller can audit it."""
    entries = real_entries()
    pick = viewed(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        wd, _bdir = build_workdir(tmp, entries)
        rel = rel_sample("batch-01", pick)
        first = photo_see.record_confirmed_subject_ids(wd, [(rel, "subj-0001")])
        second = photo_see.record_confirmed_subject_ids(wd, [(rel, "subj-0002")])
    got = second.get("replaced")
    return (first.get("replaced") == [] and got is not None and len(got) == 1
            and got[0]["replaced"] == "subj-0001"
            and got[0]["subject_id"] == "subj-0002"
            and got[0]["path"] == pick["path"]), f"first={first}, second={second}"


@case
def a_rename_does_not_strand_the_recorded_id():
    """GUARD (trap 3, second half). Only the id is stored, so renaming the
    subject afterwards re-renders under the new name with nothing rewritten."""
    entries = real_entries()
    pick = viewed(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        wd, _bdir = build_workdir(tmp, entries)
        pack = make_pack(tmp, [confirmed("subj-0001", "Lotus")])
        photo_see.record_confirmed_subject_ids(
            wd, [(rel_sample("batch-01", pick), "subj-0001")])
        renamed = make_pack(Path(tmp) / "second",
                            [confirmed("subj-0001", "Bao")])
        cells = photo_plan.visual_columns(wd, [1], renamed.profile, renamed)
    return cells[pick["path"]].get("who") == "Bao", \
        f"who={cells[pick['path']].get('who')!r}"


@case
def an_unconfirmed_subject_still_renders_the_class_word():
    """GUARD (trap 2). If a draft's id ever reached a label, the renderer must
    still refuse to print its proposed name — N-4, and the `draft:` guard U-2
    proved is holding. ⛔ `cmd_confirm` will not pass a draft here in the first
    place; this asserts the second line of defence."""
    entries = real_entries()
    pick = viewed(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        wd, _bdir = build_workdir(tmp, entries)
        pack = make_pack(tmp, [drafted("subj-0001")])
        photo_see.record_confirmed_subject_ids(
            wd, [(rel_sample("batch-01", pick), "subj-0001")])
        cell = photo_plan.visual_columns(wd, [1], pack.profile, pack)[pick["path"]]
    return (cell.get("who") != "Whiskers"
            and cell["who_provenance"].startswith(photo_evidence.DRAFT)), \
        f"who={cell.get('who')!r}/{cell['who_provenance']!r}"


@case
def a_batch_with_no_see_output_is_reported_not_crashed():
    """GUARD. A review page can name a frame from a work dir that has since
    been re-scanned. Reported, never raised — `confirm` has already written
    the pack by this point and must not fail after it."""
    entries = real_entries()
    pick = viewed(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        wd, _bdir = build_workdir(tmp, entries)
        out = photo_see.record_confirmed_subject_ids(
            wd, [(f"classify/batch-99/samples/{pick['sample']}", "subj-0001")])
    return (out["unresolved"] and not out["written"]), f"{out}"


@case
def a_pick_pointing_into_another_work_dir_is_refused_and_writes_nothing():
    """REPRODUCTION (L7, G7). A COPIED work dir's page carries the SOURCE's
    absolute sample path; on `91ca5e6` the name was written into the source's
    labels and the copy's stayed empty, with no word said."""
    entries = real_entries()
    pick = viewed(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        src, src_b = build_workdir(Path(tmp) / "source", entries)
        copy, copy_b = build_workdir(Path(tmp) / "copy", entries)
        before = [(b / "see-labels.json").read_bytes() for b in (src_b, copy_b)]
        out = photo_see.record_confirmed_subject_ids(
            copy, [(str(src_b / "samples" / pick["sample"]), "subj-0001")])
        after = [(b / "see-labels.json").read_bytes() for b in (src_b, copy_b)]
    return (before == after and not out["written"]
            and len(out.get("outside_workdir") or []) == 1), \
        f"source changed={before[0] != after[0]}, copy changed={before[1] != after[1]}, {out}"


@case
def an_absolute_pick_inside_the_work_dir_still_writes():
    """GUARD. `look_image()` falls back to an absolute path whenever the
    resolved paths disagree on a prefix; one that still lies inside this work
    dir is this work dir's own frame and must keep being recorded."""
    entries = real_entries()
    pick = viewed(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        wd, bdir = build_workdir(tmp, entries)
        out = photo_see.record_confirmed_subject_ids(
            wd, [(str(bdir.resolve() / "samples" / pick["sample"]), "subj-0001")])
        got = photo_evidence.subject_list(entry_for(bdir, pick["path"]))
    return (len(out["written"]) == 1 and not out.get("outside_workdir")
            and got[0].get("subject_id") == "subj-0001"), f"{out}"


@case
def the_untouched_batches_are_nameable_for_the_note():
    """The second half the owner asked for: partial coverage must be VISIBLE, so
    the caller can name the batches that gained nothing."""
    entries = real_entries()
    with tempfile.TemporaryDirectory() as tmp:
        wd, _bdir = build_workdir(tmp, entries)
        got = photo_see.batches_with_labels(wd)
    return got == ["batch-01"], f"{got}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    failures, skipped = [], []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
        try:
            ok, detail = fn()
        except Skipped as why:
            skipped.append(fn.__name__)
            print(f"  skip  {fn.__name__.replace('_', ' ').ljust(width)}   {why}")
            continue
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  "
                  f"{fn.__name__.replace('_', ' ').ljust(width)}"
                  + (f"   {detail}" if not ok else ""))

    ran = len(CASES) - len(skipped)
    print(f"\n{ran - len(failures)}/{ran} record-picks cases passed"
          + (f", {len(skipped)} skipped" if skipped else "")
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
