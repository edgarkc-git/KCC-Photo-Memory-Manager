#!/usr/bin/env python3
"""G6 cases — the per-batch page (SNS + SNL) for the first batches with a
question.

A dump with an index gets short pages, one batch at a time, in date order:
a page for each of the first `memory.batch_pages` batches that show an animal
still to be asked about, and a page for every batch where a place the owner
visits often first shows up and has no name yet (owner rulings R1-R3,
20260913). A batch with nothing to ask is skipped, and the skip is logged in
the index.

  python3 tests/batch_page_cases.py [-v]

Exit 0 = pass. Synthetic dumps in a temp dir: invented coordinates, invented
names, no owner pack is read.
"""

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import photo_index_cases as ix  # noqa: E402
import photo_memory as pm  # noqa: E402
import photo_memory_cases as pmc  # noqa: E402
import photo_onboard_page as op  # noqa: E402
import photo_plan  # noqa: E402
import photo_profile  # noqa: E402

# Invented, far from the fixture pack's home (Ford) and named place (Harbour).
PLACE = (30.13579, 50.24681)
PLACE_TEXT = ("30.13579", "50.24681", "30.136", "50.247")
BATCHES = 8
# ~6.1 km north of PLACE: the same map word in batches.json, outside the 1 km
# naming radius (FIX6, U6-23).
FAR = (30.19079, 50.24681)

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def page_dump(tmp, pets=(1, 2, 3, 5, 6, 7), place_batches=(6, 7, 8),
              route="collection", pet_pages=4, one_month=False, far_batches=(),
              place_word=None):
    """Eight batches, one a month (or, `one_month`, eight days of one month).
    An animal (a different one each time) in `pets`; the files of
    `place_batches` taken at PLACE, everything else at the pack's home. The
    pack sets its own bars, so no case rests on a shipped default.
    -> (work dir, pack dir, extra argv for the pack route)."""
    root = Path(tmp)
    wd = root / "Working Files" / "dump-a"
    rows, batches = [], []
    for n in range(1, BATCHES + 1):
        month, dom = (1, 10 + n) if one_month else (n, 10)
        day = f"2029-{month:02d}-{dom:02d}"
        gps = (PLACE if n in place_batches else FAR if n in far_batches
               else ix.HOME)
        names = ([f"B{n}_C0_{k:03d}.JPG" for k in range(4)] if n in pets
                 else [f"B{n}_X.JPG"])
        for name in names:
            rows.append(ix.row(name, when=f"2029:{month:02d}:{dom:02d} 10:00:00",
                               gps=gps, SourceFile=str(wd / name)))
        word = (place_word if place_word and (n in place_batches or n in far_batches)
                else "Ford")
        batches.append({"batch": n, "from": day, "to": day, "place": word})
    ix.make_dump(root, rows=rows, batches=batches, bind=(route == "collection"))
    pack_dir = ix.make_pack(root)          # the bound dump made it already
    profile_path = pack_dir / photo_profile.PROFILE_NAME
    prof = json.loads(profile_path.read_text())
    prof.setdefault("cluster_defaults", {}).update(
        fsl_min_days=3, fsl_min_months=1 if one_month else 3,
        fsl_month_min_visits=3)
    prof["memory"] = {"batch_pages": pet_pages}
    profile_path.write_text(json.dumps(prof, indent=2))
    extra = []
    if route == "env":
        os.environ[photo_profile.ENV_VAR] = str(profile_path)
    elif route == "profile":
        extra = ["--profile", str(profile_path)]
    code, _out, err = ix.run("init", wd, *extra)
    if code:
        raise RuntimeError(err[-300:])
    pack = photo_profile.resolve_pack(explicit=profile_path)
    for n in pets:
        report, index, samples = pmc.batch_fixture(
            wd, n, [(pmc.basis(n), 4)], month=f"2029-{n:02d}")
        pmc.apply_and_memorize(wd, pack, report, index, samples,
                               {report["selected"][0]["path"]:
                                {"label": "Cat", "subject_kind": "cat"}})
    return wd, pack_dir, extra


def profile_arg(extra):
    return extra[1] if extra else None


def next_page(wd, extra):
    """-> (exit code, what it said)."""
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        try:
            rc = pm.cmd_review(argparse.Namespace(
                workdir=str(wd), profile=profile_arg(extra), checkpoint=None,
                out=None, next_page=True))
        except SystemExit as stop:
            rc = f"exit: {stop}"
    return rc, said.getvalue()


def index_of(tmp):
    return ix.index_of(tmp)[0]


def record_page(tmp, wd, page):
    """What `apply-page` records, written by hand so the COUNT is tested on
    its own: the page, its batch and the kinds it asked."""
    text = (wd / f"{page}.md").read_text()
    kinds = (["sns"] if pm.parse_review(text) else []) + \
            (["snl"] if pm.parse_places(text) else [])
    target = ix.index_of(tmp)[2]
    index = json.loads((target / "index.json").read_text())
    index["pages"].append({"page_id": page, "batch": pm.page_batch(f"{page}.md"),
                           "kinds": kinds, "status": "answered", "rows": []})
    (target / "index.json").write_text(json.dumps(index))
    return kinds


def walk_pages(tmp, wd, extra, limit=12):
    """Run `review --next-page` until no page is due, recording each page.
    -> ([(page, kinds)], last exit code, everything said)."""
    seen, spoken = [], ""
    for _ in range(limit):
        rc, said = next_page(wd, extra)
        spoken += said
        if rc != pm.PAGE_WRITTEN_RC:
            return seen, rc, spoken
        page = sorted(p.name[:-3] for p in wd.glob("P-B*.md")
                      if p.name[:-3] not in [s[0] for s in seen])[0]
        seen.append((page, record_page(tmp, wd, page)))
    return seen, "limit", spoken


@contextlib.contextmanager
def fixture_env():
    with ix.no_env():
        op.LOOKS_LIKE_DOCUMENT = lambda raw: False
        try:
            yield
        finally:
            op.LOOKS_LIKE_DOCUMENT = None
            op.ACTIVE_FILTER = op.UNARMED


# ---------------------------------------------------------------------------
# the count (D-I6, R2)
# ---------------------------------------------------------------------------

@case
def pages_go_to_the_first_pet_batches_and_every_new_place():
    """⭐ REPRODUCTION (U5-11). ⛔ FAILS on 8a70e69: there is no batch page, and
    `review` writes a dump-wide checkpoint page instead. Animals in batches
    1, 2, 3, 5, 6, 7 and a new place first seen in batch 6, with 4 pet pages:
    pages for 1, 2, 3, 5 (animals) and 6 (the place alone). Batch 4 had
    nothing to ask; 7 and 8 come after the pet pages are used. Each skip is
    in the index log."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, _pack, extra = page_dump(tmp)
        seen, rc, said = walk_pages(tmp, wd, extra)
        log = [e["change"] for e in index_of(tmp)["log"]]
    want = [("P-B01", ["sns"]), ("P-B02", ["sns"]), ("P-B03", ["sns"]),
            ("P-B05", ["sns"]), ("P-B06", ["snl"])]
    skipped = [c for c in log if ": no page — " in c]
    return (seen == want and rc == 0
            and [c[:3] for c in skipped] == ["B04", "B07", "B08"]
            and "nothing to ask" in skipped[0]
            and "pet page" in skipped[1]), \
        f"seen={seen} rc={rc} skipped={skipped} said={said[-300:]!r}"


@case
def the_pet_page_count_comes_from_the_pack():
    """REPRODUCTION (R8). ⛔ FAILS on 8a70e69. The same dump with
    `memory.batch_pages` 2: pets get pages 1 and 2, the place still gets 6."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, _pack, extra = page_dump(tmp, pet_pages=2)
        seen, rc, _said = walk_pages(tmp, wd, extra)
    return ([s[0] for s in seen] == ["P-B01", "P-B02", "P-B06"] and rc == 0
            and photo_profile.batch_pages({}) == 4), f"seen={seen} rc={rc}"


@case
def a_page_written_and_not_applied_holds_the_next_one():
    """REPRODUCTION (R4). ⛔ FAILS on 8a70e69. One page at a time: while P-B01
    has not been applied, the next call writes nothing and says which page
    waits, with the two commands that release it."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, _pack, extra = page_dump(tmp)
        first, _ = next_page(wd, extra)
        again, said = next_page(wd, extra)
        pages = sorted(p.name for p in wd.glob("P-B*.md"))
    return (first == pm.PAGE_WRITTEN_RC and again == pm.PAGE_WAITING_RC
            and pages == ["P-B01.md"] and "--page P-B01 --go" in said
            and "apply-page" in said), f"{first} {again} {pages} {said!r}"


# ---------------------------------------------------------------------------
# what a page shows
# ---------------------------------------------------------------------------

@case
def the_lines_a_waiting_page_and_a_stale_page_print_name_their_scripts():
    """REPRODUCTION (H-I follow-up, HIL01 obs-15). ⛔ FAILS on 2ac5961: these
    stops printed a bare `photo_memory.py ...` / `photo_index.py ...`, which
    runs from no folder as printed. Each line now begins with a python and
    the script's full path; a `review` line, which makes crops, names the
    pages' python (HIL-10)."""
    import shlex
    import photo_run
    scripts = ROOT / "scripts"
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(1,), place_batches=())
        next_page(wd, extra)
        _rc, waiting = next_page(wd, extra)
        page = wd / "P-B01.md"
        reg = pack_dir / "photo-subjects" / "subjects.json"
        data = json.loads(reg.read_text())
        data["subjects"].append({"subject_id": "subj-0950", "name": "Other",
                                 "who": "pet", "kind": "cat",
                                 "status": "human-confirmed", "exemplars": []})
        reg.write_text(json.dumps(data))
        page.write_text(pmc.fill_pick(page.read_text(), [1], name="Name-A"))
        _rc2, stale = pmc.confirm_page(pack_dir, wd, page="P-B01", go=True)

    def argv_of(text, needle):
        """The printed command holding `needle`: a whole line, or the
        backtick span inside a sentence."""
        line = next((ln for ln in text.splitlines() if needle in ln), "")
        if "`" in line:
            line = next((part for part in line.split("`")[1::2] if needle in part), "")
        return shlex.split(line.strip()) if line.strip() else []

    confirm = argv_of(waiting, " confirm ")
    apply_ = argv_of(waiting, " apply-page ")
    review = argv_of(stale, " review ")
    want_review_py = str(photo_run.page_python())
    ok = (len(confirm) > 2 and confirm[1] == str(scripts / "photo_memory.py")
          and len(apply_) > 2 and apply_[1] == str(scripts / "photo_index.py")
          and len(review) > 2 and review[1] == str(scripts / "photo_memory.py")
          and review[0] == want_review_py)
    return ok, f"confirm={confirm[:3]} apply={apply_[:3]} review={review[:3]}"


@case
def a_page_offers_the_owners_own_animal_names():
    """REPRODUCTION (G6 item 3). ⛔ FAILS on 8a70e69. The names declared at
    onboarding are offered on the page with the `same` token that joins a
    pick to that record."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp)
        op.declare_pets(str(pack_dir), ["Pebble", "Juniper"])
        next_page(wd, extra)
        text = (wd / "P-B01.md").read_text()
    return ("**Juniper**, **Pebble**" in text and "name: Juniper same" in text
            and len(pm.parse_review(text)) == 1), text[:900]


@case
def a_page_shows_the_page_line_a_text_answer_needs():
    """REPRODUCTION (FIX6, U6-14/U6-19). ⛔ FAILS on 0865b82: only the web
    page's copy box wrote `page: P-B01`, so an answer typed from the `.md` page
    was refused. The page says the line, and that more rows may be copied;
    neither sentence is read back as a row."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp)
        op.declare_pets(str(pack_dir), ["Pebble", "Juniper"])
        next_page(wd, extra)
        text = (wd / "P-B01.md").read_text()
    blocks = pm.parse_review(text)
    return ("`page: P-B01`" in text and "copy a row for each more animal" in text
            and len(blocks) == 1
            and all(u["verb"] in ("pick", "skip", "recheck")
                    for b in blocks for u in b["picks"])), text[:1200]


@case
def a_refused_text_answer_says_the_line_to_add():
    """REPRODUCTION (FIX6, U6-14). ⛔ FAILS on 0865b82: the refusal said only
    "apply an answer to the page it was given on". GUARD half: the same answer
    WITH the line is accepted, and a P-B01 answer is still refused on P-B02's
    name (the guard G4 exists for)."""
    import photo_review_page as rp
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp)
        op.declare_pets(str(pack_dir), ["Pebble", "Juniper"])
        next_page(wd, extra)
        md = str(wd / "P-B01.md")
        rows = "pick: 1   who: pet   name: Pebble same\n"
        said = {}
        for label, body in (("bare", rows), ("marked", "page: P-B01\n" + rows),
                            ("other", "page: P-B02\n" + rows)):
            ans = Path(tmp) / f"{label}.txt"
            ans.write_text(body, encoding="utf-8")
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    said[label] = rp.main(["apply", md, "--answer", str(ans), "--dry-run"])
            except SystemExit as exc:
                said[label] = str(exc.code)
    return (isinstance(said["bare"], str) and "page: P-B01" in said["bare"]
            and said["marked"] == 0
            and isinstance(said["other"], str) and "add this" not in said["other"]), \
        f"{said}"


@case
def a_place_page_shows_no_coordinate():
    """GUARD with a positive control (G6 item 9). The place page, the index and
    its log carry no coordinate of the place; the manifest does."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, _pack, extra = page_dump(tmp)
        walk_pages(tmp, wd, extra)
        page = (wd / "P-B06.md").read_text()
        index = (ix.index_of(tmp)[2] / "index.json").read_text()
        manifest = (wd / "manifest.csv").read_text()
    hits = [t for t in PLACE_TEXT if t in page or t in index]
    return (not hits and "30.13579" in manifest
            and len(pm.parse_places(page)) == 1), f"hits={hits}"


@case
def a_place_photo_that_looks_like_a_document_is_held_back():
    """REPRODUCTION (R9). ⛔ FAILS on 8a70e69. The place photos go through the
    U3-06 document check; a held one is counted and not shown."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, _pack, extra = page_dump(tmp, pets=(6,), place_batches=(6, 7, 8))
        op.LOOKS_LIKE_DOCUMENT = lambda raw: True
        rc = pm.cmd_review(argparse.Namespace(
            workdir=str(wd), profile=profile_arg(extra), checkpoint=None,
            out=None, batch=6, places_only=True))
        text = (wd / "P-B06.md").read_text()
    shown = [line for line in text.splitlines() if "B6_C0" in line]
    return (rc == 0 and not shown and "1 photo(s) of this place are not shown"
            in text), text[-700:]


# ---------------------------------------------------------------------------
# a place named on a page
# ---------------------------------------------------------------------------

@case
def a_place_named_on_a_page_joins_a_pack_that_holds_one():
    """⭐ REPRODUCTION (G6 SNL). ⛔ FAILS on 8a70e69. The fixture pack already
    holds `fsl-0001`; naming the page's place writes `fsl-0002` beside it,
    through `confirm --page`. A dry run first writes nothing."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(), place_batches=(6, 7, 8))
        walk_pages(tmp, wd, extra)
        page = wd / "P-B06.md"
        page.write_text(page.read_text().replace(
            "`name:` ______   `home:` ______", "`name:` Mill Pond   `home:` ______"))
        ents = pack_dir / photo_profile.ENTITIES_NAME
        before = ents.read_bytes()
        dry = pmc.confirm_page(pack_dir, wd, page="P-B06", go=False)
        unchanged = ents.read_bytes() == before
        rc, said = pmc.confirm_page(pack_dir, wd, page="P-B06", go=True)
        places = json.loads(ents.read_text())["frequent_places"]
    return (unchanged and dry[0] == 0 and rc == 0
            and [(p["id"], p["label"]) for p in places]
            == [("fsl-0001", "Harbour"), ("fsl-0002", "Mill Pond")]
            and not any(t in said for t in PLACE_TEXT)), \
        f"dry={dry[0]} rc={rc} places={places} said={said[-400:]!r}"


@case
def a_batch_page_speaks_of_no_later_checkpoint_and_no_people():
    """REPRODUCTION (G6-6 item 5). ⛔ FAILS on bbb3966: P-B01 carried the
    dump-wide "fired because … threshold", a "later checkpoint" and a `who:`
    hint listing people. A checkpoint page on the same dump keeps its own
    sentences (guard half)."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, _pack, extra = page_dump(tmp, pets=(1,), place_batches=())
        next_page(wd, extra)
        page = (wd / "P-B01.md").read_text()
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_review(argparse.Namespace(
                workdir=str(wd), profile=profile_arg(extra), checkpoint=None,
                out=None))
        checkpoint = (wd / "memory-review_C1.md").read_text()
    rmsg = photo_profile.review_messages({})
    people = [w for w in ("wife", "mother", "colleague", "self") if w in page]
    return ("fired because" not in page and "later checkpoint" not in page
            and not people and rmsg["review_hint_who_on_page"] in page
            and "fired because" in checkpoint
            and "later checkpoint" in checkpoint), \
        f"people={people} fired={'fired because' in page} " \
        f"later={'later checkpoint' in page}"


@case
def a_place_write_is_counted_in_the_closing_line():
    """REPRODUCTION (G6-6 item 5). ⛔ FAILS on bbb3966: "✅ Written" was
    followed by "wrote 0 change(s)" when the page's only answer was a place."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(), place_batches=(6, 7, 8))
        walk_pages(tmp, wd, extra)
        page = wd / "P-B06.md"
        page.write_text(page.read_text().replace(
            "`name:` ______   `home:` ______", "`name:` Mill Pond   `home:` ______"))
        rc, said = pmc.confirm_page(pack_dir, wd, page="P-B06", go=True)
    return (rc == 0 and "wrote 0 change(s)" not in said
            and "wrote 1 change(s)" in said), said[-300:]


# ---------------------------------------------------------------------------
# apply-page (G6-4)
# ---------------------------------------------------------------------------

def apply_page(wd, page, *more):
    return ix.run("apply-page", wd, page, *more)


@case
def a_confirmed_pick_reaches_who_and_the_page_trace():
    """⭐ REPRODUCTION (G6 picks). ⛔ FAILS on 4c8e639: there is no `apply-page`.
    The owner picks the declared animal's name for batch 1's frame: `confirm
    --page` puts it on the picked file's label at bare `viewed-image:` (R5 —
    the deliberate deviation from the schema's `viewed-image:owner-picked`),
    `[who]` renders the name with no `draft:`, a file nobody picked stays
    unnamed, and `apply-page` records the row with the file id and subject."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(1,), place_batches=())
        op.declare_pets(str(pack_dir), ["Pebble"])
        next_page(wd, extra)
        page = wd / "P-B01.md"
        page.write_text(pmc.fill_pick(page.read_text(), [1], who="pet",
                                      name="Pebble same"))
        rc, said = pmc.confirm_page(pack_dir, wd, page="P-B01", go=True)
        pack = photo_profile.resolve_pack(explicit=pack_dir / photo_profile.PROFILE_NAME)
        cells = photo_plan.visual_columns(wd, [1], pack.profile, pack)
        rep, other = str(wd / "B1_C0_000.JPG"), str(wd / "B1_C0_001.JPG")
        labels = json.loads((wd / "classify" / "batch-01" / "see-labels.json")
                            .read_text())["labels"]
        code, out, err = apply_page(wd, "P-B01", "--go")
        index = index_of(tmp)
        pebble = [s for s in json.loads((pack_dir / "photo-subjects" / "subjects.json")
                                        .read_text())["subjects"]
                  if s.get("name") == "Pebble"]
    file_id = {f["source"]: f["file_id"] for f in index["files"]}[rep]
    prov = [e["provenance"] for e in labels if e["path"] == rep]
    rows = (index["pages"] or [{}])[0].get("rows")
    return (rc == 0 and code == 0 and len(pebble) == 1
            and cells[rep].get("who") == "Pebble"
            and not cells[rep]["who_provenance"].startswith("draft:")
            and cells.get(other, {}).get("who") != "Pebble"
            and prov == ["viewed-image:"]
            and rows == [{"row": 1, "kind": "sns", "answer": rows[0]["answer"],
                          "file_ids": [file_id],
                          "subject_ids": [pebble[0]["subject_id"]],
                          "by": "owner-picked"}]), \
        f"rc={rc} code={code} who={cells.get(rep, {}).get('who')!r} prov={prov} " \
        f"rows={rows} err={err[-300:]!r} said={said[-300:]!r}"


@case
def a_named_place_switches_the_refs_and_proposes_a_monthly_parent():
    """⭐ REPRODUCTION (G6 SNL). ⛔ FAILS on 4c8e639. Three January visits to an
    unnamed place, named on its page: after `confirm --page` and `apply-page`,
    the three day folders point at the new `fsl-0002`, a `make-fsl-month` for
    2029-01 is PROPOSED in the output and the log, and no monthly parent is
    made."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(), one_month=True)
        next_page(wd, extra)
        page = wd / "P-B06.md"
        page.write_text(page.read_text().replace(
            "`name:` ______   `home:` ______", "`name:` Mill Pond   `home:` ______"))
        rc, _ = pmc.confirm_page(pack_dir, wd, page="P-B06", go=True)
        code, out, err = apply_page(wd, "P-B06", "--go")
        index = index_of(tmp)
    where = {fo["id"]: [r["ref"] for r in fo["where"]] for fo in index["folders"]}
    log = [e["change"] for e in index["log"]]
    return (rc == 0 and code == 0
            and [where[f] for f in ("F006", "F007", "F008")] == [["fsl-0002"]] * 3
            and "make-fsl-month" in out and "fsl-0002 2029-01" in out
            and any("proposed, not run: group make-fsl-month fsl-0002 2029-01" in c
                    for c in log)
            and not any(fo["kind"] == "fsl-month" for fo in index["folders"])
            and index["pages"][0]["rows"][0]["place_ref"] == "fsl-0002"
            and not any(t in out + json.dumps(index) for t in PLACE_TEXT)), \
        f"rc={rc} code={code} where={where} out={out[-400:]!r} err={err[-300:]!r}"


@case
def a_folder_that_keeps_the_map_word_says_it_is_outside_the_radius():
    """REPRODUCTION (FIX6, U6-23). ⛔ FAILS on 0865b82: naming a place switched
    the day folders inside its radius and said nothing about a folder with
    the SAME map word 6 km away, so the owner could not tell why one visit
    was left out. GUARD half: a switched folder gets no notice, and no
    coordinate is printed."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(), one_month=True,
                                        far_batches=(5,), place_word="Weir District")
        next_page(wd, extra)
        page = wd / "P-B06.md"
        page.write_text(page.read_text().replace(
            "`name:` ______   `home:` ______", "`name:` Mill Pond   `home:` ______"))
        pmc.confirm_page(pack_dir, wd, page="P-B06", go=True)
        code, out, err = apply_page(wd, "P-B06")
    notices = [ln for ln in out.splitlines() if "keeps its map word" in ln]
    return (code == 0 and len(notices) == 1
            and notices[0].strip().startswith("F005 keeps its map word Weir District: its days are 6.1 km "
                                              "from Mill Pond (naming radius 1 km)")
            and not any(t in out for t in PLACE_TEXT + ("30.19079", "30.191"))), \
        f"code={code} notices={notices} out={out[-500:]!r} err={err[-300:]!r}"


@case
def apply_page_refuses_what_it_cannot_record():
    """GUARD (G6-4). Refused, nothing written: a name that is not a batch page,
    a page whose answer was never confirmed, and a page applied twice."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(1,), place_batches=())
        next_page(wd, extra)
        before = (ix.index_of(tmp)[2] / "index.json").read_bytes()
        wrong = apply_page(wd, "memory-review_C1", "--go")
        page = wd / "P-B01.md"
        page.write_text(pmc.fill_pick(page.read_text(), [1], who="pet", name="Nova"))
        unconfirmed = apply_page(wd, "P-B01", "--go")
        untouched = (ix.index_of(tmp)[2] / "index.json").read_bytes() == before
        pmc.confirm_page(pack_dir, wd, page="P-B01", go=True)
        first = apply_page(wd, "P-B01", "--go")
        twice = apply_page(wd, "P-B01", "--go")
    return (wrong[0] != 0 and unconfirmed[0] != 0 and "confirm" in unconfirmed[2]
            and untouched and first[0] == 0 and twice[0] != 0
            and "already applied" in twice[2]), \
        f"wrong={wrong[0]} unconfirmed={unconfirmed[0]}:{unconfirmed[2][-200:]!r} " \
        f"first={first[0]}:{first[2][-200:]!r} twice={twice[0]}"


@case
def a_crop_ref_on_pick_is_refused_by_confirm_and_apply_page():
    """GUARD (F26). Both batch-page steps refuse `pick: 1.2` and say how to
    name two animals in one photo; nothing is written. (On 5b320fb this
    fixture also wrote nothing, but apply-page's refusal sent the owner back
    to a confirm that took the row as frames 1 and 2.)"""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(1,), place_batches=())
        next_page(wd, extra)
        page = wd / "P-B01.md"
        page.write_text(pmc.fill_pick(page.read_text(), [1], who="pet",
                                      name="Nova", frames="1.2"))
        before = (ix.index_of(tmp)[2] / "index.json").read_bytes()
        _rc, said = pmc.confirm_page(pack_dir, wd, page="P-B01", go=True)
        code, _out, err = apply_page(wd, "P-B01", "--go")
        untouched = (ix.index_of(tmp)[2] / "index.json").read_bytes() == before
        named = subjects_named(pack_dir, "Nova")
    return ("one row per name" in said and code != 0
            and "one row per name" in err and untouched and not named), \
        f"confirm={said[-300:]!r} apply-page={code}:{err[-300:]!r} named={named}"


@case
def a_page_row_naming_a_missing_file_is_reported():
    """REPRODUCTION (R11). ⛔ FAILS on 4c8e639. A page row whose file the index
    now holds as `missing` is reported by the final check, never re-linked."""
    import photo_index
    index = {"files": [{"file_id": "f-0001", "status": "present"},
                       {"file_id": "f-0002", "status": "missing"}],
             "pages": [{"page_id": "P-B03", "rows": [
                 {"row": 1, "file_ids": ["f-0001"]},
                 {"row": 2, "file_ids": ["f-0002"]}]}]}
    said = getattr(photo_index, "page_row_warnings", lambda ix_: [])(index)
    return (len(said) == 1 and "P-B03 row 2" in said[0] and "f-0002" in said[0]), \
        f"{said}"


# ---------------------------------------------------------------------------
# the web page (G6-6b): named for its page, answered back into that page
# ---------------------------------------------------------------------------

def web_render(wd, pack_dir, page):
    """-> (exit code, round-data) of `photo_review_page.py render` on a page."""
    import photo_review_page as rp
    from PIL import Image
    # The see fixture's samples are placeholder bytes; the web page decodes
    # every photo it embeds, so give each one real pixels first.
    for sample in wd.glob("classify/batch-*/samples/*.jpg"):
        try:
            Image.open(sample).size
        except Exception:                                   # noqa: BLE001
            Image.new("RGB", (32, 24), (120, 110, 90)).save(sample, "JPEG")
    said = io.StringIO()
    with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said):
        try:
            rc = rp.main(["render", str(wd / f"{page}.md"), "--workdir", str(wd),
                          "--pack", str(pack_dir)])
        except SystemExit as stop:
            return f"exit: {stop}", None, said.getvalue()
    html = (wd / f"{page}.html").read_text() if (wd / f"{page}.html").exists() else ""
    data = None
    if html:
        a = html.index('<script id="round-data" type="application/json">')
        a = html.index(">", a) + 1
        data = json.loads(html[a:html.index("</script>", a)].replace("<\\/", "</"))
    return rc, data, said.getvalue()


def web_apply(wd, page, lines):
    import photo_review_page as rp
    answer = wd / "answer.txt"
    answer.write_text("\n".join(lines) + "\n")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return rp.main(["apply", str(wd / f"{page}.md"), "--answer", str(answer)])
    except SystemExit as stop:
        return f"exit: {stop}"


def web_route_case(route):
    """⭐ REPRODUCTION (G6-6 item 1). ⛔ FAILS on 78ae1fd: the web page of a
    batch page called itself "Checkpoint C1", wrote `memory-review_C1.html`,
    and its answer carried no page, so it could land on any page. The page is
    named P-B01 and lists the owner's animals; its answer (`- page: P-B01` and
    a pick row) is refused on another page, applied to its own, and
    `confirm --page P-B01` then names the file."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(1, 2), place_batches=(),
                                        route=route)
        op.declare_pets(str(pack_dir), ["Pebble"])
        next_page(wd, extra)
        rc, data, said = web_render(wd, pack_dir, "P-B01")
        frame = sorted((data or {}).get("frames", {}), key=int)[:1]
        lines = ["- page: P-B01",
                 f"- pick: {frame[0] if frame else 1}   who: pet   name: Pebble same"]
        (wd / "P-B02.md").write_text((wd / "P-B01.md").read_text().replace(
            "sns-page: P-B01", "sns-page: P-B02"))
        wrong = web_apply(wd, "P-B02", lines)
        right = web_apply(wd, "P-B01", lines)
        confirmed, spoken = pmc.confirm_page(pack_dir, wd, page="P-B01", go=True)
        pack = photo_profile.resolve_pack(explicit=pack_dir / photo_profile.PROFILE_NAME)
        who = photo_plan.visual_columns(wd, [1], pack.profile, pack).get(
            str(wd / "B1_C0_000.JPG"), {}).get("who")
    return (rc == 0 and data and data.get("page") == "P-B01"
            and data.get("batch") == 1 and data.get("checkpoint") != "C1"
            and "Pebble" in [k["name"] for k in data.get("known_names", [])]
            and str(wrong).startswith("exit:") and right == 0
            and confirmed == 0 and who == "Pebble"), \
        f"rc={rc} page={(data or {}).get('page')} wrong={wrong} right={right} " \
        f"confirmed={confirmed} who={who!r} said={said[-200:]!r} {spoken[-300:]!r}"


@case
def a_place_page_is_answered_on_the_web_page_end_to_end():
    """⭐ REPRODUCTION (G6-6 item 2). ⛔ FAILS on 63aef2e: the web page refused
    a place-only page ("nothing for an owner to answer"). P-B06 renders a place
    question with no coordinate in it; the web answer lands on its row and
    `confirm --page` writes `fsl-0002` beside the fixture's `fsl-0001`."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(), place_batches=(6, 7, 8))
        walk_pages(tmp, wd, extra)
        rc, data, said = web_render(wd, pack_dir, "P-B06")
        html = (wd / "P-B06.html").read_text() if (wd / "P-B06.html").exists() else ""
        applied = web_apply(wd, "P-B06", ["- page: P-B06",
                                          "- place: 1   name: Mill Pond   home: "])
        confirmed, spoken = pmc.confirm_page(pack_dir, wd, page="P-B06", go=True)
        places = json.loads((pack_dir / photo_profile.ENTITIES_NAME).read_text())[
            "frequent_places"]
    return (rc == 0 and len((data or {}).get("places") or []) == 1
            and not any(t in html for t in PLACE_TEXT)
            and applied == 0 and confirmed == 0
            and [p["id"] for p in places] == ["fsl-0001", "fsl-0002"]), \
        f"rc={rc} said={said[-200:]!r} applied={applied} confirmed={confirmed} " \
        f"places={[p.get('label') for p in places]} {spoken[-300:]!r}"


@case
def a_place_only_page_speaks_of_no_checkpoint_threshold():
    """REPRODUCTION (G8). ⛔ FAILS on 8c192c1: a batch page with no animal
    question said "No draft crosses the threshold at this checkpoint" — a page
    is not a checkpoint and has no threshold."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, _pack_dir, extra = page_dump(tmp, pets=(), place_batches=(6, 7, 8))
        walk_pages(tmp, wd, extra)
        text = (wd / "P-B06.md").read_text() if (wd / "P-B06.md").exists() else ""
    msg = photo_profile.review_messages({})
    return (bool(text) and msg.get("review_no_questions_page", "\0") in text
            and msg["review_no_questions"] not in text), text[:600]


@case
def a_page_with_animals_and_a_place_shows_both_on_the_web_page():
    """REPRODUCTION (G6-6 item 2). ⛔ FAILS on 63aef2e (no place on the web
    page). An animal and a new place first seen in batch 6: one page, both."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(6,), place_batches=(6, 7, 8))
        next_page(wd, extra)
        rc, data, _said = web_render(wd, pack_dir, "P-B06")
    return (rc == 0 and len((data or {}).get("tiles") or []) == 1
            and len((data or {}).get("places") or []) == 1), \
        f"rc={rc} tiles={len((data or {}).get('tiles') or [])} " \
        f"places={len((data or {}).get('places') or [])}"


# ---------------------------------------------------------------------------
# G6-6d — two animals in one photo: two names, no exemplar
# ---------------------------------------------------------------------------

def identity_index(wd, source, animals):
    """A real-layout identity index with one row for `source`, counting
    `animals` detections (`photo_identity.load_existing` reads it as-is)."""
    import csv as _csv
    import numpy as np
    import photo_identity
    embed = wd / "embed"
    embed.mkdir(parents=True, exist_ok=True)
    with open(embed / "identity.csv", "w", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=photo_identity.CSV_FIELDS)
        w.writeheader()
        w.writerow({"SourceFile": source, "sha256": "", "status": "ok",
                    "det_index": 0, "det_count": animals, "kind": "cat",
                    "det_score": 0.9, "box": "0,0,10,10", "box_share": 0.5,
                    "error": ""})
    with open(embed / "identity.npy", "wb") as fh:
        np.save(fh, np.ones((1, 6), dtype=np.float32))
    (embed / "identity-meta.json").write_text(json.dumps(
        {**photo_identity.meta_identity(6), "created_at": "2029-01-01 00:00"}))


def two_name_page(tmp, animals, names, extra_rows=()):
    """P-B01 over one draft whose only photo holds `animals` animals (as the
    identity index counts), answered with one row per name on that photo.
    -> (work dir, pack dir, confirm exit code, what it said)."""
    wd, pack_dir, extra = page_dump(tmp, pets=(1,), place_batches=())
    op.declare_pets(str(pack_dir), ["Pebble", "Juniper"])
    next_page(wd, extra)
    identity_index(wd, str(wd / "B1_C0_000.JPG"), animals)
    page = wd / "P-B01.md"
    text = page.read_text()
    for name in names:
        text = pmc.fill_pick(text, [1], who="pet", name=name)
    page.write_text(text)
    rc, said = pmc.confirm_page(pack_dir, wd, page="P-B01", go=True)
    return wd, pack_dir, rc, said


def subjects_named(pack_dir, *names):
    subs = json.loads((pack_dir / "photo-subjects" / "subjects.json").read_text())["subjects"]
    return {s["name"]: s for s in subs if s.get("name") in names}


@case
def two_animals_in_one_photo_get_two_names_end_to_end():
    """⭐ REPRODUCTION (G6-6 item 4, end to end through confirm). ⛔ FAILS on
    5211459: both rows were refused ("answered by more than one row"). The
    photo holds 2 animals: rows `Pebble same` and `Juniper same` on it →
    `confirm --page --go` → `apply-page --go` → `[who]` is both names, no
    exemplar for either (G1), the draft is booked and not asked again (G2),
    and apply-page records both subjects on the page row trace."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, rc, said = two_name_page(tmp, 2, ["Pebble same", "Juniper same"])
        code, out, err = apply_page(wd, "P-B01", "--go")
        pack = photo_profile.resolve_pack(explicit=pack_dir / photo_profile.PROFILE_NAME)
        cell = photo_plan.visual_columns(wd, [1], pack.profile, pack).get(
            str(wd / "B1_C0_000.JPG"), {})
        named = subjects_named(pack_dir, "Pebble", "Juniper")
        registry = pm.photo_subjects.load(pack=pack)
        questions = pm.build_questions(registry, str(wd), pack, pack.profile,
                                       photo_profile.review_messages(pack.profile))[0]
        rows = (index_of(tmp)["pages"] or [{}])[0].get("rows") or []
    return (rc == 0 and code == 0
            and sorted((cell.get("who") or "").split("+")) == ["Juniper", "Pebble"]
            and not (cell.get("who_provenance") or "").startswith("draft:")
            and all(len(s.get("exemplars") or []) == 0 for s in named.values())
            and len(named) == 2 and questions == []
            and "named, not remembered as a look: 2+ animals" in said
            and sorted(sid for r in rows for sid in r.get("subject_ids", []))
            == sorted(s["subject_id"] for s in named.values())), \
        f"rc={rc} code={code} who={cell.get('who')!r}/{cell.get('who_provenance')!r} " \
        f"exemplars={[len(s.get('exemplars') or []) for s in named.values()]} " \
        f"questions={len(questions)} rows={rows} err={err[-200:]!r} said={said[-500:]!r}"


@case
def a_stale_batch_page_refusal_leads_to_the_page_again():
    """⭐ M7 (REPRODUCTION). ⛔ FAILS on 6edab52: a batch page refused as stale
    said to run `review` again; the batch page then stayed "not applied yet"
    for `--next-page` and a rewrite of it asked nothing. Followed literally,
    the new instruction ends on the page written again with its question."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, extra = page_dump(tmp, pets=(1,), place_batches=())
        next_page(wd, extra)
        page = wd / "P-B01.md"
        asked = [b["subject_ids"] for b in pm.parse_review(page.read_text())]
        reg = pack_dir / "photo-subjects" / "subjects.json"
        data = json.loads(reg.read_text())
        data["subjects"].append({"subject_id": "subj-0950", "name": "Other",
                                 "who": "pet", "kind": "cat",
                                 "status": "human-confirmed", "exemplars": []})
        reg.write_text(json.dumps(data))
        page.write_text(pmc.fill_pick(page.read_text(), [1], name="Name-A"))
        rc, said = pmc.confirm_page(pack_dir, wd, page="P-B01", go=True)
        moved = pmc.follow_stale_instruction(said, wd, Path(tmp) / "set-aside")
        rc2, _said2 = next_page(wd, extra)
        again = ([b["subject_ids"] for b in pm.parse_review(page.read_text())]
                 if page.exists() else [])
    return (rc == 1 and moved and rc2 == pm.PAGE_WRITTEN_RC and again == asked), \
        f"rc={rc} moved={moved} rc2={rc2} asked={asked} again={again} {said[-300:]!r}"


@case
def a_one_animal_photo_on_two_rows_is_still_refused():
    """GUARD (G6-6 item 4). ⛔ A photo the identity index counts ONE animal in
    (or no row at all) on two rows is refused as before, nothing written."""
    results = []
    for animals in (1, None):
        with tempfile.TemporaryDirectory() as tmp, fixture_env():
            if animals is None:
                wd, pack_dir, extra = page_dump(tmp, pets=(1,), place_batches=())
                op.declare_pets(str(pack_dir), ["Pebble", "Juniper"])
                next_page(wd, extra)
                page = wd / "P-B01.md"
                text = page.read_text()
                for name in ("Pebble same", "Juniper same"):
                    text = pmc.fill_pick(text, [1], who="pet", name=name)
                page.write_text(text)
                rc, said = pmc.confirm_page(pack_dir, wd, page="P-B01", go=True)
            else:
                wd, pack_dir, rc, said = two_name_page(tmp, animals,
                                                       ["Pebble same", "Juniper same"])
            named = subjects_named(pack_dir, "Pebble", "Juniper")
            results.append((rc, "more than one row" in said,
                            all(not s.get("exemplars") for s in named.values())))
    return results == [(1, True, True), (1, True, True)], f"{results}"


@case
def the_same_name_twice_on_one_photo_is_refused():
    """REPRODUCTION (G6-6 ruling). ⛔ One animal named twice is not two
    animals: the rows are refused, nothing written."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, rc, said = two_name_page(tmp, 2, ["Pebble same", "Pebble same"])
    return rc == 1 and "the same name is on two of its rows" in said, said[-400:]


@case
def one_name_on_a_two_animal_photo_keeps_no_exemplar():
    """⭐ REPRODUCTION (G6-6 G1). ⛔ FAILS on 5211459: one row on a photo of two
    animals promoted its whole-frame CLIP vector as the named subject's
    exemplar (D-24). The name is written; no exemplar in any space."""
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, pack_dir, rc, said = two_name_page(tmp, 2, ["Pebble same"])
        named = subjects_named(pack_dir, "Pebble")
    return (rc == 0 and "Pebble" in named and not named["Pebble"].get("exemplars")
            and "named, not remembered as a look" in said), \
        f"rc={rc} exemplars={len(named.get('Pebble', {}).get('exemplars') or [])} {said[-400:]!r}"


@case
def web_answer_route_collection_json():
    return web_route_case("collection")


@case
def web_answer_route_env_var():
    return web_route_case("env")


@case
def web_answer_route_explicit_profile():
    return web_route_case("profile")


# ---------------------------------------------------------------------------
# one case per pack route (LL-PHO-132)
# ---------------------------------------------------------------------------

def route_case(route):
    with tempfile.TemporaryDirectory() as tmp, fixture_env():
        wd, _pack, extra = page_dump(tmp, route=route)
        rc, said = next_page(wd, extra)
        written = sorted(p.name for p in wd.glob("P-B*.md"))
    return (rc == pm.PAGE_WRITTEN_RC and written == ["P-B01.md"]), \
        f"rc={rc} written={written} said={said[-200:]!r}"


@case
def route_collection_json_writes_the_first_page():
    return route_case("collection")


@case
def route_env_var_writes_the_first_page():
    return route_case("env")


@case
def route_explicit_profile_writes_the_first_page():
    return route_case("profile")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failures = []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
        try:
            ok, detail = fn()
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  "
                  f"{fn.__name__.replace('_', ' ').ljust(width)}"
                  + (f"   {detail}" if not ok else ""))
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} batch page cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
