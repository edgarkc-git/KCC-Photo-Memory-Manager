#!/usr/bin/env python3
"""VS-1 — local CLIP embedding index for one work dir.

Reads manifest.csv; writes into the work dir only:
  embed/embeddings.npy         float32 (N, D), L2-normalized, row i = row i
                                of embeddings.csv
  embed/embeddings.csv         SourceFile, sha256, kind, status, size, mtime
  embed/embeddings-meta.json   model identity — the guard against comparing
                                vectors across incompatible model swaps
  embed/embed-errors.log       per-file failures (sips/qlmanage/decode)

Every image is embedded directly; every video contributes ONE frame — one
row per FILE, never per frame, because VS-1b's recurrence census and
cluster-identity dedupe key both operate at file granularity. Previews come
from `convert_to_thumbnail`: Pillow + ffmpeg by default on every machine,
sips + qlmanage behind $PHOTO_PREVIEW_BACKEND=sips. A file with no preview
is recorded with its cause, and the stage exits 3 naming each cause.

The history below is the sips/qlmanage backend's, and still binds it:

Conversion dispatches on the manifest's exiftool FileType (already computed
at scan time), NOT the filename suffix — unlike photo_sample.make_viewable.
Found running this against the real 202605 dump (documented here because it
cost 4.2 hours instead of ~25 minutes to find): `qlmanage` resolves which
Quick Look generator to use from the file's EXTENSION, not its content —
confirmed both directions: a real HEIC image saved with a `.MP4` name (D13)
hangs qlmanage 90s+, and a real QuickTime video saved with a `.PNG` name
hangs it just as badly. A plain symlink to a correctly-named path does NOT
fix this (Quick Look resolves through it to the real name) — only an actual
byte copy to a correctly-extensioned temp path does. `sips`, by contrast,
sniffs real content and handles a mismatched extension fine on its own
(verified directly). So: images always call `sips` on the source path
as-is; videos call `qlmanage` on the source path when its extension is
already MOV/MP4, and on a corrected-extension temp COPY otherwise. A
bounded per-file timeout is still the backstop for whatever this doesn't
anticipate.

Of the 273 files this recovered in the real dump (489 failed -> 216
failed), only 5 needed the corrected-extension copy — the other 268 were
recovered simply by trusting FileType over suffix and sending them to
`sips` instead of `qlmanage` in the first place. The copy machinery is
cheap and only fires on that rare 5-file case, but don't read "5/4819" as
"this bought 5 files" — it is the FileType-vs-suffix dispatch, not the
copy, that did most of the work.

FileType is not the last word, though: exiftool ITSELF sometimes misreports
a HEIC-named QuickTime movie as FileType HEIC (L17, known project-wide) —
216 of the 3,836 HEIC-typed files in the real 202605 dump, 5.6%, are really
QuickTime. Those went to `sips`, which correctly refuses real video content,
and were silently lost. So magic bytes overrule FileType: every PENDING file
is sniffed from its own first bytes (`photo_magic`, pure Python since Card 6
— Unix `file` is missing from Windows PowerShell/cmd) and its kind is
corrected when the two
disagree about image-vs-video — the same override D13 point 1 already
applies at copy time. Deliberate limits: only PENDING files are checked,
never every indexed row, so a no-op resume still costs one stat() per file
and nothing more; content the sniffer cannot place never overrides anything;
and a disagreement that doesn't change the image/video kind (exiftool HEIC
vs content JPEG) is left alone, since kind is all the dispatch uses.
Both directions are checked, not just image-typed files — a real image
carrying a video FileType is the other half of the same D13 mismatch and
would otherwise be sent to qlmanage. The count lands in the summary as
`magic_corrected`.

Never sampled — every eligible file is embedded (VS spec: recurrence
cannot be measured on a sample). Actual coverage is whatever survives
conversion; the summary reports it honestly (skipped_ineligible /
skipped_missing / failed).

Failed files still occupy a row: an all-zero vector at the same row index,
with status "failed" in the CSV. `embeddings-meta.json` carries
"zero_vector_means_failed": true so a later stage that reads the .npy by
row position can tell them apart without parsing the CSV.

Resumable by default: re-running skips any file whose (size, mtime) in
manifest.csv matches what was last recorded, and only (re)embeds new or
changed files. Rows whose file no longer exists are PRUNED before saving —
without that, a folder rename (exactly what photo-execute does, and what
--index-root then walks) left the old rows in place and counted the same
photo twice, inflating the recurrence census. A file that merely moved
keeps its vector: a pruned row is matched to a new path by sha256, gated on
a size match first, so a run that pruned nothing hashes nothing. The
.npy/.csv are rewritten as a whole each run (small
enough at this scale: ~5k rows x 512 float32 is a few MB). A model swap
changes embeddings-meta.json's identity fields, and this script hard-fails
rather than silently mixing two models' vectors in one index (Cosine
similarity, VS-3's stored thresholds, and every exemplar in a subject
registry are only comparable within one model + preprocess regime) — pass
--force to rebuild the index from scratch under the new model.

--index-root mode builds/refreshes a SEPARATE global index over an already-
sorted folder tree instead of one work dir's manifest (VS spec: "a global
index over the sorted tree ... updated after each execute"). It is not
wired into photo_execute.py — that is a deliberate deferral, since the
golden-dump harness covers the PLAN stage only and would not catch a
regression there. Run it by hand when a global recurrence census is needed.

--index-root has no exiftool pass and starts from the filename suffix
(SUFFIX_TO_FILETYPE below). Before the magic-byte check above, that made it
blind to D13 mismatches in a way per-workdir mode was not: kind_of() and the
dispatch extension both came from the same lying suffix, so a sorted tree
full of them (`_2026_Photo_Manager` is exactly where those files get copied
to) could hang for hours. The magic-byte check is the independent source of
truth this mode was missing, and it applies here too — run() is shared. Not
a guarantee, and the residual is bigger here than in per-workdir mode: the
check only sees files that reached `pending`, so a suffix kind_of() can't
place at all (a `.HEIF` name, say) is skipped before the magic bytes ever
get a vote, and a mime `file` can't place falls back to the suffix.
CONVERT_TIMEOUT's 25s per-file bound remains the backstop.

VS-1 exit test (2026-08-06, on `202605`, 4,819 files, MPS): a clean run
embeds in 16m08s — 4,812 embedded, 0 failed, 216 magic_corrected, 6
skipped_ineligible (AppleDouble `._` sidecars, exiftool FileType MacOS), 1
skipped_missing (IMG_4620.MOV, gone from the drive since the scan). That is
every file that exists and is media: 4,812/4,819 = 99.85%. It was 13m56s /
4,596 embedded / 216 failed before the magic-byte check; the extra 2m12s is
~76s of `file --mime-type` over 4,813 eligible paths (15.8 ms/file, warm
cache, external drive) plus the cost of actually converting and embedding
the 1.27 GB of video that used to just fail. A resume of the finished index
is a true no-op — no failed rows left to retry, so the model never loads
and it only stat()s: 0.11s over 4,812 rows, unchanged by the magic-byte
check (measured before/after on the same copied index).

--scene-labels does not touch the image index at all: it runs CLIP's TEXT
tower once over VS-2's zero-shot label set and writes embed/scene-labels.npy
+ .json. It lives here because this is the one stage that already depends on
torch — `photo_see.py` then reads those vectors with numpy only.

Usage:
  python3 photo_embed.py "<Working Files>/202401"
  python3 photo_embed.py "<Working Files>/202401" --force
  python3 photo_embed.py "<Working Files>/202401" --scene-labels
  python3 photo_embed.py --index-root "/Volumes/EXAMPLE_DRIVE/_Photo_Manager"
"""

import argparse
import contextlib
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from photo_sample import IMAGE_TYPES, VIDEO_TYPES  # noqa: E402
import photo_magic  # noqa: E402

MODEL_ID = "ViT-B-32"
PRETRAINED_TAG = "laion2b_s34b_b79k"
BATCH_SIZE = 32
CONVERT_TIMEOUT = 25  # seconds — bounds the worst case this dispatch doesn't already avoid

CSV_FIELDS = ["SourceFile", "sha256", "kind", "status", "size", "mtime", "error"]


# ⛔ The ONE preview converter (Card 4). photo_sample, photo_see, identity,
# memory and the onboarding page all call `convert_to_thumbnail`; a second
# converter picking by filename suffix is what this replaced (L17).
#
# Backends, chosen by $PHOTO_PREVIEW_BACKEND:
#   pillow (default, every machine) — Pillow for stills (+ pillow-heif for
#          HEIC), ffmpeg for one video frame
#   sips   — macOS sips for stills, qlmanage for video. The fallback, kept
#          working and tested: the owner may choose it if Pillow does not
#          hold up on the Mac
# ⛔ The two backends build DIFFERENT pixels, and the vectors move with them:
# measured on 933 JPEGs, ~9% of DINOv2 crop pairs shift by more than the
# settled 0.02 identity margin. So the backend is recorded in the index meta
# and one index never mixes two backends (`meta_identity`).
BACKEND_ENV = "PHOTO_PREVIEW_BACKEND"
BACKENDS = ("pillow", "sips")
DEFAULT_BACKEND = "pillow"
# What an index with no recorded backend was built with: every index before
# Card 4 came from sips.
LEGACY_BACKEND = "sips"
PREVIEW_PX = 1280

# Why a preview was not made. Stable words: the CSV `error` column, the
# summary's per-cause count and the stage's exit all carry them.
CAUSE_UNSUPPORTED = "unsupported_type"
CAUSE_MISSING = "source_missing"
CAUSE_NO_HEIF = "no_heif_decoder (pip install pillow-heif)"
CAUSE_NO_FFMPEG = "no_ffmpeg (install ffmpeg, or pip install imageio-ffmpeg)"
CAUSE_NO_SIPS = "no_sips (macOS only)"
CAUSE_NO_QLMANAGE = "no_qlmanage (macOS only)"
CAUSE_DECODE = "decode_failed"
CAUSE_NO_FRAME = "no_video_frame"
CAUSE_TIMEOUT = "timeout"

# qlmanage picks its generator from the EXTENSION, so a video whose name
# lies needs a correctly-named copy; every video FileType is listed so a
# correctly-named 3GP/M4V/AVI is never copied for nothing.
FILETYPE_TO_EXT = {t: t.lower() for t in VIDEO_TYPES}
VIDEO_EXTENSIONS = set(FILETYPE_TO_EXT.values())


# The meta key every vector space carries (CLIP index, identity index, and
# the owner pack's stamps of both). ⛔ Read through `space_view` only: a meta
# written before Card 4 has no key, and every such vector came from sips.
PREVIEW_KEY = "preview_backend"


def space_view(meta, keys):
    """-> `meta` projected onto `keys`, a missing backend read as sips. The ONE
    reading of a stored space, for every guard that compares two of them."""
    if not meta:
        return meta
    view = {k: meta.get(k) for k in keys}
    if PREVIEW_KEY in keys and view[PREVIEW_KEY] is None:
        view[PREVIEW_KEY] = LEGACY_BACKEND
    return view


def backend_advice(stored, current):
    """Owner-facing lines for an index built with one preview backend and a
    run using the other."""
    return (f"These vectors were made from {stored} previews, and this run makes "
            f"{current} previews. The two give slightly different pictures, and "
            "the vectors move with them, so they are never mixed. Either rebuild "
            f"this index with --force, or set {BACKEND_ENV}={stored} to keep "
            "using it as it is.")


def preview_backend():
    import os
    name = (os.environ.get(BACKEND_ENV) or DEFAULT_BACKEND).strip().lower()
    if name not in BACKENDS:
        sys.exit(f"${BACKEND_ENV}={name!r} is not a preview backend "
                 f"(one of {', '.join(BACKENDS)})")
    return name


def ffmpeg_exe():
    """-> (path, route) or (None, None). A system ffmpeg on PATH wins; the
    binary pip ships inside imageio-ffmpeg is the fallback."""
    found = shutil.which("ffmpeg")
    if found:
        return found, "path"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe(), "imageio-ffmpeg"
    except Exception:                                    # noqa: BLE001
        return None, None


def heif_ready():
    try:
        import pillow_heif
    except ImportError:
        return False
    pillow_heif.register_heif_opener()
    return True


def _pillow_still(src, out, filetype):
    from PIL import Image, ImageOps
    # Content decides, not the type name: a HEIC-typed file holding JPEG
    # bytes opens without pillow-heif. The missing decoder is named only when
    # the open actually failed for want of it.
    heif = heif_ready()
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            scale = PREVIEW_PX / max(im.size)
            # int(), not round(): the size sips makes, so a switch of backend
            # never also moves a box by a pixel
            size = (max(1, int(im.width * scale)), max(1, int(im.height * scale)))
            im.resize(size, Image.LANCZOS).save(out, "JPEG", quality=90)
    except Exception:                                    # noqa: BLE001
        return None, (CAUSE_NO_HEIF if filetype == "HEIC" and not heif
                      else CAUSE_DECODE)
    return out, None


def video_duration(exe, src):
    """-> seconds, or None. Read from ffmpeg's own header dump: the
    imageio-ffmpeg route ships no ffprobe."""
    import re
    err = subprocess.run([exe, "-nostdin", "-i", str(src)], capture_output=True,
                         text=True, timeout=CONVERT_TIMEOUT).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def _ffmpeg_frame(src, out):
    """The MIDDLE frame. Measured on 63 real clips (57 S24U + 6 exemplar
    videos) against the first frame, 1 s in, and qlmanage's poster frame:
    the middle showed an animal in 60 (first 57, 1 s 54, poster 59), with
    the most detections and no black frame (the first frame had one)."""
    exe, _route = ffmpeg_exe()
    if exe is None:
        return None, CAUSE_NO_FFMPEG
    duration = video_duration(exe, src)
    seek = ["-ss", f"{duration / 2:.3f}"] if duration else []
    box = f"{PREVIEW_PX}:{PREVIEW_PX}"
    r = subprocess.run([exe, "-v", "error", "-nostdin", "-y", *seek, "-i", str(src),
                        "-frames:v", "1",
                        "-vf", f"scale={box}:force_original_aspect_ratio=decrease",
                        str(out)],
                       capture_output=True, timeout=CONVERT_TIMEOUT)
    if r.returncode != 0 or not out.exists():
        return None, CAUSE_NO_FRAME
    return out, None


def _sips_still(src, out):
    if shutil.which("sips") is None:
        return None, CAUSE_NO_SIPS
    r = subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(PREVIEW_PX),
                        str(src), "--out", str(out)],
                       capture_output=True, timeout=CONVERT_TIMEOUT)
    if r.returncode != 0 or not out.exists():
        return None, CAUSE_DECODE
    from photo_sample import bake_orientation
    return bake_orientation(out), None


def _qlmanage_frame(src, dst_dir, stem, filetype):
    if shutil.which("qlmanage") is None:
        return None, CAUSE_NO_QLMANAGE
    target = src
    if src.suffix.lower().lstrip(".") not in VIDEO_EXTENSIONS:
        target = dst_dir / f"{stem}_src.{FILETYPE_TO_EXT.get(filetype, 'mov')}"
        shutil.copyfile(src, target)
    r = subprocess.run(["qlmanage", "-t", "-s", str(PREVIEW_PX), "-o", str(dst_dir),
                        str(target)],
                       capture_output=True, timeout=CONVERT_TIMEOUT)
    thumb = dst_dir / f"{target.name}.png"
    if r.returncode != 0 or not thumb.exists():
        return None, CAUSE_NO_FRAME
    out = dst_dir / f"{stem}.png"
    thumb.rename(out)
    return out, None


def convert_to_thumbnail(src, dst_dir, stem, kind, filetype):
    """-> (path, None) for one viewable preview, or (None, cause).

    Stills become `<stem>.jpg`, a video's frame `<stem>.png` — photo_see names
    samples by that extension and photo_evidence checks the bytes match.
    Dispatches on `kind` (from the manifest's exiftool FileType), never the
    filename suffix — see the module docstring for why."""
    src, dst_dir = Path(src), Path(dst_dir)
    if kind not in ("image", "video"):
        return None, CAUSE_UNSUPPORTED
    if not src.is_file():
        return None, CAUSE_MISSING
    # L17 in every caller, not only embed: the sheet, see and sample hand over
    # the manifest's FileType, and exiftool calls a HEIC-named movie HEIC.
    real = photo_magic.sniff(src)
    if real and kind_of(real) and kind_of(real) != kind:
        kind, filetype = kind_of(real), real
    backend = preview_backend()
    try:
        if kind == "image":
            out = dst_dir / f"{stem}.jpg"
            if backend == "pillow":
                return _pillow_still(src, out, filetype)
            return _sips_still(src, out)
        if backend == "pillow":
            return _ffmpeg_frame(src, dst_dir / f"{stem}.png")
        return _qlmanage_frame(src, dst_dir, stem, filetype)
    except subprocess.TimeoutExpired:
        return None, CAUSE_TIMEOUT
    except Exception as exc:                             # noqa: BLE001
        return None, f"{CAUSE_DECODE}: {type(exc).__name__}"


def magic_filetypes(paths):
    """-> {path: FileType} from the files' own magic bytes (`photo_magic`), for
    the paths whose content is recognized; absent means "no opinion". Pure
    Python since Card 6: Unix `file` is absent from Windows PowerShell/cmd, and
    the check used to return nothing there without a word."""
    return photo_magic.filetypes(paths)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


CLIP_WEIGHT_FILES = ("open_clip_model.safetensors", "open_clip_pytorch_model.bin")


def clip_cached(open_clip, hub):
    """-> True when this model's weights are already in the Hugging Face cache.
    Modules are arguments so the rule is testable without the ML deps. A
    module that cannot answer means "not known to be installed": online."""
    if hub is None or not hasattr(open_clip, "get_pretrained_cfg"):
        return False
    cfg = open_clip.get_pretrained_cfg(MODEL_ID, PRETRAINED_TAG) or {}
    repo = (cfg.get("hf_hub") or "").strip("/")
    return bool(repo) and any(
        isinstance(hub.try_to_load_from_cache(repo, name), str)
        for name in CLIP_WEIGHT_FILES)


@contextlib.contextmanager
def hub_offline(constants, on):
    """FIX8 F8-9 — "offline once installed" (an owner decision). With the
    weights on disk the load still asked huggingface.co for a newer revision.
    ⛔ The module constant, not `os.environ`: huggingface_hub reads the env
    var once at import, and a caller may already have imported it (measured:
    setting HF_HUB_OFFLINE after import still made the call)."""
    if constants is None:
        yield
        return
    before = constants.HF_HUB_OFFLINE
    if on:
        constants.HF_HUB_OFFLINE = True
    try:
        yield
    finally:
        constants.HF_HUB_OFFLINE = before


def load_model(device_arg):
    """Lazy import: nothing outside this stage should pay torch's import cost
    or need it installed (golden_replay/fresh_owner_smoke/preclassify_cases
    exercise the PLAN stage and must stay green with no ML deps present)."""
    import torch
    import open_clip
    try:
        import huggingface_hub
        import huggingface_hub.constants as hub_constants
    except ImportError:
        huggingface_hub = hub_constants = None

    device = device_arg or ("mps" if torch.backends.mps.is_available() else "cpu")
    with hub_offline(hub_constants, clip_cached(open_clip, huggingface_hub)):
        model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL_ID, pretrained=PRETRAINED_TAG)
    model.eval().to(device)
    return torch, model, preprocess, device


def meta_identity(preprocess, embed_dim):
    fingerprint = hashlib.sha256(repr(preprocess).encode()).hexdigest()[:16]
    return {
        "model_id": MODEL_ID,
        "pretrained_tag": PRETRAINED_TAG,
        "embed_dim": embed_dim,
        "normalized": True,
        "preprocess_fingerprint": f"sha256:{fingerprint}",
        # Stamped by the same function the converter reads, so an index can
        # never claim one backend while holding the other's vectors.
        PREVIEW_KEY: preview_backend(),
    }


def load_existing(embed_dir):
    """-> (rows: list[dict] SourceFile-keyed order, vectors: np.ndarray|None,
    meta: dict|None). Empty/None when there is nothing to resume from."""
    import numpy as np

    csv_path, npy_path, meta_path = (embed_dir / n for n in
                                      ("embeddings.csv", "embeddings.npy", "embeddings-meta.json"))
    if not (csv_path.exists() and npy_path.exists() and meta_path.exists()):
        return [], None, None
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    vectors = np.load(npy_path)
    meta = json.loads(meta_path.read_text())
    if len(rows) != len(vectors):
        sys.exit(f"{embed_dir}: embeddings.csv has {len(rows)} rows but "
                 f"embeddings.npy has {len(vectors)} — index is corrupt, rebuild with --force")
    return rows, vectors, meta


def save_index(embed_dir, rows, vectors, meta):
    import numpy as np

    if len(rows) != len(vectors):
        sys.exit(f"{embed_dir}: refusing to write a desynchronized index — "
                 f"{len(rows)} rows vs {len(vectors)} vectors (internal bug)")
    embed_dir.mkdir(parents=True, exist_ok=True)
    tmp_npy = embed_dir / "embeddings.npy.tmp"
    arr = np.asarray(vectors, dtype=np.float32) if len(vectors) \
        else np.zeros((0, meta["embed_dim"]), dtype=np.float32)
    with open(tmp_npy, "wb") as f:  # np.save appends .npy to bare paths — use a file object instead
        np.save(f, arr)
    tmp_npy.replace(embed_dir / "embeddings.npy")
    with open(embed_dir / "embeddings.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    (embed_dir / "embeddings-meta.json").write_text(
        json.dumps(meta, indent=1, ensure_ascii=False))


def write_errors_log(errors_log, rows):
    """Regenerated from the index itself on every run that saves. It used to
    be rewritten only when the CURRENT run hit errors, so a clean re-run left
    a stale log naming files that no longer fail (or no longer exist)."""
    failures = [f"{r['SourceFile']}: {r.get('error') or 'failed'} ({r.get('kind')})"
                for r in rows if r.get("status") != "embedded"]
    if failures:
        errors_log.parent.mkdir(parents=True, exist_ok=True)
        errors_log.write_text("\n".join(failures) + "\n")
    elif errors_log.exists():
        errors_log.unlink()


def kind_of(row_filetype):
    if row_filetype in IMAGE_TYPES:
        return "image"
    if row_filetype in VIDEO_TYPES:
        return "video"
    return None


def embed_batch(torch, model, preprocess, device, images):
    from PIL import Image, ImageOps

    # exif_transpose again, even though convert_to_thumbnail already baked it:
    # an index built before that fix, or a thumbnail made on a machine without
    # PIL, still carries the tag, and a sideways vector is silently wrong.
    tensors = torch.stack([
        preprocess(ImageOps.exif_transpose(Image.open(p)).convert("RGB"))
        for p in images])
    with torch.no_grad():
        feats = model.encode_image(tensors.to(device))
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.cpu().numpy()


def reclaim_hit(pool, src, st):
    """-> (sha256, vector) of a pruned row holding the same CONTENT as src,
    or None. This is what stops a folder rename from re-embedding files that
    only moved. Hashing is gated on a size match against a pruned row first,
    so a run that pruned nothing hashes nothing and the fast resume — which
    only stat()s — stays fast."""
    candidates = pool.get(str(st.st_size))
    if not candidates:
        return None
    digest = sha256_file(src)
    for sha, vec in candidates:
        if sha == digest:
            return digest, vec
    return None


def run(manifest_rows, embed_dir, force, device_arg, errors_log):
    existing_rows, existing_vectors, existing_meta = ([], None, None) if force \
        else load_existing(embed_dir)

    rows, vectors, pruned, reclaim_pool = [], [], [], {}
    for i, r in enumerate(existing_rows):
        if Path(r["SourceFile"]).is_file():
            rows.append(r)
            vectors.append(existing_vectors[i])
            continue
        pruned.append(r)
        if r.get("status") == "embedded" and r.get("sha256") and r.get("size"):
            reclaim_pool.setdefault(r["size"], []).append((r["sha256"], existing_vectors[i]))
    row_index = {r["SourceFile"]: i for i, r in enumerate(rows)}
    by_source = {r["SourceFile"]: r for r in rows}

    pending, reclaimed = [], []
    skipped_ineligible = skipped_missing = 0
    for row in manifest_rows:
        filetype = row.get("FileType")
        kind = kind_of(filetype)
        if kind is None:
            skipped_ineligible += 1
            continue
        src = Path(row["SourceFile"])
        if not src.is_file():
            skipped_missing += 1
            continue
        st = src.stat()
        prow = by_source.get(row["SourceFile"])
        # CSV values are strings — compare as strings, so a truncated or
        # hand-edited blank `size` re-embeds the file instead of raising
        # int('') and aborting the whole resume.
        if prow and (prow.get("status") == "embedded"
                     and prow.get("size") == str(st.st_size)
                     and prow.get("mtime") == str(st.st_mtime)):
            continue
        hit = reclaim_hit(reclaim_pool, src, st)
        if hit is not None:
            reclaimed.append((row["SourceFile"], kind, st, hit))
            continue
        pending.append((row["SourceFile"], kind, filetype, st))

    # L17: exiftool's FileType is not trustworthy on its own, so magic bytes
    # overrule it — see the module docstring. Only `pending` is sniffed, never
    # every indexed row: that is what keeps a no-op resume at one stat() per
    # file instead of also spawning `file` over the whole index.
    magic_corrected = 0
    if pending:
        real = magic_filetypes([source_file for source_file, _, _, _ in pending])
        for i, (source_file, kind, filetype, st) in enumerate(pending):
            real_filetype = real.get(source_file)
            real_kind = kind_of(real_filetype) if real_filetype else None
            if real_kind and real_kind != kind:
                pending[i] = (source_file, real_kind, real_filetype, st)
                magic_corrected += 1

    unavailable = bool(pruned) and not rows and not pending and not reclaimed
    if unavailable:
        # Every indexed file gone AND nothing to do: the source is absent
        # (unmounted drive — see the project's two-drive pitfall), not empty.
        # Pruning here would destroy a good index; leave it untouched.
        print(f"{embed_dir}: all {len(pruned)} indexed files are missing and nothing "
              "is pending — treating the source as unavailable and leaving the index "
              "alone. Check the drive is mounted; use --force to rebuild deliberately.")
        rows, vectors, pruned = list(existing_rows), list(existing_vectors), []

    embedded = failed = 0
    failed_by_cause = {}

    def summarize(device=None):
        # already_embedded counts rows this run confirmed were still valid, so
        # the counters always add up to files_seen — on the unavailable-source
        # path nothing was confirmed, even though the index is kept intact.
        return {"files_seen": len(manifest_rows), "total_in_index": len(rows),
                "already_embedded": 0 if unavailable
                else len(rows) - embedded - failed - len(reclaimed),
                "newly_embedded": embedded, "reclaimed": len(reclaimed), "failed": failed,
                "skipped_ineligible": skipped_ineligible, "skipped_missing": skipped_missing,
                "pruned": len(pruned), "magic_corrected": magic_corrected,
                "failed_by_cause": dict(sorted(failed_by_cause.items())),
                "preview_backend": preview_backend(), "device": device}

    def record(source_file, kind, st, status, vec, error="", sha=None):
        """Every file that leaves this function — embedded OR failed — gets
        exactly one rows[] entry and one vectors[] entry at the same index.
        Skipping this for batch-level failures was the bug: it let `failed`
        files vanish from the index instead of being recorded as failed,
        desynchronizing .npy row i from .csv row i (VS-1b centroids and
        every later stage index vectors by that row position)."""
        if sha is None:
            sha = sha256_file(source_file) if status == "embedded" else ""
        rows_entry = {"SourceFile": source_file, "sha256": sha, "kind": kind,
                      "status": status, "size": st.st_size, "mtime": str(st.st_mtime),
                      "error": error}
        idx = row_index.get(source_file)
        if idx is None:
            row_index[source_file] = len(rows)
            rows.append(rows_entry)
            vectors.append(vec)
        else:
            rows[idx] = rows_entry
            vectors[idx] = vec

    for source_file, kind, st, (digest, vec) in reclaimed:
        record(source_file, kind, st, "embedded", vec, sha=digest)

    if not pending and existing_meta:
        if pruned or reclaimed:
            existing_meta["zero_vector_means_failed"] = True
            existing_meta["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            save_index(embed_dir, rows, vectors, existing_meta)
            write_errors_log(errors_log, rows)
        write_paperwork_scores(embed_dir, rows, vectors, existing_meta,
                               device_arg=device_arg)
        write_document_flags(embed_dir, rows, existing_meta, {},
                             device_arg=device_arg)
        summary = summarize()
        print(json.dumps(summary, indent=1))
        return summary

    torch, model, preprocess, device = load_model(device_arg)
    with torch.no_grad():
        embed_dim = model.visual.output_dim if hasattr(model.visual, "output_dim") \
            else model.encode_image(torch.zeros(1, 3, 224, 224).to(device)).shape[-1]
    meta = meta_identity(preprocess, embed_dim)
    stored = space_view(existing_meta, tuple(meta))
    if stored and stored[PREVIEW_KEY] != meta[PREVIEW_KEY]:
        sys.exit(f"{embed_dir}/embeddings-meta.json: "
                 + backend_advice(stored[PREVIEW_KEY], meta[PREVIEW_KEY]))
    if stored and stored != meta:
        sys.exit(
            f"embed/embeddings-meta.json in {embed_dir} was built with a "
            f"different model/preprocess ({existing_meta.get('model_id')}/"
            f"{existing_meta.get('pretrained_tag')}) than this run "
            f"({MODEL_ID}/{PRETRAINED_TAG}). Vectors from two models are not "
            "comparable — pass --force to rebuild the whole index.")
    # Set AFTER the identity check, which compares every key of `meta` against
    # the stored one: an index written before this flag existed must not
    # hard-fail as a model mismatch.
    meta["zero_vector_means_failed"] = True
    meta["created_at"] = (existing_meta.get("created_at") if existing_meta and not force
                          else None) or datetime.now().strftime("%Y-%m-%d %H:%M")

    doc_raw = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for i in range(0, len(pending), BATCH_SIZE):
            try:
                chunk = pending[i:i + BATCH_SIZE]
                thumbs, meta_for_thumb = [], []
                for source_file, kind, filetype, st in chunk:
                    out, cause = convert_to_thumbnail(source_file, tmp,
                                                      f"e{i}_{len(thumbs)}",
                                                      kind, filetype)
                    if out is None:
                        failed += 1
                        failed_by_cause[cause] = failed_by_cause.get(cause, 0) + 1
                        record(source_file, kind, st, "failed",
                               [0.0] * meta["embed_dim"], cause)
                        continue
                    thumbs.append(out)
                    meta_for_thumb.append((source_file, kind, st))
                    if kind == "image":
                        doc_raw[source_file] = document_bytes(out)
                if not thumbs:
                    continue
                try:
                    feats = embed_batch(torch, model, preprocess, device, thumbs)
                except Exception as exc:  # noqa: BLE001 — one bad file must not kill the run
                    for source_file, kind, st in meta_for_thumb:
                        failed += 1
                        failed_by_cause["embed_failed"] = \
                            failed_by_cause.get("embed_failed", 0) + 1
                        record(source_file, kind, st, "failed",
                               [0.0] * meta["embed_dim"], str(exc))
                    continue
                for (source_file, kind, st), vec in zip(meta_for_thumb, feats):
                    record(source_file, kind, st, "embedded", vec)
                    embedded += 1
                if (i // BATCH_SIZE) % 5 == 0:
                    meta["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    save_index(embed_dir, rows, vectors, meta)
                    print(f"  {min(i + BATCH_SIZE, len(pending))}/{len(pending)} "
                          f"({embedded} embedded, {failed} failed)")
            finally:
                # Thumbnails (and the corrected-extension source copies, which
                # are full-size) used to accumulate for the whole run.
                for leftover in tmp.iterdir():
                    if leftover.is_file():
                        leftover.unlink()

    meta["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_index(embed_dir, rows, vectors, meta)
    write_errors_log(errors_log, rows)
    write_paperwork_scores(embed_dir, rows, vectors, meta,
                           bundle=(torch, model, preprocess, device))
    write_document_flags(embed_dir, rows, meta, doc_raw,
                         bundle=(torch, model, preprocess, device))

    summary = summarize(device)
    print(json.dumps(summary, indent=1))
    return summary


# --index-root has no exiftool pass, so FileType is inferred from the
# extension — canonicalized to what exiftool would report, since kind_of()
# checks against photo_sample.IMAGE_TYPES/VIDEO_TYPES either way.
SUFFIX_TO_FILETYPE = {"JPG": "JPEG", "TIF": "TIFF", "M4V": "MP4"}


def run_index_root(root, force, device_arg):
    """Global index over an already-sorted tree: same per-file machinery,
    plus per-folder centroids for the recurrence census (VS-1b)."""
    import numpy as np

    root = Path(root).resolve()
    if not root.is_dir():
        sys.exit(f"{root}: not a directory — is the drive mounted?")
    index_dir = root / ".photo-embed-index"
    files = [p for p in root.rglob("*")
             if p.is_file() and not p.name.startswith(".")
             and p.suffix.upper().lstrip(".") not in ("AAE",)]
    manifest_rows = [{"SourceFile": str(p),
                      "FileType": SUFFIX_TO_FILETYPE.get(
                          p.suffix.upper().lstrip("."), p.suffix.upper().lstrip("."))}
                     for p in files]
    errors_log = index_dir / "embed-errors.log"
    summary = run(manifest_rows, index_dir, force, device_arg, errors_log)

    rows, vectors, _ = load_existing(index_dir)
    by_folder = {}
    for row, vec in zip(rows, vectors):
        if row["status"] != "embedded":
            continue
        folder = str(Path(row["SourceFile"]).parent)
        by_folder.setdefault(folder, []).append(vec)
    centroids = {folder: {"n": len(vecs),
                          "centroid": np.mean(vecs, axis=0).tolist()}
                 for folder, vecs in by_folder.items()}
    (index_dir / "folder-centroids.json").write_text(
        json.dumps(centroids, indent=1))
    print(f"global index: {len(rows)} files, {len(centroids)} folder centroids -> {index_dir}")
    return summary


def encode_scene_labels(embed_dir, profile, device_arg, force):
    """VS-2's text side: encode the zero-shot label set ONCE, here, where torch
    already lives, so `photo_see.py` stays numpy-only (the same dependency
    posture as photo_recurrence.py).

    One vector per CLASS: its prompts are encoded, L2-normalized, averaged and
    re-normalized — the standard prompt-ensembling that makes a class less
    dependent on one sentence's wording. The JSON records the exact prompt
    strings, so the .npy is re-derivable from a declared input instead of
    being an opaque blob, and it carries the same model identity fields as
    embeddings-meta.json: a text vector from another CLIP is not comparable to
    these image vectors, and photo_see refuses the pair rather than silently
    scoring every file slightly wrong."""
    import numpy as np

    sys.path.insert(0, str(Path(__file__).parent))
    import photo_see

    classes, source = photo_see.scene_label_set(profile)
    json_path, npy_path = embed_dir / "scene-labels.json", embed_dir / "scene-labels.npy"
    if json_path.exists() and not force:
        sys.exit(f"{json_path} already exists — pass --force to re-encode")

    import open_clip
    torch, model, preprocess, device = load_model(device_arg)
    tokenizer = open_clip.get_tokenizer(MODEL_ID)
    vectors = []
    with torch.no_grad():
        for name in classes:
            feats = model.encode_text(tokenizer(classes[name]).to(device))
            feats = feats / feats.norm(dim=-1, keepdim=True)
            mean = feats.mean(dim=0)
            vectors.append((mean / mean.norm()).cpu().numpy())
    arr = np.stack(vectors).astype(np.float32)

    embed_dir.mkdir(parents=True, exist_ok=True)
    with open(npy_path, "wb") as f:
        np.save(f, arr)
    meta = meta_identity(preprocess, arr.shape[1])
    meta.update({
        "kind": "scene-labels",
        "classes": list(classes),
        "prompts": {name: list(prompts) for name, prompts in classes.items()},
        "prompt_language": "en",
        "prompt_language_note": (
            f"{MODEL_ID}/{PRETRAINED_TAG} is an English-text CLIP; the class NAMES "
            "follow the owner's language (ONB-9) but the prompts are English "
            "because a zh-TW prompt scores noise against this text tower."),
        "label_set_source": source,
        "encoded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"{len(classes)} scene label vectors ({source}, {device}) -> {json_path}")
    return meta


# W2C / ADR 0005 — FINANCIAL OR OFFICIAL PAPERWORK, the narrow class.
#
# Scored HERE, where CLIP already lives, because `photo_plan` is stdlib-only
# and must stay so: the plan stage reads the number and never a vector.
#
# ⛔ NARROW ON PURPOSE, and NOT the onboarding filter's cut or prompt set
# (`photo_onboard_page.document_filter`). Onboarding hides anything
# document-shaped because a false positive there costs one thumbnail; routing
# MOVES a file, so a false positive costs an owner a holiday photo in the
# wrong place. The decoys below are the things ADR 0005 says must NOT move —
# a menu, a placard, a book page, a ticket, an infographic — named so a file
# that looks like one of them scores against it rather than against nothing.
#
# ⛔ Engine defaults, not pack data: the same stance as the onboarding filter,
# so a pack cannot switch the check off by emptying a list. English because
# ViT-B-32/laion2b is an English-text CLIP (see encode_scene_labels).
PAPERWORK_PROMPTS = [
    "a photo of a bill or an invoice", "a utility bill", "a bank statement",
    "a bankbook page", "a signed contract", "an official letter from a bank",
    "an official letter from a government office", "a tax notice",
    "a tax assessment document", "a screenshot of a tax notice",
    "a screenshot of a bank statement", "an insurance policy document",
]
PAPERWORK_DECOYS = {
    "menu": ["a restaurant menu", "a menu with prices"],
    "sign": ["a sign or placard", "a museum information panel"],
    "book": ["a page of a book", "a magazine page"],
    "ticket": ["an admission ticket with a QR code", "a boarding pass"],
    "chart": ["an infographic", "a chart or diagram"],
    "map": ["a map", "a screenshot of a map"],
    "label": ["a barcode label", "a product box with printed text"],
    "social": ["a screenshot of a social media post"],
}
PAPERWORK_SCORES_NAME = "paperwork-scores.json"
PAPERWORK_IDENTITY = ("model_id", "pretrained_tag", "preprocess_fingerprint")


def paperwork_text_vectors(torch, model, device):
    """-> (narrow prompts, one vector per ordinary class). Each ordinary class
    is a prompt ensemble, as `encode_scene_labels` builds them; the narrow
    side is every prompt on its own, so ONE sentence that fits is enough."""
    import numpy as np
    import open_clip
    import photo_see

    tokenizer = open_clip.get_tokenizer(MODEL_ID)

    def encode(prompts):
        with torch.no_grad():
            feats = model.encode_text(tokenizer(prompts).to(device))
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy()

    ordinary = {name: prompts for name, prompts
                in photo_see.DEFAULT_SCENE_LABELS.items() if name != "document"}
    ordinary.update(PAPERWORK_DECOYS)
    classes = []
    for prompts in ordinary.values():
        mean = encode(prompts).mean(axis=0)
        classes.append(mean / np.linalg.norm(mean))
    return encode(PAPERWORK_PROMPTS), np.stack(classes)


def write_paperwork_scores(embed_dir, rows, vectors, meta, bundle=None,
                           device_arg=None):
    """W2C — one score per embedded STILL: best paperwork prompt minus best
    ordinary class. -> the file's contents.

    ⛔ STILLS ONLY. A video is not a photograph of paperwork, and a video's one
    frame is a qlmanage poster the owner never chose (LL-PHO-131's stance on
    the IM ladder). A video gets no score, so it can never be moved.

    Re-scored only when the file is missing, was made by another model, used
    other prompts, or does not cover exactly the stills now indexed AT THEIR
    CURRENT CONTENT — so a no-op resume costs nothing, and a dump embedded
    before this existed gets its scores on the next run without a --force.
    ⛔ Content, not path: a file replaced in place is re-embedded under the
    same SourceFile, so a path-set check kept the old picture's score.
    """
    import numpy as np

    path = embed_dir / PAPERWORK_SCORES_NAME
    stills = [(i, r) for i, r in enumerate(rows)
              if r.get("kind") == "image" and r.get("status") == "embedded"]
    identity = {k: meta.get(k) for k in PAPERWORK_IDENTITY}
    content = {r["SourceFile"]: r.get("sha256") for _, r in stills}
    if path.exists():
        try:
            old = json.loads(path.read_text())
        except ValueError:
            old = {}
        if ({k: old.get(k) for k in PAPERWORK_IDENTITY} == identity
                and old.get("prompts") == PAPERWORK_PROMPTS
                and old.get("decoys") == PAPERWORK_DECOYS
                and old.get("sha256") == content):
            return old
    if bundle is None:
        bundle = load_model(device_arg)
    torch, model, _preprocess, device = bundle
    narrow, ordinary = paperwork_text_vectors(torch, model, device)
    scores = {}
    for i, r in stills:
        x = np.asarray(vectors[i], dtype=np.float32)
        scores[r["SourceFile"]] = round(
            float((narrow @ x).max() - (ordinary @ x).max()), 6)
    out = {**identity, "kind": "paperwork-scores",
           "prompts": PAPERWORK_PROMPTS, "decoys": PAPERWORK_DECOYS,
           "scored_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "sha256": content, "scores": scores}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    tmp.replace(path)
    return out


# F-jj (Card 6) — the U3-06 document check, run on every embedded STILL so
# photo_see / photo_sample can keep documents out of the vision pool. Owner
# ruling 20260924 (Q-a): ALL stills, camera photos included; a held photo is
# still copied and named, it just gets no vision look.
#
# ⛔ The SAME judgement and the SAME basis as the onboarding sheet
# (`photo_onboard_page.document_filter` on a THUMB_PX JPEG): DOCUMENT_MARGIN
# was calibrated on that 320 px thumbnail. Measured 20260924 on UAT02-02's 303
# stills: this index's own CLIP vectors at the same margin missed 7 of 37
# documents, so they are NOT reused; a 320 px copy of the embed preview agreed
# with the sheet's source-path thumbnail on 303 of 303 at ~7x less cost.
DOCUMENT_FLAGS_NAME = "document-flags.json"


def document_bytes(preview):
    """-> the THUMB_PX JPEG bytes the sheet's document check reads."""
    import photo_onboard_page as op
    return op._encode_pil(str(preview), op.THUMB_PX, op.THUMB_QUALITY)


def document_check_identity():
    import photo_onboard_page as op
    import photo_see
    return {"model_id": MODEL_ID, "pretrained_tag": PRETRAINED_TAG,
            "margin": op.DOCUMENT_MARGIN,
            "prompts": [p for c in op.DOCUMENT_CLASSES
                        for p in photo_see.DEFAULT_SCENE_LABELS[c]]
                       + op.DOCUMENT_EXTRA_PROMPTS,
            "thumb": [op.THUMB_PX, op.THUMB_QUALITY]}


def write_document_flags(embed_dir, rows, meta, fresh, bundle=None,
                         device_arg=None):
    """-> {SourceFile: True when it looks like a document} for every embedded
    still, written to DOCUMENT_FLAGS_NAME.

    `fresh` holds the 320 px bytes made from this run's previews. A still the
    file already answers for AT ITS CURRENT CONTENT keeps its flag; any other
    embedded still (an index built before this existed) gets its preview made
    again, once — so a resume needs no --force, like the paperwork scores."""
    path = embed_dir / DOCUMENT_FLAGS_NAME
    identity = document_check_identity()
    stills = {r["SourceFile"]: r for r in rows
              if r.get("kind") == "image" and r.get("status") == "embedded"}
    old = {}
    if path.exists():
        try:
            old = json.loads(path.read_text())
        except ValueError:
            old = {}
    keep = {}
    if old.get("identity") == identity:
        for src, flag in (old.get("document") or {}).items():
            if src in stills and src not in fresh and \
                    (old.get("sha256") or {}).get(src) == stills[src].get("sha256"):
                keep[src] = flag
    todo = [src for src in stills if src not in keep]
    if not todo and old.get("identity") == identity and \
            set(old.get("document") or {}) == set(stills):
        return old.get("document") or {}
    flags = dict(keep)
    if todo:
        import photo_onboard_page as op
        if bundle is None:
            bundle = load_model(device_arg)
        looks_like_document = op.document_filter(bundle=bundle)
        with tempfile.TemporaryDirectory() as tmp:
            for src in todo:
                raw = fresh.get(src)
                if raw is None:
                    out, _cause = convert_to_thumbnail(
                        src, Path(tmp), "d", "image", photo_magic.sniff(src))
                    if out is None:
                        continue                     # no flag: photo_see names it
                    raw = document_bytes(out)
                    out.unlink()
                flags[src] = bool(looks_like_document(raw))
    body = {"identity": identity, "kind": "still",
            "sha256": {src: stills[src].get("sha256") for src in flags},
            "document": flags,
            "documents": sum(1 for v in flags.values() if v)}
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(body, ensure_ascii=False, indent=1))
    tmp_path.replace(path)
    return flags


def load_document_flags(embed_dir):
    """-> {SourceFile: bool}, empty when the check never ran here."""
    try:
        return json.loads((Path(embed_dir) / DOCUMENT_FLAGS_NAME).read_text()
                          ).get("document") or {}
    except (OSError, ValueError):
        return {}


# B1: a run where previews failed used to exit 0 with every vector zero
# (368/368 on a machine with no sips) and name no cause.
EXIT_PREVIEWS_FAILED = 3


def exit_code(summary):
    """-> 0, or EXIT_PREVIEWS_FAILED after naming each cause and its count on
    stderr. The index is saved either way: failed rows stay zero and retry
    on the next run."""
    if not summary or not summary.get("failed"):
        return 0
    print(f"⛔ {summary['failed']} file(s) got no preview and no vector "
          f"(backend: {summary.get('preview_backend')}):", file=sys.stderr)
    for cause, n in (summary.get("failed_by_cause") or {}).items():
        print(f"   {n:>6}  {cause}", file=sys.stderr)
    return EXIT_PREVIEWS_FAILED


def exit_if_nothing_viewable(stage, selected, made, by_cause):
    """The viewing stages (photo_see, photo_sample --batch): exit
    EXIT_PREVIEWS_FAILED when files were picked for viewing and NOT ONE got a
    viewable sample. The agent would then have nothing to look at — the
    setting of the 2026-07-20 fabrication incident. A partial failure (an
    L17 movie among good stills) stays exit 0 and is named in the report.
    Call it after the report is written."""
    if not selected or made:
        return
    print(f"⛔ {stage}: {selected} file(s) were picked for viewing and NONE got a "
          "viewable sample, so there is nothing to look at. Do not label this "
          "batch. Causes:", file=sys.stderr)
    for cause, n in sorted(by_cause.items()):
        print(f"   {n:>6}  {cause}", file=sys.stderr)
    sys.exit(EXIT_PREVIEWS_FAILED)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir", nargs="?", help="a per-dump Working Files dir (reads manifest.csv)")
    ap.add_argument("--index-root", help="build/refresh the global index over a sorted tree instead")
    ap.add_argument("--force", action="store_true",
                    help="rebuild the index from scratch (required after a model change)")
    ap.add_argument("--scene-labels", action="store_true",
                    help="encode VS-2's zero-shot label set into embed/scene-labels.npy "
                         "and exit (the only place the CLIP text tower is used)")
    ap.add_argument("--profile", help="owner pack, for --scene-labels (ONB-10: the "
                                      "label set is owner data)")
    ap.add_argument("--device", choices=["mps", "cpu"], default=None)
    args = ap.parse_args()
    if (args.workdir is None) == (args.index_root is None):
        sys.exit("exactly one of workdir / --index-root is required")

    if args.scene_labels:
        import photo_profile
        root = Path(args.index_root).resolve() / ".photo-embed-index" if args.index_root \
            else Path(args.workdir).resolve() / "embed"
        encode_scene_labels(
            root,
            photo_profile.load_profile(explicit=args.profile,
                                       workdir=Path(args.workdir).resolve()
                                       if args.workdir else None),
            args.device, args.force)
        return

    if args.index_root:
        sys.exit(exit_code(run_index_root(args.index_root, args.force, args.device)))

    workdir = Path(args.workdir).resolve()
    manifest_path = workdir / "manifest.csv"
    if not manifest_path.exists():
        sys.exit(f"no manifest.csv in {workdir} — run photo_scan.py first")
    with open(manifest_path, newline="") as f:
        manifest_rows = list(csv.DictReader(f))
    embed_dir = workdir / "embed"
    sys.exit(exit_code(run(manifest_rows, embed_dir, args.force, args.device,
                           embed_dir / "embed-errors.log")))


if __name__ == "__main__":
    main()
