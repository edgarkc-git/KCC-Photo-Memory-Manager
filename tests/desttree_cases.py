#!/usr/bin/env python3
"""P1 M4 + M5 cases — the dest scanner (G15) and skipping twins (G16).

A twin is a file whose bytes (size + SHA-256) are already in the sorted tree
or earlier in the same dump (E57, E58). The copy skips it and lists where its
twin is; `verify --copied` proves every source's bytes are in the tree. A
same-name or same-size file with OTHER bytes is not a twin (E55).

  python3 tests/desttree_cases.py [-v]

Exit 0 = pass. Every dump, pack and file is synthetic, in a temp dir (the
two-day fixture of `photo_index_cases.py`); no network.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import photo_exiftool  # noqa: E402
import photo_index_cases as ix  # noqa: E402
import index_finish_cases as fx  # noqa: E402

try:
    import photo_desttree  # noqa: E402
except ImportError:          # the unfixed code has no scanner
    photo_desttree = None

LOTUS = fx.LOTUS
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def jpeg(path, note):
    data = note.encode()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xfe" + (len(data) + 2).to_bytes(2, "big") + data + b"\xff\xd9")


def real_jpeg(path):
    """A JPEG exiftool can write a date into."""
    from PIL import Image
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (10, 20, 30)).save(path, "JPEG")


def state(root):
    root = Path(root)
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def raw(tmp, name):
    return Path(tmp).resolve() / "raw" / "dump-a" / name


def sorted_root(tmp):
    return Path(tmp).resolve() / "sorted"


def with_copy_in_dump(extra_name, of):
    """A g3 fixture whose dump also holds `extra_name`, byte-identical to
    `of` (the E58 shape: `X.jpg` + `X 2.jpg`)."""
    real = ix.g3_rows

    def rows(base):
        out = real(base)
        twin = next(r for r in out if r["FileName"] == of)
        out.append({**twin, "FileName": extra_name,
                    "SourceFile": f"{base}/{extra_name}"})
        return out
    return rows


def ready_with(tmp, before=None, rows=None):
    """`index_finish_cases.ready()` with a hook between the dump and init."""
    real = ix.g3_rows
    if rows:
        ix.g3_rows = rows
    try:
        wd, pack = ix.g3_dump(tmp)
    finally:
        ix.g3_rows = real
    if rows:
        for r in rows(raw(tmp, "")):
            if r["FileName"].endswith(" 2.jpg"):
                shutil.copyfile(raw(tmp, r["FileName"].replace(" 2.jpg", ".jpg")),
                                r["SourceFile"])
    if before:
        before(tmp)
    for cmd in ("init", "render", "check", "freeze"):
        code, out, err = ix.run(cmd, wd)
        if code:
            raise RuntimeError(f"{cmd}: {(out + err)[-400:]}")
    return wd, pack


def verify(wd):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "photo_index.py"),
                           "verify", str(wd), "--copied"],
                          capture_output=True, text=True)


def plan_text(wd):
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted((wd / "plan").glob("plan_*.md")))


def exec_text(wd):
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted((wd / "plan").glob("execution-log_*.md")))


# ---------------------------------------------------------------------------
# M4 — the dest scanner
# ---------------------------------------------------------------------------

@case
def scan_lists_each_media_file_with_folder_size_sha_and_day():
    """⭐ M4. ⛔ FAILS on 11f5353: there is no dest scanner. Every media file
    of the tree, with its folder relative to the root, size, SHA-256 and
    capture day read by exiftool; `._*` and non-media files are not listed."""
    if photo_desttree is None:
        return False, "no scripts/photo_desttree.py"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "sorted"
        real_jpeg(root / "20241101_Ford" / "A.jpg")
        jpeg(root / "B.jpg", "b")
        jpeg(root / "20241101_Ford" / "._A.jpg", "junk")
        (root / "notes.txt").write_text("x")
        r = photo_exiftool.run(["-overwrite_original",
                                "-DateTimeOriginal=2024:11:01 10:00:00"],
                               [root / "20241101_Ford" / "A.jpg"])
        rows = photo_desttree.scan(root, Path(tmp) / "wd")
        got = {(x["folder"], x["name"]): x for x in rows}
        a = got.get(("20241101_Ford", "A.jpg"))
        b = got.get(("", "B.jpg"))
        ok = (r.returncode == 0 and len(rows) == 2 and a and b
              and a["day"] == "2024-11-01" and b["day"] is None
              and a["sha256"] == photo_desttree.sha256_file(
                  root / "20241101_Ford" / "A.jpg")
              and a["size"] == (root / "20241101_Ford" / "A.jpg").stat().st_size)
    return ok, f"rows={rows}"


@case
def scan_is_read_only_and_rehashes_only_new_or_changed_files():
    """GUARD (G15). The dest is byte for byte as it was; with `write` the
    cache sits beside the work dir, never in it and never in the dest, and a
    second scan hashes only the file that changed."""
    if photo_desttree is None:
        return False, "no scripts/photo_desttree.py"
    with tempfile.TemporaryDirectory() as tmp:
        root, wd = Path(tmp) / "sorted", Path(tmp) / "wd"
        wd.mkdir()
        for n in ("A", "B", "C"):
            jpeg(root / f"{n}.jpg", n)
        before = state(root)
        photo_desttree.scan(root, wd, write=True)
        dest_same = state(root) == before
        jpeg(root / "C.jpg", "changed")
        hashed = []
        real = photo_desttree.sha256_file
        photo_desttree.sha256_file = lambda p: hashed.append(Path(p).name) or real(p)
        try:
            rows = photo_desttree.scan(root, wd, write=True)
        finally:
            photo_desttree.sha256_file = real
        cache = (photo_desttree.cache_dir(wd) / photo_desttree.CACHE_NAME).is_file()
        fresh = {x["name"]: x["sha256"] for x in rows}["C.jpg"] == real(root / "C.jpg")
        wd_empty = not any(wd.iterdir())
    return (dest_same and hashed == ["C.jpg"] and fresh and cache and wd_empty), \
        f"hashed={hashed} dest_same={dest_same} cache={cache} wd_empty={wd_empty}"


@case
def scan_of_a_missing_or_empty_tree_never_calls_exiftool():
    """GUARD. exiftool given no file prints its man page and exits 0; a dest
    root that is not there, or holds nothing, is an empty tree."""
    if photo_desttree is None:
        return False, "no scripts/photo_desttree.py"
    calls = []
    real = photo_exiftool.run
    photo_exiftool.run = lambda *a, **k: calls.append(a) or real(*a, **k)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "empty").mkdir()
            a = photo_desttree.scan(Path(tmp) / "missing", tmp)
            b = photo_desttree.scan(Path(tmp) / "empty", tmp)
    finally:
        photo_exiftool.run = real
    return a == [] and b == [] and calls == [], f"calls={calls}"


@case
def same_size_other_bytes_is_never_a_twin():
    """GUARD (Lead, size + full SHA-256). Two files of the same size with
    different bytes are not twins, in the tree or in the dump."""
    if photo_desttree is None:
        return False, "no scripts/photo_desttree.py"
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        jpeg(t / "src" / "A.jpg", "aaaa")
        jpeg(t / "src" / "B.jpg", "bbbb")
        jpeg(t / "sorted" / "A.jpg", "cccc")
        srcs = [str(t / "src" / "A.jpg"), str(t / "src" / "B.jpg")]
        shas = {s: photo_desttree.sha256_file(s) for s in srcs}
        tree = photo_desttree.scan(t / "sorted", t / "wd")
        same_size = len({Path(s).stat().st_size for s in srcs}
                        | {tree[0]["size"]}) == 1
        got = photo_desttree.twins(shas, tree)
    return same_size and got == {}, f"twins={got}"


# ---------------------------------------------------------------------------
# M5 — twins skipped at copy
# ---------------------------------------------------------------------------

@case
def a_photo_already_in_the_tree_under_another_name_is_not_copied_again():
    """⭐ E57 REPRODUCTION. ⛔ FAILS on 11f5353: a byte-identical photo an
    earlier dump copied is copied again under its own name (`skip_dupe` 0).
    Now it is a skip row naming the tree file; the plan and the execution log
    list it; `verify --copied` proves its bytes are in the tree."""
    def earlier(tmp):
        shutil.copyfile(raw(tmp, "IMG_0102.jpg"),
                        ix_dir(sorted_root(tmp) / "20241101_old") / "P1010002.jpg")
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready_with(tmp, before=earlier)
        r = fx.finish(wd)
        got = fx.copied(tmp)
        v = verify(wd)
        plan, log = plan_text(wd), exec_text(wd)
    return (r.returncode == 0 and f"{LOTUS}/IMG_0101.jpg" in got
            and not any(p.endswith("/IMG_0102.jpg") for p in got)
            and "P1010002.jpg" in plan and "P1010002.jpg" in log and v.returncode == 0
            and "1 twin(s) found in the tree" in v.stdout), \
        f"rc={r.returncode} got={got} v={v.stdout[-300:]!r} plan={plan[-300:]!r}"


def ix_dir(p):
    Path(p).mkdir(parents=True, exist_ok=True)
    return Path(p)


@case
def a_finder_copy_inside_one_dump_is_copied_once():
    """⭐ E58 REPRODUCTION. ⛔ FAILS on 11f5353: `X.jpg` and `X 2.jpg` with
    the same bytes are both copied. Now `X.jpg` is copied and `X 2.jpg` is a
    skip row naming it."""
    rows = with_copy_in_dump("IMG_0101 2.jpg", "IMG_0101.jpg")
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready_with(tmp, rows=rows)
        r = fx.finish(wd)
        got = fx.copied(tmp)
        v = verify(wd)
        log = exec_text(wd)
    return (r.returncode == 0 and f"{LOTUS}/IMG_0101.jpg" in got
            and not any("IMG_0101 2" in p for p in got)
            and "IMG_0101 2.jpg" in log and v.returncode == 0), \
        f"rc={r.returncode} got={got} v={v.stdout[-300:]!r}"


@case
def a_no_date_twin_is_skipped_too():
    """⭐ E58 on the no-date plan. ⛔ FAILS on 11f5353: a no-EXIF still that
    is already in the tree is copied again into the to-be-checked bucket."""
    def earlier(tmp):
        shutil.copyfile(raw(tmp, "NODATE.jpg"),
                        ix_dir(sorted_root(tmp) / "inbox") / "NODATE_old.jpg")
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready_with(tmp, before=earlier)
        r = fx.finish(wd)
        got = fx.copied(tmp)
        v = verify(wd)
    return (r.returncode == 0
            and [p for p in got if "NODATE" in p] == ["inbox/NODATE_old.jpg"]
            and v.returncode == 0), f"rc={r.returncode} got={got} v={v.stdout[-300:]!r}"


@case
def same_name_other_bytes_keeps_the_collision():
    """GUARD (E55 is NOT a twin). An older, different copy under the same
    name in a folder the dump writes into is still today's `collision`: not
    skipped, nothing overwritten, finish exits 1."""
    def earlier(tmp):
        jpeg(ix_dir(sorted_root(tmp) / LOTUS) / "IMG_0101.jpg", "an older smaller copy")
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready_with(tmp, before=earlier)
        old = (sorted_root(tmp) / LOTUS / "IMG_0101.jpg").read_bytes()
        r = fx.finish(wd)
        kept = (sorted_root(tmp) / LOTUS / "IMG_0101.jpg").read_bytes() == old
        log = exec_text(wd)
    return r.returncode == 1 and kept and "collision" in log, \
        f"rc={r.returncode} kept={kept}"


@case
def a_copied_file_is_never_a_twin_of_its_own_copy():
    """GUARD. After the copy, a re-render finds this dump's own copies in the
    tree; none of them makes its source a twin, and the copy check still
    counts every file copied."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready_with(tmp)
        r = fx.finish(wd)
        ix.run("unfreeze", wd, "--reason", "test")
        code, out, _err = ix.run("render", wd)
        index, _view, _ = ix.index_of(tmp)
        skips = [f["source"] for f in index["files"] if f["route"] == "skip_dupe"]
    return (r.returncode == 0 and code == 0 and skips == []
            and "0 twin(s)" in out), f"skips={skips} out={out[-300:]!r}"


@case
def a_render_dry_run_writes_no_cache():
    """GUARD (LL-PHO-205/208). `render --dry-run` hashes in memory: the work
    dir, the hash cache beside it and the dest are byte for byte as before."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp)
        jpeg(sorted_root(tmp) / "x" / "A.jpg", "a")
        ix.run("init", wd)
        before = state(tmp)
        code, out, _err = ix.run("render", wd, "--dry-run")
        after = state(tmp)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    return code == 0 and changed == [], f"changed={changed} out={out[-200:]!r}"


@case
def a_twin_gone_before_the_copy_is_copied_and_said():
    """GUARD (Lead, G16). The tree changed between the freeze and the copy:
    the twin's file is gone, so the source is copied where it would have
    gone, the copy says so, and `verify --copied` still passes."""
    def earlier(tmp):
        shutil.copyfile(raw(tmp, "IMG_0102.jpg"),
                        ix_dir(sorted_root(tmp) / "20241101_old") / "P1010002.jpg")
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready_with(tmp, before=earlier)
        (sorted_root(tmp) / "20241101_old" / "P1010002.jpg").unlink()
        r = fx.finish(wd)
        got = fx.copied(tmp)
        v = verify(wd)
        log = exec_text(wd)
    return (r.returncode == 0 and f"{LOTUS}/IMG_0102.jpg" in got
            and "twin gone or changed" in r.stdout and "twin gone or changed" in log
            and v.returncode == 0), \
        f"rc={r.returncode} got={got} v={v.stdout[-300:]!r} out={r.stdout[-300:]!r}"


@case
def verify_fails_when_a_twin_leaves_the_tree_after_the_copy():
    """GUARD (G16). `verify --copied` proves every source's bytes are in the
    tree: a twin whose tree file is removed after the copy fails it."""
    def earlier(tmp):
        shutil.copyfile(raw(tmp, "IMG_0102.jpg"),
                        ix_dir(sorted_root(tmp) / "20241101_old") / "P1010002.jpg")
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ready_with(tmp, before=earlier)
        r = fx.finish(wd)
        (sorted_root(tmp) / "20241101_old" / "P1010002.jpg").unlink()
        v = verify(wd)
    return (r.returncode == 0 and v.returncode == 1
            and "twin not in the tree: IMG_0102.jpg" in v.stdout), \
        f"rc={r.returncode} v={v.returncode} {v.stdout[-300:]!r}"


@case
def a_missing_dest_root_is_said_in_the_plan_and_the_log():
    """GUARD (Lead). A wrong dest path must not pass as "no twins": the
    render, the plan and the execution log say the tree was not found and
    0 files were scanned."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp)
        ix.run("init", wd)
        code, out, _err = ix.run("render", wd)
        for cmd in ("check", "freeze"):
            ix.run(cmd, wd)
        fx.finish(wd)
        plan, log = plan_text(wd), exec_text(wd)
    said = "dest tree: not found, 0 files scanned"
    return (code == 0 and said in out and said in plan and said in log), \
        f"out={said in out} plan={said in plan} log={said in log}"


@case
def a_dump_twin_of_a_ref_duplicate_is_proved_through_it():
    """GUARD (D5 merge). `X.jpg` is a `--ref` duplicate of a file already in
    a hand-named folder (never copied), and `X 2.jpg` is its dump twin: the
    copy check follows `X.jpg` to that folder's file, and fails once that
    file is gone."""
    import photo_desttree as dt
    import photo_index
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        jpeg(t / "hand" / "X.jpg", "x")
        sha = dt.sha256_file(t / "hand" / "X.jpg")
        x, x2 = str(t / "raw" / "X.jpg"), str(t / "raw" / "X 2.jpg")
        shas = {x: sha, x2: sha}
        twin_map = {x2: {"twin": x, "kind": "dump", "sha256": sha}}
        dupes = {x: str(t / "hand" / "X.jpg"), x2: x}
        held = photo_index.twin_in_tree(x2, x, shas, {}, twin_map, dupes)
        (t / "hand" / "X.jpg").unlink()
        gone = photo_index.twin_in_tree(x2, x, shas, {}, twin_map, dupes)
    return held and not gone, f"held={held} gone={gone}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failures = []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
        try:
            ok, detail = fn()
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  "
                  f"{fn.__name__.replace('_', ' ').ljust(width)}"
                  + (f"   {detail}" if not ok else ""))
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} desttree cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
