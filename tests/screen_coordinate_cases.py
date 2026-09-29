#!/usr/bin/env python3
"""FIX8 F8-8 (UAT01-6 U6-06) — no stage prints a GPS coordinate on screen.

Whatever a stage prints lands in the driving model's transcript, so a
residence's coordinate printed there leaves the machine even when the files
on disk keep it. Two routes did: the census printed each home and near-miss
row as a coordinate with a map link (and `prep` streams the census), and
clustering's no-name fallback wrote a coordinate into a batch's `place` and
`label`, which `photo_cluster.py`, `photo_run.py cluster` and
`photo_where.py` all printed. Files the owner keeps (the manifest,
`batches.json`, the census places file) are allowed to hold them.

Every coordinate here is invented and out at sea (Rule 7). The network is
blocked with a dead proxy and clustering runs `--no-geocode`, which is the
state that reaches the fallback.

  python3 tests/screen_coordinate_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(SCRIPTS))
import photo_index_cases as ix  # noqa: E402

HOME = (10.56789, 20.34567)
NEAR = (13.24681, 24.13579)
TRIP = (15.97531, 27.86420)
# The invented numbers' own leading digits, at any precision a stage rounds
# to, and any "number, number" pair.
MINE = re.compile(r"\b(10\.5[67]|20\.3[45]|13\.2[45]|24\.1[34]|15\.9[789]|"
                  r"16\.0[01]|27\.8[67])\d*|mlat=")
PAIR = re.compile(r"-?\d{1,3}\.\d{2,}\s*,\s*-?\d{1,3}\.\d{2,}")

CASES = []
VERBOSE = False


def case(fn):
    CASES.append(fn)
    return fn


def log(msg):
    if VERBOSE:
        print(f"        {msg}")


def dump(tmp, bind=True):
    rows = []
    for d in range(1, 13):
        for hh in ("10", "21"):
            rows.append(ix.row(f"H{d:02d}{hh}.jpg",
                               when=f"2024:11:{d:02d} {hh}:00:00", gps=HOME))
    for d in (13, 14):
        rows.append(ix.row(f"N{d}.jpg", when=f"2024:11:{d} 11:00:00", gps=NEAR))
    for d in (20, 21, 22):
        for i in range(3):
            rows.append(ix.row(f"T{d}{i}.jpg", when=f"2024:11:{d} 1{i}:00:00",
                               gps=(TRIP[0] + i * 0.01, TRIP[1])))
    wd = Path(tmp) / "Working Files" / "dump-a"
    wd.mkdir(parents=True)
    with open(wd / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ix.FIELDS)
        w.writeheader()
        w.writerows(rows)
    coll = {"collection": "fixture", "dest_root": str(Path(tmp) / "sorted")}
    if bind:
        pack = ix.make_pack(tmp, places=[])
        coll.update(owner=ix.OWNER, memory_root=str(pack.parent))
    (wd.parent / "collection.json").write_text(json.dumps(coll))
    return wd


def env():
    e = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
    dead = "http://127.0.0.1:9"
    e.update(HTTPS_PROXY=dead, HTTP_PROXY=dead, https_proxy=dead, http_proxy=dead)
    return e


def run(tmp, script, *argv):
    got = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, argv)],
                         capture_output=True, text=True, cwd=str(tmp), env=env(),
                         timeout=600)
    return got


def leaks(got):
    return [line for line in (got.stdout + got.stderr).splitlines()
            if MINE.search(line) or PAIR.search(line)]


@case
def the_census_prints_no_coordinate(tmp):
    """REPRODUCTION. Home and near-miss rows were `lat, lon` + a map link."""
    wd = dump(tmp)
    for extra in ((), ("--all-places",), ("--json",)):
        got = run(tmp, "photo_census.py", wd, *extra)
        assert got.returncode == 0, got.stderr[-400:]
        assert not leaks(got), (extra, len(leaks(got)))
    log("census, --all-places and --json: 0 coordinate lines")


@case
def the_census_keeps_the_numbers_in_a_file_it_names(tmp):
    """GUARD. The owner still needs the numbers to write a home row: they go
    to a file beside the manifest, numbered as on screen, and stdout names it."""
    wd = dump(tmp)
    got = run(tmp, "photo_census.py", wd)
    places = wd / "census-places.txt"
    assert places.exists(), got.stdout[-600:]
    assert str(places) in got.stdout, got.stdout[-600:]
    text = places.read_text(encoding="utf-8")
    assert "place 1" in got.stdout and "place 1" in text, text
    assert MINE.search(text) and "openstreetmap.org" in text, text


@case
def census_json_to_a_file_keeps_the_coordinates(tmp):
    """GUARD. `--json-out` writes the whole report, coordinates included."""
    wd = dump(tmp)
    out = Path(tmp) / "census.json"
    got = run(tmp, "photo_census.py", wd, "--json-out", out)
    assert got.returncode == 0 and not leaks(got), got.stdout[-400:]
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["home_candidates"] and doc["home_candidates"][0]["coord"], doc


@case
def clustering_prints_no_coordinate(tmp):
    """REPRODUCTION. The no-name fallback's coordinate reached the printed
    JSON and the label; `batches.json` (a file) still keeps `place`."""
    wd = dump(tmp)
    for script, argv in (("photo_cluster.py", (wd, "--no-geocode")),
                         ("photo_run.py", ("cluster", wd, "--force"))):
        got = run(tmp, script, *argv)
        assert got.returncode == 0, got.stderr[-400:]
        assert not leaks(got), (script, len(leaks(got)))
    batches = json.loads((wd / "batches.json").read_text())["batches"]
    assert any(PAIR.search(b.get("place") or "") for b in batches), batches
    assert not any(PAIR.search(b["label"]) for b in batches), batches
    log(f"{len(batches)} batch(es); place kept in the file, not in any label")


@case
def unbound_clustering_prints_no_coordinate(tmp):
    """REPRODUCTION, no pack: every batch reached the fallback."""
    wd = dump(tmp, bind=False)
    got = run(tmp, "photo_cluster.py", wd, "--no-geocode")
    assert got.returncode == 0 and not leaks(got), len(leaks(got))


@case
def an_added_anchor_prints_no_coordinate(tmp):
    """GUARD, not a reproduction — this path was already clean when it was
    written (Release B M16a, measured). `--anchor` is the one way a coordinate
    reaches a stage as an ARGUMENT rather than out of the manifest, and it ADDS
    a home that carries no label, so nothing in the pack can name it. The
    no-name fallback is exactly what F8-8 fixed, so the argument route needs
    the same bar as the manifest route, bound and unbound."""
    for bind in (True, False):
        wd = dump(tmp, bind=bind) if bind else dump(tmp / "un", bind=False)
        got = run(tmp, "photo_cluster.py", wd, "--no-geocode",
                  "--anchor", f"{TRIP[0]},{TRIP[1]}")
        assert got.returncode == 0, got.stderr[-400:]
        assert not leaks(got), (bind, len(leaks(got)))
        labels = [b["label"] for b in
                  json.loads((wd / "batches.json").read_text())["batches"]]
        assert not any(PAIR.search(x) or MINE.search(x) for x in labels), labels
    log("anchored clustering, bound and unbound: 0 coordinate lines")


@case
def a_malformed_anchor_answers_in_a_sentence(tmp):
    """REPRODUCTION (M4). A typo'd `--anchor` died in a raw Python traceback
    whose ValueError quoted the offending token — `--anchor "<lat>, <lon>x"`
    printed ' <lon>x', one coordinate component, on stderr. Two defects in one
    line: an owner who is not a developer gets a stack trace, and the one
    place a coordinate was echoed back to the screen.

    ⛔ The message must not quote what was typed. Asserted here, not just the
    absence of a traceback — a friendly message that helpfully repeats the bad
    value would pass the traceback half and fail the privacy half."""
    wd = dump(tmp)
    for bad in ("%s,notanumber" % HOME[0],
                "%s, %sx" % (HOME[0], HOME[1]),
                "%s,%s,9" % (HOME[0], HOME[1])):
        got = run(tmp, "photo_cluster.py", wd, "--no-geocode", "--anchor", bad)
        assert got.returncode == 1, (bad, got.returncode)
        assert "Traceback" not in got.stderr, bad
        assert "--anchor takes two numbers" in got.stderr, got.stderr[-200:]
        assert not leaks(got), (bad, len(leaks(got)))
    got = run(tmp, "photo_cluster.py", wd, "--no-geocode", "--force",
              "--anchor", "%s,%s" % (HOME[0], HOME[1]))
    assert got.returncode == 0, got.stderr[-300:]
    log("3 malformed anchors refused in a sentence; a valid one still runs")


@case
def where_and_status_print_no_coordinate(tmp):
    """REPRODUCTION. `photo_where.py` echoed the batch label."""
    wd = dump(tmp)
    got = run(tmp, "photo_cluster.py", wd, "--no-geocode")
    assert got.returncode == 0, got.stderr[-400:]
    batches = json.loads((wd / "batches.json").read_text())["batches"]
    for b in batches:
        got = run(tmp, "photo_where.py", wd, "--batch", b["batch"])
        assert got.returncode == 0 and not leaks(got), (b["batch"], len(leaks(got)))
    got = run(tmp, "photo_run.py", "status", wd)
    assert got.returncode == 0 and not leaks(got), len(leaks(got))


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose
    passed = 0
    for fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="screen_coords_"))
        try:
            fn(tmp)
        except Exception as exc:                                # noqa: BLE001
            print(f"  FAIL  {fn.__name__}: {type(exc).__name__}: {str(exc)[:300]}")
        else:
            print(f"  ok    {fn.__name__}")
            passed += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{passed}/{len(CASES)} screen-coordinate cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
