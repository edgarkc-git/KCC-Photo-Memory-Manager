#!/usr/bin/env python3
"""D-I15 cases — every home and every named place carries a fixed id.

Wave 3's index refers to a place by an id, never by a coordinate and never by
a label the owner can rename. These cases hold the id's whole life in one
place: `apply --write-pack` writes it, `backfill-ids` gives one to a pack
written before ids existed, and the ONE reader of each list exposes it —
`labelled_home_points()` (6th element) and `named_places()` (4th). The privacy
callers' `home_points()` never sees it.

  python3 tests/place_id_cases.py [-v]

Exit 0 = pass. Every pack is a copy of the shipped template in a temp dir with
invented labels and coordinates; no owner's pack is read.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pack_state  # noqa: E402
import photo_onboard_page as op  # noqa: E402
import photo_profile  # noqa: E402

TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"
COORDS = ("home rows — coordinates, kept off the page.\n\n"
          "A  10.5, 20.25  40 day(s), 9 after dark, 90 file(s)  [u]\n"
          "B  11.5, 21.25  8 day(s), 2 after dark, 12 file(s)  [u]\n"
          "C  12.5, 22.25  6 day(s), 1 after dark, 30 file(s)  [u]\n")
ANSWERS = ("language: en\nhome: A = Ford live\nhome: B = Bay visit\n"
           "home: C = Harbour Cafe\n")
NUMBERS = ("10.5", "20.25", "11.5", "21.25", "12.5", "22.25")

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def make_pack(root, name="pack"):
    pack = Path(root) / "photo-memory" / name
    shutil.copytree(TEMPLATE, pack)
    for path in list(pack.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", name)))
    for leaf in (photo_profile.PROFILE_NAME, photo_profile.ENTITIES_NAME):
        path = pack / leaf
        path.write_text(path.read_text(encoding="utf-8")
                        .replace("{{SLUG}}", name)
                        .replace("{{DISPLAY}}", name), encoding="utf-8")
    return pack


def edit(pack, leaf, **keys):
    path = Path(pack) / leaf
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(keys)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def load(pack, leaf):
    return json.loads((Path(pack) / leaf).read_text(encoding="utf-8"))


def op_main(*argv):
    """-> (exit code, stdout, stderr) of one `photo_onboard_page` command."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = op.main([str(a) for a in argv])
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue(), err.getvalue()


def written_pack(root):
    """A pack written the way onboarding writes one. -> pack dir."""
    pack = make_pack(root)
    answers = Path(root) / "answers.txt"
    answers.write_text(ANSWERS, encoding="utf-8")
    coords = Path(root) / "coords.txt"
    coords.write_text(COORDS, encoding="utf-8")
    code, out, _err = op_main("apply", answers, "--write-pack", pack,
                              "--coords-in", coords)
    assert code == 0, out
    return pack


def legacy_pack(root, homes, places=(), **marks):
    """A pack written before ids existed: rows as given, marks as given."""
    pack = make_pack(root)
    edit(pack, photo_profile.PROFILE_NAME, home_locations=list(homes),
         **{k: v for k, v in marks.items() if k.startswith("home")})
    edit(pack, photo_profile.ENTITIES_NAME, frequent_places=list(places),
         **{k: v for k, v in marks.items() if k.startswith("frequent")})
    return pack


def warnings_of(fn):
    """-> stderr from `fn()`, with the once-per-process memory cleared."""
    photo_profile._PLACE_ID_SAID.clear()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        fn()
    return err.getvalue()


HOME = {"label": "Ford", "lat": 10.5, "lon": 20.25}
VISIT = {"label": "Bay", "lat": 11.5, "lon": 21.25, "home_range": False}
PLACE = {"label": "Harbour Cafe", "lat": 12.5, "lon": 22.25}


# ---------------------------------------------------------------------------
# the writer — `apply --write-pack`
# ---------------------------------------------------------------------------

@case
def write_pack_gives_each_home_and_place_an_id():
    """REPRODUCTION. ⛔ FAILS on 25cf5f3: rows were written as
    {label, lat, lon} only, so an index had nothing but a coordinate or a
    renameable label to point at."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = written_pack(tmp)
        profile = load(pack, photo_profile.PROFILE_NAME)
        entities = load(pack, photo_profile.ENTITIES_NAME)
    homes = [h.get("id") for h in profile["home_locations"]]
    places = [p.get("id") for p in entities["frequent_places"]]
    return (homes == ["home-01", "home-02"] and places == ["fsl-0001"]
            and list(profile["home_locations"][0])[0] == "id"
            and profile.get("home_locations_next_id") == 3
            and entities.get("frequent_places_next_id") == 2), \
        f"homes={homes}, places={places}, marks=" \
        f"{profile.get('home_locations_next_id')}/" \
        f"{entities.get('frequent_places_next_id')}"


@case
def write_pack_numbers_after_the_mark():
    """GUARD — never reused. A pack whose owner deleted every home by hand
    still holds the mark, so its next home is numbered after it, not home-01
    again (an older dump's index may still point at home-01..03)."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = make_pack(tmp)
        edit(pack, photo_profile.PROFILE_NAME, home_locations=[],
             home_locations_next_id=4)
        answers = Path(tmp) / "answers.txt"
        answers.write_text("home: A = Ford live\n", encoding="utf-8")
        coords = Path(tmp) / "coords.txt"
        coords.write_text(COORDS, encoding="utf-8")
        code, out, _ = op_main("apply", answers, "--write-pack", pack,
                               "--coords-in", coords)
        profile = load(pack, photo_profile.PROFILE_NAME)
    ids = [h.get("id") for h in profile["home_locations"]]
    return (code == 0 and ids == ["home-04"]
            and profile["home_locations_next_id"] == 5), \
        f"code={code}, ids={ids}, out={out[-200:]!r}"


SECOND = ("home rows — coordinates, kept off the page.\n\n"
          "D  13.5, 23.25  6 day(s), 0 after dark, 20 file(s)  [u]\n"
          "E  12.5001, 22.2501  4 day(s), 0 after dark, 9 file(s)  [u]\n")


def second_answer(root, pack, answer):
    """A later answer on the same pack (G6: a page names one more place).
    -> (exit code, stdout)."""
    answers = Path(root) / "answers-2.txt"
    answers.write_text(answer, encoding="utf-8")
    coords = Path(root) / "coords-2.txt"
    coords.write_text(SECOND, encoding="utf-8")
    code, out, _err = op_main("apply", answers, "--write-pack", pack,
                              "--coords-in", coords)
    return code, out


@case
def a_second_place_is_appended_with_the_next_id():
    """⭐ REPRODUCTION (G6-2, the SNL case). ⛔ FAILS on 76cb997: a pack that
    already held one named place refused a second ("frequent_places already
    holds 1 entry(ies). Merge the new names by hand.") and wrote nothing. Now
    the row is appended as fsl-0002, fsl-0001 is untouched, the mark moves on,
    and the file is copied aside first."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = written_pack(tmp)
        before = load(pack, photo_profile.ENTITIES_NAME)["frequent_places"]
        code, out = second_answer(tmp, pack, "home: D = Mill Pond\n")
        ents = load(pack, photo_profile.ENTITIES_NAME)
        baks = [p.name for p in pack.iterdir() if ".bak-" in p.name]
    places = ents["frequent_places"]
    return (code == 0 and [p["id"] for p in places] == ["fsl-0001", "fsl-0002"]
            and places[0] == before[0] and places[1]["label"] == "Mill Pond"
            and ents["frequent_places_next_id"] == 3
            and any(b.startswith(photo_profile.ENTITIES_NAME) for b in baks)
            and not any(n in out for n in ("13.5", "23.25"))), \
        f"code={code} places={[(p.get('id'), p.get('label')) for p in places]} " \
        f"baks={baks} out={out[-300:]!r}"


@case
def a_home_named_mid_run_is_appended_too():
    """REPRODUCTION (G6-2, R12). ⛔ FAILS on 76cb997 (refused: the pack held
    homes). A "home" answer on a later page appends home-03."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = written_pack(tmp)
        code, out = second_answer(tmp, pack, "home: D = Hill House live\n")
        homes = load(pack, photo_profile.PROFILE_NAME)["home_locations"]
    return (code == 0
            and [h["id"] for h in homes] == ["home-01", "home-02", "home-03"]
            and homes[2]["label"] == "Hill House"), \
        f"code={code} homes={[(h.get('id'), h.get('label')) for h in homes]} {out[-200:]!r}"


@case
def an_appended_row_that_clashes_is_still_refused():
    """GUARD (G6-2; refused on 76cb997 too, for the old reason). The same label,
    or a new row within the radius that already answers for an existing row,
    is a merge — refused whole, nothing written, no coordinate said."""
    results = []
    for answer in ("home: D = Harbour Cafe\n", "home: E = Other Cafe\n"):
        with tempfile.TemporaryDirectory() as tmp:
            pack = written_pack(tmp)
            before = (pack / photo_profile.ENTITIES_NAME).read_bytes()
            code, out = second_answer(tmp, pack, answer)
            results.append((code, "Nothing written" in out,
                            (pack / photo_profile.ENTITIES_NAME).read_bytes() == before,
                            "12.5001" in out))
    return results == [(1, True, True, False)] * 2, f"{results}"


@case
def write_pack_report_shows_ids_and_no_coordinate():
    """GUARD. Operational Rule 3: the report names what landed by label and id."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = make_pack(tmp)
        answers = Path(tmp) / "answers.txt"
        answers.write_text(ANSWERS, encoding="utf-8")
        coords = Path(tmp) / "coords.txt"
        coords.write_text(COORDS, encoding="utf-8")
        _code, out, _ = op_main("apply", answers, "--write-pack", pack,
                                "--coords-in", coords)
    return ("Ford" in out and "home-01" in out and "fsl-0001" in out
            and not any(n in out for n in NUMBERS)), out[-400:]


# ---------------------------------------------------------------------------
# the readers — ids exposed through the ONE reader of each list
# ---------------------------------------------------------------------------

@case
def the_readers_expose_the_id():
    """REPRODUCTION. ⛔ FAILS on 25cf5f3: `labelled_home_points()` rows had
    five elements and `named_places()` rows three, so no caller could learn
    which home or place a day matched."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = photo_profile.resolve_pack(
            explicit=written_pack(tmp) / photo_profile.PROFILE_NAME)
        homes = photo_profile.labelled_home_points(pack.profile)
        places = photo_profile.named_places(pack)
    return ([h[5] for h in homes] == ["home-01", "home-02"]
            and [p[3] for p in places] == ["fsl-0001"]
            and [p[2] for p in places] == ["Harbour Cafe"]), \
        f"homes={[h[4:] for h in homes]}, places={[p[2:] for p in places]}"


@case
def the_privacy_list_never_sees_an_id():
    """GUARD. `home_points()` is a 4-tuple slice on purpose: the callers whose
    whole job is to refuse to print anything get no label and no id."""
    with tempfile.TemporaryDirectory() as tmp:
        profile = load(written_pack(tmp), photo_profile.PROFILE_NAME)
    rows = photo_profile.home_points(profile)
    return (len(rows) == 2 and all(len(r) == 4 for r in rows)), f"rows={rows}"


@case
def a_row_with_no_id_is_warned_once_and_reads_none():
    """GUARD. A hand-written home (photo-init tells the agent to type one when
    the census proposes nothing) is warned about, reads as None, and is still
    suppressed — never refused, never numbered at load."""
    profile = {"home_locations": [dict(HOME)]}
    said = warnings_of(lambda: (photo_profile.labelled_home_points(profile),
                                photo_profile.labelled_home_points(profile)))
    rows = photo_profile.labelled_home_points(profile)
    return (rows[0][5] is None and len(photo_profile.home_points(profile)) == 1
            and said.count("home_locations[0] has no id") == 1
            and "backfill-ids" in said and "id" not in profile["home_locations"][0]
            and not any(n in said for n in NUMBERS)), f"said={said!r}"


@case
def a_shared_or_malformed_id_reads_none():
    """GUARD. One id on two rows points at neither, and a row LETTER is not an
    id — one real scratch pack held `"id": "C"`. Both read None and are said."""
    profile = {"home_locations": [dict(HOME, id="home-01"),
                                  dict(VISIT, id="home-01"),
                                  dict(HOME, id="C")]}
    said = warnings_of(lambda: photo_profile.labelled_home_points(profile))
    rows = photo_profile.labelled_home_points(profile)
    return ([r[5] for r in rows] == [None, None, None]
            and said.count("shares its id") == 2
            and "home_locations[2] has an id not in home-NN form" in said), \
        f"ids={[r[5] for r in rows]}, said={said!r}"


@case
def no_pack_reads_as_before():
    """GUARD. A dump with no pack — every benchmark — reads no homes and no
    places, and says nothing."""
    said = warnings_of(lambda: (photo_profile.labelled_home_points({}),
                                photo_profile.named_places(
                                    photo_profile.Pack())))
    return (photo_profile.labelled_home_points({}) == []
            and photo_profile.named_places(photo_profile.Pack()) == []
            and said == ""), f"said={said!r}"


# ---------------------------------------------------------------------------
# one case per pack route — ⛔ LL-PHO-132. `named_places()` reads the pack's
# FOLDER, so a route that loses `pack.dir` loses the place ids with it.
# ---------------------------------------------------------------------------

def ids_via(pack):
    homes = photo_profile.labelled_home_points(pack.profile)
    return ([h[5] for h in homes], [p[3] for p in photo_profile.named_places(pack)])


WANT = (["home-01", "home-02"], ["fsl-0001"])


@contextlib.contextmanager
def no_env():
    saved = os.environ.pop(photo_profile.ENV_VAR, None)
    try:
        yield
    finally:
        os.environ.pop(photo_profile.ENV_VAR, None)
        if saved is not None:
            os.environ[photo_profile.ENV_VAR] = saved


@case
def route_collection_json():
    with tempfile.TemporaryDirectory() as tmp, no_env():
        pack = written_pack(tmp)
        workdir = Path(tmp) / "Working Files" / "dump-a"
        workdir.mkdir(parents=True)
        (workdir.parent / "collection.json").write_text(json.dumps({
            "collection": "fixture", "owner": pack.name,
            "memory_root": str(pack.parent)}), encoding="utf-8")
        got = ids_via(photo_profile.resolve_pack(workdir=workdir))
    return got == WANT, f"got={got}"


@case
def route_env_var():
    with tempfile.TemporaryDirectory() as tmp, no_env():
        pack = written_pack(tmp)
        os.environ[photo_profile.ENV_VAR] = str(pack / photo_profile.PROFILE_NAME)
        got = ids_via(photo_profile.resolve_pack())
    return got == WANT, f"got={got}"


@case
def route_explicit_profile():
    with tempfile.TemporaryDirectory() as tmp, no_env():
        pack = written_pack(tmp)
        got = ids_via(photo_profile.resolve_pack(
            explicit=str(pack / photo_profile.PROFILE_NAME)))
    return got == WANT, f"got={got}"


# ---------------------------------------------------------------------------
# the backfill — a pack written before ids existed
# ---------------------------------------------------------------------------

@case
def backfill_dry_run_writes_nothing():
    """REPRODUCTION. ⛔ FAILS on 25cf5f3: there was no `backfill-ids`
    command (argparse exits 2), so a pack written before ids — every existing
    owner's — could never gain them. The dry run is the default."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = legacy_pack(tmp, [HOME, VISIT], [PLACE])
        before = {leaf: (pack / leaf).read_bytes()
                  for leaf in os.listdir(pack) if (pack / leaf).is_file()}
        code, out, _ = op_main("backfill-ids", pack)
        after = {leaf: (pack / leaf).read_bytes()
                 for leaf in os.listdir(pack) if (pack / leaf).is_file()}
    return (code == 0 and before == after and "DRY RUN" in out
            and "Ford -> home-01" in out and "Bay -> home-02" in out
            and "Harbour Cafe -> fsl-0001" in out
            and "refused at `confirm`" in out
            and not any(n in out for n in NUMBERS)), out[-600:]


@case
def backfill_go_adds_ids_and_changes_nothing_else():
    """REPRODUCTION, the write. A `.bak` first; then the ids, as each row's
    first key, and the mark right after its list — every other key, value and
    key order as it was. The pack id moves once, and the report says so."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = legacy_pack(tmp, [HOME, VISIT], [PLACE])
        old = load(pack, photo_profile.PROFILE_NAME)
        old_raw = (pack / photo_profile.PROFILE_NAME).read_text(encoding="utf-8")
        before = photo_profile.Pack(directory=pack).snapshot()["id"]
        code, out, _ = op_main("backfill-ids", pack, "--go")
        new = load(pack, photo_profile.PROFILE_NAME)
        ents = load(pack, photo_profile.ENTITIES_NAME)
        baks = sorted(p.name for p in pack.glob("*.bak-*-ids"))
        bak_raw = next(pack.glob(photo_profile.PROFILE_NAME + ".bak-*")) \
            .read_text(encoding="utf-8")
        after = photo_profile.Pack(directory=pack).snapshot()["id"]
    keys = list(new)
    stripped = {k: v for k, v in new.items() if k != "home_locations_next_id"}
    stripped["home_locations"] = [{k: v for k, v in h.items() if k != "id"}
                                  for h in new["home_locations"]]
    return (code == 0 and bak_raw == old_raw and len(baks) == 2
            and [h["id"] for h in new["home_locations"]] == ["home-01", "home-02"]
            and all(list(h)[0] == "id" for h in new["home_locations"])
            and keys[keys.index("home_locations") + 1] == "home_locations_next_id"
            and new["home_locations_next_id"] == 3
            and stripped == old and list(stripped) == list(old)
            and [p["id"] for p in ents["frequent_places"]] == ["fsl-0001"]
            and before != after and before in out and after in out), \
        f"code={code}, baks={baks}, keys={keys}, out={out[-300:]!r}"


@case
def backfill_is_idempotent():
    """GUARD. A second run finds nothing missing and writes nothing — no new
    `.bak`, no byte changed, the pack id unmoved."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = legacy_pack(tmp, [HOME], [PLACE])
        op_main("backfill-ids", pack, "--go")
        files = {p.name: p.read_bytes() for p in pack.iterdir() if p.is_file()}
        code, out, _ = op_main("backfill-ids", pack, "--go")
        again = {p.name: p.read_bytes() for p in pack.iterdir() if p.is_file()}
    return (code == 0 and files == again and "Nothing to write" in out), \
        out[-300:]


@case
def backfill_leaves_shared_and_malformed_ids_alone():
    """GUARD. It reports them and never renumbers one — renumbering would
    redirect an older index. A missing id is numbered after the highest valid
    id present AND the mark, whichever is later."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = legacy_pack(tmp, [dict(HOME, id="home-02"),
                                 dict(VISIT, id="home-02"),
                                 dict(HOME, id="C"), dict(VISIT)],
                           home_locations_next_id=6)
        code, out, _ = op_main("backfill-ids", pack, "--go")
        ids = [h.get("id") for h in
               load(pack, photo_profile.PROFILE_NAME)["home_locations"]]
    return (code == 0 and ids == ["home-02", "home-02", "C", "home-06"]
            and out.count("left alone") == 3), f"ids={ids}, out={out[-500:]!r}"


@case
def backfill_writes_only_the_file_that_changed():
    """GUARD. A pack with homes and no named places rewrites
    photo-profile.json only; photo-entities.json keeps its own bytes and its
    own hand formatting, and gets no `.bak`."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = legacy_pack(tmp, [HOME])
        ents = pack / photo_profile.ENTITIES_NAME
        ents.write_text('{"owner": {"slug": "pack"},  "frequent_places": []}\n',
                        encoding="utf-8")
        raw = ents.read_bytes()
        code, _out, _ = op_main("backfill-ids", pack, "--go")
        baks = [p.name for p in pack.glob("*.bak-*")]
        same = ents.read_bytes() == raw
    return (code == 0 and same and len(baks) == 1
            and baks[0].startswith(photo_profile.PROFILE_NAME)), f"baks={baks}"


@case
def an_existing_mark_keeps_its_place():
    """GUARD. A mark the owner's file already holds — wherever it sits — is
    updated where it is, never moved after the list."""
    data = {"a": 1, "home_locations_next_id": 4,
            "home_locations": [dict(HOME)], "z": 2}
    mark, assigned = photo_profile.assign_place_ids(
        data["home_locations"], "home_locations", data["home_locations_next_id"])
    out = photo_profile.with_place_ids(data, "home_locations", assigned, mark)
    return (list(out) == list(data) and out["home_locations_next_id"] == 5
            and out["home_locations"][0]["id"] == "home-04"), \
        f"keys={list(out)}, out={out}"


@case
def a_blank_pack_stays_blank():
    """GUARD. The template ships no rows and no mark, so a backfill of a new
    owner's pack writes nothing, and `pack_state` still reads it as a blank
    sheet — the benchmark owner's precondition."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = make_pack(tmp, "betauser00")
        code, out, _ = op_main("backfill-ids", pack, "--go")
        facts = pack_state.owner_facts_in(photo_profile.resolve_pack(
            explicit=str(pack / photo_profile.PROFILE_NAME)))
    return (code == 0 and "Nothing to write" in out and facts == []), \
        f"facts={facts}, out={out[-200:]!r}"


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

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} place id cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
