#!/usr/bin/env python3
"""Unit cases for photo_cluster.py's home anchor — the R2-F3 defect class.

The defect these exist to keep out: the anchor used to be re-derived from the
work dir as the modal Taiwan day-centroid cell, so a folder holding ONE trip
had exactly one cell, anchored on the trip itself, sat 0 km from its own
anchor, and filed the whole trip as everyday home range. Measured on eight
real trip folders, all eight wrong. The anchor now comes from the owner pack.

Every case runs the real script over a synthetic dump, offline (--no-geocode),
on invented coordinates that belong to nobody. `case_no_pack_still_self_anchors`
is deliberately an assertion that the OLD behaviour survives with no pack: it
is the fallback, and it is also the reproduction of the bug, so if the pack
path ever stops being taken this case still passes while the ones above it
fail — which is the signal we want.

Since A24 this file also holds the module's SHARED GPS PREDICATE — the one
`photo_scan`, `photo_cluster` and `photo_census` all have to agree on. It sits
here because the function does, and because the cases that matter are about
three stages giving one answer rather than about clustering.

  python3 tests/photo_cluster_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import contextlib
import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_cluster  # noqa: E402
import photo_profile  # noqa: E402

# Invented points inside the Taiwan bbox, so the run takes the TW_HOME /
# TW_AWAY path rather than the OVERSEAS one. None is anyone's address.
HOME = (23.5000, 120.5000)
NEAR = (23.5005, 120.5005)      # ~0.07 km from HOME — the GPS-drift case
OFTEN = (23.9000, 121.2000)     # ~85 km — visited often, not everyday life
FORMER = (23.4000, 120.4000)    # ~15 km — a home given up in the past
TRIP = (24.6000, 121.7000)      # ~170 km from HOME
NEARISH = (23.5180, 120.5000)   # ~2 km — far enough to be a day out, close
                                # enough that PLACE_SUPPRESS_KM withholds the
                                # name (A7)
ABROAD = (35.0000, 139.0000)    # outside the TW bbox — the OVERSEAS path
ABROAD_FAR = (35.0000, 140.0000)  # ~91 km from ABROAD — a second city on
                                # one overseas trip, past the 30 km jump
ABROAD_NEXT = (35.0100, 139.0100)  # ~1.4 km from ABROAD — the same city

AWAY_KM = 10.0                  # explicit, so no pack default can move a case

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def run(days, profile, anchor=None, away_km=AWAY_KM, route="env",
        entities=None):
    """-> (returncode, parsed batches.json or None, stdout, stderr).

    `days` is [(iso date, point)]; every day gets three own-camera frames.
    `entities` writes a `photo-entities.json` beside the profile, with the
    owner anchor file that makes that folder a PACK (W2B-3)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workdir = root / "dump"
        workdir.mkdir(parents=True)

        fields = ["SourceFile", "FileName", "FileType", "Make", "Model",
                  "GPSPosition", "DateTimeOriginal"]
        rows = []
        for day, point in days:
            # a point of None is a day whose frames carry no GPS at all
            gps = "" if point is None else f"{point[0]} {point[1]}"
            for i in range(3):
                name = f"IMG_{day.replace('-', '')}{i}.HEIC"
                rows.append({"SourceFile": f"/raw/{name}", "FileName": name,
                             "FileType": "HEIC", "Make": "Apple", "Model": "-",
                             "GPSPosition": gps,
                             "DateTimeOriginal": f"{day.replace('-', ':')} 1{i}:00:00"})
        with open(workdir / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

        env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
        profile_file = None
        if profile is not None:
            profile_file = root / "photo-profile.json"
            profile_file.write_text(json.dumps(profile))
            if entities is not None:
                (root / "photo-owner-fixture.md").write_text("fixture\n")
                (root / "photo-entities.json").write_text(json.dumps(entities))
            # ⛔ A42 / LL-PHO-132 — the pack reaches a stage by three routes
            # and a suite that exercises one proves nothing about the others.
            # Every case says which route it is on, by name.
            if route == "env":
                env["PHOTO_PROFILE"] = str(profile_file)

        cmd = [sys.executable, str(SCRIPTS / "photo_cluster.py"), str(workdir),
               "--no-geocode"]
        # R13 — `away_km=None` omits the flag, which is the ONLY way to reach
        # the unanswered path. Every case above passes it, which is exactly
        # why the silent 60 km default survived this long.
        if away_km is not None:
            cmd += ["--away-km", str(away_km)]
        if anchor:
            cmd += ["--anchor", f"{anchor[0]},{anchor[1]}"]
        if route == "flag" and profile_file is not None:
            cmd += ["--profile", str(profile_file)]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        out = None
        path = workdir / "batches.json"
        if path.exists():
            out = json.loads(path.read_text())
        return proc.returncode, out, proc.stdout, proc.stderr


def pack(*homes):
    """A profile whose home_locations are the given (point, extras) pairs."""
    return {"home_locations": [{"lat": pt[0], "lon": pt[1], **extra}
                               for pt, extra in homes]}


def labels_of(out):
    return [b["label"] for b in out["batches"]] if out else []


def types_of(out, profile=None):
    """The day type behind each batch, read back from its label.

    Read from the label rather than asserted on a field, because the label is
    what travels downstream into where.json — it is the thing R2-F3 was
    actually about.

    ⛔ `profile` is not optional decoration: the labels are LANGUAGE-RESOLVED
    (Rule 8), so reading an `en` pack's batches against the unbound legacy
    zh-TW strings types every home batch as a day out. Pass the pack the run
    used, or the case measures the language and calls it a defect."""
    msg = photo_profile.messages(profile or {})
    home = msg["cluster_label_home"]
    # R13 — a home batch may now carry a city, so an EXACT match would read
    # `everyday (around home) — X` as a day out. The prefix is the stable part.
    home_prefix = msg["cluster_label_home_place"].split("{")[0].rstrip(" \u2014-")
    overseas_prefix = msg["cluster_label_overseas"].split("{")[0]
    out_types = []
    for label in labels_of(out):
        if label == home or label.startswith(home_prefix):
            out_types.append("TW_HOME")
        elif label.startswith(overseas_prefix):
            out_types.append("OVERSEAS")
        else:
            out_types.append("TW_AWAY")
    return out_types


THREE_DAYS = ["2026-03-01", "2026-03-02", "2026-03-03"]


@case
def case_trip_only_dump_is_not_home():
    """R2-F3 itself: a folder holding one trip, and a pack that says where
    home actually is. Every day must read as a trip."""
    days = [(d, TRIP) for d in THREE_DAYS]
    rc, out, _, err = run(days, pack((HOME, {})))
    got = types_of(out)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if got != ["TW_AWAY"]:
        return f"expected one away batch, got {got} / {labels_of(out)}"
    return None


@case
def case_no_pack_still_self_anchors():
    """The fallback, stated as a case so it cannot change by accident: with no
    pack there is nothing but the folder to anchor on, so the same trip-only
    dump still reads as home. This is the bug, and it is why the pack path has
    to exist — not something to 'fix' here."""
    days = [(d, TRIP) for d in THREE_DAYS]
    rc, out, _, err = run(days, None)
    got = types_of(out)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if got != ["TW_HOME"]:
        return f"expected the legacy self-anchor, got {got}"
    return None


@case
def case_the_shipped_away_km_default_is_three_km():
    """⛔ Pinned, because it is a JUDGEMENT and judgements drift back.

    It was 60 km, and 60 km is a region rather than a home range: measured on
    a 990-file dump it typed 11 days that were 1.4-57 km out as everyday life,
    buried 227 photos inside home batches and returned 17 batches where 27
    were natural. 3 km is the knee of that curve and it is the owner's own
    rule (20260906): further than 3 km from ANY registered home is a
    different PLACE, so it gets named.

    ⛔ Equal to PLACE_SUPPRESS_KM by coincidence, NOT by wiring. One is a
    privacy ring and one is everyday range; a future change to either must
    not be assumed to apply to the other."""
    got = photo_cluster.PACK_DEFAULTS["away_km"][1]
    if got != 3.0:
        return f"the shipped away_km default is {got}, expected 3.0"
    if photo_cluster.PACK_DEFAULTS["away_km"][0] != "away_km":
        return "the pack key moved"
    return None


@case
def case_an_unanswered_away_km_is_flagged_and_warned():
    """⭐ REPRODUCTION (R13). The 60 km fallback is defensible; being unable to
    tell that it was used is not.

    Measured on a real 990-file dump whose pack carried no `away_km`: 11 days
    that were 1.4-57 km from home were typed as everyday-at-home, 227 photos
    were buried in home batches, and 27 natural batches came out as 17. The
    run exited 0 and said nothing, so the number nobody chose was
    indistinguishable from a number somebody did.

    ⛔ Asserted on the FLAG and the artifact field, not only on stderr: a
    warning scrolls past, and the next stage cannot read it."""
    home = (25.0, 121.5)
    days = [("2029-03-01", home), ("2029-03-02", (25.35, 121.5))]   # ~39 km out
    rc, out, _, err = run(days, pack((home, {})), away_km=None)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if out.get("away_km_answered") is not False:
        return "the artifact does not record that away_km was unanswered"
    if not all("away_km_not_set" in b["flags"] for b in out["batches"]):
        return f"batches are not flagged: {[b['flags'] for b in out['batches']]}"
    if "away_km" not in err:
        return f"nothing was said on stderr: {err.strip()[:200]!r}"
    return None


# ---- the three layers of `away_km`. Measured on a real dump, U3-32 ----
# The pack template shipped 60 while the code default was 3, so R13's number
# never reached a single new owner: one delivered folder held 11 days and
# three places, two of them 16 km and 51 km from home, and `batches.json`
# said `away_km_answered: true` about a run whose owner had answered nothing.
# ⛔ The authority for what cut a batch is `batches.json`, never the pack and
# never the transcript — every case here reads the artifact.

TEMPLATE_PROFILE = (Path(__file__).resolve().parent.parent / "templates" /
                    "photo-memory" / "_template" / "photo-profile.json")

# 23.5 N, +0.146 deg and +0.459 deg of latitude: the two distances U3-32
# measured, 16 km and 51 km, both inside the dead band between 3 and 60.
DEAD_BAND_16 = (23.6460, 120.5000)
DEAD_BAND_51 = (23.9590, 120.5000)


def template_pack(*homes):
    """The pack a new owner really gets: the SHIPPED template, with homes.

    ⛔ Not a hand-written dict. A dict states what this file believes the
    template holds, and the defect was that the template held something else
    — the fixture has to be the artifact, or it cannot see the bug."""
    profile = json.loads(TEMPLATE_PROFILE.read_text())
    profile.update(pack(*homes))
    return profile


@case
def case_a_template_made_pack_cuts_at_three_km_env_route():
    """⭐ REPRODUCTION, layer 1 (template) — on the $PHOTO_PROFILE route.

    A pack made from the shipped template, no --away-km, two days out in the
    dead band. Before the fix the template's 60 beat the code's 3 (a pack
    value always does) and both away days came back TW_HOME: 16 km and 51 km
    from the front door, filed as everyday life. That is U3-32's folder."""
    profile = template_pack((HOME, {}))
    days = [("2029-04-01", HOME), ("2029-04-02", DEAD_BAND_16),
            ("2029-04-10", DEAD_BAND_51)]
    rc, out, _, err = run(days, profile, away_km=None)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    got = types_of(out, profile)
    if got.count("TW_AWAY") != 2 or got.count("TW_HOME") != 1:
        return (f"a template-made pack typed the dump as {got} — expected one "
                f"home batch and the 16 km and 51 km days AWAY. The template "
                f"is beating the code default again.")
    return None


@case
def case_a_template_made_pack_is_not_an_answered_away_km_collection_route():
    """⭐ REPRODUCTION, layer 3 (the answered flag) — on the collection.json
    route, which is how every real workdir binds its pack.

    `away_km_answered` was read off the KEY'S PRESENCE, and the template
    writes the key, so it was true for everybody. Measured live in UAT01-3:
    `"away_km_answered": true` on a run where the owner's answer never
    reached this stage. Presence is not evidence when the shipper supplies
    it — so a pack still holding the shipped value counts as unanswered."""
    days = [("2029-04-01", HOME), ("2029-04-02", DEAD_BAND_51)]
    rc, out, _, err = run_bound(days, template_pack((HOME, {})))
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if out.get("away_km_answered") is not False:
        return ("a pack nobody has answered reports away_km_answered "
                f"{out.get('away_km_answered')!r} — the flag is stuck on true")
    if not all("away_km_not_set" in b["flags"] for b in out["batches"]):
        return f"batches are not flagged: {[b['flags'] for b in out['batches']]}"
    if "away_km" not in err:
        return f"nothing was said on stderr: {err.strip()[:200]!r}"
    return None


@case
def case_the_owner_can_answer_the_shipped_value_flag_route():
    """GUARD, on the --profile route. The cost of reading "the pack still
    holds what we shipped" as unanswered is that an owner who genuinely wants
    3 km could be warned forever, so there has to be a way to say so — and
    `away_km_answered: true` beside the value is it.

    ⛔ Not a reproduction: it defends the mechanism this card added, and it
    passes on the unfixed code too, where the flag was true regardless."""
    profile = template_pack((HOME, {}))
    profile["cluster_defaults"]["away_km"] = 3
    profile["cluster_defaults"]["away_km_answered"] = True
    days = [("2029-04-01", HOME), ("2029-04-02", DEAD_BAND_51)]
    rc, out, _, err = run(days, profile, away_km=None, route="flag")
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if out.get("away_km_answered") is not True:
        return "an owner who stated 3 km is still reported as unanswered"
    if any("away_km_not_set" in b["flags"] for b in out["batches"]):
        return "an owner who stated 3 km is still flagged"
    return None


@case
def case_a_legacy_pack_that_still_holds_sixty_counts_as_answered():
    """GUARD. 60 was somebody's decision once, and a pack carrying it is not
    a pack nobody touched — so it must NOT collect the unanswered warning,
    however wrong the number is. Nobody edits a value to what it already was,
    which is the whole reason "differs from the shipped default" can stand in
    for provenance."""
    profile = template_pack((HOME, {}))
    profile["cluster_defaults"]["away_km"] = 60
    days = [("2029-04-01", HOME), ("2029-04-02", DEAD_BAND_51)]
    rc, out, _, err = run(days, profile, away_km=None)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if out.get("away_km_answered") is not True:
        return "a pack holding a chosen 60 km is reported as unanswered"
    if types_of(out, profile) != ["TW_HOME"]:
        return f"60 km did not reach the clustering: {types_of(out, profile)}"
    return None


@case
def case_the_template_and_the_code_default_are_one_fact():
    """⭐ REPRODUCTION, and the guard the CLAUDE.md trap asks for: *a default
    in code and a default in a pack are ONE fact and must move together*.

    The template shipped 60 against the code's 3 for two days and nothing
    said so. This reads both files and refuses the drift, in either
    direction."""
    shipped = json.loads(TEMPLATE_PROFILE.read_text())["cluster_defaults"]
    if shipped.get("away_km") != photo_cluster.AWAY_KM_DEFAULT:
        return (f"the template ships away_km {shipped.get('away_km')!r} and "
                f"the code defaults to {photo_cluster.AWAY_KM_DEFAULT!r} — a "
                f"pack value beats the code, so the code's is unreachable")
    if shipped.get("away_km_answered") is not False:
        return ("the template must ship away_km_answered: false — it writes "
                "the value, so nothing else can tell a shipped range from a "
                "chosen one")
    return None


@case
def case_an_answered_away_km_is_not_flagged():
    """The other side, so the flag means something. A pack that states the
    value, and a run that passes it, both count as answered."""
    home = (25.0, 121.5)
    days = [("2029-03-01", home), ("2029-03-02", (25.35, 121.5))]
    rc, out, _, err = run(days, pack((home, {})), away_km=5)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if any("away_km_not_set" in b["flags"] for b in out["batches"]):
        return "an explicitly-passed away_km was still flagged as unanswered"
    prof = pack((home, {}))
    prof["cluster_defaults"] = {"away_km": 0.5}
    rc, out, _, err = run(days, prof, away_km=None)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if any("away_km_not_set" in b["flags"] for b in out["batches"]):
        return "a pack-supplied away_km was still flagged as unanswered"
    return None


@case
def case_a_home_batch_never_prints_a_coordinate_with_no_pack():
    """⭐ R13's own guard, and it exists because the first cut of R13 broke it.

    Removing the `typ != "TW_HOME"` gate above the place block is the whole
    point of R13 — but the raw-coordinate fallback lives INSIDE that block,
    protected only by a suppression test against `all_homes`. With no pack
    `all_homes` is EMPTY, so that test passes everywhere and the fallback
    happily prints the auto-detected anchor: the owner's doorstep, to two
    decimal places, in a batch label.

    ⛔ The plausible wrong fix is 'delete the TW_HOME gate' full stop. This
    case fails against exactly that, which is why it is written against the
    label text rather than against the place field."""
    days = [(d, TRIP) for d in THREE_DAYS]
    rc, out, _, err = run(days, None)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    for label in labels_of(out):
        if re.search(r"-?\d+\.\d+\s*,\s*-?\d+\.\d+", label):
            return f"a home batch printed a coordinate: {label!r}"
    return None


@case
def case_drift_around_home_stays_home():
    """A day whose points sit a few dozen metres off home is home, whatever
    away_km is tightened to. Guards the tight-radius setting an owner may
    choose against calling ordinary days trips."""
    days = [(THREE_DAYS[0], HOME), (THREE_DAYS[1], NEAR), (THREE_DAYS[2], HOME)]
    rc, out, _, err = run(days, pack((HOME, {})), away_km=0.3)
    got = types_of(out)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if got != ["TW_HOME"]:
        return f"expected one home batch, got {got}"
    return None


@case
def case_home_range_false_reads_as_a_trip():
    """A home the owner marks `home_range: false` — somewhere they go often,
    and may own, but do not live — must not make a day everyday life."""
    days = [(d, OFTEN) for d in THREE_DAYS]
    rc, out, _, err = run(days, pack((HOME, {}), (OFTEN, {"home_range": False})))
    got = types_of(out)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if got != ["TW_AWAY"]:
        return f"expected away, got {got}"
    return None


@case
def case_home_range_absent_means_true():
    """A pack written before the key existed keeps every home it had."""
    days = [(d, OFTEN) for d in THREE_DAYS]
    rc, out, _, err = run(days, pack((HOME, {}), (OFTEN, {})))
    got = types_of(out)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if got != ["TW_HOME"]:
        return f"expected home, got {got}"
    return None


@case
def case_expired_home_does_not_anchor_a_later_day():
    """A home given up in 2021 must not file a 2026 day as everyday life."""
    days = [(d, FORMER) for d in THREE_DAYS]
    rc, out, _, err = run(days, pack((HOME, {}),
                                     (FORMER, {"valid_until": "2021-10"})))
    got = types_of(out)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if got != ["TW_AWAY"]:
        return f"expected away, got {got}"
    return None


@case
def case_expired_home_still_anchors_its_own_era():
    """...and the positive control: the same home, inside its own window, is
    still home. Without this the case above would pass on a pack that had
    simply stopped reading validity windows."""
    days = [("2021-09-01", FORMER), ("2021-09-02", FORMER)]
    rc, out, _, err = run(days, pack((HOME, {}),
                                     (FORMER, {"valid_until": "2021-10"})))
    got = types_of(out)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if got != ["TW_HOME"]:
        return f"expected home, got {got}"
    return None


@case
def case_anchor_flag_adds_to_the_pack():
    """--anchor ADDS a point; it does not replace the pack's homes. Both the
    pack home and the flagged point have to read as home in one run."""
    days = [("2026-03-01", HOME), ("2026-03-02", TRIP), ("2026-03-03", HOME)]
    rc, out, _, err = run(days, pack((HOME, {})), anchor=TRIP)
    got = types_of(out)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if got != ["TW_HOME"]:
        return f"expected every day home, got {got} / {labels_of(out)}"
    return None


@case
def case_a_real_trip_still_separates_from_home():
    """The positive control for the whole file: with the pack anchor in play,
    home days and trip days still land in DIFFERENT batches. A fix that filed
    everything as one type would pass several cases above."""
    days = [("2026-03-01", HOME), ("2026-03-02", TRIP), ("2026-03-03", HOME)]
    rc, out, _, err = run(days, pack((HOME, {})))
    got = types_of(out)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if got != ["TW_HOME", "TW_AWAY", "TW_HOME"]:
        return f"expected home/away/home, got {got}"
    return None


@case
def case_home_range_false_never_reaches_the_privacy_rule():
    """⛔ The invariant that makes `home_range` safe to add at all.

    `home_range: false` narrows the batch LABEL. It must never narrow name
    suppression: a place the owner marked is still their address, and
    photo_where has to go on refusing to name it. Read here at the seam
    rather than through a second dump, because the seam is the whole risk —
    one caller passing the flag through is all it would take."""
    profile = pack((HOME, {}), (OFTEN, {"home_range": False}))
    privacy = photo_profile.home_points(profile)
    labelling = photo_profile.home_points(profile, home_range_only=True)
    if len(privacy) != 2:
        return f"privacy must see BOTH homes, saw {len(privacy)}"
    if len(labelling) != 1:
        return f"labelling must see one home, saw {len(labelling)}"
    import photo_where  # noqa: E402  — imported here to keep the seam explicit
    if photo_where.home_points is not photo_profile.home_points:
        return "photo_where no longer shares the pack reader"
    if not photo_where.is_home(OFTEN, "2026-03-01", privacy, 1.0):
        return "a home_range:false home stopped suppressing its own name"
    return None


@case
def case_a_near_home_day_never_prints_the_home_coordinate():
    """⛔ Rule 3 at the seam a tight away_km opened.

    With a small away_km a day a few hundred metres from the door is an
    away-day, and an away-day gets a place. When the geocoder returns nothing
    the place used to fall back to the raw coordinate — which is the owner's
    address to about a kilometre, printed into batches.json and copied on into
    where.json. The label must carry no coordinate at all here."""
    days = [(d, NEAR) for d in THREE_DAYS]
    rc, out, _, err = run(days, pack((HOME, {})), away_km=0.01)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    got = types_of(out)
    if got != ["TW_AWAY"]:
        return f"fixture no longer exercises the fallback: got {got}"
    for label in labels_of(out):
        for coord in (f"{HOME[0]:.2f}", f"{HOME[1]:.2f}",
                      f"{NEAR[0]:.2f}", f"{NEAR[1]:.2f}"):
            if coord in label:
                return f"home coordinate {coord} leaked into label {label!r}"
    return None


@case
def case_home_range_false_still_hides_its_coordinate():
    """The same guard, on the home the `home_range` flag exists for. A place
    can be 'not my everyday life' and still be an address — so the anchor set
    is filtered and the never-print set is not."""
    days = [(d, OFTEN) for d in THREE_DAYS]
    rc, out, _, err = run(days, pack((HOME, {}), (OFTEN, {"home_range": False})))
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if types_of(out) != ["TW_AWAY"]:
        return "fixture no longer produces an away batch"
    for label in labels_of(out):
        for coord in (f"{OFTEN[0]:.2f}", f"{OFTEN[1]:.2f}"):
            if coord in label:
                return f"coordinate {coord} leaked into label {label!r}"
    return None


@case
def case_a_real_trip_still_gets_its_coordinate_fallback():
    """The positive control: away from every home, with no geocoder, the
    coordinate fallback is still how a batch says where it was. A guard that
    suppressed everywhere would pass both cases above."""
    days = [(d, TRIP) for d in THREE_DAYS]
    rc, out, _, err = run(days, pack((HOME, {})))
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    # FIX8 F8-8: the fallback lives in batches.json's `place`, never in the
    # label, which is printed on screen.
    places = [bt.get("place") or "" for bt in out["batches"]]
    if not any(f"{TRIP[0]:.2f}" in place for place in places):
        return f"expected the coordinate fallback in place, got {places}"
    if any(f"{TRIP[0]:.2f}" in label for label in labels_of(out)):
        return f"a label carries the coordinate: {labels_of(out)}"
    return None


# ---------------------------------------------------------------------------
# A24 — one GPS predicate, shared. `photo_scan` counted any non-empty
# GPSPosition, clustering rejected null island, and `photo_census` had a third
# copy. The three disagreed silently, and the one that rounded UP was
# `gps_coverage_pct` — the number a human reads to decide a dump is
# well-tagged.
# ---------------------------------------------------------------------------

NULL_ISLAND_ROW = {"GPSPosition": "0 0"}
REAL_ROW = {"GPSPosition": "23.5 120.5"}


@case
def case_null_island_is_not_a_location():
    """0,0 is the Atlantic off Ghana. A device writing it is saying "no fix"
    in the one way that still parses as a coordinate."""
    for value in ("0 0", "0.0 0.0", "0,0", "0.00000 0.00000"):
        if photo_cluster.gps_point(value) is not None:
            return f"{value!r} was accepted as a location"
    return None


@case
def case_a_real_coordinate_still_parses_in_both_forms():
    """The tolerant parse came from photo_census's copy and clustering's did
    not have it. Merging the two must not lose a real coordinate — and must
    not start accepting half of one."""
    if photo_cluster.gps_point("23.5 120.5") != (23.5, 120.5):
        return "the space-separated form stopped parsing"
    if photo_cluster.gps_point("23.5, 120.5") != (23.5, 120.5):
        return "the comma-separated form is still rejected"
    for bad in ("23.5", "x y", "", "-", None):
        if photo_cluster.gps_point(bad) is not None:
            return f"{bad!r} was accepted"
    return None


@case
def case_the_row_form_and_the_value_form_are_the_same_predicate():
    """`parse_gps(row)` is a wrapper, not a second opinion — the shape the bug
    took the first time."""
    for row in (NULL_ISLAND_ROW, REAL_ROW, {"GPSPosition": "-"}, {}):
        value = row.get("GPSPosition", "-")
        if photo_cluster.parse_gps(row) != photo_cluster.gps_point(value):
            return f"row and value forms disagree on {row}"
    return None


@case
def case_every_stage_imports_the_one_predicate():
    """The card's actual fix: not three corrected copies, ONE function. This
    is a source check on purpose — an equality check between three functions
    would pass again the moment somebody re-derived a fourth that happened to
    agree today."""
    import photo_census
    import photo_scan
    if photo_census.gps_point is not photo_cluster.gps_point:
        return "photo_census does not use the shared predicate"
    if photo_scan.parse_gps is not photo_cluster.parse_gps:
        return "photo_scan does not use the shared predicate"
    # and nobody has quietly written a fourth
    others = []
    for name in ("photo_scan.py", "photo_census.py", "photo_sample.py",
                 "photo_plan.py", "photo_where.py"):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        if re.search(r"^def (gps_point|parse_gps)\b", text, re.M):
            others.append(name)
    return f"a second definition lives in {others}" if others else None


@case
def case_the_scan_summary_counts_what_clustering_will_use():
    """The visible symptom, through photo_scan's REAL counting loop.

    That loop lives inside `main()` and needs exiftool, so exiftool is
    replaced by a function returning a CSV this file wrote — the rows are
    synthetic, the code under test is not. Asserting the same expression twice
    would have proved nothing, which is what the first draft of this case
    did.

    4 of 5 rows carry a non-empty GPSPosition and only 2 are locations, so
    before A24 this dump reported 80% and clustering used 40%."""
    csv_text = (
        "SourceFile,DateTimeOriginal,GPSPosition,FileType\n"
        "/raw/a.jpg,2024:01:01 10:00:00,23.5 120.5,JPEG\n"
        "/raw/b.jpg,2024:01:01 11:00:00,23.6 120.6,JPEG\n"
        "/raw/c.mp4,2024:01:01 12:00:00,0 0,MP4\n"
        "/raw/d.mp4,2024:01:01 13:00:00,0 0,MP4\n"
        "/raw/e.jpg,2024:01:01 14:00:00,-,JPEG\n")
    import photo_scan
    real, argv = photo_scan.run_exiftool, sys.argv
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "dump"
        source.mkdir()
        workdir = Path(tmp) / "work"
        try:
            photo_scan.run_exiftool = lambda source, recursive: (csv_text, "")
            sys.argv = ["photo_scan.py", str(source), "--workdir", str(workdir)]
            with contextlib.redirect_stdout(io.StringIO()):
                photo_scan.main()
        finally:
            photo_scan.run_exiftool, sys.argv = real, argv
        summary = json.loads((workdir / "scan-summary.json").read_text())
        rows = list(csv.DictReader(
            open(workdir / "manifest.csv", newline="", encoding="utf-8")))

    usable = sum(1 for r in rows if photo_cluster.parse_gps(r) is not None)
    if summary["with_gps"] != usable:
        return (f"scan-summary says {summary['with_gps']} rows have GPS, "
                f"clustering can use {usable}")
    if usable != 2:
        return f"the fixture changed: {usable} usable rows, expected 2"
    # the fixture must still contain the disagreement, or the case is asleep
    naive = sum(1 for r in rows if r.get("GPSPosition", "-") not in ("-", ""))
    if naive == usable:
        return ("no null-island row survived into the manifest — this case "
                "can no longer tell the two predicates apart")
    if summary.get("gps_coverage_pct") not in (40.0, 40):
        return f"gps_coverage_pct is {summary.get('gps_coverage_pct')}, expected 40"
    return None


@case
def case_null_island_can_never_become_a_home_candidate():
    """The consequence that is not a rounding error. `photo_census`'s copy
    fed `home_candidates`, which accumulates days and nights per cell — so a
    dump with enough `0 0` rows across enough days could have proposed the
    Atlantic as somewhere the owner lives, in the one flow the privacy rule
    depends on."""
    import photo_census
    rows = [{"GPSPosition": "0 0",
             "DateTimeOriginal": f"2024:01:{day:02d} 22:00:00"}
            for day in range(1, 29)]
    proposals = photo_census.home_candidates(rows)
    if proposals:
        return f"null island was proposed as a home: {proposals}"
    # the same rows at a real place DO propose, or the case proves nothing
    real = [{"GPSPosition": "23.5 120.5",
             "DateTimeOriginal": f"2024:01:{day:02d} 22:00:00"}
            for day in range(1, 29)]
    if not photo_census.home_candidates(real):
        return ("the control did not propose either — this case cannot tell "
                "suppression from a threshold nobody reached")
    return None


@case
def case_a_batch_with_no_resolved_place_reads_as_a_sentence():
    """A7. A label is read by the owner, so an unresolved place has to render
    as words. It used to render Python's `None` — reproduced live in C0 on
    B14, and the shape is preserved in tests/golden/202603/input/batches.json.

    BOTH causes are exercised, because one line in photo_cluster now covers
    both and they must stay indistinguishable in the output:

      * a day out whose midpoint sits inside PLACE_SUPPRESS_KM of a home, so
        the name is WITHHELD — wording this one apart would tell a reader
        which batches were near a residence;
      * a batch that carried no usable coordinate at all (an orphan no-GPS
        day that inherited its type from a trip too far away in time to be
        merged into it).

    The phrase itself is asserted from the message table, never spelled here:
    it is an owner-language string like every other, and a case that hardcoded
    it would be asserting the engine ships one language.
    """
    msg = photo_profile.messages({})
    unresolved = msg["cluster_place_unresolved"]

    withheld = run([(d, NEARISH) for d in THREE_DAYS], pack((HOME, {})),
                   away_km=1.0)[1]
    got = labels_of(withheld)
    if got != [msg["cluster_label_domestic"].format(place=unresolved)]:
        return f"suppressed-place label is {got}"

    no_gps = run([("2026-03-01", None),
                  ("2026-05-20", ABROAD), ("2026-05-21", ABROAD)],
                 pack((HOME, {})))[1]
    orphan = [b for b in no_gps["batches"] if b["gps_files"] == 0]
    if len(orphan) != 1:
        return (f"expected one GPS-less batch, got {len(orphan)} — the fixture "
                f"no longer reproduces the cause")
    if orphan[0]["label"] != msg["cluster_label_overseas"].format(
            place=unresolved):
        return f"no-GPS label is {orphan[0]['label']!r}"

    # and the two are the same phrase, which is the privacy half of the card
    if got[0].split("—")[-1] != orphan[0]["label"].split("—")[-1]:
        return "the two causes render differently"
    return None


def run_bound(days, profile, extra_args=(), entities=None):
    """Like run(), but the pack is bound the way a real collection is — a
    `collection.json` beside the work dir — with **$PHOTO_PROFILE unset**.

    This exists because every other case in this file binds through the env
    var, which is the one path that was never broken. A42: `photo_cluster`
    resolved its pack BEFORE argparse knew the work dir, so `load_profile()`
    ran with no `workdir=` and a collection.json was never seen. All 24 cases
    above stayed green throughout, because none of them used this binding.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workdir = root / "dump"
        workdir.mkdir(parents=True)

        fields = ["SourceFile", "FileName", "FileType", "Make", "Model",
                  "GPSPosition", "DateTimeOriginal"]
        rows = []
        for day, point in days:
            gps = "" if point is None else f"{point[0]} {point[1]}"
            for i in range(3):
                name = f"IMG_{day.replace('-', '')}{i}.HEIC"
                rows.append({"SourceFile": f"/raw/{name}", "FileName": name,
                             "FileType": "HEIC", "Make": "Apple", "Model": "-",
                             "GPSPosition": gps,
                             "DateTimeOriginal": f"{day.replace('-', ':')} 1{i}:00:00"})
        with open(workdir / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

        memory_root = root / "memory"
        (memory_root / "someone").mkdir(parents=True)
        (memory_root / "someone" / "photo-profile.json").write_text(
            json.dumps(profile), encoding="utf-8")
        if entities is not None:
            (memory_root / "someone" / "photo-entities.json").write_text(
                json.dumps(entities), encoding="utf-8")
        (root / "collection.json").write_text(
            json.dumps({"owner": "someone", "memory_root": str(memory_root)}),
            encoding="utf-8")

        env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
        cmd = [sys.executable, str(SCRIPTS / "photo_cluster.py"), str(workdir),
               "--no-geocode", *extra_args]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        out = None
        path = workdir / "batches.json"
        if path.exists():
            out = json.loads(path.read_text())
        return proc.returncode, out, proc.stdout, proc.stderr


TRIP_ONLY = [(d, TRIP) for d in THREE_DAYS]


@case
def case_a_collection_bound_pack_reaches_a_direct_run():
    """A42: the trip-only dump again, but bound by collection.json and with
    NO --away-km passed, so the run has to take `cluster_defaults.away_km`
    off the pack. Before the fix this returned TW_HOME: no pack meant
    away_km 60 and an anchor auto-derived from the trip itself."""
    profile = {**pack((HOME, {})), "cluster_defaults": {"away_km": 0.3}}
    rc, out, _, err = run_bound(TRIP_ONLY, profile)
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    got = types_of(out)
    if got != ["TW_AWAY"]:
        return (f"a pack bound by collection.json did not reach the run: "
                f"{got} — expected ['TW_AWAY']")
    return None


@case
def case_an_explicit_flag_still_beats_the_pack():
    """The other half of A42's fix: pack values fill in only what the owner
    did NOT type. A default baked into add_argument() is indistinguishable
    from a value the owner passed, which is why they are None until the pack
    is loaded — but an explicit flag must still win."""
    profile = {**pack((HOME, {})), "cluster_defaults": {"away_km": 0.3}}
    rc, out, _, err = run_bound(TRIP_ONLY, profile, extra_args=("--away-km", "500"))
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    got = types_of(out)
    if got != ["TW_HOME"]:
        return (f"--away-km 500 was overridden by the pack's 0.3: {got} — "
                f"expected ['TW_HOME'], the trip inside a 500 km home range")
    return None


# ---- R9 / R10: a batch is named by every day, and never by a residence ----

class StubGeocoder:
    """Answers from a dict and COUNTS its calls, offline. The call count is
    half the point: R10's refusal has to happen BEFORE the lookup, so a test
    that only inspects the returned names cannot tell a suppressed day from a
    day the geocoder happened to answer nothing for."""

    def __init__(self, answers, admin=None):
        self.answers = answers
        # R13 — what an ADMINISTRATIVE lookup would answer, kept apart from
        # `answers` on purpose. A near-home day may be named, but only from
        # Nominatim's structured address dict; if the two lookups shared one
        # table a test could not tell which one the code actually called.
        self.admin = admin or {}
        self.asked = []
        self.asked_admin = []

    def city(self, pt):
        self.asked.append(pt)
        return self.answers.get((round(pt[0], 4), round(pt[1], 4)))

    def city_admin(self, pt):
        self.asked_admin.append(pt)
        return self.admin.get((round(pt[0], 4), round(pt[1], 4)))


def five_day_trip():
    """A batch that moves every day. Invented coordinates, invented names —
    Rule 7 keeps a real itinerary out of the repo."""
    from datetime import date
    pts = [(20.0 + i, 100.0 + i) for i in range(5)]
    names = ["Place-A", "Place-B", "Place-C", "Place-D", "Place-E"]
    part = [date(2029, 3, 1 + i) for i in range(5)]
    day_files = {d: {"centroid": pts[i]} for i, d in enumerate(part)}
    answers = {(round(a, 4), round(b, 4)): n for (a, b), n in zip(pts, names)}
    return part, day_files, StubGeocoder(answers), names, pts


@case
def case_a_moving_batch_is_named_by_every_day_not_the_median_one():
    """⭐ REPRODUCTION (R9). The old line was
    `mid = centroids[len(centroids) // 2]; place = geocoder.city(mid)` — ONE
    lookup for the whole batch, so a six-day trip took the name of whichever
    day sat in the middle. Measured on a real six-day trip, per-day geocoding
    returned five different municipalities in about six seconds using the same
    Geocoder and no other change."""
    part, day_files, geo, names, _pts = five_day_trip()
    got = photo_cluster.batch_places(part, day_files, geo, [], limit=8)
    if got != names:
        return f"expected every day in travel order, got {got}"
    if len(geo.asked) != 5:
        return f"expected one lookup per day, got {len(geo.asked)}"
    return None


@case
def case_repeated_places_collapse_and_the_order_is_travel_order():
    """A guard. Deduped FIRST-SEEN, so `where1+where2` reads as an itinerary
    rather than a set — and a batch that stays put still names one place."""
    part, day_files, geo, _names, pts = five_day_trip()
    for d in part:                       # every day at the same place
        day_files[d]["centroid"] = pts[0]
    got = photo_cluster.batch_places(part, day_files, geo, [])
    if got != ["Place-A"]:
        return f"a stationary batch named {got}"
    if len(geo.asked) != 5:
        return "the dedupe must not skip the lookup — the cache does that"
    return None


@case
def case_the_place_limit_is_a_parameter_and_stops_early():
    """`{n}` — a trip across five towns is readable, twenty is not a label.
    Passed explicitly: a case that relies on the shipped default turns a
    parameter back into a constant."""
    part, day_files, geo, names, _pts = five_day_trip()
    got = photo_cluster.batch_places(part, day_files, geo, [], limit=2)
    if got != names[:2]:
        return f"limit ignored: {got}"
    return None


@case
def case_a_day_at_home_is_named_only_from_the_administrative_lookup():
    """⭐ R13 AMENDS R10, on the owner's decision (20260906).

    R10 skipped a near-home day BEFORE the geocoder, because `Geocoder.city()`
    performs no suppression of its own and zoom 10 only USUALLY answers with a
    town — luck, not a control. That refusal was correct about the mechanism
    and too wide in its effect: it left 10 of 17 batches with no `[where]` at
    all on a real dump, 669 of 990 files, and Operational Rule 3 has always
    ALLOWED a residence's CITY (it is the coordinates, and a POI-level name,
    that may never surface).

    So the property under test changes shape rather than being dropped: a
    near-home day must still never reach the free-form `city()` lookup, and
    must be named — if it can be named at all — from the structured address
    dict, which cannot return a road or a POI whatever the zoom does.

    ⛔ Asserted on BOTH call lists. Reading the names alone cannot tell a day
    that took the safe path from one that took the unsafe path and happened to
    get a town back."""
    part, day_files, geo, names, pts = five_day_trip()
    geo.admin = {(round(pts[2][0], 4), round(pts[2][1], 4)): "Home-City"}
    home = [(pts[2][0], pts[2][1], None, None)]      # the middle day is home
    got = photo_cluster.batch_places(part, day_files, geo, home, limit=8)
    if pts[2] in geo.asked:
        return ("the home day reached the free-form city() lookup — it must "
                "take the administrative one")
    if pts[2] not in geo.asked_admin:
        return "the home day was not offered to the administrative lookup at all"
    if names[2] in got:
        return f"the free-form name of a residence reached the label: {got}"
    if got != [names[0], names[1], "Home-City", names[3], names[4]]:
        return f"the home day was not named at city level in travel order: {got}"
    return None


@case
def case_a_home_day_with_no_administrative_answer_is_still_withheld():
    """The other half of R13, and the one that keeps it honest. Naming a
    near-home day is permitted, never forced: when the structured address dict
    has nothing at city level the day drops out exactly as it did under R10.
    ⛔ There is no fallback to `city()` here — that would be the R10 hole
    reopened through the back door."""
    part, day_files, geo, names, pts = five_day_trip()
    home = [(pts[2][0], pts[2][1], None, None)]
    got = photo_cluster.batch_places(part, day_files, geo, home, limit=8)   # geo.admin empty
    if pts[2] in geo.asked:
        return "a home day fell back to the free-form lookup"
    if got != [names[0], names[1], names[3], names[4]]:
        return f"an unnameable home day did not drop out: {got}"
    return None


@case
def case_the_admin_lookup_coarsens_the_coordinate_before_sending_it():
    """⛔ R13's cost, paid down. R10 never geocoded a residence, so its exact
    position never left the machine; naming its city means asking someone.
    The request is rounded to 2 dp (~1.1 km) — coarser than a front door,
    finer than any municipality boundary needs, and already the precision of
    the cache key, so nothing is lost.

    Asserted by capturing the URL the class would build, with the network
    never reached."""
    import photo_cluster as pc
    sent = {}

    class Probe(pc.Geocoder):
        def __init__(self):
            super().__init__(Path(os.devnull + "-nope"), enabled=True)

    geo = Probe()
    # Invented, and belongs to nobody (Rule 7) — the point is the rounding.
    fine = (20.1234567891234, 100.9876543219876)
    import urllib.request as ur
    real = ur.urlopen

    def fake(req, *a, **k):
        sent["url"] = req.full_url
        raise RuntimeError("network refused by the test")

    ur.urlopen = fake
    try:
        geo.city_admin(fine)
    finally:
        ur.urlopen = real
    if "url" not in sent:
        return "the lookup never built a request"
    if f"{fine[0]}" in sent["url"] or f"{fine[1]}" in sent["url"]:
        return f"the full-precision coordinate was sent: {sent['url']}"
    if "lat=20.12" not in sent["url"] or "lon=100.99" not in sent["url"]:
        return f"not rounded to 2 dp: {sent['url']}"
    return None


@case
def case_an_address_from_the_administrative_lookup_is_still_refused():
    """A43 does not get to be skipped just because the source changed. Belt
    and braces: the address dict should never answer with a lane number, and
    if it ever does the cost is a residence in a folder name."""
    from datetime import date
    pt = (20.0, 100.0)
    part = [date(2029, 3, 1)]
    day_files = {part[0]: {"centroid": pt}}
    # i18n-guard:allow-begin — an address is the thing under test
    geo = StubGeocoder({}, admin={(20.0, 100.0): "\u9e97\u5712\u4e00\u88579\u5df7"})
    # i18n-guard:allow-end
    home = [(pt[0], pt[1], None, None)]
    got = photo_cluster.batch_places(part, day_files, geo, home)
    if got:
        return f"an address was accepted as a near-home place: {got}"
    return None


@case
def case_a_street_address_never_becomes_a_batch_place():
    """A43 reaching the batch namer too. It should never fire at zoom 10; it
    is here because the cost of being wrong is an address in a folder name,
    and one shared predicate is cheaper than two that disagree (A24 / D-07)."""
    from datetime import date
    pt = (20.0, 100.0)
    part = [date(2029, 3, 1)]
    day_files = {part[0]: {"centroid": pt}}
    # i18n-guard:allow-begin — an address is the thing under test
    geo = StubGeocoder({(20.0, 100.0): "\u9e97\u5712\u4e00\u88579\u5df7"})
    # i18n-guard:allow-end
    got = photo_cluster.batch_places(part, day_files, geo, [])
    if got:
        return f"an address was accepted as a place: {got}"
    return None


@case
def case_a_day_with_no_coordinate_is_skipped_not_fatal():
    """A guard: a batch mixes days that carry GPS with days that do not."""
    part, day_files, geo, names, _pts = five_day_trip()
    day_files[part[1]]["centroid"] = None
    got = photo_cluster.batch_places(part, day_files, geo, [], limit=8)
    if got != [names[0], names[2], names[3], names[4]]:
        return f"a coordinate-less day broke the walk: {got}"
    return None


# ---------------------------------------------------------------------------
# D-F9 — a home batch is named from the OWNER'S label, not from the map
# ---------------------------------------------------------------------------
#
# Invented words. Rule 7: an owner's real label is pack DATA and never reaches
# this repo, so these have to be readable as "the owner typed this" without
# being anybody's actual home.
OWNER_WORD = "Owner-Word"
OTHER_WORD = "Other-Word"


@case
def case_a_labelled_home_day_takes_the_owners_word_and_asks_nobody():
    """⭐ REPRODUCTION (D-F9). On R13 (cf3f50d) a near-home day was named by
    calling `Geocoder.city_admin()`, so the owner's own home came back with
    whatever municipality the map holds. Run against the unfixed code this
    case fails on BOTH counts at once — the day appears in `asked_admin`, and
    the map's word appears in the result where the owner's should be.

    ⛔ Asserted on the call lists, not on the name alone. "No geocode call at
    all" is the substance of D-F9 rather than a saving: a labelled home is a
    coordinate that never leaves the machine.
    """
    part, day_files, geo, names, pts = five_day_trip()
    geo.admin = {(round(pts[2][0], 4), round(pts[2][1], 4)): "Map-City"}
    home = [(pts[2][0], pts[2][1], None, None)]
    labelled = [(pts[2][0], pts[2][1], None, None, OWNER_WORD)]
    got = photo_cluster.batch_places(part, day_files, geo, home, limit=8,
                                     labelled_homes=labelled)
    if pts[2] in geo.asked:
        return "a home day reached the free-form city() lookup"
    if pts[2] in geo.asked_admin:
        return ("a LABELLED home day was still geocoded — D-F9 makes no call "
                "at all when the owner has named the place")
    if got != [names[0], names[1], OWNER_WORD, names[3], names[4]]:
        return f"the owner's own word did not name the day: {got}"
    return None


@case
def case_an_unlabelled_home_still_takes_the_administrative_lookup():
    """A guard, and the half of R13 D-F9 must not break. No label is the
    ordinary case for a pack written before D-F9 and for a home the owner has
    not named yet — step 2 of the order, unchanged, and step 3 (drop the day)
    still stands behind it."""
    part, day_files, geo, names, pts = five_day_trip()
    geo.admin = {(round(pts[2][0], 4), round(pts[2][1], 4)): "Map-City"}
    home = [(pts[2][0], pts[2][1], None, None)]
    labelled = [(pts[2][0], pts[2][1], None, None, None)]
    got = photo_cluster.batch_places(part, day_files, geo, home, limit=8,
                                     labelled_homes=labelled)
    if pts[2] not in geo.asked_admin:
        return "an unlabelled home day was not offered to the admin lookup"
    if got != [names[0], names[1], "Map-City", names[3], names[4]]:
        return f"an unlabelled home day lost its city: {got}"
    return None


@case
def case_the_label_comes_from_the_nearest_home_not_the_first_in_the_pack():
    """⭐ A guard against the PLAUSIBLE WRONG FIX — `next(label for ... if
    within radius)`. Pack order is the order the owner typed their homes in
    and carries no meaning, so first-within-radius names a day after whichever
    residence was typed first. Both homes here qualify; the farther one is
    listed first, and only a nearest-wins lookup can tell them apart."""
    part, day_files, geo, names, pts = five_day_trip()
    near = pts[2]
    far = (pts[2][0] + 0.02, pts[2][1])          # ~2.2 km — still inside 3 km
    home = [(far[0], far[1], None, None), (near[0], near[1], None, None)]
    labelled = [(far[0], far[1], None, None, OTHER_WORD),
                (near[0], near[1], None, None, OWNER_WORD)]
    got = photo_cluster.batch_places(part, day_files, geo, home, limit=8,
                                     labelled_homes=labelled)
    if OTHER_WORD in got:
        return f"the day was named after the farther home: {got}"
    if got[2] != OWNER_WORD:
        return f"the nearest home's label did not name the day: {got}"
    return None


@case
def case_an_unlabelled_nearest_home_does_not_reach_past_itself():
    """A guard. The nearest home having no label IS the answer: the caller
    falls to the administrative lookup rather than borrowing the name of a
    second residence the day was not spent at. A wrong name is worse than a
    city — and worse than no name."""
    part, day_files, geo, names, pts = five_day_trip()
    near = pts[2]
    far = (pts[2][0] + 0.02, pts[2][1])
    geo.admin = {(round(near[0], 4), round(near[1], 4)): "Map-City"}
    home = [(far[0], far[1], None, None), (near[0], near[1], None, None)]
    labelled = [(far[0], far[1], None, None, OTHER_WORD),
                (near[0], near[1], None, None, None)]
    got = photo_cluster.batch_places(part, day_files, geo, home, limit=8,
                                     labelled_homes=labelled)
    if OTHER_WORD in got:
        return f"a farther home's label was borrowed: {got}"
    if got[2] != "Map-City":
        return f"the admin lookup did not run for the unlabelled home: {got}"
    return None


@case
def case_a_home_outside_its_validity_window_lends_no_label():
    """A guard. A home the owner had not moved into yet must not name an older
    day — the same window `within_home_range` applies, applied by the same
    rules, so the two cannot disagree about which homes exist on a date."""
    part, day_files, geo, names, pts = five_day_trip()
    home = [(pts[2][0], pts[2][1], None, None)]          # suppresses always
    labelled = [(pts[2][0], pts[2][1], "2030", None, OWNER_WORD)]
    got = photo_cluster.batch_places(part, day_files, geo, home, limit=8,
                                     labelled_homes=labelled)
    if OWNER_WORD in got:
        return f"a home not yet moved into named a 2029 day: {got}"
    if pts[2] not in geo.asked_admin:
        return "the day should have fallen through to the admin lookup"
    return None


@case
def case_home_range_false_still_lends_its_own_label():
    """⛔ The label list is the UNFILTERED one, and this is why.

    `home_range: false` says a place is not the owner's everyday life, so a
    day there still reads as a trip. It never says the place may not be NAMED
    — D-F4 puts the word under the owner's authority and protects only the
    coordinate. Filtering the label lookup by that flag would leave the one
    home the flag exists for suppressing the map lookup and unable to supply
    the replacement word: the worst of both halves.
    """
    profile = pack((HOME, {"label": OWNER_WORD}),
                   (OFTEN, {"home_range": False, "label": OTHER_WORD}))
    labelled = photo_profile.labelled_home_points(profile)
    if len(labelled) != 2:
        return f"the label list must be unfiltered, saw {len(labelled)} of 2"
    got = photo_cluster.home_label(OFTEN, "2026-03-01", labelled,
                                   photo_cluster.PLACE_SUPPRESS_KM)
    if got != OTHER_WORD:
        return f"a home_range:false home lent no label: {got!r}"
    narrowed = photo_profile.labelled_home_points(profile, home_range_only=True)
    if len(narrowed) != 1:
        return "home_range_only must still narrow, for the callers that want it"
    return None


@case
def case_home_points_keeps_its_four_tuple_shape():
    """⛔ Three callers unpack `home_points()` as four values (photo_where.py
    :461, photo_cluster.py :517 and :522) and none of them wants a label. The
    label arrives on a SIBLING accessor, so the two callers whose job is to
    refuse to print anything never hold a printable field."""
    profile = pack((HOME, {"label": OWNER_WORD}))
    plain = photo_profile.home_points(profile)
    labelled = photo_profile.labelled_home_points(profile)
    if [len(r) for r in plain] != [4]:
        return f"home_points widened to {[len(r) for r in plain]}"
    # D-I15: the sibling now also carries the home's id (6th); home_points()
    # must still see neither.
    if [len(r) for r in labelled] != [6]:
        return f"labelled_home_points is not 6-tuples: {[len(r) for r in labelled]}"
    if labelled[0][:4] != plain[0]:
        return "the two accessors disagree about the same home"
    if labelled[0][4] != OWNER_WORD:
        return f"the label was not read: {labelled[0][4]!r}"
    return None


@case
def case_an_unusable_label_degrades_instead_of_exiting():
    """A guard, and the asymmetry is deliberate: an unreadable lat/lon is a
    hard exit because it switches the privacy rule off, while an unreadable
    label costs one map call and a city-level name. Blank, whitespace and a
    non-string all mean 'not named yet'."""
    for bad in ("", "   ", 7, None, []):
        profile = pack((HOME, {"label": bad}))
        got = photo_profile.labelled_home_points(profile)
        if got[0][4] is not None:
            return f"label {bad!r} was read as {got[0][4]!r}"
    return None


@case
def case_an_owner_label_names_a_home_batch_end_to_end_via_env():
    """⭐ REPRODUCTION, end to end, on the $PHOTO_PROFILE route.

    `--no-geocode` is the point: with the network refused, `city_admin()`
    answers nothing, so on R13 this batch's `place` is None and its label is
    the bare 'everyday' sentence. The owner's own word needs no lookup, so it
    survives a run that can reach nobody — which is also what an offline first
    run of the engine looks like."""
    days = [("2026-03-01", HOME), ("2026-03-02", HOME)]
    rc, out, _, err = run(days, pack((HOME, {"label": OWNER_WORD})),
                          route="env")
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    places = [b["place"] for b in out["batches"]]
    if places != [OWNER_WORD]:
        return f"the home batch was not named from the pack label: {places}"
    if OWNER_WORD not in out["batches"][0]["label"]:
        return f"the label sentence dropped the place: {out['batches'][0]['label']}"
    return None


@case
def case_an_owner_label_names_a_home_batch_end_to_end_via_the_flag():
    """The SAME property on the `--profile` route. ⛔ A42 / LL-PHO-132: 24
    green cases once proved nothing about a collection-bound run because every
    one of them was env-bound. Two routes here, named in the case names; the
    collection.json route is not reachable from this suite's temp dump."""
    days = [("2026-03-01", HOME), ("2026-03-02", HOME)]
    rc, out, _, err = run(days, pack((HOME, {"label": OWNER_WORD})),
                          route="flag")
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    places = [b["place"] for b in out["batches"]]
    if places != [OWNER_WORD]:
        return f"the --profile route did not carry the label: {places}"
    return None


@case
def case_an_unlabelled_home_batch_is_unchanged_end_to_end():
    """The positive control for the pair above: same dump, same route, no
    label. If D-F9 had accidentally invented a name for every home batch this
    is the case that catches it — offline, `place` must still be None."""
    days = [("2026-03-01", HOME), ("2026-03-02", HOME)]
    rc, out, _, err = run(days, pack((HOME, {})), route="env")
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    places = [b["place"] for b in out["batches"]]
    if places != [None]:
        return f"an unlabelled home batch acquired a place offline: {places}"
    return None


# An invented address-shaped label. Rule 7: nobody's street, and it exists to
# be recognised BY is_address(), which needs the numbered component.
# i18n-guard:allow-begin — an address is the thing under test
ADDRESS_WORD = "Testville 9\u5df7"
# i18n-guard:allow-end


@case
def case_an_address_shaped_home_label_is_used_and_warned_about():
    """⭐ REPRODUCTION (D-F9 follow-up, owner decision 20260906). On 8bdd625
    the label was used in silence — no warning existed. The owner chose WARN,
    not refuse and
    not silence, which is the D-F5 pattern: the engine tells the owner what
    their own data is about to do and leaves the decision with them.

    ⛔ BOTH halves asserted in one case on purpose. A warning that also
    dropped the name is the option the owner rejected, and a case that only reads
    stderr could not tell the two apart."""
    days = [("2026-03-01", HOME), ("2026-03-02", HOME)]
    profile = pack((HOME, {"label": ADDRESS_WORD}))
    rc, out, _, err = run(days, profile, route="env")
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    expected = photo_profile.messages(profile)[
        "cluster_home_label_is_address"].format(label=ADDRESS_WORD)
    if expected not in err:
        return f"no warning on stderr for an address-shaped label: {err[-200:]!r}"
    if [b["place"] for b in out["batches"]] != [ADDRESS_WORD]:
        return ("the warning came with a refusal — the owner's label must "
                f"still name the day: {[b['place'] for b in out['batches']]}")
    if str(HOME[0]) in err or str(HOME[1]) in err:
        return "the warning echoed the home COORDINATE"
    return None


@case
def case_an_ordinary_home_label_warns_about_nothing():
    """The control. A warning every owner sees is a warning nobody reads, and
    a fix that warned on every label would pass the case above."""
    days = [("2026-03-01", HOME), ("2026-03-02", HOME)]
    profile = pack((HOME, {"label": OWNER_WORD}))
    rc, out, _, err = run(days, profile, route="env")
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    stem = photo_profile.messages(profile)[
        "cluster_home_label_is_address"].split("{")[0]
    if stem in err:
        return f"an ordinary label was warned about: {err[-200:]!r}"
    return None


@case
def case_the_address_warning_is_said_once_per_label_not_once_per_batch():
    """⛔ Why it is read at pack load rather than inside batch_places(): an
    address-shaped label is a property of the PACK. Two home batches here —
    the days are split by a gap — and the owner hears it once."""
    days = [("2026-03-01", HOME), ("2026-06-01", HOME)]
    profile = pack((HOME, {"label": ADDRESS_WORD}))
    rc, out, _, err = run(days, profile, route="env")
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if len(out["batches"]) < 2:
        return f"the fixture stopped making two batches: {len(out['batches'])}"
    stem = photo_profile.messages(profile)[
        "cluster_home_label_is_address"].split("{")[0]
    if err.count(stem) != 1:
        return f"said {err.count(stem)} times, expected once"
    return None


# ---------------------------------------------------------------------------
# R15 — the jump cut reads every AWAY type, not TW_AWAY alone
# ---------------------------------------------------------------------------

FOUR_DAYS = ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04"]


@case
def case_an_overseas_trip_is_cut_by_a_gps_jump():
    """R15, and this is the REPRODUCTION. The jump test used to read
    `== "TW_AWAY"`, so a run of OVERSEAS days could not be cut by distance at
    all — a trip that crossed the far side of a country came back as one leg
    with one geocode, and the case that most needs legs was the one case that
    never got them. Two days in one place, two days ~91 km away: two legs."""
    rc, out, _o, err = run([(FOUR_DAYS[0], ABROAD), (FOUR_DAYS[1], ABROAD),
                            (FOUR_DAYS[2], ABROAD_FAR),
                            (FOUR_DAYS[3], ABROAD_FAR)], pack((HOME, {})))
    if rc != 0:
        return f"exit {rc}: {err}"
    types = types_of(out)
    if types != ["OVERSEAS", "OVERSEAS"]:
        return ("an overseas trip crossing 91 km was not cut into legs: "
                f"{len(types)} batch(es), {types}")
    return None


@case
def case_an_overseas_trip_with_no_big_jump_stays_one_leg():
    """A guard, not a reproduction: the cut is DISTANCE, not the day type.
    Four overseas days inside ~1.4 km of each other are one leg, exactly as
    they were before R15 — otherwise the fix would be splitting every trip."""
    rc, out, _o, err = run([(FOUR_DAYS[0], ABROAD), (FOUR_DAYS[1], ABROAD_NEXT),
                            (FOUR_DAYS[2], ABROAD),
                            (FOUR_DAYS[3], ABROAD_NEXT)], pack((HOME, {})))
    if rc != 0:
        return f"exit {rc}: {err}"
    types = types_of(out)
    if types != ["OVERSEAS"]:
        return f"one city became {len(types)} leg(s): {types}"
    return None


@case
def case_two_homes_far_apart_are_never_cut_by_the_jump():
    """A guard on the half of R15 that was DELIBERATELY not changed. A pack
    may hold several homes and they are far apart on purpose; every day at any
    of them is the same non-event, and a home run is never named. Cutting
    there would manufacture batches out of the one day type that has no place
    to put on them — which is what removing the type test outright would do.
    Two homes ~85 km apart, a day at each, past the 30 km jump: still one."""
    rc, out, _o, err = run([(FOUR_DAYS[0], HOME), (FOUR_DAYS[1], OFTEN)],
                           pack((HOME, {}), (OFTEN, {})))
    if rc != 0:
        return f"exit {rc}: {err}"
    types = types_of(out)
    if types != ["TW_HOME"]:
        return (f"two homes were cut into {len(types)} batch(es) by the "
                f"jump test: {types}")
    return None


@case
def case_a_domestic_away_run_is_still_cut_by_a_gps_jump():
    """The behaviour R15 generalised FROM, asserted so the generalisation
    cannot quietly lose it: two domestic away days ~170 km apart are two
    separate events, as they were before."""
    rc, out, _o, err = run([(FOUR_DAYS[0], FORMER), (FOUR_DAYS[1], TRIP)],
                           pack((HOME, {})))
    if rc != 0:
        return f"exit {rc}: {err}"
    types = types_of(out)
    if types != ["TW_AWAY", "TW_AWAY"]:
        return f"a domestic jump stopped cutting: {len(types)} batch(es), {types}"
    return None


# ---------------------------------------------------------------------------
# D-06 — a place is named in the OWNER'S language, and the cache knows which
#
# The engine used to send `accept-language: zh-TW` on every reverse geocode
# and then prefer Chinese tags in the reply, at both call sites. The Chinese
# name was REQUESTED, not volunteered: an owner whose pack says `en` got
# Chinese district names in their folder names, with nothing in the output to
# say why. Rule 8 — language is a variable, default English.
# ---------------------------------------------------------------------------

def resolved(reply, language):
    """`photo_cluster.read_name`, or a sentinel when the engine has no such
    function yet. ⛔ Deliberately not a bare call: on the unfixed code an
    AttributeError aborts the whole suite at the first case and hides every
    other failure, and a runner that reports one line is a runner nobody can
    read a reproduction out of."""
    fn = getattr(photo_cluster, "read_name", None)
    return fn(reply, language) if fn else ("<no read_name()>", None)


# One Nominatim reply, as the API returns it: several language tags on one
# place, plus the neutral `name`. Invented, and nobody's address.
# ⚠️ The tag VALUES are ASCII placeholders on purpose. What these cases test
# is which TAG the engine reads, and a real script in the value would put CJK
# into a test file for no gain (Rule 8). The one case below that genuinely
# turns on script says so and declares its data.
OSM_REPLY = {"name": "Neutralia",
             "namedetails": {"name": "Neutralia",
                             "name:en": "Neutral Town",
                             "name:ja": "JA-NAME",
                             "name:zh-Hant": "HANT-NAME",
                             "name:zh-Hans": "HANS-NAME"},
             "display_name": "Neutralia, Somewhere",
             "address": {"city": "Neutralia"}}


def seeded_geocoder(language):
    """A Geocoder with a language and no cache file, for key questions."""
    g = photo_cluster.Geocoder.__new__(photo_cluster.Geocoder)
    g.language = language
    return g


@case
def case_the_place_language_comes_from_the_pack():
    """The REPRODUCTION. The engine asked for Chinese whatever the pack said,
    so this is the one case that fails outright on the unfixed code: an `en`
    pack got the Chinese tag."""
    problems = []
    for language, want in (("en", "Neutral Town"),
                           ("ja", "JA-NAME"),
                           ("zh-TW", "HANT-NAME"),
                           ("zh-CN", "HANS-NAME")):
        got, _tag = resolved(OSM_REPLY, language)
        if got != want:
            problems.append(f"{language} -> {got!r}, wanted {want!r}")
    return None if not problems else "; ".join(problems)


@case
def case_no_pack_language_is_english_not_chinese():
    """Rule 8's default, asserted rather than assumed. ⛔ Not the legacy
    zh-TW: an unbound run has no owner to be Chinese for, and the engine
    carries no language of its own."""
    got, _tag = resolved(OSM_REPLY, None)
    if getattr(photo_cluster, "DEFAULT_GEOCODE_LANGUAGE", None) != "en":
        return "the default is no longer English"
    return None if got == "Neutral Town" else f"unbound run got {got!r}"


@case
def case_a_missing_language_tag_falls_back_and_says_so():
    """The fallback has to be VISIBLE. OSM holds no name in this owner's
    language, so the neutral one is used — and the returned tag says which,
    because a place named in the wrong language silently is the whole
    defect."""
    got, tag = resolved(OSM_REPLY, "fi")
    if got != "Neutralia" or tag != "name":
        return f"fallback returned {got!r} from {tag!r}"
    hit, hit_tag = resolved(OSM_REPLY, "en")
    if hit_tag == "name":
        return "a real language hit is reported as a fallback"
    return None if hit == "Neutral Town" else f"{hit!r}"


@case
def case_the_cache_key_carries_the_language():
    """⛔ THE TRAP. The key used to be `lat,lon,z10` with no language in it,
    so changing the language served the PREVIOUS language's name forever, out
    of the cache, with nothing to see — and any test written to prove the
    change worked would pass without reaching the network.

    ⚠️ The consequence is deliberate and is not migrated: an existing cache
    goes cold and re-fetches. An unsuffixed key cannot be assumed to be any
    particular language — a fresh owner's cache has no language in it
    either."""
    if not hasattr(photo_cluster.Geocoder, "key_for"):
        return "the Geocoder has no key_for() — the key is still built inline"
    en, zh = seeded_geocoder("en"), seeded_geocoder("zh-TW")
    point = (12.3456, 65.4321)
    if en.key_for(point, 10) == zh.key_for(point, 10):
        return "two languages share one cache key"
    if "en" not in en.key_for(point, 10):
        return f"the language is not in the key: {en.key_for(point, 10)}"
    # both zoom levels, because the two call sites key separately
    if en.key_for(point, 13) == en.key_for(point, 10):
        return "the zoom left the key"
    return None


@case
def case_a_cached_name_in_another_language_is_never_served():
    """The trap, end to end and offline: a cache holding the zh-TW answer is
    a MISS for an `en` run, so the wrong-language name cannot reach a batch.
    ⛔ `--no-geocode`, so a miss can only resolve to nothing — if this case
    ever returns a name, the key stopped separating the languages."""
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "geocode-cache.json"
        # ⛔ Seeded under the key the UNFIXED engine writes — `lat,lon,z10`
        # with no language in it. That is what makes this a reproduction
        # rather than a test of the new function: on the old code this entry
        # IS the key `city()` looks up, so an `en` run is handed the Chinese
        # name straight out of the cache, offline, with nothing to see.
        legacy = f"{round(TRIP[0], 2):.5f},{round(TRIP[1], 2):.5f},z10"
        cache.write_text(json.dumps(
            {legacy: {"name": "HANT-NAME", "name_tag": "name:zh-Hant"}}))
        try:
            reader = photo_cluster.Geocoder(cache, enabled=False, language="en")
        except TypeError:
            # the unfixed engine takes no language at all — construct it the
            # way that code does, so the case measures its BEHAVIOUR rather
            # than reporting that a new keyword is missing
            reader = photo_cluster.Geocoder(cache, enabled=False)
        got = reader.city(TRIP)
        if got is not None:
            return (f"an `en` run was served {got!r} out of a cache written "
                    "in another language")
    return None


@case
def case_only_traditional_chinese_gets_the_traditional_filter():
    """`pick_traditional()` exists for Traditional owners and is WRONG
    everywhere else — a Simplified owner asked for their own script would
    have it filtered back out of a ';'-joined tag."""
    # i18n-guard:allow-begin — locale detection data, not user-facing output:
    # this is the ONE case whose answer depends on the SCRIPT of the value, so
    # an ASCII placeholder could not exercise it. `trad` and `simp` differ by
    # a character in photo_cluster.SIMPLIFIED_CHARS, which is the whole input
    # `pick_traditional()` decides on.
    # ⚠️ These two, specifically: `simp` is IN photo_cluster.SIMPLIFIED_CHARS
    # and `trad` is not, which is the only property the chooser reads. A pair
    # the detector does not know would pass by falling through to "first
    # variant" and prove nothing — measured, on the first draft of this case.
    trad, simp = "國", "国"
    # i18n-guard:allow-end
    joined = {"namedetails": {"name:zh-Hant": f"{trad};{simp}",
                              "name:zh-Hans": f"{simp};{trad}"}}
    hant, _ = resolved(joined, "zh-TW")
    hans, _ = resolved(joined, "zh-CN")
    if hant != trad:
        return f"a Traditional owner got {hant!r}"
    if hans != simp:
        return f"a Simplified owner got {hans!r} — the Traditional filter ran"
    return None


@case
def a_place_named_in_the_local_language_is_said_out_loud():
    """F7 — the reproduction. `place_name_not_in_owner_language` was appended
    to a batch's flags when the map service had no name in the owner's
    language, and nothing read it but the batch file: `flags` is consumed for
    `no_gps` only. The SKILL promised the product "says so rather than
    swapping scripts silently"; it did not. The notice must name exactly the
    flagged batches, and stay away when there are none."""
    import photo_profile
    notice = getattr(photo_cluster, "local_name_notice", None)
    if notice is None:
        return "photo_cluster has no local_name_notice(): the flag reaches no one"
    flagged = "place_name_not_in_owner_language"
    batches = [{"batch": 1, "flags": []},
               {"batch": 3, "flags": [flagged]},
               {"batch": 7, "flags": ["no_gps", flagged]}]
    msg = photo_profile.messages({"language": "en"})
    said = notice(batches, msg, "en") or ""
    quiet = notice(batches[:1], msg, "en")
    problems = []
    if not ("B3" in said and "B7" in said) or "B1" in said:
        problems.append(f"names the wrong batches: {said!r}")
    if "en" not in said:
        problems.append("does not say which language was asked for")
    if quiet is not None:
        problems.append(f"speaks with nothing flagged: {quiet!r}")
    return "; ".join(problems) or None


# ---------------------------------------------------------------------------
# W2B-3 / ADR 0001 — a place the owner named names the batch
#
# ⭐ REPRODUCTION. Wave 1's onboarding writes `frequent_places` into
# photo-entities.json and nothing in scripts/ read the key: the owner named a
# place and no folder changed. Invented coordinates and words (Rule 7).
# ---------------------------------------------------------------------------

NP_HOME = (10.0, 100.0)
NP_SPOT = (13.1, 99.5)
NP_WORD = "Harbour-Cafe"
NP_DAYS = [("2026-05-01", NP_SPOT)]


def named(*rows):
    return {"frequent_places": [{"label": w, "lat": p[0], "lon": p[1]}
                                for w, p in rows]}


def np_places(out):
    return [b["place"] for b in out["batches"]] if out else None


@case
def case_a_named_place_names_its_batch_env_route():
    """⭐ REPRODUCTION, $PHOTO_PROFILE route. Offline, so on the unfixed
    engine the batch falls to its raw-coordinate fallback."""
    rc, out, _, err = run(NP_DAYS, pack((NP_HOME, {})), route="env",
                          entities=named((NP_WORD, NP_SPOT)))
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    got = np_places(out)
    return None if got == [NP_WORD] else f"the owner's word did not name it: {got}"


@case
def case_a_named_place_names_its_batch_flag_route():
    """⭐ REPRODUCTION, --profile route (LL-PHO-132: one case per route)."""
    rc, out, _, err = run(NP_DAYS, pack((NP_HOME, {})), route="flag",
                          entities=named((NP_WORD, NP_SPOT)))
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    got = np_places(out)
    return None if got == [NP_WORD] else f"the owner's word did not name it: {got}"


@case
def case_a_named_place_names_its_batch_collection_route():
    """⭐ REPRODUCTION, collection.json route — the one a real owner is on."""
    rc, out, _, err = run_bound(NP_DAYS, pack((NP_HOME, {})),
                                ("--away-km", str(AWAY_KM)),
                                entities=named((NP_WORD, NP_SPOT)))
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    got = np_places(out)
    return None if got == [NP_WORD] else f"the owner's word did not name it: {got}"


@case
def case_the_named_place_radius_is_read_off_the_pack():
    """A day 1.5 km from the place is outside the shipped 1 km and inside a
    pack's 2 km. The number is the pack's, never a constant at the call."""
    near = (NP_SPOT[0] + 0.0135, NP_SPOT[1])
    days = [("2026-05-01", near)]
    rc, out, _, err = run(days, pack((NP_HOME, {})),
                          entities=named((NP_WORD, NP_SPOT)))
    if rc != 0 or np_places(out) == [NP_WORD]:
        return f"1.5 km took the name at the 1 km default: {np_places(out)}"
    profile = {**pack((NP_HOME, {})), "cluster_defaults": {"named_place_km": 2}}
    rc, out, _, err = run(days, profile, entities=named((NP_WORD, NP_SPOT)))
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    got = np_places(out)
    return None if got == [NP_WORD] else f"the pack's 2 km was not read: {got}"


@case
def case_a_named_place_day_asks_the_map_nothing():
    """Like a labelled home (D-F9): the owner's word replaces the lookup, it
    is not a second opinion beside it."""
    part, day_files, geo, names, pts = five_day_trip()
    got = photo_cluster.batch_places(
        part, day_files, geo, [], limit=8,
        named_places=[(pts[3][0], pts[3][1], OWNER_WORD)], place_km=1.0)
    if pts[3] in geo.asked:
        return "a named-place day was still geocoded"
    if got != names[:3] + [OWNER_WORD] + names[4:]:
        return f"the owner's word did not name the day: {got}"
    return None


@case
def case_the_nearest_named_place_wins():
    """Not first in file order — file order carries no meaning."""
    part, day_files, geo, names, pts = five_day_trip()
    far = (pts[1][0] + 0.005, pts[1][1], OTHER_WORD)
    near = (pts[1][0] + 0.001, pts[1][1], OWNER_WORD)
    got = photo_cluster.batch_places(part, day_files, geo, [], limit=8,
                                     named_places=[far, near], place_km=1.0)
    return None if got[1] == OWNER_WORD else f"not the nearest: {got}"


@case
def case_beyond_its_radius_a_named_place_leaves_the_map_to_name_it():
    """Guard: 1.5 km away is somewhere else at the 1 km default."""
    part, day_files, geo, names, pts = five_day_trip()
    place = [(pts[1][0] + 0.0135, pts[1][1], OWNER_WORD)]
    got = photo_cluster.batch_places(part, day_files, geo, [], limit=8,
                                     named_places=place, place_km=1.0)
    if got[1] != names[1] or pts[1] not in geo.asked:
        return f"a place 1.5 km off still named the day: {got}"
    return None


@case
def case_a_named_place_never_overrides_a_home():
    """Guard: home label -> named place -> geocoder. A day inside a home's
    radius keeps the home branch exactly as it was, labelled or not."""
    part, day_files, geo, names, pts = five_day_trip()
    geo.admin = {(round(pts[2][0], 4), round(pts[2][1], 4)): "Map-City"}
    home = [(pts[2][0], pts[2][1], None, None)]
    place = [(pts[2][0], pts[2][1], OTHER_WORD)]
    got = photo_cluster.batch_places(
        part, day_files, geo, home, limit=8,
        labelled_homes=[(pts[2][0], pts[2][1], None, None, None)],
        named_places=place, place_km=1.0)
    if got[2] != "Map-City":
        return f"an unlabelled home day took a named place's word: {got}"
    part, day_files, geo, names, pts = five_day_trip()
    got = photo_cluster.batch_places(
        part, day_files, geo, home, limit=8,
        labelled_homes=[(pts[2][0], pts[2][1], None, None, OWNER_WORD)],
        named_places=place, place_km=1.0)
    return None if got[2] == OWNER_WORD else f"the home label lost: {got}"


@case
def case_named_place_km_is_one_fact():
    """⛔ The away_km lesson: a default in code and a default in a pack are
    ONE fact. The template must not ship a second value, and no other
    pack number may move this one."""
    d = photo_profile.NAMED_PLACE_KM_DEFAULT
    shipped = json.loads(TEMPLATE_PROFILE.read_text()).get("cluster_defaults") or {}
    if photo_profile.named_place_km({"cluster_defaults": shipped}) != d:
        return f"the template ships named_place_km {shipped.get('named_place_km')!r}, the code {d!r}"
    if photo_profile.named_place_km({}) != d:
        return "an empty pack does not get the one default"
    if photo_profile.named_place_km({"cluster_defaults": {"away_km": 7}}) != d:
        return "away_km moved the named-place radius"
    if photo_profile.named_place_km({"cluster_defaults": {"named_place_km": 2.5}}) != 2.5:
        return "a pack value was not read"
    for bad in ("x", -1, 0, None, [1]):
        if photo_profile.named_place_km({"cluster_defaults": {"named_place_km": bad}}) != d:
            return f"a malformed radius {bad!r} did not fall back"
    return None


@case
def case_a_malformed_named_place_is_skipped_never_fatal():
    """Unlike a home, a bad row costs one day its owner's word, not the run:
    a named place protects nothing, so it can never switch anything off."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "photo-entities.json").write_text(json.dumps(
            {"frequent_places": ["x", {"label": "No-Coord"},
                                 {"label": " ", "lat": 1, "lon": 2},
                                 {"label": "Bad-Lat", "lat": "n", "lon": 2},
                                 {"label": " Good ", "lat": "1.5", "lon": 2}]}))
        got = photo_profile.named_places(photo_profile.Pack(directory=tmp))
        # D-I15: the 4th element is the place's id — None here, none written.
        if got != [(1.5, 2.0, "Good", None)]:
            return f"got {got}"
        (Path(tmp) / "photo-entities.json").write_text("{not json")
        if photo_profile.named_places(photo_profile.Pack(directory=tmp)) != []:
            return "unreadable JSON did not answer []"
    if photo_profile.named_places(photo_profile.Pack()) != []:
        return "a run with no pack did not answer []"
    return None


@case
def case_an_address_shaped_place_name_is_used_and_said_once():
    """The D-F5 pattern, as for a home label: used, warned about once per
    name, never refused — the word is the owner's."""
    days = [("2026-05-01", NP_SPOT), ("2026-08-01", NP_SPOT)]
    profile = pack((NP_HOME, {}))
    rc, out, _, err = run(days, profile, entities=named((ADDRESS_WORD, NP_SPOT)))
    if rc != 0:
        return f"exit {rc}: {err.strip()[:200]}"
    if len(out["batches"]) < 2:
        return f"the fixture stopped making two batches: {len(out['batches'])}"
    line = photo_profile.messages(profile).get(
        "cluster_place_label_is_address", "\x00missing").format(label=ADDRESS_WORD)
    if err.count(line) != 1:
        return f"said {err.count(line)} times, expected once: {err[-200:]!r}"
    if np_places(out) != [ADDRESS_WORD, ADDRESS_WORD]:
        return f"the warning came with a refusal: {np_places(out)}"
    return None


# ---- FIX6 F5: a day whose median sits where no photo was taken ----

def midpoint_day(stops_at, answers, homes=()):
    """One day of two photos far apart. `stops_at` is [(point, hour)] in any
    order; the day's centroid is their median, as `read_day_files` computes
    it. -> (part, day_files, stub geocoder, all_homes, labelled homes)."""
    from datetime import date, datetime
    from statistics import median
    d = date(2029, 5, 4)
    points = [(p[0], p[1], datetime(2029, 5, 4, h)) for p, h in stops_at]
    centroid = (median(p[0] for p in points), median(p[1] for p in points))
    day_files = {d: {"centroid": centroid, "gps": [(p[0], p[1]) for p in points],
                     "points": points}}
    profile = {"home_locations": [{"id": f"home-0{i + 1}", "label": label,
                                   "lat": pt[0], "lon": pt[1]}
                                  for i, (pt, label) in enumerate(homes)]}
    geo = StubGeocoder({(round(a, 4), round(b, 4)): n for (a, b), n in answers.items()})
    return ([d], day_files, geo, photo_profile.home_points(profile),
            photo_profile.labelled_home_points(profile), centroid)


HOME_A, HOME_B = (40.0, 10.0), (40.5, 10.0)
AWAY_X = (40.0, 10.3)


def named_midpoint_day(stops_at, answers, homes=()):
    part, day_files, geo, all_homes, labelled, centroid = midpoint_day(
        stops_at, answers, homes)
    answers_mid = dict(answers)
    answers_mid[centroid] = "Mid-Town"
    geo.answers = {(round(a, 4), round(b, 4)): n for (a, b), n in answers_mid.items()}
    got = photo_cluster.batch_places(part, day_files, geo, all_homes,
                                     labelled_homes=labelled)
    return got, geo


@case
def case_a_midpoint_day_is_named_by_its_away_stop_not_the_midpoint():
    """⭐ REPRODUCTION (FIX6 F5, owner decision 20260915). ⛔ FAILS on 0865b82: a day
    with one photo at home in the morning and one 25 km away at noon took the
    name of the district HALFWAY between them, where no photo was taken
    (UAT01-6: 9 of 119 days, 59.8 km at worst). It is named by the away stop."""
    got, _geo = named_midpoint_day([(HOME_A, 9), (AWAY_X, 13)],
                                   {AWAY_X: "Place-X"}, homes=[(HOME_A, "Home-A")])
    return None if got == ["Place-X"] else f"named {got}"


@case
def case_a_home_photo_after_the_outing_does_not_name_the_day():
    """REPRODUCTION (FIX6 F5, Lead rule). ⛔ FAILS on 0865b82 (named by the
    midpoint). The LAST AWAY stop names the day, so an evening photo at home
    after an outing never renames the outing after home."""
    got, _geo = named_midpoint_day([(AWAY_X, 13), (HOME_A, 19)],
                                   {AWAY_X: "Place-X"}, homes=[(HOME_A, "Home-A")])
    return None if got == ["Place-X"] else f"named {got}"


@case
def case_a_day_between_two_homes_takes_the_last_homes_label():
    """REPRODUCTION (FIX6 F5). ⛔ FAILS on 0865b82: a morning at one home and a
    night at another was named after a town between them. A day whose stops
    are ALL homes takes the last home's own label, and asks the map nothing."""
    got, geo = named_midpoint_day([(HOME_A, 9), (HOME_B, 23)], {},
                                  homes=[(HOME_A, "Home-A"), (HOME_B, "Home-B")])
    if geo.asked or geo.asked_admin:
        return f"a labelled home day asked the map: {geo.asked} {geo.asked_admin}"
    return None if got == ["Home-B"] else f"named {got}"


@case
def case_an_unnameable_away_stop_keeps_the_days_word_never_a_blank():
    """GUARD (FIX6 F5, Lead rule). A stop the chain cannot name (a cache miss
    with the geocoder off) leaves the day its centroid word as before; a day
    that had a word never loses it."""
    got, _geo = named_midpoint_day([(HOME_A, 9), (AWAY_X, 13)], {},
                                   homes=[(HOME_A, "Home-A")])
    return None if got == ["Mid-Town"] else f"named {got}"


@case
def case_a_day_whose_median_sits_among_its_photos_is_unchanged():
    """GUARD (FIX6 F5). Only a median further than a stop's width from EVERY
    photo is re-read; any other day asks for its centroid once, as before."""
    near = (AWAY_X[0], AWAY_X[1] + 0.01)
    part, day_files, geo, all_homes, labelled, centroid = midpoint_day(
        [(AWAY_X, 10), (near, 11)], {})
    geo.answers = {(round(centroid[0], 4), round(centroid[1], 4)): "Place-X"}
    got = photo_cluster.batch_places(part, day_files, geo, all_homes,
                                     labelled_homes=labelled)
    return (None if got == ["Place-X"] and len(geo.asked) == 1
            else f"named {got}, asked {len(geo.asked)}")


@case
def case_every_reverse_lookup_sends_at_most_2_dp():
    """REPRODUCTION (RS7c, owner ruling 20260929). ⛔ FAILS on 8ba35a1:
    `Geocoder.city()` and `photo_where.area_name()` sent the batch or stop
    centre at full precision; only `city_admin()` rounded. Every Nominatim
    reverse request now leaves at 2 dp, the cache key's own precision.
    Asserted on the URL each site builds, with the network never reached."""
    import re as _re
    import time as _time
    import urllib.request as ur
    import photo_cluster as pc
    import photo_where as pw
    fine = (20.1234567891234, 100.9876543219876)   # invented (Rule 7)
    sent = []

    def fake(req, *a, **k):
        sent.append(req.full_url)
        raise RuntimeError("network refused by the test")

    real_open, real_sleep = ur.urlopen, _time.sleep
    ur.urlopen, _time.sleep = fake, (lambda s: None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            geo = pc.Geocoder(Path(tmp) / "geocode-cache.json", enabled=True)
            sites = {"Geocoder.city": lambda: geo.city(fine),
                     "Geocoder.city_admin": lambda: geo.city_admin(fine),
                     "photo_where.area_name": lambda: pw.area_name(fine, geo)}
            bad = []
            for name, call in sites.items():
                before = len(sent)
                call()
                if len(sent) != before + 1:
                    bad.append(f"{name}: built no request")
                    continue
                url = sent[-1]
                for axis in ("lat", "lon"):
                    m = _re.search(axis + r"=(-?[0-9.]+)", url)
                    dp = len(m.group(1).split(".")[1]) if m and "." in m.group(1) else 0
                    if not m or dp > 2:
                        bad.append(f"{name}: {axis} not at most 2 dp: {url}")
    finally:
        ur.urlopen, _time.sleep = real_open, real_sleep
    return "; ".join(bad) or None


@case
def case_no_reverse_url_is_built_outside_the_one_helper():
    """GUARD (RS7c). A new call site that writes its own Nominatim reverse URL
    would skip the rounding silently: the URL lives in one place only."""
    hits = [f"{p.name}:{i}" for p in sorted(SCRIPTS.glob("*.py"))
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if "nominatim.openstreetmap.org/reverse" in line]
    return (None if len(hits) == 1 and hits[0].startswith("photo_cluster.py:")
            else f"reverse URL built at {hits}")


# ---------------------------------------------------------------------------
# K20 — the owner's own country, not Taiwan for everyone
# ---------------------------------------------------------------------------

US_HOME = (40.0000, -100.0000)   # invented, outside every COUNTRY_BOXES row
US_TRIP = (42.5000, -100.0000)   # ~280 km from US_HOME
K20_DAYS = ["2026-05-01", "2026-05-02", "2026-05-03"]


def k20_types(home, trip, extra=None, third=None):
    profile = {"language": "en",
               "home_locations": [{"lat": home[0], "lon": home[1]}], **(extra or {})}
    days = list(zip(K20_DAYS, [home, trip, third or home]))
    rc, out, _so, err = run(days, profile)
    return rc, (types_of(out, profile) if out else None), err


@case
def k20_an_owner_outside_taiwan_is_never_abroad_at_home():
    """⭐ REPRODUCTION (K20). ⛔ FAILS on 2559783: the Taiwan box was tested
    BEFORE the home, so for an owner who lives anywhere else every day — home
    days included — was OVERSEAS ("abroad — <their home>", measured on a
    made-up US owner). With no day test for their country the owner's days
    are home or away, never abroad. Both routes: a home outside every row,
    and a declared `country`."""
    got = {}
    for name, extra in (("undeclared", None), ("declared US", {"country": "US"})):
        rc, types, err = k20_types(US_HOME, US_TRIP, extra)
        got[name] = types if rc == 0 else f"rc={rc} {err[-200:]}"
    want = ["TW_HOME", "TW_AWAY", "TW_HOME"]
    return None if all(v == want for v in got.values()) else f"want {want}, got {got}"


@case
def k20_a_taiwan_owner_is_unchanged():
    """GUARD (K20). A home in the TW row is TW without declaring it, and a
    declared TW is the same: home, away and abroad exactly as before."""
    got = {}
    for name, extra in (("undeclared", None), ("declared TW", {"country": "tw"})):
        rc, types, err = k20_types(HOME, TRIP, extra, third=ABROAD)
        got[name] = types if rc == 0 else f"rc={rc} {err[-200:]}"
    want = ["TW_HOME", "TW_AWAY", "OVERSEAS"]
    return None if all(v == want for v in got.values()) else f"want {want}, got {got}"


@case
def k20_a_home_outside_the_owners_country_is_still_abroad():
    """GUARD (K20, U2-04 — the owner's ruling). ONE country per owner: a Taiwan
    owner's registered home abroad is still abroad, whether the country is
    declared or comes from the first home."""
    profile_extra = {"home_locations": [{"lat": HOME[0], "lon": HOME[1]},
                                        {"lat": ABROAD[0], "lon": ABROAD[1]}]}
    got = {}
    for name, extra in (("first home", {}), ("declared TW", {"country": "TW"})):
        profile = {"language": "en", **profile_extra, **extra}
        rc, out, _so, err = run(list(zip(K20_DAYS, [HOME, ABROAD, HOME])), profile)
        got[name] = types_of(out, profile) if rc == 0 and out else f"rc={rc} {err[-200:]}"
    want = ["TW_HOME", "OVERSEAS", "TW_HOME"]
    return None if all(v == want for v in got.values()) else f"want {want}, got {got}"


@case
def k20_a_malformed_country_stops_the_run():
    """GUARD (K20). A country the engine cannot read decides which days are
    abroad, so it stops the run with a sentence — never a guess."""
    rc, _out, _so, err = run(list(zip(K20_DAYS, [US_HOME] * 3)),
                             {"country": "United States",
                              "home_locations": [{"lat": US_HOME[0], "lon": US_HOME[1]}]})
    return None if rc != 0 and "two-letter country code" in err else f"rc={rc} {err[-200:]}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    failed = 0
    for fn in CASES:
        problem = fn()
        if problem:
            failed += 1
            print(f"FAIL  {fn.__name__}\n      {problem}")
        elif args.verbose:
            print(f"pass  {fn.__name__}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} cluster cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
