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
}
WANT = {"2025-05-01": "Lotus Garden",
        "2025-05-02": "Old Mill Museum+Harbour Beach",
        "2025-05-03": "Birk Inn",
        "2025-05-04": "Seaview Point",
        "2025-05-05": "Townfield",
        "2025-05-06": "Homecity"}


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


def geocoder(cache=None, enabled=False):
    g = pc.Geocoder(Path("/nonexistent-map-cache.json"), enabled, language=LANGUAGE)
    g.cache = dict(cache or {})
    return g


def day_center(pts):
    return (median(p[0] for p in pts), median(p[1] for p in pts))


def build_fixture():
    """-> the recorded cache, keyed with the engine's own key functions —
    exactly what a run over DAYS asks for and nothing else."""
    g = geocoder()
    cache = {}
    for day, pts in DAYS.items():
        if day in ELEMENTS:
            box = pc.points_bbox(pts, pc.LANDMARK_RADIUS_M)
            cache["landmarks:" + ",".join(f"{v:.{pc.PRECISE_DP}f}" for v in box)] = \
                ELEMENTS[day]
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
        names = sorted(fo["rendered"] for fo in ix.index_of(tmp)[0]["folders"]
                       if fo.get("rendered") and fo["kind"] == "day")
    want = ["20250501_Lotus Garden", "20250502_Old Mill Museum+Harbour Beach",
            "20250503_Birk Inn", "20250504_Seaview Point", "20250505_Townfield"]
    return all(w in names for w in want), f"rc={code} names={names} {err[-200:]!r}"


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
    pts = pts_at((hotel, 5), (off(temple, 0.004), 2))
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
