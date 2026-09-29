#!/usr/bin/env python3
"""Cases for photo_quickscan.py's YEAR LABEL — the D-19 defect class.

The label is what a human reads when reviewing proposed processing groups, and
it used to be the LATEST sampled year: `unit_year()` returned
`exif_range[1][:4]`, the max. Measured on a real 990-file dump — 923 of 923
dated camera files in 2024 — the unit was labelled **2025**, because two chat
screenshots saved the following January sorted last by filename and were
picked by the sample. Two files out of 990 set the label for all of them.

⛔ The sample is deliberately NOT random: it takes the first, middle and last
file by NAME plus a stride. That is fine for the date RANGE, which the report
declares an estimate, and it is exactly why an extreme of that sample may not
decide the year.

  ./.venv/bin/python3 tests/photo_quickscan_cases.py [-v]

Exit 0 = pass. No files are read and exiftool is never called: `unit_year()`
is fed the sampled years directly, which is the unit the decision is made on.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import photo_quickscan as qs  # noqa: E402

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def unit(name="dump", years=None, rng=None):
    """A scanned unit as `main()` builds one, carrying only what the label
    reads: the sampled year counts, the sampled range, and the folder name."""
    u = {"name": name, "files": 1, "bytes": 1}
    if years is not None:
        u["exif_years"] = years
    if rng is not None:
        u["exif_range"] = rng
    return u


@case
def a_late_straggler_does_not_set_the_year():
    """⛔ THE REPRODUCTION, at the real proportion measured on the dump: a
    2024 camera dump with a couple of 2025 chat screenshots saved into it."""
    got = qs.unit_year(unit(years={"2024": 4, "2025": 1},
                            rng=("2024-09-28", "2025-01-11")))
    return None if got == "2024" else f"labelled {got!r}, not 2024"


@case
def the_year_is_the_modal_one_not_the_last_one():
    """The same rule stated as a property rather than as one dump: whichever
    year holds most of the sample wins, in either direction, so this cannot
    be satisfied by a fix that simply swapped max for min."""
    problems = []
    late = qs.unit_year(unit(years={"2019": 1, "2023": 6}))
    if late != "2023":
        problems.append(f"a mostly-2023 unit labelled {late!r}")
    early = qs.unit_year(unit(years={"2019": 6, "2023": 1}))
    if early != "2019":
        problems.append(f"a mostly-2019 unit labelled {early!r}")
    return "; ".join(problems) or None


@case
def a_tie_breaks_to_the_earlier_year_and_is_deterministic():
    """⛔ A tie is REACHABLE — the measured dump was one screenshot away from
    it — and `Counter.most_common` breaks ties on insertion order, which is an
    answer nobody can reproduce from the output. A dump is named for when its
    photographs were taken; screenshots, chat saves and re-exports accrete
    afterwards, so the earlier year describes the dump rather than the
    sediment on top of it."""
    both_ways = [qs.unit_year(unit(years={"2024": 2, "2025": 2})),
                 qs.unit_year(unit(years={"2025": 2, "2024": 2}))]
    if both_ways != ["2024", "2024"]:
        return f"tie resolved to {both_ways} — order-dependent or later year"
    return None


@case
def a_unit_with_no_exif_still_falls_back_to_the_name():
    """A guard on the path the fix must not disturb: a dump exiftool could
    not read at all is still labelled from its folder name, exactly as
    before."""
    problems = []
    if qs.unit_year(unit(name="2019 holiday photos")) != "2019":
        problems.append("a name hint stopped being read")
    if qs.unit_year(unit(name="holiday photos")) is not None:
        problems.append("a nameless, dateless unit invented a year")
    # an EMPTY sample is not a sample: it must fall through to the name, not
    # answer from a table with nothing in it
    if qs.unit_year(unit(name="2019 holiday", years={})) != "2019":
        problems.append("an empty year table beat the name hint")
    return "; ".join(problems) or None


@case
def an_appledouble_file_never_reaches_the_sample():
    """`._*` files carry the media extension and no EXIF at all, so each one
    that reaches the pool burns a sample slot and returns nothing —
    `photo_scan.py:85` has excluded them since 2026-07-30 and quickscan did
    not. Measured on the real dump: 1 of 6 slots, and freeing it moved the
    range start from 2024-10-29 to 2024-09-28, the actual first capture.

    ⛔ This asserts WHICH FILES REACH EXIFTOOL, by capturing the argument
    list. The obvious version — hand it a pool of `._*` names and check the
    result is empty — passes with the filter DELETED, because those files do
    not exist and exiftool returns nothing either way. Measured: that version
    survived the mutant, so it tested nothing."""
    sample = getattr(qs, "exif_sample_dates", None)
    if sample is None:
        # ⛔ a FAIL line, not a traceback that hides every case after it:
        # the pre-D-19 engine has no such function
        return "photo_quickscan has no exif_sample_dates()"

    seen = []

    class Reply:
        stdout = "[]"

    def fake_run(options, files, timeout=None):
        seen.extend(Path(f).name for f in files)
        return Reply()

    pool = [Path(f"/raw/IMG_{i:04d}.jpg") for i in range(1, 9)]
    pool += [Path("/raw/._IMG_0001.jpg"), Path("/raw/._IMG_0008.jpg")]
    real_run, real_which = qs.photo_exiftool.run, qs.shutil.which
    qs.photo_exiftool.run = fake_run
    qs.shutil.which = lambda _name: "/usr/bin/exiftool"
    try:
        sample(pool, 3)
    finally:
        qs.photo_exiftool.run, qs.shutil.which = real_run, real_which

    # the precondition, asserted: the stub really was called, or "no hidden
    # file was sampled" is true of a call that never happened
    if not seen:
        return "exiftool was never called — the case measured nothing"
    hidden = [n for n in seen if n.startswith("._")]
    if hidden:
        return f"AppleDouble file(s) reached the sample: {hidden}"
    return None


@case
def the_report_names_every_skipped_file_and_why():
    """F1 — `junk skipped: 3` was the whole disclosure. Measured on a real
    round: the count was right (three `._*` AppleDouble sidecars), and the
    tester still could not tell whether anything of theirs had been dropped,
    because nothing said WHICH files or WHY.

    ⛔ Not a case against the exclusion: AppleDouble files stay excluded. It
    asserts the report, on a real folder run through `main()`, names each
    skipped file, gives its reason, and says whether the picture an
    AppleDouble file belongs to was counted — the one fact that answers
    "was anything of mine dropped?"."""
    import io
    import tempfile
    from contextlib import redirect_stdout

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw" / "unit-a"
        raw.mkdir(parents=True)
        for name in ("IMG_0001.jpg", "._IMG_0001.jpg", "._IMG_0404.jpg",
                     ".DS_Store"):
            (raw / name).write_bytes(b"x")
        out = Path(tmp) / "out"
        argv = sys.argv
        sys.argv = ["photo_quickscan.py", str(raw.parent), "--no-exif",
                    "--out", str(out)]
        try:
            with redirect_stdout(io.StringIO()):
                qs.main()
        finally:
            sys.argv = argv
        md = (out / "quickscan.md").read_text(encoding="utf-8")

    problems = []
    if "junk skipped: 3" not in md:
        problems.append("the count itself changed — it was correct")
    for name in ("._IMG_0001.jpg", "._IMG_0404.jpg", ".DS_Store"):
        if name not in md:
            problems.append(f"{name} is counted but never named")
    lines = {ln.split("`")[1]: ln for ln in md.splitlines()
             if ln.startswith("- `")}
    if "AppleDouble" not in lines.get("._IMG_0001.jpg", ""):
        problems.append("an AppleDouble file is named without saying what it is")
    if "IMG_0001.jpg" not in lines.get("._IMG_0001.jpg", "").split("—", 1)[-1] \
            or "counted" not in lines.get("._IMG_0001.jpg", ""):
        problems.append("the sidecar does not say its picture was counted")
    if "not in this folder" not in lines.get("._IMG_0404.jpg", ""):
        problems.append("an orphaned sidecar reads the same as a paired one")
    return "; ".join(problems) or None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failed = 0
    for fn in CASES:
        problem = fn()
        if problem:
            failed += 1
            print(f"FAIL  {fn.__name__}\n      {problem}")
        elif args.verbose:
            print(f"pass  {fn.__name__}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} quickscan cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
