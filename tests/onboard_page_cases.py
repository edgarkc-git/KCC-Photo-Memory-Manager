#!/usr/bin/env python3
"""Cases for photo_onboard_page.py — the rendered onboarding checkpoint.

Every fixture is invented: three devices, four screen-size candidates and two
places that behave like residences, built from generated images and a manifest
this file writes.

The case this suite exists for is the coordinate one. This page is the first
surface in the pipeline that is BOTH published to somewhere the owner did not
choose AND rendered from `home_candidates()`, whose every row is a residence's
coordinate. Operational Rule 3 is enforced here by a default, and a default is
exactly the kind of thing a later edit flips without noticing — so the absence
is asserted against the rendered bytes, not against the flag.
"""

import base64
import contextlib
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import photo_onboard_page as op  # noqa: E402
import photo_profile  # noqa: E402

# The pack a new owner is really given. Read, never restated: the whole of
# U3-32 layer 1 is that this file said something the code did not.
TEMPLATE_PROFILE = os.path.join(os.path.dirname(HERE), "templates",
                                "photo-memory", "_template",
                                "photo-profile.json")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %-5s %-64s %s" % ("ok" if cond else "FAIL", name, detail))


class JSNum(int):
    """A JS number, for the one thing JS does here that Python will not: 1 + "a"."""

    def __add__(self, other):
        if isinstance(other, str):
            return str(int(self)) + other
        return int(self) + other

    def __radd__(self, other):
        if isinstance(other, str):
            return other + str(int(self))
        return other + int(self)


RE_TERNARY = re.compile(r'\(\s*(\w+)\s*===\s*(\d+)\s*\?\s*("[^"]*")\s*:\s*("[^"]*")\s*\)')


def cut_clause(tpl, var):
    """The one `cut.push(...)` clause guarded by `var`, rewritten as Python."""
    m = re.search(r"if\(%s\)\s*cut\.push\((.*?)\);" % var, tpl, re.S)
    if not m:
        return None
    return "(" + RE_TERNARY.sub(r"(\3 if \1 == \2 else \4)", m.group(1)) + ")"


def cut_says(tpl, var, n):
    """What that clause puts on the page for n. No DOM, so it is evaluated."""
    expr = cut_clause(tpl, var)
    if expr is None:
        return None
    return eval(expr, {"__builtins__": {}}, {var: JSNum(n)})


def jpg(path, w=40, h=60):
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (w, h), (90, 120, 150)).save(path, "JPEG")


COLS = ["SourceFile", "FileName", "FileType", "FileSize", "DateTimeOriginal",
        "CreateDate", "GPSPosition", "Make", "Model", "Software",
        "ImageWidth", "ImageHeight", "Duration", "UserComment"]

# Places far enough apart that HOME_MATCH_KM cannot merge them, and none of
# them anywhere anybody lives.
HOME_1 = "10.500000 20.500000"
HOME_2 = "40.500000 50.500000"
# The shape U2-02 was measured on: a real residence photographed like a
# visitor. It misses BOTH bars, so it is proposed nowhere — and it is the row
# whose absence cost an owner their third home.
HOME_3 = "-30.500000 60.500000"
# Five more that miss a bar, which is one over the cap, and one place seen on
# a single daytime visit, which the reporting filter drops. Both cuts have to
# be printed or the page repeats the defect it is disclosing.
NEAR = ["%d.500000 %d.500000" % (n, n + 5) for n in range(61, 66)]
ONE_VISIT = "80.500000 5.500000"


def row(src, name, ftype="JPEG", when="", gps="-", make="-", model="-",
        w="4000", h="3000"):
    return {"SourceFile": src, "FileName": name, "FileType": ftype,
            "FileSize": "1000", "DateTimeOriginal": when, "CreateDate": when,
            "GPSPosition": gps, "Make": make, "Model": model, "Software": "-",
            "ImageWidth": w, "ImageHeight": h, "Duration": "-",
            "UserComment": "-"}


def build_workdir(tmp):
    """A collection with three devices, four screen sizes and two residences.

    ⛔ The screen sizes are seeded so the CORRECT one is NOT the most common:
    that inversion is the defect this page was built for, and a fixture where
    the top row happens to be right would let a regression pass.
    """
    wd = os.path.join(tmp, "unit-alpha")
    src = os.path.join(tmp, "src")
    rows = []

    def add(n, **kw):
        for i in range(n):
            name = "f%04d.jpg" % len(rows)
            path = os.path.join(src, name)
            jpg(path)
            rows.append(row(path, name, **kw))

    # Devices: one obvious owner, one tail device, one clearly foreign.
    add(30, when="2031:03:0%d 12:00:00" % 1, make="Zenith", model="Q1")
    add(3, when="2031:03:02 12:00:00", make="Zenith", model="Q1 Pro")
    add(2, when="2031:03:03 12:00:00", make="Corvid", model="X")

    # Screen candidates. 900x1600 is the real screen and is the RAREST.
    add(9, w="1000", h="1400")
    add(6, w="800", h="1200")
    add(4, w="900", h="1600")

    # Home 1: many days, plenty after dark -> a residence.
    for d in range(1, 9):
        add(2, when="2031:04:%02d 21:30:00" % d, gps=HOME_1,
            make="Zenith", model="Q1")
    # Home 2: the trip hotel. Same shape, fewer days, one month.
    for d in range(1, 6):
        add(3, when="2031:06:%02d 22:15:00" % d, gps=HOME_2,
            make="Zenith", model="Q1")

    # Home 3: a residence photographed like a visitor. Four days against a bar
    # of five, one evening against a bar of three — it clears neither, so
    # nothing proposes it, and it is somebody's home.
    for d in range(1, 5):
        add(2, when="2031:07:%02d %s" % (d, "20:10:00" if d == 1 else "13:00:00"),
            gps=HOME_3, make="Zenith", model="Q1")
    # Five more near misses, so the sixth is over the cap.
    for i, gps in enumerate(NEAR):
        for d in range(1, 3):
            add(1, when="2031:08:%02d 1%d:00:00" % (d, i), gps=gps,
                make="Zenith", model="Q1")
    # One daytime visit to one spot: withheld, and not even shown.
    add(1, when="2031:09:01 11:00:00", gps=ONE_VISIT, make="Zenith", model="Q1")

    os.makedirs(wd, exist_ok=True)
    with io.open(os.path.join(wd, "manifest.csv"), "w", encoding="utf-8",
                 newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLS)
        wr.writeheader()
        for r in rows:
            wr.writerow(r)
    return wd


def data_of(html):
    m = op.RE_DATA.search(html)
    return json.loads(m.group(1))


def render_to_with(wd, out, *extra):
    """`render` with extra flags — the pack-bound page, which is the only way
    to see what this page says about a setting it reads from the pack."""
    op.main(["render", wd, "--out", out, *extra])
    with io.open(out, encoding="utf-8") as fh:
        return fh.read()


def render_to(wd, out, with_coords, coords_out=None):
    argv = ["render", wd, "--out", out]
    if with_coords:
        argv.append("--with-coords")
    if coords_out:
        argv += ["--coords-out", coords_out]
    op.main(argv)
    with io.open(out, encoding="utf-8") as fh:
        return fh.read()


def js_code(text):
    """`text` with /* */ comments stripped.

    ⛔ Use this before ANY substring assertion over this template. A comment
    explaining a rule contains the words the rule forbids — the block saying
    why `near_misses` is excluded names `near_misses`, and the one recording
    that the visit line used to say "still never named" quotes it. Both made a
    source-level check fail on its own documentation. Measured, twice.
    """
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def run_optional(near, answers):
    """Actually EXECUTE the page's `optional()` with node. -> its rows, or None.

    ⛔ Run, not read. E7 was a logic hole — a started-but-nameless row
    acknowledged nowhere — and a source-level assertion on the spelling of
    this function would have passed straight over it. Two findings in a row
    lived only in this file's JS, so the JS is what gets exercised.

    Skips visibly when node is absent rather than failing: the rest of this
    suite is stdlib and must stay runnable on a machine with no JS engine.
    """
    node = shutil.which("node")
    if not node:
        return None
    tpl = io.open(os.path.join(os.path.dirname(HERE), "templates",
                               "onboarding-page.html"), encoding="utf-8").read()
    if "function optional()" not in tpl:
        # ⛔ Report, never raise. An absent function is exactly the state this
        # case exists to catch, and a ValueError here would abort the whole
        # suite instead of failing one line — which is what it did the first
        # time I ran the red proof.
        return [["optional() is not defined in this template", ""]]
    start = tpl.index("function optional()")
    depth, i = 0, tpl.index("{", start)
    while True:                      # brace-match, so the body is exact
        if tpl[i] == "{":
            depth += 1
        elif tpl[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = tpl[start:i + 1]
    script = ("var D = %s, state = %s;\n%s\nconsole.log(JSON.stringify("
              "optional()));" % (json.dumps({"homes": {"near_misses": near}}),
                                 json.dumps({"homes": answers}), body))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True)
    if out.returncode != 0:
        return [["node failed", out.stderr.strip()[:120]]]
    return json.loads(out.stdout)


def js_fn_body(tpl, name):
    """-> the source of `function <name>()`, brace-matched so the body is exact."""
    start = tpl.index("function %s()" % name)
    depth, i = 0, tpl.index("{", start)
    while True:
        if tpl[i] == "{":
            depth += 1
        elif tpl[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return tpl[start:i + 1]


def run_lines(state):
    """Actually EXECUTE the page's `lines()` with node. -> the answer lines.

    ⛔ Run, not read. `lines()` is the SINGLE reader of the owner's answers —
    `photo_onboard_page.py` parses `submitted["lines"]` and deliberately
    ignores the raw `screens` object beside it ("the write path has one
    reader, not two"), so whatever this function omits is simply lost. A
    source-level assertion on its spelling would pass straight over that.

    Skips visibly when node is absent, like `run_optional`.
    """
    node = shutil.which("node")
    if not node:
        return None
    tpl = io.open(os.path.join(os.path.dirname(HERE), "templates",
                               "onboarding-page.html"), encoding="utf-8").read()
    if "function lines()" not in tpl:
        return [["lines() is not defined in this template", ""]]
    full = dict({"makes": {}, "screens": {}, "homes": {}, "language": "",
                 "types": "", "away": "", "pets": ""}, **state)
    script = ('var KEY = {makes:"makes", screen:"screen", home:"home", '
              'language:"language", types:"types", away:"away_km", '
              'pets:"pets"};\nvar state = %s;\n%s\n'
              'console.log(JSON.stringify(lines()));'
              % (json.dumps(full), js_fn_body(tpl, "lines")))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True)
    if out.returncode != 0:
        return [["node failed", out.stderr.strip()[:200]]]
    return json.loads(out.stdout)


def js_lines_cases():
    """-> (label, got, want) for how each screen answer is serialised.

    ⭐ REPRODUCTION (Release B, M12). UAT02-01: the owner pressed "Not a
    screen" and `declined_screen_dims` stayed EMPTY. The refusal was dropped
    before it was ever written — `lines()` skipped a `false` outright — while
    the page's own checklist ticked "Every size answered" green, because
    `false` is a defined value. So the page confirmed the answer was taken and
    then threw it away, and the size stayed unanswered in the pack.

    ⛔ The home half of the same function has always written its refusal
    (`home: <id> = not a place`). Screens were the odd one out; that asymmetry
    is the defect, not a design choice.
    """
    for label, state, want in (
        ("a refusal is written, not dropped (REPRODUCTION)",
         {"screens": {"1170x2532": False}}, ["screen: 1170x2532 = no"]),
        ("an accepted size with no device named stays bare",
         {"screens": {"1170x2532": ""}}, ["screen: 1170x2532"]),
        ("an accepted size names its device",
         {"screens": {"1170x2532": "iPhone 12"}},
         ["screen: 1170x2532 = iPhone 12"]),
        ("a refusal and an acceptance both survive together",
         {"screens": {"1170x2532": False, "2796x1290": "iPhone 15"}},
         ["screen: 1170x2532 = no", "screen: 2796x1290 = iPhone 15"]),
        # GUARD, not a reproduction: the refusal this emits has to be the
        # exact form the parser turns back into `False` — `= no`. The two
        # halves are in different languages and only meet here.
        ("an untouched size is not mentioned at all (guard)", {}, []),
    ):
        got = run_lines(state)
        if got is None:
            print("  SKIP  lines(): %s — node not installed" % label)
            continue
        yield label, got, want


def run_unfinished(data, state):
    """EXECUTE the page's `unfinished()` with node. -> its rows, or None.

    Skips visibly when node is absent, like `run_optional`/`run_lines`.
    """
    node = shutil.which("node")
    if not node:
        return None
    tpl = io.open(os.path.join(os.path.dirname(HERE), "templates",
                               "onboarding-page.html"), encoding="utf-8").read()
    if "function unfinished()" not in tpl:
        return [["unfinished() is not defined in this template", ""]]
    full = dict({"makes": {}, "screens": {}, "homes": {}, "language": "",
                 "types": "", "away": "", "pets": ""}, **state)
    script = ("var D = %s, state = %s;\n%s\n%s\n"
              "console.log(JSON.stringify(unfinished()));"
              % (json.dumps(data), json.dumps(full),
                 js_fn_body(tpl, "todo"), js_fn_body(tpl, "unfinished")))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True)
    if out.returncode != 0:
        return [["node failed", out.stderr.strip()[:200]]]
    return json.loads(out.stdout)


def js_unfinished_cases():
    """-> (label, got, want).

    ⭐ REPRODUCTION (Release B, the M12 leftover). The page's Confirm sent
    whatever was answered and said NOTHING about what was not: `btn-confirm`
    serialises `lines()` and posts, and nothing gates or comments on `todo()`.
    A blank screen size and a blank trip distance both went through in silence
    on UAT02-01.

    ⛔ WARN ONLY — no block, no second press (owner ruling: "ask, but never
    block"). This function only NAMES what is unfinished; the send proceeds.
    """
    data = {"cameras": {"devices": [{"make": "Acme", "model": "One"}]},
            "screens": {"candidates": [{"dims": ["1080", "2340"]}]},
            "homes": {"rows": [{"id": "A"}], "near_misses": []}}
    answered = {"makes": {"Acme One": True},
                "screens": {"1080x2340": False},
                "homes": {"A": {"kind": "live", "label": ""}},
                "language": "en", "types": "trip", "away": "3"}
    for label, state, want in (
        ("nothing answered names every required row", {},
         ["Every camera answered", "Every size answered",
          "Every proposed area named or rejected", "Language picked",
          "Folder kinds given", "Trip distance given"]),
        ("a fully answered page warns about nothing", answered, []),
        # ⛔ A REFUSAL IS AN ANSWER — the same rule the engine side follows.
        ("a refused size is not called unfinished",
         dict(answered, screens={"1080x2340": False}), []),
        ("a blank trip distance is named",
         dict(answered, away=""), ["Trip distance given"]),
        ("a blank size is named",
         dict(answered, screens={}), ["Every size answered"]),
    ):
        got = run_unfinished(data, state)
        if got is None:
            print("  SKIP  unfinished(): %s — node not installed" % label)
            continue
        yield label, got, want


def js_optional_cases():
    """-> (label, got, want) for each state a withheld row can be in."""
    rows = [{"id": "C"}, {"id": "D"}, {"id": "E"}]
    for label, answers, want in (
        ("untouched rows read as an optional opportunity", {},
         [["3 places not proposed as homes, not yet named — optional", "opt"]]),
        # ⭐ E7. This is the case that was invisible: the owner clicked, left
        # the name empty, and NOTHING on the page acknowledged the row.
        ("a started-but-nameless row is acknowledged (REPRODUCTION)",
         {"C": {"kind": "place", "label": ""}},
         [["Area C — you started naming this; nothing is recorded until you "
           "type the name", "start"],
          ["2 places not proposed as homes, not yet named — optional", "opt"]]),
        ("a named one reads as a win",
         {"C": {"kind": "place", "label": "Kampong Glam"}},
         [["2 places not proposed as homes, not yet named — optional", "opt"],
          ["1 place named that the engine did not propose", "ok"]]),
        # An unnamed HOME is a complete answer — it registers by coordinate
        # and is suppressed by it. Only a place kept for its NAME is
        # incomplete without one.
        ("an unnamed home is complete, not started",
         {"C": {"kind": "live", "label": ""}},
         [["2 places not proposed as homes, not yet named — optional", "opt"]]),
        ("rejecting a row is an answer",
         {"C": {"kind": "drop", "label": ""}},
         [["2 places not proposed as homes, not yet named — optional", "opt"]]),
    ):
        got = run_optional(rows, answers)
        if got is None:
            print("  SKIP  optional(): %s — node not installed" % label)
            continue
        yield label, got, want


def fresh_pack(tmp, name):
    """A pack made the way a new owner really gets one — by COPYING the
    shipped template, so its own defaults and comments come too. Restating the
    template here is the U3-32 defect (a test that says what the code does
    not), and `away_km_answered` is exactly the key that trap is about."""
    pack = os.path.join(tmp, name)
    shutil.copytree(os.path.join(os.path.dirname(HERE), "templates",
                                 "photo-memory", "_template"), pack)
    for leaf in ("photo-profile.json", "photo-entities.json"):
        path = os.path.join(pack, leaf)
        text = io.open(path, encoding="utf-8").read()
        io.open(path, "w", encoding="utf-8").write(
            text.replace("{{SLUG}}", "betauser").replace("{{DISPLAY}}", "Beta"))
    return pack


def fixture_document(raw):
    """The suite's stand-in for the CLIP judgement: a near-white frame is a
    'document'. The real judgement is measured on a real dump and cannot be a
    suite case (owner data); what these cases prove is the PLUMBING — that a
    frame judged a document never reaches either surface, and that its
    absence is said out loud."""
    from PIL import Image, ImageStat
    return ImageStat.Stat(Image.open(io.BytesIO(raw)).convert("L")).mean[0] > 230


def build_doc_workdir(tmp):
    """One camera and one screen size, each holding document-shaped frames
    (white) beside ordinary ones (blue)."""
    from PIL import Image
    wd = os.path.join(tmp, "unit-docs")
    src = os.path.join(tmp, "src-docs")
    os.makedirs(src, exist_ok=True)
    rows = []
    for i, (white, w, h, make) in enumerate(
            [(True, 700, 1500, "-"), (True, 700, 1500, "-"),
             (True, 700, 1500, "-"), (False, 700, 1500, "-"),
             (False, 700, 1500, "-"), (False, 700, 1500, "-"),
             (True, 80, 60, "Zenith"), (False, 80, 60, "Zenith"),
             (False, 80, 60, "Zenith")]):
        name = "d%03d.jpg" % i
        path = os.path.join(src, name)
        Image.new("RGB", (w // 10, h // 10),
                  (255, 255, 255) if white else (90, 120, 150)).save(path, "JPEG")
        rows.append(row(path, name, when="2031:05:0%d 12:00:00" % (1 + i % 3),
                        make=make, model="Q1" if make != "-" else "-",
                        w=str(w), h=str(h)))
    os.makedirs(wd, exist_ok=True)
    with io.open(os.path.join(wd, "manifest.csv"), "w", encoding="utf-8",
                 newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLS)
        wr.writeheader()
        for r in rows:
            wr.writerow(r)
    return wd


def uri_bytes(uri):
    return base64.b64decode(uri.split(",", 1)[1])


def flat(text):
    return " ".join(text.split())


def evidence_cases(tmp):
    """U3-06 — the owner's MUST-FIX. The evidence strips embedded whatever frame
    the sampler picked; on a real dump that was a legible admission ticket
    with an ID number, and in an earlier round an invoice with a name, a unit
    number and a phone number. `--no-coords` meanwhile promised a page with
    no coordinates, which was true and read as a stronger guarantee."""
    wd = build_doc_workdir(tmp)
    out = os.path.join(tmp, "docs.html")
    html = render_to_with(wd, out)
    D = data_of(html)
    shown = [uri_bytes(u) for block in (D["cameras"]["devices"]
                                        + D["screens"]["candidates"])
             for u in block["thumbs"]]
    check("U3-06 precondition: the fixture renders ordinary frames at all",
          any(not fixture_document(b) for b in shown),
          "without this the absence below is vacuous")
    check("U3-06 a document-shaped frame never reaches the page (REPRODUCTION)",
          not any(fixture_document(b) for b in shown),
          "%d document frame(s) embedded" % sum(map(fixture_document, shown)))

    sheet_dir = os.path.join(tmp, "docs-sheet")
    op.main(["sheet", wd, "--out-dir", sheet_dir])
    written = []
    for dirpath, _, files in os.walk(os.path.join(sheet_dir, "photographs")):
        written += [io.open(os.path.join(dirpath, f), "rb").read() for f in files]
    check("U3-06 ...nor the sheet's photographs directory (REPRODUCTION)",
          written and not any(fixture_document(b) for b in written),
          "%d of %d written file(s) are documents"
          % (sum(map(fixture_document, written)), len(written)))

    screen = D["screens"]["candidates"][0] if D["screens"]["candidates"] else {}
    sheet_text = io.open(os.path.join(sheet_dir, "answers.txt"),
                         encoding="utf-8").read()
    tpl = io.open(op.TEMPLATE, encoding="utf-8").read()
    check("U3-06 the hole is counted per row, apart from unreadable (REPRODUCTION)",
          screen.get("withheld") == 3 and screen.get("unreadable") == 0,
          "withheld=%r unreadable=%r" % (screen.get("withheld"),
                                         screen.get("unreadable")))
    check("U3-06 the page says so on every strip, not only where it happened",
          len(re.findall(r"strip\([^;]*\.withheld\)", tpl)) == 3
          and "look like a document" in tpl,
          "cameras, screens and homes all pass it; one missed call is one "
          "silent hole")
    check("U3-06 ...and so does the sheet, in its own copy of the prose",
          re.search(r"WITHHELD: 3 photograph\(s\)[^\n]*look like a document",
                    sheet_text) is not None)

    # ⛔ The refusal. The documented command is bare `python3`, which has no
    # torch, so a filter that quietly switched itself off there would be off
    # exactly where owners run it.
    real_hook = op.LOOKS_LIKE_DOCUMENT
    real_loader = getattr(op, "document_filter", None)

    def no_clip(*_a, **_k):
        raise ImportError("No module named 'torch'")

    op.LOOKS_LIKE_DOCUMENT = None
    op.document_filter = no_clip
    try:
        for cmd, dest in (("render", ["--out", os.path.join(tmp, "x.html")]),
                          ("sheet", ["--out-dir", os.path.join(tmp, "x")])):
            said = ""
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    op.main([cmd, wd] + dest)
            except SystemExit as err:
                said = str(err.code)
            check("U3-06 no CLIP, no opt-out: `%s` REFUSES and names the "
                  "venv (REPRODUCTION)" % cmd,
                  ".venv" in said and "--unfiltered-evidence" in said,
                  said[:70] or "it rendered unfiltered, silently")
        out3 = os.path.join(tmp, "unfiltered.html")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                html3 = render_to_with(wd, out3, "--unfiltered-evidence")
            D3 = data_of(html3)
        except SystemExit:
            D3 = {}
        check("U3-06 --unfiltered-evidence is an opt-out the page admits to",
              D3.get("evidence_filtered") is False
              and any(fixture_document(uri_bytes(u))
                      for c in D3["screens"]["candidates"] for u in c["thumbs"]),
              "the flag must work, and must not be silent about it")
    finally:
        op.LOOKS_LIKE_DOCUMENT = real_hook
        if real_loader is None:
            del op.document_filter
        else:
            op.document_filter = real_loader

    # The --no-coords half: correct the claim to what is actually withheld.
    help_text = io.StringIO()
    try:
        with contextlib.redirect_stdout(help_text):
            op.main(["render", "--help"])
    except SystemExit:
        pass
    phrase = "can still show where a place is"
    where = {"page": phrase in flat(tpl), "sheet": phrase in flat(sheet_text),
             "--help": phrase in flat(help_text.getvalue()),
             "module doc": phrase in flat(op.__doc__)}
    check("U3-06 --no-coords says what it does NOT withhold, on every "
          "surface (REPRODUCTION)", all(where.values()),
          "missing on: %s" % [k for k, v in where.items() if not v])


def device_spec_cases(tmp, wd, D_plain, tpl, f3_plain):
    """W1C-1 — the owner cannot be expected to know their screen size, so the
    session looks the phone up and passes it in. ⛔ The observed size always
    wins: a panel spec and a screenshot legitimately disagree (a phone set to
    a lower display resolution screenshots at that setting), so the lookup is
    a CROSS-CHECK that explains, never a gate that rejects. And no spec passed
    in is the normal path, not a degraded one."""
    code = js_code(tpl)
    specs = ["--device-spec", "Zenith Q1=1800x3200@a published spec sheet",
             "--device-spec", "Corvid X=800x1200@the maker's site"]
    out = os.path.join(tmp, "spec.html")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            D = data_of(render_to_with(wd, out, *specs))
    except SystemExit as err:
        D = {"error": str(err.code)}
    labels = [s.get("label", "") for s in D.get("device_specs", [])]
    by = {"%sx%s" % tuple(c["dims"]): {k["device"]: k["text"]
                                       for k in c.get("device_checks", [])}
          for c in D.get("screens", {}).get("candidates", [])}
    q1 = {k: v.get("Zenith Q1", "") for k, v in by.items()}
    check("W1C-1 a looked-up spec is labelled as looked up, and by whom "
          "(REPRODUCTION)",
          len(labels) == 2 and all("looked up by the assistant" in l
                                   for l in labels)
          and "a published spec sheet" in labels[0], D.get("error") or labels)
    check("W1C-1 a smaller size of the same shape reads as a lower display "
          "setting, consistent (REPRODUCTION)",
          "consistent with this phone" in q1.get("900x1600", ""), q1)
    check("W1C-1 a different shape is explained, never rejected "
          "(REPRODUCTION)",
          "different shape" in q1.get("800x1200", "")
          and "always wins" in q1.get("800x1200", "")
          and "exactly" in by.get("800x1200", {}).get("Corvid X", "")
          and len(D.get("screens", {}).get("candidates", []))
          == len(D_plain["screens"]["candidates"])
          and D.get("submitted") is None, by)
    check("W1C-1 the page shows it in the pack panel only once the camera "
          "is confirmed (REPRODUCTION)",
          "D.device_specs" in code and "state.makes[sp.device] !== true" in code)

    sheet_dir = os.path.join(tmp, "spec-sheet")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            op.main(["sheet", wd, "--out-dir", sheet_dir] + specs)
        sheet = io.open(os.path.join(sheet_dir, "answers.txt"),
                        encoding="utf-8").read()
    except SystemExit:
        sheet = ""
    check("W1C-1 the sheet prints the same label and checks (REPRODUCTION)",
          bool(labels) and all(l in sheet for l in labels)
          and q1.get("900x1600", "@@") in sheet)

    check("W1C-1 no spec is the NORMAL path: nothing added, nothing warned "
          "(REPRODUCTION)",
          D_plain.get("device_specs") == []
          and not any(c.get("device_checks")
                      for c in D_plain["screens"]["candidates"])
          and "looked up" not in f3_plain)
    check("W1C-1 both surfaces lead with 'you don't need to know the number' "
          "(REPRODUCTION)",
          "You don't need to know" in code
          and "You don't need to know" in f3_plain)

    refused = {}
    for name, bad in (("no size", "Zenith Q1=abc@x"),
                      ("no source", "Zenith Q1=1800x3200"),
                      ("not in this collection", "Nokia 3310=100x200@x")):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                render_to_with(wd, os.path.join(tmp, "bad.html"),
                               "--device-spec", bad)
            refused[name] = ""
        except SystemExit as err:
            refused[name] = str(err.code)
    check("W1C-1 a malformed, unsourced or unknown spec is refused, and says "
          "why (REPRODUCTION)",
          "--device-spec" in refused["no size"]
          and "@" in refused["no source"]
          and "Zenith Q1" in refused["not in this collection"], refused)


def repeat_page_cases(tmp, wd):
    """HIL-9 (HIL01) — a 2nd or later onboarding page asked section 4
    (language, types, away_km) EMPTY although the pack held the answers, and
    `apply` then warned that the engine default applies, which was false."""
    def pack_with(name, **values):
        pack = fresh_pack(tmp, name)
        path = os.path.join(pack, "photo-profile.json")
        prof = json.load(io.open(path, encoding="utf-8"))
        prof.update({k: v for k, v in values.items() if k in ("language", "own_camera_makes")})
        if "types" in values:
            prof.setdefault("naming_spec", {})["types"] = values["types"]
        if "away_km" in values:
            prof.setdefault("cluster_defaults", {}).update(
                away_km=values["away_km"], away_km_answered=True)
        io.open(path, "w", encoding="utf-8").write(json.dumps(prof))
        return pack

    answered = pack_with("pack-answered", language="en", own_camera_makes=["Lotusphone"],
                         types=["trip", "dinner"], away_km=5)
    html = render_to_with(wd, os.path.join(tmp, "repeat.html"), "--profile",
                          os.path.join(answered, "photo-profile.json"))
    d = data_of(html)
    check("HIL-9 a later page carries section 4 in from the pack (REPRODUCTION)",
          d.get("prefill") == {"language": "en", "types": "trip, dinner", "away": "5"}
          and sorted(d.get("prefill_from_pack") or []) == ["away", "language", "types"],
          "%r" % (d.get("prefill"),))
    check("HIL-9 the page says what a pack-filled answer means (REPRODUCTION)",
          "D.prefill_from_pack" in html
          and "Nothing changed? " in html and "Leave these as they are, and the pack" in html)
    fresh = fresh_pack(tmp, "pack-fresh")
    d0 = data_of(render_to_with(wd, os.path.join(tmp, "first.html"), "--profile",
                                os.path.join(fresh, "photo-profile.json")))
    check("HIL-9 a first page over a fresh pack carries nothing in (GUARD)",
          d0.get("prefill") == {} and not d0.get("prefill_from_pack"),
          "%r" % (d0.get("prefill"),))
    d1 = data_of(render_to_with(wd, os.path.join(tmp, "cli.html"), "--profile",
                                os.path.join(answered, "photo-profile.json"),
                                "--prefill", "away=9"))
    check("HIL-9 a --prefill given on the command line still wins (GUARD)",
          d1["prefill"]["away"] == "9" and "away" not in d1["prefill_from_pack"])

    block = {"cameras": {"devices": []}, "screens": {"candidates": []},
             "homes": {"rows": [], "near_misses": []},
             "submitted": {"lines": ["pets: none"], "pets": "none"}}
    page = os.path.join(tmp, "blank4.html")
    io.open(page, "w", encoding="utf-8").write(
        '<script id="onboard-data" type="application/json">'
        + json.dumps(block) + '</script>')

    def apply(pack):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            op.main(["apply", page, "--pack", pack])
        return buf.getvalue()

    said = apply(answered)
    check("HIL-9 a blank section 4 over an answered pack is not 'no answer' "
          "(REPRODUCTION)", "came back with no answer" not in said
          and "kept from the pack: language, types, away_km" in said, said[-300:])
    said0 = apply(fresh)
    check("HIL-9 a blank section 4 over a fresh pack still warns (GUARD)",
          "came back with no answer" in said0 and "types" in said0, said0[-300:])
    block["submitted"] = {"lines": []}
    io.open(page, "w", encoding="utf-8").write(
        '<script id="onboard-data" type="application/json">'
        + json.dumps(block) + '</script>')
    op.declare_pets(answered, ["Lotus", "Birk"])
    said_p = apply(answered)
    check("HIL-9 a blank pets line over a pack that names pets is kept "
          "(REPRODUCTION)", "came back with no answer" not in said_p
          and "kept from the pack: language, types, away_km, pets" in said_p,
          said_p[-300:])


def answer_contract(tmp):
    """W1A: naming-first at SNL, an opt-in pack write, A44's missing writer,
    and a declared animal becoming a subject record."""
    import photo_cluster
    import photo_subjects  # noqa: F401  (imported for its side-effect-free API)

    root = os.path.join(tmp, "contract")
    os.makedirs(root, exist_ok=True)
    # The page's own copy of the place prose and logic. ⛔ Read here because
    # `sheet_blocks()` is the SHEET's alone (one caller, cmd_sheet) — the two
    # surfaces keep independent copies and each needs its own assertions.
    tpl = io.open(os.path.join(os.path.dirname(HERE), "templates",
                               "onboarding-page.html"), encoding="utf-8").read()

    def write(name, text):
        path = os.path.join(root, name)
        io.open(path, "w", encoding="utf-8").write(text)
        return path

    def run(*argv):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = op.main(list(argv))
        except SystemExit as err:
            return 2, buf.getvalue() + str(err)
        return code, buf.getvalue()

    coords = write("coords.txt",
                   "home rows — coordinates, kept off the page.\n\n"
                   "A  10.5, 20.25  40 day(s), 9 after dark, 90 file(s)  [u]\n"
                   "   https://example.invalid/map\n"
                   "B  11.5, 21.25  8 day(s), 2 after dark, 12 file(s)  [u]\n"
                   "   https://example.invalid/map\n"
                   "C  12.5, 22.25  6 day(s), 1 after dark, 30 file(s)  [u]\n"
                   "   https://example.invalid/map\n")

    # -- item 1: naming is the primary question -------------------------
    # ⭐ REPRODUCTION. On unfixed code `_home_answer` raises SystemExit
    # ("end it with `live`") for a bare label, so the owner's own name for a
    # place they do not live at could not be expressed at all — and the only
    # way to say "not a home" threw the typed name away with the row.
    named = op._home_answer("Harbour Cafe")
    check("a place NAMED but not lived at is kept (REPRODUCTION)",
          named == {"kind": "place", "label": "Harbour Cafe"},
          "ADR 0001 needs an owner label to exist before it can beat the "
          "geocoder; for a non-home, none could")

    # GUARD: rejecting a row outright is still reachable. Losing it would be
    # a regression — an owner must be able to refuse an area the engine
    # invented.
    check("`not a place` still drops the row (guard)",
          op._home_answer("not a place") == {"kind": "drop", "label": ""}
          and op._home_answer("skip")["kind"] == "drop",
          "an owner must still be able to reject a proposed area")

    # GUARD, and the highest-severity failure mode in the inversion:
    # suppression is COORDINATE-based, so an owner who declines to name their
    # own front door must not lose the privacy rule with the name.
    check("an UNNAMED home still registers (guard)",
          op._home_answer("live") == {"kind": "live", "label": ""}
          and op._home_answer("(unnamed) live") == {"kind": "live", "label": ""},
          "making a name mandatory would cost an unnamed home its suppression")

    check("the retired wording is REFUSED, never re-read (guard)",
          "no longer has one meaning" in run(
              "apply", write("retired.txt", "home: A = not a home\n"))[1],
          "under naming-first `not a home` describes the KEPT row, and a "
          "silent meaning flip is invisible to questions_digest")

    # -- E6: the `visit` consequence must match the shipped engine ------
    # ⭐ BEHAVIOUR FIRST, then the sentence about it. The page told the owner a
    # residence they travel to is "still never named". Measured against the
    # engine it is false, and this is the fact the new wording rests on: if
    # anyone ever wires the label lookup to the NARROWED list, the page's
    # sentence becomes a lie again and this case is what says so.
    import photo_cluster as pc
    prof = {"home_locations": [
        {"label": "Everyday Town", "lat": 10.0, "lon": 20.0},
        {"label": "Relatives House", "lat": 30.0, "lon": 40.0,
         "home_range": False}]}
    unfiltered = photo_profile.labelled_home_points(prof)
    narrowed = photo_profile.labelled_home_points(prof, home_range_only=True)
    check("a `visit` residence DOES lend its label to a folder",
          pc.home_label((30.0, 40.0), "2024-10-01", unfiltered, 3.0)
          == "Relatives House"
          and [h[4] for h in narrowed] == ["Everyday Town"],
          "home_range narrows the everyday-life filing, never the name — "
          "D-F4, and photo_cluster passes the UNFILTERED list on purpose")
    visit = tpl[tpl.index('if(cur.kind === "visit"){'):]
    visit = js_code(visit[:visit.index("\n    }")])
    check("and the page no longer says it is never named (REPRODUCTION)",
          "never named" not in visit and "address" in visit,
          "the ask is `what do you call this place?` and the answer said the "
          "place is never named — what is withheld is the ADDRESS")

    # -- E7 + the owner's ruling: an optional third state ----------------
    # ⛔ Owner 20260910: "ask, but never block." The withheld rows are shown
    # as optional so the opportunity is visible; nothing may gate on them.
    check("nothing gates on optional() (guard)",
          tpl.count("optional()") - tpl.count("function optional()") == 1,
          "the only reader is paintPanel; a second one is how `optional` "
          "becomes required by accident")
    # ⛔ render() indexes todo() POSITIONALLY (flags[0]..flags[5]) to mark each
    # step done, which is exactly why the optional rows are NOT extra entries
    # in todo(). If that list ever grows, the step marks silently shift.
    # ⛔ Cut at todo()'s own closing brace, not at whatever function follows
    # it: anchoring on `function optional()` made this ValueError on a
    # template that does not have one — aborting the suite instead of failing
    # the case that exists to notice it.
    todo_body = tpl[tpl.index("function todo()"):]
    todo_body = todo_body[:todo_body.index("\n  }")]
    check("todo() still returns exactly the six REQUIRED rows (guard)",
          len(re.findall(r'\["[^"]+",', todo_body)) == 6,
          "render() reads flags[0]..flags[5] by position; a seventh row here "
          "mis-marks the steps rather than failing")

    # ⛔ E8. Every class a checklist row wears must be SCOPED, never a bare
    # global. `.opt` is the home option CARD (border, padding,
    # flex-direction:column); a checklist row given that name inherited the
    # column direction — `.todo span` sets display:flex and no direction, so
    # the card's rule won without needing specificity — and each marker
    # rendered on its own line above its text. Generic, not one-off: this
    # fails for any row class that also has a bare `.<name>{` rule.
    css = tpl[:tpl.index("</style>")]
    panel = tpl[tpl.index("function paintPanel()"):]
    panel = panel[:panel.index("\n  }")]
    # ⛔ EVERY quoted token in the class argument, not the first. The class is
    # chosen by a ternary — `row[1] === "ok" ? "ok" : "optional"` — so a
    # non-greedy match stops at "ok" and never sees the second branch, which
    # is the branch that collided. Measured: written that way this guard
    # stayed green against the very commit it was meant to fail on.
    worn = set()
    for call in re.finditer(r'el\("span",', panel):
        arg = panel[call.end():panel.index(");", call.end())]
        worn.update(re.findall(r'"([a-z][a-z-]*)"', arg))
    bare = {c for c in worn if re.search(r"(?m)^\.%s\{" % re.escape(c), css)}
    check("no checklist row wears a bare global class (REPRODUCTION)",
          not bare,
          "these also style something else entirely: %s" % (sorted(bare) or "none"))
    check("and the optional rows are styled at all (guard)",
          ".todo span.optional{" in css and '"optional")' in panel,
          "renaming the class without moving the rule leaves them unstyled, "
          "which looks fixed and is not")

    for label, stub, want in js_optional_cases():
        check("optional(): " + label, stub == want, repr(stub))

    for label, got, want in js_lines_cases():
        check("lines(): " + label, got == want, repr(got))

    for label, got, want in js_unfinished_cases():
        check("unfinished(): " + label, got == want, repr(got))

    # ⛔ WARN ONLY. The owner ruling for these rows is "ask, but never
    # block", so Confirm must still send. A second press would be a soft block
    # and is the engine inventing an owner rule it was not given.
    page_src = js_code(io.open(os.path.join(os.path.dirname(HERE), "templates",
                                            "onboarding-page.html"),
                               encoding="utf-8").read())
    # ⛔ Report, never raise: an absent handler is a state this case exists to
    # catch, and index() would abort the whole suite instead of failing here.
    marker = 'getElementById("btn-confirm")'
    at = page_src.find(marker)
    handler = page_src[at:][:2500] if at >= 0 else ""
    check("the Confirm handler is still findable (guard)", at >= 0,
          "the marker this case reads moved: %r" % marker)
    check("Confirm names what is unfinished (REPRODUCTION)",
          "unfinished(" in handler,
          "Confirm sent a half-answered page in silence")
    check("and the warning does not stop the send (guard)",
          "confirm(" not in handler and "return false" not in handler,
          "warn only: no block, no second press")
    # ⛔ Same trap the optional rows carry: a class with no rule behind it
    # renders unstyled, which looks fixed and is not.
    check("the sent-with-blanks notice is actually styled (guard)",
          ".check.warn{" in page_src and '"check warn"' in page_src,
          "the class is used but has no CSS rule")

    # ⛔ The two halves of the refusal meet only through this string. The page
    # writes `= no`; `parse_lines` turns `= no` into False and `_declined_dims`
    # turns False into a `declined_screen_dims` row. Asserted end to end here
    # so a change to either side cannot pass by agreeing with itself.
    round_trip = op.parse_lines("screen: 1170x2532 = no",
                                known={"screen": {"1170x2532"}})
    check("the page's refusal is the form the parser declines (guard)",
          round_trip["screens"] == {"1170x2532": False}
          and op._declined_dims(round_trip["screens"]) == [[1170, 2532]],
          repr(round_trip["screens"]))

    # -- E5: a checklist may not claim more than its predicate checks ----
    # ⭐ REPRODUCTION. `homesAnswered` reads `D.homes.rows` alone; the withheld
    # rows in `near_misses` are rendered as answerable questions and are
    # deliberately never counted as unfinished. The predicate is unchanged
    # since aa83290 — the LABEL moved, from "Every area answered" to "Every
    # area named or rejected", and on a real dump (2 proposed, 5 withheld)
    # that ticks green with five areas holding no name and no rejection.
    # ⛔ Guarded at SOURCE level on purpose: `todo()` is pure JS with no
    # runtime behind it here, so what is checkable is that the label and the
    # predicate still agree about which rows they are talking about.
    body = tpl[tpl.index("function todo()"):]
    body = body[:body.index("function paintPanel")]
    label = re.search(r'\["([^"]*)",\s*homesAnswered\]', body)
    check("the homes checklist names what it actually checks (REPRODUCTION)",
          bool(label) and "proposed" in label.group(1),
          "on a real dump it claimed 'Every area named or rejected' with 5 of "
          "7 areas holding neither: %r" % (label and label.group(1)))
    predicate = js_code(body[:body.index("return [")])
    check("and the predicate still reads only the proposed rows (guard)",
          "D.homes.rows" in predicate and "near_misses" not in predicate,
          "excluding the withheld rows is deliberate — the engine did not "
          "propose them and must not press as though it had. Widening the "
          "PREDICATE is a policy change and is the owner's call, not this "
          "function's; widening the LABEL alone is how it became false")

    # -- E1/E2: the prose around the question must answer THAT question --
    # Found by the Lead on a real dump: 5 of 7 rows carried a residence
    # verdict above a question that no longer asks about residence.
    verdicts = {"title": "Area C",
                "facts": ["2 separate day(s), 0 of them with a photo after "
                          "dark, 3 file(s)", "seen in u"],
                "missed_why": ["was photographed on fewer than 5 separate days"],
                "id": "C", "days": 2, "night_days": 0, "files": 3,
                "units": ["u"], "thumbs": [], "unreadable": 0}
    shaped = op.sheet_blocks({"cameras": {"devices": []},
                              "screens": {"candidates": []},
                              "homes": {"rows": [], "near_misses": [verdicts]}})
    near = shaped[0]
    check("a withheld row's TITLE carries no verdict (REPRODUCTION)",
          near["title"] == "Area C" and "NOT proposed" not in near["title"],
          "it answered `is this a home?`, which is the question that was "
          "replaced — the row is always asking for a name")
    check("and the census fact survives as EVIDENCE (guard)",
          "did NOT propose" in near["note"]
          and "fewer than 5 separate days" in near["note"]
          and "still wants a name" in near["note"],
          "D-04 discloses a withheld row; it must not disclose it as a ruling")
    check("a withheld row's COST leads with naming (REPRODUCTION)",
          near["cost"].startswith("Your word for this place")
          and "MOVES FILES" in near["cost"],
          "the residence warning led on every row, so a 2-day place got the "
          "wrong warning first and the relevant one last")
    proposed = dict(verdicts)
    proposed.pop("missed_why")
    home = op.sheet_blocks({"cameras": {"devices": []},
                            "screens": {"candidates": []},
                            "homes": {"rows": [proposed],
                                      "near_misses": []}})[0]
    check("a PROPOSED row still leads with the privacy rule (guard)",
          home["cost"].startswith("⛔ This one MOVES FILES")
          and home["note"] is None
          and "names its folders" in home["cost"],
          "on a row the engine does think is a residence, that IS what the "
          "answer does first")
    check("every row asks the naming question (guard)",
          near["ask"] == home["ask"] == "What do you call this place?",
          "what varies between the two is the evidence, never the ask")

    # -- item 2: writing is OPT-IN --------------------------------------
    # GUARD. The stance is deliberate and mirrored in photo_census; what
    # changed is only that the owner may ASK for a write.
    lines = ("makes: Zenith\nhome: A = Ford live\nhome: B = Bay visit\n"
             "home: C = Harbour Cafe\nhome: D = not a place\n"
             "language: en\ntypes: hiking, dinner\naway_km: 3\n"
             "pets: Pepper, Sage\n")
    quiet = fresh_pack(tmp, "pack-untouched")
    before = io.open(os.path.join(quiet, "photo-profile.json"),
                     encoding="utf-8").read()
    code, said = run("apply", write("answers.txt", lines))
    after = io.open(os.path.join(quiet, "photo-profile.json"),
                    encoding="utf-8").read()
    check("with no --write-pack nothing is written (guard)",
          code == 0 and op.NOT_WRITTEN in said and before == after,
          "a proposal the owner confirmed is still the owner's to place")

    # ⭐ REPRODUCTION. On unfixed code there is no `--write-pack` flag at all
    # (argparse exits 2), so an owner's confirmed answers could not reach a
    # pack by any supported command.
    pack = fresh_pack(tmp, "pack-written")
    code, said = run("apply", os.path.join(root, "answers.txt"),
                     "--write-pack", pack, "--coords-in", coords)
    profile = json.loads(io.open(os.path.join(pack, "photo-profile.json"),
                                 encoding="utf-8").read())
    check("--write-pack writes the answers (REPRODUCTION)",
          code == 0 and profile["language"] == "en"
          and profile["naming_spec"]["types"] == ["hiking", "dinner"]
          and "Zenith" in profile["own_camera_makes"],
          "the flag did not exist; answers could not reach a pack at all")

    # ⛔ Operational Rule 3: the coordinate the owner supplied is written and
    # never echoed. A report that prints it moves it somewhere new.
    check("a coordinate is never printed back (guard)",
          "10.5" not in said and "20.25" not in said and "Ford" in said,
          "the label and the count say what landed; the coordinate does not")

    homes = photo_profile.labelled_home_points(profile)
    check("a home is registered by coordinate, with its label",
          len(homes) == 2 and homes[0][4] == "Ford"
          and len(photo_profile.home_points(profile, home_range_only=True)) == 1,
          "`visit` means home_range: false — it narrows the batch label and "
          "never suppression")

    entities = json.loads(io.open(os.path.join(pack, "photo-entities.json"),
                                  encoding="utf-8").read())
    check("the named non-home lands in the pack, not the bin",
          [pl["label"] for pl in entities["frequent_places"]] == ["Harbour Cafe"],
          "this is the answer the old grammar could not even express")
    # ⭐ REPRODUCTION. The label was stored ALONE. A row letter is assigned by
    # a render's own proposal ordering and is rightly not stored — but the
    # coordinate is not the row letter, and it is the only thing that can ever
    # bind the owner's word to a batch. A label without one is not "no reader
    # yet", it is unreadable in principle.
    # D-I15: the row also carries its fixed id (tests/place_id_cases.py).
    check("a named place is stored with its COORDINATE (REPRODUCTION)",
          entities["frequent_places"] == [{"id": "fsl-0001",
                                           "label": "Harbour Cafe",
                                           "lat": 12.5, "lon": 22.25}],
          "a name nothing can locate again is not a usable answer")
    # ⛔ Not a residence, so nothing is withheld here — OA-23 settled that a
    # frequent place needs no key. The suppression rule reads home_locations
    # and is untouched.
    check("and the write report still prints no coordinate (guard)",
          "12.5" not in said and "22.25" not in said,
          "stored is not the same as shown")

    # A home cannot be registered without the coordinate file, and the refusal
    # NAMES the row rather than dropping it — a home nobody registered is a
    # home whose name is not withheld.
    code, said = run("apply", os.path.join(root, "answers.txt"),
                     "--write-pack", fresh_pack(tmp, "pack-nocoords"))
    # Q-b (owner ruling 20260924): the safe answers are written and this one is
    # refused ALONE, by name, with a non-zero exit.
    check("a home with no --coords-in is refused BY NAME (guard)",
          code == 1 and "row A" in said and "--coords-in" in said
          and "refused and NOT written" in said,
          "silently dropping it would leave the privacy rule off with no sign")
    check("a NAMED PLACE with no coordinate is refused too (guard)",
          code == 1 and "row C" in said and "named place" in said,
          "storing the label alone would write an answer nothing can read")
    # Two different reasons reach this list — an answer that would overwrite an
    # owner choice, and one that cannot be written at all. Saying "would have
    # overwritten" about a missing coordinate names the wrong failure.
    check("each refusal names its own answer (guard)",
          "⛔ home A:" in said and "would have overwritten" not in said,
          "nothing was overwritten in this run; a coordinate was missing")

    # The same answers again: every one is ALREADY LISTED (F-ff/F-nn), so
    # nothing is written and nothing the owner chose moves.
    code, said = run("apply", os.path.join(root, "answers.txt"),
                     "--write-pack", pack, "--coords-in", coords)
    again = json.loads(io.open(os.path.join(pack, "photo-profile.json"),
                               encoding="utf-8").read())
    check("a second write of the same answers changes nothing (guard)",
          "already listed" in said and "Nothing written" in said
          and again == profile,
          "an owner choice already in the pack is never overwritten here")

    # A page is a file too. Its `lines` reach the pack writer with no
    # questions digest and no photographs to check them against, so the one
    # gate it has is what the page ASKED — read off the questions half of the
    # data block, never off `submitted`.
    def page_with(rows, lines):
        block = {"cameras": {"devices": []}, "screens": {"candidates": []},
                 "homes": {"rows": [{"id": r} for r in rows],
                           "near_misses": []},
                 "submitted": {"lines": lines}}
        return write("page.html",
                     '<script id="onboard-data" type="application/json">'
                     + json.dumps(block) + '</script>')

    check("the page asked what the page asked (guard)",
          op.page_subjects(io.open(page_with(["A"], []), encoding="utf-8").read())
          == {"home": {"A"}},
          "derived from the questions; deriving it from the answers would let "
          "an invented row vouch for itself")
    code, said = run("apply", page_with(["A"], ["home: ZZ = Nowhere live"]),
                     "--write-pack", fresh_pack(tmp, "pack-invented"),
                     "--coords-in", coords)
    check("a row invented in a PAGE is refused too (guard)",
          code == 2 and "never asked about" in said,
          "an HTML file is as editable as a sheet, and this path has neither "
          "a digest nor photographs")

    # -- M12, second half: a blank went through Confirm in silence ------
    # ⭐ REPRODUCTION. UAT02-01 pressed Confirm with a screen size and the trip
    # distance unanswered and nothing said so. The `blank` warning could not
    # fire: it reads the parser's list, which only fills when a line ARRIVES
    # carrying an empty value, and the page never writes such a line — an
    # unanswered question is simply absent from `lines()`. So the gap is only
    # visible against what the page ASKED.
    def page_asking(screens, homes, lines, **extra):
        block = {"cameras": {"devices": []},
                 "screens": {"candidates": [{"dims": list(d)} for d in screens]},
                 "homes": {"rows": [{"id": r} for r in homes],
                           "near_misses": []},
                 "submitted": dict({"lines": lines}, **extra)}
        return write("blank.html",
                     '<script id="onboard-data" type="application/json">'
                     + json.dumps(block) + '</script>')

    code, said = run("apply", page_asking([(1170, 2532), (2796, 1290)], [],
                                          ["screen: 1170x2532 = iPhone 12"]))
    check("a size the page asked about and nobody answered is named "
          "(REPRODUCTION)",
          "came back with no answer" in said and "screen: 2796x1290" in said,
          said[-400:])
    check("and the one that WAS answered is not named (guard)",
          "screen: 1170x2532," not in said and "screen: 1170x2532\n" not in said,
          "warning about an answered question trains the owner to ignore it")
    check("a blank trip distance is named too (REPRODUCTION)",
          "away_km" in said, said[-400:])

    # ⛔ A REFUSAL IS AN ANSWER. This is the M12 pair: the first half makes the
    # page WRITE `= no`, and this half must not then call it unanswered.
    code, said = run("apply", page_asking([(1170, 2532)], [],
                                          ["screen: 1170x2532 = no"],
                                          away_km="3", language="en",
                                          types="trip", pets="none"))
    check("a refused size counts as answered, not blank (guard)",
          "came back with no answer" not in said,
          "`false` is an answer; only membership counts, never truthiness")

    # -- obs-14 (HIL01): a camera answered on the page read as unanswered ----
    # The page's Copy lines collapse per-device answers to `makes: <Make>`,
    # so the keyed parse holds none; the page's own per-device answers ride in
    # `submitted.makes`, and that is what was asked.
    def page_with_cameras(devices, lines, makes, **extra):
        block = {"cameras": {"devices": [{"make": m, "model": d} for m, d in devices]},
                 "screens": {"candidates": []},
                 "homes": {"rows": [], "near_misses": []},
                 "submitted": dict({"lines": lines, "makes": makes}, **extra)}
        return write("cams.html",
                     '<script id="onboard-data" type="application/json">'
                     + json.dumps(block) + '</script>')

    full = dict(away_km="3", language="en", types="trip", pets="none")
    code, said = run("apply", page_with_cameras(
        [("Lotusphone", "One"), ("Birkcam", "Two")], ["makes: Lotusphone"],
        {"Lotusphone One": True, "Birkcam Two": False}, **full))
    check("obs-14 a camera answered on the page is not called unanswered "
          "(REPRODUCTION)", "came back with no answer" not in said, said[-300:])
    code, said = run("apply", page_with_cameras(
        [("Lotusphone", "One"), ("Birkcam", "Two")], ["makes: Lotusphone"],
        {"Lotusphone One": True}, **full))
    check("obs-14 a camera truly left blank is still named (GUARD)",
          "make: Birkcam Two" in said and "make: Lotusphone One" not in said,
          said[-300:])

    # -- item 3 / A44: something finally WRITES the flag -----------------
    # ⭐ REPRODUCTION, and answering-3 is THE case. `away_km_answered()` reads
    # three things and nothing else; the template writes `away_km` itself, so
    # presence proves nothing and a value of 3 is indistinguishable from the
    # shipped one. Before this, `apply` emitted `away_km` alone and wrote no
    # pack — so an owner who answered exactly 3 read as UNANSWERED and was
    # warned on every batch, for ever.
    check("an owner who answers exactly 3 reads as ANSWERED (REPRODUCTION)",
          photo_cluster.away_km_answered(profile) is True,
          "nothing wrote the flag, and 3 == the shipped default")
    check("and it is the FLAG that carries it, not a value difference",
          profile["cluster_defaults"]["away_km_answered"] is True
          and profile["cluster_defaults"]["away_km"] == 3,
          "a difference from the shipped 3 would be true by accident here")
    # ⛔ A NUMBER. parse_lines carries away_km as a string; `"3" != 3.0` is
    # True, so writing the string would make this owner read as answered BY
    # DIFFERENCE — green for the wrong reason, and every arithmetic reader
    # downstream then compares a string against a float.
    check("away_km is written as a number, not the parsed string",
          isinstance(profile["cluster_defaults"]["away_km"], (int, float))
          and not isinstance(profile["cluster_defaults"]["away_km"], bool),
          "a string is never equal to AWAY_KM_DEFAULT, which would make the "
          "answered test true for the wrong reason")

    # -- item 4 / ADR 0004: a declared animal is a subject record --------
    # ⭐ REPRODUCTION. Onboarding asked about animals nowhere (0 hits for
    # "pet"), and `pets: []` in the template had no writer — so the engine
    # could not say what it had NOT seen.
    subjects = json.loads(io.open(
        os.path.join(pack, "photo-subjects", "subjects.json"),
        encoding="utf-8").read())["subjects"]
    by_name = {s["name"]: s for s in subjects}
    check("a declared animal becomes a subject record (REPRODUCTION)",
          set(by_name) == {"Pepper", "Sage"}
          and all(re.match(r"^subj-\d{4}$", s["subject_id"])
                  for s in subjects),
          "an empty record is the absence of an unphotographed animal, made "
          "visible")
    # ⛔ ADR 0004's hard line. Declaring creates an identity to attach to;
    # only the owner attaches it. Any exemplar here would be the engine
    # deciding which animal is which, and the cold-start rule would be gone.
    check("declaring attaches NOTHING to a face (guard)",
          all(not s["exemplars"] for s in subjects)
          and all(s["who"] == "pet" for s in subjects),
          "recognition is still learned from photographs only")

    # One name maps to exactly one record — the failure that halted a test
    # round was one name spread across several.
    twice = run("apply", write("more.txt", "pets: Pepper, PEPPER, Juno\n"),
                "--write-pack", pack)
    reread = json.loads(io.open(
        os.path.join(pack, "photo-subjects", "subjects.json"),
        encoding="utf-8").read())["subjects"]
    check("a re-declared name does not fork its record (guard)",
          len(reread) == 3
          and sorted(s["name"] for s in reread) == ["Juno", "Pepper", "Sage"],
          "one name across several records is unanswerable, and %s" % twice[0])


def main():
    print("\nonboard_page cases\n")
    # Armed once for the whole suite: render/sheet refuse to run unfiltered,
    # and this suite runs under a python with no torch.
    op.LOOKS_LIKE_DOCUMENT = fixture_document
    tmp = tempfile.mkdtemp(prefix="onboardpage-")
    try:
        wd = build_workdir(tmp)
        out = os.path.join(tmp, "page.html")
        coords = os.path.join(tmp, "coords.txt")
        html = render_to(wd, out, with_coords=False, coords_out=coords)
        D = data_of(html)

        # ---- 1. Operational Rule 3, asserted on the bytes ------------------
        # The positive control first. Every assertion below is an ABSENCE, and
        # an absence over an empty list is not evidence — a fixture whose GPS
        # never parsed would pass all of them while proving nothing.
        check("the fixture actually produced home rows to withhold",
              len(D["homes"]["rows"]) == 2,
              "without this the three absence checks below are vacuous")
        check("no coordinate reaches the page by default",
              "openstreetmap" not in html and "mlat=" not in html
              and '"coord"' not in html,
              "asserted on the rendered file, not on the flag")
        check("every home row still carries its evidence",
              all(r["days"] and r["night_days"] and r["files"]
                  and r["thumbs"] for r in D["homes"]["rows"]),
              "a withheld coordinate must not cost the owner the evidence")
        check("the coordinates went to the local file instead",
              os.path.exists(coords)
              and "10.5" in io.open(coords, encoding="utf-8").read())
        check("row letters on the page match the coordinate file",
              all(("\n%s  " % r["id"]) in io.open(coords, encoding="utf-8").read()
                  for r in D["homes"]["rows"]))

        # ---- 2. --with-coords is a deliberate, visible opt-in --------------
        out2 = os.path.join(tmp, "page-local.html")
        html2 = render_to(wd, out2, with_coords=True)
        check("--with-coords does put the map links in",
              "openstreetmap" in html2,
              "the local-only mode has to actually work")

        # ---- 3. the ranking inversion this page exists for -----------------
        cands = D["screens"]["candidates"]
        top = cands[0]["dims"]
        check("the census ranks the WRONG screen size first",
              top == ["1000", "1400"],
              "fixture asserts the defect is present, or case 4 proves nothing")
        check("every candidate carries photographs, not just a count",
              all(c["thumbs"] for c in cands))

        # ---- 4. nothing is pre-selected -----------------------------------
        check("no answer is pre-filled anywhere in the data",
              D["submitted"] is None
              and not re.search(r'"(selected|checked|default)"\s*:\s*true', html),
              "an owner who clicks straight through submits nothing")
        check("the page ships every device, including the tail",
              len(D["cameras"]["devices"]) == 3
              and all(d["thumbs"] for d in D["cameras"]["devices"]),
              "a 3-file device is where a second phone hides")

        # ---- 5. both residences are proposed, neither is named -------------
        check("both places that behave like homes are proposed",
              len(D["homes"]["rows"]) == 2)
        check("no home row carries a name",
              all("label" not in r and "name" not in r
                  for r in D["homes"]["rows"]),
              "the page asks for the word; it never supplies one")

        # ---- 6. the page can republish itself -----------------------------
        key = '<script id="page-template" type="text/plain">'
        a = html.index(key) + len(key)
        b64 = html[a:html.index("</script>", a)].strip()
        tpl = base64.b64decode(b64).decode("utf-8")
        check("the embedded template round-trips and keeps both markers",
              op.MARK_DATA in tpl and op.MARK_TPL in tpl,
              "without this the page cannot publish its own next version")

        # ---- 7. reading the answers back ----------------------------------
        check("a page nobody answered reports no answers",
              op.read_submitted(html) is None)
        answered = data_of(html)
        answered["submitted"] = {"at": "2031-07-01 09:00",
                                 "lines": ["language: en"]}
        payload = json.dumps(answered, ensure_ascii=False).replace("</", "<\\/")
        html3 = html.replace(op.RE_DATA.search(html).group(1), payload)
        got = op.read_submitted(html3)
        check("a submitted page reads its answers back off its own data",
              got and got["lines"] == ["language: en"],
              "the data is the record; the markup is a view of it")

        # ---- 8. the converter dispatch, and the masking it replaced -------
        # The first draft did Pillow, then `sips`, and swallowed what was
        # left. On the real collection that produced a page whose evidence
        # strips were nearly empty and a run that reported success: HEIC has
        # no Pillow decoder and sips cannot pull a frame out of an MP4. Both
        # facts belong to photo_embed, which already knew them.
        seen = []
        real_convert = op.photo_embed.convert_to_thumbnail

        def spy(src, dst_dir, stem, kind, filetype):
            seen.append((kind, filetype))
            return real_convert(src, dst_dir, stem, kind, filetype)

        op.photo_embed.convert_to_thumbnail = spy
        try:
            broken = os.path.join(tmp, "clip.jpg")     # suffix lies, as D13 says
            io.open(broken, "w").write("not an image")
            got, why = op.thumbs([{"SourceFile": broken, "FileType": "MP4"}])
        finally:
            op.photo_embed.convert_to_thumbnail = real_convert
        check("the manifest's FileType reaches the converter, not the suffix",
              seen and seen[0] == ("video", "MP4"),
              "a .jpg holding an MP4 must convert as video (D13 gate 1)")
        check("a file nothing can read is REPORTED, never swallowed",
              not got and len(why) == 1 and "produced nothing" in list(why)[0],
              "an empty strip reads as 'few photos here' — the opposite")

        # ---- 9. --prefill may never reach the two file-moving answers ------
        check("prefill accepts the answers that carry no file consequence",
              op.read_prefill(["language=en", "away=0.3"])
              == {"language": "en", "away": "0.3"})
        for bad in ("screens", "homes", "makes"):
            refused = False
            try:
                op.read_prefill(["%s=x" % bad])
            except SystemExit as e:
                refused = "move files" in str(e) or "may be carried in" in str(e)
            check("prefill REFUSES %s" % bad, refused,
                  "a pre-filled answer the owner did not look at is the "
                  "default this page exists to prevent")

        out4 = os.path.join(tmp, "page-prefill.html")
        op.main(["render", wd, "--out", out4, "--prefill", "language=en"])
        with io.open(out4, encoding="utf-8") as fh:
            html4 = fh.read()
        D4 = data_of(html4)
        check("a carried-in answer travels in `prefill`, NOT in the answers",
              D4["prefill"] == {"language": "en"} and D4["submitted"] is None,
              "the page marks it and seeds only an empty field")

        # ---- 10. D-04 reaches the PAGE, not just the printed census -------
        # C7 / U2-02. `home_near_misses()` existed and had zero call sites
        # here, so the surface the owner is actually sent to printed only what
        # it proposed. On the measured dump that hid a real residence.
        near = D["homes"]["near_misses"]
        residence = [r for r in near if r["days"] == 4 and r["night_days"] == 1]
        check("the fixture holds a residence that missed BOTH home bars",
              len(residence) == 1,
              "the positive control: without it every check below is vacuous")
        # Everything below reads this row. A suite that dies on an empty list
        # reports one failure and hides the rest, and the rest is what says
        # HOW an unfixed build fails.
        probe = residence[0] if residence else {"id": "?", "missed": None,
                                                "missed_why": []}
        check("the place the census withheld is ON the page",
              bool(near) and probe["id"] not in
              [r["id"] for r in D["homes"]["rows"]],
              "a surface that prints only its proposals cannot be told apart "
              "from one that found nothing")
        check("a withheld row says why, in the census's own words",
              probe["missed"] == ["days", "night_days"]
              and probe["missed_why"]
              and all(w in op.photo_census.MISSED_WORDS.values()
                      for w in probe["missed_why"]),
              "one wording, so a page and a printed report cannot disagree")
        check("a withheld row carries the photographs, not just the counts",
              bool(near) and all(r["thumbs"] for r in near),
              "it is the row the counts are LEAST able to settle")
        check("the withheld row is answerable — a letter of its own",
              len(set(r["id"] for r in near + D["homes"]["rows"]))
              == len(near) + len(D["homes"]["rows"]),
              "a missing row costs every question that row would be asked")
        check("what the cap and the filter cut is printed, not dropped",
              D["homes"]["near_misses_over_cap"] == 1
              and D["homes"]["near_misses_one_day_only"] == 1,
              "two counts, never one total — they are withheld for different "
              "reasons and only one of them can be described")
        check("the cap is the census's own, not a second copy",
              len(near) == op.photo_census.HOME_NEAR_MISS_SHOWN)
        check("a withheld row is answerable from the page, coordinate or not",
              bool(near) and "coords_withheld" in D["homes"],
              "the coordinate is in --coords-out; the LETTER is the handle")
        check("no withheld row leaks a coordinate onto the page either",
              all("coord" not in r and "map" not in r for r in near),
              "Rule 3 does not stop at the rows that cleared the bars")
        coord_text = io.open(coords, encoding="utf-8").read()
        check("the coordinate file carries the withheld rows, marked",
              bool(near)
              and all(("\n%s  " % r["id"]) in coord_text for r in near)
              and "NOT proposed" in coord_text,
              "a near-miss row is the one whose photographs settle it least")

        # The rendering half, structurally. ⚠️ NOT a browser test — there is
        # no DOM here, so this says the page's code reads the withheld rows
        # and renders them through the SAME function as a proposal (which is
        # what makes them answerable). Whether they paint is untested.
        tpl = io.open(op.TEMPLATE, encoding="utf-8").read()
        check("the page's own code reads the withheld rows",
              "near_misses" in tpl and "homeOpt(h, true)" in tpl
              and "homeOpt(h, false)" in tpl,
              "data wired to a page that ignores it is the same defect one "
              "layer along")

        # C16. The cut line is assembled in the page's JS, so there is no
        # sentence here to read — the two clauses are lifted out and evaluated
        # instead. An owner with exactly one place over the cap was told "1
        # more that missed a test ARE not listed"; the sibling clause below it
        # agreed number all along, which is what says oversight and not house
        # style. Evaluating BOTH numbers is the point: a fix that hardcodes
        # the singular reads correctly at 1 and is wrong everywhere else.
        check("both cut clauses were found in the template at all",
              bool(cut_clause(tpl, "overCap")) and bool(cut_clause(tpl, "oneDay")),
              "the four checks below are vacuous if the extractor missed")
        cap1, cap2 = cut_says(tpl, "overCap", 1), cut_says(tpl, "overCap", 2)
        check("the over-cap cut line agrees number at one",
              bool(cap1) and " is not listed" in cap1 and " are " not in cap1,
              repr(cap1))
        check("the over-cap cut line agrees number above one",
              bool(cap2) and " are not listed" in cap2 and " is " not in cap2,
              repr(cap2))
        # The sibling clause, already correct: a guard, and the positive
        # control that says the evaluator can report agreement, not only
        # disagreement.
        day1, day2 = cut_says(tpl, "oneDay", 1), cut_says(tpl, "oneDay", 2)
        check("the single-visit cut line agrees number at one",
              bool(day1) and " place " in day1 and " is not listed" in day1,
              repr(day1))
        check("the single-visit cut line agrees number above one",
              bool(day2) and " places " in day2 and " are not listed" in day2,
              repr(day2))

        # ---- 11. answerable with no browser and nothing to publish --------
        # C8 / U2-01. `render` writes a page; the page's Confirm button calls
        # window.claude.use("artifact"), and `apply` only read a page whose own
        # JS had embedded the answers. First checkpoint of the first run, and
        # unreachable for a terminal-only, headless, server or agent-driven
        # install.
        sheet_dir = os.path.join(tmp, "onboard")
        op.main(["sheet", wd, "--out-dir", sheet_dir])
        answers_path = os.path.join(sheet_dir, "answers.txt")
        sheet = io.open(answers_path, encoding="utf-8").read()
        photos = os.path.join(sheet_dir, "photographs")

        stems = op.question_stems(sheet)
        want = (["make|%s %s" % (d["make"], d["model"])
                 for d in D["cameras"]["devices"]]
                + ["screen|%sx%s" % (c["dims"][0], c["dims"][1])
                   for c in D["screens"]["candidates"]]
                + ["home|%s" % r["id"]
                   for r in D["homes"]["rows"] + D["homes"]["near_misses"]]
                + ["language", "types", "away_km", "pets"])
        check("the sheet asks EVERY question the page asks", stems == want,
              "%d question(s); a second surface that asks less is a second "
              "defect" % len(stems))
        check("every question names photographs that exist on disk",
              bool(os.path.isdir(photos) and os.listdir(photos))
              and all(os.path.isdir(os.path.join(photos, slug))
                      and os.listdir(os.path.join(photos, slug))
                      for slug in os.listdir(photos)),
              "the constraint: the answer path still makes the owner LOOK")
        asks = [l for l in sheet.splitlines() if l.startswith(">>>")]
        check("the sheet ships with every answer blank",
              bool(asks) and all(l.rstrip().endswith(("=", ":")) for l in asks),
              "an owner who returns it untouched answers nothing, exactly "
              "like clicking through the page")
        check("no coordinate reaches the sheet",
              "openstreetmap" not in sheet and "10.5" not in sheet
              and "-30.5" not in sheet,
              "asserted on the written file, not on the flag")

        def apply_text(text, path=answers_path):
            io.open(path, "w", encoding="utf-8").write(text)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                op.main(["apply", path])
            return json.loads(buf.getvalue()[buf.getvalue().index("{"):
                                             buf.getvalue().rindex("}") + 1])

        blank = apply_text(sheet)
        check("a blank sheet answers nothing and invents nothing",
              len(blank["unanswered"]) == len(stems)
              and not blank["homes"] and not blank["screens"]
              and not blank["makes"],
              "blank is not a no, and it is never read as a yes")

        filled = sheet
        for old, new in ((">>> make: %s %s =" % (D["cameras"]["devices"][0]["make"],
                                                 D["cameras"]["devices"][0]["model"]),
                          " yes"),
                         (">>> screen: 900x1600 =", " Zenith Q1"),
                         (">>> home: %s =" % probe["id"], " Rivermouth visit"),
                         (">>> language:", " en"),
                         (">>> away_km:", " 3")):
            filled = filled.replace(old + "\n", old + new + "\n")
        got = apply_text(filled, os.path.join(sheet_dir, "filled.txt"))
        check("an answered sheet comes back as the owner's answers",
              got["via"] == "sheet"
              and got["homes"].get(probe["id"]) == {"kind": "visit",
                                                    "label": "Rivermouth"}
              and got["screens"].get("900x1600") == "Zenith Q1"
              and got["own_camera_makes"] == ["Zenith"]
              and got["away_km"] == "3",
              "the withheld row is registrable — U2-02's second-order cost")

        # The three refusals. Each one is the difference between this and a
        # plain --answers flag, which is what PREFILLABLE:320 forbids.
        def refused(text, path, hint):
            io.open(path, "w", encoding="utf-8").write(text)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    op.main(["apply", path])
            except SystemExit as err:
                return hint in str(err)
            return False

        away = os.path.join(tmp, "away")
        os.makedirs(away, exist_ok=True)
        check("a sheet answered away from its photographs is REFUSED",
              refused(filled, os.path.join(away, "answers.txt"),
                      "are not beside it"),
              "answering from the counts alone is the observed failure")

        strips = sorted(os.listdir(photos)) if os.path.isdir(photos) else []
        if strips:
            shot = os.path.join(photos, strips[0])
            io.open(os.path.join(shot, sorted(os.listdir(shot))[0]),
                    "wb").write(b"x")
        check("a sheet whose photographs changed is REFUSED",
              bool(strips)
              and refused(filled, os.path.join(sheet_dir, "moved.txt"),
                          "no longer holds the photographs"),
              "answers written against different pictures answer nothing")

        invented = sheet.replace(">>> home: %s =" % probe["id"],
                                 ">>> home: %s =\n>>> home: ZZ = Nowhere live"
                                 % probe["id"])
        check("a row typed in by hand is REFUSED",
              refused(invented, os.path.join(sheet_dir, "invented.txt"),
                      "not the ones it was written with"),
              "`known` is read off the sheet's own lines, so without the "
              "questions digest an invented row vouches for itself")

        # The page's own escape hatch — its Copy button — now parses too.
        pasted = apply_text("makes: Zenith\nscreen: 900x1600\nhome: A = Ford live\n",
                            os.path.join(tmp, "pasted.txt"))
        check("the lines the page's Copy button prints are readable too",
              pasted["via"] == "pasted"
              and pasted["own_camera_makes"] == ["Zenith"]
              and pasted["screens"] == {"900x1600": ""}
              and pasted["homes"].get("A", {}).get("label") == "Ford",
              "a page that renders but cannot send left the owner holding an "
              "answer nothing read")

        # ⭐ W1A item 1. `home: A = Ford` — a bare label — used to be refused
        # here with "end it with `live`". Naming-first makes it the ANSWER, so
        # what has to be refused instead is the wording whose meaning the
        # inversion flipped: `not a home` now describes the KEPT row.
        for bad, hint in (("home: A = not a home\n", "no longer has one meaning"),
                          ("home: A = (unnamed)\n", "has to have"),
                          ("away_km: three\n", "not a number of kilometres"),
                          ("screen_dims: 900x1600\n", "not an answer this "
                                                      "stage knows")):
            check("a %s answer is refused, never dropped" % bad.split(":")[0],
                  refused(bad, os.path.join(tmp, "bad.txt"), hint),
                  "a silently ignored answer leaves whoever wrote it "
                  "believing it was recorded")

        check("the sheet did NOT widen --prefill",
              op.PREFILLABLE == ("language", "types", "away"),
              "the evidence moved to where a terminal can open it; the "
              "refusal to carry in screens and homes is untouched")

        # ---- 12. the away_km sentence comes off the PACK ------------------
        # ⭐ REPRODUCTION, U3-32 layer 2. This page hardcoded `away_km_default:
        # 3` and printed "The engine's default is 3" to an owner whose pack
        # held 60. That is the false sentence in the worst direction: it says
        # the default is a safe small number, which is the strongest argument
        # there is for leaving the question blank — and blank kept the 60,
        # which merged 11 days and three places into one folder.
        legacy = os.path.join(tmp, "legacy-profile.json")
        with io.open(legacy, "w", encoding="utf-8") as fh:
            json.dump({"owner": {"slug": "someone", "display": "Someone"},
                       "cluster_defaults": {"away_km": 60}}, fh)
        legacy_page = os.path.join(tmp, "legacy.html")
        LD = data_of(render_to_with(wd, legacy_page, "--profile", legacy))
        check("a pack that still says 60 km is described as 60",
              LD["away_km_default"] == 60,
              "the page told one owner 3 while their pack cut at 60")

        legacy_sheet = os.path.join(tmp, "legacy-onboard")
        op.main(["sheet", wd, "--out-dir", legacy_sheet, "--profile", legacy])
        with io.open(os.path.join(legacy_sheet, "answers.txt"),
                     encoding="utf-8") as fh:
            legacy_text = fh.read()
        check("the sheet's away_km sentence carries that same 60",
              "60" in [l for l in legacy_text.splitlines()
                       if "this pipeline asks it" in l][0],
              "the two surfaces must not disagree about one setting")

        # The other side, and the positive control: without it the check above
        # passes on a page that simply prints whatever number it is handed.
        shipped = os.path.join(tmp, "shipped-profile.json")
        shutil.copyfile(TEMPLATE_PROFILE, shipped)
        SD = data_of(render_to_with(wd, os.path.join(tmp, "shipped.html"),
                                    "--profile", shipped))
        check("a pack made from the shipped template is described as 3",
              SD["away_km_default"] == 3,
              "3 is the engine's own number; it has to arrive by reading the "
              "pack, not by being retyped here")
        check("no pack at all still falls to the engine's own default",
              D["away_km_default"] == op.AWAY_KM_DEFAULT == 3,
              "one number, and it is photo_cluster's")

        # ---- 12b. the types question shows the vocabulary it is authoring --
        # ⭐ REPRODUCTION, U3-01. The sheet said "the kinds of folder you sort
        # by (a trip, an event, a hike…)" and showed no list. Two things were
        # wrong at once. It reads as a preference while being a controlled
        # vocabulary — `photo_classify_set.allowed_types()` takes
        # `naming_spec.types` over `default_types()` ENTIRELY, so the answer
        # does not join a list, it REPLACES one. And not one of its three
        # worked examples is a word this engine accepts, so an owner who
        # followed the sheet pinned their pack to three unusable strings and
        # had every batch refused at classify.
        types_line = [l for l in sheet.splitlines() if l.startswith(">>> types")]
        check("the sheet still asks types", len(types_line) == 1,
              "the question itself must not move")
        block = sheet.split("#   types:")[1].split(">>> types:")[0]
        # ⛔ Read from photo_profile, NOT from op.type_defaults(): these two
        # checks are about what the SHEET says, and routing them through the
        # new helper would make them error out on the unfixed page instead of
        # failing on it. A reproduction has to fail, not crash.
        engine_words = {w for t in photo_profile.TYPE_VOCAB.values()
                        for w in t.values()}
        shown = {w for w in engine_words if w in block}
        check("the sheet shows the words the engine would otherwise use",
              len(shown) >= 9,
              "an owner cannot author a vocabulary they have never been "
              "shown; it read as a preference and refused them later")
        check("every language the engine has types for is on the sheet",
              all(code in block for code in photo_profile.TYPE_VOCAB),
              "language is asked immediately ABOVE types, so the list cannot "
              "be resolved to one language at render time — show them all")
        check("the sheet no longer offers examples the engine refuses",
              not any(e in block for e in ("a trip", "an event", "a hike")),
              "these three are the exact strings U3-04 nearly wrote into a "
              "pack; none of them is an accepted type id")
        check("the sheet says the answer REPLACES the list, not joins it",
              "BECOMES" in block,
              "whatever is written here is the whole vocabulary — an owner "
              "told 'refused at sorting time' reads that as a hidden list")
        # ⛔ Positive control for Rule 8, and the reason it is shaped this
        # way: a substring test cannot tell a type word from ordinary prose
        # ("cat" is inside "indicates", "screenshot" is also a bucket key).
        # So prove DERIVATION instead — give the engine a language it has
        # never had and the sheet must print that language's words. A page
        # that retyped the nine would be blind to this and keep printing them.
        real_vocab = photo_profile.TYPE_VOCAB
        photo_profile.TYPE_VOCAB = dict(real_vocab, xx={"k": "zzquokka",
                                                        "j": "zzbandicoot"})
        try:
            probe_dir = os.path.join(tmp, "vocab-probe")
            op.main(["sheet", wd, "--out-dir", probe_dir])
            with io.open(os.path.join(probe_dir, "answers.txt"),
                         encoding="utf-8") as fh:
                probe = fh.read().split("#   types:")[1].split(">>> types:")[0]
        finally:
            photo_profile.TYPE_VOCAB = real_vocab
        check("the type words are read off photo_profile, not retyped here",
              "zzquokka" in probe and "zzbandicoot" in probe and "xx" in probe,
              "a page naming a vocabulary the engine does not hold is the "
              "same defect one layer up")

        # ---- 13. the size the artifact host will actually accept ----------
        mb = os.path.getsize(out) / 1048576.0
        check("the rendered page fits the 16 MB artifact ceiling", mb < 16,
              "%.2f MB on this fixture" % mb)

        # ---- 14. the answer contract: what the owner answers -> the pack ---
        answer_contract(tmp)
        repeat_page_cases(tmp, wd)

        # ---- 15. U3-06: what the evidence strips withhold, and say ---------
        evidence_cases(tmp)

        # ---- 17. F7: an answered language with no table is flagged where
        # it is recorded, not discovered later as English folder names ------
        lang_path = os.path.join(tmp, "lang-lines.txt")
        io.open(lang_path, "w", encoding="utf-8").write("language: xx-F7b\n")
        heard = io.StringIO()
        with contextlib.redirect_stdout(heard), contextlib.redirect_stderr(heard):
            op.main(["apply", lang_path])
        check("F7 apply says the answered language has no table "
              "(REPRODUCTION)",
              "no word table" in heard.getvalue()
              and "xx-F7b" in heard.getvalue(), heard.getvalue()[-160:])

        # ---- 16. F3: every cut the page reports, the sheet reports too -----
        f3_dir = os.path.join(tmp, "f3-sheet")
        op.main(["sheet", wd, "--out-dir", f3_dir])
        f3 = io.open(os.path.join(f3_dir, "answers.txt"),
                     encoding="utf-8").read()
        tpl = io.open(op.TEMPLATE, encoding="utf-8").read()
        check("F3 the sheet reports the places its cap and filter cut "
              "(REPRODUCTION)",
              "1 more place(s) that missed a home test" in f3
              and "1 place(s) seen on a single daytime visit" in f3,
              "the page said so; the sheet was silent")
        check("F3 both surfaces name the flag that prints them (REPRODUCTION)",
              "--all-places" in f3 and "--all-places" in tpl)

        # ---- 18. F6: every screen size carries the engine's own check -----
        sizes = {"%sx%s" % tuple(c["dims"]): c
                 for c in D["screens"]["candidates"]}
        check("F6 every screen size carries the engine's check (REPRODUCTION)",
              all(c.get("check") for c in sizes.values())
              and "3:2" in sizes.get("800x1200", {}).get("check", "")
              and "phone screen" in sizes.get("900x1600", {}).get("check", ""),
              str({k: v.get("check") for k, v in sizes.items()}))
        check("F6 ...said on the page and on the sheet from ONE sentence "
              "(REPRODUCTION)",
              "c.check" in tpl
              and sizes.get("900x1600", {}).get("check", "@@") in f3,
              "two copies of the prose is how three findings lived on one "
              "surface only")

        # ---- 19. W1C-3: the language sentence the owner could not parse ---
        code = js_code(tpl)
        note = D.get("language_note") or ""
        check("W1C-3 no clue in the filenames reads as 'asked, not assumed "
              "English' on both surfaces (REPRODUCTION)",
              "which means no evidence" not in code
              and "D.language_note" in code
              and "not a reason to assume English" in note
              and note in f3, repr(note))
        said = getattr(op, "language_note", lambda s: "")(
            [{"script": "zh", "files": 3}])
        check("W1C-3 a filename signal is written as words, never as a list "
              "object (REPRODUCTION)",
              "+ D.language_signal +" not in code
              and "zh" in said and "3 file" in said, repr(said))

        # ---- 20. W1C-4: "Pets", and NF-3 said on BOTH surfaces ------------
        check("W1C-4 the page asks for Pets, not Animals (REPRODUCTION)",
              "Pets that live with you" in code
              and "Animals that live with you" not in code)
        check("W1C-4 the page says people are not recognised, like the "
              "sheet (REPRODUCTION)",
              "people are not recognised by this engine at all" in code.lower(),
              "NF-3 lived on the sheet only")
        check("W1C-4 the sheet asks for pets and keeps its people line "
              "(REPRODUCTION)",
              "#   pets: your pets" in f3
              and "People are not recognised by this engine at all." in f3)

        # ---- 21. W1C-2: the owner's button words, the same wire words -----
        check("W1C-2/W1C-6 the buttons say the owner's words, and the drop "
              "button says what it does (REPRODUCTION)",
              '"Visit often, name this place"' in code
              and '"Don\'t add to my profile"' in code
              and '"Don\'t name the place"' not in code
              and '"Just a place I know"' not in code
              and '"Not a place"' not in code)
        # ⛔ A GUARD, proven red by mutating the emitted word: the label is
        # not the wire. What Copy writes for a rejected row must still be a
        # word _home_answer() reads as a rejection, or the escape hatch hands
        # the owner a file nothing reads.
        wire = re.search(r'h\.kind === "drop"\)\s*out\.push\(KEY\.home \+ ": " '
                         r'\+ id \+ " = ([^"]+)"\)', code)
        got = op._home_answer(wire.group(1))["kind"] if wire else None
        check("W1C-2 what Copy writes for a rejected row still parses as a "
              "rejection", got == "drop",
              "emitted %r -> kind %r" % (wire.group(1) if wire else None, got))
        # ---- 23. W1C-1: the screen lookup is a cross-check, never a gate ---
        device_spec_cases(tmp, wd, D, tpl, f3)

        # ---- 24. W1C-7: the new type word reaches the list the owner sees -
        en_row = [r for r in D.get("type_defaults", []) if r["code"] == "en"]
        types_block = f3.split("#   types:")[1].split(">>> types:")[0]
        check("W1C-7 the default type list shown to the owner includes "
              "'home', on both surfaces (REPRODUCTION)",
              bool(en_row) and "home" in en_row[0]["words"]
              and "D.type_defaults" in code
              and re.search(r"#\s+en\s+.*\bhome\b", types_block) is not None,
              types_block.strip()[-200:])

        # ---- 22. W1C-5: Disclaimer and Next steps, ONE text, both surfaces -
        disc = D.get("disclaimer") or []
        steps = D.get("next_steps") or []
        said_steps = " ".join("%s %s" % (t, x) for t, x in steps).lower()
        check("W1C-5 the page ends with a Disclaimer and Next steps "
              "(REPRODUCTION)",
              bool(disc and steps) and "D.disclaimer" in code
              and "D.next_steps" in code)
        check("W1C-5 ...and the sheet prints the same text (REPRODUCTION)",
              bool(disc and steps) and all(s in f3 for s in disc)
              and all(t in f3 and x in f3 for t, x in steps))
        check("W1C-5 Next steps tells the owner to stay at the computer "
              "(REPRODUCTION)", "stay at the computer" in said_steps)
        check("G6 R10 Next steps announces a few short pages that match the "
              "owner's own pets and name a place, and never says 'one at a "
              "time' (REPRODUCTION)",
              "a few short pages" in said_steps
              and "picking the name from your list" in said_steps
              and "place you visit often" in said_steps
              and "one at a time" not in said_steps
              and "naming round" not in said_steps, said_steps[-400:])
        # ⛔ A GUARD. The brief once proposed "the coordinates stay on this
        # machine" and it is FALSE: trip GPS goes to the map service, and no
        # switch the owner is shown turns every lookup off. Proven red on a
        # planted line, since the real text never held one.
        false_claims = ("stay on this machine", "never leave", "nothing is sent",
                        "nothing leaves", "no-geocode")
        planted = "Your coordinates stay on this machine."
        check("W1C-5 the disclaimer makes no privacy claim the engine breaks",
              any(b in planted.lower() for b in false_claims)
              and not any(b in " ".join(disc).lower() for b in false_claims)
              and "openstreetmap" in " ".join(disc).lower(),
              "and it names where trip locations DO go")
        # W1C-6 — the owner's own sentence, verbatim. ⛔ And nothing more:
        # "Anyway, your home address is out of folder names" was proposed and
        # is FALSE for a dropped row (is_address() is CJK-only), so it must
        # never come back in any form.
        owner_line = ('Optional: if you live here, choose "I live here" and '
                      'give it your own name — that keeps your address out of '
                      'folder names entirely. Leave the name blank and only '
                      'the city is used.')
        note = D.get("drop_note") or ""
        check("W1C-6 the drop note is the owner's sentence verbatim, on both "
              "surfaces, and promises nothing more (REPRODUCTION)",
              note == owner_line and "D.drop_note" in code
              and "may still name it" not in code
              and "anyway" not in note.lower()
              and "Don't add to my profile" in f3
              and "only the city is used" in f3, repr(note))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n  %d passed, %d failed\n" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
