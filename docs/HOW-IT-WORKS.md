# How it works

The short README points here for the internals. Install: [INSTALL.md](INSTALL.md).
Where your data goes: [YOUR-DATA.md](YOUR-DATA.md).

Sort a phone/camera photo dump into dated, named folders you can actually
browse — **the folder tree is the product**. No database, no viewer, no
lock-in. Point Immich or PhotoPrism at the result if you want a UI.

The engine plans, a human approves, the engine copies and verifies. Originals
are never moved, renamed or deleted.

```
scan → cluster → index → vision pass → owner pages + agent views → render → check → freeze → copy → verify
```

Alongside it, the Visual Sorting module builds a local embedding index
(`photo-embed`, VS-1), runs a **recurrence census** over a whole collection
(`photo-recurrence`, VS-1b) — what keeps coming back, ranked by how many files
a human answer would relabel — and decides **which files the vision model
actually has to look at** (`photo-see`, VS-2): scene zero-shot plus in-batch
visual clustering plus a priority-filled see-rate, so a confident CLIP match
costs no vision budget at all.

`photo-see` is also where **subjects get named**. Animals that keep coming back
are recognised across the collection, the owner is asked what each one is
called, the name is remembered in the owner pack, and later folders carry it —
so a folder can say the animal's name instead of its species. Named subjects
are a pack fact, never engine content, and the registry holding them is
inspected and repaired with `photo_subjects.py review`.

## Status

Phase A of the v2 re-engineering: the engine has been extracted into this
standalone repo and is guarded by two test suites — a **golden-dump
regression harness** (four dumps that already shipped, 13,208 planned rows,
`tests/golden_replay.py`) and a **fresh-owner smoke test** proving the whole
chain runs for an owner the engine has never seen, in a different language
(`tests/fresh_owner_smoke.py`). It has run end-to-end on 17 real dumps
(~35,000 files) as `Claude-Skills/Photo-Manager`, which stays frozen as the
fallback.

**Licence: Apache 2.0** — see [LICENSE](../LICENSE).

## What is in here

| Path | What |
|---|---|
| `scripts/` | the engine — plain Python 3, no packages to install, except `photo_embed.py` / `photo_recurrence.py` / `photo_see.py` (below) |
| `photo-*/SKILL.md` | agent-facing instructions, one per pipeline stage |
| `docs/` | naming SPEC, build plan, `status.json` schema, and these guides |
| `tests/` | golden-dump regression harness (`tests/README.md`) |

Requires `exiftool` (capture dates and GPS — filesystem timestamps are
worthless for this, see below). Everything else is the standard library,
**except** the Visual Sorting module's `photo_embed.py` (VS-1), which needs a
local CLIP model and the preview libraries in a repo `.venv/` (see
[INSTALL.md](INSTALL.md)), never installed into the system interpreter the rest
of the pipeline runs on. See
`photo-embed/SKILL.md`. The first run downloads the CLIP weights from Hugging
Face, so it needs the network; once they are on disk every later run loads
them with no network call. `photo_recurrence.py` and `photo_see.py` need only
numpy from that same `.venv` — they load no model.

`photo_identity.py` (VS-3b) is the one other stage that loads models, and it
loads two: a COCO detector from `torchvision` (~167 MB) to find the animal in
the frame, and DINOv2 (~330 MB, `torch.hub`) to embed the crop. Both are
fetched on first use and cached by torch, so the first run needs the network;
once both are on disk every later run loads them with no network call. It builds a SECOND index, for
subject identity only — the CLIP index stays exactly as it is and keeps doing
scene, clustering and recurrence. **The stage is optional**: a work dir that
has never run it, and a pack with no identity vectors, both fall back to
scoring subjects in the CLIP space, which is what every run did before it
existed. `.[all]` in [INSTALL.md](INSTALL.md) includes torchvision.

## Two things it holds no data about

**The engine ships with zero facts about any photo owner.** Home locations,
pets, people, vocabulary, language, thresholds — all of it lives in a
**photo memory pack** outside this repo, one folder per owner, loaded through
`--profile` / `PHOTO_PROFILE` / `collection.json → owner`. A run loads exactly
one owner's pack and hard-fails rather than falling back to somebody else's.
See `docs/photo-memory-pack.md`.

**The engine never deletes.** Every stage copies and SHA-256 verifies. Trash,
duplicates and sidecars are *proposed* for you to remove by hand.

## Why not just use the file dates

Finder's "Date Modified" is when the file reached the drive, not when the
photo was taken — an entire archive can show one identical date. The pipeline
reads EXIF `DateTimeOriginal` and nothing else. Files with no usable date are
routed to a "to be sorted" bucket for human triage rather than guessed at.
(The bucket's actual folder name comes from the owner pack's language —
`To-be-checked` under the English default.)

## Running the tests

```bash
python3 tests/golden_replay.py          # replay every golden dump, offline
python3 tests/fresh_owner_smoke.py      # full chain for an unknown owner
```

The replay needs a fixture set. `tests/golden/` is one owner's real data and a
checkout may not carry it — point the harness at your own with `--fixtures DIR`
or `$PHOTO_GOLDEN_FIXTURES`. With no fixtures it exits **2** and says so; it
never reports a clean replay over zero dumps. Everything else in
`tests/README.md` runs with no fixtures at all.
