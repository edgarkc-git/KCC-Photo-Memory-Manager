#!/usr/bin/env python3
"""Unit cases for the onboarding checkpoint — the device/screen census and the
mid-run screen-size trigger.

The golden harness cannot reach any of this: it replays the PLAN stage over
four frozen dumps, none of which carries a screenshot the census can name, and
none of whose packs sets `screen_dims` at all. So every assertion here is one
the replay is structurally blind to.

  python3 tests/onb_cases.py [-v]

Exit 0 = pass. Rows are written out here; nothing on a drive is read.
"""

import argparse
import contextlib
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_census  # noqa: E402
import photo_plan  # noqa: E402
import photo_profile  # noqa: E402
import photo_run  # noqa: E402
import photo_sample  # noqa: E402

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def row(name, ftype, w, h, make="-", model="-"):
    return {"FileName": name, "SourceFile": f"/raw/{name}", "FileType": ftype,
            "ImageWidth": str(w), "ImageHeight": str(h),
            "Make": make, "Model": model}


# ---------------------------------------------------------------------------
# G-5 — an owner with fewer than MIN_SCREEN_HITS screenshots gets no proposal.
# That is correct, and it used to be silent.
# ---------------------------------------------------------------------------

ONE_SHOT = [
    row("IMG_0001.JPG", "JPEG", 4032, 3024, make="Apple", model="iPhone 12"),
    row("IMG_0002.JPG", "JPEG", 4032, 3024, make="Apple", model="iPhone 12"),
    row("IMG_0003.PNG", "PNG", 1170, 2532),
]


@case
def a_single_screenshot_is_counted_as_below_threshold():
    c = photo_census.census(ONE_SHOT)
    return (c["screen_size_candidates"] == []
            and c["screen_sizes_below_threshold"] == 1), \
        f"candidates={c['screen_size_candidates']} below={c['screen_sizes_below_threshold']}"


@case
def below_threshold_silence_is_explained_in_the_report():
    text = photo_census.render(photo_census.census(ONE_SHOT), "x", {}, None)
    # Card 9: typing a size in by hand is no longer a route (a pasted size
    # the census never offered is refused), so the line must not offer it.
    return ("type the size in by hand" not in text
            and "none named like a screenshot" in text
            and f"fewer than {photo_census.MIN_SCREEN_HITS}" in text), text[-400:]


@case
def a_collection_with_no_no_camera_still_claims_nothing():
    rows = [r for r in ONE_SHOT if r["Make"] != "-"]
    c = photo_census.census(rows)
    text = photo_census.render(c, "x", {}, None)
    return (c["screen_sizes_below_threshold"] == 0
            and "type the size in by hand" not in text), text[-300:]


@case
def two_files_at_one_size_still_clear_the_threshold():
    rows = ONE_SHOT + [row("IMG_0004.PNG", "PNG", 1170, 2532)]
    c = photo_census.census(rows)
    return (c["screen_sizes_below_threshold"] == 0
            and [s["dims"] for s in c["screen_size_candidates"]]
            == [["1170", "2532"]]), str(c["screen_size_candidates"])


# ---------------------------------------------------------------------------
# G-1 — a screen size is paired with the device it belongs to. The reader has
# to keep accepting the shape every pack written before today uses.
# ---------------------------------------------------------------------------

FLAT = {"screen_dims": [[1080, 2280]]}
PAIRED = {"screen_dims": [{"model": "samsung SM-N9750", "dims": [1080, 2280]}]}
MIXED = {"screen_dims": [[1080, 2280],
                         {"model": "Apple iPhone 12", "dims": [1170, 2532]}]}


@case
def an_unmigrated_flat_pack_still_matches_its_size():
    return (photo_sample.screen_dims(FLAT)
            == {("1080", "2280"), ("2280", "1080")}), \
        str(photo_sample.screen_dims(FLAT))


@case
def the_paired_shape_matches_exactly_what_the_flat_one_did():
    return (photo_sample.screen_dims(PAIRED)
            == photo_sample.screen_dims(FLAT)), "shapes disagree"


@case
def the_two_shapes_may_be_mixed_in_one_pack():
    return (photo_sample.screen_dims(MIXED)
            == {("1080", "2280"), ("2280", "1080"),
                ("1170", "2532"), ("2532", "1170")}), \
        str(photo_sample.screen_dims(MIXED))


@case
def the_device_survives_the_read():
    return (photo_sample.screen_devices(PAIRED)
            == [("samsung SM-N9750", ("1080", "2280"))]), \
        str(photo_sample.screen_devices(PAIRED))


@case
def a_flat_entry_reads_back_with_no_device():
    return photo_sample.screen_devices(FLAT) == [(None, ("1080", "2280"))], \
        str(photo_sample.screen_devices(FLAT))


@case
def an_empty_list_still_turns_size_detection_off():
    return photo_sample.screen_dims({"screen_dims": []}) == set(), "not empty"


@case
def a_malformed_entry_is_refused_rather_than_ignored():
    """This key MOVES FILES. Skipping an entry nobody can parse would make
    screenshot detection silently blind, which is worse than stopping."""
    for bad in ({"screen_dims": [{"model": "x"}]},
                {"screen_dims": [[1080]]},
                {"screen_dims": ["1080x2280"]}):
        try:
            photo_sample.screen_dims(bad)
        except SystemExit:
            continue
        return False, f"{bad} was accepted"
    return True, "all three refused"


@case
def the_census_pairs_a_candidate_with_the_only_device_present():
    c = photo_census.census(ONE_SHOT + [row("IMG_0004.PNG", "PNG", 1170, 2532)])
    s = c["screen_size_candidates"][0]
    return s["model"] == "Apple iPhone 12", str(s)


@case
def the_census_proposes_no_device_when_several_are_present():
    rows = ONE_SHOT + [row("IMG_0004.PNG", "PNG", 1170, 2532),
                       row("DSC_0001.JPG", "JPEG", 6000, 4000,
                           make="NIKON CORPORATION", model="Z 8")]
    c = photo_census.census(rows)
    text = photo_census.render(c, "x", {}, None)
    return (c["screen_size_candidates"][0]["model"] is None
            and "more than one device here" in text), text


@case
def an_unpaired_pack_is_named_as_unauditable_in_the_report():
    c = photo_census.census(ONE_SHOT + [row("IMG_0004.PNG", "PNG", 1170, 2532)])
    flat = photo_census.render(c, "x", FLAT, "someone")
    paired = photo_census.render(c, "x", PAIRED, "someone")
    return ("carry no device model" in flat
            and "carry no device model" not in paired), flat[-400:]


# ---------------------------------------------------------------------------
# G-2 — the checkpoint's missing trigger (b): a screen size spotted mid-run,
# reported without stopping the run.
# ---------------------------------------------------------------------------

def dump(tmp, rows):
    """A work dir holding just the manifest the trigger reads."""
    workdir = Path(tmp) / "unit"
    workdir.mkdir(parents=True, exist_ok=True)
    fields = ["SourceFile", "FileName", "FileType", "ImageWidth",
              "ImageHeight", "Make", "Model"]
    with open(workdir / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows([{k: r[k] for k in fields} for r in rows])
    return workdir


# One named capture proves 1290x2796 is a screen; four unnamed stills sit at
# the same size and nothing in the pack has confirmed it.
UNIT_SEVEN = [row("Screenshot_20260101_101010.png", "PNG", 1290, 2796)] + \
    [row(f"IMG_90{i}.PNG", "PNG", 1290, 2796) for i in range(4)] + \
    [row(f"IMG_10{i}.JPG", "JPEG", 4032, 3024, make="Apple", model="iPhone 15")
     for i in range(3)]


@case
def a_size_proven_by_a_filename_becomes_a_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        got = photo_plan.screen_size_candidates(dump(tmp, UNIT_SEVEN), {})
    return (list(got) == [("1290", "2796")]
            and got[("1290", "2796")]["files"] == 5), str(got)


@case
def a_size_the_pack_already_confirmed_is_not_re_proposed():
    pack = {"screen_dims": [{"model": "Apple iPhone 15",
                             "dims": [1290, 2796]}]}
    with tempfile.TemporaryDirectory() as tmp:
        got = photo_plan.screen_size_candidates(dump(tmp, UNIT_SEVEN), pack)
    return got == {}, str(got)


@case
def a_named_screen_recording_never_makes_a_video_size_a_candidate():
    """The 326-video hazard. One named screen recording at 1080x1920 must not
    turn every ordinary video in the dump into a possible screenshot."""
    rows = [row("Screen_Recording_20260101.mp4", "MP4", 1080, 1920)] + \
        [row(f"VID_{i}.mp4", "MP4", 1080, 1920) for i in range(20)]
    with tempfile.TemporaryDirectory() as tmp:
        got = photo_plan.screen_size_candidates(dump(tmp, rows), {})
    return got == {}, str(got)


@case
def a_size_the_owners_own_camera_also_makes_is_dropped():
    rows = [row("Screenshot_20260101_101010.png", "PNG", 4032, 3024),
            row("stripped.png", "PNG", 4032, 3024),
            row("IMG_1.JPG", "JPEG", 4032, 3024, make="Apple", model="iPhone 15")]
    with tempfile.TemporaryDirectory() as tmp:
        got = photo_plan.screen_size_candidates(dump(tmp, rows), {})
    return got == {}, str(got)


@case
def the_candidate_set_does_not_depend_on_which_plan_runs():
    """The pipeline is resumable, so a candidate set read from the plan's own
    batches would route one file two ways depending on run order. It is read
    from the manifest, which every plan sees whole."""
    with tempfile.TemporaryDirectory() as tmp:
        wd = dump(tmp, UNIT_SEVEN)
        first = photo_plan.screen_size_candidates(wd, {})
        # the evidence file alone, as a single late plan would have seen it
        wd2 = dump(tmp + "/b", UNIT_SEVEN[1:])
        without_evidence = photo_plan.screen_size_candidates(wd2, {})
    return (first and not without_evidence), \
        f"{first} vs {without_evidence}"


@case
def an_affected_file_goes_to_triage_and_the_run_is_not_blocked():
    msg = photo_profile.messages({"language": "en"})
    dims = photo_plan.screen_candidate_dims({("1290", "2796")})
    plan = {"dest": {"mode": "new", "path": "/sorted/20260101_trip"}}
    r = {"FileName": "IMG_900.PNG", "FileType": "PNG", "ImageWidth": "1290",
         "ImageHeight": "2796", "Make": "-", "Model": "-", "_day": "2026-01-01",
         "SourceFile": "/raw/IMG_900.PNG", "DateTimeOriginal": "2026:01:01 10:00:00",
         "GPSPosition": "-"}
    action, dest, note, tags = photo_plan.route(
        r, plan, "/sorted", {}, msg, profile={"language": "en"},
        screen_candidates=dims)
    return (action == "copy" and tags == {"screen_candidate"}
            and dest == "/sorted/20260100_To-be-checked"
            and "1290x2796" in note), f"{action} {dest} {tags} {note}"


@case
def a_rotated_capture_reaches_triage_too():
    """The same screen held sideways. screen_size_candidates() keys portrait-
    normalised while its `files` count sums BOTH orientations, so the two
    numbers only agree because screen_candidate_dims() re-expands the key
    before route() ever sees it. Nothing asserted that expansion; drop it and
    every landscape capture is counted as affected and then left in the trip
    folder, silently."""
    msg = photo_profile.messages({"language": "en"})
    dims = photo_plan.screen_candidate_dims({("1290", "2796")})
    plan = {"dest": {"mode": "new", "path": "/sorted/20260101_trip"}}
    r = {"FileName": "IMG_901.PNG", "FileType": "PNG", "ImageWidth": "2796",
         "ImageHeight": "1290", "Make": "-", "Model": "-", "_day": "2026-01-01",
         "SourceFile": "/raw/IMG_901.PNG",
         "DateTimeOriginal": "2026:01:01 10:00:00", "GPSPosition": "-"}
    _a, dest, note, tags = photo_plan.route(
        r, plan, "/sorted", {}, msg, profile={"language": "en"},
        screen_candidates=dims)
    return (tags == {"screen_candidate"}
            and dest == "/sorted/20260100_To-be-checked"
            # the note quotes the file's OWN orientation, not the key's
            and "2796x1290" in note), f"{dest} {tags} {note}"


@case
def every_counted_file_is_either_moved_or_the_witness():
    """The queued `files_at_this_size` and `moved_to_to_be_checked` are two
    different numbers, and the ONLY file allowed to sit between them is the
    named witness — it goes to the screenshots bucket by ONB-12. Any other gap
    means a file was counted as affected and never routed.

    Runs the pair through screen_candidate_dims() exactly as photo_plan.py:579
    does. Reaching into route() with the raw candidate dict instead tests a
    shape production never passes, and reports a landscape file as stranded
    when it is not."""
    msg = photo_profile.messages({"language": "en"})
    rows = [{"FileName": n, "FileType": "PNG", "ImageWidth": w,
             "ImageHeight": h, "Make": "-", "Model": "-", "FileSize": "100",
             "_day": "2026-01-01", "SourceFile": f"/raw/{n}",
             "DateTimeOriginal": "2026:01:01 10:00:00", "GPSPosition": "-"}
            for n, w, h in (("Screenshot_20260101.png", "1440", "3120"),
                            ("IMG_900.PNG", "1440", "3120"),
                            ("IMG_901.PNG", "3120", "1440"))]
    with tempfile.TemporaryDirectory() as tmp:
        wd = Path(tmp)
        with open(wd / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        cands = photo_plan.screen_size_candidates(wd, {"language": "en"})
    counted = sum(c["files"] for c in cands.values())
    dims = photo_plan.screen_candidate_dims(cands)
    plan = {"dest": {"mode": "new", "path": "/sorted/20260101_trip"}}
    moved = witness = 0
    for r in rows:
        _a, _d, _n, tags = photo_plan.route(
            r, plan, "/sorted", {}, msg, profile={"language": "en"},
            screen_candidates=dims)
        moved += "screen_candidate" in tags
        witness += "screenshot" in tags
    return (counted == 3 and moved == 2 and witness == 1
            and counted == moved + witness), \
        f"counted={counted} moved={moved} witness={witness}"


@case
def a_confirmed_screenshot_still_beats_the_candidate_branch():
    """A file the ONB-12 name rule already catches belongs in the screenshots
    bucket, not in triage — the candidate branch must sit AFTER it."""
    msg = photo_profile.messages({"language": "en"})
    dims = photo_plan.screen_candidate_dims({("1290", "2796")})
    plan = {"dest": {"mode": "new", "path": "/sorted/20260101_trip"}}
    r = {"FileName": "Screenshot_20260101_101010.png", "FileType": "PNG",
         "ImageWidth": "1290", "ImageHeight": "2796", "Make": "-", "Model": "-",
         "_day": "2026-01-01", "SourceFile": "/raw/s.png",
         "DateTimeOriginal": "2026:01:01 10:00:00", "GPSPosition": "-"}
    _a, dest, _n, tags = photo_plan.route(
        r, plan, "/sorted", {}, msg, profile={"language": "en"},
        screen_candidates=dims)
    return (tags == {"screenshot"}
            and dest == "/sorted/20260100_Screenshots"), f"{dest} {tags}"


@case
def a_camera_tagged_file_at_a_candidate_size_is_left_alone():
    msg = photo_profile.messages({"language": "en"})
    dims = photo_plan.screen_candidate_dims({("1290", "2796")})
    plan = {"dest": {"mode": "new", "path": "/sorted/20260101_trip"}}
    r = {"FileName": "IMG_1.JPG", "FileType": "JPEG", "ImageWidth": "1290",
         "ImageHeight": "2796", "Make": "Apple", "Model": "iPhone 15",
         "_day": "2026-01-01", "SourceFile": "/raw/IMG_1.JPG",
         "DateTimeOriginal": "2026:01:01 10:00:00", "GPSPosition": "-"}
    _a, dest, _n, tags = photo_plan.route(
        r, plan, "/sorted", {}, msg,
        profile={"language": "en", "own_camera_makes": ["Apple"]},
        screen_candidates=dims)
    return dest == "/sorted/20260101_trip" and not tags, f"{dest} {tags}"


@case
def a_real_plan_run_queues_the_proposal_and_still_finishes():
    """End to end through photo_plan.py itself: the affected files land in the
    triage bucket, the proposal is queued in the plan document AND in the file
    photo_run reads, and the stage exits 0 — nothing about it blocks."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workdir = root / "Working Files" / "2026-01"
        (workdir / "plan").mkdir(parents=True)
        rows = []
        for r in UNIT_SEVEN:
            rows.append({**r, "FileSize": "1000000",
                         "SourceFile": f"{root}/raw/{r['FileName']}",
                         "DateTimeOriginal": "2026:01:01 10:00:00",
                         "GPSLatitude": "", "GPSLongitude": ""})
        with open(workdir / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        (workdir / "batches.json").write_text(json.dumps({
            "source": f"{root}/raw", "main_files": len(rows),
            "batches": [{"batch": 1, "from": "2026-01-01", "to": "2026-01-01",
                         "files": len(rows), "status": "classified",
                         "flags": []}]}))
        (workdir / "plans.json").write_text(json.dumps({
            "dest_root": f"{root}/sorted",
            "plans": [{"plan": 1, "title": "A day out", "batches": [1],
                       "dest": {"mode": "new",
                                "path": f"{root}/sorted/20260101_out"}}]}))
        env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
        proc = subprocess.run(
            # R1: onboarding fixtures carry no see stage; --no-vision says so.
            [sys.executable, str(SCRIPTS / "photo_plan.py"), str(workdir),
             "--plan", "1", "--no-status", "--no-vision"],
            capture_output=True, text=True,
            env=env)
        if proc.returncode != 0:
            return False, proc.stderr
        plan_rows = list(csv.DictReader(
            open(workdir / "plan" / "plan_P1-files.csv", newline="")))
        queued = json.loads((workdir / "plan"
                             / photo_plan.SCREEN_PROPOSALS_NAME).read_text())
        md = (workdir / "plan" / "plan_P1.md").read_text()

    triaged = [r for r in plan_rows if r["FileName"].startswith("IMG_90")]
    trip = [r for r in plan_rows if r["FileName"].startswith("IMG_10")]
    shot = [r for r in plan_rows
            if r["FileName"].startswith("Screenshot_")]
    ok = (len(triaged) == 4
          and all("20260100_" in r["destination"] for r in triaged)
          and all(r["destination"].endswith("20260101_out") for r in trip)
          and len(shot) == 1 and "20260100_" in shot[0]["destination"]
          and shot[0]["destination"] != triaged[0]["destination"]
          and queued["proposed_screen_dims"][0]["dims"] == [1290, 2796]
          and queued["proposed_screen_dims"][0]["model"] is None
          and queued["moved_to_to_be_checked"] == {"1": 4}
          and "1290x2796" in md)
    return ok, (f"triaged={[r['destination'] for r in triaged][:1]} "
                f"trip={len(trip)} shot={[r['destination'] for r in shot]} "
                f"queued={queued}")


@case
def the_moved_count_survives_a_second_plan_that_moved_nothing():
    """Every plan of a dump writes the same proposal file, and `finish` prints
    the banner once at the end. A count stored as a single number would be the
    LAST plan's, so a dump that triaged files in P1 and none in P2 would
    announce zero."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workdir = root / "Working Files" / "2026-01"
        (workdir / "plan").mkdir(parents=True)
        rows = []
        for i, r in enumerate(UNIT_SEVEN):
            rows.append({**r, "FileSize": "1000000",
                         "SourceFile": f"{root}/raw/{r['FileName']}",
                         "DateTimeOriginal": "2026:01:01 10:00:00",
                         "GPSLatitude": "", "GPSLongitude": ""})
        # a second day with nothing at a candidate size
        rows.append({**row("IMG_777.JPG", "JPEG", 4032, 3024,
                           make="Apple", model="iPhone 15"),
                     "FileSize": "1000000",
                     "SourceFile": f"{root}/raw/IMG_777.JPG",
                     "DateTimeOriginal": "2026:01:05 10:00:00",
                     "GPSLatitude": "", "GPSLongitude": ""})
        with open(workdir / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        (workdir / "batches.json").write_text(json.dumps({
            "source": f"{root}/raw", "main_files": len(rows),
            "batches": [
                {"batch": 1, "from": "2026-01-01", "to": "2026-01-01",
                 "files": 8, "status": "classified", "flags": []},
                {"batch": 2, "from": "2026-01-05", "to": "2026-01-05",
                 "files": 1, "status": "classified", "flags": []}]}))
        (workdir / "plans.json").write_text(json.dumps({
            "dest_root": f"{root}/sorted",
            "plans": [
                {"plan": 1, "title": "day one", "batches": [1],
                 "dest": {"mode": "new", "path": f"{root}/sorted/20260101_a"}},
                {"plan": 2, "title": "day five", "batches": [2],
                 "dest": {"mode": "new", "path": f"{root}/sorted/20260105_b"}}]}))
        env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
        for n in ("1", "2"):
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "photo_plan.py"), str(workdir),
                 "--plan", n, "--no-status", "--no-vision"],
                capture_output=True, text=True,
                env=env)
            if proc.returncode != 0:
                return False, proc.stderr
        queued = json.loads((workdir / "plan"
                             / photo_plan.SCREEN_PROPOSALS_NAME).read_text())
    moved = queued["moved_to_to_be_checked"]
    return (moved == {"1": 4, "2": 0} and sum(moved.values()) == 4), str(queued)


# ---------------------------------------------------------------------------
# OA-10 — the fourth proposal: home areas, mined from GPSPosition and capture
# time. Every coordinate below is hand-written, arbitrary and out at sea; no
# owner's coordinate enters this repo (Rule 7).
# ---------------------------------------------------------------------------

HOME_LAT, HOME_LON = 10.5, -20.5     # a negative longitude on purpose: it parses
TRIP_LAT, TRIP_LON = 5.25, -30.75


def gps_row(name, lat, lon, when):
    """A manifest row carrying the two columns the home proposal reads. `when`
    is exiftool's own format, colons in the date half and all."""
    r = row(name, "JPEG", 4032, 3024, make="Apple", model="iPhone 12")
    r["GPSPosition"] = f"{lat} {lon}"
    r["DateTimeOriginal"] = when
    return r


def stay(lat, lon, days, night_days, per_day=3, step=2, offset=0):
    """`days` separate days photographed at one point, `night_days` of them
    carrying an after-dark shot. `step` 2 scatters them through the month the
    way a home is; `step` 1 makes the consecutive block a trip is."""
    out = []
    for i in range(days):
        hour = 21 if i < night_days else 12
        for k in range(per_day):
            out.append(gps_row(f"IMG_{offset + i * per_day + k:04d}.JPG",
                               lat, lon,
                               f"2026:03:{i * step + 1:02d} {hour:02d}:1{k}:00"))
    return out


HOME_ONE_MONTH = stay(HOME_LAT, HOME_LON, days=12, night_days=8)
TRIP = stay(TRIP_LAT, TRIP_LON, days=4, night_days=4, per_day=9, step=1)


def visits(lat, lon, months, prefix):
    """One daytime photo at a point on the 5th of each `months` (YYYY:MM)."""
    return [gps_row(f"{prefix}_{i:02d}.JPG", lat, lon, f"{m}:05 12:00:00")
            for i, m in enumerate(months)]


@case
def the_snl_bar_is_days_and_months_from_the_pack():
    """REPRODUCTION (G6-2, R1). ⛔ FAILS on 76cb997: nothing selected a place to
    NAME mid-run. A place is asked when it clears BOTH bars and the pack does
    not answer it. The bars here come from the pack (2 days, 2 months), so the
    case rests on no shipped default: two days in two months passes, two days
    in one month does not, and a place at a home or at a named place is
    already answered."""
    named_at = (15.5, -35.5)
    rows = (visits(7.25, -40.25, ["2026:01", "2026:02"], "A")
            + visits(8.25, -41.25, ["2026:03", "2026:03"], "B")
            + [gps_row("B_02.JPG", 8.25, -41.25, "2026:03:09 12:00:00")]
            + visits(HOME_LAT, HOME_LON, ["2026:01", "2026:02"], "H")
            + visits(*named_at, ["2026:01", "2026:02"], "N"))
    profile = {"cluster_defaults": {"fsl_min_days": 2, "fsl_min_months": 2},
               "home_locations": [{"id": "home-01", "label": "Ford",
                                   "lat": HOME_LAT, "lon": HOME_LON}]}
    named = [(named_at[0], named_at[1], "Cafe", "fsl-0001")]
    found = photo_census.unnamed_frequent_places(rows, profile, named)
    got = [sorted(p["sources"]) for p in found]
    return got == [["/raw/A_00.JPG", "/raw/A_01.JPG"]], f"{got}"


@case
def the_snl_bar_ships_three_days_and_three_months_and_the_template_writes_neither():
    """GUARD (G6-2, R1 + R8). The one case that reads the shipped defaults:
    3 days and 3 months. ⛔ The pack template writes neither key, nor the batch
    page count: a default in code and a default in a pack are one fact."""
    template = json.loads((SCRIPTS.parent / "templates" / "photo-memory" /
                           "_template" / "photo-profile.json").read_text())
    carried = [k for k in ("fsl_min_days", "fsl_min_months")
               if k in (template.get("cluster_defaults") or {})]
    carried += [k for k in ("batch_pages",) if k in (template.get("memory") or {})]
    two_months = (visits(7.25, -40.25, ["2026:01", "2026:02"], "T")
                  + [gps_row("T_09.JPG", 7.25, -40.25, "2026:02:09 12:00:00")])
    three = visits(7.25, -40.25, ["2026:01", "2026:02", "2026:03"], "T")
    return (photo_profile.fsl_bar({}) == (3, 3) and not carried
            and photo_census.unnamed_frequent_places(two_months, {}, []) == []
            and len(photo_census.unnamed_frequent_places(three, {}, [])) == 1), \
        f"bar={photo_profile.fsl_bar({})} template carries {carried}"


@case
def a_one_month_home_shaped_collection_still_proposes():
    """§7.0's regression guard. One dump is one month, so a month-span term
    inside the gate could never fire on a first run — and the first run is
    exactly when the residence-privacy rule has nothing else to go on. Month
    span is still shown, because §7.1 asks for the evidence."""
    c = photo_census.census(HOME_ONE_MONTH)
    homes = c["home_candidates"]
    text = photo_census.render(c, "x", {}, None)
    return (len(homes) == 1 and homes[0]["months"] == 1
            and homes[0]["days"] == 12 and homes[0]["night_days"] == 8
            and "1 month(s)" in text
            # FIX8 F8-8: the map link is evidence the owner may open, but it
            # is a coordinate — it goes to the places file, never the screen.
            and homes[0]["map"] not in text
            and homes[0]["map"] in photo_census.render_places_file(c)
            and "openstreetmap.org" in homes[0]["map"]), str(homes)


@case
def a_trip_shaped_collection_of_the_same_size_proposes_nothing():
    """Same file count, one place, every night away from home — and it does
    not clear the distinct-days bar, because four days is what a trip is.

    Honest about its own limit: a LONGER trip would be proposed, and that is
    the direction the bars are deliberately wrong in (§7.2b) — one extra line
    the owner says no to, rather than a residence nobody ever hears about."""
    c = photo_census.census(TRIP)
    return (len(TRIP) == len(HOME_ONE_MONTH)
            and c["home_candidates"] == []), \
        f"{len(TRIP)} vs {len(HOME_ONE_MONTH)} files: {c['home_candidates']}"


@case
def a_place_never_photographed_at_night_is_not_a_home():
    """Night-days gates as an equal, not as a tiebreaker: drop it and a place
    somebody merely visits often reads as somewhere they live."""
    daytime = stay(HOME_LAT, HOME_LON, days=12, night_days=0)
    return photo_census.census(daytime)["home_candidates"] == [], "proposed"


@case
def a_residence_spread_across_touching_cells_is_proposed_once():
    """GPS scatter around one address straddles cell edges, so the raw grid
    holds four cells for this one home. Un-merged, the owner is handed four
    near-identical rows and no threshold repairs that."""
    spread = []
    for n, (dlat, dlon) in enumerate([(0, 0), (0.011, 0), (0, 0.011),
                                      (0.011, 0.011)]):
        spread += stay(HOME_LAT + dlat, HOME_LON + dlon, days=12,
                       night_days=8, per_day=1, offset=100 * n)
    cells = {photo_census.cell_of(*[float(v) for v in
                                    r["GPSPosition"].split()]) for r in spread}
    homes = photo_census.census(spread)["home_candidates"]
    return (len(cells) == 4 and len(homes) == 1
            and homes[0]["files"] == len(spread)), \
        f"{len(cells)} cells -> {homes}"


@case
def an_empty_proposal_list_asks_the_question_in_the_same_round():
    """The ordinary first run, not an edge: a thin or GPS-poor dump proposes
    nothing, and the privacy rule still needs its answer today. The typed
    prompt therefore has to sit INSIDE the same section — a second interview
    is what this must not become."""
    c = photo_census.census(ONE_SHOT)
    text = photo_census.render(c, "x", {}, None)
    head = text.find("home areas (-> home_locations")
    typed = text.find("at CITY level")
    after = text.find("every camera found is already listed")
    return (c["home_candidates"] == []
            and head != -1 and after != -1
            and head < typed < after), text[head:after]


@case
def a_home_proposal_never_becomes_a_pack_value_on_its_own():
    """The census proposes and never writes. Runs the real command line over a
    dump that DOES propose, and checks the pack came back byte-identical."""
    pack = {"owner": {"slug": "beta00", "display": "Beta"}, "language": "en"}
    fields = ["SourceFile", "FileName", "FileType", "ImageWidth", "ImageHeight",
              "Make", "Model", "GPSPosition", "DateTimeOriginal"]
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "unit"
        workdir.mkdir(parents=True)
        with open(workdir / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows([{k: r[k] for k in fields} for r in HOME_ONE_MONTH])
        profile = Path(tmp) / "photo-profile.json"
        profile.write_text(json.dumps(pack))
        before = profile.read_bytes()
        env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "photo_census.py"), str(workdir),
             "--profile", str(profile)], capture_output=True, text=True, env=env)
        wrote = sorted(p.name for p in workdir.iterdir())
        after = profile.read_bytes()
    return (proc.returncode == 0
            and "home areas (-> home_locations" in proc.stdout
            and "distinct day(s)" in proc.stdout
            and "Nothing was written to the pack" in proc.stdout
            and before == after
            # FIX8 F8-8: the coordinates go to a places file beside the
            # manifest instead of the screen. The pack is still untouched.
            and wrote == [photo_census.PLACES_FILE, "manifest.csv"]), \
        f"rc={proc.returncode} wrote={wrote} changed={before != after} {proc.stderr}"


# ---------------------------------------------------------------------------
# D2 — the home proposals get the cross-check the cameras have had all along.
# Another arbitrary point out at sea, far enough from HOME that no radius
# could confuse the two.
# ---------------------------------------------------------------------------

OTHER_LAT, OTHER_LON = -3.25, 47.5


def two_homes():
    return HOME_ONE_MONTH + stay(OTHER_LAT, OTHER_LON, days=12, night_days=8,
                                 offset=500)


@case
def a_home_the_pack_already_holds_is_not_re_asked():
    """D2: the census read `own_camera_makes` and never `home_locations`, so
    every re-run told the operator to CONFIRM a residence the pack had held
    since before that run — and an owner who answers the same question twice
    writes a duplicate row.

    Both halves in ONE render, because a fix that just says "already listed"
    to everything passes either half alone: the held home drops out of the
    ask, and the place the pack has never seen is still asked about."""
    c = photo_census.census(two_homes())
    pack = {"home_locations": [{"label": "somewhere",
                                "lat": HOME_LAT, "lon": HOME_LON}]}
    text = photo_census.render(c, "x", pack, "beta00")
    marked = [ln for ln in text.splitlines()
              if "already listed in" in ln and "distinct day(s)" in ln]
    return (len(c["home_candidates"]) == 2
            and len(marked) == 1
            # FIX8 F8-8: rows are numbered on screen; the number leads to the
            # coordinate in the places file.
            and [f"place {n}" for n, h in photo_census.numbered_places(c)
                 if tuple(h["coord"]) == (HOME_LAT, HOME_LON)][0] in marked[0]
            and f"{HOME_LAT}" not in text
            and "CONFIRM the 1 row(s)" in text
            and "CITY word" in text), \
        f"marked={marked}\n{text}"


@case
def a_census_that_proposes_only_known_homes_says_so_and_asks_nothing():
    """The camera check's own sentence, for homes: with nothing new to
    confirm the section says so instead of handing back a list of answered
    questions. ⛔ The evidence rows stay — they are what makes a listed home
    auditable — and only the instruction goes."""
    pack = {"home_locations": [
        {"label": "somewhere", "lat": HOME_LAT, "lon": HOME_LON},
        {"label": "elsewhere", "lat": OTHER_LAT, "lon": OTHER_LON}]}
    text = photo_census.render(photo_census.census(two_homes()), "x",
                               pack, "beta00")
    return ("every home area found is already listed in pack `beta00`" in text
            and "CONFIRM" not in text
            and "distinct day(s)" in text), text


# ---------------------------------------------------------------------------
# D-04 — the census says what it WITHHELD, not only what it proposed.
#
# The measured failure: an owner's third residence cleared the day bar and
# missed the night bar (the whole dump held one day with an after-dark photo
# there — they were moving out, so the daylight was spent indoors packing and
# the evenings out). It was dropped in silence, the owner read the silence as
# "that place is not in this dump", declined to register their own home, and
# nothing then suppressed its address from a folder name.
#
# ⛔ These cases assert the DISCLOSURE, never a lower bar. A case that made
# the place get proposed would be the fix the defect log rules out.
# ---------------------------------------------------------------------------

MOVING_LAT, MOVING_LON = 42.125, 8.875   # a fourth arbitrary point at sea


def a_home_with_the_lights_off():
    """A residence photographed on 4 separate days, ONE of them after dark —
    the move-out shape. Misses both bars; it is somewhere the owner lives."""
    return stay(MOVING_LAT, MOVING_LON, days=4, night_days=1, offset=900)


@case
def a_withheld_home_is_disclosed_with_its_evidence():
    """The reproduction. Before D-04 the rejected group left no trace in the
    census at all: not in the JSON, not in the render, not as a count."""
    c = photo_census.census(HOME_ONE_MONTH + a_home_with_the_lights_off())
    text = photo_census.render(c, "x", {}, None)
    near = c.get("home_near_misses", [])
    return (len(c["home_candidates"]) == 1
            and len(near) == 1
            and near[0]["days"] == 4 and near[0]["night_days"] == 1
            and sorted(near[0]["missed"]) == ["days", "night_days"]
            and "NOT proposed as homes" in text
            and "silence here is not evidence of absence" in text
            and "4 distinct day(s), 1 of them with a photo after dark" in text
            and near[0]["map"] not in text
            and near[0]["map"] in photo_census.render_places_file(c)),         f"candidates={c['home_candidates']} near={near}\n{text}"


@case
def a_withheld_home_says_WHICH_bar_it_missed():
    """"Withheld" on its own is the same silence one step quieter. A place
    that missed only the night bar must not be described as short of days:
    the owner recognises the place from the counts and the reason together."""
    c = photo_census.census(HOME_ONE_MONTH
                            + stay(MOVING_LAT, MOVING_LON, days=9,
                                   night_days=1, offset=900))
    text = photo_census.render(c, "x", {}, None)
    near = c.get("home_near_misses", [])
    why = [ln for ln in text.splitlines() if "withheld because" in ln]
    return (len(near) == 1 and near[0]["missed"] == ["night_days"]
            and len(why) == 1
            and "after dark" in why[0]
            and "separate days" not in why[0]), f"{near} {why}"


@case
def a_daylight_only_residence_still_reaches_the_disclosure():
    """The half a night-photo rule can never see, and the reason the
    reporting filter is `returned on a second day` OR `seen after dark`
    rather than both. A residence with zero after-dark photos is invisible to
    the bars by construction; if it were also invisible here, the one owner
    the bars cannot serve would be the one owner told nothing."""
    c = photo_census.census(HOME_ONE_MONTH
                            + stay(MOVING_LAT, MOVING_LON, days=4,
                                   night_days=0, offset=900))
    near = c.get("home_near_misses", [])
    return (len(near) == 1 and near[0]["night_days"] == 0
            and near[0]["days"] == 4), str(near)


@case
def a_census_with_nothing_withheld_prints_no_disclosure():
    """A guard, not a reproduction: the block is evidence, so it stays away
    when there is none. Two clean homes and nothing else — an owner told
    "5 further places were withheld" over an empty set learns a false thing
    about their own collection."""
    c = photo_census.census(two_homes())
    text = photo_census.render(c, "x", {}, None)
    return (c.get("home_near_misses", []) == []
            and c.get("home_near_misses_over_cap", 0) == 0
            and c.get("home_near_misses_one_day_only", 0) == 0
            and "NOT proposed as homes" not in text), text


@case
def the_two_withheld_counts_are_never_summed():
    """A place the display cap cut looks exactly like the rows above it and
    could be a residence. A place the reporting filter cut was seen on one
    day and never after dark. The report describes the second and refuses to
    describe the first — summing them would put a reason on places that do
    not have it, which is the move that made the original silence readable as
    absence."""
    crowd = list(HOME_ONE_MONTH)
    for n in range(getattr(photo_census, "HOME_NEAR_MISS_SHOWN", 5) + 2):
        crowd += stay(MOVING_LAT + n * 0.05, MOVING_LON, days=3,
                      night_days=1, offset=900 + 100 * n)
    # two one-day daylight stops, which only the filter may describe
    crowd += stay(MOVING_LAT, MOVING_LON + 0.5, days=1, night_days=0,
                  offset=5000)
    crowd += stay(MOVING_LAT, MOVING_LON + 1.5, days=1, night_days=0,
                  offset=5100)
    c = photo_census.census(crowd)
    text = photo_census.render(c, "x", {}, None)
    return (len(c.get("home_near_misses", [])) == getattr(photo_census, "HOME_NEAR_MISS_SHOWN", 5)
            and c.get("home_near_misses_over_cap", 0) == 2
            and c.get("home_near_misses_one_day_only", 0) == 2
            and "2 more place(s) missed the bars in the same way" in text
            and "2 further place(s) were withheld too" in text
            and "ONE day and never after dark" in text),         (f"shown={len(c.get('home_near_misses', []))} "
         f"cap={c.get('home_near_misses_over_cap')} "
         f"filtered={c.get('home_near_misses_one_day_only')}\n{text}")


@case
def every_screen_size_is_checked_not_only_warned_about():
    """F6 — the reproduction. A home is compared against the pack and shown
    with its evidence; a camera make is compared against the pack. A screen
    size was taken on the owner's word, with a warning that the top row is
    routinely a resized photograph and nothing that CHECKED which rows were.
    The manifest already says two things that do: how many files at the size
    are named like screenshots, and whether the size has a camera photo's
    shape. And whether the pack already holds it, like a home row's tick."""
    ev = getattr(photo_census, "screen_evidence", None)
    if ev is None:
        return False, "photo_census has no screen_evidence(): taken on trust"
    rows = [row(f"Screenshot_2031010{i}_app.png", "PNG", 1080, 2340)
            for i in range(2)]
    rows += [row(f"IMG_{i:04d}.JPG", "JPEG", 1200, 1600) for i in range(3)]
    rows += [row("IMG_9001.JPG", "JPEG", 4032, 3024, make="Apple",
                 model="iPhone 12")]
    c = photo_census.census(rows)
    by = {tuple(s["dims"]): s for s in c["screen_size_candidates"]}
    shot, photo = by.get(("1080", "2340")), by.get(("1200", "1600"))
    if not (shot and photo):
        return False, f"fixture produced {list(by)}"
    pack = {"screen_dims": [{"model": "Q", "dims": [1080, 2340]}]}
    a, b = ev(shot, pack), ev(photo, pack)
    text = photo_census.render(c, "x", pack, None)
    return ("2 of 2" in a and "named like a screenshot" in a
            and "phone screen" in a and "already" in a
            and "0 of 3" in b and "4:3" in b and "already" not in b
            and a in text and b in text), f"{a}\n{b}\n{text}"


@case
def a_zero_sized_image_is_described_not_crashed_on():
    """The reproduction, of a defect F6 brought in (13c6061) and W1C-1 copied.
    exiftool writes 0 for some corrupt images; two of them at 0x0 make a
    screen-size candidate, and the shape check divided by the short side, so
    the census print and the onboarding page both died on ZeroDivisionError.
    The check is evidence: with no size it states no shape, and it never
    drops the candidate."""
    import photo_onboard_page as op
    rows = [row(f"broken{i}.jpg", "JPEG", 0, 0) for i in range(2)]
    try:
        c = photo_census.census(rows)
        text = photo_census.render(c, "x", {}, None)
        said = op.device_check({"device": "Q", "dims": [1440, 3120]},
                               ["0", "0"])
    except ZeroDivisionError as err:
        return False, f"crashed: {err}"
    return (len(c["screen_size_candidates"]) == 1
            and "no shape" in text and "always wins" in said), f"{text}\n{said}"


@case
def every_offer_to_print_more_names_a_flag_that_does():
    """F3 — the reproduction. The census told the reader to "ask for the
    rest" (the cap cut) and to "ask for the full grid" (the one-visit cut),
    and its CLI was `target`, `--profile`, `--json`: nothing could produce
    either. Both offers must name the flag, and the flag must print every
    withheld place — both cuts — so an offer is never a dead end."""
    crowd = list(HOME_ONE_MONTH)
    for n in range(getattr(photo_census, "HOME_NEAR_MISS_SHOWN", 5) + 2):
        crowd += stay(MOVING_LAT + n * 0.05, MOVING_LON, days=3,
                      night_days=1, offset=900 + 100 * n)
    crowd += stay(MOVING_LAT, MOVING_LON + 0.5, days=1, night_days=0,
                  offset=5000)
    crowd += stay(MOVING_LAT, MOVING_LON + 1.5, days=1, night_days=0,
                  offset=5100)
    text = photo_census.render(photo_census.census(crowd), "x", {}, None)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "manifest.csv"), "w", newline="",
                  encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(crowd[0]))
            wr.writeheader()
            wr.writerows(crowd)
        env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
        run = subprocess.run(
            [sys.executable, photo_census.__file__, tmp, "--all-places"],
            capture_output=True, text=True, env=env)
    full = run.stdout
    shown = sum("withheld because" in ln for ln in full.splitlines())
    return (" ".join(text.split()).count("--all-places") == 2
            and run.returncode == 0 and shown == 7 + 2
            and "more place(s) missed the bars" not in full
            and "further place(s) were withheld too" not in full), (
        f"offers naming the flag: {text.count('--all-places')}, "
        f"rc={run.returncode}, rows printed with it: {shown} of 9\n"
        f"{run.stderr[-300:]}")


@case
def the_disclosure_moves_no_bar_and_writes_no_pack():
    """⛔ The rule the whole card turns on. The withheld place is disclosed
    and is STILL not proposed — `home_candidates()` is unchanged, the two bars
    are unchanged, and nothing here reaches `home_locations` on its own."""
    rows = HOME_ONE_MONTH + a_home_with_the_lights_off()
    c = photo_census.census(rows)
    return (photo_census.HOME_MIN_DAYS == 5
            and photo_census.HOME_MIN_NIGHT_DAYS == 3
            and len(photo_census.home_candidates(rows)) == 1
            and c["home_candidates"] == photo_census.home_candidates(rows)
            and all("proposed" not in h and "missed" not in h
                    for h in c["home_candidates"])), str(c["home_candidates"])


# ---------------------------------------------------------------------------
# The conductor's own prep-stage checklist: preflight and the "next:" list.
# Both are operator instructions, which is the same job the census does, so
# they are guarded beside it rather than in a suite of their own.
# ---------------------------------------------------------------------------


def status_text(workdir):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        photo_run.print_status(workdir)
    return buf.getvalue()


def embedded_dump(tmp, with_labels, status="pending"):
    """A prepped dump that already carries a VS-1 image index, with and
    without the scene-label file the axis needs. Nothing here is read for its
    content — only the two paths print_status tests for exist.

    `status` picks which of print_status's two next-step branches is reached:
    `pending` is the classify branch, `classified` (with no plans.json and no
    see-labels.json) is the VISUAL-pass branch."""
    workdir = Path(tmp) / "unit"
    (workdir / "embed").mkdir(parents=True)
    (workdir / "embed" / "embeddings.npy").write_bytes(b"")
    if with_labels:
        (workdir / "embed" / "scene-labels.json").write_text("{}")
    (workdir / "batches.json").write_text(json.dumps({
        "source": "/raw", "main_files": 1,
        "batches": [{"batch": 1, "from": "2026-01-01", "to": "2026-01-01",
                     "files": 1, "status": status, "flags": []}]}))
    return workdir


@case
def the_next_step_names_the_scene_axis_it_depends_on():
    """D3: photo_see runs perfectly well with no scene-label matrix — it
    writes a valid report and matches nothing — so an operator following this
    list got an empty scene column with no sign that a stage was missing. The
    hint must also stay quiet once the file is there, or it teaches nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        off = status_text(embedded_dump(tmp, with_labels=False))
    with tempfile.TemporaryDirectory() as tmp:
        on = status_text(embedded_dump(tmp, with_labels=True))
    return ("--scene-labels" in off and "photo_see.py" in off
            and "--scene-labels" not in on and "photo_see.py" in on), \
        f"missing:\n{off}\npresent:\n{on}"


@case
def the_visual_pass_branch_names_the_scene_axis_too():
    """U2-09. D3 above closed the CLASSIFY branch only. print_status has a
    SECOND next-step branch — every batch classified, no plans.json yet — and
    that one is where the visual pass is actually listed, in the order
    photo-run/SKILL.md step 2b mirrors. It printed photo_embed, photo_identity
    and photo_see and never named `--scene-labels`, so the operator who
    followed it built an image index, an identity index and a see report with
    the scene axis off for the whole dump, at exit 0.

    A dependency named in one branch and not the other is not named: which
    branch you land in is decided by how far the dump has got, not by whether
    you need the label matrix."""
    with tempfile.TemporaryDirectory() as tmp:
        off = status_text(embedded_dump(tmp, with_labels=False,
                                        status="classified"))
    with tempfile.TemporaryDirectory() as tmp:
        on = status_text(embedded_dump(tmp, with_labels=True,
                                       status="classified"))
    return ("VISUAL" in off and "--scene-labels" in off
            and "photo_see.py" in off
            and "--scene-labels" not in on and "photo_see.py" in on), \
        f"missing:\n{off}\npresent:\n{on}"


@case
def the_run_skill_lists_the_scene_label_step():
    """U2-09, the prose half. The engine's own status output is only read by
    an operator who runs `status`; photo-run/SKILL.md step 2b is the list the
    driving agent works from, and it carried three commands where the pipeline
    has four. The two must not drift apart again — a code hint nobody is told
    to look for is not a step."""
    skill = (Path(__file__).resolve().parent.parent
             / "photo-run" / "SKILL.md").read_text(encoding="utf-8")
    block = skill.split("2b.", 1)[-1].split("\n3. ", 1)[0]
    return ("--scene-labels" in block
            and "photo_identity.py" in block
            and "photo_see.py" in block), \
        f"step 2b does not name --scene-labels:\n{block[:1200]}"


@case
def the_preflight_probe_says_who_it_is():
    """D1: the probe went out with the stdlib's default User-Agent, which the
    geocoder answers 403 to — so preflight reported the service unreachable on
    every run, and the remedy it named turns a working feature OFF. The header
    is the whole fix, and it has to be the SAME one the stage that really
    geocodes sends, or the probe stops answering for it.

    ⛔ Offline: the probe is captured, never made."""
    seen = []

    def fake_urlopen(target, timeout=None):
        seen.append(target)
        return None

    real = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            photo_run.preflight()
    finally:
        urllib.request.urlopen = real

    probe = seen[0] if seen else None
    sent = probe.get_header("User-agent") \
        if isinstance(probe, urllib.request.Request) else None
    # The geocoding stage sets the header inline at each call site and there
    # is nowhere shared to import the string from, so it is read off that
    # file's source: the two drifting apart is the failure this catches.
    geocoder = set(re.findall(r'"User-Agent":\s*"([^"]+)"',
                              (SCRIPTS / "photo_where.py").read_text()))
    return (bool(geocoder) and sent in geocoder), \
        f"probe={probe!r} sent={sent!r}, the geocoder sends {sorted(geocoder)}"


# ---------------------------------------------------------------------------
# FIX6 (U6-37) — a screen size the owner answered `no` to is remembered
# ---------------------------------------------------------------------------

TEMPLATE_PACK = SCRIPTS.parent / "templates" / "photo-memory" / "_template"
OWNER = "fixture-owner"


def declined_pack(root, declined):
    """A template-made pack declining `declined` ([[w, h], ...])."""
    import shutil
    pack_dir = Path(root) / "photo-memory" / OWNER
    shutil.copytree(TEMPLATE_PACK, pack_dir)
    for path in list(pack_dir.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", OWNER)))
    profile_file = pack_dir / photo_profile.PROFILE_NAME
    prof = json.loads(profile_file.read_text(encoding="utf-8")
                      .replace("{{SLUG}}", OWNER).replace("{{DISPLAY}}", OWNER))
    prof["declined_screen_dims"] = declined
    profile_file.write_text(json.dumps(prof, indent=1), encoding="utf-8")
    return pack_dir


def unit_seven_workdir(root):
    workdir = Path(root) / "Working Files" / "2026-01"
    (workdir / "plan").mkdir(parents=True)
    rows = [{**r, "FileSize": "1000000", "SourceFile": f"{root}/raw/{r['FileName']}",
             "DateTimeOriginal": "2026:01:01 10:00:00",
             "GPSLatitude": "", "GPSLongitude": ""} for r in UNIT_SEVEN]
    with open(workdir / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (workdir / "batches.json").write_text(json.dumps({
        "source": f"{root}/raw", "main_files": len(rows),
        "batches": [{"batch": 1, "from": "2026-01-01", "to": "2026-01-01",
                     "files": len(rows), "status": "classified", "flags": []}]}))
    (workdir / "plans.json").write_text(json.dumps({
        "dest_root": f"{root}/sorted",
        "plans": [{"plan": 1, "title": "A day out", "batches": [1],
                   "dest": {"mode": "new", "path": f"{root}/sorted/20260101_out"}}]}))
    return workdir


def declined_plan_run(route):
    """photo_plan over UNIT_SEVEN with a pack declining its proven size, bound
    by `route`. -> (ok, detail)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workdir = unit_seven_workdir(root)
        pack = declined_pack(root, [[1290, 2796]])
        env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
        if route == "env":
            env["PHOTO_PROFILE"] = str(pack / photo_profile.PROFILE_NAME)
        else:
            (workdir.parent / "collection.json").write_text(json.dumps({
                "collection": "fixture", "owner": OWNER,
                "memory_root": str(pack.parent)}))
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "photo_plan.py"), str(workdir),
             "--plan", "1", "--no-status", "--no-vision"],
            capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            return False, proc.stderr[-400:]
        queue = workdir / "plan" / photo_plan.SCREEN_PROPOSALS_NAME
        queued = json.loads(queue.read_text()) if queue.exists() else {}
        md = (workdir / "plan" / "plan_P1.md").read_text()
    proposed = [q["dims"] for q in queued.get("proposed_screen_dims", [])]
    return ([1290, 2796] not in proposed and "1290x2796" not in md
            and not sum((queued.get("moved_to_to_be_checked") or {}).values())), \
        f"proposed={proposed} queued={queued}"


@case
def a_declined_screen_size_is_not_proposed_again_env_route():
    """REPRODUCTION (FIX6, U6-37). ⛔ FAILS on 0865b82: the owner's `no` was
    kept nowhere, so the plan proposed the size again at the end of the copy
    and sent its files to the to-be-checked bucket. Pack bound by
    $PHOTO_PROFILE."""
    return declined_plan_run("env")


@case
def a_declined_screen_size_is_not_proposed_again_collection_route():
    """REPRODUCTION (FIX6, U6-37). ⛔ FAILS on 0865b82. Pack bound by
    collection.json."""
    return declined_plan_run("collection")


@case
def a_declined_screen_size_is_not_offered_by_the_census_flag_route():
    """REPRODUCTION (FIX6, U6-37). ⛔ FAILS on 0865b82: the census (and the
    onboarding page and sheet built from it) offered the size again. Pack
    given by --profile."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workdir = unit_seven_workdir(root)
        pack = declined_pack(root, [[1290, 2796]])
        env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "photo_census.py"), str(workdir),
             "--profile", str(pack), "--json"],
            capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        return False, proc.stderr[-400:]
    c = json.loads(proc.stdout)
    dims = [s["dims"] for s in c["screen_size_candidates"]]
    return ([1290, 2796] not in dims and c.get("screen_sizes_declined") == 1), \
        f"dims={dims} declined={c.get('screen_sizes_declined')}"


@case
def write_pack_remembers_a_no_to_a_screen_size():
    """REPRODUCTION (FIX6, U6-37). ⛔ FAILS on 0865b82: `apply --write-pack`
    wrote the accepted sizes and dropped the `no`. It now writes the declined
    size, merged with what the pack already declined."""
    import photo_onboard_page as op
    answers = {"lines": [], "makes": {}, "own_camera_makes": [],
               "screens": {"1054x1080": False, "1080x2340": "Phone"},
               "homes": {}, "language": "", "types": "", "away_km": "",
               "pets": "", "header": {}, "blank": []}
    plan, refuse = op.pack_updates(answers, {}, {"declined_screen_dims": [[720, 720]]}, {},
                                   add_screens={(1080, 2340)},
                                   screen_gate={(1080, 2340): None})
    got = [v for where, what, v in plan if what == "declined_screen_dims"]
    return (not refuse and got == [[[720, 720], [1054, 1080]]]), f"plan={plan} refuse={refuse}"


@case
def the_sheet_does_not_ask_a_declined_size_again():
    """GUARD (FIX6, U6-37). The onboarding page and sheet read their screen
    questions through the same filter as the census."""
    import photo_onboard_page as op
    census = {"screen_size_candidates": [
        {"dims": [1290, 2796], "files": 5, "warning": None, "model": None,
         "named_like_screenshots": 1},
        {"dims": [1080, 2340], "files": 4, "warning": None, "model": None,
         "named_like_screenshots": 4}],
        "screen_sizes_below_threshold": 0, "screenshots_by_filename": 0}
    got = op.screens_section([], census, {"declined_screen_dims": [[2796, 1290]]})
    dims = [c["dims"] for c in got["candidates"]]
    return dims == [[1080, 2340]], f"{dims}"


@case
def the_template_ships_the_key_and_it_moves_the_pack_fingerprint():
    """GUARD (FIX6, U6-37). The template writes `declined_screen_dims: []`, and
    the key is inside the pack fingerprint: declining a size changes routing,
    so a freeze taken before it must not hold after it."""
    template = json.loads((TEMPLATE_PACK / photo_profile.PROFILE_NAME)
                          .read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        pack = declined_pack(tmp, [])
        profile_file = pack / photo_profile.PROFILE_NAME
        before = photo_profile.resolve_pack(explicit=profile_file).snapshot()["id"]
        prof = json.loads(profile_file.read_text())
        prof["declined_screen_dims"] = [[1054, 1080]]
        profile_file.write_text(json.dumps(prof, indent=1))
        after = photo_profile.resolve_pack(explicit=profile_file).snapshot()["id"]
    return (template.get("declined_screen_dims") == [] and before != after), \
        f"template={template.get('declined_screen_dims')} {before} {after}"


# ---------------------------------------------------------------------------
# M4 (Release B) — an owner who is not a developer is never told to edit JSON.
#
# The owner's ruling (20260920) extends M4 from the screen-size checkpoint to
# the census home row as well: the engine writes the row for the owner, AND the
# coordinate stays off screen. The owner names a place by the NUMBER the report
# already shows plus a label; `read_coords()` takes the pair from
# `census-places.txt`, which already holds it on disk keyed by that same
# number, and `pack_updates()` splits it into the pack's two fields itself.
# ⛔ One reader, not two — this widens the file shapes `read_coords()` accepts
# and adds no second reader of the coordinate.


@case
def the_census_home_row_does_not_ask_for_hand_written_json():
    """REPRODUCTION. The report told the owner to WRITE a row as
    {"label": ..., "lat": <first number>, "lon": <second number>} and said the
    pair "has to be split by hand". An owner who is not a developer cannot do
    that, and splitting it is exactly what the engine already does."""
    c = photo_census.census(HOME_ONE_MONTH)
    text = photo_census.render(c, "x", {}, None)
    return ('"lat": <first number>' not in text
            and "split by hand" not in text
            # and it still says what to DO — a removal is not a fix
            and "apply" in text and "--write-pack" in text), text[-500:]


@case
def the_census_closing_line_names_the_command_not_the_json_file():
    """REPRODUCTION. "put the accepted values in their photo-profile.json" is
    the same instruction in one sentence, and it covers the screen answers too
    — which `apply --write-pack` has always been able to write."""
    text = photo_census.render(photo_census.census(ONE_SHOT), "x", {}, None)
    return ("put the accepted values in their photo-profile.json" not in text
            and "Nothing was written to the pack" in text), text[-400:]


@case
def the_census_still_says_to_pick_the_sizes_by_hand():
    """GUARD: "PICK from these by hand" is about CHOOSING, not about editing
    JSON. Card 9 changed the below-threshold line on purpose: it used to tell
    the owner to type a size in by hand, and a pasted size the census never
    offered is now refused — so that sentence would name a dead route."""
    rows = ONE_SHOT + [row("IMG_0004.PNG", "PNG", 1170, 2532)]
    text = photo_census.render(photo_census.census(rows), "x", {}, None)
    below = photo_census.render(photo_census.census(ONE_SHOT), "x", {}, None)
    return ("PICK from these by hand" in text
            and "type the size in by hand" not in below), text[-300:]


@case
def read_coords_takes_the_census_places_file():
    """REPRODUCTION. `RE_COORD_ROW` matched a single LETTER key, so the file
    the census writes ("place 1: <lat>, <lon>") parsed to nothing and `apply`
    exited saying it "holds no coordinate rows" — measured on a real census
    file before the fix. Both shapes now read through the one reader."""
    import photo_onboard_page as op
    tmp = tempfile.mkdtemp(prefix="onb_m4_")
    try:
        io.open(os.path.join(tmp, "census-places.txt"), "w",
                encoding="utf-8").write(
            "census places — the coordinate and map link for each place the "
            "census report numbers. Kept on disk; never printed.\n\n"
            "place 1: 10.5, 20.25\n"
            "  https://example.invalid/map\n"
            "place 2: -11.5, -21.25\n"
            "  https://example.invalid/map\n")
        # ⛔ Report, never raise: on the unfixed code this exits with
        # "holds no coordinate rows", and a SystemExit here would abort the
        # whole suite instead of failing one case — which is what it did the
        # first time this red proof was run.
        def coords(where):
            try:
                return op.read_coords(where)
            except SystemExit as exc:
                return "refused: %s" % str(exc)[:80]

        path = os.path.join(tmp, "census-places.txt")
        got = coords(path)
        lettered = os.path.join(tmp, "coords.txt")
        io.open(lettered, "w", encoding="utf-8").write(
            "A  10.5, 20.25  40 day(s)\n   https://example.invalid/map\n")
        still = coords(lettered)
        return (got == {"1": (10.5, 20.25), "2": (-11.5, -21.25)}
                and still == {"A": (10.5, 20.25)}), f"{got} | {still}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# M13 (Release B) — the evidence index missed a candidate's own files.


def _screens_for(rows):
    import photo_onboard_page as op
    op.document_filter = lambda: (lambda _b: False)   # nothing is a document
    op.ACTIVE_FILTER = None
    op.encode_image = lambda path, ftype: "data:image/jpeg;base64,x"
    return op.screens_section(rows, photo_census.census(rows))["candidates"]


def _shot(name, w, h):
    return row(name, "PNG", w, h)


@case
def a_candidates_evidence_finds_its_files_in_either_orientation():
    """REPRODUCTION (M13, measured on the real UAT02-01 page). The census
    collapses a screen size to PORTRAIT and sums both orientations
    (`photo_census.py:337-341` — "a candidate is one size, not two rows"), but
    the page's evidence index keyed on the RAW `(ImageWidth, ImageHeight)`.

    On the real dump the census proposed 1054x1080 while BOTH its files were
    stored 1080x1054, so the evidence list came back empty and the page told
    the owner "no file at this size" — about a question that MOVES FILES,
    with `files: 2` printed in the same block.
    """
    rows = [_shot("A.png", "1080", "1054"), _shot("B.png", "1080", "1054")]
    cands = _screens_for(rows)
    one = [c for c in cands if sorted(c["dims"]) == sorted(["1054", "1080"])]
    if not one:
        return False, f"no candidate proposed at all: {[c['dims'] for c in cands]}"
    c = one[0]
    return (c["files"] == 2 and len(c["names"]) == 2
            and len(c["thumbs"]) == 2), \
        f"files={c['files']} names={len(c['names'])} thumbs={len(c['thumbs'])}"


@case
def a_mixed_orientation_candidate_shows_every_files_evidence():
    """REPRODUCTION. The other half, and it is silent rather than false: on
    the real dump 1080x2340 held 4 portrait files and 2 landscape, the census
    counted 6, and the evidence index saw only the 4 — so the strip, the
    filename list and the withheld count were all computed over a subset the
    owner was never told about."""
    rows = ([_shot("P%d.png" % i, "1080", "2340") for i in range(4)]
            + [_shot("L%d.png" % i, "2340", "1080") for i in range(2)])
    cands = _screens_for(rows)
    one = [c for c in cands if sorted(c["dims"], key=int) == ["1080", "2340"]]
    if not one:
        return False, f"not proposed: {[c['dims'] for c in cands]}"
    c = one[0]
    return (c["files"] == 6 and len(c["thumbs"]) == min(6, len(c["thumbs"]))
            and len(c["names"]) == min(6, op_exemplars())), \
        f"files={c['files']} names={len(c['names'])} thumbs={len(c['thumbs'])}"


def op_exemplars():
    import photo_onboard_page as op
    return op.EXEMPLARS


# ---------------------------------------------------------------------------
# M16b (Release B) — the screen question printed raw owner filenames.
#
# ⛔ The names are EVIDENCE, not decoration: measured on the real page they are
# the only thing some questions have when the U3-06 document check withholds
# the photographs — and a chat screenshot is exactly what that check withholds.
# So they are MASKED, never dropped: the date and the app word are what let an
# owner recognise a size, and the id is what must not travel.


@case
def a_masked_name_keeps_the_date_and_the_app_and_drops_the_id():
    """REPRODUCTION (M16b). Measured on the real UAT02-01 page: 13 of 14 names
    carried a run of 8+ digits, the longest name was 146 characters, and three
    carried paired UUID-shaped query tokens — chat ids, on a page whose own
    text says it may be passed on."""
    import photo_onboard_page as op
    cases = [
        # (name, must still contain, must NOT contain)
        ("Screenshot_20240115_143022_ChatApp.jpg", ["20240115", "ChatApp"], []),
        ("chat_a1b2c3d4-e5f6-7890-abcd-ef1234567890&thread_id=9f8e7d6c-1a2b.jpg",
         [], ["a1b2c3d4-e5f6-7890-abcd-ef1234567890", "9f8e7d6c"]),
        ("IMG_20231102_090301.png", ["20231102"], []),
        ("0123456789012345678901234.jpg", [], ["0123456789012345678901234"]),
        # ⛔ A phone number is exactly what this exists to keep off a surface
        # the product says may be passed on, and it came through WHOLE while
        # the run threshold was 12. A TIME (6 digits) and a frame number must
        # still survive — that is the air the bound sits in.
        ("IMG_0912345678_received.jpg", ["received"], ["0912345678"]),
        ("Screenshot_20240115_143022_Chat.jpg",
         ["20240115", "143022", "Chat"], []),
        ("VID_20240115_093012.mp4", ["20240115", "093012"], []),
        ("DSC_0042.JPG", ["0042"], []),
    ]
    if not hasattr(op, "mask_name"):
        return False, "mask_name() is not defined"
    bad = []
    for name, keep, drop in cases:
        got = op.mask_name(name)
        for k in keep:
            if k not in got:
                bad.append("%r lost %r" % (name[:24], k))
        for d in drop:
            if d in got:
                bad.append("%r kept id %r" % (name[:24], d[:12]))
        if len(got) > op.NAME_SHOWN_MAX:
            bad.append("%r is %d chars" % (name[:24], len(got)))
    return not bad, "; ".join(bad)


@case
def the_page_block_carries_no_raw_owner_filename():
    """REPRODUCTION. `photo_onboard_page.py:1093` put `", ".join(cand["names"])`
    straight into the question block."""
    import photo_onboard_page as op
    op.ACTIVE_FILTER = None
    op.encode_image = lambda p, t: "data:image/jpeg;base64,x"
    rows = [row("chat_deadbeefcafe1234567890ab&tid=11112222-3333-4444.png",
                "PNG", "1080", "2340") for _ in range(3)]
    for i, r in enumerate(rows):
        r["SourceFile"] = "/x/chat_deadbeefcafe1234567890ab&tid=1111222%d-3333-4444.png" % i
    screens = op.screens_section(rows, photo_census.census(rows))
    data = {"screens": screens, "cameras": {"devices": []},
            "homes": {"rows": [], "near_misses": []}, "files": len(rows)}
    # BOTH surfaces, from the one source. The SHEET prints the names
    # (`sheet_blocks`); the PAGE never displays them but embeds them in its
    # JSON data block, and the page FILE is the thing that gets passed on — so
    # an undisplayed id still travels. Masking at `screens_section()` is what
    # covers both without a second copy of the rule.
    leaked = []
    if "deadbeefcafe1234567890ab" in json.dumps(screens):
        leaked.append("the page's own data block")
    if "deadbeefcafe1234567890ab" in json.dumps(op.sheet_blocks(data)):
        leaked.append("the sheet's question block")
    return not leaked, "raw id-bearing filename reached: " + ", ".join(leaked)


@case
def the_full_filename_list_is_kept_on_disk():
    """GUARD, on the `places_file()` pattern F8-8 proved: what is withheld from
    the page is not destroyed, it is written beside it, and the page says
    where. An owner who cannot recognise a size from a masked name has
    somewhere to look."""
    import photo_onboard_page as op
    if not (hasattr(op, "names_file") and hasattr(op, "write_names_file")):
        return False, "names_file()/write_names_file() are not defined"
    tmp = tempfile.mkdtemp(prefix="onb_m16b_")
    try:
        page = os.path.join(tmp, "page.html")
        cands = [{"dims": ["1080", "2340"],
                  "names": ["Screenshot_20240115_143022_ChatApp.jpg",
                            "chat_a1b2c3d4-e5f6-7890-abcd-ef1234567890.jpg"]}]
        op.write_names_file(op.names_file(page), cands)
        text = io.open(op.names_file(page), encoding="utf-8").read()
        return ("a1b2c3d4-e5f6-7890-abcd-ef1234567890" in text
                and "1080x2340" in text), text[:200]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Q7 (owner ruling, 20260920) — a stale places file is REFUSED, not warned.
#
# Census place numbers are per-run: `numbered_places()` enumerates
# home_candidates + near_misses, so a re-run over a changed manifest can
# renumber. An owner answering `home: 1 = ...` against an OLD file would
# register the WRONG coordinate, silently. The owner chose a refusal over a
# warning because a wrong home address must never be saved quietly — it is a
# Rule 3 hazard. ⛔ The stamp names the MANIFEST, never the pack, and carries
# no coordinate; the refusal names the step to re-run, never a place.


def _census_dir(tmp, rows):
    """A work dir holding a manifest and the census places file beside it."""
    import photo_onboard_page as op          # noqa: F401  (one reader lives there)
    wd = os.path.join(tmp, "wd")
    os.makedirs(wd, exist_ok=True)
    path = os.path.join(wd, "manifest.csv")
    with io.open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return wd, path


@case
def the_places_file_is_stamped_with_its_manifest_and_no_coordinate():
    """REPRODUCTION. The file carried a header, numbered places and map links
    and NOTHING binding it to the run that wrote it."""
    if not hasattr(photo_census, "manifest_stamp"):
        return False, "manifest_stamp() is not defined"
    tmp = tempfile.mkdtemp(prefix="onb_q7a_")
    try:
        wd, path = _census_dir(tmp, HOME_ONE_MONTH)
        c = photo_census.census(HOME_ONE_MONTH)
        text = photo_census.render_places_file(c, path)
        stamp = photo_census.manifest_stamp(path)
        has = ("manifest-stamp:" in text and stamp in text)
        # ⛔ the stamp must not be a coordinate, or the file's whole point dies
        import re as _re
        line = [ln for ln in text.splitlines() if "manifest-stamp:" in ln][0]
        clean = not _re.search(r"-?\d{1,3}\.\d{2,}\s*,\s*-?\d{1,3}\.\d{2,}", line)
        return (has and clean), f"{line!r}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case
def an_answer_against_a_stale_places_file_is_refused():
    """REPRODUCTION. With the manifest changed under it, the numbers in the
    file may name different places — so the read STOPS rather than register a
    coordinate the owner never confirmed."""
    import photo_onboard_page as op
    # ⛔ Report, never raise. On the unfixed code `render_places_file()` takes
    # one argument and `check_places_stamp()` does not exist — both raise, and
    # a raise here aborts the whole suite instead of failing this case, which
    # is exactly what hid this case's own red proof the first time.
    if not (hasattr(photo_census, "manifest_stamp")
            and hasattr(op, "check_places_stamp")):
        return False, "manifest_stamp()/check_places_stamp() are not defined"
    tmp = tempfile.mkdtemp(prefix="onb_q7b_")
    try:
        wd, path = _census_dir(tmp, HOME_ONE_MONTH)
        c = photo_census.census(HOME_ONE_MONTH)
        places = os.path.join(wd, photo_census.PLACES_FILE)
        io.open(places, "w", encoding="utf-8").write(
            photo_census.render_places_file(c, path))
        fresh = op.read_coords(places)          # matches -> reads normally
        # now the manifest changes under it
        with io.open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(HOME_ONE_MONTH[0].keys()))
            w.writerows(TRIP[:3])
        try:
            op.read_coords(places)
            return False, "a stale places file was read without complaint"
        except SystemExit as exc:
            said = str(exc)
        import re as _re
        return (bool(fresh)
                and "photo_census" in said
                and not _re.search(r"-?\d{1,3}\.\d{2,}\s*,\s*-?\d{1,3}\.\d{2,}",
                                   said)), said[:200]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case
def a_lettered_coords_file_has_no_stamp_and_is_still_read():
    """GUARD. `render`/`sheet` write `A  <lat>, <lon>  ...` with no stamp and
    no manifest beside it. The check must fire on a stamp that MISMATCHES,
    never on a file that never carried one — otherwise Q7 breaks the path M4
    depends on."""
    import photo_onboard_page as op
    tmp = tempfile.mkdtemp(prefix="onb_q7c_")
    try:
        path = os.path.join(tmp, "coords.txt")
        io.open(path, "w", encoding="utf-8").write(
            "A  10.5, 20.25  40 day(s)\n   https://example.invalid/map\n")
        return op.read_coords(path) == {"A": (10.5, 20.25)}, "lettered file"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case
def no_candidate_claims_no_files_while_counting_some():
    """GUARD, and it outlives the orientation fix. The page's empty-strip
    message is `emptyMsg` = "no file at this size", printed in the same block
    as `files: N`. Those two come from DIFFERENT sources — the strip from the
    evidence index, the count from the census — so any future divergence
    between them prints a falsehood about a question that MOVES FILES.

    ⛔ This asserts the INVARIANT, not the bug: a candidate with files must
    find at least one of them, whatever the indexing rule happens to be. It
    would have caught M13 without anyone knowing orientation was the cause.
    """
    shapes = [
        ("portrait only", [_shot("P%d.png" % i, "1080", "2340") for i in range(3)]),
        ("landscape only", [_shot("L%d.png" % i, "2340", "1080") for i in range(3)]),
        ("mixed", [_shot("P.png", "1080", "2340"), _shot("L.png", "2340", "1080"),
                   _shot("P2.png", "1080", "2340")]),
        ("square-ish landscape", [_shot("S%d.png" % i, "1080", "1054")
                                  for i in range(2)]),
    ]
    bad = []
    for label, rows in shapes:
        for c in _screens_for(rows):
            if c["files"] and not (c["thumbs"] or c["names"]
                                   or c["unreadable"] or c["withheld"]):
                bad.append("%s: %s counts %d file(s) and shows nothing"
                           % (label, "x".join(c["dims"]), c["files"]))
    return not bad, "; ".join(bad)


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

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} onboarding cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
