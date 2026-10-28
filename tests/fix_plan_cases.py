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
import photo_execute  # noqa: E402
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
def a_day_moved_into_a_wider_owner_folder_keeps_its_name_l13():
    """⭐ REPRODUCTION (M17 / L-13, G2 shape). ⛔ FAILS on 73b3731: the
    owner's folder spans 2024-10-30 to 11-02 and is named after Birk, whom no
    photo of this dump shows; one day of a two-day batch moves into it as an
    override, and photo_plan judged that EXISTING name as its own: the period
    against the one day it receives, and Birk against the one moved file.
    The name is on the drive already: freeze and the copy pass."""
    rel = "2024/20241030-1102_Day out_Birk"
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, r4, _code = per_day(tmp, {rel: "2024:11:02 09:00:00"}, rel_pets=True)
        _aout, (fcode, ferr), run = to_the_copy(wd, "ok")
        mine = landed(tmp, rel)
    return (len(r4) == 1 and "`2024-11-02` → `" in r4[0] and fcode == 0
            and run.returncode == 3 and "IMG_0201.jpg" in mine
            and "IMG_0101.jpg" not in mine), \
        f"r4={r4} freeze={fcode} {ferr[-500:]!r} finish={run.returncode} {run.stdout[-300:]!r} mine={mine}"


@case
def only_an_existing_folder_override_is_marked_as_a_merge():
    """Guard (L-13): `unit_plan` marks an override `merge` only when its
    folder is an existing one; a new folder, a new leg of an existing trip
    and a leg stay unmarked, so photo_plan still judges their names."""
    def fo(fid, mode, kind="day", **extra):
        return {"id": fid, "kind": kind, "dest": dict({"mode": mode}, **extra)}
    top = fo("F1", "new")
    heads = [fo("F2", "merge"), fo("F3", "new"),
             fo("F4", "merge", **{photo_index.NEW_LEG: True}), fo("F5", "new", kind="leg")]
    unit = {"top": top, "batches": [1], "legs": [],
            "overrides": [([f"2024-11-0{k}"], h) for k, h in enumerate(heads, 2)]}
    paths = {h["id"]: f"/sorted/{h['id']}" for h in [top] + heads}
    plan = photo_index.unit_plan(unit, 1, paths)
    marked = [o["dest"].rsplit("/", 1)[1] for o in plan["overrides"] if o.get("merge")]
    return marked == ["F2"], f"marked={marked}"


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



MISNAMED = "2024/20241105_Old trip"


def g79_flow(tmp, word_answer, change_after_copy=False):
    """L-16 / G79: day 2024-11-01 merges (R4 ok) into the owner's folder named
    `20241105_…`, whose period the name check refuses. The freeze passes and
    points at the row; unfreeze, answer the NAME-CHECK row `word_answer`,
    re-lock, copy, and (if any) answer the final check's name row `ok`.
    -> dict of what each step said and what is on the drive."""
    owner_folder(tmp, rel=MISNAMED)
    wd, _pack = ready(tmp)
    ix.run("freeze", wd)
    answer(wd, *["ok" for _ in rows(wd)])
    must(apply(wd), "apply R4")
    for cmd in ("render", "check"):
        must(ix.run(cmd, wd), cmd)
    first = ix.run("freeze", wd)
    must(ix.run("unfreeze", wd, "--reason", "answer the name check"), "unfreeze")
    ix.run("fix-plan", wd)
    got = rows(wd)
    answer(wd, *[word_answer for _ in got])
    applied = apply(wd)
    for cmd in ("render", "check"):
        must(ix.run(cmd, wd), cmd)
    second = ix.run("freeze", wd)
    run = fin.finish(wd)
    root = Path(tmp).resolve() / "sorted"
    if change_after_copy:
        (root / MISNAMED / "OLD_0002.jpg").write_bytes(b"added by hand")
    page = after_page(wd).read_text() if after_page(wd).is_file() else ""
    lines = [ln for ln in page.splitlines() if ln.rstrip().endswith("answer: ______")]
    if lines:
        answer_after(wd, *["ok" if "(name check)" in ln else "skip" for ln in lines])
    after = ix.run("after-check", wd, "--answers", after_page(wd), "--go") \
        if lines else (0, "", "")
    return {"first": first, "rows": got, "applied": applied, "second": second,
            "page": page, "after": after,
            "drive": sorted(p.name for p in (root / "2024").iterdir())}


@case
def a_name_check_row_answered_ok_keeps_the_name_and_silences_the_line():
    """⭐ L-16 / G79 REPRODUCTION, `ok`. The NAME CHECK on a merge into an
    existing folder was a report-only line at the freeze (5 on Liked G2).
    It is a Review folders row: the first freeze is NOT stopped by it and
    points at it; `ok` keeps the name and the next freeze says "answered:
    kept" instead of the line. ⛔ FAILS on 3c5eb76: no row."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        got = g79_flow(tmp, "ok")
    second = got["second"][1] + got["second"][2]
    return (got["first"][0] == 0 and "row NAME-CHECK F001" in got["first"][1]
            and len(got["rows"]) == 1 and "NAME-CHECK (G75) · F001" in got["rows"][0]
            and got["applied"][0] == 0 and got["second"][0] == 0
            and "answered: kept `20241105_Old trip`" in second
            and "NAME CHECK FAILED" not in second
            and "(name check)" not in got["page"]
            and "20241105_Old trip" in got["drive"]), f"{got}"


@case
def a_name_check_row_answered_with_a_word_renames_after_the_copy():
    """⭐ L-16 / G79 REPRODUCTION, `word:`. The owner's name for the EXISTING
    folder is renamed only by the final check after the copy, through G41's
    proof, and it replaces the engine's own row for that folder."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        got = g79_flow(tmp, "word: 20241101-1105_Old trip")
    rows_after = [ln for ln in got["page"].splitlines() if "RENAME (" in ln]
    return (got["applied"][0] == 0 and got["second"][0] == 0
            and "becomes `20241101-1105_Old trip` at the final check" in got["second"][1]
            and len(rows_after) == 1 and "RENAME (name check)" in rows_after[0]
            and got["after"][0] == 0
            and got["drive"] == ["20241101-1105_Old trip"]), f"{got}"


@case
def a_skipped_name_check_row_keeps_todays_line_and_never_blocks():
    """⭐ L-16 / G79 REPRODUCTION, `skip`. A skipped row keeps today's line at
    the freeze, and the freeze never stops for it."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        got = g79_flow(tmp, "skip")
    second = got["second"][1] + got["second"][2]
    return (len(got["rows"]) == 1 and got["second"][0] == 0
            and "NAME CHECK FAILED" in second
            and got["drive"] == ["20241105_Old trip"]), f"{got}"


@case
def a_name_check_word_is_checked_by_the_name_grammar():
    """GUARD G79 — the `word:` is a whole folder name and photo_name.validate()
    judges it: a word that is no name is refused, nothing written."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        got = g79_flow(tmp, "word: Old trip")
    return (got["applied"][0] == 1 and "nothing written for it" in got["applied"][1]
            and "(name check)" not in got["page"]), f"{got['applied']}"


@case
def a_name_check_rename_is_refused_when_the_folder_changed_after_the_scan():
    """GUARD G79 — G41's proof: the owner added a file to the folder after
    the scan, so the final check renames nothing."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        got = g79_flow(tmp, "word: 20241101-1105_Old trip", change_after_copy=True)
    said = got["after"][1] + got["after"][2]
    return ("RENAME (name check)" in got["page"] and got["after"][0] == 1
            and "changed since the engine looked at it" in said
            and got["drive"] == ["20241105_Old trip"]), f"{got['after']} {got['drive']}"


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
def an_engine_folder_stays_the_engines_when_the_drive_is_mounted_elsewhere():
    """⭐ S-4 (ii) REPRODUCTION. dump-a copied and CREATED its folder, then
    the drive came back under another root (plans.json still names the old
    one). dump-b merges into that folder: the fix plan offers the engine R2
    rename (no "by hand"), and the final check has no `RENAME (owner)` row
    for it. A folder of the same name on another root, holding none of
    dump-a's copies, is not the engine's. ⛔ FAILS on a06ac55: "the engine
    did not create this folder: rename it by hand", and an owner row."""
    import shutil
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wa, _pack = fin.ready(tmp)
        first = fin.finish(wa)
        moved = Path(tmp).resolve() / "moved"
        shutil.move(str(Path(tmp).resolve() / "sorted"), str(moved))
        wb = second_dump(tmp)
        coll = wb.parent / "collection.json"
        coll.write_text(json.dumps({**json.loads(coll.read_text()), "dest_root": str(moved)}))
        must(ix.run("dest", wb, "F001", "merge", moved / LOTUS_DAY, "--ref", wa,
                    "--reason", "the same day"), "dest")
        for cmd in ("render", "check"):
            must(ix.run(cmd, wb), cmd)
        fcode, fout, _ = ix.run("freeze", wb)
        got = rows(wb) if fcode == 3 else []
        _a, _f, run = to_the_copy(wb, *["skip"] * len(got)) if got else (None, None, fin.finish(wb))
        pack, _t, idx = photo_index.load(wb, None)
        for fo in idx["folders"]:
            if fo["id"] == "F001":
                fo["dest"]["owner_scan"] = {}    # as an R4 `ok` records it
        plans = json.loads((wb / "plans.json").read_text())
        owner = photo_index.owner_rows(wb, idx, plans, pack)
        other = Path(tmp).resolve() / "other"
        (other / LOTUS_DAY).mkdir(parents=True)
        (other / LOTUS_DAY / "IMG_0101.jpg").write_bytes(b"\xff\xd8not the copy\xff\xd9")
        theirs = getattr(photo_index, "collection_copies", None)
        stranger = (photo_execute.real_key(other / LOTUS_DAY) in theirs(wb, str(other))[0]
                    if theirs else None)
    return (first.returncode == 0 and len(got) == 1 and "(R2) · F001" in got[0]
            and "by hand" not in got[0] and run.returncode == 0 and owner == []
            and stranger is False), \
        f"freeze={fcode} rows={got} {fout[-300:]!r} finish={run.returncode} owner={owner} stranger={stranger}"


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
    work dir; no preview is made, and the answers still parse past it. Since
    M17 (L-7) a folder with no preview shows one of its own stills, by its
    source path. ⛔ The no-preview half FAILS on f9102e8 (no line)."""
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
    own = got[False][0]
    return (got[True] == (want, 0) and got[False][1] == 0 and len(own) == 1
            and own[0].endswith("/IMG_0101.jpg") and " | " not in own[0]), f"{got}"


@case
def a_per_day_row_shows_the_photos_of_its_own_days():
    """⭐ L-6 REPRODUCTION (Liked rows 3/4 and 16/17: two DAYS-INTO-EXISTING
    rows split from one folder showed the SAME photos). F001 holds 11-01 and
    11-02, each with an owner folder and a preview of its own: each row shows
    only its day's. ⛔ FAILS on f9102e8: both rows showed both days'."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        owner_folder(tmp, day="2024:11:01 09:00:00", rel="2024/20241101_Old trip")
        owner_folder(tmp, day="2024:11:02 09:00:00", rel="2024/20241102_Other day")
        wd, _pack = ix.g3_dump(tmp, batches=[
            {"batch": 1, "from": "2024-11-01", "to": "2024-11-02", "place": "Ford"}])
        bdir = wd / "classify" / "batch-01"
        (bdir / "samples").mkdir(parents=True, exist_ok=True)
        base = Path(tmp).resolve() / "raw" / "dump-a"
        selected = []
        for name in ("IMG_0101.jpg", "IMG_0201.jpg"):
            (bdir / "samples" / name).write_bytes(b"jpeg")
            selected.append({"path": f"{base}/{name}", "sample": name})
        (bdir / "see-report.json").write_text(json.dumps({"batch": 1, "selected": selected}))
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        ix.run("fix-plan", wd)
        lines = page(wd).read_text().splitlines()
    shown = {}
    for i, line in enumerate(lines):
        if "DAYS-INTO-EXISTING (R4)" in line and i + 1 < len(lines):
            day = "2024-11-01" if "`2024-11-01`" in line else "2024-11-02"
            shown[day] = lines[i + 1].strip()
    return (shown.get("2024-11-01") == "samples: classify/batch-01/samples/IMG_0101.jpg"
            and shown.get("2024-11-02") == "samples: classify/batch-01/samples/IMG_0201.jpg"), \
        f"{shown}"


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



def w7_trip(answers):
    """W-7: two days abroad at `Harbour+Birk County`, the county flagged an
    administrative area, answered row by row with `answers(row text)`.
    -> (the trip's rendered name, what apply said)."""
    batches = [dict(b, day_type="OVERSEAS", country_word="Ruritania",
                    place="Harbour+Birk County", place_kinds={"Birk County": "admin"})
               for b in ix.G3_BATCHES]
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, batches=batches)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        ix.run("freeze", wd)
        answer(wd, *[answers(x) for x in rows(wd)])
        _c, out, err = apply(wd)
        must(ix.run("render", wd), "render")
        trip = [fo.get("rendered") for fo in ix.index_of(tmp)[0]["folders"]
                if fo["kind"] == "trip"]
    return trip, out + err


@case
def a_place_r1_drops_from_the_legs_leaves_the_trip_name_too():
    """⭐ W-7 REPRODUCTION (Win11 run 20261026). R1 dropped an administrative
    area from the legs, and the R5 trip made on the same page still carried
    it: `…_Grand Teton National Park+Teton County`. The trip's place words are
    taken after the approved drops of its own legs. ⛔ FAILS on 3c5eb76."""
    trip, said = w7_trip(lambda x: "ok")
    return trip == ["20241101-1102_Ruritania_Harbour"], f"trip={trip} {said[-300:]!r}"


@case
def a_skipped_r1_row_leaves_the_trip_name_as_offered():
    """GUARD W-7 — only an APPROVED drop reaches the trip: with the R1 rows
    skipped the trip keeps the word its row offered."""
    trip, said = w7_trip(lambda x: "ok" if "(R5)" in x else "skip")
    return trip == ["20241101-1102_Ruritania_Harbour+Birk County"], \
        f"trip={trip} {said[-300:]!r}"


@case
def an_agent_name_beside_a_make_trip_row_is_checked_as_the_leg_it_becomes():
    """⭐ C-19 REPRODUCTION (Camera: 6 owner-approved agent names failed
    check after the same OK's MAKE-TRIP turned their folders into legs —
    `YYYYMMDD` in a leg, [where] not the parent's — and freeze refused).
    Both rows `ok`: render names F002 in its final, leg shape, `check` and
    `freeze` pass, and the page row says the leg form. ⛔ FAILS on f9102e8:
    check refused the leg name."""
    batches = [dict(b, day_type="OVERSEAS", country_word="Ruritania")
               for b in ix.G3_BATCHES]
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, batches=batches)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        must(ix.run("fix-plan", wd, "--agent", "F002", "--to",
                    "20241102_Shrine_temple walk", "--reason", "the shrine"), "agent")
        ix.run("fix-plan", wd)
        got = rows(wd)
        answer(wd, *["ok" for _ in got])
        acode, _aout, aerr = apply(wd)
        rcode, _ro, rerr = ix.run("render", wd)
        ccode, cout, cerr = ix.run("check", wd)
        fcode, _fo, ferr = ix.run("freeze", wd)
        f2 = next(fo for fo in ix.index_of(tmp)[0]["folders"] if fo["id"] == "F002")
    agent = [x for x in got if "(agent) · F002" in x]
    return (acode == 0 and rcode == 0 and ccode == 0 and fcode == 0
            and f2.get("kind") == "leg" and f2.get("rendered") == "1102_Shrine_temple walk"
            and agent and "`1102_Shrine_temple walk`" in agent[0]), \
        (f"apply={acode} render={rcode} check={ccode} {(cout + cerr)[-300:]!r} "
         f"freeze={fcode} {ferr[-200:]!r} f2={f2.get('kind')} {f2.get('rendered')!r} "
         f"rows={got}")


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

TRIP_1030 = "2024/20241030-1105_Ruritania_Ford"


def trip_with_one_leg(tmp):
    """G3 abroad (F001 on 11-01, F002 on 11-02) and an existing trip on the
    drive whose only leg is 1101_Ford: 11-02 has no leg there."""
    owner_folder(tmp, day="2024:11:01 09:00:00", rel=f"{TRIP_1030}/1101_Ford")
    batches = [dict(b, day_type="OVERSEAS", country_word="Ruritania")
               for b in ix.G3_BATCHES]
    wd, _pack = ix.g3_dump(tmp, batches=batches)
    for cmd in ("init", "render", "check"):
        must(ix.run(cmd, wd), cmd)
    ix.run("fix-plan", wd)
    return wd


@case
def a_day_in_an_existing_trip_with_no_leg_for_it_gets_a_new_leg_folder():
    """⭐ S-4 REPRODUCTION. 11-02 falls inside the existing trip but no leg
    covers it: the R4 row offers a NEW leg `<trip>/1102_...`, and after `ok`
    the copies land in that leg — none loose in the trip folder — and the
    freeze's name check has nothing to say about the trip's period. ⛔ FAILS
    on c3485fe: the row pointed at the trip folder itself and the 11-02
    photos were copied loose into it."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = trip_with_one_leg(tmp)
        got = [x for x in rows(wd) if "INTO-EXISTING (R4)" in x]
        _aout, (fcode, ferr), run = to_the_copy(wd, *["ok"] * len(rows(wd)))
        trip = Path(tmp).resolve() / "sorted" / TRIP_1030
        loose = sorted(p.name for p in trip.iterdir() if p.is_file())
        legs = sorted(p.name for p in trip.iterdir() if p.is_dir())
        new = trip / "1102_Harbour_harbour walk"
        inside = sorted(p.name for p in new.iterdir()) if new.is_dir() else []
        plans = json.loads((wd / "plans.json").read_text())["plans"]
    f2 = [x for x in got if "F002" in x]
    return (len(f2) == 1 and f"{TRIP_1030.split('/')[1]}/1102_Harbour_harbour walk`" in f2[0]
            and "a new leg folder" in f2[0] and fcode == 0 and not loose
            and legs == ["1101_Ford", "1102_Harbour_harbour walk"] and inside
            and run.returncode in (0, 3)
            and "NAME CHECK FAILED" not in run.stdout + run.stderr + ferr
            and any((p.get("legs") or [{}])[0].get("name") == "1102_Harbour_harbour walk"
                    for p in plans)), \
        (f"rows={got} freeze={fcode} {ferr[-200:]!r} loose={loose} legs={legs} "
         f"inside={inside} finish={run.returncode} {run.stdout[-300:]!r}")


@case
def the_freezes_own_name_check_judges_the_new_leg_not_the_trip():
    """⭐ S-4 follow-up REPRODUCTION (the scratch run's dumpB-13-freeze.log).
    11-02 goes into an existing trip as a new leg, 11-01 into its existing
    leg 1101_Ford: the freeze's own photo_plan name check judges the legs and
    says nothing about the trip's period. ⛔ FAILS on 2805f9d: "NAME CHECK
    FAILED" for the trip's period (P2) and for `1101_Ford` read as a folder
    (P1)."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = trip_with_one_leg(tmp)
        answer(wd, *["ok"] * len(rows(wd)))
        must(apply(wd), "apply")
        for cmd in ("render", "check"):
            must(ix.run(cmd, wd), cmd)
        fcode, fout, ferr = ix.run("freeze", wd)
        plans = json.loads((wd / "plans.json").read_text())["plans"]
    leg = [p for p in plans if p["dest"]["mode"] == "merge" and p.get("legs")]
    said = [l for l in (fout + ferr).splitlines() if "NAME CHECK FAILED" in l]
    return (fcode == 0 and len(plans) == 2 and len(leg) == 1 and not said), \
        f"freeze={fcode} legs={[(p['dest']['path'][-40:], p.get('legs')) for p in plans]} said={said}"


@case
def a_merge_into_a_flat_folder_offers_no_rename_beside_it():
    """GUARD (L-8's own shape: Liked rows 2 + 21, F005 INTO-EXISTING an
    owner's flat folder AND a RENAME of F005, both ok'd, the whole plan
    refused). M16's G62 rule already lists the rename as refused; this pins
    it for a merge into a day folder, not only into a trip's leg, and `ok`
    on every offered row applies."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        owner_folder(tmp)
        wd, _pack = ix.g3_dump(tmp)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        must(ix.run("fix-plan", wd, "--agent", "F001", "--to", "20241101_Ford_morning",
                    "--reason", "the morning"), "agent")
        ix.run("fix-plan", wd)
        got = rows(wd)
        listed = "cannot apply beside it" in page(wd).read_text()
        answer(wd, *["ok" for _ in got])
        acode, aout, aerr = apply(wd)
    f001 = [x for x in got if "· F001 ·" in x]
    return (len(f001) == 1 and "INTO-EXISTING (R4)" in f001[0] and listed
            and acode == 0), f"rows={got} apply={acode} {aerr[-300:]!r}"


@case
def a_folder_every_day_of_which_goes_elsewhere_offers_no_rename():
    """⭐ L-8 REPRODUCTION, the case M16 left open: F001 holds 11-01 and
    11-02, and each day already has an owner folder, so two
    DAYS-INTO-EXISTING rows take every day of it. A RENAME of F001 is then
    a question about an empty folder: listed as refused, never offered.
    ⛔ FAILS on f9102e8: the rename was offered and applied beside them."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        owner_folder(tmp, day="2024:11:01 09:00:00", rel="2024/20241101_Old trip")
        owner_folder(tmp, day="2024:11:02 09:00:00", rel="2024/20241102_Other day")
        wd, _pack = ix.g3_dump(tmp, batches=[
            {"batch": 1, "from": "2024-11-01", "to": "2024-11-02", "place": "Ford"}])
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        must(ix.run("fix-plan", wd, "--agent", "F001", "--to",
                    "20241101-1102_Ford_morning", "--reason", "the morning"), "agent")
        ix.run("fix-plan", wd)
        got = rows(wd)
        listed = "cannot apply beside it" in page(wd).read_text()
        answer(wd, *["ok" for _ in got])
        acode, _aout, aerr = apply(wd)
    days = [x for x in got if "DAYS-INTO-EXISTING (R4) · F001" in x]
    return (len(days) == 2 and not [x for x in got if "(agent) · F001" in x]
            and listed and acode == 0), f"rows={got} apply={acode} {aerr[-300:]!r}"


@case
def a_freeze_that_writes_rows_rewrites_the_web_page():
    """⭐ L-10 REPRODUCTION (Liked: `freeze` wrote the new Review folders
    rows to fix-plan.md; the old 21-row fix-plan.html stayed until a hand
    `render`). A page already rendered is rendered again from the new rows.
    ⛔ FAILS on f9102e8: the old page is left as it was."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        owner_folder(tmp)
        wd, _pack = ready(tmp)
        (wd / "plan").mkdir(exist_ok=True)
        html = wd / "plan" / "fix-plan.html"
        html.write_text("<html>OLD PAGE</html>", encoding="utf-8")
        code, _o, _e = ix.run("freeze", wd)
        text = html.read_text(encoding="utf-8")
    return (code == 3 and "OLD PAGE" not in text and "INTO-EXISTING" in text), \
        f"freeze={code} page={text[:120]!r}"


@case
def a_row_left_open_is_not_asked_again_in_another_shape():
    """⭐ L-12 REPRODUCTION (Liked round 2 re-asked round 1's row 3). F001
    holds 11-01 and 11-02, each with an owner folder: two DAYS-INTO-EXISTING
    rows. 11-01 left open (= skip), 11-02 `ok`. With only 11-01 left, R4
    reads the same move as INTO-EXISTING of the whole folder: not asked
    again, it is the row the owner already skipped. ⛔ FAILS on f9102e8:
    round 2 offered it."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        owner_folder(tmp, day="2024:11:01 09:00:00", rel="2024/20241101_Old trip")
        owner_folder(tmp, day="2024:11:02 09:00:00", rel="2024/20241102_Other day")
        wd, _pack = ix.g3_dump(tmp, batches=[
            {"batch": 1, "from": "2024-11-01", "to": "2024-11-02", "place": "Ford"}])
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        ix.run("fix-plan", wd)
        first = rows(wd)
        answer(wd, *["ok" if "2024-11-02" in x else "" for x in first])
        must(apply(wd), "apply round 1")
        for cmd in ("render", "check"):
            must(ix.run(cmd, wd), cmd)
        ix.run("fix-plan", wd)
        second = rows(wd)
    return (len(first) == 2 and not [x for x in second if "· F001 ·" in x]), \
        f"first={first} second={second}"


FLAT_SPAN = "2024/20240901-1215_Lotus_tower"


@case
def a_flat_folder_spanning_months_is_not_a_trip():
    """⭐ L-11 REPRODUCTION (Liked: R4 offered a leg inside a flat folder of
    206 files and no subfolder, `2022/20220620-1210_...`). An owner folder
    with a `YYYYMMDD-MMDD` name and no leg folder in it is not a trip: no
    R4 row puts 11-01 or 11-02 into it. ⛔ FAILS on f9102e8: two
    INTO-EXISTING rows, each "a new leg folder" in it."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        owner_folder(tmp, day="2024:09:05 09:00:00", rel=FLAT_SPAN)
        wd, _pack = ix.g3_dump(tmp)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wd), cmd)
        ix.run("fix-plan", wd)
        got = [x for x in rows(wd) if "R4" in x]
    return not any("20240901-1215" in x for x in got), f"rows={got}"


@case
def a_trip_with_a_leg_folder_still_takes_a_new_leg():
    """GUARD (L-11): the trip test is the leg folder, so the S-4 shape — a
    trip holding a leg — still offers its new leg."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = trip_with_one_leg(tmp)
        got = [x for x in rows(wd) if "INTO-EXISTING (R4)" in x and "F002" in x]
    return len(got) == 1 and "a new leg folder" in got[0], f"rows={got}"


TRIP_1030_31 = "2024/20241030-1031_Ruritania_Ford"
TRIP_1030_1102 = "2024/20241030-1102_Ruritania_Ford"


def days_after_a_trip(tmp, country="Ruritania"):
    """The owner's trip `20241030-1031_Ruritania_Ford` (legs 1030, 1031) and
    G3 abroad in `country`: F001 on 11-01, F002 on 11-02, the two days right
    after it. -> work dir, fix plan drafted."""
    for leg, day in (("1030_Ford", "2024:10:30 09:00:00"), ("1031_Ford", "2024:10:31 09:00:00")):
        owner_folder(tmp, day=day, rel=f"{TRIP_1030_31}/{leg}")
    batches = [dict(b, day_type="OVERSEAS", country_word=country) for b in ix.G3_BATCHES]
    wd, _pack = ix.g3_dump(tmp, batches=batches)
    for cmd in ("init", "render", "check"):
        must(ix.run(cmd, wd), cmd)
    ix.run("fix-plan", wd)
    return wd


@case
def days_right_after_a_trip_join_it_and_its_dates_widen_after_the_copy():
    """⭐ G70 REPRODUCTION (owner ruling). The two days right after the
    owner's trip, in its country: ONE R4 row joins them to it (no new trip
    for them); `ok` copies each into a new leg; the final check offers to
    widen the trip's period 1030-1031 -> 1030-1102 (`RENAME (owner)`), and
    `ok` + --go renames it with the before = after proof, the legs inside.
    In another country nothing joins. ⛔ FAILS on ca7c36a: a new trip
    F001+F002 was offered beside the owner's."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = days_after_a_trip(tmp)
        got = rows(wd)
        _a, (fcode, ferr), run = to_the_copy(wd, *["ok"] * len(got))
        after = owner_row(wd) if after_page(wd).is_file() else []
        root = Path(tmp).resolve() / "sorted"
        answer_after(wd, *["ok"] * len(after))
        gcode, gout, gerr = ix.run("after-check", wd, "--answers", after_page(wd), "--go")
        legs = (sorted(p.name for p in (root / TRIP_1030_1102).iterdir())
                if (root / TRIP_1030_1102).is_dir() else [])
        vcode, _v, _ = ix.run("verify", wd, "--copied")
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        other = [x for x in rows(days_after_a_trip(tmp, country="Otherland"))
                 if "INTO-EXISTING" in x]
    join = [x for x in got if "INTO-EXISTING (R4)" in x]
    return (len(join) == 1 and "2 day folder(s) 1101-1102" in join[0]
            and f"`{TRIP_1030_31}`" in join[0] and "(G70)" in join[0]
            and not [x for x in got if "MAKE-TRIP" in x] and fcode == 0
            and run.returncode == 3 and len(after) == 1
            and f"`{TRIP_1030_31}` → `{TRIP_1030_1102}`" in after[0]
            and "RENAME (owner)" in after[0] and gcode == 0
            and legs == ["1030_Ford", "1031_Ford", "1101_Ford_Lotus_sofa nap",
                         "1102_Harbour_harbour walk"]
            and not (root / TRIP_1030_31).exists() and vcode in (0, 6) and not other), \
        (f"rows={got} freeze={fcode} {ferr[-200:]!r} finish={run.returncode} "
         f"after={after} go={gcode} {gout[-300:]!r}{gerr[-200:]!r} legs={legs} "
         f"verify={vcode} other={other}")


ENGINE_TRIP = "20241101-1102_Ruritania_Ford+Harbour"
ENGINE_TRIP_WIDE = "20241101-1103_Ruritania_Ford+Harbour"


@case
def a_day_after_an_engine_trip_joins_it_and_both_dumps_follow_the_new_dates():
    """⭐ G70 REPRODUCTION (the scratch run's shape). dump-a made and copied
    the trip 1101-1102 (R5 `ok`); dump-b's 11-03 in the same country joins
    it as a new leg; the final check offers `RENAME (trip period)` to
    1101-1103, and `ok` + --go renames it with the proof over BOTH dumps'
    copies, moves both records, and both verify. ⛔ FAILS on ca7c36a: no
    join row (11-03 stayed its own folder) and no period row."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        batches = [dict(b, day_type="OVERSEAS", country_word="Ruritania")
                   for b in ix.G3_BATCHES]
        wa, _pack = ix.g3_dump(tmp, batches=batches)
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wa), cmd)
        ix.run("fix-plan", wa)
        _a, _f, run_a = to_the_copy(wa, *["ok"] * len(rows(wa)))
        base = Path(tmp).resolve() / "raw" / "dump-b"
        base.mkdir(parents=True)
        made = []
        for k, file in enumerate(("IMG_0501.jpg", "IMG_0502.jpg")):
            (base / file).write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
                                      + f"dump-b/{file}".encode() + b"\xff\xd9")
            made.append(ix.row(file, SourceFile=str(base / file),
                               when=f"2024:11:03 1{k}:00:00", gps=ix.FAR))
        wb = ix.make_dump(tmp, rows=made, name="dump-b", batches=[
            {"batch": 1, "from": "2024-11-03", "to": "2024-11-03", "place": "Harbour",
             "day_type": "OVERSEAS", "country_word": "Ruritania"}])
        ix.write_see(wb, 1, [ix.see_label(base, n, what="pier walk")
                             for n in ("IMG_0501.jpg", "IMG_0502.jpg")])
        for cmd in ("init", "render", "check"):
            must(ix.run(cmd, wb), cmd)
        ix.run("fix-plan", wb)
        got = rows(wb)
        _a, _f, run_b = to_the_copy(wb, *["ok"] * len(got))
        after = owner_row(wb) if after_page(wb).is_file() else []
        answer_after(wb, *["ok"] * len(after))
        gcode, gout, gerr = ix.run("after-check", wb, "--answers", after_page(wb), "--go")
        root = Path(tmp).resolve() / "sorted"
        legs = (sorted(p.name for p in (root / ENGINE_TRIP_WIDE).iterdir())
                if (root / ENGINE_TRIP_WIDE).is_dir() else [])
        va, _v, _ = ix.run("verify", wa, "--copied")
        vb, _w, _ = ix.run("verify", wb, "--copied")
    return (run_a.returncode == 0 and len(got) == 1 and "INTO-EXISTING (R4)" in got[0]
            and f"`{ENGINE_TRIP}`" in got[0] and run_b.returncode == 3
            and len(after) == 1 and "RENAME (trip period)" in after[0]
            and f"`{ENGINE_TRIP}` → `{ENGINE_TRIP_WIDE}`" in after[0] and gcode == 0
            and legs == ["1101_Ford_Lotus_sofa nap", "1102_Harbour_harbour walk",
                         "1103_Harbour_pier walk"]
            and va in (0, 6) and vb in (0, 6)), \
        (f"a={run_a.returncode} rows={got} b={run_b.returncode} after={after} "
         f"go={gcode} {gout[-300:]!r}{gerr[-200:]!r} legs={legs} verify={va},{vb}")


@case
def a_skipped_join_leaves_the_days_their_own_folders_and_offers_no_trip():
    """GUARD (G70). `skip` on the join row: the days stay their own folders
    and no new trip of only those days is offered in its place."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = days_after_a_trip(tmp)
        first = rows(wd)
        answer(wd, *["skip"] * len(first))
        must(apply(wd), "apply")
        for cmd in ("render", "check"):
            must(ix.run(cmd, wd), cmd)
        fcode, fout, ferr = ix.run("freeze", wd)
        again = rows(wd) if fcode == 3 else []
        modes = {fo["id"]: fo["dest"]["mode"] for fo in ix.index_of(tmp)[0]["folders"]
                 if fo["kind"] == "day"}
    return (len(first) == 1 and fcode == 0 and not again
            and modes == {"F001": "new", "F002": "new"}), \
        f"first={first} freeze={fcode} again={again} modes={modes} {(fout + ferr)[-300:]!r}"


@case
def a_trip_changed_by_hand_after_the_copy_keeps_its_dates():
    """⭐ G70 / ADR 0007 GUARD. The owner put a photo into the trip after the
    copy: the widening row is refused, nothing is renamed."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = days_after_a_trip(tmp)
        to_the_copy(wd, *["ok"] * len(rows(wd)))
        after = owner_row(wd) if after_page(wd).is_file() else []
        root = Path(tmp).resolve() / "sorted"
        (root / TRIP_1030_31 / "1031_Ford" / "HAND.jpg").write_bytes(b"\xff\xd8hand\xff\xd9")
        answer_after(wd, *["ok"] * len(after))
        gcode, gout, _ = ix.run("after-check", wd, "--answers", after_page(wd), "--go")
        kept = (root / TRIP_1030_31).is_dir() and not (root / TRIP_1030_1102).exists()
    return (len(after) == 1 and gcode == 1 and "nothing was renamed" in gout
            and kept), f"after={after} go={gcode} kept={kept} {gout[-400:]!r}"


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
