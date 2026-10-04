#!/usr/bin/env python3
"""G2 cases — the per-dump index: `photo_index.py init` + `view`.

The index is the one plan the rest of Wave 3 renders and copies from, so these
cases hold what it must never do (carry a coordinate, move the pack id, guess
a route, lose a file id) as well as what it builds.

  python3 tests/photo_index_cases.py [-v]

Exit 0 = pass. Every dump and pack is synthetic (`betauser00`, invented
places and coordinates) in a temp dir.
"""

import argparse
import contextlib
import csv
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import golden_replay  # noqa: E402
import photo_cluster  # noqa: E402
import photo_evidence  # noqa: E402
import photo_index  # noqa: E402
import photo_plan  # noqa: E402
import photo_profile  # noqa: E402
import photo_scan  # noqa: E402
import photo_subjects  # noqa: E402
try:
    import photo_index  # noqa: E402
except ImportError:                     # the unfixed code has no such stage
    photo_index = None

TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"
FIELDS = ["SourceFile"] + photo_scan.TAGS + [photo_scan.DERIVED_LOCAL]
OWNER = "betauser00"
# Invented, and distinctive enough that finding one in an output is a leak.
HOME = (10.56789, 20.34567)
FAR = (11.98765, 21.45678)
FAKE_PLACE = "12.34,56.78"

CASES = []


class Skipped(Exception):
    """No fixture set to read. Neither a pass nor a failure — printed with its
    reason and counted apart, the photo_memory_cases.py rule."""


def case(fn):
    CASES.append(fn)
    return fn


def row(name, when="2024:11:01 10:00:00", ftype="JPEG", make="Zenith",
        gps=HOME, **extra):
    r = {k: "-" for k in FIELDS}
    r.update({"SourceFile": f"/raw/dump-a/{name}", "FileName": name,
              "FileType": ftype, "Make": make, "Model": make,
              "DateTimeOriginal": when,
              "GPSPosition": f"{gps[0]} {gps[1]}" if gps else "-"})
    r.update(extra)
    return r


def standard_rows():
    return [
        row("IMG_0001.jpg"),
        row("IMG_0001 2.jpg"),                  # a byte-identical Finder copy
        row("Screenshot_20241101_101010.jpg", make="-"),
        row("IMG_0002.jpg", when="2024:11:02 09:00:00", gps=FAR),
        row("VID_0003.mp4", when="-", ftype="MP4", make="-",
            CreateDate="2024:11:03 02:00:00",
            CreateDateLocal="2024:11:03 10:00:00"),
        row("VID_0004.mp4", when="-", ftype="MP4", make="-",
            CreateDate="2024:11:03 03:00:00"),
        row("NODATE.jpg", when="-", gps=None),
        row("WEIRD.bin", when="2024:11:03 11:00:00", ftype="FOO"),
        row("._IMG_0005.jpg", when="2024:11:03 12:00:00", ftype="MacOS"),
    ]


BATCHES = [
    {"batch": 1, "from": "2024-11-01", "to": "2024-11-01", "place": "Ford"},
    {"batch": 2, "from": "2024-11-02", "to": "2024-11-02", "place": FAKE_PLACE},
    {"batch": 3, "from": "2024-11-03", "to": "2024-11-03",
     "place": "Harbour+Townsville"},
]


def make_pack(root, homes=None, places=None):
    pack = Path(root) / "photo-memory" / OWNER
    if pack.exists():
        return pack
    shutil.copytree(TEMPLATE, pack)
    for path in list(pack.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", OWNER)))
    for leaf in (photo_profile.PROFILE_NAME, photo_profile.ENTITIES_NAME):
        p = pack / leaf
        p.write_text(p.read_text(encoding="utf-8").replace("{{SLUG}}", OWNER)
                     .replace("{{DISPLAY}}", OWNER), encoding="utf-8")
    prof = json.loads((pack / photo_profile.PROFILE_NAME).read_text())
    prof["home_locations"] = homes if homes is not None else [
        {"id": "home-01", "label": "Ford", "lat": HOME[0], "lon": HOME[1]}]
    (pack / photo_profile.PROFILE_NAME).write_text(json.dumps(prof, indent=2))
    ents = json.loads((pack / photo_profile.ENTITIES_NAME).read_text())
    ents["frequent_places"] = places if places is not None else [
        {"id": "fsl-0001", "label": "Harbour", "lat": FAR[0], "lon": FAR[1]}]
    (pack / photo_profile.ENTITIES_NAME).write_text(json.dumps(ents, indent=2))
    return pack


def make_dump(root, rows=None, batches=None, name="dump-a", bind=True,
              pack_root=None):
    workdir = Path(root) / "Working Files" / name
    workdir.mkdir(parents=True)
    with open(workdir / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows if rows is not None else standard_rows())
    (workdir / "batches.json").write_text(json.dumps(
        {"source": f"/raw/{name}", "batches": batches or BATCHES}))
    # A dest_root always; the owner only when bound — an unbound collection
    # reaches its pack by --profile or $PHOTO_PROFILE.
    coll = {"collection": "fixture", "dest_root": str(Path(root) / "sorted")}
    if bind:
        pack = make_pack(pack_root or root)
        coll.update(owner=OWNER, memory_root=str(pack.parent))
    (workdir.parent / "collection.json").write_text(json.dumps(coll))
    return workdir


@contextlib.contextmanager
def no_env():
    saved = os.environ.pop(photo_profile.ENV_VAR, None)
    photo_profile._PLACE_ID_SAID.clear()
    try:
        yield
    finally:
        os.environ.pop(photo_profile.ENV_VAR, None)
        if saved is not None:
            os.environ[photo_profile.ENV_VAR] = saved


def run(*argv):
    """-> (exit code, stdout, stderr) of one photo_index command."""
    if photo_index is None:
        raise RuntimeError("no scripts/photo_index.py")
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = photo_index.main([str(a) for a in argv])
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        err.write(str(exc.code))
    return code, out.getvalue(), err.getvalue()


def index_of(root, key="dump-a"):
    target = Path(root) / "photo-memory" / OWNER / "photo-index" / key
    return (json.loads((target / "index.json").read_text(encoding="utf-8")),
            (target / "Index_pscan.md").read_text(encoding="utf-8"), target)


def by_name(index):
    return {Path(f["source"]).name: f for f in index["files"]}


# ---------------------------------------------------------------------------
# what init builds
# ---------------------------------------------------------------------------

@case
def init_writes_the_index_and_its_view_in_the_pack():
    """REPRODUCTION. ⛔ FAILS on 2acaf5a: there is no index stage at all, so a
    folder name had no plan to render from (U5-01, U5-10)."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp)
        code, out, _ = run("init", wd)
        index, view, target = index_of(tmp)
        pointer = json.loads((wd / "index-pointer.json").read_text())
    return (code == 0 and index["index_version"] == 2
            and index["phase"] == "pscan00" and index["dump"] == "dump-a"
            and pointer == {"owner": OWNER, "dump_key": "dump-a"}
            and len(index["files"]) == 9 and view.startswith("# Index — dump-a")
            and all(index[k] in (None, []) for k in ("frozen", "pages"))), \
        f"code={code}, out={out[-300:]!r}"


@case
def every_file_sits_in_exactly_one_folder():
    """GUARD. Every present file has one folder, except a skipped sidecar,
    which is never copied and has none; every folder id is real."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        run("init", make_dump(tmp))
        index, _view, _ = index_of(tmp)
    ids = {fo["id"] for fo in index["folders"]}
    bad = [f["source"] for f in index["files"]
           if (f["route"] == "skip_junk") != (f["folder"] is None)
           or (f["folder"] is not None and f["folder"] not in ids)]
    return not bad and len(index["files"]) == 9, f"bad={bad}"


@case
def init_decides_only_the_four_pack_independent_routes():
    """GUARD. No date -> to-be-checked, a sidecar -> skipped, an unknown format
    -> others, a screenshot by NAME -> its bucket; everything else waits for G3
    (`route: null`). No class is recorded."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        run("init", make_dump(tmp))
        index, _view, _ = index_of(tmp)
    f = by_name(index)
    folders = {fo["id"]: fo for fo in index["folders"]}
    got = {n: (x["route"], x["route_source"]) for n, x in f.items()}
    want = {"NODATE.jpg": ("to_be_checked", "provisional:D13-no-date"),
            "._IMG_0005.jpg": ("skip_junk", "provisional:T0"),
            "WEIRD.bin": ("others", "provisional:D13-format"),
            "Screenshot_20241101_101010.jpg": ("screenshot", "provisional:T1-name")}
    rest = [n for n in got if n not in want and got[n] != (None, None)]
    shot = folders[f["Screenshot_20241101_101010.jpg"]["folder"]]
    return (all(got[n] == want[n] for n in want) and not rest
            and (shot["kind"], shot["bucket_key"], shot["month"])
            == ("bucket", "screenshots", "202411")
            and not any("class" in x for x in index["files"])), \
        f"got={got}, shot={shot}"


@case
def date_and_date_source():
    """GUARD. The date is `parse_date()`'s; the source says which rule gave it:
    EXIF, a video's local time from its nearest still, a video left on its raw
    UTC stamp (flagged), or none."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        run("init", make_dump(tmp))
        index, _view, _ = index_of(tmp)
    f = by_name(index)
    got = {n: (f[n]["date"], f[n]["date_source"]) for n in
           ("IMG_0001.jpg", "VID_0003.mp4", "VID_0004.mp4", "NODATE.jpg")}
    return got == {"IMG_0001.jpg": ("2024-11-01T10:00:00", "exif"),
                   "VID_0003.mp4": ("2024-11-03T10:00:00", "nearest_still"),
                   "VID_0004.mp4": ("2024-11-03T03:00:00", "flagged"),
                   "NODATE.jpg": (None, None)}, f"got={got}"


@case
def place_words_become_refs():
    """GUARD. A word equal to an id'd place's label takes its id; any other
    word is a map word; a coordinate-shaped `place` (photo_cluster.py:918
    writes one when no day could be named) is dropped, never a ref."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        _code, out, _ = run("init", make_dump(tmp))
        index, _view, _ = index_of(tmp)
    days = [fo["where"] for fo in index["folders"] if fo["kind"] == "day"]
    return (days == [[{"ref": "home-01"}], [],
                     [{"ref": "fsl-0001"}, {"ref": "map:Townsville"}]]
            and index["places"]["map:Townsville"] == {"kind": "map",
                                                      "text": "Townsville"}
            and index["places"]["home-01"]["kind"] == "home"
            and "1 batch place(s) were a coordinate" in out), f"days={days}"


@case
def a_label_two_places_share_stays_a_map_word():
    """GUARD. Two id'd places with one label point at neither: the word stays
    a map word and the run says so."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        make_pack(tmp, homes=[
            {"id": "home-01", "label": "Ford", "lat": HOME[0], "lon": HOME[1]},
            {"id": "home-02", "label": "Ford", "lat": FAR[0], "lon": FAR[1]}])
        _code, _out, err = run("init", make_dump(tmp))
        index, _view, _ = index_of(tmp)
    first = index["folders"][0]["where"]
    return (first == [{"ref": "map:Ford"}] and "share the label" in err), \
        f"first={first}, err={err!r}"


@case
def no_coordinate_in_either_file():
    """GUARD. ⛔ No `lat`/`lon` key, no manifest GPS number (whole or at
    2 dp), and not the coordinate-shaped batch place, anywhere in index.json
    or Index_pscan.md."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        run("init", make_dump(tmp))
        _index, view, target = index_of(tmp)
        raw = (target / "index.json").read_text(encoding="utf-8")

    def keys(node):
        if isinstance(node, dict):
            return set(node) | set().union(*(keys(v) for v in node.values()))
        if isinstance(node, list):
            return set().union(set(), *(keys(v) for v in node))
        return set()

    needles = [FAKE_PLACE, "12.34", "56.78"]
    for lat, lon in (HOME, FAR):
        needles += [str(lat), str(lon), f"{lat:.2f}", f"{lon:.2f}"]
    leaks = [n for n in needles if n in raw or n in view]
    bad_keys = keys(json.loads(raw)) & {"lat", "lon", "coord", "GPSPosition"}
    return not leaks and not bad_keys, f"leaks={leaks}, keys={bad_keys}"


@case
def an_index_write_leaves_the_pack_id_alone():
    """GUARD. ⛔ D-I17: `photo-index/` is outside SNAPSHOT_PARTS. If it were
    hashed, every index write would refuse every open review page as stale."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp)
        pack = photo_profile.resolve_pack(workdir=wd)
        before = pack.snapshot()["id"]
        run("init", wd)
        run("view", wd)
        after = pack.snapshot()["id"]
        index, _view, _ = index_of(tmp)
    return (before == after == index["pack_fingerprint"]), \
        f"before={before}, after={after}"


@case
def the_view_names_the_json_it_came_from():
    """GUARD. The view is regenerated from the JSON and says which version."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        run("init", make_dump(tmp))
        _index, view, target = index_of(tmp)
        digest = photo_index.index_hash(target / "index.json")
    return (digest in view and "## Phase log" in view and "index init" in view
            and "Screenshot_20241101_101010.jpg" in view), view[:400]


@case
def init_says_which_pack_it_writes_into():
    """GUARD (F-C). A copied work dir can carry a collection.json that points
    at the ORIGINAL pack; the run names the directory before writing."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp)
        _code, out, _ = run("init", wd)
        pack_dir = photo_profile.resolve_pack(workdir=wd).dir
    return f"owner pack: {pack_dir}" in out, out[:300]


# ---------------------------------------------------------------------------
# file ids
# ---------------------------------------------------------------------------

@case
def two_identical_files_get_two_ids_and_a_rerun_keeps_them():
    """REPRODUCTION (G1 of the schema check). ⛔ Keyed by SHA, a file and its
    Finder copy would be ONE entry — measured on a real dump: 4 such pairs.
    Ids are issued per source file and a re-run keeps every one."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp)
        run("init", wd)
        first, _v, _ = index_of(tmp)
        run("init", wd)
        second, _v, _ = index_of(tmp)
    a, b = by_name(first), by_name(second)
    return (a["IMG_0001.jpg"]["file_id"] != a["IMG_0001 2.jpg"]["file_id"]
            and {n: f["file_id"] for n, f in a.items()}
            == {n: f["file_id"] for n, f in b.items()}
            and len(second["log"]) == 2), f"ids={[f['file_id'] for f in first['files']]}"


@case
def a_vanished_file_keeps_its_id_and_no_id_is_reused():
    """GUARD. A file gone from the manifest stays, `missing`; a new file takes
    the next id, never the vanished one's."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp)
        run("init", wd)
        before, _v, _ = index_of(tmp)
        rows = [r for r in standard_rows() if r["FileName"] != "IMG_0002.jpg"]
        rows.append(row("IMG_0009.jpg"))
        with open(wd / "manifest.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        run("init", wd)
        after, _v, _ = index_of(tmp)
    gone, new = by_name(after)["IMG_0002.jpg"], by_name(after)["IMG_0009.jpg"]
    old_id = by_name(before)["IMG_0002.jpg"]["file_id"]
    return (gone["status"] == "missing" and gone["file_id"] == old_id
            and gone["folder"] is None and new["file_id"] == "f-0010"
            and after["file_id_next"] == 11), f"gone={gone}, new={new['file_id']}"


# ---------------------------------------------------------------------------
# the dump key
# ---------------------------------------------------------------------------

@case
def a_moved_work_dir_still_finds_its_index():
    """GUARD. The key is RECORDED, never re-derived: renaming the work dir
    does not lose the index — the pointer names it."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp)
        run("init", wd)
        moved = wd.parent / "dump-renamed"
        wd.rename(moved)
        code, out, err = run("view", moved)
        missing_new = not (Path(tmp) / "photo-memory" / OWNER / "photo-index"
                           / "dump-renamed").exists()
    return code == 0 and missing_new and "dump-a" in out, f"{out!r} {err!r}"


@case
def a_second_dump_with_the_same_key_is_refused():
    """GUARD. Two work dirs of one name, bound to one pack: the second is
    refused and told about --dump-key, which then works."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        run("init", make_dump(Path(tmp) / "one", pack_root=tmp))
        other = make_dump(Path(tmp) / "two", pack_root=tmp)
        code, _out, err = run("init", other)
        code2, _out2, _ = run("init", other, "--dump-key", "dump-a-2")
        exists = (Path(tmp) / "photo-memory" / OWNER / "photo-index"
                  / "dump-a-2" / "index.json").exists()
    return (code != 0 and "--dump-key" in err and code2 == 0 and exists), \
        f"code={code}, err={err!r}"


@case
def init_will_not_rebuild_a_later_phase():
    """GUARD. Once a later phase has touched the index, init would throw that
    work away — it refuses."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp)
        run("init", wd)
        index, _v, target = index_of(tmp)
        index["phase"] = "onb"
        (target / "index.json").write_text(json.dumps(index))
        code, _out, err = run("init", wd)
    return code != 0 and "phase" in err, f"code={code}, err={err!r}"


# ---------------------------------------------------------------------------
# one case per pack route — ⛔ LL-PHO-132 — and no pack at all
# ---------------------------------------------------------------------------

@case
def route_collection_json():
    with tempfile.TemporaryDirectory() as tmp, no_env():
        code, _out, _ = run("init", make_dump(tmp))
        ok = (Path(tmp) / "photo-memory" / OWNER / "photo-index" / "dump-a"
              / "index.json").exists()
    return code == 0 and ok, f"code={code}"


@case
def route_env_var():
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp, bind=False)
        pack = make_pack(tmp)
        os.environ[photo_profile.ENV_VAR] = str(pack / photo_profile.PROFILE_NAME)
        code, _out, _ = run("init", wd)
        ok = (pack / "photo-index" / "dump-a" / "index.json").exists()
    return code == 0 and ok, f"code={code}"


@case
def route_explicit_profile():
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp, bind=False)
        pack = make_pack(tmp)
        code, _out, _ = run("init", wd, "--profile",
                            pack / photo_profile.PROFILE_NAME)
        ok = (pack / "photo-index" / "dump-a" / "index.json").exists()
    return code == 0 and ok, f"code={code}"


@case
def no_pack_writes_nothing_and_exits_zero():
    """GUARD. ⛔ Every benchmark runs with no pack: one line, exit 0, and not
    even the pointer is written."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp, bind=False)
        before = sorted(p.name for p in wd.iterdir())
        code, out, _ = run("init", wd)
        after = sorted(p.name for p in wd.iterdir())
        stray = list(Path(tmp).rglob("index.json"))
    return (code == 0 and before == after and not stray
            and out.count("\n") == 1 and "no owner pack" in out), f"out={out!r}"


# ---------------------------------------------------------------------------
# G3 — render
# ---------------------------------------------------------------------------

WORD = "Screenshot_20241101_120000_Word.jpg"
SHOT = "Screenshot_20241102_100000.jpg"
G3_BATCHES = [
    {"batch": 1, "from": "2024-11-01", "to": "2024-11-01", "place": "Ford"},
    {"batch": 2, "from": "2024-11-02", "to": "2024-11-02", "place": "Harbour"},
]
SCORE_ID = {"model_id": "ViT-B-32", "pretrained_tag": "test-tag",
            "preprocess_fingerprint": "sha256:test"}


def g3_rows(base):
    specs = [("IMG_0101.jpg", {}), ("IMG_0102.jpg", {"when": "2024:11:01 11:00:00"}),
             (WORD, {"when": "2024:11:01 12:00:00", "make": "-"}),
             ("IMG_0201.jpg", {"when": "2024:11:02 09:00:00", "gps": FAR}),
             (SHOT, {"when": "2024:11:02 10:00:00", "make": "-"}),
             ("NODATE.jpg", {"when": "-", "gps": None})]
    return [row(n, SourceFile=f"{base}/{n}", **kw) for n, kw in specs]


def subject(sid, name, kind="cat", status=None):
    return {"subject_id": sid, "exemplars": [], "name": name, "who": name,
            "kind": kind, "status": status or photo_subjects.STATUS_CONFIRMED}


def see_label(base, name, subjects=(), what="a view"):
    return {"path": f"{base}/{name}", "label": what,
            "provenance": photo_evidence.VIEWED, "subjects": list(subjects),
            "subject_provenance": photo_evidence.VIEWED if subjects else None}


def write_see(workdir, batch, entries):
    d = workdir / "classify" / f"batch-{batch:02d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "see-labels.json").write_text(json.dumps({"labels": entries}))


def g3_dump(root, seen=(1, 2), scores=True, bind=True, batches=None):
    """A two-day dump of REAL files: day 1 holds a CONFIRMED cat at
    `viewed-image:` and a paperwork screenshot, day 2 a DRAFT dog and a plain
    screenshot; one file has no date. -> (work dir, pack dir)."""
    base = Path(root).resolve() / "raw" / "dump-a"
    base.mkdir(parents=True)
    rows = g3_rows(base)
    for r in rows:
        # JPEG-shaped and distinct per file: the OA-4 rename sweep that follows
        # a copy reads each copied file's real type.
        note = r["FileName"].encode()
        Path(r["SourceFile"]).write_bytes(
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"\xff\xfe" + (len(note) + 2).to_bytes(2, "big") + note + b"\xff\xd9")
    wd = make_dump(root, rows=rows, batches=batches or G3_BATCHES, bind=bind)
    pack = make_pack(root)
    reg = pack / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text(encoding="utf-8"))
    data["subjects"] = [subject("subj-0001", "Lotus"),
                        subject("subj-0002", "Rex", "dog",
                                photo_subjects.STATUS_DRAFT)]
    reg.write_text(json.dumps(data), encoding="utf-8")
    labels = {1: [see_label(base, "IMG_0101.jpg", [{"subject_id": "subj-0001"}],
                            "sofa nap"),
                  see_label(base, "IMG_0102.jpg", what="sofa nap"),
                  see_label(base, WORD, what="a document")],
              2: [see_label(base, "IMG_0201.jpg", [{"subject_id": "subj-0002"}],
                            "harbour walk"),
                  see_label(base, SHOT, what="a chat")]}
    for n in seen:
        write_see(wd, n, labels[n])
    with open(wd / "no-date-files.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(r for r in rows if r["DateTimeOriginal"] == "-")
    if scores:
        embed = wd / "embed"
        embed.mkdir()
        (embed / "embeddings-meta.json").write_text(json.dumps(SCORE_ID))
        (embed / "paperwork-scores.json").write_text(json.dumps(
            {**SCORE_ID, "scores": {f"{base}/{WORD}": 0.5}}))
    return wd, pack


def folders_of(index):
    return {fo["id"]: fo for fo in index["folders"]}


def tree_state(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


@case
def render_names_a_confirmed_subject_and_never_a_draft():
    """⭐ REPRODUCTION of U5-01 at the index. ⛔ FAILS on 5efc4e5: nothing
    rendered a folder name at all, so a pet confirmed before the copy never
    reached one (UAT01-5: 0 of 47). The confirmed cat at `viewed-image:` is in
    its folder's name; the DRAFT dog is in no name, not even as a class word."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        run("init", wd)
        code, out, err = run("render", wd)
        index, view, _ = index_of(tmp)
    f = folders_of(index)
    return (code == 0 and f["F001"]["rendered"] == "20241101_Ford_Lotus_sofa nap"
            and f["F002"]["rendered"] == "20241102_Harbour_harbour walk"
            and not f["F001"]["validation"]["refusals"]
            and "Lotus (1)" in view), \
        f"code={code} names={[fo['rendered'] for fo in index['folders']]} err={err[-300:]!r}"


@case
def render_settles_every_route_and_logs_each_disagreement():
    """REPRODUCTION (ruling 7). ⛔ FAILS on 5efc4e5: init's four routes were
    the last word. The paperwork screenshot that init called a screenshot is
    settled by photo_plan.route() into the to-be-checked bucket (ADR 0005), the
    change is logged, and every file's route is now a settled one."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = g3_dump(tmp)
        run("init", wd)
        code, _out, _err = run("render", wd)
        index, _view, _ = index_of(tmp)
        words = photo_profile.buckets(photo_profile.resolve_pack(workdir=wd).profile)
    f, fo = by_name(index), folders_of(index)
    word, nodate = f[WORD], f["NODATE.jpg"]
    logged = [e["change"] for e in index["log"] if WORD in e["change"]]
    return (code == 0 and word["route"] == "to_be_checked"
            and word["route_source"] == "settled:paperwork"
            and fo[word["folder"]]["rendered"] == f"20241100_{words['to_be_checked']}"
            and fo[f[SHOT]["folder"]]["rendered"] == f"20241100_{words['screenshots']}"
            # ⛔ CHANGED BY M14 (owner rulings Q8/Q10, 20260922). This used to
            # expect `202400_<word>` — dump_yyyymm() falling back to the
            # batches' year — i.e. a no-EXIF STILL filed under a year taken
            # from the DUMP. That is exactly what "no folder may claim a year
            # it cannot support" rules out. NODATE.jpg is a no-EXIF still on a
            # manifest that carries FileModifyDate, so it now lands in the one
            # undated bucket under its import. The expectation is computed
            # from photo_plan.undated_rel() — the function that BUILDS it — so
            # this test cannot become a second copy of the rule.
            and fo[nodate["folder"]]["rendered"] == photo_plan.undated_rel(
                words["to_be_checked"], wd)
            and logged == [f"{word['file_id']} {WORD}: screenshot → to_be_checked"]
            and all(x["route_source"].startswith("settled:") for x in index["files"])), \
        f"code={code} word={word} logged={logged}"


def bucket_name_problems(rendered_name, import_name):
    """-> the problems the REAL `run_check()` raises about one bucket's name,
    for a work dir whose NAME is `import_name`.

    ⛔ In-process on purpose, and it is still the real check: the `/`
    exception keys on `photo_plan.undated_rel()` for THIS work dir, so proving
    it needs to control the work dir's name. The fixture's dump is always
    `dump-a`, so the work dir is copied whole under the new name — everything
    `run_check` reads from it (batches, the agent view) comes along."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = rendered(tmp)
        index, _view, _ = index_of(tmp)
        pack = photo_profile.resolve_pack(workdir=wd)
        alt = wd.parent / import_name
        shutil.copytree(wd, alt)
        bucket = next(fo for fo in folders_of(index).values()
                      if fo["kind"] == "bucket"
                      and fo["bucket_key"] == "to_be_checked")
        bucket.update(rendered=rendered_name, status="proposed")
        problems, _warnings = photo_index.run_check(alt, pack, index)
        word = photo_profile.buckets(pack.profile)["to_be_checked"]
    return [p for p in problems if bucket["id"] in p], word


@case
def check_admits_exactly_the_undated_bucket():
    """REPRODUCTION (M14). At ec96863 the index refused the undated stills
    bucket outright: `check` reads any `/` in a name as "not a usable folder
    name", so the ONE two-level bucket the owner chose (Q10) could never
    pass. It passes now — and only because its name IS the path
    `photo_plan.undated_rel()` built for this work dir."""
    probe = "import-a"
    _p, word = bucket_name_problems("x", probe)
    got, _w = bucket_name_problems(f"_{word}/{probe}", probe)
    return not got, got


@case
def check_still_refuses_every_other_slash_shape():
    """GUARD — the exception is ONE shape, not a class. Each of these carries a
    `/` and none is the undated bucket for this work dir, so each is still
    "not a usable folder name"."""
    probe = "import-a"
    _p, word = bucket_name_problems("x", probe)
    bad = {}
    for name in (f"_{word}/{probe}/extra",     # three levels
                 f"_Other/{probe}",             # another word
                 f"{word}/{probe}",             # no underscore
                 f"_{word}/someone-else"):      # not THIS import
        got, _w = bucket_name_problems(name, probe)
        if not any("not a usable folder name" in p for p in got):
            bad[name] = got
    return not bad, bad


@case
def check_runs_the_coordinate_test_even_when_the_slash_is_excused():
    """⭐ THE CASE THAT PROVES THE EXCEPTION IS SURGICAL (Lead, 20260922).

    The work dir is NAMED like a coordinate, so `undated_rel()` produces
    `_<word>/<coordinate>` and the `/` IS excused — the slash test is exactly
    satisfied. `import_folder()` lets it through (a comma, a dot and a space
    are not characters a drive refuses). Operational Rule 3 must still refuse
    it. If this passes silently, the exception was written as a skip and it
    took the coordinate check with it."""
    probe = "12.3456,56.7890"
    _p, word = bucket_name_problems("x", probe)
    got, _w = bucket_name_problems(f"_{word}/{probe}", probe)
    usable = [p for p in got if "not a usable folder name" in p]
    coord = [p for p in got if "coordinate" in p]
    return (not usable and bool(coord)), got


@case
def init_and_render_agree_on_every_no_date_file():
    """REPRODUCTION (M14 (ii), Lead 20260922). init guessed every no-date
    file's bucket itself (the dump's month) and render then moved each one
    into its real bucket, logging a "disagreement" per file. Measured on real
    work dirs: 12 on a realistic import, 257 on the largest — each reading
    `to_be_checked → to_be_checked`. init now CALLS photo_plan.no_date_dest(),
    the function render's routing uses, so there is nothing to disagree about.
    Measured on this fixture at 9b3245c: 1 such line. Now: 0."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        run("init", wd)
        run("render", wd)
        index, _view, _ = index_of(tmp)
    nodate = {f["file_id"] for f in index["files"] if f["date"] is None}
    about = [e["change"] for e in index["log"]
             if e["change"].split(" ")[0] in nodate]
    return bool(nodate) and not about, f"no-date={sorted(nodate)} logged={about}"


@case
def a_genuine_route_change_is_still_logged():
    """GUARD. Silencing the no-date noise must not silence the signal: the
    paperwork screenshot init calls a screenshot and photo_plan settles into
    the to-be-checked bucket is a REAL route change, and it is still logged,
    once, with both routes named."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        run("init", wd)
        run("render", wd)
        index, _view, _ = index_of(tmp)
    word = by_name(index)[WORD]
    got = [e["change"] for e in index["log"] if WORD in e["change"]]
    return got == [f"{word['file_id']} {WORD}: screenshot → to_be_checked"], got


@case
def a_folder_only_move_says_which_folder_not_x_to_x():
    """REPRODUCTION. The log entry printed the route alone, so a file whose
    route held and whose FOLDER moved read "to_be_checked → to_be_checked" —
    a line that looks meaningless on its face. It now names the folder. The
    move is forced here by pointing the no-date file at another bucket after
    init, so render has a folder-only change to report."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        run("init", wd)
        state = {}

        def repoint(ix):
            f = next(x for x in ix["files"] if x["date"] is None)
            other = next(fo for fo in ix["folders"] if fo["kind"] == "bucket"
                         and fo["id"] != f["folder"])
            state.update(fid=f["file_id"], wrong=other["id"])
            f["folder"] = other["id"]
        edit_index(tmp, repoint)
        run("render", wd)
        index, _view, _ = index_of(tmp)
    got = [e["change"] for e in index["log"]
           if e["change"].startswith(state["fid"] + " ")]
    return (len(got) == 1 and "folder" in got[0] and state["wrong"] in got[0]
            and "to_be_checked → to_be_checked" not in got[0]), got


@case
def the_render_summary_does_not_count_a_folder_move_as_a_route_change():
    """REPRODUCTION (Lead, 20260922). The per-line fix stopped a folder-only
    move reading "X → X"; the SUMMARY still said "N route(s) changed" while
    counting every (route, folder) change — the same untruth as a count. Here
    one file genuinely changes route (the paperwork screenshot) and one only
    changes folder (forced), so the two must be reported apart."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        run("init", wd)

        def repoint(ix):
            f = next(x for x in ix["files"] if x["date"] is None)
            f["folder"] = next(fo["id"] for fo in ix["folders"]
                               if fo["kind"] == "bucket"
                               and fo["id"] != f["folder"])
        edit_index(tmp, repoint)
        _code, out, _err = run("render", wd)
        index, _view, _ = index_of(tmp)
    summary = [e["change"] for e in index["log"] if "day folder(s)" in e["change"]]
    return (len(summary) == 1
            and "1 route(s) changed" in summary[0]
            and "1 folder-only move(s)" in summary[0]
            and "1 route(s) differ" in out
            and "1 folder-only move(s)" in out), (summary, out[-300:])


@case
def render_leaves_the_work_dir_and_the_pack_id_alone():
    """GUARD. render routes with the PURE seams: the work dir is byte-for-byte
    unchanged and the pack id does not move (the index is outside it)."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        run("init", wd)
        before, pid = tree_state(wd), photo_profile.resolve_pack(workdir=wd).snapshot()["id"]
        code, _out, _err = run("render", wd)
        after = tree_state(wd)
        pid2 = photo_profile.resolve_pack(workdir=wd).snapshot()["id"]
    return code == 0 and before == after and pid == pid2, \
        f"code={code} changed={sorted(set(before) ^ set(after))}"


@case
def render_refuses_an_unseen_batch_unless_no_vision():
    """GUARD (R1). A batch the see stage never ran for would be named from
    metadata alone; render says which and stops, and --no-vision goes past."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp, seen=(1,))
        run("init", wd)
        code, _out, err = run("render", wd)
        code2, _out2, _ = run("render", wd, "--no-vision")
        index, _view, _ = index_of(tmp)
    return (code != 0 and "B2" in err and code2 == 0
            and index["render"]["no_vision"] is True), f"code={code} err={err!r}"


@case
def the_view_header_shows_the_pack_the_render_used():
    """REPRODUCTION (FIX7, F5-a). ⛔ FAILS on b58f0fd: `Index_pscan.md` showed
    only the id init/recut/freeze write, so after a render on a changed pack
    the header still named the old one and read as current."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = rendered(tmp)
        rename_lotus(pack)
        run("render", wd)
        index, view, _ = index_of(tmp)
    top = index["pack_fingerprint"]
    used = index["render"]["pack_fingerprint"]
    return (top != used and f"pack `{top}`" in view
            and f"rendered with pack `{used}`" in view), \
        f"top={top} used={used} header={[l for l in view.splitlines() if 'pack' in l]}"


@case
def render_dry_run_prints_the_name_diff_and_writes_nothing():
    """REPRODUCTION (FIX7, U7-3). ⛔ FAILS on b58f0fd: render had no dry run,
    so a name change could only be seen by writing it."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = rendered(tmp)
        rename_lotus(pack)
        target = index_of(tmp)[2]
        before = tree_state(target)
        code, out, err = run("render", wd, "--dry-run")
        after = tree_state(target)
    return (code == 0 and before == after
            and "1 folder name(s) would change" in out
            and "F001" in out and "Momo" in out), \
        f"code={code} out={out!r} err={err[-300:]!r}"


@case
def render_dry_run_says_what_fills_a_new_folder():
    """⭐ REPRODUCTION (UAT02-02 F-kk, narrowed by the Lead 20260924). ⛔ FAILS
    on c5b6f99: a folder a route creates (the paperwork bucket) was listed as
    a bare "a new folder". It now says how many files and which route."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        run("init", wd)
        code, out, err = run("render", wd, "--dry-run")
    lines = [l for l in out.splitlines() if "why: a new folder" in l]
    return (code == 0 and lines and all(re.search(r"— \d+ file\(s\): \d+ ", l)
                                        for l in lines)), \
        f"code={code} lines={lines[:3]} out={out[-300:]!r} err={err[-300:]!r}"


@case
def render_dry_run_says_why_each_name_would_change():
    """⭐ REPRODUCTION (M3, UAT01-9 F5 / UAT01-10 F4). ⛔ FAILS on 4739665: 11
    names moved and the dry run never said why. Each changed folder now
    carries a `why:` line, and a pack that moved since the last render is
    said once."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = rendered(tmp)
        rename_lotus(pack)
        code, out, err = run("render", wd, "--dry-run")
    return (code == 0 and "why: [who] Lotus is now Momo" in out
            and "the owner pack changed since the last render" in out), \
        f"code={code} out={out!r} err={err[-300:]!r}"


@case
def freeze_next_line_offers_the_dry_run_first_and_the_short_name():
    """REPRODUCTION (N3, UAT01-9 F7a). ⛔ FAILS on 4739665: `next:` went
    straight to `finish "<full path>" --go`. It now offers the dry run first,
    then `--go`, by the dump's name when `finish` run from the same folder
    resolves that name back to this work dir — else by its full path."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = rendered(tmp)
        here = os.getcwd()
        try:
            os.chdir(tmp)
            code, out, _e = run("freeze", wd)
        finally:
            os.chdir(here)
        run("unfreeze", wd, "--reason", "again, from elsewhere")
        code2, out2, _e2 = run("freeze", wd)
    lines = out.split("next:", 1)[-1].splitlines()
    far = out2.split("next:", 1)[-1].splitlines()
    return (code == 0 and code2 == 0 and len(lines) >= 2
            and lines[0].strip().startswith("photo_run.py finish dump-a ")
            and "dry run" in lines[0]
            and lines[1].strip() == "photo_run.py finish dump-a --go"
            and far[1].strip() == f'photo_run.py finish "{wd.resolve()}" --go'), \
        f"near={lines[:2]} far={far[:2]}"


@case
def render_dry_run_is_allowed_while_the_freeze_holds():
    """REPRODUCTION (FIX7, U7-3). A holding freeze refuses a render; a dry
    run writes nothing, so it runs and the freeze stays."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack, fcode, _o, _e = frozen(tmp)
        target = index_of(tmp)[2]
        before = tree_state(target)
        code, out, err = run("render", wd, "--dry-run")
        after = tree_state(target)
        refused, _o2, _e2 = run("render", wd)
        index = index_of(tmp)[0]
    return (fcode == 0 and code == 0 and refused != 0 and before == after
            and index["frozen"] is not None
            and "no folder name would change" in out
            and "stays frozen" in out), f"code={code} out={out!r} err={err[-300:]!r}"


# ---------------------------------------------------------------------------
# G3 — check (P4, D-I9)
# ---------------------------------------------------------------------------

def rendered(tmp, **kw):
    wd, pack = g3_dump(tmp, **kw)
    run("init", wd)
    run("render", wd)
    return wd, pack


def edit_index(tmp, fn):
    index, _view, target = index_of(tmp)
    fn(index)
    (target / "index.json").write_text(json.dumps(index), encoding="utf-8")


@case
def init_refuses_to_rebuild_a_rendered_index():
    """REPRODUCTION (G4 R7). ⛔ FAILS on 1fce778: init refused only a phase
    other than pscan00, and render never moves the phase, so a re-init
    silently dropped every settled route and name and renumbered the folders."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = rendered(tmp)
        before = index_of(tmp)[0]
        code, _out, err = run("init", wd)
        after = index_of(tmp)[0]
    return (code != 0 and "rendered" in err and "recut" in err
            and before == after), f"code={code} err={err!r}"


@case
def check_passes_a_rendered_index():
    """REPRODUCTION. ⛔ FAILS on 8998916: there was no final check (P4), so
    nothing stood between a rendered name and the copy."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = rendered(tmp)
        code, out, err = run("check", wd)
    return code == 0 and "check passed" in out, f"code={code} {out!r} {err!r}"


@case
def check_fails_an_index_not_rendered():
    """GUARD. init alone leaves provisional routes and no names."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        run("init", wd)
        code, out, _err = run("check", wd)
    return code == 1 and "render" in out, f"code={code} {out!r}"


@case
def check_fails_a_pack_changed_since_render():
    """GUARD. A subject renamed after render would leave its old name in a
    folder name no current name matches — the pack id says so first."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = rendered(tmp)
        reg = pack / "photo-subjects" / "subjects.json"
        reg.write_text(reg.read_text(encoding="utf-8").replace('"Lotus"', '"Momo"'),
                       encoding="utf-8")
        code, out, _err = run("check", wd)
    return code == 1 and "changed since render" in out, f"code={code} {out!r}"


@case
def check_fails_a_name_no_copied_file_backs():
    """GUARD (the W2-B tree guard). A subject's name in a folder none of whose
    copied files shows that subject is refused, whoever wrote it."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = rendered(tmp)
        edit_index(tmp, lambda ix: folders_of(ix)["F002"].update(
            rendered="20241102_Harbour_Lotus"))
        code, out, _err = run("check", wd)
    return code == 1 and "F002" in out and "Lotus" in out and "F12" in out, out


@case
def check_fails_a_coordinate_in_a_name():
    """GUARD (Operational Rule 3)."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = rendered(tmp)
        edit_index(tmp, lambda ix: folders_of(ix)["F002"].update(
            rendered="20241102_12.3456,56.7890"))
        code, out, _err = run("check", wd)
    return code == 1 and "coordinate" in out, out


@case
def check_fails_a_street_address_but_keeps_the_owners_own_label():
    """GUARD. A map word that reads as an address is refused; the owner's own
    home label that reads as one is used and warned about (R13/D-F9).
    ⚠️ `is_address()` knows CJK addresses only (a known card), so the two
    address words are written as escapes to keep this source ASCII."""
    label, lane = "12\u865f", "7\u5df7"
    with tempfile.TemporaryDirectory() as tmp, no_env():
        make_pack(tmp, homes=[{"id": "home-01", "label": label,
                               "lat": HOME[0], "lon": HOME[1]}])
        batches = [dict(G3_BATCHES[0], place=label), dict(G3_BATCHES[1], place=lane)]
        wd, _pack = rendered(tmp, batches=batches)
        code, out, _err = run("check", wd)
    lines = out.splitlines()
    problem = [x for x in lines if "⛔" in x and lane in x and "F002" in x]
    warned = [x for x in lines if "⚠️" in x and label in x and "F001" in x]
    return code == 1 and problem and warned and not any(
        "⛔" in x and label in x for x in lines), out


# ---------------------------------------------------------------------------
# G3 — dest: merge / fill_shell keep the owner's folder name (D6)
# ---------------------------------------------------------------------------

def existing(tmp, name, scanned=True):
    """An owner's hand-named folder on the drive, and (scanned) the work dir
    holding its manifest — the dedupe reference. -> (folder, ref work dir)."""
    folder = Path(tmp) / "drive" / name
    folder.mkdir(parents=True)
    ref = Path(tmp) / "Working Files" / f"ref-{len(list(folder.parent.iterdir()))}"
    if scanned:
        ref.mkdir(parents=True)
        with open(ref / "manifest.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerow(row("OLD_0001.jpg"))
    return folder, ref


@case
def a_merge_folder_keeps_the_owners_name():
    """⭐ REPRODUCTION (D6). ⛔ FAILS on 37aec55: nothing could say that a day
    folder goes into an existing hand-named one, so render would name it
    anew. With `dest merge`, the owner's name is the folder's name, the copy is
    deduped against the folder's manifest, and the change is logged."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        folder, ref = existing(tmp, "Ford weekend (kept)")
        run("init", wd)
        code, out, err = run("dest", wd, "F001", "merge", folder, "--ref", ref,
                             "--reason", "the owner already has this folder")
        run("render", wd)
        code2, out2, _ = run("check", wd)
        index, view, _ = index_of(tmp)
        deduped = (wd / "plan" / "dedupe_batch-01.json").exists()
    fo = folders_of(index)["F001"]
    logged = [e for e in index["log"] if e["cmd"] == "index dest"]
    return (code == 0 and fo["rendered"] == "Ford weekend (kept)"
            and fo["dest"] == {"mode": "merge", "existing_path": str(folder.resolve()),
                               "refs": [str(ref.resolve())]}
            and deduped and code2 == 0 and "kept (D6)" in out2
            and logged and logged[0]["reason"] == "the owner already has this folder"
            and "merge into `Ford weekend (kept)`" in view), \
        f"code={code} {err!r} rendered={fo['rendered']!r} check={code2} {out2!r}"


@case
def a_fill_shell_folder_keeps_the_owners_name_without_a_ref():
    """GUARD. An empty shell has nothing to dedupe against."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        folder, _ref = existing(tmp, "20241102_Harbour", scanned=False)
        run("init", wd)
        code, _out, err = run("dest", wd, "F002", "fill_shell", folder,
                              "--reason", "an empty shell the owner made")
        run("render", wd)
        index, _view, _ = index_of(tmp)
    return (code == 0 and folders_of(index)["F002"]["rendered"] == "20241102_Harbour"), \
        f"code={code} {err!r}"


@case
def dest_refuses_what_it_cannot_record():
    """GUARD. Not a directory · a merge with no dedupe reference · a reference
    with no manifest · a bucket folder: each refused, the index unchanged."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        folder, ref = existing(tmp, "Ford weekend")
        run("init", wd)
        before = index_of(tmp)[0]
        codes = [run("dest", wd, "F001", "merge", Path(tmp) / "nowhere", "--ref", ref,
                     "--reason", "x")[0],
                 run("dest", wd, "F001", "merge", folder, "--reason", "x")[0],
                 run("dest", wd, "F001", "merge", folder, "--ref", folder,
                     "--reason", "x")[0],
                 run("dest", wd, "F003", "merge", folder, "--ref", ref,
                     "--reason", "x")[0]]
        after = index_of(tmp)[0]
    return all(c != 0 for c in codes) and before == after, f"codes={codes}"


@case
def the_owners_folder_name_still_needs_its_who_backed():
    """GUARD (ruling 5). The owner's name is never rendered over and its
    grammar only warns — but a pet's name in it must still be backed by a
    file copied into it (F12)."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = g3_dump(tmp)
        folder, _ref = existing(tmp, "20241102_Harbour_Lotus", scanned=False)
        run("init", wd)
        run("dest", wd, "F002", "fill_shell", folder, "--reason", "the owner's shell")
        run("render", wd)
        code, out, _err = run("check", wd)
    return code == 1 and "F002" in out and "F12" in out, out


# ---------------------------------------------------------------------------
# G3 — freeze · verify · unfreeze (D-I16)
# ---------------------------------------------------------------------------

def frozen(tmp, **kw):
    wd, pack = rendered(tmp, **kw)
    code, out, err = run("freeze", wd)
    return wd, pack, code, out, err


def csv_rows(wd, rel):
    with open(wd / rel, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rename_lotus(pack):
    reg = pack / "photo-subjects" / "subjects.json"
    reg.write_text(reg.read_text(encoding="utf-8").replace('"Lotus"', '"Momo"'),
                   encoding="utf-8")


@case
def freeze_exports_the_plan_the_index_holds():
    """⭐ REPRODUCTION (U5-01's copy path). ⛔ FAILS on 3ef9085: no code wrote
    plans.json from a checked index — it was typed before the naming round, so
    a pet's name never reached a destination. The frozen plan's destination IS
    the rendered name, photo_plan itself wrote the CSVs, and every file to be
    copied has its SHA-256 recorded; the freeze is timed."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack, code, out, err = frozen(tmp)
        index, view, _ = index_of(tmp)
        plans = json.loads((wd / "plans.json").read_text())
        p1 = csv_rows(wd, "plan/plan_P1-files.csv")
        verify = run("verify", wd)[0]
    dest = plans["plans"][0]["dest"]["path"] if plans.get("plans") else ""
    copies = [f for f in index["files"] if f["route"] in photo_index.COPIED]
    return (code == 0 and plans.get("generated_by") == "photo_index"
            and Path(dest).name == "20241101_Ford_Lotus_sofa nap"
            and {r["destination"] for r in p1 if r["FileName"].startswith("IMG_")}
            == {dest}
            and index["phase"] == "final" and index["frozen"]["seconds"] >= 0
            and len(copies) == 6 and all(f["sha256"] for f in copies)
            and verify == 0 and "FROZEN" in view and "frozen sha256:" in out), \
        f"code={code} err={err[-400:]!r} dest={dest!r}"


@case
def freeze_records_the_reason_it_is_given():
    """REPRODUCTION (FIX8 F8-3, UAT01-8 F6). `unfreeze` demands a reason and
    `freeze` took none, so a re-lock after a correction could not say why.
    Given, it replaces the fixed log text; not given, the fixed text stays."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = rendered(tmp)
        code, _out, err = run("freeze", wd, "--reason", "the owner corrected two names")
        index, _view, _ = index_of(tmp)
    rows = [e for e in index["log"] if e["cmd"] == "index freeze"]
    return (code == 0 and rows
            and rows[-1]["reason"] == "the owner corrected two names"), \
        f"code={code} err={err[-300:]!r} rows={rows[-1:]}"


@case
def freeze_with_no_reason_keeps_the_fixed_log_text():
    """GUARD (F8-3). The reason is optional; the default is unchanged."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        _wd, _pack, code, _out, err = frozen(tmp)
        index, _view, _ = index_of(tmp)
    rows = [e for e in index["log"] if e["cmd"] == "index freeze"]
    return (code == 0 and rows and rows[-1]["reason"]
            == "the final check passed (D-I9); the names are locked (D-I16)"), \
        f"code={code} err={err[-300:]!r} rows={rows[-1:]}"


@case
def freeze_refuses_a_hand_written_plans_json():
    """GUARD (ruling 6). A hand-written plans.json — and the execute-state of
    a copy made from it — is never overwritten: refused; with --replace-plans
    it and its plan files are moved aside, stamped."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = rendered(tmp)
        hand = {"dest_root": "/x", "plans": [{"plan": 1, "batches": [1], "dest": {
            "mode": "new", "path": "/x/typed"}}]}
        (wd / "plans.json").write_text(json.dumps(hand))
        (wd / "plan").mkdir(exist_ok=True)
        (wd / "plan" / "execute-state_P1.json").write_text('{"plan": 1, "verified": {}}')
        code, _out, err = run("freeze", wd)
        kept = json.loads((wd / "plans.json").read_text()) == hand
        code2, _out2, err2 = run("freeze", wd, "--replace-plans")
        baks = [p.name for p in wd.iterdir()
                if p.name.startswith(("plans.json.bak-", "plan.bak-"))]
        moved = any((wd / b / "execute-state_P1.json").exists() for b in baks)
        generated = json.loads((wd / "plans.json").read_text()).get("generated_by")
    return (code != 0 and "--replace-plans" in err and kept and code2 == 0
            and len(baks) == 2 and moved and generated == "photo_index"), \
        f"code={code} code2={code2} baks={baks} err2={err2[-300:]!r}"


@case
def freeze_refuses_when_the_check_fails():
    """GUARD. Nothing is exported from an index the final check fails."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = rendered(tmp)
        edit_index(tmp, lambda ix: folders_of(ix)["F002"].update(
            rendered="20241102_12.3456,56.7890"))
        code, _out, err = run("freeze", wd)
        wrote = (wd / "plans.json").exists()
    return code != 0 and "check fails" in err and not wrote, err


@case
def verify_holds_until_the_index_the_plan_files_or_the_pack_change():
    """REPRODUCTION (D-I16 / G8). ⛔ FAILS on 3ef9085: there was no freeze to
    hold. A changed name, a moved file, an edited plan file or a changed pack
    each make verify exit 4; untouched, it exits 0."""
    def name(tmp, wd, pack):
        edit_index(tmp, lambda ix: folders_of(ix)["F001"].update(
            rendered="20241101_Ford_Other"))

    def folder(tmp, wd, pack):
        edit_index(tmp, lambda ix: by_name(ix)["IMG_0102.jpg"].update(folder="F002"))

    def plan_file(tmp, wd, pack):
        p = wd / "plan" / "plan_P1-files.csv"
        p.write_text(p.read_text(encoding="utf-8").replace("sofa nap", "sofa naps"),
                     encoding="utf-8")

    def pack_changed(tmp, wd, pack):
        rename_lotus(pack)

    got = {}
    for what, change in (("nothing", None), ("name", name), ("folder", folder),
                         ("plan file", plan_file), ("pack", pack_changed)):
        with tempfile.TemporaryDirectory() as tmp, no_env():
            wd, pack, _code, _out, _err = frozen(tmp)
            if change:
                change(tmp, wd, pack)
            got[what] = run("verify", wd)[0]
    return got == {"nothing": 0, "name": 4, "folder": 4, "plan file": 4,
                   "pack": 4}, f"{got}"


@case
def a_freeze_that_holds_locks_the_names_until_unfrozen():
    """GUARD (D-I16). render and dest refuse on a freeze that still holds;
    unfreeze lifts it with a logged reason, and render works again."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack, _code, _out, _err = frozen(tmp)
        code, _o, err = run("render", wd)
        code_d = run("dest", wd, "F001", "new", "--reason", "x")[0]
        code_u = run("unfreeze", wd, "--reason", "a pet was renamed")[0]
        code_r = run("render", wd)[0]
        index, _v, _ = index_of(tmp)
    reasons = [e["reason"] for e in index["log"] if e["cmd"] == "index unfreeze"]
    return (code != 0 and "unfreeze" in err and code_d != 0 and code_u == 0
            and code_r == 0 and reasons == ["a pet was renamed"]
            and index["frozen"] is None and index["phase"] == "pscan00"), \
        f"{code} {code_d} {code_u} {code_r} {reasons}"


@case
def a_stale_freeze_is_lifted_by_render_and_logged():
    """GUARD. A freeze the pack no longer matches locks nothing the copy
    would accept: render lifts it, says why in the log, and renders the new
    name."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack, _code, _out, _err = frozen(tmp)
        rename_lotus(pack)
        code, _o, err = run("render", wd)
        index, _v, _ = index_of(tmp)
    lifted = [e for e in index["log"] if "lifted" in e["change"]]
    return (code == 0 and index["frozen"] is None and lifted
            and "pack changed" in lifted[0]["reason"]
            and "Momo" in folders_of(index)["F001"]["rendered"]), f"{err!r} {lifted}"


@case
def freeze_refuses_an_earlier_copy_that_went_elsewhere():
    """GUARD. photo_execute counts a file in its execute-state as done: one an
    earlier run copied elsewhere would never be copied into this folder."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = rendered(tmp)
        src = by_name(index_of(tmp)[0])["IMG_0101.jpg"]["source"]
        (wd / "plan").mkdir(exist_ok=True)
        (wd / "plan" / "execute-state_P1.json").write_text(json.dumps(
            {"plan": 1, "verified": {src: {"dest": "/elsewhere/IMG_0101.jpg",
                                           "sha256": "x"}}}))
        code, _o, err = run("freeze", wd)
    return code != 0 and "earlier run" in err, err


# ---- Card 6 F-mm / F-bb — a later pack write does not fail a good copy -------

def copied_and_frozen(tmp):
    """Freeze, then record every copy row as copied with its frozen SHA."""
    wd, pack, code, _o, err = frozen(tmp)
    assert code == 0, err
    sha = {f["source"]: f.get("sha256") for f in index_of(tmp)[0]["files"]}
    verified = {r["SourceFile"]: {"dest": "/d/" + r["FileName"],
                                  "sha256": sha[r["SourceFile"]], "status": "copied"}
                for f in sorted((wd / "plan").glob("plan_*-files.csv"))
                for r in csv_rows(wd, f.relative_to(wd)) if r["action"] == "copy"}
    assert verified
    (wd / "plan" / "execute-state_P1.json").write_text(json.dumps(
        {"plan": 1, "verified": verified}))
    return wd, pack


@case
def a_pack_change_after_a_good_copy_is_exit_6_not_4():
    """⭐ REPRODUCTION (UAT02-02 F-mm, UAT01-10 F-bb). ⛔ FAILS on c5b6f99:
    verify --copied exited 4 before the copy check ran, so a later dump's
    onboarding (or the end-of-dump page) failed every earlier dump's copy."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = copied_and_frozen(tmp)
        before = run("verify", wd, "--copied")[0]
        rename_lotus(pack)
        code, out, _e = run("verify", wd, "--copied")
    return (before == 0 and code == 6 and "copy check:" in out
            and "drive is fine" in out), f"before={before} code={code} out={out[-400:]!r}"


@case
def a_pack_change_still_stops_the_copy_gate():
    """GUARD — plain verify (what photo_run asks before copying) still exits
    4 when the pack moved: nothing new is copied under a stale freeze."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = copied_and_frozen(tmp)
        rename_lotus(pack)
        code = run("verify", wd)[0]
    return code == 4, f"code={code}"


@case
def a_copy_mismatch_beats_a_pack_change():
    """GUARD — a changed file is exit 1, pack moved or not."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = copied_and_frozen(tmp)
        state = wd / "plan" / "execute-state_P1.json"
        body = json.loads(state.read_text())
        first = next(iter(body["verified"]))
        body["verified"][first]["sha256"] = "0" * 64
        state.write_text(json.dumps(body))
        rename_lotus(pack)
        code, out, _e = run("verify", wd, "--copied")
    return code == 1 and "changed since the freeze" in out, f"code={code} out={out[-300:]!r}"


@case
def a_stale_freeze_that_is_not_the_pack_is_still_4():
    """GUARD — an exported plan file gone is a real stale freeze: 4, even with
    --copied."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = copied_and_frozen(tmp)
        (wd / index_of(tmp)[0]["frozen"]["files"][0]).unlink()
        code = run("verify", wd, "--copied")[0]
    return code == 4, f"code={code}"


# ---- FIX8 F8-2 — a folder renamed after its copy is locked, never re-copied --

OLD_NAME = "20241101_Ford_an older name"


def copied_under_an_old_name(tmp, how="collection", old=OLD_NAME, split=False):
    """Freeze, pretend photo_execute copied P1 into `old` (a sibling of the
    frozen folder), unfreeze. With `split` the first file went to `old` and the
    rest to a second old folder, so the frozen folder is a MERGE of two.
    -> (work dir, pack dir, the route's extra args, dest_root)."""
    wd, pack = g3_dump(tmp, bind=how == "collection")
    extra = []
    if how == "env":
        os.environ[photo_profile.ENV_VAR] = str(pack / photo_profile.PROFILE_NAME)
    if how == "profile":
        extra = ["--profile", pack / photo_profile.PROFILE_NAME]
    for cmd in ("init", "render", "freeze"):
        code, _o, err = run(cmd, wd, *extra)
        assert code == 0, (cmd, err)
    plans = json.loads((wd / "plans.json").read_text())
    root = Path(plans["dest_root"])
    assert Path(plans["plans"][0]["dest"]["path"]).parent == root
    folder = plans["plans"][0]["dest"]["path"]
    rows = [r for r in csv_rows(wd, "plan/plan_P1-files.csv")
            if r["action"] == "copy" and r["destination"] == folder]
    verified = {}
    for k, r in enumerate(rows):
        folder = old if not (split and k) else old + " too"
        verified[r["SourceFile"]] = {"dest": str(root / folder / r["FileName"]),
                                     "sha256": "x", "status": "copied"}
    (wd / "plan" / "execute-state_P1.json").write_text(json.dumps(
        {"plan": 1, "verified": verified}))
    assert run("unfreeze", wd, *extra, "--reason", "a name was corrected")[0] == 0
    return wd, pack, extra, root


def plan_bytes(wd):
    return {str(p.relative_to(wd)): p.read_bytes()
            for p in [wd / "plans.json", *sorted((wd / "plan").glob("*"))]
            if p.is_file()}


@case
def a_folder_renamed_after_its_copy_is_locked_with_a_rename_list():
    """⭐ REPRODUCTION (UAT01-8 F7). ⛔ FAILS on 99ca388: freeze exit 1, "copied
    by an earlier run to a place this freeze does not name". Owner decision
    "lock it, list renames": the freeze holds, prints old -> new, keeps the
    list in plans.json and plan/folder-renames.md, and verify --copied says
    the rename is still to do until the old folder is gone."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack, _x, root = copied_under_an_old_name(tmp)
        code, out, err = run("freeze", wd)
        plans = json.loads((wd / "plans.json").read_text())
        md = (wd / "plan" / "folder-renames.md").is_file()
        (root / OLD_NAME).mkdir(parents=True)
        _c, still, _e = run("verify", wd, "--copied")
        (root / OLD_NAME).rename(root / "20241101_Ford_Lotus_sofa nap")
        _c, after, _e = run("verify", wd, "--copied")
    want = {"old": OLD_NAME, "new": "20241101_Ford_Lotus_sofa nap"}
    line = f'"{OLD_NAME}" -> "20241101_Ford_Lotus_sofa nap"'
    return (code == 0 and plans.get("renames") == [want] and line in out
            and md and "still to do" in still and line in still
            and "still to do" not in after), \
        f"code={code} renames={plans.get('renames')} out={out[-300:]!r} err={err[-300:]!r} still={still[-200:]!r}"


@case
def a_folder_merged_after_its_copy_is_refused_and_writes_nothing():
    """GUARD (owner ruling D4). Two copied folders now one: not a rename. The
    refusal names both old folders, the new one and the files, and plans.json
    and plan/ are byte-identical — on 99ca388 a refused freeze had already
    rewritten them."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack, _x, _root = copied_under_an_old_name(tmp, split=True)
        before = plan_bytes(wd)
        code, _out, err = run("freeze", wd)
        after = plan_bytes(wd)
    return (code != 0 and "split or merged" in err and OLD_NAME in err
            and OLD_NAME + " too" in err and "IMG_0101.jpg" in err
            and before == after), f"code={code} same={before == after} err={err[-400:]!r}"


# ---- H-D (K25) — two pets keep ONE order: the order they were first named --

def two_pet_dump(tmp, day1, day2=("subj-0001", "subj-0002")):
    """g3_dump with two CONFIRMED pets — Lotus = subj-0001 and Birk = subj-0002,
    so name order and id order disagree. `day1` is the subjects on IMG_0101
    and on IMG_0102 (two tuples); `day2` the subjects on IMG_0201."""
    wd, pack = g3_dump(tmp)
    reg = pack / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text(encoding="utf-8"))
    data["subjects"] = [subject("subj-0001", "Lotus"),
                        subject("subj-0002", "Birk", "dog")]
    reg.write_text(json.dumps(data), encoding="utf-8")
    base = Path(tmp).resolve() / "raw" / "dump-a"

    def ids(sids):
        return [{"subject_id": s} for s in sids]
    write_see(wd, 1, [see_label(base, "IMG_0101.jpg", ids(day1[0]), "sofa nap"),
                      see_label(base, "IMG_0102.jpg", ids(day1[1]), "sofa nap"),
                      see_label(base, WORD, what="a document")])
    write_see(wd, 2, [see_label(base, "IMG_0201.jpg", ids(day2), "harbour walk"),
                      see_label(base, SHOT, what="a chat")])
    return wd, pack


LOTUS_FIRST = (("subj-0001", "subj-0002"), ("subj-0001",))   # Lotus 2, Birk 1
BIRK_MORE = (("subj-0001", "subj-0002"), ("subj-0002",))     # Birk 2, Lotus 1


@case
def two_pets_keep_one_order_in_every_folder():
    """⭐ REPRODUCTION (H-D, K25). ⛔ FAILS on 8743143: [who] went most files
    first, then by name, so the order followed each folder's counts — Lotus
    led one folder and Birk the next. Owner ruling 20261003/04: the order the
    pets were first named (registry mint order), in every folder."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = two_pet_dump(tmp, LOTUS_FIRST)
        run("init", wd)
        code, _out, err = run("render", wd)
        f = folders_of(index_of(tmp)[0])
    return (code == 0 and f["F001"]["rendered"] == "20241101_Ford_Lotus+Birk_sofa nap"
            and f["F002"]["rendered"] == "20241102_Harbour_Lotus+Birk_harbour walk"), \
        f"code={code} {f['F001']['rendered']!r} {f['F002']['rendered']!r} {err[-200:]!r}"


@case
def the_pet_with_more_photos_does_not_move_ahead():
    """REPRODUCTION (H-D). ⛔ FAILS on 8743143 (Birk+Lotus): the count no
    longer sets the order; Lotus was named first and stays first."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = two_pet_dump(tmp, BIRK_MORE)
        run("init", wd)
        run("render", wd)
        f1 = folders_of(index_of(tmp)[0])["F001"]
    return (f1["rendered"] == "20241101_Ford_Lotus+Birk_sofa nap"
            and [w["files"] for w in f1["validation"]["who"]] == [1, 2]), \
        f"{f1['rendered']!r} {f1['validation']['who']}"


def copied_two_pets(tmp, prior, old_name):
    """Init, render, freeze; pretend P1 was copied into `old_name` with its
    earlier [who] keys `prior` (None = no who field at all, an older index);
    unfreeze, render again and freeze again. -> (render code, freeze code,
    freeze output, plans.json, folders, folder-renames.md exists)."""
    wd, _pack = two_pet_dump(tmp, LOTUS_FIRST, day2=("subj-0001", "subj-0002"))
    for cmd in ("init", "render", "freeze"):
        code, _o, err = run(cmd, wd)
        assert code == 0, (cmd, err)
    plans = json.loads((wd / "plans.json").read_text())
    root = Path(plans["dest_root"])
    folder = [p for p in plans["plans"] if "Ford" in p["dest"]["path"]][0]
    rows = [r for r in csv_rows(wd, f"plan/plan_P{folder['plan']}-files.csv")
            if r["action"] == "copy" and r["destination"] == folder["dest"]["path"]]
    (wd / "plan" / "execute-state_P1.json").write_text(json.dumps(
        {"plan": 1, "verified": {r["SourceFile"]: {
            "dest": str(root / old_name / r["FileName"]), "sha256": "x",
            "status": "copied"} for r in rows}}))
    assert run("unfreeze", wd, "--reason", "a later render")[0] == 0
    index, _v, target = index_of(tmp)
    for fo in index["folders"]:
        if fo["id"] in ("F001", "F002") and prior is None:
            fo.get("validation", {}).pop("who", None)
        elif fo["id"] in ("F001", "F002"):
            fo["validation"]["who"] = [{"subject_id": k, "name": "x", "files": 1}
                                       for k in prior]
    (target / "index.json").write_text(json.dumps(index))
    rcode, _o, rerr = run("render", wd)
    fcode, fout, ferr = run("freeze", wd)
    return (rcode, fcode, fout + ferr + rerr,
            json.loads((wd / "plans.json").read_text()),
            folders_of(index_of(tmp)[0]),
            (wd / "plan" / "folder-renames.md").is_file())


@case
def a_copied_folder_keeps_its_who_order_and_lists_no_rename():
    """⭐ REPRODUCTION (H-D, owner 20261004 "new folders only"). ⛔ FAILS on
    8743143: a folder copied as `Birk+Lotus` re-rendered by count as
    `Lotus+Birk` and the re-lock listed a rename for the order alone. A copied
    folder keeps its earlier order — no plans.json `renames`, no
    plan/folder-renames.md — while F002, never copied, takes the id order."""
    old = "20241101_Ford_Birk+Lotus_sofa nap"
    with tempfile.TemporaryDirectory() as tmp, no_env():
        rcode, fcode, said, plans, f, md = copied_two_pets(
            tmp, ["subj-0002", "subj-0001"], old)
    return (rcode == 0 and fcode == 0 and f["F001"]["rendered"] == old
            and not plans.get("renames") and not md
            and f["F002"]["rendered"] == "20241102_Harbour_Lotus+Birk_harbour walk"), \
        f"r={rcode} f={fcode} {f['F001']['rendered']!r} {f['F002']['rendered']!r} renames={plans.get('renames')} md={md} {said[-300:]!r}"


@case
def a_copied_folder_with_no_earlier_who_falls_back_to_the_id_order():
    """GUARD. An index whose copied folder has no `who` field (rendered before
    it existed, or edited by hand) does not crash: it takes the id order. If
    the copy carried another order, that is a real rename and is listed."""
    old = "20241101_Ford_Birk+Lotus_sofa nap"
    with tempfile.TemporaryDirectory() as tmp, no_env():
        rcode, fcode, said, plans, f, md = copied_two_pets(tmp, None, old)
    return (rcode == 0 and fcode == 0
            and f["F001"]["rendered"] == "20241101_Ford_Lotus+Birk_sofa nap"
            and plans.get("renames") == [{"old": old,
                                          "new": "20241101_Ford_Lotus+Birk_sofa nap"}]
            and md), \
        f"r={rcode} f={fcode} {f['F001']['rendered']!r} renames={plans.get('renames')} {said[-300:]!r}"


@case
def who_order_is_mint_order_then_names_and_keeps_a_copied_order():
    """GUARD (H-D). Ids compare as numbers (`subj-10000` after `subj-9999`);
    a subject with no id has no mint time and goes after every id, by name; a
    copied folder's kept keys come first and a newly backed pet follows them
    in id order; a kept key no longer backed is dropped, never invented."""
    seen = photo_evidence.VIEWED
    cells = {"a": {photo_plan.WHO_SUBJECTS: [
        {"subject_id": sid, "name": n, "confirmed": True, "provenance": seen}
        for sid, n in (("subj-10000", "Birk"), ("subj-9999", "Lotus"),
                       (None, "Moss"), ("subj-0003", "Fern"))]}}
    members = [{"source": "a"}]
    plain = [b[0] for b in photo_index.backed_subjects(members, cells)]
    kept = [b[0] for b in photo_index.backed_subjects(
        members, cells, keep=["subj-10000", "subj-0042", "subj-9999"])]
    return (plain == ["subj-0003", "subj-9999", "subj-10000", "Moss"]
            and kept == ["subj-10000", "subj-9999", "subj-0003", "Moss"]), \
        f"plain={plain} kept={kept}"


@case
def a_refusal_after_the_plan_files_are_written_puts_them_back():
    """GUARD. A refusal from photo_plan or the export comparison comes after
    plans.json is written; the freeze's own outputs are restored exactly."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack, _x, _root = copied_under_an_old_name(tmp)
        before = plan_bytes(wd)
        real = photo_index.compare_exports

        def refuse(*a, **k):
            (wd / "plan" / "plan_P9-files.csv").write_text("stray")
            raise photo_index.Refused("the export disagrees (test)")
        photo_index.compare_exports = refuse
        try:
            code, _out, err = run("freeze", wd)
        finally:
            photo_index.compare_exports = real
        after = plan_bytes(wd)
    return code != 0 and before == after, \
        f"code={code} changed={sorted(set(before) ^ set(after)) or [k for k in before if before[k] != after.get(k)]}"


@case
def the_rename_list_is_one_line_per_highest_changed_folder():
    """GUARD on the unit. A renamed trip is ONE line, not one per leg; a leg
    renamed inside a renamed trip follows it under the NEW trip name; a folder
    whose files now sit in two folders is refused, and so is a folder that now
    holds the files of two."""
    root = "/d"
    def state(tmp, rows):
        (Path(tmp) / "plan").mkdir(exist_ok=True)
        (Path(tmp) / "plan" / "execute-state_P1.json").write_text(json.dumps(
            {"plan": 1, "verified": {s: {"dest": d} for s, d in rows.items()}}))
    with tempfile.TemporaryDirectory() as tmp:
        state(tmp, {"/s/1": "/d/Trip/Leg A/1.jpg", "/s/2": "/d/Trip/Leg B/2.jpg"})
        one = photo_index.earlier_copies_elsewhere(Path(tmp), {
            "/s/1": ("copy", "/d/Trip 2/Leg A", "1.jpg"),
            "/s/2": ("copy", "/d/Trip 2/Leg B", "2.jpg")}, root)
        two = photo_index.earlier_copies_elsewhere(Path(tmp), {
            "/s/1": ("copy", "/d/Trip 2/Leg A2", "1.jpg"),
            "/s/2": ("copy", "/d/Trip 2/Leg B", "2.jpg")}, root)
        split = photo_index.earlier_copies_elsewhere(Path(tmp), {
            "/s/1": ("copy", "/d/Trip/Leg A", "1.jpg"),
            "/s/2": ("copy", "/d/Trip/Leg A", "2.jpg")}, root)
        state(tmp, {"/s/1": "/d/Day/1.jpg", "/s/2": "/d/Day/2.jpg"})
        apart = photo_index.earlier_copies_elsewhere(Path(tmp), {
            "/s/1": ("copy", "/d/Day A", "1.jpg"),
            "/s/2": ("copy", "/d/Day B", "2.jpg")}, root)
        state(tmp, {"/s/1": "/d/Trip/Leg A/1.jpg", "/s/2": "/d/Trip/Leg B/2.jpg"})
        same = photo_index.earlier_copies_elsewhere(Path(tmp), {
            "/s/1": ("copy", "/d/Trip/Leg A", "1.jpg"),
            "/s/2": ("copy", "/d/Trip/Leg B", "2.jpg")}, root)
    got = (one, two, split[0], [r[0] for r in split[1]],
           apart[0], [(r[0], r[1]) for r in apart[1]], same)
    ok = (one == ([{"old": "Trip", "new": "Trip 2"}], [])
          and two == ([{"old": "Trip", "new": "Trip 2"},
                       {"old": "Trip 2/Leg A", "new": "Trip 2/Leg A2"}], [])
          and split[0] == [] and [r[0] for r in split[1]] == ["Trip/Leg A", "Trip/Leg B"]
          and apart[0] == [] and [(r[0], r[1]) for r in apart[1]] == [("Day", ["Day A", "Day B"])]
          and same == ([], []))
    return ok, f"{got}"


def lock_route_case(how):
    """LL-PHO-132: the rename lock through ONE pack route."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack, extra, _root = copied_under_an_old_name(tmp, how=how)
        code, out, err = run("freeze", wd, *extra)
    return code == 0 and f'"{OLD_NAME}" -> ' in out, f"code={code} err={err[-300:]!r}"


@case
def lock_route_collection_json():
    return lock_route_case("collection")


@case
def lock_route_env_var():
    return lock_route_case("env")


@case
def lock_route_explicit_profile():
    return lock_route_case("profile")


def route_case(how):
    """LL-PHO-132: render → check → freeze through ONE pack route, and the
    freeze records THAT pack's id."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = g3_dump(tmp, bind=how == "collection")
        extra = []
        if how == "env":
            os.environ[photo_profile.ENV_VAR] = str(pack / photo_profile.PROFILE_NAME)
        if how == "profile":
            extra = ["--profile", pack / photo_profile.PROFILE_NAME]
        codes = [run(cmd, wd, *extra)[0]
                 for cmd in ("init", "render", "check", "freeze")]
        index, _v, _ = index_of(tmp)
        pid = photo_profile.resolve_pack(
            explicit=pack / photo_profile.PROFILE_NAME).snapshot()["id"]
    name = folders_of(index)["F001"]["rendered"]
    return (codes == [0, 0, 0, 0] and (index["frozen"] or {}).get(
        "pack_fingerprint") == pid and "Lotus" in (name or "")), \
        f"codes={codes} name={name}"


@case
def route_collection_json_renders_and_freezes():
    return route_case("collection")


@case
def route_env_var_renders_and_freezes():
    return route_case("env")


@case
def route_explicit_profile_renders_and_freezes():
    return route_case("profile")


# ---------------------------------------------------------------------------
# FIX8 F8-7 — U6-28, a folder is named from photos taken at its own place
# ---------------------------------------------------------------------------

HOME_SHOT, SECOND_HOME_SHOT, NOGPS_SHOT = "IMG_0202.jpg", "IMG_0204.jpg", "IMG_0203.jpg"


def outing_with_a_home_photo(root, bind=True, nogps=False):
    """g3_dump, plus a photo on the Harbour day taken AT HOME that holds the
    confirmed cat and describes the sofa, twice, so the sofa outnumbers the
    outing — the U6-28 shape. With `nogps` the
    cat photo carries no GPS instead. -> (work dir, pack dir)."""
    wd, pack = g3_dump(root, bind=bind)
    base = Path(root).resolve() / "raw" / "dump-a"
    names = [NOGPS_SHOT] if nogps else [HOME_SHOT, SECOND_HOME_SHOT]
    doc_path = wd / "classify" / "batch-02" / "see-labels.json"
    doc = json.loads(doc_path.read_text())
    for k, name in enumerate(names):
        extra = row(name, SourceFile=f"{base}/{name}",
                    when=f"2024:11:02 2{k}:00:00", gps=None if nogps else HOME)
        Path(extra["SourceFile"]).write_bytes(
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + name.encode() + b"\xff\xd9")
        with open(wd / "manifest.csv", "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writerow(extra)
        doc["labels"].append(see_label(base, name, [{"subject_id": "subj-0001"}],
                                       "sofa nap"))
    doc_path.write_text(json.dumps(doc))
    return wd, pack


@case
def a_home_photo_names_no_outing_folder():
    """⭐ REPRODUCTION (U6-28, UAT01-6). ⛔ FAILS on 99ca388: the one Lotus photo
    on the Harbour day were taken at home, and the Harbour folder took Lotus
    AND their sofa [what] from them (owner decision D1: both slots). Now that photo stays in the folder and names
    nothing there; the home folder still names Lotus from its own photo."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = outing_with_a_home_photo(tmp)
        run("init", wd)
        code, _o, err = run("render", wd)
        index, _v, _ = index_of(tmp)
    f = folders_of(index)
    kept = [x["folder"] for x in index["files"]
            if Path(x["source"]).name == HOME_SHOT]
    return (code == 0 and f["F002"]["rendered"] == "20241102_Harbour_harbour walk"
            and not f["F002"]["validation"]["who"]
            and f["F001"]["rendered"] == "20241101_Ford_Lotus_sofa nap"
            and kept == ["F002"]), \
        f"code={code} F001={f['F001']['rendered']} F002={f['F002']['rendered']} kept={kept} err={err[-200:]!r}"


@case
def a_photo_with_no_gps_still_names_its_folder():
    """GUARD (owner ruling D3). Where a photo with no GPS was taken is
    unknown, so it counts, as it always did."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = outing_with_a_home_photo(tmp, nogps=True)
        run("init", wd)
        code, _o, err = run("render", wd)
        index, _v, _ = index_of(tmp)
    f = folders_of(index)
    return (code == 0 and "Lotus" in (f["F002"]["rendered"] or "")), \
        f"code={code} F002={f['F002']['rendered']} err={err[-200:]!r}"


@case
def own_place_reads_the_parent_and_the_nearest_home():
    """GUARD on the unit. A leg with no place of its own uses its parent's; a
    photo at the SECOND home counts in that home's folder and in no other;
    an away photo counts everywhere; the nearest home wins."""
    near_home = (HOME[0] + 0.001, HOME[1])
    homes = [(HOME[0], HOME[1], None, None, "Ford", "home-01"),
             (FAR[0], FAR[1], None, None, "Sea", "home-02"),
             (near_home[0], near_home[1], None, None, "Twin", "home-03")]
    gps = {"/a": near_home, "/b": FAR, "/c": (40.0, 40.0), "/d": None, "/e": HOME}
    files = [{"source": s, "date": "2024-11-02T10:00:00"} for s in gps]
    pick = lambda fo, parent=None: sorted(
        x["source"] for x in photo_index.at_own_place(files, fo, parent, gps, homes))
    at_one = {"where": [{"ref": "home-01"}]}
    leg, trip = {"where": []}, {"where": [{"ref": "home-02"}]}
    got = (pick(at_one), pick(leg, trip), pick({"where": [{"ref": "map:Elsewhere"}]}),
           pick(at_one, None) == pick(at_one, trip))
    want = (["/c", "/d", "/e"], ["/b", "/c", "/d"], ["/c", "/d"], True)
    return got == want, f"{got} != {want}"


def own_place_route_case(how):
    """LL-PHO-132: the homes that decide [who] come from the pack — one case
    per route, each rendering the Harbour folder without the home photo's cat."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = outing_with_a_home_photo(tmp, bind=how == "collection")
        extra = []
        if how == "env":
            os.environ[photo_profile.ENV_VAR] = str(pack / photo_profile.PROFILE_NAME)
        if how == "profile":
            extra = ["--profile", pack / photo_profile.PROFILE_NAME]
        codes = [run(cmd, wd, *extra)[0] for cmd in ("init", "render")]
        index, _v, _ = index_of(tmp)
    name = folders_of(index)["F002"]["rendered"]
    return codes == [0, 0] and name == "20241102_Harbour_harbour walk", \
        f"codes={codes} name={name}"


@case
def own_place_route_collection_json():
    return own_place_route_case("collection")


@case
def own_place_route_env_var():
    return own_place_route_case("env")


@case
def own_place_route_explicit_profile():
    return own_place_route_case("profile")


# ---------------------------------------------------------------------------
# G4 — recut (D-I1) and relabel
# ---------------------------------------------------------------------------

FAR2 = (12.51234, 22.56789)
MAP_WORDS = {HOME: "Hometown District", FAR: "Harbourtown", FAR2: "Farview"}


def cut_rows():
    """Three days that cluster as three batches with or without a pack: day 1
    at the home, days 2-3 at the named place (a >30 km jump from day 1), and
    a day more than 30 days later somewhere else."""
    return [row("IMG_1001.jpg", when="2024:11:01 10:00:00", gps=HOME),
            row("IMG_1002.jpg", when="2024:11:01 11:00:00", gps=HOME),
            row("IMG_1003.jpg", when="2024:11:02 10:00:00", gps=FAR),
            row("IMG_1004.jpg", when="2024:11:03 10:00:00", gps=FAR),
            row("IMG_1005.jpg", when="2025:01:10 10:00:00", gps=FAR2)]


def seed_cache(root, names=MAP_WORDS):
    """The map words a geocoder once returned, so no case touches a network."""
    path = Path(root) / "Working Files" / "geocode-cache.json"
    geo = photo_cluster.Geocoder(path, enabled=False, language="en")
    path.write_text(json.dumps({geo.key_for(pt, 10): {"name": n, "name_tag": "name"}
                                for pt, n in names.items()}))


def no_pack_cut(wd):
    env = {k: v for k, v in os.environ.items() if k != photo_profile.ENV_VAR}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "photo_cluster.py"),
                        str(wd), "--force", "--no-geocode"],
                       capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(r.stderr[-300:])


def first_dump(tmp, bound=True, init=True):
    """UAT01-5's order: the dump is clustered with NO pack, then onboarding
    writes a pack with a labelled home (`home-01` Ford at HOME) and a named
    place (`fsl-0001` Harbour at FAR), then the index is initialised."""
    wd = make_dump(tmp, rows=cut_rows(), bind=False)
    seed_cache(tmp)
    no_pack_cut(wd)
    pack = make_pack(tmp)
    extra = []
    if bound:
        coll = json.loads((wd.parent / "collection.json").read_text())
        coll.update(owner=OWNER, memory_root=str(pack.parent))
        (wd.parent / "collection.json").write_text(json.dumps(coll))
    else:
        extra = ["--profile", pack / photo_profile.PROFILE_NAME]
    if init:
        code, _o, err = run("init", wd, *extra)
        if code:
            raise RuntimeError(err[-300:])
    return wd, pack


def where_of(index, fid):
    return [r["ref"] for r in folders_of(index)[fid]["where"]]


def backups(wd):
    return sorted(q.name for q in wd.iterdir() if q.name.startswith("batches.json.bak-"))


@case
def recut_puts_the_owners_label_on_a_first_dump():
    """⭐ THE U5-02 REPRODUCTION. ⛔ FAILS on 5cc7e1d: nothing re-cut a dump
    clustered before onboarding, so the home batch kept the map's district
    word and the index a `map:` ref. After `recut` the batch's place is the
    owner's label, the ref is `home-01`, and the rendered name carries it."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = first_dump(tmp)
        before = where_of(index_of(tmp)[0], "F001")
        code, out, err = run("recut", wd, "--no-geocode")
        batches = json.loads((wd / "batches.json").read_text())["batches"]
        run("render", wd, "--no-vision")
        index, view, _ = index_of(tmp)
        kept = backups(wd)
    return (before == ["map:Hometown District"] and code == 0
            and [b["place"] for b in batches] == ["Ford", "Harbour", "Farview"]
            and where_of(index, "F001") == ["home-01"]
            and where_of(index, "F002") == ["fsl-0001"]
            and folders_of(index)["F001"]["rendered"] == "20241101_Ford"
            and index["phase"] == "onb" and index["cluster_gen"] == 2
            and len(kept) == 1), f"code={code} err={err[-300:]!r} before={before}"


@case
def recut_dry_run_reports_and_writes_nothing():
    """⭐ REPRODUCTION (UAT02-02 F-s). ⛔ FAILS on c5b6f99: `recut` had no
    dry run — the owner saw the new cut only after it was written. The dry
    run reports the same summary and leaves batches.json, the index and
    no-date-files.csv byte for byte, with no backup made."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = first_dump(tmp)
        files = [wd / "batches.json", index_of(tmp)[2] / "index.json"]
        before = [p.read_bytes() for p in files]
        code, out, err = run("recut", wd, "--no-geocode", "--dry-run")
        after = [p.read_bytes() for p in files]
        kept = backups(wd)
    return (code == 0 and "DRY RUN" in out and "batches 3 → 3" in out
            and before == after and kept == []), \
        f"code={code} out={out[-400:]!r} err={err[-300:]!r} kept={kept}"


ARTEFACTS = [
    ("classify/batch-NN", lambda wd, tmp: (wd / "classify" / "batch-01").mkdir(parents=True)),
    ("dedupe_batch", lambda wd, tmp: ((wd / "plan").mkdir(exist_ok=True),
                                      (wd / "plan" / "dedupe_batch-01.json").write_text("{}"))),
    ("plan_P*", lambda wd, tmp: ((wd / "plan").mkdir(exist_ok=True),
                                 (wd / "plan" / "plan_P1-files.csv").write_text("x"))),
    ("execute-state", lambda wd, tmp: ((wd / "plan").mkdir(exist_ok=True),
                                       (wd / "plan" / "execute-state_P1.json").write_text("{}"))),
    ("plans.json", lambda wd, tmp: (wd / "plans.json").write_text("{}")),
    ("memory-review_C", lambda wd, tmp: (wd / "memory-review_C1.md").write_text("x")),
    ("P-B*.md", lambda wd, tmp: (wd / "P-B01.md").write_text("x")),
    ("past `pending`", lambda wd, tmp: edit_batches(wd, status="classified")),
    ("past `pending`", lambda wd, tmp: edit_batches(wd, type="a day out")),
    ("subject evidence", lambda wd, tmp: add_evidence(tmp, "dump-a")),
    ("phase", lambda wd, tmp: edit_index(tmp, lambda ix: ix.update(phase="B03"))),
]


def edit_batches(wd, **fields):
    data = json.loads((wd / "batches.json").read_text())
    data["batches"][0].update(fields)
    (wd / "batches.json").write_text(json.dumps(data))


def add_evidence(tmp, unit):
    reg = Path(tmp) / "photo-memory" / OWNER / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text(encoding="utf-8"))
    data["subjects"] = [dict(subject("subj-0001", "Lotus"),
                             evidence=[{"batch": 1, "unit": unit, "files": 1}])]
    reg.write_text(json.dumps(data), encoding="utf-8")


@case
def recut_refuses_on_every_per_batch_artefact_and_names_it():
    """REPRODUCTION (R2). ⛔ FAILS on 5cc7e1d (no recut at all). A re-cut
    renumbers batches, so anything keyed by a batch number refuses it — each
    kind named with its count — and nothing is written: not batches.json, not
    a backup, not the index. Evidence from ANOTHER dump does not block."""
    bad = []
    for label, make in ARTEFACTS:
        with tempfile.TemporaryDirectory() as tmp, no_env():
            wd, _pack = first_dump(tmp)
            make(wd, tmp)
            b0, i0 = (wd / "batches.json").read_bytes(), index_of(tmp)[0]
            code, _out, err = run("recut", wd, "--no-geocode")
            if not (code != 0 and label in err and ": 1" in err
                    and (wd / "batches.json").read_bytes() == b0
                    and index_of(tmp)[0] == i0 and not backups(wd)):
                bad.append((label, code, err[-160:]))
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = first_dump(tmp)
        add_evidence(tmp, "another-dump")
        (wd / "status.json").write_text("{}")
        other = run("recut", wd, "--no-geocode")[0]
    return not bad and other == 0, f"bad={bad} other={other}"


@case
def recut_keeps_file_ids_and_never_reuses_a_folder_id():
    """REPRODUCTION (R5). ⛔ FAILS on 5cc7e1d: the only way to a new cut was
    init, which renumbers folders from F001 (measured on a real dump: 52 of
    52 surviving ids then held different files). A folder whose files are
    unchanged keeps its id; any other is retired and a new id is issued
    (max + 1), with split_from / merged_into where one-to-one; each moved file
    gets a history entry and a log line."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = first_dump(tmp, init=False)
        data = json.loads((wd / "batches.json").read_text())
        spans = [("2024-11-01", "2024-11-02"), ("2024-11-03", "2024-11-03"),
                 ("2025-01-10", "2025-01-10")]
        for b, (lo, hi) in zip(data["batches"], spans):
            b.update({"from": lo, "to": hi})
        (wd / "batches.json").write_text(json.dumps(data))
        run("init", wd)
        before = index_of(tmp)[0]
        code, _out, err = run("recut", wd, "--no-geocode")
        index, view, _ = index_of(tmp)
    fo = folders_of(index)
    ids = {n: f["file_id"] for n, f in by_name(before).items()}
    after = by_name(index)
    liv = {x["id"] for x in index["folders"] if x["status"] != "retired"}
    moved = [e for e in index["log"] if e["cmd"] == "index recut" and "→" in e["change"]
             and e["change"].startswith("f-")]
    return (code == 0
            and {n: f["file_id"] for n, f in after.items()} == ids
            and all(f["folder"] in liv for f in index["files"])
            and liv == {"F003", "F004", "F005"}
            and fo["F001"]["status"] == fo["F002"]["status"] == "retired"
            and fo["F004"]["split_from"] == "F001"
            and fo["F002"]["merged_into"] == "F005" and not fo["F001"]["merged_into"]
            and after["IMG_1003.jpg"]["folder"] == "F005"
            and after["IMG_1003.jpg"]["history"][-1] == {
                "phase": "onb", "folder": "F005", "cluster_gen": 2, "by": "recut"}
            and after["IMG_1005.jpg"]["history"] == by_name(before)["IMG_1005.jpg"]["history"]
            and len(moved) == 4 and "Retired folders" in view), \
        f"code={code} err={err[-300:]!r} live={liv} moved={len(moved)}"


@case
def a_frozen_index_refuses_recut():
    """GUARD (D-I16). A freeze locks the folders; a re-cut would move files
    out of them. Refused before anything is looked at, nothing written."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack, _c, _o, _e = frozen(tmp)
        b0 = (wd / "batches.json").read_bytes()
        code, _out, err = run("recut", wd)
        same = (wd / "batches.json").read_bytes() == b0 and not backups(wd)
    return code != 0 and "frozen" in err and same, err


@case
def a_second_recut_keeps_the_first_backup():
    """REPRODUCTION (R3). ⛔ FAILS on 5cc7e1d: photo_cluster --force keeps ONE
    `batches.json.bak`, shared with photo_classify_set and photo_plan, so a
    second cut lost the first. Each recut writes its own stamped copy."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = first_dump(tmp)
        original = (wd / "batches.json").read_bytes()
        c1 = run("recut", wd, "--no-geocode")[0]
        c2 = run("recut", wd, "--no-geocode")[0]
        names = backups(wd)
        first = (wd / names[0]).read_bytes() if names else b""
        index = index_of(tmp)[0]
    return (c1 == c2 == 0 and len(names) == 2 and first == original
            and index["cluster_gen"] == 3), f"{c1} {c2} {names}"


class NetworkUsed(Exception):
    pass


@contextlib.contextmanager
def no_network():
    calls = []

    def refuse(*a, **k):
        calls.append(a[:1])
        raise NetworkUsed("network")

    saved = (socket.create_connection, photo_cluster.urllib.request.urlopen)
    socket.create_connection = refuse
    photo_cluster.urllib.request.urlopen = refuse
    try:
        yield calls
    finally:
        socket.create_connection, photo_cluster.urllib.request.urlopen = saved


@case
def relabel_after_vision_puts_the_owners_label_on_the_folder():
    """⭐ U5-02 THROUGH RELABEL (R4). ⛔ FAILS on 5cc7e1d. With see-labels
    present recut refuses; relabel — a dry run by default — then puts the
    owner's labels on the refs with --go, logs each folder with its reason,
    never touches batches.json, and asks the network NOTHING: the day the
    cache cannot answer keeps its ref, and an enabled geocoder would have
    tried to look it up."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = first_dump(tmp)
        write_see(wd, 1, [])
        seed_cache(tmp, {HOME: "Hometown District", FAR: "Harbourtown"})
        b0 = (wd / "batches.json").read_bytes()
        refused = run("recut", wd)
        i0 = index_of(tmp)[0]
        with no_network() as calls:
            dry = run("relabel", wd)
            unchanged = index_of(tmp)[0] == i0
            go = run("relabel", wd, "--go", "--reason", "onboarding labels")
        run("render", wd, "--no-vision")
        index, _view, _ = index_of(tmp)
        same_batches = (wd / "batches.json").read_bytes() == b0
    logged = [e for e in index["log"] if e["cmd"] == "index relabel"]
    return (refused[0] != 0 and "classify/batch-NN" in refused[2]
            and dry[0] == 0 and "DRY RUN" in dry[1] and unchanged
            and go[0] == 0 and calls == []
            and "1 kept their refs (1 day(s)" in go[1]
            and where_of(index, "F001") == ["home-01"]
            and where_of(index, "F002") == ["fsl-0001"]
            and where_of(index, "F003") == ["map:Farview"]
            and index["places"]["home-01"].get("label_from") == "relabel"
            and folders_of(index)["F001"]["rendered"] == "20241101_Ford"
            and len(logged) == 2 and logged[0]["reason"] == "onboarding labels"
            and same_batches and index["cluster_gen"] == 1), \
        f"calls={calls} dry={dry[1][-200:]!r} go={go[1][-300:]!r} {go[2][-200:]!r}"


@case
def relabel_is_a_function_g6_can_call():
    """GUARD. G6 calls it after an SNL answer, in-process."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = first_dump(tmp)
        pack = photo_profile.resolve_pack(workdir=wd)
        _p, target, index = photo_index.load(wd, None)
        result = photo_index.relabel(wd, pack, target, index, go=False)
    return ([c[0] for c in result["changed"]] == ["F001", "F002"]
            and result["written"] is False), f"{result}"


@case
def relabel_refuses_on_a_freeze_that_holds():
    """GUARD (D-I16)."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack, _c, _o, _e = frozen(tmp)
        i0 = index_of(tmp)[0]
        code, _out, err = run("relabel", wd, "--go")
        same = index_of(tmp)[0] == i0
    return code != 0 and "frozen" in err and same, err


@case
def recut_and_relabel_write_no_coordinate():
    """GUARD with a positive control. The day centroids relabel reads are
    never stored: no coordinate — whole, or at 2 or 1 dp — in index.json, the
    view or the log, after a recut and a relabel. The control proves the
    detector would have fired."""
    needles = []
    for lat, lon in (HOME, FAR, FAR2):
        needles += [str(lat), str(lon), f"{lat:.2f}", f"{lon:.2f}"]

    def leaks(text):
        return [n for n in needles if n in text]

    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, _pack = first_dump(tmp)
        run("recut", wd, "--no-geocode")
        run("relabel", wd, "--go")
        run("render", wd, "--no-vision")
        _index, view, target = index_of(tmp)
        raw = (target / "index.json").read_text(encoding="utf-8")
    control = leaks(f"somewhere near {HOME[0]:.2f}")
    return not leaks(raw + view) and control, f"leaks={leaks(raw + view)} control={control}"


def g4_route(how, cmd):
    """LL-PHO-132: one pack route, end to end."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd, pack = first_dump(tmp, bound=how == "collection", init=False)
        extra = []
        if how == "env":
            os.environ[photo_profile.ENV_VAR] = str(pack / photo_profile.PROFILE_NAME)
        if how == "profile":
            extra = ["--profile", pack / photo_profile.PROFILE_NAME]
        c0 = run("init", wd, *extra)[0]
        if cmd == "recut":
            code, out, err = run("recut", wd, "--no-geocode", *extra)
        else:
            code, out, err = run("relabel", wd, "--go", *extra)
        index = index_of(tmp)[0]
    return (c0 == 0 and code == 0 and where_of(index, "F001") == ["home-01"]), \
        f"code={code} err={err[-200:]!r}"


@case
def route_collection_json_recuts():
    return g4_route("collection", "recut")


@case
def route_env_var_recuts():
    return g4_route("env", "recut")


@case
def route_explicit_profile_recuts():
    return g4_route("profile", "recut")


@case
def route_collection_json_relabels():
    return g4_route("collection", "relabel")


@case
def route_env_var_relabels():
    return g4_route("env", "relabel")


@case
def route_explicit_profile_relabels():
    return g4_route("profile", "relabel")


@case
def no_pack_recut_and_relabel_write_nothing():
    """GUARD. With no pack: one line each, exit 0, nothing written."""
    with tempfile.TemporaryDirectory() as tmp, no_env():
        wd = make_dump(tmp, rows=cut_rows(), bind=False)
        seed_cache(tmp)
        no_pack_cut(wd)
        before = tree_state(tmp)
        r1, r2 = run("recut", wd, "--no-geocode"), run("relabel", wd, "--go")
        after = tree_state(tmp)
    return (r1[0] == r2[0] == 0 and before == after
            and all(r[1].count("\n") == 1 and "no owner pack" in r[1] for r in (r1, r2))), \
        f"{r1} {r2}"


# ---------------------------------------------------------------------------
# the one date resolver is unchanged
# ---------------------------------------------------------------------------

def parse_date_before(row):
    """photo_cluster.parse_date as it stood at 2acaf5a, pinned verbatim."""
    for tag in ("CreateDateLocal", "DateTimeOriginal", "CreateDate"):
        v = row.get(tag, "-")
        if v not in ("-", "", "0000:00:00 00:00:00"):
            try:
                return datetime.strptime(v[:19], "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue
    return None


@case
def parse_date_is_unchanged_on_every_golden_manifest():
    """GUARD. The split adds `parse_date_source()`; `parse_date()` must return
    exactly what it did, row for row, on every golden fixture.

    The fixture root comes from the replay harness's ONE resolver. It SKIPS
    only when that root holds no manifest at all; a root with some manifests
    and too few rows still fails on `seen`."""
    root = golden_replay.fixture_root()
    paths = [p for p in sorted(root.glob("*/input/*.csv"))
             if p.name in ("manifest.csv", "no-date-files.csv")]
    if not paths:
        raise Skipped(f"no golden manifest under {root} — point "
                      f"${golden_replay.ENV_FIXTURES} at a fixture set")
    seen, diff = 0, []
    for path in paths:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                seen += 1
                got = photo_cluster.parse_date(r)
                when, _tag = photo_cluster.parse_date_source(r)
                if got != parse_date_before(r) or when != got:
                    diff.append(r.get("SourceFile"))
    return seen > 10000 and not diff, f"seen={seen}, diff={diff[:3]}"


@contextlib.contextmanager
def cwd(path):
    import os
    before = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


def bare_name_case(route):
    """U5-10 (G8): from the workspace folder, `init` and `view` take the bare
    dump name, resolved by photo_run's own resolver. ONE pack route each
    (A42 / LL-PHO-132)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp, no_env():
        root = Path(tmp).resolve()
        wd = make_dump(root, bind=route == "collection")
        pack = make_pack(root)
        extra = []
        if route == "env":
            os.environ[photo_profile.ENV_VAR] = str(pack / photo_profile.PROFILE_NAME)
        elif route == "profile":
            extra = ["--profile", str(pack / photo_profile.PROFILE_NAME)]
        with cwd(root):
            code, out, err = run("init", "dump-a", *extra)
            vcode, _vout, verr = run("view", "dump-a", *extra)
        ok = (code == 0 and vcode == 0 and (wd / "index-pointer.json").exists()
              and not (root / "dump-a").exists())
        return ok, f"init={code} view={vcode} {(err + verr)[-200:]}"


@case
def a_bare_dump_name_resolves_route_collection_json():
    """⛔ REPRODUCTION: at 8c192c1 the name resolved under the cwd and found no
    batches.json."""
    return bare_name_case("collection")


@case
def a_bare_dump_name_resolves_route_env_var():
    """REPRODUCTION (the PHOTO_PROFILE route)."""
    return bare_name_case("env")


@case
def a_bare_dump_name_resolves_route_explicit_profile():
    """REPRODUCTION (the --profile route)."""
    return bare_name_case("profile")


@case
def a_full_work_dir_path_is_unchanged_from_any_cwd():
    """GUARD: a path with a separator is used as typed, from a cwd that is not
    the workspace."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other, no_env():
        wd = make_dump(Path(tmp).resolve())
        with cwd(other):
            code, _out, err = run("init", wd)
        return code == 0 and (wd / "index-pointer.json").exists(), err[-200:]


@case
def a_bare_dump_name_outside_the_workspace_is_refused_and_writes_nothing():
    """GUARD: from a folder with no collection.json the resolver refuses, as
    `photo_run.py` does, and nothing is created under that folder."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other, no_env():
        wd = make_dump(Path(tmp).resolve())
        with cwd(other):
            code, _out, err = run("init", "dump-a")
        return (code != 0 and "collection.json" in err and not any(Path(other).iterdir())
                and not (wd / "index-pointer.json").exists()), f"code={code} {err[-200:]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    failures, skipped = [], []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
        try:
            ok, detail = fn()
        except Skipped as why:
            skipped.append(fn.__name__)
            print(f"  skip  {fn.__name__.replace('_', ' ').ljust(width)}   {why}")
            continue
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  "
                  f"{fn.__name__.replace('_', ' ').ljust(width)}"
                  + (f"   {detail}" if not ok else ""))

    ran = len(CASES) - len(skipped)
    print(f"\n{ran - len(failures)}/{ran} photo_index cases passed"
          + (f", {len(skipped)} skipped" if skipped else "")
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
