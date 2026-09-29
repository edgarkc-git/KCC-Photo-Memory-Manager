#!/usr/bin/env python3
"""photo-classify Stage 3a — pick sample images for one batch and pre-classify
by pure EXIF rules, so the vision step only looks at what needs eyes.

Reads manifest.csv + batches.json; writes into the work dir only:
  classify/batch-NN/samples/       viewable JPEGs (sips) / video thumbs (qlmanage)
  classify/batch-NN/sample-report.json

EXIF pre-classification (SPEC v0.3, no vision needed):
  screenshot     a Screenshot_* style filename, or PNG at exactly one of the
                 owner's screen sizes (profile.screen_dims) — both with no
                 camera tags
  screen_record  the same two signals on a video
  no_exif        no Make/Model + no EXIF date + no GPS. Named for the
                 evidence, not for a guess: this rule cannot tell an AI
                 image from an EXIF-stripped forwarded photo or from a
                 capture tool's output, and it used to be called ai_gen
  shared         Make is not in profile.own_camera_makes (default: Apple only)
                 or random XXXX9999 name with no camera tags (LINE/AirDrop
                 saves) — D-B: sort with own captures, but skip GPS clustering
  own            everything else (the profile's own device(s))

Usage:
  python3 photo_sample.py "<Working Files>/202605__" --batch 1 [--max-samples 12]
  python3 photo_sample.py "<Working Files>/202605__" --no-date   (sweep no-date-files.csv)
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from photo_cluster import parse_date, parse_gps  # noqa: E402
import photo_profile  # noqa: E402

# formal sampling stage (R2/P2.2): 10% of a GPS leg's own-camera files, 5% for
# no-GPS ("to-be-ID") batches, clamped to [min_samples, max_samples] — or all
# of them if fewer exist than the floor. Overridable per user via profile.json
# sampling{gps_pct,no_gps_pct,min_samples,max_samples}; --max-samples still
# wins if passed explicitly (ambiguous-batch escalation, manual overrides).
DEFAULT_SAMPLING = {"gps_pct": 0.10, "no_gps_pct": 0.05,
                    "min_samples": 10, "max_samples": 40}


def sample_budget(total_own, has_gps, profile):
    cfg = {**DEFAULT_SAMPLING, **photo_profile.get(profile, "sampling", default={})}
    pct = cfg["gps_pct"] if has_gps else cfg["no_gps_pct"]
    n = round(total_own * pct)
    n = max(cfg["min_samples"], min(cfg["max_samples"], n))
    return min(n, total_own)

# Screen sizes belong to the OWNER's devices, so the real list lives in their
# pack (photo-profile.json -> screen_dims, proposed by photo_census.py). This
# fallback is deliberately the single size the engine has always shipped: a
# generous built-in table is worse than none, because 1080x1920 is both a
# phone screen and the commonest video resolution there is — on one real dump
# it would have called 326 ordinary videos screen recordings.
# Deliberately left in the flat, model-less shape: it is the ENGINE's
# fallback, and a device model on it would claim a device the owner never
# confirmed. Pairing (G-1) is for the sizes the OWNER accepted.
DEFAULT_SCREEN_DIMS = [["1170", "2532"]]                       # iPhone 12

# Android names screenshots and screen recordings; iOS does not (an iPhone
# screenshot is IMG_1234.PNG like any photo). So the two rules are
# complementary, not alternatives — and the filename is the one that survives
# CROPPING, which the dimension rule cannot: of 4 real Android screenshots in
# this archive, 2 had been cropped away from any screen size.
# i18n-guard:allow-begin — locale detection data, not user-facing output.
# The words phones and capture tools in various locales put at the start of a
# screenshot filename. Matching INPUT, so the list grows with the locales and
# the tools the engine can read, never with the language it writes.
#
# The second group is G-3 (ONB-12 extension): a PC/tablet capture tool that
# writes its OWN name rather than the platform's. The platform names are
# already covered by the first group — macOS and Windows both start theirs
# with "Screenshot"/"Screen Shot". `capture` is anchored to what those tools
# actually emit (`Capture.PNG`, `Capture (2).png`, `Capture_01.png`) because
# the bare word also begins ordinary camera-app filenames.
SCREENSHOT_NAME = re.compile(
    r"^(screen[ _-]?shot|screen[ _-]?recording|screenrecord|scrn|"
    r"螢幕擷取|螢幕錄製|螢幕快照|截圖|截屏|스크린샷|"
    r"snipaste|screenclip|擷取畫面|"
    r"capture(?:[ _-]?\d+|\s?\(\d+\))?\.)", re.I)
# i18n-guard:allow-end

# T2 (A34a) — the filenames instant messengers write. These are PRODUCT facts,
# public and the same for every owner, so they ship: an owner should not have to
# discover that LINE prefixes its albums. Same category as SCREENSHOT_NAME
# above — matching INPUT, so the list grows with the apps the engine can read.
# i18n-guard:allow-begin — messenger filename signatures, not user-facing output.
DEFAULT_IM_NAME_PREFIXES = ["LINE_", "IMG-", "KakaoTalk_", "Screenshot_"]
IM_NAME_ANCHORS = {
    # prefix     -> extra shape the rest of the name must have, or None for
    #               "the prefix alone is enough". `IMG-` is anchored because
    #               bare IMG- is far too close to an ordinary camera name; the
    #               WhatsApp form carries a date and a WA serial.
    "IMG-": re.compile(r"^IMG-\d{8}-WA\d+", re.I),
}
# i18n-guard:allow-end

# T3 (A34a) — the compression ladder an IM app re-encodes a photo to. ⛔ SHIPS
# EMPTY ON PURPOSE. The values that work are MEASURED FROM ONE OWNER'S CORPUS
# ({1280, 1477, 1478, 1705, 1706} for this project's), and a long edge is not a
# product constant: bake one in and every owner whose messenger uses a different
# ladder gets files moved on evidence that was never about them. Empty means T3
# is simply off until the pack supplies `im_long_edges`, which costs only a
# larger review inbox — the failure direction that asks rather than guesses.
DEFAULT_IM_LONG_EDGES = []

RANDOM_NAME = re.compile(r"^[A-Z]{4}\d{4}\.", re.I)
IMAGE_TYPES = {"HEIC", "JPEG", "PNG", "TIFF", "WEBP", "GIF"}
# ⛔ THE video predicate — by exiftool FileType, never by extension (D13 renames
# the extension at copy precisely because it cannot be trusted: measured, 14
# still-named files are really video and 361 video-named files are really
# stills). It was {MOV, MP4} and silently treated 3GP, M4V and AVI as stills;
# M14 (owner ruling 20260922) names 3GP explicitly and measured it 8/8, and a
# real Duration corroborates FileType on 1,511 of 1,511 videos.
# ⚠️ Five stages read this: photo_census (screen-size exclusion), photo_embed
# (previews), photo_index (the VIDEO TIMEZONE date rule, and kind), and
# photo_sample. Widening it was probed before landing: golden identical and
# every one of those suites green.
# `photo_embed.VIDEO_EXTENSIONS` is derived from this set and only names the
# extensions qlmanage needs no renamed copy for (the sips backend).
VIDEO_TYPES = {"MOV", "MP4", "M4V", "AVI", "3GP"}


DEFAULT_OWN_CAMERA_MAKES = ["Apple"]


def screen_devices(profile=None):
    """-> [(model or None, (w, h))] — the owner's screen sizes, each paired
    with the device it belongs to (G-1). Values are stringified because a
    manifest row is all strings.

    TWO shapes are read, on purpose. The paired one is what the census now
    proposes and what can be audited a year later ("whose phone was
    1170x2532?"):

        "screen_dims": [{"model": "Apple iPhone 12", "dims": [1170, 2532]}]

    The flat one is every pack written before G-1, and it keeps working
    unchanged with model None — a size that MOVES FILES must never stop
    matching because the pack was not migrated."""
    entries = photo_profile.get(profile, "screen_dims",
                                default=DEFAULT_SCREEN_DIMS)
    out = []
    for e in entries or []:
        dims, model = (e.get("dims"), e.get("model")) if isinstance(e, dict) \
            else (e, None)
        if not isinstance(dims, (list, tuple)) or len(dims) != 2:
            # Stopped, not skipped: this key MOVES FILES, so an entry nobody
            # can parse would make screenshot detection silently blind. Same
            # posture (and same shape) as photo_profile's pack failures.
            sys.exit(f"screen_dims entry {e!r} is neither [w, h] nor "
                     '{"model": ..., "dims": [w, h]} — this key moves files, '
                     "so it is not guessed at")
        out.append((model, tuple(str(v) for v in dims)))
    return out


def screen_dims(profile=None):
    """-> {(w, h)} in both orientations, from the owner's pack when it has
    them. Values are stringified because a manifest row is all strings."""
    out = set()
    for _model, (w, h) in screen_devices(profile):
        out |= {(w, h), (h, w)}
    return out


def im_name_prefixes(profile=None):
    """-> the messenger filename signatures to test, pack first."""
    return photo_profile.get(profile, "im_name_prefixes",
                             default=DEFAULT_IM_NAME_PREFIXES) or []


def im_long_edges(profile=None):
    """-> {int} the IM compression ladder from the pack, empty if unset."""
    vals = photo_profile.get(profile, "im_long_edges",
                             default=DEFAULT_IM_LONG_EDGES) or []
    out = set()
    for v in vals:
        try:
            out.add(int(v))
        except (TypeError, ValueError):
            # Stopped, not skipped: this key MOVES FILES. Same reasoning as
            # screen_devices() — a ladder nobody can parse would silently
            # switch T3 off and look like an owner with no shared photos.
            sys.exit(f"pack: im_long_edges has an unreadable value {v!r}")
    return out


def long_edge(row):
    try:
        return max(int(row.get("ImageWidth")), int(row.get("ImageHeight")))
    except (TypeError, ValueError):
        return None


def im_named(filename, prefixes):
    for pre in prefixes:
        if not filename.upper().startswith(pre.upper()):
            continue
        anchor = IM_NAME_ANCHORS.get(pre)
        if anchor is None or anchor.match(filename):
            return True
    return False


# The tiers of the Non-EXIF Classification SPEC (v1.2, D-N1..D-N15), in the
# order they are evaluated. Order is load-bearing and signed: T1 runs before
# T2/T3 because a screenshot forwarded through LINE satisfies both, and the
# owner's policy is that the screenshot verdict wins.
#
# A tier is the EVIDENCE; the class is the DESTINATION. They are returned
# separately because several tiers share a class -- T2 and T3 are both
# `shared`, T4 and T5 are both `no_exif` -- and collapsing them would throw
# away the only record of why a file was routed, which is exactly what the
# review page has to show the owner.
TIERS = {
    "T0": "junk",            # AppleDouble sidecar / MacOS resource fork
    "T1": "screenshot",      # or screen_record on a video
    "T2": "shared",          # messenger filename
    "T3": "shared",          # messenger compression ladder
    "T4": "no_exif",         # video, no date -- joins the dump's event (A38)
    "T5": "no_exif",         # undecidable from metadata -- this is VI's input
}


def tier_of(row, profile=None):
    """-> (tier, class) for one manifest row. Camera-bearing rows get no tier.

    The tiers apply to NO-CAMERA rows only. A file that carries a Make or a
    Model is a photograph from a device, and the pre-EXIF rules below (own /
    shared by make) decide it -- a tier would be claiming to know better than
    the camera that wrote the file.
    """
    name = row.get("FileName", "")
    ftype = row.get("FileType", "-")
    make, model = row.get("Make", "-"), row.get("Model", "-")
    no_camera = make in ("-", "") and model in ("-", "")
    dims = (row.get("ImageWidth", "-"), row.get("ImageHeight", "-"))
    is_video = ftype in VIDEO_TYPES

    # T0 -- sidecars. These are excluded at scan (photo_scan.py, since
    # bd1a3b2 on 2026-07-30), so no row from a manifest scanned after that
    # date can reach here. The tier exists for the manifests written BEFORE
    # it, which are still on disk and still replayed.
    if name.startswith("._") or ftype == "MacOS":
        return "T0", "junk"

    if not no_camera:
        return None, None

    # T1 -- a screen capture. Two complementary signals, and they must stay
    # complementary: the dimension rule is EXACT-match only (D-N8, signed --
    # a capture is by definition the screen's own resolution), and the
    # filename rule is the one that survives cropping, which the dimension
    # rule cannot.
    if SCREENSHOT_NAME.match(name) or dims in screen_dims(profile):
        return "T1", "screen_record" if is_video else "screenshot"

    # T2 -- the messenger wrote the filename. Ground truth.
    if im_named(name, im_name_prefixes(profile)):
        return "T2", "shared"

    # T3 -- the messenger's compression ladder.
    #
    # ⛔ STILLS ONLY, and that guard is measured, not cautious. An IM app
    # re-encodes a PHOTO to the ladder; a video it leaves alone. Without the
    # guard the ladder catches 168 ordinary videos in this corpus, every one
    # of them at exactly 720x1280 or 1280x720 -- 720p, which collides with a
    # ladder value of 1280 for reasons that have nothing to do with a
    # messenger. The SPEC's "0 false positives" was measured against
    # camera-bearing rows only, and these carry no camera, so they were never
    # in that test set. No messenger-named video exists in the corpus, so the
    # guard costs nothing.
    if not is_video and long_edge(row) in im_long_edges(profile):
        return "T3", "shared"

    dated = parse_date(row) is not None
    # T4 -- a video with no date of its own. Treated exactly like a non-EXIF
    # photo: it joins the event of the dump it sits in (SPEC section 6, A38).
    if is_video and not dated:
        return "T4", "no_exif"

    # T5 -- undecidable from metadata. This is the set VI reads, and the only
    # tier that is never allowed to run unattended.
    if not dated and parse_gps(row) is None:
        return "T5", "no_exif"
    return None, None


def own_makes(profile=None):
    """-> the EXIF `Make` values that count as the owner's own device, lower
    cased. ⛔ ONE definition, called by every stage that asks the question —
    `photo_sample` splits own from shared on it and `photo_where` filters a
    batch's GPS trail by it, and a second copy is how those two came to
    disagree. A hardcoded `Make == "Apple"` in the naming stage made `[where]`
    silently dead for every non-Apple owner: 0 of 13 batches nameable on a
    Samsung dump, at exit 0, with 58% of the files losing a place name
    (D-07). Same shape as the single GPS predicate (A24).
    """
    return {m.lower() for m in
            photo_profile.get(profile, "own_camera_makes",
                              default=DEFAULT_OWN_CAMERA_MAKES)}


def is_own_make(make, profile=None):
    """-> was this row shot on one of the owner's own devices?

    ⚠️ An EMPTY `own_camera_makes` answers NO for every named camera, and that
    is the shipped template's value. It is deliberate and it is not a second
    D-07: the census proposes the list at onboarding, the checkpoint says out
    loud which makes are missing from the pack (`pack_gap`), and a run whose
    pack never got one has a pack problem, not a naming problem. What must
    never happen again is a stage deciding this from a constant of its own.
    """
    return bool(make) and make.lower() in own_makes(profile)


def preclassify(row, profile=None):
    """-> the class this row routes to. The tiers decide the no-camera rows;
    everything below them is the make-based split, which needs a camera."""
    _, cls = tier_of(row, profile)
    if cls is not None:
        return cls
    make = row.get("Make", "-")
    no_camera = make in ("-", "") and row.get("Model", "-") in ("-", "")
    if make not in ("-", "") and not is_own_make(make, profile):
        return "shared"
    if no_camera and RANDOM_NAME.match(row.get("FileName", "")):
        return "shared"
    return "own"


def bake_orientation(path):
    """Rotate the pixels to match the EXIF Orientation tag, then drop the tag.

    A phone stores a rotated capture as sensor-order pixels plus a tag, and
    `sips` copies both through unchanged. Everything downstream reads the
    pixels and not the tag: CLIP, the COCO detector, the review page's `<img>`,
    and the vision model looking at the sample. Leaving the tag set means a
    third of a typical dump is embedded, clustered and shown sideways.

    Best-effort on purpose — PIL is not a hard dependency of this stage, and a
    machine without it gets the old behaviour rather than no thumbnail.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return path
    try:
        with Image.open(path) as im:
            if im.getexif().get(274, 1) in (1, None):
                return path
            ImageOps.exif_transpose(im).save(path, quality=90)
    except Exception:                                     # noqa: BLE001
        pass
    return path


def spread(items, k):
    if len(items) <= k:
        return items
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir")
    ap.add_argument("--batch", type=int)
    ap.add_argument("--no-date", action="store_true",
                    help="pre-classify no-date-files.csv instead of a batch (no sampling)")
    ap.add_argument("--max-samples", type=int, default=None,
                    help="override the formal 10%%/5%% sampling formula "
                         "(e.g. escalate an ambiguous batch to a full look)")
    args = ap.parse_args()
    # Here, not at the top: photo_embed imports this module's type sets.
    import photo_embed
    workdir = Path(args.workdir).resolve()
    # workdir matters: without it an owner bound through collection.json is
    # invisible unless photo_run happened to export PHOTO_PROFILE, and the
    # sampling budget silently reverts to the generic camera list
    profile = photo_profile.load_profile(workdir=workdir)

    if args.no_date:
        # D-08 — guarded, the same way `photo_plan.write_no_date_plan()` and
        # `photo_run` already guard this exact file. A dump where every file
        # carried a usable date never has one, so a CLEAN dump was the case
        # that crashed here, with a raw traceback, on the sweep the
        # photo-classify SKILL tells every owner to run once per folder.
        #
        # ⛔ Exit 0 and the SAME JSON shape, not a bare sentence. This command
        # has a documented output contract and an agent reads it; replacing
        # the object with prose on the empty path would trade a traceback for
        # an unparseable success. Zero is a real answer, and `note` says why
        # it is zero rather than leaving the reader to guess.
        path = workdir / "no-date-files.csv"
        if not path.exists():
            print(json.dumps({"no_date_files": 0, "preclass": {},
                              "note": f"no {path.name} in {workdir} — "
                                      "nothing to sweep"},
                             ensure_ascii=False, indent=1))
            return
        rows = list(csv.DictReader(open(path, newline="")))
        counts = {}
        for r in rows:
            counts[preclassify(r, profile)] = counts.get(preclassify(r, profile), 0) + 1
        print(json.dumps({"no_date_files": len(rows), "preclass": counts},
                         ensure_ascii=False, indent=1))
        return

    if args.batch is None:
        sys.exit("--batch N required (or --no-date)")
    batches = json.loads((workdir / "batches.json").read_text())
    batch = next((b for b in batches["batches"] if b["batch"] == args.batch), None)
    if batch is None:
        sys.exit(f"batch {args.batch} not in batches.json")

    rows = []
    with open(workdir / "manifest.csv", newline="") as f:
        every_row = list(csv.DictReader(f))
    for row in every_row:
        dt = parse_date(row)
        if dt and batch["from"] <= dt.date().isoformat() <= batch["to"]:
            row["_dt"] = dt
            rows.append(row)
    # F-jj (Card 6) — photo_see's rule, the census's sizes: a no-camera still
    # at a screen size the owner has not answered is never a sample.
    import photo_census
    held_sizes = photo_census.pending_screen_sizes(every_row, profile)
    document_flags = photo_embed.load_document_flags(workdir / "embed")

    def held_from_vision(r):
        return (photo_census.at_pending_screen_size(r, held_sizes)
                or bool(document_flags.get(r["SourceFile"])))

    counts, per_day = {}, {}
    for r in rows:
        r["_class"] = preclassify(r, profile)
        counts[r["_class"]] = counts.get(r["_class"], 0) + 1
        per_day.setdefault(r["_dt"].date().isoformat(), []).append(r)

    out_dir = workdir / "classify" / f"batch-{args.batch:02d}"
    smp_dir = out_dir / "samples"
    smp_dir.mkdir(parents=True, exist_ok=True)

    total_own = sum(1 for r in rows if r["_class"] == "own")
    # "shared" files (forwarded/AirDrop, not the profile's own device) are
    # still real, viewable photos — if a batch has zero "own" files, sample
    # from "shared" instead so classification always has a real evidence
    # entry point. Without this fallback, agents had nothing to view and
    # some fabricated observations instead (2026-07-20 incident).
    sample_class = "own" if total_own > 0 else "shared"
    total_pool = total_own if total_own > 0 else sum(
        1 for r in rows if r["_class"] == "shared")
    has_gps = any(parse_gps(r) for r in rows)
    budget = args.max_samples if args.max_samples is not None else \
        sample_budget(total_pool, has_gps, profile)
    samples, failed = [], []
    for day in sorted(per_day):
        own = sorted((r for r in per_day[day] if r["_class"] == sample_class
                      and not held_from_vision(r)),
                     key=lambda r: r["_dt"])
        stills = [r for r in own if r.get("FileType") in IMAGE_TYPES] or own
        if not stills:
            continue
        k = max(1, round(budget * len(own) / max(total_pool, 1)))
        for r in spread(stills, min(k, budget)):
            stem = f"{day}_{r['_dt'].strftime('%H%M')}_{Path(r['SourceFile']).stem}"
            made, cause = photo_embed.convert_to_thumbnail(
                r["SourceFile"], smp_dir, stem,
                photo_embed.kind_of(r.get("FileType")), r.get("FileType"))
            (samples if made else failed).append({
                "sample": made.name if made else None,
                **({} if made else {"cause": cause}),
                "source": r["SourceFile"],
                "time": r["_dt"].strftime("%Y-%m-%d %H:%M"),
                "gps": r.get("GPSPosition", "-"),
            })

    report = {
        "batch": args.batch, "label": batch["label"],
        "from": batch["from"], "to": batch["to"], "files": len(rows),
        "preclass": counts,
        "per_day": {d: len(v) for d, v in sorted(per_day.items())},
        "samples": samples,
        "held_from_vision": {
            "pending_screen_size": sum(
                1 for r in rows if r["_class"] == sample_class
                and photo_census.at_pending_screen_size(r, held_sizes)),
            "document": sum(
                1 for r in rows if r["_class"] == sample_class
                and not photo_census.at_pending_screen_size(r, held_sizes)
                and document_flags.get(r["SourceFile"]))},
        "sample_failures": failed,
        "samples_dir": str(smp_dir),
    }
    (out_dir / "sample-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    by_cause = {}
    for f in failed:
        by_cause[f["cause"]] = by_cause.get(f["cause"], 0) + 1
    photo_embed.exit_if_nothing_viewable("photo_sample", len(samples) + len(failed),
                                         len(samples), by_cause)


if __name__ == "__main__":
    main()
