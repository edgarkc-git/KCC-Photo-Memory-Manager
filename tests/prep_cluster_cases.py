#!/usr/bin/env python3
"""G4 cases — a first dump is clustered AFTER onboarding (D-I1).

`photo_run.py prep` scans and clusters in one go. On a first dump the owner's
homes are not in the pack yet, so every home day is geocoded as an ordinary
place and named after the map's district, and its day centroid is sent to the
geocoder (measured on a real dump: 75 of 119 lookups within 3 km of a home).
`prep --no-cluster` scans and runs the census only; `cluster` runs the
clustering once onboarding has written the pack. `prep` with no flag is
unchanged.

  python3 tests/prep_cluster_cases.py [-v]

Exit 0 = pass. Every fixture is a temp dir; the conductor's `run()` is a
recorder, so no stage subprocess runs and nothing is scanned.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import photo_profile  # noqa: E402
import photo_run  # noqa: E402

TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"
OWNER = "fixture-owner"

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


class Args:
    def __init__(self, source=None, root=None, workdir=None, no_cluster=None,
                 force=False, profile=None):
        self.source = str(source) if source else None
        self.workdir = str(workdir) if workdir else None
        self.workdir_root = str(root) if root else None
        self.force = force
        self.no_recursive = False
        self.profile = profile
        if no_cluster is not None:
            self.no_cluster = no_cluster


@contextlib.contextmanager
def conductor():
    """A recorded `run()`, no preflight network or preview probe, a clean pack cache and
    PHOTO_PROFILE restored afterwards."""
    calls = []

    def record(script, *a):
        calls.append((script, [str(x) for x in a]))
        return subprocess.CompletedProcess([script], 0)

    real = (photo_run.run, photo_run.preflight, photo_run.preview_check)
    saved_env = os.environ.pop(photo_profile.ENV_VAR, None)
    photo_run.run, photo_run.preflight = record, lambda: None
    photo_run.preview_check = lambda: None
    photo_run._pack_cache.clear()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            yield calls, buf
    finally:
        photo_run.run, photo_run.preflight, photo_run.preview_check = real
        photo_run._pack_cache.clear()
        os.environ.pop(photo_profile.ENV_VAR, None)
        if saved_env is not None:
            os.environ[photo_profile.ENV_VAR] = saved_env


def make_pack(root):
    pack = Path(root) / "photo-memory" / OWNER
    shutil.copytree(TEMPLATE, pack)
    for path in list(pack.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", OWNER)))
    prof = pack / photo_profile.PROFILE_NAME
    prof.write_text(prof.read_text(encoding="utf-8").replace("{{SLUG}}", OWNER)
                    .replace("{{DISPLAY}}", OWNER), encoding="utf-8")
    return pack


def scanned(root, bind=False):
    """A work dir holding a manifest and nothing clustered. -> (work dir, pack)."""
    wd = Path(root) / "Working Files" / "dump-a"
    wd.mkdir(parents=True)
    (wd / "manifest.csv").write_text("SourceFile,FileName\n", encoding="utf-8")
    pack = make_pack(root)
    coll = {"collection": "fixture"}
    if bind:
        coll.update(owner=OWNER, memory_root=str(pack.parent))
    (wd.parent / "collection.json").write_text(json.dumps(coll), encoding="utf-8")
    return wd, pack


def prep(no_cluster):
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "raw" / "dump-a"
        source.mkdir(parents=True)
        root = Path(tmp) / "Working Files"
        root.mkdir()
        with conductor() as (calls, buf):
            photo_run.cmd_prep(Args(source=source, root=root, no_cluster=no_cluster))
        return calls, buf.getvalue(), str(root / "dump-a")


@case
def prep_no_cluster_scans_and_runs_the_census_but_never_clusters():
    """REPRODUCTION. ⛔ FAILS on 5cc7e1d: prep always clustered, so a first
    dump was cut and geocoded before the owner's homes existed (U5-02)."""
    calls, out, wd = prep(no_cluster=True)
    return ([c[0] for c in calls] == ["photo_scan.py", "photo_census.py"]
            and calls[1][1] == [wd] and "photo_run.py cluster" in out), \
        f"calls={calls} out={out[-200:]!r}"


@case
def prep_without_the_flag_is_as_before():
    """GUARD. ⛔ R1: `prep` with no flag runs scan, cluster, census, with the
    same arguments, as it always did — returning owners and goldens rely on it."""
    calls, _out, wd = prep(no_cluster=None)
    return ([c[0] for c in calls] == ["photo_scan.py", "photo_cluster.py",
                                      "photo_census.py"]
            and calls[1][1] == [wd] and calls[2][1] == [wd]), f"calls={calls}"


@case
def prep_stops_when_the_scan_reads_fewer_files_than_the_folder_holds():
    """REPRODUCTION (F04). ⛔ FAILS on 5b320fb: the REAL photo_scan, with
    exiftool reading 0 of 2 photos (as the SMB share did), exited 0, and prep
    ran the census and printed "next: onboarding"."""
    import photo_scan
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "raw" / "dump-a"
        source.mkdir(parents=True)
        for name in ("IMG_1.JPG", "IMG_2.HEIC"):
            (source / name).write_bytes(b"x")
        root = Path(tmp) / "Working Files"
        root.mkdir()
        real = photo_scan.run_exiftool
        photo_scan.run_exiftool = lambda source, recursive: ("SourceFile\n", "")
        stopped = None
        try:
            with conductor() as (calls, buf):
                def scan_for_real(script, *a):
                    calls.append((script, [str(x) for x in a]))
                    if script != "photo_scan.py":
                        return subprocess.CompletedProcess([script], 0)
                    argv = sys.argv
                    sys.argv = [script, *[str(x) for x in a]]
                    try:
                        with contextlib.redirect_stderr(io.StringIO()):
                            rc = photo_scan.main()
                    finally:
                        sys.argv = argv
                    return subprocess.CompletedProcess([script], rc or 0)
                photo_run.run = scan_for_real
                try:
                    photo_run.cmd_prep(Args(source=source, root=root,
                                            no_cluster=True))
                except SystemExit as e:
                    stopped = str(e.code)
        finally:
            photo_scan.run_exiftool = real
    return ([c[0] for c in calls] == ["photo_scan.py"] and stopped
            and "next: onboarding" not in buf.getvalue()), \
        f"calls={calls} stopped={stopped!r}"


@case
def cluster_runs_photo_cluster_on_a_scanned_dump():
    """REPRODUCTION. ⛔ FAILS on 5cc7e1d: there was no `cluster` subcommand, so
    a dump scanned without clustering had no conductor step to finish it."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, _pack = scanned(tmp, bind=True)
        with conductor() as (calls, _buf):
            photo_run.cmd_cluster(Args(workdir=wd, force=True))
    return calls[:1] == [("photo_cluster.py", [str(wd.resolve()), "--force"])], \
        f"calls={calls}"


@case
def cluster_refuses_a_dump_never_scanned():
    """GUARD. No manifest: said, and nothing run."""
    with tempfile.TemporaryDirectory() as tmp:
        wd = Path(tmp) / "Working Files" / "dump-a"
        wd.mkdir(parents=True)
        (wd / "batches.json").write_text("{}")
        with conductor() as (calls, _buf):
            try:
                photo_run.cmd_cluster(Args(workdir=wd))
                code = 0
            except SystemExit as exc:
                code = exc.code
    return bool(code) and "prep" in str(code) and not calls, f"{code} {calls}"


def route_case(how):
    """LL-PHO-132: `cluster` hands photo_cluster the pack each route names."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = scanned(tmp, bind=how == "collection")
        profile = str((pack / photo_profile.PROFILE_NAME).resolve())
        with conductor() as (calls, _buf):
            if how == "env":
                os.environ[photo_profile.ENV_VAR] = profile
            photo_run.cmd_cluster(Args(workdir=wd, profile=profile if how == "profile"
                                       else None))
            exported = os.environ.get(photo_profile.ENV_VAR)
    return exported == profile and calls[0][0] == "photo_cluster.py", \
        f"exported={exported!r}"


@case
def route_collection_json_clusters_with_the_pack():
    return route_case("collection")


@case
def route_env_var_clusters_with_the_pack():
    return route_case("env")


@case
def route_explicit_profile_clusters_with_the_pack():
    return route_case("profile")


@case
def the_help_names_both():
    """REPRODUCTION. ⛔ FAILS on 5cc7e1d."""
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "photo_run.py"),  # noqa: E731
                                     *a], capture_output=True, text=True)
    p, c = run("prep", "--help"), run("cluster", "--help")
    return "--no-cluster" in p.stdout and c.returncode == 0, p.stdout[-300:]


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
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} prep_cluster cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
