#!/usr/bin/env python3
"""Golden-dump regression harness (Phase A / M9).

Replays photo_plan.py against dumps that already shipped, and diffs the plan
it produces now against the plan that was actually executed back then.

Dumps planned before a naming decision (D13, D14) legitimately differ. Those
are handled by replaying the shipped plan FORWARD through the decisions that
post-date it (tests/waivers.py) and requiring exact equality — not by a list
of rows to ignore. Anything left over fails the harness.

Runs fully OFFLINE — the fixtures in tests/golden/ are frozen copies of each
dump's work dir, so neither external drive has to be mounted.

The fixture root is SELECTABLE, because the default one does not ship to
everybody: flag > $PHOTO_GOLDEN_FIXTURES > tests/golden. A checkout without
fixtures does not get a quiet green run — it gets exit 2 (see
`fixture_root_problem`).

  python3 tests/golden_replay.py                 # all dumps
  python3 tests/golden_replay.py --dump 202605   # one dump
  python3 tests/golden_replay.py -v              # name the deltas applied
  python3 tests/golden_replay.py --report out.md # write a markdown report
  python3 tests/golden_replay.py --fixtures DIR  # a fixture set kept elsewhere
  PHOTO_GOLDEN_FIXTURES=DIR python3 tests/golden_replay.py   # same, via env

Exit 0 = clean or fully explained; 1 = unexplained diffs; 2 = harness error.

Scope and limits (read before trusting a green run):
  * Covers the PLAN stage only — photo_plan.py plus what it imports
    (photo_cluster.parse_date, photo_sample.preclassify, photo_profile).
  * Dedupe results are frozen INPUTS (plan/dedupe_batch-NN.json), so a change
    to photo_dedupe.py passes this harness untested. Same for photo_scan.py
    (manifest.csv is frozen) and photo_cluster.py's clustering itself
    (batches.json is frozen). Those stages need their own tests.
  * Compares plan_PN-files.csv only, never plan_PN.md — the md embeds
    datetime.now() and a destination-folder listing that depends on whether
    the drive is mounted, both nondeterministic by construction.
  * The engine's behaviour also depends on the loaded memory pack, so a fixture
    that needs one carries its own SYNTHETIC pack inside input/ (bound by
    input/collection.json) and index.json pins that pack's snapshot id. The
    operator's PHOTO_PROFILE is still cleared from the environment: a replay
    reads fixture data only, pack included, and a pack that drifts fails the
    run rather than silently changing what "reproduced" means.
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts"))
import pack_state as pks  # noqa: E402
import waivers  # noqa: E402
import photo_magic  # noqa: E402
import photo_profile  # noqa: E402

ENV_FIXTURES = "PHOTO_GOLDEN_FIXTURES"
DEFAULT_FIXTURES = HERE / "golden"
PLAN_PY = REPO / "scripts" / "photo_plan.py"


def fixture_root(arg=None):
    """Where the frozen dumps live: --fixtures > $PHOTO_GOLDEN_FIXTURES >
    tests/golden.

    ⚠️ Resolution ONLY — it never touches the disk. The one caller that may
    legitimately find nothing (tests/photo_memory_cases.py, which skips its
    fixture-backed case) must be able to ask where the root would be without
    being exited out from under. Validation lives in `fixture_root_problem`.

    An empty string from either source counts as unset: `PHOTO_GOLDEN_FIXTURES=`
    in a shell profile is a variable nobody meant to set, not a request to
    replay the current directory."""
    return Path(arg or os.environ.get(ENV_FIXTURES) or DEFAULT_FIXTURES).expanduser()


def fixture_root_problem(root):
    """-> a sentence naming what is missing and how to point elsewhere, or None.

    ⛔ An absent, empty or dump-less fixture root is a HARNESS ERROR — exit 2,
    never 1 and never 0.

    ⚠️ Measured at b0b9e11 before this was written, because the obvious
    justification is wrong: with no fixtures the old harness did NOT print a
    green line over zero dumps. It exited 1 four different ways — a
    FileNotFoundError traceback for an absent root and for a root with no
    index.json, `no such dump; have: []` for an index declaring nothing, and a
    copytree traceback for a declared dump with no directory. What it DID do
    was exit 0 with ALL GOLDEN DUMPS REPRODUCED while ignoring
    $PHOTO_GOLDEN_FIXTURES entirely and replaying tests/golden instead — a
    green line for a set the caller never asked for.

    So the value here is not "stops a false green" but: one exit code that
    means the harness could not run, distinct from 1 (the engine changed), and
    a message a public cloner can act on. The zero-dump green line is what a
    build with the flag and WITHOUT this function produces — measured as
    mutation control B, not as history."""
    # The default is named only when it is NOT the path that just failed:
    # printing the same directory twice in one sentence reads as a bug in the
    # message and buries the two override names, which are the actionable part.
    where = f"point --fixtures or ${ENV_FIXTURES} at a fixture set"
    if root != DEFAULT_FIXTURES:
        where += f" (default: {DEFAULT_FIXTURES})"
    if not root.is_dir():
        return f"no fixture root at {root} — {where}"
    index_path = root / "index.json"
    if not index_path.is_file():
        return f"no index.json in fixture root {root} — {where}"
    try:
        index = json.loads(index_path.read_text())
    except (ValueError, OSError) as exc:
        return f"cannot read {index_path}: {exc} — {where}"
    if not index.get("dumps"):
        return f"{index_path} declares no dumps — {where}"
    missing = [d["id"] for d in index["dumps"] if not (root / d["id"]).is_dir()]
    if missing:
        # Otherwise replay_dump()'s copytree raises a traceback instead, and a
        # half-populated root replays whatever happens to be there.
        return (f"fixture root {root} is missing the dump director"
                f"{'y' if len(missing) == 1 else 'ies'} its index.json "
                f"declares: {', '.join(missing)} — {where}")
    return None


def require_fixture_root(arg=None):
    """-> (root, index), or exit 2. ⚠️ `sys.exit(str)` exits 1, which is the
    code for "the engine changed" — a harness error has to stay 2."""
    root = fixture_root(arg)
    problem = fixture_root_problem(root)
    if problem:
        print(f"harness error: {problem}", file=sys.stderr)
        sys.exit(2)
    return root, json.loads((root / "index.json").read_text())


def fixture_pack(fixture):
    """The pack THIS fixture carries, resolved from fixture data alone.

    ⚠️ `PHOTO_PROFILE` is cleared first, for the same reason `replay_dump()`
    strips it from the subprocess environment: a replay reads fixture data
    only, pack included. Without this the operator's own pack could be the one
    a Tier 1 header names, which is precisely the substitution EV-9 exists to
    make visible."""
    return pks.resolve_pack_ignoring_env(workdir=fixture / "input")


def pack_line(dump, fixture):
    """EV-9's header, per fixture.

    ⭐ Per FIXTURE, not per run, and that is the only honest shape here: each
    golden dump carries its own pack inside `input/photo-memory/` (three carry
    none, two carry different owners), so one summary line for the run would
    have to either omit which pack produced which rows or invent a pack the
    run never loaded.

    ⛔ Printed, never asserted blank. A Tier 1 fixture is not a benchmark: two
    of these packs exist precisely BECAUSE the routing under test is
    pack-driven, and a blank-sheet assertion here would fail the suite for
    holding the input it is supposed to hold. What guards a Tier 1 pack is
    `check_pack()`'s snapshot pin against index.json."""
    _state, line = pks.pack_state(fixture_pack(fixture), benchmark=False,
                                 run_type=pks.TIER1_FIXTURE)
    return f"{dump['id']:<10} {line}"


def check_pack(dump, fixture):
    """The fixture's own pack is an input like any other, so it has to be
    pinned. -> list of problems (empty = the run used the pack index.json
    names, or no pack at all where none is declared)."""
    pack = fixture_pack(fixture)
    want, got = dump.get("pack"), pack.snapshot()
    if not want:
        return ([] if not got else
                [f"fixture carries an undeclared pack ({got['owner']} "
                 f"{got['id']}) — add it to index.json or remove it"])
    if not got:
        return [f"index.json declares pack {want['owner']!r} but the fixture "
                "has none"]
    if (got["owner"], got["id"]) != (want["owner"], want["id"]):
        return [f"pack drift: index.json pins {want['owner']} {want['id']}, "
                f"fixture now resolves {got['owner']} {got['id']}"]
    return []


def load_csv(path):
    """-> {SourceFile: row}. SourceFile is unique within a plan CSV."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        key = r["SourceFile"]
        if key in out:                       # defensive: never seen so far
            key = f"{key}#{len(out)}"
        out[key] = r
    return out


def replay_dump(dump, tmp_root, gold, verbose=False):
    """-> dict with per-plan results for one golden dump.

    `gold` is passed in, never read off a module global: the fixture root is
    now a run-time choice, and a global would make which set was replayed
    invisible at this call site."""
    fixture = gold / dump["id"]
    work = tmp_root / dump["id"]
    shutil.copytree(fixture / "input", work)
    (work / "plan").mkdir(exist_ok=True)

    env = dict(os.environ)
    env.pop("PHOTO_PROFILE", None)           # fixture data only, no owner pack
    # A replay reads fixture bytes, not the live drive: on the owner's machine
    # a fixture's SourceFile paths can still resolve, and the plan's L17
    # content check would then read real files (Card 6).
    env[photo_magic.TEST_HOOK_ENV] = "1"

    fixture_inputs = waivers.Fixture(fixture / "input")
    result = {"id": dump["id"], "plans": [], "errors": check_pack(dump, fixture),
              "pack_line": pack_line(dump, fixture)}
    tally = {}
    targets = [("--plan", str(n), f"plan_P{n}-files.csv") for n in dump["plans"]]
    if dump.get("has_no_date"):
        targets.append(("--no-date", None, "plan_no-date-files.csv"))

    for flag, value, csv_name in targets:
        cmd = [sys.executable, str(PLAN_PY), str(work), flag]
        if value:
            cmd.append(value)
        cmd.append("--no-status")
        # R1's gate refuses a plan whose batches have no see-stage output. The
        # golden fixtures are frozen dumps that SHIPPED BEFORE that stage
        # existed, so most carry none -- and this harness compares ROUTING
        # rows, which the gate does not touch. Bypassing it here keeps the
        # replay measuring what it was built to measure; the gate's own
        # behaviour is held by tests/photo_plan_cases.py, which reproduces the
        # UAT01 condition end to end. ⛔ Never widen this flag's use beyond
        # frozen fixtures: on a live dump it gives up WHO/WHAT silently, which
        # is the defect R1 exists to end.
        cmd.append("--no-vision")
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            result["errors"].append(f"{csv_name}: photo_plan exited "
                                    f"{proc.returncode}: {proc.stderr.strip()}")
            continue

        expected_path = fixture / "expected" / csv_name
        actual_path = work / "plan" / csv_name
        if not expected_path.exists():
            result["errors"].append(f"{csv_name}: no shipped baseline captured")
            continue
        if not actual_path.exists():
            result["errors"].append(f"{csv_name}: replay produced no CSV")
            continue

        exp, act = load_csv(expected_path), load_csv(actual_path)
        entry = {"csv": csv_name, "rows": len(exp), "identical": 0,
                 "deltas": set(), "unexplained": [], "missing": [], "extra": []}

        if csv_name == "plan_no-date-files.csv" and dump["id"] in waivers.PRE_D13:
            problems, fired = waivers.check_no_date(dump["id"], exp, act, fixture_inputs)
            entry["deltas"] |= fired
            entry["identical"] = len(exp) - len(problems)
            entry["unexplained"] = [{"source": p, "fields": [], "expected": {},
                                     "actual": {}} for p in problems]
            result["plans"].append(entry)
            continue

        model, fired, problems = waivers.forward_plan(dump["id"], exp,
                                                      fixture_inputs, tally)
        entry["deltas"] |= fired
        entry["unexplained"] += [{"source": p, "fields": [], "expected": {},
                                  "actual": {}} for p in problems]
        entry["missing"] = sorted(set(model) - set(act))
        entry["extra"] = sorted(set(act) - set(model))
        for key in sorted(set(model) & set(act)):
            e, a = model[key], act[key]
            if e == a:
                entry["identical"] += 1
            else:
                fields = sorted(k for k in (set(e) | set(a))
                                if e.get(k) != a.get(k))
                entry["unexplained"].append({
                    "source": key, "fields": fields,
                    "expected": {k: e.get(k) for k in fields},
                    "actual": {k: a.get(k) for k in fields}})
        result["plans"].append(entry)

    # A bug delta has to explain an exact number of rows, not "some".
    for key, want in waivers.EXPECTED_FLIPS.get(dump["id"], {}).items():
        got = tally.get(key, 0)
        if got != want:
            result["errors"].append(
                f"{key}: reconstruction moved {got} rows, expected exactly "
                f"{want} — the delta model and the engine disagree about "
                "which rows the fix reaches")

    return result


def render(results, verbose=False):
    # EV-9 — the pack state comes first, before any number it could qualify.
    lines = ["pack state (EV-9), one line per fixture:"]
    lines += ["  " + r["pack_line"] for r in results] + [""]
    ok = True
    for r in results:
        n_rows = sum(p["rows"] for p in r["plans"])
        n_same = sum(p["identical"] for p in r["plans"])
        deltas = set()
        for p in r["plans"]:
            deltas |= p["deltas"]
        bad = sum(len(p["unexplained"]) for p in r["plans"])
        gone = sum(len(p["missing"]) + len(p["extra"]) for p in r["plans"])
        status = "PASS" if not bad and not gone and not r["errors"] else "FAIL"
        if status == "FAIL":
            ok = False
        lines.append(f"{status}  {r['id']:<8} {len(r['plans']):>3} plans  "
                     f"{n_rows:>6} rows  {n_same:>6} identical  "
                     + (", ".join(sorted(deltas)) or "no deltas"))
        for e in r["errors"]:
            lines.append(f"       ! {e}")
        for p in r["plans"]:
            for key in p["missing"]:
                lines.append(f"       ! {p['csv']}: row vanished — {key}")
            for key in p["extra"]:
                lines.append(f"       ! {p['csv']}: row appeared — {key}")
            for u in p["unexplained"]:
                lines.append(f"       X {p['csv']}: {u['source']}")
                for f in u["fields"]:
                    lines.append(f"           {f}: {u['expected'][f]!r}"
                                 f" -> {u['actual'][f]!r}")
            if verbose and p["deltas"]:
                for wid in sorted(p["deltas"]):
                    lines.append(f"       ~ {p['csv']}: {wid}"
                                 f" ({waivers.REASONS.get(wid, '')})")
    return "\n".join(lines), ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", action="append", help="dump id (repeatable)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="name the policy deltas applied per plan CSV")
    ap.add_argument("--report", help="write a markdown report to this path")
    ap.add_argument("--fixtures", metavar="DIR",
                    help=f"fixture root (default ${ENV_FIXTURES}, "
                         "else tests/golden)")
    args = ap.parse_args()

    # Upstream of the --dump filter on purpose: "this root has nothing to
    # replay" is a harness error (2), "you asked for a dump this set does not
    # hold" is not. Merging them would let an empty root exit 1.
    gold, index = require_fixture_root(args.fixtures)
    dumps = [d for d in index["dumps"]
             if not args.dump or d["id"] in args.dump]
    if not dumps:
        sys.exit(f"no such dump; have: {[d['id'] for d in index['dumps']]}")

    with tempfile.TemporaryDirectory(prefix="golden-replay-") as tmp:
        results = [replay_dump(d, Path(tmp), gold, args.verbose) for d in dumps]

    text, ok = render(results, args.verbose)
    print(text)
    print("\n" + ("ALL GOLDEN DUMPS REPRODUCED" if ok
                  else "UNEXPLAINED DIFFS — treat as a regression"))

    if args.report:
        waived_total = {}
        for r in results:
            for p in r["plans"]:
                for wid in p["deltas"]:
                    waived_total[wid] = waived_total.get(wid, 0) + 1
        md = ["# Golden-dump replay report", "",
              "```", text, "```", "", "## Policy deltas applied", ""]
        md += [f"- `{k}` in {v} plan CSVs — {waivers.REASONS.get(k, '')}"
               for k, v in sorted(waived_total.items())] or ["- none"]
        Path(args.report).write_text("\n".join(md) + "\n")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
