#!/usr/bin/env python3
"""SET-1 — a safe editor over the settings that already live in the owner's
pack. The script reads, resolves, validates and writes; the SKILL talks.

  python3 photo_settings.py show [--workdir W] [--profile P] [--flag k=v] [-v]
  python3 photo_settings.py explain <key> [--workdir W] [--profile P]
  python3 photo_settings.py set <key> <value> [--workdir W] [--profile P] --go

Exit 0 = the command answered. A refused `set` exits 2, so a caller can tell
"I would not do that" from "something broke".

Five things this file is careful about.

**Settings are OWNER data.** They live in the pack, never here (ONB-10 /
rule 7). This module holds the engine's own narrow defaults, the shape of each
key and the rules for a legal value — nothing about any particular owner.

**Every setting carries a blast tag** (ONB-10's corollary, verbatim: *say
whether a change moves files or only edits a label*). The tag is printed in
`show`, and `explain` prints the sentence behind it. `moves-files` is the tag
that matters: a setting that changes how a folder is NAMED changes which
folder a future run copies a photo into.

**The layers, in order: engine default → pack → collection → a flag on the
run.** ⚠️ The collection layer is resolved and displayed here, but no stage
script reads a setting out of `collection.json` today — every one of them
resolves through `photo_profile.get(profile, ...)`, which is the pack alone.
So a value found there is shown with a warning saying the run will not use it,
and `set --layer collection` is refused rather than silently doing nothing.
The layer is not dropped, because the design says it exists and a display that
hid it would hide the discrepancy too.

**One key the §3D table lists is deliberately absent, and so is its
replacement.**
`naming.named_subject_budget` is NOT offered: the `{10}` cap was amended away
(N-9, 2026-08-15) and there is now no cap on how many subjects may be
remembered, so offering the knob would reinstate a limit the project removed.
What replaced it is `named_subjects_warn_at` — a warning threshold, not a cap
— and that one lives in the subject registry's `defaults` in `subjects.json`,
not in the profile. Surfacing it means a second store with its own writer, and
`Registry.save()` owns that file; it is a follow-up, not a line here.

**The model floor is not a preference.** `models.classify` may be raised and
not lowered (L01, after the 2026-07-20 fabrication incident). A model name
this file cannot place on the ladder is REFUSED for that key rather than
assumed to clear the floor — the ladder is engine code because the floor is
engine policy, and a stronger model reaches it by being added here.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import photo_profile  # noqa: E402

# ---------------------------------------------------------------- tags -----
# ASCII ids. What a human reads is resolved from the pack's vocabulary, like
# every other word this engine prints.
MOVES_FILES = "moves-files"
LABEL_ONLY = "label-only"
COST_ONLY = "cost-only"
SCHEDULE_ONLY = "schedule-only"

TAG_MESSAGE_KEY = {MOVES_FILES: "settings_tag_moves_files",
                   LABEL_ONLY: "settings_tag_label_only",
                   COST_ONLY: "settings_tag_cost_only",
                   SCHEDULE_ONLY: "settings_tag_schedule_only"}
TAGLINE_MESSAGE_KEY = {MOVES_FILES: "settings_tagline_moves_files",
                       LABEL_ONLY: "settings_tagline_label_only",
                       COST_ONLY: "settings_tagline_cost_only",
                       SCHEDULE_ONLY: "settings_tagline_schedule_only"}

# --------------------------------------------------------------- layers ----
DEFAULT, PACK, COLLECTION, FLAG = "default", "pack", "collection", "flag"
LAYER_MESSAGE_KEY = {DEFAULT: "settings_layer_default",
                     PACK: "settings_layer_pack",
                     COLLECTION: "settings_layer_collection",
                     FLAG: "settings_layer_flag"}
# Lowest first. The last layer holding a value wins.
LAYER_ORDER = (DEFAULT, PACK, COLLECTION, FLAG)

# --------------------------------------------------------------- models ----
# The classify floor's ladder. Rank order only — this is not a price list and
# not a capability claim, it is the one comparison the floor needs.
MODEL_TIERS = {"haiku": 1, "sonnet": 2, "opus": 3}
CLASSIFY_FLOOR = "opus"

BOOL_WORDS = {"true": True, "on": True, "yes": True, "1": True,
              "false": False, "off": False, "no": False, "0": False}


class Refused(Exception):
    """A value this tool will not write, with the sentence saying why. Raised
    rather than printed at the point of detection so that every refusal leaves
    by one door and `set` can exit 2 from it."""

    def __init__(self, key, message):
        super().__init__(message)
        self.key, self.message = key, message


class Setting:
    """One key: where it lives in the profile, what a legal value is, and what
    changing it does to the owner's files."""

    def __init__(self, key, tag, kind, default, why, low=None, high=None,
                 editable=True, not_above=None):
        self.key = key
        self.path = tuple(key.split("."))
        self.tag = tag
        self.kind = kind
        self.default = default
        self.why = why                       # message key, never a sentence
        self.low, self.high = low, high
        self.editable = editable
        # the sibling this value may never exceed (min_samples vs max_samples,
        # soft_target_units vs max_units) — checked against the RESOLVED
        # config, so a pack that already disagrees is caught too
        self.not_above = not_above

    def __repr__(self):
        return f"<Setting {self.key}>"

    # -- parsing and validation --------------------------------------------

    def parse(self, raw, smsg):
        """A string off the command line -> a typed value, or Refused."""
        if raw is None or raw == "":
            raise Refused(self.key, smsg["settings_refuse_empty"].format(key=self.key))
        if self.kind == "bool":
            got = BOOL_WORDS.get(str(raw).strip().lower())
            if got is None:
                raise Refused(self.key, smsg["settings_refuse_not_a_bool"].format(
                    key=self.key, accepted=", ".join(sorted(BOOL_WORDS))))
            return got
        if self.kind in ("ratio", "count"):
            try:
                value = float(raw) if self.kind == "ratio" else int(str(raw), 10)
            except (TypeError, ValueError):
                raise Refused(self.key, smsg["settings_refuse_not_a_number"].format(
                    key=self.key, value=raw))
            return value
        return str(raw).strip()

    def check(self, value, smsg):
        if self.kind in ("ratio", "count"):
            if (self.low is not None and value < self.low) or \
                    (self.high is not None and value > self.high):
                raise Refused(self.key, smsg["settings_refuse_out_of_range"].format(
                    key=self.key, value=value, low=self.low, high=self.high))
        if self.kind == "model_floor":
            tier = MODEL_TIERS.get(value)
            accepted = ", ".join(m for m, t in sorted(MODEL_TIERS.items(),
                                                      key=lambda kv: kv[1])
                                 if t >= MODEL_TIERS[CLASSIFY_FLOOR])
            if tier is None:
                raise Refused(self.key, smsg["settings_refuse_unknown_model"].format(
                    key=self.key, value=value, accepted=accepted))
            if tier < MODEL_TIERS[CLASSIFY_FLOOR]:
                raise Refused(self.key, smsg["settings_refuse_below_floor"].format(
                    key=self.key, value=value, floor=CLASSIFY_FLOOR,
                    accepted=accepted))
        return value


SETTINGS = [
    # (A2') the floor. Tagged moves-files and not cost-only on purpose: the
    # vision label becomes part of a folder NAME, so a different model sends a
    # future run's photos to a differently named folder.
    Setting("models.classify", MOVES_FILES, "model_floor", CLASSIFY_FLOOR,
            "settings_why_models_classify"),
    # (A3) the script copies and checksums; the model reports.
    Setting("models.copy_conductor", COST_ONLY, "model_any", "haiku",
            "settings_why_models_copy_conductor"),
    # (A2) local, on-device, free per photo after the download.
    Setting("models.embed_local", COST_ONLY, "text", "",
            "settings_why_models_embed_local"),
    # Shown so the owner can see it, un-editable by decision: recurrence
    # cannot be measured on a sample (Visual-Sorting DESIGN).
    Setting("visual.embed_coverage", COST_ONLY, "ratio", 1.0,
            "settings_why_visual_embed_coverage", low=1.0, high=1.0,
            editable=False),
    # Already read by photo_sample.sample_budget(); surfaced read-write here.
    Setting("sampling.gps_pct", COST_ONLY, "ratio", 0.10,
            "settings_why_sampling_gps_pct", low=0.0, high=1.0),
    Setting("sampling.no_gps_pct", COST_ONLY, "ratio", 0.05,
            "settings_why_sampling_no_gps_pct", low=0.0, high=1.0),
    Setting("sampling.min_samples", COST_ONLY, "count", 10,
            "settings_why_sampling_min_samples", low=0, high=10000,
            not_above="sampling.max_samples"),
    Setting("sampling.max_samples", COST_ONLY, "count", 40,
            "settings_why_sampling_max_samples", low=1, high=10000),
    # §3D. ⚠️ Principle A is SIGNED but UNBUILT: no stage reads these yet, so
    # they are surfaced as settings whose effect is still to arrive. `explain`
    # says so; see `unbuilt` below.
    Setting("naming.smart_scenario", MOVES_FILES, "bool", False,
            "settings_why_naming_smart_scenario"),
    Setting("naming.max_units", LABEL_ONLY, "count", 20,
            "settings_why_naming_max_units", low=1, high=200),
    Setting("naming.soft_target_units", LABEL_ONLY, "count", 12,
            "settings_why_naming_soft_target_units", low=1, high=200,
            not_above="naming.max_units"),
    Setting("naming.max_names_in_folder", LABEL_ONLY, "count", 3,
            "settings_why_naming_max_names_in_folder", low=1, high=50),
    # SET-3 owns these; here they are read-only so `show` is the whole
    # settings surface rather than most of it.
    Setting("schedule.enabled", SCHEDULE_ONLY, "bool", False,
            "settings_why_schedule_enabled", editable=False),
    Setting("schedule.window", SCHEDULE_ONLY, "text", "",
            "settings_why_schedule_window", editable=False),
]
BY_KEY = {s.key: s for s in SETTINGS}

# Keys whose effect has not been built yet. Naming principle A is signed and
# unbuilt (no `smart_scenario` / `max_units` in any stage script), and a
# settings tool that offered the switch without saying so would be promising
# an effect the engine does not have.
UNBUILT_PREFIXES = ("naming.",)

# The keys whose number is counted in NAME UNITS rather than characters (N-2).
# A number whose unit is unstated is not one the owner can act on.
UNIT_COUNTED = {"naming.max_units", "naming.soft_target_units"}


def unbuilt(setting):
    return setting.key.startswith(UNBUILT_PREFIXES)


# ------------------------------------------------------------ resolution ---

def dig(data, path):
    """-> (value, True) if `path` is present in `data`, else (None, False).
    Presence and value are separate answers: `false` and `0` are values."""
    cur = data
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None, False
        cur = cur[k]
    return cur, True


def resolve(setting, profile, collection, flags):
    """-> {"value", "layer", "shadowed"}. `shadowed` is the layer the run will
    actually use when a lower one is masked by collection.json — the case the
    engine cannot honour yet."""
    found = {DEFAULT: (setting.default, True)}
    found[PACK] = dig(profile, setting.path)
    found[COLLECTION] = dig(collection.get("settings") or {}, setting.path)
    found[FLAG] = ((flags[setting.key], True) if setting.key in flags
                   else (None, False))

    winner, layer = setting.default, DEFAULT
    for name in LAYER_ORDER:
        value, present = found[name]
        if present:
            winner, layer = value, name

    shadowed = None
    if layer == COLLECTION:
        # what the run will really use, the collection layer removed
        for name in (DEFAULT, PACK):
            value, present = found[name]
            if present:
                shadowed = (value, name)
    return {"value": winner, "layer": layer, "shadowed": shadowed}


def resolve_all(profile, collection, flags=None):
    flags = flags or {}
    return {s.key: resolve(s, profile, collection, flags) for s in SETTINGS}


def check_pairs(state, smsg):
    """The rules that need two keys. Run over the RESOLVED config rather than
    over the one value being written, so a pack that already disagrees with
    itself is reported instead of being carried forward silently.
    -> list of Refused."""
    problems = []
    for setting in SETTINGS:
        if not setting.not_above:
            continue
        mine = state[setting.key]["value"]
        other = state[setting.not_above]["value"]
        if isinstance(mine, (int, float)) and isinstance(other, (int, float)) \
                and mine > other:
            problems.append(Refused(setting.key, smsg["settings_refuse_order"].format(
                key=setting.key, value=mine,
                other_key=setting.not_above, other=other)))
    return problems


# --------------------------------------------------------------- writing ---

def put(data, path, value):
    cur = data
    for k in path[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[path[-1]] = value


def write_profile(pack, data):
    """Rewritten whole, indent 2, non-ASCII kept as itself: the file is the
    owner's and they may open it. `_comment` keys survive because they are
    ordinary keys and dict order is preserved."""
    path = Path(pack.dir) / photo_profile.PROFILE_NAME
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


# --------------------------------------------------------------- display ---

def render(value):
    if isinstance(value, bool):
        return "on" if value else "off"
    if value == "" or value is None:
        return "—"
    return str(value)


def show(pack, collection, flags, verbose=False, as_json=False):
    profile = pack.profile
    smsg = photo_profile.settings_messages(profile)
    state = resolve_all(profile, collection, flags)

    if as_json:
        out = {"owner": pack.owner,
               "pack": str(pack.dir) if pack.dir else None,
               "settings": [
                   {"key": s.key, "value": state[s.key]["value"],
                    "layer": state[s.key]["layer"], "tag": s.tag,
                    "editable": s.editable,
                    "engine_reads_it": not unbuilt(s),
                    "shadowed": state[s.key]["shadowed"]}
                   for s in SETTINGS]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(smsg["settings_pack_line"].format(owner=pack.owner, path=pack.dir)
          if pack.dir else smsg["settings_no_pack_line"])
    print()
    rows = [(s.key, render(state[s.key]["value"]),
             smsg[LAYER_MESSAGE_KEY[state[s.key]["layer"]]],
             smsg[TAG_MESSAGE_KEY[s.tag]]
             + ("" if s.editable else f" · {smsg['settings_read_only']}"))
            for s in SETTINGS]
    head = (smsg["settings_h_key"], smsg["settings_h_value"],
            smsg["settings_h_layer"], smsg["settings_h_tag"])
    widths = [max(len(r[i]) for r in rows + [head]) for i in range(4)]
    print("  " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(head)))
    print("  " + "  ".join("-" * w for w in widths))
    for setting, row in zip(SETTINGS, rows):
        print("  " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))
        if unbuilt(setting):
            print("      " + smsg["settings_not_built_yet"])
        shadow = state[setting.key]["shadowed"]
        if shadow:
            print("      " + smsg["settings_collection_not_read"].format(
                value=render(shadow[0]),
                layer=smsg[LAYER_MESSAGE_KEY[shadow[1]]]))
        if verbose:
            print("      " + smsg[setting.why])
    print()
    print("  " + smsg["settings_flag_layer_note"])
    for problem in check_pairs(state, smsg):
        print("  " + problem.message)
    return 0


def explain(key, pack, collection, smsg, as_json=False):
    setting = BY_KEY.get(key)
    if setting is None:
        print(smsg["settings_refuse_unknown_key"].format(key=key))
        return 2
    state = resolve(setting, pack.profile, collection, {})
    if as_json:
        print(json.dumps({"key": setting.key, "value": state["value"],
                          "layer": state["layer"], "tag": setting.tag,
                          "editable": setting.editable,
                          "why": smsg[setting.why],
                          "tag_means": smsg[TAGLINE_MESSAGE_KEY[setting.tag]],
                          "engine_reads_it": not unbuilt(setting)},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"{setting.key} = {render(state['value'])} "
          f"({smsg[LAYER_MESSAGE_KEY[state['layer']]]})")
    print()
    print("  " + smsg[setting.why])
    print("  " + smsg[TAGLINE_MESSAGE_KEY[setting.tag]])
    if unbuilt(setting):
        print("  " + smsg["settings_not_built_yet"])
    if setting.key in UNIT_COUNTED:
        print("  " + smsg["settings_units_note"])
    if not setting.editable:
        print("  " + smsg["settings_read_only"])
    print("  " + smsg["settings_flag_layer_note"])
    return 0


# ----------------------------------------------------------------- set -----

def apply_set(key, raw, pack, collection, smsg, go=False, layer=PACK):
    setting = BY_KEY.get(key)
    if setting is None:
        raise Refused(key, smsg["settings_refuse_unknown_key"].format(key=key))
    if layer == COLLECTION:
        raise Refused(key, smsg["settings_refuse_collection_layer"])
    if not setting.editable:
        raise Refused(key, smsg["settings_refuse_read_only"].format(
            key=key, why=smsg[setting.why]))
    # The VALUE is judged before the destination is: an owner who typed an
    # illegal value should be told so whether or not they have a pack yet,
    # and "there is nowhere to write it" is the less useful of the two answers.
    value = setting.check(setting.parse(raw, smsg), smsg)
    if not pack.dir:
        raise Refused(key, smsg["settings_refuse_no_pack"])
    before = resolve(setting, pack.profile, collection, {})
    if before["value"] == value and before["layer"] == PACK:
        print(smsg["settings_no_change"].format(key=key, value=render(value)))
        return 0

    # the pair rules judge the config as it would be AFTER the write
    after = json.loads(json.dumps(pack.profile))
    put(after, setting.path, value)
    problems = check_pairs(resolve_all(after, collection), smsg)
    for problem in problems:
        if problem.key in (setting.key, setting.not_above or "") or \
                setting.key in (BY_KEY[problem.key].not_above or ""):
            raise problem

    print(smsg["settings_plan_change"].format(
        key=key, old=render(before["value"]), value=render(value),
        layer=smsg[LAYER_MESSAGE_KEY[PACK]]))
    print(smsg[TAGLINE_MESSAGE_KEY[setting.tag]])
    if not go:
        print(smsg["settings_dry_run"])
        return 0
    print(smsg["settings_written"].format(path=write_profile(pack, after)))
    return 0


# ---------------------------------------------------------------- main -----

def parse_flags(pairs, smsg):
    """--flag models.classify=opus, repeated. The fourth layer, made visible:
    a stage script's own flag beats the pack for one run, and an owner asking
    "what would that do?" should not have to write to find out."""
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            sys.exit(f"--flag takes key=value, not {pair!r}")
        key, raw = pair.split("=", 1)
        setting = BY_KEY.get(key.strip())
        if setting is None:
            sys.exit(smsg["settings_refuse_unknown_key"].format(key=key.strip()))
        out[setting.key] = setting.parse(raw, smsg)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("show", "explain", "set"))
    ap.add_argument("args", nargs="*", help="explain <key> · set <key> <value>")
    ap.add_argument("--workdir", help="a dump work dir, to find collection.json")
    ap.add_argument("--profile", help="a pack folder or photo-profile.json")
    ap.add_argument("--flag", action="append",
                    help="key=value, as a stage command would override it")
    ap.add_argument("--go", action="store_true", help="write the change")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    pack = photo_profile.resolve_pack(workdir=args.workdir,
                                      explicit=args.profile)
    collection, _path = photo_profile.find_collection(args.workdir)
    smsg = photo_profile.settings_messages(pack.profile)

    try:
        if args.command == "show":
            return show(pack, collection, parse_flags(args.flag, smsg),
                        verbose=args.verbose, as_json=args.as_json)
        if args.command == "explain":
            if len(args.args) != 1:
                sys.exit("explain takes one key")
            return explain(args.args[0], pack, collection, smsg,
                           as_json=args.as_json)
        if len(args.args) != 2:
            sys.exit("set takes a key and a value")
        return apply_set(args.args[0], args.args[1], pack, collection, smsg,
                         go=args.go)
    except Refused as refused:
        print(refused.message)
        return 2


if __name__ == "__main__":
    sys.exit(main())
