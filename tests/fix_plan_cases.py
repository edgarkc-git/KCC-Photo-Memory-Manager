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
def a_look_inside_a_longer_what_gets_an_r3_row():
    """⭐ C-18 / G35 REPRODUCTION. Lotus's look is `sofa` and the folder's
    [what] is `sofa nap`: the piece holding the look gets an R3 row and `ok`
    drops it. ⛔ FAILS on 7280c54: R3 matched a whole piece only, so a look
    inside a longer [what] kept its place next to the named pet."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack = ready(tmp)
        add_look(pack, "subj-0001", "sofa", wd)
        ix.run("fix-plan", wd)
        got = [x for x in rows(wd) if "(R3)" in x]
        answer(wd, *["ok" if "(R3)" in x else "skip" for x in rows(wd)])
        acode, aout, aerr = apply(wd)
        must(ix.run("render", wd), "render")
        n = names(tmp)
    return (len(got) == 1 and "drops sofa nap: a look of Lotus" in got[0]
            and acode == 0 and n["F001"] == "20241101_Ford_Lotus"), \
        f"rows={got} apply={acode} {(aout + aerr)[-300:]!r} names={n}"


@case
def a_confirmed_pet_missing_from_an_agent_name_gets_an_r2_row():
    """⭐ C-18 / G35 REPRODUCTION (an agent-named folder). An approved agent row named
    F001 without Lotus, who is confirmed on its viewed photo: Review folders
    offers an R2 row adding Lotus, and `ok` names the folder with her. ⛔
    FAILS on 7280c54: R2 looked only at folders merged into an existing one."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        must(ix.run("fix-plan", wd, "--agent", "F001", "--to", "20241101_Ford_morning",
                    "--reason", "the morning"), "agent")
        ix.run("fix-plan", wd)
        answer(wd, *["ok" if "(agent)" in x else "skip" for x in rows(wd)])
        must(apply(wd), "apply agent")
        must(ix.run("render", wd), "render")
        ix.run("fix-plan", wd)
        got = [x for x in rows(wd) if "(R2)" in x]
        answer(wd, *["ok" if "(R2)" in x else "skip" for x in rows(wd)])
        acode, aout, aerr = apply(wd)
        must(ix.run("render", wd), "render")
        n = names(tmp)
    return (len(got) == 1 and "`20241101_Ford_morning` → `20241101_Ford_Lotus_morning`" in got[0]
            and acode == 0 and n["F001"] == "20241101_Ford_Lotus_morning"), \
        f"rows={got} apply={acode} {(aout + aerr)[-300:]!r} names={n}"

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

def map_ready(tmp):
    """`ready` with a pack that names no frequent place: Harbour is a map
    word, which R1 may offer to replace (OR-2)."""
    ix.make_pack(tmp, places=[])
    return ready(tmp)


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
            wd, _pack = map_ready(tmp)
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
def an_owner_word_on_a_trip_row_may_name_three_places():
    """⭐ G63 (owner ruling 20261024) REPRODUCTION. The owner's word on an R5 row is
    the whole place part of the trip name: three places are taken as the
    name grammar takes them, and the trip renders with all three. A word the
    grammar refuses (a coordinate) writes nothing. ⛔ FAILS on 4f1cd10: the
    word went through make-trip's two --where words and was refused (D3)."""
    batches = [dict(b, day_type="OVERSEAS", country_word="Ruritania")
               for b in ix.G3_BATCHES]
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, batches=batches)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        ix.run("fix-plan", wd)
        answer(wd, *["word: Lotus Bay+25.03,121.56" if "(R5)" in x else "skip"
                     for x in rows(wd)])
        bcode, bout, _b = apply(wd)
        ix.run("fix-plan", wd)
        answer(wd, *["word: Lotus Bay+Birk Falls+Old Pier" if "(R5)" in x else "skip"
                     for x in rows(wd)])
        acode, aout, aerr = apply(wd)
        must(ix.run("render", wd), "render")
        trips = [fo["rendered"] for fo in ix.index_of(tmp)[0]["folders"]
                 if fo["kind"] == "trip" and fo["status"] != "retired"]
    return (bcode != 0 and acode == 0
            and trips == ["20241101-1102_Ruritania_Lotus Bay+Birk Falls+Old Pier"]), \
        f"bad={bcode} {bout[-200:]!r} apply={acode} {(aout + aerr)[-300:]!r} trips={trips}"


@case
def a_trip_row_says_when_its_place_word_is_a_stay():
    """G61 on R5: a trip whose place word is a stay says so in its reason,
    so the owner can give their own word. ⛔ FAILS on 4f1cd10 (no reason)."""
    batches = [dict(ix.G3_BATCHES[0], day_type="OVERSEAS", country_word="Ruritania",
                    place="Lotus Inn", place_kinds={"Lotus Inn": "stay"}),
               dict(ix.G3_BATCHES[1], day_type="OVERSEAS", country_word="Ruritania")]
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, batches=batches)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        ix.run("fix-plan", wd)
        r5 = [x for x in rows(wd) if "(R5)" in x]
    return (len(r5) == 1 and "Lotus Inn is a place to stay" in r5[0]), f"{r5}"

@case
def an_owner_word_on_an_agent_row_names_the_folder_after_the_grammar():
    """⭐ G63 / C-21 REPRODUCTION. On an agent row the owner's word is the
    whole folder name: one the grammar refuses is refused for that row and
    nothing changes; a valid one names the folder. ⛔ FAILS on 7280c54: an
    agent row took `ok` or `skip` only."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        must(ix.run("fix-plan", wd, "--agent", "F002", "--to", "20241102_Harbour_old pier",
                    "--reason", "the pier"), "agent")
        ix.run("fix-plan", wd)
        answer(wd, *["word: Harbour walk day" if "(agent)" in x else "skip" for x in rows(wd)])
        bcode, bout, _b = apply(wd)
        ix.run("fix-plan", wd)
        answer(wd, *["word: 20241102_Harbour_old boats" if "(agent)" in x else "skip"
                     for x in rows(wd)])
        acode, aout, aerr = apply(wd)
        must(ix.run("render", wd), "render")
        n = names(tmp)
    return ("not a folder name this engine can use" in bout and acode == 0
            and n["F002"] == "20241102_Harbour_old boats"), \
        f"bad={bcode} {bout[-300:]!r} apply={acode} {(aout + aerr)[-300:]!r} names={n}"

@case
def a_failed_landmark_lookup_is_said_and_never_offered():
    """GUARD (A1's flag). A batch flagged `landmark_lookup_failed` gets no
    row to answer: the plan lists it as refused, saying to type the place,
    and the freeze goes on."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = map_ready(tmp)
        landmark_later(wd, flags=["landmark_lookup_failed"])
        code, out, _ = ix.run("fix-plan", wd)
        fcode, fout, _ = ix.run("freeze", wd)
    return (code == 0 and "## Refused" in out and "landmark lookup failed" in out
            and "set-where" in out and fcode == 0
            and "landmark lookup failed" in fout), \
        f"code={code} out={out[-500:]!r} freeze={fcode} {fout[-300:]!r}"



@case
def an_owners_frequent_place_is_never_replaced_by_a_landmark():
    """⭐ REPRODUCTION (owner run OR-2). ⛔ FAILS on 43ca589: F002's place is
    the pack's frequent place (fsl-0001, the owner's own word) and R1
    offered the map landmark over it. An owner word beats a landmark: no
    row."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready(tmp)
        refs = [r["ref"] for r in ix.index_of(tmp)[0]["folders"][1]["where"]]
        landmark_later(wd)
        code, out, _ = ix.run("fix-plan", wd)
    return (refs == ["fsl-0001"] and code == 0
            and photo_index.NOTHING_TO_CHANGE in out), f"refs={refs} code={code} {out[-400:]!r}"


@case
def an_r1_skip_holds_when_only_the_what_changes():
    """⭐ REPRODUCTION (owner run OR-11). ⛔ FAILS on 43ca589: R1's answer
    was keyed on the whole new name, so a `skip` was asked again once the
    folder's [what] changed. The key is the folder and the proposed place:
    after `set-what`, the freeze asks nothing."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = map_ready(tmp)
        landmark_later(wd)
        code, _o, _ = ix.run("freeze", wd)
        r1 = rows(wd)
        answer(wd, "skip")
        must(apply(wd), "apply skip")
        must(ix.run("group", "set-what", wd, "F002", "pier walk", "--reason",
                    "the owner's words"), "set-what")
        must(ix.run("render", wd), "render")
        must(ix.run("check", wd), "check")
        fcode, fout, ferr = ix.run("freeze", wd)
        name = names(tmp)["F002"]
    return (code == 3 and len(r1) == 1 and "(R1) · F002 ·" in r1[0] and fcode == 0
            and name == "20241102_Harbour_pier walk"), \
        f"code={code} r1={r1} freeze={fcode} {(fout + ferr)[-400:]!r} name={name}"


@case
def an_agent_row_on_a_leg_names_the_leg():
    """⭐ REPRODUCTION (owner run OR-10). ⛔ FAILS on 43ca589: an agent
    RENAME on a trip leg was stored and logged on `ok`, but render named the
    leg from its places as before. Render now uses it, as for a day
    folder."""
    import index_group_cases as g
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = g.ready(tmp, min_visits=3)
        must(g.trip(wd), "make-trip")
        g.render(wd)
        leg = next(fo for fo in g.folders(tmp).values()
                   if fo["kind"] == "leg" and fo["rendered"] == "1025_Ashford")
        must(ix.run("fix-plan", wd, "--agent", leg["id"], "--to", "1025_Ashford Bay",
                    "--reason", "the bay"), "agent row")
        must(ix.run("check", wd), "check")
        code, _o, _e = ix.run("freeze", wd)
        got = rows(wd)
        answer(wd, *["ok" if "(agent)" in r else "skip" for r in got])
        acode, aout, _ = apply(wd)
        g.render(wd)
        now = g.folders(tmp)[leg["id"]]["rendered"]
    return (code == 3 and any("(agent) · %s ·" % leg["id"] in r for r in got)
            and acode == 0 and now == "1025_Ashford Bay"), \
        f"code={code} rows={got} apply={acode} {aout[-300:]!r} now={now}"

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
    in F001, is then missing from that folder's name: Review folders asks
    nothing about it (G47, information only) and the final check offers it."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        old_photo = owner_folder(tmp)
        wd, _pack = ready(tmp)
        code, _o, _ = ix.run("freeze", wd)
        r4 = rows(wd)
        answer(wd, "ok")
        must(apply(wd), "apply R4")
        must(ix.run("render", wd), "render")
        must(ix.run("check", wd), "check")
        fcode, fout, ferr = ix.run("freeze", wd)
        run = fin.finish(wd)
        landed = sorted(p.name for p in old_photo.parent.iterdir())
        still = old_photo.parent.is_dir()
        later = owner_row(wd)
    return (code == 3 and len(r4) == 1 and f"(R4) · F001 · `{LOTUS_DAY}` → `{OLD}`" in r4[0]
            and "merges into the existing folder" in r4[0]
            and fcode == 0 and "After the copy: Your folder `20241101_Old trip`: the "
            "final check offers to add Lotus after the copy." in fout and still
            and run.returncode == 3 and "IMG_0101.jpg" in landed
            and "OLD_0001.jpg" in landed and len(later) == 1
            and f"`{OLD}` → `{OLD}_Lotus`" in later[0]), \
        (f"code={code} r4={r4} freeze={fcode} {fout[-300:]!r}{ferr[-300:]!r} "
         f"finish={run.returncode} landed={landed} later={later}")


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
        fcode, fout, ferr = ix.run("freeze", wd)
        run = fin.finish(wd)
        landed = sorted(p.name for p in old_photo.parent.iterdir())
    return (ccode == 0 and fcode == 0 and run.returncode == 3
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


ONE_BATCH = [{"batch": 1, "from": "2024-11-01", "to": "2024-11-02", "place": "Ford"}]


def per_day(tmp, owners, rel_pets=False):
    """A one-batch, two-day dump (F001 holds 2024-11-01 and 11-02) and the
    owner's dated folders `owners` {rel: capture day}. -> (wd, rows, code)."""
    for rel, day in owners.items():
        owner_folder(tmp, day=day, rel=rel)
    wd, pack = ix.g3_dump(tmp, batches=ONE_BATCH)
    if rel_pets:
        reg = pack / "photo-subjects" / "subjects.json"
        data = json.loads(reg.read_text())
        data["subjects"].append(ix.subject("subj-0003", "Birk"))
        reg.write_text(json.dumps(data))
    for cmd in ("init", "render", "check"):
        must(ix.run(cmd, wd), cmd)
    code, _o, _e = ix.run("freeze", wd)
    return wd, rows(wd), code


def to_the_copy(wd, *answers):
    """Answer the open rows, apply, and run until the copy (R2 rows: skip).
    -> (apply out, freeze code, finish)."""
    answer(wd, *answers)
    aout = must(apply(wd), "apply R4")
    for _ in range(3):
        must(ix.run("render", wd), "render")
        must(ix.run("check", wd), "check")
        fcode, _f, ferr = ix.run("freeze", wd)
        if fcode != 3:
            break
        answer(wd, *["skip"] * len(rows(wd)))
        must(apply(wd), "apply")
    return aout, (fcode, ferr), fin.finish(wd)


def landed(tmp, rel):
    d = Path(tmp).resolve() / "sorted" / rel
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


def new_folders(tmp, *skip):
    root = Path(tmp).resolve() / "sorted"
    return {p.parent.relative_to(root).as_posix(): None for p in root.rglob("IMG_*")
            if not any(p.is_relative_to(root / s) for s in skip)}


@case
def only_one_day_with_a_folder_moves_that_day_and_the_rest_stays():
    """⭐ REPRODUCTION (UAT5 U5-1, G42). ⛔ FAILS on d5201b6: R4 asked only
    when EVERY day of the folder sat in one existing folder, so the owner's
    2024-11-01 folder got nothing and that day was copied into the new
    two-day folder beside it. Now a DAYS-INTO-EXISTING row moves that day's
    photos into the owner's folder and 2024-11-02 stays in the new one."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, r4, code = per_day(tmp, {OLD: "2024:11:01 09:00:00"})
        aout, (fcode, ferr), run = to_the_copy(wd, "ok")
        mine = landed(tmp, OLD)
        rest = new_folders(tmp, OLD)
    want = f"DAYS-INTO-EXISTING (R4) · F001 · `2024-11-01` → `{OLD}`"
    return (code == 3 and len(r4) == 1 and want in r4[0] and "2 photo(s)" in r4[0]
            and fcode == 0 and run.returncode == 3
            and {"IMG_0101.jpg", "IMG_0102.jpg", "OLD_0001.jpg"} <= set(mine)
            and "IMG_0201.jpg" not in mine and len(rest) == 1), \
        (f"code={code} r4={r4} apply={aout[-300:]!r} freeze={fcode} {ferr[-300:]!r} "
         f"finish={run.returncode} {run.stdout[-300:]!r} mine={mine} rest={rest}")


@case
def the_later_day_alone_with_a_folder_moves_and_the_first_stays():
    """⭐ REPRODUCTION (G42, the moved day is not the batch's first). ⛔ FAILS
    on d5201b6: no row. Now 2024-11-02 goes into the owner's folder; the new
    folder keeps 2024-11-01."""
    rel = "2024/20241102_Day out"
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, r4, code = per_day(tmp, {rel: "2024:11:02 09:00:00"})
        _aout, (fcode, ferr), run = to_the_copy(wd, "ok")
        mine = landed(tmp, rel)
        rest = new_folders(tmp, rel)
    return (code == 3 and len(r4) == 1 and "`2024-11-02` → `" in r4[0]
            and fcode == 0 and run.returncode == 3 and "IMG_0201.jpg" in mine
            and "IMG_0101.jpg" not in mine and len(rest) == 1
            and all(k.split("/")[-1].startswith("20241101") for k in rest)), \
        f"r4={r4} freeze={fcode} {ferr[-300:]!r} finish={run.returncode} mine={mine} rest={rest}"


@case
def two_days_in_two_owner_folders_apply_one_after_the_other():
    """⭐ REPRODUCTION (G42). ⛔ FAILS on d5201b6: the days sit in two
    different owner folders, so no row was made. Two rows, both `ok`: each
    moves its own day, the second after the first changed the folder."""
    a, b = "2024/20241101_Old trip", "2024/20241102_Day out"
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, r4, code = per_day(tmp, {a: "2024:11:01 09:00:00", b: "2024:11:02 09:00:00"})
        aout, (fcode, ferr), run = to_the_copy(wd, "ok", "ok")
        in_a, in_b = landed(tmp, a), landed(tmp, b)
    return (code == 3 and len(r4) == 2 and fcode == 0 and run.returncode in (0, 3)
            and "IMG_0101.jpg" in in_a and "IMG_0201.jpg" in in_b
            and "IMG_0201.jpg" not in in_a), \
        f"r4={r4} apply={aout[-400:]!r} freeze={fcode} {ferr[-300:]!r} a={in_a} b={in_b}"


@case
def a_per_day_move_into_a_folder_named_after_another_pet_passes_e48():
    """GUARD (E48 on the per-day path): the owner's folder is named after
    Birk, whom no photo of this dump shows; the moved day arrives there as an
    override, and the existing name keeps its pets — check, freeze and the
    copy pass."""
    rel = "2024/20241101_Old trip_Birk"
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, r4, _code = per_day(tmp, {rel: "2024:11:01 09:00:00"}, rel_pets=True)
        _aout, (fcode, ferr), run = to_the_copy(wd, "ok")
        mine = landed(tmp, rel)
    return (len(r4) == 1 and fcode == 0 and run.returncode == 3
            and "IMG_0101.jpg" in mine), \
        f"r4={r4} freeze={fcode} {ferr[-300:]!r} finish={run.returncode} {run.stdout[-300:]!r}"


@case
def a_per_day_answer_never_stands_for_other_days():
    """GUARD (G42): a per-day row's key carries its days, so a `skip` for
    2024-11-01 is not an answer for 2024-11-01 + 11-02 into the same
    folder; the whole-folder key is unchanged."""
    op = {"rule": "R4", "folder": "F001", "op": "DAYS-INTO-EXISTING", "to": OLD}
    one = photo_index.fix_key(dict(op, **{"from": "2024-11-01"}))
    two = photo_index.fix_key(dict(op, **{"from": "2024-11-01, 2024-11-02"}))
    whole = photo_index.fix_key(dict(op, op="INTO-EXISTING", **{"from": "x"}))
    return one != two and whole == f"R4|F001|INTO-EXISTING|{OLD}", f"{one} {two} {whole}"


# ---------------------------------------------------------------------------
# G41 — the after-check offers to add the place to the OWNER's folder
# ---------------------------------------------------------------------------

DAY_OUT = "2024/20241102_Day out"
DAY_OUT_PLACE = "2024/20241102_Day out_Harbour"


def after_page(wd):
    return wd / "plan" / photo_index.AFTER_CHECK_MD


def answer_after(wd, *answers):
    lines, k = [], 0
    for line in after_page(wd).read_text().splitlines():
        if photo_index.AFTER_ROW.match(line):
            line = line.replace("answer: ______", f"answer: {answers[k]}")
            k += 1
        lines.append(line)
    after_page(wd).write_text("\n".join(lines) + "\n")


def merged_into_day_out(tmp, per_day=False):
    """The owner's `20241102_Day out` (no place) holds a 2024-11-02 photo; the
    engine found Harbour for that day. R4 `ok`, copied. -> (wd, finish)."""
    if per_day:
        wd, _r4, _code = per_day_dump(tmp)
    else:
        owner_folder(tmp, day="2024:11:02 09:00:00", rel=DAY_OUT)
        wd, _pack = ready(tmp)
        ix.run("freeze", wd)
    _aout, _f, run = to_the_copy(wd, "ok")
    return wd, run


def per_day_dump(tmp):
    return per_day(tmp, {DAY_OUT: "2024:11:02 09:00:00"})


def owner_row(wd):
    return [l for l in after_page(wd).read_text().splitlines()
            if photo_index.AFTER_ROW.match(l)]


@case
def an_r4_merge_into_an_owner_folder_with_no_place_offers_to_add_it():
    """⭐ REPRODUCTION (UAT5 U5-2, G41). ⛔ FAILS on d5201b6: the merge kept
    the owner's `20241102_Day out` and the place the engine found (Harbour)
    was lost. Now the after-check offers `RENAME (owner)` to
    `20241102_Day out_Harbour`; a dry run renames nothing; `ok` + --go
    renames the owner's folder with the size + SHA-256 + name proof (before
    = after), the copy record follows it, verify passes, and nothing is
    left."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, run = merged_into_day_out(tmp)
        rows0 = owner_row(wd)
        root = Path(tmp).resolve() / "sorted"
        answer_after(wd, "ok")
        tree0 = state(root)
        dcode, dout, _ = ix.run("after-check", wd, "--answers", after_page(wd))
        dry = state(root) == tree0
        gcode, gout, gerr = ix.run("after-check", wd, "--answers", after_page(wd), "--go")
        moved = (root / DAY_OUT_PLACE).is_dir() and not (root / DAY_OUT).exists()
        names = sorted(p.name for p in (root / DAY_OUT_PLACE).iterdir()) if moved else []
        vcode, _v, _ = ix.run("verify", wd, "--copied")
        ncode, nout, _ = ix.run("after-check", wd)
    want = f"1. RENAME (owner) · `{DAY_OUT}` → `{DAY_OUT_PLACE}` · "
    return (run.returncode == 3 and len(rows0) == 1 and want in rows0[0]
            and "adds Harbour" in rows0[0] and dcode == 0 and "would rename" in dout
            and dry and gcode == 0 and moved and "OLD_0001.jpg" in names
            and "IMG_0201.jpg" in names and "before 2 = after 2" in gout
            and vcode == 0 and ncode == 0 and "Nothing left to fix" in nout), \
        (f"finish={run.returncode} {run.stdout[-300:]!r} rows={rows0} dry={dcode} "
         f"{dout[-200:]!r} go={gcode} {gout[-300:]!r}{gerr[-200:]!r} moved={moved} "
         f"names={names} verify={vcode} next={ncode} {nout[-200:]!r}")


@case
def a_relock_after_the_owner_rename_follows_the_folder():
    """⭐ REPRODUCTION (G41 x re-lock). ⛔ FAILS on b960a5b: after the owner's
    folder took its place, the frozen index still named the old path, so a
    re-lock after a pack change (render, check, freeze) was refused — "the
    merge target is no longer a directory". The re-lock now follows the
    rename the after-check logged, and verify passes."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _run = merged_into_day_out(tmp)
        answer_after(wd, "ok")
        must(ix.run("after-check", wd, "--answers", after_page(wd), "--go"), "rename")
        ix.rename_lotus(Path(tmp) / "photo-memory" / ix.OWNER)
        stale, _s, _e = ix.run("verify", wd, "--copied")
        codes = [ix.run(cmd, wd) for cmd in ("render", "check", "freeze")]
        vcode, vout, _ = ix.run("verify", wd, "--copied")
        dest = next(fo["dest"]["existing_path"] for fo in ix.index_of(tmp)[0]["folders"]
                    if fo["dest"]["mode"] == "merge")
    return (stale == 6 and [c[0] for c in codes] == [0, 0, 0] and vcode == 0
            and dest.endswith(DAY_OUT_PLACE)), \
        (f"stale={stale} codes={[(c[0], (c[1] + c[2])[-200:]) for c in codes]} "
         f"verify={vcode} {vout[-200:]!r} dest={dest}")

@case
def a_per_day_merge_offers_the_place_of_the_merged_day():
    """⭐ REPRODUCTION (G41 on the G42 path). ⛔ FAILS on d5201b6. The day
    moved into the owner's folder brings ITS place (Harbour), not the two-day
    batch's."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, run = merged_into_day_out(tmp, per_day=True)
        rows0 = owner_row(wd)
    return (run.returncode == 3 and len(rows0) == 1
            and f"`{DAY_OUT}` → `{DAY_OUT_PLACE}`" in rows0[0]), f"rows={rows0}"


@case
def an_owner_folder_changed_since_the_scan_is_not_renamed():
    """GUARD (G41: refused if the folder changed since the scan). The owner
    adds a photo of their own after the copy: `ok` renames nothing, says why,
    and the tree is byte for byte as it was."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _run = merged_into_day_out(tmp)
        root = Path(tmp).resolve() / "sorted"
        Image.new("RGB", (8, 8), (1, 2, 3)).save(root / DAY_OUT / "MINE.jpg", "JPEG")
        answer_after(wd, "ok")
        before = state(root)
        code, out, _ = ix.run("after-check", wd, "--answers", after_page(wd), "--go")
        same = before == state(root)
    return (code == 1 and "changed since the engine looked at it" in out
            and "MINE.jpg" in out and same), f"code={code} same={same} {out[-300:]!r}"


@case
def a_home_is_never_added_to_an_owner_folder():
    """GUARD (G41: no home as a POI). The merged day was taken at the
    owner's home (the fixture's `Ford`): the owner row adds only the pet
    confirmed there (G47), never the home."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        owner_folder(tmp)
        wd, _pack = ready(tmp)
        ix.run("freeze", wd)
        _a, _f, run = to_the_copy(wd, "ok")
        got = owner_row(wd)
    return (run.returncode == 3 and len(got) == 1
            and f"`{OLD}` → `{OLD}_Lotus`" in got[0] and "Ford" not in got[0]), \
        f"finish={run.returncode} {got}"


@case
def a_folder_an_engine_copy_created_keeps_todays_path():
    """GUARD (G41: engine-created folders keep today's path). When a copy
    record lists the target folder as created by the engine, no owner row."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _run = merged_into_day_out(tmp)
        target = str(Path(tmp).resolve() / "sorted" / DAY_OUT)
        for sp in (wd / "plan").glob("execute-state_*.json"):
            doc = json.loads(sp.read_text())
            doc["created_dirs"] = sorted(set(doc.get("created_dirs") or []) | {target})
            sp.write_text(json.dumps(doc))
        ncode, nout, _ = ix.run("after-check", wd)
    return ncode == 0 and "(owner)" not in nout, f"{ncode} {nout[-300:]!r}"


@case
def an_owner_row_whose_name_fails_the_grammar_is_refused_out_loud():
    """GUARD (G41: the new name passes photo_name.validate). An owner name
    already at the length limit cannot take the place: the row is listed
    under Refused (the [who]+[what] hard cap), never offered."""
    long_rel = "2024/20241102_Day out_" + " ".join(["walk"] * 40)
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        owner_folder(tmp, day="2024:11:02 09:00:00", rel=long_rel)
        wd, _pack = ready(tmp)
        ix.run("freeze", wd)
        _a, _f, run = to_the_copy(wd, "ok")
        page = after_page(wd).read_text() if after_page(wd).is_file() else ""
    return (run.returncode == 0 and "## Refused (never applied)" in page
            and "(owner)" not in page and "_Harbour`" in page), \
        f"finish={run.returncode} {page[-600:]!r}"


# G47 — an owner's folder gaining confirmed pets is renamed at the final check
AT_HOME = "2024/20241101_At home"


def two_pets_at_home(tmp, rel=AT_HOME, day="2024:11:01 09:00:00",
                     pets=(("IMG_0101.jpg", "subj-0001"), ("IMG_0102.jpg", "subj-0003"))):
    """UAT6 U6-1: a two-day batch at home; 2024-11-01 holds Lotus and Birk
    (both confirmed) and the owner's `20241101_At home`. R4 per day `ok`.
    `pets` puts a confirmed pet on a photo. -> (wd, R4 rows, freeze after R4
    (code, out), finish)."""
    owner_folder(tmp, day=day, rel=rel)
    wd, pack = ix.g3_dump(tmp, seen=(), batches=ONE_BATCH)
    reg = pack / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text())
    data["subjects"].append(ix.subject("subj-0003", "Birk"))
    reg.write_text(json.dumps(data))
    base = Path(tmp).resolve() / "raw" / "dump-a"
    on = dict(pets)
    ix.write_see(wd, 1, [
        *(ix.see_label(base, n, [{"subject_id": on[n]}] if n in on else (), w)
          for n, w in (("IMG_0101.jpg", "sofa nap"), ("IMG_0102.jpg", "sofa nap"),
                       ("IMG_0201.jpg", "harbour walk"))),
        ix.see_label(base, ix.WORD, what="a document"),
        ix.see_label(base, ix.SHOT, what="a chat")])
    for cmd in ("init", "render", "check"):
        must(ix.run(cmd, wd), cmd)
    ix.run("freeze", wd)
    r4 = rows(wd)
    answer(wd, *["ok"] * len(r4))
    must(apply(wd), "apply R4")
    must(ix.run("render", wd), "render")
    must(ix.run("check", wd), "check")
    code, out, err = ix.run("freeze", wd)
    return wd, r4, (code, out + err), fin.finish(wd)


@case
def an_owner_folder_gaining_pets_is_renamed_at_the_final_check():
    """⭐ REPRODUCTION (UAT6 U6-1, G47). ⛔ FAILS on 3c6adb1: Review folders
    offered an R2 row `20241101_At home` → `…_Lotus+Birk` the owner could
    `ok`, and `--go` only said "rename it by hand". Now Review folders asks
    nothing about the owner's folder (the freeze passes and says the final
    check offers it); the final check offers `RENAME (owner)` with both
    pets; `ok` + --go renames it with before = after."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, r4, (fcode, fout), run = two_pets_at_home(tmp)
        got = owner_row(wd) if after_page(wd).is_file() else []
        root = Path(tmp).resolve() / "sorted"
        new = f"{AT_HOME}_Lotus+Birk"
        if got:
            answer_after(wd, "ok")
        gcode, gout, gerr = ix.run("after-check", wd, "--answers", after_page(wd), "--go")
        moved = (root / new).is_dir() and not (root / AT_HOME).exists()
    return (len(r4) == 1 and "DAYS-INTO-EXISTING" in r4[0] and fcode == 0
            and "After the copy: Your folder `20241101_At home`: the final check "
            "offers to add Lotus, Birk after the copy." in fout
            and "answer:" not in fout and "refused" not in fout and "⚠️" not in fout
            and run.returncode == 3 and len(got) == 1
            and f"1. RENAME (owner) · `{AT_HOME}` → `{new}` · " in got[0]
            and "adds Lotus, Birk" in got[0] and gcode == 0 and moved
            and "before 3 = after 3" in gout), \
        (f"r4={r4} freeze={fcode} {fout[-400:]!r} finish={run.returncode} "
         f"rows={got} go={gcode} {gout[-300:]!r}{gerr[-200:]!r} moved={moved}")


@case
def one_owner_row_adds_the_place_and_the_pet_together():
    """⭐ REPRODUCTION (G47 x G41). ⛔ FAILS on 3c6adb1 (the row added the
    place only). The merged 2024-11-02 brings its place (Harbour) and Birk,
    confirmed on its photo: ONE owner row adds both, it is offered (not
    refused), and `ok` + --go renames with before = after."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _r4, (fcode, _fout), run = two_pets_at_home(
            tmp, rel=DAY_OUT, day="2024:11:02 09:00:00",
            pets=(("IMG_0201.jpg", "subj-0003"),))
        page = after_page(wd).read_text() if after_page(wd).is_file() else ""
        got = owner_row(wd) if page else []
        new = f"{DAY_OUT}_Birk_Harbour"
        if got:
            answer_after(wd, "ok")
        gcode, gout, _ = ix.run("after-check", wd, "--answers", after_page(wd), "--go")
        moved = (Path(tmp).resolve() / "sorted" / new).is_dir()
    return (fcode == 0 and run.returncode == 3 and len(got) == 1
            and f"`{DAY_OUT}` → `{new}`" in got[0] and "adds Harbour" in got[0]
            and "adds Birk" in got[0] and "## Refused" not in page
            and gcode == 0 and moved and "before 2 = after 2" in gout), \
        f"freeze={fcode} finish={run.returncode} rows={got} go={gcode} {gout[-300:]!r}"

@case
def an_owner_folder_changed_after_the_copy_keeps_its_name():
    """GUARD (G47 with G41's proof). The owner adds a photo to their folder
    after the copy: `ok` renames nothing, says why, and the tree is as it
    was."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _r4, _f, _run = two_pets_at_home(tmp)
        root = Path(tmp).resolve() / "sorted"
        Image.new("RGB", (8, 8), (1, 2, 3)).save(root / AT_HOME / "MINE.jpg", "JPEG")
        answer_after(wd, "ok")
        before = state(root)
        code, out, _ = ix.run("after-check", wd, "--answers", after_page(wd), "--go")
        same = before == state(root)
    return (code == 1 and "changed since the engine looked at it" in out
            and "MINE.jpg" in out and same), f"code={code} same={same} {out[-300:]!r}"

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
    """⭐ REPRODUCTION (G47, Lead F4b). ⛔ FAILS on 9d99b05: an earlier dump
    whose copy record misses a row made an R2 row the owner could `ok`, and
    `--go` renamed nothing ("rename it by hand"). Now it is information
    under `## After the copy` — finish that copy first — the freeze asks
    nothing, and the tree is untouched."""
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
        before = ix.tree_state(sorted_root)
        fcode, fout, ferr = ix.run("freeze", wb)
        same = before == ix.tree_state(sorted_root)
    note = (f"After the copy: `{LOTUS_DAY}`: adds Birk — finish the copy of dump-a "
            "first; then Review folders offers the rename.")
    return (fcode == 0 and note in fout and "answer:" not in fout and same), \
        f"freeze={fcode} {fout[-500:]!r}{ferr[-200:]!r}"


@case
def a_merge_declared_by_hand_is_information_only():
    """⭐ REPRODUCTION (G47, Lead F4b). ⛔ FAILS on 9d99b05 (listed under
    "Refused (never applied)" with a ⚠️). The owner's folder is a `dest
    merge` typed by hand — no R4 scan, so the final check cannot prove a
    rename: Review folders lists it under `## After the copy` as a rename by
    hand, asks nothing, and nothing says refused."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        owner_folder(tmp)
        wd, _pack = ready(tmp)
        target = Path(tmp).resolve() / "sorted" / OLD
        # The dedupe reference: a work dir whose manifest holds no photo.
        ref = Path(tmp).resolve() / "ref"
        ref.mkdir()
        head = (wd / "manifest.csv").read_text(encoding="utf-8").splitlines()[0]
        (ref / "manifest.csv").write_text(head + "\n", encoding="utf-8")
        must(ix.run("dest", wd, "F001", "merge", target, "--ref", ref,
                    "--reason", "the owner's folder"), "dest")
        must(ix.run("render", wd), "render")
        must(ix.run("check", wd), "check")
        fcode, fout, ferr = ix.run("freeze", wd)
        _p, pout, _e = ix.run("fix-plan", wd)
    note = (f"After the copy: Your folder `20241101_Old trip`: adds Lotus — "
            f"{photo_index.BY_HAND}.")
    return (fcode == 0 and note in fout and "refused" not in fout and "⚠️" not in fout
            and "## After the copy" in pout and "## Refused" not in pout
            and "answer:" not in pout), f"freeze={fcode} {fout[-400:]!r}{ferr[-200:]!r} {pout[-400:]!r}"


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
    F001 and F002 as its legs; `word:` on R5 makes the trip at the owner's
    place word (G63); a dump at home gets no R5 row."""
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
            and word[2] == 0 and word[3] == ["20241101-1102_Ruritania_Somewhere"]
            and "(R5)" not in home_out), f"{got}"


@case
def a_trip_abroad_with_no_file_to_copy_gets_no_make_trip_row():
    """⭐ L-9 / G57 REPRODUCTION. The same two days abroad, every photo a
    twin already in the sorted tree: no MAKE-TRIP row. ⛔ FAILS on 7280c54:
    R5 offered a trip of "0 photo(s)", and once made it could never be named."""
    import shutil
    batches = [dict(b, day_type="OVERSEAS", country_word="Ruritania")
               for b in ix.G3_BATCHES]
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, batches=batches)
        old = Path(tmp) / "sorted" / "20241101_earlier"
        old.mkdir(parents=True)
        for src in (Path(tmp).resolve() / "raw" / "dump-a").iterdir():
            shutil.copyfile(src, old / src.name)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        _c, out, _e = ix.run("fix-plan", wd)
        r5 = [x for x in rows(wd) if "(R5)" in x] if (wd / "plan").exists() else []
    return ("(R5)" not in out and r5 == []), f"r5={r5} out={out[-300:]!r}"

@case
def a_folder_named_after_a_stay_or_an_eatery_gets_an_r1_row():
    """⭐ G61 REPRODUCTION (C-18). Batch 1's only place word is an inn, batch
    2's an eatery beside a sight (cluster's `place_kinds`): each folder gets
    an R1 row. `ok` drops the eatery and keeps the sight; the inn's row takes
    the owner's word (`ok` alone is refused). ⛔ FAILS on 7280c54: no row, the
    names went to the owner as they were."""
    batches = [dict(ix.G3_BATCHES[0], place="Lotus Inn", place_kinds={"Lotus Inn": "stay"}),
               dict(ix.G3_BATCHES[1], place="Birk Cafe+Harbour",
                    place_kinds={"Birk Cafe": "eatery"})]
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, batches=batches)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        ix.run("fix-plan", wd)
        r1 = [x for x in rows(wd) if "(R1)" in x]
        answer(wd, *["ok" for _ in rows(wd)])
        _c, refused, _e = apply(wd, go=False)
        ix.run("fix-plan", wd)
        answer(wd, *["word: Old Quarter" if "Lotus Inn" in x else
                     "ok" if "(R1)" in x else "skip" for x in rows(wd)])
        acode, aout, aerr = apply(wd)
        must(ix.run("render", wd), "render")
        names = sorted(fo["rendered"] for fo in ix.index_of(tmp)[0]["folders"]
                       if fo["kind"] == "day" and fo.get("rendered"))
    inn = [x for x in r1 if "Lotus Inn" in x]
    cafe = [x for x in r1 if "Birk Cafe" in x]
    return (len(inn) == 1 and "a place to stay" in inn[0]
            and len(cafe) == 1 and "a restaurant or cafe" in cafe[0]
            and "takes your own place word" in refused and acode == 0
            and any(n.startswith("20241101_Old Quarter") for n in names)
            and any(n.startswith("20241102_Harbour") for n in names)), \
        f"r1={r1} refused={refused[-200:]!r} apply={acode} {(aout + aerr)[-300:]!r} names={names}"

@case
def a_folder_named_after_a_minor_marker_gets_an_r1_street_row():
    """GUARD (S-2). The kind cluster now gives a plain memorial stone
    (`street`) reaches Review folders as an R1 row with the kind reason."""
    batches = [dict(ix.G3_BATCHES[0], place="Lotus Stone",
                    place_kinds={"Lotus Stone": "street"}), ix.G3_BATCHES[1]]
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, batches=batches)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        ix.run("fix-plan", wd)
        r1 = [x for x in rows(wd) if "(R1)" in x and "Lotus Stone" in x]
    return (len(r1) == 1 and "a street or street marker" in r1[0]), f"r1={r1}"


@case
def days_inside_an_existing_trip_go_into_it_and_no_second_row_is_offered():
    """⭐ G62 / L-2 + L-8 REPRODUCTION. Two days abroad fall inside an
    existing trip folder (`20241030-1105_...`, a leg per day) in the sorted
    tree: each day folder gets an INTO-EXISTING row into its leg, no
    MAKE-TRIP row is offered, and the agent row naming F001 (which cannot
    apply once F001 goes into the trip) is listed as refused, not offered
    beside it; `ok` on
    every row applies. ⛔ FAILS on 7280c54: R5 offered a new trip for days
    the owner's trip already holds, and both rows for F001 were offered."""
    batches = [dict(b, day_type="OVERSEAS", country_word="Ruritania")
               for b in ix.G3_BATCHES]
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, batches=batches)
        trip = Path(tmp) / "sorted" / "2024" / "20241030-1105_Ruritania_Ford"
        for leg, name in (("1101_Ford", "OLD_A.jpg"), ("1102_Harbour", "OLD_B.jpg")):
            (trip / leg).mkdir(parents=True)
            note = name.encode()
            (trip / leg / name).write_bytes(
                b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
                + b"\xff\xfe" + (len(note) + 2).to_bytes(2, "big") + note + b"\xff\xd9")
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        must(ix.run("fix-plan", wd, "--agent", "F001", "--to", "20241101_Ford_morning",
                    "--reason", "the morning"), "agent")
        ix.run("fix-plan", wd)
        got = rows(wd)
        listed = "cannot apply beside it" in page(wd).read_text()
        answer(wd, *["ok" for _ in got])
        acode, aout, aerr = apply(wd)
    into = [x for x in got if "INTO-EXISTING (R4)" in x]
    return (len(into) == 2
            and any("F001" in x and "20241030-1105_Ruritania_Ford/1101_Ford`" in x for x in into)
            and any("F002" in x and "20241030-1105_Ruritania_Ford/1102_Harbour`" in x for x in into)
            and not [x for x in got if "MAKE-TRIP" in x]
            and not [x for x in got if "(agent) · F001" in x] and listed
            and acode == 0), f"rows={got} listed={listed} apply={acode} {(aout + aerr)[-300:]!r}"

# ---------------------------------------------------------------------------
# R6 — the owner's own place word for the same spot
# ---------------------------------------------------------------------------

HARBOUR_DAY = "20241102_Harbour_harbour walk"
PIER_DAY = "2024/20241102_Old Pier_harbour walk"


def later_dump(tmp, gps=ix.FAR, day="2024:11:05", place="Harbour", name="dump-b"):
    """A later dump of the same collection: two photos at `gps` on `day`,
    labelled `pier walk`, initialised, rendered and checked. -> work dir."""
    base = Path(tmp).resolve() / "raw" / name
    base.mkdir(parents=True)
    rows = []
    for k, file in enumerate(("IMG_0501.jpg", "IMG_0502.jpg")):
        (base / file).write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
                                  + f"{name}/{file}".encode() + b"\xff\xd9")
        rows.append(ix.row(file, SourceFile=str(base / file),
                           when=f"{day} 1{k}:00:00", gps=gps))
    iso = day.replace(":", "-")
    wd = ix.make_dump(tmp, rows=rows, name=name, batches=[
        {"batch": 1, "from": iso, "to": iso, "place": place}])
    ix.write_see(wd, 1, [ix.see_label(base, n, what="pier walk")
                         for n in ("IMG_0501.jpg", "IMG_0502.jpg")])
    for cmd in ("init", "render", "check"):
        must(ix.run(cmd, wd), f"{cmd} {name}")
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
def two_owner_words_at_one_spot_the_latest_frozen_dump_wins():
    """GUARD (Lead, the tie). dump-a's folder became `Old Pier`, dump-c's
    `Pier End`, both at the same spot. dump-a was frozen LATER (its name sorts
    first): its word is offered — the freeze time decides, the name only when
    no freeze time is known."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        _wa, pack, root = copied_dump_a(tmp)
        hand_move(root, HARBOUR_DAY, PIER_DAY)
        wc = later_dump(tmp, name="dump-c")
        ix.run("freeze", wc)
        answer(wc, *["skip"] * len(rows(wc)))
        must(apply(wc), "skip c")
        must(ix.run("freeze", wc), "freeze c")
        if fin.finish(wc).returncode:
            raise RuntimeError("finish c")
        hand_move(root, "20241105_Harbour_pier walk", "2024/20241105_Pier End_pier walk")
        index_a = ix.index_of(tmp, "dump-a")[2] / "index.json"
        doc = json.loads(index_a.read_text())
        doc["frozen"]["at"] = "2099-01-01 00:00"
        index_a.write_text(json.dumps(doc))
        wd = later_dump(tmp, day="2024:11:07", name="dump-d")
        _c, out, _ = ix.run("fix-plan", wd)
        got = [r for r in rows(wd) if "(R6)" in r]
    return (len(got) == 1 and "`20241107_Old Pier_pier walk`" in got[0]
            and f"in {PIER_DAY}" in got[0]), f"rows={got} out={out[-400:]!r}"


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
