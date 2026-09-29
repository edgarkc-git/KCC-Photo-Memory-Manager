#!/usr/bin/env python3
"""Cases for photo_name.py (R11 + R12) — the folder-name grammar, enforced.

Before this module `photo_plan.py` accepted whatever string the naming agent
typed into `plans.json`. Nothing assembled a name and nothing checked one, so
the signed grammar was a convention the agent was trusted to follow. In UAT01
it did not: 9 of 11 folders carried a single-day period for a multi-day batch,
and 6 of 11 dropped `[where]` while a resolved place name sat on disk in
`batches.json`.

⛔ The two REPRODUCTIONS below are those two failures, stated as tests. The
rest are guards — several of them exist because the obvious wrong fix breaks
something the SPEC is explicit about (dropping `[where]` to save budget,
capping `[who]` at one name, counting the separators).

Stdlib only — this suite belongs in the plain chain in tests/README.md.

  python3 tests/photo_name_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import photo_name as pn  # noqa: E402

VERBOSE = False


def log(msg):
    if VERBOSE:
        print(f"       {msg}")


def case_a_multi_day_batch_cannot_be_named_with_one_day():
    """⭐ REPRODUCTION (R11). 9 of 11 UAT01 folders were wrong this way.

    ⛔ The check is against the BATCH's own dates. A renderer that produces the
    right span does not stop an agent typing a single day over it, and typing
    the name is what actually happened — so the validator has to compare the
    name with the files it will hold, not merely parse it.
    """
    span = ("2026-04-29", "2026-05-03")
    ok, refusals, _ = pn.validate("20260429_Some-Place", span=span)
    assert not ok, "a one-day period over a five-day batch was accepted"
    assert "20260429-0503" in refusals[0], refusals
    log(refusals[0])
    ok, refusals, _ = pn.validate("20260429-0503_Some-Place", span=span)
    assert ok, f"the correct name was refused: {refusals}"


def case_a_span_end_is_a_full_mmdd_across_a_month_boundary():
    """D8. The old `-DD` form is unreadable exactly where a trip needs it:
    `20260429-03` cannot be resolved across a month boundary."""
    assert pn.period("2026-04-29", "2026-05-03") == "20260429-0503"
    assert pn.period("2026-12-30", "2027-01-02") == "20261230-0102", \
        "a span across a YEAR boundary still ends in a full MMDD"
    assert pn.period("2026-04-29") == "20260429"
    assert pn.period("2026-04-29", "2026-04-29") == "20260429", \
        "a span whose end repeats its start is one day, not a range"


def case_a_backwards_span_is_refused_not_rendered():
    """A guard. Rendering `20260503-0429` would produce a name that sorts into
    the wrong place and reads as a typo the owner has to trust."""
    for bad in [("2026-05-03", "2026-04-29"), ("not-a-date", None),
                ("", None)]:
        try:
            pn.period(*bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} was rendered instead of refused")


def case_a_known_place_may_not_be_dropped_from_the_name():
    """⭐ REPRODUCTION (R12). 6 of 11 UAT01 folders had a resolved place name
    sitting on disk in `batches.json` and used none of it.

    ⛔ N-5 is explicit: the elastic budget is spent on `[who]`/`[what]`, and
    that is NOT a permission to drop `[where]`. `[period]` and `[where]` are
    fixed cost.
    """
    ok, refusals, _ = pn.validate("20260429", place_known=True)
    assert not ok, "a name with no [where] passed while the place was known"
    assert "[where]" in refusals[0], refusals
    log(refusals[0])
    # ...and the honest case still passes: the engine really could not name it.
    ok, _, _ = pn.validate("20260429", place_known=False)
    assert ok, "a batch whose place is genuinely unknown must still be nameable"


def case_the_n2_budget_counts_what_the_spec_says_it_counts():
    """N-2, against the SPEC's own worked example.

    Two two-character names plus a five-character phrase = 9 units. Wide
    script is one unit per CHARACTER, narrow script one unit per WORD, and the
    separators cost nothing.

    ⛔ The SPEC states this rule with a worked example built from the owner's
    own pets and home. That example is NOT copied here — Rule 7 keeps owner
    facts out of the engine and out of its tests, and a fixture is exactly
    where such a name slips in unnoticed. These characters are arbitrary.
    """
    # i18n-guard:allow-begin — wide-vs-narrow counting is the thing under test,
    # so the fixture has to contain wide characters; they name nothing.
    wide = "\u7532\u4e59+\u4e19\u4e01_\u620a\u5df1\u5e9a\u8f9b\u58ec"
    assert pn.budget_units(wide) == 9, pn.budget_units(wide)
    # i18n-guard:allow-end
    assert pn.budget_units("play in Central park") == 4, \
        "narrow script counts WORDS, not characters"
    assert pn.budget_units("Ada+Bix") == 2, \
        "the `+` between names is punctuation and consumes no budget"
    assert pn.budget_units("") == 0 and pn.budget_units(None) == 0


def case_period_and_where_never_consume_budget():
    """A guard, and the one most likely to be broken by a naive validator: a
    long place name would otherwise eat the budget that belongs to [who]."""
    short = "20260429_A_Ada_hiking"
    longer = "20260429_" + "+".join(["Averyverylongplacename"] * 4) + "_Ada_hiking"
    a = pn.validate(short)
    b = pn.validate(longer)
    assert a[0] and b[0], (a, b)
    assert not a[2] and not b[2], \
        f"a longer [where] changed the budget verdict: {a[2]} vs {b[2]}"


def case_who_is_repeatable_and_is_not_capped_at_one():
    """SPEC v0.7 as amended 20260904: `[who]` is a REPEATABLE subject-ID slot.
    Three subjects in one folder name is normal, and the grammar itself
    imposes no cap — any cap is the caller's parameter."""
    # ⛔ Invented names. The plan writes this rule with an example built from
    # the owner's own household; Rule 7 keeps that out of the engine AND its
    # tests, and a fixture is precisely where such a name travels unnoticed.
    name = pn.render("2026-04-29", who=["Ada", "Bix", "Cleo"],
                     where=["Some-Place"])
    assert name == "20260429_Some-Place_Ada+Bix+Cleo", name
    ok, refusals, _ = pn.validate(name)
    assert ok, refusals
    log(name)


def case_the_hard_cap_refuses_and_the_soft_cap_only_warns():
    """Both are `{n}` parameters, so the case passes them explicitly rather
    than depending on the shipped defaults — a suite that pins a parameter
    turns it back into a constant."""
    name = "20260429_Place_" + "+".join(["Name"] * 6)   # 6 narrow words
    ok, refusals, warnings = pn.validate(name, hard=20, soft=4)
    assert ok and not refusals, refusals
    assert warnings and "soft target" in warnings[0], warnings
    ok, refusals, _ = pn.validate(name, hard=5, soft=4)
    assert not ok and "hard cap" in refusals[0], refusals
    log(refusals[0])



def case_the_what_slot_is_never_checked_against_a_list():
    """⭐ THE D-F11 GUARD, and the most important case in this file.

    `[what]` is OPEN free text — `hiking`, `sunset`, `coffee time`. The owner
    pack may carry a list of the owner's own phrases, and D-F11 is explicit
    that the list is a REFERENCE for whoever writes the name and NEVER A
    BOUNDARY on what they may write. A membership check on this slot turns
    `[what]` back into the closed `[type]` taxonomy it is specifically not —
    which is the defect, not the fix.

    ⛔ This case exists because the wrong fix is the tempting one. Validating
    a free-text slot against the vocabulary sitting right there reads like
    rigour, passes review, and silently deletes the whole point of the slot.
    So the guard is written three ways, because one alone is evadable:

      1. BEHAVIOUR — a phrase in no vocabulary anywhere validates clean.
         Catches a check written inline against a literal list.
      2. SIGNATURE — `validate()` takes no vocabulary argument. Catches the
         check that arrives as a new `vocabulary=` / `allowed=` keyword,
         which behaviour alone would miss while the default stayed None.
      3. REACH — `photo_name` does not import `photo_profile` at all, so it
         cannot reach the pack's list even if somebody wanted it to. Catches
         the check that reads the pack directly instead of being handed it.

    ⛔ Do not "fix" a failure here by adding the slot to a vocabulary. The
    failure means the membership check is back."""
    invented = "20260429_Place_Birk_qwertyuiop-noplacenames"
    ok, refusals, warnings = pn.validate(invented)
    assert ok and not refusals, (
        "a [what] phrase in no vocabulary was refused — D-F11 says the pack "
        f"list is a reference, never a boundary: {refusals}")
    assert not warnings, f"and it did not even warn about it: {warnings}"

    import inspect
    params = set(inspect.signature(pn.validate).parameters)
    forbidden = {"vocabulary", "vocab", "allowed", "allowed_what", "what",
                 "what_reference", "phrases", "types", "profile", "pack"}
    intruders = sorted(params & forbidden)
    assert not intruders, (
        f"photo_name.validate() grew {intruders} — a vocabulary reaching the "
        "validator is a membership check on [what] waiting to happen (D-F11)")

    # An IMPORT statement, not a mention: the docstrings name
    # `photo_profile.what_reference()` precisely to say it is not consulted,
    # and a substring test would read that sentence as the defect it forbids.
    import re
    src = inspect.getsource(pn)
    reach = re.search(r"^[ \t]*(?:import|from)\s+photo_profile\b", src, re.M)
    assert reach is None, (
        f"photo_name imports photo_profile ({reach.group(0).strip()!r}) — the "
        "grammar module must not be able to reach the owner's [what] list at "
        "all (D-F11); the budget travels the other way, passed IN as "
        "parameters by photo_profile.name_budget()")
    log(f"{invented!r} accepted, signature clean, no reach into the pack")


def case_the_soft_budget_is_sixteen_not_twelve():
    """⭐ REPRODUCTION (D-F13, signed 20260906). The shipped soft target was
    `{12}` and the signed one is `{16}`, so a correct name warned.

    ⛔ NOTHING IS DROPPED TO FIT — the limit was RAISED, which is only sane
    because of what N-2 counts: Latin per WORD and CJK per CHARACTER. The
    worst realistic English name is 6 units, so 12 could only ever be
    exceeded by a Chinese name carrying three subjects and a phrase. A soft
    target that fires on correct names teaches its reader to ignore it, and
    then it is not there for the name that really is too long.

    The name below is 14 units — over the old target, under the new one — so
    it warns on the unfixed engine and is silent now. ⛔ The hard cap is
    unchanged at 20 and must stay so; a case that only checked the soft
    number would pass a "fix" that moved both."""
    name = "20260429_Place_" + "_".join(["word"] * 14)
    assert pn.budget_units("_".join(["word"] * 14)) == 14, "the unit count moved"
    ok, refusals, warnings = pn.validate(name)
    assert ok and not refusals, refusals
    assert not warnings, (
        f"14 units still warns against the shipped soft target — D-F13 signed "
        f"{{16}}, this engine is using {pn.DEFAULT_NAME_BUDGET_SOFT}: {warnings}")
    assert pn.DEFAULT_NAME_BUDGET_SOFT == 16, pn.DEFAULT_NAME_BUDGET_SOFT
    assert pn.DEFAULT_NAME_BUDGET_HARD == 20, pn.DEFAULT_NAME_BUDGET_HARD
    # ...and 17 still warns, so the target was raised rather than removed.
    over = "20260429_Place_" + "_".join(["word"] * 17)
    ok, refusals, warnings = pn.validate(over)
    assert ok and not refusals and warnings, (refusals, warnings)
    log(warnings[0])


def case_a_leg_name_is_not_a_folder_name():
    """⭐ REPRODUCTION, and it was found by MEASURING before wiring, not by
    reading. Run over the 7 golden fixtures, a validator that treated every
    name as a FOLDER refused 32 of 132 — and most of those names were right
    all along. Three different things share this grammar and they are not
    variations of one pattern:

      FOLDER   YYYYMMDD / YYYYMMDD-MMDD   the trip or event folder
      LEG      MMDD / MMDD-MMDD           a SUB-folder inside a trip parent,
                                          carrying no year because its parent
                                          already does
      MONTHLY  YYYYMM00                   D14's bucket, the `00` day field
                                          sorting it inside its own month

    Had this shipped as a hard refusal on the write path it would have
    rejected a dozen correct names and broken the replay."""
    ok, refusals, _ = pn.validate("0506-0509", kind=pn.NAME_FOLDER)
    assert not ok, "a leg name passed as a folder name — the kinds are not separated"
    ok, refusals, _ = pn.validate("0506-0509", kind=pn.NAME_LEG)
    assert ok, f"a correct leg name was refused: {refusals}"
    ok, _, _ = pn.validate("20260506-0509", kind=pn.NAME_FOLDER)
    assert ok, "a correct folder name was refused"
    ok, refusals, _ = pn.validate("20260506-0509", kind=pn.NAME_LEG)
    assert not ok, "a full folder period passed as a leg — the check is not a no-op"


def case_a_monthly_bucket_carries_its_zero_day_field():
    """D14. The `00` is not decoration: it sorts the bucket INSIDE its month
    group beside the daily folders, instead of ahead of or behind all of
    them."""
    ok, refusals, warnings = pn.validate("20260200_others", kind=pn.NAME_MONTHLY)
    assert ok and not warnings, (refusals, warnings)
    ok, refusals, warnings = pn.validate("202602_others", kind=pn.NAME_MONTHLY)
    assert ok, f"a pre-D14 bucket was refused rather than warned: {refusals}"
    assert warnings, "a pre-D14 bucket passed silently"


def case_a_yearly_bucket_is_its_own_kind_and_not_legacy():
    """REPRODUCTION (Release B, M14). The owner ruled (20260922) that a no-EXIF
    VIDEO goes to `YYYY00_<bucket>`. The grammar had no yearly form: `202600`
    is SIX characters, so it cannot match MONTHLY (`\\d{6}00`, eight) and the
    only thing that DOES match it is the legacy pre-D14 `YYYYMM` pattern. The
    engine would have warned about its own new output as a superseded name."""
    assert hasattr(pn, "NAME_YEARLY"), "the grammar has no yearly kind"
    assert pn.kind_of("202600") == pn.NAME_YEARLY, pn.kind_of("202600")
    ok, refusals, warnings = pn.validate("202600_To-be-checked",
                                         kind=pn.NAME_YEARLY)
    assert ok and not refusals, refusals
    assert not warnings, ("a new yearly bucket was warned as a legacy "
                          "name: %s" % warnings)


def case_a_yearly_head_is_told_apart_by_its_zero_month():
    """GUARD. `00` is never a month, so it is what separates the yearly form
    from a legacy `YYYYMM` of the same six-digit length — and an EIGHT-digit
    head can never be yearly, whatever its last four digits say."""
    assert pn.kind_of("202606") == pn.NAME_MONTHLY, "legacy June 2026 moved"
    assert pn.kind_of("20260700") == pn.NAME_MONTHLY, "a dated bucket moved"
    # ⛔ the Lead's reverse pin: eight digits, trailing zeros, still NOT yearly
    assert pn.kind_of("20260000") != pn.NAME_YEARLY, pn.kind_of("20260000")
    assert pn.kind_of("20260506") == pn.NAME_FOLDER, pn.kind_of("20260506")
    # a legacy June 2026 still WARNS, exactly as it did before
    _ok, _r, warnings = pn.validate("202606_others", kind=pn.kind_of("202606"))
    assert warnings, "a legacy YYYYMM name stopped warning"
    # and a yearly head handed to the MONTHLY check is refused, never accepted
    ok, refusals, _w = pn.validate("202600_others", kind=pn.NAME_YEARLY)
    assert ok, refusals
    ok, refusals, _w = pn.validate("2026_others", kind=pn.NAME_YEARLY)
    assert not ok and refusals, "a four-digit year passed as yearly"


def case_a_new_no_date_bucket_is_one_of_three_forms():
    """REPRODUCTION (M14). The no-date plan was never name-checked at all —
    `write_no_date_plan` did not call `validate()` — so any string a route
    produced reached the drive unchecked. A NEWLY WRITTEN no-date bucket is now
    one of exactly three forms, and anything else is refused.

    ⛔ The bucket WORD is a parameter, never a literal: it comes from the
    owner pack's language table at runtime (Rule 8), so this case passes the
    English table's word and would pass any other the same way."""
    assert hasattr(pn, "bucket_form"), "there is no no-date bucket check"
    word = "To-be-checked"
    assert pn.bucket_form(f"20260700_{word}", word) == pn.NAME_MONTHLY
    assert pn.bucket_form(f"202600_{word}", word) == pn.NAME_YEARLY
    # ⛔ the Lead's pin: the undated stills bucket passes, and is NOT warned
    assert pn.bucket_form(f"_{word}", word) == pn.NAME_UNDATED
    for bad in (f"junk_{word}", f"_{word}_x", f"{word}", f"2026_{word}",
                f"202600_Other", f"__{word}"):
        assert pn.bucket_form(bad, word) is None, "%r was accepted" % bad


def case_an_already_written_span_bucket_is_not_a_new_form():
    """GUARD. `2018-2023_<word>` is golden group3's bucket, already on a
    drive, and it is never auto-renamed — the already-on-drive warning path
    owns it. It is not one of the forms a NEW bucket may take, so it must not
    be quietly accepted here as if it were."""
    word = "To-be-checked"
    assert pn.bucket_form(f"2018-2023_{word}", word) is None


def case_a_superseded_date_form_warns_and_is_never_refused():
    """⛔ The distinction this whole card turns on. 26 of the 132 names in the
    golden fixtures use a superseded form — the short `-DD` end (D8 replaced
    it) or a pre-D14 bucket. Those folders are ALREADY ON THE DRIVE. A
    validator that refuses history cannot be switched on at all, so it warns
    and renames nothing.

    A genuinely malformed name is still refused — otherwise this is not a
    validator, it is a comment."""
    ok, _, warnings = pn.validate("20260506-20", kind=pn.NAME_FOLDER)
    assert ok, "the superseded -DD end form was refused, not warned"
    assert warnings and "superseded" in warnings[0], warnings
    ok, refusals, _ = pn.validate("not-a-date_Place", kind=pn.NAME_FOLDER)
    assert not ok and refusals, "a malformed name passed"


def case_a_leg_omits_its_place_only_when_it_is_the_parents():
    """⭐ REPRODUCTION (D-I13). ⛔ FAILS on c6f0ea7: `validate()` took no place
    for a leg, so a leg that dropped a place DIFFERENT from its parent's passed
    (R12 never ran on a leg). A leg at the parent's own place may leave
    `[where]` out; one elsewhere must carry it; slot 2 holding a `[what]` is
    not a `[where]` (words compared, never slots counted)."""
    ok, refusals, _ = pn.validate("1211_street cats", kind=pn.NAME_LEG,
                                  where=["Harbour"], parent_where=["Harbour"])
    assert ok, f"a leg at its parent's place was refused: {refusals}"
    ok, refusals, _ = pn.validate("1026_lake walk", kind=pn.NAME_LEG,
                                  where=["Brookvale"], parent_where=["Northland"])
    assert not ok and "D-I13" in refusals[0], "a leg dropped a different place and passed"
    ok, refusals, _ = pn.validate("1026_Brookvale_lake walk", kind=pn.NAME_LEG,
                                  where=["Brookvale"], parent_where=["Northland"])
    assert ok, f"a leg that names its own place was refused: {refusals}"
    ok, refusals, _ = pn.validate("0310-0311_Fenwick+Ashford", kind=pn.NAME_LEG,
                                  where=["Fenwick", "Ashford"], parent_where=["Northland"])
    assert ok, f"a two-place leg was refused: {refusals}"


def case_a_hand_written_leg_is_unchanged():
    """GUARD. With no place words (every hand-written plan, every golden leg)
    the D-I13 rule is not armed: the result is what it was."""
    for name in ("0506-0509_Place+Other", "0513-0517", "1211_street cats"):
        assert pn.validate(name, kind=pn.NAME_LEG) == pn.validate(
            name, kind=pn.NAME_LEG, where=None, parent_where=["X"]), name


def case_render_writes_the_three_period_forms():
    """REPRODUCTION. ⛔ FAILS on c6f0ea7: `render()` wrote only a FOLDER period,
    so no leg (`MMDD`) or monthly parent (`YYYYMM00`) could be rendered."""
    assert pn.render("2024-10-29", "2024-10-30", where=["Dunmore"],
                     kind=pn.NAME_LEG) == "1029-1030_Dunmore"
    assert pn.render("2024-12-11", what="street cats", kind=pn.NAME_LEG) == "1211_street cats"
    assert pn.render("2024-12-11", "2024-12-26", where=["Harbour"],
                     kind=pn.NAME_MONTHLY) == "20241200_Harbour"
    assert pn.render("2024-10-25", "2024-10-31", where=["Northland"],
                     what="autumn") == "20241025-1031_Northland_autumn"


CASES = [
    ("a leg omits its place only when it is the parent's (D-I13 REPRODUCTION)",
     case_a_leg_omits_its_place_only_when_it_is_the_parents),
    ("a hand-written leg is unchanged (D-I13 GUARD)",
     case_a_hand_written_leg_is_unchanged),
    ("render writes the three period forms (REPRODUCTION)",
     case_render_writes_the_three_period_forms),
    ("a leg name is not a folder name (REPRODUCTION)",
     case_a_leg_name_is_not_a_folder_name),
    ("a monthly bucket carries its zero day field",
     case_a_monthly_bucket_carries_its_zero_day_field),
    ("a superseded date form warns and is never refused",
     case_a_superseded_date_form_warns_and_is_never_refused),
    ("a multi-day batch cannot be named with one day (REPRODUCTION)",
     case_a_multi_day_batch_cannot_be_named_with_one_day),
    ("a span end is a full MMDD across a month boundary",
     case_a_span_end_is_a_full_mmdd_across_a_month_boundary),
    ("a backwards or unparseable span is refused, not rendered",
     case_a_backwards_span_is_refused_not_rendered),
    ("a known place may not be dropped from the name (REPRODUCTION)",
     case_a_known_place_may_not_be_dropped_from_the_name),
    ("the N-2 budget counts what the SPEC says it counts",
     case_the_n2_budget_counts_what_the_spec_says_it_counts),
    ("[period] and [where] never consume budget",
     case_period_and_where_never_consume_budget),
    ("[who] is repeatable and is not capped at one",
     case_who_is_repeatable_and_is_not_capped_at_one),
    ("the hard cap refuses and the soft cap only warns",
     case_the_hard_cap_refuses_and_the_soft_cap_only_warns),
    ("[what] is never checked against a list (D-F11 GUARD)",
     case_the_what_slot_is_never_checked_against_a_list),
    ("the soft budget is {16}, not {12} (REPRODUCTION)",
     case_the_soft_budget_is_sixteen_not_twelve),
    ("M14 — a yearly bucket is its own kind and not legacy",
     case_a_yearly_bucket_is_its_own_kind_and_not_legacy),
    ("M14 — a yearly head is told apart by its zero month",
     case_a_yearly_head_is_told_apart_by_its_zero_month),
    ("M14 — a new no-date bucket is one of three forms",
     case_a_new_no_date_bucket_is_one_of_three_forms),
    ("M14 — an already-written span bucket is not a new form",
     case_an_already_written_span_bucket_is_not_a_new_form),
]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose
    passed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            print(f"  FAIL  {name}\n        {e}")
        except Exception as e:                            # noqa: BLE001
            print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
        else:
            print(f"  ok    {name}")
            passed += 1
    print(f"\n{passed}/{len(CASES)} photo_name cases passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
