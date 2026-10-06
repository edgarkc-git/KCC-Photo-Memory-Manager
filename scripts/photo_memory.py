#!/usr/bin/env python3
"""VS-4 / Phase C — the memory confirm checkpoint: `review` writes the table a
human edits, `confirm` parses it back into the pack.

One script, one owner phase. The build order pairs Phase C with VS-3/VS-4
because the table needs both the pack schema (C) and the subject registry plus
provenance validator (VS) — it is not a C deliverable and a VS deliverable.

    python3 photo_memory.py review  "<Working Files>/<unit>" [--checkpoint 1]
    python3 photo_memory.py confirm "<Working Files>/<unit>" --checkpoint 1 --go
    python3 photo_memory.py review  "<Working Files>/<unit>" --next-page     (indexed dump)
    python3 photo_memory.py confirm "<Working Files>/<unit>" --page P-B03 --go
    python3 photo_memory.py confirm "<Working Files>/<unit>" --sync --go

## The one rule that makes a checkpoint replay deterministic

**`review` never writes the pack. `confirm` does.**

`photo_profile.SNAPSHOT_PARTS` includes `photo-subjects`, `photo-entities.json`
and `photo-proposals.md`, so anything `review` wrote into the pack would change
the pack's snapshot id — and the second replay of a run would be reading a
different memory state than the first. The determinism the DESIGN asks for
would be unprovable, not merely unproved. So `review` writes exactly one file,
into the WORK DIR, and pins the snapshot id it ran against in its header.

For the same reason the table carries no wall-clock time. Two `review` runs
over one pack and one work dir produce byte-identical files; when they do not,
the pack changed, and the header says which snapshot each ran under.

## ONB-13a — one grouped question per `kind`, and the OWNER does the merge

F16. The checkpoint no longer asks "who is this draft?" per draft and "are
these two the same?" per lookalike pair. It emits ONE `Group it` question per
`kind`, rendering that kind's unsettled drafts as numbered tiles, and the
owner answers with a grouping: which tile numbers are one subject, and the
`who` + `name` for each group. Cardinality moves off the engine, which is what
the TEMPLATE said from the start — *cardinality is never auto-resolved*.

⚠️ A tile leaves that answer in THREE states and they must never collapse:

  * **grouped** — listed on a `group:` row with `who` + `name`. Confirmed,
    exemplars attach, never asked again.
  * **deferred** — left out of every row. NOT an answer. Stays `ai-drafted`,
    keeps proposing `draft:` names, and comes back when its evidence grows.
    A draft the engine never RENDERED is deferred too, and is not even
    recorded as asked — see `asked_before()`.
  * **`skip:`** — named explicitly on the skip row. `rejected`: the subject
    leaves the question loop, and OA-14's retained centroid keeps it out of it
    on later dumps too. Permanent in the sense that nothing but the owner
    re-opens it — `--revive` is the one door back, and it exists so that a
    suppression this strong is never also unreachable.

**Silence is never rejection.** Answering three of eight tiles must not retire
the other five, at the parser level and not only in doctrine.

## One subject spanning K batches yields ONE question

Three mechanisms, in order, and all three are needed:

  1. **Within a run** — embedding identity. `photo_subjects.observe_draft_
     subject()` matches a new unmatched cluster against the existing draft
     centroids and bumps `obs_count` instead of forking a second draft. K
     batches, one draft record.
  2. **Across checkpoints in a run** — this file. A question whose subject was
     asked in an earlier `memory-review_C*.md` in the same work dir is
     suppressed unless its evidence GREW (TEMPLATE validator rule 5). One
     draft can otherwise appear in every checkpoint's Ask column.
  3. **Across runs** — `photo-memory-log.md`. A subject already
     `human-confirmed` or `rejected` is not asked again, in any run, until the
     owner takes that decision back (`un-confirmed` / `revived` are the two
     tokens that clear it).
  4. **Across dumps** — the exemplar store, and this is F14. Layers 1-3 all
     key on `subject_id`, and `confirm` used to leave a subject with no way to
     be recognised again: it left the draft pool (so layer 1 stopped seeing
     it) with no exemplars (so `match()` skipped it), and next dump the same
     subject arrived as a NEW id that no layer had ever heard of. Answering
     the question did not stop the question. `confirm` now attaches the
     exemplars its members' looks prove, and `observe_draft_subject()`
     suppresses a cluster that matches them — see `attach_exemplars()` below
     and `photo_subjects.confirmed_match()`.
  4b. **Across dumps, for the other permanent answer** — OA-14. A REJECTED
     subject had the identical hole and it was worse, because nothing in the
     UI said so: rejected records are in neither `drafts` nor `recognisers`,
     so a rejection survived exactly until the next dump and then came back
     under a new id. `photo_subjects.rejected_match()` suppresses on the draft
     centroid the rejection retains — a key that stops a question and can
     never name a file.

## SNS-5 — the round is also the way BACK, and it is unconditional

Layers 3 and 4b above are one-way doors as written: `human-confirmed` and
`rejected` both leave `is_draft`, so `build_questions()` never sees them
again, and `settled_subjects()` closes them for every later run. A name typed
wrongly onto a subject that is never photographed again would be invisible
forever — the mistake disappears exactly when it is worst.

So every round also RE-PRESENTS what the pack already remembers, in its own
builder and its own section, reading `registry.subjects` by status. ⛔ It does
NOT widen `is_draft` or `registry.drafts`: steps 2 and 3 rest on that whitelist
keeping `superseded`, `rejected` and `human-confirmed` out of the question
loop, and a re-presentation is not a question.

  * **Unconditional.** Not gated by `settled_subjects()`, not by
    `asked_before()`, not by evidence growth. An evidence-gated
    re-presentation preserves the hole it was built to close.
  * **`{frames_per_reconfirmation}` frames, its own budget** — a name check,
    not the identity judgement `{contact_frames_per_draft}` is sized for
    (SNS-9's "two budgets, not one").
  * **The frame is the WORST-SCORING sighting** (SNS-6). A subject shown by
    its best frame looks right every round even when it has absorbed a second
    animal, and the glance-yes then reinforces the error. When the score
    cannot be computed the page SAYS SO and shows the record's own order —
    never a quiet fallback to a frame that happens to look good, which would
    make the drift check decoration.
  * **A re-presentation promotes NOTHING.** No `attach_exemplars()` call on
    this path at all. SNS-6 says re-confirmation promotes only PICKED frames
    and there is no `pick:` grammar until step 5; wiring promotion to a
    1-frame glance is the widened human yes `only_refs` exists to stop.
  * **A rejection is re-presented with NO frames.** It is a question the owner
    closed, and re-showing its photos re-asks it. One line — the id, the
    evidence behind it, when it was rejected — plus the row that revives it.
    It is listed at all because `photo_subjects.rejected_match()` makes a
    rejection ACTIVELY suppress, and nothing that permanent may be invisible.

  * **The `recheck:` row is where a remembered name is CORRECTED**, and
    therefore the only door into SNS-14's fold. A confirmed subject never
    reaches a `pick:` row — the question loop tiles drafts — so the SPEC's
    *"renaming A to B's name raises the collision question, and `same`
    performs the fold at the next confirm"* has nowhere else to be typed. A
    name, optionally armed with `same` or `distinct`; a name and a gesture on
    one row is refused whole. ⛔ Still promotes nothing, on every branch.

⚠️ **The owner sees NAMES; the rows carry ids** (SNS-8). No new numbering
space is minted here, deliberately: step 5 owns global frame numbering, and
SNS-8 requires re-presented subjects to occupy numbers in the SAME sequence as
new FSS so the owner can address the subject whose name is the thing being
corrected. **Step 5 inherits that obligation** — these `recheck:` rows must
fold into its one numbering, not survive beside it.

## The honesty marker

An unnamed subject renders as a generic CLASS WORD — never a guessed name.
That word comes from the owner pack (`photo_profile.scene_classes()` for the
species the zero-shot set already names, `review_messages()` for the rest); it
is not a literal in this file. TEMPLATE column rule 5: showing the gap is what
invites the correction.

## ONB-13 — who and name are ONE question

A subject is not identified until the pack holds both its relation to the
owner (`who`) and what the owner calls it (`name`). `confirm` refuses a half
answer rather than writing half a subject: a name with no relation cannot be
used by the naming step, and asking for the other half later is the second
interview the Onboarding SPEC forbids.

## What this stage needs installed

numpy, imported lazily inside the functions that compare vectors, and nowhere
else. ⚠️ `review` gained that dependency with SNS-5: scoring a remembered
subject's frames is arithmetic over the exemplar store, so a pack that
remembers somebody needs numpy to render a table. A pack with nothing
remembered still renders without it — `worst_frames()` returns before the
import when the record holds no look, and `build_representations()` calls it
only for a `human-confirmed` record. `confirm` has needed numpy since F14 for
the same reason: promotion re-derives vectors from the dump's `embed/` index.

## Field keys are ASCII, hints are translated

A human types into `who:` / `name:` / `answer:` / `skip:`. Those keys are the
parser's contract and are never translated — the sentence beside them is.
"""

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import photo_cluster  # noqa: E402
import photo_embed  # noqa: E402
import photo_identity
import photo_platform  # noqa: E402
import photo_profile  # noqa: E402
import photo_subjects  # noqa: E402

REVIEW_GLOB = "memory-review_C*.md"
# G6 — the per-batch page, `P-B<nn>.md`: the second page shape. It is BOOKED
# like a checkpoint page (layer 2 and the refusal channel read it) and never
# CHARGED (`next_checkpoint`, `rounds_fired` and `final_round_asked` read the
# C shape only), because the batch pages have their own count.
BATCH_PAGE_GLOB = "P-B*.md"
# Doc 4 v4's fourth outcome, in the work dir beside the pages it corrects.
# One line per `confirm --go` that refused something, naming the drafts those
# refused rows were about. ⛔ NOT in the pack: a refusal writes nothing to the
# registry, and a file inside the pack would move the pack id and invalidate
# the very page the refusal told the owner to keep answering.
REFUSED_NAME = "memory-refused.jsonl"
LOG_NAME = "photo-memory-log.md"
PROPOSALS_NAME = "photo-proposals.md"
ENTITIES_NAME = "photo-entities.json"

# The maturity token a withdrawal writes. ASCII and untranslated like every
# other key the log is parsed on, and deliberately not a word `settled_
# subjects()` already reads: it is the one that re-opens a question.
UNCONFIRMED = "un-confirmed"
# OA-14's other clearing token, and it needs its own word rather than reusing
# the one above: `un-confirmed` says a yes was withdrawn, and a rejection was
# never a yes. Both clear; the log stays readable about WHICH decision was
# taken back.
REVIVED = "revived"

DRAFTS_BEGIN = "<!-- vs4:subject-drafts:begin -->"
DRAFTS_END = "<!-- vs4:subject-drafts:end -->"

# V2-7's cadence knob. ⚠️ A STARTING VALUE with no data behind it — the DESIGN
# says so in as many words and asks for it to be calibrated on the first
# cold-start replay. It lives in the pack (`memory.confirm_threshold`) so an
# owner moves it without touching the engine.
DEFAULT_CONFIRM_THRESHOLD = 200

# SNS-4's two cadence knobs, beside the checkpoint's own for the reason that
# they are the same kind of number: when is it worth interrupting. They live
# in the pack (`memory.new_fss_floor`, `memory.sns_rounds_per_dump`) so an
# owner moves them without touching the engine, and both are STARTING VALUES —
# signed as numbers to be moved by the build step 8 replay, not defended by
# argument.
#
# The floor is on NEWLY-DISCOVERED frequently-seen subjects since the last
# round, never on a file count: it is low enough that a dump introducing one
# household's worth of subjects is still asked in more than one round, and
# high enough that a single stray cluster cannot interrupt on its own.
DEFAULT_NEW_FSS_FLOOR = 3
# A UX BUDGET, not a ceiling. Past it the engine stops interrupting on the
# floor alone; the last round of the dump still fires and is not charged
# against it, because a budget spent early must not be able to strand every
# subject discovered late. Nothing the budget withholds is ever booked as
# asked.
DEFAULT_SNS_ROUNDS_PER_DUMP = 4

TYPE_GROUP_IT = "group_it"

# ONE key/value per line was the pre-F16 contract, and the signed `Group it`
# row puts three of them on one line:
#
#     - `group:` 1,3,7   `who:` pet   `name:` ______
#
# An anchored one-shot match reads that as group = "1,3,7   `who:` pet …" with
# who and name None, so ONB-13's both-halves check refuses every group the
# owner ever writes — silently, because no fixture had ever put two fields on
# one line. So the parser SCANS, and the anchor is kept as a gate rather than
# as the match: a line still has to BEGIN with a field key before any of it is
# read, which is what keeps a translated sentence that happens to contain
# `name:` from being parsed as an answer.
FIELD_KEYS = ("who|name|answer|skip|pick|group|subject|subjects|obs_count"
              "|frames")
# SNS-5's row, and it is deliberately NOT in FIELD_KEYS. `parse_review()`
# builds `Q<n>` blocks and `asked_before()` globs every review file this work
# dir holds to read them; a re-presentation is not a question and must not
# become one, or a subject re-presented at C1 would book itself into layer 2
# and suppress the draft question it is not.
RECHECK_KEY = "recheck"
# The three gestures, ASCII and untranslated for the same reason the field
# keys are, and for the same reason `skip:` needs the word `confirm`: a parser
# that depends on a translated label breaks the moment somebody translates it.
GESTURE_WITHDRAW = "withdraw"
GESTURE_REVIVE = "revive"
# ⛔ Parsed only to be REFUSED — see `cmd_confirm`. Recognised rather than
# ignored, because a gesture that is silently dropped is indistinguishable
# from one that worked.
GESTURE_REJECT = "reject"
GESTURES = (GESTURE_WITHDRAW, GESTURE_REVIVE, GESTURE_REJECT)
# SNS-7's armed answer. A typed name that collides with one the pack already
# remembers is a QUESTION, and this word is the owner's answer to it: *a
# separate subject that happens to share the name*. ASCII and untranslated for
# the same reason `skip:`'s `confirm` is — a parser that depends on a
# translated label breaks the moment somebody translates it, and this one
# forces a slot that can never be un-forced by the engine.
DISTINCT_TOKEN = "distinct"
NAME_DISTINCT = re.compile(rf"\s+{DISTINCT_TOKEN}\s*$", re.I)
# SNS-14's armed answer, and the exact mirror of the one above it. The same
# collision question has two owner answers — *a different subject that happens
# to share the name* (`distinct`) and *the same one* (`same`) — so they are one
# grammar, typed the same way, stripped in the same place. ASCII and
# untranslated for the reason every parsed token here is.
#
# ⚠️ `same` is the heavier of the two: it FOLDS two remembered subjects into
# one and there is no un-fold verb. What makes that acceptable is that it is
# only reachable against a subject the pack already holds a name for — the
# owner is answering about a record they can see, not creating one.
SAME_TOKEN = "same"
NAME_SAME = re.compile(rf"\s+{SAME_TOKEN}\s*$", re.I)
# F13 (iii)(b) — `name: X same subj-NNNN`: the same answer, naming WHICH of
# several records holding X. Its own expression, matched BEFORE the suffix
# loop below, so `X same` and `X distinct` parse exactly as they always did.
# The owner is never asked to compose it: the refusal that needs it prints it.
NAME_SAME_AS = re.compile(rf"\s+{SAME_TOKEN}\s+(subj-\d{{4,}})\s*$", re.I)
# U2-10 — WHY a `skip:` row was typed. `rejected` answered two questions with
# one word: *this is not my animal* and *this was never an animal*. They are
# not the same fact and they do not have the same future — a neighbour's cat
# may legitimately turn up again and be worth asking about, and a bonfire the
# detector scored as a cat never is. The registry recorded both identically,
# so nothing downstream could ever tell them apart, and the owner had no way
# to say which one they meant.
#
# ⛔ The DEFAULT is `not-mine`, and that is the conservative direction: it is
# the weaker claim, it is what every rejection written before this meant, and
# reading an old record as the stronger one would invent a judgement the owner
# never made. ASCII and untranslated for the reason every parsed token is.
BASIS_NOT_MINE = "not-mine"
BASIS_NOT_A_SUBJECT = "not-a-subject"
SKIP_NOT_A_SUBJECT = re.compile(rf"\b{BASIS_NOT_A_SUBJECT}\b", re.I)
# Q8-c — one crop of a shared frame, `<frame>.<animal>`, as the page labels it.
CROP_REF = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])")
CROP_FILE = re.compile(r"_d(\d+)\.jpg$")
# F26 — a crop ref on a `pick:` row is REFUSED: read as numbers, `3.1` is
# frames 3 AND 1, which names a photo nobody picked.
PICK_CROP_WHY = ("`pick:` takes photo numbers only, never `<photo>.<animal>` "
                 "like {refs}. To name each animal in one photo, put the photo "
                 "number on one row per name: `pick: {n}` with one name, and a "
                 "second row `pick: {n}` with the other.")


def pick_crop_refusal(value):
    """-> the F26 refusal for a `pick:` value holding `N.M`, or None."""
    refs = CROP_REF.findall(value or "")
    if not refs:
        return None
    return PICK_CROP_WHY.format(refs=", ".join(f"{n}.{a}" for n, a in refs),
                                n=refs[0][0])
# The crop refs `not-a-subject` arms: the word binds to the refs right before
# it, so `4 confirm, 1.2 not-a-subject` still rejects frame 4 as `not-mine`.
CROP_ARMED = re.compile(
    rf"((?:(?<![\d.])\d+\.\d+(?![\d.])\s*,?\s*)+){BASIS_NOT_A_SUBJECT}\b", re.I)
# C10 — the crop refs `confirm` arms: that ONE animal of a shared photo is
# not the owner's. Bound the same way, to the refs right before the word.
CROP_CONFIRMED = re.compile(
    r"((?:(?<![\d.])\d+\.\d+(?![\d.])\s*,?\s*)+)confirm\b", re.I)
FIELD_LINE = re.compile(rf"^\s*[-*]?\s*(?=`?(?:{FIELD_KEYS})\b)", re.I)
FIELD_SCAN = re.compile(rf"`?\b({FIELD_KEYS})\b`?\s*:\s*`?\s*", re.I)
# The closing backtick after the colon is eaten HERE, the way `FIELD_SCAN` eats
# it, and it stopped being cosmetic the moment this row could carry a name: the
# key is rendered as `recheck:` — backtick, key, colon, backtick — so a value
# read from just past the colon starts with a stray "`", and a parser that
# treats whatever-is-left as the name would read every rendered row as a
# subject called "`".
RECHECK_LINE = re.compile(
    rf"^\s*[-*]?\s*`?{RECHECK_KEY}`?\s*:\s*`?\s*(.*)$", re.I)
GESTURE_SCAN = re.compile(rf"\b({'|'.join(GESTURES)})\b", re.I)
# Q8-b — `not <frame>[,<frame>…]` takes those photos out of ONE remembered
# subject's memory and keeps its name. ASCII and untranslated, like every
# parsed token. `not1`, `not 1 3` and `not: 1` are the same answer.
NOT_TOKEN = "not"
NOT_FRAMES = re.compile(rf"\b{NOT_TOKEN}\s*:?\s*(\d+(?:\s*[,\s]\s*\d+)*)", re.I)
NOT_BARE = re.compile(rf"\b{NOT_TOKEN}\b\s*:?", re.I)
# A name on a `recheck:` row may not hold a bare number: `nto 3` is a mistyped
# `not 3`, and reading it as a name would rename the subject (A20).
BARE_NUMBER = re.compile(r"(?<![^\s,])\d+(?![^\s,])")
# The frame number -> photo map under a remembered subject. Its OWN key, never
# `frames:`, so it opens no promotion path (a re-presentation promotes nothing).
SHOWN_KEY = "shown"
SHOWN_LINE = re.compile(rf"`{SHOWN_KEY}:`\s*(subj-\d{{4,}})\s*(.*)$")
# The blank `render_representations()` writes for the owner to type into. A RUN
# rather than an end-strip: an owner who types after it leaves the underscores
# in the middle of the value, and a name read as `______ Bo` matches nothing.
BLANK_RUN = re.compile(r"_{2,}")
SUBJECT_IN_TEXT = re.compile(r"subj-\d{4,}")
TILE_TO_SUBJECT = re.compile(r"(\d+)\s*=\s*(subj-\d{4,})")
# SNS-1b item 1's mapping line, one entry per frame:
#
#     `frames:` 1=subj-0034 9b1c2d3e4f5a classify/batch-01/samples/B1_C0.jpg, 2=…
#
# The path runs to the next entry rather than to the next comma or space,
# because a file name may hold either and a map that mis-reads a path is worse
# than no map. The lookahead is what makes the entry separator unambiguous: a
# comma only ends an entry when a frame number and a subject id follow it.
FRAME_ENTRY = re.compile(
    r"(\d+)\s*=\s*(subj-\d{4,})\s+(\S+)\s*(.*?)\s*(?=,\s*\d+\s*=\s*subj-|$)")
TILE_TO_COUNT = re.compile(r"(\d+)\s*=\s*(\d+)")
QUESTION_HEAD = re.compile(r"^\*\*Q(\d+)\s*·")
CHECKPOINT_IN_NAME = re.compile(r"memory-review_C(\d+)\.md$")
# ⛔ Anchored at BOTH ends, and matched on the file NAME: `P-B03 (1).md` or
# `old-P-B03.md` is a copy, and a copy books nothing (LL-PHO-94).
BATCH_PAGE_IN_NAME = re.compile(r"^(P-B\d{2,})\.md$")
# What `review` writes onto a batch page, so `confirm` can refuse a page handed
# in under another name (U5-06). ASCII, outside the header fence, like
# FINAL_MARKER.
PAGE_MARKER = "<!-- sns-page: {page} -->"
PAGE_MARKER_IN_TEXT = re.compile(r"<!-- sns-page: (P-B\d{2,}) -->")
# G6 — `review --next-page` tells the conductor what happened with its exit
# status, the way `--pre-plan` does: a page was just written, or one written
# earlier is still waiting for its confirm and `apply-page`.
PAGE_WRITTEN_RC = 11
PAGE_WAITING_RC = 12
# G6 SNL — a place question, rendered AFTER the questions fence so
# `parse_review()` never reads it. ASCII keys; the counts on the `place:` line
# are what `confirm` checks the place against — never a coordinate.
PLACE_HEAD = re.compile(r"^\*\*S(\d+)\s*·")
PLACE_LINE = re.compile(r"`place:`\s*(\d+)\s*·\s*(\d+)\s*d\s*·\s*(\d+)\s*m")
PLACE_ANSWER = re.compile(r"`name:`\s*(.*?)\s*`home:`\s*(.*?)\s*$")
PLACE_PHOTOS = 4
# G6-6d (owner 20260904, re-confirmed 20260913) — a draft whose every photo
# on a page held 2+ animals and was named there, one row per animal. Its
# names are logged on the photos; the record itself moves nowhere (G2).
SHARED_FRAMES_FLAG = "named_on_shared_frames"
# The pack id `review` pinned into its header. ASCII and untranslated like
# every other parsed value — the SENTENCE around it is owner language, so the
# id itself is what is matched, inside the header fence and nowhere else.
SNAPSHOT_ID = re.compile(r"sha256:[0-9a-f]{8,}")
# SNS-4 — the machine-readable trace that the guaranteed end-of-dump round has
# already been asked in this work dir. An HTML COMMENT and ASCII, for the
# reason every other parsed token on the page is: the sentence stating the
# reason is owner language (`ROUND_REASON_KEY` -> `REVIEW_VOCAB`), so reading
# the reason back out of the prose would make a cadence decision depend on
# which language the pack is written in. `parse_review()` strips comments
# before it reads a line, so this can never be mistaken for an answer.
FINAL_MARKER = "<!-- sns-round: final -->"

# U-2 — `review --pre-plan` answers ONE question back to the conductor with
# its exit status: was a question actually put to the owner at this
# checkpoint? The conductor needs it because a pre-plan round is only useful
# if the owner gets to answer BEFORE the folders are written, so it has to
# hold the copy — and it cannot see the registry or the pages to work that
# out for itself. ⛔ The same boundary `--final` draws, in the other
# direction: a fact crosses back, never a decision. Whether a round fires is
# still decided here, in `sns_round()`, against evidence the conductor does
# not hold.
#
# ⛔ NOT the rc of a plain `review`, which stays 0 whether or not a round
# fired — `finish` treats a non-zero review as "no page was written" and
# would warn on every firing checkpoint. Only `--pre-plan` returns it.
PRE_PLAN_ROUND_FIRED_RC = 10


def next_checkpoint(workdir):
    """The number `review` gives a page when none is passed: one past the
    highest page in the work dir. ⛔ Counts only names `CHECKPOINT_IN_NAME`
    parses — `REVIEW_GLOB` is wider (LL-PHO-94). `photo_run` carries a copy
    (it imports no stage); `pre_plan_checkpoint_cases` holds the two equal."""
    used = [int(CHECKPOINT_IN_NAME.search(p.name).group(1))
            for p in Path(workdir).glob(REVIEW_GLOB)
            if CHECKPOINT_IN_NAME.search(p.name)]
    return (max(used) + 1) if used else 1


def frame_animals(workdir, pack=None):
    """-> {SourceFile: how many animals the identity index counted in it}.

    ⛔ G3 — the ONLY source for "this photo holds 2+ animals" at confirm: the
    page's `animals:` line is display. A file with no row, or no index at all,
    is absent here and counts as ONE animal — the strict side. Q8-c: read
    through `load_detections()`, so a crop marked "not a real animal" is not
    counted. `pack` is the stage's own (Card 9), so --profile reaches it."""
    out = {}
    if not (Path(workdir) / "embed" / "identity.csv").is_file():
        return out
    by_file, _space = photo_identity.load_detections(Path(workdir) / "embed",
                                                      pack)
    for source, entries in by_file.items():
        try:
            out[source] = max(int(r.get("det_count") or 0) for r, _v in entries)
        except ValueError:
            continue
    return out


def frame_source(workdir, sample_rel):
    """-> the SourceFile a page frame's sample was made from, or None."""
    rel = Path(sample_rel)
    report = load_json(Path(workdir) / rel.parent.parent / "see-report.json", {}) or {}
    for entry in report.get("selected") or []:
        if entry.get("sample") == rel.name:
            return entry.get("path")
    return None


def shared_frame_rows(workdir, block, refusals, pack=None):
    """G6-6d — a photo with 2+ animals may sit on one pick row per animal.
    -> [(sample path, typed name, draft id, frame number)] to LOG.

    Only a frame named on MORE THAN ONE row is looked at, and only one the
    identity index counts 2+ animals in (`frame_animals()`). For each such
    frame the rows only log names: the frame is taken off every row before a
    row is judged, so it joins, splits and promotes nothing, and the join rule
    (SNS-16) and the frame clash never see it. A one-animal frame on two rows
    is left exactly as it was, and is refused by those rules as before.

    Refused, whole rows: more rows than animals; a row missing who or name;
    the same name twice on one photo (that is one animal, not two)."""
    rows_of = {}
    for unit in block["picks"]:
        if unit["verb"] != "pick":
            continue
        for number in set(unit["numbers"]):
            rows_of.setdefault(number, []).append(unit)
    doubled = {n: units for n, units in rows_of.items()
               if len(units) > 1 and n in block["frames"]}
    if not doubled:
        return []
    animals = frame_animals(workdir, pack)
    logs, dropped = [], []
    for number, units in sorted(doubled.items()):
        frame = block["frames"][number]
        count = animals.get(frame_source(workdir, frame["path"]), 1)
        if count < 2:
            continue
        names = [(u["name"] or "").strip().casefold() for u in units]
        why = None
        if len(units) > count:
            why = (f"it holds {count} animals and is on {len(units)} rows — "
                   "one row per animal at most")
        elif not all(u["who"] and u["name"] for u in units):
            why = "`who` and `name` are one answer on each of its rows (ONB-13)"
        elif len(set(names)) < len(names):
            why = ("the same name is on two of its rows — one animal named "
                   "twice is not two animals")
        if why:
            refusals.about = sorted({s for u in units for s in u["subject_ids"]})
            refusals.append(f"Q{block['n']}: frame {number}: {why}. Its rows "
                            "were not applied.")
            dropped.extend(units)
            continue
        for unit in units:
            logs.append((frame["path"], unit["name"], frame["subject_id"], number))
            unit["numbers"] = [x for x in unit["numbers"] if x != number]
    for unit in block["picks"]:
        if unit["verb"] != "pick":
            continue
        refs = {}
        for x in unit["numbers"]:
            entry = block["frames"].get(x)
            if entry:
                refs.setdefault(entry["subject_id"], []).append(entry["ref"])
        unit["refs"], unit["subject_ids"] = refs, list(refs)
    block["picks"] = [u for u in block["picks"]
                      if u["verb"] != "pick" or (u["numbers"]
                                                 and not any(u is d for d in dropped))]
    return logs


def read_mixed_rows(block, registry, changes):
    """U2-6 (owner ruling 20261001; supersedes OA-19 for this case only) — a
    NAMED pick row whose one-animal frames span 2+ drafts, while one of those
    drafts is split by another row, is read as ONE ROW PER DRAFT with the same
    who and name: the two-row form `partition_subject()`'s refusal teaches,
    and with one name on both (doc 8 amendment (a)) one subject over the ids
    they name. Said in owner words, in the dry run and under --go alike.

    Runs after `shared_frame_rows()`, so a 2+ animal frame has already left
    the rows. ⛔ The storage gate is NOT changed: a mixed row reaching
    `partition_subject()` from anywhere else is still refused. A row with no
    name, or whose drafts no other row splits (an SNS-16 join), is left as it
    is."""
    picks = [u for u in block["picks"] if u["verb"] == "pick"]

    def drafts_of(unit):
        out = {}
        for n in unit["numbers"]:
            entry = block["frames"].get(n)
            if entry:
                out.setdefault(entry["subject_id"], []).append(n)
        return out

    rows_per = {}
    for unit in picks:
        for sid in drafts_of(unit):
            rows_per[sid] = rows_per.get(sid, 0) + 1
    out, row_no = [], 0
    for unit in block["picks"]:
        if unit["verb"] != "pick":
            out.append(unit)
            continue
        row_no += 1
        drafts = drafts_of(unit)
        if not (unit["name"] and len(drafts) > 1
                and any(rows_per[s] > 1 for s in drafts)):
            out.append(unit)
            continue
        loose = [n for n in unit["numbers"] if n not in block["frames"]]
        pieces = []
        for i, (sid, numbers) in enumerate(drafts.items()):
            piece = dict(unit)
            piece["numbers"] = numbers + (loose if i == 0 else [])
            piece["refs"] = {sid: [block["frames"][n]["ref"] for n in numbers]}
            piece["subject_ids"] = [sid]
            pieces.append(piece)
        out.extend(pieces)
        kinds = {(registry.get_literal(s).record.get("kind") if registry.get_literal(s)
                  else None) or "animal" for s in drafts}
        kind = kinds.pop() if len(kinds) == 1 else "animal"
        said = [("photo " if len(p["numbers"]) == 1 else "photos ")
                + ", ".join(str(n) for n in p["numbers"]) for p in pieces]
        count = {2: "two", 3: "three", 4: "four"}.get(len(pieces), str(len(pieces)))
        changes.append(
            "Q%d: Row %d had photos of %s %s groups, so it was read as %s rows, "
            "%s named %s: %s." % (block["n"], row_no, count, kind, count,
                                  "both" if len(pieces) == 2 else "all",
                                  unit["name"], ", and ".join(said)))
    block["picks"] = out


def batch_page_name(batch):
    """-> the file name of batch N's page: `P-B03.md`."""
    return f"P-B{int(batch):02d}.md"


def page_key(name):
    """-> the booking key a review page's NAME gives it, or None.

    An int for a checkpoint page (`memory-review_C3.md` -> 3), the page id for
    a batch page (`P-B03.md` -> "P-B03"). Both shapes key layer 2 and the
    refusal channel; only the int is a round."""
    found = CHECKPOINT_IN_NAME.search(name)
    if found:
        return int(found.group(1))
    found = BATCH_PAGE_IN_NAME.match(name)
    return found.group(1) if found else None


def page_label(key):
    """-> how a booking key is said on a page: `C3` or `P-B03`."""
    return key if isinstance(key, str) else f"C{key}"


def booking_order(key):
    """-> a sort key over both shapes, for "the later booking wins".

    ⚠️ A batch page ranks below EVERY checkpoint page. Batch pages are asked
    before the copy; the one checkpoint round certain to exist is SNS-4's, after
    it. Whether U-2's pre-plan round survives beside the pages is still open
    (G6 R3); if it does, this ordering is what to revisit."""
    return (0, int(key[3:])) if isinstance(key, str) else (1, key)


def booked_pages(workdir):
    """-> [(path, booking key)] for every review page layer 2 reads, sorted.

    A `memory-review_C*.md` file its pattern cannot parse is booked at 0, as it
    always was. A `P-B*.md` file is read only when its name parses."""
    workdir = Path(workdir)
    pages = [(path, page_key(path.name) or 0)
             for path in workdir.glob(REVIEW_GLOB)]
    pages += [(path, page_key(path.name)) for path in workdir.glob(BATCH_PAGE_GLOB)
              if BATCH_PAGE_IN_NAME.match(path.name)]
    return sorted(pages, key=lambda pair: pair[0].name)


def page_batch(name):
    """-> the batch number a batch page's file name carries, or None."""
    found = BATCH_PAGE_IN_NAME.match(Path(name).name)
    return int(found.group(1)[3:]) if found else None


def dump_index(workdir, pack):
    """-> (index dir, index) for this dump, or (None, None) with no index.
    Read here, written only through `photo_index`."""
    import photo_index
    pointer = photo_index.read_pointer(workdir)
    if not pointer or pack.dir is None:
        return None, None
    target = photo_index.index_dir(pack, pointer["dump_key"])
    index = load_json(target / photo_index.INDEX_NAME)
    return (target, index) if index else (None, None)


def places_by_first_batch(workdir, pack):
    """G6 SNL — {batch: [place, ...]}: every place to ask the owner to name
    (`photo_census.unnamed_frequent_places()`), filed under the FIRST batch it
    appears in, with `batches` and its number on that batch's page (`n`).

    ⛔ Batches come from the index's own files, so no index -> {}: a place is
    asked only on a batch page, and batch pages need the index. Recomputed at
    `confirm` from the same manifest and the same pack the page was pinned to,
    so a page carries no coordinate and still names exactly one place."""
    import csv as _csv
    import photo_census
    _target, index = dump_index(workdir, pack)
    manifest = Path(workdir) / "manifest.csv"
    if index is None or not manifest.is_file():
        return {}
    batch_of = {f["source"]: f["batch"] for f in index.get("files") or []
                if f.get("batch") is not None}
    with manifest.open(newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    out = {}
    for place in photo_census.unnamed_frequent_places(
            rows, pack.profile, photo_profile.named_places(pack)):
        batches = sorted({batch_of[s] for s in place["sources"] if s in batch_of})
        if batches:
            group = out.setdefault(batches[0], [])
            group.append(dict(place, batches=batches, n=len(group) + 1))
    return out


def place_photos(workdir, batch, place, limit=PLACE_PHOTOS):
    """-> ([image paths relative to the work dir], how many the document check
    held back) — this batch's viewed samples taken AT the place.

    ⛔ R9 — through the U3-06 document check, armed here and FAIL-CLOSED: with
    no CLIP it stops the page (`arm_evidence_filter` exits), because a place
    photo is a whole frame and may be a ticket or a letter."""
    report, bdir = see_reports(workdir).get(batch, (None, None))
    samples = [e["sample"] for e in (report or {}).get("selected") or []
               if e.get("sample") and e.get("path") in place["sources"]]
    if not samples:
        return [], 0
    import photo_onboard_page
    photo_onboard_page.arm_evidence_filter(False, script="photo_memory.py")
    shown, held = [], 0
    for sample in samples:
        path = bdir / "samples" / sample
        if not path.is_file():
            continue
        check = photo_onboard_page.ACTIVE_FILTER
        if check is not None and check(path.read_bytes()):
            held += 1
            continue
        shown.append(path.relative_to(Path(workdir)).as_posix())
        if len(shown) >= limit:
            break
    return shown, held


def render_places(workdir, batch, places, rmsg):
    """The SNL block of a batch page. -> lines. After the questions fence."""
    if not places:
        return []
    out = [rmsg["review_places_header"], ""]
    for place in places:
        out.append(rmsg["review_place_header"].format(
            n=place["n"], days=place["days"], months=place["months"],
            batches=len(place["batches"])))
        out.append("> " + rmsg["review_place_ask"])
        shown, held = place_photos(workdir, batch, place)
        for image in shown:
            out.append(f"> ![]({image})")
        if not shown:
            out.append("> " + rmsg["review_place_no_photos"])
        if held:
            out.append("> " + rmsg["review_place_photos_held"].format(n=held))
        out.append("> " + rmsg["review_place_no_recut"])
        out.append(f"> `place:` {place['n']} · {place['days']} d · "
                   f"{place['months']} m")
        out.append("> - `name:` ______   `home:` ______ "
                   f"<!-- {rmsg['review_hint_place']} -->")
        out.append("")
    return out


def parse_places(text):
    """-> [{"n", "days", "months", "name", "home"}] for every SNL block on a
    batch page. Blank rows come back with `name` None."""
    out, current = [], None
    for line in re.sub(r"<!--.*?-->", "", text, flags=re.S).splitlines():
        if PLACE_HEAD.match(line.strip()):
            current = {"n": None, "days": None, "months": None,
                       "name": None, "home": None}
            out.append(current)
            continue
        if current is None:
            continue
        found = PLACE_LINE.search(line)
        if found:
            current.update(n=int(found.group(1)), days=int(found.group(2)),
                           months=int(found.group(3)))
            continue
        found = PLACE_ANSWER.search(line)
        if found:
            current["name"] = found.group(1).strip("_").strip() or None
            current["home"] = found.group(2).strip("_").strip() or None
    return [p for p in out if p["n"] is not None]


def place_answers(workdir, pack, page_name, text, refusals):
    """confirm's half of SNL. -> (answers, coords) for `write_pack`, or None
    when the page names no place. A row that cannot be tied to the place its
    page showed is refused and books nothing."""
    rows = [p for p in parse_places(text) if p["name"]]
    if not rows:
        return None
    refusals.about = []
    batch = page_batch(page_name)
    if batch is None:
        refusals.append("a place is named only on a batch page (P-B…) — "
                        "nothing written for it")
        return None
    import photo_onboard_page
    shown = {p["n"]: p for p in places_by_first_batch(workdir, pack).get(batch, [])}
    answers = {"language": "", "types": "", "own_camera_makes": [],
               "screens": {}, "away_km": "", "pets": "", "homes": {}}
    coords = {}
    for row in rows:
        place = shown.get(row["n"])
        if place is None or (place["days"], place["months"]) != (row["days"],
                                                                 row["months"]):
            refusals.append(f"S{row['n']}: this page no longer describes the "
                            "place it asked about — nothing written for it. "
                            "Write the page again with `review`.")
            continue
        try:
            answer = photo_onboard_page._home_answer(
                f"{row['name']} {row['home'] or ''}".strip())
        except SystemExit as why:
            refusals.append(f"S{row['n']}: {why}")
            continue
        if answer["kind"] == "drop":
            continue
        letter = f"S{row['n']}"
        answers["homes"][letter] = answer
        coords[letter.upper()] = tuple(place["coord"])
    return (answers, coords) if answers["homes"] else None


# ------------------------------------------------------------ pack access ---

def require_pack(workdir, explicit):
    pack = photo_profile.resolve_pack(workdir=workdir, explicit=explicit)
    if pack.dir is None:
        sys.exit("no owner pack for this run — the memory checkpoint writes into "
                 "the pack (photo-entities.json, photo-memory-log.md). Bind the "
                 "collection to an owner or pass --profile; see "
                 "docs/photo-memory-pack.md.")
    return pack


def log_path(pack):
    return Path(pack.dir) / LOG_NAME


def settled_subjects(pack):
    """-> {subject_id: maturity} for everything the log has closed.

    A `human-confirmed` or `rejected` subject is not asked about again — in
    this run or any later one — until the owner takes that decision back.
    That is the outermost of the three dedupe layers and the only one that
    survives a new work dir.

    SNS-5 — and it is the layer un-confirm has to reach. A status flip in the
    registry alone leaves this scan still reading the `human-confirmed` line
    that closed the question, so the subject would be askable by `is_draft`
    and suppressed here: withdrawn and invisible at once. `un-confirmed` is
    therefore a maturity token like the others, and the one that CLEARS rather
    than sets. The scan is already last-writer-wins over an append-only log,
    so the newest word about a subject is the one that counts; a later
    confirm closes it again with no special case.

    OA-14 — `revived` is the second clearing token, for the same reason and
    against the other permanent word. A rejection now SUPPRESSES on its
    retained centroid (`photo_subjects.rejected_match()`) instead of merely
    hiding, so taking one back has to reach every layer that closed it: the
    status, the retained centroid, and this log. A revive that cleared only
    the first two would leave the subject askable, unsuppressed by geometry
    and still closed here — revived and invisible at once, which is the trap
    this paragraph's neighbour was written to avoid.

    F15 — EVERY id on the line is settled, not the first one. One answer can
    close a question that carried several member ids, and a reader that took
    only `ids[0]` marked one member closed forever while leaving the rest
    open: the closed one was never named, and nothing said so. Reading all of
    them is only safe because a line whose token is not one of these three
    settles nothing at all — a cardinality answer logs `human-answered` for
    exactly that reason, and never reaches this loop's body."""
    path = log_path(pack)
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        found = re.search(
            r"\|\s*(human-confirmed|rejected|human-typed|un-confirmed"
            r"|revived)\s*\|",
            line)
        if not found:
            continue
        for subject_id in re.findall(r"subj-\d{4,}", line[found.end():]):
            if found.group(1) in (UNCONFIRMED, REVIVED):
                out.pop(subject_id, None)
            else:
                out[subject_id] = found.group(1)
    return out


# --------------------------------------------------------- the class word ---

def kind_word(kind, profile, rmsg):
    """The honesty marker's noun: what an unnamed subject is CALLED when
    nobody has said who it is.

    Resolution, all of it owner data: the zero-shot scene vocabulary already
    names the species the label set covers, and `review_messages` covers the
    rest (`person`, `object`, and the case where even the species is unknown).
    No branch here returns a literal of this file's own."""
    classes = photo_profile.scene_classes(profile)
    if kind and kind in classes:
        return classes[kind]
    if not kind:
        return rmsg["review_kind_unknown"]
    return rmsg.get(f"review_kind_{kind}", rmsg["review_kind_unknown"])


def subject_display(subject, profile, rmsg):
    """A confirmed subject shows its name; an unconfirmed one shows its class
    word AND the cheapest fact that tells it from the next one along.
    TEMPLATE column rule 5 — never a guessed name.

    ⭐ D-21. The class word alone is not a label, it is a category: one
    measured page rendered `an unnamed Cat` eleven times in a tile list and
    seventeen times inside one table cell, and an owner asked to name them
    could only refer to them by their position in a list. First-seen is the
    discriminator this picks because it is the one the marker can carry
    EVERYWHERE it appears — the tile line already prints files and batches,
    and the Scene column can afford neither a second count nor a subject id
    (an id is the index the defect is about).

    ⚠️ A draft with no capture date anywhere keeps the bare marker. That is a
    real case — `active` stays open when nothing in the group carried a date —
    and inventing a date to fill the slot would be the one thing this column
    may never do. The evidence is WRAPPED around the pack's own marker for the
    same reason: a pack that translated the marker must not lose it here."""
    if subject.name and not subject.is_draft:
        return subject.name
    word = kind_word(subject.kind, profile, rmsg)
    marker = rmsg["review_unnamed_subject"].format(kind=word)
    since = (subject.record.get("active") or [None])[0]
    if not since:
        return marker
    return rmsg["review_unnamed_subject_since"].format(subject=marker,
                                                       since=since)


# ------------------------------------------------------ proposals document --

def render_subject_drafts(registry, profile, rmsg):
    """The `ai-drafted` block VS-4's discovery loop owns inside
    `photo-proposals.md`. Written between markers so re-running discovery
    replaces its own block and never duplicates or clobbers the census's."""
    lines = [DRAFTS_BEGIN,
             "## ai-drafted — recurring subjects (VS-4 discovery)",
             "",
             "Visual clusters that matched no confirmed subject, deduped across "
             "batches by embedding identity: one subject seen in K batches is "
             "ONE draft here, not K. None of them may become a recognition "
             "exemplar — only a vision-confirmed match may (anti-drift rule) — "
             "and none of them is a fact until a human answers at a checkpoint.",
             ""]
    drafts = sorted(registry.drafts,
                    key=lambda s: (-int(s.record.get("files", 0)), s.subject_id))
    if not drafts:
        lines += ["(none)", ""]
    for subject in drafts:
        active = subject.record.get("active") or [None, None]
        lines.append(
            f"- **{subject.subject_id}** · {subject_display(subject, profile, rmsg)}"
            f" · {subject.record.get('files', 0)} file(s)"
            f" · {len(subject.observed_in)} batch(es)"
            f" · {active[0] or '?'} → {active[1] or '?'}")
        lines.append(f"  - provenance: `{subject.status}` · obs_count "
                     f"{subject.obs_count} · batches "
                     f"{', '.join(str(b) for b in subject.observed_in)}")
        sheet = subject.record.get("contact_sheet") or []
        if sheet:
            lines.append(f"  - looked at: {', '.join(sheet[:4])}")
    lines += ["", DRAFTS_END]
    return "\n".join(lines) + "\n"


def write_subject_drafts(pack, registry, profile):
    """Replace this loop's own block in the pack's `photo-proposals.md`.

    Called by the MEMORIZE step (which already mutates the pack), never by
    `review` — see the determinism rule in the module docstring."""
    rmsg = photo_profile.review_messages(profile)
    block = render_subject_drafts(registry, profile, rmsg)
    path = Path(pack.dir) / PROPOSALS_NAME
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if DRAFTS_BEGIN in text and DRAFTS_END in text:
        head, rest = text.split(DRAFTS_BEGIN, 1)
        _old, tail = rest.split(DRAFTS_END, 1)
        text = head + block + tail.lstrip("\n")
    else:
        text = (text.rstrip("\n") + "\n\n" + block) if text.strip() else block
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------ review rows ---

def subject_name(registry, subject_id):
    """-> the name a subject id reads as, or the id itself (a draft)."""
    subject = registry.get(subject_id)
    return (subject.name if subject is not None and subject.name
            else subject_id)


def frames_named(workdir, registry, frames):
    """B4 -> {frame image: [names]} for each frame whose photo already carries
    a NAMED subject, read the way the confirm's dry run reads it
    (`photo_see.subjects_held`). A draft carries no name and is left out: it
    is the question being asked."""
    import photo_see
    held = photo_see.subjects_held(workdir, [f["image"] for f in frames])
    out = {}
    for image, (_source, ids) in held.items():
        names = [s.name for s in (registry.get(i) for i in ids)
                 if s is not None and s.name
                 and s.status == photo_subjects.STATUS_CONFIRMED]
        if names:
            out[image] = list(dict.fromkeys(names))
    return out


def displaced_line(source, held, new, add=False, same=False):
    """FIX8 F8-1 — `<photo>: <its name now> -> <after>`, one photo.

    `held` and `new` are display names (a draft shows its id). `add` is the
    writer's two-animal path, which keeps every name the photo had; otherwise
    the new name REPLACES what was held. The photo is the SOURCE file, never
    the sample a video was looked at through."""
    now = " + ".join(held) or "—"
    if same:
        return f"{Path(source).name}: {now} -> {now} (no change)"
    after = held + [n for n in new if n not in held] if add else new
    return f"{Path(source).name}: {now} -> {' + '.join(after)}"


def load_json(path, default=None):
    path = Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


def see_reports(workdir):
    """-> {batch number: (report, its directory)} for whatever has been seen."""
    out = {}
    for path in sorted((Path(workdir) / "classify").glob("batch-*/see-report.json")):
        report = load_json(path)
        if report and "batch" in report:
            out[int(report["batch"])] = (report, path.parent)
    return out


def batch_observations(registry):
    """-> {batch: [(subject, evidence entry), ...]} from the registry's own
    per-batch evidence. The registry is the record of what was observed; the
    table only reads it."""
    out = {}
    for subject in registry.subjects:
        for entry in subject.record.get("evidence") or []:
            batch = entry.get("batch")
            if batch is None:
                continue
            out.setdefault(int(batch), []).append((subject, entry))
    for rows in out.values():
        rows.sort(key=lambda t: t[0].subject_id)
    return out


def build_rows(workdir, registry, profile, rmsg):
    """One row per batch, columns 1-5 of the TEMPLATE."""
    batches = load_json(Path(workdir) / "batches.json", {}) or {}
    reports = see_reports(workdir)
    observed = batch_observations(registry)
    rows = []
    for batch in batches.get("batches", []):
        n = int(batch["batch"])
        report, _dir = reports.get(n, (None, None))
        files = int(batch.get("files") or batch.get("count") or
                    (report or {}).get("coverage", {}).get("batch_files") or 0)
        seen = len((report or {}).get("selected") or [])
        clusters = len((report or {}).get("clusters") or [])

        facts, subjects = [], []
        for subject, entry in observed.get(n, []):
            # TEMPLATE column 4's three tags: `new` = first sighting,
            # `again` = a draft reinforced, `known` = matched a confirmed fact.
            tag = {"reinforced": "again", "known": "known"}.get(
                entry.get("state") or "new", "new")
            shown = subject_display(subject, profile, rmsg)
            facts.append(rmsg[f"review_fact_{tag}"].format(
                subject=f"{shown} ({subject.subject_id})",
                files=entry.get("files", 0)))
            subjects.append(shown)
        scene = (rmsg["review_scene"].format(
                    subjects=rmsg.get("review_subject_separator", ", ")
                             .join(subjects),
                    clusters=clusters, seen=seen, files=files)
                 if subjects else
                 rmsg["review_scene_none"].format(seen=seen, files=files))
        rows.append({"batch": n, "from": batch.get("from", ""),
                     "to": batch.get("to", ""), "files": files, "seen": seen,
                     "facts": facts or [rmsg["review_no_facts"]],
                     "scene": scene, "ask": []})
    return rows


# -------------------------------------------------------------- questions ---

class RefusalChannel(list):
    """`cmd_confirm`'s refusal channel, which also books WHICH drafts each
    refused row was about.

    ⭐ Doc 4 v4, signed 2026-08-20: *a refused row leaves its drafts exactly as
    they were before the page was rendered — not booked into layer 2, and
    re-asked at the next round. A refusal is the ENGINE's failure, never the
    owner's silence.* Layer 2 is `asked_before()`, which reads the review
    FILES, so the only thing that can un-book an id is another fact written
    beside them — and the id has to reach the writer from the site that
    refused.

    ⛔ It is per ROW and never per page. `about` is set to the ids the row
    being judged names, at each point in `cmd_confirm` where the scope changes,
    and every `refusals.append()` between two of those points books that scope.
    A page-wide set would un-book the tiles the owner simply left out —
    DEFERRED, which is a different outcome with a different rule (they return
    when their evidence grows) — and the four outcomes are specified never to
    collapse into one another.

    A refusal about a record that is not a draft books an id nothing reads:
    layer 2 only ever suppresses a record still in `registry.drafts`, so an
    id that was confirmed or rejected by another row on the same page is
    harmless here. That asymmetry is why over-booking is cheap and
    under-booking is not."""

    def __init__(self):
        super().__init__()
        self.about = []
        self.ids = set()

    def append(self, message):
        super().append(message)
        self.ids.update(self.about)


def record_refusals(workdir, checkpoint, subject_ids, src=None, by=None):
    """Write one refusal line into the work dir. -> the ids booked.

    ⚠️ `--go` only, like every other write: a dry run refuses on paper and
    nothing was booked as asked by it either."""
    ids = sorted(set(subject_ids))
    if not ids:
        return []
    # A batch page is keyed by its page id, a checkpoint page by its number.
    where = ({"page": checkpoint} if isinstance(checkpoint, str)
             else {"checkpoint": int(checkpoint)})
    line = json.dumps({"at": datetime.now().strftime("%Y-%m-%d"), **where,
                       "src": src, "by": by, "subject_ids": ids},
                      ensure_ascii=False)
    path = Path(workdir) / REFUSED_NAME
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return ids


def refused_rows(workdir):
    """-> {subject_id: {checkpoints whose page held a row about it that was
    refused}}.

    Keyed on the CHECKPOINT so the exemption spends itself. A refusal at C1
    un-books C1's booking and nothing later: if C2 renders the draft again and
    the owner leaves it out, C2 books it as deferred and it stays deferred,
    which is the outcome the owner chose that time."""
    out = {}
    path = Path(workdir) / REFUSED_NAME
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        key = row.get("page") or int(row.get("checkpoint", 0))
        for subject_id in row.get("subject_ids") or []:
            out.setdefault(subject_id, set()).add(key)
    return out


def asked_before(workdir):
    """-> {subject_id: (checkpoint, THAT SUBJECT'S OWN obs_count when it was
    rendered)} from the review files already written into this work dir. Layer
    2 of the dedupe.

    F16, and the number is the whole point. This used to record the BLOCK's
    obs_count against every id on it. Under `Group it` every block is
    multi-member by construction, so each member's deferral bar became the
    sum of the group's evidence: a member needed roughly N times its own
    evidence before its question could return. C2 would then look beautifully
    suppressed — as an artifact of an inflated bar, not of the mechanism
    working. So the render emits a per-tile `obs_count:` map and this reads
    each member's own value; a legacy block with one scalar still applies that
    scalar to every id on it, which is all a pre-F16 file can say.

    ⚠️ SNS-5 — this stays a PURE READER of the review files on disk, and that
    is why the withdrawal exemption is not here. What the files say is a fact:
    the subject WAS rendered at C1, and no later decision changes that. What
    a withdrawal changes is whether that fact may still suppress, which is a
    question about the bar, so the exemption sits on the bar in
    `build_questions()` — see `photo_subjects.REOPENED_FLAG`. Before it, the
    debt this docstring recorded when un-confirm shipped was live: the log
    layer re-opened the question and this one held it shut inside the work dir
    where the wrong name was typed, until evidence grew — and evidence is
    exactly what a subject named wrongly may never gain again.

    The same-checkpoint rule (`checkpoint > prior[0]`, so the first block
    sorted wins a tie) is LEFT ALONE deliberately. It was load-bearing only
    because two blocks at one checkpoint could carry the same id with
    different sums; with the count recorded per member, and one question per
    kind, an id appears in at most one block per checkpoint and the tie-break
    is inert. Introducing a new one here would rest on exactly the kind of
    undocumented ordering F15 refused to build on.

    ⭐ **A REFUSED row was never booked, and that is why the subtraction is
    here rather than on the bar.** SNS-5's withdrawal exemption sits in
    `build_questions()` because what a withdrawal changes is whether a real
    booking may still suppress. A refusal changes something earlier: doc 4 v4
    says the drafts are left *exactly as they were before the page was
    rendered*, so the booking is not a fact this reader may report at all.
    Putting it here also puts it in front of `sns_round()`, which asks whether
    a tile is absent from THIS map to decide whether it is new material — and
    a fix that moved only the bar would render the question into a round that
    is then withheld, which is 0 questions on the fresh page and the measured
    symptom verbatim."""
    refused = refused_rows(workdir)
    out = {}
    for path, checkpoint in booked_pages(workdir):
        for block in parse_review(path.read_text(encoding="utf-8")):
            for subject_id in block["subject_ids"]:
                if checkpoint in refused.get(subject_id, ()):
                    continue
                prior = out.get(subject_id)
                obs = block["obs_by_id"].get(subject_id,
                                             block.get("obs_count") or 0)
                if (prior is None
                        or booking_order(checkpoint) > booking_order(prior[0])):
                    out[subject_id] = (checkpoint, obs)
    return out


def subject_looks(subject):
    """Every look this subject's evidence holds, deduped on `vec_ref` and in
    record order. First writer wins, because `vec_ref` is the content sha and
    two looks carrying one ref are one photograph seen twice.

    The registry keeps its own copy of this walk (`_looks_by_ref`) for the
    partition. This one returns a LIST rather than a map because a tile's
    frames have an order the owner sees and answers in."""
    out, seen = [], set()
    for entry in subject.record.get("evidence") or []:
        for look in entry.get("looks") or []:
            ref = look.get("vec_ref")
            if ref and ref not in seen:
                seen.add(ref)
                out.append(look)
    return out


CROP_DIR = "review-crops"
# Q3 — marks the end page's "shown whole" line for photo_review_page.
WHOLE_MARK = "<!-- whole -->"
# Marks the end page's "a photo the pet is in" line for photo_review_page.
SHARED_MARK = "<!-- shared -->"
# HIL-4 — marks the two-step lines, which the web page prints verbatim.
HOWTO_MARK = "<!-- how-to -->"
# W2-7 — the one line beside a question's 2+ animal photo, read by the web
# page like the how-to lines. Display only: it starts with no field key.
SEVERAL_MARK = "<!-- several -->"
# U2-13 — what a web page says for a frame's place: the home/away word only.
WEB_MARK = "<!-- web: {} -->"


class FrameCrops:
    """R3b — turns a work dir's identity index into the two things a tile
    needs about each frame: **what the animal in it looks like on its own**,
    and **how many animals are in it**.

    ⭐ The whole point is that both facts reach the owner BEFORE they answer.
    In UAT01 the page rendered five whole frames as a single claim and offered
    a frame-level verb to refute it, while supplying no per-frame evidence at
    all — no score, no outlier mark, no multi-animal flag. The owner opened
    one frame, recognised the cat, and confirmed all five; three were wrong
    and two of those were wrong because the frame held both cats. The failure
    was invisible at decision time and permanent afterwards (LL-PHO-136).

    ⛔ The crop is re-derived through `photo_embed.convert_to_thumbnail`, the
    SAME conversion `photo_identity` cropped, and the stored box is applied to
    it unchanged. Scaling the box onto the classify sample instead would be
    cheaper and is wrong twice over: the two thumbnails are different sizes,
    and there is no guarantee they agree about EXIF orientation — the defect
    that contaminated every index built before `49cd0f6`. A crop that is off
    by a rotation is worse than no crop, because it looks like an answer.

    ⚠️ Bounded to looks whose file is in THIS work dir's identity index. A
    confirmed subject's sightings span dumps (F14); the end page opens one
    of these per earlier dump (`crop_root` = the page's own dir, Q3). A look
    no index covers carries no claim at all — "no crop" and "no animal" must
    never render the same — and the end page says it is shown whole.
    """

    def __init__(self, workdir, pack=None, crop_root=None):
        self.workdir = Path(workdir) if workdir else None
        # Q3 — an earlier dump's crops are cut into the page's OWN work dir,
        # so a relative link resolves from where the page sits and nothing
        # is written into the other dump.
        self.crop_root = Path(crop_root) if crop_root else self.workdir
        self.pack = pack
        self.detections = {}
        self.kinds = {}
        self.filetypes = {}
        self.cache = {}
        self.available = False
        if self.workdir is None:
            return
        self.detections, _space = photo_identity.load_detections(
            self.workdir / "embed", pack)
        if not self.detections:
            return
        self.available = True
        # `kind` picks sips vs qlmanage and `FileType` catches the mismatched
        # extension, exactly as photo_identity reads them — see its own note
        # on why the two cannot be collapsed into one.
        embeddings = self.workdir / "embed" / "embeddings.csv"
        if embeddings.exists():
            with open(embeddings, newline="") as f:
                self.kinds = {r["SourceFile"]: r.get("kind")
                              for r in csv.DictReader(f)}
        manifest = self.workdir / "manifest.csv"
        if manifest.exists():
            with open(manifest, newline="") as f:
                self.filetypes = {r["SourceFile"]: r.get("FileType")
                                  for r in csv.DictReader(f)}

    def describe(self, look):
        """-> {"crops": [work-dir-relative paths], "det_count": int} for one
        look, or None when this work dir's index has nothing to say about it.

        ⛔ None and `det_count` 0 are DIFFERENT answers — "not indexed here"
        versus "indexed, and there is no animal in it" — and the renderer
        must never collapse them into one sentence.
        """
        path = (look or {}).get("path")
        if not self.available or not path:
            return None
        rows = self.detections.get(path)
        if rows is None:
            return None
        identified = [(r, i) for i, (r, _v) in enumerate(rows)
                      if r.get("status") == photo_identity.STATUS_OK]
        if not identified:
            return {"crops": [], "det_count": 0}
        count = int(identified[0][0].get("det_count") or len(identified))
        return {"crops": self._render(path, look, identified), "det_count": count}

    def identity_vector(self, look):
        """-> the PRIMARY detection's identity vector for one look, else None.

        U2-12's input. `det_index` 0 and nothing else: index 0 is the
        highest-scoring animal in the frame and the only one a group-level
        comparison can use, because a frame's second animal belongs to some
        OTHER subject and comparing it here would manufacture exactly the
        disagreement this check exists to report.
        """
        path = (look or {}).get("path")
        if not self.available or not path:
            return None
        # Q8-c: the first detection LEFT after the not-an-animal marks, which
        # is det_index 0 whenever nothing is marked.
        for row, vec in self.detections.get(path) or []:
            if row.get("status") == photo_identity.STATUS_OK:
                return vec
        return None

    def _render(self, path, look, identified):
        import tempfile
        from PIL import Image, ImageOps

        ref = look.get("vec_ref") or Path(path).stem
        out_dir = self.crop_root / CROP_DIR
        wanted = [(r, f"{ref}_d{r.get('det_index') or 0}.jpg")
                  for r, _i in identified]
        missing = [(r, n) for r, n in wanted if not (out_dir / n).exists()]
        if missing:
            out_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as tmp:
                thumb, _cause = photo_embed.convert_to_thumbnail(
                    path, Path(tmp), f"c{ref}", self.kinds.get(path),
                    self.filetypes.get(path))
                if thumb is None:
                    return []
                try:
                    image = ImageOps.exif_transpose(
                        Image.open(thumb)).convert("RGB")
                    for row, name in missing:
                        box = [float(v) for v in (row.get("box") or "").split(",")]
                        if len(box) != 4:
                            continue
                        image.crop(tuple(box)).save(out_dir / name, "JPEG",
                                                    quality=88)
                except Exception:                          # noqa: BLE001
                    # A crop that cannot be made is not an error worth
                    # stopping a checkpoint for: the frame renders whole, as
                    # it always did, and the shared-frame count still reaches
                    # the page because it comes from the CSV, not the image.
                    return []
                finally:
                    Path(thumb).unlink(missing_ok=True)
        return [f"{CROP_DIR}/{n}" for _r, n in wanted if (out_dir / n).exists()]


class FrameWhere:
    """F10 — one short phrase per FRAME saying where it was taken: at which
    registered home, or how far from the nearest one.

    ⭐ The naming checkpoint asks for a permanent decision, and in UAT01-4 both
    near-misses were about PLACE, not looks: two frames the owner read as a
    day out were 0.2 km from home, and a lookalike at a relative's house was
    119.5 km away. The two houses hold lookalikes of each other's animals, so
    appearance cannot separate them and location can.

    ⛔ Per FRAME, never the batch's place — a batch is a day cluster, and its
    label is exactly what misled the owner. A frame with no fix says so and
    borrows nothing.

    ⛔ Never a coordinate: the owner's own home label (ADR 0001) and a
    distance, nothing else. An unlabelled nearest home is named as such,
    never by reaching past it for a farther labelled one.

    The radius is the pack's `away_km`, the everyday "same place" rule
    (`photo_cluster.PACK_DEFAULTS`), NOT the privacy ring. Homes are the
    UNFILTERED `labelled_home_points()`, so a relative's house reads by its own
    label. One GPS predicate, `photo_cluster.parse_gps`; each look's own work
    dir's manifest, cached, because a subject's looks span dumps."""

    def __init__(self, profile, rmsg):
        self.rmsg = rmsg
        self.homes = photo_profile.labelled_home_points(profile)
        self.away_km = float(photo_profile.get(
            profile, "cluster_defaults", "away_km",
            default=photo_cluster.AWAY_KM_DEFAULT))
        self.manifests = {}

    def _row(self, path, workdir):
        if not (path and workdir):
            return None
        if workdir not in self.manifests:
            rows, manifest = {}, Path(workdir) / "manifest.csv"
            if manifest.is_file():
                with open(manifest, newline="") as f:
                    rows = {r["SourceFile"]: r for r in csv.DictReader(f)}
            self.manifests[workdir] = rows
        return self.manifests[workdir].get(path)

    def phrase(self, frame):
        return self.place(frame)[0]

    def place(self, frame):
        """-> (the text page's phrase, the web page's word or "").

        U2-13 — a web page may be published, so it says only "at a home you
        named" or "away from home", decided by the same `away_km` test; the
        km and the home label stay on the text page. U3-3 — the home words are
        the same for every registered home, lived in or visited, labelled or
        not. A phrase with neither is its own web word."""
        rmsg = self.rmsg
        row = self._row(frame.get("path"), frame.get("workdir"))
        if row is None:
            return (rmsg["review_frame_where_unknown"],) * 2
        point = photo_cluster.parse_gps(row)
        if point is None:
            return (rmsg["review_frame_where_none"],) * 2
        when = photo_cluster.parse_date(row)
        near = photo_cluster.nearest_home(
            point, when.strftime("%Y-%m-%d") if when else "", self.homes)
        if near is None:
            return (rmsg["review_frame_where_no_home"],) * 2
        km, label = near
        if km <= self.away_km:
            return ((rmsg["review_frame_where_home"].format(home=label) if label
                     else rmsg["review_frame_where_home_unlabelled"]),
                    rmsg["review_frame_where_web_home"])
        return ((rmsg["review_frame_where_away"].format(km=f"{km:.1f}",
                                                        home=label) if label
                 else rmsg["review_frame_where_away_unlabelled"].format(
                     km=f"{km:.1f}")),
                rmsg["review_frame_where_web_away"])


def where_suffix(frame):
    """The F10 phrase as it trails a frame's number on the page. ` · ` is
    what `photo_review_page.RE_IMG` splits on, so the page JS prints the
    phrase this module wrote rather than a second copy of it (LL-PHO-188)."""
    if not frame.get("where"):
        return ""
    web = frame.get("where_web")
    return f" · {frame['where']}" + (f" {WEB_MARK.format(web)}" if web else "")


def uncropped_frames(questions, represented):
    """F22 — the frames this dump's identity index found an animal in, but
    whose crop could not be made. -> [frame].

    ⛔ Such a frame is never shown whole instead: the owner then names the
    whole photo while the only box may sit on another animal (F22: a
    stranger's dog, the owner's own dog missed).

    ⭐ DECISION (Lead, 20260929), not a gap: a frame this dump's index does
    not cover (`det_count` None — another dump's sighting, F14) still renders
    whole, as it always did. It never had a crop to lose. `det_count` 0 (no
    animal found) has no crop to make either."""
    frames = [f for q in questions for t in q["tiles"] for f in t["frames"]]
    frames += [f for record in represented.get("remembered") or []
               for f in record.get("frames") or []]
    return [f for f in frames if (f.get("det_count") or 0) >= 1
            and not f.get("crops")]


def uncropped_refusal(out, frames):
    names = sorted({Path(f.get("path") or f["image"]).name for f in frames})
    return (f"⛔ {out.name} was not written: {len(names)} photo(s) hold an "
            "animal the identity index found, but no crop of it could be made "
            f"here: {', '.join(names)}.\n"
            "Showing the whole photo instead would hide WHICH animal the "
            "question is about. This python most likely cannot open the photo "
            "(a HEIC photo needs pillow-heif). Run this step again with the "
            f"repo .venv, `{photo_platform.quoted(photo_platform.venv_python())}`; `photo_run.py "
            "finish` uses it by itself when it exists.")


def tile_frames(subject, sheet, workdir=None, crops=None, where=None):
    """-> (frames, [reason codes]) — a tile's contact sheet RESOLVED BACK to
    the looks behind it, so every frame on the page carries a storage key.

    ⭐ SNS-1b item 1 in one function. A contact-sheet entry is a thumbnail
    path and nothing else; a `pick:` on it has to reach a `vec_ref`, and the
    only honest way to get one is to find the look that was shown on that
    thumbnail. A frame that resolves to no look is therefore NOT RENDERED at
    all — the alternative is a number the owner can type that promotes
    nothing, which reads exactly like a number that worked.

    ⛔ The frames are not simply taken from the looks instead, which would be
    shorter and is wrong: `contact_sheet` is what the record says was PUT IN
    FRONT OF A HUMAN, and it is the field the frameless-subject gate reads
    (SNS-12). Building the page off the evidence list would show frames a
    see-run never selected and would make that gate unreachable.

    The image is `look_image()`'s answer rather than the stored string, for
    the reason that function's docstring gives: a look from an earlier dump
    renders as an absolute path, and the stored string is relative to the dump
    it was seen in — which resolves to nothing from where this table sits.

    Every drop is REPORTED, never silent: the codes come back and the renderer
    says how many frames a tile lost and why."""
    looks = subject_looks(subject)
    frames, reasons, used = [], [], set()

    def note(code):
        if code not in reasons:
            reasons.append(code)

    for item in sheet:
        name = Path(item).name
        candidates = [look for look in looks
                      if look.get("sample") == name
                      and look["vec_ref"] not in used]
        if not candidates:
            note("no_looks")
            continue
        exact = [look for look in candidates
                 if look_image(look, workdir) == item]
        if len(exact) == 1:
            chosen = exact[0]
        elif len(candidates) == 1:
            chosen = candidates[0]
        else:
            # Two sightings from two dumps under one file name. Which
            # photograph this frame is cannot be decided, and deciding it by
            # order is how a pick lands on the wrong one.
            note("two_looks")
            continue
        image = look_image(chosen, workdir)
        if image is None:
            note("no_thumbnail")
            continue
        used.add(chosen["vec_ref"])
        frame = {"vec_ref": chosen["vec_ref"], "image": image,
                 "path": chosen.get("path"),
                 "workdir": chosen.get("workdir"),
                 # R3b. `crops` empty and `det_count` None mean "this work
                 # dir's index has nothing to say about this frame" — NOT
                 # "there is no animal in it". The renderer keeps them apart.
                 "crops": [], "det_count": None}
        told = crops.describe(chosen) if crops is not None else None
        if told is not None:
            frame["crops"] = told["crops"]
            frame["det_count"] = told["det_count"]
        if where is not None:
            frame["where"], frame["where_web"] = where.place(frame)
        frames.append(frame)
    return frames, reasons


def build_questions(registry, workdir, pack, profile, rmsg, last_ask=False,
                    batch=None):
    """-> (questions, suppressed, round_deferred, held_for_final). ONE `Group
    it` question per `kind`, ranked by blast radius, each carrying that kind's
    unsettled drafts as numbered tiles (ONB-13a).

    ⭐ **`last_ask` is doc 8 amendment (b), signed 2026-08-27.** It says one
    fact — this is the checkpoint that ends the dump, and the guaranteed round
    fires here — and what it buys is that layer 2 stops holding a question
    shut. See the exemption below for what it is repairing.

    `held_for_final` is the drafts layer 2 suppressed at a checkpoint that was
    NOT the last one: the ones the final round will ask about. Returned rather
    than counted by the caller, because `waiting` is the number the page
    prints beside the promise that the last round comes back to them, and a
    promise beside a number that excludes them is the contradiction (b) was
    approved to close.

    Question count is bounded BY CONSTRUCTION rather than by a budget — at
    most one per kind present — which is what V2-7 wanted when it refused to
    cap questions per checkpoint.

    ⭐ **TILE count is bounded by `{tiles_per_round}` (12), and that ceiling
    is ABOVE the per-kind split** (2026-08-21). A question count that cannot
    exceed the number of kinds says nothing about what one interruption costs:
    the first whole-dump measurement found ONE round carrying 7 questions and
    45 tiles in a shape that permits 12 x 7 = 84. So every renderable draft of
    every kind is ranked TOGETHER on one blast-radius scale, the top
    `{tiles_per_round}` survive, and only the survivors are grouped into
    per-kind questions. A kind can therefore be shut out of a round entirely —
    accepted, and the reason it is safe is that being cut is a DEFERRAL: the
    draft is not booked as asked, it is written into `suppressed` with its own
    sentence, and it comes back at the next checkpoint.

    `round_deferred` is that count, returned separately rather than stashed on
    a question, because it is a property of the ROUND and no single question
    owns it — the page says it once, under all of them.

    The grouping key is `subject.kind`, the field the draft store already
    carries and `kind_word()` already renders. ONB-13a's parenthetical reads
    "person / pet / object", but the pack's zero-shot vocabulary puts a
    SPECIES there when it knows one, so two species are two questions. That is
    the plain reading of the field and it keeps the honesty marker intact; it
    is a divergence from the parenthetical, not from the mechanism."""
    settled = settled_subjects(pack)
    seen_before = asked_before(workdir)
    # ⚠️ ONE flat list now, not `by_kind` — the ranking the ceiling cuts on has
    # to see every kind at once, and a dict of per-kind lists is exactly the
    # view that cannot. Grouping happens AFTER the cut, below.
    renderable, suppressed, held_for_final = [], [], []
    # Read BEFORE the loop now, because the frameless gate below no longer
    # asks whether the record lists a contact sheet — it asks whether the
    # frames that sheet names can be resolved to looks, and how many of them
    # this question would render is part of that question.
    frames = int(registry.defaults.get(
        "contact_frames_per_draft",
        photo_subjects.DEFAULT_THRESHOLDS["contact_frames_per_draft"]))

    # ONCE per checkpoint, not once per tile: it opens the identity index and
    # two CSVs, and a round renders up to `{tiles_per_round}` tiles over them.
    crops = FrameCrops(workdir, pack)
    where = FrameWhere(profile, rmsg)

    for subject in sorted(registry.drafts,
                          key=lambda s: (-int(s.record.get("files", 0)),
                                         s.subject_id)):
        if batch is not None and batch not in subject.observed_in:
            # G6 (R7) — a batch page asks about the drafts OBSERVED in its
            # batch. The others are not this page's to list, even as withheld.
            continue
        if subject.subject_id in settled:
            suppressed.append((subject.subject_id,
                               f"already {settled[subject.subject_id]}"))
            continue
        if subject.record.get(SHARED_FRAMES_FLAG):
            # G6-6d (G2) — answered on a page, one name per animal.
            suppressed.append((subject.subject_id,
                               "its photos hold 2+ animals and were named "
                               "on a page — not asked again"))
            continue
        prior = seen_before.get(subject.subject_id)
        reopened = bool(subject.record.get(photo_subjects.REOPENED_FLAG))
        if prior and subject.obs_count <= prior[1] and not reopened:
            # ⭐ SNS-5's third layer, and the exemption is what makes a
            # withdrawal reach a work dir that already asked. `unconfirm()` and
            # `revive()` clear the STATUS, and `record_unconfirm()` /
            # `record_revive()` clear the memory LOG — but the review file that
            # booked this id at C1 is still on disk, so without this the
            # subject was askable by `is_draft`, cleared in the log, and shut
            # out here: withdrawn and invisible at once, which is the trap the
            # other two layers were fixed to avoid.
            #
            # The exemption is deliberately not permanent. It lasts until the
            # question is ANSWERED again — `cmd_confirm` pops the flag on both
            # answer paths — so a withdrawn subject comes back at every
            # checkpoint until the owner deals with it, and every subject
            # nobody withdrew keeps the bar it always had.
            #
            # ---- doc 8 amendment (b) — the LAST ask, signed 2026-08-27 -----
            #
            # ⛔ MEASURED 20260827, Tier 3 round 1 defect D7: the owner's
            # answer named seven frames of one subject, five of them were
            # refused by D6, and layer 2 then shut those five drafts for good.
            # C2, C3, C4 and C5 were identical — *0 question(s) carrying 0
            # tile(s), 7 suppressed* — while the page above them promised
            # *the last round of the dump asks about them*. Both cannot be
            # true: the dump is fully processed, so `no new evidence` is a
            # condition that can never be met again, and the guaranteed final
            # round fired into an empty page.
            #
            # So the bar comes down on the checkpoint that ENDS the dump, and
            # only there — once, on the same predicate `sns_round()` demotes a
            # second `--final` by, so a round that fires and a question that
            # is asked can never disagree.
            #
            # ⚠️ Scoped to THIS branch. `settled`, the two frameless gates and
            # the round ceiling below are untouched: a confirmed or rejected
            # subject has an answer, and a draft with no frame on disk cannot
            # be picked from whether the dump is ending or not.
            if not last_ask:
                held_for_final.append(subject.subject_id)
                suppressed.append((subject.subject_id,
                                   f"asked at {page_label(prior[0])}, "
                                   "no new evidence"))
                continue
        sheet = list(subject.record.get("contact_sheet") or [])[:frames]
        if not sheet:
            # Frames are the ONLY way an owner can notice that one cluster
            # holds two subjects, so a tile with none invites a name typed
            # blind — and a wrong merge is the error this whole question shape
            # exists to avoid. Dropped here rather than at render so it does
            # not consume a rendering slot either. Deferred, never rejected: it
            # returns as soon as the see-report puts a frame on disk.
            suppressed.append((subject.subject_id,
                               "no example photo on disk — not asked; still "
                               "ai-drafted, still askable"))
            continue
        shown, dropped = tile_frames(subject, sheet, workdir, crops, where)
        if not shown:
            # SNS-12's gate, one step further in than it used to reach. A
            # sheet whose every image resolves to no look is a sheet of
            # frames the owner cannot ACT on: `pick:` names a frame and a
            # frame has to carry a `vec_ref`, so a tile like this would render
            # numbers that promote nothing and say nothing about it. Same
            # answer as no sheet at all — deferred, still askable — and its
            # own sentence, because the two gaps have different repairs.
            suppressed.append(
                (subject.subject_id,
                 "no example photo on disk that this subject's own evidence "
                 "can key — not asked; still ai-drafted, still askable"))
            continue
        renderable.append((subject, prior, shown, dropped, len(sheet)))

    per_round = int(registry.defaults.get(
        "tiles_per_round",
        photo_subjects.DEFAULT_THRESHOLDS["tiles_per_round"]))
    per_question = int(registry.defaults.get(
        "drafts_rendered_per_question",
        photo_subjects.DEFAULT_THRESHOLDS["drafts_rendered_per_question"]))

    # ---- the ROUND ceiling, and it cuts BEFORE the kinds are separated -----
    # `renderable` is in the outer loop's total order (-files, subject_id) —
    # blast radius, the SPEC's ranking key, and the same key the per-kind slice
    # and the question sort below use. ONE SCALE, THREE PLACES, ONE KEY: no new
    # sort is introduced here, which is the whole determinism argument. A total
    # order is also what keeps two replays of one checkpoint byte-identical.
    #
    # ⛔ The cut is here and not inside the per-kind loop. Down there the top
    # `{n}` of each kind survive independently, which is 12 x K tiles for the
    # price of one interruption — the gap this parameter closes. Up here the
    # kinds compete, so a kind whose widest draft loses to twelve wider ones
    # elsewhere renders nothing at this checkpoint.
    # ⚠️ What "still askable" MEANS depends on whether another checkpoint is
    # coming, and on the last round of a dump one is not. ⛔ The ceiling still
    # cuts — `{tiles_per_round}` is SETTLED (20260821) and doc 8's amendment
    # gave it no scope — so what changes here is the SENTENCE and nothing
    # else: a draft cut by the ceiling on the final round comes back at the
    # next DUMP's first round, on its own record and under its own id, because
    # layer 2 reads the review files of one work dir and the next dump has
    # none. That is a real wait and it is said out loud rather than covered by
    # a promise the checkpoint cannot keep.
    # ⛔ D-23 — "still askable" is TRUE of the question and was read as a
    # promise about the record. The post-confirm sweep scores every open draft
    # against the subjects confirmed on this page, and a draft suppressed here
    # is an open draft: two of them were absorbed on one real run, both named
    # in this very comment as still askable. The qualification is added rather
    # than the sentence withdrawn, because the sentence's own claim — nobody
    # skipped it, nobody named it — survives an absorb intact.
    # ⛔ N17 — the page may claim only what it CONTROLS. This used to say "this
    # dump has no checkpoint left, so it is asked at the next dump's first
    # round", and that promise is not the engine's to make: a re-run of
    # `finish --go` passes `--final` again, SNS-4 demotes it to an ordinary
    # round judged on the floor, and drafts promised to the next dump get
    # asked in this one. Measured on a real run: 12 of 25 over-ceiling drafts
    # came back at the very next checkpoint.
    # ⛔ WORDING ONLY. `sns_round()` is unchanged and SNS-4's "demoted, judged
    # on the floor" clause is unchanged — the owner ruled on 20260920 that a
    # re-run MAY ask again, against both the builder's and the Lead's
    # recommendation. So the sentence stops promising and starts describing.
    still_askable = ("still ai-drafted; this is the last round this dump "
                     "starts on its own, so it is asked at the next dump's "
                     "first round — but a re-run of `finish --go` here may "
                     "ask again before then"
                     if last_ask else "still ai-drafted, still askable")
    still_askable += ("; unless this page's own answer turns out to name it, "
                      "which the next checkpoint lists")
    in_round, over_ceiling = renderable[:per_round], renderable[per_round:]
    for subject, _prior, _shown, _dropped, _n in over_ceiling:
        # ⚠️ NOT recorded as asked — same guarantee as the per-question defer
        # below, and its OWN SENTENCE because the two have different repairs.
        # This one is not "this kind had more than a question can hold"; it is
        # "the whole round was full", and what fixes it is the next checkpoint
        # or a bigger `{tiles_per_round}`, not a bigger question.
        suppressed.append(
            (subject.subject_id,
             f"beyond this round's tile ceiling — {per_round} tile(s) per "
             "round across every kind, ranked by blast radius; "
             + still_askable))

    by_kind = {}
    for entry in in_round:
        by_kind.setdefault(entry[0].kind or "", []).append(entry)

    questions = []
    for kind, members in by_kind.items():
        # Members arrive in the outer loop's total order (-files, subject_id),
        # which is blast radius — the SPEC's ranking key — and a total order is
        # also what keeps two replays of one checkpoint byte-identical.
        #
        # ⚠️ This slice is the SECOND bound and it can only bite when a pack
        # sets `{drafts_rendered_per_question}` below `{tiles_per_round}`: the
        # ceiling above already cut to `per_round` entries in total, so no kind
        # can hold more than that. At the shipped 12/12 it is subsumed — a
        # property of the two defaults, not a dead parameter (see the comment
        # on it in `photo_subjects.DEFAULT_THRESHOLDS`).
        rendered, deferred = members[:per_question], members[per_question:]
        for subject, _prior, _shown, _dropped, _n in deferred:
            # ⚠️ NOT recorded as asked. An unrendered draft was never in front
            # of the owner, so booking it into layer 2 would bury it behind a
            # bar it never earned. Engine-deferred is not owner-deferred.
            suppressed.append(
                (subject.subject_id,
                 f"not rendered at this checkpoint — {per_question} tile(s) "
                 "per question, ranked by blast radius; " + still_askable))
        tiles = []
        for position, (subject, prior, shown, dropped, on_sheet) \
                in enumerate(rendered, 1):
            tiles.append({
                "tile": position, "subject_id": subject.subject_id,
                "display": subject_display(subject, profile, rmsg),
                "files": int(subject.record.get("files", 0)),
                "batches": sorted(subject.observed_in),
                "obs_count": subject.obs_count,
                # The frames the owner picks from, each one carrying the
                # storage key behind it (SNS-1b item 1). `contact_sheet` stays
                # beside them as what those frames RENDER as — every reader
                # that only wants the images keeps working, and the two can
                # never disagree because one is derived from the other.
                "frames": shown,
                "contact_sheet": [f["image"] for f in shown],
                # U2-12 — does this tile's own evidence agree with itself?
                # Keyed on vec_ref because frame numbers are assigned in a
                # later pass over every question at once.
                "coherence": (photo_subjects.group_coherence(
                    [(f["vec_ref"], crops.identity_vector(f)) for f in shown])
                    if crops is not None else None),
                "unresolved": on_sheet - len(shown),
                "why_unresolved": dropped,
                "active": subject.record.get("active") or [None, None],
                "repeat": page_label(prior[0]) if prior else None,
            })
        if not tiles:
            continue
        word = kind_word(kind or None, profile, rmsg)
        files = sum(t["files"] for t in tiles)
        starts = [t["active"][0] for t in tiles if t["active"][0]]
        ends = [t["active"][1] for t in tiles if t["active"][1]]
        questions.append({
            "type": TYPE_GROUP_IT, "kind": kind, "kind_word": word,
            "tiles": tiles,
            "subject_ids": [t["subject_id"] for t in tiles],
            "files": files,
            "batches": sorted({b for t in tiles for b in t["batches"]}),
            "span": f"{min(starts) if starts else '?'} → "
                    f"{max(ends) if ends else '?'}",
            "deferred": len(deferred),
            "body": rmsg["review_q_group_it"].format(n=len(tiles), kind=word),
            "effect": rmsg["review_effect_group_it"].format(files=files),
        })

    # Question ORDER follows (-files, kind) and nothing else — `files` summed
    # over the tiles that SURVIVED the ceiling, so the order is read off what
    # the page actually shows rather than off what the kind holds. Total,
    # because `by_kind` keys on `kind` and one kind yields one question, so the
    # tie-break can never be reached by two different questions. ⛔ Never
    # `by_kind` insertion order: that is a dict built from the draft ranking
    # and it would make the page's order an artifact of which kind happened to
    # own the widest draft.
    questions.sort(key=lambda q: (-q["files"], q["kind"]))
    for i, q in enumerate(questions, 1):
        q["id"] = f"Q{i}"
    return questions, suppressed, len(over_ceiling), len(held_for_final)


# --------------------------------------------------- SNS-4: round cadence ---

def rounds_fired(workdir):
    """How many SNS rounds this work dir has already asked. -> int.

    Read off the review files themselves — a file carrying a question block IS
    a round that was put in front of the owner — rather than from a counter
    kept beside them. Same doctrine as `asked_before()`, and for the same
    reason: what the files say is a fact, and a counter can disagree with the
    pages that were actually written. A withheld round writes no block, so it
    is not counted, which is what "nothing the budget withholds is booked as
    asked" means at the level of the budget itself."""
    # ⛔ Checkpoint pages only. A `P-B*.md` batch page is booked, never charged.
    fired = 0
    for path in sorted(Path(workdir).glob(REVIEW_GLOB)):
        if parse_review(path.read_text(encoding="utf-8")):
            fired += 1
    return fired


def final_round_asked(workdir):
    """Has the guaranteed end-of-dump round already been put to the owner in
    this work dir? -> bool.

    ⭐ **Because `finish --go` is re-runnable and always has been.** A plan
    whose batches are already done is skipped, so re-running `finish` on a
    dump is a normal, safe thing to do — and the conductor passes `--final`
    every time it runs. Without this, each re-run fired another guaranteed
    round: `rounds_fired()` counts every page carrying a block, so three
    re-runs would spend three of the four rounds in `{sns_rounds_per_dump}`
    and every later floor-triggered round would be withheld against a budget
    the owner never saw spent.

    ⛔ Read off the pages, never off a counter, for `rounds_fired()`'s reason
    exactly: what the files say is a fact. A page the owner deleted is a round
    that is allowed to ask again, which is the honest reading of a deleted
    page and not a special case."""
    for path in sorted(Path(workdir).glob(REVIEW_GLOB)):
        if FINAL_MARKER in path.read_text(encoding="utf-8"):
            return True
    return False


def sns_round(workdir, questions, seen_before, registry, profile, final=False,
              held_for_final=0):
    """SNS-4 — does an SNS round fire at this checkpoint, and why?

    -> {fire, why, round, rounds, cap, floor, new, waiting}.

    ⚠️ **`held_for_final` is counted into `waiting` and never into `new`**, and
    that is doc 8 amendment (b)'s other half. `waiting` is the number printed
    beside the sentence *the last round of the dump asks about them*, so it has
    to be the drafts that round will actually ask about — which is the tiles
    this checkpoint holds PLUS the ones layer 2 shut. Measured 20260827 (D7):
    the page said *0 subject(s) are waiting … the last round of the dump asks
    about them* with seven ids in the suppression block twelve lines below it.
    ⛔ Not into `new`: they were asked at an earlier checkpoint, and counting
    them as newly discovered would fire rounds on the floor forever.

    ⭐ **The engine decides, and it decides HERE.** ⛔ Not in `photo_run.py`:
    the evidence this rests on — how many frequently-seen subjects are newly
    discovered, at what blast radius, since which round — is visible only from
    the registry and the work dir's own pages, so a conductor that cannot see
    either would be choosing on a summary of a thing it does not hold. That is
    the same mistake as asking the operator to judge evidence they cannot see,
    which is the alternative SNS-4 rejected.

    ⚠️ **`final` is passed IN, and that is not the same thing.** Whether the
    dump is over is a fact only the caller knows; what to do about it is
    decided here, along with everything else. One fact crosses the boundary,
    no decision does.

    Three ways a checkpoint resolves, and each one is SAID (see
    `render_review`, which prints the reason in the owner's own language, and
    `cmd_review`, which prints it to the operator):

      * **floor met** — enough new material to be worth interrupting for. The
        round is charged against the dump's budget;
      * **end of dump** — the guaranteed round, whether or not the floor was
        met, and NOT charged. Without the exemption the two rules contradict
        each other on any dump that spends its budget early, and subjects that
        only became frequent late would be stranded until the next dump.
        ⚠️ ONCE per dump: a second `--final` over a work dir that has already
        asked its guaranteed round is demoted to an ordinary checkpoint (see
        `final_round_asked()`), because `finish --go` is re-runnable and a
        dump does not end twice;
      * **withheld** — either the floor was not reached or the budget is
        spent. Nothing is rejected, nothing is booked as asked, and the reason
        says which of the two it was.

    ⛔ A withheld round renders no question block AT ALL — not the tiles, and
    not the `subjects:` / `obs_count:` / `frames:` lines under them.
    `asked_before()` reads every review file in the work dir and books every id
    on those lines into layer 2, so a page that printed the mapping without
    asking the question would bury those drafts behind a bar they never
    earned: withheld and suppressed at once, which is the trap SNS-5 had to
    dig three layers out of."""
    floor = int(photo_profile.get(profile, "memory", "new_fss_floor",
                                  default=DEFAULT_NEW_FSS_FLOOR))
    cap = int(photo_profile.get(profile, "memory", "sns_rounds_per_dump",
                                default=DEFAULT_SNS_ROUNDS_PER_DUMP))
    fired = rounds_fired(workdir)
    new, waiting = 0, 0
    for question in questions:
        for tile in question["tiles"]:
            waiting += 1
            # LITERAL — the tile came from `build_questions()`, which reads
            # `registry.drafts`, and what is read here is the record's own
            # REOPENED flag. A tombstone is in neither place.
            subject = registry.get_literal(tile["subject_id"])
            # A REOPENED subject counts as newly discovered, and it has to.
            # `unconfirm()` and `revive()` put a subject back in the question
            # loop, which is new material by every measure except the one this
            # counts — the id is on an older page, so it is not "new" to
            # `asked_before()`. Reading it as old would make the withdrawal
            # reachable only at the end of a dump, which is the correction
            # path being slow exactly when it is needed most.
            if tile["subject_id"] not in seen_before or (
                    subject is not None
                    and subject.record.get(photo_subjects.REOPENED_FLAG)):
                new += 1
    # ⚠️ ONE guaranteed round per dump, not one per invocation. `final` says
    # the dump is over; it does not say this is the first time the caller has
    # said so, and `finish --go` is re-runnable. A dump that is over twice is
    # still one dump, so a second `--final` is demoted to an ordinary
    # checkpoint and judged on the floor and the budget like any other. ⛔ The
    # demotion is a CADENCE decision and belongs here, beside the evidence,
    # not in the conductor that only knows the dump ended.
    already = bool(final and final_round_asked(workdir))
    state = {"round": fired + 1, "rounds": fired, "cap": cap, "floor": floor,
             "new": new, "waiting": waiting + held_for_final,
             "final_already": already}
    if final and not already:
        return {**state, "fire": True, "why": "final"}
    if new >= floor and fired < cap:
        return {**state, "fire": True, "why": "floor"}
    if new >= floor:
        return {**state, "fire": False, "why": "cap"}
    return {**state, "fire": False, "why": "floor"}


ROUND_REASON_KEY = {(True, "floor"): "review_round_fired_floor",
                    (True, "final"): "review_round_fired_final",
                    (False, "floor"): "review_round_withheld_floor",
                    (False, "cap"): "review_round_withheld_cap",
                    # G6 — a batch page is not a round: it asks when its
                    # batch has something to ask, and is never charged.
                    (True, "page"): "review_page_asks",
                    (False, "page"): "review_page_nothing"}


# ------------------------------------------- SNS-5: the path back into a --
# ------------------------------------------- round, for what is remembered --

def look_image(look, workdir=None):
    """-> the thumbnail a look was judged on, or None when it is not on disk.

    **Work-dir-relative when the photo is under the work dir being reviewed,
    absolute otherwise**, and the common case is the first one. A draft's tile
    renders `classify/batch-01/samples/…` because `observe_draft_subject()`
    stores `contact_sheet` that way, and the review file is written INTO the
    work dir — so a relative link resolves when the owner opens the table
    where it sits. An absolute link is treated as root-relative by common
    markdown previewers and shows a blank, which in THIS section is worse than
    anywhere else in the file: a blank frame beside "leave blank if it is
    still right" is a glance-yes against nothing, the exact failure SNS-6's
    worst-frame rule exists to prevent.

    The absolute form is the fallback and it is still needed: a confirmed
    subject's sightings span DUMPS — accumulating them is what F14 built — and
    a path relative to the work dir being reviewed would point at nothing for
    every look that came from an earlier one. Both ends are resolved before
    they are compared, because a see-report path and a work-dir path can
    disagree on a symlinked prefix while naming one file."""
    report, sample = look.get("see_report"), look.get("sample")
    if not (report and sample):
        return None
    path = Path(report).parent / "samples" / sample
    if not path.is_file():
        return None
    if workdir is not None:
        try:
            return str(path.resolve().relative_to(Path(workdir).resolve()))
        except ValueError:
            pass                        # a look from another dump — absolute
    return str(path)


def worst_frames(registry, subject, wanted, workdir=None):
    """SNS-6 — the {wanted} sightings this subject matches its OWN memory
    LEAST well. -> (frames, unscored, reason codes).

    ⭐ **Worst, never best, and never "representative".** Fable 5's finding 3,
    and it is the whole reason a 1-frame glance can be a check at all: a
    subject shown by its best-matching frame looks correct every round even
    when it has absorbed a second animal, and the glance-yes then reinforces
    the error. Showing the photo the engine is least sure about is the only
    version of this check that can fail.

    The score is `confirmed_match()`'s shape — max cosine of the look's vector
    over the subject's exemplar ROWS, not a distance to an averaged one, so a
    subject holding kitten looks and adult looks is scored against both — and
    the MINIMUM over the candidates is what is shown. The vectors are
    re-loaded from each dump's own `embed/` index, the posture
    `attach_exemplars()` takes and for the same reason: a look whose artifacts
    have gone is unproved, not probably fine. One index per work dir, cached,
    because a mature subject's looks span dumps.

    ⚠️ **The pool is every look the record holds, and "recent" is bounded by
    what it retains** — no recency window is invented here, because that would
    be a parameter the SPEC does not name and an arbitrary one either way.

    ⚠️ **The score SATURATES at 1.000 immediately after a confirm**, and the
    number is on the page so nobody reads that as a passed check. Today's
    `cmd_confirm --go` enumerates every look the subject holds, so at t=0
    every candidate IS an exemplar and scores itself. The frames that can
    actually reveal absorption are the UNPROMOTED ones — the suppressed
    sightings `observe_draft_subject()` keeps appending on later dumps — so
    this check sharpens as the subject is seen again and is blind on the round
    that created it. Ties break on `vec_ref` so two renders pick one frame.

    ⛔ **Never a silent fallback to a frame that looks good.** Three failures
    are reachable — the look's work dir has been cleaned away, the index sha no
    longer matches the look's `vec_ref` (re-embedded), the subject holds no
    exemplar to score against — plus two more this loop meets: the thumbnail is
    gone, and `vectors_for()` refusing a record that disagrees with its `.npy`.
    In every one of them the frame is returned with `score: None` and the code
    that explains it, and the renderer says so. A fallback that quietly showed
    a nice frame would make SNS-6 decoration while every test stayed green.

    ⚠️ `vectors_for()` raising is CAUGHT here, and that is a deliberate
    divergence from `confirmed_match()`, which leaves it uncaught so a
    suppression can never fail silently. The two failures are not alike: a
    suppression that stops working must be loud, and a page that stops
    rendering tells the owner nothing at all. A table that says the score is
    unavailable beats no table."""
    looks, seen_refs = [], set(registry.not_this_refs(subject.subject_id))
    for entry in subject.record.get("evidence") or []:
        for look in entry.get("looks") or []:
            ref = look.get("vec_ref")
            if ref and ref not in seen_refs:
                seen_refs.add(ref)
                looks.append(look)
    if not looks:
        return [], 0, ["no_looks"]

    import numpy as np

    broken = False
    try:
        V = registry.vectors_for(subject.subject_id)
    except ValueError:
        V, broken = None, True

    indexes, scored, showable, reasons, unscored = {}, [], [], [], 0
    for look in looks:
        image = look_image(look, workdir)
        # ⚠️ `look_dir` is the dump this LOOK was observed in; `workdir` is the
        # one the table is being written into, and they are the same dir only
        # for the current dump's looks. Binding the look's own dir to the
        # parameter name — which is what this line did until the relative-link
        # test was written — silently re-pointed every frame after the first
        # at whichever dump it came from, so a cross-dump look rendered as a
        # bare relative path that resolves to nothing from where the table
        # sits. One name, two meanings, and the first look always looked fine.
        path, look_dir = look.get("path"), look.get("workdir")
        vector, reason = None, None
        if image is None:
            reason = "no_thumbnail"
        elif not (path and look_dir):
            reason = "no_looks"
        else:
            if look_dir not in indexes:
                indexes[look_dir] = load_embed_index(look_dir)
            row = indexes[look_dir][0].get(path)
            if row is None:
                reason = "no_index"
            elif row[0] != look["vec_ref"]:
                reason = "re_embedded"
            elif broken:
                reason = "vectors_broken"
            elif V is None or not len(V) or V.shape[1] != row[1].shape[0]:
                reason = "no_exemplar"
            else:
                vector = row[1]
        if reason is None:
            scored.append((float(np.max(V @ vector)), look["vec_ref"], image,
                           look))
            continue
        unscored += 1
        if reason not in reasons:
            reasons.append(reason)
        if image is not None:
            showable.append((look["vec_ref"], image, look))

    scored.sort(key=lambda t: (t[0], t[1]))
    # `path` / `workdir` ride along for F10, which reads the look's own scan.
    if scored:
        frames = [{"image": image, "score": score, "vec_ref": ref,
                   "path": look.get("path"), "workdir": look.get("workdir")}
                  for score, ref, image, look in scored[:wanted]]
    else:
        # Shown, and labelled as what they are: the record's own order. The
        # renderer prints no score beside them and says why there is none.
        frames = [{"image": image, "score": None, "vec_ref": ref,
                   "path": look.get("path"), "workdir": look.get("workdir")}
                  for ref, image, look in showable[:wanted]]
    return frames, unscored, reasons


def build_representations(registry, profile, rmsg, workdir=None, crops=None):
    """-> {"remembered": [...], "rejected": [...]}. SNS-5, and the ONE thing
    that makes Pattern 6 true: every permanent decision the pack holds comes
    back in front of the owner, every round, whether or not new evidence
    arrived.

    ⛔ A SEPARATE builder from `build_questions()`, reading `registry.subjects`
    by status. `is_draft` and `registry.drafts` are NOT widened and must not
    be: steps 2 and 3 both rest on that whitelist keeping `superseded`,
    `rejected` and `human-confirmed` out of the question loop — a superseded
    parent leaves it "for free", a rejection recognises nothing — and a
    re-presentation is not a question. It asks nothing and its default answer
    is silence.

    The set is `human-confirmed` ∪ `rejected`, and `superseded` is
    deliberately outside it: a split parent holds no name to check, its
    children are live and carry its looks, and `unconfirm()` already refuses
    it. There is nothing for the owner to do with one.

    Ordered by blast radius with a `subject_id` tiebreak, the same total order
    the question loop uses, because two `review` runs over one pack and one
    work dir must be byte-identical.

    `workdir` is the dir the table will be WRITTEN into, and it is here only
    so a frame under it renders as a relative link the way a draft tile's
    contact sheet does — see `look_image()`. Nothing is read from it.

    ⚠️ **Nothing is truncated.** Unconditional is the guarantee (SNS-5), and
    silent truncation would sacrifice exactly the undo path it exists to
    protect. If a profile ever grows past the ~50 soft warning far enough that
    this section stops being readable, the ONLY allowed answer is rotation
    with a stated ceiling — every remembered subject re-presented at least
    once per dump, said out loud on the page — and it is not built here
    because nothing yet needs it."""
    wanted = int(registry.defaults.get(
        "frames_per_reconfirmation",
        photo_subjects.DEFAULT_THRESHOLDS["frames_per_reconfirmation"]))
    remembered, rejected = [], []
    where = FrameWhere(profile, rmsg)
    # Q3 (Lead 20261001) — a look from an EARLIER dump is cropped from that
    # dump's own identity index while its work dir is on disk.
    others = {}

    def crops_for(frame):
        look_dir = frame.get("workdir")
        if not (look_dir and workdir and crops.workdir) or \
                Path(look_dir).resolve() == Path(workdir).resolve():
            return crops
        if look_dir not in others:
            others[look_dir] = FrameCrops(look_dir, crops.pack,
                                          crop_root=workdir)
        return others[look_dir]
    # ⭐ SNS-15's read-time sum, and the SORT reads it too — deliberately the
    # same number the line below prints. Ordering by the stored `files` while
    # showing the summed one would hand the owner a list whose order disagrees
    # with the magnitudes beside it, which is the kind of quiet wrongness that
    # never gets reported as a bug.
    #
    # ⚠️ This also reorders the `rejected` branch, harmlessly: only a
    # `human-confirmed` record can carry `absorbed_drafts` at all — the sweep's
    # winner loop refuses anything else, and `release_absorbed()` pops the list
    # before a withdrawal — so for every rejection `display_files()` returns
    # its stored `files` exactly.
    #
    # ⛔ The folded-in term is NOT bounded that way: `unconfirm()` on a fold's
    # winner leaves an `ai-drafted` record with tombstones still naming it, so
    # `display_files()` on a draft can legitimately return a sum. That is safe
    # only because no draft reader calls it — the question tiles, the drafts
    # block and the checkpoint threshold all read the stored `files` — and
    # anyone who gives one of them this number owes the ordering above a second
    # look.
    for subject in sorted(registry.subjects,
                          key=lambda s: (-registry.display_files(s),
                                         s.subject_id)):
        if subject.status == photo_subjects.STATUS_CONFIRMED:
            frames, unscored, reasons = worst_frames(registry, subject, wanted,
                                                     workdir)
            for frame in frames:
                frame["where"], frame["where_web"] = where.place(frame)
                # HIL-7 — the crop whose vector the memory holds, never the
                # whole photo: a wrong example looks right when the photo
                # holds both animals. `FrameCrops` keeps them apart from
                # "not indexed here" exactly as it does for a tile.
                told = crops_for(frame).describe(frame) if crops is not None else None
                frame["crops"] = told["crops"] if told else []
                frame["det_count"] = told["det_count"] if told else None
                # Q3 — whole only when no index covers the look, and said.
                frame["whole"] = told is None
            remembered.append({
                "subject_id": subject.subject_id,
                "display": subject_display(subject, profile, rmsg),
                # The number the owner reads, summed at DISPLAY time and never
                # stored (the owner's decision, 2026-08-19).
                # `review_remembered_line` takes
                # the same `{files}` argument it always did, so no vocabulary
                # key moves and no pack needs re-translating.
                "files": registry.display_files(subject),
                # A19, on the same display-time basis as `files` directly
                # above so the owner can subtract one from the other.
                "files_ungated": registry.display_files_ungated(subject),
                "batches": len(subject.observed_in),
                "frames": frames, "unscored": unscored, "reasons": reasons})
        elif subject.status == photo_subjects.STATUS_REJECTED:
            # ⛔ NO frames, and this is the decision rather than a saving. A
            # rejection is a question the owner CLOSED; putting its photos back
            # on the page is asking it again. One line of what it is and what
            # it costs, and the row that takes it back.
            rejected.append({
                "subject_id": subject.subject_id,
                "files": int(subject.record.get("files", 0)),
                "batches": len(subject.observed_in),
                "at": (subject.record.get("rejected") or {}).get("at") or "?",
                # U2-10. ⛔ `.get(...) or BASIS_NOT_MINE` and never a bare get:
                # a rejection written before this build states no basis, and
                # the weaker claim is the only honest reading of it.
                "basis": ((subject.record.get("rejected") or {}).get("basis")
                          or BASIS_NOT_MINE),
                # Step 3 speaks this warning at the moment the rejection is
                # taken. The round is where the owner can still see it.
                "centroid": registry.draft_centroid(subject.subject_id)
                is not None})
    return {"remembered": remembered, "rejected": rejected}


# ---------------------------------------------------------------- render ----

def frame_reasons(reasons, rmsg):
    """The owner-language sentence behind a frame that is missing or unscored.

    One function for both sections: the question's tiles lose frames for the
    same reasons the re-presentation's do — the thumbnail is gone, the record
    keeps no look behind it — and two copies of this join would drift into two
    vocabularies for one gap."""
    separator = rmsg.get("review_subject_separator", ", ")
    return separator.join(rmsg[f"review_frame_why_{code}"] for code in reasons)


def render_representations(represented, rmsg):
    """The two re-presentation sections, each with its own header.

    ⚠️ **Visually separate, and that is a safety property, not a layout
    one.** A name check is a glance; a revival is a decision. Rendering a
    rejection among the remembered subjects would put the one row that
    re-opens a closed question inside the block the owner is skimming."""
    separator = rmsg.get("review_subject_separator", ", ")

    def why(reasons):
        return frame_reasons(reasons, rmsg)

    out = []
    if represented["remembered"]:
        out += ["", rmsg["review_remembered_header"], "",
                f"> {rmsg['review_remembered_intro']}"]
        for record in represented["remembered"]:
            line = rmsg["review_remembered_line"].format(
                subject=record["display"], files=record["files"],
                batches=record["batches"])
            # A19 item 3. The header used to present a total that included
            # sightings no timeline gate ever approved, with nothing saying so
            # — the owner read it as the weight of evidence behind a name. The
            # total is unchanged and the ungated share is stated beside it.
            # ⛔ Appended, not substituted: a pack that has never taken an
            # ungated sighting renders exactly the line it rendered before.
            if record.get("files_ungated"):
                line += rmsg["review_remembered_ungated"].format(
                    files=record["files_ungated"])
            out.append("> " + line)
            for frame in record["frames"]:
                # SNS-8's fold, and the number is the whole of it: a
                # re-presented subject's frames are drawn from the same
                # sequence the questions above use, so the owner never sees two
                # frame 1s and never has to ask which numbering a number is in.
                # ⛔ There is no `frames:` line under here — see
                # `number_frames()`. The number identifies the photograph on
                # the page; it does not open a promotion path, because a
                # re-presentation promotes nothing.
                # HIL-7 — the crop(s), as a tile shows them; the whole photo
                # only when this dump's index says nothing about the look.
                shared = (frame.get("det_count") or 0) > 1
                # Lead ruling 20261001 (frame 13): a shared photo holds no
                # crop of the pet (D-24), so the WHOLE photo comes first and
                # the crops follow as what else is in it.
                images = frame.get("crops") or [frame["image"]]
                if shared:
                    out.append(f"> ![]({frame['image']}) "
                               + rmsg["review_frame_number"].format(n=frame["n"])
                               + where_suffix(frame))
                for image in images:
                    crop = CROP_FILE.search(str(image)) if shared else None
                    out.append(f"> ![]({image}) "
                               + rmsg["review_frame_number"].format(n=frame["n"])
                               + (f" (animal {frame['n']}."
                                  f"{int(crop.group(1)) + 1})" if crop else "")
                               + where_suffix(frame))
                if shared:
                    out.append("> " + rmsg["review_frame_shared_remembered"].format(
                        n=frame["n"], count=frame["det_count"],
                        subject=record["display"]) + f" {SHARED_MARK}")
                    out += not_mine_lines(frame, rmsg)
                if frame.get("whole"):
                    # Q3 — its own line, so the where-phrase stays the
                    # where-phrase; the ASCII mark is what the web page reads
                    # (an HTML comment, so `confirm` never sees it).
                    out.append("> " + rmsg["review_frame_whole_note"].format(
                        n=frame["n"]) + f" {WHOLE_MARK}")
            mapped = [f for f in record["frames"] if f.get("vec_ref")]
            if mapped:
                # Q8-b — what `not <n>` resolves through. Parsed, never
                # re-derived at confirm: the record has moved since render.
                out.append(f"> `{SHOWN_KEY}:` {record['subject_id']} " + ", ".join(
                    f"{f['n']}={short_ref(f['vec_ref'])}" for f in mapped))
            shown = [f for f in record["frames"] if f["score"] is not None]
            if shown:
                # Pinned to three decimals and formatted from a float(), never
                # from the numpy scalar `np.max` returns: a repr that carries
                # its dtype would make two renders of one pack differ.
                out.append("> " + rmsg["review_worst_frame_note"].format(
                    scores=separator.join(f"{f['score']:.3f}" for f in shown)))
            if not record["frames"]:
                out.append("> " + rmsg["review_no_frame"].format(
                    why=why(record["reasons"])))
            if record["unscored"]:
                out.append("> " + rmsg["review_frames_unscored"].format(
                    n=record["unscored"], why=why(record["reasons"])))
            # ⭐ The name half of the hint is on THIS section's rows only, and
            # the asymmetry is the point. SNS-14's rename is a verb for a
            # subject that holds a name; the rejected rows below hold none by
            # construction, and `rename()` refuses every one of them. Offering
            # the owner an action that is always refused, on the one section
            # where a stray word re-opens a closed question, would be worse
            # than not mentioning it — their door there is `revive`, and the
            # hint above already names it.
            #
            # ⛔ Inside the HTML comment like every other hint. This is the one
            # place a translated sentence shares a line with a parsed value,
            # and `parse_representations()` strips comments before it reads —
            # otherwise the words `same` and `distinct` in this very sentence
            # would arm every row the renderer wrote.
            if mapped:
                out.append("> " + rmsg["review_recheck_example"].format(
                    n=mapped[0]["n"], subject=record["display"],
                    sid=record["subject_id"]))
            out.append(f"> - `{RECHECK_KEY}:` {record['subject_id']} ______"
                       f" <!-- {rmsg['review_recheck_hint']} · "
                       f"{rmsg['review_recheck_name_hint']} · "
                       f"{rmsg['review_recheck_not_hint']} -->")
        out.append("")
    if represented["rejected"]:
        out += ["", rmsg["review_rejected_header"], "",
                f"> {rmsg['review_rejected_intro']}"]
        for record in represented["rejected"]:
            out.append("> " + rmsg["review_rejected_line"].format(
                subject=record["subject_id"], files=record["files"],
                batches=record["batches"], at=record["at"]))
            # ⛔ Both keys named as LITERALS. Building the key from the
            # basis string reads as tidier and makes them invisible to the
            # catalogue check that proves every shipped message is reachable —
            # a dead-key report is the only thing standing between a renamed
            # message and a KeyError in front of an owner.
            out.append("> " + (rmsg["review_rejected_basis_not_a_subject"]
                               if record["basis"] == BASIS_NOT_A_SUBJECT
                               else rmsg["review_rejected_basis_not_mine"]))
            if not record["centroid"]:
                out.append("> " + rmsg["review_rejected_no_centroid"])
            out.append(f"> - `{RECHECK_KEY}:` {record['subject_id']} ______"
                       f" <!-- {rmsg['review_recheck_hint']} -->")
        out.append("")
    return out


def short_ref(ref):
    """The frame's storage key, shortened for a line a human may have to scan.

    First 12 hex of the content sha (SNS-1b item 1). The `sha256:` prefix is
    dropped because every ref on the page carries it and it says nothing; what
    is kept is the part that distinguishes one photograph from another."""
    return str(ref).split(":")[-1][:12]


def number_frames(questions, represented):
    """SNS-1 and SNS-8 — ONE frame numbering for the whole page, and the short
    ref each number resolves through. -> the highest number used.

    ⭐ **One sequence, not one per section.** SNS-8 requires a re-presented
    subject to occupy numbers in the same space as a new one, because the
    owner has to be able to address the subject whose *name is the thing being
    corrected*. Step 4 shipped `recheck:` rows with no numbers at all and
    recorded this fold as its debt; this is where the debt is paid.

    ⚠️ The order is RENDER order — questions, then the remembered section —
    and not the SPEC mockup's, which shows the remembered subjects first. The
    mockup draws one question with both sections inside it; what actually
    ships puts the re-presentations after the closing fence, deliberately, so
    that `parse_review()` cannot mistake a `recheck:` row for part of a
    question. Numbering the page in an order the page is not written in would
    show the owner a table that starts at frame 3.

    ⛔ A remembered subject's frames get a NUMBER and no `frames:` entry, and
    that asymmetry is the safety property. A re-presentation promotes zero
    exemplars (SNS-5, SNS-6); giving its frames a mapping line would build the
    promotion path this build is required not to have, and a guard against
    using it would be one edit away from being deleted. With no map, `pick:`
    on such a number resolves to nothing and is refused — by construction,
    not by a check.

    The short ref is unique across the whole page or it is not short: two
    frames whose first 12 hex agree BOTH fall back to the full sha, because
    shortening one of them would leave a line where the same-looking key means
    two different photographs."""
    counter = 0
    for question in questions:
        for tile in question["tiles"]:
            for frame in tile["frames"]:
                counter += 1
                frame["n"] = counter
    for record in represented["remembered"]:
        for frame in record["frames"]:
            counter += 1
            frame["n"] = counter

    every = [frame for question in questions for tile in question["tiles"]
             for frame in tile["frames"]]
    seen = {}
    for frame in every:
        seen.setdefault(short_ref(frame["vec_ref"]), []).append(frame)
    for short, sharing in seen.items():
        for frame in sharing:
            frame["ref"] = short if len(sharing) == 1 else frame["vec_ref"]
    return counter


def absorbed_since(registry, checkpoint):
    """D-23's other half — what the LAST confirm's sweep closed without
    asking, so the next page can show it. -> (that checkpoint's number,
    [{subject_id, into, files, score}]) or (None, []).

    Each row also carries the SPACE the absorb was decided in (card (c) /
    LL-PHO-105): an accept the owner reads is never quoted without its space,
    and `None` means the row does not say — never a guess, and never a dash.

    ⭐ Why it has to exist. The sweep is right to reach a suppressed draft —
    at a tile ceiling those are the very drafts it was built to close — but a
    decision the owner cannot see is a decision they cannot undo, and
    `release_absorbed()` is only reachable by someone who knows there is
    something to release. One aggregate line in a confirm's console output is
    not that: it scrolls past, and the page is the artifact that keeps.

    ⛔ ONE checkpoint's worth, the highest below this one, never every absorb
    the pack holds. A list that accumulated would re-raise a decision the
    owner has already read and let go, and by the tenth checkpoint the page
    would open with nine rounds of settled bookkeeping.

    ⛔ An OWNER-ANSWERED absorb is excluded EXPLICITLY, on `answered`. It used
    to fall out by accident and the comment here said the wrong reason: SNS-16
    writes `src` as `"<page>.md Q<n>"`, which does carry the page, and it was
    only the `$` anchor on `CHECKPOINT_IN_NAME` that kept it out. Measured —
    `"memory-review_C1.md Q1"` matches nothing while `"memory-review_C1.md"`
    matches. Drop the anchor or change that format and every row the owner
    typed would appear under a heading that says nobody asked them."""
    rows = []
    for subject in registry.subjects:
        if subject.status != photo_subjects.STATUS_ABSORBED:
            continue
        record = subject.record
        absorbed = record.get("absorbed") or {}
        if absorbed.get("answered"):
            # The owner said this draft is that subject. They already know:
            # this section is about the decisions nobody typed.
            continue
        found = CHECKPOINT_IN_NAME.search(absorbed.get("src") or "")
        if not found:
            continue
        rows.append((int(found.group(1)), subject, record))
    earlier = [n for n, _s, _r in rows if n < checkpoint]
    if not earlier:
        return None, []
    last = max(earlier)
    return last, [{"subject_id": subject.subject_id,
                   "into": record.get("absorbed_by"),
                   "files": int(record.get("files", 0)),
                   "score": record.get("absorbed_at_score"),
                   # ⛔ READ, never derived. `absorbed_space()` returns what
                   # the row stored on the day; what the pack is configured
                   # for now is not what ran, and re-deriving it is
                   # LL-PHO-105 rebuilt somewhere new.
                   "space": photo_subjects.absorbed_space(record)}
                  for n, subject, record in sorted(rows, key=lambda t: t[1].subject_id)
                  if n == last]


SPACE_WORD_KEY = {
    photo_subjects.SPACE_IDENTITY: "review_absorbed_space_identity",
    photo_subjects.SPACE_CLIP: "review_absorbed_space_clip",
}


def space_word(space, rmsg):
    """The space an absorb was decided in, as the owner reads it.

    ⛔ An unrecorded space is a WORD, not a dash, and not an assumption. A
    dash reads as a field that failed to render; what is true is that the row
    does not say which space decided it, and a reader who cannot tell those
    apart is back at LL-PHO-105 — where every verdict was CLIP and was read as
    identity because nothing said otherwise. ⛔ `None` is never resolved to
    `clip` on the grounds that it probably was.

    ⚠️ The constants are photo_subjects', not retyped here: a third copy of
    the string `"identity"` is a third place the two could disagree, and the
    whole point of the field is that it says what actually ran."""
    key = SPACE_WORD_KEY.get(space)
    return rmsg[key] if key else rmsg["review_absorbed_space_unrecorded"]


def render_absorbed(registry, profile, rmsg, checkpoint):
    """The section itself. Deliberately NOT inside the questions fence: it is
    a report, and `parse_review()` reads nothing after that fence — an absorb
    must never be readable as a question the owner answered."""
    at, absorbed = absorbed_since(registry, checkpoint)
    if not absorbed:
        return []
    out = ["", rmsg["review_absorbed_header"].format(n=len(absorbed)),
           "", rmsg["review_absorbed_intro"].format(n=at), ""]
    for row in absorbed:
        winner = registry.get(row["into"]) if row["into"] else None
        space = space_word(row["space"], rmsg)
        into = (subject_display(winner, profile, rmsg) if winner
                else row["into"])
        subject = registry.get_literal(row["subject_id"])
        shown = (subject_display(subject, profile, rmsg) if subject
                 else row["subject_id"])
        out.append(rmsg["review_absorbed_row"].format(
            subject=f"{shown} ({row['subject_id']})", files=row["files"],
            into=f"{into} ({row['into']})",
            # An absorb with no score is SNS-16's owner-typed one, which this
            # section already skips; a missing one here would still be said
            # rather than rendered as a number nobody computed.
            score=("—" if row["score"] is None else f"{row['score']:.3f}"),
            space=space))
    out.append("")
    return out


def taken_names(registry):
    """-> the names the pack already holds, sorted, deduped.

    ⛔ CONFIRMED subjects only, and the whitelist is positive for the reason
    the header count is: `is_draft` covers two statuses out of five, so its
    negation counts `rejected`, `superseded` and `absorbed` records as names
    the owner chose. A rejected record holds no name at all, and warning about
    a name nobody can collide with is the noise this notice exists to avoid.
    """
    return sorted({s.name for s in registry.subjects
                   if s.name and s.status == photo_subjects.STATUS_CONFIRMED})


def render_name_taken(registry, profile, rmsg):
    """D-27 — the `same`/`distinct` qualifier, said before the owner types it.

    The rule is sound and is not being relaxed: a repeated name is genuinely
    ambiguous and only the owner can resolve it. What this removes is the
    discovery-by-failure — the page used to offer a blank `name:` row, say
    nothing, and refuse the answer afterwards.

    ⛔ Nothing renders when the pack holds no confirmed name: the rule cannot
    fire, so the sentence would be noise. That is also why the example is a
    REAL name from the pack rather than a placeholder — an owner who sees
    their own subject in the example can tell at a glance whether the name
    they are about to type is one of these."""
    names = taken_names(registry)
    if not names:
        return []
    return [rmsg["review_name_taken"].format(
        names=", ".join(f"**{n}**" for n in names),
        example=names[0], same=SAME_TOKEN, distinct=DISTINCT_TOKEN), ""]


def tag_not_mine(workdir, pack, questions, represented):
    """C10 — `frame["not_mine"]` = the animals (det_index) of a shared photo
    this dump's index records as not the owner's, so the page says so rather
    than asking again. Only this dump's marks: a frame from another dump is
    left as it was."""
    embed = Path(workdir) / "embed"
    marks = photo_identity.not_mine_marks(embed, pack)
    if not marks:
        return
    by_file, _space = photo_identity.load_detections(embed, pack)
    by_sha = {}
    for sha, det_index in photo_identity.not_mine_keys(by_file, marks):
        by_sha.setdefault(sha, []).append(det_index)
    frames = [f for q in questions for t in q.get("tiles") or []
              for f in t.get("frames") or []]
    frames += [f for r in represented.get("remembered") or []
               for f in r.get("frames") or []]
    for frame in frames:
        if frame.get("vec_ref") in by_sha:
            frame["not_mine"] = sorted(by_sha[frame["vec_ref"]])


def not_mine_lines(frame, rmsg):
    return ["> " + rmsg["review_frame_not_mine"].format(
        n=frame["n"], ref=f"{frame['n']}.{d + 1}")
        for d in frame.get("not_mine") or []]


def render_review(workdir, pack, registry, rows, questions, suppressed,
                  represented, checkpoint, threshold, depending, round_state,
                  round_deferred=0, page=None, places=()):
    profile = pack.profile
    rmsg = photo_profile.review_messages(profile)
    snapshot = pack.snapshot() or {"id": "(no pack files)", "files": 0}
    number_frames(questions, represented)
    tag_not_mine(workdir, pack, questions, represented)

    for q in questions:
        for row in rows:
            if row["batch"] in q["batches"]:
                row["ask"].append(q["id"])

    # ⛔ The POSITIVE whitelist, never `not is_draft`. `is_draft` covers two
    # statuses out of five, so its negation counts `rejected`, `superseded`
    # and `absorbed` records as things the owner confirmed — the header told
    # the owner their memory held N confirmed subjects while N included every
    # subject they had refused and every parent a split retired. Written as
    # the status test so each new status has to opt IN to being called
    # confirmed, which is the direction that stays correct as statuses are
    # added.
    confirmed = sum(1 for s in registry.subjects
                    if s.status == photo_subjects.STATUS_CONFIRMED)
    out = ["```",
           (rmsg["review_page_title"].format(page=page,
                                             batch=page_batch(f"{page}.md"))
            if page else rmsg["review_title"].format(n=checkpoint)),
           rmsg["review_owner_line"].format(
               owner=pack.owner or "(unbound)", unit=Path(workdir).name,
               batches=(f"B{rows[0]['batch']}–B{rows[-1]['batch']}" if rows
                        else "(none)"),
               files=sum(r["files"] for r in rows)),
           # G6-6 — the dump-wide threshold says nothing about one batch.
           *([] if page else
             [rmsg["review_fired_line"].format(n=depending, threshold=threshold)]),
           # SNS-4's obligation, and it is the half that makes the engine
           # deciding safe rather than merely convenient. A round that
           # interrupts without saying what it interrupted for is the
           # behaviour the decision exists to bound; a checkpoint that
           # withholds one without saying so is silent truncation. Both are
           # said, in one line, in the owner's own language — the sentence
           # comes from the pack like every other one on this page.
           rmsg[ROUND_REASON_KEY[(bool(round_state["fire"]),
                                  round_state["why"])]].format(**round_state),
           rmsg["review_age_line"].format(confirmed=confirmed,
                                          drafts=len(registry.drafts)),
           rmsg["review_snapshot_line"].format(snapshot=snapshot["id"],
                                               files=snapshot["files"]),
           "```", ""]
    if round_state["fire"] and round_state["why"] == "final":
        # The trace `final_round_asked()` reads back, so a re-run of
        # `finish --go` does not fire a second guaranteed round and spend the
        # dump's budget on a page nobody asked for. OUTSIDE the fence — inside
        # it a comment renders as literal text on the owner's page — and in
        # ASCII, because the sentence above it is in the owner's language.
        out.append(FINAL_MARKER)
    if page:
        # G6 — the name this page was written under, read back by `confirm`.
        out.append(PAGE_MARKER.format(page=page))
    out += [rmsg["review_table_header"],
            "|---|---|---|---|---|---|"]
    for row in rows:
        out.append(f"| B{row['batch']} | {row['from']}→{row['to']} | "
                   f"{row['files']} | {'<br>'.join(row['facts'])} | "
                   f"{row['scene']} | {' '.join(row['ask']) or '—'} |")

    out += ["", rmsg["review_questions_header"], ""]
    if page:
        # FIX6 (U6-14) — `photo_review_page.py apply` refuses a batch page's
        # answer without this line; say it where the owner reads the rows.
        out += [rmsg["review_page_answer_line"].format(page=page), ""]
    if not questions:
        # A batch page is not a checkpoint and has no threshold (G8).
        out += [rmsg["review_no_questions_page"] if page else rmsg["review_no_questions"], ""]
    # The hints sit in HTML comments: that is the one place a translated
    # sentence shares a line with a parsed value, and a comment is the only
    # delimiter that cannot be confused with an answer in any language.
    # `parse_review` strips comments before reading the line. The field keys
    # inside the comment are ASCII and untranslated like every other one.
    row_hint = (f"`pick:` {rmsg['review_hint_pick']}"
                f" · `who:` "
                f"{rmsg['review_hint_who_on_page'] if page else rmsg['review_hint_who']}"
                f" · `name:` {rmsg['review_hint_name']}")
    named = frames_named(workdir, registry, [f for q in questions
                                            for t in q["tiles"] for f in t["frames"]])
    for q in questions:
        out.append(rmsg["review_q_header"].format(
            n=q["id"][1:],
            type=rmsg["review_q_type_group_it"].format(kind=q["kind_word"]),
            files=q["files"], batches=len(q["batches"]), span=q["span"]))
        out.append(f"> {q['body']}")
        out.append(f"> {rmsg['review_q_count_why']}")
        # HIL-4 — named as literals so the dead-key check can see them.
        out.append(f"> {rmsg['review_howto_step1']} {HOWTO_MARK}")
        out.append(f"> {rmsg['review_howto_step2']} {HOWTO_MARK}")
        for tile in q["tiles"]:
            out.append("> " + rmsg["review_tile_line"].format(
                n=tile["tile"], subject=tile["display"], files=tile["files"],
                batches=len(tile["batches"])))
            for frame in tile["frames"]:
                # R3b — the CROP, when this work dir's index has one. What the
                # owner is being asked is *which animal is this*, and the room
                # around it is exactly the part that cannot answer that. The
                # whole frame is the fallback, never a second image beside the
                # crop: two pictures of one frame make the number ambiguous,
                # and the number is what `pick:` takes.
                images = frame.get("crops") or [frame["image"]]
                # The number goes BESIDE the photograph, because `pick:` takes
                # numbers and a number the owner has to count out is a number
                # they will miscount. On a shared frame every crop carries the
                # SAME number — they are one pickable unit, and giving them a
                # number each would offer a promotion path that does not exist.
                shared = (frame.get("det_count") or 0) > 1
                for image in images:
                    # Q8-c — on a shared frame each crop says WHICH animal it
                    # is, `<frame>.<animal>` (det_index + 1, stable across
                    # marks), which is what `skip: … not-a-subject` takes.
                    crop = CROP_FILE.search(str(image)) if shared else None
                    out.append(f"> ![]({image}) "
                               + rmsg["review_frame_number"].format(n=frame["n"])
                               + (f" (animal {frame['n']}."
                                  f"{int(crop.group(1)) + 1})" if crop else "")
                               + where_suffix(frame))
                if shared:
                    out.append(f"> {rmsg['review_frame_several']} {SEVERAL_MARK}")
                    out.append("> " + rmsg["review_frame_shared"].format(
                        n=frame["det_count"], frame=frame["n"]))
                    first = CROP_FILE.search(str(images[-1]))
                    out.append("> " + rmsg["review_frame_not_animal"].format(
                        ref=f"{frame['n']}."
                            f"{int(first.group(1)) + 1 if first else 2}"))
                    out += not_mine_lines(frame, rmsg)
                if named.get(frame["image"]):
                    out.append("> " + rmsg["review_frame_named"].format(
                        n=frame["n"], names=" + ".join(named[frame["image"]])))
            # U2-12 — after the frames, because it is a claim about the SET of
            # them and it names two of the numbers printed above.
            coherence = tile.get("coherence")
            if coherence is not None and not coherence["coherent"]:
                numbers = {f["vec_ref"]: f["n"] for f in tile["frames"]}
                a, b = coherence["worst"]
                if a in numbers and b in numbers:
                    out.append("> " + rmsg["review_group_incoherent"].format(
                        a=numbers[a], b=numbers[b]))
            out.append("> " + (rmsg["review_contact_note"].format(
                n=len(tile["frames"])) if tile["frames"]
                else rmsg["review_contact_missing"]))
            if tile["unresolved"]:
                # Said out loud: the sheet named more photographs than this
                # tile can offer, and a frame the owner cannot pick is worse
                # unmentioned than absent.
                out.append("> " + (rmsg["review_frames_unresolved_on_page"]
                                   if page else
                                   rmsg["review_frames_unresolved"]).format(
                    n=tile["unresolved"],
                    why=frame_reasons(tile["why_unresolved"], rmsg)))
            if tile["repeat"] and tile["repeat"].startswith("P-B"):
                out.append("> " + rmsg["review_asked_on_page"].format(
                    page=tile["repeat"]))
            elif tile["repeat"]:
                out.append("> " + rmsg["review_asked_before"].format(
                    n=tile["repeat"].lstrip("C")))
        if q["deferred"]:
            out.append("> " + (rmsg["review_more_deferred_on_page"] if page
                               else rmsg["review_more_deferred"]).format(
                n=q["deferred"]))
        out.append("> " + rmsg["review_effect_line"].format(effect=q["effect"]))
        # Trap 2's mapping. Tile number -> `subject_id`, written down and
        # PARSED back, never inferred from the order of a flat list: `confirm`
        # has to turn `group:` 1,3,7 into storage keys, and a mapping that
        # exists only as an incidental list order is a mapping that breaks the
        # first time anything sorts differently.
        out.append("> `subjects:` " + ", ".join(
            f"{t['tile']}={t['subject_id']}" for t in q["tiles"]))
        out.append("> `obs_count:` " + ", ".join(
            f"{t['tile']}={t['obs_count']}" for t in q["tiles"]))
        # SNS-1b item 1. The tile map above says which SUBJECT a tile is; this
        # says which PHOTOGRAPH a frame is, and `pick:` needs the second one.
        #
        # ⛔ PARSED, never inferred — not from the order of the images above,
        # not from `contact_sheet[:n]` re-read at confirm time. Both would be
        # maps that exist only as an incidental list order, and
        # `observe_draft_subject()` appends to `contact_sheet` between the
        # render and the confirm whenever a later batch is seen, so the second
        # one is a map that is WRONG rather than merely fragile.
        #
        # Machine plumbing the owner is not expected to read (SNS-8), which is
        # why the numbers on the photographs above are what the answer rows
        # ask for.
        out.append("> `frames:` " + ", ".join(
            f"{f['n']}={t['subject_id']} {f['ref']} {f['image']}"
            for t in q["tiles"] for f in t["frames"]))
        # G6-6d — which photos hold 2+ animals, for the web page to allow one
        # group per animal. DISPLAY: `confirm` re-reads the identity index.
        shared = [f"{f['n']}={f['det_count']}" for t in q["tiles"]
                  for f in t["frames"] if (f.get("det_count") or 0) > 1]
        if shared:
            out.append("> `animals:` " + ", ".join(shared))
        # B4 — display, like `animals:`: the name each frame's photo carries
        # now, for the web page to show beside the photo. `confirm` reads the
        # see labels again and never this line.
        held = [f"{f['n']}={' + '.join(named[f['image']])}" for t in q["tiles"]
                for f in t["frames"] if named.get(f["image"])]
        if held:
            out.append("> `named:` " + "; ".join(held))
        # ⛔ TWO blank rows even for a single tile, and that reversal is SNS-1
        # itself. The old shape gave one tile one row because "one subject
        # cannot be split" — the defect stated as a design rule, and the
        # comment OA-15 quotes. A tile is now a display grouping over frames
        # the owner may divide, so a page that offers one row for one tile
        # makes the split invisible to the person who would type it. An owner
        # who needs a third row copies one; a blank row is not an answer.
        for _ in range(2):
            out.append("> - `pick:` ______   `who:` ______   `name:` ______"
                       f" <!-- {row_hint} -->")
        out.append("> " + rmsg["review_more_rows"])
        out.append(f"> - `skip:` ______ <!-- {rmsg['review_hint_skip']} -->")
        out.append("")
    if questions and round_deferred:
        # ⚠️ ONCE, under all of the questions, and OUTSIDE every `>` block. The
        # per-question line above sits inside its question because it is about
        # that kind; this one is about the round, and putting it under one
        # question would read as that question's own overflow. Suppressed only
        # when no question rendered — a withheld round says so in its own line
        # at the top of the page, and "the round was full" beside "there was no
        # round" is two answers to one question.
        out += [(rmsg["review_more_deferred_round_on_page"] if page
                 else rmsg["review_more_deferred_round"]).format(
            n=round_deferred,
            cap=int(registry.defaults.get(
                "tiles_per_round",
                photo_subjects.DEFAULT_THRESHOLDS["tiles_per_round"]))), ""]
        # D-23 — its own line, immediately under the paragraph it qualifies.
        # ⛔ Not folded into that paragraph: a pack that translated the
        # paragraph would keep the old, false version of it and never see
        # this. Same rule the paragraph itself was given its own key for.
        out += [rmsg["review_deferred_sweep_note_on_page"] if page
                else rmsg["review_deferred_sweep_note"], ""]
    if questions and page:
        # G6 — the owner picks each animal's name FROM THEIR OWN LIST (the
        # names declared at onboarding and the ones confirmed since). The list
        # is the pack's; `same` is D-27's token, so a pick joins that record.
        names = taken_names(registry)
        if names:
            out += [rmsg["review_page_pets"].format(
                names=", ".join(f"**{n}**" for n in names), example=names[0],
                same=SAME_TOKEN), ""]
    elif questions:
        # D-27 — beside the answer rows it governs, and only when it can
        # apply. See `taken_names()`.
        out += render_name_taken(registry, profile, rmsg)
    out += ["```", rmsg["review_skip_note_on_page"] if page
            else rmsg["review_skip_note"], "```", ""]
    if page:
        out += render_places(workdir, page_batch(f"{page}.md"), places, rmsg)
    # ⚠️ AFTER the fence that closes the questions, and that placement is
    # parsed rather than cosmetic: `parse_review()` ends the open block on a
    # bare ``` and reads nothing after it, so a `recheck:` row can never be
    # mistaken for part of a question — and `asked_before()`, which globs every
    # review file this work dir holds, never books a re-presented subject into
    # layer 2. The rows are read by `parse_representations()`, alone.
    out += render_representations(represented, rmsg)
    # D-23 — after the re-presentations, which are the other section about
    # decisions already taken, and after the questions fence for the reason
    # `render_absorbed` states.
    out += render_absorbed(registry, profile, rmsg, checkpoint)
    if suppressed:
        out += ["<!-- questions suppressed, and why:"]
        out += [f"     {sid}: {why}" for sid, why in suppressed]
        out += ["-->", ""]
    return "\n".join(out)


# ----------------------------------------------------------------- parse ----

def scan_fields(body):
    """-> [(key, value)] for every ASCII field key on ONE line.

    A value runs to the next key on the line, or to the end of it. See
    FIELD_LINE above for why a line has to begin with a key before any of it
    is scanned."""
    if not FIELD_LINE.match(body):
        return []
    found = list(FIELD_SCAN.finditer(body))
    out = []
    for i, match in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(body)
        value = body[match.end():end].strip().strip("`").strip()
        out.append((match.group(1).lower(), value))
    return out


def tile_numbers(value):
    """-> the numbers on a `pick:`, `skip:` or legacy `group:` value, in order
    and without repeats. `[x]` and `[ ]` (the pre-F16 skip box) hold no digits
    and yield nothing, which is how one field serves both shapes.

    ⚠️ The name is historical and the numbers are no longer tiles on the rows
    that matter: SNS-1 made the FRAME the unit, so `pick:` and `skip:` are
    read against the `frames:` map and only a legacy `group:` row is read
    against the tile map. What this function does is unchanged — the numbers a
    human typed, in the order they typed them — and which map they are looked
    up in is the caller's question."""
    out = []
    for token in re.findall(r"\d+", value or ""):
        number = int(token)
        if number not in out:
            out.append(number)
    return out


def file_skips_by_frame(blocks, text):
    """K24 (U2-5/9) — frame numbers run through the whole page, so a `skip:`
    number typed under the wrong question is FILED under the question whose
    `frames:` map holds it, with the row's own words (`confirm`, the basis),
    and said out loud by `cmd_confirm`. Crop refs `N.M` move the same way.

    Not moved, and refused by `cmd_confirm` instead: a number two or more
    other questions hold, and one whose target question has its own `skip:`
    row saying something different. A number no question holds stays where it
    was typed and is refused there, as before."""
    shown = {int(n) for m in map(SHOWN_LINE.search, text.splitlines()) if m
             for n in re.findall(r"(\d+)\s*=", m.group(2))}
    for block in blocks:
        block["skip_filed"], block["skip_ambiguous"] = [], []
        block["skip_conflict"], block["page_shown"] = [], shown
        block.setdefault("skip_animals_armed_refs", [])
        block.setdefault("skip_animals_mine_refs", [])
    for block in blocks:
        def owners(n):
            return [b for b in blocks if b is not block and n in b["frames"]]

        for n in list(block["skip_numbers"]):
            if n in block["frames"] or not block["frames"] or not owners(n):
                continue
            block["skip_numbers"].remove(n)
            found = owners(n)
            if len(found) > 1:
                block["skip_ambiguous"].append((n, [b["n"] for b in found]))
                continue
            target = found[0]
            if target["skip_numbers"] and (
                    target["skip_armed"] != block["skip_armed"]
                    or target["skip_basis"] != block["skip_basis"]):
                block["skip_conflict"].append((n, target["n"]))
                continue
            if not target["skip_numbers"]:
                target["skip_armed"] = block["skip_armed"]
                target["skip_basis"] = block["skip_basis"]
            target["skip_numbers"].append(n)
            target["skip_filed"].append((str(n), block["n"]))
        for n, a in list(block["skip_animals"]):
            if n in block["frames"] or not block["frames"] or not owners(n):
                continue
            block["skip_animals"].remove((n, a))
            ref = f"{n}.{a}"
            found = owners(n)
            if len(found) > 1:
                block["skip_ambiguous"].append((ref, [b["n"] for b in found]))
                continue
            target = found[0]
            not_animal = (n, a) in block["skip_animals_armed_refs"]
            mine = (n, a) in block["skip_animals_mine_refs"]
            armed = not_animal or mine
            if target["skip_animals"] and target["skip_animals_armed"] != armed:
                block["skip_conflict"].append((ref, target["n"]))
                continue
            if not target["skip_animals"]:
                target["skip_animals_armed"] = armed
            target["skip_animals"].append((n, a))
            if not_animal:
                target["skip_animals_armed_refs"].append((n, a))
            if mine:
                target["skip_animals_mine_refs"].append((n, a))
            target["skip_filed"].append((ref, block["n"]))
        block["skip_animals_armed"] = (
            bool(block["skip_animals"]) and block["skip_animals_armed"])


def parse_review(text):
    """-> list of answered/unanswered question blocks.

    Parses on ASCII field keys only. The sentences beside them are the owner's
    language and may be anything.

    Reads BOTH shapes. A pre-F16 work dir holds `memory-review_C*.md` files
    with one question per subject, a flat `subjects:` list and a scalar
    `obs_count:`; `asked_before()` globs every one of them, so a parser that
    understood only the grouped shape would blind layer 2 in exactly the work
    dirs that already have history."""
    blocks, current = [], None
    for line in re.sub(r"<!--.*?-->", "", text, flags=re.S).splitlines():
        head = QUESTION_HEAD.match(line.strip())
        if head:
            if current:
                blocks.append(current)
            current = {"n": int(head.group(1)), "subject_ids": [], "tiles": {},
                       "who": None, "name": None, "answer": None, "skip": False,
                       "skip_numbers": [], "skip_armed": False,
                       # Q8-c — `<frame>.<animal>` crops the owner says are
                       # not a real animal. Never frame numbers.
                       "skip_animals": [],
                       # U2-10. Explicit in the shape, like every other key
                       # here: None means NO SKIP ROW WAS TYPED, which is a
                       # third state and not the same as a rejection whose
                       # basis went unstated (that one reads BASIS_NOT_MINE).
                       "skip_basis": None, "groups": [],
                       "obs_count": 0, "obs_by_tile": {}, "frames": {},
                       "picks": []}
            continue
        if current is None:
            continue
        body = line.lstrip("> ").rstrip()
        fields = scan_fields(body)
        if not fields:
            if line.strip().startswith("**Q") or line.strip() == "```":
                blocks.append(current)
                current = None
            continue
        keyed = {}
        for key, value in fields:
            keyed.setdefault(key, value)
        if "pick" in keyed or "group" in keyed:
            # One answer row, read as a UNIT — its numbers, its who and its
            # name belong together — because ONB-13's both-halves rule and the
            # {10} budget both apply per row, not per block.
            #
            # SNS-1: `pick:` takes FRAME numbers and does both jobs the old
            # verb could not. Frames from inside one tile are a split; frames
            # across tiles are a merge. `group:` took TILE numbers and could
            # express neither — it is superseded, and it is still parsed
            # because a work dir with history holds files that use it. What a
            # parsed `group:` row may DO is `cmd_confirm`'s answer, and it is
            # nothing.
            verb = "pick" if "pick" in keyed else "group"
            name = (keyed.get("name") or "").strip("_").strip() or None
            # SNS-7's token is stripped HERE, at the parser, so no write site
            # and no reader downstream ever sees it inside a name. A name that
            # reached the registry carrying `distinct` would be rendered onto
            # folders, printed in plan CSVs and compared against the next
            # round's typing — the collision answer becoming part of the
            # collision.
            #
            # SNS-14's `same` is stripped in the same loop and for the same
            # reason. Both are read as SUFFIXES and stripped repeatedly, so
            # `name: X same distinct` yields the name X with both flags set —
            # which `cmd_confirm` then refuses as the contradiction it is,
            # rather than silently honouring whichever token happened to be
            # written last.
            distinct = same = False
            same_as = None
            found = NAME_SAME_AS.search(name) if name else None
            if found:
                same, same_as = True, found.group(1).lower()
                name = name[:found.start()].strip() or None
            while name:
                if NAME_DISTINCT.search(name):
                    distinct = True
                    name = NAME_DISTINCT.sub("", name).strip() or None
                elif NAME_SAME.search(name):
                    same = True
                    name = NAME_SAME.sub("", name).strip() or None
                else:
                    break
            crop_refusal = (pick_crop_refusal(keyed[verb])
                            if verb == "pick" else None)
            unit = {"verb": verb,
                    "numbers": tile_numbers(CROP_REF.sub(" ", keyed[verb])
                                            if crop_refusal else keyed[verb]),
                    "crop_refusal": crop_refusal,
                    "who": (keyed.get("who") or "").strip("_").strip() or None,
                    "name": name, "distinct": distinct, "same": same,
                    "same_as": same_as}
            if (unit["numbers"] or unit["who"] or unit["name"]
                    or crop_refusal):
                (current["picks"] if verb == "pick"
                 else current["groups"]).append(unit)
            continue
        for key, value in keyed.items():
            if key in ("subject", "subjects"):
                current["subject_ids"] = re.findall(r"subj-\d{4,}", value)
                current["tiles"] = {int(n): sid
                                    for n, sid in TILE_TO_SUBJECT.findall(value)}
            elif key == "skip":
                current["skip"] = bool(re.search(r"\[\s*[xX]\s*\]", value))
                # Q8-c — taken out FIRST: `1.2` read as numbers is frames 1
                # AND 2, which would reject two subjects nobody skipped.
                current["skip_animals"] = [(int(n), int(a)) for n, a in
                                           CROP_REF.findall(value)]
                armed = [(int(n), int(a)) for m in CROP_ARMED.findall(value)
                         for n, a in CROP_REF.findall(m)]
                mine = [(int(n), int(a)) for m in CROP_CONFIRMED.findall(
                            CROP_ARMED.sub(" ", value))
                        for n, a in CROP_REF.findall(m)]
                current["skip_animals_armed"] = bool(current["skip_animals"]) \
                    and all(r in armed or r in mine
                            for r in current["skip_animals"])
                current["skip_animals_armed_refs"] = armed
                current["skip_animals_mine_refs"] = mine
                # What is left is the whole-photo half, read on its own — the
                # crops' word must not become the frames' basis (U2-10).
                value = CROP_REF.sub(" ", CROP_ARMED.sub(" ", value))
                current["skip_numbers"] = tile_numbers(value)
                # The one row that has to be typed on purpose. `rejected` is
                # the only outcome no later checkpoint can reach, so the
                # numbers alone are not enough — an ASCII token beside them is
                # what separates a decision from a slip of the keyboard. The
                # token is untranslated for the same reason the field keys are.
                current["skip_armed"] = bool(
                    re.search(r"\bconfirm\b", value, re.I))
                # U2-10. Read off the same row rather than a row of its own:
                # it qualifies a rejection and cannot occur without one, and a
                # second row could be typed alone, which would be a basis for
                # nothing. ⛔ Absent means `not-mine` — never "unknown".
                current["skip_basis"] = (
                    BASIS_NOT_A_SUBJECT if SKIP_NOT_A_SUBJECT.search(value)
                    else BASIS_NOT_MINE)
            elif key == "frames":
                # ⚠️ An EXPLICIT branch, like every other structured key here.
                # The `else` at the bottom of this loop writes the raw string
                # onto `current[key]`, so a new key that falls through it
                # silently replaces the dict the rest of the file reads —
                # answered with no error, and every pick row afterwards
                # refusing for a reason nobody could act on.
                for n, subject_id, ref, path in FRAME_ENTRY.findall(value):
                    current["frames"][int(n)] = {
                        "subject_id": subject_id, "ref": ref,
                        "path": path.strip()}
            elif key == "obs_count":
                pairs = TILE_TO_COUNT.findall(value)
                if pairs:
                    current["obs_by_tile"] = {int(t): int(n) for t, n in pairs}
                else:
                    current["obs_count"] = int(re.sub(r"\D", "", value) or 0)
            else:
                current[key] = value.strip("_").strip() or None
    if current:
        blocks.append(current)
    file_skips_by_frame(blocks, text)
    for block in blocks:
        tiles, frames = block["tiles"], block["frames"]
        block["obs_by_id"] = {tiles[t]: n for t, n in block["obs_by_tile"].items()
                              if t in tiles}
        # Which subject each frame number belongs to, and the frames each
        # subject put on the page. The second one is what makes "a strict
        # subset of this subject's frames" a question the parser can answer —
        # without it a `skip:` row cannot tell "all of it" from "part of it",
        # and those two mean opposite things (SNS-1b item 5).
        owner_of = {n: entry["subject_id"] for n, entry in frames.items()}
        block["frames_by_subject"] = {}
        for n in sorted(frames):
            block["frames_by_subject"].setdefault(owner_of[n], []).append(n)

        for unit in block["groups"]:
            # ⚠️ A legacy row's numbers are TILE numbers and are resolved
            # against the tile map, never the frame map. Reading them as
            # frames would silently turn "tile 3" into "the third photograph
            # on the page", which on a page with five frames per tile names a
            # different subject entirely.
            unit["subject_ids"] = [tiles[t] for t in unit["numbers"]
                                   if t in tiles]
            unit["unknown"] = [t for t in unit["numbers"] if t not in tiles]
            unit["refs"] = {}
        for unit in block["picks"]:
            unit["unknown"] = [n for n in unit["numbers"] if n not in frames]
            refs = {}
            for n in unit["numbers"]:
                entry = frames.get(n)
                if entry:
                    refs.setdefault(entry["subject_id"], []).append(entry["ref"])
            # Grouped BY SUBJECT, because that is the unit storage promotes in
            # and the unit a partition is decided on: one row naming frames of
            # two drafts is a merge of two records, and one draft named by two
            # rows is a split of one.
            unit["refs"] = refs
            unit["subject_ids"] = list(refs)

        # `skip:` reads the same numbering `pick:` does (SNS-1, SNS-8) — one
        # page, one meaning for the number 3. A page with no frame map at all
        # is a pre-step-5 file, and its numbers are tiles; `cmd_confirm`
        # refuses those rather than acting on them, but they still have to
        # RESOLVE or the refusal cannot name what it is refusing.
        source = frames or tiles
        block["skip_ids"], block["skip_unknown"] = [], []
        for n in block["skip_numbers"]:
            entry = source.get(n)
            subject_id = entry["subject_id"] if isinstance(entry, dict) else entry
            if subject_id is None:
                block["skip_unknown"].append(n)
            elif subject_id not in block["skip_ids"]:
                block["skip_ids"].append(subject_id)
        # A block whose only content is answer rows IS answered — and a block
        # with SOME rows filled is answered for those rows only. What a blank
        # row must never become is a rejection: silence is not an answer, so
        # nothing below reads an empty row at all.
        block["answered"] = bool(block["who"] or block["name"]
                                 or block["answer"] or block["skip"]
                                 or block["groups"] or block["picks"]
                                 or block["skip_numbers"]
                                 or block["skip_animals"])
    return blocks


def pinned_snapshot(text):
    """-> the pack snapshot id this review was rendered against, or None.

    SNS-1b item 1's other half: *"`confirm` refuses a review whose pinned pack
    snapshot no longer matches"*. `review` has always printed the id into its
    header (the determinism rule in the module docstring is why it is there at
    all); until now nothing read it back, so the header said which pack the
    page describes and `confirm` believed whatever page it was handed.

    ⚠️ Read from the HEADER FENCE ONLY, and that is not tidiness. A `frames:`
    line carries a `vec_ref` per frame and a `vec_ref` is a content sha with
    the same spelling — scanning the whole file would match the first
    photograph on the page and compare the pack against a photograph. The
    header is everything between the first pair of ``` fences, which is where
    `render_review()` puts it and the one block no answer row can reach.

    A file with no id at all -> None, and that is NOT a refusal here: a
    hand-written table and a pre-F16 file both look like this, and there is
    nothing to compare. What such a file cannot do is promote — see the
    `frames:` gate in `cmd_confirm`, which is where a page with no provable
    frame map is refused for the reason it deserves."""
    parts = text.split("```")
    if len(parts) < 2:
        return None
    found = SNAPSHOT_ID.search(parts[1])
    return found.group(0) if found else None


def parse_representations(text):
    """-> [{"subject_ids", "gestures", "name", "same", "distinct", "raw"}] for
    every `recheck:` row that carries something. SNS-5's half of the parse, and
    SNS-14's only door.

    ⭐ **A typed NAME is the other thing this row may carry.** SNS-14 is one
    sentence — *"renaming A to B's name raises the collision question, and
    `same` performs the fold at the next confirm"* — and until this parsed a
    name there was nowhere to type the rename. `build_questions()` tiles drafts
    only, so a confirmed subject never reaches a `pick:` row; `number_frames()`
    deliberately gives a re-presented frame a number and no `frames:` entry.
    This row is where a remembered subject's name is written, so it is where a
    remembered subject's name is corrected.

    ⚠️ The name is what is LEFT after the ids, the rendered blank and the
    gesture words are taken out — never a positional read. The row is rendered
    with its id already on it and the owner types around it, so which side of
    the id the name lands on is theirs to decide, not the parser's.

    ⛔ A row carrying a name AND a gesture keeps BOTH, so `cmd_confirm` can
    refuse it whole. A name that happens to contain `withdraw`, `revive` or
    `reject` therefore bounces rather than being silently read as one or the
    other — visible is the right failure here, and the refusal says so.

    ⚠️ **Comments are stripped FIRST, and that is not hygiene.** The hint
    beside every row has to name the gestures — `withdraw`, `revive` — or
    nobody knows they exist, so a scan of the raw line finds a gesture on every
    row the renderer wrote and a file nobody touched would withdraw the whole
    profile. `parse_review()` strips for the same reason; an HTML comment is
    the one delimiter that cannot be confused with an answer in any language.

    A blank row yields nothing at all, which is what "silence is never
    rejection" means here: the DEFAULT answer to "is this still right?" is
    yes, and yes writes nothing.

    Separate from `parse_review()` on purpose. That one builds `Q<n>` blocks
    and `asked_before()` reads every one of them out of the work dir; a
    re-presentation booked into layer 2 would suppress the draft question it
    is not."""
    out = []
    for line in re.sub(r"<!--.*?-->", "", text, flags=re.S).splitlines():
        body = line.lstrip("> ").rstrip()
        found = RECHECK_LINE.match(body)
        if not found:
            continue
        value = found.group(1)
        # W2-4 — a row typed inside one pair of backticks keeps the closing
        # one on its value; left there it would end a new name (A20).
        if (value.endswith("`") and "`" not in value[:-1]
                and re.match(rf"[-*\s]*`{RECHECK_KEY}\s*:\s*[^`\s]", body)):
            value = value[:-1].rstrip()
        # Q8-b — taken out FIRST, so neither the numbers nor the word can be
        # read as part of a name.
        not_frames = [int(n) for m in NOT_FRAMES.findall(value)
                      for n in re.findall(r"\d+", m)]
        value_rest = NOT_FRAMES.sub(" ", value)
        not_bare = bool(NOT_BARE.search(value_rest))
        value_rest = NOT_BARE.sub(" ", value_rest)
        gestures = []
        for token in GESTURE_SCAN.findall(value):
            if token.lower() not in gestures:
                gestures.append(token.lower())
        # What is left once everything the row was RENDERED with is taken out:
        # the subject id (machine plumbing, SNS-8), the blank the owner types
        # into, and the gesture words — which are removed here so that a row
        # carrying only `withdraw` is a gesture and not a subject named
        # "withdraw". A name written beside one still survives the removal, so
        # the two arrive together and `cmd_confirm` refuses the pair.
        #
        # ⚠️ The blank is matched as a RUN of underscores rather than stripped
        # off the ends: an owner who types after it leaves it in the middle,
        # and a name read as `______ Bo` is a name nothing in the pack can ever
        # match.
        name = GESTURE_SCAN.sub(" ", SUBJECT_IN_TEXT.sub(" ", value_rest))
        name = " ".join(BLANK_RUN.sub(" ", name).split()) or None
        # Stripped with the SAME two expressions `parse_review()` uses, and
        # repeatedly, so `X same distinct` yields the name X with both flags
        # set — a contradiction `cmd_confirm` refuses out loud rather than
        # resolving in favour of whichever token was written last.
        #
        # ⚠️ Matched against a LEADING SPACE, and that is the one place this
        # row reads differently from a `name:` row. Both expressions want
        # whitespace before the token, so a value that is NOTHING but the token
        # would survive them and parse as a subject called "same". On a `name:`
        # row that is right — the owner typed it into a name field. Here the
        # value is the whole answer, so a bare token is an armed word with no
        # name in front of it, and `cmd_confirm` says so rather than quietly
        # renaming somebody's cat to "same".
        distinct = same = False
        name = f" {name}" if name else None
        while name:
            if NAME_DISTINCT.search(name):
                distinct = True
                name = NAME_DISTINCT.sub("", name) or None
            elif NAME_SAME.search(name):
                same = True
                name = NAME_SAME.sub("", name) or None
            else:
                break
        name = name.strip() or None if name else None
        bare = BARE_NUMBER.findall(name) if name else []
        if not gestures and not name and not (same or distinct) \
                and not not_frames and not not_bare:
            # The row as it was rendered: an id and a blank. Not returned at
            # all, so no caller can reach a code path for it and no code path
            # can be written that treats it as an answer.
            continue
        out.append({"subject_ids": SUBJECT_IN_TEXT.findall(value),
                    "gestures": gestures, "name": name, "same": same,
                    "distinct": distinct, "raw": value.strip(),
                    "not_frames": not_frames, "not_bare": not_bare,
                    "bare_numbers": bare})
    return out


def take_out_row(registry, row, shown_on_page, gestured, refusals, changes,
                 by, page, go):
    """Q8-b — one `recheck: <id> not <n>[,<n>…]` row. -> True when applied or
    predicted. The whole row is refused, and nothing written, on any doubt;
    the dry run writes nothing and audits nothing."""
    raw = row["raw"]
    if row["gestures"] or row["name"] or row["same"] or row["distinct"]:
        refusals.append(
            f"`{RECHECK_KEY}:` {raw!r} — `{NOT_TOKEN}` takes photos out of one "
            "subject's memory and is the whole answer on its row; this row also "
            "carries " + ", ".join(
                [f"the name {row['name']!r}"] * bool(row["name"])
                + row["gestures"] + [SAME_TOKEN] * row["same"]
                + [DISTINCT_TOKEN] * row["distinct"])
            + ". Nothing was applied.")
        return False
    if not row["not_frames"]:
        refusals.append(
            f"`{RECHECK_KEY}:` {raw!r} — `{NOT_TOKEN}` needs the frame number(s) "
            f"printed under this subject, e.g. `{NOT_TOKEN} 3`. Nothing was "
            "applied.")
        return False
    if len(row["subject_ids"]) != 1:
        refusals.append(f"`{RECHECK_KEY}:` {raw!r} names "
                        f"{len(row['subject_ids'])} subject(s) — one row is one "
                        "record. Nothing was applied.")
        return False
    subject_id = row["subject_ids"][0]
    subject = registry.get_literal(subject_id)
    if subject is None or subject.status != photo_subjects.STATUS_CONFIRMED:
        refusals.append(f"`{RECHECK_KEY}:` {subject_id} is not a named subject, "
                        f"so `{NOT_TOKEN}` has no memory to take a photo out "
                        "of. Nothing was applied.")
        return False
    if subject_id in gestured:
        refusals.append(f"`{RECHECK_KEY}:` {subject_id} is on more than one row. "
                        "A record takes one answer per round — the second row "
                        "was not applied, and the first stands.")
        return False
    gestured.add(subject_id)
    mine = shown_on_page.get(subject_id) or {}
    foreign = [n for n in row["not_frames"] if n not in mine]
    if foreign:
        refusals.append(
            f"`{RECHECK_KEY}:` {subject_id} `{NOT_TOKEN} "
            f"{', '.join(map(str, foreign))}` — "
            + ("that is not" if len(foreign) == 1 else "those are not")
            + f" among this subject's photos on this page (its frames: "
            f"{', '.join(map(str, sorted(mine))) or 'none'}). Nothing was "
            "applied.")
        return False
    held = {look["vec_ref"] for entry in subject.record.get("evidence") or []
            for look in entry.get("looks") or [] if look.get("vec_ref")}
    held |= {e["vec_ref"] for e in subject.exemplars if e.get("vec_ref")}
    refs, lost = [], []
    for n in row["not_frames"]:
        found = [r for r in held if short_ref(r) == mine[n]]
        (refs.append(found[0]) if len(found) == 1 else lost.append(n))
    if lost:
        refusals.append(
            f"`{RECHECK_KEY}:` {subject_id} `{NOT_TOKEN} "
            f"{', '.join(map(str, lost))}` — the photo is no longer in this "
            "subject's memory as the page showed it. Nothing was applied.")
        return False
    refs = list(dict.fromkeys(refs))
    name = subject.name or subject_id
    if go:
        done = registry.take_out_photos(subject_id, refs, by=by,
                                        reason=f"`{RECHECK_KEY}: {NOT_TOKEN}` on {page}")
        changes.append(
            f"{subject_id} -> {len(refs)} photo(s) taken out of {name!r}'s "
            f"memory ({len(done['exemplars'])} were examples of what it looks "
            "like); the name stays, and no folder name or label changes. It is "
            "not filed back unless you pick it for this subject again")
    else:
        changes.append(
            f"{subject_id} -> would take {len(refs)} photo(s) out of {name!r}'s "
            "memory; the name stays, and no folder name or label changes")
    return True


def mark_not_animals(workdir, profile, blocks, refusals, changes, by, page, go):
    """Q8-c — `skip: <frame>.<animal> not-a-subject`: that crop is not a real
    animal (a picture in a frame, a reflection). -> the marks written or
    predicted. Written into the dump INDEX before any row is judged, so the
    frame's animal count — and with it `exemplar_quality()` and the shared-
    frame rule — reads the frame without it. No detector filter, and nothing
    is rejected: the frame itself stays askable and pickable.

    C10 — `skip: <frame>.<animal> confirm`: that ONE animal of a shared photo
    is not the owner's. Kept in the index's own `not_mine` list, keyed like a
    not-a-subject mark (sha256, det_index, box). ⛔ It changes no count: the
    stranger is still an animal in the frame, so D-24 still holds the photo
    out of the exemplars, and the owner's pick on the same photo keeps its
    name. A photo with ONE animal is refused here — that is `skip: N confirm`."""
    import photo_index
    wanted = []
    for block in blocks:
        if not block.get("skip_animals"):
            continue
        refs = ", ".join(f"{n}.{a}" for n, a in block["skip_animals"])
        if not block.get("skip_animals_armed"):
            refusals.append(
                f"Q{block['n']}: `skip:` {refs} names one animal in a photo — "
                f"say which: `confirm` if it is not your animal (e.g. "
                f"`skip: {refs} confirm`), or `{BASIS_NOT_A_SUBJECT}` if it is "
                f"not a real animal (e.g. `skip: {refs} {BASIS_NOT_A_SUBJECT}`)."
                " Nothing was marked. " + photo_profile.STRANGER_ANIMAL)
            continue
        mine_refs = block.get("skip_animals_mine_refs") or []
        armed_refs = block.get("skip_animals_armed_refs") or []
        for n, a in block["skip_animals"]:
            if (n, a) in mine_refs and (n, a) in armed_refs:
                refusals.append(f"Q{block['n']}: `skip:` {n}.{a} carries both "
                                f"`confirm` and `{BASIS_NOT_A_SUBJECT}` — keep "
                                "the one you mean. Nothing was marked.")
                continue
            frame = block["frames"].get(n)
            if not frame:
                refusals.append(f"Q{block['n']}: `skip:` {n}.{a} — there is no "
                                f"frame {n} on any question of this page. "
                                "Nothing was marked.")
                continue
            basis = BASIS_NOT_MINE if (n, a) in mine_refs else BASIS_NOT_A_SUBJECT
            wanted.append((block["n"], n, a, frame.get("ref"), basis))
    if not wanted:
        return []
    by_file, _space = photo_identity.load_detections(Path(workdir) / "embed",
                                                      profile)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    marks = []
    for q, n, a, ref, basis in wanted:
        hits = [(source, row) for source, entries in by_file.items()
                for row, _v in entries
                if short_ref(row.get("sha256") or "") == ref
                and int(row.get("det_index") or 0) == a - 1
                and row.get("status") == photo_identity.STATUS_OK]
        if len(hits) != 1:
            refusals.append(f"Q{q}: `skip:` {n}.{a} — frame {n} holds no animal "
                            f"{a} that is still counted. Nothing was marked.")
            continue
        source, row = hits[0]
        if basis == BASIS_NOT_MINE and int(row.get("det_count") or 0) < 2:
            refusals.append(f"Q{q}: `skip:` {n}.{a} — photo {n} holds one "
                            "animal, so the whole photo is the answer: "
                            f"`skip: {n} confirm`. Nothing was marked.")
            continue
        marks.append({"sha256": row["sha256"], "det_index": a - 1,
                      "box": row.get("box"), "file": Path(source).name,
                      "by": by, "source": f"{page} Q{q} {n}.{a}", "at": now,
                      "basis": basis})
    if not marks:
        return []
    lists = {BASIS_NOT_A_SUBJECT: "not_animals", BASIS_NOT_MINE: "not_mine"}
    said = {BASIS_NOT_A_SUBJECT: ("would stop counting as an animal; this dry "
                                  "run still counts it, so a pick on that "
                                  "photo is judged with --go",
                                  "no longer counted as an animal (the "
                                  "photo's other animals are unchanged)"),
            BASIS_NOT_MINE: ("would be recorded as not your animal (the "
                             "photo's other animals are unchanged)",
                             "recorded as not your animal (the photo's other "
                             "animals are unchanged)")}

    def shown(basis):
        return ", ".join(m["source"].split()[-1] for m in marks
                         if m["basis"] == basis)
    if not go:
        for basis in lists:
            if shown(basis):
                changes.append(f"{shown(basis)} -> {said[basis][0]}")
        return marks
    try:
        loaded = photo_index.load(Path(workdir), profile)
        if loaded is None:
            raise photo_index.Refused("this dump has no owner pack")
        ipack, target, index = loaded
        photo_index.open_for_change(Path(workdir), ipack, index,
                                    "photo_memory confirm")
    except photo_index.Refused as exc:
        everything = ", ".join(m["source"].split()[-1] for m in marks)
        refusals.append(f"`skip:` {everything} — a crop mark is kept in the "
                        f"dump's index, and it cannot be written: {exc}")
        return []
    wrote = False
    for basis, key in lists.items():
        mine = [{k: v for k, v in m.items() if k != "basis"}
                for m in marks if m["basis"] == basis]
        if not mine:
            continue
        have = {(m.get("sha256"), int(m.get("det_index") or 0))
                for m in index.get(key) or []}
        new = [m for m in mine if (m["sha256"], m["det_index"]) not in have]
        if new:
            index.setdefault(key, []).extend(new)
            what = ("marked not a real animal" if basis == BASIS_NOT_A_SUBJECT
                    else "recorded as not the owner's animal")
            photo_index.log_entry(
                index, "photo_memory confirm",
                f"{len(new)} crop(s) {what}: "
                + ", ".join(f"{m['file']} animal {m['det_index'] + 1}"
                            for m in new),
                (f"Q8-c: `skip: … {BASIS_NOT_A_SUBJECT}` on {page}"
                 if basis == BASIS_NOT_A_SUBJECT
                 else f"C10: `skip: N.M confirm` on {page}"), by=by or "owner")
            wrote = True
        changes.append(f"{shown(basis)} -> {said[basis][1]}")
    if wrote:
        photo_index.save(target, ipack, index)
    return marks


def parse_shown(text):
    """Q8-b — {subject_id: {frame number: short ref}} off the `shown:` lines
    the page was rendered with."""
    out = {}
    for line in re.sub(r"<!--.*?-->", "", text, flags=re.S).splitlines():
        found = SHOWN_LINE.search(line)
        if found:
            out[found.group(1)] = {int(n): ref for n, ref in
                                   re.findall(r"(\d+)\s*=\s*([^,\s]+)",
                                              found.group(2))}
    return out


# --------------------------------------------------------------- entities ---

def entities_path(pack):
    return Path(pack.dir) / ENTITIES_NAME


def sync_entity(entities, subject, confirmed_by):
    """Write the subject's facts into `photo-entities.json` under the SAME
    `subject_id` the registry keys its vectors on. This is the pairing that
    makes the two files one subject model — without it the claim is a
    sentence in a design doc and nothing in the pack holds it up.

    `who == 'pet'` routes to `pets`, everything else to `people`. The schema
    has those two lists and no third; a named object (ONB-13's `kind`
    extension) therefore lands in `people` with its `kind` intact, which is
    wrong-ish and visible, rather than silently dropped."""
    bucket = "pets" if (subject.who or "").lower() == "pet" else "people"
    records = entities.setdefault(bucket, [])
    record = next((r for r in records
                   if r.get("subject_id") == subject.subject_id), None)
    if record is None:
        record = {"subject_id": subject.subject_id}
        records.append(record)
    record.update({"name": subject.name, "who": subject.who,
                   "active": subject.record.get("active") or [None, None]})
    if subject.kind:
        record["kind"] = subject.kind
    if subject.previous_names:
        record["previous_names"] = subject.previous_names
    record["confirmed_by"] = confirmed_by
    records.sort(key=lambda r: r.get("subject_id") or "")
    return bucket, record


# --------------------------------------------------- F14: the exemplars ----

def load_embed_index(workdir):
    """-> ({SourceFile: (sha256, vector)}, identity) for one dump's embed
    index, or `({}, None)` when it is not on disk.

    NOT `photo_see.load_index()`, which `sys.exit()`s on a missing index. Here
    a missing index must refuse ONE promotion, not kill a confirm that is also
    writing the owner's answer into the pack. numpy is imported inside, and
    photo_see is not imported at all, so `confirm` still runs in a process
    that has neither."""
    import numpy as np
    from photo_recurrence import META_IDENTITY

    embed_dir = Path(workdir) / "embed"
    rows_path, vec_path, meta_path = (embed_dir / n for n in (
        "embeddings.csv", "embeddings.npy", "embeddings-meta.json"))
    if not all(p.is_file() for p in (rows_path, vec_path, meta_path)):
        return {}, None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    with open(rows_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    arr = np.load(vec_path)
    index = {}
    for row, vec in zip(rows, arr):
        if row.get("status") != "embedded":
            continue
        norm = float(np.linalg.norm(vec))
        if norm < 0.5:                  # a failed row, `zero_vector_means_failed`
            continue
        index[row["SourceFile"]] = (row["sha256"], vec / norm)
    import photo_embed
    return index, photo_embed.space_view(meta, META_IDENTITY)


def resolve_refs(subject, refs):
    """-> (the full `vec_ref`s these picks name, [problems]).

    SNS-1b item 1's last clause: the short ref on a `frames:` line *"resolves
    against that subject's own evidence looks, and an ambiguous or absent ref
    is a per-row refusal"*.

    ⚠️ **Against THIS subject's looks, never the pack's.** A short ref is 12
    hex and the map already says which subject the frame belongs to, so
    resolving globally would let a collision in another record decide what
    this row picked. Scoped here, a collision can only happen between two
    photographs of one subject — where it is still refused, never guessed.

    A full ref matches itself, which is what the render falls back to when two
    frames on a page share their first 12 hex."""
    looks = subject_looks(subject)
    out, problems = [], []
    for ref in refs:
        found = [look["vec_ref"] for look in looks
                 if look["vec_ref"] == ref or short_ref(look["vec_ref"]) == ref]
        found = list(dict.fromkeys(found))
        if not found:
            problems.append(
                f"the frame keyed {ref} names no photograph "
                f"{subject.subject_id} was seen in — the page and the pack "
                "disagree about what that number is")
        elif len(found) > 1:
            problems.append(
                f"the frame keyed {ref} matches {len(found)} of "
                f"{subject.subject_id}'s photographs, so which one was picked "
                "cannot be told")
        else:
            out.append(found[0])
    return out, problems


def attach_exemplars(registry, subject, only_refs):
    """F14 — the one point where geometry becomes recognition evidence.

    -> (exemplars gained, [notes]). Called with THE SUBJECT THAT WAS JUST
    CONFIRMED, because that is the moment the human yes exists: before it, the
    looks below are files a clustering attributed to an unnamed draft; after
    it, they are photographs of somebody the owner has identified. Nothing is
    promoted anywhere else, and a draft that is never confirmed never gains
    one.

    ## SNS-1b — `only_refs` is REQUIRED, and `None` is not "everything"

    Which of the subject's looks may be promoted, by `vec_ref`. Before this
    the answer was "all of them", and that is OA-15's mechanism: an owner
    looking at five frames of one tile, two of which are a second animal,
    promoted all five — plus every look behind them nobody rendered. Making
    the frame the owner's unit in the question (SNS-1) fixes nothing while
    promotion still works a whole record at a time, so the selector goes
    HERE, with no way to opt out. A caller that really does want every look
    enumerates them and can be read doing it.

    ⚠️ No default and no `None` sentinel, deliberately. Either would be an
    implicit-promotion escape hatch that re-opens OA-15 one layer down while
    every test stayed green — the failure is silent by construction, because
    a promoted frame the owner never saw looks exactly like one they picked.

    A ref that names no look in this subject's evidence is a per-row REFUSAL
    with a spoken reason, never a silent skip: the caller believed it was
    promoting something, and a set that quietly shrinks is how a split loses
    frames. A ref that matches several looks promotes once — `vec_ref` is the
    content sha, so two looks carrying one ref are one vector, and
    `add_exemplar()` answers a repeat with `already-held` anyway.

    The vectors are re-loaded from the dump's own `embed/` index rather than
    carried in the pack, which is the posture `photo_evidence` already takes:
    everything is re-derived from disk, because a promotion whose artifacts
    have gone is unproved rather than probably fine. Gate 2 requires the
    see-report and the thumbnail to still be there anyway, so an index that
    has been cleaned away refuses exactly the promotions that would have been
    refused regardless.

    Both `add_exemplar()` gates run unchanged: the provenance the labels file
    applied (never a default) and the look re-derived from the see-report. A
    `clip-matched:` or `draft:viewed-image:` member is refused at gate 1, a
    forged thumbnail at gate 2, and either way the refusal is a line in the
    audit log rather than a silent skip."""
    if only_refs is None:
        raise TypeError(
            f"attach_exemplars({subject.subject_id}) needs the vec_refs the "
            "owner actually picked. `None` is not 'every look' — a promotion "
            "nobody asked for is OA-15, and this signature is what stops it. "
            "Enumerate the refs, even when the answer is all of them.")
    wanted = set(only_refs)
    gained, notes = 0, []
    # Q8-b — the owner's own pick is the one thing that lifts `not`.
    for ref in registry.lift_not_this(
            subject.subject_id, wanted,
            reason="the owner picked this photo for this subject again"):
        notes.append(f"{ref}: the owner picked this photo for "
                     f"{subject.name or subject.subject_id} again, so the "
                     "earlier `not` on it is lifted")
    indexes = {}
    held = {look["vec_ref"] for entry in subject.record.get("evidence") or []
            for look in entry.get("looks") or [] if look.get("vec_ref")}
    for ref in sorted(wanted - held):
        notes.append(f"{ref}: no look in {subject.subject_id}'s evidence "
                     "carries this vec_ref — nothing was promoted for it. The "
                     "frame it names belongs to another subject, or the "
                     "observation behind it is gone")
        registry.audit({"subject_id": subject.subject_id, "vec_ref": ref,
                        "decision": "refused", "gate": "picked-ref",
                        "reason": notes[-1]})
    promoted = set()
    for entry in subject.record.get("evidence") or []:
        for look in entry.get("looks") or []:
            path, workdir = look.get("path"), look.get("workdir")
            if not (path and workdir and look.get("vec_ref")):
                notes.append(f"{path or '(no path)'}: the observation recorded "
                             "no work dir or no vec_ref, so the vector behind "
                             "the look cannot be found again")
                continue
            if look["vec_ref"] not in wanted or look["vec_ref"] in promoted:
                continue
            promoted.add(look["vec_ref"])
            if workdir not in indexes:
                # VS-3b: the identity index is loaded from the SAME work dir
                # and is allowed to be absent — a pack built before the stage
                # existed, or an owner who has never run it, promotes CLIP
                # exemplars exactly as before and simply gains no identity
                # evidence. Never a hard failure: the confirm is the owner's
                # answer, and it must land whether or not a second model ran.
                # Card 9: the registry IS the pack (`<pack>/photo-subjects`),
                # so its marks are read even when --profile alone bound it.
                indexes[workdir] = (load_embed_index(workdir),
                                    photo_identity.load_index(
                                        Path(workdir) / "embed",
                                        registry.dir.parent if registry.dir
                                        else None))
            (index, identity), (id_index, id_space) = indexes[workdir]
            row = index.get(path)
            if row is None:
                notes.append(f"{path}: no embedded vector in {workdir}/embed — "
                             "the index this look came from is gone or was "
                             "rebuilt without it")
                continue
            sha, vector = row
            if sha != look["vec_ref"]:
                notes.append(f"{path}: the index now holds {sha} where the look "
                             f"recorded {look['vec_ref']} — the file was "
                             "re-embedded, and a vector that is not the one "
                             "that was looked at may not become an exemplar")
                continue
            evidence = {k: look.get(k) for k in
                        ("see_report", "batch", "path", "sample", "label",
                         "run_id")}
            id_row = id_index.get(path)
            try:
                animals = int((id_row[0].get("det_count") if id_row else 0) or 0)
            except (TypeError, ValueError):
                animals = 0
            if animals > 1:
                # ⛔ G6-6d (G1) — D-24 / LL-PHO-136: a photo with 2+ animals is
                # no example of ANY one of them, in any space. The CLIP vector
                # is the whole frame and holds both animals, so it is not kept
                # either — with one name or two.
                notes.append(f"{path}: named, not remembered as a look — this "
                             f"photo holds {animals} animals")
                continue
            identity_vector = identity_quality = None
            if id_row is not None:
                id_meta, identity_vector = id_row
                identity_quality = photo_identity.exemplar_quality(id_meta)
            try:
                added, _dropped = registry.add_exemplar(
                    subject.subject_id, vector, look["vec_ref"], path,
                    confirmed_by=look.get("provenance"), identity=identity,
                    evidence=evidence, captured=look.get("captured"),
                    identity_vector=identity_vector, identity_space=id_space,
                    identity_quality=identity_quality)
            except ValueError as exc:
                notes.append(str(exc))
                continue
            if added and identity_quality is not None and not identity_quality[0]:
                # Spoken, not silent. The exemplar WAS gained; what did not
                # happen is that it joined the identity bank, and an owner
                # wondering why a subject still is not recognised deserves to
                # read the reason rather than infer it.
                notes.append(f"{path}: promoted, but not as identity evidence — "
                             f"{identity_quality[1]}")
            gained += int(bool(added))
    return gained, notes


def frames_centroid(subject, refs):
    """-> (the identity vector for one pick row's frames, [problems]).

    SNS-1b item 3's ⛔, and the reason this is the CALLER's job: a child's
    centroid is computed from the frames that row picked and passed in.
    `partition_subject()` deliberately cannot do it — the registry holds no
    per-look vector, so the only centroid it could reach is the parent's, and
    reassigning a first-sighting centroid to a child of a cluster the split
    just disproved is the first thing SNS-1b forbids.

    ⛔ There is NO fallback. A row whose vectors cannot all be re-derived
    returns None and its problems, and the caller refuses it. An obliging
    `or parent_centroid` would introduce exactly the forbidden thing in one
    keystroke, and every test would stay green while doing it.

    The vectors come from each dump's own `embed/` index, which is the posture
    `attach_exemplars()` and `worst_frames()` both take: a promotion or a
    partition whose artifacts have gone is unproved, not probably fine."""
    import numpy as np

    looks = {look["vec_ref"]: look for look in subject_looks(subject)}
    indexes, vectors, problems = {}, [], []
    for ref in refs:
        look = looks.get(ref)
        source, dump = (look or {}).get("path"), (look or {}).get("workdir")
        if not (source and dump):
            problems.append(f"{ref}: the observation behind this frame kept no "
                            "work dir, so the vector it was clustered on cannot "
                            "be found again")
            continue
        if dump not in indexes:
            indexes[dump] = load_embed_index(dump)
        row = indexes[dump][0].get(source)
        if row is None:
            problems.append(f"{source}: no embedded vector in {dump}/embed — "
                            "the index this frame came from is gone or was "
                            "rebuilt without it")
        elif row[0] != ref:
            problems.append(f"{source}: the index now holds {row[0]} where the "
                            f"frame recorded {ref} — the file was re-embedded, "
                            "and a vector that is not the one that was looked "
                            "at cannot define a subject")
        else:
            vectors.append(row[1])
    if problems or not vectors:
        return None, problems
    return np.mean(np.vstack(vectors), axis=0), []


def skip_groups(subject_id, refs_by_row, skip_subsets, frames_on_page):
    """The UNNAMED groups a subset `skip:` adds to one draft's partition: the
    frames the owner skipped, and the remainder — the frames they saw and left
    alone. -> [(kind, refs)], in the order `partition_subject()` is handed them.

    ⚠️ The remainder is the frames THIS PAGE RENDERED and the owner left alone
    — not every look the record holds. A mature draft can hold more looks than
    `contact_frames_per_draft` shows, and those stay behind in the superseded
    parent.

    That is SNS-1b item 4 applied evenly rather than an oversight: a split is
    proof the machine's grouping was wrong, so the looks nobody was shown are
    void attribution, exactly as they are on a pick-only split. They are not
    lost — the next see-run re-observes the files behind them and
    `observe_draft_subject()` matches them against this child's own centroid,
    which is the mechanism item 4 names. Widening this to `subject_looks()`
    would preserve the grouping the split disproved, and would give one surgery
    two doctrines depending on which row triggered it.

    ⛔ ONE definition, and `splits_here()` reads it too. The number of groups is
    the SPLIT discriminator, and a second copy that counted these differently
    would let the name-collision exemption fire on a split that never happens —
    which is the only thing standing between the owner and two subjects quietly
    sharing one name."""
    skipped = list(skip_subsets.get(subject_id) or [])
    if not skipped:
        return []
    claimed = {ref for refs in refs_by_row for ref in refs}
    claimed.update(skipped)
    remainder = [ref for ref in frames_on_page.get(subject_id, [])
                 if ref not in claimed]
    return ([("rejected", skipped)]
            + ([("draft", remainder)] if remainder else []))


def one_row_remedy_exists(name, units, skip_subsets):
    """Could the rows of this answer that took `name` be re-typed as ONE
    `pick:` row? -> bool.

    ⭐ The page-local collision refusal's own remedy — *put all of its frames
    on ONE `pick:` row* — asked as a question BEFORE it is printed. ⛔ Doc 8
    amendment (a), 2026-08-27, and the invariant behind it: **a refusal must
    never prescribe a row another gate would refuse.** D6, measured 20260827,
    is what happens when it does — `partition_subject()` said *say it as TWO
    rows*, this check said *say it as ONE*, and each door was the other's
    forbidden form.

    The merged row is refused when it would BOTH split a draft and name a
    subject beside it (`_partition_plan`'s `shared` gate), so it exists unless:

      * the rows name more than one draft between them — one draft's frames
        merge into a row that splits nothing and shares nothing, however many
        rows they were typed on; AND
      * one of those drafts is still partitioned after the merge, by a row
        under a DIFFERENT name or by a subset `skip:`.

    ⚠️ Read off the PARSED rows, because the collision check runs per row and
    cannot see that a later row also picks the same parent. It therefore counts
    rows `partition_picks()` may yet refuse — over-reporting, and harmless in
    the one place it is read: `pending` only gains a name a row was ACCEPTED
    with, so a refused row raises no page-local collision to be exempted from.

    ⛔ `pick:` rows only, matching `partition_picks()`. A legacy `group:` row
    splits nothing, and reading one as a partition would exempt a collision on
    a page where the one-row answer works."""
    named, names_on = set(), {}
    for unit in units:
        if unit["verb"] != "pick" or not unit["name"]:
            continue
        for subject_id in unit["subject_ids"]:
            names_on.setdefault(subject_id, []).append(unit["name"])
        if unit["name"] == name:
            named.update(unit["subject_ids"])
    if len(named) < 2:
        return True
    return not any(bool(skip_subsets.get(subject_id))
                   or any(other != name
                          for other in names_on.get(subject_id, []))
                   for subject_id in named)


def partition_picks(registry, block, accepted, refusals, changes, by, src,
                    go=False, skip_subsets=None, frames_on_page=None):
    """SNS-1b items 3 and 5 — decide, per draft, what this block's answer rows
    did to it, and perform the split when there was one. -> (the accepted rows
    with any split parent replaced by the child that row minted, [(rejected
    child, its parent)]).

    ## The subset `skip:` (item 5)

    A `skip:` naming SOME of a subject's frames is a split too, and the groups
    are the pick rows, the skipped frames, and **the remainder** — the frames
    the owner saw and left alone.

    ⛔ The remainder group is not optional and not bookkeeping. Without it the
    skipped frames are the only group, which is one row, which writes nothing
    — and the caller would be back to rejecting the whole record, the widening
    item 5 forbids. With it but WITHOUT minting a child, the leftover frames
    would sit inside a `superseded` parent: outside `is_draft`, so out of the
    question loop, so retired without anybody saying so. The remainder child
    is what keeps "these defer" true.

    The child born of the skipped frames is returned rather than rejected
    here, because writing `rejected` is the caller's job and it owns the log
    line and the entities twin.

    ⭐ **The discriminator is ROWS, never coverage** — the rule
    `partition_subject()` states and this caller must not undermine. One row
    picking three of a tile's five frames is not a split: the two left out are
    DEFERRED (SNS-3, SNS-11), and reading them as a partition would turn the
    owner's silence into a decision. Two rows naming frames of ONE draft is a
    split, whether or not they cover it.

    Every touched draft goes through `partition_subject()`, including the
    one-row cases that write nothing, because that is where a row's frames are
    validated against the record — one place, whichever case they turn out to
    be.

    ⚠️ **Under `--go` only, and the dry run is not weaker for it.** The verb
    audits its refusals at the moment it takes them, and `audit()` appends to
    `photo-subjects/memorize-audit.jsonl` immediately rather than at `save()`
    — which the pack snapshot hashes. A dry run that called it would move the
    pack it promised not to touch, and the pinned-snapshot check would then
    refuse the `--go` that followed. So the dry run does the caller-side half
    (`resolve_refs()` has already proved every frame belongs to the subject
    the map names, and `frames_centroid()` proves every vector is still
    re-derivable) and PREDICTS the split, in the posture the `revive` gesture
    already uses: checked here as well as inside the verb, so a dry run
    refuses what `--go` would refuse.

    ⛔ The unseen remainder inherits nothing and nothing is auto-clustered
    (SNS-1b item 4). This function mints exactly one child per pick row and
    leaves everything else where it is."""
    skip_subsets = skip_subsets or {}
    frames_on_page = frames_on_page or {}
    rows_for = {}
    for row in accepted:
        if row["unit"]["verb"] != "pick":
            continue
        for subject in row["members"]:
            rows_for.setdefault(subject.subject_id, []).append(row)
    for subject_id in skip_subsets:
        rows_for.setdefault(subject_id, [])

    dead, rejected_children = [], []
    for subject_id, rows in sorted(rows_for.items()):
        # LITERAL — this is the record about to be partitioned, and
        # `partition_subject()` refuses anything that is not a draft. Resolving
        # would hand it the winner of a fold.
        subject = registry.get_literal(subject_id)
        # Doc 4 v4 — a refusal here kills every row that claimed this draft
        # (`dead += rows`), so the drafts those rows named are the ones that
        # must not stay booked as asked.
        refusals.about = sorted({subject_id}
                                | {s.subject_id for row in rows
                                   for s in row["members"]})
        # The unnamed groups this subject also needs: the frames a `skip:` row
        # named, and whatever the owner neither picked nor skipped.
        skipped = list(skip_subsets.get(subject_id) or [])
        extra = skip_groups(subject_id,
                            [row["refs"].get(subject_id) or [] for row in rows],
                            skip_subsets, frames_on_page)
        splitting = len(rows) + len(extra) > 1
        groups, problems = [], []
        for refs, shared in ([(row["refs"].get(subject_id) or [],
                               [o for o in row["refs"] if o != subject_id])
                              for row in rows]
                             + [(refs, []) for _kind, refs in extra]):
            group = {"vec_refs": refs, "shared_with": shared}
            if splitting:
                # Required only for a split — `partition_subject()` refuses a
                # splitting row that arrives without one, and the one-row
                # cases write no record for a centroid to belong to.
                group["centroid"], bad = frames_centroid(subject, refs)
                problems += bad
            groups.append(group)
        if problems:
            refusals.append(
                f"Q{block['n']}: {subject_id} was picked apart by "
                f"{len(rows)} rows, and a child's identity is computed from "
                "the photographs its own row picked — which cannot be done "
                "here: " + "; ".join(problems) + ". Nothing was split and "
                "nothing was named. There is deliberately no fallback to the "
                "parent's own identity vector: this split is the proof that "
                "the machine's grouping was wrong, so re-using it would build "
                "both children out of the mistake.")
            dead += rows
            continue
        # ---- step 9, item 2 — the dry run walks the SAME sequence ----------
        #
        # ⛔ Asked in BOTH modes, before the split is predicted or performed,
        # in the posture `fold_refusal()` and `rename_refusal()` already use:
        # the verb audits at the decision point, so it runs under `--go` only,
        # and a dry run that could not ask it predicted a split `--go` would
        # refuse. Measured 2026-08-20 as `21 change(s) would be written, 0
        # refused` followed by `wrote 0 change(s), 1 refused`, on a row that
        # both splits one draft and shares a name across another.
        #
        # ⚠️ Under `--go` the verb is still CALLED, and still audits its own
        # refusal — a refusal nobody can trace is worse than a duplicated
        # check, and the two cannot disagree because they read one set of
        # gates. What the prediction adds is that the dry run says it first,
        # in the same words, and kills the same rows.
        why = registry.partition_refusal(subject_id, groups)
        if why and not go:
            refusals.append(f"Q{block['n']}: {why}")
            dead += rows
            continue
        if splitting and not go:
            # U3-1 — one line per line `--go` prints: each unnamed child, then
            # the parent. The children's ids are minted only by `--go`.
            for kind, refs in extra:
                changes.append(
                    f"{subject_id} -> would split off a new subject, rejected"
                    if kind == "rejected" else
                    f"{subject_id} -> would split off the {len(refs)} frame(s) "
                    "you neither picked nor skipped, kept as a draft and "
                    "asked about again")
            changes.append(
                f"{subject_id} -> would be superseded by a split into "
                f"{len(groups)} subject(s)")
            continue
        if not go:
            continue
        try:
            result = registry.partition_subject(
                subject_id, groups, by=by,
                reason=f"answer rows on {Path(src).name} Q{block['n']}")
        except ValueError as exc:
            refusals.append(f"Q{block['n']}: {exc}")
            dead += rows
            continue
        if result["case"] != "split":
            continue
        # `partition_subject()` mints one child per group, in the order the
        # groups were handed to it — pick rows first, then the skipped frames,
        # then the remainder. That order is the only thing tying a child back
        # to what the owner said about it, so the two lists are zipped rather
        # than searched.
        born = result["children"]
        for row, child in zip(rows, born):
            # The row now answers about the child it minted. Its picked frames
            # came with it — `_inherit_evidence()` copies the looks — so the
            # refs are unchanged and only the id they are filed under moves.
            # LITERAL — a child minted seconds ago is nobody's alias, and the
            # row is about to be written through it.
            row["members"] = [registry.get_literal(child["subject_id"])
                              if s.subject_id == subject_id else s
                              for s in row["members"]]
            row["refs"] = {(child["subject_id"] if k == subject_id else k): v
                           for k, v in row["refs"].items()}
        for (kind, _refs), child in zip(extra, born[len(rows):]):
            if kind == "rejected":
                rejected_children.append((child["subject_id"], subject_id))
            else:
                # ⛔ Left an `ai-drafted` record, deliberately and with nothing
                # written on it. These are the frames the owner saw and said
                # nothing about, and silence is never rejection — so they come
                # back next round under their own id, on their own centroid.
                changes.append(
                    f"{child['subject_id']} -> the {child['files']} frame(s) "
                    "you neither picked nor skipped, kept as a draft and "
                    "asked about again")
        changes.append(
            f"{subject_id} -> superseded by a split into "
            + ", ".join(c["subject_id"] for c in born)
            + "; its unpicked files inherit nothing and re-earn a name per "
              "file")
    return [row for row in accepted if row not in dead], rejected_children


def withdraw_entity(entities, subject_id):
    """Drop one subject's record from the entities twin. -> the bucket it was
    in, or None.

    The other half of `sync_entity()`, and it runs for the same reason that
    one exists: the registry and `photo-entities.json` are ONE subject model
    keyed on one id, so a withdrawal that moved only the registry would leave
    the file a human reads still asserting the identity the owner just took
    back. `confirm` writes both files together; so does this."""
    for bucket in ("people", "pets"):
        records = entities.get(bucket) or []
        keep = [r for r in records if r.get("subject_id") != subject_id]
        if len(keep) != len(records):
            entities[bucket] = keep
            return bucket
    return None


def record_unconfirm(pack, results, by=None, reason=None):
    """Write the pack-side half of a withdrawal: the maturity line that
    re-opens the question, and the entities twin.

    -> (log path, {subject_id: bucket}). `results` are
    `photo_subjects.Registry.unconfirm()`'s dicts.

    ⚠️ Every id on a maturity line is read by `settled_subjects()`, so one
    line names one subject and no bystander id appears on it. The name that
    was withdrawn goes on the evidence continuation, below the fold, where the
    scan never reaches it."""
    entities = load_json(entities_path(pack), {}) or {}
    lines, buckets = [], {}
    for result in results:
        subject_id = result["subject_id"]
        bucket = withdraw_entity(entities, subject_id)
        if bucket:
            buckets[subject_id] = bucket
        lines.append(
            f"| {UNCONFIRMED} | {subject_id}\n"
            f"  | evidence: the yes recorded for {result['was'] or '(unnamed)'}"
            f" is withdrawn; {len(result['exemplars_retained'])} exemplar(s) "
            "kept but attributing nothing until it is confirmed again, draft "
            f"centroid {'retained' if result['draft_centroid'] else 'ABSENT'}"
            + (f"\n  | why: {reason}" if reason else "")
            + f"\n  | by: {by} | src: photo_subjects.py --unconfirm")
    path = append_log(pack, lines)
    entities_path(pack).write_text(
        json.dumps(entities, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return path, buckets


def record_revive(pack, results, by=None, reason=None):
    """Write the pack-side half of a revival: the maturity line that re-opens
    a question the `rejected` line closed. -> the log path.

    `results` are `photo_subjects.Registry.revive()`'s dicts.

    ⚠️ No entities twin to touch, and that asymmetry with `record_unconfirm()`
    is the point: a rejected subject never had a name, so it was never written
    into `photo-entities.json` and there is nothing to withdraw from it. A
    revival returns a record to the draft pool, which is a pool the entities
    file does not describe.

    One line names one subject, like every other maturity line — every id on
    one is read by `settled_subjects()`."""
    lines = []
    for result in results:
        lines.append(
            f"| {REVIVED} | {result['subject_id']}\n"
            "  | evidence: the rejection recorded for this subject is taken "
            f"back; {len(result['exemplars_retained'])} exemplar(s) stay "
            "frozen and attribute nothing, draft centroid "
            f"{'retained' if result['draft_centroid'] else 'ABSENT'} and no "
            "longer suppressing"
            + (f"\n  | why: {reason}" if reason else "")
            + f"\n  | by: {by} | src: photo_subjects.py --revive")
    return append_log(pack, lines)


def record_fold(pack, registry, result, by=None, reason=None, src=None):
    """Write the pack-side half of a fold applied from the registry CLI: the
    entities twin, and the log line that says what happened.

    -> (log path, {subject_id: bucket}). `result` is
    `photo_subjects.Registry.fold_subjects()`'s dict and `registry` is the
    registry it came from, already saved — passed in rather than re-opened
    so the twin is written from the same records the fold mutated.

    ⚠️ The twin FOLLOWS, or the pack says two subjects where the registry says
    one — and it says it in the file a human reads. Each tombstone is dropped
    and the winner re-written, in that order, so the winner picks up its new
    `previous_names` and its unioned `active`. This is `apply_fold()`'s second
    half, lifted out of `cmd_confirm`'s four report channels so the operator
    door reaches the same two files the review-table door does; the fold
    itself is `fold_subjects()` and is not reimplemented here.

    ⚠️ `merged` is deliberately NOT one of `settled_subjects()`'s maturity
    tokens, for the reason `apply_fold()` gives: this line records what
    happened without closing any id in the log layer. The winner was already
    closed by its own confirmation, and the aliases leave the question loop by
    status alone."""
    entities = load_json(entities_path(pack), {}) or {}
    lost, buckets = [], {}
    for item in result["folded"]:
        subject_id = item["subject_id"]
        lost.append(subject_id)
        bucket = withdraw_entity(entities, subject_id)
        if bucket:
            buckets[subject_id] = bucket
    winner = registry.get_literal(result["winner"])
    if winner is not None:
        sync_entity(entities, winner, by)
    entities_path(pack).write_text(
        json.dumps(entities, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    path = append_log(pack, [
        f"| merged | {', '.join(lost)} -> {result['winner']} "
        f"({result['name'] or '(unnamed)'}) — the operator said these are one "
        "subject"
        f"\n  | evidence: {result['exemplars']} exemplar(s) after the join, "
        f"active {result['active'][0] or '?'} → "
        f"{result['active'][1] or 'open'}, previously known as "
        + (", ".join(result["previous_names"]) or "nothing else")
        + (f"\n  | why: {reason}" if reason else "")
        + f"\n  | by: {by} | src: {src or 'photo_subjects.py --merge'}"])
    return path, buckets


def append_log(pack, lines):
    path = log_path(pack)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    path.write_text(text.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n",
                    encoding="utf-8")
    return path


# ------------------------------------------------------------------ verbs ---

def page_tiles(text):
    """-> what a checkpoint page asks, as the answers are keyed: each question
    block's subjects and frame map. The owner-language prose is not in it."""
    return [(b["subject_ids"], sorted(b["frames"].items(), key=str))
            for b in parse_review(text)]


def cli_line(script, crops=False):
    """H-I — `<python> "<repo>/scripts/<script>"` for a printed next step:
    photo_index's ONE helper (the pages' python for a line that makes
    crops), never a second copy."""
    import photo_index
    return photo_index.run_line(script, crops=crops)


def stale_page_way_on(path, workdir):
    """M7 — how to get a fresh page for the same questions after a stale one
    was refused. -> one instruction that works.

    ⛔ Not "run `review` again": measured 20260920, the stale page's subjects
    count as asked while it sits in the work dir, so a new checkpoint page
    asked NOTHING (round budget 4 or 1 alike), the same number was refused as
    another round's tiles, and a rewritten batch page asked nothing while
    `--next-page` kept calling it unanswered. Moved OUT of the work dir, the
    page is no round and asked nothing — true, since not one row of it was
    applied — and the next page asks the same questions. ⛔ Out, never a
    rename inside: `REVIEW_GLOB` is wider than the name it parses (LL-PHO-94)."""
    move = (f"Move {path.name} OUT of the work dir (never rename it inside: "
            "any page name there still counts), then ")
    review = f"{cli_line('photo_memory.py', crops=True)} review \"{workdir}\""
    if BATCH_PAGE_IN_NAME.match(path.name):
        return (move + f"re-run `finish --go` (or `{review} --next-page`): "
                f"it writes {path.name} again "
                "from the pack as it stands, with the same questions. Nothing "
                "in the old page was applied, so only the typing is lost.")
    return (move + f"run `{review}`: it asks the "
            "same questions again on a fresh page. Nothing in the old page was "
            "applied, so only the typing is lost.")


def page_reuse_refusal(out, text):
    """-> the sentence `review` refuses with, or None. FIX8 F8-10.

    The existing page counts as a round, so a second `review --checkpoint N`
    over it asked the NEXT round's tiles under the same name: an answer typed
    for one set of tiles then joined different drafts, with no warning
    (C102-measured, UAT01-8 follow-up). The same tiles again is a repeat and
    is allowed. ⛔ The way out is a MOVE out of the work dir: `REVIEW_GLOB` is
    wider than the name it parses (LL-PHO-94), so a renamed page inside it is
    still read as a round."""
    if page_tiles(out.read_text(encoding="utf-8")) == page_tiles(text):
        return None
    return (f"⛔ {out.name} already holds a different round's tiles — nothing "
            "written. An answer typed on it belongs to THOSE tiles; writing "
            "this round under the same name would join different drafts. "
            "Run `review` without --checkpoint to take the next number; to "
            "reuse this one, move the old page out of the work dir first — "
            "never rename it inside, where the page pattern still reads it.")


def cmd_review(args):
    workdir = Path(args.workdir).resolve()
    pack = require_pack(workdir, args.profile)
    registry = photo_subjects.load(pack=pack)
    profile = pack.profile
    rmsg = photo_profile.review_messages(profile)
    if getattr(args, "next_page", False):
        return next_page(args, workdir, pack, registry, rmsg)
    batch = getattr(args, "batch", None)
    if batch is not None and (getattr(args, "final", False)
                              or getattr(args, "pre_plan", False)):
        sys.exit("--batch writes one batch's page; it is not a round, so "
                 "--final and --pre-plan do not apply to it")

    rows = build_rows(workdir, registry, profile, rmsg)
    # ⭐ Doc 8 amendment (b) — ONE predicate, read here and used twice. It is
    # the same expression `sns_round()` demotes a second `--final` by
    # (`final and final_round_asked()`), because a checkpoint that lifts layer
    # 2 and a checkpoint that fires the guaranteed round have to be the SAME
    # checkpoint: lifting without firing re-asks nothing, and firing without
    # lifting is the empty final round D7 measured.
    last_ask = bool(getattr(args, "final", False)
                    and not final_round_asked(workdir))
    questions, suppressed, round_deferred, held_for_final = build_questions(
        registry, workdir, pack, profile, rmsg, last_ask=last_ask, batch=batch)
    represented = build_representations(registry, profile, rmsg, workdir,
                                        FrameCrops(workdir, pack))
    places = []
    if batch is not None:
        rows = [row for row in rows if row["batch"] == batch]
        places = places_by_first_batch(workdir, pack).get(batch, [])
        if getattr(args, "places_only", False):
            # R2 — the pet pages are used up; a new place still gets its page,
            # and that page asks about the place alone.
            questions = []
    threshold = int(photo_profile.get(profile, "memory", "confirm_threshold",
                                      default=DEFAULT_CONFIRM_THRESHOLD))
    depending = sum(int(s.record.get("files", 0)) for s in registry.drafts)

    # ---- SNS-4 — does a round fire here, and why ----------------------------
    if batch is not None:
        # G6 — a batch page asks whenever its batch has something to ask. No
        # floor, no budget: the pages have their own count (`next_page()`).
        # No re-presentations either: the end-of-dump round keeps those.
        round_state = {"fire": bool(questions or places), "why": "page",
                       "round": 0, "rounds": rounds_fired(workdir), "cap": 0,
                       "floor": 0, "new": 0, "waiting": 0}
        represented = {"remembered": [], "rejected": []}
    else:
        round_state = sns_round(workdir, questions, asked_before(workdir),
                                registry, profile,
                                final=getattr(args, "final", False),
                                held_for_final=held_for_final)
    if batch is None and not round_state["fire"]:
        # ⛔ The block does not reach the page — see `sns_round()`. Every tile
        # it would have carried is reported as suppressed with the words that
        # say it is still open, in the shape the engine-deferred tiles already
        # use, because withheld is not asked and not rejected either.
        for question in questions:
            for tile in question["tiles"]:
                suppressed.append(
                    (tile["subject_id"],
                     "no SNS round at this checkpoint — "
                     f"{round_state['new']} new subject(s) against a floor of "
                     f"{round_state['floor']}, {round_state['rounds']} round(s) "
                     f"asked against a budget of {round_state['cap']}; still "
                     "ai-drafted, still askable"))
        questions = []
        # SNS-5 stays unconditional WITHIN a round; what a withheld checkpoint
        # withholds is the round itself, and a re-presentation with no question
        # beside it would be an interruption whose whole content is a budget
        # decision. The guaranteed final round is what bounds the wait, and it
        # is the bound SNS-5 itself names as acceptable: every remembered
        # subject re-presented at least once per dump.
        represented = {"remembered": [], "rejected": []}

    checkpoint = args.checkpoint
    if checkpoint is None:
        checkpoint = next_checkpoint(workdir)

    if getattr(args, "preview", False) and batch is None:
        # What reaches the owner is a question block; the page itself is
        # written either way and a page with no tile asks nothing.
        tiles = sum(len(q["tiles"]) for q in questions)
        asks = round_state["fire"] and tiles > 0
        print(f"preview: memory-review_C{checkpoint}.md would "
              + (f"ask the owner about {tiles} tile(s) ("
                 + ("the guaranteed end-of-dump round" if round_state["why"] == "final"
                    else f"{round_state['new']} newly-seen subject(s) reached the "
                         f"floor of {round_state['floor']}") + ")"
                 if asks else
                 "ask the owner nothing — "
                 + ("no subject to ask about" if round_state["fire"] else
                    f"{round_state['rounds']} round(s) asked against a budget of "
                    f"{round_state['cap']}" if round_state["why"] == "cap" else
                    f"{round_state['new']} newly-seen subject(s) against a floor "
                    f"of {round_state['floor']}"))
              + "; nothing written")
        return PRE_PLAN_ROUND_FIRED_RC if asks else 0

    if args.out:
        out = Path(args.out)
    elif batch is not None:
        out = workdir / batch_page_name(batch)
    else:
        out = workdir / f"memory-review_C{checkpoint}.md"
    batch_page = BATCH_PAGE_IN_NAME.match(out.name)
    uncropped = uncropped_frames(questions, represented)
    if uncropped:
        sys.exit(uncropped_refusal(out, uncropped))
    text = render_review(workdir, pack, registry, rows, questions, suppressed,
                         represented, checkpoint, threshold, depending,
                         round_state, round_deferred,
                         page=batch_page.group(1) if batch_page else None,
                         places=places)
    if batch is None and out.exists():
        refusal = page_reuse_refusal(out, text)
        if refusal:
            sys.exit(refusal)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    snapshot = pack.snapshot() or {"id": "(none)"}
    if batch is not None:
        print(f"page {out.name}: batch {batch}, {len(questions)} question(s) "
              f"carrying {sum(len(q['tiles']) for q in questions)} tile(s), "
              f"{len(places)} place(s) to name; pack {snapshot['id']} -> {out}")
        return 0
    # The same obligation on the operator's channel. The page says it in the
    # owner's language; this says it in the one the console speaks.
    print("SNS round "
          + (f"{round_state['round']} of {round_state['cap']}: FIRED — "
             + ("the last round of the dump always asks, and is not charged "
                "against the budget"
                if round_state["why"] == "final" else
                f"{round_state['new']} newly-seen subject(s) reached the floor "
                f"of {round_state['floor']}")
             if round_state["fire"] else
             f"{round_state['round']}: withheld — "
             + (f"{round_state['rounds']} round(s) already asked and the "
                f"budget for this dump is {round_state['cap']}"
                if round_state["why"] == "cap" else
                f"{round_state['new']} newly-seen subject(s) against a floor "
                f"of {round_state['floor']}")
             + f"; {round_state['waiting']} subject(s) wait, none booked as "
               "asked")
          # Said on the operator's channel and not the owner's: the owner is
          # not waiting on an answer about how many times `finish` was run.
          # Unsaid, a re-run would look like `--final` being ignored.
          + ("\n  (--final: the guaranteed end-of-dump round already asked in "
             "this work dir, so this checkpoint was judged on the floor and "
             "the budget like any other — one guaranteed round per dump, not "
             "per run)" if round_state.get("final_already") else ""))
    tiles = sum(len(q["tiles"]) for q in questions)
    ceiling = int(registry.defaults.get(
        "tiles_per_round",
        photo_subjects.DEFAULT_THRESHOLDS["tiles_per_round"]))
    print(f"checkpoint C{checkpoint}: {len(rows)} batch row(s), "
          f"{len(questions)} question(s) carrying {tiles} tile(s) against a "
          f"round ceiling of {ceiling}"
          # Said on the operator's channel because the owner's page says it in
          # prose and the operator's question is a number: how much of this
          # checkpoint's material the ceiling held back, as distinct from the
          # per-question clamp and from everything else in `suppressed`.
          + (f" ({round_deferred} draft(s) beyond it, deferred)"
             if round_deferred else "")
          + f", {len(suppressed)} suppressed, "
          f"{len(represented['remembered'])} remembered + "
          f"{len(represented['rejected'])} rejected re-presented; "
          f"{depending} file(s) depend on a draft (threshold {threshold}, "
          f"{'FIRED' if depending >= threshold else 'below'}); "
          f"pack {snapshot['id']} -> {out}")
    if getattr(args, "pre_plan", False) and round_state["fire"]:
        # ⛔ Said on the operator's channel, because the owner's page already
        # asks the question — what the operator needs to know is that nothing
        # should be copied until it is answered.
        # U5-06: `confirm` defaults to checkpoint 1, so from round 2 on a
        # command without the number opens the round-1 page, which is refused
        # as stale and writes nothing.
        confirm = (f'{cli_line("photo_memory.py")} confirm "{workdir}" '
                   f'--checkpoint {checkpoint}')
        if out.resolve() != (workdir / f"memory-review_C{checkpoint}.md").resolve():
            confirm += f' --file "{out}"'
        print(f"  (pre-plan: a question was put to the owner — answer {out.name} "
              f"and run `{confirm} --go` before "
              "planning, so a confirmed subject can be named INTO the folder)")
        return PRE_PLAN_ROUND_FIRED_RC
    return 0


def next_page(args, workdir, pack, registry, rmsg):
    """G6 (D-I6) — write the next batch page that is due. -> an exit status:
    PAGE_WRITTEN_RC, PAGE_WAITING_RC, or 0 when no page is due.

    Batches are walked in date order (batch number) after the last page the
    index records. A batch gets a page when it has a question: a draft
    observed in it that is still askable, while fewer than
    `memory.batch_pages` pages have asked about animals (R2: that count caps
    PET pages only) — or a place to name whose first batch it is (a new place
    always gets its page). A batch with neither is skipped, and the skip is
    written into the index log.

    ⛔ One page at a time (R4): confirming a page moves the pack, and a second
    page written beside it would be refused as stale."""
    import photo_index
    preview = getattr(args, "preview", False)
    target, index = dump_index(workdir, pack)
    if index is None:
        print("no index for this dump — batch pages need one "
              "(`photo_index.py init`); nothing written")
        return 0
    pages = index.get("pages") or []
    done = {p.get("batch") for p in pages}
    waiting = sorted((page_batch(p.name), p.name)
                     for p in Path(workdir).glob(BATCH_PAGE_GLOB)
                     if page_batch(p.name) is not None
                     and page_batch(p.name) not in done)
    if waiting:
        page = waiting[0][1][:-3]
        print(f"page {page}.md is written and not applied yet — answer it, then:\n"
              f"  {cli_line('photo_memory.py')} confirm \"{workdir}\" --page {page} --go\n"
              f"  {cli_line('photo_index.py')} apply-page \"{workdir}\" {page} --go")
        return PAGE_WAITING_RC
    cap = photo_profile.batch_pages(pack.profile)
    pet_pages = sum(1 for p in pages if "sns" in (p.get("kinds") or []))
    places = places_by_first_batch(workdir, pack)
    last = max((b for b in done if b is not None), default=0)
    batches = sorted(int(b["batch"]) for b in
                     (load_json(Path(workdir) / "batches.json", {}) or {})
                     .get("batches", []))
    said = {entry.get("change") for entry in index.get("log") or []}
    logged = []
    for number in batches:
        if number <= last:
            continue
        kinds = []
        if pet_pages < cap and build_questions(registry, workdir, pack,
                                               pack.profile, rmsg,
                                               batch=number)[0]:
            kinds.append("sns")
        if places.get(number):
            kinds.append("snl")
        if kinds:
            break
        why = (f"the {cap} pet page(s) are used and no new place is named here"
               if pet_pages >= cap else "nothing to ask")
        change = f"B{number:02d}: no page — {why}"
        print(f"  {change}")
        if change not in said and not preview:
            photo_index.log_entry(index, "photo_memory review --next-page",
                                  change, "D-I6: pages go to the first batches "
                                  "with a question", by="engine")
            logged.append(change)
    else:
        number = None
    if logged:
        photo_index.save(target, pack, index)
    if number is None:
        print(f"no batch page is due ({pet_pages} of {cap} pet page(s) used)")
        return 0
    if preview:
        print(f"preview: {batch_page_name(number)} would be written "
              f"({' and '.join(kinds)}) — nothing written")
        return PAGE_WRITTEN_RC
    cmd_review(argparse.Namespace(workdir=str(workdir), profile=args.profile,
                                  batch=number, out=None, checkpoint=None,
                                  places_only="sns" not in kinds))
    return PAGE_WRITTEN_RC


def name_distance(a, b):
    """-> the Levenshtein distance between two strings (insert, delete,
    substitute, each 1), per character."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def near_names(name, others):
    """FIX7 (U7-4) -> [(subject_id, other name, distance)] for each name in
    `others` ([(subject_id, name)]) close enough to `name` to be a typo of it.

    Script-neutral and list-free: both names are NFKC-normalized and
    casefolded, then compared by `name_distance()`. Close is distance 0 (they
    differ only in letter case or width), or distance 1 when the shorter name
    has at least 4 characters. ⚠️ So a name of 2 or 3 characters — most CJK
    names — is only ever matched at distance 0: one character in two is half
    the name, and a warning there would fire on different animals."""
    import unicodedata

    def fold(text):
        return unicodedata.normalize("NFKC", text).casefold()

    mine, out = fold(name), []
    for subject_id, other in others:
        theirs = fold(other)
        distance = name_distance(mine, theirs)
        if distance == 0 or (distance <= 1 and min(len(mine), len(theirs)) >= 4):
            out.append((subject_id, other, distance))
    return out


def near_name_warning(prefix, name, other, subject_id, distance):
    """The one sentence U7-4's warning is said in, at confirm."""
    how = ("matches it once letter case and width are ignored" if distance == 0
           else "is one letter away from it")
    return (f"{prefix}: {name!r} {how} — {other!r} ({subject_id}) is a name "
            "this pack already holds. Nothing is refused. If it is the same "
            f"animal, write `name: {other} {SAME_TOKEN}`; if the new name is a "
            "typo, fix it later with `photo_memory.py rename`; if it is a "
            "different animal, nothing is needed.")


def name_collision_refusal(prefix, name, where, distinct_row, way_on):
    """SNS-7's ask, in ONE set of words for the TWO rows that can raise it.

    ⛔ One refusal, not a near-identical sentence per grammar. The owner's
    mistake is the same mistake — a name typed that the pack already holds —
    and the file says so at the `pick:` site in as many words. Two copies would
    drift into two explanations of one rule, and the one that drifted would be
    whichever row is typed less often.

    What DOES differ is the syntax each door is typed in, which is why it
    arrives as an argument rather than being written into the sentence: a
    `recheck:` row told to answer on a `name:` row is being sent to a row that
    is not on its page, and an instruction the owner cannot follow is worse
    than none."""
    return (f"{prefix}: the name {name!r} is already taken {where}. Nothing "
            "was written for this row, because whether that is the same one "
            "is yours to say and not the engine's — two animals can share a "
            "name, and answering it by matching the letters is how two "
            "subjects quietly become one. Three ways on: type a different "
            "name; or, if this really is a separate subject that happens to "
            f"share the name, write {distinct_row} and it gets its own slot; "
            f"or, if it is genuinely the same one, {way_on}")


def distinct_holders(registry, ids, name):
    """F13 (iii)(b) — which of `ids` the owner named `name` as a DIFFERENT
    animal (`distinct`). Read off the stamp that answer writes, never
    inferred."""
    return [sid for sid in ids
            if (registry.get_literal(sid) or None) is not None
            and registry.get_literal(sid).record.get(
                photo_subjects.DISTINCT_FLAG) == name]


def distinct_refusal(prefix, name, held, stamped, registry, profile,
                     rows=True):
    """The one refusal left where `rename one of them first` used to stand —
    and it asks the owner for nothing about their pet's name.

    ⭐ The owner never composes the answer: each holder comes with the exact
    `name:` to type and one fact a person can tell them apart by — its file
    count and where its last photo was taken (F10's phrase, F10's reader).
    `rows=False` on the `recheck:` door, which has no such syntax."""
    where = FrameWhere(profile, photo_profile.review_messages(profile))
    facts = []
    for sid in held:
        subject = registry.get_literal(sid)
        looks = subject_looks(subject)
        fact = (f"{sid}: {registry.display_files(subject)} file(s), last "
                f"photo {where.phrase(looks[-1]) if looks else 'none yet'}"
                + (", named as a different animal" if sid in stamped else ""))
        facts.append(f"`name: {name} {SAME_TOKEN} {sid}` ({fact})" if rows
                     else fact)
    return (f"{prefix}: {name!r} is held by {', '.join(held)}, and "
            f"{', '.join(stamped)} was named as a DIFFERENT animal that shares "
            f"the name (you answered `{DISTINCT_TOKEN}`), so which one these "
            "frames are cannot be told from the name, and folding them would "
            "merge two animals. Nothing was written for this row. "
            + ("To say which one, keep your `pick:` and `who:` as typed and "
               "write one of: " if rows else "They are: ")
            + "; ".join(facts)
            + ". Left unanswered, the drafts come back as a question next "
              "round.")


def fold_notice(prefix, name, held, registry):
    """F13 (iii)(b) — said in the dry run and again under `--go`, in the
    same words: which ids fold, which one keeps the name, which become
    aliases. A fold of an older pack's same-named records is never silent."""
    keeper = min(held, key=registry._ordinal)
    others = [sid for sid in held if sid != keeper]
    return (f"{prefix}: {name!r} is held by {', '.join(held)} and none was "
            f"named as a different animal, so `{SAME_TOKEN}` folds them: "
            f"{keeper} keeps the name, {', '.join(others)} become alias(es), "
            "and these frames join it. Folders already written keep their "
            "names on disk.")


def apply_fold(registry, entities, ids, name, who, by, src, prefix, go, out):
    """SNS-14's fold, applied AND reported — one implementation for both doors
    into it. -> True when something was written or predicted.

    ⚠️ `--go` only, like every other verb that audits at the decision point
    (`unconfirm`, `revive`, `attach_exemplars`). A dry run that folded would
    write the memorize audit log, which moves the pack snapshot — the one thing
    this file's determinism rule forbids. The dry run still says exactly what
    `--go` would do, because the caller judged the same ids through
    `fold_refusal()` before getting here.

    `out` is `cmd_confirm`'s four report channels passed as one dict. A fold
    speaks on all four — a change, an advisory about folders on disk, a log
    line, and a refusal if the verb still says no — and threading four lists as
    positionals is how a caller ends up passing `notes` where `changes` goes."""
    if not go:
        out["changes"].append(
            f"{' + '.join(ids)} -> would be folded into one subject under "
            f"{name!r}; the earlier id keeps the name, the rest become aliases")
        return True
    try:
        result = registry.fold_subjects(ids, name=name, who=who, by=by,
                                        reason=src)
    except ValueError as exc:
        out["refusals"].append(f"{prefix}: {exc}")
        return False
    lost = [item["subject_id"] for item in result["folded"]]
    # ⚠️ The twin follows, or the pack says two subjects where the registry
    # says one — and it says it in the file a human reads. `--sync` cannot
    # repair that: its loop only adds and updates, and `withdraw_entity()` is
    # the only remover, so a fold that skipped this would leave the loser
    # asserting an identity nothing in the registry holds any more. Dropped
    # first and re-written second, so the winner's own record picks up its new
    # name and its unioned `active`.
    for gone in lost:
        withdraw_entity(entities, gone)
    sync_entity(entities, registry.get_literal(result["winner"]), by)
    out["changes"].append(
        f"{', '.join(lost)} -> folded into {result['winner']}, which holds "
        f"{who}/{name} and {result['exemplars']} exemplar(s); the folded id(s) "
        "stay as aliases so nothing that already names them breaks")
    # ⛔ The advisory the SPEC asks for, and it NAMES them. Folders already
    # written under a losing name are not moved, renamed or touched — this
    # engine is copy-only — and the rename ledger is what keeps them
    # resolvable. Saying nothing would leave the owner to discover two folders
    # for one animal and guess why.
    orphaned = result["names_retired"]
    if orphaned:
        out["notes"].append(
            f"{prefix}: folders already written under "
            + ", ".join(repr(n) for n in orphaned)
            + " keep those names on disk — nothing was moved or renamed. They "
            f"resolve to {result['winner']} through the rename ledger, and the "
            "next dump's photographs of this subject sort under "
            f"{result['name']!r}.")
    for item in result["folded"]:
        if item["absorbed_moved"]:
            out["notes"].append(
                f"{prefix}: {len(item['absorbed_moved'])} draft(s) the sweep "
                f"had absorbed under {item['subject_id']} now follow "
                f"{result['winner']} — withdrawing its name releases them, as "
                "it did before the fold.")
    if result["dropped_for_cap"]:
        out["notes"].append(
            f"{prefix}: the two exemplar sets were joined and "
            f"{len(result['dropped_for_cap'])} of them were evicted for "
            "redundancy at the cap — the set kept is the diverse one, which is "
            "what two views of one subject should leave behind.")
    # ⚠️ `merged` is deliberately NOT one of `settled_subjects()`'s maturity
    # tokens, for the reason `absorbed` is not: this line records what happened
    # without closing any id in the log layer. The winner was already closed by
    # its own confirmation and the aliases leave the question loop by status
    # alone.
    out["log_lines"].append(
        f"| merged | {', '.join(lost)} -> {result['winner']} "
        f"({who} {name}) — the operator said these are one subject"
        f"\n  | evidence: {result['exemplars']} exemplar(s) after the join, "
        f"active {result['active'][0] or '?'} → "
        f"{result['active'][1] or 'open'}, previously known as "
        + (", ".join(result["previous_names"]) or "nothing else")
        + f"\n  | by: {by} | src: {src}")
    return True


def apply_promotion(registry, target, members, refs, by, src, prefix, go, out):
    """SNS-16's answer, applied AND reported. -> True when something was
    written or predicted.

    ⭐ The draft → already-confirmed direction, which no decision covered
    until 2026-08-20 and which arrives on every dump after the first. The
    owner picked frames, typed a name the pack already holds and answered the
    collision with `same`; that is a promotion into the subject behind the
    name.

    ⛔ `only_refs` is the frames the owner picked on THIS row, read off the
    page's `frames:` map — never `None`, and never re-derived from the record,
    which `observe_draft_subject()` has appended to since the page was
    rendered. SNS-1b's per-look rule governs a promotion exactly as it governs
    a first confirm.

    ⛔ No similarity bar and no `{n}` to tune. See
    `Registry.attach_draft_to_subject()` for the two measurements behind the
    signature; the short version is that a bar would refuse a real photograph
    of the right animal, and once the owner has answered there is no guess
    left to bound.

    ⚠️ `--go` only for the promotion itself, like every other verb that audits
    at the decision point. The dry run says exactly what it would do, because
    every refusal this row can earn was spoken before it got here."""
    picked = sum(len(refs.get(s.subject_id) or []) for s in members)
    ids = ", ".join(s.subject_id for s in members)
    if not go:
        # FIX7 (U7-3) — the lines --go prints, one per draft and one for the
        # target, so the two counts agree (UAT01-7: 4 predicted, 7 written).
        for subject in members:
            # U3-1 — counted in LOOKS, the unit `--go` reports, by the same
            # read-only copy `attach_draft_to_subject()` counts.
            looks = sum(len(entry.get("looks") or [])
                        for entry in registry._inherit_evidence(
                            subject.record,
                            set(refs.get(subject.subject_id) or [])))
            out["changes"].append(
                f"{subject.subject_id} -> would join {target.subject_id} "
                f"({target.who}/{target.name}); {looks} look(s) carried "
                "across, and the draft stops being asked about. "
                f"Withdrawing {target.name!r} releases it again")
        out["changes"].append(
            f"{target.subject_id} -> {picked} picked frame(s) would be offered "
            "to the memorize rule; --go says how many become exemplars")
        return True
    # ⛔ Every member judged BEFORE the first one moves. One row is one
    # answer, so a row that would refuse on its third draft must refuse before
    # its first is absorbed — the two-pass rule the split already keeps.
    for subject in members:
        why = registry.attach_draft_refusal(
            subject.subject_id, target.subject_id,
            refs.get(subject.subject_id) or [])
        if why:
            out["refusals"].append(f"{prefix}: {why}")
            return False
    gained = 0
    for subject in members:
        result = registry.attach_draft_to_subject(
            subject.subject_id, target.subject_id,
            refs.get(subject.subject_id) or [], by=by, reason=src)
        # AFTER the looks are carried across, and only then: the promotion
        # reads the target's own evidence, so the order is what makes the
        # picked frames reachable at all.
        added, look_notes = attach_exemplars(
            registry, target, refs.get(subject.subject_id) or [])
        out["notes"] += [f"{prefix}: {note}" for note in look_notes]
        gained += added
        out["changes"].append(
            f"{subject.subject_id} -> joined {target.subject_id} "
            f"({target.who}/{target.name}); {result['looks']} look(s) carried "
            f"across, and the draft stops being asked about")
    if not gained:
        # F14's warning channel, one door along. The answer is honoured and
        # the half that makes it stick is missing: without a new exemplar the
        # subject recognises this animal's new photographs no better than it
        # did before the owner answered.
        out["notes"].append(
            f"{prefix}: {target.subject_id} gained NO exemplar from this "
            "answer — the notes above and the memorize audit log say which "
            "look was refused and why. The draft(s) still stop being asked "
            "about, and withdrawing the name releases them.")
    # N16 — one line for the target WHATEVER it gained, because the dry run
    # prints one before it can know: it said 8 and `--go` wrote 7 whenever a
    # promotion gained nothing (UAT02-01).
    out["changes"].append(
        f"{target.subject_id} -> {gained} exemplar(s) memorized from the "
        "frames you picked; its name, its who and its first sighting are "
        "unchanged")
    out["log_lines"].append(
        f"| absorbed | {ids} -> {target.subject_id} ({target.who} "
        f"{target.name}) — the operator said these frames are the subject the "
        "pack already knows"
        f"\n  | evidence: {picked} picked frame(s), {gained} exemplar(s) "
        "gained; no similarity bar (SNS-16)"
        f"\n  | by: {by} | src: {src}")
    return True


def judge_rename(registry, request, now, end, profile):
    """-> (refusal or None, plan or None) for ONE name request, judged
    against the pack as it will stand after every request (`end`), and
    against `now` only to tell a token that answers nothing. Plans are
    ("fold", ids) or ("rename", ids that will share the name).

    The sentences are the ones the `recheck:` row always spoke; `syntax`
    says how the owner would type a row on the door the request came from."""
    sid, name = request["subject_id"], request["name"]
    same, distinct = request["same"], request["distinct"]
    door = request["door"]
    subject = registry.get_literal(sid)
    if subject is None:
        return f"{door} no such subject {sid}", None
    held = sorted(h for h, n in end.items() if n == name and h != sid)
    held_now = sorted(h for h, n in now.items() if n == name and h != sid)
    if name == subject.name and not (same or distinct):
        # The name it already holds, typed out: "still right". Nothing to do
        # and nothing wrong.
        return None, None
    if (same or distinct) and not (held or held_now):
        return (f"{door} `{SAME_TOKEN if same else DISTINCT_TOKEN}` "
                f"answers a collision, and nothing else in this pack "
                f"holds the name {name!r} — there is no other half. "
                "Nothing was written. Check the spelling against the "
                "remembered section of this page, or drop the word and "
                f"the row simply renames {sid} to {name!r}."), None
    if held and not (same or distinct):
        return name_collision_refusal(
            f"{door} {sid}", name, f"in this pack, by {', '.join(held)}",
            request["syntax"](DISTINCT_TOKEN),
            f"write {request['syntax'](SAME_TOKEN)} and the two are folded "
            "into one subject — the earlier id keeps the name, the later "
            "one stays as an alias so folders already written under it "
            "still resolve, and nothing on disk moves."), None
    if same:
        # SNS-14. ⛔ `fold_refusal()` here, so the dry run refuses exactly
        # what `--go` refuses.
        others = held or held_now
        stamped = (distinct_holders(registry, others, name)
                   if len(others) > 1 else [])
        if stamped:
            return distinct_refusal(f"{door} {sid}", name, others, stamped,
                                    registry, profile, rows=False), None
        why = registry.fold_refusal([sid] + others)
        return (f"{door} {why}", None) if why else (None, ("fold",
                                                          [sid] + others))
    # A plain rename, or one the owner armed with `distinct`. ⛔ The five
    # status guards are `rename_refusal()`'s, never re-written here.
    why, _gate = registry.rename_refusal(sid)
    return (f"{door} {why}", None) if why else (None, ("rename", held))


def rename_subjects(registry, entities, requests, by, src, go, out, profile):
    """ADR 0004 — the ONE path that corrects a confirmed subject's name. The
    `recheck:` row and the `rename` verb both come here, so there is never a
    second rename path.

    ⭐ **Every request is judged against the END state** — the names as they
    will stand once every other request here has applied — and re-judged
    until no new refusal appears. That is what makes a swap one answer
    (`A=Birk`, `B=Lotus`) and what makes the dry run say what `--go` does:
    the old inline loop judged the second row against a pack the dry run had
    not moved, and refused a row `--go` then applied (measured on 7b74570).

    It renames a RECORD, never a folder: `photo_execute` holds "no delete,
    move or rename call" as a hard property. Folders keep their names and
    resolve through the rename ledger."""
    now = {s.subject_id: s.name for s in registry.subjects
           if s.status == photo_subjects.STATUS_CONFIRMED}
    refused, plans = set(), []
    while True:
        end = dict(now)
        for i, request in enumerate(requests):
            if (i not in refused and not request["same"]
                    and request["subject_id"] in end):
                end[request["subject_id"]] = request["name"]
        plans, fresh = [], []
        for i, request in enumerate(requests):
            if i in refused:
                continue
            why, plan = judge_rename(registry, request, now, end, profile)
            if why:
                fresh.append((i, why))
            elif plan:
                plans.append((request, plan))
        if not fresh:
            break
        for i, why in fresh:
            refused.add(i)
            out["refusals"].append(why)
    for request, (kind, ids) in plans:
        sid, name, door = request["subject_id"], request["name"], request["door"]
        subject = registry.get_literal(sid)
        if kind == "fold":
            apply_fold(registry, entities, ids, name, subject.who, by, src,
                       f"{door} {sid}", go, out)
            continue
        was = subject.name
        if go:
            try:
                registry.rename(sid, name)
            except ValueError as exc:
                out["refusals"].append(f"{door} {exc}")
                continue
            # ⚠️ The twin follows the name, or `photo-entities.json` asserts
            # the old one and `--sync` cannot repair it.
            sync_entity(entities, subject, by)
            if ids and request["distinct"]:
                subject.record[photo_subjects.DISTINCT_FLAG] = name
        out["changes"].append(
            f"{sid} -> renamed from {was!r} to {name!r}"
            + (f"; {', '.join(ids)} keep(s) the same name, as "
               f"`{DISTINCT_TOKEN}` asked" if ids else "")
            + ". Folders already written under the old name keep it on "
              "disk — nothing was moved — and resolve through the "
              "rename ledger.")
        out["log_lines"].append(
            f"| renamed | {sid} {was!r} -> {name!r} — the operator corrected "
            f"the name\n  | by: {by} | src: {src}")


RENAME_PAIR = re.compile(r"^\s*(subj-\d{4,})\s*=\s*(.*?)\s*$", re.S)


def cmd_rename(args):
    """ADR 0004's rename verb — correct a CONFIRMED subject's name with no
    checkpoint page, `subj-0001=Name` per pair, all pairs judged together so
    a swap is one command. `=Name same` / `=Name distinct` answer a collision
    exactly as a `recheck:` row does. Records only, never a folder."""
    workdir = Path(args.workdir).resolve()
    pack = require_pack(workdir, args.profile)
    registry = photo_subjects.load(pack=pack)
    entities = load_json(entities_path(pack), {}) or {}
    out = {"changes": [], "notes": [], "log_lines": [], "refusals": []}
    requests, seen = [], set()
    for pair in args.pairs:
        found = RENAME_PAIR.match(pair)
        if not found:
            out["refusals"].append(
                f"{pair!r} is not `subj-NNNN=Name` — nothing was applied for "
                "it.")
            continue
        sid, name = found.group(1), found.group(2)
        same = distinct = False
        while name:
            if NAME_DISTINCT.search(" " + name):
                distinct, name = True, NAME_DISTINCT.sub("", " " + name).strip()
            elif NAME_SAME.search(" " + name):
                same, name = True, NAME_SAME.sub("", " " + name).strip()
            else:
                break
        subject = registry.get_literal(sid)
        if not name:
            why = "carries no name"
        elif sid in seen:
            why = ("is named twice in this command — one record takes one "
                   "answer")
        elif subject is None:
            why = "is not in this pack"
        elif subject.status != photo_subjects.STATUS_CONFIRMED:
            why = (f"is {subject.status}: only a name you have confirmed can "
                   "be corrected here — a draft is named at the checkpoint")
        elif same and distinct:
            why = (f"carries both `{SAME_TOKEN}` and `{DISTINCT_TOKEN}` — the "
                   "two opposite answers to one question")
        else:
            why = None
        seen.add(sid)
        if why:
            out["refusals"].append(f"{sid} {why}. Nothing was applied for it.")
            continue
        requests.append({"subject_id": sid, "name": name, "same": same,
                         "distinct": distinct, "door": "`rename`",
                         "syntax": (lambda token, s=sid, n=name:
                                    f"`{s}={n} {token}`")})
    rename_subjects(registry, entities, requests, args.by,
                    "`photo_memory.py rename`", args.go, out, pack.profile)
    for refusal in out["refusals"]:
        print(f"  ! {refusal}")
    for note in out["notes"]:
        print(f"  ~ {note}")
    for change in out["changes"]:
        print(f"  {change}")
    if not args.go:
        print(f"dry run — {len(out['changes'])} change(s) would be written, "
              f"{len(out['refusals'])} refused. Re-run with --go.")
        return 1 if out["refusals"] else 0
    if out["changes"]:
        registry.save()
        entities_path(pack).write_text(
            json.dumps(entities, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        append_log(pack, out["log_lines"])
        write_subject_drafts(pack, registry, pack.profile)
    print(f"wrote {len(out['changes'])} change(s); pack now "
          f"{(pack.snapshot() or {'id': '(none)'})['id']}")
    return 1 if out["refusals"] else 0


def split_child_holding(registry, parent, ref):
    """F11 — the child of a split `parent` whose own looks hold the frame
    keyed `ref`, or None. -> Subject.

    A picked frame is recorded under the draft id its `frames:` entry named,
    and a split supersedes that draft in the same confirm. Following the
    PARSED ref into `split_into` is what keeps the owner's picked frame
    attached to the child it was picked into; without it every frame of a
    split draft was silently dropped from `see-labels.json`.

    ⛔ Nothing is matched: `resolve_refs()` against each child's own looks, and
    an ambiguous or absent ref resolves to nobody. A child split again is
    followed down, for the same reason."""
    for child_id in parent.record.get("split_into") or []:
        child = registry.get_literal(child_id)
        if child is None:
            continue
        keys, problems = resolve_refs(child, [ref])
        if not keys or problems:
            continue
        if child.status == photo_subjects.STATUS_SUPERSEDED:
            return split_child_holding(registry, child, ref)
        return child
    return None


def cmd_confirm(args):
    workdir = Path(args.workdir).resolve()
    pack = require_pack(workdir, args.profile)
    registry = photo_subjects.load(pack=pack)
    # FIX8 F8-1 — a photo's CURRENT name is said as it stood before this page
    # moved anything, so a draft named on this same page still reads as a draft.
    names_before = {s.subject_id: s.name for s in registry.subjects}
    entities = load_json(entities_path(pack), {}) or {}
    by = args.by
    # ⭐ Doc 4 v4 — the refusal channel books the drafts each refused row was
    # about, so layer 2 can leave them exactly as they stood before the page
    # was rendered. `refusals.about` is re-pointed wherever the scope changes
    # below; see `RefusalChannel`.
    changes, log_lines = [], []
    picked_frames = []
    shared_logs, shared_blocks = [], []
    refusals = RefusalChannel()
    # F14's own channel. A look that could not be promoted is NOT a refused
    # answer — the owner's who/name is written either way — so it must not
    # flip the exit code the way a refusal does. It still has to be said out
    # loud: a confirmed subject with no exemplar is not recognisable next
    # dump, and that is the whole defect being fixed.
    notes, warnings = [], []
    # The four channels a fold speaks on, bundled once so `apply_fold()` takes
    # them as one argument instead of four positionals a caller can transpose.
    report = {"changes": changes, "notes": notes, "log_lines": log_lines,
              "refusals": refusals}
    # SNS-9 — a pack written before the cap was removed still carries the key,
    # and a knob that no longer does anything is worse unmentioned than
    # absent: the owner who set it to 3 believes three names is what they get.
    if "named_subject_budget" in (registry.defaults or {}):
        notes.append(
            "this pack sets `named_subject_budget`, which is no longer read — "
            "there is no cap on how many subjects may be remembered. "
            "`named_subjects_warn_at` is what the count is said against now.")
    # R2 — the identity index is OPTIONAL by design (see attach_exemplars), but
    # absent must not mean SILENT. This function already speaks when a frame
    # FAILS the exemplar quality bar; until now it said nothing when there was
    # no bar at all, which is the louder fact. Measured in UAT01 (20260904):
    # photo_identity had never run, so every promoted exemplar was a
    # whole-image CLIP vector, one confirmed subject's bank ended up 60%
    # another animal (D-24), and every subject verdict in the run was CLIP
    # while the pack recorded no reason why (LL-PHO-105).
    # Run-level, said once — a per-subject note would repeat it per confirm.
    if not (workdir / "embed" / "identity.csv").exists():
        notes.append(
            "no identity index in this work dir, so every exemplar promoted "
            "by this confirm is a WHOLE-IMAGE vector: a frame holding two "
            "animals contributes both of them to whichever subject it is "
            "picked for, and the exemplar quality bar cannot run. Subject "
            "verdicts here are CLIP, not identity. Build it once, then "
            "re-run this confirm:\n"
            f"    {photo_platform.run_line(photo_platform.venv_python(), Path(__file__).resolve().parent / 'photo_identity.py')}"
            f" \"{workdir}\"\n"
            "  Exemplars already promoted are repaired with `photo_subjects.py "
            "review --prune --drop <vec_ref> --subject <id>`.")
    # SNS-5's two clearing writes. Collected here and written AFTER the main
    # write block: `record_unconfirm()` re-reads `photo-entities.json` off
    # disk to drop the identity the owner took back, and this function holds
    # its own in-memory copy loaded before any of that — writing the two in
    # the other order would restore the record that was just withdrawn.
    withdrawn, revived = [], []
    # SNS-15 — the subjects THIS run confirmed, which is the set the sweep may
    # ride on. Collected in both modes so the dry run can say what `--go`
    # would sweep; the sweep itself needs exemplars that only `--go` writes.
    confirmed_now, review_src = [], None

    if args.sync:
        # Reconcile what the registry already holds into the entities twin.
        # Every confirmed subject must exist on both sides under one id; a
        # pack where only the registry half exists does not satisfy the
        # one-subject model, whatever the design doc says.
        for subject in sorted(registry.subjects, key=lambda s: s.subject_id):
            if subject.is_draft or not (subject.name and subject.who):
                continue
            bucket, _record = sync_entity(entities, subject, by)
            changes.append(f"{subject.subject_id} -> {ENTITIES_NAME} {bucket}"
                           f" (sync)")
    else:
        page = getattr(args, "page", None)
        if page:
            if args.file:
                sys.exit("--page and --file both name the page — pass one")
            name = page if page.endswith(".md") else f"{page}.md"
            if Path(name).name != name or page_key(name) is None:
                sys.exit(f"{page!r} is not a review page name — a batch page "
                         "is `P-B03`, a checkpoint page `memory-review_C2.md`")
            path = workdir / name
        else:
            path = (Path(args.file) if args.file
                    else workdir / f"memory-review_C{args.checkpoint}.md")
        if not path.is_file():
            sys.exit(f"{path} does not exist — run `review` first")
        text = path.read_text(encoding="utf-8")
        review_src = path.name

        # ---- G6 — a batch page is confirmed BY ITS OWN NAME (U5-06) ------
        #
        # WHOLE-FILE, for the pin's reason below: the page's name is what its
        # answers are booked under, so a page handed in under another name
        # books them against the wrong page, or against none.
        marked = PAGE_MARKER_IN_TEXT.search(text)
        named = BATCH_PAGE_IN_NAME.match(path.name)
        if (named or marked) and not (
                named and marked and named.group(1) == marked.group(1)):
            written = (f"was written as {marked.group(1)}" if marked else
                       "carries no batch-page mark")
            way_on = (f"confirm it by that name: `--page {marked.group(1)}`"
                      if marked else "write the page again with `review`")
            print(f"  ! {path.name} {written}. NOTHING in the file was applied "
                  f"— not one row. Its answers are booked under the page's "
                  f"name, so {way_on}.")
            print("dry run — 0 change(s) would be written, 1 refused. "
                  "Re-run with --go." if not args.go else
                  "wrote 0 change(s); the pack is untouched")
            return 1

        # ---- SNS-1b item 1 — the pinned pack snapshot ---------------------
        #
        # ⛔ WHOLE-FILE, not per row, and that is the one place in this
        # function where all-or-nothing is right. Everywhere else `confirm`
        # applies per row so a bad row cannot discard the nine the owner got
        # right (SNS-11). Here the thing that has gone stale is the MAP: frame
        # numbers, tile numbers and subject ids all point into the pack as it
        # stood when the page was written, so a pack that has moved does not
        # invalidate one row, it invalidates the page's whole coordinate
        # system. Applying the rows that happen to still resolve would promote
        # a photograph nobody picked, under a number that used to mean
        # something else.
        #
        # This is the proof three refusals were written waiting for: the
        # superseded-parent gate, the OA-16 confirmed-subject gate and the
        # `reject` gesture all say, in as many words, that they cannot tell a
        # fresh page from one rendered before the decision they are refusing.
        # ⚠️ It is a FOURTH guard and it replaces none of them — a check on the
        # pack as a whole cannot see a record that moved inside a pack that did
        # not, and `--sync` reaches those write paths with no file at all.
        pinned = pinned_snapshot(text)
        snapshot = pack.snapshot() or {}
        if pinned and snapshot.get("id") and pinned != snapshot["id"]:
            print(f"  ! {path.name} was written when this pack held {pinned}, "
                  f"and the pack now holds {snapshot['id']}. NOTHING in the "
                  "file was applied — not one row. The numbers on that page "
                  "name photographs and subjects as they stood when it was "
                  "written, so a pack that has moved since turns every one of "
                  "them into a guess, and a guess here puts a name on the "
                  "wrong photograph. " + stale_page_way_on(path, workdir))
            print("dry run — 0 change(s) would be written, 1 refused. "
                  "Re-run with --go." if not args.go else
                  "wrote 0 change(s); the pack is untouched")
            return 1

        # Q8-c — before ANY row: a crop that is not a real animal must be out
        # of the frame's count when the shared-frame rule and the exemplar
        # bar read it.
        refusals.about = []
        mark_not_animals(workdir, args.profile, parse_review(text), refusals,
                         changes, by, path.name, args.go)
        for block in parse_review(text):
            for ref, was in block["skip_filed"]:
                notes.append(f"skip {ref} was under Question {was}; frame "
                             f"{ref.split('.')[0]} is in Question {block['n']}"
                             " — filed there.")
            refusals.about = []
            for number, qs in block["skip_ambiguous"]:
                refusals.append(
                    f"Q{block['n']}: `skip:` names frame {number}, which is in "
                    + " and ".join(f"Question {q}" for q in qs)
                    + " — it cannot be told which one was meant, so nothing "
                    "was rejected for it. Type it on that question's `skip:` "
                    "row.")
            for number, q in block["skip_conflict"]:
                refusals.append(
                    f"Q{block['n']}: `skip:` names frame {number}, which is in "
                    f"Question {q}, and Question {q}'s own `skip:` row says "
                    "something different — nothing was rejected for it. Type "
                    f"it on Question {q}'s `skip:` row.")
            if not block["answered"]:
                continue
            # G6-6d — FIRST, before any row is judged or U-3 notes a pick.
            logged = shared_frame_rows(workdir, block, refusals, pack)
            if logged:
                shared_logs.extend(logged)
                shared_blocks.append((block, logged))
            read_mixed_rows(block, registry, changes)
            # U-3: the owner's picks, kept as (frame sample path, the draft id
            # that frame stood for, the name typed on the row). Resolved and
            # filtered AFTER the pack is saved — a row refused below must
            # record nothing, and the only honest test of "was this row
            # applied" is what the registry says afterwards.
            for unit in block["picks"]:
                if unit["verb"] != "pick" or not unit["name"]:
                    continue
                for n in unit["numbers"]:
                    frame = block["frames"].get(n)
                    if frame and frame.get("path"):
                        picked_frames.append((frame["path"],
                                              frame["subject_id"],
                                              frame.get("ref"),
                                              unit["name"],
                                              bool(unit.get("distinct"))))
            ids = block["subject_ids"]
            # Scope for the refusals that are about the PAGE and not about a
            # row — they book nothing, because no row of the owner's was
            # refused. Re-pointed at each row below.
            refusals.about = []
            if not ids:
                refusals.append(f"Q{block['n']}: no `subjects:` line — the "
                                "storage key is what an answer attaches to")
                continue
            # `skip:` is the ONLY permanent outcome, and it is always explicit:
            # named tile numbers under F16, the whole block under the pre-F16
            # checkbox. A tile the owner simply left out reaches nothing here,
            # which is what "silence is never rejection" means in code.
            # ⛔ A frame on a `pick:` row AND on the `skip:` row is a
            # CONTRADICTION, and both rows are refused. They now read the same
            # numbering (SNS-1), which is what makes the contradiction
            # expressible at all — and what makes honouring either half a
            # guess. The two answers are opposites: one says this is a subject
            # worth naming, the other says never ask about it again. Before
            # this the skip loop simply ran first, so the permanent answer won
            # and the refusal the owner saw was about the other row.
            contested = sorted(set(block["skip_numbers"])
                               & {n for unit in block["picks"]
                                  for n in unit["numbers"]})
            if contested:
                refusals.about = sorted(
                    {block["frames"][n]["subject_id"] for n in contested
                     if n in block["frames"]})
                refusals.append(
                    f"Q{block['n']}: frame(s) "
                    f"{','.join(str(n) for n in contested)} are named on a "
                    "`pick:` row AND on the `skip:` row. Those say opposite "
                    "things about the same photograph, so BOTH rows were "
                    "refused and nothing was written for either — not the "
                    "name, and not the rejection. Decide which one you meant "
                    "and type it again; every other row on this question was "
                    "applied as it stands.")
                block["skip_numbers"], block["skip_ids"] = [], []
            refusals.about = []
            for number in block["skip_unknown"]:
                refusals.append(
                    f"Q{block['n']}: `skip:` names frame {number}, which this "
                    "question never rendered — nothing was rejected for it. "
                    + (("Frame numbers run through the whole page: a frame in "
                        "the remembered section is checked on its own "
                        f"`{RECHECK_KEY}:` row, not skipped here")
                       if number in block.get("page_shown", ())
                       else f"Frame {number} is on no question of this page"))
            refusals.about = list(block["skip_ids"])
            if block["skip_numbers"] and not block["skip_armed"]:
                # Refused out loud, never honoured quietly and never dropped
                # quietly either: the owner who typed numbers here meant
                # something, and both readings of what they meant are wrong to
                # guess. The tiles stay drafts, which is the safe half.
                refusals.append(
                    f"Q{block['n']}: `skip:` names frame(s) "
                    f"{','.join(str(t) for t in block['skip_numbers'])} without "
                    "the word `confirm` on the line — nothing was rejected. "
                    "Rejection is the one answer no later checkpoint can undo, "
                    "so it is typed twice or not at all")
                block["skip_numbers"] = []
                block["skip_ids"] = []
            if block["skip_numbers"] and not block["frames"]:
                # Decision A, on the permanent row. A page with no frame map
                # numbered tiles, and a tile is a whole record: honouring it
                # would reject every frame behind a number the owner typed
                # while looking at a page that could not offer them one at a
                # time. Refused for the same reason a legacy `group:` row is,
                # and the fix is the same one line.
                refusals.append(
                    f"Q{block['n']}: `skip:` names number(s) "
                    f"{','.join(str(t) for t in block['skip_numbers'])} on a "
                    "page written before frames were numbered, so what those "
                    "numbers point at cannot be told. Nothing was rejected. "
                    "Run `photo_memory.py review` again and type the frame "
                    "numbers on the new page — it costs nothing and can be "
                    "re-run as often as you like")
                block["skip_numbers"] = []
                block["skip_ids"] = []
            skipped_all = {}
            for subject_id in block["skip_ids"]:
                # SNS-1b item 5. Naming SOME of a subject's frames says
                # something different from naming all of them, and the
                # difference is the whole of what `pick:` bought: "the thing
                # in these frames — never ask" is not "this record — never
                # ask". The subset case is answered further down, once the
                # split machinery has been reached; here it is only separated
                # out, because the two must never share a code path.
                named = [n for n in block["skip_numbers"]
                         if block["frames"].get(n, {}).get(
                             "subject_id") == subject_id]
                whole = block["frames_by_subject"].get(subject_id, [])
                skipped_all[subject_id] = set(named) == set(whole)
            subset = [sid for sid, whole in skipped_all.items() if not whole]
            # SNS-1b item 5, signed: split-then-reject. The skipped frames
            # become their OWN child through the same machinery a `pick:`
            # split uses, with a centroid computed from those frames, and that
            # child is what is rejected — so OA-14's retained centroid
            # suppresses the thing in those photographs and nothing else.
            #
            # ⛔ Never widened to the whole subject. "The thing in these frames
            # — never ask" is not "this record — never ask", and the second
            # reading destroys information silently: it retires the frames the
            # owner left alone, which they had said nothing at all about.
            skip_subsets, frames_on_page = {}, {}
            for subject_id in list(subset):
                refusals.about = [subject_id]
                # LITERAL — the refs below are resolved against THIS record's
                # own looks, and the split that follows is written onto it.
                subject = registry.get_literal(subject_id)
                named = [block["frames"][n]["ref"] for n in block["skip_numbers"]
                         if block["frames"].get(n, {}).get(
                             "subject_id") == subject_id]
                shown = [block["frames"][n]["ref"]
                         for n in block["frames_by_subject"].get(subject_id, [])]
                keys, bad = resolve_refs(subject, named) if subject else ([], [])
                page, more = resolve_refs(subject, shown) if subject else ([], [])
                if subject is None or bad or more:
                    refusals.append(
                        f"Q{block['n']}: `skip:` names part of {subject_id}'s "
                        "frames and they cannot be told apart from the pack as "
                        "it stands"
                        + (": " + "; ".join(bad + more) if bad or more else "")
                        + ". Nothing was rejected for this subject.")
                    subset.remove(subject_id)
                    continue
                skip_subsets[subject_id] = keys
                frames_on_page[subject_id] = page
            skip_ids = ([s for s in block["skip_ids"] if s not in subset]
                        if block["skip_numbers"]
                        else (ids if block["skip"] else []))
            for subject_id in skip_ids:
                refusals.about = [subject_id]
                # LITERAL — every branch in this loop reads a status, and the
                # last one WRITES `rejected` onto whatever it was handed.
                subject = registry.get_literal(subject_id)
                if subject is None:
                    refusals.append(f"Q{block['n']}: no such subject "
                                    f"{subject_id}")
                    continue
                if subject.status == photo_subjects.STATUS_MERGED_INTO:
                    # SNS-14, and it has to be named HERE rather than left to
                    # the no-name check further down: a tombstone holds no
                    # name, so it would sail past that check and be written
                    # `rejected` — retiring an alias that older folders and
                    # plan CSVs still resolve through, and doing it silently.
                    refusals.append(
                        f"Q{block['n']}: {subject_id} was folded into "
                        f"{subject.record.get('merged_into') or 'another subject'} "
                        "and cannot be rejected — it is an alias kept so older "
                        "folders still resolve, not a subject anybody is asked "
                        "about. This review was written before the fold.")
                    continue
                if subject.status == photo_subjects.STATUS_SUPERSEDED:
                    # Same stale-review path as the member loop, with a
                    # different ending: the parent would flip `superseded` ->
                    # `rejected` while `split_into` still points at live
                    # children, handing the rejection machinery a record that
                    # was already answered.
                    refusals.append(
                        f"Q{block['n']}: {subject_id} was superseded by a "
                        "split — it cannot be rejected. Its children are "
                        f"{', '.join(subject.record.get('split_into') or []) or 'none'}")
                    continue
                if subject.status == photo_subjects.STATUS_REJECTED:
                    # Not a refusal: the owner asked for a state the record is
                    # already in, and nothing about that is wrong. Said out
                    # loud anyway, because a silent no-op on the one permanent
                    # row is indistinguishable from a rejection that worked.
                    notes.append(f"Q{block['n']}: {subject_id} is already "
                                 "rejected — nothing changed, and its "
                                 "rejection still stands")
                    continue
                # ⭐ OA-16, and it is the reason this block reads status BEFORE
                # name: a review file rendered before a confirm still names the
                # tile, still parses, and flipped a CONFIRMED subject to
                # `rejected` while it kept its name and its exemplars — rc 0,
                # no refusal spoken. `rejected` is outside `is_draft`, so
                # `photo_plan.py:132` then rendered that name as a confirmed
                # `who` for a subject the owner had just asked never to hear
                # about again; `recognisers` meanwhile dropped it, so the name
                # was being printed by a record that recognises nothing.
                #
                # ⛔ Refused, never downgraded: stripping the name here would
                # discard a human yes on the strength of a stale file, and the
                # two answers cannot both be honoured. The owner who means it
                # withdraws the name first, which is one command and leaves
                # the history intact.
                #
                # ⚠️ This is not a rule that "a confirmed subject may never be
                # rejected". Step 4 re-presents confirmed subjects in every
                # round, and "stop asking about this one" becomes a gesture the
                # owner can make there, against a record the round is showing
                # them. What is refused here is that gesture arriving from a
                # file written before the confirmation existed.
                if subject.status == photo_subjects.STATUS_CONFIRMED:
                    refusals.append(
                        f"Q{block['n']}: {subject_id} is confirmed as "
                        f"{subject.who or '?'} {subject.name or '?'} — a "
                        "rejection cannot be typed onto it, and this review "
                        "was written before that confirmation. Withdraw the "
                        "name first (`photo_subjects.py review --unconfirm "
                        f"{subject_id} --go`), then reject the draft it "
                        "becomes.")
                    continue
                if subject.name:
                    # The no-name rule as an invariant rather than a check on
                    # one status: a rejected record must not hold a name,
                    # whatever status it arrives in, because every reader that
                    # renders a name gates on the name and not on the status.
                    refusals.append(
                        f"Q{block['n']}: {subject_id} holds the name "
                        f"{subject.name!r} and cannot be rejected while it "
                        "does — a rejected record renders as a confirmed "
                        "identity if it keeps one. Withdraw the name first.")
                    continue
                subject.record["status"] = photo_subjects.STATUS_REJECTED
                # SNS-5's layer-2 exemption is spent the moment the question
                # is answered again. Popped on BOTH answer paths — one missed
                # site and a withdrawn-then-answered subject is re-asked at
                # every checkpoint for the life of the work dir.
                subject.record.pop(photo_subjects.REOPENED_FLAG, None)
                subject.record["rejected"] = {
                    "at": datetime.now().strftime("%Y-%m-%d"), "by": by,
                    "src": f"{path.name} Q{block['n']}",
                    # U2-10 — WHICH rejection this was. Written on every
                    # rejection, including the default one, so a record that
                    # states nothing is an OLD record rather than an
                    # unanswered question.
                    "basis": block.get("skip_basis") or BASIS_NOT_MINE}
                changes.append(f"{subject_id} -> rejected")
                if registry.draft_centroid(subject_id) is None:
                    # F14's warning channel, one status along and for the same
                    # reason: the answer is honoured, and half of what makes it
                    # STICK is missing. OA-14 suppresses on the retained draft
                    # centroid, so a rejection without one is a rejection that
                    # evaporates at the dump boundary — the subject returns
                    # under a new id, which is the defect this build closed.
                    # Reachable: a subject created already-named holds no
                    # centroid, and `--unconfirm` says the same sentence about
                    # the same gap. Not a refusal — the rejection is real for
                    # this run and nothing here is wrong to write.
                    warnings.append(
                        f"Q{block['n']}: {subject_id} is rejected but holds NO "
                        "draft centroid, so nothing suppresses it on the next "
                        "dump and the same subject will be drafted again under "
                        "a new id. It stays rejected in this pack; the "
                        "permanence is what is missing.")
                log_lines.append(
                    f"| rejected | subject {subject_id} — the operator asked "
                    f"never to be asked again\n  | evidence: "
                    f"{subject.record.get('files', 0)} file(s) across "
                    f"{len(subject.observed_in)} batch(es)\n  | by: {by} | "
                    f"src: {path.name} Q{block['n']}")
            if block["skip"] and not block["skip_numbers"]:
                continue
            if block["answer"] is not None and block["who"] is None \
                    and not block["groups"] and not block["picks"]:
                # A cardinality answer: recorded, never acted on silently.
                #
                # F15. The maturity token is `human-answered` and NOT
                # `human-confirmed`, and that word is the whole finding.
                # `settled_subjects()` reads `human-confirmed` as "never ask
                # about this subject again, in any run"; a line carrying that
                # token while naming two ids therefore retired one of them
                # forever, although nobody had said who it was. A cardinality
                # answer settles CARDINALITY, not identity: it says how many
                # subjects are in front of the camera, never what either of
                # them is called. Both members stay askable, and the count
                # they were given is written onto their records below.
                log_lines.append(
                    f"| human-answered | cardinality of {' + '.join(ids)}: "
                    f"{block['answer']}\n  | evidence: two lookalike draft "
                    f"clusters\n  | by: {by} | src: {path.name} Q{block['n']}")
                changes.append(f"{' + '.join(ids)} -> cardinality "
                               f"{block['answer']!r} recorded")
                for subject_id in ids:
                    # LITERAL — this writes onto the record the page named. A
                    # cardinality answer about a folded id says nothing about
                    # the winner, and writing it there would be an answer
                    # nobody gave about a subject nobody was shown.
                    subject = registry.get_literal(subject_id)
                    if subject is not None:
                        subject.record["cardinality_answer"] = block["answer"]
                continue
            # SNS-1. One block, N answer units — one per `pick:` row, plus
            # whatever a work dir with history still holds. A pre-F16 block has
            # no tile map at all, so its who/name applies to the one subject
            # list it carries; a block that DOES render tiles must carry its
            # who/name on an answer row, because "all of them" is a merge
            # nobody typed.
            units = list(block["picks"]) + list(block["groups"])
            refusals.about = list(ids)
            if not units and (block["who"] or block["name"]):
                if block["tiles"]:
                    refusals.append(
                        f"Q{block['n']}: `who`/`name` were given outside any "
                        "`pick:` row. Which frames they name is the answer — "
                        "the engine will not assume all of them.")
                    continue
                units = [{"verb": "group", "numbers": [], "subject_ids": ids,
                          "unknown": [], "refs": {}, "distinct": False,
                          "same": False,
                          "who": block["who"], "name": block["name"]}]
            claimed = set(block["skip_numbers"])
            # ⭐ TWO PASSES, and the split is why. Every row this block can
            # refuse is refused in the first pass, before one record moves;
            # `partition_subject()` then runs on rows that are known to be
            # answerable, and the writes happen last.
            #
            # ⛔ Not one pass. A split mints children and supersedes their
            # parent, so a row refused AFTER the surgery — for its name, its
            # budget, anything — would leave the owner's answer half applied:
            # a parent out of the question loop and children nobody named,
            # which no later reader could tell from a deliberate outcome. That
            # is the rule `partition_subject()` states for itself ("refusals
            # write nothing at all"), kept by its caller rather than assumed.
            accepted, pending, folds, promotions = [], set(), [], []
            # ⭐ Doc 8 amendment (a), 2026-08-27. `named_here` keeps the
            # ACCEPTED rows per name, so a name the collision check stood down
            # for can be withdrawn WHOLE if the split it rests on dies.
            named_here, shared_names = {}, set()
            # SNS-16 / B2 — how many of this block's rows claim each draft. A
            # promotion marks the record `absorbed`; any other row confirms it
            # where it stands, and a record cannot be both — so a draft claimed
            # by a promotion and another row is split first (below).
            rows_claiming = {}
            for other in units:
                for claimed_id in other["subject_ids"]:
                    rows_claiming[claimed_id] = \
                        rows_claiming.get(claimed_id, 0) + 1
            # ⭐ B2 (owner decision, 20260918) — a draft answered by a
            # promotion row AND another row (or a `skip:`) is SPLIT, never
            # refused. SNS-16's "a promotion row is one answer" is narrowed to
            # this: each row still answers about the frames IT picked, so the
            # draft is partitioned by rows first (`partition_picks()`, each
            # child on its own row's frames and centroid) and the promotion
            # then joins its own child to the remembered subject. The old
            # refusal told the owner to "answer the other on the next round",
            # which on the last round never came (UAT02-01: 3 of 5 pages).
            #
            # ⛔ Still refused, BOTH rows: a promotion and another row that
            # share a FRAME. That is one photograph given two answers, not a
            # draft to split — and the frame clash below refuses only the
            # later row, which would let the promotion write alone.
            frame_rows = {}
            for other in units:
                for n in set(other["numbers"]):
                    frame_rows.setdefault(n, []).append(other)
            answered_twice = set()
            for other in units:
                if not other.get("same"):
                    continue
                if any(len(frame_rows.get(n, [])) > 1 for n in other["numbers"]):
                    answered_twice.update(other["subject_ids"])
            for unit in units:
                refusals.about = list(unit["subject_ids"])
                if unit.get("crop_refusal"):
                    refusals.append(f"Q{block['n']}: {unit['crop_refusal']} "
                                    "The row was not applied.")
                    continue
                doubled = sorted(set(unit["subject_ids"]) & answered_twice)
                if doubled and any(len(frame_rows.get(n, [])) > 1
                                   for n in unit["numbers"]):
                    refusals.append(
                        f"Q{block['n']}: a frame of {', '.join(doubled)} is on "
                        "more than one row here, and one of those rows joins it "
                        "to a subject the pack already remembers. One photograph "
                        "cannot be two answers. BOTH rows were refused and "
                        "nothing was written for either — put each frame on "
                        "ONE row.")
                    continue
                if any(n in contested for n in unit["numbers"]):
                    # Its half of the contradiction was refused above, by
                    # name and once for the pair. Speaking it again per row
                    # would report one mistake as two.
                    continue
                # A frame belongs to one pick row or to `skip:`, never to both
                # and never to two rows. Choosing for the owner here would be
                # the engine merging on its own, which is the one thing C
                # removes.
                clash = sorted(t for t in unit["numbers"] if t in claimed)
                claimed.update(unit["numbers"])
                if clash:
                    refusals.append(
                        f"Q{block['n']}: frame(s) {clash} appear on more than "
                        "one row. A frame is one row's, or `skip:`'s, never "
                        "both.")
                    continue
                if unit["unknown"]:
                    word = "frame(s)" if unit["verb"] == "pick" else "tile(s)"
                    refusals.append(
                        f"Q{block['n']}: `{unit['verb']}:` names {word} "
                        f"{unit['unknown']}, which this question never "
                        "rendered — the row was not applied. Frame numbers run "
                        "through the whole page: one in the remembered section "
                        f"is checked on its own `{RECHECK_KEY}:` row, which "
                        "promotes nothing and cannot be picked.")
                    continue
                # ONB-13: both halves, or neither. PER ROW, so one bad row
                # cannot quietly defer the tiles the owner did answer for.
                if not (unit["who"] and unit["name"]):
                    refusals.append(
                        f"Q{block['n']}: `who` and `name` are one answer "
                        f"(ONB-13) — got who={unit['who']!r}, "
                        f"name={unit['name']!r}. A half-identified subject "
                        "cannot be used by the naming step and is not written.")
                    continue
                if not unit["subject_ids"]:
                    refusals.append(
                        f"Q{block['n']}: a `{unit['verb']}:` row carries "
                        f"{unit['who']}/{unit['name']} but no numbers — "
                        "there is nothing to attach the answer to.")
                    continue
                # F15. ONE answer settles EVERY id it was given, not the first
                # one on the line. Settling only `ids[0]` left the rest unnamed
                # while the log claimed the question was closed.
                #
                # The N member ids keep their own records and share one name.
                # That is transitional BY DESIGN: the human-attested merge is
                # its own verb and its own build, and nothing here decides that
                # two ids are one subject — the doctrine this file states
                # everywhere.
                members = []
                for subject_id in unit["subject_ids"]:
                    refusals.about = [subject_id]
                    # LITERAL — the write below sets `name`, `who` and
                    # `human-confirmed` on whatever record this returns, and
                    # the refusals around it read a status. A resolving fetch
                    # would answer a stale page's question by writing onto the
                    # winner of a fold the page has never heard of.
                    subject = registry.get_literal(subject_id)
                    if subject is None:
                        refusals.append(f"Q{block['n']}: no such subject "
                                        f"{subject_id}")
                        continue
                    if subject.status == photo_subjects.STATUS_MERGED_INTO:
                        # SNS-14's fifth guard, on the one path that writes a
                        # name. A tombstone holds none, so nothing below would
                        # stop this row resurrecting an alias as a second
                        # confirmed identity for the animal the fold just made
                        # single. Reachable exactly the way the superseded case
                        # is: a review file rendered BEFORE the fold still
                        # names the loser and still parses.
                        winner = (subject.record.get("merged_into")
                                  or "another subject")
                        refusals.append(
                            f"Q{block['n']}: {subject_id} was folded into "
                            f"{winner} and cannot take a name — this review "
                            "was written before the fold. Answer under "
                            f"{winner}, which is the subject those frames now "
                            "belong to.")
                        continue
                    if subject.status == photo_subjects.STATUS_SUPERSEDED:
                        # The member write below sets `name` and
                        # `human-confirmed` on whatever id it is handed, and it
                        # does not go through `rename()` when the record holds
                        # no name — which is exactly a split parent. Confirming
                        # one resurrects it as a recogniser holding the same
                        # looks as its own children, so it competes with them
                        # in `match()` and wins as often as not.
                        #
                        # Reachable because a review file rendered BEFORE the
                        # split still names the parent and still parses.
                        # ⚠️ SNS-1b item 1's pinned-snapshot check is built
                        # now, at the top of this function, and it catches the
                        # ordinary version of this — a split moves the pack, so
                        # a page written before one no longer matches. It does
                        # NOT discharge this refusal: it compares the pack as a
                        # whole and only when the page pinned an id at all, so
                        # a hand-written table, an edited header, a pack with
                        # no directory to hash and `--sync` (no file at all)
                        # every one of them arrives here with the check
                        # silent. A guard that fires only when another guard
                        # already fired is not the guard on this write.
                        refusals.append(
                            f"Q{block['n']}: {subject_id} was superseded by a "
                            "split and cannot take a name — this review was "
                            "written before the split. Answer its children "
                            "instead: "
                            f"{', '.join(subject.record.get('split_into') or []) or 'none'}")
                        continue
                    members.append(subject)
                refusals.about = list(unit["subject_ids"])
                if not members:
                    continue
                if unit["verb"] != "pick":
                    # ⛔ Decision A — a legacy row is parsed and REFUSED, and
                    # this is the refusal. `group:` names TILES, and a tile is
                    # a whole record: honouring one would promote every look
                    # behind it, including the frames of a second animal
                    # nobody rendered. That is OA-15's exact mechanism, and
                    # accepting it "just for old files" would leave it alive
                    # in precisely the work dirs that have enough history to
                    # hit it.
                    #
                    # ⛔ There is deliberately no fallback that promotes the
                    # rendered frames instead. This call site cannot see them:
                    # a page with no `frames:` line never wrote them down, and
                    # re-deriving `contact_sheet[:n]` now reads a record
                    # `observe_draft_subject()` has appended to since.
                    #
                    # Refused WHOLE rather than half applied. Writing the name
                    # and skipping the promotion would leave a confirmed
                    # subject that recognises nothing and is no longer asked
                    # about — the F14 defect, arrived at deliberately — and
                    # the owner could not simply answer again, because the
                    # question would be closed.
                    refusals.append(
                        f"Q{block['n']}: this row uses `{unit['verb']}:`, "
                        "which names whole groups, on a page that was written "
                        "before frames were numbered. Nothing was applied for "
                        f"{', '.join(s.subject_id for s in members)}. Which "
                        "photographs an answer covers is now the answer, so "
                        "run `photo_memory.py review` again and pick frame "
                        "numbers on the new page — it re-reads everything, "
                        "costs nothing, and can be re-run as often as you "
                        "like. Nothing you typed here was written, so nothing "
                        "was lost.")
                    continue
                # Every picked frame turned back into the storage key it
                # names, BEFORE anything is written. A ref that names no look
                # on the subject it was mapped to, or two, refuses the whole
                # row: the owner believed they were picking a photograph, and
                # a set that quietly shrinks is how a split loses frames.
                resolved, problems = {}, []
                for subject in members:
                    keys, bad = resolve_refs(
                        subject, unit["refs"].get(subject.subject_id, []))
                    resolved[subject.subject_id] = keys
                    problems += bad
                if problems:
                    refusals.append(
                        f"Q{block['n']}: " + "; ".join(problems)
                        + ". The row was not applied — re-run "
                          "`photo_memory.py review` for a page whose frame "
                          "numbers match the pack as it stands.")
                    continue
                # ONB-13's `{10}` registry budget. A resource limit, not a
                # policy one: nothing here restricts WHO may be named, only how
                # many names the pack carries into a model's context.
                #
                # So it counts distinct NAMES, not subjects. One answer over a
                # five-member group is ONE name in that context; counting it
                # five times would let a group refuse ITSELF part way through —
                # members 1-2 written, 3-5 refused, one answer half applied —
                # which is a worse outcome than either accepting or refusing it
                # whole. The check runs BEFORE the loop for the same reason.
                member_ids = {s.subject_id for s in members}
                # ---- SNS-7 — a name collision ASKS; it never merges --------
                #
                # ⛔ The engine RAISES the question and cannot resolve it. A
                # name is not an identity (N-10a: recurring subjects key on
                # `subject_id`, never on the rendered name), and no exemplar
                # moves without a human yes about THAT identity (V2-5a). Two
                # cats called the same thing, or one generic class word reused,
                # would otherwise become one subject on a string comparison —
                # in a language the owner chose, which makes the comparison
                # locale-dependent as well as wrong.
                #
                # Gated on `human-confirmed` and nothing else. A `superseded`
                # or `rejected` record holds no name to collide with — three
                # refusals see to that — so widening this to `not is_draft`
                # would raise the question against records that cannot be the
                # other half of it.
                held = sorted(
                    s.subject_id for s in registry.subjects
                    if s.name == unit["name"]
                    and s.status == photo_subjects.STATUS_CONFIRMED
                    and s.subject_id not in member_ids)
                # ⚠️ The other half a name can collide with is a row EARLIER ON
                # THIS PAGE, and `held` cannot see it. `held` reads the
                # registry; the two-pass split means nothing is written until
                # every row has been judged, so the second row of a pair looks
                # at a pack that has not moved and the ask never happens.
                #
                # That is not an edge case, it is the likeliest collision there
                # is. A round answered by naming two fragments of one cluster
                # the same thing is exactly what fragmentation produces, and
                # this step was built expecting collisions in the first real
                # rounds.
                #
                # What missing it costs: `photo_recurrence.subject_folder()`
                # keys on identity (N-10a) but renders `folder_name` off the
                # NAME, so two ids sharing one name are two keys and ONE folder
                # on disk. The registry stays honest and the drive does not —
                # the merge this decision exists to prevent, arriving at the
                # layer the owner actually looks at.
                #
                # ⛔ ONE refusal, not a second one beside it: the owner's
                # mistake is the same mistake and has to read the same way.
                # ⛔ And it must not fire on a row naming SEVERAL members —
                # that is one name over N ids, and `pending` gains it once,
                # after the row is accepted.
                # ---- doc 8 amendment (a) — the one page-local collision that
                # ---- is NOT a question, signed 2026-08-27 ------------------
                #
                # ⛔ MEASURED 20260827, Tier 3 round 1 defect D6: the owner's
                # true answer was one subject over frames that lived partly
                # INSIDE a draft they were splitting and partly in whole drafts
                # beside it, and the two refusals prescribed each other's
                # forbidden form. `partition_subject()` refuses a row that both
                # splits and names ("say it as TWO rows"); this check refused
                # the two rows for sharing a name ("put all of its frames on
                # ONE row"). Following either message exactly landed on the
                # other, and the third door it offered — `distinct` — writes
                # the very duplicate the checkpoint exists to prevent.
                #
                # So the exemption is scoped to exactly the case where the
                # remedy does not exist — `one_row_remedy_exists()` decides it
                # off the same gate that would refuse the merged row, so the
                # two can never prescribe each other's forbidden form again.
                # ⚠️ Wider than the amendment's wording ("a split row and a
                # naming row") by one shape — two split rows on two different
                # parents, which has the same impossible remedy for the same
                # reason. Widened deliberately and recorded in the SPEC, not
                # inherited by accident.
                #
                # ⛔ `held` is NOT exempt and must never be. A name the PACK
                # holds is SNS-7's question about a subject already remembered,
                # and its answer is `same` (SNS-14/SNS-16) or `distinct` — a
                # split on this page says nothing about it.
                page_taken = unit["name"] in pending
                shares_a_split = page_taken and not one_row_remedy_exists(
                    unit["name"], units, skip_subsets)
                collision = bool(held or (page_taken and not shares_a_split))
                if shares_a_split:
                    shared_names.add(unit["name"])
                    if unit.get("distinct"):
                        # ⛔ Never silently dropped — the rule this file states
                        # for `same` with nothing to be armed against. The
                        # token is not REFUSED here because it asks for what
                        # these rows already get: ids that keep their own
                        # records and share a name (F15). What it cannot do is
                        # make them two subjects in a store that has no way to
                        # say so, and the owner who typed it — on the old
                        # refusal's advice — should hear that.
                        notes.append(
                            f"Q{block['n']}: `{DISTINCT_TOKEN}` after "
                            f"{unit['name']!r} changed nothing on this row. "
                            "The rows sharing this name were not a question "
                            "here — they answer one subject across a draft "
                            "you split and the drafts beside it — and either "
                            "way each id keeps its own record under the one "
                            "name.")
                if unit.get("same") and unit.get("distinct"):
                    # Both answers to one question, on one row. ⛔ Neither is
                    # honoured and the row is refused whole: the two are
                    # opposites — one subject or two — and picking the token
                    # that happens to be written last would be the engine
                    # answering the very question SNS-7 exists to hand back.
                    refusals.append(
                        f"Q{block['n']}: this row carries both "
                        f"`{SAME_TOKEN}` and `{DISTINCT_TOKEN}` after the name "
                        f"{unit['name']!r}. Those are the two opposite answers "
                        "to the same question — one subject, or two — so "
                        "nothing was written for this row. Keep the one you "
                        "meant.")
                    continue
                if unit.get("same") and not collision:
                    # An armed token with nothing to be armed against. Said out
                    # loud rather than dropped: an owner who typed `same`
                    # believes a fold happened, and a silently ignored token is
                    # indistinguishable from one that worked.
                    refusals.append(
                        f"Q{block['n']}: `{SAME_TOKEN}` says this subject is "
                        f"one already remembered, but nothing in this pack "
                        f"holds the name {unit['name']!r} — there is no other "
                        "half to fold into. Nothing was written. Check the "
                        "spelling against the remembered section of this page, "
                        f"or drop `{SAME_TOKEN}` and the row names a new "
                        "subject.")
                    continue
                # ---- F13 (iii)(b) — `name: X same subj-NNNN` ---------------
                #
                # The owner says WHICH record holding X these frames are. It
                # must be a confirmed holder of X; anything else is refused in
                # its own words. A right one narrows the question to that one
                # record — nothing else is folded.
                same_as = unit.get("same_as")
                if same_as:
                    chosen = registry.get_literal(same_as)
                    if chosen is None:
                        why = f"there is no {same_as} in this pack"
                    elif same_as in member_ids:
                        why = f"{same_as} is one of this row's own drafts"
                    elif chosen.status != photo_subjects.STATUS_CONFIRMED:
                        why = (f"{same_as} is {chosen.status}, not a subject "
                               "you have named")
                    elif chosen.name != unit["name"]:
                        why = (f"{same_as} is called {chosen.name!r}, not "
                               f"{unit['name']!r}")
                    else:
                        why = None
                    if why:
                        refusals.append(
                            f"Q{block['n']}: `name: {unit['name']} "
                            f"{SAME_TOKEN} {same_as}` — {why}. Nothing was "
                            "written for this row.")
                        continue
                    held = [same_as]
                # ---- ADR 0004 (iv) — a name the owner DECLARED at setup ----
                #
                # The owner already answered SNS-7's question when they said
                # "I have an animal called this", so a plain name whose SOLE
                # holder is that declared record joins it through SNS-16, as
                # `same` would. ⛔ Only the marker `declare_pets()` writes: a
                # same-named record without it still gets the ask, and so does
                # a name held twice, a confirmed member, or an explicit token.
                declared_join = bool(
                    collision and len(held) == 1
                    and not unit.get("same") and not unit.get("distinct")
                    and registry.get_literal(held[0]).record.get(
                        photo_subjects.DECLARED_FLAG)
                    and all(s.status != photo_subjects.STATUS_CONFIRMED
                            for s in members))
                if declared_join:
                    notes.append(
                        f"Q{block['n']}: {unit['name']!r} is the animal you "
                        f"declared at setup ({held[0]}), so these frames join "
                        f"it without `{SAME_TOKEN}`. Withdrawing its name puts "
                        "these drafts back in the question.")
                if collision and (unit.get("same") or declared_join):
                    # ---- SNS-14 — the fold, and the ONLY door into it -------
                    #
                    # ⭐ It arrives through the collision ask by design: the
                    # case always presents as a typed name that is already
                    # taken, so extending SNS-7 needs no second verb and no
                    # second grammar. What `same` adds is the owner's answer to
                    # the question the engine raised — *the same one* — which
                    # is the only place that answer may come from (V2-5a: no
                    # exemplar moves without a human yes about THAT identity).
                    if not held:
                        # The other half is a row on this same page, not a
                        # subject in the pack. Two drafts on one page are not
                        # two remembered subjects — SNS-14 is explicitly the
                        # case SNS-1's `pick:` does not cover — and the answer
                        # is the one SNS-1 already gives.
                        refusals.append(
                            f"Q{block['n']}: `{SAME_TOKEN}` folds two subjects "
                            f"the pack already remembers, and {unit['name']!r} "
                            "is taken here by an earlier row on this same "
                            "page, not by a remembered subject. Two rows of "
                            "one page are not two memories: put all of the "
                            "frames on ONE `pick:` row instead. Nothing was "
                            "written.")
                        continue
                    drafts = [s for s in members
                              if s.status != photo_subjects.STATUS_CONFIRMED]
                    if drafts and len(drafts) != len(members):
                        # ⛔ One row, two verbs. The confirmed members would
                        # fold and the drafts would be promoted, on a single
                        # gesture — and the fold is the half with no reverse.
                        # Refused whole, in the pattern every other mixed row
                        # in this file uses.
                        refusals.append(
                            f"Q{block['n']}: this row names "
                            + ", ".join(f"{s.subject_id} ({s.status})"
                                        for s in members)
                            + f", and `{SAME_TOKEN}` means two different "
                            "things to them: a subject the owner already "
                            "named is FOLDED (SNS-14), and a draft is "
                            "PROMOTED into the remembered subject (SNS-16). "
                            "Nothing was written for this row. Put the drafts "
                            "on one row and the named subject on another, and "
                            "both answers land.")
                        continue
                    if drafts:
                        # ---- SNS-16 — the draft -> confirmed direction ------
                        #
                        # ⭐ Signed 2026-08-20, and it is the direction SNS-1
                        # said had no path: the owner recognises a draft as a
                        # subject the pack already knows. The collision ask's
                        # own instruction — *if it is genuinely the same one,
                        # write `name: X same`* — is what brings it here, and
                        # until this branch existed the engine refused the
                        # thing it had just told the owner to type.
                        closed = [s for s in drafts if not s.is_draft]
                        if closed:
                            # `rejected`, `absorbed` or `superseded`. The way
                            # on is the one SNS-14 already gives for the same
                            # states: put the record back in the question loop
                            # first, and answer it there.
                            refusals.append(
                                f"Q{block['n']}: " + ", ".join(
                                    f"{s.subject_id} ({s.status})"
                                    for s in closed)
                                + " is not an open draft, so it cannot join "
                                f"{', '.join(held)}. Nothing was written for "
                                "this row. Take that decision back first — "
                                "`revive` a rejection, or withdraw the name "
                                "of the subject that absorbed it — and the "
                                "draft it becomes can be answered here.")
                            continue
                        fold = None
                        if len(held) > 1:
                            # ---- F13 (iii)(b) — several records, one name ---
                            #
                            # Amendment (a) leaves one answer over several
                            # records sharing a name, and the owner has now
                            # said these frames are THAT animal. Unless a
                            # holder was named as a DIFFERENT animal
                            # (`distinct`), the holders are folded into one
                            # and the frames join it — the owner is never
                            # asked to rename their pet to fit the data.
                            stamped = distinct_holders(registry, held,
                                                       unit["name"])
                            if stamped:
                                refusals.append(distinct_refusal(
                                    f"Q{block['n']}", unit["name"], held,
                                    stamped, registry, pack.profile))
                                continue
                            why = registry.fold_refusal(held)
                            if why:
                                refusals.append(f"Q{block['n']}: {why}")
                                continue
                            fold = held
                            notes.append(fold_notice(
                                f"Q{block['n']}", unit["name"], held,
                                registry))
                        # LITERAL — the promotion writes onto the record the
                        # name resolves to, and `held` was built from
                        # `human-confirmed` records only. With a fold, that is
                        # the record the fold keeps (its own rule: lowest id).
                        target = registry.get_literal(
                            min(held, key=registry._ordinal))
                        crossed = [s for s in drafts if s.kind and target.kind
                                   and s.kind != target.kind]
                        if crossed:
                            # The same-kind guard every other comparison in
                            # the engine makes, and SNS-14 makes it too: two
                            # kinds are two subjects however close the vectors
                            # sit.
                            refusals.append(
                                f"Q{block['n']}: " + ", ".join(
                                    f"{s.subject_id} ({s.kind})"
                                    for s in crossed)
                                + f" cannot join {target.subject_id}, which is "
                                f"a {target.kind}. Two kinds are two subjects, "
                                "whatever they are called. Nothing was written "
                                "for this row.")
                            continue
                        # ⚠️ A draft answered by this row AND by another
                        # was refused at the top of the loop, on BOTH rows —
                        # a record cannot be `absorbed` bookkeeping and a
                        # confirmed subject at once, and refusing only the
                        # promotion would let the other row take the record
                        # the owner said belongs elsewhere.
                        promotions.append({"target": target, "members": drafts,
                                           "refs": resolved, "unit": unit,
                                           "fold": fold})
                        continue
                    # ⛔ The refusal that stood here is GONE, and both halves
                    # of it were wrong (FINDINGS defects A and B). It refused
                    # every row with a draft member — *"a fold joins two
                    # subjects the owner has each already confirmed, and this
                    # one is not one of them"* — which is the exact row the
                    # SNS-7 collision message instructs the owner to type, and
                    # SNS-16 above is now the path it always needed. Its
                    # offered way on, *"leave these frames unpicked and the
                    # sweep absorbs them by itself"*, could not work at all:
                    # `sweep_absorb()` rides only on ids confirmed in THIS run
                    # and re-presentation promotes nothing, so an
                    # already-confirmed subject is never in the sweep set.
                    # Verified empirically — nothing was absorbed. ⛔ Not an
                    # SNS-15 change: the sweep is correct as signed, and only
                    # the sentence about it was false.
                    fold_ids = [s.subject_id for s in members] + list(held)
                    why = registry.fold_refusal(fold_ids)
                    if why:
                        refusals.append(f"Q{block['n']}: {why}")
                        continue
                    # ⛔ A `same` row PROMOTES NOTHING, and it is the only
                    # `pick:` row in this file that resolves refs and then
                    # promotes none of them. That is SNS-14, not an omission:
                    # the fold concatenates the two exemplar sets DIRECTLY,
                    # and re-offering the picked frames to
                    # `attach_exemplars()` afterwards would re-gate looks a
                    # human yes already blessed — refusing every one whose
                    # work-dir artifacts have since been cleaned away, which
                    # is exactly what the SPEC forbids. The row identifies
                    # WHICH remembered subject the owner means; the evidence
                    # moves through the fold.
                    folds.append({"ids": fold_ids, "unit": unit,
                                  "members": members})
                    continue
                if collision and not unit.get("distinct"):
                    # Where the other half is, and what to do about it. The two
                    # differ in the last clause and only there: a name in the
                    # pack belongs to a subject already remembered, so claiming
                    # it is SNS-14's fold and is typed with `same`; a name on
                    # this page belongs to a row the owner is still typing, so
                    # the answer is simply to type one row instead of two
                    # (SNS-1 — frames from different groups on one `pick:` row
                    # ARE the merge).
                    where = (f"in this pack, by {', '.join(held)}" if held
                             else "by an earlier row on this same page")
                    # ⭐ The way on says what the row WILL DO, and which of the
                    # two it is depends on what this row names. Measured
                    # 2026-08-20 (defect A): this message instructed
                    # `name: X same` and the handler refused it, because the
                    # only reading built was SNS-14's fold and a fold needs
                    # two subjects the owner has each already confirmed. SNS-16
                    # is the other reading and it is now built — but an
                    # instruction that promises an ALIAS to a row that
                    # promotes is the same defect one sentence along: the
                    # owner types it and gets a different thing.
                    joining = held and all(
                        s.status != photo_subjects.STATUS_CONFIRMED
                        for s in members)
                    if joining:
                        way_on = (
                            f"write `name: {unit['name']} {SAME_TOKEN}` and "
                            "these frames JOIN the subject that already holds "
                            f"the name ({', '.join(held)}): it gains them as "
                            "exemplars, so it recognises photographs like them "
                            "by itself from now on, and the draft(s) here stop "
                            "being asked about. Nothing on disk moves, no name "
                            "changes, and withdrawing that subject's name puts "
                            "these drafts back in the question.")
                    elif held:
                        way_on = (
                            f"write `name: {unit['name']} {SAME_TOKEN}` and "
                            "the two are folded into one subject — the earlier "
                            "id keeps the name, the later one stays as an "
                            "alias so folders already written under it still "
                            "resolve, and nothing on disk moves.")
                    else:
                        # ⚠️ Reachable ONLY where this remedy can be typed.
                        # A row that both splits a draft and names another
                        # subject is refused by `partition_subject()`, so on a
                        # page that splits anything the two rows are exempted
                        # above (doc 8 amendment (a)) rather than sent here to
                        # a door that is closed — which is D6, measured.
                        way_on = ("put all of its frames on ONE `pick:` row. "
                                  "One row is one subject, and two rows are "
                                  "two.")
                    refusals.append(name_collision_refusal(
                        f"Q{block['n']}", unit["name"], where,
                        f"`name: {unit['name']} {DISTINCT_TOKEN}`", way_on))
                    continue
                # FIX7 (U7-4) — a near-typo of a name the pack holds is SAID,
                # never refused: two animals may have close names.
                for sid, other, distance in near_names(unit["name"], [
                        (s.subject_id, s.name) for s in registry.subjects
                        if s.name and s.name != unit["name"]
                        and s.status == photo_subjects.STATUS_CONFIRMED
                        and s.subject_id not in member_ids]):
                    warnings.append(near_name_warning(
                        f"Q{block['n']}", unit["name"], other, sid, distance))
                # ⭐ SNS-9 — COUNTED AND SAID, never refused. `{10}` used to
                # refuse the eleventh name right here, at the one place a name
                # is written, on a context cost that does not exist: no
                # remembered subject is ever put in a prompt. A signed "no cap"
                # and a live cap of 10 coexisted for three days because no
                # test asserted the thing that changed, and the sweep below is
                # what would have made it bite — cheaper rounds mean more
                # names.
                #
                # ⚠️ `pending` is the names the rows ACCEPTED SO FAR in this
                # block will add. Nothing is written until every row has been
                # judged, so without it the count would be measured against a
                # pack that has not moved yet.
                #
                # A name already held by one of THIS row's own members is not
                # a new name — that is F15's loop bug, where one animal on two
                # ids was counted twice.
                warn_at = int(registry.defaults.get(
                    "named_subjects_warn_at",
                    photo_subjects.DEFAULT_THRESHOLDS["named_subjects_warn_at"]))
                named = {s.name for s in registry.subjects
                         if s.name and not s.is_draft
                         and s.subject_id not in member_ids} | pending
                if unit["name"] not in named and len(named) + 1 >= warn_at:
                    # A warning and not a refusal, so it goes where warnings go
                    # — it must not flip the exit code, because nothing was
                    # refused and a caller reading rc would learn the opposite
                    # of what happened.
                    warnings.append(
                        f"Q{block['n']}: this pack will hold {len(named) + 1} "
                        f"remembered name(s), past the {warn_at} the engine "
                        "expects to see. Nothing is refused — there is no cap "
                        "on who may be remembered. Worth a look only in case "
                        "clustering is minting names nobody typed; if the "
                        "number is real, raise `named_subjects_warn_at` in "
                        "the registry's `defaults` and it stops being said.")
                row = {"unit": unit, "members": members, "refs": resolved,
                       # F13 (iii)(b): `distinct` typed AS the answer to a
                       # collision — the only thing that writes the stamp.
                       "distinct": bool(collision and unit.get("distinct"))}
                accepted.append(row)
                pending.add(unit["name"])
                named_here.setdefault(unit["name"], []).append(row)

            # ---- amendment (a)'s FIRST guard: the split that never was ------
            #
            # ⛔ `one_row_remedy_exists()` reads the PARSED rows, so a row that
            # was refused in the pass above still counted towards the split it
            # named. With that row gone the parent takes the one-row in-place
            # branch, nothing is partitioned, and the merged row the collision
            # message asks for would have been accepted — so the remedy exists
            # after all and the collision is a real question again. Left
            # unchecked this writes two ids under one name with nothing asked,
            # which `subject_folder()` renders as ONE folder: the merge SNS-7
            # exists to prevent, arriving at the layer the owner looks at.
            #
            # Asked here, on the ACCEPTED rows and before `partition_picks()`,
            # so nothing has been written when the answer turns out to be yes.
            # ⚠️ A DIFFERENT cause from the guard below, which is about a split
            # that was attempted and failed inside the surgery. Two guards, two
            # causes, both said in their own words.
            for name in sorted(shared_names):
                if not one_row_remedy_exists(
                        name, [row["unit"] for row in accepted], skip_subsets):
                    continue
                rows = named_here.pop(name, [])
                shared_names.discard(name)
                dropped = {id(row) for row in rows}
                accepted = [row for row in accepted if id(row) not in dropped]
                refusals.about = sorted({s.subject_id for row in rows
                                         for s in row["members"]})
                refusals.append(
                    f"Q{block['n']}: {name!r} was answered on {len(rows)} "
                    "rows of this page, and the other row that would have "
                    "split the draft they share was refused above. Without it "
                    "nothing here is picked apart, so those frames DO fit on "
                    "one row — and two rows taking one name is then the "
                    "question the engine may not answer for you: two animals "
                    "can share a name. Nothing was written for "
                    f"{name!r}. Put all of its frames on ONE `pick:` row, or "
                    "fix what the refusal above asks for and type the same "
                    "rows again.")

            # ---- SNS-1b item 3 — the partition, before any name is written --
            # B2 — a promotion row whose draft another row (or `skip:`) also
            # claims goes through the partition beside the accepted rows, and
            # comes back answering about the child its own frames minted.
            splitting = [row for row in promotions
                         if any(rows_claiming.get(s.subject_id, 0) > 1
                                or s.subject_id in skip_subsets
                                for s in row["members"])]
            parted, rejected_children = partition_picks(
                registry, block, accepted + splitting, refusals, changes, by,
                path, go=args.go, skip_subsets=skip_subsets,
                frames_on_page=frames_on_page)
            alive_rows = {id(row) for row in parted}
            accepted = [row for row in parted
                        if not any(row is p for p in splitting)]
            promotions = [row for row in promotions
                          if not any(row is p for p in splitting)
                          or id(row) in alive_rows]
            # ---- amendment (a)'s half-applied path, closed deliberately -----
            #
            # ⛔ Two rows sharing one name are ONE answer about ONE subject —
            # that is the whole reason the collision above stood down. A split
            # that dies inside `partition_picks()` kills its own rows
            # (`dead += rows`) and would leave the other half of that name
            # written: the whole drafts confirmed, the frames the split would
            # have carried unnamed, and a subject that is a fraction of what
            # the owner said it was. Refused WHOLE instead, in the pattern
            # every other mixed row in this file uses.
            alive = {id(row) for row in accepted}
            for name in sorted(shared_names):
                rows = named_here.get(name) or []
                if len(rows) < 2 or all(id(row) in alive for row in rows):
                    if len(rows) > 1:
                        # Said out loud on the operator's channel: the page
                        # will show one name on two `human-confirmed` log
                        # lines, and a reader who does not know the amendment
                        # would read that as the duplicate it is not.
                        notes.append(
                            f"Q{block['n']}: {name!r} was answered on "
                            f"{len(rows)} rows — one subject over the draft "
                            "you split and the drafts beside it, which is one "
                            "answer and not two. They share the name and the "
                            "member ids stay their own, exactly as several "
                            "tiles on one row already do.")
                    continue
                dropped = {id(row) for row in rows}
                accepted = [row for row in accepted if id(row) not in dropped]
                refusals.about = sorted({s.subject_id for row in rows
                                         for s in row["members"]})
                refusals.append(
                    f"Q{block['n']}: {name!r} was answered on "
                    f"{len(rows)} rows of this page — one subject spread "
                    "across a draft you were splitting and the drafts beside "
                    "it — and the split above could not be performed. Nothing "
                    f"was written for {name!r} at all: half of it would be a "
                    "subject smaller than the one you described, and no later "
                    "reader could tell that from an answer you meant. Fix "
                    "what the split refusal asks for and type the same rows "
                    "again.")
            for child_id, parent_id in rejected_children:
                # The child the subset `skip:` minted, taking the one answer
                # its parent may not take. It holds no name — it was born a
                # draft seconds ago — so the no-name invariant is met by
                # construction rather than by a check, and its centroid is the
                # one computed from the skipped frames, which is what
                # `rejected_match()` suppresses on across the next dump.
                # LITERAL — a child minted seconds ago by the split above, and
                # the next line writes a status onto it.
                child = registry.get_literal(child_id)
                child.record["status"] = photo_subjects.STATUS_REJECTED
                child.record["rejected"] = {
                    "at": datetime.now().strftime("%Y-%m-%d"), "by": by,
                    "src": f"{path.name} Q{block['n']}"}
                changes.append(f"{child_id} -> rejected")
                if registry.draft_centroid(child_id) is None:
                    warnings.append(
                        f"Q{block['n']}: {child_id} is rejected but holds NO "
                        "draft centroid, so nothing suppresses it on the next "
                        "dump and the same subject will be drafted again under "
                        "a new id.")
                # ⚠️ F15 — the parent's id goes BELOW THE FOLD, on the evidence
                # continuation. `settled_subjects()` reads every id on a
                # maturity line, so naming the parent up here would close its
                # question too — and its question is the one this answer left
                # open on purpose, in the child that kept the unskipped frames.
                log_lines.append(
                    f"| rejected | subject {child_id} — the operator asked "
                    "never to be asked again about the thing in these frames"
                    f"\n  | evidence: {child.record.get('files', 0)} frame(s) "
                    f"split out of the draft {parent_id}, which is superseded"
                    f"\n  | by: {by} | src: {path.name} Q{block['n']}")

            for row in accepted:
                unit, members, resolved = (row["unit"], row["members"],
                                           row["refs"])
                for subject in members:
                    if subject.name and subject.name != unit["name"]:
                        registry.rename(subject.subject_id, unit["name"])
                    else:
                        subject.record["name"] = unit["name"]
                    subject.record["who"] = unit["who"]
                    if row.get("distinct"):
                        subject.record[photo_subjects.DISTINCT_FLAG] = \
                            unit["name"]
                    subject.record["status"] = photo_subjects.STATUS_CONFIRMED
                    subject.record["confirmed_by"] = by
                    # The other of the two answer paths — see the `rejected`
                    # write above.
                    subject.record.pop(photo_subjects.REOPENED_FLAG, None)
                    confirmed_now.append(subject.subject_id)
                    bucket, _record = sync_entity(entities, subject, by)
                    changes.append(f"{subject.subject_id} -> "
                                   f"{unit['who']}/{unit['name']}"
                                   f" ({ENTITIES_NAME} {bucket})")
                    # F14. The answer is only half of what makes the question
                    # stop: without exemplars this subject is unrecognisable
                    # next dump and comes back as a new id nothing has ever
                    # heard of.
                    # ...and it is deferred to --go, because `add_exemplar()`
                    # appends to the memorize audit log at the decision point. A
                    # dry run that promoted would move the pack snapshot, which
                    # is the one thing this file's determinism rule forbids.
                    #
                    # It runs per MEMBER because `attach_exemplars()` is written
                    # as a function of the subject that was just confirmed, and
                    # each member was just confirmed: each one's own looks
                    # become its own recognition evidence, under the same two
                    # gates. A member whose looks are all refused is reported on
                    # its own line — the group answer must not hide which id
                    # came out unrecognisable.
                    if args.go:
                        # ⭐ SNS-1b, and this is the line OA-15 was open on.
                        # `only_refs` is the frames the owner PICKED on this
                        # row, resolved through the `frames:` map — no longer
                        # "every look this subject holds", which promoted the
                        # second animal in the tile along with the first and
                        # then let F14 suppress it forever.
                        #
                        # ⚠️ The count DROPS on a partial pick, and that is the
                        # fix landing rather than a regression: five looks and
                        # two picked frames is two exemplars now, where it was
                        # five before.
                        #
                        # The refs come from the PAGE, never from the record.
                        # `observe_draft_subject()` appends to `contact_sheet`
                        # and to `evidence` whenever a later batch is seen, so
                        # a set re-derived here would include looks that did
                        # not exist when the owner answered.
                        gained, look_notes = attach_exemplars(
                            registry, subject, resolved[subject.subject_id])
                        notes += [f"Q{block['n']}: {note}" for note in look_notes]
                        # N16 — said whatever it gained: the dry run printed
                        # a line here before it could know.
                        changes.append(f"{subject.subject_id} -> {gained} "
                                       "exemplar(s) memorized from the "
                                       "looks behind it")
                        if not subject.exemplars:
                            warnings.append(
                                f"Q{block['n']}: {subject.subject_id} is "
                                "confirmed but holds NO exemplar, so nothing "
                                "recognises it on the next dump and the same "
                                "subject will be drafted again under a new id. "
                                "The notes above and the memorize audit log say "
                                "which look was refused and why.")
                    else:
                        changes.append(
                            f"{subject.subject_id} -> "
                            f"{len(resolved[subject.subject_id])} picked "
                            "frame(s) would be offered to the memorize rule")
                # F15. Every member id goes on the MATURITY line itself, never
                # on an `evidence:` continuation: `settled_subjects()` reads the
                # log one physical line at a time, so an id below the fold is an
                # id whose question comes back next dump.
                files = sum(int(s.record.get("files", 0)) for s in members)
                batches = {b for s in members for b in s.observed_in}
                group_note = (f", {len(members)} member id(s) under one name"
                              if len(members) > 1 else "")
                log_lines.append(
                    f"| human-confirmed | {unit['who']} {unit['name']} "
                    f"({', '.join(s.subject_id for s in members)})\n"
                    f"  | evidence: {files} file(s) across {len(batches)} "
                    f"batch(es), obs_count {sum(s.obs_count for s in members)}, "
                    f"{sum(len(s.exemplars) for s in members)} exemplar(s)"
                    f"{group_note}"
                    f"\n  | by: {by} | src: {path.name} "
                    f"Q{block['n']}")

            # ---- SNS-16 — the promotion, beside the fold -------------------
            #
            # After the ordinary rows for the fold's reason exactly: it moves
            # looks between two records, so a row refused after it had run
            # would leave the owner's answer half applied. Every refusal it
            # can earn was spoken in the pass above.
            for row in promotions:
                refusals.about = [s.subject_id for s in row["members"]]
                target = row["target"]
                if row.get("fold"):
                    # F13 (iii)(b): the holders become ONE record first, so
                    # the picked frames join the record that keeps the name.
                    if not apply_fold(registry, entities, row["fold"],
                                      row["unit"]["name"], row["unit"]["who"],
                                      by, f"{path.name} Q{block['n']}",
                                      f"Q{block['n']}", args.go, report):
                        continue
                    target = registry.get(target.subject_id) or target
                apply_promotion(registry, target, row["members"],
                                row["refs"], by,
                                f"{path.name} Q{block['n']}", f"Q{block['n']}",
                                args.go, report)

            # ---- SNS-14 — the fold, written last ---------------------------
            #
            # AFTER the ordinary rows, for the reason the two-pass split exists
            # at all: a fold empties one record's exemplars and deletes its
            # vectors, so a row refused after it had run would leave the
            # owner's answer half applied across two subjects. Every refusal
            # this row can earn was spoken in the pass above, on a pack that
            # had not moved.
            #
            # The applying and the reporting are `apply_fold()`'s, shared with
            # the `recheck:` row that reaches the same verb — one fold, one set
            # of words, whichever row the owner typed it on.
            for row in folds:
                refusals.about = [s.subject_id for s in row["members"]]
                apply_fold(registry, entities, row["ids"], row["unit"]["name"],
                           row["unit"]["who"], by,
                           f"{path.name} Q{block['n']}", f"Q{block['n']}",
                           args.go, report)

        # ---- SNS-5 / SNS-14 — what a re-presentation row may carry ---------
        #
        # A GESTURE or a NAME, never both. Three gestures, all optional, and
        # the DEFAULT is silence: a row left blank parses to nothing at all, so
        # "still right" reaches no code path and writes nothing. Only two
        # gestures are honoured, and both are REVERSIBLE — `withdraw` is undone
        # by confirming again (the exemplars were kept for exactly that),
        # `revive` by rejecting again. The permanent one is refused, below.
        #
        # ⭐ The NAME is SNS-14's door, and it is the only one there is. The
        # SPEC's sentence is *"renaming A to B's name raises the collision
        # question, and `same` performs the fold at the next confirm"* — and A
        # is a subject the owner has already named, which is exactly the record
        # that never appears on a `pick:` row: `build_questions()` tiles drafts
        # only. Step 7 built the verb, the tombstone, the alias following and
        # four refusals, and every one of them was reachable only from a page
        # this engine cannot render. This is the row that reaches them.
        #
        # ⛔ Nothing here promotes an exemplar — not a gesture, not a rename,
        # not a fold. SNS-6 says re-confirmation promotes only the frames the
        # owner PICKED, and a re-presented frame carries a number and no
        # `frames:` entry, so there is no map for a promotion to travel
        # through. A rename is not new evidence; the fold moves the evidence
        # the two records already held, through `fold_subjects()`, and adds
        # none.
        #
        # ⛔ And nothing here books an id into layer 2. `parse_representations()`
        # is a separate parse from `parse_review()` precisely so a re-presented
        # subject never lands on a `subjects:` line — an id renamed here must
        # not turn up in `asked_before()` and suppress a draft question it is
        # not.
        gestured = set()
        name_rows = []
        shown_on_page = parse_shown(text)
        for row in parse_representations(text):
            # ⛔ Nothing to book: every record on a `recheck:` row is
            # `human-confirmed` or `rejected`, and layer 2 only ever suppresses
            # a record still in `registry.drafts`.
            refusals.about = []
            if row["not_frames"] or row["not_bare"]:
                # Q8-b — `not <frame>`: one photo out of one pet's memory.
                take_out_row(registry, row, shown_on_page, gestured,
                                    refusals, changes, by, path.name, args.go)
                continue
            if row["name"] and row["bare_numbers"]:
                # A20 — a leftover number is never read as part of a name.
                refusals.append(
                    f"`{RECHECK_KEY}:` {row['raw']!r} would rename this subject "
                    f"to {row['name']!r}, which holds a bare number "
                    f"({', '.join(row['bare_numbers'])}). Nothing was applied. "
                    f"To take a photo out of its memory type `{NOT_TOKEN} "
                    f"{row['bare_numbers'][0]}`; to rename it, type the name "
                    "without the number.")
                continue
            if row["name"] and row["gestures"]:
                # ⛔ One row is one answer, and these are two. Refused rather
                # than resolved in either direction: reading the gesture and
                # dropping the name loses what the owner typed, and reading the
                # name and dropping the gesture takes a decision they did not
                # ask for on that row.
                #
                # This is also where a name that CONTAINS a gesture word lands
                # — `revive` is a legal thing to call a cat — so the refusal
                # says so. A bounced name the owner can see beats a name
                # silently read as a withdrawal.
                refusals.append(
                    f"`{RECHECK_KEY}:` {row['raw']!r} carries a name "
                    f"({row['name']!r}) AND a gesture "
                    f"({', '.join(row['gestures'])}) — one row is one answer, "
                    "so nothing was applied. If the name is what you meant and "
                    f"it really contains the word {row['gestures'][0]!r}, this "
                    "row cannot express it: withdraw the name and answer the "
                    "draft it becomes on the next round, where a `name:` row "
                    "reads the whole line as a name.")
                continue
            if len(row["gestures"]) > 1:
                refusals.append(
                    f"`{RECHECK_KEY}:` {row['raw']!r} carries more than one "
                    f"gesture ({', '.join(row['gestures'])}) — a row is one "
                    "gesture, and picking between them would be the engine "
                    "answering for you. Nothing was applied.")
                continue
            if len(row["subject_ids"]) != 1:
                refusals.append(
                    f"`{RECHECK_KEY}:` {row['raw']!r} names "
                    f"{len(row['subject_ids'])} subject(s) — one row is one "
                    "record, and the id is what an answer attaches to. "
                    "Nothing was applied.")
                continue
            subject_id = row["subject_ids"][0]
            # LITERAL — every branch below reads this record's status and then
            # calls a verb that writes to it. A resolving fetch would withdraw
            # the winner's confirmation, or write the winner's name, from a row
            # naming an alias.
            subject = registry.get_literal(subject_id)
            if subject is None:
                refusals.append(f"`{RECHECK_KEY}:` no such subject "
                                f"{subject_id}")
                continue
            if subject_id in gestured:
                # Refused in BOTH modes, and the dry run is the reason. Under
                # `--go` the second row would refuse anyway — the verb reads
                # the status the first row just moved — but a dry run calls no
                # verb, so it would report two changes where `--go` delivers
                # one change and a refusal. A dry run that does not predict
                # `--go` is worth less than no dry run.
                #
                # ⚠️ It counts the NAME rows too, and has to: a rename row and
                # a withdraw row for one id are two answers about one record in
                # one round, and which one survived would depend on the order
                # they were typed in.
                refusals.append(
                    f"`{RECHECK_KEY}:` {subject_id} is on more than one row. "
                    "A record takes one answer per round — the second row "
                    "was not applied, and the first stands.")
                continue
            gestured.add(subject_id)
            if not row["gestures"]:
                # ---- SNS-14's door — a name typed onto a remembered row -----
                if not row["name"]:
                    # An armed token with no name in front of it. Said out loud
                    # rather than dropped, for the reason the `pick:` path says
                    # it: an owner who typed `same` believes a fold happened.
                    refusals.append(
                        f"`{RECHECK_KEY}:` {row['raw']!r} carries "
                        f"`{SAME_TOKEN if row['same'] else DISTINCT_TOKEN}` "
                        "with no name in front of it — both words answer a "
                        "question about a name, and there is none on this row. "
                        "Nothing was applied. Type the name you meant, and the "
                        "word after it.")
                    continue
                name = row["name"]
                if row["same"] and row["distinct"]:
                    refusals.append(
                        f"`{RECHECK_KEY}:` {subject_id} carries both "
                        f"`{SAME_TOKEN}` and `{DISTINCT_TOKEN}` after the name "
                        f"{name!r}. Those are the two opposite answers to the "
                        "same question — one subject, or two — so nothing was "
                        "written for this row. Keep the one you meant.")
                    continue
                # ADR 0004 — judged with every other name row against the END
                # state, by the one rename path the `rename` verb also uses.
                name_rows.append({
                    "subject_id": subject_id, "name": name,
                    "same": row["same"], "distinct": row["distinct"],
                    "door": f"`{RECHECK_KEY}:`",
                    "syntax": (lambda token, sid=subject_id, n=name:
                               f"`{RECHECK_KEY}: {sid} {n} {token}`")})
                continue
            gesture = row["gestures"][0]
            if gesture == GESTURE_REJECT:
                # ⛔ REFUSED OUT LOUD, and it is the promise `cmd_confirm`'s
                # OA-16 refusal made one status along — "step 4 re-presents
                # confirmed subjects, and stop-asking-about-this-one becomes a
                # gesture the owner can make there". This step does not keep
                # it, and says so rather than keeping it badly.
                #
                # ⚠️ Step 5 built the proof this refusal was waiting on and the
                # refusal STANDS, because freshness was only half of it. The
                # pinned-snapshot check at the top of this function now
                # establishes that the page was rendered from the pack as it
                # stands, which was the OA-16 discriminator. What it cannot
                # supply is the other half, which is not about staleness at
                # all: `rejected` may never be written onto a record that
                # still holds a name (three refusals enforce it), and a
                # re-presented subject holds one BY DEFINITION — it is
                # `human-confirmed` or it would not be in that section. So the
                # gesture is withdraw-THEN-reject however fresh the page is,
                # and a row carries one gesture, so it cannot be both at once.
                #
                # ⛔ Do not "fix" this by relaxing the `group_it` skip refusal
                # so the gesture can travel that way instead. Both are the
                # same gate.
                refusals.append(
                    f"`{RECHECK_KEY}:` {subject_id} was asked to be rejected, "
                    "and this round will not write it. Rejection is the one "
                    "decision no later round takes back by itself, and it "
                    "cannot be typed onto a record that still holds a name — "
                    "which every subject in this section does, or it would "
                    "not be listed here as remembered. So it arrives as "
                    "withdraw-then-reject, in two moves, never one. Withdraw "
                    "the name first "
                    f"(`photo_subjects.py review --unconfirm {subject_id} "
                    "--go`), then reject the draft it becomes on the next "
                    "round's `skip:` row.")
                continue
            if gesture == GESTURE_WITHDRAW:
                if subject.status != photo_subjects.STATUS_CONFIRMED:
                    refusals.append(
                        f"`{RECHECK_KEY}:` {subject_id} is {subject.status}, "
                        f"not {photo_subjects.STATUS_CONFIRMED} — there is no "
                        f"confirmation to withdraw. `{GESTURE_REVIVE}` is what "
                        "takes a rejection back.")
                    continue
                was = subject.name
                if args.go:
                    try:
                        result = registry.unconfirm(
                            subject_id, by=by,
                            reason=f"`{RECHECK_KEY}:` on {path.name}")
                    except ValueError as exc:
                        refusals.append(f"`{RECHECK_KEY}:` {exc}")
                        continue
                    withdrawn.append(result)
                    if result.get("released_absorbed"):
                        # SNS-15's reversal, said out loud. The withdrawal
                        # takes back more than the name: every draft the sweep
                        # stopped asking about did so BECAUSE of this yes, and
                        # an owner who is told only about the name would not
                        # know why the next round grew.
                        changes.append(
                            f"{subject_id} -> "
                            f"{len(result['released_absorbed'])} absorbed "
                            "draft(s) are released and are asked about again: "
                            + ", ".join(result["released_absorbed"]))
                    if not result["draft_centroid"]:
                        # The same gap `--unconfirm` and the rejection path
                        # both speak: without a centroid the subject rejoins
                        # the draft pool with nothing to be recognised by, so
                        # the next dump drafts it again under a new id.
                        warnings.append(
                            f"{subject_id} is a draft again but holds NO "
                            "draft centroid, so nothing links it to the same "
                            "subject on the next dump. The withdrawal stands; "
                            "the continuity is what is missing.")
                changes.append(f"{subject_id} -> the name {was!r} is "
                               "withdrawn; the subject is a draft and is "
                               "asked about again")
                continue
            # `revive`, the third gesture. Status is checked here as well as
            # inside the verb, so a dry run refuses what `--go` would refuse
            # rather than promising a change it will not make.
            if subject.status != photo_subjects.STATUS_REJECTED:
                refusals.append(
                    f"`{RECHECK_KEY}:` {subject_id} is {subject.status}, not "
                    f"{photo_subjects.STATUS_REJECTED} — there is no "
                    f"rejection to take back. `{GESTURE_WITHDRAW}` is what "
                    "takes a name back.")
                continue
            if args.go:
                try:
                    revived.append(registry.revive(
                        subject_id, by=by,
                        reason=f"`{RECHECK_KEY}:` on {path.name}"))
                except ValueError as exc:
                    refusals.append(f"`{RECHECK_KEY}:` {exc}")
                    continue
            changes.append(f"{subject_id} -> the rejection is taken back; the "
                           "subject is a draft and is asked about again")
        refusals.about = []
        rename_subjects(registry, entities, name_rows, by,
                        f"`{RECHECK_KEY}:` on {path.name}", args.go, report,
                        pack.profile)

    # ---- SNS-15 — the post-confirm sweep -------------------------------------
    #
    # HERE, and the placement is the decision: after every block is applied and
    # every exemplar attached, before `registry.save()`. That is the one moment
    # in the whole pipeline when the exemplars the owner just created and the
    # drafts that predate them are in the same process — `confirmed_match()`
    # scores incoming clusters only, so without this pass the other thirty
    # draft records of the animal just named come back at every later
    # checkpoint, each one now colliding with the name that was typed.
    #
    # ⚠️ `--go` only, and said out loud rather than skipped quietly. The sweep
    # scores against exemplars that `attach_exemplars()` writes under `--go`;
    # in a dry run they do not exist, so a prediction here would be a
    # measurement of an empty exemplar set reported as "nothing to absorb" —
    # the most flattering wrong answer available. A dry run that cannot predict
    # `--go` says which part it cannot predict.
    if confirmed_now and args.go:
        absorbed = registry.sweep_absorb(
            confirmed_now, by=by,
            reason=f"post-confirm sweep on {review_src}")
        if absorbed:
            # ONE aggregate line, in both channels. Per-draft lines would bury
            # the rows the owner actually answered under bookkeeping they never
            # asked for, and the per-draft detail is in the audit trail.
            into = ", ".join(sorted({row["into"] for row in absorbed}))
            files = sum(row["files"] for row in absorbed)
            changes.append(
                f"sweep: {len(absorbed)} open draft(s) of the same subject "
                f"were absorbed into {into} and stop being asked about "
                f"({files} file(s) affected); no name and no exemplar was "
                "written for any of them, and withdrawing the name releases "
                "them all")
            ids = ", ".join(row["subject_id"] for row in absorbed)
            scores = ", ".join(f"{row['score']:.3f}" for row in absorbed)
            # ⚠️ `absorbed` is deliberately NOT one of `settled_subjects()`'s
            # maturity tokens, so this line records the sweep without closing
            # a single one of those ids in the log layer. That is what keeps
            # the release honest: absorption suppresses on the STATUS alone,
            # and `release_absorbed()` reverses the status, so there is no
            # second layer left holding the question shut after a withdrawal.
            log_lines.append(
                f"| absorbed | {len(absorbed)} draft(s) -> {into} — the "
                "post-confirm sweep recognised drafts already on the books as "
                "the subject just named"
                f"\n  | evidence: {ids}; {files} file(s); scores {scores}"
                f"\n  | by: {by} | src: {review_src}")
    elif confirmed_now:
        notes.append(
            "the post-confirm sweep is not predicted here: it scores the open "
            "drafts against exemplars this run has not written yet, and a dry "
            "run holds none. Re-run with --go and it reports what it absorbed.")

    # ---- doc 4 v4 — a refused row is not booked as asked ---------------------
    #
    # ⛔ OUTSIDE `if changes:`, and that is the whole case: the measured
    # failure was `wrote 0 change(s), 1 refused`, where `registry.save()` never
    # runs. A booking correction that only happened when something else was
    # written would miss every refusal that refused the whole page.
    #
    # Written into the WORK DIR, beside the pages it corrects, never into the
    # pack — a refusal writes nothing to the registry, and a file inside the
    # pack would move the pack id and invalidate the page the owner is still
    # holding an answer for.
    #
    # ⚠️ Only when the page's own NAME says which checkpoint it is. A
    # correction is keyed on the booking it corrects, and `--file some.md`
    # names no checkpoint — falling back to `--checkpoint` (which defaults to
    # 1) would un-book whatever `memory-review_C1.md` legitimately recorded
    # for those ids, including a DEFERRAL, which is the one outcome this
    # change is careful not to disturb. A hand-named page keeps its refusal
    # spoken and books nothing. G6: a batch page's name says which page it is
    # as plainly as a checkpoint's number does, so it books too.
    # ---- G6-6d — names logged on a photo with 2+ animals -------------------
    for block, logged in shared_blocks:
        by_frame = {}
        for _path, name, _draft, number in logged:
            by_frame.setdefault(number, []).append(name)
        for number, names in sorted(by_frame.items()):
            changes.append(f"Q{block['n']} frame {number}: {' + '.join(names)} "
                           "— named, not remembered as a look: 2+ animals")
        # G2 — a draft whose every photo on this page was named that way has
        # nothing left to ask. Booked, and moved nowhere: no join, no split,
        # no exemplar.
        still_claimed = {s for u in block["picks"] for s in u["subject_ids"]}
        for draft_id, numbers in block["frames_by_subject"].items():
            if draft_id in still_claimed or not set(numbers) <= set(by_frame):
                continue
            subject = registry.get_literal(draft_id)
            if subject is None or not subject.is_draft:
                continue
            names = sorted({n for x in numbers for n in by_frame[x]})
            subject.record[SHARED_FRAMES_FLAG] = {
                "at": datetime.now().strftime("%Y-%m-%d"), "by": by,
                "src": f"{path.name} Q{block['n']}", "names": names}
            changes.append(f"{draft_id} -> answered: its photos hold 2+ animals, "
                           f"named {' + '.join(names)}; not asked again")
            log_lines.append(
                f"| human-answered | {draft_id} — photos holding 2+ animals, "
                f"named {' + '.join(names)} on the frames\n  | by: {by} | "
                f"src: {path.name} Q{block['n']}")

    # ---- G6 SNL — a place named on a batch page goes into the pack ---------
    #
    # Through onboarding's own writer (`photo_onboard_page.write_pack`), so a
    # place named mid-run obeys every rule a place named at setup does. AFTER
    # the pinned check: the page was checked against this pack, so the place
    # it showed is recomputed from exactly what it was rendered from.
    places_to_write = None
    if not args.sync and review_src:
        places_to_write = place_answers(workdir, pack, review_src, text,
                                        refusals)
        if places_to_write and not args.go:
            import photo_onboard_page
            plan, refused = photo_onboard_page.pack_updates(
                places_to_write[0], places_to_write[1],
                load_json(pack.dir / photo_profile.PROFILE_NAME, {}) or {},
                load_json(entities_path(pack), {}) or {})
            refusals.about = []
            for line in refused:
                refusals.append(line)
            for _where, key, value in plan:
                if isinstance(value, list):
                    changes.append(f"{key} -> {', '.join(r.get('label') or '(unnamed)' for r in value)}")

    unbooked, at_page = [], page_key(review_src or "")
    if args.go and refusals.ids and not args.sync and at_page is not None:
        unbooked = record_refusals(workdir, at_page, refusals.ids,
                                   src=review_src, by=by)

    for refusal in refusals:
        print(f"  ! {refusal}")
    if unbooked:
        # Said out loud on both channels' behalf: the owner answered, the
        # engine could not apply it, and the one thing they must be able to
        # rely on is that the question comes back.
        print(f"  ~ {len(unbooked)} draft(s) on the refused row(s) are NOT "
              "booked as asked — they come back as questions at the next "
              "round, so the answer above can be typed again: "
              + ", ".join(unbooked))
    for note in notes:
        print(f"  ~ {note}")
    for warning in warnings:
        print(f"  ⚠️  {warning}")
    for change in changes:
        print(f"  {change}")
    if not args.go:
        # FIX7 (U7-3) — the write that names folders, predicted. `--go`
        # records the frames of rows the registry then holds as confirmed; a
        # refused row records nothing, so its frames are left out here.
        would_record = [rel for rel, draft, _ref, _name, _d in picked_frames
                        if draft not in refusals.ids]
        would_record += [rel for rel, _name, draft, _n in shared_logs
                         if draft not in refusals.ids]
        if would_record:
            typed = {}
            for rel, draft, _ref, name, distinct in picked_frames:
                if draft not in refusals.ids:
                    typed.setdefault(rel, []).append((name, distinct))
            added = {rel for rel, _name, draft, _n in shared_logs
                     if draft not in refusals.ids}
            for rel, logged_name, draft, _n in shared_logs:
                if draft not in refusals.ids:
                    typed.setdefault(rel, []).append((logged_name, True))
            import photo_see
            held = photo_see.subjects_held(workdir, list(typed))
            lines, renamed = [], 0
            for rel in sorted(typed, key=lambda r: Path(held.get(r, (r,))[0]).name):
                if rel not in held:
                    continue
                source, ids = held[rel]
                names = list(dict.fromkeys(n for n, _ in typed[rel]))
                now = [names_before.get(i) or i for i in ids]
                add = rel in added or len(ids) > 1 or len(names) > 1
                # U3-1 — a photo that already holds every typed name is
                # unchanged, one name or several: `--go` writes nothing there.
                same = ((len(ids) == 1 and names == [names_before.get(ids[0])]
                         and not any(d for _, d in typed[rel]))
                        or (add and bool(ids) and set(names) <= set(now)))
                renamed += not same
                lines.append("    " + displaced_line(source, now, names,
                                                     add=add, same=same))
            # U3-1 — PHOTOS that take a new name, the unit `--go` reports.
            print(f"  would give {renamed} photo(s) a new name in "
                  "see-labels.json — the name each one's folder takes at "
                  "render, per photo (its name now -> after):")
            for line in lines:
                print(line)
        print(f"dry run — {len(changes)} change(s) would be written, "
              f"{len(refusals)} refused. Re-run with --go.")
        return 1 if refusals else 0

    if changes:
        registry.save()
        entities_path(pack).write_text(
            json.dumps(entities, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        if log_lines:
            append_log(pack, log_lines)
        write_subject_drafts(pack, registry, pack.profile)
    # ⚠️ AFTER the entities write above, not before it. `record_unconfirm()`
    # re-reads `photo-entities.json` from disk to drop the identity the owner
    # took back; this function's own copy was loaded before the withdrawal
    # happened, so writing it second would put the withdrawn record straight
    # back. Both clearing tokens go through the same functions `--unconfirm`
    # and `--revive` use, so the maturity line `settled_subjects()` reads is
    # written in one place — a second, hand-rolled line here is how an id ends
    # up on an `evidence:` continuation where the scan never reaches it (F15).
    if withdrawn:
        record_unconfirm(pack, withdrawn, by=by)
    if revived:
        record_revive(pack, revived, by=by)
    # ---- U-3 — write the decision onto the frames it was about -------------
    #
    # AFTER `registry.save()`, and the ordering is the whole guard: a row the
    # loop refused wrote nothing to the pack, so the check below — does this
    # frame's subject now resolve to a CONFIRMED record carrying the name the
    # owner typed? — is false for it, and nothing is recorded. ⛔ Never a
    # separate list of "rows that succeeded": that would be a second account of
    # what happened, free to disagree with the pack.
    #
    # ⛔ NOTHING IS MATCHED HERE. Only frames the owner personally picked are
    # touched, which is what keeps a stray out of a confirmed subject's folder
    # (A19) — a batch holding none of them correctly gains no `[who]`, and
    # that is the system declining to guess.
    if changes and (picked_frames or shared_logs):
        confirmed = []
        for sample_rel, draft_id, ref, name, _distinct in picked_frames:
            subject = registry.get(draft_id)          # follows a fold (SNS-14)
            if (subject is not None and ref
                    and subject.status == photo_subjects.STATUS_SUPERSEDED):
                subject = split_child_holding(registry, subject, ref)
            # The same gap one verb along: a draft this answer JOINED to a
            # named record (`same`, or a name declared at setup) is left as
            # `absorbed` bookkeeping, and its picked frame belongs to the
            # record that absorbed it. Still gated below on that record being
            # confirmed with the name typed on this row.
            if (subject is not None
                    and subject.status == photo_subjects.STATUS_ABSORBED
                    and subject.record.get("absorbed_by")):
                subject = registry.get(subject.record["absorbed_by"])
            if (subject is not None
                    and subject.status == photo_subjects.STATUS_CONFIRMED
                    and subject.name == name):
                confirmed.append((sample_rel, subject.subject_id))
        # G6-6d — a name logged on a photo with 2+ animals goes to the ONE
        # confirmed subject holding that name after the writes above. None, or
        # two, and nothing is recorded for it: said, never guessed.
        for sample_rel, name, _draft, number in shared_logs:
            holders = [s.subject_id for s in registry.subjects
                       if s.name == name
                       and s.status == photo_subjects.STATUS_CONFIRMED]
            if len(holders) == 1:
                confirmed.append((sample_rel, holders[0]))
            else:
                print(f"  ⚠️  frame {number}: {name!r} is held by "
                      f"{len(holders)} confirmed subject(s), so it was not "
                      "recorded on that photo")
        # Imported HERE, not at module scope: `photo_see` reaches back into
        # this module the same way (`photo_see.py`'s own lazy import inside
        # `memorize_batch`), and one of the two has to stay lazy.
        import photo_see
        if confirmed:
            held = photo_see.subjects_held(workdir, [rel for rel, _ in confirmed])
            recorded = photo_see.record_confirmed_subject_ids(workdir, confirmed)
            # FIX7 (U7-1) — the id each write replaced, kept where a detach
            # reads it. The audit, not the see-label: no schema change, and
            # the audit is outside the pack snapshot.
            for row in recorded.get("replaced") or []:
                registry.audit({"decision": "see-label replaced",
                                "subject_id": row["subject_id"],
                                "replaced": row["replaced"],
                                "path": row["path"], "sample": row["sample"],
                                "workdir": str(workdir), "by": by,
                                "reason": review_src,
                                "at": datetime.now().strftime("%Y-%m-%d")})
            if recorded["written"] or any(rel in held for rel, _ in confirmed):
                # U3-1 — PHOTOS that took a new name, the dry run's unit.
                renamed = len({source for source, _ in recorded["written"]})
                print(f"  gave {renamed} photo(s) a new name in "
                      "see-labels.json — those files can now carry the "
                      "subject's NAME in a plan, instead of its class word. "
                      "Per photo (its name before -> now):")
            # FIX8 F8-1 — which name each write displaced, from the writer's
            # own report: `replaced` is a swap, anything else written is an add.
            new_by_source = {}
            for source, sid in recorded["written"]:
                new_by_source.setdefault(source, []).append(sid)
            swapped = {row["path"] for row in recorded.get("replaced") or []}
            shown = set()
            for rel, sid in confirmed:
                if rel not in held:
                    continue
                source, ids = held[rel]
                if source in new_by_source:
                    new = new_by_source.pop(source)
                    shown.add(source)
                    print("    " + displaced_line(
                        source, [names_before.get(i) or i for i in ids],
                        [subject_name(registry, s) for s in new],
                        add=bool(ids) and source not in swapped))
                elif sid in ids and source not in shown:
                    # U3-1 — every unchanged photo is listed, as the dry run
                    # lists it, a 2-name photo included.
                    shown.add(source)
                    now = [names_before.get(i) or i for i in ids]
                    print("    " + displaced_line(source, now, now, same=True))
            for path in recorded["skipped_multi_subject"]:
                print(f"  ⚠️  {path} names more than one subject, so which one "
                      "you picked cannot be told from the frame — left as it "
                      "was. Nothing about it is guessed.")
            for path in recorded["unresolved"]:
                print(f"  ⚠️  {path} is on the review page but not in this work "
                      "dir's see output — nothing recorded for it.")
            # W2-20b — one line per OTHER work dir, paths quoted. The name
            # itself is already in the registry (saved above); only the
            # see-labels write, which names the folder, was refused.
            name_of = {Path(rel): subject_name(registry, sid)
                       for rel, sid in confirmed}
            elsewhere = {}
            for path in recorded["outside_workdir"]:
                other = Path(path).parent.parent.parent.parent
                names = elsewhere.setdefault(other, [0, []])
                names[0] += 1
                name = name_of.get(Path(path))
                if name and name not in names[1]:
                    names[1].append(name)
            for other, (count, names) in elsewhere.items():
                print(f"  ⛔ {count} picked photo(s) were viewed in another work "
                      f"dir (\"{other}\"), not this one (\"{workdir}\"): the "
                      f"name {' + '.join(names) or '(unnamed)'} is saved in your "
                      "memory, but these photos' folders keep their class word.")
        # ⛔ The limitation, said out loud rather than engineered around. A
        # batch holding none of the picked frames gains nothing, and that is
        # the SAFE direction: widening it by matching is exactly the absorb
        # this design refuses.
        touched = {Path(rel).parent.parent.name for rel, _ in confirmed}
        untouched = [b for b in photo_see.batches_with_labels(workdir)
                     if b not in touched]
        if untouched:
            print("  note: no frame was picked in " + ", ".join(untouched)
                  + " — files there keep their class word, which is the "
                  "engine declining to guess rather than a failure")
    if places_to_write:
        # LAST, after every registry write above: this moves the pack id, and
        # nothing after it re-reads the page.
        import photo_onboard_page
        if photo_onboard_page.write_pack(str(pack.dir), places_to_write[0],
                                         None, coords=places_to_write[1]):
            refusals.about = []
            refusals.append("the place(s) named on this page were not written "
                            "— the reason is above")
            print(f"  ! {refusals[-1]}")
        else:
            # G6-6 — counted, so the closing line agrees with "✅ Written".
            changes.extend(f"place {label} -> the pack"
                           for label in places_to_write[0]["homes"])
    snapshot = pack.snapshot() or {"id": "(none)"}
    print(f"wrote {len(changes)} change(s); pack now {snapshot['id']}")
    return 1 if refusals else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    rv = sub.add_parser("review", help="write the checkpoint's review table")
    rv.add_argument("workdir")
    rv.add_argument("--profile", help="owner pack (else collection.json / "
                                      "PHOTO_PROFILE)")
    rv.add_argument("--checkpoint", type=int, default=None)
    rv.add_argument("--out", help="write the table here instead")
    rv.add_argument("--batch", type=int, default=None,
                    help="G6: write batch N's own page, P-B<NN>.md — the "
                         "drafts observed in it, and a place first seen in it "
                         "to name. Not a round: never charged")
    rv.add_argument("--next-page", action="store_true",
                    help="G6: write the next batch page that is due (needs the "
                         f"index); exits {PAGE_WRITTEN_RC} when one was "
                         f"written, {PAGE_WAITING_RC} when one still waits for "
                         "its confirm and apply-page, 0 when none is due")
    rv.add_argument("--final", action="store_true",
                    help="this is the last checkpoint of the dump — the "
                         "guaranteed SNS round fires here whether or not the "
                         "floor was reached, and is not charged against "
                         "`memory.sns_rounds_per_dump`")
    rv.add_argument("--pre-plan", action="store_true",
                    help="this checkpoint runs before the dump is planned and "
                         "nothing has been copied yet: an ORDINARY round, "
                         "judged on the floor and the budget like any other, "
                         f"but exits {PRE_PLAN_ROUND_FIRED_RC} when a question "
                         "was actually put, so the caller can hold the copy "
                         "until it is answered")
    rv.add_argument("--preview", action="store_true",
                    help="decide exactly as without it and write NOTHING: with "
                         f"--next-page exits {PAGE_WRITTEN_RC}/{PAGE_WAITING_RC}"
                         f"/0 as it would; with --final or --pre-plan exits "
                         f"{PRE_PLAN_ROUND_FIRED_RC} when a round would be put "
                         "to the owner (M1 — what a `finish` dry run reports)")
    rv.set_defaults(func=cmd_review)

    cf = sub.add_parser("confirm", help="parse an edited review table back into "
                                        "the pack")
    cf.add_argument("workdir")
    cf.add_argument("--profile")
    cf.add_argument("--checkpoint", type=int, default=1)
    cf.add_argument("--file", help="the edited table (else "
                                   "<workdir>/memory-review_C<N>.md)")
    cf.add_argument("--page", help="the page by its name, in the work dir: "
                                   "`P-B03` (a batch page) or "
                                   "`memory-review_C2.md`; refused when the "
                                   "file was written under another name")
    cf.add_argument("--sync", action="store_true",
                    help="no table: reconcile confirmed registry subjects into "
                         "photo-entities.json under the same subject_id")
    cf.add_argument("--by", default="Claude User",
                    help="self-declared confirmer, recorded not verified")
    cf.add_argument("--go", action="store_true", help="write the changes")
    cf.set_defaults(func=cmd_confirm)

    rn = sub.add_parser("rename", help="correct a CONFIRMED subject's name "
                                       "(ADR 0004): subj-0001=Name ... — "
                                       "records only, never a folder")
    rn.add_argument("workdir")
    rn.add_argument("pairs", nargs="+", metavar="subj-NNNN=NAME",
                    help="all pairs are judged together, so a swap is one "
                         "command; `=Name same` / `=Name distinct` answer a "
                         "collision as a recheck: row does")
    rn.add_argument("--profile")
    rn.add_argument("--by", default="Claude User",
                    help="self-declared renamer, recorded not verified")
    rn.add_argument("--go", action="store_true", help="write the changes")
    rn.set_defaults(func=cmd_rename)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
