#!/usr/bin/env python3
"""Render a memory-review checkpoint page as a self-contained HTML artifact.

The markdown page stays the record and the parse target: `photo_memory.py
confirm` reads it, and nothing here writes to the pack. This script only
*renders* it onto a surface the owner can actually see, and `apply` splices
the owner's answer back into the same markdown so `confirm` is unchanged.

Two rules govern the whole file.

* **The `frames:` line is the storage key.** Every frame the page offers is
  read from it — never from list order, never by re-deriving a contact sheet.
  The record moves between render and confirm, and a frame number that no
  longer names the same photograph is a wrong memory written silently.
* **The output is UTF-8 and is checked for it.** A page whose text has been
  through a latin-1 round trip is valid UTF-8 of the wrong characters, so
  nothing raises; it simply arrives unreadable. In a script whose entire job
  is to show an owner their own words, that is a correctness failure, not a
  cosmetic one, and it is invisible in ASCII. `assert_clean_text` is the
  guard, and it runs on every render.
"""

import argparse
import base64
import io
import json
import os
import re
import sys

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - reported, never guessed around
    Image = None

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(os.path.dirname(HERE), "templates", "review-page.html")

MARK_DATA = "__" + "DATA" + "__"
MARK_TPL = "__" + "TEMPLATE_B64" + "__"

# What a latin-1 -> utf-8 re-encoding leaves behind. Every sequence here is a
# C1 control or a lone combining-looking Latin-1 letter followed by
# punctuation, which is what mojibake looks like and what real prose does not.
MOJIBAKE = re.compile("[ÂÃâ][-¿]")


def assert_clean_text(html, where):
    hits = MOJIBAKE.findall(html)
    if hits:
        raise SystemExit(
            "%s: text is double-encoded UTF-8 (%d sequence(s), first %r). "
            "The page would render every non-ASCII name as garbage; refusing "
            "to write it." % (where, len(hits), hits[0]))


# --------------------------------------------------------------- md parsing

RE_CHECKPOINT = re.compile(r"Checkpoint\s+(C\d+)")
RE_OWNER = re.compile(r"^owner:\s*(\S+)")
# The unit is a folder name and may hold spaces; it runs to the next ` · `.
RE_UNIT = re.compile(r"unit:\s*(.+?)(?:\s+·|\s*$)")
# G6 — the batch page's own name, written by `photo_memory review` as an
# ASCII mark outside the header fence. Its absence is a checkpoint page.
RE_PAGE_MARK = re.compile(r"<!-- sns-page: (P-B(\d{2,})) -->")
RE_PAGE_LINE = re.compile(r"^-?\s*page:\s*(\S+)\s*$", re.I)
# G6-6c — the place question (SNL) of a batch page, read on its ASCII keys:
# the `**S<n> ·` header, the `place:` counts line and the `name:`/`home:` row.
# The sentences between them are the owner's language and are shown verbatim.
RE_PLACE_HEAD = re.compile(r"^\*\*S(\d+)\s*·\s*(.+?)\*\*\s*(?:—\s*(.*))?$")
RE_PLACE_COUNTS = re.compile(r"`place:`\s*(\d+)\s*·\s*(\d+)\s*d\s*·\s*(\d+)\s*m")
RE_PLACE_IMG = re.compile(r"^>\s*!\[\]\((.+?)\)\s*$")
RE_PLACE_ROW = re.compile(r"^>\s*-\s*`?name:`?")
RE_PLACE_ANSWER = re.compile(
    r"^place:\s*(\d+)\s+name:\s*(.*?)(?:\s+home:\s*(.*?))?\s*$", re.I)
RE_PACK = re.compile(r"pack snapshot:\s*(sha256:[0-9a-f]+)")
RE_QUESTION = re.compile(
    r"^\*\*Q(\d+)\s*·\s*(.+?)\*\*\s*—\s*affects\s*(\d+)\s*file\(s\)"
    r"\s*/\s*(\d+)\s*batch\(es\)(?:\s*·\s*(.+?))?\s*$")
RE_TILE = re.compile(
    r"^>\s*\*\*(\d+)\*\*\s*·\s*(.+?)\s*·\s*(\d+)\s*file\(s\)"
    r"\s*/\s*(\d+)\s*batch\(es\)\s*$")
# F10: the phrase after ` · ` is where the frame was taken, written once by
# photo_memory and printed verbatim here, never re-worded in the page JS.
RE_IMG = re.compile(
    r"^>\s*!\[\]\((.+?)\)\s*\[frame\s+(\d+)\](?:\s*\(animal\s+[\d.]+\))?"
    r"(?:\s*·\s*(.*\S))?")
# Q8-c — which crop of a shared frame a line shows: `(animal 1.2)`.
RE_CROP_ANIMAL = re.compile(r"\[frame\s+\d+\]\s*\(animal\s+\d+\.(\d+)\)")
# HIL-4/5 — a one-animal frame's line is its crop with no `(animal …)`; the
# file name carries the detection, as photo_memory.CROP_FILE reads it.
RE_CROP_NAME = re.compile(r"(?:^|/)review-crops/[^/]+_d(\d+)\.jpg$")
# F26 — `<photo>.<animal>` on a `pick:` row; the same shape as
# photo_memory.CROP_REF, which this standalone script does not import.
RE_PICK_CROP = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])")
RE_FRAMES = re.compile(r"^>\s*`?frames:`?\s*(.+)$")
RE_SUBJECTS = re.compile(r"^>\s*`?subjects:`?\s*(.+)$")
# G6-6d — frames holding 2+ animals, `n=count`. Display only.
RE_ANIMALS = re.compile(r"^>\s*`?animals:`?\s*(.+)$")
# B4 — the name each frame's photo carries now, `n=Name + Name; n=Name`.
# Display only; `;` separates, because a name may hold a comma.
RE_NAMED = re.compile(r"^>\s*`?named:`?\s*(.+)$")
RE_REMEMBERED = re.compile(r"^###\s+Remembered already")
RE_QUESTIONS_H = re.compile(r"^###\s+Questions")
RE_RE_SUBJ = re.compile(
    r"^>\s*\*\*(.+?)\*\*\s*·\s*(\d+)\s*file\(s\)\s*/\s*(\d+)\s*batch\(es\)\s*$")
RE_RE_WHY = re.compile(r"^>\s*(shown because .+?)\s*$")
RE_RECHECK = re.compile(r"^>?\s*-?\s*`?recheck:`?\s*(subj-\d+)")

# `frames:` entries are `N=subj-0001 <vec_ref> <path>`, comma separated. The
# path may itself hold a comma, so the split is on the number that opens the
# next entry, never on every comma.
RE_FRAME_ENTRY = re.compile(
    r"(\d+)\s*=\s*(subj-\d+)\s+([0-9a-f]+)\s+(.+?)(?=,\s*\d+\s*=\s*subj-|$)")
RE_PAIR = re.compile(r"(\d+)\s*=\s*(subj-\d+)")


def parse_places(md_text):
    """-> [{"n", "title", "facts", "days", "months", "photos", "notes"}] for
    every place question on a batch page (G6-6c)."""
    places, cur = [], None
    for ln in md_text.splitlines():
        m = RE_PLACE_HEAD.match(ln.strip())
        if m:
            cur = {"n": int(m.group(1)), "title": m.group(2).strip(),
                   "facts": (m.group(3) or "").strip(), "days": None,
                   "months": None, "photos": [], "notes": []}
            places.append(cur)
            continue
        if cur is None or not ln.startswith(">"):
            cur = cur if (cur is not None and not ln.strip()) else None
            continue
        c = RE_PLACE_COUNTS.search(ln)
        if c:
            cur.update(days=int(c.group(2)), months=int(c.group(3)))
            continue
        if RE_PLACE_ROW.match(ln):
            continue
        im = RE_PLACE_IMG.match(ln)
        if im:
            cur["photos"].append(im.group(1))
            continue
        cur["notes"].append(ln[1:].strip())
    return [pl for pl in places if pl["days"] is not None]


def parse_review(md_text):
    """-> a dict of everything the page needs, read from the markdown alone."""
    lines = md_text.splitlines()
    out = {"checkpoint": "C1", "owner": "", "unit": "", "files": 0,
           "batches": 0, "pack": "", "questions": [], "recheck": [],
           "no_round": "", "page": "", "batch": None}
    mark = RE_PAGE_MARK.search(md_text)
    if mark:
        # ⛔ Never "C1" for a batch page: its answer is booked under its NAME.
        out.update(page=mark.group(1), batch=int(mark.group(2)), checkpoint="")
    out["places"] = parse_places(md_text) if mark else []

    for ln in lines[:12]:
        m = RE_CHECKPOINT.search(ln)
        if m:
            out["checkpoint"] = m.group(1)
        m = RE_OWNER.match(ln)
        if m:
            out["owner"] = m.group(1)
        m = RE_UNIT.search(ln)
        if m:
            out["unit"] = m.group(1)
        m = RE_PACK.search(ln)
        if m:
            out["pack"] = m.group(1)
        if ln.lower().startswith("no sns round here"):
            out["no_round"] = ln.strip()
        if ln.strip().startswith("fired because:"):
            out["fired"] = ln.split(":", 1)[1].strip()

    section = None
    q = None
    tile = None
    rsubj = None
    for ln in lines:
        if RE_QUESTIONS_H.match(ln):
            section = "q"
            continue
        if RE_REMEMBERED.match(ln):
            section = "r"
            rsubj = None
            continue
        if ln.startswith("### "):
            section = None
            continue

        if section == "q":
            m = RE_QUESTION.match(ln)
            if m:
                title = m.group(2).strip()
                kind = title.split("—")[-1].strip() if "—" in title else ""
                q = {"n": int(m.group(1)), "title": title, "kind": kind,
                     "files": int(m.group(3)), "batches": int(m.group(4)),
                     "span": (m.group(5) or "").strip(),
                     "tiles": [], "frames": {}, "subjects": {}, "where": {},
                     "animals": {}}
                out["questions"].append(q)
                tile = None
                continue
            if q is None:
                if "nothing to ask" in ln.lower():
                    out["no_round"] = ln.strip()
                continue
            m = RE_TILE.match(ln)
            if m:
                tile = {"tile": int(m.group(1)), "display": m.group(2).strip(),
                        "files": int(m.group(3)), "batches": int(m.group(4)),
                        "frames": []}
                q["tiles"].append(tile)
                continue
            m = RE_IMG.match(ln)
            if m and tile is not None:
                if int(m.group(2)) not in tile["frames"]:
                    tile["frames"].append(int(m.group(2)))
                if m.group(3):
                    q["where"][int(m.group(2))] = m.group(3)
                crop = RE_CROP_ANIMAL.search(ln)
                alone = RE_CROP_NAME.search(m.group(1))
                if crop:
                    q.setdefault("crops", {}).setdefault(int(m.group(2)), []).append(
                        (int(crop.group(1)), m.group(1)))
                elif alone:
                    # HIL-5 — the markdown shows this frame as its one crop,
                    # so the web tile must too: the whole photo can hold an
                    # animal the detector missed, and the owner then names
                    # the photo for an animal the crop is not.
                    q.setdefault("crops", {})[int(m.group(2))] = [
                        (int(alone.group(1)) + 1, m.group(1))]
                    q.setdefault("alone", {})[int(m.group(2))] = m.group(1)
                continue
            m = RE_FRAMES.match(ln)
            if m:
                for num, sid, ref, path in RE_FRAME_ENTRY.findall(m.group(1)):
                    q["frames"][int(num)] = {
                        "subject_id": sid, "key": ref,
                        "path": path.strip().rstrip(",")}
                continue
            m = RE_SUBJECTS.match(ln)
            if m:
                for num, sid in RE_PAIR.findall(m.group(1)):
                    q["subjects"][int(num)] = sid
                continue
            m = RE_ANIMALS.match(ln)
            if m:
                for num, count in re.findall(r"(\d+)\s*=\s*(\d+)", m.group(1)):
                    q["animals"][int(num)] = int(count)
                continue
            m = RE_NAMED.match(ln)
            if m:
                for part in m.group(1).split(";"):
                    num, _, names = part.partition("=")
                    if num.strip().isdigit() and names.strip():
                        q.setdefault("named", {})[int(num)] = names.strip()
                continue

        elif section == "r":
            m = RE_RE_SUBJ.match(ln)
            if m:
                rsubj = {"name": m.group(1).strip(), "files": int(m.group(2)),
                         "batches": int(m.group(3)), "frames": [],
                         "paths": {}, "where": {}, "why": "",
                         "subject_id": ""}
                out["recheck"].append(rsubj)
                continue
            if rsubj is None:
                continue
            m = RE_IMG.match(ln)
            if m:
                n = int(m.group(2))
                # HIL-7 — a shared frame is one line per crop, one frame.
                if n not in rsubj["frames"]:
                    rsubj["frames"].append(n)
                    rsubj["paths"][n] = m.group(1)
                crop = RE_CROP_ANIMAL.search(ln)
                if crop:
                    rsubj.setdefault("crops", {}).setdefault(n, []).append(
                        (int(crop.group(1)), m.group(1)))
                if m.group(3):
                    rsubj["where"][n] = m.group(3)
                continue
            m = RE_RE_WHY.match(ln)
            if m:
                rsubj["why"] = m.group(1).strip()
                continue
            m = RE_RECHECK.match(ln)
            if m:
                rsubj["subject_id"] = m.group(1)
                continue
    return out


# ------------------------------------------------------------------ images

def encode_image(path, max_px, quality):
    """-> a data: URI, downscaled and EXIF-rotated for DISPLAY only.

    ⛔ This is not a crop (ONB-11) and not an exemplar. The exemplar is the
    file the `frames:` line names; what the page shows is a thumbnail of it.
    EXIF orientation is applied because a sideways contact sheet is what a
    39% -sideways benchmark taught us the owner is actually shown.
    """
    if Image is None:
        raise SystemExit("Pillow is required to embed images: pip install pillow")
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ------------------------------------------------------------------ known

def known_names(pack_dir):
    """-> the names this pack already remembers, for the SNS-7/14 collision."""
    if not pack_dir:
        return []
    path = os.path.join(pack_dir, "photo-subjects", "subjects.json")
    if not os.path.exists(path):
        return []
    with io.open(path, encoding="utf-8") as fh:
        reg = json.load(fh)
    out = []
    for s in reg.get("subjects", []):
        name = (s.get("name") or "").strip()
        if not name or s.get("state") == "rejected" \
                or s.get("status") == "rejected":
            continue
        out.append({"name": name, "subject_id": s.get("subject_id", ""),
                    "files": (s.get("origin") or {}).get("files", 0)})
    return out


# ----------------------------------------------------------------- render

def build_round_data(rev, q, workdir, max_px, quality, pack_dir):
    frames = {}
    for n, f in sorted(q["frames"].items()):
        src = os.path.join(workdir, f["path"])
        if not os.path.exists(src):
            raise SystemExit(
                "frame %d points at %s, which does not exist. The `frames:` "
                "line is the storage key and is never guessed around — "
                "re-render the checkpoint instead." % (n, src))
        alone = q.get("alone", {}).get(n)
        if alone and os.path.exists(os.path.join(workdir, alone)):
            src = os.path.join(workdir, alone)
        frames[str(n)] = {
            "subject_id": f["subject_id"], "key": f["key"],
            "file": os.path.basename(f["path"]),
            "batch": _batch_of(f["path"]),
            "role": f.get("role", "exemplar"),
            "where": q.get("where", {}).get(n, ""),
            "animals": q.get("animals", {}).get(n, 1),
            "named": q.get("named", {}).get(n, ""),
            "crops": [{"animal": a,
                       "data": encode_image(os.path.join(workdir, c), max_px, quality)
                       if os.path.exists(os.path.join(workdir, c)) else ""}
                      for a, c in q.get("crops", {}).get(n, [])],
            "data": encode_image(src, max_px, quality)}

    recheck = []
    for r in rev["recheck"]:
        for n in r["frames"]:
            src = os.path.join(workdir, r["paths"][n])
            if not os.path.exists(src):
                continue
            frames[str(n)] = {
                "subject_id": r["subject_id"], "key": "",
                "file": os.path.basename(r["paths"][n]),
                "batch": _batch_of(r["paths"][n]), "role": "represented",
                "where": r["where"].get(n, ""),
                "crops": [{"animal": a,
                           "data": encode_image(os.path.join(workdir, c), max_px, quality)
                           if os.path.exists(os.path.join(workdir, c)) else ""}
                          for a, c in r.get("crops", {}).get(n, [])],
                "data": encode_image(src, max_px, quality)}
        recheck.append({"subject_id": r["subject_id"], "name": r["name"],
                        "files": r["files"], "batches": r["batches"],
                        "why": r["why"],
                        "frames": [n for n in r["frames"]
                                   if str(n) in frames]})

    places = []
    for pl in rev.get("places") or []:
        # Already through the U3-06 document check when the page was written;
        # re-encoded here as a thumbnail with no EXIF, like every frame.
        photos = [encode_image(os.path.join(workdir, rel), max_px, quality)
                  for rel in pl["photos"] if os.path.exists(os.path.join(workdir, rel))]
        places.append({"n": pl["n"], "title": pl["title"], "facts": pl["facts"],
                       "days": pl["days"], "months": pl["months"],
                       "notes": pl["notes"], "photos": photos})

    return {"question": q["title"] if q else "",
            "kind": (q["kind"] if q else "") or "subject",
            "checkpoint": rev["checkpoint"], "unit": rev["unit"],
            "files": q["files"] if q else 0,
            "batches": q["batches"] if q else 0,
            "span": q["span"] if q else "",
            "pack": rev["pack"], "no_round": rev["no_round"],
            "tiles": [{"tile": t["tile"], "display": t["display"],
                       "files": t["files"], "batches": t["batches"],
                       "subject_id": q["subjects"].get(t["tile"], ""),
                       "frames": t["frames"]} for t in (q["tiles"] if q else [])],
            "frames": frames, "recheck": recheck,
            "known_names": known_names(pack_dir),
            # G6-6 — a batch page: its name and batch, and the owner's own
            # animal names offered as the natural choice for a group.
            "page": rev.get("page", ""), "batch": rev.get("batch"),
            "places": places,
            "name_suffixes": name_suffixes()}


def name_suffixes():
    """-> the `name:` answer suffixes (` same subj-NNNN`, ` same`,
    ` distinct`) as `photo_memory`'s parser reads them.

    Handed to the page so the answer table shows the NAME the parser will
    store, stripping exactly what the parser strips — one set of patterns,
    so display and parse cannot drift (LL-PHO-188). Display only: the page
    still emits the owner's typing byte for byte."""
    import photo_memory
    return [p.pattern for p in (photo_memory.NAME_SAME_AS,
                                photo_memory.NAME_SAME,
                                photo_memory.NAME_DISTINCT)]


def _batch_of(path):
    m = re.search(r"batch-(\d+)", path)
    return m.group(1) if m else ""


def render(template, data):
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    tpl_b64 = base64.b64encode(template.encode("utf-8")).decode("ascii")
    html = template.replace(MARK_TPL, tpl_b64).replace(MARK_DATA, payload)
    return html


# ------------------------------------------------------------------ apply

RE_ANSWER_ROW = re.compile(r"^(>\s*-\s*`?(?:pick|skip|recheck)`?:).*$")
BLANK_ROW = re.compile(r"_{2,}")

ROUND_DATA_OPEN = '<script id="round-data" type="application/json">'


def read_answer(raw):
    """-> the owner's rows, from any of the shapes the answer actually arrives in.

    Four, and the last is the one tomorrow uses. When the owner presses
    Confirm the page republishes ITSELF with the answer merged into its own
    round-data, so what comes back from the artifact is a whole HTML document
    with `submitted.lines` buried in it. Every earlier shape is what a person
    pastes. ⛔ A shape this cannot read must RAISE: the failure mode being
    guarded against is a JSON blob falling through to the line splitter and
    writing nothing the parser recognises, which looks like an owner who
    answered nothing rather than like a bug.
    """
    text = raw.strip()

    if ROUND_DATA_OPEN in text:
        a = text.index(ROUND_DATA_OPEN) + len(ROUND_DATA_OPEN)
        b = text.index("</script>", a)
        # The page escapes `</` on the way out so the JSON cannot close its own
        # script tag; undo exactly that, and nothing else.
        text = text[a:b].replace("<\\/", "</")

    if text.startswith("{") or text.startswith("["):
        payload = json.loads(text)
        for get in (lambda p: p,
                    lambda p: p["lines"],
                    lambda p: p["submitted"]["lines"]):
            try:
                lines = get(payload)
            except (KeyError, TypeError):
                continue
            if isinstance(lines, list) and all(isinstance(x, str)
                                               for x in lines):
                return lines
        raise SystemExit(
            "the answer is JSON but carries no list of rows — looked at the "
            "value itself, `lines`, and `submitted.lines`. Nothing was "
            "written.")

    return [l for l in raw.splitlines() if l.strip()]


def apply_answer(md_text, answer_lines):
    """Splice the owner's rows into the markdown -> the new text. See
    `apply_answer_report()`."""
    return apply_answer_report(md_text, answer_lines)[0]


def apply_answer_report(md_text, answer_lines):
    """Splice the owner's rows into the markdown, in the text path's shape.
    -> (new text, [earlier answer rows this answer replaced]).

    The page emits rows without the rendered backticks; the markdown carries
    them, and `parse_review()` in photo_memory.py accepts either. Writing the
    backticked form keeps a rendered page and an answered page the same
    document, so a diff shows the answer and nothing else.

    ⭐ M6 — the answer is the page's WHOLE answer, so it REPLACES what an
    earlier apply wrote: every pick row of the question the page shows (not
    only the first), its `skip:` row, and every `recheck:` value. A filled row
    the new answer does not carry is put back to blank. It used to survive a
    re-apply beside the new rows, and nothing said so (UAT01-9 F3b).
    """
    picks, skips, rechecks, places = [], [], {}, {}
    for ln in answer_lines:
        t = ln.strip().lstrip("-").strip()
        found = RE_PLACE_ANSWER.match(t)
        if found:
            places[int(found.group(1))] = (found.group(2).strip(),
                                           (found.group(3) or "").strip())
        elif t.lower().startswith("pick:"):
            picks.append(t)
        elif t.lower().startswith("skip:"):
            skips.append(t)
        elif t.lower().startswith("recheck:"):
            m = re.match(r"recheck:\s*(subj-\d+)\s*(.*)$", t, re.I)
            if m:
                rechecks[m.group(1)] = m.group(2).strip()

    def backticked(row):
        for key in ("pick", "who", "name", "skip"):
            row = re.sub(r"\b%s:" % key, "`%s:`" % key, row, count=1)
        return row

    blank_pick = "`pick:` ______   `who:` ______   `name:` ______"
    out, replaced = [], []
    used_pick, used_skip, place_n = False, False, None
    question, pick_question = 0, None
    for ln in md_text.splitlines():
        if ln.strip().startswith("**Q"):
            question += 1
        head = RE_PLACE_HEAD.match(ln.strip())
        if head:
            place_n = int(head.group(1))
        if place_n in places and RE_PLACE_ROW.match(ln) and places[place_n][0]:
            name, home = places[place_n]
            comment = ln.split("<!--", 1)
            tail = " <!--" + comment[1] if len(comment) > 1 else ""
            out.append("> - `name:` %s   `home:` %s%s"
                       % (name, home or "______", tail))
            continue
        m = RE_ANSWER_ROW.match(ln)
        if not m:
            out.append(ln)
            continue
        head = m.group(1)
        comment = ln.split("<!--", 1)
        tail = " <!--" + comment[1] if len(comment) > 1 else ""
        filled = not BLANK_ROW.search(ln.split("<!--", 1)[0])
        pre = head[:head.index("-") + 1]
        key = re.search(r"(pick|skip|recheck)", head, re.I).group(1).lower()

        if key == "pick":
            # Every pick row lands at the FIRST pick row, so a page that
            # returns three groups against a template that rendered two rows
            # still writes three. The rest of THAT question's pick rows go:
            # a blank one is a template row nothing filled, and a filled one
            # is an earlier answer this one replaces. Another question's rows
            # are its own and are left as they are.
            if not used_pick:
                used_pick, pick_question = True, question
                if filled:
                    replaced.append(ln.split("<!--", 1)[0].strip())
                if picks:
                    for p in picks:
                        out.append("%s %s%s" % (pre, backticked(p), tail))
                else:
                    out.append("%s %s%s" % (pre, blank_pick, tail))
                continue
            if question == pick_question:
                if filled:
                    replaced.append(ln.split("<!--", 1)[0].strip())
                    continue
                if picks:
                    continue
        elif key == "skip" and not used_skip:
            used_skip = True
            if filled:
                replaced.append(ln.split("<!--", 1)[0].strip())
            out.append("%s %s%s" % (pre, backticked(skips[0]) if skips
                                    else "`skip:` ______", tail))
            continue
        elif key == "recheck":
            sid = RE_RECHECK.match(ln)
            sid = sid.group(1) if sid else ""
            value = rechecks.get(sid) or ""
            if sid and (value or filled):
                if filled:
                    replaced.append(ln.split("<!--", 1)[0].strip())
                out.append("%s `recheck:` %s %s%s"
                           % (pre, sid, value or "______", tail))
                continue
        out.append(ln)
    return ("\n".join(out) + ("\n" if md_text.endswith("\n") else ""),
            [r for r in replaced if r])


# ------------------------------------------------------------------- main

def cmd_render(args):
    md_path = os.path.abspath(args.review)
    workdir = args.workdir or os.path.dirname(md_path)
    with io.open(md_path, encoding="utf-8") as fh:
        md_text = fh.read()
    assert_clean_text(md_text, md_path)

    rev = parse_review(md_text)
    qs = rev["questions"]
    q = None
    if qs:
        wanted = args.question
        picked = [x for x in qs if x["n"] == wanted] if wanted else qs[:1]
        if not picked:
            raise SystemExit("no Q%d in %s (found %s)"
                             % (wanted, md_path,
                                ", ".join("Q%d" % x["n"] for x in qs)))
        q = picked[0]
        if len(qs) > 1:
            sys.stderr.write(
                "note: %d questions in this checkpoint; rendering Q%d (%s). "
                "Render the others with --question.\n"
                % (len(qs), q["n"], q["title"]))
    if q is None and not rev["recheck"] and not rev.get("places"):
        raise SystemExit(
            "%s carries no question, nothing re-presented and no place to "
            "name — there is nothing for an owner to answer on a page."
            % md_path)

    with io.open(TEMPLATE, encoding="utf-8") as fh:
        template = fh.read()
    assert_clean_text(template, TEMPLATE)

    empty = {"tiles": [], "frames": {}, "subjects": {}, "files": 0,
             "batches": 0, "span": "", "title": "", "kind": ""}
    data = build_round_data(rev, q or empty, workdir,
                            args.max_px, args.quality, args.pack)
    html = render(template, data)
    assert_clean_text(html, args.out)

    out = args.out or os.path.join(
        os.path.dirname(md_path),
        ("%s.html" % rev["page"]) if rev["page"]
        else "memory-review_%s.html" % rev["checkpoint"])
    with io.open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    mb = len(html.encode("utf-8")) / 1048576.0
    print("%s  ·  %s %s  ·  %d frame(s), %d tile(s), %d re-presented, %d place(s)  ·  %.1f MB"
          % (out, rev["unit"], rev["page"] or rev["checkpoint"], len(data["frames"]),
             len(data["tiles"]), len(data["recheck"]), len(data["places"]), mb))
    if mb > 15.0:
        sys.stderr.write(
            "WARNING: %.1f MB is at the 16 MB artifact ceiling. Re-render "
            "with a smaller --max-px.\n" % mb)
    return 0


def cmd_apply(args):
    md_path = os.path.abspath(args.review)
    with io.open(md_path, encoding="utf-8") as fh:
        md_text = fh.read()
    raw = (sys.stdin.read() if args.answer == "-"
           else io.open(args.answer, encoding="utf-8").read())
    answer_lines = read_answer(raw)
    # G6-6 (G4) — an answer is tied to its page. A batch page's answer names
    # its page on a `page:` line, and lands only on the Markdown carrying that
    # page's mark; a checkpoint page's answer names none, and lands only on a
    # checkpoint page.
    named = [m.group(1) for m in (RE_PAGE_LINE.match(l.strip()) for l in answer_lines)
             if m]
    mark = RE_PAGE_MARK.search(md_text)
    target = mark.group(1) if mark else ""
    if (named[:1] or [""])[0] != target or len(set(named)) > 1:
        # FIX6 (U6-14) — a typed answer for a batch page has no `page:` line
        # unless someone says so; say the line to add.
        fix = (" If this answer IS for %s, add this as its first line:\n"
               "  page: %s" % (target, target)) if target and not named else ""
        raise SystemExit(
            "this answer is for %s and %s is %s — nothing was written. Apply "
            "an answer to the page it was given on.%s"
            % (("page " + named[0]) if named else "a checkpoint page", md_path,
               ("page " + target) if target else "a checkpoint page", fix))
    answer_lines = [l for l in answer_lines if not RE_PAGE_LINE.match(l.strip())]
    crop_picks = []
    for line in answer_lines:
        t = line.strip().lstrip("-").strip()
        if t.lower().startswith("pick:"):
            pick = re.split(r"\b(?:who|name):", t[5:], maxsplit=1)[0]
            crop_picks += RE_PICK_CROP.findall(pick)
    if crop_picks:
        raise SystemExit(
            "`pick:` takes photo numbers only, never `<photo>.<animal>` like "
            "%s — nothing was written. To name each animal in one photo, put "
            "the photo number on one row per name: `pick: %s` with one name, "
            "and a second row `pick: %s` with the other."
            % (", ".join("%s.%s" % r for r in crop_picks), crop_picks[0][0],
               crop_picks[0][0]))

    new_text, replaced = apply_answer_report(md_text, answer_lines)
    assert_clean_text(new_text, md_path)
    if new_text == md_text:
        raise SystemExit("nothing changed — no answer row matched %s" % md_path)
    if not args.dry_run:
        with io.open(md_path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
    if args.dry_run:
        # FIX7 (U7-3) — the rows themselves, so the answer can be read before
        # it is written and before `confirm` reads it.
        print("%s  ·  %d row(s) would be written (dry run — nothing written):"
              % (md_path, len(answer_lines)))
        for line in answer_lines:
            print("  %s" % line.strip())
        for line in replaced:
            print("  replaces the earlier row: %s" % line)
        return 0
    print("%s  ·  %d row(s) written" % (md_path, len(answer_lines)))
    for line in replaced:
        print("  replaced the earlier row: %s" % line)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("render", help="markdown checkpoint -> HTML artifact")
    r.add_argument("review", help="path to memory-review_C<N>.md")
    r.add_argument("-o", "--out", default=None)
    r.add_argument("--workdir", default=None,
                   help="root the frames: paths are relative to "
                        "(default: the markdown's own directory)")
    r.add_argument("--pack", default=None,
                   help="owner pack directory, for the names it already knows")
    r.add_argument("--question", type=int, default=0)
    r.add_argument("--max-px", type=int, default=640)
    r.add_argument("--quality", type=int, default=72)
    r.set_defaults(func=cmd_render)

    a = sub.add_parser("apply", help="owner's answer -> back into the markdown")
    a.add_argument("review")
    a.add_argument("--answer", required=True,
                   help="file holding the emitted rows or the submitted JSON; "
                        "- for stdin")
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_apply)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
