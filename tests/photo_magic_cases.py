#!/usr/bin/env python3
"""Card 6 (L17 everywhere) — the one content sniffer, with no Unix `file`.

exiftool calls some HEIC-named QuickTime movies HEIC. The engine used to ask
Unix `file` for the truth, only in embed and the copy backstop; Windows
PowerShell/cmd have no `file`, and the sheet, see, sample and plan never asked.
Each case says whether it REPRODUCES a defect (fails on c5b6f99) or only
GUARDS behaviour that already held.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import photo_embed  # noqa: E402
import photo_magic  # noqa: E402
import photo_plan  # noqa: E402
import photo_profile  # noqa: E402
import photo_rename_mismatches  # noqa: E402


def ftyp(major, compatible=b""):
    body = major + b"\x00\x00\x00\x00" + compatible
    return (8 + len(body)).to_bytes(4, "big") + b"ftyp" + body + b"\x00" * 16


QT_MOVIE = ftyp(b"qt  ", b"qt  ")
REAL_HEIC = ftyp(b"heic", b"mif1heic")


def no_file_tool():
    """Make `file` unavailable the way a Windows shell does, for any caller."""
    real_run, real_which = subprocess.run, shutil.which

    def run(cmd, *a, **kw):
        if cmd and cmd[0] == "file":
            raise FileNotFoundError(2, "No such file or directory: 'file'")
        return real_run(cmd, *a, **kw)

    def which(name, *a, **kw):
        return None if name == "file" else real_which(name, *a, **kw)

    subprocess.run, shutil.which = run, which
    return lambda: (setattr(subprocess, "run", real_run),
                    setattr(shutil, "which", real_which))


def case_sniff_places_each_format(tmp):
    """GUARD — the header table."""
    cases = {
        b"\xff\xd8\xff\xe0" + b"\x00" * 20: "JPEG",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 20: "PNG",
        b"GIF89a" + b"\x00" * 20: "GIF",
        b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8: "WEBP",
        REAL_HEIC: "HEIC",
        ftyp(b"mif1", b"mif1heic"): "HEIC",
        QT_MOVIE: "MOV",
        ftyp(b"mp42", b"isommp42"): "MP4",
        ftyp(b"3gp4", b"isom3gp4"): "3GP",
        b"\x00\x00\x00\x08wide" + b"\x00" * 20: "MOV",
        b"plain text, no format at all": None,
        b"": None,
    }
    for head, want in cases.items():
        got = photo_magic.sniff_bytes(head)
        assert got == want, (head[:12], got, want)
    assert photo_magic.sniff(tmp / "absent.heic") is None


def case_embed_magic_needs_no_file_tool(tmp):
    """REPRODUCES 6b (W11 F1) — with no `file`, c5b6f99 returned {} silently."""
    movie = tmp / "IMG_0001.HEIC"
    movie.write_bytes(QT_MOVIE)
    restore = no_file_tool()
    try:
        got = photo_embed.magic_filetypes([str(movie)])
    finally:
        restore()
    assert got == {str(movie): "MOV"}, got


def case_every_preview_caller_gets_the_correction(tmp):
    """REPRODUCES F-dd / F-ii — a HEIC-typed movie handed to the one converter
    (as the sheet, see and sample do) must be treated as a video."""
    movie = tmp / "IMG_0002.HEIC"
    movie.write_bytes(QT_MOVIE)
    called = []
    real_still, real_frame = photo_embed._pillow_still, photo_embed._ffmpeg_frame
    photo_embed._pillow_still = lambda *a: called.append("still") or (None, "x")
    photo_embed._ffmpeg_frame = lambda *a: called.append("video") or (None, "x")
    try:
        photo_embed.convert_to_thumbnail(movie, tmp, "s", "image", "HEIC")
    finally:
        photo_embed._pillow_still, photo_embed._ffmpeg_frame = real_still, real_frame
    if photo_embed.preview_backend() == "pillow":
        assert called == ["video"], called


def case_a_real_still_is_not_touched(tmp):
    """GUARD — content that agrees with the FileType, or that the sniffer
    cannot place, never changes the dispatch."""
    for name, data in (("a.HEIC", REAL_HEIC), ("b.HEIC", b"garbage bytes")):
        path = tmp / name
        path.write_bytes(data)
        called = []
        real_still = photo_embed._pillow_still
        photo_embed._pillow_still = lambda *a: called.append("still") or (None, "x")
        try:
            photo_embed.convert_to_thumbnail(path, tmp, "s", "image", "HEIC")
        finally:
            photo_embed._pillow_still = real_still
        if photo_embed.preview_backend() == "pillow":
            assert called == ["still"], (name, called)


def case_plan_names_a_heic_named_movie_mov(tmp):
    """REPRODUCES F-ll — the plan copied the movie under .HEIC."""
    msg = photo_profile.messages(None)
    movie = tmp / "IMG_0003.HEIC"
    movie.write_bytes(QT_MOVIE)
    row = {"FileName": movie.name, "FileType": "HEIC", "SourceFile": str(movie)}
    name, note, known = photo_plan.dest_name(row, msg)
    assert (name, known) == ("IMG_0003.MOV", True), (name, known)
    assert "MOV" in note, note


def case_plan_leaves_a_real_heic_and_an_absent_file(tmp):
    """GUARD — a true HEIC and a row whose file is not on disk (every golden
    fixture) keep their name, so a replay is unchanged."""
    msg = photo_profile.messages(None)
    still = tmp / "IMG_0004.HEIC"
    still.write_bytes(REAL_HEIC)
    for row in ({"FileName": still.name, "FileType": "HEIC", "SourceFile": str(still)},
                {"FileName": "IMG_0005.HEIC", "FileType": "HEIC",
                 "SourceFile": str(tmp / "gone" / "IMG_0005.HEIC")}):
        name, note, _ = photo_plan.dest_name(row, msg)
        assert (name, note) == (row["FileName"], ""), (name, note)


def case_replay_hook_only_acts_when_set(tmp):
    """GUARD — golden_replay's test hook. Unset (every real run) the plan
    renames a HEIC-named movie; set, the content is not read and the name
    stays, which is what keeps a replay off the live drive."""
    import os
    msg = photo_profile.messages(None)
    movie = tmp / "IMG_0008.HEIC"
    movie.write_bytes(QT_MOVIE)
    row = {"FileName": movie.name, "FileType": "HEIC", "SourceFile": str(movie)}
    before = os.environ.pop(photo_magic.TEST_HOOK_ENV, None)
    try:
        assert photo_plan.dest_name(row, msg)[0] == "IMG_0008.MOV"
        os.environ[photo_magic.TEST_HOOK_ENV] = "1"
        assert photo_plan.dest_name(row, msg)[0] == "IMG_0008.HEIC"
    finally:
        os.environ.pop(photo_magic.TEST_HOOK_ENV, None)
        if before is not None:
            os.environ[photo_magic.TEST_HOOK_ENV] = before


def case_copy_backstop_needs_no_file_tool(tmp):
    """REPRODUCES 6b for the OA-4 backstop — c5b6f99 raised FileNotFoundError."""
    (tmp / "IMG_0006.HEIC").write_bytes(QT_MOVIE)
    (tmp / "IMG_0007.HEIC").write_bytes(REAL_HEIC)
    restore = no_file_tool()
    try:
        got = photo_rename_mismatches.magic_check_heic(tmp, set())
    finally:
        restore()
    assert got == [(tmp / "IMG_0006.HEIC", "mov")], got


CASES = [
    ("the sniffer places each format (GUARD)", case_sniff_places_each_format),
    ("embed's magic check needs no `file` (REPRO 6b)", case_embed_magic_needs_no_file_tool),
    ("every preview caller gets the L17 correction (REPRO F-dd/F-ii)",
     case_every_preview_caller_gets_the_correction),
    ("a real still is not touched (GUARD)", case_a_real_still_is_not_touched),
    ("the plan names a HEIC-named movie .MOV (REPRO F-ll)",
     case_plan_names_a_heic_named_movie_mov),
    ("the plan leaves a real HEIC and an absent file (GUARD)",
     case_plan_leaves_a_real_heic_and_an_absent_file),
    ("the copy backstop needs no `file` (REPRO 6b)", case_copy_backstop_needs_no_file_tool),
    ("the replay hook acts only when set (GUARD)", case_replay_hook_only_acts_when_set),
]


def main():
    passed = 0
    for name, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="photo_magic_case_"))
        try:
            fn(tmp)
            print(f"  ok    {name}")
            passed += 1
        except Exception as e:                            # noqa: BLE001
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{passed}/{len(CASES)} photo_magic cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
