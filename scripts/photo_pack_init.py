#!/usr/bin/env python3
"""Create an empty photo memory pack for one owner, from the repo template.

The engine hard-fails when a collection names an owner with no pack; this is
the one command that fixes that. It only lays out the folder — the pack's
CONTENT is drafted from the photos themselves during onboarding (v2 Phase C),
not typed in from imagination.

  python3 photo_pack_init.py <memory_root> <slug> [--display "Renée Dubois"]

Slug rule: lowercase ASCII [a-z0-9-]. A name outside that set gets a
transliterated slug with the display name kept inside the files (owner
Renée Dubois -> folder renee-dubois, display Renée Dubois).

Nothing here belongs in the engine repo — put <memory_root> wherever the
owner's private notes live, and point collection.json at it:

  {"owner": "<slug>", "memory_root": "<absolute path to memory_root>"}

Use an ABSOLUTE path there. collection.json's "memory_root" is resolved
against the directory the engine is run FROM, not against collection.json, so
a relative value binds the pack for one working directory and no other. This
command prints the absolute form for you to paste.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "photo-memory" / "_template"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("memory_root")
    ap.add_argument("slug")
    ap.add_argument("--display", help="display name (defaults to the slug)")
    args = ap.parse_args()

    if not re.fullmatch(r"[a-z0-9-]+", args.slug):
        sys.exit(f"slug must be lowercase ASCII [a-z0-9-]: {args.slug!r}")
    dest = Path(args.memory_root).expanduser() / args.slug
    if dest.exists():
        sys.exit(f"{dest} already exists — refusing to overwrite a pack")

    shutil.copytree(TEMPLATE, dest)
    display = args.display or args.slug
    fill = {"{{SLUG}}": args.slug, "{{DISPLAY}}": display}
    for path in dest.rglob("*"):
        if path.is_file():
            text = path.read_text()
            for token, value in fill.items():
                text = text.replace(token, value)
            path.write_text(text)
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", args.slug)))

    # D-09. What gets pasted into collection.json must be a path that resolves
    # from anywhere, because collection.json is read relative to the CURRENT
    # DIRECTORY, not relative to itself. Printing back a relative <memory_root>
    # verbatim generates a binding that works from exactly one folder — and the
    # engine's (correct, fail-closed) refusal then names a path the owner
    # cannot see is relative.
    root = dest.parent.resolve()
    print(f"created pack for {display} at {dest}")
    print('bind it: add {"owner": "%s", "memory_root": "%s"} to collection.json'
          % (args.slug, root))
    if not Path(args.memory_root).expanduser().is_absolute():
        print(f'note: you passed a relative memory_root ({args.memory_root!r}). '
              "The absolute form above is what collection.json needs — a "
              "relative one resolves against whatever directory the engine is "
              "run from, so the binding would work from one folder only.")


if __name__ == "__main__":
    main()
