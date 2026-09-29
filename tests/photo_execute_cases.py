#!/usr/bin/env python3
"""Unit cases for the execute stage — the one stage that writes to the drive,
and until now the one stage with no suite of its own.

The defect these were written for: `dest_root` is created lazily, as a parent
of the first destination dir, and only under `--go`. But the free-space check
runs before that, on both a dry run and a real one, and measured the space at
`dest_root` itself. On a first run — the run where `dest_root` has never been
created — that raised FileNotFoundError, and the user's first contact with the
stage was a Python traceback. Neither the golden replay nor any other suite
could see it: every fixture replays the PLAN stage, and the four frozen dumps
all describe a destination root that already exists.

So the cases below run the real script end to end over a synthetic dump whose
`dest_root` does not exist yet, once dry and once for real. Nothing on a drive
is read or written — sources and destination both live in a temp dir.

  python3 tests/photo_execute_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_execute  # noqa: E402


def build_dump(tmp, dest_root):
    """A minimal work dir the execute stage will accept: one approved batch,
    one plan, and a files csv naming real sources under tmp."""
    src_dir = tmp / "raw"
    src_dir.mkdir()
    sources = []
    for i, name in enumerate(("a.jpg", "b.jpg")):
        p = src_dir / name
        p.write_bytes(b"pixels-%d" % i)
        sources.append(p)

    wd = tmp / "work"
    (wd / "plan").mkdir(parents=True)
    trip = f"{dest_root}/20260708_trip"
    (wd / "batches.json").write_text(json.dumps(
        {"source": str(src_dir), "generated_at": "2026-07-08 00:00",
         "batches": [{"batch": 1, "status": "approved", "label": "trip",
                      "from": "2026-07-08", "to": "2026-07-08",
                      "days": 1, "files": 2, "gps_files": 2, "flags": []}]}))
    (wd / "plans.json").write_text(json.dumps(
        {"dest_root": str(dest_root),
         "plans": [{"plan": 1, "batches": [1],
                    "dest": {"mode": "new", "path": trip}}]}))
    with open(wd / "plan" / "plan_P1-files.csv", "w", newline="") as f:
        # Same columns photo_plan writes — the execute stage reads `batch`
        # back off this file to advance a batch to done.
        w = csv.DictWriter(f, ["SourceFile", "FileName", "batch", "date",
                               "action", "destination", "note", "who",
                               "who_provenance", "what", "what_provenance"])
        w.writeheader()
        for p in sources:
            w.writerow({"SourceFile": str(p), "FileName": p.name, "batch": "1",
                        "date": "2026-07-08", "action": "copy",
                        "destination": trip, "note": "", "who": "",
                        "who_provenance": "", "what": "",
                        "what_provenance": ""})
    return wd, sources, Path(trip)


def run_execute(wd, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "photo_execute.py"), str(wd),
         "--plan", "1", *extra],
        capture_output=True, text=True)


def free_space_walks_up_to_an_existing_ancestor():
    """The unit half: a dest_root several levels below anything that exists
    still reports the filesystem's free space, not an exception."""
    with tempfile.TemporaryDirectory() as td:
        missing = Path(td) / "not" / "created" / "yet"
        free = photo_execute.free_space_at(missing)
    return free > 0, f"free={free}"


def free_space_matches_the_existing_path_case():
    """And it agrees with the plain answer when the path does exist, so the
    walk-up is not quietly measuring a different filesystem."""
    with tempfile.TemporaryDirectory() as td:
        here = photo_execute.free_space_at(Path(td))
        below = photo_execute.free_space_at(Path(td) / "missing")
    # Free space moves under us on a live disk; agree to within 1%.
    return abs(here - below) < max(here, 1) * 0.01, f"{here} vs {below}"


def dry_run_survives_a_dest_root_that_does_not_exist():
    """The regression: the first run a real owner ever makes."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        dest_root = tmp / "drive" / "_Photo_Manager"   # deliberately absent
        (tmp / "drive").mkdir()
        wd, _, _ = build_dump(tmp, dest_root)
        r = run_execute(wd)
        if "Traceback" in r.stderr:
            return False, r.stderr.strip().splitlines()[-1]
        return (r.returncode == 0 and "DRY-RUN ONLY" in r.stdout,
                f"rc={r.returncode} {r.stdout.strip()[-200:]}")


def go_creates_the_dest_root_and_copies_verified():
    """--go on the same absent dest_root: the root is created, both files land
    with their bytes intact, and nothing is left as a .part."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        dest_root = tmp / "drive" / "_Photo_Manager"
        (tmp / "drive").mkdir()
        wd, sources, trip = build_dump(tmp, dest_root)
        r = run_execute(wd, "--go")
        if "Traceback" in r.stderr:
            return False, r.stderr.strip().splitlines()[-1]
        if not trip.is_dir():
            return False, f"destination not created (rc={r.returncode})"
        for src in sources:
            dest = trip / src.name
            if not dest.is_file():
                return False, f"{src.name} not copied"
            if dest.read_bytes() != src.read_bytes():
                return False, f"{src.name} copied but differs"
        parts = list(trip.glob("*.part"))
        return not parts, f"leftover .part files: {parts}"


def sources_are_never_touched():
    """Copy-only (D2), asserted rather than assumed: after a real --go every
    source is still there, with the same bytes."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        dest_root = tmp / "drive" / "_Photo_Manager"
        (tmp / "drive").mkdir()
        wd, sources, _ = build_dump(tmp, dest_root)
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        run_execute(wd, "--go")
        after = {p: (hashlib.sha256(p.read_bytes()).hexdigest()
                     if p.is_file() else None) for p in sources}
        bad = {p.name: (before[p], after[p]) for p in sources
               if before[p] != after[p]}
        return not bad, f"{bad}"


def unreachable_destination_exits_with_a_message():
    """The other side of the walk-up: when the drive really is not mounted the
    stage must still say so in one line, not raise."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        dest_root = tmp / "drive" / "_Photo_Manager"   # 'drive' never created
        wd, _, _ = build_dump(tmp, dest_root)
        # tmp itself exists, so the walk-up finds it — the point here is only
        # that a dest_root under a missing mount does not crash.
        r = run_execute(wd)
        return "Traceback" not in r.stderr, r.stderr.strip()[-200:]


def mark_verified(wd, sources, dest_dir):
    """Record every source as copied by an earlier run into `dest_dir`."""
    (wd / "plan" / "execute-state_P1.json").write_text(json.dumps(
        {"plan": 1, "verified": {str(p): {"dest": str(Path(dest_dir) / p.name),
                                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                                          "status": "copied", "at": "2026-07-08 00:00"}
                                 for p in sources}}))


def go_creates_no_folder_that_receives_no_file():
    """FIX8 F8-2 (reproduction). Every file was already copied, under the
    folder's OLD name; the plan now names it differently. A real run copies
    nothing, and used to create the new-named folder anyway — an EMPTY folder
    beside the old one, which the owner's hand rename then collides with."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        dest_root = tmp / "drive" / "_Photo_Manager"
        (tmp / "drive").mkdir()
        wd, sources, trip = build_dump(tmp, dest_root)
        old = dest_root / "20260708_old name"
        old.mkdir(parents=True)
        mark_verified(wd, sources, old)
        dry = run_execute(wd)
        r = run_execute(wd, "--go")
        if r.returncode != 0:
            return False, f"rc={r.returncode} {r.stderr.strip()[-200:]}"
        if "would create" in dry.stdout:
            return False, f"the dry run promised a folder: {dry.stdout.strip()[-200:]}"
        return not trip.exists(), f"created {trip.name} with {len(list(trip.iterdir())) if trip.exists() else 0} file(s)"


def a_file_copied_under_another_plan_number_is_not_copied_again():
    """FIX8 F8-2 (REPRODUCTION). A merge after a copy renumbers the plans, so
    the file P1 now holds was verified in execute-state_P2. On 99ca388 only
    P1's own state was read and the file was copied again (262 files on a
    real dump)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        dest_root = tmp / "drive" / "_Photo_Manager"
        (tmp / "drive").mkdir()
        wd, sources, trip = build_dump(tmp, dest_root)
        mark_verified(wd, sources, trip)
        state = wd / "plan" / "execute-state_P1.json"
        data = json.loads(state.read_text())
        data["plan"] = 2
        (wd / "plan" / "execute-state_P2.json").write_text(json.dumps(data))
        state.unlink()
        r = run_execute(wd, "--go")
        copied = sorted(p.name for p in trip.iterdir()) if trip.exists() else []
    return (r.returncode == 0 and "0 copied" in r.stdout and not copied), \
        f"rc={r.returncode} copied={copied} {r.stdout.strip()[-200:]}"


def a_new_file_waits_for_its_folder_rename():
    """FIX8 F8-2 (GUARD). A freeze listed a folder to rename; its old name is
    still on the drive. A file not yet copied would open the new name beside
    it, so the run refuses before any write, dry run and --go alike. Once the
    owner renames, it copies."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        dest_root = tmp / "drive" / "_Photo_Manager"
        (tmp / "drive").mkdir()
        wd, sources, trip = build_dump(tmp, dest_root)
        old = dest_root / "20260708_old name"
        old.mkdir(parents=True)
        plans = json.loads((wd / "plans.json").read_text())
        plans["renames"] = [{"old": old.name, "new": trip.name}]
        (wd / "plans.json").write_text(json.dumps(plans))
        dry = run_execute(wd)
        go = run_execute(wd, "--go")
        refused = (dry.returncode != 0 and go.returncode != 0
                   and "rename it by hand first" in go.stderr
                   and not trip.exists())
        old.rename(trip)
        after = run_execute(wd, "--go")
        landed = all((trip / s.name).is_file() for s in sources)
    return refused and after.returncode == 0 and landed, \
        f"refused={refused} after={after.returncode} landed={landed} {go.stderr.strip()[-200:]}"


def a_rename_blocks_a_windows_shaped_destination():
    """⭐ REPRODUCTION (RS4). On Windows the rename target was
    `str(Path(dest_root) / new)`, all backslashes, and every plan row's
    destination is photo_plan's `f"{dest_root}/{name}"`, so the two never
    matched: the block never fired and `--go` opened the new folder beside
    the old one. `Path` is swapped for PureWindowsPath around the one call,
    which is the join Windows does; the rows are the plan writer's shape."""
    from pathlib import PureWindowsPath
    root = "Z:\\_Photo_Manager"
    pending = [{"destination": f"{root}/20260708_trip"},
               {"destination": f"{root}/20260708_trip/1025_leg"}]
    saved = photo_execute.Path
    photo_execute.Path = PureWindowsPath
    try:
        got = photo_execute.blocked_renames([("20260708_old", "20260708_trip")],
                                            root, pending)
        other = photo_execute.blocked_renames([("x", "20260708_trip2")],
                                              root, pending)
    finally:
        photo_execute.Path = saved
    return got == [("20260708_old", "20260708_trip")] and other == [], \
        f"got={got} other={other}"


CASES = [free_space_walks_up_to_an_existing_ancestor,
         free_space_matches_the_existing_path_case,
         dry_run_survives_a_dest_root_that_does_not_exist,
         go_creates_the_dest_root_and_copies_verified,
         sources_are_never_touched,
         unreachable_destination_exits_with_a_message,
         go_creates_no_folder_that_receives_no_file,
         a_file_copied_under_another_plan_number_is_not_copied_again,
         a_new_file_waits_for_its_folder_rename,
         a_rename_blocks_a_windows_shaped_destination]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    failures = []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
        # A case that RAISES is a failure with a reason, not a crash that takes
        # the tally with it (LL-PHO-115).
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

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} photo_execute cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
