#!/usr/bin/env python3
"""Device census — the prescan/onboarding checkpoint that tells an owner pack
which cameras and screen sizes this collection actually contains.

Three engine rules depend on facts only the photos can supply:

  own_camera_makes  a photo whose Make is not on this list is noted `shared`
                    ("not shot on this device"). One measured pack listed
                    a single make, so a second phone's 5,239 photos were all
                    described as somebody else's.
  screen_dims       a no-camera still at exactly a screen size is a
                    screenshot, and screenshots route to their own monthly
                    bucket. Wrong sizes here MOVE FILES.
  home_locations    a residence is never named as a place, so the engine has
                    to know where the owner lives before it names their first
                    folders. A home is a place photographed on many separate
                    days, and at night — a trip is not.

All three were hand-maintained, and all three were wrong the first time a new
phone or a new address appeared. This reads them off the data instead and
proposes them for confirmation — it never writes the pack itself.

  python3 photo_census.py "<Working Files>/2020-2022"     # after prep
  python3 photo_census.py <path>/manifest.csv --json    # no coordinates
  python3 photo_census.py <work dir> --json-out <file>  # coordinates, to disk

⚠️  A proposal, not a verdict. Screen sizes especially: the census only
offers sizes seen on no-camera STILLS and never one that also appears on a
video, because 1080x1920 is both a phone screen and the commonest video
resolution there is — on one real dump, accepting it would have swept 326
ordinary videos into the screenshot bucket.
"""

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import photo_profile  # noqa: E402
from photo_cluster import gps_point, haversine_km  # noqa: E402
from photo_sample import (DEFAULT_OWN_CAMERA_MAKES, SCREENSHOT_NAME,  # noqa: E402
                          VIDEO_TYPES, screen_devices)

# Scripts worth telling apart for the folder-naming language. Latin is the
# absence of a signal, not a signal: nearly every camera filename is ASCII.
# i18n-guard:allow-begin — locale detection data, not user-facing output:
# these are Unicode block ranges used to tell input scripts apart.
SCRIPTS = [
    ("ja", re.compile(r"[぀-ゟ゠-ヿ]")),   # kana; check first
    ("ko", re.compile(r"[가-힯]")),
    ("zh", re.compile(r"[一-鿿]")),                # Han, dialect-blind
    ("ru", re.compile(r"[Ѐ-ӿ]")),
    ("th", re.compile(r"[฀-๿]")),
]
# i18n-guard:allow-end
STILL_TYPES = {"HEIC", "HEIF", "JPEG", "PNG", "TIFF", "WEBP", "GIF"}
MIN_SCREEN_HITS = 2          # one UNNAMED file at a size proves nothing

HOME_CELL = 0.01             # ~1 km grid; touching cells merge into one place
HOME_NIGHT_HOURS = set(range(19, 24)) | set(range(0, 7))
HOME_MAP_ZOOM = 15
# The two bars below are GENEROUS on purpose, and neither is a matching
# threshold — do not tighten them to look calibrated. Their two failure
# directions cost completely different things. Proposing a place that turns out
# not to be a home costs one line in a list the owner is already reading and
# answering. Failing to propose a home costs the residence-privacy rule —
# residences never become POI or folder names — on the owner's FIRST runs,
# which is exactly when their first folders are being named and nothing else
# knows where they live. So they sit low enough to fire on a thin first dump of
# a single month; they were argued from that asymmetry, never fitted to a
# collection.
HOME_MIN_DAYS = 5
HOME_MIN_NIGHT_DAYS = 3
# D-04 — how many WITHHELD places the report lists, and it is a display cap
# rather than a third bar. Nothing above moves: a place either clears the two
# bars or it does not, and this only decides how much of what missed gets
# printed. Measured over four real dumps (980-4,819 rows), the reporting
# filter below selects 1-10 rows, so the cap bites on a bulk archive import
# and nowhere else — and the count of what it cut is printed beside it.
HOME_NEAR_MISS_SHOWN = 5
# photo_where.py's own --home-km default. ⭐ Not a new threshold: it is the
# radius inside which the privacy rule ALREADY suppresses, so a candidate
# within it of a pack entry is one the pack already answers — which is the
# only question this comparison asks. Change it there, not here.
HOME_MATCH_KM = 1.0


def portrait_key(w, h):
    """-> a screen size as ONE key, whichever orientation it was stored in.

    ⛔ ONE predicate, one definition (A24's rule). The engine matches a screen
    size in both orientations, so a candidate is one size and not two rows —
    and every reader that indexes files BY that size has to collapse them the
    same way. `photo_onboard_page.screens_section()` did not: it keyed its
    evidence on the raw `(ImageWidth, ImageHeight)`, so on a real dump the
    census proposed a size whose files were all stored the other way round,
    found none of them, and the page told the owner "no file at this size"
    about a question that MOVES FILES. A second copy of this rule is how that
    happened; import this one.
    """
    return (w, h) if int(w) <= int(h) else (h, w)


def read_manifest(target):
    p = Path(target)
    if p.is_dir():
        p = p / "manifest.csv"
    if not p.exists():
        sys.exit(f"no manifest at {p} — run photo_scan.py (or photo_run.py prep) first")
    # F04: an older manifest may still sit beside a scan that stopped short.
    summary = p.parent / "scan-summary.json"
    if summary.exists():
        missed = json.loads(summary.read_text(encoding="utf-8")).get(
            "media_files_not_read", 0)
        if missed:
            sys.exit(f"⛔ the last scan of this folder did not read {missed} "
                     f"photo(s) or video(s) ({summary}), so the census stops. "
                     "Re-run the scan until it reads every file.")
    with open(p, newline="") as f:
        return list(csv.DictReader(f)), p


def no_camera(row):
    return (row.get("Make", "-") in ("-", "")
            and row.get("Model", "-") in ("-", ""))


def taken_at(value):
    """-> (day, month, was_at_night) from "YYYY:MM:DD HH:MM:SS", or None. The
    date half is colon-separated, so no ISO parser reads this."""
    if not value or value in ("-", "0000:00:00 00:00:00") or len(value) < 13:
        return None
    try:
        hour = int(value[11:13])
    except ValueError:
        return None
    return value[:10], value[:7], hour in HOME_NIGHT_HOURS


def cell_of(lat, lon):
    """-> the grid cell a point falls in. Rounded before the floor because
    10.5 / 0.01 is 1049.9999999999998 in binary, and a whole degree landing one
    cell low would put two halves of a place out of each other's reach."""
    return (math.floor(round(lat / HOME_CELL, 6)),
            math.floor(round(lon / HOME_CELL, 6)))


def merge_touching(cells):
    """-> the cells grouped into places, joining any two that touch (corners
    count) and following the chain. GPS scatter around one address straddles
    cell edges, so an unmerged grid hands the owner the same home three or
    four times over, and no threshold repairs that."""
    groups, seen = [], set()
    for start in sorted(cells):
        if start in seen:
            continue
        seen.add(start)
        group, queue = [], [start]
        while queue:
            x, y = queue.pop()
            group.append((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    near = (x + dx, y + dy)
                    if near in cells and near not in seen:
                        seen.add(near)
                        queue.append(near)
        groups.append(group)
    return groups


def home_places(rows):
    """Every place this collection saw enough of to describe, each carrying
    the evidence the two home bars read and whether it CLEARED them.

    ⭐ D-04 — this used to drop what it rejected on the floor, and that is the
    defect rather than the bars. Measured on a real dump: an owner's third
    residence cleared the day bar and missed the night bar (one day in the
    whole dump carried an after-dark photo there — they were moving out, so
    the days were spent indoors packing and the evenings out). It was withheld
    in silence, the owner read the silence as `that place is not in this dump`
    and declined to register their own home, and nothing then suppressed its
    address from becoming a folder name. A report that prints only what it
    proposes cannot be told apart from a report that found nothing.

    ⛔ The bars are NOT touched, and lowering them is not the repair —
    `HOME_MIN_NIGHT_DAYS` says the same asymmetry that justifies a low bar
    also says a lower one buys little. What was missing is the disclosure.

    Evidence only — the row carries no name, because naming it would need a
    network the prep stage does not have and must never acquire."""
    return [{k: v for k, v in place.items() if k != "sources"}
            for place in _places(rows)]


def _places(rows):
    """`home_places()` with each place's member files (`sources`, the
    manifest's SourceFile) kept — G6's SNL needs to know which batches a place
    is in. Kept out of `home_places()`'s rows so no existing reader changes."""
    cells = {}
    for row in rows:
        point = gps_point(row.get("GPSPosition", "-"))
        when = taken_at(row.get("DateTimeOriginal", "-"))
        if not point or not when:
            continue
        lat, lon = point
        day, month, night = when
        cell = cells.setdefault(
            cell_of(lat, lon),
            {"days": set(), "nights": set(), "months": set(),
             "files": 0, "lat": 0.0, "lon": 0.0, "sources": set()})
        cell["sources"].add(row.get("SourceFile"))
        cell["days"].add(day)
        cell["months"].add(month)
        if night:
            cell["nights"].add(day)
        cell["files"] += 1
        cell["lat"] += lat
        cell["lon"] += lon

    out = []
    for group in merge_touching(set(cells)):
        days, nights, months, sources = set(), set(), set(), set()
        files, lat, lon = 0, 0.0, 0.0
        for key in group:
            c = cells[key]
            sources |= c["sources"]
            days |= c["days"]
            nights |= c["nights"]
            months |= c["months"]
            files += c["files"]
            lat += c["lat"]
            lon += c["lon"]
        # Month span is reported, never gated on: one dump is normally one
        # month, so a month term in this condition can only fire for a bulk
        # archive import — and it would silently withhold the proposal on the
        # very first run, which is the run the privacy rule depends on.
        missed = []
        if len(days) < HOME_MIN_DAYS:
            missed.append("days")
        if len(nights) < HOME_MIN_NIGHT_DAYS:
            missed.append("night_days")
        coord = [round(lat / files, 3), round(lon / files, 3)]
        out.append({"coord": coord, "days": len(days), "night_days": len(nights),
                    "months": len(months), "files": files,
                    "map": (f"https://www.openstreetmap.org/?mlat={coord[0]}"
                            f"&mlon={coord[1]}"
                            f"#map={HOME_MAP_ZOOM}/{coord[0]}/{coord[1]}"),
                    "proposed": not missed, "missed": missed,
                    "sources": sources})
    out.sort(key=lambda h: (-h["days"], -h["night_days"], -h["files"]))
    return out


def unnamed_frequent_places(rows, profile, named):
    """G6 SNL — the places to ask the owner to NAME mid-run. -> `home_places()`
    rows, each with its `sources`, in that function's order.

    A place qualifies when it clears the FSL bar (`photo_profile.fsl_bar()`:
    days AND months) and the pack does not answer it yet: not within
    HOME_MATCH_KM of a home, not within `named_place_km()` of a place the owner
    named (`named`, `photo_profile.named_places()` rows). The same census
    reader as onboarding; no second one.

    ⛔ Rule 3 limits what is PUBLISHED, not what is ASKED: a qualifying place
    may be one the owner lives at, and the answer may say so."""
    min_days, min_months = photo_profile.fsl_bar(profile)
    homes = [(h[0], h[1]) for h in photo_profile.home_points(profile)]
    place_km = photo_profile.named_place_km(profile)
    out = []
    for place in _places(rows):
        if place["days"] < min_days or place["months"] < min_months:
            continue
        at = tuple(place["coord"])
        if any(haversine_km(at, home) <= HOME_MATCH_KM for home in homes):
            continue
        if any(haversine_km(at, (p[0], p[1])) <= place_km for p in named):
            continue
        out.append(place)
    return out


def home_candidates(rows):
    """The places `home_places()` PROPOSED — the pack-shaped rows, with the
    two bookkeeping fields dropped so every existing reader is unchanged."""
    return [{k: v for k, v in place.items() if k not in ("proposed", "missed")}
            for place in home_places(rows) if place["proposed"]]


def home_near_misses(places, everything=False):
    """-> ([the withheld places shown], how many the CAP cut, how many the
    reporting filter cut). The last two are counted apart on purpose: they are
    withheld for different reasons and only one of them can be described.

    `everything` (F3, `--all-places`) returns every withheld place and cuts
    nothing: the two sentences that report a cut both offer it, so an offer
    to print more is never a dead end.

    D-04's disclosure set. The filter is a REPORTING one and says so: a place
    the owner returned to on a second day, or photographed once after dark, is
    a place they can recognise from a count. One daylight visit to one spot is
    a stop on a trip, and printing every one of those would bury the row this
    exists to surface — that is the same argument the tile ceiling makes, and
    like the tile ceiling it prints what it cut.

    ⚠️ Ordering is `home_places()`'s own — days, then night-days, then files —
    so the row nearest to clearing the bars is the row at the top."""
    withheld = [p for p in places if not p["proposed"]]
    if everything:
        return withheld, 0, 0
    worth_showing = [p for p in withheld if p["days"] >= 2 or p["night_days"] >= 1]
    return (worth_showing[:HOME_NEAR_MISS_SHOWN],
            len(worth_showing[HOME_NEAR_MISS_SHOWN:]),
            len(withheld) - len(worth_showing))


def census(rows, all_places=False):
    places = home_places(rows)
    near_misses, over_cap, one_day_only = home_near_misses(
        places, everything=all_places)
    devices = Counter()
    makes = Counter()
    still_dims, video_dims, camera_dims = Counter(), Counter(), set()
    named_shots = 0
    named_dims = Counter()      # F6 — screenshot-named stills, per size
    scripts = Counter()

    for row in rows:
        make, model = row.get("Make", "-"), row.get("Model", "-")
        ftype = row.get("FileType", "-")
        dims = (row.get("ImageWidth", "-"), row.get("ImageHeight", "-"))
        if make not in ("-", ""):
            makes[make] += 1
            devices[(make, model)] += 1
            if ftype in STILL_TYPES:
                camera_dims.add(dims)
        elif "-" not in dims:
            (video_dims if ftype in VIDEO_TYPES else still_dims)[dims] += 1

        name = row.get("FileName", "")
        if no_camera(row) and SCREENSHOT_NAME.match(name):
            named_shots += 1
            if "-" not in dims and ftype not in VIDEO_TYPES:
                try:
                    w, h = dims
                    named_dims[(w, h) if int(w) <= int(h) else (h, w)] += 1
                except ValueError:
                    pass
        # the raw folder names carry more language signal than IMG_0001 ever
        # will, so read the whole relative path, not just the filename
        text = row.get("SourceFile", "") or name
        for code, pat in SCRIPTS:
            if pat.search(text):
                scripts[code] += 1
                break

    # The engine matches a screen size in both orientations, so a candidate is
    # one size, not two rows. Collapse to portrait and add the counts.
    merged = Counter()
    for (w, h), n in still_dims.items():
        merged[portrait_key(w, h)] += n

    # G-1: a size is proposed WITH the device it belongs to, so it can be
    # audited later and re-proposed per device. A screenshot carries no
    # camera tags, so the pairing is not derivable from the file itself —
    # what the collection can say is which devices are in it. One device is
    # a proposal; several is a question, and the owner answers it.
    device_names = [f"{mk} {md}".strip() for (mk, md), _ in devices.most_common()]
    sole_device = device_names[0] if len(device_names) == 1 else None

    screens, below_threshold = [], 0
    for dims, n in merged.most_common():
        # Card 9 — a file whose NAME proves it a screenshot proves its size on
        # its own. That is G-2's evidence (`photo_plan.screen_size_candidates`),
        # so every size the copy step proposes is one this census asks: the
        # sheet is the one route a new size has into the pack.
        if n < MIN_SCREEN_HITS and not named_dims[dims]:
            below_threshold += 1
            continue
        flipped = (dims[1], dims[0])
        note = None
        if dims in video_dims or flipped in video_dims:
            note = (f"also the size of {video_dims[dims] + video_dims[flipped]} "
                    "video(s) here — accepting it would call those screen recordings")
        elif dims in camera_dims or flipped in camera_dims:
            note = "also produced by a camera in this collection"
        screens.append({"dims": list(dims), "files": n, "warning": note,
                        "model": sole_device,
                        "named_like_screenshots": named_dims[dims]})

    return {
        "files": len(rows),
        "devices": [{"make": mk, "model": md, "files": n}
                    for (mk, md), n in devices.most_common()],
        "device_names": device_names,
        "propose_own_camera_makes": [m for m, _ in makes.most_common()],
        "screen_size_candidates": screens,
        "screen_sizes_below_threshold": below_threshold,
        "home_candidates": [{k: v for k, v in h.items()
                             if k not in ("proposed", "missed")}
                            for h in places if h["proposed"]],
        # D-04 — what the two bars WITHHELD, so silence can be told apart from
        # absence. Never a name, exactly like the row above it.
        "home_near_misses": near_misses,
        "home_near_misses_over_cap": over_cap,
        "home_near_misses_one_day_only": one_day_only,
        "screenshots_by_filename": named_shots,
        "language_signal": ([{"script": s, "files": n} for s, n in scripts.most_common()]
                            or None),
    }


def without_declined(c, profile):
    """FIX6 (U6-37) — the census with the screen sizes the owner already
    declined (`declined_screen_dims`) taken out, and how many. The one filter
    for every surface that offers a size: this report and the onboarding
    page and sheet."""
    declined = photo_profile.declined_screen_sizes(profile)
    kept = [s for s in c["screen_size_candidates"]
            if tuple(sorted(int(x) for x in s["dims"])) not in declined]
    return dict(c, screen_size_candidates=kept,
                screen_sizes_declined=len(c["screen_size_candidates"]) - len(kept))


def pending_screen_sizes(rows, profile=None):
    """-> {(short, long)} screen-size candidates the owner has NOT answered:
    proposed by `census()` for these rows, not declined, not already in the
    pack's `screen_dims` (those already route as screenshots).

    F-jj (Card 6): a no-camera still at one of these sizes is held out of the
    vision pool until the owner answers. It moves no file — routing still
    waits for the answer — it only keeps what is probably a screenshot (a
    statement, a chat) away from the vision model while the question is open.
    ⛔ The census's own candidates, never a second size rule."""
    c = without_declined(census(rows), profile)
    answered = pack_screen_sizes(profile)
    out = set()
    for cand in c["screen_size_candidates"]:
        try:
            size = tuple(sorted(int(x) for x in cand["dims"]))
        except (TypeError, ValueError):
            continue
        if size not in answered:
            out.add(size)
    return out


def at_pending_screen_size(row, sizes):
    """-> is this row a no-camera STILL at one of `sizes`?"""
    if not sizes or not no_camera(row) or row.get("FileType") not in STILL_TYPES:
        return False
    try:
        size = tuple(sorted(int(row[k]) for k in ("ImageWidth", "ImageHeight")))
    except (KeyError, TypeError, ValueError):
        return False
    return size in sizes


def pack_gap(c, profile):
    """What the photos show minus what the pack says. This is the whole point
    of the checkpoint: the gap is silent otherwise, and only shows up as a
    plan document calling the owner's own photos somebody else's.
    -> (makes missing from the pack, whether the pack sets screen_dims, how
    many of those sizes carry no device model)."""
    listed = photo_profile.get(profile, "own_camera_makes",
                               default=DEFAULT_OWN_CAMERA_MAKES)
    listed = {m.lower() for m in listed}
    missing = [d["make"] for d in c["devices"] if d["make"].lower() not in listed]
    seen = set()
    missing = [m for m in missing if not (m.lower() in seen or seen.add(m.lower()))]
    has_dims = photo_profile.get(profile, "screen_dims") is not None
    unpaired = sum(1 for model, _ in screen_devices(profile) if not model) \
        if has_dims else 0
    return missing, has_dims, unpaired


# F6 — a camera photo's shapes. A resized photograph keeps its shape, so a
# screen-size candidate at one of these is exactly what the page warns about.
PHOTO_SHAPES = (("4:3", 4 / 3), ("3:2", 1.5))
# Taller than this is a phone screen's shape (16:9 is 1.78, modern phones ~2.2).
SCREEN_TALL = 1.7


def screen_shape(dims):
    short, tall = sorted(int(x) for x in dims)
    if short <= 0:
        # exiftool writes 0 for some corrupt images. Evidence, not a gate:
        # state nothing about the shape, and never drop the candidate.
        return "no width or height recorded, so no shape to state"
    ratio = tall / short
    for name, want in PHOTO_SHAPES:
        if abs(ratio - want) < 0.02:
            return (f"{name}, the shape of a camera photo — a resized "
                    "photograph looks exactly like this"
                    + (" (a tablet's screen can be 4:3 too)"
                       if name == "4:3" else ""))
    if ratio >= SCREEN_TALL:
        return f"{ratio:.2f}:1, as tall as a phone screen"
    return f"{ratio:.2f}:1, neither a camera photo's shape nor a phone screen's"


def pack_screen_sizes(profile):
    """-> the sizes the pack's `screen_dims` holds, portrait, tolerantly —
    `photo_profile.pack_screen_sizes()`, the one reader."""
    return photo_profile.pack_screen_sizes(profile)


def screen_evidence(cand, profile=None):
    """F6 — what the manifest says about one screen-size candidate.

    A home row is compared against the pack and shown with its evidence; a
    camera make is compared against the pack. A screen size was taken on the
    owner's word. These are the checks the engine can make itself, as ONE
    sentence the census, the page and the sheet all print — never retyped."""
    parts = [f"{cand.get('named_like_screenshots', 0)} of {cand['files']} "
             "named like a screenshot", screen_shape(cand["dims"])]
    if tuple(sorted(int(x) for x in cand["dims"])) in pack_screen_sizes(profile):
        parts.append("already in the pack's screen_dims")
    return "checked: " + "; ".join(parts) + "."


def pack_homes(profile):
    """-> the pack's existing `home_locations` as (lat, lon), tolerantly.

    ⛔ Deliberately NOT photo_where.home_points(): that one exits the run on a
    row it cannot read, which is the right posture for the stage that enforces
    the privacy rule and the wrong one for a report that prints and always
    exits 0. A row this cannot read simply matches nothing, so the worst it
    costs is a home re-proposed — which is the behaviour that existed before
    this comparison did. The schema is the pack's: `lat` and `lon`, two
    fields, never the census's own single `coord` pair."""
    entries = photo_profile.get(profile, "home_locations", default=None)
    if not isinstance(entries, list):
        return []
    homes = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            homes.append((float(entry["lat"]), float(entry["lon"])))
        except (KeyError, TypeError, ValueError):
            continue
    return homes


def already_listed(candidate, homes):
    """Whether a day at this candidate would already be suppressed by a home
    the pack holds — the same test `photo_where.is_home()` makes, so "already
    listed" means the privacy rule already covers this place rather than that
    two numbers look alike.

    ⚠️ `valid_from`/`valid_until` are not read. A proposal carries no date
    range to compare a window against, and the question here is whether the
    owner has answered for this place at all — which they have, whatever
    window they gave it."""
    return listed_as(candidate, homes) is not None


def listed_as(candidate, homes):
    """-> the first of `homes` that already answers for `candidate`, or None.
    ⛔ `already_listed()`'s ONE distance test; a home may be a (lat, lon) pair
    or a pack row with `lat`/`lon` (then its label and id come with it)."""
    for home in homes:
        point = ((float(home["lat"]), float(home["lon"]))
                 if isinstance(home, dict) else home)
        if haversine_km(tuple(candidate["coord"]), point) < HOME_MATCH_KM:
            return home
    return None


def pack_home_rows(profile):
    """-> the pack's readable `home_locations` rows (label and id kept), in
    `pack_homes()`'s tolerant way."""
    entries = photo_profile.get(profile, "home_locations", default=None)
    rows = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        try:
            float(entry["lat"]), float(entry["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append(entry)
    return rows


MISSED_WORDS = {
    "days": f"was photographed on fewer than {HOME_MIN_DAYS} separate days",
    "night_days": (f"has fewer than {HOME_MIN_NIGHT_DAYS} day(s) with a photo "
                   "after dark"),
}


PLACES_FILE = "census-places.txt"


def places_file(path):
    """-> where a census over `path` (a manifest) keeps its coordinates."""
    return Path(path).parent / PLACES_FILE


def numbered_places(c):
    """-> [(n, row)] — home proposals then near misses, numbered as the screen
    shows them. FIX8 F8-8 (U6-06): what a stage prints reaches the driving
    model's transcript, so the screen carries the number and the evidence and
    the coordinate stays in `places_file()` on disk."""
    return list(enumerate(list(c["home_candidates"])
                          + list(c.get("home_near_misses") or []), 1))


STAMP_PREFIX = "manifest-stamp:"


def manifest_stamp(path):
    """-> a short digest of the MANIFEST a census ran over (Q7).

    ⛔ The manifest, never the pack, and it carries NO coordinate — it is a
    hash, so nothing in it can be read back as a place. Its only job is to let
    a later reader tell whether the numbers in the places file still mean what
    they meant when they were written.

    ⛔ ONE definition. The writer below and the reader in
    `photo_onboard_page.read_coords()` both call this; a second copy of the
    rule is how the orientation bug (M13) happened in this same file.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(131072), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def render_places_file(c, manifest_path=None):
    lines = ["census places — the coordinate and map link for each place the "
             "census report numbers. Kept on disk; never printed.", ""]
    if manifest_path is not None:
        # Q7 (owner ruling, 20260920). The place NUMBERS below are per-run:
        # they enumerate the home candidates and near misses in this census's
        # own order, so a re-run over a changed manifest can renumber them.
        # An answer keyed to a stale number would register a coordinate the
        # owner never confirmed, which is a Rule 3 hazard, so the reader stops
        # rather than guess. This line is what lets it tell.
        lines.append("%s %s" % (STAMP_PREFIX, manifest_stamp(manifest_path)))
        lines.append("  (the numbers below belong to that manifest; if it "
                     "changes, re-run the census and answer the new list)")
        lines.append("")
    for n, h in numbered_places(c):
        lines.append(f"place {n}: {h['coord'][0]}, {h['coord'][1]}")
        lines.append(f"  {h['map']}")
    return "\n".join(lines) + "\n"


def without_coordinates(c):
    """-> the report with every place row's `coord` and `map` removed."""
    out = dict(c)
    for key in ("home_candidates", "home_near_misses"):
        if out.get(key):
            out[key] = [{k: v for k, v in row.items() if k not in ("coord", "map")}
                        for row in out[key]]
    return out


def render_near_misses(c):
    """D-04 — the places the two home bars withheld, said out loud.

    ⛔ This is a DISCLOSURE, never a second proposal: the rows below did not
    clear the bars and the report does not ask the owner to confirm them the
    way it asks about the rows above. What it asks is the one question the
    census could not answer for itself — is one of these yours? — because the
    engine cannot tell a residence with the evening light off from a car park
    the owner walked through twice, and the owner can tell instantly."""
    near = c.get("home_near_misses") or []
    over_cap = c.get("home_near_misses_over_cap") or 0
    one_day_only = c.get("home_near_misses_one_day_only") or 0
    if not (near or over_cap or one_day_only):
        return []
    out = ["", "  places you were that were NOT proposed as homes — silence "
                "here is not evidence of absence:"]
    number = {id(row): n for n, row in numbered_places(c)}
    for h in near:
        why = " and ".join(MISSED_WORDS[m] for m in h["missed"])
        out.append(f"  · place {number[id(h)]}   {h['days']} "
                   f"distinct day(s), {h['night_days']} of them with a photo "
                   f"after dark, {h['months']} month(s), {h['files']} file(s)")
        out.append(f"      withheld because it {why}")
    # ⛔ Two counts, never one total. The rows the cap cut look exactly like
    # the rows above them and could each be a residence; the rows the filter
    # cut were seen on one day and never after dark. Summing them would put a
    # describable reason on places that do not have it — the same move that
    # made the silence readable as absence in the first place.
    if over_cap:
        out.append(f"  {over_cap} more place(s) missed the bars in the same "
                   f"way and are not printed — this list shows "
                   f"{HOME_NEAR_MISS_SHOWN}, closest to the bars first. Re-run "
                   "with --all-places to print them if the residence is not "
                   "above.")
    if one_day_only:
        out.append(f"  {one_day_only} further place(s) were withheld too — "
                   "each seen on ONE day and never after dark, which is what a "
                   "stop on a trip looks like. Re-run with --all-places to "
                   "print them if one of them should have been a home.")
    if near:
        out.append("  ⚠️  If one of these IS somewhere they live, ADD IT BY "
                   "HAND — a home the pack does not hold is a home nothing "
                   "suppresses, and its address can reach a folder name. The "
                   "bars are deliberately not lowered to catch these: a "
                   "residence photographed only in daylight (moving in or "
                   "out, working away, evenings spent out) is invisible to "
                   "any night-photo rule, and only the owner knows.")
    return out


def apply_line():
    """H-C C4 / H-I — the onboarding `apply` step as a line that runs from
    any folder, by the one rule `photo_index.run_line()` keeps."""
    import photo_index
    return photo_index.run_line("photo_onboard_page.py") + " apply"


def render(c, path, profile=None, owner=None):
    out = [f"device census — {c['files']} files in {path}", ""]
    # Named once, up here, because both cross-checks below answer the same
    # question — what the photos show against what this pack already holds.
    who = f"pack `{owner}`" if owner else "the generic defaults (no pack loaded)"

    out.append("cameras found (-> own_camera_makes):")
    if c["devices"]:
        shot = sum(d["files"] for d in c["devices"]) or 1
        for d in c["devices"]:
            share = 100 * d["files"] / shot
            out.append(f"  {d['files']:>6}  {d['make']} {d['model']}"
                       + ("   — under 1%, as likely a photo somebody sent "
                          "them as a device they owned" if share < 1 else ""))
        out.append(f"  propose: own_camera_makes = "
                   f"{json.dumps(c['propose_own_camera_makes'])}")
        out.append("  ⚠️  a make left off this list gets its photos noted "
                   "`shared` — check the list is the OWNER's devices, not "
                   "every device that ever sent them a photo")
    else:
        out.append("  none — no file here carries a camera Make")

    out.append("")
    out.append("screen-size candidates (-> screen_dims; these MOVE FILES):")
    if not c["screen_size_candidates"]:
        out.append("  none — no repeated no-camera still size to offer")
    for s in c["screen_size_candidates"]:
        mark = "  " if not s["warning"] else "! "
        out.append(f" {mark}{s['files']:>5}  {s['dims'][0]}x{s['dims'][1]}"
                   + (f"   device: {s['model']}" if s["model"] else "")
                   + (f"   ⚠️  {s['warning']}" if s["warning"] else ""))
        out.append(f"         {screen_evidence(s, profile)}")
    if c.get("screen_sizes_declined"):
        out.append(f"  {c['screen_sizes_declined']} size(s) the owner already "
                   "declined are not offered again (declined_screen_dims).")
    # G-5: the threshold's price, said out loud. Silence here reads as "this
    # collection has no screenshots"; what it can also mean is "it has one".
    if c["screen_sizes_below_threshold"]:
        out.append(f"  {c['screen_sizes_below_threshold']} further size(s) were "
                   f"seen on fewer than {MIN_SCREEN_HITS} no-camera still(s), none "
                   "named like a screenshot, and are not offered — one unnamed "
                   "file at a size proves nothing.")
    if c["screen_size_candidates"]:
        out.append("  PICK from these by hand — a screen size is a phone's own "
                   "resolution, and most rows above are just resized or "
                   "forwarded images. If you don't recognise it as a screen, "
                   "leave it out; both orientations are matched automatically.")
        # G-1: a size with no device on it cannot be audited or re-proposed.
        # A screenshot carries no camera tags, so the census can only offer
        # the devices it found — the owner says which one owns which size.
        example = c["screen_size_candidates"][0]
        model = example["model"] or "<pick from the device list above>"
        out.append('  PAIR each accepted size with its device: screen_dims = '
                   f'[{{"model": "{model}", "dims": '
                   f'[{example["dims"][0]}, {example["dims"][1]}]}}]'
                   + ("   ← model filled in from the only device in this "
                      "collection; change it if the screenshots came from "
                      "another one" if example["model"] else ""))
        if not example["model"] and len(c["device_names"]) > 1:
            out.append("  more than one device here, so no model is proposed: "
                       + ", ".join(c["device_names"]))

    out.append("")
    out.append(f"screenshots identifiable by FILENAME: {c['screenshots_by_filename']}"
               " (caught regardless of screen size — cropped ones included)")

    out.append("")
    if c["language_signal"]:
        top = c["language_signal"][0]
        out.append(f"language signal from names/paths: "
                   + ", ".join(f"{s['script']}×{s['files']}"
                               for s in c["language_signal"]))
        out.append(f"  candidate language: {top['script']} — CONFIRM with the "
                   "owner before it names folders (a script is not a locale: "
                   "Han could be zh-TW or zh-CN)")
    else:
        out.append("language signal from names/paths: none (all-ASCII "
                   "filenames) — ask the owner rather than guessing")

    out.append("")
    out.append("home areas (-> home_locations; the residence-privacy rule "
               "rests on these):")
    if not c["home_candidates"]:
        # Not an exception path. A first dump that is thin, early, or short of
        # GPS proposes nothing, and the privacy rule still needs its answer
        # today — so the same question keeps a typed way to answer it.
        out.append("  nothing here looks like somewhere the owner lives — so "
                   "ASK, in this same question: name the areas they live in, "
                   "at CITY level (the city word, never a street or a door "
                   "number).")
        out.append("  This is an ordinary first run, not a failure: one dump "
                   "is normally one month, plenty of files carry no GPS at "
                   "all, and a home takes a while to show up in the data.")
    else:
        # The same cross-check the cameras have had all along, ten lines down.
        # Without it every re-run re-asks a settled question — the census kept
        # telling the operator to CONFIRM homes the pack had held for weeks —
        # and an owner who answers twice writes a duplicate row.
        homes = pack_homes(profile or {})
        unlisted = []
        number = {id(row): n for n, row in numbered_places(c)}
        for h in c["home_candidates"]:
            known = already_listed(h, homes)
            if not known:
                unlisted.append(h)
            out.append(f"  place {number[id(h)]}   {h['days']} "
                       f"distinct day(s), {h['night_days']} of them with a "
                       f"photo after dark, {h['months']} month(s), "
                       f"{h['files']} file(s)"
                       + (f"   ✓ already listed in {who}" if known else ""))
        if not unlisted:
            # The evidence rows stay above whatever the answer is: they are
            # what makes a listed home auditable later. What goes away is the
            # instruction to go and ask about it again.
            out.append(f"  ✓  every home area found is already listed in {who} "
                       "— nothing to confirm here.")
        else:
            out.append(f"  CONFIRM the {len(unlisted)} row(s) not marked "
                       "✓ with the owner and ask for the CITY word for each — "
                       "the census offers evidence and never a name: there is "
                       "no network at prep and a coordinate is not a place. "
                       f"Open the place's map link in {places_file(path)} if "
                       "the counts alone don't identify it.")
            # M4 (owner ruling, 20260920). This used to spell out a JSON
            # row and say the pair "has to be split by hand". An owner who is
            # not a developer cannot do that — and splitting it is exactly
            # what `pack_updates()` already does. So the owner gives a NUMBER
            # and a word, and the engine takes the pair from the places file
            # itself. ⛔ The coordinate still never reaches the screen: it is
            # read off disk, keyed by the number this report already printed.
            out.append("  ANSWER each confirmed row as `home: <number> = "
                       "<city word> live` — one line per row, the number as "
                       "printed above. Write them in a plain text file, then:")
            out.append(f"    {apply_line()} <that file> "
                       f"--write-pack <pack> --coords-in \"{places_file(path)}\"")
            out.append("  The engine reads the coordinate out of that file "
                       "and writes the pack row itself. You never type a "
                       "coordinate, and none is printed here.")
            out.append("  Month span is evidence, not a bar — one dump is "
                       "normally one month, and a home has to be proposable on "
                       "the first run or the privacy rule has nothing to work "
                       "with.")

    # D-04 — the disclosure, and it prints in BOTH branches above. It matters
    # most in the empty one: "nothing here looks like somewhere they live"
    # over a place that missed a bar by one night is the exact sentence that
    # cost a real owner their third residence.
    out += render_near_misses(c)
    if numbered_places(c):
        out.append(f"  the coordinate and map link of each numbered place are "
                   f"in {places_file(path)} — kept on disk, never printed "
                   "(copy the numbers from there, not from a transcript)")

    out.append("")
    missing, has_dims, unpaired = pack_gap(c, profile or {})
    if missing:
        n = sum(d["files"] for d in c["devices"]
                if d["make"] in missing)
        out.append(f"⚠️  CHECKPOINT — {who} does not list: "
                   + ", ".join(missing))
        out.append(f"    {n} file(s) here will be described as `shared` "
                   "(not shot on this device) until it does.")
    else:
        out.append(f"✓  every camera found is already listed in {who}.")
    if not has_dims and c["screenshots_by_filename"] == 0:
        out.append("   screen_dims is unset, so screenshot detection falls "
                   "back to one built-in iPhone size — fine for an iPhone "
                   "owner, blind for anyone else.")
    if has_dims and unpaired:
        # G-1: still matched, still moving files — but unauditable. Said once
        # rather than fixed, because only the owner knows whose phone it was.
        out.append(f"   {unpaired} size(s) in {who} carry no device model. They "
                   "still match, but nobody can tell later which phone they "
                   'came from — re-save them as {"model": ..., "dims": [w, h]}.')

    out.append("")
    # M4: the same instruction in one sentence, and it covered the screen
    # answers too — which `apply --write-pack` has always been able to write
    # (`screen_dims` and `declined_screen_dims` both have writers in
    # `pack_updates()`). Naming the command is the whole fix here.
    out.append("Nothing was written to the pack. Confirm with the owner, then "
               "write their answers as `screen: <w>x<h> = <device>` (or "
               "`= no`) and `home: <number> = <city word> live`, one per "
               "line, and apply that file:")
    out.append(f"  {apply_line()} <that file> --write-pack <pack>")
    out.append("  (add `--coords-in <the census places file>` if any home row "
               "is answered — that is where the coordinates were kept.)")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="a work dir, or a manifest.csv")
    ap.add_argument("--profile", help="owner pack to check against (default: "
                                      "whatever this collection is bound to)")
    ap.add_argument("--json", action="store_true",
                    help="the report as JSON on stdout, without coordinates "
                         "or map links")
    ap.add_argument("--json-out", metavar="FILE",
                    help="write the whole JSON report, coordinates included, "
                         "to FILE (nothing coordinate-shaped is printed)")
    ap.add_argument("--all-places", action="store_true",
                    help="print EVERY place the home bars withheld, including "
                         "the ones the display cap and the one-daytime-visit "
                         "filter leave out by default")
    args = ap.parse_args()
    rows, path = read_manifest(args.target)
    c = census(rows, all_places=args.all_places)
    pack = photo_profile.resolve_pack(
        workdir=path.parent, explicit=args.profile)
    c = without_declined(c, pack.profile)
    if args.json or args.json_out:
        c["pack_gap"], _, c["unpaired_screen_dims"] = pack_gap(
            c, pack.profile)
        c["owner"] = pack.owner
        if args.json_out:
            Path(args.json_out).write_text(
                json.dumps(c, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8")
            print(f"census report (coordinates included) -> {args.json_out}")
        else:
            print(json.dumps(without_coordinates(c), ensure_ascii=False,
                             indent=1))
    else:
        if numbered_places(c):
            places_file(path).write_text(render_places_file(c, path),
                                         encoding="utf-8")
        print(render(c, path, pack.profile, pack.owner))


if __name__ == "__main__":
    main()
