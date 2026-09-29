#!/usr/bin/env python3
"""A38 — propose a DAY for a file that carries no date, from its neighbours.

The problem this exists for: a photo that arrived through a messenger has no
GPS (0 of 2,923 measured), no camera tags, and essentially never a date. Two
of the four fields a folder name is built from are gone and cannot be
recovered from the file. It can never FORM a folder; it can only JOIN one.

The signed rule (Non-EXIF SPEC v1.2, D-N12) is that neighbours in file order
propose and VI confirms. An IM download lands as a burst, so a shared file
usually sits between camera photos of the same event in filename order. The
nearest DATED file on each side is read, and if the two agree on a day, that
day is the proposal.

⛔ WHAT THIS DOES NOT DO, and why it stops here:

  * It proposes a DAY, never a destination. In a workdir holding several
    events two folders can share a day, and the day -> folder mapping is not
    specified anywhere yet. Proposing a folder would be inventing a tiebreak
    the owner never signed.
  * It never proposes from ONE side. A single anchor is not agreement, and a
    LINE album arrives as one long contiguous block whose middle files see
    only other LINE files -- 829 of 1,941 shared photos in the measured
    corpus have no camera anchor on one side. Those need VI; this stage says
    so rather than guessing.
  * Agreement is not accuracy. For a shared photo there is no ground truth,
    so the agreement rate is the rate at which this method OFFERS an answer
    confidently, not the rate at which it is right. `--control` measures the
    part that can be measured: it hides a dated camera file's own date and
    checks the proposal against it.

Usage:
  python3 photo_adjacency.py "<Working Files>/202605__"
  python3 photo_adjacency.py "<Working Files>/202605__" --control
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).parent))
from photo_cluster import parse_date  # noqa: E402


def file_order(rows):
    """-> rows sorted the way a burst actually lands.

    Within one folder, by filename; folders kept apart. A manifest is written
    in exiftool's traversal order, which for a recursive scan interleaves
    directories, and neighbours across a directory boundary are not
    neighbours in any sense the owner would recognise.
    """
    def key(r):
        p = PurePosixPath(r.get("SourceFile", ""))
        return (str(p.parent), p.name)
    return sorted(rows, key=key)


def _folder(row):
    return str(PurePosixPath(row.get("SourceFile", "")).parent)


def nearest_dated(rows, i, step):
    """-> (day, distance) of the nearest dated row from i in direction `step`,
    or (None, None). Stops at the folder boundary for the reason in
    file_order(): a neighbour in another folder is not a neighbour."""
    home = _folder(rows[i])
    j, dist = i + step, 1
    while 0 <= j < len(rows):
        if _folder(rows[j]) != home:
            return None, None
        dt = parse_date(rows[j])
        if dt is not None:
            return dt.date().isoformat(), dist
        j += step
        dist += 1
    return None, None


def propose(rows, index=None):
    """-> {SourceFile: proposal} for every undated row (or just `index`).

    A proposal is offered ONLY where both sides carry a date and the two
    agree. Everything else is reported with the reason it could not be
    decided, because those reasons are what tells the owner which files still
    need eyes on them.
    """
    out = {}
    targets = range(len(rows)) if index is None else [index]
    for i in targets:
        row = rows[i]
        if index is None and parse_date(row) is not None:
            continue
        before, d_before = nearest_dated(rows, i, -1)
        after, d_after = nearest_dated(rows, i, +1)
        rec = {"source": row.get("SourceFile"),
               "before": before, "after": after,
               "distance_before": d_before, "distance_after": d_after}
        if before is None and after is None:
            rec.update(day=None, verdict="no_anchor_either_side")
        elif before is None or after is None:
            # Deliberately NOT proposed. One anchor is not agreement, and this
            # is the shape a contiguous IM album makes -- the case where a
            # confident single-sided guess would be wrong most often.
            rec.update(day=None, verdict="no_anchor_one_side")
        elif before == after:
            rec.update(day=before, verdict="agree")
        else:
            rec.update(day=None, verdict="disagree")
        out[row.get("SourceFile")] = rec
    return out


def control(rows):
    """The positive control. Agreement is not accuracy, and for a shared photo
    nothing can measure accuracy -- there is no ground truth. So the method
    itself is measured on the files that DO have a truth: hide a dated camera
    file's own date, propose from its neighbours, and compare.

    ⛔ Read the `correct` rate against `offered`, not against the total: the
    method declining to answer is not the method being wrong."""
    dated = [i for i, r in enumerate(rows) if parse_date(r) is not None]
    tally = Counter()
    for i in dated:
        truth = parse_date(rows[i]).date().isoformat()
        rec = propose(rows, index=i)[rows[i].get("SourceFile")]
        tally[rec["verdict"]] += 1
        if rec["verdict"] == "agree":
            tally["correct" if rec["day"] == truth else "wrong"] += 1
    offered = tally["agree"]
    return {"dated_rows": len(dated), "offered": offered,
            "correct": tally["correct"], "wrong": tally["wrong"],
            "accuracy_pct": round(100 * tally["correct"] / offered, 1) if offered else None,
            "offer_rate_pct": round(100 * offered / len(dated), 1) if dated else None,
            "verdicts": dict(tally)}


def load(workdir):
    manifest = Path(workdir) / "manifest.csv"
    if not manifest.exists():
        sys.exit(f"no manifest: {manifest}")
    with open(manifest, newline="", encoding="utf-8") as f:
        return file_order(list(csv.DictReader(f)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir")
    ap.add_argument("--control", action="store_true",
                    help="measure the method against dated files whose date is hidden")
    args = ap.parse_args()

    rows = load(args.workdir)
    if args.control:
        print(json.dumps(control(rows), indent=1))
        return

    props = propose(rows)
    counts = Counter(p["verdict"] for p in props.values())
    report = {
        "workdir": str(args.workdir),
        "undated_rows": len(props),
        "counts": dict(counts),
        "proposed": counts["agree"],
        # ⛔ A day, not a folder. Placement needs the day -> folder mapping,
        # which is undefined for a workdir holding several events, and VI for
        # everything this stage declined.
        "proposals": [p for p in props.values() if p["verdict"] == "agree"],
        "undecided": [p for p in props.values() if p["verdict"] != "agree"],
    }
    out = Path(args.workdir) / "no-date-adjacency.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("workdir", "undated_rows", "counts", "proposed")},
                     indent=1, ensure_ascii=False))
    print(f"\n-> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
