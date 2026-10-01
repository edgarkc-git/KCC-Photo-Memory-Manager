#!/usr/bin/env python3
"""Photo memory pack loader — every fact about a photo OWNER that the engine
needs but must never contain: home locations, pets and people, language,
naming vocabulary, clustering and sampling thresholds.

The engine ships with zero owner facts. A pack lives outside this repo, on the
operator's own machine, one folder per owner:

    photo-memory/
      <owner-slug>/
        photo-owner-<owner-slug>.md   narrative anchor file (Phase C)
        photo-profile.json        machine config — the only file Phase A reads
        photo-entities.json       people / pets / places / scenes (Phase C)
        photo-subjects/           visual exemplars (Phase D)
        photo-memory-log.md       append-only audit journal
        photo-proposals.md        agent drafts, not yet human-confirmed

Layout and rationale: docs/photo-memory-pack.md

Resolution order
  1. --profile <path> on the calling script
  2. PHOTO_PROFILE environment variable (photo_run.py exports it once, so
     every script it shells out to inherits the same pack)
  3. collection.json -> "owner", resolved under "memory_root"
  4. nothing — the pipeline still runs on generic defaults

ISOLATION INVARIANT: one run loads exactly one owner's pack. A collection that
names an owner with no pack is a hard failure, never a silent fall-back to
whichever pack happens to be configured — mixing two people's photo memories
is worse than stopping. Likewise a --profile that disagrees with the
collection's owner stops the run.
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ENV_VAR = "PHOTO_PROFILE"
PROFILE_NAME = "photo-profile.json"
OWNER_GLOB = "photo-owner-*.md"
DEFAULT_PACK_DIRNAME = "photo-memory"

# Files whose content can change what a run produces, and therefore define the
# snapshot a replay has to pin. photo-memory-log.md is deliberately excluded:
# it is an audit trail, it never feeds a decision.
SNAPSHOT_PARTS = ("photo-profile.json", "photo-entities.json",
                  "photo-proposals.md", OWNER_GLOB, "photo-subjects")

# ⛔ ONE file, excluded BY NAME, for the reason photo-memory-log.md is:
# `photo-subjects/memorize-audit.jsonl` is append-only provenance and no
# decision reads it back. Everything else under `photo-subjects/` — the
# records, the `.npy` vectors — is state and stays hashed.
#
# Measured 2026-08-20 (step 9, item 1): a REFUSED `confirm --go` writes
# nothing to the registry and still audits, because a refusal that leaves no
# trace is worse than one that moves a hash. With the audit inside the
# snapshot, that moved the pack id, so SNS-1b's pinned-snapshot check then
# refused the WHOLE of the page the engine had just refused a single row of —
# and the fresh page it advised the owner to render carried no questions.
# ⛔ Do not widen this into a general looseness: the pinned check is the
# fourth guard on the confirm write path and a permissive hash blinds it.
SNAPSHOT_EXCLUDE = ("memorize-audit.jsonl",)


class Pack:
    """A resolved owner pack. `owner` is None when the run has no pack at all,
    which is legal — the engine falls back to its own generic defaults."""

    def __init__(self, owner=None, directory=None, profile=None, source=None):
        self.owner = owner
        self.dir = Path(directory) if directory else None
        self.profile = profile or {}
        self.source = source          # how it was found, for the run log

    def __bool__(self):
        return bool(self.profile)

    def snapshot(self):
        """Content id over everything in the pack that can steer a run, so a
        golden replay can prove it ran against the same memory state.
        -> {"owner", "id", "files"} or None when there is no pack."""
        if not self.dir or not self.dir.is_dir():
            return None
        digest, count = hashlib.sha256(), 0
        for part in sorted(SNAPSHOT_PARTS):
            for path in sorted(self.dir.glob(part)):
                targets = ([path] if path.is_file()
                           else sorted(p for p in path.rglob("*") if p.is_file()))
                for p in targets:
                    if p.name in SNAPSHOT_EXCLUDE:
                        continue
                    digest.update(str(p.relative_to(self.dir)).encode())
                    digest.update(hashlib.sha256(p.read_bytes()).digest())
                    count += 1
        return {"owner": self.owner, "id": "sha256:" + digest.hexdigest()[:16],
                "files": count}


def find_collection(workdir=None):
    """collection.json sits beside the per-dump work dirs, i.e. one level above
    a work dir. -> (config dict, its path) or ({}, None)."""
    if not workdir:
        return {}, None
    for candidate in (Path(workdir).parent / "collection.json",
                      Path(workdir) / "collection.json"):
        if candidate.exists():
            return json.loads(candidate.read_text()), candidate
    return {}, None


def _pack_dir_of(profile_file):
    """A profile path may point inside a pack, or at a stand-alone legacy
    profile. Only the former has an owner anchor file next to it."""
    parent = Path(profile_file).parent
    return parent if any(parent.glob(OWNER_GLOB)) else None


def resolve_pack(workdir=None, explicit=None):
    """Find the one pack this run may use. Hard-fails on the two mistakes that
    matter: a named owner with no pack, and two sources naming different
    owners."""
    coll, coll_path = find_collection(workdir)
    coll_owner = coll.get("owner")

    given = explicit or os.environ.get(ENV_VAR)
    if given:
        given = Path(given)
        if given.is_dir():                       # a pack folder was passed
            given = given / PROFILE_NAME
        if not given.exists():
            sys.exit(f"profile not found: {given}")
        given_pack = _pack_dir_of(given)
        given_owner = given_pack.name if given_pack else None
        if coll_owner and given_owner and coll_owner != given_owner:
            sys.exit(f"owner conflict: collection.json says {coll_owner!r} but "
                     f"{given} belongs to {given_owner!r}. One run loads exactly "
                     "one owner's pack — fix the binding rather than mixing two "
                     "people's photo memories.")
        return Pack(owner=given_owner or coll_owner, directory=given_pack,
                    profile=json.loads(given.read_text()),
                    source=f"--profile/{ENV_VAR}: {given}")

    if not coll_owner:
        return Pack()

    root = coll.get("memory_root")
    root = (Path(root).expanduser() if root
            else coll_path.parent / DEFAULT_PACK_DIRNAME)
    pack_dir = Path(root) / coll_owner
    profile_file = pack_dir / PROFILE_NAME
    if not profile_file.exists():
        sys.exit(
            f"collection {coll.get('collection', str(coll_path))!r} is bound to "
            f"owner {coll_owner!r} but there is no pack at {profile_file}.\n"
            "Create it (see docs/photo-memory-pack.md) or set \"memory_root\" in "
            "collection.json. The engine will not fall back to another owner's "
            "pack.")
    return Pack(owner=coll_owner, directory=pack_dir,
                profile=json.loads(profile_file.read_text()),
                source=f"collection.json owner={coll_owner}")


# ---- backwards-compatible surface used by the existing pipeline scripts ----

def profile_path(explicit=None):
    if explicit:
        return Path(explicit)
    env = os.environ.get(ENV_VAR)
    return Path(env) if env else None


def load_profile(explicit=None, workdir=None):
    """The profile dict alone. A missing profile is not an error — the engine
    just has no owner context and uses its generic defaults."""
    if explicit or os.environ.get(ENV_VAR) or workdir:
        return resolve_pack(workdir=workdir, explicit=explicit).profile
    return {}


# Names for the buckets the ENGINE invents (as opposed to the folder names an
# agent writes into plans.json, which are used verbatim). These were hardcoded
# Traditional Chinese, so a first-time owner in any other language got Chinese
# folders they never asked for.
#
# Resolution: naming_spec.buckets (the owner typed it) -> the table for
# profile.language -> the strings the engine has always shipped, for a run
# with no pack at all. A pack created from the template says language "en", so
# "new owner" and "no owner" are deliberately NOT the same case: an unbound
# run keeps producing exactly what it produced yesterday.
# i18n-guard:allow-begin — a declared locale table: the one place non-English
# strings are allowed to live, because that is what this table IS.
BUCKET_VOCAB = {
    "zh-TW": {"screenshots": "截圖", "to_be_checked": "待分類",
              "others": "others", "ai_images": "AI-images"},
    "en": {"screenshots": "Screenshots", "to_be_checked": "To-be-checked",
           "others": "others", "ai_images": "AI-images"},
}
# i18n-guard:allow-end
LEGACY_BUCKET_LANGUAGE = "zh-TW"


_TABLE_MISSING_SAID = set()


def announce_missing_table(lang, vocab):
    """F7 / U3-26 — say, once per run, that a declared language has no table.

    The English fallback is right (Rule 8) and was silent, so an owner whose
    language did not take read English folder names as a fault in their pack.
    Once per language per process: four resolvers fire on every stage, and
    four identical lines read as four problems. English on purpose — the owner
    has no table to be told in. stderr, so no stdout a caller parses moves."""
    if lang in vocab or lang in _TABLE_MISSING_SAID:
        return
    _TABLE_MISSING_SAID.add(lang)
    print(f"⚠️ The owner pack's language is {lang!r}, and this engine has no "
          "word table for it, so the folders and labels it makes are in "
          f"English. Tables exist for: {', '.join(sorted(BUCKET_VOCAB))}. This "
          "is the documented fallback, not a fault in your pack — set "
          "`language` to one of those, or name the buckets yourself in "
          "naming_spec.buckets.", file=sys.stderr)


def buckets(profile):
    """-> {key: folder name} for one owner."""
    lang = get(profile, "language")
    if lang is None:
        table = BUCKET_VOCAB[LEGACY_BUCKET_LANGUAGE]
    else:
        # an unknown language falls to English rather than to Chinese: ASCII
        # is the least surprising thing to hand someone whose language the
        # engine has no table for
        announce_missing_table(lang, BUCKET_VOCAB)
        table = BUCKET_VOCAB.get(lang, BUCKET_VOCAB["en"])
    named = get(profile, "naming_spec", "buckets", default=None) or {}
    return {**table, **named}


# The names of the zero-shot SCENE classes photo_see.py ships as its fallback
# label set. The class IDS are ASCII and stable (`hiking`); what a human reads
# is resolved here, exactly like a bucket name, because a class name ends up in
# a report the owner reads and — for the classes that are also naming_spec
# types — in a folder name.
#
# `screenshots` is deliberately absent: it is a bucket the ENGINE also creates,
# so it resolves through buckets() and there is one string, not two that can
# drift. `document`/`whiteboard`/`food`/`AI-image-suspect` are absent too —
# they are utility classes, not owner vocabulary, and they route nothing.
#
# An owner pack that declares `visual_sorting.scene_labels` replaces the whole
# set, ids and prompts together (ONB-10), and never reaches this table.
#
# i18n-guard:allow-begin — a declared locale table: the one place non-English
# strings are allowed to live, because that is what this table IS.
# ⛔ THREE lists in this engine get called "the taxonomy" and they are three
# different things on two different axes. Naming them here because the
# confusion has produced a wrong remedy before — "fix the 11 down to 9" is
# NOT a fix, the 11 is not a longer version of anything:
#
#   photo_see.DEFAULT_SCENE_LABELS   11  CLIP prompt sets, keyed by class id.
#                                        The 6 below PLUS 5 utility detectors
#                                        (document, food, whiteboard,
#                                        screenshots, AI-image-suspect) that
#                                        exist to RECOGNISE an image and have
#                                        no owner-facing name at all.
#   SCENE_CLASS_VOCAB (here)          6  the display name of each NAMEABLE
#                                        scene class — the 11 minus the 5.
#   TYPE_VOCAB (below)               10  the `[type]` words that reach a
#                                        FOLDER NAME: these 6, `home` (an
#                                        ordinary day at home, W1C-7), and
#                                        the three engine buckets screenshot,
#                                        ai_generated, others.
#
# So: 11 = 6 + 5 utility, and 10 = 6 + `home` + 3 buckets. The 6 is the
# overlap and the only set that appears in all three.
SCENE_CLASS_VOCAB = {
    "zh-TW": {"hiking": "爬山", "overseas_trip": "出國旅遊", "day_trip": "一日遊",
              "dining": "聚餐", "cat": "小貓", "dog": "小狗"},
    "en": {"hiking": "Hiking", "overseas_trip": "Overseas trip",
           "day_trip": "Day trip", "dining": "Dining out", "cat": "Cat",
           "dog": "Dog"},
}
# i18n-guard:allow-end
LEGACY_SCENE_CLASS_LANGUAGE = "zh-TW"


def scene_classes(profile):
    """-> {class id: displayed name}. Same three-step resolution as buckets(),
    and the same reason for the legacy step: an unbound run must keep emitting
    the strings it emitted yesterday, or every replay comparison against a
    shipped decision silently stops matching."""
    lang = get(profile, "language")
    if lang is None:
        return dict(SCENE_CLASS_VOCAB[LEGACY_SCENE_CLASS_LANGUAGE])
    announce_missing_table(lang, SCENE_CLASS_VOCAB)
    return dict(SCENE_CLASS_VOCAB.get(lang, SCENE_CLASS_VOCAB["en"]))


# The `[type]` taxonomy — the CLOSED vocabulary a folder name's type slot may
# use. ⛔ NOT the same thing as SCENE_CLASS_VOCAB: that one is what the vision
# pass may SEE, this one is what a folder may be CALLED, and the naming SPEC
# keeps them apart on purpose.
#
# U2-06. This lived in `photo_classify_set.FALLBACK_TYPES` as a single
# Traditional-Chinese set with no other language, and `allowed_types()` fell
# back to it whenever the pack declared no `naming_spec.types` — which is every
# pack made from the template. An owner whose language is English was handed a
# Chinese taxonomy, and `photo_classify_set` does not merely PRINT it: it
# exits with "type must be one of: ..." for anything outside the set, so the
# owner was refused in a language they may not read. The waiver that let this
# past the guard claimed it was "the same pack-sourced default vocabulary as
# photo_see.py's"; both halves were false — it fires precisely BECAUSE the
# pack is empty, and photo_see's equivalent is scene_classes(), resolved here.
#
# i18n-guard:allow-begin — a declared locale table: the one place non-English
# strings are allowed to live, because that is what this table IS.
# The `[type]` vocabulary — 10 words, and ⛔ the VALUES are what
# `photo_classify_set.allowed_types()` validates against, never these keys.
# A key is the engine's stable id; the value is what the owner types and what
# reaches a folder name. See the three-list note above SCENE_CLASS_VOCAB.
TYPE_VOCAB = {
    "zh-TW": {"hiking": "爬山", "dining": "聚餐", "overseas_trip": "出國旅遊",
              "day_trip": "一日遊", "cat": "小貓", "dog": "小狗",
              "home": "住家",
              "screenshot": "截圖", "ai_generated": "AI生成",
              "others": "others"},
    "en": {"hiking": "hiking", "dining": "dining",
           "overseas_trip": "overseas-trip", "day_trip": "day-trip",
           "cat": "cat", "dog": "dog", "home": "home",
           "screenshot": "screenshot",
           "ai_generated": "AI-generated", "others": "others"},
}
# i18n-guard:allow-end
LEGACY_TYPE_LANGUAGE = "zh-TW"


def default_types(profile):
    """-> the `[type]` words for one owner, as a set.

    Same three-step resolution as buckets() and scene_classes(), and the same
    reason for the legacy step: a run with NO pack at all must keep accepting
    the words it accepted yesterday, or every replay of a shipped decision
    stops matching. ⛔ A pack that declares `naming_spec.types` overrides this
    entirely — the owner's own taxonomy always wins; this is only the default.

    An unknown language falls to English, never to Chinese: ASCII is the least
    surprising thing to hand someone whose language has no table here.
    """
    lang = get(profile, "language")
    if lang is None:
        return set(TYPE_VOCAB[LEGACY_TYPE_LANGUAGE].values())
    announce_missing_table(lang, TYPE_VOCAB)
    return set(TYPE_VOCAB.get(lang, TYPE_VOCAB["en"]).values())


# The `[what]` REFERENCE list (D-F7 / D-F11, signed by the owner 20260906).
#
# ⛔ THERE IS NO TABLE HERE, AND THERE MUST NEVER BE ONE. Every other
# vocabulary above resolves owner-declaration -> language table -> legacy
# strings, because the ENGINE invents those words: a bucket folder, a scene
# class, a `[type]`. `[what]` is not the engine's word for anything. It is
# what a photograph is OF, in the owner's own phrasing, and the only place
# that can come from is the owner.
#
# So the three-step resolution collapses to one step, and the empty case is
# the CORRECT answer rather than a gap waiting to be filled. ⛔ NO STARTER
# LIST SHIPS (D-F7). That is not an omission to be tidied up later — it is
# the mechanism that stops U2-06 recurring, where a Traditional-Chinese-only
# `[type]` set shipped as a "default", reached folder names, and hard-exited
# an English owner at `photo_classify_set.py:70`. Nothing shipped means
# nothing to ship in the wrong language.
#
# ⛔ AND IT IS A REFERENCE, NEVER A BOUNDARY (D-F11). The list exists so the
# naming agent can learn how this owner phrases things; the agent is never
# limited to it and its own free text is equally valid. Therefore `[what]`
# can never be validated against this list, and `photo_name.validate()` must
# not grow a membership check on that slot —
# `tests/photo_name_cases.py::the_what_slot_is_never_checked_against_a_list`
# is there to catch the next well-meaning attempt.
ENTITIES_NAME = "photo-entities.json"
WHAT_REFERENCE_KEY = "scenes"


def what_reference(pack):
    """-> the owner's `[what]` phrases, in pack order, deduplicated.

    Read from `photo-entities.json` under `scenes` — the slot the pack schema
    has always declared and nothing has ever read. ⛔ Not a new key: a second
    home for the same fact is how two lists drift, and the blank-sheet guard
    (`pack_state.owner_facts_in`) already counts `scenes` as owner knowledge,
    which is exactly what this is.

    Two entry shapes, because both will be written by hand at some point: a
    bare string, and the record shape the rest of this file uses
    (`{"name": ..., "confirmed_by": ...}`). Anything else in the list is
    skipped rather than raising.

    ⛔ NEVER RAISES AND NEVER EXITS. A missing pack, a missing file, unreadable
    JSON, a malformed entry — every one of them answers `[]`, for the reason
    `name_budget()` falls back rather than raising: this is a hint to a
    generator, so a broken hint must cost a run its style guide and never its
    folder names. Compare `home_locations`, which DOES hard-exit on a
    malformed row: a home the engine cannot read is a home it names, and that
    publishes a coordinate. Nothing here can leak anything by being absent.
    """
    directory = getattr(pack, "dir", None)
    if directory is None:
        return []
    path = Path(directory) / ENTITIES_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    out = []
    for entry in data.get(WHAT_REFERENCE_KEY) or []:
        if isinstance(entry, str):
            phrase = entry
        elif isinstance(entry, dict):
            phrase = entry.get("name")
        else:
            continue
        phrase = phrase.strip() if isinstance(phrase, str) else ""
        if phrase and phrase not in out:
            out.append(phrase)
    return out


# W2B-3 / ADR 0001 — a place the owner named at onboarding.
#
# `photo_onboard_page apply` writes them to `photo-entities.json` as
# `frequent_places: [{"label", "lat", "lon"}]`, and until this reader existed
# nothing in the engine read the key: the owner named a place and no folder
# changed. ⛔ ONE reader. Every naming path calls this, as every privacy path
# calls `home_points()`; a second reader is how two lists drift.
FREQUENT_PLACES_KEY = "frequent_places"
HOME_LOCATIONS_KEY = "home_locations"

# D-I15 — every home and every named place carries a fixed id, so an index can
# point at it with no coordinate and no label the owner may rename. Written by
# `apply --write-pack` and `backfill-ids`, never invented at load. The mark
# beside each list is the NEXT number to issue, so a deleted row's id is never
# issued again (an older dump's index may still point at it).
# list key -> (prefix, digits, pattern, mark key)
PLACE_IDS = {
    HOME_LOCATIONS_KEY: ("home", 2, re.compile(r"^home-\d{2,}$"),
                         "home_locations_next_id"),
    FREQUENT_PLACES_KEY: ("fsl", 4, re.compile(r"^fsl-\d{4,}$"),
                          "frequent_places_next_id"),
}
BACKFILL_IDS_COMMAND = "photo_onboard_page.py backfill-ids <pack>"


def place_ids(entries, list_key):
    """-> ([id or None, one per entry], [problem, ...]).

    A missing, malformed or shared id reads as None: a row letter such as
    "C" is not an id, and one id on two rows points at neither. None costs
    only the index's reference — suppression is by coordinate and never reads
    an id. A problem names the row by position, never by label or coordinate.
    """
    _prefix, _digits, pattern, _mark = PLACE_IDS[list_key]
    raw = [e.get("id") if isinstance(e, dict) else None for e in entries]
    valid = [v if isinstance(v, str) and pattern.match(v) else None
             for v in raw]
    ids, problems = [], []
    for i, (entry, given, good) in enumerate(zip(entries, raw, valid)):
        if not isinstance(entry, dict):
            ids.append(None)
            continue
        if good and valid.count(good) > 1:
            problems.append(f"{list_key}[{i}] shares its id with another row")
            good = None
        elif given in (None, ""):
            problems.append(f"{list_key}[{i}] has no id")
        elif good is None:
            problems.append(f"{list_key}[{i}] has an id not in "
                            f"{_prefix}-{'N' * _digits} form")
        ids.append(good)
    return ids, problems


_PLACE_ID_SAID = set()


def announce_place_ids(problems):
    """Say each id problem once per process, on stderr: every stage reads the
    homes, several times."""
    fresh = [p for p in problems if p not in _PLACE_ID_SAID]
    if not fresh:
        return
    _PLACE_ID_SAID.update(fresh)
    import photo_platform
    print("⚠️ owner pack: " + "; ".join(fresh) + ". A place with no usable "
          "id is still suppressed and named as before, but an index cannot "
          f"refer to it. `{photo_platform.owner_python()} {BACKFILL_IDS_COMMAND}` "
          "gives a missing id "
          "(a dry run; --go writes). A shared or malformed id is fixed by hand "
          "— the backfill never renumbers one.", file=sys.stderr)


def assign_place_ids(entries, list_key, mark):
    """-> (next mark, [(index, new id)]) for the rows with NO id at all.

    ⛔ A malformed or shared id is left alone: renumbering it would redirect
    whatever an older index points at. New numbers start after both the mark
    and the highest id present, so a hand-deleted last row is never re-issued.
    """
    prefix, digits, pattern, _mark = PLACE_IDS[list_key]
    present = [int(e["id"].split("-")[1]) for e in entries
               if isinstance(e, dict) and isinstance(e.get("id"), str)
               and pattern.match(e["id"])]
    try:
        mark = int(mark)
    except (TypeError, ValueError):
        mark = 1
    nxt = max([mark, 1] + [n + 1 for n in present])
    assigned = []
    for i, entry in enumerate(entries):
        if isinstance(entry, dict) and entry.get("id") in (None, ""):
            assigned.append((i, f"{prefix}-{nxt:0{digits}d}"))
            nxt += 1
    return nxt, assigned


def with_place_ids(data, list_key, assigned, mark):
    """-> a copy of `data` whose `list_key` rows carry `assigned` ids (as the
    first key) and whose mark is set. Every other key keeps its place; a new
    mark goes right after its list."""
    _prefix, _digits, _pattern, mark_key = PLACE_IDS[list_key]
    rows = list(data.get(list_key) or [])
    for i, pid in assigned:
        rows[i] = {"id": pid, **{k: v for k, v in rows[i].items() if k != "id"}}
    out = {}
    for key, value in data.items():
        out[key] = rows if key == list_key else value
        if key == list_key and mark_key not in data:
            out[mark_key] = mark
    if list_key not in out:
        out[list_key] = rows
    out[mark_key] = mark
    return out

# 📐 `{n}` — how close a day or a stop must be to a named place to take its
# name. ONE default, here; the pack may override it as
# `cluster_defaults.named_place_km`, and the template does not write it, so
# there is no second default to drift from this one.
#
# 1 km, measured (UAT01-4, 330 files): a day spent AT a place the census
# found has its centroid 0.03-0.16 km from that place, while places the census
# itself told apart sit 1.9, 2.6 and 3.1 km from each other. At 3 km one named
# cafe names a different part of the same city; at 1 km it does not. That is
# the scale the census DISCOVERS a place at (a ~1 km grid), not a tuning.
#
# ⛔ Wired to nothing else. Not `photo_cluster.PLACE_SUPPRESS_KM` (the 3 km
# privacy ring around a home) and not `photo_census.HOME_MATCH_KM` (pinned to
# `photo_where --home-km`, also privacy): a naming radius tied to a privacy
# radius moves one when somebody means to move the other.
NAMED_PLACE_KM_DEFAULT = 1.0

# 📐 G6 SNL (D-I3, owner 20260913 R1) — a place the owner is asked to name
# mid-run: seen on at least `{fsl_min_days}` separate days AND in at least
# `{fsl_min_months}` separate months. The months half is what keeps one trip
# (three days in a row at a hotel) from being asked as a place the owner
# returns to. CODE defaults; the pack may override them as
# `cluster_defaults.fsl_min_days` / `.fsl_min_months`, and ⛔ the template
# writes NEITHER — a default in code and a default in a pack are one fact.
FSL_MIN_DAYS_DEFAULT = 3
FSL_MIN_MONTHS_DEFAULT = 3


def fsl_bar(profile):
    """-> (fewest days, fewest months) that make an FSL, from the pack or the
    code defaults. Anything that is not a positive whole number falls back."""
    out = []
    for key, default in (("fsl_min_days", FSL_MIN_DAYS_DEFAULT),
                         ("fsl_min_months", FSL_MIN_MONTHS_DEFAULT)):
        value = get(profile, "cluster_defaults", key, default=None)
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
        out.append(value if value > 0 else default)
    return tuple(out)


# 📐 G6 (D-I6, owner R2) — how many batch pages may ask about ANIMALS. A page
# for a new place to name is never counted. CODE default; the pack may set
# `memory.batch_pages`, and ⛔ the template does not write it.
BATCH_PAGES_DEFAULT = 4


def batch_pages(profile):
    """-> the pet-page count, from the pack or the code default. Anything that
    is not a whole number of zero or more falls back."""
    value = get(profile, "memory", "batch_pages", default=None)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return BATCH_PAGES_DEFAULT
    return value if value >= 0 else BATCH_PAGES_DEFAULT


def named_places(pack):
    """-> [(lat, lon, label, id or None)] for every place the owner named, in
    file order. The id is D-I15's (`place_ids()`); naming does not read it.

    ⛔ A named place is NOT a residence (OA-23, owner 20260827): its
    coordinate is not sensitive and nothing here suppresses anything. The
    privacy rule reads `home_locations` and this list never touches it.

    ⛔ NEVER RAISES AND NEVER EXITS, for `what_reference()`'s reason and
    unlike `home_locations`: a malformed home switches the privacy rule off,
    so it is a hard exit; a malformed named place costs one day its owner's
    word and falls back to the map. A row without a label or a readable
    coordinate is skipped.
    """
    directory = getattr(pack, "dir", None)
    if directory is None:
        return []
    try:
        data = json.loads((Path(directory) / ENTITIES_NAME)
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    entries = data.get(FREQUENT_PLACES_KEY) or []
    if not isinstance(entries, list):
        return []
    ids, problems = place_ids(entries, FREQUENT_PLACES_KEY)
    announce_place_ids(problems)
    out = []
    for entry, pid in zip(entries, ids):
        if not isinstance(entry, dict):
            continue
        label = entry.get("label")
        label = label.strip() if isinstance(label, str) else ""
        try:
            lat, lon = float(entry["lat"]), float(entry["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if label:
            out.append((lat, lon, label, pid))
    return out


# 📐 `{n}` — W2C / ADR 0005. A still whose paperwork score (photo_embed's
# best financial/official prompt minus its best ordinary class) EXCEEDS this is
# routed to the to-be-checked bucket. ONE default, here; the pack may override
# it as `routing.paperwork_margin`, and the template does not write it.
#
# ⚠️ FITTED TO 2 POSITIVES — EVIDENCE, NOT CALIBRATION. Measured on 1,611 real
# files over three dumps, labelled by looking: the only real financial or
# official paperwork was ONE tax-assessment screenshot (two copies, +0.091)
# and ONE photographed service receipt (+0.036). The nearest false positives
# were an infographic screenshot (+0.026), a lighthouse photo (+0.015) and a
# video frame of banknotes (+0.008). 0.03 separates those, and the camera-shot
# bill clears the worst false positive by 0.010. Nobody tuned this on a
# labelled set; do not quote it as tuned, and re-measure before moving it.
PAPERWORK_MARGIN_DEFAULT = 0.03


def paperwork_margin(profile):
    """-> the routing cut, from the pack or the one default. A value that is
    not a number falls back rather than raising, as `named_place_km()` does."""
    value = get(profile, "routing", "paperwork_margin", default=None)
    try:
        return float(value)
    except (TypeError, ValueError):
        return PAPERWORK_MARGIN_DEFAULT


def pack_screen_sizes(profile):
    """-> {(short, long)} the sizes the pack's `screen_dims` holds, portrait,
    tolerantly. ⛔ Not `photo_sample.screen_devices()`: that one stops the run
    on an entry it cannot read, the right posture where the key moves files
    and the wrong one for a report."""
    sizes = set()
    for entry in get(profile, "screen_dims", default=None) or []:
        dims = entry.get("dims") if isinstance(entry, dict) else entry
        try:
            sizes.add(tuple(sorted(int(x) for x in dims)))
        except (TypeError, ValueError):
            continue
    return sizes


def open_screen_proposals(path, profile):
    """Card 9 — the sizes in a G-2 `screen-size-proposals.json` the owner has
    NOT answered yet: neither in `screen_dims` nor in `declined_screen_dims`.
    -> [[w, h], ...]. The file is written by the plan and never removed, so a
    reader that took its existence as "waiting" kept asking about a size the
    owner had already added or declined. An unreadable file waits on nothing."""
    try:
        q = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    answered = pack_screen_sizes(profile) | declined_screen_sizes(profile)
    out = []
    for c in (q.get("proposed_screen_dims") or []) if isinstance(q, dict) else []:
        try:
            dims = [int(v) for v in c["dims"]]
        except (KeyError, TypeError, ValueError):
            continue
        if tuple(sorted(dims)) not in answered:
            out.append(dims)
    return out


def declined_screen_sizes(profile):
    """-> {(short, long)} the sizes the owner said are NOT a screen they take
    screenshots on (`declined_screen_dims`, FIX6 / U6-37), portrait,
    tolerantly. A row that cannot be read is skipped: the answer costs that
    size one more question, never the run."""
    out = set()
    for entry in get(profile, "declined_screen_dims", default=None) or []:
        try:
            out.add(tuple(sorted(int(x) for x in entry)))
        except (TypeError, ValueError):
            continue
    return out


def named_place_km(profile):
    """-> the radius a named place names within, from the pack or the one
    default. Anything that is not a positive number falls back rather than
    raising, as `name_budget()` does: a malformed radius must cost the owner
    their word for a place, never the run."""
    value = get(profile, "cluster_defaults", "named_place_km", default=None)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return NAMED_PLACE_KM_DEFAULT
    return value if value > 0 else NAMED_PLACE_KM_DEFAULT


# Every sentence the ENGINE writes for a human to read: the notes it puts in a
# plan CSV, the plan document, the execution record, the batch labels. These
# were hardcoded Traditional Chinese, so a first-time owner in any other
# language got a report they could not read.
#
# Resolution is the same three steps as buckets(): profile.messages (the owner
# overrode a line) -> the table for profile.language -> the strings the engine
# has always shipped, for a run with no pack at all. A pack created from the
# template says language "en", so "new owner" and "no owner" are deliberately
# NOT the same case: an unbound run keeps producing exactly what it produced
# yesterday, byte for byte (tests/golden_replay.py leans on this).
#
# Rules for anyone adding a line here:
#   * a key is one WHOLE sentence, parameterized — never half a sentence that
#     the caller concatenates, because half a sentence cannot be translated;
#   * every key in one table exists in all of them;
#   * keys are English and ASCII, whatever the language of the value.
#
# i18n-guard:allow-begin — a declared locale table: the one place non-English
# strings are allowed to live, because that is what this table IS.
MESSAGE_VOCAB = {
    "zh-TW": {
        # --- separators the engine uses to join its own phrases -------------
        "note_separator": ";",
        "ref_separator": "、",

        # --- notes written into a plan CSV row ------------------------------
        "note_extension_corrected": "副檔名更正(D13):{old} → {new}(實際格式 {filetype})",
        "note_duplicate_name_in_plan": "同名檔已在本計畫 → _dup 後綴",
        "note_already_in_existing_folder": "既有資料夾已有相同檔案(名稱+大小+SHA-256)",
        "note_screenshot_duplicate_in_trip_folder":
            "為截圖,既有檔位於行程資料夾,可手動移至月度截圖資料夾",
        "note_format_undeterminable": "無法判定實際檔案格式(D13)→ 需人工確認",
        "note_junk_sidecar": "系統中繼檔(AppleDouble/資源分支),非媒體 → 不複製",
        "note_screenshot_exif_rule": "截圖(EXIF規則)",
        "note_shared": "shared(非本機拍攝,依日期歸檔 D-B)",
        "note_ai_confirmed": "AI生成(已人工確認)→ {bucket}",
        "note_unclassifiable": "無法分類(無日期/無地點)→ {bucket}",
        "note_screen_size_candidate":
            "疑似截圖({w}x{h}:同尺寸另有檔名可證為截圖,但設定檔尚未確認此螢幕尺寸)"
            "→ {bucket}",

        # --- lines shared by the plan document and the execution record -----
        "md_generated_at": "產生時間:{when}",
        "md_source": "來源:{source}",
        "md_item_count_header": "| 項目 | 數量 |",
        "md_dest_count_header": "| 目的地 | 檔數 |",

        # --- the destination modes a plan can ask for -----------------------
        "plan_mode_merge": "併入既有資料夾",
        "plan_mode_new": "新建資料夾",
        "plan_mode_fill_shell": "填入既有空殼資料夾",

        # --- the plan document ----------------------------------------------
        "plan_title": "# 計畫 P{plan} — {title}",
        "plan_batches": "批次:{batches}({start} → {end})",
        "plan_h_destination": "## 目的地",
        "plan_dest_line": "- **{mode}**:`{path}`",
        "plan_dest_merge_note":
            "  (人工命名的既有資料夾 — 依「既有資料夾優先」原則,名稱不變)",
        "plan_existing_subdirs": "- 既有子資料夾(不更動,僅供對照):",
        "plan_h_legs": "### 行程段子資料夾(D8:`MMDD-MMDD_[地點]`)",
        "plan_legs_header": "| 子資料夾 | 期間 | 複製檔數 |",
        "plan_h_override": "### 例外改歸(override)",
        "plan_override_line": "- {dates} 共 {n} 檔 → `{dest}`",
        "plan_override_reason": "  原因:{reason}",
        "plan_h_stats": "## 統計",
        "plan_stat_total": "| 檔案總數 | {n} |",
        "plan_stat_copy": "| **複製** | **{n}** |",
        "plan_stat_skip": "| 跳過(已存在,去重) | {n} |",
        "plan_stat_screenshots": "| 其中:截圖 → 月度截圖資料夾(D7) | {n} |",
        "plan_stat_shared": "| 其中:shared 檔(D-B 依日期歸檔) | {n} |",
        "plan_stat_renamed": "| 其中:副檔名更正後複製(D13) | {n} |",
        "plan_stat_unknown_format": "| 其中:格式無法判定 → 月度 others(D13) | {n} |",
        "plan_stat_bytes": "| 預估複製容量 | {size} |",
        "plan_h_dest_counts": "### 各目的地檔數",
        "plan_h_dedupe": "## 去重(OA-3,必要步驟)",
        "plan_dedupe_refs": "- 比對基準:{refs}",
        "plan_dedupe_rule": "- 規則:檔名+大小相符 → 兩側 SHA-256 雜湊一致才判定重複",
        "plan_dedupe_result":
            "- 結果:**{n} 檔已存在,將跳過**;明細見 CSV"
            "(action=skip_dupe,destination 欄為既有檔路徑)",
        "plan_dedupe_collisions":
            "- ⚠️ {n} 檔名稱+大小相符但雜湊不同(視為不同檔案,照常複製)",
        "plan_dedupe_limitation":
            "- 已知限制:iPhone 編輯再匯出檔(IMG_E 開頭)內容相同但名稱不同,"
            "本規則不會攔截",
        "plan_h_who_evidence": "## 檔案中拍到的對象",
        "plan_who_evidence_intro":
            "本計畫複製的 {n} 檔,於辨識階段記錄到的對象。只有「已確認」的對象"
            "且來源為 `viewed-image:`,名字才能放進資料夾名稱;`draft:` 表示該動物"
            "尚未命名。",
        "plan_who_evidence_header": "| 對象 | 來源 | 檔數 |",
        "plan_who_evidence_none": "- 未記錄到動物:{n} 檔",
        "plan_who_evidence_unseen": "- 辨識階段未看過:{n} 檔",
        "note_paperwork": "看起來是財務或官方文件 — 改放待分類,不放入此資料夾(ADR 0005)",
        "plan_stat_paperwork": "| 其中:疑似財務/官方文件 → 待分類 | {n} |",
        "plan_h_paperwork": "## 未放入此資料夾的文件照片",
        "plan_paperwork_intro":
            "有 {n} 張照片看起來是財務或官方文件:帳單、發票、銀行或稅務文件、合約、"
            "官方信函。它們已改放 `{bucket}`,沒有放進此資料夾,以免含個人資料的照片"
            "被當成旅遊照片分類與命名。沒有刪除任何檔案:請打開 `{bucket}`,把不是"
            "文件的照片移回。",
        "plan_paperwork_not_run":
            "有 {n} 個檔案未做文件檢查({reason}),因此照一般規則分類。"
            "其中若有帳單或官方信函的照片,可能已在此資料夾中。",
        "plan_paperwork_reason_missing": "photo_embed 尚未為此批檔案評分",
        "plan_paperwork_reason_model": "評分所用的模型與影像索引不同",
        "plan_paperwork_reason_unscored": "這些檔案未經 photo_embed 評分",
        "run_paperwork_banner":
            "有 {n} 張看起來是財務或官方文件的照片已改放 `{bucket}`,"
            "沒有放進旅遊或活動資料夾。沒有刪除任何檔案。",
        "plan_refused_unbacked": "計畫 P{plan} 本次未產生 — 未寫入任何計畫檔,批次狀態也未推進。",
        "plan_unbacked_name_line":
            "  資料夾名稱 `{folder}` 把 {names} 放在 {n} 個檔案上,但其中沒有任何一檔"
            "以 `viewed-image:` 拍到已確認的 {names}。",
        "plan_unbacked_evidence": "  這些檔案實際拍到:{evidence}",
        "plan_unbacked_evidence_item": "{who} ×{n}({provenance})",
        "plan_unbacked_no_animal": "未記錄到動物 {n} 檔",
        "plan_unbacked_unseen": "辨識階段未看過 {n} 檔",
        "plan_unbacked_not_seen": "無 — 本次略過辨識階段(--no-vision),沒有任何檔案能支持名字",
        "plan_unbacked_remedy":
            "  請從 plans.json 移除這個名字;或在命名檢查點為這隻動物命名、"
            "為這些批次重跑辨識階段,再重跑本計畫。同一張照片裡的兩隻動物是兩個名字,"
            "各自需要證據。",
        "plan_h_notes": "## 備註",
        "plan_h_safety": "## 安全確認",
        "plan_safety_readonly":
            "- 本計畫為唯讀產出 — 執行前不會動到任何檔案;原始檔案永不移動或刪除(僅複製)",
        "plan_safety_dest_root": "- 新建資料夾僅位於 `{root}`(D5);併入既有資料夾者已於上方明列",
        "plan_full_file_list": "- 完整檔案清單:`{path}`",
        "plan_h_screen_candidates": "## 疑似截圖 — 尚未確認的螢幕尺寸",
        "plan_screen_candidate_intro":
            "本次共 **{n} 檔**改送 `{bucket}` 而非行程資料夾:同尺寸另有檔案的檔名可證"
            "為截圖,但擁有者的 `screen_dims` 尚未確認該尺寸。流程未中斷。"
            "這些尺寸不會加入設定檔;要加入,請為此工作資料夾重新產生引導答卷,"
            "並回答其中的 `screen:` 行 — 在那之前檔案留在 `{bucket}`。",
        "plan_screen_candidate_row":
            "- `{w}x{h}` — 全機 {files} 檔為同尺寸;證據檔名:`{witness}`",
        "plan_screen_capture_limit":
            "- 已知限制:引擎尚未學過的截圖工具,其檔案會依日期歸檔 — 看到請手動移動",
        "plan_safety_approval": "**經核准後,才由 photo-execute 執行。**",

        # --- the no-date plan document ---------------------------------------
        "nodate_title": "# 計畫 — 無日期檔案(D13 自動歸檔)",
        "nodate_intro":
            "共 **{n} 檔**沒有可用的 EXIF 拍攝日期,依 D13(2026-07-06 待分類修訂)自動歸檔:",
        "nodate_route_ai": "- `no_exif` 規則檔已**人工確認為 AI 生成** → `{dest}`",
        "nodate_route_all":
            "- 全部 → `{dest}`(後續人工檢視;{ai_bucket} 僅收人工確認的 AI 生成圖,"
            "用 --ai-confirmed)",
        "nodate_route_split":
            "- 依檔案本身的日期歸檔:影片依其檔案修改日期的年份 → `YYYY00_{bucket}`;"
            "靜態圖不標示年份 → `{stills}`(後續人工檢視;{ai_bucket} 僅收人工確認的 "
            "AI 生成圖,用 --ai-confirmed)",
        "nodate_rename_line": "- 副檔名與實際格式不符者,複製時以更正後的檔名寫入(D13)",
        "nodate_rule_header": "| EXIF 規則判定 | 檔數 |",
        "nodate_full_list": "- 完整清單:`{path}`",
        "nodate_run_line": "- 執行:`photo_execute.py <workdir> --no-date [--go]`",

        # --- execution flags (both sides left untouched) ----------------------
        "flag_collision_existing_differs": "目的地已有同名檔且內容不同 — 兩側皆未更動",
        "flag_collision_appeared_midcopy": "複製途中目的地出現同名檔 — 未覆寫",
        "flag_checksum_mismatch": "SHA-256 兩次複製皆不符 — 已刪除不良副本,原始檔未動",

        # --- the execution record ---------------------------------------------
        "exec_title": "# 執行紀錄 — 計畫 {label}",
        "exec_executed_at": "執行時間:{when}(耗時 {seconds} 秒)",
        "exec_stat_copied": "| 本次複製並通過 SHA-256 驗證 | {n} |",
        "exec_stat_already_present": "| 目的地已有相同內容(視為完成) | {n} |",
        "exec_stat_previously_verified": "| 先前執行已驗證(本次跳過) | {n} |",
        "exec_stat_skip_dupe": "| skip_dupe(去重,永不複製) | {n} |",
        "exec_stat_flags": "| ⚠️ 待處理旗標 | {n} |",
        "exec_h_dest_counts": "## 各目的地已驗證檔數",
        "exec_h_flags": "## ⚠️ 旗標(兩側皆未更動,需人工處理)",
        "exec_flags_header": "| 類型 | 來源 | 目的地 | 說明 |",
        "exec_batches_done": "批次 {batches} 全數驗證完成 → 狀態 `done`",
        "exec_footer": "原始檔案未移動、未修改、未刪除(D2 copy-only)。",

        # --- provisional batch labels written by photo_cluster ----------------
        "cluster_label_home": "日常（住家範圍）",
        "cluster_label_home_place": "日常（住家範圍）—{place}",
        "cluster_away_km_not_set": (
            "ℹ️ 尚未設定 away_km，本次以預設值 {away_km} 公里判斷「在家/外出」。"
            "這是合理的起點，但不等於你的實際生活範圍；"
            "如需調整，請於 onboarding 頁面或 photo-profile.json 的 "
            "cluster_defaults.away_km 填入後重跑此階段。"),
        "cluster_place_label_is_address": (
            "⚠️ 地點名稱「{label}」看起來像街道地址。這是你自己取的名稱,"
            "引擎會照用,它會出現在資料夾名稱上。如不希望如此,請在 "
            "photo-entities.json 的 frequent_places 改成較概括的名稱後重跑此階段。"),
        "cluster_home_label_is_address": (
            "⚠️ 住家標籤「{label}」看起來像街道地址。這是你自己取的名稱,"
            "引擎會照用,它會出現在資料夾名稱上——若該磁碟有同步到雲端硬碟,"
            "這個名稱也會一起上傳。如不希望如此,請在 photo-profile.json 的 "
            "home_locations 改成較概括的名稱後重跑此階段。"),
        "cluster_label_domestic": "台灣出遊—{place}",
        "cluster_label_overseas": "出國—{place}",
        "cluster_place_unresolved": "未能確定地點",
        "cluster_place_name_not_in_owner_language": (
            "ℹ️ 地圖服務對批次 {batches} 的地點沒有 {language} 的名稱，"
            "因此使用當地名稱。這是地圖原本的名稱，並非翻譯，"
            "也不是你的設定出錯。"),
    },
    "en": {
        # --- separators the engine uses to join its own phrases -------------
        "note_separator": "; ",
        "ref_separator": ", ",

        # --- notes written into a plan CSV row ------------------------------
        "note_extension_corrected":
            "extension corrected (D13): {old} → {new} (real format {filetype})",
        "note_duplicate_name_in_plan":
            "a file of the same name is already in this plan → _dup suffix",
        "note_already_in_existing_folder":
            "the existing folder already holds this file (name + size + SHA-256)",
        "note_screenshot_duplicate_in_trip_folder":
            "this is a screenshot and the existing copy sits in a trip folder — "
            "move it to the monthly screenshots folder by hand if you want it there",
        "note_format_undeterminable":
            "the real file format cannot be determined (D13) → needs a human check",
        "note_junk_sidecar":
            "a system metadata sidecar (AppleDouble / resource fork), not media "
            "→ not copied",
        "note_screenshot_exif_rule": "screenshot (EXIF rule)",
        "note_shared": "shared (not shot on this device, filed by date D-B)",
        "note_ai_confirmed": "AI-generated (confirmed by a human) → {bucket}",
        "note_unclassifiable": "cannot be classified (no date / no place) → {bucket}",
        "note_screen_size_candidate":
            "possible screenshot ({w}x{h}: another file's name proves this is a "
            "screen size, and the profile has not confirmed it) → {bucket}",

        # --- lines shared by the plan document and the execution record -----
        "md_generated_at": "Generated: {when}",
        "md_source": "Source: {source}",
        "md_item_count_header": "| Item | Count |",
        "md_dest_count_header": "| Destination | Files |",

        # --- the destination modes a plan can ask for -----------------------
        "plan_mode_merge": "merge into an existing folder",
        "plan_mode_new": "create a new folder",
        "plan_mode_fill_shell": "fill an existing empty folder",

        # --- the plan document ----------------------------------------------
        "plan_title": "# Plan P{plan} — {title}",
        "plan_batches": "Batches: {batches} ({start} → {end})",
        "plan_h_destination": "## Destination",
        "plan_dest_line": "- **{mode}**: `{path}`",
        "plan_dest_merge_note":
            "  (a folder you named by hand — under the \"existing folder wins\" "
            "rule its name is left alone)",
        "plan_existing_subdirs": "- Sub-folders already there (untouched, for reference):",
        "plan_h_legs": "### Trip-leg sub-folders (D8: `MMDD-MMDD_[where]`)",
        "plan_legs_header": "| Sub-folder | Period | Files copied |",
        "plan_h_override": "### Override",
        "plan_override_line": "- {dates}: {n} files → `{dest}`",
        "plan_override_reason": "  Reason: {reason}",
        "plan_h_stats": "## Statistics",
        "plan_stat_total": "| Files in total | {n} |",
        "plan_stat_copy": "| **Copy** | **{n}** |",
        "plan_stat_skip": "| Skipped (already there, deduped) | {n} |",
        "plan_stat_screenshots":
            "| of which: screenshots → the monthly screenshots folder (D7) | {n} |",
        "plan_stat_shared": "| of which: shared files (D-B, filed by date) | {n} |",
        "plan_stat_renamed": "| of which: copied under a corrected extension (D13) | {n} |",
        "plan_stat_unknown_format":
            "| of which: format undeterminable → the monthly others folder (D13) | {n} |",
        "plan_stat_bytes": "| Estimated size to copy | {size} |",
        "plan_h_dest_counts": "### Files per destination",
        "plan_h_dedupe": "## Dedupe (OA-3, mandatory)",
        "plan_dedupe_refs": "- Compared against: {refs}",
        "plan_dedupe_rule":
            "- Rule: same name + same size → only a matching SHA-256 on both sides "
            "counts as a duplicate",
        "plan_dedupe_result":
            "- Result: **{n} files are already there and will be skipped**; see the CSV "
            "for detail (action=skip_dupe, the destination column holds the existing path)",
        "plan_dedupe_collisions":
            "- ⚠️ {n} files match on name + size but not on hash "
            "(treated as different files and copied as usual)",
        "plan_dedupe_limitation":
            "- Known limit: a photo edited and re-exported on an iPhone (name starting "
            "IMG_E) has the same content under a different name; this rule will not "
            "catch it",
        "plan_h_who_evidence": "## Who the files show",
        "plan_who_evidence_intro":
            "What the see stage recorded for the {n} file(s) this plan copies. "
            "Only a CONFIRMED subject seen at `viewed-image:` may put its name "
            "in a folder name; `draft:` means the animal has not been named yet.",
        "plan_who_evidence_header": "| who | provenance | files |",
        "plan_who_evidence_none": "- no animal recorded: {n} file(s)",
        "plan_who_evidence_unseen": "- not seen by the see stage: {n} file(s)",
        "note_paperwork":
            "looks like financial or official paperwork — put in the "
            "to-be-checked bucket instead of this folder (ADR 0005)",
        "plan_stat_paperwork":
            "| of which: looks like paperwork → to-be-checked | {n} |",
        "plan_h_paperwork": "## Paperwork kept out of this folder",
        "plan_paperwork_intro":
            "{n} photo(s) look like financial or official paperwork: a bill, "
            "an invoice, a bank or tax document, a contract, an official "
            "letter. They went to `{bucket}` instead of this folder, so "
            "personal details are not sorted and named like a holiday photo. "
            "Nothing was deleted: open `{bucket}` and move back anything that "
            "is not paperwork.",
        "plan_paperwork_not_run":
            "The paperwork check did not run for {n} file(s) ({reason}), so "
            "they were sorted as usual. A photo of a bill or an official "
            "letter among them may be in this folder.",
        "plan_paperwork_reason_missing":
            "photo_embed has not scored this dump",
        "plan_paperwork_reason_model":
            "the scores were made by a different model than the image index",
        "plan_paperwork_reason_unscored":
            "these files were not scored by photo_embed",
        "run_paperwork_banner":
            "{n} photo(s) that look like financial or official paperwork were "
            "put in `{bucket}` instead of a trip or event folder. Nothing was "
            "deleted.",
        "plan_refused_unbacked":
            "plan P{plan} was not written this run — no plan file was written "
            "and no batch status moved.",
        "plan_unbacked_name_line":
            "  the folder name `{folder}` puts {names} on {n} file(s), and not "
            "one of them shows {names} at `viewed-image:` as a confirmed subject.",
        "plan_unbacked_evidence": "  what those files show: {evidence}",
        "plan_unbacked_evidence_item": "{who} x{n} ({provenance})",
        "plan_unbacked_no_animal": "no animal on {n}",
        "plan_unbacked_unseen": "not seen by the see stage: {n}",
        "plan_unbacked_not_seen":
            "nothing — the see stage was skipped (--no-vision), so no file "
            "here can back a name",
        "plan_unbacked_remedy":
            "  Take the name out of plans.json, or name the animal at the "
            "naming checkpoint and re-run the see stage for these batches, "
            "then re-run this plan. Two animals in one frame are two names, "
            "and each needs its own evidence.",
        "plan_h_notes": "## Notes",
        "plan_h_safety": "## Safety",
        "plan_safety_readonly":
            "- This plan is read-only output — nothing is touched before you execute it; "
            "originals are never moved or deleted (copy only)",
        "plan_safety_dest_root":
            "- New folders are created under `{root}` only (D5); merges into existing "
            "folders are listed above",
        "plan_full_file_list": "- Full file list: `{path}`",
        "plan_h_screen_candidates": "## Possible screenshots — an unconfirmed screen size",
        "plan_screen_candidate_intro":
            "**{n} file(s)** went to `{bucket}` instead of this trip's folder: another "
            "file's name proves those are screen sizes, and the owner's `screen_dims` "
            "has not confirmed them. Nothing was blocked. These sizes are not added "
            "to the pack; to add one, make the onboarding sheet for this work dir "
            "again and answer its `screen:` line — until then the files wait in "
            "`{bucket}`.",
        "plan_screen_candidate_row":
            "- `{w}x{h}` — {files} file(s) at this size across the dump; proven by "
            "`{witness}`",
        "plan_screen_capture_limit":
            "- Known limit: a capture tool the engine has not learned is filed "
            "by date — move any you spot",
        "plan_safety_approval": "**Nothing is copied until you approve and run photo-execute.**",

        # --- the no-date plan document ---------------------------------------
        "nodate_title": "# Plan — files with no date (D13, auto-filed)",
        "nodate_intro":
            "**{n} files** have no usable EXIF capture date and are auto-filed under D13 "
            "(the 2026-07-06 to-be-checked revision):",
        "nodate_route_ai":
            "- files matching the `no_exif` rule were **confirmed AI-generated by a "
            "human** → `{dest}`",
        "nodate_route_all":
            "- everything → `{dest}` (for a later human pass; {ai_bucket} only ever "
            "takes human-confirmed AI images, via --ai-confirmed)",
        # M14 — "everything → one bucket" is false once files split by their
        # own date, so this path gets its own sentence rather than a wrong one.
        "nodate_route_split":
            "- by the date each file carries: a video goes to the year of its own "
            "file date (`YYYY00_{bucket}`); a still claims no year and goes to "
            "`{stills}` (for a later human pass; {ai_bucket} only ever takes "
            "human-confirmed AI images, via --ai-confirmed)",
        "nodate_rename_line":
            "- files whose extension disagrees with the real format are written under "
            "the corrected name (D13)",
        "nodate_rule_header": "| EXIF rule verdict | Files |",
        "nodate_full_list": "- Full list: `{path}`",
        "nodate_run_line": "- Run: `photo_execute.py <workdir> --no-date [--go]`",

        # --- execution flags (both sides left untouched) ----------------------
        "flag_collision_existing_differs":
            "the destination already holds a file of this name with different content — "
            "neither side was touched",
        "flag_collision_appeared_midcopy":
            "a file of this name appeared at the destination mid-copy — not overwritten",
        "flag_checksum_mismatch":
            "SHA-256 mismatched on both copy attempts — the bad copy was deleted, the "
            "original was not touched",

        # --- the execution record ---------------------------------------------
        "exec_title": "# Execution record — plan {label}",
        "exec_executed_at": "Executed: {when} (took {seconds} s)",
        "exec_stat_copied": "| Copied and SHA-256 verified in this run | {n} |",
        "exec_stat_already_present":
            "| Already present with identical content (counted as done) | {n} |",
        "exec_stat_previously_verified":
            "| Verified by an earlier run (skipped this time) | {n} |",
        "exec_stat_skip_dupe": "| skip_dupe (deduped, never copied) | {n} |",
        "exec_stat_flags": "| ⚠️ Flags to deal with | {n} |",
        "exec_h_dest_counts": "## Verified files per destination",
        "exec_h_flags": "## ⚠️ Flags (neither side touched, needs a human)",
        "exec_flags_header": "| Kind | Source | Destination | Detail |",
        "exec_batches_done": "Batches {batches} are fully verified → status `done`",
        "exec_footer":
            "No original file was moved, modified or deleted (D2 copy-only).",

        # --- provisional batch labels written by photo_cluster ----------------
        "cluster_label_home": "everyday (around home)",
        # R13 — a home batch may now carry a CITY-level place. The plain form
        # above stays for the batch the administrative lookup could not name.
        "cluster_label_home_place": "everyday (around home) — {place}",
        # R13. Said once, at the end, on stderr — the run is not wrong, it is
        # unanswered, and the difference is the whole message.
        "cluster_away_km_not_set": (
            "ℹ️ away_km was never set, so this run used the {away_km} km "
            "default to decide 'at home' from 'away'. That is a reasonable "
            "starting point, not a measurement of your life: if home feels "
            "smaller or larger than that, set it on the onboarding page or as "
            "cluster_defaults.away_km in photo-profile.json and re-run this "
            "stage."),
        # D-F9 follow-up. The owner's label is USED — this warns, it does not
        # refuse, which is the D-F5 pattern: the engine tells the owner what
        # their own data is about to do and leaves the choice with them.
        # ⛔ Echoes the LABEL, never the coordinate.
        "cluster_place_label_is_address": (
            "⚠️ The place name '{label}' looks like a street address. It is "
            "your own word and the engine is using it, so it will appear in "
            "folder names. If you would rather it did not, change that name "
            "under frequent_places in photo-entities.json and re-run this "
            "stage."),
        "cluster_home_label_is_address": (
            "⚠️ The home label '{label}' looks like a street address. It is "
            "your own word and the engine is using it, so it will appear in "
            "folder names — and on a drive you sync, those names go with it. "
            "If you would rather it did not, change that label in "
            "home_locations in photo-profile.json and re-run this stage."),
        "cluster_label_domestic": "day out — {place}",
        "cluster_label_overseas": "abroad — {place}",
        # Stands in for the place in the two labels above when the engine has
        # no name to put there. ONE phrase covers both causes on purpose — see
        # photo_cluster.py, where the second cause is a privacy suppression
        # that a distinct wording would announce.
        "cluster_place_unresolved": "place not determined",
        # F7 / D-06 — the map service had no name in the owner's language, so
        # the local one was used. Said at the end of the stage, on stderr.
        "cluster_place_name_not_in_owner_language": (
            "ℹ️ The map service holds no name in your language ({language}) "
            "for the place(s) in batch(es) {batches}, so the local name was "
            "used. That is the map's own name, not a translation, and not a "
            "fault in your settings."),
    },
}
# i18n-guard:allow-end
LEGACY_MESSAGE_LANGUAGE = "zh-TW"


def messages(profile):
    """-> {key: format string} for one owner. Same resolution as buckets()."""
    lang = get(profile, "language")
    if lang is None:
        table = MESSAGE_VOCAB[LEGACY_MESSAGE_LANGUAGE]
    else:
        # an unknown language falls to English rather than to Chinese, for the
        # same reason buckets() does
        announce_missing_table(lang, MESSAGE_VOCAB)
        table = MESSAGE_VOCAB.get(lang, MESSAGE_VOCAB["en"])
    named = get(profile, "messages", default=None) or {}
    return {**table, **named}


# Every sentence the MEMORY REVIEW TABLE puts in front of a human (VS-4 /
# Phase C). Separate from MESSAGE_VOCAB for one reason worth stating: the
# review table is a NEW artifact, so unlike a plan CSV it has no shipped
# output to reproduce and therefore no legacy locale. Rule 8 applies with
# nothing pulling against it — the engine ships English, and any other
# language arrives from the pack.
#
# ⚠️ The two lines the TEMPLATE makes mandatory are in here, not in the
# renderer: the `Effect if answered:` line (`review_effect_line`) and the
# honesty marker for an unnamed subject (`review_unnamed_subject`, which
# renders a generic CLASS WORD and never a guessed name). A renderer holding
# either as a literal would be untranslatable and — worse for the honesty
# marker — would put an engine-chosen word where an owner's word belongs.
#
# The FIELD KEYS a human types into (`who:`, `name:`, `answer:`, `skip:`) are
# ASCII and are NOT in this table: `photo_memory.py confirm` parses them, and
# a parser that depends on a translated label breaks the moment somebody
# translates it. Same rule the message keys already follow — keys English,
# values whatever the owner speaks.
REVIEW_VOCAB = {
    "en": {
        "review_title": "Memory Review — Checkpoint C{n}",
        # G6 — the per-batch page.
        "review_page_title": "Photo page {page} — batch {batch}",
        "review_page_asks": "This page asks only about this batch: its "
                            "animals, and a place you visit often if one "
                            "first shows up here. It is one of a few short "
                            "pages, and the copy waits until it is answered.",
        "review_page_nothing": "Nothing to ask in this batch.",
        "review_page_pets": "Your animals: {names}. On a row, pick the photos "
                            "of one of them and write its name followed by "
                            "`{same}` — for example `name: {example} {same}`. "
                            "For an animal that is not on your list, write a "
                            "new name. For one that is not yours, use `skip:`.",
        "review_places_header": "### A place you visit often",
        "review_place_header": "**S{n} · a place you visit often** — {days} "
                               "day(s) over {months} month(s), in {batches} "
                               "batch(es)",
        "review_place_ask": "What do you call this place? Write its name. If "
                            "you live there, add `live` after the name; if it "
                            "is a home you stay at when you travel, add "
                            "`visit`. Leave the row blank to skip it.",
        "review_place_no_photos": "(no sample photo of this place in this "
                                  "batch)",
        "review_place_photos_held": "{n} photo(s) of this place are not shown "
                                    "because they look like a document.",
        "review_place_no_recut": "A home named here is protected from now on, "
                                 "but the batches already cut are not cut "
                                 "again.",
        "review_hint_place": "the place's name, then `live` or `visit` after "
                             "it if it is a home",
        # G6-6 — a batch page has no later checkpoint and asks about animals
        # only (NF-3). A checkpoint page keeps its own sentences.
        "review_hint_who_on_page": "pet — this page asks about animals only",
        "review_skip_note_on_page": "Leaving a frame out of every row is "
                                    "free — that draft stays a draft, and the "
                                    "last page of this folder of photos, after "
                                    "the copy, may ask about it again. "
                                    "`skip:` is the opposite: nothing asks "
                                    "again, which is why it is the one row "
                                    "that asks you to type the word confirm "
                                    "beside the numbers. Nothing here has "
                                    "copied a file.",
        "review_more_deferred_on_page": "{n} more draft(s) of this kind are "
                                        "not shown here. They are not skipped "
                                        "— the last page, after the copy, may "
                                        "ask about them.",
        "review_frames_unresolved_on_page": "⚠️ {n} more example photo(s) for "
                                            "this subject are not shown and "
                                            "cannot be picked ({why}). Nothing "
                                            "is lost.",
        "review_more_deferred_round_on_page": "{n} further draft(s) are not on "
                                              "this page at all: a page shows "
                                              "at most {cap} photo group(s), "
                                              "and the ones that would relabel "
                                              "the most files went first. You "
                                              "skipped none of them and named "
                                              "none of them — the last page, "
                                              "after the copy, may ask about "
                                              "them.",
        "review_deferred_sweep_note_on_page": "One thing can still change "
                                              "without you: if one of these "
                                              "turns out to be a subject you "
                                              "name on this page, it stops "
                                              "being asked about. No name and "
                                              "no exemplar is written for it, "
                                              "it is written in your pack's "
                                              "memory log, and withdrawing the "
                                              "name releases them all.",
        "review_asked_on_page": "already asked on page {page}; repeated here "
                                "because its evidence grew",
        "review_owner_line": "owner: {owner} · unit: {unit} · batches {batches} "
                             "· {files} files",
        "review_fired_line": "fired because: {n} file(s) depend on an unnamed or "
                             "unconfirmed recurring subject (threshold {threshold})",
        # SNS-4 — the round's own reason, said on every page whichever way it
        # went. Four sentences and not one: an owner who is told "no round"
        # without being told the floor was not reached cannot tell a decision
        # from a fault. All four take the same fields, so a pack may reword any
        # of them without knowing which one the engine will pick.
        "review_round_fired_floor": "SNS round {round} of {cap}: asking, "
                                    "because {new} newly-seen subject(s) "
                                    "reached the floor of {floor}",
        # ⛔ N17 — "the last checkpoint OF THE DUMP" was the same
        # unkeepable promise the suppression line carried: a re-run of
        # `finish --go` passes `--final` again and fires another one. It
        # is the last checkpoint the dump starts BY ITSELF, and saying
        # more than that made this header contradict the very page it
        # heads once that line was corrected.
        "review_round_fired_final": "SNS round {round}: asking, because this "
                                    "is the last checkpoint this dump starts "
                                    "on its own — the final round always asks, "
                                    "whether or not the floor of {floor} was "
                                    "reached, and is not charged against the "
                                    "budget of {cap}",
        "review_round_withheld_floor": "no SNS round here: {new} newly-seen "
                                       "subject(s) since the last round and "
                                       "the floor is {floor}. {waiting} "
                                       "subject(s) are waiting, none of them "
                                       "counted as asked — the last round of "
                                       "the dump asks about them",
        "review_round_withheld_cap": "no SNS round here: {rounds} round(s) "
                                     "asked already and the budget for this "
                                     "dump is {cap}. {waiting} subject(s) are "
                                     "waiting, none of them counted as asked — "
                                     "the last round of the dump asks about "
                                     "them",
        "review_age_line": "memory age: {confirmed} confirmed subject(s) · "
                           "{drafts} draft(s)",
        "review_snapshot_line": "pack snapshot: {snapshot} · {files} file(s)",
        "review_table_header": "| # | Date range | Files | Key facts captured | "
                               "Scene | Ask |",
        "review_fact_new": "**new** {subject} ({files}f)",
        "review_fact_again": "**again** {subject} ({files}f)",
        "review_fact_known": "**known** {subject} ({files}f)",
        "review_no_facts": "—",
        "review_scene": "{subjects} · {clusters} visual cluster(s) (saw {seen} "
                        "of {files})",
        "review_scene_none": "nothing visual was recorded for this batch (saw "
                             "{seen} of {files})",
        "review_subject_separator": ", ",
        "review_unnamed_subject": "an unnamed {kind}",
        # D-21 — the honesty marker with the cheapest evidence that tells one
        # draft from another. Eleven groups of one species all rendered
        # `an unnamed Cat`, in the tile list and up to seventeen times in a
        # single Scene cell, and the owner had nothing but list position to
        # hold them apart — while the engine held a first-seen date, a file
        # count and a batch span it did not print. The date is the one that
        # fits everywhere the marker appears: it is short, it is how a person
        # actually recalls a photograph, and unlike a count it stays stable
        # while the group grows.
        # ⛔ It WRAPS the marker above rather than restating it, and that is
        # the same rule `review_more_deferred_round` was given its own key
        # for: a pack that translated `review_unnamed_subject` keeps its own
        # word here, because that word arrives as `{subject}`. A second
        # `an unnamed {kind}` in this row would silently untranslate every
        # pack that answered the first one.
        # ⚠️ Still an honesty marker and still never a guessed name; a draft
        # with no capture date on any of its frames keeps the bare marker.
        "review_unnamed_subject_since": "{subject} (first seen {since})",
        # N-9's collective noun, for a folder holding more named subjects than
        # `{names_per_folder}`. English pluralises with an `s` and most
        # languages do not, which is exactly why it is a FORMAT STRING in the
        # overridable table rather than a rule in the renderer — a pack whose
        # language has no plural sets it to "{kind}" and loses nothing.
        "review_who_many": "{kind}s",
        "review_kind_person": "person",
        "review_kind_object": "object",
        "review_kind_unknown": "subject",
        "review_questions_header": "### Questions",
        "review_no_questions": "No draft crosses the threshold at this "
                               "checkpoint — nothing to ask.",
        "review_no_questions_page": "No animal to match in this batch.",
        "review_q_header": "**Q{n} · {type}** — affects {files} file(s) / "
                           "{batches} batch(es) · {span}",
        "review_q_type_group_it": "Group it — {kind}",
        "review_q_group_it": "{n} group(s) of photos look like a {kind}. How "
                             "many {kind}(s) is this, and what do you call each "
                             "one?",
        "review_q_count_why": "**Why you decide, not the system:** a wrong merge "
                              "mislabels both subjects forever and quietly; a "
                              "wrong split costs one extra question.",
        "review_tile_line": "**{n}** · {subject} · {files} file(s) / {batches} "
                            "batch(es)",
        "review_more_deferred": "{n} more draft(s) of this kind are not shown "
                                "here. They are not skipped — they come back at "
                                "a later checkpoint.",
        # SNS-4's `{tiles_per_round}` ceiling, and it needs its OWN key rather
        # than a longer `review_more_deferred`. That sentence is about ONE
        # question being too long for one kind; this one is about the whole
        # ROUND being full across every kind, and the two have different
        # repairs. A pack that already overrode the sentence above translated
        # the per-question clamp and would keep saying only that — so the one
        # owner who took the trouble to translate the round would be the one
        # owner never told the ceiling exists. Same reasoning as
        # `review_recheck_name_hint`: a new key reaches every pack, translated
        # or not, and no existing key quietly changes meaning underneath one.
        "review_more_deferred_round": "{n} further draft(s), across every kind "
                                      "above, are not on this page at all: one "
                                      "round shows at most {cap} photo group(s) "
                                      "in total, and the ones that would "
                                      "relabel the most files went first. Some "
                                      "kinds may not appear here at all. "
                                      "You skipped none of them and named "
                                      "none of them — the next checkpoint "
                                      "asks about them.",
        # D-23 — the clause that makes the sentence above TRUE, and it is a
        # NEW key for the reason every new key here gets: a pack that
        # translated the paragraph above kept the promise it used to make
        # ("nothing was decided about them"), and a pack that never
        # translated it would have been the only one told otherwise. A new
        # key reaches every pack, translated or not.
        #
        # ⛔ The promise was measurably false. The post-confirm sweep scores
        # every open draft against the subjects just confirmed, and a draft
        # this page held back for the tile ceiling is an open draft — so two
        # of them were absorbed on one real run, both named on that page as
        # "still ai-drafted, still askable". The sweep is not the defect: at a
        # tile ceiling the drafts it exists to close are exactly the ones the
        # page suppressed, so refusing to touch them would absorb nothing.
        # What was wrong is a page promising more than the run can keep.
        "review_deferred_sweep_note": "One thing can still change without you: "
                                      "if one of these turns out to be a "
                                      "subject you name on this page, it stops "
                                      "being asked about. No name and no "
                                      "exemplar is written for it, the next "
                                      "checkpoint lists every one this "
                                      "happened to, and withdrawing the name "
                                      "releases them all.",
        # D-23's other half: the list itself, on the NEXT page. The owner
        # cannot undo what they were never shown.
        "review_absorbed_header": "### Recognised without asking — {n} draft(s) "
                                  "the last answer closed",
        "review_absorbed_intro": "These were open drafts when you answered "
                                 "checkpoint C{n}, and the confirm recognised "
                                 "them as a subject you had just named. "
                                 "Nothing was named and no exemplar was "
                                 "written for any of them. If one is wrong, "
                                 "withdraw the name it went to and all of them "
                                 "come back.",
        "review_absorbed_row": "> **{subject}** · {files} file(s) · went to "
                               "**{into}** · match {score} ({space})",
        # Card (c) / LL-PHO-105 — an accept an owner reads is never quoted
        # without the space it was decided in. `subject_verdict_spaces` said
        # `clip` for everything until 3d229f0 and every verdict in the first
        # user test was read as identity while being CLIP.
        #
        # ⛔ THREE KEYS, not three literals in the renderer. A pack that
        # translated `review_absorbed_row` would otherwise get an English
        # `{space}` interpolated into its own translated sentence — a
        # half-translated line, which is worse than an untranslated one
        # because it reads as deliberate. Same argument as
        # `review_unnamed_subject_since` wrapping the marker.
        "review_absorbed_space_identity": "identity space",
        "review_absorbed_space_clip": "clip space",
        # ⛔ A WORD, never a dash. A dash reads as missing data; the fact is
        # that no space was recorded — which is a thing the row says, not a
        # thing it fails to say. ⛔ It is never filled in later by guessing
        # `clip` because it probably was: that is a space nobody measured,
        # presented as if somebody had.
        "review_absorbed_space_unrecorded": "space not recorded",
        "review_effect_line": "**Effect if answered:** {effect}",
        # SNS-13 — the disclosure line, and it states the PERMANENT part. The
        # file count is what a group covers only while the group survives the
        # answer: picking some of its frames onto separate rows splits it, and
        # SNS-1b item 4 then voids the bulk attribution, so the files nobody
        # looked at go back to the class word and re-earn a name one at a time.
        # Promising all {files} would be a promise this engine breaks on the
        # one answer it most wants the owner to feel safe giving.
        "review_effect_group_it": "up to {files} file(s) stop being labelled "
                                  "with a generic class word and take the name "
                                  "of the group they are in — most of them "
                                  "matched by similarity, not shown to you "
                                  "here. Splitting a group with your picks "
                                  "keeps only the frames you chose: the rest "
                                  "go back to the class word and earn a name "
                                  "one file at a time. Each named group "
                                  "becomes a remembered subject, recognised "
                                  "the next time a photo of it is seen, and no "
                                  "longer asked about: answering this is what "
                                  "stops the question.",
        "review_hint_pick": "the frame numbers that are one subject, e.g. "
                            "1,3,7 — frames from one group split it, frames "
                            "from different groups join them",
        "review_hint_who": "relation to you — pet / wife / mother / family / "
                           "friend / colleague / self",
        "review_hint_name": "what you actually call them",
        # FIX6 (U6-14, U6-19) — the text answer route, said on the page itself.
        "review_page_answer_line": "An answer written as text for this page "
                                   "starts with this line: `page: {page}` "
                                   "(the web page's copy lines already carry it).",
        "review_more_rows": "One row per animal: copy a row for each more animal. "
                            "Two animals in one photo take two rows with the "
                            "same photo number.",
        "review_hint_skip": "frame numbers that are not subjects, then the "
                            "word confirm on the same line — not asked about "
                            "again while this pack remembers the rejection. "
                            "Add not-a-subject if the photo holds no animal "
                            "at all (a fire, a cushion, a shadow), as opposed "
                            "to an animal that simply is not yours",
        # U2-10 — the two rejections, told apart on the page that lists them.
        # An owner scanning this list has to be able to see which of their own
        # decisions was which; before this they read identically.
        "review_rejected_basis_not_mine": "an animal, but not yours",
        "review_rejected_basis_not_a_subject": "not an animal at all",
        "review_contact_note": "{n} example photo(s) the model actually looked "
                               "at",
        # SNS-1 — the frame is the unit the owner answers with, so its number
        # sits beside the photograph rather than being counted out by eye.
        "review_frame_number": "[frame {n}]",
        "review_frame_not_animal": "If one of these is not a real animal — a "
                                   "picture in a frame, a reflection — put its "
                                   "number on the `skip:` row with "
                                   "not-a-subject, e.g. `skip: {ref} "
                                   "not-a-subject`: it stops counting as an "
                                   "animal, and nothing is rejected.",
        # B4 — what the photo behind a frame is ALREADY named. A new name typed
        # for it replaces that one, which the owner could only learn from the
        # confirm's dry run, after answering.
        "review_frame_named": "frame {n} is already named {names} — a name "
                              "given to it here replaces that",
        # R3b — the per-frame evidence the page did not supply. A tile is a
        # claim that some photographs are one subject; without this the owner
        # can only accept or refuse it whole, which is how three wrong
        # exemplars were confirmed in one gesture.
        "review_frame_shared": "⚠️ {n} animals in this frame. Each crop is "
                               "shown above. To give each animal its name, "
                               "put the photo number on one row per name: "
                               "`pick: {frame}` with one name, and a second "
                               "row `pick: {frame}` with the other — never "
                               "`pick: {frame}.1`. It is never kept as an "
                               "example of what either one LOOKS like, "
                               "because one photograph cannot stand for two "
                               "different animals.",
        # F10 — where each FRAME was taken, never the batch's place: a batch
        # is a day, and the evening at home rides along with the day out.
        # A label and a distance only; a coordinate never reaches the page.
        "review_frame_where_home": "taken at {home}",
        "review_frame_where_home_unlabelled": "taken at a registered home "
                                              "(no label in the pack)",
        "review_frame_where_away": "taken {km} km from {home}",
        "review_frame_where_away_unlabelled": "taken {km} km from the "
                                              "nearest registered home",
        "review_frame_where_no_home": "location known, but the pack has no "
                                      "home to measure it from",
        "review_frame_where_none": "no location — this file carries no GPS",
        "review_frame_where_unknown": "location not checked — this photo's "
                                      "scan is not in its work dir",
        # U2-12 — the GROUP-level counterpart of review_frame_shared. That
        # one says a single photograph holds two animals; this one says two
        # photographs the page is asking about as ONE subject do not look
        # like the same animal as each other.
        "review_group_incoherent": "⚠️ The example photos for this one do not "
                                   "all look like the same animal. Frames {a} "
                                   "and {b} are the furthest apart. Compare "
                                   "them AGAINST EACH OTHER before you answer: "
                                   "if they are two animals, split them with a "
                                   "`pick:` row for each — one name here would "
                                   "land on both.",
        "review_frames_unresolved": "⚠️ {n} more example photo(s) for this "
                                    "subject are not shown and cannot be "
                                    "picked ({why}). Nothing is lost — they "
                                    "come back at a later checkpoint.",
        "review_contact_missing": "no example photo is on disk for this subject "
                                  "yet",
        # D-27 — the qualifier said BEFORE the owner types, not after they
        # fail. The requirement itself is sound and stays: a repeated name
        # genuinely is ambiguous — the same animal, or a second animal with
        # the same name? — and only the owner knows. What was wrong is that
        # the page offered a blank `name:` row, said nothing, and the owner
        # discovered the rule by having their answer refused.
        #
        # ⛔ Rendered ONLY when the pack actually holds a confirmed name, so a
        # first run never sees it: with nothing to collide with, the rule
        # cannot fire and the sentence would be pure noise on the one page
        # that is already the longest thing a new owner reads.
        #
        # ⚠️ `{same}` and `{distinct}` arrive as fields because the tokens are
        # ASCII and UNTRANSLATED — a parser that depended on a translated word
        # would break the moment somebody translated it — while the sentence
        # around them is the owner's. A pack translates the sentence and
        # places the tokens; it never spells them.
        "review_name_taken": "⚠️ Already the name of a subject you confirmed: "
                             "{names}. Reusing one is allowed, and the page "
                             "cannot tell which you mean — so say: "
                             "`name: {example} {same}` if it IS that subject, "
                             "or `name: {example} {distinct}` if it is a "
                             "different one that shares the name. A repeated "
                             "name with neither is refused.",
        "review_skip_note": "Leaving a frame out of every row is free — that "
                            "draft stays a draft, keeps working, and comes back "
                            "at a later checkpoint if its evidence grew. "
                            "`skip:` is the opposite: no later checkpoint asks "
                            "again, which is why it is the one row that asks "
                            "you to type the word confirm beside the numbers. "
                            "Nothing here has copied a file.",
        "review_asked_before": "already asked at checkpoint C{n}; repeated here "
                               "because its evidence grew",
        # SNS-5 / SNS-6 — the re-presentation section. Every remembered
        # subject comes back every round, whether or not new evidence
        # arrived, because an evidence-gated re-presentation cannot reach the
        # one mistake that matters: a subject named wrongly and never
        # photographed again.
        "review_remembered_header": "### Remembered already — check these are "
                                    "still right",
        "review_remembered_intro": "Nothing below has to be answered. A blank "
                                   "row means \"still right\" and writes "
                                   "nothing. These are here so a name you gave "
                                   "once is never out of reach.",
        "review_remembered_line": "**{subject}** · {files} file(s) / {batches} "
                                  "batch(es)",
        # A19. Appended to the line above, never folded into it: `{files}`
        # keeps meaning exactly what it has always meant, so no pack needs
        # re-translating and no fixture that shows a subject with none of
        # these moves. Rendered only when the count is above zero.
        "review_remembered_ungated": " — {files} of those were matched to this "
                                     "name outside the dates it is remembered "
                                     "from, without being asked about",
        "review_worst_frame_note": "shown because this is the photo this "
                                   "subject matches its own memory LEAST well "
                                   "({scores}) — the frame that looks right "
                                   "would prove nothing. A score near 1.000 "
                                   "usually means every photo it remembers is "
                                   "also a photo it was taught from; the check "
                                   "sharpens as it is seen again.",
        "review_frames_unscored": "⚠️ {n} of this subject's sightings could not "
                                  "be scored ({why}). Any frame above with no "
                                  "score beside it is the record's own order "
                                  "and NOT the least certain photo — a frame "
                                  "with no score is not a check.",
        "review_no_frame": "no photo of this subject can be shown here "
                           "({why}), so there is nothing to check by eye.",
        "review_recheck_hint": "leave blank if it is still right · type "
                               "withdraw to take the name back and be asked "
                               "again · type revive to take a rejection back",
        # SNS-14's door, and it needs its OWN key rather than a longer
        # `review_recheck_hint`. A pack that already overrides the hint above
        # would keep the sentence it wrote, which never mentions names — so an
        # owner who translated the round once would be the one owner never told
        # the rename exists. A new key reaches every pack, translated or not.
        "review_recheck_not_hint": "or type not and the frame number of a "
                                   "photo that is NOT this one (e.g. not 3) "
                                   "to take just that photo out of its memory "
                                   "and keep the name",
        # HIL-4 (owner ruling 20261001) — the two steps for a photo holding several
        # pets, the SAME sentences on the text page and on the web page.
        # The pick mechanism is unchanged and `pick: N.M` is still refused.
        "review_howto_step1": "Step 1. Put every photo with your pet in that "
                              "pet's row (its group on the web page), even "
                              "when one photo holds several pets: one row per "
                              "pet, with the same photo number. Name the "
                              "animal in the picture shown. If the picture "
                              "shows a different pet than one you know is in "
                              "the photo, leave the photo out of that pet's "
                              "row.",
        "review_howto_step2": "Step 2. Then look at each crop. If a crop is "
                              "not a real animal (a toy, a cushion, a "
                              "picture), mark it not-a-subject: tick \"not a "
                              "real animal\" under it on the web page, or "
                              "write `skip: 2.1 not-a-subject` in text. An "
                              "animal that is simply not yours is \"Not my "
                              "pet\" instead (`skip: 3 confirm`).",
        # Q3 (Lead 20261001) — a re-presented photo no animal index covers
        # is shown whole, and the page says so: never a silent fallback.
        "review_frame_whole_note": "Photo {n} is the whole photo: no animal "
                                   "index for the dump it came from is on "
                                   "this computer, so no crop could be cut.",
        # Lead ruling 20261001 (frame 13) — a remembered photo holding 2+
        # animals carries no crop of the pet: it is a photo the pet is IN.
        "review_frame_shared_remembered": "Photo {n} holds {count} animals. "
                                          "It is remembered as a photo "
                                          "{subject} is in, never as what "
                                          "{subject} looks like.",
        # HIL-5 — the row filled in, with THIS pet's id and a photo number
        # printed above it: an owner who only reads the hints did not know
        # what to type. Visible, never inside the row's comment.
        "review_recheck_example": "Not sure what to type? If photo {n} is "
                                  "not {subject}, write the row as "
                                  "`recheck: {sid} not {n}`. Leave it blank "
                                  "if every photo above is {subject}.",
        "review_recheck_name_hint": "or type a new name to correct this one · "
                                    "if that name is one this pack already "
                                    "remembers you will be asked which you "
                                    "mean: add same after it to make the two "
                                    "one subject, or distinct to keep them "
                                    "apart",
        "review_frame_why_no_index": "the dump these photos came from is no "
                                     "longer on disk",
        "review_frame_why_re_embedded": "the photos were re-embedded and no "
                                        "longer carry the vector that was "
                                        "looked at",
        "review_frame_why_no_exemplar": "this subject holds no exemplar vector "
                                        "to score a frame against",
        "review_frame_why_no_looks": "the record kept no look with a vector "
                                     "behind it",
        "review_frame_why_two_looks": "two different sightings were kept under "
                                      "the same file name, so which photo this "
                                      "frame is cannot be decided",
        "review_frame_why_no_thumbnail": "the example photo behind the sighting "
                                         "is no longer on disk",
        "review_frame_why_vectors_broken": "this subject's exemplar vectors and "
                                           "its record are out of step",
        # OA-14's other half. A rejection is a question the owner CLOSED, so
        # re-showing its frames would re-ask it — one line each, and the
        # separate section is what stops a name-check glance from reviving
        # something by accident.
        "review_rejected_header": "### Not subjects — you asked never to be "
                                  "asked again",
        "review_rejected_intro": "No photos are shown for these: you closed "
                                 "the question and showing it again would be "
                                 "asking it again. They are listed because "
                                 "each one now actively stops a question, and "
                                 "nothing that permanent should be invisible.",
        "review_rejected_line": "{subject} · {files} file(s) / {batches} "
                                "batch(es) · rejected {at}",
        "review_rejected_no_centroid": "⚠️ this rejection kept nothing to "
                                       "recognise itself by, so the next dump "
                                       "will draft the same subject under a "
                                       "new id and ask again.",
    },
}


# Every sentence `photo_settings.py` puts in front of a human (SET-1). A third
# table rather than more keys in MESSAGE_VOCAB, for the reason REVIEW_VOCAB is
# separate: the settings surface is NEW, so it has no shipped output to
# reproduce and therefore no legacy locale. Rule 8 applies with nothing pulling
# against it — the engine ships English, any other language arrives from the
# pack under `settings_messages`.
#
# The SETTING KEYS themselves (`models.classify`, `naming.max_units`) are ASCII
# and are NOT in this table, for the same reason the review table's field keys
# are not: they are what an owner types and what the pack file stores, and a
# key that changes with the language is not a key.
SETTINGS_VOCAB = {
    "en": {
        "settings_h_key": "setting",
        "settings_h_value": "value",
        "settings_h_layer": "from",
        "settings_h_tag": "changing it",
        "settings_layer_default": "engine default",
        "settings_layer_pack": "your pack",
        "settings_layer_collection": "this collection",
        "settings_layer_flag": "a flag on this command",
        # The four blast tags (ONB-10 corollary: say whether a change moves
        # files or only edits a label). The NAME is what the table prints; the
        # LINE is what `explain` says about it.
        "settings_tag_moves_files": "moves files",
        "settings_tag_label_only": "labels only",
        "settings_tag_cost_only": "cost only",
        "settings_tag_schedule_only": "schedule only",
        "settings_tagline_moves_files": "⚠️ This changes where future runs "
                                        "copy your photos. Files already "
                                        "copied stay where they are — nothing "
                                        "is moved or deleted retroactively.",
        "settings_tagline_label_only": "This changes how a folder is NAMED, "
                                       "not which folder a photo goes into.",
        "settings_tagline_cost_only": "This changes what a run costs in time "
                                      "or tokens. It does not move a file or "
                                      "rename a folder.",
        "settings_tagline_schedule_only": "This affects the unattended "
                                          "schedule only.",
        "settings_read_only": "read-only",
        # One sentence per setting. `explain` prints it; `show --verbose`
        # prints it under the row.
        "settings_why_models_classify": "Which model looks at your photos and "
                                        "says what is in them. It has a floor: "
                                        "a weaker model made up things it had "
                                        "not seen, so the floor is policy, not "
                                        "a preference. You may set a stronger "
                                        "one.",
        "settings_why_models_copy_conductor": "Which model runs the copy "
                                              "stage. Any is safe: the script "
                                              "copies the bytes and checksums "
                                              "them, the model only reports.",
        "settings_why_models_embed_local": "The local model that builds the "
                                           "visual index. It runs on this "
                                           "machine and costs nothing per "
                                           "photo. Changing it forces a full "
                                           "re-index.",
        "settings_why_visual_embed_coverage": "Every photo is indexed, always. "
                                              "This is shown so you can see "
                                              "it, and it cannot be changed: "
                                              "how often something recurs "
                                              "cannot be measured on a sample.",
        "settings_why_sampling_gps_pct": "What share of a batch WITH location "
                                         "data is looked at by the vision "
                                         "model.",
        "settings_why_sampling_no_gps_pct": "What share of a batch WITHOUT "
                                            "location data is looked at. A "
                                            "batch with no location leans on "
                                            "its contents alone.",
        "settings_why_sampling_min_samples": "Never look at fewer than this "
                                             "many photos in a batch, however "
                                             "small the share works out to.",
        "settings_why_sampling_max_samples": "Never look at more than this "
                                             "many photos in one batch.",
        "settings_why_naming_smart_scenario": "Off, a folder is named after "
                                              "the date, the place and the "
                                              "kind of trip. On, it may also "
                                              "describe the scene and who is "
                                              "in it. Turning it off is the "
                                              "way back: every folder falls to "
                                              "the plainer name with no "
                                              "re-planning.",
        "settings_why_naming_max_units": "The hard cap on how long a folder "
                                         "name may get. A name over the cap is "
                                         "refused rather than trimmed.",
        "settings_why_naming_soft_target_units": "The length the name "
                                                 "generator aims for. It stays "
                                                 "at or below the hard cap.",
        "settings_why_naming_max_names_in_folder": "How many subjects may be "
                                                   "named in one folder name "
                                                   "before a collective word "
                                                   "is used instead.",
        "settings_why_schedule_enabled": "Whether an unattended run is "
                                         "scheduled. Read-only here — the "
                                         "schedule wizard owns it.",
        "settings_why_schedule_window": "The hours an unattended run may use. "
                                        "Read-only here — the schedule wizard "
                                        "owns it.",
        # units, per N-2: a number whose unit is unstated is not a number the
        # owner can act on
        "settings_units_note": "Counted in name units, not characters: the "
                               "date and the place are excluded, `_` and `+` "
                               "cost nothing, one Chinese full-width character "
                               "is one unit and one English word is one unit.",
        # refusals — every one says what to do instead
        "settings_refuse_unknown_key": "There is no setting called {key}. "
                                       "`show` lists every setting there is.",
        "settings_refuse_read_only": "{key} is shown, not set. {why}",
        "settings_refuse_below_floor": "{key} may not be set to {value}: the "
                                       "floor is {floor}. A weaker model "
                                       "described photos it had never seen, so "
                                       "this floor is a policy and the tool "
                                       "will not step around it. Accepted: "
                                       "{accepted}.",
        "settings_refuse_unknown_model": "{key} does not recognise {value}. "
                                         "Accepted: {accepted}. A name this "
                                         "tool cannot place on the ladder "
                                         "cannot be shown to meet the floor, "
                                         "so it is refused rather than "
                                         "assumed.",
        "settings_refuse_not_a_bool": "{key} is on or off. Say one of: {accepted}.",
        "settings_refuse_not_a_number": "{key} takes a number; {value} is not "
                                        "one.",
        "settings_refuse_out_of_range": "{key} must be between {low} and "
                                        "{high}; {value} is outside that.",
        "settings_refuse_order": "{key} would be {value}, which is above "
                                 "{other_key} ({other}). The first can never "
                                 "exceed the second.",
        "settings_refuse_empty": "{key} needs a value.",
        "settings_refuse_no_pack": "There is no pack to write to. Settings are "
                                   "your data and live in your pack, never in "
                                   "the engine — run onboarding first, or "
                                   "point at a pack with --profile.",
        "settings_refuse_collection_layer": "Settings are written to your pack. "
                                            "No stage reads settings out of "
                                            "collection.json yet, so writing "
                                            "one there would change nothing.",
        # what a change does and does not do
        "settings_plan_change": "{key}: {old} → {value} ({layer})",
        "settings_dry_run": "Nothing was written. Re-run with --go to save it.",
        "settings_written": "Saved to {path}.",
        "settings_no_change": "{key} is already {value}. Nothing to do.",
        "settings_collection_not_read": "⚠️ this value is in collection.json, "
                                        "and no stage reads settings from "
                                        "there yet — the run will use {value} "
                                        "from {layer} instead.",
        "settings_flag_layer_note": "A flag on a stage command wins over "
                                    "everything here, for that one run only.",
        # A switch that does nothing is worse than a switch that is missing:
        # the owner sets it, sees no change, and concludes the tool is broken.
        "settings_not_built_yet": "⚠️ not in use yet — this is stored, and no "
                                  "stage reads it, so setting it changes "
                                  "nothing today.",
        "settings_pack_line": "pack: {owner} · {path}",
        "settings_no_pack_line": "no pack bound — every value below is the "
                                 "engine's own default.",
    },
}


def settings_messages(profile):
    """-> {key: format string} for the settings surface.

    Two-step like `review_messages()`, and for the same reason: this artifact
    never had a before, so an unknown language and no pack at all both resolve
    to English. An owner who wants another supplies `settings_messages` in
    their pack."""
    lang = get(profile, "language") or "en"
    table = SETTINGS_VOCAB.get(lang, SETTINGS_VOCAB["en"])
    named = get(profile, "settings_messages", default=None) or {}
    return {**table, **named}


SCHEDULE_VOCAB = {
    "en": {
        # what the wizard asks (§3C: collection · window · cadence · notify)
        "sched_collection": "which photos",
        "sched_window": "off-hours window",
        "sched_at": "starts at",
        "sched_notify": "morning message",
        "sched_label": "job name",
        "sched_model_pinned": "classify model (pinned)",
        "sched_notify_telegram": "Telegram, sent by the run itself",
        "sched_notify_none": "none — the log file is the only record",
        # state
        "sched_not_configured": "No unattended run is set up. "
                                "`install` sets one up.",
        "sched_configured": "Configured in your pack:",
        "sched_installed": "Installed and loaded. Next run: {when}.",
        "sched_installed_paused": "Installed but PAUSED — it will not run "
                                  "until you `resume`.",
        "sched_not_installed": "Not installed on this machine yet. The "
                               "settings below are stored; nothing runs.",
        "sched_last_run": "Last run: {when} (exit {code}).",
        "sched_never_run": "It has not run yet.",
        "sched_log": "Log: {path}",
        # the HIL-stop rule — the whole point of the card
        "sched_hil_rule": "An unattended run stops before anything is copied. "
                          "It sorts and groups your photos and writes the plan "
                          "for you to read — then it waits. Nothing is copied "
                          "to your drive while you are asleep, so a folder "
                          "name nobody checked is never created.",
        "sched_hil_waiting": "Waiting for you: {what}",
        "sched_hil_waiting_none": "Nothing is waiting for you.",
        "sched_waiting_plan_review": "{n} plan(s) rendered and waiting to be "
                                     "read, in {where}",
        "sched_waiting_memory": "a memory review page waiting for your "
                                "answers, in {where}",
        "sched_waiting_screens": "{n} screen size(s) found in {where} that "
                                 "the pack has not answered ({sizes}) — make "
                                 "the onboarding sheet for it and answer its "
                                 "screen: line: {command}",
        "sched_morning_next_step": "When you are happy with the plan, copy it "
                                   "with: {command}",
        # rendering / installing
        "sched_would_write": "Would write:",
        "sched_wrote": "Wrote:",
        "sched_would_load": "Would load the job into launchd as {label}.",
        "sched_loaded": "Loaded into launchd as {label}.",
        "sched_dry_run": "Nothing was written or loaded. Re-run with --go.",
        "sched_paused": "Paused {label}. The files are kept — `resume` starts "
                        "it again.",
        "sched_resumed": "Resumed {label}.",
        "sched_removed": "Removed {label} and deleted the files it used.",
        "sched_would_remove": "Would unload {label} and delete the files it "
                              "used.",
        # refusals — each says what to do instead
        "sched_refuse_not_macos": "The unattended schedule uses launchd, which "
                                  "is macOS only. This machine is {platform}, "
                                  "so there is nothing here to install. It is "
                                  "said plainly rather than half-supported: a "
                                  "cron job written here would not behave the "
                                  "same way, and you would find out at 3am.",
        "sched_refuse_no_pack": "There is no pack to store the schedule in. "
                                "The schedule is your data and lives in your "
                                "pack, never in the engine — run onboarding "
                                "first, or point at a pack with --profile.",
        "sched_refuse_no_collection": "Say which photos to work on with "
                                      "--collection. It is the folder holding "
                                      "collection.json, the one photo-init "
                                      "made for you.",
        "sched_refuse_collection_missing": "There is no collection.json in "
                                           "{path}. That folder is not a "
                                           "collection workspace.",
        "sched_refuse_bad_window": "--window takes two times like 01:00-06:00; "
                                   "{value} is not that.",
        "sched_refuse_bad_time": "--at takes a time like 03:05; {value} is not "
                                 "that.",
        "sched_refuse_outside_window": "{value} is outside the off-hours "
                                       "window {window}. The window is the "
                                       "promise that the run never competes "
                                       "with you for the machine, so a start "
                                       "time outside it is refused rather than "
                                       "quietly moved.",
        "sched_refuse_no_at": "Say when it should start with --at, like "
                              "--at 03:05. It must fall inside {window}.",
        "sched_refuse_not_installed": "{label} is not installed, so there is "
                                      "nothing to {action}.",
        "sched_refuse_already": "{label} is already installed. `remove` it "
                                "first, or `pause` it if you only want it to "
                                "stop for now.",
        "sched_refuse_no_claude": "The unattended run drives Claude Code, and "
                                  "`claude` was not found on this machine. "
                                  "Install it, or pass --claude with the path "
                                  "to it.",
        "sched_launchctl_failed": "launchctl refused: {detail}",
        # MEASURED 20260901, not inferred: a launchd agent reading a file
        # under a TCC-protected folder blocks in open() forever instead of
        # failing. Same job, same interpreter, script under /private/tmp
        # finished in under a second; under ~/Documents it was still blocked
        # three hours later. It has to be said at install, because at 3am
        # there is nobody to notice a job that never returns.
        "sched_warn_protected": "⚠️ A scheduled run may not be able to read "
                                "these, and would HANG rather than fail:",
        "sched_warn_protected_path": "  {path} — inside {folder}, which macOS "
                                     "protects",
        "sched_warn_protected_fix": "macOS asks permission before a "
                                    "background job reads Documents, Desktop "
                                    "or Downloads, and at 3am there is nobody "
                                    "to answer — so it waits forever. Fix it "
                                    "once, either way: give Full Disk Access "
                                    "to /bin/zsh in System Settings → Privacy "
                                    "& Security, or keep the engine and the "
                                    "photos outside those three folders. "
                                    "Until then this job may do nothing and "
                                    "say nothing.",
        "sched_run_never_reported": "⚠️ The last run started and never "
                                    "reported. That is what a permission "
                                    "block looks like — see the note about "
                                    "protected folders above.",
    },
}


def schedule_messages(profile):
    """-> {key: format string} for the schedule wizard.

    Two-step like `settings_messages()` / `review_messages()`, and for the same
    reason: this surface never had a before, so an unknown language and no pack
    at all both resolve to English. An owner who wants another supplies
    `schedule_messages` in their pack."""
    lang = get(profile, "language") or "en"
    table = SCHEDULE_VOCAB.get(lang, SCHEDULE_VOCAB["en"])
    named = get(profile, "schedule_messages", default=None) or {}
    return {**table, **named}


def review_messages(profile):
    """-> {key: format string} for the memory review table.

    Two-step, not three: `messages()` has a LEGACY step because an unbound run
    has to keep emitting the strings it emitted before language was a
    variable. This artifact never had a before, so there is nothing to
    reproduce — an unknown language and no pack at all both resolve to
    English, and an owner who wants another one supplies `review_messages` in
    their pack."""
    lang = get(profile, "language") or "en"
    table = REVIEW_VOCAB.get(lang, REVIEW_VOCAB["en"])
    named = get(profile, "review_messages", default=None) or {}
    return {**table, **named}


# A pack's valid_from / valid_until may be a year, a month or a day. All three
# are compared against a capture date by prefix, so the window needs no date
# parser — and a bound in any other shape is not one of these three.
HOME_BOUND = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def home_bound(value):
    """A `valid_from`/`valid_until` the prefix comparison can use, else None
    (open-ended). Anything unreadable resolves to open-ended deliberately: a
    home that suppresses a day too long costs one folder name, a home that
    stops suppressing costs the privacy rule."""
    return value if isinstance(value, str) and HOME_BOUND.match(value) else None


def home_points(profile, home_range_only=False):
    """The owner pack's `home_locations`, as (lat, lon, valid_from, valid_until).

    ⭐ D-F9 (20260906) REVERSES the line that used to stand here — "`label` is
    deliberately not read". It is read now, by `labelled_home_points()` below
    and through it by `photo_cluster.batch_places`, because the owner settled
    that a home batch is named from the OWNER'S OWN WORD rather than from the
    map. The old reasoning was half right and is kept where it still holds:
    suppression runs on COORDINATES ALONE, so an entry the owner has not named
    yet is still never given an invented name — it simply falls through to the
    administrative city lookup, which is R13's behaviour unchanged.

    THIS function keeps its 4-tuple shape on purpose: three callers unpack it
    (photo_where.py:461, photo_cluster.py:517 and :522) and none of them wants
    a label. Widening it here to serve one new reader would put a field that
    may be printed into the hands of the two callers whose whole job is to
    refuse to print anything.

    A row that cannot be read is a hard failure rather than a skipped row —
    skipping one turns the privacy rule off with no sign that it happened. An
    absent or empty key is the ordinary no-pack case, not a malformed one.

    ⛔ `home_range_only` NARROWS THE BATCH LABEL, NEVER THE PRIVACY RULE.
    A home may carry `home_range: false` to say "this address is mine, but a
    day spent here is not my everyday home range" — an owner's parent's house
    is the case it was added for. `photo_cluster` passes True so such a place
    still reads as a trip; `photo_where` MUST keep passing False, because
    every home suppresses its own name whatever this flag says. Wiring the
    filter into the privacy caller would silently un-suppress a real
    residence, which is the one failure this pack key exists to prevent.
    An absent `home_range` means True — a pack written before the key existed
    keeps every home it had.
    """
    return [row[:4] for row in labelled_home_points(profile, home_range_only)]


def labelled_home_points(profile, home_range_only=False):
    """The same rows as `home_points()`, plus the owner's `label` or None and
    the home's D-I15 id or None (`place_ids()`).

    ⭐ D-F9. The sibling accessor, not a replacement: naming is the only thing
    that may read a label, so the label is only on the list naming reads. The
    id rides here for the same reason, and `home_points()`'s `[:4]` slice keeps
    both away from the privacy callers.

    A label that is missing, not a string, or blank comes back as None and the
    caller falls to the administrative lookup. That is deliberately NOT a hard
    exit, unlike an unreadable `lat`/`lon`: an unreadable coordinate would
    switch the privacy rule off, while an unreadable label costs at most one
    map call and a city-level name the owner can improve by editing the pack.
    """
    entries = get(profile, "home_locations", default=None)
    if entries is None:
        return []
    if not isinstance(entries, list):
        sys.exit("owner pack: home_locations must be a list of "
                 "{label, lat, lon, ...} entries")
    ids, problems = place_ids(entries, HOME_LOCATIONS_KEY)
    homes = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            sys.exit(f"owner pack: home_locations[{i}] is not an entry object "
                     "— expected {label, lat, lon, ...}")
        point = []
        for field in ("lat", "lon"):
            try:
                point.append(float(entry[field]))
            except (KeyError, TypeError, ValueError):
                sys.exit(f"owner pack: home_locations[{i}] has no usable "
                         f"{field!r} — fix the entry rather than dropping it. "
                         "A home the engine cannot read is a home it names.")
        if home_range_only and entry.get("home_range") is False:
            continue
        label = entry.get("label")
        label = label.strip() if isinstance(label, str) else None
        homes.append((point[0], point[1], home_bound(entry.get("valid_from")),
                      home_bound(entry.get("valid_until")), label or None,
                      ids[i]))
    announce_place_ids(problems)
    return homes


def name_budget(profile):
    """-> (hard, soft) for N-2, from the pack.

    📐 Both are `{n}` PARAMETERS. `photo_name` carries working defaults so the
    grammar module stays stdlib-only and usable with no pack at all (a
    benchmark, a first run); an owner who names longer folders raises
    `naming_spec.name_budget` and no engine code moves.

    ⛔ A caller must read them through here rather than from
    `photo_name.DEFAULT_NAME_BUDGET_*`. Reading the constant is how a pack's
    value silently stops being consulted — the same shape as D-07, where
    `photo_where` held its own idea of the owner's camera make while
    `photo_sample` read the pack, and a whole dump lost its place names at
    exit 0.

    A value that is not a positive integer falls back rather than raising: a
    malformed budget must not stop a run from naming folders, and the shipped
    numbers are the SPEC's own."""
    import photo_name
    declared = get(profile, "naming_spec", "name_budget", default=None) or {}

    def number(key, fallback):
        value = declared.get(key)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return fallback
        return value if value > 0 else fallback

    return (number("hard", photo_name.DEFAULT_NAME_BUDGET_HARD),
            number("soft", photo_name.DEFAULT_NAME_BUDGET_SOFT))


def country(profile):
    """-> the owner's primary home country as the pack declares it (`country`,
    ISO 3166-1 alpha-2, upper case), or None when the pack does not say.

    K20 (owner ruling, 20261001): the OWNER confirms it — onboarding asks "mark this
    country as your primary home country?" after a home is confirmed, from a
    list; nothing is looked up online. ONE country per owner: a home outside
    it is still abroad (U2-04). The default for an undeclared pack lives in
    `photo_cluster.owner_country()`, beside the country boxes it reads.
    ⛔ A malformed value stops the run, like a malformed home row: guessing
    a country decides which days are "abroad"."""
    value = get(profile, "country")
    if value is None:
        return None
    if not (isinstance(value, str) and re.fullmatch(r"[A-Za-z]{2}", value.strip())):
        sys.exit("the owner pack's `country` must be a two-letter country code "
                 "(ISO 3166-1, for example TW or US); fix it in photo-profile.json")
    return value.strip().upper()


def get(profile, *keys, default=None):
    cur = profile
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="show the pack a run would load")
    ap.add_argument("workdir", nargs="?")
    ap.add_argument("--profile")
    args = ap.parse_args()
    pack = resolve_pack(workdir=args.workdir, explicit=args.profile)
    print(json.dumps({"owner": pack.owner,
                      "dir": str(pack.dir) if pack.dir else None,
                      "source": pack.source,
                      "snapshot": pack.snapshot(),
                      "keys": sorted(pack.profile)}, ensure_ascii=False, indent=2))

    # naming_spec.types is a hard gate at classify time, and it only fails at
    # the moment somebody tries to use a missing word. If this run points at a
    # scanned dump, say now which vocabulary already in use the pack lacks.
    types = get(pack.profile, "naming_spec", "types")
    batches = Path(args.workdir) / "batches.json" if args.workdir else None
    if types and batches and batches.exists():
        used = {b["type"] for b in json.loads(batches.read_text()).get("batches", [])
                if b.get("type")}
        drift = sorted(used - set(types))
        if drift:
            print(f"\n⚠️  in use in this dump but missing from naming_spec.types: "
                  f"{' '.join(drift)}\n   classify will reject them until the pack "
                  f"lists them.")
