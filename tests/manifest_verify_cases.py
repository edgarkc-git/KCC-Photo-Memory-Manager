#!/usr/bin/env python3
"""Cases for `photo_scan --verify` — the manifest staleness check (A41) — and
for the count honesty the summary and the verify report both rest on (U2-14).

Every case builds a real directory tree in a temp dir and a manifest that
points into it, then moves or deletes files underneath. Real files rather than
mocks because the thing under test IS the filesystem question "is it still
there?", and a mocked `exists()` would assert only that the mock was called.

The case that matters is `moved`: the owner re-splits a trip folder into leg
sub-folders, every recorded path stops resolving, and the files are all still
on the disk one level down. A checker that reports that as data loss is worse
than no checker, because it invites a re-scan nobody needed.

The U2-14 cases test a different failure with the same shape: a number that is
correct and unfalsifiable. Both stages exclude file classes that are not media,
correctly — and neither used to say so, so the owner's only outside check,
counting the folder, disagreed with the report for an unstated reason.

  python3 tests/manifest_verify_cases.py [-v]

Exit 0 = pass. No owner data is read; every tree is written out here.
"""

import argparse
import contextlib
import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "scripts" / "photo_scan.py"

FIELDS = ["SourceFile", "FileName", "FileType", "FileSize", "DateTimeOriginal",
          "CreateDate", "GPSPosition", "Make", "Model", "Software",
          "ImageWidth", "ImageHeight", "Duration", "UserComment"]


def write_manifest(workdir, files):
    """files: [(path, size)] — the manifest as it was when the drive was scanned."""
    workdir.mkdir(parents=True, exist_ok=True)
    with open(workdir / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for path, size in files:
            row = {k: "-" for k in FIELDS}
            row.update({"SourceFile": str(path), "FileName": Path(path).name,
                        "FileType": "JPEG", "FileSize": str(size)})
            w.writerow(row)


def make(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def run_verify(workdir):
    r = subprocess.run([sys.executable, str(SCAN), "--verify",
                        "--workdir", str(workdir)],
                       capture_output=True, text=True)
    report = workdir / "manifest-verify.json"
    data = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
    return r.returncode, data, r.stderr


def run_verify_out(workdir):
    """As run_verify, but hands back stdout — the channel the operator reads,
    and the one the bare `N of N` ratio was printed on."""
    r = subprocess.run([sys.executable, str(SCAN), "--verify",
                        "--workdir", str(workdir)],
                       capture_output=True, text=True)
    return r.stdout


# --------------------------------------------------------------- the cases

def case_all_present(tmp):
    """Nothing moved: every row resolves, and the report says so."""
    src = tmp / "Volumes" / "DISK" / "trip"
    files = [(make(src / f"IMG_{i}.JPG", 100 + i), 100 + i) for i in range(3)]
    wd = tmp / "work"
    write_manifest(wd, files)
    _, d, _ = run_verify(wd)
    assert d["counts"] == {"present": 3, "moved": 0, "ambiguous": 0, "gone": 0}, d["counts"]
    assert d["stale_pct"] == 0.0, d["stale_pct"]


def case_resplit_into_subfolders(tmp):
    """The A41 case that was measured on real data: a trip folder is re-split
    into leg sub-folders, so every recorded path breaks at once while every
    file is still on the disk. All rows must come back `moved`, each with the
    path it actually sits at now — not `gone`."""
    src = tmp / "Volumes" / "DISK" / "trip"
    files = [(src / f"IMG_{i}.JPG", 100 + i) for i in range(4)]
    for p, s in files:
        make(p, s)
    wd = tmp / "work"
    write_manifest(wd, files)
    for i, (p, _) in enumerate(files):                    # the owner re-splits
        leg = src / ("leg_a" if i < 2 else "leg_b")
        leg.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(leg / p.name))
    _, d, _ = run_verify(wd)
    assert d["counts"]["moved"] == 4, d["counts"]
    assert d["counts"]["gone"] == 0, d["counts"]
    assert d["stale_pct"] == 100.0, d["stale_pct"]
    for m in d["moved"]:
        assert Path(m["found_at"]).exists(), m
        assert Path(m["found_at"]).name == Path(m["source"]).name, m


def case_renamed_parent(tmp):
    """A folder renamed on the drive — the same break, one level up."""
    src = tmp / "Volumes" / "DISK" / "2025 trip"
    files = [(make(src / f"IMG_{i}.JPG", 200 + i), 200 + i) for i in range(2)]
    wd = tmp / "work"
    write_manifest(wd, files)
    src.rename(src.parent / "2025_trip")
    _, d, _ = run_verify(wd)
    assert d["counts"]["moved"] == 2, d["counts"]


def case_deleted_is_gone(tmp):
    """A file the owner actually deleted is `gone`, never `moved`. `moved`
    claims a file was found; it must not be reachable without one."""
    src = tmp / "Volumes" / "DISK" / "trip"
    files = [(make(src / f"IMG_{i}.JPG", 300 + i), 300 + i) for i in range(3)]
    wd = tmp / "work"
    write_manifest(wd, files)
    files[1][0].unlink()
    _, d, _ = run_verify(wd)
    assert d["counts"] == {"present": 2, "moved": 0, "ambiguous": 0, "gone": 1}, d["counts"]
    assert d["gone"][0]["found_at"] is None, d["gone"]


def case_size_discriminates_same_name(tmp):
    """Two files share a name; only one shares the recorded byte count. The
    name alone would make this ambiguous, and the size settles it — which is
    why the size is matched at all."""
    src = tmp / "Volumes" / "DISK" / "trip"
    original = make(src / "IMG_1.JPG", 500)
    wd = tmp / "work"
    write_manifest(wd, [(original, 500)])
    make(src / "other" / "IMG_1.JPG", 999)                # decoy: same name
    (src / "leg").mkdir(parents=True, exist_ok=True)
    shutil.move(str(original), str(src / "leg" / "IMG_1.JPG"))
    _, d, _ = run_verify(wd)
    assert d["counts"]["moved"] == 1, d["counts"]
    assert "leg" in d["moved"][0]["found_at"], d["moved"]


def case_ambiguous_is_not_moved(tmp):
    """Same name AND same size in two places: the checker cannot tell which,
    and must say `ambiguous` rather than pick one. A wrong `moved` would be
    reported to the owner as a located file."""
    src = tmp / "Volumes" / "DISK" / "trip"
    original = make(src / "IMG_1.JPG", 500)
    wd = tmp / "work"
    write_manifest(wd, [(original, 500)])
    make(src / "copy_a" / "IMG_1.JPG", 500)
    make(src / "copy_b" / "IMG_1.JPG", 500)
    original.unlink()
    _, d, _ = run_verify(wd)
    assert d["counts"]["ambiguous"] == 1, d["counts"]
    assert d["counts"]["moved"] == 0, d["counts"]


def case_unmounted_drive_stops(tmp):
    """Pitfall 4. An unmounted drive makes every row unreadable, and reporting
    that as 100% data loss is the most misleading thing this stage could say.
    It must refuse to report instead — non-zero exit, no report written."""
    wd = tmp / "work"
    write_manifest(wd, [(Path("/Volumes/NOT_MOUNTED_XYZ/trip/IMG_1.JPG"), 100)])
    rc, d, err = run_verify(wd)
    assert rc != 0, rc
    assert d is None, "a report was written for an unreachable drive"
    assert "mounted" in err.lower(), err


def case_appledouble_not_offered_as_match(tmp):
    """`._*` sidecars are excluded at scan (photo_scan.py, since bd1a3b2), so
    the index must not offer one as a candidate either — a stale manifest from
    before that fix carries `._` rows, and matching them would report a
    metadata sidecar as the owner's recovered photo."""
    src = tmp / "Volumes" / "DISK" / "trip"
    wd = tmp / "work"
    write_manifest(wd, [(src / "._IMG_1.JPG", 4096)])
    make(src / "leg" / "._IMG_1.JPG", 4096)
    _, d, _ = run_verify(wd)
    assert d["counts"]["gone"] == 1, d["counts"]


def case_excluded_sidecars_are_counted_not_just_skipped(tmp):
    """U2-14. The verdict counts are derived from the manifest, so `present`
    and `rows` agree with each other whatever the drive holds — `3 of 3` is
    printed just the same on a folder Finder says holds 5 entries. The two
    extra entries here are `._*` sidecars, correctly excluded at scan and
    correctly excluded from this index; what was missing is any statement that
    they exist, which left the owner's only independent check (count the
    folder) disagreeing with the report for a reason the report never gave.

    The exclusion must stay. The silence must not."""
    src = tmp / "Volumes" / "DISK" / "trip"
    files = [(make(src / f"IMG_{i}.JPG", 100 + i), 100 + i) for i in range(3)]
    make(src / "._IMG_0.JPG", 4096)
    make(src / "._IMG_1.JPG", 4096)
    wd = tmp / "work"
    write_manifest(wd, files)
    _, d, _ = run_verify(wd)
    assert d["counts"]["present"] == 3, d["counts"]
    idx = d.get("indexed")
    assert idx is not None, "the report does not say what it counted"
    assert idx["excluded"]["appledouble"] == 2, idx
    assert idx["files"] == 3, idx
    # The arithmetic the owner can check against a folder listing.
    assert idx["entries_under_roots"] == 5, idx


def case_the_ratio_explains_itself_on_a_clean_run(tmp):
    """U2-14, the operator's channel. The report file is only opened by
    someone already suspicious; the number that reassures is the one printed
    on a run where nothing is wrong. That line said `N of N` and nothing else,
    so it could not be reconciled with a folder listing — and the stale branch
    that did explain itself only fires when something IS wrong, which is the
    run nobody needed convincing on."""
    src = tmp / "Volumes" / "DISK" / "trip"
    files = [(make(src / f"IMG_{i}.JPG", 400 + i), 400 + i) for i in range(2)]
    make(src / "._IMG_0.JPG", 4096)
    wd = tmp / "work"
    write_manifest(wd, files)
    out = run_verify_out(wd)
    assert "2 of 2" in out, out
    assert "AppleDouble" in out, f"the ratio names no exclusion:\n{out}"
    assert "MEDIA rows" in out, f"the ratio does not name its unit:\n{out}"


def case_verify_still_writes_nothing_but_its_report(tmp):
    """A guard, not a reproduction. --verify is REPORT-ONLY: making the count
    self-explaining must not have turned it into something that re-scans or
    repairs. Regenerating a manifest reflows batches.json, so the manifest's
    bytes and the absence of a scan-summary are both part of the contract."""
    src = tmp / "Volumes" / "DISK" / "trip"
    files = [(make(src / f"IMG_{i}.JPG", 800 + i), 800 + i) for i in range(3)]
    make(src / "._IMG_0.JPG", 4096)
    wd = tmp / "work"
    write_manifest(wd, files)
    before = (wd / "manifest.csv").read_bytes()
    run_verify(wd)
    assert (wd / "manifest.csv").read_bytes() == before, "the manifest was rewritten"
    assert not (wd / "scan-summary.json").exists(), "--verify re-scanned"
    assert sorted(p.name for p in wd.iterdir()) == \
        ["manifest-verify.json", "manifest.csv"], sorted(p.name for p in wd.iterdir())


def case_scan_summary_arithmetic_closes(tmp):
    """U2-14 at the scan end, through photo_scan's REAL counting loop — the
    loop lives in main() and needs exiftool, so exiftool is replaced by a
    function returning a CSV this case wrote. The rows are synthetic; the code
    under test is not.

    `aae_ignored` was the only exclusion the summary named, so on a dump
    carrying `._*` sidecars `total_files_seen` exceeded
    `main_files + aae_ignored` by a number nothing accounted for. The owner
    checking the summary against a Finder count found a shortfall the summary
    could not explain — indistinguishable, from outside, from lost photos.
    The identity has to close, and it has to close on a fixture where the
    unnamed term is non-zero or the case is asleep."""
    csv_text = (
        "SourceFile,DateTimeOriginal,GPSPosition,FileType\n"
        "/raw/a.jpg,2024:01:01 10:00:00,23.5 120.5,JPEG\n"
        "/raw/b.jpg,2024:01:01 11:00:00,23.6 120.6,JPEG\n"
        "/raw/._a.jpg,-,-,JPEG\n"
        "/raw/._b.jpg,-,-,JPEG\n"
        "/raw/._c.jpg,-,-,JPEG\n"
        "/raw/c.aae,-,-,AAE\n")
    sys.path.insert(0, str(ROOT / "scripts"))
    import photo_scan
    real, argv = photo_scan.run_exiftool, sys.argv
    source, workdir = tmp / "dump", tmp / "work"
    source.mkdir(parents=True)
    try:
        photo_scan.run_exiftool = lambda source, recursive: (csv_text, "")
        sys.argv = ["photo_scan.py", str(source), "--workdir", str(workdir)]
        with contextlib.redirect_stdout(io.StringIO()):
            photo_scan.main()
    finally:
        photo_scan.run_exiftool, sys.argv = real, argv

    s = json.loads((workdir / "scan-summary.json").read_text())
    assert "appledouble_ignored" in s, f"the summary names no such exclusion: {s}"
    assert s["appledouble_ignored"] == 3, s
    assert s["main_files"] == 2 and s["aae_ignored"] == 1, s
    assert s["total_files_seen"] == 6, s
    assert (s["main_files"] + s["aae_ignored"] + s["appledouble_ignored"]
            == s["total_files_seen"]), s
    manifest = list(csv.DictReader(
        open(workdir / "manifest.csv", newline="", encoding="utf-8")))
    assert all(not Path(r["SourceFile"]).name.startswith("._")
               for r in manifest), "a sidecar reached the manifest"


def scan_with(tmp, csv_text, files, recursive=True):
    """Run photo_scan's real main() over a real folder holding `files`, with
    exiftool replaced by a function returning `csv_text`. -> (rc, work dir)."""
    source, workdir = tmp / "dump", tmp / "work"
    for name in files:
        make(source / name, 10)
    source.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "scripts"))
    import photo_scan
    real, argv = photo_scan.run_exiftool, sys.argv
    try:
        photo_scan.run_exiftool = lambda source, recursive: (csv_text, "")
        sys.argv = ["photo_scan.py", str(source), "--workdir", str(workdir)]
        if not recursive:
            sys.argv.append("--no-recursive")
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            rc = photo_scan.main()
    finally:
        photo_scan.run_exiftool, sys.argv = real, argv
    return rc, workdir, err.getvalue()


def case_partial_scan_stops_and_writes_no_manifest(tmp):
    """REPRODUCTION (F04). ⛔ FAILS on 5b320fb: exiftool read 1 of the 3
    photos the folder lists, the scan wrote a 1-row manifest and exited 0, and
    prep went on to the census as if the dump held one photo."""
    rc, wd, err = scan_with(
        tmp, "SourceFile,FileType\n/x/dump/IMG_1.JPG,JPEG\n",
        ["IMG_1.JPG", "IMG_2.HEIC", "sub/IMG_3.MOV"])
    assert rc not in (0, None), f"exit {rc}"
    assert not (wd / "manifest.csv").exists(), "a partial manifest was written"
    s = json.loads((wd / "scan-summary.json").read_text(encoding="utf-8"))
    assert s["media_files_in_folder"] == 3 and s["media_files_not_read"] == 2, s
    assert s["not_read"] == ["img_2.heic", "img_3.mov"], s
    assert "2 were not read" in err and "local disk" in err, err


def case_full_scan_is_not_stopped(tmp):
    """GUARD. Everything the folder lists was read: sidecars, `._*` files,
    non-media files and dot-directories are not counted as missing."""
    rc, wd, _ = scan_with(
        tmp,
        "SourceFile,FileType\n/x/dump/IMG_1.JPG,JPEG\n"
        "/x/dump/sub/img_2.mov,MOV\n/x/dump/IMG_1.AAE,AAE\n",
        ["IMG_1.JPG", "sub/img_2.mov", "IMG_1.AAE", "._IMG_1.JPG",
         "notes.txt", ".hidden/IMG_9.JPG"])
    assert rc in (0, None), f"exit {rc}"
    assert (wd / "manifest.csv").exists()


def case_no_recursive_counts_the_top_level_only(tmp):
    """GUARD. With --no-recursive exiftool reads the top level only, so the
    folder count must not expect the sub-folder's files."""
    rc, wd, _ = scan_with(
        tmp, "SourceFile,FileType\n/x/dump/IMG_1.JPG,JPEG\n",
        ["IMG_1.JPG", "sub/IMG_2.JPG"], recursive=False)
    assert rc in (0, None), f"exit {rc}"


def case_census_refuses_after_a_partial_scan(tmp):
    """REPRODUCTION (F04). ⛔ FAILS on 5b320fb: a manifest left by an earlier
    scan sat beside a scan that stopped short, and the census read it."""
    wd = tmp / "work"
    write_manifest(wd, [(tmp / "IMG_1.JPG", 10)])
    (wd / "scan-summary.json").write_text(json.dumps(
        {"media_files_in_folder": 3, "media_files_not_read": 2}))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "photo_census.py"),
                        str(wd)], capture_output=True, text=True)
    assert r.returncode != 0, (r.returncode, r.stdout[-300:])
    assert "did not read 2" in r.stderr, r.stderr


def case_empty_manifest_stops(tmp):
    """A header-only manifest divides by zero on stale_pct if waved through."""
    wd = tmp / "work"
    write_manifest(wd, [])
    rc, d, err = run_verify(wd)
    assert rc != 0, rc
    assert d is None, d


def case_report_is_written_not_printed(tmp):
    """The actionable rows go to a file. A 6,000-row finding printed to a
    terminal is a finding nobody reads."""
    src = tmp / "Volumes" / "DISK" / "trip"
    files = [(make(src / f"IMG_{i}.JPG", 700 + i), 700 + i) for i in range(2)]
    wd = tmp / "work"
    write_manifest(wd, files)
    (src / "leg").mkdir(parents=True, exist_ok=True)
    shutil.move(str(files[0][0]), str(src / "leg" / files[0][0].name))
    _, d, _ = run_verify(wd)
    assert (wd / "manifest-verify.json").exists()
    assert d["manifest"].endswith("manifest.csv")
    assert d["verified_at"], d


CASES = [v for k, v in sorted(globals().items()) if k.startswith("case_")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failures = []
    for fn in CASES:
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
                if args.verbose:
                    print(f"  ok   {fn.__name__}")
            except AssertionError as e:
                failures.append((fn.__name__, str(e)))
                print(f"  FAIL {fn.__name__}: {e}")
            except Exception as e:                        # noqa: BLE001
                failures.append((fn.__name__, repr(e)))
                print(f"  ERROR {fn.__name__}: {e!r}")
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} manifest-verify cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
