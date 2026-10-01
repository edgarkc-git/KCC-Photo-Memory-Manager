---
name: photo-run
description: >
  The conductor for the photo-manager pipeline — drives one raw dump
  end-to-end through the per-dump INDEX: scan and cluster, onboarding, a
  vision pass per batch, the owner's short batch pages, the agent's own
  identification views, then render, check, freeze and a SHA-256 verified
  copy. Resumable across sessions: every stop says what to do and which
  command to run next. Trigger when the owner says "process folder X",
  "sort the next dump", "run the whole pipeline on 202401", or wants
  walk-away sorting of a raw dump.
---

# photo-run — pipeline conductor

> ⛔ **If a product command is refused as `[Code from External]` (agent
> note).** Run the product's commands normally; do NOT stop first to make the
> owner pick a path. Prefer the full-path lines `doctor` prints (on Windows the
> PowerShell tool resets its folder after every command, so a relative
> `scripts\...` line runs from the wrong place). Only if a command IS refused
> with `[Code from External]`: STOP, relay the refusal to the owner word for
> word, and point them to **"Step 0" in `docs/INSTALL.md`** (Path A or
> Path B). Never retry it, never run it another way, and never write
> permission rules yourself.

Version: 0.5 (G8: the index flow — no hand-typed `plans.json`, bare dump names,
every stop and exit code. Prior: 0.4 per-collection `collection.json`)

> Bucket names below are written with the ENGLISH defaults (`Screenshots`,
> `To-be-checked`, `others`, `AI-images`). They are not literals: every one
> resolves from the owner pack's language at run time.

## What it does

One command, `photo_run.py finish`, drives a dump to its copy and **stops at
every point where somebody has to look at something**. It holds no model and
writes nothing to the drive itself — it shells out to the stage scripts in the
right order. Each stop prints what happened, what to do, and the exact lines to
run next; after doing it you run the same `finish` command again. Because all
state lives on disk, every invocation is a fresh context that resumes where the
last one stopped.

The dump's plan is its **index** — `index.json` in the owner pack under
`photo-index/<dump>/`, the only truth, with `Index_pscan.md` beside it as a view
that is rewritten after every change and never edited. The copy plan
(`plans.json` and the plan files) is **written by `photo_index.py freeze`**; on
this flow nobody authors it by hand.

The judgment steps stay with the driving agent and the owner:

- **A. vision** — look at each batch's selected photos and write what they show.
- **B. the owner's pages** — a few short pages where the owner names their animals and the places they visit often.
- **C. the agent's views** — after the pages, recognition proposes a pet's name on other photos and the agent looks at each one.
- **D. folder structure** — trips, monthly parents for a named place, moves, splits, merges, with `photo_index.py group`.

## Where to run from

⭐ **Run every command from the collection's workspace folder** — the folder
that holds `Working Files/collection.json` (photo-init). From there
`photo_run.py` and `photo_index.py` take the **bare dump name** (`202401`) and
find the work dir themselves. From anywhere else — a work dir included —
a bare dump name is NOT found (`no collection.json under cwd`): pass the
full work dir path. A `cd` into a work dir is the usual way to lose it.
⛔ Never compose a work dir path by hand: the dump name is enough, and every
stop message prints any other command with its paths already filled in —
run those lines as printed. Where a command below shows `"<work dir>"`, type
the bare dump name from the workspace folder — that is the same thing.
`<repo>` below is the folder holding this SKILL's `scripts/` and `.venv/`;
`status` and every stop print the `.venv` lines with it filled in, so they
work from the workspace folder.
On Windows the interpreter is `<repo>\.venv\Scripts\python.exe` wherever these lines say `<repo>/.venv/bin/python3`.

## Configuration

| | |
|---|---|
| Conductor | `scripts/photo_run.py` (stdlib; `finish` runs the batch-page stage under the repo `.venv` by itself when the interpreter it was started with has no CLIP, because a place page checks its photos for documents) |
| The index | `scripts/photo_index.py` — `init`, `recut`, `relabel`, `apply-page`, `identify`, `group`, `dest`, `render`, `check`, `freeze`, `verify`, `unfreeze` |
| State | the index in the owner pack (`photo-index/<dump>/`); per-dump work files in `<workspace>/Working Files/<dump>/` |
| Destination root | per collection: `dest_root` in `collection.json` (photo-init) — the only place new folders are created. A merge into an existing folder is declared per folder with `photo_index.py dest` |
| Source drive | the collection's drive (see `collection.json`) — **read-only; copy-only always (D2)**; `prep` mount-checks and aborts with a hint if the volume isn't connected |
| Requires | exiftool, Python 3 stdlib, network reach to Nominatim (geocoding) — `photo_run.py doctor` checks every item with its install line; `prep` runs the same start checks and stops without exiftool. The vision stages need the repo `.venv`; a place page does too, and `finish` uses it without being told, or stops with exit 5 when there is none |
| Owner pack | bound by `collection.json` (`owner`, `memory_root`); `--profile <pack>` or `PHOTO_PROFILE` also work. No pack = no index, generic engine defaults |
| Pipeline visibility | `photo_run.py status <dump>` — batch states, the stage summary, and the next step. It names no destination: `dest_root` shows as `set` / `not set` and each plan row has no folder name. `photo_run.py status <dump> --paths` shows them; only `status` takes `--paths` |

## Before the first dump: Setup check — `doctor`, before anything else

```
python3 "<product folder>/scripts/photo_run.py" doctor          # Windows: py "<product folder>\scripts\photo_run.py" doctor
python3 "<product folder>/scripts/photo_run.py" doctor --json   # the same, for you to read
```

It lists every item this machine needs — Python, exiftool, the repo `.venv`,
the packages inside it (Pillow, pillow-heif, ffmpeg, numpy, torch +
torchvision, open_clip), a real preview, and the network — each **OK** or
**MISSING**, and for each MISSING item why it matters. Below the list comes
the **install plan**: the lines to run for THIS OS, each once, in order. Every
package comes from ONE line that installs the repo's own extras
(`-e "<repo>[all]"`); on Windows or Linux with no NVIDIA card a CPU-only torch
line runs before it. Exit
**0** when everything required to start is present, **1** when not; the
vision-only items are listed and do not change the exit.

1) **Show the owner the list** — every MISSING item, its reason, and its
   download size where one is given (torch, the model weights). Do not
   summarise it away.
2) **Ask yes/no per line of the install plan with AskUserQuestion** — one
   question per line, naming the items it covers and their download sizes.
   Recommend the start items first.
3) **Run only the plan lines the owner approved, in the plan's order**, exactly
   as `doctor` printed them (`--json`: `install_plan[].run`). Python packages go into the repo `.venv` with that `.venv`'s
   own interpreter — the printed line already says so; never a bare `pip`. An
   item with only a `note:` (an installer to download, another route) is the
   owner's to do; say so and wait.
4) ⛔ **Never `sudo` and never an admin prompt.** A line marked *needs admin* is
   the owner's to run in their own terminal (`! <line>` in Claude Code); say
   so and wait.
5) **Run `doctor` again and show the owner the new result.** Only then go on.
   ⛔ **On Windows, after installing exiftool** (or anything else that changes
   PATH): the owner closes and reopens the terminal AND this agent session
   (Claude Code) first. A session started before the install does not see
   the new PATH, so `doctor` in the same session still says MISSING.

`prep` runs the start half of the same checks and **stops** when exiftool is
missing — there is no second list to keep in step.

## Workflow — one dump, start to finish

1. **prep** — scan + cluster (read-only, no model), then build the index:
   ```
   python3 scripts/photo_run.py prep "/Volumes/EXAMPLE_DRIVE/<source-root>/202401"
   python3 scripts/photo_index.py init 202401
   ```
   The source path is the one place a path is typed: it is the owner's raw
   folder, recorded in `collection.json` under `raw_roots`. Sanity-check the
   printed counts (main + AAE = total seen; date range plausible).

   ⭐ **A FIRST dump — the owner's homes are not in the pack yet — is scanned
   WITHOUT clustering**, then onboarded, then clustered (D-I1):
   ```
   python3 scripts/photo_run.py prep "<source>" --no-cluster   # scan + census only
   # onboarding (photo-init): the page, then `apply --write-pack`
   python3 scripts/photo_run.py cluster 202401
   python3 scripts/photo_index.py init 202401
   ```
   Clustered before onboarding, every home day is named after the map's
   district instead of the owner's label, and its position is sent to the
   geocoder. If that already happened, and BEFORE any vision pass,
   `photo_index.py recut 202401` cuts the batches again with the pack; it
   refuses once anything per batch exists. Add `--dry-run` first to see how
   many batches and files would move — it puts every file back and writes
   nothing. A place label that arrives later
   needs no re-cut: `photo_index.py relabel 202401` (a dry run; `--go` writes).

   `prep` ends with a **device census** — the cameras, screen sizes and home
   areas this dump actually contains, checked against the owner's pack. Three
   lines are worth stopping for:
   - `⚠️ CHECKPOINT — pack does not list: <make>` — every photo from that
     camera will be described as `shared` (not shot on this device) until the
     owner confirms it belongs to them. Add it to `own_camera_makes`.
   - screen-size candidates — only needed if this owner's screenshots are
     being missed. **Pick by hand**; a size that also appears on videos is
     flagged, and accepting one would move ordinary videos into the
     screenshot bucket. Android screenshots are caught by filename regardless.
   - `home areas (-> home_locations)` — coordinates that behave like somewhere
     the owner lives (many separate days, and photographs after dark), each
     with a map link. **Confirm the rows not marked ✓ with the owner and ask
     for the city word** — a residence is never named as a place or a folder,
     and until this is answered that rule has nothing to enforce. A row the
     pack already holds is marked `✓ already listed` and needs no second
     answer; answering one twice is how a duplicate row gets written. The
     census shows evidence and never a name: no network, no reverse-geocoding.
     **Nothing proposed is ordinary** on a first dump — then ask the owner to
     name their home areas at city level in the same question rather than
     waiting for a later run.

   Nothing is written by the census. Run it again any time with the path
   `prep` printed: `python3 scripts/photo_census.py "<work dir>"`.

2. **The VISUAL pass — every batch, in date order, BEFORE `finish`.** The
   commands need the repo `.venv` (torch + open_clip + the models), so they are
   run directly rather than through `photo_run.py`. `photo_run.py status
   202401` prints them with the work dir filled in:
   ```
   <repo>/.venv/bin/python3 <repo>/scripts/photo_embed.py    "<work dir>"                  # VS-1  CLIP image index
   <repo>/.venv/bin/python3 <repo>/scripts/photo_embed.py    "<work dir>" --scene-labels   # VS-2  scene axis, ONCE per dump
   <repo>/.venv/bin/python3 <repo>/scripts/photo_identity.py "<work dir>"                  # VS-3b identity index
   <repo>/.venv/bin/python3 <repo>/scripts/photo_see.py      "<work dir>" --batch 1        # VS-2  SELECTS -> see-report.json + samples/
   # YOU look at samples/ and write {selected[].path: label} into decisions.json (photo-see/SKILL.md)
   <repo>/.venv/bin/python3 <repo>/scripts/photo_see.py      "<work dir>" --batch 1 \
       --apply decisions.json --memorize                                   # VS-2  RECORDS -> see-labels.json
   ```
   ⛔ **`photo_see.py` alone selects and labels NOTHING.** Without `--apply`
   it writes `see-report.json` and no `see-labels.json`, exits 0, and `render`
   then refuses the batch as unseen. The look in between is yours, and
   `--apply` is what records it (`--memorize` needs an owner pack).
   ⛔ **A decision never names a pet.** `--apply` refuses a `subject_id` in
   `decisions.json`; write `subject_kind`. `--memorize` records what it saw as
   draft observations — no exemplar, no name. Names come only from the owner's
   pages (step 3) and from the agent's views (step 4).
   ⛔ **`--scene-labels` is a SEPARATE run of `photo_embed.py`, not a variant
   of the line above it.** It does not touch the image index: it runs CLIP's
   text tower once over the owner's zero-shot label set and writes
   `embed/scene-labels.npy` + `.json`. Because it is once-per-dump rather than
   once-per-batch it is the step most easily skipped — and skipping it fails
   SILENTLY. `photo_see` still runs, still writes a valid `see-report.json`
   and still selects files; it just clip-matches **nothing**, so an axis of
   classification is off for the whole dump and every folder name downstream
   is poorer for it at exit 0. Both `photo_see` and `photo_run.py status` say
   so on stdout when `embed/scene-labels.json` is absent — if you see
   `scene axis is OFF`, this is the line you missed.
   ⚠️ **`photo_identity` is optional by design and skipping it is not free.**
   Without it every subject verdict is CLIP, not identity: the agent's views
   (step 4) propose nothing at all, and an exemplar promoted from a frame
   holding two animals carries both of them into one subject's memory (D-24).
   ⛔ **Order matters and it is enforced.** `[who]` and `[what]` reach a folder
   name only from this stage's `see-labels.json`. `photo_index.py render`
   refuses a batch with no see output and names which ones; `--no-vision`
   gives up WHO/WHAT deliberately (a metadata-only dump: screenshots, no-date
   files, no subjects). It is not a way past a stage that simply has not been
   run.
   ⭐ **A batch with nothing to look at** (its only files were held out as
   screenshots or documents, or `photo_see` exited 3 for it) is rendered with
   `photo_index.py render "<work dir>" --no-vision`. It covers only the
   batches with no see output; every seen batch keeps its labels. ⛔ Never
   write an empty `{}` into `decisions.json` and `--apply` it to get past the
   refusal: that records a look that never happened.

   ⭐ **There is no classify step on this flow.** `photo_sample.py` and
   `photo_classify_set.py` (`--type`, `--where`) are not run: the index names folders
   from the place refs, the see labels and `[what]`, and `finish --go` moves
   each batch to `approved` itself (a dry run approves nothing and writes
   nothing — it previews each copy). Measured on a real 291-file dump reset to
   `pending` with no classify field: init, the vision pass, render, check,
   freeze and a `finish` dry run all passed. ⛔ Classify fields written before
   a `recut` make `recut` refuse.

3. **`finish --go` — run it, do what the stop says, run it again.**
   ```
   python3 scripts/photo_run.py finish 202401 --go     # stops at each question, then copies
   ```
   ⛔ **Start with `--go`, not a dry run.** On an indexed dump the pages and the
   views run only with `--go`, and a dry run copies only from a freeze — so a
   dry run before the first freeze exits **4** and asks for render, check and
   freeze, which would lock the names before the pages add any. A dry run is
   useful after the freeze, to preview the copy.
   Tell the owner before the first stop: *a few short pages, a few minutes
   each; the copy waits for them.* With `--go` the stops come in this order,
   and each one exits before a single file is copied:

   **a. A batch page (exit 3).** `finish` runs `photo_memory.py review
   "<work dir>" --next-page`, which writes ONE page, `P-B<NN>.md`, for the next
   batch in date order that has something to ask: an animal still to be matched
   (for the first `memory.batch_pages` batches that show one, default 4), or a
   place the owner visits often, first seen in that batch, with no name yet
   (always). `--next-page` exits **11** when it wrote a page, **12** when one
   still waits for its answer, **0** when none is due; `finish` turns 11 and 12
   into its own exit 3 and prints the page's name and the lines to run.
   - Make the web page for the owner with the line the stop prints:
     `<repo>/.venv/bin/python3 <repo>/scripts/photo_review_page.py render "<work dir>/P-B<NN>.md" --workdir "<work dir>" --pack "<pack>"`.
     A page with only a place question shows none of the animal parts.
   - ⛔ **Send the owner to the page, and wait for their answer.** Never offer
     your own reading of the photos for them to agree to ("my reading: Name-A
     in 1, 2, 4 — is that right?"). The owner picks the frames (SNS-1); a yes
     to your guess is your guess, and it trains the pack. If the page cannot
     hold what the owner says, write their answer in their own words.
   - The owner picks each animal's photos and gives a name from their own list
     with `same` (`name: Name-A same`); a new name for an animal not on the list;
     `skip:` for one that is not theirs. A place is answered with its name, plus
     `live` or `visit` if it is a home.
   - Their answer lines go into the page with
     `python3 scripts/photo_review_page.py apply "<work dir>/P-B<NN>.md" --answer <answer file>`
     (the lines the page's Confirm sends, or the ones it lets them copy). An
     answer written as text starts with the line `page: P-B<NN>`; the web
     page's copy lines already carry it, and `apply` refuses a batch page's
     answer without it. One row per animal: copy a row for each more animal.
     Two animals in one photo take two rows with the same photo number;
     `pick: 3.1` is refused (a `<photo>.<animal>` number belongs on `skip:` only).
     To change an answer before its confirm, see step f.
   - Then the two lines the stop printed:
     `photo_memory.py confirm "<work dir>" --page P-B<NN> --go` (the names into
     the pack) and `photo_index.py apply-page 202401 P-B<NN> --go` (the page into
     the index; a named place's folders switch to it, and a monthly parent is
     PROPOSED — run `photo_index.py group make-fsl-month` yourself if it fits).
   - Batches already cut are not cut again. Skipped batches are written into the
     index log. Batches after the pet pages get no animal question; a place
     first seen there still gets its page.

   **b. The agent's views (exit 3).** When no page is due, `finish` runs
   `photo_index.py identify 202401 --new-only`. Recognition proposes a
   confirmed pet's name on photos that were VIEWED in step 2 and writes
   `identify-views.md`; `identify` exits **13** and `finish` turns it into exit
   3. Open EACH photo on it and look at its `crop:` first — the animal the
   name is proposed for (`animal 2 of 2` says which one); the sample is context:
   - `agree` only when you can see it IS that animal;
   - `no` for a stranger — recognition scores look-alike street cats inside a
     pet's own range, so the view is the only guard;
   - `unsure` when you cannot tell.
   The views file IS the answer form. Write the verdict at the end of each row:
   replace `______` after `verdict:` with `agree`, `no` or `unsure`, and change
   nothing else on the row. Any other word refuses the whole file. A row looks
   like:
   ``- `I-0100` · batch 35 · `classify/batch-35/samples/<photo>.jpg` · `subj-0001` Name-A · identity 0.6768 lead 0.2416 · animal 1 of 1 · crop: `review-crops/<ref>_d0.jpg` · verdict: agree``
   Apply it with the lines the views file's header prints — they carry the
   full work dir, so they work from any folder. ⛔ You edit
   `identify-views.md` inside the work dir; a bare dump name (`202401`) typed
   from there is NOT found (`no collection.json under cwd`, HIL01). Check it
   first with `photo_index.py identify "<work dir>" --answers
   "<work dir>/identify-views.md"` (a dry run: it prints the counts). Then
   `photo_index.py identify "<work dir>" --answers "<work dir>/identify-views.md"
   --go`, and go on to step d. ⛔ **If the index is frozen** (always, after a
   name corrected after the copy), `--go` refuses with `Lift it first`. The
   stop, the views file's header and `identify --new-only` then print an
   `unfreeze "<work dir>" --reason "..."` line first; run the stop's route:
   ```
   python3 scripts/photo_index.py unfreeze "<work dir>" --reason "..."   # (the freeze locks the names)
   python3 scripts/photo_index.py identify "<work dir>" --answers "<work dir>/identify-views.md" --go
   python3 scripts/photo_index.py render "<work dir>"
   python3 scripts/photo_index.py check "<work dir>"
   python3 scripts/photo_index.py freeze "<work dir>"
   ```
   then re-run `finish --go`. A row left blank names nothing and is recorded
   nowhere; `finish` does not ask it again and says on every run how many photos
   were left without a verdict — `photo_index.py identify 202401` shows them
   again. A views file whose verdicts are not applied yet is never rewritten.

   **c. The folder structure (no stop — your judgment).** Look at
   `Index_pscan.md` and shape the folders with a reason for every change:
   ```
   python3 scripts/photo_index.py group make-trip 202401 F008 F009 --where "<place>" --reason "..."
   python3 scripts/photo_index.py group make-fsl-month 202401 fsl-0003 2024-12 --reason "..."
   python3 scripts/photo_index.py group move 202401 F021 --to F023 --dates 2024-12-11 --reason "..."
   python3 scripts/photo_index.py group split 202401 F011 --at 2024-10-30 --reason "..."
   python3 scripts/photo_index.py group merge 202401 F034 --into F033 --reason "..."
   python3 scripts/photo_index.py group set-what 202401 F044 "<text>" --reason "..."
   python3 scripts/photo_index.py dest 202401 F003 merge "<existing folder>" --ref "<its work dir>" --reason "..."
   ```
   Every `group` action takes `--dry-run`: it prints what the change would do
   and writes nothing — show it to the owner when they asked for the change,
   then run it without the flag and `render --dry-run` for the names.
   Day trips and evenings back home stay one day folder. In-transit shots
   follow the destination. An existing hand-named folder wins over a new one
   (merge-don't-duplicate); `dest ... new` undoes a merge.

   **d. render → check → freeze.**
   ```
   python3 scripts/photo_index.py render 202401    # every route settled, every folder name rendered (dedupe too)
   python3 scripts/photo_index.py check 202401     # exit 0 passes, 1 fails and lists why
   python3 scripts/photo_index.py freeze 202401    # locks the names, exports plans.json + plan files, hashes it all
   python3 scripts/photo_index.py freeze 202401 --reason "..."   # optional: why, recorded in the index log (say it on a re-lock after a correction)
   ```
   `render` names each folder from the date, the place refs, the CONFIRMED
   subjects at `viewed-image:` and `[what]`; a folder may have no `[who]`, and
   that is a legal name. `[who]` and `[what]` are read only from photos taken
   at that folder's own place: a photo taken at a home that is not this
   folder's place does not name it, and a photo with no GPS still counts. No
   photo moves folder for this. `check` fails a name the evidence does not back — a
   pet's name with no copied file showing that confirmed subject at
   `viewed-image:`, or an agent's name with no `agree` view on record. Fix it
   through the index and run the three again.

   **e. The copy.** Run `finish 202401 --go` again. It copies **only from a
   freeze that still holds** — the same index, the same exported plan files,
   the same owner pack — and verifies every copy's SHA-256 against the freeze.
   Anything changed since `freeze` makes it exit **4** with nothing copied: run
   render, check and freeze again. The no-date plan goes by each file's own
   date: a no-date VIDEO → `YYYY00_To-be-checked` (its own modify year); a no-date STILL → one `_To-be-checked/<import>` folder that claims no year (Card 5); a manifest scanned before Card 5 still uses the dump's `YYYYMM00_To-be-checked`; extension-mislabeled files
   land under their **corrected filename**, and files whose real format cannot
   be determined go to `YYYYMM00_others`. `finish` then runs the OA-4 backstop
   (`photo_rename_mismatches.py` over this dump's destination folders: .AAE
   skipped, collisions get `_dupN`, never overwrites, sources untouched).

   **f. The end-of-dump round (SNS-4), after the copy.** With `--go`, `finish`
   ends with `photo_memory.py review "<work dir>" --final` — the guaranteed
   end-of-dump checkpoint. It fires whether or not the round floor was reached
   and is not charged against the per-dump budget, so a subject that only became
   frequent late is not stranded until the next dump. The page it writes is
   `memory-review_C<N>.md` in the work dir — `<N>` is the checkpoint number,
   and every checkpoint page is named that way. Read it, then write the answers
   into its rows — by hand, or from an answer file with the same route a batch
   page takes:
   `python3 scripts/photo_review_page.py apply "<work dir>/memory-review_C<N>.md" --answer <answer file> --dry-run`,
   then again without `--dry-run`.
   **To change or take back an answer before `confirm --go`**, answer the page
   again and re-run `apply`: the new answer REPLACES every earlier `pick:` row
   of that question, its `skip:` row and every `recheck:` value, and `apply`
   (dry run too) prints each earlier row it replaces. Editing the rows back to
   `______` by hand works as well. Then run the `confirm` dry run again: it must say
   `0 change(s) would be written`, or list only what the owner means now. After
   `--go` the page is no longer the way back — see Correcting a name
   (`--detach`).
   Then answer it with
   `photo_memory.py confirm "<work dir>" --checkpoint N` (a dry run) and
   `--go`. **Read the confirm's per-photo lines before `--go`** — each picked
   photo with the name it holds and the name it takes. The dry run prints
   `would record N owner-picked frame(s) into see-labels.json — the name each one's folder takes at render, per photo (its name now -> after):`
   and `--go` prints `(its name before -> now)`, then one line per photo:

   | line | means |
   |---|---|
   | `20241021_140730.jpg: Birk -> Lotus` | the photo named Birk; it will name Lotus — Birk is displaced. Stop here if the owner never meant that |
   | `— -> Lotus` | the photo named nothing before |
   | `subj-0017 -> Lotus` | it held a draft |
   | `Lotus -> Lotus (no change)` | the same subject already |
   | `Birk -> Birk + Lotus` | two animals in the photo; both are named |

   A refused row prints no line. The photo is always the SOURCE file (the
   `.mp4`, never its `.png` sample). **After the confirm, run
   `photo_index.py render <dump> --dry-run`**: one answer can move more folder
   names than the photos it lists — a pet can drop out of a folder whose only
   photo of it was re-picked, and a tie between two pets can swap their order.
   If a name typed on a page is one letter from a name the pack already holds,
   or the same but for letter case or width, `confirm` SAYS so on both the dry
   run and `--go` and still accepts it — two animals may have close names.
   ⚠️ Names are compared whole, after normalising case and width; a name of
   fewer than four characters (most CJK names) is only flagged when it matches
   that way exactly, because one character in two is half the name.
   **Re-running `finish --go` does not ask a second guaranteed round** — one per
   dump, not one per run. ⚠️ It CAN still put a new ordinary page to the owner
   (`memory-review_C<N+1>.md`) when enough new subjects appeared and the budget
   allows — even while an earlier page is unanswered — and it does not stop
   the copy for it. The `finish` dry run says beforehand whether `--go` would
   stop (a batch page, the agent's views, a naming round) and whether it would
   end with a new page; it asks each stage with `--preview`, which writes
   nothing. A dump with no owner pack skips it and says so; it never changes
   what `finish` exits with.

   **A checkpoint page left unconfirmed** waits for nothing and teaches
   nothing: render, check, freeze and the copy go on. Its subjects count as
   asked, and a later `finish --go` may write the next page
   (`memory-review_C<N+1>.md`) with other subjects, up to
   `memory.sns_rounds_per_dump` pages. ⛔ **Confirm one page before answering
   the next**: any `confirm --go` changes the pack, and every other open page
   is then refused whole (`NOTHING in the file was applied — not one row`).
   To get that page's questions back, MOVE the refused page out of the work
   dir (never rename it inside), then run `review` (a checkpoint page) or
   `finish --go` (a batch page): the same questions come back on a new page,
   even when the round budget is spent. A plain `review` with the refused page
   still in place asks nothing. A
   late confirm moves names like any other: `render --dry-run`, then unfreeze,
   render, check and freeze.

   `--skip-memory` goes past the pages AND the agent's views in one run. The
   folders then carry no pet names, which is a legal outcome, not a failure.

4. **done** — `photo_run.py status 202401` shows every batch `done` and points
   the owner at `plan/execution-log_PN.md` for any flags. The owner spot-checks
   in Finder and, if something's wrong, **re-processes** the folder (below).

`prep` and `finish` can be split across sessions freely — `status` always shows
what's left.

## Exit codes you will meet

Read the exit code of the command itself. ⛔ Never pipe a stage into `tail`
or `head` and then read `$?`: that is the exit code of `tail` (0), not of the
stage. `${PIPESTATUS[0]}` is no fix: it is bash-only and empty in zsh, the
macOS shell. Write the output to a file instead:
`<command> > run.log 2>&1; echo "EXIT=$?"; tail -40 run.log`.

| command | exit | means | do |
|---|---|---|---|
| `photo_run.py finish` / `plan` | 0 | done (or a dry run finished) | read the status |
| | 1 | a plan was flagged or failed during the copy | read `plan/execution-log_*.md` |
| | 3 | a question was just put: a batch page, or `identify-views.md` | answer it (step 3a / 3b), then re-run |
| | 4 | the dump has an index and its freeze is missing or no longer holds | `render`, `check`, `freeze`, then re-run |
| | 5 | a naming stage did not finish (a batch page, the pre-plan round, or identify); nothing was copied, and the stop prints the line to run it again | run that line, fix what it says (for a place page: the repo `.venv`), then re-run |
| `photo_memory.py review --next-page` | 11 | a page was written | answer it |
| | 12 | a page still waits for its confirm and apply-page | finish that page first |
| | 0 | no page is due | go on |
| `photo_memory.py review` (a pet page, or `--next-page`) | 1 | `was not written`: a photo holds an animal the identity index found, but no crop of it could be made with this python (F22; a HEIC needs pillow-heif). The page is never shown with the whole photo instead | run the same step with the repo `.venv` python; `finish` does that by itself when the `.venv` exists |
| `photo_index.py identify` | 13 | views are wanted in `identify-views.md` | view each photo, write verdicts, `--answers ... --go` |
| `photo_index.py identify --answers --go` | 1 | `Lift it first`: the index is frozen, nothing written | `unfreeze --reason "..."`, `--answers ... --go` again, then `render`, `check`, `freeze` (step 3b) |
| `photo_index.py check` | 1 | a folder name or a route fails; each problem is listed | fix through the index, then `render` and `check` again |
| `photo_index.py freeze` | 1 | refused, nothing frozen: the check fails, a target changed, or a folder copied by an earlier run was since split or merged (a folder only RENAMED after its copy freezes, and lists the renames) | fix what it names; a split or merge after the copy: stop and ask the owner (see Re-processing a folder) |
| `photo_execute.py` (inside `finish`) | non-zero | a new file would go into a folder still to rename on the drive; nothing written | rename the listed folder by hand, then re-run `finish` |
| `photo_index.py verify` | 4 | the freeze does not hold | `render`, `check`, `freeze` |
| `photo_index.py verify --copied` | 6 | every copied file matches its freeze, but the owner pack changed since (a later dump's onboarding, an end-of-dump page). The drive is fine; folder names may differ on a re-lock | re-lock when convenient: `render`, `check`, `freeze`, then `verify --copied` again. Never read 6 as a failed copy |
| `photo_embed.py` / `photo_identity.py` | 3 | some files got NO preview and so no vector; the index is saved, and stderr names each cause with its count (`no_ffmpeg …`, `no_heif_decoder …`, `decode_failed`, …) | fix the named cause — most name the tool to install — and run the same line again; only the failed files are retried. ⛔ Do not go on to `photo_see` past an unexplained count: a file with no vector is invisible to every later stage. This 3 is NOT `finish`'s 3 |
| `photo_see.py` / `photo_sample.py --batch` | 3 | NOT ONE selected file got a viewable sample; the report is written and stderr names each cause | do NOT label the batch — there is nothing to look at. Fix the cause and re-run (`photo_see --force`). Some samples failed = exit 0, causes in the report |
| `photo_embed.py` / `photo_identity.py` | 1 | refused: this index, or the owner pack, was built from the OTHER preview backend (`sips` vs `pillow`) | read the message and tell the owner: rebuild the index with `--force`, or run with `PHOTO_PREVIEW_BACKEND=<the backend it names>`; a pack has no rebuild yet, so for a pack the switch is the only way |

⛔ A pet name the evidence does not back never reaches the copy on this flow:
`check` fails (exit 1), `freeze` refuses, and `finish --go` exits 4 with
nothing copied.

## Rules to keep

- ⛔ **Only the owner's answers train.** An agent's `agree` names the photo's
  folder and teaches the pack nothing — no exemplar, no record moved. The pages
  and the end-of-dump round are the only teachers.
- ⛔ **Only identity-space proposals are offered.** A `clip` accept, a `gray`
  and a `question` are listed in the views file as not offered, with their
  space, and never get a verdict row.
- ⛔ **`photo_see --apply` refuses a decision naming a `subject_id`.** Name a
  pet through `photo_index.py identify`, where the view is recorded.
- The end-of-dump round still asks as it always has; an agent's verdict never
  appears on a tile.
- ⚠️ **Honest limits.** `check` proves a thumbnail existed and a verdict was
  recorded, not that a model looked — the same trust `viewed-image:` has always
  carried. A frame that already names a confirmed subject is skipped whole, so a
  second animal on it is never proposed. A declared pet the owner never picked on
  a page has no exemplar and is never proposed. A views file written and never
  opened counts as shown: its rows are counted as left without a verdict.

## Correcting a name

**Before the freeze**, a name change re-renders: run `render`, `check` and
`freeze` again. **After the freeze the names are locked** (D-I16): lift it with
`photo_index.py unfreeze 202401 --reason "..."`, then render, check, freeze. A
folder already copied is never renamed by this engine.

**A name corrected after the copy** (the names are often first seen then) is
locked the same way — unfreeze, render, check, `freeze --reason "..."` — and
nothing is copied again. When a folder already copied now renders under a new
name, the freeze still succeeds and prints the renames:

```
N folder(s) already copied carry an old name. Rename each one by hand on the drive, in this order — the engine never renames a folder:
  "<old>" -> "<new>"
The list is kept in plan/folder-renames.md.
```

The owner renames each folder by hand on the drive, **in the listed order**
(`plan/folder-renames.md` holds the same list under `# Folders to rename by
hand`, one `- "<old>" -> "<new>"` line each, relative to `dest_root`). Until a
rename is done:
- `photo_index.py verify 202401 --copied` still exits 0 and lists what is left:
  `⚠️ N folder rename(s) still to do on the drive (plan/folder-renames.md):`;
- `finish` ends with `===== N folder(s) to rename by hand on the drive =====`
  and the same list;
- a copy that would put a NEW file into a folder still to rename is refused by
  `photo_execute` (non-zero exit, dry run and `--go`, nothing written):
  `a file to copy goes into a folder that is still to be renamed on the drive — rename it by hand first, then copy again (the engine never renames a folder). Nothing written:`.
  Rename the folder, then run `finish --go` again.

A rename is known to be done when the old folder is gone from the drive.
⛔ **A split or a merge after the copy cannot be locked**: the freeze exits 1
with `N file(s) were copied by an earlier run into a folder that has since been split or merged (or copied to a place this freeze does not name). …`
and writes nothing, the engine never renames or moves anything on the drive.
Stop and put it to the owner: the documented way on is re-processing the dump
(below), which removes that dump's copied folders.
To see which names a change would move before lifting anything, run
`photo_index.py render 202401 --dry-run`: it prints each folder name that
would change, with a `why:` line (files moved, place, `[who]`, `[what]`, a
`group` command, or — when none of those moved — the naming rule itself), and
writes nothing, even while the index is frozen. Run it after
every `confirm`, `rename` or `--detach` too, not only before an unfreeze.
Re-lock with `photo_index.py freeze 202401 --reason "..."` so the index log
says why the names changed.
If the dump has a batch with no see output (rendered with `--no-vision`), every
`render` of the re-lock, `--dry-run` included, needs `--no-vision` again.

**After a correction, `finish --go` may stop again for the agent's views (exit
3)** — a confirm changes which photos recognition proposes. This is step 3b,
and the views file IS the answer form: replace `______` after `verdict:` at the
end of each row with `agree`, `no` or `unsure` (or leave it blank), and change
nothing else. The index is frozen at this point, so record them with the
frozen route in step 3b (`unfreeze --reason "..."`, `identify --answers ... --go`,
render, check, freeze). An `agree` teaches the pack nothing, but it can add a
pet's name to a folder: run `photo_index.py render 202401 --dry-run` before the
freeze and read what changes.

**A confirmed NAME that is wrong — a typo, or two names swapped — is corrected
with one command**, no checkpoint page needed (ADR 0004):

```
python3 scripts/photo_memory.py rename "<work dir>" subj-0001=Name-B subj-0002=Name-A         # dry run
python3 scripts/photo_memory.py rename "<work dir>" subj-0001=Name-B subj-0002=Name-A --go    # write
```

Every pair is judged against the names as they will stand afterwards, so a swap
is one command. It renames the RECORD only: folders already on the drive keep
their names and still resolve through the rename ledger.

**If the owner confirmed a name onto the wrong animal, it is repairable.** A
confirmation memorizes the frame picked as that subject's evidence, so a frame
holding two animals — or the wrong one — teaches the registry something false,
and it will go on matching on it. `photo_subjects.py` is the repair tool:

```
python3 scripts/photo_subjects.py review                     # what is held: each absorbed draft (id, photos, crop), each exemplar (short vec_ref, photo)
python3 scripts/photo_subjects.py review --json review.json  # the same, with each exemplar's full vec_ref
python3 scripts/photo_subjects.py review --detach <draft-id> --reason "..."        # dry run: shows the reason it will record
python3 scripts/photo_subjects.py review --detach <draft-id> --reason "..." --go   # write (add --into <subject-id> to move it to another pet)
python3 scripts/photo_subjects.py review --prune --drop <vec_ref>       # dry run
python3 scripts/photo_subjects.py review --prune --drop <vec_ref> --go  # write
python3 scripts/photo_subjects.py review --unconfirm <subject-id> --go
```

**A photo picked into the wrong pet on a checkpoint (`same`) comes out with
`--detach`, not `--drop`.** `--drop` removes the evidence but the photo keeps
that pet's id, so its folder keeps the pet's name. In `review`, find the draft
listed under the pet by its photo name or crop, and detach that draft id. The
photos it picked get back what they said before: the agent's `identify` agree,
else the id the confirm replaced, else the draft itself; with `--into` they
name that pet. Without `--into` the draft is asked about again at the next
checkpoint; with `--into` it stays joined, now to that pet, and is not asked
again. Either way the exemplars and looks the join carried leave the first
pet, and that pet keeps its name. Give `--reason` with the owner's words: the
`detached` audit row records it, and a detach without one says so and records
none. Then render (`--dry-run` first), check and freeze again.

`--drop` takes the 12-character ref `review` prints beside the photo (any
unique first 8 characters or more of a vec_ref); a prefix that matches two
exemplars is refused with both named, never guessed.

`--drop` removes one piece of evidence and keeps the subject; `--unconfirm`
withdraws the whole answer, turning the subject back into a draft that gets
asked again — its evidence is frozen, not deleted, so re-confirming stays cheap.
Both are a **dry run until `--go`**. Run these from the workspace folder and the
owner pack is resolved for you; from anywhere else, name a work dir or pass
`--profile <pack>`.

## A dump with NO index

A dump with no owner pack bound, or one that never ran `photo_index.py init`,
takes the older route:

- **classify** each batch: `photo_sample.py` for samples, then
  `photo_classify_set.py "<work dir>" --batch N --type <type> --where "<place>"`.
- **author `plans.json`** by hand (schema in `photo_plan.py --help`; policy in
  `photo-plan/SKILL.md`).
- **`finish --go` starts with the naming round (U-2):** it runs
  `photo_memory.py review "<work dir>" --pre-plan`, and if it asked something it
  **stops before copying** (exit 3). Answer the page, run the `confirm` line it
  prints — `photo_memory.py confirm "<work dir>" --checkpoint N --go`, with the
  page's number — then re-run. `--skip-memory` goes past it.
- A pet name typed into `plans.json` that no viewed, confirmed file backs is
  refused when the plan renders, and `finish` exits **1**.
- A first dry run advances fresh batches `classified -> approved` and copies
  nothing; `finish` is idempotent (`--force` re-renders a plan whose batches are
  all `done`).

## The "Others" rule (fully-automated policy)

Route to Others/Misc **only when no rule can be applied**, i.e. no usable date
or no usable GPS grouping — **not** when the type label is merely uncertain. A
batch with solid GPS still gets its real folder even if the type is fuzzy: the
test is "can't find the rule to apply". Buckets (D13, with the to-be-checked
mod; YYYYMM = the raw dump's YYYYMM):

- No EXIF date -> a no-date VIDEO → `YYYY00_To-be-checked` (its own modify year); a no-date STILL → one `_To-be-checked/<import>` folder that claims no year (Card 5); a manifest scanned before Card 5 still uses the dump's `YYYYMM00_To-be-checked`. No where (dated, can't be classified) ->
  `YYYYMM00_To-be-checked`. Both are auto-planned and copied; the owner
  triages later.
- **G-2, a screen size spotted mid-run**: a no-camera still at a size some
  other file's *name* proves is a screen, which the owner's `screen_dims`
  has not confirmed, also goes to the monthly to-be-checked bucket rather
  than the trip folder. The proposal is printed after `plan`/`finish` and
  queued in `plan/screen-size-proposals.json` — the run is never blocked to ask.
  To add one, re-make the onboarding sheet for that work dir and answer its
  `screen:` line (photo-init, "A NEW screen size"); the banner and the
  schedule's morning list name that command, and stop naming a size once the
  owner has added or declined it.
- `YYYYMM00_AI-images` is strictly for **confirmed** AI-generated images —
  the EXIF `no_exif` rule alone can't tell AI output from an EXIF-stripped
  forwarded photo, so unattended runs never route there; requires a manual
  `photo_plan.py --no-date --ai-confirmed` after visual verification.
  `YYYYMM_Misc` is retired as an auto-route.
- Has a date but the file's real format can't be determined (exiftool
  `FileType` unknown) -> `YYYYMM00_others` (file's own month, human-attention
  placeholder). Nothing rule-classifiable (screenshots, pets, clear trips)
  ever lands in any of these buckets.

## Re-processing a folder (the replacement for the approval gate)

Because everything is copy-only, a bad run is fully reversible:

1. Delete the destination folders that plan created (listed in its
   `plan/execution-log_PN.md`). Merged/shared folders (a shared
   `20240100_Screenshots`, hand-named trips): remove **only this dump's** files — the execute state file
   (`plan/execute-state_PN.json`) records every path this dump copied and its
   destination, so another dump's files in the same shared folder are untouched.
2. Delete `plan/execute-state_PN.json` and reset the affected batches
   (`photo_classify_set.py "<work dir>" --batch N --status classified`).
3. On an indexed dump: `photo_index.py unfreeze 202401 --reason "..."`, fix it
   through the index (`group`, `dest`, the see labels), then `render`, `check`,
   `freeze` and `finish 202401 --go`. On a dump with no index: fix labels or
   `plans.json`, then `finish --go`.

Sources are never touched at any point, so re-processing is safe to repeat.

## Safety properties (unchanged from the stage scripts)

- Copy-only: no move/delete/rename against any source path exists in any script.
- `--go` required to write; dry-run is the default at every level.
- Allowlist: execute refuses any destination outside the destination root or a
  folder's declared merge target.
- Never-overwrite: same-name different-content files are flagged, both sides
  left untouched (this caught 559 low-res/full-res collisions in one measured dump).
- Resumable + idempotent: re-runs skip already-verified copies.

## Portability (Phase 6)

The conductor and every mechanical stage are Python 3 stdlib and run anywhere
exiftool + the drive are reachable. The one exception inside `finish` is a
place page's document check, which needs the repo `.venv` (see exit 5). The
vision pass needs the repo `.venv` (its previews come from Pillow + pillow-heif
and ffmpeg, installed there — macOS `sips`/`qlmanage` only with
`PHOTO_PREVIEW_BACKEND=sips`). Cloud scheduling can't be used
when the collection lives on an external drive that mounts on one machine only;
unattended runs must then be a **local** `launchd`/cron firing `claude -p`, and
any job treating a non-zero `finish` as failure will see exit 3 once per page.
