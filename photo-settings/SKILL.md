---
name: photo-settings
description: >
  SET-2 of the photo-manager v2 settings surface — the conversational layer
  over `scripts/photo_settings.py`. Shows every effective setting with the
  layer it came from, explains in plain language what each one changes, and
  writes a change to the owner's pack only after saying whether it moves
  files or only edits a label. The owner never opens a JSON file. Trigger
  when the owner asks what a setting does, why a value is what it is, which
  model does what and what it costs, how many photos the vision model looks
  at, or says "settings", "change the model", "see rate", "photo-settings".
---

# photo-settings — the settings conversation (SET-2)

Version: 0.1 (SET-2 build)

## What this is

`scripts/photo_settings.py` (SET-1) reads, resolves, validates and writes.
This skill **talks**: it decides which of the three commands answers the
question in front of you, states the consequence before a change, and reads
the tool's answer back.

**The owner never opens a JSON file.** If a session ends with the owner being
told to edit `photo-profile.json` by hand, this skill failed — every value it
covers is reachable through `show` / `explain` / `set`.

Runs on any text model. Needs Python 3 (stdlib only) and the owner's pack. No
drive, no photos, no vision call, no network. It reads no work-dir state and
changes no plan: running it can never alter where a photo has already been
copied or what a pending plan proposes.

## Speak the tool's sentences, not your own

Every explanation and every refusal the script prints comes from the pack's
vocabulary, already in the owner's language (ONB-9). **Read those back;
never paraphrase them into your own wording.** A refusal in particular is a
sentence someone wrote once, on purpose — re-wording it loses the reason.

Prose you compose yourself — the stage table below, an answer to a question
the tool has no message for — goes in the owner's language like any other
reply. Language is a variable; the engine's default is English and the pack
overrides it.

## The three commands

| Question in front of you | Command |
|---|---|
| "what are my settings?" · "why is it doing that?" | `show` |
| "what does *this one* do?" · before any change | `explain <key>` |
| "change it" | `set <key> <value>` — then `--go` |

```
python3 scripts/photo_settings.py show    [--workdir W] [--profile P] [--flag k=v] [-v]
python3 scripts/photo_settings.py explain <key> [--workdir W] [--profile P]
python3 scripts/photo_settings.py set <key> <value> [--workdir W] [--profile P] --go
```

- `--profile` is a pack folder; `--workdir` is a **per-dump** work dir (that
  is where `collection.json` is found — one level above it). In a collection
  workspace, `--workdir` alone resolves the owner. A relative `memory_root`
  in `collection.json` is read from the current directory, so run from the
  workspace folder or pass `--profile` — "there is no pack at ..." is usually
  this, not a missing pack.
- **Exit 2 means refused** — "I will not do that", not "something broke".
  Exit 0 means the command answered.
- `-v` adds each setting's one-line reason to `show`. Use it when the owner
  is browsing rather than hunting one key.
- `--json` on `show` / `explain` is for you, not for the owner. Never paste
  it into the conversation.

## Say the tag before you confirm

Every setting carries a **blast tag** — this is ONB-10's corollary, verbatim:
*say whether a change moves files or only edits a label.*

| Tag | What it means for the owner |
|---|---|
| `moves-files` | changes which folder **future** runs copy a photo into |
| `label-only` | changes how a folder is named, not where a photo goes |
| `cost-only` | changes what a run costs in time or tokens |
| `schedule-only` | affects unattended runs (SET-3 owns these) |

`set` without `--go` is a dry run: it prints `old → new`, prints the tagline
for that tag, and writes nothing. **Always run the dry run first and put its
tagline in front of the owner before you add `--go`** — for a `moves-files`
key, get an explicit yes. Files already copied are never moved or deleted
retroactively; the tagline says so, so let it.

## What actually runs at each stage

Several "which model?" questions dissolve once the owner sees this. Say it in
plain language — most of these stages have no model in them at all.

| Stage | What actually runs | What the owner can choose |
|---|---|---|
| Reading dates, GPS, file type | `exiftool` plus scripts — **no AI model** | nothing to choose |
| Building the visual index | a **local** model on this machine, free per photo after the download | `models.embed_local` — changing it forces a full re-index |
| Looking at photos and saying what is in them | a vision model, with a **floor** | `models.classify` — upward only |
| Copying files | the script copies the bytes and checksums them; a model only reports | `models.copy_conductor` — any is safe |

**The classify floor is policy, not preference.** A weaker model once
described photos it had never seen, so the floor cannot be argued down and
this skill must not try. The tool refuses a below-floor value and names the
models it accepts.

A model the engine cannot place on its ladder is **refused rather than
assumed** to clear the floor. So an owner naming a newer, stronger model may
still be refused — the honest answer is that the ladder is engine code
because the floor is engine policy, and a stronger model reaches the accepted
list by being added there. That is a change to the engine, not a setting; do
not work around it by lowering anything.

## Two knobs that sound the same

- **The visual index covers every photo, always.** `visual.embed_coverage` is
  shown so the owner can see it and is deliberately not editable: how often
  something recurs cannot be measured on a sample.
- **The see-rate IS a setting** — how much of a batch the vision model looks
  at: `sampling.gps_pct`, `sampling.no_gps_pct`, and the
  `sampling.min_samples` / `sampling.max_samples` floor and ceiling that
  override the percentages on small and large batches. All `cost-only`.

`sampling.min_samples` may never exceed `sampling.max_samples`. The tool
checks that against
the **resolved** configuration, so it also reports a pack that already
disagreed with itself before you touched it — a complaint about a key the
owner did not just change is real, not a glitch.

## On a brand-new pack

Assume the owner's pack was created minutes ago and holds nothing — no
subjects, no home locations, no history. That is the normal starting state,
and `show` reads correctly in it. Measured on a pack straight out of the
shipped template:

- only the four `sampling.*` rows come from `your pack` — the template ships
  those and nothing else in this surface;
- every other row says `engine default`, which is not a gap. It is the value
  a run will actually use;
- `models.embed_local` and `schedule.window` render as `—`. **Blank is a
  real state, not a missing one**: no local model has been chosen yet (the
  visual-index stage picks it) and no schedule exists yet (SET-3 makes one).
  Say that, rather than treating the dash as something to fill in;
- **the collection layer shows nothing at all**, because a fresh workspace
  has no settings in `collection.json` — and none should ever be put there
  (below).

Never invent a value to make an empty layer look populated, and never present
a mature-looking configuration the owner does not have.

## Where a value came from

`show`'s `from` column is the answer to "why is it doing that?": engine
default → the owner's pack → this collection → a flag on the command, last
one wins.

- **A flag beats everything, for one run only.** `show --flag <key>=<value>`
  previews what a stage command's own flag would do without writing anything
  — the honest answer to "what would that change?"
- ⚠️ **The collection layer is displayed but cannot be written.** No stage
  script reads a setting out of `collection.json` today; every one resolves
  through the pack. So a value found there is shown **with a warning naming
  the value the run will actually use**, and `set` writes to the pack. Do not
  soften this and do not offer to put a setting in `collection.json` "for
  this collection only" — that would promise an effect the engine does not
  have. If a collection value is shadowing something, tell the owner it is
  being ignored and offer to set it in the pack instead.
- ⚠️ When a key carries that warning, `set`'s `old → new` line shows the
  **collection's** value as `old`, which is the value the run was *not*
  using. Say which one was actually in effect; do not read the arrow out
  unqualified.

## Do not promise these

- **The `naming.*` keys are stored and unread.** The naming principle behind
  them is signed and unbuilt — no stage reads them yet. `show` and `explain`
  both print a warning saying so; keep it in front of the owner rather than
  selling the switch. `naming.smart_scenario` is a real `moves-files` key for
  the day it lands, and it is also the way back out: off, every folder falls
  to the plainer name with no re-planning.
- **`schedule.*` is read-only here.** The schedule wizard (SET-3) owns it;
  say that instead of editing anything.
- **There is no cap on how many subjects may be remembered**, and there is no
  setting for one. An earlier budget was removed on purpose. If the owner
  asks for a limit, do not offer to add one here — a warning threshold lives
  with the subject registry, not with these settings.
- **`naming.max_units` and `naming.soft_target_units` count name units, not
  characters.** `explain` prints the unit note for them; a number whose unit
  is unstated is not one the owner can act on. `naming.max_names_in_folder`
  is a count of subjects, not of letters either.

## Walkthrough — the fresh-owner path

A non-developer owner who has never seen this repo, changing the see-rate and
the copy model, without any JSON.

**1. Show them where they stand.**

```
python3 scripts/photo_settings.py show --workdir "<work dir>"
```

```
pack: <owner> · <pack path>

  setting                     value  from            changing it
  --------------------------  -----  --------------  -------------------------
  models.classify             opus   engine default  moves files
  models.copy_conductor       haiku  engine default  cost only
  ...
  sampling.no_gps_pct         0.05   your pack       cost only
```

Read the shape, not the table: these are their settings, most came from
defaults, and the last column says what each one can do to their files.

**2. They ask for more photos to be looked at.** Explain first:

```
python3 scripts/photo_settings.py explain sampling.no_gps_pct --workdir "<work dir>"
```

Read back the reason and the tagline — here, that it costs more time or
tokens and moves nothing.

**3. Dry run, then confirm.**

```
python3 scripts/photo_settings.py set sampling.no_gps_pct 0.15 --workdir "<work dir>"
```

```
sampling.no_gps_pct: 0.05 → 0.15 (your pack)
This changes what a run costs in time or tokens. It does not move a file or rename a folder.
Nothing was written. Re-run with --go to save it.
```

Put that in front of them, get the yes, then add `--go`. The tool answers
`Saved to <pack>/photo-profile.json.`

**4. The copy model, same three beats** — `explain models.copy_conductor`
says any model is safe because the script does the copying; then dry run,
confirm, `--go`.

**5. If they aim at the classify model instead**, the tool refuses with the
floor and the accepted list. Read the refusal back and stop there; a
`moves-files` key is exactly where a workaround is worst.

Re-running a `set` that is already true answers *nothing to do* and exits 0 —
a safe way to check a change landed.

## Never

- Never edit `photo-profile.json` by hand, or tell the owner to.
- Never route around a refusal — every one of them is a decision someone
  recorded, and the refusal text says what to do instead.
- Never add `--go` in the same breath as the dry run for a `moves-files` key.
  The dry run exists so the owner sees the consequence first.
- Never write settings into `collection.json`, and never describe a value
  found there as being in effect.
- Never invent a setting. If `show` does not list it, it is not one — say so
  rather than proposing a key the engine will not read.

## Eval record

SET-2's exit test, run on the clean sheet Release A starts from — a pack
built minutes earlier from the shipped template, for an owner the engine had
never seen, resolved by `--workdir` alone: `show` printed all
14 settings with their layers; the see-rate (`sampling.no_gps_pct`) and the
copy model (`models.copy_conductor`) were both explained, dry-run, confirmed
and written; a below-floor `models.classify` was refused with the floor and
the accepted list (exit 2); the pack's JSON was never opened or shown. Golden
replay reproduced all seven dumps unchanged — this tool is plan-neutral.
