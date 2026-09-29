#!/usr/bin/env python3
"""Cases for photo_recurrence.py (VS-1b) — the four axes, blast-radius
ranking, stable candidate ids, the cross-census obs_count bump, and the
residence privacy rule.

Every fixture is synthetic: vectors are hand-built in a 32-dimensional toy
space with a fixed geometry, and the "photos" are manifest rows that never
existed. Nothing here is a real photo, a real vector or a real place — the
same rule photo_embed_cases.py follows, for the same reason (an exemplar
store must never live in this repo).

Needs **numpy**, which lives in the repo .venv, so it runs there — but NOT
torch: the census loads no model. It is not part of the stdlib-only
three-suite chain in tests/README.md.

  ./.venv/bin/python3 tests/photo_recurrence_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import photo_profile  # noqa: E402
import photo_recurrence as pr  # noqa: E402

VERBOSE = False
DIM = 32
HOME = (25.00, 121.00)          # synthetic, and deliberately not anybody's
HILL = (24.00, 121.50)
NEAR_HOME = (25.02, 121.00)     # ~2.2 km away: a fragment of the same home


def log(msg):
    if VERBOSE:
        print(f"  {msg}")


def unit(v):
    return np.asarray(v, dtype=np.float32) / float(np.linalg.norm(v))


def basis(i):
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


RNG = np.random.RandomState(7)


def orth(base):
    """A deterministic direction orthogonal to base — random enough that two
    of them are far apart in cosine, which is what makes the leftover files
    below singletons instead of a cluster."""
    v = RNG.normal(size=DIM).astype(np.float32)
    return unit(v - float(v @ base) * np.asarray(base, dtype=np.float32))


def near(base, direction, jitter=0.12):
    """A member of base's cluster: close enough to be inside tau, off-axis
    enough that the cluster is not a pile of identical vectors."""
    return unit(base + jitter * direction)


def blend(base, direction, cos):
    """A vector at exactly `cos` from base, along an orthogonal direction."""
    return unit(cos * base + float(np.sqrt(1 - cos * cos)) * direction)


class Fixture:
    """Accumulates synthetic files, then writes them out as one or more work
    dirs that look exactly like photo_embed.py's output."""

    def __init__(self, prefix="f"):
        self.prefix = prefix
        self.files = []

    def add(self, vec, when, gps, make="Apple", status="embedded", n=1, day_step=0):
        for k in range(n):
            i = len(self.files)
            date = when if not day_step else when.replace(day=when.day + k * day_step)
            self.files.append({
                "name": f"IMG_{self.prefix}{i:04d}.JPG", "vec": np.asarray(vec, dtype=np.float32),
                "date": date, "gps": gps, "make": make, "status": status})
        return self

    def write(self, root, name, start=0, end=None):
        workdir = Path(root) / name
        (workdir / "embed").mkdir(parents=True, exist_ok=True)
        chunk = self.files[start:end if end is not None else len(self.files)]
        with open(workdir / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["SourceFile", "FileName", "FileType",
                                              "DateTimeOriginal", "GPSPosition", "Make"])
            w.writeheader()
            for rec in chunk:
                w.writerow({
                    "SourceFile": str(workdir / rec["name"]), "FileName": rec["name"],
                    "FileType": "JPEG",
                    "DateTimeOriginal": rec["date"].strftime("%Y:%m:%d %H:%M:%S"),
                    "GPSPosition": (f"{rec['gps'][0]} {rec['gps'][1]}" if rec["gps"] else "-"),
                    "Make": rec["make"]})
        with open(workdir / "embed" / "embeddings.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["SourceFile", "sha256", "kind", "status",
                                              "size", "mtime", "error"])
            w.writeheader()
            for rec in chunk:
                w.writerow({"SourceFile": str(workdir / rec["name"]),
                            # The kind column is the one VS-1 defect the census
                            # tolerates by never reading it — so lie in it here.
                            "sha256": sha_of(rec["name"]), "kind": "video",
                            "status": rec["status"], "size": 100, "mtime": "1.0", "error": ""})
        vecs = np.stack([rec["vec"] if rec["status"] == "embedded" else np.zeros(DIM)
                         for rec in chunk]).astype(np.float32)
        with open(workdir / "embed" / "embeddings.npy", "wb") as f:
            np.save(f, vecs)
        (workdir / "embed" / "embeddings-meta.json").write_text(json.dumps({
            "model_id": "ViT-B-32", "pretrained_tag": "laion2b_s34b_b79k",
            "embed_dim": DIM, "normalized": True,
            "preprocess_fingerprint": "sha256:testfixture0000"}))
        return workdir


def sha_of(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


CAT, SUNSET, HIKE = basis(0), basis(1), basis(2)


def standard_fixture():
    """One synthetic collection with a known answer:

      cat      32 files at HOME, 32 days over 4 months, 21:00  -> a subject
      sunset   10 files at HOME,  4 days over 2 months, 17:00  -> home-bound
      hike     12 files at HILL,  6 days over 3 months, 09:00  -> place-bound
      near     20 leftovers at cos 0.77 from HIKE — inside the blast-radius
               reach (tau - 0.05) but outside the cluster, and mutually far
               enough apart to stay singletons
      burst    12 files at cos 0.77 from SUNSET, one day, a cluster of its own
      frag      3 files 2.2 km from HOME, unlike anything else visually
                (they exist to prove the AREA is absorbed into the residence)
      failed    1 zero vector (must be ignored)
    """
    RNG.seed(7)          # the geometry below must not depend on earlier cases
    f = Fixture("s")
    for k in range(32):                                  # 4 months x 4 days x 2
        month = 1 + (k // 8)
        day = 3 + (k % 8) * 3
        f.add(near(CAT, basis(3 + k % 5)), datetime(2026, month, day, 21, 0), HOME)
    for k in range(10):
        f.add(near(SUNSET, basis(8 + k % 4), jitter=0.03),
              datetime(2026, 2 + k % 2, 5 + (k % 4) * 6, 17, 0), HOME)
    for k in range(12):
        f.add(near(HIKE, basis(12 + k % 5), jitter=0.04),
              datetime(2026, 1 + k % 3, 4 + (k % 6) * 4, 9, 0), HILL)
    for k in range(20):
        f.add(blend(HIKE, orth(HIKE), 0.77), datetime(2026, 3, 1 + k, 10, 0), None)
    # Deliberately built on basis vectors no other group uses, so the cosine
    # between a burst file and a sunset file is exactly 0.77 — inside the
    # blast-radius reach, outside tau. A random direction here overlapped the
    # sunset jitter enough to merge two of them.
    burst = blend(SUNSET, unit(basis(17) + basis(18)), 0.77)
    for k in range(12):
        f.add(near(burst, basis(19 + k % 3), jitter=0.06),
              datetime(2026, 4, 9, 14, 0), HILL)
    for k in range(3):
        f.add(near(basis(25), basis(26)), datetime(2026, 3, 20 + k, 22, 0), NEAR_HOME)
    f.add(np.zeros(DIM), datetime(2026, 5, 1, 12, 0), HOME, status="failed")
    return f


def build(workdirs, prior=(), run_id="census-test"):
    return pr.build([str(w) for w in workdirs], pr.TAU, list(prior), run_id)


def by_kind(census, kind):
    return [c for c in census["candidates"] if c["kind"] == kind]


def run_case(name, fn):
    try:
        fn()
        print(f"  ok    {name}")
        return True
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        return False


# ---------------------------------------------------------------- cases


def case_axes_are_scored(tmp):
    wd = standard_fixture().write(tmp, "dump-a")
    census, _, _ = build([wd])

    subjects = [c for c in census["candidates"]
                if c["axes"]["mass"] >= 30 and c["kind"] != "residence_area"]
    assert len(subjects) == 1, [c["kind"] for c in subjects]
    a = subjects[0]["axes"]
    assert a["mass"] == 32, a["mass"]                        # mass
    assert a["spread_days"] == 32 and a["spread_months"] == 4, a  # spread
    assert a["persistence_span_days"] > 90, a                # persistence
    assert a["place_boundness"] == 1.0, a                    # place-boundness
    assert a["bound_area_kind"] == "residence", a
    assert a["night_share"] == 1.0 and a["time_of_day"] == "mostly after dark", a

    hikes = [c for c in census["candidates"] if c["axes"]["bound_area"] == "area-1"]
    assert hikes and hikes[0]["kind"] == "place_bound_pattern", [c["kind"] for c in hikes]
    assert hikes[0]["axes"]["spread_months"] == 3, hikes[0]["axes"]


def case_blast_radius_ranks_and_counts_leftovers_only(tmp):
    wd = standard_fixture().write(tmp, "dump-a")
    census, _, _ = build([wd])
    blasts = [c["blast_radius"] for c in census["candidates"]]
    assert blasts == sorted(blasts, reverse=True), blasts

    hike = next(c for c in census["candidates"] if c["axes"]["bound_area"] == "area-1")
    assert hike["near_miss_files"] == 20, hike["near_miss_files"]
    assert hike["blast_radius"] == 32, hike["blast_radius"]

    # The 12-file one-day burst sits just as close to the sunset candidate, but
    # it is a coherent cluster of its own — it must not donate its mass.
    sunset = next(c for c in census["candidates"]
                  if c["kind"] == "residence_bound_pattern" and c["axes"]["mass"] == 10)
    assert sunset["near_miss_files"] == 0, sunset["near_miss_files"]
    assert sunset["blast_radius"] == 10, sunset["blast_radius"]


def case_ids_are_stable_across_reruns(tmp):
    a = standard_fixture().write(tmp, "dump-a")
    first, _, _ = build([a], run_id="census-1")
    second, _, _ = build([a], run_id="census-2")
    ids1 = [c["candidate_id"] for c in first["candidates"]]
    ids2 = [c["candidate_id"] for c in second["candidates"]]
    assert ids1 == ids2, (ids1, ids2)
    assert all(i.startswith("rc-") for i in ids1), ids1
    assert len(set(ids1)) == len(ids1), "candidate ids must be unique within a census"


def case_ids_do_not_depend_on_workdir_order(tmp):
    f = standard_fixture()
    half = len(f.files) // 2
    a = f.write(tmp, "dump-a", 0, half)
    b = f.write(tmp, "dump-b", half)
    forward, _, _ = build([a, b])
    backward, _, _ = build([b, a])
    assert ([c["candidate_id"] for c in forward["candidates"]]
            == [c["candidate_id"] for c in backward["candidates"]])


def case_reobservation_bumps_obs_count(tmp):
    f = standard_fixture()
    a = f.write(tmp, "dump-a")
    first, _, _ = build([a], run_id="census-1")
    cat = next(c for c in first["candidates"] if c["axes"]["mass"] == 32)
    assert cat["obs_count"] == 1 and cat["status"] == "ai-drafted", cat["status"]

    # A later census sees the same subject plus new members of it.
    grown = Fixture("g")
    for k in range(9):
        grown.add(near(CAT, basis(3 + k % 5)), datetime(2026, 5, 2 + k * 2, 21, 0), HOME)
    b = grown.write(tmp, "dump-b")
    second, _, _ = build([a, b], prior=first["candidates"], run_id="census-2")

    same = [c for c in second["candidates"] if c["candidate_id"] == cat["candidate_id"]]
    assert len(same) == 1, f"the grown subject forked into {len(same)} drafts"
    assert same[0]["axes"]["mass"] == 41, same[0]["axes"]["mass"]
    assert same[0]["obs_count"] == 2, same[0]["obs_count"]
    assert same[0]["status"] == "ai-reinforced", same[0]["status"]
    assert same[0]["first_observed_in_census"] == "census-1", same[0]


def case_renaming_a_subject_does_not_fork_its_folder(tmp):
    """N-10a / LL-PHO-39. On a recurring-subject or D9 pet folder the confirmed
    name REPLACES the routing class word, so the folder's own name is mutable.
    Key on the rendered string and the first rename forks the folder in two.

    The whole test is one rename: the display name changes, the key does not.
    Names here are invented test strings — no owner facts (the pack ships
    empty)."""
    a = standard_fixture().write(tmp, "dump-a")
    census, _, _ = build([a], run_id="census-1")
    cat = next(c for c in census["candidates"] if c["axes"]["mass"] == 32)

    # 1. before confirmation: the identity is the census candidate
    draft = pr.subject_folder("2026_01-05", candidate=cat, fallback_word="class-word")
    assert draft["identity"] == cat["candidate_id"], draft
    assert draft["identity_source"] == "census candidate", draft
    assert draft["folder_name"] == "2026_01-05_class-word", draft
    assert draft["key"] == f"2026_01-05/subject:{cat['candidate_id']}", draft

    # 2. confirmed with a name — N-10a's substitution. Rendered name changes,
    #    key does not, so the drafted folder and the named one are ONE folder.
    entry = {"subject_id": "subj-0001", "kind": "pet", "name": "Name-One"}
    named = pr.subject_folder("2026_01-05", candidate=cat, registry_entry=entry)
    assert named["folder_name"] == "2026_01-05_Name-One", named
    assert named["identity_source"] == "registry", named

    # 3. the rename itself
    renamed = pr.subject_folder("2026_01-05", candidate=cat,
                                registry_entry={**entry, "name": "Name-Two",
                                                "previous_names": ["Name-One"]})
    assert renamed["folder_name"] == "2026_01-05_Name-Two", renamed
    assert renamed["key"] == named["key"], \
        "the rename forked the folder — this is LL-PHO-39 happening again"
    assert len({named["key"], renamed["key"]}) == 1
    assert renamed["previous_names"] == ["Name-One"], renamed
    assert "Name-One" not in renamed["key"] and "Name-Two" not in renamed["key"], \
        "a rendered name may never appear in the key"

    # 4. a tree sorted before the rename still resolves afterwards (N-6 ledger)
    ledger = {"Name-One": "subj-0001"}
    assert pr.resolve_subject_key("2026_01-05", "Name-One", ledger) == renamed["key"]
    assert pr.resolve_subject_key("2026_01-05", "Name-Three", ledger) is None, \
        "an unresolvable folder is a question, never a new folder on a guess"

    # 5. no identity at all is a hard failure, not a fall-back to the name
    try:
        pr.subject_folder("2026_01-05", registry_entry={"name": "Name-Two"})
    except ValueError as exc:
        assert "identity" in str(exc), exc
    else:
        raise AssertionError("a folder was keyed with no identity behind it")


def case_reset_starts_obs_count_over(tmp):
    a = standard_fixture().write(tmp, "dump-a")
    first, _, _ = build([a], run_id="census-1")
    fresh, _, _ = build([a], prior=[], run_id="census-2")
    assert all(c["obs_count"] == 1 and c["status"] == "ai-drafted"
               for c in fresh["candidates"])


def case_residence_is_inferred_and_suppressed(tmp):
    wd = standard_fixture().write(tmp, "dump-a")
    census, records, areas = build([wd])

    residences = [a for a in census["areas"] if a["kind"] == "residence"]
    assert len(residences) == 1, [a["area_id"] for a in census["areas"]]
    home = residences[0]
    assert home["area_id"] == "residence-A", home
    assert home["approx_center"] is None, "a residence must never carry coordinates"
    assert home["absorbed_nearby_areas"] == 1, home       # the 2.2 km fragment
    assert home["files"] == 45, home["files"]             # 32 cat + 10 sunset + 3 fragment
    # Re-stated AFTER absorption: the fragment's own days count too, or the
    # home under-reports the axes it is ranked on. 32 cat days + 4 sunset days
    # + 2 fragment days the others did not already cover = 38.
    assert home["days"] == 38, home["days"]
    assert home["first_seen"] == "2026-01-03", home["first_seen"]
    assert home["last_seen"] == "2026-04-24", home["last_seen"]

    markdown = pr.scrub(pr.render_markdown(census), records, areas)
    for forbidden in ("25.0", "121.0", "24.0", "121.5"):
        assert forbidden not in markdown, f"markdown leaked the coordinate {forbidden}"
    assert "residence-A" in markdown


def case_scrub_catches_a_directory_name_leak(tmp):
    wd = standard_fixture().write(tmp, "202512_home_place_resort")
    census, records, areas = build([wd])
    leaked = pr.render_markdown(census) + "\n\nsource: 202512_home_place_resort\n"
    try:
        pr.scrub(leaked, records, areas)
    except AssertionError as e:
        assert "202512_home_place_resort" in str(e), e
        return
    raise AssertionError("scrub() let a directory name through")


def case_scrub_catches_a_coordinate_leak(tmp):
    wd = standard_fixture().write(tmp, "dump-a")
    census, records, areas = build([wd])
    leaked = pr.render_markdown(census) + "\n\nhome is at 25.00,121.00\n"
    try:
        pr.scrub(leaked, records, areas)
    except AssertionError as e:
        assert "coordinate" in str(e), e
        return
    raise AssertionError("scrub() let a coordinate through")


def case_nothing_is_named(tmp):
    """V2-6: the census may draft anything and name nothing. Every emitted
    label must be one of the kinds or an opaque area id."""
    wd = standard_fixture().write(tmp, "dump-a")
    census, _, _ = build([wd])
    kinds = {"residence_area", "residence_bound_pattern", "place_bound_pattern",
             "recurring_subject_or_scene", "bulk_no_camera_class"}
    for c in census["candidates"]:
        assert c["kind"] in kinds, c["kind"]
        assert c["status"] in ("ai-drafted", "ai-reinforced"), c["status"]
        assert c["noticed_by"] == "agent", c
        assert "confirmed_by" not in c, "a draft can never carry a confirmer"
        assert c["axes"]["bound_area"] in (None,) or c["axes"]["bound_area"].startswith(
            ("area-", "residence-")), c["axes"]["bound_area"]


def case_pack_blind(tmp):
    """The census runs before any pack exists, so it must never resolve one."""
    wd = standard_fixture().write(tmp, "dump-a")
    saved = photo_profile.resolve_pack, photo_profile.load_profile, photo_profile.get

    def boom(*a, **k):
        raise AssertionError("the recurrence census resolved an owner pack")

    photo_profile.resolve_pack = photo_profile.load_profile = photo_profile.get = boom
    try:
        census, records, areas = build([wd])
        pr.scrub(pr.render_markdown(census), records, areas)
    finally:
        (photo_profile.resolve_pack, photo_profile.load_profile,
         photo_profile.get) = saved


def case_failed_rows_are_excluded(tmp):
    wd = standard_fixture().write(tmp, "dump-a")
    census, records, _ = build([wd])
    assert census["coverage"]["files"] == 89, census["coverage"]["files"]  # 90 - 1 failed
    assert len(records) == 89, len(records)


def case_duplicate_content_counted_once(tmp):
    f = standard_fixture()
    a = f.write(tmp, "dump-a")
    b = f.write(tmp, "dump-b")           # the same files again, byte for byte
    one, _, _ = build([a])
    both, _, _ = build([a, b])
    assert one["coverage"]["files"] == both["coverage"]["files"], (
        one["coverage"]["files"], both["coverage"]["files"])


def case_model_mismatch_hard_fails(tmp):
    f = standard_fixture()
    a = f.write(tmp, "dump-a")
    b = f.write(tmp, "dump-b")
    meta = json.loads((b / "embed" / "embeddings-meta.json").read_text())
    meta["pretrained_tag"] = "something-else"
    (b / "embed" / "embeddings-meta.json").write_text(json.dumps(meta))
    try:
        build([a, b])
    except SystemExit as e:
        assert "different model" in str(e), e
        return
    raise AssertionError("two models' vectors were mixed in one census")


def case_cli_refuses_overwrite(tmp):
    wd = standard_fixture().write(tmp, "dump-a")
    out = Path(tmp) / "census-out"
    cmd = [sys.executable, str(ROOT / "scripts" / "photo_recurrence.py"), str(wd),
           "--out", str(out)]
    first = subprocess.run(cmd, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert (out / "recurrence-census.json").exists()
    assert (out / "photo-proposals-draft.md").exists()

    second = subprocess.run(cmd, capture_output=True, text=True)
    assert second.returncode != 0, "a second run overwrote the census without --force"
    assert "--force" in second.stderr, second.stderr

    third = subprocess.run(cmd + ["--force"], capture_output=True, text=True)
    assert third.returncode == 0, third.stderr
    census = json.loads((out / "recurrence-census.json").read_text())
    assert all(c["obs_count"] == 2 for c in census["candidates"]), \
        "--force must carry the previous census forward"

    fourth = subprocess.run(cmd + ["--force", "--reset"], capture_output=True, text=True)
    assert fourth.returncode == 0, fourth.stderr
    census = json.loads((out / "recurrence-census.json").read_text())
    assert all(c["obs_count"] == 1 for c in census["candidates"]), "--reset must start over"


CASES = [
    ("the four axes are scored off the members' own EXIF", case_axes_are_scored),
    ("blast radius ranks, and reaches leftovers only",
     case_blast_radius_ranks_and_counts_leftovers_only),
    ("candidate ids are stable across re-runs", case_ids_are_stable_across_reruns),
    ("candidate ids do not depend on work-dir order", case_ids_do_not_depend_on_workdir_order),
    ("a re-observed candidate bumps obs_count instead of forking",
     case_reobservation_bumps_obs_count),
    ("renaming a subject does not fork its folder (N-10a, LL-PHO-39)",
     case_renaming_a_subject_does_not_fork_its_folder),
    ("--reset starts obs_count over", case_reset_starts_obs_count_over),
    ("a residence is inferred, absorbed and never given coordinates",
     case_residence_is_inferred_and_suppressed),
    ("scrub() catches a directory-name leak", case_scrub_catches_a_directory_name_leak),
    ("scrub() catches a coordinate leak", case_scrub_catches_a_coordinate_leak),
    ("the census drafts everything and names nothing (V2-6)", case_nothing_is_named),
    ("the census never resolves an owner pack", case_pack_blind),
    ("failed rows (zero vectors) are excluded", case_failed_rows_are_excluded),
    ("the same content in two dumps is counted once", case_duplicate_content_counted_once),
    ("two models' indexes are never mixed", case_model_mismatch_hard_fails),
    ("the CLI refuses to overwrite without --force", case_cli_refuses_overwrite),
]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    passed = 0
    for name, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="photo_recurrence_test_"))
        try:
            passed += 1 if run_case(name, lambda: fn(tmp)) else 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{passed}/{len(CASES)} photo_recurrence cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
