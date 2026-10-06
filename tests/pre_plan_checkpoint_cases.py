#!/usr/bin/env python3
"""U-2 cases — the naming checkpoint runs BEFORE the folders are written.

A folder name is rendered from the subject REGISTRY at copy time, and
`photo_plan.visual_columns()` already prints a CONFIRMED subject's real name.
So `[who]` reaching a first dump's folders was never a renderer problem — it
was an ORDER problem. The only checkpoint that existed ran at the end of
`finish`, minutes after the files had been copied, and nothing renames a
folder on the drive afterwards.

Measured in UAT01-3: 38 subjects drafted, none ever put to the owner before
the copy, `who` 0/15. The manual recovery named two cats and not one folder
changed.

What is under test here is the CONDUCTOR's half — that the round runs first,
and that a round which actually asked holds the copy until it is answered.
The engine's half (does a round fire, is it charged, what does the page say)
stays in `photo_memory_cases.py` beside the evidence it is decided against,
and the renderer's half is `photo_plan_cases.py`'s A6 block. Two cases below
cross into the renderer on purpose: they are the claim that the fix needs no
renderer change, and the N-4 guard that it had better not get one.

  python3 tests/pre_plan_checkpoint_cases.py [-v]

Exit 0 = pass. Every fixture is built in a temp dir; nothing on a drive is
read, no owner's pack is touched, and no stage subprocess is spawned — the
conductor's `run()` is replaced by a recorder, so what a case asserts is the
command the conductor CHOSE to run.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_evidence  # noqa: E402
import photo_memory  # noqa: E402
import photo_plan  # noqa: E402
import photo_profile  # noqa: E402
import photo_run  # noqa: E402
import photo_subjects  # noqa: E402

TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"
EN = {"language": "English"}
CLASSES = photo_profile.scene_classes(EN)

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


class Args:
    """The conductor's parsed arguments, on the path under test."""

    def __init__(self, workdir, go=True, skip_memory=False, profile=None):
        self.workdir = workdir
        self.go = go
        self.skip_memory = skip_memory
        self.profile = profile
        self.workdir_root = None
        self.force = False
        self.no_vision = False


def make_pack(root, owner="fixture-owner"):
    pack_dir = Path(root) / "photo-memory" / owner
    pack_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE, pack_dir)
    for path in list(pack_dir.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", owner)))
    profile_file = pack_dir / photo_profile.PROFILE_NAME
    profile_file.write_text(
        profile_file.read_text(encoding="utf-8")
        .replace("{{SLUG}}", owner).replace("{{DISPLAY}}", owner),
        encoding="utf-8")
    return pack_dir


def make_dump(root, bind=True, owner="fixture-owner"):
    """The layout photo-init produces. -> (work dir, pack dir or None)."""
    workdir = Path(root) / "Working Files" / "dump-a"
    workdir.mkdir(parents=True)
    (workdir / "batches.json").write_text('{"batches": []}', encoding="utf-8")
    if not bind:
        return workdir, None
    pack_dir = make_pack(root, owner)
    (workdir.parent / "collection.json").write_text(json.dumps({
        "collection": "fixture", "owner": owner,
        "memory_root": str(pack_dir.parent)}), encoding="utf-8")
    return workdir, pack_dir


class Recorder:
    """Stands in for `photo_run.run()`. Records what the conductor asked for
    and hands back the return code the case is about."""

    def __init__(self, rc=0):
        self.rc = rc
        self.calls = []
        self.pythons = {}

    def __call__(self, script, *scr_args, python=None):
        self.calls.append((script, [str(a) for a in scr_args]))
        self.pythons[script] = python
        rc = self.rc.get(script, 0) if isinstance(self.rc, dict) else self.rc
        return subprocess.CompletedProcess(args=[script], returncode=rc)

    @property
    def reviews(self):
        return [c for c in self.calls if c[0] == "photo_memory.py"]


@contextlib.contextmanager
def conductor(rc=0):
    """One process, one pack cache, one recorded `run()`. ⛔ The cache and the
    PHOTO_PROFILE export both survive a call, so a case that inherited either
    would be reading the previous case's owner (see C17)."""
    recorder = Recorder(rc)
    real_run = photo_run.run
    saved_env = os.environ.get(photo_profile.ENV_VAR)
    os.environ.pop(photo_profile.ENV_VAR, None)
    photo_run._pack_cache.clear()
    photo_run.run = recorder
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            yield recorder, buf
    finally:
        photo_run.run = real_run
        photo_run._pack_cache.clear()
        os.environ.pop(photo_profile.ENV_VAR, None)
        if saved_env is not None:
            os.environ[photo_profile.ENV_VAR] = saved_env


def source_of(func_name):
    """The body of one `photo_run` function, as text."""
    src = (SCRIPTS / "photo_run.py").read_text(encoding="utf-8")
    body = src[src.index(f"def {func_name}("):]
    return body[:body.index("\ndef ", 1)]


# ---------------------------------------------------------------------------
# the defect — the round ran after the copy, so a name could never reach a
# folder
# ---------------------------------------------------------------------------

@case
def finish_asks_before_it_copies():
    """REPRODUCTION. ⛔ FAILS on 7e72721, where `cmd_finish`'s only checkpoint
    is the `--final` one at the END, after every plan has been rendered,
    approved and executed. The order IS the defect: a name confirmed after the
    copy names nothing, and `photo_execute.py` contains no rename call by
    design."""
    body = source_of("cmd_finish")
    if "pre_plan_checkpoint(args, workdir)" not in body:
        return False, "cmd_finish never runs a pre-plan checkpoint"
    return (body.index("pre_plan_checkpoint(args, workdir)")
            < body.index("run_one_plan(")), \
        "the checkpoint runs after the first plan"


@case
def plan_asks_before_it_copies():
    """REPRODUCTION, the other entry point. `plan --go` copies one plan's
    batches and had no checkpoint of any kind."""
    body = source_of("cmd_plan")
    if "pre_plan_checkpoint(args, workdir)" not in body:
        return False, "cmd_plan never runs a pre-plan checkpoint"
    return (body.index("pre_plan_checkpoint(args, workdir)")
            < body.index("run_one_plan(")), \
        "the checkpoint runs after the plan"


@case
def a_round_that_asked_holds_the_copy():
    """REPRODUCTION. The point of asking first is that the answer arrives
    first, so a checkpoint that put a question to the owner must stop before
    anything is written — and say how to go on."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp)
        with conductor(rc=photo_run.PRE_PLAN_ROUND_FIRED_RC) as (rec, buf):
            stop = photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
        out = buf.getvalue()
    return (stop is True and "STOPPED BEFORE COPYING" in out
            and "confirm" in out and len(rec.reviews) == 1), \
        f"stop={stop}, reviews={rec.reviews}, out={out[:200]!r}"


@case
def a_round_two_stop_prints_the_page_number_it_asked_for():
    """REPRODUCTION (U5-06). ⛔ FAILS on 5826436, which printed
    `confirm <work dir> --go`: `confirm` defaults to checkpoint 1, so from round
    2 on the paste opened the stale round-1 page and wrote nothing. The number
    printed must be the SAME number the review was told to write, not a second
    guess at it."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp)
        (workdir / "memory-review_C1.md").write_text("round 1\n",
                                                     encoding="utf-8")
        with conductor(rc=photo_run.PRE_PLAN_ROUND_FIRED_RC) as (rec, buf):
            photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
        out = buf.getvalue()
    argv = rec.reviews[0][1] if rec.reviews else []
    asked = (argv[argv.index("--checkpoint") + 1]
             if "--checkpoint" in argv else None)
    printed = f'confirm "{workdir}" --checkpoint {asked} --go'
    return (asked == "2" and printed in out
            and f"memory-review_C{asked}.md" in out), \
        f"asked={asked}, argv={argv}, out={out[:300]!r}"


@case
def the_conductor_numbers_a_page_as_review_does():
    """GUARD. The conductor imports no stage, so it carries its own copy of
    `photo_memory.next_checkpoint()`. Two copies drift; this holds them equal,
    including over names the glob finds and the pattern does not parse — an
    archived page left in the work dir (LL-PHO-94)."""
    seen = []
    with tempfile.TemporaryDirectory() as tmp:
        wd = Path(tmp)
        for names in ([], ["memory-review_C1.md"],
                      ["memory-review_C3.md", "memory-review_C7.bak.md",
                       "memory-review_C9-old.md", "memory-review_Cx.md",
                       # G6-1: a batch page takes no checkpoint number
                       "P-B09.md"]):
            for name in names:
                (wd / name).write_text("", encoding="utf-8")
            seen.append((photo_run.next_checkpoint(wd),
                         photo_memory.next_checkpoint(wd)))
    return seen == [(1, 1), (2, 2), (4, 4)], f"(conductor, review) = {seen}"


@case
def the_pre_plan_round_is_ordinary_and_never_final():
    """⛔ NOT `--final`. The guaranteed end-of-dump round is the one that is
    never charged and always asks; passing it here would spend that guarantee
    before the dump is over and leave the real end of the dump with nothing to
    give. A pre-plan round is judged on the floor and the budget like any
    other."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp)
        with conductor(rc=0) as (rec, _buf):
            photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
    if len(rec.reviews) != 1:
        return False, f"reviews={rec.reviews}"
    _script, argv = rec.reviews[0]
    return ("--pre-plan" in argv and "--final" not in argv
            and argv[0] == "review"), f"argv={argv}"


@case
def a_round_that_did_not_ask_lets_the_copy_go_on():
    """GUARD. Below the floor, or past the budget, nothing was asked and there
    is nothing to wait for."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp)
        with conductor(rc=0) as (rec, buf):
            stop = photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
        out = buf.getvalue()
    return (stop is False and len(rec.reviews) == 1
            and "STOPPED" not in out), f"stop={stop}, out={out[:200]!r}"


@case
def a_failed_round_stops_and_skip_memory_is_the_way_past():
    """GUARD, REVERSED BY FIX6 (U6-21, Lead ruling). This case used to hold
    that a round which could not write a page is a warning, never a stop, so
    a broken pack could not become an unbreakable gate. UAT01-6 showed the
    cost of that posture: a skipped page read like an ordinary stop and the
    names after it were frozen unasked. The gate stays breakable: the stop
    names `--skip-memory`, and with it the round is never run at all."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp)
        code, out, _rec = stage_exit(workdir, 1)
        with conductor(rc=1) as (rec, _buf):
            stop = photo_run.pre_plan_checkpoint(
                Args(str(workdir), skip_memory=True), workdir)
    return (code == photo_run.EXIT_STAGE_FAILED and "--skip-memory" in out
            and stop is False and not rec.reviews), \
        f"code={code} stop={stop} reviews={rec.reviews} out={out[-300:]!r}"


# ---------------------------------------------------------------------------
# the four ways it must NOT fire
# ---------------------------------------------------------------------------

@case
def a_packless_dump_reaches_plan_unchanged():
    """GUARD. ⛔ Every benchmark run is packless, and `finish` has never
    depended on a pack. The checkpoint is skipped — out loud, the same as the
    final round's — and no review is even attempted."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp, bind=False)
        with conductor(rc=photo_run.PRE_PLAN_ROUND_FIRED_RC) as (rec, buf):
            stop = photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
        out = buf.getvalue()
    return (stop is False and rec.calls == []
            and "no owner pack bound" in out), \
        f"stop={stop}, calls={rec.calls}, out={out[:200]!r}"


@case
def a_dry_run_books_no_round():
    """GUARD. `rounds_fired()` counts pages carrying a question block, so a
    dry run that wrote a real page would spend a round the owner never saw —
    the same reason the final round is `--go` only. Since M1 the dry run
    asks the stage with `--preview` — which decides and writes nothing — so it
    can say that `--go` would stop; any other call would be a real round."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp)
        with conductor(rc=photo_run.PRE_PLAN_ROUND_FIRED_RC) as (rec, buf):
            stop = photo_run.pre_plan_checkpoint(
                Args(str(workdir), go=False), workdir)
        out = buf.getvalue()
    return (stop is False and rec.calls
            and all("--preview" in args for _s, args in rec.calls)
            and "only with --go" in out and "would STOP" in out), \
        f"stop={stop}, calls={rec.calls} out={out[-300:]!r}"


@case
def skip_memory_is_the_way_past_it_in_one_run():
    """GUARD. ⛔ Not a gate. An owner who does not want to name anything must
    still reach `plan` in the run they are already in — `[who]` stays empty
    and that is a legal outcome, not a failure."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp)
        with conductor(rc=photo_run.PRE_PLAN_ROUND_FIRED_RC) as (rec, buf):
            stop = photo_run.pre_plan_checkpoint(
                Args(str(workdir), skip_memory=True), workdir)
        out = buf.getvalue()
    return (stop is False and rec.calls == [] and "--skip-memory" in out), \
        f"stop={stop}, calls={rec.calls}"


@case
def both_entry_points_offer_the_way_past_it():
    """A flag that only one of the two copying commands accepts is a gate on
    the other."""
    src = (SCRIPTS / "photo_run.py").read_text(encoding="utf-8")
    return src.count('"--skip-memory"') == 2, \
        f"{src.count(chr(34) + '--skip-memory' + chr(34))} subparser(s)"


# ---------------------------------------------------------------------------
# one case per pack route — ⛔ A42 / LL-PHO-132. A suite that exercises one
# route proves nothing about the others.
# ---------------------------------------------------------------------------

@case
def route_collection_json():
    """The route a real owner is on, and the only one that needs the work dir
    to resolve — so it is the one C17 broke and the one this checkpoint would
    have inherited the break from."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp)
        with conductor(rc=0) as (rec, _buf):
            photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
    return len(rec.reviews) == 1, f"reviews={rec.reviews}"


@case
def route_env_var():
    """$PHOTO_PROFILE — resolves with no work dir at all."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp, bind=False)
        pack_dir = make_pack(tmp)
        with conductor(rc=0) as (rec, _buf):
            os.environ[photo_profile.ENV_VAR] = str(
                pack_dir / photo_profile.PROFILE_NAME)
            photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
    return len(rec.reviews) == 1, f"reviews={rec.reviews}"


@case
def route_explicit_profile():
    """`--profile`, which the conductor threads through as `args.profile`."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp, bind=False)
        pack_dir = make_pack(tmp)
        with conductor(rc=0) as (rec, _buf):
            args = Args(str(workdir),
                        profile=str(pack_dir / photo_profile.PROFILE_NAME))
            photo_run.pre_plan_checkpoint(args, workdir)
    return len(rec.reviews) == 1, f"reviews={rec.reviews}"


@case
def the_checkpoint_does_not_depend_on_the_cwd():
    """⛔ C17 is a prerequisite, not a sibling. A checkpoint resolving its pack
    through `load_pack_cached` inherits C17 verbatim — skipped, silently, at
    exit 0, depending only on which directory the owner ran the command from.
    This is the same cwd-varying arm C17's own suite reproduces, asked of the
    new checkpoint."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp)
        workspace = workdir.parent.parent
        saved = Path.cwd()
        try:
            os.chdir(workspace)
            with conductor(rc=0) as (rec, buf):
                args = Args("dump-a")
                resolved = photo_run.resolve_workdir(args.workdir, args)
                photo_run.pre_plan_checkpoint(args, resolved)
            out = buf.getvalue()
        finally:
            os.chdir(saved)
    return (len(rec.reviews) == 1 and "no owner pack bound" not in out), \
        f"reviews={rec.reviews}, out={out[:200]!r}"


# ---------------------------------------------------------------------------
# the renderer needs no change — and must not get one
# ---------------------------------------------------------------------------

def render_fixture(root, subjects):
    """A pack holding `subjects`, and a work dir holding one see-label that
    points at the first of them. -> (workdir, pack)."""
    pack_dir = make_pack(root)
    reg = pack_dir / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text(encoding="utf-8"))
    data["subjects"] = subjects
    reg.write_text(json.dumps(data), encoding="utf-8")
    workdir = Path(root) / "work"
    batch = workdir / "classify" / "batch-01"
    batch.mkdir(parents=True)
    (batch / "see-labels.json").write_text(json.dumps({"labels": [{
        "path": "/raw/a.jpg", "label": "a cat on a wall",
        "provenance": photo_evidence.VIEWED,
        "subject": {"subject_id": subjects[0]["subject_id"]},
        "subject_provenance": photo_evidence.VIEWED}]}), encoding="utf-8")
    pack = photo_profile.resolve_pack(
        explicit=pack_dir / photo_profile.PROFILE_NAME)
    return workdir, pack


@case
def a_confirmed_subject_names_the_folder_with_no_renderer_change():
    """The claim that makes U-2 a scheduling fix and not a rendering one:
    `visual_columns()` on 7e72721 ALREADY prints a confirmed subject's real
    name. Nothing in `photo_plan.py` is touched by this branch — what changed
    is only that the owner now gets to confirm before this runs."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = render_fixture(tmp, [{
            "subject_id": "subj-0001", "exemplars": [], "name": "Lotus",
            "who": "Lotus", "kind": "cat",
            "status": photo_subjects.STATUS_CONFIRMED}])
        cell = photo_plan.visual_columns(wd, [1], pack.profile, pack)["/raw/a.jpg"]
    return (cell["who"] == "Lotus"
            and not cell["who_provenance"].startswith(photo_evidence.DRAFT)), \
        f"who={cell['who']!r}, prov={cell['who_provenance']!r}"


@case
def an_unconfirmed_subject_still_renders_the_class_word_with_draft():
    """⛔ THE GUARD THAT MATTERS MOST. A fix that let a DRAFT name a folder
    would re-open N-4 — zero-shot never names a folder — and would be worse
    than the defect it replaced: the whole point of asking first is that the
    name in the folder is one the owner said out loud. The draft carries a
    proposed name here on purpose; the cell must still not print it."""
    with tempfile.TemporaryDirectory() as tmp:
        wd, pack = render_fixture(tmp, [{
            "subject_id": "subj-0001", "exemplars": [], "name": "Whiskers",
            "kind": "cat", "status": photo_subjects.STATUS_DRAFT}])
        cell = photo_plan.visual_columns(wd, [1], pack.profile, pack)["/raw/a.jpg"]
    return (cell["who"] != "Whiskers"
            and cell["who_provenance"].startswith(photo_evidence.DRAFT)), \
        f"who={cell['who']!r}, prov={cell['who_provenance']!r}"


# ---------------------------------------------------------------------------
# G6 R3 — on a dump WITH an index, the per-batch pages replace U-2
# ---------------------------------------------------------------------------

def indexed_dump(tmp, pages=()):
    workdir, pack = make_dump(tmp)
    (workdir / photo_run.INDEX_POINTER).write_text(
        json.dumps({"owner": "fixture-owner", "dump_key": "dump-a"}),
        encoding="utf-8")
    for name in pages:
        (workdir / name).write_text("page\n", encoding="utf-8")
    return workdir, pack


@case
def an_indexed_dump_runs_the_batch_pages_instead_of_the_round():
    """⭐ REPRODUCTION (G6 R3). ⛔ FAILS on 2768da1: an indexed dump still ran
    `review --pre-plan`, so the pages and a dump-wide round would both
    interrupt. It asks for the next batch page, and a page written stops the
    copy with the page's NAME and both lines to paste (U5-06)."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = indexed_dump(tmp, pages=("P-B01.md", "P-B03.md"))
        with conductor(rc=photo_run.PAGE_WRITTEN_RC
                       if hasattr(photo_run, "PAGE_WRITTEN_RC") else 11) as (rec, buf):
            stop = photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
        out = buf.getvalue()
    argv = rec.reviews[0][1] if rec.reviews else []
    return (stop is True and "--next-page" in argv and "--pre-plan" not in argv
            and "STOPPED BEFORE COPYING" in out and "P-B03.md" in out
            and f'confirm "{workdir}" --page P-B03 --go' in out
            and f'apply-page "{workdir}" P-B03 --go' in out), \
        f"stop={stop} argv={argv} out={out[-500:]!r}"


@case
def a_page_stop_prints_the_line_that_makes_its_web_page():
    """REPRODUCTION (G8, U5-10). ⛔ FAILS on 8c192c1: the stop named the page
    and the two lines after the answer, but not how the owner gets a page to
    answer, and no SKILL named the renderer."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, pack_dir = indexed_dump(tmp, pages=("P-B03.md",))
        with conductor(rc=photo_run.PAGE_WRITTEN_RC) as (_rec, buf):
            photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
        out = buf.getvalue()
    return ('photo_review_page.py" render' in out
            and f'"{workdir / "P-B03.md"}" --workdir "{workdir}"' in out
            and f'--pack "' in out and Path(pack_dir).name in out), out[-600:]


@case
def a_page_still_waiting_holds_the_copy_and_says_so():
    """REPRODUCTION (G6 R4). ⛔ FAILS on 2768da1. A re-run while the page is
    unanswered stops again, naming the same page."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = indexed_dump(tmp, pages=("P-B02.md",))
        with conductor(rc=12) as (_rec, buf):
            stop = photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
        out = buf.getvalue()
    return (stop is True and "P-B02.md is still waiting" in out
            and "--page P-B02 --go" in out), f"stop={stop} out={out[-300:]!r}"


@case
def no_page_due_lets_the_copy_go_on():
    """GUARD (G6). With no page due the copy goes on, and the round of a dump
    with no index is untouched (the cases above this block)."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = indexed_dump(tmp)
        with conductor(rc=0) as (rec, buf):
            stop = photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
        out = buf.getvalue()
    return (stop is False and len(rec.reviews) == 1 and "STOPPED" not in out), \
        f"stop={stop} out={out[-200:]!r}"


@case
def with_no_page_due_the_agents_views_stop_the_copy():
    """REPRODUCTION (G7, D-I11). ⛔ FAILS on 91ca5e6: with no page due the
    copy went straight on, so the batches after the pages kept their class
    word. Now identify runs, and views wanted stop the copy with the file to
    open and the lines to paste."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = indexed_dump(tmp)
        with conductor(rc={"photo_memory.py": 0, "photo_index.py": 13}) as (rec, buf):
            stop = photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
        out = buf.getvalue()
    asked = [c for c in rec.calls if c[0] == "photo_index.py"]
    return (stop is True and asked and asked[0][1][0] == "identify"
            and "STOPPED BEFORE COPYING" in out and "identify-views.md" in out
            and "--answers" in out and "--go" in out), \
        f"stop={stop} calls={rec.calls} out={out[-400:]!r}"


@case
def no_views_wanted_lets_the_copy_go_on():
    """GUARD (G7). Nothing proposed, or every photo already has a verdict:
    identify returns 0 and the copy goes on."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = indexed_dump(tmp)
        with conductor(rc=0) as (rec, buf):
            stop = photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
    asked = [c for c in rec.calls if c[0] == "photo_index.py"]
    return (stop is False and len(asked) == 1), f"stop={stop} calls={rec.calls}"


@case
def a_page_to_answer_comes_before_the_agents_views():
    """GUARD (G7). The owner's pages train; the agent names only after them,
    so identify never runs while a page is written or waiting."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = indexed_dump(tmp, pages=("P-B01.md",))
        with conductor(rc=11) as (rec, _buf):
            stop = photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
    return (stop is True and not [c for c in rec.calls if c[0] == "photo_index.py"]), \
        f"calls={rec.calls}"


@case
def the_conductor_reads_the_views_exit_code_identify_returns():
    """GUARD (G7). The copy of `photo_index.EXIT_VIEWS_WANTED`."""
    import photo_index
    return (getattr(photo_run, "IDENTIFY_VIEWS_RC", None)
            == photo_index.EXIT_VIEWS_WANTED), \
        f"{getattr(photo_run, 'IDENTIFY_VIEWS_RC', None)}"


@case
def the_conductor_reads_the_page_exit_codes_review_returns():
    """GUARD (G6). The conductor imports no stage, so it carries copies of
    `photo_memory`'s page exit codes; this holds them equal."""
    pairs = [(getattr(photo_run, k, None), getattr(photo_memory, k, None))
             for k in ("PAGE_WRITTEN_RC", "PAGE_WAITING_RC")]
    return all(a is not None and a == b for a, b in pairs), f"{pairs}"


# ---------------------------------------------------------------------------
# FIX6 (U6-21) — a naming stage that did not finish stops the copy
# ---------------------------------------------------------------------------

def stage_exit(workdir, rc, bind=True):
    """-> (exit code or None, stdout, recorder) of one checkpoint call."""
    with conductor(rc=rc) as (rec, buf):
        try:
            photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
            code = None
        except SystemExit as exc:
            code = exc.code
    return code, buf.getvalue(), rec


@case
def a_batch_page_that_fails_stops_the_copy_with_its_own_code():
    """⭐ REPRODUCTION (U6-21). ⛔ FAILS on 0865b82: a page stage that exited 1
    (no CLIP on the system interpreter) printed "Planning continues", skipped
    the agent's views and ran on to the ordinary freeze stop, exit 4."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = indexed_dump(tmp)
        code, out, rec = stage_exit(workdir, {"photo_memory.py": 1})
    return (code == getattr(photo_run, "EXIT_STAGE_FAILED", "missing")
            and "STOPPED BEFORE COPYING" in out and "Planning continues" not in out
            and f'review "{workdir}" --next-page' in out
            and not [c for c in rec.calls if c[0] == "photo_index.py"]), \
        f"code={code} calls={rec.calls} out={out[-400:]!r}"


@case
def identify_that_fails_stops_the_copy_with_its_own_code():
    """REPRODUCTION (U6-21, the same shape one stage later). ⛔ FAILS on
    0865b82."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = indexed_dump(tmp)
        code, out, _rec = stage_exit(workdir, {"photo_memory.py": 0, "photo_index.py": 1})
    return (code == getattr(photo_run, "EXIT_STAGE_FAILED", "missing")
            and "STOPPED BEFORE COPYING" in out and "Planning continues" not in out
            and f'identify "{workdir}" --new-only' in out), f"code={code} out={out[-400:]!r}"


@case
def a_pre_plan_round_that_fails_stops_the_copy_with_its_own_code():
    """REPRODUCTION (U6-21, the dump with no index). ⛔ FAILS on 0865b82."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, _pack = make_dump(tmp)
        code, out, _rec = stage_exit(workdir, 1)
    return (code == getattr(photo_run, "EXIT_STAGE_FAILED", "missing")
            and "STOPPED BEFORE COPYING" in out and "--pre-plan" in out
            and "Planning continues" not in out), f"code={code} out={out[-400:]!r}"


@case
def the_page_stage_runs_under_the_repo_venv_when_this_python_lacks_clip():
    """⭐ REPRODUCTION (U6-21). ⛔ FAILS on 0865b82, where every stage ran with
    `sys.executable`: the SKILL's plain `python3` could not write a place page.
    With a `.venv` present the page stage runs under it; with none, under this
    interpreter."""
    if not hasattr(photo_run, "VENV_PYTHON"):
        return False, "no photo_run.VENV_PYTHON"
    saved = photo_run.VENV_PYTHON
    got = {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            workdir, _pack = indexed_dump(tmp)
            venv = Path(tmp) / "venv-python3"
            venv.write_text("", encoding="utf-8")
            for label, path in (("venv", venv), ("none", Path(tmp) / "absent")):
                photo_run.VENV_PYTHON = path
                _code, _out, rec = stage_exit(workdir, 0)
                got[label] = rec.pythons.get("photo_memory.py")
            want = {"venv": str(venv), "none": sys.executable}
    finally:
        photo_run.VENV_PYTHON = saved
    return got == want, f"got={got} want={want}"


@case
def the_page_stage_prefers_the_venv_even_when_this_python_has_clip():
    """REPRODUCTION (F22/F23). ⛔ FAILS on 5b320fb: a python that HAS open_clip
    kept the page stage, and one without pillow-heif lost every HEIC crop
    (measured on the Mac). The `.venv` is chosen whenever it exists."""
    import importlib.util
    saved = (photo_run.VENV_PYTHON, importlib.util.find_spec)
    real_find = importlib.util.find_spec
    try:
        with tempfile.TemporaryDirectory() as tmp:
            workdir, _pack = indexed_dump(tmp)
            venv = Path(tmp) / "venv-python3"
            venv.write_text("", encoding="utf-8")
            photo_run.VENV_PYTHON = venv
            importlib.util.find_spec = (
                lambda name, *a: object() if name == "open_clip"
                else real_find(name, *a))
            _code, _out, rec = stage_exit(workdir, 0)
            got = rec.pythons.get("photo_memory.py")
    finally:
        photo_run.VENV_PYTHON, importlib.util.find_spec = saved
    return got == str(venv), f"got={got} want={venv}"


@case
def the_pre_plan_round_runs_with_the_pages_python():
    """REPRODUCTION (HIL01 HIL-10, the same defect on a dump with no index).
    ⛔ FAILS on beb57e9: `review --pre-plan`, and the dry run's `--preview` of
    it, ran with whatever python started `finish`, while every batch page ran
    with `page_python()`. A failed round's printed line names the same one."""
    real_page = photo_run.page_python
    photo_run.page_python = lambda: "/the/pages/python"
    got = {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            workdir, _pack = make_dump(tmp)
            with conductor(rc=0) as (rec, _buf):
                photo_run.pre_plan_checkpoint(Args(str(workdir)), workdir)
            got["go"] = rec.pythons.get("photo_memory.py")
            with conductor(rc=0) as (rec, _buf):
                photo_run.preview_stops(Args(str(workdir), go=False), workdir)
            got["preview"] = rec.pythons.get("photo_memory.py")
            code, out, _rec = stage_exit(workdir, 1)
    finally:
        photo_run.page_python = real_page
    want = {"go": "/the/pages/python", "preview": "/the/pages/python"}
    return (got == want and code == photo_run.EXIT_STAGE_FAILED
            and "/the/pages/python" in out), f"got={got} code={code} out={out[-300:]!r}"


@case
def with_no_venv_a_failed_page_says_the_venv_is_missing():
    """GUARD (U6-21). A fresh owner with no `.venv` gets a stop that names it,
    never a crash and never "Planning continues"."""
    saved = photo_run.VENV_PYTHON
    try:
        with tempfile.TemporaryDirectory() as tmp:
            workdir, _pack = indexed_dump(tmp)
            photo_run.VENV_PYTHON = Path(tmp) / "no-venv" / "python3"
            code, out, _rec = stage_exit(workdir, {"photo_memory.py": 1})
    finally:
        photo_run.VENV_PYTHON = saved
    return (code == photo_run.EXIT_STAGE_FAILED and "no repo virtualenv" in out), \
        f"code={code} out={out[-300:]!r}"


@case
def the_stage_failed_code_is_its_own():
    """GUARD. Not a code any other stop or stage already means, and the SKILL's
    exit table lists it."""
    code = getattr(photo_run, "EXIT_STAGE_FAILED", None)
    taken = {0, 1, 2, 3, photo_run.EXIT_STALE_FREEZE, photo_run.PAGE_WRITTEN_RC,
             photo_run.PAGE_WAITING_RC, photo_run.IDENTIFY_VIEWS_RC,
             photo_run.PRE_PLAN_ROUND_FIRED_RC}
    skill = (ROOT / "photo-run" / "SKILL.md").read_text(encoding="utf-8")
    return (code is not None and code not in taken
            and f"| | {code} |" in skill), f"code={code}"


@case
def the_place_page_refusal_offers_no_flag_its_script_lacks():
    """REPRODUCTION (FIX6). ⛔ FAILS on 0865b82: `photo_memory.py review` armed
    the document check and its refusal said "pass --unfiltered-evidence", a
    flag only the onboarding page has. The onboarding page keeps it (GUARD)."""
    import photo_onboard_page as pop
    saved = (pop.LOOKS_LIKE_DOCUMENT, pop.document_filter)

    def no_clip(device=None):
        raise ImportError("No module named 'open_clip'")

    said = {}
    try:
        pop.document_filter = no_clip
        for script in ("photo_memory.py", "photo_onboard_page.py"):
            pop.LOOKS_LIKE_DOCUMENT = None
            try:
                pop.arm_evidence_filter(False, script=script)
                said[script] = None
            except SystemExit as exc:
                said[script] = str(exc.code)
    finally:
        pop.LOOKS_LIKE_DOCUMENT, pop.document_filter = saved
    mem, onb = said.get("photo_memory.py") or "", said.get("photo_onboard_page.py") or ""
    return (".venv" in mem and "--unfiltered-evidence" not in mem
            and "--unfiltered-evidence" in onb), f"{said}"


# ---------------------------------------------------------------------------
# FIX6 (U6-09, U6-10) — the "next:" lines an owner reads
# ---------------------------------------------------------------------------

def status_of(workdir, pack):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        photo_run.print_status(workdir, pack)
    return buf.getvalue()


def pending_dump(tmp, bind=True):
    workdir, _pack = make_dump(tmp, bind=bind)
    (workdir / "batches.json").write_text(json.dumps({"batches": [
        {"batch": 1, "from": "2029-01-01", "to": "2029-01-01", "days": 1,
         "files": 1, "status": "pending", "label": "day out", "flags": []}]}),
        encoding="utf-8")
    saved = os.environ.pop(photo_profile.ENV_VAR, None)
    try:
        pack = photo_profile.resolve_pack(workdir=workdir) if bind else None
    finally:
        if saved is not None:
            os.environ[photo_profile.ENV_VAR] = saved
    return workdir, pack


@case
def an_owners_first_next_step_is_the_index_not_classify():
    """REPRODUCTION (FIX6, U6-09). ⛔ FAILS on 0865b82: `cluster` runs before
    `index init`, so on an owner's dump its "next:" said CLASSIFY with
    photo_classify_set.py, the route photo-run says does not exist. GUARD half:
    a dump with no pack keeps the classify route."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir, pack = pending_dump(tmp)
        owner = status_of(workdir, pack)
    with tempfile.TemporaryDirectory() as tmp:
        workdir2, _none = pending_dump(tmp, bind=False)
        bare = status_of(workdir2, None)
    return (f'photo_index.py" init "{workdir}"' in owner and "CLASSIFY" not in owner
            and "CLASSIFY" in bare), f"owner={owner[-300:]!r} bare={bare[-200:]!r}"


@case
def a_printed_venv_line_works_from_the_workspace():
    """REPRODUCTION (FIX6, U6-10). ⛔ FAILS on 0865b82: every printed vision
    line began `./.venv/bin/python3`, which resolves only from the repo, while
    photo-run says to run from the workspace. No script prints the relative
    form, and the two SKILLs that showed it write `<repo>/.venv/bin/python3`."""
    import photo_platform
    rel = "./.venv/bin/python3"
    scripts = [p.name for p in SCRIPTS.glob("*.py")
               if rel in p.read_text(encoding="utf-8")]
    skills = [s for s in ("photo-run", "photo-see")
              if rel in (ROOT / s / "SKILL.md").read_text(encoding="utf-8")]
    return (not scripts and not skills
            and str(photo_platform.venv_python(ROOT)) == str(photo_run.VENV_PYTHON)), \
        f"scripts={scripts} skills={skills}"


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

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} pre-plan checkpoint "
          "cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
