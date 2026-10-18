#!/usr/bin/env python3
"""M6 cases — the fix plan before the freeze (SPEC G17, G18; card E47).

The engine drafts ops from rules R1-R6 on the index; `freeze` stops with exit
3 and writes `plan/fix-plan.md` while a row has no answer, and nothing is
frozen. `photo_index.py fix-plan --answers ... --go` applies the `ok` and
`word:` rows through `open_for_change` and records every answer, so a row is
asked once. Built here: R2 (every confirmed pet, on a folder the dump merges
into), R3 (drop a look of a named pet), R4 (a day that already has a folder
goes into it). R1, R5 and R6 are named stubs.

  python3 tests/fix_plan_cases.py [-v]

Exit 0 = pass. Every dump, pack, place and pet is synthetic, in a temp dir.
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import photo_exiftool  # noqa: E402
import photo_index  # noqa: E402
import photo_profile  # noqa: E402
import photo_subjects  # noqa: E402
import index_finish_cases as fin  # noqa: E402
import photo_index_cases as ix  # noqa: E402

LOTUS_DAY = "20241101_Ford_Lotus_sofa nap"
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def must(code_out_err, what, ok=(0,)):
    code, out, err = code_out_err
    if code not in ok:
        raise RuntimeError(f"{what}: rc {code} {(out + err)[-500:]}")
    return out


def page(wd):
    return wd / "plan" / photo_index.FIX_PLAN_MD


def rows(wd):
    return [r for r in page(wd).read_text().splitlines()
            if photo_index.FIX_ROW.match(r)]


def answer(wd, *answers):
    lines, k = [], 0
    for line in page(wd).read_text().splitlines():
        if photo_index.FIX_ROW.match(line):
            line = line.replace("answer: ______", f"answer: {answers[k]}")
            k += 1
        lines.append(line)
    page(wd).write_text("\n".join(lines) + "\n")


def apply(wd, go=True):
    return ix.run("fix-plan", wd, "--answers", page(wd), *(["--go"] if go else []))


def add_look(pack, sid, words, wd=None):
    """Record a look; with `wd`, render and check again (the pack moved)."""
    registry = photo_subjects.load(pack=photo_profile.resolve_pack(
        explicit=pack / photo_profile.PROFILE_NAME))
    registry.add_look(sid, words)
    registry.save()
    if wd is not None:
        must(ix.run("render", wd), "render")
        must(ix.run("check", wd), "check")


def ready(tmp):
    """g3, initialised, rendered, checked — not frozen."""
    return fin.ready(tmp, freeze=False)


def state(*roots):
    out = {}
    for root in roots:
        for p in sorted(Path(root).rglob("*")):
            if p.is_file():
                out[str(p)] = (p.read_bytes(), p.stat().st_mtime_ns)
    return out


def names(tmp, key="dump-a"):
    return {fo["id"]: fo["rendered"] for fo in ix.index_of(tmp, key)[0]["folders"]}


# ---------------------------------------------------------------------------
# looks (Lead ruling 20261018, Q2)
# ---------------------------------------------------------------------------

@case
def an_old_pack_loads_with_no_looks_and_is_not_rewritten():
    """GUARD. A record with no `looks` key has none, and saving the registry
    adds no key to it (the not_mine pattern)."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        _wd, pack = ix.g3_dump(tmp)
        reg_path = pack / "photo-subjects" / "subjects.json"
        registry = photo_subjects.load(pack=photo_profile.resolve_pack(
            explicit=pack / photo_profile.PROFILE_NAME))
        looks = [s.looks for s in registry.subjects]
        registry.save()
        saved = json.loads(reg_path.read_text())["subjects"]
    return (looks == [[], []] and all("looks" not in s for s in saved)), \
        f"looks={looks} keys={[sorted(s) for s in saved]}"


@case
def the_look_command_adds_and_removes_with_a_dry_run():
    """`photo_subjects.py look <subj> --add/--remove`: a dry run writes
    nothing; --go writes; the same look twice (any case) is one look."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ix.g3_dump(tmp)
        reg_path = pack / "photo-subjects" / "subjects.json"
        script = ROOT / "scripts" / "photo_subjects.py"

        def look(*argv):
            return subprocess.run([sys.executable, str(script), "look", "subj-0001",
                                   str(wd), *argv], capture_output=True, text=True)

        before = reg_path.read_bytes()
        dry = look("--add", "grey cat")
        dry_same = before == reg_path.read_bytes()
        look("--add", "grey cat", "--go")
        look("--add", "Grey Cat", "--go")
        added = json.loads(reg_path.read_text())["subjects"][0].get("looks")
        look("--remove", "GREY CAT", "--go")
        removed = json.loads(reg_path.read_text())["subjects"][0].get("looks")
    return (dry.returncode == 0 and dry_same and added == ["grey cat"]
            and removed == []), f"dry={dry.stdout!r} added={added} removed={removed}"


# ---------------------------------------------------------------------------
# the stop, R3, answers
# ---------------------------------------------------------------------------

@case
def no_rule_fires_and_the_freeze_goes_on():
    """GUARD. A pet with no look, no merge and no existing folder: no op. The
    fix plan says "Nothing to change." and the freeze freezes as before."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        code, out, _ = ix.run("fix-plan", wd)
        fcode, fout, ferr = ix.run("freeze", wd)
    return (code == 0 and photo_index.NOTHING_TO_CHANGE in out and fcode == 0
            and "frozen" in fout), f"code={code} freeze={fcode} {ferr[-300:]!r}"


@case
def a_look_of_a_named_pet_stops_the_freeze_and_ok_drops_it():
    """⭐ REPRODUCTION (M6 R3, E47). ⛔ FAILS on 68bb0a9: nothing drafted a fix
    plan. Lotus is named in the folder and its [what] is a look Lotus carried
    before it had a name: the freeze stops with exit 3, freezes nothing, and
    the plan holds one R3 row; `ok` + --go records it, render drops the word,
    and the freeze then holds."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp)
        add_look(pack, "subj-0001", "sofa nap", wd)
        code, out, _ = ix.run("freeze", wd)
        frozen = ix.index_of(tmp)[0].get("frozen")
        got = rows(wd)
        answer(wd, "ok")
        acode, aout, aerr = apply(wd)
        must(ix.run("render", wd), "render")
        must(ix.run("check", wd), "check")
        n = names(tmp)
        fcode, _f, ferr = ix.run("freeze", wd)
        index = ix.index_of(tmp)[0]
    row = (f"1. RENAME (R3) · F001 · `{LOTUS_DAY}` → `20241101_Ford_Lotus` · "
           "drops sofa nap: a look of Lotus, already named")
    return (code == 3 and not frozen and len(got) == 1 and got[0].startswith(row)
            and acode == 0 and n["F001"] == "20241101_Ford_Lotus"
            and fcode == 0 and index.get("frozen")
            and list(index["fix_plan"]["answers"].values())[0]["answer"] == "ok"), \
        (f"code={code} frozen={bool(frozen)} rows={got} apply={acode} {aout[-300:]!r}"
         f"{aerr[-300:]!r} names={n} freeze={fcode} {ferr[-300:]!r}")


@case
def a_skip_is_recorded_and_never_asked_again():
    """GUARD (G21). `skip` changes nothing, is recorded, and the next freeze
    is not stopped by the same row; a row left open is a skip too."""
    got = {}
    for given in ("skip", "______"):
        with tempfile.TemporaryDirectory() as tmp, ix.no_env():
            wd, pack = ready(tmp)
            add_look(pack, "subj-0001", "sofa nap", wd)
            ix.run("freeze", wd)
            if given != "______":
                answer(wd, given)
            acode, _a, _ = apply(wd)
            fcode, _f, _ = ix.run("freeze", wd)
            index = ix.index_of(tmp)[0]
            got[given] = (acode, fcode, names(tmp)["F001"],
                          [a["answer"] for a in index["fix_plan"]["answers"].values()])
    return (got["skip"] == (0, 0, LOTUS_DAY, ["skip"])
            and got["______"] == (0, 0, LOTUS_DAY, ["skip"])), f"{got}"


@case
def a_dry_run_of_the_answers_writes_nothing():
    """GUARD (Lead). `fix-plan --answers` without --go: every file of the
    work dir and the pack keeps its bytes and its mtime."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp)
        add_look(pack, "subj-0001", "sofa nap", wd)
        ix.run("freeze", wd)
        answer(wd, "ok")
        before = state(wd, pack)
        code, out, _ = apply(wd, go=False)
        after = state(wd, pack)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    return (code == 0 and "DRY RUN" in out and not changed), \
        f"code={code} changed={changed} out={out[-300:]!r}"


@case
def only_new_ops_are_asked_after_the_index_changes():
    """GUARD (Lead Q3). Answered rows stay answered; a change that makes a
    NEW op (Rex confirmed with a look on the other day) asks that one only."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp)
        add_look(pack, "subj-0001", "sofa nap", wd)
        ix.run("freeze", wd)
        answer(wd, "skip")
        apply(wd)
        fin.confirm_rex(pack)
        add_look(pack, "subj-0002", "harbour walk", wd)
        code, _o, _ = ix.run("freeze", wd)
        got = rows(wd)
    return (code == 3 and len(got) == 1 and "(R3) · F002 ·" in got[0]), \
        f"code={code} rows={got}"


@case
def a_word_answer_gives_the_folder_the_owners_what():
    """GUARD (G21 `word:`). On an R3 row the owner's own words become the
    folder's [what]; on an R4/R2 row a word is refused."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp)
        add_look(pack, "subj-0001", "sofa nap", wd)
        ix.run("freeze", wd)
        answer(wd, "word: garden lunch")
        acode, _a, _ = apply(wd)
        must(ix.run("render", wd), "render")
        n = names(tmp)
    return (acode == 0 and n["F001"] == "20241101_Ford_Lotus_garden lunch"), \
        f"apply={acode} names={n}"


@case
def an_agent_row_is_validated_and_applied_on_ok():
    """GUARD (G17). An agent row is marked `agent`; a name the grammar
    refuses is listed as refused and never offered; a valid one names the
    folder on `ok`."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        must(ix.run("fix-plan", wd, "--agent", "F002", "--to", "Harbour walk day",
                    "--reason", "no period"), "agent bad")
        must(ix.run("fix-plan", wd, "--agent", "F002", "--to",
                    "20241102_Harbour_old pier", "--reason", "the pier"), "agent")
        code, out, _ = ix.run("freeze", wd)
        got = rows(wd)
        text = page(wd).read_text()
        answer(wd, "ok")
        apply(wd)
        must(ix.run("render", wd), "render")
        n = names(tmp)
    return (code == 3 and len(got) == 1 and "(agent) · F002 ·" in got[0]
            and "## Refused" in text and "Harbour walk day" in text
            and n["F002"] == "20241102_Harbour_old pier"), \
        f"code={code} rows={got} names={n} text={text[-500:]!r}"


# ---------------------------------------------------------------------------
# R1 — the landmark
# ---------------------------------------------------------------------------

def landmark_later(wd, place="Old Pier", flags=None):
    """batches.json now names batch 2 by its landmark (A1's lookup, run after
    the index was built), optionally flagged."""
    path = wd / "batches.json"
    doc = json.loads(path.read_text())
    for b in doc["batches"]:
        if b["batch"] == 2:
            b["place"] = place
            if flags is not None:
                b["flags"] = flags
    path.write_text(json.dumps(doc))


@case
def a_landmark_the_folder_does_not_carry_is_offered():
    """⭐ REPRODUCTION (M6 R1, E29). ⛔ FAILS on 68bb0a9. The batch's landmark
    is Old Pier and F002 still says Harbour: an R1 row offers it; `ok` makes
    the landmark the folder's [where], and `word:` instead gives the owner's
    own place word through set-where."""
    got = {}
    for given in ("ok", "word: Pier Road"):
        with tempfile.TemporaryDirectory() as tmp, ix.no_env():
            wd, _pack = ready(tmp)
            landmark_later(wd)
            code, _o, _ = ix.run("freeze", wd)
            r = rows(wd)
            answer(wd, given)
            acode, aout, aerr = apply(wd)
            must(ix.run("render", wd), "render")
            got[given] = (code, r, acode, names(tmp)["F002"],
                          ix.index_of(tmp)[0]["folders"][1].get("where_set"))
    ok, word = got["ok"], got["word: Pier Road"]
    return (ok[0] == 3 and len(ok[1]) == 1
            and "(R1) · F002 · `20241102_Harbour_harbour walk` → "
                "`20241102_Old Pier_harbour walk` · the landmark is Old Pier" in ok[1][0]
            and ok[2] == 0 and ok[3] == "20241102_Old Pier_harbour walk"
            and word[2] == 0 and word[3] == "20241102_Pier Road_harbour walk"
            and word[4]["text"] == "Pier Road"), f"{got}"


@case
def the_owners_own_place_word_is_never_proposed_over():
    """GUARD (ADR 0001). A folder whose [where] the owner set gets no R1 row,
    whatever the landmark."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        must(ix.run("group", "set-where", wd, "F002", "Pier Road", "--reason",
                    "the owner's word"), "set-where")
        must(ix.run("render", wd), "render")
        landmark_later(wd)
        code, out, _ = ix.run("fix-plan", wd)
    return code == 0 and photo_index.NOTHING_TO_CHANGE in out, \
        f"code={code} out={out[-400:]!r}"


@case
def a_failed_landmark_lookup_is_said_and_never_offered():
    """GUARD (A1's flag). A batch flagged `landmark_lookup_failed` gets no
    row to answer: the plan lists it as refused, saying to type the place,
    and the freeze goes on."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        landmark_later(wd, flags=["landmark_lookup_failed"])
        code, out, _ = ix.run("fix-plan", wd)
        fcode, fout, _ = ix.run("freeze", wd)
    return (code == 0 and "## Refused" in out and "landmark lookup failed" in out
            and "set-where" in out and fcode == 0
            and "landmark lookup failed" in fout), \
        f"code={code} out={out[-500:]!r} freeze={fcode} {fout[-300:]!r}"


# ---------------------------------------------------------------------------
# R4 — a day that already has a folder; R2 on a folder the dump merges into
# ---------------------------------------------------------------------------

OLD = "2024/20241101_Old trip"


def owner_folder(tmp, day="2024:11:01 09:00:00", rel=OLD):
    """The owner's own dated folder in the dest, holding one real photo of
    that capture day (exiftool reads its date, as M4's scan does)."""
    from PIL import Image
    photo = Path(tmp).resolve() / "sorted" / rel / "OLD_0001.jpg"
    photo.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), (10, 20, 30)).save(photo, "JPEG")
    photo_exiftool.run(["-overwrite_original", f"-DateTimeOriginal={day}"], [photo])
    return photo


@case
def a_day_with_a_folder_in_the_dest_goes_into_it():
    """⭐ REPRODUCTION (M6 R4, E17/E44). ⛔ FAILS on 68bb0a9. The owner's
    folder already holds a photo of 2024-11-01: the plan asks to merge F001
    into it, saying it is a merge into an existing folder (D5); `ok` makes
    F001 a merge, and the copy lands in the owner's folder. Lotus, confirmed
    in F001, is then missing from that folder's name: R2 lists a rename BY
    HAND (the engine did not create the folder), and `ok` renames nothing."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        old_photo = owner_folder(tmp)
        wd, _pack = ready(tmp)
        code, _o, _ = ix.run("freeze", wd)
        r4 = rows(wd)
        answer(wd, "ok")
        must(apply(wd), "apply R4")
        must(ix.run("render", wd), "render")
        must(ix.run("check", wd), "check")
        code2, _o2, _ = ix.run("freeze", wd)
        r2 = rows(wd)
        answer(wd, "ok")
        acode, aout, _ = apply(wd)
        must(ix.run("render", wd), "render")
        must(ix.run("check", wd), "check")
        fcode, _f, ferr = ix.run("freeze", wd)
        run = fin.finish(wd)
        landed = sorted(p.name for p in old_photo.parent.iterdir())
        still = old_photo.parent.is_dir()
    return (code == 3 and len(r4) == 1 and f"(R4) · F001 · `{LOTUS_DAY}` → `{OLD}`" in r4[0]
            and "merges into the existing folder" in r4[0]
            and code2 == 3 and len(r2) == 1 and "(R2) · F001 ·" in r2[0]
            and "rename it by hand" in r2[0] and acode == 0
            and "nothing renamed" in aout and fcode == 0 and still
            and run.returncode == 0 and "IMG_0101.jpg" in landed
            and "OLD_0001.jpg" in landed), \
        (f"code={code} r4={r4} code2={code2} r2={r2} apply={acode} {aout[-300:]!r} "
         f"freeze={fcode} {ferr[-300:]!r} finish={run.returncode} landed={landed} "
         f"{run.stdout[-400:]!r}")


@case
def a_merge_into_a_folder_named_after_a_pet_not_in_this_dump_passes_e48():
    """⭐ REPRODUCTION (E48). ⛔ FAILS on c8f1dac: the owner's folder is named
    after Birk, a confirmed pet no photo of this dump shows; merging F001 into
    it (R4) failed check F12 and photo_plan's name check, as if this dump
    had named it. The existing name keeps its pets: check, freeze and the
    copy pass, and Birk stays in the folder's name."""
    rel = "2024/20241101_Old trip_Birk"
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        old_photo = owner_folder(tmp, rel=rel)
        wd, pack = ix.g3_dump(tmp)
        reg = pack / "photo-subjects" / "subjects.json"
        data = json.loads(reg.read_text())
        data["subjects"].append(ix.subject("subj-0003", "Birk"))
        reg.write_text(json.dumps(data))
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        ix.run("freeze", wd)
        answer(wd, "ok")
        must(apply(wd), "apply R4")
        must(ix.run("render", wd), "render")
        ccode, cout, cerr = ix.run("check", wd)
        ix.run("freeze", wd)            # R2: adds Lotus, by hand
        answer(wd, "skip")
        must(apply(wd), "apply R2")
        fcode, fout, ferr = ix.run("freeze", wd)
        run = fin.finish(wd)
        landed = sorted(p.name for p in old_photo.parent.iterdir())
    return (ccode == 0 and fcode == 0 and run.returncode == 0
            and "IMG_0101.jpg" in landed), \
        (f"check={ccode} {cout[-300:]!r}{cerr[-200:]!r} freeze={fcode} "
         f"{fout[-200:]!r}{ferr[-300:]!r} finish={run.returncode} landed={landed}")


@case
def a_trip_abroad_stays_out_of_an_existing_folder():
    """GUARD (E52). A day of a batch abroad (OVERSEAS) is never merged into
    an existing folder: no R4 row (an R5 trip row may be offered)."""
    batches = [dict(b, day_type="OVERSEAS") for b in ix.G3_BATCHES]
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        owner_folder(tmp)
        wd, pack = ix.g3_dump(tmp, batches=batches)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        _code, out, _ = ix.run("fix-plan", wd)
    return "(R4)" not in out, f"out={out[-400:]!r}"


def second_dump(tmp):
    """dump-b in the same collection: two photos of 2024-11-01, one naming
    Birk (confirmed), merged into the folder dump-a created. No photo of
    dump-b shows Lotus, whose name the folder holds (E48)."""
    base = Path(tmp).resolve() / "raw" / "dump-b"
    base.mkdir(parents=True)
    for name in ("IMG_0105.jpg", "IMG_0106.jpg"):
        (base / name).write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
                                  + name.encode() + b"\xff\xd9")
    wd = ix.make_dump(tmp, rows=[ix.row(n, SourceFile=str(base / n), when=w)
                                 for n, w in (("IMG_0105.jpg", "2024:11:01 15:00:00"),
                                              ("IMG_0106.jpg", "2024:11:01 16:00:00"))],
                      batches=[{"batch": 1, "from": "2024-11-01", "to": "2024-11-01",
                                "place": "Ford"}], name="dump-b")
    pack = ix.make_pack(tmp)
    reg = pack / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text())
    data["subjects"].append(ix.subject("subj-0003", "Birk"))
    reg.write_text(json.dumps(data))
    ix.write_see(wd, 1, [ix.see_label(base, "IMG_0105.jpg",
                                      [{"subject_id": "subj-0003"}], "sofa nap"),
                         ix.see_label(base, "IMG_0106.jpg", what="sofa nap")])
    must(ix.run("init", wd), "init b")
    return wd


@case
def r2_renames_a_folder_an_earlier_dump_copied_and_moves_both_records():
    """⭐ REPRODUCTION (M6 R2, Lead rulings 20261018). ⛔ FAILS on 68bb0a9.
    dump-a copied and CREATED `20241101_Ford_Lotus_sofa nap`; dump-b merges a
    Birk photo into it. R2 offers an engine RENAME (no "by hand"); a dry run
    writes nothing in either dump or the tree; `ok` + --go renames it with
    the proof, moves dump-a's record and logs in both dumps; dump-a's verify
    and after-check still find every copy (0 missing); dump-b then copies
    into the renamed folder."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wa, pack = fin.ready(tmp)
        must_run = fin.finish(wa)
        sorted_root = Path(tmp).resolve() / "sorted"
        folder = sorted_root / LOTUS_DAY
        wb = second_dump(tmp)
        must(ix.run("dest", wb, "F001", "merge", folder, "--ref", wa,
                    "--reason", "the same day"), "dest")
        must(ix.run("render", wb), "render b")
        must(ix.run("check", wb), "check b")
        code, _o, _ = ix.run("freeze", wb)
        got = rows(wb)
        answer(wb, "ok")
        before = state(wa, wb, sorted_root)
        dcode, _d, _ = apply(wb, go=False)
        dry_same = before == state(wa, wb, sorted_root)
        acode, aout, aerr = apply(wb)
        new = sorted_root / "20241101_Ford_Lotus+Birk_sofa nap"
        moved = new.is_dir() and not folder.exists()
        va, _v, _ = ix.run("verify", wa, "--copied")
        ca, cout, _ = ix.run("after-check", wa)
        logs = [json.loads((w / "plan" / "after-check-log.json").read_text())
                for w in (wa, wb)]
        for cmd in ("render", "check", "freeze"):
            must(ix.run(cmd, wb), f"{cmd} b2")
        run_b = fin.finish(wb)
        landed = sorted(p.name for p in new.iterdir())
    return (must_run.returncode == 0 and code == 3 and len(got) == 1
            and "(R2) · F001 ·" in got[0] and "by hand" not in got[0]
            and "adds Birk" in got[0] and dcode == 0 and dry_same
            and acode == 0 and "renamed" in aout and moved
            # 6 = every copy matches and only the pack moved (dump-b added
            # Birk): the drive is fine, which is what is proved here.
            and va in (0, 6) and ca == 0 and "missing 0" in cout
            and all(len(log) == 1 and log[0]["before"] == log[0]["after"]
                    for log in logs)
            and run_b.returncode == 0 and "IMG_0105.jpg" in landed), \
        (f"code={code} rows={got} dry={dcode} {dry_same} apply={acode} "
         f"{aout[-400:]!r}{aerr[-300:]!r} moved={moved} verify_a={va} "
         f"after_a={ca} {cout[-300:]!r} finish_b={run_b.returncode} landed={landed}")


@case
def r2_never_moves_a_folder_whose_earlier_copy_is_unfinished():
    """GUARD (Lead). An earlier dump whose copy record misses a row: the R2
    row renames nothing and says to rename by hand; the tree is untouched."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wa, _pack = fin.ready(tmp)
        fin.finish(wa)
        for sp in (wa / "plan").glob("execute-state_P1.json"):
            doc = json.loads(sp.read_text())
            doc["verified"].pop(next(iter(doc["verified"])))
            sp.write_text(json.dumps(doc))
        sorted_root = Path(tmp).resolve() / "sorted"
        wb = second_dump(tmp)
        must(ix.run("dest", wb, "F001", "merge", sorted_root / LOTUS_DAY, "--ref", wa,
                    "--reason", "the same day"), "dest")
        must(ix.run("render", wb), "render b")
        must(ix.run("check", wb), "check b")
        ix.run("freeze", wb)
        answer(wb, "ok")
        before = ix.tree_state(sorted_root)
        acode, aout, _ = apply(wb)
        same = before == ix.tree_state(sorted_root)
    return (acode == 0 and "nothing renamed" in aout and "by hand" in aout
            and "not finished" in aout and same), f"apply={acode} {aout[-400:]!r}"


@case
def each_row_lists_up_to_three_previews_the_work_dir_already_has():
    """M9 thumbnails (Lead 20261018). After a row, an indented `samples:` line
    names up to 3 see-stage previews of the folder's files, relative to the
    work dir; no preview is made, a folder with none gets no line, and the
    answers still parse past it."""
    got = {}
    for with_previews in (True, False):
        with tempfile.TemporaryDirectory() as tmp, ix.no_env():
            wd, pack = ready(tmp)
            if with_previews:
                bdir = wd / "classify" / "batch-01"
                (bdir / "samples").mkdir(parents=True)
                base = Path(tmp).resolve() / "raw" / "dump-a"
                selected = []
                for name in ("IMG_0101.jpg", "IMG_0102.jpg"):
                    (bdir / "samples" / name).write_bytes(b"jpeg")
                    selected.append({"path": f"{base}/{name}", "sample": name})
                (bdir / "see-report.json").write_text(json.dumps(
                    {"batch": 1, "selected": selected}))
            add_look(pack, "subj-0001", "sofa nap", wd)
            ix.run("freeze", wd)
            text = page(wd).read_text()
            answer(wd, "ok")
            acode, _a, _ = apply(wd)
            got[with_previews] = ([l for l in text.splitlines() if "samples:" in l],
                                  acode)
    want = ["   samples: classify/batch-01/samples/IMG_0101.jpg | "
            "classify/batch-01/samples/IMG_0102.jpg"]
    return got[True] == (want, 0) and got[False] == ([], 0), f"{got}"


# ---------------------------------------------------------------------------
# R5 — one trip folder per trip abroad (A2's trip_candidates and make-trip)
# ---------------------------------------------------------------------------

TRIP = "20241101-1102_Ruritania_Ford+Harbour"


@case
def a_trip_abroad_becomes_a_make_trip_row_and_ok_makes_that_trip():
    """⭐ REPRODUCTION (M6 R5, end to end with A2). ⛔ FAILS on e552a87. Two
    days abroad: `trip_candidates` gives one MAKE-TRIP row (from "2 day
    folders 1101-1102", to the trip name, folder = the first id); `ok` runs
    `group make-trip`, and the trip parent then renders exactly `to` with
    F001 and F002 as its legs; `word:` is refused on R5; a dump at home gets
    no R5 row."""
    batches = [dict(b, day_type="OVERSEAS", country_word="Ruritania")
               for b in ix.G3_BATCHES]
    got = {}
    for given in ("ok", "word: Somewhere"):
        with tempfile.TemporaryDirectory() as tmp, ix.no_env():
            wd, _pack = ix.g3_dump(tmp, batches=batches)
            for cmd in ("init", "render", "check"):
                must(ix.run(cmd, wd), cmd)
            code, _o, _ = ix.run("freeze", wd)
            r = [x for x in rows(wd) if "(R5)" in x]
            answer(wd, *["ok" if "(R5)" in x else "skip" for x in rows(wd)]
                   if given == "ok" else
                   [given if "(R5)" in x else "skip" for x in rows(wd)])
            acode, aout, _ = apply(wd)
            must(ix.run("render", wd), "render")
            folders = ix.index_of(tmp)[0]["folders"]
            trip = [fo for fo in folders if fo["kind"] == "trip"]
            legs = sorted((fo["id"], fo.get("parent")) for fo in folders
                          if fo["kind"] == "leg")
            got[given] = (code, r, acode, [t["rendered"] for t in trip], legs,
                          aout[-300:])
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        _c, home_out, _ = ix.run("fix-plan", wd)
    ok, word = got["ok"], got["word: Somewhere"]
    tid = ok[4][0][1] if ok[4] else None
    return (ok[0] == 3 and len(ok[1]) == 1
            and f"MAKE-TRIP (R5) · F001 · `2 day folders 1101-1102` → `{TRIP}`" in ok[1][0]
            and ok[2] == 0 and ok[3] == [TRIP] and ok[4] == [("F001", tid), ("F002", tid)]
            and word[2] == 1 and "takes `ok` or `skip`" in word[5] and word[3] == []
            and "(R5)" not in home_out), f"{got}"


# ---------------------------------------------------------------------------
# R6 — the owner's own place word for the same spot
# ---------------------------------------------------------------------------

HARBOUR_DAY = "20241102_Harbour_harbour walk"
PIER_DAY = "2024/20241102_Old Pier_harbour walk"


def later_dump(tmp, gps=ix.FAR, day="2024:11:05", place="Harbour"):
    """dump-b of the same collection: two photos at `gps` on `day`, labelled
    `pier walk`, initialised, rendered and checked. -> work dir."""
    base = Path(tmp).resolve() / "raw" / "dump-b"
    base.mkdir(parents=True)
    rows = []
    for k, name in enumerate(("IMG_0501.jpg", "IMG_0502.jpg")):
        (base / name).write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
                                  + name.encode() + b"\xff\xd9")
        rows.append(ix.row(name, SourceFile=str(base / name),
                           when=f"{day} 1{k}:00:00", gps=gps))
    iso = day.replace(":", "-")
    wd = ix.make_dump(tmp, rows=rows, name="dump-b", batches=[
        {"batch": 1, "from": iso, "to": iso, "place": place}])
    ix.write_see(wd, 1, [ix.see_label(base, n, what="pier walk")
                         for n in ("IMG_0501.jpg", "IMG_0502.jpg")])
    for cmd in ("init", "render", "check"):
        must(ix.run(cmd, wd), f"{cmd} b")
    return wd


def copied_dump_a(tmp):
    wa, pack = fin.ready(tmp)
    if fin.finish(wa).returncode:
        raise RuntimeError("dump-a finish")
    return wa, pack, Path(tmp).resolve() / "sorted"


def hand_move(root, old, new):
    (root / new).parent.mkdir(parents=True, exist_ok=True)
    (root / old).rename(root / new)


@case
def a_word_the_owner_gave_by_renaming_and_moving_is_reused():
    """⭐ REPRODUCTION (M6 R6, E47 "reuse the owner's place word"). ⛔ FAILS on
    e552a87. dump-a was copied on v2.1-style flow; the owner then renamed its
    Harbour folder to `Old Pier` and moved it into a year folder. dump-b
    photographs the same spot: R6 finds the folder again by its copies'
    SHA-256, at any depth, and offers `Old Pier`; `ok` sets it through
    set-where, and the folder renders with the owner's word."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        _wa, _pack, root = copied_dump_a(tmp)
        hand_move(root, HARBOUR_DAY, PIER_DAY)
        wb = later_dump(tmp)
        code, _o, _ = ix.run("freeze", wb)
        got = rows(wb)
        answer(wb, "ok")
        acode, aout, _ = apply(wb)
        must(ix.run("render", wb), "render b")
        n = names(tmp, "dump-b")
        held = ix.index_of(tmp, "dump-b")[0]["folders"][0].get("where_set")
    row = ("1. RENAME (R6) · F001 · `20241105_Harbour_pier walk` → "
           "`20241105_Old Pier_pier walk` · you named this spot Old Pier in "
           f"{PIER_DAY}")
    return (code == 3 and len(got) == 1 and got[0].startswith(row) and acode == 0
            and n["F001"] == "20241105_Old Pier_pier walk"
            and held and held["text"] == "Old Pier"), \
        f"code={code} rows={got} apply={acode} {aout[-300:]!r} names={n} held={held}"


@case
def r6_offers_nothing_near_a_home_or_far_away():
    """GUARD (Lead). The owner renamed the HOME day folder and dump-b is at
    home: no row (never near a home). The owner renamed the Harbour folder and
    dump-b is far from it: no row (beyond 300 m)."""
    got = {}
    for label, old, new, gps, place in (
            ("home", "20241101_Ford_Lotus_sofa nap", "2024/20241101_Garden_Lotus_sofa nap",
             ix.HOME, "Ford"),
            ("far", HARBOUR_DAY, PIER_DAY, ix.FAR2, "Harbour")):
        with tempfile.TemporaryDirectory() as tmp, ix.no_env():
            _wa, _pack, root = copied_dump_a(tmp)
            hand_move(root, old, new)
            wb = later_dump(tmp, gps=gps, place=place)
            code, out, _ = ix.run("fix-plan", wb)
            got[label] = (code, photo_index.NOTHING_TO_CHANGE in out, "(R6)" in out)
    return all(v == (0, True, False) for v in got.values()), f"{got}"


@case
def an_engine_rename_gives_no_word():
    """GUARD (Lead). A folder the ENGINE renamed (a re-lock rename listed in
    plans.json) carries no owner word: no R6 row."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wa, _pack, root = copied_dump_a(tmp)
        new = "20241102_Old Pier_harbour walk"
        plans = json.loads((wa / "plans.json").read_text())
        plans["renames"] = [{"old": HARBOUR_DAY, "new": new}]
        (wa / "plans.json").write_text(json.dumps(plans))
        hand_move(root, HARBOUR_DAY, new)
        wb = later_dump(tmp)
        code, out, _ = ix.run("fix-plan", wb)
    return code == 0 and "(R6)" not in out, f"code={code} out={out[-400:]!r}"


@case
def a_split_or_doubled_folder_gives_no_word_and_is_counted():
    """GUARD (Lead). The Ford folder's two copies now sit in two folders (no
    folder holds more than half) and the Harbour copy sits in two folders at
    once: neither gives a word, and both are counted on a debug line, never
    as a row."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        _wa, _pack, root = copied_dump_a(tmp)
        ford = root / "20241101_Ford_Lotus_sofa nap"
        hand_move(root, "20241101_Ford_Lotus_sofa nap", "2024/20241101_Garden_sofa nap")
        moved = root / "2024" / "20241101_Kitchen_sofa nap"
        moved.mkdir()
        (root / "2024/20241101_Garden_sofa nap/IMG_0102.jpg").rename(moved / "IMG_0102.jpg")
        twin = root / "2024" / "20241102_Old Pier_harbour walk"
        twin.mkdir()
        (twin / "IMG_0201.jpg").write_bytes((root / HARBOUR_DAY / "IMG_0201.jpg").read_bytes())
        wb = later_dump(tmp)
        code, out, _ = ix.run("fix-plan", wb)
    return (code == 0 and "(R6)" not in out and not ford.exists()
            and "no folder holds more than half of its copies" in out
            and "a copy is in 2+ folders" in out), f"code={code} out={out[-700:]!r}"


@case
def r6_wins_over_r1_on_the_same_folder():
    """GUARD (ADR 0001). The landmark lookup names dump-b's batch Pier Lane
    (R1) and the owner named the spot Old Pier (R6): only R6 is offered."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        _wa, _pack, root = copied_dump_a(tmp)
        hand_move(root, HARBOUR_DAY, PIER_DAY)
        wb = later_dump(tmp)
        doc = json.loads((wb / "batches.json").read_text())
        doc["batches"][0]["place"] = "Pier Lane"
        (wb / "batches.json").write_text(json.dumps(doc))
        code, out, _ = ix.run("fix-plan", wb)
        got = rows(wb)
    return (code == 3 and len(got) == 1 and "(R6)" in got[0]
            and "Pier Lane" not in out.split("## Refused")[0]), f"rows={got}"


@case
def an_r6_dry_run_writes_nothing():
    """GUARD (Lead). `fix-plan --answers` without --go on an R6 row: both
    work dirs, the pack and the tree keep their bytes and mtimes."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wa, pack, root = copied_dump_a(tmp)
        hand_move(root, HARBOUR_DAY, PIER_DAY)
        wb = later_dump(tmp)
        ix.run("freeze", wb)
        answer(wb, "ok")
        before = state(wa, wb, pack, root)
        code, out, _ = apply(wb, go=False)
        after = state(wa, wb, pack, root)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    return code == 0 and "DRY RUN" in out and not changed, f"changed={changed}"


@case
def the_fix_plan_stop_is_exit_3():
    return photo_index.EXIT_FIX_PLAN == 3, f"{photo_index.EXIT_FIX_PLAN}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args()
    failed = []
    for fn in CASES:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        name = fn.__name__.replace("_", " ")
        print(f"  {'ok  ' if ok else 'FAIL'}  {name.ljust(70)}"
              + (f" {detail}" if (args.v or not ok) else ""))
        if not ok:
            failed.append(fn.__name__)
    print(f"\n{len(CASES) - len(failed)}/{len(CASES)} fix_plan cases passed"
          + (f" — FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
