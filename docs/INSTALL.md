# Install and first start

This guide is for the photo owner, not a developer. Every command is shown for
**macOS** and for **Windows 11** side by side. Where a Windows fact was not
measured, it says so.

Words used here:

- **product folder**: the folder that holds `README.md`, `scripts/` and the
  `photo-*` folders. The zip holds ONE folder, `KCC-Photo-Memory-Manager-RS`;
  step 1 unzips it and renames it to `photo-manager`, so the product folder is
  `~/photo-manager` (macOS) or `C:\photo-manager` (Windows). Write its full
  path wherever this guide says `<product folder>`.
- **workspace**: a separate, empty folder you make for ONE photo collection.
  You start the agent (Claude Code) in it. Everything the product remembers
  about that collection is kept inside it (see [YOUR-DATA.md](YOUR-DATA.md)).
- **agent**: Claude Code, which reads the product's instructions and runs its
  commands for you.

## Where it runs

**Run these SKILLs from Claude Code in a terminal, with the photos and the
destination on disks that machine can read directly.**

- **Previews no longer need macOS.** The vision pass makes one preview per
  photo with Pillow (HEIC through `pillow-heif`) and one frame per video with
  ffmpeg. Both come from pip (step 4 below). macOS `sips` / `qlmanage` remain
  as a fallback, chosen with `PHOTO_PREVIEW_BACKEND=sips`.
- **Measured on macOS and on Windows 11** (20260924, 240 photos and videos
  from an iPhone and a Samsung phone, CPU only: previews and vectors 240 of
  240, identity 240 of 240, 0 failed). **Linux is still untested** — treat it
  as untested rather than supported.
- **Claude Cowork is not supported.** It runs its commands in a Linux virtual
  machine even on a Mac (measured: Ubuntu 22.04, no `exiftool`, no `sudo`),
  and connected folders appear under a per-session mount path instead of
  `/Volumes/…` or `/Users/…`, so paths written into `collection.json` there
  do not work from any other session.
- **If previews fail, the stage says so.** `photo_embed.py` and
  `photo_identity.py` exit **3** and print each cause with its count (for
  example `no_ffmpeg`, `no_heif_decoder`). Fix the cause and run the same line
  again; do not carry on past it.

## Step 0: if your agent refuses to run this product

**Skip this step unless a command is refused.** Most first runs need nothing
here. In our own test, a first-time owner with
Claude Code in **auto mode** and no allow rules ran the unpack, `doctor`, the
`.venv`, pip and a quickscan with no refusal; some other sessions were refused,
for reasons not yet known. **Only if your agent is refused** with
`[Code from External]`, choose ONE of the two paths below. That refusal is
Claude Code's own safety check, not an error in the product. The choice is
yours: the product ships no `.claude/settings.json` and never grants itself
permission.

**Path A: approve by hand.** Switch your agent to manual (normal) mode. Each
time it asks to run a product command, answer **"Yes, and don't ask again"**.
That answer covers that EXACT command only, so expect a prompt for each new
command during setup (one measured setup gave 11). When `doctor` says
`ready to start: yes`, switch back to auto mode.

**Path B: paste allow rules, then stay in auto.** Add this block to your OWN
project settings (`.claude/settings.local.json` in the folder you start the
agent from, which is your workspace). Replace `<product folder>` with the full
path of the product folder. Every rule names that folder's `scripts` or its
`.venv`, so nothing else is allowed.

macOS / Linux (bash):

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 <product folder>/scripts/*)",
      "Bash(python3 \"<product folder>/scripts/*)",
      "Bash(python3 -m venv \"<product folder>/.venv\")",
      "Bash(\"<product folder>/.venv/bin/python3\" -m pip install *)",
      "Bash(<product folder>/.venv/bin/python3 <product folder>/scripts/*)",
      "Bash(\"<product folder>/.venv/bin/python3\" \"<product folder>/scripts/*)"
    ]
  }
}
```

Windows (PowerShell). In JSON every `\` of the path is written `\\`:

```json
{
  "permissions": {
    "allow": [
      "PowerShell(py <product folder>\\scripts\\*)",
      "PowerShell(py \"<product folder>\\scripts\\*)",
      "PowerShell(py -3 -m venv \"<product folder>\\.venv\")",
      "PowerShell(& \"<product folder>\\.venv\\Scripts\\python.exe\" -m pip install *)",
      "PowerShell(& \"<product folder>\\.venv\\Scripts\\python.exe\" \"<product folder>\\scripts\\*)",
      "PowerShell(<product folder>\\.venv\\Scripts\\python.exe <product folder>\\scripts\\*)"
    ]
  }
}
```

These rules match the full-path lines `doctor` prints, so use those lines as
printed. With either path, a command that is still refused is shown to you,
never retried or worked around by the agent.

**On Windows, two things do not carry over between the agent's commands.** Its
PowerShell tool goes back to the folder it started in after EVERY command, so
a relative line such as `py scripts\photo_run.py doctor` runs from the wrong
folder: the agent uses the full-path lines `doctor` prints instead. And
`$env:PYTHONUTF8 = "1"` lasts for one command only, which is why step 2 sets
it once as your own user variable.

## 1. Unzip the product onto a local disk

Unzip OUT of your downloads folder onto the computer's own disk, **not** into
a folder that a cloud service syncs (iCloud Drive, OneDrive, Google Drive,
Dropbox). Your downloads folder itself may be synced; that is fine for the
zip, but do not unzip there.

| | macOS (Terminal) | Windows 11 (PowerShell) |
|---|---|---|
| unzip | `unzip ~/Downloads/<zip name>.zip -d ~` | `Expand-Archive -LiteralPath "$HOME\Downloads\<zip name>.zip" -DestinationPath C:\photo-unzip` |
| rename the inner folder | `mv ~/KCC-Photo-Memory-Manager-RS ~/photo-manager` | `Move-Item C:\photo-unzip\KCC-Photo-Memory-Manager-RS C:\photo-manager` |
| result: the product folder | `~/photo-manager` (holds `README.md`) | `C:\photo-manager` (holds `README.md`) |

Both columns were measured (macOS on a scratch copy; Windows by a test agent,
with `Expand-Archive` and `Move-Item`). On Windows you can also right-click
the zip, choose **Extract All…**, then **Browse** to `C:\` before you press
Extract: its default is a folder next to the zip, which is often inside a
synced folder. Then rename the extracted `KCC-Photo-Memory-Manager-RS` folder
to `photo-manager`. Afterwards `C:\photo-unzip` is empty and can be deleted.

Put your workspace folders (step 5) on a local disk too, for example
`~/photo-workspaces/…` or `C:\photo-workspaces\…`.

Why not a synced folder:

- **The product folder grows to about 0.9 GB** once step 4 has made its
  `.venv` (one existing Mac `.venv`; a fresh install was not measured),
  thousands of small files that a sync client would upload and keep in step
  for no benefit.
- **The workspace holds location data.** It keeps every photo's GPS position
  and the likely home areas (see [YOUR-DATA.md](YOUR-DATA.md)). In a synced
  folder that data is copied to the cloud service. That may be your choice,
  but make it on purpose.
- **Windows:** `Documents` is often redirected to OneDrive (it was on the
  Windows 11 test machine), so `C:\Users\<you>\Documents\…` can be a synced
  folder without looking like one.
- **macOS:** iCloud Drive can sync Desktop and Documents ("Desktop & Documents
  Folders"), so keep the product in your home folder, not in those two. And a
  scheduled run cannot read files under Documents, Desktop or Downloads
  without a macOS permission prompt that nobody is awake to answer (measured:
  the job waits forever). This only matters if you later use `photo_schedule`.

The photos themselves can stay where they are (an external drive is normal).
The product only reads them.

## 2. Install the tools

| | macOS | Windows 11 |
|---|---|---|
| **exiftool** (every capture date and GPS reading comes from it; the pipeline stops without it) | `brew install exiftool` | `winget install --id OliverBetz.ExifTool -e --scope user` (no admin needed), or the Windows installer from exiftool.org |
| **Python 3.10 or newer** (the scan, plan and copy stages use only the standard library) | `brew install python`, or the installer from python.org | the installer from python.org, which also installs the `py` launcher (not measured by this guide; the Windows test machine had Python 3.14 with `py`) |
| check | `exiftool -ver` and `python3 --version` | `exiftool -ver` and `py --version` |

Linux (untested): exiftool from your package manager (Debian/Ubuntu:
`libimage-exiftool-perl`) or from exiftool.org.

On Windows use `py` or `python`, not `python3`: `python3` can open the
Microsoft Store instead of running Python.

**Windows only: set UTF-8 once**, in your own terminal (not through the
agent, because an agent's `$env:` setting lasts for one command only):

    setx PYTHONUTF8 1

**Then close and reopen the terminal AND the agent session.** A session
started before the exiftool install or before `setx` does not see them, so
`doctor` would still say exiftool is MISSING (measured). After `setx`, Python
inside an agent command runs in UTF-8 mode (measured on Windows 11).

Why UTF-8 matters: without it, Python on Windows reads and writes text in the
Windows code page (cp1252 on the test machine). What was measured: a product
script that printed a warning sign (⚠️) into the agent's output stopped with
an error, and several of the product's test suites fail. Only `photo_run.py`
protects itself against the first; which pipeline stage breaks first without
the setting is **not measured**. `doctor` does **not** check this setting.

## 3. Ask the machine: `doctor`

Use the full path of the product folder, in quotes (the agent's shell may not
stay in it):

| macOS | Windows 11 |
|---|---|
| `python3 "<product folder>/scripts/photo_run.py" doctor` | `py "<product folder>\scripts\photo_run.py" doctor` |

It lists Python, exiftool, the repo `.venv`, the packages inside it, ffmpeg, a
real preview and the network, each OK or MISSING, and then an **install
plan**: the lines to run for THIS machine, in order, with the download size
for torch and the model weights. Exit 0 means everything needed to start is
there. Install what it names (step 4), then run it again.

Its summary line reads `ready to start: yes` or `no`, then
`vision stages: ready` or `not ready`. When it says **`ready to start: yes`**,
its last line is *"If you switched to manual mode for setup, you can switch
back to auto now."* (measured on a fresh unzip on macOS, and on Windows 11,
both with the vision stages not yet installed).

`photo_run.py prep` runs the start half of `doctor` before any real work: it
stops when exiftool is missing, and when no preview backend can make a still.

## 4. The vision stages: the `.venv`

The vision stages need a virtualenv inside the product folder, never the
system Python. Run the lines **exactly as `doctor` prints them**, one at a
time, in its order. They use full paths, so they work from any folder. With
the example product folders from step 1 they are:

| | macOS | Windows 11 (no NVIDIA card) |
|---|---|---|
| 1 | `python3 -m venv "/Users/<you>/photo-manager/.venv"` | `py -3 -m venv "C:\photo-manager\.venv"` |
| 2 | — | `& "C:\photo-manager\.venv\Scripts\python.exe" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu` |
| 3 | `"/Users/<you>/photo-manager/.venv/bin/python3" -m pip install -e "/Users/<you>/photo-manager[all]"` | `& "C:\photo-manager\.venv\Scripts\python.exe" -m pip install -e "C:\photo-manager[all]"` |

The Windows lines are the ones `doctor` printed on the Windows 11 test
machine; the macOS lines are the ones it builds for a Mac. The leading `& ` is
PowerShell's way to run a quoted program.

- **Line 2, CPU-only torch, comes FIRST on a Windows or Linux machine with no
  NVIDIA GPU.** Without it pip pulls a multi-gigabyte CUDA build you cannot
  use. On a Mac there is no line 2 (Apple Silicon runs on MPS). `doctor`
  decides this for you.
- Line 3 brings Pillow, `pillow-heif`, numpy, `imageio-ffmpeg`, torch,
  torchvision and open_clip.
- **ffmpeg:** an ffmpeg already on your PATH is used first; otherwise the one
  `imageio-ffmpeg` ships is used, so no separate ffmpeg install is needed.
  `doctor` says which (`the ffmpeg on PATH` or `the binary imageio-ffmpeg
  ships`; both seen in tests).

**The first vision run needs the network** to download the model weights
once; later runs load them from disk. The sizes `doctor` prints:

| Download | Size | Measured on disk (Mac) |
|---|---|---|
| torch (Mac / Windows CPU / with CUDA) | about 150 MB / about 200 MB / several GB | not measured |
| CLIP (scenes, clustering) | about 600 MB | 577 MB |
| the animal detector | about 170 MB | 167 MB |
| DINOv2 (animal identity) | about 330 MB | 330 MB, plus 4.5 MB of its code |

Where they are kept: [YOUR-DATA.md](YOUR-DATA.md#5-model-weights).

## 5. Start: the workspace and the first prompt

1. **Make a new, empty folder for this collection** (the workspace). One
   collection per workspace: a new raw folder is a new collection, and gets a
   new workspace. **Name:** any folder name your computer accepts. Spaces and
   Chinese characters work (measured on a Mac: workspaces named with each ran
   from scan to copy; Windows not measured). The name is only a label; the
   agent writes it into `collection.json` as `"collection"`.
2. **Start Claude Code IN that folder**, yourself, in your own terminal:

   | macOS (Terminal) | Windows 11 (PowerShell) |
   |---|---|
   | `cd ~/photo-workspaces/<collection name>` then `claude` | `cd "C:\photo-workspaces\<collection name>"` then `claude` |

   Why in the workspace: `photo-init` creates `Working Files` in the folder
   the agent was started in, and every later command finds
   `Working Files/collection.json` from the current folder. Started anywhere
   else, the agent writes its files there instead. An agent cannot move
   itself into another folder, so if an agent did the install for you, start
   a new one in the workspace now.

3. **Type this first prompt**, with your product folder's full path in both
   places:

   macOS:

   ```
   I want to sort a new photo collection. The product folder is /Users/<you>/photo-manager. Read /Users/<you>/photo-manager/photo-init/SKILL.md and follow it, one step at a time.
   ```

   Windows 11:

   ```
   I want to sort a new photo collection. The product folder is C:\photo-manager. Read C:\photo-manager\photo-init\SKILL.md and follow it, one step at a time.
   ```

4. **What happens next.** The agent reads `photo-init/SKILL.md`, runs
   `doctor`, and shows you what it found.
   - **If anything is MISSING** (for example the vision stages), its first
     question is about the install: one yes/no question per line of the
     install plan, with the download size. It runs only the lines you
     approve (measured on Windows 11: the first question was the CPU torch
     line).
   - **When `doctor` is all OK**, its first question is whose photos these
     are (measured on a Mac). Then it asks where the raw folder is and where
     the sorted folder should go, and quick-scans the raw folder
     (read-only). It creates `Working Files` in the workspace only after
     these questions.

Nothing is copied until you approve it. If a command is refused with
`[Code from External]`, the agent stops and tells you: go to step 0.

## 6. Update to a new zip

Your collection's data lives in the workspace and in the owner pack, never in
the product folder (measured: a full run wrote nothing into the product folder
except Python's own `__pycache__`). So an update replaces only the product
folder:

1. Unzip the new version as in step 1, but rename its inner folder to a
   **new** name, for example `~/photo-manager-<version>` or
   `C:\photo-manager-<version>`.
2. Run `doctor` from the new folder. It will say `.venv` MISSING: run its
   install plan (step 4). The model weights are already on disk and are not
   downloaded again.
3. Use the new folder's path in your first prompt and, if you use Path B, in
   your allow rules.
4. When the new version works, delete the old product folder.

Whether a workspace made by an older version always works with a newer one is
**not measured**; each release notes it if not.

## 7. Uninstall

1. Delete the product folder (this also removes its `.venv`).
2. Delete the model weights if nothing else uses them:
   [YOUR-DATA.md](YOUR-DATA.md#5-model-weights) lists the folders.
3. Optional, the tools:

   | macOS | Windows 11 |
   |---|---|
   | `brew uninstall exiftool` | `winget uninstall --id OliverBetz.ExifTool -e` (not measured) |
   | | remove the UTF-8 setting: `reg delete HKCU\Environment /v PYTHONUTF8 /f` (not measured), or delete it in *Edit environment variables for your account* |

4. Your photo data (workspaces, owner pack, sorted folders) is separate and
   stays until you delete it: [YOUR-DATA.md](YOUR-DATA.md#delete-it-all).
