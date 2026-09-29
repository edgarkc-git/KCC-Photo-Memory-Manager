#!/usr/bin/env python3
"""VS-3 — the subject registry: who this owner's recurring subjects are, and
the exemplar vectors that recognise them in a photograph.

The registry lives in the OWNER PACK (`photo-subjects/`), never in this repo.
The engine ships the mechanism and no subjects at all: a blank pack means
every function here is a no-op that returns nothing, which is what makes the
benchmark's blank-sheet rule (V2-6) hold by construction rather than by a
literal in one test.

## One subject model, not two

`photo-entities.json` holds the facts a human reads — `who` (relation to the
owner), `name`, `kind`, `active`. This registry holds the vectors. Both key on
the SAME `subject_id`, so a subject has exactly one identity across the pack
(Memory-System DESIGN). That id is also the merge key for recurring-subject /
D9 folders under naming SPEC **N-10a**: the confirmed name REPLACES the
routing class word there, which makes the rendered folder name mutable, and a
mutable string is not a key. `photo_recurrence.subject_folder()` does the
keying; `folder_for()` below is its caller, holding the confirmed entry.

    subjects.json         one record per subject + its exemplar list
    vectors/<id>.npy      (N, D) float32, L2-normalised, row order == exemplars[]

## Recognition Level 2 — timeline gating

A match is only ELIGIBLE inside the subject's `active` range ± tolerance, and
the date compared is the FILE'S OWN capture date, passed in by the caller from
its EXIF. Never the folder path: a 2020-dated file sitting inside a folder
named for 2023 is a 2020 file, and a matcher that reads the era off the path
calls it a negative. The benchmark keeps such files on purpose.

A subject with no declared `active` range is ungated — the gate can only
exclude on evidence it has.

## The memorize rule (anti-drift) — the critical constraint

Only `confirmed_by: "viewed-image"` may enter `exemplars`. `clip-matched` and
`clip-propagated` are the registry's OWN output; letting output back in as
evidence is how a registry drifts on its own errors, and it is the same class
of mistake as the 2026-07-20 fabrication incident. `add_exemplar()` refuses
any other provenance at the point of writing — not at review time, when the
vector is already in the file.

⚠️ **VS-4: the string is not the rule.** Until VS-4 the check was
`confirmed_by == "viewed-image"` and nothing else, so a caller holding a
`clip-matched:` file and the correct spelling was memorized. A promotion now
carries EVIDENCE — the see-report that selected the file, the batch, and the
thumbnail the model opened — and `photo_evidence.evidence_problems()`
re-derives all of it from disk at the write point. Both halves must hold: the
right provenance AND a look that can be shown.

Every attempt, accepted or refused, appends one line to
`photo-subjects/memorize-audit.jsonl` in the pack. That file is the answer to
"prove the registry only grew from vision-confirmed matches" — the refusals
are the interesting half, and a log that only recorded successes would not be
an audit log. It is written at the decision point, not at `save()`, so a run
that crashes still leaves its trail.

The store is capped (`exemplar_cap`, 24) and DIVERSITY-kept: at the cap the
most redundant exemplar is dropped, not the oldest. Twenty-four near-identical
burst frames recognise one afternoon; twenty-four different ones recognise a
subject.

## Cardinality is never auto-resolved

Two subjects that both clear `accept` on one file, or two lookalike clusters,
produce a "one subject or two?" QUESTION with a contact sheet. Nothing here
merges them. A wrong merge mislabels both subjects forever and silently; a
wrong split costs one extra question. The question is a structured record —
rendering it into a review table is VS-4's job, not this module's.

⛔ **`review --merge` is not a hole in that rule** (U-1). It is the OWNER
saying two records they each named are one animal, typed as two ids after
looking at both; geometry proposes nothing and no similarity is consulted.
What it adds is a DOOR, not a verb — `fold_subjects()` has held SNS-14 since
step 7, but its only caller was a `recheck:` name collision on a live review
table, which needs a checkpoint in a work dir. Two subjects confirmed in an
earlier round, which no later checkpoint asks about again, could not be
rejoined at all; that is the gap, and it is a reachability gap.

## F14 — suppression is not a merge

A cluster that looks like an ALREADY CONFIRMED subject opens no draft and
raises no question: `observe_draft_subject()` records the sighting against
that subject and returns `known`. Before this, `confirm` moved a subject out
of the draft pool and wrote no exemplar, so the same animal came back next
dump as a NEW `subject_id` with a new naming question. Answering the question
did not stop the question.

The distinction that keeps this inside the doctrine above:

  * a MERGE collapses two ids into one confirmed identity on geometry alone —
    still forbidden, still a human's answer, and nothing here does it;
  * a SUPPRESSION only declines to open a third record and to ask a question
    that has already been answered. It writes no name, no exemplar and no
    timeline — nothing that a later reader could mistake for a fact somebody
    confirmed. Its whole footprint is `obs_count` / `observed_in` / evidence,
    which is bookkeeping about what was seen, not a claim about who it was.

Geometry becomes recognition evidence at exactly one point, `confirm`, where
the human yes exists — `photo_memory.attach_exemplars()` promotes the members'
looks through `add_exemplar()` below, gates and all.

## Thresholds are starting values, not tuned ones

`accept` 0.82 / `gray_low` 0.70 are the Visual-Sorting DESIGN's numbers,
pending calibration on a benchmark replay; the timeline tolerance and the
exemplar cap are the engine's own starting values. All four live in the PACK
(`defaults`, overridable per subject) so an owner can move them without
touching the engine — written down so the mechanism works, not derived from a
measurement yet. (`photo_see.RUNG1_BUDGET_SHARE` no longer shares this
posture: it has been swept on the benchmark replay. These four have not.)

## Dependencies

numpy, imported lazily inside the functions that compare vectors — an empty
registry answers without importing anything.

Usage:
  python3 photo_subjects.py review                     # from a collection
                                                       # workspace: the pack is
                                                       # resolved from
                                                       # collection.json
  python3 photo_subjects.py review "<Working Files>/202605__"
  python3 photo_subjects.py review --profile <pack> --json out.json
  python3 photo_subjects.py review --profile <pack> --prune --go
  python3 photo_subjects.py review --profile <pack> --unconfirm subj-0001 --go
  python3 photo_subjects.py review --profile <pack> \
      --merge subj-0039 subj-0013 --go

The pack reaches this stage by the same three routes as every other stage —
`--profile`, `$PHOTO_PROFILE`, or `collection.json` (via the work-dir
positional, or via the workspace folder you are standing in). ⛔ The positional
is a WORK DIR or a workspace, never a pack path; a pack goes to `--profile`.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import photo_embed  # noqa: E402
import photo_evidence  # noqa: E402
# stdlib-only at import time (its torch/PIL imports are inside functions),
# so the plan-stage tests stay runnable with no ML deps present
import photo_identity  # noqa: E402
import photo_profile  # noqa: E402

SUBJECTS_DIRNAME = "photo-subjects"
REGISTRY_NAME = "subjects.json"
VECTORS_DIRNAME = "vectors"
DRAFT_VECTORS_DIRNAME = "draft-vectors"
# VS-3b. A SECOND vector space, for identity only. Its own directory because
# it is a different model over a different picture (a crop, not the frame) and
# the two are never comparable — see photo_identity.py for why one embedding
# cannot do both jobs. Stored as an .npz keyed by `vec_ref` rather than as a
# positional array like `vectors/`: an exemplar may have a CLIP vector and no
# identity vector (no animal was detected in it, or the pack predates this
# stage), and a positional array would make that a hole nobody can read past.
IDENTITY_VECTORS_DIRNAME = "identity-vectors"
# ⚠️ Named in `photo_profile.SNAPSHOT_EXCLUDE` as well, and the two must
# agree: this file is append-only provenance, so it is the one thing under
# `photo-subjects/` the pack snapshot does not hash. A rename here that is not
# made there puts a refusal's audit line back inside the pack id.
AUDIT_NAME = "memorize-audit.jsonl"
SUBJECT_ID_PATTERN = re.compile(r"^subj-\d{4,}$")

# The one provenance a vector may enter the store under. Everything else is
# the registry's own output — see the memorize rule above.
MEMORIZE_PROVENANCE = "viewed-image"

# The two vector spaces a verdict can be decided in. ⛔ LL-PHO-105: an
# identity verdict is only real if the row says `identity` — `subject_verdict_
# spaces` said `clip` for everything until 3d229f0, and every subject verdict
# in the first user test was CLIP while being read as identity. The rule that
# came out of it is that an accept count is never quoted without its space, so
# any surface an owner reads an accept from has to carry one.
#
# ⛔ The space is recorded WHERE THE COMPARISON RUNS and stored with the
# decision. It is never re-derived later from current config: what a pack is
# configured for today is not what ran on the day, and re-deriving it is
# LL-PHO-105 rebuilt somewhere new.
SPACE_CLIP = "clip"
SPACE_IDENTITY = "identity"


def absorbed_space(record):
    """-> the space an absorb was decided in, or None when the row does not
    say.

    ⛔ None means NOT RECORDED and must be rendered as that. A row written
    before the space was stored cannot be given one retroactively, and
    guessing `clip` because it probably was is exactly the claim LL-PHO-105
    forbids — a space nobody measured, presented as if somebody had.

    ⚠️ None is also what an OWNER-ANSWERED absorb returns (SNS-16's attach),
    and that is a different thing said the same way: no geometry ran, so there
    is no space. Those rows carry `answered: True` and a null score, which is
    how a caller that needs to tell them apart does it.
    """
    return ((record or {}).get("absorbed") or {}).get("space") or None

# A subject record's maturity, mirroring the memory system's provenance
# ladder. A draft GAINS no exemplars: it is a subject the census noticed, not
# one anybody has confirmed. It may HOLD them — a withdrawn confirmation keeps
# its evidence frozen so re-confirming stays cheap (`unconfirm`) — and status,
# never the presence of evidence, is what decides whether it recognises
# anything.
STATUS_DRAFT = "ai-drafted"
STATUS_REINFORCED = "ai-reinforced"
STATUS_CONFIRMED = "human-confirmed"
# OA-14 / OA-16 — the owner said "never ask me about this again". Decided in
# step 3, and the four halves are one decision:
#
#   * it HOLDS NO NAME. `rejected` is outside `is_draft` exactly like
#     `superseded`, so `photo_plan.py:132`'s `name and not is_draft` would
#     print a name on it as a confirmed answer with no `draft:` marker. The
#     write sites are gated, not trusted (`rename()`, `cmd_confirm()`);
#   * it GAINS NOTHING and RECOGNISES NOTHING — `add_exemplar()`'s third gate
#     and `recognisers` both read `human-confirmed`, so any exemplars frozen
#     onto it by an earlier confirmation attribute no file;
#   * it KEEPS ITS DRAFT CENTROID, and that is the whole of OA-14:
#     `rejected_match()` suppresses on it, so the rejected subject stops
#     returning under a fresh `subject_id` on the next dump;
#   * it IS REVIVABLE — `revive()`. A rejection that suppresses is a stronger
#     door than one that only hides, and SNS-5's fourth job is that no
#     permanent decision is invisible to the owner.
STATUS_REJECTED = "rejected"
# SNS-1b — a draft the owner split across two answers. It is deliberately in
# NEITHER whitelist: outside `is_draft` it leaves the question loop with no
# change to `build_questions()`, and outside `human-confirmed` it recognises
# nothing and suppresses nothing. What holds that pair together is that a
# superseded record carries NO NAME — `partition_subject()` refuses to make
# one that does, because every reader that renders a name gates on the name
# and not on the status.
STATUS_SUPERSEDED = "superseded"
# SNS-15 — a draft the sweep recognised as a subject the owner just named.
# In NEITHER whitelist, for the same two reasons `superseded` is in neither:
# outside `is_draft` it leaves the question loop, and outside `human-confirmed`
# it recognises nothing and suppresses nothing on its own.
#
# ⭐ What separates it from every other status here is what it does NOT write.
# Absorption writes no name, no exemplar, no timeline and no contact sheet —
# it only declines to ask a question whose answer the owner already gave, so
# V2-5a is untouched (F14's suppression argument, exactly). An absorbed
# draft's files still render the class word with `draft:` provenance until
# they match the confirming subject's exemplars at the `accept` bar; the
# absorption never puts a name on a file.
#
# And because nothing was written, the reversal is cheap and is BUILT:
# `unconfirm()` releases every draft absorbed under the withdrawn name back to
# `ai-drafted`. A sweep with no way back would make the cheapness argument
# false and take Pattern 6's undo with it.
STATUS_ABSORBED = "absorbed"
# SNS-14 — one of two subjects the owner confirmed separately and has since
# said are one animal. The loser survives as an ALIAS TOMBSTONE so every id
# ever written into a plan CSV, a see-label or a folder record still resolves;
# `merged_into` names the winner.
#
# In NEITHER whitelist, for the third time and the same two reasons: outside
# `is_draft` it never returns to the question loop, and outside
# `human-confirmed` it recognises nothing, suppresses nothing and gains
# nothing. It holds NO NAME either — the names it held move to the winner's
# `previous_names`, which is what keeps `rename_ledger()` resolving every
# folder ever written under them (N-10a holds across the fold) while
# `photo_plan.py:132`'s `name and not is_draft` can never render a tombstone as
# a second confirmed identity for one animal.
#
# ⚠️ What is different about this status, and it is the sharp edge of the whole
# fold: `Registry.get()` FOLLOWS it. Every other status is inert — a reader
# that fetches the record gets the record. A caller that fetches a tombstone
# gets the WINNER, so the ~20 call sites that fetch a record in order to branch
# on its status or to mutate it must ask for the literal record instead
# (`get_literal()`), or a refusal written about a dead id would be applied to a
# live one. Every such site is named in this module and in `photo_memory`.
STATUS_MERGED_INTO = "merged-into"
# How far `get()` will walk a chain of tombstones before it calls the pack
# corrupt. The engine writes no chain at all — `fold_subjects()` re-points
# every tombstone that already named the loser at the new winner, so the
# invariant "no tombstone points at a tombstone" holds in STORAGE and this
# limit is only ever met by a hand-edited pack.
MERGE_FOLLOW_LIMIT = 16

# SNS-5 — the flag that lets a withdrawal reach the WORK-DIR dedupe layer.
# Recorded as debt when step 1 shipped: `unconfirm()` clears the pack-log layer
# (`photo_memory.settled_subjects()`) but a review file in the work dir has
# already booked the subject, so `photo_memory.asked_before()` goes on
# suppressing it until its evidence grows — and evidence is exactly what a
# subject the owner named wrongly may never gain again. Withdrawn in the log,
# invisible in the work dir.
#
# ⚠️ A QUESTION-LOOP flag, never history. The history of the decision is
# `unconfirmed` / `revived` on the record and those are kept forever; this one
# is popped the moment the question is answered again (`photo_memory.
# cmd_confirm`, on BOTH answer paths). Reading the history markers instead
# would exempt the subject from layer 2 for the rest of the pack's life.
REOPENED_FLAG = "reopened"

# ADR 0004 (iv) — set ONLY by `photo_onboard_page.declare_pets()`, on a record
# it created: the owner said at setup "I have an animal called this". A plain
# `name:` at the checkpoint then joins that record without `same`, because
# the owner already answered SNS-7's question. ⛔ Never inferred for a record
# without it — an older pack's same-named record still gets the ask.
DECLARED_FLAG = "declared"

# F13 (iii)(b) — the name a record was given with an owner-typed `distinct`:
# "this is a DIFFERENT animal that shares the name". Written ONLY where that
# answer is applied (`photo_memory.cmd_confirm`, both doors). `name: X same`
# over several holders folds them unless one carries this for X, because
# folding would then merge two animals. ⛔ Never inferred for an older pack.
DISTINCT_FLAG = "named_distinct"

# ⚠️ STARTING VALUES, NOT CALIBRATED. accept/gray_low are the Visual-Sorting
# DESIGN's numbers and are calibrated on a benchmark replay, not chosen here;
# the tolerance and the cap are this module's own starting values, written
# down so the gate has a width at all. A pack overrides any of them, globally
# in `defaults` or per subject in `thresholds` — which is where an owner's
# tuned numbers belong, since the engine holds no owner thresholds.
DEFAULT_THRESHOLDS = {
    "accept": 0.82,
    "gray_low": 0.70,
    "timeline_tolerance_days": 45,
    "exemplar_cap": 24,
    # VS-4: how close two unmatched clusters must be to count as the SAME
    # draft subject across batches. Inherited from the census's own
    # cross-census dedupe (photo_recurrence.DEDUPE_TAU) so one pipeline holds
    # one definition of "the same thing"; also a starting value, and it lives
    # in the pack for the same reason the four above do.
    "draft_dedupe_tau": 0.85,
    # F14: how close a new cluster must sit to a CONFIRMED subject's exemplars
    # before the draft store declines to open a record for it. Deliberately
    # its OWN parameter, read from neither neighbour:
    #   * not `draft_dedupe_tau` — one threshold serving a dedupe and a
    #     suppression is the coupling ONB-13a's fault table names (b), where
    #     lowering it to merge drafts also changes what gets asked;
    #   * not `accept` — that bar decides whether a FILE is attributed to a
    #     subject, this one decides whether a QUESTION is asked, and the two
    #     move for different reasons.
    # The comparison is the same shape `match()` scores (cluster centroid
    # against exemplar rows, max cosine), so `accept` 0.82 is the floor the
    # starting value sits on: strict, because over-suppressing hides a real
    # second subject silently while under-suppressing only re-asks visibly.
    # A starting value like the five above it, not a measured one.
    "confirmed_suppress_tau": 0.85,
    # VS-3b, and they replace nothing: these two gate the IDENTITY space, the
    # five above gate the CLIP space, and a run uses whichever space both
    # sides of the comparison have. Two numbers rather than one because the
    # identity space is decided RELATIVELY — measured on the 20260821 trial,
    # a fixed cosine either missed most true sightings or named an impostor,
    # while "clearly the nearest, and not close" separated them cleanly:
    #   * `identity_floor` — below this nothing is claimed at all, however far
    #     ahead of the runner-up it is. This is what stops a photograph of a
    #     stray cat being named after the household one merely because that
    #     subject holds the biggest exemplar bank;
    #   * `identity_margin` — how far the leader must sit above the SECOND
    #     subject. Two subjects a hair apart is a question, not a ranking,
    #     which is the same posture AMBIGUITY_MARGIN takes in the CLIP space.
    # ⚠️ STARTING VALUES from 15 true queries and 5 impostors in ONE household
    # — a direction, not a calibration. The floor was chosen where impostors
    # stopped being named at all; a lower one recognised 4 more true sightings
    # and named 1 impostor, which is the wrong trade: a missed sighting costs
    # one question, a wrong name is written silently.
    "identity_floor": 0.45,
    "identity_margin": 0.02,
    # U2-12: below this cosine, two frames in ONE draft group are far enough
    # apart in the IDENTITY space to be two different animals, and the group
    # is flagged for the owner to look at. ⛔ It gates a WARNING, never a
    # split: the engine may not decide that a group is two subjects, because
    # `pick:` already lets the owner say so and a geometric split would be the
    # engine writing an identity nobody confirmed.
    #
    # ⚠️ A STARTING VALUE from ONE household — 8 identity vectors over 2
    # animals, 12 within-animal pairs and 16 between-animal pairs. The bands
    # separate there: lowest within 0.3795, highest between 0.2704, and this
    # sits in the gap. ⛔ Read the n before moving it, and re-measure with the
    # frames LABELLED BY APPEARANCE — on that same set, grouping the frames by
    # SUBJECT ID instead inverts the bands to 0.1677 apart in the WRONG order,
    # and the conclusion "no threshold separates these" was an artefact of two
    # subject records holding one animal, not a fact about the space.
    "group_coherence_tau": 0.33,
    # OA-14: how close a new cluster must sit to a REJECTED subject's retained
    # draft centroid before the draft store declines to open a record for it.
    # Its own parameter for the same reason `confirmed_suppress_tau` is, and
    # the inputs differ from both neighbours':
    #   * not `confirmed_suppress_tau` — that one scores a fresh centroid
    #     against EXEMPLARS a human yes promoted; this one scores it against a
    #     first-sighting centroid nobody curated, and the replay showed those
    #     sit systematically lower (the same argument SNS-15 makes for
    #     `{sweep_absorb_tau}`);
    #   * not `draft_dedupe_tau` — that one decides whether two sightings are
    #     ONE draft, this one decides whether a QUESTION is asked at all, and
    #     a rejection is the answer that no later checkpoint re-opens by
    #     itself.
    # Starts at the dedupe's value because the comparison has the same shape,
    # and moves on the build step 8 replay, not here.
    "rejected_suppress_tau": 0.85,
    # SNS-15: how close an EXISTING draft must sit to the exemplars of the
    # subject just confirmed before the sweep declines to ask about it again.
    # Its own parameter, and the third one on this list that had to be argued
    # for separately:
    #   * not `confirmed_suppress_tau` — that one scores a FRESH cluster
    #     centroid computed from the batch being observed; this one scores a
    #     possibly year-old FIRST-SIGHTING centroid that has never been
    #     updated, and those sit systematically lower. One threshold over two
    #     inputs would either under-absorb (the questions the sweep exists to
    #     kill keep coming back) or over-absorb on the fresh side;
    #   * not `draft_dedupe_tau` — that one decides whether two sightings are
    #     ONE draft, with no human in the story at all.
    # The error asymmetry is suppression's: over-absorbing hides a real second
    # subject silently, under-absorbing re-asks visibly. So it starts strict,
    # at the value its two neighbours start at, and moves on the build step 8
    # replay rather than here.
    "sweep_absorb_tau": 0.85,
    # SNS-9: how many names the pack may hold before the confirm checkpoint
    # says something. ⛔ A WARNING, NOT A CAP — the difference is the whole
    # decision. ONB-13's `{10}` was a hard refusal at the one place a name is
    # written, justified by a context cost that does not exist: no remembered
    # subject is ever placed in a prompt, identification is numpy over `.npy`
    # rows on disk, and the classify path resolves names by registry lookup at
    # write time. A remembered subject costs disk and a matrix multiply.
    #
    # What is left worth saying is the runaway case: a clustering bug minting
    # names nobody typed. That is a thing to NOTICE, not a thing to refuse,
    # because the refusal falls on the owner naming their household's
    # fiftieth subject and not on the bug.
    "named_subjects_warn_at": 50,
    # N-9's `{3}` names-per-folder cap (SPEC v0.7, and the one part of N-9 the
    # 2026-08-15 amendment left standing). It bounds READING a folder name,
    # not remembering a subject — `named_subjects_warn_at` above is the other
    # question and they move for different reasons. Beyond the cap the SPEC
    # says use a collective noun, which is what `photo_plan` renders: a folder
    # of five cats printing three of their names would be a false statement
    # about the folder, and it reads as a complete one.
    # A PARAMETER, not a constant — a household with more animals than this
    # can raise it in `defaults` without an engine change.
    "names_per_folder": 3,
    # ONB-13a's two `{n}` parameters for the `Group it` question. NEITHER IS
    # SIGNED OFF — they live here so the numbers can move without an engine
    # change, and so the reason for each one is written down next to it.
    #
    # How many example frames each numbered tile carries. The SPEC's parameter
    # table says the shipped 3 is "probably too few", because direction C moves
    # the cardinality judgement onto these thumbnails; the TEMPLATE's own
    # worked example shows 5, so 5 is what this follows.
    "contact_frames_per_draft": 5,
    # How many tiles one question renders. The SPEC leaves it unset: a class
    # with 200 drafts is not one readable question, so the top `{n}` by blast
    # radius are rendered and the rest DEFER — they are not skipped and not
    # recorded as asked. 12 sits just above the `{10}` name budget, so one
    # answer can still group everything on screen down to names the pack is
    # allowed to hold.
    #
    # ⚠️ It bounds ONE QUESTION's readability, never the round's cost, and
    # since 2026-08-21 it is the SECOND of two bounds, not the only one.
    # `tiles_per_round` below binds FIRST — every renderable draft of every
    # kind is ranked on one scale and cut to that ceiling, and only the
    # survivors are grouped into per-kind questions. So this one bites only
    # where a pack sets it BELOW `tiles_per_round`: at the shipped 12/12 a
    # kind can hold at most 12 of the top 12, so the slice is provably the
    # whole list. That is a property of the two DEFAULTS lining up, not a
    # retirement of this parameter — a pack that wants short questions inside
    # a full round (say 4 per question under a ceiling of 12) sets it lower
    # and it binds again. ⛔ Do not delete it and do not fold the two into
    # one number: they answer different questions — "how much can the owner
    # read in one block?" and "how much may one interruption cost?"
    "drafts_rendered_per_question": 12,
    # SNS-4 — how many tiles ONE ROUND may put in front of the owner, TOTAL,
    # across every kind it carries. Signed off 2026-08-21.
    #
    # A round is one interruption carrying one question per kind (SNS-4, as
    # amended 2026-08-20), so the per-question clamp above bounded a QUESTION
    # and nothing bounded the interruption: `tests/memorize_replay.py`'s first
    # whole-dump run measured one round carrying 7 questions and 45 tiles,
    # charged as ONE round against a soft cap of 4 per dump, in a shape that
    # permits 12 x 7 = 84. The owner has actually answered 12 tiles in one
    # sitting, so 12 is what a round may cost.
    #
    # Ranked ACROSS kinds on one blast-radius scale — the same
    # `(-files, subject_id)` total order the drafts already arrive in — so a
    # kind may be shut out of a round entirely. That is accepted: it returns
    # at the next checkpoint, recorded in `suppressed` with its own sentence,
    # never dropped and never booked as asked.
    #
    # A starting value like every number above it, moved by measurement (the
    # whole-dump replay) and not by argument here.
    "tiles_per_round": 12,
    # SNS-5 / SNS-9 — how many frames a RE-PRESENTED subject shows. ⚠️ Its own
    # parameter, and merging it back into either neighbour is the specific
    # mistake SNS-9 calls "two budgets, not one":
    #   * not `contact_frames_per_draft` — that one is a SAFETY number set by
    #     detection (at 1 frame a second subject in the same cluster is simply
    #     not on screen, SNS-12), because the owner is making an identity
    #     judgement. This one buys a NAME CHECK — "still that name?" — where
    #     the owner already made the identity judgement once;
    #   * not `drafts_rendered_per_question` — that budget bounds how many NEW
    #     subjects one question asks about and it DEFERS what it cannot fit.
    #     Re-presentation is unconditional (SNS-5) and defers nothing, so a
    #     shared budget would either overflow before a single new subject was
    #     asked about or truncate the re-presentation, which makes the word
    #     "unconditional" false and takes the undo path away with it.
    # 1-2 in the SPEC's table; 2 so that a subject that has absorbed a second
    # animal can show one frame of each. A starting value like every number
    # above it, moved by the build step 8 replay and not here.
    "frames_per_reconfirmation": 2,
}

# Two subjects this close at the top of one file's scores are not a ranking,
# they are a question. Also a starting value.
AMBIGUITY_MARGIN = 0.03
# The identity space's gray band, as a fraction of its own floor — the CLIP
# space's gray_low (0.70) sits at the same fraction of its accept (0.82), so
# "nearly" means the same kind of thing in both spaces without pinning a
# second absolute number to a scale that has not been calibrated.
GRAY_LOW_RATIO = 0.70 / 0.82

VERDICT_ACCEPT = "accept"
VERDICT_GRAY = "gray"
VERDICT_QUESTION = "question"
VERDICT_NONE = "none"


# ------------------------------------------------------------- date help ----

def _bound(value, end=False):
    """`active` accepts YYYY, YYYY-MM or YYYY-MM-DD. An END bound covers the
    whole of its last unit, so active ["2029-03", "2031-08"] includes every
    day of 2031-08 rather than stopping on the 1st."""
    if not value:
        return None
    text = str(value).strip()
    for fmt, unit in (("%Y-%m-%d", "day"), ("%Y-%m", "month"), ("%Y", "year")):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if not end:
            return dt
        if unit == "day":
            return dt.replace(hour=23, minute=59, second=59)
        if unit == "month":
            nxt = (dt.replace(year=dt.year + 1, month=1) if dt.month == 12
                   else dt.replace(month=dt.month + 1))
        else:
            nxt = dt.replace(year=dt.year + 1)
        return nxt - timedelta(seconds=1)
    raise ValueError(f"active bound {value!r} is not YYYY, YYYY-MM or YYYY-MM-DD")


def normalize_provenance(value):
    """`viewed-image:` (the plan-CSV prefix form) and `viewed-image` (the pack
    schema form) are the same claim. One spelling reaches the comparison.

    The vocabulary itself lives in `photo_evidence`, which is where all three
    consumers of it now read from."""
    return photo_evidence.normalize(value)


def _evidence_summary(evidence):
    """What the audit log and the exemplar record keep of a promotion's proof.

    The see-report path, batch, viewed file, thumbnail and returned label —
    enough for a human to re-open the exact image the model was shown, which
    is the only form of "prove it" worth writing down. `None` when a caller
    supplied nothing, so a refusal line says so rather than looking empty."""
    if not isinstance(evidence, dict):
        return None
    keep = ("see_report", "batch", "path", "sample", "label", "run_id")
    return {k: evidence[k] for k in keep if k in evidence}


# ---------------------------------------------------------------- subject ---

class Subject:
    """One registry record. `record` is the live dict — edits land in the file
    the Registry writes back."""

    def __init__(self, record, defaults):
        self.record = record
        self.defaults = defaults

    def __repr__(self):
        return f"<Subject {self.subject_id} exemplars={len(self.exemplars)}>"

    @property
    def subject_id(self):
        return self.record.get("subject_id")

    @property
    def name(self):
        return self.record.get("name") or None

    @property
    def kind(self):
        return self.record.get("kind") or None

    @property
    def who(self):
        return self.record.get("who") or None

    @property
    def exemplars(self):
        return self.record.setdefault("exemplars", [])

    @property
    def previous_names(self):
        return list(self.record.get("previous_names", []))

    @property
    def status(self):
        """Maturity, on the memory system's own ladder. Derived when absent so
        a pack written before VS-4 still answers: a record with both halves of
        ONB-13's identity pair (`who` + `name`) came from a human, anything
        else is a draft."""
        stored = self.record.get("status")
        if stored:
            return stored
        return STATUS_CONFIRMED if (self.name and self.who) else STATUS_DRAFT

    @property
    def is_draft(self):
        return self.status in (STATUS_DRAFT, STATUS_REINFORCED)

    @property
    def obs_count(self):
        return int(self.record.get("obs_count", 0))

    @property
    def observed_in(self):
        """The batches this subject has been seen in — the list that makes
        "one question for K batches" checkable rather than asserted."""
        return list(self.record.get("observed_in", []))

    def threshold(self, key):
        packed = (self.record.get("thresholds") or {})
        return packed.get(key, self.defaults.get(key, DEFAULT_THRESHOLDS[key]))

    def active_bounds(self):
        active = self.record.get("active") or []
        start = _bound(active[0] if len(active) > 0 else None)
        end = _bound(active[1] if len(active) > 1 else None, end=True)
        return start, end

    def eligible_at(self, when):
        """Timeline gate. `when` is the FILE'S OWN capture datetime — the
        caller reads it from EXIF, never off the path. No date at all is not
        eligible: an ungated match on an undated file is a guess."""
        if when is None:
            return False
        start, end = self.active_bounds()
        if start is None and end is None:
            return True                     # no declared timeline, nothing to gate on
        tol = timedelta(days=float(self.threshold("timeline_tolerance_days")))
        if start is not None and when < start - tol:
            return False
        if end is not None and when > end + tol:
            return False
        return True

    def forms_own_folder(self):
        """The naming carve-out's only question (N-4): does this subject get
        its own output folder?

        DERIVED, not a required field. A subject forms its own folder once it
        has a confirmed `name` AND a declared `active` start — under N-10a
        that is exactly the recurring-subject / D9 class, where the name
        replaces the routing class word. An unnamed draft subject may group
        files but never claims a folder (V2-6: drafts, never names), and an
        owner who does not want one subject foldered sets `forms_folder`
        false. A stored default either way would be an invention: `false`
        makes the carve-out inert on every real pack, `true` decides a naming
        policy nobody signed."""
        stored = self.record.get("forms_folder")
        if stored is not None:
            return bool(stored)
        start, _end = self.active_bounds()
        return bool(self.name) and start is not None


# --------------------------------------------------------------- registry ---

class Registry:
    """The pack's `photo-subjects/` store. An empty one is legal, common, and
    the state every benchmark run starts in — it answers every question with
    nothing rather than with a proxy."""

    def __init__(self, directory=None, data=None, source=None):
        self.dir = Path(directory) if directory else None
        self.data = data if data is not None else {"version": 1, "subjects": []}
        self.defaults = {**DEFAULT_THRESHOLDS, **(self.data.get("defaults") or {})}
        self.source = source
        self.subjects = [Subject(r, self.defaults)
                         for r in self.data.setdefault("subjects", [])]
        self._vectors = {}
        self._draft_vectors = {}
        self._identity_vectors = {}
        # vec_ref -> vector, written at save(). Held apart from the read cache
        # so a load-and-score run never writes anything back.
        self._identity_pending = {}
        self.audit_records = []

    def __bool__(self):
        return bool(self.subjects)

    def __len__(self):
        return len(self.subjects)

    # -- identity ----------------------------------------------------------

    @property
    def embedding_identity(self):
        return self.data.get("embedding_identity")

    @property
    def identity_embedding(self):
        """The identity space's own model identity. Deliberately NOT the same
        field as `embedding_identity` above, which names the CLIP model: the
        two stores are rebuilt independently, and one field would make a CLIP
        re-embed look like an identity-model swap and vice versa."""
        return self.data.get("identity_embedding")

    def assert_identity_space(self, space):
        """The identity store's own version of `assert_identity`. Same
        refusal, same reason, separate field.

        ⛔ Both sides are PROJECTED onto the identity-defining keys first. A
        pack seeded before that projection existed stored the index meta whole,
        timestamps included, so a raw dict comparison found every freshly built
        index different from every pack and refused — which is the one case
        this guard must NOT fire on, and the reason a mature pack could never
        reach the identity space. Projecting here rather than only at the write
        site keeps those packs working with no migration.

        The refusal names the fields that actually differ. The old message
        printed model and detector only, so a mismatch in any other field
        rendered as two identical strings and told the operator nothing."""
        mine = self.identity_embedding
        if not mine or not space:
            return
        keys = tuple(photo_identity.SPACE_KEYS)
        ours = photo_embed.space_view(mine, keys)
        theirs = photo_embed.space_view(space, keys)
        if ours == theirs:
            return
        self.refuse_other_backend(ours, theirs)
        differing = ", ".join(
            f"{k}: {ours[k]!r} vs {theirs[k]!r}" for k in keys
            if ours[k] != theirs[k])
        raise ValueError(
            f"the identity vectors at {self.dir} were built under a different "
            f"pipeline than this index ({differing}). Crops from two detectors "
            "embedded by two models are not comparable — rebuild the identity "
            "index with one pipeline (photo_identity.py --force).")

    def refuse_other_backend(self, ours, theirs):
        """A pack whose remembered animals were learned from one kind of
        preview, met by a run making the other kind. Said to the OWNER: there
        is no way yet to re-learn a pack's animals from new previews, so the
        switch is the only way to keep using this pack. -> None when the
        backends agree (the caller then reports the other difference)."""
        key = photo_embed.PREVIEW_KEY
        if ours.get(key) == theirs.get(key):
            return
        raise ValueError(
            f"The animals remembered in {self.dir} were learned from "
            f"{ours[key]} previews, but this run makes {theirs[key]} previews. "
            "The two give slightly different pictures, so comparing them could "
            "name the wrong animal, and this run stops instead. There is no way "
            "yet to re-learn a pack's animals from the new previews. To keep "
            f"using this pack, run with {photo_embed.BACKEND_ENV}={ours[key]} "
            "(and build this work dir's index the same way).")

    def assert_identity(self, identity):
        """Exemplars from another CLIP are not comparable to this batch's
        vectors, and the failure would be silent — every file would just get a
        slightly wrong score. Same refusal photo_recurrence makes between two
        indexes."""
        mine = self.embedding_identity
        if not mine or not identity:
            return
        from photo_recurrence import META_IDENTITY
        ours = photo_embed.space_view(mine, META_IDENTITY)
        theirs = photo_embed.space_view(identity, META_IDENTITY)
        if ours == theirs:
            return
        self.refuse_other_backend(ours, theirs)
        raise ValueError(
            f"the subject registry at {self.dir} was built under {mine} but this "
            f"index is {identity}. Vectors from two models are not comparable — "
            "re-embed with one model, or re-seed the registry under it.")

    # -- vectors -----------------------------------------------------------

    def vectors_path(self, subject_id):
        return (self.dir / VECTORS_DIRNAME / f"{subject_id}.npy") if self.dir else None

    def vectors_for(self, subject_id):
        """-> (N, D) array, or None when the subject has no exemplars.

        A row count that disagrees with `exemplars[]` means the two halves of
        one record are out of step, which would silently score a subject
        against another subject's vectors. That is a hard failure."""
        import numpy as np

        if subject_id in self._vectors:
            return self._vectors[subject_id]
        # LITERAL — this id's own rows. Resolving would count the WINNER's
        # exemplars against the tombstone's `.npy`, which the fold deleted, and
        # raise "lists N exemplar(s) but <path> is missing" about a record that
        # is correct to hold none.
        subject = self.get_literal(subject_id)
        want = len(subject.exemplars) if subject else 0
        path = self.vectors_path(subject_id)
        if not want:
            self._vectors[subject_id] = None
            return None
        if path is None or not path.exists():
            raise ValueError(f"{subject_id} lists {want} exemplar(s) but {path} "
                             "is missing")
        arr = np.load(path).astype(np.float32)
        if arr.shape[0] != want:
            raise ValueError(f"{path} holds {arr.shape[0]} vectors but "
                             f"{subject_id} lists {want} exemplars — the record "
                             "and its vectors are out of step")
        self._vectors[subject_id] = arr
        return arr

    # -- identity vectors (VS-3b) ------------------------------------------

    def identity_vectors_path(self, subject_id):
        return ((self.dir / IDENTITY_VECTORS_DIRNAME / f"{subject_id}.npz")
                if self.dir else None)

    def identity_vectors_for(self, subject_id):
        """-> (M, D) array of this subject's IDENTITY exemplars, or None.

        M is at most the number of CLIP exemplars and is often fewer: an
        exemplar whose frame held no detected animal contributes nothing here.

        ⛔ A missing file is None, never an error — the opposite of
        `vectors_for`, and the asymmetry is deliberate. There, a missing
        `.npy` means a record and its evidence are out of step, which is
        corruption. Here it means the pack predates this stage, or the
        identity index has not been built for this owner yet. Both are
        ordinary, and both must degrade to "score in the CLIP space" rather
        than take the run down.
        """
        import numpy as np

        if subject_id in self._identity_vectors:
            return self._identity_vectors[subject_id]
        subject = self.get_literal(subject_id)
        path = self.identity_vectors_path(subject_id)
        stored = {}
        if path is not None and path.exists():
            with np.load(path) as store:
                stored = {k: store[k] for k in store.files}
        # Vectors attached this session outrank the file, so a promote-then-
        # score run inside one process sees what it just wrote.
        stored.update(self._identity_pending.get(subject_id, {}))
        refs = [e.get("vec_ref") for e in subject.exemplars] if subject else []
        rows = [stored[r] for r in refs if r in stored]
        result = np.stack(rows).astype(np.float32) if rows else None
        self._identity_vectors[subject_id] = result
        return result

    def set_identity_vector(self, subject_id, vec_ref, vector):
        """Attach one identity vector to one already-promoted exemplar.

        Keyed by `vec_ref`, so it survives the exemplar cap dropping rows
        around it: `save()` writes only the refs the record still lists, which
        makes a dropped exemplar's identity vector disappear with it instead of
        going on scoring from a file nobody reads."""
        import numpy as np

        if vector is None:
            return False
        vec = np.asarray(vector, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vec))
        if norm < 0.5:
            return False                    # a zero row is "no subject in frame"
        pending = self._identity_pending.setdefault(subject_id, {})
        pending[vec_ref] = vec / norm
        self._identity_vectors.pop(subject_id, None)
        return True

    @property
    def identity_recognisers(self):
        """`recognisers` that also hold identity exemplars — the subjects the
        identity space can actually speak about. Never a different STATUS test
        from `recognisers`: a withdrawn confirmation must stop attributing
        files in both spaces at once, and reading the status twice is how the
        two would drift apart."""
        return [s for s in self.recognisers
                if self.identity_vectors_for(s.subject_id) is not None]

    @property
    def identity_silent_recognisers(self):
        """The exact complement: `recognisers` the identity space CANNOT
        speak about, and the omission nothing used to say out loud.

        A subject lands here when the owner confirmed it and not one of its
        exemplar frames left a usable identity vector — a frame with no
        detected animal is `photo_identity`'s `no-subject` and carries a zero
        row, which `set_identity_vector()` refuses rather than let it score
        0.0 against everything. The confirmation stands, the CLIP bank stands,
        and the subject then drops out of `identity_recognisers` at MATCH
        time with nobody told. Measured on real packs: two confirmed subjects
        recognising nothing in the identity space, and no line anywhere saying
        so — `attach_exemplars()` speaks at PROMOTE time only.

        ⚠️ A REPORT, never a gate. The CLIP fallback is the design, and this
        list is not evidence of a defect on its own: in a pack that never ran
        the identity stage EVERY recogniser is silent, which is ordinary. The
        reader needs `identity_embedding` beside the list to tell the two
        apart, and even that splits at PACK granularity only — nothing on an
        exemplar record says its identity vector was refused (the reason is
        written to the memorize audit log and nowhere else).

        ⛔ Never its own status test. Both lists are built from `recognisers`
        for the reason stated above: a withdrawn confirmation must leave both
        at once, and a second status test is how they would drift apart."""
        return [s for s in self.recognisers
                if self.identity_vectors_for(s.subject_id) is None]

    # -- lookup ------------------------------------------------------------

    def get_literal(self, subject_id):
        """The record filed under this id, whatever state it is in. No alias
        following, ever.

        ⭐ **This is what a caller wants whenever it fetched a record in order
        to BRANCH ON ITS STATUS or to MUTATE IT** — which is most of them.
        `rename("<tombstone>", …)` must refuse the tombstone, not rename the
        winner; `unconfirm("<tombstone>")` must refuse, not withdraw the
        winner's confirmation. Following an alias there does not fail loudly:
        it succeeds on the wrong subject."""
        return next((s for s in self.subjects if s.subject_id == subject_id), None)

    def resolve_merged(self, subject_id):
        """-> the live record this id ends at, following `merged_into`.

        SNS-14's alias following, in one place. An id that names no record, or
        one that is not a tombstone, comes back as `get_literal()` gave it.

        Two terminal cases, both stated rather than left to the loop:

          * **a tombstone with no `merged_into`** (only reachable by hand
            editing) returns the TOMBSTONE ITSELF. Returning `None` would make
            every caller say "no such subject" about a record that plainly
            exists, and the tombstone is not `human-confirmed`, so every status
            gate downstream still refuses it — the failure stays visible and
            stays safe;
          * **a cycle, or a chain past `MERGE_FOLLOW_LIMIT`, RAISES.** Same
            posture `vectors_for()` takes on a record that disagrees with its
            `.npy`: this is a corrupt pack, and a silent answer would be a name
            resolved to whichever record the walk happened to stop on. The
            engine cannot write either shape — `fold_subjects()` re-points
            every tombstone at the new winner and refuses to fold a subject
            into itself."""
        subject = self.get_literal(subject_id)
        seen = [subject_id]
        while subject is not None and subject.status == STATUS_MERGED_INTO:
            nxt = subject.record.get("merged_into")
            if not nxt:
                return subject
            if nxt in seen or len(seen) > MERGE_FOLLOW_LIMIT:
                raise ValueError(
                    f"the merge chain from {subject_id} does not end: "
                    + " -> ".join(seen + [nxt])
                    + ". A tombstone points at a tombstone, which this engine "
                    "never writes — `fold_subjects()` re-points every alias at "
                    "the new winner. Repair `merged_into` in subjects.json by "
                    "hand; nothing here can choose which end of a loop is the "
                    "subject.")
            seen.append(nxt)
            subject = self.get_literal(nxt)
        return subject

    def get(self, subject_id):
        """The subject this id MEANS, with `merged_into` followed (SNS-14).

        ⚠️ **Resolving is the default because reading is the common case.**
        `photo_plan.visual_columns()` holds ids off see-labels written before
        the fold and has to print the winner's name; `folder_for()` holds ids
        off a folder record and has to key on the winner. Neither may need a
        change of its own — that is exactly what SNS-14 asks alias following in
        `get()` to buy.

        ⛔ **Every caller that branches on status or writes to the record it
        gets back must use `get_literal()` instead**, and each one in this repo
        says which it wants and why at the call site."""
        return self.resolve_merged(subject_id)

    def next_subject_id(self):
        used = [int(s.subject_id.split("-")[1]) for s in self.subjects
                if s.subject_id and SUBJECT_ID_PATTERN.match(s.subject_id)]
        return f"subj-{(max(used) + 1 if used else 1):04d}"

    def create_subject(self, name=None, who=None, kind=None, active=None,
                       origin=None, subject_id=None, status=None):
        """A subject exists before it has a name — that is the whole point of
        N-6's rename-after. `origin` carries the recurrence-census candidate it
        was drafted from, so a tree sorted before the checkpoint still
        resolves."""
        subject_id = subject_id or self.next_subject_id()
        # LITERAL — id uniqueness is about the FILE, not about meaning. A
        # tombstone still occupies its id and must not be minted over.
        if self.get_literal(subject_id):
            raise ValueError(f"{subject_id} already exists")
        if not SUBJECT_ID_PATTERN.match(subject_id):
            raise ValueError(f"subject id must look like subj-0001: {subject_id!r}")
        record = {"subject_id": subject_id, "name": name, "who": who, "kind": kind,
                  "active": list(active) if active else [None, None],
                  "forms_folder": None, "origin": origin or {},
                  "status": status or (STATUS_CONFIRMED if (name and who)
                                       else STATUS_DRAFT),
                  "exemplars": []}
        self.data["subjects"].append(record)
        subject = Subject(record, self.defaults)
        self.subjects.append(subject)
        return subject

    # -- new-subject discovery (VS-4) --------------------------------------

    @property
    def drafts(self):
        return [s for s in self.subjects if s.is_draft]

    def draft_vectors_path(self, subject_id):
        return ((self.dir / DRAFT_VECTORS_DIRNAME / f"{subject_id}.npy")
                if self.dir else None)

    def draft_centroid(self, subject_id):
        """A draft's identity vector. NOT an exemplar and never used by
        `match()` — the memorize rule owns that store. This one exists so the
        same unnamed animal in batch 8 is recognised as the batch-1 draft, and
        for nothing else."""
        import numpy as np

        if subject_id in self._draft_vectors:
            return self._draft_vectors[subject_id]
        path = self.draft_vectors_path(subject_id)
        arr = (np.load(path).astype(np.float32).reshape(-1)
               if path is not None and path.exists() else None)
        self._draft_vectors[subject_id] = arr
        return arr

    def confirmed_match(self, vec, kind=None, identity_vec=None):
        """-> (Subject, score) when this cluster is a subject the owner has
        already confirmed, else None. F14's suppression test.

        Scored against the confirmed subject's EXEMPLARS — the vectors a human
        yes put in the store — not against a draft centroid, because the
        question being suppressed was answered about those files. A subject
        with no exemplars cannot suppress anything: that is the state F14
        describes, and it is why `confirm` now has to attach them.

        `vectors_for()` raises when a record and its `.npy` are out of step,
        and that exception is deliberately NOT caught here. A confirmed
        subject whose vectors are corrupt would otherwise stop suppressing in
        silence, which is F14 coming back with no way to notice.

        ⚠️ There is deliberately NO timeline gate here, though `match()` has
        one. `active` is set from what has been seen and never widens after a
        confirm, so a subject photographed outside its range would fail the
        gate — and a gated suppression would ask its naming question again,
        which is the loop this closes. The only answer available would mint a
        SECOND confirmed id carrying the same name, which is worse than the
        cost of not gating: files outside the range are suppressed (no
        question) but not matched (no name), so they stay unnamed rather than
        being named wrongly. Widening `active` on a sighting is not the way
        out either — that is a fact changed on geometry.
        """
        import numpy as np

        # VS-3b: when the caller has an identity vector for this cluster and
        # any confirmed subject holds identity exemplars, the suppression is
        # decided in the identity space, on the same floor-and-margin shape
        # `_verdict_identity` uses. `confirmed_suppress_tau` stays exactly as
        # it is for the CLIP fallback — a second meaning on one number is the
        # coupling this module has refused four times already.
        if identity_vec is not None:
            iv = np.asarray(identity_vec, dtype=np.float32).reshape(-1)
            if float(np.linalg.norm(iv)) >= 0.5:
                hit = self._confirmed_match_identity(iv / float(np.linalg.norm(iv)),
                                                     kind=kind)
                if hit is not None:
                    return hit
                if self.identity_recognisers:
                    # The identity space HAD an opinion and it was "no". Falling
                    # through to CLIP here would let the weaker space overturn
                    # the stronger one, which is the whole reason for the change.
                    return None

        tau = float(self.defaults.get("confirmed_suppress_tau",
                                      DEFAULT_THRESHOLDS["confirmed_suppress_tau"]))
        scored = []
        for subject in self.subjects:
            if subject.status != STATUS_CONFIRMED or not subject.exemplars:
                continue
            if kind and subject.kind and subject.kind != kind:
                # Same species guard as the draft dedupe below: two different
                # kinds are two subjects however close their vectors sit.
                continue
            V = self.vectors_for(subject.subject_id)
            if V is None or not len(V) or V.shape[1] != vec.shape[0]:
                continue
            scored.append((float(np.max(V @ vec)), subject))
        scored.sort(key=lambda t: (-t[0], t[1].subject_id))
        if scored and scored[0][0] >= tau:
            return scored[0][1], scored[0][0]
        return None

    def _confirmed_match_identity(self, iv, kind=None):
        """F14's suppression, decided in the identity space. -> (Subject,
        score) or None.

        Same floor and margin as `_verdict_identity`, and deliberately the
        same NUMBERS rather than a third pair: attributing a file to a subject
        and declining to ask about it are different decisions, but they are
        the same measurement, and the 20260821 trial calibrated one ranking,
        not two. If they ever need to diverge they diverge as their own keys,
        the way `confirmed_suppress_tau` split from `accept`."""
        import numpy as np

        scored = []
        for subject in self.subjects:
            if subject.status != STATUS_CONFIRMED or not subject.exemplars:
                continue
            if kind and subject.kind and subject.kind != kind:
                continue
            V = self.identity_vectors_for(subject.subject_id)
            if V is None or not len(V) or V.shape[1] != iv.shape[0]:
                continue
            scored.append((float(np.max(V @ iv)), subject))
        if not scored:
            return None
        scored.sort(key=lambda t: (-t[0], t[1].subject_id))
        score, subject = scored[0]
        floor = subject.threshold("identity_floor")
        margin = subject.threshold("identity_margin")
        lead = score - scored[1][0] if len(scored) > 1 else score
        if score >= floor and lead >= margin:
            return subject, score
        return None

    def rejected_match(self, vec, kind=None):
        """-> (Subject, score) when this cluster is one the owner REJECTED,
        else None. OA-14's half of the suppression story.

        Scored against the rejected subject's retained DRAFT CENTROID, because
        that is the only vector a rejection leaves behind: a rejected record
        holds no name and gains no exemplars, so `confirmed_match()` cannot see
        it and `drafts` does not list it. Without this the rejected subject was
        invisible to BOTH suppression layers and came back next dump under a
        fresh `subject_id` that no layer had ever heard of — the defect OA-14
        names, and the reason `skip:` could not honestly promise what
        ONB-13a:255 promised.

        ⚠️ A retained centroid SUPPRESSES A QUESTION and never attributes a
        file. `match()` reads `recognisers`, which is `human-confirmed` plus
        exemplars, and a rejected record is neither — so nothing here can put a
        name on anything. That is what keeps V2-5a intact: the owner's yes is
        being honoured, not extended.

        A rejected record whose centroid is gone (a pack written before this,
        or one hand-edited) simply does not suppress. Computing one from the
        evidence would be geometry inventing the key the owner's decision was
        taken on."""
        import numpy as np

        tau = float(self.defaults.get("rejected_suppress_tau",
                                      DEFAULT_THRESHOLDS["rejected_suppress_tau"]))
        scored = []
        for subject in self.subjects:
            if subject.status != STATUS_REJECTED:
                continue
            if kind and subject.kind and subject.kind != kind:
                # Same species guard the other two comparisons use: two kinds
                # are two subjects however close their vectors sit.
                continue
            other = self.draft_centroid(subject.subject_id)
            if other is None or other.shape != vec.shape:
                continue
            scored.append((float(other @ vec), subject))
        scored.sort(key=lambda t: (-t[0], t[1].subject_id))
        if scored and scored[0][0] >= tau:
            return scored[0][1], scored[0][0]
        return None

    def observe_draft_subject(self, centroid, kind=None, batch=None,
                              files=0, dates=None, evidence=None,
                              identity=None, seen_on=None,
                              identity_centroid=None, ask_away=False):
        """One unmatched visual cluster, offered to the draft store.

        -> (Subject, "new" | "reinforced" | "known" | "rejected"). This is the
        cross-batch dedupe
        (Memory-System DESIGN, *Learn while working*): a candidate re-observed
        in a later batch does NOT confirm anything — it bumps `obs_count` and
        re-tags `ai-reinforced`, so one subject spanning K batches is ONE
        draft and therefore one question.

        The stored centroid is the FIRST sighting's and is never updated. A
        running mean would let a draft walk across the similarity space one
        batch at a time and silently absorb a second subject; a subject whose
        appearance really did drift is the *Same or different* question type,
        which a human answers. Drift is not a merge the engine may make.

        F14: a cluster that already IS a confirmed subject (`confirmed_match`)
        is recorded against it and returns `known` — no third record, no
        second naming question. That path deliberately writes less than the
        draft path does: no `active`, no `contact_sheet`, no status change and
        no exemplar. Widening a confirmed subject's timeline would move the
        gate `match()` scores against, and a contact sheet is what a checkpoint
        shows a human — both would be facts changed on geometry alone, which
        is the one thing this module may never do.

        OA-14: a cluster that matches a REJECTED subject's retained draft
        centroid (`rejected_match`) is recorded against it and returns
        `rejected`, on the same write-less path. That is the other half of
        "never ask me about this again" — without it the rejected subject was
        in neither `drafts` nor `recognisers`, so the next dump opened a new
        record for it and asked again under an id the owner had never seen.
        ⚠️ The record it lands on attributes nothing: no name, no exemplar, no
        recogniser row.
        """
        import numpy as np

        self.assert_identity(identity)
        vec = np.asarray(centroid, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vec))
        if norm < 0.5:
            raise ValueError("a draft subject needs a usable centroid "
                             f"(norm {norm:.3f})")
        vec = vec / norm

        # VS-3b — the identity centroid decides the suppression when there is
        # one. The DRAFT DEDUPE below stays in the CLIP space deliberately and
        # is a separate question: `draft_dedupe_tau` groups sightings of a
        # subject nobody has named, where there is no bank of confirmed
        # evidence to score against and nothing was measured. Moving it on the
        # same commit would change what gets ASKED and what gets GROUPED at
        # once, and the two failures look identical from the outside.
        # Q8-a (owner ruling 20260924) — ASK, DON'T FILE. A cluster taken
        # beyond the home range of every home is never filed onto a confirmed
        # subject on geometry: it takes the draft path and so becomes a page
        # question. A PLACE gate, not a score (A19: the wrong band sits inside
        # the right one). A rejection still suppresses — that is a human's.
        known = None if ask_away else self.confirmed_match(
            vec, kind=kind, identity_vec=identity_centroid)
        suppressed_at = None
        if known is not None:
            subject, suppressed_at = known
            state = "known"
        else:
            tau = float(self.defaults.get(
                "draft_dedupe_tau", DEFAULT_THRESHOLDS["draft_dedupe_tau"]))
            scored = []
            for draft in self.drafts:
                other = self.draft_centroid(draft.subject_id)
                if other is None or other.shape != vec.shape:
                    continue
                if kind and draft.kind and draft.kind != kind:
                    # Two different species are two subjects however close their
                    # vectors sit. Merging them is the error that is silent.
                    continue
                scored.append((float(other @ vec), draft))
            scored.sort(key=lambda t: (-t[0], t[1].subject_id))

            rejected = self.rejected_match(vec, kind=kind)
            # ⭐ PRECEDENCE, and it is a decision rather than an ordering
            # accident. Confirmed first (above): a confirmation names files,
            # a rejection only declines to ask. Then a rejection suppresses
            # ONLY IF no live draft explains this cluster better — both sides
            # are first-sighting centroids in one space, so they compare on
            # one scale.
            #
            # ⛔ Not "rejection wins whenever it clears its bar": a cluster
            # sitting closer to a live draft than to the rejected one would be
            # absorbed by the rejection, and the question the owner never
            # answered would disappear. That is the SILENT error; the other
            # direction only re-asks visibly, which is the asymmetry every
            # suppression bar in this module is set on. A tie goes to the
            # rejection, because one side of it is a human decision.
            if rejected is not None and (not scored
                                         or scored[0][0] <= rejected[1]):
                subject, suppressed_at = rejected
                state = "rejected"
            elif scored and scored[0][0] >= tau:
                subject = scored[0][1]
                state = "reinforced"
                subject.record["status"] = STATUS_REINFORCED
            else:
                subject = self.create_subject(kind=kind,
                                              origin=dict(evidence or {}),
                                              status=STATUS_DRAFT)
                self._draft_vectors[subject.subject_id] = vec
                state = "new"
                subject.record["obs_count"] = 0
                subject.record["observed_in"] = []
                subject.record["evidence"] = []

        record = subject.record

        # A19: a suppression carries no timeline gate (see `confirmed_match`),
        # so it can land on a subject this file's own capture date sits far
        # outside — the state `match()` refuses by returning `none`. That is
        # still the decision this module takes, deliberately and unchanged.
        # What changes here is only that the record says which kind it was:
        # measured on one owner dump, 24 of 24 suppressions were outside the
        # subject's window, and nothing anywhere could tell them from a gated
        # match afterwards.
        # ⛔ MARKED, never dropped. 19 of those 24 were correct, and a rule
        # that discarded them to catch the other 5 would cost more than it saved
        # — which is also why this is not a threshold: the wrong ones sit inside
        # the right ones' score range, so no floor separates them.
        within = None
        if suppressed_at is not None:
            within = False
            for when in (dates or []):
                if not when:
                    continue
                try:
                    parsed = _bound(when)
                except ValueError:
                    # An unparseable date is not evidence of being in range.
                    continue
                if subject.eligible_at(parsed):
                    within = True
                    break

        if ask_away and state in ("new", "reinforced"):
            # Read by `sweep_absorb()`, which must not end the question.
            record["asked_away"] = True
        record["obs_count"] = int(record.get("obs_count", 0)) + 1
        if batch is not None and batch not in record.setdefault("observed_in", []):
            record["observed_in"].append(batch)
        record["files"] = int(record.get("files", 0)) + int(files)
        if within is False:
            # A19 item 2. The TOTALS above are untouched — they are what every
            # existing reader means by "files" — and these two say how much of
            # the total arrived ungated, so the share is separable rather than
            # inferred. Stored per record beside `files`, NOT aggregated: the
            # display-time sum lives in `display_files_ungated()`, on the same
            # basis and for the same reason `display_files` is read-time.
            record["obs_count_ungated"] = int(record.get("obs_count_ungated", 0)) + 1
            record["files_ungated"] = int(record.get("files_ungated", 0)) + int(files)
        if evidence:
            entry = dict(evidence)
            if state == "known" and entry.get("looks"):
                # Q8-b — a photo the owner took out does not come back as a
                # recognised sighting of the same subject.
                gone = self.not_this_refs(subject.subject_id)
                entry["looks"] = [l for l in entry["looks"]
                                  if l.get("vec_ref") not in gone]
            if ask_away:
                entry["asked_away"] = True
            if suppressed_at is not None:
                # The one number behind a suppression, written down where a
                # reviewer meets it. A decision taken on geometry with no human
                # in the room has to be legible afterwards.
                entry["suppressed_at"] = round(suppressed_at, 4)
                # A19. Written on BOTH branches rather than only on the bad
                # one: absence then means "a pack older than this", which is a
                # different thing from "gated", and a reader who cannot tell
                # those apart is the position this whole card is about.
                entry["within_timeline"] = within
            record.setdefault("evidence", []).append(entry)
        if state in ("new", "reinforced"):
            # ⚠️ The two SUPPRESSED states write less, and identically: no
            # `active`, no `contact_sheet`, no status change. Widening a
            # timeline moves the gate `match()` scores against and a contact
            # sheet is what a checkpoint shows a human — both are facts changed
            # on geometry alone. Written as a whitelist rather than as
            # `!= "known"`, which is what it said before OA-14 added the second
            # suppressed state: the negative form silently gave a rejected
            # record the draft treatment, which is how it would have grown a
            # contact sheet for a question nobody is going to ask.
            for when in sorted(d for d in (dates or []) if d):
                first, last = record.get("active") or [None, None]
                record["active"] = [min(first, when) if first else when,
                                    max(last, when) if last else when]
            if seen_on:
                shown = record.setdefault("contact_sheet", [])
                for item in seen_on:
                    if item not in shown:
                        shown.append(item)
        if identity and not self.data.get("embedding_identity"):
            self.data["embedding_identity"] = dict(identity)
        return subject, state

    def rename_refusal(self, subject_id):
        """-> (the one reason this rename may not happen, the audit gate that
        refused it), or (None, None).

        Split out of `rename()` for the reason `fold_refusal()` is split out of
        `fold_subjects()`: the confirm checkpoint's DRY RUN must refuse exactly
        what `--go` refuses, and `rename()` itself cannot be what a dry run
        asks. Its refusals `audit()`, `audit()` appends to disk at the decision
        point rather than at `save()`, and `memorize-audit.jsonl` sits inside
        `photo-subjects/` — which is one of `SNAPSHOT_PARTS`. A dry run that
        asked `rename()` whether it would refuse would move the pack snapshot
        it promised not to touch, and the confirm checkpoint's own determinism
        rule forbids exactly that.

        ⛔ The gate name travels back with the reason instead of being audited
        here. A refusal a dry run PREDICTED is not a decision anyone took; only
        the caller that was actually going to write knows which it is, and that
        caller is `rename()`.

        Five statuses, each refusing for its OWN reason and naming its own way
        on — a caller told *"revive it first"* learns something a generic
        refusal cannot tell them."""
        # LITERAL, and this is the regression alias following creates. Every
        # guard below reads a STATUS; on a resolving fetch `rename(<tombstone>,
        # …)` would sail past all five and rename the winner instead — no
        # refusal, wrong subject, and the audit log would name the id that was
        # not touched.
        subject = self.get_literal(subject_id)
        if subject is None:
            # ⛔ No gate, and therefore no audit line — the same as before this
            # was split out. There is no record to write a decision against,
            # and a refusal filed under an id the pack does not hold would be
            # the only line in the trail naming nothing.
            return f"no such subject: {subject_id}", None
        if subject.status == STATUS_MERGED_INTO:
            # SNS-14, the fifth guard on this door and the newest. The record
            # is an ALIAS: the name it would take is the winner's to hold, and
            # a name written here would render as a second confirmed identity
            # for the one animal the fold just made single — with no `draft:`
            # marker, because `merged-into` is outside `is_draft` like the
            # three statuses above it.
            winner = subject.record.get("merged_into") or "another subject"
            why = (f"{subject_id} was folded into {winner} and may not be "
                   "renamed — it is an alias kept so older folders and plan "
                   f"CSVs still resolve, not a subject. Rename {winner}, which "
                   "is where that name is actually held; every name this "
                   "record ever had is already in its `previous_names`.")
            return why, "merged-into"
        if subject.status == STATUS_SUPERSEDED:
            # `partition_subject()` refusing a NAMED parent only covers the
            # moment of the split. This is the other direction, and without it
            # the no-name rule is a mint-time check rather than an invariant:
            # `superseded` is outside both whitelists, so a name written here
            # makes `name and not is_draft` true and the plan prints a
            # confirmed `who` with no `draft:` marker — for a record whose
            # children hold the same looks.
            why = (f"{subject_id} was {STATUS_SUPERSEDED} by a split and may "
                   "not be renamed — a name on it renders as a confirmed "
                   "identity. Rename its children instead: "
                   f"{', '.join(subject.record.get('split_into') or []) or 'none'}")
            return why, "superseded"
        if subject.status == STATUS_REJECTED:
            # OA-16, the same door one status along, and the answer is the same
            # because the mechanism is: `rejected` is outside `is_draft`, so a
            # name written here prints as a confirmed `who` with no `draft:`
            # marker — for a subject the owner asked never to hear about again.
            # ⛔ Still named per status rather than written as "anything not
            # confirmed": each status refuses for its OWN reason and says it,
            # and a caller told "revive it first" learns something a generic
            # refusal cannot tell them.
            why = (f"{subject_id} is {STATUS_REJECTED} and may not be renamed "
                   "— a rejected record holds no name, because a name on it "
                   "renders as a confirmed identity. Revive it first "
                   "(`--revive`), which returns it to the question loop where "
                   "a name is answered for rather than typed onto it.")
            return why, "rejected"
        if subject.status == STATUS_ABSORBED:
            # The same door a third status along. An absorbed record is one
            # the sweep folded into a subject that already holds the name, so
            # a name written here would render a second confirmed identity for
            # the animal the owner named once — and it would do it with no
            # `draft:` marker, because `absorbed` is outside `is_draft` too.
            why = (f"{subject_id} was {STATUS_ABSORBED} into "
                   f"{subject.record.get('absorbed_by') or 'another subject'} "
                   "and may not be renamed — the name it would take is already "
                   "held by the subject that absorbed it. Rename that one, or "
                   "withdraw its confirmation, which releases this draft back "
                   "into the question loop.")
            return why, "absorbed"
        return None, None

    def rename(self, subject_id, new_name):
        """N-6: names arrive after folders exist, so renaming is normal. The
        old rendered name is kept so a pre-rename tree still resolves, and the
        KEY does not move — that is N-10a.

        The five status guards live in `rename_refusal()` and are read from
        there rather than repeated here: this is the only caller that WRITES,
        so it is the only one that audits."""
        why, gate = self.rename_refusal(subject_id)
        if why:
            if gate:
                self.audit({"subject_id": subject_id, "decision": "refused",
                            "gate": gate, "reason": why,
                            "at": datetime.now().strftime("%Y-%m-%d")})
            raise ValueError(why)
        subject = self.get_literal(subject_id)
        old = subject.name
        if old and old != new_name:
            previous = subject.record.setdefault("previous_names", [])
            if old not in previous:
                previous.append(old)
        subject.record["name"] = new_name
        return subject

    # -- the memorize rule -------------------------------------------------

    def add_exemplar(self, subject_id, vector, vec_ref, source, added=None,
                     confirmed_by=None, identity=None, evidence=None,
                     captured=None, identity_vector=None, identity_space=None,
                     identity_quality=None):
        """Promote one file to an exemplar. -> (added?, dropped vec_refs).

        Three independent gates, all at the point of writing, because a vector
        that reaches the file has already become evidence:

          1. the provenance must be a bare `viewed-image` (the anti-drift rule)
          2. the LOOK must be provable — `evidence` names the see-report that
             selected the file and the thumbnail the model opened, and
             `photo_evidence` re-derives every part of that from disk
          3. the SUBJECT must be `human-confirmed` — no exemplar is GAINED
             without a live yes standing behind the identity

        Gate 1 alone was the whole rule until VS-4, and it is a string
        comparison: a caller holding a `clip-matched:` file and the right
        spelling passed it. Gate 2 is what makes exit test 1 checkable.

        SNS-10 — `added` is the day this vector was PROMOTED; `captured` is the
        day the photograph was TAKEN, and they are different facts. The
        retention rule keeps a diverse set rather than a recent one precisely
        so a subject's whole life stays recognisable, and no reader can check
        that coverage against a promotion date. The caller passes the capture
        time it already holds (the see-report's own `time`), in full: a month
        is too coarse to argue about drift with.

        ⚠️ Absent means NULL, never a substitute. `added`, today's date or a
        file mtime would each read downstream as a real capture date, and a
        wrong one is worse than a missing one — a missing date declares the
        gap, a wrong one hides it. Packs written before this carry no
        `captured` at all, so every reader treats absent and null alike.

        Every attempt is written to the audit log first, refusals included."""
        import numpy as np

        provenance = normalize_provenance(confirmed_by)
        base = {"subject_id": subject_id, "vec_ref": vec_ref,
                "source": str(source), "claimed": confirmed_by,
                "evidence": _evidence_summary(evidence),
                "at": added or datetime.now().strftime("%Y-%m-%d"),
                "captured": captured or None}

        if not photo_evidence.is_view_confirmed(confirmed_by):
            why = (f"{subject_id}: refusing to memorize {vec_ref} with provenance "
                   f"{provenance or 'none'!r}. Only {MEMORIZE_PROVENANCE!r} may "
                   "become an exemplar — a CLIP match is the registry's own output, "
                   "and output that becomes its own evidence is how a registry "
                   "drifts on its own errors.")
            self.audit({**base, "decision": "refused", "gate": "provenance",
                        "reason": why})
            raise ValueError(why)

        problems = photo_evidence.evidence_problems(evidence, expect_path=source)
        if problems:
            why = (f"{subject_id}: refusing to memorize {vec_ref} — the look it "
                   "claims cannot be verified: " + "; ".join(problems))
            self.audit({**base, "decision": "refused", "gate": "evidence",
                        "reason": why})
            raise ValueError(why)

        # LITERAL — gate 3 below is a STATUS test, and the whole of it is that
        # nothing is gained where no yes stands. A resolving fetch would
        # promote the tombstone's look onto the WINNER: a subject that is
        # confirmed, so the gate would pass, on a vec_ref the caller attributed
        # to a different id.
        subject = self.get_literal(subject_id)
        if subject is None:
            why = f"no such subject: {subject_id}"
            self.audit({**base, "decision": "refused", "gate": "subject",
                        "reason": why})
            raise ValueError(why)
        if subject.status == STATUS_MERGED_INTO:
            # ⚠️ NOT a second gate — gate 3 below already refuses this record,
            # because the whitelist refuses everything that is not
            # `human-confirmed` and that is deliberately how it is written.
            # This branch only replaces the sentence, because "it is
            # merged-into, not human-confirmed" tells a caller nothing they can
            # act on and the winner's id does.
            why = (f"{subject_id}: refusing to memorize {vec_ref} — the subject "
                   f"was folded into "
                   f"{subject.record.get('merged_into') or 'another subject'} "
                   "and is an alias, not an identity. Promote onto the winner, "
                   "which is what the fold left holding this subject's "
                   "exemplars.")
            self.audit({**base, "decision": "refused", "gate": "merged-into",
                        "reason": why})
            raise ValueError(why)
        if subject.status != STATUS_CONFIRMED:
            # Gate 3 — NO EXEMPLAR IS GAINED WITHOUT A LIVE HUMAN YES.
            #
            # ⚠️ Not "a draft holds no exemplars": since 2026-08-16 a WITHDRAWN
            # subject deliberately keeps the ones it had, frozen, so that
            # re-confirming costs nothing. This gate is what keeps them frozen
            # — retained evidence may sit there, and nothing may be added to it
            # while no yes stands behind the identity.
            #
            # The caller cannot enforce this. The see stage marks a
            # draft-attributed file `draft:viewed-image:` when the LABEL is
            # written, and gate 1 refuses it; a withdrawal happens afterwards,
            # so those labels say a bare `viewed-image:` truthfully and were
            # earned under a confirmation that no longer exists. Same move gate
            # 2 made at VS-4: a rule the caller applies is a rule some caller
            # does not.
            #
            # ⚠️ The test is a WHITELIST — `human-confirmed`, and nothing else
            # — where it used to name statuses one at a time (`is_draft`, then
            # `superseded` at commit 95df8eb, with `rejected` left open). The
            # enumerating form existed only because `rejected` was an open
            # question; step 3 closes it, and the whitelist is what stops a
            # sixth status walking through this gate the day someone adds one.
            #
            # Both extra statuses reach here by the same path 95df8eb measured:
            # `photo_see.memorize_batch()` promotes on whatever `subject_id` a
            # decision names, and the labels on disk say a bare `viewed-image:`
            # truthfully — earned before the split, or before the rejection.
            why = (f"{subject_id}: refusing to memorize {vec_ref} — the subject "
                   f"is {subject.status}, not {STATUS_CONFIRMED}. An exemplar "
                   "is gained only under a live human yes about this identity, "
                   "and there is none standing here. Any evidence already on "
                   "the record stays, frozen and attributing nothing.")
            self.audit({**base, "decision": "refused", "gate": "unconfirmed",
                        "reason": why})
            raise ValueError(why)
        if vec_ref in self.not_this_refs(subject_id):
            # Q8-b — the owner took this photo out of this subject's memory.
            # Only their own later pick lifts it (`lift_not_this()`).
            why = (f"{subject_id}: refusing to memorize {vec_ref} — the owner "
                   "took this photo out of this subject's memory with `not`; "
                   "only their own pick of it for this subject brings it back.")
            self.audit({**base, "decision": "refused", "gate": "not-this",
                        "reason": why})
            raise ValueError(why)
        if any(e.get("vec_ref") == vec_ref for e in subject.exemplars):
            self.audit({**base, "decision": "already-held",
                        "reason": "this vec_ref is already an exemplar"})
            return False, []
        self.assert_identity(identity)

        vec = np.asarray(vector, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vec))
        if norm < 0.5:
            why = f"{vec_ref} has no usable vector (norm {norm:.3f})"
            self.audit({**base, "decision": "refused", "gate": "vector",
                        "reason": why})
            raise ValueError(why)
        vec = vec / norm

        current = self.vectors_for(subject_id)
        stack = (np.vstack([current, vec[None, :]]) if current is not None
                 and len(current) else vec[None, :])
        subject.exemplars.append({
            "vec_ref": vec_ref, "source": str(source),
            "added": base["at"], "captured": captured or None,
            "confirmed_by": MEMORIZE_PROVENANCE,
            "evidence": _evidence_summary(evidence)})
        self._vectors[subject_id] = stack
        dropped = self._enforce_cap(subject)
        # The first exemplar fixes which model this store speaks. Every later
        # comparison is refused against another one (assert_identity).
        if identity and not self.data.get("embedding_identity"):
            self.data["embedding_identity"] = dict(identity)

        # VS-3b — the identity vector rides along, and is allowed to be
        # refused on its own without failing the promotion.
        #
        # ⭐ The two stores answer different questions and therefore have
        # different admission rules. The CLIP exemplar answers "is this the
        # right animal", which the owner just said yes to; the identity
        # exemplar answers "WHICH one is this", and a frame can be a true
        # picture of a subject while carrying no answer to that at all. In the
        # 20260821 trial three of one subject's seven confirmed frames were
        # vet-visit close-ups of a paw being held — every one a real photograph
        # of that animal, none of them evidence of anything. Dropping them took
        # nearest-neighbour accuracy from 16/18 to 15/15.
        #
        # ⛔ So a refusal here NEVER refuses the exemplar. The owner's yes
        # stands, the file keeps its name and its folder; it simply does not
        # join the bank the matcher scores against. Overturning a human answer
        # because a detector disliked the framing would be the engine deciding
        # a fact on geometry.
        identity_note = None
        if identity_vector is not None:
            ok, why = (True, "ok") if identity_quality is None else identity_quality
            if ok and self.set_identity_vector(subject_id, vec_ref, identity_vector):
                if identity_space and not self.data.get("identity_embedding"):
                    # Projected, so a pack never stores a build timestamp as
                    # though it were part of the space's identity.
                    self.data["identity_embedding"] = photo_identity.space_of(
                        dict(identity_space))
                identity_note = "attached"
            else:
                identity_note = f"not usable as identity evidence: {why}"

        self.audit({**base, "decision": "memorized", "gate": None,
                    "dropped_for_cap": dropped,
                    "identity_vector": identity_note,
                    "exemplars_after": len(subject.exemplars)})
        return True, dropped

    # -- the audit log -----------------------------------------------------

    @property
    def audit_path(self):
        return (self.dir / AUDIT_NAME) if self.dir else None

    def audit(self, record):
        """Append one decision to `photo-subjects/memorize-audit.jsonl`.

        Kept in memory as well, so an in-memory registry (no pack directory)
        is still auditable in a test, and appended to disk IMMEDIATELY rather
        than at save(): the run that crashes half way through is exactly the
        run whose trail matters."""
        self.audit_records.append(record)
        path = self.audit_path
        if path is None:
            return record
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def audit_trail(self):
        """-> every decision this pack has ever recorded, disk first.

        This is the artifact exit test 1 asks for: `memorized` lines each name
        the see-report, batch and thumbnail that confirmed them, and `refused`
        lines name the gate that stopped them."""
        path = self.audit_path
        if path is None or not path.is_file():
            return list(self.audit_records)
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def _enforce_cap(self, subject):
        """Diversity-kept: over the cap, drop the most REDUNDANT exemplar — the
        one whose nearest neighbour in the set is closest — not the oldest.
        Ties by vec_ref so a re-run drops the same one."""
        import numpy as np

        cap = int(subject.threshold("exemplar_cap"))
        dropped = []
        while len(subject.exemplars) > cap:
            V = self._vectors[subject.subject_id]
            sims = V @ V.T
            np.fill_diagonal(sims, -1.0)
            nearest = sims.max(axis=1)
            worst = min(range(len(subject.exemplars)),
                        key=lambda i: (-float(nearest[i]),
                                       subject.exemplars[i]["vec_ref"]))
            dropped.append(subject.exemplars[worst]["vec_ref"])
            del subject.exemplars[worst]
            self._vectors[subject.subject_id] = np.delete(V, worst, axis=0)
        return dropped

    def prune(self, subject_ids=None, drop_refs=()):
        """`review --prune`: apply the cap, plus any exemplar the operator
        named. -> {subject_id: [dropped vec_refs]}."""
        import numpy as np

        out = {}
        for subject in self.subjects:
            if subject_ids and subject.subject_id not in subject_ids:
                continue
            gone = self.drop_exemplars(subject.subject_id, drop_refs)
            if subject.exemplars:
                self.vectors_for(subject.subject_id)
                gone += self._enforce_cap(subject)
            if gone:
                out[subject.subject_id] = gone
        return out

    def unconfirm(self, subject_id, by=None, reason=None):
        """Withdraw a confirmation: the subject becomes a draft and is asked
        about again. -> a dict describing what was withdrawn.

        Pattern 6's missing half (SNS-5). `prune()` removes exemplars and
        `rename()` moves a name, but nothing reverses a STATUS, so a subject
        named wrongly was unreachable: `is_draft` keeps a confirmed record out
        of the question loop, and the only correction path this system has is
        the next question. The mistake disappeared exactly when it was worst.

        Four things happen, and the second is a decision rather than a
        mechanism:

          1. **the status goes back to `ai-drafted`**, which is all askability
             costs — `is_draft` is a status whitelist. The name is not thrown
             away but moved into `previous_names`, so `rename_ledger()` still
             resolves every folder already written under it (N-6/N-10a): the
             owner withdrew an identity, not the history of what was sorted.
          2. **the exemplars promoted under that yes are KEPT**, and stop
             attributing anything the moment the status moves — ✅ the owner's
             decision, 2026-08-16. See below.
          3. **the draft centroid is left alone.** Nothing ever deleted it
             (`save()` only writes `draft-vectors/`), so a subject confirmed
             from a draft can be re-recognised across batches immediately. A
             subject with no centroid on disk is reported in the result rather
             than given one: a centroid computed here would be geometry
             inventing a dedupe key nobody observed.
          4. **`REOPENED_FLAG` is set**, which is what carries the withdrawal
             into the WORK-DIR dedupe layer — step 4's half of this verb. The
             pack-log layer is `photo_memory.record_unconfirm()`'s; without
             both, the subject is withdrawn in one place and invisible in the
             other.

        ✅ **Why the exemplars stay — the owner's decision, 2026-08-16.** Because
        RE-CONFIRMING MUST STAY CHEAP. `photo_memory.attach_exemplars()`
        re-derives every vector from the dump's own `embed/` index, so a
        removal is one-way the moment that index is cleaned away: the owner
        who withdrew a name in March could not get the recognition back in
        June, and a correction path that costs the evidence is one nobody
        uses. The evidence is FROZEN, not live — it attributes nothing while
        the status is a draft (`recognisers`), and it grows no further,
        because `add_exemplar()` refuses a subject that is not confirmed.

        ⚠️ So the safety of this verb rests entirely on the STATUS test, in
        two places, and neither is optional: `recognisers` (nothing is
        attributed) and `add_exemplar()`'s third gate (nothing is gained).
        Anyone who "optimises" either back to an exemplar test hands a
        withdrawn identity its files back, silently — the vectors are real
        and the scores are good."""
        # LITERAL, for `rename()`'s reason exactly: every refusal below reads a
        # status, and a resolving fetch would withdraw the WINNER's
        # confirmation when the owner named a tombstone — releasing the
        # winner's absorbed drafts with it, from an id that holds nothing.
        subject = self.get_literal(subject_id)
        if subject is None:
            raise ValueError(f"no such subject: {subject_id}")
        base = {"subject_id": subject_id, "decision": "un-confirmed",
                "by": by, "reason": reason,
                "at": datetime.now().strftime("%Y-%m-%d")}
        if subject.is_draft:
            why = (f"{subject_id} is already {subject.status} — there is no "
                   "confirmation to withdraw")
            self.audit({**base, "decision": "refused", "gate": "status",
                        "reason": why})
            raise ValueError(why)
        if subject.status == STATUS_MERGED_INTO:
            # SNS-14. Named rather than left to fall through the body, which
            # would flip an ALIAS to `ai-drafted` and ask the owner about a
            # record whose looks the winner now holds — the same shape the
            # `superseded` refusal below stops one status along. ⛔ And this is
            # not the way to reverse a fold: there is no un-fold verb, because
            # the exemplars concatenated and the cap has since evicted for
            # redundancy across both sets.
            winner = subject.record.get("merged_into") or "another subject"
            why = (f"{subject_id} was folded into {winner} — it holds no "
                   "confirmation of its own to withdraw, and returning it to "
                   "the question loop would ask about looks the winner now "
                   f"carries. Withdraw {winner} instead. ⚠️ That withdraws the "
                   "whole folded subject, including everything this id "
                   "contributed: the fold has no reverse.")
            self.audit({**base, "decision": "refused", "gate": "merged-into",
                        "reason": why})
            raise ValueError(why)
        if subject.status == STATUS_SUPERSEDED:
            # ⚠️ Named, not folded into the test above, because `superseded` is
            # not a draft and would otherwise fall through to the withdrawal
            # body: status -> `ai-drafted` puts the parent back in the question
            # loop while its children hold the same looks, so the owner is
            # asked twice about frames they already partitioned. There is no
            # un-split verb in SNS-1b and this is not one. ⛔ Written as its own
            # test rather than as "anything not confirmed": `rejected` reaches
            # here too and gets its own answer below, naming its own verb.
            why = (f"{subject_id} was {STATUS_SUPERSEDED} by a split — it holds "
                   "no confirmation to withdraw, and returning it to the "
                   "question loop would ask about frames its children already "
                   f"carry. Its children are "
                   f"{', '.join(subject.record.get('split_into') or []) or 'none'}")
            self.audit({**base, "decision": "refused", "gate": "superseded",
                        "reason": why})
            raise ValueError(why)
        if subject.status == STATUS_REJECTED:
            # A rejection is not a confirmation, so there is nothing here to
            # withdraw — and the body below would write the wrong history onto
            # it (`unconfirmed`, a withdrawn name it never held). The owner's
            # word was "never ask me about this again"; taking that back is
            # `revive()`, which says so in the audit log and in the memory log.
            why = (f"{subject_id} is {STATUS_REJECTED} — there is no "
                   "confirmation to withdraw. `revive()` is what takes a "
                   "rejection back and returns the subject to the question "
                   "loop.")
            self.audit({**base, "decision": "refused", "gate": "rejected",
                        "reason": why})
            raise ValueError(why)

        retained = [e.get("vec_ref") for e in subject.exemplars
                    if e.get("vec_ref")]
        record = subject.record
        name, who = subject.name, subject.who
        if name:
            previous = record.setdefault("previous_names", [])
            if name not in previous:
                previous.append(name)
        record["name"] = None
        record["who"] = None
        record["status"] = STATUS_DRAFT
        record.pop("confirmed_by", None)
        record["unconfirmed"] = {"at": base["at"], "by": by, "reason": reason,
                                 "was": name, "who": who}
        # SNS-5's third layer. A status flip re-opens the question for a NEW
        # work dir; the work dir where the wrong name was typed still holds the
        # review file that booked this id, and `asked_before()` reads it. See
        # REOPENED_FLAG.
        record[REOPENED_FLAG] = True
        # SNS-15's reversal, and it is why the sweep may write at all. Every
        # draft the sweep folded into this name was declining to ask a question
        # BECAUSE of this yes; with the yes withdrawn, the declining has no
        # ground left and each one goes back into the question loop. A
        # withdrawal that left them absorbed would make the sweep a one-way
        # door built out of a reversible decision.
        released = self.release_absorbed(subject_id, by=by, reason=reason)
        centroid = self.draft_centroid(subject_id)
        result = {"subject_id": subject_id, "was": name, "who": who,
                  "exemplars_retained": retained,
                  "released_absorbed": released,
                  "draft_centroid": centroid is not None}
        self.audit({**base, "was": name, "exemplars_retained": retained,
                    "released_absorbed": released,
                    "draft_centroid": result["draft_centroid"]})
        return result

    def revive(self, subject_id, by=None, reason=None):
        """Take a rejection back: the subject becomes a draft and is asked
        about again. -> a dict describing what was revived.

        ⚠️ **This verb is what makes OA-14's suppression legal to ship**, and
        it is not a convenience. Before `rejected_match()`, a rejected record
        was inert and invisible — it hid, and the subject came back next dump
        under a new id, which is the bug. Suppression makes it inert and
        ACTIVE: it now eats the question every dump, for as long as the pack
        lives. A door that strong with no handle on the inside is a one-way
        door, and SNS-5's fourth job says the opposite — no permanent decision
        anywhere in this system is invisible or unreachable to the owner.

        Step 4 RE-PRESENTS rejections in a round — compactly, with no frames,
        each carrying a `recheck:` row — so the owner reaches this verb
        without a CLI. `--revive` stays the handle for anything not in a
        round.

        What moves, and what deliberately does not:

          1. **the status goes back to `ai-drafted`** — askability is a status
             whitelist, so that is all it costs, and `rejected_match()` stops
             seeing the record in the same move;
          2. **the draft centroid is left exactly where it is.** It was the
             suppression key and it becomes the dedupe key again — the same
             vector, doing the job it did before the rejection. Nothing is
             recomputed: a centroid computed here would be geometry inventing
             a key nobody observed;
          3. **frozen exemplars stay frozen.** A rejected record gains none
             (gate 3), and a revived draft gains none either — status is what
             decides, in `recognisers` and in `add_exemplar()`, and this verb
             moves the status to `ai-drafted`, not to a yes;
          4. **the rejection is kept, not erased** — `revived` records what
             was taken back and when. The owner's history of decisions is not
             something a later decision may overwrite;
          5. **`REOPENED_FLAG` is set**, for the same reason `unconfirm()`
             sets it: the work dir that rendered the tile the owner skipped
             still holds that review file, and `photo_memory.asked_before()`
             reads it.

        ⚠️ The registry half is not sufficient on its own. `photo_memory.
        settled_subjects()` reads the memory log, where the `rejected` line
        closed this subject for every later run, so a status flip alone leaves
        it askable by `is_draft` and suppressed by the log — revived and
        invisible at once, which is exactly the trap `un-confirm` had to
        avoid. `photo_memory.record_revive()` writes the clearing line."""
        # LITERAL — the status test below is the whole verb, and a resolving
        # fetch would read the WINNER's status when the owner named an alias.
        subject = self.get_literal(subject_id)
        if subject is None:
            raise ValueError(f"no such subject: {subject_id}")
        base = {"subject_id": subject_id, "decision": "revived", "by": by,
                "reason": reason, "at": datetime.now().strftime("%Y-%m-%d")}
        if subject.status == STATUS_MERGED_INTO:
            # SNS-14. The whitelist below refuses this record anyway; what it
            # cannot say is that there is no un-fold verb at all, which is the
            # thing a caller reaching for `revive` on an alias is looking for.
            why = (f"{subject_id} was folded into "
                   f"{subject.record.get('merged_into') or 'another subject'} "
                   f"— that is not a rejection and there is nothing here to "
                   "take back. A fold has no reverse verb: the two exemplar "
                   "sets were concatenated and the cap has evicted across "
                   "both, so nothing knows which look came from where.")
            self.audit({**base, "decision": "refused", "gate": "merged-into",
                        "reason": why})
            raise ValueError(why)
        if subject.status != STATUS_REJECTED:
            why = (f"{subject_id} is {subject.status}, not {STATUS_REJECTED} — "
                   "there is no rejection to take back. This verb reverses one "
                   "decision only; a confirmation is `unconfirm()` and a split "
                   "parent has no reverse at all.")
            self.audit({**base, "decision": "refused", "gate": "status",
                        "reason": why})
            raise ValueError(why)

        record = subject.record
        rejected_at = dict(record.get("rejected") or {})
        record["status"] = STATUS_DRAFT
        record["revived"] = {"at": base["at"], "by": by, "reason": reason,
                             "rejected": rejected_at or None}
        # Same third layer, same reason: the work dir that rendered the tile
        # the owner skipped still holds that review file. See REOPENED_FLAG.
        record[REOPENED_FLAG] = True
        centroid = self.draft_centroid(subject_id)
        result = {"subject_id": subject_id,
                  "exemplars_retained": [e.get("vec_ref")
                                         for e in subject.exemplars
                                         if e.get("vec_ref")],
                  "draft_centroid": centroid is not None,
                  "was_rejected": rejected_at or None}
        self.audit({**base, "draft_centroid": result["draft_centroid"],
                    "exemplars_retained": result["exemplars_retained"]})
        return result

    # -- SNS-15: the sweep --------------------------------------------------

    def sweep_absorb(self, subject_ids, by=None, reason=None):
        """SNS-15. Re-score the drafts that are still open against the
        subjects just confirmed, and absorb the ones that are the same
        subject. -> [{subject_id, into, score, files, kind}], in id order.

        ⭐ **Why it has to exist at all.** `confirmed_match()` is consulted for
        INCOMING clusters only; nothing has ever re-scored the drafts already
        on the books. So one animal sitting in dozens of draft records is
        named once and the other records come back round after round, each one
        now colliding with the name the owner just typed. SNS-4's "rounds get
        cheaper as the profile matures" is delivered by this function or by
        nothing.

        ⛔ **Only the subjects passed in**, never every confirmed subject in
        the pack. The sweep rides on a confirmation the owner has JUST made —
        a pack-wide re-score would absorb drafts on the strength of a yes
        given months ago, which is a decision nobody took at a moment nobody
        chose. Re-presentation promotes nothing (SNS-5/SNS-6), so "the
        subjects that gained exemplars in this confirm" is exactly the set.

        ⚠️ It writes LESS than any other path in this module, and that is the
        V2-5a argument rather than an optimisation. No name, no exemplar, no
        `active` widening, no contact sheet — the confirmed subject's own
        facts are not touched by geometry, and the absorbed record only leaves
        the question loop. Its files keep rendering the class word with
        `draft:` provenance until they match exemplars at the `accept` bar;
        absorption kills questions and never names a file.

        The score is `confirmed_match()`'s shape — max cosine over the
        exemplar rows — but the input is the draft's retained FIRST-SIGHTING
        centroid, which is why the bar is its own `{sweep_absorb_tau}` and not
        that function's."""
        import numpy as np

        tau = float(self.defaults.get("sweep_absorb_tau",
                                      DEFAULT_THRESHOLDS["sweep_absorb_tau"]))
        at = datetime.now().strftime("%Y-%m-%d")
        winners = []
        for subject_id in subject_ids:
            # LITERAL — the status test on the next line is what limits the
            # sweep to subjects a yes stands behind. A resolving fetch would
            # let a tombstone id in the caller's list sweep on the winner's
            # exemplars, which is a decision nobody took about an id nobody
            # confirmed in this run.
            subject = self.get_literal(subject_id)
            if subject is None or subject.status != STATUS_CONFIRMED \
                    or not subject.exemplars:
                continue
            V = self.vectors_for(subject.subject_id)
            if V is None or not len(V):
                continue
            winners.append((subject, V))
        if not winners:
            return []

        absorbed = []
        for draft in sorted(self.drafts, key=lambda s: s.subject_id):
            if draft.record.get("asked_away"):
                # Q8-a — this draft exists to be ASKED; absorbing it on
                # geometry would end the question silently.
                continue
            vec = self.draft_centroid(draft.subject_id)
            if vec is None:
                # Nothing to score. A draft with no centroid is not absorbed on
                # its evidence instead: computing one here would be geometry
                # inventing the key the decision is taken on, which is the same
                # refusal `rejected_match()` makes one status along.
                continue
            scored = []
            for subject, V in winners:
                if draft.kind and subject.kind and draft.kind != subject.kind:
                    # The same-species guard all three comparisons make: two
                    # kinds are two subjects however close their vectors sit.
                    continue
                if V.shape[1] != vec.shape[0]:
                    continue
                # ⛔ The space is attached HERE, to the comparison that
                # produced this score, and not to the row afterwards. Both
                # operands are CLIP — `vectors_for()` is the exemplar store and
                # `draft_centroid()` reads `draft-vectors/` — so this sweep is
                # a CLIP decision today, whatever spaces exist elsewhere in the
                # module. An identity branch added above would have to name its
                # own space to append a row, which is the point of putting it
                # in the tuple rather than at the end.
                scored.append((float(np.max(V @ vec)), subject, SPACE_CLIP))
            scored.sort(key=lambda t: (-t[0], t[1].subject_id))
            if not scored or scored[0][0] < tau:
                continue
            score, winner, space = scored[0]
            score = round(score, 4)
            record = draft.record
            record["status"] = STATUS_ABSORBED
            record["absorbed_by"] = winner.subject_id
            record["absorbed_at_score"] = score
            record["absorbed"] = {"at": at, "by": by, "src": reason,
                                  "was": draft.status, "space": space}
            # ⛔ The parent's own counters are NOT mutated. The bookkeeping
            # folds as a LIST the release can walk back item by item; adding
            # the files into `files` would be a number no reversal could
            # separate again from the files that were always the parent's.
            winner.record.setdefault("absorbed_drafts", []).append(
                {"subject_id": draft.subject_id,
                 "files": int(record.get("files", 0)),
                 "score": score, "at": at, "space": space})
            row = {"subject_id": draft.subject_id, "into": winner.subject_id,
                   "score": score, "files": int(record.get("files", 0)),
                   "kind": draft.kind, "space": space}
            absorbed.append(row)
            self.audit({**row, "decision": "absorbed", "by": by,
                        "reason": reason, "at": at, "tau": tau})
        return absorbed

    def attach_draft_to_subject(self, draft_id, subject_id, vec_refs,
                                by=None, reason=None):
        """SNS-16's storage half — the owner says this draft is the subject
        the pack already knows. -> {"looks": n, "was": the draft's status}.

        ⭐ **Signed 2026-08-20, and it is a PROMOTION, not a fold and not a new
        record.** SNS-1 sends two already-confirmed subjects to SNS-14's fold;
        nobody had covered the other direction, which is what arrives on every
        dump after the first for every remembered subject whose new
        photographs the geometry failed to match. Measured 2026-08-20: the
        engine INSTRUCTED the owner to type `same` and then refused it.

        Two writes and no others:

          * the picked looks are COPIED onto the confirmed subject, so the
            promotion that follows has provenance to stand on and SNS-6's
            worst-frame re-presentation can show the owner what came in. ⛔
            Without them `attach_exemplars()` has nothing to promote from and
            the accepted cost below would be uncatchable;
          * the draft becomes `absorbed` (SNS-15's bookkeeping-only status),
            with `absorbed_by` and a row on the winner's `absorbed_drafts`
            list, which is what `release_absorbed()` walks back.

        ⛔ **NO SIMILARITY BAR, and no `absorbed_at_score`.** This is the
        substance of the signature, not a detail: the promotion is accepted on
        the owner's yes alone. Every other bar in this file sits at 0.85, and
        a confirmed subject scored **0.832** against its own photograph at C1
        — a bar meant to protect it would have refused a real photo of it.
        Photographs of one animal across a year score 0.60–0.85 against each
        other; that finding killed cross-batch dedupe once already. Geometry
        may not overrule a human who has looked at the photograph.

        ⚠️ The accepted cost is a mis-picked frame entering unchecked. It is
        caught by SNS-6's worst-frame re-presentation — which is why the looks
        are carried across — and reversed by `unconfirm`.

        ⛔ The confirmed subject gains the looks and NOTHING else: not its
        name, not its `who`, not its first-sighting centroid, and not its
        `active` range. SNS-14 unions `active` because a fold joins two
        attested identities; this attests one photograph at a time, and
        widening a range on that would be a fact nobody stated. `obs_count`,
        `observed_in` and `files` are the draft's own bookkeeping and stay
        with the draft, which is what keeps the release honest."""
        # LITERAL on both sides. The winner must be the record the owner's
        # name resolves to, and the draft must be the record the page named:
        # a resolving fetch would promote onto a tombstone's winner, or absorb
        # a record nobody picked frames from.
        why = self.attach_draft_refusal(draft_id, subject_id, vec_refs)
        if why:
            raise ValueError(why)
        draft = self.get_literal(draft_id)
        winner = self.get_literal(subject_id)
        refs = set(vec_refs)
        carried = self._inherit_evidence(draft.record, refs)
        winner.record.setdefault("evidence", []).extend(carried)
        at = datetime.now().strftime("%Y-%m-%d")
        was = draft.status
        draft.record["status"] = STATUS_ABSORBED
        draft.record["absorbed_by"] = subject_id
        # ⛔ No `space` here, deliberately. Nothing was compared: the owner
        # said this draft is that subject, so there is no space to name and
        # inventing one would put a geometric claim behind a human answer.
        # `answered: True` is what separates this from a row whose space was
        # simply never recorded — see `absorbed_space()`.
        draft.record["absorbed"] = {"at": at, "by": by, "src": reason,
                                    "was": was, "answered": True}
        winner.record.setdefault("absorbed_drafts", []).append(
            {"subject_id": draft_id, "files": int(draft.record.get("files", 0)),
             "score": None, "at": at})
        looks = sum(len(entry.get("looks") or []) for entry in carried)
        self.audit({"subject_id": draft_id, "into": subject_id,
                    "decision": "attached", "looks": looks,
                    "vec_refs": sorted(refs), "by": by, "reason": reason,
                    "at": at, "was": was})
        return {"looks": looks, "was": was}

    def attach_draft_refusal(self, draft_id, subject_id, vec_refs):
        """-> the sentence `attach_draft_to_subject()` would refuse with, or
        None. Nothing is written and nothing is audited.

        The same pattern `fold_refusal()`, `rename_refusal()` and
        `partition_refusal()` follow, and for the reason step 9 item 2 made
        explicit: the caller answers about SEVERAL drafts on one row, and a
        row is refused whole or applied whole. A verb that raised half way
        through would leave one draft absorbed and the next one not, which no
        later reader could tell from a deliberate outcome."""
        # LITERAL on both sides. The winner must be the record the owner's
        # name resolves to, and the draft the record the page named: a
        # resolving fetch would promote onto a tombstone's winner, or absorb a
        # record nobody picked frames from.
        draft = self.get_literal(draft_id)
        winner = self.get_literal(subject_id)
        if draft is None:
            return f"no such subject: {draft_id}"
        if winner is None:
            return f"no such subject: {subject_id}"
        if winner.status != STATUS_CONFIRMED:
            return (f"{subject_id} is {winner.status}, not {STATUS_CONFIRMED} "
                    "— a draft may only join a subject a human yes stands "
                    "behind")
        if not draft.is_draft:
            return (f"{draft_id} is {draft.status}, not a draft — only an "
                    "unidentified cluster joins a subject this way")
        missing = sorted(set(vec_refs) - set(self._looks_by_ref(draft.record)))
        if missing:
            return (f"{draft_id}: no look on this draft carries "
                    + ", ".join(missing)
                    + " — the frames the row picked are not this record's")
        return None

    def detach_refusal(self, draft_id, into=None):
        """-> the sentence `review --detach` refuses with, or None. FIX7 (U7-1).

        Only a draft a JOIN absorbed can be detached: its status is `absorbed`
        and `absorbed_by` names the record it went into. `--into` must be a
        different confirmed subject, for `attach_draft_refusal()`'s reason —
        a draft joins only a subject a human yes stands behind."""
        draft = self.get_literal(draft_id)
        if draft is None:
            return f"no such subject: {draft_id}"
        into_of = draft.record.get("absorbed_by")
        if draft.status != STATUS_ABSORBED or not into_of:
            return (f"{draft_id} is {draft.status}, not a draft joined to a "
                    "subject — there is nothing to detach")
        if self.get_literal(into_of) is None:
            return f"{draft_id} was joined to {into_of}, which no longer exists"
        if into:
            target = self.get_literal(into)
            if target is None:
                return f"no such subject: {into}"
            if into == into_of:
                return f"{draft_id} is already joined to {into}"
            if target.status != STATUS_CONFIRMED:
                return (f"{into} is {target.status}, not {STATUS_CONFIRMED} — "
                        "a draft may only join a subject a human yes stands "
                        "behind")
        return None

    def _release_child(self, child, by=None, reason=None):
        """One absorbed draft back to the question loop — the body
        `release_absorbed()` runs per row, shared with `release_one()`."""
        child.record["status"] = STATUS_DRAFT
        child.record.pop("absorbed_by", None)
        child.record.pop("absorbed_at_score", None)
        child.record["absorbed"] = {
            **(child.record.get("absorbed") or {}),
            "released_at": datetime.now().strftime("%Y-%m-%d"),
            "released_by": by, "released_reason": reason}
        child.record[REOPENED_FLAG] = True

    def release_one(self, draft_id, by=None, reason=None):
        """FIX7 (U7-1) — release ONE draft from the subject it was joined to,
        and nothing else of that subject's. -> the subject it left, or None.

        `release_absorbed()` releases every row, because withdrawing a name
        withdraws every answer under it; a detach withdraws one answer. The
        row leaves the winner's `absorbed_drafts`; the same guards hold (the
        child's own status and `absorbed_by`)."""
        child = self.get_literal(draft_id)
        if child is None or child.status != STATUS_ABSORBED:
            return None
        from_id = child.record.get("absorbed_by")
        winner = self.get_literal(from_id) if from_id else None
        if winner is None:
            return None
        rows = winner.record.get("absorbed_drafts") or []
        kept = [r for r in rows if r.get("subject_id") != draft_id]
        if kept:
            winner.record["absorbed_drafts"] = kept
        else:
            winner.record.pop("absorbed_drafts", None)
        self._release_child(child, by, reason)
        return from_id

    def absorbed_listing(self, draft_id):
        """FIX7 (U7-2) -> {subject_id, status, files, crops} for one absorbed
        draft: the photo names on its looks and a picture of each the owner
        can open (`look_crop()`)."""
        draft = self.get_literal(draft_id)
        files, crops = [], []
        for look in (self._looks_by_ref(draft.record).values() if draft else []):
            name = Path(look.get("path") or "").name
            if name and name not in files:
                files.append(name)
            crop = look_crop(look)
            if crop and crop not in crops:
                crops.append(crop)
        return {"subject_id": draft_id, "status": draft.status if draft else None,
                "files": files, "crops": crops}

    def resolve_drop_refs(self, refs, subject_ids=None):
        """FIX7 — what `--drop` was given, resolved to full vec_refs.
        -> (resolved, refusals).

        `review` prints a 12-character ref beside each exemplar's photo, so
        the ref the owner can copy is a PREFIX. A prefix of at least
        MIN_DROP_PREFIX characters that matches exactly one exemplar is that
        exemplar; anything shorter, unknown or ambiguous is refused, with the
        candidates named. ⛔ Never the nearest match: dropping the wrong
        evidence is silent and the owner cannot see it happen."""
        rows = [(s.subject_id, e) for s in self.subjects for e in s.exemplars
                if not subject_ids or s.subject_id in subject_ids]
        resolved, refusals = [], []
        for ref in refs:
            if any(e.get("vec_ref") == ref for _sid, e in rows):
                resolved.append(ref)
                continue
            if len(ref) < MIN_DROP_PREFIX:
                refusals.append(
                    f"{ref!r} is shorter than {MIN_DROP_PREFIX} characters — "
                    "give the full vec_ref (`review --json` holds it) or at "
                    "least the first 12 that `review` prints")
                continue
            hits = [(sid, e) for sid, e in rows
                    if (e.get("vec_ref") or "").startswith(ref)]
            if not hits:
                refusals.append(
                    f"no exemplar starts with {ref!r} — `review` lists each "
                    "one's short vec_ref beside its photo")
            elif len(hits) > 1:
                refusals.append(
                    f"{ref!r} matches {len(hits)} exemplars, so which one to "
                    "drop has not been said: "
                    + "; ".join(f"{sid} {Path(e.get('source') or '').name or '(no photo)'}"
                                f" {(e.get('vec_ref') or '')[:16]}"
                                for sid, e in hits)
                    + " — give more characters")
            else:
                resolved.append(hits[0][1]["vec_ref"])
        return resolved, refusals

    def not_this_refs(self, subject_id):
        """Q8-b — the vec_refs the owner took out of this subject's memory."""
        subject = self.get_literal(subject_id)
        if subject is None:
            return set()
        return {e.get("vec_ref") for e in subject.record.get("not_this") or []}

    def take_out_photos(self, subject_id, refs, by=None, reason=None):
        """Q8-b — the owner's `not <frame>`: these photos leave ONE subject's
        memory and the name stays. -> {"exemplars", "looks", "refs"}.

        Removes the exemplar (if the photo was one) and every look carrying
        the ref, and lists the ref in `not_this` so no engine path files it
        back: the next memorize's recognised sighting, an automatic exemplar,
        the worst-frame check. ⛔ Records only — no folder name and no
        see-label changes, like `review --prune --drop`. The `files` /
        `obs_count` totals are left as they are: other readers sum them."""
        subject = self.get_literal(subject_id)
        if subject is None or subject.status != STATUS_CONFIRMED:
            raise ValueError(f"{subject_id} is not a confirmed subject")
        refs = [r for r in refs if r]
        paths = {}
        for entry in subject.record.get("evidence") or []:
            for look in entry.get("looks") or []:
                if look.get("vec_ref") in refs:
                    paths.setdefault(look["vec_ref"], look.get("path"))
        for exemplar in subject.exemplars:
            if exemplar.get("vec_ref") in refs:
                paths.setdefault(exemplar["vec_ref"], exemplar.get("source"))
        dropped = self.drop_exemplars(subject_id, refs)
        looks, kept = 0, []
        for entry in subject.record.get("evidence") or []:
            before = entry.get("looks") or []
            after = [l for l in before if l.get("vec_ref") not in refs]
            looks += len(before) - len(after)
            if before and not after:
                continue
            if len(after) != len(before):
                entry["looks"] = after
            kept.append(entry)
        subject.record["evidence"] = kept
        at = datetime.now().strftime("%Y-%m-%d")
        listed = subject.record.setdefault("not_this", [])
        for ref in refs:
            if ref not in {e.get("vec_ref") for e in listed}:
                listed.append({"vec_ref": ref, "path": paths.get(ref),
                               "at": at, "by": by, "reason": reason})
            self.audit({"at": at, "by": by, "subject_id": subject_id,
                        "decision": "not-this", "vec_ref": ref,
                        "was_exemplar": ref in dropped, "reason": reason})
        return {"exemplars": dropped, "looks": looks, "refs": refs}

    def lift_not_this(self, subject_id, refs, by=None, reason=None):
        """Q8-b — the owner picked these photos for this subject again: the
        one thing that lifts `not`. -> the refs lifted."""
        subject = self.get_literal(subject_id)
        if subject is None:
            return []
        refs = set(refs or ())
        listed = subject.record.get("not_this") or []
        lifted = [e["vec_ref"] for e in listed if e.get("vec_ref") in refs]
        if lifted:
            subject.record["not_this"] = [e for e in listed
                                          if e.get("vec_ref") not in refs]
            at = datetime.now().strftime("%Y-%m-%d")
            for ref in lifted:
                self.audit({"at": at, "by": by, "subject_id": subject_id,
                            "decision": "not-this-lifted", "vec_ref": ref,
                            "reason": reason})
        return lifted

    def drop_exemplars(self, subject_id, refs):
        """-> the vec_refs removed from one subject's exemplars, with their
        vector rows. No cap is applied: `prune()` adds that, a detach does
        not, because a cap eviction would drop exemplars nobody named. The
        identity store follows at `save()`, which keeps only listed refs."""
        import numpy as np

        subject = self.get_literal(subject_id)
        if subject is None:
            return []
        gone = []
        for ref in list(refs):
            idx = next((i for i, e in enumerate(subject.exemplars)
                        if e.get("vec_ref") == ref), None)
            if idx is None:
                continue
            V = self.vectors_for(subject.subject_id)
            del subject.exemplars[idx]
            if V is not None and len(V):
                self._vectors[subject.subject_id] = np.delete(V, idx, axis=0)
            gone.append(ref)
        return gone

    def remove_carried_evidence(self, subject_id, draft_id, refs, dry_run=False):
        """FIX7 (U7-1) — undo `_inherit_evidence()` for one join. -> the
        number of looks removed from `subject_id`'s evidence.

        Only looks carrying one of `refs`, in an entry from a batch and see
        run the draft's own evidence holds them in. An entry left empty goes;
        a carried entry is recounted to its looks (it was counted that way
        when copied), and an entry of the subject's own keeps its count."""
        subject, draft = self.get_literal(subject_id), self.get_literal(draft_id)
        if subject is None or draft is None or not refs:
            return 0
        refs = set(refs)
        keys = {(e.get("batch"), e.get("run_id"))
                for e in draft.record.get("evidence") or []
                if any(l.get("vec_ref") in refs for l in e.get("looks") or [])}
        removed, kept = 0, []
        for entry in subject.record.get("evidence") or []:
            looks = entry.get("looks") or []
            keep = [l for l in looks if l.get("vec_ref") not in refs]
            if (entry.get("batch"), entry.get("run_id")) not in keys \
                    or len(keep) == len(looks):
                kept.append(entry)
                continue
            removed += len(looks) - len(keep)
            if not keep:
                continue
            entry = dict(entry)
            if entry.get("files") == len(looks):
                entry["files"] = len(keep)
            samples = {l.get("sample") for l in keep}
            if entry.get("seen"):
                entry["seen"] = [s for s in entry["seen"] if Path(s).name in samples]
            entry["looks"] = keep
            kept.append(entry)
        if removed and not dry_run:
            subject.record["evidence"] = kept
        return removed

    def picked_looks(self, draft_id):
        """-> the looks of `draft_id` the owner picked on the row that joined
        it, read off the memorize audit's `attached` vec_refs since the last
        time this draft was released or detached. A draft the sweep absorbed
        has no such row: nothing was picked, so nothing is returned."""
        draft = self.get_literal(draft_id)
        if draft is None:
            return []
        into_of = draft.record.get("absorbed_by")
        refs = []
        for row in self.audit_trail():
            decision = row.get("decision")
            if decision == "released" and draft_id in (row.get("released") or []):
                refs = []
            elif decision == "detached" and row.get("subject_id") == draft_id:
                refs = []
            elif (decision == "attached" and row.get("subject_id") == draft_id
                    and row.get("into") == into_of):
                refs += [r for r in row.get("vec_refs") or [] if r not in refs]
        looks = self._looks_by_ref(draft.record)
        return [looks[r] for r in refs if r in looks]

    def release_absorbed(self, subject_id, by=None, reason=None):
        """Undo the sweep for one confirmed subject. -> [subject_id released].

        The other half of what makes absorption legal. SNS-15's V2-5a argument
        is that nothing was written, so the fold is cheaply reversible — an
        argument that is only true if something reverses it. Called by
        `unconfirm()`, because withdrawing the name withdraws the answer the
        absorption declined to ask again.

        The released draft comes back with `REOPENED_FLAG` set, for the reason
        `unconfirm()` and `revive()` both set it: a review file in the work dir
        may already have booked this id, and a draft released into a question
        loop that is holding it shut is released nowhere.

        ⚠️ SNS-14 — after a fold, the winner's list also holds the rows the
        LOSER absorbed, re-pointed at the winner by `fold_subjects()`. That is
        deliberate and it is what keeps absorption reversible across a fold:
        left on the tombstone those rows could never be released by anything,
        which is the one-way door SNS-15's legality rests on not being."""
        # LITERAL — this verb reverses ONE record's own fold. A resolving fetch
        # called with a tombstone would pop the WINNER's list on an id that
        # holds none, releasing drafts nobody withdrew a name from.
        subject = self.get_literal(subject_id)
        if subject is None:
            return []
        released = []
        for row in list(subject.record.get("absorbed_drafts") or []):
            # LITERAL again, and for the neighbouring reason: the two tests on
            # the next line read the CHILD's own status and its own
            # `absorbed_by`, which is how this verb refuses to reverse a fold it
            # did not write.
            child = self.get_literal(row.get("subject_id"))
            if child is None or child.status != STATUS_ABSORBED \
                    or child.record.get("absorbed_by") != subject_id:
                # Somebody else's absorption, or a record that has moved on
                # since. Left exactly as it is: this verb reverses its own
                # subject's fold and never a status it did not write.
                continue
            self._release_child(child, by, reason)
            released.append(child.subject_id)
        subject.record.pop("absorbed_drafts", None)
        if released:
            self.audit({"subject_id": subject_id, "decision": "released",
                        "released": released, "by": by, "reason": reason,
                        "at": datetime.now().strftime("%Y-%m-%d")})
        return released

    # -- SNS-14: two confirmed subjects that turn out to be one -------------

    def _ordinal(self, subject_id):
        """The number in `subj-0007`, which is what "earlier-confirmed" means
        in practice: ids are minted in order and never reused. An id that does
        not match the pattern sorts last, by its own text, so the winner is
        still deterministic in a hand-edited pack."""
        match = SUBJECT_ID_PATTERN.match(subject_id or "")
        return (0, int(subject_id.split("-")[1]), "") if match \
            else (1, 0, str(subject_id))

    def fold_refusal(self, subject_ids):
        """-> the one reason this fold may not happen, or None.

        Separated from `fold_subjects()` so the confirm checkpoint's DRY RUN
        refuses exactly what `--go` refuses. The verb writes to the audit log
        at the decision point, so it only runs under `--go`; without this a dry
        run would promise a fold that the real run then refuses, and a dry run
        that does not predict `--go` is worth less than no dry run at all.

        Four refusals, and each one names the id it is about plus the way on —
        the house pattern, because a caller told *"revive it first"* learns
        something a generic refusal cannot tell them."""
        try:
            resolved = [(sid, self.resolve_merged(sid)) for sid in subject_ids]
        except ValueError as exc:
            # A corrupt merge chain. Reported as a refusal rather than raised,
            # because the caller is in the middle of a review file that may
            # hold nine good rows.
            return str(exc)

        for subject_id, subject in resolved:
            if subject is None:
                return (f"no such subject: {subject_id}. A fold joins two "
                        "records that both exist; nothing was written.")
            if subject.status == STATUS_CONFIRMED:
                continue
            if subject.status == STATUS_REJECTED:
                return (f"{subject.subject_id} is {STATUS_REJECTED} — the owner "
                        "asked never to be asked about it again, and a fold "
                        "would put its looks back into a subject that names "
                        "files. Revive it first "
                        f"(`photo_subjects.py review --revive "
                        f"{subject.subject_id} --go`), name it, and then say "
                        "they are the same.")
            if subject.status == STATUS_ABSORBED:
                return (f"{subject.subject_id} was {STATUS_ABSORBED} into "
                        f"{subject.record.get('absorbed_by') or 'another subject'}"
                        " — the sweep already stopped asking about it, and it "
                        "holds no confirmation to fold. Withdraw that "
                        "subject's name, which releases this draft back into "
                        "the question loop, and answer it there.")
            return (f"{subject.subject_id} is {subject.status}, not "
                    f"{STATUS_CONFIRMED} — a fold joins two subjects the owner "
                    "has each already named. Nothing was written.")

        live = {s.subject_id: s for _sid, s in resolved}
        if len(live) < 2:
            only = sorted(live)[0] if live else "?"
            return (f"{only} is the only subject named here — the ids given "
                    "are already one record, which is what a fold makes them. "
                    "Nothing was written and nothing needs to be.")

        kinds = {s.kind for s in live.values() if s.kind}
        if len(kinds) > 1:
            return ("these subjects are of different kinds ("
                    + ", ".join(f"{s.subject_id} is {s.kind}"
                                for s in sorted(live.values(),
                                                key=lambda x: x.subject_id)
                                if s.kind)
                    + "). Two kinds are two subjects however alike they look — "
                    "the same guard every comparison in this registry makes — "
                    "so this is refused rather than resolved. If one of them "
                    "carries the wrong kind, that is what to correct first.")
        return None

    def fold_subjects(self, subject_ids, name=None, who=None, by=None,
                      reason=None):
        """SNS-14 — two subjects the owner confirmed separately and has since
        said are one. -> a dict describing the fold.

        ⭐ **The earlier `subject_id` wins** (lower ordinal). Deterministic,
        explainable, and it is the id most likely to be sitting in a plan CSV
        or a folder record already. ⛔ NOT the one with more exemplars: that
        rule re-decides itself every time the cap evicts, so two runs over one
        pack could disagree about which record is the subject.

        What moves, and why each one is the way it is:

          * **exemplars concatenate DIRECTLY, then `_enforce_cap()`** — never
            re-added through `add_exemplar()`. The loser's exemplars passed
            gates 1 and 2 once already, and re-gating would refuse every one
            whose work-dir artifacts have since been cleaned away: a set a
            human blessed, silently thinned by housekeeping. The cap's
            redundancy eviction then does exactly the right thing with two sets
            of one animal;
          * **the loser becomes an alias tombstone** — `merged-into`,
            `merged_into`, exemplars emptied, its vectors file removed by
            `save()`. Nothing is deleted from disk here, so a DRY RUN at the
            call site above still writes nothing;
          * **every name either record ever held lands in the winner's
            `previous_names`**, which is what makes `rename_ledger()` resolve
            each folder already written under the losing name. N-10a holds
            across the fold;
          * **the tombstone keeps NO name.** It is outside both whitelists, so
            a name left on it would render through `photo_plan.py:132` as a
            second confirmed identity for the one animal this just made
            single. Its own history keeps the name it had;
          * **`absorbed_drafts` MOVE to the winner and their children are
            re-pointed at it.** Left on the tombstone, `release_absorbed()`
            could never reach them — its per-child test compares `absorbed_by`
            against the id it was called on — so withdrawing the winner's name
            would leave those drafts absorbed forever. That is the one-way door
            SNS-15's whole legality rests on not being;
          * **the `active` ranges union**, as intervals: an undeclared bound is
            UNBOUNDED, so the union never narrows anybody's range. It is the
            one fact a fold widens, and it is legal here because it is
            human-attested rather than inferred;
          * **`files` stays where it is, on both records.** ⛔ No sum is stored
            — that is the shape the owner's 2026-08-19 decision rejects — and
            the
            tombstone is deliberately NOT appended to `absorbed_drafts`, which
            `release_absorbed()` would pop, resurrecting a folded subject as a
            draft. What the owner reads is `display_files()`, which adds the
            two at READ time;
          * **chained folds are compressed in storage.** Folding B into C
            re-points every tombstone that named B at C, so no tombstone ever
            points at a tombstone and `resolve_merged()`'s depth guard is only
            met by a hand-edited pack.

        ⛔ **Folders on disk under the losing name stay exactly where they
        are.** This engine is copy-only and moves nothing; the ledger is what
        keeps them resolvable, and the result carries the names so the caller
        can say so out loud.

        ⛔ **No fold is ever proposed from geometry.** Surfacing lookalikes is
        fine; the answer stays human, and this verb is only reached through a
        name the owner typed with the `same` token beside it."""
        import numpy as np

        base = {"subject_id": None, "decision": "merged", "by": by,
                "reason": reason, "at": datetime.now().strftime("%Y-%m-%d")}
        refusal = self.fold_refusal(subject_ids)
        if refusal:
            self.audit({**base, "decision": "refused", "gate": "fold",
                        "asked": list(subject_ids), "reason": refusal})
            raise ValueError(refusal)

        parts = {}
        for subject_id in subject_ids:
            subject = self.resolve_merged(subject_id)
            parts[subject.subject_id] = subject
        order = sorted(parts, key=self._ordinal)
        winner = parts[order[0]]
        losers = [parts[sid] for sid in order[1:]]

        names = [n for n in ([winner.name] + winner.previous_names) if n]
        # The names that were RENDERED before this fold. What matters to a
        # reader is which of them stops being rendered afterwards, because that
        # is the set of folders on disk that now carry a name no live subject
        # displays — the advisory the confirm prints, and it must include the
        # WINNER's old name too: `same` is typed as the OTHER subject's name,
        # so the name that retires is as often the winner's as the loser's.
        rendered = [n for n in [winner.name] if n]
        folded = []
        for loser in losers:
            names += [n for n in ([loser.name] + loser.previous_names) if n]
            if loser.name:
                rendered.append(loser.name)

            # -- exemplars: concatenate, then let the cap evict for redundancy
            held = {e.get("vec_ref") for e in winner.exemplars}
            incoming = [e for e in loser.exemplars
                        if e.get("vec_ref") not in held]
            V = self.vectors_for(winner.subject_id)
            W = self.vectors_for(loser.subject_id)
            if incoming and W is not None and len(W):
                keep = [i for i, e in enumerate(loser.exemplars)
                        if e.get("vec_ref") not in held]
                rows = W[keep]
                if V is not None and len(V) and V.shape[1] == rows.shape[1]:
                    self._vectors[winner.subject_id] = np.vstack([V, rows])
                elif V is None or not len(V):
                    self._vectors[winner.subject_id] = rows
                else:
                    # Two models' vectors are not comparable, and a fold is not
                    # the place to discover it. The names and the alias still
                    # move; the exemplars do not.
                    incoming = []
            if incoming:
                winner.exemplars.extend(incoming)

            # -- the tombstone
            record = loser.record
            was_name, was_who = loser.name, loser.who
            if was_name:
                previous = record.setdefault("previous_names", [])
                if was_name not in previous:
                    previous.append(was_name)
            record["name"] = None
            record["who"] = None
            record["status"] = STATUS_MERGED_INTO
            record["merged_into"] = winner.subject_id
            record["merged"] = {"at": base["at"], "by": by, "reason": reason,
                                "into": winner.subject_id, "was": was_name,
                                "who": was_who,
                                "exemplars": len(loser.exemplars)}
            record.pop("confirmed_by", None)
            record["exemplars"] = []
            # An EMPTY array rather than None, so `save()` takes its unlink
            # branch: `None` means "nothing cached" and would leave the loser's
            # `.npy` on disk beside a record that lists no exemplars — the
            # out-of-step state `vectors_for()` refuses to read. ⚠️ The unlink
            # happens in `save()` and not here, which is what lets the confirm
            # checkpoint's dry run call nothing on disk.
            width = (W.shape[1] if W is not None and len(W)
                     else V.shape[1] if V is not None and len(V) else 1)
            self._vectors[loser.subject_id] = np.zeros((0, width),
                                                       dtype=np.float32)

            # -- SNS-15's rows follow the subject they were absorbed into
            moved = []
            for row in list(record.get("absorbed_drafts") or []):
                child = self.get_literal(row.get("subject_id"))
                if child is None or child.status != STATUS_ABSORBED \
                        or child.record.get("absorbed_by") != loser.subject_id:
                    continue
                child.record["absorbed_by"] = winner.subject_id
                winner.record.setdefault("absorbed_drafts", []).append(dict(row))
                moved.append(child.subject_id)
            record.pop("absorbed_drafts", None)

            # -- the union, as intervals: an undeclared bound is unbounded, so
            # this can only widen and never takes a range away.
            wa = list(winner.record.get("active") or [None, None]) + [None, None]
            la = list(loser.record.get("active") or [None, None]) + [None, None]
            start = None if (wa[0] is None or la[0] is None) \
                else min(wa[0], la[0])
            end = None if (wa[1] is None or la[1] is None) else max(wa[1], la[1])
            winner.record["active"] = [start, end]

            # -- path compression: no tombstone may point at a tombstone
            rechained = []
            for other in self.subjects:
                if other.status == STATUS_MERGED_INTO \
                        and other.record.get("merged_into") == loser.subject_id:
                    other.record["merged_into"] = winner.subject_id
                    other.record.setdefault("merged", {})["rechained_to"] = \
                        winner.subject_id
                    rechained.append(other.subject_id)

            folded.append({"subject_id": loser.subject_id,
                           "was": was_name, "who": was_who,
                           "exemplars_moved": len(incoming),
                           "files": int(record.get("files", 0)),
                           "absorbed_moved": moved, "rechained": rechained})

        if name:
            old = winner.name
            if old and old != name:
                previous = winner.record.setdefault("previous_names", [])
                if old not in previous:
                    previous.append(old)
            winner.record["name"] = name
        if who:
            winner.record["who"] = who
        if by:
            winner.record["confirmed_by"] = by
        previous = winner.record.setdefault("previous_names", [])
        for item in names:
            if item and item != winner.name and item not in previous:
                previous.append(item)
        self.vectors_for(winner.subject_id)
        dropped = self._enforce_cap(winner)

        # ⛔ THE INVARIANT, checked where the join happens and not only in a
        # test: `vectors/<id>.npy` is positional, its row order IS
        # `exemplars[]`, and a fold is the one operation that extends both
        # lists from a second file. Appending to one and not the other
        # mis-attributes every vector after the join — silently, because every
        # later read is by index and an index that exists is never wrong-
        # looking. Raised rather than saved: the registry is still in memory
        # here, so a break leaves the pack on disk untouched.
        for subject in [winner] + losers:
            rows = self._vectors.get(subject.subject_id)
            if rows is None:
                continue
            if len(rows) != len(subject.exemplars):
                raise AssertionError(
                    f"fold left {subject.subject_id} with {len(rows)} vector "
                    f"row(s) against {len(subject.exemplars)} exemplar(s) — "
                    "the two are positional and must move together. Nothing "
                    "was saved.")

        result = {"winner": winner.subject_id, "name": winner.name,
                  "folded": folded,
                  "names_retired": sorted({n for n in rendered
                                           if n != winner.name}),
                  "exemplars": len(winner.exemplars),
                  "dropped_for_cap": dropped,
                  "previous_names": list(winner.previous_names),
                  "active": list(winner.record.get("active") or [None, None])}
        self.audit({**base, "subject_id": winner.subject_id,
                    "folded": [row["subject_id"] for row in folded],
                    "names_retired": result["names_retired"],
                    "exemplars_after": len(winner.exemplars),
                    "dropped_for_cap": dropped,
                    "previous_names": result["previous_names"]})
        return result

    # -- SNS-1b: what a split does in storage -------------------------------

    def _looks_by_ref(self, record):
        """Every look this record holds, keyed on the `vec_ref` a pick row
        names. First writer wins: `vec_ref` is the content sha, so two looks
        carrying one ref are one photograph seen twice."""
        out = {}
        for entry in record.get("evidence") or []:
            for look in entry.get("looks") or []:
                ref = look.get("vec_ref")
                if ref and ref not in out:
                    out[ref] = look
        return out

    def _inherit_evidence(self, parent_record, refs):
        """The parent's evidence, restricted to one group's frames.

        A COPY — the parent keeps its own list whole, because a superseded
        record is an audit trail and SNS-1b keeps its draft vector on disk for
        the same reason. What is partitioned is what the CHILDREN receive: no
        two children share a look, which the overlap refusal guarantees.

        Each inherited entry's `files` is recounted to the looks that came
        with it. The stored number is the parent cluster's member count, and
        SNS-1b item 4 declares that bulk attribution void — carrying it into a
        child would let a reader sum the children back up to the count the
        split just disproved."""
        out = []
        for entry in parent_record.get("evidence") or []:
            looks = [dict(look) for look in (entry.get("looks") or [])
                     if look.get("vec_ref") in refs]
            if not looks:
                continue
            kept = {k: v for k, v in entry.items()
                    if k not in ("looks", "files", "seen")}
            samples = {look.get("sample") for look in looks if look.get("sample")}
            seen = [item for item in (entry.get("seen") or [])
                    if Path(item).name in samples]
            kept["looks"] = looks
            kept["files"] = len(looks)
            if seen:
                kept["seen"] = seen
            out.append(kept)
        return out

    def partition_subject(self, subject_id, groups, by=None, reason=None):
        """SNS-1b item 3 — the three partition cases, decided for ONE draft by
        how many `pick:` rows claim its frames.

        `groups` is one entry per pick row that names a frame of this subject:

            {"vec_refs": [...],          the frames that row picked, required
             "centroid": <vector>,       required when there are 2+ rows
             "shared_with": [ids]}       other subjects the same row names,
                                         and refused on a splitting row

        -> a dict carrying `case`, and `children` when the case is a split.

        | rows | case | what is written |
        |---|---|---|
        | 1, this subject only | `in-place` | NOTHING — the caller confirms this
          id where it stands, and see-labels and plan CSVs that already carry
          it keep resolving |
        | 1, shared with others | `shared` | NOTHING — every member is confirmed
          under one name with its own id, today's F15/F16 posture |
        | 2 or more | `split` | one child per row, and the parent takes
          `superseded` + `split_into` |

        ⭐ **The discriminator is rows, never coverage.** A single row that
        picks three of a tile's five frames is NOT a split: the two frames left
        out are DEFERRED (SNS-3, SNS-11), and reading them as a partition would
        convert the owner's silence into a decision — the one thing this
        question shape exists to stop.

        ## What a child is

        Its own subject, minted as a DRAFT with its own first-sighting centroid
        **computed by the caller from that row's frames** and passed in here.
        The caller then writes the name, the `who` and `human-confirmed`, and
        only then may `photo_memory.attach_exemplars(..., only_refs=<the row's
        refs>)` run — `add_exemplar()`'s third gate refuses any other order,
        and that order is the one `confirm` already uses.

        A child inherits its group's looks, the contact-sheet frames those
        looks were shown on, and an `active` range derived from THEIR OWN
        capture dates. It does not inherit the parent's file count: the split
        is proof the machine's cluster was wrong, so the ~200 files nobody
        looked at re-earn a name per file against the new exemplars (item 4),
        and until they do they render the class word with `draft:` provenance
        (`photo_plan.py:131-137`).

        ⛔ The ⛔ list at SNS-1b, enforced here rather than promised:

          * a group with no usable centroid is REFUSED. There is deliberately
            no fallback to the parent's — reassigning a first-sighting centroid
            to a child is the first thing the SPEC forbids, and it is the one
            an obliging `or parent_centroid` would introduce in one keystroke;
          * nothing is auto-clustered: the remainder is left alone and the next
            see-run re-observes it;
          * nothing on disk is moved or deleted, and the parent's own draft
            vector stays where it is — `save()` never unlinks one.

        ## The refusals that keep `superseded` safe — THREE, not one

        A superseded record sits outside BOTH status whitelists, which is what
        buys it a free exit from the question loop. The price is that
        `photo_plan.py:132` renders a name whenever the record holds one and
        `is_draft` is false — so a NAMED parent would print as a confirmed
        `who` with no `draft:` marker, which is OA-15's silent-failure class
        one layer down. Every other name-rendering reader (`subject_display`,
        `forms_own_folder`, `--sync`, the name budget,
        `photo_recurrence.subject_folder()`) gates on the name too.

        ⚠️ This method's own refusals — a parent that holds a name, and one
        that is not a draft (splitting a CONFIRMED subject is SNS-14, not
        this) — cover only the moment of the split. They are NOT the whole
        invariant, and an earlier draft of this docstring claimed they were.
        A name reaches a record through two other doors, both gated
        separately and both required:

          * `rename()` writes a name on any status it is handed;
          * `photo_memory.cmd_confirm()` writes `name` + `human-confirmed`
            (and, on the `skip:` path, `rejected`) on any id a review file
            names — and a review rendered BEFORE the split still names the
            parent and still parses. ⚠️ SNS-1b item 1's pinned-pack-snapshot
            check is built (`photo_memory.pinned_snapshot()`) and catches the
            ordinary case, since a split moves the pack; it does not close
            this door, because it compares the pack as a whole and only when
            the page pinned an id — a hand-written table, an edited header or
            `--sync` reaches those writes with the check silent.

        Resurrecting a parent is worse than a bad label: with exemplars it
        re-enters `recognisers` holding the same looks as its children and
        competes with them in `match()`. Any future writer of `name` or
        `status` inherits this obligation — the mint-time check below cannot
        discharge it.

        Refusals raise and write nothing at all. A partition applied to half
        its rows would leave the owner's answer split between a record that
        moved and rows that did not, which no later reader could tell from a
        deliberate outcome."""
        parent, prepared, claimed, single, why, gate = self._partition_plan(
            subject_id, groups)
        base = {"subject_id": subject_id, "decision": "superseded", "by": by,
                "reason": reason, "at": datetime.now().strftime("%Y-%m-%d")}
        if why:
            # ⛔ The audit is written HERE and not in the plan, which is what
            # keeps `partition_refusal()` free of side effects: a dry run asks
            # what this would say, and asking must not move the pack.
            self.audit({**base, "decision": "refused", "gate": gate,
                        "reason": why})
            raise ValueError(why)
        if single is not None:
            return single
        return self._perform_partition(parent, prepared, claimed, base, by,
                                       reason)

    def partition_refusal(self, subject_id, groups):
        """-> the sentence `partition_subject()` would refuse this partition
        with, or None. Nothing is written and nothing is audited.

        ⭐ Step 9, item 2, and it exists for the reason `fold_refusal()` and
        `rename_refusal()` do: the verb audits at the decision point, so it
        runs under `--go` only, and a dry run that cannot ask it predicts a
        split the `--go` then refuses. Measured 2026-08-20 as `21 change(s)
        would be written, 0 refused` followed by `wrote 0 change(s), 1
        refused` — the owner is told the answer is fine, and then it is not.

        ⛔ ONE set of gates, read from here by both callers rather than copied
        into the dry run. A second copy drifts, and it drifts silently: the
        dry run is exactly the path no `--go` result comes back from."""
        return self._partition_plan(subject_id, groups)[4]

    def _partition_plan(self, subject_id, groups):
        """Every gate `partition_subject()` takes, decided and NOTHING
        written. -> (parent, prepared rows, claimed frames, the one-row result
        or None, why, gate)."""
        import numpy as np

        # LITERAL — `not parent.is_draft` below is the first refusal, and a
        # resolving fetch would supersede the WINNER of a fold when the caller
        # named an alias, minting children off a confirmed subject's looks.
        parent = self.get_literal(subject_id)
        if parent is None:
            raise ValueError(f"no such subject: {subject_id}")

        def refuse(gate, why):
            return (parent, None, None, None, why, gate)

        # Status before name, so a CONFIRMED subject hears about SNS-14 rather
        # than about a name it was always going to hold.
        if not parent.is_draft:
            return refuse("status", (
                f"{subject_id} is {parent.status}, not a draft — a partition "
                "is what an owner does to a cluster nobody has identified "
                "yet. Two CONFIRMED subjects that turn out to be ONE is "
                "SNS-14's fold (`fold_subjects()`, typed as `name: <the other "
                "name> same`); one that turns out to be TWO is still not "
                "built — withdraw the name first, and the draft it becomes is "
                "partitionable."))
        if parent.name:
            return refuse("named", (
                f"{subject_id} holds the name {parent.name!r} and may not be "
                f"{STATUS_SUPERSEDED}. That status is outside both whitelists, "
                "so a reader asking `name and not is_draft` would print this "
                "name as a confirmed answer with no `draft:` marker on it. "
                "Withdraw the name first (`unconfirm`), or split the drafts "
                "under it."))

        rows = [dict(group) for group in groups]
        if not rows:
            return refuse("groups",
                          f"{subject_id}: a partition needs at least one "
                          "pick row; nothing was decided about it")

        held = self._looks_by_ref(parent.record)
        claimed, prepared = {}, []
        for n, row in enumerate(rows, 1):
            refs = list(dict.fromkeys(row.get("vec_refs") or []))
            if not refs:
                return refuse("frames",
                              f"{subject_id}: pick row {n} names no frame of "
                              "this subject — an empty row decides nothing "
                              "and must not reach the storage")
            for ref in refs:
                if ref not in held:
                    return refuse("frames", (
                        f"{subject_id}: pick row {n} names {ref}, which no look "
                        "on this subject carries. The frame belongs to another "
                        "subject, or the observation behind it is gone — either "
                        "way this is not a partition of THIS record"))
                if ref in claimed:
                    return refuse("frames", (
                        f"{subject_id}: {ref} is picked by rows {claimed[ref]} "
                        f"and {n}. One frame is one photograph of one subject; "
                        "two rows claiming it is a question, not a partition"))
                claimed[ref] = n
            row["vec_refs"] = refs
            prepared.append(row)

        if len(prepared) == 1:
            row = prepared[0]
            shared = sorted(row.get("shared_with") or [])
            # Cases A and B write NOTHING here. They are still answered by this
            # method rather than by the caller's own `if`, so the rows are
            # validated against the record once, in one place, whichever case
            # they turn out to be.
            return parent, prepared, claimed, {
                    "subject_id": subject_id,
                    "case": "shared" if shared else "in-place",
                    "children": [], "shared_with": shared,
                    "vec_refs": list(row["vec_refs"]),
                    "why": ("one pick row, so this subject keeps its id and is "
                            "confirmed where it stands"
                            + (f" alongside {', '.join(shared)}" if shared
                               else "; frames it did not pick are deferred, "
                                    "not rejected"))}, None, None

        parent_centroid = self.draft_centroid(subject_id)
        # Card 6 F-o: EVERY such row is named in the one refusal. It used to
        # return at the first, so an owner fixed row 1 and was refused again
        # for row 2 on the next try (UAT02-02, P-B07: the Birk row had the
        # Lotus row's shape and was never looked at). The gate is unchanged.
        bad = [(n, sorted(row["shared_with"]))
               for n, row in enumerate(prepared, 1) if row.get("shared_with")]
        for n, row in enumerate(prepared, 1):
            if bad:
                # Case B and case C on the SAME row: this row splits the parent
                # AND names another subject. Refused rather than accepted with
                # the sharing dropped — a caller that passed it believed it was
                # saying something, and a set that quietly shrinks is how a
                # split loses frames.
                #
                # ⭐ OA-19, decided 2026-08-22: such a row means NOTHING NEW and
                # stays refused BY DESIGN. There is no third case to build. The
                # two halves want opposite things from the storage, and no
                # reading of the row picks between them without inventing the
                # owner's intent — so the owner writes the two halves as two
                # rows, which the message below asks for by row number.
                # ⛔ Not a pending decision: do not "resolve" this by making the
                # call succeed.
                #
                # ⭐ Doc 8 amendment (a), 2026-08-27, changes the MESSAGE and
                # not this gate: the two rows may now carry the SAME name, so
                # "say it as two rows" no longer sends an owner whose answer is
                # one subject into a name-collision refusal that sends them
                # back here (D6). The row itself stays refused.
                rows_said = "; ".join(
                    f"pick row {m} both splits this subject and names "
                    f"{', '.join(o)}" for m, o in bad)
                which = (f"row {bad[0][0]}" if len(bad) == 1 else
                         "rows " + ", ".join(str(m) for m, _o in bad))
                others = ", ".join(sorted({x for _m, o in bad for x in o}))
                return refuse("shared", (
                    f"{subject_id}: {rows_said}. A split "
                    "child is a new id and a shared row keeps the ids it names "
                    "— which of those the row wants is a question the storage "
                    "may not answer for it. Say each as TWO rows: leave "
                    f"{which} picking only its frames of {subject_id}, so the "
                    "split writes one child per row; then put the naming of "
                    f"{others} on a row of its own, which keeps those ids as "
                    "they are. Both rows belong in the SAME answer — copy a "
                    "blank row if the page does not offer enough of them. And "
                    "if the two rows are about the SAME one, write the same "
                    "name on both: a row that splits and a row that names may "
                    "share a name inside one answer, and what you get is one "
                    "subject over the ids they name"))
            centroid = row.get("centroid")
            if centroid is None:
                return refuse("centroid", (
                    f"{subject_id}: pick row {n} arrives with no centroid. A "
                    "child's identity vector is computed from the frames that "
                    "row picked and passed in — the parent's is a FIRST "
                    "SIGHTING of a cluster this split just disproved, and "
                    "reassigning it is the first thing SNS-1b forbids"))
            vec = np.asarray(centroid, dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(vec))
            if norm < 0.5:
                return refuse("centroid",
                              f"{subject_id}: pick row {n} has no usable "
                              f"centroid (norm {norm:.3f})")
            if parent_centroid is not None and vec.shape != parent_centroid.shape:
                return refuse("centroid", (
                    f"{subject_id}: pick row {n}'s centroid is {vec.shape[0]}-d "
                    f"where this subject's is {parent_centroid.shape[0]}-d — "
                    "vectors from two models are not comparable"))
            row["centroid"] = vec / norm

        return parent, prepared, claimed, None, None, None

    def _perform_partition(self, parent, prepared, claimed, base, by, reason):
        """The record surgery, once every gate in `_partition_plan()` has
        passed. Split by split, this is `partition_subject()`'s second half —
        separated so the first half can be asked as a question."""
        subject_id = parent.subject_id
        held = self._looks_by_ref(parent.record)
        children = []
        for n, row in enumerate(prepared, 1):
            refs = set(row["vec_refs"])
            looks = [held[ref] for ref in row["vec_refs"]]
            child = self.create_subject(
                kind=parent.kind, status=STATUS_DRAFT,
                origin={"split_from": subject_id, "pick_row": n,
                        "frames": list(row["vec_refs"]), "at": base["at"],
                        "by": by})
            record = child.record
            record["evidence"] = self._inherit_evidence(parent.record, refs)
            # Bookkeeping about what this child was actually seen in, and
            # nothing about what the parent's cluster claimed. `files` is the
            # frame count, which is the only number a human has looked at.
            record["files"] = len(looks)
            record["obs_count"] = len(record["evidence"])
            record["observed_in"] = sorted(
                {entry["batch"] for entry in record["evidence"]
                 if entry.get("batch") is not None})
            samples = {look.get("sample") for look in looks if look.get("sample")}
            record["contact_sheet"] = [
                item for item in (parent.record.get("contact_sheet") or [])
                if Path(item).name in samples]
            # Derived from this group's OWN capture dates, never copied: the
            # parent's range spans frames that went to the other child. With no
            # capture date on any of them the range stays open, and
            # `forms_own_folder()` therefore stays false even once the caller
            # names this child — a folder claimed on a range nobody observed
            # would be a fact invented here.
            months = sorted({str(look["captured"])[:7] for look in looks
                             if look.get("captured")})
            record["active"] = [months[0], months[-1]] if months else [None, None]
            self._draft_vectors[child.subject_id] = row["centroid"]
            children.append(child)

        ids = [child.subject_id for child in children]
        parent.record["status"] = STATUS_SUPERSEDED
        parent.record["split_into"] = list(ids)
        parent.record["superseded"] = {"at": base["at"], "by": by,
                                       "reason": reason, "into": list(ids),
                                       "frames": sorted(claimed)}
        result = {"subject_id": subject_id, "case": "split",
                  "children": [{"subject_id": child.subject_id,
                                "vec_refs": list(row["vec_refs"]),
                                "files": child.record["files"],
                                "active": list(child.record["active"]),
                                "frames_on_sheet": len(child.record["contact_sheet"])}
                               for child, row in zip(children, prepared)],
                  "kind": parent.kind,
                  "why": (f"{len(prepared)} pick rows claimed this draft's "
                          "frames, so it is superseded by one child per row; "
                          "its files inherit nothing and re-earn a name per "
                          "file")}
        self.audit({**base, "split_into": ids,
                    "children": result["children"], "reason": reason})
        return result

    # -- matching ----------------------------------------------------------

    @property
    def recognisers(self):
        """The subjects that may put a name on a file: `human-confirmed` AND
        holding exemplars. ONE definition, used by `match()` and by the see
        stage's report, so "the registry can recognise something" means the
        same thing in both places.

        ⚠️ **Status is half the test, and it is the half that looks
        redundant.** Filtering on exemplars alone was the rule until un-confirm
        existed, and it reads as sufficient because only a confirm ever
        promoted one. A WITHDRAWN subject breaks that: the owner's decision
        (2026-08-16) keeps its exemplars on the record so re-confirming stays
        cheap, which means evidence outlives the yes that made it evidence.
        A filter on evidence alone would therefore keep attributing files to
        an identity the owner took back — silently, because the vectors are
        real and the scores are good. `confirmed_match()` has always tested
        status for the neighbouring decision; this is the same posture."""
        return [s for s in self.subjects
                if s.status == STATUS_CONFIRMED and s.exemplars]

    def match(self, X, dates, identity=None, X_identity=None,
              identity_space=None):
        """Recognition Level 2 -> one verdict per row (or None).

        `dates` are the files' OWN capture datetimes, in the same order as X.
        An empty registry returns Nones without importing numpy or touching
        the disk: no registry means "no subject" is UNKNOWN, not false.

        Only `recognisers` are scored — see there for why the status test is
        not redundant with the exemplar test.

        ## Two spaces, decided per FILE (VS-3b)

        `X_identity` is the optional identity-space matrix, same row order as
        `X`, from `photo_identity.py`. A row is scored in the identity space
        when THAT ROW has an identity vector AND at least one eligible subject
        has identity exemplars; otherwise it falls back to the CLIP space
        exactly as before. Every verdict names the `space` it was decided in,
        because the two carry different bars and a reader comparing scores
        across them would be comparing nothing.

        ⛔ Per file, never per run. A dump holds photographs with no animal in
        them at all, and those legitimately have no identity vector; deciding
        the space once for the whole batch would either drop them from
        matching or drag every animal photo back into the CLIP space to keep
        them company.

        ⚠️ The fallback is a real answer, not a degraded one — but it is the
        answer the 20260821 measurement showed cannot recognise a subject
        across sessions. A run with no identity index gets the old behaviour
        and the old result; that is why `space` is reported rather than
        assumed."""
        n = 0 if X is None else len(X)
        if not self.subjects or not n:
            return [None] * n
        self.assert_identity(identity)
        self.assert_identity_space(identity_space)

        import numpy as np

        usable = self.recognisers
        vectors = {s.subject_id: self.vectors_for(s.subject_id) for s in usable}
        id_usable = self.identity_recognisers if X_identity is not None else []
        id_vectors = {s.subject_id: self.identity_vectors_for(s.subject_id)
                      for s in id_usable}
        out = []
        for i in range(n):
            when = dates[i] if i < len(dates) else None
            row_id = X_identity[i] if X_identity is not None and i < len(X_identity) \
                else None
            # A zero row is photo_identity's "no subject in this frame" — a
            # positive statement, and not something to score.
            has_id = row_id is not None and float(np.linalg.norm(row_id)) >= 0.5
            if has_id and id_usable:
                scored = []
                for s in id_usable:
                    if not s.eligible_at(when):
                        continue
                    V = id_vectors[s.subject_id]
                    if V is None or not len(V):
                        continue
                    scored.append((float(np.max(V @ row_id)), s))
                scored.sort(key=lambda t: (-t[0], t[1].subject_id))
                out.append(self._verdict_identity(scored))
                continue
            scored = []
            for s in usable:
                if not s.eligible_at(when):
                    continue
                V = vectors[s.subject_id]
                if V is None or not len(V):
                    continue
                scored.append((float(np.max(V @ X[i])), s))
            scored.sort(key=lambda t: (-t[0], t[1].subject_id))
            out.append(self._verdict(scored))
        return out

    def _verdict_identity(self, scored):
        """The identity space's verdict: a FLOOR and a MARGIN over the
        runner-up, where the CLIP space uses one absolute cosine.

        ⭐ Relative, and measured that way. In the identity space a true
        sighting scores far above every impostor but nowhere near 1.0, so a
        fixed bar high enough to exclude impostors excludes almost every true
        sighting too. What separates them is the SHAPE of the ranking: the
        right subject leads by a wide margin, a wrong one leads by almost
        nothing. Both halves are load-bearing — the floor alone names a stray
        animal after whichever subject holds the largest bank, and the margin
        alone does the same whenever only one subject is eligible.

        A leader that clears the floor but not the margin is a QUESTION, not a
        near-miss: two subjects this close is cardinality, which is never
        auto-resolved. A leader under the floor is GRAY when it is within
        reach of it and NONE below that — the gray band is what puts the file
        in front of a human at the next round.
        """
        if not scored:
            return {"subject_id": None, "name": None, "kind": None, "score": None,
                    "verdict": VERDICT_NONE, "eligible": 0, "runner_up": None,
                    "question": None, "space": "identity",
                    "why": "no subject with identity exemplars is eligible at "
                           "this file's own capture date"}
        score, subject = scored[0]
        floor = subject.threshold("identity_floor")
        margin = subject.threshold("identity_margin")
        runner = ({"subject_id": scored[1][1].subject_id,
                   "score": round(scored[1][0], 4)} if len(scored) > 1 else None)
        lead = score - scored[1][0] if len(scored) > 1 else score
        question = None
        if score < floor:
            # One band below the floor, sized like the CLIP space's gray band
            # relative to its own bar, so "nearly" means the same kind of thing
            # in both: close enough that a human should look, not close enough
            # to claim.
            verdict = VERDICT_GRAY if score >= floor * (GRAY_LOW_RATIO) else VERDICT_NONE
        elif lead >= margin or len(scored) == 1:
            # One eligible subject has no runner-up to lead, so `lead` is the
            # score itself and the margin test is vacuous — the floor above is
            # the whole decision. Spelled out because a pack MAY set a
            # per-subject `identity_margin` above its `identity_floor`, and
            # without this that pack would index scored[1] on a list of one.
            verdict = VERDICT_ACCEPT
        else:
            verdict = VERDICT_QUESTION
            question = cardinality_question(
                [scored[0][1].subject_id, scored[1][1].subject_id],
                scores=[round(scored[0][0], 4), round(scored[1][0], 4)])
        return {"subject_id": subject.subject_id, "name": subject.name,
                "kind": subject.kind, "score": round(score, 4),
                "verdict": verdict, "eligible": len(scored), "runner_up": runner,
                "question": question, "space": "identity",
                "lead": round(lead, 4),
                "why": f"identity_floor {floor}, identity_margin {margin} "
                       f"(starting values); leads the runner-up by {lead:.3f}"}

    def _verdict(self, scored):
        if not scored:
            return {"subject_id": None, "name": None, "kind": None, "score": None,
                    "verdict": VERDICT_NONE, "eligible": 0, "runner_up": None,
                    "question": None, "space": "clip",
                    "why": "no subject is eligible at this file's own capture date"}
        score, subject = scored[0]
        accept, gray_low = subject.threshold("accept"), subject.threshold("gray_low")
        runner = ({"subject_id": scored[1][1].subject_id,
                   "score": round(scored[1][0], 4)} if len(scored) > 1 else None)
        verdict = (VERDICT_ACCEPT if score >= accept
                   else VERDICT_GRAY if score >= gray_low else VERDICT_NONE)
        question = None
        if (verdict == VERDICT_ACCEPT and len(scored) > 1
                and scored[1][0] >= scored[1][1].threshold("accept")
                and score - scored[1][0] <= AMBIGUITY_MARGIN):
            # Two subjects, both accepted, indistinguishable. Cardinality is
            # never auto-resolved — this becomes a question, not a ranking.
            verdict = VERDICT_QUESTION
            question = cardinality_question(
                [scored[0][1].subject_id, scored[1][1].subject_id],
                scores=[round(scored[0][0], 4), round(scored[1][0], 4)])
        return {"subject_id": subject.subject_id, "name": subject.name,
                "kind": subject.kind, "score": round(score, 4),
                "verdict": verdict, "eligible": len(scored), "runner_up": runner,
                "question": question, "space": "clip",
                "why": f"accept {accept}, gray_low {gray_low} (starting values)"}

    # -- N-10a keying (this module is photo_recurrence's caller) -----------

    def folder_for(self, subject_id, period, fallback_word=None, candidate=None):
        """The folder record for one recurring-subject / D9 folder, keyed on
        subject identity rather than on the rendered name (N-10a). The keying
        itself lives in `photo_recurrence.subject_folder()`, next to the
        pre-confirmation identity it also has to accept; this is the caller
        that holds a confirmed registry entry."""
        import photo_recurrence

        # RESOLVED, and one of only two sites that want it. The id arrives off
        # a folder record or a plan that may predate a fold, and what the
        # folder must be keyed and rendered on is the subject it now MEANS —
        # SNS-14's "N-10a holds across the fold", bought here for free.
        subject = self.get(subject_id)
        return photo_recurrence.subject_folder(
            period, candidate=candidate,
            registry_entry=subject.record if subject else None,
            fallback_word=fallback_word)

    def rename_ledger(self):
        """N-6's ledger: every rendered name a subject has ever had -> its
        identity, so a tree sorted before a rename still resolves after it.

        ⭐ **One name can be claimed by more than one record, and the winner is
        chosen by a STATED PRECEDENCE — never by iteration order.** This used
        to be last-writer-wins over `self.subjects`, so a name held by both a
        dead record (a superseded parent, a rejection, an absorbed draft, a
        fold's tombstone) and a live one resolved to whichever happened to sit
        later in the file. The folder that name is on would then be keyed to a
        record that recognises nothing — silently, and differently after any
        edit that reordered the list.

        Three tiers, applied in order, lowest wins:

          1. **a CURRENT `name` beats a `previous_names`-only claim.** The
             common collision is not two live names — a withdrawal moves the
             name to `previous_names` — it is one record still holding the name
             and another that used to;
          2. **a live record beats a dead one.** Live is `ai-drafted` /
             `ai-reinforced` / `human-confirmed`; dead is everything else. A
             fold's tombstone is judged on the record it RESOLVES to, because
             its claim is really the winner's (SNS-14: N-10a holds across the
             fold);
          3. **the lower `subject_id`**, so two records with the same standing
             resolve the same way on every run and in every file order.
        """
        ranked = {}
        for subject in self.subjects:
            target = self.resolve_merged(subject.subject_id) or subject
            live = 0 if target.status in (STATUS_DRAFT, STATUS_REINFORCED,
                                          STATUS_CONFIRMED) else 1
            claims = [(name, 1) for name in subject.previous_names]
            if subject.name:
                claims.append((subject.name, 0))
            for name, current in claims:
                rank = (current, live, self._ordinal(target.subject_id))
                if name not in ranked or rank < ranked[name][0]:
                    ranked[name] = (rank, target.subject_id)
        return {name: target for name, (_rank, target) in ranked.items()}

    # -- SNS-15 / SNS-14: what a subject's totals READ as -------------------

    def display_files(self, subject):
        """How many files this subject accounts for, for a READER. -> int.

        ✅ **The owner's decision, 2026-08-19: absorbed counts aggregate at
        DISPLAY time,
        never in storage.** The stored `files` on each record stays exactly
        what it always was, and this adds them up on the way out:

          * the subject's own `files`;
          * every draft the post-confirm sweep absorbed into it
            (`absorbed_drafts`), which is a REVERSIBLE list —
            `release_absorbed()` pops it and this number goes back down by
            itself. A sum written into storage could never be separated again
            from the files that were always the subject's, which is why the
            clause that read as a stored sum was amended rather than built;
          * every subject FOLDED into it (SNS-14). A tombstone's own `files`
            is not a row in `absorbed_drafts` and must never be added as one —
            `release_absorbed()` would pop it and resurrect a folded subject as
            a draft — so it is counted here, from the tombstones themselves.
            Path compression is what makes that safe: after a chained fold
            every tombstone names the final winner, so nothing is counted
            twice.

        ⛔ Nothing here writes. A caller that wants the breakdown reads
        `review()`, which reports the three parts separately."""
        total = int(subject.record.get("files", 0))
        for row in subject.record.get("absorbed_drafts") or []:
            total += int(row.get("files", 0))
        for other in self.subjects:
            if other.status == STATUS_MERGED_INTO \
                    and other.record.get("merged_into") == subject.subject_id:
                total += int(other.record.get("files", 0))
        return total

    def display_files_ungated(self, subject):
        """How many of `display_files()` arrived through an UNGATED
        suppression — A19. -> int.

        Deliberately the same three parts on the same basis as
        `display_files`, so the two numbers can be shown side by side and a
        reader can subtract them. A different basis would produce a share that
        looks wrong without being wrong, which is worse than not reporting it.

        ⛔ Reads only. A record written before A19 has no `files_ungated` and
        contributes 0 — that is silence, NOT a claim that its sightings were
        gated. `within_timeline` on the evidence rows is where a reader tells
        those two apart."""
        total = int(subject.record.get("files_ungated", 0))
        for row in subject.record.get("absorbed_drafts") or []:
            total += int(row.get("files_ungated", 0))
        for other in self.subjects:
            if other.status == STATUS_MERGED_INTO \
                    and other.record.get("merged_into") == subject.subject_id:
                total += int(other.record.get("files_ungated", 0))
        return total

    # -- writing -----------------------------------------------------------

    def save(self):
        """Registry and vectors are written together — a record whose vectors
        are one edit behind scores against the wrong rows."""
        import numpy as np

        if self.dir is None:
            raise ValueError("this registry has no pack directory to save into")
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / VECTORS_DIRNAME).mkdir(exist_ok=True)
        for subject in self.subjects:
            path = self.vectors_path(subject.subject_id)
            arr = self._vectors.get(subject.subject_id)
            if arr is None:
                continue
            if len(subject.exemplars):
                np.save(path, np.asarray(arr, dtype=np.float32))
            elif path.exists():
                path.unlink()
        # Draft centroids sit in their own directory, not in vectors/. They are
        # dedupe keys, not recognition evidence, and a reader that cannot tell
        # the two apart is one edit away from matching on an unconfirmed guess.
        for subject_id, arr in sorted(self._draft_vectors.items()):
            if arr is None:
                continue
            path = self.draft_vectors_path(subject_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, np.asarray(arr, dtype=np.float32))
        # Identity vectors, keyed by vec_ref and PRUNED to what the record
        # still lists. The prune is the whole reason this store is a dict: an
        # exemplar the cap dropped must stop being scored, and a positional
        # array would have needed the same rows deleted in lock step with
        # `vectors/` to achieve it.
        if self._identity_pending:
            (self.dir / IDENTITY_VECTORS_DIRNAME).mkdir(exist_ok=True)
        for subject in self.subjects:
            pending = self._identity_pending.get(subject.subject_id)
            path = self.identity_vectors_path(subject.subject_id)
            if pending is None and not (path and path.exists()):
                continue
            stored = {}
            if path.exists():
                with np.load(path) as store:
                    stored = {k: store[k] for k in store.files}
            stored.update(pending or {})
            keep = {e["vec_ref"]: stored[e["vec_ref"]] for e in subject.exemplars
                    if e.get("vec_ref") in stored}
            if keep:
                path.parent.mkdir(parents=True, exist_ok=True)
                np.savez(path, **keep)
            elif path.exists():
                path.unlink()
        (self.dir / REGISTRY_NAME).write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")


# ------------------------------------------------------------------ load ----

def load(pack=None, workdir=None, explicit=None):
    """-> Registry. Resolved off the one pack this run may use
    (`photo_profile.resolve_pack`). No pack, or no `photo-subjects/` in it, is
    an EMPTY registry rather than an error: a run with no owner memory is
    legal and is what every benchmark run does."""
    if pack is None and (workdir or explicit):
        pack = photo_profile.resolve_pack(workdir=workdir, explicit=explicit)
    if pack is None or getattr(pack, "dir", None) is None:
        return Registry(source="no pack")
    directory = Path(pack.dir) / SUBJECTS_DIRNAME
    path = directory / REGISTRY_NAME
    if not path.exists():
        return Registry(directory=directory,
                        source=f"{path} does not exist yet")
    data = json.loads(path.read_text())
    return Registry(directory=directory, data=data, source=str(path))


# ------------------------------------------------------- the question ------

def group_coherence(frames, tau=None):
    """Do a draft group's own frames agree with EACH OTHER? (U2-12)

    `frames` is `[(key, vector), ...]` — one entry per frame that has an
    IDENTITY vector, `key` being whatever the caller wants named back (a frame
    number, a vec_ref). -> None when fewer than two frames carry one, else::

        {"pairs": int, "min": float, "worst": (key, key), "coherent": bool}

    ⭐ Why this exists. Every multi-animal warning this system had was about a
    single FRAME. A draft group is assembled by scoring each new sighting
    against the group's FIRST centroid and nothing else, so two frames can
    both sit within `draft_dedupe_tau` of that centroid while sitting nowhere
    near each other — and the owner is then asked to put ONE name on them. In
    the trial that found this, a group of 147 files across 5 batches held two
    different animals, and its only two single-animal frames were one of each:
    the tidiest evidence on the page was the most dangerous.

    ⛔ The comparison is frames AGAINST EACH OTHER, never each frame against
    the centroid. The centroid is one arbitrary member (the first sighting),
    so a group split evenly between two animals has a centroid sitting between
    them, near neither, and every frame looks equally mediocre against it. The
    pair that disagrees most is the finding, which is why `worst` is returned
    and not just a score.

    ⛔ IDENTITY vectors only. The CLIP space encodes the room as much as the
    animal, so two photographs of one cat in two rooms score low there and two
    cats on one sofa score high — it answers a different question, and using
    it here would flag the wrong groups confidently.

    ⚠️ This REPORTS; it never splits. `pick:` is how a group becomes two
    subjects, and that gesture belongs to the owner.
    """
    import numpy as np

    usable = [(key, np.asarray(vec, dtype=np.float32).reshape(-1))
              for key, vec in frames if vec is not None]
    usable = [(key, vec) for key, vec in usable
              if vec.size and float(np.linalg.norm(vec)) > 0.5]
    if len(usable) < 2:
        return None
    if tau is None:
        tau = DEFAULT_THRESHOLDS["group_coherence_tau"]
    unit = [(key, vec / float(np.linalg.norm(vec))) for key, vec in usable]
    worst_score, worst_pair, pairs = None, None, 0
    for i in range(len(unit)):
        for j in range(i + 1, len(unit)):
            pairs += 1
            score = float(unit[i][1] @ unit[j][1])
            if worst_score is None or score < worst_score:
                worst_score, worst_pair = score, (unit[i][0], unit[j][0])
    return {"pairs": pairs, "min": worst_score, "worst": worst_pair,
            "coherent": worst_score >= float(tau)}


def cardinality_question(subject_ids, scores=None, contact_sheet=None,
                         cluster_ids=None):
    """A structured "one subject or two?" record. Never a merge.

    A wrong merge mislabels both subjects forever and silently; a wrong split
    costs one extra question. Rendering this into a review table and writing
    it to photo-proposals.md is VS-4's memorize loop — this module only has to
    produce the record and take no action on it."""
    return {
        "kind": "cardinality",
        "question": "one subject or two?",
        "subject_ids": sorted(subject_ids),
        "cluster_ids": sorted(cluster_ids) if cluster_ids else [],
        "scores": list(scores or []),
        "contact_sheet": sorted(contact_sheet or []),
        "auto_merge": False,
        "resolved_by": "human",
    }


# The cluster-pair form of the same question — two in-batch clusters that look
# like each other, before either is a named subject — belongs to VS-4's
# memorize loop, which is what discovers unmatched clusters and writes them to
# photo-proposals.md. It is not built here: nothing in VS-3 would call it, and
# a primitive with no production caller is the "no speculative abstractions"
# line in CLAUDE.md — the same reason the N-10a keying was reverted at VS-2 and
# only restored here once `folder_for()` existed to consume it.


# ------------------------------------------------------------------- CLI ----

def review(registry):
    """-> a plain dict of what the store holds, for a human or for --json."""
    subjects = []
    for s in registry.subjects:
        provenance = {}
        for e in s.exemplars:
            key = normalize_provenance(e.get("confirmed_by")) or "none"
            provenance[key] = provenance.get(key, 0) + 1
        # The read-time sum, BROKEN OUT rather than reported as one number.
        # Operator view, so it is plain English keys and no i18n: the owner's
        # page shows the total (`review_remembered_line`), and the person
        # debugging a count needs to see which part of it came from where.
        absorbed = s.record.get("absorbed_drafts") or []
        merged_in = sorted(o.subject_id for o in registry.subjects
                           if o.status == STATUS_MERGED_INTO
                           and o.record.get("merged_into") == s.subject_id)
        subjects.append({
            "subject_id": s.subject_id, "name": s.name, "who": s.who,
            "kind": s.kind, "active": s.record.get("active"),
            "files": int(s.record.get("files", 0)),
            "display_files": registry.display_files(s),
            "absorbed": len(absorbed),
            "absorbed_files": sum(int(r.get("files", 0)) for r in absorbed),
            "merged_into": s.record.get("merged_into"),
            "merged_in": merged_in,
            "status": s.status, "obs_count": s.obs_count,
            "observed_in": s.observed_in,
            "exemplars": len(s.exemplars), "cap": int(s.threshold("exemplar_cap")),
            "provenance": provenance,
            "forms_own_folder": s.forms_own_folder(),
            "thresholds": {k: s.threshold(k) for k in
                           ("accept", "gray_low", "timeline_tolerance_days")},
            "previous_names": s.previous_names,
            # FIX7 (U7-2) — the ids the repair verbs take: a draft id for
            # `--detach`, a vec_ref for `--prune --drop`, each beside the
            # photo it stands for.
            "absorbed_drafts": [registry.absorbed_listing(r.get("subject_id"))
                                for r in absorbed],
            "exemplar_refs": [{"vec_ref": e.get("vec_ref"),
                               "file": Path(e.get("source") or "").name or None}
                              for e in s.exemplars],
        })
    trail = registry.audit_trail()
    return {"source": registry.source, "subjects": subjects,
            "count": len(subjects),
            "drafts": sum(1 for s in registry.subjects if s.is_draft),
            "embedding_identity": registry.embedding_identity,
            "defaults": registry.defaults,
            "memorize_audit": {
                "path": str(registry.audit_path) if registry.audit_path else None,
                "entries": len(trail),
                "memorized": sum(1 for r in trail if r.get("decision") == "memorized"),
                "refused": sum(1 for r in trail if r.get("decision") == "refused"),
                "refused_gates": sorted({r.get("gate") for r in trail
                                         if r.get("decision") == "refused"
                                         and r.get("gate")}),
                "exemplars_without_evidence": sum(
                    1 for s in registry.subjects for e in s.exemplars
                    if not e.get("evidence")),
                "note": ("every exemplar in this pack should appear as a "
                         "`memorized` line naming the see-report, batch and "
                         "thumbnail that confirmed it. Exemplars written before "
                         "VS-4 carry no evidence block and are counted above."),
            }}


def print_review(report):
    print(f"subject registry: {report['source']}")
    print(f"{report['count']} subject(s)")
    if not report["subjects"]:
        print("  (empty — the engine ships no subjects; they arrive from "
              "vision-confirmed picks at a memory checkpoint)")
        return
    for s in report["subjects"]:
        active = s["active"] or [None, None]
        print(f"  {s['subject_id']}  {s['name'] or '(unnamed draft)'}"
              f"  who={s['who'] or '-'} kind={s['kind'] or '-'}"
              f"  active={active[0] or '-'}..{active[1] or 'open'}")
        print(f"      exemplars {s['exemplars']}/{s['cap']}  {s['provenance']}"
              f"  own folder: {'yes' if s['forms_own_folder'] else 'no'}")
        print(f"      status {s['status']}  obs_count {s['obs_count']}"
              f"  batches {len(s['observed_in'])}")
        # Said only when the two disagree, and said as a SUM rather than as a
        # total: a number the owner sees on the page has to be traceable back
        # to the records it came from, and "28" on its own is not.
        if s["display_files"] != s["files"]:
            parts = [f"{s['files']} its own"]
            if s["absorbed"]:
                parts.append(f"{s['absorbed_files']} from {s['absorbed']} "
                             "absorbed draft(s)")
            if s["merged_in"]:
                parts.append(f"{s['display_files'] - s['files'] - s['absorbed_files']}"
                             f" from {len(s['merged_in'])} folded subject(s): "
                             + ", ".join(s["merged_in"]))
            print(f"      files {s['display_files']} = " + " + ".join(parts))
        elif s["files"]:
            print(f"      files {s['files']}")
        if s["merged_into"]:
            print(f"      folded into {s['merged_into']} — an alias, kept so "
                  "older folders and plan rows still resolve")
        if s["previous_names"]:
            print(f"      previously: {', '.join(s['previous_names'])}")
        for d in s.get("absorbed_drafts") or []:
            crops = d["crops"]
            print(f"      absorbed draft {d['subject_id']}: "
                  f"{', '.join(d['files']) or '(no photo on record)'}"
                  + (f"  crop: {crops[0]}" if crops else "")
                  + (f" (+{len(crops) - 1} more in --json)" if len(crops) > 1 else ""))
        for e in s.get("exemplar_refs") or []:
            print(f"      exemplar {(e['vec_ref'] or '-')[:12]}  {e['file'] or '-'}")
    audit = report["memorize_audit"]
    print(f"memorize audit: {audit['entries']} decision(s) — "
          f"{audit['memorized']} memorized, {audit['refused']} refused"
          + (f" ({', '.join(audit['refused_gates'])})" if audit["refused_gates"]
             else ""))
    if audit["exemplars_without_evidence"]:
        print(f"  ⚠️  {audit['exemplars_without_evidence']} exemplar(s) carry no "
              "evidence block — written before VS-4, unprovable from this log")


# FIX7 (U7-3) — measured on the UAT01-7 end state with the pet withdrawn:
# `photo_index.py check` failed with 34 problems, every one an agent agree
# resting on the withdrawn subject. Said, not changed.
# FIX7 — the shortest `--drop` prefix that is allowed to stand for a vec_ref.
# `review` prints 12; fewer than this many characters of a content sha is a
# guess, whatever it happens to match today.
MIN_DROP_PREFIX = 8

UNCONFIRM_CHECK_NOTE = (
    "      ⚠️  any folder named from an agent `identify` agree on this subject "
    "fails `photo_index.py check` until the subject is confirmed again")


# `photo_memory.CROP_DIR`, where a review page renders each animal's crop.
# Spelled here because photo_memory imports this module; a case asserts the
# two agree.
CROP_DIR = "review-crops"


def look_crop(look):
    """-> a picture of one look an owner can open: the animal crop a review
    page rendered (`<work dir>/review-crops/<vec_ref>_d0.jpg`), else the see
    stage's thumbnail, else None."""
    ref, workdir = look.get("vec_ref"), look.get("workdir")
    if ref and workdir:
        crop = Path(workdir) / CROP_DIR / f"{ref}_d0.jpg"
        if crop.is_file():
            return str(crop)
    if look.get("see_report") and look.get("sample"):
        thumb = Path(look["see_report"]).parent / "samples" / look["sample"]
        if thumb.is_file():
            return str(thumb)
    return None


def cmd_detach(registry, args, workdir):
    """FIX7 (U7-1) — `review --detach <draft-id> [--into <subject-id>]`.

    A `same` answer on a checkpoint writes the pet's id onto every photo the
    owner picked for that row, and render names the folder from that id. A
    wrong pick therefore kept the folder on the wrong pet after `--prune
    --drop`, which removes exemplars only (UAT01-7, LL-PHO-202). This puts
    back what those photos said before the join."""
    draft_id = args.detach
    refusal = registry.detach_refusal(draft_id, args.into)
    if refusal:
        # Exit 2 — a refusal, distinct from a break. Nothing was written.
        print(f"  ! --detach {draft_id}: {refusal}")
        sys.exit(2)
    from_id = registry.get_literal(draft_id).record["absorbed_by"]
    # Lazy, for the reason --unconfirm imports photo_memory lazily: the
    # see-label half is `photo_see`'s to write, and it imports this module.
    import photo_see

    looks = registry.picked_looks(draft_id)
    replaced = {row.get("path"): row.get("replaced")
                for row in registry.audit_trail()
                if row.get("decision") == "see-label replaced"
                and row.get("subject_id") == from_id}
    out = photo_see.restore_detached_subject_ids(
        looks, from_id, draft_id, into=args.into, replaced=replaced,
        workdir=workdir, dry_run=not args.go)
    verb = "restored" if args.go else "would restore"
    print(f"  {draft_id}: detach from {from_id}"
          + (f", into {args.into}" if args.into else ""))
    # F8-3 — said on both runs: a reason passed to a dry run that the output
    # never mentions reads as dropped (UAT01-8 F6).
    print(f'      reason: "{args.reason}"' if args.reason else
          "      no --reason given — the audit row will record none")
    if not looks:
        print("      no photo was picked for this join, so no see-label "
              "carries its name")
    if out["restored"]:
        print(f"      {verb} {len(out['restored'])} photo(s) in see-labels:")
        for row in out["restored"]:
            print(f"        {row['labels']}  {Path(row['path']).name}: "
                  f"{row['old']} -> {row['new'] or '(no name)'} ({row['why']})")
    for row in out["moved_on"]:
        print(f"      ~ {Path(row['path']).name} now names {row['now']}, not "
              f"{from_id} — left as it is")
    for path in out["unresolved"]:
        print(f"      ⚠️  {path}: no see-label entry found for it — nothing "
              "restored")
    for path in out["outside_workdir"]:
        print(f"      ⛔ {path} is not inside the work dir — nothing restored "
              "there")
    refs = [look.get("vec_ref") for look in looks if look.get("vec_ref")]
    if args.go:
        registry.release_one(draft_id, by=args.by, reason=args.reason)
        # F8-4 — ONE end state. With --into the release is a step, not an
        # outcome: the join below absorbs the draft again (UAT01-8 F5).
        if args.into:
            print(f"      moved {draft_id} from {from_id} to {args.into}: it "
                  f"stays joined, now to {args.into}, and is not asked about "
                  "again")
        else:
            print(f"      released {draft_id} from {from_id}: it is a draft "
                  "again and is asked about at the next checkpoint")
        dropped = registry.drop_exemplars(from_id, refs)
        looks_removed = registry.remove_carried_evidence(from_id, draft_id, refs)
        print(f"      {from_id}: dropped {len(dropped)} exemplar(s) that join "
              f"memorized ({', '.join(r[:12] for r in dropped) or 'none'}), "
              f"removed {looks_removed} look(s) it carried into the evidence")
        # ONE row for the whole answer, and BEFORE an --into join: that join
        # writes its own `attached` row, which `picked_looks()` must read as
        # newer than this detach.
        registry.audit({
            "subject_id": draft_id, "decision": "detached", "from": from_id,
            "into": args.into, "vec_refs": refs,
            "see_labels": [{"path": r["path"], "old": r["old"], "new": r["new"]}
                           for r in out["restored"]],
            "exemplars_dropped": dropped, "evidence_looks_removed": looks_removed,
            "by": args.by, "reason": args.reason,
            "at": datetime.now().strftime("%Y-%m-%d")})
        if args.into:
            registry.attach_draft_to_subject(draft_id, args.into, refs,
                                             by=args.by, reason=args.reason)
            print("      no exemplar is memorized by a detach — a later "
                  "checkpoint can add one")
        registry.save()
        print("      run `photo_index.py render` again (then check and "
              "freeze): folder names change at render")
    else:
        # Every write --go makes, read off the same records and nothing
        # written: U7-3's rule that a dry run must not under-report.
        winner = registry.get_literal(from_id)
        dropping = [r for r in refs
                    if any(e.get("vec_ref") == r for e in winner.exemplars)]
        carried = registry.remove_carried_evidence(from_id, draft_id, refs,
                                                   dry_run=True)
        if args.into:
            print(f"      would move {draft_id} from {from_id} to {args.into}: "
                  f"it stays joined, now to {args.into}, and is not asked "
                  "about again")
        else:
            print(f"      would release {draft_id} from {from_id}: it becomes "
                  "a draft again and is asked about at the next checkpoint")
        print(f"      {from_id}: would drop {len(dropping)} exemplar(s) that "
              f"join memorized ({', '.join(r[:12] for r in dropping) or 'none'}), "
              f"and remove {carried} look(s) it carried into the evidence")
        if args.into:
            print(f"      {args.into}: would carry {len(refs)} look(s); no "
                  "exemplar is memorized by a detach")
        print(f"      would write one `detached` row to {registry.audit_path} "
              f"and save {registry.dir / REGISTRY_NAME}")
        print("dry run — re-run with --go.")


def workspace_dir():
    """The collection workspace, when this was run from inside one.

    D-25. `review` resolves its pack through the work dir it is handed, so with
    no work dir it had no collection.json to read and reported "no owner pack"
    from the very folder `photo-init` tells the owner to stand in. The repair
    is the one `photo_run.default_workdir_root` already makes: a workspace is
    self-locating. ⛔ Not a new binding route — the three routes are unchanged;
    this only lets the collection.json route be reached without the owner
    knowing to name a work dir. Returns None off a workspace, which leaves the
    old behaviour (and the fail-closed refusal) exactly as it was.
    """
    for cand in (Path.cwd() / "Working Files", Path.cwd()):
        if (cand / "collection.json").exists():
            return cand
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    rv = sub.add_parser("review", help="list what the registry holds; prune it")
    rv.add_argument("workdir", nargs="?", help="a work dir, to resolve the "
                                               "collection's owner pack")
    rv.add_argument("--profile", help="owner pack (else collection.json / "
                                      "PHOTO_PROFILE)")
    rv.add_argument("--prune", action="store_true",
                    help="apply the exemplar cap (and --drop) — a dry run "
                         "unless --go")
    rv.add_argument("--drop", nargs="*", default=[],
                    help="vec_refs to remove, with --prune")
    rv.add_argument("--subject", nargs="*", help="limit --prune to these ids")
    rv.add_argument("--unconfirm", nargs="*", default=[],
                    help="withdraw these subjects' confirmations: they become "
                         "drafts and are asked about again — a dry run unless "
                         "--go")
    rv.add_argument("--revive", nargs="*", default=[],
                    help="take back these subjects' rejections: they become "
                         "drafts and are asked about again — a dry run unless "
                         "--go")
    rv.add_argument("--merge", nargs=2, metavar=("SOURCE_ID", "INTO_ID"),
                    help="SNS-14 — the owner says these two confirmed "
                         "subjects are one animal: SOURCE_ID becomes an alias "
                         "of INTO_ID — a dry run unless --go")
    rv.add_argument("--detach", metavar="DRAFT_ID",
                    help="take ONE draft a checkpoint joined to a pet back "
                         "out of it: the photos picked for that join stop "
                         "carrying the pet's name — a dry run unless --go")
    rv.add_argument("--into", metavar="SUBJECT_ID",
                    help="with --detach: the confirmed subject those photos "
                         "are instead")
    rv.add_argument("--by", default="Claude User",
                    help="self-declared operator, recorded not verified")
    rv.add_argument("--reason",
                    help="why, recorded with --detach/--unconfirm/--revive/"
                         "--merge")
    rv.add_argument("--go", action="store_true", help="write the changes")
    rv.add_argument("--json", help="write the report to this path")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve() if args.workdir else workspace_dir()
    pack = photo_profile.resolve_pack(workdir=workdir, explicit=args.profile)
    registry = load(pack=pack)
    if registry.dir is None:
        sys.exit("no owner pack for this run — the subject registry lives in the "
                 "pack (photo-subjects/). Bind a collection to an owner or pass "
                 "--profile; see docs/photo-memory-pack.md.")

    if args.unconfirm:
        withdrawn = []
        for subject_id in sorted(set(args.unconfirm)):
            # LITERAL — this pre-check exists to say the same thing
            # `unconfirm()` would say, so it has to read the same record the
            # verb will read. On a resolving fetch the operator would be told
            # what would happen to the winner.
            subject = registry.get_literal(subject_id)
            # The same three answers `unconfirm()` gives, given before it is
            # called: this loop prints and continues where the method raises,
            # so one unwithdrawable id must not abort the rest of the list.
            if subject is None or subject.is_draft \
                    or subject.status in (STATUS_SUPERSEDED,
                                          STATUS_MERGED_INTO):
                print(f"  ! {subject_id}: nothing to withdraw — "
                      + ("no such subject" if subject is None
                         else f"already {subject.status}"))
                continue
            if not args.go:
                # The withdrawal itself only runs under --go, because
                # `unconfirm()` audits at the decision point and a dry run that
                # wrote the audit log would move the pack snapshot — the same
                # rule photo_memory.confirm follows for promotion.
                print(f"  {subject_id}: would withdraw {subject.name!r}, "
                      f"returning the subject to the question loop; its "
                      f"{len(subject.exemplars)} exemplar(s) would be kept and "
                      "would attribute nothing until it is confirmed again")
                # FIX7 (U7-3) — what `release_absorbed()` will release, read
                # with its own two guards; only --go used to say it.
                releasing = []
                for row in subject.record.get("absorbed_drafts") or []:
                    child = registry.get_literal(row.get("subject_id"))
                    if (child is not None and child.status == STATUS_ABSORBED
                            and child.record.get("absorbed_by") == subject_id):
                        releasing.append(child.subject_id)
                if releasing:
                    print(f"      {len(releasing)} draft(s) joined or absorbed "
                          "under that name would be released and asked about "
                          "again: " + ", ".join(releasing))
                print(UNCONFIRM_CHECK_NOTE)
                continue
            withdrawn.append(registry.unconfirm(subject_id, by=args.by,
                                                reason=args.reason))
        if withdrawn:
            registry.save()
            # Lazy: photo_memory imports this module, and the pack-side half of
            # a withdrawal (the maturity line that re-opens the question, the
            # entities twin) is that module's to write.
            import photo_memory

            log, buckets = photo_memory.record_unconfirm(
                pack, withdrawn, by=args.by, reason=args.reason)
            for result in withdrawn:
                print(f"  {result['subject_id']}: withdrew "
                      f"{result['was'] or '(unnamed)'}, kept "
                      f"{len(result['exemplars_retained'])} exemplar(s) "
                      "(attributing nothing until it is confirmed again), "
                      f"draft centroid "
                      f"{'retained' if result['draft_centroid'] else 'ABSENT'}"
                      + (f", dropped from {buckets[result['subject_id']]}"
                         if result["subject_id"] in buckets else ""))
                if result.get("released_absorbed"):
                    print("      "
                          f"{len(result['released_absorbed'])} draft(s) the "
                          "post-confirm sweep had absorbed under that name are "
                          "released and asked about again: "
                          + ", ".join(result["released_absorbed"]))
                if not result["draft_centroid"]:
                    print("      ⚠️  no draft centroid on disk — this subject "
                          "is askable again but nothing re-recognises it "
                          "across batches until it is seen anew")
            print(UNCONFIRM_CHECK_NOTE)
            print(f"withdrew {len(withdrawn)} confirmation(s) -> {log}")
        elif args.unconfirm and not args.go:
            print("dry run — re-run with --go.")

    if args.revive:
        # OA-14's handle. Same shape as --unconfirm, one status along: print
        # and continue where the method raises, so one unrevivable id does not
        # abort the rest of the list.
        revived = []
        for subject_id in sorted(set(args.revive)):
            # LITERAL, for the reason the `--unconfirm` loop above is.
            subject = registry.get_literal(subject_id)
            if subject is None or subject.status != STATUS_REJECTED:
                print(f"  ! {subject_id}: nothing to revive — "
                      + ("no such subject" if subject is None
                         else f"it is {subject.status}, not {STATUS_REJECTED}"))
                continue
            if not args.go:
                print(f"  {subject_id}: would take back the rejection, "
                      "returning the subject to the question loop; its "
                      "retained centroid would stop suppressing and become a "
                      "dedupe key again")
                continue
            revived.append(registry.revive(subject_id, by=args.by,
                                           reason=args.reason))
        if revived:
            registry.save()
            import photo_memory

            log = photo_memory.record_revive(pack, revived, by=args.by,
                                             reason=args.reason)
            for result in revived:
                print(f"  {result['subject_id']}: rejection taken back; "
                      f"{len(result['exemplars_retained'])} exemplar(s) stay "
                      "frozen, draft centroid "
                      f"{'retained' if result['draft_centroid'] else 'ABSENT'}")
                if not result["draft_centroid"]:
                    print("      ⚠️  no draft centroid on disk — this subject "
                          "is askable again but nothing re-recognises it "
                          "across batches until it is seen anew")
            print(f"revived {len(revived)} rejection(s) -> {log}")
        elif args.revive and not args.go:
            print("dry run — re-run with --go.")

    if args.merge:
        # U-1. The operator's door onto SNS-14. ⛔ The fold itself is NOT
        # reimplemented here — `fold_subjects()` is the one implementation and
        # it holds the invariants this command must not break (exemplar rows
        # and vector rows moved together, the tombstone `get()` follows, the
        # `previous_names` that keep `rename_ledger()` resolving, the cap).
        # What was missing was never the verb: it was a way to reach it. The
        # only other door is a `recheck:` name collision on a review table
        # (`photo_memory.cmd_confirm`), which needs a live checkpoint in a work
        # dir, so two subjects confirmed in an earlier run and never asked
        # about again could not be rejoined at all.
        #
        # ⛔ Geometry proposes nothing here, which is what keeps this inside
        # the doctrine at the top of this file: the two ids are typed by a
        # human who has looked at both.
        source_id, into_id = args.merge
        loser = winner = None
        refusal = registry.fold_refusal([source_id, into_id])
        if refusal is None:
            # Both ids resolve and are confirmed — `fold_refusal()` just said
            # so, so these cannot be None.
            loser = registry.resolve_merged(source_id)
            winner = registry.resolve_merged(into_id)
            # ⛔ The winner is the EARLIER id and `fold_subjects()` decides it,
            # not the argument order — so an operator who names them the other
            # way round would get a fold that keeps the id they called the
            # source. Refused rather than silently corrected: doing the
            # opposite of what was typed is worse than asking for it again,
            # and the way on is one swapped command.
            if registry._ordinal(loser.subject_id) \
                    < registry._ordinal(winner.subject_id):
                refusal = (
                    f"{winner.subject_id} cannot absorb {loser.subject_id} — "
                    "the earlier id wins a fold, so this one would keep "
                    f"{loser.subject_id}. That rule is deterministic on "
                    "purpose: the earlier id is the one already sitting in "
                    "plan CSVs and folder records. Say it the other way "
                    f"round: `--merge {winner.subject_id} "
                    f"{loser.subject_id}`.")
        if refusal:
            # Exit 2 — a refusal, distinct from a break. Nothing was written.
            print(f"  ! --merge {source_id} {into_id}: {refusal}")
            sys.exit(2)

        if not args.go:
            # `fold_subjects()` audits at the decision point, so it only runs
            # under --go: a dry run that folded would write the memorize audit
            # log and move the pack snapshot. The prediction is exact because
            # `fold_refusal()` above judged the same ids the real run will.
            print(f"  {loser.subject_id}: would be folded into "
                  f"{winner.subject_id}, keeping {winner.name!r} — "
                  f"{len(loser.exemplars)} exemplar(s) join "
                  f"{len(winner.exemplars)} (the cap then evicts for "
                  "redundancy), the folded id becomes an alias that still "
                  f"resolves, and {loser.name!r} is retired into "
                  "`previous_names` so folders already written under it stay "
                  "resolvable")
            print("dry run — re-run with --go.")
        else:
            try:
                result = registry.fold_subjects(
                    [source_id, into_id], by=args.by, reason=args.reason)
            except ValueError as exc:
                print(f"  ! --merge {source_id} {into_id}: {exc}")
                sys.exit(2)
            registry.save()
            # Lazy, for the reason --unconfirm imports it lazily: photo_memory
            # imports this module, and the pack-side half of a fold (the
            # entities twin, the log line) is that module's to write.
            import photo_memory

            log, buckets = photo_memory.record_fold(
                pack, registry, result, by=args.by, reason=args.reason)
            for item in result["folded"]:
                print(f"  {item['subject_id']}: folded into "
                      f"{result['winner']}, {item['exemplars_moved']} "
                      f"exemplar(s) moved; it is now an alias that still "
                      "resolves"
                      + (f", dropped from {buckets[item['subject_id']]}"
                         if item["subject_id"] in buckets else ""))
                if item["absorbed_moved"]:
                    print(f"      {len(item['absorbed_moved'])} absorbed "
                          f"draft(s) now follow {result['winner']}: "
                          + ", ".join(item["absorbed_moved"]))
            if result["names_retired"]:
                print("      names now rendered by no live subject: "
                      + ", ".join(result["names_retired"])
                      + " — folders already on disk keep them and resolve "
                        "through the rename ledger; nothing is moved")
            if result["dropped_for_cap"]:
                print(f"      {len(result['dropped_for_cap'])} exemplar(s) "
                      "evicted for redundancy at the cap")
            print(f"folded {len(result['folded'])} subject(s) into "
                  f"{result['winner']} ({result['exemplars']} exemplar(s)) "
                  f"-> {log}")

    if args.into and not args.detach:
        print("  ! --into names where a --detach goes; give --detach too")
        sys.exit(2)
    if args.detach:
        cmd_detach(registry, args, workdir)

    if args.prune:
        only = set(args.subject or []) or None
        drop_refs, bad = registry.resolve_drop_refs(args.drop, only)
        for line in bad:
            print(f"  ! --drop {line}")
        if bad:
            # Exit 2 — a refusal, distinct from a break. Nothing was written.
            sys.exit(2)
        dropped = registry.prune(subject_ids=only, drop_refs=drop_refs)
        total = sum(len(v) for v in dropped.values())
        for subject_id, refs in sorted(dropped.items()):
            print(f"  {subject_id}: dropping {len(refs)} exemplar(s)")
        if args.go and total:
            registry.save()
            print(f"pruned {total} exemplar(s) -> {registry.dir / REGISTRY_NAME}")
        elif total:
            print(f"dry run — {total} exemplar(s) would go. Re-run with --go.")
        else:
            print("nothing to prune")

    report = review(registry)
    if args.detach:
        # FIX7 — a detach's answer is its plan, and the listing that follows
        # every other `review` run is one block per subject: on a real pack it
        # scrolled the plan off the screen (~490 lines). Said, not dropped.
        print("  (`photo_subjects.py review` on its own prints the full "
              "listing of what the pack holds)")
    else:
        print_review(report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False,
                                              indent=1) + "\n")
        print(f"full report -> {args.json}")


if __name__ == "__main__":
    main()
