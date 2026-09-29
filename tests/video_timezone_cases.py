#!/usr/bin/env python3
"""U3-23 cases — a video's UTC stamp must not be read as local time.

A QuickTime `CreateDate` is UTC and carries no zone. `parse_date()` read it as
local, so every video was dated by the owner's own UTC offset. Measured on a
real dump: 25 of 25 videos exactly 8 h out against a stills control of 301 of
302 at 0 h — the video path only, not clock skew. On the full dump 2 of 57
land on the wrong calendar DAY, which is a different folder.

⛔ THE OFFSET IS NEVER A CONSTANT AND NEVER THE MACHINE'S. Measured on one
330-file dump: the stills declared TWO offsets — `+08:00` across it and
`+09:00` for a contiguous week, which is a trip. So a hardcoded offset is
wrong and a single home offset in the owner pack is wrong too, for a whole
week of one dump. This engine ships an overseas-trip type; travel is normal.
⚠️ And it would have been easy to miss: no video fell inside that week, so a
hardcoded +8 reproduces that dump perfectly and is still wrong.

Two sources, in order, because vendors differ and neither alone is "how
videos work" — measured 22 of 22 on an Apple dump and 0 of 25 on a Samsung
one:
  1. the video's own `Keys:CreationDate`, local time carrying its offset;
  2. failing that, `OffsetTimeOriginal` from the nearest still in the dump.
⛔ Neither available -> the row is left EXACTLY as it was and flagged.

  python3 tests/video_timezone_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))
import golden_replay  # noqa: E402
import photo_cluster  # noqa: E402
import photo_scan  # noqa: E402


CASES = []


class Skipped(Exception):
    """No fixture set to read. Neither a pass nor a failure — printed with its
    reason and counted apart, the photo_memory_cases.py rule."""


def golden_manifest():
    """-> the frozen tier3cat manifest, resolved by the replay harness's ONE
    resolver (--fixtures > $PHOTO_GOLDEN_FIXTURES > tests/golden). Raises
    Skipped when it is not there."""
    path = golden_replay.fixture_root() / "tier3cat" / "input" / "manifest.csv"
    if not path.is_file():
        raise Skipped(f"no fixture at {path} — point "
                      f"${golden_replay.ENV_FIXTURES} at a fixture set")
    return path


def case(fn):
    CASES.append(fn)
    return fn


def still(name, shot, offset="+08:00"):
    return {"SourceFile": f"/d/{name}", "FileName": name, "FileType": "JPEG",
            "DateTimeOriginal": shot, "CreateDate": shot,
            "OffsetTimeOriginal": offset, "CreationDate": "-"}


def video(name, utc, creation="-"):
    """⛔ `-` is exiftool's ABSENT marker (`-f` is passed), which is what a
    real manifest holds — not an empty string."""
    return {"SourceFile": f"/d/{name}", "FileName": name, "FileType": "MP4",
            "DateTimeOriginal": "-", "CreateDate": utc,
            "OffsetTimeOriginal": "-", "CreationDate": creation}


@case
def the_fixture_rows_carry_the_columns_a_real_manifest_has():
    """LL-PHO-176's cheap check, made mechanical: the constructed rows must
    use the same field names a scan actually writes, or every case below is
    testing a shape the pipeline never produces."""
    real = set(next(csv.reader(open(golden_manifest(), encoding="utf-8"))))
    built = set(still("a.jpg", "2024:10:03 09:58:39"))
    missing = built - real - {"OffsetTimeOriginal", "CreationDate"}
    return not missing, f"fields not in a real manifest: {sorted(missing)}"


@case
def a_video_takes_the_offset_a_nearby_still_declares():
    """REPRODUCTION. The Samsung path: no `CreationDate` on the file, so the
    offset comes from a still an hour away. 02:00 UTC at +08:00 is 10:00."""
    rows = [still("s.jpg", "2024:10:03 09:00:00", "+08:00"),
            video("v.mp4", "2024:10:03 02:00:25")]
    dated, undated = photo_scan.local_video_dates(rows)
    return (dated == 1 and not undated
            and rows[1][photo_scan.DERIVED_LOCAL] == "2024:10:03 10:00:25"), \
        f"dated={dated}, undated={undated}, row={rows[1].get(photo_scan.DERIVED_LOCAL)}"


@case
def the_files_own_creation_date_beats_a_neighbours_offset():
    """GUARD — the ORDER is the point. Apple states local time with its
    offset on the file itself. ⛔ Inferring from a neighbour when the file
    says so would prefer a guess to a declaration; here the neighbour would
    give a different answer, so the case can tell them apart."""
    rows = [still("s.jpg", "2026:05:28 07:00:00", "+01:00"),
            video("v.mov", "2026:05:27 23:13:36",
                  creation="2026:05:28 07:13:36+08:00")]
    dated, _ = photo_scan.local_video_dates(rows)
    return (dated == 1
            and rows[1][photo_scan.DERIVED_LOCAL] == "2026:05:28 07:13:36"), \
        f"got {rows[1].get(photo_scan.DERIVED_LOCAL)!r}, neighbour would say 00:13"


@case
def two_offsets_in_one_dump_are_honoured_separately():
    """⛔ THE CASE THAT KILLS EVERY CONSTANT. One dump, a home block at +08:00
    and a trip week at +09:00 — measured on real data, 218 stills against 87.
    Each video takes the offset of the still nearest IT, so a single dump-wide
    or pack-wide offset cannot reproduce this."""
    rows = [still("home.jpg", "2024:10:03 09:00:00", "+08:00"),
            still("trip.jpg", "2024:10:27 09:00:00", "+09:00"),
            video("vhome.mp4", "2024:10:03 02:00:00"),
            video("vtrip.mp4", "2024:10:27 02:00:00")]
    photo_scan.local_video_dates(rows)
    return (rows[2][photo_scan.DERIVED_LOCAL] == "2024:10:03 10:00:00"
            and rows[3][photo_scan.DERIVED_LOCAL] == "2024:10:27 11:00:00"), \
        f"home={rows[2].get(photo_scan.DERIVED_LOCAL)}, trip={rows[3].get(photo_scan.DERIVED_LOCAL)}"


@case
def a_video_with_no_evidence_is_left_alone_and_flagged():
    """⛔ GUARD. Nothing to derive from -> the row keeps exactly what it had
    and is RETURNED as a flag. Guessing would put a file in a folder for a day
    it was not taken, which is the defect wearing the fix's clothes."""
    rows = [still("far.jpg", "2024:01:01 09:00:00", "+08:00"),
            video("v.mp4", "2024:10:03 02:00:25")]
    dated, undated = photo_scan.local_video_dates(rows)
    return (dated == 0 and undated == ["/d/v.mp4"]
            and photo_scan.DERIVED_LOCAL not in rows[1]), \
        f"dated={dated}, undated={undated}, row={rows[1]}"


@case
def a_still_that_declares_no_offset_is_not_used_as_evidence():
    """GUARD. `-` means the tag is absent. ⛔ Reading absent as a value is the
    mistake that once turned a 1,475-file finding into a zero."""
    rows = [still("s.jpg", "2024:10:03 09:00:00", "-"),
            video("v.mp4", "2024:10:03 02:00:25")]
    dated, undated = photo_scan.local_video_dates(rows)
    return (dated == 0 and undated == ["/d/v.mp4"]), f"{dated}, {undated}"


@case
def stills_are_never_given_a_derived_date():
    """GUARD. A still's `DateTimeOriginal` is already local. ⛔ A fix that
    shifted stills too would move every dated file in every dump."""
    rows = [still("s.jpg", "2024:10:03 09:00:00"),
            video("v.mp4", "2024:10:03 02:00:25")]
    photo_scan.local_video_dates(rows)
    return photo_scan.DERIVED_LOCAL not in rows[0], f"{rows[0]}"


# ---------------------------------------------------------------------------
# what must not have moved
# ---------------------------------------------------------------------------

@case
def parse_date_prefers_the_derived_local_time():
    """The wire between the two halves: deriving it is useless if the
    resolver every stage reads through does not prefer it."""
    row = video("v.mp4", "2024:10:03 02:00:25")
    row[photo_scan.DERIVED_LOCAL] = "2024:10:03 10:00:25"
    got = photo_cluster.parse_date(row)
    return got.strftime("%Y:%m:%d %H:%M:%S") == "2024:10:03 10:00:25", str(got)


@case
def a_manifest_without_the_column_dates_exactly_as_before():
    """⛔ THE GUARD THAT PROTECTS EVERY EXISTING WORK DIR, and the reason
    `golden_replay` still reproduces. A manifest written before U3-23 has no
    derived column, so `parse_date` falls straight through to the behaviour it
    always had. ⚠️ The consequence is deliberate and must be said rather than
    enjoyed: those videos are NOT re-dated until the dump is re-scanned."""
    rows = list(csv.DictReader(open(golden_manifest(), encoding="utf-8")))
    videos = [r for r in rows if (r.get("FileType") or "").upper() == "MOV"]
    if not videos:
        return False, "no video in the golden manifest to check"
    row = videos[0]
    return (photo_scan.DERIVED_LOCAL not in row
            and photo_cluster.parse_date(row).strftime("%Y:%m:%d %H:%M:%S")
            == row["CreateDate"][:19]), f"{row.get('CreateDate')}"


@case
def the_scan_requests_both_evidence_tags():
    """Neither path can work if the scan never asks exiftool for the tag."""
    return ("OffsetTimeOriginal" in photo_scan.TAGS
            and "CreationDate" in photo_scan.TAGS
            and photo_scan.DERIVED_LOCAL not in photo_scan.TAGS), \
        f"{photo_scan.TAGS}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failures, skipped = [], []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
        try:
            ok, detail = fn()
        except Skipped as why:
            skipped.append(fn.__name__)
            print(f"  skip  {fn.__name__.replace('_', ' ').ljust(width)}   {why}")
            continue
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  "
                  f"{fn.__name__.replace('_', ' ').ljust(width)}"
                  + (f"   {detail}" if not ok else ""))
    ran = len(CASES) - len(skipped)
    print(f"\n{ran - len(failures)}/{ran} video-timezone cases passed"
          + (f", {len(skipped)} skipped" if skipped else "")
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
