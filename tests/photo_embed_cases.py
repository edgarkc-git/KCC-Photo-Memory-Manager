#!/usr/bin/env python3
"""Cases for photo_embed.py (VS-1) — resume, model-identity guard, failure
handling. Synthetic images only, generated at run time with Pillow: this
suite must never hold real photos or owner-derived vectors (design doc,
docs/photo-memory-pack.md — the subject registry's exemplar store is never
in the public repo, and neither is anything that could seed one).

NOT part of the stdlib-only three-suite chain in tests/README.md — this is
the one suite that needs the ML deps, so it runs under the repo .venv:

  ./.venv/bin/python3 tests/photo_embed_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import contextlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import photo_embed  # noqa: E402

VERBOSE = False


def log(msg):
    if VERBOSE:
        print(f"  {msg}")


def make_image(path, color, fmt=None):
    """fmt is needed only for the D13-mismatch cases, where the whole point is
    that the filename suffix does not describe the content and Pillow has no
    extension to infer a format from."""
    from PIL import Image
    Image.new("RGB", (64, 64), color).save(path, fmt)


def manifest_row(path, filetype="JPEG"):
    return {"SourceFile": str(path), "FileType": filetype}


class Skipped(Exception):
    """A case that needs a tool this machine lacks. Shown, never a green tick."""


SKIPPED = []


def need_qlmanage():
    if shutil.which("qlmanage") is None:
        raise Skipped("no qlmanage on this machine (macOS only)")


def run_case(name, fn):
    try:
        fn()
        print(f"  ok    {name}")
        return True
    except Skipped as s:
        print(f"  SKIP  {name}: {s}")
        SKIPPED.append(name)
        return True
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        return False


def case_basic_embed(tmp):
    src = tmp / "src"
    src.mkdir()
    paths = []
    for i, color in enumerate([(200, 0, 0), (0, 200, 0), (0, 0, 200), (100, 100, 100)]):
        p = src / f"img_{i}.jpg"
        make_image(p, color)
        paths.append(p)
    embed_dir = tmp / "case_basic" / "embed"
    manifest = [manifest_row(p) for p in paths]

    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["newly_embedded"] == 4, summary
    assert summary["failed"] == 0, summary

    import numpy as np
    vecs = np.load(embed_dir / "embeddings.npy")
    assert vecs.shape == (4, 512), vecs.shape
    norms = np.linalg.norm(vecs, axis=1)
    assert all(abs(n - 1.0) < 1e-4 for n in norms), norms

    return embed_dir, manifest


def case_resume_noop(tmp):
    embed_dir, manifest = case_basic_embed(tmp)
    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["newly_embedded"] == 0, summary
    assert summary.get("already_embedded") == 4, summary


def case_resume_add_one(tmp):
    embed_dir, manifest = case_basic_embed(tmp)
    src = tmp / "src"
    p = src / "img_new.jpg"
    make_image(p, (50, 200, 200))
    manifest = manifest + [manifest_row(p)]
    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["newly_embedded"] == 1, summary
    assert summary["total_in_index"] == 5, summary


def case_resume_changed_file(tmp):
    embed_dir, manifest = case_basic_embed(tmp)
    p = Path(manifest[0]["SourceFile"])
    make_image(p, (9, 9, 9))               # rewrite -> new mtime
    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["newly_embedded"] == 1, summary
    assert summary["total_in_index"] == 4, summary       # replaced, not appended


def case_meta_mismatch_hard_fails(tmp):
    embed_dir, manifest = case_basic_embed(tmp)
    import json
    meta_path = embed_dir / "embeddings-meta.json"
    meta = json.loads(meta_path.read_text())
    meta["embed_dim"] = 999
    meta_path.write_text(json.dumps(meta))
    p = Path(manifest[0]["SourceFile"])
    p.touch()                              # force it into "pending" so run() reaches the check
    try:
        photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                        errors_log=embed_dir / "embed-errors.log")
        raise AssertionError("expected SystemExit on model/meta mismatch")
    except SystemExit as e:
        assert "--force" in str(e), e


def case_force_rebuilds_after_mismatch(tmp):
    embed_dir, manifest = case_basic_embed(tmp)
    import json
    meta_path = embed_dir / "embeddings-meta.json"
    meta = json.loads(meta_path.read_text())
    meta["embed_dim"] = 999
    meta_path.write_text(json.dumps(meta))
    summary = photo_embed.run(manifest, embed_dir, force=True, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["newly_embedded"] == 4, summary
    assert summary["failed"] == 0, summary


def case_failed_file_recorded_not_fatal(tmp):
    src = tmp / "src_fail"
    src.mkdir()
    good = src / "good.jpg"
    make_image(good, (10, 20, 30))
    bad = src / "bad.jpg"
    bad.write_text("not an image")
    embed_dir = tmp / "case_fail" / "embed"
    # bad BEFORE good: the failure path must still leave row i aligned with
    # vector i for every file that comes after it in the same run.
    manifest = [manifest_row(bad), manifest_row(good)]
    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["newly_embedded"] == 1, summary
    assert summary["failed"] == 1, summary

    import csv
    import numpy as np
    rows = list(csv.DictReader(open(embed_dir / "embeddings.csv", newline="")))
    vecs = np.load(embed_dir / "embeddings.npy")
    assert len(rows) == len(vecs) == 2, (len(rows), len(vecs))
    statuses = {r["SourceFile"]: r["status"] for r in rows}
    assert statuses[str(good)] == "embedded", statuses
    assert statuses[str(bad)] == "failed", statuses
    for r, v in zip(rows, vecs):                    # row i must be vector i
        if r["status"] == "embedded":
            assert abs(np.linalg.norm(v) - 1.0) < 1e-4, (r, v)
        else:
            assert np.linalg.norm(v) == 0.0, (r, v)  # failed rows are the zero placeholder
    assert (embed_dir / "embed-errors.log").exists()


def case_batch_exception_still_records_every_row(tmp):
    """A whole-batch failure (embed_batch itself raises) used to drop those
    files from the index entirely instead of recording them as failed —
    desynchronizing .npy row i from .csv row i. Regression case."""
    src = tmp / "src_batchfail"
    src.mkdir()
    paths = [src / f"i{i}.jpg" for i in range(3)]
    for i, p in enumerate(paths):
        make_image(p, (i * 10, i * 10, i * 10))
    embed_dir = tmp / "case_batchfail" / "embed"
    manifest = [manifest_row(p) for p in paths]

    original = photo_embed.embed_batch
    photo_embed.embed_batch = lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError("simulated model failure"))
    try:
        summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                                  errors_log=embed_dir / "embed-errors.log")
    finally:
        photo_embed.embed_batch = original

    assert summary["failed"] == 3, summary
    assert summary["newly_embedded"] == 0, summary
    import csv
    import numpy as np
    rows = list(csv.DictReader(open(embed_dir / "embeddings.csv", newline="")))
    vecs = np.load(embed_dir / "embeddings.npy")
    assert len(rows) == len(vecs) == 3, (len(rows), len(vecs))
    assert all(r["status"] == "failed" for r in rows), rows


def case_kind_of_dispatch():
    assert photo_embed.kind_of("HEIC") == "image"
    assert photo_embed.kind_of("JPEG") == "image"
    assert photo_embed.kind_of("MOV") == "video"
    assert photo_embed.kind_of("MP4") == "video"
    assert photo_embed.kind_of("AAE") is None
    assert photo_embed.kind_of("PDF") is None


@contextlib.contextmanager
def preview_backend(name):
    """Force one preview backend for the block, and put back what was there."""
    before = os.environ.get(photo_embed.BACKEND_ENV)
    os.environ[photo_embed.BACKEND_ENV] = name
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(photo_embed.BACKEND_ENV, None)
        else:
            os.environ[photo_embed.BACKEND_ENV] = before


def case_orientation_is_baked_into_the_pixels(tmp):
    """Tier 3 round 1, 2026-08-27: a phone stores a rotated capture as
    sensor-order pixels plus an EXIF Orientation tag, and every consumer here
    reads the pixels — CLIP, the COCO detector, the review page, the vision
    model. On the two dumps measured that evening, 78 of 220 files (35%)
    carried a non-normal tag, so a third of the input was embedded and shown
    sideways. The invariant: after make_viewable, the tag must be gone and the
    pixels must have turned.
    """
    from PIL import Image

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from photo_sample import bake_orientation

    landscape = tmp / "rotated.jpg"
    im = Image.new("RGB", (400, 200), (10, 120, 200))
    exif = im.getexif()
    exif[274] = 6                                    # Rotate 90 CW
    im.save(landscape, exif=exif)

    assert Image.open(landscape).size == (400, 200)
    assert Image.open(landscape).getexif().get(274) == 6

    bake_orientation(landscape)
    after = Image.open(landscape)
    assert after.size == (200, 400), f"pixels not turned: {after.size}"
    assert after.getexif().get(274) in (None, 1), "orientation tag survived"

    # Idempotent: a second pass must not rotate an already-upright file, or a
    # re-run of the pipeline turns every corrected thumbnail a further 90.
    bake_orientation(landscape)
    assert Image.open(landscape).size == (200, 400), "second pass rotated again"

    upright = tmp / "upright.jpg"
    Image.new("RGB", (300, 100), (200, 30, 30)).save(upright)
    bake_orientation(upright)
    assert Image.open(upright).size == (300, 100), "a file with no tag was altered"


def case_video_mismatched_extension_gets_corrected_copy(tmp):
    """Regression case for the real-dump finding: qlmanage resolves its
    generator from the file EXTENSION, not content, and hangs 90s+ on a
    mismatch. The invariant that matters is what path qlmanage is actually
    invoked with — not whether a copy happens to be left on disk (that would
    still pass if the copy ran AFTER qlmanage, which is the bug)."""
    import subprocess
    need_qlmanage()
    src_dir = tmp / "vidsrc"
    src_dir.mkdir()
    fake = src_dir / "clip.png"                # real FileType is MOV, extension lies
    fake.write_bytes(b"not real video bytes, only testing the copy trigger")
    dst_dir = tmp / "dst"
    dst_dir.mkdir()

    calls = []
    original_run = subprocess.run

    def spy(cmd, **kw):
        calls.append(cmd)
        return original_run(cmd, **kw)

    photo_embed.subprocess.run = spy
    try:
        with preview_backend("sips"):
            photo_embed.convert_to_thumbnail(fake, dst_dir, "stem1", "video", "MOV")
    finally:
        photo_embed.subprocess.run = original_run

    qlmanage_calls = [c for c in calls if c[0] == "qlmanage"]
    assert len(qlmanage_calls) == 1, calls
    qlmanage_arg = qlmanage_calls[0][-1]
    assert qlmanage_arg.endswith(".mov"), qlmanage_arg
    assert qlmanage_arg != str(fake), \
        "qlmanage must never see the original mismatched-extension path"


def case_video_matching_extension_skips_the_copy(tmp):
    import subprocess
    need_qlmanage()
    src_dir = tmp / "vidsrc2"
    src_dir.mkdir()
    fake = src_dir / "clip.mov"                 # extension already matches kind=video
    fake.write_bytes(b"not real video bytes either")
    dst_dir = tmp / "dst2"
    dst_dir.mkdir()

    calls = []
    original_run = subprocess.run

    def spy(cmd, **kw):
        calls.append(cmd)
        return original_run(cmd, **kw)

    photo_embed.subprocess.run = spy
    try:
        with preview_backend("sips"):
            photo_embed.convert_to_thumbnail(fake, dst_dir, "stem2", "video", "MOV")
    finally:
        photo_embed.subprocess.run = original_run

    qlmanage_calls = [c for c in calls if c[0] == "qlmanage"]
    assert len(qlmanage_calls) == 1, calls
    assert qlmanage_calls[0][-1] == str(fake), \
        "when the extension already matches, qlmanage should see the original path — no copy needed"
    assert list(dst_dir.glob("*_src.mov")) == [], \
        "no copy should be made when the extension already matches — avoids the cost for the common case"


def case_index_root_prunes_renamed_folder(tmp):
    """E-1: --index-root keyed the index on the full path, so a folder rename
    (what photo-execute does for a living) re-added every file under its new
    path and kept the old rows AND the old folder centroid — VS-1b's
    recurrence census counted those photos twice."""
    import json
    root = tmp.resolve() / "sorted"            # run_index_root resolves; centroid keys are resolved paths
    (root / "20260101_A_event").mkdir(parents=True)
    (root / "20260202_B_event").mkdir(parents=True)
    for i in range(3):
        make_image(root / "20260101_A_event" / f"a{i}.jpg", (i * 40, 10, 10))
    for i in range(2):
        make_image(root / "20260202_B_event" / f"b{i}.jpg", (10, i * 40, 10))

    photo_embed.run_index_root(root, force=False, device_arg=None)
    (root / "20260101_A_event").rename(root / "20260101_台北_event")
    summary = photo_embed.run_index_root(root, force=False, device_arg=None)

    index_dir = root / ".photo-embed-index"
    rows, vecs, _ = photo_embed.load_existing(index_dir)
    assert len(rows) == len(vecs) == 5, f"{len(rows)} rows / {len(vecs)} vectors, want 5 each"
    assert summary["pruned"] == 3, summary
    centroids = json.loads((index_dir / "folder-centroids.json").read_text())
    assert len(centroids) == 2, list(centroids)
    assert str(root / "20260101_A_event") not in centroids, \
        "a folder that no longer exists must not keep a centroid"
    assert str(root / "20260101_台北_event") in centroids, list(centroids)
    assert sum(c["n"] for c in centroids.values()) == 5, centroids
    # the 3 moved files are the same content: their vectors are reclaimed, not
    # re-embedded (E-1's second half — a rename must not cost a re-embed)
    assert summary["reclaimed"] == 3, summary
    assert summary["newly_embedded"] == 0, summary


def case_moved_file_keeps_its_vector(tmp):
    """The reclaim path must reproduce the SAME vector the file had before it
    moved — a resurrected row is only sound if it is bit-identical."""
    import numpy as np
    embed_dir, manifest = case_basic_embed(tmp)
    prior_rows, prior_vecs, _ = photo_embed.load_existing(embed_dir)
    before = {r["SourceFile"]: v for r, v in zip(prior_rows, prior_vecs)}
    old = Path(manifest[0]["SourceFile"])
    new = old.with_name("moved_" + old.name)
    old.rename(new)
    manifest = [manifest_row(new)] + manifest[1:]

    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["total_in_index"] == 4, summary
    assert summary["reclaimed"] == 1, summary
    assert summary["newly_embedded"] == 0, summary
    rows, vecs, _ = photo_embed.load_existing(embed_dir)
    got = {r["SourceFile"]: v for r, v in zip(rows, vecs)}
    assert str(old) not in got, "the vanished path must be gone from the index"
    assert np.array_equal(got[str(new)], before[str(old)]), "reclaimed vector differs"


def case_skips_are_counted_and_reported(tmp):
    """E-2: an ineligible file and a file that vanished between scan and embed
    both used to be a bare `continue` — the summary's arithmetic didn't close
    and nothing said where they went."""
    embed_dir, manifest = case_basic_embed(tmp)
    gone = Path(manifest[0]["SourceFile"])
    gone.unlink()
    sidecar = tmp / "src" / "._IMG_0001.JPG"
    sidecar.write_text("AppleDouble, exiftool FileType MacOS")
    manifest = manifest + [manifest_row(sidecar, filetype="MacOS")]

    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["skipped_ineligible"] == 1, summary
    assert summary["skipped_missing"] == 1, summary
    assert summary["pruned"] == 1, summary
    assert summary["total_in_index"] == 3, summary
    assert (summary["files_seen"] == summary["skipped_ineligible"]
            + summary["skipped_missing"] + summary["already_embedded"]
            + summary["newly_embedded"] + summary["reclaimed"] + summary["failed"]), \
        f"summary arithmetic must close: {summary}"


def case_unmounted_source_does_not_wipe_the_index(tmp):
    """Pruning must not turn an unmounted drive into an emptied index."""
    embed_dir, manifest = case_basic_embed(tmp)
    shutil.rmtree(tmp / "src")
    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["pruned"] == 0, summary
    assert summary["total_in_index"] == 4, summary
    assert summary["skipped_missing"] == 4, summary
    assert summary["already_embedded"] == 0, \
        f"nothing was confirmed this run; the counters must still add up: {summary}"
    rows, vecs, _ = photo_embed.load_existing(embed_dir)
    assert len(rows) == len(vecs) == 4, (len(rows), len(vecs))


def case_blank_size_field_does_not_crash_resume(tmp):
    """E-3: a truncated / hand-edited embeddings.csv used to abort the resume
    with ValueError: invalid literal for int() with base 10: ''."""
    import csv
    embed_dir, manifest = case_basic_embed(tmp)
    csv_path = embed_dir / "embeddings.csv"
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    rows[0]["size"] = ""
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=photo_embed.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)

    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["newly_embedded"] == 1, summary       # just that one, re-embedded
    assert summary["total_in_index"] == 4, summary


def case_created_at_survives_an_interrupted_run(tmp):
    """E-4: the mid-run periodic save wrote meta BEFORE created_at was set, so
    a run interrupted after that save (Ctrl-C, sleep, crash) left
    created_at null in the index's provenance record, permanently."""
    import json
    src = tmp / "src_interrupt"
    src.mkdir()
    for i in range(3):
        make_image(src / f"c{i}.jpg", (i * 50, 30, 90))
    embed_dir = tmp / "case_interrupt" / "embed"
    manifest = [manifest_row(p) for p in sorted(src.glob("*.jpg"))]

    original, original_batch_size = photo_embed.embed_batch, photo_embed.BATCH_SIZE
    calls = []

    def spy(torch, model, preprocess, device, images):
        calls.append(1)
        if len(calls) > 1:                       # after the first periodic save
            raise KeyboardInterrupt("simulated interrupt")
        return original(torch, model, preprocess, device, images)

    photo_embed.embed_batch, photo_embed.BATCH_SIZE = spy, 1
    try:
        photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                        errors_log=embed_dir / "embed-errors.log")
        raise AssertionError("expected the simulated interrupt to propagate")
    except KeyboardInterrupt:
        pass
    finally:
        photo_embed.embed_batch, photo_embed.BATCH_SIZE = original, original_batch_size

    meta = json.loads((embed_dir / "embeddings-meta.json").read_text())
    created = meta.get("created_at")
    assert created, f"interrupted run lost created_at: {meta}"

    photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                    errors_log=embed_dir / "embed-errors.log")
    meta2 = json.loads((embed_dir / "embeddings-meta.json").read_text())
    assert meta2.get("created_at") == created, (created, meta2)
    assert meta2.get("zero_vector_means_failed") is True, meta2   # E-6


def case_errors_log_is_not_stale(tmp):
    """E-5: the log was only rewritten when the CURRENT run had errors, and it
    replaced the file — so a clean re-run kept naming files that no longer
    fail."""
    src = tmp / "src_stale"
    src.mkdir()
    good = src / "good.jpg"
    make_image(good, (10, 20, 30))
    bad = src / "bad.jpg"
    bad.write_text("not an image")
    embed_dir = tmp / "case_stale" / "embed"
    errors_log = embed_dir / "embed-errors.log"
    manifest = [manifest_row(good), manifest_row(bad)]
    photo_embed.run(manifest, embed_dir, force=False, device_arg=None, errors_log=errors_log)
    assert str(bad) in errors_log.read_text(), errors_log.read_text()

    bad.unlink()
    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=errors_log)
    assert summary["pruned"] == 1, summary
    assert not errors_log.exists(), \
        f"log must not keep naming a file that no longer fails: {errors_log.read_text()}"


def case_temp_files_do_not_accumulate(tmp):
    """E-7: every thumbnail (and every full-size corrected-extension copy) was
    kept until the run ended."""
    src = tmp / "src_tmp"
    src.mkdir()
    for i in range(3):
        make_image(src / f"t{i}.jpg", (i * 60, 5, 5))
    embed_dir = tmp / "case_tmp" / "embed"
    manifest = [manifest_row(p) for p in sorted(src.glob("*.jpg"))]

    seen = []
    original, original_batch_size = photo_embed.embed_batch, photo_embed.BATCH_SIZE

    def spy(torch, model, preprocess, device, images):
        # one file per batch, so by batch 3 an un-cleaned temp dir holds 3
        seen.append(len(list(Path(images[0]).parent.iterdir())))
        return original(torch, model, preprocess, device, images)

    photo_embed.embed_batch, photo_embed.BATCH_SIZE = spy, 1
    try:
        photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                        errors_log=embed_dir / "embed-errors.log")
    finally:
        photo_embed.embed_batch, photo_embed.BATCH_SIZE = original, original_batch_size

    assert len(seen) == 3, seen
    assert seen == [1, 1, 1], f"temp files accumulated across batches: {seen}"


QUICKTIME_MAGIC = b"\x00\x00\x00\x14ftypqt  \x00\x00\x02\x00qt  " + b"\x00" * 512


def case_exiftool_heic_lie_is_embedded_as_video(tmp):
    """L17: exiftool calls some HEIC-named QuickTime movies FileType HEIC, so
    they went to `sips`, which correctly refuses real video — 216/4,819 lost
    in the real 202605 dump. Magic bytes must overrule FileType and route them
    as video. convert_to_thumbnail is stubbed: qlmanage genuinely hangs on the
    truncated movie header this case can synthesize (25s CONVERT_TIMEOUT), and
    the invariant under test is the dispatch, not Quick Look."""
    src = tmp / "src_lie"
    src.mkdir()
    liar = src / "IMG_9999.HEIC"               # QuickTime content, HEIC name, HEIC FileType
    liar.write_bytes(QUICKTIME_MAGIC)
    embed_dir = tmp / "case_lie" / "embed"
    manifest = [manifest_row(liar, filetype="HEIC")]

    seen = []
    original = photo_embed.convert_to_thumbnail

    def spy(source_file, dst_dir, stem, kind, filetype):
        seen.append((kind, filetype))
        out = Path(dst_dir) / f"{stem}.jpg"
        make_image(out, (30, 60, 90))
        return out, None

    photo_embed.convert_to_thumbnail = spy
    try:
        summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                                  errors_log=embed_dir / "embed-errors.log")
    finally:
        photo_embed.convert_to_thumbnail = original

    assert seen == [("video", "MOV")], \
        f"a QuickTime file must be converted as video/MOV, not as its lying FileType: {seen}"
    assert summary["magic_corrected"] == 1, summary
    assert summary["newly_embedded"] == 1, summary
    assert summary["failed"] == 0, summary

    import csv
    rows = list(csv.DictReader(open(embed_dir / "embeddings.csv", newline="")))
    assert rows[0]["kind"] == "video", rows
    assert rows[0]["status"] == "embedded", rows


def case_image_content_with_video_filetype_is_embedded(tmp):
    """The other direction of the same D13 mismatch, and why the check is not
    limited to image-typed rows: a real image carrying a video FileType (what
    --index-root's suffix inference produces for a JPEG named .mp4) would go
    to qlmanage and hang. End-to-end — this one really is embedded."""
    src = tmp / "src_rev"
    src.mkdir()
    liar = src / "clip_0001.mp4"               # JPEG content, video name and FileType
    make_image(liar, (120, 40, 200), "JPEG")
    embed_dir = tmp / "case_rev" / "embed"
    manifest = [manifest_row(liar, filetype="MP4")]

    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["magic_corrected"] == 1, summary
    assert summary["newly_embedded"] == 1, summary
    assert summary["failed"] == 0, summary

    import csv
    rows = list(csv.DictReader(open(embed_dir / "embeddings.csv", newline="")))
    assert rows[0]["kind"] == "image", rows


def case_genuine_image_is_not_rerouted(tmp):
    """The safety half: a HEIC-typed row whose content really is an image must
    be left exactly as it was. The content here is JPEG rather than HEIC (no
    HEIF encoder in the .venv, and this suite generates every file it uses),
    which also pins the narrower rule — the override fires on a changed
    image/video KIND, not on any FileType-vs-mime disagreement."""
    src = tmp / "src_true"
    src.mkdir()
    still = src / "IMG_0001.HEIC"
    make_image(still, (200, 200, 30), "JPEG")
    embed_dir = tmp / "case_true" / "embed"
    manifest = [manifest_row(still, filetype="HEIC")]

    seen = []
    original = photo_embed.convert_to_thumbnail

    def spy(source_file, dst_dir, stem, kind, filetype):
        seen.append((kind, filetype))
        return original(source_file, dst_dir, stem, kind, filetype)

    photo_embed.convert_to_thumbnail = spy
    try:
        summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                                  errors_log=embed_dir / "embed-errors.log")
    finally:
        photo_embed.convert_to_thumbnail = original

    assert seen == [("image", "HEIC")], f"a genuine image must keep its FileType dispatch: {seen}"
    assert summary["magic_corrected"] == 0, summary
    assert summary["newly_embedded"] == 1, summary
    assert summary["failed"] == 0, summary


def case_noop_resume_does_not_magic_check(tmp):
    """The magic-byte check opens every file it is given, so it must
    see only the PENDING list. A resume with nothing to do stat()s and stops —
    if it ever sniffs the whole index instead, 0.1s becomes minutes."""
    embed_dir, manifest = case_basic_embed(tmp)

    calls = []
    original = photo_embed.magic_filetypes

    def spy(paths):
        calls.append(list(paths))
        return original(paths)

    photo_embed.magic_filetypes = spy
    try:
        summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                                  errors_log=embed_dir / "embed-errors.log")
        assert summary["newly_embedded"] == 0, summary
        assert calls == [], f"a no-op resume must not magic-byte-check anything: {calls}"

        p = Path(manifest[0]["SourceFile"])
        make_image(p, (7, 7, 7))               # one changed file -> exactly one pending
        photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                        errors_log=embed_dir / "embed-errors.log")
        assert len(calls) == 1 and calls[0] == [str(p)], \
            f"only the pending file should be checked, not all 4 rows: {calls}"
    finally:
        photo_embed.magic_filetypes = original


# ------------------------------------------------ --scene-labels (VS-2) -----
# F11: the +79 lines `encode_scene_labels` added to this file shipped with no
# tests at all. The refuse path needs no model. The rest is covered against a
# STUBBED text tower — the real one costs a model load and would test
# open_clip, not this function: what belongs to this file is the JSON/npy
# shape, the identity fields photo_see refuses a mismatch on, and the
# prompt-ensembling arithmetic (encode -> L2-normalize -> mean ->
# re-normalize), all of which the stub reproduces exactly.


class FakeTensor:
    """The handful of torch operations `encode_scene_labels` performs, over
    numpy. Nothing here pretends to be torch in general."""

    def __init__(self, array):
        import numpy as np
        self.a = np.asarray(array, dtype="float32")

    def __truediv__(self, other):
        return FakeTensor(self.a / (other.a if isinstance(other, FakeTensor) else other))

    def norm(self, dim=None, keepdim=False):
        import numpy as np
        if dim is None:
            return FakeTensor(np.linalg.norm(self.a))
        return FakeTensor(np.linalg.norm(self.a, axis=dim, keepdims=keepdim))

    def mean(self, dim=0):
        return FakeTensor(self.a.mean(axis=dim))

    def to(self, _device):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.a


FAKE_DIM = 8


def prompt_vector(prompt):
    """A deterministic pseudo-embedding per prompt string, so the test can
    recompute the ensemble independently of the code under test."""
    import hashlib
    import numpy as np
    digest = hashlib.sha256(prompt.encode()).digest()
    return np.array([digest[i] - 128 for i in range(FAKE_DIM)], dtype="float32")


class FakeTextTower:
    def eval(self):
        return self

    def to(self, _device):
        return self

    def encode_text(self, tokens):
        import numpy as np
        return FakeTensor(np.stack([prompt_vector(p) for p in tokens.prompts]))


class FakeTokens:
    def __init__(self, prompts):
        self.prompts = list(prompts)

    def to(self, _device):
        return self


def stub_clip():
    """Install fake `torch` / `open_clip` modules; returns a restore callable."""
    import types
    saved = {name: sys.modules.get(name) for name in ("torch", "open_clip")}

    torch = types.ModuleType("torch")
    torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False))

    class _NoGrad:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    torch.no_grad = _NoGrad
    open_clip = types.ModuleType("open_clip")
    open_clip.create_model_and_transforms = \
        lambda model_id, pretrained=None: (FakeTextTower(), None, "fake-preprocess")
    open_clip.get_tokenizer = lambda model_id: FakeTokens
    sys.modules["torch"], sys.modules["open_clip"] = torch, open_clip

    def restore():
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
    return restore


def case_scene_labels_refuse_without_force(tmp):
    """The refuse path is reachable before the model is loaded, and it must
    stay that way — re-encoding is a several-second model load, and silently
    overwriting a label file whose vectors are already referenced by a written
    see-report is not a recovery."""
    import json
    embed_dir = tmp / "embed"
    embed_dir.mkdir(parents=True)
    (embed_dir / "scene-labels.json").write_text(json.dumps({"classes": ["x"]}))
    restore = stub_clip()
    try:
        try:
            photo_embed.encode_scene_labels(embed_dir, {}, "cpu", force=False)
        except SystemExit as exc:
            assert "--force" in str(exc), exc
        else:
            raise AssertionError("an existing scene-labels.json was overwritten")
        # ...and --force goes through
        meta = photo_embed.encode_scene_labels(embed_dir, {}, "cpu", force=True)
        assert meta["kind"] == "scene-labels", meta
    finally:
        restore()


def case_scene_labels_json_and_prompt_ensembling(tmp):
    """One vector per CLASS, not per prompt: each prompt is encoded,
    L2-normalized, averaged, then re-normalized. The JSON records the exact
    prompt strings so the .npy is re-derivable from a declared input."""
    import json
    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import photo_see

    embed_dir = tmp / "embed"
    restore = stub_clip()
    try:
        meta = photo_embed.encode_scene_labels(embed_dir, {}, "cpu", force=False)
    finally:
        restore()

    classes, source = photo_see.scene_label_set({})
    assert meta["classes"] == list(classes), meta["classes"]
    assert meta["prompts"] == {k: list(v) for k, v in classes.items()}, meta["prompts"]
    assert meta["label_set_source"] == source == "engine fallback", meta
    assert meta["prompt_language"] == "en", meta
    assert meta["embed_dim"] == FAKE_DIM and meta["normalized"] is True, meta

    arr = np.load(embed_dir / "scene-labels.npy")
    assert arr.shape == (len(classes), FAKE_DIM), arr.shape
    assert np.allclose(np.linalg.norm(arr, axis=1), 1.0, atol=1e-5), \
        "every class vector must be unit-norm — photo_see takes raw dot products"

    for row, (name, prompts) in zip(arr, classes.items()):
        feats = np.stack([prompt_vector(p) for p in prompts])
        feats = feats / np.linalg.norm(feats, axis=-1, keepdims=True)
        mean = feats.mean(axis=0)
        expected = mean / np.linalg.norm(mean)
        assert np.allclose(row, expected, atol=1e-5), name
    log(f"{len(classes)} classes ensembled from "
        f"{sum(len(p) for p in classes.values())} prompts")


def case_scene_labels_carry_the_image_index_identity(tmp):
    """The contract with photo_see: a text vector from another CLIP is not
    comparable to these image vectors, so the label file carries the same
    identity fields as embeddings-meta.json and is refused when they differ.
    Asserted end to end — encode here, load there."""
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import photo_see
    from photo_recurrence import META_IDENTITY

    embed_dir = tmp / "embed"
    restore = stub_clip()
    try:
        meta = photo_embed.encode_scene_labels(embed_dir, {}, "cpu", force=False)
    finally:
        restore()

    identity = {k: meta.get(k) for k in META_IDENTITY}
    assert all(identity[k] is not None for k in META_IDENTITY), identity
    assert identity["model_id"] == photo_embed.MODEL_ID
    assert identity["pretrained_tag"] == photo_embed.PRETRAINED_TAG
    assert identity["preprocess_fingerprint"].startswith("sha256:"), identity

    classes, _src = photo_see.scene_label_set({})
    matrix, encoded, loaded = photo_see.load_scene_labels(
        embed_dir / "scene-labels.json", identity, list(classes))
    assert matrix is not None and encoded == list(classes)
    assert loaded["kind"] == "scene-labels"

    other = dict(identity, model_id="ViT-Other")
    try:
        photo_see.load_scene_labels(embed_dir / "scene-labels.json", other,
                                    list(classes))
    except SystemExit as exc:
        assert "different model" in str(exc), exc
    else:
        raise AssertionError("a label file from another model was accepted")


# ---------------------------------------------------------------------------
# W2C / ADR 0005 — the paperwork score, written where CLIP already runs.
#
# ⭐ REPRODUCTION: until W2C nothing scored a file for financial or official
# paperwork, so a photographed bill was sorted and named like a holiday photo.
# Synthetic images only; no real document is ever used here.

# Read through getattr so that on an engine without W2C each case FAILS on
# what is missing rather than crashing the suite on an AttributeError.
SCORES_NAME = getattr(photo_embed, "PAPERWORK_SCORES_NAME", "paperwork-scores.json")
IDENTITY = getattr(photo_embed, "PAPERWORK_IDENTITY",
                   ("model_id", "pretrained_tag", "preprocess_fingerprint"))


def paperwork_file(embed_dir):
    import json
    path = embed_dir / SCORES_NAME
    return json.loads(path.read_text()) if path.exists() else None


def case_a_run_scores_every_still_for_paperwork(tmp):
    """⭐ REPRODUCTION: the file exists, carries the image index's identity,
    and holds one number per embedded still."""
    import json
    embed_dir, manifest = case_basic_embed(tmp)
    data = (embed_dir / SCORES_NAME).exists() \
        and paperwork_file(embed_dir)
    assert data, "no paperwork-scores.json after a run"
    meta = json.loads((embed_dir / "embeddings-meta.json").read_text())
    for key in IDENTITY:
        assert data[key] == meta[key], (key, data[key], meta[key])
    assert set(data["scores"]) == {r["SourceFile"] for r in manifest}, data["scores"]
    assert all(isinstance(v, float) for v in data["scores"].values())


def case_a_noop_resume_backfills_missing_scores(tmp):
    """⭐ REPRODUCTION for every dump embedded before W2C: a plain re-run adds
    the scores, with no --force and no re-embedding."""
    embed_dir, manifest = case_basic_embed(tmp)
    (embed_dir / SCORES_NAME).unlink(missing_ok=True)
    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["newly_embedded"] == 0, summary
    data = paperwork_file(embed_dir)
    assert data and len(data["scores"]) == 4, data


def case_current_scores_cost_a_noop_resume_nothing(tmp):
    """Guard: scores that already cover the index are not recomputed, so a
    no-op resume still never loads the model."""
    embed_dir, manifest = case_basic_embed(tmp)
    assert paperwork_file(embed_dir), "precondition: scores written"
    original = photo_embed.load_model
    photo_embed.load_model = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("a no-op resume loaded the model"))
    try:
        photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                        errors_log=embed_dir / "embed-errors.log")
    finally:
        photo_embed.load_model = original


def case_only_embedded_stills_are_scored(tmp):
    """⛔ STILLS ONLY (Lead ruling, LL-PHO-131's stance): a video's poster
    frame is never scored, so it can never be moved; nor is a failed row."""
    import numpy as np
    embed_dir = tmp / "embed"
    embed_dir.mkdir()
    rows = [{"SourceFile": "/a.jpg", "kind": "image", "status": "embedded"},
            {"SourceFile": "/v.mp4", "kind": "video", "status": "embedded"},
            {"SourceFile": "/f.jpg", "kind": "image", "status": "failed"}]
    vec = np.ones(512, dtype=np.float32) / np.sqrt(512)
    meta = {"model_id": photo_embed.MODEL_ID,
            "pretrained_tag": photo_embed.PRETRAINED_TAG,
            "preprocess_fingerprint": "sha256:test"}
    scorer = getattr(photo_embed, "write_paperwork_scores", None)
    assert scorer, "photo_embed has no paperwork scorer"
    data = scorer(embed_dir, rows, [vec] * 3, meta)
    assert set(data["scores"]) == {"/a.jpg"}, data["scores"]


def case_a_drawn_bill_outscores_a_plain_colour(tmp):
    """Sanity on the real text tower, synthetic pixels only: a white page
    ruled like a bill must score above a flat colour field. Not a threshold
    test — the cut is the plan stage's, and it is a pack parameter."""
    from PIL import Image, ImageDraw
    src = tmp / "src"
    src.mkdir()
    bill = Image.new("RGB", (600, 800), "white")
    d = ImageDraw.Draw(bill)
    d.text((40, 30), "INVOICE", fill="black")
    for y in range(90, 700, 36):
        d.line([(40, y), (560, y)], fill="gray")
        d.text((44, y + 8), "Item    Qty    Amount    Tax", fill="black")
    d.text((40, 720), "TOTAL DUE    Account No.    Due date", fill="black")
    bill.save(src / "bill.jpg")
    make_image(src / "plain.jpg", (40, 160, 60))
    embed_dir = tmp / "embed"
    manifest = [manifest_row(src / "bill.jpg"), manifest_row(src / "plain.jpg")]
    photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                    errors_log=embed_dir / "embed-errors.log")
    s = (paperwork_file(embed_dir) or {}).get("scores") or {}
    assert str(src / "bill.jpg") in s and str(src / "plain.jpg") in s, s
    assert s[str(src / "bill.jpg")] > s[str(src / "plain.jpg")], s


def draw_bill(path):
    from PIL import Image, ImageDraw
    bill = Image.new("RGB", (600, 800), "white")
    d = ImageDraw.Draw(bill)
    d.text((40, 30), "INVOICE", fill="black")
    for y in range(90, 700, 36):
        d.line([(40, y), (560, y)], fill="gray")
        d.text((44, y + 8), "Item    Qty    Amount    Tax", fill="black")
    d.text((40, 720), "TOTAL DUE    Account No.    Due date", fill="black")
    bill.save(path)


def case_a_re_embedded_file_is_re_scored(tmp):
    """⭐ REPRODUCTION (found in review). A file replaced at the same path is
    re-embedded in place, so the set of scored paths does not change — and a
    refresh keyed on that set alone kept the OLD score for the NEW picture."""
    src = tmp / "src"
    src.mkdir()
    make_image(src / "a.jpg", (40, 160, 60))
    make_image(src / "b.jpg", (160, 40, 60))
    embed_dir = tmp / "embed"
    manifest = [manifest_row(src / "a.jpg"), manifest_row(src / "b.jpg")]
    photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                    errors_log=embed_dir / "embed-errors.log")
    before = ((paperwork_file(embed_dir) or {}).get("scores") or {}).get(str(src / "a.jpg"))
    draw_bill(src / "a.jpg")
    summary = photo_embed.run(manifest, embed_dir, force=False, device_arg=None,
                              errors_log=embed_dir / "embed-errors.log")
    assert summary["newly_embedded"] == 1, summary
    after = ((paperwork_file(embed_dir) or {}).get("scores") or {}).get(str(src / "a.jpg"))
    assert before is not None and after is not None and after != before, (before, after)


CASES = [
    ("basic embed: shape, normalization", lambda tmp: case_basic_embed(tmp) and None),
    ("W2C: a re-embedded file is re-scored", case_a_re_embedded_file_is_re_scored),
    ("W2C: a run scores every still for paperwork", case_a_run_scores_every_still_for_paperwork),
    ("W2C: a no-op resume backfills missing scores", case_a_noop_resume_backfills_missing_scores),
    ("W2C: current scores cost a no-op resume nothing", case_current_scores_cost_a_noop_resume_nothing),
    ("W2C: only embedded stills are scored, never a video", case_only_embedded_stills_are_scored),
    ("W2C: a drawn bill outscores a plain colour", case_a_drawn_bill_outscores_a_plain_colour),
    ("resume: no-op when nothing changed", case_resume_noop),
    ("resume: appends exactly the new file", case_resume_add_one),
    ("resume: re-embeds a changed file in place, no duplicate row", case_resume_changed_file),
    ("model/meta mismatch hard-fails without --force", case_meta_mismatch_hard_fails),
    ("--force rebuilds cleanly after a mismatch", case_force_rebuilds_after_mismatch),
    ("a corrupt file fails without killing the run, rows stay aligned", case_failed_file_recorded_not_fatal),
    ("a whole-batch model failure still records every row", case_batch_exception_still_records_every_row),
    ("video with a mismatched extension gets a corrected-extension copy before qlmanage",
     case_video_mismatched_extension_gets_corrected_copy),
    ("video with a matching extension skips the copy", case_video_matching_extension_skips_the_copy),
    ("--index-root: a renamed folder is not counted twice (E-1)",
     case_index_root_prunes_renamed_folder),
    ("a moved file keeps its exact vector instead of being re-embedded (E-1)",
     case_moved_file_keeps_its_vector),
    ("skipped-ineligible / skipped-missing are counted and the summary closes (E-2)",
     case_skips_are_counted_and_reported),
    ("an unavailable source does not wipe the index (E-1 guard)",
     case_unmounted_source_does_not_wipe_the_index),
    ("a blank size field re-embeds instead of crashing the resume (E-3)",
     case_blank_size_field_does_not_crash_resume),
    ("created_at survives an interrupted run (E-4, E-6)",
     case_created_at_survives_an_interrupted_run),
    ("embed-errors.log never names a file that no longer fails (E-5)",
     case_errors_log_is_not_stale),
    ("temp thumbnails are deleted after each batch (E-7)",
     case_temp_files_do_not_accumulate),
    ("a QuickTime movie exiftool calls HEIC is embedded as video, not failed (L17)",
     case_exiftool_heic_lie_is_embedded_as_video),
    ("an image carrying a video FileType is embedded as an image (L17, other direction)",
     case_image_content_with_video_filetype_is_embedded),
    ("a genuine image keeps its FileType dispatch — no false override (L17)",
     case_genuine_image_is_not_rerouted),
    ("a no-op resume magic-byte-checks nothing; a resume checks only the pending file (L17)",
     case_noop_resume_does_not_magic_check),
    ("--scene-labels refuses to overwrite without --force (F11)",
     case_scene_labels_refuse_without_force),
    ("--scene-labels: JSON shape and prompt ensembling (F11)",
     case_scene_labels_json_and_prompt_ensembling),
    ("--scene-labels carries the image index's identity, and photo_see enforces it (F11)",
     case_scene_labels_carry_the_image_index_identity),
    ("EXIF orientation is baked into the pixels, once, and never re-applied",
     case_orientation_is_baked_into_the_pixels),
]


class _FakeOpenClip:
    @staticmethod
    def get_pretrained_cfg(model, tag):
        assert (model, tag) == (photo_embed.MODEL_ID, photo_embed.PRETRAINED_TAG)
        return {"hf_hub": "someone/some-clip/"}


class _FakeHub:
    def __init__(self, on_disk):
        self.on_disk = set(on_disk)

    def try_to_load_from_cache(self, repo, filename):
        assert repo == "someone/some-clip", repo
        return f"/cache/{repo}/{filename}" if filename in self.on_disk else None


class _FakeConstants:
    HF_HUB_OFFLINE = False


def case_clip_loads_offline_once_installed(tmp):
    """GUARD (FIX8 F8-9, owner decision "offline once installed"). With the
    weights on disk the hub's offline switch is on for the load and restored
    after, even when the load raises; with nothing on disk the load stays
    online. The socket probe that proves 0 lookups needs the real model and
    is run at acceptance, not here."""
    installed = _FakeHub({"open_clip_model.safetensors"})
    assert photo_embed.clip_cached(_FakeOpenClip, installed)
    assert not photo_embed.clip_cached(_FakeOpenClip, _FakeHub(()))
    assert not photo_embed.clip_cached(object(), installed)
    assert not photo_embed.clip_cached(_FakeOpenClip, None)
    consts = _FakeConstants()
    with photo_embed.hub_offline(consts, True):
        assert consts.HF_HUB_OFFLINE is True
    assert consts.HF_HUB_OFFLINE is False
    try:
        with photo_embed.hub_offline(consts, True):
            raise RuntimeError("load failed")
    except RuntimeError:
        pass
    assert consts.HF_HUB_OFFLINE is False
    with photo_embed.hub_offline(consts, False):
        assert consts.HF_HUB_OFFLINE is False


CASES.append(("F8-9 — CLIP loads offline once installed (GUARD)",
              case_clip_loads_offline_once_installed))


def main():
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    VERBOSE = args.verbose

    ok = run_case("kind_of() dispatches image/video/None correctly", case_kind_of_dispatch)
    passed, total = (1 if ok else 0), 1

    for name, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="photo_embed_test_"))
        try:
            ok = run_case(name, lambda: fn(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        passed += 1 if ok else 0
        total += 1

    print(f"\n{passed}/{total} photo_embed cases passed"
          + (f" ({len(SKIPPED)} skipped)" if SKIPPED else ""))
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
