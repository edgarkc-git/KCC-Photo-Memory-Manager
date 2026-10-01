#!/usr/bin/env python3
"""Unit cases for the residence-privacy rule in `photo_where.py` (OA-22).

The rule the engine has to keep is not "the pack key loads" — it is that a
home coordinate never reaches a name. So every case here runs the real script
over a synthetic dump whose geocode cache is pre-seeded with a name for EVERY
day, home days included. If suppression ever breaks, the home's name appears
in the output and the case fails; a run that quietly produced nothing would
otherwise pass every assertion while proving nothing, which is why each case
also asserts the positive control — a non-home day that IS named in the same
run.

  python3 tests/photo_where_cases.py [-v]

Exit 0 = pass. Offline: the cache seed means no Overpass or Nominatim call is
ever made, and none of the coordinates or names below belongs to anyone.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_cluster  # noqa: E402
import photo_where  # noqa: E402

# Invented coordinates, well outside the Taiwan bbox so the run takes the
# reverse-geocode path — the one whose cache key is reproducible offline.
HOME_A = (12.3456, 98.7654)
HOME_B = (12.5000, 98.9000)
AWAY = (13.1000, 99.5000)

# The names seeded for each. The two home names exist only so that a broken
# suppression is loud: nothing should ever be able to render them.
NAMES = {HOME_A: "Home-Leak-A", HOME_B: "Home-Leak-B", AWAY: "City-One"}

DAYS = [("2026-03-01", HOME_A), ("2026-03-02", HOME_B), ("2026-03-03", AWAY)]

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def geocode_key(point, language=None):
    """The key photo_where.py looks a zoom-13 name up under — built by the
    ENGINE'S OWN `Geocoder.key_for`, not pasted.

    ⛔ D-06 put the language in that key, and a pasted copy of the expression
    would still have matched the old shape: the seeded lookups would have
    turned into (failing, nameless) network calls and the suite would have
    reported it as a naming defect. Deriving it is what keeps a key change
    honest."""
    if not hasattr(photo_cluster.Geocoder, "key_for"):
        # the pre-D-06 engine built the key inline and carried no language.
        # Reproduced here ONLY so the suite still runs against that code and
        # can report which cases fail — never as a shape this suite accepts.
        return f"{round(point[0], 2):.5f},{round(point[1], 2):.5f},z13"
    return photo_cluster.Geocoder.key_for(
        _FakeCache(language), point, 13)


class _FakeCache:
    """The two attributes `key_for` reads, and nothing else."""
    def __init__(self, language=None):
        self.language = language or getattr(
            photo_cluster, "DEFAULT_GEOCODE_LANGUAGE", "en")


def run(tmp, profile, anchor=None, make="Apple"):
    """-> (returncode, parsed where.json or None, stdout, stderr).

    ⛔ `make` is a PARAMETER, and that is D-07 stated as a fixture defect.
    Every synthetic row here was an iPhone, so 16 green cases said nothing at
    all about the stage on any other camera — while the stage compared `Make`
    against the literal string "Apple" and silently named nothing for 58% of a
    Samsung owner's files, at exit 0.
    """
    root = Path(tmp)
    workdir = root / "202603"
    workdir.mkdir(parents=True)

    fields = ["SourceFile", "FileName", "FileType", "Make", "Model",
              "GPSPosition", "DateTimeOriginal"]
    rows = []
    for day, (lat, lon) in DAYS:
        for i in range(3):
            name = f"IMG_{day.replace('-', '')}{i}.HEIC"
            rows.append({"SourceFile": f"/raw/{name}", "FileName": name,
                         "FileType": "HEIC", "Make": make, "Model": "-",
                         "GPSPosition": f"{lat} {lon}",
                         "DateTimeOriginal": f"{day.replace('-', ':')} 1{i}:00:00"})
    with open(workdir / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    (workdir / "batches.json").write_text(json.dumps(
        {"batches": [{"batch": 1, "label": "b1", "from": DAYS[0][0],
                      "to": DAYS[-1][0]}]}))
    (root / "geocode-cache.json").write_text(json.dumps(
        {geocode_key(pt): {"name": NAMES[pt]} for pt in NAMES}))

    profile_file = root / "photo-profile.json"
    profile_file.write_text(json.dumps(profile))
    env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
    env["PHOTO_PROFILE"] = str(profile_file)

    cmd = [sys.executable, str(SCRIPTS / "photo_where.py"), str(workdir),
           "--batch", "1"]
    if anchor:
        cmd += ["--anchor", f"{anchor[0]},{anchor[1]}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        out = None
    return proc.returncode, out, proc.stdout, proc.stderr


def check(out, stdout, suppressed, named):
    """suppressed = days that must resolve to home with no name at all;
    named = days that must carry their seeded name (the positive control)."""
    problems = []
    if out is None:
        return ["no where.json on stdout"]
    days = out["days"]
    for day, point in DAYS:
        got = days.get(day)
        if got is None:
            problems.append(f"{day} produced no cluster at all")
            continue
        if day in suppressed:
            if got.get("mode") != "home" or got.get("names") != []:
                problems.append(f"{day} was not suppressed: {got}")
        elif day in named:
            if got.get("names") != [NAMES[point]]:
                problems.append(f"{day} lost its name: {got}")
    for day, point in DAYS:
        if day in suppressed and NAMES[point] in stdout:
            problems.append(f"{NAMES[point]} leaked into the output")
    want = [NAMES[p] for d, p in DAYS if d in named]
    if out.get("suggestion") != ("+".join(want) or None):
        problems.append(f"suggestion is {out.get('suggestion')!r}, want {want}")
    return problems


@case
def case_every_pack_home_is_a_never_name_zone():
    """The point of OA-22: several homes, read from the pack, no CLI flag —
    and the second one carries no label, which must not weaken it."""
    pack = {"home_locations": [
        {"label": "Place-One", "lat": HOME_A[0], "lon": HOME_A[1],
         "role": "primary"},
        {"lat": HOME_B[0], "lon": HOME_B[1]}]}
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err = run(tmp, pack)
    problems = check(out, stdout, {"2026-03-01", "2026-03-02"}, {"2026-03-03"})
    return (rc == 0 and not problems), f"rc={rc} {problems} {err[:200]}"


@case
def case_anchor_alone_still_suppresses():
    """A run with no home_locations at all — a benchmark, or a blank pack —
    keeps the only injection route it has."""
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err = run(tmp, {}, anchor=HOME_A)
    problems = check(out, stdout, {"2026-03-01"},
                     {"2026-03-02", "2026-03-03"})
    return (rc == 0 and not problems), f"rc={rc} {problems} {err[:200]}"


@case
def case_anchor_and_pack_are_a_union_not_an_override():
    """Both sources suppress. Neither switches the other off — an --anchor
    that replaced the pack would silently un-hide every other home."""
    pack = {"home_locations": [{"lat": HOME_B[0], "lon": HOME_B[1]}]}
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err = run(tmp, pack, anchor=HOME_A)
    problems = check(out, stdout, {"2026-03-01", "2026-03-02"}, {"2026-03-03"})
    return (rc == 0 and not problems), f"rc={rc} {problems} {err[:200]}"


@case
def case_no_homes_and_no_anchor_suppresses_nothing():
    """Absent and empty are the ordinary no-pack case, not a malformed one:
    every day is named and the run does not crash."""
    problems = []
    for pack in ({}, {"home_locations": []}):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, stdout, err = run(tmp, pack)
        if rc != 0:
            problems.append(f"rc={rc} for {pack}: {err[:200]}")
        problems += check(out, stdout, set(), {d for d, _ in DAYS})
    return not problems, str(problems)


@case
def case_a_malformed_home_row_fails_loudly():
    """A row the engine cannot read stops the run and names the key. Skipping
    it would disable the privacy rule with nothing on screen to say so."""
    broken = [
        [{"label": "Place-One", "lon": HOME_A[1]}],          # no lat
        [{"lat": "north", "lon": HOME_A[1]}],                # not a number
        [{"lat": HOME_A[0], "lon": None}],                   # null
        ["12.3456,98.7654"],                                 # not an entry
        {"lat": HOME_A[0], "lon": HOME_A[1]},                # not a list
    ]
    problems = []
    for entries in broken:
        with tempfile.TemporaryDirectory() as tmp:
            rc, _, _, err = run(tmp, {"home_locations": entries})
        if rc == 0:
            problems.append(f"accepted {entries!r}")
        elif "home_locations" not in err:
            problems.append(f"{entries!r} failed without naming the key: {err[:120]}")
    return not problems, str(problems)


@case
def case_a_home_only_suppresses_inside_its_window():
    """valid_from / valid_until are honoured, and never auto-computed. Both
    bounds are put on the excluding side in turn — a home that ENDED before
    this dump, then one that had not STARTED yet — because a window enforced
    on one edge only reads as working right up until the other edge matters."""
    packs = [
        [{"lat": HOME_A[0], "lon": HOME_A[1], "valid_until": "2026-02"},
         {"lat": HOME_B[0], "lon": HOME_B[1], "valid_from": "2026-01"}],
        [{"lat": HOME_A[0], "lon": HOME_A[1], "valid_from": "2026-04"},
         {"lat": HOME_B[0], "lon": HOME_B[1], "valid_until": "2026-12-31"}],
    ]
    problems = []
    for entries in packs:
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, stdout, err = run(tmp, {"home_locations": entries})
        if rc != 0:
            problems.append(f"rc={rc}: {err[:200]}")
        problems += check(out, stdout, {"2026-03-02"},
                          {"2026-03-01", "2026-03-03"})
    return not problems, str(problems)


@case
def case_an_unreadable_bound_still_suppresses():
    """A bound nobody can parse must fall through to open-ended. Both bounds
    here sort ABOVE the capture date as raw prefixes — an un-guarded
    comparison reads them as "this home had not started yet" and names it,
    which is the one direction this rule may never fail in."""
    pack = {"home_locations": [
        {"lat": HOME_A[0], "lon": HOME_A[1], "valid_from": "2026-3"},
        {"lat": HOME_B[0], "lon": HOME_B[1], "valid_from": "March 2026"}]}
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err = run(tmp, pack)
    problems = check(out, stdout, {"2026-03-01", "2026-03-02"}, {"2026-03-03"})
    return (rc == 0 and not problems), f"rc={rc} {problems} {err[:200]}"


@case
def case_bounds_compare_at_year_month_and_day_granularity():
    """The prefix comparison, exercised directly: all three shapes a pack may
    write, on both edges, plus the strict radius."""
    day = "2026-03-15"
    checks = [
        (("2026", None), True), (("2027", None), False),
        ((None, "2026"), True), ((None, "2025"), False),
        (("2026-03", None), True), (("2026-04", None), False),
        ((None, "2026-03"), True), ((None, "2026-02"), False),
        (("2026-03-15", None), True), (("2026-03-16", None), False),
        ((None, "2026-03-15"), True), ((None, "2026-03-14"), False),
        (("2026-01", "2026-12"), True), (("2025-01", "2025-12"), False),
    ]
    problems = []
    for (since, until), want in checks:
        homes = [(HOME_A[0], HOME_A[1], since, until)]
        got = photo_where.is_home(HOME_A, day, homes, 1.0)
        if got != want:
            problems.append(f"{since}..{until} -> {got}, want {want}")
    if photo_where.is_home(AWAY, day, [(HOME_A[0], HOME_A[1], None, None)], 1.0):
        problems.append("a point kilometres away read as home")
    for bad in ("2026-3", "26-03-15", "2026-03-15T09:00", "March 2026", "",
                2026, None, ["2026"], {"year": 2026}):
        if photo_where.home_bound(bad) is not None:
            problems.append(f"{bad!r} was accepted as a bound")
    return not problems, str(problems)


@case
def case_a_census_proposal_suppresses_once_it_is_written_as_a_pack_row():
    """OA-10 and OA-22 are one feature, and this is the only case that proves
    it: the coordinate the census PROPOSES, written into the pack the way
    photo-init says to, is the coordinate photo_where SUPPRESSES.

    The two ends do not share a shape — the census emits one `coord` pair and
    the pack stores `lat`/`lon` — so the split is the step a person performs
    and therefore the step that can silently stop happening. The case pins
    both halves: translated, it suppresses; copied whole, it stops the run
    rather than passing through unnamed.
    """
    import photo_census  # noqa: E402  — the proposer, exercised for real

    rows = []
    for d in range(1, 1 + photo_census.HOME_MIN_DAYS):
        for hour in (9, 21):  # every day carries an after-dark photo
            rows.append({"GPSPosition": f"{HOME_A[0]} {HOME_A[1]}",
                         "DateTimeOriginal": f"2026:03:{d:02d} {hour}:00:00"})
    proposals = photo_census.home_candidates(rows)
    if len(proposals) != 1:
        return False, f"census proposed {len(proposals)}, want 1"

    coord = proposals[0]["coord"]
    if "lat" in proposals[0] or "lon" in proposals[0]:
        return False, ("the census now emits lat/lon directly — drop the "
                       "hand-split from photo-init/SKILL.md and this case")

    written = {"label": "City-Word", "lat": coord[0], "lon": coord[1]}
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err = run(tmp, {"home_locations": [written]})
    problems = check(out, stdout, {"2026-03-01"}, {"2026-03-02", "2026-03-03"})
    if rc != 0:
        problems.append(f"translated row rejected: rc={rc} {err[:200]}")

    # and the untranslated proposal must be loud, never a quiet no-op
    with tempfile.TemporaryDirectory() as tmp:
        raw_rc, _, _, raw_err = run(tmp, {"home_locations": [proposals[0]]})
    if raw_rc == 0:
        problems.append("a raw census row was accepted — it suppresses nothing")
    elif "home_locations" not in raw_err:
        problems.append(f"raw row failed without naming the key: {raw_err[:120]}")
    return not problems, str(problems)


# ---------------------------------------------------------------- LL-PHO-97
# A day that MOVES used to leave the output entirely: the day's median landed
# mid-route, the 3 km filter called nearly every point an outlier, and the
# >=3 survivors gate then dropped the day with no name, no entry, no count and
# no warning. The cases below pin the two halves of the fix — the day appears,
# and splitting it into stops did not cost the privacy rule.

# A second away point, far enough from AWAY to segment. Invented, like the rest.
AWAY_2 = (13.9000, 100.4000)
NAMES[AWAY_2] = "City-Two"

# Invented coordinates INSIDE the Taiwan bbox, used only by the sparse-day
# case: a stop under MIN_NAME_POINTS returns before any Overpass call, so the
# case stays offline.
TW_SPARSE = (23.5000, 120.9000)


def run_layout(tmp, profile, layout, overpass=None, names=None):
    """Like `run`, but the caller lays out the days: [(day, [(point, hour)])].
    `overpass` seeds overpass-cache.json, so a Taiwan stop stays offline;
    `names` adds {point: name} to the seeded zoom-13 names.
    -> (returncode, parsed where.json or None, stdout, stderr, where_path)."""
    root = Path(tmp)
    workdir = root / "202603"
    workdir.mkdir(parents=True)
    fields = ["SourceFile", "FileName", "FileType", "Make", "Model",
              "GPSPosition", "DateTimeOriginal"]
    rows = []
    for day, points in layout:
        for i, ((lat, lon), hour) in enumerate(points):
            name = f"IMG_{day.replace('-', '')}{i}.HEIC"
            rows.append({"SourceFile": f"/raw/{name}", "FileName": name,
                         "FileType": "HEIC", "Make": "Apple", "Model": "-",
                         "GPSPosition": f"{lat} {lon}",
                         "DateTimeOriginal": f"{day.replace('-', ':')} {hour:02d}:00:00"})
    with open(workdir / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    days = [d for d, _ in layout]
    (workdir / "batches.json").write_text(json.dumps(
        {"batches": [{"batch": 1, "label": "b1", "from": min(days),
                      "to": max(days)}]}))
    seeded = {**NAMES, **(names or {})}
    (root / "geocode-cache.json").write_text(json.dumps(
        {geocode_key(pt): {"name": seeded[pt]} for pt in seeded}))
    if overpass:
        (root / "overpass-cache.json").write_text(json.dumps(overpass))

    profile_file = root / "photo-profile.json"
    profile_file.write_text(json.dumps(profile))
    env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
    env["PHOTO_PROFILE"] = str(profile_file)
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "photo_where.py"), str(workdir),
         "--batch", "1"], capture_output=True, text=True, env=env)
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        out = None
    return (proc.returncode, out, proc.stdout, proc.stderr,
            workdir / "classify" / "batch-01" / "where.json")


@case
def case_a_day_that_moves_still_appears():
    """LL-PHO-97, the whole point: a day whose points span two places must be
    in the output. It is also the regression that no single-cluster rewrite can
    pass by accident — the day's own median falls between the two stops."""
    pack = {"home_locations": []}
    layout = [("2026-03-10", [(AWAY, 9), (AWAY, 10), (AWAY, 11),
                              (AWAY_2, 16), (AWAY_2, 17), (AWAY_2, 18)])]
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err, _ = run_layout(tmp, pack, layout)
    if rc != 0 or out is None:
        return False, f"rc={rc} {err[:200]}"
    day = out["days"].get("2026-03-10")
    problems = []
    if day is None:
        problems.append("the moving day vanished — LL-PHO-97 is back")
    else:
        if day.get("mode") != "moving":
            problems.append(f"mode is {day.get('mode')!r}, want 'moving'")
        if len(day.get("stops") or []) != 2:
            problems.append(f"{len(day.get('stops') or [])} stops, want 2")
        if day.get("points") != 6:
            problems.append(f"points is {day.get('points')!r}, want 6")
        # Rule 4 / L09: in-transit shots follow the DESTINATION, so the day is
        # named for where it ended, never where it started.
        if day.get("names") != ["City-Two"]:
            problems.append(f"names is {day.get('names')!r}, want the last stop")
    return not problems, str(problems)


@case
def case_a_home_stop_on_a_moving_day_is_never_named():
    """Splitting a day into stops must not cost Operational Rule 3.

    The day-level median of a moving day is nowhere near home, so a per-DAY
    home check passes it straight through; only a per-STOP check suppresses
    the leg that started at the owner's door. The day also ENDS at home, so
    the destination rule has to reach past it to the last NON-home stop —
    otherwise the folder is named after a residence.
    """
    pack = {"home_locations": [{"lat": HOME_A[0], "lon": HOME_A[1]}]}
    layout = [("2026-03-11", [(HOME_A, 7), (HOME_A, 8), (HOME_A, 9),
                              (AWAY, 12), (AWAY, 13), (AWAY, 14),
                              (HOME_A, 19), (HOME_A, 20), (HOME_A, 21)])]
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err, _ = run_layout(tmp, pack, layout)
    if rc != 0 or out is None:
        return False, f"rc={rc} {err[:200]}"
    day = out["days"].get("2026-03-11") or {}
    problems = []
    if NAMES[HOME_A] in stdout:
        problems.append(f"{NAMES[HOME_A]} leaked into the output")
    if day.get("names") != [NAMES[AWAY]]:
        problems.append(f"names is {day.get('names')!r}, want the last non-home stop")
    home_stops = [s for s in day.get("stops") or [] if s.get("mode") == "home"]
    if len(home_stops) != 2:
        problems.append(f"{len(home_stops)} stops read as home, want 2")
    if any(s.get("names") for s in home_stops):
        problems.append("a home stop carried a name")
    return not problems, str(problems)


@case
def case_a_day_too_sparse_to_name_is_counted_not_dropped():
    """The same silence had a second cause, and the backlog missed it: a day
    with fewer than MIN_NAME_POINTS points was dropped by the same gate. It is
    now reported with its count and left unnamed — never guessed at from a
    single point (pitfall 2), and never simply absent.
    K20: the pack carries a home far from the day. With no home at all a
    one-day work dir now anchors on itself (`no_pack_anchor`), so the day
    would be a home stop and this case would no longer reach the gate."""
    pack = {"home_locations": [{"lat": HOME_A[0], "lon": HOME_A[1]}]}
    layout = [("2026-03-12", [(TW_SPARSE, 9)])]
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err, _ = run_layout(tmp, pack, layout)
    if rc != 0 or out is None:
        return False, f"rc={rc} {err[:200]}"
    day = out["days"].get("2026-03-12")
    if day is None:
        return False, "a one-photo day vanished instead of being counted"
    problems = []
    if day.get("mode") != "unnamed":
        problems.append(f"mode is {day.get('mode')!r}, want 'unnamed'")
    if day.get("points") != 1:
        problems.append(f"points is {day.get('points')!r}, want 1")
    if day.get("names"):
        problems.append(f"a single point was named: {day.get('names')!r}")
    return not problems, str(problems)


@case
def case_a_batch_with_no_gps_still_writes_where_json():
    """No file used to be written at all when nothing clustered, which reads
    downstream as "photo_where has not been run yet" rather than "it ran and
    found no location"."""
    pack = {"home_locations": []}
    root = None
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err, where_path = run_layout(
            tmp, pack, [("2026-03-13", [])])
        exists = where_path.exists()
        written = json.loads(where_path.read_text()) if exists else None
    if rc != 0:
        return False, f"rc={rc} {err[:200]}"
    if not exists:
        return False, "no where.json was written for a batch with no GPS"
    problems = []
    if written.get("days") != {}:
        problems.append(f"days is {written.get('days')!r}, want {{}}")
    if not written.get("note"):
        problems.append("the empty result says nothing about why it is empty")
    return not problems, str(problems)


@case
def case_a_name_that_needs_no_stripping_is_kept_whole():
    """R2-F2's buildable half. Returning None when nothing stripped made every
    name that is ALREADY a place unreachable at any rank — the owner's own
    folder name among them. Built from the module's own constants so the case
    names no real place and carries no owner fact."""
    suffix = photo_where.TRAIL_SUFFIXES[0]
    view = photo_where.VIEW_PREFIXES[0]
    joiner = photo_where.LEG_JOINERS[0]
    route = photo_where.ROUTE_DESCRIPTIONS[0]
    structure = photo_where.STRUCTURE_SUFFIXES[0]
    checks = [
        ("AA" + suffix, "AA", "a trail word must still be stripped"),
        ("BB", "BB", "a bare place name must survive whole"),
        (view + "CC", "CC", "a viewpoint prefix hides the place behind it"),
        (joiner + "DD", "DD", "a leading joiner hides the place behind it"),
        ("EE" + joiner + "FF", "EE", "'A to B' names the first place"),
        ("GG;HH", "GG", "a multi-name tag is two features, not one name"),
        ("II-JJ", "II", "a route variant is the same place"),
        ("KK" + route + "LL", None, "a route description is not a place"),
        ("MM" + structure, None, "a structure is not a place"),
        ("N", None, "a one-character name is not usable"),
    ]
    problems = []
    for raw, want, why in checks:
        got = photo_where.strip_trail_name(raw)
        if got != want:
            problems.append(f"{raw!r} -> {got!r}, want {want!r} ({why})")
    return not problems, str(problems)


@case
def case_one_feature_spelled_several_ways_is_proposed_once():
    """OSM carries one ridge as several ways whose names differ by a character
    or a trail word. Without folding them the engine proposes the same place
    three times and fills the whole name with it."""
    suffix = photo_where.TRAIL_SUFFIXES[0]
    feats = [{"name": "AA" + suffix, "kind": "trail", "near": 9, "min_d": 10,
              "first_touch": "1"},
             {"name": "AA", "kind": "trail", "near": 8, "min_d": 20,
              "first_touch": "2"},
             {"name": "BB", "kind": "trail", "near": 7, "min_d": 30,
              "first_touch": "3"}]
    got = photo_where.select_names(feats)
    if got != ["AA", "BB"]:
        return False, f"select_names -> {got}, want ['AA', 'BB']"
    return True, ""


@case
def case_a_fine_grained_area_name_is_refused_locally_but_kept_abroad():
    """The zoom-13 fallback must not answer a moving day with a neighbourhood:
    it is useless as a folder and finer than anything the engine should
    volunteer. But the very same suffixes are ordinary municipality names in
    other countries, so refusing them everywhere would DROP a real city name —
    the silence this whole change set exists to remove, pointed the other way.
    """
    class FakeGeocoder(_FakeCache):
        def __init__(self, name):
            super().__init__()
            self.cache = {geocode_key(AWAY): {"name": name}}
            self.dirty = False

        key_for = getattr(photo_cluster.Geocoder, "key_for", None)

    problems = []
    for suffix in photo_where.AREA_TOO_FINE:
        name = "XX" + suffix
        local = photo_where.area_name(AWAY, FakeGeocoder(name), reject_fine=True)
        abroad = photo_where.area_name(AWAY, FakeGeocoder(name))
        if local is not None:
            problems.append(f"{name!r} was accepted as a local fallback name")
        if abroad != name:
            problems.append(f"{name!r} was dropped abroad, got {abroad!r}")
    kept = "YY" + photo_where.TRAIL_SUFFIXES[0]
    if photo_where.area_name(AWAY, FakeGeocoder(kept), reject_fine=True) != kept:
        problems.append("an ordinary district name was refused locally")
    return not problems, str(problems)


@case
def case_a_non_apple_owner_gets_names_too():
    """⭐ THE R7 REPRODUCTION (D-07, CRITICAL).

    `photo_where.py` compared `Make` against the literal string "Apple" and
    never read the pack's `own_camera_makes`. On a Samsung dump that filtered
    every row out before a single coordinate was looked at: 0 of 13 batches
    nameable, exit 0, nothing on stderr, 576 files (58%) with no place name.
    The 16 cases green at the time were green because every row was an iPhone.

    Same fixture, same pack shape, one field changed."""
    pack = {"home_locations": [{"lat": HOME_A[0], "lon": HOME_A[1]},
                               {"lat": HOME_B[0], "lon": HOME_B[1]}],
            "own_camera_makes": ["samsung"]}
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err = run(tmp, pack, make="samsung")
    problems = check(out, stdout, {"2026-03-01", "2026-03-02"}, {"2026-03-03"})
    if out is not None and out.get("filtered_out"):
        problems.append("the owner's own camera was called somebody else's")
    return (rc == 0 and not problems), f"rc={rc} {problems} {err[:200]}"


@case
def case_a_camera_missing_from_the_pack_says_so():
    """The other half of R7, and the reason D-07 survived a whole UAT run: a
    batch whose every file is filtered out is INDISTINGUISHABLE from a batch
    with no GPS — both produce no name, at exit 0. An owner cannot fix a pack
    nobody tells them is wrong."""
    pack = {"home_locations": [{"lat": HOME_A[0], "lon": HOME_A[1]}],
            "own_camera_makes": ["Apple"]}
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err = run(tmp, pack, make="samsung")
    if out is None:
        return False, "no where.json on stdout"
    told = out.get("filtered_out")
    problems = []
    if not told:
        problems.append("every file was dropped and the output said nothing")
    else:
        if told.get("cameras_found") != ["samsung"]:
            problems.append(f"cameras_found={told.get('cameras_found')}")
        if told.get("own_camera_makes") != ["apple"]:
            problems.append(f"own_camera_makes={told.get('own_camera_makes')}")
        if not told.get("files_in_window"):
            problems.append("files_in_window is 0 — nothing was filtered")
    if out.get("days"):
        problems.append("a fully filtered batch also reported named days")
    return (rc == 0 and not problems), f"rc={rc} {problems} {err[:200]}"


@case
def case_a_street_address_is_never_a_place_name():
    """⭐ THE R8 REPRODUCTION (A43). A residential lane carries a name in OSM
    and sits exactly on the track, so density ranks it FIRST — measured, a
    lane 288 m from an owner's front door was proposed as a folder name. Of
    four near-home batches in UAT01 the two that were nameable at all BOTH
    named a street.

    ⛔ A privacy guard before it is a naming one: a lane number is the
    residence written down at higher precision than the coordinates the pack
    refuses to publish."""
    problems = []
    # i18n-guard:allow-begin — locale detection data under test
    for addr in ("青禾三街7巷", "文化路100號", "5弄"):
        if not photo_where.is_address(addr):
            problems.append(f"{addr} was not read as an address")
        if not photo_where.names_no_place(addr):
            problems.append(f"{addr} would still survive select_names()")
    # The positive control, and the whole reason the road word itself is NOT
    # on the list: an old street is a place people travel TO.
    for keep in ("鹿港老街", "七星山", "小樽市", "南庄鄉"):
        if photo_where.is_address(keep) or photo_where.names_no_place(keep):
            problems.append(f"{keep} — a real destination — was refused")
    # i18n-guard:allow-end
    return not problems, str(problems)


@case
def case_a_stop_wider_than_the_home_radius_is_still_home():
    """R8's structural half, and it is what let the lane above be named at all.

    `is_home()` tested ONE point — the stop's centre — while a stop may span
    `STOP_SPLIT_KM` (3.0 km) and the home radius defaults to 1.0 km. A stop
    whose photographs start at the owner's front door therefore has a centre
    well outside the radius, and the nearest point was never consulted."""
    homes = [(HOME_A[0], HOME_A[1], None, None)]
    day = "2026-03-01"
    pts = [(HOME_A[0], HOME_A[1], None), (HOME_A[0] + 0.018, HOME_A[1], None)]
    problems = []
    center = photo_where.stop_center(pts)
    if photo_where.is_home(center, day, homes, 1.0):
        problems.append("fixture is wrong: the centre must be OUTSIDE the "
                        "radius or this case proves nothing")
    if photo_where.is_home_stop(pts, day, homes, 1.0) != "point":
        problems.append("a stop holding a photograph taken at home was not "
                        "treated as home")
    far = [(AWAY[0], AWAY[1], None), (AWAY[0] + 0.01, AWAY[1], None)]
    if photo_where.is_home_stop(far, day, homes, 1.0) is not None:
        problems.append("a stop nowhere near home was suppressed — the guard "
                        "swallows every name")
    return not problems, str(problems)


# ---------------------------------------------------------------------------
# D-06, fifth site — the Overpass path that names HIKES
#
# The Overpass REQUEST is neutral: plain `tags.name`, no accept-language. Its
# NAME SELECTION was not. A ';'-joined OSM tag was resolved by
# `pick_traditional()`, hardwired to Traditional Chinese, for every owner in
# every language — the same judgement the Nominatim sites make, one function
# along. It reads as harmless because it is a no-op on a name with no ';',
# and this is the path whose answer reaches a folder name.
# ---------------------------------------------------------------------------

def ranked(elements, pts, language):
    """`rank_features`, tolerating the pre-D-06 signature that took no
    language — so the unfixed engine reports a FAIL line rather than a
    TypeError that hides every case after it."""
    try:
        return photo_where.rank_features(elements, pts, language)
    except TypeError:
        return photo_where.rank_features(elements, pts)


@case
def a_joined_overpass_name_is_resolved_in_the_owners_language():
    """⛔ The REPRODUCTION for the fifth site. A peak tagged with two script
    variants used to resolve to the Traditional one whatever the pack said."""
    # i18n-guard:allow-begin — locale detection data, not user-facing output:
    # the case turns on the SCRIPT of the value, so an ASCII placeholder
    # cannot exercise it. The two differ by a character in
    # photo_cluster.SIMPLIFIED_CHARS, which is what the choice is made on.
    # ⚠️ These two, specifically: `simp` is IN photo_cluster.SIMPLIFIED_CHARS
    # and `trad` is not, which is the only property the chooser reads. A pair
    # the detector does not know would pass by falling through to "first
    # variant" and prove nothing — measured, on the first draft of this case.
    trad, simp = "國", "国"
    # i18n-guard:allow-end
    node = {"type": "node", "lat": AWAY[0], "lon": AWAY[1],
            "tags": {"name": f"{simp};{trad}", "natural": "peak"}}
    pts = [(AWAY[0], AWAY[1], datetime(2026, 3, 1, 10, 0))]
    picked = {}
    for language in (None, "en", "zh-TW", "zh-CN"):
        feats = ranked([node], pts, language)
        picked[language] = feats[0]["name"] if feats else None
    problems = []
    if picked["zh-TW"] != trad:
        problems.append(f"a Traditional pack got {picked['zh-TW']!r}")
    # ⛔ every non-Traditional pack takes the tag's FIRST variant — the engine
    # has nothing else to choose on, and choosing by script would be choosing
    # a language nobody asked for
    for language in (None, "en", "zh-CN"):
        if picked[language] != simp:
            problems.append(f"{language} got {picked[language]!r}, "
                            "the Traditional filter ran")
    return not problems, f"{problems} :: {picked}"


@case
def a_plain_overpass_name_is_untouched_in_every_language():
    """A guard: the fifth site is a variant CHOOSER, not a translator. A name
    with no ';' is the ordinary case and no language may alter it."""
    node = {"type": "node", "lat": AWAY[0], "lon": AWAY[1],
            "tags": {"name": "Lone Peak", "natural": "peak"}}
    pts = [(AWAY[0], AWAY[1], datetime(2026, 3, 1, 10, 0))]
    got = {lang: ranked([node], pts, lang)[0]["name"]
           for lang in (None, "en", "ja", "zh-TW", "zh-CN")}
    return set(got.values()) == {"Lone Peak"}, str(got)


# ---------------------------------------------------------------------------
# W2B-3 / ADR 0001 — a place the owner named names its stop.
#
# ⭐ REPRODUCTION. The classify SKILL writes `[where]` from this script's
# candidates, and it read no `frequent_places`: in UAT01-4 three folders took
# an OSM access note as their place word where the owner's name for the place
# would have stood. Invented points and words, as everywhere in this file.

OWNER_PLACE = "Owner-Place"


def with_named_places(tmp, *rows):
    """Make the fixture profile's folder a PACK (the owner anchor) holding
    `frequent_places` — the only shape `named_places()` reads."""
    root = Path(tmp)
    root.mkdir(parents=True, exist_ok=True)
    (root / "photo-owner-fixture.md").write_text("fixture\n")
    (root / "photo-entities.json").write_text(json.dumps(
        {"frequent_places": [{"label": w, "lat": p[0], "lon": p[1]}
                             for w, p in rows]}))


@case
def case_a_named_place_names_its_stop():
    """⭐ REPRODUCTION: the seeded map name loses to the owner's word."""
    with tempfile.TemporaryDirectory() as tmp:
        with_named_places(tmp, (OWNER_PLACE, AWAY))
        rc, out, stdout, err = run(tmp, {"home_locations": [
            {"lat": HOME_A[0], "lon": HOME_A[1]},
            {"lat": HOME_B[0], "lon": HOME_B[1]}]})
        if rc != 0 or out is None:
            return False, f"exit {rc}: {err[-200:]}"
        got = out["days"]["2026-03-03"]
        problems = []
        if got.get("names") != [OWNER_PLACE] or got.get("mode") != "named":
            problems.append(f"the owner's word did not name the stop: {got}")
        if out.get("suggestion") != OWNER_PLACE:
            problems.append(f"suggestion is {out.get('suggestion')!r}")
        return not problems, problems


@case
def case_a_named_place_never_names_a_home_stop():
    """Guard: the home test runs first and is untouched. A named place sitting
    on a residence does not reach it, and the positive control still names."""
    with tempfile.TemporaryDirectory() as tmp:
        with_named_places(tmp, (OWNER_PLACE, HOME_A))
        rc, out, stdout, err = run(tmp, {"home_locations": [
            {"lat": HOME_A[0], "lon": HOME_A[1]},
            {"lat": HOME_B[0], "lon": HOME_B[1]}]})
        if rc != 0 or out is None:
            return False, f"exit {rc}: {err[-200:]}"
        problems = check(out, stdout, suppressed={"2026-03-01", "2026-03-02"},
                         named={"2026-03-03"})
        if OWNER_PLACE in stdout:
            problems.append("a named place's word reached a home stop")
        return not problems, problems


@case
def case_beyond_its_radius_a_named_place_leaves_the_map_to_name_it():
    """Guard: 1.5 km off is somewhere else at the shipped 1 km — and the
    radius is the pack's, so a pack's 2 km takes it."""
    near = (AWAY[0] + 0.0135, AWAY[1])
    homes = {"home_locations": [{"lat": HOME_A[0], "lon": HOME_A[1]},
                                {"lat": HOME_B[0], "lon": HOME_B[1]}]}
    with tempfile.TemporaryDirectory() as tmp:
        with_named_places(tmp, (OWNER_PLACE, near))
        rc, out, stdout, err = run(tmp, homes)
        if rc != 0 or out is None:
            return False, f"exit {rc}: {err[-200:]}"
        if out["days"]["2026-03-03"].get("names") != [NAMES[AWAY]]:
            return False, f"1.5 km took the name: {out['days']['2026-03-03']}"
    with tempfile.TemporaryDirectory() as tmp:
        with_named_places(tmp, (OWNER_PLACE, near))
        rc, out, stdout, err = run(tmp, {**homes, "cluster_defaults":
                                         {"named_place_km": 2}})
        if rc != 0 or out is None:
            return False, f"exit {rc}: {err[-200:]}"
        if out["days"]["2026-03-03"].get("names") != [OWNER_PLACE]:
            return False, f"the pack's 2 km was not read: {out['days']['2026-03-03']}"
    return True, ""


# ---------------------------------------------------------------------------
# K20 — a packless run has a home: photo_cluster.no_pack_anchor
# ---------------------------------------------------------------------------

TW_HOME_POINT = (23.6000, 120.6000)   # invented, inside the Taiwan box


def stop_bbox_key(point):
    """The Overpass cache key photo_where builds for a stop of identical
    points at `point` — the engine's own arithmetic, so a seeded leak name
    is found offline exactly where a real query would have put it."""
    import math
    lat_m = 0.0045
    lon_m = 0.0045 / max(math.cos(math.radians(point[0])), 0.2)
    bbox = (point[0] - lat_m, point[1] - lon_m, point[0] + lat_m, point[1] + lon_m)
    return ",".join(f"{v:.4f}" for v in bbox)


def no_pack_layout(home):
    """Five days at `home`, then one day at AWAY: the home cell is modal."""
    days = [(f"2026-04-0{i}", [(home, 9), (home, 10), (home, 11)]) for i in range(1, 6)]
    return days + [("2026-04-06", [(AWAY, 9), (AWAY, 10), (AWAY, 11)])]


def no_pack_problems(out, stdout, leak):
    if out is None:
        return ["no where.json on stdout"]
    problems = []
    for d in (f"2026-04-0{i}" for i in range(1, 6)):
        got = out["days"].get(d) or {}
        if got.get("mode") != "home" or got.get("names") != []:
            problems.append(f"{d} not suppressed: {got.get('mode')} {got.get('names')}")
    if leak in stdout:
        problems.append(f"{leak} leaked into the output")
    if (out["days"].get("2026-04-06") or {}).get("names") != ["City-One"]:
        problems.append("the away day lost its name (positive control)")
    return problems


@case
def k20_a_packless_home_day_is_never_named_abroad():
    """⭐ REPRODUCTION (K20, Rule 3). ⛔ FAILS on 8ec97b5: with no home in the
    pack and no --anchor, photo_where had no home at all, so every home day
    outside Taiwan was named after the place around it (measured on a made-up
    US owner: "Green Lake", the park beside the home). It now takes
    photo_cluster's own no-pack anchor over the whole work dir."""
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err, _ = run_layout(tmp, {}, no_pack_layout(HOME_A))
    problems = no_pack_problems(out, stdout, NAMES[HOME_A])
    return (rc == 0 and not problems), f"rc={rc} {problems} {err[-200:]}"


@case
def k20_a_packless_home_day_is_never_named_in_taiwan():
    """⭐ REPRODUCTION (K20, Rule 3): the same in Taiwan, where a home stop
    went to the Overpass query. ⛔ FAILS on 8ec97b5. Offline: the stop's
    Overpass box is seeded with a peak named for the leak."""
    leak = "Homeleakpeak"
    seed = {stop_bbox_key(TW_HOME_POINT): [
        {"type": "node", "id": 1, "lat": TW_HOME_POINT[0], "lon": TW_HOME_POINT[1],
         "tags": {"natural": "peak", "name": leak}}]}
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err, _ = run_layout(tmp, {}, no_pack_layout(TW_HOME_POINT),
                                             overpass=seed)
    problems = no_pack_problems(out, stdout, leak)
    return (rc == 0 and not problems), f"rc={rc} {problems} {err[-200:]}"


@case
def k20_with_a_pack_home_the_no_pack_anchor_is_never_asked():
    """GUARD (K20, R2-F3). The pack's homes always win: with one, photo_where
    never calls no_pack_anchor (here it would raise)."""
    import io
    import contextlib
    if not hasattr(photo_where, "no_pack_anchor"):
        return False, "photo_where has no no_pack_anchor (the code before K20)"
    pack = {"home_locations": [{"lat": HOME_A[0], "lon": HOME_A[1]}]}
    called = []
    with tempfile.TemporaryDirectory() as tmp:
        rc, _out, _so, err, where = run_layout(tmp, pack, no_pack_layout(HOME_A))
        workdir = where.parents[2]
        saved = (photo_where.no_pack_anchor, sys.argv[:],
                 os.environ.get("PHOTO_PROFILE"))

        def refuse(*a):
            called.append(a)
            raise AssertionError("no_pack_anchor asked with a pack home")

        photo_where.no_pack_anchor = refuse
        sys.argv = ["photo_where.py", str(workdir), "--batch", "1"]
        os.environ["PHOTO_PROFILE"] = str(Path(tmp) / "photo-profile.json")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                photo_where.main()
            ok = True
        except AssertionError:
            ok = False
        finally:
            photo_where.no_pack_anchor, sys.argv = saved[0], saved[1]
            if saved[2] is None:
                os.environ.pop("PHOTO_PROFILE", None)
            else:
                os.environ["PHOTO_PROFILE"] = saved[2]
    return (rc == 0 and ok and not called), f"rc={rc} called={len(called)} {err[-200:]}"


@case
def k20_a_packless_trip_only_folder_is_its_own_home_by_choice():
    """⚠️ THE CHOSEN COST of the two cases above (Lead D1, 20261001), pinned so
    a later reader sees it was chosen, not missed. A packless work dir holding
    ONLY a trip anchors on the trip itself (R2-F3's shape), so its stops are
    home stops and nothing there is named. Privacy-safe, benchmark-only: a
    real owner always has a pack, and photo_cluster already types such a
    folder this way. Measured on a US trip: the 3 city days lost "Spokane"."""
    layout = [(f"2026-04-1{i}", [(AWAY, 9), (AWAY, 10), (AWAY, 11)]) for i in range(1, 4)]
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, stdout, err, _ = run_layout(tmp, {}, layout)
    if rc != 0 or out is None:
        return False, f"rc={rc} {err[-200:]}"
    days = [out["days"].get(f"2026-04-1{i}") or {} for i in range(1, 4)]
    return (all(d.get("mode") == "home" and d.get("names") == [] for d in days)
            and NAMES[AWAY] not in stdout), f"{days}"


@case
def k20_an_owner_with_no_day_test_asks_no_overpass():
    """GUARD (K20, owner ruling 20261001: "country only, no day test yet"). Overpass
    runs only inside the owner's own country, and only a country with a day
    test has an inside. ⛔ FAILS on 2559783 for the US owner: the Taiwan box
    sent ANY owner's stop there to the peak query. A declared-US owner on a
    stop inside the TW row gets the town name and no peak; a Taiwan owner on
    the same stop still gets the peak (the positive control)."""
    peak = "Birkhorn"
    seed = {stop_bbox_key(TW_HOME_POINT): [
        {"type": "node", "id": 2, "lat": TW_HOME_POINT[0], "lon": TW_HOME_POINT[1],
         "tags": {"natural": "peak", "name": peak}}]}
    layout = [("2026-04-20", [(TW_HOME_POINT, 9), (TW_HOME_POINT, 10),
                              (TW_HOME_POINT, 11)])]
    far = [{"lat": HOME_A[0], "lon": HOME_A[1]}]
    got = {}
    for owner, pack in (("US", {"country": "US", "home_locations": far}),
                        ("TW", {"country": "TW", "home_locations": far})):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, stdout, err, _ = run_layout(
                tmp, pack, layout, overpass=seed, names={TW_HOME_POINT: "Town-TW"})
        day = (out or {}).get("days", {}).get("2026-04-20") or {}
        got[owner] = (rc, day.get("mode"), day.get("names"))
    return (got["US"] == (0, "area_z13", ["Town-TW"])
            and got["TW"][:2] == (0, "overpass") and peak in (got["TW"][2] or [])), \
        f"{got}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    failures = []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
        ok, detail = fn()
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  "
                  f"{fn.__name__.replace('_', ' ').ljust(width)}"
                  + (f"   {detail}" if not ok else ""))

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} where-privacy cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
