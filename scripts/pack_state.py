#!/usr/bin/env python3
"""EV-9 — a run that does not print the pack state it ran under is not
admissible evidence.

    "Every replay and every Tier 3 run must print, in its report header: the
     run type [...], the pack slug, whether the pack was empty, and its
     snapshot id."   — Evaluation SPEC, EV-9

The elision is a cross-reference to EV-1, deliberately not carried across: see
*Two different questions* below for why importing it here would import a
confusion rather than a rule.

This module is the ONE implementation of that rule. It started life inside
`tests/see_replay.py`, which is still its loudest caller; it lives here so
every replay states its pack under the same rules and a second copy cannot
drift away from the first.

It sits in `scripts/` rather than `tests/` for one reason: `scripts/photo_run.py`
prints this header on a real Tier 3 run, and engine code must not import from
the test tree. The dependency runs one way — this module needs `photo_profile`
and nothing else.

## Why this is a guard and not a print statement

The blank profile a benchmark runs against holds today by a literal in one
function, not by a check. An edit that wires `--profile` in for convenience
would silently destroy every benchmark number with nothing failing, and the
number it produced would look exactly like a cold-start number. So
`pack_state()` REFUSES to label a run a benchmark while the pack holds owner
facts — the label and the assertion are one call, because two calls can be
half-applied.

## Two different questions, both in the header, never merged

  * `run_type` — WHICH TIER of evidence this run is. Supplied explicitly by
    every caller (see `RUN_TYPES`); there is no default, because a tier that
    can be forgotten is a tier that gets misquoted.
  * `mode` — a benchmark run (empty pack, comparable across runs) versus a
    run against a configured pack. This is the distinction the Evaluation
    SPEC's EV-1 draws, and it is what EV-8 means by "the run type from EV-1".

They are not the same axis: a Tier 2 replay can be either mode, and a Tier 1
suite is neither a benchmark nor an owner run. Reporting one as the other is
the mistake the whole tier framing exists to prevent.
"""

import json
import os

import photo_profile

# The cold-start owner a benchmark runs as. A name, not None: an unbound run
# and a new owner's empty pack are different cases by design (photo_profile
# .buckets()), and the benchmark has to be the second one.
BENCHMARK_OWNER = "BetaUser00"

# photo-profile.json keys that may legitimately hold a value on a blank sheet.
# Everything else in the profile is a FACT ABOUT THE OWNER — where they live,
# what they shoot with, what their folders are called — and a benchmark that
# starts with any of it is not a cold start. `_`-prefixed keys are the
# template's own comments. `language` is a rendering choice made at
# onboarding, not knowledge about the photos; `cluster_defaults`/`sampling`
# are engine thresholds that ship in the template.
BLANK_SHEET_ALLOWED = {"owner", "language", "cluster_defaults", "sampling",
                       "visual_sorting"}
# ...with one exception nested a level down: the scene label set IS owner
# vocabulary (ONB-10), so it must be empty even though its parent is config.
BLANK_SHEET_NESTED_FACTS = (("visual_sorting", "scene_labels"),)

# The tiers of evidence, as the Evaluation SPEC's tier table draws them. A
# caller names one of these keys; an unknown key raises rather than printing a
# header nobody can interpret.
#
# ⛔ These are TIERS, not EV-1's run type. EV-1 splits a benchmark run from an
# owner run, and that axis is `mode` below. Do not relabel one as the other:
# a header that calls a tier "the EV-1 run type" invents a cross-reference the
# SPEC does not make.
TIER1_FIXTURE = "tier-1-fixture"
TIER2_REPLAY = "tier-2-replay"
TIER3_DUMP = "tier-3-dump"
RUN_TYPES = {
    TIER1_FIXTURE: "Tier 1 (frozen fixture, pass/fail)",
    TIER2_REPLAY: "Tier 2 (replay measurement)",
    TIER3_DUMP: "Tier 3 (new-dump judgement)",
}


def resolve_pack_ignoring_env(workdir=None, explicit=None):
    """`photo_profile.resolve_pack()` with $PHOTO_PROFILE taken out of the way.

    A harness resolves a pack to REPORT it, and the operator's shell must not
    be able to answer that question. `resolve_pack()` reads $PHOTO_PROFILE
    when no explicit path is given, so a machine with the variable exported
    would have every header name the operator's own pack while the run itself
    used the fixture's — a header that describes a different run than the one
    that produced the numbers is worse than no header."""
    before = os.environ.pop(photo_profile.ENV_VAR, None)
    try:
        return photo_profile.resolve_pack(workdir=workdir, explicit=explicit)
    finally:
        if before is not None:
            os.environ[photo_profile.ENV_VAR] = before


def has_content(value):
    """Is there an actual owner fact in here? A container of empty containers
    is still a blank sheet — the template ships `"naming_spec": {"types": []}`,
    which is scaffolding, not knowledge."""
    if isinstance(value, dict):
        return any(has_content(v) for k, v in value.items()
                   if not str(k).startswith("_"))
    if isinstance(value, (list, tuple, set)):
        return any(has_content(v) for v in value)
    return bool(value)


def owner_facts_in(pack):
    """-> sorted list of the owner facts a pack holds. Empty = a blank sheet.

    Three places carry them: the profile's fact keys, photo-entities.json
    (people / pets / places), and photo-subjects/ (visual exemplars — a
    learned identity is a fact even when it has no name yet)."""
    found = []
    for key, value in sorted((pack.profile or {}).items()):
        if key.startswith("_") or key in BLANK_SHEET_ALLOWED:
            continue
        if has_content(value):
            found.append(f"photo-profile.json:{key}")
    for parent, child in BLANK_SHEET_NESTED_FACTS:
        if photo_profile.get(pack.profile, parent, child):
            found.append(f"photo-profile.json:{parent}.{child}")
    if pack.dir and pack.dir.is_dir():
        entities = pack.dir / "photo-entities.json"
        if entities.exists():
            try:
                data = json.loads(entities.read_text())
            except json.JSONDecodeError as exc:
                found.append(f"photo-entities.json is unreadable ({exc})")
                data = {}
            for key, value in sorted(data.items()):
                # `owner` is the pack's IDENTITY block ({"slug", "display"}),
                # not knowledge about the photos — every pack carries one,
                # including an empty one, and `BetaUser00` is a named cold-start
                # owner by design (N-11). Exempt for the same reason it is
                # already exempt on the profile side; without this the guard
                # rejected the very pack the benchmark is supposed to run.
                #
                # Deliberately NOT the whole BLANK_SHEET_ALLOWED set: that also
                # holds `visual_sorting`, which only earns its exemption on the
                # profile side because BLANK_SHEET_NESTED_FACTS re-catches
                # `visual_sorting.scene_labels` as owner vocabulary (ONB-10).
                # There is no such nested check here, so a blanket exemption
                # would open a leak channel in a leak guard.
                if key == "owner":
                    continue
                if not key.startswith("_") and has_content(value):
                    found.append(f"photo-entities.json:{key}")
        subjects_dir = pack.dir / "photo-subjects"
        if subjects_dir.is_dir():
            # Count what the registry actually KNOWS, not how many files sit in
            # the directory. The template ships an empty `subjects.json`, which
            # is scaffolding in exactly the sense `has_content()` already
            # forgives for `"naming_spec": {"types": []}`; counting it as an
            # exemplar made every freshly created pack non-blank.
            subjects = []
            registry_file = subjects_dir / "subjects.json"
            if registry_file.exists():
                try:
                    subjects = json.loads(registry_file.read_text()).get(
                        "subjects") or []
                except json.JSONDecodeError as exc:
                    found.append(f"photo-subjects/subjects.json is unreadable ({exc})")
                    subjects = [{}]          # unreadable is not "blank"
            # Anything else under photo-subjects/ is still treated as owner
            # knowledge — the conservative default is kept deliberately. The ONE
            # exemption is an EMPTY subjects.json, which is template
            # scaffolding in exactly the sense has_content() already forgives
            # for `"naming_spec": {"types": []}`.
            stray = [p for p in subjects_dir.rglob("*")
                     if p.is_file() and p.name != ".gitkeep"
                     and not (p == registry_file and not subjects)]
            if subjects:
                # A subject with no exemplars is still a learned identity, and a
                # learned identity is an owner fact even before it has a name.
                exemplars = sum(len(s.get("exemplars") or []) for s in subjects)
                found.append(f"photo-subjects/ holds {len(subjects)} subject(s), "
                             f"{exemplars} exemplar(s)")
            elif stray:
                found.append(f"photo-subjects/ holds {len(stray)} file(s)")
    return sorted(found)


def assert_blank_sheet(pack, expected_owner):
    """A benchmark scores a cold start, so the pack it runs against must be a
    NAMED owner holding nothing. Raises rather than warning: a benchmark that
    silently ran with the owner's real knowledge in the pack produces a number
    that looks like the cold-start number and is not one — that is worse than
    no number at all."""
    if not pack.owner:
        raise AssertionError(
            "a benchmark needs a named cold-start owner and no pack resolved. "
            f"Create one from templates/photo-memory/_template as "
            f"{expected_owner!r} and pass --profile, or set collection.json's "
            "owner. 'No pack at all' is a different case from 'a new owner's "
            "empty pack' and the benchmark must be the second.")
    if pack.owner != expected_owner:
        raise AssertionError(
            f"a benchmark expects owner {expected_owner!r} but the resolved pack "
            f"belongs to {pack.owner!r} ({pack.source}). The real owner's pack is "
            "hidden ground truth, scored after the run and never loaded into it.")
    leaked = owner_facts_in(pack)
    if leaked:
        raise AssertionError(
            f"the benchmark pack {pack.owner!r} is NOT a blank sheet — "
            f"{len(leaked)} owner fact(s) leaked in: " + ", ".join(leaked) +
            ". A cold-start score measured with prior knowledge in the pack is "
            "not a cold-start score.")
    return True


def pack_state(pack, benchmark, run_type, benchmark_owner=BENCHMARK_OWNER):
    """-> a dict for the JSON and a one-line string for the report header.

    `run_type` is one of RUN_TYPES and has NO default: which tier of evidence
    a number belongs to is the thing readers get wrong, so a caller has to say
    it out loud. An unknown value raises here rather than reaching a reader.

    When `benchmark` is set this also ENFORCES the blank sheet — the label and
    the check are deliberately the same call. A separate `assert_blank_sheet()`
    beside a `pack_state()` can be dropped in one edit, leaving a header that
    says "benchmark (cold start)" over a pack full of owner knowledge.
    """
    if run_type not in RUN_TYPES:
        raise ValueError(
            f"unknown run type {run_type!r} — pass one of "
            f"{sorted(RUN_TYPES)}. EV-9 requires the report header to name "
            "which tier of evidence produced these numbers; a run that cannot "
            "name its tier is not admissible evidence.")
    if benchmark:
        assert_blank_sheet(pack, benchmark_owner)
    snap = pack.snapshot() if pack.dir else None
    facts = owner_facts_in(pack) if (pack.owner or pack.profile) else []
    state = {
        "run_type": run_type,
        "run_type_label": RUN_TYPES[run_type],
        "mode": "benchmark (cold start)" if benchmark else "as-configured",
        "owner": pack.owner,
        "source": pack.source or "no pack — engine defaults only",
        "snapshot": snap,
        "owner_facts": facts,
        "blank_sheet": bool(pack.owner) and not facts,
    }
    body = ("pack: NONE — engine defaults only, no owner bound"
            if not pack.owner and not pack.profile else
            f"pack: owner={pack.owner or '(unnamed)'} "
            f"{'BLANK SHEET verified' if state['blank_sheet'] else f'{len(facts)} owner fact(s)'}")
    snap_clause = (f"snapshot {snap['id']} over {snap['files']} file(s)"
                   if snap else "snapshot n/a")
    line = f"[{RUN_TYPES[run_type]}] {body}, {snap_clause} [{state['mode']}]"
    return state, line
