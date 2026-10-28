#!/usr/bin/env python3
"""The owner-fact guard, run on a scratch repo it has never seen (RS7d).

`no_owner_facts.py` finds its repo from its own location, so each case copies
the guard into a temp tree beside a made-up term list and made-up files, runs
it, and reads its owner-term line. No real owner term appears here: the one
term is invented.

  python3 tests/owner_guard_cases.py

Exit 0 = pass. Stdlib only, no network, nothing outside a temp dir.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
GUARD = HERE / "no_owner_facts.py"
HOOK = REPO / ".githooks" / "pre-commit"
# the files the guard's CJK waivers name: without them the scratch repo fails
# "every waiver still covers real debt" and every commit is refused for that
WAIVED = ("tests/waivers.py", "tests/photo_see_cases.py",
          "tests/photo_embed_cases.py")
TERM = "zqxinventedterm"      # belongs to nobody

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def run_guard(files):
    """-> (count of owner hits, the paths reported) for a scratch repo
    holding `files` {relpath: text} plus the guard and a one-term list."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()   # /var is a symlink on macOS
        (root / "tests").mkdir()
        shutil.copy(GUARD, root / "tests" / GUARD.name)
        (root / "tests" / ".owner-terms.json").write_text(
            json.dumps({"terms": [TERM]}), encoding="utf-8")
        (root / ".gitignore").write_text(".owner-terms.json\n", encoding="utf-8")
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        out = subprocess.run([sys.executable, str(root / "tests" / GUARD.name), "-v"],
                             capture_output=True, text=True, encoding="utf-8",
                             cwd=root)
        out = out.stdout + out.stderr
    line = next((l for l in out.splitlines() if "no owner facts in" in l), "")
    m = re.search(r"(\d+) (?:found|unwaived)", line)
    reported = re.findall(r"^\s+(\S+):\d+\s*$", out, re.M)
    return (int(m.group(1)) if m else None), reported, out


@case
def an_owner_term_in_a_waived_file_is_still_reported():
    """REPRODUCTION. ⛔ FAILS on bf3d2b6: `tests/waivers.py` is whole-file
    waived for its CJK strings, and the owner half honoured that waiver, so an
    owner term inside it was counted as "waived" and passed."""
    n, reported, out = run_guard(
        {"tests/waivers.py": f"# a note that names {TERM} by mistake\n"})
    ok = n == 1 and "tests/waivers.py" in reported
    return ok, f"found={n} reported={reported}"


@case
def an_owner_term_in_the_hook_dirs_is_reported():
    """REPRODUCTION. ⛔ FAILS on bf3d2b6: `.githooks/` and `.github/` ship in
    the zip but were never scanned, and the hook has no file extension."""
    n, reported, out = run_guard({
        ".githooks/pre-commit": f"#!/bin/sh\n# runs on {TERM}'s machine\n",
        ".github/workflows/guard.yml": f"# owner half runs on {TERM}'s machine\n"})
    want = {".githooks/pre-commit", ".github/workflows/guard.yml"}
    ok = n == 2 and want <= set(reported)
    return ok, f"found={n} reported={reported}"


@case
def a_clean_scratch_repo_reports_nothing():
    """GUARD. The positive control: with no term anywhere, zero hits, so the
    two cases above are not counting something the scratch tree adds."""
    n, reported, out = run_guard({"tests/waivers.py": "# nothing here\n",
                                  ".githooks/pre-commit": "#!/bin/sh\n"})
    return n == 0, f"found={n} reported={reported}"

# --------------------------------------------------------------------------
# C-29: what a COMMIT stores, through the real pre-commit hook
# --------------------------------------------------------------------------
# ⛔ GIT_* scrubbed for every call here: this file may itself run under a
# hook, and an inherited GIT_DIR aims the scratch repo's git at the caller's.
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(root, *args, check=True):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                           "-c", "commit.gpgsign=false", *args], cwd=root,
                          env=CLEAN_ENV, capture_output=True, text=True,
                          check=check)


OWNER_CASE = "no owner facts in shippable paths"


class HookRepo:
    """A scratch repo holding the guard, the hook and the waived files, with
    a one-term private list and core.hooksPath set, committed clean once."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = root = Path(self._tmp.name).resolve() / "main"
        root.mkdir()
        git(root, "init", "-q", ".")
        for rel in ("tests/no_owner_facts.py", ".githooks/pre-commit",
                    ".gitignore", *WAIVED):
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / rel, dst)
        (root / "tests" / ".owner-terms.json").write_text(
            json.dumps({"terms": [TERM]}), encoding="utf-8")
        venv = REPO / ".venv"
        if venv.exists():
            (root / ".venv").symlink_to(venv.resolve(), target_is_directory=True)
        git(root, "config", "core.hooksPath", ".githooks")
        git(root, "add", "-A")
        first = git(root, "commit", "-qm", "clean", check=False)
        if first.returncode:
            raise RuntimeError("the clean first commit was refused: "
                               + (first.stdout + first.stderr)[-300:])
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()

    def head(self, root=None):
        return git(root or self.root, "rev-parse", "HEAD").stdout.strip()

    def write(self, rel, data, root=None):
        path = (root or self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return path

    def commit(self, *args, root=None, why=OWNER_CASE):
        """-> (refused, detail): refused = non-zero exit, HEAD unmoved, AND the
        guard case named `why` is the one that FAILED. A refusal for another
        reason (a crash, a stale waiver) would prove nothing here."""
        root = root or self.root
        before = self.head(root)
        out = git(root, "commit", "-qm", "probe", *args, check=False)
        moved = self.head(root) != before
        text = out.stdout + out.stderr
        failed = re.findall(r"FAILED: (.*)$", text, re.M)
        named = bool(failed) and why in failed[-1]
        refused = out.returncode != 0 and not moved and named
        return refused, (f"exit {out.returncode}, head "
                         f"{'moved' if moved else 'kept'}, failed: "
                         f"{failed[-1] if failed else '-'}")


def staged_then_cleaned(rel, staged, clean, why=OWNER_CASE):
    with HookRepo() as r:
        r.write(rel, staged)
        git(r.root, "add", rel)
        r.write(rel, clean)
        return r.commit(why=why)


@case
def a_staged_term_with_a_clean_disk_copy_is_refused():
    """⭐ REPRODUCTION (C-29). The guard read the DISK while a commit stores
    the STAGED blob: stage a term, clean the disk copy (`git add -p`, or an
    edit after `git add`), and the hook passed 9/9 with the term committed."""
    return staged_then_cleaned("scripts/leak.py",
                               f"# {TERM}\n", "# nothing here\n")


@case
def a_staged_term_whose_disk_file_is_deleted_is_refused():
    """⭐ REPRODUCTION (C-29). A NEW root file, staged, then deleted on disk.
    Root files were listed from disk at import, so this one was not even
    listed, let alone read."""
    with HookRepo() as r:
        r.write("NOTES.md", f"{TERM}\n")
        git(r.root, "add", "NOTES.md")
        (r.root / "NOTES.md").unlink()
        return r.commit()


@case
def a_staged_term_in_the_guard_itself_is_refused():
    """⭐ REPRODUCTION (C-29). The guard file and the .gitignore were read
    from disk too: a term staged into the guard, disk copy restored."""
    clean = GUARD.read_text(encoding="utf-8")
    return staged_then_cleaned("tests/no_owner_facts.py",
                               clean + f"# {TERM}\n", clean,
                               why="the guard itself names no owner terms")


@case
def a_staged_gitignore_that_drops_the_term_list_is_refused():
    """⭐ REPRODUCTION (C-29). The staged .gitignore no longer names the
    private list while the disk copy still does."""
    clean = (REPO / ".gitignore").read_text(encoding="utf-8")
    dropped = clean.replace("tests/.owner-terms.json", "# (dropped)")
    return staged_then_cleaned(".gitignore", dropped, clean,
                               why="the private term list is gitignored")


@case
def a_term_beside_a_non_utf8_byte_is_refused():
    """⭐ REPRODUCTION (C-29, second hole). A file that does not decode as
    UTF-8 was skipped whole: one 0xE9 byte hid the term on every line."""
    with HookRepo() as r:
        r.write("scripts/latin.py", b"# caf\xe9 " + TERM.encode() + b"\n")
        git(r.root, "add", "-A")
        return r.commit()


@case
def a_term_in_a_utf16_file_is_refused():
    """⭐ REPRODUCTION (C-29). A UTF-16 file failed to decode and was skipped;
    both byte orders are checked, the BOM-less big-endian one too."""
    results = []
    for enc in ("utf-16", "utf-16-be"):
        with HookRepo() as r:
            r.write("docs/notes.md", f"see {TERM}\n".encode(enc))
            git(r.root, "add", "-A")
            results.append(r.commit())
    return all(ok for ok, _ in results), "; ".join(d for _, d in results)


@case
def a_term_in_a_file_type_outside_the_text_list_is_refused():
    """⭐ REPRODUCTION (C-29). Only SUFFIXES were read, so an image (or a
    `.tmpl`) holding the term was never scanned."""
    with HookRepo() as r:
        r.write("docs/shot.jpg", b"\xff\xd8\xff\xe0JFIF\x00" + TERM.upper().encode()
                + b"\x00\xff\xd9")
        git(r.root, "add", "-A")
        return r.commit()


@case
def commit_all_reads_the_index_it_is_about_to_store():
    """GUARD (C-29). `git commit -a` hands the hook a TEMPORARY index
    (GIT_INDEX_FILE = .git/index.lock, measured 20261028). A fix that scrubs
    GIT_* reads .git/index instead and misses an unstaged edit -a adds."""
    with HookRepo() as r:
        r.write("tests/waivers.py", (REPO / "tests/waivers.py").read_bytes()
                + f"# {TERM}\n".encode())
        return r.commit("-a")


@case
def commit_of_a_named_path_reads_its_own_index():
    """GUARD (C-29). `git commit <path>` uses .git/next-index-*.lock."""
    with HookRepo() as r:
        r.write("tests/waivers.py", (REPO / "tests/waivers.py").read_bytes()
                + f"# {TERM}\n".encode())
        return r.commit("tests/waivers.py")


@case
def a_staged_term_is_refused_from_a_linked_worktree():
    """⭐ REPRODUCTION (C-29). The same hole from a linked worktree, where
    the hook gets the worktree's own GIT_DIR and index; the staged read must
    use them, not the main checkout's."""
    with HookRepo() as r:
        wt = r.root.parent / "wt"
        git(r.root, "worktree", "add", "-q", str(wt))
        venv = r.root / ".venv"
        if venv.is_symlink():
            (wt / ".venv").symlink_to(os.readlink(venv), target_is_directory=True)
        shutil.copy(r.root / "tests" / ".owner-terms.json",
                    wt / "tests" / ".owner-terms.json")
        r.write("scripts/leak.py", f"# {TERM}\n", root=wt)
        git(wt, "add", "scripts/leak.py")
        r.write("scripts/leak.py", "# nothing here\n", root=wt)
        return r.commit(root=wt)



BINARY_CASE = "no binary file ships unless allow-listed"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01" + bytes(64) + b"\xff\xd9"
# the OLE2 header a legacy .xls starts with, then padding
XLS = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(504)


@case
def a_staged_image_with_no_term_is_refused():
    """⭐ REPRODUCTION (G78). A binary cannot be scanned for an owner term
    with any confidence (a short UTF-16 or legacy form of a CJK name hits
    random bytes), so one that ships must be on BINARY_ALLOWED. On the C-29
    guard this image, holding no term, was committed."""
    with HookRepo() as r:
        r.write("docs/shot.jpg", JPEG)
        git(r.root, "add", "-A")
        return r.commit(why=BINARY_CASE)


@case
def a_staged_sheet_with_no_term_is_refused():
    """⭐ REPRODUCTION (G78). The same for a legacy spreadsheet blob."""
    with HookRepo() as r:
        r.write("templates/sheet.xls", XLS)
        git(r.root, "add", "-A")
        return r.commit(why=BINARY_CASE)


@case
def an_allow_listed_binary_is_accepted():
    """GUARD (G78). A path on BINARY_ALLOWED ships; the list is the guard's
    own, so the scratch copy of the guard is edited to name it."""
    with HookRepo() as r:
        guard = r.root / "tests" / "no_owner_facts.py"
        text = guard.read_text(encoding="utf-8")
        assert "BINARY_ALLOWED = ()" in text
        guard.write_text(text.replace("BINARY_ALLOWED = ()",
                                      'BINARY_ALLOWED = ("docs/shot.jpg",)'),
                         encoding="utf-8")
        r.write("docs/shot.jpg", JPEG)
        git(r.root, "add", "-A")
        before = r.head()
        out = git(r.root, "commit", "-qm", "allowed", check=False)
        moved = r.head() != before
        return out.returncode == 0 and moved, f"exit {out.returncode}, moved={moved}"


@case
def an_empty_placeholder_is_not_a_binary():
    """GUARD (G78). The repo's two empty .gitkeep files must keep passing."""
    with HookRepo() as r:
        r.write("templates/x/.gitkeep", b"")
        git(r.root, "add", "-A")
        before = r.head()
        out = git(r.root, "commit", "-qm", "keep", check=False)
        moved = r.head() != before
        return out.returncode == 0 and moved, f"exit {out.returncode}, moved={moved}"


@case
def a_clean_staged_commit_passes():
    """GUARD. The control: the same hook lets a clean change through, so the
    refusals above are about the term, not the scratch repo."""
    with HookRepo() as r:
        r.write("scripts/fine.py", "# nothing here\n")
        git(r.root, "add", "-A")
        before = r.head()
        out = git(r.root, "commit", "-qm", "fine", check=False)
        moved = r.head() != before
        return out.returncode == 0 and moved, f"exit {out.returncode}, moved={moved}"


@case
def a_direct_run_still_reads_the_disk():
    """GUARD (C-29). Without --staged the guard reads the disk as before: an
    unstaged term is reported by a direct run."""
    n, reported, out = run_guard({"scripts/draft.py": f"# {TERM}\n"})
    return n == 1 and "scripts/draft.py" in reported, f"found={n} reported={reported}"


def main():
    failed = 0
    for fn in CASES:
        try:
            ok, detail = fn()
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        failed += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {fn.__name__}   {detail}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} owner_guard cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
