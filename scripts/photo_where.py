#!/usr/bin/env python3
"""photo-classify Stage 3b — generate [where] name candidates for one batch.

Implements the SPEC v0.3 algorithm (tested 2026-07-03):
  Every day is first split into STOPS — consecutive points stay in one stop
    until they leave STOP_SPLIT_KM. A day that stayed put is one stop and is
    named exactly as before; a day that moved keeps every stop instead of
    disappearing (LL-PHO-97), and its [where] is the last stop the engine
    could NAME — Operational Rule 4 / L09 in the shape the pipeline can act
    on, and not merely the last non-home stop (see day_entry).
  Taiwan stops: ONE Overpass query per stop bbox +500 m: natural=peak/saddle,
    named viewpoints, named trails -> rank by #track-points within 400 m then
    min distance (peaks keep min_d < 350 m); trail names reduce to a place
    name via strip_trail_name -> top 2-4 names, first-touch order.
  Overseas stops: Nominatim reverse at zoom 13 (city level), in the OWNER PACK'S
  language (D-06) — the engine names no language of its own.
  A stop on a MOVED day that no peak query can name falls back to the same
    zoom-13 district label; a stop under MIN_NAME_POINTS is counted, not named.
  Privacy: every STOP within --home-km of any home is never named — the check
    is per stop, because a moving day's own centre is nowhere near home. The
    homes come from the owner pack's `home_locations`; --anchor adds one more.

Results are candidates, not final names — vision (summit signs) and the
owner's approval finish the job. Writes classify/batch-NN/where.json in the work dir.

Usage:
  python3 photo_where.py "<Working Files>/202401" --batch 1
"""

import argparse
import csv
import json
import math
import re
import sys
import time
import urllib.request
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).parent))
import photo_profile  # noqa: E402
import photo_sample  # noqa: E402
from photo_cluster import (is_address, parse_date, parse_gps, in_taiwan,  # noqa: E402
                           haversine_km, place_label,
                           pick_variant, read_name, Geocoder, reverse_url)

OVERPASS = "https://overpass-api.de/api/interpreter"

# i18n-guard:allow-begin — locale detection data, not user-facing output.
# Words OpenStreetMap puts at the end of a Chinese trail name; stripping them
# leaves the peak name. This is INPUT parsing, so it stays in the script it
# parses whatever language the engine reports in.
TRAIL_SUFFIXES = ["登山路線", "登山步道", "越嶺步道", "岩稜路線", "山腰線", "步道", "路線"]

# OSM way names on hiking routes are often a description of the GOING, not a
# place: "rope section", "hard route via the creek", "alternative line through
# the grass". They sit exactly on the track, so density ranks them first — the
# one thing that most reliably put a non-place into a folder name.
ROUTE_DESCRIPTIONS = ["拉繩", "陡上", "陡下", "艱難", "溼滑", "濕滑", "替代", "高繞",
                      "腰繞", "捷徑", "溯溪", "溪階", "溪邊", "上稜線", "斜岩",
                      "岩壁", "新路", "舊路", "路段"]
# Man-made things a route passes but is never named after. The urban ones
# matter as much as the hiking ones: a city stop's footways are almost all
# named for a structure, and keeping a name whole now reaches them.
STRUCTURE_SUFFIXES = ["橋", "隧道", "海堤", "堤防", "涼亭", "停車場", "登山口",
                      "地下道", "陸橋", "天橋", "人行道", "月台", "出入口"]
# "distant view of X" — the place name is the REST of the string, so these are
# stripped from the front rather than used to reject the feature.
VIEW_PREFIXES = ["遠眺", "遠觀", "眺望", "可見"]
# Administrative units BELOW the district level. The zoom-13 reverse lookup is
# meant to answer "which town"; when it answers with a neighbourhood instead,
# the name is both useless as a folder and finer-grained than anything the
# engine should volunteer about where its owner was.
AREA_TOO_FINE = ["里", "鄰", "村"]
# "A to B" / "via A": OSM joins two places with these; the first is the feature.
LEG_JOINERS = ["往", "至", "經"]
# i18n-guard:allow-end

RANK_RADIUS_M = 400
PEAK_KEEP_M = 350

# Pitfall 2 / SPEC: a place is never named from a single point. A stop below
# this many points is recorded with its count and left unnamed rather than
# guessed at.
MIN_NAME_POINTS = 3
# A day's points split into a new stop once they leave this radius. Same value
# the old single-cluster outlier filter used, so a day that stayed in one place
# segments into exactly one stop and its output is unchanged.
STOP_SPLIT_KM = 3.0

# Both live in photo_profile — the pack reader is where pack schema belongs,
# and photo_cluster needs the same rows to pick its home anchor. Re-exported
# under the old names so this module stays the one place the privacy rule is
# read from.
#
# ⛔ home_points() is called with the DEFAULT home_range_only=False, and must
# stay that way: `home_range: false` narrows what counts as an everyday batch
# label, never what suppresses a name. Passing True here would un-suppress a
# real residence.
home_bound = photo_profile.home_bound
home_points = photo_profile.home_points


def home_distance_km(point, day, homes):
    """-> km to the nearest home in force on `day`, or None when there is
    none. Split out of `is_home` so a caller can ask HOW FAR as well as
    whether, which is what a stop-wide test needs."""
    live = [(lat, lon) for lat, lon, since, until in homes
            if not (since and day[:len(since)] < since)
            and not (until and day[:len(until)] > until)]
    if not live:
        return None
    return min(haversine_km(point, h) for h in live)


def is_home_stop(pts, day, homes, home_km):
    """-> was any part of this stop at home?

    ⛔ A43's structural half. `is_home()` tests ONE point — the stop's centre —
    while `STOP_SPLIT_KM` is 3.0 km and `--home-km` defaults to 1.0. A stop
    three kilometres wide therefore has a centre that can sit well outside the
    home radius while its own photographs were taken at the front door, and
    the nearest point was never consulted. That is how a residential lane 288
    m from a home reached a folder name at all.

    ⚠️ Fails toward silence on purpose. A stop that merely passes near home on
    its way somewhere is suppressed too, and loses a real name. Operational
    Rule 3 is not a naming preference — a residence must never surface — so
    the cost of a lost name is the correct trade against the cost of a
    published address. The stop is still COUNTED, and the reason is written
    into the entry so the loss is readable rather than invisible.
    """
    center = stop_center(pts)
    if is_home(center, day, homes, home_km):
        return "centre"
    # ⛔ An explicit None test, never `or`. A photograph taken AT the front
    # door has a distance of 0.0, which is falsy — `d or <big>` would send the
    # one case this guard exists for straight past it.
    distances = [d for d in (home_distance_km((p[0], p[1]), day, homes)
                             for p in pts) if d is not None]
    return "point" if distances and min(distances) < home_km else None


def is_home(point, day, homes, home_km):
    for lat, lon, since, until in homes:
        if haversine_km(point, (lat, lon)) >= home_km:
            continue
        if since and day[:len(since)] < since:
            continue
        if until and day[:len(until)] > until:
            continue
        return True
    return False


def day_stops(rows):
    """date -> list of stops, each a time-ordered list of (lat, lon, datetime).

    Every day holding at least one own-capture GPS point appears, and no point
    is ever discarded. The old shape took the day's median and dropped
    everything >3 km from it, then required 3 survivors: on a day that MOVES
    the median lands mid-route, almost every point is an outlier, and the whole
    day left the output with no name, no entry, no count and no warning
    (LL-PHO-97). A day that stayed in one place still segments into exactly one
    stop, so its result is unchanged.
    """
    days = {}
    for r in rows:
        pt = parse_gps(r)
        if pt:
            days.setdefault(r["_dt"].date().isoformat(), []).append((pt[0], pt[1], r["_dt"]))
    return {d: segment(pts) for d, pts in days.items()}


def segment(pts):
    """[(lat, lon, datetime)] of one day -> its stops, in time order. The one
    stop splitter: `photo_cluster.batch_places` reuses it for a day whose
    median sits where no photo was taken (FIX6)."""
    stops = []
    for p in sorted(pts, key=lambda p: p[2]):
        if stops and haversine_km((p[0], p[1]), stop_center(stops[-1])) <= STOP_SPLIT_KM:
            stops[-1].append(p)
        else:
            stops.append([p])
    return stops


def stop_center(stop):
    return (median(p[0] for p in stop), median(p[1] for p in stop))


def overpass_query(bbox, cache):
    key = ",".join(f"{v:.4f}" for v in bbox)
    if key in cache:
        return cache[key]
    s, w, n, e = bbox
    q = f"""[out:json][timeout:60];
(
  node["natural"~"^(peak|saddle)$"]({s},{w},{n},{e});
  node["tourism"="viewpoint"]["name"]({s},{w},{n},{e});
  way["highway"~"^(path|footway|track|steps)$"]["name"]({s},{w},{n},{e});
);
out body geom;"""
    for attempt, backoff in enumerate((0, 15, 45)):
        time.sleep(backoff)
        try:
            req = urllib.request.Request(OVERPASS, data=q.encode(),
                                         headers={"User-Agent": "kcc-photo-manager/0.1"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.loads(r.read().decode())
            cache[key] = data.get("elements", [])
            return cache[key]
        except Exception as ex:
            err = ex
    print(f"overpass failed after retries: {err}", file=sys.stderr)
    return []


def strip_trail_name(name):
    """An OSM feature name reduced to the place name, or None if it names no
    place.

    Returning None when nothing stripped was the old behaviour, and it made
    every name that IS already a place unreachable at any rank — which is why
    the engine could not propose a name an owner had chosen by hand for the
    same track. A name that survives the filters is now kept whole; adding the
    trail word to TRAIL_SUFFIXES instead would truncate a name whose trail
    word is part of the place.
    """
    # i18n-guard:allow-begin — locale detection data: OSM trail names carry
    # fullwidth parentheses, so the stripper has to know both forms.
    n = re.sub(r"[（(].*?[）)]", "", name).strip()
    n = re.split(r"[;；]", n)[0].strip()   # a multi-name tag is two features
    n = n.split("-")[0].strip()            # a route variant of the same place
    # i18n-guard:allow-end
    for pre in VIEW_PREFIXES + LEG_JOINERS:
        if n.startswith(pre) and len(n) > len(pre):
            n = n[len(pre):].strip()
            break
    for join in LEG_JOINERS:
        if join in n[1:]:                  # "A to B" -> A; a leading joiner
            n = n.split(join)[0].strip()   # was already removed above
            break
    for suf in TRAIL_SUFFIXES:
        if n.endswith(suf) and len(n) > len(suf):
            n = n[: -len(suf)]
            break
    if len(n) < 2 or names_no_place(n):
        return None
    return n


def names_no_place(name):
    """True for a name that describes the going, a structure, or an ADDRESS,
    rather than a place."""
    return (any(w in name for w in ROUTE_DESCRIPTIONS)
            or any(name.endswith(s) for s in STRUCTURE_SUFFIXES)
            or is_address(name))


def same_place_key(name):
    """A key that folds OSM's several spellings of one feature together.

    One ridge reaches us on three separate ways whose names differ only by a
    variant character, a parenthetical or a trail word; without this the
    engine proposes all three as if they were three places.
    """
    # i18n-guard:allow-begin — locale detection data, not user-facing output.
    key = name.replace("陵", "稜")
    for tail in ("路", "線", "稜", "道", "坡", "點"):
        # i18n-guard:allow-end
        if key.endswith(tail) and len(key) > len(tail) + 1:
            return key[: -len(tail)]
    return key


def rank_features(elements, pts, language=None):
    """-> list of {name, kind, min_d, near, first_touch} ranked like Phase 1.

    ⛔ D-06, and this site is easy to miss. The Overpass REQUEST is neutral —
    plain `tags.name`, no accept-language — but choosing between the
    ';'-joined variants inside one tag is the same language judgement the
    Nominatim sites make, and it used to be hardwired to Traditional Chinese.
    It reads as harmless because it is a no-op on a name with no ';'. This is
    the path that names HIKES, so it is also the one where a wrong choice
    reaches a folder name."""
    feats = []
    for el in elements:
        name = (el.get("tags") or {}).get("name")
        if not name:
            continue
        if el["type"] == "node":
            coords = [(el["lat"], el["lon"])]
            kind = {"peak": "peak", "saddle": "saddle"}.get(
                el["tags"].get("natural"), "viewpoint")
        else:
            coords = [(g["lat"], g["lon"]) for g in el.get("geometry", [])]
            kind = "trail"
        if not coords:
            continue
        min_d, near, first = 1e9, 0, None
        for lat, lon, ts in pts:
            d = min(haversine_km((lat, lon), c) for c in coords) * 1000
            if d < min_d:
                min_d = d
            if d <= RANK_RADIUS_M:
                near += 1
                if first is None or ts < first:
                    first = ts
        feats.append({"name": pick_variant(name, language), "kind": kind,
                      "min_d": round(min_d), "near": near,
                      "first_touch": first.isoformat() if first else None})
    feats.sort(key=lambda f: (-f["near"], f["min_d"]))
    return feats


def select_names(feats):
    """SPEC step 3-5: peaks first (min_d<350), else names stripped from trails."""
    picks, keys = [], set()

    def take(f):
        base = strip_trail_name(f["name"])
        if not base or same_place_key(base) in keys:
            return
        keys.add(same_place_key(base))
        picks.append((f["first_touch"] or "9", base))

    for f in feats:
        if f["kind"] in ("peak", "saddle") and f["min_d"] < PEAK_KEEP_M and f["near"] > 0:
            take(f)
    if len(picks) < 2:
        for f in feats:
            if f["kind"] in ("trail", "viewpoint") and f["near"] > 0:
                take(f)
    return [name for _, name in sorted(picks)][:4]


def area_name(center, geocoder, reject_fine=False):
    """Nominatim reverse at zoom 13 — a district or city label, never a peak.

    Zoom 13 is the level the SPEC allows precisely because it cannot name a
    summit: it answers "which town", which is the only thing worth saying
    about a stop the peak-and-trail query could not name.
    """
    def usable(name):
        # Only ever applied to the local moving-day fallback. Overseas, the
        # same suffixes are ordinary municipality names in their own countries
        # — dropping one there would lose a real city name, which is the very
        # silence this change set exists to remove.
        if not name or not reject_fine:
            return name or None
        return None if any(name.endswith(a) for a in AREA_TOO_FINE) else name

    # D-06 — the key carries the LANGUAGE (`Geocoder.key_for`). Without it a
    # pack that changes language keeps being served the old language's name
    # out of the cache, forever and with nothing to see.
    key = geocoder.key_for(center, 13)
    if key in geocoder.cache:
        return usable(geocoder.cache[key].get("name"))
    url = reverse_url(center, 13, geocoder.language, "namedetails")
    try:
        time.sleep(1.1)
        req = urllib.request.Request(url, headers={"User-Agent": "kcc-photo-manager/0.1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        name, tag = read_name(data, geocoder.language)
        geocoder.cache[key] = {"name": name or "", "name_tag": tag,
                               "display": data.get("display_name", ""),
                               "cat": data.get("category", ""),
                               "type": data.get("type", "")}
        geocoder.dirty = True
        return usable(name or "")
    except Exception:
        return None


def name_stop(pts, day, homes, home_km, geocoder, op_cache, area_fallback,
              places=(), place_km=None):
    """One stop -> its entry. `area_fallback` is only ever true on a day that
    moved: a stop the peak query cannot name still deserves a town name, but
    turning that on for every day would rename days that answer correctly now.

    The home check runs per STOP, not per day. A day whose median sits
    mid-route is not within any home radius even when it started at the
    owner's door, so suppressing on the day alone would name a residence the
    moment the day was split (Operational Rule 3).
    """
    center = stop_center(pts)
    span = {"from": pts[0][2].isoformat(), "to": pts[-1][2].isoformat(),
            "points": len(pts)}
    at_home = is_home_stop(pts, day, homes, home_km)
    if at_home:
        return dict(span, mode="home", names=[],
                    note="within home radius — never named (privacy)"
                         + ("" if at_home == "centre" else
                            "; the stop's centre is outside the radius but at "
                            "least one of its photographs was taken inside it "
                            "(A43) — a stop may be wider than the radius"))
    if len(pts) < MIN_NAME_POINTS:
        # Before every other test: a brief stop is where a moving day pauses,
        # and naming one puts a motorway service area into a folder name. The
        # gate that used to DROP such a stop now only declines to name it.
        return dict(span, mode="unnamed", names=[],
                    note=f"{len(pts)} own-capture GPS point(s) — fewer than "
                         f"{MIN_NAME_POINTS}, so the stop is counted, not named")
    # ⭐ W2B-3 / ADR 0001 — the owner's own name for a place they named
    # beats every lookup below, and asks none of them. After the home test,
    # never before it: a named place never names a home stop.
    label = place_label(center, places, place_km)
    if label:
        return dict(span, mode="named", names=[label],
                    note="the owner's own name for this place "
                         "(frequent_places) — no map lookup")
    if not in_taiwan(center):
        name = area_name(center, geocoder)
        return dict(span, mode="overseas_z13", names=[name] if name else [])
    lat_m = 0.0045  # ~500 m
    lon_m = 0.0045 / max(math.cos(math.radians(center[0])), 0.2)
    bbox = (min(p[0] for p in pts) - lat_m, min(p[1] for p in pts) - lon_m,
            max(p[0] for p in pts) + lat_m, max(p[1] for p in pts) + lon_m)
    feats = rank_features(overpass_query(bbox, op_cache), pts,
                          geocoder.language)
    names = select_names(feats)
    if names or not area_fallback:
        return dict(span, mode="overpass", names=names, candidates=feats[:12])
    name = area_name(center, geocoder, reject_fine=True)
    return dict(span, mode="area_z13", names=[name] if name else [],
                note="district-level name — no named feature on the track")


def day_entry(stops, day, homes, home_km, geocoder, op_cache, places=(),
              place_km=None):
    """One day -> its entry. A day that stayed put keeps the single-stop shape
    it has always had; a day that moved carries its stops and takes its name
    from the last non-home one (Operational Rule 4 / L09 — in-transit shots
    follow the destination)."""
    moved = len(stops) > 1
    entries = [name_stop(s, day, homes, home_km, geocoder, op_cache, moved,
                         places, place_km)
               for s in stops]
    if not moved:
        return entries[0], entries[0]["names"]
    # The last stop the engine was willing to NAME — which is not simply the
    # last non-home stop. A relocation between two of the owner's own homes
    # ends on a suppressed stop and its only non-home stops are brief pauses;
    # taking those would name the day after a motorway service area.
    names = next((e["names"] for e in reversed(entries) if e["names"]), [])
    return ({"mode": "moving", "points": sum(len(s) for s in stops),
             "stops": entries, "names": names,
             "note": "the day moved; [where] is the last stop the engine could "
                     "name (Rule 4 / L09 — in-transit shots follow the "
                     "destination). An empty list means every stop was a home "
                     "or too brief to name — read the stops, they are all here"},
            names)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir")
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--home-km", type=float, default=1.0,
                    help="never name clusters within this distance of home (privacy)")
    ap.add_argument("--anchor", help="one more home anchor 'lat,lon', ADDED to "
                                     "the pack's home_locations rather than "
                                     "replacing them (privacy check; optional)")
    args = ap.parse_args()
    workdir = Path(args.workdir).resolve()

    # Read the pack before the manifest: a home the engine cannot read must
    # stop the run whether or not this batch turns out to hold GPS at all.
    # W2B-3 — the PACK, resolved once: its profile for the homes, its folder
    # for the places the owner named (photo-entities.json). The same
    # resolution load_profile() ran.
    pack = photo_profile.resolve_pack(workdir=workdir)
    homes = home_points(pack.profile)
    if args.anchor:
        lat, lon = (float(x) for x in args.anchor.split(","))
        homes.append((lat, lon, None, None))

    batches = json.loads((workdir / "batches.json").read_text())
    batch = next((b for b in batches["batches"] if b["batch"] == args.batch), None)
    if batch is None:
        sys.exit(f"batch {args.batch} not in batches.json")

    # D-B: own captures only — and WHOSE camera that is comes from the pack,
    # never from a constant here. ⛔ This line read `Make == "Apple"` until R7,
    # which made the whole naming stage silently dead for any non-Apple owner:
    # 0 of 13 batches nameable on a Samsung dump, exit 0, no warning, 58% of
    # the files losing a place name (D-07). The predicate is `photo_sample`'s
    # own, imported rather than restated, so the stage that SPLITS own from
    # shared and the stage that NAMES the place can never disagree about which
    # camera is the owner's (A24's rule, applied to a second predicate).
    profile = pack.profile
    rows, in_window, makes_seen = [], 0, {}
    with open(workdir / "manifest.csv", newline="") as f:
        for row in csv.DictReader(f):
            dt = parse_date(row)
            if not (dt and batch["from"] <= dt.date().isoformat() <= batch["to"]):
                continue
            in_window += 1
            make = row.get("Make") or ""
            makes_seen[make] = makes_seen.get(make, 0) + 1
            if photo_sample.is_own_make(make, profile):
                row["_dt"] = dt
                rows.append(row)

    # ⛔ Said out loud, because this is the exact silence D-07 hid in: a batch
    # whose every photo was filtered out looks identical to a batch with no
    # GPS at all — both produce no name, at exit 0. The owner cannot fix a
    # pack they are never told is wrong.
    filtered_out = None
    if in_window and not rows:
        found = sorted((m for m in makes_seen if m), key=lambda m: -makes_seen[m])
        filtered_out = {
            "files_in_window": in_window,
            "cameras_found": found,
            "own_camera_makes": sorted(photo_sample.own_makes(profile)),
            "why": ("every file in this batch was shot on a camera that is not "
                    "in the pack's own_camera_makes, so none of them could be "
                    "used to name the place. Add the make(s) to the pack — "
                    "photo_census.py proposes them."),
        }

    stops_by_day = day_stops(rows)

    cache_path = workdir.parent / "overpass-cache.json"
    op_cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    geocoder = Geocoder(workdir.parent / "geocode-cache.json", enabled=True,
                        # D-06 — the pack's language, never a constant.
                        language=photo_profile.get(profile, "language"))

    places = photo_profile.named_places(pack)
    place_km = photo_profile.named_place_km(profile)
    result_days, all_names = {}, []
    for d, stops in sorted(stops_by_day.items()):
        entry, names = day_entry(stops, d, homes, args.home_km, geocoder,
                                 op_cache, places, place_km)
        result_days[d] = entry
        all_names.extend(names)
    geocoder.save()
    cache_path.write_text(json.dumps(op_cache))

    seen, suggestion = set(), []
    for n in all_names:
        if n not in seen:
            seen.add(n)
            suggestion.append(n)
    out = {"batch": args.batch, "label": batch["label"],
           "days": result_days, "suggestion": "+".join(suggestion[:4]) or None}
    if filtered_out:
        out["filtered_out"] = filtered_out
    if not result_days:
        # Written, not just printed: a batch with no GPS at all used to leave
        # no file behind, which reads downstream as "not run yet".
        out["note"] = "no own-capture GPS points in this batch's date range"
    out_dir = workdir / "classify" / f"batch-{args.batch:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "where.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
