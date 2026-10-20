#!/usr/bin/env python3
"""Render the fix plan (`plan/fix-plan.md`) as a private web page, and read
the owner's answers back into it (M9, SPEC G20/G21).

The markdown stays the record and the parse target: `photo_index.py
fix-plan` writes it, the owner's answers are written into its rows here, and
`photo_index.py fix-plan --answers <md> --go` reads them there. This script
only puts it on a page the owner can see on a phone.

⛔ ONE row format: a row is what `photo_index.FIX_ROW` matches, and nothing
here keeps a second pattern for it —

    N. OP (rule) · F0NN · `from` → `to` · reason · P photo(s) · answer: ______

followed, when the stage has them, by up to three sample photos (paths
relative to the work dir):

       samples: classify/batch-01/samples/a.jpg | ... | ...

`## Refused (never applied)` lists what the engine will not do (a failed
map lookup among them); the page shows it as information, never as a row.
An answer is `ok`, `skip` or `word: <text>` (R1: the place word; R3: the
words that replace the look-word). ⛔ A row left open is a skip (G21).

  photo_fixplan_page.py render <plan/fix-plan.md> [--workdir W] [-o page.html]
                               [--out-of-date "<why>"]
  photo_fixplan_page.py apply  <plan/fix-plan.md> --answer <file|-> [--dry-run]

The page is PRIVATE and the agent deletes it after the dump (photo-run
SKILL): it shows the owner's own photographs.
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import photo_index  # noqa: E402
import photo_name  # noqa: E402
import photo_review_page as rp  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(HERE), "templates", "fixplan-page.html")
DATA_OPEN = '<script id="plan-data" type="application/json">'

SEP = " · "
BLANK = re.compile(r"^_{2,}$")
RE_PHOTOS = re.compile(r"^(\d+)\s+photo")
RE_SAMPLES = re.compile(r"^\s+samples:\s*(.*)$")
RE_TITLE = re.compile(r"^#\s+(.+)$")
TITLE = "Review folders"
OLD_TITLE = "Fix plan"
REFUSED_HEAD = "## Refused (never applied)"
RE_REPLY = re.compile(r"^\s*-?\s*(\d+)\s*[:.]\s*(ok|skip|word:\s*.+)\s*$", re.I)
MAX_SAMPLES = 3
# The rules whose row takes the owner's own words (the fix plan's apply:
# R1 = the place word, through set-where; R3 = the [what]).
WORD_KIND = {"R1": "place", "R3": "what"}
# Rule -> the filter chip a row sits under on the page.
CHIP = {"R1": "Place", "R6": "Place", "R2": "Pets", "R3": "Pets",
        "R4": "Move", "R5": "Move"}


def parse_answer(raw):
    """-> "" (open), "ok", "skip" or "word:<text>"."""
    raw = (raw or "").strip()
    if not raw or BLANK.match(raw):
        return ""
    low = raw.lower()
    if low in ("ok", "skip"):
        return low
    if low.startswith("word:"):
        word = raw[5:].strip()
        return "word:" + word if word else ""
    raise SystemExit("an answer is `ok`, `skip` or `word: <text>`, not %r" % raw)


def parse_op(line):
    """-> an op dict for one fix plan row (`photo_index.FIX_ROW`), else None.
    The reason and photo count are the fields between the `to` and the
    answer, read off the row's own tail."""
    m = photo_index.FIX_ROW.match(line.rstrip("\n"))
    if not m:
        return None
    tail = line[m.end(6) + 1:].split(SEP)[1:]
    photos = RE_PHOTOS.match(tail[-2].strip()) if len(tail) >= 2 else None
    return {"n": int(m.group(1)), "op": m.group(2), "rule": m.group(3).strip(),
            "folder": m.group(4), "from": m.group(5), "to": m.group(6),
            "reason": SEP.join(tail[:-2]).strip(),
            "photos": int(photos.group(1)) if photos else 0,
            "answer": parse_answer(m.group(7)), "samples": []}


def parse_plan(md_text):
    """-> {"title", "ops", "refused"} read off the fix plan's own lines."""
    title, ops, refused, in_refused = "", [], [], False
    for line in md_text.splitlines():
        m = RE_TITLE.match(line)
        if m and not title:
            title = m.group(1).strip()
            if title.startswith(OLD_TITLE):
                # A plan written before G45 keeps its old heading on disk.
                title = TITLE + title[len(OLD_TITLE):]
            continue
        if line.startswith("## "):
            in_refused = line.strip() == REFUSED_HEAD
            continue
        if in_refused:
            if line.startswith("- "):
                refused.append(line[2:].strip())
            elif line.strip():
                in_refused = False
            continue
        op = parse_op(line)
        if op:
            ops.append(op)
            continue
        sub = RE_SAMPLES.match(line)
        if sub and ops:
            ops[-1]["samples"] = [s.strip() for s in sub.group(1).split("|")
                                  if s.strip()][:MAX_SAMPLES]
    seen = set()
    for op in ops:
        if op["n"] in seen:
            raise SystemExit("the fix plan numbers row %d twice — a row the "
                             "owner answers must name one op" % op["n"])
        seen.add(op["n"])
    return {"title": title, "ops": ops, "refused": refused}


def plan_digest(ops):
    """A digest over what the owner is asked, answers left out: a page sent
    for one draft never lands on a re-drafted plan."""
    h = hashlib.sha256()
    for op in ops:
        h.update(json.dumps([op["n"], op["op"], op["rule"], op["folder"],
                             op["from"], op["to"]], ensure_ascii=False).encode("utf-8"))
    return "sha256:" + h.hexdigest()


def build_data(plan, workdir, max_px, quality, out_of_date=None):
    rows = []
    for op in plan["ops"]:
        thumbs = []
        for rel in op["samples"]:
            path = rel if os.path.isabs(rel) else os.path.join(workdir, rel)
            try:
                thumbs.append(rp.encode_image(path, max_px, quality))
            except (OSError, ValueError, SystemExit):
                thumbs.append(None)
        rows.append({"n": op["n"], "op": op["op"], "rule": op["rule"],
                     "folder": op["folder"],
                     "chip": CHIP.get(op["rule"], "Other"),
                     "from": op["from"], "to": op["to"], "reason": op["reason"],
                     "photos": op["photos"], "thumbs": thumbs,
                     "word": WORD_KIND.get(op["rule"]), "answer": op["answer"]})
    return {"title": plan["title"] or TITLE, "rows": rows,
            "refused": plan["refused"], "digest": plan_digest(plan["ops"]),
            "photos": sum(op["photos"] for op in plan["ops"]),
            "nothing": photo_index.NOTHING_TO_CHANGE,
            "out_of_date": out_of_date or "", "submitted": None}


def read_reply(raw):
    """-> (digest or None, {n: answer}) from what came back: the page
    republished with `submitted` inside it, its JSON, or typed rows
    (`3: ok`, `4: word: Lotus Bay`)."""
    text = raw.strip()
    if DATA_OPEN in text:
        a = text.index(DATA_OPEN) + len(DATA_OPEN)
        b = text.index("</script>", a)
        text = text[a:b].replace("<\\/", "</")
    if text.startswith("{"):
        payload = json.loads(text)
        sub = payload.get("submitted") or payload
        lines = sub.get("lines")
        if not isinstance(lines, list):
            raise SystemExit("the answer is JSON but carries no `lines` — "
                             "nothing was written.")
        return sub.get("digest"), read_rows(lines)
    return None, read_rows(text.splitlines())


def read_rows(lines):
    out = {}
    for line in lines:
        if not line.strip():
            continue
        m = RE_REPLY.match(line)
        if not m:
            raise SystemExit("not an answer row: %r — a row is `<row number>: "
                             "ok`, `skip` or `word: <text>`. Nothing was "
                             "written." % line.strip())
        out[int(m.group(1))] = parse_answer(m.group(2))
    return out


def check_word(rule, word):
    """The owner's words go into a folder name: checked as the fix plan's
    apply will use them (R1 the place word, as `group set-where`, two joined
    with `+`; R3 the [what]). -> warnings; raises on a refusal."""
    kind = WORD_KIND.get(rule)
    if kind is None:
        raise SystemExit("a %s row takes `ok` or `skip`, not a word. Nothing "
                         "was written." % rule)
    warnings = []
    try:
        if kind == "place":
            for part in word.split(photo_name.NAME_SEP):
                photo_index.agent_text(part, "the word %r" % word, "where", warnings)
        else:
            photo_index.agent_text(word, "the words %r" % word, "what")
    except photo_index.Refused as exc:
        raise SystemExit("%s. Nothing was written: ask the owner for other "
                         "words." % exc)
    return warnings


def shown_answer(answer):
    return ("word: " + answer[5:]) if answer.startswith("word:") else answer


def apply_reply(md_text, digest, answers):
    """-> (new text, [(n, answer)], [warning]). Only the answer field of a
    row changes. Refuses an answer for another draft, a row number the plan
    does not hold and a word its row cannot take."""
    plan = parse_plan(md_text)
    if digest and digest != plan_digest(plan["ops"]):
        raise SystemExit(
            "this plan is out of date: the answers were given on a page for "
            "an earlier draft of it. Nothing was written. Render the page "
            "again and ask the owner once more.")
    by_n = {op["n"]: op for op in plan["ops"]}
    unknown = sorted(n for n in answers if n not in by_n)
    if unknown:
        raise SystemExit("the plan has no row %s — nothing was written"
                         % ", ".join(map(str, unknown)))
    warnings = []
    for n, ans in answers.items():
        if ans.startswith("word:"):
            warnings += ["row %d: %s" % (n, w) for w in check_word(by_n[n]["rule"], ans[5:])]
    out, done = [], []
    for line in md_text.splitlines(keepends=True):
        m = photo_index.FIX_ROW.match(line.rstrip("\n"))
        n = int(m.group(1)) if m else None
        if n in answers and answers[n]:
            out.append(line[:m.start(7)] + shown_answer(answers[n]) + line[m.end(7):])
            done.append((n, answers[n]))
        else:
            out.append(line)
    return "".join(out), done, warnings


def decided(md_text):
    """-> {n: "ok" | "skip" | "word:<text>"} — the rows as the fix plan's
    apply reads them: ⛔ an open row is a skip (G21). For the page's own
    report; `photo_index.py fix-plan --answers` reads the file itself."""
    return {op["n"]: op["answer"] or "skip" for op in parse_plan(md_text)["ops"]}


def cmd_render(args):
    md_path = os.path.abspath(args.plan)
    with io.open(md_path, encoding="utf-8") as fh:
        md_text = fh.read()
    rp.assert_clean_text(md_text, md_path)
    plan = parse_plan(md_text)
    workdir = args.workdir or os.path.dirname(os.path.dirname(md_path))
    with io.open(TEMPLATE, encoding="utf-8") as fh:
        template = fh.read()
    data = build_data(plan, workdir, args.max_px, args.quality, args.out_of_date)
    html = rp.render(template, data)
    rp.assert_clean_text(html, args.out or md_path)
    out = args.out or os.path.splitext(md_path)[0] + ".html"
    with io.open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    missing = sum(1 for r in data["rows"] for t in r["thumbs"] if t is None)
    print("%s  ·  %d row(s), %d photo(s), %d refused%s%s" % (
        out, len(data["rows"]), data["photos"], len(data["refused"]),
        ("  ·  %d sample(s) unreadable" % missing) if missing else "",
        "  ·  OUT OF DATE" if args.out_of_date else ""))
    return 0


def cmd_apply(args):
    md_path = os.path.abspath(args.plan)
    with io.open(md_path, encoding="utf-8") as fh:
        md_text = fh.read()
    raw = (sys.stdin.read() if args.answer == "-"
           else io.open(args.answer, encoding="utf-8").read())
    digest, answers = read_reply(raw)
    new_text, done, warnings = apply_reply(md_text, digest, answers)
    rp.assert_clean_text(new_text, md_path)
    if not args.dry_run and new_text != md_text:
        with io.open(md_path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
    ops = parse_plan(new_text)["ops"]
    got = [op["answer"] for op in ops]
    print("%s  ·  %d answer(s) %s  ·  %d ok, %d skip (%d left open), %d own word"
          % (md_path, len(done), "would be written (dry run)" if args.dry_run
             else "written", got.count("ok"), got.count("skip") + got.count(""),
             got.count(""), sum(1 for a in got if a.startswith("word:"))))
    for w in warnings:
        print("  ⚠️ %s" % w)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("render", help="plan/fix-plan.md -> private web page")
    r.add_argument("plan")
    r.add_argument("-o", "--out", default=None)
    r.add_argument("--workdir", default=None,
                   help="root the samples: paths are relative to (default: the "
                        "work dir that holds plan/)")
    r.add_argument("--out-of-date", default=None, metavar="WHY",
                   help="render the error state: the plan changed, Send is off")
    r.add_argument("--max-px", type=int, default=480)
    r.add_argument("--quality", type=int, default=72)
    r.set_defaults(func=cmd_render)
    a = sub.add_parser("apply", help="the owner's answers -> into the rows")
    a.add_argument("plan")
    a.add_argument("--answer", required=True,
                   help="the republished page, its JSON, or typed rows; - for stdin")
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_apply)
    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
