#!/usr/bin/env python3
"""Card 9 — the screen-size route, followed up (items 1-3 and D1).

1. The census and the copy step's G-2 used two rules for "this is a screen
   size", so a size G-2 proposed was never on the sheet and had no route into
   the pack. Owner 20260925: ONE rule, in the census — a size proven by one
   screenshot-NAMED no-camera still is offered too. A pasted or page `screen:`
   line may add a NEW size only if the bound collection's census offers it.
2. Gap A: an uncounted new size was still written. It is now refused, and the
   dry run and the write print the same line.
3. The morning line and the post-copy banner name the sheet route, and stop
   once every proposed size is answered.
D1. G-2 counted a no-date file twice (manifest.csv + no-date-files.csv).

Each case says REPRO (fails on f4b656f) or GUARD.
"""

import contextlib
import csv
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
import photo_census  # noqa: E402
import photo_onboard_page as op  # noqa: E402
import photo_plan  # noqa: E402
import photo_profile  # noqa: E402
import photo_run  # noqa: E402
import photo_schedule as sch  # noqa: E402
from screen_route_cases import make_pack, make_unit, run  # noqa: E402

FIELDS = ["SourceFile", "FileName", "FileType", "Make", "Model", "ImageWidth",
          "ImageHeight"]
SHOT = "Screenshot_20240101-101010.png"
NEW = "1179x2556"


def row(name, ftype, w, h, make="-", model="-"):
    return {"SourceFile": "/raw/" + name, "FileName": name, "FileType": ftype,
            "Make": make, "Model": model, "ImageWidth": str(w),
            "ImageHeight": str(h)}


def write_rows(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def one_shot_unit(work, name="phone-2", owner="betauser"):
    """A bound work dir whose ONLY evidence for 1179x2556 is one file named
    like a screenshot — the size G-2 proposes and the old census did not."""
    unit = work / name
    unit.mkdir(parents=True)
    (work / "collection.json").write_text(json.dumps({"owner": owner}))
    write_rows(unit / "manifest.csv", [
        row(SHOT, "PNG", 1179, 2556),
        row("IMG_0001.JPG", "JPEG", 4032, 3024, "Apple", "Phone"),
    ])
    return unit


def screens_in(pack):
    profile = json.loads((pack / "photo-profile.json").read_text(encoding="utf-8"))
    return sorted(tuple(sorted(e["dims"])) for e in profile.get("screen_dims") or [])


def g2(rows):
    tmp = Path(tempfile.mkdtemp())
    try:
        write_rows(tmp / "manifest.csv", rows)
        return {tuple(sorted(int(x) for x in k))
                for k in photo_plan.screen_size_candidates(tmp, {})}
    finally:
        shutil.rmtree(tmp)


def census_sizes(rows):
    return {tuple(sorted(int(x) for x in c["dims"]))
            for c in photo_census.census(rows)["screen_size_candidates"]}


# ---------------------------------------------------------------- item 1 --

def case_one_named_screenshot_is_offered(tmp):
    """REPRO 1 — one screenshot-named no-camera still: G-2 proposed its size,
    the census did not, so no sheet ever asked it."""
    rows = [row(SHOT, "PNG", 1080, 2340)]
    assert g2(rows) == {(1080, 2340)}, g2(rows)
    assert census_sizes(rows) == {(1080, 2340)}, census_sizes(rows)


def case_every_g2_size_is_a_census_size(tmp):
    """REPRO 1 — the census's rule contains G-2's: portrait, landscape, a
    witness among others, several sizes at once."""
    rows = [row(SHOT, "PNG", 2340, 1080), row("a.png", "PNG", 1080, 2340),
            row("Screenshot_2.jpg", "JPEG", 1290, 2796),
            row("IMG_1.HEIC", "HEIC", 3024, 4032, "Apple", "Phone"),
            row("b.png", "PNG", 720, 1600)]
    assert g2(rows) and g2(rows) <= census_sizes(rows), (g2(rows), census_sizes(rows))


def case_a_camera_size_is_still_asked_with_its_warning(tmp):
    """GUARD 1 — a size a camera in the dump also emits: G-2 still does not
    route it, the census still asks it and says why to doubt it."""
    rows = [row("Screenshot_1.png", "PNG", 3000, 4000),
            row("Screenshot_2.png", "PNG", 3000, 4000),
            row("IMG_1.JPG", "JPEG", 3000, 4000, "Maker", "Cam")]
    assert g2(rows) == set(), g2(rows)
    got = photo_census.census(rows)["screen_size_candidates"]
    assert [c["dims"] for c in got] == [["3000", "4000"]], got
    assert "camera" in (got[0]["warning"] or ""), got


def case_one_unnamed_file_still_proves_nothing(tmp):
    """GUARD 1 — the threshold stands for an UNNAMED file."""
    rows = [row("IMG_0003.PNG", "PNG", 1170, 2532)]
    c = photo_census.census(rows)
    assert c["screen_size_candidates"] == [] and c["screen_sizes_below_threshold"] == 1, c


def case_a_g2_size_goes_through_the_sheet_end_to_end(tmp):
    """REPRO 1 (LL-PHO-220) — the route the messages now name, run: G-2
    proposes the size, `sheet` asks it, the dry run COUNTS it, and only the
    owner's yes (--add-screen) writes it."""
    pack = make_pack(tmp)
    unit = one_shot_unit(tmp / "Working Files")
    assert (1179, 2556) in {tuple(sorted(int(x) for x in k))
                            for k in photo_plan.screen_size_candidates(
                                unit, json.loads((pack / "photo-profile.json")
                                                 .read_text()))}
    out = tmp / "onboard"
    code, said = run("sheet", unit, "--out-dir", out, "--profile", pack)
    assert code == 0, said
    answers = out / "answers.txt"
    text = answers.read_text(encoding="utf-8")
    assert ">>> screen: %s =\n" % NEW in text, text
    answers.write_text(text.replace(">>> screen: %s =\n" % NEW,
                                    ">>> screen: %s = Phone 2\n" % NEW),
                       encoding="utf-8")
    code, said = run("apply", answers, "--pack", pack)
    assert "NEW screen size %s MOVES FILES. Show the owner this" % NEW in said, said
    assert "NOT COUNTED" not in said, said
    code, said = run("apply", answers, "--write-pack", pack, "--add-screen", NEW)
    assert (1179, 2556) in screens_in(pack), said


# ------------------------------------------------- item 1, the pasted hole --

def pasted(tmp, where, line="screen: %s = Phone 2\n" % NEW):
    answers = where / "answers.txt"
    answers.parent.mkdir(parents=True, exist_ok=True)
    answers.write_text(line, encoding="utf-8")
    return answers


def case_a_pasted_size_never_offered_is_refused(tmp):
    """REPRO 1 — a pasted `screen:` line for a size the collection's census
    never offered was written, photographs or not."""
    pack = make_pack(tmp)
    unit = one_shot_unit(tmp / "Working Files")
    answers = pasted(tmp, unit / "loose", "screen: 1440x3088 = Phone 9\n")
    code, said = run("apply", answers, "--write-pack", pack,
                     "--add-screen", "1440x3088")
    assert (1440, 3088) not in screens_in(pack), said
    assert "never offered it" in said and "sheet" in said, said
    assert "Show the owner this" not in said, said


def case_a_pasted_size_the_census_offers_is_written(tmp):
    """GUARD 1 — the same pasted line for a size the census offers, counted,
    with the owner's yes, is written."""
    pack = make_pack(tmp)
    unit = one_shot_unit(tmp / "Working Files")
    answers = pasted(tmp, unit / "loose")
    code, said = run("apply", answers, "--write-pack", pack, "--add-screen", NEW)
    assert (1179, 2556) in screens_in(pack), said
    assert "Show the owner this" in said, said


def case_a_page_answer_is_gated_like_a_pasted_one(tmp):
    """REPRO 1 — the page route has no questions digest: a page whose data
    block was edited to ask a size the census never offered wrote it."""
    pack = make_pack(tmp)
    unit = one_shot_unit(tmp / "Working Files")
    data = {"screens": {"candidates": [{"dims": [1440, 3088]}]},
            "submitted": {"lines": ["screen: 1440x3088 = Phone 9"]}}
    page = unit / "onboard.html"
    page.write_text('<script id="onboard-data" type="application/json">%s'
                    '</script>' % json.dumps(data), encoding="utf-8")
    code, said = run("apply", page, "--write-pack", pack,
                     "--add-screen", "1440x3088")
    assert (1440, 3088) not in screens_in(pack), said
    assert "never offered it" in said, said


# ---------------------------------------------------------------- item 2 --

def case_uncounted_pasted_is_refused_not_written(tmp):
    """REPRO 2 (Gap A) — no collection to count against: it printed NOT
    COUNTED and wrote the size anyway."""
    pack = make_pack(tmp)
    answers = pasted(tmp, tmp / "loose")
    code, said = run("apply", answers, "--write-pack", pack, "--add-screen", NEW)
    assert (1179, 2556) not in screens_in(pack), said
    assert "could not be counted" in said and 'sheet "<work dir>"' in said, said
    assert code == 1, (code, said)


def case_uncounted_unstamped_sheet_is_refused(tmp):
    """REPRO 2 (Gap A) — a real sheet with no `workdirs:` line, kept away
    from its collection. Three unnamed stills, so the size is asked on the
    old rule too and only the count is at stake."""
    pack = make_pack(tmp)
    unit = make_unit(tmp / "Working Files", "phone-2")
    out = tmp / "far" / "away"
    code, said = run("sheet", unit, "--out-dir", out, "--profile", pack)
    answers = out / "answers.txt"
    text = "\n".join(line for line in answers.read_text(encoding="utf-8")
                     .splitlines() if not line.startswith("workdirs:")) + "\n"
    answers.write_text(text.replace(">>> screen: %s =\n" % NEW,
                                    ">>> screen: %s = Phone 2\n" % NEW),
                       encoding="utf-8")
    code, said = run("apply", answers, "--write-pack", pack, "--add-screen", NEW)
    assert (1179, 2556) not in screens_in(pack), said
    assert "could not be counted" in said, said


def case_dry_run_and_write_say_the_same(tmp):
    """REPRO 2 (F-gg) — the dry run said `add` where the write had nothing to
    count; both now print the same `refuse` line."""
    pack = make_pack(tmp)
    answers = pasted(tmp, tmp / "loose")

    def verdict(said):
        return [line.split()[0] for line in said.splitlines()
                if "screen_dims" in line and not line.strip().startswith("⛔")]
    _c, dry = run("apply", answers, "--pack", pack, "--add-screen", NEW)
    _c, wrote = run("apply", answers, "--write-pack", pack, "--add-screen", NEW)
    assert verdict(dry) == verdict(wrote) == ["refuse"], (verdict(dry), verdict(wrote))


# -------------------------------------------------------------------- D1 --

def case_a_no_date_file_is_counted_once(tmp):
    """REPRO D1 — no-date-files.csv is a subset of manifest.csv, and G-2 read
    both: one no-date screenshot was `files: 2`."""
    rows = [row(SHOT, "PNG", 1080, 2340)]
    write_rows(tmp / "manifest.csv", rows)
    write_rows(tmp / "no-date-files.csv", rows)
    got = photo_plan.screen_size_candidates(tmp, {})
    assert [c["files"] for c in got.values()] == [1], got


# ---------------------------------------------------------------- item 3 --

def proposals(workdir, dims=(1179, 2556), moved=None):
    (workdir / "plan").mkdir(parents=True, exist_ok=True)
    (workdir / "plan" / photo_run.SCREEN_PROPOSALS_NAME).write_text(json.dumps({
        "proposed_screen_dims": [{"model": None, "dims": list(dims),
                                  "files_at_this_size": 1, "proven_by": SHOT}],
        "moved_to_to_be_checked": moved or {"1": 1}}))


def bound(tmp, **extra):
    """A work dir holding a G-2 proposal, bound by collection.json to a pack
    carrying `extra`. -> the collection folder."""
    pack = make_pack(tmp)
    profile = json.loads((pack / "photo-profile.json").read_text())
    profile.update(extra)
    (pack / "photo-profile.json").write_text(json.dumps(profile))
    unit = one_shot_unit(tmp / "Working Files")
    (tmp / "Working Files" / "collection.json").write_text(
        json.dumps({"owner": "betauser", "memory_root": str(tmp)}))
    proposals(unit)
    return tmp / "Working Files", unit


def morning(coll):
    msg = photo_profile.schedule_messages({})
    return [line for line in sch.waiting_for_owner(coll, msg) if "screen" in line]


def case_the_morning_line_names_the_sheet(tmp):
    """REPRO 3 — it said "an unconfirmed screen size to confirm" and named
    no way to confirm one."""
    coll, unit = bound(tmp)
    got = morning(coll)
    assert len(got) == 1 and NEW in got[0], got
    assert "photo_onboard_page.py sheet" in got[0] and str(unit) in got[0], got


def case_the_morning_line_stops_once_added(tmp):
    """REPRO 3 — it fired on the file existing, so a size the pack already
    holds was still "waiting"."""
    coll, _unit = bound(tmp, screen_dims=[{"model": "P", "dims": [2556, 1179]}])
    assert morning(coll) == [], morning(coll)


def case_the_morning_line_stops_once_declined(tmp):
    """REPRO 3 — the same for a size the owner declined."""
    coll, _unit = bound(tmp, declined_screen_dims=[[1179, 2556]])
    assert morning(coll) == [], morning(coll)


def case_a_passed_pack_beats_the_collections(tmp):
    """GUARD 3 — `status --profile` passes its pack; it decides."""
    coll, _unit = bound(tmp)
    msg = photo_profile.schedule_messages({})
    got = [x for x in sch.waiting_for_owner(
        coll, msg, {"declined_screen_dims": [[1179, 2556]]}) if "screen" in x]
    assert got == [], got


def case_a_missing_pack_never_stops_the_morning(tmp):
    """GUARD 3 — the per-work-dir pack lookup hard-fails on a collection whose
    owner has no pack; the morning answer lists the size instead of exiting."""
    unit = one_shot_unit(tmp / "Working Files")
    (tmp / "Working Files" / "collection.json").write_text(
        json.dumps({"owner": "ghost", "memory_root": str(tmp / "nowhere")}))
    proposals(unit)
    got = morning(tmp / "Working Files")
    assert len(got) == 1 and NEW in got[0], got


def case_a_sheet_without_its_digest_is_gated_as_pasted(tmp):
    """REPRO 1 — `sheet: 1` alone made a file a sheet, and a sheet skipped
    the census check even when its questions digest line had been deleted, so
    an invented `>>> screen:` line was counted and written."""
    pack = make_pack(tmp)
    unit = one_shot_unit(tmp / "Working Files")
    answers = unit / "loose" / "answers.txt"
    answers.parent.mkdir()
    answers.write_text("sheet: 1\nworkdirs: %s\n>>> screen: 1440x3088 = Phone 9\n"
                       % json.dumps([str(unit)]), encoding="utf-8")
    code, said = run("apply", answers, "--write-pack", pack,
                     "--add-screen", "1440x3088")
    assert (1440, 3088) not in screens_in(pack), said
    assert "never offered it" in said, said


def banner(workdir):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        photo_run.print_screen_checkpoint(workdir)
    return buf.getvalue()


def case_the_banner_names_the_sheet(tmp):
    """REPRO 3 — the post-copy banner said adding one was "not possible from
    here yet"."""
    _coll, unit = bound(tmp)
    said = banner(unit)
    assert "photo_onboard_page.py sheet" in said and "not possible" not in said, said


def case_the_banner_stops_once_answered(tmp):
    """REPRO 3 — it kept printing a size the owner had declined."""
    _coll, unit = bound(tmp, declined_screen_dims=[[1179, 2556]])
    assert banner(unit) == "", banner(unit)


CASES = [
    ("1: one named screenshot is offered (REPRO)", case_one_named_screenshot_is_offered),
    ("1: every G-2 size is a census size (REPRO)", case_every_g2_size_is_a_census_size),
    ("1: a camera size is still asked with its warning (GUARD)",
     case_a_camera_size_is_still_asked_with_its_warning),
    ("1: one unnamed file still proves nothing (GUARD)",
     case_one_unnamed_file_still_proves_nothing),
    ("1: a G-2 size goes through the sheet end to end (REPRO)",
     case_a_g2_size_goes_through_the_sheet_end_to_end),
    ("1: a pasted size never offered is refused (REPRO)",
     case_a_pasted_size_never_offered_is_refused),
    ("1: a pasted size the census offers is written (GUARD)",
     case_a_pasted_size_the_census_offers_is_written),
    ("1: a page answer is gated like a pasted one (REPRO)",
     case_a_page_answer_is_gated_like_a_pasted_one),
    ("2: uncounted pasted is refused, not written (REPRO)",
     case_uncounted_pasted_is_refused_not_written),
    ("2: uncounted unstamped sheet is refused (REPRO)",
     case_uncounted_unstamped_sheet_is_refused),
    ("2: dry run and write say the same (REPRO)", case_dry_run_and_write_say_the_same),
    ("D1: a no-date file is counted once (REPRO)", case_a_no_date_file_is_counted_once),
    ("3: the morning line names the sheet (REPRO)", case_the_morning_line_names_the_sheet),
    ("3: the morning line stops once added (REPRO)", case_the_morning_line_stops_once_added),
    ("3: the morning line stops once declined (REPRO)",
     case_the_morning_line_stops_once_declined),
    ("3: a passed pack beats the collection's (GUARD, new parameter)",
     case_a_passed_pack_beats_the_collections),
    ("3: a missing pack never stops the morning (GUARD)",
     case_a_missing_pack_never_stops_the_morning),
    ("1: a sheet without its digest is gated as pasted (REPRO)",
     case_a_sheet_without_its_digest_is_gated_as_pasted),
    ("3: the banner names the sheet (REPRO)", case_the_banner_names_the_sheet),
    ("3: the banner stops once answered (REPRO)", case_the_banner_stops_once_answered),
]


def main():
    passed, failed = 0, []
    for label, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="rb9_"))
        try:
            with photo_profile_env_cleared():
                fn(tmp)
            print("  ok    " + label)
            passed += 1
        except Exception as err:  # noqa: BLE001 — the runner reports, never stops
            print("  FAIL  %s: %s: %s" % (label, type(err).__name__, err))
            failed.append(label)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d/%d screen_followup cases passed%s"
          % (passed, len(CASES), " — FAILED: " + "; ".join(failed) if failed else ""))
    return 1 if failed else 0


@contextlib.contextmanager
def photo_profile_env_cleared():
    import os
    saved = os.environ.pop(photo_profile.ENV_VAR, None)
    try:
        yield
    finally:
        if saved is not None:
            os.environ[photo_profile.ENV_VAR] = saved


if __name__ == "__main__":
    sys.exit(main())
