#!/usr/bin/env python3
"""Card 6 (F-hh, F-ff/F-nn, F-gg) — a second phone can be onboarded.

UAT02-02 unit 2: the pack already held one phone's screen size and the home;
the owner's answers for the second phone (its make, its screen size, the same
home) were refused WHOLE, so even the camera make was lost. Owner rulings
20260924: save the safe answers (Q-b); a new screen size is previewed, then
written only with `--add-screen WxH` (Q-c); a home the pack holds is "already
listed". Each case says REPRO (fails on c5b6f99) or GUARD.
"""

import contextlib
import csv
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import photo_onboard_page as op  # noqa: E402

HOME = (10.5, 20.25)
ANSWERS = ("make: Acme Phone 2 = yes\n"
           "screen: 1179x2556 = Phone 2\n"
           "home: A = Riverside live\n")


def setup(tmp):
    """A collection with one bound unit and a pack that already holds the
    first phone's size, its make and the home."""
    pack = tmp / "pack"
    shutil.copytree(HERE.parent / "templates" / "photo-memory" / "_template", pack)
    for leaf in ("photo-profile.json", "photo-entities.json"):
        path = pack / leaf
        path.write_text(path.read_text(encoding="utf-8")
                        .replace("{{SLUG}}", "betauser").replace("{{DISPLAY}}", "Beta"),
                        encoding="utf-8")
    profile = json.loads((pack / "photo-profile.json").read_text(encoding="utf-8"))
    profile["own_camera_makes"] = ["Othermake"]
    profile["screen_dims"] = [{"model": "Phone 1", "dims": [1080, 2280]}]
    profile["home_locations"] = [{"id": "home-01", "label": "Riverside",
                                  "lat": HOME[0], "lon": HOME[1]}]
    (pack / "photo-profile.json").write_text(json.dumps(profile, indent=2),
                                             encoding="utf-8")
    work = tmp / "Working Files"
    unit = work / "phone-2"
    unit.mkdir(parents=True)
    (work / "collection.json").write_text(json.dumps({"owner": "betauser"}))
    with open(unit / "manifest.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["SourceFile", "FileName", "FileType",
                                           "Make", "Model", "ImageWidth",
                                           "ImageHeight"])
        w.writeheader()
        for i in range(3):
            w.writerow({"SourceFile": "/x/IMG_%d.PNG" % i, "FileName": "IMG_%d.PNG" % i,
                        "FileType": "PNG", "Make": "-", "Model": "-",
                        "ImageWidth": "1179", "ImageHeight": "2556"})
        w.writerow({"SourceFile": "/x/IMG_9.HEIC", "FileName": "IMG_9.HEIC",
                    "FileType": "HEIC", "Make": "Acme", "Model": "Phone 2",
                    "ImageWidth": "4032", "ImageHeight": "3024"})
    answers = unit / "onboard" / "answers.txt"
    answers.parent.mkdir()
    answers.write_text(ANSWERS, encoding="utf-8")
    coords = unit / "onboard" / "coords.txt"
    coords.write_text("A  %s, %s  9 day(s)\n" % HOME, encoding="utf-8")
    return pack, answers, coords


def run(*argv):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = op.main([str(a) for a in argv])
    except SystemExit as err:
        return 2, buf.getvalue() + str(err)
    return code, buf.getvalue()


def profile_of(pack):
    return json.loads((pack / "photo-profile.json").read_text(encoding="utf-8"))


def case_the_safe_answers_are_written(tmp):
    """REPRO F-hh — c5b6f99 refused the whole write: the make was lost too."""
    pack, answers, coords = setup(tmp)
    code, said = run("apply", answers, "--write-pack", pack, "--coords-in", coords)
    got = profile_of(pack)
    assert "Acme" in got["own_camera_makes"] and "Othermake" in got["own_camera_makes"], \
        (got["own_camera_makes"], said)
    assert got["screen_dims"] == [{"model": "Phone 1", "dims": [1080, 2280]}], got["screen_dims"]
    assert code == 1 and "--add-screen 1179x2556" in said, (code, said)


def case_a_home_the_pack_holds_is_already_listed(tmp):
    """REPRO F-ff — the same home under another word was a clash."""
    pack, answers, coords = setup(tmp)
    code, said = run("apply", answers, "--write-pack", pack, "--coords-in", coords)
    assert "already listed" in said and "Riverside (home-01)" in said, said
    assert len(profile_of(pack)["home_locations"]) == 1


def case_add_screen_writes_the_union(tmp):
    """REPRO F-hh — the owner's yes adds the second size, keeps the first."""
    pack, answers, coords = setup(tmp)
    code, said = run("apply", answers, "--write-pack", pack, "--coords-in", coords,
                     "--add-screen", "2556x1179")
    got = profile_of(pack)["screen_dims"]
    assert got == [{"model": "Phone 1", "dims": [1080, 2280]},
                   {"model": "Phone 2", "dims": [1179, 2556]}], got
    assert code == 0, (code, said)


def case_the_dry_run_says_what_each_answer_does(tmp):
    """REPRO F-gg + Q-c — per-key lines and what the new size moves, per bound
    unit, with nothing written."""
    pack, answers, coords = setup(tmp)
    before = (pack / "photo-profile.json").read_bytes()
    code, said = run("apply", answers, "--pack", pack, "--coords-in", coords)
    assert (pack / "photo-profile.json").read_bytes() == before
    for want in ("DRY RUN", "merge", "already listed", "refuse",
                 "NEW screen size 1179x2556 MOVES FILES",
                 "phone-2", "3 still(s) -> screenshots", "stay where they are"):
        assert want in said, (want, said)


def case_the_sheet_does_not_ask_a_listed_home_or_size(tmp):
    """REPRO F-ff / F-nn — the page and sheet re-asked the pack's own home."""
    profile = {"home_locations": [{"id": "home-01", "label": "Riverside",
                                   "lat": HOME[0], "lon": HOME[1]}],
               "screen_dims": [[1080, 2280]]}
    rows = [{"SourceFile": "/x/%d.jpg" % d, "GPSPosition": "%s %s" % HOME,
             "DateTimeOriginal": "2026:03:%02d 21:00:00" % d, "Make": "Acme",
             "Model": "P", "FileType": "JPEG"} for d in range(1, 10)]
    op.arm_evidence_filter(True)
    homes = op.homes_section([("u", rows)], with_coords=False, profile=profile)
    assert homes["rows"] == [] and homes["already_listed"] == ["Riverside (home-01)"], homes
    census = {"screen_size_candidates": [{"dims": [1080, 2280], "files": 4,
                                          "warning": None, "model": None,
                                          "named_like_screenshots": 0}],
              "screen_sizes_below_threshold": 0, "screenshots_by_filename": 0}
    screens = op.screens_section([], census, profile)
    assert screens["candidates"] == [] and screens["already_listed"] == ["1080x2280"], screens


CASES = [
    ("F-hh: the safe answers are written (REPRO)", case_the_safe_answers_are_written),
    ("F-ff: a home the pack holds is already listed (REPRO)",
     case_a_home_the_pack_holds_is_already_listed),
    ("F-hh: --add-screen writes the union (REPRO)", case_add_screen_writes_the_union),
    ("F-gg: the dry run says what each answer does (REPRO)",
     case_the_dry_run_says_what_each_answer_does),
    ("F-nn: the sheet does not ask a listed home or size (REPRO)",
     case_the_sheet_does_not_ask_a_listed_home_or_size),
]


def main():
    passed = 0
    for name, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="second_phone_case_"))
        try:
            fn(tmp)
            print(f"  ok    {name}")
            passed += 1
        except Exception as e:                            # noqa: BLE001
            print(f"  FAIL  {name}: {type(e).__name__}: {str(e)[:600]}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{passed}/{len(CASES)} second_phone cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
