#!/usr/bin/env python3
"""The owner-fact guard, run on a scratch repo it has never seen (RS7d).

`no_owner_facts.py` finds its repo from its own location, so each case copies
the guard into a temp tree beside a made-up term list and made-up files, runs
it, and reads its owner-term line. No real owner term appears here: the one
term is invented.

  python3 tests/owner_guard_cases.py

Exit 0 = pass. Stdlib only, no network, nothing outside a temp dir.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD = HERE / "no_owner_facts.py"
TERM = "zqxinventedterm"      # belongs to nobody

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def run_guard(files):
    """-> (count of owner hits, the paths reported) for a scratch repo
    holding `files` {relpath: text} plus the guard and a one-term list."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()   # /var is a symlink on macOS
        (root / "tests").mkdir()
        shutil.copy(GUARD, root / "tests" / GUARD.name)
        (root / "tests" / ".owner-terms.json").write_text(
            json.dumps({"terms": [TERM]}), encoding="utf-8")
        (root / ".gitignore").write_text(".owner-terms.json\n", encoding="utf-8")
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        out = subprocess.run([sys.executable, str(root / "tests" / GUARD.name), "-v"],
                             capture_output=True, text=True, encoding="utf-8",
                             cwd=root)
        out = out.stdout + out.stderr
    line = next((l for l in out.splitlines() if "no owner facts in" in l), "")
    m = re.search(r"(\d+) (?:found|unwaived)", line)
    reported = re.findall(r"^\s+(\S+):\d+\s*$", out, re.M)
    return (int(m.group(1)) if m else None), reported, out


@case
def an_owner_term_in_a_waived_file_is_still_reported():
    """REPRODUCTION. ⛔ FAILS on bf3d2b6: `tests/waivers.py` is whole-file
    waived for its CJK strings, and the owner half honoured that waiver, so an
    owner term inside it was counted as "waived" and passed."""
    n, reported, out = run_guard(
        {"tests/waivers.py": f"# a note that names {TERM} by mistake\n"})
    ok = n == 1 and "tests/waivers.py" in reported
    return ok, f"found={n} reported={reported}"


@case
def an_owner_term_in_the_hook_dirs_is_reported():
    """REPRODUCTION. ⛔ FAILS on bf3d2b6: `.githooks/` and `.github/` ship in
    the zip but were never scanned, and the hook has no file extension."""
    n, reported, out = run_guard({
        ".githooks/pre-commit": f"#!/bin/sh\n# runs on {TERM}'s machine\n",
        ".github/workflows/guard.yml": f"# owner half runs on {TERM}'s machine\n"})
    want = {".githooks/pre-commit", ".github/workflows/guard.yml"}
    ok = n == 2 and want <= set(reported)
    return ok, f"found={n} reported={reported}"


@case
def a_clean_scratch_repo_reports_nothing():
    """GUARD. The positive control: with no term anywhere, zero hits, so the
    two cases above are not counting something the scratch tree adds."""
    n, reported, out = run_guard({"tests/waivers.py": "# nothing here\n",
                                  ".githooks/pre-commit": "#!/bin/sh\n"})
    return n == 0, f"found={n} reported={reported}"


def main():
    failed = 0
    for fn in CASES:
        try:
            ok, detail = fn()
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        failed += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {fn.__name__}   {detail}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} owner_guard cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
