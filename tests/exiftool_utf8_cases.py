#!/usr/bin/env python3
"""Cases for photo_exiftool.run() — the UTF-8 argfile (OA-27).

exiftool.exe decodes argv through the Windows ANSI codepage, so a path whose
name is not representable there reaches it as `?` and is then read as a
wildcard: a folder that exists reports "No matching files". The engine had no
test that any path reaches exiftool intact, so the whole scan stage could be
unreachable on a machine and still replay green here.

Two halves, deliberately:
  * unit — the argfile really is UTF-8 bytes, the command really carries
    `-charset filename=UTF8 -@`, and the temp file is removed even when the
    call raises. Runs everywhere, exiftool or not.
  * end-to-end — photo_scan over a folder with a non-ASCII name finds the
    file inside it. Needs exiftool, and SKIPS loudly without it.

  python3 tests/exiftool_utf8_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_exiftool  # noqa: E402

# i18n-guard:allow-begin — locale detection data: the non-ASCII folder name IS
# the thing under test. A name representable in a Windows ANSI codepage would
# not reproduce the defect, so it has to be non-Latin; it is a generic word
# invented here, never a real folder from anyone's drive.
NON_ASCII_DIR = "測試資料夾"
# i18n-guard:allow-end

# The three names an argfile can swallow where argv could not. `#` opens a
# comment and leading whitespace is stripped, so the first two stop being
# arguments at all; the third is the control that says the fix did not just
# start trimming names to be safe.
HASH_DIR = "#hash"
LEAD_SPACE_DIR = " lead"
TRAIL_SPACE_DIR = "trail "

# An MP4 wearing a .HEIC name (ftyp isom + moov). Both of
# photo_rename_mismatches' passes flag this one file — exiftool by
# FileTypeExtension, the magic-byte pass by mime — and that overlap is what a
# mixed absolute/relative path space turns into a double rename. A plain
# QuickTime `ftypqt  ` box does NOT reproduce it: exiftool calls that one heic
# and the two passes never meet.
MP4_IN_HEIC_CLOTHING = (
    struct.pack(">I", 24) + b"ftyp" + b"isom" + struct.pack(">I", 0x200)
    + b"isom" + b"iso2" + struct.pack(">I", 8) + b"moov")

# 1x1 PNG, so the end-to-end case needs no image library and no real photo.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg==")

VERBOSE = False


def log(msg):
    if VERBOSE:
        print(f"  {msg}")


class FakeSubprocess:
    """Stands in for photo_exiftool's subprocess module so the call can be
    inspected without exiftool being installed."""

    def __init__(self, raise_with=None):
        self.raise_with = raise_with
        self.cmd = None
        self.kwargs = None
        self.argfile = None
        self.argfile_bytes = None

    def run(self, cmd, **kwargs):
        self.cmd, self.kwargs = list(cmd), kwargs
        self.argfile = Path(cmd[-1])
        self.argfile_bytes = self.argfile.read_bytes()
        if self.raise_with:
            raise self.raise_with
        return subprocess.CompletedProcess(cmd, 0, "", "")


def call_with_fake(options, paths, raise_with=None):
    fake = FakeSubprocess(raise_with)
    real = photo_exiftool.subprocess
    photo_exiftool.subprocess = fake
    try:
        photo_exiftool.run(options, paths)
    finally:
        photo_exiftool.subprocess = real
    return fake


@contextmanager
def in_dir(path):
    was = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(was)


def scan_names(path):
    """-> the FileName column exiftool reports for `path`, as a set."""
    proc = photo_exiftool.run(["-csv", "-FileName"], [path])
    return {line.split(",")[-1].strip()
            for line in proc.stdout.splitlines()[1:] if "," in line}


def case_argfile_carries_the_path_as_utf8():
    # The point is that the non-ASCII name reaches the argfile as UTF-8, so
    # build the expectation the way the launcher does rather than assuming a
    # POSIX root: an absolute path is `C:\...` on Windows, never `/tmp/...`.
    src = Path(tempfile.gettempdir()) / NON_ASCII_DIR
    fake = call_with_fake(["-csv"], [str(src)])
    want = f"-csv\n{src.absolute()}\n".encode("utf-8")
    log(f"argfile bytes: {fake.argfile_bytes!r}")
    assert fake.argfile_bytes == want, f"argfile is {fake.argfile_bytes!r}"


def case_command_declares_the_charset_and_the_argfile():
    fake = call_with_fake(["-csv"], ["/tmp/x"])
    log(f"cmd: {fake.cmd}")
    assert fake.cmd[:4] == ["exiftool", "-charset", "filename=UTF8", "-@"], \
        f"cmd starts {fake.cmd[:4]}"
    assert len(fake.cmd) == 5, f"cmd has {len(fake.cmd)} tokens"


def case_output_is_decoded_as_utf8_not_the_locale():
    """text=True would decode exiftool's answer with the locale encoding —
    cp950/cp1252 on Windows — and mojibake the SourceFile column even after a
    successful scan."""
    fake = call_with_fake(["-csv"], ["/tmp/x"])
    log(f"kwargs: {fake.kwargs}")
    assert fake.kwargs.get("encoding") == "utf-8", fake.kwargs
    assert fake.kwargs.get("errors"), "no errors= policy set"
    assert not fake.kwargs.get("text"), "text=True still set"


def case_argfile_is_removed_after_a_normal_call():
    fake = call_with_fake(["-csv"], ["/tmp/x"])
    assert not fake.argfile.exists(), f"left behind: {fake.argfile}"


def case_argfile_is_removed_when_exiftool_is_missing():
    fake = FakeSubprocess(FileNotFoundError("exiftool"))
    real = photo_exiftool.subprocess
    photo_exiftool.subprocess = fake
    try:
        photo_exiftool.run(["-csv"], ["/tmp/x"])
        raise AssertionError("FileNotFoundError did not propagate")
    except FileNotFoundError:
        pass
    finally:
        photo_exiftool.subprocess = real
    assert not fake.argfile.exists(), f"left behind: {fake.argfile}"


def case_a_relative_path_is_absolutised():
    """The line has to start with a separator: that is what stops `#drafts`
    from opening a comment and ` inbox` from being whitespace-stripped."""
    with in_dir(tempfile.gettempdir()):
        fake = call_with_fake(["-csv"], [HASH_DIR])
    line = fake.argfile_bytes.decode("utf-8").splitlines()[-1]
    log(f"path line: {line!r}")
    assert os.path.isabs(line), f"not absolutised: {line!r}"
    assert line.endswith(HASH_DIR), f"name mangled: {line!r}"


def case_a_run_with_no_surviving_path_is_refused():
    """The net: given a path list that produces no usable line, exiftool would
    be handed options only — and would then read the working directory, or
    print its own manual to stdout, at exit 0. Refuse instead."""
    try:
        call_with_fake(["-csv"], ["  "])
        raise AssertionError("empty path was accepted")
    except ValueError as e:
        log(f"refused: {e}")


def case_a_run_with_no_paths_at_all_is_allowed():
    """Only a caller that asked for paths and lost them is refused."""
    fake = call_with_fake(["-ver"], [])
    assert fake.argfile_bytes == b"-ver\n", f"argfile is {fake.argfile_bytes!r}"


def case_scan_finds_a_file_under_a_non_ascii_folder(tmp):
    src = tmp / NON_ASCII_DIR
    src.mkdir()
    (src / "sample.png").write_bytes(PNG_1X1)
    workdir = tmp / "work"
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "photo_scan.py"), str(src),
         "--workdir", str(workdir)],
        capture_output=True, encoding="utf-8", errors="replace")
    log(f"photo_scan stderr: {proc.stderr.strip()[:200]}")
    assert proc.returncode == 0, f"photo_scan exited {proc.returncode}"
    summary = json.loads((workdir / "scan-summary.json")
                         .read_text(encoding="utf-8"))
    assert summary["main_files"] == 1, f"main_files={summary['main_files']}"
    manifest = (workdir / "manifest.csv").read_text(encoding="utf-8")
    assert NON_ASCII_DIR in manifest, "the folder name did not survive"
    assert "sample.png" in manifest, "the file was not scanned"


def case_a_hash_leading_folder_is_not_read_as_a_comment(tmp):
    """The dangerous one. `#hash` on its own line is a comment, so exiftool
    gets no file argument at all — and then prints its man page to stdout at
    exit 0. Run from a directory stocked with decoys: the folder's own file
    must be found, and no decoy may appear, which together say the reported
    names came from the folder that was asked for and nowhere else."""
    (tmp / "decoy_one.png").write_bytes(PNG_1X1)
    (tmp / "decoy_two.png").write_bytes(PNG_1X1)
    target = tmp / HASH_DIR
    target.mkdir()
    (target / "sample.png").write_bytes(PNG_1X1)
    with in_dir(tmp):
        names = scan_names(HASH_DIR)
    log(f"reported: {sorted(names)}")
    assert "sample.png" in names, f"the folder was not scanned: {sorted(names)}"
    assert not {"decoy_one.png", "decoy_two.png"} & names, \
        f"reported files the requested folder does not hold: {sorted(names)}"


def case_a_leading_space_folder_survives(tmp):
    """exiftool strips leading whitespace from an argfile line, so ` lead`
    arrives as `lead` and is not found."""
    target = tmp / LEAD_SPACE_DIR
    target.mkdir()
    (target / "sample.png").write_bytes(PNG_1X1)
    with in_dir(tmp):
        names = scan_names(LEAD_SPACE_DIR)
    assert "sample.png" in names, f"the folder was not scanned: {sorted(names)}"


def case_a_trailing_space_folder_still_works(tmp):
    """The control: a trailing space is legal and was never the problem, so
    the fix must not have started trimming names to be safe."""
    target = tmp / TRAIL_SPACE_DIR
    target.mkdir()
    (target / "sample.png").write_bytes(PNG_1X1)
    with in_dir(tmp):
        names = scan_names(TRAIL_SPACE_DIR)
    assert "sample.png" in names, f"the folder was not scanned: {sorted(names)}"


def rename_mismatches(root, *extra, cwd):
    with in_dir(cwd):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "photo_rename_mismatches.py"),
             root, *extra],
            capture_output=True, encoding="utf-8", errors="replace")


def case_rename_mismatches_reports_a_relative_root_file_once(tmp):
    """Absolutising the exiftool argument put scan_root's paths in a different
    space from magic_check_heic's rglob, so with a RELATIVE root one physical
    file was reported by both passes and counted twice."""
    dest = tmp / "dest"
    dest.mkdir()
    (dest / "clip.HEIC").write_bytes(MP4_IN_HEIC_CLOTHING)
    proc = rename_mismatches("dest", cwd=tmp)
    log(proc.stdout.strip())
    assert proc.returncode == 0, f"exited {proc.returncode}: {proc.stderr[:300]}"
    assert "1 mismatched file(s) found" in proc.stdout, proc.stdout[:300]
    assert proc.stdout.count("would rename") == 1, \
        f"reported {proc.stdout.count('would rename')} times, want 1"


def case_rename_mismatches_go_completes_from_a_relative_root(tmp):
    """The double report was not only noise: the second entry renamed a file
    the first had already moved, so --go died mid-batch with FileNotFoundError
    after the collision guard escalated it to a _dup2 name."""
    dest = tmp / "dest"
    dest.mkdir()
    (dest / "clip.HEIC").write_bytes(MP4_IN_HEIC_CLOTHING)
    proc = rename_mismatches("dest", "--go", cwd=tmp)
    log(proc.stderr.strip()[-200:] or proc.stdout.strip())
    assert proc.returncode == 0, f"exited {proc.returncode}: {proc.stderr[-300:]}"
    assert "Traceback" not in proc.stderr, proc.stderr[-300:]
    after = sorted(p.name for p in dest.iterdir())
    assert after == ["clip.MP4"], f"left {after}"


def case_rename_mismatches_checks_a_split_piece_and_a_folder_still_to_rename(tmp):
    """⭐ REPRODUCTION (M2, UAT01-9 F11b / UAT01-10 F3). ⛔ FAILS on 4739665:
    `--plans` read each plan's `dest` only, so a split piece (an override's
    folder) was never checked, and a folder a freeze renamed after its copy
    was looked for under its NEW name — not on the drive yet — and skipped.
    Both are checked now, the second under its old name, and the pass says
    so. Dry run: nothing is renamed."""
    root = tmp / "sorted"
    (root / "20240101_Old").mkdir(parents=True)
    (root / "20240102_Piece").mkdir()
    (root / "20240101_Old" / "a.HEIC").write_bytes(MP4_IN_HEIC_CLOTHING)
    (root / "20240102_Piece" / "b.HEIC").write_bytes(MP4_IN_HEIC_CLOTHING)
    plans = tmp / "plans.json"
    plans.write_text(json.dumps({"dest_root": str(root), "renames": [
        {"old": "20240101_Old", "new": "20240101_New"}], "plans": [
        {"plan": 1, "batches": [1],
         "dest": {"mode": "new", "path": str(root / "20240101_New")},
         "overrides": [{"dates": ["2024-01-02"],
                        "dest": str(root / "20240102_Piece")}]}]}))
    proc = rename_mismatches("--plans", str(plans), cwd=tmp)
    assert proc.returncode == 0, f"exited {proc.returncode}: {proc.stderr[-300:]}"
    assert "2 mismatched file(s) found" in proc.stdout, proc.stdout + proc.stderr
    assert "checking 20240101_Old under its old name" in proc.stderr, proc.stderr
    assert sorted(p.name for p in root.rglob("*.HEIC")) == ["a.HEIC", "b.HEIC"]


UNIT_CASES = [
    ("the argfile holds the path as UTF-8 bytes",
     case_argfile_carries_the_path_as_utf8),
    ("the command is exiftool -charset filename=UTF8 -@ <argfile>",
     case_command_declares_the_charset_and_the_argfile),
    ("output is decoded as UTF-8, never the locale encoding",
     case_output_is_decoded_as_utf8_not_the_locale),
    ("the argfile is removed after the call",
     case_argfile_is_removed_after_a_normal_call),
    ("the argfile is removed when exiftool is not on PATH",
     case_argfile_is_removed_when_exiftool_is_missing),
    ("a relative path is absolutised before it reaches the argfile",
     case_a_relative_path_is_absolutised),
    ("a run whose paths all vanish is refused, not sent",
     case_a_run_with_no_surviving_path_is_refused),
    ("a run that asked for no paths is still allowed",
     case_a_run_with_no_paths_at_all_is_allowed),
]

TMP_CASES = [
    ("photo_scan finds a file under a non-ASCII folder name",
     case_scan_finds_a_file_under_a_non_ascii_folder),
    ("a '#'-leading folder is scanned, not swallowed as a comment",
     case_a_hash_leading_folder_is_not_read_as_a_comment),
    ("a leading-space folder is scanned",
     case_a_leading_space_folder_survives),
    ("a trailing-space folder is scanned (no over-trimming)",
     case_a_trailing_space_folder_still_works),
    ("photo_rename_mismatches reports a relative-root file once",
     case_rename_mismatches_reports_a_relative_root_file_once),
    ("photo_rename_mismatches --go completes from a relative root",
     case_rename_mismatches_go_completes_from_a_relative_root),
    ("photo_rename_mismatches checks a split piece and a folder still to "
     "rename (REPRODUCTION, M2)",
     case_rename_mismatches_checks_a_split_piece_and_a_folder_still_to_rename),
]


# Cases whose FIXTURE cannot exist off POSIX — not features we decline to test.
POSIX_ONLY_CASES = {
    "a trailing-space folder is scanned (no over-trimming)":
        "Windows strips a trailing space from a directory name, so the "
        "fixture cannot be created and there is no over-trimming to test",
}


def run_case(name, fn):
    try:
        fn()
        print(f"  ok    {name}")
        return True
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        return False
    except Exception as e:
        # Anything other than an AssertionError used to escape main() and end
        # the run with no tally at all, hiding every case after it.
        print(f"  ERROR {name}: {type(e).__name__}: {e}")
        return False


def main():
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    passed = total = skipped = 0
    for name, fn in UNIT_CASES:
        passed += 1 if run_case(name, fn) else 0
        total += 1

    have_exiftool = shutil.which("exiftool") is not None
    for name, fn in TMP_CASES:
        if not have_exiftool:
            print(f"  SKIP  {name}: exiftool not on PATH")
            skipped += 1
            continue
        if name in POSIX_ONLY_CASES and os.name != "posix":
            print(f"  SKIP  {name}: {POSIX_ONLY_CASES[name]}")
            skipped += 1
            continue
        tmp = Path(tempfile.mkdtemp(prefix="exiftool_utf8_test_"))
        try:
            ok = run_case(name, lambda: fn(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        passed += 1 if ok else 0
        total += 1

    # Denominator counts every DECLARED case, not just the ones that ran: a
    # platform that skipped six would otherwise print "8/8", which reads as
    # full coverage. The exit code still turns only on what actually ran.
    tail = f", {skipped} SKIPPED" if skipped else ""
    print(f"\n{passed}/{total + skipped} exiftool utf8 cases passed{tail}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
