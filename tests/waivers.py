#!/usr/bin/env python3
"""Explained-diff policy deltas for the golden-dump harness.

A golden dump records what the pipeline *shipped* on the day it ran. Naming
policy decided after that day legitimately changes what the engine produces
today. Those diffs must be explained — not silently accepted, and not treated
as regressions.

The mechanism is a FORWARD RECONSTRUCTION, not a diff whitelist: take the
shipped plan, push it through each documented decision that post-dates it, and
require the result to equal today's output EXACTLY. A snapshot of "these 94
rows differ" rots the moment a row is added; a reconstruction absorbs new rows
that differ in the same understood way and fails on anything else.

Every input to the reconstruction comes from the frozen fixture (the shipped
CSV plus manifest.csv), never from the engine's current output — otherwise a
delta could "explain" any behaviour at all.

Scope is part of the assertion. A dump planned AFTER a decision must reproduce
byte-for-byte with no deltas at all; if D14 appears to explain a diff in a
post-D14 dump, that is a regression and the harness says so.

Two KINDS of delta live here, and they are not the same claim:

  * a naming POLICY decided after the dump shipped (D13, D14) — the old output
    was right for its day;
  * a BUG fixed after the dump shipped (profile-aware preclassify) — the old
    output was wrong on the day it shipped, and the reconstruction says
    exactly which rows were wrong and why. Keeping the two apart matters: a
    bug delta must be justified by a fixture INPUT (here the pack's
    own_camera_makes), never by "the engine changed".

Decisions modelled here
  D13 (owner ruling 2026-07-06) — a file whose extension disagrees with its real
      exiftool FileType is copied under the corrected name, decided at plan
      time. Dumps planned earlier shipped the wrong name and were repaired
      afterwards by the OA-4 post-copy rename pass.
      Knock-on: a corrected name can collide inside the same plan, so the
      collision suffixer (_dup2, _dup3 …) reshuffles names (Lesson L12).
      Knock-on: the no-date CSV changed from a review list to an executable
      plan routing everything to YYYYMM00_待分類.
  G-3 (owner ruling 2026-08-05) — `preclassify()`'s no-camera/no-date/no-GPS class
      was renamed `ai_gen` -> `no_exif`. A LABEL change only: it appears in
      the no-date CSV's `preclass` cell and must move nothing else.
  D14 (owner ruling 2026-07-13) — monthly buckets gained a "00" day field so they
      sort inside their month group: YYYYMM_[name] -> YYYYMM00_[name].
  D-N8 / A34a (Non-EXIF SPEC v1.2, signed 2026-09-02) — the screen-capture test
      is EXACT resolution and any file type. It used to require PNG, which
      missed a screen capture the owner had edited in Photos: iOS re-renders
      an edited asset as `IMG_E*.JPG` at the SAME pixel size, so 16 of the 17
      files this widening catches in the corpus are edited screen captures
      that were sitting in the review inbox. The same card gave T2 a messenger
      filename test, so a LINE video that had been filed as the owner's own
      capture is now noted `shared`.
      ⛔ Both are POLICY deltas on a signed SPEC, not bug repairs: the old
      output was right for the rule of its day.

Bugs modelled here
  profile-aware preclassify (fixed 2026-07-31) — photo_plan.route() called
      preclassify() without the owner pack, so own_camera_makes fell back to
      the generic Apple-only list and every photo from any other make was
      noted `shared` ("not shot on this device"). Nothing was ever misfiled —
      the note is cosmetic at plan stage — but the plan document described
      most of a Note10+ collection as somebody else's photos.
  overrides before the classifiers (A5, fixed 2026-08-31) — route() evaluated
      a plan's `overrides` before the screenshot / D13 / G-2 branches, so an
      override date swallowed all three (LL-PHO-96). Files WERE misfiled: a
      screenshot taken on an overridden date was copied into the trip folder,
      untagged, so the plan report counted it as an ordinary photo. The
      reconstruction moves exactly those rows the fixture's own manifest
      proves are screen captures, and nothing else.
      ⛔ LL-PHO-96 recorded the intersection as EMPTY. It is not: 18 rows
      across three frozen dumps sit in it, which is why this is a bug delta
      and not a note about a risk to future plans.
"""

import csv
import json
import re
from pathlib import Path, PurePosixPath

# Dumps whose plans were written before each decision.
PRE_D13 = {"202605", "202603", "202602"}
PRE_D14 = {"202605", "202603", "202602"}
# Dumps whose no-date CSV shipped the EXIF class under its old name. The rule
# did not change — only what it is called — so this delta may rewrite the
# `preclass` cell and NOTHING else. If it ever appears to explain a routing or
# a naming difference, the model is wrong.
PRE_G3_RENAME = {"202605", "202603", "202602", "group3"}
PRECLASS_RENAMED = {"ai_gen": "no_exif"}

# Dumps planned while route() still ran preclassify without the owner pack.
# Only a dump shot on a make outside the generic list can show the bug, which
# is why the iPhone dumps are absent rather than merely unaffected.
PRE_PROFILE_AWARE = {"group3"}

# Dumps planned while route() evaluated `overrides` before the per-file
# classifiers (A5 / LL-PHO-96). EVERY fixture is in here — they all shipped
# before the fix — and the ones with no overrides, or with no screen capture
# on an overridden date, simply never fire the delta. Listing only the dumps
# that visibly change would make the set a diff whitelist, which is the thing
# this module is not.
PRE_OVERRIDE_AFTER_CLASSIFY = {"202605", "202603", "202602", "group3",
                               "screens01", "tier3cat", "tier3hike"}

# Dumps planned before the non-EXIF tiers (A34a / SPEC v1.2). Every fixture
# shipped before them, so every fixture is listed; the ones holding no edited
# screen capture and no messenger-named file simply never fire the delta.
PRE_NONEXIF_TIERS = {"202605", "202603", "202602", "group3",
                     "screens01", "tier3cat", "tier3hike"}

# preclassify()'s screenshot test, restated so the harness asserts against the
# rule as written down rather than against whatever photo_sample.py currently
# does. Kept to the two branches that can reach an override destination: a
# name a capture tool wrote, and a PNG (or video) at a known screen size with
# no camera tags. The name list is the engine's, current as of 2026-08-31.
HARNESS_SCREENSHOT_NAME = re.compile(
    r"^(screen[ _-]?shot|screen[ _-]?recording|screenrecord|scrn|"
    r"螢幕擷取|螢幕錄製|螢幕快照|截圖|截屏|스크린샷|"
    r"snipaste|screenclip|擷取畫面|"
    r"capture(?:[ _-]?\d+|\s?\(\d+\))?\.)", re.I)
HARNESS_DEFAULT_SCREEN_DIMS = [["1170", "2532"]]              # iPhone 12
HARNESS_VIDEO_TYPES = {"MOV", "MP4"}
# T2's messenger filename test, restated (A34a). The ladder (T3) is NOT
# restated: it ships empty and no fixture pack sets `im_long_edges`, so a
# restatement here would assert a rule no fixture can exercise.
# i18n-guard:allow-begin — messenger filename signatures, not user-facing output.
HARNESS_IM_PREFIXES = ("LINE_", "KAKAOTALK_", "SCREENSHOT_")
HARNESS_IM_WHATSAPP = re.compile(r"^IMG-\d{8}-WA\d+", re.I)
# i18n-guard:allow-end
# The bucket a screen capture lands in, for a run with no pack (the legacy
# zh-TW table). A fixture whose pack declares a language would get a different
# word, so the delta refuses to fire for one rather than guess — see
# forward_plan().
SCREENSHOT_BUCKET = "截圖"

# The dump's own YYYYMM, used to check the no-date bucket independently of the
# engine's dump_yyyymm() derivation. None = the dump has no single month.
DUMP_YYYYMM = {"202605": "202605", "202603": "202603", "202602": "202602",
               "group3": None}

# D13's canonical extension per exiftool FileType, restated here on purpose:
# the harness must assert the rule independently of the engine's own table.
EXT_BY_FILETYPE = {
    "JPEG": ("JPG", {"JPG", "JPEG"}), "HEIC": ("HEIC", {"HEIC"}),
    "HEIF": ("HEIF", {"HEIF"}), "PNG": ("PNG", {"PNG"}),
    "TIFF": ("TIF", {"TIF", "TIFF"}), "WEBP": ("WEBP", {"WEBP"}),
    "GIF": ("GIF", {"GIF"}), "BMP": ("BMP", {"BMP"}), "DNG": ("DNG", {"DNG"}),
    "MOV": ("MOV", {"MOV"}), "MP4": ("MP4", {"MP4"}), "M4V": ("M4V", {"M4V"}),
    "AVI": ("AVI", {"AVI"}), "3GP": ("3GP", {"3GP"}),
}

DUP_NOTE = "同名檔已在本計畫 → _dup 後綴"
NO_DATE_NOTE = "無法分類(無日期/無地點)→ 待分類"

REASONS = {
    "D13-rename-at-copy": "extension corrected at plan time (D13, 2026-07-06)",
    "D13-dup-suffix": "corrected name collided in-plan → _dup suffix (D13/L12)",
    "D14-monthly-bucket": "monthly bucket YYYYMM_ → YYYYMM00_ (D14, 2026-07-13)",
    "D13-no-date-executable": "no-date review list became an executable 待分類 "
                              "plan (D13 待分類 mod, 2026-07-06 evening)",
    "G3-no-exif-rename": "the no-camera/no-date/no-GPS class was renamed "
                         "`ai_gen` -> `no_exif`, for the evidence it has "
                         "rather than the guess it made (G-3, 2026-08-05)",
    "BUG-profile-aware-preclassify": "owner's own camera was labelled `shared` "
                                     "because route() ran without the pack "
                                     "(fixed 2026-07-31)",
    "BUG-override-before-classify": "a screen capture on an overridden date was "
                                    "copied into the override's folder because "
                                    "`overrides` ran before the classifiers "
                                    "(A5 / LL-PHO-96, fixed 2026-08-31)",
    "A34A-screenshot-any-filetype": "the screen-capture test dropped its PNG "
                                    "guard, so an edited capture (iOS re-renders "
                                    "it as IMG_E*.JPG at the same pixel size) "
                                    "leaves the review inbox (D-N8, 2026-09-02)",
    "A34A-messenger-filename": "T2: a file the messenger named is `shared`, so a "
                               "LINE video stops being filed as the owner's own "
                               "capture (SPEC v1.2, 2026-09-02)",
    "A34A-appledouble-junk": "T0: an AppleDouble sidecar is `junk` and is no "
                             "longer copied into the review inbox. Scan has "
                             "excluded them since bd1a3b2 (2026-07-30), so this "
                             "reaches only manifests written before that date",
}

# The exact note route() writes for a file it believes was not shot on the
# owner's own device. Restated here so a change to the engine's wording shows
# up as a failure instead of quietly widening what this delta explains.
SHARED_NOTE = "shared(非本機拍攝,依日期歸檔 D-B)"


class Fixture:
    """The frozen inputs a reconstruction is allowed to consult."""

    def __init__(self, input_dir):
        self.dir = Path(input_dir)
        self.filetype, self.order, self.make = {}, {}, {}
        self.screen_shape = {}
        with open(self.dir / "manifest.csv", newline="") as f:
            for i, row in enumerate(csv.DictReader(f)):
                self.filetype[row["SourceFile"]] = row.get("FileType", "-")
                self.make[row["SourceFile"]] = row.get("Make", "-")
                self.order[row["SourceFile"]] = i
                self.screen_shape[row["SourceFile"]] = (
                    row.get("FileName", ""), row.get("Model", "-"),
                    (row.get("ImageWidth", "-"), row.get("ImageHeight", "-")))
        plans = json.loads((self.dir / "plans.json").read_text())
        self.dest_root = plans.get("dest_root")
        self.pack = self._pack()
        self.own_makes = {m.lower() for m in self.pack.get("own_camera_makes", [])}
        self.screen_dims = self._screen_dims()
        # (destination, reason) for every override the agent wrote. Both
        # halves: route() returns the override's reason as the row's whole
        # note, so the pair identifies an override row exactly, where the
        # destination alone could also match a leg that happens to share it.
        self.override_rows = {(ov["dest"]["path"]
                               if isinstance(ov.get("dest"), dict)
                               else ov.get("dest"), ov.get("reason", ""))
                              for p in plans["plans"]
                              for ov in p.get("overrides", [])}

    def _pack(self):
        """The fixture's own pack. Read straight off the file rather than
        through photo_profile, so the harness asserts against the fixture's
        declared input and not against whatever the engine's resolver decides
        to do."""
        packs = sorted(self.dir.glob("photo-memory/*/photo-profile.json"))
        if len(packs) > 1:
            raise SystemExit(f"{self.dir}: more than one pack in a fixture — "
                             "one run loads exactly one owner's pack")
        return json.loads(packs[0].read_text()) if packs else {}

    def _screen_dims(self):
        """-> {(w, h)} in both orientations, from the fixture's own pack, or
        the engine's documented default when it has none. Both the pre-G-1
        flat shape and the paired one, restated here on purpose."""
        out = set()
        entries = self._pack().get("screen_dims") or HARNESS_DEFAULT_SCREEN_DIMS
        for e in entries:
            dims = e.get("dims") if isinstance(e, dict) else e
            w, h = (str(v) for v in dims)
            out |= {(w, h), (h, w)}
        return out

    def is_screen_capture(self, source):
        """preclassify()'s screenshot/screen_record test, restated. Only the
        no-camera branches: a file with a Make or a Model is a photo, whatever
        its size.

        ⛔ No file-type guard, since D-N8 (A34a). The rule is the EXACT screen
        resolution and nothing else: an owner who marks up a screen capture in
        Photos gets an `IMG_E*.JPG` back at the same pixel size, and requiring
        PNG left every one of those in the review inbox."""
        name, model, dims = self.screen_shape.get(source, ("", "-", ("-", "-")))
        if self.make.get(source, "-") not in ("-", "") or model not in ("-", ""):
            return False
        if HARNESS_SCREENSHOT_NAME.match(name):
            return True
        return dims in self.screen_dims

    def is_messenger_named(self, source):
        """T2, restated (A34a): the messenger wrote the filename."""
        name = self.screen_shape.get(source, ("", "-", ("-", "-")))[0]
        if self.make.get(source, "-") not in ("-", ""):
            return False
        return (name.upper().startswith(HARNESS_IM_PREFIXES)
                or bool(HARNESS_IM_WHATSAPP.match(name)))


def d13_name(filename, filetype):
    """-> (corrected filename, explanatory note, real format is known)."""
    canon = EXT_BY_FILETYPE.get(filetype)
    if canon is None:
        return filename, "", False
    if PurePosixPath(filename).suffix.lstrip(".").upper() in canon[1]:
        return filename, "", True
    new = str(PurePosixPath(filename).with_suffix("." + canon[0]))
    return new, f"副檔名更正(D13):{filename} → {new}(實際格式 {filetype})", True


def _append(note, extra):
    return (note + ";" if note else "") + extra if extra else note


def apply_collision_suffix(rows):
    """Two sources can map to one corrected name at one destination; later ones
    take _dup2/_dup3. Restated independently of photo_plan.py so that a change
    to the engine's rule shows up as a harness failure rather than passing
    unexamined. rows: dicts with name/dest/action/note, in manifest order.
    -> number of rows suffixed."""
    taken, hits = set(), 0
    for r in sorted(rows, key=lambda r: r["name"]):
        if r["action"] != "copy":
            continue
        key = (r["dest"], r["name"].lower())
        if key in taken:
            stem = PurePosixPath(r["name"]).stem
            ext = PurePosixPath(r["name"]).suffix
            n = 2
            while (r["dest"], f"{stem}_dup{n}{ext}".lower()) in taken:
                n += 1
            r["name"] = f"{stem}_dup{n}{ext}"
            r["note"] = _append(r["note"], DUP_NOTE)
            key = (r["dest"], r["name"].lower())
            hits += 1
        taken.add(key)
    return hits


# How many rows each bug delta is allowed to move, per dump. The fixtures are
# frozen, so this is an exact number, not an estimate: if the fix reaches more
# rows than the pack's own_camera_makes explains, the model is wrong and the
# harness must say so instead of absorbing it.
EXPECTED_FLIPS = {"group3": {"profile_flips": 5239},
                  # A5: the screen captures LL-PHO-96 said did not exist.
                  "202602": {"override_screen_captures": 15},
                  "202603": {"override_screen_captures": 2},
                  "202605": {"override_screen_captures": 1}}


# notes that identify a destination the ENGINE generated (rather than one the
# agent wrote into plans.json, which is used verbatim and never day-filled)
SCREENSHOT_NOTE = "截圖(EXIF規則)"
UNKNOWN_FORMAT_NOTE = "無法判定實際檔案格式(D13)→ 需人工確認"


def d14_bucket(destination, shipped_note):
    """'…/202605_截圖' -> '…/20260500_截圖'.

    D14 renamed the buckets photo_plan generates itself. Destinations the agent
    typed into plans.json are copied verbatim and keep whatever name they were
    given — several of the owner's are YYYYMM_ shaped, so matching on the path
    alone would wrongly "explain" a real routing change. The shipped note is
    what says which branch of route() produced the row."""
    if shipped_note not in (SCREENSHOT_NOTE, UNKNOWN_FORMAT_NOTE):
        return destination
    p = PurePosixPath(destination)
    m = re.fullmatch(r"(\d{6})_(.+)", p.name)
    return str(p.parent / f"{m.group(1)}00_{m.group(2)}") if m else destination


def forward_plan(dump, exp_rows, fx, tally=None):
    """Push shipped plan rows through the decisions that post-date them.
    `tally` (a dict) accumulates per-delta row counts across a dump's plan
    CSVs, so the caller can check the blast radius against EXPECTED_FLIPS.
    -> (reconstructed rows keyed by SourceFile, set of deltas that fired,
        list of problems that make the reconstruction untrustworthy)."""
    fired, problems = set(), []
    tally = {} if tally is None else tally
    work = []
    for r in sorted(exp_rows.values(), key=lambda r: fx.order.get(r["SourceFile"], 1 << 30)):
        row = dict(r)
        name, dest, note = row["FileName"], row["destination"], row["note"]

        # A5 runs FIRST, before D13 appends its extension note: the engine
        # writes route()'s note and then the rename note after it, so a row
        # this delta rewrites has to be rewritten while its note is still the
        # only thing there.
        if (dump in PRE_OVERRIDE_AFTER_CLASSIFY
                and (dest, note) in fx.override_rows
                and fx.is_screen_capture(row["SourceFile"])):
            if fx.pack.get("language"):
                problems.append(
                    f"{row['SourceFile']}: an override row is a screen capture, "
                    "but the fixture's pack declares a language — the bucket "
                    "name is resolved from the pack and this delta only knows "
                    "the legacy one")
                continue
            month = row["date"][:7].replace("-", "")
            dest = f"{fx.dest_root}/{month}00_{SCREENSHOT_BUCKET}"
            note = SCREENSHOT_NOTE
            fired.add("BUG-override-before-classify")
            tally["override_screen_captures"] = \
                tally.get("override_screen_captures", 0) + 1

        if dump in PRE_D13:
            ft = fx.filetype.get(row["SourceFile"], "-")
            if ft not in EXT_BY_FILETYPE:
                problems.append(f"{row['SourceFile']}: FileType {ft!r} is outside "
                                "the D13 canonical map — reconstruction cannot "
                                "predict its destination")
                continue
            # The engine renames from the manifest name, so undo any _dup
            # suffix the original run applied before re-deriving.
            base = re.sub(r"_dup\d+(?=\.[^.]*$)", "", name)
            new, ext_note, _known = d13_name(base, ft)
            if new != base:
                fired.add("D13-rename-at-copy")
            name = new
            if ext_note and row["action"] == "copy":
                note = _append(note, ext_note)

        if dump in PRE_D14:
            moved = d14_bucket(dest, row["note"])
            if moved != dest:
                fired.add("D14-monthly-bucket")
            dest = moved

        if dump in PRE_PROFILE_AWARE and note == SHARED_NOTE:
            # Drop the note only where the pack's own_camera_makes explains
            # it. A file with no Make at all was called `shared` by the
            # random-name rule (LINE/AirDrop saves), which the fix does not
            # touch — it must still say `shared`.
            make = fx.make.get(row["SourceFile"], "-")
            if make not in ("-", "") and make.lower() in fx.own_makes:
                note = ""
                fired.add("BUG-profile-aware-preclassify")
                tally["profile_flips"] = tally.get("profile_flips", 0) + 1

        # T2 (A34a). The reverse direction of the profile delta above: that one
        # REMOVES a shared note the engine no longer writes, this one ADDS the
        # note the engine now writes for a messenger-named file. Only where the
        # shipped row carried no note at all — a row already noted `shared` was
        # already right, and rewriting it would let this delta explain diffs it
        # has nothing to do with.
        if (dump in PRE_NONEXIF_TIERS and not note
                and fx.is_messenger_named(row["SourceFile"])):
            note = SHARED_NOTE
            fired.add("A34A-messenger-filename")
            tally["messenger_named"] = tally.get("messenger_named", 0) + 1

        if dump in PRE_G3_RENAME and row.get("preclass") in PRECLASS_RENAMED:
            row["preclass"] = PRECLASS_RENAMED[row["preclass"]]
            fired.add("G3-no-exif-rename")
            tally["preclass_renamed"] = tally.get("preclass_renamed", 0) + 1

        work.append({"row": row, "name": name, "dest": dest, "note": note,
                     "action": row["action"]})

    if dump in PRE_D13 and apply_collision_suffix(work):
        fired.add("D13-dup-suffix")

    out = {}
    for w in work:
        row = w["row"]
        row["FileName"], row["destination"], row["note"] = w["name"], w["dest"], w["note"]
        out[row["SourceFile"]] = row
    return out, fired, problems


def check_no_date(dump, exp_rows, act_rows, fx):
    """The no-date artifact changed shape, so it is checked by assertion rather
    than by row equality: same files, same EXIF verdicts, and every file routed
    to the one bucket D13 mandates.
    -> (list of problems, set of deltas that fired)."""
    problems, renamed = [], set()
    missing = sorted(set(exp_rows) - set(act_rows))
    extra = sorted(set(act_rows) - set(exp_rows))
    problems += [f"no-date row vanished — {k}" for k in missing]
    problems += [f"no-date row appeared — {k}" for k in extra]

    ym = DUMP_YYYYMM.get(dump)
    if not ym:
        return ["no-date reconstruction needs the dump's YYYYMM"], set()
    bucket = f"{fx.dest_root}/{ym}00_待分類"

    work = []
    for key in sorted(set(exp_rows) & set(act_rows), key=lambda k: fx.order.get(k, 1 << 30)):
        e, a = exp_rows[key], act_rows[key]
        if e.get("action") != "review":
            problems.append(f"{key}: shipped no-date row is not a review row")
        for field in ("FileType", "FileSize", "preclass"):
            want = e.get(field)
            if field == "preclass" and dump in PRE_G3_RENAME:
                want = PRECLASS_RENAMED.get(want, want)
                if want != e.get(field):
                    renamed.add("G3-no-exif-rename")
            # D-N8 (A34a): exact screen resolution, any file type. Applied
            # after the rename so the two compose rather than race — the
            # shipped cell says `ai_gen`, G-3 makes it `no_exif`, and this
            # makes it `screenshot` where the fixture's own dimensions prove
            # the file is a screen capture.
            if (field == "preclass" and dump in PRE_NONEXIF_TIERS
                    and want in ("no_exif", "ai_gen")
                    and fx.is_screen_capture(key)):
                want = "screenshot"
                renamed.add("A34A-screenshot-any-filetype")
            # T0 (A34a). Keyed on the `._` name the fixture itself carries, so
            # this can only ever explain a sidecar — never an ordinary file
            # that happened to land in the same bucket.
            if (field == "preclass" and dump in PRE_NONEXIF_TIERS
                    and PurePosixPath(key).name.startswith("._")):
                want = "junk"
                renamed.add("A34A-appledouble-junk")
            if want != a.get(field):
                problems.append(f"{key}: {field} {e.get(field)!r} -> {a.get(field)!r}")
        name, ext_note, _known = d13_name(e["FileName"], e.get("FileType", "-"))
        work.append({"key": key, "name": name, "dest": bucket, "action": "copy",
                     "note": _append(ext_note, NO_DATE_NOTE)})
    apply_collision_suffix(work)

    for w in work:
        a = act_rows[w["key"]]
        for field, want in (("FileName", w["name"]), ("destination", w["dest"]),
                            ("action", "copy"), ("note", w["note"])):
            if a.get(field) != want:
                problems.append(f"{w['key']}: {field} {a.get(field)!r} != "
                                f"expected-after-D13 {want!r}")
    return problems, {"D13-no-date-executable"} | renamed
