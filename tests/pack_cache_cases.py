#!/usr/bin/env python3
"""C17 cases — the conductor's one-pack-per-run cache, and the cwd.

`photo_run` resolves the owner pack once and reuses it everywhere. The
resolution it caches must be the one made WITH a work dir, because
`collection.json` is found THROUGH the work dir and nowhere else: a
workdir-less answer is empty for a fully bound dump, and caching it hides the
owner from every later stage in the same process.

Measured symptom this file exists to keep dead (C17): `finish --go` on a
collection-bound dump printed "no owner pack bound to this dump", at exit 0,
and skipped the SNS-4 checkpoint — but only when the command was run from the
workspace folder rather than from `Working Files`. 38 drafted subjects were
never put to the owner.

⛔ These cases are about pack RESOLUTION under the conductor's own call
sequence, not about a live SNS-4 round. `checkpoint_branches_on_pack_dir`
is what ties the two together: it pins the expression `cmd_finish` actually
branches on, so a passing resolution case cannot drift away from the code it
speaks for.

⛔ Every case must run with NO --profile and NO PHOTO_PROFILE. Both env-var
routes make `resolve_pack` succeed with no work dir, so the cache is never
poisoned and the defect is invisible — that is the A42 trap (Rule 6 /
LL-PHO-132), and `env_var_route_hides_the_defect` is the control that shows
it, by failing to reproduce on purpose.

  python3 tests/pack_cache_cases.py [-v]

Exit 0 = pass. Every fixture is built in a temp dir; nothing on a drive is
read and no owner's pack is touched.
"""

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_profile  # noqa: E402
import photo_run  # noqa: E402

TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"
DUMP = "dump-a"

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


class Args:
    """The two attributes the conductor reads off its parsed arguments on the
    path under test. `profile` is None in every case here by design."""

    def __init__(self, workdir, profile=None, workdir_root=None):
        self.workdir = workdir
        self.profile = profile
        self.workdir_root = workdir_root


def make_pack(root, owner="fixture-owner"):
    pack_dir = Path(root) / "photo-memory" / owner
    pack_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE, pack_dir)
    for path in list(pack_dir.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", owner)))
    profile_file = pack_dir / photo_profile.PROFILE_NAME
    profile_file.write_text(
        profile_file.read_text(encoding="utf-8")
        .replace("{{SLUG}}", owner).replace("{{DISPLAY}}", owner),
        encoding="utf-8")
    return pack_dir


def make_workspace(root, bind=True, owner="fixture-owner"):
    """The layout photo-init produces: a workspace folder holding
    `Working Files/`, one work dir per dump inside it, and the collection
    binding beside them. -> (workspace, work dir)."""
    workspace = Path(root) / "workspace"
    wf = workspace / "Working Files"
    workdir = wf / DUMP
    workdir.mkdir(parents=True)
    (workdir / "batches.json").write_text('{"batches": []}', encoding="utf-8")
    if bind:
        pack_dir = make_pack(root, owner)
        (wf / "collection.json").write_text(json.dumps({
            "collection": "fixture",
            "owner": owner,
            "memory_root": str(pack_dir.parent),
        }), encoding="utf-8")
    return workspace, workdir


@contextlib.contextmanager
def clean_run(cwd):
    """One process, one pack cache — so a case that inherited the previous
    case's cache would be reading someone else's answer. The env var is reset
    too: `load_pack_cached` EXPORTS it as a side effect, so leaving it set
    would hand the next case the --profile route and silence the defect."""
    saved_cwd = Path.cwd()
    saved_env = os.environ.get(photo_profile.ENV_VAR)
    os.environ.pop(photo_profile.ENV_VAR, None)
    photo_run._pack_cache.clear()
    os.chdir(cwd)
    try:
        yield
    finally:
        os.chdir(saved_cwd)
        photo_run._pack_cache.clear()
        os.environ.pop(photo_profile.ENV_VAR, None)
        if saved_env is not None:
            os.environ[photo_profile.ENV_VAR] = saved_env


def conductor_sequence(workdir_arg):
    """The two lines `cmd_finish` runs, in its order: resolve the work dir
    (which resolves a pack with no work dir to expand a bare dump name), then
    ask for the pack again now that a work dir is known. -> the second pack."""
    args = Args(workdir_arg)
    workdir = photo_run.resolve_workdir(args.workdir, args)
    return photo_run.load_pack_cached(args, workdir)


# ---------------------------------------------------------------------------
# the defect — same dump, same binding, only the cwd differs
# ---------------------------------------------------------------------------

@case
def bound_dump_resolves_from_the_workspace_folder():
    """REPRODUCTION. cwd = the workspace folder, so the bare dump name cannot
    be found relative to it and `resolve_workdir` must ask for a workdir_root
    first — the call that caches a workdir-less, empty pack. ⛔ This is the
    arm that FAILS on unfixed code."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace, _wd = make_workspace(tmp)
        with clean_run(workspace):
            pack = conductor_sequence(DUMP)
            return pack.dir is not None, f"pack.dir={pack.dir}, owner={pack.owner}"


@case
def bound_dump_resolves_from_the_working_files_folder():
    """GUARD. cwd = `Working Files`, so the bare name resolves directly and no
    workdir-less resolution is ever made. This arm passes on the unfixed code
    — it is here to prove the fix did not break the path that worked."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace, _wd = make_workspace(tmp)
        with clean_run(workspace / "Working Files"):
            pack = conductor_sequence(DUMP)
            return pack.dir is not None, f"pack.dir={pack.dir}, owner={pack.owner}"


@case
def the_two_cwds_agree():
    """The claim in one line: where the owner ran the command from is not an
    input to which owner the run belongs to."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace, _wd = make_workspace(tmp)
        with clean_run(workspace):
            outer = conductor_sequence(DUMP)
        with clean_run(workspace / "Working Files"):
            inner = conductor_sequence(DUMP)
    return outer.owner == inner.owner, f"{outer.owner!r} vs {inner.owner!r}"


@case
def a_full_workdir_path_resolves_from_anywhere():
    """The third way a work dir is named — a full path — takes the early
    return too, from any cwd at all."""
    with tempfile.TemporaryDirectory() as tmp:
        _workspace, workdir = make_workspace(tmp)
        with clean_run(tmp):
            pack = conductor_sequence(str(workdir))
            return pack.dir is not None, f"pack.dir={pack.dir}"


# ---------------------------------------------------------------------------
# the other half — an unbound dump must still say so
# ---------------------------------------------------------------------------

@case
def an_unbound_dump_still_has_no_pack():
    """GUARD. A dump with no collection binding is legal and common — it is
    what every benchmark run is. ⛔ A fix that makes the 'no owner pack bound'
    banner unreachable is also wrong: `finish` must print it when, and only
    when, it is true."""
    with tempfile.TemporaryDirectory() as tmp:
        _workspace, workdir = make_workspace(tmp, bind=False)
        with clean_run(tmp):
            pack = conductor_sequence(str(workdir))
            return pack.dir is None, f"pack.dir={pack.dir}, owner={pack.owner}"


@case
def checkpoint_branches_on_pack_dir():
    """What the resolution cases are speaking for. `cmd_finish` gates SNS-4 on
    `pack.dir is None` and prints the banner on the other side of it, so
    `pack.dir` is the value under test and not a proxy for one."""
    src = (SCRIPTS / "photo_run.py").read_text(encoding="utf-8")
    finish = src[src.index("def cmd_finish("):]
    finish = finish[:finish.index("\ndef ", 1)]
    return ("pack = load_pack_cached(args, workdir)" in finish
            and "if pack.dir is None:" in finish
            and "no owner pack bound to this dump" in finish), \
        "cmd_finish no longer gates the checkpoint on pack.dir"


# ---------------------------------------------------------------------------
# why no existing suite sees this
# ---------------------------------------------------------------------------

@case
def env_var_route_hides_the_defect():
    """CONTROL — it must NOT reproduce. The pack reaches a stage by three
    routes and only `collection.json` needs a work dir, so a case written with
    PHOTO_PROFILE set resolves from either cwd and passes on the broken code.
    ⛔ That is why every green suite was blind to C17 (A42, LL-PHO-132): this
    case is evidence about the OTHER cases, not about the fix."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace, _wd = make_workspace(tmp)
        pack_file = (Path(tmp) / "photo-memory" / "fixture-owner"
                     / photo_profile.PROFILE_NAME)
        with clean_run(workspace):
            os.environ[photo_profile.ENV_VAR] = str(pack_file)
            pack = conductor_sequence(DUMP)
            return pack.dir is not None, f"pack.dir={pack.dir}"


@case
def explicit_profile_route_hides_the_defect():
    """CONTROL — the other env-var-shaped route, same job as the case above."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace, _wd = make_workspace(tmp)
        pack_file = (Path(tmp) / "photo-memory" / "fixture-owner"
                     / photo_profile.PROFILE_NAME)
        with clean_run(workspace):
            args = Args(DUMP, profile=str(pack_file))
            workdir = photo_run.resolve_workdir(args.workdir, args)
            pack = photo_run.load_pack_cached(args, workdir)
            return pack.dir is not None, f"pack.dir={pack.dir}"


# ---------------------------------------------------------------------------
# the invariant the fix installs — stated once, for every call site
# ---------------------------------------------------------------------------

@case
def a_workdir_less_resolution_is_never_cached():
    """`finish` is not the only conductor command that resolves a workdir_root
    before it knows a work dir — `prep` does the same at its first line. The
    fix belongs in the shared helper, so the property is asserted there:
    asking without a work dir must leave the cache empty for the caller that
    can ask properly."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace, _wd = make_workspace(tmp)
        with clean_run(workspace):
            args = Args(DUMP)
            first = photo_run.load_pack_cached(args)
            second = photo_run.load_pack_cached(args, workspace
                                                / "Working Files" / DUMP)
            return (first.dir is None and second.dir is not None), \
                f"first={first.dir}, second={second.dir}"


@case
def the_pack_is_exported_to_the_stage_subprocesses():
    """The cache's other job. Every stage is a subprocess, and they inherit
    the owner through PHOTO_PROFILE — so a poisoned cache did not merely
    mislead the conductor, it unbound the whole pipeline. The export must
    survive the fix."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace, _wd = make_workspace(tmp)
        with clean_run(workspace):
            pack = conductor_sequence(DUMP)
            exported = os.environ.get(photo_profile.ENV_VAR)
            # ⛔ Compare RESOLVED paths: the export resolves and pack.dir
            # does not, so on macOS a temp dir differs by /private alone.
            ok = (exported is not None and pack.dir is not None
                  and Path(exported).parent == pack.dir.resolve())
            return ok, f"PHOTO_PROFILE={exported}"


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

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} pack cache cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
