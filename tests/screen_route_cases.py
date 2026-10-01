#!/usr/bin/env python3
"""Card 7 (F-01, F-13) — Card 6's screen-size route, finished.

UAT02-03: the Q-c move preview could not count when the sheet was written
where photo-init's own example puts it (a folder BESIDE `Working Files/`), and
the post-copy screen-size banner told the agent to hand-edit the pack. Owner
20260924: F-01 counts from the sheet's own work dirs; F-13 is reworded only,
with no new way to add a size. Each case says REPRO (fails on 073050f) or GUARD.
"""

import contextlib
import csv
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import photo_onboard_page as op  # noqa: E402
import photo_profile  # noqa: E402
import photo_run  # noqa: E402


def make_pack(root, owner="betauser"):
    pack = root / owner
    shutil.copytree(HERE.parent / "templates" / "photo-memory" / "_template", pack)
    for leaf in ("photo-profile.json", "photo-entities.json"):
        path = pack / leaf
        path.write_text(path.read_text(encoding="utf-8")
                        .replace("{{SLUG}}", owner).replace("{{DISPLAY}}", "Beta"),
                        encoding="utf-8")
    profile = json.loads((pack / "photo-profile.json").read_text(encoding="utf-8"))
    profile["screen_dims"] = [{"model": "Phone 1", "dims": [1080, 2280]}]
    (pack / "photo-profile.json").write_text(json.dumps(profile, indent=2),
                                             encoding="utf-8")
    return pack


def make_unit(work, name, owner="betauser"):
    """A bound work dir holding three no-camera stills at a new screen size."""
    unit = work / name
    unit.mkdir(parents=True)
    (work / "collection.json").write_text(json.dumps({"owner": owner}))
    with open(unit / "manifest.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["SourceFile", "FileName", "FileType",
                                           "Make", "Model", "ImageWidth",
                                           "ImageHeight"])
        w.writeheader()
        for i in range(3):
            w.writerow({"SourceFile": "/x/IMG_%d.PNG" % i,
                        "FileName": "IMG_%d.PNG" % i, "FileType": "PNG",
                        "Make": "-", "Model": "-",
                        "ImageWidth": "1179", "ImageHeight": "2556"})
    return unit


def run(*argv):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = op.main([str(a) for a in argv])
    except SystemExit as err:
        return 2, buf.getvalue() + str(err)
    return code, buf.getvalue()


def answered_sheet(unit, pack, out_dir):
    """`sheet` exactly as photo-init's example runs it, then the owner's answer."""
    code, said = run("sheet", unit, "--out-dir", out_dir, "--profile", pack)
    assert code == 0, said
    answers = out_dir / "answers.txt"
    text = answers.read_text(encoding="utf-8").replace(
        ">>> screen: 1179x2556 =\n", ">>> screen: 1179x2556 = Phone 2\n")
    assert "screen: 1179x2556 = Phone 2" in text, text
    answers.write_text(text, encoding="utf-8")
    return answers


def case_the_skill_layout_counts(tmp):
    """REPRO F-01 — a sheet in `<workspace>/onboard/`, beside `Working Files/`,
    printed 'no collection.json found above' and counted nothing."""
    pack = make_pack(tmp)
    unit = make_unit(tmp / "Working Files", "phone-2")
    answers = answered_sheet(unit, pack, tmp / "onboard")
    code, said = run("apply", answers, "--pack", pack)
    assert "NEW screen size 1179x2556 MOVES FILES. Show the owner this" in said, said
    assert "phone-2" in said and "3 still(s) -> screenshots" in said, said
    assert "NOT COUNTED" not in said, said


def case_uncounted_is_refused_not_shown(tmp):
    """REPRO F-01 — with no collection to count against, the preview still
    said 'Show the owner this, and add it only after their yes'."""
    pack = make_pack(tmp)
    answers = tmp / "loose" / "answers.txt"
    answers.parent.mkdir()
    answers.write_text("screen: 1179x2556 = Phone 2\n", encoding="utf-8")
    code, said = run("apply", answers, "--pack", pack)
    assert "NOT COUNTED" in said, said
    assert "Show the owner" not in said, said
    assert 'photo_onboard_page.py" sheet "<work dir>"' in said, said  # H-C C4: full path


def case_mixed_collections_are_refused(tmp):
    """GUARD F-01 — a sheet whose work dirs sit in two collections counts
    neither."""
    a = make_unit(tmp / "one" / "Working Files", "u1")
    b = make_unit(tmp / "two" / "Working Files", "u2")
    where, why = op.bound_collection(tmp, [str(a), str(b)])
    assert where is None and "2 different collections" in why, (where, why)


def case_the_stamp_uses_the_one_lookup(tmp):
    """GUARD F-01 — the stamped work dir resolves through
    photo_profile.find_collection(), not a folder-name probe."""
    unit = make_unit(tmp / "Anything", "u1")
    where, why = op.bound_collection(tmp / "elsewhere" / "answers.txt", [str(unit)])
    assert why is None, why
    assert Path(where) == photo_profile.find_collection(str(unit))[1].parent


def case_a_stamped_sheet_never_counts_a_stranger(tmp):
    """REPRO F-01 (363e37a) — a sheet whose recorded work dir has no
    collection, kept under ANOTHER collection's folder, counted that one."""
    pack = make_pack(tmp)
    lost = tmp / "lost" / "u1"
    lost.mkdir(parents=True)
    stranger = make_unit(tmp / "other" / "Working Files", "stranger")
    answers = stranger / "onboard" / "answers.txt"
    answers.parent.mkdir()
    answers.write_text("workdirs: %s\nscreen: 1179x2556 = Phone 2\n"
                       % json.dumps([str(lost)]), encoding="utf-8")
    code, said = run("apply", answers, "--pack", pack)
    assert "NOT COUNTED" in said and "stranger " not in said, said


def checkpoint(tmp, moved):
    plan = tmp / "plan"
    plan.mkdir()
    (plan / photo_run.SCREEN_PROPOSALS_NAME).write_text(json.dumps({
        "proposed_screen_dims": [{"model": None, "dims": [1080, 1462],
                                  "files_at_this_size": 1,
                                  "proven_by": "Screenshot_1.png"}],
        "moved_to_to_be_checked": moved}))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        photo_run.print_screen_checkpoint(tmp)
    return buf.getvalue()


def case_the_banner_never_says_hand_edit(tmp):
    """REPRO F-13 — the banner said to add the sizes to photo-profile.json."""
    said = checkpoint(tmp, {"1": 0})
    assert "photo-profile.json" not in said and "--add-screen" not in said, said
    assert "NOT added" in said, said


def case_nothing_moved_says_so(tmp):
    """REPRO F-13 — moved 0 (the s24u case): no action is needed."""
    said = checkpoint(tmp, {"1": 0, "2": 0})
    assert "Nothing moved" in said and "No action is needed" in said, said


def case_files_moved_says_how_many(tmp):
    """REPRO F-13 — moved > 0: the count, and no command to add the size."""
    said = checkpoint(tmp, {"1": 2, "2": 3})
    assert "5 file(s) at these sizes went to the to-be-checked bucket" in said, said
    # Card 9: the sheet now asks these sizes, so "not possible from here yet"
    # became the route itself.
    assert "Nothing moved" not in said and "not possible" not in said, said
    assert "make the onboarding sheet for this work dir" in said, said


def case_the_plan_page_never_says_write_it_in(tmp):
    """REPRO F-13 — the plan page said to confirm the size and re-plan."""
    intro = photo_profile.messages({"language": "en"})["plan_screen_candidate_intro"]
    assert "re-plan" not in intro and "not added to the pack" in intro, intro
    # every language table says it: the same `{bucket}` pointer twice
    for lang, table in photo_profile.MESSAGE_VOCAB.items():
        assert table["plan_screen_candidate_intro"].count("{bucket}") == 2, lang


CASES = [
    ("F-01: the SKILL layout counts (REPRO)", case_the_skill_layout_counts),
    ("F-01: an uncounted preview is refused, not shown (REPRO)",
     case_uncounted_is_refused_not_shown),
    ("F-01: mixed collections are refused (GUARD)", case_mixed_collections_are_refused),
    ("F-01: the stamp uses the one lookup (GUARD)", case_the_stamp_uses_the_one_lookup),
    ("F-01: a stamped sheet never counts a stranger (REPRO)",
     case_a_stamped_sheet_never_counts_a_stranger),
    ("F-13: the banner never says hand-edit (REPRO)", case_the_banner_never_says_hand_edit),
    ("F-13: nothing moved says so (REPRO)", case_nothing_moved_says_so),
    ("F-13: files moved says how many (REPRO)", case_files_moved_says_how_many),
    ("F-13: the plan page never says write it in (REPRO)",
     case_the_plan_page_never_says_write_it_in),
]


def main():
    passed = 0
    for name, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="screen_route_case_"))
        try:
            fn(tmp)
            print(f"  ok    {name}")
            passed += 1
        except Exception as e:                            # noqa: BLE001
            print(f"  FAIL  {name}: {type(e).__name__}: {str(e)[:600]}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{passed}/{len(CASES)} screen_route cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
