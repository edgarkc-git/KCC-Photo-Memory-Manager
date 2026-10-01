#!/usr/bin/env python3
"""photo-scan Stage 2 — detect day/GPS legs in manifest.csv, write batches.json.

Reads manifest.csv + scan-summary.json from the work dir (never touches the
source drive). Writes into the work dir only:
  batches.json        the leg roadmap; each batch starts at status "pending"
                      (lifecycle: pending -> classified -> planned -> approved -> done)
  no-date-files.csv   files with no usable EXIF date — manual review, never auto-sorted

Leg detection:
  1. Group files by EXIF capture day; day centroid = median GPS position.
  2. Day type: OVERSEAS (outside the owner's own country — only for a
     country with a day test in COUNTRY_BOXES; the pack's `country`, else the
     row holding its first home), TW_AWAY (> --away-km from every home anchor
     valid that day), TW_HOME. An owner whose country has no day test gets
     TW_HOME/TW_AWAY only (K20; the type strings keep their old names).
     Anchors are the owner pack's `home_locations` minus any marked
     `home_range: false`; with no pack the anchor falls back to this folder's
     modal day-centroid cell (inside the country when it has a day test),
     which a single-trip folder would otherwise take from the trip itself.
     Days without GPS take the neighbouring days' type when both sides agree
     (or OVERSEAS at a trip edge), otherwise default to TW_HOME.
  3. A run of consecutive same-type days = one leg; an AWAY run — TW_AWAY or
     OVERSEAS — is also cut where the day-to-day jump exceeds --jump-km
     (separate away events). TW_HOME is never cut this way: two homes are
     far apart on purpose and neither is an event.
     Runs larger than --max-batch files are split recursively at the day
     boundary with the largest GPS jump (approximates real travel legs).
  4. Labels are provisional and human-facing, written in the owner's language
     via photo_profile.messages() — a run with no pack keeps the legacy
     legacy wording. Place names come from Nominatim zoom-10 reverse
     geocoding in the OWNER PACK'S language (D-06), cached in the shared
     geocode-cache.json under a key that carries that language
     (1 req/s). Final naming happens in photo-classify / photo-plan.
     status/flags stay as machine codes.

Refuses to overwrite an existing batches.json unless --force (keeps a .bak).

Usage:
  python3 photo_cluster.py "/path/to/Working Files/202605__" [--max-batch 1000]
"""

import argparse
import csv
import json
import math
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).parent))
import photo_profile  # noqa: E402

# K20 — the day test for an owner's OWN country: is a day at home-country or
# abroad? One row per country the engine can test offline, (lat min, lat max,
# lon min, lon max). ⛔ This is a TABLE, not the world: an owner whose country
# has no row gets no day test at all — HOME/AWAY days only, no OVERSEAS split
# and no Overpass (owner_country(), in_country()). Never test a day against a
# row that is not the owner's.
COUNTRY_BOXES = {
    "TW": (21.6, 25.5, 118.0, 122.3),
}

# The day types a --jump-km cut may separate: the ones where a move is
# an EVENT boundary. TW_HOME is absent on purpose — see the run loop.
AWAY_TYPES = ("TW_AWAY", "OVERSEAS")

# ⛔ A PRIVACY ring, not the home-range knob. When Nominatim gives nothing back
# the batch label falls back to the raw coordinate, and a tight --away-km makes
# a day a few hundred metres from the owner's door an away-day — so that
# fallback can now print their address to ~1 km. Inside this radius of a home
# the coordinate is withheld instead. It has to be its own number: --away-km is
# the value that MADE the day an away-day, so reusing it could never fire.
# Sized to zoom-10 reverse geocoding, which resolves to a district anyway.
PLACE_SUPPRESS_KM = 3.0


def haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))


def in_box(pt, box):
    return box[0] <= pt[0] <= box[1] and box[2] <= pt[1] <= box[3]


def in_country(pt, country):
    """-> True / False when `country` has a row in COUNTRY_BOXES, None when
    there is no day test for it (an unknown country, or a country with no
    row): the caller then types and names the day as at home-country."""
    box = COUNTRY_BOXES.get(country) if country else None
    return None if box is None else in_box(pt, box)


def owner_country(profile, day_files=None):
    """-> the owner's primary home country (ISO2), or None for "unknown".

    ⛔ The ONE place the default is decided; photo_where asks it too.
    1. the pack's declared `country` (photo_profile.country — the owner said);
    2. else the row of COUNTRY_BOXES holding the pack's FIRST home (home-01),
       so every Taiwan owner is TW without declaring it, exactly as before;
    3. else, with no home at all (a packless run): TW when any day lies in the
       TW row — the old auto-anchor's own precondition, kept so a packless
       Taiwan run is unchanged;
    4. else None: no day test, so no OVERSEAS and no Overpass.
    Nothing here goes online (K20: the owner confirms, never a lookup)."""
    declared = photo_profile.country(profile)
    if declared:
        return declared
    homes = photo_profile.home_points(profile)
    if homes:
        first = (homes[0][0], homes[0][1])
        return next((c for c, box in COUNTRY_BOXES.items() if in_box(first, box)), None)
    for e in (day_files or {}).values():
        pt = e.get("centroid")
        if pt:
            hit = next((c for c, box in COUNTRY_BOXES.items() if in_box(pt, box)), None)
            if hit:
                return hit
    return None


# i18n-guard:allow-begin
# A43. Components of a STREET ADDRESS. A residential lane carries a name in
# OSM and sits exactly on the track, so density ranks it first — measured: a
# lane beside an owner's home (shaped like `青禾三街7巷`, a made-up example)
# was proposed as a folder name.
# ⛔ These three only. A road or street word is NOT here on purpose: a great
# many real destinations end in one (an old street is a place people travel
# to, not an address), and rejecting the word would lose them. Nothing anyone
# travels to ends in a lane, an alley or a house number.
# ⚠️ Residual, stated rather than silently accepted: a bare road name with no
# number still passes this filter. What catches that case is the home
# suppression below, not this list.
ADDRESS_SUFFIXES = ["巷", "弄", "號"]
# i18n-guard:allow-end


def is_address(name):
    """True for a name that is a street address rather than a destination.

    ⛔ A43, and it is a privacy guard before it is a naming one.
    ⛔ It lives HERE, in the lower module, because BOTH naming paths need
    it — `photo_where` names a stop and `photo_cluster` names a batch — and
    `photo_where` already imports from `photo_cluster`, so a copy in the
    upper module would be a second definition AND a circular import. One
    predicate, one definition (A24's rule; D-07 is what two copies cost). A lane 288 m
    from an owner's front door is not merely a poor folder name — it is the
    residence, written down at higher precision than the coordinates the pack
    refuses to publish. Of four near-home batches in UAT01 the two that were
    nameable at all BOTH named a street.

    Two tests, because an address shows up in two shapes: a numbered component
    anywhere in the string, and the string ending in one of the components
    that only ever appears in an address.
    """
    # i18n-guard:allow-begin — locale detection data: fullwidth digits are
    # what OSM carries for a Taiwanese lane number as often as ASCII ones.
    if re.search(r"[0-9０-９]+\s*[巷弄號段]", name):
        return True
    # i18n-guard:allow-end
    return any(name.endswith(a) for a in ADDRESS_SUFFIXES)


# 📐 `{n}` — how many distinct places a batch label may name. A trip that
# crosses five towns is readable; one that lists twenty is not a label.
MAX_BATCH_PLACES = 4


def midpoint_stops(day):
    """-> the centres of a day's stops, in time order, when its median centroid
    is further than a stop's width (`photo_where.STOP_SPLIT_KM`) from EVERY
    photo of that day, else None. Measured on a 291-file dump (UAT01-6): 9 of
    119 GPS days, all two photos far apart, whose midpoint named a district
    nobody visited (59.8 km from the nearest photo at worst)."""
    points = day.get("points") or []
    centroid = day.get("centroid")
    if not points or not centroid:
        return None
    import photo_where
    if min(haversine_km(centroid, (p[0], p[1])) for p in points) <= photo_where.STOP_SPLIT_KM:
        return None
    return [photo_where.stop_center(s) for s in photo_where.segment(points)]


def batch_places(part, day_files, geocoder, all_homes,
                 limit=MAX_BATCH_PLACES, labelled_homes=(), named_places=(),
                 place_km=None):
    """-> the ordered, distinct places a batch actually visited.

    ⭐ R9. This used to be ONE geocode of the MEDIAN day's centroid for the
    whole batch, so a six-day trip was named after whichever day happened to
    sit in the middle. Measured on a real six-day trip: geocoding per day
    returned five different municipalities in about six seconds, with the
    engine's own Geocoder and no other change. The information was always
    there; nothing was asking for it.

    Order is travel order, deduped first-seen — that is what makes
    `where1+where2` readable as an itinerary rather than a set.

    ⛔ R10. Two refusals, and both are privacy before they are naming:
      * a day whose centroid sits inside a home's suppression radius is
        skipped BEFORE the geocoder is called. `Geocoder.city()` performs no
        suppression of its own — `within_home_range` gated only the raw
        coordinate fallback below, so a residence was kept out of the label by
        the zoom-10 constant alone. That is luck, not a control: zoom 10
        usually answers with a town, and "usually" is not a guarantee anyone
        should rest a residence on.
      * a name that is a street address is dropped (`is_address`, A43). At
        zoom 10 this should never fire; it is here because the cost of being
        wrong is an address in a folder name, and the check is free.

    ⚠️ Cost: the geocoder sleeps 1.1 s per UNCACHED lookup (Nominatim's usage
    policy). Its cache key is the coordinate rounded to 2 decimal places, so a
    batch that stays in one place pays once, not once per day.
    """
    names = []
    for d in part:
        centroid = day_files[d]["centroid"]
        if not centroid:
            continue
        stops = midpoint_stops(day_files[d])
        word = None
        if stops:
            # FIX6 F5 (owner decision 20260915, "name from a real stop") —
            # the median sits where no photo was taken, so the day takes the
            # word of its LAST AWAY stop this same chain can name. Only a day
            # whose stops are all homes takes the last home label. A stop the
            # chain cannot name leaves the centroid word below, never a blank.
            at_home = [within_home_range(s, d.isoformat(), all_homes, PLACE_SUPPRESS_KM)
                       for s in stops]
            order = stops if all(at_home) else [s for s, h in zip(stops, at_home) if not h]
            for stop in reversed(order):
                got = batch_places([d], {d: {"centroid": stop}}, geocoder, all_homes,
                                   limit=1, labelled_homes=labelled_homes,
                                   named_places=named_places, place_km=place_km)
                if got:
                    word = got[0]
                    break
        if word:
            if word not in names:
                names.append(word)
            if len(names) >= limit:
                break
            continue
        # ⭐ R13, AMENDED BY D-F9. A day inside a home's suppression radius
        # takes the owner's OWN word for that home if they gave one, and only
        # otherwise the ADMINISTRATIVE lookup — never the free-form one, see
        # city_admin(). R10 skipped such a day outright; that was right about
        # `city()` and too wide in effect. The owner settled the rest on
        # 20260906: the protected asset is the COORDINATE, never the word
        # (D-F4), so PLACE_SUPPRESS_KM stops being a name suppressor and
        # becomes the trigger to prefer the label.
        # ⛔ No fallback to `city()` when neither answers. "We could not name
        # it safely" ends the attempt; walking on to the unsafe lookup would be
        # R10's hole with an extra step in front of it.
        if within_home_range(centroid, d.isoformat(), all_homes,
                             PLACE_SUPPRESS_KM):
            label = home_label(centroid, d.isoformat(), labelled_homes,
                               PLACE_SUPPRESS_KM)
            if label:
                # ⛔ NOT passed through is_address(). A43 exists to stop the
                # ENGINE from writing an address it derived from a map; this
                # word was typed by the owner about their own home, and D-F4
                # puts the word under their authority. Refusing it here would
                # be the engine overruling the owner silently, and the day
                # would lose the one name they actually chose.
                # ⛔ And no geocode call at all — that is the point of D-F9,
                # not a saving. A labelled home never leaves the machine.
                if label not in names:
                    names.append(label)
                if len(names) >= limit:
                    break
                continue
            name = geocoder.city_admin(centroid)
        else:
            # ⭐ W2B-3 / ADR 0001 — outside every home, the owner's own name
            # for a place they named beats the map, and like a labelled home
            # it asks the map nothing. The home branch above is untouched: a
            # named place never overrides a home.
            label = place_label(centroid, named_places, place_km)
            if label:
                if label not in names:
                    names.append(label)
                if len(names) >= limit:
                    break
                continue
            name = geocoder.city(centroid)
        if not name or is_address(name):
            continue
        if name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def home_label(point, day, homes, away_km):
    """-> the owner's own label for the home `point` sits at, or None. D-F9.

    ⛔ NEAREST qualifying home, not the first one inside the radius. The
    canonical pack holds two homes and a dump can hold days at both; ordering
    is pack-file order, which carries no meaning, so "first within radius"
    would name a day after whichever residence the owner happened to type
    first. Nearest is the one the day was actually spent at.

    ⛔ And if the nearest home has NO label, that is the answer — the caller
    falls to the administrative lookup rather than reaching past it for a
    farther home that does have one. Borrowing a second residence's name for a
    day spent at the first is a wrong name, which is worse than a city.

    `homes` is `photo_profile.labelled_home_points()`, and it is the UNFILTERED
    list — `home_range_only=False`. The filter says a place is not the owner's
    everyday life, so it decides whether the day reads as a trip; it never says
    the place may not be named, and D-F4 is explicit that a home CAN be named.
    Wiring the label lookup to the narrowed list would mean the one home the
    flag exists for (a relative's house) suppresses the map lookup and then
    cannot supply the replacement word — the worst of both halves.

    Same validity-window semantics as `within_home_range`, which is what
    decided this day was near a home in the first place.
    """
    best = None
    for lat, lon, since, until, label, *_ in homes:
        km = haversine_km(point, (lat, lon))
        if km > away_km:
            continue
        if since and day[:len(since)] < since:
            continue
        if until and day[:len(until)] > until:
            continue
        if best is None or km < best[0]:
            best = (km, label)
    return best[1] if best else None


def nearest_home(point, day, homes):
    """-> (km, label or None) for the nearest home in force on `day`, or None
    when no home is. F10's reader: the review page says where each FRAME was
    taken, and "far away" needs a distance where `home_label()` only answers
    inside the radius.

    ⛔ Deliberately not folded into `home_label()`: that one decides folder
    names, and this one only describes a photograph to its owner. Same
    validity-window semantics, same `labelled_home_points()` rows."""
    best = None
    for lat, lon, since, until, label, *_ in homes:
        if since and day[:len(since)] < since:
            continue
        if until and day[:len(until)] > until:
            continue
        km = haversine_km(point, (lat, lon))
        if best is None or km < best[0]:
            best = (km, label)
    return best


def within_home_range(point, day, homes, away_km):
    """True when `point` is inside `away_km` of a home the owner had on `day`.

    Same validity-window semantics as photo_where.is_home — a home they had
    not moved into yet must not anchor an older day — but a different radius,
    and that difference is deliberate. photo_where's --home-km is a
    coordinate-level PRIVACY ring (metres); this is the everyday HOME RANGE
    that decides whether a day reads as ordinary life or as a trip. Wiring
    one to the other would call a short drive across town a trip, or a real
    trip ordinary."""
    for lat, lon, since, until in homes:
        if haversine_km(point, (lat, lon)) > away_km:
            continue
        if since and day[:len(since)] < since:
            continue
        if until and day[:len(until)] > until:
            continue
        return True
    return False


def place_label(point, places, radius_km):
    """-> the owner's name for the named place `point` sits at, or None.

    `places` is `photo_profile.named_places()`, `radius_km` its
    `named_place_km()`. NEAREST within the radius, never first in file order,
    for `home_label()`'s reason: file order carries no meaning. Kept apart
    from `home_label()` on purpose — a named place has no validity window and
    no privacy role, and the two lists must never be merged into one.
    """
    if not places:
        return None
    radius = photo_profile.NAMED_PLACE_KM_DEFAULT if radius_km is None \
        else radius_km
    best = None
    for lat, lon, label, *_ in places:
        km = haversine_km(point, (lat, lon))
        if km <= radius and (best is None or km < best[0]):
            best = (km, label)
    return best[1] if best else None


def parse_date(row):
    """The one capture-date resolver in the engine — see parse_date_source()."""
    return parse_date_source(row)[0]


def parse_date_source(row):
    """-> (datetime, the manifest column it came from), or (None, None).

    Every stage reads dates through here, via parse_date(), so the order below
    is the order that decides folders. The column is for the index's
    `date_source` (G11); nothing else reads it.

    ⛔ `CreateDateLocal` FIRST, and only videos ever carry it (U3-23). It is
    the engine-derived local time of a QuickTime `CreateDate`, which is UTC
    with no zone recorded anywhere in the file; `photo_scan` converts it using
    the offset a nearby still declared, and writes nothing when it cannot.
    ⚠️ A manifest written before U3-23 has no such column, so every existing
    work dir keeps exactly the dates it already had and nothing is silently
    re-dated underneath an owner — a dump gets the correction when it is
    re-scanned, and the delta shows up in a plan dry run before any copy."""
    for tag in ("CreateDateLocal", "DateTimeOriginal", "CreateDate"):
        v = row.get(tag, "-")
        if v not in ("-", "", "0000:00:00 00:00:00"):
            try:
                return datetime.strptime(v[:19], "%Y:%m:%d %H:%M:%S"), tag
            except ValueError:
                continue
    return None, None


# i18n-guard:allow-begin — locale detection data, not user-facing output:
# characters that mark a simplified-Chinese variant of an OSM place name, so
# the traditional variant can be preferred. This parses INPUT from OSM.
SIMPLIFIED_CHARS = set("旧国东门马华湾区岛汉兰凤龙圣罗宝尔盐纽约莱坞")
# i18n-guard:allow-end


def pick_traditional(name):
    """An OSM zh name tag can hold several ';'-joined variants of one place
    name — pick the first with no simplified-only character in it."""
    if not name or ";" not in name:
        return name
    variants = [v.strip() for v in name.split(";") if v.strip()]
    for v in variants:
        if not set(v) & SIMPLIFIED_CHARS:
            return v
    return variants[0]


# ---------------------------------------------------------------------------
# D-06 — the language a place is NAMED in is the owner's, not the engine's.
#
# Both reverse-geocode call sites used to ask Nominatim for `zh-TW` and then
# prefer Chinese tags in the reply, so an owner whose pack says `en` got
# Chinese district names in their folder names. The name was REQUESTED, not
# volunteered. Rule 8: language is a variable, default English.
#
# ⛔ There is no language constant below this line and no "if Taiwan then
# Chinese" anywhere: the value arrives from the pack, and `en` is the default
# only because Rule 8 names it as the default for everything else too.
DEFAULT_GEOCODE_LANGUAGE = "en"
# Traditional-script Chinese locales. `pick_traditional()` above exists for
# these and is wrong everywhere else — a Simplified owner asked for their own
# script would have it filtered back out.
TRADITIONAL_CHINESE = ("zh-hant", "zh-tw", "zh-hk", "zh-mo")


def is_traditional(language):
    lang = (language or "").lower()
    return lang in TRADITIONAL_CHINESE or lang.startswith("zh-hant")


def name_tags(language):
    """-> the OSM `namedetails` tags to read, in preference order.

    ⛔ The neutral `name` is NOT in this list. It is the fallback, and the
    fallback has to be distinguishable from a hit — a place named in the
    wrong language silently is the whole of D-06."""
    lang = language or DEFAULT_GEOCODE_LANGUAGE
    if lang.split("-")[0].lower() == "zh":
        script = "zh-Hant" if is_traditional(lang) else "zh-Hans"
        tags = [f"name:{script}", f"name:{lang}", "name:zh"]
    else:
        tags = [f"name:{lang}"]
        base = lang.split("-")[0]
        if base != lang:
            tags.append(f"name:{base}")
    return list(dict.fromkeys(tags))


def pick_variant(name, language):
    """One OSM tag can hold several ';'-joined variants. Traditional Chinese
    picks by script (`pick_traditional`); every other language takes the
    first, because there is nothing in the string to choose on."""
    if not name or ";" not in name:
        return name
    if is_traditional(language):
        return pick_traditional(name)
    return name.split(";")[0].strip()


def read_name(data, language):
    """-> (name, the tag it came from), or (None, None).

    The neutral `name` closes the list and SAYS SO through the returned tag,
    which is what makes the language fallback visible instead of silent."""
    details = data.get("namedetails") or {}
    for tag in name_tags(language):
        if details.get(tag):
            return pick_variant(details[tag], language), tag
    if data.get("name"):
        return pick_variant(data["name"], language), "name"
    return None, None


# 0,0 is the Atlantic off Ghana. No camera has ever been there, and a device
# that writes it is saying "no fix" in the one way that still parses as a
# coordinate — so it is not a location, and every stage has to agree about
# that. THE SINGLE GPS PREDICATE (A24): `photo_scan` counted its own way and
# reported coverage a percentage point high, while clustering rejected the
# same rows; `photo_census` had a third copy that would have let null island
# accumulate days and nights toward a HOME proposal. One function now, called
# by all three — a shared answer is the fix, not three corrected copies.
NULL_ISLAND = (0.0, 0.0)


def gps_point(value):
    """-> (lat, lon) from a "<lat> <lon>" GPSPosition, or None.

    Accepts the comma-separated form too, which is what photo_census's copy
    accepted and clustering's did not. Measured over all 14,435 rows in the
    frozen fixtures before merging the two: not one carries a comma, so the
    tolerance costs no golden dump anything and closes a way of dropping a
    real coordinate."""
    if not value or value in ("-", ""):
        return None
    parts = str(value).replace(",", " ").split()
    if len(parts) < 2:
        return None
    try:
        point = (float(parts[0]), float(parts[1]))
    except ValueError:
        return None
    return None if point == NULL_ISLAND else point


def parse_gps(row):
    """The same predicate, for a manifest row."""
    return gps_point(row.get("GPSPosition", "-"))


# ⛔ RS7c (owner ruling 20260929): every Nominatim reverse request is built
# here and sends the point at 2 decimal places (~1.1 km), the precision the
# cache key already keeps — so no call site can send a finer position than
# the engine remembers. Overpass is NOT built here: it needs ~400 m.
REVERSE_DP = 2
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"


def coarse_point(pt):
    return round(pt[0], REVERSE_DP), round(pt[1], REVERSE_DP)


def reverse_url(pt, zoom, language, detail):
    """-> the Nominatim reverse URL for `pt`, coarsened. `detail` is the
    Nominatim flag the caller reads back (`namedetails` / `addressdetails`)."""
    lat, lon = coarse_point(pt)
    return (f"{NOMINATIM_REVERSE}?format=jsonv2&zoom={zoom}&{detail}=1&"
            + urllib.parse.urlencode({"lat": lat, "lon": lon,
                                      "accept-language": language}))


class Geocoder:
    """⛔ D-06 — the LANGUAGE IS PART OF THE CACHE KEY, and leaving it out is
    the trap this class walks into otherwise. Change the language without
    changing the key and every lookup serves the previous language's name,
    forever and silently, and every test written to prove the change works
    passes because it never reaches the network.

    ⚠️ Existing caches on disk therefore go cold and re-fetch at 1.1 s a
    request. That is correct and is not migrated: an unsuffixed key cannot be
    assumed to be any particular language — a fresh owner's cache has no
    language in it either, so the assumption would be wrong for them."""

    def __init__(self, cache_path, enabled, language=None):
        self.path = cache_path
        self.enabled = enabled
        self.language = language or DEFAULT_GEOCODE_LANGUAGE
        self.cache = {}
        self.dirty = False
        if cache_path.exists():
            self.cache = json.loads(cache_path.read_text())

    def key_for(self, pt, zoom):
        lat, lon = coarse_point(pt)
        return f"{lat:.5f},{lon:.5f},z{zoom},{self.language}"

    def entry(self, pt, zoom):
        """-> the cached row for this point IN THIS LANGUAGE, or None."""
        return self.cache.get(self.key_for(pt, zoom))

    def fell_back(self, pt, zoom):
        """Whether the cached name came from the neutral `name` rather than a
        tag in the owner's language. Read by the callers so the fallback is
        reported on the batch rather than swallowed here."""
        row = self.entry(pt, zoom) or {}
        return bool(row.get("name")) and row.get("name_tag") in ("name", "address")

    def city(self, pt):
        key = self.key_for(pt, 10)
        if key in self.cache:
            return self.cache[key].get("name") or None
        if not self.enabled:
            return None
        url = reverse_url(pt, 10, self.language, "namedetails")
        req = urllib.request.Request(url, headers={"User-Agent": "kcc-photo-manager/0.1"})
        try:
            time.sleep(1.1)  # Nominatim usage policy: max 1 req/s
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            name, tag = read_name(data, self.language)
            if not name:
                # This stage's own last resorts, which carry no language at
                # all — booked as `address` so they read as a fallback too.
                name = (data.get("address", {}).get("city")
                        or data.get("display_name", "").split(",")[0])
                tag = "address" if name else None
            self.cache[key] = {"name": name, "name_tag": tag,
                               "display": data.get("display_name", ""),
                               "cat": data.get("category", ""), "type": data.get("type", "")}
            self.dirty = True
            return name or None
        except Exception:
            return None

    # 📐 The administrative fields Nominatim returns, coarsest-useful first.
    # ⛔ `road`, `neighbourhood`, `suburb` and `display_name` are DELIBERATELY
    # absent: this lookup exists to be safe next to a residence, and its whole
    # guarantee is that nothing finer than a municipality can come out of it.
    ADMIN_FIELDS = ("city", "town", "municipality", "county", "state")

    def city_admin(self, pt):
        """-> a name taken ONLY from Nominatim's structured address dict, or
        None. R13, and the guarantee is structural rather than statistical.

        `city()` reads `namedetails` and falls back to the first component of
        `display_name`, so at zoom 10 it USUALLY answers with a town — which
        is why R10 refused to call it anywhere near a home. Reading the
        address dict instead cannot return a road or a POI however the zoom
        behaves, so a residence's CITY can be named (Operational Rule 3 has
        always permitted that) without the coordinate-level leak R10 stopped.

        ⛔ Its own cache key. An existing `z10` row was written by `city()` and
        carries no `admin`, and a missing field is indistinguishable from a
        genuine "no city here" — reusing the key would serve one as the other,
        silently, on every cache hit."""
        key = self.key_for(pt, "10adm")
        if key in self.cache:
            return self.cache[key].get("name") or None
        if not self.enabled:
            return None
        # ⛔ The coordinate is COARSENED before it leaves the machine, and
        # this lookup is the only one that needs it. Under R10 a residence was
        # never geocoded at all, so its exact position never went anywhere;
        # R13 names its city, which means asking someone. 2 decimal places is
        # ~1.1 km — far finer than a municipality boundary needs and far
        # coarser than a front door — and it is already the cache key's
        # precision, so nothing is lost and one fewer copy of the owner's
        # doorstep exists off this machine. RS7c: every reverse call now does.
        url = reverse_url(pt, 10, self.language, "addressdetails")
        req = urllib.request.Request(url, headers={"User-Agent": "kcc-photo-manager/0.1"})
        try:
            time.sleep(1.1)  # Nominatim usage policy: max 1 req/s
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            address = data.get("address", {}) or {}
            name = next((address[f] for f in self.ADMIN_FIELDS if address.get(f)), None)
            self.cache[key] = {"name": name, "name_tag": "admin"}
            self.dirty = True
            return name or None
        except Exception:
            return None

    def save(self):
        if self.dirty:
            self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1))


def split_run(days, day_files, max_batch):
    """Recursively split a run of days at the largest GPS jump until each
    part holds <= max_batch files (single days always stay whole)."""
    total = sum(len(day_files[d]["rows"]) for d in days)
    if total <= max_batch or len(days) == 1:
        return [days]
    jumps = []
    for i in range(1, len(days)):
        a, b = day_files[days[i - 1]]["centroid"], day_files[days[i]]["centroid"]
        jumps.append(haversine_km(a, b) if a and b else 0.0)
    cut = jumps.index(max(jumps)) + 1
    if cut == 0 or cut == len(days):
        cut = len(days) // 2
    return split_run(days[:cut], day_files, max_batch) + split_run(days[cut:], day_files, max_batch)


# The pack cannot be resolved before the arguments are parsed: it is found
# from the work dir, and the work dir is a positional argument. Resolving it
# early — which this stage used to do — meant `load_profile()` was called with
# no `workdir=`, so a collection.json beside the work dirs was never seen and a
# direct `photo_cluster.py <workdir>` run silently had NO pack: away_km fell
# back to 60, `home_locations` was empty, and the anchor auto-detected from the
# folder's own modal day-centroid, which on a single-trip folder IS the trip.
# The trip was then labelled as everyday home, at exit 0 with no flag.
#
# So every pack-backed option defaults to None here and is filled in AFTER the
# pack is loaded. None is what "the owner did not type this" has to look like:
# a real default baked into add_argument() is indistinguishable from a value
# the owner passed, and the pack would lose to it every time.

# ⭐ R13's number, named once. The pack template WRITES this same value, and
# the two are one fact: a default in code and a default in a pack must move
# together or the pack's copy silently wins. `away_km_answered()` below is
# what makes them safe to keep in two places — it can tell the shipped value
# from a chosen one.
AWAY_KM_DEFAULT = 3.0

PACK_DEFAULTS = {"max_batch": ("max_batch", 300),
                 # ⭐ R13, owner 20260906: 3 km, was 60. 60 km is a REGION,
                 # not a home range — measured on a 990-file dump it typed 11
                 # days 1.4-57 km out as everyday life, buried 227 photos in
                 # home batches and collapsed 27 natural batches into 17.
                 # 3 km is the knee of that curve on real data (17 -> 27
                 # batches; below it you only gain errands), and it is the
                 # owner's own rule stated plainly: more than 3 km from ANY
                 # registered home is a different PLACE, so it gets a name.
                 # ⛔ It coincides with PLACE_SUPPRESS_KM and is NOT wired to
                 # it. That one is a privacy ring, this one is everyday range;
                 # they answer different questions and either may move alone.
                 "away_km": ("away_km", AWAY_KM_DEFAULT),
                 "jump_km": ("jump_km", 30.0),
                 "gap_days": ("gap_days", 30)}


def away_km_answered(profile, flag=None):
    """Did the OWNER choose this home range, or did they never see the question?

    ⛔ The presence of `cluster_defaults.away_km` is NOT the answer, and
    reading it that way is the defect this replaces. The pack template writes
    the key, so a pack nobody has touched carries it too — measured on a real
    run, `batches.json` said `away_km_answered: true` about an owner whose
    answer never reached this stage at all.

    Three things count as an answer and nothing else does:
      --away-km on this run · `away_km_answered: true` in the pack · a pack
      value that differs from what the template ships, because nobody edits a
      number to the value it already had.

    The last one is why a legacy pack still reads correctly: it holds 60, that
    is not the shipped 3, and 60 was somebody's decision once.
    """
    if flag is not None:
        return True
    if photo_profile.get(profile, "cluster_defaults", "away_km_answered",
                         default=None) is True:
        return True
    value = photo_profile.get(profile, "cluster_defaults", "away_km",
                              default=None)
    return value is not None and value != AWAY_KM_DEFAULT


def no_pack_anchor(day_files, country=None):
    """-> the no-pack home anchor, or None: the median point of the modal
    0.2-degree cell among this work dir's day centroids.

    ⛔ The ONE copy. `photo_where` imports it, so the stage that types a day
    and the stage that names it can never disagree about where a packless
    run's home is (K20: `photo_where` had none at all, and named a home day
    after the park beside it). ⛔ Fallback only — the pack's homes always
    win (R2-F3: a work dir holding one trip anchors on the trip itself).
    K20: with a day test for `country` only the days inside it count (a
    packless Taiwan run, exactly as before); with none, every day counts —
    the Taiwan-only rule gave a packless run anywhere else no anchor."""
    cells = {}
    for e in day_files.values():
        pt = e["centroid"]
        if pt and in_country(pt, country) is not False:
            cells.setdefault((round(pt[0] / 0.2), round(pt[1] / 0.2)), []).append(pt)
    if not cells:
        return None
    modal = max(cells.values(), key=len)
    return (median(p[0] for p in modal), median(p[1] for p in modal))


def read_day_files(manifest):
    """-> ({date: {"rows", "gps", "centroid"}}, [rows with no date]) from one
    manifest.csv. A day's centroid is the median of its GPS points, None with
    none.

    ⛔ The ONE place a day centroid is computed. `photo_index relabel` reads
    the same days at run time to put the owner's labels on folders without
    storing a coordinate anywhere, and a second copy of this median would let
    the two disagree about which home a day was spent at.
    """
    day_files = {}
    no_date_rows = []
    with open(manifest, newline="") as f:
        for row in csv.DictReader(f):
            dt = parse_date(row)
            if dt is None:
                no_date_rows.append(row)
                continue
            d = dt.date()
            entry = day_files.setdefault(d, {"rows": [], "gps": [], "points": []})
            entry["rows"].append(row["SourceFile"])
            pt = parse_gps(row)
            if pt:
                entry["gps"].append(pt)
                entry["points"].append((pt[0], pt[1], dt))
    for e in day_files.values():
        e["centroid"] = (median(p[0] for p in e["gps"]),
                         median(p[1] for p in e["gps"])) if e["gps"] else None
    return day_files, no_date_rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir", help="work dir containing manifest.csv")
    ap.add_argument("--max-batch", type=int,
                    help="a run of days never splits mid-date; a single date "
                         "group over this size stays its own oversize batch "
                         "rather than being split/interleaved (pack "
                         "cluster_defaults.max_batch, else 300)")
    ap.add_argument("--away-km", type=float,
                    help="distance from home anchor that makes a TW day an "
                         "away-trip day (pack cluster_defaults.away_km, else 3)")
    ap.add_argument("--jump-km", type=float,
                    help="day-to-day jump that splits a TW away-run into "
                         "separate events (pack cluster_defaults.jump_km, else 30)")
    ap.add_argument("--anchor", help="ADD a home anchor as 'lat,lon' (the pack's "
                                     "home_locations are used first; with no pack "
                                     "the folder's modal day-centroid cell is)")
    ap.add_argument("--gap-days", type=int,
                    help="date gap that forces a batch boundary (pack "
                         "cluster_defaults.gap_days, else 30)")
    ap.add_argument("--profile", help="owner pack to use, overriding the one "
                                      "collection.json binds to this work dir")
    ap.add_argument("--no-geocode", action="store_true")
    ap.add_argument("--geocode-cache", help="shared cache (default: <workdir>/../geocode-cache.json)")
    ap.add_argument("--force", action="store_true", help="overwrite existing batches.json (keeps .bak)")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()

    # W2B-3 — the PACK, not just its profile: the places the owner named live
    # beside it in photo-entities.json. The same resolution load_profile()
    # ran, kept whole.
    pack = photo_profile.resolve_pack(workdir=workdir, explicit=args.profile)
    profile = pack.profile
    answered = away_km_answered(profile, args.away_km)
    for opt, (key, fallback) in PACK_DEFAULTS.items():
        if getattr(args, opt) is None:
            setattr(args, opt, photo_profile.get(profile, "cluster_defaults",
                                                 key, default=fallback))
    msg = photo_profile.messages(profile)

    manifest = workdir / "manifest.csv"
    if not manifest.exists():
        sys.exit(f"no manifest.csv in {workdir} — run photo_scan.py first")
    out = workdir / "batches.json"
    if out.exists() and not args.force:
        sys.exit(f"{out} already exists — pass --force to regenerate (a .bak will be kept)")

    summary = {}
    if (workdir / "scan-summary.json").exists():
        summary = json.loads((workdir / "scan-summary.json").read_text())

    day_files, no_date_rows = read_day_files(manifest)

    if not day_files:
        sys.exit("no dated files in manifest — nothing to cluster")

    # Home anchors — the pack's own home_locations first, auto-detect only as
    # the no-pack fallback.
    #
    # ⛔ Why the pack has to come first (R2-F3). The detector below takes the
    # modal 0.2-degree cell among this WORK DIR's Taiwan day centroids. A work
    # dir holding one trip has one such cell — the trip — so the trip anchors
    # on itself, sits 0.00 km from its own anchor, and the whole dump is filed
    # as everyday home range. Measured on eight trip dumps, all eight. It also
    # drifts on a month spent mostly away, where the modal cell was a house the
    # owner visits rather than lives in.
    #
    # Homes flagged `home_range: false` are left out: somewhere the owner goes
    # often, and may well own, is still a trip. --anchor ADDS a point rather
    # than replacing the pack, matching photo_where's --anchor.
    homes = photo_profile.home_points(profile, home_range_only=True)
    # ⛔ Separately, and UNFILTERED: what may never be printed as a coordinate.
    # `home_range: false` says a place is not the owner's everyday life; it
    # never says the place may be disclosed. Filtering this set would leak the
    # one address the flag was added for.
    all_homes = photo_profile.home_points(profile)
    # ⭐ D-F9 — the same unfiltered set, carrying each home's own label, for
    # the ONE reader allowed to print one: batch naming. See home_label().
    labelled_homes = photo_profile.labelled_home_points(profile)
    # ⭐ D-F9 follow-up (owner decision, 20260906): a label that looks like a
    # street address is USED, and SAID OUT LOUD. Not refused — the word is the
    # owner's (D-F4) and the engine's duty over their own data is to warn
    # rather than overrule (the D-F5 pattern).
    # ⛔ Read ONCE here, at pack load, not inside batch_places(): an
    # address-shaped label is a property of the PACK, so per-batch would
    # repeat one warning per home batch, and it would force a return-shape
    # change on all of batch_places' callers to carry the warning back out.
    # Deduped by label, so two homes the owner named the same thing say it
    # once. ⛔ The LABEL is echoed, never the coordinate.
    address_labels = list(dict.fromkeys(
        label for _lat, _lon, _since, _until, label, *_ in labelled_homes
        if label and is_address(label)))
    # ⭐ W2B-3 / ADR 0001 — the places the owner named, read ONCE through the
    # one reader. An address-shaped name is used and said, never refused, the
    # same D-F5 pattern as a home label above.
    named = photo_profile.named_places(pack)
    place_km = photo_profile.named_place_km(profile)
    place_address_labels = list(dict.fromkeys(
        label for _lat, _lon, label, *_ in named if is_address(label)))
    if args.anchor:
        # ⛔ A sentence, not a traceback (M4). Unguarded, a typo'd anchor died
        # in a raw `ValueError: could not convert string to float: ' 121.36x'`
        # — which is both unreadable to an owner who is not a developer and
        # the one place a coordinate component was echoed back to the screen.
        # The message below names the shape and never quotes what was typed.
        parts = [p.strip() for p in args.anchor.split(",")]
        try:
            if len(parts) != 2:
                raise ValueError
            lat, lon = (float(p) for p in parts)
        except ValueError:
            sys.exit("--anchor takes two numbers, a latitude and a longitude "
                     "separated by a comma, like `25.0,121.5`. What was "
                     "passed is not that shape. (It is not quoted back here "
                     "on purpose — a coordinate does not belong on screen.)")
        homes = homes + [(lat, lon, None, None)]
        all_homes = all_homes + [(lat, lon, None, None)]
        # An anchor is a coordinate on a command line, so it has no label and
        # cannot acquire one — it suppresses like any home and names like an
        # unlabelled one.
        labelled_homes = labelled_homes + [(lat, lon, None, None, None)]
    country = owner_country(profile, day_files)
    auto_anchor = None if homes else no_pack_anchor(day_files, country)

    days = sorted(day_files)
    for d in days:
        e = day_files[d]
        c = e["centroid"]
        if c is None:
            e["type"] = None
        elif in_country(c, country) is False:
            # K20 — only an owner whose country has a day test has an abroad;
            # for any other owner a far day is an away day, never OVERSEAS.
            e["type"] = "OVERSEAS"
        elif homes:
            e["type"] = ("TW_HOME"
                         if within_home_range(c, d.isoformat(), homes, args.away_km)
                         else "TW_AWAY")
        elif auto_anchor and haversine_km(c, auto_anchor) > args.away_km:
            e["type"] = "TW_AWAY"
        else:
            e["type"] = "TW_HOME"

    # no-GPS days: neighbours' type when both sides agree (or OVERSEAS at a
    # trip edge — you can't teleport home mid-trip); otherwise TW_HOME
    for i, d in enumerate(days):
        if day_files[d]["type"]:
            continue
        prev = next((day_files[x]["type"] for x in reversed(days[:i]) if day_files[x]["type"]), None)
        nxt = next((day_files[x]["type"] for x in days[i + 1:] if day_files[x]["type"]), None)
        if prev == nxt and prev:
            day_files[d]["type"] = prev
        elif "OVERSEAS" in (prev, nxt) and None in (prev, nxt):
            day_files[d]["type"] = "OVERSEAS"
        else:
            day_files[d]["type"] = "TW_HOME"

    # runs of consecutive same-type days; a date gap or (for away-runs) a big
    # location jump also cuts — separate away events, separate batches
    #
    # R15 — the jump test reads EVERY away type, not TW_AWAY alone. It used to
    # be written `== "TW_AWAY"`, which meant an OVERSEAS run could not be cut
    # by distance at all: a trip that crossed five cities end to end came back
    # as one leg with one geocode, and the case that most needs legs was the
    # one case that never got them. Measured on a real overseas dump: six
    # photo days, five distinct municipalities, one batch.
    # ⛔ TW_HOME stays OUT, and that is the decision rather than the leftover.
    # A pack may hold several homes, deliberately far apart, and every day at
    # any of them is the same non-event; cutting there would manufacture
    # batches out of the one day type that is never named.
    runs = []
    for d in days:
        if runs:
            last = runs[-1][-1]
            same = day_files[d]["type"] == day_files[last]["type"]
            close_in_time = (d - last).days <= args.gap_days
            jump_cut = False
            if day_files[d]["type"] in AWAY_TYPES:
                a, b = day_files[last]["centroid"], day_files[d]["centroid"]
                jump_cut = bool(a and b) and haversine_km(a, b) > args.jump_km
            if same and close_in_time and not jump_cut:
                runs[-1].append(d)
                continue
        runs.append([d])

    geocoder = Geocoder(
        Path(args.geocode_cache) if args.geocode_cache else workdir.parent / "geocode-cache.json",
        enabled=not args.no_geocode,
        # D-06 — from the PACK. No constant, and no inference from where the
        # photographs were taken: a place is named in the owner's language,
        # not in its own country's.
        language=photo_profile.get(profile, "language"))

    batches = []
    coordinate_batches = set()
    for run in runs:
        for part in split_run(run, day_files, args.max_batch):
            rows = sum(len(day_files[d]["rows"]) for d in part)
            gps_n = sum(len(day_files[d]["gps"]) for d in part)
            typ = day_files[part[0]]["type"]
            flags = []
            if not answered and (homes or auto_anchor):
                flags.append("away_km_not_set")
            if any(len(day_files[d]["rows"]) > args.max_batch for d in part):
                flags.append("oversize_day")
            if gps_n == 0:
                flags.append("no_gps")
            centroids = [day_files[d]["centroid"] for d in part if day_files[d]["centroid"]]
            place = None
            place_is_coordinate = False
            # ⛔ R13 — `typ != "TW_HOME"` used to stand here, and it was the
            # LARGER half of the missing-[where] defect: a home batch never
            # called this at all, so the suppression radius below never even
            # got a turn. Measured on a real dump: of 669 files in batches
            # with no place, 527 were in home batches stopped by this line and
            # only 142 by the radius.
            if centroids:
                # R9 — every day, in travel order, not the median one.
                found = batch_places(part, day_files, geocoder, all_homes,
                                     labelled_homes=labelled_homes,
                                     named_places=named, place_km=place_km)
                if found:
                    place = "+".join(found)
                    # D-06 — said out loud rather than swallowed. OSM has no
                    # name in this owner's language for at least one of these
                    # places, so the neutral `name` was used; the owner is the
                    # only one who can tell whether that reads acceptably.
                    if any(geocoder.fell_back(day_files[d]["centroid"], 10)
                           for d in part if day_files[d]["centroid"]):
                        flags.append("place_name_not_in_owner_language")
                else:
                    # The coordinate fallback keeps its OWN suppression test,
                    # unchanged: it prints a raw lat/lon, which is the most
                    # sensitive thing this function can emit. It is reached
                    # only when no day could be named at all.
                    # ⛔ R13 — and `typ != "TW_HOME"` is NOT redundant with
                    # the suppression test beside it. With no pack the anchor
                    # is auto-detected and `all_homes` is EMPTY, so that test
                    # passes for every point on earth and a home batch would
                    # print the owner's own doorstep as a coordinate. The gate
                    # that used to sit above this whole block is what stopped
                    # it; removing it from there put the burden here.
                    mid = centroids[len(centroids) // 2]
                    if typ != "TW_HOME" and not within_home_range(
                            mid, part[0].isoformat(), all_homes,
                            PLACE_SUPPRESS_KM):
                        place = f"{mid[0]:.2f},{mid[1]:.2f}"
                        place_is_coordinate = True
            # A label is read by the owner, so a `place` that is still None has
            # to become a sentence rather than the word None. Two different
            # causes arrive here and both take the SAME phrase: the batch
            # carried no usable coordinate, or it had one and the line above
            # withheld it because the midpoint sits inside a home's suppression
            # radius. Wording them apart would tell a reader which batches were
            # near a residence, which is the thing the suppression exists to
            # not say.
            # FIX8 F8-8 — a coordinate stays in batches.json's `place` (a
            # file; photo_index drops it at init) and never enters the LABEL,
            # which is printed here and echoed by photo_where (U6-06).
            place_text = place if place is not None and not place_is_coordinate \
                else msg["cluster_place_unresolved"]
            home_label = (msg["cluster_label_home_place"].format(place=place)
                          if place else msg["cluster_label_home"])
            label = {"TW_HOME": home_label,
                     "TW_AWAY": msg["cluster_label_domestic"].format(place=place_text),
                     "OVERSEAS": msg["cluster_label_overseas"].format(place=place_text)}[typ]
            if place_is_coordinate:
                coordinate_batches.add(len(batches) + 1)
            batches.append({
                "batch": len(batches) + 1, "label": label,
                # ⛔ The resolved place as its OWN field, not only inside the
                # label. `label` is a sentence in the owner's language, so a
                # consumer asking "is a place known for this batch?" would
                # have to parse localized prose — which is a Rule 8 break and
                # a silent one. `None` means genuinely unresolved; the two
                # causes (no coordinate, or withheld near a home) stay
                # deliberately indistinguishable here, exactly as the label's
                # own note explains.
                "place": place,
                "from": part[0].isoformat(), "to": part[-1].isoformat(),
                "days": len(part), "files": rows, "gps_files": gps_n,
                "status": "pending", "flags": flags,
            })
    geocoder.save()

    if no_date_rows:
        with open(workdir / "no-date-files.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(no_date_rows[0].keys()))
            w.writeheader()
            w.writerows(no_date_rows)

    result = {
        "source": summary.get("source", "unknown"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "main_files": summary.get("main_files", sum(len(e["rows"]) for e in day_files.values())),
        "aae_ignored": summary.get("aae_ignored"),
        "no_exif_date": len(no_date_rows),
        "max_batch": args.max_batch,
        # ⭐ R13 — in the artifact, not only on stderr, so a later stage and a
        # later reader can both tell a chosen home range from a defaulted one.
        "away_km": args.away_km,
        "away_km_answered": answered,
        "batches": batches,
    }
    if out.exists():
        shutil.copy2(out, out.with_suffix(".json.bak"))
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    # FIX8 F8-8 — the printed copy never carries a coordinate-shaped place.
    shown = dict(result, batches=[
        dict(b, place="(a coordinate — kept in batches.json, not printed)")
        if b["batch"] in coordinate_batches else b
        for b in batches])
    print(json.dumps(shown, ensure_ascii=False, indent=1))
    # ⛔ stderr, and AFTER the JSON, so a caller parsing stdout is unaffected.
    if not answered and (homes or auto_anchor):
        print(msg["cluster_away_km_not_set"].format(away_km=args.away_km),
              file=sys.stderr)
    for label in address_labels:
        print(msg["cluster_home_label_is_address"].format(label=label),
              file=sys.stderr)
    for label in place_address_labels:
        print(msg["cluster_place_label_is_address"].format(label=label),
              file=sys.stderr)
    said = local_name_notice(batches, msg, geocoder.language)
    if said:
        print(said, file=sys.stderr)


def local_name_notice(batches, msg, language):
    """F7 — the flagged batches, said out loud, or None.

    `place_name_not_in_owner_language` used to be written into the batch and
    read by nothing; the SKILL promised the product says so rather than
    swapping scripts silently."""
    hit = ["B%s" % b["batch"] for b in batches
           if "place_name_not_in_owner_language" in b.get("flags", [])]
    if not hit:
        return None
    return msg["cluster_place_name_not_in_owner_language"].format(
        batches=", ".join(hit), language=language)


if __name__ == "__main__":
    main()
