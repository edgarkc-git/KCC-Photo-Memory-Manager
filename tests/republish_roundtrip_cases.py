#!/usr/bin/env python3
"""Cases for the self-republish round trip that BOTH rendered pages use.

A page carries a base64 copy of its own template and rebuilds itself from it
when the owner submits. The rebuild used `atob()`, which returns a BINARY
string -- one character per byte, i.e. latin-1 -- so every multi-byte UTF-8
character came back double-encoded.

⛔ This is invisible to every check that existed. The FIRST render is clean, so
`photo_review_page.assert_clean_text` passes; the corruption happens in the
browser, after render, and only on the version the owner submits. It was found
by an owner reading a live page (20260901), not by a suite, and it had been
shipping in `review-page.html` the whole time -- that template carries five
non-ASCII characters and made the same call.

These cases simulate both halves of the browser's decode so the regression
cannot come back silently.
"""

import base64
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(os.path.dirname(HERE), "templates")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %-5s %-58s %s" % ("ok" if cond else "FAIL", name, detail))


def atob(b64):
    """What the browser's atob() gives you: latin-1, one char per byte."""
    return base64.b64decode(b64).decode("latin-1")


def b64utf8(b64):
    """What the fixed helper gives you: the bytes decoded as UTF-8."""
    return base64.b64decode(b64).decode("utf-8")


# What a latin-1 round trip leaves behind -- the same family as
# photo_review_page.MOJIBAKE, widened to the punctuation these pages use.
MOJIBAKE = re.compile("[ÂÃâ][ -¿–—·]")

PAGES = ("onboarding-page.html", "review-page.html")


def main():
    print("\nrepublish round-trip cases\n")

    for name in PAGES:
        path = os.path.join(TEMPLATES, name)
        src = io.open(path, encoding="utf-8").read()
        b64 = base64.b64encode(src.encode("utf-8")).decode("ascii")

        # ---- the positive control -------------------------------------
        # Every assertion below is about non-ASCII surviving a round trip. A
        # template that had none would pass all of them while proving nothing,
        # and both templates would then be free to lose their punctuation with
        # no case noticing.
        non_ascii = sorted({c for c in src if ord(c) > 127})
        check("%s carries non-ASCII to lose" % name,
              len(non_ascii) > 0,
              "%d distinct" % len(non_ascii))

        # ---- the bug, reproduced --------------------------------------
        check("%s: a raw atob() DOES corrupt it" % name,
              bool(MOJIBAKE.search(atob(b64))),
              "if this stops failing, the bug moved, not the fix")

        # ---- the fix ---------------------------------------------------
        fixed = b64utf8(b64)
        check("%s: the UTF-8 decode round-trips exactly" % name,
              fixed == src and not MOJIBAKE.search(fixed))

        # ---- and the page must actually USE the fixed one --------------
        check("%s calls b64utf8, not a bare atob" % name,
              "b64utf8(" in src
              and not re.search(r"=\s*atob\(\s*(?:tplB64|document)", src),
              "the helper existing is not the page using it")

    print("\n  %d passed, %d failed\n" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
