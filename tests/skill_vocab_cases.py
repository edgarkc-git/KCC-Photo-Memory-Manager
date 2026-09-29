#!/usr/bin/env python3
"""U3-24 cases — what `photo-classify/SKILL.md` documents must be typeable.

`photo_classify_set.py --type X` validates X against `allowed_types()`, which
resolves the owner pack's `naming_spec.types` or falls back to the VALUES of
`photo_profile.TYPE_VOCAB` for the owner's language. The SKILL documented the
KEYS — and two words (`screenshots`, `ai_images`) that are neither key nor
value. ⛔ Measured in UAT01-3: 9 of 17 classify calls were refused, so a
tester following the SKILL verbatim is rejected on nearly half its vocabulary.

⛔ THE FIX IS NOT "PUT THE ENGLISH VALUES IN THE SKILL." The accepted words
are language-resolved (Rule 8): `hiking` is valid for an English owner and
INVALID for a Chinese one, whose pack accepts the Chinese word instead.
A hardcoded list in a
document is wrong for every owner it was not written for, which is why the
SKILL now points at the runtime's own message instead of carrying a list.

So these cases assert two things a document CAN promise:
  * every id it prints is a real engine id, and
  * every `--type` example it shows is one an English owner could actually
    type — the default an unbound run gets.

⚠️ This suite reads a MARKDOWN file on purpose. It is a drift test between a
document and a vocabulary, which is the defect class it exists for; no
fixture is built and nothing is mocked.

  python3 tests/skill_vocab_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_profile  # noqa: E402
import photo_see  # noqa: E402

SKILL = ROOT / "photo-classify" / "SKILL.md"
EN = {"language": "English"}

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def taxonomy_row():
    for line in SKILL.read_text(encoding="utf-8").splitlines():
        if line.startswith("| [type] taxonomy |"):
            return line
    return ""


@case
def every_id_the_skill_prints_is_a_real_engine_id():
    """⛔ THE REPRODUCTION. On `c050665` the row printed `screenshots` and
    `ai_images`, which are not ids and not words — the engine's are
    `screenshot` and `ai_generated`. A reader had no way to tell a typo from
    a vocabulary they had not met."""
    ids = set(photo_profile.TYPE_VOCAB["en"])
    printed = set(re.findall(r"`([a-z][a-z_]+)`", taxonomy_row()))
    # ⛔ EVERY bare lowercase token in backticks is judged, with no "looks
    # like an id" filter. An earlier version of this case required an
    # underscore or a known id, and `screenshots` — one of the four words
    # that actually refused a tester — passed straight through it. A guard
    # that skips the tokens it cannot classify is not a guard.
    # Resolved words (`overseas-trip`) carry a hyphen and dotted paths
    # (`naming_spec.types`) a dot, so neither matches this pattern at all.
    unknown = sorted(printed - ids)
    return not unknown, f"not engine ids: {unknown}"


@case
def the_skill_names_every_engine_id():
    """A document that lists a vocabulary must list all of it — a silently
    missing id is a word the operator never learns exists."""
    ids = set(photo_profile.TYPE_VOCAB["en"])
    printed = set(re.findall(r"`([a-z][a-z_]+)`", taxonomy_row()))
    return not (ids - printed), f"missing from the SKILL: {sorted(ids - printed)}"


@case
def every_type_example_in_the_skill_is_typeable_by_an_english_owner():
    """⛔ THE OTHER HALF OF THE REPRODUCTION, and the one that actually
    refused a tester. The worked example carried `day_trip`; an unbound run
    resolves English, where the accepted word is `day-trip`."""
    text = SKILL.read_text(encoding="utf-8")
    accepted = photo_profile.default_types(EN)
    ids = set(photo_profile.TYPE_VOCAB["en"])
    # A worked example prints `<type>` bare in the batch summary block; the
    # ids are only legal inside the taxonomy row that declares them as ids.
    body = "\n".join(l for l in text.splitlines()
                     if not l.startswith("| [type] taxonomy |"))
    bad = sorted({t for t in ids if t not in accepted
                  and re.search(rf"(?<![-`\w]){re.escape(t)}(?![-\w])", body)})
    return not bad, f"engine ids used as examples: {bad}"


@case
def the_skill_does_not_promise_a_fixed_list_of_accepted_words():
    """⛔ Rule 8. The accepted words are language-resolved, so a document that
    names them is wrong for every owner it was not written for. It must send
    the reader to the runtime instead — the refusal already prints the exact
    set."""
    row = taxonomy_row()
    return ("type must be one of" in row
            and "naming_spec.types" in row), "the row promises no runtime source"


@case
def the_refusal_really_does_print_the_accepted_set():
    """The claim the SKILL now rests on, checked against the code rather than
    trusted. ⛔ If this message ever stops listing them, the document silently
    becomes a dead end."""
    src = (SCRIPTS / "photo_classify_set.py").read_text(encoding="utf-8")
    return ('sys.exit(f"type must be one of: {\' \'.join(sorted(types))}")'
            in src), "the refusal no longer lists the accepted types"


# ---------------------------------------------------------------------------
# U3-02 / U3-03 — three lists, three names
# ---------------------------------------------------------------------------

@case
def the_three_vocabularies_still_stand_in_the_documented_relation():
    """⛔ "Fix the 11 down to 10" was a wrong remedy once already (when it
    was 9). The 11 is not a longer `[type]` list: 11 = the 6 nameable scene
    classes + 5 utility detectors, and 10 = those same 6 + `home` (an ordinary
    day at home, W1C-7 — a type word with no scene class behind it) + 3 engine
    buckets. Asserted so the note explaining it cannot quietly stop being
    true: the extra words are named, not counted."""
    labels = set(photo_see.DEFAULT_SCENE_LABELS)
    classes = set(photo_profile.SCENE_CLASS_VOCAB["en"])
    types = set(photo_profile.TYPE_VOCAB["en"])
    return (len(labels) == 11 and len(classes) == 6 and len(types) == 10
            and classes < labels and classes < types
            and len(labels - classes) == 5
            and types - classes == {"home", "screenshot", "ai_generated",
                                    "others"}), \
        f"labels={len(labels)}, classes={len(classes)}, types={len(types)}, " \
        f"utility={sorted(labels - classes)}, buckets={sorted(types - classes)}"


@case
def each_vocabulary_says_which_one_it_is():
    """The cheap half of U3-02/U3-03: a reader landing on any one of the three
    can tell which it is without finding the other two."""
    prof = (SCRIPTS / "photo_profile.py").read_text(encoding="utf-8")
    see = (SCRIPTS / "photo_see.py").read_text(encoding="utf-8")
    return ("THREE lists in this engine get called" in prof
            and "the VALUES are what" in prof
            and "is NOT a longer `[type]` list" in see), \
        "a vocabulary no longer names itself"


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

    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} skill-vocab cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
