#!/usr/bin/env python3
"""A45 cases — a re-apply must not destroy a look that was really spent.

`photo_see.apply_decisions()` builds one entry per pool file from the CURRENT
see-report. A second `--apply` on a batch whose selection has moved therefore
used to overwrite the labels of frames that fell off the new see-list — and a
`viewed-image:` frame carrying the agent's own phrase came back `clip-matched:`
holding a zero-shot class word, at exit 0.

That matters beyond the lost phrase: `[who]` is legal under N-4 only because a
model looked at the frame, so the downgrade removes the evidence that permits
a name while leaving a plausible label in place. ⛔ And it is unrepairable —
the assertion in `apply_decisions` refuses a decision naming a path the current
report did not select, so the look cannot be re-stamped afterwards.

⛔ THE FIXTURE IS A REAL PIPELINE ARTIFACT, NOT A HAND-BUILT ONE (LL-PHO-176).
`existing` is read from the golden fixture set's `tier3cat/…/see-labels.json`
(no fixture set → every case skips, naming `$PHOTO_GOLDEN_FIXTURES`), a file the
engine actually wrote, and `the_fixture_is_shaped_like_a_real_artifact` is the
cheap key-diff that would have caught U-2's mistake: those fixtures carried a
`subject_id` that `photo_see` never writes on a first dump, so two green tests
answered a question nobody was asking. The one thing built here is the
`samples/` thumbnails, because `tests/golden` ships none and the fabrication
guard needs bytes to check.

⚠️ NO PACK-ROUTE CASES, deliberately. The usual A42 rule does not apply:
`apply_decisions()` takes no pack, resolves none, and reads none — a route
case here would assert nothing and imply coverage that does not exist.

  python3 tests/apply_merge_cases.py [-v]

Exit 0 = pass. Everything is built in a temp dir; no drive is read.
"""

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))
import golden_replay  # noqa: E402
import photo_evidence  # noqa: E402
import photo_see  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

CASES = []


class Skipped(Exception):
    """No fixture set to read. Neither a pass nor a failure — printed with its
    reason and counted apart, the photo_memory_cases.py rule."""


def fixture(*parts):
    """-> a path under the golden fixture root, resolved by the replay
    harness's ONE resolver (--fixtures > $PHOTO_GOLDEN_FIXTURES >
    tests/golden). Raises Skipped when that file is not there."""
    path = golden_replay.fixture_root().joinpath(*parts)
    if not path.is_file():
        raise Skipped(f"no fixture at {path} — point "
                      f"${golden_replay.ENV_FIXTURES} at a fixture set")
    return path


def case(fn):
    CASES.append(fn)
    return fn


def real_entries():
    path = fixture("tier3cat", "input", "classify", "batch-01", "see-labels.json")
    return json.loads(path.read_text(encoding="utf-8"))["labels"]


def viewed_entries(entries):
    return [e for e in entries
            if e.get("provenance") == photo_evidence.VIEWED and e.get("sample")]


def make_samples(root, entries):
    """The thumbnails the fabrication guard checks. `tests/golden` ships none,
    so they are written here — real image magic, one file per claim, never one
    thumbnail shared (that is its own refusal)."""
    samples = Path(root) / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    for e in entries:
        if e.get("sample"):
            (samples / e["sample"]).write_bytes(PNG)
    return samples


def report_for(entries, selected_paths):
    """A see-report over the SAME files the real artifact names, with
    `selected` set to whichever of them this run is pretending to have picked.
    Only the scaffolding is constructed; every path, label and provenance in
    play comes from the artifact."""
    by_path = {e["path"]: e for e in entries}
    return {
        "engine": "test", "batch": 1,
        "selected": [{"path": p, "sample": by_path[p].get("sample"),
                      "rung": 1, "reason": "fixture"}
                     for p in selected_paths],
        "clusters": [{"cluster": i, "representative": e["path"],
                      "members": [e["path"]]}
                     for i, e in enumerate(entries)],
        "provisional": [{"path": e["path"], "label": None, "provenance": None,
                         "from": None} for e in entries],
    }


def apply(report, decisions, samples, existing=None):
    return photo_see.apply_decisions(report, decisions, samples,
                                     existing=existing)


def prov_of(entries, path):
    for e in entries:
        if e["path"] == path:
            return e.get("provenance"), e.get("label")
    return None, None


# ---------------------------------------------------------------------------
# the fixture itself is the first thing under test (LL-PHO-176)
# ---------------------------------------------------------------------------

@case
def the_fixture_is_shaped_like_a_real_artifact():
    """⛔ The cheap check that would have caught U-2's fixture defect: diff the
    fixture's KEYS against a real artifact's. This one IS the real artifact, so
    what it asserts is that the shape still holds — and, pointedly, that a real
    see-label carries NO `subject_id`. U-2 shipped two green renderer tests
    whose hand-built labels carried one; the claim was true and the defect
    survived both."""
    entries = real_entries()
    keys = set().union(*(set(e) for e in entries))
    ids = [e for e in entries
           for s in photo_evidence.subject_list(e) if s.get("subject_id")]
    return (keys <= {"path", "label", "provenance", "sample", "note",
                     "subject", "subjects", "subject_provenance", "from"}
            and "path" in keys and not ids and len(viewed_entries(entries)) >= 2), \
        f"keys={sorted(keys)}, entries_with_subject_id={len(ids)}"


# ---------------------------------------------------------------------------
# the defect
# ---------------------------------------------------------------------------

@case
def a_viewed_label_survives_a_reselection_that_drops_its_frame():
    """REPRODUCTION. ⛔ FAILS on d694be8. Two frames were looked at; the
    selection then moves and keeps only one. On the unfixed code the dropped
    frame comes back with the provisional entry — its look, and the phrase the
    look produced, both gone at exit 0."""
    entries = real_entries()
    v = viewed_entries(entries)
    keep, dropped = v[0], v[1]
    with tempfile.TemporaryDirectory() as tmp:
        samples = make_samples(tmp, entries)
        first = apply(report_for(entries, [keep["path"], dropped["path"]]),
                      {keep["path"]: keep["label"],
                       dropped["path"]: dropped["label"]}, samples)
        second = apply(report_for(entries, [keep["path"]]),
                       {keep["path"]: keep["label"]}, samples,
                       existing=first)
    prov, label = prov_of(second, dropped["path"])
    return (prov == photo_evidence.VIEWED and label == dropped["label"]), \
        f"dropped frame came back as {prov!r} / {label!r}"


@case
def the_surviving_frame_is_not_disturbed():
    """GUARD. The frame still on the see-list is re-applied normally — the fix
    must not turn every entry into a preserved one."""
    entries = real_entries()
    v = viewed_entries(entries)
    keep, dropped = v[0], v[1]
    with tempfile.TemporaryDirectory() as tmp:
        samples = make_samples(tmp, entries)
        first = apply(report_for(entries, [keep["path"], dropped["path"]]),
                      {keep["path"]: keep["label"],
                       dropped["path"]: dropped["label"]}, samples)
        second = apply(report_for(entries, [keep["path"]]),
                       {keep["path"]: keep["label"]}, samples, existing=first)
    kept = [e for e in second if e["path"] == keep["path"]][0]
    return (kept.get("provenance") == photo_evidence.VIEWED
            and not kept.get("preserved")), f"{kept}"


@case
def a_clip_matched_entry_never_overwrites_a_viewed_one():
    """GUARD — this single case is the whole defect in miniature. The dropped
    frame's cluster now zero-shot-matches, so the newly computed entry is a
    real `clip-matched:` label rather than a bare provisional one. It must
    still lose."""
    entries = real_entries()
    v = viewed_entries(entries)
    keep, dropped = v[0], v[1]
    with tempfile.TemporaryDirectory() as tmp:
        samples = make_samples(tmp, entries)
        first = apply(report_for(entries, [keep["path"], dropped["path"]]),
                      {keep["path"]: keep["label"],
                       dropped["path"]: dropped["label"]}, samples)
        rep = report_for(entries, [keep["path"]])
        for prov in rep["provisional"]:
            if prov["path"] == dropped["path"]:
                prov["label"] = "a zero-shot class word"
                prov["provenance"] = photo_evidence.CLIP_MATCHED
        second = apply(rep, {keep["path"]: keep["label"]}, samples,
                       existing=first)
    prov, label = prov_of(second, dropped["path"])
    return (prov == photo_evidence.VIEWED and label == dropped["label"]), \
        f"a clip-matched entry won: {prov!r} / {label!r}"


@case
def a_fresh_look_still_wins():
    """GUARD, the other direction. Re-applying is how a label is CORRECTED, so
    an equal-or-stronger claim must replace. ⛔ A fix that made the old entry
    always win would freeze the first look forever."""
    entries = real_entries()
    keep = viewed_entries(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        samples = make_samples(tmp, entries)
        first = apply(report_for(entries, [keep["path"]]),
                      {keep["path"]: keep["label"]}, samples)
        second = apply(report_for(entries, [keep["path"]]),
                       {keep["path"]: "a corrected phrase"}, samples,
                       existing=first)
    prov, label = prov_of(second, keep["path"])
    return (prov == photo_evidence.VIEWED and label == "a corrected phrase"), \
        f"{prov!r} / {label!r}"


# ---------------------------------------------------------------------------
# what must not have moved
# ---------------------------------------------------------------------------

@case
def a_first_apply_is_unchanged():
    """GUARD — the one that protects `golden_replay`. With nothing to merge,
    the merge does not run and the output is what it always was."""
    entries = real_entries()
    keep = viewed_entries(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        samples = make_samples(tmp, entries)
        rep, dec = report_for(entries, [keep["path"]]), {keep["path"]: keep["label"]}
        none_ = apply(copy.deepcopy(rep), dec, samples)
        empty = apply(copy.deepcopy(rep), dec, samples, existing=[])
    return (none_ == empty
            and not any(e.get("preserved") for e in none_)), \
        "a first apply gained a preserved entry"


@case
def an_unknown_path_is_still_refused():
    """GUARD. ⛔ Do not weaken the assertion: it is what stops a decision file
    from another batch being absorbed."""
    entries = real_entries()
    keep = viewed_entries(entries)[0]
    with tempfile.TemporaryDirectory() as tmp:
        samples = make_samples(tmp, entries)
        try:
            apply(report_for(entries, [keep["path"]]),
                  {"/nowhere/never-selected.jpg": "x"}, samples)
        except AssertionError as exc:
            return "never selected" in str(exc), str(exc)[:120]
    return False, "no AssertionError for an unselected path"


@case
def a_preserved_claim_still_needs_its_thumbnail():
    """GUARD — the fabrication guard must still bite. `preserved` exempts an
    entry from the SEE-LIST test and from nothing else: delete the thumbnail
    and the claim is refused again. ⛔ This is what makes A45 a narrowing of
    one membership test rather than a hole in the 2026-07-20 guard."""
    entries = real_entries()
    v = viewed_entries(entries)
    keep, dropped = v[0], v[1]
    with tempfile.TemporaryDirectory() as tmp:
        samples = make_samples(tmp, entries)
        first = apply(report_for(entries, [keep["path"], dropped["path"]]),
                      {keep["path"]: keep["label"],
                       dropped["path"]: dropped["label"]}, samples)
        rep = report_for(entries, [keep["path"]])
        second = apply(rep, {keep["path"]: keep["label"]}, samples,
                       existing=first)
        (samples / dropped["sample"]).unlink()
        problems = photo_evidence.viewed_claim_problems(
            second, {e["path"] for e in rep["selected"]}, samples, report=rep)
    return (any("no thumbnail" in p and dropped["path"] in p
                for p in problems)), f"problems={problems}"


@case
def an_unpreserved_promotion_is_still_refused():
    """GUARD against the obvious wrong fix — exempting every off-list entry
    instead of only carried-forward ones. An entry that claims `viewed-image:`
    without `preserved` and without being on the see-list is still a
    fabrication."""
    entries = real_entries()
    v = viewed_entries(entries)
    keep, forged = v[0], v[1]
    with tempfile.TemporaryDirectory() as tmp:
        samples = make_samples(tmp, entries)
        rep = report_for(entries, [keep["path"]])
        claim = [{"path": forged["path"], "label": forged["label"],
                  "provenance": photo_evidence.VIEWED,
                  "sample": forged["sample"]}]
        problems = photo_evidence.viewed_claim_problems(
            claim, {e["path"] for e in rep["selected"]}, samples, report=rep)
    return any("never selected it" in p for p in problems), f"{problems}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    failures, skipped = [], []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
        try:
            ok, detail = fn()
        except Skipped as why:
            skipped.append(fn.__name__)
            print(f"  skip  {fn.__name__.replace('_', ' ').ljust(width)}   {why}")
            continue
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  "
                  f"{fn.__name__.replace('_', ' ').ljust(width)}"
                  + (f"   {detail}" if not ok else ""))

    ran = len(CASES) - len(skipped)
    print(f"\n{ran - len(failures)}/{ran} apply-merge cases passed"
          + (f", {len(skipped)} skipped" if skipped else "")
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
