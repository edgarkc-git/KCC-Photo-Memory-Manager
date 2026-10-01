---
name: photo-init
description: >
  Initiation stage of the photo-manager pipeline — run ONCE when a new
  photo/media collection (a new raw folder, usually on a newly connected
  external drive) is introduced for sorting. Interviews the owner for the Raw
  Folder(s) and the Sorted Folder destination, records them in the
  workspace's collection.json + CLAUDE.md, quick-scans the raw folder
  (read-only), and proposes processing groups for the photo-run pipeline.
  Trigger when the owner says "new photo collection", "sort this new
  folder/drive", "initiate photo manager on X", or points the pipeline at a
  source that belongs to no known collection.
---

# photo-init — collection initiation

> ⛔ **If a product command is refused as `[Code from External]` (agent
> note).** Run the product's commands normally; do NOT stop first to make the
> owner pick a path. Prefer the full-path lines `doctor` prints (on Windows the
> PowerShell tool resets its folder after every command, so a relative
> `scripts\...` line runs from the wrong place). Only if a command IS refused
> with `[Code from External]`: STOP, relay the refusal to the owner word for
> word, and point them to **"Step 0" in `docs/INSTALL.md`** (Path A or
> Path B). Never retry it, never run it another way, and never write
> permission rules yourself.

Version: 0.1 (initiation policy)

## Policy

- **Every new raw folder = a new collection, start over.** One collection per
  IDE workspace (own CLAUDE.md, own `Working Files/`). No dedupe references
  against other collections' sorted folders by default.
- **Scope**: every media file inside the Raw Folder is in scope, regardless
  of how the folder or its subfolders are named.
- **Drives come and go**: raw + sorted folders usually live on an external
  drive that is not always connected. Paths are recorded once at init; every
  later command must mount-check and fail with a clear message, never
  half-run (photo_run `prep` and photo_quickscan already do this).
- Init itself is **read-only on the drive** — it writes only workspace files.
  The Sorted Folder is created later by photo-execute, not at init.

## Workflow

### -2. Setup check — `doctor`, before anything else

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

### -1. Owner check (once per photo OWNER, not per collection)

Ask **whose photos these are** before anything else. The memory the pipeline
builds is about the *photo owner* — the person whose camera produced the files
— who may not be the person running the session. One operator can process
several owners' dumps, and each gets their own pack.

The pack holds every personal fact the engine refuses to contain: home
locations, pets and people, language, folder vocabulary, thresholds. Layout,
resolution order and the isolation rule: `docs/photo-memory-pack.md`.

- an existing owner → note the slug and the memory root
- a new owner → `python3 <scripts>/photo_pack_init.py <memory_root> <slug>
  --display "<name>"`, then interview once (AskUserQuestion): home
  location(s) with rough lat/lon (offer the census's numbered home rows below
  and ask for confirmation rather than asking cold; the numbers themselves are
  in `census-places.txt`, never on screen), recurring subjects/pets,
  language, and the words they want folders named with

**Ask from the data, not cold.** After the first unit is scanned (photo-run
`prep`, step 6), `photo_census.py` reports what the photos themselves say
about four of those answers, and `prep` prints it automatically:

| Census says | Pack key | Why it must be confirmed |
|---|---|---|
| cameras found, with file counts | `own_camera_makes` | a make left off gets its photos described as **somebody else's**; a make wrongly added claims a friend's camera as the owner's. A device under 1% of the collection is flagged — as likely a photo somebody sent them as a phone they owned |
| screen-size candidates, each with a device | `screen_dims` | **moves files** into the screenshots bucket. Pick by hand and pair each accepted size with the device it belongs to (`{"model": …, "dims": [w, h]}`, G-1) — an unpaired size still works but cannot be audited later. A size that also appears on videos is flagged and should normally be refused |
| script seen in filenames/paths | `language` | names the generated buckets. A script is **not** a locale — Han could be zh-TW or zh-CN, so confirm the actual language even when the signal is strong, and say which one will be used before it names anything |
| home areas — a numbered place with its distinct days, how many of those carry an after-dark photo, month span and file count; its coordinate and map link are in `census-places.txt` beside the manifest | `home_locations` | a residence is **never** named as a place or a folder, so this has to be answered before the owner's first folders are named. The census shows **evidence, never a name**: there is no network at `prep` and it does no reverse-geocoding. Confirm each row and ask the owner for the **city word** for it — the owner may open the place's map link in `census-places.txt` if the counts alone don't identify it. ⛔ **Never read the coordinates or the links out into the conversation**: whatever reaches the transcript leaves the machine, which is why the census no longer prints them (U6-06). The onboarding sheet (below) is the preferred route — it keeps the numbers in `--coords-out` and the owner answers by letter. When a row must be written by hand, write it as `{"label": <city word>, "lat": <first number>, "lon": <second number>}` from that place's line in `census-places.txt`, with a file edit rather than by quoting the numbers: the file holds the coordinate as one pair and the pack stores two fields, so split it — a row copied whole stops the run. A proposal the pack already covers is marked **✓ already listed** and is not one of the rows to confirm — the census cross-checks these against `home_locations` the same way it does cameras, so a re-run never re-asks a settled one. For each confirmed row also ask whether it is somewhere they **live day to day**, or a residence they **travel to** (a relative's house); on the second answer add `"home_range": false`, which keeps the row unnameable but stops days spent there being filed as the owner's everyday life. Do not ask this when there is only one row — a single home is the everyday one by definition |

All-ASCII filenames mean *no signal*, not English — ask.

### Ask these on a page, not from the printed table

⛔ **Do not answer the four rows above from their numbers alone.** Two of them
cannot honestly be answered that way: the top-ranked `screen_dims` candidate is
routinely a resized-forward size rather than a real screen, and *"many separate
days, including after dark"* also describes a hotel on a long trip. Render the
checkpoint page and go through it **with the owner** — it carries the same
proposals with the **photographs beside them**, and pre-selects nothing, so
clicking straight through submits an empty answer instead of a wrong guess:

```bash
<repo>/.venv/bin/python3 <scripts>/photo_onboard_page.py render "<work dir>" --out page.html
# the owner fills it in and saves it, then (apply needs no .venv):
python3 <scripts>/photo_onboard_page.py apply page.html --pack "<pack dir>"
```

On Windows the interpreter is `<repo>\.venv\Scripts\python.exe` wherever these lines say `<repo>/.venv/bin/python3`.

⛔ **`render` and `sheet` need the repo `.venv`** (CLIP). They leave out every
evidence photograph that looks like a document — a ticket, a receipt, a form,
an ID card — because on real dumps those carried a name, an ID number, a unit
number and a phone number, and the page is a file the owner may pass on.
Without CLIP they **refuse** rather than embed unchecked photographs;
`--unfiltered-evidence` is the explicit opt-out, and the page then says it was
not checked. Each strip says how many it left out, never what they showed.

**Look up each camera's screen before rendering (W1C-1).** An owner should not
have to know their screen size. For every camera the census lists, look up its
panel resolution and pass it with its source:
`--device-spec "<camera exactly as the census names it>=<W>x<H>@<source>"`
(repeatable, on `render` and `sheet`). The page labels it *looked up by the
assistant, not measured*, and compares it with the sizes in the screenshots.
⛔ **The observed size always wins.** Phones are often set below their panel
resolution and screenshot at that setting — a 1440x3120 panel screenshots at
1080x2340 on a lower setting, the same shape — so a mismatch is explained,
never a reason to drop a size. ⛔ Never guess a number: with no source, pass
nothing, and the page is exactly what it was without this.

⛔ **No browser, or nowhere to publish? Do not skip the checkpoint and do not
answer it from the table.** The page needs a browser to read and an artifact
host to send back, and a session that has neither — terminal-only, headless,
a server install, an agent-driven run — used to be stopped dead here, at the
first checkpoint of the first run. `sheet` asks the same questions as a text
file and writes **the same photographs beside it as image files**, so the owner
still looks; they look in an image viewer instead of a browser:

```bash
<repo>/.venv/bin/python3 <scripts>/photo_onboard_page.py sheet "<work dir>" --out-dir onboard/
# open onboard/photographs/<question>/ , answer onboard/answers.txt, then:
python3 <scripts>/photo_onboard_page.py apply onboard/answers.txt --pack "<pack dir>"
```

Every block names its own photographs and every answer line ships **blank** —
returning it untouched answers nothing, exactly like clicking through the page.
`apply` refuses a sheet whose photographs are missing or changed, and refuses a
row typed in by hand: an answer written from the counts alone is the failure
this checkpoint exists to stop. It reports what was left blank rather than
completing it.

⭐ The same command also reads **the lines the page's own `Copy` button
prints**, pasted into a file — the escape hatch for a page that renders but
cannot send. Those carry no photographs to check against, and `apply` says so.

Coordinates stay off both surfaces by default (`--no-coords`): each home row
carries a letter and its evidence, and the numbers go to `--coords-out` on
local disk. Pass `--with-coords` only when the page never leaves the owner's
machine. ⛔ **That withholds the NUMBERS only** (U3-06): a photograph can still
show where a place is — a street sign, the view from a window, a letter on a
table. Never describe the page or the sheet as carrying nothing that locates
the owner. `--prefill language=…|types=…|away=…` carries in an answer already
given elsewhere; ⛔ it is **still refused for screens and homes**, which only
the owner can settle — the sheet moved the evidence, not the answer.

⭐ **The page carries one setting this pipeline asks nowhere else** — *"How far
from home is still 'home' (km)"* (`cluster_defaults.away_km`). It ships at 3 km,
and the page reads that number **off the owner's own pack** rather than
restating it: a pack still carrying the old 60 is described as 60, because a
sentence about a setting has to come from where the setting does. Left too
high, every day trip the owner takes is filed as a day at home, whole weeks
merge into one folder, and the folder names show it. **Skip the page and the
owner is never asked** — the shipped 3 applies in silence, and ⛔ the run says
so: `batches.json` carries `away_km_answered: false` and every batch is
flagged, because the template writes the key and its mere presence therefore
proves nothing. **Writing the owner's answer into the pack means writing
`away_km_answered: true` beside it.** ⛔ Especially when they answer **3**: the
value alone cannot be told from the shipped one, so without the flag an owner
who answered is warned on every batch for ever. `--write-pack` below writes
both.

### Naming a place is the question; living there is an answer about it

⭐ Each area on the page asks **"What do you call this place?"** — the owner's
own word, which is what names the folder instead of whatever the map service
returns. Whether they live there is an **attribute** of that answer:

| The owner says | What it means | Where it lands |
|---|---|---|
| `<name> live` | somewhere they live day to day | `home_locations` — never named, and the coordinate is suppressed |
| `<name> visit` | a residence they travel to | `home_locations` with `home_range: false` — still never named, but days there are not their everyday life |
| `<name>` on its own | a place they know and have named, not a residence | `frequent_places`, **with its coordinate** — nothing is withheld, and their word is used |
| `not a place` (or `skip`, `no`, `drop`) | reject the row outright | dropped |

⛔ **`not a home` is refused, not re-read.** It used to mean *drop this row*,
and under naming-first the same three words describe the row that must be
**kept**. The engine says so rather than guessing. ⛔ A home with **no name** is
still registered (`live` on its own): suppression runs on the coordinate alone,
so an owner who declines to name their own front door keeps the privacy rule.

### Writing the answers into the pack

⛔ **Writing is OPT-IN and stays that way.** With no `--write-pack` this stage
reports the answers and writes nothing — a proposal the owner confirmed is
still the owner's to place, which is `photo_census`'s stance too. Answering
does not imply writing; the owner has to ask:

```bash
python3 <scripts>/photo_onboard_page.py apply onboard/answers.txt \
    --write-pack "<pack dir>" --coords-in onboard/coords.txt
```

⛔ **Every kept place row needs `--coords-in`** — the file `render`/`sheet`
wrote with `--coords-out` — a **named non-home included**. A home is stored by
coordinate because that is how its name is withheld; a named place is stored by
coordinate because the coordinate is the only thing that can ever bind the
owner's word back to a batch. Neither surface carries one on purpose, and
`apply` has no work dirs to re-derive it from, so without that file every such
row is **refused by name** rather than dropped: a home nobody registered is a
home whose address nothing suppresses, and a label stored with no coordinate is
an answer nothing can ever read. The rest of the answers still write.

⛔ A named place is **not** a residence, so nothing about it is withheld — a
frequent place needs no key and its GPS is not sensitive (owner, 20260827). The
coordinate-based suppression rule reads `home_locations` and is untouched.

⭐ **Each answer is decided on its own, and the safe ones are written** (owner
ruling 20260924). Both the dry run (`--pack`) and the write print ONE line per
answer — `add`, `merge`, `already listed` or `refuse` — so a second phone, a
second dump or a re-run can be read before anything lands. An answer that would
overwrite what the owner already chose is **refused alone**, named, and the
command exits 1; the rest still write. A home the pack already holds (by
distance, whatever the owner called it this time) is **already listed** and
kept as it is; the page and the sheet no longer ask it, nor a screen size the
pack already routes. It prints what landed and where, and ⛔ never prints a
coordinate.

⛔ **A NEW screen size is written only on the owner's own yes, after they have
seen what it moves — the FIRST size a new owner ever registers included** (owner
ruling 20260924: a first phone's size moves files exactly as a second phone's
does). A size the pack does not hold yet MOVES FILES: every
no-camera photograph at it becomes a screenshot, in every dump bound to this
collection, including dumps already frozen or copied. So:

1. Run the dry run (`apply … --pack "<pack dir>" --coords-in …`). For each new
   size it prints how many stills and videos in **each** bound dump would
   re-route, which of those dumps are frozen or copied, and that files already
   on the drive stay where they are.
2. **Show the owner that block, in full, and ask.** A frozen or copied dump
   then answers `verify --copied` with exit 6 (every copy matches, the names
   may change) until it is re-locked.
3. Only on their yes, write with `--add-screen <WxH>` (either orientation).
   Without it that size is refused on its own and everything else is written.

⛔ **A new size is refused, not written, when the dry run could not count it**
(Card 9) — no bound collection was found for the answers (an old sheet with
no `workdirs:` line, a page or pasted lines kept outside the collection). The
refusal names the fix: make the sheet from the work dir and answer that one.
⛔ **Pasted lines and a page answer may add only a size the collection's census
offers** — they carry no record of what was asked, and a size the owner was
never shown photographs of is not one they answered.

⭐ **A screen size the copy step found (G-2, `plan/screen-size-proposals.json`)
is asked the same way.** The census now also offers a size proven by a single
file named like a screenshot, which is exactly G-2's evidence, so re-making the
sheet for that work dir asks it — `sheet "<work dir>" --out-dir <folder>`, then
the steps above. Never hand-edit the pack for it.

⛔ **Never pass `--add-screen` on your own judgement** — not because the census
proposed the size, not because the size "is obviously a phone", not because
the owner answered the sheet's screen question. The sheet answer says *this is
my screen*; the yes to the preview says *move these files*. They are two
answers.

### Ask which animals live with the owner

⭐ The page and the sheet both ask for the **animals that live with the owner**,
by name. Each declared name becomes a **subject record** (`subj-NNNN`) — the
same id `photo-subjects/subjects.json` keys exemplars on, so there is one
subject model and not two.

⛔ **Declaring attaches nothing to a face.** It creates an identity for the
owner to attach frames to at the naming checkpoint; the engine never decides
which animal is which, so recognition is still learned from photographs only.
An animal declared and never seen stays an **empty record** — that is the
intended outcome and is never reported as a recognition failure. It is what
lets the engine say *"you told me three, I have drafted two"* instead of
leaving the third one's absence invisible to everyone but the owner.

⛔ **Animals only.** Human subjects are out of scope; the detector never emits
`person`. Left blank, nothing is created and nothing is lost.

⛔ **A home the census did not propose is still on that page**, in its own
block under the proposals, with its photographs and with the reason it was
withheld. A residence the owner photographed like a visitor — few distinct
days, few evenings spent indoors — lands there rather than among the
proposals, and it is **answered exactly like a proposed row**, by its letter:
so it also gets the *"day to day, or a residence you travel to?"* follow-up
that a missing row would have cost it. Read those rows out too, along with the
line saying how many more were cut by the cap and by the one-daytime-visit
filter — and if the owner's home is not among them, `photo_census.py
"<work dir>" --all-places` lists every place that was cut, numbered, with its
coordinate in `census-places.txt`. A home left unregistered is a home whose address nothing suppresses.

**Say what `language` reaches, so the answer is not over-read.** It governs two
different things, and the second is the one owners do not expect:

1. **The words this product writes** — the buckets it creates (screenshots,
   to-be-checked, others, AI images) and the labels it composes.
2. **The language this product asks the map service for.** Place names are not
   invented here and are never translated here: the product requests the
   owner's language from the map service and uses what comes back.

Where the map service holds a name in that language, that name is used. Where
it does not, the product falls back to the **local** name — and it says so
rather than swapping scripts silently, so an owner is not left with a folder
they cannot read and no explanation. With no `language` in the pack the
request is **English**. Where it says so: the cluster stage names the batches
that used the local name (stderr, at the end), and `photo_run status` marks
them. A `language` the engine holds no word table for falls back to English
too, and says so once per stage on stderr — and `apply` says so the moment the
answer is recorded — rather than leaving the owner to read English folder
names as a fault in their pack.

⛔ So this answer reaches the owner's **folder names**, not just the buckets.
It is worth a sentence at the question rather than a discovery afterwards.

The home row often proposes **nothing** on a first dump — one dump is normally
one month, and plenty of collections carry little or no GPS. That is an
ordinary first run, not a failure: in the **same question**, ask the owner to
name their home areas at **city level** and put those in `home_locations`
(a row typed by hand has no id — run `photo_onboard_page.py backfill-ids
"<pack dir>" --go` after it, D-I15, and never type an id yourself). Do
not defer it to a later interview — the privacy rule is unenforced until it is
answered. Month span is shown as evidence and is deliberately **not** part of
what makes a proposal appear; later dumps refine these through the same
checkpoint, never through a fresh interview.

Put the memory root wherever the owner's private notes live — never in the
engine repo. With no answer at all, the default is `photo-memory/` beside
`collection.json`, so nothing has to be installed or decided up front.

⚠️ `naming_spec.types` is the vocabulary `photo_classify_set.py` validates
against. A type in use but missing from the pack is rejected at classify — if
you are adopting an owner who already has sorted output, check their existing
`batches.json` types against the list.

⛔ **The owner's `types:` answer REPLACES the vocabulary, it does not join
it.** `allowed_types()` takes `naming_spec.types` over `default_types()`
entirely, so whatever you transcribe into the pack is the whole list and every
other word is refused at classify. Two consequences when you write it:

- **Transcribe kinds, not prose.** An answer written as a sentence ("a trip,
  an event") becomes three unusable strings and refuses every batch. Strip
  articles, keep one word or hyphenated phrase per entry, and read the answer
  back to the owner before writing it.
- **A blank answer is the right answer for most owners** — omit the key and
  they inherit `default_types()` for their language. Write the key only when
  the owner asked for words the engine does not have.

### 0. Workspace check

One collection per workspace. If the current workspace already has a
`Working Files/collection.json` for a different collection, stop. Ask the
owner to make a new, empty folder for this collection and open the agent
there (`docs/INSTALL.md`, step 5), then re-run photo-init in it.

**What this stage expects to find.** Exactly one state folder, named
`Working Files` — with the space, capitalised, directly inside the workspace.
Everything this product writes outside the destination drive lives there:
`collection.json`, one per-dump work dir, and the quickscan output. It is
normal for it **not to exist yet** — create it and say so.

⛔ **If something close but not equal is already there** — `Working/`,
`Work Files/`, `photo-work/`, or an old state folder under another name —
**do not adopt it and do not rename it.** Create `Working Files` as named,
then tell the owner in one line: which folder you created, which near-miss you
left untouched, and that you did not look inside it. The two most likely
explanations are opposite in consequence and only the owner can tell them
apart: it is somebody else's folder that merely looks similar, or it is a
previous run's state under a name this SKILL no longer uses. Guessing the
second one wrong adopts a stranger's state; guessing the first wrong strands
work the owner still wants.

⚠️ A near-miss is not an error and does not stop the run. Create, report, and
carry on — the owner can move or delete anything afterwards, and nothing this
product writes ever depends on the other folder.

⛔ **A name differing only in CASE is a different situation, and the filesystem
decides which.** On a case-insensitive one (the macOS default) `working files/`
and `Working Files/` are the SAME directory: creating the second silently uses
the first, and reporting "created `Working Files`" would be false. On a
case-sensitive one they are two directories and the rule above applies.
⛔ Do not resolve this by guessing which kind of disk you are on. Say what you
found, say that a case-only difference may or may not be the same folder here,
and let the owner choose the name — this is the one near-miss that can silently
adopt somebody else's state while looking like a clean start.

### 1. Ask: where is the Raw Folder? (AskUserQuestion)

Ask the owner for the Raw Media Files Folder location(s) — more than one
path is allowed. Ask with an empty question: ⛔ do NOT list drives or folders
first, and never offer a folder the owner did not name as a choice. A disk
holds the owner's private folders; showing them as options turns a question
into a tour of their drive (HIL01 HIL-1).

Verify each typed path exists. ONLY when one is missing, list `/Volumes/`
to say which drives are connected, and ask the owner to connect the drive or
correct the path, rather than guessing.

### 2. Ask: where should the Sorted Folder go? (AskUserQuestion)

Offer options in this order:

1. **(Recommended / default)** `/Volumes/<drive>/_sorted_<RawFolderName>` —
   same drive as the raw folder, next to it, named `_sorted_` + the raw
   folder's name. Example: raw `/Volumes/EXAMPLE_DRIVE/Photo Archive` →
   `/Volumes/EXAMPLE_DRIVE/_sorted_Photo Archive`.
2. Other — the owner types a path (for example a sorted folder they already
   use).

⛔ On a first run, offer only these two. Never look for, and never offer, a
folder you found on a drive (an existing sorted or archive folder): merging
into a folder the owner did not name is their call, made by typing it.

### 3. Record the configuration

**One of these two is authoritative and the other is a convenience. Know which
before you write either.**

| | What it is | Who reads it |
|---|---|---|
| **a. `Working Files/collection.json`** | **THE configuration.** | the ENGINE |
| b. a Key Configuration block in the workspace `CLAUDE.md` | a human-readable copy of the same facts | people, and agents reading context |

⛔ **Step (a) is required. Step (b) is OPTIONAL and skipping it costs the
engine nothing** — no pipeline stage parses that file, or any `.md`, for
configuration. The engine reads `collection.json` for `owner`, `memory_root`,
`dest_root`, `raw_roots` and `settings`, and reads nothing else anywhere for
them. A workspace with no `CLAUDE.md` at all runs normally.

⛔ **Never edit a `CLAUDE.md` you did not create without asking the owner
first.** In a workspace the owner set up themselves it is their own governance
document, not a product file — and it is the more common case, not the edge
case. If the owner says no, or does not answer, **write (a) and carry on**:
say that the configuration is complete and that (b) was skipped by choice. Do
not stall the run on it, and do not imply something is missing.

a. `<workspace>/Working Files/collection.json` — **the authoritative copy**:

```json
{
  "collection": "<workspace name>",
  "owner": "<owner slug from step -1>",
  "memory_root": "<where that owner's pack lives>",
  "created": "YYYYMMDD.HHmm",
  "drive": "<volume name>",
  "raw_roots": ["/Volumes/<drive>/<Raw Folder>"],
  "dest_root": "/Volumes/<drive>/_sorted_<Raw Folder>",
  "groups": []
}
```

`owner` binds this collection to exactly one pack. Naming an owner with no
pack stops the run — the engine will not fall back to whichever pack happens
to be configured, because mixing two people's photo memories is worse than a
failed run. `memory_root` may be omitted for the default location.

The pipeline scripts pick this up automatically: run `photo_run.py` and
`photo_index.py` from the workspace folder and `Working Files/collection.json`
supplies the workdir root, so a command run THERE takes the bare dump name.
⛔ From any other folder (a work dir included) a bare dump name is not found:
paste the printed next-step lines as they are, with their full paths;
`photo_plan.py` / `photo_execute.py` resolve `dest_root` from it (allowlist
follows it — D5 generalized per-collection). A merge into an existing folder
is declared per folder with `photo_index.py dest`.

b. **(optional — ask first, skip freely)** The workspace `CLAUDE.md`, Key
Configuration section. This is for a human or an agent reading the workspace
for orientation; nothing in the pipeline reads it.

```
Raw Folder(s):  /Volumes/<drive>/<Raw Folder>   (external drive — not always connected)
Sorted Folder:  /Volumes/<drive>/_sorted_<Raw Folder>  (dest_root; created at first execute)
Config:         Working Files/collection.json (THE configuration — this block is a copy)
```

⚠️ Two copies of one fact drift. If they ever disagree, `collection.json`
is right by definition and the block is stale — correct the block, never the
other way round.

### 4. Quick scan (read-only)

```
python3 scripts/photo_quickscan.py "<raw root>" --out "<workspace>/Working Files"
```

Seconds-fast inventory: per-subfolder counts, photo/video/other mix, `.AAE`
(D4) and junk counts, size, and a date estimate (folder-name hints + a small
sampled exiftool call — an *estimate*, not the full scan; `prep` does the
real one later). Units over `--max-unit` (default 5,000 — largest proven
photo-run was 4,819 files) are flagged **⚠️split**: re-run quickscan on that
subfolder to break it into its own sub-units until nothing is flagged.

### 5. Propose and confirm the batch approach

Present to the owner: (1) the quickscan summary table, (2) the proposed
processing groups — **one unit (subfolder / loose-files bucket) = one
photo-run cycle**, grouped by estimated year for review. Adjust per the
owner's feedback, then write the approved groups into `collection.json` under
`groups` (each: `group`, `label`, `sources`, `status: "pending"`). Update a
group's `status` to `done` as its units finish the pipeline.

### 6. Handoff to photo-run

Process groups in approved order, from the workspace folder:

```
cd <workspace>
python3 <scripts>/photo_run.py prep "<unit source path>"
python3 <scripts>/photo_index.py init <dump name>
```

`collection.json` (step 3) binds the owner, so a run started from the
workspace folder resolves the pack with no `--profile`, and every later
command takes the bare dump name `prep` printed. The unit source path is the
only path typed: it is one of the `raw_roots` recorded above.

⭐ **The FIRST unit of a new owner is scanned WITHOUT clustering** (D-I1):
`prep "<unit source path>" --no-cluster` runs the scan and the census the
onboarding page needs, the owner answers and `apply --write-pack` writes the
pack, and only then `photo_run.py cluster <dump name>` cuts the batches and
`photo_index.py init <dump name>` builds the index. A
day at a LABELLED home is then named from the owner's own label, with no
geocoder call at all; a day at a home left unlabelled is named from a coarse
city lookup whose position is rounded to 2 decimal places before it is sent.
Later units, with the homes already in the pack, use plain `prep`.

Everything downstream is photo-run procedure (see `photo-run/SKILL.md`):
the vision pass per batch, then `finish --go` with its stops. ⛔ **Do not promise a re-cluster for a lumped batch** —
there is no documented one (U3-10). A new cut with the owner's answers —
`photo_index.py recut` — is possible only BEFORE `photo_see` has run: its
labels are held per batch, so `recut` refuses once anything per batch exists
and names it (U3-11). A place label that arrives later needs no re-cut:
`photo_index.py relabel`.

⭐ **Say what comes next before the first page (G6).** On a dump with an
index, `finish --go` stops for **a few short pages, a few minutes each**, and
the copy waits for them: for the first batches that show an animal, the owner
matches each pet named at onboarding with its photos, picking the name from
their own list; wherever a place they visit often first shows up with no name,
they name it (and say `live` or `visit` if it is a home). Tell the owner this
now, in those words, so the first stop is expected. The commands for each page
are in `photo-run/SKILL.md` (Workflow, step 3a).

## Notes for old archives (pre-iPhone-dump era)

- Expect loose files at the raw root — quickscan buckets them as one
  `(loose files)` unit; they are in scope like everything else.
- Old cameras/phones often have no GPS: batches will lean on date-only
  clustering, and more files will land in a to-be-checked bucket (under an
  English pack: a no-date VIDEO → `YYYY00_To-be-checked` (its own modify year); a no-date STILL → one `_To-be-checked/<import>` folder that claims no year (Card 5); a manifest scanned before Card 5 still uses the dump's `YYYYMM00_To-be-checked` — the word resolves from the pack's language)
  (D13). That is expected, not a failure.
- Android exports (`Screenshot_*`, `*_capture`, epoch-millis filenames) may
  carry no EXIF; the D13 no-date route handles them.
