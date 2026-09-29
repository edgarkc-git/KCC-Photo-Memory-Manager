#!/usr/bin/env python3
"""Rule 7 / Rule 8 guard — the engine ships with zero owner facts, and writes
no language it did not resolve at run time.

  Rule 7  no owner's memory, settings, decisions, drive / folder / place /
          subject names or paths in code, tests, SKILL.md or docs. Owner
          values arrive at run time from the memory pack.
  Rule 8  language is a variable, default English. Traditional Chinese is a
          BUILD-VALIDATION locale, never a hardcoded one — no code, comment,
          test or doc is written in it.

  ./.venv/bin/python3 tests/no_owner_facts.py [-v]

Exit 0 = pass.

Scope: the shippable set — scripts/, photo-*/, docs/, templates/, .githooks/,
.github/, the root files — plus tests/, minus tests/golden/. Rule 8 names tests explicitly, and a test
that hardcodes a real person's name leaks that person just as surely as a
script does (tests/fresh_owner_smoke.py is exactly that case, F13).
tests/golden/ is the one exclusion: those fixtures ARE one owner's real data,
held back by a separate packaging decision, not by this guard. The private
term list below is excluded for the same reason — it is gitignored, and it is
made of the very strings it looks for.

THE GUARD MUST NOT CONTAIN THE TERMS IT BANS. Embedding them here would
reproduce the very violation it exists to catch — which is what
tests/fresh_owner_smoke.py:203 does today. So the owner term list is loaded
from tests/.owner-terms.json, which is gitignored. A committed
tests/.owner-terms.example.json shows the shape with obviously fake terms.
With no private file the owner half SKIPS with a message and the CJK half
still runs: a missing private file must never fail a public contributor's
build. A skipped case is not a passed one, so it is subtracted from the
summary and counted beside it — CI prints that line as its whole answer, and
`5/5 passed` while three cases never ran is a claim the run cannot make.

Known debt is waived, not hidden. Each waiver names a reason, and the run
prints how many hits are waived, so the number can only go down on purpose.
Waiving is the mechanism for "we know, it is queued" — never for "make it
green".
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# OA-21 step 1 — every file at the repo ROOT ships, and none of them were
# read. `README.md` was listed by name and the two beside it were not, so
# `LICENSE` and `pyproject.toml` — the first files a packager or a licence
# scanner opens — were outside the scan while the run still printed `0 stale`.
# The gap was not that someone forgot two names: it was that root files were
# enumerated BY HAND, so the next one to land (SECURITY.md, CONTRIBUTING.md)
# would be outside too, silently. Computed instead, so a new root file is in
# scope the day it appears.
#
# Dotfiles are IN. `.gitignore` is a shipped file that names paths, and a path
# is exactly the shape an owner fact takes here.
#
# ⛔ `.git` is NOT always a directory, and this comment used to say it was. In
# a **git worktree** `.git` is a one-line FILE holding an absolute `gitdir:`
# path into the main checkout — which on any real machine contains the owner's
# username. So the guard scanned it, found an owner term, and failed 4/5 in
# every worktree while the same commit passed 5/5 in the main checkout. With
# `core.hooksPath = .githooks` that blocks every commit made from a worktree,
# and a worktree is exactly what CLAUDE.md's multi-session rules REQUIRE a peer
# session to work in. Git's own metadata is never shipped in either shape, so
# it is excluded by name rather than by being a directory.
NOT_SOURCE = {".DS_Store", ".git"}


def is_scannable_root_file(path):
    """-> should this root entry be scanned as shippable source?

    A named function so the worktree case can be tested without building a
    worktree: `ROOT_FILES` is computed once at import from the real repo, so a
    test that only reads it can never see the shape that broke.
    """
    return path.is_file() and path.name not in NOT_SOURCE


ROOT_FILES = sorted(p.name for p in REPO.iterdir() if is_scannable_root_file(p))
# What a stranger downloads, plus the test suite that ships beside it.
# RS7d: `.githooks/` and `.github/` ship in the zip too, and were never read.
SHIPPABLE = ["scripts", "docs", "templates", "tests", ".githooks", ".github"] \
    + ROOT_FILES + sorted(p.name for p in REPO.glob("photo-*") if p.is_dir())
NEVER = ("tests/golden", "tests/.owner-terms.json", "__pycache__",
         ".venv", ".git")
SUFFIXES = {".py", ".md", ".json", ".txt", ".sh", ".yaml", ".yml", ".toml",
            # SET-4a shipped the first rendered surface into `templates/`.
            # A page is prose plus an owner's vocabulary, which is exactly
            # what this guard exists to keep out, and it was unreadable to
            # the guard purely because of its extension.
            ".html"}

OWNER_TERMS_FILE = HERE / ".owner-terms.json"

# i18n-guard:allow-begin — locale detection data, not user-facing output.
# The guard's own pattern is the one place these ranges must be spelled out.
# Han, kana, hangul, and CJK punctuation/fullwidth forms. Fullwidth forms
# matter as much as the ideographs: "(D13)" in fullwidth brackets is still a
# sentence written for one locale.
CJK = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿"
                 r"가-힯豈-﫿＀-￯]")
# i18n-guard:allow-end

# A file may declare a region where non-English strings are the point. Two
# legitimate cases, and only two:
#   * a locale TABLE (photo_profile.BUCKET_VOCAB / MESSAGE_VOCAB) — the engine
#     has to hold the strings it resolves;
#   * locale DETECTION DATA — patterns that read Chinese/Japanese/Korean
#     INPUT (screenshot filenames, OSM place-name variants, trail words). A
#     public tool legitimately needs to understand input it did not write.
ALLOW_BEGIN = "i18n-guard:allow-begin"
ALLOW_END = "i18n-guard:allow-end"


class Waiver:
    """One piece of known CJK debt. `lines` None = the whole file.

    ⛔ RS7d: a waiver covers the CJK half ONLY. An owner fact is never known
    debt, so `scan_owner_terms()` consults no waiver: two whole-file waivers
    used to hide owner terms in the files they covered."""

    def __init__(self, path, reason, ref, lines=None):
        self.path, self.reason, self.ref, self.lines = path, reason, ref, lines
        self.used = 0

    def covers(self, path, line):
        if path == self.path and (self.lines is None or line in self.lines):
            self.used += 1
            return True
        return False


# ---------------------------------------------------------------------------
# Known debt, all of it pre-existing. F13 is the tracked item for the owner
# facts; the CJK entries are the prose and default vocabularies that this
# migration deliberately did not touch. Each one is a thing to fix, not a
# thing to forget.
# ---------------------------------------------------------------------------
WAIVERS = [
    # ⛔ REMOVED 20260906 (U2-06). The waiver here claimed FALLBACK_TYPES was
    # "the same pack-sourced default vocabulary as photo_see.py's". BOTH HALVES
    # WERE FALSE: it fired precisely BECAUSE the pack was empty, and
    # photo_see's equivalent is scene_classes(), which has always been
    # language-resolved. The vocabulary now lives in photo_profile.TYPE_VOCAB
    # with an English table, so there is nothing left to waive.
    # ⛔ A waiver is a claim nobody re-runs. Re-measure waivers, not just code.

    # --- prose: docs and SKILL cards ---------------------------------------

    # --- tests: fixture restatements and synthetic-but-CJK cases ------------
    Waiver("tests/waivers.py",
           "the shipped strings are restated here ON PURPOSE — the golden "
           "harness must assert against a copy the engine cannot change. Do "
           "NOT migrate this file to the message catalog",
           "harness-by-design"),
    Waiver("tests/photo_see_cases.py",
           "cases exercise the built-in zero-shot class names, so they follow "
           "whatever photo_see.py ships",
           "ONB-zero-shot-defaults"),
    Waiver("tests/photo_embed_cases.py",
           "a case checks non-ASCII path handling; the string is test input, "
           "not user-facing output",
           "test-input-data"),
]

def load_owner_terms():
    """-> (list of terms, note) or (None, why not). Never embeds a term."""
    if not OWNER_TERMS_FILE.exists():
        return None, (f"{OWNER_TERMS_FILE.name} not found — the owner-fact half "
                      "is SKIPPED. Copy .owner-terms.example.json to "
                      ".owner-terms.json and fill in the terms you must not "
                      "ship. The file is gitignored on purpose.")
    try:
        data = json.loads(OWNER_TERMS_FILE.read_text())
    except json.JSONDecodeError as e:
        return None, f"{OWNER_TERMS_FILE.name} is not valid JSON: {e}"
    terms = [t for t in data.get("terms", []) if t]
    if not terms:
        return None, f"{OWNER_TERMS_FILE.name} lists no terms"
    return terms, f"{len(terms)} private terms loaded"


def excluded(rel):
    """Match whole path components, never substrings: "tests/golden" as a
    substring also swallows tests/golden_replay.py, quietly putting the most
    important test file outside the scan."""
    parts = rel.split("/")
    for entry in NEVER:
        want = entry.split("/")
        if parts[:len(want)] == want or entry in parts:
            return True
    return False


def walk(roots):
    for root in roots:
        p = REPO / root
        if p.is_file():
            yield p
            continue
        for f in sorted(p.rglob("*")):
            rel = f.relative_to(REPO).as_posix()
            # "" = a file with no extension, such as .githooks/pre-commit
            if not f.is_file() or f.suffix not in SUFFIXES | {""}:
                continue
            if excluded(rel):
                continue
            yield f


def read_lines(path):
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []


def allowed_lines(lines):
    """-> set of 1-based line numbers inside a declared allow block."""
    out, depth = set(), 0
    for i, line in enumerate(lines, 1):
        if ALLOW_BEGIN in line:
            depth += 1
        if depth:
            out.add(i)
        if ALLOW_END in line:
            depth = max(0, depth - 1)
    return out


def scan_cjk():
    """-> (hits, waived) as lists of (relpath, line no, excerpt)."""
    hits, waived = [], []
    for f in walk(SHIPPABLE):
        rel = f.relative_to(REPO).as_posix()
        lines = read_lines(f)
        skip = allowed_lines(lines)
        for i, line in enumerate(lines, 1):
            if i in skip or not CJK.search(line):
                continue
            row = (rel, i, line.strip()[:90])
            if any(w.covers(rel, i) for w in WAIVERS):
                waived.append(row)
            else:
                hits.append(row)
    return hits, waived


def scan_owner_terms(terms):
    """-> hits as (relpath, line no, placeholder). No waiver applies here."""
    hits = []
    lowered = [t.lower() for t in terms]
    for f in walk(SHIPPABLE):
        rel = f.relative_to(REPO).as_posix()
        if rel == Path(__file__).relative_to(REPO).as_posix():
            continue                    # the guard names no terms of its own
        for i, line in enumerate(read_lines(f), 1):
            low = line.lower()
            if not any(t in low for t in lowered):
                continue
            # never echo the term itself, only where it was found
            hits.append((rel, i, "<owner term found — not printed>"))
    return hits


# --------------------------------------------------------------------------
# cases
# --------------------------------------------------------------------------
VERBOSE = False
STATE = {}
# A case that could not run is neither a pass nor a failure. Returned
# instead of True so the summary can subtract it — the same convention
# fresh_owner_smoke.py already uses. It used to return True: with no
# private term list three of the five cases never ran and the last line
# still read `5/5 no_owner_facts cases passed`, which is the whole of
# what CI prints. Nothing was wrong with the guard; the number was
# wrong about it.
SKIP = None


def log(msg):
    if VERBOSE:
        print(f"      {msg}")


def case_no_cjk_outside_locale_tables():
    hits, waived = STATE["cjk"]
    for rel, i, excerpt in hits[:20]:
        log(f"{rel}:{i}  {excerpt}")
    return not hits, f"{len(hits)} unwaived, {len(waived)} waived"


def case_no_owner_terms():
    if STATE["terms"] is None:
        return SKIP, "no private term list"
    hits = STATE["owner"]
    for rel, i, _ in hits[:20]:
        log(f"{rel}:{i}")
    return not hits, f"{len(hits)} found, no waiver applies"


def case_guard_holds_no_owner_terms():
    """The enforcer must not become the leak. Checks this file and the
    committed example against the private list."""
    if STATE["terms"] is None:
        return SKIP, "no private term list"
    lowered = [t.lower() for t in STATE["terms"]]
    bad = []
    for p in (Path(__file__), HERE / ".owner-terms.example.json"):
        if not p.exists():
            continue
        low = p.read_text(encoding="utf-8").lower()
        if any(t in low for t in lowered):
            bad.append(p.name)
    return not bad, ", ".join(bad) or "clean"


def case_private_term_list_is_gitignored():
    ignore = (REPO / ".gitignore").read_text()
    ok = OWNER_TERMS_FILE.name in ignore
    return ok, "listed in .gitignore" if ok else "NOT in .gitignore"


def case_golden_fixtures_cannot_be_staged():
    """⭐ REPRODUCTION (probes 1 and 3; probe 2 is a guard). The golden
    fixtures are one owner's real data with a GPS movement log, and they reach
    the suites only through `$PHOTO_GOLDEN_FIXTURES`. A copy placed at
    `tests/golden/` must never be addable.

    Asked of `git add --dry-run` in a temp repo holding the real `.gitignore`,
    never of `git check-ignore` on this tree: that needs a git repo (a
    `git archive` export is not one) and answers unreliably for a `!` rule
    under an ignored parent. The real tree never gets a `tests/golden/`."""
    import shutil
    import subprocess
    import tempfile
    if shutil.which("git") is None:
        return SKIP, "git not on PATH"

    # ⛔ Run from .githooks/pre-commit, git exports GIT_DIR and GIT_INDEX_FILE.
    # Inherited, they aim `git init` at THIS repo's git dir, which it
    # re-initialises as bare (measured 20260928: it broke the main checkout).
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    # An EMPTY FILE stands in for the machine's global excludes, never
    # os.devnull: that is `nul` on Windows, and git 2.53 refuses it as an
    # exclude file (exit 128, measured on Win11 20260928).
    fd, no_excludes = tempfile.mkstemp(suffix=".gitignore")
    os.close(fd)

    def addable(root):
        subprocess.run(["git", "init", "-q", str(root)], env=env, check=True,
                       capture_output=True, text=True)
        out = subprocess.run(
            ["git", "-c", "core.excludesFile=" + no_excludes, "add", "-A",
             "--dry-run"], cwd=root, env=env, capture_output=True, text=True,
            check=True)
        return out.stdout

    try:
        return staging_probes(addable)
    except subprocess.CalledProcessError as exc:
        return False, f"git exit {exc.returncode}: {(exc.stderr or '').strip()}"
    finally:
        os.unlink(no_excludes)


def staging_probes(addable):
    import shutil
    import tempfile
    problems = []
    notes = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        probes = {
            "tests/golden/dump-x/input/manifest.csv": "a fixture input",
            "tests/golden/dump-x/input/photo-memory/s/photo-profile.json":
                "a fixture pack (the path the old un-ignore re-admitted)",
        }
        control = "scripts/probe.py"
        for rel in [*probes, control]:
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x\n")
        shutil.copy(REPO / ".gitignore", tmp / ".gitignore")
        listed = addable(tmp)
        if control not in listed:
            problems.append("positive control not addable — the probe is broken")
        for rel, what in probes.items():
            if rel in listed:
                problems.append(f"{what} is addable: {rel}")

        # A symlinked tests/golden is the obvious shortcut to the fixture
        # root, and git does not treat a symlink as a directory.
        link_root = tmp / "link"
        (link_root / "tests").mkdir(parents=True)
        (link_root / "scripts").mkdir()
        (link_root / control).write_text("x\n")
        shutil.copy(REPO / ".gitignore", link_root / ".gitignore")
        try:
            os.symlink(tmp / "tests" / "golden", link_root / "tests" / "golden",
                       target_is_directory=True)
        except (OSError, NotImplementedError):
            notes.append("symlink probe not run on this platform")
        else:
            listed = addable(link_root)
            if control not in listed:
                problems.append("symlink positive control not addable")
            if "tests/golden" in listed:
                problems.append("a symlinked tests/golden is addable")
    detail = str(problems) if problems else "not addable, file or symlink"
    return not problems, "; ".join([detail, *notes])


def case_the_staging_check_leaves_a_hooks_repo_alone():
    """GUARD (RS4) for the scrub above. .githooks/pre-commit in a linked
    worktree exports GIT_DIR (that worktree's gitdir) and GIT_INDEX_FILE;
    measured 20260928. Inherited, they made the staging check's `git init`
    re-initialise the hook's repo as bare. Here they point at a SCRATCH repo
    with a worktree, never at this one, and its core.bare must not move.
    ⛔ This file itself runs under that hook, so the setup scrubs GIT_* too
    and the caller's values are put back exactly."""
    import shutil
    import subprocess
    import tempfile
    if shutil.which("git") is None:
        return SKIP, "git not on PATH"
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    def git(*args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                               *args], env=clean, capture_output=True, text=True,
                              check=True).stdout.strip()

    with tempfile.TemporaryDirectory() as tmp:
        main, wt = Path(tmp) / "main", Path(tmp) / "wt"
        git("init", "-q", str(main))
        git("-C", str(main), "commit", "-q", "--allow-empty", "-m", "i")
        git("-C", str(main), "worktree", "add", "-q", str(wt))
        config = str(main / ".git" / "config")
        before = git("config", "--file", config, "core.bare")
        hook = {"GIT_DIR": str(main / ".git" / "worktrees" / "wt"),
                "GIT_INDEX_FILE": str(main / ".git" / "worktrees" / "wt" / "index")}
        saved = {k: os.environ.get(k) for k in hook}
        os.environ.update(hook)
        try:
            staged, detail = case_golden_fixtures_cannot_be_staged()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        after = git("config", "--file", config, "core.bare")
    ok = before == after == "false" and staged is not False
    return ok, f"core.bare {before} -> {after}; staging check: {detail}"


def case_the_staging_check_does_not_lean_on_os_devnull():
    """⭐ REPRODUCTION (RS4b). The staging check passed `os.devnull` as
    core.excludesFile. On Windows that is `nul`, git 2.53 answers "fatal:
    cannot use nul as an exclude file", exit 128, and the raise took the
    whole file down: every later case unrun, every Windows commit blocked by
    the hook. On the Mac git reads a plain `nul` as a missing file and
    carries on, so os.devnull is pointed at a DIRECTORY instead, which Mac
    git refuses with the same message and exit code."""
    import tempfile
    saved = os.devnull
    with tempfile.TemporaryDirectory() as tmp:
        os.devnull = tmp
        try:
            ok, detail = case_golden_fixtures_cannot_be_staged()
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        finally:
            os.devnull = saved
    return ok is not False, detail


def case_every_waiver_still_fires():
    """A waiver whose debt is already gone is a lie about how much debt there
    is, so it has to be deleted. Waivers are CJK-only (RS7d), so this is
    judged on the CJK half alone and runs with or without a term list."""
    stale = sorted(w.path for w in WAIVERS if not w.used)
    for s in stale:
        log(f"stale waiver (debt is gone, delete it): {s}")
    return not stale, f"{len(stale)} stale"


def case_a_worktrees_git_pointer_is_not_source():
    """⭐ REPRODUCTION. In a git WORKTREE `.git` is a one-line file holding an
    absolute `gitdir:` path into the main checkout, and on a real machine that
    path contains the owner's username. The guard scanned it as a root file and
    failed 4/5 in every worktree while the same commit passed 5/5 in the main
    checkout — and with `core.hooksPath = .githooks` that blocks every commit
    made from a worktree, which is exactly where CLAUDE.md's multi-session
    rules require a peer session to work.

    ⛔ Tested through `is_scannable_root_file()` rather than `ROOT_FILES`:
    that list is computed once at import from the real repo, where `.git` is a
    directory, so a test that reads it can never see the shape that broke.
    """
    import tempfile
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pointer = tmp / ".git"
        pointer.write_text("gitdir: /Users/<someone>/repo/.git/worktrees/wt\n")
        if scanned(pointer):
            problems.append("a worktree's .git pointer file is scanned as source")
        # the positive control: an ordinary dotfile at the root IS scanned,
        # because .gitignore names paths and a path is an owner fact's shape.
        ignore = tmp / ".gitignore"
        ignore.write_text("*.pyc\n")
        if not scanned(ignore):
            problems.append(".gitignore stopped being scanned — the fix went "
                            "too wide and dotfiles are out")
        real_dir = tmp / ".venv"
        real_dir.mkdir()
        if scanned(real_dir):
            problems.append("a directory was treated as a root FILE")
    return not problems, str(problems)


def scanned(path):
    return is_scannable_root_file(path)


CASES = [
    ("a worktree's .git pointer is not source (REPRODUCTION)",
     case_a_worktrees_git_pointer_is_not_source),
    ("no CJK outside declared locale tables and detection data",
     case_no_cjk_outside_locale_tables),
    ("no owner facts in shippable paths or tests", case_no_owner_terms),
    ("the guard itself names no owner terms", case_guard_holds_no_owner_terms),
    ("the private term list is gitignored", case_private_term_list_is_gitignored),
    ("golden fixtures can never be staged (REPRODUCTION)",
     case_golden_fixtures_cannot_be_staged),
    ("the staging check leaves a hook's repo alone",
     case_the_staging_check_leaves_a_hooks_repo_alone),
    ("the staging check does not lean on os.devnull (REPRODUCTION)",
     case_the_staging_check_does_not_lean_on_os_devnull),
    ("every waiver still covers real debt", case_every_waiver_still_fires),
]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list the offending lines")
    VERBOSE = ap.parse_args().verbose

    terms, note = load_owner_terms()
    STATE["terms"] = terms
    STATE["cjk"] = scan_cjk()
    STATE["owner"] = scan_owner_terms(terms) if terms else []
    print(f"  owner terms: {note}")

    results = []
    for name, fn in CASES:
        # a case that RAISES is a FAIL with a reason, never a crash that
        # leaves every later case unrun (RS4b: one raise on Windows did)
        try:
            ok, detail = fn()
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append((name, ok, detail))
    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        mark = "skip" if ok is SKIP else ("ok  " if ok else "FAIL")
        print(f"  {mark}  {name.ljust(width)}   {detail}")

    waived = len(STATE["cjk"][1])
    skipped = [n for n, ok, _ in results if ok is SKIP]
    failed = [n for n, ok, _ in results if ok is not SKIP and not ok]
    ran = len(results) - len(skipped)
    print(f"\n  waived: {waived} known CJK hits across {len(WAIVERS)} waiver "
          "entries — debt, not absolution (owner facts are never waived)")
    # Counted, not named: the per-case lines above already say WHICH ones
    # skipped, and CI shows them.
    print(f"\n{ran - len(failed)}/{ran} no_owner_facts cases passed"
          + (f", {len(skipped)} skipped" if skipped else "")
          + ("" if not failed else f" — FAILED: {', '.join(failed)}"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
