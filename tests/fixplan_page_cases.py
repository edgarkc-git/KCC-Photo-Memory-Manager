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

PLAN = """# Fix plan — dump-a

Answer each row: ok, skip or word: <your place word>. A row left open is a skip.

1. RENAME (R1) · 20250104_Townsville_beach → 20250104_Lotus Beach Park_beach · Map: Lotus Beach Park holds 39 of 42 photos · 42 photos · answer: ______
   samples: DCIM/a.jpg | DCIM/b.jpg | DCIM/c.jpg
2. RENAME (R2) · 20250111_Hillside_sofa → 20250111_Hillside_Lotus_sofa · Lotus agreed in 3 photos · 18 photos · answer: ______
3. INTO-EXISTING (R4) · (new) 20250120_Birkton → 2025/20250120_Birk Old Street_market · This day already has a folder · 6 photos · answer: ______
4. RENAME (agent) · 20250215_Townsville → 20250215_Townsville · The map did not answer · 9 photos · answer: ______
   lookup: failed
"""


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
def the_op_lines_are_read_and_written_back_unchanged():
    """GUARD (M9 on the stage's own line). Every field of `N. OP (rule) ·
    from → to · reason · photos · answer:` is read, the indented samples and
    a map failure ride with their op, and writing an op back gives the line
    it came from."""
    plan = fp.parse_plan(PLAN)
    ops = plan["ops"]
    first = ops[0]
    lines = [l for l in PLAN.splitlines() if re.match(r"^\d+\. ", l)]
    return (plan["title"] == "Fix plan — dump-a" and len(ops) == 4
            and first["op"] == "RENAME" and first["rule"] == "R1"
            and first["to"] == "20250104_Lotus Beach Park_beach"
            and first["photos"] == 42 and first["answer"] == ""
            and first["samples"] == ["DCIM/a.jpg", "DCIM/b.jpg", "DCIM/c.jpg"]
            and ops[3]["lookup_failed"] and not ops[1]["lookup_failed"]
            and [fp.op_line(o) for o in ops] == lines), \
        f"{len(ops)} {first}"


@case
def the_page_carries_every_row_and_three_thumbnails():
    """REPRODUCTION (G20). ⛔ FAILS on c7b761e (no fix plan page). `render`
    writes one self-contained page: every op with its rule, old → new,
    reason and count, up to three sample photos embedded as thumbnails,
    the plan's digest, and no mojibake."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, md = workdir(tmp)
        r = run("render", md)
        out = md.with_suffix(".html")
        html = out.read_text(encoding="utf-8") if out.exists() else ""
    if r.returncode or not html:
        return False, r.stderr[-300:]
    d = page_data(html)
    rows = d["rows"]
    return (len(rows) == 4 and rows[0]["chip"] == "Place" and rows[1]["chip"] == "Pets"
            and rows[2]["chip"] == "Move" and len(rows[0]["thumbs"]) == 3
            and all(t.startswith("data:image/jpeg;base64,") for t in rows[0]["thumbs"])
            and rows[3]["lookup_failed"] and d["digest"].startswith("sha256:")
            and d["photos"] == 75 and "__DATA__" not in html
            and "__TEMPLATE_B64__" not in html), f"{r.stdout} {rows[0]['chip']}"


@case
def typed_answers_land_on_their_op_lines_and_an_open_row_is_a_skip():
    """REPRODUCTION (G21). `apply` writes `ok` / `skip` / `word:` into the
    op lines and nothing else; the plan as the applying stage reads it
    (`decided`) holds every row, an open one as skip. ⛔ FAILS on c7b761e."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, md = workdir(tmp)
        ans = Path(tmp) / "answers.txt"
        ans.write_text("1: ok\n3: word: Birk Hill Market\n4: skip\n", encoding="utf-8")
        r = run("apply", md, "--answer", ans)
        text = md.read_text(encoding="utf-8")
    got = fp.decided(text)
    untouched = [l for l in text.splitlines() if not re.match(r"^\d+\. ", l)] == \
        [l for l in PLAN.splitlines() if not re.match(r"^\d+\. ", l)]
    return (r.returncode == 0 and got == {1: "ok", 2: "skip", 3: "word:Birk Hill Market",
                                          4: "skip"}
            and "answer: word: Birk Hill Market" in text
            and "2. RENAME (R2)" in text and "answer: ______" in text
            and untouched and "1 left open" in r.stdout), f"{got} {r.stdout} {r.stderr[-200:]}"


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
    return (r.returncode == 0 and got[1] == "ok" and got[2] == "ok"
            and got[3] == "skip"), f"{got} {r.stderr[-200:]}"


@case
def an_answer_for_another_draft_or_op_or_a_bad_word_writes_nothing():
    """REPRODUCTION (G21, G17). A page sent for an earlier draft (the digest
    differs), an op number the plan does not hold, and a typed word that is
    a coordinate or holds a grammar separator are all refused, and the plan
    file is byte-identical afterwards. ⛔ FAILS on c7b761e."""
    bad = {"stale": json.dumps({"digest": "sha256:0", "lines": ["1: ok"]}),
           "unknown op": "9: ok\n",
           "coordinate": "1: word: 25.03,121.56\n",
           "separator": "1: word: Lotus_Bay\n",
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
    """GUARD (as `group set-where`). `Old Pier+Sea Park` is two place words,
    each checked; it is written as given."""
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
    shows why and keeps Send off); a plan with no op renders the empty
    state, "Nothing to change"."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, md = workdir(tmp)
        run("render", md, "--out-of-date", "You named a pet after this plan was made.")
        stale = page_data(md.with_suffix(".html").read_text(encoding="utf-8"))
        md.write_text("# Fix plan — dump-a\n\nNothing to change.\n", encoding="utf-8")
        r = run("render", md)
        empty = page_data(md.with_suffix(".html").read_text(encoding="utf-8"))
    tpl = (ROOT / "templates" / "fixplan-page.html").read_text(encoding="utf-8")
    return (stale["out_of_date"].startswith("You named") and empty["rows"] == []
            and r.returncode == 0 and "Nothing to change" in tpl
            and "This plan is out of date" in tpl and "Answers sent" in tpl
            and "deleted after the dump" in tpl), f"{stale['out_of_date']!r}"


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
