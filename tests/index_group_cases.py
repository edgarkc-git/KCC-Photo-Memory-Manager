#!/usr/bin/env python3
"""G5 cases — `photo_index.py group`: trips with legs, a monthly parent for a
named frequent place, moves / splits / merges by date, the agent's [what].

  python3 tests/index_group_cases.py [-v]

Exit 0 = pass. Every dump, pack and place is synthetic (`betauser00`,
invented coordinates) in a temp dir: a five-day trip, three visits to the
pack's named place `fsl-0001` in one month, a day out beside them that month,
a screenshot, a sidecar and a file with no date.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import photo_index  # noqa: E402
import photo_plan  # noqa: E402
import photo_profile  # noqa: E402
import photo_index_cases as ix  # noqa: E402

RUN = ROOT / "scripts" / "photo_run.py"
TRIP = (40.11111, 140.22222)          # invented, far from every pack place
SHOT = "Screenshot_20241211_101010.jpg"
SPECS = [
    ("IMG_2501.jpg", "2024:10:25 10:00:00", TRIP, {}),
    ("IMG_2601.jpg", "2024:10:26 10:00:00", TRIP, {}),
    ("IMG_2701.jpg", "2024:10:27 10:00:00", TRIP, {}),
    ("IMG_2901.jpg", "2024:10:29 10:00:00", TRIP, {}),
    ("IMG_3001.jpg", "2024:10:30 10:00:00", TRIP, {}),
    ("IMG_3101.jpg", "2024:10:31 10:00:00", TRIP, {}),
    ("IMG_0801.jpg", "2024:12:08 10:00:00", ix.FAR2, {}),
    ("IMG_1101.jpg", "2024:12:11 10:00:00", ix.FAR, {}),
    (SHOT, "2024:12:11 10:10:10", ix.FAR, {"make": "-"}),
    ("._IMG_1102.jpg", "2024:12:11 11:00:00", ix.FAR, {"ftype": "MacOS"}),
    ("IMG_2201.jpg", "2024:12:22 10:00:00", ix.FAR, {}),
    ("IMG_2601b.jpg", "2024:12:26 10:00:00", ix.FAR, {}),
    ("IMG_2602b.jpg", "2024:12:26 15:00:00", ix.FAR, {}),
    ("NODATE.jpg", "-", None, {}),
]
BATCHES = [
    {"batch": 1, "from": "2024-10-25", "to": "2024-10-25", "place": "Ashford"},
    {"batch": 2, "from": "2024-10-26", "to": "2024-10-26", "place": "Brookvale"},
    {"batch": 3, "from": "2024-10-27", "to": "2024-10-27", "place": "Cedarton"},
    {"batch": 4, "from": "2024-10-29", "to": "2024-10-30", "place": "Dunmore"},
    {"batch": 5, "from": "2024-10-31", "to": "2024-10-31", "place": "Elmwick"},
    {"batch": 6, "from": "2024-12-08", "to": "2024-12-08", "place": "Townsville"},
    {"batch": 7, "from": "2024-12-11", "to": "2024-12-11", "place": "Harbour"},
    {"batch": 8, "from": "2024-12-22", "to": "2024-12-22", "place": "Harbour"},
    {"batch": 9, "from": "2024-12-26", "to": "2024-12-26", "place": "Harbour"},
]
TRIP_DAYS = ["F001", "F002", "F003", "F004", "F005"]
VISITS = ["F007", "F008", "F009"]
BESIDE = "F006"

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def run(*argv):
    return ix.run(*argv)


def group_dump(tmp, bind=True, min_visits=None):
    """-> (work dir, pack): real files, init NOT run."""
    base = Path(tmp).resolve() / "raw" / "dump-a"
    base.mkdir(parents=True)
    rows = []
    for name, when, gps, extra in SPECS:
        rows.append(ix.row(name, when=when, gps=gps, SourceFile=f"{base}/{name}", **extra))
        note = name.encode()
        (base / name).write_bytes(
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"\xff\xfe" + (len(note) + 2).to_bytes(2, "big") + note + b"\xff\xd9")
    wd = ix.make_dump(tmp, rows=rows, batches=BATCHES, bind=bind)
    pack = ix.make_pack(tmp)
    if min_visits is not None:
        set_min_visits(pack, min_visits)
    with open(wd / "no-date-files.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ix.FIELDS)
        w.writeheader()
        w.writerows(r for r in rows if r["DateTimeOriginal"] == "-")
    return wd, pack


def set_min_visits(pack, n):
    path = pack / photo_profile.PROFILE_NAME
    prof = json.loads(path.read_text())
    prof.setdefault("cluster_defaults", {})[photo_index.MIN_VISITS_KEY] = n
    path.write_text(json.dumps(prof, indent=2))


def ready(tmp, **kw):
    wd, pack = group_dump(tmp, **kw)
    code, _o, err = run("init", wd)
    if code:
        raise RuntimeError(err[-300:])
    return wd, pack


def must(code_out_err, what):
    code, out, err = code_out_err
    if code:
        raise RuntimeError(f"{what}: rc {code} {(out + err)[-400:]}")
    return out


def trip(wd, *extra):
    return run("group", "make-trip", wd, *TRIP_DAYS, "--where", "Northland",
               "--reason", "one trip", *extra)


def fsl_month(wd):
    return run("group", "make-fsl-month", wd, "fsl-0001", "2024-12",
               "--reason", "the month's visits to one place")


def index(tmp):
    return ix.index_of(tmp)[0]


def folders(tmp):
    return ix.folders_of(index(tmp))


def render(wd):
    return must(run("render", wd, "--no-vision"), "render")


def names(tmp):
    return {fid: fo["rendered"] for fid, fo in folders(tmp).items()
            if fo["status"] != "retired"}


def invariants(ix_before, ix_after):
    """-> [broken]: file ids unchanged; every present file in at most one
    folder, a live one, and one only when its route may be copied."""
    bad = []
    ids_b = {f["source"]: f["file_id"] for f in ix_before["files"]}
    ids_a = {f["source"]: f["file_id"] for f in ix_after["files"]}
    if ids_b != ids_a:
        bad.append("file ids changed")
    live = {fo["id"] for fo in photo_index.live(ix_after)}
    for f in ix_after["files"]:
        if f["status"] != "present":
            continue
        if f["folder"] is not None and f["folder"] not in live:
            bad.append(f"{f['file_id']} sits in {f['folder']}, not a live folder")
        if f["route"] in ("skip_junk", "skip_dupe") and f["folder"] is not None:
            bad.append(f"{f['file_id']} ({f['route']}) sits in a folder")
    return bad


# ---------------------------------------------------------------------------
# the two parents
# ---------------------------------------------------------------------------

@case
def fsl_month_consolidates_the_visits_and_leaves_the_day_out_beside():
    """⭐ REPRODUCTION of U5-14's CONSOLIDATION half. ⛔ FAILS on c6f0ea7: no
    group command existed, so every visit to one place was its own top
    folder. Three visits to `fsl-0001` in one month become legs of
    `20241200_Harbour`, each leaving out the parent's place (D-I13), and the
    month's other day out stays BESIDE the parent (D-I14). The pack's
    minimum is set in the fixture: the case never rests on the code default."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp, min_visits=3)
        code, out, err = fsl_month(wd)
        render(wd)
        n, f = names(tmp), folders(tmp)
    parent = next(fid for fid, fo in f.items() if fo["kind"] == "fsl-month")
    return (code == 0 and n[parent] == "20241200_Harbour"
            and [n[v] for v in VISITS] == ["1211", "1222", "1226"]
            and all(f[v]["parent"] == parent and f[v]["kind"] == "leg" for v in VISITS)
            and n[BESIDE] == "20241208_Townsville" and f[BESIDE]["parent"] is None), \
        f"code={code} out={out!r} err={err[-300:]!r} names={n}"


@case
def a_trip_parent_takes_its_span_from_its_legs_and_the_legs_keep_their_places():
    """REPRODUCTION (walk-through 1). ⛔ FAILS on c6f0ea7 (no make-trip). The
    parent is `YYYYMMDD-MMDD_<the agent's place>`, its span derived from the
    legs' files; each leg keeps its own place because it differs from the
    parent's (D-I13)."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        code, _out, err = trip(wd, "--what", "red leaves")
        render(wd)
        n, f, idx = names(tmp), folders(tmp), index(tmp)
    parent = next(fid for fid, fo in f.items() if fo["kind"] == "trip")
    return (code == 0 and n[parent] == "20241025-1031_Northland_red leaves"
            and [n[d] for d in TRIP_DAYS] == ["1025_Ashford", "1026_Brookvale",
                                              "1027_Cedarton", "1029-1030_Dunmore",
                                              "1031_Elmwick"]
            and f[parent]["where"] == [{"ref": "agent:Northland"}]
            and idx["places"]["agent:Northland"]["kind"] == "agent"
            and f[parent]["what"] == {"text": "red leaves", "source": "agent"}), \
        f"code={code} err={err[-300:]!r} names={n}"


@case
def legs_nest_on_disk_under_their_parents_after_freeze_and_finish():
    """⭐ REPRODUCTION (R1). ⛔ FAILS on c6f0ea7 (nothing could make a leg).
    photo_execute has no leg code: nesting rests on the plan CSV's
    destination. After freeze and `finish --go`, every leg's files are on disk
    UNDER their parent, the day out and the buckets beside, nothing lost, and
    photo_plan's own name check (both callers of D-I13) says nothing."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp, min_visits=3)
        must(trip(wd), "make-trip")
        must(fsl_month(wd), "make-fsl-month")
        render(wd)
        must(run("check", wd), "check")
        out = must(run("freeze", wd), "freeze")
        plans = json.loads((wd / "plans.json").read_text())["plans"]
        env = {k: v for k, v in os.environ.items() if k != photo_profile.ENV_VAR}
        r = subprocess.run([sys.executable, str(RUN), "finish", str(wd), "--go",
                            "--skip-memory"], capture_output=True, text=True, env=env)
        tree = sorted(p.relative_to(Path(tmp) / "sorted").as_posix()
                      for p in (Path(tmp) / "sorted").rglob("*") if p.is_file())
    want = {"20241025-1031_Northland/1025_Ashford/IMG_2501.jpg",
            "20241025-1031_Northland/1029-1030_Dunmore/IMG_2901.jpg",
            "20241025-1031_Northland/1029-1030_Dunmore/IMG_3001.jpg",
            "20241025-1031_Northland/1031_Elmwick/IMG_3101.jpg",
            "20241200_Harbour/1211/IMG_1101.jpg",
            "20241200_Harbour/1226/IMG_2601b.jpg",
            "20241208_Townsville/IMG_0801.jpg"}
    legs = [p for p in plans if p.get("legs")]
    return (r.returncode == 0 and want <= set(tree) and len(tree) == 13
            and not any(t.startswith("20241025-1031_Northland/IMG") for t in tree)
            and len(plans) == 3 and len(legs) == 2
            and all("where" in leg for p in legs for leg in p["legs"])
            and "NAME CHECK" not in out), \
        f"rc={r.returncode} tree={tree} out={out[-300:]!r} err={r.stderr[-400:]!r}"


@case
def photo_plan_refuses_a_leg_that_drops_a_different_place():
    """REPRODUCTION (R6, the photo_plan caller). ⛔ FAILS with photo_plan.py
    at c6f0ea7: check_plan_names passed no place for a leg. With the words
    freeze writes, a leg dropping a place different from its parent's is
    refused; the parent's own place may be left out; a hand-written plan (no
    words) is as before."""
    batches = [{"batch": 1, "from": "2024-10-25", "to": "2024-10-26", "place": "x"}]
    plan = {"dest": {"path": "/r/20241025-1026_Northland"}, "where": ["Northland"],
            "legs": [{"name": "1025_lake walk", "where": ["Brookvale"]},
                     {"name": "1026", "where": ["Northland"]}]}
    refused, _w = photo_plan.check_plan_names(plan, batches)
    bare = {"dest": plan["dest"], "legs": [{"name": "1025_lake walk"}]}
    bare_refused, _w = photo_plan.check_plan_names(bare, batches)
    return (len(refused) == 1 and refused[0].startswith("1025_lake walk")
            and "D-I13" in refused[0] and not bare_refused), f"refused={refused}"


# ---------------------------------------------------------------------------
# R1 — overlapping legs, refused twice
# ---------------------------------------------------------------------------

@case
def overlapping_legs_route_every_shared_day_to_the_first_leg():
    """GUARD — why the refusal exists (measured, G5 case B). photo_plan's
    route() gives a day two leg ranges hold to the FIRST leg; the other gets
    nothing, and nothing says so. Passes before and after G5: photo_plan is
    unchanged, so the index must never write such legs."""
    row = {"SourceFile": "/x/a.jpg", "_day": "2024-11-02", "FileType": "JPEG",
           "Make": "Zenith", "Model": "Zenith", "ImageWidth": "-", "ImageHeight": "-"}
    plan = {"dest": {"path": "/r/P"}, "legs": [
        {"from": "2024-11-01", "to": "2024-11-02", "name": "1101-1102_A"},
        {"from": "2024-11-02", "to": "2024-11-02", "name": "1102_B"}]}
    _a, dest, _n, _t = photo_plan.route(row, plan, "/r", {}, photo_profile.messages({}))
    return dest == "/r/P/1101-1102_A", dest


@case
def check_refuses_overlapping_legs_and_so_does_a_group_command():
    """⭐ REPRODUCTION of case B (R1). ⛔ FAILS on c6f0ea7: nothing checked leg
    ranges. A leg whose days reach across a sibling's is a check PROBLEM; a
    `move` that would make one is refused, and nothing is written."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        must(trip(wd), "make-trip")
        before = index(tmp)
        code, _o, err = run("group", "move", wd, "F001", "--to", "F003",
                            "--dates", "2024-10-25", "--reason", "try")
        unchanged = index(tmp) == before
        render(wd)
        idx, _v, target = ix.index_of(tmp)
        f = ix.folders_of(idx)
        f["F003"]["days"] = ["2024-10-25", "2024-10-27"]
        f["F001"]["days"] = ["2024-10-25"]
        f["F001"]["batches"], f["F003"]["batches"] = [1], [1, 3]
        (target / "index.json").write_text(json.dumps(idx))
        ccode, cout, _e = run("check", wd)
    return (code != 0 and "overlap" in err and unchanged
            and ccode == 1 and "overlap" in cout), \
        f"code={code} err={err[-300:]!r} check={ccode} {cout[-400:]!r}"


# ---------------------------------------------------------------------------
# G10, the reason, the freeze, the invariants
# ---------------------------------------------------------------------------

@case
def a_bucket_file_is_never_moved_into_an_event_folder():
    """REPRODUCTION (G10). ⛔ FAILS on c6f0ea7 (no group command). A move out
    of the screenshot bucket or the no-date bucket, or a trip that names a
    bucket, is refused naming the route; a date move leaves the sidecar
    (skip_junk) and the screenshot where they are."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        render(wd)
        f = folders(tmp)
        shot = next(fid for fid, fo in f.items() if fo.get("bucket_key") == "screenshots")
        nodate = next(fid for fid, fo in f.items() if fo.get("bucket_key") == "to_be_checked")
        c1, _o, e1 = run("group", "move", wd, shot, "--to", "F007",
                         "--dates", "2024-12-11", "--reason", "r")
        c2, _o, e2 = run("group", "merge", wd, nodate, "--into", "F006", "--reason", "r")
        c3, _o, e3 = run("group", "make-trip", wd, "F006", shot, "--where", "X",
                         "--reason", "r")
        before = index(tmp)
        must(run("group", "move", wd, "F007", "--to", "F006", "--dates", "2024-12-11",
                 "--reason", "a day out"), "move")
        render(wd)
        after = index(tmp)
        by = ix.by_name(after)
    return (c1 and "screenshot" in e1 and "G10" in e1
            and c2 and "to_be_checked" in e2 and c3 and "G10" in e3
            and by[SHOT]["route"] == "screenshot" and by[SHOT]["folder"] == shot
            and by["._IMG_1102.jpg"]["route"] == "skip_junk"
            and by["._IMG_1102.jpg"]["folder"] is None
            and by["IMG_1101.jpg"]["folder"] == "F006"
            and not invariants(before, after)), \
        f"{e1[-200:]!r} {e2[-200:]!r} {e3[-200:]!r} shot={by[SHOT]}"


@case
def every_command_needs_a_reason_and_a_frozen_index_refuses_every_one():
    """GUARD. Without --reason (or with a blank one) a command is refused; on
    a freeze that holds, every command is refused and the index is unchanged."""
    commands = [["make-trip", "F001", "F002", "--where", "X"],
                ["make-fsl-month", "fsl-0001", "2024-12"],
                ["move", "F007", "--to", "F008", "--dates", "2024-12-11"],
                ["split", "F004", "--at", "2024-10-30"],
                ["merge", "F007", "--into", "F008"],
                ["set-what", "F006", "a walk"]]
    bad = []
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp, min_visits=2)
        for c in commands:
            if run("group", c[0], wd, *c[1:])[0] == 0:
                bad.append(("no reason", c[0]))
            if run("group", c[0], wd, *c[1:], "--reason", "  ")[0] == 0:
                bad.append(("blank reason", c[0]))
        render(wd)
        must(run("check", wd), "check")
        must(run("freeze", wd), "freeze")
        before = index(tmp)
        for c in commands:
            code, _o, err = run("group", c[0], wd, *c[1:], "--reason", "r")
            if code == 0 or "frozen" not in err:
                bad.append(("frozen", c[0], err[-120:]))
        after = index(tmp)
    return not bad and before == after, f"bad={bad}"


@case
def split_move_and_merge_keep_every_file_in_one_live_folder():
    """REPRODUCTION (R2). ⛔ FAILS on c6f0ea7 (no commands). By DATE only:
    `split --at` gives a new folder with `split_from`; a split with an empty
    side is refused; `merge` retires its source with `merged_into`; a `move`
    of a day into another top folder exports as an override and still lands
    every file (its place refs are relabel's to change, not a move's). File ids never change; every moved file has a history entry."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        before = index(tmp)
        cs, _o, es = run("group", "split", wd, "F004", "--at", "2024-10-30",
                         "--reason", "two days")
        ce, _o, ee = run("group", "split", wd, "F006", "--at", "2024-12-09",
                         "--reason", "nothing after")
        cm, _o, em = run("group", "merge", wd, "F008", "--into", "F007",
                         "--reason", "one outing")
        cv, _o, ev = run("group", "move", wd, "F009", "--to", "F006",
                         "--dates", "2024-12-26", "--reason", "with the day out")
        render(wd)
        must(run("check", wd), "check")
        out = must(run("freeze", wd), "freeze")
        plans = json.loads((wd / "plans.json").read_text())["plans"]
        idx = index(tmp)
    f = ix.folders_of(idx)
    new = next(fid for fid, fo in f.items() if fo.get("split_from") == "F004")
    by = ix.by_name(idx)
    moved = by["IMG_3001.jpg"]
    return (cs == 0 and ce != 0 and "both sides" in ee and cm == 0 and cv == 0
            and f[new]["rendered"] == "20241030_Dunmore" and f["F004"]["rendered"] == "20241029_Dunmore"
            and f["F008"]["status"] == "retired" and f["F008"]["merged_into"] == "F007"
            and f["F009"]["status"] == "retired" and f["F009"]["merged_into"] == "F006"
            and f["F007"]["rendered"] == "20241211-1222_Harbour"
            and f["F006"]["rendered"] == "20241208-1226_Townsville"
            and moved["folder"] == new
            and any(h.get("by") == "index group split" for h in moved["history"])
            and any(p.get("overrides") for p in plans)
            and not invariants(before, idx) and "frozen" in out), \
        (f"cs={cs} ce={ce} {ee[-150:]!r} cm={cm} {em[-150:]!r} cv={cv} {ev[-150:]!r} "
         f"names={[(k, v['rendered']) for k, v in f.items()]}")


@case
def a_split_freezes_with_no_false_name_check_failure():
    """⭐ REPRODUCTION (B3b, UAT02-01 P12/P28). ⛔ FAILS on 4739665: after a
    split the parent's name was checked against its BATCH's span, so a correct
    `20241029_Dunmore` printed NAME CHECK FAILED ("the period is
    20241029-1030") while the day it had given away went to the new folder."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        must(run("group", "split", wd, "F004", "--at", "2024-10-30",
                 "--reason", "two days"), "split")
        render(wd)
        code, out, err = run("freeze", wd)
    return code == 0 and "frozen" in out and "NAME CHECK" not in out + err, \
        f"code={code} out={out[-400:]!r} err={err[-200:]!r}"


@case
def a_split_piece_takes_the_places_of_its_own_days():
    """⭐ REPRODUCTION (B3a, UAT02-01 F028/F039/F040). ⛔ FAILS on 4739665: the
    new folder copied the batch's `Westvale+Farview`, so both days' pieces
    were named after both places. Each side now reads its own days the way
    relabel does (geocoder off, the cache only); the split says so."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        rows = [ix.row("IMG_0101.jpg", when="2024:11:01 10:00:00", gps=TRIP),
                ix.row("IMG_0102.jpg", when="2024:11:01 11:00:00", gps=TRIP),
                ix.row("IMG_0201.jpg", when="2024:11:02 10:00:00", gps=ix.FAR2),
                ix.row("IMG_0202.jpg", when="2024:11:02 11:00:00", gps=ix.FAR2)]
        wd = ix.make_dump(tmp, rows=rows, batches=[
            {"batch": 1, "from": "2024-11-01", "to": "2024-11-02",
             "place": "Westvale+Farview"}])
        ix.make_pack(tmp)
        ix.seed_cache(tmp, {TRIP: "Westvale", ix.FAR2: "Farview"})
        must(run("init", wd), "init")
        said = must(run("group", "split", wd, "F001", "--at", "2024-11-02",
                        "--reason", "two outings"), "split")
        render(wd)
        n, f = names(tmp), folders(tmp)
    new = next(fid for fid, fo in f.items() if fo.get("split_from") == "F001")
    return (n["F001"] == "20241101_Westvale" and n[new] == "20241102_Farview"
            and f[new]["where"] == [{"ref": "map:Farview"}]
            and "map:Farview" in said), f"names={n} said={said[-200:]!r}"


@case
def render_dry_run_says_a_split_moved_files_and_places():
    """REPRODUCTION (M3). ⛔ FAILS on 4739665 (no reason printed). A group
    command clears the names it touches, so the dry run names the command and
    what it changed — the split and each side's new place — since the last
    render."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        rows = [ix.row("IMG_0101.jpg", when="2024:11:01 10:00:00", gps=TRIP),
                ix.row("IMG_0201.jpg", when="2024:11:02 10:00:00", gps=ix.FAR2)]
        wd = ix.make_dump(tmp, rows=rows, batches=[
            {"batch": 1, "from": "2024-11-01", "to": "2024-11-02",
             "place": "Westvale+Farview"}])
        ix.make_pack(tmp)
        ix.seed_cache(tmp, {TRIP: "Westvale", ix.FAR2: "Farview"})
        must(run("init", wd), "init")
        render(wd)
        must(run("group", "split", wd, "F001", "--at", "2024-11-02",
                 "--reason", "two outings"), "split")
        out = must(run("render", wd, "--dry-run", "--no-vision"), "dry run")
    return (out.count("why: `group split` since the last render: F002 split from "
                      "F001 at 2024-11-02") == 2
            and "F001: map:Westvale + map:Farview → map:Westvale" in out), out


@case
def photo_plan_checks_every_folder_on_the_days_it_keeps():
    """⭐ REPRODUCTION (B3b). ⛔ FAILS on 4739665 (no `rows`; override folders
    never checked). With the rows it settled, a plan's folder is judged on the
    days it keeps and each override's folder on its own — a wrong period on a
    split piece is refused, the right one on the parent is not."""
    batches = [{"batch": 1, "from": "2024-10-29", "to": "2024-10-31", "place": "x"}]
    plan = {"dest": {"path": "/r/20241029_Dunmore"}, "overrides": [
        {"dates": ["2024-10-30"], "dest": "/r/20241030_Dunmore"},
        {"dates": ["2024-10-31"], "dest": "/r/20241030_Elmwick"}]}
    rows = [{"_action": "copy", "_dest": d, "_day": day} for d, day in
            [("/r/20241029_Dunmore", "2024-10-29"), ("/r/20241030_Dunmore", "2024-10-30"),
             ("/r/20241030_Elmwick", "2024-10-31")]]
    refused, _w = photo_plan.check_plan_names(plan, batches, rows=rows)
    old, _w = photo_plan.check_plan_names(plan, batches)
    return (len(refused) == 1 and refused[0].startswith("20241030_Elmwick")
            and "2024-10-31" in refused[0]
            and any(r.startswith("20241029_Dunmore") for r in old)), \
        f"refused={refused} without rows={old}"


@case
def freeze_stops_on_a_failed_name_only_for_a_folder_not_yet_on_the_drive():
    """GUARD (B3, owner ruling 20260918: stop on failure). The index's own `check`
    already refuses a name its render judged invalid; this is the backstop for
    photo_plan's check disagreeing. A new folder is listed; a merge target and
    a folder an earlier run copied into keep the report-only path (D10)."""
    with tempfile.TemporaryDirectory() as tmp:
        wd = Path(tmp)
        (wd / "plan").mkdir()
        index = {"files": [{"source": f"/s/{n}.jpg", "date": f"2024-10-{n}T10:00:00"}
                           for n in ("29", "30")]}
        by_number = {1: {"batch": 1, "from": "2024-10-29", "to": "2024-10-30"}}

        def plan(path, mode="new"):
            return [{"plan": 1, "batches": [1], "dest": {"mode": mode, "path": path}}]

        def rows(path):
            return {f"/s/{n}.jpg": ("copy", path, f"{n}.jpg") for n in ("29", "30")}

        bad = f"{tmp}/sorted/20241029_Dunmore"
        new = photo_index.new_folder_name_problems(wd, index, plan(bad), by_number,
                                                   rows(bad), {})
        merge = photo_index.new_folder_name_problems(wd, index, plan(bad, "merge"),
                                                     by_number, rows(bad), {})
        (wd / "plan" / "execute-state_P1.json").write_text(json.dumps(
            {"verified": {"/s/29.jpg": {"dest": f"{bad}/29.jpg"}}}))
        copied = photo_index.new_folder_name_problems(wd, index, plan(bad), by_number,
                                                      rows(bad), {})
    return (len(new) == 1 and new[0][0] == "20241029_Dunmore"
            and "20241029-1030" in new[0][1] and merge == [] and copied == []), \
        f"new={new} merge={merge} copied={copied}"


@case
def a_folder_copied_into_on_windows_is_on_the_drive_while_it_is_unreachable():
    """⭐ REPRODUCTION (RS4). On Windows photo_execute records `dest` as
    `str(Path(...))`, all backslashes, while the plan path is photo_plan's
    `f"{dest_root}/{name}"`: a native root, then "/". The two never matched,
    so with the drive unreachable a folder already copied into was judged
    new and a re-freeze STOPPED on its name. Both strings below are the
    Windows writers' shapes; the Mac's own Path does the rest, so this proves
    the comparison, not Windows' pathlib."""
    with tempfile.TemporaryDirectory() as tmp:
        wd = Path(tmp)
        (wd / "plan").mkdir()
        index = {"files": [{"source": f"/s/{n}.jpg", "date": f"2024-10-{n}T10:00:00"}
                           for n in ("29", "30")]}
        by_number = {1: {"batch": 1, "from": "2024-10-29", "to": "2024-10-30"}}
        root = "Z:\\_Photo_Manager"
        bad = f"{root}/20241029_Dunmore"
        plan = [{"plan": 1, "batches": [1], "dest": {"mode": "new", "path": bad}}]
        rows = {f"/s/{n}.jpg": ("copy", bad, f"{n}.jpg") for n in ("29", "30")}
        before = photo_index.new_folder_name_problems(wd, index, plan, by_number,
                                                      rows, {})
        (wd / "plan" / "execute-state_P1.json").write_text(json.dumps(
            {"verified": {"/s/29.jpg": {"dest": f"{root}\\20241029_Dunmore\\29.jpg"}}}))
        copied = photo_index.new_folder_name_problems(wd, index, plan, by_number,
                                                      rows, {})
    return len(before) == 1 and copied == [], f"before={before} copied={copied}"


# ---------------------------------------------------------------------------
# R3, R4, R5 — what the parents accept
# ---------------------------------------------------------------------------

@case
def fsl_month_takes_only_a_named_place_and_the_packs_minimum():
    """REPRODUCTION (R3, R4). ⛔ FAILS on c6f0ea7 (no command). A map word is
    refused; an id the pack does not hold is refused; fewer visits than the
    PACK's minimum is refused naming the key (the case sets 4, so it does not
    rest on the code default); a minimum below two still means two."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp, min_visits=4)
        c1, _o, e1 = run("group", "make-fsl-month", wd, "map:Harbour", "2024-12",
                         "--reason", "r")
        c2, _o, e2 = run("group", "make-fsl-month", wd, "fsl-0009", "2024-12",
                         "--reason", "r")
        c3, _o, e3 = fsl_month(wd)
        set_min_visits(pack, 1)
        floor = photo_index.fsl_month_min_visits(json.loads(
            (pack / photo_profile.PROFILE_NAME).read_text()))
    return (c1 and "R3" in e1 and c2 and "fsl-0009" in e2
            and c3 and "3 visit(s)" in e3 and photo_index.MIN_VISITS_KEY in e3
            and floor == 2), f"{e1[-150:]!r} {e2[-150:]!r} {e3[-200:]!r} floor={floor}"


@case
def a_trip_place_is_checked_like_a_name_part():
    """REPRODUCTION (R5). ⛔ FAILS on c6f0ea7 (no command). `--where` holding a
    grammar separator or a coordinate is refused; a trip of one folder is
    refused; nothing is written."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        before = index(tmp)
        codes = [run("group", "make-trip", wd, "F001", "F002", "--where", w,
                     "--reason", "r") for w in ("Hok_kaido", "Hok+kaido", "12.345, 67.891")]
        single = run("group", "make-trip", wd, "F001", "--where", "X", "--reason", "r")
        after = index(tmp)
    return (all(c[0] != 0 for c in codes) and "separator" in codes[0][2]
            and "coordinate" in codes[2][2] and single[0] != 0 and before == after), \
        [c[2][-120:] for c in codes]


# ---------------------------------------------------------------------------
# R7 — the [who] + animal [what] warning (on, by the owner's ruling)
# ---------------------------------------------------------------------------

@case
def check_warns_on_an_animal_what_beside_a_who_and_set_what_clears_it():
    """REPRODUCTION (R7). ⛔ FAILS on c6f0ea7: render recorded nothing about the
    frames behind a [what] and check never said a word. Lotus's folder takes
    `sofa nap` from a frame the see stage found Lotus in: check WARNS by
    default, the warning never blocks freeze, and after `set-what` (source
    agent) the warning is gone."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp)
        must(run("init", wd), "init")
        must(run("render", wd), "render")
        f1 = folders(tmp)["F001"]
        code, warned, _e = run("check", wd)
        fz, fout, ferr = run("freeze", wd)
        must(run("unfreeze", wd, "--reason", "rename the [what]"), "unfreeze")
        must(run("group", "set-what", wd, "F001", "an afternoon at home",
                 "--reason", "the pet is already named"), "set-what")
        must(run("render", wd), "render")
        _c, cleared, _e = run("check", wd)
        f1b = folders(tmp)["F001"]
    return (f1["validation"]["what_animal_files"] == 1 and code == 0
            and "`sofa nap` was picked from 1 frame(s)" in warned
            and "1 warning(s)" in warned and fz == 0 and "frozen" in fout
            and "was picked" not in cleared and "0 warning(s)" in cleared
            and f1b["rendered"] == "20241101_Ford_Lotus_an afternoon at home"
            and photo_index.what_animal_warning(f1b) is None), \
        f"f1={f1['validation']} warned={warned[-300:]!r} freeze={fz} {ferr[-200:]!r} cleared={cleared[-300:]!r}"


@case
def the_shipped_minimum_is_three_visits():
    """GUARD (R4, the owner's ruling). The ONE case that reads the code
    default: a pack that says nothing needs 3 visits; a pack may say 2."""
    return (photo_index.fsl_month_min_visits({}) == 3
            and photo_index.fsl_month_min_visits(
                {"cluster_defaults": {photo_index.MIN_VISITS_KEY: 2}}) == 2), \
        photo_index.fsl_month_min_visits({})


@case
def set_what_stores_the_agents_text_and_clear_goes_back_to_the_pick():
    """REPRODUCTION (R10). ⛔ FAILS on c6f0ea7 (no set-what; `what` was read
    as a string). The store is {text, source: agent}; render and the view read
    the text; --clear returns the pick."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp)
        must(run("init", wd), "init")
        must(run("group", "set-what", wd, "F002", "a walk", "--reason", "r"), "set")
        must(run("render", wd), "render")
        idx, view, _t = ix.index_of(tmp)
        first = ix.folders_of(idx)["F002"]
        must(run("group", "set-what", wd, "F002", "--clear", "--reason", "r"), "clear")
        must(run("render", wd), "render")
        second = folders(tmp)["F002"]
    return (first["what"] == {"text": "a walk", "source": "agent"}
            and first["rendered"] == "20241102_Harbour_a walk" and "a walk (agent)" in view
            and second["what"] is None
            and second["rendered"] == "20241102_Harbour_harbour walk"), \
        f"first={first['rendered']} second={second['rendered']}"


# ---------------------------------------------------------------------------
# R8, R9 — recut, relabel, and the no-plan net
# ---------------------------------------------------------------------------

@case
def recut_refuses_a_grouped_index_and_names_the_parent():
    """REPRODUCTION (R8). ⛔ FAILS on c6f0ea7: nothing refused, and a re-cut
    would retire the parent (no member files) while its legs still point at
    it. Nothing is written."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        must(trip(wd), "make-trip")
        before, b0 = index(tmp), (wd / "batches.json").read_bytes()
        code, _o, err = run("recut", wd, "--no-geocode")
        parent = next(fid for fid, fo in folders(tmp).items() if fo["kind"] == "trip")
        same = index(tmp) == before and (wd / "batches.json").read_bytes() == b0
    return (code != 0 and parent in err and "grouped" in err and same), \
        f"code={code} err={err[-300:]!r}"


@case
def relabel_moves_legs_and_never_a_parents_place_and_check_says_so():
    """REPRODUCTION (R8). ⛔ FAILS on c6f0ea7: relabel read day folders only
    and rebuilt `places` without a parent's refs. Legs are relabelled; the
    parent's `fsl-0001` and `agent:` refs stay; a leg of a monthly parent no
    longer at its place renders its own place (D-I13) and check warns."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp, min_visits=3)
        must(trip(wd), "make-trip")
        must(fsl_month(wd), "make-fsl-month")
        must(run("relabel", wd, "--go"), "relabel")
        idx, _v, target = ix.index_of(tmp)
        f = ix.folders_of(idx)
        month = next(fid for fid, fo in f.items() if fo["kind"] == "fsl-month")
        kept = (f[month]["where"] == [{"ref": "fsl-0001"}]
                and "fsl-0001" in idx["places"] and "agent:Northland" in idx["places"])
        f["F008"]["where"] = [{"ref": "map:Elsewhere"}]
        idx["places"]["map:Elsewhere"] = {"kind": "map", "text": "Elsewhere"}
        (target / "index.json").write_text(json.dumps(idx))
        render(wd)
        _c, out, _e = run("check", wd)
        n = names(tmp)
    return (kept and n["F008"] == "1222_Elsewhere" and n["F007"] == "1211"
            and "no longer at its place" in out), f"kept={kept} names={n} out={out[-300:]!r}"


@case
def a_batched_file_no_plan_settled_is_a_check_problem():
    """⭐ REPRODUCTION (R9). ⛔ FAILS on c6f0ea7: a file of a batch that no
    plan settled was only a WARNING, freeze passed, and the file was simply
    not copied (how a leg the export missed would fail). It is now a problem;
    a file in no batch still only warns."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        render(wd)
        clean = run("check", wd)
        idx, _v, target = ix.index_of(tmp)
        by = ix.by_name(idx)
        by["IMG_0801.jpg"].update(route=None, folder=None,
                                  route_source=photo_index.SETTLED + "no-plan")
        (target / "index.json").write_text(json.dumps(idx))
        code, out, _e = run("check", wd)
    return (clean[0] == 0 and code == 1 and "R9" in out and "IMG_0801.jpg" in out), \
        f"clean={clean[1][-200:]!r} code={code} out={out[-300:]!r}"


# ---------------------------------------------------------------------------
# dest, no index, no pack, and one case per pack route (LL-PHO-132)
# ---------------------------------------------------------------------------

@case
def dest_stays_day_only_and_top_level():
    """GUARD (R10). `dest` refuses a leg and a parent."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        must(trip(wd), "make-trip")
        parent = next(fid for fid, fo in folders(tmp).items() if fo["kind"] == "trip")
        leg = run("dest", wd, "F001", "fill_shell", str(tmp), "--reason", "r")
        top = run("dest", wd, parent, "fill_shell", str(tmp), "--reason", "r")
    return leg[0] != 0 and top[0] != 0, f"{leg[2][-120:]!r} {top[2][-120:]!r}"


@case
def with_no_index_group_refuses_and_with_no_pack_it_writes_nothing():
    """GUARD. A pack but no index: refused like render ("run init first"). No
    pack at all: one line, exit 0, nothing written."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = group_dump(tmp)
        no_index = run("group", "set-what", wd, "F001", "x", "--reason", "r")
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = group_dump(tmp, bind=False)
        before = sorted(p.name for p in wd.iterdir())
        no_pack = run("group", "set-what", wd, "F001", "x", "--reason", "r")
        after = sorted(p.name for p in wd.iterdir())
    return (no_index[0] != 0 and "init" in no_index[2]
            and no_pack[0] == 0 and "no owner pack" in no_pack[1] and before == after), \
        f"{no_index} {no_pack}"


def route_case(how):
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = group_dump(tmp, bind=how == "collection", min_visits=3)
        profile = pack / photo_profile.PROFILE_NAME
        extra = ["--profile", profile] if how == "profile" else []
        if how == "env":
            os.environ[photo_profile.ENV_VAR] = str(profile)
        must(run("init", wd, *extra), "init")
        code, _o, err = run("group", "make-fsl-month", wd, "fsl-0001", "2024-12",
                            "--reason", "r", *extra)
        kinds = [fo["kind"] for fo in folders(tmp).values()]
    return code == 0 and "fsl-month" in kinds, f"code={code} err={err[-300:]!r}"


@case
def route_collection_json_groups_with_the_pack():
    return route_case("collection")


@case
def route_env_var_groups_with_the_pack():
    return route_case("env")


@case
def route_explicit_profile_groups_with_the_pack():
    return route_case("profile")



@case
def a_group_dry_run_writes_nothing():
    """⭐ REPRODUCTION (UAT02-02 F-s). ⛔ FAILS on c5b6f99: `group` had no dry
    run — make-trip, split, move and set-what wrote the index at once. The
    dry run prints the same answer the write would and leaves the index as
    it was."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        path = ix.index_of(tmp)[2] / "index.json"
        before = path.read_bytes()
        code, out, err = trip(wd, "--dry-run")
        after = path.read_bytes()
        real = trip(wd)
    return (code == 0 and "DRY RUN" in out and before == after
            and real[0] == 0 and out.split("DRY RUN")[0].strip()
            in real[1]), f"code={code} out={out[-300:]!r} err={err[-300:]!r}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failures = []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
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
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} index_group cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
