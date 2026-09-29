#!/usr/bin/env python3
"""Cases for the `held` batch state (D-28).

A held batch is one a human deliberately stopped on an unanswered question.
Before this state existed the hold had no durable representation at all: it
was left as `pending` — the same value an unstarted batch carries — with no
reason, no time and no operator, and `photo_run.py status` then printed the
command to classify it. The tool's own guidance pointed at the trap the hold
existed to prevent.

⛔ A hold is NOT a sixth pipeline stage. A batch is held AT whatever stage it
reached, so `stage` still reports progress and `status` reports the hold. What
the state changes is what the conductor PROPOSES.

Three of these are reproductions, and each fails on the unfixed code for its
own reason — the state is unrepresentable, the ledger cannot carry it, and
`next:` names the batch anyway. The rest are guards.

Every fixture is synthetic: invented dump names, invented batch dates, and a
reason string that is deliberately about nothing (`waiting on an answer`).

  python3 tests/held_state_cases.py [-v]

Exit 0 = pass. No network, no drive, no pack.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
RUN = str(SCRIPTS / "photo_run.py")
SET = str(SCRIPTS / "photo_classify_set.py")

VERBOSE = False
REASON = "waiting on an answer from the owner"


def log(msg):
    if VERBOSE:
        print(f"      {msg}")


def make_workdir(tmp, statuses=("pending", "pending")):
    """A work dir holding only batches.json — which is all `status` reads."""
    workdir = Path(tmp) / "202401__"
    workdir.mkdir(parents=True)
    batches = [{"batch": i + 1, "from": "2024-01-01", "to": "2024-01-02",
                "status": st, "files": 10, "flags": []}
               for i, st in enumerate(statuses)]
    (workdir / "batches.json").write_text(json.dumps(
        {"source": "/nowhere/202401__", "main_files": 20,
         "generated_at": "2024-01-03 09:00", "batches": batches}))
    return workdir


def status(workdir, *extra):
    got = subprocess.run([sys.executable, RUN, "status", str(workdir), *extra],
                         capture_output=True, text=True, cwd=str(workdir.parent))
    assert got.returncode == 0, got.stderr
    return got.stdout


def two_plans(tmp):
    """-> (workdir, root, elsewhere): plan 1 under the collection's dest_root,
    plan 2 under another sorted root."""
    workdir = make_workdir(tmp)
    root = Path(tmp) / "sorted"
    elsewhere = Path(tmp) / "other-sorted"
    # No owner bound: `status` reads dest_root off the collection, and this
    # suite has no pack (a bound owner with no pack is a different refusal).
    (workdir.parent / "collection.json").write_text(json.dumps(
        {"collection": "TESTBOX", "dest_root": str(root)}))
    (workdir / "plans.json").write_text(json.dumps({"plans": [
        {"plan": 1, "batches": [1], "files": 10,
         "dest": {"mode": "new", "path": str(root / "20240101_Here")}},
        {"plan": 2, "batches": [2], "files": 10,
         "dest": {"mode": "new", "path": str(elsewhere / "20240102_There")}}]}))
    return workdir, root, elsewhere


def case_status_shows_plan_paths_against_dest_root(tmp):
    """FIX7 (F2) REPRODUCTION, behind `--paths` since FIX8 F8-5. `status`
    printed every plan's full destination path and said nothing when
    plans.json pointed at another sorted root."""
    workdir, root, elsewhere = two_plans(tmp)
    said = status(workdir, "--paths")
    assert "<dest_root>/20240101_Here" in said, said
    assert str(root / "20240101_Here") not in said, said
    assert "P2 point outside this collection's dest_root" in said, said
    assert str(elsewhere / "20240102_There") in said, said
    log("plan paths are shown against dest_root, and the stray one is flagged")


def case_status_hides_destination_names_by_default(tmp):
    """FIX8 F8-5 REPRODUCTION (UAT01-7 F2, UAT01-8 F2). With --paths only as
    FIX7 left it, a tester told not to see the destination could not use
    `status` at all: the header, every plan row and the stray-plan warning
    each named a destination. The owner decided: hidden by default."""
    workdir, root, elsewhere = two_plans(tmp)
    said = status(workdir)
    for leak in (str(root), str(elsewhere), "20240101_Here", "20240102_There"):
        assert leak not in said, (leak, said)
    assert "dest_root: set" in said, said
    assert "P2 point outside this collection's dest_root" in said, said
    assert "(status --paths shows where)" in said, said
    log("no destination named without --paths; the stray plan still flagged")


def case_the_tail_of_other_commands_names_no_destination(tmp):
    """REPRODUCTION (F8-5). `prep`, `cluster` and `finish` end with the same status
    block and have no --paths: they never print one."""
    workdir, root, _elsewhere = two_plans(tmp)
    sys.path.insert(0, str(Path(RUN).parent))
    import contextlib
    import io
    import photo_run
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        photo_run.print_status(workdir)
    assert str(root) not in buf.getvalue() and "20240101_Here" not in buf.getvalue(), \
        buf.getvalue()


def hold(workdir, batch=1, reason=REASON, extra=()):
    return subprocess.run(
        [sys.executable, SET, str(workdir), "--batch", str(batch),
         "--status", "held", "--reason", reason, *extra],
        capture_output=True, text=True)


def batch_record(workdir, batch=1):
    data = json.loads((workdir / "batches.json").read_text())
    return next(b for b in data["batches"] if b["batch"] == batch)


# ---- reproductions --------------------------------------------------------

def case_held_is_an_accepted_status(tmp):
    """REPRODUCTION. On the unfixed code `held` is not in STATUSES, so the
    state cannot be recorded at all — the operator's only option is to leave
    the batch `pending`, which is the defect."""
    workdir = make_workdir(tmp)
    got = hold(workdir)
    assert got.returncode == 0, got.stderr
    assert batch_record(workdir)["status"] == "held", batch_record(workdir)
    log("a batch can be recorded as held")


def case_next_never_proposes_a_held_batch(tmp):
    """REPRODUCTION. The heart of D-28: `next:` handed the operator the command
    to classify the batch somebody stopped on purpose. Batch 1 is held, batch 2
    is live — the live one must still be proposed, so this cannot be passed by
    printing nothing."""
    workdir = make_workdir(tmp, statuses=("held", "pending"))
    data = json.loads((workdir / "batches.json").read_text())
    data["batches"][0].update(held_reason=REASON, held_at="2024-01-03 10:00",
                              held_by="Someone")
    (workdir / "batches.json").write_text(json.dumps(data))

    out = status(workdir)
    after = out.split("next:", 1)[1]
    assert "held (1)" in out, out
    # the live batch is still proposed...
    assert "CLASSIFY" in after, after
    # ...and the held one is named only as held, never as an action
    assert "(batches: 1" not in after and "batches: 1," not in after, after
    assert "1 batch(es) held" in after, after
    log("next: proposes the live batch and refuses to propose the held one")


def case_the_ledger_carries_the_hold(tmp):
    """REPRODUCTION. status.json is what a later session or a scheduled run
    actually reads. A hold that lives only in a console print is not durable."""
    workdir = make_workdir(tmp)
    assert hold(workdir).returncode == 0
    status(workdir)
    ledger = json.loads((workdir / "status.json").read_text())
    held = next(b for b in ledger["batches"] if b["batch"] == 1)
    assert held["status"] == "held", held
    assert held["held_reason"] == REASON, held
    assert held["held_at"], held
    live = next(b for b in ledger["batches"] if b["batch"] == 2)
    assert "held_reason" not in live, live
    log("status.json carries reason/when/who, and only on the held batch")


# ---- guards ---------------------------------------------------------------

def case_a_hold_without_a_reason_is_refused(tmp):
    """A hold nobody can read is the defect wearing a different status name."""
    workdir = make_workdir(tmp)
    got = subprocess.run([sys.executable, SET, str(workdir), "--batch", "1",
                          "--status", "held"], capture_output=True, text=True)
    assert got.returncode != 0, got.stdout
    assert "--reason" in got.stderr, got.stderr
    blank = hold(workdir, reason="   ")
    assert blank.returncode != 0, blank.stdout
    assert batch_record(workdir)["status"] == "pending", batch_record(workdir)
    log("a hold with no reason, or a blank one, is refused")


def case_a_reason_without_a_hold_is_refused(tmp):
    """`--reason` is the hold's field; a classification note is `--note`."""
    workdir = make_workdir(tmp)
    got = subprocess.run([sys.executable, SET, str(workdir), "--batch", "1",
                          "--status", "classified", "--reason", REASON],
                         capture_output=True, text=True)
    assert got.returncode != 0, got.stdout
    # ⛔ The specific refusal, not merely a non-zero exit: on the code before
    # `--reason` existed argparse rejected it as an unknown flag and printed a
    # usage line that mentions `--note` all by itself, so a looser assert here
    # passed against the unfixed engine and guarded nothing.
    assert "belongs to --status held" in got.stderr, got.stderr
    log("--reason is refused on any status but held")


def case_releasing_a_hold_clears_it(tmp):
    """A reason that outlives its answer would let `status` print a stale hold
    beside a batch that is moving again."""
    workdir = make_workdir(tmp)
    assert hold(workdir).returncode == 0
    got = subprocess.run([sys.executable, SET, str(workdir), "--batch", "1",
                          "--status", "classified"],
                         capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
    record = batch_record(workdir)
    assert record["status"] == "classified", record
    for key in ("held_reason", "held_at", "held_by"):
        assert key not in record, record
    released = status(workdir)
    assert "held (" not in released, released
    assert "batch(es) held" not in released, released
    log("releasing a hold clears reason/when/who")


def case_a_hold_is_not_a_stage(tmp):
    """A batch is held AT whatever stage it reached. If `held` were treated as
    a stage, the ledger would lose the batch's actual progress."""
    workdir = make_workdir(tmp)
    status(workdir)
    before = json.loads((workdir / "status.json").read_text())
    stage_before = next(b for b in before["batches"] if b["batch"] == 1)["stage"]
    assert hold(workdir).returncode == 0
    status(workdir)
    after = json.loads((workdir / "status.json").read_text())
    held = next(b for b in after["batches"] if b["batch"] == 1)
    assert held["stage"] == stage_before, (held, stage_before)
    assert held["stage"] in before["stage_names"], held
    log(f"stage stays {stage_before} while status becomes held")


def case_the_reason_is_shown_with_who_and_when(tmp):
    """The reason is the only part of a hold worth anything a week later, so it
    is printed under its own heading rather than buried in the batch list."""
    workdir = make_workdir(tmp)
    assert hold(workdir, extra=("--by", "Some Operator")).returncode == 0
    out = status(workdir)
    section = out.split("held (", 1)[1].split("next:", 1)[0]
    assert REASON in section, section
    assert "Some Operator" in section, section
    assert "--status classified" in section, section
    log("the held heading carries reason, operator, time and the release verb")


CASES = [
    ("D-28 — `held` is an accepted status", case_held_is_an_accepted_status),
    ("D-28 — next: never proposes a held batch",
     case_next_never_proposes_a_held_batch),
    ("D-28 — status.json carries the hold", case_the_ledger_carries_the_hold),
    ("D-28 — a hold without a reason is refused",
     case_a_hold_without_a_reason_is_refused),
    ("D-28 — a reason without a hold is refused",
     case_a_reason_without_a_hold_is_refused),
    ("D-28 — releasing a hold clears it", case_releasing_a_hold_clears_it),
    ("D-28 — a hold is not a stage", case_a_hold_is_not_a_stage),
    ("D-28 — the reason is shown with who and when",
     case_the_reason_is_shown_with_who_and_when),
    ("FIX7 F2 — status shows plan paths against dest_root (REPRODUCTION)",
     case_status_shows_plan_paths_against_dest_root),
    ("FIX8 F8-5 — status hides destination names by default (REPRODUCTION)",
     case_status_hides_destination_names_by_default),
    ("FIX8 F8-5 — prep/cluster/finish tails name no destination",
     case_the_tail_of_other_commands_names_no_destination),
]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    passed = 0
    for name, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="d28_"))
        try:
            fn(tmp)
        except Exception as exc:
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"  ok    {name}")
            passed += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{passed}/{len(CASES)} held-state cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
