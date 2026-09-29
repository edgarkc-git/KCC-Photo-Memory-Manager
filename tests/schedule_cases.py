#!/usr/bin/env python3
"""SET-3 cases — `photo_schedule.py` show / install / status / pause / resume
/ remove.

Four claims are load-bearing and are what most of these cases are about.

  * **The HIL-stop rule is enforced, not described.** An unattended run may
    sort, group, look and plan; it may never copy. The cases assert both
    halves: no `--go` anywhere in the rendered runner or plist, and
    `photo_execute.py` absent from the tool allowlist the runner passes to
    `claude -p`. The second is the one that holds when the prompt is misread.
  * **The classify model is pinned and the floor is not re-implemented**
    (Operational Rule 5, L01). A pack may raise the model; a pack that lowers
    it is refused — by `photo_settings`' own ladder, called, so there is one
    floor rather than three copies of one.
  * **Nothing happens without `--go`.** Rendering is pure. A dry run writes no
    file, touches no launchd, and stores nothing in the pack.
  * **It works on a clean-sheet pack** (A27) and with no pack at all. Only the
    WRITE is refused when there is nowhere to write, exactly as
    `photo_settings set` behaves.

  python3 tests/schedule_cases.py [-v]

Exit 0 = pass. Every pack is built in a temp dir from the shipped template,
every collection is synthetic, and no case installs a launchd job, reads a
drive or touches an owner's pack. The install path that really talks to
launchd is verified by hand on macOS — a suite that bootstrapped a real
LaunchAgent would leave one behind when it failed.
"""

import argparse
import contextlib
import io
import json
import plistlib
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_profile  # noqa: E402
import photo_schedule as sch  # noqa: E402
import photo_settings  # noqa: E402

TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# ------------------------------------------------------------- fixtures ----

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


def make_collection(root, owner="fixture-owner"):
    """A collection workspace in the shape photo-init writes."""
    working = Path(root) / "ws" / "Working Files"
    working.mkdir(parents=True, exist_ok=True)
    (Path(root) / "raw").mkdir(exist_ok=True)
    (working / "collection.json").write_text(json.dumps({
        "collection": "ws", "owner": owner,
        "memory_root": str(Path(root) / "photo-memory"),
        "raw_roots": [str(Path(root) / "raw")],
        "dest_root": str(Path(root) / "sorted"),
    }, indent=2), encoding="utf-8")
    return Path(root) / "ws"


def open_pack(pack_dir):
    return photo_profile.resolve_pack(
        explicit=pack_dir / photo_profile.PROFILE_NAME)


def schmsg_of(pack):
    return photo_profile.schedule_messages(pack.profile)


class Args:
    """The argparse namespace the commands read, with the defaults main()
    would have supplied."""

    def __init__(self, **kw):
        self.collection = None
        self.profile = None
        self.window = None
        self.at = None
        self.notify = None
        self.claude = "/bin/echo"      # never executed; must merely exist
        self.go = False
        self.label = None
        self.started = None
        self.rc = 0
        self.outcome = None
        self.log = None
        self.__dict__.update(kw)


def run(fn, *args, **kw):
    """-> (exit code, printed text). A refusal comes back as (2, message),
    the same shape the CLI produces."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            code = fn(*args, **kw)
        except sch.Refused as refused:
            return 2, refused.message
    return code, buf.getvalue()


def build(tmp, **profile_edits):
    """-> (pack, collection dir, parsed collection, schmsg) ready to render."""
    pack_dir = make_pack(tmp, **profile_edits)
    workspace = make_collection(tmp)
    pack = open_pack(pack_dir)
    schmsg = schmsg_of(pack)
    coll_dir, coll = sch.resolve_collection(workspace, schmsg)
    return pack, coll_dir, coll, schmsg


def rendered(tmp, at=None, window="01:00-06:00", notify="telegram", **edits):
    pack, coll_dir, coll, schmsg = build(tmp, **edits)
    config = {"enabled": True, "collection": str(coll_dir), "window": window,
              "at": at or [185], "notify": notify,
              "label": sch.label_for(pack)}
    return sch.render(pack, coll_dir, coll, config, schmsg, claude="/bin/echo")


def texts(built):
    return {Path(p).name: t for p, t in built["files"].items()}


# ------------------------------------------------- the HIL-stop rule -------

@case
def the_rendered_runner_contains_no_go_anywhere():
    """Half one of the HIL-stop rule. An unattended run plans; it never
    copies."""
    with tempfile.TemporaryDirectory() as tmp:
        runner = texts(rendered(tmp))["run-unattended.sh"]
    offenders = [line for line in runner.splitlines()
                 if "--go" in line and not line.strip().startswith("#")]
    return not offenders, f"{offenders}"


@case
def the_allowlist_does_not_contain_the_copy_stage():
    """Half two, and the half that holds when the prompt is misread. The
    allowlist is what makes the rule enforcement rather than wording."""
    tools = sch.allowed_tools("/usr/bin/python3", SCRIPTS)
    listed = [t for t in tools if "photo_execute" in t]
    return not listed, f"{listed}"


@case
def the_allowlist_gives_photo_run_only_prep_and_status():
    """`photo_run.py plan` and `finish` take the `--go` this run must never
    pass, so they are not on the list at all — the run uses the plan renderer
    directly instead."""
    tools = [t for t in sch.allowed_tools("/usr/bin/python3", SCRIPTS)
             if "photo_run.py" in t]
    subs = sorted(t.split("photo_run.py ")[1].split(":")[0] for t in tools)
    return subs == ["prep", "status"], f"{subs}"


@case
def the_allowlist_reaches_the_runner_verbatim():
    """A list built and never rendered would be a comforting no-op.

    ⚠️ Judged on the EXECUTABLE lines only, like the render guard itself. The
    runner's header comment names `photo_execute.py` on purpose — it is where
    the rule is explained — and a check that could not tell the explanation
    from the thing explained would force the comment to go unwritten."""
    with tempfile.TemporaryDirectory() as tmp:
        runner = texts(rendered(tmp))["run-unattended.sh"]
    code_lines = [ln for ln in runner.splitlines()
                  if not ln.strip().startswith("#")]
    body = "\n".join(code_lines)
    return ("--allowedTools" in body
            and "photo_classify_validate.py" in body
            and "photo_execute" not in body), f"{body[-300:]}"


@case
def a_template_that_regains_go_is_refused_at_render_time():
    """The guard runs at render, not only in this suite: a template edited by
    a later session is caught before it is installed, which is the only moment
    anyone is watching."""
    with tempfile.TemporaryDirectory() as tmp:
        pack, coll_dir, coll, schmsg = build(tmp)
        original = (sch.TEMPLATES / "run-unattended.sh.tmpl").read_text()
        tampered = original.replace('  --model "$MODEL" \\',
                                    '  --model "$MODEL" --go \\')
        config = {"enabled": True, "collection": str(coll_dir),
                  "window": "01:00-06:00", "at": [185], "notify": "none",
                  "label": sch.label_for(pack)}
        path = sch.TEMPLATES / "run-unattended.sh.tmpl"
        try:
            path.write_text(tampered, encoding="utf-8")
            code, message = run(sch.render, pack, coll_dir, coll, config,
                                schmsg, claude="/bin/echo")
        finally:
            path.write_text(original, encoding="utf-8")
    return code == 2 and "--go" in message, f"{code} {message[:160]}"


@case
def a_prompt_that_stops_stating_the_rule_is_refused():
    """The allowlist ENFORCES the rule; the prompt is what explains it and
    pins the classify rules. A prompt edited down to something agreeable is
    how the next session finds no reason not to widen the allowlist."""
    with tempfile.TemporaryDirectory() as tmp:
        pack, coll_dir, coll, schmsg = build(tmp)
        path = sch.TEMPLATES / "unattended-prompt.md.tmpl"
        original = path.read_text()
        config = {"enabled": True, "collection": str(coll_dir),
                  "window": "01:00-06:00", "at": [185], "notify": "none",
                  "label": sch.label_for(pack)}
        try:
            path.write_text(original.replace("Stop before anything is copied",
                                             "Be careful"), encoding="utf-8")
            code, message = run(sch.render, pack, coll_dir, coll, config,
                                schmsg, claude="/bin/echo")
        finally:
            path.write_text(original, encoding="utf-8")
    return code == 2 and "Stop before anything is copied" in message, \
        f"{code} {message[:160]}"


@case
def the_prompt_carries_rule_5_in_full():
    """Operational Rule 5 is three things, not one: the pinned model, the
    `viewed-image:` provenance prefix, and validation BEFORE any plan is
    rendered. A plan built on an unvalidated classify is a rendered guess."""
    with tempfile.TemporaryDirectory() as tmp:
        prompt = texts(rendered(tmp))["unattended-prompt.md"]
    return all(x in prompt for x in ("viewed-image:",
                                     "photo_classify_validate.py",
                                     "opus")), f"{prompt[:200]}"


# ----------------------------------------------------- the model pin -------

@case
def the_classify_model_defaults_to_the_floor_and_is_rendered():
    with tempfile.TemporaryDirectory() as tmp:
        built = rendered(tmp)
    return (built["model"] == photo_settings.CLASSIFY_FLOOR
            and f'MODEL="{built["model"]}"'
            in texts(built)["run-unattended.sh"]), f"{built['model']}"


@case
def a_pack_may_raise_the_model_but_never_lower_it():
    """The floor is policy, not preference — and it is `photo_settings`'
    ladder, called. ⛔ Not re-implemented here: three corrected copies of one
    policy is the same defect waiting (the A24 lesson)."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            lowered = "rendered anyway: " + rendered(
                tmp, models={"classify": "haiku"})["model"]
        except (sch.Refused, photo_settings.Refused) as refused:
            lowered = refused.message
    with tempfile.TemporaryDirectory() as tmp:
        # The other direction must still work, or the floor would read as a
        # pin and an owner could never move up.
        raised = rendered(tmp, models={"classify": "opus"})["model"]
    return ("haiku" in lowered and "floor" in lowered
            and raised == "opus"), f"{lowered[:140]} | raised={raised}"


@case
def the_pinned_model_is_readable_without_opening_a_plist():
    """Lead's requirement: a drift has to be visible in `show`, or it is only
    findable by whoever thinks to look inside a plist."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        workspace = make_collection(tmp)
        _code, out = run(sch.cmd_install,
                         Args(collection=str(workspace), window="01:00-06:00",
                              at=["03:05"]),
                         open_pack(pack_dir),
                         schmsg_of(open_pack(pack_dir)))
    return photo_settings.CLASSIFY_FLOOR in out, f"{out[:300]}"


# ------------------------------------------------------ nothing without --go

@case
def a_dry_run_writes_no_file_and_stores_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        workspace = make_collection(tmp)
        pack = open_pack(pack_dir)
        before = (pack_dir / photo_profile.PROFILE_NAME).read_text()
        code, _out = run(sch.cmd_install,
                         Args(collection=str(workspace), window="01:00-06:00",
                              at=["03:05"]), pack, schmsg_of(pack))
        after = (pack_dir / photo_profile.PROFILE_NAME).read_text()
        wrote = list((workspace / "Working Files" / "schedule").glob("*")) \
            if (workspace / "Working Files" / "schedule").exists() else []
    return code == 0 and before == after and not wrote, f"{code} {wrote}"


@case
def rendering_puts_nothing_inside_the_engine_tree():
    """Rule 7 from the operational side: what this tool writes is the owner's,
    and it lives with the owner's photos."""
    with tempfile.TemporaryDirectory() as tmp:
        built = rendered(tmp)
    inside = [str(p) for p in built["files"]
              if str(ROOT) in str(p) and "LaunchAgents" not in str(p)]
    return not inside, f"{inside}"


# ------------------------------------------------------- window and times --

@case
def an_off_hours_window_may_wrap_past_midnight():
    schmsg = photo_profile.schedule_messages({})
    window = sch.parse_window("22:00-06:00", schmsg)
    return (sch.in_window(sch.parse_time("23:30", schmsg), window)
            and sch.in_window(sch.parse_time("05:00", schmsg), window)
            and not sch.in_window(sch.parse_time("12:00", schmsg), window)), \
        f"{window}"


@case
def a_start_time_outside_the_window_is_refused_not_moved():
    """The window is the promise that the run never competes with the owner
    for the machine, so a time outside it is refused rather than adjusted."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        workspace = make_collection(tmp)
        pack = open_pack(pack_dir)
        code, message = run(sch.cmd_install,
                            Args(collection=str(workspace),
                                 window="01:00-06:00", at=["14:00"]),
                            pack, schmsg_of(pack))
    return code == 2 and "14:00" in message, f"{code} {message[:160]}"


@case
def a_malformed_window_or_time_is_named_rather_than_guessed():
    schmsg = photo_profile.schedule_messages({})
    outcomes = []
    for bad in ("1am-6am", "01:00", "25:00-26:00"):
        try:
            sch.parse_window(bad, schmsg)
            outcomes.append(f"accepted {bad}")
        except sch.Refused as refused:
            outcomes.append(bad if bad in refused.message else
                            f"unnamed {bad}")
    return outcomes == ["1am-6am", "01:00", "25:00-26:00"], f"{outcomes}"


# ------------------------------------------------------------ refusals -----

@case
def no_collection_is_a_sentence_saying_what_to_pass():
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        code, message = run(sch.cmd_install, Args(window="01:00-06:00",
                                                  at=["03:05"]),
                            pack, schmsg_of(pack))
    return code == 2 and "--collection" in message, f"{code} {message[:160]}"


@case
def a_folder_that_is_not_a_collection_is_named():
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        empty = Path(tmp) / "not-a-collection"
        empty.mkdir()
        code, message = run(sch.cmd_install,
                            Args(collection=str(empty), window="01:00-06:00",
                                 at=["03:05"]), pack, schmsg_of(pack))
    return code == 2 and "collection.json" in message, f"{code} {message[:160]}"


@case
def with_no_pack_it_still_answers_and_refuses_only_the_write():
    """A27's clean sheet taken to its limit: no pack at all. `show` answers,
    and it is the WRITE that has nowhere to go — the same posture
    `photo_settings set` takes."""
    pack = photo_profile.Pack()
    schmsg = schmsg_of(pack)
    show_code, show_out = run(sch.cmd_show, Args(), pack, schmsg)
    store_code, store_msg = run(sch.store, pack,
                                {"enabled": True}, schmsg)
    return (show_code == 0 and show_out.strip()
            and store_code == 2 and "pack" in store_msg), \
        f"{show_code} {store_code} {store_msg[:120]}"


@case
def a_clean_sheet_pack_renders_without_a_schedule_in_it():
    """A27. The pack the wizard writes INTO is the blank one, and `show` on it
    must answer rather than trip over the absent key."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp))
        code, out = run(sch.cmd_show, Args(), pack, schmsg_of(pack))
    return code == 0 and "install" in out, f"{code} {out[:160]}"


# --------------------------------------------------------- rendered shape --

@case
def the_plist_is_valid_and_carries_the_label_and_every_start_time():
    with tempfile.TemporaryDirectory() as tmp:
        built = rendered(tmp, at=[185, 485])
        plist_path = [p for p in built["files"] if str(p).endswith(".plist")][0]
        parsed = plistlib.loads(built["files"][plist_path].encode("utf-8"))
    times = {(d["Hour"], d["Minute"]) for d in parsed["StartCalendarInterval"]}
    return (parsed["Label"] == built["label"]
            and times == {(3, 5), (8, 5)}
            and parsed["RunAtLoad"] is False), f"{parsed.get('Label')} {times}"


@case
def the_runner_guards_on_the_collections_own_roots():
    """A drive that is unplugged is a normal night. The guard list comes from
    the collection, never from anything hardcoded (rule 7)."""
    with tempfile.TemporaryDirectory() as tmp:
        built = rendered(tmp)
        runner = texts(built)["run-unattended.sh"]
    return (str(Path(tmp) / "raw") in runner
            and str(Path(tmp) / "sorted") in runner), f"{runner[:200]}"


@case
def the_label_is_generic_and_carries_the_owner_slug():
    """Rule 7: the prefix ships, so it may name no person and no company; the
    slug arrives at runtime from the pack."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(tmp, owner="someone-else"))
        label = sch.label_for(pack)
    return (label.startswith("com.kcc-photo-manager.")
            and label.endswith("someone-else")), label


# ------------------------------------------------------------- the morning -

@case
def status_reports_what_is_waiting_for_the_owner():
    """The morning answer, read off the work dirs rather than off anything the
    run claimed — a run that died before reporting still left its evidence."""
    with tempfile.TemporaryDirectory() as tmp:
        _pack, coll_dir, _coll, schmsg = build(tmp)
        workdir = coll_dir / "202601__"
        (workdir / "plan").mkdir(parents=True)
        (workdir / "plan" / "plan_P1.md").write_text("x", encoding="utf-8")
        # Card 9: a proposals file waits only on a size the pack has not
        # answered, so the fixture carries one ("{}" used to be enough).
        (workdir / "plan" / "screen-size-proposals.json").write_text(
            '{"proposed_screen_dims": [{"dims": [1080, 1462]}]}',
            encoding="utf-8")
        (workdir / "memory-review_C1.md").write_text("x", encoding="utf-8")
        waiting = sch.waiting_for_owner(coll_dir, schmsg)
    return len(waiting) == 3, f"{waiting}"


@case
def a_batch_page_is_waiting_for_the_owner_too():
    """REPRODUCTION (G6-1). A `P-B03.md` batch page is a page the owner has to
    answer, the same as a checkpoint page. ⛔ FAILS on ce4eb56: only
    `memory-review_C*.md` was counted, so the morning said nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        _pack, coll_dir, _coll, schmsg = build(tmp)
        workdir = coll_dir / "202601__"
        workdir.mkdir(parents=True)
        (workdir / "P-B03.md").write_text("x", encoding="utf-8")
        waiting = sch.waiting_for_owner(coll_dir, schmsg)
    return len(waiting) == 1, f"{waiting}"


@case
def a_quiet_night_says_nothing_is_waiting():
    with tempfile.TemporaryDirectory() as tmp:
        _pack, coll_dir, _coll, schmsg = build(tmp)
        waiting = sch.waiting_for_owner(coll_dir, schmsg)
    return waiting == [], f"{waiting}"


@case
def the_runner_records_its_outcome_for_the_morning():
    """The runner calls back into this file so the state file has one writer
    and one shape — including on the nights it skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        _pack, coll_dir, _coll, _smsg = build(tmp)
        sch.cmd_record(Args(label="com.kcc-photo-manager.x",
                            collection=str(coll_dir),
                            started="2026-09-01T03:05:00", rc=0,
                            outcome="skipped — not mounted", log="/x.out"),
                       None, None)
        state = sch.read_state(coll_dir, "com.kcc-photo-manager.x")
    return (state.get("outcome", "").startswith("skipped")
            and state.get("rc") == 0), f"{state}"


# ------------------------------------------------------------- language ----

@case
def an_owner_can_translate_the_whole_surface_from_their_pack():
    """ONB-9's ladder, rule 8. The engine ships English; any other language
    arrives from the pack — including one the engine has no table for."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = open_pack(make_pack(
            tmp, language="sv",
            schedule_messages={"sched_not_configured": "inget schema"}))
        _code, out = run(sch.cmd_show, Args(), pack, schmsg_of(pack))
    return "inget schema" in out, f"{out[:160]}"


@case
def nothing_in_the_schedule_defaults_is_an_owners_fact():
    """Rule 7 from the other side: what this module ships is the ENGINE's, so
    it must be the same for every owner — no path, no place, no drive."""
    suspicious = [v for v in (sch.LABEL_PREFIX, sch.SCHEDULE_DIRNAME,
                              sch.STATE_NAME)
                  if "/" in v or "Volumes" in v]
    return not suspicious, f"{suspicious}"


# ------------------------------------------------ protected folders --------

@case
def a_protected_folder_is_detected_by_path_not_by_name():
    """MEASURED 20260901: a launchd agent reading under ~/Documents blocks in
    open(2) forever rather than failing. The detector compares against the
    real home, so a path that merely contains the WORD is not flagged — a
    false positive here would train the owner to ignore the one warning that
    matters."""
    home = Path.home()
    hits = sch.protected_paths(home / "Documents" / "engine" / "scripts",
                               Path("/Volumes/Drive/Documents/photos"),
                               home / "Projects" / "engine")
    return ([str(h[1]) for h in hits] == [str(home / "Documents")]), f"{hits}"


@case
def install_warns_when_the_engine_sits_in_a_protected_folder():
    """It has to be said while the owner is awake. At 3am there is nobody to
    answer the permission prompt, so the job waits forever and reports
    nothing — the failure this warning exists to pre-empt."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        workspace = make_collection(tmp)
        pack = open_pack(pack_dir)
        real = sch.HERE
        try:
            sch.HERE = Path.home() / "Documents" / "engine" / "scripts"
            _code, out = run(sch.cmd_install,
                             Args(collection=str(workspace),
                                  window="01:00-06:00", at=["03:05"]),
                             pack, schmsg_of(pack))
        finally:
            sch.HERE = real
    return ("Documents" in out and "Full Disk Access" in out), f"{out[-400:]}"


@case
def an_unprotected_layout_gets_no_warning():
    """The other half: a warning that always fires is not a warning."""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = make_pack(tmp)
        workspace = make_collection(tmp)
        pack = open_pack(pack_dir)
        real = sch.HERE
        try:
            sch.HERE = Path(tmp) / "engine" / "scripts"
            _code, out = run(sch.cmd_install,
                             Args(collection=str(workspace),
                                  window="01:00-06:00", at=["03:05"]),
                             pack, schmsg_of(pack))
        finally:
            sch.HERE = real
    return "Full Disk Access" not in out, f"{out[-200:]}"


@case
def the_runner_time_boxes_every_call_it_makes():
    """Without this a blocked read leaves a stuck process and an empty log
    forever — measured, three hours and still going. The probe runs BEFORE
    anything slow, so 'permission was never granted' cannot be mistaken for
    'nothing to do'."""
    with tempfile.TemporaryDirectory() as tmp:
        runner = texts(rendered(tmp))["run-unattended.sh"]
    probe = runner.index('with_timeout "$PROBE_TIMEOUT" "$PYTHON"')
    return ("with_timeout()" in runner
            and probe < runner.index("for required")
            and "return 124" in runner), "probe/order/timeout"


# --------------------------------------------------------------- platform --

@case
def off_macos_it_says_so_instead_of_half_supporting_cron():
    """§3C, verbatim: macOS-only at release, and the wizard says so. A cron
    job written here would not behave the same way and the owner would find
    that out at 3am."""
    real = sch.platform.system
    try:
        sch.platform.system = lambda: "Linux"
        schmsg = photo_profile.schedule_messages({})
        code, message = run(sch.need_macos, schmsg)
    finally:
        sch.platform.system = real
    return code == 2 and "launchd" in message and "Linux" in message, \
        f"{code} {message[:160]}"


@case
def rendering_still_works_off_macos():
    """The templates stay testable on a machine that can never install them,
    which is the only reason this suite runs anywhere."""
    real = sch.platform.system
    try:
        sch.platform.system = lambda: "Linux"
        with tempfile.TemporaryDirectory() as tmp:
            built = rendered(tmp)
    finally:
        sch.platform.system = real
    return len(built["files"]) == 3, f"{list(built['files'])}"


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

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} schedule cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
