# Your data: where it goes

Every place this product writes, what it never writes, what leaves your
machine, and how to delete it all.

How this was checked: a full run on a made-up owner with 15 made-up photos,
in scratch folders on a Mac (doctor, quickscan, prep, cluster, index, embed,
identity, see, the onboarding sheet, render, freeze, copy, verify), with the
source hashed before and after and the product folder and the home-folder
caches checked for new files. Each row says **measured** (seen in that run) or
**from the code** (read in the code, not seen in a run). Windows paths are
**not measured** unless a row says so.

Words: **workspace** is the folder you start the agent in, one per collection
([INSTALL.md](INSTALL.md#5-start-the-workspace-and-the-first-prompt)).
**Dump** is one unit of photos the pipeline runs on (for example one month's
folder); its **work dir** is `Working Files/<dump>/`.

## Where it writes

### 1. The workspace: `<workspace>/Working Files/` (measured)

Created at the first step. Everything the product keeps about the collection,
outside the destination, is here.

| File | What is in it |
|---|---|
| `collection.json` | the configuration: owner, memory root, raw folders, destination, groups |
| `quickscan.json`, `quickscan.md` | the first read-only inventory: counts, sizes, estimated years |
| `geocode-cache.json` | place names from OpenStreetMap, keyed by position rounded to 2 decimal places (about 1 km) and language |
| `overpass-cache.json` | map features (peaks, trails) keyed by an area around the photos, to 4 decimal places. Written only by `photo_where.py` (the `photo-classify` stage); measured by running that script by hand |
| `photo-memory/` | the owner pack, **when `collection.json` sets no `memory_root`** (section 2) |
| `<dump>/` | one work dir per dump (below) |

Inside each work dir `Working Files/<dump>/` (measured unless marked):

| Path | What is in it |
|---|---|
| `manifest.csv` | one row per file: its path, capture date and time zone, camera, and **GPS position** |
| `scan-summary.json`, `scan-errors.log`, `no-date-files.csv` | scan counts, files exiftool could not read, files with no date |
| `census-places.txt` | the places the census numbered as possible homes, **with their coordinates and map links**. Kept on disk so they are never printed on screen. Written when the census numbers a place |
| `batches.json` (+ `batches.json.bak`), `status.json`, `index-pointer.json`, `plans.json` | the batches, the run's progress, where the index is |
| `embed/` | vectors made on this machine from each photo (CLIP and animal identity), scene labels, and document flags (which photos look like tickets or ID cards) |
| `classify/batch-NN/` | `see-report.json` (which photos the vision pass may look at) and `samples/`: **downscaled copies of the selected photos**, the only pictures the agent looks at |
| `classify/batch-NN/where.json` | per-day places, written by `photo_where.py` only |
| `classify/batch-NN/see-labels.json`, `decisions.json` | the labels the vision pass gave the selected photos, and the agent's answers file (from the code; the test run did not apply a vision pass) |
| `P-B<NN>.md` | a per-batch question page for you to answer (from the code; the test run asked nothing) |
| `review-crops/` | cropped animal pictures for a review page (from the code; not reached in the test run, which had no animals) |
| `memory-review_C<N>.md` | a checkpoint page for you to answer |
| `plan/` | the copy plans (`plan_*.md`, `plan_*-files.csv`), copy state and copy logs with SHA-256 per file |

### 2. The owner pack: `<memory root>/<owner>/` (measured)

The pack holds what the product learns about one photo owner: homes, pets,
language, folder words. One folder per owner.

- **Default** (measured): `<workspace>/Working Files/photo-memory/<owner>/`.
- **When set**: `memory_root` in `collection.json` (from the code; the
  `photo-init` step asks where the owner's private notes live), or a pack
  named with `--profile` / the `PHOTO_PROFILE` variable.

| Path | What is in it |
|---|---|
| `photo-profile.json` | settings and facts: home locations (**coordinates**), cameras, screen sizes, language, folder words |
| `photo-entities.json`, `photo-owner-<owner>.md`, `photo-proposals.md` | people, pets and places; a short description of the owner; drafts waiting for confirmation |
| `photo-memory-log.md` | an append-only record of what was learnt and when |
| `photo-subjects/` | named animals: `subjects.json` plus their vectors (`vectors/`, and from the code `identity-vectors/`, `draft-vectors/`) |
| `photo-index/<dump>/` | the index for each dump: `index.json`, `Index_pscan.md` |

### 3. The onboarding sheet: the folder you or the agent name (measured)

`photo_onboard_page.py sheet "<work dir>" --out-dir <folder>` (the SKILL's
example is `onboard/` in the workspace) writes:

- `photographs/`: **small copies of your photos** shown as evidence beside each
  question (photos that look like documents are left out);
- `answers.txt`, `screen-filenames.txt`: your answers, and the full file names
  (the page itself shows them masked).

With `--coords-out <file>` it also writes the home coordinates to that file
(from the code). `photo_onboard_page.py render --out page.html` writes one
HTML page with the photos inside it (from the code).

### 4. The destination (measured)

The sorted folder in `collection.json` → `dest_root`. Created at the first
copy, never before. It holds the day folders (for example
`YYYYMMDD-MMDD_<place>`) and the buckets (for example `_To-be-checked/`), each
file a byte-for-byte copy, checked by SHA-256 after copying.

A merge into a folder that already exists elsewhere happens only when you
approve it for that folder (`photo_index.py dest`).

### 5. Model weights

Measured on a Mac. Downloaded once, on the first vision run, by the libraries the product uses:

| Model | macOS (measured) | Windows 11 (from the libraries' defaults, not measured) |
|---|---|---|
| CLIP, 577 MB | `~/.cache/huggingface/hub/models--laion--CLIP-ViT-B-32-laion2B-s34B-b79K/` | `%USERPROFILE%\.cache\huggingface\hub\…` |
| animal detector, 167 MB | `~/.cache/torch/hub/checkpoints/fasterrcnn_resnet50_fpn_v2_coco-*.pth` | `%USERPROFILE%\.cache\torch\hub\checkpoints\…` |
| DINOv2, 330 MB + 4.5 MB code | `~/.cache/torch/hub/checkpoints/dinov2_vitb14_pretrain.pth` and `~/.cache/torch/hub/facebookresearch_dinov2_main/` | `%USERPROFILE%\.cache\torch\hub\…` |

The libraries' own settings `HF_HOME` and `TORCH_HOME` move these folders
(from the libraries, not the product). They hold no photo data.

### 6. The product folder (measured)

- `.venv/`: written when you install (INSTALL step 4). One existing Mac
  `.venv` measured 0.9 GB; a fresh install was not measured.
- `scripts/__pycache__/`: Python's own compiled files. In the test run this
  was the ONLY thing written into the product folder.
- `*.egg-info/` beside `pyproject.toml`: may be written by `pip install -e`
  (from the code: `.gitignore`).

### 7. Other places (from the code)

- **Temporary files**: the exiftool argument list, preview conversions and
  onboarding thumbnails are made in the system's temporary folder and deleted
  when that step ends. None were left after the test run (measured).
- **A scheduled job**: only if you run `photo_schedule.py install` (macOS):
  one file in `~/Library/LaunchAgents/`, plus its runner, prompt, state and
  logs in `Working Files/schedule/`. Nothing is scheduled otherwise.
  `photo_schedule.py remove --go` takes the job away and keeps the logs.
- **`photo_recurrence.py`** (an optional census over a whole collection):
  `recurrence-census.json` and `photo-proposals-draft.md` in the folder you
  give it with `--out`.
- **pip's download cache**: written by pip during install, not by the product
  (macOS `~/Library/Caches/pip`; Windows `%LocalAppData%\pip\Cache`, not
  measured).

## What it never writes

- **The source photos are never changed.** Copy-only: no stage moves,
  renames or deletes a source file. In the test run every source file had the
  same SHA-256 before and after (measured).
- **The engine never deletes.** Trash, duplicates and sidecars are *proposed*
  for you to remove by hand.
- **The engine never writes owner facts into the product folder.** Homes,
  pets and words live in the pack; a run loads exactly one owner's pack and
  stops rather than falling back to somebody else's.
- **No photo file is uploaded by the product.** The only pictures that leave
  the machine are the vision-pass samples the agent looks at (below). Nothing
  is scheduled or synced unless you set it up.
- **No other place in your home folder.** A search of the code for writes
  under the home folder found only the scheduled job's file (section 7), and
  after the test run no product file was new under `~/.cache`,
  `~/Library/Caches` or the temporary folder (measured).

## What leaves your machine

Network calls the product makes itself (from the code):

| Call | When | What is sent |
|---|---|---|
| OpenStreetMap Nominatim (`nominatim.openstreetmap.org`) | naming places: `cluster` (also run by `prep`) and `photo_where.py`. `photo_index.py` reads the cache only | one position per batch or stop away from home, and per home day that has no label: the centre worked out from its photos, **rounded to 2 decimal places (about 1 km)** before it is sent, plus the owner's language. A day at a home with a label sends nothing. |
| OpenStreetMap Overpass (`overpass-api.de`) | `photo_where.py` only, for a stop in Taiwan (naming peaks and trails) | a box around the stop: the southernmost, westernmost, northernmost and easternmost photo positions, each widened by about 500 m, **not rounded**. Hike naming needs about 400 m, so this box is sent at full precision. `cluster`, `prep` and the index flow never send it |
| Nominatim, reachability only | `doctor` | no position, just a request to see that the service answers |
| model downloads (Hugging Face, PyTorch, GitHub) | first vision run only | nothing about your photos |

Every one of these requests carries the product's User-Agent
(`kcc-photo-manager`). Turning the geocoder off (`--no-geocode`) keeps names
to what the cache and the pack already know.

And the vision pass, below.

## Reminder — what leaves your machine, and how much

**One stage of this pipeline sends pictures to an external vision model: the
vision pass** (step 2 of `photo-run`), where the driving agent looks at the
`samples/` that `photo_see.py` selects. Everything else is local. `scan`, `cluster`, `plan`,
`execute` and `verify` read metadata and copy bytes on your own disk;
`photo_embed.py` runs a CLIP model **on your machine**, and
`photo_recurrence.py` / `photo_see.py` load no model at all. The memory pack
stores vectors, file paths and thumbnail paths — never uploaded copies.

So the only question that matters for privacy is: **which files does the
vision pass send, and how many?**

### How the count is decided

`photo_see.py` picks them. It does not sample randomly and it does not send
the whole batch. Per batch:

```
pool    = files whose preclass is `own` or `shared`
          (screenshots, screen recordings and no_exif files never enter —
           rules already decide those, so eyes would buy nothing)
budget  = round(pool x see_rate)          # see_rate: 0.10 first sort,
                                          #           0.05 a re-sort
budget  = clamp(budget, see_floor, see_cap)   # defaults 5 and 40
budget  = min(budget, pool)                   # never more than exists
```

The budget is then filled by priority, not by chance: one representative per
visual cluster first, then registry gray-zone matches, then embedding
outliers, then a diversity fill. Files the local CLIP model already matches
confidently spend **no** budget — they are labelled on your machine and never
sent.

### The floor is usually what sets the number, not the rate

This is the part worth reading twice. `see_rate` is 10%, but the **floor of 5
files per batch** overrides it on every small batch, and most real dumps are
mostly small batches.

| Batch pool | Budget | Share sent |
|---|---|---|
| 4 files | 4 (floor, capped at pool) | 100% |
| 20 files | 5 (floor beats 10% = 2) | 25% |
| 300 files | 30 | 10% |
| 1,000 files | 40 (cap) | 4% |

A collection made of many small batches can therefore send **a third of its
files** while the configured rate says 10%, and nothing is wrong. If that
number matters to you, read it off the `coverage` block of each
`see-report.json` **before** the agent looks at them — the selection is written to
disk first, and looking at a photo is a separate later step.

### If you want to send less

* lower `see_floor` — the biggest lever on a dump of small batches;
* lower `see_rate`, or run `--pass second_sort` (5%);
* lower `see_cap` to bound the worst case per batch;
* or stop after `photo_see.py` and label by hand. The pipeline still runs;
  it just has no model opinion to work with.

### Say it plainly

**These are personal photographs, and the selected ones are uploaded to a
third-party model provider** (Anthropic's API, when this is driven by Claude).
Downscaled previews, not originals — but they are still your pictures of your
home, your family and your pets, leaving your computer. That is a real
trade-off, not a formality: the folder names this engine produces are only as
good as what something was allowed to look at.

Nobody should discover this after the fact. Decide it before the first
vision pass, and if the answer is no, the local-only path above is a
supported way to use this tool.

## Delete it all

Nothing below touches your source photos.

1. **One collection:** delete its workspace folder. That removes
   `Working Files/` with every work dir, the caches, the samples and, if the
   pack is in its default place, the owner pack.
2. **An owner pack kept somewhere else:** delete `<memory root>/<owner>/`
   (the path is `memory_root` in `collection.json`).
3. **An onboarding sheet folder** you put outside the workspace: delete it.
4. **The sorted copies:** delete the destination folder (`dest_root`), or the
   folders in it you do not want. These are copies; the originals stay.
5. **The model weights:** delete the three entries in section 5.
6. **A scheduled job** (only if you installed one): run
   `photo_schedule.py remove --go` BEFORE deleting the workspace; it keeps
   its logs in `Working Files/schedule/logs/`.
7. **The product itself:** [INSTALL.md, step 7](INSTALL.md#7-uninstall).
