#!/usr/bin/env python3
"""SET-3 — the conversational schedule wizard. Renders the proven launchd
template, installs it, and can status / pause / resume / remove it.

  python3 photo_schedule.py show    [--collection C] [--profile P]
  python3 photo_schedule.py install --collection C --window 01:00-06:00
                                    --at 03:05 [--notify telegram] [--go]
  python3 photo_schedule.py status  [--collection C] [--profile P]
  python3 photo_schedule.py pause   [--go]
  python3 photo_schedule.py resume  [--go]
  python3 photo_schedule.py remove  [--go]

Exit 0 = the command answered. A refusal exits 2, so a caller can tell "I
would not do that" from "something broke". Nothing is written or loaded
without `--go`, like every other stage in this engine.

Six things this file is careful about.

**The HIL-stop rule is the product, and it is enforced twice.** An unattended
run may sort, group, look and plan; it may never copy. Prose in the rendered
prompt is not enforcement, so the rendered runner also passes a tool allowlist
that does not contain `photo_execute.py` — the one script that writes to the
drive. A 3am run that misread its instructions still cannot reach the copy
stage. `no_go_in_executables()` asserts the first half over the rendered
bytes at render time; the suite asserts the second.

⚠️ This is deliberately NARROWER than D10, and it does not amend it. D10
removed the pre-execution approval gate for a run someone is watching, on the
grounds that copy-only is reversible. An unattended run is the other
situation: nobody reads the folder name before it exists, and this project's
own Tier 3 judgement is that naming is not yet trustworthy unattended. So the
gate comes back for this path only. Nothing here touches `photo_execute.py`.

**The classify model is pinned, never inherited** (Operational Rule 5, after
the 2026-07-20 fabrication incident). The pin is resolved here, written into
the runner, and printed by `show` and `status` — a drift has to be readable
without opening a plist. ⛔ The floor itself is NOT re-implemented here: it is
`photo_settings`' ladder, called. Three corrected copies of a policy is the
same defect waiting (the A24 lesson, one predicate).

**launchd, and it says so.** macOS only at release. On another platform the
commands that touch launchd refuse with a sentence saying why, rather than
half-supporting cron — a cron job would not behave the same way and the owner
would find that out at 3am. Rendering still works anywhere, so the templates
stay testable off a Mac.

**The schedule is owner data.** It lives in the pack under `schedule.*` —
where `photo_settings.py` already surfaces `schedule.enabled` and
`schedule.window` read-only, saying this wizard owns them (SET-1 left the
seam deliberately). The engine holds the shape and the defaults, never one
owner's window, path or drive.

**A missing drive is a normal night, not a failure.** The rendered runner
checks the collection's own roots and exits 0 when one is unplugged, so
launchd never throttles the job for repeated failure.

**Every path it writes is the owner's, not the repo's.** The runner, prompt
and logs live under the collection workspace; only the plist goes to
`~/Library/LaunchAgents/`. Nothing is rendered into the engine tree.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import photo_profile  # noqa: E402
import photo_settings  # noqa: E402

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates" / "schedule"

# Generic by construction: the owner's slug is appended at runtime. ⛔ Never
# put a person or an organisation in this prefix — it ships (rule 7).
LABEL_PREFIX = "com.kcc-photo-manager"

# Where the rendered runner/prompt/logs live, under the collection workspace.
SCHEDULE_DIRNAME = "schedule"
STATE_NAME = "schedule-state.json"

NOTIFY_CHOICES = ("telegram", "none")

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

# The stage scripts an unattended run may drive. ⛔ `photo_execute.py` is
# absent BY DESIGN — it is the only script that writes to the drive, and its
# absence is half of the HIL-stop enforcement. `photo_run.py` appears only as
# `prep` and `status`: its `plan` and `finish` take the `--go` this run must
# never pass, so the run uses the plan RENDERER directly instead.
STAGE_SCRIPTS = ("photo_scan.py", "photo_cluster.py", "photo_sample.py",
                 "photo_see.py", "photo_embed.py", "photo_recurrence.py",
                 "photo_subjects.py", "photo_identity.py", "photo_dedupe.py",
                 "photo_where.py", "photo_classify_set.py",
                 "photo_classify_validate.py", "photo_plan.py",
                 "photo_memory.py", "photo_census.py")
RUN_SUBCOMMANDS = ("prep", "status")
# Reading and authoring `plans.json` is the owner-facing judgement step the
# run still has to perform; it writes into the work dir, never to the drive.
BASE_TOOLS = ("Read", "Grep", "Glob", "Write", "Edit")

FORBIDDEN_IN_RENDER = ("--go", "photo_execute")

# ⛔ MEASURED on macOS 20260901, not inferred. A launchd agent that reads a
# file under one of these blocks in open(2) INDEFINITELY rather than failing:
# the system wants a consent decision and there is nobody awake to give one.
# Controlled test, one variable — the same job, interpreter and arguments ran
# in under a second with the script under /private/tmp, and was still blocked
# three hours later with the script under ~/Documents.
#
# This is a warning and not a refusal on purpose: an owner who has already
# granted Full Disk Access is fine, and this tool cannot see that from here.
# What it must not do is install a job that hangs silently and say nothing.
TCC_PROTECTED_DIRS = ("Documents", "Desktop", "Downloads")


class Refused(Exception):
    """A thing this tool will not do, with the sentence saying why. Raised
    rather than printed where it is detected, so every refusal leaves by one
    door and the command can exit 2 from it."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------- times ----

def parse_time(value, schmsg):
    """'03:05' -> minutes past midnight."""
    m = TIME_RE.match(str(value).strip())
    if not m:
        raise Refused(schmsg["sched_refuse_bad_time"].format(value=value))
    return int(m.group(1)) * 60 + int(m.group(2))


def parse_window(value, schmsg):
    """'01:00-06:00' -> (start, end) in minutes. May wrap past midnight, which
    is the normal case for an off-hours window."""
    parts = str(value).split("-")
    if len(parts) != 2:
        raise Refused(schmsg["sched_refuse_bad_window"].format(value=value))
    try:
        start, end = (parse_time(p, schmsg) for p in parts)
    except Refused:
        raise Refused(schmsg["sched_refuse_bad_window"].format(value=value))
    return start, end


def in_window(minute, window):
    """Inclusive of both ends. A window whose end is at or before its start
    wraps past midnight (22:00-06:00), which is what an off-hours window
    usually looks like."""
    start, end = window
    if start <= end:
        return start <= minute <= end
    return minute >= start or minute <= end


def hhmm(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


# ------------------------------------------------------------ collection ---

def resolve_collection(given, schmsg):
    """-> (the directory holding collection.json, its parsed contents).

    Accepts the workspace or the `Working Files` dir inside it, because an
    owner types the folder they think of as 'the collection' and either answer
    is reasonable."""
    if not given:
        raise Refused(schmsg["sched_refuse_no_collection"])
    root = Path(given).expanduser().resolve()
    for candidate in (root / "collection.json",
                      root / "Working Files" / "collection.json"):
        if candidate.exists():
            return candidate.parent, json.loads(
                candidate.read_text(encoding="utf-8"))
    raise Refused(schmsg["sched_refuse_collection_missing"].format(path=root))


def guard_paths(collection):
    """The directories that vanish when the drive is unplugged. Deliberately
    the configured roots themselves rather than a derived mount point: a
    `/Volumes/X/Raw` that is not there is exactly the question being asked,
    and deriving `/Volumes/X` from it would guess at a layout."""
    roots = list(collection.get("raw_roots") or [])
    if collection.get("dest_root"):
        roots.append(collection["dest_root"])
    seen, out = set(), []
    for r in roots:
        r = str(r)
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# ----------------------------------------------------------------- pack ----

def protected_paths(*paths):
    """-> [(path, the protected folder it sits in)] for every path a scheduled
    run has to read. Compared against the real home directory rather than a
    string, so a path that merely CONTAINS the word "Documents" is not
    flagged."""
    home = Path.home().resolve()
    out = []
    for path in paths:
        if not path:
            continue
        resolved = Path(path).expanduser().resolve()
        for folder in TCC_PROTECTED_DIRS:
            root = home / folder
            if resolved == root or root in resolved.parents:
                out.append((resolved, root))
                break
    return out


def warn_protected(schmsg, *paths):
    """Print the warning if any path is protected. -> True if it warned."""
    hits = protected_paths(*paths)
    if not hits:
        return False
    print(schmsg["sched_warn_protected"])
    for path, folder in hits:
        print(schmsg["sched_warn_protected_path"].format(path=path,
                                                         folder=folder))
    print()
    print("  " + schmsg["sched_warn_protected_fix"])
    return True


def classify_model(pack, collection, schmsg):
    """The pinned classify model, resolved through the SAME layered resolution
    and the SAME floor as `photo_settings`. ⛔ Not re-implemented here: the
    floor is policy (L01) and a second copy of a policy is the defect that
    policy exists to prevent."""
    setting = photo_settings.BY_KEY["models.classify"]
    state = photo_settings.resolve(setting, pack.profile, collection, {})
    value = state["value"]
    # A pack carrying a model this engine cannot place on the ladder must not
    # be silently pinned into a 3am run — that is the fabrication incident's
    # exact shape. Refuse in the wizard's own words.
    setting.check(value, photo_profile.settings_messages(pack.profile))
    return value


def stored(pack):
    return photo_profile.get(pack.profile, "schedule", default=None) or {}


def label_for(pack):
    slug = (pack.owner or (pack.profile.get("owner") or {}).get("slug")
            or "default")
    return f"{LABEL_PREFIX}.{slug}"


# -------------------------------------------------------------- rendering --

def allowed_tools(python, scripts_dir):
    """The allowlist the rendered runner passes to `claude -p`. Anything
    unlisted is refused rather than asked, so nothing waits for a click at
    3am — and the copy stage is not on it."""
    tools = list(BASE_TOOLS)
    for sub in RUN_SUBCOMMANDS:
        tools.append(f"Bash({python} {scripts_dir}/photo_run.py {sub}:*)")
    for script in STAGE_SCRIPTS:
        tools.append(f"Bash({python} {scripts_dir}/{script}:*)")
    return tools


def calendar_block(times):
    rows = []
    for minute in times:
        rows.append("        <dict>\n"
                    f"            <key>Hour</key><integer>{minute // 60}</integer>\n"
                    f"            <key>Minute</key><integer>{minute % 60}</integer>\n"
                    "        </dict>")
    return "\n".join(rows)


def paths_for(collection_dir, label):
    base = Path(collection_dir) / SCHEDULE_DIRNAME
    return {"base": base,
            "runner": base / "run-unattended.sh",
            "prompt": base / "unattended-prompt.md",
            "logs": base / "logs",
            "state": base / STATE_NAME,
            "plist": (Path.home() / "Library" / "LaunchAgents"
                      / f"{label}.plist")}


def fill(template, values):
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", str(value))
    return out


def render(pack, collection_dir, collection, config, schmsg, claude=None,
           python=None):
    """-> {label, paths, files: {path: text}}. Pure: it reads templates and
    returns text, and touches nothing on disk. `install` is the only caller
    that writes, and the suite renders without writing."""
    label = label_for(pack)
    paths = paths_for(collection_dir, label)
    python = python or sys.executable
    claude = claude or shutil.which("claude") or ""
    if not claude:
        raise Refused(schmsg["sched_refuse_no_claude"])

    model = classify_model(pack, collection, schmsg)
    guards = " ".join(f'"{g}"' for g in guard_paths(collection)) or '""'
    tools = " ".join(f"'{t}'" for t in allowed_tools(python, HERE))

    notify_line = ("Then send that summary to the owner over Telegram, the "
                   "way this machine already sends its other notifications. "
                   "If you cannot, say so in the log and stop — the log file "
                   "below is the durable record either way."
                   if config["notify"] == "telegram" else
                   "There is no message to send: the log file is the record, "
                   "and the owner reads it when they choose to.")

    values = {"LABEL": label,
              "RUNNER": paths["runner"],
              "CALENDAR": calendar_block(config["at"]),
              "STDOUT": paths["logs"] / "launchd_stdout.log",
              "STDERR": paths["logs"] / "launchd_stderr.log",
              "COLLECTION": collection_dir,
              "SCRIPTS": HERE,
              "PROMPT": paths["prompt"],
              "LOGDIR": paths["logs"],
              "CLAUDE": claude,
              "PYTHON": python,
              "MODEL": model,
              "WINDOW": config["window"],
              "GUARDS": guards,
              "ALLOWED_TOOLS": tools,
              "NOTIFY_LINE": notify_line}

    plist = fill((TEMPLATES / "launchd.plist.tmpl")
                 .read_text(encoding="utf-8"), values)
    runner = fill((TEMPLATES / "run-unattended.sh.tmpl")
                  .read_text(encoding="utf-8"), values)
    prompt = fill((TEMPLATES / "unattended-prompt.md.tmpl")
                  .read_text(encoding="utf-8"), values)

    no_go_in_executables({paths["plist"]: plist, paths["runner"]: runner})
    prompt_states_the_rule(prompt, paths["prompt"])

    files = {paths["plist"]: plist, paths["runner"]: runner,
             paths["prompt"]: prompt}
    return {"label": label, "paths": paths, "files": files, "model": model}


def no_go_in_executables(files):
    """The HIL-stop rule, asserted over the rendered bytes rather than trusted.

    ⛔ Scoped to the files that EXECUTE — the runner and the plist. The prompt
    is prose and is judged separately, because it has to be able to NAME the
    things it forbids; a check that could not tell "never pass --go" from
    "pass --go" would force the prohibition to go unwritten, which is the
    opposite of what it is for.

    ⛔ Checked at RENDER time, not only in the suite: a template edited by a
    later session is caught before it is installed, which is the only moment
    anyone is watching."""
    for path, text in files.items():
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("<!--"):
                continue
            for token in FORBIDDEN_IN_RENDER:
                if token in line:
                    raise Refused(
                        f"refusing to render {Path(path).name}: it contains "
                        f"{token!r} on a line that is not a comment. An "
                        "unattended run must never copy — see the HIL-stop "
                        "rule in photo_schedule.py.")


# What the prompt must still be saying for the rule to have been stated at
# all. A template edited down to something agreeable is the failure this
# catches: the allowlist would still hold, but the run would no longer be TOLD
# why, and the next person to widen the allowlist would find no reason not to.
PROMPT_MUST_SAY = ("Stop before anything is copied", "photo_execute",
                   "viewed-image:", "photo_classify_validate.py")


def prompt_states_the_rule(text, path):
    missing = [phrase for phrase in PROMPT_MUST_SAY if phrase not in text]
    if missing:
        raise Refused(
            f"refusing to render {Path(path).name}: it no longer states "
            f"{missing}. The tool allowlist is what ENFORCES the HIL-stop "
            "rule, but the prompt is what explains it and pins the classify "
            "rules (Operational Rule 5) — a run told nothing is a run the "
            "next edit widens.")


# --------------------------------------------------------------- launchd ---

def is_macos():
    return platform.system() == "Darwin"


def need_macos(schmsg):
    if not is_macos():
        raise Refused(schmsg["sched_refuse_not_macos"].format(
            platform=platform.system() or "unknown"))


def domain():
    return f"gui/{os.getuid()}"


def launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def is_loaded(label):
    return launchctl("print", f"{domain()}/{label}").returncode == 0


def launchd_runs(label):
    """How many times launchd has started the job. Read from launchd rather
    than from our own state file, because the two disagreeing is exactly the
    signal worth reporting."""
    got = launchctl("print", f"{domain()}/{label}")
    if got.returncode != 0:
        return 0
    found = re.search(r"\bruns\s*=\s*(\d+)", got.stdout)
    return int(found.group(1)) if found else 0


def launchd_detail(label):
    """-> (loaded, last_exit_code or None). `launchctl print` is the only
    place the real state lives; the pack records intent, not fact."""
    got = launchctl("print", f"{domain()}/{label}")
    if got.returncode != 0:
        return False, None
    last = re.search(r"last exit code\s*=\s*(\d+)", got.stdout)
    return True, (int(last.group(1)) if last else None)


# ---------------------------------------------------------------- status ---

def waiting_for_owner(collection_dir, schmsg, profile=None):
    """What an unattended run has queued up for the owner. This is the morning
    answer, and it is read off the work dirs rather than off anything the run
    claimed — a run that died before reporting still leaves its evidence.

    `profile` is the pack a screen size is checked against; None resolves it
    from each work dir's own collection.json."""
    out = []
    root = Path(collection_dir)
    plans = 0
    for workdir in sorted(p for p in root.iterdir() if p.is_dir()):
        if workdir.name in (SCHEDULE_DIRNAME, "photo-memory"):
            continue
        plans += len(list((workdir / "plan").glob("plan_P*.md")))
        proposals = workdir / "plan" / "screen-size-proposals.json"
        if proposals.exists():
            # Card 9 — only a size the owner has not answered, and the one
            # route that adds it: the onboarding sheet's `screen:` line.
            here = profile
            if here is None:
                # A pack that cannot be resolved must not stop the morning
                # answer: every size is then listed as unanswered.
                try:
                    here = photo_profile.resolve_pack(workdir=workdir).profile
                except SystemExit:
                    here = {}
            sizes = photo_profile.open_screen_proposals(proposals, here)
            if sizes:
                out.append(schmsg["sched_waiting_screens"].format(
                    n=len(sizes), where=workdir.name,
                    sizes=", ".join("%sx%s" % tuple(d) for d in sizes),
                    command=f'python3 {HERE}/photo_onboard_page.py sheet '
                            f'"{workdir}" --out-dir <folder>'))
        # LL-PHO-94: these are globbed wider than they are parsed, so this
        # counts pages and never tries to read one. Both page shapes: a
        # checkpoint page and a G6 batch page (`P-B03.md`).
        if any(workdir.glob("memory-review_C*.md")) or any(workdir.glob("P-B*.md")):
            out.append(schmsg["sched_waiting_memory"].format(where=workdir.name))
    if plans:
        out.insert(0, schmsg["sched_waiting_plan_review"].format(
            n=plans, where=root))
    return out


def read_state(collection_dir, label):
    path = paths_for(collection_dir, label)["state"]
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


# -------------------------------------------------------------- commands ---

def print_config(config, schmsg, model=None):
    rows = [(schmsg["sched_collection"], config.get("collection", "—")),
            (schmsg["sched_window"], config.get("window", "—")),
            (schmsg["sched_at"], ", ".join(hhmm(m) for m in config.get("at", []))
             or "—"),
            (schmsg["sched_notify"],
             schmsg["sched_notify_telegram"] if config.get("notify") == "telegram"
             else schmsg["sched_notify_none"]),
            (schmsg["sched_label"], config.get("label", "—"))]
    if model:
        # Operational Rule 5: the pin has to be readable without opening a
        # plist, or a drift is only findable by whoever thinks to look.
        rows.append((schmsg["sched_model_pinned"], model))
    width = max(len(r[0]) for r in rows)
    for name, value in rows:
        print(f"  {name.ljust(width)}   {value}")


def config_from_args(args, pack, schmsg, collection_dir=None):
    """The four questions of §3C, from flags or from what the pack already
    holds. A re-install that changes one answer keeps the other three."""
    was = stored(pack)
    window = args.window or was.get("window")
    if not window:
        raise Refused(schmsg["sched_refuse_bad_window"].format(value="(none)"))
    bounds = parse_window(window, schmsg)

    if args.at:
        times = [parse_time(t, schmsg) for t in args.at]
    else:
        times = [parse_time(t, schmsg) for t in (was.get("at") or [])]
    if not times:
        raise Refused(schmsg["sched_refuse_no_at"].format(window=window))
    for minute in times:
        if not in_window(minute, bounds):
            raise Refused(schmsg["sched_refuse_outside_window"].format(
                value=hhmm(minute), window=window))

    notify = args.notify or was.get("notify") or "telegram"
    return {"enabled": True,
            "collection": str(collection_dir) if collection_dir
            else was.get("collection"),
            "window": window,
            "at": sorted(times),
            "notify": notify,
            "label": label_for(pack)}


def store(pack, config, schmsg):
    if not pack.dir:
        raise Refused(schmsg["sched_refuse_no_pack"])
    after = json.loads(json.dumps(pack.profile))
    photo_settings.put(after, ("schedule",), dict(config))
    return photo_settings.write_profile(pack, after)


def cmd_show(args, pack, schmsg):
    config = stored(pack)
    if not config:
        print(schmsg["sched_not_configured"])
        print()
        print("  " + schmsg["sched_hil_rule"])
        return 0
    print(schmsg["sched_configured"])
    model = None
    try:
        collection_dir, collection = resolve_collection(
            args.collection or config.get("collection"), schmsg)
        model = classify_model(pack, collection, schmsg)
    except Refused:
        collection_dir = None
    print_config(config, schmsg, model=model)
    print()
    label = config.get("label") or label_for(pack)
    if is_macos():
        loaded, _rc = launchd_detail(label)
        if loaded:
            print(schmsg["sched_installed"].format(
                when=", ".join(hhmm(m) for m in config.get("at", []))))
        elif config.get("paused"):
            print(schmsg["sched_installed_paused"])
        else:
            print(schmsg["sched_not_installed"])
    else:
        print(schmsg["sched_refuse_not_macos"].format(
            platform=platform.system() or "unknown"))
    print()
    print("  " + schmsg["sched_hil_rule"])
    return 0


def cmd_install(args, pack, schmsg):
    collection_dir, collection = resolve_collection(args.collection, schmsg)
    config = config_from_args(args, pack, schmsg, collection_dir=collection_dir)
    built = render(pack, collection_dir, collection, config, schmsg,
                   claude=args.claude)
    label = built["label"]

    if args.go and is_macos() and is_loaded(label):
        raise Refused(schmsg["sched_refuse_already"].format(label=label))

    print(schmsg["sched_would_write"] if not args.go else schmsg["sched_wrote"])
    for path in built["files"]:
        print(f"  {path}")
    print()
    print_config(config, schmsg, model=built["model"])
    print()
    print("  " + schmsg["sched_hil_rule"])
    print()
    # Said BEFORE the write, and on the dry run too: the whole point is that
    # the owner reads it while awake.
    if warn_protected(schmsg, HERE, collection_dir):
        print()

    if not args.go:
        print(schmsg["sched_would_load"].format(label=label))
        print(schmsg["sched_dry_run"])
        return 0

    need_macos(schmsg)
    paths = built["paths"]
    paths["base"].mkdir(parents=True, exist_ok=True)
    paths["logs"].mkdir(parents=True, exist_ok=True)
    paths["plist"].parent.mkdir(parents=True, exist_ok=True)
    for path, text in built["files"].items():
        Path(path).write_text(text, encoding="utf-8")
    paths["runner"].chmod(0o700)

    got = launchctl("bootstrap", domain(), str(paths["plist"]))
    if got.returncode != 0 and not is_loaded(label):
        raise Refused(schmsg["sched_launchctl_failed"].format(
            detail=(got.stderr or got.stdout).strip()))
    config.pop("paused", None)
    store(pack, config, schmsg)
    print(schmsg["sched_loaded"].format(label=label))
    return 0


def cmd_status(args, pack, schmsg):
    config = stored(pack)
    if not config:
        print(schmsg["sched_not_configured"])
        return 0
    label = config.get("label") or label_for(pack)
    print_config(config, schmsg)
    print()
    if is_macos():
        loaded, last_rc = launchd_detail(label)
        if loaded:
            print(schmsg["sched_installed"].format(
                when=", ".join(hhmm(m) for m in config.get("at", []))))
        elif config.get("paused"):
            print(schmsg["sched_installed_paused"])
        else:
            print(schmsg["sched_not_installed"])
    else:
        print(schmsg["sched_refuse_not_macos"].format(
            platform=platform.system() or "unknown"))

    collection_dir = config.get("collection")
    if collection_dir and Path(collection_dir).is_dir():
        state = read_state(collection_dir, label)
        if state.get("started"):
            print(schmsg["sched_last_run"].format(
                when=state["started"], code=state.get("rc", "?")))
            if state.get("log"):
                print(schmsg["sched_log"].format(path=state["log"]))
        else:
            print(schmsg["sched_never_run"])
        # launchd counted a run that left no record of itself. That is what a
        # permission block looks like from the outside, so name it rather than
        # leaving the owner with a silent job.
        if warn_protected(schmsg, HERE, collection_dir):
            print()
        if is_macos() and not state.get("started") \
                and launchd_runs(label) > 0:
            print(schmsg["sched_run_never_reported"])
        print()
        pending = waiting_for_owner(collection_dir, schmsg,
                                    pack.profile if pack.dir else None)
        if pending:
            print(schmsg["sched_hil_waiting"].format(what=""))
            for item in pending:
                print(f"  - {item}")
            print()
            print("  " + schmsg["sched_morning_next_step"].format(
                command=f"python3 {HERE}/photo_run.py finish <dump> --go"))
        else:
            print(schmsg["sched_hil_waiting_none"])
    return 0


def cmd_pause(args, pack, schmsg):
    need_macos(schmsg)
    config = stored(pack)
    label = config.get("label") or label_for(pack)
    if not config:
        raise Refused(schmsg["sched_refuse_not_installed"].format(
            label=label, action="pause"))
    if not args.go:
        print(schmsg["sched_paused"].format(label=label))
        print(schmsg["sched_dry_run"])
        return 0
    launchctl("bootout", f"{domain()}/{label}")
    # `disable` is what survives a reboot; bootout alone does not, because a
    # plist in ~/Library/LaunchAgents loads again at the next login.
    launchctl("disable", f"{domain()}/{label}")
    config["paused"] = True
    store(pack, config, schmsg)
    print(schmsg["sched_paused"].format(label=label))
    return 0


def cmd_resume(args, pack, schmsg):
    need_macos(schmsg)
    config = stored(pack)
    label = config.get("label") or label_for(pack)
    if not config:
        raise Refused(schmsg["sched_refuse_not_installed"].format(
            label=label, action="resume"))
    if not args.go:
        print(schmsg["sched_resumed"].format(label=label))
        print(schmsg["sched_dry_run"])
        return 0
    launchctl("enable", f"{domain()}/{label}")
    plist = paths_for(config.get("collection") or ".", label)["plist"]
    got = launchctl("bootstrap", domain(), str(plist))
    if got.returncode != 0 and not is_loaded(label):
        raise Refused(schmsg["sched_launchctl_failed"].format(
            detail=(got.stderr or got.stdout).strip()))
    config.pop("paused", None)
    store(pack, config, schmsg)
    print(schmsg["sched_resumed"].format(label=label))
    return 0


def cmd_remove(args, pack, schmsg):
    need_macos(schmsg)
    config = stored(pack)
    label = config.get("label") or label_for(pack)
    paths = paths_for(config.get("collection") or ".", label)
    if not args.go:
        print(schmsg["sched_would_remove"].format(label=label))
        print(schmsg["sched_dry_run"])
        return 0
    launchctl("bootout", f"{domain()}/{label}")
    launchctl("enable", f"{domain()}/{label}")     # leave no disabled ghost
    for path in (paths["plist"], paths["runner"], paths["prompt"]):
        if Path(path).exists():
            Path(path).unlink()
    # The logs are the owner's record of what ran; deleting them would remove
    # the evidence of the very runs they might be asking about.
    if pack.dir:
        after = json.loads(json.dumps(pack.profile))
        photo_settings.put(after, ("schedule",), {"enabled": False})
        photo_settings.write_profile(pack, after)
    print(schmsg["sched_removed"].format(label=label))
    return 0


def cmd_record(args, _pack, _smsg):
    """Written by the rendered runner at the end of every fire. Kept in Python
    so the state file has one writer and one shape."""
    label = args.label or "unknown"
    paths = paths_for(args.collection or ".", label)
    paths["base"].mkdir(parents=True, exist_ok=True)
    paths["state"].write_text(json.dumps(
        {"label": label, "started": args.started, "rc": args.rc,
         "outcome": args.outcome, "log": args.log},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


COMMANDS = {"show": cmd_show, "install": cmd_install, "status": cmd_status,
            "pause": cmd_pause, "resume": cmd_resume, "remove": cmd_remove,
            "record": cmd_record}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--collection", help="the collection workspace to work on")
    ap.add_argument("--profile", help="a pack folder or photo-profile.json")
    ap.add_argument("--window", help="off-hours window, e.g. 01:00-06:00")
    ap.add_argument("--at", action="append",
                    help="start time inside the window, e.g. 03:05 (repeatable)")
    ap.add_argument("--notify", choices=NOTIFY_CHOICES)
    ap.add_argument("--claude", help="path to the claude CLI")
    ap.add_argument("--go", action="store_true", help="actually write and load")
    # `record` only — the rendered runner's own call back into this file.
    ap.add_argument("--label", help=argparse.SUPPRESS)
    ap.add_argument("--started", help=argparse.SUPPRESS)
    ap.add_argument("--rc", type=int, default=0, help=argparse.SUPPRESS)
    ap.add_argument("--outcome", help=argparse.SUPPRESS)
    ap.add_argument("--log", help=argparse.SUPPRESS)
    args = ap.parse_args()

    pack = photo_profile.resolve_pack(explicit=args.profile)
    schmsg = photo_profile.schedule_messages(pack.profile)
    try:
        return COMMANDS[args.command](args, pack, schmsg)
    except Refused as refused:
        print(refused.message)
        return 2


if __name__ == "__main__":
    sys.exit(main())
