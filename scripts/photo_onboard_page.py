#!/usr/bin/env python3
"""Onboarding checkpoint as a page — the census's proposals, with the photos.

`photo_census.py` measures four facts off the collection and proposes each one
for confirmation. Its output is a table of numbers, and two of the four
questions cannot honestly be answered from a number:

  screen_dims     the census ranks candidates by file count. On a measured
                  collection the CORRECT size (an iPhone 12's 1170x2532, 6
                  files) ranked SIXTH, under three resized-forward sizes with
                  33, 32 and 19 files. Accepting the top row would have filed
                  33 ordinary photos as screenshots. Nothing about the numbers
                  says which is which; one glance at the pictures does.
  home_locations  "photographed on many separate days, including after dark"
                  is also a hotel on a two-week trip. One measured collection
                  proposed a national-park hotel as a residence, correctly by
                  its own rule. The owner recognises their own front door.

So this renders the same proposals with exemplar photographs beside them, and
**pre-selects nothing**. An owner who clicks straight through submits an empty
answer rather than the top-ranked guess — which is the point: on both defects
above the top-ranked guess is the wrong one.

⛔ Photographs, not a browser. `sheet` writes the same exemplars as files and
the same questions as text, because a page needs a browser to read and an
artifact host to send back, and this is the FIRST checkpoint of the FIRST run
— without a second surface the product is unreachable at its own front door
for a terminal-only session, a server install, or an agent-driven run. It is
NOT `--prefill` widened: that refusal stands, and what moves is the evidence,
not the answer.

⛔ It also shows what the census WITHHELD. A place that missed a home bar
carries no proposal and used to reach the printed report alone; on a measured
dump an owner's third residence — photographed like a visitor, few days, one
evening — appeared on the page not at all, so it was never registered and
never asked the follow-up every proposed row gets. A surface that prints only
what it proposes cannot be told apart from one that found nothing.

  render, then open the file or publish it as an artifact:
  (render and sheet need the repo's .venv — see the U3-06 note below.
  <venv python> is <repo>/.venv/bin/python3 on macOS and Linux,
  <repo>\\.venv\\Scripts\\python.exe on Windows)
    <venv python> photo_onboard_page.py render <work dir> [...] \\
        --out page.html [--coords-out coords.txt] [--profile <pack>]

  or, with no browser and nowhere to publish, the same questions as a text
  file with the same photographs written beside it as image files:
    <venv python> photo_onboard_page.py sheet <work dir> [...] \\
        --out-dir onboard/

  read the answers back — off the page the owner submitted, off the sheet
  they answered, or off the lines they copied out of the page:
    python3 photo_onboard_page.py apply <page.html|answers.txt> --pack <pack>

  and, only if asked, write them into the pack:
    python3 photo_onboard_page.py apply answers.txt --write-pack <pack> \\
        [--coords-in coords.txt]

  give each home and named place of a pack written before ids existed its
  fixed id (D-I15; a dry run unless --go):
    python3 photo_onboard_page.py backfill-ids <pack> [--go]

⛔ Writing is OPT-IN and stays that way. With no `--write-pack` this stage
reports and writes nothing, exactly as it always has — a proposal the owner
confirmed is still the owner's to place, which is `photo_census`'s stance too.
What changed is only that the owner can now ask for it; answering does not
imply it. A write is all-or-nothing and refuses rather than overwrite anything
the owner already chose.

⛔ Registering a HOME needs `--coords-in`, the file `render`/`sheet` wrote with
`--coords-out`. A home is registered by COORDINATE — that is how its name is
withheld — and neither the sheet nor the page carries one, deliberately. This
stage has no work dirs and never calls `build_data()`, so it cannot re-derive
one; without that file every home row is refused BY NAME rather than dropped.

⛔ Coordinates. A home row's coordinate is the one thing on this page that
must not reach a service the owner did not choose (Operational Rule 3). The
default is `--no-coords`: rows carry a letter, their evidence counts and their
photographs, and the coordinates go to `--coords-out` on local disk instead.
Pass `--with-coords` only when the page is staying on the owner's machine.

⛔ And that is ALL `--no-coords` withholds (U3-06). It keeps the NUMBER off
the page; a photograph can still show where a place is — a street sign, the
view from a window, a letter on a table. What this stage leaves out besides is
every evidence frame that LOOKS LIKE A DOCUMENT (a ticket, a receipt, a form,
an ID card): on real dumps those carried a name, an ID number, a unit number
and a phone number. The check needs CLIP, so `render` and `sheet` run under the
repo's `.venv`; without it they refuse rather than embed unchecked
photographs, and `--unfiltered-evidence` is the explicit, admitted opt-out.
"""

import argparse
import base64
import hashlib
import csv
import io
import json
import os
import re
import shutil
import pathlib
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import photo_census  # noqa: E402
import photo_cluster  # noqa: E402
import photo_embed  # noqa: E402
import photo_platform  # noqa: E402
import photo_profile  # noqa: E402
from photo_cluster import (AWAY_KM_DEFAULT, gps_point,  # noqa: E402
                           haversine_km)

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None

MARK_DATA = "__" + "DATA" + "__"
MARK_TPL = "__" + "TEMPLATE_B64" + "__"

TEMPLATE = os.path.join(os.path.dirname(SCRIPTS), "templates",
                        "onboarding-page.html")

# How many photographs stand as evidence for one proposal. Six is what fits a
# row at a size where a screenshot is still recognisable as one, and it is a
# sample, never the whole set — the counts beside it say how many there are.
EXEMPLARS = 6
THUMB_PX = 320
THUMB_QUALITY = 72

# A home row's photographs are chosen from files within this of its
# coordinate. photo_census uses the same constant to decide whether a proposal
# is one the pack already holds, so a row's evidence and its identity agree.
HOME_MATCH_KM = photo_census.HOME_MATCH_KM

# U3-06 — evidence frames that look like a document are left out of both
# surfaces. Built on photo_see's `document` and `whiteboard` classes, read from
# the ENGINE defaults and never from the owner pack: a pack may redeclare the
# scene set without either class, and a privacy check a pack can switch off is
# not one. The prompts below only widen it, and they live here rather than in
# photo_see because photo_see's prompts are the sorting path's and are
# recorded beside its encoded vectors.
#
# ⛔ BROAD on purpose. A false positive costs one thumbnail (the strip tries
# the next file); a false negative puts an ID number into a file the owner may
# hand to somebody. Measured on a real 990-file dump, reading the 320 px
# thumbnail this page actually embeds: every real document (a receipt, a bill,
# an admission ticket, a tax notice, a slide) scored at least +0.034 over its
# best ordinary class; the rule below withholds anything within 0.02 BELOW
# that — 36 frames of 990 (3.6%), almost all of them ordinary photographs.
DOCUMENT_EXTRA_PROMPTS = [
    "a ticket with a QR code", "an admission ticket shown on a phone screen",
    "an identity card", "a passport page", "a boarding pass", "an invoice",
    "a bill showing a name, an address and a phone number",
    "a form filled in with personal details", "a bank card",
    "a screenshot of a booking confirmation",
    "a letter or an envelope with a printed address",
    "a screenshot of a text document",
]
DOCUMENT_CLASSES = ("document", "whiteboard")
DOCUMENT_MARGIN = 0.02
DOCUMENT_WORDS = "a ticket, a receipt, a form, an ID card"

# The check in force: a callable(jpeg bytes) -> True for a document. Tests
# inject one; production fills it from `document_filter()` on first use.
LOOKS_LIKE_DOCUMENT = None
# Set per run by `arm_evidence_filter()`. UNARMED is fail-closed: a caller that
# reaches `thumbs()` without arming it gets no photographs, with the reason.
UNARMED = object()
ACTIVE_FILTER = UNARMED

NO_CLIP_REFUSAL = (
    "the evidence photographs could not be checked for documents (%s).\n"
    "  That check keeps %s off a page or sheet the owner may pass on (U3-06),\n"
    "  and it needs CLIP. Run this under the repo's virtualenv:\n"
    "      %s %s ...")
# ⛔ Only this script has the flag (FIX6): `photo_memory.py review` arms the
# same check for a place page and offers no opt-out, so the hint is a dead end
# there.
NO_CLIP_OPT_OUT = (
    "\n  or pass --unfiltered-evidence to embed every photograph unchecked —\n"
    "  the page and the sheet then say they were not checked.")


def document_filter(device=None, bundle=None):
    """-> callable(jpeg bytes) -> bool, the U3-06 judgement, over CLIP.

    A frame is a document when its best document prompt comes within
    DOCUMENT_MARGIN of its best ordinary class. Ordinary classes are prompt
    ensembles, the document side is every prompt on its own: one sentence that
    fits is enough, which is what makes the rule broad."""
    import numpy as np
    import open_clip
    import photo_see

    torch, model, preprocess, device = bundle or photo_embed.load_model(device)
    tokenizer = open_clip.get_tokenizer(photo_embed.MODEL_ID)

    def encode(prompts):
        with torch.no_grad():
            feats = model.encode_text(tokenizer(prompts).to(device))
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy()

    labels = photo_see.DEFAULT_SCENE_LABELS
    document = encode([p for c in DOCUMENT_CLASSES for p in labels[c]]
                      + DOCUMENT_EXTRA_PROMPTS)
    ordinary = []
    for name, prompts in labels.items():
        if name not in DOCUMENT_CLASSES:
            mean = encode(prompts).mean(axis=0)
            ordinary.append(mean / np.linalg.norm(mean))
    ordinary = np.stack(ordinary)

    def looks_like_document(raw):
        with Image.open(io.BytesIO(raw)) as im:
            tensor = preprocess(im.convert("RGB")).unsqueeze(0).to(device)
        with torch.no_grad():
            feats = model.encode_image(tensor)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        x = feats.cpu().numpy()[0]
        return float((document @ x).max()) >= \
            float((ordinary @ x).max()) - DOCUMENT_MARGIN

    return looks_like_document


def arm_evidence_filter(unfiltered, script="photo_onboard_page.py"):
    """Decide, once per run, what `thumbs()` checks frames with."""
    global LOOKS_LIKE_DOCUMENT, ACTIVE_FILTER
    if unfiltered:
        ACTIVE_FILTER = None
        return
    if LOOKS_LIKE_DOCUMENT is None:
        try:
            LOOKS_LIKE_DOCUMENT = document_filter()
        except ImportError as err:
            venv = str(photo_platform.venv_python())
            sys.exit(NO_CLIP_REFUSAL % (err, DOCUMENT_WORDS, venv,
                                        os.path.join(SCRIPTS, script))
                     + (NO_CLIP_OPT_OUT if script == "photo_onboard_page.py" else ""))
    ACTIVE_FILTER = LOOKS_LIKE_DOCUMENT


def _encode_pil(path, max_px, quality):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def encode_image(path, filetype=None, max_px=THUMB_PX, quality=THUMB_QUALITY):
    """-> a data: URI, downscaled and EXIF-rotated for DISPLAY only.

    Orientation is applied for the same reason the review page applies it: a
    sideways contact sheet is what the owner is actually shown, and a
    screenshot rotated 90 degrees does not read as a screenshot.

    ⛔ Pillow alone reads almost none of a real phone dump. Measured on the
    collection this was built against: **852 of 995 files in one month are
    HEIC**, which stock Pillow cannot decode, and a further slice are MP4,
    which no still-image decoder can. A Pillow-only path returns an empty
    evidence strip for nearly every photograph an iPhone ever took — the one
    thing this page exists to show.

    ⛔ So the fallback is `photo_embed.convert_to_thumbnail`, the converter
    the engine already has, and NOT a second copy of it here. It dispatches on
    the manifest's FileType rather than the suffix (`sips` for stills,
    `qlmanage` for video — sips cannot extract a frame from an MP4 and returns
    a bare "Error 13"), and it already handles the mismatched-extension case
    D13 gate 1 is about. A private copy would have to re-learn all of that,
    and would drift from it.

    ⚠️ That converter is macOS-only by design (A22), so off macOS this raises
    for any format Pillow refuses, and the caller reports which. It must never
    come back as a quietly short strip: that is indistinguishable from "this
    place has few photos", and the owner would answer a question about
    evidence that was never rendered.
    """
    if Image is None:
        raise SystemExit("Pillow is required to embed images: pip install pillow")
    try:
        raw = _encode_pil(path, max_px, quality)
    except Exception as first:                           # noqa: BLE001
        kind = photo_embed.kind_of(filetype) if filetype else "image"
        tmp = tempfile.mkdtemp(prefix="onboard-thumb-")
        try:
            out, cause = photo_embed.convert_to_thumbnail(
                path, pathlib.Path(tmp), "t", kind, filetype)
            if not out:
                raise RuntimeError(
                    "Pillow refused it (%s) and the engine's %s converter "
                    "produced nothing: %s" % (type(first).__name__, kind, cause))
            raw = _encode_pil(str(out), max_px, quality)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


# How many files one strip may try before giving up. Without a cap, a
# collection whose format has no decoder walks every file it holds looking for
# one that opens — which is what a missing HEIF decoder actually did here:
# minutes of work, no error, an empty strip at the end.
MAX_ATTEMPTS = EXEMPLARS * 4

# Every reason a strip came up short this run, reported at the end rather
# than counted and dropped.
TROUBLE = Counter()


def thumbs(rows, limit=EXEMPLARS, held=None):
    """-> (data URIs, {reason: count}) for up to `limit` of manifest `rows`.

    `held`, when given, collects the names of frames the document check left
    out (U3-06). Kept apart from the reasons on purpose: "could not open" and
    "chose not to show" want different answers from whoever reads them.

    Rows, not paths: the converter dispatches on the manifest's FileType, and
    a suffix is exactly what D13 gate 1 says not to trust.

    ⛔ The reasons are RETURNED, never swallowed. A strip can come up short
    for two reasons that look identical on the page — the drive was unplugged,
    or this build cannot decode the format — and only the second means every
    strip on the page is empty for the same cause. `except Exception: pass`
    here is the defect already carded as A22(c); this is the same mistake and
    it is not repeated.
    """
    out, why, tried = [], Counter(), 0
    for row in rows:
        if len(out) >= limit or tried >= MAX_ATTEMPTS:
            break
        tried += 1
        path = row["SourceFile"]
        try:
            uri = encode_image(path, row.get("FileType"))
            if ACTIVE_FILTER is UNARMED:
                raise RuntimeError("no document check was armed (U3-06), so "
                                   "no frame is shown")
            if ACTIVE_FILTER is not None and ACTIVE_FILTER(
                    base64.b64decode(uri.split(",", 1)[1])):
                if held is not None:
                    held.append(os.path.basename(path))
                continue
            out.append(uri)
        except Exception as err:                         # noqa: BLE001
            # The extension AND what actually went wrong. An extension alone
            # says which files failed but not whether the cause is one broken
            # file or a decoder this build does not have — and those two want
            # completely different answers from whoever reads the warning.
            why["%s %s: %s" % (os.path.splitext(path)[1].lower() or "?",
                               type(err).__name__,
                               # 160, not 90: these messages put the
                               # useful half at the END ("... produced
                               # nothing"), so a tight cut keeps the noun and
                               # throws away the verdict.
                               str(err).strip().splitlines()[0][:160])] += 1
    return out, dict(why)


def blank(value):
    """exiftool writes '-' for a tag a file does not carry."""
    return (value or "").strip() in ("", "-")


def read_units(targets):
    """-> [(label, [row, ...]), ...] for each work dir or manifest given."""
    units = []
    for target in targets:
        rows, path = photo_census.read_manifest(target)
        units.append((os.path.basename(os.path.dirname(str(path))) or str(path),
                      rows))
    return units


# ------------------------------------------------------------------ sections

def cameras_section(rows):
    """Every device that took a file here, with the photos it took.

    The census proposes makes; the owner is being asked to recognise DEVICES.
    A make left off files its photos as somebody else's, so the tail devices —
    the ones under a percent, which is exactly where a second phone and a
    friend's camera are indistinguishable by count — get their photographs
    shown, not just their counts.
    """
    by_device = defaultdict(list)
    for row in rows:
        if blank(row.get("Make")) and blank(row.get("Model")):
            continue
        key = ((row.get("Make") or "").strip(), (row.get("Model") or "").strip())
        by_device[key].append(row)

    total = sum(len(v) for v in by_device.values())
    devices = []
    for (make, model), drows in sorted(by_device.items(),
                                       key=lambda kv: -len(kv[1])):
        held = []
        strip, why = thumbs(drows, held=held)
        TROUBLE.update(why)
        devices.append({
            "make": make, "model": model, "files": len(drows),
            "share": round(100.0 * len(drows) / total, 2) if total else 0.0,
            "thumbs": strip, "unreadable": sum(why.values()),
            "withheld": len(held),
        })
    return {"devices": devices, "files_with_make": total}


# M16b. What a screen-size question may show OF A FILENAME.
#
# ⛔ MASKED, never dropped. Measured on a real page: the filenames are the only
# evidence some questions have, because the U3-06 document check withholds the
# photographs — and a chat screenshot is exactly what that check withholds. So
# deleting them takes a question that moves files from thin to unanswerable.
# What must not travel is the ID: measured, 13 of 14 names carried a run of 8+
# digits, the longest was 146 characters, and three carried paired UUID-shaped
# query tokens. What EARNS its place is the date and the app word — that is
# what lets an owner say "that is my chat app".
NAME_SHOWN_MAX = 44
# A date is NOT an id, and it is the single most useful token here. Matched
# first and protected, because `\d{8,}` cannot tell `20240115` from a chat id.
RE_NAME_DATE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?:0[1-9]|1[0-2])"
                          r"(?:0[1-9]|[12]\d|3[01])(?!\d)")
RE_NAME_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{8,}")
RE_NAME_QUERY = re.compile(r"[?&][A-Za-z_]+=[^&_]*")
# 9, not 12. ⛔ The bound is NOT protecting dates — `RE_NAME_DATE` is parked
# and restored around this, so the threshold never had to carry that job.
# What it has to clear is a TIME (`143022`, 6 digits) and an ordinary frame
# number (`0042`), and what it has to catch is a phone number: measured,
# `IMG_0912345678_received.jpg` came through WHOLE at 12. Nine leaves clear
# air above a time and below any phone number. Measured on the real dump
# (368 filenames): thresholds 8, 9, 10 and 11 all bite EXACTLY the same
# names as 12 — there is not one run of length 9-11 in it — so this costs
# nothing observed and closes a shape the corpus simply did not contain.
RE_NAME_RUN = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{9,}(?![0-9A-Za-z])")


def mask_name(name):
    """-> `name` with its id-shaped runs blanked, its date and words kept."""
    stem, dot, ext = name.rpartition(".")
    if not stem:
        stem, dot, ext = name, "", ""
    keep = {}

    def park(match):
        token = "\x00%d\x00" % len(keep)
        keep[token] = match.group(0)
        return token

    stem = RE_NAME_DATE.sub(park, stem)      # protect real dates first
    stem = RE_NAME_UUID.sub("…", stem)
    stem = RE_NAME_QUERY.sub("", stem)
    stem = RE_NAME_RUN.sub("…", stem)
    for token, value in keep.items():
        stem = stem.replace(token, value)
    stem = re.sub("…{2,}", "…", stem).strip("_-. ")
    if len(stem) > NAME_SHOWN_MAX - len(dot + ext):
        stem = stem[:NAME_SHOWN_MAX - len(dot + ext) - 1] + "…"
    return stem + dot + ext


NAMES_FILE = "screen-filenames.txt"


def names_file(page_path):
    """-> where the FULL filenames for a page/sheet are kept, on disk.

    The `places_file()` pattern, in the same spirit: what is withheld from a
    surface the owner may pass on is not destroyed, it is written beside it.
    """
    return pathlib.Path(page_path).parent / NAMES_FILE


def write_names_file(path, candidates):
    lines = ["screen-size filenames — the full names behind each size the "
             "page or sheet asks about. Kept on disk; the surfaces show a "
             "masked form, because an id in a filename travels with them.", ""]
    for cand in candidates:
        lines.append("%sx%s:" % (cand["dims"][0], cand["dims"][1]))
        for name in cand.get("names") or []:
            lines.append("  %s" % name)
        if not cand.get("names"):
            lines.append("  (no filename was collected)")
        lines.append("")
    pathlib.Path(path).write_text("\n".join(lines) + "\n",
                                  encoding="utf-8")


def screens_section(rows, census, profile=None, full_names=None):
    """Screen-size candidates, each with the files that carry the size.

    ⛔ The ordering here is the census's own — by file count — and it is
    reproduced rather than corrected, because correcting it would be inventing
    a ranking the engine cannot justify. What the page adds is the pictures,
    and a plain statement of what accepting each row would MOVE.
    """
    at_size = defaultdict(list)
    for row in rows:
        if not photo_census.no_camera(row):
            continue
        # ⛔ Collapsed the way the CENSUS collapses it — same predicate, not a
        # second copy (M13). Keyed raw, a candidate whose files are all stored
        # in the other orientation found none of its own evidence and the page
        # said "no file at this size" beside `files: 2`.
        at_size[photo_census.portrait_key(row.get("ImageWidth"),
                                          row.get("ImageHeight"))].append(row)

    out, listed = [], []
    in_pack = photo_census.pack_screen_sizes(profile)
    for cand in photo_census.without_declined(census, profile)["screen_size_candidates"]:
        dims = tuple(cand["dims"])
        # F-ff for screens: a size the pack already routes is not asked again.
        if tuple(sorted(int(x) for x in dims)) in in_pack:
            listed.append("%sx%s" % dims)
            continue
        crows = at_size.get(dims, [])
        held = []
        strip, why = thumbs(crows, held=held)
        TROUBLE.update(why)
        if full_names is not None:
            # ⛔ An OUT-PARAMETER, the same idiom as `held` above, and it
            # exists so the unmasked names never enter the returned structure:
            # that structure is embedded verbatim in the page's JSON, so a key
            # holding them would ship the ids in the file even though nothing
            # displays them.
            full_names.append({"dims": list(cand["dims"]),
                               "names": [os.path.basename(r["SourceFile"])
                                         for r in crows[:EXEMPLARS]]})
        out.append({
            "dims": list(cand["dims"]),
            "files": cand["files"],
            "warning": cand.get("warning"),
            "model": cand.get("model"),
            # ⛔ MASKED here, at the one source both surfaces read (M16b). The
            # SHEET prints these; the PAGE never displays them but embeds them
            # in its JSON data block — and the page FILE is what gets passed
            # on, so an undisplayed id still travels. `full_names` stays for
            # `write_names_file()`, which keeps them on local disk only.
            "names": [mask_name(os.path.basename(r["SourceFile"]))
                      for r in crows[:EXEMPLARS]],
            # F6 — the census's own sentence, so page, sheet and census
            # cannot drift apart.
            "check": photo_census.screen_evidence(cand, profile),
            "thumbs": strip, "unreadable": sum(why.values()),
            "withheld": len(held),
        })
    return {"candidates": out, "already_listed": listed,
            "below_threshold": census["screen_sizes_below_threshold"],
            "by_filename": census["screenshots_by_filename"]}


def with_device_checks(screens, specs):
    """W1C-1 — every candidate carries one sentence per looked-up camera."""
    for cand in screens["candidates"]:
        cand["device_checks"] = [{"device": s["device"],
                                  "text": device_check(s, cand["dims"])}
                                 for s in specs]
    return screens


def pool_places(units):
    """-> every place the census could describe, pooled across the work dirs.

    Rows are pooled across every unit given and matched to each other by
    `HOME_MATCH_KM`, so the same address censused in six monthly dumps is ONE
    row carrying six months of evidence rather than six rows the owner has to
    recognise as the same place. That pooling is the reason this stage takes
    work dirs rather than a single manifest.

    ⛔ It pools `home_places()`, not `home_candidates()` — the whole set, both
    the places that cleared the two home bars and the places that did not.
    Dropping the second half here is what made D-04 stop at the census: the
    page is the surface the owner is sent to, and it printed only proposals.

    A place that cleared the bars in ANY unit is a proposal. The bars are read
    per unit and never re-read on the pooled totals: `home_places()` counts
    DISTINCT days inside one manifest and this can only add them up, so a
    pooled total is an upper bound on the distinct days and re-deciding a bar
    from it would promote a place on evidence nobody measured.
    """
    pooled = []
    for label, rows in units:
        for place in photo_census.home_places(rows):
            for seen in pooled:
                if haversine_km(tuple(place["coord"]),
                                tuple(seen["coord"])) < HOME_MATCH_KM:
                    seen["days"] += place["days"]
                    seen["night_days"] += place["night_days"]
                    seen["files"] += place["files"]
                    seen["units"].append(label)
                    if place["proposed"]:
                        seen["proposed"] = True
                        seen["missed"] = []
                    elif not seen["proposed"]:
                        for miss in place["missed"]:
                            if miss not in seen["missed"]:
                                seen["missed"].append(miss)
                    break
            else:
                pooled.append({"coord": place["coord"], "days": place["days"],
                               "night_days": place["night_days"],
                               "files": place["files"], "units": [label],
                               "map": place["map"],
                               "proposed": place["proposed"],
                               "missed": list(place["missed"])})
    return pooled


def homes_section(units, with_coords, profile=None):
    """Two lettered blocks: the residences proposed, then the ones withheld.

    ⭐ D-04, on the page this time. `home_near_misses()` existed and reached
    the census text alone; the page — the surface `photo-init` sends the owner
    to, and the only one carrying the photographs — showed proposals only. On
    a measured dump that cost a real owner their third residence: they had
    photographed the place they lived like a visitor, it missed the day bar by
    one, it appeared on the page not at all, and so it was never asked the
    follow-up every proposed row gets. A missing row does not just cost a row;
    it costs every question that row would have been asked.

    ⛔ The second block is a DISCLOSURE, not a second proposal — the same
    distinction `photo_census.render_near_misses()` makes, and the reason the
    two are separate lists rather than one with a flag. It is answerable,
    because the question is the point, and it is NOT required: the engine did
    not propose these and must not press the owner as though it had.

    ⛔ The filter and the cap are `photo_census.home_near_misses()`'s, called
    rather than reimplemented, so a page and a census printed from the same
    collection cannot disagree about what was withheld.
    """
    pooled = pool_places(units)
    # ⭐ F-ff / F-nn — a place the pack already registers as a home is not
    # asked again (the census already said "already listed"; the sheet asked
    # anyway). The census's own distance test; the pack's row is named.
    pack_homes = photo_census.pack_home_rows(profile)
    listed = []
    for home in list(pooled):
        hit = photo_census.listed_as(home, pack_homes)
        if hit is not None:
            listed.append("%s (%s)" % (hit.get("label") or "(unnamed)",
                                       hit.get("id") or "no id"))
            pooled.remove(home)
    proposals = [h for h in pooled if h["proposed"]]
    proposals.sort(key=lambda h: (-len(h["units"]), -h["days"], -h["files"]))

    # The census's own ordering — closest to the bars first — so the cap cuts
    # from the far end, which is what makes `home_near_misses()`'s promise
    # about its top row true here too.
    by_bars = sorted(pooled, key=lambda h: (-h["days"], -h["night_days"],
                                            -h["files"]))
    withheld, over_cap, one_day_only = photo_census.home_near_misses(by_bars)

    all_rows = [r for _, rows in units for r in rows]

    def make_row(home, letter):
        near = []
        for row in all_rows:
            point = gps_point(row.get("GPSPosition", "-"))
            if point and haversine_km(point, tuple(home["coord"])) < HOME_MATCH_KM:
                near.append(row)
        held = []
        strip, why = thumbs(near, held=held)
        TROUBLE.update(why)
        row = {
            "id": letter,
            "days": home["days"], "night_days": home["night_days"],
            "files": home["files"], "units": sorted(set(home["units"])),
            "thumbs": strip, "unreadable": sum(why.values()),
            "withheld": len(held),
            "country_box": row_country(home["coord"]),
        }
        if home["missed"]:
            row["missed"] = list(home["missed"])
            # The wording is the census's, so the page and the printed report
            # give the same reason for the same withheld row.
            row["missed_why"] = [photo_census.MISSED_WORDS[m]
                                 for m in home["missed"]]
        if with_coords:
            row["coord"] = home["coord"]
            row["map"] = home["map"]
        return row

    letters = (chr(ord("A") + i) for i in range(len(proposals) + len(withheld)))
    return {"rows": [make_row(h, next(letters)) for h in proposals],
            "near_misses": [make_row(h, next(letters)) for h in withheld],
            "near_misses_over_cap": over_cap,
            "near_misses_one_day_only": one_day_only,
            "already_listed": listed,
            "coords_withheld": not with_coords}


# K20 / H-C C5 — ISO 3166-1 alpha-2, every officially assigned code. A
# `country:` answer is checked against this at WRITE time: the reader
# (photo_profile.country) accepts any two letters, and an unknown code would
# silently turn off the owner's day test.
ISO2 = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL
BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV
CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD
GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM
IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK
LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW
MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR
PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS
ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY
UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW""".split())
# The page's short list; any other code is typed. Codes only, no names, so
# no language is hardcoded (Rule 8).
COUNTRY_COMMON = ("US", "GB", "CA", "AU", "DE", "FR", "JP", "KR", "SG", "TW",
                  "HK", "MY")


def row_country(coord):
    """-> the COUNTRY_BOXES row a home's coordinate lies in, else None. A
    country-level flag, so it may travel on the page; the coordinate never
    does."""
    return next((c for c, box in photo_cluster.COUNTRY_BOXES.items()
                 if photo_cluster.in_box(tuple(coord), box)), None)


# The only answers a render may carry in. ⛔ `screens` and `homes` are NOT
# here and must never be: they are the two that MOVE FILES, the two the census
# ranks misleadingly, and the two the photographs exist for. An owner who was
# handed those pre-filled would be confirming a guess, which is the exact
# failure this whole stage was built to stop.
PREFILLABLE = ("language", "types", "away")


def read_prefill(raw):
    """-> {key: value} for answers the owner already gave somewhere else.

    A pre-fill is a QUOTE, not a choice: the page marks every field it seeds
    and seeds only empty ones, so the owner sees what was carried in and can
    correct it. Anything outside PREFILLABLE stops the run rather than being
    dropped quietly — a silently ignored `--prefill screens=...` would leave
    whoever wrote it believing the answer was recorded.
    """
    if not raw:
        return {}
    out = {}
    for pair in raw:
        key, _, value = pair.partition("=")
        key = key.strip()
        if key not in PREFILLABLE:
            raise SystemExit(
                "--prefill %r: only %s may be carried in. `screens` and "
                "`homes` move files and must be answered from the "
                "photographs." % (key, "/".join(PREFILLABLE)))
        out[key] = value.strip()
    return out


def pack_answers(profile):
    """HIL-9 — {page key: value} for the section-4 answers this pack already
    holds FROM THE OWNER, the shape `read_prefill` returns.

    ⛔ Only what an owner actually gave. The template ships `language: en`
    and `away_km: 3`, so neither proves an answer: `en` counts once the pack
    has been through an onboarding (it holds a camera, a home or a screen
    size, or an answered away_km), and away_km counts only when
    `photo_cluster.away_km_answered()` says so."""
    profile = profile or {}
    out = {}
    onboarded = bool(profile.get("own_camera_makes") or profile.get("home_locations")
                     or profile.get("screen_dims")
                     or photo_cluster.away_km_answered(profile))
    language = profile.get("language")
    if language and (language != "en" or onboarded):
        out["language"] = language
    types = (profile.get("naming_spec") or {}).get("types") or []
    if types:
        out["types"] = ", ".join(types)
    if photo_cluster.away_km_answered(profile):
        out["away"] = str(away_km_shown(profile))
    return out


LANGUAGE_NO_CLUE = ("Your filenames give no clue to which language you use. "
                    "That is not a reason to assume English, so the engine "
                    "asks you instead of guessing.")


def language_note(signal):
    """W1C-3 — the one sentence both surfaces print under the language
    question. Built here so the page and the sheet cannot drift, and so the
    page never concatenates the census's list of {script, files} rows into a
    sentence (it used to: "The filenames suggest [object Object]")."""
    if not signal:
        return LANGUAGE_NO_CLUE
    seen = ", ".join("%s (%d file%s)" % (s["script"], s["files"],
                                         "" if s["files"] == 1 else "s")
                     for s in signal)
    return ("The filenames carry this script: %s. A script is not a language "
            "(Han can be zh-TW or zh-CN), so the engine asks you instead of "
            "guessing." % seen)


def disclaimer(with_coords):
    """W1C-5 — what this product does and does not promise, as the page and
    the sheet both print it. Every line is a measured property of the engine,
    never a guarantee it does not keep.

    ⛔ Never "the coordinates stay on this machine": trip GPS goes to the map
    service (photo_cluster's Nominatim calls, photo_where's Overpass calls), an
    unnamed home goes out rounded to 2 dp for its city, and no switch an owner
    is shown turns every lookup off (`--no-geocode` is photo_cluster's alone).
    ⛔ Never "a home is never named": the owner's own word for it names its
    folders (D-F9), and an unnamed one may carry its city (R13)."""
    return [
        "It copies, and only copies: no original photo or video is ever "
        "moved, renamed or deleted, and every copy is checked against its "
        "original before it counts as done.",
        "A home you register is never named by its street or address: its "
        "folders carry your own word for it or, if you gave none, only its "
        "city.",
        ("This page and the answer sheet carry no coordinates."
         if not with_coords else
         "This page carries the coordinates of the areas above, because it was "
         "built to stay on this computer. Do not send it to anyone."),
        "To name trips, the engine sends locations from your photos' GPS to "
        "OpenStreetMap, a public map service, and uses the place names it "
        "sends back. For a home you left unnamed, the location is rounded to "
        "about 1 km before it is sent.",
        "Recognising which animal is which is not reliable yet. A name it "
        "proposes is a proposal for you to check and correct, not a fact.",
        "Every new folder of photos brings its own questions — a new camera, "
        "a new place, an animal it keeps seeing — so expect to be asked "
        "again.",
    ]


# W1C-6 — shown when an owner picks "Don't add to my profile", verbatim as
# the owner ruled it. Both halves are traced: a labelled home is named from
# its label with no geocode call (D-F9); a blank-named home falls to
# city_admin(), coordinate coarsened, which cannot return a road or a POI.
# ⛔ Never extend it with a claim about DROPPED rows: their only address guard
# is photo_cluster.is_address(), which recognises CJK addresses only.
DROP_NOTE = ('Optional: if you live here, choose "I live here" and give it '
             'your own name — that keeps your address out of folder names '
             'entirely. Leave the name blank and only the city is used.')

NEXT_INTRO = ("More questions will come up while it runs, on pages like this "
              "one. Please stay at the computer until the copy has finished.")

# W1C-5 — what happens after Confirm, in order. Each step is one that exists
# (photo-run/SKILL.md, Workflow): apply --write-pack, prep, classify + the
# visual pass, the per-batch pages (G6, which replace U-2 on an indexed dump),
# finish --go, the end-of-dump round (SNS-4). ⛔ Never add a step the engine
# does not run. G6 R10 (provisional, the owner judges the words): "a few short
# pages", and NOT "one at a time" for the looking — the visual pass still
# covers every batch before the first page.
NEXT_STEPS = [
    ("Your answers go into your pack",
     "The session reads what you confirmed and, when you agree, writes it "
     "into your owner pack. Nothing is written before that."),
    ("The photos are grouped",
     "The engine reads each photo's date and place and groups them into "
     "batches: a trip, a day out, days at home. Nothing is copied yet."),
    ("Each batch is looked at",
     "The assistant looks at sample photos of each batch to decide what kind "
     "of folder it is, and a picture pass looks for scenes and for animals "
     "that keep coming back."),
    ("A few short pages — stay at the computer",
     "For the first batches that show an animal or a place you visit often, "
     "a page asks you to match each pet you named here with its photos, "
     "picking the name from your list, and to name any place you visit often "
     "that is not a home. Expect a few of these pages, a few minutes each. "
     "The copy waits until they are answered: a name given after the copy "
     "does not rename a folder by itself, so you would rename those folders "
     "by hand."),
    ("The copy",
     "Files are copied into the new folders and every copy is checked. Files "
     "with no date go to a to-be-checked folder for you to sort by hand."),
    ("One more round at the end",
     "After the copy, one last page may ask about an animal that only became "
     "frequent late in this folder of photos."),
]


# W1C-1 — the owner cannot be expected to know their phone's screen size, so
# the session looks each camera up and passes it in. The ENGINE ships no device
# table (it is stale on day one for exactly the owners with new phones); the
# agent generates, this code validates — photo_name's pattern.
# ⛔ The observed size ALWAYS wins. A panel spec and a screenshot legitimately
# disagree: a phone set below its panel resolution screenshots at that setting
# (panel 1440x3120, screenshots 1080x2340 — the same 13:6 shape). So this is a
# cross-check that explains, never a gate: nothing here rejects a size, and no
# spec at all is the normal path.
SPEC_RE = re.compile(r"^\s*(?P<device>.+?)\s*=\s*(?P<w>\d+)\s*[xX]\s*"
                     r"(?P<h>\d+)\s*(?:@\s*(?P<source>.*?))?\s*$")
SPEC_SHAPE_TOLERANCE = 0.01


def parse_device_spec(raw, devices):
    """-> one validated `--device-spec`, or SystemExit saying what is wrong.
    ⛔ A source is REQUIRED: an unsourced number on the page cannot be told
    apart from one measured off the photographs."""
    m = SPEC_RE.match(raw or "")
    if not m or int(m.group("w")) <= 0 or int(m.group("h")) <= 0:
        raise SystemExit(
            "--device-spec %r: write it as \"<camera as the census names it>="
            "<width>x<height>@<where it was looked up>\"." % raw)
    source = (m.group("source") or "").strip()
    if not source:
        raise SystemExit(
            "--device-spec %r has no source. Add `@<where it was looked up>`: "
            "a number on this page with no source cannot be told apart from "
            "one measured from the photographs." % raw)
    found = [d for d in devices if d.lower() == m.group("device").lower()]
    if not found:
        raise SystemExit(
            "--device-spec %r names %r, which is not a camera in this "
            "collection. Cameras here: %s"
            % (raw, m.group("device"), ", ".join(devices) or "none"))
    w, h = int(m.group("w")), int(m.group("h"))
    return {"device": found[0], "dims": [w, h], "source": source,
            "label": "%s: screen %dx%d, looked up by the assistant (source: "
                     "%s), not measured from your photos."
                     % (found[0], w, h, source)}


def device_check(spec, dims):
    """-> one sentence comparing a looked-up screen with an observed size.
    Printed verbatim by the page and the sheet; never a verdict."""
    ps, pl = sorted(spec["dims"])
    cs, cl = sorted(int(x) for x in dims)
    screen = "the %s's screen (%dx%d)" % (spec["device"], spec["dims"][0],
                                          spec["dims"][1])
    wins = ("That does not rule it out: the size in your own screenshots "
            "always wins.")
    if cs <= 0:
        return ("no width or height is recorded at this size, so it cannot "
                "be compared with %s. %s" % (screen, wins))
    if (cs, cl) == (ps, pl):
        return "matches %s exactly." % screen
    if abs(pl / ps - cl / cs) < SPEC_SHAPE_TOLERANCE:
        if cl < pl:
            return ("the same shape as %s, but smaller. Phones are often set "
                    "to a lower display resolution, and screenshots follow "
                    "that setting, so this size is consistent with this "
                    "phone." % screen)
        return ("the same shape as %s, but larger, so it did not come from "
                "this phone's screen. %s" % (screen, wins))
    return ("a different shape from %s: a cropped picture, or another "
            "device's screen. %s" % (screen, wins))


def camera_ids(rows):
    """The camera names exactly as the page's first question shows them."""
    return sorted({"%s %s" % ((r.get("Make") or "").strip(),
                              (r.get("Model") or "").strip())
                   for r in rows
                   if not (blank(r.get("Make")) and blank(r.get("Model")))})


def languages():
    """-> the languages the ENGINE has a bucket table for, each shown by the
    folder names it would actually produce.

    Read off `photo_profile.BUCKET_VOCAB` rather than listed here, for a
    reason that is not tidiness: a page offering a language the engine has no
    table for is offering a silent fallback to English. The owner picks it,
    the folders come out in the wrong language, and nothing anywhere reports
    a problem — `buckets()` falls back by design. What the engine can do is
    the only honest list, and the sample is what makes the choice legible to
    someone who cannot read a language tag.
    """
    out = []
    for code, table in sorted(photo_profile.BUCKET_VOCAB.items()):
        out.append({"code": code,
                    "sample": [table["screenshots"], table["to_be_checked"],
                               table["others"]]})
    return out


def type_defaults():
    """-> the `[type]` words the engine falls back to, per language.

    Read off `photo_profile.TYPE_VOCAB` for the same reason `languages()` is
    read off `BUCKET_VOCAB`, and for one more that is specific to this
    question: whatever the owner writes at `types:` BECOMES the vocabulary --
    `photo_classify_set.allowed_types()` takes `naming_spec.types` over
    `default_types()` entirely. So the sheet was asking someone to author a
    controlled vocabulary while showing them nothing, and its own worked
    examples ("a trip, an event, a hike") are not words this engine can
    accept. An owner who copied them would have pinned their whole pack to
    three unusable strings and had every batch refused at classify (U3-01,
    and the damage U3-04 nearly took).

    ⛔ The words are never listed in this file. A page that names a
    vocabulary the engine does not hold is the same defect one layer up.
    """
    return [{"code": code, "words": sorted(table.values())}
            for code, table in sorted(photo_profile.TYPE_VOCAB.items())]


def coords_file(homes, near_misses=()):
    """The coordinates the page does not carry, for local disk only.

    Written beside the page so the owner can open a map when the photographs
    alone do not settle which address a row is. Row letters match the page.

    ⛔ The withheld rows are here too, and marked. A near-miss row is exactly
    the row whose photographs are least likely to settle it — the owner was
    there on few days — so leaving its coordinate out of the one file that
    holds coordinates would disclose the row and withhold the only thing that
    identifies it.
    """
    lines = ["home rows — coordinates, kept off the page (Operational Rule 3).",
             "Row letters match the onboarding page.", ""]

    def say(row, tail=""):
        coord = row.get("coord")
        if not coord:
            return
        lines.append("%s  %s, %s  %d day(s), %d after dark, %d file(s)  [%s]%s"
                     % (row["id"], coord[0], coord[1], row["days"],
                        row["night_days"], row["files"],
                        ", ".join(row["units"]), tail))
        lines.append("   " + row["map"])

    for row in homes:
        say(row)
    if near_misses:
        lines += ["", "NOT proposed as homes — shown because silence is not "
                      "evidence of absence:"]
        for row in near_misses:
            say(row, "  withheld: " + " and ".join(row.get("missed_why", [])))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------- render

def away_km_shown(profile):
    """The home range this owner's next run would actually use, as a number
    fit to print — 3, not 3.0, and 60 when the pack still says 60.

    ⛔ Never a literal. The hardcoded 3 that stood here told one owner their
    default was a safe small number while their pack held 60, which is the
    strongest possible argument for leaving the question blank — and blank
    kept the 60. A sentence about a setting has to come from the same place
    the setting does.
    """
    value = photo_profile.get(profile, "cluster_defaults", "away_km",
                              default=AWAY_KM_DEFAULT)
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value          # a malformed pack says so on the page, verbatim
    return int(num) if num == int(num) else num


def build_data(targets, profile, with_coords, prefill=None, device_specs=None,
               full_names=None):
    units = read_units(targets)
    all_rows = [r for _, rows in units for r in rows]
    census_all = photo_census.census(all_rows)
    # Validated before any photograph is opened, so a bad spec fails fast.
    specs = [parse_device_spec(raw, camera_ids(all_rows))
             for raw in device_specs or []]
    pack = photo_profile.resolve_pack(
        workdir=os.path.dirname(str(photo_census.read_manifest(targets[0])[1])),
        explicit=profile)

    # Built once, with coordinates, then stripped for the page. Building it
    # twice would re-open and re-encode every exemplar for a second copy that
    # differs by two keys.
    homes_with = homes_section(units, with_coords=True, profile=pack.profile)
    homes = dict(homes_with)
    homes["coords_withheld"] = not with_coords
    for key in ("rows", "near_misses"):
        kept_rows = []
        for row in homes_with[key]:
            kept = dict(row)
            if not with_coords:
                kept.pop("coord", None)
                kept.pop("map", None)
            kept_rows.append(kept)
        homes[key] = kept_rows

    screens = with_device_checks(
        screens_section(all_rows, census_all, pack.profile,
                        full_names=full_names), specs)
    return {
        # H-C C3 / obs-9 — what this unit adds that the pack does not hold.
        "new": {"cameras": photo_census.pack_gap(census_all, pack.profile)[0],
                "screens": len(screens["candidates"]),
                "homes": len(homes["rows"]),
                "near_misses": homes["near_misses"],
                "onboarded": bool(pack_answers(pack.profile))},
        "owner": pack.owner or "",
        "generated": datetime.now(timezone.utc).astimezone()
                             .strftime("%Y-%m-%d %H:%M"),
        "files": len(all_rows),
        "units": [label for label, _ in units],
        "cameras": cameras_section(all_rows),
        "screens": screens,
        "device_specs": specs,
        "homes": homes,
        "language_signal": census_all["language_signal"],
        "language_note": language_note(census_all["language_signal"]),
        "disclaimer": disclaimer(with_coords),
        "next_intro": NEXT_INTRO,
        "next_steps": [list(step) for step in NEXT_STEPS],
        "drop_note": DROP_NOTE,
        "languages": languages(),
        "type_defaults": type_defaults(),
        # HIL-9 — a later page quotes the pack's own section-4 answers; a
        # --prefill given on the command line still wins.
        "prefill": dict(pack_answers(pack.profile), **(prefill or {})),
        # K20 / C5 — known: the country the engine already has for this pack
        # (declared, or home-01's box), so the page does not ask it again.
        "country": {"known": photo_cluster.owner_country(pack.profile),
                    "common": list(COUNTRY_COMMON), "codes": sorted(ISO2)},
        "prefill_from_pack": sorted(k for k in pack_answers(pack.profile)
                                    if k not in (prefill or {})),
        # ⛔ Read off the PACK this page is describing, never hardcoded. The
        # hardcoded 3 told one owner their default was a safe small number
        # while their pack held 60 — which is the strongest possible argument
        # for leaving the line blank, and blank kept the 60. A sentence about
        # a setting has to come from the same place the setting does.
        "away_km_default": away_km_shown(pack.profile),
        # False only under --unfiltered-evidence, and then both surfaces say so.
        "evidence_filtered": callable(ACTIVE_FILTER),
        "submitted": None,
    }, homes_with


def render(template, data):
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    tpl_b64 = base64.b64encode(template.encode("utf-8")).decode("ascii")
    return template.replace(MARK_TPL, tpl_b64).replace(MARK_DATA, payload)


def write_coords(path, homes_with_coords):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(coords_file(homes_with_coords["rows"],
                             homes_with_coords["near_misses"]))


def report_counts(data, what):
    print("  %d device(s), %d screen-size candidate(s), %d home row(s), "
          "%d withheld place(s), %d file(s)"
          % (len(data["cameras"]["devices"]),
             len(data["screens"]["candidates"]),
             len(data["homes"]["rows"]),
             len(data["homes"]["near_misses"]), data["files"]))
    every = (data["cameras"]["devices"] + data["screens"]["candidates"]
             + data["homes"]["rows"] + data["homes"]["near_misses"])
    held = sum(row.get("withheld", 0) for row in every)
    if not data.get("evidence_filtered"):
        print("  ⚠️  the photographs were NOT checked for documents "
              "(--unfiltered-evidence) — %s can be among them" % DOCUMENT_WORDS)
    elif held:
        print("  %d photograph(s) left out because they look like a document "
              "(%s) — U3-06; the %s says so where each one was" % (
                  held, DOCUMENT_WORDS, what))
    short = [row for row in every if len(row.get("thumbs", [])) < EXEMPLARS]
    if TROUBLE:
        print("\n⚠️  %d proposal(s) show fewer than %d photographs. Why:"
              % (len(short), EXEMPLARS))
        for reason, n in TROUBLE.most_common():
            print("      %4d x  %s" % (n, reason))
        print("    An empty strip reads to the owner as 'few photos here', not"
              " as 'this\n    build cannot open them' — so answer this before"
              " showing anyone the %s." % what)


def nothing_new(data):
    """H-C C3 / obs-9 (owner ruling 20261001) -> the one line to print when
    this unit adds no camera, no screen size and no proposed home to a pack
    that has been onboarded before, else None. A near-miss is not a home
    candidate, but it is DISCLOSED here with the route to open it (D-04)."""
    new = data["new"]
    if not new["onboarded"] or new["cameras"] or new["screens"] or new["homes"]:
        return None
    line = ("Nothing new to ask for %s: every camera and screen size is "
            "already in the pack, and no place here looks like a home. No "
            "page written." % " + ".join(data["units"]))
    near = new["near_misses"]
    if near:
        days = sorted(r["days"] for r in near)
        line += (" %d place(s) seen on %s day(s) were not proposed as homes."
                 % (len(near), days[0] if days[0] == days[-1]
                    else "%d-%d" % (days[0], days[-1])))
    return line


def cmd_render(args):
    with io.open(TEMPLATE, encoding="utf-8") as fh:
        template = fh.read()
    arm_evidence_filter(args.unfiltered_evidence)
    full_names = []
    data, homes_with_coords = build_data(args.targets, args.profile,
                                         with_coords=args.with_coords,
                                         prefill=read_prefill(args.prefill),
                                         device_specs=args.device_spec,
                                         full_names=full_names)
    skip = None if args.force_page else nothing_new(data)
    if skip:
        print(skip)
        same = ""
        if args.profile:
            same += " --profile %s" % quoted(args.profile)
        if args.coords_out:
            same += " --coords-out %s" % quoted(args.coords_out)
        if args.with_coords:
            same += " --with-coords"
        print("To see them, or to add a home or camera by hand:\n  %s render %s "
              "--out %s%s --force-page"
              % (cli("photo_onboard_page.py", crops=True),
                 " ".join(quoted(x) for x in args.targets), quoted(args.out), same))
        return 0
    html = render(template, data)
    with io.open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    # M16b — the page shows a masked filename; the full ones stay beside it on
    # local disk, the way `places_file()` keeps a coordinate.
    if any(c["names"] for c in full_names):
        write_names_file(names_file(args.out), full_names)

    said = ["wrote %s (%.1f MB)"
            % (args.out, os.path.getsize(args.out) / 1048576.0)]
    if not args.with_coords:
        said.append("coordinates are NOT in the page (photographs are, and "
                    "a photograph can still show where a place is)")
        if args.coords_out:
            write_coords(args.coords_out, homes_with_coords)
            said.append("they are in %s" % args.coords_out)
        else:
            said.append("and were not written anywhere (--coords-out to keep them)")
    print("; ".join(said))
    report_counts(data, "page")
    return 0


# -------------------------------------------------------------------- sheet
#
# The page needs a browser to read it and an artifact host to send it back.
# A terminal-only session, a server install, a session with no browser and
# an agent-driven run have none of those, and this is the FIRST checkpoint of
# the FIRST run — so without a second surface the product is unreachable for
# all four, at its own front door.
#
# ⛔ This is NOT `--prefill` widened. `PREFILLABLE` refuses `screens` and
# `homes` because an answer carried in from somewhere else was formed without
# the photographs, and on exactly those two questions the obvious answer is
# measurably the wrong one. That refusal is untouched. What this does instead
# is move the PHOTOGRAPHS to where a terminal session can open them: the same
# exemplars the page embeds, written as files, one directory per question,
# named on the question. The owner still has to look; they look in an image
# viewer instead of a browser.
#
# ⛔ And it is checked. The sheet records a digest of the photographs it was
# written from, and `apply` refuses a sheet whose photographs are missing or
# changed. That does not force anyone to look — nothing can, and the page
# cannot either — but it does mean an answer file cannot be written from the
# census numbers alone, which is the failure that was actually observed.

SHEET_VERSION = 1

# Stamped into the sheet, then replaced by the digest of the sheet's own
# questions once they exist. Two passes rather than one because the digest is
# taken over the `>>>` lines and the header sits above them.
QUESTIONS_MARK = "__" + "QUESTIONS" + "__"

# What a sheet says about ITSELF. Held apart from the answer keys so
# `parse_lines` can refuse a key it does not recognise rather than drop it —
# the same argument `read_prefill` makes: a silently ignored answer leaves
# whoever wrote it believing it was recorded.
SHEET_HEADER = ("sheet", "generated", "owner", "files", "folders", "workdirs",
                "photographs", "evidence-digest", "questions-digest")

RULE = "# " + "-" * 74


def slugify(kind, key):
    return "%s-%s" % (kind, re.sub(r"[^A-Za-z0-9]+", "-", key).strip("-").lower())


def sheet_blocks(data):
    """-> one block per question, in the page's own order.

    The blocks ARE the page's steps: same rows, same counts, same warnings,
    same exemplars. Only the medium differs, and the two are built from one
    `build_data()` so a sheet and a page rendered from the same collection
    cannot ask different questions.
    """
    blocks = []
    for dev in data["cameras"]["devices"]:
        key = ("%s %s" % (dev["make"], dev["model"])).strip()
        blocks.append({
            "kind": "make", "key": key, "slug": slugify("make", key),
            "title": key,
            "facts": ["%d file(s), %.1f%% of everything here carrying a "
                      "camera tag" % (dev["files"], dev["share"])],
            "note": ("under 1%% of the collection — as likely a photo somebody "
                     "sent you as a phone you owned"
                     if dev["share"] < 1 else None),
            "ask": "Is this a camera you own?",
            "cost": "A make left off gets its photographs described as "
                    "somebody else's. A make wrongly added claims a friend's "
                    "camera as yours.",
            "hint": "`yes` or `no`",
            "thumbs": dev["thumbs"], "unreadable": dev["unreadable"],
            "withheld": dev.get("withheld", 0),
        })

    for cand in data["screens"]["candidates"]:
        key = "%sx%s" % (cand["dims"][0], cand["dims"][1])
        blocks.append({
            "kind": "screen", "key": key, "slug": slugify("screen", key),
            "title": key,
            "facts": ["%d file(s) at this exact size" % cand["files"]]
                     + ([cand["check"]] if cand.get("check") else [])
                     + ["if the %s is yours: %s" % (k["device"], k["text"])
                        for k in cand.get("device_checks", [])]
                     # M16b — these are MASKED at the source (`mask_name`):
                     # the date and the app word are what let an owner
                     # recognise a size, the id is what must not travel on a
                     # sheet that may be passed on. The full names are beside
                     # this sheet on local disk.
                     + (["filenames here (shortened; the full names are in "
                         "%s beside this sheet): %s"
                         % (NAMES_FILE, ", ".join(cand["names"]))]
                        if cand["names"] else []),
            "note": cand["warning"],
            "ask": "Is this the size of a screen you take screenshots on? "
                   "(You don't need to know the number: these sizes come "
                   "from your own screenshots.)",
            "cost": "⛔ This one MOVES FILES. Accepting a size files every "
                    "photograph at it as a screenshot — and the size with the "
                    "most files is routinely a resized copy of ordinary "
                    "photographs, not a screen.",
            "hint": "the device this screen belongs to, or `no`",
            "thumbs": cand["thumbs"], "unreadable": cand["unreadable"],
            "withheld": cand.get("withheld", 0),
        })

    for row in data["homes"]["rows"] + data["homes"]["near_misses"]:
        withheld = bool(row.get("missed_why"))
        blocks.append({
            "kind": "home", "key": row["id"], "slug": slugify("home", row["id"]),
            # ⛔ The title carries NO verdict. It used to append "(NOT
            # proposed as a home)", which answers "is this a home?" — the
            # question naming-first replaced. On a real dump 5 of 7 rows
            # showed that verdict directly above a question that no longer
            # asks it, and an owner reading it concludes the row wants
            # nothing from them. Every row is asking for a name; what varies
            # is only whether the engine also thinks somebody lives here, and
            # that belongs below as EVIDENCE about the place.
            "title": "Area %s" % row["id"],
            "facts": ["%d separate day(s), %d of them with a photo after dark, "
                      "%d file(s)" % (row["days"], row["night_days"],
                                      row["files"]),
                      "seen in " + ", ".join(row["units"])],
            # The census fact is still worth showing — it is D-04's whole
            # point that a withheld row is disclosed rather than hidden — but
            # said as what the photographs show, not as a ruling on the ask.
            "note": ("the engine did NOT propose this as somewhere you live: "
                     "it " + " and ".join(row["missed_why"]) + ". That is "
                     "what the photographs show about the place, not an "
                     "answer to this question — it still wants a name. It is "
                     "also what your own home looks like when you were moving "
                     "in, or spent the evenings out, so if you do live here "
                     "this row is where you say so"
                     if withheld else None),
            # ⭐ Naming FIRST (owner decision, 20260910). The old ask was
            # "Do you live here?", and the only way to say no threw the
            # owner's own name for the place away with it. Living here is now
            # an attribute of the name, so every answered row keeps a label —
            # which is what ADR 0001 needs to exist before an owner's word can
            # beat the map.
            "ask": "What do you call this place?",
            # ⛔ Ordered by what the answer actually does ON THIS ROW. The
            # privacy sentence led on all seven rows, so a place seen on two
            # days got the residence warning first and the relevant one last.
            # Both facts are on every row; only the order moves.
            "cost": ("Your word for this place is what names its folders, "
                     "instead of whatever the map service calls it. ⛔ And if "
                     "you do live here, saying so MOVES FILES and is the "
                     "privacy rule: where you live is never used as a place "
                     "name or a folder name, and that cannot be kept for a "
                     "home you leave unregistered."
                     if withheld else
                     "⛔ This one MOVES FILES, and it is the privacy rule. "
                     "Where you live is never used as a place name or a "
                     "folder name — and that cannot be kept for a home you "
                     "leave unregistered. Naming a place you do NOT live at "
                     "costs you none of that: your word for it is what names "
                     "its folders."),
            # W1C-2 — the page's buttons in the sheet's typed words. The wire
            # words are unchanged; only what they are explained as moved.
            "hint": "the name on its own for a place you visit often and "
                    "want named, `<name> live` if you live here, `<name> "
                    "visit` if you stay there sometimes, or `not a place` to "
                    "leave it out of your profile (the page's \"Don't add to "
                    "my profile\"). Optional: if you live here, write `<name> "
                    "live` — your own name keeps your address out of folder "
                    "names entirely; `live` on its own leaves the name blank "
                    "and only the city is used",
            "thumbs": row["thumbs"], "unreadable": row["unreadable"],
            "withheld": row.get("withheld", 0),
        })
    return blocks


def evidence_digest(root):
    """-> a digest of the photographs on disk, or "" if there are none.

    Path AND content, so a sheet cannot be answered next to a directory that
    has been emptied, refilled, or copied from a different collection.
    """
    if not os.path.isdir(root):
        return ""
    h = hashlib.sha256()
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            with io.open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            h.update(rel.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
            seen += 1
    return h.hexdigest() if seen else ""


def write_photographs(blocks, root):
    """The exemplars the page embeds, as files a terminal session can open."""
    written = 0
    for block in blocks:
        if not block["thumbs"]:
            continue
        folder = os.path.join(root, block["slug"])
        os.makedirs(folder, exist_ok=True)
        for i, uri in enumerate(block["thumbs"], 1):
            raw = base64.b64decode(uri.split(",", 1)[1])
            with io.open(os.path.join(folder, "%02d.jpg" % i), "wb") as fh:
                fh.write(raw)
            written += 1
    return written


SHEET_PREAMBLE = """\
# =========================================================================
#  ONBOARDING — the same checkpoint as the page, for a session with no
#  browser. Answer it here, then:
#
#      {APPLY} <this file>
#
#  ⛔ TWO OF THESE QUESTIONS CANNOT BE ANSWERED FROM THE NUMBERS, and both
#     of those two move files. The screen size with the most files is
#     routinely a resized copy of ordinary photographs; accepting it files
#     them all as screenshots. "Many separate days, including after dark"
#     is also a hotel on a long trip.
#
#  ⛔ SO OPEN THE PHOTOGRAPHS. Every block names its own, written beside
#     this file. `apply` checks they are still there, unchanged — an answer
#     written from the counts alone is the failure this checkpoint exists
#     to stop, and it is the one that was actually observed.
#
#  ⛔ NOTHING IS PRE-SELECTED. Every answer line below is blank. A blank is
#     an unanswered question and is reported as one: it is never read as a
#     yes, and never as a no.
#
#  HOW TO ANSWER: write your answer on the `>>>` line, after the `=` (or
#  after the `:` on the three at the end). Keep the key. Lines beginning
#  with # are ignored. Answer what you can and leave the rest — a partial
#  sheet is reported as partial, never completed for you.
# =========================================================================
"""


def withheld_stanza(data):
    """U3-06 — the sheet's copy of the page's coord-note. ⛔ Two copies of
    this prose exist (the template's `render()` is the other); a change to one
    is not a change to both."""
    if data.get("evidence_filtered"):
        docs = ["#     and photographs that look like a document (%s)"
                % DOCUMENT_WORDS,
                "#     are not written beside it."]
    else:
        docs = ["#  ⚠️  THE PHOTOGRAPHS WERE NOT CHECKED FOR DOCUMENTS",
                "#     (--unfiltered-evidence): %s can be among them." %
                DOCUMENT_WORDS]
    return (["#  ⛔ WHAT THIS SHEET WITHHOLDS. Coordinates are not in it "
             "(--coords-out keeps",
             "#     them on this machine),"] + docs +
            ["#     Nothing else is withheld: a photograph can still show "
             "where a place is",
             "#     — a street sign, the view from a window, a letter on a "
             "table.", ""])


def sheet_text(data, blocks, photographs, digest, workdirs=()):
    out = [SHEET_PREAMBLE.replace("{APPLY}", cli("photo_onboard_page.py")
                                  + " apply")] + withheld_stanza(data)
    out.append("sheet: %d" % SHEET_VERSION)
    out.append("generated: %s" % data["generated"])
    out.append("owner: %s" % (data["owner"] or "-"))
    out.append("files: %d" % data["files"])
    out.append("folders: %s" % ", ".join(data["units"]))
    # F-01 — where the sheet came from, so `apply` finds the collection the
    # way every stage does, wherever the sheet was written. Kept out of
    # `data`, which the page renders.
    if workdirs:
        out.append("workdirs: %s" % json.dumps(list(workdirs), ensure_ascii=False))
    out.append("photographs: %s" % photographs)
    out.append("evidence-digest: %s" % (digest or "-"))
    out.append("questions-digest: %s" % QUESTIONS_MARK)
    out.append("")
    for spec in data.get("device_specs") or []:
        out.append("# LOOKED UP, NOT MEASURED — %s" % spec["label"])
    if data.get("device_specs"):
        out.append("")

    kinds = Counter(b["kind"] for b in blocks)
    seen = Counter()
    for block in blocks:
        seen[block["kind"]] += 1
        out.append(RULE)
        out.append("# %s %d of %d — %s"
                   % ({"make": "CAMERA", "screen": "SCREEN SIZE",
                       "home": "PLACE"}[block["kind"]],
                      seen[block["kind"]], kinds[block["kind"]], block["title"]))
        for fact in block["facts"]:
            out.append("#     %s" % fact)
        if block["note"]:
            out.append("#     ⚠️  %s" % block["note"])
        if block["thumbs"]:
            out.append("#   PHOTOGRAPHS: %s/%s/  (%d file(s)) — open these"
                       % (photographs, block["slug"], len(block["thumbs"])))
        else:
            # ⛔ Never a silent short strip. On the page an empty strip reads
            # as "few photos here"; in a text file a missing line reads as
            # nothing at all, which is worse.
            out.append("#   PHOTOGRAPHS: NONE — %s"
                       % ("could not open %d file(s) here; this is not a "
                          "picture of how many there are"
                          % block["unreadable"] if block["unreadable"]
                          else "every one found looks like a document, see "
                               "below" if block["withheld"]
                          else "there are no files to show"))
        if block["withheld"]:
            # Names the KIND, never what the frame showed — the page's
            # strip() says the same, and must.
            out.append("#   WITHHELD: %d photograph(s) here look like a "
                       "document (%s) and were" % (block["withheld"],
                                                   DOCUMENT_WORDS))
            out.append("#     not written, because this sheet may be passed "
                       "on. For privacy concern, please open the folder "
                       "itself if you need them.")
        out.append("#   %s  Write %s" % (block["ask"], block["hint"]))
        out.append("#   %s" % block["cost"])
        out.append(">>> %s: %s =" % (block["kind"], block["key"]))
        out.append("")

    # F3 — the page reports what its cap and its one-visit filter cut, and the
    # sheet used to report neither: a withheld place past the cap was on one
    # surface and silent on the other.
    homes = data["homes"]
    listed = (["home " + h for h in homes.get("already_listed") or []]
              + ["screen size " + d for d in
                 (data["screens"].get("already_listed") or [])])
    if listed:
        out.append(RULE)
        out.append("# ALREADY IN YOUR PACK — not asked again: "
                   + "; ".join(listed) + ".")
        out.append("")
    cut = []
    if homes.get("near_misses_over_cap"):
        cut.append("%d more place(s) that missed a home test"
                   % homes["near_misses_over_cap"])
    if homes.get("near_misses_one_day_only"):
        cut.append("%d place(s) seen on a single daytime visit"
                   % homes["near_misses_one_day_only"])
    if cut:
        out.append(RULE)
        out.append("# NOT LISTED: " + "; ".join(cut) + ".")
        out.append("#   If the place you live is not above, tell the session: "
                   "the census prints")
        out.append("#   every place it withheld with")
        out.append("#   %s %s --all-places"
                   % (cli("photo_census.py"),
                      quoted(workdirs[0]) if len(workdirs) == 1 else '"<work dir>"'))
        out.append("")

    out.append(RULE)
    out.append("# THE THREE WORD QUESTIONS — no photographs, and none needed.")
    out.append("#   language: which language names the folders the engine "
               "always makes,")
    out.append("#     and which language it asks the map service for. One of: %s"
               % ", ".join(lang["code"] for lang in data["languages"]))
    out.append("#     Any other falls back to English, and every stage says so "
               "when it does.")
    # W1C-3 — the page's own sentence, verbatim (language_note()).
    out.append("#     %s" % data["language_note"])
    out.append(">>> language:")
    out.append("")
    out.append("#   types: the kinds of folder you sort by, comma separated.")
    out.append("#     ⛔ What you write here BECOMES the list — anything else "
               "is refused")
    out.append("#     at sorting time, including the words below. So write "
               "kinds, not a")
    out.append("#     sentence: no \"a\"/\"an\", one word or hyphenated "
               "phrase each.")
    out.append("#     Left blank this run uses the set for the language you "
               "named above:")
    for row in data["type_defaults"]:
        out.append("#       %-6s %s" % (row["code"], ", ".join(row["words"])))
    out.append(">>> types:")
    out.append("")
    out.append("#   away_km: how far from home is still 'home', in km. "
               "Nothing else in")
    out.append("#     this pipeline asks it. Left blank this run uses %s; "
               "too high," % data["away_km_default"])
    out.append("#     every day trip you take is filed as a day at home and "
               "whole weeks")
    out.append("#     merge into one folder.")
    out.append(">>> away_km:")
    out.append("")
    out.append("#   pets: your pets, the ones that live with you, comma "
               "separated — the names you")
    out.append("#     actually call them. Each one becomes a record the engine "
               "can attach")
    out.append("#     photographs to later; it attaches NOTHING now, and never "
               "guesses which")
    out.append("#     pet is which. Naming them here is how it can tell you "
               "\"you said")
    out.append("#     three, I have found two\" instead of leaving the third's "
               "absence")
    out.append("#     invisible. Left blank, nothing is created and nothing is "
               "lost — the")
    out.append("#     engine still learns them from the photographs.")
    out.append("#   ⛔ Animals only. People are not recognised by this engine "
               "at all.")
    out.append(">>> pets:")
    out.append("")
    if not (data.get("country") or {}).get("known"):
        # K20 / C5 — the page's own question, asked here only as text: the
        # sheet cannot see which home you will answer "live".
        boxes = ", ".join(sorted(photo_cluster.COUNTRY_BOXES))
        out.append("#   country: mark this country as your primary home "
                   "country? Only if a home")
        out.append("#     you answer `live` above is OUTSIDE %s: write its "
                   "two-letter code" % boxes)
        out.append("#     (ISO 3166-1, e.g. US, JP, NZ). Nothing goes online "
                   "for this. Left blank,")
        out.append("#     no day is called abroad.")
        out.append(">>> country:")
        out.append("")
    # W1C-5 — the page's closing blocks, verbatim (disclaimer(), NEXT_STEPS).
    out.append(RULE)
    out.append("# DISCLAIMER")
    for line in data["disclaimer"]:
        out.append("#   - %s" % line)
    out.append("#")
    out.append("# NEXT STEPS — %s" % data["next_intro"])
    for n, (title, text) in enumerate(data["next_steps"], 1):
        out.append("#   %d. %s" % (n, title))
        out.append("#      %s" % text)
    out.append("")
    return "\n".join(out)


def cmd_sheet(args):
    arm_evidence_filter(args.unfiltered_evidence)
    full_names = []
    data, homes_with_coords = build_data(args.targets, args.profile,
                                         with_coords=args.with_coords,
                                         prefill=None,
                                         device_specs=args.device_spec,
                                         full_names=full_names)
    os.makedirs(args.out_dir, exist_ok=True)
    if any(c["names"] for c in full_names):
        write_names_file(os.path.join(args.out_dir, NAMES_FILE), full_names)
    blocks = sheet_blocks(data)
    root = os.path.join(args.out_dir, "photographs")
    shutil.rmtree(root, ignore_errors=True)
    written = write_photographs(blocks, root)
    digest = evidence_digest(root)

    workdirs = [os.path.abspath(t if os.path.isdir(t) else os.path.dirname(t))
                for t in args.targets]
    text = sheet_text(data, blocks, "photographs", digest, workdirs)
    text = text.replace(QUESTIONS_MARK, questions_digest(text))
    answers = os.path.join(args.out_dir, "answers.txt")
    with io.open(answers, "w", encoding="utf-8") as fh:
        fh.write(text)

    print("wrote %s and %d photograph(s) under %s"
          % (answers, written, root))
    if not args.with_coords:
        if args.coords_out:
            write_coords(args.coords_out, homes_with_coords)
            print("  coordinates are NOT in the sheet; they are in %s"
                  % args.coords_out)
        else:
            print("  coordinates are NOT in the sheet, and were not written "
                  "anywhere (--coords-out to keep them)")
        print("  (the photographs are, and a photograph can still show where "
              "a place is)")
    report_counts(data, "sheet")
    return 0


# ------------------------------------------------------------------- answers

# ⛔ `pets` is UNKEYED, like `makes`/`language`/`types` and unlike
# `make`/`screen`/`home`. A keyed `pet: <n> = <name>` would have to grow
# `sheet_subjects()`'s hardcoded three-kind vocabulary and change the shape of
# an existing stem; unkeyed it only ADDS a stem, which no already-written sheet
# carries and none of them is invalidated by (`questions_digest` is computed
# over a sheet's own text at write time, so an old sheet still re-digests to
# the value it stored).
ANSWER_KEYS = ("make", "makes", "screen", "home", "language", "types",
               "away_km", "pets", "country")


# The words that REJECT a proposed area outright. ⛔ `not a home` is NOT one
# of them and must never be added back: under naming-first it describes the
# KEPT case (a place the owner named but does not live at), so the three words
# that used to throw a row away now describe the row that must survive. A
# silent meaning flip is invisible to `questions_digest`, which pins the STEMS
# and never the answer vocabulary — so it is refused loudly in
# `_home_answer()` instead, naming the words that replaced it.
DROP_WORDS = ("not a place", "skip", "no", "drop")

# The attribute a label may carry. Naming is the question; living there is an
# answer ABOUT the name, which is why a bare label is already complete and
# these two are suffixes on it rather than the choice itself.
HOME_KINDS = ("live", "visit")


def _home_answer(value):
    """-> {"kind": live|visit|place|drop, "label": str} for one `home:` answer.

    ⭐ **Naming is the primary question** (owner decision, 20260910). The ask
    is *what do you call this place?*, and whether the owner lives there is an
    attribute of that answer. So a bare label is a complete answer — kind `place` — and
    the row is KEPT carrying the owner's own word rather than thrown away.
    That is ADR 0001's precondition: the owner's word beats the geocoder
    *wherever an owner label exists*, and before this no label could exist for
    a place that was not a residence. The old shape returned
    `{"kind": "drop", "label": ""}` for `not a home` — it took a name the
    owner had typed and discarded it.

    ⛔ Rejecting a row is still reachable, through `DROP_WORDS`. An owner must
    be able to refuse a proposed area outright; a row the engine invented is
    exactly the row that needs refusing, and losing that is a regression.

    ⛔ An EMPTY label with `live` still registers the home. Suppression is
    COORDINATE-based (`photo_where` reads `home_locations` and withholds on the
    coordinate alone), so making a name mandatory would cost an owner who
    declines to name their own front door the privacy rule itself. `(unnamed)`
    is what the page prints for that case, and it round-trips to "".

    ⛔ Both wordings are accepted because there are two sources and only one
    grammar: this sheet, and the page's own "copy the lines yourself" button,
    which is the escape hatch an owner reaches for when the page renders but
    cannot send. Refusing what the page prints would leave that owner holding
    an answer nothing reads — which is the defect, one surface along.
    """
    low = value.lower().strip()
    if low == "not a home":
        raise SystemExit(
            "home answer 'not a home': that wording no longer has one meaning. "
            "The question is now what you CALL this place, and a place you "
            "name but do not live at is KEPT, not dropped. Write `not a place` "
            "to reject the row outright, or write the name on its own to keep "
            "it as a place you have named.")
    if low in DROP_WORDS:
        return {"kind": "drop", "label": ""}
    for kind in HOME_KINDS:
        if low == kind or low.endswith(" " + kind):
            label = value[:-len(kind)].strip() if low != kind else ""
            if label == "(unnamed)":      # what the page prints for an empty one
                label = ""
            return {"kind": kind, "label": label}
    # ⛔ `(unnamed)` is what the page prints for an EMPTY label. With a kind
    # word after it that is a real answer (a home the owner declined to name,
    # which still registers — suppression is coordinate-based). On its own it
    # is not: naming is the whole question here, so there is nothing left of
    # the answer. Refuse it rather than let the literal string `(unnamed)`
    # through as somebody's word for a place and out onto a folder.
    if low == "(unnamed)":
        raise SystemExit(
            "home answer '(unnamed)': a place kept for its NAME has to have "
            "one. Write what you call it, add `live` or `visit` if you stay "
            "there, or write `not a place` to reject the row.")
    # Anything else IS the name. Naming-first means a label needs no keyword to
    # be an answer; the keyword is what adds "and I live here" to it.
    return {"kind": "place", "label": value.strip()}


def parse_lines(text, known=None):
    """-> the answers written on a sheet, or copied off the page.

    ⛔ ONE grammar, and this only ever READS it. The keys are the page's own
    (`photo_profile`-free, literal ASCII, never translated) because the page
    already prints them on its Copy button, so an owner who can see the page
    but cannot send it pastes those lines straight into a file and applies
    them. A second grammar here would have meant a second thing to keep in
    step, and the page is the one that cannot be changed after it ships —
    it carries its own template.

    `known` is what the sheet or page actually asked about. An answer naming
    a row that was never put to the owner is REFUSED, not stored: it is the
    signature of an answer written from the census table instead of from the
    photographs, and it would name a place the owner never saw.
    """
    known = known or {}
    out = {"lines": [], "makes": {}, "own_camera_makes": [], "screens": {},
           "homes": {}, "language": "", "types": "", "away_km": "",
           "pets": "", "country": "", "header": {}, "blank": []}

    def check(kind, subject):
        pool = known.get(kind)
        if pool is not None and subject not in pool:
            raise SystemExit(
                "%s: %r was never asked about. The rows put to the owner were: "
                "%s" % (kind, subject, ", ".join(sorted(pool)) or "(none)"))

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(">>>"):
            line = line[3:].strip()
        if not line or line.startswith("#"):
            continue
        key, sep, rest = line.partition(":")
        key = key.strip().lower()
        if not sep:
            continue
        if key in SHEET_HEADER:
            out["header"][key] = rest.strip()
            continue
        if key not in ANSWER_KEYS:
            raise SystemExit(
                "%r is not an answer this stage knows. The keys are: %s"
                % (key, ", ".join(ANSWER_KEYS)))

        rest = rest.strip()
        if key in ("make", "screen", "home"):
            subject, eq, value = rest.partition("=")
            subject, value = subject.strip(), value.strip()
            if not eq and key != "screen":
                out["blank"].append("%s: %s" % (key, subject))
                continue
            if eq and not value:
                out["blank"].append("%s: %s" % (key, subject))
                continue
            check(key, subject)
            out["lines"].append(line)
            if key == "make":
                if value.lower() not in ("yes", "no"):
                    raise SystemExit(
                        "make answer %r: write `yes` if it is a camera you "
                        "own, `no` if it is not." % value)
                out["makes"][subject] = value.lower() == "yes"
            elif key == "screen":
                # No `=` at all is the page's own form for an accepted size
                # with no device named; `= no` is this sheet's refusal.
                out["screens"][subject] = False if value.lower() == "no" else value
            else:
                out["homes"][subject] = _home_answer(value)
            continue

        if not rest:
            out["blank"].append(key)
            continue
        out["lines"].append(line)
        if key == "makes":
            for make in [m.strip() for m in rest.split(",") if m.strip()]:
                # The page collapses its per-device answers to a make list, so
                # this form carries no model and cannot be checked against one.
                out["own_camera_makes"].append(make)
        elif key == "away_km":
            try:
                float(rest)
            except ValueError:
                raise SystemExit(
                    "away_km %r is not a number of kilometres. Left wrong it "
                    "does not fail — it silently files every day trip as a "
                    "day at home." % rest)
            out["away_km"] = rest
        elif key == "country":
            code = rest.strip().upper()
            if code not in ISO2:
                raise SystemExit(
                    "country %r is not a two-letter country code (ISO 3166-1, "
                    "for example TW or US). Left wrong it does not fail — it "
                    "turns off the test that tells a day abroad from a day at "
                    "home." % rest)
            out["country"] = code
        else:
            out[key] = rest

    for device, mine in out["makes"].items():
        if not mine:
            continue
        make = device.split(" ")[0]
        if make not in out["own_camera_makes"]:
            out["own_camera_makes"].append(make)
    return out


def pet_names(raw):
    """-> the animal names on a `pets:` line, in order, de-duplicated.

    ⛔ Case-INSENSITIVE de-duplication, but the owner's own casing is what is
    kept: two records for one animal is the exact failure ADR 0004 exists to
    remove ("one name spread across several records becomes unanswerable"), and
    a first run is where it would be minted.

    ⛔ No vocabulary, no species list, no validation of the name itself. A pet
    name is the owner's word in the owner's language (Rule 8), and there is
    nothing to check it against — the same reason `[what]` can never be
    validated against a list.
    """
    seen, names = set(), []
    for part in raw.split(","):
        name = part.strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        names.append(name)
    return names


def question_stems(text):
    """-> the QUESTIONS a sheet asks, in order, with the answers cut off.

    A stem is everything the owner is told to keep: the key, and for the three
    keyed kinds the subject up to the `=`. What they write after it is not
    part of it, so a sheet's stems are identical before and after it is
    answered — which is what lets the digest below pin them.
    """
    stems = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith(">>>"):
            continue
        key, sep, rest = line[3:].strip().partition(":")
        key = key.strip().lower()
        if not sep or key not in ANSWER_KEYS:
            continue
        if key in ("make", "screen", "home"):
            stems.append("%s|%s" % (key, rest.partition("=")[0].strip()))
        else:
            stems.append(key)
    return stems


def questions_digest(text):
    """A digest over the questions, so the sheet cannot grow one.

    ⛔ Without this the subject check below is VACUOUS on a sheet: `known` is
    read off the file's own lines, so a row typed in by hand declares itself
    as a question that was asked. Measured while building this — an invented
    `home: Z = Somewhere live` was accepted, and a home the owner never saw a
    photograph of is exactly the row that must not get through. The digest is
    over the stems, so answering the sheet does not disturb it and adding or
    deleting a question does.
    """
    h = hashlib.sha256()
    for stem in question_stems(text):
        h.update(stem.encode("utf-8") + b"\n")
    return h.hexdigest()


def sheet_subjects(text):
    """-> what this file put to the owner, blank answers included.

    Read off the file's own `>>>` lines rather than rebuilt from the
    collection: `apply` must be able to check an answer against the questions
    THIS sheet asked, and the collection may have been re-scanned since. Safe
    to trust only because `questions_digest` pins the same lines.
    """
    known = {"make": set(), "screen": set(), "home": set()}
    for stem in question_stems(text):
        kind, sep, subject = stem.partition("|")
        if sep:
            known[kind].add(subject)
    return {k: v for k, v in known.items() if v}


# -------------------------------------------------------------------- apply

RE_DATA = re.compile(
    r'<script id="onboard-data" type="application/json">(.*?)</script>',
    re.S)


def read_submitted(html):
    """-> the answers the owner submitted, or None if they have not yet.

    Read out of the page's own data block, which is what the page republishes
    itself with. ⛔ Never re-derived from the rendered markup: the page is
    regenerated from its data, so the data is the record and the markup is a
    view of it.
    """
    match = RE_DATA.search(html)
    if not match:
        raise SystemExit("no onboard-data block in that file — is it an "
                         "onboarding page?")
    return json.loads(match.group(1)).get("submitted")


NOT_WRITTEN = ("\n⛔ Not written. Read the answers above, then write the pack "
               "yourself — this stage never writes a profile, for the same "
               "reason photo_census never does: a proposal the owner "
               "confirmed is still the owner's to place.")


# ------------------------------------------------------- writing the pack ---

# The coordinate rows `--coords-out` wrote at render/sheet time: a row letter,
# then "lat, lon". ⛔ This is the ONLY way a coordinate reaches `apply`. The
# sheet header carries `sheet`/`generated`/`owner`/`files`/`folders`/
# `photographs`/`evidence-digest`/`questions-digest` and the page's data block
# carries the same — by design, because a coordinate must not travel to a
# surface the owner did not choose (Operational Rule 3). `apply` has no work
# dirs and never calls `build_data()`, so it cannot re-derive one either.
# Two files, ONE reader. `render`/`sheet` write `A  <lat>, <lon>  ...`; the
# census writes `place 1: <lat>, <lon>` beside the manifest. Both keep the pair
# off the screen and both key it by the token the owner can see, so both are
# read here rather than by a second reader — the same discipline that keeps
# `home_points()` a slice of `labelled_home_points()` instead of a second
# reader of `home_locations` (M4, owner ruling 20260920).
RE_COORD_ROW = re.compile(r"^(?:place\s+(\d+)\s*:|([A-Za-z])\s)\s*"
                          r"(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)(?:\s|$)")


def cli(script, crops=False):
    """H-C C4 / H-I — a printed next step that runs from any folder: the one
    rule `photo_index.run_line()` keeps (full interpreter and script path;
    the pages' python when the stage makes crops or reads photographs)."""
    import photo_index
    return photo_index.run_line(script, crops=crops)


def quoted(path):
    return '"%s"' % path


def check_places_stamp(path):
    """STOP if a census places file no longer matches the manifest it came
    from (Q7, owner ruling 20260920).

    The place NUMBERS in that file are per-run — they enumerate this census's
    own home candidates and near misses — so a re-run over a changed manifest
    can renumber them. An answer keyed to a stale number registers a
    coordinate the owner never confirmed, and a wrong home address saved
    silently is a Rule 3 failure, not untidiness. The owner chose a refusal
    over a warning for exactly that reason.

    ⛔ Three things this must NOT do, each one measured or ruled:
      * fire on a file that never carried a stamp — `render`/`sheet` write a
        lettered coords file with no manifest beside it, and that is the path
        M4's home registration runs on;
      * name a place or a coordinate in the refusal (the file exists to keep
        those off every surface);
      * grow a second reader of the places file — this is called from
        `read_coords()`, which stays the one reader.
    """
    stamp = None
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip().startswith(photo_census.STAMP_PREFIX):
                stamp = line.split(photo_census.STAMP_PREFIX, 1)[1].strip()
                break
    if not stamp:
        return                      # a lettered coords file: nothing to check
    manifest = pathlib.Path(path).parent / "manifest.csv"
    if not manifest.exists():
        raise SystemExit(
            "%s was written from a manifest that is not beside it any more, "
            "so its numbered places cannot be checked.\n"
            "  Those numbers belong to one census run. Re-run\n"
            "      %s %s\n"
            "  and answer the list it prints."
            % (path, cli("photo_census.py"), quoted(pathlib.Path(path).parent)))
    now = photo_census.manifest_stamp(manifest)
    if now != stamp:
        raise SystemExit(
            "%s is out of date: the manifest beside it has changed since it "
            "was written.\n"
            "  Its place numbers belong to the earlier run, so an answer "
            "given against them could register the wrong place.\n"
            "  Re-run\n"
            "      %s %s\n"
            "  and answer the numbers it prints now."
            % (path, cli("photo_census.py"), quoted(pathlib.Path(path).parent)))


def read_coords(path):
    """-> {row letter: (lat, lon)} off the file `--coords-out` wrote.

    ⛔ Parsed, never re-measured. `apply` reads an answer file and nothing
    else; the coordinates it needs to register a home were measured at render
    or sheet time, and this is the file that kept them off the page.
    """
    out = {}
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            match = RE_COORD_ROW.match(line.strip())
            if match:
                # `place 1:` keys on the number the census report showed; a
                # lettered row keys on its letter. Either way the key is the
                # token the OWNER can see, and the pair stays here.
                key = match.group(1) or match.group(2).upper()
                out[key] = (float(match.group(3)), float(match.group(4)))
    if not out:
        raise SystemExit(
            "%s holds no coordinate rows. Expected the file `render` or "
            "`sheet` wrote with --coords-out (`A  <lat>, <lon>  ...`), or the "
            "`census-places.txt` the census wrote beside the manifest "
            "(`place 1: <lat>, <lon>`)." % path)
    check_places_stamp(path)
    return out


def away_km_number(raw):
    """-> the owner's home range as a NUMBER, int where it is whole.

    ⛔ Never the string `parse_lines` carries. `away_km_answered()` compares
    the pack value against `AWAY_KM_DEFAULT`, and a string is never equal to
    3.0 — so writing "3" would make an owner who answered exactly the shipped
    number read as answered BY DIFFERENCE, which is true by accident and for
    the wrong reason. Every arithmetic reader downstream wants a number too.
    """
    value = float(raw)
    return int(value) if value == int(value) else value


def _screen_dims(screens):
    """-> `screen_dims` rows for the sizes the owner ACCEPTED.

    A `False` is a refusal and contributes nothing; a size with no device
    named still counts as accepted, and carries `model: None` rather than
    being dropped — the pack's own comment says an unpaired size cannot be
    audited, and a missing one cannot even be seen.
    """
    rows = []
    for dims, value in sorted(screens.items()):
        if value is False:
            continue
        try:
            wide, high = [int(n) for n in dims.lower().split("x")]
        except ValueError:
            raise SystemExit(
                "screen answer %r: expected a size like 1170x2532." % dims)
        rows.append({"model": value if isinstance(value, str) else None,
                     "dims": [wide, high]})
    return rows


def _declined_dims(screens):
    """-> `declined_screen_dims` rows ([w, h]) for the sizes answered `no`."""
    rows = []
    for dims, value in sorted(screens.items()):
        if value is not False:
            continue
        try:
            rows.append([int(n) for n in dims.lower().split("x")])
        except ValueError:
            raise SystemExit(
                "screen answer %r: expected a size like 1170x2532." % dims)
    return rows


def pack_updates(answers, coords, profile, entities, add_screens=frozenset(),
                 status=None, screen_gate=None):
    """-> ([(where, what, value)], [refusals]) — the whole write, decided
    before any of it happens.

    ⭐ Q-b (owner ruling 20260924): SAVE THE SAFE ANSWERS. Each key is decided
    on its own and an unsafe one is refused alone; `write_pack()` writes the
    rest. `status`, when given, collects one (key, verdict, text) line per
    answer — verdict add / merge / already listed / refuse — so the dry run
    and the write both say what each answer does (F-gg).

    `add_screens` is the set of NEW screen sizes (portrait) the owner said yes
    to after the dry run showed what they move (Q-c, `--add-screen`).
    `screen_gate` ({size: refusal text or None}, from `screen_gate()`) says
    whether each NEW size could be counted and was ever offered; a new size
    it does not clear is refused, so the dry run and the write print the same
    line (Card 9). None clears nothing.

    ⛔ **Clobbering is judged against what the owner chose, never against what
    is present.** The template WRITES most of these keys, so presence proves
    nothing — the same trap `photo_cluster.away_km_answered()` exists for, and
    the reason this asks that function rather than testing the key itself.
    """
    plan, refuse = [], []
    if status is None:
        status = []

    def differs(old, new):
        return old not in (None, "", [], {}) and old != new

    def said(key, verdict, text=""):
        status.append((key, verdict, text))

    if answers["language"]:
        old = profile.get("language")
        # The template ships "en". An owner who never answered has exactly
        # that, so only a value they cannot have inherited is a conflict.
        if old and old != answers["language"] and old != "en":
            refuse.append("language is already %r in the pack and the answers "
                          "say %r. Nothing here can tell which is the owner's "
                          "— fix one of them by hand." % (old, answers["language"]))
            said("language", "refuse", refuse[-1])
        elif old == answers["language"]:
            said("language", "already listed", old)
        else:
            plan.append(("photo-profile.json", "language", answers["language"]))
            said("language", "add", answers["language"])

    if answers.get("country"):
        # K20 / C5 — ONE primary home country per owner (U2-04). Read through
        # the one reader; a different answer over a declared one is refused.
        old = photo_profile.country(profile)
        if old and old != answers["country"]:
            refuse.append("country is already %r in the pack and the answers "
                          "say %r. One owner has one home country — fix it "
                          "by hand if it really changed." % (old, answers["country"]))
            said("country", "refuse", refuse[-1])
        elif old:
            said("country", "already listed", old)
        else:
            plan.append(("photo-profile.json", "country", answers["country"]))
            said("country", "add", answers["country"])

    if answers["types"]:
        types = [t.strip() for t in answers["types"].split(",") if t.strip()]
        old = (profile.get("naming_spec") or {}).get("types") or []
        if differs(old, types):
            refuse.append("naming_spec.types already holds %d word(s) and the "
                          "answers give %d different one(s). What the owner "
                          "writes here BECOMES the list, so this is not a "
                          "merge." % (len(old), len(types)))
            said("naming_spec.types", "refuse", refuse[-1])
        elif old == types:
            said("naming_spec.types", "already listed", ", ".join(types))
        else:
            plan.append(("photo-profile.json", "naming_spec.types", types))
            said("naming_spec.types", "add", ", ".join(types))

    if answers["own_camera_makes"]:
        old = profile.get("own_camera_makes") or []
        merged = list(old) + [m for m in answers["own_camera_makes"]
                              if m not in old]
        if merged != old:
            plan.append(("photo-profile.json", "own_camera_makes", merged))
            said("own_camera_makes", "merge" if old else "add",
                 "%s (kept: %s)" % (", ".join(m for m in merged if m not in old),
                                    ", ".join(old) or "none"))
        else:
            said("own_camera_makes", "already listed", ", ".join(old))

    # FIX6 (U6-37) — a `no` is remembered, so no later run asks it again.
    # Merged, never refused: it adds sizes the owner turned down.
    declined = _declined_dims(answers["screens"])
    if declined:
        old = profile.get("declined_screen_dims") or []
        merged = list(old) + [d for d in declined if d not in old]
        if merged != old:
            plan.append(("photo-profile.json", "declined_screen_dims", merged))
            said("declined_screen_dims", "merge" if old else "add",
                 ", ".join("%sx%s" % tuple(d) for d in merged if d not in old))
        else:
            said("declined_screen_dims", "already listed",
                 ", ".join("%sx%s" % tuple(d) for d in declined))

    # ⭐ F-hh / Q-c — a UNION, never a replacement: a second phone ADDS its
    # size and no size is ever removed here. A size the pack already holds is
    # "already listed"; a NEW one moves files, so it is written only when the
    # owner said yes to the dry run's preview (`--add-screen WxH`), and is
    # otherwise refused on its own.
    screens = _screen_dims(answers["screens"])
    if screens:
        old = list(profile.get("screen_dims") or [])
        have = photo_census.pack_screen_sizes(profile)
        added = []
        for entry in screens:
            size = tuple(sorted(entry["dims"]))
            shown = "%sx%s" % tuple(entry["dims"])
            blocked = ((screen_gate or {}).get(size, "no count was made of "
                                                   "what it moves")
                       if size not in have else None)
            if size in have:
                said("screen_dims", "already listed", shown)
            elif blocked:
                refuse.append("screen size %s is NEW and it MOVES FILES, and "
                              "%s. Nothing was written for it." % (shown, blocked))
                said("screen_dims", "refuse", refuse[-1])
            elif size in add_screens:
                added.append(entry)
                said("screen_dims", "add", shown + (" (%s)" % entry["model"]
                                                    if entry["model"] else ""))
            else:
                refuse.append(
                    "screen size %s is NEW and it MOVES FILES — show the owner "
                    "the dry run's count of what it moves, and only after "
                    "their yes re-run with --add-screen %s" % (shown, shown))
                said("screen_dims", "refuse", refuse[-1])
        if added:
            plan.append(("photo-profile.json", "screen_dims", old + added))

    if answers["away_km"]:
        want = away_km_number(answers["away_km"])
        old = (profile.get("cluster_defaults") or {}).get("away_km")
        if photo_cluster.away_km_answered(profile) and old != want:
            refuse.append("cluster_defaults.away_km is %r and was already "
                          "answered by the owner; these answers say %r."
                          % (old, want))
            said("cluster_defaults.away_km", "refuse", refuse[-1])
        elif photo_cluster.away_km_answered(profile):
            said("cluster_defaults.away_km", "already listed", str(want))
        else:
            plan.append(("photo-profile.json", "cluster_defaults.away_km", want))
            said("cluster_defaults.away_km", "add", str(want))
            # ⭐ A44. The value alone is not the answer: the template writes
            # `away_km` too, so an owner who answers exactly the shipped 3
            # would be indistinguishable from one who never saw the question
            # and would be warned on every batch forever. THIS is the flag's
            # only writer.
            plan.append(("photo-profile.json",
                         "cluster_defaults.away_km_answered", True))

    homes, places = [], []
    pack_homes = photo_census.pack_home_rows(profile)
    for row_id, answer in sorted(answers["homes"].items()):
        if answer["kind"] == "drop":
            continue
        # ⛔ EVERY kept row needs its coordinate, a named non-home included.
        # The ROW LETTER is not a substitute and is deliberately never stored:
        # it is assigned by this render's own proposal ordering, so it names a
        # different place after a re-scan. The coordinate is the only thing
        # that can ever bind the owner's word to a batch — a label stored
        # without one is not "unread yet", it is unreadable in principle,
        # which is the same defect this branch exists to close.
        point = coords.get(row_id.upper())
        if point is None:
            refuse.append(
                "row %s was answered and there is no coordinate for it. %s "
                "The answers never carry one, by design — pass --coords-in "
                "with the file render/sheet wrote via --coords-out."
                % (row_id,
                   "A home is registered BY COORDINATE; that is how its name "
                   "is withheld." if answer["kind"] != "place" else
                   "A named place is stored BY COORDINATE; the name is the "
                   "owner's word for somewhere, and nothing can find that "
                   "somewhere again without it."))
            said("home " + row_id, "refuse", refuse[-1])
            continue
        # ⭐ F-ff / F-nn — the census's own test: an answer at a home the pack
        # already holds is ALREADY LISTED, not a clash, whatever it was called.
        # The pack's row is kept as it is (its label, its id, its window).
        if answer["kind"] != "place":
            hit = photo_census.listed_as({"coord": point}, pack_homes)
            if hit is not None:
                said("home " + row_id, "already listed",
                     "as %s (%s) — kept as it is" % (
                         hit.get("label") or "(unnamed)", hit.get("id") or "no id"))
                continue
        if answer["kind"] == "place":
            # ⛔ A named place is NOT a residence, so nothing here is
            # withheld: OA-23 (owner, 20260827) settled that a frequent
            # place needs no key and its GPS is not sensitive. The
            # coordinate-based suppression rule reads `home_locations` and is
            # untouched by this list.
            places.append({"label": answer["label"],
                           "lat": point[0], "lon": point[1]})
            continue
        entry = {"label": answer["label"], "lat": point[0], "lon": point[1]}
        if answer["kind"] == "visit":
            # `home_range: false` narrows the batch LABEL and never
            # suppression — a residence travelled to is still never named.
            entry["home_range"] = False
        homes.append(entry)
    # ⭐ D-I15 — each row gets its fixed id here, numbered after the pack's
    # mark, so an id is never re-issued even to a pack whose list is empty
    # because the owner deleted every row by hand.
    #
    # ⭐ G6 — a list that already holds entries is APPENDED to, not refused:
    # a second place named mid-run is exactly the SNL case. The rows already
    # there keep their ids and their order. A new row that names the same
    # label, or sits within the radius that already answers for an existing
    # row, is still refused — that is a merge, and a merge stays the owner's.
    home_key, place_key = (photo_profile.HOME_LOCATIONS_KEY,
                           photo_profile.FREQUENT_PLACES_KEY)
    for where, key, rows, data, radius, why in (
            ("photo-profile.json", home_key, homes, profile, HOME_MATCH_KM,
             "A residence is the one thing here that is never guessed at — "
             "merge it by hand."),
            ("photo-entities.json", place_key, places, entities,
             photo_profile.named_place_km(profile),
             "Merge the new names by hand.")):
        if not rows:
            continue
        old = data.get(key) or []
        # The same label at the same place is the answer the pack already
        # holds — already listed, not a clash (F-ff/F-nn, for named places).
        fresh = []
        for new in rows:
            same = next((e for e in old if same_place(e, new, radius)), None)
            if same is not None:
                said(key, "already listed", "%s (%s)" % (
                    same.get("label") or "(unnamed)", same.get("id") or "no id"))
            else:
                fresh.append(new)
        rows = fresh
        if not rows:
            continue
        clashes = place_clashes(old, rows, radius)
        if clashes:
            refuse.append("%s already holds %s. %s"
                          % (key, "; ".join(clashes), why))
            said(key, "refuse", refuse[-1])
            continue
        said(key, "add" if not old else "merge",
             ", ".join(r["label"] or "(unnamed)" for r in rows))
        mark_key = photo_profile.PLACE_IDS[key][3]
        combined = list(old) + rows
        mark, assigned = photo_profile.assign_place_ids(combined, key,
                                                        data.get(mark_key))
        for i, pid in assigned:
            if i >= len(old):      # an old row with no id is backfill's to fix
                combined[i] = {"id": pid, **combined[i]}
        plan.append((where, key, combined))
        plan.append((where, mark_key, mark))
    return plan, refuse


def same_place(entry, new, radius):
    """-> is `entry` (a pack row) the same label within `radius` of `new`?"""
    if not isinstance(entry, dict) or (entry.get("label") or "").strip().casefold() \
            != (new["label"] or "").strip().casefold():
        return False
    try:
        there = (float(entry["lat"]), float(entry["lon"]))
    except (KeyError, TypeError, ValueError):
        return False
    return photo_cluster.haversine_km(there, (new["lat"], new["lon"])) <= radius


def place_clashes(old, rows, radius):
    """-> why each new row cannot simply be appended to `old`: the same label,
    or within `radius` km of a row already there. Never a coordinate in the
    reason, only the label and the id."""
    out = []
    for new in rows:
        for entry in old:
            if not isinstance(entry, dict):
                continue
            said = "%s (%s)" % (entry.get("label") or "(unnamed)",
                                entry.get("id") or "no id")
            label = (entry.get("label") or "").strip().casefold()
            if label and label == (new["label"] or "").strip().casefold():
                out.append("a row with the label %s" % said)
                break
            try:
                there = (float(entry["lat"]), float(entry["lon"]))
            except (KeyError, TypeError, ValueError):
                continue
            if photo_cluster.haversine_km(there, (new["lat"], new["lon"])) <= radius:
                out.append("%s within %s km of the new row %r"
                           % (said, radius, new["label"]))
                break
    return out


def _set_path(target, dotted, value):
    parts = dotted.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def write_json(path, data):
    """Written whole through a temp file in the same directory, then renamed.

    An interrupted write must not leave a pack half-parsed: every stage in
    this pipeline hard-exits on a profile it cannot read, so a truncated one
    takes the owner's whole collection offline.
    """
    tmp = "%s.tmp-%d" % (path, os.getpid())
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def known_pet_names(pack_dir):
    """-> {lower-cased name} of every subject the pack already holds — the
    same test `declare_pets()` makes before it mints a record."""
    import photo_subjects
    registry = photo_subjects.load(
        pack=photo_profile.Pack(directory=pack_dir, profile={"_": True}))
    return {(s.name or "").lower() for s in registry.subjects if s.name}


def pack_pet_names(pack_dir):
    """-> the pets this pack already names (HIL-9: not re-asked on a later
    page; a new one is named on the pet pages)."""
    import photo_subjects

    registry = photo_subjects.load(
        pack=photo_profile.Pack(directory=pack_dir, profile={"_": True}))
    return [s.name for s in registry.subjects
            if s.name and getattr(s, "who", None) == "pet"
            and s.status != photo_subjects.STATUS_REJECTED]


def declare_pets(pack_dir, names):
    """Each declared animal becomes a subject record with a name and no
    photographs (ADR 0004). -> [(subject_id, name, "created"|"already")].

    ⛔ **Nothing is attached to a face.** Declaring creates an identity for the
    owner to attach frames to at the naming checkpoint; the engine never
    decides which animal is which, so the cold-start rule is untouched. An
    animal declared and never seen stays an empty record, and that is the
    intended outcome — it is how the pack can say "you told me three" instead
    of leaving the third one's absence invisible.

    ⛔ `photo_subjects.Registry` is the one writer, and `create_subject()` the
    one minting verb. A second id allocator here would fork the subject model
    the pack's own `_subject_id_comment` says is single.
    """
    import photo_subjects

    registry = photo_subjects.load(
        pack=photo_profile.Pack(directory=pack_dir, profile={"_": True}))
    out = []
    for name in names:
        existing = next((s for s in registry.subjects
                         if (s.name or "").lower() == name.lower()), None)
        if existing is not None:
            # ⛔ Never a second record for a name the pack already knows: one
            # name across several records is the failure ADR 0004 removes.
            out.append((existing.subject_id, name, "already"))
            continue
        subject = registry.create_subject(name=name, who="pet")
        # Only on a record created HERE: an "already" record's history is not
        # this declaration's to rewrite.
        subject.record[photo_subjects.DECLARED_FLAG] = True
        out.append((subject.subject_id, name, "created"))
    if any(s == "created" for _, _, s in out):
        registry.save()
    return out


def pack_files(pack_arg):
    """-> (pack dir, profile path, entities path) for a pack given as its
    folder or its profile file, or exits."""
    pack_dir = os.path.abspath(pack_arg)
    if os.path.isfile(pack_dir):
        pack_dir = os.path.dirname(pack_dir)
    profile_path = os.path.join(pack_dir, photo_profile.PROFILE_NAME)
    if not os.path.isfile(profile_path):
        raise SystemExit(
            "no pack at %s (%s is missing). This stage writes INTO an owner "
            "pack and never creates one — copy templates/photo-memory/"
            "_template first, so the pack's own comments and defaults come "
            "with it." % (pack_dir, photo_profile.PROFILE_NAME))
    return (pack_dir, profile_path,
            os.path.join(pack_dir, photo_profile.ENTITIES_NAME))


def write_pack(pack_arg, answers, coords_path, coords=None,
               add_screens=frozenset(), answers_path=None, dry_run=False,
               workdirs=(), route="sheet"):
    """The whole of `--write-pack`. -> 0 when every answer was written, 1 when
    any was refused (the safe ones are written anyway — Q-b), or exits.
    `dry_run` prints the same per-key lines and writes nothing.

    ⛔ OPT-IN. Without the flag this stage still writes nothing and still
    prints `NOT_WRITTEN` — a proposal the owner confirmed is still the owner's
    to place, and that stance is `photo_census`'s too. This only says the
    owner may ask for it, not that answering implies it.

    `coords` ({row letter: (lat, lon)}) is for a caller that holds them
    already — G6's page answer — instead of a `--coords-out` file.
    """
    pack_dir, profile_path, entities_path = pack_files(pack_arg)

    with io.open(profile_path, encoding="utf-8") as fh:
        profile = json.load(fh)
    entities = {}
    if os.path.isfile(entities_path):
        with io.open(entities_path, encoding="utf-8") as fh:
            entities = json.load(fh)

    if coords is None:
        coords = read_coords(coords_path) if coords_path else {}
    status = []
    new_sizes = [e for e in _screen_dims(answers["screens"])
                 if tuple(sorted(e["dims"])) not in
                 photo_census.pack_screen_sizes(profile)]
    near = answers_path or pack_dir
    gate = screen_gate(new_sizes, near, workdirs, route) if new_sizes else {}
    plan, refuse = pack_updates(answers, coords, profile, entities,
                                add_screens=add_screens, status=status,
                                screen_gate=gate)
    pets = pet_names(answers["pets"])

    # F-gg — one line per answer, the same on the dry run and the write.
    print("\n%s — what each answer does to %s:"
          % ("DRY RUN" if dry_run else "WRITE", pack_dir))
    for key, verdict, text in status:
        print("   %-15s %-26s %s" % (verdict, key,
                                     "" if verdict == "refuse" else text))
    for key, verdict, text in status:
        if verdict == "refuse":
            print("   ⛔ %s: %s" % (key, text))
    # A size refused because it was never offered gets no count: a count
    # beside it would read as the preview Q-c asks the owner to answer.
    shown_sizes = [e for e in new_sizes
                   if gate.get(tuple(sorted(e["dims"]))) is None
                   or NOT_COUNTED_MARK in gate[tuple(sorted(e["dims"]))]]
    if shown_sizes:
        print_screen_move_preview(shown_sizes, profile, near, workdirs)

    if pets:
        known = known_pet_names(pack_dir)
        for name in pets:
            print("   %-15s %-26s %s" % ("already listed" if name.lower() in known
                                         else "add", "pet", name))
        pets = [n for n in pets if n.lower() not in known]

    if dry_run:
        print("\nDRY RUN — nothing written.")
        return 0

    if not plan and not pets:
        print("\n⛔ Nothing written: %s" % (
            "every answer that had something to write was refused (above)."
            if refuse else "every answer was left blank or is already listed."))
        return 1

    # G6 — a list that held rows before this write is appended to; the file is
    # copied aside first, so the owner's rows can be put back as they were.
    appended = {where for where, key, _value in plan
                if key in (photo_profile.HOME_LOCATIONS_KEY,
                           photo_profile.FREQUENT_PLACES_KEY)
                and ((profile if where == "photo-profile.json" else entities)
                     .get(key))}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for where, path in (("photo-profile.json", profile_path),
                        ("photo-entities.json", entities_path)):
        if where in appended:
            shutil.copy2(path, "%s.bak-%s-append" % (path, stamp))

    for where, key, value in plan:
        _set_path(profile if where == "photo-profile.json" else entities,
                  key, value)
    if any(w == "photo-profile.json" for w, _, _ in plan):
        write_json(profile_path, profile)
    if any(w == "photo-entities.json" for w, _, _ in plan):
        write_json(entities_path, entities)

    print("\n✅ Written to %s%s" % (pack_dir, (
        " — %d answer(s) refused and NOT written (above); the rest are in"
        % len(refuse)) if refuse else ""))
    for where, key, value in plan:
        # ⛔ A coordinate is never printed — not even back to the owner who
        # supplied it. The count and the label say what landed.
        if key == "home_locations":
            shown = "%d home(s): %s" % (
                len(value), ", ".join((h["label"] or "(unnamed)") + (
                    " [travel-to]" if h.get("home_range") is False else "")
                    + " (%s)" % h["id"] for h in value))
        elif key == "frequent_places":
            shown = "%d named place(s): %s" % (
                len(value), ", ".join("%s (%s)" % (pl["label"], pl["id"])
                                      for pl in value))
        else:
            shown = json.dumps(value, ensure_ascii=False)
        print("   %-22s %-38s %s" % (where, key, shown))

    if pets:
        for subject_id, name, what in declare_pets(pack_dir, pets):
            print("   %-22s %-38s %s (%s)"
                  % ("photo-subjects/", "subjects.json", subject_id, what))
        print("   %d animal(s) declared: %s"
              % (len(pets), ", ".join(pets)))
        print("   ⚠️  Declared, never matched. No photograph is attached to "
              "any of these names — the owner attaches them at the naming "
              "checkpoint, and one that is never seen stays an empty record.")
    return 1 if refuse else 0


def sheet_workdirs(header):
    """-> the work dirs a sheet recorded (`workdirs:`), or [] for a sheet
    written before F-01 or a hand-edited header."""
    try:
        got = json.loads(header.get("workdirs") or "[]")
    except ValueError:
        return []
    return [w for w in got if isinstance(w, str)] if isinstance(got, list) else []


def bound_collection(near, workdirs=()):
    """-> (the folder holding collection.json, None) or (None, why not).

    F-01 — found from the sheet's own work dirs through
    `photo_profile.find_collection()`, the lookup every stage uses, so a sheet
    written beside `Working Files/` (photo-init's own layout) still counts.
    The upward search from `near` is only the fallback for input that names no
    work dir: an older sheet, a page, pasted lines."""
    found = set()
    for workdir in workdirs:
        _, path = photo_profile.find_collection(workdir)
        if path:
            found.add(os.path.dirname(os.path.abspath(str(path))))
    if len(found) > 1:
        return None, ("this sheet's work dirs belong to %d different "
                      "collections (%s) — make one sheet per collection"
                      % (len(found), ", ".join(sorted(found))))
    if found:
        return found.pop(), None
    if workdirs:
        # ⛔ Never fall through to the folders above: a stamped sheet kept
        # under another collection would count that collection's units.
        return None, ("no collection.json was found for the work dirs this "
                      "sheet records (%s)" % ", ".join(workdirs))
    here = os.path.abspath(near)
    if os.path.isfile(here):
        here = os.path.dirname(here)
    for _ in range(4):
        if os.path.isfile(os.path.join(here, "collection.json")):
            return here, None
        here = os.path.dirname(here)
    return None, ("no collection.json was found for %s — it records no "
                  "work dir, and none is in its folder or the 3 above it"
                  % near)


NOT_COUNTED_MARK = "what it moves could not be counted"


def screen_gate(new_sizes, near, workdirs=(), route="sheet"):
    """Card 9 — {size (portrait): refusal text, or None when it may be added}
    for every NEW screen size an answer accepts. Decided BEFORE the per-key
    lines are printed, so the dry run and the write say the same thing.

    * Gap A: with no bound collection nothing can be counted, and a yes to an
      uncounted move is not the yes Q-c asks for — refused, naming how to get
      a count (the sheet records its work dirs).
    * A PASTED or PAGE answer carries no digest of what was asked, so a size
      is admitted only if the census of the bound collection offers it: a
      size the owner was never shown photographs of is not one they answered.
      A sheet's own questions are pinned by `questions_digest`."""
    collection_dir, why = bound_collection(near, workdirs)
    how = ('make the sheet from the work dir and answer that one: '
           '%s sheet %s --out-dir <folder>'
           % (cli("photo_onboard_page.py", crops=True),
              quoted(workdirs[0]) if len(workdirs) == 1 else '"<work dir>"'))
    if not collection_dir:
        return {tuple(sorted(e["dims"])): "%s (%s) — %s"
                % (NOT_COUNTED_MARK, why, how) for e in new_sizes}
    offered = None
    if route != "sheet":
        rows = []
        for _label, workdir in bound_units(collection_dir):
            with io.open(os.path.join(workdir, "manifest.csv"),
                         encoding="utf-8", newline="") as fh:
                rows += list(csv.DictReader(fh))
        offered = {tuple(sorted(int(x) for x in c["dims"]))
                   for c in photo_census.census(rows)["screen_size_candidates"]}
    out = {}
    for e in new_sizes:
        size = tuple(sorted(e["dims"]))
        out[size] = None
        if offered is not None and size not in offered:
            out[size] = ("the census of this collection never offered it, so "
                         "no photographs of it were put to the owner — "
                         + how)
    return out


def bound_units(collection_dir):
    """-> [(label, work dir)] for every work dir beside collection.json."""
    return sorted((name, os.path.join(collection_dir, name))
                  for name in os.listdir(collection_dir)
                  if os.path.isfile(os.path.join(collection_dir, name,
                                                 "manifest.csv")))


def print_screen_move_preview(new_sizes, profile, near, workdirs=()):
    """Q-c — what each NEW screen size would move, per bound unit, BEFORE the
    owner says yes. The same rule the plan applies (`photo_sample.tier_of`),
    run with the size added, so the count is the routing's own.

    ⛔ With no collection to count against it REFUSES: no "show the owner"
    line and no count, because a yes to an uncounted move is not the yes Q-c
    asks for."""
    import photo_sample
    collection_dir, why = bound_collection(near, workdirs)
    units = bound_units(collection_dir) if collection_dir else []
    for entry in new_sizes:
        shown = "%sx%s" % tuple(entry["dims"])
        one = dict(profile)
        one["screen_dims"] = list(profile.get("screen_dims") or []) + [entry]
        if not collection_dir:
            print("\n   ⛔ NEW screen size %s MOVES FILES, and what it moves was "
                  "NOT COUNTED: %s." % (shown, why))
            print("      Do not put this size to the owner yet. Make the sheet "
                  "from the work dir, answer that one, and run this dry run "
                  "on it:\n"
                  "          %s sheet %s --out-dir <folder>\n"
                  "      The sheet records its work dirs, and the count is "
                  "made from their collection.json."
                  % (cli("photo_onboard_page.py", crops=True),
                     quoted(workdirs[0]) if len(workdirs) == 1 else '"<work dir>"'))
            continue
        print("\n   ⚠️  NEW screen size %s MOVES FILES. Show the owner this, and "
              "add it only after their yes (--add-screen %s):" % (shown, shown))
        for label, workdir in units:
            with io.open(os.path.join(workdir, "manifest.csv"),
                         encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            moved = Counter(photo_sample.tier_of(r, one)[1] for r in rows
                            if photo_sample.tier_of(r, profile)[0] != "T1"
                            and photo_sample.tier_of(r, one)[0] == "T1")
            state = unit_state(workdir)
            print("      %-24s %d still(s) -> screenshots, %d video(s) -> screen "
                  "recordings%s" % (label, moved["screenshot"],
                                    moved["screen_record"], state))
        print("      Files already copied to the drive stay where they are "
              "(copy-only). A frozen or copied unit answers `verify --copied` "
              "with exit 6 after this write (every copy matches, the names may "
              "change) until it is re-locked, and a re-lock routes these files "
              "by the new size.")


def unit_state(workdir):
    """-> ' (frozen, copied)'-style suffix, from the work dir's own files."""
    parts = []
    if os.path.isfile(os.path.join(workdir, "plans.json")):
        parts.append("planned or frozen")
    plan_dir = os.path.join(workdir, "plan")
    if os.path.isdir(plan_dir) and any(n.startswith("execute-state_")
                                       for n in os.listdir(plan_dir)):
        parts.append("copied")
    return " (%s)" % ", ".join(parts) if parts else ""


def backfill_ids(pack_arg, go):
    """D-I15 for a pack written before ids existed. -> 0, or exits.

    Gives an id to every home and named place that has NONE, numbered after
    the mark and the highest id present. A shared or malformed id is reported
    and left alone — renumbering it would redirect an older index. Dry run
    unless `go`; with it, each changed file is copied to a `.bak-…` first and
    a file is written only if a row in it changed, so a second run writes
    nothing. ⛔ Labels and counts only — never a coordinate.
    """
    pack_dir, profile_path, entities_path = pack_files(pack_arg)
    changed = []
    for path, key in ((profile_path, photo_profile.HOME_LOCATIONS_KEY),
                      (entities_path, photo_profile.FREQUENT_PLACES_KEY)):
        if not os.path.isfile(path):
            continue
        with io.open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        rows = data.get(key) or []
        if not isinstance(rows, list):
            print("   %-18s is not a list — left alone" % key)
            continue
        mark_key = photo_profile.PLACE_IDS[key][3]
        _ids, problems = photo_profile.place_ids(rows, key)
        mark, assigned = photo_profile.assign_place_ids(rows, key,
                                                        data.get(mark_key))
        print("   %-18s %d row(s), %d to give an id%s"
              % (key, len(rows), len(assigned),
                 "".join("\n      %s -> %s" % (rows[i].get("label")
                                               or "(unnamed)", pid)
                         for i, pid in assigned)))
        for problem in problems:
            if not problem.endswith("has no id"):
                print("      ⚠️ %s — left alone; fix it by hand" % problem)
        if assigned:
            changed.append((path, photo_profile.with_place_ids(
                data, key, assigned, mark)))

    if not changed:
        print("\nNothing to write — no row is missing an id.")
        return 0

    def pack_id():
        return (photo_profile.Pack(directory=pack_dir).snapshot()
                or {}).get("id")

    before = pack_id()
    print("\n⚠️  Writing ids moves this pack's id (now %s). A review page "
          "written before that is refused at `confirm`, whole, and nothing on "
          "it is applied — answer any open review page first, or re-run "
          "`%s review <work dir>` afterwards." % (before, cli("photo_memory.py")))
    if not go:
        print("\nDRY RUN — nothing written. Add --go to write (each changed "
              "file is copied to a .bak first).")
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path, data in changed:
        backup = "%s.bak-%s-ids" % (path, stamp)
        shutil.copy2(path, backup)
        write_json(path, data)
        print("   wrote %s (backup %s)" % (os.path.basename(path),
                                           os.path.basename(backup)))
    print("✅ pack id %s -> %s" % (before, pack_id()))
    return 0


def cmd_backfill_ids(args):
    return backfill_ids(args.pack, args.go)


def page_subjects(html):
    """-> what the PAGE put to the owner, in `sheet_subjects()`'s shape.

    ⛔ Read off the questions half of the data block — `cameras.devices`,
    `screens.candidates`, `homes.rows` + `homes.near_misses` — and never off
    `submitted`. Deriving it from the answers would be exactly the vacuity
    `questions_digest()` exists to close on the sheet: a row invented in the
    answers would declare itself as a question that was asked, and a home the
    owner never saw a photograph of is the row that must not get through.

    The sheet has three gates (digest, photographs, `known`) because a sheet
    is a file a person types into. A page has one, and this is it — so a
    `--write-pack` off a page is checked against what that page ASKED even
    though its answers arrived through its own Confirm button.
    """
    match = RE_DATA.search(html)
    data = json.loads(match.group(1)) if match else {}
    homes = data.get("homes") or {}
    known = {
        "make": {("%s %s" % (d.get("make", ""), d.get("model", ""))).strip()
                 for d in (data.get("cameras") or {}).get("devices") or []},
        "screen": {"%sx%s" % (c["dims"][0], c["dims"][1])
                   for c in (data.get("screens") or {}).get("candidates") or []
                   if c.get("dims")},
        "home": {r["id"] for r in (homes.get("rows") or [])
                 + (homes.get("near_misses") or []) if r.get("id")},
    }
    return {k: v for k, v in known.items() if v}


def unanswered(asked, answers, submitted, kept=()):
    """-> ["screen: 1170x2532", "away_km", …] for every question the page PUT
    that came back without an answer.

    ⛔ Asked MINUS answered, never the parser's `blank` list. `blank` only
    fills when a line arrives carrying an empty value, and the page never
    writes such a line — an unanswered question is simply absent from
    `lines()`. So on the page path `blank` is always empty and the warning
    that reads it can never fire (M12, UAT02-01: a blank size and a blank trip
    distance both went through Confirm in silence). The only place the gap is
    visible is against what the page asked, which `page_subjects()` already
    reads off the questions half of the data block.

    ⛔ A REFUSAL IS AN ANSWER. `screens` holds False for "not a screen" and
    that key is answered, so membership is what counts here, never truthiness.
    """
    out = []
    # obs-14 — the page's Copy lines collapse per-device answers to
    # `makes: <Make>`, so the keyed parse holds none; the page's own
    # per-device answers ride in `submitted.makes`.
    makes = dict(submitted.get("makes") or {}, **(answers.get("makes") or {}))
    for key, got in (("make", makes),
                     ("screen", answers.get("screens") or {}),
                     ("home", answers.get("homes") or {})):
        for subject in sorted(asked.get(key) or ()):
            if subject not in got:
                out.append("%s: %s" % (key, subject))
    for key in ("language", "types", "away_km", "pets"):
        if not str(submitted.get(key) or "").strip() and key not in kept:
            out.append(key)
    return out


def apply_page(text, args=None):
    submitted = read_submitted(text)
    if not submitted:
        print("that page carries no answers yet — nobody has pressed Confirm.")
        print("  If the page opens but cannot send (no artifact host, no "
              "session to reach), press `Or copy the lines yourself`, paste "
              "them into a text file, and apply THAT file — the same command "
              "reads it.")
        return 1
    print(json.dumps(submitted, ensure_ascii=False, indent=1))
    if submitted.get("language"):
        photo_profile.announce_missing_table(submitted["language"],
                                             photo_profile.BUCKET_VOCAB)
    # HIL-9 — a section-4 answer left blank keeps the pack's own value.
    pack_dir = getattr(args, "write_pack", None) or getattr(args, "pack", None)
    held = {}
    if pack_dir:
        with io.open(pack_files(pack_dir)[1], encoding="utf-8") as fh:
            held = pack_answers(json.load(fh))
    kept = [k for k in ("language", "types", "away_km")
            if (held.get("away") if k == "away_km" else held.get(k))
            and not str(submitted.get(k) or "").strip()]
    if pack_dir and not str(submitted.get("pets") or "").strip() \
            and pack_pet_names(pack_dir):
        kept.append("pets")     # a new pet is named on the pet pages
    if kept:
        print("\n   kept from the pack: %s (left blank on the page, so the "
              "pack's own values stay)" % ", ".join(kept))
    missing = unanswered(page_subjects(text),
                         parse_lines("\n".join(submitted.get("lines") or []),
                                     known=page_subjects(text)),
                         submitted, kept)
    if missing:
        print("\n⚠️  %d question(s) came back with no answer: %s"
              % (len(missing), ", ".join(missing)))
        print("    Blank is not a no. Nothing above answers them, and the "
              "engine's own default applies in silence to every one.")
    if getattr(args, "write_pack", None):
        # The page's `lines` are the SAME grammar the sheet uses — its Copy
        # button prints them — so the write path has one reader, not two.
        # ⛔ Checked against what the PAGE asked, not against its answers: an
        # HTML file is as editable as a sheet is, and this path has neither a
        # questions digest nor photographs to check.
        return write_pack(args.write_pack,
                          parse_lines("\n".join(submitted.get("lines") or []),
                                      known=page_subjects(text)),
                          args.coords_in, add_screens=add_screen_sizes(args),
                          answers_path=args.page, route="page")
    if getattr(args, "pack", None):
        write_pack(args.pack, parse_lines("\n".join(submitted.get("lines") or []),
                                          known=page_subjects(text)),
                   args.coords_in, add_screens=add_screen_sizes(args),
                   answers_path=args.page, dry_run=True, route="page")
    print(NOT_WRITTEN)
    return 0


def apply_answers(path, text, args=None):
    """Answers written on a sheet, or pasted off the page's Copy button."""
    answers = parse_lines(text, known=sheet_subjects(text))
    header = answers["header"]
    via = "sheet" if header.get("sheet") else "pasted"

    if via == "sheet":
        # ⛔ The questions are checked FIRST. `known` is read off this file's
        # own lines, so without this a row typed in by hand would declare
        # itself as a question that was asked — and a home the owner never saw
        # a photograph of is exactly the row that must not get through.
        want_q = header.get("questions-digest", "")
        if want_q and want_q != questions_digest(text):
            raise SystemExit(
                "the questions on this sheet are not the ones it was written "
                "with — a line has been added, removed or renamed. Answer the "
                "sheet `sheet` wrote, or re-run it: a row nobody was shown "
                "photographs of is not a row the owner answered.")

        # ⛔ The photographs are checked, not assumed. A sheet answered beside
        # an empty directory is an answer written from the numbers, and the
        # numbers are exactly what misleads on the two questions that move
        # files. Refuse, and say which half is wrong.
        root = os.path.join(os.path.dirname(os.path.abspath(path)),
                            header.get("photographs") or "photographs")
        want = header.get("evidence-digest", "-")
        got = evidence_digest(root)
        if want in ("", "-"):
            print("⚠️  this sheet recorded no photographs at all — every "
                  "evidence strip on it was empty. Say why before trusting "
                  "these answers.")
        elif not got:
            raise SystemExit(
                "the photographs this sheet was written from are not beside "
                "it (%s is missing or empty). `screen:` and `home:` move "
                "files and cannot be answered from the counts — re-run "
                "`sheet` and answer it where the pictures are." % root)
        elif got != want:
            raise SystemExit(
                "%s no longer holds the photographs this sheet was written "
                "from. Answers written against different pictures are not "
                "the answers to these questions — re-run `sheet`." % root)

    payload = {"at": datetime.now(timezone.utc).astimezone()
                              .strftime("%Y-%m-%d %H:%M"),
               "via": via,
               "source": os.path.abspath(path),
               "lines": answers["lines"],
               "makes": answers["makes"],
               "own_camera_makes": answers["own_camera_makes"],
               "screens": answers["screens"],
               "homes": answers["homes"],
               "language": answers["language"],
               "types": answers["types"],
               "away_km": answers["away_km"],
               "pets": answers["pets"],
               "units": [u.strip() for u in
                         (header.get("folders") or "").split(",") if u.strip()],
               "unanswered": answers["blank"]}
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    # F7 — said where the answer is recorded, not discovered later as
    # English folder names.
    if answers["language"]:
        photo_profile.announce_missing_table(answers["language"],
                                             photo_profile.BUCKET_VOCAB)

    if via == "pasted":
        print("\n⚠️  These lines were pasted, not read off a sheet, so there "
              "was nothing to check them against: no photographs, and no "
              "record of which rows were put to the owner. Fine when they "
              "came off the page's own Copy button; not fine when they were "
              "typed from the census table.")
    if answers["blank"]:
        print("\n⚠️  %d question(s) left blank: %s"
              % (len(answers["blank"]), ", ".join(answers["blank"])))
        print("    Blank is not a no. Nothing above answers them, and the "
              "engine's own default applies in silence to every one.")
    workdirs = sheet_workdirs(header)
    # Card 9 — only a sheet whose questions digest was present AND matched
    # proves what it asked; one with the line deleted is gated as pasted.
    route = ("sheet" if via == "sheet" and header.get("questions-digest")
             else "pasted")
    if getattr(args, "write_pack", None):
        return write_pack(args.write_pack, answers, args.coords_in,
                          add_screens=add_screen_sizes(args), answers_path=path,
                          workdirs=workdirs, route=route)
    if getattr(args, "pack", None):
        write_pack(args.pack, answers, args.coords_in, answers_path=path,
                   add_screens=add_screen_sizes(args), dry_run=True,
                   workdirs=workdirs, route=route)
    print(NOT_WRITTEN)
    return 0


def add_screen_sizes(args):
    """-> {(short, long)} from --add-screen WxH (either orientation)."""
    out = set()
    for raw in getattr(args, "add_screen", None) or []:
        try:
            out.add(tuple(sorted(int(n) for n in raw.lower().split("x"))))
        except ValueError:
            raise SystemExit("--add-screen %r: expected a size like 1170x2532"
                             % raw)
    return out


def cmd_apply(args):
    with io.open(args.page, encoding="utf-8") as fh:
        text = fh.read()
    if RE_DATA.search(text):
        return apply_page(text, args)
    return apply_answers(args.page, text, args)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="build the page from work dirs")
    r.add_argument("targets", nargs="+", help="work dir(s), or manifest.csv")
    r.add_argument("--out", required=True)
    r.add_argument("--profile", help="owner pack to check against")
    r.add_argument("--coords-out", help="where to keep the home coordinates "
                                        "the page does not carry")
    r.add_argument("--prefill", action="append", metavar="KEY=VALUE",
                   help="carry in an answer the owner already gave elsewhere "
                        "(language/types/away). Marked on the page as carried "
                        "in, and only fills a field left empty. Refused for "
                        "screens and homes.")
    r.add_argument("--device-spec", action="append", default=[],
                   metavar="CAMERA=WxH@SOURCE",
                   help="a camera's screen resolution as the session looked it "
                        "up, with where from. Repeatable. A cross-check shown "
                        "beside the screen sizes, never a verdict; leave it out "
                        "and the page is unchanged")
    r.add_argument("--force-page", action="store_true",
                   help="write the page even when this unit adds nothing new "
                        "(no camera, screen size or home), e.g. to add a home "
                        "or camera by hand (H-C C3)")
    r.add_argument("--unfiltered-evidence", action="store_true",
                   help="embed the evidence photographs WITHOUT the check "
                        "that leaves out documents (U3-06). Only for a python "
                        "with no CLIP; the page then says it was not checked")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--no-coords", dest="with_coords", action="store_false",
                   default=False, help="(default) home coordinates stay off "
                                       "the page. The numbers only: a "
                                       "photograph can still show where a "
                                       "place is")
    g.add_argument("--with-coords", dest="with_coords", action="store_true",
                   help="put coordinates and map links IN the page — only for "
                        "a page that stays on this machine")
    r.set_defaults(fn=cmd_render)

    s = sub.add_parser("sheet", help="the same checkpoint as a text file plus "
                                     "the photographs, for a session with no "
                                     "browser")
    s.add_argument("targets", nargs="+", help="work dir(s), or manifest.csv")
    s.add_argument("--out-dir", required=True,
                   help="directory to write answers.txt and photographs/ into")
    s.add_argument("--profile", help="owner pack to check against")
    s.add_argument("--coords-out", help="where to keep the home coordinates "
                                        "the sheet does not carry")
    s.add_argument("--device-spec", action="append", default=[],
                   metavar="CAMERA=WxH@SOURCE",
                   help="a camera's screen resolution as the session looked it "
                        "up, with where from. Repeatable; see render")
    s.add_argument("--unfiltered-evidence", action="store_true",
                   help="write the evidence photographs WITHOUT the check "
                        "that leaves out documents (U3-06). Only for a python "
                        "with no CLIP; the sheet then says it was not checked")
    sg = s.add_mutually_exclusive_group()
    sg.add_argument("--no-coords", dest="with_coords", action="store_false",
                    default=False, help="(default) home coordinates stay off "
                                        "the sheet. The numbers only: a "
                                        "photograph can still show where a "
                                        "place is")
    sg.add_argument("--with-coords", dest="with_coords", action="store_true",
                    help="put coordinates and map links IN the coordinate "
                         "file only — the sheet itself never carries them")
    s.set_defaults(fn=cmd_sheet)

    a = sub.add_parser("apply", help="read the owner's answers back, off a "
                                     "page or off an answered sheet")
    a.add_argument("page", help="the page the owner submitted, the sheet they "
                                "answered, or a file holding the lines they "
                                "copied off the page")
    a.add_argument("--pack", help="the pack the answers describe: prints, "
                                  "per answer, add / merge / already listed "
                                  "/ refuse and what a new screen size moves "
                                  "— a dry run; writes nothing")
    a.add_argument("--write-pack", metavar="PACK",
                   help="OPT-IN: write the answers into this owner pack. "
                        "Without it this stage reports and writes nothing, "
                        "which is the default and the long-standing stance. "
                        "Refuses, one answer at a time, anything that would "
                        "overwrite what the owner already chose, and writes "
                        "the rest.")
    a.add_argument("--add-screen", action="append", metavar="WxH",
                   help="a NEW screen size the owner said yes to after the "
                        "dry run (--pack) showed what it moves. Without it a "
                        "new size is refused on its own. Only on the owner's "
                        "own yes, never on an agent's judgement.")
    # ⛔ --coords-IN. `render`/`sheet` write coordinates OUT to keep them off
    # the page (Operational Rule 3); `apply` has no work dirs and never calls
    # build_data(), so registering a home means reading that file back. With
    # no --coords-in every home row is refused BY NAME rather than silently
    # dropped — a home nobody registered is a home whose name is not withheld.
    a.add_argument("--coords-in", metavar="FILE",
                   help="the coordinate file render/sheet wrote with "
                        "--coords-out. Required to register a home; the rest "
                        "of the answers write without it.")
    a.set_defaults(fn=cmd_apply)

    b = sub.add_parser("backfill-ids", help="D-I15: give every home and "
                                            "named place in an existing pack "
                                            "its fixed id. Dry run unless --go")
    b.add_argument("pack", help="the owner pack folder, or its "
                                "photo-profile.json")
    b.add_argument("--go", action="store_true",
                   help="write; each changed file is copied to a .bak first")
    b.set_defaults(fn=cmd_backfill_ids)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
