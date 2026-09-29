#!/usr/bin/env python3
"""OA-4: find files whose extension doesn't match their real content
under given destination folders and rename them in place. Destination
copies only — never run on raw source dumps.

Two detection passes:
  1. exiftool FileTypeExtension vs extension (all files).
  2. magic-byte check (`photo_magic`, pure Python) on every .HEIC file — exiftool's
     brand-atom heuristic misreports some Live Photo video components as
     HEIC when they are really QuickTime movies (L17: in one measured
     trip folder, 66 such files that exiftool called clean). MIME
     video/quicktime -> .MOV, video/mp4 -> .MP4.

Rules (owner-approved, see Lesson L12):
  - .AAE sidecars skipped entirely (D4)
  - never overwrite: a name collision gets a _dup2/_dup3... suffix
  - dry-run by default; --go to actually rename

Usage
  photo_rename_mismatches.py <folder> [<folder> ...] [--go]
  photo_rename_mismatches.py --plans <workdir>/plans.json [--go]
      (derives target folders from each plan's dest path and its overrides'
       folders; a folder still to rename is checked under its old name)

Called automatically by photo_run.py `finish --go` after all plans copy.
Since D13 (2026-07-06) photo_plan corrects mislabeled extensions at copy
time, so this pass is a BACKSTOP — it mainly catches older mismatched copies
already sitting in merge destinations.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import photo_exiftool  # noqa: E402
import photo_magic  # noqa: E402


def scan_root(root):
    """One exiftool process per root: returns [(Path, real_ext_lower), ...]
    for every file whose extension != FileTypeExtension."""
    try:
        out = photo_exiftool.run(
            ["-r", "-fast2", "-q", "-q", "--ext", "aae",
             "-p", "${Directory}/${FileName}\t${FileTypeExtension}"],
            [root]
        ).stdout
    except FileNotFoundError:
        sys.exit("exiftool not found on PATH")
    mismatches = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        path_s, real_ext = line.rsplit("\t", 1)
        real_ext = real_ext.strip().lower()
        if not real_ext:
            continue
        f = Path(path_s)
        cur_ext = f.suffix.lower().lstrip(".")
        if real_ext != cur_ext:
            mismatches.append((f, real_ext))
    return mismatches


MAGIC_VIDEO_EXT = {"MOV": "mov", "MP4": "mp4"}


def magic_check_heic(root, already_flagged):
    """Second pass (L17): magic-byte sniff every .HEIC under root — exiftool
    can misreport HEIC-named QuickTime movies as genuine HEIC. Returns extra
    (Path, real_ext_lower) mismatches not caught by the exiftool pass."""
    extra = []
    for p in Path(root).rglob("*"):
        if (p.is_file() and p.suffix.lower() == ".heic"
                and p not in already_flagged):
            real_ext = MAGIC_VIDEO_EXT.get(photo_magic.sniff(p))
            if real_ext:
                extra.append((p, real_ext))
    return extra


RENAMES_KEY = "renames"   # photo_execute.RENAMES_KEY, as plans.json spells it


def plan_roots(plans):
    """Every folder this dump's plans name: each plan's own folder (a merge
    target may hold older copies) and each override's — a `group split`'s
    pieces, which reading `dest` alone never reached (M2). ⛔ Not the monthly
    buckets: they are shared with other dumps, and this pass renames files."""
    roots = []
    for p in plans.get("plans", []):
        roots += [(p.get("dest") or {}).get("path")]
        roots += [o["dest"]["path"] if isinstance(o["dest"], dict) else o["dest"]
                  for o in p.get("overrides") or []]
    return list(dict.fromkeys(r for r in roots if r))


def outermost(roots):
    """The roots that no other root holds: a scan is recursive."""
    paths = sorted({str(Path(r).absolute()) for r in roots}, key=len)
    out = []
    for r in paths:
        if not any(r == o or r.startswith(o + "/") for o in out):
            out.append(r)
    return out


def still_to_rename(root, renamed):
    """A folder a freeze renamed after its copy is still on the drive under
    its OLD name until the owner renames it by hand: check it there, rather
    than skip it as not found (M2)."""
    for new, old in renamed.items():
        if root == new or root.startswith(new + "/"):
            return old + root[len(new):]
    return root


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="*", help="destination folders to scan")
    ap.add_argument("--plans", help="plans.json — scan each plan's dest path")
    ap.add_argument("--go", action="store_true",
                    help="actually rename (default: dry-run)")
    args = ap.parse_args()

    roots = list(args.roots)
    renamed = {}
    if args.plans:
        plans = json.loads(Path(args.plans).read_text())
        roots += [d for d in plan_roots(plans) if d not in roots]
        dest_root = plans.get("dest_root") or ""
        renamed = {str(Path(dest_root) / r["new"]): str(Path(dest_root) / r["old"])
                   for r in plans.get(RENAMES_KEY) or []}
    if not roots:
        sys.exit("no folders given (positional roots and/or --plans)")

    mismatches = []
    for root in outermost(roots):
        # Both passes have to name files the same way: scan_root gets its
        # paths back from exiftool, which absolutises them, while
        # magic_check_heic rglobs this root itself. A relative root left the
        # two in different spaces, so the `already_flagged` and
        # `planned_targets` comparisons below silently stopped matching.
        p = Path(still_to_rename(root, renamed)).absolute()
        if str(p) != str(Path(root).absolute()) and p.exists():
            print(f"(still to rename on the drive: checking {p.name} under its "
                  "old name)", file=sys.stderr)
        if not p.exists():
            print(f"(skip, not found: {root})", file=sys.stderr)
            continue
        found = scan_root(p)
        found += magic_check_heic(p, {f for f, _ in found})
        mismatches.extend(found)

    print(f"{len(mismatches)} mismatched file(s) found")
    planned_targets = set()
    for f, real_ext in mismatches:
        new_name = f.with_suffix("." + real_ext.upper())
        if new_name != f and (new_name.exists() or new_name in planned_targets):
            stem, ext = new_name.stem, new_name.suffix
            n = 2
            while True:
                candidate = new_name.with_name(f"{stem}_dup{n}{ext}")
                if not candidate.exists() and candidate not in planned_targets:
                    new_name = candidate
                    break
                n += 1
        planned_targets.add(new_name)
        marker = "RENAME" if args.go else "would rename"
        print(f"[{marker}] {f}\n    -> {new_name.name}")
        if args.go:
            f.rename(new_name)

    if not args.go and mismatches:
        print("\nDRY-RUN — nothing renamed. Re-run with --go to rename.")


if __name__ == "__main__":
    main()
