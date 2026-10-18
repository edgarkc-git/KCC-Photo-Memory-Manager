#!/usr/bin/env python3
"""Render the fix plan (`plan/fix-plan.md`) as a private web page, and read
the owner's answers back into it (M9, SPEC G20/G21).

The markdown stays the record and the parse target: the fix plan stage
writes it, the owner's answers are spliced back into its op lines, and the
stage that applies the plan reads them there. This script only renders it
onto a page the owner can see on a phone and returns what they sent.

One op per line, the stage's own shape:

    N. OP (rule) · from → to · reason · <n> photos · answer: ______

optionally followed by an indented line of up to three sample photos
(paths relative to the work dir) and a map-failure mark:

       samples: DCIM/a.jpg | DCIM/b.jpg | DCIM/c.jpg
       lookup: failed

An answer is `ok`, `skip` or `word: <text>`. ⛔ A row left open is a skip:
the engine applies only rows the owner ticked (G21).

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
import photo_review_page as rp  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(HERE), "templates", "fixplan-page.html")
DATA_OPEN = '<script id="plan-data" type="application/json">'

SEP = " · "
ARROW = " → "
BLANK = re.compile(r"^_{2,}$")
RE_HEAD = re.compile(r"^(\d+)\.\s+([A-Z][A-Z-]*)\s+\(([^)]+)\)$")
RE_PHOTOS = re.compile(r"^(\d+)\s+photos?$")
RE_ANSWER = re.compile(r"^answer:\s*(.*)$")
RE_SUB = re.compile(r"^\s+(samples|lookup):\s*(.*)$")
RE_TITLE = re.compile(r"^#\s+(.+)$")
RE_REPLY = re.compile(r"^\s*-?\s*(\d+)\s*[:.]\s*(ok|skip|word:\s*.+)\s*$", re.I)
MAX_SAMPLES = 3
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
    """-> an op dict for one op line, or None for any other line."""
    parts = line.rstrip("\n").split(SEP)
    if len(parts) < 5:
        return None
    head = RE_HEAD.match(parts[0].strip())
    photos = RE_PHOTOS.match(parts[-2].strip())
    answer = RE_ANSWER.match(parts[-1].strip())
    if not (head and photos and answer and ARROW in parts[1]):
        return None
    old, new = parts[1].split(ARROW, 1)
    return {"n": int(head.group(1)), "op": head.group(2),
            "rule": head.group(3).strip(), "from": old.strip(),
            "to": new.strip(), "reason": SEP.join(parts[2:-2]).strip(),
            "photos": int(photos.group(1)),
            "answer": parse_answer(answer.group(1)),
            "samples": [], "lookup_failed": False}


def parse_plan(md_text):
    """-> {"title", "ops"} read off the fix plan's own lines."""
    title, ops = "", []
    for line in md_text.splitlines():
        m = RE_TITLE.match(line)
        if m and not title:
            title = m.group(1).strip()
            continue
        op = parse_op(line.strip())
        if op:
            ops.append(op)
            continue
        sub = RE_SUB.match(line)
        if sub and ops:
            if sub.group(1) == "samples":
                ops[-1]["samples"] = [s.strip() for s in sub.group(2).split("|")
                                      if s.strip()][:MAX_SAMPLES]
            else:
                ops[-1]["lookup_failed"] = sub.group(2).strip().lower() == "failed"
    seen = set()
    for op in ops:
        if op["n"] in seen:
            raise SystemExit("the fix plan numbers op %d twice — a row the "
                             "owner answers must name one op" % op["n"])
        seen.add(op["n"])
    return {"title": title, "ops": ops}


def plan_digest(ops):
    """A digest over what the owner is asked, answers left out: a page sent
    for one plan never lands on a re-drafted one."""
    h = hashlib.sha256()
    for op in ops:
        h.update(json.dumps([op["n"], op["op"], op["rule"], op["from"], op["to"],
                             op["photos"]], ensure_ascii=False).encode("utf-8"))
    return "sha256:" + h.hexdigest()


def op_line(op):
    """-> the stage's own op line for `op` (the inverse of parse_op)."""
    answer = op.get("answer") or ""
    shown = ("word: " + answer[5:]) if answer.startswith("word:") else (answer or "______")
    return "%d. %s (%s)%s%s%s%s%s%s%s%d photos%sanswer: %s" % (
        op["n"], op["op"], op["rule"], SEP, op["from"], ARROW, op["to"], SEP,
        op["reason"], SEP, op["photos"], SEP, shown)


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
                     "chip": CHIP.get(op["rule"].split()[0], "Other"),
                     "from": op["from"], "to": op["to"], "reason": op["reason"],
                     "photos": op["photos"], "thumbs": thumbs,
                     "lookup_failed": op["lookup_failed"],
                     "answer": op["answer"]})
    return {"title": plan["title"] or "Fix plan", "rows": rows,
            "digest": plan_digest(plan["ops"]),
            "photos": sum(op["photos"] for op in plan["ops"]),
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
            raise SystemExit("not an answer row: %r — a row is `<op number>: "
                             "ok`, `skip` or `word: <text>`. Nothing was "
                             "written." % line.strip())
        out[int(m.group(1))] = parse_answer(m.group(2))
    return out


def check_word(word):
    """A place word typed on the page goes into a folder name: the same
    checks as `group set-where`. -> list of warnings; raises on a refusal."""
    import photo_index
    import photo_name
    warnings = []
    try:
        for part in word.split(photo_name.NAME_SEP):
            photo_index.agent_text(part, "the word %r" % word, "where", warnings)
    except photo_index.Refused as exc:
        raise SystemExit("%s. Nothing was written: ask the owner for another "
                         "word." % exc)
    return warnings


def apply_reply(md_text, digest, answers):
    """-> (new text, [(n, answer)], [warning]). Refuses an answer for
    another plan and a row number the plan does not hold."""
    plan = parse_plan(md_text)
    if digest and digest != plan_digest(plan["ops"]):
        raise SystemExit(
            "this plan is out of date: the answers were given on a page for "
            "an earlier draft of it. Nothing was written. Render the page "
            "again and ask the owner once more.")
    by_n = {op["n"]: op for op in plan["ops"]}
    unknown = sorted(n for n in answers if n not in by_n)
    if unknown:
        raise SystemExit("the plan has no op %s — nothing was written"
                         % ", ".join(map(str, unknown)))
    warnings = []
    for n, ans in answers.items():
        if ans.startswith("word:"):
            warnings += ["op %d: %s" % (n, w) for w in check_word(ans[5:])]
    out, done = [], []
    for line in md_text.splitlines(keepends=True):
        op = parse_op(line.strip())
        if op and op["n"] in answers:
            op["answer"] = answers[op["n"]]
            out.append(op_line(op) + ("\n" if line.endswith("\n") else ""))
            done.append((op["n"], op["answer"]))
        else:
            out.append(line)
    return "".join(out), done, warnings


def decided(md_text):
    """-> {n: "ok" | "skip" | "word:<text>"} — the plan as the applying stage
    must read it: ⛔ an open row is a skip (G21)."""
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
    print("%s  ·  %d op(s), %d photo(s)%s%s" % (
        out, len(data["rows"]), data["photos"],
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
    plan = decided(new_text)
    counts = {k: sum(1 for v in plan.values() if (v[:5] if k == "word:" else v) == k)
              for k in ("ok", "skip", "word:")}
    opened = sum(1 for op in parse_plan(new_text)["ops"] if not op["answer"])
    print("%s  ·  %d answer(s) %s  ·  %d ok, %d skip (%d left open), %d own word"
          % (md_path, len(done), "would be written (dry run)" if args.dry_run
             else "written", counts["ok"], counts["skip"], opened, counts["word:"]))
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
    a = sub.add_parser("apply", help="the owner's answers -> into the op lines")
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
