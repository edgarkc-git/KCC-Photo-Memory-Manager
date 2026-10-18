#!/usr/bin/env python3
"""Dest scanner (SPEC v1 C8, G15) — what is already in the sorted tree.

Walks the collection's dest root and records, per media file: its folder
relative to the root, name, size, mtime, SHA-256 and capture day. The tree is
re-scanned every run (G15: no catalog in the pack); the cost is held down by a
cache keyed by path + size + mtime, so a re-run hashes only the files that are
new or changed. The cache sits BESIDE the work dirs, in the collection's own
folder (`cache_dir()`): `photo_index render` must leave the work dir byte for
byte as it found it (G3), and one sorted tree serves every dump of the
collection.

⛔ READ-ONLY on the dest: it opens files to hash them and asks exiftool for
their dates, nothing else. The only file it writes is its own cache, and only
when the caller asks (`write=True`) — a dry run writes nothing.

The capture day follows the scan's own rules (`photo_scan.local_video_dates`,
`photo_cluster.parse_date`), never a second copy of them.

A twin (CONTEXT "Twin") is a file whose bytes are identical to a file already
in the tree or earlier in the same dump. `twins()` decides which source files
are twins and of what; a same-name file with different bytes is NOT one.

Usage:
  python3 photo_desttree.py "<work dir>" [--dest-root <path>] [--write]
"""

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import photo_exiftool  # noqa: E402
import photo_scan  # noqa: E402
from photo_cluster import parse_date  # noqa: E402
from photo_platform import path_key  # noqa: E402
from photo_quickscan import JUNK  # noqa: E402

CACHE_DIR = "_hash-cache"
CACHE_NAME = "dest-tree.json"
SOURCE_CACHE_NAME = "source-sha_{dump}.json"
# The exiftool fields the capture day is read from — a subset of the scan's.
DATE_TAGS = ["FileType", "DateTimeOriginal", "CreateDate", "OffsetTimeOriginal",
             "CreationDate"]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def media_files(root):
    """Every media file under `root`, the way the scan judges one (`._*`
    excluded, dot-directories skipped)."""
    for top, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")
                         and d.lower() not in JUNK)
        for name in sorted(files):
            if photo_scan.is_media_name(name):
                yield Path(top) / name


def cache_dir(workdir):
    return Path(workdir).resolve().parent / CACHE_DIR


def stat_key(path):
    st = path.stat()
    return st.st_size, st.st_mtime_ns


def read_cache(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_cache(path, data):
    Path(path).parent.mkdir(exist_ok=True)
    tmp = Path(path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def hash_cached(paths, cache, missing_ok=False):
    """-> {path_key: entry}, entry = {size, mtime_ns, sha256, ...}. An entry
    whose size and mtime still match is reused; every other file is hashed.
    `cache` is the previous result (same shape); it is never mutated. With
    `missing_ok` a file that cannot be read is left out."""
    out = {}
    for p in paths:
        try:
            size, mtime = stat_key(p)
        except OSError:
            if missing_ok:
                continue
            raise
        key = path_key(p)
        old = cache.get(key)
        if old and old.get("size") == size and old.get("mtime_ns") == mtime:
            out[key] = old
        else:
            out[key] = {"size": size, "mtime_ns": mtime, "sha256": sha256_file(p)}
    return out


def read_dates(paths):
    """-> {path_key: {tag: value}} for `paths`, one exiftool call. ⛔ Never
    called with no path: exiftool with no file argument prints its man page
    and exits 0."""
    if not paths:
        return {}
    proc = photo_exiftool.run(["-csv", "-n", "-f", *(f"-{t}" for t in DATE_TAGS)],
                              paths)
    if proc.returncode != 0 and not proc.stdout:
        raise RuntimeError(f"exiftool failed: {proc.stderr.strip()[:500]}")
    out = {}
    for row in csv.DictReader(io.StringIO(proc.stdout)):
        out[path_key(Path(row["SourceFile"]).absolute())] = {
            t: row.get(t, "-") for t in DATE_TAGS}
    return out


def scan(dest_root, workdir, write=False):
    """-> [{folder, name, path, size, mtime_ns, sha256, day}] for every media
    file under `dest_root`, folder relative to it ("" at the root), day
    YYYY-MM-DD or None. A dest root that does not exist is an empty tree.
    With `write`, the cache in `workdir` is updated."""
    root = Path(dest_root)
    if not root.is_dir():
        return []
    cache_path = cache_dir(workdir) / CACHE_NAME
    cache = read_cache(cache_path).get(path_key(root), {})
    files = list(media_files(root))
    entries = hash_cached(files, cache)
    new = [p for p in files if "tags" not in entries[path_key(p)]]
    tags = read_dates(new)
    for p in new:
        key = path_key(p)
        entries[key] = {**entries[key],
                        "tags": tags.get(path_key(p.absolute()))
                        or {t: "-" for t in DATE_TAGS}}
    rows = []
    for p in files:
        e = entries[path_key(p)]
        rows.append({"SourceFile": str(p), **e["tags"]})
    # The scan's video rule: a video's UTC stamp made local by its own
    # declaration or the nearest still's offset — here, the tree's stills.
    photo_scan.local_video_dates(rows)
    out = []
    for p, row in zip(files, rows):
        e = entries[path_key(p)]
        dt = parse_date(row)
        rel = p.parent.relative_to(root)
        out.append({"folder": "" if str(rel) == "." else rel.as_posix(),
                    "name": p.name, "path": str(p), "size": e["size"],
                    "mtime_ns": e["mtime_ns"], "sha256": e["sha256"],
                    "day": dt.date().isoformat() if dt else None})
    if write:
        whole = read_cache(cache_path)
        whole[path_key(root)] = entries
        write_cache(cache_path, whole)
    return out


def source_shas(paths, workdir, write=False):
    """-> {source path: SHA-256} for the dump's own files that can be read,
    cached by path + size + mtime like the tree. A file that cannot be read
    is left out: it is no twin, and the freeze refuses it on its own."""
    cache_path = cache_dir(workdir) / SOURCE_CACHE_NAME.format(
        dump=Path(workdir).resolve().name)
    entries = hash_cached([Path(p) for p in paths], read_cache(cache_path),
                          missing_ok=True)
    if write:
        write_cache(cache_path, entries)
    return {p: entries[path_key(Path(p))]["sha256"] for p in paths
            if path_key(Path(p)) in entries}


def twins(shas, tree, own_copies=(), done=()):
    """-> {source: twin}, the source files a copy must skip (G16).

    `shas` is {source: SHA-256} for the dump's files; `tree` is `scan()`'s
    rows; `own_copies` the dest paths THIS dump already copied and `done` the
    sources it copied (`photo_execute.verified_anywhere`). A copied file is
    never a twin of its own copy, and never turned into a skip afterwards.

    Bytes, never names: a twin has the same size AND the same full SHA-256.
    A twin in the tree wins: every source with those bytes points at that
    tree file (the first by path). Otherwise, inside the dump, one source is
    kept — one already copied, then the shortest name, then the path, so
    `X.jpg` is kept over `X 2.jpg` — and the others point at the kept SOURCE
    path, which is the same string at render and at freeze."""
    own = {path_key(p) for p in own_copies}
    copied = {path_key(p) for p in done}
    sources = {path_key(s) for s in shas}
    in_tree = {}
    for t in sorted(tree, key=lambda t: t["path"]):
        key = path_key(t["path"])
        if key in own or key in sources:
            continue
        in_tree.setdefault((t["size"], t["sha256"]), t["path"])
    groups = {}
    for src, sha in shas.items():
        groups.setdefault((Path(src).stat().st_size, sha), []).append(src)
    out = {}
    for key, members in groups.items():
        if key in in_tree:
            for src in members:
                out[src] = in_tree[key]
        else:
            keep, *rest = sorted(members, key=lambda s: (
                path_key(s) not in copied, len(Path(s).name), s))
            for src in rest:
                out[src] = keep
    return {s: t for s, t in out.items() if path_key(s) not in copied}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir")
    ap.add_argument("--dest-root", help="default: the collection's dest root")
    ap.add_argument("--write", action="store_true",
                    help="update the hash cache beside the work dir "
                         "(default: read only)")
    args = ap.parse_args()
    workdir = Path(args.workdir).resolve()
    dest = args.dest_root
    if not dest:
        import photo_plan
        dest = photo_plan.resolve_dest_root(workdir)
    if not Path(dest).is_dir():
        print(f"dest root not found: {dest} — an empty tree")
        return 0
    rows = scan(dest, workdir, write=args.write)
    print(f"{len(rows)} media file(s) in {dest}, "
          f"{len({r['sha256'] for r in rows})} distinct SHA-256, "
          f"{sum(1 for r in rows if r['day'] is None)} with no capture day")
    return 0


if __name__ == "__main__":
    sys.exit(main())
