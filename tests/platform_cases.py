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
