#!/usr/bin/env python3
"""Card 4 (B1) — the one preview converter, its causes and the honest exit.

`photo_embed.convert_to_thumbnail` is the only converter: every stage that
needs a viewable preview calls it, it picks by the manifest FileType, and it
returns (path, None) or (None, cause). A stage whose previews failed exits
non-zero and names each cause with its count.

Cases that need a tool this machine lacks (ffmpeg, sips, pillow-heif) SKIP
visibly; a green tick for a path that never ran would be a lie.
"""

import contextlib
import csv
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import photo_embed  # noqa: E402


class Skipped(Exception):
    pass


@contextlib.contextmanager
def backend(name):
    before = os.environ.get(photo_embed.BACKEND_ENV)
    os.environ[photo_embed.BACKEND_ENV] = name
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(photo_embed.BACKEND_ENV, None)
        else:
            os.environ[photo_embed.BACKEND_ENV] = before


@contextlib.contextmanager
def patched(obj, name, value):
    before = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, before)


def jpeg(path, size=(64, 48), color=(20, 140, 90), fmt="JPEG"):
    from PIL import Image
    Image.new("RGB", size, color).save(path, fmt)
    return path


def magic(path):
    head = Path(path).read_bytes()[:8]
    return ("jpeg" if head.startswith(b"\xff\xd8\xff")
            else "png" if head.startswith(b"\x89PNG\r\n\x1a\n") else None)


def case_default_backend_is_pillow(tmp):
    """Owner ruling Q12 (20260923): Pillow + ffmpeg on every machine, the Mac too."""
    with backend(""):
        os.environ.pop(photo_embed.BACKEND_ENV)
        assert photo_embed.preview_backend() == "pillow", photo_embed.preview_backend()


def case_unknown_backend_is_refused(tmp):
    with backend("gimp"):
        try:
            photo_embed.preview_backend()
        except SystemExit as e:
            assert "gimp" in str(e), e
        else:
            raise AssertionError("an unknown backend name was accepted")


def case_still_is_a_real_jpeg_named_jpg(tmp):
    """The output contract: photo_see names samples by `.jpg`, and
    photo_evidence checks the bytes are JPEG. A PNG source must come out as
    JPEG bytes, and the long edge is 1280 (upscaled, as sips does)."""
    from PIL import Image
    src = jpeg(tmp / "in.png", (400, 300), fmt="PNG")
    with backend("pillow"):
        out, cause = photo_embed.convert_to_thumbnail(src, tmp, "s", "image", "PNG")
    assert cause is None and out == tmp / "s.jpg", (out, cause)
    assert magic(out) == "jpeg", magic(out)
    assert Image.open(out).size == (1280, 960), Image.open(out).size


def case_dispatch_is_by_filetype_not_suffix(tmp):
    """L17: a JPEG named `.mp4` whose FileType says JPEG is a still. The old
    sample/see converter picked by suffix and sent it to qlmanage."""
    src = jpeg(tmp / "clip.mp4")
    with backend("pillow"):
        out, cause = photo_embed.convert_to_thumbnail(
            src, tmp, "d", photo_embed.kind_of("JPEG"), "JPEG")
    assert cause is None and out.suffix == ".jpg" and magic(out) == "jpeg", (out, cause)


def case_orientation_is_baked(tmp):
    from PIL import Image
    src = tmp / "rot.jpg"
    im = Image.new("RGB", (400, 200), (10, 120, 200))
    exif = im.getexif()
    exif[274] = 6
    im.save(src, exif=exif)
    with backend("pillow"):
        out, cause = photo_embed.convert_to_thumbnail(src, tmp, "o", "image", "JPEG")
    got = Image.open(out)
    assert got.size == (640, 1280), got.size
    assert got.getexif().get(274) in (None, 1), "orientation tag survived"


def case_each_failure_names_its_cause(tmp):
    """B1: both old converters ended `except: pass; return None`, so nothing
    downstream could say WHY. Each failure now carries a stable cause."""
    bad = tmp / "bad.jpg"
    bad.write_text("not an image")
    with backend("pillow"):
        got = photo_embed.convert_to_thumbnail(bad, tmp, "b", "image", "JPEG")
        assert got == (None, photo_embed.CAUSE_DECODE), got
        got = photo_embed.convert_to_thumbnail(tmp / "gone.jpg", tmp, "g", "image", "JPEG")
        assert got == (None, photo_embed.CAUSE_MISSING), got
        got = photo_embed.convert_to_thumbnail(bad, tmp, "u", None, "PDF")
        assert got == (None, photo_embed.CAUSE_UNSUPPORTED), got


def case_missing_ffmpeg_is_named(tmp):
    """Owner ruling: the failure message must name which tool is missing."""
    clip = tmp / "clip.mp4"
    clip.write_bytes(b"\x00" * 64)
    with backend("pillow"), patched(photo_embed, "ffmpeg_exe", lambda: (None, None)):
        got = photo_embed.convert_to_thumbnail(clip, tmp, "v", "video", "MP4")
    assert got == (None, photo_embed.CAUSE_NO_FFMPEG), got
    assert "ffmpeg" in got[1]


def case_missing_heif_decoder_is_named(tmp):
    """A HEIC Pillow cannot open for want of pillow-heif names that package;
    the same bytes typed JPEG are an ordinary decode failure."""
    heic = tmp / "IMG_1.HEIC"
    heic.write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64)
    with backend("pillow"), patched(photo_embed, "heif_ready", lambda: False):
        got = photo_embed.convert_to_thumbnail(heic, tmp, "h", "image", "HEIC")
        assert got == (None, photo_embed.CAUSE_NO_HEIF), got
        assert "pillow-heif" in got[1]
        got = photo_embed.convert_to_thumbnail(heic, tmp, "j", "image", "JPEG")
        assert got == (None, photo_embed.CAUSE_DECODE), got


def case_real_heic_through_pillow(tmp):
    try:
        import pillow_heif
    except ImportError:
        raise Skipped("pillow-heif not installed in this interpreter")
    from PIL import Image
    pillow_heif.register_heif_opener()
    src = tmp / "IMG_2.HEIC"
    Image.new("RGB", (320, 240), (200, 60, 60)).save(src, "HEIF")
    with backend("pillow"):
        out, cause = photo_embed.convert_to_thumbnail(src, tmp, "r", "image", "HEIC")
    assert cause is None and magic(out) == "jpeg", (out, cause)


def case_video_frame_is_a_real_png_named_png(tmp):
    exe, route = photo_embed.ffmpeg_exe()
    if exe is None:
        raise Skipped("no ffmpeg on PATH and no imageio-ffmpeg")
    clip = tmp / "clip.mp4"
    subprocess.run([exe, "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x240:rate=5", "-t", "1", "-pix_fmt", "yuv420p",
                    str(clip)], check=True, capture_output=True)
    with backend("pillow"):
        out, cause = photo_embed.convert_to_thumbnail(clip, tmp, "f", "video", "MP4")
    assert cause is None and out == tmp / "f.png" and magic(out) == "png", (out, cause, route)


def case_sips_fallback_still_works(tmp):
    """The sips fallback (Q12 option 1) must stay tested, not only kept."""
    if shutil.which("sips") is None:
        raise Skipped("no sips on this machine")
    src = jpeg(tmp / "in.jpg", (400, 300))
    with backend("sips"):
        out, cause = photo_embed.convert_to_thumbnail(src, tmp, "k", "image", "JPEG")
    assert cause is None and out == tmp / "k.jpg" and magic(out) == "jpeg", (out, cause)


def case_sips_missing_is_named(tmp):
    src = jpeg(tmp / "in.jpg")
    # Not the JPEG: since Card 6 the converter reads a file's own bytes and
    # would (rightly) treat a JPEG handed over as MOV as a still.
    clip = tmp / "in.mov"
    clip.write_bytes(b"\x00" * 64)
    real_which = shutil.which
    with backend("sips"), patched(photo_embed.shutil, "which",
                                  lambda n: None if n in ("sips", "qlmanage")
                                  else real_which(n)):
        got = photo_embed.convert_to_thumbnail(src, tmp, "n", "image", "JPEG")
        assert got == (None, photo_embed.CAUSE_NO_SIPS), got
        got = photo_embed.convert_to_thumbnail(clip, tmp, "q", "video", "MOV")
        assert got == (None, photo_embed.CAUSE_NO_QLMANAGE), got


def case_embed_exits_3_and_counts_each_cause(tmp):
    """B1 / F06: `photo_embed.py` exited 0 with 368/368 previews failed and
    no cause named. Now: exit 3, one stderr line per cause with its count,
    and the per-row cause in embeddings.csv."""
    wd = tmp / "wd"
    wd.mkdir()
    good = jpeg(wd / "a.jpg")
    bad = wd / "b.jpg"
    bad.write_text("not an image")
    clip = wd / "c.mp4"
    clip.write_bytes(b"\x00" * 64)
    with open(wd / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["SourceFile", "FileType"])
        w.writeheader()
        for p, t in ((good, "JPEG"), (bad, "JPEG"), (clip, "MP4")):
            w.writerow({"SourceFile": str(p), "FileType": t})
    env = {**os.environ, photo_embed.BACKEND_ENV: "pillow",
           "PATH": "/usr/bin:/bin"}
    # PATH holds no system ffmpeg; whether the imageio-ffmpeg route exists
    # depends on the interpreter, so the video row's cause is read either way.
    r = subprocess.run([sys.executable, str(HERE.parent / "scripts" / "photo_embed.py"),
                        str(wd)], capture_output=True, text=True, env=env)
    assert r.returncode == photo_embed.EXIT_PREVIEWS_FAILED, (r.returncode, r.stderr[-800:])
    assert photo_embed.CAUSE_DECODE in r.stderr, r.stderr[-800:]
    rows = {Path(x["SourceFile"]).name: x
            for x in csv.DictReader(open(wd / "embed" / "embeddings.csv"))}
    assert rows["a.jpg"]["status"] == "embedded", rows["a.jpg"]
    assert rows["b.jpg"]["error"] == photo_embed.CAUSE_DECODE, rows["b.jpg"]
    video_ok = photo_embed.ffmpeg_exe()[0] is not None
    if video_ok:
        assert rows["c.mp4"]["error"] == photo_embed.CAUSE_NO_FRAME, rows["c.mp4"]
    else:
        assert rows["c.mp4"]["error"] == photo_embed.CAUSE_NO_FFMPEG, rows["c.mp4"]
        assert "no_ffmpeg" in r.stderr


def case_exit_code_is_zero_when_nothing_failed(tmp):
    assert photo_embed.exit_code({"failed": 0}) == 0
    assert photo_embed.exit_code(None) == 0
    assert photo_embed.exit_code({"failed": 2, "failed_by_cause": {"x": 2}}) == 3


def case_see_sample_dispatches_on_filetype(tmp):
    """photo_see.make_samples picked by suffix via photo_sample.make_viewable.
    It now carries the manifest FileType on each selected entry."""
    import photo_see
    src = jpeg(tmp / "IMG_9.mp4")
    report = {"selected": [{"path": str(src), "time": "2024-01-02 03:04",
                            "filetype": "JPEG"}]}
    with backend("pillow"):
        photo_see.make_samples(report, tmp / "out")
    entry = report["selected"][0]
    assert entry["sample"] and entry["sample"].endswith(".jpg"), report
    assert report["sample_failures"] == [], report
    assert report["sample_failures_by_cause"] == {}, report


def case_one_converter_only(tmp):
    """Card 4 ends with ONE converter (A24's rule for predicates)."""
    import photo_sample
    assert not hasattr(photo_sample, "make_viewable"), \
        "a second, suffix-dispatched converter is back"


def tiny_manifest(wd, names):
    rows = []
    for n in names:
        rows.append({"SourceFile": str(jpeg(wd / n)), "FileType": "JPEG"})
    return rows


def case_switch_decides_converter_and_stamp_together(tmp):
    """Lead condition 1: the switch is read in ONE place, which decides both
    the backend that makes the pixels and the one stamped into the index. A
    run that built with one and stamped the other is the silent mix."""
    import json
    for name, private in (("pillow", "_pillow_still"), ("sips", "_sips_still")):
        if name == "sips" and shutil.which("sips") is None:
            continue
        used = []
        real = getattr(photo_embed, private)

        def spy(*a, _real=real, _name=name, **k):
            used.append(_name)
            return _real(*a, **k)

        wd = tmp / name
        wd.mkdir()
        with backend(name), patched(photo_embed, private, spy):
            photo_embed.run(tiny_manifest(wd, ["a.jpg"]), wd / "embed", False, None,
                            wd / "embed" / "embed-errors.log")
        stamp = json.loads((wd / "embed" / "embeddings-meta.json").read_text())
        assert used == [name], (name, used)
        assert stamp[photo_embed.PREVIEW_KEY] == name, (name, stamp)


def case_legacy_index_is_refused_with_advice(tmp):
    """An index from before Card 4 has no backend key, and its vectors came
    from sips. A Pillow run adding to it must stop and say how to go on; the
    sips switch must let it resume."""
    import json
    if shutil.which("sips") is None:
        raise Skipped("no sips: a legacy index cannot be built here")
    wd = tmp / "wd"
    wd.mkdir()
    rows = tiny_manifest(wd, ["a.jpg"])
    with backend("sips"):
        photo_embed.run(rows, wd / "embed", False, None, wd / "embed" / "e.log")
    meta_path = wd / "embed" / "embeddings-meta.json"
    meta = json.loads(meta_path.read_text())
    meta.pop(photo_embed.PREVIEW_KEY)
    meta_path.write_text(json.dumps(meta))
    rows += tiny_manifest(wd, ["b.jpg"])
    with backend("pillow"):
        try:
            photo_embed.run(rows, wd / "embed", False, None, wd / "embed" / "e.log")
        except SystemExit as e:
            text = str(e)
        else:
            raise AssertionError("a Pillow run extended a sips index")
    assert "--force" in text and f"{photo_embed.BACKEND_ENV}=sips" in text, text
    with backend("sips"):
        summary = photo_embed.run(rows, wd / "embed", False, None, wd / "embed" / "e.log")
    assert summary["newly_embedded"] == 1, summary


def case_space_view_reads_missing_backend_as_sips(tmp):
    got = photo_embed.space_view({"model_id": "m"}, ("model_id", photo_embed.PREVIEW_KEY))
    assert got == {"model_id": "m", photo_embed.PREVIEW_KEY: "sips"}, got
    assert photo_embed.space_view(None, ("model_id",)) is None


def case_pack_refusal_speaks_to_the_owner(tmp):
    """Lead condition 2: a pack learned from sips previews, met by a Pillow
    run, is refused in owner language: no pack rebuild exists yet, and the
    switch is how to keep using the pack. Both pack stamps are guarded."""
    import photo_identity
    import photo_subjects
    from photo_recurrence import META_IDENTITY
    clip_old = {k: "x" for k in META_IDENTITY if k != photo_embed.PREVIEW_KEY}
    reg = photo_subjects.Registry(directory=tmp / "photo-subjects",
                                  data={"version": 1, "subjects": [],
                                        "embedding_identity": clip_old})
    try:
        reg.assert_identity({**clip_old, photo_embed.PREVIEW_KEY: "pillow"})
    except ValueError as e:
        text = str(e)
    else:
        raise AssertionError("a sips-learned pack met a Pillow index silently")
    assert "no way yet" in text and f"{photo_embed.BACKEND_ENV}=sips" in text, text
    reg.assert_identity({**clip_old, photo_embed.PREVIEW_KEY: "sips"})
    reg.assert_identity(clip_old)

    space_old = {k: "y" for k in photo_identity.SPACE_KEYS if k != photo_embed.PREVIEW_KEY}
    reg.data["identity_embedding"] = space_old
    try:
        reg.assert_identity_space({**space_old, photo_embed.PREVIEW_KEY: "pillow"})
    except ValueError as e:
        assert "no way yet" in str(e), e
    else:
        raise AssertionError("the identity stamp let a backend mix through")
    reg.assert_identity_space(space_old)


def case_prep_stops_before_the_scan_when_no_still_backend_works(tmp):
    """M8 (UAT02-A F07): `prep` warned that sips was missing and carried on,
    so the owner was led past the last safe stop into a vision pass where
    every file failed. It must stop BEFORE the scan, naming the cause."""
    import argparse
    import photo_run
    src = tmp / "src"
    src.mkdir()
    calls = []

    def record(script, *a, **k):
        calls.append(script)
        return subprocess.CompletedProcess([script], 0)

    args = argparse.Namespace(source=str(src), workdir_root=str(tmp / "wf"),
                              no_recursive=False, no_cluster=True, profile=None)
    path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(tmp / "nothing-here")       # no sips for the probe
    try:
        with backend("sips"), patched(photo_run, "run", record), \
                patched(photo_run, "preflight", lambda: None):
            try:
                photo_run.cmd_prep(args)
            except SystemExit as e:
                text = str(e)
            else:
                text = None
    finally:
        os.environ["PATH"] = path
    assert calls == [], f"prep went on to {calls} with no working preview backend"
    assert text and "no_sips" in text, text


def case_prep_passes_when_a_still_backend_works(tmp):
    import photo_run
    with backend("pillow"):
        photo_run.preview_check()


def case_video_frame_is_the_middle_not_a_black_fade_in(tmp):
    """The frame is taken from the MIDDLE of the clip. `-frames:v 1` alone
    took the first frame, which on a clip that fades in is black: it embeds
    fine, exits 0, and is garbage — the silent class B1 is about."""
    import numpy as np
    from PIL import Image
    exe, _route = photo_embed.ffmpeg_exe()
    if exe is None:
        raise Skipped("no ffmpeg on PATH and no imageio-ffmpeg")
    clip = tmp / "fade.mp4"
    subprocess.run([exe, "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x240:rate=10:duration=2", "-vf", "fade=in:0:10",
                    "-pix_fmt", "yuv420p", str(clip)], check=True, capture_output=True)
    with backend("pillow"):
        out, cause = photo_embed.convert_to_thumbnail(clip, tmp, "m", "video", "MP4")
    assert cause is None, cause
    lum = float(np.asarray(Image.open(out).convert("L")).mean())
    assert lum > 40, f"a black frame came back (mean luminance {lum:.1f})"


CASES = [
    ("the default backend is Pillow + ffmpeg (Q12)", case_default_backend_is_pillow),
    ("an unknown backend name is refused", case_unknown_backend_is_refused),
    ("a still is real JPEG bytes named .jpg, long edge 1280", case_still_is_a_real_jpeg_named_jpg),
    ("dispatch follows FileType, never the suffix (L17)", case_dispatch_is_by_filetype_not_suffix),
    ("orientation is baked into the pixels", case_orientation_is_baked),
    ("each failure names its cause (B1)", case_each_failure_names_its_cause),
    ("a missing ffmpeg is named", case_missing_ffmpeg_is_named),
    ("a missing HEIF decoder is named", case_missing_heif_decoder_is_named),
    ("a real HEIC converts through Pillow", case_real_heic_through_pillow),
    ("a video frame is real PNG bytes named .png", case_video_frame_is_a_real_png_named_png),
    ("a video frame is the middle, not a black fade-in", case_video_frame_is_the_middle_not_a_black_fade_in),
    ("the sips fallback still works", case_sips_fallback_still_works),
    ("a missing sips/qlmanage is named", case_sips_missing_is_named),
    ("embed exits 3 and names each cause (B1/F06)", case_embed_exits_3_and_counts_each_cause),
    ("exit code is 0 only when nothing failed", case_exit_code_is_zero_when_nothing_failed),
    ("see samples dispatch on FileType", case_see_sample_dispatches_on_filetype),
    ("there is one converter only", case_one_converter_only),
    ("the switch decides converter AND stamp together", case_switch_decides_converter_and_stamp_together),
    ("a pre-Card-4 index is refused with advice; the sips switch resumes it", case_legacy_index_is_refused_with_advice),
    ("a missing backend key reads as sips", case_space_view_reads_missing_backend_as_sips),
    ("a pack refusal speaks to the owner (no rebuild yet; the switch)", case_pack_refusal_speaks_to_the_owner),
    ("M8: prep stops before the scan when no still backend works", case_prep_stops_before_the_scan_when_no_still_backend_works),
    ("M8: prep passes when a still backend works", case_prep_passes_when_a_still_backend_works),
]


def main():
    passed = skipped = 0
    for name, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="preview_case_"))
        try:
            fn(tmp)
            print(f"  ok    {name}")
            passed += 1
        except Skipped as s:
            print(f"  SKIP  {name}: {s}")
            skipped += 1
        except Exception as e:                            # noqa: BLE001
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    total = len(CASES)
    print(f"\n{passed}/{total} preview cases passed"
          + (f" ({skipped} skipped)" if skipped else ""))
    sys.exit(0 if passed + skipped == total else 1)


if __name__ == "__main__":
    main()
