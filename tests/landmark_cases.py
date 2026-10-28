#!/usr/bin/env python3
"""M1 / M2 cases (P1, ADR 0006): a folder's [where] is the landmark, looked
up at full precision away from every home, in the owner's language.

  python3 tests/landmark_cases.py [-v]
  python3 tests/landmark_cases.py --write-fixture   # rebuild the map cache

Exit 0 = pass. No case reaches a network: the stages run with
`tests/offline` on PYTHONPATH, which refuses (or stubs) every request and
logs it, so a case can COUNT what a stage tried to send. Map answers come
from the recorded cache `tests/fixtures/map-cache.json` — synthetic points
and invented names (Rule 7), in the engine's own cache shape (the Geocoder's
`geocode-cache.json`).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))
import photo_cluster as pc  # noqa: E402
import photo_index_cases as ix  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "map-cache.json"
OFFLINE = ROOT / "tests" / "offline"
LANGUAGE = "en"

# Invented points, nobody's address. HOME is the pack's only home.
HOME = (40.0000, 140.0000)
NEAR_HOME = (40.0100, 140.0000)          # ~1.1 km — inside PLACE_SUPPRESS_KM
A = (40.6000, 140.6000)                  # each day ~85 km from the last
B = (41.2000, 141.2000)
C = (41.8000, 141.8000)
D = (42.4000, 142.4000)
E = (43.0000, 143.0000)
F = (43.6000, 143.6000)
G = (44.2000, 144.2000)
H = (44.8000, 144.8000)
J = (45.4000, 145.4000)


def off(pt, dlat=0.0, dlon=0.0):
    return (round(pt[0] + dlat, 6), round(pt[1] + dlon, 6))


# day -> [photo points]
DAYS = {
    # a park holds every photo; a hotel near it holds two: the sight (D4)
    "2025-05-01": [off(A, 0.0002 * i) for i in range(4)] + [off(A, 0.0015)] * 2,
    # museum 3, beach 2 (a third of 6, D3), a tower 1 (below a third)
    "2025-05-02": [off(B, 0.0001 * i) for i in range(3)] + [off(B, 0.0100)] * 2
                  + [off(B, 0.0200)],
    # a restaurant only: it names a day with no sight
    "2025-05-03": [off(C, 0.0001 * i) for i in range(3)],
    # Overpass knows nothing; zoom 18 answers a viewpoint
    "2025-05-04": [off(D, 0.0001 * i) for i in range(3)],
    # Overpass knows nothing; zoom 18 answers a road (refused); the town
    "2025-05-05": [off(E, 0.0001 * i) for i in range(3)],
    # near the (unlabelled) home: the 2 dp administrative lookup only (R13)
    "2025-05-06": [off(NEAR_HOME, 0.0001 * i) for i in range(3)],
    # F1: every photo at a tower that stands inside a large park — the park
    # holds them too, yet only the tower names the day
    "2025-05-09": [off(F, 0.0001 * i) for i in range(4)],
    # F1: the same, plus 2 of 6 photos on the park's lawn, nearer the park
    # than the tower — a third, so the park joins second
    "2025-05-10": [off(G, 0.0001 * i) for i in range(4)] + [off(G, 0.0020)] * 2,
    # F3, the shape of the Lead's live probe (synthetic): photos under a
    # notable tower inside a notable park, beside a tiny office node and a
    # small viewpoint inside the tower, a notable memorial 37 m off, and
    # plain pedestrian streets — the tower names the day, alone
    "2025-05-11": [off(H, 0.0001 * i) for i in range(4)],
    # F4, the shape of the Lead's second live probe (synthetic): photos
    # inside two hostel outlines, a restaurant 24 m off, a cafe 45 m off and
    # an old-street attraction node 67 m off — the sight names the day (D4)
    "2025-05-12": [off(J, 0.00005 * i) for i in range(4)],
}
WANT = {"2025-05-01": "Lotus Garden",
        "2025-05-02": "Old Mill Museum+Harbour Beach",
        "2025-05-03": "Birk Inn",
        "2025-05-04": "Seaview Point",
        "2025-05-05": "Townfield",
        "2025-05-06": "Homecity",
        "2025-05-09": "Birk Tower",
        "2025-05-10": "Birk Tower+Lotus Commons",
        "2025-05-11": "Lotus Spire",
        "2025-05-12": "Birk Hill Street"}


def bounds(pt, half):
    return {"minlat": pt[0] - half, "minlon": pt[1] - half,
            "maxlat": pt[0] + half, "maxlon": pt[1] + half}


ELEMENTS = {
    "2025-05-01": [
        {"type": "way", "bounds": bounds(A, 0.001),
         "tags": {"leisure": "park", "name": "Lotus Garden"}},
        {"type": "node", "lat": off(A, 0.0015)[0], "lon": A[1],
         "tags": {"tourism": "hotel", "name": "Birk Hotel"}}],
    "2025-05-02": [
        {"type": "node", "lat": B[0], "lon": B[1],
         "tags": {"tourism": "museum", "name": "Old Mill Museum"}},
        {"type": "way", "bounds": bounds(off(B, 0.0100), 0.0005),
         "tags": {"natural": "beach", "name": "Harbour Beach"}},
        {"type": "node", "lat": off(B, 0.0200)[0], "lon": B[1],
         "tags": {"historic": "monument", "name": "Clock Tower"}}],
    "2025-05-03": [
        {"type": "node", "lat": C[0], "lon": C[1],
         "tags": {"amenity": "restaurant", "name": "Birk Inn"}}],
    "2025-05-04": [],
    "2025-05-05": [],
}
for _day, _pt in (("2025-05-09", F), ("2025-05-10", G)):
    # the park first, as an Overpass answer may list it
    ELEMENTS[_day] = [
        {"type": "way", "bounds": bounds(_pt, 0.005),
         "tags": {"leisure": "park", "name": "Lotus Commons"}},
        {"type": "way", "bounds": bounds(off(_pt, 0.0002), 0.0003),
         "tags": {"tourism": "attraction", "name": "Birk Tower"}}]
ELEMENTS["2025-05-11"] = [
    {"type": "way", "bounds": bounds(H, 0.0100),
     "tags": {"leisure": "park", "name": "Birk Fields", "wikidata": "Q1"}},
    {"type": "way", "bounds": bounds(H, 0.0012),
     "tags": {"tourism": "attraction", "name": "Lotus Spire", "wikidata": "Q2"}},
    {"type": "way", "bounds": bounds(off(H, 0.0001), 0.0002),
     "tags": {"tourism": "viewpoint", "name": "Spire Second Floor"}},
    {"type": "node", "lat": off(H, 0.00008)[0], "lon": H[1],
     "tags": {"tourism": "attraction", "name": "Keeper's Office"}},
    {"type": "node", "lat": H[0], "lon": off(H, 0.0, 0.00047)[1],
     "tags": {"historic": "memorial", "name": "Founder Memorial", "wikidata": "Q3"}},
    {"type": "way", "bounds": {"minlat": H[0] - 0.002, "minlon": H[1] - 0.00005,
                               "maxlat": H[0] + 0.002, "maxlon": H[1] + 0.00005},
     "tags": {"highway": "pedestrian", "name": "Lotus Walk"}}]
ELEMENTS["2025-05-12"] = [
    {"type": "way", "bounds": bounds(J, 0.0002),
     "tags": {"tourism": "hostel", "name": "Hillside Hostel"}},
    {"type": "way", "bounds": bounds(off(J, 0.0001), 0.0002),
     "tags": {"tourism": "hostel", "name": "Lantern Hostel"}},
    {"type": "node", "lat": J[0], "lon": off(J, 0.0, 0.0003)[1],
     "tags": {"amenity": "restaurant", "name": "Birk Kitchen"}},
    {"type": "node", "lat": off(J, -0.0004)[0], "lon": J[1],
     "tags": {"amenity": "cafe", "name": "Lotus Cafe"}},
    {"type": "node", "lat": off(J, 0.0006)[0], "lon": J[1],
     "tags": {"tourism": "attraction", "name": "Birk Hill Street"}}]


def geocoder(cache=None, enabled=False):
    g = pc.Geocoder(Path("/nonexistent-map-cache.json"), enabled, language=LANGUAGE)
    g.cache = dict(cache or {})
    return g


def day_center(pts):
    return (median(p[0] for p in pts), median(p[1] for p in pts))


def timed(day, pts):
    """A day's points as the manifest gives them: one photo an hour from 10."""
    base = datetime.fromisoformat(day)
    return [(p[0], p[1], base.replace(hour=10 + i)) for i, p in enumerate(pts)]


def build_fixture():
    """-> the hand-built map cache, keyed with the engine's own key functions
    — exactly what a run over DAYS asks for and nothing else. ⚠️ Hand-built
    in the shape the engine caches, NOT a recorded live reply: the points
    are synthetic, so nothing real could answer them (Rule 7)."""
    import photo_where
    g = geocoder()
    cache = {}
    radius = pc.LANDMARK_RADIUS_M / 1000
    for day, pts in DAYS.items():
        if day not in ELEMENTS:
            continue
        for stop in photo_where.segment(timed(day, pts)):
            box = pc.points_bbox(stop, pc.LANDMARK_RADIUS_M)
            cache["landmarks:" + ",".join(f"{v:.{pc.PRECISE_DP}f}" for v in box)] = [
                el for el in ELEMENTS[day]
                if any(pc.feature_km((p[0], p[1]), el) <= radius for p in stop)]
    # G61 — the days with no sight within LANDMARK_RADIUS_M ask the wider
    # sight box; nothing answers there, so the stay / zoom 18 / town still
    # names them.
    for day in ("2025-05-03", "2025-05-04", "2025-05-05"):
        for stop in photo_where.segment(timed(day, DAYS[day])):
            box = pc.points_bbox(stop, pc.LANDMARK_WIDE_SIGHT_M)
            cache["sights:" + ",".join(f"{v:.{pc.PRECISE_DP}f}" for v in box)] = []
    cache[g.key_for(day_center(DAYS["2025-05-04"]), 18, precise=True)] = {
        "name": "Seaview Point", "name_tag": "name", "cat": "tourism",
        "type": "viewpoint"}
    cache[g.key_for(day_center(DAYS["2025-05-05"]), 18, precise=True)] = {
        "name": "", "name_tag": None, "cat": "highway", "type": "residential"}
    cache[g.key_for(day_center(DAYS["2025-05-05"]), 10, precise=True)] = {
        "name": "Townfield", "name_tag": "name", "cat": "place", "type": "town"}
    cache[g.key_for(day_center(DAYS["2025-05-06"]), "10adm")] = {
        "name": "Homecity", "name_tag": "admin"}
    return cache


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def offline_env(log=None, answer=None):
    env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(OFFLINE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    if log:
        env["PHOTO_TEST_NET_LOG"] = str(log)
    if answer:
        env["PHOTO_TEST_NET_ANSWER"] = answer
    return env


def requests(log):
    if not Path(log).exists():
        return []
    return [json.loads(line) for line in Path(log).read_text().splitlines()]


def dump(tmp, days=DAYS, cache=None, home_label=None):
    """-> work dir of a bound synthetic dump (pack: one home), with `cache`
    as its geocode-cache.json."""
    rows = []
    for day, pts in days.items():
        for i, pt in enumerate(pts):
            rows.append(ix.row(f"IMG_{day.replace('-', '')}_{i}.jpg",
                               when=f"{day.replace('-', ':')} {10 + i:02d}:00:00",
                               gps=pt))
    wd = ix.make_dump(tmp, rows=rows, batches=[{"batch": 1, "from": "2025-05-01",
                                                "to": "2025-05-01", "place": None}])
    home = {"id": "home-01", "lat": HOME[0], "lon": HOME[1]}
    if home_label:
        home["label"] = home_label
    pack = Path(tmp) / "photo-memory" / ix.OWNER
    prof = json.loads((pack / "photo-profile.json").read_text())
    prof.update(home_locations=[home], language=LANGUAGE, own_camera_makes=["Zenith"])
    (pack / "photo-profile.json").write_text(json.dumps(prof, indent=2))
    if cache is not None:
        (wd.parent / "geocode-cache.json").write_text(json.dumps(cache))
    return wd


def cluster(wd, log, answer=None):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "photo_cluster.py"), str(wd), "--force",
         "--away-km", "10"], capture_output=True, text=True,
        env=offline_env(log, answer))


def places_by_day(wd):
    return {b["from"]: b.get("place")
            for b in json.loads((wd / "batches.json").read_text())["batches"]}


# ---------------------------------------------------------------------------
# M1 — the landmark, end to end
# ---------------------------------------------------------------------------

@case
def the_recorded_cache_is_what_the_engine_asks_for():
    """GUARD. The fixture is the engine's own keys for DAYS; a key change
    turns every lookup below into a (refused) network call, and this names
    that cause first."""
    got = json.loads(FIXTURE.read_text())
    return got == build_fixture(), ("tests/fixtures/map-cache.json is stale — "
                                    "rebuild it with --write-fixture")


@case
def batches_take_the_landmark_and_ask_nothing():
    """⭐ REPRODUCTION (E29, ADR 0006). ⛔ FAILS on 11f5353: every away day was
    named by the zoom-10 town (`Geocoder.city()`), so no landmark could reach
    batches.json. Now: a park over a hotel (D4), museum + beach and not the
    tower (D3), a restaurant on a day with no sight, a zoom-18 viewpoint, the
    town only where zoom 18 answers a road, and the home day keeps R13's
    administrative name — all from the recorded cache, 0 requests."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = dump(tmp, cache=json.loads(FIXTURE.read_text()))
        log = Path(tmp) / "net.log"
        proc = cluster(wd, log)
        got = places_by_day(wd) if proc.returncode == 0 else {}
        sent = requests(log)
    return (got == WANT and not sent), \
        f"rc={proc.returncode} got={got} sent={len(sent)} {proc.stderr[-200:]!r}"


@case
def the_index_flow_names_folders_after_the_landmark():
    """⭐ REPRODUCTION (E29). ⛔ FAILS on 11f5353 (town names). The index
    reads batches.json's place: `init` + `render` name each day folder
    after its landmark, two landmarks joined with `+`."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = dump(tmp, cache=json.loads(FIXTURE.read_text()))
        proc = cluster(wd, Path(tmp) / "net.log")
        if proc.returncode:
            return False, proc.stderr[-300:]
        code, _o, err = ix.run("init", wd)
        if code:
            return False, err[-300:]
        code, _o, err = ix.run("render", wd, "--no-vision")
        days = [fo for fo in ix.index_of(tmp)[0]["folders"]
                if fo.get("rendered") and fo["kind"] == "day"]
        names = sorted(fo["rendered"] for fo in days)
        refused = {fo["rendered"]: fo["validation"]["refusals"] for fo in days
                   if (fo.get("validation") or {}).get("refusals")}
    want = ["20250501_Lotus Garden", "20250502_Old Mill Museum+Harbour Beach",
            "20250503_Birk Inn", "20250504_Seaview Point", "20250505_Townfield"]
    return all(w in names for w in want) and not refused, \
        f"rc={code} names={names} refused={refused} {err[-200:]!r}"


@case
def photo_where_names_a_stop_with_the_same_lookup():
    """REPRODUCTION (M1). ⛔ FAILS on 11f5353: abroad (no day test for this
    owner) a stop got the zoom-13 town. `name_stop` now asks the same
    `Geocoder.landmarks()` first."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = dump(tmp, days={"2025-05-02": DAYS["2025-05-02"]},
                  cache=json.loads(FIXTURE.read_text()))
        (wd / "batches.json").write_text(json.dumps({"batches": [
            {"batch": 1, "label": "b1", "from": "2025-05-02", "to": "2025-05-02"}]}))
        log = Path(tmp) / "net.log"
        proc = subprocess.run([sys.executable, str(SCRIPTS / "photo_where.py"),
                               str(wd), "--batch", "1"], capture_output=True,
                              text=True, env=offline_env(log))
        try:
            day = json.loads(proc.stdout)["days"]["2025-05-02"]
        except (ValueError, KeyError):
            day = {}
        sent = requests(log)
    return (day.get("mode") == "landmark"
            and day.get("names") == ["Old Mill Museum", "Harbour Beach"]
            and not sent), f"day={day} sent={len(sent)} {proc.stderr[-200:]!r}"


# ---------------------------------------------------------------------------
# M1 — the home gate (R13 kept: owner ruling 20261018)
# ---------------------------------------------------------------------------

A43_DAY = {"2025-05-07": [(40.0200, 140.0000)]          # ~2.2 km from home
           + [(40.0600, 140.0000)] * 2}                # ~6.7 km: the centre


def coords_in(text):
    """Every lat/lon pair a request carries: URL parameters and Overpass
    boxes."""
    pairs = []
    m = re.search(r"lat=(-?[0-9.]+).*?lon=(-?[0-9.]+)", text or "")
    if m:
        pairs.append((float(m.group(1)), float(m.group(2)), m.group(1), m.group(2)))
    for box in re.findall(r"\((-?[0-9.]+),(-?[0-9.]+),(-?[0-9.]+),(-?[0-9.]+)\)",
                          text or ""):
        s, w, n, e = (float(v) for v in box)
        lat = min(max(HOME[0], s), n)
        lon = min(max(HOME[1], w), e)
        pairs.append((lat, lon, box[0], box[1]))
    return pairs


def dp(text):
    return len(text.split(".")[1]) if "." in text else 0


@case
def nothing_near_a_home_is_sent_precisely_or_to_overpass():
    """⭐ REPRODUCTION + GUARD (ADR 0006, R13 kept). With an EMPTY cache and
    every request stubbed and logged: the near-home day sends ONE request,
    the 2 dp administrative lookup; no Overpass box and no zoom-18 request
    comes within PLACE_SUPPRESS_KM of the home; and the A43 day — centre far,
    one photo 2.2 km from the door — leaves that photo out of every request.
    ⛔ FAILS on 11f5353 only through the away half (no landmark request is
    made at all); the home half guards R13."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        days = {"2025-05-06": DAYS["2025-05-06"], **A43_DAY}
        wd = dump(tmp, days=days, cache={})
        log = Path(tmp) / "net.log"
        proc = cluster(wd, log, answer="stub")
        sent = requests(log)
    bad, kinds = [], {"overpass": 0, "z18": 0, "admin": 0, "precise": 0}
    for r in sent:
        text = (r["url"] or "") + " " + (r["data"] or "")
        overpass = "overpass" in r["url"]
        z18 = "zoom=18" in r["url"]
        admin = "addressdetails" in r["url"]
        for lat, lon, lat_s, _lon_s in coords_in(text):
            near = pc.haversine_km(HOME, (lat, lon)) <= pc.PLACE_SUPPRESS_KM
            if overpass:
                kinds["overpass"] += 1
            if not overpass and dp(lat_s) > pc.REVERSE_DP:
                kinds["precise"] += 1
            if z18:
                kinds["z18"] += 1
            if admin:
                kinds["admin"] += 1
            if near and (overpass or z18 or dp(lat_s) > pc.REVERSE_DP):
                bad.append(f"near-home {('overpass' if overpass else 'z18' if z18 else 'precise')}: {r['url'][:90]}")
            if near and not admin:
                bad.append(f"near-home non-admin request: {r['url'][:90]}")
    admin_near = [r for r in sent if "addressdetails" in r["url"]]
    return (proc.returncode == 0 and not bad and len(admin_near) == 1
            and kinds["overpass"] >= 1), \
        f"rc={proc.returncode} kinds={kinds} bad={bad[:3]} {proc.stderr[-200:]!r}"


# Photos 4.4 km either side of the home: the day's centre is the north group
# (3 of 5), so the day is away and no stop splits it by its centre alone.
EITHER_SIDE = {"2025-05-08": [(40.0400, 140.0000)] * 3 + [(39.9600, 140.0000)] * 2}


@case
def one_overpass_box_per_stop_and_none_holds_the_home():
    """⭐ REPRODUCTION (M1, privacy). A box drawn round the whole day would
    hold the home between its two groups of photos; one box per stop never
    does, and each stays small. ⛔ FAILS on 11f5353 (no landmark request at
    all); on the first M1 draft the single day box held the home."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = dump(tmp, days=EITHER_SIDE, cache={})
        log = Path(tmp) / "net.log"
        proc = cluster(wd, log, answer="stub")
        boxes = []
        for r in requests(log):
            if "overpass" in r["url"]:
                for box in re.findall(r"\((-?[0-9.]+),(-?[0-9.]+),(-?[0-9.]+),(-?[0-9.]+)\)",
                                      r["data"] or ""):
                    boxes.append(tuple(float(v) for v in box))
    boxes = sorted(set(boxes))
    bad = []
    for s_, w, n, e in boxes:
        lat = min(max(HOME[0], s_), n)
        lon = min(max(HOME[1], w), e)
        if pc.haversine_km(HOME, (lat, lon)) <= pc.PLACE_SUPPRESS_KM:
            bad.append("a box comes within the suppression radius of the home")
        if pc.haversine_km((s_, w), (n, e)) > 7:
            bad.append("a box wider than 7 km")
    return (proc.returncode == 0 and len(boxes) == 2 and not bad), \
        f"rc={proc.returncode} boxes={len(boxes)} bad={bad}"


@case
def a_labelled_home_day_sends_nothing_at_all():
    """GUARD (D-F9). A day at a labelled home takes the owner's word and
    asks no map service of any kind."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = dump(tmp, days={"2025-05-06": DAYS["2025-05-06"]}, cache={},
                  home_label="Hillside")
        log = Path(tmp) / "net.log"
        proc = cluster(wd, log, answer="stub")
        got = places_by_day(wd) if proc.returncode == 0 else {}
        sent = requests(log)
    return (got.get("2025-05-06") == "Hillside" and not sent), \
        f"got={got} sent={[r['url'][:80] for r in sent]}"


@case
def the_cache_never_holds_a_near_home_point_finer_than_2_dp():
    """⭐ GUARD (Q2, the Lead 20261018). Precision is chosen per lookup: the
    cache file the run writes holds no key within PLACE_SUPPRESS_KM of the
    home at more than 2 dp, while an away key is at full precision."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        days = {"2025-05-06": DAYS["2025-05-06"], **A43_DAY,
                "2025-05-05": DAYS["2025-05-05"]}
        wd = dump(tmp, days=days, cache={})
        proc = cluster(wd, Path(tmp) / "net.log", answer="stub")
        path = wd.parent / "geocode-cache.json"
        cache = json.loads(path.read_text()) if path.exists() else {}
    bad, precise_away = [], 0
    for key in cache:
        nums = re.findall(r"-?\d+\.\d+", key)
        for lat_s, lon_s in zip(nums[0::2], nums[1::2]):
            lat, lon = float(lat_s), float(lon_s)
            near = pc.haversine_km(HOME, (lat, lon)) <= pc.PLACE_SUPPRESS_KM
            fine = round(lat, 2) != lat or round(lon, 2) != lon
            if near and fine:
                bad.append(key)
            if not near and fine:
                precise_away += 1
    return (proc.returncode == 0 and cache and not bad and precise_away), \
        f"rc={proc.returncode} keys={len(cache)} bad={bad[:3]} precise_away={precise_away}"


# ---------------------------------------------------------------------------
# M1 — the pure rules
# ---------------------------------------------------------------------------

def pts_at(*groups):
    """[(point, n)] -> n photo points at each point."""
    t = datetime(2025, 5, 1, 10)
    return [(p[0], p[1], t) for p, n in groups for _ in range(n)]


@case
def a_sight_beats_a_hotel_even_with_fewer_photos():
    """REPRODUCTION (D4). ⛔ FAILS on 11f5353 (no landmark ranking). A hotel
    with 5 photos loses to a temple with 2; a stay names a day only when no
    sight does."""
    if not hasattr(pc, "rank_landmarks"):
        return False, "no rank_landmarks()"
    hotel, temple = (45.0, 145.0), (45.002, 145.0)
    els = [{"type": "node", "lat": hotel[0], "lon": hotel[1],
            "tags": {"tourism": "hotel", "name": "Lotus Hotel"}},
           {"type": "node", "lat": temple[0], "lon": temple[1],
            "tags": {"amenity": "place_of_worship", "name": "Birk Temple"}}]
    pts = pts_at((hotel, 5), (off(temple, 0.0002), 2))
    got = pc.pick_landmarks(pc.rank_landmarks(els, pts, "en"), len(pts))
    only_stay = pc.pick_landmarks(pc.rank_landmarks(els[:1], pts, "en"), len(pts))
    return got == ["Birk Temple"] and only_stay == ["Lotus Hotel"], f"{got} {only_stay}"


@case
def a_second_landmark_needs_a_third_and_never_a_third_name():
    """REPRODUCTION (D3). ⛔ FAILS on 11f5353. 4/2/2 of 8: the second at
    2 of 8 (< a third) stays out; 3/3/3 of 9: two names, never three."""
    if not hasattr(pc, "rank_landmarks"):
        return False, "no rank_landmarks()"
    a, b, c = (45.0, 145.0), (45.01, 145.0), (45.02, 145.0)
    els = [{"type": "node", "lat": p[0], "lon": p[1],
            "tags": {"tourism": "attraction", "name": n}}
           for p, n in ((a, "Alpha Falls"), (b, "Beta Rock"), (c, "Gamma Cove"))]
    few = pts_at((a, 4), (b, 2), (c, 2))
    even = pts_at((a, 3), (b, 3), (c, 3))
    one = pc.pick_landmarks(pc.rank_landmarks(els, few, "en"), len(few))
    two = pc.pick_landmarks(pc.rank_landmarks(els, even, "en"), len(even))
    return one == ["Alpha Falls"] and len(two) == 2, f"{one} {two}"


@case
def a_two_day_batch_never_pools_a_third_landmark():
    """⭐ REPRODUCTION (UAT5 U5-8, D3). ⛔ FAILS on d5201b6: a batch of two
    days pooled each day's landmarks — the park of the first and the museum
    + beach of the second — so its leg was named with three. A batch holds
    at most two landmarks, the first in travel order; a one-day batch keeps
    its two."""
    from datetime import date
    g = geocoder(json.loads(FIXTURE.read_text()))

    def places(*days):
        df = {}
        for day in days:
            pts = timed(day, DAYS[day])
            df[date.fromisoformat(day)] = {"centroid": day_center(pts), "points": pts}
        return pc.batch_places(sorted(df), df, g, [])
    two = places("2025-05-01", "2025-05-02")
    one = places("2025-05-02")
    return (two == ["Lotus Garden", "Old Mill Museum"]
            and one == ["Old Mill Museum", "Harbour Beach"]), f"two={two} one={one}"

@case
def each_photo_votes_once_for_the_landmark_it_is_at():
    """⭐ REPRODUCTION (F1, the Lead's live probe 20261018: the photos were
    at the tower, yet the park around it came first and the tower second
    with `+`). Every feature within the radius counted every photo, so the
    park tied the sight and D3 passed both. Now each photo votes once, for
    the smallest feature it is at, else the nearest. ⛔ FAILS on bd4d047."""
    t = (46.0, 146.0)
    park = {"type": "way", "bounds": bounds(t, 0.005),
            "tags": {"leisure": "park", "name": "Lotus Commons"}}
    tower = {"type": "way", "bounds": bounds(t, 0.0003),
             "tags": {"tourism": "attraction", "name": "Birk Tower"}}
    at_tower = pts_at((off(t, 0.0002), 4))
    lawn = at_tower + pts_at((off(t, 0.0020), 2))
    few = at_tower * 2 + pts_at((off(t, 0.0020), 1))
    got = {order: pc.pick_landmarks(pc.rank_landmarks(els, pts, "en"), len(pts))
           for order, els in (("park first", [park, tower]),
                              ("tower first", [tower, park]))
           for pts in (at_tower,)}
    two = pc.pick_landmarks(pc.rank_landmarks([park, tower], lawn, "en"), len(lawn))
    one = pc.pick_landmarks(pc.rank_landmarks([park, tower], few, "en"), len(few))
    return (all(v == ["Birk Tower"] for v in got.values())
            and two == ["Birk Tower", "Lotus Commons"]
            and one == ["Birk Tower"]), f"{got} lawn={two} few={one}"


@case
def a_failed_landmark_lookup_is_said_out_loud():
    """⭐ REPRODUCTION (F2). With every request refused, the away days fall
    to the town or nothing — and the stage SAYS so: batches.json carries the
    count, stderr prints it, and `photo_where` prints it again, so a short
    outage never leaves town names that look final. ⛔ FAILS on bd4d047
    (silent). M12 (U6-4, Lead ruling 20261022): said ONCE per dump — the
    `render` after `cluster` no longer repeats it."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        days = {k: DAYS[k] for k in ("2025-05-01", "2025-05-02")}
        wd = dump(tmp, days=days, cache={})
        log = Path(tmp) / "net.log"
        proc = cluster(wd, log)
        batches = (json.loads((wd / "batches.json").read_text())["batches"]
                   if proc.returncode == 0 else [])
        failed = sum(b.get("landmark_failed_stops", 0) for b in batches)
        flagged = [b["batch"] for b in batches
                   if "landmark_lookup_failed" in b.get("flags", [])]
        # distinct boxes: one overpass_post retries the same box
        overpass = len({r["data"] for r in requests(log) if "overpass" in r["url"]})
        where = subprocess.run([sys.executable, str(SCRIPTS / "photo_where.py"),
                                str(wd), "--batch", "1"], capture_output=True,
                               text=True, env=offline_env(log))
        ix.run("init", wd)
        _c, out, _e = ix.run("render", wd, "--no-vision")
    said = "landmark lookup failed for"
    return (proc.returncode == 0 and failed >= 2 and len(flagged) >= 1
            and said in proc.stderr and said not in out and said in where.stderr
            and overpass == failed), \
        (f"rc={proc.returncode} failed={failed} flagged={flagged} "
         f"overpass={overpass} stderr={proc.stderr[-200:]!r} out={out[-200:]!r} "
         f"where={where.stderr[-200:]!r}")



def c25_retry(tmp, answers):
    """C-25: a dump clustered while every request was refused (its away
    batches flagged), initialised; then `retry-landmarks --go` with the
    shared cache holding `answers` (what the map service answers now), the
    network still refused. -> (batches before, batches after, said, net log)."""
    days = {k: DAYS[k] for k in ("2025-05-01", "2025-05-02")}
    wd = dump(tmp, days=days, cache={})
    log = Path(tmp) / "net.log"
    if cluster(wd, log).returncode:
        raise RuntimeError("cluster failed")
    ix.run("init", wd)
    ix.run("render", wd, "--no-vision")
    before = json.loads((wd / "batches.json").read_text())["batches"]
    (wd.parent / "geocode-cache.json").write_text(json.dumps(answers))
    asked_before = len(requests(log))
    saved = {k: os.environ.get(k) for k in ("PYTHONPATH", "PHOTO_TEST_NET_LOG")}
    os.environ.update(offline_env(log))
    try:
        dry = ix.run("retry-landmarks", wd)
        go = ix.run("retry-landmarks", wd, "--go")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    after = json.loads((wd / "batches.json").read_text())["batches"]
    plan = ix.run("fix-plan", wd)
    return before, after, dry, go, requests(log)[asked_before:], plan


@case
def a_failed_landmark_lookup_can_be_retried_after_the_copy():
    """⭐ C-25 REPRODUCTION. 8 stops' lookups failed on a real run and were
    named by town; the run said "re-run to retry", but the copy was made and
    a re-cut is refused after grouping. `photo_index retry-landmarks` looks
    the failed batches up again through the stage's own lookup (dry run
    writes nothing) and writes the place it now finds into batches.json, the
    flag cleared, so the Review folders page can offer it. ⛔ FAILS on
    3c5eb76: no such command."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        before, after, dry, go, _sent, plan = c25_retry(
            tmp, json.loads(FIXTURE.read_text()))
    flagged = [b["batch"] for b in before
               if "landmark_lookup_failed" in (b.get("flags") or [])]
    fixed = [b for b in after if b["batch"] in flagged]
    return (flagged and dry[0] == 0 and "DRY RUN" in dry[1] and go[0] == 0
            and all("landmark_lookup_failed" not in (b.get("flags") or [])
                    and b.get("place") for b in fixed)
            and any(b.get("place") != o.get("place")
                    for b, o in zip(fixed, [x for x in before if x["batch"] in flagged]))
            and any("(R1)" in ln and b["place"].split("+")[0] in ln
                    for b in fixed for ln in plan[1].splitlines())), \
        f"flagged={flagged} dry={dry[1][-300:]!r} go={go[0]} {(go[1] + go[2])[-400:]!r} " \
        f"after={[(b['batch'], b.get('place'), b.get('flags')) for b in after]}"


@case
def a_lookup_that_fails_again_keeps_the_batch_as_it_was():
    """GUARD C-25 — with the service still refusing, nothing is written, the
    flag stays, and a failure is never cached (each retry asks again)."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        before, after, _dry, go, sent, _plan = c25_retry(tmp, {})
    return (go[0] == 0 and before == after and "still no landmark" in go[1]
            and any("overpass" in r["url"] for r in sent)), \
        f"go={go} sent={len(sent)}"


@case
def a_stop_whose_lookup_failed_is_named_by_its_town():
    """⭐ REPRODUCTION (UAT5 U5-9). ⛔ FAILS on d5201b6: a day whose other
    stop answered (the museum, from the recorded cache) took only that
    landmark; the stop whose Overpass request failed got no name at all,
    though the run said "named by town". Now that stop adds its own town
    (cached; no request is sent but the failed one), after the landmarks."""
    from datetime import date
    x = off(B, 0.05)
    pts = timed("2025-05-02", DAYS["2025-05-02"] + [x, off(x, 0.0001)])
    g = geocoder(json.loads(FIXTURE.read_text()), enabled=True)
    import photo_where
    far = photo_where.stop_center(photo_where.segment(pts)[-1])
    g.cache[g.key_for(far, 10, precise=True)] = {
        "name": "Millbrook", "name_tag": "name", "cat": "place", "type": "town"}
    sent = []

    def refuse(query, backoffs=()):
        sent.append(query)
        return None
    saved, pc.overpass_post = pc.overpass_post, refuse
    try:
        d = date(2025, 5, 2)
        got = pc.batch_places([d], {d: {"centroid": day_center(pts), "points": pts}},
                              g, [])
    finally:
        pc.overpass_post = saved
    # The beach is 2 of 8 photos now, below a third (D3): the museum alone.
    return (got == ["Old Mill Museum", "Millbrook"]
            and len(sent) == 1 and len(g.landmark_failed) == 1), \
        f"got={got} sent={len(sent)} failed={len(g.landmark_failed)}"

def trip_legs(tmp):
    """The UAT5 B4 shape (G44): a trip abroad of two legs, the first two days
    long and holding most photos, so the trip takes ITS two landmarks as its
    own words. The places come from the recorded cache through
    `batch_places`, as the cluster stage writes them. Initialised, the fix
    plan's R5 MAKE-TRIP row answered `ok`, rendered. -> (R5 row, leg names)."""
    from datetime import date
    import fix_plan_cases as fpc
    days = {k: DAYS[k] for k in ("2025-05-01", "2025-05-02", "2025-05-03")}
    wd = dump(tmp, days=days, cache=json.loads(FIXTURE.read_text()))
    g = geocoder(json.loads(FIXTURE.read_text()))

    def place(*ds):
        df = {}
        for d in ds:
            pts = timed(d, DAYS[d])
            df[date.fromisoformat(d)] = {"centroid": day_center(pts), "points": pts}
        return "+".join(pc.batch_places(sorted(df), df, g, []))
    batches = [{"batch": 1, "from": "2025-05-01", "to": "2025-05-02",
                "place": place("2025-05-01", "2025-05-02")},
               {"batch": 2, "from": "2025-05-03", "to": "2025-05-03",
                "place": place("2025-05-03")}]
    batches = [dict(b, day_type="OVERSEAS", country_word="Countryland") for b in batches]
    (wd / "batches.json").write_text(json.dumps({"source": "/raw/dump-a",
                                                 "batches": batches}))
    for cmd in ("init", "render", "check"):
        fpc.must(ix.run(cmd, wd, *(["--no-vision"] if cmd == "render" else [])), cmd)
    ix.run("freeze", wd)
    r5 = [r for r in fpc.rows(wd) if "(R5)" in r]
    fpc.answer(wd, *["ok" if "(R5)" in r else "skip" for r in fpc.rows(wd)])
    fpc.must(fpc.apply(wd), "apply R5")
    fpc.must(ix.run("render", wd, "--no-vision"), "render")
    folders = ix.index_of(tmp)[0]["folders"]
    legs = [fo["rendered"] for fo in folders if fo["kind"] == "leg"]
    trip = [fo["rendered"] for fo in folders if fo["kind"] == "trip"]
    return r5, trip, sorted(legs)


@case
def a_trip_leg_is_never_placeless():
    """⭐ REPRODUCTION (UAT5 U5-9, G44). ⛔ FAILS on 6e4d848: the first leg's
    two landmarks became the trip's words, so D-I13 dropped them and the leg
    had no place at all (`0501-0502` and nothing after the date but [what]).
    Now a leg left with no word keeps its top landmark; a leg with a word of
    its own is unchanged."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        r5, trip, legs = trip_legs(tmp)
    return (len(r5) == 1 and trip == ["20250501-0503_Countryland_Lotus Garden+Old Mill Museum"]
            and legs[0].startswith("0501-0502_Lotus Garden")
            and "Old Mill Museum" not in legs[0]
            and legs[1].startswith("0503_Birk Inn")), f"r5={r5} trip={trip} legs={legs}"

@case
def the_execution_log_carries_the_failed_landmark_count():
    """⭐ REPRODUCTION (F2). The execution log is the record an owner reads
    after the copy, so a batch named by the town after a failed lookup says
    so there too — only for the plan's own batches. ⛔ FAILS on bd4d047."""
    import photo_execute_cases as ex
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        wd, _src, _trip = ex.build_dump(tmp, tmp / "drive")
        bdata = json.loads((wd / "batches.json").read_text())
        bdata["batches"][0].update(flags=["landmark_lookup_failed"],
                                   landmark_failed_stops=2)
        (wd / "batches.json").write_text(json.dumps(bdata))
        r = ex.run_execute(wd, "--go")
        md = (wd / "plan" / "execution-log_P1.md")
        md = md.read_text() if md.exists() else ""
    said = "landmark lookup failed for 2 stop(s)"
    return (r.returncode == 0 and said in md and said in r.stdout), \
        f"rc={r.returncode} md={md[-200:]!r} {r.stderr[-200:]!r}"


@case
def a_notable_outline_beats_a_room_inside_it():
    """⭐ REPRODUCTION (F3, the Lead's live probe on 90d299e: photos under a
    tower named a small office node inside it). Among the features a photo
    is at: notable (wikidata) first, then an outline that contains the
    photo, then the smallest. ⛔ FAILS on 90d299e ("Keeper's Office")."""
    pts = pts_at(*((off(H, 0.0001 * i), 1) for i in range(4)))
    got = pc.pick_landmarks(pc.rank_landmarks(ELEMENTS["2025-05-11"], pts, "en"),
                            len(pts))
    return got == ["Lotus Spire"], f"{got}"


@case
def a_sight_within_reach_beats_the_hostel_the_photo_is_in():
    """⭐ REPRODUCTION (F4, the Lead's live probe on 199ca9b: photos inside
    two hostels named the day after a restaurant 24 m off, with the old
    street 67 m away). D4: a sight within LANDMARK_SIGHT_REACH_M takes the
    vote before any stay. ⛔ FAILS on 199ca9b ("Birk Kitchen" or a hostel)."""
    pts = pts_at(*((off(J, 0.00005 * i), 1) for i in range(4)))
    got = pc.pick_landmarks(pc.rank_landmarks(ELEMENTS["2025-05-12"], pts, "en"),
                            len(pts))
    far = [dict(el, lat=off(J, 0.0016)[0]) if el["tags"].get("tourism") == "attraction"
           else el for el in ELEMENTS["2025-05-12"]]
    stays = pc.pick_landmarks(pc.rank_landmarks(far, pts, "en"), len(pts))
    return (got == ["Birk Hill Street"]
            and stays and stays[0] != "Birk Hill Street"), f"{got} far={stays}"


@case
def a_temple_node_near_the_photos_beats_the_park_around_them():
    """⭐ REPRODUCTION (F4). A non-notable sight mapped as a node 15 m off
    counts as containing the photo (LANDMARK_NODE_AT_M), so it beats the
    non-notable park whose outline holds the photos — the smaller wins.
    ⛔ FAILS on 199ca9b (the park)."""
    t = (48.0, 148.0)
    park = {"type": "way", "bounds": bounds(t, 0.005),
            "tags": {"leisure": "park", "name": "Lotus Commons"}}
    temple = {"type": "node", "lat": off(t, 0.000135)[0], "lon": t[1],
              "tags": {"amenity": "place_of_worship", "name": "Birk Temple"}}
    pts = pts_at((t, 3))
    got = pc.pick_landmarks(pc.rank_landmarks([park, temple], pts, "en"), 3)
    return got == ["Birk Temple"], f"{got}"


@case
def a_plain_pedestrian_street_is_never_a_landmark():
    """⭐ REPRODUCTION (F3). A pedestrian street with only a name is a
    street, not a sight: never named, and never asked of Overpass without a
    notable tag. ⛔ FAILS on 90d299e (named "Lotus Lane")."""
    p = (47.0, 147.0)
    street = {"type": "way", "bounds": bounds(p, 0.0005),
              "tags": {"highway": "pedestrian", "name": "Lotus Lane"}}
    got = pc.pick_landmarks(pc.rank_landmarks([street], pts_at((p, 3)), "en"), 3)
    query = pc.landmark_query((1, 2, 3, 4))
    plain = [ln for ln in query.splitlines()
             if "pedestrian" in ln and "wiki" not in ln]
    return got == [] and not plain, f"{got} plain={plain}"


@case
def a_tagged_old_street_names_a_day_with_no_other_sight():
    """GUARD (F3). A historic or notable pedestrian street names a day spent
    walking it when nothing else is there; a temple on it takes the photos
    taken at both — by the street rule, not only by size."""
    p = (47.5, 147.5)
    old = {"type": "way", "bounds": bounds(p, 0.0005),
           "tags": {"highway": "pedestrian", "historic": "yes",
                    "name": "Old Birk Street"}}
    wiki = {"type": "way", "bounds": bounds(p, 0.0005),
            "tags": {"highway": "pedestrian", "wikidata": "Q4",
                     "name": "Lotus Arcade"}}
    temple = {"type": "way", "bounds": bounds(p, 0.0001),
              "tags": {"amenity": "place_of_worship", "name": "Birk Temple"}}
    pts = pts_at((p, 3))
    alone = pc.pick_landmarks(pc.rank_landmarks([old], pts, "en"), 3)
    notable = pc.pick_landmarks(pc.rank_landmarks([wiki], pts, "en"), 3)
    beside = pc.pick_landmarks(pc.rank_landmarks([old, temple], pts, "en"), 3)
    return (alone == ["Old Birk Street"] and notable == ["Lotus Arcade"]
            and beside == ["Birk Temple"]), f"{alone} {notable} {beside}"


@case
def a_photo_inside_a_large_park_is_at_the_park():
    """GUARD. A way is measured to its bounding box, so a photo deep inside
    a park far from the park's centre still counts for it."""
    if not hasattr(pc, "feature_km"):
        return False, "no feature_km()"
    el = {"type": "way", "bounds": {"minlat": 45.0, "minlon": 145.0,
                                    "maxlat": 45.05, "maxlon": 145.05}}
    return pc.feature_km((45.001, 145.049), el) == 0.0, "not inside"


@case
def a_country_sized_answer_is_never_a_place():
    """⭐ REPRODUCTION (E14). ⛔ FAILS on 11f5353: a zoom-10 reply that is a
    whole country became `[where]`. Read from the reply's structure, never
    its spelling, and remembered so the cache never serves it either."""
    import urllib.request as ur
    import time as _time
    reply = {"name": "Countryland", "addresstype": "country", "place_rank": 4,
             "category": "boundary", "type": "administrative",
             "namedetails": {"name": "Countryland", "name:en": "Countryland"}}

    class R:
        def __init__(self):
            self.body = json.dumps(reply).encode()

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    real, real_sleep = ur.urlopen, _time.sleep
    ur.urlopen, _time.sleep = (lambda *a, **k: R()), (lambda s: None)
    try:
        g = geocoder(enabled=True)
        first = g.city((50.0, 150.0))
        g.enabled = False
        again = g.city((50.0, 150.0))
    finally:
        ur.urlopen, _time.sleep = real, real_sleep
    return first is None and again is None, f"first={first!r} again={again!r}"


@case
def an_old_2_dp_town_row_is_asked_again_online_and_kept_offline():
    """⭐ REPRODUCTION (E14 in an existing cache). A row written before M1 was
    never checked for a country-sized answer: an online run asks again at
    full precision (and drops the country), while an offline stage
    (relabel, split) or a failed fetch still reads the old town."""
    import urllib.request as ur
    import time as _time
    pt = (50.0, 150.0)
    reply = {"name": "Countryland", "addresstype": "country", "place_rank": 4,
             "namedetails": {"name": "Countryland"}}

    class R:
        def read(self):
            return json.dumps(reply).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def legacy_geocoder(enabled):
        g = geocoder(enabled=enabled)
        g.cache = {g.key_for(pt, 10): {"name": "Countryland", "name_tag": "name"}}
        return g

    real, real_sleep = ur.urlopen, _time.sleep
    _time.sleep = lambda s: None
    try:
        ur.urlopen = lambda *a, **k: R()
        online = legacy_geocoder(True).city(pt, precise=True)

        def refuse(*a, **k):
            raise OSError("refused")
        ur.urlopen = refuse
        failed = legacy_geocoder(True).city(pt, precise=True)
        offline = legacy_geocoder(False).city(pt, precise=True)
    finally:
        ur.urlopen, _time.sleep = real, real_sleep
    return (online is None and failed == "Countryland" and offline == "Countryland"), \
        f"online={online!r} failed={failed!r} offline={offline!r}"


@case
def zoom_18_names_only_a_landmark_class():
    """REPRODUCTION (M1). ⛔ FAILS on 11f5353 (no zoom-18 step). A road or a
    house number at zoom 18 is never a place name — an English owner has no
    address guard (`is_address` reads CJK only)."""
    if not hasattr(pc.Geocoder, "zoom18"):
        return False, "no zoom18()"
    p, q = (50.0, 150.0), (51.0, 151.0)
    g = geocoder()
    g.cache = {g.key_for(p, 18, precise=True): {"name": "", "cat": "highway"},
               g.key_for(q, 18, precise=True): {"name": "Lotus Lookout",
                                                "cat": "tourism"}}
    return g.zoom18(p) is None and g.zoom18(q) == "Lotus Lookout", "zoom18"


@case
def an_away_lookup_is_full_precision_and_the_admin_one_stays_2_dp():
    """⭐ REPRODUCTION (ADR 0006 reverses RS7c for AWAY points). ⛔ FAILS on
    11f5353: `city()` and `area_name()` sent 2 dp, which cannot find a
    landmark. `city_admin()` — the near-home lookup — still sends 2 dp."""
    import urllib.request as ur
    import time as _time
    import photo_where as pw
    fine = (20.1234567891234, 100.9876543219876)
    sent = []

    def fake(req, *a, **k):
        sent.append(req.full_url)
        raise RuntimeError("network refused by the test")

    real, real_sleep = ur.urlopen, _time.sleep
    ur.urlopen, _time.sleep = fake, (lambda s: None)
    try:
        g = geocoder(enabled=True)
        calls = {"city": lambda: g.city(fine, precise=True),
                 "area_name": lambda: pw.area_name(fine, g, precise=True),
                 "zoom18": lambda: g.zoom18(fine),
                 "city_admin": lambda: g.city_admin(fine)}
        got = {}
        for name, call in calls.items():
            before = len(sent)
            try:
                call()
            except TypeError as exc:
                got[name] = f"TypeError {exc}"
                continue
            url = sent[-1] if len(sent) > before else ""
            m = re.search(r"lat=(-?[0-9.]+)", url)
            got[name] = dp(m.group(1)) if m else None
    finally:
        ur.urlopen, _time.sleep = real, real_sleep
    want = {"city": pc.PRECISE_DP if hasattr(pc, "PRECISE_DP") else 6,
            "area_name": 6, "zoom18": 6, "city_admin": 2}
    return got == want, f"{got}"


# ---------------------------------------------------------------------------
# M2 — the owner's language, never Simplified for a Traditional owner
# ---------------------------------------------------------------------------

# i18n-guard:allow-begin — locale detection data: the cases turn on the
# SCRIPT of the value, so an ASCII placeholder cannot exercise them.
SIMPLIFIED_E15 = "赫莫萨比奇"     # a beach town, Simplified
TRADITIONAL = "赫莫薩比奇"        # the same, Traditional
NEUTRAL_HANS = "吉田"                         # same glyphs in both
# i18n-guard:allow-end


@case
def a_traditional_owner_gets_english_before_a_simplified_name():
    """⭐ REPRODUCTION (E6/E15). ⛔ FAILS on 11f5353: a zh-TW owner got the
    Simplified `name:zh`. Order: owner language → English → neutral name,
    and a Simplified value is passed over."""
    tags = {"name": "Hermosa", "name:en": "Hermosa Beach", "name:zh": SIMPLIFIED_E15}
    got = pc.read_name({"namedetails": tags, "name": "Hermosa"}, "zh-TW")
    hant = pc.read_name({"namedetails": dict(tags, **{"name:zh-Hant": TRADITIONAL})},
                        "zh-TW")
    return got == ("Hermosa Beach", "name:en") and hant[0] == TRADITIONAL, \
        f"{got} {hant}"


@case
def a_traditional_owner_keeps_a_traditional_neutral_name_before_english():
    """⭐ GUARD (M2, the owner's own country). A small place in Taiwan often
    carries only `name` (Traditional) and `name:en`: the Traditional name is
    the owner's language and beats English. Kana or hangul is not."""
    tags = {"name": TRADITIONAL, "name:en": "Hermosa Beach"}
    got = pc.read_name({"namedetails": tags, "name": TRADITIONAL}, "zh-TW")
    kana = pc.read_name({"namedetails": {"name": TRADITIONAL + "\u306e",
                                         "name:en": "Hermosa Beach"}}, "zh-TW")
    en = pc.read_name({"namedetails": tags}, "en")
    return (got == (TRADITIONAL, "name") and kana[0] == "Hermosa Beach"
            and en[0] == "Hermosa Beach"), f"{got} {kana} {en}"


@case
def a_simplified_tag_is_caught_by_structure_not_only_by_characters():
    """REPRODUCTION (E15). A value with no Simplified-only character is still
    Simplified when it IS the tag set's `name:zh-Hans` and no Traditional tag
    says the same. ⛔ FAILS on 11f5353 (`name:zh` returned as is)."""
    tags = {"name:zh": NEUTRAL_HANS, "name:zh-Hans": NEUTRAL_HANS,
            "name:en": "Lotus Field"}
    got = pc.read_name({"namedetails": tags}, "zh-TW")
    both = dict(tags, **{"name:zh-Hant": NEUTRAL_HANS})
    kept = pc.read_name({"namedetails": both}, "zh-TW")
    return got == ("Lotus Field", "name:en") and kept[0] == NEUTRAL_HANS, \
        f"{got} {kept}"


@case
def a_simplified_only_place_has_no_name_rather_than_a_wrong_one():
    """REPRODUCTION (E6). No owner-language and no English tag, and the
    neutral name is Simplified: no name at all. ⛔ FAILS on 11f5353."""
    got = pc.read_name({"namedetails": {"name": SIMPLIFIED_E15},
                        "name": SIMPLIFIED_E15}, "zh-TW")
    return got == (None, None), f"{got}"


@case
def an_overpass_landmark_is_named_in_the_owners_language_too():
    """REPRODUCTION (M2 on the Overpass path). ⛔ FAILS on 11f5353: Overpass
    read only `tags.name`. A landmark's `name:en` names it for an English
    owner; a zh-TW owner gets English over a Simplified `name:zh`."""
    if not hasattr(pc, "rank_landmarks"):
        return False, "no rank_landmarks()"
    p = (45.0, 145.0)
    el = {"type": "node", "lat": p[0], "lon": p[1],
          "tags": {"tourism": "attraction", "name": "Lotusberg",
                   "name:en": "Lotus Hill", "name:zh": SIMPLIFIED_E15}}
    pts = pts_at((p, 3))
    en = pc.pick_landmarks(pc.rank_landmarks([el], pts, "en"), 3)
    zh = pc.pick_landmarks(pc.rank_landmarks([el], pts, "zh-TW"), 3)
    return en == ["Lotus Hill"] and zh == ["Lotus Hill"], f"{en} {zh}"


# ---------------------------------------------------------------------------
# G61 — with no sight near, a sight a little further off names the stop
# ---------------------------------------------------------------------------

def wide_geocoder(tmp, near, wide, enabled=False):
    """A Geocoder whose cache holds `near` for the stop's 300 m box and `wide`
    for its sight box (None = not cached), at point A."""
    g = pc.Geocoder(Path(tmp) / "c.json", enabled=enabled, language=LANGUAGE)
    def key(prefix, margin):
        box = pc.points_bbox([A], margin)
        return prefix + ",".join(f"{v:.{pc.PRECISE_DP}f}" for v in box)
    g.cache[key("landmarks:", pc.LANDMARK_RADIUS_M)] = near
    if wide is not None:
        g.cache[key("sights:", getattr(pc, "LANDMARK_WIDE_SIGHT_M", 3000))] = wide
    return g


def element(name, tags, dlat):
    return {"type": "node", "lat": A[0] + dlat, "lon": A[1],
            "tags": {"name": name, **tags}}


from datetime import datetime as _dt  # noqa: E402
PT_A = (A[0], A[1], _dt(2025, 5, 1, 10))
INN = element("Lotus Inn", {"tourism": "hotel"}, 0.0)
CAFE = element("Birk Cafe", {"amenity": "cafe"}, 0.0)
FALLS = element("Lotus Falls", {"natural": "waterfall"}, 0.015)     # ~1.7 km


@case
def with_no_sight_near_a_sight_further_off_beats_a_stay():
    """⭐ G61 REPRODUCTION (C-5, C-7, C-8, C-10, C-12). Only an inn and a cafe
    within 300 m, a waterfall 1.7 km off: the stop is named after the
    waterfall. ⛔ FAILS on 7280c54: the inn named the stop (no wider search)."""
    with tempfile.TemporaryDirectory() as tmp:
        g = wide_geocoder(tmp, [INN, CAFE], [FALLS])
        got = g.landmarks([PT_A])
        none = wide_geocoder(tmp, [INN], []).landmarks([PT_A])
    return (got == ["Lotus Falls"] and none == ["Lotus Inn"]), f"got={got} none={none}"


@case
def the_wider_sight_search_is_never_made_near_a_home():
    """GUARD (G61, G28). A home 4 km from the photos: the wider box would
    hold it, so no sight request is sent and the stay names the stop."""
    sent = []
    real = pc.overpass_post
    pc.overpass_post = lambda q, **k: sent.append(q) or []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            g = wide_geocoder(tmp, [INN], None, enabled=True)
            home = (A[0] + 0.036, A[1], None, None)               # ~4 km
            got = g.landmarks([PT_A], [home])
            far = wide_geocoder(tmp, [INN], None, enabled=True)
            far.landmarks([PT_A], [(A[0] + 0.2, A[1], None, None)])   # ~22 km
    finally:
        pc.overpass_post = real
    return (got == ["Lotus Inn"] and len(sent) == 1), f"got={got} sent={len(sent)}"


@case
def the_batch_says_which_place_words_are_not_a_sight():
    """⭐ G61: batches.json carries `place_kinds` for a place word that is a
    stay or an eatery (the restaurant day), and none for a sight or a town —
    what Review folders reads for its R1 row. ⛔ FAILS on 7280c54 (no
    `place_kinds`: nothing could say the folder is named after an eatery)."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = dump(tmp, cache=json.loads(FIXTURE.read_text()))
        proc = cluster(wd, Path(tmp) / "net.log")
        kinds = {b["from"]: b.get("place_kinds")
                 for b in json.loads((wd / "batches.json").read_text())["batches"]}
    return (proc.returncode == 0 and kinds["2025-05-03"] in ({"Birk Inn": "eatery"},
                                                             {"Birk Inn": "stay"})
            and kinds["2025-05-01"] is None and kinds["2025-05-05"] is None), f"{kinds}"

STONE = element("Lotus Stone", {"historic": "memorial"}, 0.0)
NOTED = element("Birk Memorial", {"historic": "memorial", "wikidata": "Q1"}, 0.0)


@case
def a_minor_historic_object_names_the_stop_and_is_flagged_a_street():
    """⭐ S-2 REPRODUCTION (G61 option A). A memorial stone with no
    wikidata/wikipedia tag still names the stop, and no wider search replaces
    it — but its kind is `street`, so the folder gets an R1 row. A notable
    memorial stays a sight. ⛔ FAILS on b0293f9: the stone was a `sight`."""
    with tempfile.TemporaryDirectory() as tmp:
        g = wide_geocoder(tmp, [STONE, INN], [FALLS])
        got = g.landmarks([PT_A])
        n = wide_geocoder(tmp, [NOTED], [FALLS])
        noted = n.landmarks([PT_A])
    return (got == ["Lotus Stone"] and g.place_kinds == {"Lotus Stone": "street"}
            and noted == ["Birk Memorial"]
            and n.place_kinds == {"Birk Memorial": "sight"}), \
        f"got={got} {g.place_kinds} noted={noted} {n.place_kinds}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--write-fixture", action="store_true")
    args = ap.parse_args()
    if args.write_fixture:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(build_fixture(), indent=1, sort_keys=True) + "\n")
        print(f"wrote {FIXTURE}")
        return 0
    failures = []
    for fn in CASES:
        try:
            ok, detail = fn()
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  {fn.__name__.replace('_', ' ')}"
                  + ("" if ok else f"   {detail}"))
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} landmark cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
