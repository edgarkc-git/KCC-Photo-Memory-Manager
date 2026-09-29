#!/usr/bin/env python3
"""photo-plan Stage 4a — mandatory dedupe check (OA-3) for one or more batches.

Matches batch files against reference manifests of already-sorted folders:
filename + size first; on any name+size hit, SHA-256 both sides before
calling it a duplicate (hash mismatch = collision, kept as unique + logged).
Known limitation: iPhone edited re-exports (IMG_E1234)
share content under a different name — name+size will not catch them.

Strictly read-only on the drive (hashing only reads). Writes into the work
dir only:  plan/dedupe_batch-NN.json  per batch.

Reference manifests are the manifest.csv files photo_scan.py wrote for the
populated hand-named folders, e.g. "Working Files/20240115_Lakeside_hiking".

Usage:
  python3 photo_dedupe.py "<Working Files>/202401" --batches 4-12 \
      --ref "<Working Files>/20240115-0118_Rivertown_overseas_trip" [--ref ...]
"""

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from photo_cluster import parse_date  # noqa: E402


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_ref_index(ref_workdirs):
    """(lowercased filename, size) -> [existing SourceFile paths]."""
    index = {}
    for wd in ref_workdirs:
        mpath = Path(wd) / "manifest.csv"
        if not mpath.exists():
            sys.exit(f"no manifest.csv in {wd} — run photo_scan.py on that folder first")
        with open(mpath, newline="") as f:
            for row in csv.DictReader(f):
                key = (row["FileName"].lower(), row["FileSize"])
                index.setdefault(key, []).append(row["SourceFile"])
    return index


def batch_rows(workdir, batch):
    rows = []
    with open(workdir / "manifest.csv", newline="") as f:
        for row in csv.DictReader(f):
            dt = parse_date(row)
            if dt and batch["from"] <= dt.date().isoformat() <= batch["to"]:
                rows.append(row)
    return rows


def parse_batch_spec(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def dedupe_batch(rows, index, hash_cache):
    dupes, uniques, collisions = [], [], []
    for row in rows:
        key = (row["FileName"].lower(), row["FileSize"])
        candidates = index.get(key)
        if not candidates:
            uniques.append(row["SourceFile"])
            continue
        src_hash = sha256_file(row["SourceFile"])
        match = None
        for c in candidates:
            if c not in hash_cache:
                hash_cache[c] = sha256_file(c)
            if hash_cache[c] == src_hash:
                match = c
                break
        if match:
            dupes.append({"source": row["SourceFile"], "existing": match,
                          "sha256": src_hash})
        else:
            collisions.append({"source": row["SourceFile"],
                               "name_size_matches": candidates})
            uniques.append(row["SourceFile"])
    return dupes, uniques, collisions


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir", help="work dir of the source dump (manifest.csv + batches.json)")
    ap.add_argument("--batches", required=True, help="e.g. 4-12 or 1,3,15")
    ap.add_argument("--ref", action="append", required=True,
                    help="work dir of a reference (already-sorted) folder; repeatable")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    data = json.loads((workdir / "batches.json").read_text())
    wanted = parse_batch_spec(args.batches)
    index = load_ref_index(args.ref)
    out_dir = workdir / "plan"
    out_dir.mkdir(exist_ok=True)

    hash_cache = {}
    for n in wanted:
        batch = next((b for b in data["batches"] if b["batch"] == n), None)
        if batch is None:
            sys.exit(f"batch {n} not in batches.json")
        rows = batch_rows(workdir, batch)
        dupes, uniques, collisions = dedupe_batch(rows, index, hash_cache)
        result = {
            "batch": n, "from": batch["from"], "to": batch["to"],
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "refs": args.ref, "files": len(rows),
            "dupes": len(dupes), "uniques": len(uniques),
            "collisions": len(collisions),
            "dupe_list": dupes, "unique_list": uniques,
            "collision_list": collisions,
        }
        (out_dir / f"dedupe_batch-{n:02d}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1))
        print(f"batch {n:>2}: {len(rows)} files -> {len(dupes)} dupes, "
              f"{len(uniques)} uniques, {len(collisions)} collisions")


if __name__ == "__main__":
    main()
