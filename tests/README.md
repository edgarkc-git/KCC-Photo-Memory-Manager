# Tests

| Suite | Answers |
|---|---|
| `golden_replay.py` | does the engine still produce the plans that were actually copied to the drive? |
| `golden_replay_cases.py` | the harness's own fixture root: does the default still resolve to `tests/golden`, does `--fixtures` beat `$PHOTO_GOLDEN_FIXTURES`, and does a root with nothing in it exit **2** instead of reporting success over zero dumps? |
| `fresh_owner_smoke.py` | does it run for an owner it has never seen, with none of one particular person's facts? |
| `preclassify_cases.py` | do the EXIF rules **fire** — the positive control a frozen dump cannot give |
| `photo_execute_cases.py` | the stage that actually writes to the drive, which had no suite at all until A26: does a first-ever run — the one where `dest_root` has never been created — survive the free-space check instead of raising a traceback, does `--go` create the root and land every byte, and are the sources still untouched afterwards (D2)? |
| `photo_plan_cases.py` | the plan stage's two blind spots: the order `route()` tries its branches in — does an `overrides` date still let the screenshot, unreadable-format and G-2 classifiers decide first (LL-PHO-96)? — and `visual_columns()`'s registry branch, where WHO is resolved at write time from a subject registry no golden fixture has |
| `onb_cases.py` | the onboarding checkpoint: does the census propose what it should, does a pre-G-1 pack still work, and does a screen size spotted mid-run reach the report without blocking the run? |
| `settings_cases.py` | SET-1: does `photo_settings.py` report the layer a value really came from, refuse a below-floor classify model and an edit to embed coverage, and stay out of everything that is not the pack? |
| `schedule_cases.py` | SET-3: is the HIL-stop rule **enforced** rather than described — no `--go` in the rendered runner, and `photo_execute.py` absent from the allowlist the 3am run gets — is the classify model pinned through `photo_settings`' own floor rather than a second copy of it, and does a dry run really write nothing? |
| `i18n_cases.py` | is language really a variable — and does an unbound run still produce the legacy strings? |
| `photo_where_cases.py` | the residence-privacy rule (OA-22): does a home in the pack's `home_locations` ever reach a name? |
| `photo_cluster_cases.py` | the home anchor (R2-F3): does a work dir holding one trip still anchor on itself and call the trip everyday life — and does `home_range: false` narrow the batch label without ever narrowing suppression? Since A24 also the shared GPS predicate: do `photo_scan`, `photo_cluster` and `photo_census` give one answer about null island? Since A7 also the unresolved place: does a batch with no name for its place read as a sentence rather than `None`, and do its two causes — withheld near a home, and no coordinate at all — stay indistinguishable? |
| `exiftool_utf8_cases.py` | OA-27: does a path with a non-ASCII name reach exiftool intact, and does its answer come back decoded as UTF-8 rather than as the locale? |
| `photo_identity_cases.py` | R3a: does a frame holding TWO animals produce two detections, two crops and two vectors — or does the second one leave no trace anywhere in the index (D-24)? Also the compat contract: `load_index()` still answers with the primary detection so every pre-R3b consumer is unchanged, `load_detections()` is the new wire, and an owner's pre-R3a `identity.csv` is read and flagged rather than rejected. Needs numpy, not the model weights: `animal_boxes()` takes `torch` and the detector as arguments, so a stub of each tests the selection rule. |
| `photo_name_cases.py` | R11/R12 + D-F11/D-F13: is the folder-name grammar ENFORCED, or still a convention the naming agent is trusted to follow? Does a multi-day batch refuse a single-day period (9 of 11 UAT01 folders were wrong that way), does a known place refuse to be dropped from the name (6 of 11), and does the N-2 budget count what the SPEC says — [period] and [where] never charged, full-width per character, narrow script per word, separators free? Stdlib only. Since C4 also the `[what]` slot: is it still OPEN free text — no vocabulary argument on `validate()`, no membership check, and no reach into the owner's pack from the grammar module — and is the soft budget the signed `{16}`? |
| `photo_sample_cli_cases.py` | D-08: does the `--no-date` sweep survive a dump with **nothing to sweep** — the CLEAN dump, which is the case that used to crash — and does it still answer in the JSON shape an agent reads, rather than trading a traceback for an unparseable sentence? `preclassify_cases.py` covers this module's rules as functions and reads no files, so the entry point had no suite at all. |
| `photo_quickscan_cases.py` | D-19: is the proposed group's **year label** what the unit mostly IS? It was the LATEST sampled year, so two chat screenshots saved the following January labelled a 990-file 2024 dump as 2025. Also the sample pool: `._*` AppleDouble files carry a media extension and no EXIF, and each one burns a slot. |
| `manifest_verify_cases.py` | A41: is a stale manifest reported as **moved** rather than as data loss — the re-split, the renamed parent, the deleted file and the unmounted drive, over real temp trees because the question under test IS the filesystem's. Since U2-14 also count honesty: does `--verify` say what it indexed and what it excluded, and does the scan summary's `main_files + aae_ignored + appledouble_ignored = total_files_seen` close, so the owner's folder count can be reconciled instead of merely disagreeing? |
| `no_owner_facts.py` | rule 7 / rule 8 guard: no owner facts, and no hardcoded non-English, in what we ship |
| `owner_guard_cases.py` | RS7d: does the owner-fact guard report a term inside a CJK-waived file (no waiver covers an owner fact), and inside `.githooks/` and `.github/`? Runs the guard on a scratch repo with an invented term |

```bash
python3 tests/golden_replay.py && python3 tests/golden_replay_cases.py \
  && python3 tests/fresh_owner_smoke.py \
  && python3 tests/preclassify_cases.py && python3 tests/photo_plan_cases.py \
  && python3 tests/photo_execute_cases.py \
  && python3 tests/onb_cases.py \
  && python3 tests/photo_where_cases.py && python3 tests/photo_cluster_cases.py \
  && python3 tests/settings_cases.py \
  && python3 tests/schedule_cases.py \
  && python3 tests/i18n_cases.py && python3 tests/exiftool_utf8_cases.py \
  && python3 tests/photo_name_cases.py \
  && python3 tests/photo_sample_cli_cases.py \
  && python3 tests/photo_quickscan_cases.py \
  && python3 tests/no_owner_facts.py
```

Why `exiftool_utf8_cases.py` exists: every golden fixture is a replay of rows
already scanned, so the scan stage's own argv could be broken for a whole
platform — it was — and the suite would still be green. On Windows exiftool
decodes argv through the ANSI codepage, turning a name it cannot represent
into `?`, which it then reads as a wildcard; the engine passes every argument
through a UTF-8 argfile (`-@`) instead. The unit half runs with no exiftool
installed; the end-to-end half needs it and SKIPS, visibly, without it.

Why `schedule_cases.py` exists: the rule it guards is a NEGATIVE one — the
unattended run must never copy — and nothing in a green pipeline run can
demonstrate a thing that did not happen. So the suite asserts the two
mechanisms instead: the rendered bytes carry no `--go`, and the tool
allowlist handed to `claude -p` omits `photo_execute.py`. The second is the
one that still holds when the prompt is misread, which is the failure mode a
3am run actually has. ⛔ Two cases tamper with a template on purpose and
restore it in a `finally` — a guard that has never been shown to fire is
decoration.

⚠️ What it does NOT cover: the suite never bootstraps a real LaunchAgent, so
"the plist fires" is not a claim it makes. That half is verified by hand on
macOS (a short-interval job, watched, then removed) — a suite that installed
one would leave it behind on the run where it failed.

⛔ What the by-hand fire found, and why it could not have been a case
(MEASURED 20260901, A11): a launchd agent reading a file under a
TCC-protected folder — `~/Documents`, `~/Desktop`, `~/Downloads` — blocks in
`open(2)` **indefinitely** rather than failing. Controlled test, one variable:
the same job, interpreter and arguments finished in under a second with the
script under `/private/tmp` and was still blocked three hours later under
`~/Documents`. Two consequences worth keeping:

* **The permission is per EXECUTABLE, not per path.** `/bin/zsh` and its
  `cat` read the engine fine in the same job where the Homebrew python binary
  was blocked on the same file — so a `cat` probe returns a confident yes and
  the run hangs anyway. The runner probes with `$PYTHON`.
⛔ And the allowlist claim itself is MEASURED, not assumed (20260901). The
whole HIL-stop argument rests on `photo_execute.py` being absent from the
allowlist the runner hands `claude -p` — which is only as strong as the
matcher underneath it. If that matching were a prefix test, a chained command
could satisfy an allowed pattern and run a second binary. It is not. Tested
with a working positive control, so "everything was blocked" is excluded:

| command, against `Bash(/bin/echo ALLOWEDMARKER:*)` | result |
|---|---|
| `/bin/echo ALLOWEDMARKER` | **ran unattended** — the grant is real |
| `… ; /bin/echo SMUGGLEDMARKER` | refused; approval demanded on *the second part* |
| `… && /bin/echo SMUGGLEDMARKER` | refused; second part named |
| `… $(/bin/echo SMUGGLEDMARKER)` | refused — command substitution rejected |

The matcher decomposes a command and judges each part, and in `-p` mode an
approval request is a refusal because nobody is there to answer. ⚠️ This is
Claude Code's behaviour, not the engine's, so no case in this repo can pin it
— it is recorded here so the next person to widen the allowlist knows what
was checked and re-checks it rather than inheriting the conclusion.

* **A hang is not a failure.** Nothing times out, nothing is logged, launchd
  counts a run that left no record. `install` therefore warns while the owner
  is awake, `status` names a run that started and never reported, and every
  call the runner makes is time-boxed so it cannot leave a stuck process.

Why `photo_where_cases.py` exists: the golden harness replays the PLAN stage,
and `photo_where.py` is not in its import set — so the rule that a residence is
never named had no test at all, and until OA-22 it depended on an operator
typing `--anchor`. Its cases run the real script over a synthetic dump whose
geocode cache is pre-seeded with a name for **every** day, home days included:
a suppression that breaks renders the home's name instead of producing
nothing, and each case pins a non-home day that must still be named in the
same run. Offline — no Overpass or Nominatim call is made.

`no_owner_facts.py` needs a private term list to run its owner-fact half:
copy `tests/.owner-terms.example.json` to `tests/.owner-terms.json` (which is
gitignored) and fill in the strings that must never ship. Without it that half
SKIPS with a message and the rest of the guard still runs — a missing private
file must never fail a contributor's build. Known debt is waived with a stated
reason and the waived count is printed on every run; a waiver whose debt is
already gone fails the guard, so the number can only go down deliberately.

Why `preclassify_cases.py` exists: no golden dump contains an Android-style `Screenshot_*`
file, so the screenshot rule could be entirely broken and still replay 13,208
rows green. A replay proves a rule does not **misfire**; only a written case
proves it fires. `preclassify_cases.py` uses the real filenames and real
dimensions of screenshots this archive holds — two of which are cropped, and
so unreachable by any screen-size rule.

## photo_embed_cases.py / photo_recurrence_cases.py / photo_see_cases.py — NOT in the chain above

VS-1's suite needs the ML deps (`torch`, `open_clip_torch`) that the stdlib
chain above deliberately does not — the PLAN stage they cover must stay
green with zero ML dependencies installed. Run it separately, under the
repo `.venv` (see `photo-embed/SKILL.md`):

```bash
./.venv/bin/python3 tests/photo_embed_cases.py
```

Covers resume (no-op / append / re-embed-in-place), the model-identity
mismatch hard-fail, and one file failing without killing the run. Synthetic
Pillow images only, generated at run time — never real photos in `tests/`.

VS-1b's suite needs `numpy` — which is only in the `.venv` — but **not**
torch, since the census loads no model:

```bash
./.venv/bin/python3 tests/photo_recurrence_cases.py
```

Covers the four axes, blast-radius ranking (and that it reaches leftovers
only), stable candidate ids across re-runs and across work-dir order, the
`obs_count` bump on re-observation, residence inference plus coordinate and
directory-name suppression, pack-blindness, and the `--force` / `--reset`
overwrite rules. Synthetic 32-dimensional vectors with a hand-built geometry —
never a real photo, a real vector or a real place.

VS-2's suite needs **numpy** and (for the four thumbnail cases) **Pillow**,
both in the `.venv`; like the census it loads no model:

```bash
./.venv/bin/python3 tests/photo_see_cases.py
```

Covers the priority ladder's fill order and its floor/cap budget, that the
three registry-fed parts (rungs 2 and 4, the N-4 naming carve-out) are a
strict **no-op** when the run's pack holds no subjects and fire correctly when
it does, determinism of the selection and of the whole report modulo `run_id`,
cluster-label propagation, the model-identity and class-set guards on the
scene-label file, that ONB-12's filename rule is not weakened, and the
2026-07-20 **fabrication guard**: a `clip-propagated:` label promoted to
`viewed-image:` must raise, and so must a `viewed-image:` claim with no
thumbnail on disk.

VS-3's suite needs **numpy** only, and no pack of any kind — it builds its
own from `templates/photo-memory/_template`:

```bash
./.venv/bin/python3 tests/photo_subjects_cases.py
```

Covers the subject registry: the empty-pack no-op, the **memorize rule**
(eleven provenances refused, only `viewed-image` accepted), the
diversity-kept exemplar cap, the **timeline gate** — structurally, since
`match()` has no path to read an era off, and behaviourally on dates alone —
the accept/gray/none thresholds with per-subject overrides, **cardinality
never auto-resolved** (two lookalike subjects produce a question, never a
merge), N-10a's rename-keeps-the-key, the save/load
round trip with vectors aligned to `exemplars[]`, another model's registry
being refused, and the `review --prune --go` write gate. Invented names only.

VS-4's suite needs **numpy** and (for the one end-to-end CLI case) **Pillow**:

```bash
./.venv/bin/python3 tests/photo_memory_cases.py
```

Covers the memorize loop, new-subject discovery, the hardened fabrication
guard, the plan CSV's provenance columns and the review-table round trip. Four
cases are named for the DESIGN's four exit tests: the registry grows only from
vision-confirmed matches **and the audit log proves it**; the fabrication
guard against eleven forgeries (empty thumbnail, text file wearing a `.jpg`
name, symlink out of `samples/`, `../` escape, one thumbnail backing two
looks, a see-report for another batch, …); one subject over K batches yielding
exactly one question, across checkpoints and across runs; and a byte-identical
checkpoint replay against a pinned pack snapshot id.

Three step-8 cases drive `memorize_replay.py` itself as a subprocess over a
synthetic three-class dump: the whole-dump run replays every kind through one
draft store and reports one round, a single `--type` still selects exactly that
class, and a requested class the dump does not ship is named rather than
silently contributing nothing. The tile assertion is the INVARIANT — a round of
K kinds renders `sum(min(drafts_in_kind, {drafts_rendered_per_question}))`
tiles — which is the missing round-level tile ceiling written as an equation
rather than as the shipped 12.

It also covers SNS-5's re-presentation: a remembered subject comes back in a
round with **no new evidence at all**, the frame shown is the **worst**-scoring
sighting (asserted both ways — promoting the other look must flip which frame
renders), each of the three unscoreable paths says so instead of falling back
to a nice frame, a re-presentation promotes zero exemplars and an untouched
review writes nothing, a rejection is listed with no frames and revived from
the round, a withdrawal reaches the work dir that already asked **and only
that subject**, and the one gesture this step refuses — *stop asking about
this one* — is asserted on the refusal's own words and the id it names.

## pack_state.py — the EV-9 header every run prints

`scripts/pack_state.py` holds one implementation of one rule: *a run that does
not print the pack state it ran under is not admissible evidence*. Every
harness above and below calls it, so a benchmark, a replay and a fixture suite
all state their pack in the same words. It sits in `scripts/` because
`photo_run.py` prints the same header on a real Tier 3 run, and engine code
must not import from the test tree.

The header names four things — the run type (which tier of evidence), the pack
slug, whether the pack was empty, and the pack's snapshot id:

```
[Tier 2 (replay measurement)] pack: owner=BetaUser00 BLANK SHEET verified, snapshot sha256:… over 7 file(s) [benchmark (cold start)]
[Tier 1 (frozen fixture, pass/fail)] pack: NONE — engine defaults only, no owner bound, snapshot n/a [as-configured]
```

Two things about it are deliberate and easy to undo by accident:

* **`run_type` has no default.** Each caller names its tier; an omitted one is
  a `TypeError` and an invented one a `ValueError`. A tier that can be
  forgotten is a tier that gets misquoted.
* **The benchmark label and the blank-sheet check are the same call.**
  `pack_state(..., benchmark=True)` refuses to return at all if the pack holds
  owner facts. ⛔ Do not re-split it into a check standing beside a print: a
  later edit drops one and keeps the other, and the number that comes out
  looks exactly like a cold-start number.

⚠️ **Printed, never asserted blank, outside a benchmark.** Two golden fixtures
and the fresh-owner smoke test carry packs *on purpose* — the routing under
test is pack-driven. What guards those is `golden_replay.check_pack()`'s
snapshot pin against `tests/golden/index.json`, not a blank-sheet assertion.

Cases: `tests/photo_see_cases.py`, the five `EV-9`/benchmark entries.

## memorize_replay.py / see_replay.py — measurements, not suites

`tests/memorize_replay.py` is VS-4 exit test 3 against a real embedding index:
does the cross-batch dedupe that works on hand-built geometry survive the
geometry of real photographs? ⛔ **On the archive benchmark dump it does not** —
59 batches of one shipped class produced 42 drafts and 57 questions at the
shipped dedupe tau, and no value in a 0.90→0.60 sweep approaches one. The
numbers, the oracle substitution they rest on, and what they do and do not
establish are recorded in that file's docstring. It runs read-only and prints
an mtime check over the work dir.

`--type` is **repeatable and optional** (step 8, 2026-08-21). Omit it and every
class the dump ships is replayed in one run through ONE draft store, which is
the only shape that yields a dump-level ask count; pass it once and the run is
the single-class slice every earlier number was measured on. Either way the
result is reported as **three numbers, never one** — rounds, tiles, deferred —
with frameless drafts kept separate as a fourth. ⛔ It walks the silent-owner
path only: nothing is answered and nothing is promoted, so it measures OA-13
exit-test clause (1) and cannot touch clause (2).

```bash
./.venv/bin/python3 tests/memorize_replay.py "<work dir>"                 # whole dump
./.venv/bin/python3 tests/memorize_replay.py "<work dir>" --type <class>   # one class
```


`tests/see_replay.py` is VS-2's exit test: does 10% embedding-guided seeing
reproduce the shipped classify decisions, and what does it cost against the
old sampler? It cannot run on the frozen fixtures — it needs the VS-1
embedding indexes, which are built from the real image bytes — so it runs
against the live `Working Files/` dumps and prints numbers instead of
passing or failing. Its docstring states the oracle substitution it makes and
what that does and does not prove. Results are recorded in
`photo-see/SKILL.md`.

```bash
./.venv/bin/python3 tests/see_replay.py "<Working Files>" --dump 202605__ 202603__
```

## Golden-dump regression harness

Every later phase of the v2 plan changes engine behaviour. This is the thing
that says whether a change was intended.

Four dumps that already shipped are frozen here as fixtures. The harness
re-runs `photo_plan.py` against them and compares the plan it produces **now**
against the plan that was actually copied to the drive **then**.

```bash
python3 tests/golden_replay.py                 # all dumps
python3 tests/golden_replay.py --dump 202605   # one dump
python3 tests/golden_replay.py -v              # name the policy deltas applied
python3 tests/golden_replay.py --report r.md   # markdown report
python3 tests/golden_replay.py --fixtures DIR  # a fixture set kept elsewhere
```

Exit 0 = reproduced. Exit 1 = something changed that nobody explained.

### Where the fixtures come from

⛔ Fixtures come only from `$PHOTO_GOLDEN_FIXTURES` (or `--fixtures DIR`); `tests/golden/` is gitignored, symlink included, and `no_owner_facts.py` fails if it ever becomes addable.

`--fixtures DIR` > `$PHOTO_GOLDEN_FIXTURES` > `tests/golden`. The default is
unchanged, so every invocation above behaves exactly as it always has; the
override exists because `tests/golden/` is one owner's real data and a
checkout may legitimately not have it.

⛔ A root that is absent, holds no `index.json`, declares no dumps, or is
missing a dump directory its index names is a **harness error — exit 2**,
naming the path and the two ways to change it. ⚠️ Measured at `b0b9e11`, not
assumed: every one of those routes used to exit **1**, as a traceback or as
`no such dump; have: []` — indistinguishable from "the engine changed", which
is the one finding this harness exists to report. The green line for a set
nobody asked for was reachable a different way: `$PHOTO_GOLDEN_FIXTURES` was
ignored, so a run aimed elsewhere replayed `tests/golden` and reported
`ALL GOLDEN DUMPS REPRODUCED`. `golden_replay_cases.py` holds both shut.

The same resolver is imported by `photo_memory_cases.py` for the one case
there that needs a frozen dump; without the fixture that case **skips** with a
printed reason and the suite still passes (`{n} skipped` in the summary line).
`apply_merge_cases.py`, `record_picks_cases.py`, `video_timezone_cases.py` and
`photo_index_cases.py` (its golden-manifest case) read their fixtures the same
way and skip the same way, naming `$PHOTO_GOLDEN_FIXTURES`; every case that
needs no fixture still runs. Before RS1 they read `tests/golden/` directly and
failed without it.

Runs **offline** — no external drive has to be mounted, nothing is copied,
no network. About 9 seconds for all four.

## The dumps

| id | files | plans | shipped | why it is in the set |
|---|---|---|---|---|
| `202605` | 4,819 | 7 + no-date | 2026-07-04 | the hard one: trip legs, 1,214 dedupe skips, an override pointing outside `dest_root`, in-plan name collisions |
| `202603` | 996 | 9 + no-date | 2026-07-05 | date overrides splitting one plan across destinations; the only plan declaring dedupe refs |
| `202602` | 1,031 | 7 + no-date | 2026-07-05 | day-level overrides, a merge into an existing hand-named trip folder |
| `group3` | 7,362 | 100 + no-date | 2026-07-22 | scale, and a Samsung/Android device instead of iPhone. Post-dates **D13 and D14**, so neither may ever explain a diff here. It does carry two later deltas — `BUG-profile-aware-preclassify` (a bug that was live when it shipped) and `G3-no-exif-rename` (a 2026-08-05 label rename it legitimately pre-dates) |
| `screens01` | 7 | 1 | 2026-08-21 | **SYNTHETIC — the only fixture that is not a shipped dump.** G-1 and G-2 had zero replay coverage: no fixture pack set `screen_dims` and no golden dump held a filename-detected screenshot, so both rules could break silently — and G-2 **moves files** |

### screens01 — why a synthetic dump was added

The four dumps above are frozen copies of runs that really happened, and that
is what makes them evidence. `screens01` is not one, and the difference is
stated rather than blurred: its expected CSV was generated by the engine, so
it can only ever be a **regression lock** — it pins today's behaviour and
fails when that behaviour changes. It proves nothing about whether the
behaviour is *right*. (Tier 1 in the Evaluation SPEC: a green suite is a
regression claim, never a correctness one.)

It was added because the alternative was worse. `screen_dims` is a
pack-driven rule that **routes files**, and no replay touched it. The seven
rows are chosen so each rule owns one:

| row | what it pins |
|---|---|
| `IMG_2003.PNG` @ 1170x2532 | **G-1** — the model-paired `{"model": ..., "dims": [w, h]}` shape matches |
| `IMG_2004.PNG` @ 828x1792 | the **pre-G-1 flat** `[w, h]` shape still matches, so an un-migrated pack does not go blind |
| `Screenshot_*.png` @ 1440x3120 | the filename rule (ONB-12), and this file is the **witness** that proves an unconfirmed size |
| `IMG_2006.PNG` @ 1440x3120 | **G-2 / ONB-16b** — a same-size neighbour goes to *to-be-checked*, never to the screenshots bucket. A guess is not filed as a fact |
| `IMG_2007.PNG` @ 3120x1440 | the same neighbour rule through the **orientation expansion**, which is the path a code review called a defect on 2026-08-21 and had to retract — it was correct, and it was untested |
| two `IMG_200x.HEIC` | the ordinary path, so a rule that fires on everything fails here too |

**Verified load-bearing, not assumed.** Three regressions were injected and
each was caught on the right file: dropping the paired shape moved
`IMG_2003` into the trip folder; dropping the flat shape moved `IMG_2004`;
and returning one orientation from `screen_candidate_dims()` moved
`IMG_2007`. A fixture generated from the engine that has never been shown to
fail is decoration.

## Explained diffs are reconstructions, not a whitelist

`202605`/`202603`/`202602` were planned before decisions **D13** (2026-07-06,
extension corrected at copy time) and **D14** (2026-07-13, monthly buckets
gained a `00` day field). Their shipped plans are therefore legitimately out
of date. `group3` was planned while a **bug** was live (see below).

Rather than listing the rows that differ — a list that rots the moment the
data changes — `waivers.py` **replays the shipped plan forward through those
decisions** and requires the result to equal today's output exactly. A new
file that differs in an already-understood way is absorbed; a file that
differs in any other way fails.

Two properties keep this honest:

- the reconstruction may only read the **frozen fixture** (shipped CSV +
  `manifest.csv`), never the engine's current output, so it cannot bend to
  fit whatever the engine happens to emit;
- every delta is **scoped to the dumps that pre-date its decision**. If D14
  ever appears to explain a diff in `group3`, that is a regression and the
  harness says so.

The D13 collision-suffix rule (`_dup2`, `_dup3`) is deliberately re-implemented
in `waivers.py` instead of imported from `photo_plan.py`. Importing it would
make the harness agree with the engine by construction.

### A policy delta and a bug delta are different claims

`group3` shipped while `photo_plan.route()` was calling `preclassify()`
without the owner pack, so 5,239 of the owner's own Samsung photos were noted
`shared` — "not shot on this device". That output was not right-for-its-day
like D13/D14; it was **wrong when it shipped**. `BUG-profile-aware-preclassify`
therefore carries a stricter burden than a policy delta:

- it may only drop the note where the **fixture's own pack** lists that
  camera `Make` as the owner's — read straight off the pack file, so the
  justification is a declared input and not "the engine changed its mind";
- files that read `shared` for the other reason (random-name LINE/AirDrop
  saves with no camera tags at all) must still read `shared`;
- it must move **exactly** the number in `waivers.EXPECTED_FLIPS`. The
  fixtures are frozen, so this is an exact count, not an estimate — if the fix
  reaches more rows than the pack explains, the harness fails rather than
  absorbing it.

## Fixture packs

A fixture that needs an owner pack carries a **synthetic** one inside its
`input/`, bound by `input/collection.json`, and `index.json` pins its snapshot
id. Only `group3` has one today (it is the only dump shot on two camera
makes). Editing it changes the pack id and fails the run — the pack is a
fixture input like `manifest.csv`, not an ambient setting.

The operator's `PHOTO_PROFILE` is still cleared before each replay, so a real
person's pack can never leak into a test. And a fixture pack holds **no owner
facts**: no real name, no home locations, no people, no pets, no vocabulary.

## What a green run does NOT prove

- **Plan stage only.** `photo_plan.py` and what it imports
  (`photo_cluster.parse_date`, `photo_sample.preclassify`, `photo_profile`).
- **`photo_dedupe.py` is untested here** — dedupe results are frozen inputs,
  so a change to the dedupe rule passes unnoticed. Same for `photo_scan.py`
  (`manifest.csv` is frozen) and for clustering itself (`batches.json` is
  frozen). Those stages need their own tests.
- **Never the `.md` plan** — it embeds `datetime.now()` and a folder listing
  that depends on whether the drive is mounted.
- **Coverage is uneven.** No fixture contains a filename-detected screenshot,
  so that rule is proved only by `preclassify_cases.py`. A green replay says
  the rule does not misfire on 13,208 real rows — nothing more.
- **Not the whole pack.** Four fixtures load one, and only
  `own_camera_makes` / `language` / `screen_dims` steer anything today. Once
  memory mutates per batch (v2 Phase C), a replay must also pin the snapshot
  recorded in `status.json`.
- **The subject registry is untouched.** `tier3cat`'s `who` column renders
  through `visual_columns()`, but every see-label it carries holds a
  `subject_kind` and NO `subject_id`, so the branch that resolves a name out
  of the registry never runs. A rename, a fold, or an alias following an old
  id passes this harness untested.
- **Every fixture see-label is in the PRE-R4 shape** — one `subject` object,
  never a `subjects` list, because they were frozen before a frame could hold
  two animals. That makes the replay the compatibility proof for the old
  shape and blind to the new one: `photo_evidence.subject_list()` reads both,
  and only `photo_plan_cases.py` exercises the list. ⛔ Do not "modernise"
  these fixtures — rewriting them would delete the only place the old shape
  is still read end to end.

Verified by injecting real regressions: reverting the D14 bucket name;
dropping the shared-file provenance note; reverting the profile-aware
`preclassify` fix (5,239 rows go unexplained); tampering with the fixture pack
(pack-drift error); and setting `EXPECTED_FLIPS` off by one. Each fails the
harness, and reverting each returns it to green.

## Adding a dump

⛔ Every `tests/golden/<id>/` below means `<id>/` under your `$PHOTO_GOLDEN_FIXTURES` root — never a `tests/golden/` inside a clone of this repo.

1. Copy its work dir inputs to `tests/golden/<id>/input/` — `manifest.csv`,
   `batches.json`, `plans.json`, `no-date-files.csv`, any
   `plan/dedupe_batch-NN.json`, and any
   `classify/batch-NN/see-labels.json`. ⚠️ The see-labels are easy to miss
   and they are not optional: `visual_columns()` reads them, and when a plan
   has them its `plan_PN-files.csv` gains four columns (`who`,
   `who_provenance`, `what`, `what_provenance`). Omit them and the replay
   writes a narrower header than the shipped CSV, so every row differs.
2. Copy the shipped `plan/plan_P*-files.csv` to `tests/golden/<id>/expected/`.
3. Add the entry to `tests/golden/index.json`.
4. If the dump pre-dates a decision, add its id to that decision's scope set
   in `waivers.py`. If it post-dates all of them, add nothing — it must
   reproduce exactly.
5. If its plans depend on an owner pack, add a **synthetic** one under
   `input/photo-memory/<slug>/` (profile + `photo-owner-<slug>.md`), bind it
   with `input/collection.json`, and record its snapshot id — printed by
   `python3 scripts/photo_profile.py tests/golden/<id>/input` — in
   `index.json` under `pack`. Never point a fixture at a real person's pack.


## 📐 Measuring recognition: hold out the BATCH, never the frame

Any measurement of "would this subject be recognised in a photo it has not
seen" must split on the **capture session**, not on the individual frame.

Real dumps are full of bursts — the same shot again six to sixty seconds
later. A frame-level holdout leaves each query's near-duplicate sitting in the
exemplar bank, so it measures duplicate retrieval, not recognition. It also
biases asymmetrically and in the flattering direction: an impostor has no
burst partner in the bank and structurally cannot have one, so contaminated
positives get compared against clean negatives.

Measured both ways on the same 23 owner-labelled frames (20260821):

    leave-one-FRAME-out    17/18 nearest neighbour correct  (94%)   WRONG
    leave-one-BATCH-out    12/18                            (67%)   honest

The contamination has a signature worth knowing: sort the scores and look for
**mirrored pairs** — `0.931 / 0.931`, `0.952 / 0.952`. Two frames scoring each
other are two halves of one burst.

The same split produced the VS-3b numbers in `scripts/photo_identity.py`, and
those are a DIRECTION rather than a calibration: 15 true queries and 5
impostors, one household, two subjects.
