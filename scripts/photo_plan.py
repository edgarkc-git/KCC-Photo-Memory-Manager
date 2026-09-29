#!/usr/bin/env python3
"""photo-plan Stage 4b — turn classified batches into an approvable copy plan.

Reads manifest.csv + batches.json + plan/dedupe_batch-NN.json + a plans.json
config (the agent's destination decisions). Writes into the work dir only:
  plan/plan_PN.md         human-readable plan in the owner's language —
                          the document the operator approves
  plan/plan_PN-files.csv  full file list sidecar (source, action, destination)
and advances the plan's batches to status "planned" in batches.json (.bak kept).

Baked-in routing rules:
  Monthly-bucket naming (D14, 2026-07-13): auto-generated monthly folders use
      YYYYMM00_[name] (trailing 00 as the day field) so they sort inside the
      same month group as daily YYYYMMDD_ folders.
  D7  screenshots / screen recordings (EXIF rule) -> the monthly screenshots
      bucket <dest_root>/YYYYMM00_[screenshots], never the trip folder.
  D8  trip-leg sub-folders MMDD-MMDD_[where] via the plan's "legs" list.
  G-2 (2026-08-05) a no-camera still at a size that some OTHER file's name
      proves is a screen, which the pack has not confirmed, goes to the
      monthly to-be-checked bucket instead of the trip folder, and the
      proposal is queued into the plan document and screen-size-proposals.json.
      Non-blocking on purpose: the run never stops to ask.
  D5  every generated folder lives under dest_root; the only exceptions are
      merges into existing hand-named folders, stated explicitly in the md.
  D13 (2026-07-06) extension-mislabeled files (extension != exiftool
      FileType) are copied under a CORRECTED filename; if the real format
      cannot be determined, the file routes to <dest_root>/YYYYMM00_others
      (file's own capture month) for human attention — the only auto-route
      into YYYYMM00_others.
  Safety gate 5 (amended by D13; to-be-checked mod, 2026-07-06 evening): files
      with no EXIF date are never in any batch — plan them with --no-date,
      which writes an executable plan routing everything to the monthly
      to-be-checked bucket <dest_root>/YYYYMM00_[to_be_checked] (YYYYMM = the
      raw dump folder's YYYYMM).
      YYYYMM00_AI-images is STRICTLY for confirmed AI-generated images: pass
      --ai-confirmed only after visually verifying the no_exif-rule files —
      the EXIF rule alone (no camera/no date/no GPS) cannot tell an AI image
      from an EXIF-stripped forwarded photo.
      YYYYMM_Misc is retired as an auto-route.
  Dedupe (OA-3) is mandatory when a plan declares "refs": the script refuses
      to plan if photo_dedupe.py results are missing.

Language: every sentence this script writes for a human comes from
photo_profile.messages(profile), and every bucket name from
photo_profile.buckets(profile). A run with no owner pack resolves to the
legacy zh-TW table, so it keeps producing byte-for-byte what it produced
before the catalog existed; a pack that declares a language gets that
language, and an unknown one gets English.

plans.json schema (agent-written, lives in the work dir):
  {"dest_root": "<dest root for this collection>",
   "plans": [{
     "plan": 3, "title": "...",
     "batches": [4,5],
     "dest": {"mode": "merge|new|fill_shell", "path": "<dest_root>/folder"},
     "legs":      [{"from": "2026-05-06", "to": "2026-05-09", "name": "0506-0509_[where]"}],
     "overrides": [{"dates": ["2026-04-27"], "dest": "<dest_root>/20260427_[where]",
                    "mode": "fill_shell", "reason": "..."}],
     "refs": ["<Working Files>/<dump>"],   # dedupe references, optional
     "notes": "..."}]}

Usage:
  python3 photo_plan.py "<Working Files>/<dump>" --plan 3
  python3 photo_plan.py "<Working Files>/<dump>" --no-date
"""

import argparse
import csv
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from photo_cluster import parse_date  # noqa: E402
import photo_magic  # noqa: E402
from photo_sample import (IMAGE_TYPES, SCREENSHOT_NAME,  # noqa: E402
                          VIDEO_TYPES, preclassify, screen_dims)
import photo_evidence  # noqa: E402
import photo_name  # noqa: E402
import photo_platform  # noqa: E402
import photo_profile  # noqa: E402

MODE_MESSAGE_KEY = {"merge": "plan_mode_merge", "new": "plan_mode_new",
                    "fill_shell": "plan_mode_fill_shell"}

# VS-4 provenance (Visual-Sorting DESIGN, per-batch flow): "the plan CSV
# records which prefix each WHO/WHAT came from — auditable end to end, so the
# operator can see at review time which names are still resting on unconfirmed
# memory."
#
# ⚠️ These four columns appear ONLY when the plan's batches have been through
# the see stage. A dump classified without it produces the same seven columns
# it has always produced, byte for byte — which is what keeps every golden
# replay a comparison against the shipped decision rather than against a
# reformatted version of it. `photo_execute.py` reads the CSV by field name,
# so a wider row costs it nothing.
VISUAL_FIELDS = ["who", "who_provenance", "what", "what_provenance"]


def batches_without_vision(workdir, batch_numbers):
    """-> the batch numbers in this plan with no see-stage output yet.

    R1. `visual_columns()` returns None when no batch in the plan has been
    seen, and that None is SILENT: the plan still renders, the CSV simply
    loses its WHO/WHAT columns, and the folder gets named from metadata
    alone. Measured in UAT01 (20260904): every plan was authored 16-30
    minutes BEFORE the see stage ran, so `[who]` could not reach a folder
    name even though the label file, the registry resolver and the columns
    were all built and working. The stage order made it impossible and
    nothing said so -- 11 of 11 folders, no warning, exit 0.

    Reported per batch rather than as a bool on purpose: a plan that groups a
    seen batch with an unseen one loses names for only part of its files, and
    a bool cannot say which part.
    """
    return [n for n in sorted(batch_numbers)
            if not (workdir / "classify" / f"batch-{n:02d}"
                    / "see-labels.json").exists()]


def visual_columns(workdir, batch_numbers, profile, pack):
    """-> {SourceFile: {who, who_provenance, what, what_provenance}}, or None
    when no batch in this plan has see-stage output.

    `pack` is the one this run already resolved, threaded down rather than
    re-resolved: the isolation invariant is "one run loads exactly one owner's
    pack", and a second `resolve_pack()` here would be a second chance to load
    a different one.

    WHO renders from the subject REGISTRY, never from the label file: the
    label file stores a `subject_id` (the stable key), and what a human reads
    is resolved here, at write time, so a subject renamed after this tree was
    sorted still prints its current name (N-6 / N-10a). An unconfirmed subject
    prints its class word and its provenance gains the `draft:` prefix — the
    operator can then see at a glance which names rest on unconfirmed memory
    (V2-5), which is the entire point of the column."""
    labels = {}
    for n in sorted(batch_numbers):
        path = workdir / "classify" / f"batch-{n:02d}" / "see-labels.json"
        if not path.exists():
            continue
        for entry in json.loads(path.read_text()).get("labels") or []:
            labels[entry["path"]] = entry
    if not labels:
        return None
    # D-F10 — which files a `clip-propagated:` label may be traced back to.
    #
    # ⛔ `clip-propagated:` NAMES TWO DIFFERENT POPULATIONS and they must not
    # be treated as one. Both carry that prefix and both carry a `from`:
    #
    #   applied      `photo_see.apply_decisions()` — a file inherits the
    #                PHRASE a model returned for another file in its visual
    #                cluster. Its `from` is a file that was really looked at.
    #   provisional  `photo_see.provisional_labels()` — a file inherits its
    #                cluster medoid's zero-shot SCENE CLASS. Its `from` is
    #                the medoid, which nobody opened, and the label text is a
    #                word out of the pack's class vocabulary.
    #
    # D-F10 opens `[what]` to the first (480 of 990 files on the real dump,
    # against 126 genuinely viewed — restricting the slot to viewed evidence
    # leaves 87% of files contributing nothing). Opening it to the SECOND
    # would put a `[type]` word in the `[what]` slot, which is the exact
    # defect D-F11 forbids and the one R6 was built to close. Measured: on a
    # cluster of ten propagated class words around one viewed phrase, a gate
    # written on the prefix alone ranks the class word first, because
    # propagation is what makes it a majority.
    #
    # The discriminator is whether the `from` file carries a bare
    # `viewed-image:` in this same labels file, so it is read off what the see
    # stage actually wrote rather than inferred from the label's text.
    seen_paths = {path for path, entry in labels.items()
                  if photo_evidence.is_view_confirmed(entry.get("provenance"))}

    import photo_memory
    import photo_subjects
    registry = photo_subjects.load(pack=pack)
    rmsg = photo_profile.review_messages(profile)
    # N-9's `{3}`, read from the PACK. ⛔ Never the constant: a household with
    # four animals raises this in `defaults` and nothing in the engine moves.
    cap = int(registry.defaults.get(
        "names_per_folder",
        photo_subjects.DEFAULT_THRESHOLDS["names_per_folder"]))

    out = {}
    for path, entry in labels.items():
        cell = {"what": entry.get("label") or "",
                "what_provenance": entry.get("provenance") or ""}
        # ⚠️ NOT a CSV column, deliberately. `VISUAL_FIELDS` still names four
        # columns and the row is built by picking those four by name, so the
        # plan CSV is byte-identical and `photo_evidence.PLAN_PROVENANCE`
        # keeps its eight legal strings — a ninth prefix meaning "propagated
        # from a look" would be a second vocabulary for a fact the existing
        # one already carries between them.
        source = entry.get("from")
        if source in seen_paths:
            cell[WHAT_VIEWED_SOURCE] = source
        prefix = entry.get("subject_provenance") or ""
        subjects = photo_evidence.subject_list(entry)
        picked = entry.get("subject_ids") or []
        if picked:
            # G6 R6 — names the owner picked for the FRAME (a frame with more
            # than one animal). They stand in for as many detections; any
            # detection beyond them is still an unnamed animal and says so.
            subjects = ([{"subject_id": sid, "subject_kind": None}
                         for sid in picked] + subjects[len(picked):])
        names, kinds, drafted = [], [], False
        seen = []
        # G7 — which names the AGENT applied after a view, and the record each
        # rests on. Carried beside the subject, never into the provenance (L1).
        views = {m.get("subject_id"): m.get("view")
                 for m in entry.get("identified") or []}
        for subject in subjects:
            name, is_draft = subject_name(subject, registry, profile, rmsg)
            kind = subject_kind(subject, registry)
            names.append(name)
            kinds.append(kind)
            drafted = drafted or is_draft
            seen.append({"name": name, "confirmed": not is_draft,
                         "provenance": (photo_evidence.DRAFT + prefix
                                        if is_draft and prefix else prefix),
                         "kind": kind,
                         "subject_id": subject_id(subject, registry)})
            if subject.get("subject_id") in views:
                seen[-1].update(by="agent-confirmed",
                                view=views[subject["subject_id"]])
        # ⚠️ Not a CSV column either, for the reason WHAT_VIEWED_SOURCE is
        # not. One entry PER SUBJECT, because the rendered `who` cannot answer
        # "what backs this name": past `{names_per_folder}` it is a collective
        # noun with no names left in it, and its one provenance marker is the
        # weakest of the cell's subjects, so a confirmed animal photographed
        # beside a draft reads as a draft there.
        cell[WHO_SUBJECTS] = seen
        if names:
            cell["who"] = render_who(names, kinds, cap, profile, rmsg)
            # ONE marker for the cell, not one per name. `draft:` qualifies
            # the provenance claim the cell makes, and the cell makes one —
            # a name resting on unconfirmed memory anywhere in it is what the
            # operator has to see (V2-5), so the weaker of the two wins.
            if drafted and prefix:
                prefix = photo_evidence.DRAFT + prefix
        else:
            # A provenance claim about WHO, on a cell holding no WHO,
            # qualifies nothing — the same reasoning that keeps a bare
            # `draft:` out of the column, one level up. Unreachable from
            # `photo_see`, which only sets `subject_provenance` where it set a
            # subject; reachable from a label file written by anything else,
            # and it renders as `viewed-image:` beside an empty cell, which
            # reads as evidence for a name that is not there.
            prefix = ""
        cell["who_provenance"] = prefix
        out[path] = cell
    return out


# R6 — why `[what]` may be picked at all, and why it may not.
#
# `ok`            a phrase resting on a look was chosen and it fits the budget
# `nothing-viewed` nothing in this folder rests on a look at all: no bare
#                 `viewed-image:` WHAT, and no `clip-propagated:` WHAT that
#                 inherited its phrase from a file somebody opened.
# `no-phrase`     files rest on a look and none of them carries a phrase
# `over-budget`   every eligible phrase, with `[who]` beside it, exceeds N-2's
#                 hard cap
#
# ⛔ TOKENS, not sentences. What the operator reads is rendered by the caller
# out of the message table (Rule 8); a sentence returned from here would be
# an English string the engine wrote for a human, in a module that must not
# hold one.
WHAT_OK = "ok"
WHAT_NOTHING_VIEWED = "nothing-viewed"
WHAT_NO_PHRASE = "no-phrase"
WHAT_OVER_BUDGET = "over-budget"

# The cell key `visual_columns()` writes when a `clip-propagated:` WHAT
# inherited its phrase from a file that really was looked at (D-F10). Present
# = the propagated phrase traces to a look; absent = it does not, and then the
# label is the zero-shot classifier's class word wearing a propagated prefix.
# ⛔ Not a CSV column — see `visual_columns()`.
WHAT_VIEWED_SOURCE = "what_viewed_source"

# The cell key `visual_columns()` writes with one entry per subject in the
# file: {name, confirmed, provenance, kind, subject_id}. `kind` is what
# `render_who()` needs for the collective noun when a FOLDER gathers subjects
# from several files (Wave 3 G3); `subject_id` is what the index stores, the
# name being resolved at every render (gap G3). ⛔ Not a CSV column.
WHO_SUBJECTS = "who_subjects"


def who_evidence(cells):
    """F14 — what the files actually show, per subject. -> dict.

    `cells` is one `visual_columns()` cell per file, `None` for a file the see
    stage never labelled. A file counts once per (name, provenance) however
    many boxes it holds, so the number is files, which is what the owner is
    asked to trust.

    ⛔ Read off the same cells the CSV is written from. A second resolution
    of the registry here could print a name the file list does not carry,
    and then the document the owner signs and the file it summarises would
    disagree about who is in the photographs.
    """
    counts, none, unseen = {}, 0, 0
    for cell in cells:
        if cell is None:
            unseen += 1
            continue
        pairs = {(s["name"], s["provenance"], s["confirmed"])
                 for s in cell.get(WHO_SUBJECTS) or []}
        if not pairs:
            none += 1
        for pair in pairs:
            counts[pair] = counts.get(pair, 0) + 1
    rows = sorted(counts.items(),
                  key=lambda kv: (not kv[0][2], -kv[1], kv[0][0], kv[0][1]))
    return {"subjects": [{"name": n, "provenance": p, "confirmed": c,
                          "files": k} for (n, p, c), k in rows],
            "no_subject": none, "unseen": unseen}


PAPERWORK_MOVED_NAME = "paperwork-moved.json"


def paperwork_scores(workdir):
    """W2C / ADR 0005 — the per-still paperwork scores photo_embed wrote.
    -> (scores or None, why). `why` is None when the scores are usable, else
    "missing" or "model"; the caller turns it into the owner's sentence.

    ⛔ READ, never computed: this stage is stdlib-only. And never a reason to
    stop — routing cannot fail closed (that would move every file), so with
    no usable scores every file routes as it always did and the plan says the
    check did not run.

    Scores from another model than the image index are refused, not used: a
    number is only comparable to the cut it was measured against.
    """
    import photo_embed
    embed = workdir / "embed"
    try:
        data = json.loads((embed / photo_embed.PAPERWORK_SCORES_NAME).read_text())
        scores = data["scores"]
    except (OSError, ValueError, KeyError, TypeError):
        return None, "missing"
    if not isinstance(scores, dict):
        return None, "missing"
    try:
        meta = json.loads((embed / "embeddings-meta.json").read_text())
    except (OSError, ValueError):
        meta = {}
    if any(data.get(k) != meta.get(k) for k in photo_embed.PAPERWORK_IDENTITY):
        return None, "model"
    return scores, None


def subject_names(pack):
    """-> {casefolded name: name} for every name a registry record holds NOW.

    W2B-1's only source of "is this word a subject's name". ⛔ The grammar
    cannot say: `[who]` is optional, so the slot after `[where]` is as often
    `[what]`, and a folder may carry no `[where]` at all. ⛔ And never a word
    list of ours — the pack's own records are the only authority on what its
    animals are called. Declared pets are subject records too (ADR 0004).

    Every status, drafts included: a draft's proposed name in a folder name is
    a name resting on a guess, which is exactly what is being refused, and
    only a confirmed subject can back one. `previous_names` are left out: a
    withdrawn name belongs to no animal the plan could render.
    """
    import photo_subjects
    registry = photo_subjects.load(pack=pack)
    return {s.name.casefold(): s.name for s in registry.subjects if s.name}


def names_in(folder, names):
    """-> the subject names `folder` carries, as written in it.

    A name is a WHOLE `+`-joined piece of a `_` slot, compared casefolded —
    the unit `render_who()` writes. ⛔ Not a word inside a phrase: `[what]` is
    open free text (D-F11), and a pet called Birk must not make
    `walk up birk hill` a claim about a cat.
    """
    found = []
    for slot in folder.split(photo_name.SLOT_SEP):
        for piece in slot.split(photo_name.NAME_SEP):
            piece = piece.strip()
            if piece.casefold() in names and piece not in found:
                found.append(piece)
    return found


def unbacked_names(plan, rows, visual, names):
    """W2B-1 / F12 — every subject name in a folder this plan writes that no
    file going INTO that folder backs. -> a list, empty when all are backed.

    Backed = at least one copied file in that folder, or under it, whose
    see-label names a CONFIRMED subject of that name at `viewed-image:`. That
    is SKILL's `[who]` rule, which until now bound only the path where the
    engine derives a name; the name the agent types into `plans.json` was
    checked for grammar alone, and UAT01-4 put two pets on twelve files that
    showed neither (`plan P12: 12 files = 12 copy`, exit 0).

    ⛔ Per SUBJECT, never per frame: two animals in one frame are two names,
    and each is backed or not on its own.
    ⛔ No location test. Pets travel; a pet seen away from home belongs in
    the folder for that place, so only the evidence is asked about.
    ⛔ No matching. Evidence is what the see stage wrote against a subject id;
    `accepted_match()` stays reported, never applied (A19).

    Folder, not plan: a leg is its own folder and is judged on its own files,
    as is an override's destination. A trip parent holds its legs, so files
    under it back its name.
    """
    parent = plan["dest"]["path"]
    folders = [(parent, True)]
    folders += [(f"{parent}/{leg['name']}", False)
                for leg in plan.get("legs") or []]
    for ov in plan.get("overrides") or []:
        dest = ov["dest"]
        folders.append((dest["path"] if isinstance(dest, dict) else dest, True))
    copies = [r for r in rows if r["_action"] == "copy"]
    out, done = [], set()
    for path, nested in folders:
        if path in done:
            continue
        done.add(path)
        words = names_in(Path(path).name, names)
        if not words:
            continue
        inside = [r for r in copies if r["_dest"] == path
                  or (nested and r["_dest"].startswith(path + "/"))]
        if not inside:
            # `photo_execute` creates only folders a copy lands in, so a
            # folder that receives nothing never reaches the tree — an
            # override that takes every day leaves its parent empty.
            continue
        cells = [visual.get(r["SourceFile"]) if visual else None
                 for r in inside]
        backed = {s["name"].casefold()
                  for cell in cells if cell
                  for s in cell.get(WHO_SUBJECTS) or []
                  if s["confirmed"]
                  and photo_evidence.is_view_confirmed(s["provenance"])}
        missing = [w for w in words if w.casefold() not in backed]
        if missing:
            out.append({"folder": Path(path).name, "names": missing,
                        "files": len(inside), "seen": visual is not None,
                        "evidence": who_evidence(cells)})
    return out


def unbacked_message(plan_number, unbacked, msg):
    """-> the refusal, every sentence from the owner's table (Rule 8)."""
    sep = msg["ref_separator"]
    lines = [msg["plan_refused_unbacked"].format(plan=plan_number)]
    for u in unbacked:
        names = sep.join(u["names"])
        lines.append(msg["plan_unbacked_name_line"].format(
            folder=u["folder"], names=names, n=u["files"]))
        ev = u["evidence"]
        if u["seen"]:
            items = [msg["plan_unbacked_evidence_item"].format(
                who=s["name"], n=s["files"], provenance=s["provenance"] or "-")
                for s in ev["subjects"]]
            if ev["no_subject"]:
                items.append(msg["plan_unbacked_no_animal"].format(
                    n=ev["no_subject"]))
            if ev["unseen"]:
                items.append(msg["plan_unbacked_unseen"].format(
                    n=ev["unseen"]))
            shown = sep.join(items)
        else:
            shown = msg["plan_unbacked_not_seen"]
        lines.append(msg["plan_unbacked_evidence"].format(evidence=shown))
    lines.append(msg["plan_unbacked_remedy"])
    return "\n".join(lines)


def rests_on_a_look(cell):
    """D-F10 — may this cell's `[what]` reach a FOLDER name? -> bool.

    | slot     | evidence                                                    |
    |----------|-------------------------------------------------------------|
    | `[who]`  | `viewed-image:` ONLY — naming an INDIVIDUAL on a guess is    |
    |          | how identities get corrupted, so that slot is untouched here |
    | `[what]` | `viewed-image:` **or** a `clip-propagated:` phrase that      |
    |          | inherited from a file somebody opened                        |

    The asymmetry is the decision, not an oversight: `[what]` is near-constant
    inside a Where-About (batch-13 on the real dump: `Cat` on 181 of 206
    files), so a phrase propagated across a visual cluster is still a claim
    about the SAME scene the model looked at. Who is IN the frame is not
    constant that way.

    ⛔ `clip-matched:` is still refused, and that refusal is what keeps
    `[what]` from collapsing into `[type]`: a clip-matched label is the
    zero-shot classifier's own output, drawn from the pack's closed class
    vocabulary. So is a propagated label with no viewed source — same
    vocabulary, one hop further from anybody's eyes.

    ⛔ `draft:viewed-image:` is refused too, by `is_view_confirmed()`: a real
    look attributed to an unconfirmed subject. The string is one prefix away
    from the one that means a bare look, which is why the test is that
    function and never an `in`.
    """
    provenance = cell.get("what_provenance")
    if photo_evidence.is_view_confirmed(provenance):
        return True
    return (provenance == photo_evidence.CLIP_PROPAGATED
            and bool(cell.get(WHAT_VIEWED_SOURCE)))


def name_phrase(cells, who="", hard=None, soft=None):
    """R6 — the `[what]` a FOLDER may be named with. -> a dict; `what` is None
    when nothing here may name one.

    `[what]` is KEYWORDS OR SHORT PHRASES — `hiking`, `sunset`, `coffee time`,
    `play in grass` (owner, 20260904). ⛔ It is NOT the 11-word `[type]`
    taxonomy; that is a different field, and `photo_classify_set.py --type`
    has no `choices=` precisely because this one was never meant to be closed.

    ⛔ THE GATE IS `rests_on_a_look()`, and it does two jobs at once. A phrase
    may name a folder from a bare `viewed-image:` source — a model opened that
    file and said this — or, since D-F10, from a `clip-propagated:` label that
    inherited its phrase from such a file. A `clip-matched:` phrase is the
    zero-shot scene classifier's own output, drawn from the pack's class
    vocabulary, and so is a propagated label with no viewed source; both stay
    refused. That is what keeps `[what]` from collapsing back into the
    taxonomy it is not, and the reason the gate reads the label's SOURCE and
    not just its prefix.

    ⛔ The pack's `[what]` list (`photo_profile.what_reference()`) is NOT
    consulted here and must not be. It is a reference for whoever writes the
    name — a phrase absent from it is perfectly legal (D-F11), and this
    function ranks what the model said, never what the owner has said before.

    Candidates rank by how many files carry them, then by text so the answer
    is deterministic, and the FIRST that fits N-2 wins. Walking on rather than
    refusing outright matters: a folder losing `[what]` entirely because its
    best-supported phrase ran three units long, while a shorter phrase with
    almost as many files sat right behind it, is a worse answer than the
    shorter phrase.

    `who` is the rendered `[who]` slot, counted alongside — N-2 bounds the two
    together and excludes `[period]` and `[where]`."""
    import photo_name
    if hard is None or soft is None:
        dh, ds = photo_name.DEFAULT_NAME_BUDGET_HARD, photo_name.DEFAULT_NAME_BUDGET_SOFT
        hard = dh if hard is None else hard
        soft = ds if soft is None else soft

    viewed = [c for c in cells.values() if rests_on_a_look(c)]
    base = {"what": None, "provenance": None, "units": photo_name.budget_units(who),
            "hard": hard, "soft": soft, "over_soft": False, "candidates": []}
    if not viewed:
        return {**base, "why": WHAT_NOTHING_VIEWED}

    counts = {}
    for cell in viewed:
        phrase = (cell.get("what") or "").strip()
        if phrase:
            counts[phrase] = counts.get(phrase, 0) + 1
    if not counts:
        return {**base, "why": WHAT_NO_PHRASE}

    who_units = photo_name.budget_units(who)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    candidates = [{"what": phrase, "files": n,
                   "units": who_units + photo_name.budget_units(phrase)}
                  for phrase, n in ranked]
    # Which prefix the WINNING phrase earned. ⛔ Not a constant `viewed-image:`
    # any more: since D-F10 a phrase can be picked on propagated evidence
    # alone, and reporting it as viewed would claim a look that never
    # happened — the same class of overstatement `assert_no_fabrication()`
    # exists to stop one stage upstream. The stronger claim wins when both
    # back the same phrase, because one real look is what N-4 asks for.
    backing = {}
    for cell in viewed:
        phrase = (cell.get("what") or "").strip()
        if not phrase:
            continue
        if photo_evidence.is_view_confirmed(cell.get("what_provenance")):
            backing[phrase] = photo_evidence.VIEWED
        else:
            backing.setdefault(phrase, photo_evidence.CLIP_PROPAGATED)

    for candidate in candidates:
        if candidate["units"] <= hard:
            return {"what": candidate["what"],
                    "provenance": backing[candidate["what"]],
                    "units": candidate["units"], "hard": hard, "soft": soft,
                    "over_soft": candidate["units"] > soft,
                    "candidates": candidates, "why": WHAT_OK}
    return {**base, "candidates": candidates, "why": WHAT_OVER_BUDGET}


WHO_JOINER = "+"


def render_who(names, kinds, cap, profile, rmsg):
    """N-9 — `[who]` is a REPEATABLE slot. -> the cell's whole WHO.

    ⛔ `[who]` IS NEVER CAPPED AT ONE (SPEC v0.7 as amended by the owner,
    20260904: three names in one folder name is normal). Until R5 this cell
    held one string, so the second animal in a frame reached the CSV and
    stopped there.

    Names join with `+` — `Birk+Moggie` — the same joiner multi-`[where]`
    already uses (`Kyoto+Osaka`), and the SPEC says why: the cap has to be
    checkable by READING a name. A different joiner per slot would make it
    unreadable.

    ⭐ Beyond `{names_per_folder}` the SPEC says use a COLLECTIVE NOUN, and
    this renders one rather than truncating. Truncation is the tempting
    shortcut and it is a lie the reader cannot detect: `A+B+C` on a folder of
    five animals is a complete, well-formed, false statement about what is in
    it, while the collective is true and visibly not a list of names. The
    noun itself is a pack format string (`review_who_many`) over the class
    word — the engine holds no vocabulary of its own (Rule 7/8).

    ⚠️ ANIMALS ONLY. The detector maps COCO `cat`/`dog`/`bird`/`horse` and
    never `person`; human subjects are NF-3 and out of Release A and B by the
    owner's decision of 20260904. Nothing here refuses a person — nothing can
    produce one."""
    if len(names) <= cap:
        return WHO_JOINER.join(names)
    import photo_memory
    # One kind or several: a folder of cats gets the cat word, a folder of a
    # cat and a dog has no shared species and falls to the unknown-kind word.
    # ⛔ Not "the first subject's kind" — that would print `cats` over a
    # mixed group, which is the same class of false-but-readable statement
    # truncation makes.
    distinct = {k for k in kinds if k}
    kind = distinct.pop() if (len(distinct) == 1 and all(kinds)) else None
    return rmsg["review_who_many"].format(
        kind=photo_memory.kind_word(kind, profile, rmsg))


def subject_kind(subject, registry):
    """-> the species this subject is recorded under, or the label's own guess.

    Read through the REGISTRY first, exactly as the name is: a see-label
    written before the owner corrected a subject's kind still carries the old
    one, and the collective noun must say what the pack believes now."""
    if subject.get("subject_id"):
        known = registry.get(subject["subject_id"])
        if known is not None and known.kind:
            return known.kind
    return subject.get("subject_kind")


def subject_id(subject, registry):
    """-> the id of the record this subject resolves to NOW, or the label's
    own id when the registry has none. A folded loser's id resolves to the
    winner, as its name does in `subject_name()`."""
    sid = subject.get("subject_id")
    if sid:
        known = registry.get(sid)
        if known is not None:
            return known.subject_id
    return sid


def subject_name(subject, registry, profile, rmsg):
    """-> (what this ONE subject prints, whether it rests on unconfirmed
    memory).

    Split out of `visual_columns()` by R4 because a see-label now names a
    list. The two branches are unchanged: a confirmed id prints the name the
    registry holds NOW, everything else prints its class word.

    RESOLVED (SNS-14), and this is the site the fold's alias following was
    built for. A see-label written before a fold still names the loser; what
    belongs in the plan is the name the subject holds NOW, so an old id
    resolves to the winner with no change of this function's own. `is_draft`
    still gates the `draft:` marker, and a tombstone resolves to a confirmed
    record, so the marker stays off exactly when it should."""
    import photo_memory
    if subject.get("subject_id"):
        known = registry.get(subject["subject_id"])
        if known is not None and known.name and not known.is_draft:
            return known.name, False
        kind = (known.kind if known is not None
                else subject.get("subject_kind"))
        return photo_memory.kind_word(kind, profile, rmsg), True
    return photo_memory.kind_word(subject["subject_kind"], profile, rmsg), True


SCREEN_PROPOSALS_NAME = "screen-size-proposals.json"


def screen_size_candidates(workdir, profile):
    """G-2, the checkpoint's missing trigger (b): a screen size spotted in the
    middle of a run rather than at prescan.

    The onboarding checkpoint only ever fired after `prep`. A collection whose
    first screenshot turns up in unit 7 therefore got no checkpoint at all, and
    those files were filed into whatever trip the date belonged to.

    The trigger is EVIDENCE, not suspicion. A no-camera still whose FILENAME
    says screenshot is decided by ONB-12 already; what is new is that its size
    is then a proven screen size, and the pack has not confirmed it. Other
    no-camera stills at that same size are `possible screenshot pictures` —
    which is what the checkpoint was asked to react to.

    Two things this deliberately does NOT do:
      * it never derives a size from a VIDEO. 1080x1920 is both a phone screen
        and the commonest video resolution there is; one named screen
        recording would otherwise sweep every ordinary video in the dump.
      * it drops a size a CAMERA in this dump also produces — a no-camera file
        at a size the owner's own camera emits is far more likely a stripped
        photo than a screenshot.

    Read from manifest.csv (plus the no-date sweep), never from the plan's own
    batches: the pipeline is resumable and re-runnable, so a candidate set that
    depended on which plan ran first would route the same file two ways.
    -> {(w, h): {"dims", "files", "witness"}}, keyed portrait-normalised."""
    # Card 9 (D1) — once per FILE: no-date-files.csv is a subset of
    # manifest.csv, so reading both counted every no-date file twice.
    rows, seen = [], set()
    for name in ("manifest.csv", "no-date-files.csv"):
        path = workdir / name
        if path.exists():
            with open(path, newline="") as f:
                for r in csv.DictReader(f):
                    key = r.get("SourceFile") or id(r)
                    if key not in seen:
                        seen.add(key)
                        rows.append(r)

    confirmed = screen_dims(profile)
    # FIX6 (U6-37) — a size the owner answered `no` to is neither proposed
    # again nor used to send files to the to-be-checked bucket.
    declined = photo_profile.declined_screen_sizes(profile)
    proven, camera_dims, at_size = {}, set(), {}
    for r in rows:
        dims = (r.get("ImageWidth", "-"), r.get("ImageHeight", "-"))
        if "-" in dims or "" in dims:
            continue
        if r.get("FileType") not in IMAGE_TYPES:
            continue
        make, model = r.get("Make", "-"), r.get("Model", "-")
        if make not in ("-", "") or model not in ("-", ""):
            camera_dims.add(dims)
            continue
        at_size[dims] = at_size.get(dims, 0) + 1
        if dims not in confirmed and SCREENSHOT_NAME.match(r.get("FileName", "")):
            proven.setdefault(dims, r.get("FileName", ""))

    out = {}
    for dims, witness in sorted(proven.items()):
        flipped = (dims[1], dims[0])
        if dims in camera_dims or flipped in camera_dims:
            continue
        key = dims if int(dims[0]) <= int(dims[1]) else flipped
        if tuple(sorted(int(v) for v in key)) in declined:
            continue
        # counted per SIZE, not per witness — the same screen can be proven by
        # a portrait and a landscape capture, and that is one candidate
        out[key] = {"dims": list(key), "witness": witness,
                    "files": at_size.get(key, 0) + at_size.get(
                        (key[1], key[0]), 0)}
    return out


def screen_candidate_dims(candidates):
    """-> {(w, h)} in both orientations, the shape route() matches against."""
    out = set()
    for w, h in candidates:
        out |= {(w, h), (h, w)}
    return out


def join_note(note, extra, msg):
    """Append one whole sentence to a note, in the owner's list punctuation."""
    if not extra:
        return note
    return (note + msg["note_separator"] if note else "") + extra


def resolve_dest_root(workdir, config=None, profile=None):
    """plans.json -> collection.json (photo-init, per collection) -> the
    user's profile (legacy_dest_root) -> hard failure. No engine-hardcoded
    path — a fresh user with no profile must be told, not silently pointed
    at someone else's drive."""
    cj = Path(workdir).parent / "collection.json"
    coll = json.loads(cj.read_text()) if cj.exists() else {}
    dest = (config or {}).get("dest_root") or coll.get("dest_root")
    if dest:
        return dest
    if profile is None:
        profile = photo_profile.load_profile(workdir=workdir)
    dest = photo_profile.get(profile, "legacy_dest_root")
    if dest:
        return dest
    sys.exit("no dest_root in plans.json/collection.json and no "
              "legacy_dest_root in profile — set one (photo-init records "
              "collection.json's dest_root normally)")

# D13: canonical extension (and accepted spellings) per exiftool FileType.
# A file whose extension is not in the accepted set is copied under the
# canonical name; a FileType missing from this map = format undeterminable.
EXT_BY_FILETYPE = {
    "JPEG": ("JPG", {"JPG", "JPEG"}),
    "HEIC": ("HEIC", {"HEIC"}),
    "HEIF": ("HEIF", {"HEIF"}),
    "PNG": ("PNG", {"PNG"}),
    "TIFF": ("TIF", {"TIF", "TIFF"}),
    "WEBP": ("WEBP", {"WEBP"}),
    "GIF": ("GIF", {"GIF"}),
    "BMP": ("BMP", {"BMP"}),
    "DNG": ("DNG", {"DNG"}),
    "MOV": ("MOV", {"MOV"}),
    "MP4": ("MP4", {"MP4"}),
    "M4V": ("M4V", {"M4V"}),
    "AVI": ("AVI", {"AVI"}),
    "3GP": ("3GP", {"3GP"}),
}


# L17 — exiftool calls some HEIC-named QuickTime movies HEIC, so for these
# FileTypes the file's own bytes decide. Only these: they are the class L17
# measured, and it keeps the plan from opening every file on the drive.
MAGIC_CHECKED_FILETYPES = {"HEIC", "HEIF"}


def real_filetype(row):
    """-> the FileType to name the copy by: the file's content when it is a
    video exiftool typed as HEIC (L17), else the manifest's FileType."""
    filetype = row.get("FileType", "-")
    if filetype in MAGIC_CHECKED_FILETYPES and row.get("SourceFile"):
        real = photo_magic.sniff(row["SourceFile"])
        if real in ("MOV", "MP4"):
            return real
    return filetype


def dest_name(row, msg):
    """D13 rename-at-copy. -> (destination filename, note, format_known)"""
    name = row["FileName"]
    filetype = real_filetype(row)
    canon = EXT_BY_FILETYPE.get(filetype)
    if canon is None:
        return name, "", False
    if Path(name).suffix.lstrip(".").upper() in canon[1]:
        return name, "", True
    new = str(Path(name).with_suffix("." + canon[0]))
    return new, msg["note_extension_corrected"].format(
        old=name, new=new, filetype=filetype), True


def dump_yyyymm(workdir):
    """YYYYMM of the raw dump, from batches.json source basename. Archive
    units without a YYYYMM name (e.g. "iPhone") fall back to the batches'
    year span ("2009" or "2006-2010") so the bucket never inherits a
    meaningless prefix like "iPhone00"."""
    data = json.loads((workdir / "batches.json").read_text())
    digits = "".join(c for c in Path(data["source"]).name if c.isdigit())
    # a real YYYYMM needs a valid month; "2020-2022" -> digits "20202022"
    # whose [:6] is "202020" (month 20) — a year-range, not a dump month.
    if len(digits) >= 6 and 1 <= int(digits[4:6]) <= 12:
        return digits[:6]
    b = data["batches"]
    y1, y2 = b[0]["from"][:4], b[-1]["to"][:4]
    return y1 if y1 == y2 else f"{y1}-{y2}"


def suffix_in_plan_collisions(rows, msg):
    """Two sources may map to the same corrected name at one destination —
    give later ones a _dup2/_dup3... suffix (never rely on execute flags)."""
    taken = set()
    for r in sorted(rows, key=lambda r: r.get("_name", "")):
        if r["_action"] != "copy":
            continue
        key = (r["_dest"], r["_name"].lower())
        if key in taken:
            stem, ext = Path(r["_name"]).stem, Path(r["_name"]).suffix
            n = 2
            while (r["_dest"], f"{stem}_dup{n}{ext}".lower()) in taken:
                n += 1
            r["_name"] = f"{stem}_dup{n}{ext}"
            r["_note"] = join_note(r["_note"], msg["note_duplicate_name_in_plan"], msg)
            key = (r["_dest"], r["_name"].lower())
        taken.add(key)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.2f} TB"


def load_dedupe(workdir, batch_nums):
    """source path -> existing duplicate path, across the plan's batches."""
    dupes = {}
    missing = []
    for n in batch_nums:
        p = workdir / "plan" / f"dedupe_batch-{n:02d}.json"
        if not p.exists():
            missing.append(n)
            continue
        data = json.loads(p.read_text())
        for d in data["dupe_list"]:
            dupes[d["source"]] = d["existing"]
    return dupes, missing


def collect_rows(workdir, batches):
    rows = []
    with open(workdir / "manifest.csv", newline="") as f:
        for row in csv.DictReader(f):
            dt = parse_date(row)
            if not dt:
                continue
            day = dt.date().isoformat()
            for b in batches:
                if b["from"] <= day <= b["to"]:
                    row["_dt"], row["_day"], row["_batch"] = dt, day, b["batch"]
                    rows.append(row)
                    break
    return rows


def route(row, plan, dest_root, dupes, msg, format_known=True, profile=None,
          screen_candidates=frozenset(), paperwork=None):
    """-> (action, destination, note, tags)

    `tags` is a set of machine-readable markers for the branch that fired
    ("screenshot", "shared", "unknown_format"). The plan report counts rows by
    tag rather than by searching the note text: a note is a translated
    sentence, so substring-matching it would silently count zero in every
    language but the one the sentence happens to be written in.

    `profile` is the owner pack. Without it preclassify falls back to the
    generic Apple-only camera list, and every photo from any other phone is
    labelled `shared` — which is how 71% of a Note10+ collection came to be
    described as "not shot on this device" (docs/photo-memory-pack.md)."""
    src = row["SourceFile"]
    cls = preclassify(row, profile)
    if src in dupes:
        # skip wins even for screenshots — never create a second copy on the
        # drive (SPEC Q7); the owner can relocate the existing one manually
        note = msg["note_already_in_existing_folder"]
        if cls in ("screenshot", "screen_record"):
            note = join_note(note, msg["note_screenshot_duplicate_in_trip_folder"], msg)
        return "skip_dupe", dupes[src], note, set()
    month = row["_day"][:7].replace("-", "")
    bk = photo_profile.buckets(profile)
    # T0 (A34a). A sidecar is not media, so it is never copied — the tier
    # would be cosmetic otherwise, because an unrecognised class falls through
    # to the plain copy at the end of this function. Scan has excluded these
    # since bd1a3b2 (2026-07-30), so only a manifest written before that date
    # can produce one; those manifests are still on disk and still replayed.
    if cls == "junk":
        return "skip_junk", "", msg["note_junk_sidecar"], {"junk"}
    if not format_known:
        # D13: real format undeterminable -> human-attention placeholder
        return ("copy", f"{dest_root}/{month}00_{bk['others']}",
                msg["note_format_undeterminable"], {"unknown_format"})
    # W2C / ADR 0005 — financial or official paperwork, the narrow class.
    # A FILE classifier, so it sits with the screenshot and G-2 tests and
    # BEFORE the overrides below (the A5 lesson: an override names a day and
    # cannot answer a question about a file). Before the screenshots branch
    # too, by the Lead's ruling of 20260911: a Screenshots bucket is sorted
    # output, not a review inbox, and the one real tax notice measured was a
    # screenshot.
    # ⛔ STILLS ONLY. A video is never scored by photo_embed, and is checked
    # for here as well, so no score file can ever move one.
    if (paperwork and row.get("FileType") in IMAGE_TYPES
            and src in paperwork
            and paperwork[src] > photo_profile.paperwork_margin(profile)):
        return ("copy", f"{dest_root}/{month}00_{bk['to_be_checked']}",
                msg["note_paperwork"], {"paperwork"})
    if cls in ("screenshot", "screen_record"):
        return ("copy", f"{dest_root}/{month}00_{bk['screenshots']}",
                msg["note_screenshot_exif_rule"], {"screenshot"})
    # G-2: a size another file's NAME proved is a screen, that the pack has
    # not confirmed. Non-blocking by construction — the file goes to the
    # human-triage bucket, not to the screenshots bucket and not into the
    # trip, and the run carries on. Routing an unconfirmed size straight into
    # the screenshots bucket is the mistake the census refuses to make.
    dims = (row.get("ImageWidth", "-"), row.get("ImageHeight", "-"))
    if (dims in screen_candidates and row.get("FileType") in IMAGE_TYPES
            and row.get("Make", "-") in ("-", "")
            and row.get("Model", "-") in ("-", "")):
        bucket = f"{month}00_{bk['to_be_checked']}"
        return ("copy", f"{dest_root}/{bucket}",
                msg["note_screen_size_candidate"].format(
                    w=dims[0], h=dims[1], bucket=bk["to_be_checked"]),
                {"screen_candidate"})
    # An override names a DAY; the three classifiers above answer questions
    # about a FILE that a date cannot. Evaluated first — as it was until
    # LL-PHO-96 — an override silently swallowed all three, and a screenshot
    # taken on an overridden day landed in the trip folder with no tag, no
    # note and nothing in the report to show it. It still wins over the leg
    # and `shared` branches below: those only choose WHICH trip folder.
    for ov in plan.get("overrides", []):
        if row["_day"] in ov["dates"]:
            ov_dest = ov["dest"]
            ov_path = ov_dest["path"] if isinstance(ov_dest, dict) else ov_dest
            return "copy", ov_path, ov.get("reason", ""), set()
    dest = plan["dest"]["path"]
    for leg in plan.get("legs", []):
        if leg["from"] <= row["_day"] <= leg["to"]:
            dest = f"{plan['dest']['path']}/{leg['name']}"
            break
    if cls == "shared":
        return "copy", dest, msg["note_shared"], {"shared"}
    return "copy", dest, "", set()


def settle_rows(workdir, plan, batches, dest_root, profile, msg):
    """-> (rows, screen candidates, paperwork scores, why) — every file of
    `plan`'s batches with its action, destination, note and tags settled by
    `route()`. The plan CSV is written from these rows.

    ⛔ PURE: it writes no file and moves no status. `main()` owns the plan
    documents and the batches.json advance; `photo_index render` calls this
    with a placeholder destination to learn where each file lands, and must
    leave the work dir exactly as it found it (Wave 3 G3).

    The dedupe inputs travel with it: a plan that declares `refs` with no
    dedupe results stops here, whoever the caller is (OA-3 mandatory).
    """
    dupes, missing = ({}, [])
    if plan.get("refs"):
        dupes, missing = load_dedupe(workdir, plan["batches"])
        if missing:
            sys.exit(f"plan declares dedupe refs but results missing for batches "
                     f"{missing} — run photo_dedupe.py first (OA-3 mandatory)")

    rows = collect_rows(workdir, batches)
    # G-2: computed over the WHOLE dump before any row is routed, so plan 1
    # decides the same way whether it runs before or after plan 7
    candidates = screen_size_candidates(workdir, profile)
    candidate_dims = screen_candidate_dims(candidates)
    paperwork, paperwork_why = paperwork_scores(workdir)
    for r in rows:
        r["_name"], ext_note, known = dest_name(r, msg)
        r["_action"], r["_dest"], r["_note"], r["_tags"] = route(
            r, plan, dest_root, dupes, msg, format_known=known, profile=profile,
            screen_candidates=candidate_dims, paperwork=paperwork)
        if ext_note and r["_action"] == "copy":
            r["_note"] = join_note(r["_note"], ext_note, msg)
            r["_tags"] = r["_tags"] | {"renamed"}
    suffix_in_plan_collisions(rows, msg)
    return rows, candidates, paperwork, paperwork_why


# M14 — a destination-folder component the engine builds from an import's own
# name. ⛔ There was no sanitiser for this before: no-date bucket names were
# never built from anything but a date. These are the characters a destination
# filesystem refuses (exFAT refuses all of them; `/` breaks any path).
FS_REFUSED = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
RE_FS_YEAR = re.compile(r"(?:19|20)\d{2}")


def fs_year(row):
    """-> the four-digit year of a row's FileModifyDate, or None.

    ⛔ FileModifyDate ONLY. FileCreateDate is the copy-to-drive stamp — 0 of
    418 right, measured independently twice — so it is never consulted here,
    not even as a fallback when FileModifyDate is missing. A video with no
    usable modify date claims NO year rather than a wrong one."""
    value = str(row.get("FileModifyDate") or "")[:4]
    return value if RE_FS_YEAR.fullmatch(value) else None


def import_folder(workdir):
    """-> the per-import subfolder under the undated stills bucket (Q10).

    Named after the IMPORT's own identity — the work dir — and ⛔ never after a
    date derived from it: a subfolder called `202501` would re-claim the
    arrival month, which is exactly the flaw a no-EXIF still's timestamp has.
    ⛔ REFUSED, never silently rewritten, when the name carries a character the
    destination refuses: a sanitiser that turned `a:b` into `a_b` could make
    two different imports share one subfolder. Measured on 20 real source
    names: none carries such a character."""
    name = Path(workdir).name
    if not name or name in (".", "..") or FS_REFUSED.search(name):
        sys.exit(f"cannot use the import name {name!r} as a folder: it is "
                 "empty or carries a character a destination drive refuses "
                 "(\\ / : * ? \" < > | or a control character). Rename the "
                 "work dir and run this stage again.")
    return name


def undated_rel(word, workdir):
    """-> the undated stills bucket, RELATIVE to dest_root: `_<word>/<import>`.

    ⛔ ONE definition, and it is the only two-level bucket there is. photo_plan
    BUILDS the destination from it, and photo_index's `check` ADMITS the one
    `/` it contains by comparing a folder's name against THIS — so what is
    built and what is let through can never be two copies of a rule (the trap
    this card hit four times: portrait_key, kind_of, unfinished, routes).
    `<import>` has already been refused by `import_folder()` if a drive could
    not hold it, which is why admitting its `/` admits no unchecked name."""
    return f"_{word}/{import_folder(workdir)}"


def no_date_dest(row, dest_root, names, workdir, by_file_date):
    """-> the folder ONE no-date row lands in, on the default (non-AI) route.

    ⛔ ONE definition, called by `settle_no_date_rows()` here AND by
    photo_index's `init` (M14 (ii), Lead 20260922). init used to guess this
    itself — every no-date file into one bucket keyed by the dump's month —
    and render then moved each file into its real bucket and logged a
    "disagreement" for every one of them: 257 lines on the largest real
    import, each reading `to_be_checked → to_be_checked`. init now asks the
    same question render asks, so the two agree by construction.

    `by_file_date` is `routes_by_file_date()` of the caller's rows. Without the
    column this is exactly the old path — one bucket per dump — which is what
    keeps the goldens byte-identical."""
    word = names["to_be_checked"]
    if by_file_date:
        year = fs_year(row)
        if row.get("FileType") in VIDEO_TYPES and year:
            return f"{dest_root}/{year}00_{word}"
        # a still, or a video with no usable modify date: NO year
        return f"{dest_root}/{undated_rel(word, workdir)}"
    ym = dump_yyyymm(workdir)
    # D14 "00" day-fill only applies to real YYYYMM buckets; a year-span
    # fallback ("2006-2010") stays as-is
    return f"{dest_root}/{ym + '00' if ym.isdigit() else ym}_{word}"


def routes_by_file_date(rows):
    """-> True when M14 routes these no-date rows by each file's own date.

    ⛔ ONE predicate, read by the routing AND by the plan document, so the
    sentence the owner reads can never describe a different path than the
    one the files took. True only when the manifest carries the column —
    every golden predates it, which is what keeps them byte-identical."""
    return bool(rows) and "FileModifyDate" in rows[0]


def settle_no_date_rows(workdir, dest_root, profile, msg, ai_confirmed=False):
    """-> (rows, counts per class, bucket root) — every no-date file with its
    action, destination and note, as `write_no_date_plan()` writes them.
    ⛔ PURE, like `settle_rows()`: `photo_index render` reads the routes from
    here and the plan documents stay `write_no_date_plan()`'s."""
    path = workdir / "no-date-files.csv"
    if not path.exists():
        sys.exit(f"no {path}")
    rows = list(csv.DictReader(open(path, newline="")))
    ym = dump_yyyymm(workdir)
    # D14 "00" day-fill only applies to real YYYYMM buckets; year-span
    # fallbacks ("2006-2010") stay as-is
    bk = f"{ym}00" if ym.isdigit() else ym
    names = photo_profile.buckets(profile)
    bucket_root = f"{dest_root}/{bk}"
    # ⛔ M14 routes ONLY when the manifest carries the column. Every golden
    # predates it, and a per-file year cannot be computed from a manifest with
    # no per-file date — so without the column this is exactly the old path,
    # which is what keeps all seven goldens byte-identical without a waiver.
    by_file_date = routes_by_file_date(rows)
    counts = {}
    for r in rows:
        cls = preclassify(r, profile)
        counts[cls] = counts.get(cls, 0) + 1
        r["_class"] = cls
        r["_name"], note, _known = dest_name(r, msg)
        r["_action"] = "copy"
        if cls == "no_exif" and ai_confirmed:
            r["_dest"] = f"{bucket_root}_{names['ai_images']}"
            note = join_note(note, msg["note_ai_confirmed"].format(
                bucket=names["ai_images"]), msg)
        elif by_file_date:
            r["_dest"] = no_date_dest(r, dest_root, names, workdir, True)
            # ⛔ Checked, not trusted (M14). The no-date plan was never
            # name-checked before, so whatever a route produced reached the
            # drive. Every bucket this path writes is one of exactly three
            # forms — the subfolder under the undated bucket was already
            # checked by import_folder(), which refuses rather than rewrites.
            top = Path(r["_dest"]).relative_to(dest_root).parts[0]
            if photo_name.bucket_form(top, names["to_be_checked"]) is None:
                sys.exit(f"refusing to write the no-date bucket {top!r}: it is "
                         "not one of the three forms a new bucket may take "
                         "(YYYYMM00_<bucket>, YYYY00_<bucket>, _<bucket>).")
            note = join_note(note, msg["note_unclassifiable"].format(
                bucket=names["to_be_checked"]), msg)
        else:
            r["_dest"] = no_date_dest(r, dest_root, names, workdir, False)
            note = join_note(note, msg["note_unclassifiable"].format(
                bucket=names["to_be_checked"]), msg)
        r["_note"] = note
    suffix_in_plan_collisions(rows, msg)
    return rows, counts, bucket_root


def write_no_date_plan(workdir, out_dir, ai_confirmed=False, profile=None):
    """D13 routing (to-be-checked mod, 2026-07-06 evening): no-date files are
    auto-planned to the monthly to-be-checked bucket (raw dump folder's
    YYYYMM) for later human triage. Only with --ai-confirmed (agent visually
    verified the no_exif-rule files are truly AI-generated) do those route to
    YYYYMM00_AI-images instead. Extension-mislabeled files get the corrected
    filename. Executed via photo_execute --no-date."""
    msg = photo_profile.messages(profile)
    path = workdir / "no-date-files.csv"
    if not path.exists():
        sys.exit(f"no {path}")
    pp = workdir / "plans.json"
    dest_root = resolve_dest_root(
        workdir, json.loads(pp.read_text()) if pp.exists() else {}, profile)
    rows, counts, bucket_root = settle_no_date_rows(
        workdir, dest_root, profile, msg, ai_confirmed=ai_confirmed)
    names = photo_profile.buckets(profile)
    dest_counts = {}
    for r in rows:
        dest_counts[r["_dest"]] = dest_counts.get(r["_dest"], 0) + 1
    csv_path = out_dir / "plan_no-date-files.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SourceFile", "FileName", "FileType", "FileSize",
                    "preclass", "action", "destination", "note"])
        for r in rows:
            w.writerow([r["SourceFile"], r["_name"], r["FileType"],
                        r["FileSize"], r["_class"], r["_action"],
                        r["_dest"], r["_note"]])
    md = [
        msg["nodate_title"], "",
        msg["md_generated_at"].format(when=datetime.now().strftime('%Y-%m-%d %H:%M')),
        msg["md_source"].format(
            source=json.loads((workdir / 'batches.json').read_text())['source']), "",
        msg["nodate_intro"].format(n=len(rows)),
        (msg["nodate_route_ai"].format(dest=f"{bucket_root}_{names['ai_images']}")
         if ai_confirmed else
         msg["nodate_route_split"].format(
             bucket=names['to_be_checked'],
             stills=f"{dest_root}/{undated_rel(names['to_be_checked'], workdir)}",
             ai_bucket=names['ai_images'])
         if routes_by_file_date(rows) else
         msg["nodate_route_all"].format(
             dest=f"{bucket_root}_{names['to_be_checked']}",
             ai_bucket=names['ai_images'])),
        msg["nodate_rename_line"], "",
        msg["nodate_rule_header"], "|---|---|",
    ]
    for k, v in sorted(counts.items()):
        md.append(f"| {k} | {v} |")
    md += ["", msg["md_dest_count_header"], "|---|---|"]
    for d, n in sorted(dest_counts.items()):
        md.append(f"| `{d}` | {n} |")
    md += ["", msg["nodate_full_list"].format(path=csv_path.name),
           msg["nodate_run_line"], ""]
    (out_dir / "plan_no-date.md").write_text("\n".join(md))
    print(f"no-date plan: {len(rows)} files -> "
          + ", ".join(f"{Path(d).name}:{n}" for d, n in sorted(dest_counts.items()))
          + f" -> {out_dir / 'plan_no-date.md'}")


def check_plan_names(plan, batches, hard=None, soft=None, rows=None):
    """R12 — does this plan's own naming obey the grammar? -> (refusals, warnings)

    ⛔ REPORTED, not fatal, and that is a measured decision rather than
    timidity. Run over the 7 golden fixtures, 26 of 132 real names use a
    superseded date form — the short `-DD` end that D8 replaced, or a pre-D14
    monthly bucket without its `00`. Those folders are ALREADY ON THE DRIVE.
    A check that refuses history cannot be switched on at all, so the
    superseded forms warn and nothing renames them. What IS refused is a name
    this grammar cannot parse, or one that drops `[where]` while the place is
    sitting resolved in `batches.json` — which is 6 of the 11 folders the
    first user test produced.

    ⛔ A leg is validated as a LEG. Legs are sub-folders inside a trip parent
    and carry `MMDD`, no year, because the parent already has one. Treating
    every name as a folder refused 32 of 132 names in the fixtures, nearly all
    of them correct — the reason this function takes a `kind` per name instead
    of one pattern.
    """
    refusals, warnings = [], []
    # ⭐ R13 — the shape of the R12 guard, said out loud. `place_known` arms
    # the [where] refusal, so the refusal can only ever fire on batches the
    # engine ALREADY named: the check is switched on by the very field whose
    # absence is the defect. On a real dump 10 of 17 batches had no place, 669
    # of 990 files, and every one of those names passed R12 in silence. R13
    # resolves far more of them, and what remains unresolved is now stated
    # rather than assumed to be fine.
    unnamed = [b for b in batches if not b.get("place") and b.get("gps_files")]
    if unnamed:
        warnings.append(
            "no [where] could be resolved for "
            + ", ".join(f"batch {b['batch']}" for b in unnamed)
            + " although GPS is present — the name below is unchecked for "
            "[where], so confirm the place is genuinely unknown rather than "
            "unasked (R13)")
    for _path, name, ref, warn in folder_name_checks(plan, batches, hard, soft, rows):
        refusals += [f"{name}: {r}" for r in ref]
        warnings += [f"{name}: {w}" for w in warn]
    return refusals, warnings


def folder_name_checks(plan, batches, hard=None, soft=None, rows=None):
    """-> [(folder path, name, refusals, warnings)], one per folder the plan
    names: its destination, each leg, each override's destination.

    `rows` (settled rows, or anything with `_action`/`_dest`/`_day`) give each
    folder the span of the days it KEEPS. Without them the span is the
    batches' own, which is wrong for any plan with an override: measured
    (B3b, 20260920), 4 of the 7 golden plans and both UAT02-01 plans this
    check failed kept exactly the day their name says — the other days had
    gone to an override — and the override folders (a `group split`'s pieces)
    were never checked at all."""
    out = []
    # A place is KNOWN when the clustering stage resolved one. Read from the
    # batch's own `place` field, never parsed out of `label`: the label is a
    # sentence in the owner's language.
    place_known = any(b.get("place") for b in batches)
    spans = [b.get("from") for b in batches if b.get("from")], \
            [b.get("to") for b in batches if b.get("to")]
    batch_span = (min(spans[0]), max(spans[1])) if spans[0] and spans[1] else None

    def kept_span(path):
        if rows is None:
            return batch_span
        days = sorted(r["_day"] for r in rows if r["_action"] == "copy"
                      and (r["_dest"] == path or r["_dest"].startswith(path + "/")))
        return (days[0], days[-1]) if days else None

    def folder(path, known):
        head = Path(path).name
        # ⛔ `photo_name.kind_of()`, not a regex of its own (M14). The inline
        # regex read `202600` as MONTHLY, whose legacy pattern then warned
        # about the engine's own new yearly bucket as a pre-D14 name.
        kind = photo_name.kind_of(head.split("_")[0])
        # ⚠️ The span is only meaningful for a folder that names one batch
        # run; a monthly bucket deliberately spans whatever landed in it.
        _ok, ref, warn = photo_name.validate(
            head, place_known=known and kind == photo_name.NAME_FOLDER,
            span=kept_span(path) if kind == photo_name.NAME_FOLDER else None,
            hard=hard, soft=soft, kind=kind)
        out.append((path, head, ref, warn))

    dest = (plan.get("dest") or {}).get("path")
    if dest:
        folder(dest, place_known)
    for leg in plan.get("legs") or []:
        name = leg.get("name") or ""
        # D-I13: the place words are written by `photo_index freeze`; a
        # hand-written plan has none and the rule stays unarmed.
        _ok, ref, warn = photo_name.validate(
            name, hard=hard, soft=soft, kind=photo_name.NAME_LEG,
            where=leg.get("where"), parent_where=plan.get("where"))
        out.append((f"{dest}/{name}", name, ref, warn))
    for ov in plan.get("overrides") or []:
        ov_dest = ov["dest"]
        path = ov_dest["path"] if isinstance(ov_dest, dict) else ov_dest
        # A plan's override entry carries no place words, so the [where]
        # refusal stays unarmed here; the index checks each piece against its
        # own places (`check`, since B3a re-resolves them). Two overrides may
        # share a folder, which is checked once.
        if all(path != o[0] for o in out):
            folder(path, False)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir")
    ap.add_argument("--plan", type=int, help="plan number from plans.json")
    ap.add_argument("--no-date", action="store_true",
                    help="write the no-date review plan instead of a batch plan")
    ap.add_argument("--ai-confirmed", action="store_true",
                    help="with --no-date: no_exif-rule files were visually "
                         "confirmed AI-generated -> route to YYYYMM00_AI-images "
                         "(default: everything -> the monthly to-be-checked "
                         "bucket)")
    ap.add_argument("--no-status", action="store_true",
                    help="do not advance batch status to planned")
    ap.add_argument("--no-vision", action="store_true",
                    help="plan even though the see stage has not run for "
                         "these batches (R1). WHO/WHAT are given up for them: "
                         "deliberate for a metadata-only dump, never a way "
                         "past a stage that simply has not been run yet")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    out_dir = workdir / "plan"
    out_dir.mkdir(exist_ok=True)
    # one pack per run, resolved once and passed down — every EXIF rule that
    # depends on whose photos these are reads it. Resolved as the whole PACK
    # rather than just the profile dict, because VS-4's provenance columns
    # need `.dir` (the subject registry lives inside the pack) and a second
    # resolution would be a second chance to load a different owner's.
    pack = photo_profile.resolve_pack(workdir=workdir)
    profile = pack.profile
    msg = photo_profile.messages(profile)

    if args.no_date:
        write_no_date_plan(workdir, out_dir, ai_confirmed=args.ai_confirmed,
                           profile=profile)
        return
    if args.plan is None:
        sys.exit("--plan N required (or --no-date)")

    config = json.loads((workdir / "plans.json").read_text())
    dest_root = resolve_dest_root(workdir, config, profile)
    plan = next((p for p in config["plans"] if p["plan"] == args.plan), None)
    if plan is None:
        sys.exit(f"plan {args.plan} not in plans.json")

    bdata = json.loads((workdir / "batches.json").read_text())
    batches = [b for b in bdata["batches"] if b["batch"] in plan["batches"]]
    if len(batches) != len(plan["batches"]):
        sys.exit("plan references batches missing from batches.json")

    # R1: vision before plan. Refuse rather than render a name that cannot
    # carry [who]/[what] -- the failure this replaces was silent, so the fix
    # has to say which batches, and why it matters, not just that it stopped.
    unseen = batches_without_vision(workdir, plan["batches"])
    if unseen and not args.no_vision:
        seen = [n for n in sorted(plan["batches"]) if n not in unseen]
        sys.exit(
            "the see stage has not run for batch(es) "
            + ", ".join(f"B{n}" for n in unseen)
            + ("" if not seen else
               " (B" + ", B".join(str(n) for n in seen) + " have been seen)")
            + ".\nPlanning now would name these folders from metadata alone: "
              "[who] and [what] cannot reach a folder name without it, and "
              "nothing downstream would report the loss.\n"
              "  Run the visual pass first:\n"
            + ("" if (workdir / "embed" / "embeddings.npy").exists() else
               f"    {photo_platform.venv_python()} {Path(__file__).resolve().parent}"
               f"/photo_embed.py \"{workdir}\"        # no embed/ yet\n")
            + f"    {photo_platform.venv_python()} {Path(__file__).resolve().parent}"
              f"/photo_see.py \"{workdir}\" --batch <N>\n"
              "  ...then re-run this plan.\n"
              "  --no-vision plans anyway, giving up WHO/WHAT for these "
              "batches.")

    rows, candidates, paperwork, paperwork_why = settle_rows(
        workdir, plan, batches, dest_root, profile, msg)

    # R12 — check the names before writing them, each folder against the days
    # it keeps (B3b). Said out loud on stderr so it
    # reaches an operator reading a terminal AND a log, and so a refusal is
    # never something only a careful reader of the plan document would notice.
    name_refusals, name_warnings = check_plan_names(
        plan, batches, *photo_profile.name_budget(profile), rows=rows)
    for w in name_warnings:
        print(f"  name warning: {w}", file=sys.stderr)
    for r in name_refusals:
        print(f"  NAME CHECK FAILED: {r}", file=sys.stderr)
    if name_refusals:
        # ⛔ The plan is still written, and the word above says "check failed"
        # rather than "refused" for that reason: a message that claims to have
        # stopped something it did not stop is worse than silence, because the
        # operator stops reading the rest. D10 — there is no pre-execution
        # approval gate, and copy-only reversibility is the safety net.
        #
        # ⚠️ MEASURED before choosing this: 7 of the 126 plans in the golden
        # fixtures failed this check, every one of them a folder ALREADY on
        # the drive. 5 of the 7 were the batch-span false positive (B3b,
        # 20260920); on the days each folder keeps, 2 remain, both plausibly
        # deliberate (a day trip named after its main day when the GPS leg
        # spilled into the next morning). A hard exit would block a re-plan of
        # real, accepted work — the stop for a NEW folder is `photo_index
        # freeze`'s (B3), which golden_replay never runs.
        print(f"  ({len(name_refusals)} name problem(s) — the plan was still "
              "written; read the name before executing it)", file=sys.stderr)

    visual = visual_columns(workdir, plan["batches"], profile, pack)

    # W2B-1 — before anything is written, so a refused name leaves no plan
    # file and no advanced batch behind it. ⛔ A hard stop, unlike R12's
    # grammar check above: R12 would refuse names already on the drive, and
    # this fires only when a pet's name has nothing to back it.
    unbacked = unbacked_names(plan, rows, visual, subject_names(pack))
    if unbacked:
        sys.exit(unbacked_message(args.plan, unbacked, msg))

    csv_path = out_dir / f"plan_P{args.plan}-files.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        header = ["SourceFile", "FileName", "batch", "date", "action",
                  "destination", "note"]
        w.writerow(header + (VISUAL_FIELDS if visual else []))
        for r in sorted(rows, key=lambda r: (r["_dt"], r["FileName"])):
            row = [r["SourceFile"], r["_name"], r["_batch"],
                   r["_dt"].strftime("%Y-%m-%d %H:%M"), r["_action"],
                   r["_dest"], r["_note"]]
            if visual:
                cell = visual.get(r["SourceFile"], {})
                row += [cell.get(k, "") for k in VISUAL_FIELDS]
            w.writerow(row)

    copies = [r for r in rows if r["_action"] == "copy"]
    skips = [r for r in rows if r["_action"] == "skip_dupe"]
    # counted by the tag route() set, never by searching the note text: the
    # note is a translated sentence and a substring match would count zero in
    # every language but the one it happens to be written in
    shots = [r for r in copies if "screenshot" in r["_tags"]]
    shared = [r for r in copies if "shared" in r["_tags"]]
    renamed = [r for r in copies if "renamed" in r["_tags"]]
    unknown = [r for r in copies if "unknown_format" in r["_tags"]]
    maybe_shots = [r for r in copies if "screen_candidate" in r["_tags"]]
    # W2C — what the paperwork check moved, and which copied STILLS it could
    # not judge. Videos are neither: they are never checked, so they are never
    # "not checked" either (Lead ruling, stills only).
    paper = [r for r in copies if "paperwork" in r["_tags"]]
    stills = [r for r in copies if r.get("FileType") in IMAGE_TYPES]
    unchecked = stills if paperwork is None else \
        [r for r in stills if r["SourceFile"] not in paperwork]
    reason = {"missing": msg["plan_paperwork_reason_missing"],
              "model": msg["plan_paperwork_reason_model"],
              None: msg["plan_paperwork_reason_unscored"]}[paperwork_why]
    paperwork_line = msg["plan_paperwork_not_run"].format(
        n=len(unchecked), reason=reason) if unchecked else None
    total_bytes = sum(int(r["FileSize"]) for r in copies if str(r["FileSize"]).isdigit())

    dest_counts = {}
    for r in copies:
        dest_counts[r["_dest"]] = dest_counts.get(r["_dest"], 0) + 1

    existing_subdirs = []
    dp = Path(plan["dest"]["path"])
    if plan["dest"]["mode"] in ("merge", "fill_shell") and dp.is_dir():
        existing_subdirs = sorted(d.name for d in dp.iterdir()
                                  if d.is_dir() and not d.name.startswith("."))

    md = [msg["plan_title"].format(plan=args.plan, title=plan['title']), "",
          msg["md_generated_at"].format(
              when=datetime.now().strftime('%Y-%m-%d %H:%M')),
          msg["md_source"].format(source=bdata['source']),
          msg["plan_batches"].format(
              batches=', '.join('B' + str(n) for n in plan['batches']),
              start=batches[0]['from'], end=batches[-1]['to']), "",
          msg["plan_h_destination"], "",
          msg["plan_dest_line"].format(
              mode=msg[MODE_MESSAGE_KEY[plan['dest']['mode']]],
              path=plan['dest']['path'])]
    if plan["dest"]["mode"] == "merge":
        md.append(msg["plan_dest_merge_note"])
    if existing_subdirs:
        md += [msg["plan_existing_subdirs"]]
        md += [f"  - `{d}`" for d in existing_subdirs]
    if plan.get("legs"):
        md += ["", msg["plan_h_legs"], "",
               msg["plan_legs_header"], "|---|---|---|"]
        for leg in plan["legs"]:
            n = sum(1 for r in copies if r["_dest"].endswith("/" + leg["name"]))
            md.append(f"| `{leg['name']}` | {leg['from']} → {leg['to']} | {n} |")
    for ov in plan.get("overrides", []):
        n = sum(1 for r in copies if r["_dest"] == ov["dest"])
        md += ["", msg["plan_h_override"], "",
               msg["plan_override_line"].format(
                   dates=', '.join(ov['dates']), n=n, dest=ov['dest']),
               msg["plan_override_reason"].format(reason=ov.get('reason', ''))]

    md += ["", msg["plan_h_stats"], "",
           msg["md_item_count_header"], "|---|---|",
           msg["plan_stat_total"].format(n=len(rows)),
           msg["plan_stat_copy"].format(n=len(copies)),
           msg["plan_stat_skip"].format(n=len(skips)),
           msg["plan_stat_screenshots"].format(n=len(shots)),
           msg["plan_stat_shared"].format(n=len(shared)),
           msg["plan_stat_renamed"].format(n=len(renamed)),
           msg["plan_stat_unknown_format"].format(n=len(unknown)),
           msg["plan_stat_paperwork"].format(n=len(paper)),
           msg["plan_stat_bytes"].format(size=human_size(total_bytes)), "",
           msg["plan_h_dest_counts"], "",
           msg["md_dest_count_header"], "|---|---|"]
    for d, n in sorted(dest_counts.items(), key=lambda x: -x[1]):
        md.append(f"| `{d}` | {n} |")

    if visual:
        # F14 — the per-file `who` was computed and written to the CSV, and
        # the document the owner approves never showed it: a name in the
        # folder could not be checked against what backs it without opening
        # the file list. Copies only, because a skipped duplicate is already
        # in some other folder and backs nothing here.
        seen = who_evidence(visual.get(r["SourceFile"]) for r in copies)
        md += ["", msg["plan_h_who_evidence"], "",
               msg["plan_who_evidence_intro"].format(n=len(copies)), "",
               msg["plan_who_evidence_header"], "|---|---|---|"]
        for s in seen["subjects"]:
            md.append(f"| {s['name']} | `{s['provenance'] or '-'}` "
                      f"| {s['files']} |")
        md += ["", msg["plan_who_evidence_none"].format(n=seen["no_subject"])]
        if seen["unseen"]:
            md.append(msg["plan_who_evidence_unseen"].format(n=seen["unseen"]))

    if plan.get("refs"):
        md += ["", msg["plan_h_dedupe"], "",
               msg["plan_dedupe_refs"].format(refs=msg["ref_separator"].join(
                   '`' + Path(r).name + '`' for r in plan['refs'])),
               msg["plan_dedupe_rule"],
               msg["plan_dedupe_result"].format(n=len(skips))]
        coll = 0
        for n in plan["batches"]:
            p = workdir / "plan" / f"dedupe_batch-{n:02d}.json"
            coll += json.loads(p.read_text())["collisions"]
        if coll:
            md.append(msg["plan_dedupe_collisions"].format(n=coll))
        md.append(msg["plan_dedupe_limitation"])

    if maybe_shots:
        # G-2's non-blocking half: the checkpoint the run could not stop to
        # hold is queued here and in SCREEN_PROPOSALS_NAME instead.
        md += ["", msg["plan_h_screen_candidates"], "",
               msg["plan_screen_candidate_intro"].format(
                   n=len(maybe_shots),
                   bucket=photo_profile.buckets(profile)["to_be_checked"]), ""]
        for key in sorted(candidates):
            c = candidates[key]
            md.append(msg["plan_screen_candidate_row"].format(
                w=c["dims"][0], h=c["dims"][1], files=c["files"],
                witness=c["witness"]))

    if paper:
        # ADR 0005 — the disclosure is part of the feature, not a log line.
        bucket = photo_profile.buckets(profile)["to_be_checked"]
        intro = msg["plan_paperwork_intro"].format(n=len(paper), bucket=bucket)
        md += ["", msg["plan_h_paperwork"], "", intro, ""]
        md += [f"- `{r['_name']}`" for r in sorted(paper, key=lambda r: r["_name"])]
        print(f"  {intro}", file=sys.stderr)
    if paperwork_line:
        print(f"  {paperwork_line}", file=sys.stderr)

    if plan.get("notes"):
        md += ["", msg["plan_h_notes"], "", plan["notes"]]
    md += ["", msg["plan_h_safety"], "",
           msg["plan_safety_readonly"],
           msg["plan_safety_dest_root"].format(root=dest_root),
           msg["plan_full_file_list"].format(path=csv_path.name),
           # G-3: the residual case the filename list cannot reach is stated
           # every run rather than only when it is suspected — the engine
           # cannot know which files it failed to recognise.
           msg["plan_screen_capture_limit"]]
    if paperwork_line:
        # Stated where the other known limits are, and only when it bit.
        md.append(f"- {paperwork_line}")
    md += ["", msg["plan_safety_approval"], ""]

    md_path = out_dir / f"plan_P{args.plan}.md"
    md_path.write_text("\n".join(md))

    # Queued, not asked, and never pasted into the pack (F-13): nothing adds
    # these sizes from here. The G-1 shape keeps the sizes reading the same
    # everywhere; `model` is null because a screenshot carries no camera tags
    # and the engine will not guess whose phone it was.
    if candidates:
        # Every plan of a dump writes this one file, so the moved count is kept
        # PER PLAN and summed by whoever prints it. `finish` shows the banner
        # once, after the last plan — a single plan's count presented as the
        # dump's would read 0 whenever the last plan happened to hold none.
        # The proposed sizes need no such care: they are dump-wide already.
        queue_path = out_dir / SCREEN_PROPOSALS_NAME
        moved = {}
        if queue_path.exists():
            previous = json.loads(queue_path.read_text()).get(
                "moved_to_to_be_checked")
            moved = previous if isinstance(previous, dict) else {}
        moved[str(args.plan)] = len(maybe_shots)
        queue_path.write_text(json.dumps({
            "proposed_screen_dims": [
                {"model": None, "dims": [int(v) for v in candidates[k]["dims"]],
                 "files_at_this_size": candidates[k]["files"],
                 "proven_by": candidates[k]["witness"]}
                for k in sorted(candidates)],
            "moved_to_to_be_checked": moved,
        }, ensure_ascii=False, indent=1))

    # W2C — kept PER PLAN, like the screen-candidate count, and summed by
    # `photo_run` for the banner. Written when something moved or a count is
    # already on file, so a re-plan that now moves nothing resets its entry.
    moved_path = out_dir / PAPERWORK_MOVED_NAME
    if paper or moved_path.exists():
        moved = {}
        if moved_path.exists():
            try:
                moved = json.loads(moved_path.read_text())
            except ValueError:
                moved = {}
        moved = moved if isinstance(moved, dict) else {}
        moved[str(args.plan)] = len(paper)
        moved_path.write_text(json.dumps(moved, indent=1))

    if not args.no_status:
        bpath = workdir / "batches.json"
        shutil.copy2(bpath, bpath.with_suffix(".json.bak"))
        for b in bdata["batches"]:
            # A copied batch stays `done`: a re-lock after the copy re-renders
            # every plan, and demoting it made `finish` re-approve all of them,
            # a dry run included (FIX9 F7b).
            if b["batch"] in plan["batches"] and b.get("status") != "done":
                b["status"] = "planned"
                b["planned_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        bpath.write_text(json.dumps(bdata, ensure_ascii=False, indent=1))

    print(f"plan P{args.plan}: {len(rows)} files = {len(copies)} copy "
          f"+ {len(skips)} skip_dupe ({human_size(total_bytes)}) -> {md_path}")


if __name__ == "__main__":
    main()
