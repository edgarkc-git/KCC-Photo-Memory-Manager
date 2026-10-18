#!/usr/bin/env python3
"""M9 cases (P1, SPEC G20/G21): the fix plan page — `plan/fix-plan.md`
rendered as a private web page, and the owner's answers read back into its
op lines.

  python3 tests/fixplan_page_cases.py [-v]

Exit 0 = pass. Every plan, folder name and photo is synthetic, in a temp dir.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import photo_fixplan_page as fp  # noqa: E402

import photo_index  # noqa: E402

# The plan as the fix plan stage writes it: its own writer, never a copy of
# its format (one row format, `photo_index.FIX_ROW`).
OPS = [
    {"op": "RENAME", "rule": "R1", "folder": "F001", "from": "20250104_Townsville_beach",
     "to": "20250104_Lotus Beach Park_beach",
     "reason": "Map: Lotus Beach Park holds 39 of 42 photos", "photos": 42},
    {"op": "RENAME", "rule": "R2", "folder": "F002", "from": "20250111_Hillside_sofa",
     "to": "20250111_Hillside_Lotus_sofa", "reason": "Lotus agreed in 3 photos",
     "photos": 18},
    {"op": "INTO-EXISTING", "rule": "R4", "folder": "F003", "from": "20250120_Birkton",
     "to": "2025/20250120_Birk Old Street_market",
     "reason": "This day already has a folder · from an earlier dump", "photos": 6},
    {"op": "RENAME", "rule": "R3", "folder": "F004", "from": "20250215_Townsville_white cat",
     "to": "20250215_Townsville_Birk", "reason": "Birk is the white cat", "photos": 9},
]
REFUSED = [({"op": "RENAME", "rule": "R1", "folder": "F005", "from": "20250301_Townsville",
             "to": "20250301_Townsville"},
            "landmark lookup failed: type the place with group set-where")]
SAMPLES = "   samples: DCIM/a.jpg | DCIM/b.jpg | DCIM/c.jpg"


def plan_text(ops=OPS, refused=REFUSED, wd=Path("/work/dump-a")):
    text = photo_index.fix_plan_text(wd, {"dump": "dump-a"}, ops, refused)
    lines = text.splitlines()
    first = next((i for i, l in enumerate(lines) if photo_index.FIX_ROW.match(l)), None)
    if first is None:
        return text
    return "\n".join(lines[:first + 1] + [SAMPLES] + lines[first + 1:]) + "\n"


PLAN = plan_text()


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def workdir(tmp, plan=PLAN):
    wd = Path(tmp) / "dump-a"
    (wd / "plan").mkdir(parents=True)
    (wd / "DCIM").mkdir()
    from PIL import Image
    for name, color in (("a.jpg", (200, 40, 40)), ("b.jpg", (40, 200, 40)),
                        ("c.jpg", (40, 40, 200))):
        Image.new("RGB", (64, 48), color).save(wd / "DCIM" / name, "JPEG")
    md = wd / "plan" / "fix-plan.md"
    md.write_text(plan, encoding="utf-8")
    return wd, md


def run(*argv):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "photo_fixplan_page.py"),
                           *map(str, argv)], capture_output=True, text=True)


def page_data(html):
    a = html.index(fp.DATA_OPEN) + len(fp.DATA_OPEN)
    return json.loads(html[a:html.index("</script>", a)].replace("<\\/", "</"))


@case
def the_rows_are_read_with_the_stages_own_pattern():
    """GUARD (M9 on the stage's own row, `photo_index.FIX_ROW`). Every row the
    fix plan stage writes is read — number, op, rule, folder, from, to, the
    reason (a ` · ` inside it kept), the photo count — the samples ride with
    their row, and `## Refused` is read as information, not as a row."""
    plan = fp.parse_plan(PLAN)
    ops = plan["ops"]
    stage = [l for l in PLAN.splitlines() if photo_index.FIX_ROW.match(l)]
    return (plan["title"] == "Fix plan · dump dump-a" and len(ops) == len(stage) == 4
            and ops[0]["folder"] == "F001" and ops[0]["rule"] == "R1"
            and ops[0]["to"] == "20250104_Lotus Beach Park_beach"
            and ops[0]["photos"] == 42 and ops[0]["answer"] == ""
            and ops[0]["samples"] == ["DCIM/a.jpg", "DCIM/b.jpg", "DCIM/c.jpg"]
            and ops[2]["reason"] == "This day already has a folder · from an earlier dump"
            and ops[1]["samples"] == [] and len(plan["refused"]) == 1
            and "group set-where" in plan["refused"][0]), f"{ops[0]} {plan['refused']}"


@case
def the_page_carries_every_row_and_three_thumbnails():
    """REPRODUCTION (G20). ⛔ FAILS on c7b761e (no fix plan page). `render`
    writes one self-contained page: every row with its rule, old → new,
    reason and count, up to three sample photos embedded, `My word` only on
    the rows that take one (R1 place, R3 words), the Refused list, the
    digest, and no mojibake."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, md = workdir(tmp)
        r = run("render", md)
        out = md.with_suffix(".html")
        html = out.read_text(encoding="utf-8") if out.exists() else ""
    if r.returncode or not html:
        return False, r.stderr[-300:]
    d = page_data(html)
    rows = d["rows"]
    return (len(rows) == 4 and [x["chip"] for x in rows] == ["Place", "Pets", "Move", "Pets"]
            and [x["word"] for x in rows] == ["place", None, None, "what"]
            and len(rows[0]["thumbs"]) == 3 and rows[1]["thumbs"] == []
            and all(t.startswith("data:image/jpeg;base64,") for t in rows[0]["thumbs"])
            and len(d["refused"]) == 1 and d["digest"].startswith("sha256:")
            and d["photos"] == 75 and d["nothing"] == photo_index.NOTHING_TO_CHANGE
            and "__DATA__" not in html and "__TEMPLATE_B64__" not in html), \
        f"{r.stdout} {[(x['chip'], x['word']) for x in rows]}"


@case
def answers_land_on_their_rows_and_the_stage_reads_them():
    """⭐ REPRODUCTION (G21, one format). `apply` writes `ok` / `skip` /
    `word:` into the answer field of each row and changes nothing else; the
    fix plan stage's OWN reader (`photo_index.parse_fix`) then reads every
    answer, and a row left open stays open (the stage reads it as skip).
    ⛔ FAILS on c7b761e (no page apply)."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, md = workdir(tmp)
        ans = Path(tmp) / "answers.txt"
        ans.write_text("1: word: Birk Hill Market\n3: ok\n4: word: sleepy\n",
                       encoding="utf-8")
        r = run("apply", md, "--answer", ans)
        text = md.read_text(encoding="utf-8")
    got = {row["n"]: (row["answer"], row["word"]) for row in photo_index.parse_fix(text)}
    changed = [(a, b) for a, b in zip(PLAN.splitlines(), text.splitlines()) if a != b]
    only_answers = all(a.split("answer:")[0] == b.split("answer:")[0] for a, b in changed)
    return (r.returncode == 0 and len(changed) == 3 and only_answers
            and got == {1: ("word", "Birk Hill Market"), 2: ("", None),
                        3: ("ok", None), 4: ("word", "sleepy")}
            and fp.decided(text)[2] == "skip" and "1 left open" in r.stdout), \
        f"{got} {r.stdout} {r.stderr[-200:]}"


@case
def the_republished_page_is_read_back_too():
    """REPRODUCTION (G21). On Send the page republishes ITSELF with the
    answers inside; that whole document is what comes back, and `apply`
    reads it. ⛔ FAILS on c7b761e."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, md = workdir(tmp)
        run("render", md)
        html = md.with_suffix(".html").read_text(encoding="utf-8")
        d = page_data(html)
        d["submitted"] = {"at": "2025-01-01 10:00", "digest": d["digest"],
                          "lines": ["1: ok", "2: ok"], "counts": {}}
        back = html.replace(json.dumps(page_data(html), ensure_ascii=False)
                            .replace("</", "<\\/"),
                            json.dumps(d, ensure_ascii=False).replace("</", "<\\/"))
        reply = Path(tmp) / "reply.html"
        reply.write_text(back, encoding="utf-8")
        r = run("apply", md, "--answer", reply)
        got = fp.decided(md.read_text(encoding="utf-8"))
    return (r.returncode == 0 and back != html and got[1] == "ok" and got[2] == "ok"
            and got[3] == "skip"), f"{got} {r.stderr[-200:]}"


@case
def an_answer_for_another_draft_or_row_or_a_bad_word_writes_nothing():
    """REPRODUCTION (G21, G17). A page sent for an earlier draft (the digest
    differs), a row number the plan does not hold, a word on a row that
    takes none (R2, R4), and a typed word that is a coordinate or holds a
    grammar separator are all refused, and the plan file is byte-identical
    afterwards. ⛔ FAILS on c7b761e."""
    bad = {"stale": json.dumps({"digest": "sha256:0", "lines": ["1: ok"]}),
           "unknown row": "9: ok\n",
           "word on R2": "2: word: Lotus\n",
           "coordinate": "1: word: 25.03,121.56\n",
           "separator": "1: word: Lotus_Bay\n",
           "R3 separator": "4: word: a_b\n",
           "not a row": "the owner said yes\n"}
    got = {}
    with tempfile.TemporaryDirectory() as tmp:
        wd, md = workdir(tmp)
        before = md.read_bytes()
        for why, text in bad.items():
            ans = Path(tmp) / "a.txt"
            ans.write_text(text, encoding="utf-8")
            r = run("apply", md, "--answer", ans)
            got[why] = (r.returncode != 0, md.read_bytes() == before)
    return all(v == (True, True) for v in got.values()), f"{got}"


@case
def a_two_place_word_is_checked_word_by_word():
    """GUARD (as `group set-where`). On an R1 row `Old Pier+Sea Park` is two
    place words, each checked; it is written as given."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, md = workdir(tmp)
        ans = Path(tmp) / "a.txt"
        ans.write_text("1: word: Old Pier+Sea Park\n", encoding="utf-8")
        r = run("apply", md, "--answer", ans)
        got = fp.decided(md.read_text(encoding="utf-8"))
    return r.returncode == 0 and got[1] == "word:Old Pier+Sea Park", f"{got} {r.stderr[-200:]}"


@case
def the_out_of_date_and_empty_states_are_carried_in_the_data():
    """GUARD (SPEC §5.2). `--out-of-date` renders the error state (the page
    shows why and keeps Send off); the stage's own empty plan ("Nothing to
    change.") renders no row, its Refused list still shown."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, md = workdir(tmp)
        run("render", md, "--out-of-date", "You named a pet after this plan was made.")
        stale = page_data(md.with_suffix(".html").read_text(encoding="utf-8"))
        md.write_text(plan_text(ops=[]), encoding="utf-8")
        r = run("render", md)
        empty = page_data(md.with_suffix(".html").read_text(encoding="utf-8"))
    tpl = (ROOT / "templates" / "fixplan-page.html").read_text(encoding="utf-8")
    return (stale["out_of_date"].startswith("You named") and empty["rows"] == []
            and len(empty["refused"]) == 1 and r.returncode == 0
            and photo_index.NOTHING_TO_CHANGE in plan_text(ops=[])
            and "This plan is out of date" in tpl and "Answers sent" in tpl
            and "deleted after the dump" in tpl), f"{stale['out_of_date']!r} {empty}"


@case
def a_make_trip_row_is_shown_when_the_stage_writes_one():
    """GUARD (R5 MAKE-TRIP, once the stage's FIX_ROW takes it): a trip row is
    read and shown like any row, OK or Skip only."""
    if "MAKE-TRIP" not in getattr(photo_index, "FIX_OPS", ()):
        return True, "the stage writes no MAKE-TRIP row yet — skipped"
    trip = {"op": "MAKE-TRIP", "rule": "R5", "folder": "F006",
            "from": "2 day folders 1025-1031", "to": "20241025-1031_Countryland_Dunmore",
            "reason": "a trip abroad", "photos": 6}
    plan = fp.parse_plan(plan_text(ops=[trip], refused=[]))
    row = fp.build_data(plan, "/nowhere", 64, 50)["rows"]
    return (len(row) == 1 and row[0]["op"] == "MAKE-TRIP" and row[0]["word"] is None
            and row[0]["chip"] == "Move"), f"{row}"


def js_lines(rows, state):
    """Run the page's own answer writer with node; None when node is absent."""
    node = shutil.which("node")
    if not node:
        return None
    tpl = (ROOT / "templates" / "fixplan-page.html").read_text(encoding="utf-8")
    script = ("var ROWS = %s; var state = %s;\n%s\n%s\n"
              "console.log(JSON.stringify(lines()));"
              % (json.dumps(rows), json.dumps(state), _fn(tpl, "answerOf"),
                 _fn(tpl, "lines")))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True)
    return json.loads(out.stdout) if out.returncode == 0 else [out.stderr[:200]]


def _fn(tpl, name):
    """The source of `function <name>(...)`, brace-matched."""
    start = tpl.index("function %s(" % name)
    depth, i = 0, tpl.index("{", start)
    while True:
        if tpl[i] == "{":
            depth += 1
        elif tpl[i] == "}":
            depth -= 1
            if depth == 0:
                return tpl[start:i + 1]
        i += 1


@case
def the_page_writes_only_answered_rows_and_a_blank_word_is_open():
    """REPRODUCTION (G21). The page's `lines()` — the single reader of its
    answers — writes `<n>: ok|skip|word: <text>` for each answered row,
    nothing for an open row, and nothing for `My word` with no word typed.
    ⛔ FAILS on c7b761e (no page)."""
    rows = [{"n": 1}, {"n": 2}, {"n": 3}, {"n": 4}, {"n": 5}]
    state = {"pick": {"1": "ok", "2": "skip", "3": "word", "4": "word"},
             "word": {"3": " Lotus Bay ", "4": "  "}}
    got = js_lines(rows, state)
    if got is None:
        return True, "node not installed — skipped"
    return got == ["1: ok", "2: skip", "3: word: Lotus Bay"], f"{got}"


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
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} fix plan page cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
