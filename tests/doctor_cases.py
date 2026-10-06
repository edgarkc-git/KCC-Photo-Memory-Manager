#!/usr/bin/env python3
"""RS5 — `photo_run.py doctor`: what this machine is missing, and the line
that installs it here.

A HIL tester installs on a PC nobody has seen, and a missing tool used to show
up mid-run. `doctor` lists every item up front with the install line for THIS
OS; `prep` runs the same checks and stops when exiftool is missing instead of
warning past it.

Nothing is installed to test this: a missing item is FAKED — a PATH without
the tool, a probe that reports a module absent, a network that raises — and
the OS is faked by passing it, never by patching `os.name` (pathlib breaks).

Each case says whether it REPRODUCES a defect (fails on b61a743) or only
GUARDS behaviour. `photo_run` is imported inside the cases, so on b61a743 each
case still runs and reports on its own.

Run:
  python3 tests/doctor_cases.py [-v]
"""

import argparse
import io
import shutil
import sys
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def no_exiftool_offline():
    """Patch PATH lookups to lose exiftool and the network to raise.
    -> restore()."""
    real = (shutil.which, urllib.request.urlopen)

    def which(name, *a, **kw):
        return None if name == "exiftool" else real[0](name, *a, **kw)

    def urlopen(*a, **kw):
        raise OSError("offline in this test")

    shutil.which, urllib.request.urlopen = which, urlopen

    def restore():
        shutil.which, urllib.request.urlopen = real
    return restore


class Reached(Exception):
    pass


@case
def missing_exiftool_stops_prep():
    """⭐ REPRODUCTION. ⛔ FAILS on b61a743: `prep` printed a warning for a
    missing exiftool and walked on into the preview probe and the scan, where
    every date read fails. It must stop at the checklist, before either."""
    import photo_run
    args = argparse.Namespace(source=str(ROOT), workdir_root=None,
                              no_recursive=False, no_cluster=False, force=False,
                              profile=None)
    saved = photo_run.preview_check

    def reached():
        raise Reached("prep went on to the preview probe")

    photo_run.preview_check = reached
    restore = no_exiftool_offline()
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            photo_run.cmd_prep(args)
        return False, "prep returned"
    except SystemExit as exc:
        return (exc.code not in (0, None) and "exiftool" in (str(exc.code)
                                                             + buf.getvalue())), \
            f"exit {exc.code!r}"
    except Reached as exc:
        return False, str(exc)
    finally:
        restore()
        photo_run.preview_check = saved


@case
def the_prep_stop_quotes_a_product_path_with_a_space():
    """⭐ REPRODUCTION (K3). The doctor line `prep` prints when it stops was
    `<python> <scripts>/photo_run.py doctor` with no quotes, so a product
    folder with a space broke it when copied. Both paths are quoted now."""
    import photo_platform
    import photo_run
    args = argparse.Namespace(source=str(ROOT), workdir_root=None,
                              no_recursive=False, no_cluster=False, force=False,
                              profile=None)
    saved = (photo_run.HERE, photo_platform.owner_python)
    photo_run.HERE = Path("/opt/my product/scripts")
    photo_platform.owner_python = lambda: "/opt/my env/bin/python3"
    restore = no_exiftool_offline()
    try:
        with redirect_stdout(io.StringIO()):
            photo_run.cmd_prep(args)
        return False, "prep returned"
    except SystemExit as exc:
        said = str(exc.code)
        want = ('`"/opt/my env/bin/python3" "/opt/my product/scripts/'
                'photo_run.py" doctor`')
        return want in said, said
    finally:
        restore()
        photo_run.HERE, photo_platform.owner_python = saved


# ---------------------------------------------------------------------------
# Facts in, items out. facts() is a healthy machine; each case breaks one fact.
# ---------------------------------------------------------------------------

OK_MODULES = {"pillow": "12", "pillow-heif": "1", "numpy": "2", "imageio-ffmpeg": "0.6",
              "torch": "2", "torchvision": "0.2", "open_clip_torch": "3",
              "ffmpeg": "imageio-ffmpeg"}
PLATFORMS = {"mac": "darwin", "windows": "win32", "linux": "linux"}


def facts(platform="darwin", **over):
    f = {"platform": platform, "python": [3, 12, 0], "exiftool": "13.55",
         "network": None, "venv": True, "modules": dict(OK_MODULES),
         "preview": {"backend": "pillow", "still": None, "heif": True,
                     "video": "imageio-ffmpeg"},
         "preview_error": None, "nvidia": False}
    f.update(over)
    return f


def item(fs, name):
    import photo_run
    return next(i for i in photo_run.doctor_items(fs) if i["item"] == name)


def per_os(name, **over):
    return {k: item(facts(p, **over), name) for k, p in PLATFORMS.items()}


@case
def a_healthy_machine_is_all_ok_and_ready():
    """GUARD. Nothing missing: every item OK, no install line anywhere."""
    import photo_run
    items = photo_run.doctor_items(facts())
    v = photo_run.verdict(items)
    return (all(i["ok"] and i["install"] is None for i in items)
            and v["ready_to_start"] and v["ready_for_vision"]
            and [i["item"] for i in items][:2] == ["Python", "exiftool"]
            and items[-1]["item"] == "network (Nominatim)"), v


@case
def missing_exiftool_names_this_oss_line_and_blocks_start():
    """GUARD (RS2 reproduced the brew-everywhere hint; this holds it in doctor)."""
    import photo_run
    it = per_os("exiftool", exiftool=None)
    ok = (not it["mac"]["ok"] and it["mac"]["need"] == "start"
          and it["mac"]["install"] == "brew install exiftool"
          and it["windows"]["install"].startswith("winget install")
          and "exiftool.org" in it["windows"]["note"]
          and "brew" not in it["windows"]["note"]
          and "libimage-exiftool-perl" in it["linux"]["install"]
          and it["linux"]["needs_admin"] and not it["mac"]["needs_admin"]
          and not photo_run.verdict(photo_run.doctor_items(
              facts(exiftool=None)))["ready_to_start"])
    return ok, {k: (v["install"], v["note"]) for k, v in it.items()}


@case
def an_old_python_names_this_oss_line():
    it = per_os("Python", python=[3, 9, 7])
    ok = (not it["mac"]["ok"] and "brew install python" in it["mac"]["install"]
          and "winget install Python" in it["windows"]["install"]
          and "apt install python3" in it["linux"]["install"]
          and it["linux"]["needs_admin"] and not it["windows"]["needs_admin"])
    return ok, {k: v["install"] for k, v in it.items()}


@case
def no_venv_names_this_oss_venv_line_and_checks_nothing_inside():
    import photo_run
    it = per_os(".venv", venv=False, modules=None, preview=None)
    heif = item(facts("win32", venv=False, modules=None, preview=None),
                "pillow-heif")
    ok = (it["mac"]["install"].startswith("python3 -m venv ")
          and it["windows"]["install"].startswith("py -3 -m venv ")
          and it["linux"]["install"].startswith("python3 -m venv ")
          and it["mac"]["need"] == "vision"
          and heif["detail"].startswith("not checked")
          and "Scripts" in heif["install"] and "python.exe" in heif["install"]
          and photo_run.verdict(photo_run.doctor_items(
              facts(venv=False, modules=None, preview=None)))["ready_to_start"])
    return ok, {**{k: v["install"] for k, v in it.items()},
                "heif": heif["install"]}


@case
def a_missing_package_is_installed_with_the_venvs_own_python():
    """Each of Pillow, pillow-heif, numpy, open_clip: MISSING, and its line
    runs the repo .venv's interpreter for THIS OS — never a bare `pip` — to
    install the repo's own extras (RS5b)."""
    bad = []
    for name, dist in (("Pillow", "pillow"), ("pillow-heif", "pillow-heif"),
                       ("numpy", "numpy"), ("open_clip", "open_clip_torch")):
        mods = dict(OK_MODULES, **{dist: None})
        it = per_os(name, modules=mods)
        for osn, i in it.items():
            want = ("Scripts" if osn == "windows" else "/bin/python3")
            if i["ok"] or want not in i["install"] or "-m pip install" not in i["install"] \
                    or "[all]" not in i["install"]:
                bad.append(f"{name}/{osn}: {i['install']}")
    size = item(facts(modules=dict(OK_MODULES, open_clip_torch=None)), "open_clip")
    if "CLIP about 600 MB" not in (size["size"] or ""):
        bad.append(f"open_clip size: {size['size']}")
    return not bad, bad


@case
def no_ffmpeg_on_either_route_is_missing_with_the_extras_line():
    it = per_os("ffmpeg", modules=dict(OK_MODULES, ffmpeg=None))
    path = item(facts(modules=dict(OK_MODULES, ffmpeg="path")), "ffmpeg")
    ok = (all(not i["ok"] and "[all]" in i["install"] for i in it.values())
          and path["ok"] and "on PATH" in path["detail"])
    return ok, {k: v["install"] for k, v in it.items()}


@case
def torch_is_cpu_only_on_a_pc_with_no_nvidia_gpu():
    """Windows and Linux with no NVIDIA GPU get the CPU index (the plain line
    pulls a CUDA build of several GB); a Mac and a CUDA PC do not."""
    mods = dict(OK_MODULES, torch=None)
    it = per_os("torch + torchvision", modules=mods)
    cuda = item(facts("win32", modules=mods, nvidia=True), "torch + torchvision")
    cpu = "download.pytorch.org/whl/cpu"
    ok = (cpu in it["windows"]["install"] and cpu in it["linux"]["install"]
          and cpu not in it["mac"]["install"] and cpu not in cuda["install"]
          and "pytorch.org" in cuda["note"] and "(" not in cuda["install"]
          and it["windows"]["size"] == "about 200 MB" and cuda["size"] == "several GB"
          and it["mac"]["size"])
    return ok, {**{k: (v["install"], v["size"]) for k, v in it.items()},
                "cuda": (cuda["install"], cuda["size"])}


@case
def a_preview_that_fails_is_missing_with_its_cause():
    it = item(facts(preview={"backend": "pillow", "still": "decode_failed",
                             "heif": True, "video": None}), "preview")
    none = item(facts(preview=None, preview_error="No module named PIL"), "preview")
    gaps = item(facts(preview={"backend": "pillow", "still": None, "heif": False,
                               "video": None}), "preview")
    ok = (not it["ok"] and "decode_failed" in it["detail"]
          and not none["ok"] and "No module named PIL" in none["detail"]
          and gaps["ok"] and "no HEIF decoder" in gaps["detail"])
    return ok, [it["detail"], none["detail"], gaps["detail"]]


# ---------------------------------------------------------------------------
# The real fact-gatherers, with the missing thing faked.
# ---------------------------------------------------------------------------

@case
def a_path_without_exiftool_and_no_network_are_measured_as_missing():
    """The real `exiftool_fact()` and `network_fact()` with PATH and the
    network faked away."""
    import photo_run
    restore = no_exiftool_offline()
    try:
        exif, net = photo_run.exiftool_fact(), photo_run.network_fact()
    finally:
        restore()
    it = item(facts(network=net), "network (Nominatim)")
    return (exif is None and net and not it["ok"] and it["need"] == "places"
            and "--no-geocode" in it["why"]), f"exif={exif!r} net={net!r}"


@case
def the_module_probe_reports_a_missing_module_as_missing():
    """The real MODULE_PROBE, run in this interpreter, asked for a module no
    machine has."""
    import photo_run
    saved = photo_run.VENV_MODULES
    photo_run.VENV_MODULES = saved + (("no_such_module_rs5", "no-such-dist-rs5"),)
    try:
        got = photo_run.module_fact(sys.executable)
    finally:
        photo_run.VENV_MODULES = saved
    return (got is not None and "no-such-dist-rs5" in got
            and got["no-such-dist-rs5"] is None and "ffmpeg" in got), got


# ---------------------------------------------------------------------------
# One list, one probe; exit codes and --json.
# ---------------------------------------------------------------------------

def run_doctor(fs, json_out=False):
    import photo_run
    saved = photo_run.gather_facts
    photo_run.gather_facts = lambda: fs
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            photo_run.cmd_doctor(argparse.Namespace(json=json_out))
        code = 0
    except SystemExit as exc:
        code = exc.code
    finally:
        photo_run.gather_facts = saved
    return code, buf.getvalue()


@case
def doctor_exits_1_only_when_a_start_item_is_missing():
    start, _ = run_doctor(facts(exiftool=None))
    vision, text = run_doctor(facts(modules=dict(OK_MODULES, torch=None)))
    healthy, _ = run_doctor(facts())
    return (start == 1 and vision == 0 and healthy == 0
            and "vision stages: not ready" in text), (start, vision, healthy)


@case
def json_says_what_the_agent_needs():
    import json
    code, out = run_doctor(facts("win32", exiftool=None, venv=False, modules=None,
                                 preview=None), json_out=True)
    d = json.loads(out)
    exif = next(i for i in d["items"] if i["item"] == "exiftool")
    return (code == 1 and d["ready_to_start"] is False
            and d["ready_for_vision"] is False and "exiftool" in d["missing"]
            and "winget" in exif["install"] and "exiftool.org" in exif["note"]
            and {"item", "ok", "need", "detail", "why", "install", "note",
                 "needs_admin", "size"} <= set(exif)), d["missing"]


@case
def prep_prints_the_same_install_line_doctor_does():
    """GUARD for "no second list": prep's warning carries doctor's own line."""
    import photo_run
    restore = no_exiftool_offline()
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            missing = photo_run.preflight()
    finally:
        restore()
    it = item(facts(sys.platform, exiftool=None), "exiftool")
    # an item may carry only a note; then the note is what prep must print
    said = [x for x in (it["install"], it["note"]) if x]
    return (missing == ["exiftool"] and bool(said)
            and all(x in buf.getvalue() for x in said)), buf.getvalue().strip()


@case
def the_preview_probe_runs_from_one_place():
    """GUARD: PREVIEW_PROBE is run by preview_probe() alone; prep and doctor
    both go through it."""
    src = (SCRIPTS / "photo_run.py").read_text(encoding="utf-8")
    runs = src.count('"-c", PREVIEW_PROBE')
    return runs == 1 and src.count("preview_probe()") >= 2, f"runs={runs}"


SWITCH_BACK_LINE = ("If you switched to manual mode for setup, you can "
                    "switch back to auto now.")


@case
def a_ready_doctor_ends_with_the_switch_back_line():
    """REPRODUCTION (F01, step 0 Path A). ⛔ FAILS on 5b320fb: doctor
    never said when an owner who switched to manual mode for setup could
    switch back. The line is the LAST one, and only when ready to start."""
    _code, ready = run_doctor(facts())
    _code, blocked = run_doctor(facts(exiftool=None))
    return (ready.rstrip().splitlines()[-1] == SWITCH_BACK_LINE
            and SWITCH_BACK_LINE not in blocked), ready[-200:]


@case
def a_doctor_without_the_vision_stages_says_a_run_needs_them():
    """REPRODUCTION (K1). Ready to start, vision stages not ready: doctor
    ended on "ready to start: yes" and the switch-back line, and the run
    stopped later at the preview check. The last lines now say a normal run
    needs step 4. Wording only: the exit code is still 0 (GUARD)."""
    code, said = run_doctor(facts(preview=None))
    tail = said.rstrip().splitlines()[-2:]
    full_code, full = run_doctor(facts())
    return (code == 0 and full_code == 0
            and "ready to start: yes · vision stages: not ready" in said
            and tail[0].startswith("⚠️  A normal run is NOT ready yet")
            and "docs/INSTALL.md step 4" in tail[1] and "ffmpeg" in tail[1]
            and SWITCH_BACK_LINE not in said
            and "A normal run is NOT ready" not in full), said[-400:]


STEP_0 = "## Step 0: if your agent refuses to run this product"
DOCTOR_STEP = "## 3. Ask the machine: `doctor`"
STEP_0_LINK = "docs/INSTALL.md#step-0-if-your-agent-refuses-to-run-this-product"


def install_allow_blocks():
    """RS7: step 0 moved from the README into docs/INSTALL.md whole."""
    import json
    import re
    text = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    start = text.index(STEP_0)
    section = text[start:text.index("\n## ", start + 1)]
    return text, section, [json.loads(b) for b in
                           re.findall(r"```json\n(.*?)```", section, re.S)]


@case
def the_install_guide_has_step_0_and_both_paths():
    """REPRODUCTION (F01). ⛔ FAILS on 5b320fb: no step 0, so a fresh auto-mode
    agent was refused `[Code from External]` with nothing to tell the owner.
    Step 0 comes before step 1 (RS7f: the page reads in order) and so
    before the first product command (`doctor`), names both paths, and each allow block is valid JSON whose every rule names the
    product folder."""
    try:
        text, section, blocks = install_allow_blocks()
    except ValueError as exc:
        return False, f"no step 0: {exc}"
    rules = [r for b in blocks for r in b["permissions"]["allow"]]
    kinds = {r.split("(", 1)[0] for r in rules}
    first_step = "\n## 1. "
    return (DOCTOR_STEP in text and first_step in text
            and text.index(STEP_0) < text.index(first_step)
            < text.index(DOCTOR_STEP)
            and "Path A" in section and "Path B" in section
            and "[Code from External]" in section
            and "don't ask again" in section
            and len(blocks) == 2 and kinds == {"Bash", "PowerShell"}
            and all("<product folder>" in r for r in rules)
            and not any(r.rstrip(")").endswith("(*") for r in rules)), rules


@case
def the_readme_points_to_step_0_before_its_first_section():
    """RS7 GUARD. The README keeps a pointer, above its first section, that
    names the refusal and links to step 0 where it now lives."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    head = text[:text.index("\n## ")]
    return ("[Code from External]" in head and STEP_0_LINK in head
            and STEP_0 not in text), head[-300:]


@case
def the_first_skills_tell_the_agent_to_stop_on_code_from_external():
    """REPRODUCTION (F01). ⛔ FAILS on 5b320fb. The agent note sits at the
    top of photo-init and photo-run: tell the owner about step 0 first, and
    stop and relay a `[Code from External]` refusal, never work around it."""
    missing = []
    for skill in ("photo-init", "photo-run"):
        text = (ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
        head = text[:text.index("\n## ")]
        for words in ("Step 0", "docs/INSTALL.md", "[Code from External]",
                      "Never retry"):
            if words not in head:
                missing.append(f"{skill}: {words}")
    return not missing, missing


@case
def the_product_ships_no_permission_settings():
    """GUARD (F01). The product never grants itself permission: no
    `.claude/` settings file is tracked in the repo."""
    import subprocess
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True).stdout.splitlines()
    found = [f for f in tracked if f.startswith(".claude/") or "/.claude/" in f]
    return not found, found


@case
def every_install_line_is_a_command_a_shell_can_run():
    """GUARD. The SKILL runs `install` exactly as printed, so it must be a
    command and nothing else: no prose, no parenthetical (a syntax error in
    zsh, bash and PowerShell). Everything missing, every OS, NVIDIA or not."""
    import shlex
    import photo_run
    bad = []
    for plat in PLATFORMS.values():
        for nvidia in (False, True):
            fs = facts(plat, python=[3, 8, 0], exiftool=None, network="x",
                       venv=False, modules=None, preview=None, nvidia=nvidia)
            for i in photo_run.doctor_items(fs):
                line = i["install"]
                if line is None:
                    continue
                try:
                    words = shlex.split(line, posix=plat != "win32")
                except ValueError as exc:
                    bad.append(f"{plat} {i['item']}: {exc}")
                    continue
                if "(" in line or " or " in line or not words:
                    bad.append(f"{plat} {i['item']}: {line}")
    return not bad, bad


@case
def a_cp1252_console_gets_the_stop_message_not_a_traceback():
    """⭐ REPRODUCTION (measured 20260928 on the Mac with a strict cp1252
    stdout). A Windows pipe without PYTHONUTF8 encodes as cp1252, which has
    no emoji: preflight's first line raised UnicodeEncodeError, so a fresh PC
    with no exiftool saw a traceback instead of the checklist. main() now
    makes the console replace what it cannot encode."""
    import photo_run
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    real = sys.stdout
    restore = no_exiftool_offline()
    sys.stdout = console
    try:
        if hasattr(photo_run, "safe_console"):
            photo_run.safe_console()
        photo_run.preflight()
        console.flush()
        said = raw.getvalue().decode("cp1252")
        ok, detail = "exiftool" in said, said.strip()[:200]
    except UnicodeEncodeError as exc:
        ok, detail = False, f"UnicodeEncodeError: {exc}"
    finally:
        sys.stdout = real
        restore()
    return ok, detail


def extras_facts(plat, nvidia=False):
    mods = {k: None for k in OK_MODULES}
    return facts(plat, modules=mods, nvidia=nvidia,
                 preview={"backend": "pillow", "still": "no_pillow",
                          "heif": False, "video": None})


@case
def packages_come_from_the_repos_own_extras_not_a_hand_list():
    """⭐ REPRODUCTION (RS5b, the owner ruling, option c). ⛔ FAILS on 92246c1: every
    package line was a bare name (`pip install open_clip_torch`), a looser
    second copy of pyproject's version rules. Now each package item points at
    ONE line, `-e "<repo>[<extra>]"` with the .venv's own interpreter, where
    <extra> is an extra pyproject really declares — and the line names no
    package itself, so no version rule can live in doctor."""
    import tomllib
    import photo_run
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"]["optional-dependencies"]
    names = {n for pkgs in extras.values() for p in pkgs
             for n in [p.split("~")[0].split(">")[0].split("=")[0].strip()]}
    bad = []
    for osn, plat in PLATFORMS.items():
        for i in photo_run.doctor_items(extras_facts(plat, nvidia=True)):
            if i["item"] in ("Python", "exiftool", ".venv", "preview",
                             "network (Nominatim)") or not i["install"]:
                continue
            line = i["install"]
            used = [e for e in extras if f"[{e}]" in line]
            if "-m pip install -e " not in line or len(used) != 1:
                bad.append(f"{osn} {i['item']}: {line}")
            elif any(n in line.replace(str(ROOT), "") for n in names):
                bad.append(f"{osn} {i['item']} names a package: {line}")
    return not bad, bad


@case
def a_pc_with_no_nvidia_card_runs_cpu_torch_first_then_the_extras():
    """GUARD. The install plan is ordered: on Windows/Linux with no NVIDIA
    card the CPU torch line runs BEFORE the extras line (docs/INSTALL.md
    step 4), or pip resolves torch from the extras and pulls the CUDA build."""
    import photo_run
    got = {}
    for osn, plat in PLATFORMS.items():
        plan = [p["run"] for p in photo_run.install_plan(
            photo_run.doctor_items(extras_facts(plat)))]
        got[osn] = plan
    cpu = "download.pytorch.org/whl/cpu"
    ok = True
    for osn in ("windows", "linux"):
        p = got[osn]
        ci = [k for k, l in enumerate(p) if cpu in l]
        ei = [k for k, l in enumerate(p) if "-e " in l]
        ok &= len(ci) == 1 and len(ei) == 1 and ci[0] < ei[0]
    ok &= not any(cpu in l for l in got["mac"]) and sum("-e " in l for l in got["mac"]) == 1
    return bool(ok), got


@case
def the_plan_runs_each_line_once_and_keeps_every_item_listed():
    """GUARD. Seven MISSING package items, one extras line in the plan that
    says which items it covers; the per-item list and sizes stay."""
    import photo_run
    items = photo_run.doctor_items(extras_facts("darwin"))
    plan = photo_run.install_plan(items)
    extras = [p for p in plan if "-e " in p["run"]]
    missing = [i["item"] for i in items if not i["ok"]]
    return (len(extras) == 1 and {"Pillow", "numpy", "open_clip",
                                  "torch + torchvision"} <= set(extras[0]["covers"])
            and len({p["run"] for p in plan}) == len(plan)
            and "numpy" in missing
            and any(i["size"] for i in items if i["item"] == "open_clip")), \
        {"plan": plan, "missing": missing}


@case
def a_foreign_os_venv_path_is_right_on_any_host():
    """⭐ REPRODUCTION (RS5c, measured on Win11 by C205). ⛔ FAILS on 405eb0c:
    venv_python() built the path for the OS it NAMES with the HOST's Path,
    so a Windows host printed the Mac and Linux lines as `.venv\\bin\\python3`.
    A Windows host is faked the way pathlib itself would see one: the
    module's Path is PureWindowsPath and its host OS is `nt`."""
    from pathlib import PureWindowsPath
    import photo_platform
    saved_path = photo_platform.Path
    had_host = hasattr(photo_platform, "HOST_OS")
    saved_host = getattr(photo_platform, "HOST_OS", None)
    photo_platform.Path = PureWindowsPath
    photo_platform.HOST_OS = "nt"
    repo = PureWindowsPath("C:/dev/repo")
    try:
        mac = str(photo_platform.venv_python(repo, os_name="posix"))
        win = str(photo_platform.venv_python(repo, os_name="nt"))
        line = photo_platform.pip_line(["x"], repo, "linux")
    finally:
        photo_platform.Path = saved_path
        if had_host:
            photo_platform.HOST_OS = saved_host
        else:
            del photo_platform.HOST_OS
    ok = (mac.endswith("/.venv/bin/python3") and "\\.venv" not in mac
          and win.endswith("\\.venv\\Scripts\\python.exe")
          and "/.venv/bin/python3" in line)
    return ok, {"mac": mac, "win": win, "linux line": line}


@case
def windows_exiftool_has_an_admin_free_winget_line():
    """⭐ REPRODUCTION (RS5c). ⛔ FAILS on 405eb0c: Windows exiftool had no
    install line, only the exiftool.org note. `winget` is on PATH on the
    Win11 PC and lists the package id (measured by C205); the installer page
    stays as the note, for a PC without winget."""
    # RS5c amendment: the manifest (13.59, read by C205) is an Inno installer
    # with a user scope and a machine scope; only `--scope user` makes "no
    # admin" true rather than winget's default. A user-scope install lands on
    # the USER Path, which a session started before it does not see.
    it = item(facts("win32", exiftool=None), "exiftool")
    note = it["note"] or ""
    mac = item(facts("darwin", exiftool=None), "exiftool")
    return (it["install"] == "winget install --id OliverBetz.ExifTool -e --scope user"
            and not it["needs_admin"] and "exiftool.org" in note
            and "reopen" in note and "Claude Code" in note
            and "doctor again" in note
            and "reopen" not in (mac["note"] or "")), \
        (it["install"], it["note"], it["needs_admin"])


@case
def the_owner_types_py_on_windows():
    import photo_platform
    return (photo_platform.owner_python("nt") == "py"
            and photo_platform.owner_python("posix") == "python3"), ""


# ---------------------------------------------------------------------------
# H-G (obs-16) — a build id a tester can report
# ---------------------------------------------------------------------------

def git(*args, cwd):
    """git with the hook's GIT_* scrubbed: run from the pre-commit hook, an
    inherited GIT_DIR would point every call here at the real repo."""
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, env=env, check=True)


def tagged_repo(tmp):
    """-> a temp repo whose BUILD.txt is the shipped placeholder, marked
    export-subst exactly as the product's own .gitattributes marks it, and
    tagged v9.9.9."""
    repo = Path(tmp) / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "BUILD.txt").write_text(
        (SCRIPTS / "BUILD.txt").read_text(encoding="utf-8"), encoding="utf-8")
    (repo / ".gitattributes").write_text("scripts/BUILD.txt export-subst\n")
    (repo / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    git("init", "-q", cwd=repo)
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "one", cwd=repo)
    git("tag", "v9.9.9", cwd=repo)
    return repo


@case
def doctor_names_the_build():
    """REPRODUCTION (HIL01 obs-16). ⛔ FAILS on 6419ced: doctor printed no
    build at all, and a GitHub zip carries no commit, so a tester could not
    say which build they ran. The text has a `build:` line, the JSON a
    `build` field."""
    import json
    _code, text = run_doctor(facts())
    _code, out = run_doctor(facts(), json_out=True)
    line = next((ln for ln in text.splitlines() if ln.startswith("build: ")), "")
    return (bool(line) and json.loads(out).get("build") == line[len("build: "):]), \
        f"line={line!r} json={json.loads(out).get('build')!r}"


@case
def a_release_zip_names_its_tag_and_commit():
    """GUARD (H-G), route 1: the zip `git archive` makes of a tag — what a
    GitHub release download is — names the tag and the commit, with no git
    beside it. Fed by a real archive, never a hand-typed stamp."""
    import tempfile
    import zipfile
    import photo_run
    if not hasattr(photo_run, "build_id"):
        return False, "photo_run has no build_id"
    with tempfile.TemporaryDirectory() as tmp:
        repo = tagged_repo(tmp)
        sha = git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        zpath = Path(tmp) / "release.zip"
        git("archive", "--format=zip", "--prefix=unzipped/", "-o", str(zpath),
            "v9.9.9", cwd=repo)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        got = photo_run.build_id(Path(tmp) / "unzipped" / "scripts" / "BUILD.txt",
                                 Path(tmp) / "unzipped")
    return (got.startswith("v9.9.9 (commit ") and sha[:7] in got), got


@case
def a_clone_names_its_build_through_git():
    """GUARD (H-G), route 2: a clone keeps the placeholder; git describes it."""
    import tempfile
    import photo_run
    if not hasattr(photo_run, "build_id"):
        return False, "photo_run has no build_id"
    with tempfile.TemporaryDirectory() as tmp:
        repo = tagged_repo(tmp)
        got = photo_run.build_id(repo / "scripts" / "BUILD.txt", repo)
    return got == "v9.9.9 (a git clone)", got


@case
def a_copy_with_neither_says_it_does_not_know():
    """GUARD (H-G), route 3: no stamp and no git — a copied folder — says it
    does not know, and gives the pyproject version beside it."""
    import shutil as sh
    import tempfile
    import photo_run
    if not hasattr(photo_run, "build_id"):
        return False, "photo_run has no build_id"
    with tempfile.TemporaryDirectory() as tmp:
        repo = tagged_repo(tmp)
        sh.rmtree(repo / ".git")
        got = photo_run.build_id(repo / "scripts" / "BUILD.txt", repo)
    return got == "unknown (not a release download) — version 9.9.9", got


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
        print(f"{'PASS' if ok else 'FAIL'}  {fn.__name__:<{width}}"
              + (f"  {detail}" if (args.verbose or not ok) and detail else ""))
        if not ok:
            failures.append(fn.__name__)
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} doctor cases passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
