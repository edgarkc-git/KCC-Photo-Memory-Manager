#!/usr/bin/env python3
"""Unit cases for the EXIF pre-classifier — the positive control the golden
harness structurally cannot give.

A golden dump can only prove that a rule does not misfire on files that
already exist in it. None of the four frozen dumps contains an Android-style
`Screenshot_*` file, so a screenshot rule could be entirely broken and still
replay 13,208 rows green. These cases assert the rule fires, using the real
filenames and real dimensions of screenshots this archive actually holds.

  python3 tests/preclassify_cases.py [-v]

Exit 0 = pass. No files are read; every row is written out here.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from photo_sample import TIERS, preclassify, tier_of  # noqa: E402

NONE = {}                                    # no pack -> engine defaults
# A pack that has measured its owner's messenger ladder (A34a / T3). The values
# are this project's OWNER's, which is why they live in a fixture pack here and
# ship empty in the engine: another owner's messenger uses different ones.
LADDER = {"im_long_edges": [1280, 1477, 1478, 1705, 1706]}
LADDER_IPHONE = {**LADDER, "screen_dims": [[1170, 2532]]}
SAMSUNG = {"own_camera_makes": ["Apple", "samsung"]}
# The pre-G-1 flat shape, kept flat ON PURPOSE: it is the only proof left in
# the suite that an un-migrated pack still detects screenshots.
NOTE10 = {"own_camera_makes": ["samsung"], "screen_dims": [[1080, 2280]]}
# The same pack after G-1, size paired with the device it belongs to.
NOTE10_PAIRED = {"own_camera_makes": ["samsung"],
                 "screen_dims": [{"model": "samsung SM-N9750",
                                  "dims": [1080, 2280]}]}


def row(name, ftype, w, h, make="-", model="-", **kw):
    r = {"FileName": name, "FileType": ftype, "ImageWidth": str(w),
         "ImageHeight": str(h), "Make": make, "Model": model,
         "DateTimeOriginal": "2023:09:17 12:06:31", "GPSPosition": "-"}
    r.update(kw)
    return r


# (label, row, profile, expected class)
CASES = [
    # --- the Group 6 lesson: real Android screenshots, 2 of 4 cropped away
    #     from any screen size. The filename is what survives cropping.
    ("android screenshot, cropped 1079x1085",
     row("Screenshot_20230917_120631.jpg", "JPEG", 1079, 1085), NOTE10,
     "screenshot"),
    ("android screenshot, cropped 1080x1524",
     row("Screenshot_20231221_085540.jpg", "JPEG", 1080, 1524), NOTE10,
     "screenshot"),
    ("android screenshot, full screen 1080x2280",
     row("Screenshot_20231218-213432_LINE.jpg", "JPEG", 1080, 2280), NOTE10,
     "screenshot"),
    ("android screenshot with spaces in the name",
     row("Screenshot_20231127-083141_The Garden Residences.jpg", "JPEG",
         1080, 2280), NOTE10, "screenshot"),
    # …and they must be caught with NO pack at all: the filename rule is
    # device-independent, which is the whole point of having it.
    ("android screenshot, no pack loaded",
     row("Screenshot_20230917_120631.jpg", "JPEG", 1079, 1085), NONE,
     "screenshot"),
    ("android screen recording -> screen_record",
     row("Screen_Recording_20240101_101010.mp4", "MP4", 1080, 2280), NONE,
     "screen_record"),

    # --- iOS: no filename signal at all, so the dimension rule carries it
    ("iphone screenshot is IMG_*.PNG at a screen size",
     row("IMG_4210.PNG", "PNG", 1170, 2532), NONE, "screenshot"),
    ("same size but shot on a camera -> not a screenshot",
     row("IMG_4210.PNG", "PNG", 1170, 2532, make="Apple", model="iPhone 12"),
     NONE, "own"),

    # --- the 326-video hazard: 1920x1080 is the commonest video resolution
    #     there is. It must never be a screen recording by default, and it
    #     only becomes one if an owner's pack actually says so.
    ("1920x1080 video is NOT a screen recording by default",
     row("20211002_133155.mp4", "MP4", 1920, 1080), NONE, "own"),
    ("pack screen size drives detection",
     row("nameless.png", "PNG", 1080, 2280), NOTE10, "screenshot"),
    ("...and the same file is ordinary without that pack",
     row("nameless.png", "PNG", 1080, 2280), NONE, "own"),

    # --- G-1: the paired shape and the flat one must decide identically.
    #     The pairing is for auditing; it is not allowed to change routing.
    ("a model-paired screen size detects the same screenshot",
     row("nameless.png", "PNG", 1080, 2280), NOTE10_PAIRED, "screenshot"),
    ("a model-paired screen size matches the other orientation too",
     row("nameless.png", "PNG", 2280, 1080), NOTE10_PAIRED, "screenshot"),
    ("a model-paired size leaves an unrelated size alone",
     row("nameless.png", "PNG", 1200, 900), NOTE10_PAIRED, "own"),

    # --- G-3: a third-party capture tool names its own file, at a size no
    #     phone screen has. The platform's own names already matched; these
    #     are the ones that escaped, and they escape at ANY size.
    ("snipaste capture at a random size",
     row("Snipaste_2024-03-11_09-42-17.png", "PNG", 1443, 812), NONE,
     "screenshot"),
    ("windows snip & sketch ScreenClip",
     row("ScreenClip.png", "PNG", 902, 511), NONE, "screenshot"),
    ("snipping tool Capture.PNG",
     row("Capture.PNG", "PNG", 1235, 690), NONE, "screenshot"),
    ("snipping tool Capture (2).png",
     row("Capture (2).png", "PNG", 1235, 690), NONE, "screenshot"),
    # i18n-guard:allow-begin — locale detection data, not user-facing output:
    # a filename the detector has to READ. Asserting the non-Latin half of
    # SCREENSHOT_NAME needs a non-Latin filename, or the case tests nothing.
    ("a zh-TW capture-tool name",
     row("擷取畫面 2024-03-11 094217.png", "PNG", 1443, 812), NONE,
     "screenshot"),
    # i18n-guard:allow-end
    # …and the narrow anchor on `capture`: an ordinary camera-app filename
    # that merely starts with the word must NOT be swept into the bucket.
    ("captured_moment.jpg is not a capture-tool name",
     row("captured_moment.jpg", "JPEG", 3000, 2000), NONE, "own"),
    ("CaptureOne export is not a capture-tool name",
     row("CaptureOne_0031.jpg", "JPEG", 6000, 4000), NONE, "own"),
    ("a capture-tool name with camera tags stays a photo",
     row("Capture.PNG", "PNG", 4032, 3024, make="Apple", model="iPhone 12"),
     NONE, "own"),
    ("a third-party screen RECORDING is a screen_record",
     row("Snipaste_2024-03-11_09-42-17.mp4", "MP4", 1443, 812), NONE,
     "screen_record"),

    # --- a photo that merely mentions a screenshot in its name, with camera
    #     tags, is a photo (the no-camera gate holds)
    ("camera-tagged file named Screenshot* stays a photo",
     row("Screenshot_of_the_hill.jpg", "JPEG", 4032, 3024,
         make="samsung", model="SM-N975F"), NOTE10, "own"),

    # --- own vs shared, the item-2 rule, at the unit level
    ("samsung file is the owner's own when the pack says so",
     row("20211002_133155.jpg", "JPEG", 4032, 3024,
         make="samsung", model="SM-N975F"), SAMSUNG, "own"),
    ("samsung file reads as shared with no pack (the bug's shape)",
     row("20211002_133155.jpg", "JPEG", 4032, 3024,
         make="samsung", model="SM-N975F"), NONE, "shared"),
    ("a make outside the owner's list is still shared",
     row("DSC_0001.JPG", "JPEG", 6000, 4000,
         make="NIKON CORPORATION", model="Z 8"), SAMSUNG, "shared"),
    ("random-name no-camera save stays shared (LINE/AirDrop)",
     row("ABCD1234.JPG", "JPEG", 1200, 900), SAMSUNG, "shared"),
    ("no date, no GPS, no camera -> no_exif",
     row("weird.jpg", "JPEG", 800, 800, DateTimeOriginal="-"), SAMSUNG,
     "no_exif"),

    # ================= A34a — the non-EXIF tiers (SPEC v1.2) =================

    # --- T0. Excluded at scan since bd1a3b2, so this only reaches manifests
    #     written before 2026-07-30 — which are still on disk and still
    #     replayed. Without the tier they were copied into the review inbox.
    ("T0 AppleDouble sidecar is junk, not a file to review",
     row("._IMG_7902.PNG", "PNG", 1170, 2532), NONE, "junk"),
    ("T0 a resource-fork FileType is junk whatever it is named",
     row("IMG_1.JPG", "MacOS", 100, 100), NONE, "junk"),

    # --- T1. D-N8 (signed): EXACT screen resolution, and NO file-type guard.
    #     The guard used to require PNG, which missed every capture the owner
    #     had edited: iOS re-renders an edited asset as IMG_E*.JPG at the same
    #     pixel size, and 16 of the 17 files this widening catches in the
    #     corpus are exactly that.
    ("T1 an EDITED iOS screen capture is JPEG at the same size",
     row("IMG_E2295.JPG", "JPEG", 1170, 2532), NONE, "screenshot"),
    ("T1 a HEIC at exactly the screen size is still a capture",
     row("IMG_E2312.HEIC", "HEIC", 1170, 2532), NONE, "screenshot"),
    ("T1 landscape orientation counts as the same screen",
     row("IMG_9.JPG", "JPEG", 2532, 1170), NONE, "screenshot"),
    # ⛔ and the rule stops at EXACT. A capture later shrunk by a messenger
    #    keeps its ASPECT and loses its size; D-N8 sends those to VI rather
    #    than guessing from dimensions, so they must NOT be caught here.
    ("T1 a SHRUNK capture at the same aspect is not caught by dimension",
     row("IMG_8.JPG", "JPEG", 1883, 870, DateTimeOriginal="-"), NONE,
     "no_exif"),

    # --- T2. The messenger wrote the name. These are product facts, so they
    #     ship: an owner should not have to discover that LINE prefixes its
    #     albums. Note the pack is NONE in every case.
    ("T2 a LINE album file is shared, with no pack at all",
     row("LINE_ALBUM_20240101_123456.jpg", "JPEG", 1477, 1108), NONE, "shared"),
    ("T2 a LINE movie is shared, not the owner's own capture",
     row("LINE_MOVIE_1626496012182.mp4", "MP4", 540, 960), NONE, "shared"),
    ("T2 the WhatsApp form needs its date and WA serial",
     row("IMG-20240101-WA0001.jpg", "JPEG", 800, 600), NONE, "shared"),
    # ⛔ `IMG-` alone is far too close to an ordinary camera name, which is why
    #    that prefix is anchored and this must NOT be shared.
    ("T2 a bare IMG- name is NOT a messenger file",
     row("IMG-1234.jpg", "JPEG", 800, 600, make="Apple", model="iPhone 12"),
     NONE, "own"),

    # --- T3. The compression ladder, and it is OFF until a pack measures one.
    ("T3 the ladder does nothing without a pack — this is the shipped default",
     row("random.jpg", "JPEG", 1108, 1477, DateTimeOriginal="-"), NONE,
     "no_exif"),
    ("T3 with the owner's measured ladder, the same file is shared",
     row("random.jpg", "JPEG", 1108, 1477), LADDER, "shared"),
    ("T3 matches on the LONG edge, either orientation",
     row("random.jpg", "JPEG", 1705, 960), LADDER, "shared"),
    # ⛔ STILLS ONLY, and this is the measured guard, not a cautious one.
    #    720p video is 1280x720, and 1280 is also a ladder value: without this
    #    the ladder claims 168 ordinary videos in the corpus, every one of
    #    them at exactly this size. No messenger-named video exists there, so
    #    the guard costs nothing.
    #    The real rows carry a CreateDate, so without the guard they flip
    #    `own` -> `shared`: the owner's own clip described as someone else's.
    ("T3 a 720p video is NOT a shared photo — 1280 is 720p, not a ladder",
     row("IMG_7122.MP4", "MP4", 720, 1280), LADDER, "own"),
    ("T3 the same in landscape",
     row("IMG_7381.MP4", "MP4", 1280, 720), LADDER, "own"),
    # …and a messenger-NAMED video still gets through, on T2, one tier above.
    ("T3 a LINE video is still shared — caught by name, not by ladder",
     row("LINE_MOVIE_1.mp4", "MP4", 720, 1280), LADDER, "shared"),

    # --- ordering. A capture forwarded through LINE satisfies T1 and T2 both,
    #     and the signed policy is that the capture verdict wins.
    ("order: a capture forwarded through LINE is a screenshot, not shared",
     row("LINE_ALBUM_x.png", "PNG", 1170, 2532), LADDER_IPHONE, "screenshot"),

    # --- T4/T5. Both route to no_exif today; the tier is what tells them
    #     apart, and A38 reads it.
    ("T4 a video with no date of its own",
     row("clip.mp4", "MP4", 1920, 1440, DateTimeOriginal="-"), NONE, "no_exif"),
    ("T5 everything else — this is the set VI reads",
     row("unknown.jpg", "JPEG", 2729, 1535, DateTimeOriginal="-"), NONE,
     "no_exif"),
]


# tier_of returns the EVIDENCE alongside the class. Several tiers share a
# class — T2/T3 are both `shared`, T4/T5 both `no_exif` — so a test on the
# class alone cannot tell which rule fired, and the review page has to show
# the owner which one did.
TIER_CASES = [
    ("T0", row("._x.JPG", "JPEG", 10, 10), NONE),
    ("T1", row("IMG_E1.JPG", "JPEG", 1170, 2532), NONE),
    ("T2", row("LINE_ALBUM_1.jpg", "JPEG", 800, 600), NONE),
    ("T3", row("plain.jpg", "JPEG", 1108, 1477), LADDER),
    ("T4", row("clip.mp4", "MP4", 640, 480, DateTimeOriginal="-"), NONE),
    ("T5", row("plain.jpg", "JPEG", 2729, 1535, DateTimeOriginal="-"), NONE),
    # A camera-bearing row gets NO tier: the tiers are for files with no
    # camera, and a tier here would be claiming to know better than the
    # device that wrote the file.
    (None, row("IMG_1.JPG", "JPEG", 4032, 3024, make="Apple",
               model="iPhone 12"), NONE),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    failures = []
    width = max(len(c[0]) for c in CASES)
    for label, r, profile, want in CASES:
        got = preclassify(r, profile)
        ok = got == want
        if not ok:
            failures.append(label)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  {label.ljust(width)}   "
                  f"{want}" + ("" if ok else f" -> got {got}"))

    for want_tier, r, profile in TIER_CASES:
        got_tier, got_cls = tier_of(r, profile)
        ok = got_tier == want_tier
        label = f"tier_of -> {want_tier or 'no tier (camera-bearing)'}"
        if not ok:
            failures.append(label)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  {label.ljust(width)}   "
                  f"{want_tier}" + ("" if ok else f" -> got {got_tier}"))
        # the tier and the class must agree with the table, or the two have
        # drifted apart and the review page would show the wrong reason
        if got_tier is not None and TIERS[got_tier] != got_cls \
                and not (got_tier == "T1" and got_cls == "screen_record"):
            failures.append(f"{label}: tier {got_tier} claims {TIERS[got_tier]}"
                            f" but classified {got_cls}")

    total = len(CASES) + len(TIER_CASES)
    print(f"\n{total - len(failures)}/{total} preclassify cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
