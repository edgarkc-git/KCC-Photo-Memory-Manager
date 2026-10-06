#!/usr/bin/env python3
"""photo-run — the pipeline conductor. Chains the mechanical stages of the
photo-manager pipeline (scan, cluster, dedupe, plan-render, execute) so one
source dump can be driven folder-by-folder, batch-by-batch, with fresh context
each invocation. State lives on disk (the dump's index in the owner pack, or
batches.json / plans.json on a dump with no index), so every run is resumable:
re-invoking picks up wherever the last one stopped.

This script is deliberately a thin orchestrator over the existing per-stage
scripts — it holds NO model and NO drive-writing logic of its own. The
judgment steps stay OUTSIDE it, done by the driving agent and the owner.

On a dump WITH an index (`photo_index.py init`): the vision pass per batch;
the owner's batch pages and the agent's identify views, at which `finish --go`
stops; the folder structure through `photo_index.py group`; then render,
check and freeze, which export plans.json. Nobody authors plans.json.

On a dump with NO index:
  A. classify   — look at each batch's sample images, write type/where via
                  photo_classify_set.py         (only vision step)
  B. plans.json — group batches + choose destination folders (merge/new/
                  fill_shell, names, legs, dedupe refs)

Everything else is mechanical and lives here. Portability: Python 3 stdlib
only, shells out to sibling scripts via the same interpreter; nothing is
hard-wired to macOS except the default workdir root (overridable).

Subcommands
  prep    <source>            scan + cluster a raw dump -> batches.json
                              (--no-cluster: scan + census only, a first dump)
  cluster <workdir|name>      cluster after onboarding wrote the pack (G4)
  status  <workdir|name>      show batch + plan state, suggest next action
  plan    <workdir|name> --plan N [--go]
                              indexed: batch pages + identify views, then one
                              plan from the freeze; no index: naming round
                              (U-2, --go only) -> dedupe(if refs)
                              -> render plan -> approve -> execute (DRY-RUN
                              unless --go)
  finish  <workdir|name> [--go]
                              indexed: batch pages + identify views, then
                              every plan the freeze exported; no index: naming
                              round (U-2, --go only), then every plan
                              in plans.json in order; then the
                              no-date plan (D13 to-be-checked mod: everything
                              -> the monthly to-be-checked bucket; DRY-RUN
                              unless --go);
                              with --go, ends with the OA-4 extension-mismatch
                              rename backstop over the plans' destination
                              folders (mislabeled extensions are already
                              corrected at copy time per D13)

U-2: with --go, both copying commands put the dump's drafted subjects to the
owner BEFORE any folder is written, and stop if a question was actually asked.
A folder name renders a CONFIRMED subject's name and an unconfirmed one's
class word, so a name confirmed after the copy names nothing — and nothing
here renames a folder on the drive. Costs one extra invocation, only when
there was something to ask; --skip-memory goes past it in one run.

Wave 3 G3: a dump with an index (`<work dir>/index-pointer.json`) is copied
only from its freeze. `plan` and `finish` run the U-2 round as above, then
`photo_index.py verify`, again just before the first photo_execute, and
exit 4 — nothing copied — when the index, the exported plan files or the pack
changed since the freeze. They do not re-render a frozen plan, and `finish`
ends by comparing the copy's SHA-256 with the frozen ones.

Safety: writing to the drive requires --go at every level (mirrors
photo_execute.py, whose default is dry-run). Without --go nothing is copied.
Copy-only throughout — no source file is ever moved, modified, or deleted.

Usage (on Windows type `py` where these say `python3`)
  python3 photo_run.py doctor                              # what this machine lacks
  python3 photo_run.py prep   "/Volumes/<drive>/.../202511__"
  python3 photo_run.py status 202511__
  python3 photo_run.py plan   202511__ --plan 1            # dry-run
  python3 photo_run.py plan   202511__ --plan 1 --go       # copy
  python3 photo_run.py finish 202511__ --go
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_state  # noqa: E402
import photo_platform  # noqa: E402
import photo_profile  # noqa: E402

# Written by photo_plan.SCREEN_PROPOSALS_NAME. Spelled out rather than
# imported: this conductor shells out to every stage and holds no stage
# module, so that one filename does not become the exception.
SCREEN_PROPOSALS_NAME = "screen-size-proposals.json"

# The header photo_cluster.py and photo_where.py send on every geocoder call.
# ⚠️ Nominatim answers the stdlib's default User-Agent with HTTP 403, so a
# probe that omits this reports the service unreachable on a machine where
# geocoding works perfectly. Spelled out for the same reason as the filename
# above — there is no shared home for it, and importing a stage module to
# reach one would be the exception this conductor does not make.
GEOCODER_USER_AGENT = "kcc-photo-manager/0.1"

HERE = Path(__file__).resolve().parent

# How the owner types Python in a printed command: `py` on Windows, where
# `python3` can open the Microsoft Store instead (RS5).
PY = photo_platform.owner_python()


def default_workdir_root(profile):
    """A collection workspace (photo-init) is self-locating: run from the
    workspace folder and its Working Files/collection.json is picked up
    automatically; otherwise fall back to the user's profile, or (if no
    profile either) demand one rather than guessing another user's path."""
    for cand in (Path.cwd() / "Working Files", Path.cwd()):
        if (cand / "collection.json").exists():
            return str(cand)
    fallback = photo_profile.get(profile, "legacy_workdir_root")
    if fallback:
        return fallback
    sys.exit("no collection.json under cwd and no workdir_root in profile — "
             "run photo-init here, or pass --profile / set PHOTO_PROFILE")


# ---------------------------------------------------------------------------
# RS5 — the setup checks. ONE list: `doctor` shows all of it, `prep` runs the
# start half through `preflight()`. Each check turns FACTS into an item, so a
# test fakes a fact (a PATH without exiftool, a module the probe calls absent,
# a network that raises) and never has to install or remove anything.
# ---------------------------------------------------------------------------

# Who needs an item: `start` stops `prep`; `vision` only the vision stages;
# `places` only place names (a run can pass --no-geocode).
NEED_START, NEED_VISION, NEED_PLACES = "start", "vision", "places"
NEED_WORDS = {NEED_START: "required to start",
              NEED_VISION: "vision stages only",
              NEED_PLACES: "place names only"}

# (import name, distribution name) the probe asks the .venv about, in the
# order doctor lists them.
VENV_MODULES = (("PIL", "pillow"), ("pillow_heif", "pillow-heif"),
                ("numpy", "numpy"),
                ("imageio_ffmpeg", "imageio-ffmpeg"), ("torch", "torch"),
                ("torchvision", "torchvision"), ("open_clip", "open_clip_torch"))

# Run INSIDE the repo .venv, like PREVIEW_PROBE. Stdlib plus photo_embed,
# whose third-party imports are all inside functions; `ffmpeg` is the route
# photo_embed.ffmpeg_exe() really takes, not a guess from the module list.
MODULE_PROBE = r"""
import importlib.metadata, importlib.util, json, sys
sys.path.insert(0, sys.argv[1])
out = {}
for mod, dist in json.loads(sys.argv[2]):
    if importlib.util.find_spec(mod) is None:
        out[dist] = None
        continue
    try:
        out[dist] = importlib.metadata.version(dist)
    except Exception:
        out[dist] = "present"
import photo_embed
out["ffmpeg"] = photo_embed.ffmpeg_exe()[1]
print(json.dumps(out))
"""


def exiftool_fact():
    """-> exiftool's version string, "" when it is on PATH but will not say,
    None when it is not on PATH."""
    if shutil.which("exiftool") is None:
        return None
    import photo_exiftool
    try:
        return photo_exiftool.run(["-ver"], [], timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def network_fact():
    """-> None when Nominatim answers, else why not."""
    try:
        # ⛔ Identify the probe. Anonymous, this is a 403 every time and the
        # check tells the operator to turn a working feature OFF.
        urllib.request.urlopen(
            urllib.request.Request(
                "https://nominatim.openstreetmap.org",
                headers={"User-Agent": GEOCODER_USER_AGENT}), timeout=5)
        return None
    except Exception as exc:                                    # noqa: BLE001
        return str(exc) or type(exc).__name__


def module_fact(python):
    """-> {dist: version or None, "ffmpeg": route or None} from the .venv, or
    None when the probe could not run there."""
    try:
        r = subprocess.run([str(python), "-c", MODULE_PROBE, str(HERE),
                            json.dumps(VENV_MODULES)],
                           capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def start_facts():
    return {"platform": sys.platform, "python": list(sys.version_info[:3]),
            "exiftool": exiftool_fact(), "network": network_fact()}


def gather_facts():
    """Everything doctor reports, measured on THIS machine."""
    facts = start_facts()
    facts["venv"] = VENV_PYTHON.is_file()
    facts["modules"] = module_fact(VENV_PYTHON) if facts["venv"] else None
    got, why, _python = preview_probe() if facts["venv"] else (None, None, None)
    facts["preview"] = got
    facts["preview_error"] = why
    facts["nvidia"] = photo_platform.has_nvidia_gpu()
    return facts


def _item(name, ok, need, detail, why, install=None, admin=False, size=None,
          note=None):
    """`install` is a line a shell runs as it stands, or None; `note` is for
    the owner to read (another route, an installer to download)."""
    return {"item": name, "ok": ok, "need": need, "detail": detail, "why": why,
            "install": None if ok else install, "note": None if ok else note,
            "needs_admin": bool(admin and not ok), "size": None if ok else size}


def start_items(facts):
    """The checks `prep` runs before any real work, in doctor's order."""
    plat = facts["platform"]
    py = tuple(facts["python"])
    cmd, note, admin = photo_platform.python_install_hint(plat)
    items = [_item("Python", py >= (3, 10), NEED_START,
                   "Python " + ".".join(str(n) for n in py),
                   "every stage runs on Python 3.10 or newer", cmd, admin,
                   note=note)]
    cmd = photo_platform.exiftool_install_command(plat)
    ver = facts["exiftool"]
    items.append(_item(
        "exiftool", ver is not None, NEED_START,
        f"exiftool {ver}" if ver else ("exiftool on PATH, version unknown"
                                       if ver == "" else "not on PATH"),
        "every capture date and GPS reading comes from it; prep stops without it",
        cmd, photo_platform.exiftool_needs_admin(plat),
        note=photo_platform.exiftool_install_note(plat)))
    return items


def network_item(facts):
    err = facts["network"]
    return _item("network (Nominatim)", err is None, NEED_PLACES,
                 "reached with the engine's User-Agent" if err is None
                 else f"not reached ({err})",
                 "place names come from it; without it, pass --no-geocode")


def doctor_items(facts):
    """-> every item, in the card's order. Pure: facts in, items out."""
    plat, nvidia = facts["platform"], facts.get("nvidia")
    items = start_items(facts)
    venv = facts.get("venv")
    items.append(_item(".venv", bool(venv), NEED_VISION,
                       "repo .venv found" if venv else "no repo .venv",
                       "the vision stages run only in the repo .venv, never "
                       "the system Python",
                       photo_platform.venv_create_line(platform=plat)))
    mods = facts.get("modules") or {}
    unchecked = "not checked — make the .venv first" if not venv else (
        "not checked — the .venv could not answer" if not facts.get("modules")
        else None)

    # Every package comes from ONE line, the repo's own extras (RS5b): the
    # version rules live in pyproject.toml and nowhere here.
    extras = photo_platform.extras_install_line(platform=plat)

    def pkg(name, dist, why, install, size=None):
        ver = mods.get(dist)
        items.append(_item(name, bool(ver), NEED_VISION,
                           unchecked or (f"{dist} {ver}" if ver else
                                         f"{dist} not in the .venv"),
                           why, install, size=size))

    pkg("Pillow", "pillow", "makes every photo preview", extras)
    pkg("pillow-heif", "pillow-heif",
        "decodes HEIC; without it every HEIC photo fails", extras)
    route = mods.get("ffmpeg")
    items.append(_item(
        "ffmpeg", bool(route), NEED_VISION,
        unchecked or ({"path": "the ffmpeg on PATH",
                       "imageio-ffmpeg": "the binary imageio-ffmpeg ships"}.get(
                           route, "none: no ffmpeg on PATH, no imageio-ffmpeg")),
        "one frame per video; without it every video fails", extras))
    pkg("numpy", "numpy", "the array maths of subject memory, CLIP and identity",
        extras)
    torch_line, torch_size = photo_platform.torch_install_line(
        platform=plat, nvidia=nvidia)
    ok = bool(mods.get("torch")) and bool(mods.get("torchvision"))
    items.append(_item(
        "torch + torchvision", ok, NEED_VISION,
        unchecked or (f"torch {mods.get('torch')}, torchvision {mods.get('torchvision')}"
                      if ok else "torch or torchvision not in the .venv"),
        "runs the CLIP and animal-identity models", torch_line or extras,
        size=torch_size,
        note=("or the CUDA line for your driver from pytorch.org"
              if nvidia and not plat == "darwin" else None)))
    pkg("open_clip", "open_clip_torch", "the CLIP scene model", extras,
        size=photo_platform.FIRST_RUN_WEIGHTS)
    got = facts.get("preview")
    if not venv:
        detail, ok = "not checked — make the .venv first", False
    elif got is None:
        detail, ok = f"the .venv cannot make one ({facts.get('preview_error')})", False
    elif got.get("still"):
        detail, ok = f"the {got['backend']} backend failed: {got['still']}", False
    else:
        gaps = [w for w, have in (("no HEIF decoder", got.get("heif")),
                                  ("no ffmpeg", got.get("video"))) if not have]
        detail, ok = (f"a still made with {got['backend']}"
                      + (f" ({', '.join(gaps)})" if gaps else "")), True
    items.append(_item("preview", ok, NEED_VISION, detail,
                       "a real preview made end to end in the .venv",
                       note="install the items above, then run doctor again"))
    items.append(network_item(facts))
    return items


def install_plan(items):
    """-> the lines to run, each ONCE, in order: [{run, covers, sizes,
    needs_admin}]. Item order, except that the extras line goes last: the
    .venv must exist first, and a CPU-only torch line must run before it."""
    plan = {}
    for i in items:
        if i["ok"] or not i["install"]:
            continue
        p = plan.setdefault(i["install"], {"run": i["install"], "covers": [],
                                           "sizes": [], "needs_admin": False})
        p["covers"].append(i["item"])
        if i["size"]:
            p["sizes"].append(f"{i['item']}: {i['size']}")
        p["needs_admin"] |= i["needs_admin"]
    return sorted(plan.values(), key=lambda p: " -m pip install -e " in p["run"])


def verdict(items):
    missing = [i for i in items if not i["ok"]]
    return {"ready_to_start": not any(i["need"] == NEED_START for i in missing),
            "ready_for_vision": not any(i["need"] in (NEED_START, NEED_VISION)
                                        for i in missing),
            "missing": [i["item"] for i in missing]}


# F01 — step 0 (docs/INSTALL.md), Path A: the owner switched to manual mode to approve
# the product's commands once. The last line of a ready doctor says when to
# switch back.
SWITCH_BACK = ("If you switched to manual mode for setup, you can switch back "
               "to auto now.")


def render_items(items, platform):
    osn = {"darwin": "macOS"}.get(platform, "Windows" if platform.startswith("win")
                                  else "Linux")
    lines = [f"photo_run doctor — this machine ({osn})"]
    for i in items:
        lines.append(f"  {'OK     ' if i['ok'] else 'MISSING'}  {i['item']:<20} "
                     f"{i['detail']}   [{NEED_WORDS[i['need']]}]")
        if not i["ok"]:
            lines.append(f"           why: {i['why']}")
            if i["install"]:
                lines.append(f"           install: {i['install']}")
            if i["note"]:
                lines.append(f"           note: {i['note']}")
            if i["size"]:
                lines.append(f"           download: {i['size']}")
            if i["needs_admin"]:
                lines.append("           ⚠️  needs admin (sudo) — the owner runs "
                             "this line, not the agent")
    plan = install_plan(items)
    if plan:
        lines.append("")
        lines.append("install plan — each line once, in this order, after the "
                     "owner's yes:")
        for n, p in enumerate(plan, 1):
            lines.append(f"  {n}. {p['run']}")
            lines.append(f"     for: {', '.join(p['covers'])}")
            for size in p["sizes"]:
                lines.append(f"     download: {size}")
            if p["needs_admin"]:
                lines.append("     ⚠️  needs admin (sudo) — the owner runs this "
                             "line, not the agent")
    v = verdict(items)
    lines.append("")
    lines.append("ready to start: " + ("yes" if v["ready_to_start"] else "NO")
                 + " · vision stages: " + ("ready" if v["ready_for_vision"]
                                           else "not ready"))
    if v["ready_to_start"]:
        lines.append(SWITCH_BACK)
    return "\n".join(lines)


def preflight():
    """The start half of doctor, before `prep` does real work. Prints what is
    missing with its install line and returns the names of missing items that
    are REQUIRED to start; the caller stops on them."""
    facts = start_facts()
    missing = [i for i in start_items(facts) + [network_item(facts)] if not i["ok"]]
    if missing:
        print("⚠️  preflight found missing dependencies:")
        for i in missing:
            how = "; ".join(x for x in (i["install"], i["note"]) if x)
            print(f"   - {i['item']}: {i['detail']} — {i['why']}"
                  + (f" ({how})" if how else ""))
        print()
    return [i["item"] for i in missing if i["need"] == NEED_START]


BUILD_FILE = HERE / "BUILD.txt"


def build_id(build_file=BUILD_FILE, repo=HERE.parent):
    """H-G (obs-16) — which build this is, for a tester to report.

    Three routes, in order: a zip made by `git archive` (every GitHub
    download) carries `<commit> <date> <refs>` in BUILD.txt (export-subst);
    a clone keeps the `$Format` placeholder, and git describes it; anything
    else says it does not know, with the pyproject version beside it."""
    text = build_file.read_text(encoding="utf-8").strip() if build_file.is_file() else ""
    if text and not text.startswith("$Format"):
        sha, _, rest = text.partition(" ")
        date, _, refs = rest.partition(" ")
        tag = re.search(r"tag: ([^,\s]+)", refs)
        return f"{tag.group(1) if tag else 'untagged'} (commit {sha[:7]}, {date})"
    if (Path(repo) / ".git").exists():
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        r = subprocess.run(["git", "-C", str(repo), "describe", "--tags",
                            "--always", "--dirty"], capture_output=True,
                           text=True, env=env)
        if r.returncode == 0 and r.stdout.strip():
            return f"{r.stdout.strip()} (a git clone)"
    found = re.search(r'^version\s*=\s*"([^"]+)"', (Path(repo) / "pyproject.toml")
                      .read_text(encoding="utf-8"), re.M) \
        if (Path(repo) / "pyproject.toml").is_file() else None
    return ("unknown (not a release download)"
            + (f" — version {found.group(1)}" if found else ""))


def cmd_doctor(args):
    facts = gather_facts()
    items = doctor_items(facts)
    build = build_id()
    if args.json:
        print(json.dumps({"platform": facts["platform"], "build": build,
                          "items": items, "install_plan": install_plan(items),
                          **verdict(items)}, ensure_ascii=False, indent=1))
    else:
        print(render_items(items, facts["platform"]).replace(
            "\n", f"\nbuild: {build}\n", 1))
    sys.exit(0 if verdict(items)["ready_to_start"] else 1)


# Run INSIDE the interpreter that makes previews (the repo .venv), never this
# one: a probe run by a different executable answers for the wrong one.
PREVIEW_PROBE = r"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import photo_embed
from PIL import Image
out = {"backend": photo_embed.preview_backend()}
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "probe.jpg"
    Image.new("RGB", (16, 16), (90, 90, 90)).save(src, "JPEG")
    made, cause = photo_embed.convert_to_thumbnail(src, Path(tmp), "o", "image", "JPEG")
    out["still"] = cause
out["heif"] = out["backend"] != "pillow" or photo_embed.heif_ready()
out["video"] = (photo_embed.ffmpeg_exe()[1] if out["backend"] == "pillow"
                else ("qlmanage" if photo_embed.shutil.which("qlmanage") else None))
print(json.dumps(out))
"""


def preview_probe():
    """-> (probe result or None, why not, the interpreter asked). The ONE run
    of PREVIEW_PROBE: `prep` and `doctor` both read it."""
    python = VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)
    why = None
    try:
        r = subprocess.run([str(python), "-c", PREVIEW_PROBE, str(HERE)],
                           capture_output=True, text=True, timeout=120)
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError) as exc:
        got, why = None, str(exc)
    except (ValueError, IndexError):
        got, why = None, (r.stderr.strip().splitlines() or ["no output"])[-1]
    return got, why, python


def preview_check():
    """M8: stop BEFORE the scan when no preview backend can make a still.
    `prep` used to warn that sips was missing and carry on, so the owner was
    led past the last safe stop into a vision pass where every file failed.
    A missing HEIF decoder or ffmpeg is WARNED about: those fail only their
    own files, each with a named cause, at embed time."""
    got, why, python = preview_probe()
    if got is None:
        sys.exit(f"⛔ previews: {python} cannot make one ({why}).\n"
                 "   Install the vision stages first (docs/INSTALL.md, step 4), then "
                 "run prep again.")
    if got["still"]:
        sys.exit(f"⛔ previews: the {got['backend']} backend cannot make a "
                 f"still here ({got['still']}).\n   Install what it names, or "
                 "on a Mac set PHOTO_PREVIEW_BACKEND=sips, then run prep again.")
    if not got["heif"]:
        print("⚠️  previews: no HEIF decoder — every HEIC photo will fail "
              "(pip install pillow-heif into the repo .venv)")
    if not got["video"]:
        print("⚠️  previews: no ffmpeg — every video will fail "
              "(pip install imageio-ffmpeg into the repo .venv, or install ffmpeg)")


def load_collection(workdir_root):
    cj = Path(workdir_root) / "collection.json"
    return json.loads(cj.read_text()) if cj.exists() else None


def run(script, *scr_args, python=None):
    """Invoke a sibling stage script with the current interpreter (or `python`);
    stream its output. Returns the CompletedProcess (callers decide how to
    treat rc)."""
    cmd = [python or sys.executable, str(HERE / script), *[str(a) for a in scr_args]]
    print(f"$ {script} {' '.join(str(a) for a in scr_args)}", flush=True)
    return subprocess.run(cmd)


def resolve_workdir(arg, args):
    """Accept a full workdir path, a source drive path, or a bare dump name.
    workdir_root is only resolved (and only demands a profile) for the bare-
    name case — a full/already-scanned path never needs it, so `status` on
    an existing dump keeps working with no profile at all."""
    p = Path(arg)
    if (p / "batches.json").exists() or (p / "manifest.csv").exists():
        return p.resolve()
    root = args.workdir_root or default_workdir_root(load_profile_cached(args))
    cand = Path(root) / p.name
    return cand.resolve()


_pack_cache = {}


def load_pack_cached(args, workdir=None):
    """One owner pack per run — resolved once, reused everywhere.

    ⛔ A resolution made with NO work dir is answered but never cached (C17).
    `collection.json` is found through the work dir and nowhere else, so a
    workdir-less answer is empty for a fully bound dump — and this cache is
    the whole process's one pack. `resolve_workdir` legitimately asks without
    a work dir (it is resolving one), so caching that answer let the cwd
    decide whether `finish` saw an owner at all: from the workspace folder it
    printed "no owner pack bound", at exit 0, and skipped the SNS-4
    checkpoint. Re-resolving costs a JSON read and also keeps
    `resolve_pack`'s owner-conflict check reachable, which a cache hit skips.
    """
    if "pack" in _pack_cache:
        return _pack_cache["pack"]
    pack = photo_profile.resolve_pack(workdir=workdir, explicit=args.profile)
    # Export it so every stage script shelled out from here resolves the
    # SAME pack — without this an owner bound through collection.json is
    # visible to the conductor but invisible to scan/cluster/plan.
    if pack.dir:
        os.environ[photo_profile.ENV_VAR] = str(
            (pack.dir / photo_profile.PROFILE_NAME).resolve())
    if workdir is not None:
        _pack_cache["pack"] = pack
    return pack


def load_profile_cached(args, workdir=None):
    return load_pack_cached(args, workdir).profile


def load_batches(workdir):
    bp = workdir / "batches.json"
    if not bp.exists():
        return None
    return json.loads(bp.read_text())


def load_plans(workdir):
    pp = workdir / "plans.json"
    if not pp.exists():
        return None
    return json.loads(pp.read_text())


# status.json is an ADDITIVE ledger for pipeline-visibility only (R3/P3.1).
# batches.json stays the single source of truth for resumability (P2.4) —
# this file is derived/rewritten from batches.json + plans.json every time
# print_status runs; nothing reads it back to drive behavior, so it can
# never desync a live run.
STAGES = ["1-grouped", "2-gps-split", "3-sampled", "4-classified", "5-sorted"]

# D-28. A hold is orthogonal to the five stages — a batch is held AT whatever
# stage it reached — so it is deliberately not a sixth entry in STAGES. What it
# changes is what this conductor PROPOSES: a held batch is never handed to the
# operator as the next action, because `next:` telling you to classify the
# batch somebody stopped on purpose is how a hold gets undone by accident.
HELD = "held"


def batch_stage(b):
    st = b.get("status", "pending")
    if st == "done":
        return "5-sorted"
    if st in ("planned", "approved"):
        return "4-classified"
    if st == "classified":
        return "4-classified"
    if b.get("_sampled"):
        return "3-sampled"
    return "2-gps-split"


def write_status_json(workdir, bdata, plans, pack=None, write=True):
    batches = bdata["batches"]
    for b in batches:
        sample_report = (workdir / "classify" / f"batch-{b['batch']:02d}"
                          / "sample-report.json")
        b["_sampled"] = sample_report.exists()
    ledger = {
        "stage_names": STAGES,
        "generated_at": bdata.get("generated_at"),
        # Which owner memory the run stood on. From v2 Phase C the pack
        # mutates between batches, so a result is only reproducible against
        # the snapshot it was produced with — the golden harness pins this.
        "pack_snapshot": pack.snapshot() if pack else None,
        "totals": {"files": bdata.get("main_files"),
                   "batches": len(batches),
                   "gps_legs": sum(1 for b in batches if "no_gps" not in b.get("flags", [])),
                   "to_be_id": sum(1 for b in batches if "no_gps" in b.get("flags", []))},
        "batches": [{
            "batch": b["batch"],
            "stage": batch_stage(b),
            "status": b.get("status", "pending"),
            "to_be_id": "no_gps" in b.get("flags", []),
            # D-28. Carried into the ledger so a hold survives being read by
            # something other than this console print — status.json is what a
            # later session, or a scheduled run, actually reads.
            **({"held_reason": b.get("held_reason"),
                "held_at": b.get("held_at"),
                "held_by": b.get("held_by")}
               if b.get("status") == HELD else {}),
        } for b in batches],
        "plans": len(plans["plans"]) if plans else 0,
    }
    for b in batches:
        b.pop("_sampled", None)
    path = workdir / "status.json"
    text = json.dumps(ledger, ensure_ascii=False, indent=1)
    # Unchanged content is not rewritten, so a dry run leaves the work dir as
    # it found it (FIX9 F7b).
    if write and (not path.exists() or path.read_text() != text):
        path.write_text(text)
    return ledger


def print_stage_summary(ledger, index=False):
    counts = {s: 0 for s in STAGES}
    for b in ledger["batches"]:
        counts[b["stage"]] += 1
    t = ledger["totals"]
    # An indexed dump has no classify step, so ④ would count a stage nobody runs.
    classified = ("" if index else
                  f"④ {counts['4-classified'] + counts['5-sorted']}/{t['batches']} classified → ")
    print(f"\n① {t['files']} files → ② {t['gps_legs']} GPS legs + "
          f"{t['to_be_id']} to-be-ID (no-GPS) → "
          f"③ {counts['3-sampled'] + counts['4-classified'] + counts['5-sorted']}/"
          f"{t['batches']} sampled → "
          f"{classified}"
          f"⑤ {counts['5-sorted']}/{t['batches']} sorted")


def print_status(workdir, pack=None, paths=False, write=True):
    """`paths` — FIX8 F8-5 (an owner decision): destination paths and folder names are
    shown only on `status --paths`. The tails of prep, cluster and finish
    call this with the default and never print one."""
    coll = load_collection(workdir.parent)
    if coll:
        root_shown = (coll.get("dest_root", "?") if paths
                      else "set" if coll.get("dest_root") else "not set")
        print(f"collection: {coll.get('collection', '?')}  "
              f"dest_root: {root_shown}")
    # EV-9's header, in the words every replay already uses. Printed
    # unconditionally: an unbound run used to say nothing at all about its
    # pack, which reads as "no pack question was asked" rather than "no pack".
    #
    # TIER3_DUMP is not "the only one left" — it is what EV-5 names this file:
    # its protocol makes photo_run.py the conductor of a Tier 3 run, and the
    # tier table's Tier 3 is "a genuinely new photo dump, end to end", which
    # is the only thing this script is ever pointed at. ⚠️ The competing read
    # is that the tiers are an EVALUATION vocabulary and a routine sort is
    # outside all three; it was considered and rejected, because RUN_TYPES
    # carries no fourth key and inventing one would put a tier name nobody
    # can look up in the SPEC into the header EV-9 exists to make quotable.
    # If a non-evaluation tier is ever added, this call site is the first
    # thing that should change.
    #
    # `benchmark=False` is likewise named, not derived: benchmark=True makes
    # pack_state() ENFORCE the blank sheet and raise, and a status print must
    # never be the thing that raises. fresh_owner_smoke.py:163 passes False
    # for the same reason; only memorize_replay.py declares a benchmark arm.
    # The blank-sheet VERDICT is still computed from the pack and printed.
    print(pack_state.pack_state(pack or photo_profile.Pack(), benchmark=False,
                                run_type=pack_state.TIER3_DUMP)[1])
    # Beside the header, not inside it: the EV-9 line is the one every replay
    # prints and it stays byte-identical here. The directory is the operator's
    # question rather than the evidence question — the header names an owner
    # slug, and two packs may share one in different folders (the tier3cat and
    # tier3hike fixtures do), so without this `status` cannot say which.
    if pack and pack.dir:
        print(f"pack dir: {pack.dir}")
    bdata = load_batches(workdir)
    if not bdata:
        print(f"no batches.json in {workdir} — run `prep` first")
        return
    print(f"source: {bdata.get('source', '?')}")
    counts = {}
    print("\nbatches:")
    for b in bdata["batches"]:
        st = b.get("status", "pending")
        counts[st] = counts.get(st, 0) + 1
        where = b.get("where", "")
        ctype = b.get("type", "")
        tag = "to-be-ID " if "no_gps" in b.get("flags", []) else ""
        label = f"{tag}{ctype} {where}".strip()
        if "place_name_not_in_owner_language" in b.get("flags", []):
            label += "  (the map's local name — none in the owner's language)"
        print(f"  B{b['batch']:<3} {b['from']}→{b['to']:<12} "
              f"{st:<11} {label}")
    print("  " + "  ".join(f"{k}:{v}" for k, v in sorted(counts.items())))

    # ⛔ Its own heading, not a row buried in the list above. A hold is a
    # question somebody is waiting on an answer to, and the reason is the only
    # part of it that is worth anything a week later.
    held = [b for b in bdata["batches"] if b.get("status") == HELD]
    if held:
        print(f"\nheld ({len(held)}) — waiting on an answer, not unstarted:")
        for b in held:
            since = b.get("held_at") or "?"
            who = b.get("held_by") or "?"
            print(f"  B{b['batch']:<3} {since}  {who}")
            print(f"       {b.get('held_reason') or '(no reason recorded)'}")
        print("  release with: photo_classify_set.py \"<work dir>\" "
              "--batch <N> --status classified ...")
    ledger = write_status_json(workdir, bdata, load_plans(workdir), pack, write=write)
    print_stage_summary(ledger, index=indexed(workdir))

    plans = load_plans(workdir)
    if plans:
        # FIX7 (F2) — paths shown against the collection's own root, and a
        # plan that points somewhere else SAID: plans.json outlives a
        # re-pointed collection, and a copy would land where the plan says.
        root = (coll or {}).get("dest_root")
        outside = []
        print("\nplans (plans.json):")
        for p in plans["plans"]:
            path = p["dest"]["path"]
            shown = path
            if root:
                try:
                    shown = "<dest_root>/" + str(Path(path).relative_to(root))
                except ValueError:
                    outside.append(p["plan"])
            print(f"  P{p['plan']:<3} batches {p['batches']}  "
                  f"{p['dest']['mode']}" + (f"  {shown}" if paths else ""))
        if outside:
            print("  ⚠️  " + ", ".join(f"P{n}" for n in outside)
                  + " point outside this collection's dest_root"
                  + (f" ({root})" if paths else "") + " — "
                  "plans.json was written for another destination, and a copy "
                  "would land there"
                  + ("" if paths else " (status --paths shows where)"))
        # FIX8 F8-2 — the folders a re-lock found renamed after their copy,
        # by the same test `verify --copied` uses. Names only with --paths.
        import photo_execute
        todo = photo_execute.renames_to_do(plans, plans.get("dest_root") or "")
        if todo:
            print(f"\n⚠️  {len(todo)} folder rename(s) still to do on the drive — "
                  "the engine never renames a folder"
                  + (":" if paths else " (status --paths lists them)"))
            if paths:
                for old, new in todo:
                    print(f'  "{old}" -> "{new}"')

    # suggest the next action. ⛔ Held batches are filtered out of every list
    # below rather than dropped at the end: `next:` must not name a batch a
    # human stopped, and the earlier shape of this — a held batch reported as
    # `pending` and then handed to the operator with the classify command —
    # pointed straight at the trap the hold existed to prevent (D-28).
    live = [b for b in bdata["batches"] if b.get("status") != HELD]
    pending = [b for b in live if b.get("status", "pending") == "pending"]
    classified = [b for b in live if b.get("status") == "classified"]
    print("\nnext:")
    if held:
        print(f"  ({len(held)} batch(es) held — listed above, and not "
              "proposed here until released)")
    if indexed(workdir):
        print_index_next(workdir, live, pack)
        return
    if pending and pack is not None and getattr(pack, "dir", None):
        # FIX6 (U6-09) — an owner's dump is sorted through an index, which has
        # no classify step; `cluster` runs before `index init`, so without this
        # the first "next:" an owner reads sends them down the retired route.
        print(f"  {len(pending)} batch(es) and no index yet — make the index "
              "(photo-run step 1), then the visual pass:")
        print(f"    {photo_platform.run_line(PY, HERE / 'photo_index.py')} init \"{workdir}\"")
    elif pending:
        print(f"  {len(pending)} batch(es) still `pending` — CLASSIFY them "
              f"(look at samples, then photo_classify_set.py). Sample images:")
        print(f"    {photo_platform.run_line(PY, HERE / 'photo_sample.py')} \"{workdir}\" --batch <N>")
        # VS-2 supersedes the sampler where a VS-1 index exists. Printed as an
        # alternative rather than swapped in: it needs embed/, and the stage
        # wiring is not part of VS-2's scope.
        if (workdir / "embed" / "embeddings.npy").exists():
            print("  or, embedding-guided (VS-2, needs the repo .venv):")
            print(f"    {photo_platform.run_line(VENV_PYTHON, HERE / 'photo_see.py')} \"{workdir}\" "
                  "--batch <N>")
            # ⚠️ photo_see runs perfectly well with no scene-label matrix — it
            # writes a valid report and matches nothing. An operator following
            # this list would get that empty column with no sign a stage was
            # missing, so the dependency is named where the next action is
            # chosen. Inside the index gate on purpose: with no embed/ there is
            # nothing to encode labels for yet.
            if not (workdir / "embed" / "scene-labels.json").exists():
                print("    ⚠️  no embed/scene-labels.json — the scene axis is "
                      "OFF for this dump, so photo_see will clip-match nothing. "
                      "Encode the label set once first:")
                print(f"      {photo_platform.run_line(VENV_PYTHON, HERE / 'photo_embed.py')} "
                      f"\"{workdir}\" --scene-labels")
    elif not plans:
        # R1: vision BEFORE plan. Authoring plans.json first is what UAT01 did
        # and it cannot be undone by a later see run -- the folder is already
        # named. photo_plan refuses this now; saying so here is what stops the
        # operator reaching the refusal at all.
        unseen = [b["batch"] for b in live
                  if not (workdir / "classify" / f"batch-{b['batch']:02d}"
                          / "see-labels.json").exists()]
        if unseen:
            print(f"  {len(unseen)} batch(es) not seen yet — run the VISUAL "
                  f"pass before authoring plans.json. [who] and [what] can "
                  f"only reach a folder name from here; a plan authored first "
                  f"names the folder from metadata alone and photo_plan will "
                  f"refuse it:")
            print_visual_pass(workdir, unseen)
        else:
            print("  all batches classified and seen — AUTHOR plans.json "
                  "(step B), then run `finish`")
            print("  (`finish --go` puts this dump's drafted subjects to you "
                  "before it copies anything — answer that page and a name "
                  "lands IN the folder, U-2)")
    elif classified:
        print("  plans.json exists — run `finish` (dry-run) to render + "
              "execute-preview all plans, then add --go")
    else:
        print("  batches planned/approved/done — run `finish --go` to copy "
              "any remaining, or you're done")


def print_visual_pass(workdir, unseen):
    """The visual pass's commands, each one only while its output is missing."""
    if not (workdir / "embed" / "embeddings.npy").exists():
        print(f"    {photo_platform.run_line(VENV_PYTHON, HERE / 'photo_embed.py')} "
              f"\"{workdir}\"")
    if not (workdir / "embed" / "identity.csv").exists():
        print(f"    {photo_platform.run_line(VENV_PYTHON, HERE / 'photo_identity.py')} "
              f"\"{workdir}\"   # else every verdict is CLIP, "
              "not identity")
    # U2-09. A missing label matrix costs an axis of classification and
    # nothing fails, so a list of the visual pass must not list three
    # quarters of it.
    if not (workdir / "embed" / "scene-labels.json").exists():
        print(f"    {photo_platform.run_line(VENV_PYTHON, HERE / 'photo_embed.py')} "
              f"\"{workdir}\" --scene-labels   # once per dump; "
              "without it the scene axis is OFF and photo_see "
              "clip-matches nothing")
    print(f"    {photo_platform.run_line(VENV_PYTHON, HERE / 'photo_see.py')} "
          f"\"{workdir}\" --batch <N>")
    # ⛔ The selecting run alone records nothing: without this line the batch
    # stays unseen at exit 0 (F8).
    print("    # look at its samples/, write decisions.json (photo-see/SKILL.md), then:")
    print(f"    {photo_platform.run_line(VENV_PYTHON, HERE / 'photo_see.py')} "
          f"\"{workdir}\" --batch <N> --apply decisions.json --memorize")
    print(f"    (batches: {', '.join(str(n) for n in unseen)})")


def rendered_without_vision(workdir, pack):
    """W2-20a — True when the index's last render went past unseen batches
    with --no-vision: `photo_index render` stamps `render.no_vision` and
    refuses an unseen batch without the flag."""
    if pack is None or getattr(pack, "dir", None) is None:
        return False
    import photo_index
    pointer = photo_index.read_pointer(workdir)
    if not pointer or pointer.get("owner") != pack.owner:
        return False
    path = photo_index.index_dir(pack, pointer["dump_key"]) / photo_index.INDEX_NAME
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool((index.get("render") or {}).get("no_vision"))


def print_index_next(workdir, live, pack=None):
    """G8 — the next step on a dump WITH an index. Nobody authors plans.json
    here: `freeze` exports it, and the pages and the agent's views are the
    stops of `finish --go`."""
    unseen = [b["batch"] for b in live
              if not (workdir / "classify" / f"batch-{b['batch']:02d}"
                      / "see-labels.json").exists()]
    finish = f"{photo_platform.run_line(PY, HERE / 'photo_run.py')} finish \"{workdir}\" --go"
    if unseen and rendered_without_vision(workdir, pack):
        print(f"  {len(unseen)} batch(es) rendered without vision "
              f"(--no-vision): {', '.join(f'B{n}' for n in unseen)}. The visual "
              "pass was skipped for them by choice, so their folders are "
              "named from metadata alone. It can still be run, then "
              "`photo_index.py render` again without --no-vision:")
        print_visual_pass(workdir, unseen)
    elif unseen:
        print(f"  {len(unseen)} batch(es) not seen yet — run the VISUAL pass "
              "(the repo .venv), then `finish --go`:")
        print_visual_pass(workdir, unseen)
    elif live and all(b.get("status") == "done" for b in live):
        print("  every batch is done — see plan/execution-log_*.md for flags")
    elif (workdir / "plans.json").exists():
        print("  frozen — `finish --go` copies from the freeze; if it exits 4, "
              "run `photo_index.py render`, `check` and `freeze` again:")
        print(f"    {finish}")
    else:
        print("  every batch is seen — run `finish --go`. It stops for each "
              "batch page and for the agent's identify views; then run "
              "`photo_index.py render`, `check` and `freeze`, and "
              "`finish --go` again:")
        print(f"    {finish}")


def cmd_prep(args):
    missing = preflight()
    if missing:
        # RS5: exiftool is where every date comes from, so a scan without it
        # is not a degraded run but a wrong one. It used to be a warning.
        sys.exit(f"⛔ prep stops: {', '.join(missing)} missing (see above). "
                 f"`{photo_platform.owner_python()} {HERE / 'photo_run.py'} doctor` "
                 "lists everything this machine needs, and how to install each item.")
    preview_check()
    if not Path(args.source).is_dir():
        sys.exit(f"source not found: {args.source}\n"
                 + photo_platform.source_missing_hint())
    workdir_root = args.workdir_root or default_workdir_root(load_profile_cached(args))
    workdir = Path(workdir_root) / Path(args.source).name
    scan = ["photo_scan.py", args.source, "--workdir-root", workdir_root]
    if args.no_recursive:
        scan.append("--no-recursive")
    r = run(*scan)
    if r.returncode != 0:
        sys.exit("scan failed — aborting before cluster")
    if getattr(args, "no_cluster", False):
        # G4 / D-I1, a FIRST dump: the census and the onboarding page read the
        # manifest only, and clustering before the owner's homes are in the
        # pack sends home-area day centroids to the geocoder (measured on a
        # real dump: 75 of 119 lookups within 3 km of a home).
        run("photo_census.py", workdir)
        print("\n--- prep done: scanned, NOT clustered (--no-cluster) ---")
        print("next: onboarding (photo-init), `apply --write-pack`, then:")
        print(f"  {PY} {HERE / 'photo_run.py'} cluster \"{workdir}\"")
        return
    cluster = ["photo_cluster.py", workdir]
    if args.force:
        cluster.append("--force")
    r = run(*cluster)
    if r.returncode != 0:
        sys.exit("cluster failed")
    # Device/screen checkpoint: which cameras and screen sizes this dump
    # actually contains, versus what the owner's pack claims. A gap here is
    # silent otherwise — it surfaces later as plan documents calling the
    # owner's own photos `shared`, or screenshots never being detected.
    run("photo_census.py", workdir)
    print("\n--- prep done ---")
    print_status(workdir, load_pack_cached(args, workdir))


def cmd_cluster(args):
    """The clustering half of `prep`, for a dump scanned with --no-cluster:
    run once the owner's onboarding answers are in the pack, so home days
    take the owner's label and no home-area lookup leaves the machine."""
    workdir = resolve_workdir(args.workdir, args)
    if not (workdir / "manifest.csv").exists():
        sys.exit(f"no manifest.csv in {workdir} — run `prep` first")
    load_pack_cached(args, workdir)   # exports PHOTO_PROFILE for the stage
    cluster = ["photo_cluster.py", workdir]
    if args.force:
        cluster.append("--force")
    if run(*cluster).returncode != 0:
        sys.exit("cluster failed")
    print("\n--- cluster done ---")
    print_status(workdir, load_pack_cached(args, workdir))


def cmd_status(args):
    wd = resolve_workdir(args.workdir, args)
    print_status(wd, load_pack_cached(args, wd), paths=args.paths)


def run_one_plan(workdir, plans, plan_num, go, force=False,
                 no_vision=False, frozen=False, before_execute=None):
    """dedupe(if refs) -> render -> approve batches -> execute. Returns rc.

    Idempotent/resumable: a plan whose batches are all `done` is skipped, so a
    re-run (or a dry-run) never churns finished batches back to `approved`.
    Pass force=True to re-render a done plan anyway. Batches already `done` are
    left at `done` — only not-yet-done batches are advanced to `approved`.

    `frozen`: the plan comes from an index freeze, which already deduped and
    rendered it and hashed what it wrote, so neither runs again.
    `before_execute` is called just before photo_execute.
    """
    plan = next((p for p in plans["plans"] if p["plan"] == plan_num), None)
    if plan is None:
        print(f"  P{plan_num} not in plans.json — skipping")
        return 1

    bdata = load_batches(workdir)
    statuses = {b["batch"]: b.get("status", "pending")
                for b in bdata["batches"]} if bdata else {}
    plan_states = [statuses.get(b, "pending") for b in plan["batches"]]
    if not force and plan_states and all(s == "done" for s in plan_states):
        print(f"  P{plan_num}: all batches already done — skipping")
        return 0
    held = [b for b in plan["batches"] if statuses.get(b) == HELD]
    if held:
        # M5b / D-28 — a hold is a deliberate stop on an unanswered question.
        # Rendering sets `planned` and approving sets `approved`, so either
        # released it silently, and `--go` then copied the batch and marked it
        # done with its reason still recorded. The plan waits, dry run or not.
        reasons = {b["batch"]: b.get("held_reason") or "(no reason recorded)"
                   for b in (bdata or {}).get("batches", []) if b["batch"] in held}
        print(f"  P{plan_num}: batch(es) {', '.join(f'B{b}' for b in held)} held — "
              "skipping; nothing rendered, approved or copied for this plan")
        for b in held:
            print(f"    B{b}: {reasons[b]}")
        print(f"    release with: photo_classify_set.py \"{workdir}\" --batch <N> "
              "--status classified")
        return 0

    if plan.get("refs") and not frozen:
        batch_arg = ",".join(str(b) for b in plan["batches"])
        dd = ["photo_dedupe.py", workdir, "--batches", batch_arg]
        for ref in plan["refs"]:
            dd += ["--ref", ref]
        if run(*dd).returncode != 0:
            print(f"  P{plan_num}: dedupe failed — skipping")
            return 1

    render = ["photo_plan.py", workdir, "--plan", plan_num]
    if no_vision:
        render.append("--no-vision")
    if not frozen and run(*render).returncode != 0:
        print(f"  P{plan_num}: plan render failed — skipping")
        return 1

    # policy: no pre-execution approval gate (D10, 2026-07-04) — auto-approve.
    # Safety net is copy-only reversibility + the plan md as audit trail.
    # Leave already-`done` batches alone; only advance the rest.
    # ⛔ An indexed dry run approves nothing (M5, FIX9-A option A): the freeze
    # is the approval there, and a dry run writes nothing to the work dir.
    for b in plan["batches"]:
        if statuses.get(b) == "done" or (frozen and not go):
            continue
        run("photo_classify_set.py", workdir, "--batch", b,
            "--status", "approved")

    ex = ["photo_execute.py", workdir, "--plan", plan_num]
    if go:
        ex.append("--go")
    if before_execute:
        before_execute()
    return run(*ex).returncode


# `photo_index.py verify` exits with this when the freeze does not hold, and
# `finish` / `plan` pass it on. Spelled out, like PRE_PLAN_ROUND_FIRED_RC.
EXIT_STALE_FREEZE = 4
# `photo_index.py verify --copied`: the copies match, only the pack moved.
EXIT_PACK_MOVED = 6
INDEX_POINTER = "index-pointer.json"


def indexed(workdir):
    """Wave 3 G3: a dump with an index copies ONLY from its freeze. With no
    index (no pack, a legacy dump, every golden), everything is as before."""
    return (Path(workdir) / INDEX_POINTER).exists()


def freeze_gate(args, workdir, when):
    """Refuse — exit 4, nothing copied — unless the freeze still holds: the
    same index, the same exported plan files, the same owner pack (D-I16).
    The pack id moves on a confirm or a rename, which is how a name decided
    after the freeze is kept out of the copy."""
    load_pack_cached(args, workdir)   # exports PHOTO_PROFILE for the stage
    if run("photo_index.py", "verify", workdir).returncode == 0:
        return
    tool = HERE / "photo_index.py"
    print(f"\n⛔ STOPPED {when} — nothing was copied.\n"
          "   This dump has an index, and it is copied only from a freeze that "
          "still holds: the same index, the same exported plan files, the same "
          "owner pack. Run the three steps again, then this command:\n"
          # FIX7 (F5-b): render lifts a STALE freeze by itself, so the three
          # steps are the whole recipe here — but a freeze that still holds
          # refuses them, and the recipe used to say nothing about it.
          f"     {PY} {tool} unfreeze \"{workdir}\" --reason \"...\"   "
          "# only if render says the freeze still holds\n"
          f"     {PY} {tool} render \"{workdir}\"\n"
          f"     {PY} {tool} check \"{workdir}\"\n"
          f"     {PY} {tool} freeze \"{workdir}\"")
    if not args.go and not args.skip_memory:
        # A dry run never reaches the pages or the views, so it cannot know
        # whether they are done; freezing before them locks names they add.
        print("   ⚠️  If the batch pages or the agent's identify views are not "
              "done yet, run this command with --go FIRST — it stops for each "
              "of them — and freeze after the pages and the views.")
    sys.exit(EXIT_STALE_FREEZE)


def print_screen_checkpoint(workdir, profile=None):
    """G-2, trigger (b): the onboarding checkpoint the run could not stop to
    hold. photo_plan queues a proposal whenever a size it has evidence for is
    missing from the pack; this is where the operator finally reads it.

    Deliberately a PRINT and nothing else — no prompt, no non-zero exit. The
    affected files are already in the to-be-checked bucket, so nothing is lost
    by the owner answering tomorrow, and a blocking question in the middle of
    a 7-unit collection is what trigger (b) was asked NOT to be.

    Card 9 — only the sizes the owner has not answered (the file outlives the
    answer), and the one route that adds one: the onboarding sheet, whose
    census asks every size this proposes. `profile` None = the work dir's own."""
    path = Path(workdir) / "plan" / SCREEN_PROPOSALS_NAME
    if not path.exists():
        return
    if profile is None:
        try:
            profile = photo_profile.load_profile(workdir=workdir)
        except SystemExit:
            profile = {}      # a banner never stops the run; list them all
    open_sizes = {tuple(d) for d in photo_profile.open_screen_proposals(path, profile)}
    if not open_sizes:
        return
    q = json.loads(path.read_text())
    print("\n===== onboarding checkpoint — unconfirmed screen size(s) =====")
    for c in q.get("proposed_screen_dims", []):
        if tuple(int(v) for v in c["dims"]) not in open_sizes:
            continue
        print(f"  {c['dims'][0]}x{c['dims'][1]} — {c['files_at_this_size']} "
              f"file(s) at this size, proven a screen by {c['proven_by']!r}")
    moved = sum((q.get("moved_to_to_be_checked") or {}).values())
    # F-13 (owner ruling 20260924) — never a hand edit. Card 9: the sheet asks
    # these sizes, and its dry run counts what one moves before the owner's yes.
    print("  These sizes are NOT added to the owner's pack, and this run "
          "added none.")
    if moved:
        print(f"  {moved} file(s) at these sizes went to the to-be-checked "
              "bucket rather than a trip folder. The run was not blocked.")
    else:
        print("  Nothing moved: no file went to the to-be-checked bucket "
              "because of these sizes (a file whose name proves it a "
              "screenshot was filed by that name). No action is needed for "
              "this run.")
    print("  To add one: make the onboarding sheet for this work dir and "
          "answer its screen: line — its dry run counts what the size moves "
          "before the owner says yes:\n"
          f"      {PY} {Path(__file__).resolve().parent}/photo_onboard_page.py "
          f"sheet \"{workdir}\" --out-dir <folder>")
    print(f"  Full proposal: {path}")


# Written by photo_plan.PAPERWORK_MOVED_NAME; spelled out for the reason the
# screen-proposals name is.
PAPERWORK_MOVED_NAME = "paperwork-moved.json"


def print_paperwork_checkpoint(workdir):
    """W2C / ADR 0005 — the disclosure, summed over every plan of the dump.
    The files are already in the to-be-checked bucket; this says so where the
    operator reads. A print, never a prompt and never a non-zero exit."""
    path = Path(workdir) / "plan" / PAPERWORK_MOVED_NAME
    if not path.exists():
        return
    try:
        counts = json.loads(path.read_text())
    except ValueError:
        return
    moved = sum(int(v) for v in counts.values()) if isinstance(counts, dict) else 0
    if not moved:
        return
    profile = photo_profile.load_profile(workdir=workdir)
    msg = photo_profile.messages(profile)
    print("\n" + msg["run_paperwork_banner"].format(
        n=moved, bucket=photo_profile.buckets(profile)["to_be_checked"]))


# `photo_memory review --pre-plan` returns this when it actually asked. Named
# here rather than imported: the conductor shells out to every stage and holds
# no registry, so the one thing it may know about a checkpoint is its exit
# status.
PRE_PLAN_ROUND_FIRED_RC = 10

# U5-06: the conductor picks the page number and passes it, so the page
# written and the `confirm` command printed carry ONE number. A copy of
# `photo_memory.next_checkpoint()` for the reason above; a case holds them equal.
REVIEW_PAGE = re.compile(r"memory-review_C(\d+)\.md$")


def next_checkpoint(workdir):
    used = [int(REVIEW_PAGE.search(p.name).group(1))
            for p in Path(workdir).glob("memory-review_C*.md")
            if REVIEW_PAGE.search(p.name)]
    return (max(used) + 1) if used else 1


def preview_stops(args, workdir):
    """M1 — a dry run says where `finish --go` would STOP before copying. Each
    stage is asked with `--preview`, which decides exactly as the real run
    does and writes nothing."""
    if args.skip_memory:
        print("  --go with --skip-memory goes past the pages and the views")
        return
    pack = load_pack_cached(args, workdir)
    if pack.dir is None:
        return
    if indexed(workdir):
        rc = run("photo_memory.py", "review", workdir, "--next-page", "--preview",
                 python=page_python()).returncode
        if rc in (PAGE_WRITTEN_RC, PAGE_WAITING_RC):
            print("  ⚠️ `finish --go` would STOP here, before copying: "
                  + ("a batch page is due (above)" if rc == PAGE_WRITTEN_RC
                     else "a batch page still waits for its answer (above)"))
            return
        rc = run("photo_index.py", "identify", workdir, "--new-only",
                 "--preview", python=page_python()).returncode
        if rc == IDENTIFY_VIEWS_RC:
            print("  ⚠️ `finish --go` would STOP here, before copying, for the "
                  "agent's identify views (above)")
            return
        print("  `finish --go` would not stop for a page or for views")
        return
    rc = run("photo_memory.py", "review", workdir, "--pre-plan", "--preview",
             "--checkpoint", next_checkpoint(workdir),
             python=page_python()).returncode
    if rc == PRE_PLAN_ROUND_FIRED_RC:
        print("  ⚠️ `finish --go` would STOP here, before copying: a naming "
              "round would be put to the owner (above)")
    else:
        print("  `finish --go` would not stop for a naming round")


def pre_plan_checkpoint(args, workdir):
    """U-2 — the naming round, run BEFORE anything is copied. -> True when the
    caller must stop.

    A folder name is rendered from the subject REGISTRY at copy time, and
    `photo_plan.visual_columns()` already prints a CONFIRMED subject's real
    name (an unconfirmed one prints its class word with a `draft:` prefix, and
    must keep doing so — N-4). So `[who]` reaching a first dump's folders is a
    question of ORDER and nothing else: the only checkpoint that existed ran
    at the end of `finish`, minutes after the files were copied. In UAT01-3
    that scored `who` 0/15 with 38 subjects drafted and never put to the
    owner.

    ⛔ NOT `--final`. The guaranteed end-of-dump round still fires at the end
    of `finish`, and it is the one that is never charged. This is an ordinary
    round: it fires only when the floor is met and the budget allows, both
    judged inside `sns_round()`, and it is charged.

    ⛔ NOT a gate. It costs ONE extra invocation and only when there was
    something to ask: once the page is written, those ids are on it, so
    `asked_before()` books them and the same checkpoint withholds on the
    re-run whether or not the owner answered a word. An owner who declines to
    name anything still reaches `plan`, `[who]` stays empty, and that is a
    legal outcome. `--skip-memory` is the way past it in one run.

    ⚠️ `--go` ONLY, the same as the final round and for the same reason:
    `rounds_fired()` counts pages carrying a question block, so a dry run that
    wrote a real page would spend a round the owner never saw.
    """
    if not args.go:
        if indexed(workdir):
            print("\n(the batch pages and the agent's identify views run only "
                  "with --go — a dry run writes no page and no views)")
        else:
            print("\n(the pre-plan naming round runs only with --go — a dry run "
                  "renders draft names and books nothing)")
        preview_stops(args, workdir)
        return False
    if args.skip_memory:
        print("\n(--skip-memory: the pre-plan naming round was not run; any "
              "unconfirmed subject renders its class word with `draft:`)")
        return False
    pack = load_pack_cached(args, workdir)
    if pack.dir is None:
        # Same posture as the final round: a dump with no owner pack is legal
        # and common — it is what every benchmark run is — and is said out
        # loud rather than skipped silently.
        print("\n(no owner pack bound to this dump — the pre-plan naming "
              "round is skipped; there is no owner memory to name from)")
        return False
    if indexed(workdir):
        return batch_page_checkpoint(workdir, pack)
    print("\n===== pre-plan naming checkpoint (U-2) =====")
    checkpoint = next_checkpoint(workdir)
    rc = run("photo_memory.py", "review", workdir, "--pre-plan",
             "--checkpoint", checkpoint, python=page_python()).returncode
    if rc == PRE_PLAN_ROUND_FIRED_RC:
        print("\n⛔ STOPPED BEFORE COPYING — nothing was written.\n"
              "   A naming round was just put to the owner. Answer the review "
              f"page (memory-review_C{checkpoint}.md), then:\n"
              f"     {PY} {HERE / 'photo_memory.py'} confirm \"{workdir}\" "
              f"--checkpoint {checkpoint} --go\n"
              "   then re-run this command. A subject confirmed now is named "
              "INTO the folder; a subject confirmed after the copy is not, "
              "and nothing renames folders on the drive.\n"
              "   To go ahead without answering, add --skip-memory.")
        return True
    if rc != 0:
        stage_failed("the pre-plan naming round", rc,
                     f"{photo_platform.run_line(page_python(), HERE / 'photo_memory.py')} "
                     f"review \"{workdir}\" --pre-plan --checkpoint {checkpoint}")
    return False


# `photo_memory review --next-page` returns these; copies, for the reason
# PRE_PLAN_ROUND_FIRED_RC is one (a case holds them equal).
PAGE_WRITTEN_RC = 11
PAGE_WAITING_RC = 12
# `photo_index identify` returns this when it wrote views for the agent (G7).
IDENTIFY_VIEWS_RC = 13
BATCH_PAGE = re.compile(r"^P-B(\d{2,})\.md$")

# FIX6 (U6-21) — `finish` exits with this when a naming stage (a batch page,
# the pre-plan round, identify) did not finish. It used to warn "Planning
# continues" and run on to the ordinary freeze stop, so a crashed page read
# exactly like a question, and the pages and views after it were skipped.
EXIT_STAGE_FAILED = 5
# The repo virtualenv. A place page's U3-06 document check needs CLIP, which
# the system interpreter the SKILL writes (`python3`) does not have.
VENV_PYTHON = photo_platform.venv_python(HERE.parent)


def page_python():
    """-> the interpreter for the page and identify stages: the repo `.venv`
    whenever there is one, else this one (a pet page needs no CLIP, and a
    place page then stops the run).

    F22/F23: never "this one when it has open_clip". A python can have
    open_clip and still lack pillow-heif, and then every HEIC frame lost its
    crop; the page now refuses such a frame, so this stage must run where the
    crops can be made."""
    if not VENV_PYTHON.is_file():
        return sys.executable
    return str(VENV_PYTHON)


def stage_failed(stage, rc, line, note=""):
    """⛔ A naming stage that did not finish STOPS the copy. Never "Planning
    continues": render/check/freeze advice past a skipped page freezes names
    the owner and the agent were never asked for."""
    print(f"\n⛔ STOPPED BEFORE COPYING — nothing was copied.\n"
          f"   {stage} did not finish (exit {rc}); its own message is above.\n"
          + (f"   {note}\n" if note else "")
          + f"   Run it again by hand:\n     {line}\n"
          "   then re-run this command. To go ahead without naming, add "
          "--skip-memory.")
    sys.exit(EXIT_STAGE_FAILED)


def batch_page_checkpoint(workdir, pack=None):
    """G6 (owner R3) — on a dump WITH an index, the per-batch pages REPLACE the
    U-2 round. -> True when the caller must stop.

    One page per stop (R4). The page named in the stop message is the highest
    numbered `P-B*.md`: pages are written in date order, one at a time, and a
    new one is never written while one waits, so the newest page is the only
    one that can be unapplied. SNS-4's end-of-dump round is untouched."""
    print("\n===== per-batch pages (G6) =====")
    rc = run("photo_memory.py", "review", workdir, "--next-page",
             python=page_python()).returncode
    if rc in (PAGE_WRITTEN_RC, PAGE_WAITING_RC):
        pages = sorted((int(m.group(1)), p.name) for p in Path(workdir).glob("P-B*.md")
                       for m in [BATCH_PAGE.match(p.name)] if m)
        name = pages[-1][1] if pages else "P-B??.md"
        page = name[:-3]
        print("\n⛔ STOPPED BEFORE COPYING — nothing was written.\n"
              + (f"   A page was just put to the owner: {name}.\n"
                 if rc == PAGE_WRITTEN_RC else
                 f"   {name} is still waiting for its answer.\n")
              + "   Make the owner's web page for it:\n"
              f"     {VENV_PYTHON} {HERE / 'photo_review_page.py'} render "
              f"\"{Path(workdir) / name}\" --workdir \"{workdir}\""
              + (f" --pack \"{pack.dir}\"" if pack is not None and pack.dir else "")
              + "\n   Answer it, then run these two lines:\n"
              f"     {PY} {HERE / 'photo_memory.py'} confirm \"{workdir}\" "
              f"--page {page} --go\n"
              f"     {PY} {HERE / 'photo_index.py'} apply-page \"{workdir}\" "
              f"{page} --go\n"
              "   then re-run this command: it writes the next page, or goes on "
              "to the copy when none is due. A name confirmed now is named INTO "
              "the folder. After the copy, a name the end-of-dump page changes "
              "reaches a folder only through a re-lock (render, check, freeze), "
              "and the engine never renames a copied folder: the freeze lists "
              "it to rename by hand (plan/folder-renames.md).\n"
              "   To go ahead without answering, add --skip-memory.")
        return True
    if rc != 0:
        stage_failed(
            "the batch page", rc,
            f"{VENV_PYTHON} {HERE / 'photo_memory.py'} review \"{workdir}\" --next-page",
            note="" if VENV_PYTHON.is_file() else
            f"There is no repo virtualenv at {VENV_PYTHON}: a place page checks its "
            "photos for documents with CLIP and needs it (photo-init sets it up).")
    return identify_checkpoint(workdir)


def freeze_holds(workdir):
    """-> True when the index's freeze still holds. Asked of `verify` with its
    output captured, so the stop message stays as it was when it does not."""
    r = subprocess.run([sys.executable, str(HERE / "photo_index.py"), "verify",
                        str(workdir)], capture_output=True, text=True)
    return r.returncode == 0


def identify_checkpoint(workdir):
    """G7 (D-I11) — once no page is due, recognition proposes pet names on the
    batches the pages did not reach, and the AGENT views each photo before a
    name is applied. -> True when the caller must stop (views wanted).

    Idempotent: a photo with any recorded verdict is not proposed again, and
    (G7g) nor is a row a views file already showed and the agent left blank —
    a blank names nothing, so it never blocks the copy; `identify` run by hand
    shows it again."""
    print("\n===== agent identification (G7) =====")
    # F-r (Card 6): the crops need the preview libraries (pillow-heif,
    # ffmpeg) exactly as the pages' do — same interpreter choice.
    rc = run("photo_index.py", "identify", workdir, "--new-only",
             python=page_python()).returncode
    if rc == IDENTIFY_VIEWS_RC:
        views = Path(workdir) / "identify-views.md"
        tool = HERE / "photo_index.py"
        if freeze_holds(workdir):
            # FIX9 F10: a freeze that holds refuses `identify --answers --go`
            # (D-I16) — after a correction made past the copy it always holds.
            route = (f"     {PY} {tool} unfreeze \"{workdir}\" --reason \"...\"   "
                     "(the freeze locks the names)\n"
                     f"     {PY} {tool} identify \"{workdir}\" --answers \"{views}\" --go\n"
                     f"     {PY} {tool} render \"{workdir}\"\n"
                     f"     {PY} {tool} check \"{workdir}\"\n"
                     f"     {PY} {tool} freeze \"{workdir}\"\n")
        else:
            route = (f"     {PY} {tool} identify \"{workdir}\" "
                     f"--answers \"{views}\" --go\n"
                     f"     {PY} {tool} render \"{workdir}\"   "
                     "(then check and freeze)\n")
        print("\n⛔ STOPPED BEFORE COPYING — no name was applied.\n"
              f"   Recognition proposes pet names on photos: {views}.\n"
              "   Open each photo, look, and write agree / no / unsure on its row "
              "(a stranger that looks like a pet is `no`; a blank row names "
              "nothing and this command does not ask it again). Then run:\n"
              + route +
              "   then re-run this command. An agreed name is named INTO the "
              "folder; nothing is learned from it.\n"
              "   To go ahead without naming, add --skip-memory.")
        return True
    if rc != 0:
        stage_failed("agent identification", rc,
                     f"{PY} {HERE / 'photo_index.py'} identify \"{workdir}\" --new-only")
    return False


def cmd_plan(args):
    workdir = resolve_workdir(args.workdir, args)
    frozen = indexed(workdir)
    plans = load_plans(workdir)
    if not plans and not frozen:
        sys.exit(f"no plans.json in {workdir} — author it first (step B)")
    if pre_plan_checkpoint(args, workdir):
        sys.exit(3)
    if frozen:
        freeze_gate(args, workdir, "BEFORE COPYING")
        plans = load_plans(workdir)
    rc = run_one_plan(
        workdir, plans, args.plan, args.go, force=args.force,
        no_vision=args.no_vision, frozen=frozen,
        before_execute=(lambda: freeze_gate(args, workdir, "BEFORE THE COPY"))
        if frozen else None)
    print_screen_checkpoint(workdir)
    print_paperwork_checkpoint(workdir)
    if not args.go:
        print("\nDRY-RUN — nothing copied. Add --go to execute.")
    sys.exit(rc)


def cmd_finish(args):
    workdir = resolve_workdir(args.workdir, args)
    frozen = indexed(workdir)
    plans = load_plans(workdir)
    if not plans and not frozen:
        sys.exit(f"no plans.json in {workdir} — author it first (step B)")
    if pre_plan_checkpoint(args, workdir):
        sys.exit(3)
    checked = []

    def before_first_copy():
        # Once before the plan loop (below), and once more just before the
        # FIRST photo_execute: a confirm run beside this one between the two
        # moves the pack id, and nothing may be copied under the old name.
        if not checked:
            checked.append(True)
            freeze_gate(args, workdir, "BEFORE THE FIRST COPY")

    if frozen:
        freeze_gate(args, workdir, "BEFORE COPYING")
        plans = load_plans(workdir)
    flagged = []
    for p in sorted(plans["plans"], key=lambda x: x["plan"]):
        print(f"\n===== P{p['plan']} — {p.get('title', '')} =====")
        rc = run_one_plan(workdir, plans, p["plan"], args.go,
                          force=args.force, no_vision=args.no_vision,
                          frozen=frozen,
                          before_execute=before_first_copy if frozen else None)
        if rc != 0:
            flagged.append(f"P{p['plan']}")
    if frozen and (workdir / "no-date-files.csv").exists():
        # The freeze wrote and hashed the no-date plan too; it is not re-rendered.
        print("\n===== no-date plan (from the freeze) =====")
        before_first_copy()
        ex = ["photo_execute.py", workdir, "--no-date"]
        if args.go:
            ex.append("--go")
        if run(*ex).returncode != 0:
            flagged.append("no-date")
    elif (workdir / "no-date-files.csv").exists():
        # D13 (to-be-checked mod, 2026-07-06 evening): no-date files are
        # auto-planned and copied to the monthly to-be-checked bucket (dump's
        # YYYYMM); AI-images needs a manual --ai-confirmed plan, never used
        # unattended. The bucket is named in the owner's language, so the
        # banner asks the pack rather than hardcoding one.
        bucket = photo_profile.buckets(
            photo_profile.load_profile(workdir=workdir))["to_be_checked"]
        print(f"\n===== no-date plan (D13: {bucket}) =====")
        if run("photo_plan.py", workdir, "--no-date").returncode == 0:
            ex = ["photo_execute.py", workdir, "--no-date"]
            if args.go:
                ex.append("--go")
            if run(*ex).returncode != 0:
                flagged.append("no-date")
        else:
            flagged.append("no-date")
    if frozen and args.go:
        print("\n===== copy check against the freeze =====")
        rc = run("photo_index.py", "verify", workdir, "--copied").returncode
        # F-mm — 6: every copy matches, only the owner pack moved since the
        # freeze (said above by verify). Not a failed copy, so not a flag.
        if rc not in (0, EXIT_PACK_MOVED):
            flagged.append("copy-check")
    if frozen:
        # FIX8 F8-2 — the folders a re-lock found renamed after their copy.
        import photo_execute
        plans = json.loads((workdir / "plans.json").read_text())
        todo = photo_execute.renames_to_do(plans, plans.get("dest_root") or "")
        if todo:
            print(f"\n===== {len(todo)} folder(s) to rename by hand on the drive "
                  "=====\nCopied before their names changed. Rename each one, in "
                  "this order — the engine never renames a folder, and copies "
                  "nothing new into one still to rename:")
            for old, new in todo:
                print(f'  "{old}" -> "{new}"')
    if args.go:
        # OA-4 backstop: mislabeled extensions are corrected at copy time
        # (D13), but merge destinations may hold older mismatched copies —
        # sweep this dump's destination folders (copies only, never sources)
        print("\n===== extension-mismatch rename (OA-4 backstop) =====")
        r = run("photo_rename_mismatches.py",
                "--plans", workdir / "plans.json", "--go")
        if r.returncode != 0:
            print("⚠️  rename step failed — run photo_rename_mismatches.py "
                  "manually on this dump's destination folders")
    else:
        print("\n(extension-mismatch rename runs only with --go)")

    # ---- SNS-4's guaranteed end-of-dump round --------------------------------
    #
    # The dump is over at this point, and that is the ONE fact this conductor
    # has that `photo_memory` cannot see for itself. It crosses the boundary as
    # `--final` and nothing else does: whether a round fires, how it is charged
    # against the budget and what it says are all decided inside `sns_round()`,
    # against evidence — how many frequently-seen subjects are newly
    # discovered, since which round — that lives in the registry and the work
    # dir's own pages. ⛔ No floor, no cap and no round counting here; a cadence
    # decided outside the thing holding the evidence is the mistake SNS-4
    # rejected by name.
    #
    # ⚠️ `--go` ONLY. `rounds_fired()` counts review files that carry a
    # question block, so a dry run writing a real page would book a round the
    # owner never saw and spend the budget on it.
    if args.go:
        pack = load_pack_cached(args, workdir)
        if pack.dir is None:
            # A dump with no owner pack is legal and common — it is what every
            # benchmark run is. Said out loud rather than skipped silently, and
            # it must not fail: `finish` has never depended on a pack and does
            # not start now.
            print("\n(no owner pack bound to this dump — the guaranteed "
                  "end-of-dump memory round is skipped; there is no owner "
                  "memory to review)")
        else:
            print("\n===== end-of-dump memory checkpoint (SNS-4) =====")
            # The same `run()` helper every other stage goes through, so the
            # pack this conductor resolved is the one the subprocess resolves
            # (`load_pack_cached` exports PHOTO_PROFILE). ⛔ Not an import:
            # the conductor holds no registry and is not going to start.
            if run("photo_memory.py", "review", workdir, "--final",
                   python=page_python()).returncode != 0:
                # A warning, NOT a flag. Nothing that was copied depends on
                # this page, so it must not change what `finish` exits with —
                # the same posture as the rename backstop above.
                print("⚠️  the end-of-dump review did not write a page — run "
                      "it by hand:\n     "
                      f"{photo_platform.run_line(page_python(), HERE / 'photo_memory.py')} "
                      f"review \"{workdir}\" --final\n"
                      "   Nothing this dump copied is affected.")
    else:
        print("\n(the end-of-dump memory round runs only with --go)")
        pack = load_pack_cached(args, workdir)
        if pack.dir is not None:
            rc = run("photo_memory.py", "review", workdir, "--final", "--preview",
                     "--checkpoint", next_checkpoint(workdir),
                     python=page_python()).returncode
            if rc == PRE_PLAN_ROUND_FIRED_RC:
                # UAT01-9 F11: a re-run wrote C3 beside an unconfirmed C2.
                print("  ⚠️ `finish --go` would end by putting a NEW page to the "
                      f"owner (memory-review_C{next_checkpoint(workdir)}.md, above) "
                      "— after the copy, and whether or not an earlier page is "
                      "still unanswered. It does not stop the copy.")

    print_screen_checkpoint(workdir)
    print_paperwork_checkpoint(workdir)
    print("\n--- finish done ---")
    # An indexed dry run writes nothing, the status ledger included (M5); a
    # dry run without an index approved batches, and the ledger says so.
    print_status(workdir, load_pack_cached(args, workdir),
                 write=args.go or not frozen)
    if not args.go:
        print("\nDRY-RUN — nothing copied. Re-run `finish --go` to execute.")
    if flagged:
        print(f"\n⚠️  plans with flags/failures needing attention: "
              f"{flagged} — see plan/execution-log_*.md")
        sys.exit(1)


def safe_console():
    """A Windows pipe without PYTHONUTF8 encodes as cp1252, which has no emoji,
    and the first ⚠️ raised UnicodeEncodeError: a fresh PC with no exiftool got
    a traceback where the checklist should be (RS5, measured). What cannot be
    encoded is written as an escape instead; a UTF-8 console is untouched."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


def main():
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir-root", default=None,
                    help="where per-dump state dirs live (default: auto-detect "
                         "a collection.json under cwd, else the profile's)")
    ap.add_argument("--profile", default=None,
                    help="path to this user's profile.json (home locations, "
                         "pets, language, clustering defaults); falls back to "
                         "the PHOTO_PROFILE env var")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("prep", help="scan + cluster a raw dump")
    sp.add_argument("source", help="source dump folder on the drive (read-only)")
    sp.add_argument("--force", action="store_true",
                    help="overwrite an existing batches.json (keeps .bak)")
    sp.add_argument("--no-recursive", action="store_true",
                    help="scan the source's top level only (loose-files unit "
                         "from photo-init: subfolders are their own units)")
    sp.add_argument("--no-cluster", action="store_true",
                    help="a FIRST dump: scan + census only, then stop. Answer "
                         "onboarding and write the pack, then run `cluster` "
                         "(G4 / D-I1)")
    sp.set_defaults(func=cmd_prep)

    sp = sub.add_parser("cluster", help="cluster a dump scanned with "
                                        "`prep --no-cluster`, with the pack")
    sp.add_argument("workdir", help="workdir path, source path, or dump name")
    sp.add_argument("--force", action="store_true",
                    help="overwrite an existing batches.json (keeps .bak)")
    sp.set_defaults(func=cmd_cluster)

    sp = sub.add_parser("status", help="show batch + plan state")
    sp.add_argument("workdir", help="workdir path, source path, or dump name")
    sp.add_argument("--paths", action="store_true",
                    help="also show dest_root and each plan's destination "
                         "folder (hidden by default)")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("plan", help="run one plan (dry-run unless --go)")
    sp.add_argument("workdir", help="workdir path, source path, or dump name")
    sp.add_argument("--plan", type=int, required=True)
    sp.add_argument("--go", action="store_true", help="actually copy")
    sp.add_argument("--force", action="store_true",
                    help="re-render even if the plan's batches are all done")
    sp.add_argument("--no-vision", action="store_true",
                    help="plan without see-stage output — WHO/WHAT are "
                         "given up for those batches (R1)")
    sp.add_argument("--skip-memory", action="store_true",
                    help="indexed: skip the batch pages AND the agent's "
                         "identify views; no index: skip the pre-plan naming "
                         "round (U-2). No folder then carries a pet's name")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser(
        "finish", help="run all plans + no-date (dry-run unless --go)",
        description="Run every plan in plans.json, then the no-date plan "
                    "(dry-run unless --go). With an index (photo_index.py), "
                    "copy only from its freeze. Exit codes: 0 done; 1 a plan "
                    "was flagged or failed; 3 a question was just put — a "
                    "batch page or the agent's identify views on an indexed "
                    "dump, the naming round on one with no index — answer "
                    "it, then re-run; "
                    f"{EXIT_STALE_FREEZE} this dump has an index and its "
                    "freeze is missing or no longer holds (the index, the "
                    "exported plan files or the owner pack changed since "
                    "`photo_index.py freeze`) — run render, check and freeze "
                    "again; nothing was copied.")
    sp.add_argument("workdir", help="workdir path, source path, or dump name")
    sp.add_argument("--go", action="store_true", help="actually copy")
    sp.add_argument("--force", action="store_true",
                    help="re-render plans whose batches are already done")
    sp.add_argument("--no-vision", action="store_true",
                    help="plan without see-stage output — WHO/WHAT are "
                         "given up for those batches (R1)")
    sp.add_argument("--skip-memory", action="store_true",
                    help="indexed: skip the batch pages AND the agent's "
                         "identify views; no index: skip the pre-plan naming "
                         "round (U-2). No folder then carries a pet's name")
    sp.set_defaults(func=cmd_finish)

    sp = sub.add_parser(
        "doctor", help="what this machine is missing, and how to install it",
        description="Check Python, exiftool, the repo .venv and the packages in "
                    "it, a real preview, and the network. Each missing item "
                    "comes with the install line for THIS OS. Exit 0 when "
                    "everything required to start is present, 1 otherwise; "
                    "vision-only gaps are listed and do not change the exit.")
    sp.add_argument("--json", action="store_true",
                    help="one JSON object, for the agent")
    sp.set_defaults(func=cmd_doctor)

    args = ap.parse_args()
    if args.profile:
        os.environ[photo_profile.ENV_VAR] = str(Path(args.profile).resolve())
    # workdir_root is resolved lazily (see resolve_workdir/cmd_prep) — a
    # `status`/`plan`/`finish` on an already-scanned dump never needs it, so
    # it must not demand a profile that isn't actually required.
    args.func(args)


if __name__ == "__main__":
    main()
