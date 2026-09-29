# status.json schema (R3/P3.1, P3.4)

Updated (v2 Phase A): added `pack_snapshot`.

One `status.json` per dump workdir (`<Working Files>/<dump>/status.json`),
written by `photo_run.py status`/`prep`. It is an **additive, derived
ledger** — read-only pipeline visibility, never a source of truth. The
authoritative state for resumability stays `batches.json` (batch
`status: pending/classified/planned/approved/done/held`) and `plans.json`; a
future visual UI reads `status.json` only, never writes it.

```json
{
  "stage_names": ["1-grouped", "2-gps-split", "3-sampled", "4-classified", "5-sorted"],
  "generated_at": "2026-07-20 16:00",
  "pack_snapshot": {"owner": "juno", "id": "sha256:1a2b3c4d5e6f7890", "files": 5},
  "totals": {
    "files": 4819,
    "batches": 16,
    "gps_legs": 14,
    "to_be_id": 2
  },
  "batches": [
    {"batch": 1, "stage": "5-sorted", "status": "done", "to_be_id": false}
  ],
  "plans": 7
}
```

- `stage` — one of `stage_names`, derived from the batch's `status` in
  `batches.json` plus whether `classify/batch-NN/sample-report.json` exists
  yet (stage 3 vs 2).
- `held_reason` / `held_at` / `held_by` — present **only** on a batch whose
  `status` is `held`: a deliberate stop on an unanswered question, with the
  free-text reason, when it was set, and the self-declared operator who set
  it. ⛔ A hold is not a sixth stage — a batch is held AT whatever stage it
  reached, so `stage` still reports its progress. What it changes is that
  `photo_run.py status` lists it under its own heading and proposes no action
  on it. Without these fields a hold was indistinguishable from a batch nobody
  had started, and `next:` would hand the operator the command to undo it.
  Releasing the hold (any other status) clears all three.
- `to_be_id` — true when the batch carries the `no_gps` flag from
  `photo_cluster.py` (sketch step ②'s "to-be-ID" split); these route to
  the monthly to-be-checked bucket at stage ⑤ unless classified (D13/D14) —
  under an English pack, a no-date VIDEO → `YYYY00_To-be-checked` (its own modify year); a no-date STILL → one `_To-be-checked/<import>` folder that claims no year (Card 5); a manifest scanned before Card 5 still uses the dump's `YYYYMM00_To-be-checked`; the word resolves from the
  pack's language.
- `pack_snapshot` — which owner memory the run stood on: a SHA-256 over every
  pack file that can steer a decision (`photo-profile.json`,
  `photo-entities.json`, `photo-proposals.md`, the anchor file,
  `photo-subjects/`), excluding the append-only log. `null` when the run has
  no pack.

  It is here because from v2 Phase C memory mutates **between batches**, so a
  run's output depends on memory state *and* batch order. A golden-dump replay
  pins this id; two runs reporting the same id stood on the same memory. See
  `docs/photo-memory-pack.md`.
- `photo_run.py status` prints a one-line rendering of the same 5 counts,
  e.g. `① 4,819 files → ② 14 GPS legs + 2 to-be-ID → ③ 12/16 sampled →
  ④ 9/16 classified → ⑤ 3/16 sorted`.
