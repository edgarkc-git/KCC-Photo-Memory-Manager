#!/usr/bin/env python3
"""Cases for photo_review_page.py — the SET-4a rendered checkpoint.

Every fixture here is invented. The names are non-ASCII on purpose but
deliberately NOT CJK: the encoding guard has to be exercised by a test that
the i18n guard does not have to waive.

The case this suite exists for is the first one. A page whose text has been
through a latin-1 round trip is valid UTF-8 of the wrong characters, so it
raises nothing and looks fine in ASCII — and arrives unreadable to an owner
whose names are not ASCII. That is what shipped on 2026-08-20.
"""

import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import photo_review_page as rp  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %-5s %-62s %s" % ("ok" if cond else "FAIL", name, detail))


def png(path, w=40, h=60):
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (w, h), (90, 120, 150)).save(path)


REVIEW = """```
Memory Review — Checkpoint C2
owner: betauser00 · unit: unit-alpha · batches B1–B3 · 41 files
fired because: 41 file(s) depend on an unnamed or unconfirmed recurring subject
memory age: 1 confirmed subject(s) · 3 draft(s)
pack snapshot: sha256:00112233445566778899 · 9 file(s)
```

### Questions

**Q1 · Group it — hound** — affects 41 file(s) / 3 batch(es) · 2031-02 → 2031-04
> 3 group(s) of photos look like a hound. How many hound(s) is this?
> **1** · an unnamed hound · 20 file(s) / 2 batch(es)
> ![](classify/batch-01/samples/a.png) [frame 1] · taken at Hôme-Ä
> ![](classify/batch-01/samples/b, two.png) [frame 2]
> **2** · an unnamed hound · 14 file(s) / 1 batch(es)
> ![](classify/batch-02/samples/c.png) [frame 3]
> **3** · an unnamed hound · 7 file(s) / 1 batch(es)
> ![](classify/batch-02/samples/d.png) [frame 4]
> `subjects:` 1=subj-0001, 2=subj-0002, 3=subj-0003
> `obs_count:` 1=2, 2=1, 3=1
> `frames:` 1=subj-0001 aa11bb22 classify/batch-01/samples/a.png, \
2=subj-0001 cc33dd44 classify/batch-01/samples/b, two.png, \
3=subj-0002 ee55ff66 classify/batch-02/samples/c.png, \
4=subj-0003 1a2b3c4d classify/batch-02/samples/d.png
> - `pick:` ______   `who:` ______   `name:` ______ <!-- hint one -->
> - `skip:` ______ <!-- hint two -->

### Remembered already — check these are still right

> **Zoë** · 5 file(s) / 2 batch(es)
> ![](classify/batch-03/samples/e.png) [frame 5] · taken 12.4 km from Hôme-Ä
> shown because this is the photo this subject matches its own memory LEAST well
> - `recheck:` subj-0009 ______ <!-- hint three -->
> **Ñandú** · 2 file(s) / 1 batch(es)
> ![](classify/batch-03/samples/f.png) [frame 6]
> shown because this is the photo this subject matches its own memory LEAST well
> - `recheck:` subj-0010 ______ <!-- hint four -->
"""

# HIL-4/5 — the shape `photo_memory review` writes for a batch page whose
# identity index cropped each frame: frame 1 holds ONE animal, so its line is
# the crop alone; frame 2 holds two, so each crop says which animal it is.
CROPPED = """<!-- sns-page: P-B01 -->

### Questions

**Q1 · Group it — cat** — affects 2 file(s) / 1 batch(es)
> **1** · an unnamed cat · 2 file(s) / 1 batch(es)
> ![](review-crops/aa11bb22_d0.jpg) [frame 1]
> ![](review-crops/cc33dd44_d0.jpg) [frame 2] (animal 2.1)
> ![](review-crops/cc33dd44_d1.jpg) [frame 2] (animal 2.2)
> `subjects:` 1=subj-0001
> `frames:` 1=subj-0001 aa11bb22 classify/batch-01/samples/a.png, \
2=subj-0001 cc33dd44 classify/batch-01/samples/b.png
> `animals:` 2=2
> - `pick:` ______   `who:` ______   `name:` ______
> - `skip:` ______
"""

PATHS = ["classify/batch-01/samples/a.png",
         "classify/batch-01/samples/b, two.png",
         "classify/batch-02/samples/c.png",
         "classify/batch-02/samples/d.png",
         "classify/batch-03/samples/e.png",
         "classify/batch-03/samples/f.png"]


def build_workdir(root):
    for p in PATHS:
        png(os.path.join(root, p))
    md = os.path.join(root, "memory-review_C2.md")
    io.open(md, "w", encoding="utf-8").write(REVIEW)
    return md


def round_data(html):
    key = '<script id="round-data" type="application/json">'
    a = html.index(key) + len(key)
    b = html.index("</script>", a)
    return json.loads(html[a:b].replace("<\\/", "</"))


def main():
    print("\nreview_page (SET-4a) cases\n")

    # ---- 1. the encoding guard, which is why this build happened ----------
    clean = "The owner calls her Zoë — and that is the name."
    dirty = clean.encode("utf-8").decode("latin-1")
    ok = True
    try:
        rp.assert_clean_text(clean, "clean")
    except SystemExit:
        ok = False
    check("clean UTF-8 passes the encoding guard", ok)

    raised = False
    try:
        rp.assert_clean_text(dirty, "dirty")
    except SystemExit as e:
        raised = "double-encoded" in str(e)
    check("double-encoded UTF-8 is REFUSED, not written", raised,
          "a latin-1 round trip raises nothing on its own")

    tmp = tempfile.mkdtemp(prefix="reviewpage-")
    try:
        md = build_workdir(tmp)
        rev = rp.parse_review(io.open(md, encoding="utf-8").read())

        # ---- 2. the frames: line is the storage key ----------------------
        q = rev["questions"][0]
        check("checkpoint, unit and pack come off the header",
              rev["checkpoint"] == "C2" and rev["unit"] == "unit-alpha"
              and rev["pack"] == "sha256:00112233445566778899")
        check("the kind word is read, never assumed", q["kind"] == "hound",
              q["kind"])
        check("frames: yields number, subject_id, vec_ref and path",
              len(q["frames"]) == 4
              and q["frames"][1] == {"subject_id": "subj-0001",
                                     "key": "aa11bb22",
                                     "path": "classify/batch-01/samples/a.png"})
        check("a path containing a comma survives the split",
              q["frames"][2]["path"] == "classify/batch-01/samples/b, two.png",
              q["frames"][2]["path"])
        check("tiles carry the frame numbers printed beside them",
              [t["frames"] for t in q["tiles"]] == [[1, 2], [3], [4]])
        # F10 — the place is read off the frame's OWN line and nowhere else.
        check("F10 a frame's place is parsed off its own line (REPRODUCTION)",
              q.get("where") == {1: "taken at Hôme-Ä"}, str(q.get("where")))
        check("F10 a re-presented frame's place is parsed too (REPRODUCTION)",
              rev["recheck"][0].get("where") == {5: "taken 12.4 km from Hôme-Ä"},
              str(rev["recheck"][0].get("where")))

        # ---- 3. the re-presentation half --------------------------------
        check("both re-presented subjects are parsed with their ids",
              [r["subject_id"] for r in rev["recheck"]]
              == ["subj-0009", "subj-0010"])
        check("a re-presented subject keeps its non-ASCII name",
              [r["name"] for r in rev["recheck"]] == ["Zoë", "Ñandú"])
        check("the reason the frame was chosen is carried to the page",
              rev["recheck"][0]["why"].startswith("shown because"))

        # ---- 4. render ---------------------------------------------------
        out = os.path.join(tmp, "page.html")
        rp.main(["render", md, "-o", out, "--max-px", "48"])
        html = io.open(out, encoding="utf-8").read()
        d = round_data(html)

        check("the rendered page is written and parses as one JSON payload",
              isinstance(d, dict) and d["checkpoint"] == "C2")
        check("every frame is embedded, none left as a workdir path",
              len(d["frames"]) == 6
              and all(f["data"].startswith("data:image/jpeg;base64,")
                      for f in d["frames"].values()))
        check("a re-presented frame is marked, so the grid cannot group it",
              [d["frames"][n]["role"] for n in ("5", "6")]
              == ["represented", "represented"]
              and d["frames"]["1"]["role"] == "exemplar")
        check("the vec_ref reaches the page as the storage key",
              d["frames"]["1"]["key"] == "aa11bb22")
        check("F10 the place reaches the page verbatim (REPRODUCTION)",
              d["frames"]["1"].get("where") == "taken at Hôme-Ä"
              and d["frames"]["5"].get("where") == "taken 12.4 km from Hôme-Ä",
              str([d["frames"][n].get("where") for n in ("1", "5")]))
        check("F10 a frame with no place line borrows none (GUARD)",
              [d["frames"][n].get("where") for n in ("2", "3", "4", "6")]
              == ["", "", "", ""])
        # LL-PHO-188 — the JS must PRINT the phrase, not carry its own copy.
        tpl = io.open(rp.TEMPLATE, encoding="utf-8").read()
        check("F10 the page JS prints f.where on both frame surfaces "
              "(REPRODUCTION)", tpl.count("wh.textContent = f.where") == 2)
        check("the page carries the checkpoint's own blast radius",
              d["files"] == 41 and d["batches"] == 3
              and d["span"] == "2031-02 → 2031-04")
        check("the embedded self-template decodes back to the template",
              _template_roundtrips(html))

        # ---- 4b. the shape the answer ACTUALLY comes back in -------------
        # Confirm makes the page republish ITSELF with the answer merged into
        # its own round-data, so what returns from the artifact is a whole
        # HTML document. Rebuilt here exactly as the page's own handler builds
        # it, because every other test feeds `apply` lines a person typed.
        rows = ["- pick: 1,2   who: pet   name: Zoë distinct",
                "- recheck: subj-0009 withdraw"]
        republished = _republish(html, {"at": "2031-05-04 09:10", "rows": [],
                                        "recheck": [], "lines": rows})
        check("the answer is found inside a republished page",
              rp.read_answer(republished) == rows)
        check("a bare list of rows is still read", rp.read_answer(
            json.dumps(rows)) == rows)
        check("a {lines: [...]} payload is still read", rp.read_answer(
            json.dumps({"lines": rows})) == rows)
        check("plain pasted text is still read",
              rp.read_answer("\n".join(rows)) == rows)
        refused = False
        try:
            rp.read_answer(json.dumps({"submitted": {"at": "x"}}))
        except SystemExit as e:
            refused = "no list of rows" in str(e)
        check("JSON with no rows RAISES, never writes nothing quietly", refused)

        # ---- 5. apply ----------------------------------------------------
        answer = ["- pick: 1,2   who: pet   name: Zoë distinct",
                  "- pick: 3   who: pet   name: Bruno",
                  "- recheck: subj-0009 withdraw"]
        rp.main(["apply", md, "--answer", _write(tmp, answer)])
        after = io.open(md, encoding="utf-8").read()

        rows = [l for l in after.splitlines() if l.startswith("> - ")]
        check("both picks are written into the one rendered row's place",
              rows[0].startswith("> - `pick:` 1,2") and
              rows[1].startswith("> - `pick:` 3"), rows[0])
        check("the keys are written backticked, as the text path renders them",
              "`who:` pet" in rows[0] and "`name:` Zoë distinct" in rows[0])
        check("the row's hint comment survives the write",
              "<!-- hint one -->" in rows[0])
        check("no blank pick row is left behind",
              not any("`pick:` ______" in r for r in rows))
        check("an answered recheck row is filled",
              any("`recheck:` subj-0009 withdraw" in r for r in rows))
        check("an unanswered recheck row is left blank, never guessed",
              any("`recheck:` subj-0010 ______" in r for r in rows))
        check("the skip row is untouched when nothing was skipped",
              any("`skip:` ______" in r for r in rows))

        # ---- 5a. FIX7 (U7-3) — a dry run prints the rows ----------------
        import contextlib
        md4 = os.path.join(tmp, "memory-review_C4.md")
        io.open(md4, "w", encoding="utf-8").write(REVIEW)
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            rp.main(["apply", md4, "--dry-run", "--answer", _write(
                tmp, ["- pick: 3   who: pet   name: Bruno"])])
        check("FIX7 a dry-run apply prints each row it would write and writes "
              "nothing (REPRODUCTION)",
              "pick: 3   who: pet   name: Bruno" in said.getvalue()
              and "would be written" in said.getvalue()
              and io.open(md4, encoding="utf-8").read() == REVIEW,
              said.getvalue())

        # ---- 5b. F13's `name: X same subj-NNNN` survives the round trip -
        md3 = os.path.join(tmp, "memory-review_C3.md")
        io.open(md3, "w", encoding="utf-8").write(REVIEW)
        rp.main(["apply", md3, "--answer", _write(
            tmp, ["- pick: 3   who: pet   name: Bruno same subj-0009"])])
        picked = [l for l in io.open(md3, encoding="utf-8").read().splitlines()
                  if l.startswith("> - `pick:`")]
        check("F13 `name: X same subj-NNNN` is written back verbatim (GUARD)",
              len(picked) == 1 and "`name:` Bruno same subj-0009" in picked[0],
              picked[0] if picked else "no pick row")

        # ---- 6. the refusals ---------------------------------------------
        os.remove(os.path.join(tmp, PATHS[0]))
        stopped = False
        try:
            rp.main(["render", md, "-o", os.path.join(tmp, "x.html")])
        except SystemExit as e:
            stopped = "does not exist" in str(e)
        check("a frame whose file is gone STOPS the render", stopped,
              "the frames: line is never guessed around")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 7. a checkpoint with nothing to answer --------------------------
    tmp2 = tempfile.mkdtemp(prefix="reviewpage-empty-")
    try:
        md2 = os.path.join(tmp2, "memory-review_C1.md")
        io.open(md2, "w", encoding="utf-8").write(
            "```\nMemory Review — Checkpoint C1\nowner: betauser00 · unit: u\n"
            "pack snapshot: sha256:ff · 1 file(s)\n```\n\n### Questions\n\n"
            "No draft crosses the threshold at this checkpoint.\n")
        refused = False
        try:
            rp.main(["render", md2, "-o", os.path.join(tmp2, "x.html")])
        except SystemExit as e:
            refused = "nothing for an owner to answer" in str(e)
        check("an empty checkpoint is refused, not rendered blank", refused)
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    # ---- 8. known names ---------------------------------------------------
    tmp3 = tempfile.mkdtemp(prefix="reviewpage-pack-")
    try:
        sd = os.path.join(tmp3, "photo-subjects")
        os.makedirs(sd)
        io.open(os.path.join(sd, "subjects.json"), "w",
                encoding="utf-8").write(json.dumps({"subjects": [
                    {"subject_id": "subj-0001", "name": "Zoë"},
                    {"subject_id": "subj-0002", "name": None},
                    {"subject_id": "subj-0003", "name": "Gone",
                     "state": "rejected"}]}))
        names = [k["name"] for k in rp.known_names(tmp3)]
        check("only named, unrejected subjects can collide", names == ["Zoë"],
              str(names))
    finally:
        shutil.rmtree(tmp3, ignore_errors=True)

    # ---- 9. W2A table fix: the table shows the NAME, not the answer ------
    # The owner's browser check: `Name-A same subj-0017` showed as the cat's name.
    # The page's `bareName()` is lifted out of the template and RUN (node),
    # against the name `photo_memory`'s own parser stores for the same typing.
    import shutil as _shutil
    import subprocess as _subprocess
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tests"))
    import photo_memory as pm
    tpl = io.open(rp.TEMPLATE, encoding="utf-8").read()
    typed = ["Name-A same subj-0017", "Name-B same", "Name-C distinct", "Name-A",
             "same", "Zoë same", "X same subj-0001 distinct",
             "Name-A Same SUBJ-0017"]

    def stored(value):
        text = REVIEW.replace("`name:` ______", "`name:` " + value, 1)
        text = text.replace("`pick:` ______", "`pick:` 1", 1)
        text = text.replace("`who:` ______", "`who:` pet", 1)
        units = [u for u in pm.parse_review(text)[0]["picks"]
                 if u["verb"] == "pick"]
        return units[0]["name"] or ""

    lifted = (tpl.split("// bareName:begin")[1].split("// bareName:end")[0]
              if "// bareName:begin" in tpl else None)
    node = _shutil.which("node")
    suffixes = getattr(rp, "name_suffixes", lambda: None)()
    shown = None
    if lifted and node and suffixes:
        script = ("var D = %s;\n%s\nconsole.log(JSON.stringify(%s.map(bareName)));"
                  % (json.dumps({"name_suffixes": suffixes}), lifted,
                     json.dumps(typed)))
        ran = _subprocess.run([node, "-e", script], capture_output=True,
                              text=True)
        shown = json.loads(ran.stdout) if ran.returncode == 0 else ran.stderr
    want = [stored(v) for v in typed]
    check("W2A the table shows the NAME the parser stores (REPRODUCTION)",
          shown == want, "shown %r, stored %r" % (shown, want))
    check("W2A the answer table's NAME cell goes through bareName "
          "(REPRODUCTION)",
          'c4.textContent = bareName(r.name) || "— not named yet";' in tpl)
    check("W2A the page gets the parser's own patterns, not a copy (GUARD)",
          suffixes == [pm.NAME_SAME_AS.pattern, pm.NAME_SAME.pattern,
                                 pm.NAME_DISTINCT.pattern])
    # The emitted answer line must stay byte-identical: built from the RAW
    # typing plus the collision radio, never from bareName().
    body = tpl.split("function lines(){")[1].split("function paint(){")[0]
    check("W2A the emitted answer line is still the raw typing (GUARD)",
          'var nm = r.name || "______";' in body
          and 'if(r.name && r.dup) nm = nm + " " + r.dup;' in body
          and '"   name: " + nm' in body and "bareName" not in body)

    # ---- 10. G6-6b: a batch page is named for itself ---------------------
    page_md = (REVIEW.replace("Memory Review — Checkpoint C2",
                              "Photo page P-B07 — batch 7")
               .replace("unit: unit-alpha", "unit: unit alpha two")
               .replace("```\n\n### Questions",
                        "```\n<!-- sns-page: P-B07 -->\n\n### Questions", 1))
    prev = rp.parse_review(page_md)
    check("G6-6 a batch page is read as its page, never C1 (REPRODUCTION)",
          prev.get("page") == "P-B07" and prev.get("batch") == 7
          and prev["checkpoint"] != "C1", "%r" % {k: prev.get(k) for k in
                                                  ("page", "batch", "checkpoint")})
    check("G6-6 the unit is read whole, spaces and all (REPRODUCTION)",
          prev["unit"] == "unit alpha two" and rp.parse_review(REVIEW)["unit"]
          == "unit-alpha", "%r" % prev["unit"])
    check("G6-6 a checkpoint page still reads as its checkpoint (GUARD)",
          rp.parse_review(REVIEW)["checkpoint"] == "C2"
          and not rp.parse_review(REVIEW).get("page"))
    tmp4 = tempfile.mkdtemp()
    try:
        md4 = os.path.join(tmp4, "P-B07.md")
        io.open(md4, "w", encoding="utf-8").write(page_md)
        md5 = os.path.join(tmp4, "memory-review_C2.md")
        io.open(md5, "w", encoding="utf-8").write(REVIEW)
        ans = os.path.join(tmp4, "a.txt")

        def applied(md, rows):
            io.open(ans, "w", encoding="utf-8").write("\n".join(rows) + "\n")
            try:
                with open(os.devnull, "w") as quiet:
                    old, sys.stdout = sys.stdout, quiet
                    try:
                        return rp.main(["apply", md, "--answer", ans])
                    finally:
                        sys.stdout = old
            except SystemExit as stop:
                return "refused: %s" % stop

        pick = "- pick: 1   who: pet   name: Zoë"
        results = (applied(md4, ["- page: P-B08", pick]),
                   applied(md4, [pick]),
                   applied(md5, ["- page: P-B07", pick]),
                   applied(md4, ["- page: P-B07", pick]),
                   applied(md5, [pick]))
        written = io.open(md4, encoding="utf-8").read()
    finally:
        shutil.rmtree(tmp4, ignore_errors=True)
    check("G6-6 an answer lands only on the page it names (REPRODUCTION)",
          all(str(r).startswith("refused") for r in results[:3])
          and results[3] == 0 and results[4] == 0
          and "`pick:` 1" in written and "page:" not in written.split("### Questions")[1],
          "%r" % (results,))
    check("G6-6 the template names a batch page and offers only `pet` there "
          "(REPRODUCTION)",
          '"Photo page " + PAGE' in tpl and '(PAGE ? ["pet"]' in tpl
          and '"- page: " + PAGE' in tpl and 'id="pets"' in tpl)

    # ---- 11. G6-6c: the place question renders, and its answer lands -----
    coord_text = "40.97531, 60.86420"
    place_md = """```
Photo page P-B09 — batch 9
owner: betauser00 · unit: unit-alpha · batches B9–B9 · 3 files
pack snapshot: sha256:00112233445566778899 · 9 file(s)
```
<!-- sns-page: P-B09 -->

### Questions

Nothing to ask in this batch.

```
A note.
```

### A place you visit often

**S1 · a place you visit often** — 4 day(s) over 3 month(s), in 3 batch(es)
> What do you call this place? Write its name.
> ![](classify/batch-09/samples/p.jpg)
> A home named here is protected from now on, but the batches already cut are not cut again.
> `place:` 1 · 4 d · 3 m
> - `name:` ______   `home:` ______ <!-- hint five -->
"""
    tmp6 = tempfile.mkdtemp()
    try:
        from PIL import Image
        src_img = os.path.join(tmp6, "classify", "batch-09", "samples", "p.jpg")
        os.makedirs(os.path.dirname(src_img))
        exif = Image.Exif()
        exif[0x010E] = coord_text              # ImageDescription: a positive control
        Image.new("RGB", (40, 60), (90, 120, 150)).save(src_img, exif=exif)
        md6 = os.path.join(tmp6, "P-B09.md")
        io.open(md6, "w", encoding="utf-8").write(place_md)
        out6 = os.path.join(tmp6, "P-B09.html")
        try:
            with open(os.devnull, "w") as quiet:
                old, sys.stdout = sys.stdout, quiet
                try:
                    rc6 = rp.main(["render", md6, "--workdir", tmp6, "-o", out6])
                finally:
                    sys.stdout = old
        except SystemExit as stop:
            rc6 = "refused: %s" % stop
        html6 = io.open(out6, encoding="utf-8").read() if os.path.exists(out6) else ""
        data6 = round_data(html6) if html6 else {}
        control = coord_text.encode() in open(src_img, "rb").read()
        ans6 = os.path.join(tmp6, "a.txt")
        io.open(ans6, "w", encoding="utf-8").write(
            "- page: P-B09\n- place: 1   name: Mill Pond   home: live\n")
        try:
            with open(os.devnull, "w") as quiet:
                old, sys.stdout = sys.stdout, quiet
                try:
                    applied6 = rp.main(["apply", md6, "--answer", ans6])
                finally:
                    sys.stdout = old
        except SystemExit as stop:
            applied6 = "refused: %s" % stop
        written6 = io.open(md6, encoding="utf-8").read()
    finally:
        shutil.rmtree(tmp6, ignore_errors=True)
    places6 = data6.get("places") or []
    check("G6-6c a place-only batch page renders its place question "
          "(REPRODUCTION)",
          rc6 == 0 and len(places6) == 1 and places6[0]["days"] == 4
          and places6[0]["months"] == 3 and len(places6[0]["photos"]) == 1
          and any("not cut again" in n for n in places6[0]["notes"]),
          "rc=%r places=%r" % (rc6, [{k: v for k, v in p.items() if k != "photos"}
                                      for p in places6]))
    check("G6-6c no coordinate reaches the HTML (positive control: the photo's "
          "EXIF holds one) (GUARD)",
          control and html6 and coord_text not in html6 and "40.97531" not in html6)
    got6 = pm.parse_places(written6)
    check("G6-6c a place answer lands on its `name:`/`home:` row (REPRODUCTION)",
          applied6 == 0 and got6 and got6[0]["name"] == "Mill Pond"
          and got6[0]["home"] == "live", "applied=%r got=%r" % (applied6, got6))
    check("G6-6c the template has the place card and emits `place:` rows "
          "(REPRODUCTION)",
          'id="place-card"' in tpl or 'id="place-card"' in io.open(
              rp.TEMPLATE, encoding="utf-8").read())

    # ---- 12. G6-6d: a photo with 2+ animals may be in one group per animal
    shared_md = REVIEW.replace(
        "> - `pick:` ______",
        "> `animals:` 2=2\n> - `pick:` ______", 1)
    sq = rp.parse_review(shared_md)["questions"][0]
    tpl_now = io.open(rp.TEMPLATE, encoding="utf-8").read()
    check("G6-6d the page reads which photos hold 2+ animals (REPRODUCTION)",
          sq.get("animals") == {2: 2}, "%r" % sq.get("animals"))
    check("G6-6d the template allows one group per animal, and no more "
          "(REPRODUCTION)",
          "function animalsIn(n)" in tpl_now and "state.extra" in tpl_now
          and "seen[n].length > animalsIn(n)" in tpl_now
          and "No photo is in more than one group." not in tpl_now)

    # ---- 13. G8: a place-only batch page hides the animal furniture -------
    # The page's `furniture()` is lifted out of the template with the lines
    # that compute its inputs, and RUN (node) on the real round-data of the
    # place-only page rendered in section 11.
    import photo_profile
    tpl_g8 = io.open(rp.TEMPLATE, encoding="utf-8").read()
    furn = (tpl_g8.split("// furniture:begin")[1].split("// furniture:end")[0]
            if "// furniture:begin" in tpl_g8 else None)

    def furnished(d):
        if not (furn and node):
            return None
        script = ("var D = %s;\nvar frames = D.frames, tiles = D.tiles;\n"
                  "var PAGE = D.page || \"\";\n%s\n"
                  "console.log(JSON.stringify(furniture()));"
                  % (json.dumps(d), furn))
        ran = _subprocess.run([node, "-e", script], capture_output=True,
                              text=True)
        return json.loads(ran.stdout) if ran.returncode == 0 else ran.stderr

    threshold = photo_profile.review_messages(
        {"language": "en"})["review_no_questions"]
    frame = {"subject_id": "subj-0001", "key": "k", "file": "a.png",
             "batch": "07", "role": "exemplar", "where": "", "animals": 1,
             "data": ""}
    place_page = dict(data6, no_round=threshold)
    pet_page = dict(data6, page="P-B07", batch=7, places=[], files=3,
                    batches=1, no_round="", frames={"1": frame},
                    tiles=[{"tile": 1, "display": "1", "files": 3,
                            "batches": 1, "subject_id": "subj-0001",
                            "frames": [1]}])
    both_page = dict(pet_page, places=data6.get("places") or [])
    c_page = dict(pet_page, page="", batch=None, checkpoint="C2",
                  no_round=threshold)
    got = {k: furnished(v) for k, v in (("place", place_page), ("pet", pet_page),
                                        ("both", both_page), ("c", c_page))}
    listed = ["howmany", "pets", "f-files", "f-batches", "steps", "toolbar",
              "answer-card", "subjects-card", "pet-notes"]
    ok = all(isinstance(v, dict) for v in got.values())
    check("G8 a place-only page hides the animal furniture (REPRODUCTION)",
          ok and got["place"]["placeOnly"]
          and sorted(got["place"]["hide"]) == sorted(listed)
          and got["place"]["noRound"] == "", "%r" % (got["place"],))
    check("G8 the tab title names the page (REPRODUCTION)",
          ok and got["place"]["title"] == "Photo page P-B09"
          and got["pet"]["title"] == "Photo page P-B07"
          and "C2" in got["c"]["title"]
          and "document.title = FURNITURE.title" in tpl_g8,
          "%r" % ({k: v.get("title") for k, v in got.items()} if ok else got,))
    check("G8 a hidden element stays hidden under a display rule (REPRODUCTION)",
          "[hidden]{display:none!important;}" in tpl_g8
          and "FURNITURE.hide.forEach" in tpl_g8)
    check("G8 a pet page and a page with an animal AND a place keep it all (GUARD)",
          ok and not got["pet"]["placeOnly"] and got["pet"]["hide"] == []
          and not got["both"]["placeOnly"] and got["both"]["hide"] == [])
    check("G8 a checkpoint page keeps its furniture and its threshold line (GUARD)",
          ok and got["c"]["hide"] == [] and got["c"]["noRound"] == threshold
          and "Photo page" not in got["c"]["title"])
    howto_page = dict(pet_page, howto=["Step 1. a", "Step 2. b"])
    got_h = furnished(howto_page)
    check("HIL-4 one instruction set: the two steps replace the 4-step strip "
          "(REPRODUCTION)", isinstance(got_h, dict) and "steps" in got_h["hide"]
          and got_h.get("clickLine"), "%r" % (got_h,))
    check("HIL-4 a page without the two steps keeps its strip (GUARD)",
          ok and "steps" not in got["pet"]["hide"]
          and "steps" not in got["c"]["hide"])
    check("G8 every element the page can hide exists in the template (GUARD)",
          all('id="%s"' % i in tpl_g8 for i in listed))
    send_back = tpl_g8.split('id="subjects-card"')[-1].split("</aside>")[0]
    check("G8 the place answer lines and Send it back stay on a place-only "
          "page (GUARD)",
          ok and 'id="btn-confirm"' in send_back and 'id="out"' in send_back
          and "copy the lines yourself" in send_back
          and 'id="btn-confirm"' not in "".join(send_back.split("</div>", 2)[:2])
          and '"- place: " + r.n' in tpl_g8 and '["- page: " + PAGE]' in tpl_g8
          and not set(got["place"]["hide"]) & {"out", "btn-confirm", "place-card"})

    # ---- 14. FIX6 (U6-32): a saved draft is scoped to the dump and its photos
    # The page's draft helpers are lifted out of the template and RUN (node).
    # GUARD: a browser-only defect, so what is held is the key and the check.
    tpl_f1 = io.open(rp.TEMPLATE, encoding="utf-8").read()
    draft = (tpl_f1.split("// draft:begin")[1].split("// draft:end")[0]
             if "// draft:begin" in tpl_f1 else None)
    f1 = None
    if draft and node:
        a = {"unit": "dump-a", "page": "", "checkpoint": "C1",
             "frames": {"1": {"key": "aaa"}, "2": {"key": "bbb"}}}
        b = dict(a, unit="dump-b")
        a2 = dict(a, frames={"1": {"key": "ccc"}, "2": {"key": "bbb"}})
        script = ("%s\nvar A=%s, B=%s, A2=%s;\n"
                  "var saved = JSON.stringify({assign:{1:1}, meta:{}, next:2, digest:framesDigest(A)});\n"
                  "console.log(JSON.stringify({ka:draftKey(A), kb:draftKey(B),"
                  " same:restoreDraft(saved, framesDigest(A)),"
                  " moved:restoreDraft(saved, framesDigest(A2)),"
                  " old:restoreDraft(JSON.stringify({assign:{1:1}, meta:{}, next:2}), framesDigest(A))}));"
                  % (draft, json.dumps(a), json.dumps(b), json.dumps(a2)))
        ran = _subprocess.run([node, "-e", script], capture_output=True, text=True)
        f1 = json.loads(ran.stdout) if ran.returncode == 0 else ran.stderr
    ok1 = isinstance(f1, dict)
    check("FIX6 a draft key carries the dump, so another dump's C1 is a "
          "different draft (GUARD)",
          ok1 and f1["ka"] != f1["kb"] and "dump-a" in f1["ka"]
          and f1["ka"].endswith("-v5"), "%r" % (f1,))
    check("FIX6 a draft whose numbers now mean other photos is discarded, "
          "and one that still matches is kept (GUARD)",
          ok1 and f1["same"]["state"] and not f1["same"]["discarded"]
          and f1["moved"]["state"] is None and f1["moved"]["discarded"]
          and f1["old"]["state"] is None and f1["old"]["discarded"], "%r" % (f1,))
    check("FIX6 the page reads the scoped key and says when it dropped a "
          "draft (GUARD)",
          "var KEY = draftKey(D)" in tpl_f1 and '-v4"' not in tpl_f1
          and 'id="draft-notice"' in tpl_f1
          and "restoreDraft(localStorage.getItem(KEY), DIGEST)" in tpl_f1)

    # ---- M6 — a re-apply replaces every earlier answer row -------------------
    first = rp.apply_answer(REVIEW, ["pick: 1,2 who: pet name: Märta",
                                     "pick: 3 who: pet name: Öskar",
                                     "skip: 4 confirm",
                                     "recheck: subj-0009 withdraw"])
    again = rp.apply_answer(first, ["pick: 1,2 who: pet name: Märta"])
    report = getattr(rp, "apply_answer_report", None)
    gone = report(first, ["pick: 1,2 who: pet name: Märta"])[1] if report else []
    check("M6 a re-apply leaves no earlier pick row, skip or recheck value "
          "beside the new answer (REPRODUCTION)",
          "Öskar" not in again and "withdraw" not in again
          and "`skip:` 4" not in again and again.count("`pick:`") == 1
          and "`recheck:` subj-0009 ______" in again, again)
    check("M6 the replaced rows are reported (REPRODUCTION)",
          any("Öskar" in r for r in gone) and any("withdraw" in r for r in gone)
          and any("skip:` 4" in r for r in gone), "%r" % (gone,))
    two_q = REVIEW + ("\n**Q2 · Group it — hound** — affects 1 file(s) / 1 batch(es)\n"
                      "> - `pick:` 9 `who:` pet `name:` Ålda <!-- typed by hand -->\n")
    kept = rp.apply_answer(two_q, ["pick: 1 who: pet name: Märta"])
    check("M6 another question's typed row is left as it is (GUARD)",
          "`pick:` 9 `who:` pet `name:` Ålda" in kept, kept[-300:])

    # ---- F26 — `pick: N.M` is refused at apply, the two-row form is not ------
    with tempfile.TemporaryDirectory() as tmp26:
        md26 = os.path.join(tmp26, "memory-review_C1.md")
        io.open(md26, "w", encoding="utf-8").write(REVIEW)
        try:
            rp.main(["apply", md26, "--answer", _write(
                tmp26, ["pick: 3.1 who: pet name: Märta"])])
            said26 = None
        except SystemExit as e:
            said26 = str(e)
        after26 = io.open(md26, encoding="utf-8").read()
    check("F26 `pick: 3.1` is refused at apply and nothing is written "
          "(REPRODUCTION)",
          said26 is not None and "one row per name" in said26
          and after26 == REVIEW, "%r" % (said26,))
    two_rows = rp.apply_answer(REVIEW, ["pick: 3 who: pet name: Märta",
                                        "pick: 3 who: pet name: Öskar"])
    check("F26 one photo on two rows, one name each, is still written (GUARD)",
          "`pick:` 3 `who:` pet `name:` Märta" in two_rows
          and "`pick:` 3 `who:` pet `name:` Öskar" in two_rows, two_rows)

    # ---- HIL-4/5 B1 — a one-animal frame shows its CROP on the web too -----
    with tempfile.TemporaryDirectory() as tmpb1:
        for p in ("classify/batch-01/samples/a.png",
                  "classify/batch-01/samples/b.png"):
            png(os.path.join(tmpb1, p), 40, 60)
        png(os.path.join(tmpb1, "review-crops/aa11bb22_d0.jpg"), 12, 12)
        png(os.path.join(tmpb1, "review-crops/cc33dd44_d0.jpg"), 14, 14)
        png(os.path.join(tmpb1, "review-crops/cc33dd44_d1.jpg"), 16, 16)
        b1 = os.path.join(tmpb1, "memory-review_C1.md")
        io.open(b1, "w", encoding="utf-8").write(CROPPED)
        rp.main(["render", b1, "-o", os.path.join(tmpb1, "p.html")])
        d1 = round_data(io.open(os.path.join(tmpb1, "p.html"),
                                encoding="utf-8").read())
        whole = rp.encode_image(os.path.join(
            tmpb1, "classify/batch-01/samples/a.png"), 640, 72)
        crop1 = rp.encode_image(os.path.join(
            tmpb1, "review-crops/aa11bb22_d0.jpg"), 640, 72)
        whole2 = rp.encode_image(os.path.join(
            tmpb1, "classify/batch-01/samples/b.png"), 640, 72)
    f1, f2 = d1["frames"]["1"], d1["frames"]["2"]
    check("B1 a one-animal frame's web tile is its crop, as in the markdown "
          "(REPRODUCTION)", f1["data"] == crop1 and f1["data"] != whole,
          "tile is the %s" % ("crop" if f1["data"] == crop1 else "whole photo"))
    check("B1 the one crop is offered for a not-a-real-animal mark as 1.1 "
          "(REPRODUCTION)",
          [c["animal"] for c in f1.get("crops", [])] == [1]
          and f1["crops"][0]["data"] == crop1, "%r" % (
              [c["animal"] for c in f1.get("crops", [])],))
    check("B1 a 2-animal frame keeps the whole photo and both crops (GUARD)",
          f2["data"] == whole2 and [c["animal"] for c in f2["crops"]] == [1, 2])

    # ---- HIL-7 B4 — a re-presented frame reaches the web as its crop(s) -----
    remembered_md = ("### Remembered already — check these are still right\n\n"
                     "> **Lotus** · 5 file(s) / 2 batch(es)\n"
                     "> ![](review-crops/aa11bb22_d0.jpg) [frame 5]\n"
                     "> ![](review-crops/cc33dd44_d0.jpg) [frame 6] (animal 6.1)\n"
                     "> ![](review-crops/cc33dd44_d1.jpg) [frame 6] (animal 6.2)\n"
                     "> `shown:` subj-0002 5=aa11bb22, 6=cc33dd44\n"
                     "> - `recheck:` subj-0002 ______\n")
    with tempfile.TemporaryDirectory() as tmpb4:
        png(os.path.join(tmpb4, "review-crops/aa11bb22_d0.jpg"), 12, 12)
        png(os.path.join(tmpb4, "review-crops/cc33dd44_d0.jpg"), 14, 14)
        png(os.path.join(tmpb4, "review-crops/cc33dd44_d1.jpg"), 16, 16)
        b4 = os.path.join(tmpb4, "memory-review_C3.md")
        io.open(b4, "w", encoding="utf-8").write(remembered_md)
        rp.main(["render", b4, "-o", os.path.join(tmpb4, "p.html")])
        d4 = round_data(io.open(os.path.join(tmpb4, "p.html"),
                                encoding="utf-8").read())
        crop5 = rp.encode_image(os.path.join(
            tmpb4, "review-crops/aa11bb22_d0.jpg"), 640, 72)
    r4 = d4["recheck"][0]
    check("HIL-7 a shared re-presented frame is one frame, not two "
          "(REPRODUCTION)", r4["frames"] == [5, 6], "%r" % (r4["frames"],))
    check("HIL-7 a shared re-presented frame carries both crops to the web "
          "(REPRODUCTION)",
          [c["animal"] for c in d4["frames"]["6"].get("crops", [])] == [1, 2])
    check("HIL-7 a one-animal re-presented frame is its crop (GUARD)",
          d4["frames"]["5"]["data"] == crop5)
    whole_md = ("### Remembered already — check these are still right\n\n"
                "> **Lotus** · 5 file(s) / 2 batch(es)\n"
                "> ![](review-crops/aa11bb22_d0.jpg) [frame 5]\n"
                "> Photo 5 is the whole photo: reason. <!-- whole -->\n"
                "> - `recheck:` subj-0002 ______\n")
    with tempfile.TemporaryDirectory() as tmpq3:
        png(os.path.join(tmpq3, "review-crops/aa11bb22_d0.jpg"), 12, 12)
        q3 = os.path.join(tmpq3, "memory-review_C4.md")
        io.open(q3, "w", encoding="utf-8").write(whole_md)
        rp.main(["render", q3, "-o", os.path.join(tmpq3, "p.html")])
        html_q3 = io.open(os.path.join(tmpq3, "p.html"), encoding="utf-8").read()
    check("Q3 the 'shown whole' line reaches the web under its photo "
          "(REPRODUCTION)",
          round_data(html_q3)["frames"]["5"].get("whole")
          == "Photo 5 is the whole photo: reason.", "%r" % (
              round_data(html_q3)["frames"]["5"].get("whole"),))
    check("Q3 the web page prints the 'shown whole' line (REPRODUCTION)",
          "f.whole" in io.open(rp.TEMPLATE, encoding="utf-8").read())

    # ---- HIL-6 B3 — "none of these are mine" is an answer Confirm can send --
    # The page's answer helpers are lifted out of the template and RUN (node);
    # their row then goes through `apply` and `photo_memory`'s own parser.
    tpl_b3 = io.open(rp.TEMPLATE, encoding="utf-8").read()
    ans = (tpl_b3.split("// answer:begin")[1].split("// answer:end")[0]
           if "// answer:begin" in tpl_b3 else None)

    def run_answer(expr):
        if not (ans and node):
            return None
        ran = _subprocess.run([node, "-e", "%s\nconsole.log(JSON.stringify(%s));"
                               % (ans, expr)], capture_output=True, text=True)
        return json.loads(ran.stdout) if ran.returncode == 0 else ran.stderr

    every = run_answer('{none: skipRow(noneOfThese([1,2,3], {2:true}), []),'
                       ' sends: confirmable({skipped: 2}),'
                       ' marks: confirmable({notAnimals: 1}),'
                       ' empty: confirmable({}),'
                       ' broken: confirmable({skipped: 2, dupes: 1})}')
    ok = isinstance(every, dict)
    check("HIL-6 Confirm can send an answer of skips alone (REPRODUCTION)",
          ok and every["sends"] is True and every["marks"] is True,
          "%r" % (every,))
    check("HIL-6 'none of these' skips every pickable photo, never an "
          "evidence one (REPRODUCTION)",
          ok and every["none"] == "- skip: 1,3 confirm", "%r" % (every,))
    check("HIL-6 an empty or broken answer still cannot be sent (GUARD)",
          ok and every["empty"] is False and every["broken"] is False)
    md_b3 = rp.apply_answer(CROPPED, ["- page: P-B01", "- skip: 1,2 confirm"])
    blk = pm.parse_review(md_b3)[0]
    check("HIL-6 the row is the text form's not-mine skip, armed (GUARD)",
          blk["skip_numbers"] == [1, 2] and blk["skip_armed"]
          and blk["skip_basis"] == "not-mine", "%r" % (blk["skip_numbers"],))
    check("HIL-6 the page offers the answer as a button (REPRODUCTION)",
          'id="btn-none"' in tpl_b3)

    # ---- HIL-4 B2 — every crop can be marked not a real animal, one alone too
    tk = (tpl_b3.split("// cropTicks:begin")[1].split("// cropTicks:end")[0]
          if "// cropTicks:begin" in tpl_b3 else None)
    ticks = None
    if tk and node:
        ran = _subprocess.run([node, "-e", tk + "\nconsole.log(JSON.stringify(["
                               "cropTicks(%s, 1), cropTicks(%s, 2), cropTicks(%s, 3)]));"
                               % (json.dumps(f1), json.dumps(f2),
                                  json.dumps({"animals": 1, "crops": []}))],
                              capture_output=True, text=True)
        ticks = json.loads(ran.stdout) if ran.returncode == 0 else ran.stderr
    check("HIL-4 a one-animal crop can be marked not a real animal as 1.1 "
          "(REPRODUCTION)", isinstance(ticks, list)
          and [t["key"] for t in ticks[0]] == ["1.1"]
          and ticks[0][0]["thumb"] is False, "%r" % (ticks,))
    check("HIL-4 a shared photo keeps one tick per crop, with its picture "
          "(GUARD)", isinstance(ticks, list)
          and [(t["key"], t["thumb"]) for t in ticks[1]] == [("2.1", True), ("2.2", True)]
          and ticks[2] == [])

    # ---- HIL-5 B5 — recheck on the web needs no typed id and no typed `not` --
    rck = (tpl_b3.split("// recheck:begin")[1].split("// recheck:end")[0]
           if "// recheck:begin" in tpl_b3 else None)
    vals = None
    if rck and node:
        ran = _subprocess.run([node, "-e", rck + "\nconsole.log(JSON.stringify(["
                               "recheckValue({kind:'not', frames:{6:true, 5:true, 7:false}}),"
                               "recheckValue({kind:'withdraw'}),"
                               "recheckValue({kind:'rename', name:' Birk '}),"
                               "recheckValue({kind:'ok', frames:{5:true}}),"
                               "recheckValue({kind:'not', frames:{}}),"
                               "recheckValue(undefined)]));"],
                              capture_output=True, text=True)
        vals = json.loads(ran.stdout) if ran.returncode == 0 else ran.stderr
    check("HIL-5 a ticked photo becomes `not <n>` with no typing (REPRODUCTION)",
          isinstance(vals, list) and vals[0] == "not 5,6", "%r" % (vals,))
    check("HIL-5 withdraw, a new name and 'still right' are one choice each "
          "(REPRODUCTION)",
          isinstance(vals, list) and vals[1:] == ["withdraw", "Birk", "", "", ""],
          "%r" % (vals,))
    md_b5 = rp.apply_answer(remembered_md, ["- recheck: subj-0002 not 5,6"])
    rows_b5 = pm.parse_representations(md_b5)
    check("HIL-5 the web's recheck row is the text form's `not` answer (GUARD)",
          len(rows_b5) == 1 and rows_b5[0]["not_frames"] == [5, 6]
          and rows_b5[0]["subject_ids"] == ["subj-0002"]
          and not rows_b5[0]["name"], "%r" % (rows_b5,))

    print("\n%d/%d review_page cases passed"
          % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


def _write(root, lines):
    p = os.path.join(root, "answer.txt")
    io.open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return p


def _republish(html, submitted):
    """The document Confirm publishes — built the way the page's handler does."""
    import base64
    key = '<script id="page-template" type="text/plain">'
    a = html.index(key) + len(key)
    b = html.index("</script>", a)
    b64 = html[a:b].strip()
    tpl = base64.b64decode(b64).decode("utf-8")
    nxt = round_data(html)
    nxt["submitted"] = submitted
    return ("<!doctype html>\n" + tpl
            .replace(rp.MARK_TPL, b64)
            .replace(rp.MARK_DATA,
                     json.dumps(nxt, ensure_ascii=False).replace("</", "<\\/")))


def _template_roundtrips(html):
    import base64
    key = '<script id="page-template" type="text/plain">'
    a = html.index(key) + len(key)
    b = html.index("</script>", a)
    try:
        tpl = base64.b64decode(html[a:b].strip()).decode("utf-8")
    except Exception:
        return False
    return rp.MARK_DATA in tpl and rp.MARK_TPL in tpl


if __name__ == "__main__":
    sys.exit(main())
