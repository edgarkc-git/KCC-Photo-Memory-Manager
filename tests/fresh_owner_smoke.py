#!/usr/bin/env python3
"""Fresh-owner smoke test — the V2-6 assertion.

The engine must run end-to-end for an owner it has never seen, with none of
the facts that 25 sessions of real use put into one particular person's pack.
A golden replay cannot prove this: golden dumps come from that person.

So this builds a synthetic collection for a made-up owner and drives the plan
stage over it, then checks the isolation invariant the pack design rests on.

  python3 tests/fresh_owner_smoke.py [-v]

Exit 0 = pass. No network, no external drive, nothing outside a temp dir.

The leak check (check 7) names no owner. It used to hold one real owner's
names as string literals, which made this file the violation it exists to
catch (F13). The terms now come from the private, gitignored
tests/.owner-terms.json, loaded through tests/no_owner_facts.py's own
loader so there is ONE mechanism and one list. With no private file that
one check SKIPS with a message and everything else still runs: a missing
private file must never fail a public contributor's build.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))
import pack_state as pks  # noqa: E402
from no_owner_facts import load_owner_terms  # noqa: E402

# A photo owner who does not exist, with a vocabulary nobody in this project
# uses, living somewhere nobody in this project lives.
OWNER = "juno"
TYPES = ["hike", "roadtrip", "market", "screenshot", "misc"]


def build_collection(root):
    """A minimal but real work dir: manifest + batches + plans, no drive."""
    workdir = root / "Working Files" / "2031-08"
    (workdir / "plan").mkdir(parents=True)
    dest_root = str(root / "sorted")

    rows = []
    for i in range(1, 25):
        day = 3 if i <= 12 else 4
        is_shot = i % 8 != 0
        rows.append({
            "SourceFile": f"{root}/raw/2031-08/PIC_{i:04d}."
                          + ("png" if not is_shot else "jpg"),
            "FileName": f"PIC_{i:04d}." + ("png" if not is_shot else "jpg"),
            "FileType": "PNG" if not is_shot else "JPEG",
            "FileSize": str(1_000_000 + i),
            "DateTimeOriginal": f"2031:08:{day:02d} 1{i % 10}:00:00",
            "GPSLatitude": "" if not is_shot else "51.51",
            "GPSLongitude": "" if not is_shot else "-0.13",
            "Make": "" if not is_shot else "Nokia",
            "Model": "" if not is_shot else "XR30",
            # the built-in screenshot rule keys on no-camera + PNG + a phone
            # screen size; this owner has not confirmed screen sizes yet, so
            # the engine's fallback size is what has to catch these
            "ImageWidth": "1170" if not is_shot else "4032",
            "ImageHeight": "2532" if not is_shot else "3024",
        })
    with open(workdir / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    (workdir / "batches.json").write_text(json.dumps({
        "source": f"{root}/raw/2031-08",
        "main_files": len(rows),
        "batches": [{"batch": 1, "from": "2031-08-03", "to": "2031-08-04",
                     "files": len(rows), "status": "classified",
                     "type": "hike", "where": "Hampstead Heath", "flags": []}],
    }, indent=1))

    (workdir / "plans.json").write_text(json.dumps({
        "dest_root": dest_root,
        "plans": [{"plan": 1, "title": "Heath walk",
                   "batches": [1],
                   "dest": {"mode": "new",
                            "path": f"{dest_root}/20310803_Hampstead-Heath_hike"}}],
    }, indent=1))
    return workdir, dest_root


def run(cmd, env=None, expect_ok=True):
    proc = subprocess.run([sys.executable, *[str(c) for c in cmd]],
                          capture_output=True, text=True, env=env)
    if expect_ok and proc.returncode != 0:
        raise AssertionError(f"{cmd[0].name if hasattr(cmd[0], 'name') else cmd[0]} "
                             f"failed:\n{proc.stdout}\n{proc.stderr}")
    return proc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    checks, failures, skipped = [], [], []

    def check(name, ok, detail=""):
        checks.append((name, ok, detail))
        if not ok:
            failures.append(name)

    def skip(name, why):
        """A check that could not run is neither a pass nor a failure, and
        must not be printed as either."""
        checks.append((name, None, why))
        skipped.append(name)

    with tempfile.TemporaryDirectory(prefix="fresh-owner-") as tmp:
        root = Path(tmp)
        workdir, dest_root = build_collection(root)
        memory_root = root / "notes" / "photo-memory"
        env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}

        # 1. a pack can be created from the template alone
        run([SCRIPTS / "photo_pack_init.py", memory_root, OWNER,
             "--display", "Juno"], env=env)
        pack = memory_root / OWNER
        check("pack created from template",
              (pack / "photo-profile.json").exists()
              and (pack / f"photo-owner-{OWNER}.md").exists())

        profile = json.loads((pack / "photo-profile.json").read_text())
        profile["language"] = "en"
        profile["own_camera_makes"] = ["Nokia"]
        profile["naming_spec"] = {"types": TYPES}
        (pack / "photo-profile.json").write_text(json.dumps(profile, indent=2))

        # 2. binding by collection.json alone, no env var, no --profile
        (workdir.parent / "collection.json").write_text(json.dumps({
            "collection": "juno-2031", "owner": OWNER,
            "memory_root": str(memory_root), "dest_root": dest_root}, indent=1))
        got = json.loads(run([SCRIPTS / "photo_profile.py", workdir],
                             env=env).stdout)
        check("collection.json binds the owner", got["owner"] == OWNER, str(got))
        check("pack snapshot id is produced",
              bool(got["snapshot"] and got["snapshot"]["id"].startswith("sha256:")),
              str(got["snapshot"]))

        # EV-9 — say which pack these checks ran under, before printing any of
        # them. ⛔ Printed, never asserted blank: this owner is invented but
        # deliberately NOT empty (a camera make and a type vocabulary were just
        # written in, and checks 5/6b exist to prove the engine reads them). A
        # blank-sheet assertion here would fail the suite for holding its own
        # fixture. What the header buys is that a future edit binding this run
        # to somebody's real pack shows up in the first line of the report.
        state_line = pks.pack_state(
            pks.resolve_pack_ignoring_env(workdir=workdir), benchmark=False,
            run_type=pks.TIER1_FIXTURE)[1]

        # 3. an owner with no pack HARD-FAILS instead of borrowing another's
        (workdir.parent / "collection.json").write_text(json.dumps({
            "collection": "juno-2031", "owner": "nobody",
            "memory_root": str(memory_root), "dest_root": dest_root}, indent=1))
        proc = run([SCRIPTS / "photo_profile.py", workdir], env=env,
                   expect_ok=False)
        check("missing pack hard-fails",
              proc.returncode != 0 and "no pack" in proc.stderr,
              proc.stderr.strip()[:200])

        # 4. a --profile from one owner + a collection naming another is refused
        (workdir.parent / "collection.json").write_text(json.dumps({
            "collection": "juno-2031", "owner": "someone-else",
            "memory_root": str(memory_root), "dest_root": dest_root}, indent=1))
        proc = run([SCRIPTS / "photo_profile.py", workdir,
                    "--profile", pack / "photo-profile.json"],
                   env=env, expect_ok=False)
        check("cross-owner mixing is refused",
              proc.returncode != 0 and "owner conflict" in proc.stderr,
              proc.stderr.strip()[:200])

        # back to the real owner for the pipeline run
        (workdir.parent / "collection.json").write_text(json.dumps({
            "collection": "juno-2031", "owner": OWNER,
            "memory_root": str(memory_root), "dest_root": dest_root}, indent=1))

        # 5. the owner's own vocabulary is what classify validates against
        ok = run([SCRIPTS / "photo_classify_set.py", workdir, "--batch", "1",
                  "--type", "roadtrip"], env=env, expect_ok=False)
        bad = run([SCRIPTS / "photo_classify_set.py", workdir, "--batch", "1",
                   "--type", "randonnée"], env=env, expect_ok=False)
        check("owner vocabulary accepted", ok.returncode == 0, ok.stderr[:200])
        check("vocabulary outside the pack rejected",
              bad.returncode != 0 and "roadtrip" in bad.stderr,
              bad.stderr.strip()[:200])

        # 6. the plan stage runs end to end and routes into the owner's tree
        run([SCRIPTS / "photo_classify_set.py", workdir, "--batch", "1",
             "--type", "hike"], env=env)
        # This smoke drives the METADATA path only: no embed/, no see stage,
        # so R1's gate has nothing to gate and --no-vision is the honest
        # answer rather than a bypass. ⛔ Not a template for a live dump.
        run([SCRIPTS / "photo_plan.py", workdir, "--plan", "1", "--no-status",
             "--no-vision"],
            env=env)
        planned = list(csv.DictReader(
            open(workdir / "plan" / "plan_P1-files.csv", newline="")))
        check("every file planned", len(planned) == 24, str(len(planned)))
        check("everything lands under the owner's dest_root",
              all(r["destination"].startswith(dest_root) for r in planned))
        shots = [r for r in planned
                 if r["destination"].endswith("20310800_Screenshots")]
        check("screenshots split into their own monthly bucket",
              len(shots) == 3, f"{len(shots)} of 24")
        # the engine used to name every generated bucket in Traditional
        # Chinese no matter who the owner was
        # i18n-guard:allow-begin — locale detection data: the assertion has
        # to name the range it refuses, exactly like no_owner_facts.py's own
        # CJK pattern does.
        cjk = sorted({r["destination"] for r in planned
                      if any("一" <= ch <= "鿿" for ch in r["destination"])})
        # i18n-guard:allow-end
        check("no bucket named in another owner's language", not cjk, str(cjk))

        # 6b. the owner's own camera is never called somebody else's. 21 of
        # the 24 rows are Nokia, which is exactly what this pack calls its
        # own — before the fix all 21 were noted `shared`.
        own = [r for r in planned if "PIC_" in r["FileName"]
               and "shared" not in r["note"]]
        check("owner's own camera is not labelled shared",
              len(own) == 24, f"{24 - len(own)} of 24 rows say shared")

        # 7. nothing about any other owner leaked into the output. The terms
        # are read from the private list, never written here, and only the
        # COUNT is reported — printing the term would put it back in a
        # tracked file.
        blob = json.dumps(planned, ensure_ascii=False) + \
            (workdir / "plan" / "plan_P1.md").read_text()
        terms, note = load_owner_terms()
        if terms is None:
            skip("no other owner's facts in the output", note)
        else:
            low = blob.lower()
            leaks = sum(1 for t in terms if t.lower() in low)
            check("no other owner's facts in the output", not leaks,
                  f"{leaks} of {len(terms)} private terms found in the output"
                  " (terms are never printed)")

    print(state_line)
    width = max(len(n) for n, _, _ in checks)
    for name, ok, detail in checks:
        mark = "skip" if ok is None else ("ok  " if ok else "FAIL")
        show = detail and (args.verbose or ok is not True)
        print(f"  {mark}  {name.ljust(width)}" + (f"   {detail}" if show else ""))
    ran = len(checks) - len(skipped)
    print(f"\n{ran - len(failures)}/{ran} checks passed"
          + (f", {len(skipped)} skipped" if skipped else "")
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
