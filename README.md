# Photo-Manager

To manage the photos and videos from your camera rolls from phone and
digital camera.

Sort a phone/camera photo dump into dated, named folders you can actually
browse — **the folder tree is the product**. The engine plans, a human
approves, the engine copies and verifies. Originals are never moved, renamed
or deleted.

**If your agent refuses a command with `[Code from External]`**, see
[step 0 in docs/INSTALL.md](docs/INSTALL.md#step-0-if-your-agent-refuses-to-run-this-product).

## Where it runs

Claude Code in a terminal, with the photos and the destination on disks that
machine can read directly. **Measured on macOS and Windows 11. Linux is
untested. Claude Cowork is not supported.** Details: [docs/INSTALL.md](docs/INSTALL.md).

## Quick start

1. Unzip onto a local disk and rename the inner folder to `photo-manager`; install
   exiftool and Python 3.10+ ([INSTALL.md](docs/INSTALL.md), steps 1-2).
2. Run `python3 "<product folder>/scripts/photo_run.py" doctor` (Windows:
   `py "<product folder>\scripts\photo_run.py" doctor`) and install what it names.
3. Make a new empty folder for this photo collection and start Claude Code in it.
4. Type: `I want to sort a new photo collection. The product folder is <product folder>. Read <product folder>/photo-init/SKILL.md and follow it, one step at a time.`
   (The Windows form, with backslashes, is in INSTALL.md step 5.)
5. Answer its questions. Nothing is copied until you approve it.

## Read next

- [docs/INSTALL.md](docs/INSTALL.md): install, step 0, first start, update, uninstall.
- [docs/YOUR-DATA.md](docs/YOUR-DATA.md): every place it writes, what leaves your
  machine, and how to delete it all.
- [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md): the pipeline, what is in this folder,
  status and licence (Apache 2.0).
- Running the tests: see [tests/README.md](tests/README.md) and the last section of
  [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md#running-the-tests).
