#!/usr/bin/env python3
"""G8 cases — every command a SKILL tells an agent to run must exist.

A SKILL is followed literally by an agent that has not read the code. A
command it names that no script has, a subcommand the script does not offer,
or a flag its parser does not know, stops that agent at the first step and
reads as an engine failure. On `8c192c1` `photo-run/SKILL.md` still named
`photo_plan_gen.py`, which never existed.

For `photo-run`, `photo-plan`, `photo-init` and `photo-see`, every
`<script>.py <sub> [--flag]` in a code block or in backticks is checked against
the script's own `--help`: the script exists, each subcommand is one its
parser offers, and each `--flag` is in that parser's help. Commands and flags
only — no phrase in a SKILL is judged.

⚠️ This suite reads MARKDOWN and runs `--help` of the real scripts (with the
interpreter it is started with; the vision scripts need the repo `.venv`).

  python3 tests/skill_commands_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SKILLS = ["photo-run", "photo-plan", "photo-init", "photo-see"]

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


SCRIPT_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*\.py)\b")
BACKTICK = re.compile(r"`([^`\n]+)`")
CHOICES_FIRST = re.compile(
    r"usage:\s+\S+\.py(?:\s+[a-z][a-z-]*)*"
    r"(?:\s+(?:\[[^\]]*\]|--?[\w-]+(?:\s+[A-Z_]+)?))*\s+\{([^}]*)\}")

_help = {}


def help_text(script, path=()):
    key = (script, tuple(path))
    if key not in _help:
        ran = subprocess.run([sys.executable, str(SCRIPTS / script), *path, "--help"],
                             capture_output=True, text=True, cwd=str(ROOT))
        _help[key] = (ran.returncode, " ".join((ran.stdout + ran.stderr).split()))
    return _help[key]


def snippets(text):
    """-> [str]: each run of text that starts at a `<script>.py` token — one per
    code-block line (continuations joined, `#` comments cut) and one per
    backtick span."""
    out = []
    in_code, joined = False, ""
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            joined += " " + line.split(" #")[0].rstrip().rstrip("\\")
            if line.rstrip().endswith("\\"):
                continue
            out.append(joined)
            joined = ""
        else:
            out.extend(BACKTICK.findall(line))
    found = []
    for s in out:
        m = SCRIPT_TOKEN.search(s)
        if m:
            # a quoted full path (`"<product folder>/scripts/x.py" doctor`,
            # RS7f) leaves its closing quote after the name: drop it
            end = m.end() + (s[m.end():m.end() + 1] in "\"'")
            found.append(s[m.start():m.end()] + s[end:])
    return found


def tokens(snippet):
    try:
        return shlex.split(snippet)
    except ValueError:
        return snippet.split()


def takes_value(token, help_joined):
    """True when `token` is a flag its parser shows with a value
    (`--profile PROFILE`), so the next token is that value, not a subcommand."""
    return (token.startswith("--") and "=" not in token and re.search(
        re.escape(token) + r"\s+[A-Z][A-Z_]*\b", help_joined) is not None)


def judge(snippet):
    """-> [problem]: empty when the script, its subcommands and its flags all
    exist."""
    toks = tokens(snippet)
    script = toks[0]
    if not (SCRIPTS / script).exists():
        # A SKILL may point at a test suite by name; it exists, and is not run.
        return [] if (ROOT / "tests" / script).exists() else [f"{script}: no such script"]
    rc, top = help_text(script)
    if rc != 0:
        return [f"{script} --help exited {rc}"]
    problems, path, texts = [], [], [top]
    rest = toks[1:]
    while rest:
        m = CHOICES_FIRST.search(texts[-1])
        positional = [t for i, t in enumerate(rest) if not t.startswith("-")
                      and not (i and takes_value(rest[i - 1], texts[-1]))]
        if not m or not positional:
            break
        choice = positional[0]
        if choice not in m.group(1).split(","):
            problems.append(f"{script} {' '.join(path)}: no subcommand {choice!r}")
            break
        path.append(choice)
        rest = rest[rest.index(choice) + 1:]
        rc, sub = help_text(script, path)
        if rc != 0:
            problems.append(f"{script} {' '.join(path)} --help exited {rc}")
            break
        texts.append(sub)
    for t in toks[1:]:
        if t.startswith("--"):
            flag = t.split("=")[0]
            if not any(re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", h)
                       for h in texts):
                problems.append(f"{script} {' '.join(path)}: no flag {flag}")
    return problems


def commands():
    return {name: snippets((ROOT / name / "SKILL.md").read_text(encoding="utf-8"))
            for name in SKILLS}


def problems_of(kind):
    out = []
    for name, snips in commands().items():
        for s in snips:
            for p in judge(s):
                if kind in p:
                    out.append(f"{name}: {p}  <- {s[:80]}")
    return sorted(set(out))


@case
def every_script_a_skill_names_exists():
    """⛔ THE REPRODUCTION. On `8c192c1` photo-run named `photo_plan_gen.py`."""
    bad = problems_of("no such script") + problems_of("--help exited")
    return not bad, "; ".join(bad)


@case
def every_subcommand_a_skill_names_is_offered():
    """GUARD: `photo_index.py group make-trip`, `photo_memory.py confirm`, ..."""
    bad = problems_of("no subcommand")
    return not bad, "; ".join(bad)


@case
def every_flag_a_skill_names_is_in_its_parser():
    """GUARD: a flag is judged against the parser of the subcommand it follows
    (and the script's top level)."""
    bad = problems_of("no flag")
    return not bad, "; ".join(bad)


@case
def the_skills_are_actually_read():
    """GUARD: an empty parse passes every case above. The index flow names
    these commands; each must be found."""
    found = {(t[0], tuple(x for x in t[1:3] if not x.startswith("-")))
             for snips in commands().values() for t in map(tokens, snips)}
    want = [("photo_run.py", "finish"), ("photo_index.py", "init"),
            ("photo_index.py", "identify"), ("photo_index.py", "freeze"),
            ("photo_memory.py", "confirm"), ("photo_see.py", None)]
    missing = [w for w in want
               if not any(f[0] == w[0] and (w[1] is None or w[1] in f[1]) for f in found)]
    return not missing, f"not found: {missing}"


@case
def the_checker_refuses_what_does_not_exist():
    """GUARD: the judge itself can fail — an unknown script, subcommand and flag."""
    got = (judge("photo_nothing_here.py run"),
           judge('photo_index.py nosuch "<work dir>"'),
           judge('photo_index.py render "<work dir>" --no-such-flag'),
           judge("photo_index.py group make-trip 202401 F001 --where x --reason y"),
           judge('photo_run.py --profile "<pack>" prep "<source>" --no-cluster'))
    return (got[0] and got[1] and got[2] and not got[3] and not got[4]), repr(got)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failures = []
    for fn in CASES:
        ok, detail = fn()
        print(f"  {'ok  ' if ok else 'FAIL'}  {fn.__name__.replace('_', ' '):<58} "
              f"{detail if (args.verbose or not ok) else ''}")
        if not ok:
            failures.append(fn.__name__)
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} skill_commands cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
