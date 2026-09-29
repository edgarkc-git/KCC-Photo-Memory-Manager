#!/usr/bin/env python3
"""Shared exiftool launcher — every exiftool call in the engine goes through
here (OA-27).

On Windows exiftool.exe decodes its argv through the ANSI codepage, so a path
whose name is not representable there arrives as `?` characters, which
exiftool then reads as a wildcard: "No matching files" for a folder that is
sitting right there. The arguments have to reach exiftool as UTF-8 bytes, and
an argfile (`-@`) is the only thing that carries them — the argfile is the
mechanism, on its own.

`-charset filename=UTF8` is NOT what fixes it: measured on Win11 with
exiftool 13.59, three runs each way were byte-identical with and without it,
because that version already defaults the filename charset to UTF8. The flag
is kept because it costs nothing and pins the behaviour against a future
change of default, but it is belt, not braces.

The answer has to be decoded explicitly for the same reason: subprocess text
mode decodes with the locale encoding, which would mangle the same names on
the way back out.

An argfile costs one thing argv does not: exiftool reads a line beginning
with `#` as a COMMENT, and strips leading whitespace from every line. So a
folder honestly named `#drafts` or ` inbox` stops being an argument at all —
and exiftool given no file argument prints its entire MAN PAGE to stdout and
exits 0, with empty stderr. Measured at the shapes this engine sends:

    -csv -r     "No file specified", exit 1, empty stdout
    -json       "No file specified", exit 0, stdout that is not JSON
    -q -q -p    ~2965 lines of man page, exit 0, empty stderr

The last is the dangerous one: a caller parsing stdout gets prose, a success
exit code and no warning. Only a line that STARTS with `#` is swallowed — an
absolute path merely containing one mid-string is fine (measured) — so
`paths` is a separate argument, and each is absolutised to put a separator
first. A run in which no path survived is refused outright, because no exit
code distinguishes that state from a real answer.
"""

import os
import subprocess
import tempfile
from pathlib import Path


def _is_argument(line):
    """Does exiftool read this argfile line as an argument, or as a comment?"""
    return bool(line.strip()) and not line.lstrip().startswith("#")


def run(options, paths, **kwargs):
    """Run exiftool with `options` then `paths`, passed as a UTF-8 argfile.
    Returns the CompletedProcess with str stdout/stderr."""
    path_lines = [str(Path(p).absolute()) for p in paths if str(p).strip()]
    if paths and not any(_is_argument(p) for p in path_lines):
        raise ValueError(
            "no path survived into the exiftool argfile "
            f"({[str(p) for p in paths]}) — refusing to run, because exiftool "
            "with no file argument prints its man page to stdout and exits 0")
    lines = [str(o) for o in options] + path_lines

    fd, argfile = tempfile.mkstemp(prefix="exiftool-args-", suffix=".txt")
    try:
        # Written and closed before exiftool opens it: Windows will not let a
        # second process open a file this one still holds.
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(f"{line}\n" for line in lines))
        return subprocess.run(
            ["exiftool", "-charset", "filename=UTF8", "-@", argfile],
            capture_output=True, encoding="utf-8", errors="replace", **kwargs)
    finally:
        os.unlink(argfile)
