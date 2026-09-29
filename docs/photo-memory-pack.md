# The photo memory pack

The engine knows nothing about anybody. Everything personal — where someone
lives, who is in the photos, what their pets are called, which words they name
folders with — lives in a **pack**, outside this repo, one folder per **photo
owner**.

This document defines the layout, how a run is bound to exactly one pack, and
the snapshot id that makes a replay reproducible. The pack's *content* and the
learning loop that fills it are Phase C.

## Owner, operator, agent

Three different roles, deliberately named apart:

| Term | Who |
|---|---|
| **photo owner** | the person whose camera produced the photos — the memory is *about* them |
| **operator** | whoever is running the tool in a Claude session, who may not be the owner |
| **agent** | the model doing the work; it drafts memory, it never confirms it |

One operator may process several owners' dumps. The tool cannot verify who is
who and does not try — it records whether a fact was drafted or confirmed, and
on what evidence, not who someone claims to be.

## Layout

```
photo-memory/                     ← the memory root; you choose where this is
  juno/                           ← one folder per owner, named by slug
    photo-owner-juno.md           narrative anchor, loaded as vision context
    photo-profile.json            machine config  ← the only file Phase A reads
    photo-entities.json           people / pets / places / scenes + timelines
    photo-subjects/               subject registry: exemplar vectors (VS-3)
    photo-memory-log.md           append-only audit journal
    photo-proposals.md            agent drafts, not yet confirmed
  rowan/
    photo-owner-rowan.md
    …
```

Only the anchor file repeats the slug in its name — enough to identify it when
the file is opened alone or copied somewhere else, without repeating the owner
in every filename.

**Slug rule:** lowercase ASCII `[a-z0-9-]`. A name outside that set gets a
transliterated slug and keeps its real name inside the files: owner
`Renée Dubois` → folder `renee-dubois`, `photo-owner-renee-dubois.md`,
display name `Renée Dubois` within.

Create one with:

```bash
python3 scripts/photo_pack_init.py <memory_root> <slug> --display "Renée Dubois"
```

### Where to put the memory root

Wherever the owner's private notes already live. It is configuration, never a
path baked into the engine. The default — no configuration at all — is a
`photo-memory/` folder beside `collection.json`, so a new user needs nothing
installed and nothing decided.

The pack is **portable by design**: copy `photo-memory/<owner>/` to another
machine, or hand it to a different agent, and the tool knows the same owner.
Nothing in it is machine-bound. That portability is why the durable record
must stay plain files — a UI-only state store would break it.

## Binding a run to an owner

`collection.json` (the per-collection config written by `photo-init`) gains:

```json
{
  "collection": "juno-archive-2017-26",
  "owner": "juno",
  "memory_root": "/path/to/photo-memory"
}
```

`memory_root` is optional; it defaults to `photo-memory/` beside
`collection.json`.

Resolution order, highest first:

1. `--profile <path>` on any stage script — a pack folder, or the
   `photo-profile.json` inside one
2. the `PHOTO_PROFILE` environment variable — `photo_run.py` exports the
   resolved pack once, so every stage it shells out to inherits the same one
3. `collection.json → owner`, resolved under `memory_root`
4. nothing — the pipeline still runs, on the engine's generic defaults

Inspect what a run would load:

```bash
python3 scripts/photo_profile.py "<Working Files>/202605__"
```

## The isolation invariant

**One run loads exactly one owner's pack.** Two situations stop the run rather
than guess:

- a collection names an `owner` with no pack at `<memory_root>/<owner>/photo-profile.json`
- a `--profile` points into one owner's pack while `collection.json` names another

Neither falls back to whatever pack happens to be configured. Silently mixing
two people's photo memories is a worse outcome than a failed run, and it is
the kind of error nobody notices until the folder names are already wrong.

This extends the existing rule that every raw folder is its own collection
with no cross-collection dedupe.

## `photo-profile.json`

The only pack file the engine reads today. Keys, all optional:

| Key | Effect |
|---|---|
| `owner` | `{"slug", "display"}` |
| `language` | picks the folder names for engine-generated buckets (`photo_profile.BUCKET_VOCAB`); plan *prose* is still written in the legacy build-validation locale — see 4b/4c below |
| `screen_dims` | `[{"model": "<make model>", "dims": [w, h]}]` — the owner's own screen sizes, each paired with the device it belongs to (G-1). A no-camera still at exactly one of them is a screenshot; both orientations are matched. The unpaired `[[w, h]]` shape is still read, so no pack needs migrating — it just cannot be audited per device. **Moves files** — take these from `photo_census.py`, never from a phone-spec table |
| `im_long_edges` | `[<long edge>, …]` — the pixel long edges an instant messenger re-encodes a photo to (T3, A34a). An IM app does not merely strip EXIF, it re-encodes to a small fixed ladder, and that ladder is a fingerprint no camera produces. **Ships EMPTY**: the working values are measured from one owner's own corpus and a long edge is not a product constant, so an unmeasured pack simply has T3 off and a larger review inbox. ⛔ Applied to STILLS only — 720p video is 1280×720, which collides with a ladder value for reasons that have nothing to do with a messenger. **Moves files** |
| `im_name_prefixes` | `["LINE_", "IMG-", …]` — the filename signatures instant messengers write (T2, A34a). Unlike the ladder these ARE product facts, the same for every owner, so they ship with defaults; a pack only needs this key to add an app the engine does not know. `IMG-` is anchored to the WhatsApp `IMG-YYYYMMDD-WA####` form, because the bare prefix is too close to an ordinary camera name |
| `naming_spec.buckets` | override any bucket name individually: `{"screenshots", "to_be_checked", "others", "ai_images"}` |
| `own_camera_makes` | EXIF `Make` values that count as "shot on the owner's own device"; anything else is treated as forwarded/shared and filed by date. **Not** Apple-only — a Samsung collection zeroed the sampling budget until this became config |
| `home_locations` | `[{id, label, lat, lon, valid_from, valid_until, home_range}]` — **every entry is a never-name zone**, so put a place here only if it must never be named: `photo_where.py` suppresses any day whose GPS cluster falls within `--home-km` of one, on the coordinates alone, so a `label` is optional and is never needed to suppress. `valid_from` / `valid_until` (`YYYY`, `YYYY-MM` or `YYYY-MM-DD`) narrow that to a window; an absent bound is open-ended and is never inferred from the dump. A row with no readable `lat`/`lon` stops the run rather than being skipped. Take the coordinates from `photo_census.py`, which proposes them from the dump's own GPS and capture times; the owner supplies the `label` (city level). The census numbers each place on screen and keeps its coordinate in `census-places.txt` beside the manifest — never on screen — as a single pair: **split it into `lat` and `lon` when writing the row**, because a proposal copied whole has neither field and stops the run. ⛔ **Not the key for somewhere the owner merely visits often.** Membership is unconditional suppression and there is no per-row switch that can weaken it, so a frequent place put here becomes silently unnameable. A frequent place needs no key at all today: its coordinates are not sensitive, and it geocodes like anywhere else. `home_range: false` marks a residence that is NOT the owner's everyday range — a parent's house is the case it exists for. It narrows ONE thing: `photo_cluster.py` leaves it out when picking the home anchor, so days spent there read as a trip rather than as everyday life. ⛔ **It does not weaken suppression** — the row is still a never-name zone, and `photo_where.py` reads `home_locations` without the filter for exactly that reason. An absent `home_range` means `true`, so a pack written before the key keeps every home it had. ⛔ It is **not** a way to list a frequent place that is not a residence: that still belongs nowhere in this key, because membership still costs unconditional suppression. Other extra fields are ignored, so an older pack carrying `role` or `note` keeps working — nothing has ever read either. It proposes nothing on a thin or GPS-poor dump — that is an ordinary first run, and the answer is then typed at city level in the same question rather than deferred. `id` (`home-01`, `home-02`, …) is the home's fixed id (D-I15): an index refers to the home by it, never by the coordinate or the label, so renaming the label renames every folder that uses it. It is written by `photo_onboard_page.py apply --write-pack`; a row typed by hand gets one from `photo_onboard_page.py backfill-ids <pack>` (a dry run; `--go` writes a `.bak` first). Never invent one. `home_locations_next_id` is the next number to issue, so a deleted home's id is never issued again — an older dump's index may still point at it. A missing, shared or malformed id (a row letter such as `C` is not one) is warned about and reads as none; the backfill fills a missing one and never renumbers the others. ⛔ **Suppression never reads the id** — it is for naming and indexing only |
| `frequent_places` (in `photo-entities.json`) | `[{id, label, lat, lon}]` — a place the owner NAMED at onboarding that is **not** a residence (the answer `<name>` with no `live`/`visit`). Its label beats the map for any day within `cluster_defaults.named_place_km` (default 1 km) of it, and nothing about it is withheld: its coordinate is not sensitive (OA-23). ⛔ Never merged with `home_locations` — a named place never names a home stop. `id` (`fsl-0001`, …) and `frequent_places_next_id` follow the `home_locations` rules above. A row with no label or no readable coordinate is skipped, never a hard exit |
| `pets` | names and kinds, so a folder can say the animal's name instead of "dog" |
| `naming_spec.types` | the owner's own folder-type vocabulary; `photo_classify_set.py` validates against it |
| `cluster_defaults` | `away_km`, `jump_km`, `gap_days`, `max_batch` — plus `away_km_answered`, which is **provenance, not a threshold**. The template ships `away_km` at the engine's own 3 km, so the key's presence can no longer show that anybody chose it; set `away_km_answered: true` when writing the owner's answer, and every run that leaves it false says in `batches.json` and on stderr that its home range was never examined. A pack whose `away_km` simply differs from the shipped 3 counts as answered without the flag — nobody edits a number to the value it already had. ⭐ The flag's one writer is `photo_onboard_page.py apply --write-pack`; an owner who answers exactly **3** is the case it exists for, because that value is indistinguishable from the shipped one. |
| `sampling` | `gps_pct`, `no_gps_pct`, `min_samples`, `max_samples` |
| `legacy_dest_root`, `legacy_workdir_root` | fall-backs for collections predating `collection.json` |

A pack with none of these still works — the engine has a default for
everything except the destination root, which it refuses to guess.

## `photo-subjects/` — the subject registry (VS-3)

The visual half of a subject. `photo-entities.json` holds the facts a human
reads (`who`, `name`, `kind`, `active`); `photo-subjects/` holds the vectors
that recognise the same subject in a photograph. **They are one model, not
two**: both are keyed on `subject_id`, so a subject has exactly one identity
across the pack.

```
photo-subjects/
  subjects.json           the registry: one record per subject + its exemplar list
  vectors/
    subj-0001.npy         (N, D) float32, L2-normalised, row order == exemplars[]
  draft-vectors/
    subj-0007.npy         (D,)  one centroid per DRAFT subject (VS-4)
  memorize-audit.jsonl    every promotion attempt, accepted and refused (VS-4)
```

**`vectors/` and `draft-vectors/` are two different things and the separation
is load-bearing.** `vectors/` holds recognition evidence: a vector in there
was confirmed by a vision model looking at the file, and `match()` reads it.
`draft-vectors/` holds ONE centroid per unconfirmed draft subject, used for
exactly one purpose — recognising that the unnamed animal in batch 8 is the
same draft as the one in batch 1, so a human is asked once instead of eight
times. `match()` never reads it. A store that could not tell the two apart
would be one edit away from recognising subjects from a guess.

One subject record:

```json
{
  "subject_id": "subj-0001",
  "name": "Name-One",
  "who": "pet",
  "kind": "cat",
  "active": ["2029-03", "2031-08"],
  "forms_folder": null,
  "origin": {"candidate_id": "rc-0a1b2c3d4e5f", "census": "census-1"},
  "thresholds": {"accept": 0.82, "gray_low": 0.70, "timeline_tolerance_days": 45},
  "exemplars": [
    {"vec_ref": "sha256:9f86d081…", "source": "/raw/IMG_0001.HEIC",
     "added": "2031-02-14", "captured": "2029-03-04 10:02",
     "confirmed_by": "viewed-image"}
  ]
}
```

| Field | Meaning |
|---|---|
| `subject_id` | stable identity, `subj-NNNN`. The merge key for recurring-subject / D9 folders (naming SPEC **N-10a**), so a rename can never fork a folder. Assigned once and never reused |
| `name` / `who` / `kind` | the ONB-13 identity pair plus species, mirrored from `photo-entities.json`. `name` is a *display attribute* hanging off `subject_id`, never a key |
| `active` | `["YYYY-MM", "YYYY-MM"]`, either end `null` for open. Timeline gating (recognition Level 2) — a match is only *eligible* inside this range ± tolerance |
| `forms_folder` | `null` = derive it (see below); `false` = this subject never gets its own output folder. The naming carve-out's only input |
| `origin` | where the subject came from before it had a name — the recurrence census candidate it was drafted from. Lets a pre-checkpoint tree resolve afterwards |
| `previous_names` | every rendered name this subject has had. Names arrive after folders exist (**N-6**), so renaming is normal; this is the ledger that lets a tree sorted before a rename still resolve to the same folder |
| `thresholds` | per-subject override of the registry `defaults` |
| `exemplars` | up to `exemplar_cap` vectors, diversity-kept, each with its source, the date it was added, the date the photograph was taken, and the provenance that let it in |

**`added` and `captured` are two facts (SNS-10).** `added` is the day the
vector was promoted; `captured` is the day the photograph was taken, carried
whole from the see report. Retention keeps a *diverse* set rather than a
recent one so a subject's whole life stays recognisable, and no reader can
check that coverage against a promotion date. ⚠️ A file whose capture time is
unknown stores `captured: null` — never `added`, never today, never an mtime.
A missing date declares the gap; a substitute hides it. Packs written before
this carry no `captured` key at all, and readers treat absent and null alike.

**The memorize rule (anti-drift).** Only `confirmed_by: "viewed-image"` may
enter `exemplars`. A `clip-matched` or `clip-propagated` label is the
registry's own output, and letting output back in as evidence is how a
registry drifts on its own errors. `photo_subjects.py` rejects any other
provenance at the point of writing, not at review time.

**VS-4: the string is not the rule.** Until VS-4 that check was a string
comparison, so a caller holding a `clip-matched:` file and the correct
spelling was memorized. A promotion now also carries EVIDENCE — the see-report
that selected the file, the batch, and the thumbnail the model was shown — and
`photo_evidence.evidence_problems()` re-derives every part of it from disk
before the write. `draft:viewed-image:` (a real look at a file whose subject
is only a draft) is refused too: the look happened, what it was attributed to
is not confirmed.

Each exemplar therefore carries an `evidence` block:

```json
{"vec_ref": "sha256:9f86d081…", "source": "/raw/IMG_0001.HEIC",
 "added": "2031-02-14", "captured": "2029-03-04 10:02",
 "confirmed_by": "viewed-image",
 "evidence": {"see_report": "…/classify/batch-07/see-report.json", "batch": 7,
              "path": "/raw/IMG_0001.HEIC", "sample": "2031-02-14_1032_IMG_0001.jpg",
              "label": "Cat"}}
```

**`memorize-audit.jsonl` — one line per attempt, refusals included.** This is
what answers *"prove the registry only grew from vision-confirmed matches"*
without anyone having to be believed. A `memorized` line names what confirmed
it; a `refused` line names the `gate` that stopped it (`provenance`,
`evidence`, `subject`, `vector`, `unconfirmed`, `picked-ref`, and a
partition's `named` / `status` / `groups` / `frames` / `shared` /
`centroid` / `superseded`). It is appended
at the decision point, not at
save, so a run that crashes half way still leaves its trail.
`photo_subjects.py review` prints the tally and flags any exemplar with no
evidence block — a pack written before VS-4 will have some, and they are
honestly unprovable from the log rather than quietly counted as fine.

**Draft subjects.** A record with `status: ai-drafted` (or `ai-reinforced`) is
a subject the discovery loop noticed and nobody has named; its `exemplars`
list is empty, with one deliberate exception — a subject whose confirmation
was withdrawn keeps its evidence, frozen (see *Un-confirm* below). It may group files and propose a name carrying the `draft:`
prefix; it may never become recognition evidence. Extra fields on a draft:
`obs_count`, `observed_in` (batch numbers), `files`, `contact_sheet` (paths to
thumbnails a model really did look at), and `evidence` (one entry per batch).

Each `evidence` entry also carries `looks`: for every cluster member the see
controller actually selected, its `path`, `sample`, `vec_ref`, `see_report`,
`workdir` and the provenance the labels file APPLIED — read, never assumed.
That is the material `confirm` needs to promote exemplars once a human names
the subject; until then it is a list of files geometry attributed to a draft,
and nothing in it is evidence of anything.

**F14 — a confirmed subject stays recognisable.** `confirm` promotes those
looks through the same `add_exemplar()` gates (provenance read off the labels,
look re-derived from the see-report), reloading each vector from that dump's
own `embed/` index and refusing it if the file's `sha256` has moved since. A
subject that ends a confirm with no exemplar is reported loudly: nothing would
recognise it next dump, which is the defect this closes. From then on
`observe_draft_subject()` SUPPRESSES a matching cluster — no new draft, no
repeat question — recording the sighting on the confirmed record and writing
no name, no exemplar and no timeline. Suppression is not a merge: the engine
still never decides that two ids are one subject.

⚠️ **Promotion is per LOOK, and the caller says which ones.**
`photo_memory.attach_exemplars()` takes a required `only_refs` — the `vec_ref`s
of the frames the owner actually picked. There is no default and `None` is not
a sentinel for "everything": a caller that wants every look enumerates them,
in code anyone can read. Promoting a whole record on the strength of a few
frames is what made an impure cluster unrecoverable (**OA-15**), and a ref
naming no look in that subject's evidence is refused out loud rather than
skipped.

**R3a/R3b — what a frame on the page IS.**
The tile renders the **animal's crop**, not the whole photograph, and a frame
holding more than one animal says so on its own line. Both facts come from
`embed/identity.csv`, which since R3a carries **one row per detected animal**
(`det_index`, `det_count`) rather than one row per file; the crop is
re-derived through the same conversion `photo_identity` cropped and cached in
`<workdir>/review-crops/`.

⛔ A **shared** frame can still be picked and can still name its group — two
subjects in one frame is two names to log, never a frame to refuse — but it
**never becomes identity evidence**. The exemplar store keys on `vec_ref`,
the file's content sha: one photograph, one key, one subject, so there is no
key under which a two-cat frame could bank a clean vector for each. Without
the refusal whichever animal scored higher silently became both, which is
what put 3 wrong exemplars out of 5 into a fresh owner's pack in UAT01
(**D-24**, reproducing **OA-15**). The refusal is a holding position: banking
one crop per animal needs a composite key (`<sha>#<det_index>`) and is its
own card.

⚠️ Bounded to files in the work dir being reviewed. A confirmed subject's
sightings span dumps, and an earlier dump's index is not open here — those
frames render whole and carry no claim at all, because "no crop" and "no
animal" must never read the same.

**SNS-1b — the split, and the `superseded` status.**
`Registry.partition_subject()` answers the three partition cases for one
draft, decided by how many `pick:` rows claim its frames — **rows, never
coverage**, because frames no row picked are deferred and not a decision:

| rows | case | what is written |
|---|---|---|
| 1, this subject only | `in-place` | nothing — the id is kept and confirmed where it stands |
| 1, shared with other subjects | `shared` | nothing — every member keeps its id under one name |
| 2 or more | `split` | one child per row; the parent takes `status: superseded` and `split_into: [ids]` |

A child is minted as its own draft with its OWN first-sighting centroid,
computed by the caller from that row's frames and passed in — the parent's is
never recomputed and never reassigned. It inherits a restricted COPY of the
parent's evidence (its own looks only), the contact-sheet frames those looks
were shown on, and an `active` range derived from their own capture dates. It
does **not** inherit the file count: a split is proof the cluster was wrong,
so the files nobody looked at re-earn a name per file and until then render
the class word with `draft:` provenance. The parent keeps its full evidence
and its draft vector, as an audit record.

`superseded` sits outside BOTH status whitelists on purpose: outside
`is_draft` it leaves the question loop with no change to `build_questions()`,
and outside `human-confirmed` it recognises and suppresses nothing. What holds
that pair safe is that a superseded record carries **no name** — every reader
that renders one gates on the name, not on the status.

That is an invariant, not a single check, and it takes **three** refusals to
hold. `partition_subject()` refuses a parent that holds a name, and refuses
one that is not a draft (two confirmed subjects that turn out to be ONE is
SNS-14's fold, below; one that turns out to be TWO is still unbuilt — withdraw
the name first and the draft it becomes is partitionable);
`rename()` refuses a superseded record, because it otherwise writes a name on
any status; and `photo_memory.py confirm` refuses a superseded id on both its
naming and its `skip:` path, because a review file rendered **before** the
split still names the parent and still parses — SNS-1b item 1's pinned-pack
check is step 5, and `--go` only prints the snapshot today. A parent
confirmed through that door comes back as a recogniser holding the same looks
as its own children and competes with them in `match()`.

There is no un-split verb: `unconfirm()` refuses a superseded record rather
than returning it to the question loop beside the children that now hold its
frames. ⚠️ Deferred to step 5 for the owner's explicit sign-off — a split is
a one-way door today.

**Un-confirm — the withdrawal.** `photo_subjects.py review --unconfirm
subj-NNNN --go` takes back a confirmation: the subject returns to
`ai-drafted`, its name moves to `previous_names` (so folders already written
under it still resolve), its draft centroid stays on disk, and the pack log
gets an `un-confirmed` maturity line — the one token that re-opens a question
instead of closing it. The entities twin is updated in the same write.

**The evidence is kept, and frozen** (owner's decision, 2026-08-16). A
withdrawal does NOT remove the exemplars, because re-confirming has to stay
cheap:
`attach_exemplars()` re-derives every vector from the dump's own `embed/`
index, so a removal would be one-way as soon as that dump was cleaned away —
an owner who withdrew a name in one month could not get the recognition back
in another. Instead:

- **nothing is attributed.** Recognition is gated on STATUS, not on evidence:
  only a `human-confirmed` subject holding exemplars may put a name on a file
  (`Registry.recognisers`, used by `match()` and by the see stage's report).
- **nothing is gained.** `add_exemplar()` refuses a promotion onto a subject
  that is not `human-confirmed` — the labels already on disk say a bare
  `viewed-image:` truthfully, and they were earned under a yes that no longer
  exists.
- **re-confirming restores recognition immediately**, from evidence that was
  never thrown away, with no dump on disk and nothing to re-derive.

⚠️ Those two status tests are the whole safety of the verb. An "optimisation"
that puts either one back on the exemplar test hands a withdrawn identity its
files back silently — the vectors are real and the scores are good.

A work dir that already asked about this subject would go on suppressing it
until its evidence grew — and evidence is exactly what a subject named wrongly
and never photographed again can never gain. So a withdrawal also sets
`reopened` on the record, and `build_questions()` lets a flagged subject past
that bar (SNS-5). ⚠️ The flag is a QUESTION-LOOP flag, not history: it is
spent by the next answer, on both of `confirm`'s answer paths, so every
subject nobody withdrew keeps the bar it earned. `revive()` sets it for the
same reason.

**Rejected — the other permanent answer (OA-14 / OA-16).** A `skip:` row marks
a subject `rejected`: *never ask me about this again*. Four rules hold it
together, and they are one decision:

- **it holds no name.** `rejected` sits outside `is_draft`, so a name on it
  would render as a confirmed `who` with no `draft:` marker. Same invariant
  `superseded` needs, and it takes the same **three** refusals: `rename()`
  refuses a rejected record, `confirm`'s `skip:` path refuses to reject a
  CONFIRMED subject (the stale-review door — OA-16) and refuses any record
  that holds a name, and `add_exemplar()`'s third gate is now a whitelist of
  `human-confirmed` rather than a list of statuses to exclude.
- **it gains nothing and recognises nothing.** Exemplars frozen onto it by an
  earlier confirmation attribute no file — recognition is gated on status.
- **it keeps its draft centroid, and suppresses on it.** `rejected_match()`
  is why a rejection survives a dump boundary at all: before it, the record
  was in neither `drafts` nor `recognisers`, so the next dump opened a fresh
  id for the same subject and asked again. A retained centroid can stop a
  question and can never name a file.
- **it is revivable.** `photo_subjects.py review --revive subj-NNNN --go`
  returns the subject to `ai-drafted`, its centroid becomes a dedupe key
  again, and the pack log gets a `revived` maturity line — the second token
  that re-opens a question. A suppression this strong is never also
  unreachable.

Precedence when a new cluster matches more than one thing: a **confirmed**
subject wins (a confirmation names files; a rejection only declines to ask),
then a rejection wins **only if no live draft scores higher** — otherwise a
question the owner never answered would disappear into a rejection it merely
resembles.

**Thresholds are starting values, not tuned ones.** `accept: 0.82` /
`gray_low: 0.70` are the Visual-Sorting DESIGN's numbers, pending calibration
on a benchmark replay; `timeline_tolerance_days: 45`, `exemplar_cap: 24`,
`confirmed_suppress_tau: 0.85` (F14's bar for "this is a subject you have
already named", deliberately its own parameter and not the draft dedupe's or
`accept`'s — see `photo_subjects.py`) and `rejected_suppress_tau: 0.85`
(OA-14's bar for "this is a subject you told me to forget"; its own parameter
again, because it scores a fresh centroid against a first-sighting one where
`confirmed_suppress_tau` scores it against curated exemplars) and
`sweep_absorb_tau: 0.85` (SNS-15's bar for "this open draft is the subject you
just named"; its own parameter for the third time, because it scores a
first-sighting centroid against curated exemplars — neither neighbour's pair
of inputs) are the engine's own starting values.
They live in the pack so an owner can move them without touching the engine —
written down so the mechanism works, not derived from a measurement yet.
(`photo_see.RUNG1_BUDGET_SHARE` used to share this posture and no longer does:
it has been swept on the benchmark replay. These five have not.)

**Which subjects get their own folder** (the N-4 naming carve-out). With
`forms_folder: null` the engine derives it: a subject forms its own folder
when it has a confirmed `name` **and** a declared `active` start — which under
N-10a is exactly the set of recurring-subject / D9 folders where the name
replaces the routing class word. Nothing else is invented: an unnamed draft
subject groups files but never claims a folder, and an owner who does not want
one subject foldered sets `forms_folder: false`.

**Cardinality is never auto-resolved.** Two subjects that both clear `accept`
on the same file produce a *"one subject or two?"* question record with a
contact sheet. Nothing merges them. A wrong merge mislabels both subjects
forever and silently; a wrong split costs one question. For two lookalike
*clusters* — neither of them a named subject yet — **F16 stopped asking the
engine's question entirely**: they are two numbered tiles inside the one
question their kind gets, and SNS-1 carried that one step further — the owner
answers in FRAMES, so splitting one tile and joining two are the same gesture.
See *The question, and the frame as the unit* below.

**F15 — a cardinality answer settles cardinality, not identity.** The answer
to *"one subject or two?"* is logged with maturity `human-answered`, which
layer 3 does not read as settled, and it is written onto every member's
record. It used to be logged as `human-confirmed`, and layer 3 read the first
id on that line as closed forever: one of the two members was never asked
about again although nobody had named it, and nothing in the pack said so.
Conversely, a naming answer now settles EVERY member id it was given — the
name, the relation, the entities record and the exemplars, per member — and
puts all of them on the maturity line where layer 3 reads them. The members
keep their own `subject_id`s and share one name; the human-attested merge
that collapses them is its own verb, and the engine still never decides that
two ids are one subject.

Review the store with:

```bash
python3 scripts/photo_subjects.py review                  # from a collection
                                                          # workspace
python3 scripts/photo_subjects.py review <work dir>
python3 scripts/photo_subjects.py review --profile <pack> --prune --go
```

⛔ The positional is a **work dir or a workspace, never a pack path** — a pack
goes to `--profile`. All three binding routes reach this stage: `--profile`,
`$PHOTO_PROFILE`, and `collection.json` (found from the work dir you name, or
from the workspace folder you are standing in). Off a workspace with nothing
bound it refuses rather than guessing an owner.

**SNS-14 — the fold, and the `merged-into` alias.** Two subjects the owner
confirmed in different rounds under different names, and has since realised
are one. There is no separate merge verb: the case always arrives as a typed
name that is already taken, so it extends the collision ask (SNS-7). The owner
answers it with the armed token `same`:

```
- `pick:` 3,5   `who:` pet   `name:` <the other subject's name> same
```

`same` is the mirror of `distinct` — one grammar, one question, two opposite
answers — and both are stripped at the parser so no write site ever sees a
token inside a name. `Registry.fold_subjects()` then:

- gives the **earlier `subject_id`** the win (lower ordinal). ⛔ Never the one
  with more exemplars: that re-decides itself every time the cap evicts, and
  the lower id is the one already sitting in plan CSVs and folder records;
- **concatenates the exemplars and then applies `_enforce_cap()`** — never
  re-adds them through `add_exemplar()`, which would refuse every look whose
  work-dir artifacts have since been cleaned away and silently thin a set a
  human blessed;
- leaves the loser as an **alias tombstone**: `status: merged-into`,
  `merged_into: <winner>`, exemplars emptied, its vectors file removed at
  `save()`, and **no name** — the names it held move to the winner's
  `previous_names`, so `rename_ledger()` resolves every folder ever written
  under them. N-10a holds across the fold;
- **unions the `active` ranges** as intervals, so the fold can widen a
  timeline and never narrow one. That is the one fact it widens, and it is
  legal because a human attested it;
- moves the loser's `absorbed_drafts` rows to the winner and re-points their
  children, so `release_absorbed()` can still reach them after a withdrawal;
- **compresses the chain**: folding B into C re-points every tombstone that
  named B, so no tombstone ever points at a tombstone.

⛔ **Folders on disk under a retired name stay exactly where they are** — this
engine is copy-only. `confirm` prints one advisory naming them and moves
nothing.

The **entities twin follows**: `confirm` drops each alias from
`photo-entities.json` and re-writes the winner, so the file a human reads
never asserts two identities where the registry holds one. ⚠️ `--sync` cannot
repair that after the fact — its loop only adds and updates.

A `same` row **promotes nothing**. It is the only `pick:` row that resolves
its frames and then offers none of them to `attach_exemplars()`, deliberately:
the fold concatenates the two exemplar sets directly, and re-gating them would
refuse every look whose work-dir artifacts have since been cleaned away.

`Registry.get()` **follows** `merged_into`, which is what lets
`photo_plan.visual_columns()` resolve an id off an old see-label to the
winner's current name with no change of its own. Everything that branches on a
status or writes to a record uses `get_literal()` instead, and says so at the
call site — a refusal aimed at a dead id must never land on a live one.
`rename()`, `unconfirm()`, `revive()`, `add_exemplar()`, `confirm`'s member
loop and `confirm`'s `skip:` path each refuse a tombstone by name.

There is **no un-fold verb**. The two exemplar sets were concatenated and the
cap has since evicted across both, so nothing knows which look came from
where; `unconfirm()` on the winner withdraws the whole folded subject, and
says so.

**`rename_ledger()` resolves by a stated precedence, never by list order.** A
name can be claimed by more than one record — a current `name` and another
record's `previous_names`. Three tiers, lowest wins: a current name beats a
former one; a live record (`ai-drafted` / `ai-reinforced` / `human-confirmed`)
beats a dead one; then the lower `subject_id`. A tombstone is judged on the
record it resolves to. Before this the last writer in the file won, so a
folder's name could resolve to a superseded, rejected or absorbed id purely on
iteration order.

## The confirm checkpoint — `photo_memory.py` (VS-4 / Phase C)

The only gate that promotes an `ai-drafted` fact to `human-confirmed`. Plan
approval promotes nothing.

```bash
python3 scripts/photo_memory.py review  "<work dir>"                    # write the table
python3 scripts/photo_memory.py review  "<work dir>" --final             # ...the dump's last checkpoint
                                                                        # (photo_run.py finish --go does this for you)
python3 scripts/photo_memory.py confirm "<work dir>" --checkpoint 1 --go  # parse it back
python3 scripts/photo_memory.py confirm "<work dir>" --sync --go          # pair registry -> entities
```

`review` writes `<work dir>/memory-review_C<N>.md` and **nothing else**. It
never writes the pack: `photo-subjects/`, `photo-entities.json` and
`photo-proposals.md` are all in the snapshot, so a review that wrote into any
of them would move the snapshot id and make a checkpoint replay unprovable.
The table carries no wall-clock time either — two runs over one pack and one
work dir are byte-identical, and the header pins the snapshot each ran under.

`confirm` writes the pack: registry status and name, the matching
`photo-entities.json` record under the SAME `subject_id`, a line in
`photo-memory-log.md`, and a refreshed drafts block in `photo-proposals.md`.
It is a dry run without `--go`.

**One subject spanning K batches is ONE question**, held by three layers with
three different scopes — the difference matters and is not a detail:

| Layer | Mechanism | Scope |
|---|---|---|
| 1 | the draft centroid store — a re-observed cluster bumps `obs_count` instead of forking a second draft | the pack, so every run |
| 2 | the previous `memory-review_C*.md` files, compared on **each member's OWN `obs_count`**, never the block's sum (F16) | **one work dir only** |
| 3 | `photo-memory-log.md`, which carries `human-confirmed` and `rejected` — **all** the subject ids on the line, not the first (F15) | every run, forever |
| 4 | the exemplar store — a cluster that matches a confirmed subject opens no draft at all (F14) | every run, forever |

Layer 4 is what makes layers 1-3 mean anything across dumps: they all key on
`subject_id`, and before F14 a confirmed subject had no way to be recognised
again, so the next dump's photographs of it arrived as a NEW id that no layer
had ever heard of. Answering the question did not stop the question.

So a subject that was *answered* or *rejected* never returns anywhere, but a
subject that was **asked and skipped** in one dump WILL be asked again in the
next dump's work dir: layer 3 records nothing for it by design (skipping is
free and changes no fact), and layer 2 cannot see another work dir. Whether
that is right depends on your reading of *"returns only if new evidence
appears"* — `obs_count` will indeed have grown. It is recorded here so nobody
reads "three layers" as "never twice, anywhere".

⛔ And layer 1 does not yet hold on real data at all — see the measured
finding in `tests/memorize_replay.py`.

**Every round is also the way back (SNS-5).** All four layers above are
one-way doors on their own, so the table has a second half that no question
appears in: every `human-confirmed` and every `rejected` record in the pack is
re-presented, **unconditionally** — not gated on `settled_subjects()`, not on
`asked_before()`, not on new evidence. An evidence-gated re-presentation
preserves the one hole it exists to close.

- A remembered subject shows `{frames_per_reconfirmation}` frames (its own
  budget, 1-2 — a name check, not the identity judgement
  `{contact_frames_per_draft}` is sized for) and the frame shown is the
  **worst-scoring** sighting, max cosine against its own exemplars (SNS-6).
  Its best frame looks right every round even when the record has absorbed a
  second animal. ⚠️ The score is printed because it SATURATES at 1.000 right
  after a confirm, when every look is also an exemplar; the check sharpens as
  the subject is seen again. When a score cannot be computed — the dump was
  cleaned away, the file was re-embedded, the subject holds no exemplar — the
  page says so and the frames are labelled as the record's own order. There is
  no fallback to a frame that happens to look good.
- A rejection shows **no frames at all**: it is a question the owner closed,
  and re-showing its photos is asking it again. One line — id, evidence, the
  date — in its own section, plus the row that takes it back. A rejection with
  no retained centroid says so on its line.
- ⛔ A re-presentation **promotes nothing**. Re-confirmation promotes only the
  frames the owner picked, and a re-presented frame carries a NUMBER but no
  `frames:` entry — so there is no map for a promotion to travel through.

The rows are `recheck:` — the id is machine plumbing, the owner sees the
name. Blank is the default and writes nothing. `withdraw` routes to
`unconfirm()`, `revive` to `revive()`; both are reversible, both write their
clearing token to the pack log. ⛔ `reject` is parsed and **refused out
loud**: a rejection may never be written onto a record that still holds a
name, and a re-presented subject holds one by definition, so the gesture is
withdraw-then-reject however fresh the page is. The refusal names
`--unconfirm` and the `skip:` row that finishes the job. ⚠️ SNS-8's fold is
BUILT: these rows draw their frame numbers from the same sequence the
questions use, so the owner never meets two frame 1s.

**A `recheck:` row also takes a NAME, and that is SNS-14's only door.** A
confirmed subject never appears on a `pick:` row — the question loop tiles
drafts — so this is the one row where a remembered subject's name can be
corrected, and therefore the one row where *"renaming A to B's name"* can
happen at all. Six shapes, one row, one answer:

| Typed on the row | What it does |
|---|---|
| the blank, untouched | nothing. Silence is still yes, and yes writes nothing |
| `withdraw` / `revive` | the gestures above, unchanged |
| a name | renames that subject. The key does not move (N-10a); the old name lands in `previous_names`, so folders already on disk resolve through the rename ledger and nothing is moved |
| a name + `same` | the name is held by another confirmed subject and this is the same one → **the fold** (SNS-14) |
| a name + `distinct` | the name is held by another confirmed subject and they are genuinely two → both keep the name, nothing folds |
| a name AND a gesture | **refused whole** — one row is one answer |

A typed name that another `human-confirmed` subject already holds raises
SNS-7's collision ask, in **the same words** the `pick:` row raises it in —
one helper, two doors, because it is one mistake. Only the syntax of the way
on differs, since the two answers are typed on different rows. ⛔ A name that
happens to contain `withdraw`, `revive` or `reject` parses as name-plus-gesture
and bounces; the refusal says so, because a name silently read as a withdrawal
is the worse failure. ⛔ And a `recheck:` row **promotes zero exemplars on
every branch** — a rename is not new evidence, and the fold moves only what the
two records already held.

### When a round fires, and why it says so (SNS-4)

A **round** is one SNS question block. A **checkpoint** is the `review` cadence
above; they are not the same thing, and `review` decides at each checkpoint
whether a round belongs on the page.

The engine decides — the evidence is the registry's and the work dir's, so
handing the choice outward would ask a caller to judge something it cannot
see. ⛔ Which is also why the cadence is **not** in `photo_run.py`. What the
caller supplies is one fact: `review --final` says this is the last checkpoint
of the dump.

**And that fact now has a caller.** `photo_run.py finish --go` runs
`photo_memory.py review <work dir> --final` after the plans and the no-date
plan, because that is where a dump ends. ⛔ `--go` only — `rounds_fired()`
counts review files carrying a question block, so a dry run writing one would
spend the budget on a round the owner never saw. A dump with no owner pack
skips it out loud and `finish`'s exit code does not change either way; nothing
that was copied depends on the page. ⛔ No floor, no cap and no round counting
live in the conductor: it passes one fact and no decision.

⚠️ **One guaranteed round per DUMP, not per run.** `finish --go` is
re-runnable — a plan whose batches are already done is skipped — so the
conductor says *the dump is over* every time it runs. A second `--final` over
a work dir that has already asked its guaranteed round is therefore **demoted
to an ordinary checkpoint** and judged on the floor and the budget like any
other; without that, three re-runs would spend three of the four rounds in
`{sns_rounds_per_dump}` and every later floor-triggered round would be
withheld against a budget the owner never saw spent. The demotion is a cadence
decision and lives in `sns_round()` with the rest of them; it reads an ASCII
`<!-- sns-round: final -->` marker off the pages themselves
(`final_round_asked()`), never a counter, and never the printed reason — that
sentence is in the owner's language. It is said on the operator's console
only.

| Trigger | Behaviour |
|---|---|
| `memory.new_fss_floor` (3) newly-discovered frequently-seen subjects since the last round | the round fires, and is charged against the budget |
| `--final` | the round fires **whether or not** the floor was reached, and is **not** charged. Without the exemption a dump that spent its budget early would strand every subject that became frequent late. **Once per dump** — a later `--final` over a work dir that already asked it is demoted to an ordinary checkpoint |
| below the floor, or `memory.sns_rounds_per_dump` (4) rounds already asked | **withheld** — a UX budget, not a ceiling |

Every outcome is **printed**, on the page in the owner's language and on the
console in the operator's: which trigger fired, or which of the two reasons
withheld it, and the round number against the budget. A round that interrupts
without saying why is the behaviour this decision exists to bound, and a
checkpoint that withholds one silently is worse. Both numbers are starting
values in the `{n}` sense and move on a measurement, not on an argument.

⛔ A withheld round renders **no question block at all** — not the tiles and
not the `subjects:` / `obs_count:` / `frames:` lines under them. `asked_before()`
reads every review file in the work dir, so a page that printed the map
without asking would book those drafts into layer 2 and bury them behind a bar
they never earned. They are reported as suppressed, in the words that say they
are still open. The re-presentation section is withheld with the round for the
same reason; the guaranteed final round is what bounds the wait.

### The post-confirm sweep (SNS-15)

`confirmed_match()` is consulted for **incoming** clusters only, so nothing
ever re-scored the drafts already on the books: one animal in dozens of draft
records was named once and the rest came back at every later checkpoint, each
one now colliding with the name that had just been typed.

So `confirm --go` sweeps once, after every block is applied and every exemplar
attached, before `registry.save()` — the one moment the new exemplars and the
old drafts are in the same process. Every remaining draft is scored (its
retained first-sighting centroid against the new exemplars, max cosine, same
kind only) and above `defaults.sweep_absorb_tau` it is **absorbed**: `status:
absorbed`, `absorbed_by`, `absorbed_at_score`, one aggregate log line.

⚠️ **Its own threshold, 0.85, and never a reuse of `confirmed_suppress_tau`** —
that one scores a *fresh* cluster centroid, this one a possibly year-old
first-sighting centroid, and those sit systematically lower.

**The counts aggregate at DISPLAY time, never in storage** (the owner's
decision, 2026-08-19). The winner keeps a reversible `absorbed_drafts` list
and its own `files` untouched; `Registry.display_files(subject)` adds the
subject's own count, every absorbed draft's, and every folded-in tombstone's
on the way out. 20 + 8 reads as 28, and `release_absorbed()` takes it back to
20 — which a stored sum could never do, because nothing could separate it
again from the files that were always the subject's. The re-presentation's
remembered line and the sort key above it both read that number, so the order
the owner reads matches the magnitudes beside it; `review_remembered_line`
keeps the `{files}` argument it always had. Draft and rejection rows need no
sum of their own: only a `human-confirmed` record can carry `absorbed_drafts`
or be a fold's winner. `photo_subjects.py review` prints the breakdown —
`files N = own + absorbed + folded` — for whoever has to check a count.

What absorption may write is the whole of its legality: **no name, no
exemplar, no timeline, no contact sheet.** It declines to ask a question whose
answer the owner already gave (F14's suppression argument exactly), and an
absorbed draft's files still render the class word with `draft:` provenance
until they match exemplars at the `accept` bar. Because nothing was written it
is cheaply reversible, and the reversal is built: `unconfirm()` **releases**
every draft absorbed under the withdrawn name back to `ai-drafted`, flagged so
the work dir that already asked cannot hold it shut. `absorbed` is deliberately
not one of `settled_subjects()`'s maturity tokens, so the log layer holds
nothing the release cannot reach.

**ONB-13**: `who` and `name` are one answer, and that holds **per `pick:`
row** — one bad row is refused on its own, never quietly taking the
rows beside it with it. `confirm` refuses a half answer rather than writing
half a subject. ⛔ **There is NO cap on how many subjects may be remembered**
(SNS-9). The `{10}` budget that used to be refused here — at the one place a
name is written — was protecting a context cost that does not exist: no
remembered subject ever reaches a prompt, identification is numpy over `.npy`
rows, and the classify path resolves a name by registry lookup at write time.
What is left is a **soft warning** at `defaults.named_subjects_warn_at` (50),
which counts distinct names, says the count out loud and refuses nothing — it
exists so a clustering bug minting names nobody typed can be noticed. A pack
still carrying `named_subject_budget` is told that the key is no longer read.

The table's sentences come from `photo_profile.review_messages()` — English by
default, overridable per owner through `review_messages` in
`photo-profile.json`. The FIELD KEYS a human types into (`pick:`, `who:`,
`name:`, `skip:`, plus `group:` and `answer:` in tables written before SNS)
are ASCII and are never translated; so are the two armed tokens — `confirm` on
a `skip:` row, `distinct` after a colliding name. Hints sit in HTML comments
so a translated sentence can never be parsed as an answer.

### The question, and the frame as the unit (SNS-1)

One question per `kind`, not one per subject and not one per batch. That kind's
unsettled drafts are rendered as numbered tiles, ranked by blast radius, and
the owner supplies the cardinality the engine refuses to guess:

```
**Q1 · Group it — cat** — affects 20 file(s) / 4 batch(es) · 2029-01 → 2029-04
> 3 group(s) of photos look like a cat. How many cat(s) is this, and what do
> you call each one?
> **1** · an unnamed cat · 9 file(s) / 2 batch(es)
> ![](classify/batch-01/samples/…) [frame 1]
> …
> **Effect if answered:** …
> `subjects:` 1=subj-0001, 2=subj-0002, 3=subj-0003
> `obs_count:` 1=3, 2=1, 3=1
> `frames:` 1=subj-0001 9b1c2d3e4f5a classify/batch-01/samples/…, 2=…
> - `pick:` 1,4   `who:` pet   `name:` ______
> - `pick:` ______   `who:` ______   `name:` ______
> - `skip:` ______
```

⭐ **The TILE is display; the FRAME is the unit.** Tiles group photographs so
the owner can see what the engine thinks belongs together. `pick:` takes
frame numbers and does both jobs the old tile-level `group:` could not:
frames from inside one tile **split** it, frames from different tiles
**join** them. `skip:` reads the same numbering, and a frame on both rows is
a contradiction that refuses both.

Two maps, both written down and both parsed back, never inferred from list
order:

- `subjects:` — **tile number → `subject_id`**;
- `frames:` — **global frame number → (`subject_id`, short `vec_ref`, path)**.
  This is the one promotion is gated on. The short ref is the first 12 hex of
  the content sha, with the full sha used for any two frames on a page that
  would otherwise share it, and at confirm it resolves against **that
  subject's own** evidence looks. ⛔ Never re-derived from `contact_sheet[:n]`
  at confirm time: `observe_draft_subject()` appends to that list between the
  render and the answer, so a map rebuilt then is not fragile, it is wrong.

Frame numbers run through the WHOLE page, re-presented subjects included
(SNS-8), so the owner can address the subject whose *name* is the thing being
corrected. A re-presented frame gets a number and no `frames:` entry, which
is what makes "a re-presentation promotes nothing" structural.

⚠️ **A frame leaves the answer in one of THREE states, and they are not the
same word.** Collapsing any two of them is the F15 class of silent
suppression:

| Outcome | How the owner says it | What is written |
|---|---|---|
| **picked** | on a `pick:` row with `who` + `name` | `human-confirmed`, **only the picked frames** become exemplars, never asked again |
| **deferred** | left out of every row | **nothing.** Stays `ai-drafted`, keeps proposing `draft:` names, returns at a later checkpoint once its evidence grew |
| **`skip:`** | its number on the `skip:` row, plus the word `confirm` | `rejected` — never asked again, in any run |

**Silence is never rejection.** Answering three of eight frames must not
retire the other five. A draft the engine did not RENDER is deferred too, and
is not recorded as asked at all — booking it into layer 2 would bury it behind
a bar it never earned.

**What a split does in storage (SNS-1b).** Two `pick:` rows naming frames of
one draft supersede it into one child per row, each on a centroid computed
from **its own** frames — ⛔ never the parent's, which is a first sighting of
the grouping the split just disproved. The parent keeps its vector for audit,
holds no name, and leaves the question loop for free because `is_draft` is a
status whitelist. Its unseen files inherit nothing and re-earn a name per
file. A `skip:` over SOME of a subject's frames is the same surgery: the
skipped frames become their own child and that child is rejected, while the
frames the owner left alone get a child of their own and go on being asked
about.

**A colliding name asks (SNS-7).** Typing a name a confirmed subject already
holds refuses the row and names three ways on — a different name, an armed
`name: <name> distinct` for a separate subject that shares it, or leaving the
frames unpicked because it really is the same subject and folding two
remembered subjects is not built. ⛔ Never merged on the string match: a name
is not an identity (N-10a) and it is in whatever language the owner chose.

**The page pins the pack it was rendered against**, and `confirm` refuses a
review whose pinned snapshot no longer matches — WHOLE, not per row, because
what has gone stale is the page's coordinate system rather than one answer on
it. A page written before SNS carries no `frames:` line at all; its `group:`
and numeric `skip:` rows parse and are refused, with the one cheap command
that fixes them (`photo_memory.py review`) named in the refusal.

Two `{n}` parameters live in the registry's `defaults`, and **neither is
signed off** — they are starting values with their reasons written beside them
in `photo_subjects.DEFAULT_THRESHOLDS`:

| Key | Default | Why |
|---|---|---|
| `contact_frames_per_draft` | 5 | how many example frames a tile carries. The SPEC calls the shipped 3 "probably too few" — C moves the cardinality judgement onto these thumbnails — and the TEMPLATE's worked example shows 5 |
| `named_subjects_warn_at` | 50 | when the confirm checkpoint starts saying how many names the pack holds. **A warning, never a cap** (SNS-9) |
| `drafts_rendered_per_question` | 12 | how many tiles one question renders. A class with 200 drafts is not one readable question; the rest **defer**. It bounds question size; it is not a bound on how many names the pack may hold, because there is none |
| `names_per_folder` | 3 | N-9's cap on how many names one folder name may LIST. ⛔ Not a cap on remembering — `named_subjects_warn_at` above is that question, and the two move for different reasons. `[who]` is a repeatable slot and is **never capped at one**; past this cap the plan CSV renders a collective noun rather than truncating the list, because three names on a folder of five animals is a complete, well-formed, false statement about it |

Beyond `names_per_folder` the collective noun itself is a `review_messages`
string, `review_who_many` (`"{kind}s"` in English, over the class word).
English pluralises with an `s` and most languages do not, which is why it is
an overridable format string rather than a rule in the renderer: a pack whose
language has no plural sets it to `"{kind}"` and loses nothing.

## Owner-shaped facts that were baked into the engine

Phase A moved the destination paths, home locations, camera makes, thresholds
and the naming vocabulary out, and left four owner-shaped facts in the code on
purpose: each changed shipped output, and Phase A's job was to build the
harness that judges such changes, not to slip them in underneath it.

Three were dealt with once that harness existed, on the owner's decision
against the baked-in-behaviours proposal.

### 1. Screenshot detection — FIXED

Was one hardcoded iPhone 12 screen size, so screenshots from any other phone
were missed (Group 6, Samsung JPEG screenshots). Now two complementary rules:

<!-- i18n-guard:allow-begin — locale detection data: these are the literal
     filename prefixes the engine matches on INPUT, not text it writes. -->
- **filename** (`Screenshot_*`, `Screen_Recording_*`, `螢幕擷取…`, `截圖…`,
  `스크린샷…`, plus no camera tags) — Android names its screenshots, and the
  name is the only signal that survives **cropping**. Of the 4 real Android
  screenshots in the reference archive, 2 had been cropped away from any
  screen size.
<!-- i18n-guard:allow-end -->
- **`profile.screen_dims`** — the owner's own screen sizes, proposed by
  `photo_census.py`, confirmed by a human, and each paired with the device it
  belongs to (G-1) so it can be audited and re-proposed per device. iOS needs
  this one: an iPhone screenshot is `IMG_1234.PNG`, indistinguishable by name.

The engine's fallback is still the single iPhone 12 size, deliberately. A
generous built-in table is worse than none: `1080×1920` is both a phone screen
and the commonest video resolution there is, and on the Group 3 fixture
accepting it would have called **326 ordinary videos** screen recordings.
Screen sizes are an owner fact, not a guessable constant — so `photo_census.py`
never proposes a size it also sees on a video, and says why.

### 2. `route()` ran without the profile — FIXED

`photo_plan.route()` called `preclassify(row)` with no profile, so at plan
stage `own_camera_makes` fell back to Apple: on a Samsung collection **5,239 of
7,362 rows** (71%) described the owner's own photos with the engine's
"not shot on this device" shared note.
Nothing was ever misfiled — the label is cosmetic at plan stage — but the
document describing the collection was wrong.

Fixed by resolving the pack once in `main()` and passing it into `route()` and
`write_no_date_plan()`. The harness proves the blast radius rather than
asserting it: `tests/waivers.py` replays the shipped plan forward and must
account for **exactly 5,239** rows, every one a file whose `Make` the pack
calls the owner's own. Files that read `shared` for the *other* reason (a
random-name chat-app or AirDrop save with no camera tags at all) still do.

### 3. `naming_spec.types` is a hard gate with no drift detector — OPEN

A word in use but absent from the pack is rejected the moment somebody
classifies with it — one real pack's list was missing the `dog` type, which
24 batches used.
`python3 scripts/photo_profile.py <workdir>` warns when a scanned dump uses
vocabulary the pack lacks, but nothing enforces it. Becomes moot once Phase C
proposes vocabulary through the memory confirm gate.

### 4. Plan documents ignore `profile.language` — PARTLY FIXED

Split into three, because the parts carry very different risk:

- **4a. Bucket folder NAMES — FIXED.** The four bucket names (screenshots /
  to-be-checked / others / AI-images) were hardcoded in one language, so a
  first-time owner in any other language got that language's folders. Now `photo_profile.buckets()`: `naming_spec.buckets` → the table
  for `profile.language` → the strings the engine has always shipped. A pack
  made from the template says `"language": "en"`, so a **new** owner and **no**
  owner are deliberately different cases: an unbound run keeps producing
  exactly what it produced yesterday, which is why this was 0-diff on all four
  golden dumps by construction.
- **4b. The note COLUMN — OPEN.** Harness-compared on all 13,208 rows. Needs
  stable note codes plus a string table that renders the legacy locale
  byte-identically, or every row moves. Phase E.
- **4c. Plan `.md` prose — OPEN.** Not harness-compared. Free to template;
  largest text volume, lowest risk. Phase E. So an English-speaking owner today
  gets English folder names with legacy-locale prose around them — known,
  parked, and not a new regression.

## Pack snapshot id

`photo_run.py status` records in `status.json`:

```json
"pack_snapshot": {"owner": "juno", "id": "sha256:1a2b3c…", "files": 5}
```

A SHA-256 over every pack file that can steer a run — `photo-profile.json`,
`photo-entities.json`, `photo-proposals.md`, the anchor file, and
`photo-subjects/`. `photo-memory-log.md` is excluded on purpose: it is an
audit trail and never feeds a decision.

This exists because from Phase C memory mutates **between batches**, so a
run's output depends on the memory state *and* the batch order. Without a
pinned snapshot the golden-dump harness is not deterministic — and that
harness is the prerequisite for every later phase. Two runs that report the
same snapshot id stood on the same memory.

## What may never happen

- an `ai-drafted` fact becoming a Visual Sorting exemplar — a memorized
  exemplar requires a vision confirmation, or the registry drifts on its own
  errors
- an `ai-drafted` fact entering `photo-entities.json` as confirmed
- a **plan approval** promoting anything: plan review is about folders, the
  memory checkpoint is about facts, and neither leaks into the other
- a rejected fact being proposed again
- any pack file, or any owner fact, being committed to this repo
