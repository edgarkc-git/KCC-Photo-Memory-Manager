#!/usr/bin/env python3
"""Cases for the file-order day proposer (A38).

The rule is signed (Non-EXIF SPEC v1.2, D-N12) and its headline number is a
POSITIVE CONTROL, not an agreement rate -- so the important cases here are the
ones where the proposer must DECLINE. Offering a day is cheap; declining
correctly is what keeps a mis-filed memory out of the owner's archive.

  python3 tests/adjacency_cases.py [-v]

Exit 0 = pass. No owner data is read; every row is written out here.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import photo_adjacency as A  # noqa: E402

FOLDER = "/vol/dump"


def r(name, day=None, folder=FOLDER):
    """One manifest row. `day` None = the undated file we are placing."""
    return {"SourceFile": f"{folder}/{name}", "FileName": name,
            "DateTimeOriginal": f"{day} 12:00:00".replace("-", ":") if day else "-",
            "CreateDate": "-", "FileType": "JPEG"}


def verdict(rows, target):
    out = A.propose(A.file_order(rows))
    return out[f"{FOLDER}/{target}"]


def case_agreeing_neighbours_propose(_):
    v = verdict([r("a.jpg", "2026-05-01"), r("b.jpg"), r("c.jpg", "2026-05-01")], "b.jpg")
    assert v["verdict"] == "agree", v
    assert v["day"] == "2026-05-01", v


def case_disagreeing_neighbours_decline(_):
    """Two anchors that name different days settle nothing. Picking the nearer
    one would be inventing a tiebreak nobody signed."""
    v = verdict([r("a.jpg", "2026-05-01"), r("b.jpg"), r("c.jpg", "2026-05-09")], "b.jpg")
    assert v["verdict"] == "disagree", v
    assert v["day"] is None, v


def case_one_sided_anchor_declines(_):
    """The measured shape of a LINE album: one contiguous block whose middle
    files see only other undated files on one side. A single anchor is not
    agreement, and this is exactly where a confident guess is most often
    wrong -- 829 of 1,941 shared photos in the corpus land here."""
    v = verdict([r("a.jpg", "2026-05-01"), r("b.jpg"), r("c.jpg"), r("d.jpg")], "c.jpg")
    assert v["verdict"] == "no_anchor_one_side", v
    assert v["day"] is None, v


def case_no_anchor_at_all(_):
    v = verdict([r("a.jpg"), r("b.jpg"), r("c.jpg")], "b.jpg")
    assert v["verdict"] == "no_anchor_either_side", v


def case_reaches_past_undated_files(_):
    """The nearest DATED file, not the adjacent file. An IM burst is several
    files long, so a proposer that gave up at the first undated neighbour
    would decline on the whole population it exists for."""
    rows = [r("a.jpg", "2026-05-01"), r("b.jpg"), r("c.jpg"), r("d.jpg"),
            r("e.jpg", "2026-05-01")]
    v = verdict(rows, "c.jpg")
    assert v["verdict"] == "agree", v
    assert v["distance_before"] == 2 and v["distance_after"] == 2, v


def case_folder_boundary_is_not_a_neighbour(_):
    """A manifest is written in exiftool's traversal order, which interleaves
    directories. A file in another folder is not a neighbour in any sense the
    owner would recognise, so it must not anchor."""
    rows = [r("z.jpg", "2026-05-01", folder="/vol/other"),
            r("b.jpg"),
            r("z2.jpg", "2026-05-01", folder="/vol/other2")]
    v = verdict(rows, "b.jpg")
    assert v["verdict"] == "no_anchor_either_side", v


def case_sorted_by_filename_not_manifest_order(_):
    """Order comes from the filename, not from the row order it was scanned
    in: the burst is a filename sequence."""
    rows = [r("c.jpg", "2026-05-01"), r("a.jpg", "2026-05-01"), r("b.jpg")]
    v = verdict(rows, "b.jpg")
    assert v["verdict"] == "agree", v


def case_control_scores_a_clean_run(_):
    """The positive control on a corpus where every neighbour agrees: it must
    report 100% and must actually have offered something -- a run that
    declined everything would otherwise read as a perfect score."""
    rows = A.file_order([r(f"f{i:02}.jpg", "2026-05-01") for i in range(10)])
    c = A.control(rows)
    assert c["accuracy_pct"] == 100.0, c
    assert c["offered"] >= 8, c


def case_control_catches_a_wrong_proposal(_):
    """…and it must be able to score a MISS. A file that sits between two
    days genuinely gets the wrong day, and the control has to count it --
    otherwise the 97.5% means nothing."""
    rows = A.file_order(
        [r("a.jpg", "2026-05-01"), r("b.jpg", "2026-05-01"),
         r("c.jpg", "2026-05-05"),                       # the odd one out
         r("d.jpg", "2026-05-01"), r("e.jpg", "2026-05-01")])
    c = A.control(rows)
    assert c["wrong"] >= 1, c
    assert c["accuracy_pct"] < 100.0, c


def case_dated_rows_get_no_proposal(_):
    """The stage places files that have no date. A file with one is not its
    business, and quietly re-dating it would be the failure the whole SPEC is
    written against."""
    out = A.propose(A.file_order(
        [r("a.jpg", "2026-05-01"), r("b.jpg"), r("c.jpg", "2026-05-01")]))
    assert f"{FOLDER}/a.jpg" not in out, out.keys()
    assert f"{FOLDER}/b.jpg" in out, out.keys()


def case_proposal_carries_its_evidence(_):
    """A proposal the owner cannot check is not reviewable. Both anchors and
    both distances travel with it."""
    v = verdict([r("a.jpg", "2026-05-01"), r("b.jpg"), r("c.jpg", "2026-05-01")], "b.jpg")
    for k in ("before", "after", "distance_before", "distance_after", "source"):
        assert v.get(k) is not None, (k, v)


CASES = [v for k, v in sorted(globals().items()) if k.startswith("case_")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failures = []
    for fn in CASES:
        try:
            fn(None)
            if args.verbose:
                print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failures.append(fn.__name__)
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:                            # noqa: BLE001
            failures.append(fn.__name__)
            print(f"  ERROR {fn.__name__}: {e!r}")
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} adjacency cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
