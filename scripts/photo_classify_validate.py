#!/usr/bin/env python3
"""photo-classify Stage 3d — mechanical (no-LLM) fraud check on classified batches.

Catches the 2026-07-20 fabrication incident: an agent wrote "viewed sample: ..."
into a batch's note when classify/batch-NN/sample-report.json had zero real
sample images (all files "shared", no vision-verifiable thumbnail existed).

Convention this enforces going forward (bake into every classify prompt):
  - If sample-report.json samples == [] for a batch, its batches.json note
    MUST start with "gps-only:" or "exif-only:" (whichever evidence was
    actually used) — never claim to have viewed anything.
  - If samples exist, the note SHOULD start with "viewed-image:" when vision
    was actually used, so a human/script can trust the provenance tag instead
    of re-opening images to re-verify every run.

## VS-4 — the note is no longer the only thing checked

The check above reads a batch NOTE, which is one sentence an agent wrote. Once
the see controller exists there is a per-FILE record of what was looked at
(`see-report.json` → `selected`), what the model returned (`see-labels.json`)
and the thumbnails it was shown (`samples/`), and those can disagree with each
other in ways a note-level check cannot see. So when a batch has been through
the see stage this script additionally cross-checks the seen list against the
real generated thumbnails — the DESIGN's validator line, verbatim — using the
SAME rules the memorize loop applies (`photo_evidence`), because a look that
is good enough to label a file is exactly a look that is good enough to become
a recognition exemplar, and two definitions of that would eventually differ.

What that adds, concretely: a `clip-matched:` or `clip-propagated:` label can
never claim `viewed-image:`; a `viewed-image:` label needs a thumbnail that is
a real, non-empty image file inside the batch's own `samples/`, not a symlink,
not a `../` escape, and not one another file is already using as its evidence.

Stdlib only, no numpy, no model — this has to run anywhere.

This script only flags; it never rewrites notes (a human/agent decides the fix).

Usage:
  python3 photo_classify_validate.py "<Working Files>/<unit>" [--batch N]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import photo_evidence  # noqa: E402

# i18n-guard:allow-begin — locale detection data, not user-facing output.
# Words an agent's own note may use to claim it looked at an image; the
# claim can arrive in any language the agent was writing in, so the pattern
# reads them all.
VISUAL_CLAIM = re.compile(r"\b(viewed|saw|看到|viewed sample|viewed image)\b", re.I)
# i18n-guard:allow-end
HONEST_PREFIX = re.compile(r"^(gps-only|exif-only|viewed-image)\s*:", re.I)


def see_stage_problems(batch_dir):
    """-> list of problems from the per-file see-stage record, or [] when this
    batch never went through the see stage (which is not a problem: the note
    check above is the whole contract for a batch classified the old way)."""
    report_path = batch_dir / "see-report.json"
    if not report_path.is_file():
        return []
    try:
        report = json.loads(report_path.read_text())
    except ValueError as exc:
        return [f"see-report.json is unreadable: {exc}"]

    samples_dir = photo_evidence.samples_dir_of(report_path, report)
    selected = report.get("selected") or []
    problems = []

    # 1. every file the controller PICKED has a thumbnail that is really there.
    #    Without this the vision model was handed nothing for those files and
    #    whatever came back for them was not a look.
    for entry in selected:
        found = photo_evidence.sample_problems(entry.get("sample"), samples_dir)
        problems += [f"selected {entry.get('path')}: {p}" for p in found]

    # 2. every applied label that CLAIMS a look survives the same rules the
    #    memorize loop applies before it will make one permanent.
    labels_path = batch_dir / "see-labels.json"
    if labels_path.is_file():
        try:
            entries = json.loads(labels_path.read_text()).get("labels") or []
        except ValueError as exc:
            return problems + [f"see-labels.json is unreadable: {exc}"]
        problems += photo_evidence.viewed_claim_problems(
            entries, {e.get("path") for e in selected}, samples_dir,
            report=report)
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir")
    ap.add_argument("--batch", type=int)
    args = ap.parse_args()
    workdir = Path(args.workdir).resolve()

    bdata = json.loads((workdir / "batches.json").read_text())
    flags = []
    for b in bdata["batches"]:
        n = b["batch"]
        if args.batch is not None and n != args.batch:
            continue
        if b.get("status") != "classified":
            continue
        note = b.get("note", "")
        batch_dir = workdir / "classify" / f"batch-{n:02d}"
        report_path = batch_dir / "sample-report.json"
        nsamples = None
        if report_path.exists():
            report = json.loads(report_path.read_text())
            nsamples = len(report.get("samples", []))

        problems = []
        if nsamples == 0 and VISUAL_CLAIM.search(note) and not note.lower().startswith(("gps-only", "exif-only")):
            problems.append("claims a visual observation but 0 sample images exist "
                             "(fabrication pattern)")
        if not HONEST_PREFIX.match(note):
            problems.append("note missing required provenance prefix "
                             "(gps-only: / exif-only: / viewed-image:)")
        problems += see_stage_problems(batch_dir)
        if problems:
            flags.append({"batch": n, "nsamples": nsamples, "note": note,
                          "problems": problems})

    if not flags:
        print(f"OK — all classified batches in {workdir.name} pass the mechanical check.")
        return
    print(f"FLAGGED {len(flags)} batch(es) in {workdir.name}:")
    for f in flags:
        print(f"  B{f['batch']:>3}  samples={f['nsamples']}  {f['problems']}")
        print(f"       note: {f['note'][:120]}")
    sys.exit(1)


if __name__ == "__main__":
    main()
