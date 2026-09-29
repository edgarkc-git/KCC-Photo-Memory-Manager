#!/usr/bin/env python3
"""Cases for photo_sample.py's COMMAND LINE — the half no other suite reaches.

`preclassify_cases.py` exercises this module's rules as functions and reads no
files at all, deliberately. That leaves the entry point untested, and the
entry point is where D-08 lived: a bare `open()` on a file that legitimately
does not exist, so the sweep the photo-classify SKILL tells every owner to run
once per source folder crashed with a raw traceback on a CLEAN dump.

  ./.venv/bin/python3 tests/photo_sample_cli_cases.py [-v]

Exit 0 = pass. Every work dir is built here; no drive is touched.
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def sweep(workdir):
    """-> the completed `--no-date` run."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "photo_sample.py"), str(workdir),
         "--no-date"], capture_output=True, text=True)


def write_no_date_csv(workdir, rows):
    fields = ["SourceFile", "FileName", "FileType", "ImageWidth",
              "ImageHeight", "Make", "Model"]
    with open(workdir / "no-date-files.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


@case
def a_dump_with_nothing_to_sweep_does_not_crash():
    """⛔ THE REPRODUCTION, and note which dump it is: a dump where every file
    carried a usable capture date never gets a `no-date-files.csv`, so the
    CLEAN case is the one that used to crash."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "dump"
        workdir.mkdir()
        # the precondition, asserted: there really is nothing to sweep
        assert not (workdir / "no-date-files.csv").exists()
        proc = sweep(workdir)
    if proc.returncode != 0:
        return f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    if "Traceback" in proc.stderr:
        return f"raw traceback: {proc.stderr.strip()[:200]}"
    return None


@case
def an_empty_sweep_still_answers_in_json():
    """⛔ Exit 0 is only half of it. This command has a documented output
    contract and an agent reads it, so the empty path answers in the SAME
    shape — replacing the object with a sentence would trade a traceback for
    an unparseable success, which a caller cannot tell from a broken run."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "dump"
        workdir.mkdir()
        proc = sweep(workdir)
    try:
        got = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return f"stdout is not JSON ({exc}): {proc.stdout.strip()[:200]}"
    if got.get("no_date_files") != 0:
        return f"count was {got.get('no_date_files')!r}, not 0"
    if got.get("preclass") != {}:
        return f"preclass was {got.get('preclass')!r}"
    if "nothing to sweep" not in (got.get("note") or ""):
        return f"no note saying why it is zero: {got!r}"
    return None


@case
def a_dump_with_undated_files_still_sweeps_them():
    """The POSITIVE CONTROL. Without it every assertion above is satisfied by
    a command that does nothing at all — the guard could swallow the real path
    too and this suite would stay green."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "dump"
        workdir.mkdir()
        write_no_date_csv(workdir, [
            {"SourceFile": "/raw/a.png", "FileName": "a.png",
             "FileType": "PNG", "ImageWidth": "800", "ImageHeight": "600",
             "Make": "-", "Model": "-"},
            {"SourceFile": "/raw/b.png", "FileName": "b.png",
             "FileType": "PNG", "ImageWidth": "800", "ImageHeight": "600",
             "Make": "-", "Model": "-"}])
        # the precondition, asserted: this dump really does have rows to sweep
        assert (workdir / "no-date-files.csv").exists()
        proc = sweep(workdir)
    if proc.returncode != 0:
        return f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    got = json.loads(proc.stdout)
    if got.get("no_date_files") != 2:
        return f"counted {got.get('no_date_files')!r} of 2 undated file(s)"
    if not got.get("preclass"):
        return "the rows were counted but never pre-classified"
    if "note" in got:
        return "a dump WITH rows claimed there was nothing to sweep"
    return None


@case
def an_empty_csv_is_not_the_same_as_a_missing_one():
    """A guard on the distinction the note makes. A header-only file means
    the sweep RAN and found none; a missing file means it never had anything
    to run on. Both count zero, and only one of them says why."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "dump"
        workdir.mkdir()
        write_no_date_csv(workdir, [])
        proc = sweep(workdir)
    if proc.returncode != 0:
        return f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    got = json.loads(proc.stdout)
    if got.get("no_date_files") != 0:
        return f"an empty csv counted {got.get('no_date_files')!r}"
    if "note" in got:
        return "an existing-but-empty csv was reported as a missing one"
    return None


def batch_dump(root, real):
    """A work dir with one batch of three own-camera stills; `real` says
    which of them exist as real JPEGs on disk."""
    import os
    from PIL import Image
    workdir = Path(root) / "dump"
    workdir.mkdir()
    fields = ["SourceFile", "FileName", "FileType", "DateTimeOriginal",
              "GPSPosition", "Make", "Model", "ImageWidth", "ImageHeight"]
    with open(workdir / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i in range(3):
            path = workdir / f"IMG_{i:04d}.JPG"
            if i in real:
                Image.new("RGB", (64, 48), (90, 60, 30)).save(path, "JPEG")
            w.writerow({"SourceFile": str(path), "FileName": path.name,
                        "FileType": "JPEG",
                        "DateTimeOriginal": f"2026:05:03 0{i + 1}:00:00",
                        "GPSPosition": "-", "Make": "Apple", "Model": "iPhone",
                        "ImageWidth": "4032", "ImageHeight": "3024"})
    (workdir / "batches.json").write_text(json.dumps({"batches": [
        {"batch": 1, "label": "fixture", "from": "2026-05-01", "to": "2026-05-31"}]}))
    env = {**os.environ, "PHOTO_PREVIEW_BACKEND": "pillow"}
    env.pop("PHOTO_PROFILE", None)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "photo_sample.py"), str(workdir),
         "--batch", "1", "--max-samples", "3"], capture_output=True, text=True, env=env)


@case
def a_batch_with_nothing_viewable_stops():
    """Card 4: the classify vision pass looks at these samples. With none
    made, the agent has nothing to view — the 2026-07-20 incident's setting.
    Exit 3, each cause on stderr; the report is still written."""
    with tempfile.TemporaryDirectory() as tmp:
        proc = batch_dump(tmp, real=())
    if proc.returncode != 3:
        return f"exit {proc.returncode}: {proc.stderr.strip()[-300:]}"
    if "source_missing" not in proc.stderr:
        return f"no cause named: {proc.stderr.strip()[-300:]}"
    return None


@case
def one_viewable_sample_is_enough_to_go_on():
    """A partial failure stays exit 0 and names its cause in the report."""
    with tempfile.TemporaryDirectory() as tmp:
        proc = batch_dump(tmp, real=(1,))
    if proc.returncode != 0:
        return f"exit {proc.returncode}: {proc.stderr.strip()[-300:]}"
    got = json.loads(proc.stdout)
    causes = {f.get("cause") for f in got["sample_failures"]}
    if len(got["samples"]) != 1 or causes != {"source_missing"}:
        return f"samples {len(got['samples'])}, causes {causes}"
    return None


@case
def a_batch_sample_skips_an_unanswered_screen_size():
    """⛔ REPRODUCES F-jj on the classify path: a no-camera still at a screen
    size the pack does not list was sampled for the vision model. Real JPEGs,
    so a sample is made when a file IS picked."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "dump"
        workdir.mkdir()
        fields = ["SourceFile", "FileName", "FileType", "DateTimeOriginal",
                  "GPSPosition", "Make", "Model", "ImageWidth", "ImageHeight"]
        rows = []
        for i in range(4):
            path = workdir / f"IMG_{i:04d}.PNG"
            Image.new("RGB", (40, 80), (i * 40, 20, 20)).save(path, "PNG")
            rows.append({"SourceFile": str(path), "FileName": path.name,
                         "FileType": "PNG",
                         "DateTimeOriginal": f"2026:03:0{i + 1} 10:00:00",
                         "GPSPosition": "-", "Make": "-", "Model": "-",
                         "ImageWidth": "1179", "ImageHeight": "2556"})
        with open(workdir / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        (workdir / "batches.json").write_text(json.dumps({"batches": [
            {"batch": 1, "label": "t", "from": "2026-03-01", "to": "2026-03-31"}]}))
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "photo_sample.py"), str(workdir),
             "--batch", "1"], capture_output=True, text=True)
        try:
            got = json.loads((workdir / "classify" / "batch-01" /
                              "sample-report.json").read_text())
        except (OSError, ValueError) as exc:
            return f"no report ({exc}); exit {proc.returncode}: {proc.stderr[:200]}"
    if got["samples"]:
        return f"{len(got['samples'])} unanswered-screen-size file(s) sampled"
    if (got.get("held_from_vision") or {}).get("pending_screen_size") != 4:
        return f"held_from_vision {got.get('held_from_vision')}"
    if proc.returncode != 0:
        return f"exit {proc.returncode} (nothing failed, nothing to view)"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failed = 0
    for fn in CASES:
        problem = fn()
        if problem:
            failed += 1
            print(f"FAIL  {fn.__name__}\n      {problem}")
        elif args.verbose:
            print(f"pass  {fn.__name__}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} photo_sample CLI cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
