#!/usr/bin/env python3
"""SET-1 cases — `photo_settings.py show / explain / set`.

Three claims are load-bearing and are what most of these cases are about.

  * **Layered resolution is reported honestly.** `show` prints the layer a
    value came from, and the collection layer is displayed WITH a warning,
    because no stage script reads a setting out of `collection.json` today.
    A tool that showed it as an effective source would be describing a
    resolution the engine does not perform.
  * **The classify floor is policy, not preference** (L01). It may be raised,
    never lowered, and a model this engine cannot place on its ladder is
    refused rather than assumed to clear it.
  * **The tool is plan-neutral.** Nothing here writes to a work dir, and
    nothing it stores in a pack changes a plan — the golden replay is the
    other half of that claim and runs unchanged beside this file.

  python3 tests/settings_cases.py [-v]

Exit 0 = pass. Every pack is built in a temp dir from the shipped template;
nothing on a drive is read and no owner's pack is touched.
"""

import argparse
import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_profile  # noqa: E402
import photo_settings as ps  # noqa: E402

TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def make_pack(root, owner="fixture-owner", **profile_edits):
    """A pack on disk from the shipped template — the layout a real owner
    gets, with none of a real owner's facts in it."""
    pack_dir = Path(root) / "photo-memory" / owner
    pack_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE, pack_dir)
    for path in list(pack_dir.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", owner)))
    profile_file = pack_dir / photo_profile.PROFILE_NAME
    profile = json.loads(profile_file.read_text(encoding="utf-8")
                         .replace("{{SLUG}}", owner)
                         .replace("{{DISPLAY}}", owner))
    profile.update(profile_edits)
    profile_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    return pack_dir


def open_pack(pack_dir):
    return photo_profile.resolve_pack(
        explicit=pack_dir / photo_profile.PROFILE_NAME)


def smsg_of(pack):
    return photo_profile.settings_messages(pack.profile)


def run(fn, *args, **kw):
    """-> (exit code or None, printed text). The commands write to stdout, and
    what they print IS the product."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            code = fn(*args, **kw)
        except ps.Refused as refused:
            return 2, refused.message
    return code, buf.getvalue()


def profile_of(pack_dir):
    return json.loads((pack_dir / photo_profile.PROFILE_NAME)
                      .read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# show — every value, and where it came from
# ---------------------------------------------------------------------------

@case
def show_prints_every_setting_for_a_run_with_no_pack_at_all():
    """A pack is not required to ask what the engine will do. Every row falls
    to the engine's own default, and none of those defaults is anyone's."""
    pack = photo_profile.Pack()
    _code, out = run(ps.show, pack, {}, {})
    rows = [s.key for s in ps.SETTINGS if s.key in out]
    return (len(rows) == len(ps.SETTINGS)
            and smsg_of(pack)["settings_no_pack_line"] in out), \
        f"{len(rows)}/{len(ps.SETTINGS)} rows"


@case
def show_prints_every_setting_for_a_fresh_template_pack():
    """SET-1's exit test, half one: a pack a new owner would actually get."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        _code, out = run(ps.show, pack, {}, {})
    missing = [s.key for s in ps.SETTINGS if s.key not in out]
    return not missing, f"missing {missing}"


@case
def a_value_the_pack_sets_is_reported_as_coming_from_the_pack():
    """The template ships `sampling`, so a fresh pack proves the pack layer
    without anything being written first."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        state = ps.resolve_all(pack.profile, {})
    return (state["sampling.gps_pct"]["layer"] == ps.PACK
            and state["models.classify"]["layer"] == ps.DEFAULT), \
        f"{state['sampling.gps_pct']} {state['models.classify']}"


@case
def a_flag_beats_the_pack_for_one_run():
    """The fourth layer. A stage command's own flag wins, and `show --flag`
    is how an owner asks what that would do without writing anything."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        pack = open_pack(pack_dir)
        flags = ps.parse_flags(["sampling.gps_pct=0.5"], smsg_of(pack))
        state = ps.resolve_all(pack.profile, {}, flags)
        after = profile_of(pack_dir)
    return (state["sampling.gps_pct"]["value"] == 0.5
            and state["sampling.gps_pct"]["layer"] == ps.FLAG
            # and nothing was written by asking
            and after["sampling"]["gps_pct"] == 0.10), f"{state['sampling.gps_pct']}"


@case
def a_setting_in_collection_json_is_shown_with_the_warning_that_no_stage_reads_it():
    """⚠️ The discrepancy this tool must not paper over. The design names four
    layers; the engine resolves settings through the PACK alone. So the
    collection value is displayed — hiding it would hide the gap — and the row
    says which value the run will really use."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        collection = {"settings": {"sampling": {"gps_pct": 0.9}}}
        state = ps.resolve(ps.BY_KEY["sampling.gps_pct"], pack.profile,
                           collection, {})
        _code, out = run(ps.show, pack, collection, {})
    warned = smsg_of(pack)["settings_collection_not_read"].split("{")[0] in out
    return (state["layer"] == ps.COLLECTION and state["shadowed"] == (0.10, ps.PACK)
            and warned), f"{state} warned={warned}"


@case
def a_key_the_engine_does_not_read_yet_says_so():
    """Naming principle A is signed and unbuilt: no stage reads `naming.*`.
    Offering the switch silently would promise an effect the engine has not
    got, which is worse than not offering it."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        _code, out = run(ps.show, pack, {}, {})
        _c2, explained = run(ps.explain, "naming.smart_scenario", pack, {},
                             smsg_of(pack))
    note = smsg_of(pack)["settings_not_built_yet"]
    return note in out and note in explained, f"show={note in out} explain={note in explained}"


@case
def show_json_answers_the_same_questions_as_the_table():
    """SET-2 reads this, not the table. The two must not drift into different
    answers."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        _code, out = run(ps.show, pack, {}, {}, as_json=True)
        data = json.loads(out)
    keys = [row["key"] for row in data["settings"]]
    naming = [row for row in data["settings"] if row["key"].startswith("naming.")]
    return (keys == [s.key for s in ps.SETTINGS]
            and all(not row["engine_reads_it"] for row in naming)
            and data["owner"] == "fixture-owner"), f"{keys[:3]}…"


# ---------------------------------------------------------------------------
# the blast tags
# ---------------------------------------------------------------------------

@case
def every_setting_carries_a_blast_tag_the_catalog_can_render():
    """ONB-10's corollary, verbatim: say whether a change moves files or only
    edits a label. A setting with no tag, or a tag with no sentence, would
    leave the skill unable to say it."""
    smsg = photo_profile.settings_messages({})
    bad = [s.key for s in ps.SETTINGS
           if s.tag not in ps.TAG_MESSAGE_KEY
           or ps.TAG_MESSAGE_KEY[s.tag] not in smsg
           or ps.TAGLINE_MESSAGE_KEY[s.tag] not in smsg]
    return not bad, f"{bad}"


@case
def a_setting_that_changes_a_folder_name_is_tagged_moves_files():
    """The tag is about consequence, not about which subsystem the key lives
    in: a name change decides which folder a future run copies into."""
    want = {"naming.smart_scenario", "models.classify"}
    got = {s.key for s in ps.SETTINGS if s.tag == ps.MOVES_FILES}
    return got == want, f"{sorted(got)}"


@case
def every_setting_has_its_own_sentence_and_none_of_them_is_a_literal():
    """Rule 8. Not one of these sentences is written in this file or in
    photo_settings.py — every one is a key resolved from the catalog, so a
    pack can supply another language for the whole surface."""
    smsg = photo_profile.settings_messages({})
    missing = [s.key for s in ps.SETTINGS if s.why not in smsg]
    return not missing, f"{missing}"


# ---------------------------------------------------------------------------
# set — validation and the floor
# ---------------------------------------------------------------------------

@case
def a_below_floor_classify_model_is_refused():
    """SET-1's exit test, half two. L01 after the 2026-07-20 fabrication
    incident: the floor is policy and this tool does not step around it."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        pack = open_pack(pack_dir)
        code, message = run(ps.apply_set, "models.classify", "haiku", pack, {},
                            smsg_of(pack), go=True)
        untouched = "models" not in profile_of(pack_dir)
    return (code == 2 and "haiku" in message and untouched), f"{code} {message}"


@case
def a_stronger_classify_model_is_accepted():
    """"Settable upward only" has to mean upward IS settable, or the floor is
    just a lock."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        pack = open_pack(pack_dir)
        code, _out = run(ps.apply_set, "models.classify", "opus", pack, {},
                         smsg_of(pack), go=True)
        written = profile_of(pack_dir).get("models", {}).get("classify")
    return code == 0 and written == "opus", f"{code} {written}"


@case
def a_model_the_ladder_does_not_know_is_refused_for_classify():
    """It cannot be SHOWN to clear the floor, so it is refused rather than
    assumed to. The safe direction: a model that really is stronger reaches
    the ladder by being added to it, which is a code change, which is what a
    policy floor should cost."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        code, message = run(ps.apply_set, "models.classify", "some-new-model",
                            pack, {}, smsg_of(pack), go=True)
    return code == 2 and "some-new-model" in message, f"{code} {message}"


@case
def the_copy_conductor_takes_any_model_because_the_script_moves_the_bytes():
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        pack = open_pack(pack_dir)
        code, _out = run(ps.apply_set, "models.copy_conductor", "haiku", pack,
                         {}, smsg_of(pack), go=True)
        written = profile_of(pack_dir)["models"]["copy_conductor"]
    return code == 0 and written == "haiku", f"{code} {written}"


@case
def embed_coverage_is_shown_and_refused():
    """Recurrence cannot be measured on a sample, so 100% is a fact rather
    than a preference — and the refusal says that instead of just saying no."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        code, message = run(ps.apply_set, "visual.embed_coverage", "0.5", pack,
                            {}, smsg_of(pack), go=True)
        state = ps.resolve_all(pack.profile, {})
    return (code == 2 and state["visual.embed_coverage"]["value"] == 1.0
            and len(message) > 40), f"{code} {message}"


@case
def a_schedule_key_is_read_only_until_set_3_owns_it():
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        code, _m = run(ps.apply_set, "schedule.enabled", "on", pack, {},
                       smsg_of(pack), go=True)
    return code == 2, f"{code}"


@case
def an_out_of_range_number_is_refused_with_the_range_in_the_sentence():
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        code, message = run(ps.apply_set, "sampling.gps_pct", "1.7", pack, {},
                            smsg_of(pack), go=True)
    return code == 2 and "1.7" in message, f"{code} {message}"


@case
def a_word_where_a_number_belongs_is_refused_before_anything_is_written():
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        pack = open_pack(pack_dir)
        code, message = run(ps.apply_set, "sampling.max_samples", "lots", pack,
                            {}, smsg_of(pack), go=True)
        unchanged = profile_of(pack_dir)["sampling"]["max_samples"] == 40
    return code == 2 and unchanged and "lots" in message, f"{code} {message}"


@case
def a_pair_rule_refuses_a_minimum_above_its_maximum():
    """min_samples > max_samples would make the sampler ask for more photos
    than it is allowed to take. Checked against the config as it would be
    AFTER the write, not against the one value in hand."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        pack = open_pack(pack_dir)
        code, message = run(ps.apply_set, "sampling.min_samples", "99", pack,
                            {}, smsg_of(pack), go=True)
        unchanged = profile_of(pack_dir)["sampling"]["min_samples"] == 10
    return code == 2 and unchanged and "40" in message, f"{code} {message}"


@case
def the_same_pair_rule_reports_a_pack_that_already_disagrees_with_itself():
    """A hand-edited pack can hold the contradiction the setter refuses to
    create. `show` says so rather than letting the sampler discover it."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp, sampling={"min_samples": 90,
                                                  "max_samples": 40}))
        _code, out = run(ps.show, pack, {}, {})
    return "min_samples" in out and "90" in out, f"{out[-200:]}"


@case
def a_bool_takes_the_words_a_person_would_type():
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        pack = open_pack(pack_dir)
        code, _out = run(ps.apply_set, "naming.smart_scenario", "on", pack, {},
                         smsg_of(pack), go=True)
        written = profile_of(pack_dir)["naming"]["smart_scenario"]
        bad, message = run(ps.apply_set, "naming.smart_scenario", "sometimes",
                           open_pack(pack_dir), {}, smsg_of(pack), go=True)
    return (code == 0 and written is True and bad == 2
            and "sometimes" not in message.split(":")[0]), f"{code} {written} {bad}"


@case
def an_unknown_key_is_refused_by_all_three_commands():
    """Including `--flag`, which takes the same key names — a typo there would
    otherwise be silently ignored and the answer would be wrong rather than
    refused."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        smsg = smsg_of(pack)
        set_code, _m = run(ps.apply_set, "naming.colour", "blue", pack, {}, smsg)
        explain_code, _e = run(ps.explain, "naming.colour", pack, {}, smsg)
        try:
            ps.parse_flags(["naming.colour=blue"], smsg)
            flag_refused = False
        except SystemExit:
            flag_refused = True
    return (set_code == 2 and explain_code == 2 and flag_refused), \
        f"set={set_code} explain={explain_code} flag={flag_refused}"


@case
def a_write_to_the_collection_layer_is_refused_rather_than_doing_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        code, message = run(ps.apply_set, "sampling.gps_pct", "0.2", pack, {},
                            smsg_of(pack), go=True, layer=ps.COLLECTION)
    return code == 2 and "collection.json" in message, f"{code} {message}"


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------

@case
def a_set_without_go_writes_nothing_and_says_what_it_would_have_done():
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        pack = open_pack(pack_dir)
        code, out = run(ps.apply_set, "sampling.gps_pct", "0.2", pack, {},
                        smsg_of(pack))
        unchanged = profile_of(pack_dir)["sampling"]["gps_pct"] == 0.10
    return (code == 0 and unchanged and "0.2" in out
            and smsg_of(pack)["settings_dry_run"] in out), f"{code} {out}"


@case
def a_dry_run_states_the_blast_tag_before_anything_is_confirmed():
    """ONB-10's corollary is about the moment BEFORE the change, so the
    sentence has to be in the dry run and not only in `explain`."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        smsg = smsg_of(pack)
        _c, out = run(ps.apply_set, "naming.smart_scenario", "on", pack, {}, smsg)
    return smsg["settings_tagline_moves_files"] in out, f"{out}"


@case
def a_write_keeps_everything_else_in_the_pack_including_its_comments():
    """The file is the owner's and they may open it. A setter that rewrote it
    into a bare dict would take the template's explanations away."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        before = profile_of(pack_dir)
        code, _out = run(ps.apply_set, "sampling.gps_pct", "0.2",
                         open_pack(pack_dir), {}, smsg_of(open_pack(pack_dir)),
                         go=True)
        after = profile_of(pack_dir)
    lost = [k for k in before if k not in after]
    comments = [k for k in after if k.startswith("_")]
    return (code == 0 and not lost and comments
            and after["sampling"]["gps_pct"] == 0.2
            and after["owner"] == before["owner"]), f"lost={lost} comments={len(comments)}"


@case
def setting_a_value_that_is_already_there_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        run(ps.apply_set, "sampling.gps_pct", "0.2", open_pack(pack_dir), {},
            smsg_of(open_pack(pack_dir)), go=True)
        stamp = (pack_dir / photo_profile.PROFILE_NAME).read_text(encoding="utf-8")
        code, out = run(ps.apply_set, "sampling.gps_pct", "0.2",
                        open_pack(pack_dir), {}, smsg_of(open_pack(pack_dir)),
                        go=True)
        same = (pack_dir / photo_profile.PROFILE_NAME).read_text(encoding="utf-8") == stamp
    return code == 0 and same and "0.2" in out, f"{code} same={same}"


@case
def a_written_setting_is_read_back_as_the_pack_layer():
    """The round trip that makes the tool worth anything: what it wrote is
    what the next run resolves, from the layer it said it wrote to."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        run(ps.apply_set, "naming.max_units", "16", open_pack(pack_dir), {},
            smsg_of(open_pack(pack_dir)), go=True)
        state = ps.resolve_all(open_pack(pack_dir).profile, {})
    return (state["naming.max_units"]["value"] == 16
            and state["naming.max_units"]["layer"] == ps.PACK), \
        f"{state['naming.max_units']}"


# ---------------------------------------------------------------------------
# the two rules that outrank the feature
# ---------------------------------------------------------------------------

@case
def the_tool_never_writes_outside_the_pack():
    """Settings are owner data (ONB-10 / rule 7). The only path this module
    writes is inside the pack directory it was handed."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        written = ps.write_profile(open_pack(pack_dir),
                                   profile_of(pack_dir))
    return Path(written).parent == pack_dir, f"{written}"


@case
def nothing_in_the_settings_table_is_an_owners_fact():
    """Rule 7 from the other side: the defaults this file ships are the
    ENGINE's, so they must be the same for every owner — no path, no place, no
    name, no drive."""
    suspicious = [s.key for s in ps.SETTINGS
                  if isinstance(s.default, str) and ("/" in s.default
                                                     or "\\\\" in s.default)]
    return not suspicious, f"{suspicious}"


@case
def an_owner_can_translate_the_whole_surface_from_their_pack():
    """ONB-9's ladder. The engine ships English and any other language arrives
    from the pack — including for a language the engine has no table for."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(
            tmp, language="sv",
            settings_messages={"settings_h_key": "inställning"}))
        _code, out = run(ps.show, pack, {}, {})
    english = photo_profile.settings_messages({})
    return ("inställning" in out
            and english["settings_h_key"] not in out.splitlines()[2]), f"{out[:200]}"


# ---------------------------------------------------------------------------
# SET-2 — the SKILL is a description of this tool, and stays one
# ---------------------------------------------------------------------------
# A stale skill file is the failure mode this project has already paid for
# once: a doc that agrees with itself reads as correct while describing an
# engine that moved. These two cases hold the conversational layer to the
# command surface it claims to drive. They check the skill's CLAIMS, never
# its prose — wording is a writing decision, a key that does not exist is a
# defect.

SKILL_FILE = ROOT / "photo-settings" / "SKILL.md"
KEY_IN_TEXT = re.compile(r"`((?:models|sampling|visual|naming|schedule)"
                         r"\.[a-z_]+)`")
FLAG_IN_TEXT = re.compile(r"`?(--[a-z]+)")


@case
def every_setting_the_skill_names_is_a_setting_the_tool_has():
    text = SKILL_FILE.read_text(encoding="utf-8")
    named = set(KEY_IN_TEXT.findall(text))
    unknown = sorted(k for k in named if k not in ps.BY_KEY)
    # and it is worth naming most of them: a surface doc that mentions two
    # keys is not the conversational layer over this tool.
    return (not unknown and len(named) >= len(ps.SETTINGS) // 2), \
        f"unknown {unknown}, named {len(named)}/{len(ps.SETTINGS)}"


@case
def a_brand_new_pack_shows_what_the_skill_says_it_shows():
    """Release A starts from a clean sheet, so the SKILL's fresh-pack section
    describes the state an owner actually opens on. It is measured here rather
    than asserted in prose: a template that started shipping `models` would
    make that section wrong the day it changed."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        state = ps.resolve_all(pack.profile, {})
    from_pack = sorted(k for k, v in state.items() if v["layer"] == ps.PACK)
    others = [k for k, v in state.items()
              if v["layer"] not in (ps.PACK, ps.DEFAULT)]
    blank = sorted(s.key for s in ps.SETTINGS
                   if ps.render(state[s.key]["value"]) == "—")
    return (from_pack == ["sampling.gps_pct", "sampling.max_samples",
                          "sampling.min_samples", "sampling.no_gps_pct"]
            and not others
            and blank == ["models.embed_local", "schedule.window"]), \
        f"pack {from_pack}, other layers {others}, blank {blank}"


@case
def every_command_and_flag_the_skill_documents_exists():
    text = SKILL_FILE.read_text(encoding="utf-8")
    parser_flags = {"--workdir", "--profile", "--flag", "--go", "--json",
                    "--verbose"}
    missing_cmds = [c for c in ("show", "explain", "set")
                    if f"photo_settings.py {c}" not in text]
    bad_flags = sorted(set(FLAG_IN_TEXT.findall(text)) - parser_flags)
    return (not missing_cmds and not bad_flags), \
        f"commands {missing_cmds}, flags {bad_flags}"


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

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} settings cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
