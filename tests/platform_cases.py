#!/usr/bin/env python3
"""RS2 — the repo `.venv` path and the install / mount hints on every OS.

The `.venv` interpreter was spelled `.venv/bin/python3` at eight sites in five
scripts, so on
Windows (`.venv\\Scripts\\python.exe`) every "is there a .venv?" check said no
and the run carried on under whatever Python started it. `prep` told every
machine to `brew install exiftool`, and a missing source listed `/Volumes`,
which Windows and Linux do not have, so the error message itself crashed.

Each case says whether it REPRODUCES a defect (fails on 98e13ae) or only
GUARDS behaviour. `photo_platform` is imported inside the cases, so on
98e13ae each case still runs and reports on its own.

Run:
  python3 tests/platform_cases.py [-v]
"""

import argparse
import ast
import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

CASES = []

# `.venv` then `bin` then `python3`, joined by anything a path expression or
# a printed line puts between them — including a line break.
HARDCODED_VENV = re.compile(r"\.venv[\s'\",/+()\\]*bin[\s'\",/+()\\]*python3")


def case(fn):
    CASES.append(fn)
    return fn


def without_docstrings(path):
    """-> the source with every docstring blanked: a docstring that DEFINES
    both spellings is documentation, not a site that picks one."""
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                for i in range(body[0].lineno - 1, body[0].end_lineno):
                    lines[i] = "\n"
    return "".join(lines)


@case
def no_script_spells_the_venv_itself():
    """REPRODUCTION. ⛔ FAILS on 98e13ae: eight sites in five scripts wrote
    `.venv/bin/python3` themselves (one across two lines). Also the
    no-second-copy rule: only photo_platform may spell it."""
    hits = [p.name for p in sorted(SCRIPTS.glob("*.py"))
            if p.name != "photo_platform.py"
            and HARDCODED_VENV.search(without_docstrings(p))]
    return not hits, f"hardcoded in {hits}"


@case
def windows_gets_the_scripts_python_exe():
    """REPRODUCTION. ⛔ FAILS on 98e13ae: photo_run had one constant and no
    OS in it, so Windows was told `.venv/bin/python3`."""
    import photo_run
    plat = getattr(photo_run, "photo_platform", None)
    if plat is None:
        return False, f"Windows gets {photo_run.VENV_PYTHON} (no OS choice)"
    got = plat.venv_python(ROOT, os_name="nt")
    return got.parts[-3:] == (".venv", "Scripts", "python.exe"), str(got)


def posix_venv(root):
    """The POSIX `.venv` interpreter for `root`, spelled the POSIX way on ANY
    host: on a Windows host `root / ".venv" / ...` would join with a
    backslash, which is not the path venv_python() gives for a foreign OS
    (RS5c) and not one a Mac or Linux owner could type."""
    return PurePosixPath(str(root), ".venv", "bin", "python3")


@case
def mac_and_linux_path_is_unchanged():
    """GUARD. The POSIX path stays byte-identical to what 98e13ae printed,
    unresolved (a worktree's `.venv` is a symlink), and photo_run takes this
    machine's answer from the one function."""
    import photo_platform
    import photo_run
    want = posix_venv(ROOT)
    got = photo_platform.venv_python(ROOT, os_name="posix")
    return (str(got) == str(want)
            and str(photo_run.VENV_PYTHON) == str(photo_platform.venv_python(ROOT))
            and photo_platform.venv_python() == photo_platform.venv_python(ROOT)), \
        f"got={got} run={photo_run.VENV_PYTHON}"


@case
def the_posix_expectation_holds_on_a_windows_host():
    """⭐ REPRODUCTION (RS5d, measured on Win11 by C205: 7/8 at 6a49ae6). The
    case above built its expectation with the HOST's Path, so on a Windows
    host it wanted `…\\.venv\\bin\\python3` while venv_python() rightly gives
    the POSIX spelling. A Windows host is faked as the doctor case does:
    the module's Path is PureWindowsPath, its host OS `nt`, a `C:` repo."""
    import photo_platform
    saved = (photo_platform.Path, photo_platform.HOST_OS)
    photo_platform.Path, photo_platform.HOST_OS = PureWindowsPath, "nt"
    root = PureWindowsPath("C:/dev/RS")
    try:
        got = photo_platform.venv_python(root, os_name="posix")
    finally:
        photo_platform.Path, photo_platform.HOST_OS = saved
    want = posix_venv(root)
    return str(got) == str(want), f"got={got} want={want}"


def no_volumes():
    """Make `/Volumes` absent the way Windows and Linux have it."""
    real = Path.iterdir

    def iterdir(self):
        if str(self) == "/Volumes":
            raise FileNotFoundError(2, "No such file or directory", "/Volumes")
        return real(self)

    Path.iterdir = iterdir
    return lambda: setattr(Path, "iterdir", real)


def exit_message(fn):
    """-> (message, None) for a clean sys.exit, (None, error) for a crash."""
    try:
        fn()
    except SystemExit as exc:
        return str(exc.code), None
    except Exception as exc:                                    # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    return None, "did not exit"


@case
def prep_missing_source_with_no_volumes_folder():
    """REPRODUCTION. ⛔ FAILS on 98e13ae: `prep` listed `/Volumes` to explain
    a missing source, and with no such folder that raised instead."""
    import photo_run
    missing = Path(tempfile.mkdtemp(prefix="rs2_")) / "not-here"
    args = argparse.Namespace(source=str(missing), workdir_root=None,
                              no_recursive=False)
    saved = (photo_run.preflight, photo_run.preview_check)
    photo_run.preflight = photo_run.preview_check = lambda: None
    restore = no_volumes()
    try:
        msg, err = exit_message(lambda: photo_run.cmd_prep(args))
    finally:
        restore()
        photo_run.preflight, photo_run.preview_check = saved
    return (msg is not None and "source not found" in msg
            and "connected" in msg), msg or err


@case
def quickscan_missing_root_with_no_volumes_folder():
    """REPRODUCTION. ⛔ FAILS on 98e13ae: the same crash in quickscan."""
    import photo_quickscan
    missing = Path(tempfile.mkdtemp(prefix="rs2_")) / "not-here"
    saved = sys.argv
    sys.argv = ["photo_quickscan.py", str(missing), "--no-exif"]
    restore = no_volumes()
    try:
        msg, err = exit_message(photo_quickscan.main)
    finally:
        restore()
        sys.argv = saved
    return (msg is not None and "not found" in msg
            and "connected" in msg), msg or err


@case
def mounted_volumes_are_still_listed_where_the_folder_exists():
    """GUARD. On a Mac the hint still names what is mounted."""
    import photo_platform
    tmp = Path(tempfile.mkdtemp(prefix="rs2_"))
    for name in ("DRIVE_A", "DRIVE_B", ".hidden"):
        (tmp / name).mkdir()
    got = photo_platform.source_missing_hint(tmp)
    shutil.rmtree(tmp)
    return ("DRIVE_A, DRIVE_B" in got and ".hidden" not in got), got


def preflight_text(platform):
    import photo_run
    real = (shutil.which, urllib.request.urlopen, sys.platform)

    def which(name, *a, **kw):
        return None if name == "exiftool" else real[0](name, *a, **kw)

    def urlopen(*a, **kw):
        raise OSError("offline in this test")

    shutil.which, urllib.request.urlopen, sys.platform = which, urlopen, platform
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            photo_run.preflight()
    finally:
        shutil.which, urllib.request.urlopen, sys.platform = real
    return buf.getvalue()


@case
def exiftool_hint_on_windows_is_not_brew():
    """REPRODUCTION. ⛔ FAILS on 98e13ae: preflight said `brew install
    exiftool` on every machine."""
    said = preflight_text("win32")
    return ("exiftool" in said and "brew" not in said
            and "exiftool.org" in said), said.strip()


@case
def exiftool_hint_per_os():
    """REPRODUCTION for its Linux half only (⛔ FAILS on 98e13ae: Linux was
    told brew); GUARD for its macOS half, which keeps brew."""
    mac, linux = preflight_text("darwin"), preflight_text("linux")
    return ("brew install exiftool" in mac and "brew" not in linux
            and "libimage-exiftool-perl" in linux), f"mac={mac!r} linux={linux!r}"


@case
def windows_install_lines_run_in_powershell():
    """REPRODUCTION (F03). ⛔ FAILS on 5b320fb: the printed pip line started
    with a quoted path, which PowerShell prints as a string instead of
    running. It now starts with `& `; the POSIX line is unchanged (GUARD)."""
    import photo_platform
    win = photo_platform.pip_line(["x"], PureWindowsPath(r"C:\p q"), "win32")
    mac = photo_platform.pip_line(["x"], PurePosixPath("/p q"), "darwin")
    return (win.startswith('& "') and win.endswith(" -m pip install x")
            and mac.startswith('"') and not mac.startswith("&")), (win, mac)


@case
def next_step_hints_survive_a_path_with_a_space():
    """REPRODUCTION (F03). ⛔ FAILS on 5b320fb: the visual-pass hints printed
    the `.venv` python and the script unquoted, so a folder with a space split
    into two words and the line did not run."""
    import shlex
    import photo_run
    saved = (photo_run.HERE, photo_run.VENV_PYTHON)
    buf = io.StringIO()
    try:
        photo_run.HERE = Path("/p q/scripts")
        photo_run.VENV_PYTHON = Path("/p q/.venv/bin/python3")
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(buf):
            photo_run.print_visual_pass(Path(tmp), [1])
        here, venv = photo_run.HERE, photo_run.VENV_PYTHON
    finally:
        photo_run.HERE, photo_run.VENV_PYTHON = saved
    lines = [l.strip() for l in buf.getvalue().splitlines()
             if "photo_" in l and not l.strip().startswith("#")]
    words = []
    for line in lines:
        # Split as this host's shell would; on nt `&` is F03's own call
        # operator, not part of the command.
        w = [x.strip('"') for x in shlex.split(line, posix=os.name != "nt")]
        words.append(w[1:] if w[:1] == ["&"] else w)
    return (bool(words) and all(w[0] == str(venv)
                                and w[1].startswith(str(here / "photo_"))
                                for w in words)), lines


@case
def a_quoted_windows_hint_gets_the_call_operator():
    """GUARD (F03). On Windows a line that starts with a quoted interpreter
    gets `& `; `py` is a bare word and needs none."""
    import photo_platform
    venv = photo_platform.run_line(r"C:\p\.venv\Scripts\python.exe",
                                   r"C:\p q\scripts\photo_see.py", "nt")
    py = photo_platform.run_line("py", r"C:\p q\scripts\photo_run.py", "nt")
    return (venv.startswith('& "C:') and py.startswith('py "C:')), (venv, py)


def pack_init_bind(name):
    """-> (the object printed on the bind line, json.loads of it or the
    error, the pack's parent folder) for `photo_pack_init.py <name> juno`.
    On nt the drive is dropped and the rest put under a temp folder (joining
    `C:\\...` would discard the temp folder); elsewhere a Windows path is one
    relative file name, so it is run from a temp cwd and lands there too."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        root = (os.path.join(tmp, name.split(":", 1)[-1].lstrip("\\"))
                if os.name == "nt" else name)
        env = {**os.environ, "PYTHONUTF8": "1"}
        out = subprocess.run([sys.executable, str(SCRIPTS / "photo_pack_init.py"),
                              root, "juno"], cwd=tmp, env=env,
                             capture_output=True, encoding="utf-8").stdout
        m = re.search(r"bind it: add (\{.*\}) to collection\.json", out)
        if not m:
            return out, None, None
        try:
            parsed = json.loads(m.group(1))
        except ValueError as exc:
            return m.group(1), f"{type(exc).__name__}: {exc}", None
        made = Path(parsed["memory_root"], "juno", "photo-profile.json").is_file()
        return m.group(1), parsed, made


@case
def pack_init_bind_line_is_json_for_a_windows_path():
    """REPRODUCTION (W-2). ⛔ FAILS on 7c8f86d: the bind line printed
    memory_root with "%s", so `C:\\dev\\_gate4` came out with single
    backslashes and the line pasted into collection.json did not parse
    (`\\d`, `\\_` are bad JSON escapes)."""
    name = "C:\\dev\\_gate4"
    text, parsed, made = pack_init_bind(name)
    return (isinstance(parsed, dict) and parsed["owner"] == "juno"
            and parsed["memory_root"].endswith(name.split(":", 1)[1])
            and made is True), (text, parsed)


@case
def pack_init_bind_line_keeps_a_cjk_path_readable():
    """GUARD (W-2). A CJK memory_root parses back to the same path and is
    printed as itself, not as \\u escapes."""
    name = "\u7167\u7247\u8a18\u61b6"
    text, parsed, made = pack_init_bind(name)
    return (isinstance(parsed, dict) and name in text
            and Path(parsed["memory_root"]).name == name
            and made is True), (text, parsed)



class _Out:
    def __init__(self, stdout):
        self.stdout = stdout


@case
def g84_the_region_setting_is_read_per_os_and_the_seam_wins():
    """⭐ NEW (OA-24 c, G84; fails on its parent only because the reader is
    missing). The computer's region setting, per OS, from faked OS answers:
    macOS `AppleLocale`, Windows' RegionInfo, `$LANG` elsewhere; a reply
    that is no two-letter code is None. PHOTO_TEST_REGION replaces the OS
    read ("" = none), so no page depends on the machine it runs on."""
    import os
    import photo_platform as pp
    if not hasattr(pp, "os_region"):
        return False, "photo_platform has no os_region"
    saved = {k: os.environ.get(k) for k in (pp.REGION_ENV, "LANG")}
    try:
        os.environ.pop(pp.REGION_ENV, None)
        os.environ["LANG"] = "en_NZ.UTF-8"
        got = {"darwin": pp.os_region("darwin", run=lambda *a, **k: _Out("en_JP\n")),
               "darwin-odd": pp.os_region("darwin", run=lambda *a, **k: _Out("en\n")),
               "nt": pp.os_region("nt", run=lambda *a, **k: _Out("DE\r\n")),
               "posix": pp.os_region("posix")}
        os.environ[pp.REGION_ENV] = "kr"
        got["seam"] = pp.os_region("darwin", run=lambda *a, **k: _Out("en_JP\n"))
        os.environ[pp.REGION_ENV] = ""
        got["seam-blank"] = pp.os_region("darwin", run=lambda *a, **k: _Out("en_JP\n"))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    want = {"darwin": "JP", "darwin-odd": None, "nt": "DE", "posix": "NZ",
            "seam": "KR", "seam-blank": None}
    return got == want, f"got={got}"


@case
def g98_the_region_setting_is_read_from_the_os_once_per_process():
    """⭐ REPRODUCTION (G98 c, Lead ruling). ⛔ FAILS on f47558f: every draft
    of the fix plan started the OS read again (PowerShell on Windows). The
    OS read is made once per process; PHOTO_TEST_REGION is still read first
    on every call, so a test that changes it still sees the change."""
    import os
    import subprocess
    import photo_platform as pp
    calls = []
    real = subprocess.run
    saved = os.environ.get(pp.REGION_ENV)
    cache = getattr(pp, "_OS_REGION", None)
    before = dict(cache) if isinstance(cache, dict) else None

    def fake(*a, **k):
        calls.append(a)
        return _Out("en_JP\n")
    try:
        subprocess.run = fake
        if isinstance(cache, dict):
            cache.clear()
        os.environ.pop(pp.REGION_ENV, None)
        first = [pp.os_region("darwin") for _ in range(3)]
        os.environ[pp.REGION_ENV] = "kr"
        seam = pp.os_region("darwin")
        os.environ.pop(pp.REGION_ENV, None)
        after = pp.os_region("darwin")
    finally:
        subprocess.run = real
        if saved is None:
            os.environ.pop(pp.REGION_ENV, None)
        else:
            os.environ[pp.REGION_ENV] = saved
        if isinstance(cache, dict):
            cache.clear()
            cache.update(before)
    return (first == ["JP"] * 3 and len(calls) == 1 and seam == "KR"
            and after == "JP"), f"first={first} calls={len(calls)} seam={seam} after={after}"


@case
def g84_the_suggestion_is_home_01s_country_then_the_region():
    """⭐ NEW (OA-24 c, G84). The suggested country: home-01's outline first
    (Tokyo Station -> JP, a public point), else the region setting, else
    nothing. Only ever a suggestion: no typing or naming stage calls it."""
    import os
    import photo_platform as pp
    if not hasattr(pp, "suggested_country"):
        return False, "photo_platform has no suggested_country"
    saved = os.environ.get(pp.REGION_ENV)
    try:
        os.environ[pp.REGION_ENV] = "NZ"
        got = [pp.suggested_country((35.6812, 139.7671)), pp.suggested_country(None),
               pp.suggested_country((0.0, -140.0))]
        os.environ[pp.REGION_ENV] = ""
        got.append(pp.suggested_country(None))
    finally:
        if saved is None:
            os.environ.pop(pp.REGION_ENV, None)
        else:
            os.environ[pp.REGION_ENV] = saved
    want = [("JP", "home"), ("NZ", "region"), ("NZ", "region"), (None, None)]
    stages = sorted(p.name for p in (ROOT / "scripts").glob("*.py")
                    if p.name not in ("photo_platform.py", "photo_onboard_page.py",
                                      "photo_index.py", "photo_fixplan_page.py")
                    and "suggested_country(" in p.read_text(encoding="utf-8"))
    return got == want and stages == [], f"got={got} other callers={stages}"


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
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} platform cases passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
