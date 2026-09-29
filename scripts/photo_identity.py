#!/usr/bin/env python3
"""VS-3b — a SECOND embedding index, for subject identity only.

Reads embed/embeddings.csv (so only files the CLIP stage indexed are
considered); writes into the work dir only:

  embed/identity.npy         float32 (N, D), L2-normalized, row i = row i of
                              identity.csv. A row with no detected subject is
                              a ZERO vector and is never comparable.
  embed/identity.csv         SourceFile, sha256, status, det_index,
                              det_count, kind, det_score, box, box_share
                              ⛔ ONE ROW PER DETECTED ANIMAL, not per file:
                              a frame holding two cats is two rows, two
                              crops and two vectors (R3a).
  embed/identity-meta.json   detector + embedding identity — the same guard
                              embeddings-meta.json is, and a separate one,
                              because these two spaces move independently
  embed/identity-errors.log  per-file failures

## Why a second index rather than a better first one

The CLIP index answers "what is this a picture of". It is trained to match an
image to a CAPTION, so its vector encodes `a tabby cat indoors` — the room as
much as the animal. That is the right signal for scene class, clustering and
recurrence, and it stays exactly as it is.

It is the wrong signal for "WHICH cat is this", and not by a little. Measured
on 23 owner-labelled frames with a leave-one-BATCH-out split (the frame-level
split is worthless here — see `tests/README.md`, burst frames seconds apart
sit in the bank and it reads 94% where the honest number is 67%):

    whole frame, CLIP     nearest neighbour correct 12/18, margin +0.008,
                          best impostor 0.822 vs a 0.85 bar
    animal crop, CLIP     12/18, margin +0.017, best impostor 0.777
    animal crop, DINOv2   15/15, margin +0.275, best impostor 0.414

Two changes, and BOTH were needed. Cropping alone moved the impostor down and
the accuracy not at all; it is the self-supervised embedding that separates
the subjects, and it only gets to do that once the room is out of the frame.

⚠️ The numbers above are a DIRECTION, not a calibration: 15 true queries and
5 impostors, one household, two cats. Thresholds are starting values.

## What a missing box means, and why it is not a failure

A file with no detected animal gets `status: no-subject` and a zero vector.
That is a POSITIVE statement — this file has nothing to identify — and it is
different from `failed`, which means the file could not be read. `match()`
must skip both, but only the second is worth logging as a problem: a dump is
mostly photographs of places, and treating each one as an error would bury
the real conversion failures in noise.

## Dependencies

Two model weights, both fetched on first use and cached by torch:
torchvision's COCO detector (~167 MB) and DINOv2 (~330 MB). Like open_clip in
the CLIP stage, they live in the repo `.venv/` and no stage outside this one
imports them — the plan-stage tests stay green with no ML deps present.
"""
import argparse
import csv
import hashlib
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import photo_embed

DETECTOR_ID = "fasterrcnn_resnet50_fpn_v2"
DETECTOR_WEIGHTS = "COCO_V1"
EMBED_ID = "dinov2_vitb14"
EMBED_SOURCE = "facebookresearch/dinov2"

# COCO class -> the subject kind vocabulary the registry already speaks. The
# engine holds no owner's animals; these are the classes the detector was
# trained on, and an owner's pack decides which of them it cares about.
COCO_TO_KIND = {"cat": "cat", "dog": "dog", "bird": "bird", "horse": "horse"}

# ⚠️ STARTING VALUES, NOT CALIBRATED — same posture as photo_subjects'
# thresholds, and for the same reason: they are written down so the gate has
# a width at all, and they move on a replay, not here.
MIN_DETECTION_SCORE = 0.5
# How much of the box's own width/height to add on each side. A tight COCO box
# clips ears and tail, and those are exactly the parts that differ between two
# animals of the same colour.
BOX_PAD = 0.12
# Below this share of the frame the crop is a few dozen pixels upscaled to 224
# and carries no identity. It is still indexed — the box is a true fact about
# the file — but `exemplar_quality()` refuses to let it become evidence.
MIN_BOX_SHARE_FOR_EXEMPLAR = 0.02

# Two boxes this much of the SMALLER one on top of each other are one animal
# detected twice, not two animals (U2-13). Containment, not IoU: the duplicate
# a detector actually emits is a NESTED box — a head or a flank inside the
# whole animal — and nesting drives IoU down while driving containment to 1.0,
# so an IoU gate cannot see the case it is needed for.
#
# ⭐ Measured, not chosen: over the 611 detection pairs in a 990-file dump the
# containment histogram is bimodal — 346 pairs in the 0.0-0.1 bin (animals
# standing apart) against 130 in 0.9-1.0 (one box inside another) — and at
# 0.05 resolution its floor is the 0.55-0.60 bin, 2 pairs wide. This is that
# floor's lower edge: at the valley, and on the conservative side of it, since
# suppressing too eagerly merges two real animals while suppressing too little
# only leaves today's behaviour in place.
#
# ⛔ MEASURE ON THE ENGINE'S OWN PATH BEFORE MOVING IT. Detection runs on the
# 1280px THUMBNAIL (`photo_embed.convert_to_thumbnail`, then
# `ImageOps.exif_transpose`), not the source file. Re-plotted from full-size
# originals the same dump gives a different distribution and a valley in the
# 0.4-0.5 bin — a threshold fitted to that is fitted to images this stage
# never sees.
DUPLICATE_CONTAINMENT = 0.55

CSV_FIELDS = ["SourceFile", "sha256", "status", "det_index", "det_count",
              "kind", "det_score", "box", "box_share", "error"]

# `det_index` is this detection's rank within its own file, 0 = highest score;
# `det_count` is how many animals that file holds, and is 0 on a file with
# none. ⛔ Both are counted AFTER duplicate boxes are suppressed — `det_count`
# is animals, not boxes (U2-13). Both are per-FILE facts repeated on every
# one of that file's rows, so
# a single row can answer "was this frame shared" without a second lookup —
# which is the question an exemplar has to answer before it may be evidence.

STATUS_OK = "identified"
STATUS_NO_SUBJECT = "no-subject"
STATUS_FAILED = "failed"

BATCH_SIZE = 16


def dinov2_source(hub_dir):
    """-> the repo string to hand torch.hub.load. FIX8 F8-9: with no `:ref`
    torch.hub asks github.com for the default branch on every load, cached or
    not; pinned to the cached `main` checkout it makes no call. Pinned only
    when that checkout and the weights are on disk, so a first install still
    downloads. ⛔ EMBED_SOURCE itself never changes: it is `model_source` in
    `meta_identity()`, so in SPACE_KEYS."""
    owner, repo = EMBED_SOURCE.split("/")
    hub = Path(hub_dir)
    if ((hub / f"{owner}_{repo}_main").is_dir()
            and (hub / "checkpoints" / f"{EMBED_ID}_pretrain.pth").exists()):
        return f"{EMBED_SOURCE}:main"
    return EMBED_SOURCE


def load_models(device_arg=None):
    """Lazy import, exactly as photo_embed.load_model is and for the same
    reason. -> (torch, detector, animal_label_ids, embedder, transform, device)"""
    import torch
    import torchvision.transforms as T
    from torchvision.models.detection import (fasterrcnn_resnet50_fpn_v2,
                                              FasterRCNN_ResNet50_FPN_V2_Weights)

    device = device_arg or ("mps" if torch.backends.mps.is_available() else "cpu")
    weights = FasterRCNN_ResNet50_FPN_V2_Weights.DEFAULT
    detector = fasterrcnn_resnet50_fpn_v2(weights=weights).eval().to(device)
    labels = {i: COCO_TO_KIND[c] for i, c in enumerate(weights.meta["categories"])
              if c in COCO_TO_KIND}
    embedder = torch.hub.load(dinov2_source(torch.hub.get_dir()), EMBED_ID,
                              verbose=False).eval().to(device)
    transform = T.Compose([
        T.Resize(256, interpolation=T.InterpolationMode.BICUBIC),
        T.CenterCrop(224),
        T.ToTensor(),
        T.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
    ])
    return torch, detector, labels, embedder, transform, device


def meta_identity(embed_dim):
    """The guard against comparing identity vectors across a model swap. Its
    own file and its own fingerprint: the CLIP index may be rebuilt without
    touching this one, and vice versa."""
    fingerprint = hashlib.sha256(
        f"{DETECTOR_ID}/{DETECTOR_WEIGHTS}/{EMBED_ID}/{BOX_PAD}/"
        f"{MIN_DETECTION_SCORE}/{DUPLICATE_CONTAINMENT}".encode()).hexdigest()[:16]
    return {
        "space": "subject-identity",
        "detector_id": DETECTOR_ID,
        "detector_weights": DETECTOR_WEIGHTS,
        "model_id": EMBED_ID,
        "model_source": EMBED_SOURCE,
        "embed_dim": embed_dim,
        "normalized": True,
        "box_pad": BOX_PAD,
        "min_detection_score": MIN_DETECTION_SCORE,
        # ⛔ Space-defining, like min_detection_score and for the same reason:
        # it changes WHICH detections exist, so an index built without it
        # holds rows a deduped index would never have written and the two
        # cannot be compared row for row.
        "duplicate_containment": DUPLICATE_CONTAINMENT,
        "pipeline_fingerprint": f"sha256:{fingerprint}",
        "zero_vector_means_no_subject": True,
        # The crops are cut from the preview, so its backend defines the space.
        photo_embed.PREVIEW_KEY: photo_embed.preview_backend(),
    }


# The keys that DEFINE the identity space, taken from meta_identity() itself
# rather than pasted, so a new field cannot be added in one place and forgotten
# in the other. `identity-meta.json` also carries created_at/updated_at, which
# say when the index was built and nothing about whether two sets of vectors
# are comparable — including them made every freshly built index differ from
# every pack, so the identity space could never be used with a mature pack.
SPACE_KEYS = tuple(meta_identity(0))


def space_of(meta):
    """-> just the identity-defining fields of an identity-index meta."""
    return photo_embed.space_view(meta, SPACE_KEYS)


def containment(box_a, box_b):
    """-> the boxes' intersection as a share of the SMALLER box's area, 0..1.

    1.0 means one box lies entirely inside the other. ⛔ Deliberately not IoU:
    IoU divides by the UNION, so a small box nested in a large one scores low
    on IoU however completely it is contained — and nested is the shape a
    duplicate detection actually takes.
    """
    x0 = max(box_a[0], box_b[0])
    y0 = max(box_a[1], box_b[1])
    x1 = min(box_a[2], box_b[2])
    y1 = min(box_a[3], box_b[3])
    overlap = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    smaller = min(max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1]),
                  max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1]))
    return overlap / smaller if smaller > 0 else 0.0


def dedupe_boxes(found):
    """Drop the boxes that are a second detection of an animal already kept.

    Takes and returns `[(kind, score, box), ...]`, and REQUIRES the input to
    be sorted by score descending — the survivor of a duplicate pair is the
    higher-scoring box, which is only the first one if the caller sorted.

    ⭐ Why this exists (U2-13). `det_count` is what `exemplar_quality()` reads
    to refuse a shared frame, and it counted BOXES. A detector that fired
    twice on one animal therefore made a perfectly good single-subject frame
    unusable as identity evidence: measured on one real dump, of 226
    multi-detection files 133 are reduced and 89 hold exactly one animal — 86
    of those 89 then pass this module's own `exemplar_quality()`, the other 3
    still refused by the box-share floor. In the confirmed subjects of that
    run it cost the most-photographed animal half of its identity evidence.
    Nothing warned, because from the index's point of view a duplicate box
    and a second animal are the same row.

    ⛔ CLASS-AGNOSTIC, and that is the whole point. The detector already runs
    NMS internally, but PER CLASS, so the duplicates that reach here are the
    ones it structurally cannot remove: the same animal returned once as
    `cat` and once as `dog`. Of the 180 pairs in that dump that overlap past
    DUPLICATE_CONTAINMENT, 53 are cross-kind. A per-kind gate here would
    re-implement the half that is already done and skip the half that is
    missing.

    ⚠️ Greedy against KEPT boxes only, in score order, exactly as NMS is. A
    box suppressed as a duplicate cannot itself suppress a third one — one
    animal's spurious box must not chain into deleting a real neighbour.

    ⛔ RAW boxes, and never the `box` column of `identity.csv`. That column
    holds the PADDED box (`run()` writes `pad_box(raw, ...)`), and padding
    adds BOX_PAD on every side precisely to take in the ears and tail — so it
    inflates every overlap and makes boxes touch that the detector kept
    apart. Deduplicating the stored geometry instead of this one, on the same
    dump at the same threshold, collapses 112 of 226 multi-detection files to
    a single animal where the engine collapses 89; the acceptance frame reads
    containment 0.83 there and 0.67 here. ⛔ So DUPLICATE_CONTAINMENT is
    calibrated to RAW boxes and cannot be carried over to padded ones — a
    convenience check written against `identity.csv` will over-report, and it
    will look like a measurement rather than an artefact.

    ⭐ Raw is also the right question to ask: padding is a crop-quality device
    that says how much context to embed, never a claim about where the animal
    is. Whether two animals are one is a fact about the detections.
    """
    kept = []
    for detection in found:
        box = detection[2]
        if all(containment(box, other[2]) <= DUPLICATE_CONTAINMENT
               for other in kept):
            kept.append(detection)
    return kept


def animal_boxes(torch, detector, labels, device, image):
    """-> [(kind, score, (x0, y0, x1, y1)), ...] for EVERY animal in the
    image scoring at least MIN_DETECTION_SCORE, highest score first, with
    duplicate boxes on one animal removed (`dedupe_boxes`). Empty when the
    frame holds no animal.

    ⛔ Every detection, not the best one (R3a). Keeping only the top box made
    a frame with two cats structurally indistinguishable from a frame with
    one: the second animal left no trace anywhere in the index, so nothing
    downstream could warn that a confirmed exemplar was a shared frame. That
    is D-24 exactly — 3 of 5 exemplars an owner confirmed in UAT01 were
    wrong, two of them because the frame held both cats and the page had no
    way to say so.

    ⛔ Ordered by score, never by area. A cat asleep in the corner of a room
    photo is a subject; the sofa it is on is not, and area would rank the
    sofa first every time an animal is detected inside a larger one. Order
    matters now that it names `det_index`: index 0 has to mean the same thing
    on every row of every run.
    """
    import numpy as np

    tensor = torch.from_numpy(np.array(image)).permute(2, 0, 1).float() / 255.0
    with torch.no_grad():
        out = detector([tensor.to(device)])[0]
    found = []
    for score, label, box in zip(out["scores"], out["labels"], out["boxes"]):
        score = float(score)
        kind = labels.get(int(label))
        if kind is None or score < MIN_DETECTION_SCORE:
            continue
        found.append((kind, score, tuple(float(v) for v in box)))
    found.sort(key=lambda d: -d[1])
    return dedupe_boxes(found)


def pad_box(box, width, height):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    return (max(0.0, x0 - w * BOX_PAD), max(0.0, y0 - h * BOX_PAD),
            min(float(width), x1 + w * BOX_PAD), min(float(height), y1 + h * BOX_PAD))


def box_share(box, width, height):
    x0, y0, x1, y1 = box
    area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return round(area / float(width * height), 4) if width and height else 0.0


def exemplar_quality(row):
    """May this file's identity vector become EVIDENCE for a subject?

    -> (ok: bool, why: str). Separate from whether the row is indexed at all,
    and deliberately stricter.

    ⭐ An exemplar has to answer *which one is this*, not *is this the right
    animal*. Three of the seven frames an owner confirmed for one subject in
    the 20260821 trial were vet-visit close-ups of a PAW being held — every
    one of them a true picture of that animal, and none of them evidence of
    anything. Dropping those three took nearest-neighbour accuracy from 16/18
    to 15/15. The owner's answer was not wrong; the question the round asked
    ("is this the right animal") is simply not the question the exemplar store
    needs answered, and nothing downstream could tell the difference.

    A frame refused here can still be SHOWN in a round, still be picked, and
    still name its group. It just never enters the bank the matcher scores
    against.

    ⛔ A SHARED frame — `det_count` above 1 — is refused (R3b). It is still
    SHOWN, can still be picked, and still names its group: two subjects in one
    frame is two names to LOG, never a frame to refuse (owner decision,
    20260904). What it may not do is enter the bank, and the reason is that
    the exemplar store is keyed on `vec_ref`, the file's content sha — one
    photograph, one key, one subject. There is no key under which a frame
    holding two cats could bank a clean vector for each, so whichever animal
    scored higher would silently become BOTH of them. That is D-24: 3 of the 5
    exemplars an owner confirmed in UAT01 were wrong, two of them exactly so.
    ⚠️ The refusal is a HOLDING position, not the end state. Making one photo
    bank one crop per animal needs a composite key (`<sha>#<det_index>`) and
    is its own card; until then the safe half is taken, and the page says so
    at decision time rather than after the fact (LL-PHO-136).
    """
    if row.get("status") != STATUS_OK:
        return False, f"no identity vector ({row.get('status')})"
    try:
        share = float(row.get("box_share") or 0.0)
    except (TypeError, ValueError):
        return False, "box_share is not readable"
    try:
        count = int(row.get("det_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 1:
        return False, (f"this frame holds {count} animals, and the exemplar "
                       "store keys on the file — one photograph cannot bank a "
                       "separate vector for each of them")
    if share < MIN_BOX_SHARE_FOR_EXEMPLAR:
        return False, (f"the subject fills {share:.1%} of the frame, under "
                       f"{MIN_BOX_SHARE_FOR_EXEMPLAR:.0%} — too little of it is "
                       "in the picture to identify it by")
    return True, "ok"


def load_existing(embed_dir):
    import numpy as np

    csv_path = embed_dir / "identity.csv"
    npy_path = embed_dir / "identity.npy"
    meta_path = embed_dir / "identity-meta.json"
    if not (csv_path.exists() and npy_path.exists() and meta_path.exists()):
        return [], None, None
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        legacy = "det_index" not in (reader.fieldnames or [])
        rows = list(reader)
    vectors = np.load(npy_path)
    meta = json.loads(meta_path.read_text())
    if legacy:
        # An index written before R3a holds the highest-scoring box only, so
        # it cannot say whether any frame was shared. It is still READABLE —
        # every vector in it is a DINOv2 crop and comparable to a new one —
        # and a consumer that hard-exited here would take photo_see and
        # photo_memory down on an owner's existing work dir. So it is filled
        # in and FLAGGED; `run()` re-detects the whole dump on its next pass.
        # ⛔ det_count 1 would be a claim this index cannot support. A legacy
        # row knows an animal was found, never how many were there.
        for r in rows:
            r["det_index"] = "0"
            r["det_count"] = ""
        meta["legacy_single_detection"] = True
    if len(rows) != len(vectors):
        sys.exit(f"{embed_dir}: identity.csv has {len(rows)} rows but identity.npy "
                 f"has {len(vectors)} — index is corrupt, rebuild with --force")
    return rows, vectors, meta


def save_index(embed_dir, rows, vectors, meta):
    import numpy as np

    if len(rows) != len(vectors):
        sys.exit(f"{embed_dir}: refusing to write a desynchronized identity index — "
                 f"{len(rows)} rows vs {len(vectors)} vectors (internal bug)")
    embed_dir.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(vectors, dtype=np.float32) if len(vectors) \
        else np.zeros((0, meta["embed_dim"]), dtype=np.float32)
    tmp = embed_dir / "identity.npy.tmp"
    with open(tmp, "wb") as f:      # np.save appends .npy to bare paths
        np.save(f, arr)
    tmp.replace(embed_dir / "identity.npy")
    with open(embed_dir / "identity.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    (embed_dir / "identity-meta.json").write_text(
        json.dumps(meta, indent=1, ensure_ascii=False))


def load_detections(embed_dir, pack=None):
    """-> ({SourceFile: [(row, vector), ...] in det_index order}, meta).

    The full R3a shape: every animal the detector found, one entry each. This
    is what a page that offers a CROP to the owner reads (R3b). A file with
    no animal appears with its single `no-subject` row, so a caller can still
    tell "not indexed" (absent) from "nothing in it" (present, zero vector).
    """
    import numpy as np

    rows, vectors, meta = load_existing(Path(embed_dir))
    if meta is None:
        return {}, None
    by_file = {}
    for i, r in enumerate(rows):
        by_file.setdefault(r["SourceFile"], []).append((r, vectors[i]))
    for entries in by_file.values():
        entries.sort(key=lambda e: int(e[0].get("det_index") or 0))
    return apply_marks(by_file, not_animal_marks(embed_dir, pack)), space_of(meta)


def not_animal_marks(embed_dir, pack=None):
    """Q8-c — the crops marked "not a real animal" for this dump: the
    `not_animals` list of its INDEX, so the freeze hash covers them and every
    write goes through `open_for_change` (D-I16). [] for a dump with no index
    (the non-indexed flow has no page that can mark one).

    Card 9 — `pack` is the stage's own owner pack (a resolved pack, its
    folder, or its profile path; None = collection.json / $PHOTO_PROFILE), so
    a pack bound by --profile ALONE reaches this reader too."""
    workdir = Path(embed_dir).parent
    if not (workdir / "index-pointer.json").is_file():
        return []
    import contextlib
    import io
    import photo_index
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            loaded = photo_index.load(workdir, getattr(pack, "dir", pack))
    except (SystemExit, photo_index.Refused):
        loaded = None
    if not loaded:
        # ⚠️ Said, never silent: a caller that passed no pack, on a dump bound
        # ONLY by --profile, would count every marked crop as an animal again.
        if str(workdir) not in _MARKS_UNREAD:
            _MARKS_UNREAD.add(str(workdir))
            print(f"  ⚠️ {workdir.name}: this dump's index could not be opened "
                  "without the owner pack, so its not-a-real-animal marks are "
                  "NOT applied — marked crops count as animals. Bind the pack "
                  "with collection.json or $PHOTO_PROFILE (this reader was "
                  "given no pack).", file=sys.stderr)
        return []
    return list(loaded[2].get("not_animals") or [])


_MARKS_UNREAD = set()


def apply_marks(by_file, marks):
    """Q8-c — drop each marked detection, recount `det_count` on the rest, and
    let the first UNMARKED detection be the file's primary. A frame whose
    every detection is marked holds no animal: one `no-subject` row, zero
    vector. A mark whose box no longer matches (a re-detection renumbered the
    file) is STALE: reported once, never applied to a different animal.
    ⛔ Read-time only; `identity.csv` on disk is never rewritten."""
    if not marks:
        return by_file
    import numpy as np
    marks = [m for m in marks if m.get("sha256")]
    keyed = {(m.get("sha256"), int(m.get("det_index") or 0)): m for m in marks}
    shas = {m.get("sha256") for m in marks}
    out = {}
    for source, entries in by_file.items():
        if not any(r.get("sha256") in shas for r, _v in entries):
            out[source] = entries
            continue
        keep, dropped = [], 0
        for row, vec in entries:
            mark = keyed.get((row.get("sha256"), int(row.get("det_index") or 0)))
            if mark is not None and row.get("status") == STATUS_OK:
                if mark.get("box") in (None, "", row.get("box")):
                    dropped += 1
                    continue
                print(f"  ⚠️ a not-an-animal mark on {Path(source).name} animal "
                      f"{int(row.get('det_index') or 0) + 1} is stale (the photo "
                      "was detected again) — ignored", file=sys.stderr)
            keep.append((row, vec))
        if not dropped:
            out[source] = entries
            continue
        real = sum(1 for r, _v in keep if r.get("status") == STATUS_OK)
        if real:
            out[source] = [(dict(r, det_count=real), v) for r, v in keep]
        else:
            first, vec = entries[0]
            out[source] = [(dict(first, status=STATUS_NO_SUBJECT, det_count=0,
                                 det_index=0, kind="", box=""),
                            np.zeros_like(vec))]
    return out


def load_index(embed_dir, pack=None):
    """-> ({SourceFile: (row, vector)}, meta) for a consumer. Empty when the
    stage has never run, which every pre-VS-3b work dir is: the caller must
    treat an absent identity index as "unknown", never as "no subject".

    ⚠️ ONE entry per file — the PRIMARY detection, `det_index` 0 — even now
    that a file may hold several. That is deliberate and it is not the end
    state: every consumer of this function (photo_see's X_identity matrix,
    photo_subjects' scoring, photo_memory's exemplar promotion) is built on
    "row i of the matrix is file i", and widening that is R3b's work, done
    where the owner can see which crop they are answering about.
    ⛔ So R3a on its own does NOT close D-24. It makes the second animal
    exist in the index; it does not yet make the owner able to tell the two
    apart, and a caller that reads only this function still sees exactly what
    it saw before. Use `load_detections()` when the second animal matters.
    """
    by_file, space = load_detections(embed_dir, pack)
    if space is None:
        return {}, None
    # Q8-c: the primary is the first detection LEFT once the owner's and the
    # agent's "not a real animal" marks are applied — det_index 0 otherwise.
    # Projected, exactly as photo_see does for the CLIP index: the consumer
    # compares this against a pack's stored space, and a timestamp is not part
    # of what makes two sets of crops comparable.
    return {source: entries[0] for source, entries in by_file.items()
            if entries}, space


def eligible_rows(embed_rows):
    """The CLIP index's successfully embedded rows, in its own order. Order is
    inherited deliberately — two indexes over one dump that disagree about row
    order are a debugging problem nobody needs."""
    return [r for r in embed_rows if r.get("status") == "embedded"]


def run(workdir, force=False, device_arg=None, limit=None):
    import numpy as np
    from PIL import Image, ImageOps

    workdir = Path(workdir)
    embed_dir = workdir / "embed"
    embed_rows, _vectors, embed_meta = photo_embed.load_existing(embed_dir)
    if embed_meta is None:
        sys.exit(f"{embed_dir}: no CLIP index to build an identity index over — "
                 "run photo_embed.py first")

    wanted = eligible_rows(embed_rows)
    if limit:
        wanted = wanted[:limit]

    # embeddings.csv carries `kind` but not exiftool's FileType, and
    # convert_to_thumbnail needs both: `kind` picks sips vs qlmanage, while
    # FileType only matters for the rare mismatched-extension video that needs
    # a corrected-extension copy. Read it from the manifest rather than passing
    # `kind` twice — that would silently send every such video to a `.mov` copy.
    filetypes = {}
    manifest = workdir / "manifest.csv"
    if manifest.exists():
        with open(manifest, newline="") as f:
            filetypes = {r["SourceFile"]: r.get("FileType")
                         for r in csv.DictReader(f)}

    existing_rows, existing_vectors, existing_meta = ([], None, None) if force \
        else load_existing(embed_dir)
    # ⛔ A file's detections are resumed together or not at all. Keeping a
    # partial set would let a run that stopped after the first of two cats
    # look, on the next pass, exactly like a frame that only ever held one —
    # which is the very distinction R3a exists to preserve. `flush()` is only
    # ever called on a file boundary for the same reason.
    done = {}
    if existing_meta is not None:
        for i, r in enumerate(existing_rows):
            done.setdefault(r["SourceFile"], []).append((r, existing_vectors[i]))
        for entries in done.values():
            entries.sort(key=lambda e: int(e[0].get("det_index") or 0))

    legacy = bool(existing_meta and existing_meta.get("legacy_single_detection"))
    if legacy:
        # Not a corruption and not an error — it is an index that predates
        # multi-detection and therefore under-reports every shared frame. It
        # is rebuilt automatically rather than left to an owner to notice,
        # and announced, because re-detecting a whole dump is not free.
        print(f"  {embed_dir}/identity.csv predates multi-detection (R3a); "
              f"re-detecting all {len(wanted)} indexed files")
        done = {}

    pending = [r for r in wanted
               if r["SourceFile"] not in done
               or done[r["SourceFile"]][0][0].get("sha256") != r.get("sha256")]

    rows, vectors = [], []
    # ⚠️ These count ROWS, and a row is now a detection, not a file. A dump of
    # 100 photographs in which one frame holds two cats reports 101. Files are
    # counted separately below so the two numbers can never be read as one.
    counts = {STATUS_OK: 0, STATUS_NO_SUBJECT: 0, STATUS_FAILED: 0}
    kinds = {}
    files_with_subject = 0
    shared_frames = 0

    def keep(row, vec):
        rows.append(row)
        vectors.append(vec)
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        if row["status"] == STATUS_OK:
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1

    def keep_file(entries):
        """Every row a file owns, together. -> None"""
        nonlocal files_with_subject, shared_frames
        for row, vec in entries:
            keep(row, vec)
        count = int(entries[0][0].get("det_count") or 0) if entries else 0
        if count:
            files_with_subject += 1
        if count > 1:
            shared_frames += 1

    def summarize(newly_processed, device):
        by_cause = {}
        for r in rows:
            if r["status"] == STATUS_FAILED:
                cause = r.get("error") or "unknown"
                by_cause[cause] = by_cause.get(cause, 0) + 1
        return {"files_considered": len(wanted),
                "newly_processed": newly_processed,
                "files_with_subject": files_with_subject,
                "shared_frames": shared_frames,
                "detections": counts[STATUS_OK],
                **counts, "kinds": kinds,
                "failed_by_cause": dict(sorted(by_cause.items())),
                "preview_backend": photo_embed.preview_backend(), "device": device}

    if not pending:
        for r in wanted:
            if r["SourceFile"] in done:
                keep_file(done[r["SourceFile"]])
        if existing_meta is not None:
            save_index(embed_dir, rows, vectors, existing_meta)
        summary = summarize(0, None)
        print(json.dumps(summary, indent=1, ensure_ascii=False))
        return summary

    torch, detector, labels, embedder, transform, device = load_models(device_arg)
    with torch.no_grad():
        embed_dim = int(embedder(torch.zeros(1, 3, 224, 224).to(device)).shape[-1])
    meta = meta_identity(embed_dim)
    key = photo_embed.PREVIEW_KEY
    stored = photo_embed.space_view(existing_meta, tuple(meta))
    if stored and stored[key] != meta[key]:
        sys.exit(f"{embed_dir}/identity-meta.json: "
                 + photo_embed.backend_advice(stored[key], meta[key]))
    if stored and stored != meta:
        sys.exit(
            f"embed/identity-meta.json in {embed_dir} was built with a different "
            f"detector/embedding ({existing_meta.get('detector_id')}/"
            f"{existing_meta.get('model_id')}) than this run ({DETECTOR_ID}/"
            f"{EMBED_ID}). Identity vectors from two pipelines are not comparable "
            "— pass --force to rebuild the whole index.")
    meta["created_at"] = (existing_meta.get("created_at") if existing_meta and not force
                          else None) or datetime.now().strftime("%Y-%m-%d %H:%M")

    zero = [0.0] * embed_dim
    pending_set = {r["SourceFile"] for r in pending}
    processed = 0

    def embed_crops(crops):
        tensors = torch.stack([transform(c) for c in crops])
        with torch.no_grad():
            feats = embedder(tensors.to(device))
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pending_index = {r["SourceFile"]: r for r in pending}
        buffer_rows, buffer_crops = [], []

        def flush():
            """⛔ Call only on a file boundary — see the resume note above."""
            nonlocal processed, files_with_subject, shared_frames
            if not buffer_crops:
                return
            seen_files = {r["SourceFile"] for r in buffer_rows}
            multi = {r["SourceFile"] for r in buffer_rows
                     if int(r.get("det_count") or 0) > 1}
            try:
                feats = embed_crops(buffer_crops)
            except Exception as exc:                      # noqa: BLE001
                # The crops failed, not the detection. The boxes stay on the
                # rows: they are a true fact about the file and a later run
                # resumes from them, and `exemplar_quality` refuses a failed
                # row anyway.
                for row in buffer_rows:
                    row.update(status=STATUS_FAILED, error=str(exc))
                    keep(row, zero)
            else:
                for row, vec in zip(buffer_rows, feats):
                    keep(row, vec)
                    processed += 1
            files_with_subject += len(seen_files)
            shared_frames += len(multi)
            buffer_rows.clear()
            buffer_crops.clear()

        for source in wanted:
            path = source["SourceFile"]
            if path not in pending_set:
                if path in done:
                    keep_file(done[path])
                continue
            manifest_row = pending_index[path]
            base = {"SourceFile": path, "sha256": manifest_row.get("sha256", ""),
                    "det_index": 0, "det_count": 0,
                    "kind": "", "det_score": "", "box": "", "box_share": "",
                    "error": ""}
            src = Path(path)
            if not src.is_file():
                keep({**base, "status": STATUS_FAILED, "error": "source is missing"}, zero)
                continue
            thumb, cause = photo_embed.convert_to_thumbnail(
                path, tmp, f"i{len(rows)}", manifest_row.get("kind"),
                filetypes.get(path))
            if thumb is None:
                keep({**base, "status": STATUS_FAILED, "error": cause}, zero)
                continue
            try:
                image = ImageOps.exif_transpose(Image.open(thumb)).convert("RGB")
                found = animal_boxes(torch, detector, labels, device, image)
            except Exception as exc:                      # noqa: BLE001
                keep({**base, "status": STATUS_FAILED, "error": str(exc)}, zero)
                continue
            finally:
                Path(thumb).unlink(missing_ok=True)
            if not found:
                # Not an error: most photographs contain no animal at all.
                # ⛔ Exactly ONE row, with a zero vector — photo_subjects reads
                # a zero row as "nothing to identify here", and a file that
                # emitted none at all would read as "never indexed" instead.
                keep_file([({**base, "status": STATUS_NO_SUBJECT}, zero)])
                continue
            for det_index, (kind, score, raw) in enumerate(found):
                padded = pad_box(raw, image.width, image.height)
                buffer_rows.append({**base, "status": STATUS_OK, "kind": kind,
                                    "det_index": det_index,
                                    "det_count": len(found),
                                    "det_score": round(score, 4),
                                    "box": ",".join(f"{v:.1f}" for v in padded),
                                    "box_share": box_share(padded, image.width,
                                                           image.height)})
                buffer_crops.append(image.crop(padded))
            # ⛔ The check sits OUTSIDE the detection loop: a file's crops enter
            # and leave the buffer together, so a batch never splits one frame's
            # animals across two saved states.
            if len(buffer_crops) >= BATCH_SIZE:
                flush()
                meta["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                save_index(embed_dir, rows, vectors, meta)
                print(f"  {files_with_subject + counts[STATUS_NO_SUBJECT]}"
                      f"/{len(wanted)} files "
                      f"({counts[STATUS_OK]} detections in {files_with_subject} "
                      f"of them, {shared_frames} shared, "
                      f"{counts[STATUS_NO_SUBJECT]} without, "
                      f"{counts[STATUS_FAILED]} failed)")
        flush()

    meta["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_index(embed_dir, rows, vectors, meta)
    failures = [f"{r['SourceFile']}: {r.get('error')}" for r in rows
                if r["status"] == STATUS_FAILED]
    log = embed_dir / "identity-errors.log"
    if failures:
        log.write_text("\n".join(failures) + "\n")
    elif log.exists():
        log.unlink()

    summary = summarize(processed, device)
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir")
    ap.add_argument("--force", action="store_true",
                    help="rebuild the whole identity index")
    ap.add_argument("--device", help="mps / cpu (default: mps when available)")
    ap.add_argument("--limit", type=int,
                    help="process only the first N indexed files (trials)")
    args = ap.parse_args()
    sys.exit(photo_embed.exit_code(
        run(args.workdir, force=args.force, device_arg=args.device, limit=args.limit)))


if __name__ == "__main__":
    main()
