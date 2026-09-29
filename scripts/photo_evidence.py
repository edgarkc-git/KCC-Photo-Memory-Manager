#!/usr/bin/env python3
"""VS-4 — what counts as PROOF that a vision model actually looked at a file.

Three places in the pipeline ask that one question, and before this module
each answered it differently:

  * `photo_see.assert_no_fabrication()` — may this label say `viewed-image:`?
  * `photo_subjects.Registry.add_exemplar()` — may this vector be memorized?
  * `photo_classify_validate.py` — does this batch's note tell the truth?

One answer, one place. The 2026-07-20 incident was a note claiming a visual
observation over a sample set that was empty; the memorize rule is the same
failure one step later, where the fabricated observation becomes permanent
recognition evidence. A guard that is a string comparison catches neither.

## What is checked, and what each check is for

A `viewed-image:` claim is proved by a THUMBNAIL — the downscaled viewable the
see controller generated is literally the only thing the model could have
opened. So the claim has to survive all of:

  1. the see controller SELECTED this path        (`see-report.json → selected`)
  2. the report records THIS sample for it        (not some other file's)
  3. the sample is a bare filename                (no `..`, no separator)
  4. it resolves INSIDE the batch's samples/      (symlinks resolved first)
  5. it is a real regular file, not a symlink     (a link can point anywhere)
  6. it is not empty                              (a touch(1) is not a photo)
  7. it starts with image magic bytes             (a text file named .jpg
                                                   is not something to look at)
  8. no other claim uses the same sample          (one thumbnail cannot be
                                                   evidence for two files)

Checks 3-7 are what make an ADVERSARIAL test possible at all: 1-2 are
satisfiable by editing one JSON, 3-7 need a real file with real bytes in the
one directory the pipeline wrote.

## Provenance vocabulary

`viewed-image:` / `clip-matched:` / `clip-propagated:` are the visual prefixes
(Visual-Sorting DESIGN, per-batch flow). `draft:` is the MEMORY maturity
prefix — the label rests on an `ai-drafted` fact — and it composes in front of
a visual one: `draft:clip-matched:` is a name proposed for an unconfirmed
subject that was never seen. Composition is what keeps the plan CSV auditable:
the operator needs to know both whether anybody looked AND whether the fact
behind the name is confirmed, and one prefix cannot say both.

`draft:viewed-image:` is a legal plan-CSV cell and is NEVER acceptable
memorize evidence — the look was real, the subject it was attributed to is
not. `is_view_confirmed()` is the one function allowed to answer that, and it
refuses anything but a bare `viewed-image`.

No dependencies beyond the standard library, on purpose: the memorize rule
must hold in a process that has no numpy, no model and no pack.
"""

import json
from pathlib import Path

VIEWED = "viewed-image:"
CLIP_MATCHED = "clip-matched:"
CLIP_PROPAGATED = "clip-propagated:"
DRAFT = "draft:"

# What a per-file visual label may claim.
VISUAL_PROVENANCE = (VIEWED, CLIP_MATCHED, CLIP_PROPAGATED)
# ...and what a plan-CSV WHO/WHAT cell may hold on top of that: the same three,
# each optionally carrying the memory-maturity prefix.
PLAN_PROVENANCE = VISUAL_PROVENANCE + tuple(DRAFT + p for p in VISUAL_PROVENANCE)

# The formats photo_embed.convert_to_thumbnail can produce. A thumbnail in any other
# format is not "an unsupported image", it is a file nobody generated here.
MAGIC = {b"\xff\xd8\xff": "jpeg", b"\x89PNG\r\n\x1a\n": "png"}

EVIDENCE_KEYS = ("see_report", "batch", "path", "sample")


# The two keys a see-label may name a subject under. `subject_id` is the
# registry key; `subject_kind` is the detector's class word for a subject
# nothing has identified. An entry carrying neither says nothing.
SUBJECT_KEYS = ("subject_id", "subject_kind")


def subject_list(entry):
    """-> the subjects one see-label entry names, as a LIST (R4).

    Lives here rather than in `photo_see` because BOTH ends of the wire have
    to agree about it and only one of them writes it: `photo_see` at --apply,
    `photo_plan.visual_columns()` at render time, months later, from a file on
    disk. This module is the one both already import and it carries no
    dependency beyond the standard library, which is the property that lets
    the reader run in a process with no numpy and no model.

    Two shapes are read, and this is the only place either is understood:

      {"subject": {...} | null}   pre-R4 — one subject per file, because
                                  `best_animal_box()` returned one box
      {"subjects": [{...}, ...]}  R4 — one entry per DETECTED subject, in
                                  detection order (highest-scoring first),
                                  which is what R3a made a frame able to yield

    ⛔ Reading the old shape is not politeness to old files, it is what keeps
    the frozen golden fixtures replayable: every `see-labels.json` under
    `tests/golden/` carries `subject`, and a reader that saw only `subjects`
    would report those files as holding no subject at all — which is a
    different claim from the one they make, and one that renders identically
    in a CSV cell.

    An entry naming neither an id nor a kind is dropped. `null` and `{}` said
    the same thing before this function existed and must keep saying it."""
    subjects = entry.get("subjects")
    if subjects is None:
        one = entry.get("subject")
        subjects = [one] if one else []
    return [s for s in subjects
            if isinstance(s, dict) and any(s.get(k) for k in SUBJECT_KEYS)]


# ------------------------------------------------------------ provenance ----

def normalize(value):
    """`viewed-image:` (plan-CSV prefix form) and `viewed-image` (pack schema
    form) are the same claim. One spelling reaches every comparison."""
    return str(value or "").strip().rstrip(":")


def split(value):
    """-> (draft?, base token). `draft:viewed-image:` -> (True, 'viewed-image').

    Only ONE `draft:` is stripped. `draft:draft:viewed-image:` is not a
    doubly-uncertain fact, it is a malformed prefix, and it must fail the
    membership check below rather than be normalized into something valid."""
    text = str(value or "").strip()
    drafted = text.startswith(DRAFT)
    if drafted:
        text = text[len(DRAFT):]
    return drafted, normalize(text)


# The only two strings that mean "a vision model opened this file": the pack
# schema's form and the plan CSV's prefix form. Deliberately EXACT rather than
# normalized — `normalize()` is lenient because it has to read what other
# tools wrote, and leniency in the one comparison that guards a permanent
# write is how ` viewed-image ` and `viewed-image::` get in. A provenance
# token is machine-written; a sloppy one means somebody edited it by hand.
VIEW_CONFIRMED_SPELLINGS = ("viewed-image", VIEWED)


def is_view_confirmed(value):
    """The memorize rule's whole question. True ONLY for one of the two exact
    spellings — a drafted look (`draft:viewed-image:`), a clip match, a
    propagated label and every near-spelling are all False."""
    return isinstance(value, str) and value in VIEW_CONFIRMED_SPELLINGS


def plan_provenance_problems(value, field):
    """A plan-CSV WHO/WHAT provenance cell. Empty is legal (nothing claimed);
    anything present must be one of the eight strings."""
    if not value:
        return []
    if value not in PLAN_PROVENANCE:
        return [f"{field} provenance {value!r} is not one of "
                f"{', '.join(PLAN_PROVENANCE)}"]
    return []


# -------------------------------------------------------------- thumbnail ---

def sample_problems(sample, samples_dir):
    """Checks 3-7: is there really something here that a model could open?"""
    if not sample:
        return ["no thumbnail is named at all — nothing was there to look at"]
    name = str(sample)
    if Path(name).name != name or name in (".", ".."):
        return [f"thumbnail {name!r} is not a bare filename — a claim may only "
                "point at the samples directory the pipeline wrote"]
    root = Path(samples_dir)
    path = root / name
    if path.is_symlink():
        return [f"thumbnail {name!r} is a symlink — the bytes a model would "
                "have seen are not the ones this directory holds"]
    if not path.is_file():
        return [f"no thumbnail {name!r} in {root} — nothing was there to look at"]
    try:
        resolved, inside = path.resolve(), root.resolve()
    except OSError as exc:                                  # pragma: no cover
        return [f"thumbnail {name!r} cannot be resolved: {exc}"]
    if resolved.parent != inside:
        return [f"thumbnail {name!r} resolves to {resolved}, outside {inside}"]
    head = path.read_bytes()[:16]
    if not head:
        return [f"thumbnail {name!r} is empty (0 bytes)"]
    if not any(head.startswith(m) for m in MAGIC):
        return [f"thumbnail {name!r} does not start with image magic bytes — "
                f"a file named like a thumbnail is not a thumbnail "
                f"(saw {head[:8]!r})"]
    return []


def duplicate_sample_problems(claims):
    """Check 8. `claims` is an iterable of (path, sample).

    One thumbnail backing two `viewed-image:` files is the cheapest possible
    forgery: generate one sample, then claim the whole batch was seen. The
    see controller never produces it — every pick gets its own viewable."""
    owners = {}
    problems = []
    for path, sample in claims:
        if not sample:
            continue
        first = owners.setdefault(sample, path)
        if first != path:
            problems.append(
                f"{path} and {first} both claim 'viewed-image:' through the same "
                f"thumbnail {sample!r} — one look cannot be evidence for two files")
    return problems


# ------------------------------------------------------------- see-report ---

def viewed_claim_problems(entries, seen_paths, samples_dir, report=None):
    """Every `viewed-image:` claim in one batch's labels, checked together.

    -> a list of problems, empty when the batch tells the truth. Returning a
    list rather than raising is what lets two callers with opposite jobs share
    one implementation: `photo_see.assert_no_fabrication()` raises on the
    first, because a pipeline has no safe way to continue past a fabricated
    look, and `photo_classify_validate.py` reports them all, because a
    reviewer wants the whole picture in one pass.

    **`preserved` (A45) exempts an entry from the SEE-LIST test and from
    nothing else.** A re-selection moves the see-list, so a frame that really
    was looked at under an earlier selection is no longer on the current one —
    and refusing it there is what used to destroy the look. ⛔ This is not a
    hole in the 2026-07-20 guard, and the reason is physical: `samples/` is
    ADDITIVE across re-runs (measured 20260909 — 5 thumbnails became 9 and the
    dropped frame's survived), so **the thumbnail IS the trace of having been
    selected**, and every thumbnail test below still runs on a preserved
    entry — it must exist, be a real image of a plausible size, not be a
    symlink or an escape, and not be another file's look. What the flag skips
    is one membership test in a list that has since changed; what it cannot
    skip is the evidence itself.

    ⛔ **`photo_see.apply_decisions()` sets `preserved` whenever the PRIOR
    claim was STRICTLY STRONGER than the recomputed one** — which includes
    `clip-propagated:` kept over `clip-matched:`, not `viewed-image:` alone.
    Only a prior `viewed-image:` can reach the exemption above, because that
    is the only claim this function tests; the others are stamped and never
    consulted here. ⚠️ Stated as the code behaves rather than as this
    exemption needs, because the narrower sentence is what a later change
    would be written against.

    ⛔ **STANDING CONSTRAINT — the trust chain holds because every writer of
    `see-labels.json` lives in `photo_see` and only ONE of them can create a
    claim.** `apply_decisions()` is the writer that builds entries, and it is
    the only thing that ever sets `preserved`; `record_confirmed_subject_ids()`
    (U-3) adds a `subject_id` to rows that already exist and ⛔ touches no
    `provenance`, no `label` and no `preserved`, so it can neither forge a
    claim nor exempt one. A preserved entry therefore still inherits a claim
    that passed this function when it was written. **A future writer outside
    that module, or one that edits `provenance`, turns this exemption into a
    hole** — such a writer must either refuse to emit `preserved` or run this
    check itself.

    ⚠️ Read on the entry, not passed in as a set, so all three callers agree.
    A per-call-site rule here is the drift this module exists to prevent."""
    samples_dir = Path(samples_dir)
    recorded = {e.get("path"): e.get("sample")
                for e in ((report or {}).get("selected") or [])}
    problems, claims = [], []
    for entry in entries:
        prov = entry.get("provenance")
        path = entry.get("path")
        if prov is None:
            continue
        if prov not in VISUAL_PROVENANCE:
            problems.append(f"{path}: unknown provenance prefix {prov!r} — "
                            f"allowed: {', '.join(VISUAL_PROVENANCE)}")
            continue
        if prov != VIEWED:
            continue
        if (seen_paths is not None and path not in seen_paths
                and not entry.get("preserved")):
            problems.append(
                f"{path} claims 'viewed-image:' but the see controller never "
                "selected it — a clip-matched or clip-propagated label may never "
                "be promoted to viewed-image (2026-07-20 fabrication guard)")
            continue
        sample = entry.get("sample")
        want = recorded.get(path)
        if report is not None and want and sample and want != sample:
            problems.append(
                f"{path} claims thumbnail {sample!r} but the see report recorded "
                f"{want!r} for it — the claim points at another file's look")
            continue
        found = sample_problems(sample, samples_dir)
        if found:
            problems += [f"{path} claims 'viewed-image:' but {p}" for p in found]
            continue
        claims.append((path, sample))
    return problems + duplicate_sample_problems(claims)


def samples_dir_of(see_report_path, report=None):
    """Where this batch's thumbnails live. The report records it, but the
    report is also the thing an attacker edits, so a recorded directory is
    only honoured when it IS the batch's own `samples/`."""
    beside = Path(see_report_path).parent / "samples"
    recorded = (report or {}).get("samples_dir")
    if recorded and Path(recorded).resolve() == beside.resolve():
        return beside
    return beside


def seen_problems(path, sample, report, samples_dir):
    """Checks 1-7 for one file against one loaded see-report."""
    selected = {e.get("path"): e for e in (report.get("selected") or [])}
    entry = selected.get(path)
    if entry is None:
        return [f"{path} claims 'viewed-image:' but the see controller never "
                "selected it — a clip-matched or clip-propagated label may never "
                "be promoted to viewed-image (2026-07-20 fabrication guard)"]
    recorded = entry.get("sample")
    if sample and recorded and recorded != sample:
        return [f"{path} claims thumbnail {sample!r} but the see report recorded "
                f"{recorded!r} for it — the claim points at another file's look"]
    return sample_problems(sample or recorded, samples_dir)


# ------------------------------------------------------- memorize evidence --

def evidence_problems(evidence, expect_path=None):
    """The MEMORIZE contract: may this vector become permanent recognition
    evidence? -> list of problems, empty when the promotion is proved.

    `evidence` is what the caller that saw the vision result hands over:

        {"see_report": "<…/classify/batch-NN/see-report.json>",
         "batch": 7, "path": "<the file that was looked at>",
         "sample": "<its thumbnail's filename>", "label": "<what came back>"}

    Everything is re-derived from disk here rather than trusted from the dict.
    A promotion whose see-report has since been deleted is not "probably fine",
    it is unproved — and an exemplar is forever."""
    if not isinstance(evidence, dict):
        return ["no view evidence supplied — only a vision-confirmed look may "
                "become an exemplar, and a look has to be shown, not asserted"]
    missing = [k for k in EVIDENCE_KEYS if not evidence.get(k) and evidence.get(k) != 0]
    if missing:
        return [f"view evidence is missing {', '.join(missing)}"]
    path = str(evidence["path"])
    if expect_path is not None and path != str(expect_path):
        return [f"view evidence is for {path}, not for {expect_path}"]
    report_path = Path(evidence["see_report"])
    if not report_path.is_file():
        return [f"see report {report_path} does not exist — the look cannot be "
                "verified, so it cannot be memorized"]
    try:
        report = json.loads(report_path.read_text())
    except (ValueError, OSError) as exc:
        return [f"see report {report_path} is unreadable: {exc}"]
    if int(report.get("batch", -1)) != int(evidence["batch"]):
        return [f"see report {report_path} is batch {report.get('batch')}, but the "
                f"evidence says batch {evidence['batch']}"]
    problems = seen_problems(path, evidence.get("sample"), report,
                             samples_dir_of(report_path, report))
    if problems:
        return problems
    # The applied labels are the record of what the model actually returned.
    # A file the controller SELECTED but that ended up carrying a clip-* label
    # was never looked at — the run stopped before the vision call.
    labels_path = report_path.parent / "see-labels.json"
    if labels_path.is_file():
        try:
            entries = json.loads(labels_path.read_text()).get("labels") or []
        except (ValueError, OSError) as exc:                # pragma: no cover
            return [f"{labels_path} is unreadable: {exc}"]
        applied = {e.get("path"): e for e in entries}
        entry = applied.get(path)
        if entry is None:
            return [f"{path} has no applied label in {labels_path} — the vision "
                    "model's answer for it was never recorded"]
        if not is_view_confirmed(entry.get("provenance")):
            return [f"{path} carries provenance {entry.get('provenance')!r} in "
                    f"{labels_path}; only a bare 'viewed-image:' label is a look"]
    return []
