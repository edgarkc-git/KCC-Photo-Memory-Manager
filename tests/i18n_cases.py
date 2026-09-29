#!/usr/bin/env python3
"""Cases for the language layer (Rule 8): photo_profile.messages() and
photo_profile.buckets().

Language is a variable with a default of English. The one subtlety worth
testing hard is that "no owner pack at all" is NOT the same case as "a new
owner": an unbound run resolves to the LEGACY table, which is what makes
tests/golden_replay.py's byte-identity assertion possible. A new owner, whose
pack says language "en", gets English.

Every fixture here is synthetic: made-up owners, a hand-built manifest, no
drive, no network.

  ./.venv/bin/python3 tests/i18n_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_profile as pp  # noqa: E402

VERBOSE = False
# i18n-guard:allow-begin — locale detection data, not user-facing output: the
# ranges this suite uses to prove the English table holds no Chinese.
CJK = re.compile(r"[一-鿿　-〿＀-￯]")
# i18n-guard:allow-end
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def log(msg):
    if VERBOSE:
        print(f"      {msg}")


# --------------------------------------------------------------------------
# the tables themselves
# --------------------------------------------------------------------------

def case_every_language_has_every_key():
    """REVIEW_VOCAB ships one language and passes this trivially today. It is
    wired in anyway: unwired, the day somebody adds a second language with
    half the keys, nothing fails."""
    problems = []
    for table in (pp.MESSAGE_VOCAB, pp.BUCKET_VOCAB, pp.SCENE_CLASS_VOCAB,
                  pp.REVIEW_VOCAB, pp.SETTINGS_VOCAB,
                  pp.SCHEDULE_VOCAB):
        keys = {lang: set(t) for lang, t in table.items()}
        union = set().union(*keys.values())
        for lang, have in keys.items():
            for k in sorted(union - have):
                problems.append(f"{lang} is missing {k!r}")
    for p in problems:
        log(p)
    return not problems, f"{len(problems)} gaps"


def case_english_table_is_english():
    """A key copied across untranslated is worse than a missing key: it looks
    done."""
    bad = [k for k, v in pp.MESSAGE_VOCAB["en"].items() if CJK.search(v)]
    bad += [k for k, v in pp.BUCKET_VOCAB["en"].items() if CJK.search(v)]
    bad += [k for k, v in pp.SCENE_CLASS_VOCAB["en"].items() if CJK.search(v)]
    bad += [k for k, v in pp.REVIEW_VOCAB["en"].items() if CJK.search(v)]
    bad += [k for k, v in pp.SETTINGS_VOCAB["en"].items() if CJK.search(v)]
    bad += [k for k, v in pp.SCHEDULE_VOCAB["en"].items() if CJK.search(v)]
    for k in bad:
        log(f"{k} still holds CJK")
    return not bad, f"{len(bad)} untranslated"


def case_translations_keep_their_placeholders():
    """A translation that loses {n} raises KeyError at the worst moment, and a
    translation that invents one raises it too."""
    base = pp.MESSAGE_VOCAB[pp.LEGACY_MESSAGE_LANGUAGE]
    problems = []
    for lang, table in pp.MESSAGE_VOCAB.items():
        for k, v in table.items():
            want = set(PLACEHOLDER.findall(base.get(k, "")))
            got = set(PLACEHOLDER.findall(v))
            if want != got:
                problems.append(f"{lang}.{k}: {sorted(got)} != {sorted(want)}")
    for p in problems:
        log(p)
    return not problems, f"{len(problems)} mismatched"


def case_keys_are_ascii_and_descriptive():
    bad = [k for k in list(pp.MESSAGE_VOCAB[pp.LEGACY_MESSAGE_LANGUAGE])
           + list(pp.REVIEW_VOCAB["en"]) + list(pp.SETTINGS_VOCAB["en"])
           + list(pp.SCHEDULE_VOCAB["en"])
           if not k.isascii() or not re.fullmatch(r"[a-z][a-z0-9_]+", k)]
    for k in bad:
        log(f"bad key {k!r}")
    return not bad, f"{len(bad)} bad keys"


# Two catalogs, two lookup names. `rmsg[...]` is the review table's
# (REVIEW_VOCAB, resolved by review_messages()); `msg[...]` is everything
# else's. The negative look-behind is what keeps `rmsg["x"]` out of the
# message catalog — without it every review key reads as a missing message key.
LOOKUPS = {"message": (r'(?<![A-Za-z_])msg(?:\[|\.get\()["\']([^"\']+)["\']',
                       lambda: pp.MESSAGE_VOCAB[pp.LEGACY_MESSAGE_LANGUAGE]),
           "review": (r'rmsg(?:\[|\.get\()["\']([^"\']+)["\']',
                      lambda: pp.REVIEW_VOCAB["en"]),
           # SET-1's surface (SETTINGS_VOCAB, resolved by settings_messages()).
           # `smsg[...]` is outside the message pattern's look-behind already,
           # so the three catalogs cannot read each other's keys.
           "settings": (r'(?<![A-Za-z_])smsg(?:\[|\.get\()["\']([^"\']+)["\']',
                        lambda: pp.SETTINGS_VOCAB["en"]),
           # SET-3's surface (SCHEDULE_VOCAB, resolved by schedule_messages()).
           # It reads `schmsg[...]` for the same reason SET-1 reads `smsg`:
           # one prefix per catalog is what stops a missing key in one
           # surface being silently answered by another's table.
           "schedule": (r'schmsg(?:\[|\.get\()["\']([^"\']+)["\']',
                        lambda: pp.SCHEDULE_VOCAB["en"])}
# A key assembled at call time — rmsg[f"review_kind_{kind}"] — names a FAMILY,
# not one string. The family prefix counts every key under it as read, which
# is the honest limit of a static scan: it can see that the whole family is
# reachable, not which member fires.
FAMILY = re.compile(r'(?:msg|rmsg)(?:\[|\.get\()f["\']([a-z_]+)\{')


def catalog_keys_in_use(catalog="message"):
    """-> (keys the scripts ask for, prefixes they ask for, keys that do not
    exist). Direct lookups plus the one indirection the plan stage uses."""
    import photo_plan                                # noqa: E402  (needs SCRIPTS on path)
    import photo_memory                              # noqa: E402
    pattern, table = LOOKUPS[catalog]
    known = set(table())
    # The same indirection on the review side: SNS-4 picks one of four round
    # sentences from a table keyed on (fired?, why), so no line in the engine
    # spells any of them and a static scan would read all four as dead.
    if catalog == "message":
        used = set(photo_plan.MODE_MESSAGE_KEY.values())
    elif catalog == "review":
        # Two indirections on the review side, both keyed off a table so that
        # no line in the engine spells any of the sentences: SNS-4 picks one
        # of four round sentences on (fired?, why), and card (c) picks the
        # word for the space an absorb was decided in. A static scan reads
        # every one of them as dead. ⛔ `review_absorbed_space_unrecorded` is
        # deliberately NOT here — it is spelled at its call site, because the
        # unrecorded case is a fallback rather than a table entry.
        used = (set(photo_memory.ROUND_REASON_KEY.values())
                | set(photo_memory.SPACE_WORD_KEY.values()))
    elif catalog == "settings":
        # SET-1 keys three families off tables rather than spelling any of
        # them: the blast tag, the sentence behind it, the layer name, and one
        # `why` line per setting. A static scan would read all of them as dead.
        import photo_settings                          # noqa: E402
        used = (set(photo_settings.TAG_MESSAGE_KEY.values())
                | set(photo_settings.TAGLINE_MESSAGE_KEY.values())
                | set(photo_settings.LAYER_MESSAGE_KEY.values())
                | {s.why for s in photo_settings.SETTINGS})
    else:
        # SET-3 keys nothing off a table: every sentence it prints is spelled
        # at its call site, so a static scan sees all of them.
        used = set()
    families, missing = set(), []
    for f in sorted(SCRIPTS.glob("*.py")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            for k in re.findall(pattern, line):
                if "{" in k:
                    continue                       # handled by FAMILY below
                used.add(k)
                if k not in known:
                    missing.append(f"{f.name}:{i} asks for {k!r}")
            for prefix in FAMILY.findall(line):
                families.add(prefix)
    return used, families, missing


def case_every_key_the_scripts_ask_for_exists():
    """Catches a typo'd msg["..."] before a user hits that branch — several of
    these lines only run on a rare route (a checksum failure, a collision)."""
    problems, counted = [], 0
    for catalog in LOOKUPS:
        used, _families, missing = catalog_keys_in_use(catalog)
        counted += len(used)
        problems += missing
    for m in problems:
        log(m)
    log(f"{counted} distinct keys in use")
    return not problems, f"{counted} keys used, {len(problems)} unknown"


def case_no_dead_keys():
    """A key nobody reads is a sentence nobody sees — and one more thing to
    translate for nothing."""
    dead = []
    for catalog, (_pattern, table) in LOOKUPS.items():
        used, families, _missing = catalog_keys_in_use(catalog)
        for k in sorted(set(table()) - used):
            if not any(k.startswith(p) for p in families):
                dead.append(f"{catalog}.{k}")
    for k in dead:
        log(f"dead key {k!r}")
    return not dead, f"{len(dead)} unused"


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------

def case_no_pack_falls_back_to_legacy():
    """The load-bearing rule: an unbound run must produce what it produced
    yesterday, or golden_replay's byte-identity claim is meaningless."""
    got = pp.messages({})
    want = pp.MESSAGE_VOCAB[pp.LEGACY_MESSAGE_LANGUAGE]
    same = got == want
    bk = pp.buckets({}) == pp.BUCKET_VOCAB[pp.LEGACY_BUCKET_LANGUAGE]
    # The zero-shot scene classes are the same claim: photo_see.py keys its
    # fallback label set on ASCII ids, so an unbound run only keeps emitting
    # the class NAMES it emitted yesterday if this table's legacy step holds —
    # and every replay comparison against a shipped decision rests on that.
    sc = pp.scene_classes({}) == pp.SCENE_CLASS_VOCAB[pp.LEGACY_SCENE_CLASS_LANGUAGE]
    return same and bk and sc, f"messages={same} buckets={bk} scene_classes={sc}"


def case_unknown_language_falls_back_to_english():
    """ASCII is the least surprising thing to hand someone whose language the
    engine has no table for — never the legacy one."""
    got = pp.messages({"language": "sv"})
    en = got == pp.MESSAGE_VOCAB["en"]
    not_legacy = got != pp.MESSAGE_VOCAB[pp.LEGACY_MESSAGE_LANGUAGE]
    bk = pp.buckets({"language": "sv"}) == pp.BUCKET_VOCAB["en"]
    sc = pp.scene_classes({"language": "sv"}) == pp.SCENE_CLASS_VOCAB["en"]
    return en and not_legacy and bk and sc, f"en={en} buckets={bk} scene={sc}"


def case_a_language_with_no_table_says_so():
    """F7 / U3-26 — the reproduction. The fallback above is right and was
    silent: an owner whose language did not take read English folder names
    as a bug in their pack, and nothing had told them the engine simply has
    no table for it. Said once per run, not once per lookup — four resolvers
    fire on every stage and four identical warnings read as four problems."""
    import contextlib
    import io
    lang = "xx-F7"                    # in no table, and in no other case
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        bk = pp.buckets({"language": lang})
        pp.messages({"language": lang})
        pp.default_types({"language": lang})
        pp.scene_classes({"language": lang})
    said = err.getvalue()
    return (bk == pp.BUCKET_VOCAB["en"] and lang in said
            and "English" in said and said.count(lang) == 1
            and all(code in said for code in pp.BUCKET_VOCAB)), repr(said)


def case_a_language_with_a_table_says_nothing():
    """A guard, not a reproduction (silent before and after): the notice is
    about a MISSING table, so a declared language the engine holds, and an
    unbound run on the legacy table, must not trip it."""
    import contextlib
    import io
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        for profile in ({"language": "en"}, {"language": "zh-TW"}, {}):
            pp.buckets(profile)
            pp.messages(profile)
            pp.default_types(profile)
            pp.scene_classes(profile)
    return err.getvalue() == "", repr(err.getvalue())


def case_a_declared_language_wins():
    en = pp.messages({"language": "en"}) == pp.MESSAGE_VOCAB["en"]
    zh = pp.messages({"language": "zh-TW"}) == pp.MESSAGE_VOCAB["zh-TW"]
    return en and zh, f"en={en} zh-TW={zh}"


def case_a_new_hint_reaches_a_pack_that_overrode_the_old_one():
    """Why SNS-14's rename hint is its OWN key and not a longer
    `review_recheck_hint`.

    The static scans above see that the key exists and that something reads it.
    What they cannot see is the reason it is a separate key: a pack that
    already overrode the old hint has a sentence of its own, written before
    names could be typed on that row, and editing the engine's copy would leave
    exactly the owners who translated the round as the only ones never told the
    rename exists. A new key is additive — the override still wins for the half
    it covers, and the engine's default reaches every pack for the half it does
    not."""
    prof = {"language": "en",
            "review_messages": {"review_recheck_hint": "leave it alone"}}
    rmsg = pp.review_messages(prof)
    kept = rmsg["review_recheck_hint"] == "leave it alone"
    reached = (rmsg["review_recheck_name_hint"]
               == pp.REVIEW_VOCAB["en"]["review_recheck_name_hint"])
    # The armed tokens are ASCII and untranslated (the parser depends on them),
    # so the hint that teaches them has to spell them exactly.
    spells = all(t in rmsg["review_recheck_name_hint"]
                 for t in ("same", "distinct"))
    return kept and reached and spells, \
        f"override kept={kept} default reached={reached} tokens={spells}"


def case_the_owner_can_override_one_line():
    """Same escape hatch buckets() gives: what the owner typed wins over the
    table, one key at a time."""
    prof = {"language": "en", "messages": {"plan_h_notes": "## Remarks"},
            "naming_spec": {"buckets": {"others": "loose-ends"}}}
    m, b = pp.messages(prof), pp.buckets(prof)
    ok = (m["plan_h_notes"] == "## Remarks"
          and m["plan_h_stats"] == pp.MESSAGE_VOCAB["en"]["plan_h_stats"]
          and b["others"] == "loose-ends")
    return ok, "override applied" if ok else str(m["plan_h_notes"])


# --------------------------------------------------------------------------
# end to end: what a bound pack actually writes to disk
# --------------------------------------------------------------------------

def build_collection(root, language):
    """A minimal work dir for a made-up owner, plus that owner's pack."""
    workdir = root / "Working Files" / "2033-04"
    (workdir / "plan").mkdir(parents=True)
    dest_root = str(root / "sorted")

    rows = []
    for i in range(1, 13):
        is_shot = i % 4 != 0                       # every 4th row is a screenshot
        rows.append({
            "SourceFile": f"{root}/raw/PIC_{i:04d}." + ("png" if not is_shot else "jpg"),
            "FileName": f"PIC_{i:04d}." + ("png" if not is_shot else "jpg"),
            "FileType": "PNG" if not is_shot else "JPEG",
            "FileSize": str(2_000_000 + i),
            "DateTimeOriginal": f"2033:04:0{1 + i % 2} 1{i % 10}:00:00",
            "Make": "" if not is_shot else "Nokia",
            "Model": "" if not is_shot else "XR30",
            "ImageWidth": "1170" if not is_shot else "4032",
            "ImageHeight": "2532" if not is_shot else "3024",
        })
    with open(workdir / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (workdir / "batches.json").write_text(json.dumps({
        "source": f"{root}/raw", "main_files": len(rows),
        "batches": [{"batch": 1, "from": "2033-04-01", "to": "2033-04-02",
                     "files": len(rows), "status": "classified", "flags": []}]}, indent=1))
    (workdir / "plans.json").write_text(json.dumps({
        "dest_root": dest_root,
        "plans": [{"plan": 1, "title": "A walk", "batches": [1],
                   "notes": "a note the owner typed",
                   "dest": {"mode": "merge", "path": f"{dest_root}/20330401_walk"}}]}, indent=1))

    pack = root / "memory" / "someone"
    pack.mkdir(parents=True)
    (pack / "photo-owner-someone.md").write_text("# someone\n")
    profile = {"owner": {"slug": "someone", "display": "someone"},
               "own_camera_makes": ["Nokia"]}
    if language is not None:
        profile["language"] = language
    (pack / "photo-profile.json").write_text(json.dumps(profile, indent=1))
    (workdir.parent / "collection.json").write_text(json.dumps({
        "collection": "c", "owner": "someone",
        "memory_root": str(root / "memory"), "dest_root": dest_root}, indent=1))
    return workdir


def plan_output(tmp, language):
    """Run the real plan stage for one language. -> (md text, CSV rows)."""
    workdir = build_collection(Path(tmp), language)
    env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
    # R1: a language fixture drives the METADATA path only -- no embed/, no
    # see stage -- so --no-vision states that rather than bypassing a gate.
    proc = subprocess.run([sys.executable, str(SCRIPTS / "photo_plan.py"),
                           str(workdir), "--plan", "1", "--no-status",
                           "--no-vision"],
                          capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    md = (workdir / "plan" / "plan_P1.md").read_text()
    rows = list(csv.DictReader(open(workdir / "plan" / "plan_P1-files.csv",
                                    newline="")))
    return md, rows


def case_an_english_pack_writes_an_english_plan(tmp):
    md, rows = plan_output(tmp, "en")
    cjk_md = sorted({m.group(0) for m in CJK.finditer(md)})
    cjk_rows = sorted({m.group(0) for r in rows for m in CJK.finditer(r["note"])
                       } | {m.group(0) for r in rows
                            for m in CJK.finditer(r["destination"])})
    english = "## Statistics" in md and "## Destination" in md
    log(f"CJK in md: {cjk_md}; CJK in rows: {cjk_rows}")
    ok = not cjk_md and not cjk_rows and english
    return ok, "clean English" if ok else f"md={cjk_md} rows={cjk_rows} headings={english}"


def case_a_zh_pack_writes_the_legacy_strings(tmp):
    md, rows = plan_output(tmp, "zh-TW")
    zh = pp.MESSAGE_VOCAB["zh-TW"]
    ok = (zh["plan_h_stats"] in md and zh["plan_dest_merge_note"] in md
          and zh["plan_safety_approval"] in md)
    shots = [r for r in rows if zh["note_screenshot_exif_rule"] == r["note"]]
    return ok and shots, f"legacy strings={ok}, {len(shots)} screenshot notes"


def case_the_screen_capture_limit_is_stated_in_the_owners_language(tmp):
    """G-3: the case the filename list cannot reach is said out loud every
    run — and, being a sentence the ENGINE writes, in the owner's language
    rather than the one the rule happened to be written in."""
    en_md, _ = plan_output(tmp / "en", "en")
    zh_md, _ = plan_output(tmp / "zh", "zh-TW")
    ok = (pp.MESSAGE_VOCAB["en"]["plan_screen_capture_limit"] in en_md
          and pp.MESSAGE_VOCAB["zh-TW"]["plan_screen_capture_limit"] in zh_md)
    return ok, "stated in both languages" if ok else "missing from a plan"


def case_a_pack_with_no_language_still_gets_the_legacy_strings(tmp):
    """A pack can exist and simply not say — the bucket/message tables treat
    that as "unbound", which is the conservative reading."""
    md, _ = plan_output(tmp, None)
    zh = pp.MESSAGE_VOCAB["zh-TW"]
    ok = zh["plan_h_stats"] in md
    return ok, "legacy" if ok else "not legacy"


def case_the_report_counts_rows_by_tag_not_by_note_text(tmp):
    """The screenshot/shared/renamed counters used to substring-match the note.
    A translated note breaks that silently, so the English run must count the
    same rows the Chinese one does."""
    md_en, rows_en = plan_output(tmp, "en")
    with tempfile.TemporaryDirectory(prefix="i18n-zh-") as tmp2:
        md_zh, rows_zh = plan_output(tmp2, "zh-TW")

    def stat(md, table, key):
        line = [ln for ln in md.splitlines()
                if ln.startswith(table[key].split("{")[0])]
        return line[0].rsplit("|", 2)[-2].strip() if line else None

    en_n = stat(md_en, pp.MESSAGE_VOCAB["en"], "plan_stat_screenshots")
    zh_n = stat(md_zh, pp.MESSAGE_VOCAB["zh-TW"], "plan_stat_screenshots")
    ok = en_n == zh_n and en_n not in (None, "0")
    log(f"screenshots counted: en={en_n} zh={zh_n}")
    return ok, f"en={en_n} zh={zh_n}"


def case_an_english_pack_writes_an_english_execution_record(tmp):
    """photo_execute now resolves the pack on every run (it used to only when
    dest_root was missing), so the execution record follows the owner's
    language too. Real copies, into a temp dir, with a deliberate collision so
    the flags table is rendered as well."""
    root = Path(tmp)
    workdir = build_collection(root, "en")
    dest = root / "sorted" / "20330401_walk"
    dest.mkdir(parents=True)
    # the plan writer's shape, f"{dest_root}/{name}": str(dest) is backslashes
    # on Windows and photo_execute.allowed() refuses it
    plan_dest = f"{root / 'sorted'}/20330401_walk"
    src = root / "raw"
    src.mkdir(exist_ok=True)
    rows = []
    for i, name in enumerate(("A.JPG", "B.JPG", "C.JPG")):
        (src / name).write_bytes(b"payload-%d" % i)
        rows.append({"SourceFile": str(src / name), "FileName": name, "batch": "1",
                     "date": "2033-04-01 10:00", "action": "copy",
                     "destination": plan_dest, "note": ""})
    (dest / "C.JPG").write_bytes(b"different content")     # -> collision flag
    with open(workdir / "plan" / "plan_P1-files.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    bdata = json.loads((workdir / "batches.json").read_text())
    bdata["batches"][0]["status"] = "approved"
    (workdir / "batches.json").write_text(json.dumps(bdata, indent=1))

    env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
    r = subprocess.run([sys.executable, str(SCRIPTS / "photo_execute.py"),
                        str(workdir), "--plan", "1", "--go"],
                       capture_output=True, text=True, env=env)
    # exit 1 is also the answer for the one planted collision; a refusal exits
    # 1 too, but before the summary line, so the line is what tells them apart
    if r.returncode != 1 or "1 flags" not in r.stdout:
        return False, (f"photo_execute exit {r.returncode}, not the one planted "
                       f"flag: {(r.stderr or r.stdout).strip()[-300:]}")
    md = (workdir / "plan" / "execution-log_P1.md").read_text()
    cjk = sorted({m.group(0) for m in CJK.finditer(md)})
    en = pp.MESSAGE_VOCAB["en"]
    rendered = (en["exec_h_dest_counts"] in md and en["exec_footer"] in md
                and en["exec_h_flags"] in md
                and en["flag_collision_existing_differs"] in md)
    log(f"CJK in execution record: {cjk}")
    ok = not cjk and rendered
    return ok, "clean English incl. flags table" if ok else f"cjk={cjk} rendered={rendered}"


# ---------------------------------------------------------------------------
# U2-06 — the `[type]` taxonomy. This vocabulary reaches FOLDER NAMES and, in
# photo_classify_set, is enforced with a hard exit, so an owner outside the
# table was not merely shown the wrong words: they were refused in a language
# they may not read. ⛔ The waiver that hid this claimed the set was
# "pack-sourced"; it fired precisely because the pack was empty.
# ---------------------------------------------------------------------------
def case_type_vocab_has_an_english_table():
    """REPRODUCTION — fails on the unfixed engine, where the only table was
    Traditional Chinese."""
    table = getattr(pp, "TYPE_VOCAB", None)
    if not table:
        return False, "photo_profile.TYPE_VOCAB does not exist"
    if "en" not in table:
        return False, "TYPE_VOCAB has no English table"
    bad = sorted(w for w in table["en"].values() if CJK.search(w))
    return (not bad), (f"English [type] words containing CJK: {bad}"
                       if bad else f"{len(table['en'])} English type words")


def case_an_english_owner_gets_english_types():
    """REPRODUCTION — the defect in one assertion: an owner whose pack says
    English, with no taxonomy of their own, must not be handed Chinese."""
    got = pp.default_types({"language": "en"})
    bad = sorted(w for w in got if CJK.search(w))
    return (not bad), (f"an English owner was given: {bad}" if bad
                       else f"{len(got)} English words")


def case_an_unknown_language_gets_english_types():
    """GUARD against the plausible wrong fix — resolving only zh-TW and en and
    letting everything else keep falling to the legacy table. A Japanese owner
    must land on English, never on Chinese."""
    got = pp.default_types({"language": "ja"})
    bad = sorted(w for w in got if CJK.search(w))
    return (not bad), (f"a ja owner was given: {bad}" if bad else "English")


def case_no_pack_keeps_the_legacy_types():
    """GUARD against the other plausible wrong fix — making English the answer
    for EVERY caller. An unbound run must keep accepting yesterday's words or
    golden_replay's byte-identity assertion silently stops holding."""
    got = pp.default_types({})
    want = set(pp.TYPE_VOCAB[pp.LEGACY_TYPE_LANGUAGE].values())
    return got == want, ("an unbound run no longer resolves to the legacy "
                         f"table: {sorted(got)}" if got != want else "legacy")


def case_an_ordinary_day_at_home_has_a_type_word():
    """W1C-7 / U3-29 — REPRODUCTION. An ordinary day at home is the most
    common batch any owner has, and no `[type]` word could name it: it fell
    through to `others`. The owner ruled the words himself — `home` in
    English, and in zh-TW the word he typed. It is pinned here by code point
    so nobody substitutes a "better" one, and escaped because tests carry no
    CJK (Rule 8)."""
    owner_word = "\u4f4f\u5bb6"
    got = pp.TYPE_VOCAB.get("zh-TW", {}).get("home")
    en = pp.default_types({"language": "en"})
    zh = pp.default_types({"language": "zh-TW"})
    unbound = pp.default_types({})
    return ("home" in en and got == owner_word and owner_word in zh
            and owner_word in unbound), (
        f"en has home: {'home' in en}; zh-TW home = {got!r}")


def case_the_engine_holds_no_type_vocabulary():
    """GUARD — photo_classify_set must never regain a vocabulary of its own.
    The module-level set is what made this defect invisible for so long."""
    src = (SCRIPTS / "photo_classify_set.py").read_text(encoding="utf-8")
    if "FALLBACK_TYPES" in src:
        return False, "photo_classify_set.FALLBACK_TYPES is back"
    hits = sorted(set(CJK.findall(src)))
    return (not hits), (f"CJK back in photo_classify_set.py: {hits}"
                        if hits else "no vocabulary, no CJK")


def case_a_declared_taxonomy_still_wins(tmp):
    """An owner who DECLARES naming_spec.types keeps exactly those words,
    whatever their language and whatever the default table says.

    Guards the resolution ORDER. A fix that made the language table
    authoritative would silently replace the vocabulary of every existing
    owner who had already written their own, in their own language."""
    pack = tmp / "photo-memory" / "someone"
    pack.mkdir(parents=True)
    mine = ["walk", "market day", "others"]
    (pack / "photo-profile.json").write_text(json.dumps(
        {"owner": "someone", "language": "en",
         "naming_spec": {"types": mine}}), encoding="utf-8")
    work = tmp / "work"
    work.mkdir()
    (work / "collection.json").write_text(json.dumps(
        {"owner": "someone", "memory_root": str(tmp / "photo-memory")}),
        encoding="utf-8")
    sys.path.insert(0, str(SCRIPTS))
    import photo_classify_set
    got = photo_classify_set.allowed_types(work)
    return got == set(mine), (f"declared {sorted(mine)} but got {sorted(got)}"
                              if got != set(mine) else "declaration wins")


def case_english_owner_is_not_refused_in_chinese(tmp):
    """⭐ THE REPRODUCTION. Goes through the real call path — the one that
    exists on BOTH sides of the fix — so it fails on the unfixed engine by
    showing the actual Chinese words, not by an AttributeError.

    photo_classify_set.allowed_types() is not decorative: main() exits with
    "type must be one of: ..." for anything outside it. An English owner with
    no taxonomy of their own was handed a Traditional-Chinese set and could
    not name a single batch."""
    pack = tmp / "photo-memory" / "someone"
    pack.mkdir(parents=True)
    (pack / "photo-profile.json").write_text(
        json.dumps({"owner": "someone", "language": "en"}), encoding="utf-8")
    work = tmp / "work"
    work.mkdir()
    (work / "collection.json").write_text(json.dumps(
        {"owner": "someone", "memory_root": str(tmp / "photo-memory")}),
        encoding="utf-8")
    sys.path.insert(0, str(SCRIPTS))
    import photo_classify_set
    got = photo_classify_set.allowed_types(work)
    bad = sorted(w for w in got if CJK.search(w))
    return (not bad), (f"an English owner may only use: {bad}" if bad
                       else f"{len(got)} words, none Chinese")


# --------------------------------------------------------------------------
# D-F7 / D-F11 — the `[what]` reference list, and why it is the ONE vocabulary
# with no language table.
#
# Every other vocabulary above resolves owner-declaration -> language table ->
# legacy strings, because the ENGINE invents those words. `[what]` is not the
# engine's word for anything: it is what a photograph is OF, in the owner's
# phrasing. So there is nothing to translate and nothing to ship, and the
# empty answer is the correct one rather than a gap.
# --------------------------------------------------------------------------

def case_no_starter_what_list_ships_in_any_language():
    """⭐ THE D-F7 GUARD, and the one that stops U2-06 recurring in a new slot.

    U2-06 was a `[type]` set that shipped as a "default", in one language,
    reached folder names and hard-exited every other owner. The fix there was
    a language table. The fix HERE is that there is no table at all — so the
    guard is not "is the table English", it is "is there a table".

    Written against the MODULE, not just the function, because the defect
    U2-06 had was a module-level constant that outlived every review of the
    function beside it."""
    empty = pp.what_reference(pp.Pack())
    if empty:
        return False, f"an unbound run ships a [what] vocabulary: {empty}"
    import inspect
    hits = sorted(set(CJK.findall(inspect.getsource(pp.what_reference))))
    if hits:
        return False, f"CJK inside what_reference(): {hits}"
    tables = [n for n in dir(pp)
              if n.endswith("_VOCAB") and "WHAT" in n.upper()]
    return (not tables), (f"a [what] vocabulary table exists: {tables}"
                          if tables else "no table, no default, no words")


def case_an_owner_who_wrote_phrases_gets_them_back(tmp):
    """⭐ THE REPRODUCTION for the vocabulary half. The owner has confirmed
    three phrases into the pack and the engine surfaces none of them, because
    `scenes` has had zero readers since the schema declared it.

    Goes through the real resolution path (collection.json -> pack), so on the
    unfixed engine it fails by reporting 0 of 3 phrases rather than by an
    AttributeError on a symbol that did not exist."""
    pack = tmp / "photo-memory" / "someone"
    pack.mkdir(parents=True)
    (pack / "photo-profile.json").write_text(
        json.dumps({"owner": "someone", "language": "en"}), encoding="utf-8")
    mine = ["coffee time", "play in grass", "morning market"]
    (pack / "photo-entities.json").write_text(json.dumps(
        {"owner": {"slug": "someone"},
         "scenes": [{"name": w, "confirmed_by": "owner"} for w in mine]}),
        encoding="utf-8")
    work = tmp / "work"
    work.mkdir()
    (work / "collection.json").write_text(json.dumps(
        {"owner": "someone", "memory_root": str(tmp / "photo-memory")}),
        encoding="utf-8")
    got = pp.what_reference(pp.resolve_pack(workdir=work))
    return got == mine, (f"the owner confirmed {len(mine)} phrases and the "
                         f"engine surfaced {len(got)}: {got}")


def case_a_bare_string_is_a_phrase_too(tmp):
    """The list will be hand-edited — the owner approves phrases into it —
    so both shapes are read: the record shape the rest of the pack uses, and
    the bare string a human types. Order is the pack's, duplicates collapse."""
    pack = tmp / "photo-memory" / "someone"
    pack.mkdir(parents=True)
    (pack / "photo-profile.json").write_text(
        json.dumps({"owner": "someone"}), encoding="utf-8")
    (pack / "photo-entities.json").write_text(json.dumps(
        {"scenes": ["sunset", {"name": "  hiking  "}, "sunset", ""]}),
        encoding="utf-8")
    got = pp.what_reference(pp.Pack(owner="someone", directory=pack,
                                    profile={"owner": "someone"}))
    return got == ["sunset", "hiking"], f"{got}"


def case_a_broken_reference_list_costs_a_style_guide_not_a_run(tmp):
    """⛔ NEVER RAISES AND NEVER EXITS, and the contrast with `home_locations`
    is deliberate: a malformed home HARD-EXITS, because a home the engine
    cannot read is a home it names and that publishes a coordinate. Nothing
    here can leak anything by being absent — this is a hint to a generator,
    so a broken hint must cost a run its style guide and never its folders.

    Four ways it can be broken, and every one answers with the empty list."""
    pack = tmp / "photo-memory" / "someone"
    pack.mkdir(parents=True)
    profile = {"owner": "someone"}
    make = lambda: pp.Pack(owner="someone", directory=pack, profile=profile)
    problems = []
    # 1. no photo-entities.json at all
    if pp.what_reference(make()) != []:
        problems.append("a pack with no entities file")
    # 2. unreadable JSON
    (pack / "photo-entities.json").write_text("{not json", encoding="utf-8")
    if pp.what_reference(make()) != []:
        problems.append("unreadable JSON")
    # 3. `scenes` is not a list of anything usable
    (pack / "photo-entities.json").write_text(json.dumps(
        {"scenes": [None, 7, [], {"no_name": "x"}]}), encoding="utf-8")
    if pp.what_reference(make()) != []:
        problems.append("malformed entries")
    # 4. the whole file is not an object
    (pack / "photo-entities.json").write_text("[]", encoding="utf-8")
    if pp.what_reference(make()) != []:
        problems.append("a file that is not an object")
    return (not problems), (f"raised or answered wrongly for: {problems}"
                            if problems else "four broken packs, four []")


NEEDS_TMP = {"an English owner is not refused in Chinese",
             "a declared taxonomy still wins",
             "an owner who wrote [what] phrases gets them back",
             "a bare string is a [what] phrase too",
             "a broken [what] list costs a style guide, not a run",
             "an English pack writes an English plan",
             "an English pack writes an English execution record",
             "a zh-TW pack writes the legacy strings",
             "the screen-capture limit is stated in the owner's language",
             "a pack with no declared language gets the legacy strings",
             "report counters survive translation"}

CASES = [
    ("every language table has every key", case_every_language_has_every_key),
    ("the English table is really English", case_english_table_is_english),
    ("translations keep their placeholders", case_translations_keep_their_placeholders),
    ("message keys are ASCII and descriptive", case_keys_are_ascii_and_descriptive),
    ("every key the scripts ask for exists", case_every_key_the_scripts_ask_for_exists),
    ("the catalog has no dead keys", case_no_dead_keys),
    ("no pack falls back to the legacy table", case_no_pack_falls_back_to_legacy),
    ("an unknown language falls back to English",
     case_unknown_language_falls_back_to_english),
    ("a language with no table says so, once (REPRODUCTION)",
     case_a_language_with_no_table_says_so),
    ("a language with a table says nothing", case_a_language_with_a_table_says_nothing),
    ("an ordinary day at home has a type word (REPRODUCTION)",
     case_an_ordinary_day_at_home_has_a_type_word),
    ("a declared language wins", case_a_declared_language_wins),
    ("[type] vocabulary has an English table", case_type_vocab_has_an_english_table),
    ("an English owner gets English [type] words",
     case_an_english_owner_gets_english_types),
    ("an unknown language gets English [type] words",
     case_an_unknown_language_gets_english_types),
    ("no pack keeps the legacy [type] words", case_no_pack_keeps_the_legacy_types),
    ("photo_classify_set holds no vocabulary",
     case_the_engine_holds_no_type_vocabulary),
    ("a declared taxonomy still wins", case_a_declared_taxonomy_still_wins),
    ("an English owner is not refused in Chinese",
     case_english_owner_is_not_refused_in_chinese),
    ("no starter [what] list ships, in any language",
     case_no_starter_what_list_ships_in_any_language),
    ("an owner who wrote [what] phrases gets them back",
     case_an_owner_who_wrote_phrases_gets_them_back),
    ("a bare string is a [what] phrase too", case_a_bare_string_is_a_phrase_too),
    ("a broken [what] list costs a style guide, not a run",
     case_a_broken_reference_list_costs_a_style_guide_not_a_run),
    ("the owner can override one line", case_the_owner_can_override_one_line),
    ("a new hint reaches a pack that overrode the old one",
     case_a_new_hint_reaches_a_pack_that_overrode_the_old_one),
    ("an English pack writes an English plan", case_an_english_pack_writes_an_english_plan),
    ("an English pack writes an English execution record",
     case_an_english_pack_writes_an_english_execution_record),
    ("a zh-TW pack writes the legacy strings", case_a_zh_pack_writes_the_legacy_strings),
    ("the screen-capture limit is stated in the owner's language",
     case_the_screen_capture_limit_is_stated_in_the_owners_language),
    ("a pack with no declared language gets the legacy strings",
     case_a_pack_with_no_language_still_gets_the_legacy_strings),
    ("report counters survive translation",
     case_the_report_counts_rows_by_tag_not_by_note_text),
]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    results = []
    for name, fn in CASES:
        try:
            if name in NEEDS_TMP:
                tmp = Path(tempfile.mkdtemp(prefix="i18n_case_"))
                try:
                    ok, detail = fn(tmp)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            else:
                ok, detail = fn()
        except Exception as e:                      # a raising case is a failure
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append((name, bool(ok), detail))

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name.ljust(width)}"
              + (f"   {detail}" if detail and (VERBOSE or not ok) else ""))
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(CASES)} i18n cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
