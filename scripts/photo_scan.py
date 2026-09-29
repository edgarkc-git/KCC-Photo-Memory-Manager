#!/usr/bin/env python3
"""photo-scan Stage 1 — bulk EXIF scan of one source folder into manifest.csv.

Strictly read-only on the source folder. Writes into the work dir only:
  manifest.csv        one row per media file (AAE sidecars excluded)
  scan-summary.json   counts for sanity checking and for photo_cluster.py
  scan-errors.log     exiftool warnings/errors (empty file = clean scan)

.AAE sidecars are ignored entirely (D4): counted in the
summary but never written to the manifest. Detection is by exiftool FileType,
not filename extension — some sidecars carry .MP4 names.

`._*` AppleDouble sidecars are excluded too, and counted the same way. Every
exclusion is named in the summary so its arithmetic closes:
`total_files_seen == main_files + aae_ignored + appledouble_ignored`. A count
that does not close is the one thing an owner can check this stage against —
they count the folder in Finder — and an unnamed exclusion turns that check
into an unexplained shortfall.

--verify re-reads an existing manifest instead of scanning, and reports which
rows still point at a file that is there (A41). A manifest goes stale silently:
the owner reorganises the drive — splitting a trip into leg sub-folders, or
renaming one — and every path recorded before that reorganisation now names
nothing. Nothing downstream notices, because every stage reads the manifest and
none of them opens the file until far too late.

Read-only and REPORT-ONLY, deliberately. It never rewrites the manifest and
never re-scans: regenerating a manifest reflows batches.json, and whether that
should happen is the owner's call, not a repair this stage may take on its own.

Usage:
  python3 photo_scan.py "/Volumes/EXAMPLE_DRIVE/.../202401" \
      --workdir "/path/to/Working Files/202401"
  python3 photo_scan.py --verify --workdir "/path/to/Working Files/202401"
If --workdir is omitted it defaults to <--workdir-root>/<source basename>.
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import photo_exiftool  # noqa: E402
import photo_profile  # noqa: E402
from photo_cluster import parse_gps  # noqa: E402
from photo_quickscan import JUNK, PHOTO_EXT, VIDEO_EXT  # noqa: E402

# F04: exit code when exiftool read fewer media files than the folder holds.
PARTIAL_SCAN = 3

TAGS = [
    "FileName", "FileType", "FileSize", "DateTimeOriginal", "CreateDate",
    "OffsetTimeOriginal", "CreationDate",
    "GPSPosition", "Make", "Model", "Software", "ImageWidth", "ImageHeight",
    "Duration", "UserComment",
    # M14 — the filesystem modification stamp, recorded so a no-EXIF VIDEO can
    # be filed under a year. ⛔ Appended, never inserted: nothing reads the
    # manifest positionally, but appending keeps every existing column where
    # it was. ⛔ `FileCreateDate` is deliberately NOT recorded — it is the
    # copy-to-drive stamp (0 of 418 right, measured twice) and a field that is
    # not in the manifest cannot be read for a year by mistake.
    "FileModifyDate",
]

# U3-23. ⛔ NOT an exiftool tag — the one engine-DERIVED column in the
# manifest, and named so a reader can tell. A video's QuickTime `CreateDate`
# is UTC with no zone attached anywhere in the file, so reading it as local
# dated every video by the owner's own UTC offset. Measured on a real dump:
# 25 of 25 videos exactly 8 h out, against a stills control of 301 of 302 at
# 0 h; 2 of 57 on the full dump land on the wrong calendar DAY, which is a
# different folder.
DERIVED_LOCAL = "CreateDateLocal"

# How far from a video the engine will look for a still that declares an
# offset. ⚠️ Wide on purpose, and 24 h is not a guess about photography: a
# video's stamp is UTC while a still's is local, so "nearest in time" is
# compared across a skew of up to the offset itself (≤14 h). A timezone
# changes at travel granularity — days — so a window that absorbs the skew
# and still cannot cross a trip boundary is the right size. Measured: 25 of
# 25 videos found a still inside it, 24 of 25 inside 12 h.
OFFSET_SEARCH_HOURS = 24
ABSENT = ("-", "", "0000:00:00 00:00:00")


def _stamp(value):
    """One exiftool date field -> datetime, or None.

    ⛔ `-` is exiftool's ABSENT marker (`-f` is passed), not a value. Testing
    for an empty string instead reads every missing date as present — a
    mistake that turned a 1,475-file finding into a zero when it was made
    once already."""
    if value in ABSENT or value is None:
        return None
    try:
        return datetime.strptime(str(value)[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _offset_minutes(value):
    """`+08:00` -> 480. -> None when absent or malformed."""
    if not value or value in ABSENT:
        return None
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", str(value).strip())
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    return sign * (int(m.group(2)) * 60 + int(m.group(3)))


def local_video_dates(rows):
    """U3-23 — give each video the local time its UTC stamp stands for.

    -> (how many were dated, [SourceFile of every video left undated]).
    Mutates `rows`, adding `DERIVED_LOCAL` where it can be derived.

    Two sources, in this order, and the order is the point:

      1. the video's OWN `Keys:CreationDate`, which is local time carrying
         its offset. Apple writes it (22 of 22 measured); Samsung does not
         (0 of 25). ⛔ Nothing may be inferred for a file that states this.
      2. failing that, `OffsetTimeOriginal` from the NEAREST STILL IN TIME in
         the same dump — the device's declaration on a neighbouring file.

    ⛔ THE OFFSET IS NEVER A CONSTANT AND NEVER THIS MACHINE'S.
    Measured on one real 330-file dump: 305 of 305 stills carried it, and
    **two different offsets were present** — `+08:00` across the dump and
    `+09:00` for a contiguous week, which is a trip. So a hardcoded offset is
    wrong, and so is a single home offset in the owner pack: both would
    mis-date every video of that week. This engine ships an overseas-trip
    type; travel is the normal case.

    ⚠️ It would have been easy to miss. In that dump no video fell inside the
    trip week, so a hardcoded +8 reproduces it perfectly and is still wrong.

    ⛔ A video with no still in range is LEFT EXACTLY AS IT WAS and returned
    as a flag. Guessing here would put a file in a folder for a day it was
    not taken, which is the defect wearing the fix's clothes."""
    stills, videos = [], []
    dated = 0
    for row in rows:
        shot = _stamp(row.get("DateTimeOriginal"))
        if shot is not None:
            offset = _offset_minutes(row.get("OffsetTimeOriginal"))
            if offset is not None:
                stills.append((shot, offset))
            continue
        made = _stamp(row.get("CreateDate"))
        if made is None:
            continue
        # ⭐ THE FILE'S OWN DECLARATION FIRST, and it is a different tag from
        # the one this function is named for. Apple writes `Keys:CreationDate`
        # as LOCAL time carrying its offset — measured 22 of 22 on an Apple
        # dump, 0 of 25 on a Samsung one, which is why both paths exist and
        # why neither alone is "how videos work". ⛔ Never infer from a
        # neighbour what the file states about itself; the still below is the
        # FALLBACK, not the rule.
        stated = _stamp(row.get("CreationDate"))
        if stated is not None:
            row[DERIVED_LOCAL] = stated.strftime("%Y:%m:%d %H:%M:%S")
            dated += 1
            continue
        videos.append((row, made))
    if not (stills and videos):
        return dated, [r["SourceFile"] for r, _ in videos]

    stills.sort()
    window = timedelta(hours=OFFSET_SEARCH_HOURS)
    undated = []
    for row, made in videos:
        shot, offset = min(stills, key=lambda s: abs(s[0] - made))
        if abs(shot - made) > window:
            undated.append(row["SourceFile"])
            continue
        row[DERIVED_LOCAL] = (made + timedelta(minutes=offset)).strftime(
            "%Y:%m:%d %H:%M:%S")
        dated += 1
    return dated, undated


def run_exiftool(source: Path, recursive: bool):
    # No -fast/-fast2: video CreateDate can sit at the end of the file (L01).
    options = ["-csv", "-n", "-f"]
    if recursive:
        options.append("-r")
    options += [f"-{t}" for t in TAGS]
    proc = photo_exiftool.run(options, [source])
    if proc.returncode != 0 and not proc.stdout:
        sys.exit(f"exiftool failed: {proc.stderr.strip()[:500]}")
    return proc.stdout, proc.stderr


def is_media_name(name):
    """A photo or video by name, the way the folder count and the exiftool
    rows are both judged, so the two counts compare like with like."""
    return (not name.startswith("._")
            and Path(name).suffix.lower().lstrip(".") in PHOTO_EXT | VIDEO_EXT)


def folder_media_names(source: Path, recursive: bool):
    """F04 — the media files the folder itself lists, as case-folded names.

    Read from the directory LISTING, never a per-file stat: the share that
    caused F04 (an exFAT drive served over SMB) answered a per-file query with
    "directory" for every file, while its listing said 131 files. Skips what
    exiftool -r skips: dot-directories."""
    names = []
    for root, dirs, files in os.walk(source):
        dirs[:] = ([] if not recursive else
                   [d for d in dirs if not d.startswith(".")
                    and d.lower() not in JUNK])
        names += [f.casefold() for f in files if is_media_name(f)]
    return names


def unread_media(expected, rows):
    """-> the expected names no exiftool row accounts for."""
    read = Counter(Path(r.get("SourceFile", "")).name.casefold()
                   for r in rows)
    return sorted((Counter(expected) - read).elements())


# ---------------------------------------------------------------- A41 verify

# What a verdict means. `moved` is the one that carries information: the file
# is still on the drive under the same name and the same byte count, just at a
# different path — which is what a leg re-split or a folder rename looks like
# from here. `gone` and `ambiguous` are deliberately NOT merged into it: a
# report that cannot say "I found exactly one candidate" has not found the file,
# and saying so is the whole point of the stage.
VERDICTS = ("present", "moved", "ambiguous", "gone")


def search_roots(rows):
    """-> the directories to look under, derived from the manifest itself.

    The root is the VOLUME, not the folder the row was recorded in. Measured
    on real data, both of the narrower choices are wrong:

      * the row's own folder is the thing that disappears when a trip is
        re-split into leg sub-folders — the commonest cause of staleness here;
      * /Volumes/<disk>/<top> is not enough either, because a manifest can
        record a path under one top-level folder while the files now sit under
        a different one. On this corpus that mis-reported 1,034 files as gone
        when all 1,034 were on the same disk.

    The volume is walked once per run, so widening the root costs one pass,
    not one pass per row.
    """
    roots = set()
    for r in rows:
        src = r.get("SourceFile") or ""
        if not src:
            continue
        parts = Path(src).parts
        # /Volumes/<disk>/<top>/...  -> take <top>, the outermost folder the
        # owner could rename while leaving the file on the same disk.
        if len(parts) > 2 and parts[1] == "Volumes":
            roots.add(Path(*parts[:3]))                    # /Volumes/<disk>
            continue
        # No /Volumes prefix (an internal disk, or a test tree). The row's own
        # parent is NOT usable as the root: renaming that parent is one of the
        # two failures this stage exists to catch, so it is precisely the
        # directory that is gone. Climb to the nearest ancestor that still
        # exists, which for a live drive is one or two levels up.
        anc = Path(src).parent
        while len(anc.parts) > 2 and not anc.is_dir():
            anc = anc.parent
        roots.add(anc)
    # Drop any root contained in another, so a disk is walked once.
    out = []
    for r in sorted(roots, key=lambda p: len(p.parts)):
        if not any(str(r).startswith(str(k) + "/") for k in out):
            out.append(r)
    return out


SKIP_DIRS = (".Spotlight-V100", ".fseventsd", ".Trashes", "$RECYCLE.BIN")


def index_by_name(roots):
    """-> ({filename: [(path, size), ...]}, tally of what the walk left out).

    One walk per root, not one search per missing row. The corpus is ~23k rows
    over two external drives; a per-row search would be quadratic and would
    take longer than the re-scan this stage refuses to do.

    The tally is the reason this returns a pair. Everything skipped below is
    skipped correctly — `._*` AppleDouble sidecars are not media and have been
    excluded at scan since bd1a3b2, and the four system directories are the
    volume's own bookkeeping — but skipping silently is what made this stage's
    output unfalsifiable. `present` and `rows` are both derived from the
    manifest, so they agree with each other whatever the drive holds; the
    reader's only independent check is to count the folder, and that count is
    larger by however many entries were quietly dropped. From outside, a
    correct exclusion and a manifest that lost photos look identical. So the
    walk counts what it drops and the report says so, which turns a bare ratio
    into an arithmetic the reader can check.
    """
    idx = {}
    excluded = {"appledouble": 0, "system_dirs": 0, "unreadable": 0}
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            excluded["system_dirs"] += sum(1 for d in dirnames if d in SKIP_DIRS)
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn.startswith("._"):
                    excluded["appledouble"] += 1
                    continue
                fp = Path(dirpath) / fn
                try:
                    size = fp.stat().st_size
                except OSError:
                    excluded["unreadable"] += 1
                    continue
                idx.setdefault(fn, []).append((str(fp), size))
    return idx, excluded


def classify_row(row, idx):
    """-> (verdict, candidate path or None).

    Size is matched as well as name because a name alone is not identity: a
    dump folder re-split into legs keeps both, while an unrelated IMG_1234.JPG
    from another phone shares only the name. Where the manifest recorded no
    usable size the match falls back to the name, and the verdict is reported
    the same way — the caller sees the candidate and can judge it.
    """
    src = row.get("SourceFile") or ""
    if src and os.path.exists(src):
        return "present", None
    name = Path(src).name
    cands = idx.get(name, [])
    if not cands:
        return "gone", None
    try:
        want = int(row.get("FileSize") or 0)
    except (TypeError, ValueError):
        want = 0
    if want:
        sized = [c for c in cands if c[1] == want]
        if sized:
            cands = sized
    if len(cands) == 1:
        return "moved", cands[0][0]
    return "ambiguous", cands[0][0]


def verify_main(args):
    if not args.workdir:
        sys.exit("--verify needs --workdir (the dir holding manifest.csv)")
    workdir = Path(args.workdir)
    manifest = workdir / "manifest.csv"
    if not manifest.exists():
        sys.exit(f"no manifest to verify: {manifest}")

    with open(manifest, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"manifest is empty: {manifest}")

    roots = search_roots(rows)
    # Stop rather than report a clean bill of health off an unmounted disk.
    # Pitfall 4: an external drive that is not mounted makes every row read as
    # missing, and this stage would otherwise print that as a 100% failure --
    # the single most misleading thing it could say.
    missing_roots = [r for r in roots if not r.is_dir()]
    if missing_roots and len(missing_roots) == len(roots):
        sys.exit("cannot verify: none of the manifest's source volumes are "
                 "mounted -- mount them and re-run:\n  "
                 + "\n  ".join(str(r) for r in missing_roots))

    idx, excluded = index_by_name(roots)
    results = {v: [] for v in VERDICTS}
    for row in rows:
        verdict, cand = classify_row(row, idx)
        results[verdict].append({"source": row.get("SourceFile"),
                                 "found_at": cand})

    counts = {v: len(results[v]) for v in VERDICTS}
    stale = len(rows) - counts["present"]
    indexed = sum(len(v) for v in idx.values())
    report = {
        "manifest": str(manifest),
        "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "rows": len(rows),
        "search_roots": [str(r) for r in roots],
        "unreachable_roots": [str(r) for r in missing_roots],
        "counts": counts,
        "stale_pct": round(100 * stale / len(rows), 1),
        # What the ratio above was measured against. Without it `present` and
        # `rows` are two numbers derived from the same manifest, so they agree
        # with each other whatever the drive holds, and the reader's only
        # independent check -- counting the folder -- disagrees for reasons
        # the report does not mention.
        "indexed": {
            "files": indexed,
            "excluded": excluded,
            "entries_under_roots": indexed + excluded["appledouble"]
                                   + excluded["unreadable"],
            "note": ("`files` is what a directory listing of the search roots "
                     "would show MINUS `excluded`: `._*` AppleDouble sidecars "
                     "(not media, excluded at scan too, so a manifest never "
                     "held them), files that could not be stat()ed, and "
                     "anything under the volume's own system directories. A "
                     "Finder count larger than `rows` by about `appledouble` "
                     "is the expected, correct case — not missing photos. "
                     "`files` counts the whole search root, which is the "
                     "VOLUME: it is a superset of this dump and is not "
                     "expected to equal `rows`."),
        },
        # Only the actionable rows are listed. `present` is the bulk and
        # naming each one would bury the finding in its own output.
        "moved": results["moved"],
        "ambiguous": results["ambiguous"],
        "gone": results["gone"],
    }
    (workdir / "manifest-verify.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({k: report[k] for k in
                      ("manifest", "rows", "counts", "stale_pct",
                       "unreachable_roots", "indexed")}, indent=1,
                     ensure_ascii=False))
    # Printed on every run, clean ones included: a ratio that only explains
    # itself when something is wrong is a ratio nobody can check when it says
    # everything is fine, which is the run this stage is actually used on.
    print(f"\n{counts['present']} of {len(rows)} manifest rows still point at "
          f"a file. Those are MEDIA rows, not directory entries: "
          f"{excluded['appledouble']} AppleDouble sidecar(s) under the search "
          f"roots are excluded here and were excluded at scan, so a folder "
          f"listing is expected to be larger by roughly that many.")
    if stale:
        print(f"\n{stale} of {len(rows)} rows no longer point at a file "
              f"-> {workdir / 'manifest-verify.json'}", file=sys.stderr)
        print("This manifest is STALE. Re-scanning would reflow batches.json, "
              "so it is the owner's call, not this stage's.", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", nargs="?",
                    help="source folder to scan (read-only). Optional with "
                         "--verify, which reads the roots off the manifest.")
    ap.add_argument("--workdir", help="output dir for manifest/state files")
    ap.add_argument("--workdir-root", default=None)
    ap.add_argument("--no-recursive", action="store_true",
                    help="scan top level only (default: recurse into subfolders)")
    ap.add_argument("--verify", action="store_true",
                    help="do not scan: check an existing manifest's rows "
                         "still point at real files (A41)")
    args = ap.parse_args()

    if args.verify:
        return verify_main(args)
    if args.source is None:
        ap.error("source folder is required unless --verify is passed")

    source = Path(args.source).resolve()
    if not source.is_dir():
        sys.exit(f"source folder not found: {source}")
    if args.workdir is None and args.workdir_root is None:
        profile = photo_profile.load_profile()
        args.workdir_root = photo_profile.get(profile, "legacy_workdir_root")
        if not args.workdir_root:
            sys.exit("no --workdir/--workdir-root given and no "
                      "legacy_workdir_root in profile — pass one explicitly")
    workdir = Path(args.workdir) if args.workdir else Path(args.workdir_root) / source.name
    workdir.mkdir(parents=True, exist_ok=True)

    expected = folder_media_names(source, recursive=not args.no_recursive)
    stdout, stderr = run_exiftool(source, recursive=not args.no_recursive)
    (workdir / "scan-errors.log").write_text(stderr or "", encoding="utf-8")

    raw_rows = list(csv.DictReader(io.StringIO(stdout)))
    unread = unread_media(expected, raw_rows)
    if unread:
        return partial_scan(source, workdir, expected, unread)
    reader = iter(raw_rows)
    fieldnames = ["SourceFile"] + TAGS + [DERIVED_LOCAL]
    total = aae = appledouble = no_date = with_gps = 0
    dates = []
    rows = []
    for row in reader:
        total += 1
        if row.get("FileType") == "AAE":
            aae += 1
            continue
        # macOS AppleDouble metadata sidecars on non-HFS volumes — not media.
        # Counted, not just skipped: `aae_ignored` was the only named exclusion,
        # so on a dump carrying sidecars `total_files_seen` exceeded
        # main_files + aae_ignored by an amount the summary never accounted
        # for, and the owner comparing it against a Finder count had no way to
        # tell a correct exclusion from lost photos.
        if Path(row.get("SourceFile", "")).name.startswith("._"):
            appledouble += 1
            continue
        dto = row.get("DateTimeOriginal", "-")
        cd = row.get("CreateDate", "-")
        best = dto if dto not in ("-", "") else cd
        if best in ("-", "", "0000:00:00 00:00:00"):
            no_date += 1
        else:
            try:
                dates.append(datetime.strptime(best[:19], "%Y:%m:%d %H:%M:%S"))
            except ValueError:
                no_date += 1
        # A24: the shared predicate, not a second opinion. Counting any
        # non-empty GPSPosition made `gps_coverage_pct` — the number a human
        # reads to decide a dump is well-tagged — round UP over rows the
        # clustering stage then threw away.
        if parse_gps(row) is not None:
            with_gps += 1
        rows.append({k: row.get(k, "-") for k in fieldnames})

    # U3-23 — AFTER every row is collected, because the offset comes from
    # another file in the same dump and nothing here can see it row by row.
    video_dated, video_undated = local_video_dates(rows)

    with open(workdir / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    summary = {
        "source": str(source),
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_files_seen": total,
        "main_files": len(rows),
        "aae_ignored": aae,
        "appledouble_ignored": appledouble,
        "no_exif_date": no_date,
        "with_gps": with_gps,
        "gps_coverage_pct": round(100 * with_gps / len(rows), 1) if rows else 0,
        "date_min": min(dates).strftime("%Y-%m-%d") if dates else None,
        "date_max": max(dates).strftime("%Y-%m-%d") if dates else None,
        # U3-23. Said out loud rather than left in a column nobody reads: a
        # video whose offset could not be established keeps a UTC stamp read
        # as local, so it may sit on the wrong DAY and therefore in the wrong
        # folder. That is the state this stage cannot fix and must not hide.
        "video_local_dates_derived": video_dated,
        "video_local_dates_unavailable": len(video_undated),
    }
    (workdir / "scan-summary.json").write_text(json.dumps(summary, indent=1))

    print(json.dumps(summary, indent=1))
    if video_undated:
        print(f"\n⚠️  {len(video_undated)} video(s) kept an unconverted UTC "
              "timestamp — no still declaring `OffsetTimeOriginal` was found "
              f"within {OFFSET_SEARCH_HOURS}h of them, and the engine will "
              "not guess an offset. Their date may be off by the local UTC "
              "offset, which can put them on the wrong DAY and so in the "
              "wrong folder:")
        for name in video_undated[:5]:
            print(f"    {name}")
        if len(video_undated) > 5:
            print(f"    (+{len(video_undated) - 5} more)")
    if stderr.strip():
        print(f"\nexiftool reported warnings -> {workdir / 'scan-errors.log'}",
              file=sys.stderr)


def partial_scan(source, workdir, expected, unread):
    """F04 — stop, never succeed on a scan that missed files.

    No manifest is written: every later stage reads it as the whole dump, so
    a manifest missing files would sort only part of the photos and say
    nothing. The summary records the shortfall, and photo_census refuses to
    run on it."""
    summary = {
        "source": str(source),
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "media_files_in_folder": len(expected),
        "media_files_not_read": len(unread),
        "not_read": unread,
    }
    (workdir / "scan-summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"⛔ scan stopped: exiftool read {len(expected) - len(unread)} of "
          f"the {len(expected)} photos and videos in this folder, so "
          f"{len(unread)} were not read.", file=sys.stderr)
    for name in unread[:5]:
        print(f"    not read: {name}", file=sys.stderr)
    if len(unread) > 5:
        print(f"    (+{len(unread) - 5} more, listed in "
              f"{workdir / 'scan-summary.json'})", file=sys.stderr)
    print("A file that is not read is never sorted, never copied, and never "
          "reported again, so no manifest was written and nothing after this "
          "step will run.\n"
          "If this folder is on a network drive (a mapped drive, a NAS, or a "
          "disk shared from another computer), copy the photos to a local "
          "disk and scan that copy. Details from exiftool: "
          f"{workdir / 'scan-errors.log'}", file=sys.stderr)
    return PARTIAL_SCAN


if __name__ == "__main__":
    sys.exit(main())
