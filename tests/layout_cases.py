#!/usr/bin/env python3
"""M7 cases (P1, G22): the year-folders answer on the onboarding surfaces and
in the pack. The layout it drives (`photo_index.layout_path`, the copy under
`YYYY/`) is in index_group_cases.

  python3 tests/layout_cases.py [-v]

Exit 0 = pass. Every pack is a copy of the shipped template in a temp dir.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import photo_onboard_page as op  # noqa: E402
import photo_profile  # noqa: E402
import onboard_page_cases as oc  # noqa: E402

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def apply_lines(pack, text):
    """-> (rc, printed, profile) after `apply --write-pack` of pasted lines."""
    ans = os.path.join(os.path.dirname(pack), "answers.txt")
    io.open(ans, "w", encoding="utf-8").write(text)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = op.main(["apply", ans, "--write-pack", pack])
        except SystemExit as exc:
            code = exc.code
    prof = json.load(io.open(os.path.join(pack, "photo-profile.json"),
                             encoding="utf-8"))
    return code, buf.getvalue(), prof


def page_lines(state):
    """Run the page's own `lines()` with node; None when node is absent."""
    node = shutil.which("node")
    if not node:
        return None
    tpl = (ROOT / "templates" / "onboarding-page.html").read_text(encoding="utf-8")
    full = dict({"makes": {}, "screens": {}, "homes": {}, "language": "",
                 "types": "", "away": "", "pets": "", "country": "",
                 "year": ""}, **state)
    script = ('var KEY = {makes:"makes", screen:"screen", home:"home", '
              'language:"language", types:"types", away:"away_km", '
              'pets:"pets", country:"country", year:"year_folders"};\n'
              'var state = %s;\n%s\nconsole.log(JSON.stringify(lines()));'
              % (json.dumps(full), oc.js_fn_body(tpl, "lines")))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True)
    return json.loads(out.stdout) if out.returncode == 0 else [out.stderr[:200]]


@case
def a_year_folders_answer_is_read_and_a_wrong_one_refused():
    """REPRODUCTION (G22). ⛔ FAILS on c7b761e: `year_folders` is not an
    answer key, so the line is refused as unknown."""
    got = [op.parse_lines("year_folders: %s\n" % v).get("year_folders")
           for v in ("yes", "No", "YES")]
    refused = []
    for bad in ("maybe", "true", "1"):
        try:
            op.parse_lines("year_folders: %s\n" % bad)
            refused.append(False)
        except SystemExit:
            refused.append(True)
    return got == ["yes", "no", "yes"] and all(refused), f"{got} {refused}"


@case
def apply_writes_the_answer_and_a_later_sheet_may_change_it():
    """⭐ REPRODUCTION (G22). `apply --write-pack` stores `year_folders` as a
    boolean the layout reads; a later `no` turns it off (it decides where
    the NEXT copies land); a sheet without the line changes nothing.
    ⛔ FAILS on c7b761e (not an answer key)."""
    with tempfile.TemporaryDirectory() as tmp:
        pack = oc.fresh_pack(tmp, "pack")
        before = json.load(io.open(os.path.join(pack, "photo-profile.json"),
                                   encoding="utf-8"))
        c1, _s1, yes = apply_lines(pack, "year_folders: yes\n")
        c2, _s2, no = apply_lines(pack, "year_folders: no\n")
        c3, _s3, kept = apply_lines(pack, "pets: Lotus\n")
    return (c1 == 0 and c2 == 0 and c3 == 0
            and "year_folders" not in before
            and yes.get("year_folders") is True
            and photo_profile.year_folders(yes) is True
            and no.get("year_folders") is False and kept.get("year_folders") is False), \
        f"rc={c1},{c2},{c3} yes={yes.get('year_folders')} no={no.get('year_folders')}"


@case
def the_page_writes_the_answer_line_only_when_given():
    """REPRODUCTION (G22). The page's `lines()` — the single reader of its
    answers — writes `year_folders: yes|no` once the owner picks, and
    nothing while it is undecided (a quote is never an answer).
    ⛔ FAILS on c7b761e (no such answer on the page)."""
    yes = page_lines({"year": "yes"})
    if yes is None:
        return True, "node not installed — skipped"
    no = page_lines({"year": "no"})
    blank = page_lines({})
    return (yes == ["year_folders: yes"] and no == ["year_folders: no"]
            and blank == []), f"{yes} {no} {blank}"


@case
def the_page_starts_undecided_and_quotes_the_pack():
    """GUARD (G22, the onboarding rule "nothing is pre-selected"). The page
    data carries the pack's own answer to quote, "" for a pack that never
    gave one; the template ships no `year_folders`, so a new pack is flat
    until its owner answers."""
    tpl = json.loads((ROOT / "templates" / "photo-memory" / "_template"
                      / "photo-profile.json").read_text())
    return (op.year_folders_held({}) == ""
            and op.year_folders_held({"year_folders": True}) == "yes"
            and op.year_folders_held({"year_folders": False}) == "no"
            and "year_folders" not in tpl
            and photo_profile.year_folders(tpl) is False), "held/template"


@case
def a_malformed_year_folders_value_stops_the_run():
    """GUARD (M7). It decides where every copy lands, so a value that is not
    true/false is refused rather than guessed."""
    try:
        photo_profile.year_folders({"year_folders": "yes"})
        return False, "accepted a string"
    except SystemExit:
        return True, ""


# ---------------------------------------------------------------------------
# E28 — a trip abroad, PROPOSED as one trip folder (owner rulings Q2/Q3)
# ---------------------------------------------------------------------------

def group_index(tmp):
    """-> (work dir, pack, index, batches) of index_group's synthetic dump:
    F001-F005 hold 2024-10-25..31 (no photo on 10-28), F004 two days."""
    import index_group_cases as g
    import photo_index
    wd, _pack = g.ready(tmp)
    pack, _target, idx = photo_index.load(wd, None)
    batches = json.loads((wd / "batches.json").read_text())["batches"]
    return wd, pack, idx, batches


def abroad(batches, word="Countryland", upto=5):
    return [dict(b, day_type="OVERSEAS", **({"country_word": word} if word else {}))
            if b["batch"] <= upto else dict(b, day_type="TW_AWAY") for b in batches]


@case
def a_run_of_days_abroad_is_proposed_as_one_trip_named_country_and_place():
    """⭐ REPRODUCTION (E28, Q3 owner ruling 20261018). Five day folders on seven
    days abroad (one day with no photo between) are ONE proposal: the five
    folders, `YYYYMMDD-MMDD_<country>_<place>+<place>` with the legs' own
    places, most photos first, and the photo count. ⛔ FAILS on c7b761e
    (no trip_candidates: a trip abroad stayed loose day folders)."""
    import photo_index
    from index_group_cases import ix
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        _wd, pack, idx, batches = group_index(tmp)
        got = photo_index.trip_candidates(idx, abroad(batches), pack)
    want = [{"folders": ["F001", "F002", "F003", "F004", "F005"],
             "to": "20241025-1031_Countryland_Dunmore+Ashford",
             "days": ["2024-10-25", "2024-10-26", "2024-10-27", "2024-10-29",
                      "2024-10-30", "2024-10-31"], "span": "1025-1031",
             "photos": 6, "where": ["Dunmore", "Ashford"],
             "country": "Countryland"}]
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        _wd, pack, idx, batches = group_index(tmp)
        by_profile = photo_index.trip_candidates(idx, abroad(batches), pack.profile)
    return got == want and by_profile == want, f"{got} profile={by_profile}"


@case
def an_ok_through_make_trip_renders_exactly_the_proposed_name():
    """⭐ REPRODUCTION (E28 → B's R5 MAKE-TRIP). The proposal is applied
    through `group make-trip` with `--where` twice and `--country`; render
    then names the trip parent exactly as proposed (country on the trip
    folder only, D-F12) and each leg `MMDD_<place>`. ⛔ FAILS on c7b761e
    (no --country, one --where)."""
    import photo_index
    import index_group_cases as g
    with tempfile.TemporaryDirectory() as tmp, g.ix.no_env():
        wd, pack, idx, batches = group_index(tmp)
        c = photo_index.trip_candidates(idx, abroad(batches), pack)[0]
        args = ["group", "make-trip", wd, *c["folders"]]
        for w in c["where"]:
            args += ["--where", w]
        args += ["--country", c["country"], "--reason", "fix plan R5 ok"]
        code, _o, err = g.run(*args)
        if code:
            return False, err[-300:]
        g.render(wd)
        f = g.folders(tmp)
        trip = next(fo for fo in f.values() if fo["kind"] == "trip")
        legs = sorted(fo["rendered"] for fo in f.values() if fo.get("parent") == trip["id"])
    return (trip["rendered"] == c["to"] and "1025_Ashford" in legs
            and not any("Countryland" in l for l in legs)), \
        f"{trip['rendered']} vs {c['to']} legs={legs}"


@case
def no_trip_is_proposed_in_an_expat_period_or_without_a_country_test():
    """GUARD (Q2). A home outside the owner's country, valid on those days,
    is an expat period: the engine cannot tell the expat country from a
    third one, so nothing is proposed. Batches with no day type (a cut made
    before P1) propose nothing either; a single day abroad is no trip."""
    import photo_index
    from index_group_cases import ix
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        _wd, pack, idx, batches = group_index(tmp)
        pack.profile = dict(pack.profile, country="TW", home_locations=[
            {"id": "home-01", "lat": 24.0, "lon": 121.0},
            {"id": "home-02", "lat": 50.0, "lon": 10.0, "valid_from": "2024-01",
             "valid_until": "2025-06"}])
        expat = photo_index.trip_candidates(idx, abroad(batches), pack)
        pack.profile["home_locations"][1].update(valid_from="2019-01", valid_until="2020-06")
        before = photo_index.trip_candidates(idx, abroad(batches), pack)
        old = photo_index.trip_candidates(idx, batches, pack)
        one = photo_index.trip_candidates(idx, abroad(batches, upto=1), pack)
    return (expat == [] and len(before) == 1 and old == [] and one == []), \
        f"expat={expat} before={len(before)} old={old} one={one}"


@case
def with_no_country_word_the_trip_takes_its_places_only():
    """GUARD (Q3). No country word on the batches: the proposal is named by
    its places alone, never with an empty slot."""
    import photo_index
    from index_group_cases import ix
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        _wd, pack, idx, batches = group_index(tmp)
        got = photo_index.trip_candidates(idx, abroad(batches, word=None), pack)
    return (len(got) == 1 and got[0]["to"] == "20241025-1031_Dunmore+Ashford"
            and got[0]["country"] is None), f"{got}"


@case
def a_batch_abroad_carries_its_day_type_and_the_replys_country():
    """⭐ REPRODUCTION (Q3: the country word from the zoom-10 reply, stored on
    the batch). A day abroad for a Taiwan owner is typed OVERSEAS on its
    batch and takes the country the map reply named, in the owner's
    language; ⛔ no request comes within PLACE_SUPPRESS_KM of the home.
    ⛔ FAILS on c7b761e (no day_type, no country_word)."""
    import landmark_cases as lc
    import photo_cluster as pc
    from index_group_cases import ix
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        days = {"2025-05-01": lc.DAYS["2025-05-01"], "2025-05-02": lc.DAYS["2025-05-02"]}
        wd = lc.dump(tmp, days=days, cache={})
        prof_path = Path(tmp) / "photo-memory" / ix.OWNER / "photo-profile.json"
        prof = json.loads(prof_path.read_text())
        prof["country"] = "TW"
        prof["home_locations"] = [{"id": "home-01", "lat": 24.0, "lon": 121.0}]
        prof_path.write_text(json.dumps(prof))
        log = Path(tmp) / "net.log"
        proc = lc.cluster(wd, log, answer="stub")
        batches = (json.loads((wd / "batches.json").read_text())["batches"]
                   if proc.returncode == 0 else [])
        near = [r for r in lc.requests(log)
                for lat, lon, _a, _b in lc.coords_in((r["url"] or "") + " " + (r["data"] or ""))
                if pc.haversine_km((24.0, 121.0), (lat, lon)) <= pc.PLACE_SUPPRESS_KM]
    return (batches and all(b.get("day_type") == "OVERSEAS" for b in batches)
            and all(b.get("country_word") == "Stubland" for b in batches)
            and not near), f"rc={proc.returncode} {[(b.get('day_type'), b.get('country_word')) for b in batches]} {proc.stderr[-200:]!r}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failures = []
    for fn in CASES:
        try:
            ok, detail = fn()
        except (Exception, SystemExit) as exc:                  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  {fn.__name__.replace('_', ' ')}"
                  + ("" if ok else f"   {detail}"))
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} layout cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
