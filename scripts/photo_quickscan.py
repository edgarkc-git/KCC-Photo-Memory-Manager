#!/usr/bin/env python3
"""photo-quickscan — read-only inventory of a raw media folder, run once at
collection initiation (photo-init) BEFORE any pipeline work. Answers two
questions fast, without a full exiftool pass:

  1. What is in here? — per-subfolder file counts, sizes, extension mix,
     junk/.AAE counts, and a date range estimate (folder-name hints + a small
     exiftool sample per subfolder).
  2. How should we process it? — proposes processing groups: each immediate
     subfolder (plus loose files at the root) is one candidate photo-run
     unit; units are grouped by estimated year for the owner's review. Units
     larger than --max-unit files are flagged to be split (re-run quickscan
     on that subfolder, or cluster with photo_cluster options later).

Strictly read-only on the source: writes only quickscan.json + quickscan.md
into --out (the collection's Working Files folder). Scope rule: every file
inside the raw folder is in scope, regardless of how the folder is named.

Usage
  python3 photo_quickscan.py "/Volumes/EXAMPLE_ARCHIVE/Photo Archive" \
      --out "<workspace>/Working Files" [--sample 3] [--no-exif] [--max-unit 5000]
"""

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import photo_exiftool  # noqa: E402
import photo_platform  # noqa: E402

JUNK = {".ds_store", "thumbs.db", "desktop.ini", ".spotlight-v100"}
PHOTO_EXT = {"jpg", "jpeg", "heic", "heif", "png", "dng", "tif", "tiff",
             "gif", "bmp", "webp", "raw", "cr2", "nef", "arw"}
VIDEO_EXT = {"mov", "mp4", "m4v", "avi", "3gp", "mts", "m2ts", "wmv", "mkv",
             "webm", "mpg", "mpeg"}
YEAR_RE = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")
JUNK_WHY = {".ds_store": "Finder's folder settings, no picture in it",
            "thumbs.db": "a Windows thumbnail cache, no picture in it",
            "desktop.ini": "Windows folder settings, no picture in it",
            ".spotlight-v100": "a macOS search index, no picture in it"}
# The report lists skipped files by name up to this many; quickscan.json keeps
# every one of them regardless.
JUNK_LISTED = 50


def junk_reason(f):
    """Why a skipped file is not a photograph (F1).

    A count alone left the owner unable to confirm nothing of theirs was
    dropped. For an AppleDouble file the answer to that question is whether
    the file it describes is here, so that is checked, not assumed."""
    name = f.name
    if name.startswith("._"):
        twin = f.with_name(name[2:])
        if not twin.exists():
            fate = "is not in this folder"
        elif twin.suffix.lower() == ".aae":
            fate = "is an .AAE sidecar, ignored (D4)"
        else:
            fate = "is here and counted"
        return ("macOS AppleDouble sidecar: metadata macOS writes beside a file "
                f"on a non-Mac drive, no picture in it. Its file `{twin.name}` "
                + fate)
    return JUNK_WHY.get(name.lower(), "a system file, no picture in it")


def scan_unit(paths):
    """Count one processing unit (a list of files, or walk a folder)."""
    u = {"files": 0, "photos": 0, "videos": 0, "aae": 0, "junk": 0,
         "other": 0, "bytes": 0, "ext": {}, "junk_files": []}
    for f in paths:
        name = f.name.lower()
        if name in JUNK or name.startswith("._"):
            u["junk"] += 1
            u["junk_files"].append({"file": str(f), "why": junk_reason(f)})
            continue
        ext = f.suffix.lower().lstrip(".")
        if ext == "aae":
            u["aae"] += 1          # D4: sidecars ignored by the pipeline
            continue
        try:
            u["bytes"] += f.stat().st_size
        except OSError:
            pass
        u["files"] += 1
        u["ext"][ext or "(none)"] = u["ext"].get(ext or "(none)", 0) + 1
        if ext in PHOTO_EXT:
            u["photos"] += 1
        elif ext in VIDEO_EXT:
            u["videos"] += 1
        else:
            u["other"] += 1
    return u


def walk_files(folder):
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d.lower() not in JUNK]
        for f in files:
            yield Path(root) / f


def exif_sample_dates(files, n):
    """One exiftool call over up to 2n+1 sampled files -> the capture dates it
    found, sorted, as "YYYY-MM-DD" strings. [] when nothing could be read.

    ⛔ The SAMPLE IS NOT RANDOM and never was: it deliberately takes the
    first, middle and last file by NAME plus a stride. That is fine for a
    range estimate and it is why the caller must not treat the extremes as
    facts about the dump — a filename-sorted last file is very often the
    newest thing in the folder, and on a camera dump the newest thing is
    typically not a camera photo (see `unit_year`).

    ⛔ `._*` AppleDouble files are excluded, the same as `photo_scan.py:85`.
    They carry the media extension and no EXIF at all, so each one that
    reaches this pool burns a sample slot and returns nothing — measured on a
    real dump, 1 of 6."""
    files = [f for f in files if not f.name.startswith("._")]
    if not files or not shutil.which("exiftool"):
        return []
    files = sorted(files, key=lambda p: p.name)
    picks = {files[0], files[len(files) // 2], files[-1]}
    step = max(1, len(files) // max(1, n))
    picks.update(files[::step][:n * 2])
    options = ["-q", "-m", "-fast2", "-json",
               "-DateTimeOriginal", "-CreateDate"]
    try:
        out = photo_exiftool.run(options, sorted(picks), timeout=120).stdout
        dates = []
        for row in json.loads(out or "[]"):
            d = row.get("DateTimeOriginal") or row.get("CreateDate") or ""
            m = re.match(r"(\d{4}):(\d{2}):(\d{2})", str(d))
            if m and m.group(1) != "0000":
                dates.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
        return sorted(dates)
    except Exception:
        return []


def unit_year(unit):
    """Best-guess year for grouping: EXIF sample first, then name hint.

    ⛔ D-19 — the MODAL sampled year, not the latest one. This used to return
    `exif_range[1][:4]`, the max, so a single late file set the label for the
    whole unit. Measured on a real 990-file dump: 923 of 923 dated camera
    files are 2024, and the unit was labelled **2025** because two LINE
    screenshots saved the following January sorted last by filename and were
    picked by the sample. The date range is declared an estimate and survives
    as one; the YEAR is what a human reads when reviewing groups, so it says
    what the unit mostly IS.

    ⛔ A tie breaks to the EARLIER year, and that is a decision rather than a
    coin toss. `Counter.most_common` breaks ties on insertion order, which is
    exactly the kind of answer nobody can reproduce from the output. A dump is
    named for when its photographs were taken; the material that accretes
    afterwards — screenshots, chat saves, re-exports — is later by
    construction, so on a tie the earlier year is the one that describes the
    dump rather than the sediment on top of it."""
    years = unit.get("exif_years") or {}
    if years:
        # most files first, then the earlier year — one expression, and both
        # halves are deliberate
        return min(years, key=lambda y: (-years[y], y))
    m = YEAR_RE.findall(unit["name"])
    return m[-1] if m else None


def human(nbytes):
    for suffix in ["B", "KB", "MB", "GB", "TB"]:
        if nbytes < 1024 or suffix == "TB":
            return f"{nbytes:.1f} {suffix}" if suffix != "B" else f"{nbytes} B"
        nbytes /= 1024


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+", help="raw media folder(s), read-only")
    ap.add_argument("--out", default=str(Path.cwd() / "Working Files"),
                    help="where quickscan.json/.md are written")
    ap.add_argument("--sample", type=int, default=3,
                    help="exiftool date samples per subfolder (0 = skip)")
    ap.add_argument("--no-exif", action="store_true",
                    help="skip exiftool sampling (name hints only)")
    ap.add_argument("--max-unit", type=int, default=5000,
                    help="flag units larger than this many files")
    args = ap.parse_args()

    units = []
    for root in args.roots:
        rp = Path(root)
        if not rp.is_dir():
            sys.exit(f"raw folder not found: {root}\n"
                     + photo_platform.source_missing_hint())
        loose = [f for f in rp.iterdir() if f.is_file()]
        subdirs = sorted([d for d in rp.iterdir()
                          if d.is_dir() and d.name.lower() not in JUNK])
        for group_paths, name, path in (
                [(loose, f"(loose files in {rp.name})", str(rp))] +
                [(list(walk_files(d)), d.name, str(d)) for d in subdirs]):
            if not group_paths:
                continue
            u = scan_unit(group_paths)
            if u["files"] + u["aae"] == 0:
                continue
            u["name"], u["path"] = name, path
            u["loose_only"] = path == str(rp)
            if not args.no_exif and args.sample > 0:
                media = [f for f in group_paths
                         if f.suffix.lower().lstrip(".") in PHOTO_EXT | VIDEO_EXT]
                dates = exif_sample_dates(media, args.sample)
                # The RANGE keeps its old meaning — the extremes of what was
                # sampled — and stays in the table as `Date est.`. The YEARS
                # are new: the label is a count over the sample, which the
                # min/max pair had thrown away.
                u["exif_range"] = (dates[0], dates[-1]) if dates else None
                u["exif_years"] = dict(Counter(d[:4] for d in dates))
            units.append(u)

    if not units:
        sys.exit("no media files found under the given root(s)")

    # group units by estimated year for review; unknown years grouped last
    groups = {}
    for u in units:
        groups.setdefault(unit_year(u) or "unknown", []).append(u)
    proposed = [{"group": i + 1, "label": y,
                 "sources": [u["path"] for u in us],
                 "est_files": sum(u["files"] for u in us),
                 "est_bytes": sum(u["bytes"] for u in us),
                 "status": "proposed"}
                for i, (y, us) in enumerate(sorted(groups.items()))]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y%m%d.%H%M")
    (out_dir / "quickscan.json").write_text(json.dumps(
        {"scanned": now, "roots": args.roots, "units": units,
         "proposed_groups": proposed}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    tot_f = sum(u["files"] for u in units)
    tot_b = sum(u["bytes"] for u in units)
    md = [f"# Quickscan — {', '.join(args.roots)}", "",
          f"Timestamp: {now}", "",
          f"**{tot_f:,} media files / {human(tot_b)}** in {len(units)} unit(s); "
          f".AAE sidecars: {sum(u['aae'] for u in units):,} (D4 ignored), "
          f"junk skipped: {sum(u['junk'] for u in units):,} (each named below)", "",
          "| Unit | Files | Photos | Videos | Other | .AAE | Size | Date est. |",
          "|---|---|---|---|---|---|---|---|"]
    for u in units:
        rng = ("→".join(u["exif_range"]) if u.get("exif_range")
               else (unit_year(u) or "?") + " (name)")
        flag = " ⚠️split" if u["files"] > args.max_unit else ""
        md.append(f"| {u['name']}{flag} | {u['files']:,} | {u['photos']:,} "
                  f"| {u['videos']:,} | {u['other']:,} | {u['aae']:,} "
                  f"| {human(u['bytes'])} | {rng} |")
    skipped = [(u, j) for u in units for j in u["junk_files"]]
    if skipped:
        md += ["", "## Skipped as junk — not photographs", ""]
        for u, j in skipped[:JUNK_LISTED]:
            rel = os.path.relpath(j["file"], u["path"])
            md.append(f"- `{rel}` — {j['why']} ({u['name']})")
        if len(skipped) > JUNK_LISTED:
            md.append(f"- …and {len(skipped) - JUNK_LISTED:,} more, every one "
                      "named with its reason in quickscan.json (`junk_files`)")
    md += ["", "## Proposed processing groups (1 unit = 1 photo-run cycle)", "",
           "| Group | Year | Units | Est. files | Est. size |", "|---|---|---|---|---|"]
    for g in proposed:
        md.append(f"| {g['group']} | {g['label']} | {len(g['sources'])} "
                  f"| {g['est_files']:,} | {human(g['est_bytes'])} |")
    big = [u["name"] for u in units if u["files"] > args.max_unit]
    if big:
        md += ["", f"⚠️ unit(s) over {args.max_unit:,} files — re-run quickscan "
                   f"on them to split before processing: {', '.join(big)}"]
    (out_dir / "quickscan.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("\n".join(md))
    print(f"\nwritten: {out_dir / 'quickscan.json'}, {out_dir / 'quickscan.md'}")


if __name__ == "__main__":
    main()
