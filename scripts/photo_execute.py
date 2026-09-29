#!/usr/bin/env python3
"""photo-execute Stage 5 — run one approved plan: copy files with SHA-256
verification. The ONLY stage that writes to the drive.

Hard safety properties:
  - Copy-only (D2): the script contains no delete/move/rename call against
    any source path. The only unlink targets are its own unverified .part
    copies on the destination side.
  - --dry-run is the DEFAULT; real copying requires an explicit --go.
  - Refuses to run unless every batch in the plan is status approved (or
    done, for resumed runs) in batches.json.
  - Allowlist: every destination must sit under dest_root (D5) or under a
    path this plan explicitly declares (dest.path, overrides) — checked per
    row before any write.
  - Never overwrite: each file is copied to <name>.part, hashed both sides,
    and only renamed into place if the final name is still free. An existing
    destination file with identical hash counts as already-present (verified);
    a different hash is flagged and both sides are left untouched.
  - Resumable: plan/execute-state_PN.json records verified rows by SourceFile;
    re-runs skip a row verified in ANY plan's state (a renumbered plan copies
    nothing again). skip_dupe rows are logged, never copied.
  - A folder a freeze listed to rename (plans.json `renames`) whose old name
    is still on the drive takes no new file: the run refuses before any write.
    The engine never renames a folder itself.
  - One plan per run — no execute-everything flag.

Output: plan/execution-log_PN.md (+ state file). When every copy row of a
batch is verified, the batch advances approved -> done in batches.json.

--no-date mode (D13, to-be-checked mod 2026-07-06 evening): executes
plan_no-date-files.csv — the auto-routed no-date files (default all -> the
monthly to-be-checked bucket; YYYYMM00_AI-images only when the plan was
written with --ai-confirmed). No batch approval gate (no-date files belong to
no batch); destinations must still sit under dest_root. Same copy/verify
machinery.

Language: every sentence this script writes for a human comes from
photo_profile.messages(profile). A run with no owner pack resolves to the
legacy zh-TW table, so it keeps producing what it produced before the catalog
existed; a pack that declares a language gets that language.

Usage:
  python3 photo_execute.py "<Working Files>/<dump>" --plan 7          # dry-run
  python3 photo_execute.py "<Working Files>/<dump>" --plan 7 --go     # copy
  python3 photo_execute.py "<Working Files>/<dump>" --no-date --go    # D13
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import photo_profile  # noqa: E402
from photo_platform import path_key  # noqa: E402

FREE_SPACE_MARGIN = 1 << 30  # 1 GB on top of the plan's estimated size
# plans.json: the folders a freeze on an already-copied dump found renamed,
# [{"old", "new"}] relative to dest_root, parents first (FIX8 F8-2).
RENAMES_KEY = "renames"


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.2f} TB"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def allowed(dest, prefixes):
    return any(dest == p or dest.startswith(p + "/") for p in prefixes)


def free_space_at(dest_root):
    """Free bytes on the filesystem dest_root will live on.

    dest_root itself need not exist yet: on a first run it is created later,
    as a parent of the first destination dir. Measuring the space at a path
    that does not exist raises FileNotFoundError, which used to reach the
    user as a traceback on the one run most likely to hit it — the very
    first. Walk up to the nearest ancestor that does exist; it is on the
    same filesystem, so its free space is the number we want. An absent
    mount point is a different failure and keeps its own message.
    """
    p = Path(dest_root).resolve()
    for candidate in [p, *p.parents]:
        if candidate.is_dir():
            return shutil.disk_usage(candidate).free
    raise FileNotFoundError(dest_root)


def verified_anywhere(plan_dir):
    """SourceFile -> its verified record, from EVERY execute-state of this
    work dir. A file is copied once, whichever plan number copied it: a merge
    after a copy renumbers the plans, and a per-plan read then re-copied 262
    files (FIX8 F8-2, measured)."""
    out = {}
    for sp in sorted(Path(plan_dir).glob("execute-state_*.json")):
        out.update(json.loads(sp.read_text()).get("verified") or {})
    return out


def renames_to_do(config, dest_root):
    """-> [(old, new)] folder names under dest_root a freeze listed and the
    owner has not renamed yet: the old folder is still on the drive. Only
    checks whether a folder exists; the engine never renames one."""
    return [(r["old"], r["new"]) for r in config.get(RENAMES_KEY) or []
            if (Path(dest_root) / r["old"]).is_dir()]


def blocked_renames(todo, dest_root, pending):
    """-> the (old, new) renames in `todo` a row in `pending` would copy into
    under the NEW name."""
    blocked = []
    for old, new in todo:
        target = path_key(Path(dest_root) / new)
        if any(path_key(r["destination"]) == target
               or path_key(r["destination"]).startswith(target + "/")
               for r in pending):
            blocked.append((old, new))
    return blocked


def load_state(path, plan_num):
    if path.exists():
        state = json.loads(path.read_text())
        if state.get("plan") != plan_num:
            sys.exit(f"{path} belongs to plan {state.get('plan')}, not P{plan_num}")
        return state
    return {"plan": plan_num, "verified": {}}


def save_state(path, state):
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def copy_one(src, dest_dir, name, flags, msg):
    """Copy src into dest_dir/name via .part + hash-verify. -> (status, sha)
    status: copied | already_present | flagged"""
    final = dest_dir / name
    part = dest_dir / (name + ".part")
    src_sha = sha256_file(src)
    if final.exists():
        if sha256_file(final) == src_sha:
            return "already_present", src_sha
        flags.append(("collision", str(src), str(final),
                      msg["flag_collision_existing_differs"]))
        return "flagged", src_sha
    for attempt in (1, 2):
        shutil.copy2(src, part)
        if sha256_file(part) == src_sha:
            if final.exists():  # appeared since our check — never overwrite
                part.unlink()
                flags.append(("collision", str(src), str(final),
                              msg["flag_collision_appeared_midcopy"]))
                return "flagged", src_sha
            os.replace(part, final)
            return "copied", src_sha
        part.unlink()  # checksum mismatch: delete OUR copy, never the source
    flags.append(("checksum", str(src), str(final),
                  msg["flag_checksum_mismatch"]))
    return "flagged", src_sha


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir")
    ap.add_argument("--plan", type=int, help="plan number from plans.json")
    ap.add_argument("--no-date", action="store_true",
                    help="execute the no-date plan (D13: the monthly "
                         "to-be-checked bucket / confirmed AI-images)")
    ap.add_argument("--go", action="store_true",
                    help="actually copy (default is dry-run)")
    args = ap.parse_args()
    if args.no_date == (args.plan is not None):
        sys.exit("exactly one of --plan N / --no-date is required")
    label = "no-date" if args.no_date else f"P{args.plan}"

    workdir = Path(args.workdir).resolve()
    plan_dir = workdir / "plan"
    csv_path = plan_dir / f"plan_{label}-files.csv"
    if not csv_path.exists():
        sys.exit(f"no {csv_path}")

    pp = workdir / "plans.json"
    config = json.loads(pp.read_text()) if pp.exists() else {}
    # one pack per run: the execution record is written in the owner's language
    profile = photo_profile.load_profile(workdir=workdir)
    msg = photo_profile.messages(profile)
    # dest_root: plans.json -> collection.json (photo-init, per collection)
    # -> the user's profile (legacy_dest_root) -> hard failure
    cj = workdir.parent / "collection.json"
    coll = json.loads(cj.read_text()) if cj.exists() else {}
    dest_root = config.get("dest_root") or coll.get("dest_root")
    if not dest_root:
        dest_root = photo_profile.get(profile, "legacy_dest_root")
    if not dest_root:
        sys.exit("no dest_root in plans.json/collection.json and no "
                  "legacy_dest_root in profile")

    bdata = json.loads((workdir / "batches.json").read_text())
    if args.no_date:
        # D13: no-date files belong to no batch — no approval gate; every
        # destination must still sit under dest_root
        plan = None
        prefixes = [dest_root]
    else:
        plan = next((p for p in config.get("plans", [])
                     if p["plan"] == args.plan), None)
        if plan is None:
            sys.exit(f"plan {args.plan} not in plans.json")
        prefixes = [dest_root, plan["dest"]["path"]]
        prefixes += [ov["dest"] for ov in plan.get("overrides", [])]
        bad = [b["batch"] for b in bdata["batches"]
               if b["batch"] in plan["batches"] and b["status"] not in ("approved", "done")]
        if bad and args.go:
            sys.exit(f"batches {bad} are not approved — refusing to execute")
        if bad:
            # A dry run copies nothing, so it previews rather than refuses: an
            # indexed `finish` dry run no longer approves (M5).
            print(f"  (batches {bad} are not approved yet — `--go` refuses "
                  "until they are; `finish --go` approves them)")

    rows = list(csv.DictReader(open(csv_path, newline="")))
    copies = [r for r in rows if r["action"] == "copy"]
    # Any non-copy action, not just skip_dupe: a new skip kind must show up in
    # the report rather than vanish between the copies and the total.
    skips = [r for r in rows if r["action"].startswith("skip")]

    for r in copies:
        if not allowed(r["destination"], prefixes):
            sys.exit(f"destination outside allowlist, aborting before any write:\n"
                     f"  {r['destination']}\n  (allowed: {prefixes})")

    state_path = plan_dir / f"execute-state_{label}.json"
    state = load_state(state_path, "no-date" if args.no_date else args.plan)
    done = verified_anywhere(plan_dir)
    pending = [r for r in copies if r["SourceFile"] not in done]
    # A new file must not open a renamed folder under its new name while the
    # old one is still on the drive: the folder would then exist twice.
    blocked = blocked_renames(renames_to_do(config, dest_root), dest_root, pending)
    if blocked:
        sys.exit("a file to copy goes into a folder that is still to be renamed "
                 "on the drive — rename it by hand first, then copy again "
                 "(the engine never renames a folder). Nothing written:\n"
                 + "\n".join(f'  "{o}" -> "{n}"' for o, n in blocked))
    total_bytes = 0
    missing = []
    for r in pending:
        src = Path(r["SourceFile"])
        if not src.is_file() or not os.access(src, os.R_OK):
            missing.append(r["SourceFile"])
        else:
            total_bytes += src.stat().st_size

    dest_dirs = sorted({r["destination"] for r in copies})
    # Only a folder a pending file goes into. A folder renamed after its copy
    # receives nothing, and an empty new-named folder beside the old one is
    # what the owner's hand rename would collide with (FIX8 F8-2).
    to_create = sorted({r["destination"] for r in pending
                        if not Path(r["destination"]).is_dir()})
    existing_names = 0
    for r in pending:
        if (Path(r["destination"]) / r["FileName"]).exists():
            existing_names += 1
    try:
        free = free_space_at(dest_root)
    except (FileNotFoundError, OSError):
        sys.exit(f"destination not reachable: {dest_root}\n"
                 "Nothing above it exists either — check the drive is mounted.")

    print(f"plan {label}: {len(rows)} rows = {len(copies)} copy + "
          f"{len(skips)} skip_dupe; {len(copies) - len(pending)} already verified, "
          f"{len(pending)} pending ({human_size(total_bytes)})")
    print(f"  destinations: {len(dest_dirs)} ({len(to_create)} to create); "
          f"existing same-name files: {existing_names}; "
          f"free space {human_size(free)} (need {human_size(total_bytes + FREE_SPACE_MARGIN)})")
    if missing:
        for m in missing[:10]:
            print(f"  MISSING/unreadable source: {m}")
        sys.exit(f"{len(missing)} source files missing or unreadable — aborting")
    if free < total_bytes + FREE_SPACE_MARGIN:
        sys.exit("not enough free space on destination — aborting")

    if not args.go:
        for d in to_create:
            print(f"  would create: {d}")
        print("DRY-RUN ONLY — no file was written. Re-run with --go to copy.")
        return

    t0 = time.time()
    flags = []
    counts = {"copied": 0, "already_present": 0, "flagged": 0}
    for d in to_create:
        Path(d).mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(pending, 1):
        status, sha = copy_one(Path(r["SourceFile"]), Path(r["destination"]),
                               r["FileName"], flags, msg)
        counts[status] += 1
        if status != "flagged":
            state["verified"][r["SourceFile"]] = {
                "dest": str(Path(r["destination"]) / r["FileName"]),
                "sha256": sha, "status": status,
                "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        if i % 50 == 0 or i == len(pending):
            save_state(state_path, state)
            print(f"  {i}/{len(pending)} ({counts['copied']} copied, "
                  f"{counts['already_present']} already present, "
                  f"{counts['flagged']} flagged)")
    save_state(state_path, state)
    elapsed = time.time() - t0

    dest_counts = {}
    for v in state["verified"].values():
        d = str(Path(v["dest"]).parent)
        dest_counts[d] = dest_counts.get(d, 0) + 1

    done_batches = []
    if not flags and not args.no_date:
        by_batch = {}
        for r in copies:
            by_batch.setdefault(r["batch"], []).append(r)
        for bnum, brows in sorted(by_batch.items()):
            if all(r["SourceFile"] in state["verified"] or r["SourceFile"] in done
                   for r in brows):
                subprocess.run(
                    [sys.executable, str(Path(__file__).parent / "photo_classify_set.py"),
                     str(workdir), "--batch", str(bnum), "--status", "done"],
                    check=True, stdout=subprocess.DEVNULL)
                done_batches.append(bnum)

    md = [msg["exec_title"].format(label=label), "",
          msg["exec_executed_at"].format(
              when=datetime.now().strftime('%Y-%m-%d %H:%M'),
              seconds=f"{elapsed:.0f}"),
          msg["md_source"].format(source=bdata['source']), "",
          msg["md_item_count_header"], "|---|---|",
          msg["exec_stat_copied"].format(n=counts['copied']),
          msg["exec_stat_already_present"].format(n=counts['already_present']),
          msg["exec_stat_previously_verified"].format(n=len(copies) - len(pending)),
          msg["exec_stat_skip_dupe"].format(n=len(skips)),
          msg["exec_stat_flags"].format(n=len(flags)), "",
          msg["exec_h_dest_counts"], "",
          msg["md_dest_count_header"], "|---|---|"]
    for d, n in sorted(dest_counts.items(), key=lambda x: -x[1]):
        md.append(f"| `{d}` | {n} |")
    if flags:
        md += ["", msg["exec_h_flags"], "",
               msg["exec_flags_header"], "|---|---|---|---|"]
        for kind, s, dst, note in flags:
            md.append(f"| {kind} | `{s}` | `{dst}` | {note} |")
    if done_batches:
        md += ["", msg["exec_batches_done"].format(
            batches=', '.join('B' + str(b) for b in done_batches))]
    md += ["", msg["exec_footer"], ""]
    log_path = plan_dir / f"execution-log_{label}.md"
    log_path.write_text("\n".join(md))

    print(f"{label}: {counts['copied']} copied + "
          f"{counts['already_present']} already present, {len(flags)} flags, "
          f"{elapsed:.0f}s -> {log_path}")
    if flags:
        sys.exit(1)


if __name__ == "__main__":
    main()
