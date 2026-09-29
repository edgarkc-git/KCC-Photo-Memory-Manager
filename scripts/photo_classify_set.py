#!/usr/bin/env python3
"""photo-classify Stage 3c — record a batch's classification into batches.json.

Keeps state writes structured so no agent ever hand-edits JSON. Only fields
this stage owns are touched; a .bak of batches.json is kept per run.

[type] is checked against the OWNER's own vocabulary, because what a photo
collection is "about" is a fact about its owner, not about the engine. The
taxonomy comes from the owner pack (photo-profile.json -> naming_spec.types).
With no such declaration it resolves through photo_profile.default_types(),
which is language-aware — see U2-06 there. ⛔ This module holds no
vocabulary of its own and must never regain one.

Usage:
  python3 photo_classify_set.py "<work dir>" --batch 1 \
      --type "<a word from the owner's taxonomy>" --where "<place>" \
      --note "..." [--status classified]

  python3 photo_classify_set.py "<work dir>" --batch 1 --status held \
      --reason "<why this is waiting on the owner>"

`held` records a deliberate stop on an unanswered question, with a reason, a
time and a self-declared operator. `photo_run.py status` lists held batches
under their own heading and proposes no action on them. Setting any other
status releases the hold and clears those fields.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import photo_profile  # noqa: E402

# D-28. `held` is NOT a stage — it is orthogonal to how far a batch has got.
# It means a human deliberately stopped this batch on an unanswered question,
# and it exists because the alternative was indistinguishable from work nobody
# had started: a held batch reported as `pending`, with no reason, no when and
# no who, while `next:` handed the operator the command to classify it. A hold
# that the tool then talks you out of is worse than no hold at all.
HELD = "held"
STATUSES = {"pending", "classified", "planned", "approved", "done", HELD}


def allowed_types(workdir):
    """-> the `[type]` words this owner may use.

    ⛔ U2-06 — the fallback used to be a Traditional-Chinese-only set defined
    in this module, so an owner whose language is not Chinese was refused by
    the check below in a language they may not read. It now resolves through
    the owner pack exactly as the bucket and scene vocabularies do. Rule 8:
    language is a variable, default English; the engine holds no vocabulary of
    its own.
    """
    profile = photo_profile.load_profile(workdir=workdir)
    types = photo_profile.get(profile, "naming_spec", "types")
    return set(types) if types else photo_profile.default_types(profile)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir")
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--type", dest="ctype")
    ap.add_argument("--where")
    ap.add_argument("--note")
    ap.add_argument("--status", default="classified")
    ap.add_argument("--reason", help="why this batch is held — free text, "
                                     "required with --status held")
    ap.add_argument("--by", default="Claude User",
                    help="self-declared operator, recorded not verified")
    args = ap.parse_args()

    path = Path(args.workdir).resolve() / "batches.json"
    types = allowed_types(path.parent)
    if args.ctype and args.ctype not in types:
        sys.exit(f"type must be one of: {' '.join(sorted(types))}")
    if args.status not in STATUSES:
        sys.exit(f"status must be one of: {' '.join(sorted(STATUSES))}")
    # ⛔ A hold with no reason is the defect wearing a different status name:
    # the operator who finds it a week later still cannot tell it from work
    # somebody forgot. The reason is the whole point, so it is required here
    # rather than encouraged in a doc.
    if args.status == HELD and not (args.reason or "").strip():
        sys.exit("--status held needs --reason: a hold nobody can read is "
                 "indistinguishable from an unstarted batch, which is the "
                 "thing holding was meant to prevent")
    if args.reason and args.status != HELD:
        sys.exit("--reason belongs to --status held; use --note for a "
                 "classification note")

    data = json.loads(path.read_text())
    batch = next((b for b in data["batches"] if b["batch"] == args.batch), None)
    if batch is None:
        sys.exit(f"batch {args.batch} not in {path}")

    shutil.copy2(path, path.with_suffix(".json.bak"))
    if args.ctype:
        batch["type"] = args.ctype
    if args.where is not None:
        batch["where"] = args.where
    if args.note is not None:
        batch["note"] = args.note
    was_held = batch.get("status") == HELD
    batch["status"] = args.status
    if args.status == HELD:
        batch["held_reason"] = args.reason.strip()
        batch["held_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        batch["held_by"] = args.by
    elif was_held:
        # Releasing a hold clears it. Leaving the fields behind would let a
        # later `status` print a stale reason beside a batch that is moving
        # again — a hold that outlives its answer.
        for key in ("held_reason", "held_at", "held_by"):
            batch.pop(key, None)
    batch["classified_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(json.dumps(batch, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
