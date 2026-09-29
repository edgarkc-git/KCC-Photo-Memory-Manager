#!/usr/bin/env python3
"""VS-4 exit test 3, on real embeddings — a measurement, not a suite.

`tests/photo_memory_cases.py` proves the dedupe MECHANISM on hand-built
geometry: K synthetic batches, one draft, one question. That is a proof about
the code. It is not a proof that the mechanism survives the geometry of real
photographs, where "the same animal" is a cloud of vectors taken in different
light, at different distances, over a year.

This script asks the second question against a dump that has already shipped,
and prints numbers instead of passing or failing. Like `see_replay.py`, it
cannot run on the frozen fixtures — it needs the VS-1 embedding index, which
is built from real image bytes.

    ./.venv/bin/python3 tests/memorize_replay.py "<work dir>" [--type <class>]...

`--type` is REPEATABLE and OPTIONAL. Omit it and every class the dump ships is
replayed in ONE run, through ONE draft store — which is the only shape that
can produce a dump-level ask count (see *Whole-dump mode*, below). Pass it once
and the run is exactly the single-class slice it always was.

## The oracle substitution — read this before trusting the number

No vision model runs here. The discovery loop's input is normally "the model
looked at this file and said: an unidentified animal". This script substitutes
the dump's OWN SHIPPED CLASSIFICATION for that judgement: in every batch a
human filed under the chosen class, the largest in-batch visual cluster is
offered to the draft store as an unidentified subject of that class.

What that does and does not buy:

  * the batch-level judgement is a HUMAN's, not this script's — it is the
    class the operator actually filed those files under;
  * WHICH CLUSTER inside the batch carries the subject is an assumption. The
    largest one usually does in a subject-driven batch; when it does not, the
    script has offered the draft store a landscape, and the number below is
    pessimistic rather than flattering;
  * so a result of "1 draft" is real evidence. A result of "many" needs
    reading before it is believed: it may be dedupe tau, or it may be that the
    largest cluster was not the subject in some batches. The per-batch
    similarity column below is there to tell those two apart.

## The second substitution — the contact sheet, added 2026-08-19

A draft with no `contact_sheet` is REFUSED a tile (SNS-1b / SNS-12), so a
harness that never attaches one reports zero questions for any number of
drafts, and that zero is an artifact of the harness rather than a property of
the mechanism. It is the most flattering wrong answer this script can give.

So the frames are built here the way `photo_see.memorize_batch()` builds them
(`looks_in()` and its `observe_draft_subject()` call site), out of material a
v1 run already left on local disk:

  * `classify/batch-NN/sample-report.json` → `samples[]`, whose `source` is an
    absolute path string IDENTICAL to the embedding index's keys and the
    manifest's `SourceFile`, so the join is exact and needs no normalising;
  * every cluster member that HAS a sample becomes one `look` carrying
    `path`, `sample`, `vec_ref`, `captured`, `see_report`, `workdir`, `batch`
    and `label`; `seen_on` carries the same frames as
    `classify/batch-NN/samples/<sample>`, which is the string form the record
    stores and `tile_frames()` resolves back.

What this substitution does NOT reproduce, and each one is a real difference:

  * **Provenance is `None`, always.** These thumbnails came from v1's
    `photo_sample.py`. This dump has NO see run — there is no
    `see-report.json` anywhere in it — so NO look here may claim
    `viewed-image:`, and exemplar promotion is therefore out of scope for this
    script. ⛔ Do not create a `see-report.json`, and do not copy one in from
    a trial directory, to get past `photo_evidence.evidence_problems()`: that
    gate opens the file and checks the path is in its `selected` list, so
    supplying one would forge the 2026-07-20 fabrication guard, and an
    exemplar is permanent. The `see_report` path this script writes is used
    only for its PARENT directory (that is all `look_image()` reads), and the
    file it names is deliberately not on disk.
  * **A real see run selects a few thumbnails per batch; v1 sampled its own
    set.** Which files carry a frame here is v1's sampling decision.
  * **`seen_on` carries EVERY sampled member of the cluster**, where the real
    pipeline appends one sample per observation. That changes which frames an
    owner would look at (`contact_sheet` is append-only and truncated to
    `{contact_frames_per_draft}`, so an early batch saturates the sheet). It
    does not change how many questions are asked.
  * **A cluster whose members carry no sample at all** is still offered to the
    draft store and is COUNTED AND PRINTED as frameless. It is a draft the
    engine correctly declines to render, not a question SNS avoided, and the
    two must never be added together.

Nothing is written into the work dir. The draft store is a throwaway pack in a
temp directory, and the run is read-only over the dump — verify with the mtime
check the script prints.

## The unit — say it before quoting it

`f16-group-it` merged after the 2026-08-10 table below was measured, and it
changed what a question IS: `build_questions()` now emits ONE `Group it`
question per `kind`, carrying up to `{drafts_rendered_per_question}` drafts as
numbered tiles. With `--type <one class>` every draft shares one kind, so the
question count collapses to 1 and is NOT comparable to an ask-per-batch
baseline. The owner-decision count is the TILE count; the drafts past the
per-question limit are deferred to a later checkpoint, not skipped. This script
prints all three separately, and a single checkpoint's tiles are not the whole
dump's ask load.

## Whole-dump mode — added 2026-08-21 (SNS build step 8)

Every number this file recorded before today came off ONE shipped class,
because `--type` was `required=True`. That is a slice, and under the per-kind
question shape it is the slice that flatters most: one class is one kind, one
kind is one question, so the question count read 1 **by construction** and the
tile count was one kind's clamp. The measurement OA-13 actually wants — what
the whole dump asks, across every kind at once — had never been run.

Omitting `--type` now replays every class the dump ships. Three properties of
that run are deliberate, and each one is a way it could have been wrong:

  * **One draft store, one registry, for all kinds** — never a scratch pack per
    kind. The rule that two kinds are two subjects however close their vectors
    sit lives in `photo_subjects.observe_draft_subject()`, which skips a draft
    of a different `kind` while scoring dedupe candidates. This script passes
    the batch's own class as `kind` and adds NO filter of its own; splitting
    the store would re-implement the engine's rule from outside and hide it if
    it ever changed.
  * **Batches are replayed in `batches.json` order, never grouped by class.**
    The store dedupes against what it has already seen, so arrival order
    decides which record absorbs which; grouping by kind would replay an order
    no dump has. It is also what keeps the single-class run bit-for-bit what it
    was.
  * **Every shipped class is included, including the catch-all one.** Filtering
    it would be editorialising the measurement. The caveat is stated instead:
    the oracle's "largest cluster carries the subject" assumption is weakest
    there, so those drafts are the likeliest to be landscapes.

⚠️ The whole-dump run exposes a gap it does not fix: **there is no round-level
tile ceiling.** `{drafts_rendered_per_question}` clamps tiles PER KIND, so a
round covering K kinds renders up to 12K tiles and is charged ONE round against
`{sns_rounds_per_dump}` (4). `{tiles_per_round}` is a known-unbuilt parameter;
the run prints the number so the size of the problem is on the record.

## ⛔ What this measures of OA-13, and what it cannot

Exit-test clause **(1)** — one checkpoint over K batches of one kind emits
exactly one grouped question for that kind — is what the run measures, now for
every kind in the dump at once.

Clause **(2)** is out of reach and stays out of reach here. It needs an owner
to ANSWER, and an answer needs a confirm; this script walks the SILENT-OWNER
path only and promotes nothing, because promotion needs `viewed-image:`
provenance and this dump has no see run (see the provenance note above).
⛔ **No number this script prints closes OA-13**, and the whole-dump total is
not the exception.

## ⛔ Measured 2026-08-10 — the mechanism holds, the THRESHOLD does not

First run, on the archive benchmark dump (1,366 embedded files, 93 batches, 59
of them filed under one animal class by hand):

    dedupe tau   draft records   questions at C1 ⚠️ DEAD UNIT
       0.90            53              66
       0.85 (ship)     42              57
       0.80            32              42
       0.75            26              49
       0.70            17              24
       0.65            10              12
       0.60             9              13

⚠️ **The right-hand column is pre-`f16-group-it`**, when one draft was one
question. That merge made a question a per-KIND container of tiles, so this
column and the 2026-08-20 block below are in different units and MUST NOT be
subtracted from each other. The draft column is unchanged by the merge and is
the one that carries across (it reproduces exactly — see below).

**59 batches of one shipped class produced 42 drafts and 57 questions, not
one.** The per-batch similarity column shows why: most batch centroids sit at
0.60-0.85 against the nearest existing draft, i.e. BELOW the shipped 0.85.
Photographs of one animal across a year, in different light and at different
distances, do not land inside one 0.85 cosine ball.

Two things this does and does not establish, and the difference matters:

  * **Established:** centroid-cosine dedupe at the shipped tau does not
    deliver "one subject, one question" on real data, and no tau in the sweep
    does either — at 0.60, which is permissive enough to merge unrelated
    things, 9 drafts remain. The exit test's number is not one threshold away.
  * **Not established:** how many of the 42 are really the same animal. The
    oracle assumes the largest in-batch cluster carries the subject; in a
    batch that is mostly scenery it does not, and that batch contributed a
    landscape draft. The true subject count is also not 1 — this owner's
    shipped notes describe more than one animal in that class.

So: exit test 3 PASSES as a mechanism test (`tests/photo_memory_cases.py`) and
is **UNPROVEN on real data**, with evidence pointing at a real gap rather than
at a tuning value. Closing it needs a run where the vision model actually says
which cluster is a subject, and probably a dedupe signal stronger than one
centroid cosine — exemplar-set similarity, or matching against the confirmed
registry first. Do not turn the tau until it reads 1; that would be tuning the
instrument to the answer, which is the LL-PHO-43 failure.

## Measured 2026-08-20 — with frames, and in the unit the page renders

Same dump, same class, harness now attaching a contact sheet:

    59 batch(es) offered -> 59 cluster(s) -> 42 draft record(s)
    1 offered cluster carried no frame at all (its largest cluster holds no
      sampled file — NOT a join failure; that batch does have samples)
    C1: 1 question, 12 tile(s), 58 frame(s) shown, 0 unresolved
      (the diagnostic asserts its tile set EQUALS the rendered page's — it is
       computed before `cmd_review` writes, because `asked_before()` would
       otherwise book the page's own ids and hand back the NEXT 12 drafts)
    30 draft(s) suppressed: 29 "not rendered at this checkpoint" (the
      {drafts_rendered_per_question} = 12 clamp), 1 "no example photo on disk"
    copy-only: 818 file(s) before, 818 after, 0 modified, 0 added

The tau sweep reproduces the draft column above EXACTLY (53/42/32/26/17/10/9),
which is the validity check on this change: attaching frames altered what the
page can render and nothing about the dedupe geometry. The C1 tile count is 12
at every tau >= 0.70 because it is the clamp, not the tau.

⛔ **Nothing here is comparable to the 59-question ask-per-batch baseline, and
three readings are specifically wrong:**

  * *1 question vs 59* — the unit artifact this file's header warns about;
  * *12 tiles vs 59* — one checkpoint's slice with 29 drafts explicitly
    pending, not a dump total;
  * *42 vs 59* — 42 is the DRAFT count. Turning it into an ask count assumes
    each draft is asked exactly once, which only a multi-checkpoint replay
    could show. The dump-level ask count is NOT MEASURED by this run.

And the deeper limit is not arithmetic: this measures the SILENT-OWNER path
only. Nobody answers, so nothing is ever confirmed, so no subject ever
suppresses a later draft — which is where SNS's benefit is supposed to come
from (`photo_subjects.py`: a subject with no exemplars cannot suppress
anything). ⛔ A miss here is therefore not a finding about the SNS design.
Reaching the answered path needs real provenance, i.e. a vision pass on this
dump, and until then no number off this script closes the exit test.

## Measured 2026-08-21 — the whole dump, every kind, one round

Same dump, no `--type`. All 93 batches, all 7 shipped classes, one draft store:

    93 batch(es) -> 93 cluster(s) -> 75 draft record(s)
    rounds     1 fired, against the soft cap of 4 per dump; it carries 7
               question(s), one per kind — ONE interruption
    tiles      45  (the owner-decision unit)
    deferred   29  drafts past {drafts_rendered_per_question} = 12, asked at a
               LATER checkpoint, not skipped
    frameless  1   cluster the engine correctly declines to render — a FOURTH
               number, never summed with the three above
    copy-only: 818 file(s) before, 818 after, 0 modified, 0 added

Three readings, and only the first is safe:

  * **The largest class's drafts are unchanged by the other six.** It
    contributed 42 drafts, 12 tiles and 29 deferred here, with six other
    classes interleaved into the same store in dump order. Not merely the same
    COUNT as the single-class runs above: the 42 records partition that class's
    batches into exactly the same groups, compared record by record on
    `observed_in` across the two runs' packs. That is the validity check on
    this change — the engine's own kind guard held, and the harness added no
    filter of its own.
  * **7 questions is not 7 interruptions.** All seven ride in one round, which
    is why `rounds` is printed first and separately.
  * **45 tiles is one checkpoint's slice, not the dump's ask total.** 29 drafts
    are explicitly pending and 30 of the 75 were never rendered; the remaining
    ask load can only be read from a multi-checkpoint replay, which this is
    not. ⛔ And 45 is still a SILENT-OWNER number: nothing is confirmed, so no
    subject suppresses a later draft, so the count carries none of the benefit
    SNS is supposed to deliver.

⚠️ The clamp bound only once: of the seven kinds only the largest exceeded 12
drafts. Six kinds rendered every draft they had, so 45 sits far below the 12 x
7 = 84 a round of this shape is allowed to show. The ceiling is missing whether
or not a given dump walks into it.

## One reading of the output that is NOT a defect

`[tile set MATCHES the page]` is meaningful only when a ROUND FIRES. SNS-4 can
withhold the round at a checkpoint — too few newly-seen subjects against
`{new_fss_floor}`, or the dump's round budget spent — and a withheld round
writes no question block at all, while `build_questions()` still returns the
tiles it would have shown. The line then reads `⚠️ DIFFERS FROM the page` with
an empty page list beside a non-empty diagnostic, which is the two counts
correctly disagreeing rather than the silent mis-attribution the check exists
to catch. It predates whole-dump mode and is only easier to reach now, on a
dump with few drafts. Read the `SNS round …: withheld` line first.
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import pack_state as pks  # noqa: E402
import photo_memory as pm  # noqa: E402
import photo_profile  # noqa: E402
import photo_recurrence  # noqa: E402
import photo_see as ps  # noqa: E402
import photo_subjects as psub  # noqa: E402

TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"


def scratch_pack(root, owner=pks.BENCHMARK_OWNER):
    """A pack made from the shipped template and nothing else.

    ⚠️ The owner is `pack_state.BENCHMARK_OWNER`, not a slug spelled out here.
    This run is a cold start by construction, and the cold-start owner has one
    name across the whole test tree — a second spelling would make
    `assert_blank_sheet()` reject the very pack this script builds."""
    pack_dir = Path(root) / owner
    shutil.copytree(TEMPLATE, pack_dir)
    for path in list(pack_dir.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", owner)))
    for name in ("photo-profile.json", "photo-entities.json"):
        p = pack_dir / name
        p.write_text(p.read_text().replace("{{SLUG}}", owner)
                     .replace("{{DISPLAY}}", owner))
    return pack_dir


def batch_dir(workdir, batch):
    return Path(workdir) / "classify" / f"batch-{int(batch):02d}"


def samples_for(workdir, batch):
    """-> {absolute source path: {"sample": basename, "time": str|None}}.

    The v1 sample report is the only record of which files got a thumbnail.
    Its `source` strings are the embedding index's own keys, so the join is a
    dict lookup and not a path-normalising guess."""
    report = batch_dir(workdir, batch) / "sample-report.json"
    if not report.is_file():
        return None
    out = {}
    for entry in json.loads(report.read_text()).get("samples") or []:
        source, sample = entry.get("source"), entry.get("sample")
        if source and sample:
            out[source] = {"sample": sample, "time": entry.get("time") or None}
    return out


def looks_for(workdir, batch, members, index, label):
    """The `looks` a real see run would have attached to this cluster, minus
    the one thing this dump cannot honestly supply.

    Mirrors `photo_see.looks_in()`: one entry per cluster member that HAS a
    sample, keyed by `vec_ref`, carrying the thumbnail it was seen on and the
    dump it was seen in. ⛔ `provenance` is an explicit `None` rather than an
    omitted key — an absent key is what invites a later
    `.get("provenance", photo_evidence.VIEWED)` to default a claim that a
    model looked at something no model opened."""
    picked = samples_for(workdir, batch)
    if picked is None:
        return [], "no sample-report.json for this batch"
    see_report = str(batch_dir(workdir, batch) / "see-report.json")
    resolved = str(Path(workdir).resolve())
    out = []
    for member in sorted(members):
        entry = picked.get(member)
        if not entry or member not in index:
            continue
        out.append({"path": member, "sample": entry["sample"],
                    "provenance": None, "label": label,
                    "vec_ref": index[member][0], "captured": entry["time"],
                    "see_report": see_report, "workdir": resolved,
                    "batch": int(batch), "run_id": None})
    if not out:
        return [], "no cluster member carries a thumbnail"
    return out, None


def sheet_for(batch, looks):
    """The `seen_on` frames, in the string form `observe_draft_subject()`
    stores in `contact_sheet` and `tile_frames()` resolves back."""
    seen, out = set(), []
    for look in looks:
        item = f"classify/batch-{int(batch):02d}/samples/{look['sample']}"
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# The opening words of the `{drafts_rendered_per_question}` suppression
# sentence `build_questions()` writes. Matched as a PREFIX so the rest of the
# sentence — which names the live parameter value — can change without this
# silently counting zero deferred drafts.
DEFERRED_REASON = "not rendered at this checkpoint"
# ⚠️ TWO causes, TWO constants, and never one prefix covering both. The round
# ceiling (2026-08-21) defers for a different reason and has a different
# repair — the next checkpoint or a bigger `{tiles_per_round}`, not a bigger
# question — so its sentence is its own and so is its tally. Folding them
# would report one number for two decisions, which is the habit LL-PHO-48 /
# 54 / 62 were written about; and if this constant were simply missing, the
# round-deferred drafts would count as neither, the identity
# `tiles + deferred + frameless = drafts` would break, and the run would look
# like it had DROPPED them.
ROUND_DEFERRED_REASON = "beyond this round's tile ceiling"


def select_batches(batches, klasses=None):
    """-> (wanted, kinds, absent). Which batches this run replays.

    `klasses` empty or None selects EVERY class the dump ships, which is the
    only selection that can produce a DUMP-LEVEL ask count: `build_questions()`
    emits one question per `kind`, so a run narrowed to one class collapses to
    one question by construction and measures a slice.

    ⚠️ `wanted` stays in **batches.json order**, never grouped by class, and
    that is a correctness property rather than a cosmetic one. The draft store
    dedupes against what it has already seen, so the order clusters are offered
    in decides which record absorbs which — grouping by kind would replay an
    arrival order no dump ever has. It also keeps a single-class run
    bit-for-bit the list the pre-multi-kind filter built.

    A requested class the dump does not ship is returned in `absent` and
    reported, never silently dropped: a typo in a class name would otherwise
    read as "this class contributes nothing", which is a measurement."""
    shipped = []
    for batch in batches:
        kind = batch.get("type")
        if kind and kind not in shipped:
            shipped.append(kind)
    asked = list(dict.fromkeys(klasses)) if klasses else list(shipped)
    kinds = [k for k in asked if k in shipped]
    chosen = set(kinds)
    return ([b for b in batches if b.get("type") in chosen], kinds,
            [k for k in asked if k not in shipped])


def suppressed_lines(text):
    """The reason lines `render_review()` writes into its suppression comment.
    Read from the rendered page rather than from `build_questions()` so the
    count is the one an operator would see."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("<!-- questions suppressed"):
            inside = True
            continue
        if inside:
            if line.strip().startswith("-->"):
                break
            out.append(line.strip())
    return out


def tree_state(workdir):
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in sorted(Path(workdir).rglob("*")) if p.is_file()}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir")
    ap.add_argument("--type", dest="klass", action="append", metavar="CLASS",
                    help="a shipped batch class to treat as one recurring "
                         "subject. REPEATABLE; omit it for every class the "
                         "dump ships, which is the dump-level ask load")
    ap.add_argument("--tau", type=float, default=ps.SEE_TAU)
    ap.add_argument("--dedupe-tau", type=float, default=None,
                    help="override the draft dedupe threshold (pack default "
                         "0.85)")
    ap.add_argument("--drafts-per-question", type=int, default=None,
                    dest="per_question",
                    help="override {drafts_rendered_per_question} (pack "
                         "default 12) — the PER-KIND tile clamp, which binds "
                         "only where it is set BELOW {tiles_per_round}")
    ap.add_argument("--tiles-per-round", type=int, default=None,
                    dest="per_round",
                    help="override {tiles_per_round} (pack default 12) — the "
                         "ROUND ceiling, ranked across every kind on one "
                         "blast-radius scale; this is the bound on what one "
                         "interruption costs")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    before = tree_state(workdir)
    index, identity = ps.load_index(workdir)
    batches = json.loads((workdir / "batches.json").read_text())["batches"]
    asked = list(dict.fromkeys(args.klass or []))
    wanted, kinds, absent = select_batches(batches, asked)
    one = asked[0] if len(asked) == 1 else None
    scope = repr(one) if one is not None else f"{len(kinds)} shipped class(es)"
    print(f"dump {workdir.name}: {len(batches)} batches, {len(wanted)} filed "
          f"as {scope}, {len(index)} embedded files")
    if not wanted:
        sys.exit("no batch in this dump is filed as "
                 + (repr(one) if one is not None
                    else "any of " + ", ".join(repr(k) for k in asked)))
    if absent:
        print("  ⚠️ no batch in this dump is filed as "
              + ", ".join(repr(k) for k in absent)
              + " — requested, contributes nothing")

    tmp = tempfile.mkdtemp(prefix="memorize-replay-")
    pack_dir = scratch_pack(tmp)
    pack = photo_profile.resolve_pack(explicit=pack_dir / "photo-profile.json")
    registry = psub.load(pack=pack)
    if args.dedupe_tau is not None:
        registry.data.setdefault("defaults", {})["draft_dedupe_tau"] = args.dedupe_tau
        registry.defaults["draft_dedupe_tau"] = args.dedupe_tau
    if args.per_question is not None:
        registry.data.setdefault(
            "defaults", {})["drafts_rendered_per_question"] = args.per_question
        registry.defaults["drafts_rendered_per_question"] = args.per_question
    if args.per_round is not None:
        registry.data.setdefault(
            "defaults", {})["tiles_per_round"] = args.per_round
        registry.defaults["tiles_per_round"] = args.per_round
    # EV-9: a replay that does not state the pack it ran under is not
    # admissible evidence, and `benchmark=True` makes pack_state() PROVE the
    # blank sheet rather than assert it in prose. This script builds its pack
    # from the shipped template every run, so a template that ever ships an
    # owner fact has to fail here loudly instead of quietly moving the numbers.
    _state, state_line = pks.pack_state(pack, benchmark=True,
                                        run_type=pks.TIER2_REPLAY)
    print(state_line)
    print(f"blank scratch pack: {len(registry)} subject(s), dedupe tau "
          f"{registry.defaults['draft_dedupe_tau']}\n")

    print(f"{'batch':>6} {'files':>6} {'biggest':>8} {'frames':>7} "
          f"{'-> draft':>10} {'state':>11}  best-similarity-to-existing-draft")
    offered = 0
    frameless = []
    # Per-kind tallies, but ONE registry and one draft store for all of them —
    # the way a dump arrives. ⛔ Never a scratch pack per kind: the engine's
    # own cross-kind rule lives in `observe_draft_subject()`, which skips a
    # draft of a different `kind` when it scores the dedupe candidates
    # (`photo_subjects.py`, "two different species are two subjects however
    # close their vectors sit"). Splitting the store would reproduce that rule
    # from the outside and hide it if it ever changed.
    per_kind = {k: {"batches": 0, "offered": 0, "frameless": 0} for k in kinds}
    for batch in wanted:
        kind = batch.get("type")
        per_kind[kind]["batches"] += 1
        rows = ps.load_rows(workdir, batch)
        paths = [r["SourceFile"] for r in rows
                 if r["SourceFile"] in index
                 and ps.preclassify(r, pack.profile) in ps.SEE_POOL_CLASSES
                 # the same T2/T3 guard the engine applies (A34a)
                 and ps.tier_of(r, pack.profile)[0]
                 not in ps.SEE_POOL_EXCLUDED_TIERS]
        if not paths:
            continue
        shas = [index[p][0] for p in paths]
        X = np.stack([index[p][1] for p in paths]).astype(np.float32)
        labels, _leaders = photo_recurrence.cluster(X, shas, args.tau)
        sizes = {}
        for i, lid in enumerate(labels):
            sizes.setdefault(int(lid), []).append(i)
        biggest = max(sizes.values(), key=lambda m: (len(m), -m[0]))
        centroid = X[biggest].mean(axis=0)
        centroid = centroid / float(np.linalg.norm(centroid))

        best = 0.0
        for draft in registry.drafts:
            # ⚠️ The SAME kind guard `observe_draft_subject()` applies when it
            # scores dedupe candidates, and it has to be here or this column
            # stops meaning what the header says it means. Its job is to tell
            # "tau is too high" apart from "the largest cluster was not the
            # subject" — which needs the closest draft that COULD have
            # absorbed this cluster, not the closest draft in the store. With
            # one class in the store the two were the same set; across kinds
            # they are not, and the column would print a high cosine beside
            # `new` for a neighbour the engine never considered.
            # ⛔ Mirrored from the engine, never a bar of this script's own.
            if kind and draft.kind and draft.kind != kind:
                continue
            other = registry.draft_centroid(draft.subject_id)
            if other is not None:
                best = max(best, float(other @ centroid))
        members = [paths[i] for i in biggest]
        looks, why_frameless = looks_for(workdir, batch["batch"], members,
                                         index, kind)
        seen_on = sheet_for(batch["batch"], looks)
        subject, state = registry.observe_draft_subject(
            centroid, kind=kind, batch=int(batch["batch"]),
            files=len(biggest), dates=[str(batch.get("from"))[:7]],
            identity=identity,
            evidence={"batch": int(batch["batch"]), "unit": workdir.name,
                      "files": len(biggest), "state": None,
                      "looks": looks, "seen": seen_on},
            seen_on=seen_on)
        subject.record["evidence"][-1]["state"] = state
        offered += 1
        per_kind[kind]["offered"] += 1
        if why_frameless:
            per_kind[kind]["frameless"] += 1
            # ⚠️ Counted and named, never dropped: a cluster the harness could
            # put no frame under is a draft the engine correctly declines to
            # render, and adding it to "questions SNS avoided" would credit the
            # mechanism with a gap in the 2020 sampling run.
            frameless.append((int(batch["batch"]), subject.subject_id,
                              why_frameless))
        print(f"{batch['batch']:>6} {len(paths):>6} {len(biggest):>8} "
              f"{len(looks):>7} {subject.subject_id:>10} {state:>11}  "
              f"{best:.4f}")

    registry.save()
    pm.write_subject_drafts(pack, registry, pack.profile)

    print(f"\n{offered} cluster(s) offered from {len(wanted)} batch(es) "
          f"-> {len(registry.drafts)} draft record(s)")
    print(f"{len(frameless)} offered cluster(s) carried no frame at all:")
    for batch_n, sid, why in frameless:
        print(f"  batch {batch_n} -> {sid}: {why}")
    for draft in sorted(registry.drafts,
                        key=lambda s: -int(s.record.get("files", 0))):
        print(f"  {draft.subject_id}: obs_count {draft.obs_count}, "
              f"{len(draft.observed_in)} batch(es), "
              f"{draft.record.get('files', 0)} file(s), "
              f"active {draft.record.get('active')}")

    # the questions a checkpoint would actually ask
    review_dir = Path(tmp) / "review"
    review_dir.mkdir()
    shutil.copy(workdir / "batches.json", review_dir / "batches.json")

    # ⚠️ BEFORE `cmd_review`, and the order is the whole correctness of this
    # diagnostic. `build_questions()` opens with `asked_before(workdir)`, which
    # reads every review file in the dir — so run after the page is written and
    # every id on it is booked into layer 2, the tiles that come back are the
    # NEXT drafts by blast radius, not the ones C1 showed. The count still
    # reads 12, which is exactly why it looks fine. `build_questions()` mutates
    # neither registry nor pack, so this call changes nothing below it, and the
    # tile ids are compared against the rendered page's before anything here is
    # believed.
    tile_questions, _, _over, _held = pm.build_questions(
        registry, review_dir, pack, pack.profile,
        photo_profile.review_messages(pack.profile))
    shown = sum(len(t["frames"]) for q in tile_questions for t in q["tiles"])
    unresolved = sum(t["unresolved"] for q in tile_questions for t in q["tiles"])
    codes = sorted({c for q in tile_questions for t in q["tiles"]
                    for c in t["why_unresolved"]})

    pm.cmd_review(argparse.Namespace(
        workdir=str(review_dir), profile=str(pack_dir / "photo-profile.json"),
        checkpoint=1, out=None))
    page = (review_dir / "memory-review_C1.md").read_text()
    questions = pm.parse_review(page)
    tiles = sum(len(q["subject_ids"]) for q in questions)
    covers = (f"{len(wanted)} batch(es) of {one!r}" if one is not None
              else f"{len(wanted)} batch(es) across {len(kinds)} class(es)")
    print(f"\ncheckpoint C1 renders {len(questions)} question(s) carrying "
          f"{tiles} tile(s), for {covers}")
    if len(kinds) == 1:
        print("  ⚠️ one `Group it` question per KIND — with a single --type "
              "the question count is 1 by construction and is NOT the "
              "ask-per-batch unit. The owner-decision count is the TILE count.")
    else:
        print(f"  ⚠️ one `Group it` question per KIND — {len(questions)} "
              f"question(s) here means {len(questions)} kind(s) had a "
              "renderable draft, NOT that the owner was interrupted that many "
              "times. All of them ride in ONE round. The owner-decision count "
              "is the TILE count.")
    for q in questions:
        print(f"  Q{q['n']}: {q['subject_ids']}")

    # The third layer of "frameless", and the only one neither the page's
    # suppression comment nor `parse_review()` carries: a tile that RENDERED,
    # with some of its sheet dropped by `tile_frames()`. Read straight off
    # `build_questions()` (above, before the page existed) because that is
    # where the codes live — a tile showing 3 of 5 frames looks clean in every
    # other count printed here.
    # ⚠️ Compared PER QUESTION, not as one flat list. With a single kind there
    # was one question and the two were the same comparison; with K questions a
    # flat concatenation can match while the tiles sit under the wrong
    # questions — two kinds swapping their blocks cancels out — and this guard
    # exists precisely because that failure is silent.
    diag_by_q = [[t["subject_id"] for t in q["tiles"]] for q in tile_questions]
    page_by_q = [list(q["subject_ids"]) for q in questions]
    same = diag_by_q == page_by_q
    print(f"frames on the rendered sheets: {shown} shown, {unresolved} "
          f"unresolved{' (' + ', '.join(codes) + ')' if codes else ''}"
          f"  [tile set {'MATCHES' if same else '⚠️ DIFFERS FROM'} the page]")
    if not same:
        # Self-verifying, because the failure mode this guards is silent: a
        # frame count taken off a different tile set has the right shape and
        # the wrong subject.
        print(f"  diagnostic: {diag_by_q}\n  page:       {page_by_q}")

    reasons = suppressed_lines(page)
    print(f"\n{len(reasons)} draft(s) suppressed at C1, by reason:")
    tally = {}
    for line in reasons:
        why = line.split(": ", 1)[-1]
        tally[why] = tally.get(why, 0) + 1
    for why, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>4}  {why}")

    # ------------------------------------------------ the dump-level load ---
    # ⛔ THREE NUMBERS, NEVER ONE (LL-PHO-48 / 54 / 62). Rounds, tiles and
    # deferred measure different things and no single figure stands in for
    # them; frameless is a FOURTH and is never added to any of the three.
    def row_for(kind):
        return per_kind.setdefault(kind or "", {"batches": 0, "offered": 0,
                                                "frameless": 0})

    def kind_of(subject_id):
        subject = registry.get_literal(subject_id)
        return "" if subject is None else (subject.kind or "")

    for draft in registry.drafts:
        row = row_for(draft.kind)
        row["drafts"] = row.get("drafts", 0) + 1
    # ⚠️ Tiles and deferred are counted off the RENDERED PAGE, not off
    # `build_questions()`, and the two disagree exactly when it matters: a
    # checkpoint whose round SNS-4 withholds still builds questions, and a
    # breakdown fed from the builder would show tiles nobody was shown while
    # the total beside it read 0. Same doctrine as `suppressed_lines()` — the
    # count is the one an operator would see.
    for q in questions:
        for sid in q["subject_ids"]:
            row = row_for(kind_of(sid))
            row["tiles"] = row.get("tiles", 0) + 1
    for line in reasons:
        sid, _, why = line.partition(": ")
        # Both causes land in the same per-kind `deferred` column — a kind's
        # row answers "how much of this kind is still waiting" and the cause
        # does not change that — but they are tallied apart as well, and the
        # totals below print the split. A row that showed only one of the two
        # would sum to less than its own drafts.
        if why.startswith(DEFERRED_REASON):
            row = row_for(kind_of(sid))
            row["deferred"] = row.get("deferred", 0) + 1
            row["deferred_q"] = row.get("deferred_q", 0) + 1
        elif why.startswith(ROUND_DEFERRED_REASON):
            row = row_for(kind_of(sid))
            row["deferred"] = row.get("deferred", 0) + 1
            row["deferred_r"] = row.get("deferred_r", 0) + 1

    per_question = int(registry.defaults.get(
        "drafts_rendered_per_question",
        psub.DEFAULT_THRESHOLDS["drafts_rendered_per_question"]))
    per_round = int(registry.defaults.get(
        "tiles_per_round", psub.DEFAULT_THRESHOLDS["tiles_per_round"]))
    cap = int(photo_profile.get(pack.profile, "memory", "sns_rounds_per_dump",
                                default=pm.DEFAULT_SNS_ROUNDS_PER_DUMP))
    fired = pm.rounds_fired(review_dir)
    deferred = sum(row.get("deferred", 0) for row in per_kind.values())
    deferred_q = sum(row.get("deferred_q", 0) for row in per_kind.values())
    deferred_r = sum(row.get("deferred_r", 0) for row in per_kind.values())

    print(f"\nper-kind breakdown ({len(kinds)} class(es), one draft store, "
          f"one registry — the class names are the DUMP's, read from "
          f"batches.json):")
    print(f"  {'batches':>7} {'offered':>7} {'drafts':>6} {'tiles':>5} "
          f"{'deferred':>8} {'frameless':>9}  kind")
    for kind in kinds:
        row = per_kind[kind]
        print(f"  {row['batches']:>7} {row['offered']:>7} "
              f"{row.get('drafts', 0):>6} {row.get('tiles', 0):>5} "
              f"{row.get('deferred', 0):>8} {row['frameless']:>9}  {kind!r}")
    print(f"  {len(wanted):>7} {offered:>7} {len(registry.drafts):>6} "
          f"{tiles:>5} {deferred:>8} {len(frameless):>9}  = whole dump")

    print("\ndump-level ask load at C1 — three numbers, never one:")
    print(f"  rounds     {fired} fired, against the soft cap of {cap} per "
          f"dump; it carries {len(questions)} question(s), one per kind — ONE "
          "interruption")
    print(f"  tiles      {tiles} — the owner-decision unit, against the "
          f"{{tiles_per_round}} ceiling of {per_round}")
    # ⛔ The split is printed, never one figure. Round-deferred and
    # question-deferred are two causes with two repairs, and a reader who
    # cannot tell them apart cannot tell "the round was full" from "one kind
    # was too long" — which is the difference between raising the ceiling and
    # raising the clamp.
    print(f"  deferred   {deferred} draft(s) asked at a LATER checkpoint, not "
          f"skipped: {deferred_r} beyond {{tiles_per_round}} = {per_round} "
          f"(the round was full, ranked across every kind) + {deferred_q} "
          f"past {{drafts_rendered_per_question}} = {per_question} (one "
          "kind's question was full)")
    print(f"  frameless  {len(frameless)} cluster(s) the engine correctly "
          "declines to render — a FOURTH number, never summed with the three "
          "above")
    # The identity, printed so it is checked rather than assumed: every draft
    # record this run built is on the page, waiting for a later checkpoint, or
    # declined for having no frame. If it ever fails to add up, a draft was
    # DROPPED — the one outcome none of the four numbers above may hide.
    accounted = tiles + deferred + len(frameless)
    print(f"  ⇒ rendered + deferred + frameless = {tiles} + {deferred} + "
          f"{len(frameless)} = {accounted} "
          + ("= " if accounted == len(registry.drafts) else "≠ ⚠️ ")
          + f"{len(registry.drafts)} draft record(s) offered")
    if tiles > per_round:
        print(f"\n  ⚠️ ROUND CEILING EXCEEDED: {tiles} tile(s) rendered "
              f"against {{tiles_per_round}} = {per_round}. The cut in "
              "`build_questions()` is above the per-kind split, so this is "
              "unreachable — read it as a defect, not as a measurement.")

    print("\npromotion not attempted: this dump has no see run, so no look "
          "may claim viewed-image:")
    print("  ⛔ SILENT-OWNER PATH ONLY. This measures OA-13 exit-test clause "
          "(1) — one checkpoint over K batches of one kind emits exactly one "
          "grouped question for that kind. It CANNOT measure clause (2), "
          "which needs an owner to answer and a confirm this path never "
          "reaches. No number this script prints closes OA-13.")

    after = tree_state(workdir)
    changed = [p for p in before if before[p] != after.get(p)]
    added = sorted(set(after) - set(before))
    print(f"\ncopy-only check: {len(before)} file(s) in {workdir.name} before, "
          f"{len(after)} after — {len(changed)} modified, {len(added)} added")
    if changed or added:
        print("  ⚠️ " + ", ".join((changed + added)[:5]))
    print(f"scratch pack (delete when done): {tmp}")


if __name__ == "__main__":
    main()
