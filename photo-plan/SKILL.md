# SKILL — photo-plan (Stage 4)

Version: 0.5 (R13: the folder-name grammar is written out here — it was a
pointer at a document the operator was not given, and the repo's copy of that
document is four versions stale. 0.4: monthly buckets renamed `YYYYMM00_`;
D13 to-be-checked mod: no-date → by each file's own date (Card 5), no-where → `YYYYMM00_To-be-checked`; AI-images
only via `--ai-confirmed`)

Turn batches into **copy plans** (`plan_PN.md` + `plan_PN-files.csv`, written
in the owner pack's language) — what `photo-execute` copies from.
**This stage is 100% read-only on the drive** (hashing only reads).

⭐ **On a dump with an index (`photo_index.py init` ran) nobody writes
`plans.json`.** `photo_index.py render` settles every file's route with this
stage's own code and renders every folder name; `check` refuses what the
grammar or the evidence does not allow; `freeze` runs this stage itself and
writes `plans.json` and the plan files. The agent's part is the folder
structure, through `photo_index.py group` and `dest` — see
`photo-run/SKILL.md` step 3. The workflow below is for a dump with **no**
index; the routing rules and the folder-name grammar bind both.

Runs on any text model — no vision needed. Requires: Python 3 (stdlib only),
the shared `scripts/` folder, and manifests produced by `photo-scan`.

> Bucket names below are written with the ENGLISH defaults (`Screenshots`,
> `To-be-checked`, `others`, `AI-images`). They are not literals: every one
> resolves from the owner pack's language at run time.

## Inputs / outputs

| In | `Working Files/<source>/` manifest.csv + batches.json, see labels; on an indexed dump the index |
| Out | `plan/plan_PN.md` + `plan_PN-files.csv`, `plan/dedupe_batch-NN.json`; on an indexed dump all written by `photo_index.py freeze` |

## On a dump with an index

| instead of | run |
|---|---|
| scanning a merge target and listing `refs` in `plans.json` | `photo_index.py dest <dump> F003 merge "<existing folder>" --ref "<its work dir>" --reason "..."` (the reference still needs its own `photo_scan.py` manifest) |
| writing `plans.json`, legs and overrides | `photo_index.py group make-trip` / `make-fsl-month` / `move` / `split` / `merge` / `set-what` |
| running `photo_dedupe.py` | `photo_index.py render` (it dedupes a folder with a `dest` reference) |
| running `photo_plan.py --plan N` and `--no-date` | `photo_index.py freeze` |
| presenting `plan_PN.md` and `--status approved` | `photo_index.py check`; `finish` approves each batch as it copies |

## Workflow — a dump with NO index

**1. Prep dedupe references (once per merge target)** — every populated
folder a plan merges into needs a manifest:

    python3 scripts/photo_scan.py "/Volumes/EXAMPLE_DRIVE/<existing-folder>"

⛔ **The see stage must have run for every batch in a plan (R1).** This script
refuses a plan whose batches have no `see-labels.json` and names which ones —
`[who]` and `[what]` reach a folder name only from there, and a plan authored
first names the folder from metadata alone. `--no-vision` gives that up
deliberately for a metadata-only dump; it is not a way past an unrun stage.

**2. Decide destinations → write `plans.json`** in the work dir (this is the
agent's only thinking step). The schema is printed by

    python3 scripts/photo_plan.py --help

— read it there, not from the source file. Policy:

- **Existing folder wins** (merge-don't-duplicate): date-overlap match
  against drive-root folders; keep the owner's name as-is. Empty shells are
  filled (`fill_shell`), not renamed (D6).
- New folders: **the grammar below**, in the pack's language, under the
  collection's `dest_root` only — e.g.
  `/Volumes/EXAMPLE_DRIVE/_Photo_Manager/` (D5). `photo_plan.py` validates
  every name it is given and refuses the ones the grammar forbids. (On an
  indexed dump the names are rendered for you by `photo_index.py render`.)
- Multi-day trips get `legs` (D8 `MMDD-MMDD_[where]`); take leg names from
  the classified batches' `where` fields.
- Cross-batch strays from classify notes → `overrides` (per-date rerouting).
  An override reroutes that date's PHOTOS. It is applied after the per-file
  classifiers, so a screenshot, an unreadable format or a G-2 screen-size
  candidate taken on an overridden date still goes to its own bucket — do not
  write an override expecting it to sweep a whole day's files into one folder.
- Any plan with a merge target MUST list its `refs` — the script refuses to
  run without dedupe results (OA-3).

**3. Run dedupe** for every plan with refs:

    python3 scripts/photo_dedupe.py "<workdir>" --batches 4-12 --ref "<ref workdir>"

Rule: filename+size, SHA-256 both sides on collision. Spot-check ≥20 pairs
by independent `shasum` on a first run against a new target.

**4. Generate plans**:

    python3 scripts/photo_plan.py "<workdir>" --plan N     # per plan
    python3 scripts/photo_plan.py "<workdir>" --no-date    # D13 auto-plan

Baked-in rules (no agent judgment): screenshots/screen_record →
`YYYYMM00_Screenshots` (D7); skip_dupe wins over every other route (SPEC Q7 —
never a second copy on the drive). A STILL whose `embed/paperwork-scores.json`
score is above the pack's `routing.paperwork_margin` (a bill, a bank or tax
letter, a screenshot of one) goes to the to-be-checked bucket instead of its
trip folder, before screenshots and before overrides; the plan md lists those
files by name and says when the check did not run. Videos are never moved. Monthly-bucket folders end in `00` as the
day field so they sort inside the same month group as daily `YYYYMMDD_`
folders. **D13**:

1. Extension-mislabeled files (extension ≠ exiftool `FileType`) are planned
   under the **corrected filename** — the copy lands with the right extension.
   If the real format cannot be determined (`FileType` unknown), the file
   routes to `YYYYMM00_others` (file's own month) for human attention — the
   only automatic route into `YYYYMM00_others`.
2. **(modified)** No-date / no-where files — anything that can't be
   classified for lack of date or location. No date: a no-date VIDEO → `YYYY00_To-be-checked` (its own modify year); a no-date STILL → one `_To-be-checked/<import>` folder that claims no year (Card 5); a manifest scanned before Card 5 still uses the dump's `YYYYMM00_To-be-checked`.
   No where: `YYYYMM00_To-be-checked`.
   `YYYYMM00_AI-images` is **strictly for confirmed AI-generated images**: the
   EXIF `no_exif` rule (no camera/date/GPS) alone can't tell an AI image from
   an EXIF-stripped forwarded photo (in one measured trip folder, 246 such
   files were real trip photos). Route to AI-images only via
   `--no-date --ai-confirmed` after visual verification. `YYYYMM_Misc` is
   retired as an auto-route.
3. (folded into rule 2 — `To-be-checked` replaces `Misc`.)
   For rule 2, `YYYYMM` = the **raw dump folder's** YYYYMM; `--no-date`
   now writes an executable plan (`plan_no-date-files.csv`), run via
   `photo_execute.py --no-date`. In-plan destination name collisions get a
   `_dup2/_dup3` suffix — never overwritten.

**5. Present to the owner** — the md files, one by one; hard/merge cases
first. After sign-off per plan:

    python3 scripts/photo_classify_set.py "<workdir>" --batch N --status approved

(repeat per batch in the plan; type/where/note stay untouched).

## The folder-name grammar

The folder tree **is** the product, so this is the part of the plan the owner
actually judges. The rules live in `scripts/photo_name.py` — `render()`
assembles a name, `validate()` refuses a bad one. `photo_index.py render`
calls both for every folder of an indexed dump, and `photo_plan.py` calls the
validator on every name in a hand-written `plans.json`. What follows is that
module's contract, not a paraphrase of a document.

### The form

```
one day    YYYYMMDD_[where]_[who]_[what]
a span     YYYYMMDD-MMDD_[where]_[who]_[what]
a leg      MMDD_[where]_[who]_[what]        sub-folder inside a span parent
a bucket   YYYYMM00_<bucket>                the monthly buckets (D14)
```

Slots are joined with `_`. An empty slot is simply absent — there is no
placeholder and no double separator. A name with only `[period]` and a bucket
word is a legitimate degenerate form, not a failure.

⛔ **Three KINDS of name, not one pattern with variations.** A folder carries a
full `YYYYMMDD`; a **leg** carries `MMDD` with **no year**, because its parent
folder already has one; a **monthly bucket** carries `YYYYMM00`. Validate each
against its own kind (`photo_name.NAME_FOLDER` / `NAME_LEG` / `NAME_MONTHLY`).
Treating every name as a folder refused 32 of 132 real names, most of which
were correct.

A span's end is a **full `MMDD`**, never a bare `-DD` (D8): `20260429-03`
cannot be read across a month boundary, which is exactly when a trip most
needs a readable name.

### Field priority (D-F, re-confirmed at N-5)

`[period]` is **#1 and always first**; `[where]` is **#2**. Both are *fixed
cost* — they are always present when known, and they are never counted against
the budget.

⛔ **N-5 is not a permission to drop `[where]`.** It says the *elastic* budget
is spent on `[who]`/`[what]`. If the batch has a resolved place and the name
omits it, `photo_plan.py` **refuses** the name. In UAT01 six of eleven folders
dropped a place that was sitting on disk in `batches.json` — that is the
failure this rule exists to stop, so do not work around it by leaving
`place_known` unset.

### `[who]` — a REPEATABLE slot

`[who]` holds **subject IDs resolved to confirmed names**, joined with `+`.

⛔ **It is never capped at one.** Three subjects in one folder name is normal
and correct. Two subjects in one frame is **two names to log**, never a frame
to refuse. Any cap is a caller's parameter, not a rule of the grammar.

⛔ **N-4 binds.** A name may only come from a **`viewed-image:`** source. A
`clip-propagated:` label describes a file; it must never name a folder.

⛔ **Animals only.** The identity detector emits `cat` / `dog` / `bird` /
`horse` and **never `person`**. Human subjects are a separate, unbuilt feature
(NF-3) — a person going unnamed here is out of scope, not an engine failure.

A folder may carry an empty `[who]` until names arrive, and its name
re-renders with them **up to the freeze only** (N-6). After `photo_index.py
freeze` the names are locked (D-I16), and nothing in this engine renames a
copied folder. The merge key deliberately excludes `[who]`, so a name added
before the freeze cannot split a folder in two.

### `[what]` — keywords and short phrases

**OPEN free text** (D-F7 / D-F11): `hiking`, `sunset`, `scenery`, `play in
grass`, `coffee time`, `meals`. A longer scenario phrase is the advanced case
of the same slot, not a different mechanism.

⛔ `[what]` is **not** the 11-word `[type]` taxonomy — do not restrict it to
those words.

⛔ **It is never checked against any list, and it must never become checkable.**
An owner pack may carry the owner's own phrases — `photo_profile.
what_reference(pack)`, from `photo-entities.json` under `scenes`, and the see
stage puts them in its report as `what_reference`. That list is a
**REFERENCE**, so you can write in the owner's style; it is **never a
BOUNDARY**, so a phrase that is not in it is exactly as valid. An empty list is
the correct answer for a new owner — **no starter vocabulary ships, in any
language**, which is what stops a repeat of the `[type]` set that was handed to
every owner in one language. `photo_name.validate()` therefore takes no
vocabulary argument, and a guard case refuses one if it ever appears.

⛔ **Evidence — the two slots differ, and the difference is deliberate (D-F10).**

| slot | may rest on |
|---|---|
| `[who]` | **`viewed-image:` only** — naming an individual on a guess is how identities get corrupted |
| `[what]` | `viewed-image:` **or** a `clip-propagated:` phrase that inherited from a file somebody opened |

On the real dump only 126 of 990 files were genuinely viewed while 480 were
propagated, and `[what]` is near-constant inside a Where-About (one batch: the
same word on 181 of 206 files) — so a propagated phrase is still a claim about
the scene the model looked at. ⛔ **Read the source, not the prefix.** A
`clip-propagated:` label that inherited a cluster medoid's zero-shot *class*
is a `[type]` word nobody looked at, and it may never name a folder;
`photo_plan.rests_on_a_look()` is the one implementation of that distinction.
⛔ Raising the see rate to "improve" `[what]` buys almost nothing — five viewed
frames already pin a batch's phrase. The vocabulary was always the constraint.

⛔ `[what]` is **decoration, never part of a merge key**. A re-run that ranks a
different phrase to the top must merge into the existing folder, not create a
second one.

### The N-2 budget

Counts **`[who]` + `[what]` only**. `[period]` and `[where]` cost nothing, and
neither do the separators — the `_` between slots and the `+` between names are
punctuation, not units.

| Script | One unit is |
|---|---|
| full-width / CJK | one **character** |
| latin | one **word** (`play in Central park` = 4) |

**Hard `{20}` = refusal. Soft `{16}` = what the generator aims for** (D-F13).
⛔ **Nothing is dropped to fit** — over the soft target the name warns and
stands. The worst realistic English name is 6 units, so the soft target is
only reachable by a CJK name carrying several subjects and a phrase.
📐 Both are `{n}` parameters: read them with
`photo_profile.name_budget(profile)`, which takes them from the pack. ⛔ Never
read `photo_name.DEFAULT_NAME_BUDGET_*` directly — a constant read in place of
the pack's value is how an owner's setting silently stops being consulted.

## Sanity checks before presenting

On an indexed dump `photo_index.py check` and `freeze` prove these; on a dump
with no index, check them by hand:

- Sum of all plans' file totals + no-date count = manifest main_files.
- Zero `copy` destinations outside `dest_root` except declared
  merge/fill_shell paths.
- Leg file counts in the md sum to the plan's copy count minus screenshots.

## Known limitations

- Phone edited re-exports (`IMG_E####`) share content under a different
  name — not caught by name+size (revisit if the owner sees doubles).
- Files with `.AAE` extension but real media FileType (HEIC/PNG) are planned
  normally — since D13 they are planned under the corrected filename.
- Per-file content splits inside a batch (e.g. non-pet odds and ends inside a
  pet batch) are beyond Phase 4 (no vision) — noted in the plan for the
  owner's review.
