#!/usr/bin/env python3
"""G3 cases — `photo_run.py finish` copies from the index's FREEZE.

UAT01-5 failed on its last step: the folder path was typed before the naming
round, so a pet confirmed before the copy reached no folder name (0 of 47).
With an index, the name comes from `photo_index.py render`, the copy plan from
`freeze`, and `finish` refuses — exit 4, nothing copied — when the index, the
exported plan files or the owner pack changed since the freeze. With no index,
`finish` is exactly as before.

  python3 tests/index_finish_cases.py [-v]

Exit 0 = pass. Every dump, pack and file is synthetic, in a temp dir (the
two-day fixture of `photo_index_cases.py`). The conductor runs as a
subprocess, except in the one case that must put a confirm BETWEEN its two
checks, which replaces its `run()`.
"""

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import photo_profile  # noqa: E402
import photo_run  # noqa: E402
import photo_index_cases as ix  # noqa: E402

RUN = ROOT / "scripts" / "photo_run.py"
LOTUS = "20241101_Ford_Lotus_sofa nap"
STALE = 4       # the Lead's ruling: a stale or missing freeze exits 4

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def ready(tmp, freeze=True, how="collection"):
    """-> (work dir, pack) initialised, rendered, checked and (freeze) frozen,
    the pack reached by `how`."""
    wd, pack = ix.g3_dump(tmp, bind=how == "collection")
    profile = pack / photo_profile.PROFILE_NAME
    extra = ["--profile", profile] if how == "profile" else []
    if how == "env":
        os.environ[photo_profile.ENV_VAR] = str(profile)
    for cmd in ("init", "render", "check") + (("freeze",) if freeze else ()):
        code, _out, err = ix.run(cmd, wd, *extra)
        if code:
            raise RuntimeError(f"{cmd}: {err[-300:]}")
    os.environ.pop(photo_profile.ENV_VAR, None)
    return wd, pack


def finish(wd, *extra, env=None, profile=None, cmd="finish"):
    """The conductor as a subprocess; --go --skip-memory unless told else."""
    e = {k: v for k, v in os.environ.items() if k != photo_profile.ENV_VAR}
    if env:
        e[photo_profile.ENV_VAR] = str(env)
    head = [sys.executable, str(RUN)] + (["--profile", str(profile)] if profile else [])
    return subprocess.run(head + [cmd, str(wd), *(extra or ("--go", "--skip-memory"))],
                          capture_output=True, text=True, env=e)


def copied(tmp):
    root = Path(tmp) / "sorted"
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file()) if root.exists() else []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# the copy
# ---------------------------------------------------------------------------

@case
def finish_copies_a_confirmed_pet_into_its_folder_name():
    """⭐ THE U5-01 REPRODUCTION, end to end — and the collection.json route.
    ⛔ FAILS on e56226c: nothing rendered a name or froze a plan, so a pet
    confirmed before the copy reached no folder (UAT01-5: 0 of 47). Now the
    confirmed cat is IN the copied path, the draft dog is in none, every copy
    has the frozen SHA-256, and the source is untouched."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        raw = ix.tree_state(Path(tmp) / "raw")
        r = finish(wd)
        got = copied(tmp)
        untouched = raw == ix.tree_state(Path(tmp) / "raw")
        same = all(sha(Path(tmp) / "sorted" / p)
                   == sha(Path(tmp) / "raw" / "dump-a" / Path(p).name) for p in got)
    return (r.returncode == 0 and f"{LOTUS}/IMG_0101.jpg" in got
            and f"{LOTUS}/IMG_0102.jpg" in got and len(got) == 6
            and not any("Rex" in p for p in got) and same and untouched
            and "match the SHA-256 frozen" in r.stdout), \
        f"rc={r.returncode} got={got} out={r.stdout[-500:]!r} err={r.stderr[-300:]!r}"


def route_case(how):
    """LL-PHO-132: the frozen copy through ONE pack route."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp, how=how)
        profile = pack / photo_profile.PROFILE_NAME
        r = finish(wd, env=profile if how == "env" else None,
                   profile=profile if how == "profile" else None)
        got = copied(tmp)
    return r.returncode == 0 and f"{LOTUS}/IMG_0101.jpg" in got, \
        f"rc={r.returncode} got={got} out={r.stdout[-400:]!r}"


@case
def route_env_var_copies_from_the_freeze():
    return route_case("env")


@case
def route_explicit_profile_copies_from_the_freeze():
    return route_case("profile")


# ---------------------------------------------------------------------------
# the refusals — exit 4, nothing copied
# ---------------------------------------------------------------------------

def refused(tmp, r):
    # FIX7 (F5-b): the recipe names `unfreeze` too. Render lifts a STALE
    # freeze by itself, but one that still holds refuses all three steps and
    # the stop used to say nothing about it (UAT01-7: the tester followed the
    # SKILL instead). REPRODUCTION — fails on b58f0fd, where `unfreeze` is
    # absent from this print.
    return (r.returncode == STALE and not copied(tmp)
            and "nothing was copied" in r.stdout
            and all(f"photo_index.py {c}" in r.stdout
                    for c in ("unfreeze", "render", "check", "freeze")))


@case
def status_names_the_renames_still_to_do_only_with_paths():
    """⭐ FIX8 F8-2 x F8-5 REPRODUCTION. ⛔ FAILS on 2eeda81: `status --paths`
    never listed the folders a re-lock found renamed. Default status names no
    folder (F8-5) and says only how many renames remain; `--paths` lists each
    "old" -> "new", the same test `verify --copied` uses, until it is done."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp)
        finish(wd)
        ix.rename_lotus(pack)
        codes = [ix.run(cmd, wd)[0] for cmd in ("render", "check", "freeze")]
        e = bare_env()
        plain = subprocess.run([sys.executable, str(RUN), "status", str(wd)],
                               capture_output=True, text=True, env=e)
        shown = subprocess.run([sys.executable, str(RUN), "status", str(wd), "--paths"],
                               capture_output=True, text=True, env=e)
        new = LOTUS.replace("Lotus", "Momo")
        (Path(tmp) / "sorted" / LOTUS).rename(Path(tmp) / "sorted" / new)
        after = subprocess.run([sys.executable, str(RUN), "status", str(wd), "--paths"],
                               capture_output=True, text=True, env=e)
    line = f'"{LOTUS}" -> "{new}"'
    return (codes == [0, 0, 0] and plain.returncode == 0 and shown.returncode == 0
            and "1 folder rename(s) still to do" in plain.stdout
            and LOTUS not in plain.stdout and new not in plain.stdout
            and line in shown.stdout and "still to do" not in after.stdout), \
        f"codes={codes} plain={plain.stdout[-500:]!r} shown={shown.stdout[-500:]!r}"


@case
def a_name_corrected_after_the_copy_relocks_and_copies_nothing():
    """⭐ FIX8 F8-2 REPRODUCTION, the owner's whole path (UAT01-8 F7). ⛔ FAILS
    on 99ca388: after a copy, the pet's name is corrected and the freeze
    refuses ("copied by an earlier run to a place this freeze does not name").
    Now the re-lock holds, `finish --go` copies nothing, creates no folder,
    and lists "old -> new" until the owner renames the folder by hand."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp)
        first = finish(wd)
        sorted_root = Path(tmp) / "sorted"
        before = ix.tree_state(sorted_root)
        dirs = sorted(p for p in sorted_root.rglob("*") if p.is_dir())
        ix.rename_lotus(pack)
        codes = [ix.run(cmd, wd)[0] for cmd in ("render", "check", "freeze")]
        again = finish(wd)
        same = before == ix.tree_state(sorted_root)
        no_new_dir = dirs == sorted(p for p in sorted_root.rglob("*") if p.is_dir())
        line = f'"{LOTUS}" -> "{LOTUS.replace("Lotus", "Momo")}"'
        (sorted_root / LOTUS).rename(sorted_root / LOTUS.replace("Lotus", "Momo"))
        done = finish(wd)
    return (first.returncode == 0 and codes == [0, 0, 0] and again.returncode == 0
            and same and no_new_dir and line in again.stdout
            and "to rename by hand" in again.stdout
            and "to rename by hand" not in done.stdout and done.returncode == 0), \
        (f"first={first.returncode} codes={codes} again={again.returncode} same={same} "
         f"no_new_dir={no_new_dir} out={again.stdout[-600:]!r} err={again.stderr[-300:]!r}")


@case
def finish_refuses_an_index_never_frozen():
    """REPRODUCTION. ⛔ FAILS on 826b681: finish knew nothing of an index."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp, freeze=False)
        r = finish(wd)
        ok = refused(tmp, r)
    return ok, f"rc={r.returncode} out={r.stdout[-400:]!r}"


@case
def finish_refuses_a_name_changed_after_the_freeze():
    """REPRODUCTION. ⛔ FAILS on 826b681: finish re-rendered plans.json and
    copied whatever it now said."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        ix.edit_index(tmp, lambda i: ix.folders_of(i)["F001"].update(
            rendered="20241101_Ford_Other"))
        r = finish(wd)
        ok = refused(tmp, r)
    return ok, f"rc={r.returncode} out={r.stdout[-400:]!r}"


@case
def finish_refuses_a_file_moved_after_the_freeze():
    """REPRODUCTION. ⛔ FAILS on 826b681."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        ix.edit_index(tmp, lambda i: ix.by_name(i)["IMG_0102.jpg"].update(
            folder="F002"))
        r = finish(wd)
        ok = refused(tmp, r)
    return ok, f"rc={r.returncode} out={r.stdout[-400:]!r}"


@case
def finish_refuses_a_pack_changed_after_the_freeze():
    """⭐ REPRODUCTION (D-I16). ⛔ FAILS on 826b681: a rename after the freeze
    changed nothing the copy checked. A confirm or a rename moves the pack id,
    and the copy refuses — naming the three steps to run again."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp)
        ix.rename_lotus(pack)
        r = finish(wd)
        ok = refused(tmp, r) and "pack changed" in r.stdout
    return ok, f"rc={r.returncode} out={r.stdout[-400:]!r}"


@case
def plan_refuses_a_stale_freeze_too():
    """GUARD. `plan --plan N --go` is a copy path as well."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp)
        ix.rename_lotus(pack)
        r = finish(wd, "--plan", "1", "--go", "--skip-memory", cmd="plan")
        ok = refused(tmp, r)
    return ok, f"rc={r.returncode} out={r.stdout[-400:]!r}"


class Args:
    def __init__(self, workdir):
        self.workdir, self.go, self.skip_memory = str(workdir), True, True
        self.profile, self.workdir_root = None, None
        self.force, self.no_vision = False, False


@case
def a_confirm_between_the_two_checks_is_caught_before_the_first_copy():
    """REPRODUCTION (ruling 2). ⛔ FAILS on 826b681. The freeze is checked
    once before the plan loop and once more just before the FIRST
    photo_execute: a confirm made beside this run in between refuses the
    copy (exit 4) and photo_execute never runs."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        verdicts, calls = [0, STALE], []

        def fake(script, *a, python=None):
            calls.append(script)
            rc = verdicts.pop(0) if script == "photo_index.py" and verdicts else 0
            return subprocess.CompletedProcess([script], rc)

        real = photo_run.run
        photo_run.run = fake
        photo_run._pack_cache.clear()
        code = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                photo_run.cmd_finish(Args(wd))
        except SystemExit as exc:
            code = exc.code
        finally:
            photo_run.run = real
            photo_run._pack_cache.clear()
    return (code == STALE and "photo_execute.py" not in calls
            and calls.count("photo_index.py") == 2), f"code={code} calls={calls}"


@case
def a_copy_check_of_6_is_not_a_flag():
    """REPRODUCTION (Card 6 F-mm). The copy check after `finish --go` exiting
    6 (every copy matches, only the pack moved) is not a failed copy: finish
    does not exit 1 over it. ⛔ On c5b6f99 any non-zero was `copy-check`."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        calls = []

        def fake(script, *a, python=None):
            calls.append((script,) + a)
            rc = 6 if script == "photo_index.py" and "--copied" in a else 0
            return subprocess.CompletedProcess([script], rc)

        real = photo_run.run
        photo_run.run = fake
        photo_run._pack_cache.clear()
        code, out = None, io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                photo_run.cmd_finish(Args(wd))
        except SystemExit as exc:
            code = exc.code
        finally:
            photo_run.run = real
            photo_run._pack_cache.clear()
    copied_checked = any("--copied" in c for c in calls)
    return (copied_checked and code in (None, 0)
            and "copy-check" not in out.getvalue()), \
        f"code={code} checked={copied_checked} out={out.getvalue()[-300:]!r}"


@case
def finish_runs_identify_with_the_pages_python():
    """REPRODUCTION (UAT02-02 F-r). ⛔ FAILS on c5b6f99: finish ran identify
    with whatever python started it; under a system python3 with no
    pillow-heif / ffmpeg every HEIC and video row lost its crop. It now uses
    the pages' interpreter choice (`page_python()`)."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        seen = []

        def fake(script, *a, python=None):
            if script == "photo_index.py" and "identify" in a:
                seen.append(python)
            return subprocess.CompletedProcess([script], 0)

        real, real_page = photo_run.run, photo_run.page_python
        photo_run.run = fake
        photo_run.page_python = lambda: "/the/pages/python"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                photo_run.identify_checkpoint(wd)
        finally:
            photo_run.run, photo_run.page_python = real, real_page
    return seen == ["/the/pages/python"], f"seen={seen}"


@case
def the_end_of_dump_review_runs_with_the_pages_python():
    """REPRODUCTION (HIL01 HIL-10). ⛔ FAILS on beb57e9: `finish` ran the
    end-of-dump `review --final` (and its dry-run `--preview`) with whatever
    python started it, so under a system python3 every MP4/HEIC frame lost
    its crop and no end page was written. Both now use `page_python()`."""
    seen = {}
    for go in (True, False):
        with tempfile.TemporaryDirectory() as tmp, ix.no_env():
            wd, _pack = ready(tmp)

            def fake(script, *a, python=None):
                if script == "photo_memory.py" and "--final" in a:
                    seen.setdefault(go, []).append(python)
                return subprocess.CompletedProcess([script], 0)

            args = Args(wd)
            args.go = go
            real, real_page = photo_run.run, photo_run.page_python
            photo_run.run = fake
            photo_run.page_python = lambda: "/the/pages/python"
            photo_run._pack_cache.clear()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    photo_run.cmd_finish(args)
            except SystemExit:
                pass
            finally:
                photo_run.run, photo_run.page_python = real, real_page
                photo_run._pack_cache.clear()
    want = {True: ["/the/pages/python"], False: ["/the/pages/python"]}
    return seen == want, f"seen={seen}"


@case
def finish_help_names_exit_4():
    """REPRODUCTION (ruling 2). ⛔ FAILS on 826b681."""
    r = subprocess.run([sys.executable, str(RUN), "finish", "--help"],
                       capture_output=True, text=True)
    text = " ".join(r.stdout.split())
    return "4 this dump has an index" in text, text[-400:]


def status(wd):
    e = {k: v for k, v in os.environ.items() if k != photo_profile.ENV_VAR}
    r = subprocess.run([sys.executable, str(RUN), "status", str(wd)],
                       capture_output=True, text=True, env=e)
    return r.returncode, r.stdout.split("\nnext:")[-1]


@case
def status_on_an_indexed_dump_gives_the_index_next_step():
    """⭐ REPRODUCTION (G8). ⛔ FAILS on 8c192c1: an indexed dump was told to
    "AUTHOR plans.json" and that `finish --go` would put a dump-wide round."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp, freeze=False)
        seen_rc, seen = status(wd)
        code, _o, err = ix.run("freeze", wd)
        frozen_rc, frozen = status(wd)
    return (seen_rc == 0 and frozen_rc == 0 and code == 0
            and "AUTHOR plans.json" not in seen + frozen and "U-2" not in seen + frozen
            and "batch page" in seen and "identify" in seen and "freeze" in seen
            and "copies from the freeze" in frozen), f"{seen!r} {frozen!r} {err[-200:]}"


@case
def status_on_an_indexed_dump_lists_the_vision_pass_for_unseen_batches():
    """REPRODUCTION (G8): the SKILL sends the agent to `status` for these lines."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, seen=(1,))
        code, _o, err = ix.run("init", wd)
        rc, out = status(wd)
    return (code == 0 and rc == 0 and "not seen yet" in out and "photo_see.py" in out
            and "(batches: 2)" in out and "classify" not in out.lower()), f"{out!r} {err[-200:]}"


@case
def status_after_a_no_vision_render_says_vision_was_skipped():
    """⭐ REPRODUCTION (W2-20a). A batch rendered with --no-vision was still
    reported as "not seen yet", as if a step had been forgotten. The render's
    own stamp says it was skipped by choice; the visual pass stays listed."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, seen=(1,))
        code, _o, err = ix.run("init", wd)
        code2, _o2, err2 = ix.run("render", wd, "--no-vision")
        rc, out = status(wd)
    return (code == 0 and code2 == 0 and rc == 0
            and "1 batch(es) rendered without vision (--no-vision): B2" in out
            and "not seen yet" not in out and "photo_see.py" in out
            and "(batches: 2)" in out), f"{out!r} {err[-200:]} {err2[-200:]}"


@case
def status_without_an_index_keeps_its_own_next_step():
    """GUARD, NARROWED BY FIX6 (U6-09, Lead ruling). A dump with no index keeps
    its own next step and never speaks of pages or views. With an owner pack
    bound that step is now `photo_index.py init` (the index flow has no
    classify step, and `cluster` runs before `init`); the packless classify
    route is held by `pre_plan_checkpoint_cases`."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp)
        rc, out = status(wd)
    return (rc == 0 and f'photo_index.py" init "{Path(wd).resolve()}"' in out
            and "photo_classify_set.py" not in out
            and "batch page" not in out and "identify" not in out), repr(out)


@case
def finish_help_names_the_pages_and_the_views():
    """REPRODUCTION (G8): exit 3 and --skip-memory spoke only of the U-2 round."""
    r = subprocess.run([sys.executable, str(RUN), "finish", "--help"],
                       capture_output=True, text=True)
    text = " ".join(r.stdout.split())
    return ("3 a question was just put — a batch page or the agent's identify views" in text
            and "skip the batch pages AND the agent's identify views" in text), text[-600:]


def bare_env():
    return {k: v for k, v in os.environ.items() if k != photo_profile.ENV_VAR}


def status_full(wd):
    r = subprocess.run([sys.executable, str(RUN), "status", str(wd)],
                       capture_output=True, text=True, env=bare_env())
    return r.returncode, r.stdout


def dry_run(wd):
    return subprocess.run([sys.executable, str(RUN), "finish", str(wd)],
                          capture_output=True, text=True, env=bare_env())


def typed_plans(wd, tmp):
    sorted_root = str(Path(tmp) / "sorted")
    (wd / "plans.json").write_text(json.dumps({"dest_root": sorted_root, "plans": [
        {"plan": 1, "title": "one", "batches": [1],
         "dest": {"mode": "new", "path": f"{sorted_root}/20241101_typed"}},
        {"plan": 2, "title": "two", "batches": [2],
         "dest": {"mode": "new", "path": f"{sorted_root}/20241102_typed"}}]}))


@case
def status_prints_the_apply_line_of_the_visual_pass():
    """REPRODUCTION (G8i). ⛔ FAILS on e198afc: status printed only the
    selecting `photo_see.py --batch <N>`, which records nothing, while the
    SKILL tells the agent to run what status prints."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, seen=(1,))
        code, _o, err = ix.run("init", wd)
        rc, out = status_full(wd)
    return (code == 0 and rc == 0
            and "--batch <N> --apply decisions.json --memorize" in out), f"{out[-600:]!r} {err[-200:]}"


@case
def status_on_an_indexed_dump_counts_no_classify_stage():
    """REPRODUCTION (G8i). ⛔ FAILS on e198afc: "④ 0/N classified" on a flow
    with no classify step. GUARD half: a dump with no index keeps ④."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp, freeze=False)
        _rc, indexed_out = status_full(wd)
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp)
        _rc, plain_out = status_full(wd)
    return ("classified →" not in indexed_out and "⑤" in indexed_out
            and "classified →" in plain_out), f"{indexed_out[-500:]!r}"


@case
def a_dry_run_before_the_freeze_sends_the_agent_to_go_first():
    """⭐ REPRODUCTION (G8i). ⛔ FAILS on e198afc: the dry run exited 4 asking
    for render/check/freeze BEFORE the pages, and printed the U-2 round line."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp, freeze=False)
        r = dry_run(wd)
    out = r.stdout
    return (r.returncode == STALE and "--go FIRST" in out
            and "freeze after the pages and the views" in out
            and "pre-plan naming round" not in out
            and "batch pages and the agent's identify views run only with --go" in out), \
        f"rc={r.returncode} {out[-700:]!r}"


@case
def a_go_run_at_a_missing_freeze_asks_only_for_render_check_freeze():
    """GUARD: with --go the pages and the views run before the freeze check,
    so its stop does not send the agent back to --go."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp, freeze=False)
        r = finish(wd)
    return (r.returncode == STALE and "--go FIRST" not in r.stdout
            and "freeze" in r.stdout), f"rc={r.returncode} {r.stdout[-400:]!r}"


@case
def a_dry_run_without_an_index_still_names_the_naming_round():
    """GUARD: a dump with no index keeps its U-2 dry-run line."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp)
        typed_plans(wd, tmp)
        r = dry_run(wd)
    return ("pre-plan naming round runs only with --go" in r.stdout
            and "identify views" not in r.stdout), f"rc={r.returncode} {r.stdout[-400:]!r}"


# ---------------------------------------------------------------------------
# FIX9 F7b — a re-lock after the copy, then a dry run
# ---------------------------------------------------------------------------

def statuses(wd):
    return {b["batch"]: b.get("status") for b in
            json.loads((wd / "batches.json").read_text())["batches"]}


def set_status(wd, status, only=None):
    doc = json.loads((wd / "batches.json").read_text())
    for b in doc["batches"]:
        if only is None or b["batch"] in only:
            b["status"] = status
    (wd / "batches.json").write_text(json.dumps(doc))


def work_dir_state(wd):
    """bytes AND mtime of every file: "writes nothing" is both."""
    return {str(p.relative_to(wd)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(Path(wd).rglob("*")) if p.is_file()}


def copied_then_relocked(tmp):
    """The UAT01-9 state: copied, a name corrected, render/check/freeze again."""
    wd, pack = ready(tmp)
    first = finish(wd)
    ix.rename_lotus(pack)
    codes = [ix.run(cmd, wd)[0] for cmd in ("render", "check", "freeze")]
    return wd, pack, first.returncode, codes


@case
def a_relock_after_the_copy_keeps_every_batch_done():
    """⭐ FIX9 F7b REPRODUCTION (the first writer). ⛔ FAILS on 0dc797b: the
    freeze re-renders every plan through photo_plan, which set every batch
    `planned`, `done` or not — status read "0/N sorted" with every file on the
    drive (UAT01-9: 58 of 58)."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, first, codes = copied_then_relocked(tmp)
        got = statuses(wd)
    return (first == 0 and codes == [0, 0, 0] and got
            and all(s == "done" for s in got.values())), f"first={first} codes={codes} {got}"


@case
def a_dry_run_after_a_relock_writes_nothing():
    """⭐ FIX9 F7b REPRODUCTION (the whole symptom). ⛔ FAILS on 0dc797b: the dry
    run approved every batch the freeze had demoted and rewrote batches.json,
    its .bak and status.json. Now every file of the work dir keeps its bytes
    and its mtime."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, first, codes = copied_then_relocked(tmp)
        status(wd)      # the ledger as `status` leaves it
        before = work_dir_state(wd)
        r = dry_run(wd)
        after = work_dir_state(wd)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    return (first == 0 and codes == [0, 0, 0] and r.returncode == 0
            and not changed and "DRY-RUN" in r.stdout), \
        f"rc={r.returncode} changed={changed} out={r.stdout[-400:]!r}"


@case
def go_heals_a_churned_state():
    """GUARD. A dump already churned by the old code (`approved` or `planned`
    with every file copied) ends `done` after `finish --go`, copying nothing."""
    results = []
    for churned in ("approved", "planned"):
        with tempfile.TemporaryDirectory() as tmp, ix.no_env():
            wd, _pack = ready(tmp)
            finish(wd)
            before = ix.tree_state(Path(tmp) / "sorted")
            set_status(wd, churned)
            r = finish(wd)
            results.append((churned, r.returncode, statuses(wd),
                            before == ix.tree_state(Path(tmp) / "sorted")))
    return all(rc == 0 and all(s == "done" for s in st.values()) and same
               for _c, rc, st, same in results), f"{results}"


@case
def a_dry_run_without_an_index_still_approves():
    """GUARD. photo-run/SKILL.md: "A first dry run advances fresh batches
    `classified -> approved`" — a dump with no index keeps it."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp)
        typed_plans(wd, tmp)
        set_status(wd, "classified")
        r = dry_run(wd)
        got = statuses(wd)
        nothing = copied(tmp)
    return (r.returncode == 0 and got == {1: "approved", 2: "approved"}
            and not nothing), f"rc={r.returncode} {got} copied={nothing} {r.stdout[-300:]!r}"


@case
def a_not_done_batch_still_copies_after_a_relock():
    """GUARD. Keeping a `done` batch `done` must not skip one that is not: a
    batch whose copy is undone (its records and files gone) is re-copied after
    a re-lock, and the copied batch beside it stays `done`."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp)
        finish(wd)
        sorted_root = Path(tmp) / "sorted"
        day2 = {r["SourceFile"] for p in (wd / "plan").glob("plan_P*-files.csv")
                for r in ix.csv_rows(wd, p.relative_to(wd)) if r["batch"] == "2"}
        dropped = []
        for state in (wd / "plan").glob("execute-state_P*.json"):
            doc = json.loads(state.read_text())
            for src in [s for s in doc["verified"] if s in day2]:
                Path(doc["verified"].pop(src)["dest"]).unlink()
                dropped.append(Path(src).name)
            state.write_text(json.dumps(doc))
        set_status(wd, "approved", only=[2])
        ix.rename_lotus(pack)
        codes = [ix.run(cmd, wd)[0] for cmd in ("render", "check", "freeze")]
        mid = statuses(wd)
        r = finish(wd)
        back = [p.name for p in sorted_root.rglob("*") if p.name in dropped]
        got = statuses(wd)
    return (dropped and codes == [0, 0, 0] and mid[1] == "done" and mid[2] != "done"
            and r.returncode == 0 and sorted(back) == sorted(dropped)
            and got == {1: "done", 2: "done"}), \
        (f"dropped={dropped} codes={codes} mid={mid} rc={r.returncode} back={back} "
         f"got={got} out={r.stdout[-500:]!r}")


# ---------------------------------------------------------------------------
# M5 (FIX9-A option A) — before the copy, a dry run and a refused freeze
# ---------------------------------------------------------------------------

def changed_files(before, after):
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


@case
def a_dry_run_before_the_copy_writes_nothing():
    """⭐ REPRODUCTION (M5). ⛔ FAILS on 4739665: the dry run approved every
    batch of a fresh freeze and rewrote batches.json, its .bak and
    status.json. The freeze is the approval on an indexed dump; the dry run
    still previews each copy and says the batches wait for `--go`."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        status(wd)
        before = work_dir_state(wd)
        r = dry_run(wd)
        changed = changed_files(before, work_dir_state(wd))
        got, nothing = statuses(wd), copied(tmp)
    return (r.returncode == 0 and not changed and not nothing
            and got == {1: "planned", 2: "planned"}
            and "not approved yet" in r.stdout and "DRY-RUN" in r.stdout), \
        f"rc={r.returncode} changed={changed} {got} out={r.stdout[-400:]!r}"


@case
def a_refused_freeze_leaves_every_batch_as_it_was():
    """⭐ REPRODUCTION (M5 side finding). ⛔ FAILS on 4739665: photo_plan
    advanced plan 1's batch to `planned` before plan 2 was refused, and the
    freeze put back plans.json and the plan files only — batch 1 stayed
    demoted, with a new .bak and paperwork-moved.json beside it."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp, freeze=False)
        set_status(wd, "approved")
        (wd / "classify" / "batch-02" / "see-labels.json").unlink()
        before = work_dir_state(wd)
        code, _o, err = ix.run("freeze", wd)
        changed = changed_files(before, work_dir_state(wd))
        got = statuses(wd)
    return (code != 0 and "nothing frozen" in err and not changed
            and got == {1: "approved", 2: "approved"}), \
        f"code={code} changed={changed} {got} err={err[-300:]!r}"


@case
def go_after_a_dry_run_that_approved_nothing_still_copies():
    """GUARD (M5). The approval moved to `--go` only: a dry run, then
    `finish --go`, copies every file and ends every batch `done`."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        dry = dry_run(wd)
        r = finish(wd)
        got, files = statuses(wd), copied(tmp)
    return (dry.returncode == 0 and r.returncode == 0 and files
            and got == {1: "done", 2: "done"}), \
        f"dry={dry.returncode} rc={r.returncode} {got} files={files} {r.stdout[-300:]!r}"


# ---------------------------------------------------------------------------
# M5b / D-28 — a held batch is never released by `finish`
# ---------------------------------------------------------------------------

def held_dump(tmp):
    """No index, two typed plans, batch 2 held with a reason."""
    wd, _pack = ix.g3_dump(tmp)
    typed_plans(wd, tmp)
    set_status(wd, "classified")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "photo_classify_set.py"),
                        str(wd), "--batch", "2", "--status", "held",
                        "--reason", "the owner has not said which day this is"],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-300:])
    return wd


@case
def a_dry_run_leaves_a_held_batch_held():
    """⭐ REPRODUCTION (M5b). ⛔ FAILS on 6edab52: a no-index dry run approved
    the held batch like any other, so the hold was gone after a preview."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = held_dump(tmp)
        r = dry_run(wd)
        got = statuses(wd)
    return (r.returncode == 0 and got == {1: "approved", 2: "held"}
            and "B2 held" in r.stdout), f"rc={r.returncode} {got} {r.stdout[-400:]!r}"


@case
def go_copies_nothing_of_a_held_batch():
    """⭐ REPRODUCTION (M5b). ⛔ FAILS on 6edab52: `finish --go` approved the
    held batch, copied it and marked it `done` with its hold reason still
    recorded. Now its plan waits and the other plan copies."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = held_dump(tmp)
        r = finish(wd)
        got, files = statuses(wd), copied(tmp)
    return (r.returncode == 0 and got == {1: "done", 2: "held"}
            and not any("20241102_typed" in f for f in files)
            and any("20241101_typed" in f for f in files)), \
        f"rc={r.returncode} {got} files={files}"


@case
def a_released_hold_copies_as_before():
    """GUARD. Released (`--status classified`), the batch copies on the next
    `finish --go` like any other."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = held_dump(tmp)
        finish(wd)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "photo_classify_set.py"),
                        str(wd), "--batch", "2", "--status", "classified"],
                       capture_output=True, text=True)
        r = finish(wd)
        got, files = statuses(wd), copied(tmp)
    return (r.returncode == 0 and got == {1: "done", 2: "done"}
            and any("20241102_typed" in f for f in files)), f"rc={r.returncode} {got} {files}"


# ---------------------------------------------------------------------------
# no index — as before
# ---------------------------------------------------------------------------

@case
def without_an_index_finish_is_as_before():
    """GUARD. No pointer: finish renders the hand-written plans with
    photo_plan and copies them, and never calls photo_index."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp)
        sorted_root = str(Path(tmp) / "sorted")
        (wd / "plans.json").write_text(json.dumps({"dest_root": sorted_root, "plans": [
            {"plan": 1, "title": "one", "batches": [1],
             "dest": {"mode": "new", "path": f"{sorted_root}/20241101_typed"}},
            {"plan": 2, "title": "two", "batches": [2],
             "dest": {"mode": "new", "path": f"{sorted_root}/20241102_typed"}}]}))
        r = finish(wd)
        got = copied(tmp)
    return (r.returncode == 0 and "$ photo_plan.py" in r.stdout
            and "photo_index.py" not in r.stdout
            and "20241101_typed/IMG_0101.jpg" in got), \
        f"rc={r.returncode} got={got} out={r.stdout[-400:]!r}"


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

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} index_finish cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
