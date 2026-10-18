#!/usr/bin/env python3
"""M7 cases (P1, G22): the year-folders answer on the onboarding surfaces and
in the pack. The layout it drives (`photo_index.layout_path`, the copy under
`YYYY/`) is in index_group_cases.

  python3 tests/layout_cases.py [-v]

Exit 0 = pass. Every pack is a copy of the shipped template in a temp dir.
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
sys.path.insert(0, str(ROOT / "tests"))
import photo_onboard_page as op  # noqa: E402
import photo_profile  # noqa: E402
import onboard_page_cases as oc  # noqa: E402

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def apply_lines(pack, text):
    """-> (rc, printed, profile) after `apply --write-pack` of pasted lines."""
    ans = os.path.join(os.path.dirname(pack), "answers.txt")
    io.open(ans, "w", encoding="utf-8").write(text)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = op.main(["apply", ans, "--write-pack", pack])
        except SystemExit as exc:
            code = exc.code
    prof = json.load(io.open(os.path.join(pack, "photo-profile.json"),
                             encoding="utf-8"))
    return code, buf.getvalue(), prof


def page_lines(state):
    """Run the page's own `lines()` with node; None when node is absent."""
    node = shutil.which("node")
    if not node:
        return None
    tpl = (ROOT / "templates" / "onboarding-page.html").read_text(encoding="utf-8")
    full = dict({"makes": {}, "screens": {}, "homes": {}, "language": "",
                 "types": "", "away": "", "pets": "", "country": "",
                 "year": ""}, **state)
    script = ('var KEY = {makes:"makes", screen:"screen", home:"home", '
              'language:"language", types:"types", away:"away_km", '
              'pets:"pets", country:"country", year:"year_folders"};\n'
              'var state = %s;\n%s\nconsole.log(JSON.stringify(lines()));'
              % (json.dumps(full), oc.js_fn_body(tpl, "lines")))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True)
    return json.loads(out.stdout) if out.returncode == 0 else [out.stderr[:200]]


@case
def a_year_folders_answer_is_read_and_a_wrong_one_refused():
    """REPRODUCTION (G22). ⛔ FAILS on c7b761e: `year_folders` is not an
    answer key, so the line is refused as unknown."""
    got = [op.parse_lines("year_folders: %s\n" % v).get("year_folders")
           for v in ("yes", "No", "YES")]
    refused = []
    for bad in ("maybe", "true", "1"):
        try:
            op.parse_lines("year_folders: %s\n" % bad)
            refused.append(False)
        except SystemExit:
            refused.append(True)
    return got == ["yes", "no", "yes"] and all(refused), f"{got} {refused}"


@case
def apply_writes_the_answer_and_a_later_sheet_may_change_it():
    """⭐ REPRODUCTION (G22). `apply --write-pack` stores `year_folders` as a
    boolean the layout reads; a later `no` turns it off (it decides where
    the NEXT copies land); a sheet without the line changes nothing.
    ⛔ FAILS on c7b761e (not an answer key)."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = oc.fresh_pack(tmp, "pack")
        before = json.load(io.open(os.path.join(pack, "photo-profile.json"),
                                   encoding="utf-8"))
        c1, _s1, yes = apply_lines(pack, "year_folders: yes\n")
        c2, _s2, no = apply_lines(pack, "year_folders: no\n")
        c3, _s3, kept = apply_lines(pack, "pets: Lotus\n")
    return (c1 == 0 and c2 == 0 and c3 == 0
            and "year_folders" not in before
            and yes.get("year_folders") is True
            and photo_profile.year_folders(yes) is True
            and no.get("year_folders") is False and kept.get("year_folders") is False), \
        f"rc={c1},{c2},{c3} yes={yes.get('year_folders')} no={no.get('year_folders')}"


@case
def the_page_writes_the_answer_line_only_when_given():
    """REPRODUCTION (G22). The page's `lines()` — the single reader of its
    answers — writes `year_folders: yes|no` once the owner picks, and
    nothing while it is undecided (a quote is never an answer).
    ⛔ FAILS on c7b761e (no such answer on the page)."""
    yes = page_lines({"year": "yes"})
    if yes is None:
        return True, "node not installed — skipped"
    no = page_lines({"year": "no"})
    blank = page_lines({})
    return (yes == ["year_folders: yes"] and no == ["year_folders: no"]
            and blank == []), f"{yes} {no} {blank}"


@case
def the_page_starts_undecided_and_quotes_the_pack():
    """GUARD (G22, the onboarding rule "nothing is pre-selected"). The page
    data carries the pack's own answer to quote, "" for a pack that never
    gave one; the template ships no `year_folders`, so a new pack is flat
    until its owner answers."""
    tpl = json.loads((ROOT / "templates" / "photo-memory" / "_template"
                      / "photo-profile.json").read_text())
    return (op.year_folders_held({}) == ""
            and op.year_folders_held({"year_folders": True}) == "yes"
            and op.year_folders_held({"year_folders": False}) == "no"
            and "year_folders" not in tpl
            and photo_profile.year_folders(tpl) is False), "held/template"


@case
def a_malformed_year_folders_value_stops_the_run():
    """GUARD (M7). It decides where every copy lands, so a value that is not
    true/false is refused rather than guessed."""
    try:
        photo_profile.year_folders({"year_folders": "yes"})
        return False, "accepted a string"
    except SystemExit:
        return True, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failures = []
    for fn in CASES:
        try:
            ok, detail = fn()
        except (Exception, SystemExit) as exc:                  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  {fn.__name__.replace('_', ' ')}"
                  + ("" if ok else f"   {detail}"))
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} layout cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
