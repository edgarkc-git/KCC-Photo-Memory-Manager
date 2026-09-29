# Photo memory log

Append-only. One line per fact, never rewritten — deleting a fact from
`photo-entities.json` leaves its history here.

```
YYYY-MM-DD | <maturity> | <the fact>
  | evidence: <what was actually seen>
  | by: <self-declared name, default "Claude User"> | src: <run / checkpoint>
```

Maturity is `ai-drafted` · `ai-reinforced` · `human-confirmed` ·
`human-typed` · `human-answered` · `rejected`. Only a **memory checkpoint**
produces `human-confirmed`; a plan approval promotes nothing.

`human-confirmed`, `human-typed` and `rejected` SETTLE the subject ids on
their line — those subjects are never asked about again. `human-answered` is
a human fact that settles no subject: a cardinality answer says how many
subjects there are, never who either of them is, so both members stay
askable. Since F16 the checkpoint no longer ASKS for a bare count — the
grouping is the cardinality answer — so `human-answered` appears only where a
review table written before F16 was confirmed.

A subject the owner simply left out of every `pick:` row is settled by
nothing and writes no line here. That is deliberate: it stays `ai-drafted`
and comes back when its evidence grows. Only an explicit `skip:` writes
`rejected`.

`by:` is self-declared and unverified. It records who stood behind a fact when
the pack travels to another machine — it is a note, not an authentication.
