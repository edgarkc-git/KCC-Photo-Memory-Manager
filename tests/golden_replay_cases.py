#!/usr/bin/env python3
"""Cases for the golden harness itself — where it reads its fixtures from.

`tests/golden/` is one owner's real data and is held back from what ships, so
the harness has to be pointable somewhere else: --fixtures > $PHOTO_GOLDEN_FIXTURES
> tests/golden. That makes two things breakable that were not breakable while
the path was a constant, and both are asserted here:

  * the DEFAULT still resolves to tests/golden, so every existing invocation
    behaves exactly as before — golden_replay.py is the oldest regression gate
    in this repo and the change must be invisible to it;
  * a root with nothing in it FAILS LOUDLY — exit 2, and a message naming the
    path and both overrides. ⚠️ Not because the old harness printed a green
    line over zero dumps: measured at b0b9e11, every empty-root route exited 1,
    as a traceback or as `no such dump; have: []`. Two things were wrong there
    and both are asserted below — $PHOTO_GOLDEN_FIXTURES was ignored, so a run
    aimed elsewhere replayed tests/golden and reported ALL GOLDEN DUMPS
    REPRODUCED for a set nobody asked for; and every harness error shared exit
    1 with "the engine changed", which is the one thing this harness exists to
    report. The zero-dump green line is what a build with the flag and no
    validation produces, and that is a mutation control, not history.

The end-to-end cases assert on the MESSAGE as well as the exit code, and that
is not belt-and-braces: argparse also exits 2, for an unrecognised flag. A
case that checked the code alone would pass against a build that never grew
the flag.

No fixture is needed to run this file: every case that spawns the harness
points it at a directory built here, or at one that does not exist.

  python3 tests/golden_replay_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import golden_replay as gr  # noqa: E402

VERBOSE = False
REPLAY = HERE / "golden_replay.py"
# What the harness prefixes its own refusals with. Asserted in every
# subprocess case: argparse exits 2 too, so the code alone is not a finding.
MARKER = "harness error:"
ENV = gr.ENV_FIXTURES


def log(msg):
    if VERBOSE:
        print(f"  {msg}")


def env_without_fixtures(**overrides):
    """The operator's own $PHOTO_GOLDEN_FIXTURES is cleared for the same
    reason golden_replay clears PHOTO_PROFILE: a case must assert what it set,
    not what the shell happened to export."""
    env = {k: v for k, v in os.environ.items() if k != ENV}
    env.update(overrides)
    return env


def with_env(value):
    """Set $PHOTO_GOLDEN_FIXTURES in THIS process, restoring after — the cases
    share one interpreter, so a leaked value would poison later cases and
    every subprocess they spawn."""
    class _Ctx:
        def __enter__(self):
            self.old = os.environ.get(ENV)
            if value is None:
                os.environ.pop(ENV, None)
            else:
                os.environ[ENV] = value

        def __exit__(self, *exc):
            if self.old is None:
                os.environ.pop(ENV, None)
            else:
                os.environ[ENV] = self.old
            return False
    return _Ctx()


def run_replay(*args, env_fixtures=None):
    """-> CompletedProcess. Never asserts — the cases read returncode and
    stderr themselves, because which of the two is wrong is the finding."""
    extra = {} if env_fixtures is None else {ENV: env_fixtures}
    return subprocess.run([sys.executable, str(REPLAY), *args],
                          capture_output=True, text=True,
                          env=env_without_fixtures(**extra))


# ============================================================ precedence ====

def case_the_default_is_the_repo_fixture_set(tmp):
    """If this breaks, every existing `python3 tests/golden_replay.py` starts
    replaying something else — or nothing. The default is the whole
    compatibility promise of the change."""
    with with_env(None):
        assert gr.fixture_root() == HERE / "golden", gr.fixture_root()
    log(f"default -> {gr.fixture_root.__name__}() = {HERE / 'golden'}")


def case_the_env_var_is_honoured(tmp):
    """A fixture set kept outside the tree is only reachable through the env
    var in the invocations nobody wants to edit (CI, a git hook, a README
    one-liner). If the var is ignored, those all silently replay the default."""
    elsewhere = tmp / "fixtures-elsewhere"
    with with_env(str(elsewhere)):
        assert gr.fixture_root() == elsewhere, gr.fixture_root()
    log(f"${ENV} -> {elsewhere}")


def case_a_blank_env_var_counts_as_unset(tmp):
    """`PHOTO_GOLDEN_FIXTURES=` left in a shell profile is a variable nobody
    meant to set. Read literally it points the harness at the empty path,
    which resolves to the current directory — a root that will differ per
    caller and, when it happens to hold no index.json, look like a broken
    checkout."""
    with with_env(""):
        assert gr.fixture_root() == HERE / "golden", gr.fixture_root()
    log("empty env var falls through to the default")


def case_the_env_var_reaches_the_real_run(tmp):
    """The resolver honouring the var proves nothing about main() reading it:
    a build could resolve correctly and still pass `None` down. Pointed at an
    absent root through the environment ALONE, the harness must name that
    root."""
    from_env = tmp / "env-only"
    proc = run_replay(env_fixtures=str(from_env))
    assert proc.returncode == 2, f"exit {proc.returncode}: {proc.stdout}"
    assert str(from_env) in proc.stderr, proc.stderr
    log(f"the env var alone steered the run, exit {proc.returncode}")


def case_the_flag_beats_the_env_var(tmp):
    """The two sources have to be ordered, and only one order is useful: the
    var is the standing setting, the flag is the one-off override. If the var
    won, `--fixtures` would be unusable on any machine that exports it — and
    silently so, since both are paths and neither run would look wrong."""
    from_env, from_flag = tmp / "env-set", tmp / "flag-set"
    with with_env(str(from_env)):
        got = gr.fixture_root(str(from_flag))
    assert got == from_flag, f"env won: {got}"
    log(f"flag {from_flag.name} beat env {from_env.name}")


def case_the_flag_beats_the_env_var_in_the_real_run(tmp):
    """The unit case above proves the resolver's precedence; this proves main()
    actually calls it with the flag. Both roots are absent on purpose, so the
    assertion is which path the harness NAMES — no fixture set required, and
    no chance of the run passing for having found the other one."""
    from_env, from_flag = tmp / "env-set", tmp / "flag-set"
    proc = run_replay("--fixtures", str(from_flag), env_fixtures=str(from_env))
    assert proc.returncode == 2, f"exit {proc.returncode}: {proc.stderr}"
    # ⛔ The exit code alone proves NOTHING here: argparse also exits 2, for an
    # unrecognised flag, and its usage line quotes the flag's path back. A
    # build that never grew --fixtures passes every other assertion in this
    # case. Measured — it did, until this line was added.
    assert MARKER in proc.stderr, f"not the harness's own error: {proc.stderr}"
    assert str(from_flag) in proc.stderr, proc.stderr
    assert str(from_env) not in proc.stderr, f"env path used: {proc.stderr}"
    log(f"named the flag's root, exit {proc.returncode}")


# ======================================================= loud, never 0/2 ====

def case_a_missing_root_exits_2_and_names_the_path(tmp):
    """THE case. Pointed at nothing, the harness must not run its render loop
    over zero dumps and report success. Exit 2 (harness error), not 0, not 1 —
    and the message has to name the path it looked in and how to change it,
    or a public checkout is left guessing which of two mechanisms to reach
    for."""
    missing = tmp / "not-a-fixture-root"
    proc = run_replay("--fixtures", str(missing))
    assert proc.returncode == 2, f"exit {proc.returncode}: {proc.stdout}"
    assert "ALL GOLDEN DUMPS REPRODUCED" not in proc.stdout, proc.stdout
    assert MARKER in proc.stderr, proc.stderr
    assert str(missing) in proc.stderr, proc.stderr
    assert ENV in proc.stderr, proc.stderr
    log(f"exit 2, named {missing.name} and ${ENV}")


def case_an_empty_directory_exits_2_not_0(tmp):
    """A directory that exists but holds no index.json is the state a fresh
    clone is in — the fixtures were left out deliberately, or an unpack put
    the directory there and nothing in it. It gets its own case rather than
    riding on the missing-root one because it is the state a public cloner
    actually reaches, and at b0b9e11 it produced a FileNotFoundError traceback
    at exit 1 — indistinguishable, to a script, from the engine changing."""
    empty = tmp / "empty-root"
    empty.mkdir()
    proc = run_replay("--fixtures", str(empty))
    assert proc.returncode == 2, f"exit {proc.returncode}: {proc.stdout}"
    assert "ALL GOLDEN DUMPS REPRODUCED" not in proc.stdout, proc.stdout
    assert MARKER in proc.stderr, proc.stderr
    assert "index.json" in proc.stderr and str(empty) in proc.stderr, proc.stderr
    log("exit 2 on an existing but empty root")


def case_an_index_declaring_no_dumps_exits_2(tmp):
    """The same zero-dump run reached the other way: an index.json that parses
    but lists nothing. Refused upstream of the --dump filter, so it can never
    be confused with "you asked for a dump this set does not hold"."""
    root = tmp / "dumpless-root"
    root.mkdir()
    (root / "index.json").write_text(json.dumps({"dumps": []}))
    proc = run_replay("--fixtures", str(root))
    assert proc.returncode == 2, f"exit {proc.returncode}: {proc.stdout}"
    assert "ALL GOLDEN DUMPS REPRODUCED" not in proc.stdout, proc.stdout
    assert MARKER in proc.stderr, proc.stderr
    assert "no dumps" in proc.stderr, proc.stderr
    log("exit 2 on an index that declares nothing")


def case_a_declared_dump_with_no_directory_exits_2(tmp):
    """A half-populated root — index.json copied, fixture folders not. Without
    this check the copy inside replay_dump() raises an uncaught traceback and
    exits 1, which reads as "the engine changed"."""
    root = tmp / "half-root"
    root.mkdir()
    (root / "index.json").write_text(json.dumps(
        {"dumps": [{"id": "nodir01", "plans": [1]}]}))
    proc = run_replay("--fixtures", str(root))
    assert proc.returncode == 2, f"exit {proc.returncode}: {proc.stdout}"
    assert MARKER in proc.stderr, proc.stderr
    assert "nodir01" in proc.stderr, proc.stderr
    log("exit 2 on a dump the index declares but the root does not hold")


CASES = [
    ("the default is still tests/golden", case_the_default_is_the_repo_fixture_set),
    ("the env var is honoured", case_the_env_var_is_honoured),
    ("a blank env var counts as unset", case_a_blank_env_var_counts_as_unset),
    ("the env var reaches a real run", case_the_env_var_reaches_the_real_run),
    ("the flag beats the env var", case_the_flag_beats_the_env_var),
    ("the flag beats the env var in a real run",
     case_the_flag_beats_the_env_var_in_the_real_run),
    ("a missing root exits 2 and names the path",
     case_a_missing_root_exits_2_and_names_the_path),
    ("an empty directory exits 2, not 0", case_an_empty_directory_exits_2_not_0),
    ("an index declaring no dumps exits 2", case_an_index_declaring_no_dumps_exits_2),
    ("a declared dump with no directory exits 2",
     case_a_declared_dump_with_no_directory_exits_2),
]


def run_case(name, fn):
    tmp = Path(tempfile.mkdtemp(prefix="golden_replay_case_"))
    try:
        fn(tmp)
        print(f"  ok    {name}")
        return True
    except AssertionError as exc:
        print(f"  FAIL  {name}: {exc}")
        return False
    except Exception as exc:                                 # noqa: BLE001
        print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        if VERBOSE:
            import traceback
            traceback.print_exc()
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    passed = sum(1 for name, fn in CASES if run_case(name, fn))
    print(f"\n{passed}/{len(CASES)} golden_replay harness cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
