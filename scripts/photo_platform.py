#!/usr/bin/env python3
"""What differs by operating system — the ONE place the engine asks.

Stdlib only and imports no stage, the same class as `photo_magic` and
`photo_exiftool`: a stage that needs the repo `.venv` path or an install /
mount hint imports this, never another stage.

⛔ `venv_python()` is the only spelling of the repo `.venv` interpreter. A
virtualenv keeps it at `.venv/bin/python3` on macOS and Linux but at
`.venv\\Scripts\\python.exe` on Windows, and a hardcoded `bin/python3` made
every "is there a .venv?" check on Windows answer no — silently, so the run
carried on under whatever Python started it.
"""

import os
import shutil
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

REPO = Path(__file__).resolve().parent.parent

# The OS this process runs on. A name of its own so a test can fake a
# Windows host together with its Path class (patching os.name breaks pathlib).
HOST_OS = os.name

# Where each OS keeps the mounted drives, when it has such a folder at all.
VOLUMES = Path("/Volumes")


def venv_python(repo=REPO, os_name=None):
    """-> the repo `.venv` interpreter for this OS (or `os_name`, for tests).
    Never resolved: in a worktree `.venv` is a symlink, and the printed line
    must name the repo the owner is running from."""
    target = os_name or HOST_OS
    # The path for ANOTHER OS is built in that OS's own spelling; only this
    # host's path is a real Path (RS5c: a Windows host printed the Mac and
    # Linux lines as `.venv\bin\python3`).
    if target == "nt":
        parts, flavour = (".venv", "Scripts", "python.exe"), PureWindowsPath
    else:
        parts, flavour = (".venv", "bin", "python3"), PurePosixPath
    if target == HOST_OS:
        return Path(repo).joinpath(*parts)
    return flavour(str(repo)).joinpath(*parts)


def path_key(path):
    """-> `path` as one comparable string: every backslash becomes "/".

    photo_execute records `dest` through `str(Path(...))` (native separators)
    while photo_plan joins with "/", so on Windows the same folder arrived as
    two strings and every "is this the same folder?" test answered no. A key
    for comparing only, never a path to open. Applied on every OS, because a
    folder name the engine writes can never hold a backslash (photo_plan
    refuses one) and the Mac test must see the Windows shape."""
    return str(path).replace("\\", "/")


def owner_python(os_name=None):
    """-> how the owner types Python in a printed command. On Windows
    `python3` can open the Microsoft Store instead of running Python; `py` is
    the launcher every python.org and winget install puts on PATH."""
    return "py" if (os_name or os.name) == "nt" else "python3"


def _os_of(platform):
    platform = platform or sys.platform
    if platform == "darwin":
        return "mac"
    return "windows" if platform.startswith("win") else "linux"


# `install` is always a line a shell can run as it stands, or None; anything
# a person has to read (another route, a distribution caveat) is the `note`.
def python_install_hint(platform=None):
    """-> (command, note, needs admin?) for Python 3.10+ here."""
    return {"mac": ("brew install python@3.12", "or the installer from python.org",
                    False),
            "windows": ("winget install Python.Python.3.12",
                        "or the installer from python.org", False),
            "linux": ("sudo apt install python3 python3-venv",
                      "Debian/Ubuntu; other distributions use their own package "
                      "manager", True)}[_os_of(platform)]


def exiftool_install_command(platform=None):
    """-> the exiftool install COMMAND here; `exiftool_install_note()` says the
    rest. Windows: the winget package is an Inno installer with a user scope
    (/CURRENTUSER, %LocalAppData%) and a machine scope (/ALLUSERS,
    %ProgramFiles%, UAC); the bare line leaves the choice to winget, so
    `--scope user` is what makes it admin-free (manifest 13.59, read
    20260928)."""
    return {"mac": "brew install exiftool",
            "windows": "winget install --id OliverBetz.ExifTool -e --scope user",
            "linux": "sudo apt install libimage-exiftool-perl"}[_os_of(platform)]


def exiftool_needs_admin(platform=None):
    """The Linux package line needs sudo; brew and the exiftool.org installer
    do not."""
    return _os_of(platform) == "linux"


def venv_create_line(repo=REPO, platform=None):
    """-> the line that makes the repo `.venv`, in this OS's own Python."""
    py = "py -3" if _os_of(platform) == "windows" else "python3"
    return f'{py} -m venv "{Path(repo) / ".venv"}"'


def pip_line(packages, repo=REPO, platform=None, extra=""):
    """-> pip install `packages` INTO the repo `.venv`, with that `.venv`'s own
    interpreter — never a bare `pip`, which is whichever one is first on PATH."""
    os_name = "nt" if _os_of(platform) == "windows" else "posix"
    py = venv_python(repo, os_name=os_name)
    return powershell_call(f'"{py}" -m pip install {" ".join(packages)}{extra}',
                           os_name)


def powershell_call(line, os_name=None):
    """F03 — PowerShell reads a line that starts with a quoted path as a
    string, not a command; `& ` makes it run. Other shells need nothing."""
    if (os_name or HOST_OS) == "nt" and line.startswith('"'):
        return "& " + line
    return line


def quoted(word):
    """K3 — a path in a printed command, in double quotes when it holds a
    slash or a space, so a copied line still runs. Never `shlex.quote`: its
    single quotes do not quote on Windows."""
    word = str(word)
    return f'"{word}"' if any(c in word for c in "/\\ ") else word


def run_line(python, script, os_name=None):
    """F03 — `<python> <script>` for a printed next step, each quoted when it
    is a path, so a folder name with a space still runs."""
    return powershell_call(f"{quoted(python)} {quoted(script)}", os_name)


# The pyproject extra that holds every vision package. Its NAME is the one
# thing doctor knows; the packages and their version rules stay in
# pyproject.toml, so doctor cannot drift from them (RS5b, the owner ruling, option c).
ALL_EXTRA = "all"


def extras_install_line(repo=REPO, platform=None, extra=ALL_EXTRA):
    """-> install the repo's own extras into its `.venv`, editable, exactly
    as docs/INSTALL.md step 4 does."""
    return pip_line(["-e", f'"{Path(repo)}[{extra}]"'], repo, platform)


# Rough download sizes the owner is told BEFORE saying yes. Rough on purpose:
# they move with every release, and the question is "minutes or an hour".
TORCH_CPU_SIZE = "about 200 MB"
TORCH_CUDA_SIZE = "several GB"
TORCH_MAC_SIZE = "about 150 MB"
FIRST_RUN_WEIGHTS = ("the first vision run then downloads the model weights once: "
                     "CLIP about 600 MB, the animal detector about 170 MB, "
                     "DINOv2 about 330 MB")


def has_nvidia_gpu():
    return shutil.which("nvidia-smi") is not None


def torch_install_line(repo=REPO, platform=None, nvidia=None):
    """-> (the CPU-only torch line or None, torch's rough size). On Windows or
    Linux with no NVIDIA GPU the extras would pull a multi-gigabyte CUDA
    build that cannot be used, so this line runs FIRST and the extras then
    find torch already there (docs/INSTALL.md step 4). Elsewhere torch comes with the
    extras (None). No version here: the extras' own rule still applies."""
    osn = _os_of(platform)
    nvidia = has_nvidia_gpu() if nvidia is None else nvidia
    if osn == "mac":
        return None, TORCH_MAC_SIZE
    if nvidia:
        return None, TORCH_CUDA_SIZE
    return (pip_line(["torch", "torchvision"], repo, platform,
                     extra=" --index-url https://download.pytorch.org/whl/cpu"),
            TORCH_CPU_SIZE)


def exiftool_install_note(platform=None):
    """-> what the owner reads beside the command, or None. On Windows a
    user-scope install lands on the USER Path, which a terminal or agent
    session started before it does not see (measured 20260830), so doctor
    would still say MISSING until both are reopened."""
    hint = exiftool_install_hint(platform)
    if _os_of(platform) == "windows":
        return (f"or {hint}. After installing, close and reopen the terminal "
                "AND the agent session (Claude Code), then run doctor again: a "
                "session started before the install does not see exiftool")
    return None if hint == exiftool_install_command(platform) else hint


def exiftool_install_hint(platform=None):
    """-> how to install exiftool here, in docs/INSTALL.md's own words."""
    platform = platform or sys.platform
    if platform == "darwin":
        return "brew install exiftool"
    if platform.startswith("win"):
        return "the Windows installer from exiftool.org"
    return ("your package manager — Debian/Ubuntu: libimage-exiftool-perl — "
            "or exiftool.org")


def source_missing_hint(volumes=VOLUMES):
    """-> the line after "source not found". Lists `volumes` only where that
    folder exists: Windows and Linux have no `/Volumes`, and listing it there
    crashed the error message itself."""
    try:
        names = sorted(p.name for p in volumes.iterdir()
                       if not p.name.startswith("."))
    except OSError:
        return "  the drive may not be connected — check the path, then run this again."
    return f"  volume not mounted? currently mounted: {', '.join(names)}"
