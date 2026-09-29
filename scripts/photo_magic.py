#!/usr/bin/env python3
"""The file's own first bytes -> the FileType exiftool should have reported.

⛔ ONE content sniffer for the whole engine (L17). exiftool misreports some
HEIC-named QuickTime movies as FileType HEIC, so every stage that asks "is this
a still or a video?" has to be able to overrule it. This used to shell out to
Unix `file --mime-type`, which Windows PowerShell and cmd do not have: the
check returned nothing there and said nothing, so an owner lost the correction
depending on which shell they opened. Reading the bytes in Python works on
every system and needs no tool.

Stdlib only — `photo_plan` imports it and must stay stdlib-only.

`sniff()` answers only for the formats it can place with certainty and returns
None for everything else, including a file it cannot open. None means "no
opinion": a caller never overrides a FileType on it.
"""
import os
import sys

HEAD_BYTES = 64

# ⛔ TEST HOOK, set only by tests/golden_replay.py: a replay reads the frozen
# fixture, never the live drive the fixture's paths may still point at (on the
# owner's own machine they resolve). Never documented for owners.
TEST_HOOK_ENV = "PHOTO_TEST_HOOK_NO_CONTENT_SNIFF"
_warned = []


def _hooked_off():
    if os.environ.get(TEST_HOOK_ENV) != "1":
        return False
    if not _warned:
        _warned.append(True)
        print(f"⚠️ {TEST_HOOK_ENV}=1: file content is NOT checked (L17) — a "
              "replay setting, never a real run", file=sys.stderr)
    return True

# ISO base media (`ftyp` box) major/compatible brands. A HEIC-named Live Photo
# movie carries `qt  ` — that is the whole of L17.
HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1",
               b"msf1"}
BRAND_TO_FILETYPE = {
    b"qt  ": "MOV",
    b"M4V ": "M4V", b"M4VH": "M4V", b"M4VP": "M4V",
    b"isom": "MP4", b"iso2": "MP4", b"iso4": "MP4", b"iso5": "MP4",
    b"iso6": "MP4", b"mp41": "MP4", b"mp42": "MP4", b"avc1": "MP4",
    b"dash": "MP4", b"MSNV": "MP4",
    b"3gp4": "3GP", b"3gp5": "3GP", b"3gp6": "3GP", b"3gp7": "3GP",
    b"3ge6": "3GP", b"3ge7": "3GP", b"3gg6": "3GP", b"3g2a": "3GP",
}
# A QuickTime file written before `ftyp` existed opens straight on an atom.
QT_ATOMS = {b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}


def _ftyp(head):
    major = head[8:12]
    if major in HEIF_BRANDS:
        return "HEIC"
    if major in BRAND_TO_FILETYPE:
        return BRAND_TO_FILETYPE[major]
    size = int.from_bytes(head[0:4], "big")
    compatible = head[16:min(size, len(head))]
    brands = {compatible[i:i + 4] for i in range(0, len(compatible) - 3, 4)}
    if brands & HEIF_BRANDS:
        return "HEIC"
    return None


def sniff_bytes(head):
    """-> FileType from a file's first bytes, or None."""
    if head[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "AVI"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return _ftyp(head)
    if len(head) >= 8 and head[4:8] in QT_ATOMS:
        return "MOV"
    return None


def sniff(path):
    """-> FileType from the file's own bytes, or None when unknown/unreadable."""
    if _hooked_off():
        return None
    try:
        with open(os.fspath(path), "rb") as fh:
            return sniff_bytes(fh.read(HEAD_BYTES))
    except OSError:
        return None


def filetypes(paths):
    """-> {path: FileType} for the paths `sniff()` can place; absent = no opinion."""
    out = {}
    for path in paths:
        filetype = sniff(path)
        if filetype:
            out[path] = filetype
    return out
