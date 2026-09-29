#!/usr/bin/env python3
"""R11 + R12 — the folder-name renderer and its validator.

Until this module existed `photo_plan.py` accepted whatever string the naming
agent typed into `plans.json`. Nothing assembled a name from parts and nothing
checked one, so the grammar in the SPEC was a convention the agent was trusted
to follow — and in UAT01 it did not: 9 of 11 folders carried a single-day date
for a multi-day span, and 6 of 11 dropped `[where]` while a resolved place name
was sitting on disk in `batches.json`.

⛔ Stdlib only, and deliberately not inside `photo_plan.py`. The rules here are
read by the plan stage, by its SKILL and by any future renderer; a name is a
grammar, not a step in one pipeline.

## The grammar (SPEC v0.7, signed)

    one day     YYYYMMDD_[where]_[who]_[what]
    a span      YYYYMMDD-MMDD_[where1+where2...]_[who]_[what]

`[period]` is always first and `[where]` second (D-F field priority, re-confirmed
at N-5). ⛔ N-5 is explicit that the elastic budget is spent on `[who]`/`[what]`
and that this is **not** a permission to drop `[where]`.

The end of a span is a full `MMDD`, never a bare `-DD` (D8): the short form is
ambiguous across a month boundary, where `20260429-03` cannot be read.

## The N-2 budget

Counts `[who]` + `[what]` ONLY — `[period]` and `[where]` are fixed cost and
are never counted. Full-width/CJK is counted per CHARACTER; latin script is
counted per WORD ("play in Central park" = 4). Separators are punctuation and
consume nothing: neither the `_` between slots nor the `+` between names.

Hard `{20}` = the refusal point, soft `{16}` = what the generator aims for.
📐 Both are `{n}` parameters and arrive from the pack, never constants here.

⛔ `[what]` IS OPEN FREE TEXT AND IS NEVER CHECKED AGAINST A LIST (D-F11).
The owner pack may carry a list of the owner's own phrases — read it with
`photo_profile.what_reference()` — and it is a REFERENCE for whoever writes
the name, never a boundary on what they may write. A membership check on that
slot would turn `[what]` back into the closed `[type]` taxonomy it is
explicitly not, which is why `validate()` takes no vocabulary argument and
must never be given one.
"""
import re
import unicodedata

# 📐 `{n}` parameters — pack-overridable, listed here only so the module has a
# working default when no pack is bound (a benchmark, or a first run).
DEFAULT_NAME_BUDGET_HARD = 20
# D-F13, signed 20260906: the soft target is {16}, not the {12} this shipped
# with. ⛔ NOTHING IS DROPPED TO FIT — the limit was RAISED instead, because
# N-2 counts Latin per WORD and CJK per CHARACTER, so the worst realistic
# English name is 6 units and 12 was only ever exceeded in Chinese with three
# subject names plus a descriptive phrase. A soft target that fires on
# correct names teaches its reader to ignore it.
DEFAULT_NAME_BUDGET_SOFT = 16

SLOT_SEP = "_"
NAME_SEP = "+"

# ⛔ Character CLASSES, not a word list. Rule 8 forbids hardcoding any locale's
# vocabulary in engine code; a unicode range is not vocabulary, it is how the
# SPEC's own "full-width counted individually, English counted in words" rule is
# expressed for every language at once. `unicodedata.east_asian_width` gives
# 'W' (wide) and 'F' (fullwidth) for exactly the characters the SPEC means by
# its full-width rule.
WIDE_WIDTHS = ("W", "F")
LATIN_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def is_wide(ch):
    return unicodedata.east_asian_width(ch) in WIDE_WIDTHS


def budget_units(text):
    """-> how many N-2 units this slot's text costs.

    A wide character is one unit. A run of narrow script is one unit per WORD.
    ⛔ Separators cost nothing — they are punctuation, not units — so a folder
    naming three subjects is not penalised for joining them.
    """
    if not text:
        return 0
    units, narrow = 0, []
    for ch in text:
        if ch in (SLOT_SEP, NAME_SEP):
            # ⛔ Replaced by a space, never dropped. Deleting the separator
            # JOINS the words on either side of it, so two subjects joined by
            # `+` counted as one unit — the budget then under-charged exactly
            # the slot N-2 exists to bound, and `[who]` is the repeatable one.
            narrow.append(" ")
            continue
        if is_wide(ch):
            units += 1
        else:
            narrow.append(ch)
    return units + len(LATIN_WORD.findall("".join(narrow)))


def period(start, end=None):
    """-> the `[period]` slot. `start`/`end` are `YYYY-MM-DD` strings.

    One day, or a span whose end repeats the start day -> `YYYYMMDD`.
    A span -> `YYYYMMDD-MMDD`, the end in FULL MMDD (D8).

    ⛔ The end is never abbreviated to `-DD`. `20260429-03` cannot be read: it
    is unresolvable across a month boundary, which is precisely when a trip
    most needs a readable name.
    """
    if not start:
        raise ValueError("a folder name always carries a period — D-F puts it "
                         "first and N-5 makes it fixed cost, never optional")
    s = start.replace("-", "")
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"start is not YYYY-MM-DD: {start!r}")
    if not end:
        return s
    e = end.replace("-", "")
    if len(e) != 8 or not e.isdigit():
        raise ValueError(f"end is not YYYY-MM-DD: {end!r}")
    if e < s:
        raise ValueError(f"the span ends before it starts: {start} -> {end}")
    if e == s:
        return s
    return f"{s}-{e[4:]}"


def render(start, end=None, where=(), who=(), what=None, kind=None):
    """-> the assembled folder name.

    `where` and `who` are SEQUENCES, joined with `+`. ⛔ `who` is a REPEATABLE
    slot and is never capped at one (SPEC v0.7 as amended 20260904): three
    subjects in one folder name is normal. Any cap belongs to the caller and is
    a parameter, not a rule of the grammar.

    `kind` picks the period form: a FOLDER `YYYYMMDD[-MMDD]` (the default), a
    LEG `MMDD[-MMDD]` (its parent carries the year), or a MONTHLY `YYYYMM00`
    (from `start`'s month; `end` is ignored).
    """
    head = period(start, end)
    if kind == NAME_LEG:
        head = head[4:]
    elif kind == NAME_MONTHLY:
        head = head[:6] + "00"
    slots = [head]
    for seq in (where, who):
        joined = NAME_SEP.join(str(x) for x in seq if x)
        if joined:
            slots.append(joined)
    if what:
        slots.append(str(what))
    return SLOT_SEP.join(slots)


# The three kinds of name this grammar covers. ⛔ They are NOT variations of
# one pattern and a validator that assumes they are will refuse correct names:
# measured against the 7 golden fixtures, treating every name as a FOLDER
# refused 32 of 132, and most of those were right all along.
#
#   FOLDER   `YYYYMMDD_...` or `YYYYMMDD-MMDD_...` — the trip or event folder
#   LEG      `MMDD` or `MMDD-MMDD` — a SUB-folder inside a multi-day trip
#            parent, which the SPEC's grammar line calls "sub-folders by leg".
#            It carries no year because its parent already does.
#   MONTHLY  `YYYYMM00_...` — D14's monthly bucket. The `00` day field is
#            deliberate: it sorts inside the same month group as the daily
#            folders instead of ahead of or behind all of them.
#   YEARLY   `YYYY00_...` — the no-date VIDEO bucket (M14, owner ruling
#            20260922): one per year, the year taken from the file's own
#            `FileModifyDate`. ⛔ The `00` is not a month and cannot be one —
#            that is exactly what tells it apart from a legacy `YYYYMM` of the
#            same six-digit length. See `kind_of()`.
NAME_FOLDER = "folder"
NAME_LEG = "leg"
NAME_MONTHLY = "monthly"
NAME_YEARLY = "yearly"
# UNDATED  `_<bucket>` — the ONE no-EXIF stills bucket (M14, owner rulings
#          Q9/Q10, 20260922). It carries NO period at all, by design: a
#          no-EXIF still's timestamp is when it reached the disk, so no folder
#          it lands in may claim a year. The leading underscore is a symbol,
#          not a word, so it adds nothing to translate (Rule 8).
NAME_UNDATED = "undated"

# ⚠️ `-DD` is the SUPERSEDED short end form (D8 replaced it with a full MMDD
# because `20260429-03` cannot be read across a month boundary). It is
# accepted as a WARNING, never a refusal: 17 names already on the owner's
# drive use it, and a validator that refuses history cannot be switched on.
PERIOD_PATTERNS = {
    NAME_FOLDER: r"\d{8}(-\d{4})?",
    NAME_LEG: r"\d{4}(-\d{4})?",
    NAME_MONTHLY: r"\d{6}00",
    # SIX characters, fullmatched — so an eight-digit head can never be read
    # as yearly, whatever its trailing digits say.
    NAME_YEARLY: r"\d{4}00",
}
# ⚠️ `YYYYMM` with no `00` is the PRE-D14 monthly form. Folders in it are
# still on the drive and are renamed only by hand, so it warns too.
LEGACY_PATTERNS = {
    NAME_FOLDER: r"\d{8}-\d{2}",
    NAME_LEG: r"\d{4}-\d{2}",
    NAME_MONTHLY: r"\d{6}(-\d{6})?",
}


RE_YEARLY_HEAD = re.compile(r"\d{4}00")
RE_MONTHLY_HEAD = re.compile(r"\d{6}(00)?(-\d{6})?")
EXPECTED_FORM = {NAME_FOLDER: "YYYYMMDD or YYYYMMDD-MMDD",
                 NAME_LEG: "MMDD or MMDD-MMDD",
                 NAME_MONTHLY: "YYYYMM00",
                 NAME_YEARLY: "YYYY00"}


def kind_of(head):
    """-> which kind of name a period HEAD belongs to.

    ⛔ ONE predicate. The kind used to be decided inline by a regex inside
    `photo_plan`, and that regex read `202600` as MONTHLY — whose only match
    for six digits is the LEGACY pre-D14 `YYYYMM` pattern — so the engine
    would have warned about its own new yearly output as a superseded name.

    ⛔ YEARLY is tested FIRST, and the test is the zero month: `00` is never a
    month, so it is what separates `202600` (yearly) from `202606` (a legacy
    June) at the same length. Fullmatch keeps an eight-digit head such as
    `20260000` out of yearly entirely.
    """
    # ⛔ Deliberately NOT restricted to a plausible year. A golden sweep found
    # six strings this reads as yearly — `093400`, `182800` and four more — and
    # all six are TIMES inside filenames (`20211212_093400_capture.jpg`), never
    # a folder's first segment. This is only ever called on a folder head, so
    # narrowing the pattern would guard a path no caller takes. Measured
    # 20260922: of those six, 0 appear as a folder's first segment in any
    # golden destination path. Do not "fix" it.
    if RE_YEARLY_HEAD.fullmatch(head):
        return NAME_YEARLY
    if RE_MONTHLY_HEAD.fullmatch(head):
        return NAME_MONTHLY
    return NAME_FOLDER


def bucket_form(top, word):
    """-> the kind of a NEWLY WRITTEN no-date bucket, or None to refuse it.

    `top` is the bucket's top-level folder name and `word` is the bucket word
    from the owner pack's language table — ⛔ a parameter, never a literal, so
    no language is baked in (Rule 8).

    Exactly three forms, and nothing else:
      MONTHLY  `YYYYMM00_<word>` — a dated bucket (D14)
      YEARLY   `YYYY00_<word>`   — a no-EXIF video, by its file date
      UNDATED  `_<word>`         — the one no-EXIF stills bucket, no year

    ⛔ The no-date plan was never name-checked before this: `write_no_date_plan`
    did not call `validate()`, so whatever a route produced reached the drive.
    ⛔ A span such as `2018-2023_<word>` is NOT accepted here. It is golden
    group3's bucket, already on a drive; the already-on-drive warning path owns
    it and it is never auto-renamed — but it is not a form a NEW bucket takes.
    """
    if top == f"_{word}":
        return NAME_UNDATED
    head, sep, rest = top.partition("_")
    if not sep or rest != word:
        return None
    kind = kind_of(head)
    return kind if kind in (NAME_MONTHLY, NAME_YEARLY) and re.fullmatch(
        PERIOD_PATTERNS[kind], head) else None


def validate(name, place_known=False, span=None, hard=None, soft=None,
             kind=NAME_FOLDER, where=None, parent_where=None):
    """-> (ok, [refusals], [warnings]).

    A refusal means the name must not be written. A warning means it may be,
    and something should be said.

    ⛔ `place_known` is the whole point of R12's first rule. In UAT01 six of
    eleven folders had a resolved place name sitting on disk in `batches.json`
    and used none of it. A name with no `[where]` is only acceptable when the
    engine genuinely could not name the place — never when it could and the
    agent simply did not ask.

    D-I13 — a LEG names its place only when it differs from its parent's.
    `where` is the leg's place words and `parent_where` its parent's. When
    they differ, slot 2 must BE the leg's words. ⛔ Compared as words, never by
    counting slots: `1211_street cats` has two slots and no `[where]`. When
    they are equal the leg may leave the place out. With no `where` (a
    hand-written plan) the rule is not armed.
    """
    hard = DEFAULT_NAME_BUDGET_HARD if hard is None else hard
    soft = DEFAULT_NAME_BUDGET_SOFT if soft is None else soft
    refusals, warnings = [], []
    if not name:
        return False, ["the name is empty"], []
    slots = name.split(SLOT_SEP)
    head = slots[0]
    pattern = PERIOD_PATTERNS.get(kind, PERIOD_PATTERNS[NAME_FOLDER])
    legacy = LEGACY_PATTERNS.get(kind)
    if legacy and re.fullmatch(legacy, head):
        warnings.append(
            f"`{head}` uses a superseded date form. D8 asks for a span's end "
            "in full (a short `-DD` cannot be read across a month boundary) "
            "and D14 asks a monthly bucket for its `00` day field, so it "
            "sorts inside its month rather than ahead of it. ⛔ A warning, "
            "never a refusal: folders in these forms are already on the "
            "drive, and nothing here renames them.")
    elif not re.fullmatch(pattern, head):
        refusals.append(
            f"`{head}` is not a {kind} period — expected "
            f"{EXPECTED_FORM.get(kind, EXPECTED_FORM[NAME_FOLDER])}"
            " (D8/D14/D-F/M14)")
    elif span and kind == NAME_FOLDER:
        # ⛔ This is what makes the date form ENFORCEABLE rather than a
        # convention. The renderer can produce a correct span and the agent can
        # still type a single day over it — which is exactly what happened: 9
        # of 11 UAT01 folders carried a one-day period for a batch that ran for
        # several. Checked against the batch's own dates, so a name cannot
        # silently disagree with the files inside it.
        want = period(*span)
        if head != want:
            refusals.append(
                f"the period `{head}` does not describe this batch — it runs "
                f"{span[0]} to {span[1]}, so the period is `{want}`")
    if place_known and kind == NAME_FOLDER and len(slots) < 2:
        refusals.append(
            "the place is known for this batch but the name carries no "
            "[where] — N-5 spends the elastic budget on [who]/[what] and is "
            "explicitly not a permission to drop [where]")
    if kind == NAME_LEG and where:
        words, parent = list(where), list(parent_where or ())
        named = slots[1].split(NAME_SEP) if len(slots) > 1 else []
        if words != parent and named != words:
            refusals.append(
                f"this leg is at {NAME_SEP.join(words)}, not its parent's "
                f"{NAME_SEP.join(parent) or '(no place)'}, and the name does "
                "not say so — a leg leaves [where] out only when it is the "
                "parent's (D-I13)")
    # ⛔ [period] and [where] are fixed cost and are NOT counted (N-2).
    counted = SLOT_SEP.join(slots[2:]) if len(slots) > 2 else ""
    units = budget_units(counted)
    if units > hard:
        refusals.append(
            f"[who]+[what] is {units} units against a hard cap of {hard} "
            f"(N-2; [period] and [where] are not counted)")
    elif units > soft:
        warnings.append(
            f"[who]+[what] is {units} units against a soft target of {soft} "
            f"(N-2; the hard cap is {hard})")
    return not refusals, refusals, warnings
