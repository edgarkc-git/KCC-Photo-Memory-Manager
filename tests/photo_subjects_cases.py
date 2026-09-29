#!/usr/bin/env python3
"""Cases for photo_subjects.py (VS-3) — the subject registry, the timeline
gate, the memorize rule and the cardinality question.

Every fixture is synthetic: vectors are hand-built in an 8-dimensional toy
space, the "photos" are paths that never existed, and every name is invented
(`Name-One`, `class-word`, `subj-0001`). The engine ships with zero owner
facts and so does its test suite — `tests/no_owner_facts.py` fails the build
if that stops being true.

Three of these cases are adversarial rather than happy-path, and they are the
ones worth reading:

  * a `clip-matched` / `clip-propagated` file can NEVER become an exemplar —
    output that becomes its own evidence is how a registry drifts;
  * the timeline gate reads the file's OWN date and has no way to read a path,
    which is the shortcut the benchmark's 2020-dated strays exist to catch;
  * two lookalike subjects produce a QUESTION, never a merge.

Needs numpy, which lives in the repo .venv. No torch, no network, no drive.

  ./.venv/bin/python3 tests/photo_subjects_cases.py [-v]

Exit 0 = pass.
"""

import argparse
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import photo_evidence  # noqa: E402
import photo_profile  # noqa: E402
import photo_subjects as psub  # noqa: E402
import view_fixture  # noqa: E402

VERBOSE = False
DIM = 8
# The interpreter for subprocess cases. The repo's .venv is gitignored, so it is
# absent in a fresh clone and in every git worktree — a hardcoded path there gave
# 13 false failures across three suites that read as code defects (D-29). Fall back
# to the interpreter actually running this file.
PY = str(ROOT / ".venv" / "bin" / "python3")
if not Path(PY).exists():
    PY = sys.executable
SCRIPT = str(ROOT / "scripts" / "photo_subjects.py")
TEMPLATE = ROOT / "templates" / "photo-memory" / "_template"

IDENTITY = {"model_id": "ViT-B-32", "pretrained_tag": "laion2b_s34b_b79k",
            "embed_dim": DIM, "preprocess_fingerprint": "sha256:testfixture0000"}


def log(msg):
    if VERBOSE:
        print(f"      {msg}")


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / float(np.linalg.norm(v))


def basis(i):
    v = np.zeros(DIM, dtype=np.float32)
    v[i % DIM] = 1.0
    return v


def near(base, i, jitter=0.08):
    """A vector close to `base` but not identical — a different photo of the
    same thing, deterministically."""
    return unit(np.asarray(base, dtype=np.float32) + jitter * basis(i + 3))


def make_pack(root, owner="someone"):
    """A pack on disk, copied from the shipped template so these cases test
    the file layout a real owner actually gets."""
    pack_dir = Path(root) / owner
    shutil.copytree(TEMPLATE, pack_dir)
    for path in list(pack_dir.rglob("*")):
        if "{{SLUG}}" in path.name:
            path.rename(path.with_name(path.name.replace("{{SLUG}}", owner)))
    profile = json.loads((pack_dir / "photo-profile.json").read_text()
                         .replace("{{SLUG}}", owner).replace("{{DISPLAY}}", owner))
    (pack_dir / "photo-profile.json").write_text(json.dumps(profile))
    return pack_dir


def open_registry(pack_dir):
    pack = photo_profile.resolve_pack(explicit=pack_dir / "photo-profile.json")
    return psub.load(pack=pack)


_LOOKS = {"n": 0}


def look_for(registry, source, **kw):
    """The artifacts one vision-confirmed look leaves behind, written beside
    the tmp pack. VS-4 made `viewed-image:` an evidence claim, so a test that
    memorizes has to produce a real see-report and a real thumbnail — exactly
    what a caller in production has to produce."""
    _LOOKS["n"] += 1
    root = Path(registry.dir).parent.parent / "_look"
    return view_fixture.make_look(root, source, batch=_LOOKS["n"], **kw)


def seeded_subject(registry, base, count=4, name="Name-One",
                   active=("2029-03", "2031-08"), kind="class-word", start=0):
    """One subject with `count` vision-confirmed exemplars around `base`."""
    subject = registry.create_subject(name=name, who="relation-word", kind=kind,
                                      active=list(active))
    for k in range(count):
        source = f"/raw/IMG_{start + k:04d}.HEIC"
        registry.add_exemplar(subject.subject_id, near(base, start + k),
                              f"sha256:{name}-{start + k:03d}", source,
                              added="2031-02-14", confirmed_by="viewed-image",
                              identity=IDENTITY,
                              evidence=look_for(registry, source))
    return subject


# --------------------------------------------------------------- the cases --

def case_an_empty_pack_is_a_strict_no_op(tmp):
    """The first thing to be true. No pack at all, and a pack whose registry
    ships empty, must both answer nothing — that is the state every benchmark
    run and every pre-checkpoint run is in."""
    nothing = psub.load()
    assert not nothing and len(nothing) == 0, nothing.subjects
    assert nothing.match(np.zeros((3, DIM), dtype=np.float32),
                         [datetime(2030, 1, 1)] * 3) == [None, None, None]

    registry = open_registry(make_pack(tmp))
    assert not registry, registry.subjects
    assert registry.match(np.zeros((2, DIM), dtype=np.float32), [None, None]) \
        == [None, None]
    assert psub.review(registry)["count"] == 0
    log("template ships an empty registry; no pack resolves to an empty one")


def case_only_viewed_image_may_become_an_exemplar(tmp):
    """The anti-drift constraint, adversarially. A CLIP match is the
    registry's OWN output; letting it back in as evidence is how a registry
    drifts on its own errors."""
    registry = open_registry(make_pack(tmp))
    subject = registry.create_subject(name="Name-One", who="relation-word",
                                      active=["2029-03", None])
    vec = near(basis(0), 1)

    # A REAL look at a real file, so the only thing under test below is the
    # provenance string. Without this the refusals would be ambiguous — every
    # one of them would also have failed the evidence gate.
    proof = look_for(registry, "/raw/IMG_9999.HEIC")

    refused = []
    for provenance in ("clip-matched", "clip-matched:", "clip-propagated",
                       "clip-propagated:", "draft", "gps-only", "exif-only",
                       "", None, "viewed image", "VIEWED-IMAGE",
                       # VS-4: a look at a file whose SUBJECT is a draft. The
                       # look was real; what it was attributed to is not.
                       "draft:viewed-image:", "viewed-image::", " viewed-image "):
        try:
            registry.add_exemplar(subject.subject_id, vec, f"sha256:{provenance}",
                                  "/raw/IMG_9999.HEIC", confirmed_by=provenance,
                                  evidence=proof)
        except ValueError as exc:
            assert "memorize" in str(exc) or "Only" in str(exc), exc
            refused.append(provenance)
        else:
            raise AssertionError(f"{provenance!r} was allowed to become an exemplar")
    assert len(refused) == 14, refused
    assert subject.exemplars == [], subject.exemplars

    # both spellings of the ONE allowed provenance are accepted
    for spelling in ("viewed-image", "viewed-image:"):
        source = f"/raw/IMG_000{1 if spelling == 'viewed-image' else 2}.HEIC"
        added, _dropped = registry.add_exemplar(
            subject.subject_id, vec, f"sha256:{spelling}", source,
            confirmed_by=spelling, identity=IDENTITY,
            evidence=look_for(registry, source))
        assert added, spelling
    assert len(subject.exemplars) == 2, subject.exemplars
    assert all(e["confirmed_by"] == "viewed-image" for e in subject.exemplars), \
        "provenance must be normalized on write, so the file has one spelling"

    gates = {r["gate"] for r in registry.audit_trail()
             if r["decision"] == "refused"}
    assert gates == {"provenance"}, gates
    log(f"{len(refused)} provenances refused at the provenance gate, "
        "2 spellings of viewed-image accepted")


def case_the_cap_is_diversity_kept_not_oldest_first(tmp):
    """Twenty-four near-identical frames recognise one afternoon; twenty-four
    different ones recognise a subject. So the cap drops the most REDUNDANT
    exemplar, not the oldest."""
    registry = open_registry(make_pack(tmp))
    subject = registry.create_subject(name="Name-One", who="relation-word",
                                      active=["2029-03", None])
    subject.record["thresholds"] = {"exemplar_cap": 3}

    #  two well-separated exemplars, then a near-duplicate of the first
    for k, vec in enumerate((basis(0), basis(1), unit(basis(0) + 0.01 * basis(2)))):
        registry.add_exemplar(subject.subject_id, vec, f"sha256:{k}",
                              f"/raw/IMG_{k}.HEIC", confirmed_by="viewed-image",
                              identity=IDENTITY,
                              evidence=look_for(registry, f"/raw/IMG_{k}.HEIC"))
    assert len(subject.exemplars) == 3, subject.exemplars

    # a fourth, far from everything, must push out one of the near-duplicate
    # PAIR — never the distinct vectors, and never simply the oldest
    _added, dropped = registry.add_exemplar(
        subject.subject_id, basis(4), "sha256:3", "/raw/IMG_3.HEIC",
        confirmed_by="viewed-image", identity=IDENTITY,
        evidence=look_for(registry, "/raw/IMG_3.HEIC"))
    kept = [e["vec_ref"] for e in subject.exemplars]
    assert len(kept) == 3, kept
    assert dropped and dropped[0] in ("sha256:0", "sha256:2"), (dropped, kept)
    assert "sha256:1" in kept and "sha256:3" in kept, kept
    assert registry.vectors_for(subject.subject_id).shape == (3, DIM)
    log(f"cap 3: dropped {dropped}, kept {kept}")


def case_the_timeline_gate_reads_the_files_own_date(tmp):
    """Recognition Level 2, and the shortcut it exists to prevent.

    match() takes VECTORS and DATES. It is given no path, no folder and no
    dump name, so a matcher that inferred the era from a file's location
    cannot even be written here — the strays that sit in another era's folder
    are gated on their own capture date or not at all."""
    assert "path" not in inspect.signature(psub.Registry.match).parameters, \
        "match() must have no path to read an era off"

    registry = open_registry(make_pack(tmp))
    subject = seeded_subject(registry, basis(0), active=("2029-03", "2031-08"))
    X = np.stack([near(basis(0), 99)])

    inside = registry.match(X, [datetime(2030, 6, 1)])[0]
    assert inside["verdict"] == psub.VERDICT_ACCEPT, inside
    assert inside["subject_id"] == subject.subject_id, inside

    outside = registry.match(X, [datetime(2033, 6, 1)])[0]
    assert outside["verdict"] == psub.VERDICT_NONE and outside["eligible"] == 0, \
        outside

    # the source PATHS say one era and the dates say another: the dates win
    for exemplar in subject.exemplars:
        exemplar["source"] = "/raw/2033/" + Path(exemplar["source"]).name
    assert registry.match(X, [datetime(2030, 6, 1)])[0]["verdict"] == \
        psub.VERDICT_ACCEPT, "a path in the record changed a date-only decision"

    # an undated file is not eligible: an ungated match on no date is a guess
    assert registry.match(X, [None])[0]["verdict"] == psub.VERDICT_NONE
    log("in-range accept, out-of-range none, undated none, paths ignored")


def case_the_tolerance_widens_the_gate_and_does_not_remove_it(tmp):
    registry = open_registry(make_pack(tmp))
    subject = seeded_subject(registry, basis(0), active=("2030-01", "2030-01"))
    subject.record["thresholds"] = {"timeline_tolerance_days": 45}
    X = np.stack([near(basis(0), 99)])

    just_inside = registry.match(X, [datetime(2030, 2, 20)])[0]
    just_outside = registry.match(X, [datetime(2030, 4, 1)])[0]
    assert just_inside["verdict"] == psub.VERDICT_ACCEPT, just_inside
    assert just_outside["verdict"] == psub.VERDICT_NONE, just_outside
    # an END bound covers the whole of its last month, not just the 1st
    assert registry.match(X, [datetime(2030, 1, 31)])[0]["verdict"] == \
        psub.VERDICT_ACCEPT

    # no declared range at all: the gate can only exclude on evidence it has
    subject.record["active"] = [None, None]
    assert registry.match(X, [datetime(2099, 1, 1)])[0]["verdict"] == \
        psub.VERDICT_ACCEPT
    log("45-day tolerance binds on both sides; an undeclared range is ungated")


def case_thresholds_decide_accept_gray_and_none(tmp):
    """The three verdicts, and the per-subject override. The numbers are the
    DESIGN's STARTING values — this case pins the mechanism, not the tuning."""
    registry = open_registry(make_pack(tmp))
    assert registry.defaults["accept"] == 0.82
    assert registry.defaults["gray_low"] == 0.70
    subject = seeded_subject(registry, basis(0), count=1)
    when = [datetime(2030, 6, 1)]

    def score_for(cos):
        vec = unit(cos * basis(0) + float(np.sqrt(1 - cos * cos)) * basis(5))
        # the single exemplar is `near(basis(0), 3)`, so aim at IT, not at the
        # axis: the verdict must follow the cosine to the exemplar
        return registry.match(np.stack([vec]), when)[0]

    exemplar = registry.vectors_for(subject.subject_id)[0]

    def against_exemplar(cos):
        other = unit(basis(6) - float(basis(6) @ exemplar) * exemplar)
        vec = unit(cos * exemplar + float(np.sqrt(1 - cos * cos)) * other)
        return registry.match(np.stack([vec]), when)[0]

    assert against_exemplar(0.95)["verdict"] == psub.VERDICT_ACCEPT
    assert against_exemplar(0.75)["verdict"] == psub.VERDICT_GRAY
    assert against_exemplar(0.40)["verdict"] == psub.VERDICT_NONE
    assert score_for(1.0)["score"] is not None

    subject.record["thresholds"] = {"accept": 0.60, "gray_low": 0.30}
    assert against_exemplar(0.75)["verdict"] == psub.VERDICT_ACCEPT, \
        "a per-subject threshold must win over the pack default"
    log("accept / gray / none follow the thresholds, per subject")


def case_two_lookalike_subjects_are_a_question_never_a_merge(tmp):
    """Cardinality is never auto-resolved. A wrong merge mislabels both
    subjects forever and silently; a wrong split costs one extra question."""
    registry = open_registry(make_pack(tmp))
    a = seeded_subject(registry, basis(0), name="Name-One", start=0)
    b = seeded_subject(registry, basis(0), name="Name-Two", start=40)
    assert a.subject_id != b.subject_id

    verdict = registry.match(np.stack([near(basis(0), 99)]),
                             [datetime(2030, 6, 1)])[0]
    assert verdict["verdict"] == psub.VERDICT_QUESTION, verdict
    question = verdict["question"]
    assert question["auto_merge"] is False, question
    assert question["resolved_by"] == "human", question
    assert question["subject_ids"] == sorted([a.subject_id, b.subject_id]), question
    # nothing was merged: both subjects are still in the registry, untouched
    assert len(registry) == 2 and registry.get(a.subject_id) is not None
    assert len(a.exemplars) == 4 and len(b.exemplars) == 4
    log(f"question raised for {question['subject_ids']}, no merge")


def case_a_confirmed_subject_suppresses_a_new_draft(tmp):
    """F14 at the registry level, and the line between suppression and merge.

    A cluster that matches a CONFIRMED subject's exemplars opens no draft: the
    naming question it would have carried has already been answered. What the
    engine may do on that geometry is record a sighting — and nothing else. No
    name, no exemplar, no status change, and in particular no widening of the
    timeline the owner's answer set, because that would move the gate `match()`
    scores against on geometry with no human in the room."""
    registry = open_registry(make_pack(tmp))
    subject = seeded_subject(registry, basis(0), active=("2029-03", "2031-08"))
    before = {"active": list(subject.record["active"]),
              "exemplars": len(subject.exemplars), "status": subject.status,
              "name": subject.name}

    seen, state = registry.observe_draft_subject(
        unit(basis(0) + 0.2 * basis(5)), kind="class-word", batch=7, files=3,
        dates=["2035-01"], identity=IDENTITY, evidence={"batch": 7},
        seen_on=["classify/batch-07/samples/x.jpg"])

    assert state == "known", state
    assert seen.subject_id == subject.subject_id
    assert registry.drafts == [], [d.subject_id for d in registry.drafts]
    assert len(registry) == 1, "a second record was opened for a known subject"
    assert seen.record["active"] == before["active"], \
        "a confirmed timeline was widened on geometry alone"
    assert "contact_sheet" not in seen.record, \
        "a subject nobody will be asked about was given a contact sheet"
    assert len(seen.exemplars) == before["exemplars"], "geometry became evidence"
    assert seen.status == before["status"] and seen.name == before["name"]
    # what it DOES record: the sighting, and the score it was taken at
    assert seen.obs_count == 1 and seen.observed_in == [7]
    assert seen.record["evidence"][-1]["suppressed_at"] >= 0.85
    log(f"observed at {seen.record['evidence'][-1]['suppressed_at']}, "
        "recorded, not merged and not named")


def case_the_suppression_bar_is_its_own_parameter(tmp):
    """ONB-13a's fault (b) is a COUPLING, not a number: one threshold serving
    both a dedupe and a question rule means lowering it to group drafts also
    changes what gets asked. So the suppression reads
    `confirmed_suppress_tau` and nothing else — a dedupe tau at either extreme
    moves neither answer here."""
    same = unit(basis(0) + 0.33 * basis(5))              # cos ≈ 0.95 to basis(0)

    strict_dedupe = open_registry(make_pack(tmp, owner="one"))
    strict_dedupe.defaults.update(draft_dedupe_tau=0.999,
                                  confirmed_suppress_tau=0.90)
    seeded_subject(strict_dedupe, basis(0), count=2)
    _subject, state = strict_dedupe.observe_draft_subject(
        same, kind="class-word", batch=1, identity=IDENTITY)
    assert state == "known", "a dedupe tau of 0.999 blocked the suppression"

    loose_dedupe = open_registry(make_pack(tmp, owner="two"))
    loose_dedupe.defaults.update(draft_dedupe_tau=0.10,
                                 confirmed_suppress_tau=0.99)
    seeded_subject(loose_dedupe, basis(0), count=2)
    subject, state = loose_dedupe.observe_draft_subject(
        same, kind="class-word", batch=1, identity=IDENTITY)
    assert state == "new", "a dedupe tau of 0.10 suppressed on its own"
    assert subject.is_draft and subject.exemplars == []
    log("0.999 / 0.10 dedupe taus, unchanged suppression: the two bars are "
        "separate parameters")


def case_suppression_holds_the_same_guards_as_the_dedupe(tmp):
    """Two guards the suppression may not lose. A different `kind` is a
    different subject however close the vectors sit, and vectors from another
    model are not comparable at all — a comparison that scored them anyway
    would fail silently, one slightly wrong number at a time."""
    registry = open_registry(make_pack(tmp))
    seeded_subject(registry, basis(0), kind="class-word")

    subject, state = registry.observe_draft_subject(
        near(basis(0), 1), kind="other-class-word", batch=1, identity=IDENTITY)
    assert state == "new", "a different kind was suppressed as the same subject"
    assert subject.is_draft

    other_model = {**IDENTITY, "model_id": "another-model"}
    try:
        registry.observe_draft_subject(near(basis(0), 1), kind="class-word",
                                       batch=2, identity=other_model)
    except ValueError as exc:
        assert "not comparable" in str(exc), exc
    else:
        raise AssertionError("a cross-model centroid was scored anyway")
    log("kind guard holds; a foreign model refuses before anything is scored")


def case_a_subject_with_no_exemplars_suppresses_nothing(tmp):
    """The state F14 describes, kept testable. A confirmed subject that holds
    no exemplar is not recognisable — the suppression is exemplar-driven, not
    status-driven, because a status is a claim and an exemplar is a look."""
    registry = open_registry(make_pack(tmp))
    subject = registry.create_subject(name="Name-One", who="relation-word",
                                      kind="class-word", active=["2029-03", None])
    assert subject.status == psub.STATUS_CONFIRMED and subject.exemplars == []
    assert registry.confirmed_match(basis(0), kind="class-word") is None
    _draft, state = registry.observe_draft_subject(basis(0), kind="class-word",
                                                   batch=1, identity=IDENTITY)
    assert state == "new", state
    log("no exemplar, no suppression — which is the defect, stated as a test")


def case_forms_own_folder_is_derived_and_overridable(tmp):
    """The naming carve-out's only input. Derived from what the pack already
    holds — a stored default would either make the carve-out inert on every
    real pack (false) or decide a naming policy nobody signed (true)."""
    registry = open_registry(make_pack(tmp))
    draft = registry.create_subject(active=["2029-03", None])
    assert draft.forms_own_folder() is False, "an unnamed draft claims no folder"

    named_no_range = registry.create_subject(name="Name-Two")
    assert named_no_range.forms_own_folder() is False

    confirmed = registry.create_subject(name="Name-Three", active=["2029-03", None])
    assert confirmed.forms_own_folder() is True

    confirmed.record["forms_folder"] = False
    assert confirmed.forms_own_folder() is False, "an explicit false must win"
    draft.record["forms_folder"] = True
    assert draft.forms_own_folder() is True, "an explicit true must win"
    log("derived from name + active start; an explicit value wins either way")


def case_a_rename_keeps_the_key_and_the_ledger_resolves(tmp):
    """N-10a / N-6 from the registry's side: photo_recurrence does the keying,
    this is the caller that holds the confirmed entry."""
    registry = open_registry(make_pack(tmp))
    subject = seeded_subject(registry, basis(0), name="Name-One")

    before = registry.folder_for(subject.subject_id, "2031_01-05")
    registry.rename(subject.subject_id, "Name-Two")
    after = registry.folder_for(subject.subject_id, "2031_01-05")

    assert before["folder_name"] == "2031_01-05_Name-One", before
    assert after["folder_name"] == "2031_01-05_Name-Two", after
    assert before["key"] == after["key"], "the rename forked the folder"
    assert "Name-One" not in after["key"] and "Name-Two" not in after["key"]
    assert registry.rename_ledger() == {"Name-One": subject.subject_id,
                                        "Name-Two": subject.subject_id}

    # an unnamed subject still gets a folder, rendered from the caller's word
    draft = registry.create_subject(active=["2029-03", None])
    drafted = registry.folder_for(draft.subject_id, "2031_01-05",
                                  fallback_word="class-word")
    assert drafted["folder_name"] == "2031_01-05_class-word", drafted
    assert drafted["identity"] == draft.subject_id, drafted
    log(f"key {after['key']} survives the rename")


def case_subject_ids_are_unique_and_do_not_reuse(tmp):
    registry = open_registry(make_pack(tmp))
    first = registry.create_subject(name="Name-One")
    second = registry.create_subject(name="Name-Two")
    assert (first.subject_id, second.subject_id) == ("subj-0001", "subj-0002")
    try:
        registry.create_subject(subject_id="subj-0001")
    except ValueError as exc:
        assert "exists" in str(exc), exc
    else:
        raise AssertionError("a duplicate subject id was accepted")
    try:
        registry.create_subject(subject_id="Name-One")
    except ValueError as exc:
        assert "subj-0001" in str(exc), exc
    else:
        raise AssertionError("a rendered name was accepted as an identity")


def case_a_saved_registry_reloads_with_its_vectors_aligned(tmp):
    pack_dir = make_pack(tmp)
    registry = open_registry(pack_dir)
    subject = seeded_subject(registry, basis(0), count=5)
    registry.save()

    on_disk = json.loads((pack_dir / "photo-subjects" / "subjects.json").read_text())
    assert on_disk["embedding_identity"] == IDENTITY, on_disk["embedding_identity"]
    assert len(on_disk["subjects"]) == 1

    again = open_registry(pack_dir)
    assert len(again) == 1
    reloaded = again.get(subject.subject_id)
    assert len(reloaded.exemplars) == 5
    assert again.vectors_for(subject.subject_id).shape == (5, DIM)
    assert again.match(np.stack([near(basis(0), 99)]),
                       [datetime(2030, 6, 1)])[0]["verdict"] == psub.VERDICT_ACCEPT

    # a record whose vectors are one edit behind would score against the wrong
    # rows, silently — so it is a hard failure, not a best effort
    reloaded.exemplars.append({"vec_ref": "sha256:ghost", "source": "/raw/x",
                               "added": "2031-02-14",
                               "confirmed_by": "viewed-image"})
    again._vectors.clear()
    try:
        again.vectors_for(subject.subject_id)
    except ValueError as exc:
        assert "out of step" in str(exc), exc
    else:
        raise AssertionError("a misaligned record was accepted")


def case_a_registry_from_another_model_is_refused(tmp):
    """A text/image vector from another CLIP is not comparable to these, and
    the failure would be silent — every file would just score slightly wrong.
    The same refusal photo_recurrence makes between two indexes."""
    registry = open_registry(make_pack(tmp))
    seeded_subject(registry, basis(0))
    other = {**IDENTITY, "model_id": "some-other-model"}
    try:
        registry.match(np.stack([basis(0)]), [datetime(2030, 6, 1)], other)
    except ValueError as exc:
        assert "not comparable" in str(exc), exc
    else:
        raise AssertionError("vectors from two models were compared")
    # the matching identity, and no identity at all, both pass
    assert registry.match(np.stack([basis(0)]), [datetime(2030, 6, 1)],
                          IDENTITY)[0] is not None
    assert registry.match(np.stack([basis(0)]), [datetime(2030, 6, 1)])[0] is not None


def case_review_lists_and_prune_needs_go(tmp):
    pack_dir = make_pack(tmp)
    registry = open_registry(pack_dir)
    subject = seeded_subject(registry, basis(0), count=4)
    registry.save()

    env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
    listed = subprocess.run([PY, SCRIPT, "review", "--profile", str(pack_dir)],
                            capture_output=True, text=True, env=env)
    assert listed.returncode == 0, listed.stderr
    assert subject.subject_id in listed.stdout, listed.stdout
    assert "4/24" in listed.stdout, listed.stdout

    ref = subject.exemplars[0]["vec_ref"]
    dry = subprocess.run([PY, SCRIPT, "review", "--profile", str(pack_dir),
                          "--prune", "--drop", ref],
                         capture_output=True, text=True, env=env)
    assert "dry run" in dry.stdout, dry.stdout
    assert len(open_registry(pack_dir).subjects[0].exemplars) == 4, "a dry run wrote"

    done = subprocess.run([PY, SCRIPT, "review", "--profile", str(pack_dir),
                           "--prune", "--drop", ref, "--go"],
                          capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    after = open_registry(pack_dir)
    assert len(after.subjects[0].exemplars) == 3, after.subjects[0].exemplars
    assert after.vectors_for(after.subjects[0].subject_id).shape == (3, DIM)
    assert all(e["vec_ref"] != ref for e in after.subjects[0].exemplars)
    log("review lists; prune is a dry run until --go")


def observed_then_confirmed(registry, base, name="Name-Two", kind="class-word",
                            count=2):
    """A subject that arrived the way a real one does: observed as a draft
    (which is what puts a centroid in `draft-vectors/`), then confirmed with
    exemplars. `seeded_subject` skips the draft half, and the draft half is
    exactly what un-confirm has to give back."""
    subject, state = registry.observe_draft_subject(
        base, kind=kind, batch=1, files=6, dates=["2029-03"],
        identity=IDENTITY, evidence={"batch": 1, "files": 6},
        seen_on=["classify/batch-01/samples/one.jpg"])
    assert state == "new", state
    # The order `confirm` uses: the answer lands on the record, and only then
    # do its looks become exemplars. Gate 3 refuses the other order.
    subject.record.update({"name": name, "who": "relation-word",
                           "status": psub.STATUS_CONFIRMED,
                           "confirmed_by": "an operator"})
    for k in range(count):
        source = f"/raw/IMG_{80 + k:04d}.HEIC"
        registry.add_exemplar(subject.subject_id, near(base, 40 + k),
                              f"sha256:{name}-{k}", source,
                              confirmed_by="viewed-image", identity=IDENTITY,
                              evidence=look_for(registry, source),
                              captured=f"2029-03-0{k + 1} 09:1{k}")
    return subject


def case_an_exemplar_carries_the_capture_date_or_an_explicit_null(tmp):
    """SNS-10. `added` is when the vector was PROMOTED; `captured` is when the
    photograph was TAKEN. A store that holds only the first cannot say whether
    a subject's exemplars cover its life, which is the whole drift argument.

    The absent case is the one that matters: a substitute — `added`, today,
    an mtime — reads downstream as a real capture date, so absent is null."""
    registry = open_registry(make_pack(tmp))
    subject = registry.create_subject(name="Name-One", who="relation-word",
                                      active=["2029-03", None])

    for k, captured in enumerate(("2029-03-04 10:02", None, "")):
        source = f"/raw/IMG_{k:04d}.HEIC"
        registry.add_exemplar(subject.subject_id, near(basis(0), k),
                              f"sha256:{k}", source, added="2031-02-14",
                              confirmed_by="viewed-image", identity=IDENTITY,
                              evidence=look_for(registry, source),
                              captured=captured)
    held = subject.exemplars
    assert held[0]["captured"] == "2029-03-04 10:02", held[0]
    assert held[0]["added"] == "2031-02-14", "the two dates are two fields"
    assert len(held[0]["captured"]) > len("2029-03"), \
        "the full capture time is carried, never truncated to a month"
    for e in held[1:]:
        assert "captured" in e and e["captured"] is None, e
        assert e["added"] == "2031-02-14", "a missing capture date is never a "
    assert [r.get("captured") for r in registry.audit_trail()
            if r["decision"] == "memorized"] == ["2029-03-04 10:02", None, None]

    # a pack written before this field: readers tolerate its absence
    legacy = registry.create_subject(name="Name-Two", who="relation-word",
                                     active=["2029-03", None])
    legacy.exemplars.append({"vec_ref": "sha256:legacy", "source": "/raw/old.HEIC",
                             "added": "2030-01-01", "confirmed_by": "viewed-image",
                             "evidence": {}})
    registry._vectors[legacy.subject_id] = np.stack([near(basis(1), 1)])
    assert psub.review(registry)["count"] == 2
    log("captured is separate from added, null when absent, absent-tolerant")


def case_unconfirm_returns_a_subject_to_the_draft_pool(tmp):
    """Pattern 6's missing half. `prune` removes exemplars and `rename` moves
    a name; nothing reversed a STATUS, so a subject named wrongly was
    unreachable — `is_draft` keeps a confirmed record out of every question.

    What must come back is not the flag but the ability to be ASKED, and that
    needs the draft centroid too: without it the same animal in a later batch
    opens a second record instead of reinforcing this one."""
    pack_dir = make_pack(tmp)
    registry = open_registry(pack_dir)
    subject = observed_then_confirmed(registry, basis(2))
    subject_id = subject.subject_id
    registry.save()

    registry = open_registry(pack_dir)
    subject = registry.get(subject_id)
    assert not subject.is_draft and len(subject.exemplars) == 2, subject.record
    assert registry.draft_vectors_path(subject_id).exists(), "no centroid saved"

    result = registry.unconfirm(subject_id, by="an operator", reason="a test")
    assert subject.is_draft and subject.status == psub.STATUS_DRAFT
    assert subject in registry.drafts, "un-confirmed is not in the draft pool"
    assert result["was"] == "Name-Two" and result["draft_centroid"] is True
    assert len(result["exemplars_retained"]) == 2, result
    assert len(subject.exemplars) == 2, "the evidence is KEPT (owner's decision, 2026-08-16)"
    assert registry.vectors_for(subject_id).shape == (2, DIM), "vectors kept"
    assert subject.name is None and subject.who is None
    assert "confirmed_by" not in subject.record
    assert "withdrawn_exemplars" not in subject.record, \
        "nothing was removed, so there is nothing to make legible"
    assert registry.rename_ledger()["Name-Two"] == subject_id, \
        "a folder already written under the withdrawn name still resolves"
    assert registry.confirmed_match(near(basis(2), 41)) is None, \
        "a withdrawn subject suppresses nothing"

    # the centroid is what makes it askable ACROSS batches, not just present
    again, state = registry.observe_draft_subject(
        near(basis(2), 1), kind="class-word", batch=2, files=3,
        dates=["2029-04"], identity=IDENTITY, evidence={"batch": 2, "files": 3})
    assert state == "reinforced" and again.subject_id == subject_id, \
        (state, again.subject_id)
    # ⚠️ A reinforce is the ONE path that touches a withdrawn record while it
    # still holds evidence, and it writes a status. `ai-reinforced` is a draft
    # on both tests that matter, and neither may re-open on a sighting: a
    # subject re-confirmed by being photographed again is exactly the merge on
    # geometry this module never makes.
    assert again.status == psub.STATUS_REINFORCED and again.is_draft
    assert registry.recognisers == [], registry.recognisers
    assert registry.match(np.stack([near(basis(2), 41)]),
                          [datetime(2029, 3, 4)])[0]["subject_id"] is None

    registry.save()
    reloaded = open_registry(pack_dir)
    assert reloaded.get(subject_id).is_draft
    assert reloaded.vectors_for(subject_id).shape == (2, DIM), \
        "the vectors survive the round trip with the record"
    assert (Path(pack_dir) / "photo-subjects" / "vectors"
            / f"{subject_id}.npy").exists()
    trail = [r for r in reloaded.audit_trail() if r.get("decision") == "un-confirmed"]
    assert len(trail) == 1 and trail[0]["subject_id"] == subject_id, trail
    log(f"withdrew {result['was']}, kept {len(result['exemplars_retained'])} "
        "exemplar(s) and the centroid")


def case_a_withdrawn_subject_recognises_nothing(tmp):
    """The owner's choice, 2026-08-16, and the half of it that must never
    regress. The evidence stays on the record so re-confirming is cheap —
    which means the ONLY thing standing between a withdrawn identity and the
    files it used to claim is the status test in `recognisers`.

    The exemplars here are the same vectors that scored `accept` a moment
    ago. Nothing about the geometry changed; the yes did."""
    pack_dir = make_pack(tmp)
    registry = open_registry(pack_dir)
    subject = observed_then_confirmed(registry, basis(2))
    X = np.stack([near(basis(2), 40), near(basis(2), 41)])
    dates = [datetime(2029, 3, 4)] * 2

    before = registry.match(X, dates)
    assert all(v["subject_id"] == subject.subject_id for v in before), before
    assert all(v["verdict"] == psub.VERDICT_ACCEPT for v in before), before
    assert registry.recognisers == [subject]

    registry.unconfirm(subject.subject_id, by="an operator")
    assert len(subject.exemplars) == 2, "the fixture stopped testing the point"
    assert registry.recognisers == [], registry.recognisers
    after = registry.match(X, dates)
    assert all(v["subject_id"] is None for v in after), after
    assert all(v["eligible"] == 0 for v in after), after
    assert all(v["verdict"] == psub.VERDICT_NONE for v in after), after
    log("two files that scored accept now attribute to nobody, on the same "
        "vectors — status is the only thing that moved")


def case_re_confirming_costs_nothing(tmp):
    """What keeping the evidence buys. `attach_exemplars()`
    re-derives every vector from the dump's own `embed/` index, so a
    withdrawal that removed exemplars would be one-way the moment that index
    was cleaned — the owner who withdrew a name in one month could not get the
    recognition back in another.

    So the dump is GONE here — there is no work dir at all in this fixture —
    and re-confirming still restores recognition, because nothing has to be
    re-derived from anything."""
    pack_dir = make_pack(tmp)
    registry = open_registry(pack_dir)
    subject = observed_then_confirmed(registry, basis(6))
    subject_id = subject.subject_id
    X = np.stack([near(basis(6), 40)])
    dates = [datetime(2029, 3, 4)]

    registry.unconfirm(subject_id, by="an operator")
    registry.save()

    # a later session, from disk only
    registry = open_registry(pack_dir)
    subject = registry.get(subject_id)
    assert registry.match(X, dates)[0]["subject_id"] is None
    subject.record.update({"name": "Name-Three", "who": "relation-word",
                           "status": psub.STATUS_CONFIRMED})
    verdict = registry.match(X, dates)[0]
    assert verdict["subject_id"] == subject_id, verdict
    assert verdict["verdict"] == psub.VERDICT_ACCEPT, verdict
    assert verdict["name"] == "Name-Three", verdict
    assert len(subject.exemplars) == 2, subject.exemplars
    assert registry.confirmed_match(near(basis(6), 41)) is not None, \
        "suppression comes back with the confirmation"
    log("re-confirmed with no dump on disk: recognition returns from the "
        "evidence that was never thrown away")


def case_unconfirm_refuses_what_was_never_confirmed(tmp):
    """A withdrawal that invented a confirmation would be the mirror of the
    fault it fixes. Both refusals are audited: this file's rule is that the
    log records attempts, not successes."""
    registry = open_registry(make_pack(tmp))
    draft, _state = registry.observe_draft_subject(
        basis(3), kind="class-word", batch=1, files=2, dates=["2029-05"],
        identity=IDENTITY, evidence={"batch": 1, "files": 2})

    for subject_id, expect in ((draft.subject_id, "already"),
                               ("subj-9999", "no such subject")):
        try:
            registry.unconfirm(subject_id)
        except ValueError as exc:
            assert expect in str(exc), exc
        else:
            raise AssertionError(f"{subject_id} was withdrawn anyway")
    refused = [r for r in registry.audit_trail()
               if r.get("decision") == "refused" and r.get("gate") == "status"]
    assert len(refused) == 1, refused
    log("a draft and an unknown id are both refused, one of them audited")


def case_unconfirm_is_a_dry_run_until_go(tmp):
    """The operator verb, exposed like `--prune` and refusing to write on a
    dry run — `unconfirm()` audits at the decision point, so a dry run that
    ran it would move the pack snapshot."""
    pack_dir = make_pack(tmp)
    registry = open_registry(pack_dir)
    subject = observed_then_confirmed(registry, basis(4))
    registry.save()

    env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
    argv = [PY, SCRIPT, "review", "--profile", str(pack_dir),
            "--unconfirm", subject.subject_id]
    dry = subprocess.run(argv, capture_output=True, text=True, env=env)
    assert dry.returncode == 0, dry.stderr
    assert "would withdraw" in dry.stdout, dry.stdout
    assert not open_registry(pack_dir).get(subject.subject_id).is_draft, \
        "a dry run wrote"

    done = subprocess.run(argv + ["--go"], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    later = open_registry(pack_dir)
    after = later.get(subject.subject_id)
    assert after.is_draft and len(after.exemplars) == 2, after.record
    assert later.recognisers == [], "a withdrawn subject still recognises"
    log("--unconfirm is a dry run until --go, like --prune")


# ------------------------------------------------- SNS-1b: the partition ----

def frame(n, captured=None, batch=1):
    """One vision-confirmed look, in the shape `photo_see.memorize_batch()`
    records them — which is the shape a pick row addresses by `vec_ref`."""
    return {"path": f"/dump/IMG_{n:04d}.JPG", "sample": f"F{n:02d}.jpg",
            "provenance": "viewed-image:", "label": "Class-One",
            "vec_ref": f"sha256:frame-{n:02d}", "captured": captured,
            "see_report": f"/dump/classify/batch-{batch:02d}/see-report.json",
            "workdir": "/dump", "batch": batch, "run_id": "a-test"}


def observe_with_looks(registry, centroid, looks, batch=1, dates=("2029-03",),
                       kind="class-word", behind=25):
    """One cluster observation carrying its looks.

    `behind` is how many unseen files the cluster claims per frame — the ~200
    nobody looked at, which is exactly the attribution SNS-1b item 4 voids."""
    sheet = [f"classify/batch-{batch:02d}/samples/{look['sample']}"
             for look in looks]
    return registry.observe_draft_subject(
        centroid, kind=kind, batch=batch, files=len(looks) * behind,
        dates=list(dates), identity=IDENTITY,
        evidence={"batch": batch, "unit": "dump", "run_id": "a-test",
                  "files": len(looks) * behind, "looks": looks, "seen": sheet},
        seen_on=sheet)


def split_fixture(pack_dir):
    """A draft seen in two batches, holding four frames. -> (registry, id)."""
    registry = open_registry(pack_dir)
    parent, state = observe_with_looks(
        registry, basis(0), [frame(1, "2029-03-04 10:01"),
                             frame(2, "2029-03-04 10:02")],
        batch=1, dates=["2029-03"])
    assert state == "new", state
    again, state = observe_with_looks(
        registry, near(basis(0), 2), [frame(3, "2029-05-11 08:00", batch=2),
                                      frame(4, "2029-05-11 08:05", batch=2)],
        batch=2, dates=["2029-05"])
    assert state == "reinforced" and again.subject_id == parent.subject_id
    return registry, parent.subject_id


def no_name_outside_the_whitelists(registry):
    """The invariant the partition refusal exists to hold, stated the way
    `photo_plan.visual_columns()` reads it: a record whose status is in
    neither whitelist must hold no name, or that name renders as a confirmed
    answer with no `draft:` marker in front of it."""
    for subject in registry.subjects:
        if subject.name and not subject.is_draft:
            assert subject.status == psub.STATUS_CONFIRMED, subject.record


def case_a_draft_split_across_two_rows_is_superseded(tmp):
    """SNS-1b item 3, case C. Two `pick:` rows claim one draft's frames, so
    the draft becomes an audit record and each row becomes its own subject.

    The three things that make it a partition rather than a rename: each child
    carries its OWN first-sighting centroid, computed by the caller from that
    row's frames; each inherits only its own looks; and neither inherits the
    file count, because the split is proof that count was wrong."""
    pack_dir = make_pack(tmp)
    registry, parent_id = split_fixture(pack_dir)
    parent = registry.get(parent_id)
    parent_centroid = registry.draft_centroid(parent_id).copy()
    claimed_files = parent.record["files"]
    claimed_active = list(parent.record["active"])

    result = registry.partition_subject(parent_id, [
        {"vec_refs": ["sha256:frame-01", "sha256:frame-03"],
         "centroid": basis(1)},
        {"vec_refs": ["sha256:frame-02"], "centroid": basis(2)},
    ], by="an operator", reason="two subjects in one tile")

    assert result["case"] == "split", result
    first, second = (c["subject_id"] for c in result["children"])

    # the parent: out of the question loop, and still readable afterwards
    assert parent.status == psub.STATUS_SUPERSEDED and not parent.is_draft
    assert parent not in registry.drafts, "a superseded parent is still asked about"
    assert parent.record["split_into"] == [first, second], parent.record
    assert parent.name is None, "a superseded record may never hold a name"
    assert sum(len(e["looks"]) for e in parent.record["evidence"]) == 4, \
        "the parent keeps its whole evidence list — it is the audit trail"
    assert parent.record["files"] == claimed_files, "the parent's own count moved"
    assert parent.record["active"] == claimed_active
    assert np.allclose(registry.draft_centroid(parent_id), parent_centroid), \
        "the parent's first-sighting centroid was touched"

    # child one: two frames, from two different batches
    child = registry.get(first)
    assert child.is_draft and child in registry.drafts
    assert child.kind == "class-word" and child.name is None
    refs = [look["vec_ref"] for e in child.record["evidence"] for look in e["looks"]]
    assert refs == ["sha256:frame-01", "sha256:frame-03"], refs
    assert child.record["files"] == 2, \
        "a child inherited the parent's bulk attribution, which the split voids"
    assert child.record["observed_in"] == [1, 2], child.record
    assert child.record["obs_count"] == 2
    assert child.record["active"] == ["2029-03", "2029-05"], child.record
    assert child.record["contact_sheet"] == [
        "classify/batch-01/samples/F01.jpg",
        "classify/batch-02/samples/F03.jpg"], child.record
    assert child.record["origin"]["split_from"] == parent_id
    assert np.allclose(registry.draft_centroid(first), unit(basis(1))), \
        "the child is not carrying the centroid it was given"

    # child two: one frame, one batch, and a range narrower than the parent's
    other = registry.get(second)
    assert [look["vec_ref"] for e in other.record["evidence"]
            for look in e["looks"]] == ["sha256:frame-02"]
    assert other.record["files"] == 1 and other.record["observed_in"] == [1]
    assert other.record["active"] == ["2029-03", "2029-03"], other.record
    assert other.record["active"] != claimed_active, \
        "the active range was copied from the parent, not derived from the frames"
    assert other.record["evidence"][0]["files"] == 1, \
        "an inherited evidence entry still claims the parent cluster's file count"

    # frame 4 was picked by nobody: it defers with the parent and reaches no child
    for child_id in (first, second):
        assert not any(look["vec_ref"] == "sha256:frame-04"
                       for e in registry.get(child_id).record["evidence"]
                       for look in e["looks"])
    no_name_outside_the_whitelists(registry)

    registry.save()
    reloaded = open_registry(pack_dir)
    assert reloaded.get(parent_id).record["split_into"] == [first, second]
    assert reloaded.get(parent_id).status == psub.STATUS_SUPERSEDED
    assert np.allclose(reloaded.draft_centroid(first), unit(basis(1)))
    assert np.allclose(reloaded.draft_centroid(second), unit(basis(2)))
    assert np.allclose(reloaded.draft_centroid(parent_id), parent_centroid), \
        "the parent's centroid did not survive the round trip unchanged"
    trail = [r for r in reloaded.audit_trail()
             if r.get("decision") == "superseded"]
    assert len(trail) == 1 and trail[0]["split_into"] == [first, second], trail
    log(f"{parent_id} superseded by {first} + {second}; frame 4 defers")


def case_one_pick_row_is_never_a_split(tmp):
    """SNS-1b item 3, cases A and B — and the discriminator that separates
    them from C.

    ⭐ The test is ROWS, never coverage. One row that picks two of four frames
    leaves the other two DEFERRED (SNS-3, SNS-11); reading them as a second
    partition would turn the owner's silence into a decision, which is the
    failure this whole question shape exists to prevent."""
    registry, parent_id = split_fixture(make_pack(tmp))
    before = len(registry.subjects)

    # case A — one row, this subject only. Note there is no centroid on the
    # row at all: cases A and B mint nothing, so they need none.
    result = registry.partition_subject(
        parent_id, [{"vec_refs": ["sha256:frame-01", "sha256:frame-02"]}])
    assert result["case"] == "in-place" and result["children"] == [], result
    assert registry.get(parent_id).is_draft
    assert "split_into" not in registry.get(parent_id).record
    assert len(registry.subjects) == before, "case A minted a subject"

    # case B — the same row also names another subject: every member keeps its
    # id and is confirmed under the shared name (today's F15/F16 posture)
    result = registry.partition_subject(
        parent_id, [{"vec_refs": ["sha256:frame-01"],
                     "shared_with": ["subj-0099", "subj-0098"]}])
    assert result["case"] == "shared" and result["children"] == []
    assert result["shared_with"] == ["subj-0098", "subj-0099"], result
    assert registry.get(parent_id).is_draft
    assert len(registry.subjects) == before
    log("one row keeps the id whether or not it is shared; unpicked frames defer")


def case_a_partition_refuses_a_parent_that_holds_a_name(tmp):
    """The check that discriminates. `superseded` sits outside BOTH status
    whitelists, so `photo_plan.py:132`'s `name and not is_draft` would render
    a superseded record's name as a confirmed `who` with no `draft:` prefix —
    OA-15's silent-failure class one layer down.

    Enforced at the write point, because a named draft is reachable today:
    `rename()` writes a name on any status."""
    registry, parent_id = split_fixture(make_pack(tmp))
    parent = registry.get(parent_id)
    registry.rename(parent_id, "Name-Three")
    before = len(registry.subjects)
    rows = [{"vec_refs": ["sha256:frame-01"], "centroid": basis(1)},
            {"vec_refs": ["sha256:frame-02"], "centroid": basis(2)}]

    try:
        registry.partition_subject(parent_id, rows)
    except ValueError as exc:
        assert "Name-Three" in str(exc) and "draft:" in str(exc), exc
    else:
        raise AssertionError("a named draft was superseded")
    assert parent.is_draft and parent.name == "Name-Three"
    assert "split_into" not in parent.record
    assert len(registry.subjects) == before, "a refusal minted a child"
    no_name_outside_the_whitelists(registry)

    # ...and a CONFIRMED subject is not this verb's business either: two
    # subjects that turn out to be one, or one that turns out to be two after
    # it has been named, is SNS-14 and is not built.
    parent.record.update({"who": "relation-word",
                          "status": psub.STATUS_CONFIRMED})
    try:
        registry.partition_subject(parent_id, rows)
    except ValueError as exc:
        assert "not a draft" in str(exc) and "SNS-14" in str(exc), exc
    else:
        raise AssertionError("a confirmed subject was superseded")
    assert parent.status == psub.STATUS_CONFIRMED
    gates = [r["gate"] for r in registry.audit_trail()
             if r.get("decision") == "refused"]
    assert gates == ["named", "status"], gates
    log("a named or confirmed parent is refused, and nothing is written")


def case_a_child_never_inherits_the_parents_centroid(tmp):
    """The first ⛔ on SNS-1b's list. A first-sighting centroid describes a
    cluster the split just disproved, so it may not be recomputed and it may
    not be reassigned — which means a row that arrives without its own is
    REFUSED, never quietly given the parent's."""
    registry, parent_id = split_fixture(make_pack(tmp))
    before = len(registry.subjects)
    good = {"vec_refs": ["sha256:frame-01"], "centroid": basis(1)}

    for row, expect in (
            ({"vec_refs": ["sha256:frame-02"]}, "no centroid"),
            ({"vec_refs": ["sha256:frame-02"], "centroid": np.zeros(DIM)},
             "no usable centroid"),
            ({"vec_refs": ["sha256:frame-02"], "centroid": np.ones(DIM + 1)},
             "not comparable")):
        try:
            registry.partition_subject(parent_id, [good, row])
        except ValueError as exc:
            assert expect in str(exc), (expect, str(exc))
        else:
            raise AssertionError(f"a row with {expect} was accepted")
        assert len(registry.subjects) == before, "a refused partition minted"
        assert registry.get(parent_id).is_draft
        assert "split_into" not in registry.get(parent_id).record
    log("a group with no usable centroid is refused, never given the parent's")


def case_a_partition_refuses_frames_it_cannot_place(tmp):
    """A pick row that names a frame this subject does not hold, or one that
    two rows both claim, is a QUESTION rather than a partition — and an empty
    row decides nothing. Refused out loud in every case, in the pattern
    `attach_exemplars()` already uses: a set that quietly shrinks is how a
    split loses frames."""
    registry, parent_id = split_fixture(make_pack(tmp))
    before = len(registry.subjects)
    good = {"vec_refs": ["sha256:frame-01"], "centroid": basis(1)}

    for rows, expect in (
            ([], "at least one pick row"),
            ([good, {"vec_refs": [], "centroid": basis(2)}], "names no frame"),
            ([good, {"vec_refs": ["sha256:frame-99"], "centroid": basis(2)}],
             "which no look on this subject carries"),
            ([good, {"vec_refs": ["sha256:frame-01"], "centroid": basis(2)}],
             "is picked by rows 1 and 2"),
            # a row that both splits this subject and names another one is
            # cases B and C at once. Refused, never accepted with the sharing
            # silently dropped — OA-19 settled that it stays refused, and the
            # words it is refused with are their own case below.
            ([good, {"vec_refs": ["sha256:frame-02"], "centroid": basis(2),
                     "shared_with": ["subj-0099"]}],
             "both splits this subject and names")):
        try:
            registry.partition_subject(parent_id, rows)
        except ValueError as exc:
            assert expect in str(exc), (expect, str(exc))
        else:
            raise AssertionError(f"{expect!r} was accepted")
        assert len(registry.subjects) == before
        assert registry.get(parent_id).is_draft, "a refusal moved the status"
    assert [r["gate"] for r in registry.audit_trail()
            if r.get("decision") == "refused"] == (["groups"] + ["frames"] * 3
                                                   + ["shared"])
    log("unknown, duplicated and empty pick rows are all refused out loud")


def case_the_shared_refusal_teaches_the_two_row_answer(tmp):
    """OA-19. The row that both splits and names stays refused — that part is
    decided, not pending — but a refusal an owner cannot act on sends them
    back to the same row. So the refusal itself carries the remedy: the split
    on its own row, the naming on a row of its own, both nameable in one
    answer.

    Asserted on the WORDS, because the remedy is the whole change here: the
    gate, the reason code and the fact that nothing is written were all
    already right, and a test that only checks `it refused` passes just as
    happily against a message that leaves the owner stuck."""
    registry, parent_id = split_fixture(make_pack(tmp))
    before = len(registry.subjects)
    rows = [{"vec_refs": ["sha256:frame-01"], "centroid": basis(1)},
            {"vec_refs": ["sha256:frame-02"], "centroid": basis(2),
             "shared_with": ["subj-0098", "subj-0099"]}]

    why = registry.partition_refusal(parent_id, rows)
    assert why and "both splits this subject and names" in why, why
    # ⚠️ Asserted on the REMEDY clause, not on the sentence as a whole: the row
    # number and the ids were already in the diagnosis half, so a substring
    # test against either would pass on a message that names no remedy at all.
    assert "TWO rows" in why, why
    assert f"leave row 2 picking only its frames of {parent_id}" in why, why
    assert "naming of subj-0098, subj-0099 on a row of its own" in why, why
    assert "SAME answer" in why, why

    try:
        registry.partition_subject(parent_id, rows)
    except ValueError as exc:
        assert str(exc) == why, (str(exc), why)
    else:
        raise AssertionError("a row that splits AND names was accepted")

    # ⛔ still a refusal: nothing minted, nothing superseded, no sharing
    # quietly dropped so the split could go ahead anyway.
    assert len(registry.subjects) == before, "a refusal minted a child"
    parent = registry.get(parent_id)
    assert parent.is_draft and "split_into" not in parent.record, parent.record
    refused = [r for r in registry.audit_trail() if r.get("decision") == "refused"]
    assert [r["gate"] for r in refused] == ["shared"], refused

    # ...and the remedy it describes is one the storage actually performs.
    result = registry.partition_subject(parent_id, [
        rows[0], {k: v for k, v in rows[1].items() if k != "shared_with"}])
    assert result["case"] == "split", result
    assert len(result["children"]) == 2, result
    log("the shared refusal stands, and says how to write it as two rows")


def case_the_shared_refusal_names_every_bad_row(tmp):
    """REPRODUCTION (UAT02-02 F-o, Lead ruling 20260924). ⛔ FAILS on c5b6f99:
    the refusal returned at the FIRST row that both splits and names, so an
    owner who fixed it was refused again for the next (P-B07: the Birk row had
    the Lotus row's shape and was never looked at). Both rows are named now;
    the OA-19 gate itself is unchanged."""
    registry, parent_id = split_fixture(make_pack(tmp))
    rows = [{"vec_refs": ["sha256:frame-01"], "centroid": basis(1),
             "shared_with": ["subj-0098"]},
            {"vec_refs": ["sha256:frame-02"], "centroid": basis(2),
             "shared_with": ["subj-0099"]}]
    why = registry.partition_refusal(parent_id, rows)
    assert why and "pick row 1 both splits this subject and names subj-0098" in why, why
    assert "pick row 2 both splits this subject and names subj-0099" in why, why
    assert "leave rows 1, 2 picking only its frames" in why, why
    log("every row that both splits and names is named in one refusal")


def case_a_superseded_parent_is_not_revivable(tmp):
    """`unconfirm()` gates on `is_draft`, and `superseded` is outside that
    whitelist — so without a test of its own the withdrawal body would run on
    a split parent, put it back in the question loop with `ai-drafted`, and
    ask the owner about frames its children already carry.

    SNS-1b specifies no un-split verb and this is not one."""
    pack_dir = make_pack(tmp)
    registry, parent_id = split_fixture(pack_dir)
    result = registry.partition_subject(parent_id, [
        {"vec_refs": ["sha256:frame-01"], "centroid": basis(1)},
        {"vec_refs": ["sha256:frame-02"], "centroid": basis(2)}])
    child_id = result["children"][0]["subject_id"]

    try:
        registry.unconfirm(parent_id, by="an operator")
    except ValueError as exc:
        assert psub.STATUS_SUPERSEDED in str(exc) and child_id in str(exc), exc
    else:
        raise AssertionError("a split parent was returned to the question loop")
    assert registry.get(parent_id).status == psub.STATUS_SUPERSEDED
    assert registry.get(parent_id) not in registry.drafts
    registry.save()

    # the CLI says the same thing without raising, so one unwithdrawable id in
    # a list does not abort the rest of it
    env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
    done = subprocess.run([PY, SCRIPT, "review", "--profile", str(pack_dir),
                           "--unconfirm", parent_id, "--go"],
                          capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    assert f"already {psub.STATUS_SUPERSEDED}" in done.stdout, done.stdout
    assert open_registry(pack_dir).get(parent_id).status == psub.STATUS_SUPERSEDED
    log("un-confirm refuses a superseded parent, in the method and in the CLI")


def case_a_superseded_parent_cannot_be_promoted_onto(tmp):
    """Gate 3, extended to the status this build introduces.

    The gate reads `is_draft`, which `superseded` is not — and the path is the
    one commit 95df8eb measured: `photo_see.memorize_batch()` promotes on
    whatever `subject_id` a decision names, and the labels already on disk say
    a bare `viewed-image:` truthfully, earned before the split. Left alone, a
    split parent would gain exemplars nobody has a live yes for.

    ⛔ `rejected` used to be outside the same whitelist and was deliberately
    left there; step 3 closed it, and gate 3 is now a whitelist of
    `human-confirmed` rather than a list of statuses to exclude. The rejected
    half of that is its own case below."""
    registry, parent_id = split_fixture(make_pack(tmp))
    registry.partition_subject(parent_id, [
        {"vec_refs": ["sha256:frame-01"], "centroid": basis(1)},
        {"vec_refs": ["sha256:frame-02"], "centroid": basis(2)}])

    source = "/raw/IMG_7777.HEIC"
    try:
        registry.add_exemplar(parent_id, near(basis(0), 3), "sha256:after",
                              source, confirmed_by="viewed-image",
                              identity=IDENTITY,
                              evidence=look_for(registry, source))
    except ValueError as exc:
        assert psub.STATUS_SUPERSEDED in str(exc), exc
        assert "live human yes" in str(exc) or "human-confirmed" in str(exc), exc
    else:
        raise AssertionError("a superseded parent gained an exemplar")
    assert registry.get(parent_id).exemplars == []
    assert [r["gate"] for r in registry.audit_trail()
            if r.get("decision") == "refused"] == ["unconfirmed"]
    assert registry.recognisers == [], "a superseded record recognises something"
    log("gate 3 is a human-confirmed whitelist; superseded refuses on it")


def case_a_superseded_parent_cannot_be_renamed(tmp):
    """The other direction of the no-name rule, and the one the first review
    of this build caught: `partition_subject()` refusing a NAMED parent only
    covers the moment of the split, while `rename()` writes a name on any
    status it is handed. A name on a superseded record makes
    `name and not is_draft` true, so the plan prints a confirmed `who` with no
    `draft:` marker for a record whose children hold the same looks.

    The refused rename must also leave `previous_names` alone — a refusal
    that half-writes is the partial-write class this build refuses everywhere
    else."""
    registry, parent_id = split_fixture(make_pack(tmp))
    result = registry.partition_subject(parent_id, [
        {"vec_refs": ["sha256:frame-01"], "centroid": basis(1)},
        {"vec_refs": ["sha256:frame-02"], "centroid": basis(2)}])
    child_id = result["children"][0]["subject_id"]
    parent = registry.get(parent_id)

    try:
        registry.rename(parent_id, "Name-Nine")
    except ValueError as exc:
        assert psub.STATUS_SUPERSEDED in str(exc) and child_id in str(exc), exc
    else:
        raise AssertionError("a superseded parent took a name")
    assert parent.name is None, "a superseded record holds a name"
    assert parent.record.get("previous_names") in (None, []), parent.record
    assert not (parent.name and not parent.is_draft), (
        "photo_plan would render this as a confirmed who")
    assert [r["gate"] for r in registry.audit_trail()
            if r.get("decision") == "refused"] == ["superseded"]

    # the children are what the owner is meant to rename, and they still can be
    registry.rename(child_id, "Name-Nine")
    assert registry.get(child_id).name == "Name-Nine"
    log("rename refuses a superseded parent; its children rename normally")


def rejected_fixture(pack_dir, base=None):
    """A draft the owner rejected, in the state `photo_memory confirm`'s
    `skip:` path leaves it: status flipped, no name, its draft centroid still
    on disk. -> (registry, subject_id)."""
    registry = open_registry(pack_dir)
    subject, state = observe_with_looks(
        registry, base if base is not None else basis(0),
        [frame(1, "2029-03-04 10:01"), frame(2, "2029-03-04 10:02")],
        batch=1, dates=["2029-03"])
    assert state == "new", state
    subject.record["status"] = psub.STATUS_REJECTED
    subject.record["rejected"] = {"at": "2029-04-01", "by": "an operator",
                                  "src": "memory-review_C1.md Q1"}
    registry.save()
    return registry, subject.subject_id


def case_a_rejection_suppresses_on_its_retained_centroid(tmp):
    """⭐ OA-14, and it is the whole of it. A rejected record is in NEITHER
    `drafts` nor `recognisers`, so before this the owner's "never ask me about
    this again" survived exactly until the next dump: the same animal arrived
    as a cluster nothing matched, a fresh `subject_id` was minted, and the
    question came back under an id the owner had never seen.

    What the retained centroid may do is stop a question. What it may never do
    is name a file — `match()` reads `recognisers`, which is `human-confirmed`
    plus exemplars, and a rejection is neither. That asymmetry is what keeps
    V2-5a intact: the owner's decision is honoured, not extended."""
    pack_dir = make_pack(tmp)
    registry, rejected_id = rejected_fixture(pack_dir)
    before = {"active": list(registry.get(rejected_id).record["active"]),
              "sheet": list(registry.get(rejected_id).record["contact_sheet"])}

    # the same subject, a dump later: a reload, so the centroid is read off
    # disk rather than out of the writer's cache
    reloaded = open_registry(pack_dir)
    assert reloaded.get(rejected_id).status == psub.STATUS_REJECTED
    assert reloaded.drafts == [], "a rejected record is still in the draft pool"
    subject, state = observe_with_looks(
        reloaded, unit(basis(0) + 0.30 * basis(2)),
        [frame(9, "2030-01-02 09:00", batch=9)], batch=9, dates=["2030-01"])

    assert state == "rejected", state
    assert subject.subject_id == rejected_id, \
        "the rejected subject came back under a new id — OA-14 unfixed"
    assert len(reloaded) == 1, "a second record was opened for a rejection"
    # the suppressed write: the sighting and its score, and nothing else
    assert subject.record["evidence"][-1]["suppressed_at"] >= 0.85
    assert subject.record["active"] == before["active"], \
        "a rejected timeline was widened on geometry alone"
    assert subject.record["contact_sheet"] == before["sheet"], \
        "a subject nobody will be asked about grew a contact sheet"
    assert subject.status == psub.STATUS_REJECTED and subject.name is None
    # and it names nothing, ever
    assert reloaded.recognisers == [], "a rejection recognises something"
    assert reloaded.confirmed_match(unit(basis(0) + 0.30 * basis(2)),
                                    kind="class-word") is None
    no_name_outside_the_whitelists(reloaded)
    log(f"suppressed at {subject.record['evidence'][-1]['suppressed_at']} on a "
        "centroid that can stop a question and never name a file")


def case_a_live_draft_outscores_a_rejection(tmp):
    """The precedence rule, and it is the half that is easy to get wrong.

    A rejection suppresses only when nothing live explains the cluster better.
    Both sides are first-sighting centroids in one space, so they compare on
    one scale — and a cluster sitting closer to a LIVE draft would otherwise
    be absorbed by a rejection it merely resembles, taking a question the
    owner never answered with it. That is the silent error; the other
    direction only re-asks visibly."""
    pack_dir = make_pack(tmp, owner="one")
    registry, rejected_id = rejected_fixture(pack_dir)
    live, state = observe_with_looks(
        registry, basis(1), [frame(7, "2029-06-01 12:00", batch=3)],
        batch=3, dates=["2029-06"])
    assert state == "new" and live.subject_id != rejected_id

    # nearer the live draft than the rejection, and above both bars
    subject, state = observe_with_looks(
        registry, unit(basis(1) + 0.30 * basis(0)),
        [frame(8, "2029-06-02 12:00", batch=4)], batch=4, dates=["2029-06"])
    assert state == "reinforced", state
    assert subject.subject_id == live.subject_id, \
        "a rejection absorbed a cluster a live draft explained better"

    # and the other way round: nearer the rejection, so the rejection takes it
    subject, state = observe_with_looks(
        registry, unit(basis(0) + 0.30 * basis(1)),
        [frame(10, "2029-06-03 12:00", batch=5)], batch=5, dates=["2029-06"])
    assert state == "rejected" and subject.subject_id == rejected_id, state
    log("higher score wins; the rejection takes only what is nearest it")


def case_a_rejected_record_holds_no_name_and_gains_nothing(tmp):
    """OA-16's invariant, from the two doors that write onto a record.

    `rejected` is outside `is_draft` exactly like `superseded`, so a name on
    it makes `name and not is_draft` true and `photo_plan.py:132` prints it as
    a confirmed `who` with no `draft:` marker — for a subject the owner asked
    never to hear about again. And gate 3's status test is now a WHITELIST, so
    a promotion onto a rejection is refused for the reason it always should
    have been: there is no live human yes standing behind the identity."""
    pack_dir = make_pack(tmp)
    registry, rejected_id = rejected_fixture(pack_dir)
    subject = registry.get(rejected_id)

    try:
        registry.rename(rejected_id, "Name-Nine")
    except ValueError as exc:
        assert psub.STATUS_REJECTED in str(exc) and "--revive" in str(exc), exc
    else:
        raise AssertionError("a rejected record took a name")
    assert subject.name is None, "a rejected record holds a name"
    assert subject.record.get("previous_names") in (None, []), subject.record
    no_name_outside_the_whitelists(registry)

    source = "/raw/IMG_7777.HEIC"
    try:
        registry.add_exemplar(rejected_id, near(basis(0), 3), "sha256:after",
                              source, confirmed_by="viewed-image",
                              identity=IDENTITY,
                              evidence=look_for(registry, source))
    except ValueError as exc:
        assert psub.STATUS_REJECTED in str(exc), exc
        assert "live human yes" in str(exc) or "human-confirmed" in str(exc), exc
    else:
        raise AssertionError("a rejected record gained an exemplar")
    assert subject.exemplars == []
    assert registry.recognisers == []
    assert sorted(r["gate"] for r in registry.audit_trail()
                  if r.get("decision") == "refused") == ["rejected",
                                                         "unconfirmed"]
    log("rename and gate 3 both refuse a rejection, each in its own words")


def case_a_rejection_is_taken_back_by_revive_alone(tmp):
    """The handle on the inside of the door.

    A rejection that merely hid was a weak decision badly kept; a rejection
    that SUPPRESSES is a strong one, and a strong decision with no way back is
    the one-way door SNS-5's fourth job exists to forbid. `unconfirm()` is not
    that way back — there is no confirmation here to withdraw, and its body
    would write a withdrawn name onto a record that never held one."""
    pack_dir = make_pack(tmp)
    registry, rejected_id = rejected_fixture(pack_dir)

    try:
        registry.unconfirm(rejected_id, by="an operator")
    except ValueError as exc:
        assert psub.STATUS_REJECTED in str(exc) and "revive" in str(exc), exc
    else:
        raise AssertionError("un-confirm withdrew a rejection")
    assert registry.get(rejected_id).status == psub.STATUS_REJECTED

    centroid = registry.draft_centroid(rejected_id).copy()
    result = registry.revive(rejected_id, by="an operator", reason="a mistake")
    subject = registry.get(rejected_id)
    assert subject.status == psub.STATUS_DRAFT and subject.is_draft
    assert subject in registry.drafts
    assert result["draft_centroid"] is True
    assert np.allclose(registry.draft_centroid(rejected_id), centroid), \
        "the retained centroid was recomputed instead of reused"
    # the rejection is kept as history, not erased by the decision that
    # reversed it
    assert subject.record["revived"]["rejected"]["by"] == "an operator"
    assert subject.record["revived"]["reason"] == "a mistake"

    # it suppresses nothing now, and is asked about again
    assert registry.rejected_match(basis(0), kind="class-word") is None
    again, state = observe_with_looks(
        registry, unit(basis(0) + 0.30 * basis(2)),
        [frame(11, "2030-02-02 09:00", batch=6)], batch=6, dates=["2030-02"])
    assert state == "reinforced" and again.subject_id == rejected_id, state

    # and reviving twice is refused rather than quietly repeated
    try:
        registry.revive(rejected_id, by="an operator")
    except ValueError as exc:
        assert psub.STATUS_REJECTED in str(exc), exc
    else:
        raise AssertionError("a draft was revived")
    log("revive flips the status, keeps the centroid, and keeps the history")


def case_taking_a_decision_back_flags_it_for_the_question_loop(tmp):
    """SNS-5's third layer, at the registry end.

    Clearing the status re-opens the question for a NEW work dir, and
    `photo_memory.record_unconfirm()` / `record_revive()` clear the memory
    log — but the work dir where the wrong answer was typed still holds the
    review file that booked the id, and `photo_memory.asked_before()` reads
    it. Without this flag the subject was askable by `is_draft`, cleared in
    the log, and shut out by the file: withdrawn and invisible at once, which
    is the trap the other two layers were fixed to avoid.

    ⚠️ The flag is written, not derived. `unconfirmed` / `revived` are HISTORY
    and are kept forever, so a reader that used them would exempt the subject
    from the bar for the rest of the pack's life. This one is spent by the
    next answer (`photo_memory.cmd_confirm`, both answer paths)."""
    pack_dir = make_pack(tmp)
    registry = open_registry(pack_dir)
    subject = observed_then_confirmed(registry, basis(4))
    assert psub.REOPENED_FLAG not in subject.record, subject.record
    registry.unconfirm(subject.subject_id, by="an operator")
    assert subject.record[psub.REOPENED_FLAG] is True, subject.record
    registry.save()
    reloaded = open_registry(pack_dir).get(subject.subject_id)
    assert reloaded.record[psub.REOPENED_FLAG] is True, reloaded.record

    other, rejected_id = rejected_fixture(make_pack(tmp, owner="someone-else"))
    assert psub.REOPENED_FLAG not in other.get(rejected_id).record
    other.revive(rejected_id, by="an operator")
    assert other.get(rejected_id).record[psub.REOPENED_FLAG] is True

    # a refused call flags nothing — the record is exactly where it was
    for verb, subject_id in ((other.unconfirm, rejected_id),
                             (other.revive, rejected_id)):
        try:
            verb(subject_id)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{verb.__name__} was not refused")
    record = dict(other.get(rejected_id).record)
    assert record[psub.REOPENED_FLAG] is True and record["status"] == \
        psub.STATUS_DRAFT, record
    log("both verbs flag the record; a refusal flags nothing")


def case_the_reconfirmation_frame_budget_is_its_own_number(tmp):
    """SNS-9's "two budgets, not one", pinned so nobody merges them back.

    Re-presentation is UNCONDITIONAL and covers every remembered subject; new
    FSS are ranked and capped and DEFER what they cannot fit. One shared
    budget would either overflow before a single new subject was asked about
    or truncate the re-presentation — and a truncated re-presentation makes
    the word unconditional false, which takes the undo path with it."""
    keys = ("frames_per_reconfirmation", "contact_frames_per_draft",
            "drafts_rendered_per_question")
    for key in keys:
        assert key in psub.DEFAULT_THRESHOLDS, key
    assert psub.DEFAULT_THRESHOLDS["frames_per_reconfirmation"] == 2
    # and it is overridable from the pack like every other threshold, which is
    # where a number nobody has measured belongs
    pack_dir = make_pack(tmp)
    registry = open_registry(pack_dir)
    registry.data.setdefault("defaults", {})["frames_per_reconfirmation"] = 1
    registry.save()
    assert open_registry(pack_dir).defaults["frames_per_reconfirmation"] == 1
    log("the re-confirmation budget is its own parameter, and lives in the pack")


def case_revive_is_a_dry_run_until_go(tmp):
    """The CLI half, and the same two rules `--unconfirm` follows: nothing is
    written without `--go`, and an id that cannot be revived is reported
    rather than raised, so one bad id does not abort the rest of the list."""
    pack_dir = make_pack(tmp)
    registry, rejected_id = rejected_fixture(pack_dir)
    live, _state = observe_with_looks(
        registry, basis(3), [frame(12, "2029-07-01 10:00", batch=7)],
        batch=7, dates=["2029-07"])
    registry.save()
    env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}

    dry = subprocess.run([PY, SCRIPT, "review", "--profile", str(pack_dir),
                          "--revive", rejected_id, live.subject_id],
                         capture_output=True, text=True, env=env)
    assert dry.returncode == 0, dry.stderr
    assert "would take back the rejection" in dry.stdout, dry.stdout
    assert f"! {live.subject_id}" in dry.stdout, "a live draft was revivable"
    assert open_registry(pack_dir).get(rejected_id).status \
        == psub.STATUS_REJECTED, "a dry run wrote"

    done = subprocess.run([PY, SCRIPT, "review", "--profile", str(pack_dir),
                           "--revive", rejected_id, "--go"],
                          capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    assert "rejection taken back" in done.stdout, done.stdout
    after = open_registry(pack_dir)
    assert after.get(rejected_id).status == psub.STATUS_DRAFT
    # the memory log has to hear about it too, or the subject is askable by
    # status and still closed by `settled_subjects()`
    log_text = (pack_dir / "photo-memory-log.md").read_text(encoding="utf-8")
    assert f"| revived | {rejected_id}" in log_text, log_text[-400:]
    log("--revive: dry by default, and it clears the log line as well as the "
        "status")


def case_the_shipped_template_holds_no_subjects():
    """V2-6, checked on the file a new owner actually gets."""
    shipped = json.loads((TEMPLATE / "photo-subjects" / "subjects.json").read_text())
    assert shipped["subjects"] == [], shipped["subjects"]
    assert shipped["embedding_identity"] is None
    assert shipped["defaults"]["accept"] == psub.DEFAULT_THRESHOLDS["accept"]
    assert shipped["defaults"]["gray_low"] == psub.DEFAULT_THRESHOLDS["gray_low"]
    assert (TEMPLATE / "photo-subjects" / "vectors").is_dir()


# ---- D-25: the pack reaches `review` by three routes (LL-PHO-132) ----------
#
# LL-PHO-132's prescription, verbatim: "One case per route, named for the
# route." The lesson was written after 24 green cases, all bound by the env
# var, proved nothing about the collection route — so these five are named for
# the route they exercise and nothing else. Four are guards. The fourth,
# `_from_the_workspace_folder`, is the REPRODUCTION: it fails on the unfixed
# code, where `review` with no work dir had no collection.json to read and
# refused from the very folder photo-init tells the owner to stand in.


def workspace_with_collection(tmp, owner="someone"):
    """The layout photo-init produces: a workspace holding `Working Files/`,
    with collection.json and the pack both inside it, and one per-dump work
    dir beside them."""
    workspace = Path(tmp) / "workspace"
    working = workspace / "Working Files"
    working.mkdir(parents=True)
    pack_dir = make_pack(working / "photo-memory", owner=owner)
    (working / "202401__").mkdir()
    (working / "collection.json").write_text(json.dumps({
        "collection": "TESTBOX", "owner": owner,
        "memory_root": str(working / "photo-memory")}))
    return workspace, working, pack_dir


def _clean_env():
    return {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}


def _review(cwd, *args, env=None):
    return subprocess.run([PY, SCRIPT, "review", *args], capture_output=True,
                          text=True, cwd=str(cwd), env=env or _clean_env())


def case_route_profile_flag(tmp):
    workspace, _, pack_dir = workspace_with_collection(tmp)
    got = _review(tmp, "--profile", str(pack_dir))
    assert got.returncode == 0, got.stderr
    assert "subject registry:" in got.stdout, got.stdout
    log("--profile binds the pack")


def case_route_photo_profile_env(tmp):
    workspace, _, pack_dir = workspace_with_collection(tmp)
    env = {**_clean_env(), "PHOTO_PROFILE": str(pack_dir)}
    got = _review(tmp, env=env)
    assert got.returncode == 0, got.stderr
    assert "subject registry:" in got.stdout, got.stdout
    log("$PHOTO_PROFILE binds the pack")


def case_route_collection_json_via_workdir(tmp):
    workspace, working, _ = workspace_with_collection(tmp)
    got = _review(workspace, str(working / "202401__"))
    assert got.returncode == 0, got.stderr
    assert "subject registry:" in got.stdout, got.stdout
    log("collection.json binds the pack through a named work dir")


def case_route_collection_json_from_the_workspace_folder(tmp):
    """REPRODUCTION (D-25). No work dir, no --profile, no env var — standing in
    the workspace, which is where photo-init leaves the owner. On the unfixed
    code this exits non-zero with "no owner pack for this run"."""
    workspace, _, _ = workspace_with_collection(tmp)
    got = _review(workspace)
    both = got.stdout + got.stderr
    assert "no owner pack for this run" not in both, both
    assert got.returncode == 0, both
    assert "subject registry:" in got.stdout, got.stdout
    log("collection.json binds the pack from the workspace folder itself")


def case_route_none_still_fails_closed(tmp):
    """The other half of the same fix: self-location must not become a fourth
    route that guesses. Off any workspace, with nothing bound, the refusal is
    unchanged — Operational Rule 7's fail-closed behaviour is what D-09 and
    D-25 both singled out as correct."""
    bare = Path(tmp) / "nowhere"
    bare.mkdir()
    got = _review(bare)
    assert got.returncode != 0, got.stdout
    assert "no owner pack for this run" in got.stdout + got.stderr, got.stdout
    log("off a workspace the refusal is unchanged")


# ---- card (c): an absorb says which space decided it (LL-PHO-105) ---------


def absorb_fixture(tmp):
    """One draft close enough to be swept onto one confirmed subject.
    -> (registry, draft, confirmed)."""
    registry = open_registry(make_pack(tmp))
    draft, _state = observe_with_looks(
        registry, unit(basis(0) + 0.67 * basis(1)),
        [frame(4, "2029-05-01 10:00", batch=4)], batch=4, dates=["2029-05"])
    confirmed = seeded_subject(registry, basis(0), count=3)
    confirmed.record["status"] = psub.STATUS_CONFIRMED
    registry.defaults["sweep_absorb_tau"] = 0.80
    return registry, draft, confirmed


def case_an_absorb_records_the_space_it_ran_in(tmp):
    """REPRODUCTION. The absorbed list is where an owner reads an accept
    count, and LL-PHO-105's rule is that an accept count is never quoted
    without its space. The row said nothing, so `identity` and `clip` were
    indistinguishable on the page."""
    registry, draft, confirmed = absorb_fixture(tmp)
    absorbed = registry.sweep_absorb([confirmed.subject_id], by="an operator")
    assert [row["subject_id"] for row in absorbed] == [draft.subject_id], absorbed
    assert absorbed[0]["space"] == psub.SPACE_CLIP, absorbed[0]
    assert psub.absorbed_space(draft.record) == psub.SPACE_CLIP, draft.record
    assert confirmed.record["absorbed_drafts"][0]["space"] == psub.SPACE_CLIP
    entry = [r for r in registry.audit_trail() if r.get("decision") == "absorbed"]
    assert entry and entry[0]["space"] == psub.SPACE_CLIP, entry
    log("the sweep's absorb carries its space on the row, the parent and the audit")


def case_the_swept_space_is_the_one_that_ran(tmp):
    """The sweep compares a draft's `draft-vectors/` centroid against the
    CLIP exemplar store, and holds no identity branch — so `clip` here is a
    measurement of this code path, not a default anybody chose.

    ⛔ The point of the case: a pack that HOLDS identity vectors must not make
    this absorb read `identity`. That is LL-PHO-105 exactly — a space claimed
    from what the pack is equipped for rather than from what ran."""
    registry = open_registry(make_pack(tmp))
    draft, _state = observe_with_looks(
        registry, unit(basis(0) + 0.67 * basis(1)),
        [frame(4, "2029-05-01 10:00", batch=4)], batch=4, dates=["2029-05"])
    # A subject holding REAL identity exemplars, built the way the VS-3b cases
    # build one — so the pack genuinely has an identity space to be tempted by.
    confirmed = seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0),
                                        "Name-One")
    confirmed.record["status"] = psub.STATUS_CONFIRMED
    assert registry.identity_vectors_for(confirmed.subject_id) is not None, \
        "the fixture did not equip the pack, so this case proves nothing"
    assert [s.subject_id for s in registry.identity_recognisers] \
        == [confirmed.subject_id]

    registry.defaults["sweep_absorb_tau"] = 0.80
    absorbed = registry.sweep_absorb([confirmed.subject_id])
    assert absorbed, "the fixture absorbed nothing"
    assert absorbed[0]["space"] == psub.SPACE_CLIP, absorbed[0]
    assert psub.absorbed_space(draft.record) == psub.SPACE_CLIP, draft.record
    log("an identity-equipped pack does not make a CLIP sweep claim identity")


def case_an_unrecorded_space_is_never_guessed(tmp):
    """REPRODUCTION of the rendering half's contract. A row written before the
    space was stored has none, and must read as NOT RECORDED. ⛔ Backfilling
    `clip` because it probably was clip is the same claim LL-PHO-105 forbids:
    a space nobody measured, presented as if somebody had."""
    registry, draft, confirmed = absorb_fixture(tmp)
    registry.sweep_absorb([confirmed.subject_id])
    # an old row: everything an absorb wrote before this card existed
    draft.record["absorbed"].pop("space")
    assert psub.absorbed_space(draft.record) is None, draft.record
    # and the empty string a hand-edited pack could hold is not a space either
    draft.record["absorbed"]["space"] = ""
    assert psub.absorbed_space(draft.record) is None, draft.record
    assert psub.absorbed_space({}) is None
    assert psub.absorbed_space(None) is None
    log("an absent, empty or missing space reads as not recorded, never guessed")


def case_an_owner_answered_absorb_claims_no_space(tmp):
    """SNS-16's attach is a human answer, not a comparison — nothing was
    scored, so there is no space to name. It reads the same as `not recorded`
    through the accessor and is told apart by `answered`, which is how a
    renderer can say the two different things."""
    registry = open_registry(make_pack(tmp))
    known = seeded_subject(registry, basis(0), count=2)
    known.record.update({"status": psub.STATUS_CONFIRMED, "name": "Name-One"})
    draft, _state = observe_with_looks(
        registry, basis(3), [frame(7, "2030-01-02 09:00", batch=2)],
        batch=2, dates=["2030-01"])
    registry.attach_draft_to_subject(draft.subject_id, known.subject_id,
                                     ["sha256:frame-07"], by="an operator",
                                     reason="the owner said so")
    assert psub.absorbed_space(draft.record) is None, draft.record
    assert draft.record["absorbed"]["answered"] is True, draft.record
    assert "absorbed_at_score" not in draft.record, draft.record
    log("an owner-answered absorb names no space and says why")


def case_a_release_keeps_the_space_it_was_absorbed_in(tmp):
    """A release returns the record to the draft pool but does not rewrite
    history: what the absorb was decided in stays readable, because that is
    the fact the owner is undoing."""
    registry, draft, confirmed = absorb_fixture(tmp)
    registry.sweep_absorb([confirmed.subject_id], by="an operator")
    assert psub.absorbed_space(draft.record) == psub.SPACE_CLIP
    released = registry.release_absorbed(confirmed.subject_id, by="an operator")
    assert released == [draft.subject_id], released
    assert draft.status == psub.STATUS_DRAFT
    assert psub.absorbed_space(draft.record) == psub.SPACE_CLIP, draft.record
    log("the released record still says which space had absorbed it")



# --------------------------------------------------- U-1: the operator's door

def merge_cli(pack_dir, *argv):
    """`review --merge` as an operator runs it. A SUBPROCESS on purpose: what
    U-1 builds is a DOOR, and a case that calls `fold_subjects()` in-process
    walks straight past the thing that was missing — the verb was always there
    and always worked."""
    env = {k: v for k, v in os.environ.items() if k != "PHOTO_PROFILE"}
    return subprocess.run([PY, SCRIPT, "review", "--profile", str(pack_dir),
                           *argv], capture_output=True, text=True, env=env)


def entity_ids(pack_dir):
    """Every subject_id `photo-entities.json` still asserts an identity for.
    The twin is half the defect: a merge that fixed only `subjects.json` would
    leave this file naming two animals where the registry holds one, and it is
    the file a human reads."""
    entities = json.loads((pack_dir / "photo-entities.json").read_text())
    return sorted(r.get("subject_id")
                  for bucket in ("people", "pets")
                  for r in (entities.get(bucket) or []))


def confirmed_pair_with_entities(pack_dir, **kw):
    """`confirmed_pair`, plus the entities twin a real confirmation writes.
    `observed_then_confirmed` moves the registry only — it sets the record's
    status by hand — so a case about the twin has to put the twin there, or it
    asserts against a file that was empty for a reason unrelated to the fold."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import photo_memory

    registry, one, two = confirmed_pair(pack_dir, **kw)
    registry.save()
    entities = json.loads((pack_dir / "photo-entities.json").read_text()) \
        if (pack_dir / "photo-entities.json").exists() else {}
    for subject in (one, two):
        photo_memory.sync_entity(entities, subject, "an operator")
    (pack_dir / "photo-entities.json").write_text(
        json.dumps(entities, ensure_ascii=False, indent=2) + "\n")
    return registry, one, two


def case_merge_rejoins_one_animal_held_under_two_confirmed_ids(tmp):
    """⭐ THE REPRODUCTION. One animal, two `human-confirmed` records — the
    state a split leaves behind, and the state the pack was actually in.

    Naming SPEC N-10a keys a recurring-subject folder on `subject_id`, so two
    ids for one animal is two folder keys for one animal: the next dump sorts
    its photographs into whichever record happens to match, and no amount of
    renaming joins them because the name is not the key. The registry held the
    verb that fixes this (`fold_subjects()`, SNS-14) from step 7, but the only
    door onto it was a `recheck:` name collision on a live review table — so
    two subjects confirmed in an EARLIER round, which no checkpoint asks about
    again, could not be rejoined at all.

    What this asserts is the state AFTER, in both files, because both files
    are the subject model (Memory-System DESIGN) and a fix to one of them is
    the mutant this case exists to catch."""
    pack_dir = make_pack(tmp)
    registry, first, second = confirmed_pair_with_entities(pack_dir)
    assert entity_ids(pack_dir) == sorted([first.subject_id,
                                           second.subject_id]), \
        "the fixture did not write the twin"
    joined = len(first.exemplars) + len(second.exemplars)

    done = merge_cli(pack_dir, "--merge", second.subject_id, first.subject_id,
                     "--go", "--by", "an operator")
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)

    after = open_registry(pack_dir)
    live = [s for s in after.subjects if s.status == psub.STATUS_CONFIRMED]
    assert [s.subject_id for s in live] == [first.subject_id], \
        ("one animal is still two confirmed subjects",
         [(s.subject_id, s.status) for s in after.subjects])
    # ⛔ THE TWIN. This is the assertion that fails on a merge which fixes
    # `subjects.json` and forgets `photo-entities.json`.
    assert entity_ids(pack_dir) == [first.subject_id], \
        ("photo-entities.json still asserts two identities for one animal",
         entity_ids(pack_dir))
    # the losing id still resolves — every plan CSV and folder record written
    # under it before the fold keeps meaning something
    assert after.get(second.subject_id).subject_id == first.subject_id
    assert after.get_literal(second.subject_id).status \
        == psub.STATUS_MERGED_INTO
    assert after.rename_ledger()["Name-Two"] == first.subject_id
    assert after.vectors_for(first.subject_id).shape == (joined, DIM)
    log(f"{second.subject_id} rejoined {first.subject_id} from the CLI; "
        "both files hold one subject")


def case_merge_keeps_the_vector_rows_in_step_with_the_exemplars(tmp):
    """⛔ `vectors/<id>.npy` is (N, D) and POSITIONAL — row i IS exemplar i.

    A merge extends both lists from a second file, which makes it the one
    operation that can put them out of step, and out of step is SILENT: every
    later read is by index, an index that exists never looks wrong, and the
    registry goes on confidently attributing photographs to the wrong animal.

    So this case checks the pairing itself, not the count — it maps each
    exemplar's `vec_ref` to the vector it arrived with, and re-reads that
    pairing off disk after the fold. A build that appends the incoming rows
    without keeping them aligned to the incoming exemplars passes a length
    check and fails here."""
    pack_dir = make_pack(tmp)
    registry, first, second = confirmed_pair_with_entities(pack_dir)
    # ⚠️ THE FIXTURE HAS TO REACH THE DEDUPE BRANCH. The fold skips any
    # incoming exemplar whose `vec_ref` the winner already holds, so the rows
    # it appends are a SUBSET of the loser's array. With two subjects that
    # share nothing that subset is the whole array, `W[keep] == W`, and a
    # build that appended `W` instead of `W[keep]` is indistinguishable —
    # measured: that mutant passed all 83 cases until this shared look was
    # added. One photograph both records hold is what separates them.
    shared = "sha256:both-records-hold-this-look"
    for subject, offset in ((first, 200), (second, 300)):
        source = f"/raw/IMG_{offset:04d}.HEIC"
        registry.add_exemplar(subject.subject_id, near(basis(0), offset),
                              shared, source, confirmed_by="viewed-image",
                              identity=IDENTITY,
                              evidence=look_for(registry, source))
    registry.save()
    before = {}
    for subject in (second, first):
        # the winner LAST: both records hold `shared` under a different vector
        # (a `vec_ref` is a content sha, so this is one photograph memorised
        # twice), and the winner's copy is the one that survives the fold
        rows = registry.vectors_for(subject.subject_id)
        for index, exemplar in enumerate(subject.exemplars):
            before[exemplar["vec_ref"]] = rows[index].tolist()
    joined = len(first.exemplars) + len(second.exemplars) - 1
    assert len(before) == joined, (len(before), joined)

    done = merge_cli(pack_dir, "--merge", second.subject_id, first.subject_id,
                     "--go")
    assert done.returncode == 0, done.stderr

    after = open_registry(pack_dir)
    winner = after.get_literal(first.subject_id)
    rows = after.vectors_for(first.subject_id)
    assert len(rows) == len(winner.exemplars) == joined, \
        (len(rows), len(winner.exemplars), joined)
    assert [e["vec_ref"] for e in winner.exemplars].count(shared) == 1, \
        "the shared look was memorised twice"
    for index, exemplar in enumerate(winner.exemplars):
        assert rows[index].tolist() == before[exemplar["vec_ref"]], \
            (f"exemplar {exemplar['vec_ref']} at row {index} carries another "
             "exemplar's vector", index)
    log("every exemplar still sits on the vector row it arrived with")


def case_merge_is_a_dry_run_until_go(tmp):
    """The house rule for every verb that audits at the decision point: the
    dry run says what `--go` would do and writes nothing at all — not the
    registry, not the twin, not the audit log, whose line would move the pack
    snapshot."""
    pack_dir = make_pack(tmp)
    registry, first, second = confirmed_pair_with_entities(pack_dir)
    before = (pack_dir / "photo-subjects" / "subjects.json").read_text()

    dry = merge_cli(pack_dir, "--merge", second.subject_id, first.subject_id)
    assert dry.returncode == 0, dry.stderr
    assert "dry run" in dry.stdout, dry.stdout
    assert first.subject_id in dry.stdout and second.subject_id in dry.stdout
    assert (pack_dir / "photo-subjects" / "subjects.json").read_text() \
        == before, "a dry run wrote the registry"
    assert entity_ids(pack_dir) == sorted([first.subject_id,
                                           second.subject_id]), \
        "a dry run wrote the twin"
    assert open_registry(pack_dir).get_literal(second.subject_id).status \
        == psub.STATUS_CONFIRMED
    log("--merge predicts the fold and writes nothing until --go")


def case_merge_refuses_and_exits_2_without_writing(tmp):
    """Four refusals, each naming the id it is about and the way on — and each
    exiting 2, which is a REFUSAL and not a break, so a caller can tell "I said
    no" apart from "I fell over".

    ⛔ The self-merge refusal is the one worth reading. It is not "you typed the
    same id twice": `fold_refusal()` resolves both ids first, so an alias and
    the subject it points at are also one record, and folding an id into the
    winner it already reaches is a no-op the operator should be told about
    rather than a fold that appears to work."""
    pack_dir = make_pack(tmp)
    registry, first, second = confirmed_pair_with_entities(pack_dir)
    draft, _state = registry.observe_draft_subject(
        basis(2), kind="class-word", batch=1, files=3, dates=["2029-03"],
        identity=IDENTITY, evidence={"batch": 1, "files": 3})
    registry.save()
    before = (pack_dir / "photo-subjects" / "subjects.json").read_text()

    for argv, expect in (
            # a subject into itself
            ([first.subject_id, first.subject_id], "only subject named here"),
            # a record that is not human-confirmed
            ([draft.subject_id, first.subject_id], psub.STATUS_DRAFT),
            # a target that does not exist
            ([first.subject_id, "subj-9999"], "no such subject"),
            # the two ids the wrong way round: the EARLIER id wins a fold, so
            # this would keep the record the operator called the source.
            # Refused rather than silently corrected.
            ([first.subject_id, second.subject_id], "the other way round")):
        refused = merge_cli(pack_dir, "--merge", *argv, "--go")
        assert refused.returncode == 2, (argv, refused.returncode,
                                         refused.stdout, refused.stderr)
        assert expect in refused.stdout, (argv, refused.stdout)
        assert (pack_dir / "photo-subjects" / "subjects.json").read_text() \
            == before, (argv, "a refusal wrote")
        assert entity_ids(pack_dir) == sorted([first.subject_id,
                                               second.subject_id]), argv
    log("four refusals, each exit 2, none of them wrote")


def case_merge_applies_the_cap_the_way_prune_does(tmp):
    """A join can push a subject over `exemplar_cap`, and what runs then is the
    same diversity-keeping eviction `--prune` runs — the redundant exemplar
    goes, not the oldest. Two views of one animal should leave the DIVERSE set
    behind, which is the whole reason the cap is not oldest-first."""
    pack_dir = make_pack(tmp)
    registry, first, second = confirmed_pair_with_entities(pack_dir,
                                                           counts=(3, 4))
    first.record.setdefault("thresholds", {})["exemplar_cap"] = 4
    registry.save()

    done = merge_cli(pack_dir, "--merge", second.subject_id, first.subject_id,
                     "--go")
    assert done.returncode == 0, done.stderr
    assert "evicted for redundancy at the cap" in done.stdout, done.stdout

    after = open_registry(pack_dir)
    winner = after.get_literal(first.subject_id)
    assert len(winner.exemplars) == 4, winner.exemplars
    assert after.vectors_for(first.subject_id).shape == (4, DIM)
    log("the cap runs on the joined set, and the vectors follow the eviction")


NEEDS_TMP = {
    "U-1 — --merge rejoins one animal held under two confirmed ids",
    "U-1 — the merged vector rows stay in step with the exemplars",
    "U-1 — --merge is a dry run until --go",
    "U-1 — a refused merge exits 2 and writes nothing",
    "U-1 — a merge applies the exemplar cap the way --prune does",
    "D-25 route — the pack binds by --profile",
    "D-25 route — the pack binds by $PHOTO_PROFILE",
    "D-25 route — the pack binds by collection.json via the work dir",
    "D-25 route — the pack binds by collection.json from the workspace folder",
    "D-25 route — nothing bound, off a workspace: still fails closed",
    "card (c) — an absorb records the space it ran in",
    "card (c) — the recorded space is the one that ran",
    "card (c) — an unrecorded space is never guessed",
    "card (c) — an owner-answered absorb claims no space",
    "card (c) — a release keeps the space it was absorbed in",
    "A19 — an ungated suppression is marked and counted apart",
    "A19 — a gated suppression is marked true and counts nothing",
    "A19 — an undated cluster is ungated, not given the benefit of the doubt",
    "A19 — the ungated share sums the way display_files does",
    "VS-3b — identity vectors ride along and persist",
    "VS-3b — a rebuilt identity index is not a pipeline change",
    "VS-3b — a real pipeline change is still refused, and named",
    "VS-3b — a pack never stores a build timestamp as its space",
    "VS-3b — a pack without identity vectors scores in the CLIP space",
    "VS-3b — the identity space decides on a floor AND a margin",
    "VS-3b — identity suppression overrules the CLIP space",
    "VS-3b — an exemplar may be gained without being identity evidence",
    "VS-3b — a zero identity row is 'no subject', not a bad match",
    "VS-3b — two identity pipelines are refused",
    "VS-3b — a confirmed subject the identity space cannot use is named",
    "VS-3b — a pack that never ran the identity stage is not a defect",
    "SNS-16 — a draft joins a remembered subject and moves nothing else",
    "SNS-16 — a promotion refuses what it cannot attest",
    "step 9 — the partition refusal speaks for the verb",
    "step 9 — the audit log is provenance, and not pack state",
    "an empty pack is a strict no-op",
    "only viewed-image provenance may become an exemplar",
    "the exemplar cap is diversity-kept, not oldest-first",
    "the timeline gate reads the file's own date, never a path",
    "the tolerance widens the gate and does not remove it",
    "thresholds decide accept / gray / none",
    "two lookalike subjects are a question, never a merge",
    "F14 — a confirmed subject suppresses a new draft, and merges nothing",
    "the suppression bar is its own parameter, not the dedupe's",
    "suppression keeps the kind guard and the cross-model refusal",
    "a confirmed subject with no exemplars suppresses nothing",
    "forms_own_folder is derived and overridable",
    "a rename keeps the key and the ledger resolves it",
    "subject ids are unique and never reused",
    "a saved registry reloads with its vectors aligned",
    "a registry from another model is refused",
    "review lists, and prune needs --go",
    "SNS-10 — an exemplar carries the capture date, or an explicit null",
    "SNS-5 — un-confirm returns a subject to the draft pool, centroid and all",
    "a withdrawn subject recognises nothing, on the evidence it kept",
    "re-confirming costs nothing — no dump, no re-derivation",
    "un-confirm refuses what was never confirmed",
    "--unconfirm is a dry run until --go",
    "SNS-1b — a draft split across two rows is superseded",
    "one pick row is never a split, however few frames it names",
    "a partition refuses a parent that holds a name",
    "a child never inherits the parent's centroid",
    "a partition refuses frames it cannot place",
    "OA-19 — the shared refusal teaches the two-row answer",
    "F-o: the shared refusal names every bad row (REPRO)",
    "a superseded parent is not revivable",
    "a superseded parent cannot be promoted onto",
    "a superseded parent cannot be renamed",
    "OA-14 — a rejection suppresses on its retained centroid",
    "a live draft outscores a rejection",
    "OA-16 — a rejected record holds no name and gains nothing",
    "a rejection is taken back by revive alone",
    "--revive is a dry run until --go",
    "SNS-5 — taking a decision back flags the record for the question loop",
    "SNS-9 — the re-confirmation frame budget is its own number",
    "SNS-15 — the sweep bar is its own parameter, and keeps the kind guard",
    "SNS-15 — an absorbed record cannot be renamed",
    "SNS-14 — the fold keeps the earlier id and joins the exemplars",
    "SNS-14 — a chained fold never points a tombstone at a tombstone",
    "SNS-14 — a fold is refused across kinds and onto a closed record",
    "SNS-14 — a tombstone refuses every verb and never moves the winner",
    "the rename ledger resolves by precedence, not by list order",
    "SNS-15 — the absorbed count is summed at read time and un-summed",
}

def case_the_sweep_bar_is_its_own_parameter_and_keeps_the_kind_guard(tmp):
    """SNS-15. The sweep scores a draft's retained FIRST-SIGHTING centroid
    against the exemplars a human yes promoted — two different inputs from the
    two comparisons on either side of it, which is why it carries its own
    `{sweep_absorb_tau}` and reads neither neighbour.

    Two things it must not do, and both are safety rather than tuning: absorb
    across `kind` (two kinds are two subjects however close their vectors sit),
    and write anything onto the subject that absorbed. Absorption declines to
    ask a question; it never adds evidence."""
    registry = open_registry(make_pack(tmp))
    # ⚠️ The drafts exist BEFORE the confirmation, which is the whole case:
    # F14 keeps a cluster that already matches a confirmed subject from ever
    # opening a record, so the only drafts a sweep can find are the ones that
    # predate the yes. That is what `confirmed_match()` cannot reach.
    near_bar = unit(basis(0) + 0.67 * basis(1))
    same, _state = observe_with_looks(
        registry, near_bar,
        [frame(4, "2029-05-01 10:00", batch=4)], batch=4, dates=["2029-05"])
    other_kind, _state = observe_with_looks(
        registry, near_bar,
        [frame(5, "2029-05-02 10:00", batch=5)], batch=5, dates=["2029-05"],
        kind="another-class-word")
    far, _state = observe_with_looks(
        registry, basis(9), [frame(6, "2029-05-03 10:00", batch=6)],
        batch=6, dates=["2029-05"])
    confirmed = seeded_subject(registry, basis(0), count=3)
    confirmed.record["status"] = psub.STATUS_CONFIRMED
    before = {"active": list(confirmed.record["active"]),
              "exemplars": len(confirmed.exemplars)}

    # strict at the shipped bar: nothing moves
    assert registry.sweep_absorb([confirmed.subject_id]) == []
    registry.defaults["sweep_absorb_tau"] = 0.80
    # ...and `confirmed_suppress_tau` is left where it was, so an absorption
    # here can only have come from the sweep's own number.
    absorbed = registry.sweep_absorb([confirmed.subject_id], by="an operator")

    assert [row["subject_id"] for row in absorbed] == [same.subject_id], absorbed
    assert absorbed[0]["into"] == confirmed.subject_id
    assert same.status == psub.STATUS_ABSORBED
    assert other_kind.status == psub.STATUS_DRAFT, \
        "the sweep absorbed across kinds"
    assert far.status == psub.STATUS_DRAFT
    assert len(confirmed.exemplars) == before["exemplars"], \
        "the sweep promoted an exemplar"
    assert confirmed.record["active"] == before["active"], \
        "the sweep widened a confirmed timeline on geometry"
    assert same.name is None and same.exemplars == []
    no_name_outside_the_whitelists(registry)

    # the release, which is what makes the write legal
    released = registry.release_absorbed(confirmed.subject_id, by="an operator")
    assert released == [same.subject_id], released
    assert same.status == psub.STATUS_DRAFT
    assert same.record[psub.REOPENED_FLAG] is True
    log(f"absorbed {same.subject_id} at {absorbed[0]['score']} on its own bar, "
        "left the other kind alone, wrote nothing onto the subject, released")


def case_an_absorbed_record_cannot_be_renamed(tmp):
    """The same door the other two out-of-whitelist statuses hold. `absorbed`
    is outside `is_draft`, so a name written onto one would render as a second
    confirmed identity for the subject the owner named once — with no `draft:`
    marker in front of it."""
    registry = open_registry(make_pack(tmp))
    same, _state = observe_with_looks(
        registry, unit(basis(0) + 0.67 * basis(1)),
        [frame(4, "2029-05-01 10:00", batch=4)], batch=4, dates=["2029-05"])
    confirmed = seeded_subject(registry, basis(0), count=3)
    confirmed.record["status"] = psub.STATUS_CONFIRMED
    registry.defaults["sweep_absorb_tau"] = 0.80
    registry.sweep_absorb([confirmed.subject_id])

    try:
        registry.rename(same.subject_id, "Name-Two")
    except ValueError as exc:
        assert "absorbed" in str(exc) and confirmed.subject_id in str(exc), exc
        assert "withdraw" in str(exc), "the refusal did not name the way on"
    else:
        raise AssertionError("an absorbed record took a name")
    assert same.name is None
    gates = {r.get("gate") for r in registry.audit_trail()
             if r.get("decision") == "refused"}
    assert "absorbed" in gates, gates
    log("a rename onto an absorbed record is refused, and says which subject "
        "holds the name and how to get it back")


def confirmed_pair(pack_dir, first="Name-One", second="Name-Two",
                   counts=(2, 5), kinds=("class-word", "class-word")):
    """Two subjects that arrived the way real ones do — observed as drafts,
    then confirmed with exemplars — which is the only state SNS-14's fold is
    ever offered. The SECOND one deliberately holds MORE exemplars, so a build
    that picked the winner by evidence would pick it."""
    registry = open_registry(pack_dir)
    one = observed_then_confirmed(registry, basis(0), name=first,
                                  kind=kinds[0], count=counts[0])
    two = observed_then_confirmed(registry, basis(5), name=second,
                                  kind=kinds[1], count=counts[1])
    return registry, one, two


def case_the_fold_keeps_the_earlier_id_and_joins_the_exemplars(tmp):
    """SNS-14. Two subjects confirmed in different rounds under different
    names, which the owner has since said are one animal.

    ⭐ **The earlier id wins, and the argument order does not vote.** The loser
    here holds more than twice the winner's exemplars, so a rule that read the
    evidence would flip — and would flip again the next time the cap evicted,
    which is why the SPEC forbids it. The ids are minted in order and never
    reused, so the lower one is the one already sitting in the plan CSVs and
    folder records this fold must not invalidate."""
    pack_dir = make_pack(tmp)
    registry, first, second = confirmed_pair(pack_dir)
    first.record.update({"active": ["2029-03", "2029-05"], "files": 20})
    second.record.update({"active": ["2029-01", "2029-07"], "files": 12})
    registry.save()
    assert len(second.exemplars) > len(first.exemplars), "the fixture is backwards"
    joined = len(first.exemplars) + len(second.exemplars)

    result = registry.fold_subjects([second.subject_id, first.subject_id],
                                    name="Name-Two", who="relation-word",
                                    by="an operator")

    assert result["winner"] == first.subject_id, result
    assert second.status == psub.STATUS_MERGED_INTO, second.record
    assert second.record["merged_into"] == first.subject_id
    assert second.exemplars == [] and second.name is None, second.record
    assert len(first.exemplars) == joined, "the exemplars did not concatenate"
    assert first.name == "Name-Two", first.record
    assert "Name-One" in first.previous_names, first.previous_names
    # the one fact a fold widens, and it never narrows: the union of the two
    # declared ranges, not the winner's
    assert first.record["active"] == ["2029-01", "2029-07"], first.record
    # an id written into a plan before the fold still means something
    assert registry.get(second.subject_id).subject_id == first.subject_id
    assert registry.get_literal(second.subject_id).status \
        == psub.STATUS_MERGED_INTO
    ledger = registry.rename_ledger()
    assert ledger["Name-One"] == ledger["Name-Two"] == first.subject_id, ledger
    # SNS-15's read-time sum covers the fold too: one subject, both counts
    assert registry.display_files(first) == 32, registry.display_files(first)

    registry.save()
    reloaded = open_registry(pack_dir)
    assert not registry.vectors_path(second.subject_id).exists(), \
        "the tombstone kept its vectors"
    assert reloaded.vectors_for(first.subject_id).shape == (joined, DIM)
    assert reloaded.get(second.subject_id).subject_id == first.subject_id

    # ...and the cap runs AFTER the concatenation, on the joined set
    other = open_registry(make_pack(tmp, owner="someone-else"))
    third = observed_then_confirmed(other, basis(0), name="Name-Three", count=3)
    fourth = observed_then_confirmed(other, basis(5), name="Name-Four", count=4)
    third.record.setdefault("thresholds", {})["exemplar_cap"] = 4
    capped = other.fold_subjects([third.subject_id, fourth.subject_id],
                                 name="Name-Four")
    assert len(third.exemplars) == 4, third.exemplars
    assert len(capped["dropped_for_cap"]) == 3, capped
    log(f"{second.subject_id} folded into {first.subject_id} with "
        f"{joined} exemplar(s); the cap evicts for redundancy afterwards")


def case_a_chained_fold_never_points_a_tombstone_at_a_tombstone(tmp):
    """A→B, then B→C. The first tombstone must follow the second fold, or the
    pack holds a chain — and a chain is a walk that can be cut short, mis-read
    or looped by anything that edits the file.

    So the compression happens in STORAGE at fold time, and the depth guard in
    `resolve_merged()` is the belt for a pack somebody edited by hand."""
    registry = open_registry(make_pack(tmp))
    one = observed_then_confirmed(registry, basis(0), name="Name-A", count=1)
    two = observed_then_confirmed(registry, basis(3), name="Name-B", count=1)
    three = observed_then_confirmed(registry, basis(6), name="Name-C", count=1)

    registry.fold_subjects([two.subject_id, three.subject_id], name="Name-B")
    assert three.record["merged_into"] == two.subject_id
    registry.fold_subjects([one.subject_id, two.subject_id], name="Name-A")

    assert two.record["merged_into"] == one.subject_id
    assert three.record["merged_into"] == one.subject_id, \
        ("a tombstone points at a tombstone", three.record)
    assert registry.get(three.subject_id).subject_id == one.subject_id
    ledger = registry.rename_ledger()
    assert ledger["Name-C"] == one.subject_id, ledger
    assert not [s for s in registry.subjects
                if s.record.get("merged_into") == two.subject_id]

    # a hand-edited pack: the walk refuses rather than answering
    loop = psub.Registry(data={"version": 1, "subjects": [
        {"subject_id": "subj-0001", "status": psub.STATUS_MERGED_INTO,
         "merged_into": "subj-0002"},
        {"subject_id": "subj-0002", "status": psub.STATUS_MERGED_INTO,
         "merged_into": "subj-0001"}]})
    try:
        loop.get("subj-0001")
    except ValueError as exc:
        assert "subj-0001" in str(exc) and "subj-0002" in str(exc), exc
    else:
        raise AssertionError("a merge cycle resolved to a subject")
    # ...and a tombstone naming nobody is itself, not None: every status gate
    # downstream still refuses it, and "no such subject" would be a lie
    orphan = psub.Registry(data={"version": 1, "subjects": [
        {"subject_id": "subj-0001", "status": psub.STATUS_MERGED_INTO}]})
    assert orphan.get("subj-0001").subject_id == "subj-0001"
    log("the chain is compressed at fold time; a cycle is refused out loud")


def case_a_fold_is_refused_across_kinds_and_onto_a_closed_record(tmp):
    """Three refusals, each asserted on its own words and on the id it names.

    ⛔ Across `kind` — two kinds are two subjects however close their vectors
    sit, the guard every comparison in this registry makes. ⛔ Onto a REJECTED
    record — the owner asked never to be asked again, and a fold would put its
    looks into a subject that names files. ⛔ Onto an ABSORBED one — the sweep
    already stopped asking about it and it holds no confirmation to fold."""
    pack_dir = make_pack(tmp)
    registry, first, second = confirmed_pair(
        pack_dir, kinds=("class-word", "another-class-word"))
    before = (first.status, second.status, len(first.exemplars))
    try:
        registry.fold_subjects([first.subject_id, second.subject_id])
    except ValueError as exc:
        assert "different kinds" in str(exc), exc
        assert first.subject_id in str(exc) and second.subject_id in str(exc), exc
    else:
        raise AssertionError("a fold crossed two kinds")
    assert (first.status, second.status, len(first.exemplars)) == before, \
        "a refused fold moved something"

    # a rejected record: the way on is named, and it is `revive`
    rejected_reg, rejected_id = rejected_fixture(
        make_pack(tmp, owner="someone-else"))
    live = observed_then_confirmed(rejected_reg, basis(7), name="Name-Five",
                                  count=1)
    try:
        rejected_reg.fold_subjects([live.subject_id, rejected_id])
    except ValueError as exc:
        assert rejected_id in str(exc) and "revive" in str(exc).lower(), exc
    else:
        raise AssertionError("a fold reached a rejected record")
    assert rejected_reg.get_literal(rejected_id).status == psub.STATUS_REJECTED

    # an absorbed one: the way on is the withdrawal that releases it
    sweep_reg = open_registry(make_pack(tmp, owner="a-third-owner"))
    draft, _state = observe_with_looks(
        sweep_reg, unit(basis(0) + 0.67 * basis(1)),
        [frame(4, "2029-05-01 10:00", batch=4)], batch=4, dates=["2029-05"])
    winner = seeded_subject(sweep_reg, basis(0), count=3)
    winner.record["status"] = psub.STATUS_CONFIRMED
    sweep_reg.defaults["sweep_absorb_tau"] = 0.80
    assert sweep_reg.sweep_absorb([winner.subject_id]), "the fixture absorbed nothing"
    try:
        sweep_reg.fold_subjects([winner.subject_id, draft.subject_id])
    except ValueError as exc:
        assert draft.subject_id in str(exc) and winner.subject_id in str(exc), exc
        assert "withdraw" in str(exc).lower(), exc
    else:
        raise AssertionError("a fold reached an absorbed record")
    assert draft.status == psub.STATUS_ABSORBED
    gates = {r.get("gate") for r in registry.audit_trail()
             if r.get("decision") == "refused"}
    assert "fold" in gates, gates
    log("cross-kind, rejected and absorbed are each refused by name")


def case_a_tombstone_refuses_every_verb_and_never_moves_the_winner(tmp):
    """⛔ **The regression alias following creates, asserted directly.**
    `rename()` and `unconfirm()` both open with a lookup and then read the
    status. On a resolving lookup, a verb aimed at a folded id would find the
    WINNER, pass every guard, and rename or withdraw a subject the caller never
    named — no refusal, and the audit log would name the id that was not
    touched. Every one of them takes the literal record."""
    pack_dir = make_pack(tmp)
    registry, first, second = confirmed_pair(pack_dir)
    registry.fold_subjects([first.subject_id, second.subject_id],
                           name="Name-Two", who="relation-word")
    before = dict(first.record)
    held = [e["vec_ref"] for e in first.exemplars]

    for verb, args_ in ((registry.rename, (second.subject_id, "Name-Nine")),
                        (registry.unconfirm, (second.subject_id,)),
                        (registry.revive, (second.subject_id,))):
        try:
            verb(*args_)
        except ValueError as exc:
            assert second.subject_id in str(exc), (verb.__name__, exc)
            assert first.subject_id in str(exc), \
                (f"{verb.__name__} did not name the winner", exc)
        else:
            raise AssertionError(f"{verb.__name__} accepted a tombstone")

    source = "/raw/IMG_0900.HEIC"
    try:
        registry.add_exemplar(second.subject_id, near(basis(0), 9),
                              "sha256:folded-000", source,
                              confirmed_by="viewed-image", identity=IDENTITY,
                              evidence=look_for(registry, source))
    except ValueError as exc:
        assert second.subject_id in str(exc) and first.subject_id in str(exc), exc
    else:
        raise AssertionError("a tombstone gained an exemplar")

    assert first.name == before["name"] and first.status == before["status"], \
        "a verb aimed at the tombstone reached the winner"
    assert [e["vec_ref"] for e in first.exemplars] == held, \
        "the winner's evidence moved"
    assert second.status == psub.STATUS_MERGED_INTO
    gates = {r.get("gate") for r in registry.audit_trail()
             if r.get("decision") == "refused"}
    assert "merged-into" in gates, gates
    log("rename / unconfirm / revive / add_exemplar all refuse an alias, and "
        "each one names the winner")


def case_the_rename_ledger_resolves_by_precedence_not_by_order(tmp):
    """⭐ The second sharp edge this step carries. `rename_ledger()` used to be
    last-writer-wins over the subject list, so one rendered name held by both a
    dead record and a live one resolved to whichever sat later in the FILE —
    and the folder carrying that name would then be keyed to a record that
    recognises nothing.

    Asserted in BOTH list orders, which is the whole test: one arrangement
    giving the right answer is exactly what the broken version also did."""
    def ledger(records):
        return psub.Registry(data={"version": 1,
                                   "subjects": records}).rename_ledger()

    live = {"subject_id": "subj-0002", "name": "Name-Shared", "who": "w",
            "status": psub.STATUS_CONFIRMED}
    dead = {"subject_id": "subj-0001", "previous_names": ["Name-Shared"],
            "status": psub.STATUS_REJECTED}
    for order in ([dead, live], [live, dead]):
        assert ledger(order)["Name-Shared"] == "subj-0002", order

    # tier 1 — a CURRENT name beats a `previous_names`-only claim, even when
    # both records are live and the live one sorts later
    current = {"subject_id": "subj-0001", "name": "Name-Held", "who": "w",
               "status": psub.STATUS_CONFIRMED}
    former = {"subject_id": "subj-0002", "previous_names": ["Name-Held"],
              "status": psub.STATUS_DRAFT}
    for order in ([current, former], [former, current]):
        assert ledger(order)["Name-Held"] == "subj-0001", order

    # tier 2 — a fold's tombstone resolves to its winner, in either order
    winner = {"subject_id": "subj-0003", "name": "Name-Kept", "who": "w",
              "status": psub.STATUS_CONFIRMED}
    alias = {"subject_id": "subj-0001", "previous_names": ["Name-Gone"],
             "status": psub.STATUS_MERGED_INTO, "merged_into": "subj-0003"}
    for order in ([winner, alias], [alias, winner]):
        assert ledger(order)["Name-Gone"] == "subj-0003", order
    log("a live record outranks a dead one, a current name outranks a former "
        "one, and neither depends on where the record sits in the file")


def case_the_absorbed_count_is_summed_at_read_time_and_un_summed(tmp):
    """✅ The owner's decision, 2026-08-19: absorbed counts aggregate at
    DISPLAY time, never in
    storage.

    20 + 8 reads as 28, and `release_absorbed()` takes it back to 20 — which is
    the property a stored sum could not have. Nothing on either record's
    `files` moves in either direction."""
    registry = open_registry(make_pack(tmp))
    draft, _state = observe_with_looks(
        registry, unit(basis(0) + 0.67 * basis(1)),
        [frame(4, "2029-05-01 10:00", batch=4)], batch=4, dates=["2029-05"])
    draft.record["files"] = 8
    winner = seeded_subject(registry, basis(0), count=3)
    winner.record.update({"status": psub.STATUS_CONFIRMED, "files": 20})
    assert registry.display_files(winner) == 20

    registry.defaults["sweep_absorb_tau"] = 0.80
    assert registry.sweep_absorb([winner.subject_id]), "the fixture absorbed nothing"
    assert registry.display_files(winner) == 28, registry.display_files(winner)
    assert winner.record["files"] == 20, "the sum reached storage"
    assert draft.record["files"] == 8, "the absorbed record lost its count"
    report = {s["subject_id"]: s for s in psub.review(registry)["subjects"]}
    assert report[winner.subject_id]["files"] == 20
    assert report[winner.subject_id]["display_files"] == 28
    assert report[winner.subject_id]["absorbed"] == 1
    assert report[winner.subject_id]["absorbed_files"] == 8

    released = registry.release_absorbed(winner.subject_id)
    assert released == [draft.subject_id], released
    assert registry.display_files(winner) == 20, \
        "the sum did not come back apart"
    # ⚠️ the invariant every other reader rests on: only a `human-confirmed`
    # record can carry the list at all, which is why the draft and rejection
    # paths need no sum of their own
    assert not [s for s in registry.subjects
                if s.record.get("absorbed_drafts")
                and s.status != psub.STATUS_CONFIRMED]
    log("20 + 8 renders 28 and un-renders to 20; storage never held 28")


def case_the_audit_log_is_provenance_and_not_pack_state(tmp):
    """Step 9, item 1 — the audit log is the ONE file under `photo-subjects/`
    the pack snapshot does not hash.

    ⛔ Measured 2026-08-20: a REFUSED `confirm --go` writes nothing to the
    registry and still audits, so the pack id moved and the pinned-snapshot
    check then refused the whole of the page whose single row had been
    refused. Provenance is not state — the same argument that kept
    `photo-memory-log.md` out of the snapshot when it was written.

    Two halves, and the second is the one that keeps the guard load-bearing:
    an audit line must NOT move the id, and a change to any other file under
    the same directory MUST."""
    assert psub.AUDIT_NAME in photo_profile.SNAPSHOT_EXCLUDE, \
        (psub.AUDIT_NAME, photo_profile.SNAPSHOT_EXCLUDE)
    pack_dir = make_pack(tmp)
    pack = photo_profile.resolve_pack(
        explicit=pack_dir / "photo-profile.json")
    registry = psub.Registry(directory=pack_dir / "photo-subjects")
    subject = registry.create_subject(name="Name-One", who="pet", kind="cat")
    registry.save()
    before = pack.snapshot()

    registry.audit({"subject_id": subject.subject_id, "decision": "refused",
                    "gate": "test", "reason": "a refusal leaves a trace"})
    assert registry.audit_path.is_file(), "nothing was audited"
    assert pack.snapshot()["id"] == before["id"], \
        "an audit line moved the pack id — a refused page cannot be re-read"

    # ...and the exclusion is one file, not a loosened hash
    subject.record["files"] = 7
    registry.save()
    assert pack.snapshot()["id"] != before["id"], \
        "a real registry change did not move the pack id"
    log("the audit log is provenance; every other file in the pack is state")


def case_the_partition_refusal_speaks_for_the_verb(tmp):
    """Step 9, item 2 — `partition_refusal()` answers exactly what
    `partition_subject()` would, and writes nothing while answering.

    ⛔ The predicate is not a second copy of the gates. It is the same walk,
    so this asserts the two agree sentence for sentence over the refusals a
    caller can reach, and that asking moved neither the records nor the audit
    log — a dry run that audited would move the pack it promised not to
    touch."""
    pack_dir = make_pack(tmp)
    registry, parent_id = split_fixture(pack_dir)
    ok = [{"vec_refs": ["sha256:frame-01", "sha256:frame-03"],
           "centroid": basis(1), "shared_with": []},
          {"vec_refs": ["sha256:frame-02"], "centroid": basis(2),
           "shared_with": []}]
    shared = [dict(ok[0], shared_with=["subj-9999"]), dict(ok[1])]
    nowhere = [{"vec_refs": ["sha256:not-a-look"], "centroid": basis(1),
                "shared_with": []}, dict(ok[1])]

    trail = len(registry.audit_trail())
    for groups in (shared, nowhere, []):
        why = registry.partition_refusal(parent_id, groups)
        assert why, groups
        try:
            registry.partition_subject(parent_id, groups)
        except ValueError as exc:
            assert str(exc) == why, (str(exc), why)
        else:
            raise AssertionError(f"the verb accepted what the predicate "
                                 f"refused: {groups}")
    assert len(registry.audit_trail()) == trail + 3, \
        "the predicate audited, or the verb stopped auditing its refusals"
    assert registry.get(parent_id).is_draft, \
        "a refused partition moved the record"

    # ...and it says nothing about a partition it would perform
    assert registry.partition_refusal(parent_id, ok) is None
    log("the predicate and the verb refuse in the same words, and only the "
        "verb writes")


def case_a_draft_joins_a_remembered_subject_and_moves_nothing_else(tmp):
    """SNS-16's storage half, and its ⛔ list. The owner said this draft is the
    subject the pack already knows: the picked looks are carried across so the
    promotion has provenance to stand on and SNS-6 can re-present them, the
    draft becomes `absorbed` bookkeeping, and NOTHING else about the confirmed
    subject moves — not its name, not its `who`, not its first-sighting
    centroid, not its `active` range, not its file count.

    ⭐ **No `absorbed_at_score`, because there is no bar.** The sweep records
    the score it absorbed at, because a threshold decided it. Here the owner
    decided it, and a score written beside that answer would read as a check
    that was made."""
    pack_dir = make_pack(tmp)
    registry = open_registry(pack_dir)
    known, _state = observe_with_looks(
        registry, basis(0), [frame(1, "2029-03-04 10:01")], batch=1)
    known.record.update({"name": "Name-One", "who": "pet",
                         "status": psub.STATUS_CONFIRMED,
                         "active": ["2029-03", "2029-03"], "files": 40})
    # ⛔ No exemplar is minted here and no see-report is hand-written to let
    # one through: `add_exemplar()`'s second gate re-derives the look from
    # disk, and fabricating that evidence is permanently off the table. This
    # case is about what the ATTACH writes, and the attach promotes nothing.
    draft, _state = observe_with_looks(
        registry, basis(3), [frame(7, "2030-01-02 09:00", batch=2),
                             frame(8, "2030-01-02 09:05", batch=2)],
        batch=2, dates=["2030-01"])
    before = {k: v for k, v in known.record.items()
              if k in ("name", "who", "active", "files", "obs_count",
                       "observed_in")}
    centroid = registry.draft_centroid(known.subject_id)

    result = registry.attach_draft_to_subject(
        draft.subject_id, known.subject_id, ["sha256:frame-07"],
        by="an operator", reason="the owner said so")
    assert result["looks"] == 1, result

    assert draft.status == psub.STATUS_ABSORBED, draft.record
    assert draft.record["absorbed_by"] == known.subject_id, draft.record
    assert "absorbed_at_score" not in draft.record, \
        "a score was written for a decision no threshold took"
    assert draft not in registry.drafts, "an absorbed draft is still asked about"
    assert known.record["absorbed_drafts"][0]["subject_id"] == draft.subject_id

    carried = [look["vec_ref"] for entry in known.record["evidence"]
               for look in entry.get("looks") or []]
    assert "sha256:frame-07" in carried, carried
    assert "sha256:frame-08" not in carried, \
        "a frame nobody picked was carried across"
    for key, value in before.items():
        assert known.record.get(key) == value, (key, known.record.get(key),
                                                value)
    assert np.allclose(registry.draft_centroid(known.subject_id), centroid), \
        "the first-sighting centroid moved"
    assert not known.exemplars, (
        "the storage half promoted an exemplar — that is attach_exemplars()' "
        "job, behind its own three gates")

    # ...and the release takes it back
    assert registry.release_absorbed(known.subject_id) == [draft.subject_id]
    assert draft.is_draft and draft.record.get(psub.REOPENED_FLAG), draft.record
    log("the picked look is carried across, the draft is bookkeeping, and no "
        "score was written")


def case_a_promotion_refuses_what_it_cannot_attest(tmp):
    """SNS-16's three storage refusals. ⛔ A target nobody has named — no human
    yes stands behind it. ⛔ A source that is not an open draft — a rejection
    or an absorption is a decision to take back first. ⛔ A frame the draft
    does not hold, which is `attach_exemplars()`'s rule one layer down: a set
    that quietly shrinks is how an answer loses frames."""
    pack_dir = make_pack(tmp)
    registry = open_registry(pack_dir)
    known, _state = observe_with_looks(
        registry, basis(0), [frame(1, "2029-03-04 10:01")], batch=1)
    draft, _state = observe_with_looks(
        registry, basis(3), [frame(7, "2030-01-02 09:00", batch=2)],
        batch=2, dates=["2030-01"])

    for why in ("not human-confirmed",):
        try:
            registry.attach_draft_to_subject(draft.subject_id,
                                             known.subject_id,
                                             ["sha256:frame-07"])
        except ValueError as exc:
            assert psub.STATUS_CONFIRMED in str(exc), (why, exc)
        else:
            raise AssertionError("a draft joined a subject nobody named")

    known.record.update({"name": "Name-One", "who": "pet",
                         "status": psub.STATUS_CONFIRMED})
    try:
        registry.attach_draft_to_subject(draft.subject_id, known.subject_id,
                                         ["sha256:frame-99"])
    except ValueError as exc:
        assert "sha256:frame-99" in str(exc), exc
    else:
        raise AssertionError("a frame the draft does not hold was carried")
    assert draft.is_draft, "a refused promotion moved the record"

    draft.record["status"] = psub.STATUS_REJECTED
    try:
        registry.attach_draft_to_subject(draft.subject_id, known.subject_id,
                                         ["sha256:frame-07"])
    except ValueError as exc:
        assert psub.STATUS_REJECTED in str(exc), exc
    else:
        raise AssertionError("a rejected record joined a subject")
    assert not known.record.get("absorbed_drafts"), \
        "a refused promotion still booked the draft on the winner"

    # ⛔ ...and the predicate says the same thing the verb does, so a caller
    # holding several drafts on one row can judge them all before the first
    # one moves. A row is refused whole or applied whole.
    for args in ((draft.subject_id, known.subject_id, ["sha256:frame-07"]),
                 (draft.subject_id, known.subject_id, ["sha256:frame-99"]),
                 ("subj-9999", known.subject_id, [])):
        why = registry.attach_draft_refusal(*args)
        assert why, args
        try:
            registry.attach_draft_to_subject(*args)
        except ValueError as exc:
            assert str(exc) == why, (str(exc), why)
        else:
            raise AssertionError(f"the verb accepted what the predicate "
                                 f"refused: {args}")
    log("an unnamed target, a closed source and a frame nobody holds are each "
        "refused, by the verb and by the predicate in the same words")


# ---------------------------------------------- VS-3b: the identity space --

ID_DIM = 6
ID_SPACE = {"space": "subject-identity", "detector_id": "det-fixture",
            "detector_weights": "W", "model_id": "id-fixture",
            "model_source": "nowhere", "embed_dim": ID_DIM, "normalized": True,
            "box_pad": 0.12, "min_detection_score": 0.5,
            "duplicate_containment": 0.55,
            "pipeline_fingerprint": "sha256:idfixture000000", 
            "zero_vector_means_no_subject": True}
# What a pack writes down for that space: the fixture predates the preview
# backend key, and a space with none was built from sips previews (Card 4).
ID_SPACE_STORED = {**ID_SPACE, "preview_backend": "sips"}


def id_unit(*weights):
    v = np.zeros(ID_DIM, dtype=np.float32)
    for i, w in enumerate(weights):
        v[i] = w
    return v / float(np.linalg.norm(v))


def seeded_identity_subject(registry, clip_base, id_vec, name, count=2, start=0):
    """A subject whose exemplars carry BOTH vectors — the state an owner
    reaches after confirming files that had a detected subject in frame."""
    subject = registry.create_subject(name=name, who="relation-word",
                                      kind="class-word",
                                      active=["2029-03", "2031-08"])
    for k in range(count):
        source = f"/raw/ID_{name}_{start + k:04d}.HEIC"
        registry.add_exemplar(
            subject.subject_id, near(clip_base, start + k),
            f"sha256:{name}-id-{start + k:03d}", source, added="2031-02-14",
            confirmed_by="viewed-image", identity=IDENTITY,
            evidence=look_for(registry, source),
            identity_vector=id_vec, identity_space=ID_SPACE)
    return subject


def case_identity_vectors_ride_along_and_persist(tmp):
    """The store exists, survives a save/reload, and is keyed by vec_ref
    rather than by row position."""
    pack = make_pack(tmp)
    registry = open_registry(pack)
    subject = seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0),
                                      "Name-One")
    registry.save()

    reloaded = open_registry(pack)
    V = reloaded.identity_vectors_for(subject.subject_id)
    assert V is not None and V.shape == (2, ID_DIM), None if V is None else V.shape
    assert reloaded.identity_embedding["model_id"] == "id-fixture", \
        reloaded.identity_embedding
    # The CLIP store is untouched and still its own size.
    assert reloaded.vectors_for(subject.subject_id).shape == (2, DIM)
    assert [s.subject_id for s in reloaded.identity_recognisers] == [subject.subject_id]
    log("identity vectors persist beside the CLIP ones and are keyed by vec_ref")


def case_a_pack_without_identity_vectors_scores_in_the_clip_space(tmp):
    """The whole compatibility promise: a registry built before VS-3b, or an
    owner who never ran the identity stage, behaves exactly as it always did
    and SAYS which space decided it."""
    registry = open_registry(make_pack(tmp))
    subject = seeded_subject(registry, basis(0))
    assert registry.identity_vectors_for(subject.subject_id) is None
    assert registry.identity_recognisers == []

    verdicts = registry.match(np.stack([near(basis(0), 99)]),
                              [datetime(2030, 6, 1)], IDENTITY)
    assert verdicts[0]["space"] == "clip", verdicts[0]
    assert verdicts[0]["verdict"] == psub.VERDICT_ACCEPT, verdicts[0]

    # ...and passing an identity matrix a registry cannot answer in changes
    # nothing: the fallback is per FILE, decided on what both sides hold.
    with_matrix = registry.match(np.stack([near(basis(0), 99)]),
                                 [datetime(2030, 6, 1)], IDENTITY,
                                 X_identity=np.stack([id_unit(1, 0, 0)]),
                                 identity_space=ID_SPACE)
    assert with_matrix[0]["space"] == "clip", with_matrix[0]
    log("no identity exemplars -> the CLIP space, and the verdict names it")


def case_the_identity_space_decides_on_a_floor_and_a_margin(tmp):
    """Both halves are load-bearing, and the case proves each by removing the
    other. This is the measured shape from 20260821: a true sighting leads by
    a wide margin, an impostor leads by almost nothing, and neither is decided
    by an absolute cosine alone."""
    pack = make_pack(tmp)
    registry = open_registry(pack)
    one = seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0), "Name-One")
    two = seeded_identity_subject(registry, basis(2), id_unit(0, 1, 0), "Name-Two",
                                  start=50)
    dates = [datetime(2030, 6, 1)]
    clip = np.stack([near(basis(0), 99)])

    def verdict(iv):
        return registry.match(clip, dates, IDENTITY, X_identity=np.stack([iv]),
                              identity_space=ID_SPACE)[0]

    # Clearly nearest, and well clear of the floor -> a name.
    clear = verdict(id_unit(0.98, 0.05, 0.05))
    assert clear["space"] == "identity", clear
    assert clear["verdict"] == psub.VERDICT_ACCEPT, clear
    assert clear["subject_id"] == one.subject_id, clear

    # Above the floor but sitting between two subjects -> a QUESTION. Never a
    # ranking: two subjects this close is cardinality.
    between = verdict(id_unit(0.71, 0.70, 0.05))
    assert between["verdict"] == psub.VERDICT_QUESTION, between
    assert between["question"], between

    # Nearest by a mile, but too far from everything to claim anything. This
    # is the impostor case — a stray animal is closest to whichever subject
    # holds the biggest bank, and the floor is the only thing that stops it.
    far = verdict(id_unit(0.2, 0.02, 0.98))
    assert far["verdict"] in (psub.VERDICT_GRAY, psub.VERDICT_NONE), far
    assert far["score"] < registry.defaults.get(
        "identity_floor", psub.DEFAULT_THRESHOLDS["identity_floor"]), far
    log("floor stops the impostor, margin turns a near-tie into a question")


def case_identity_suppression_overrules_the_clip_space(tmp):
    """F14 in the identity space, and the ⛔ that makes the change worth
    making: when the identity space has an opinion, a CLIP near-match may not
    overturn it. Without this the weaker signal still decides."""
    pack = make_pack(tmp)
    registry = open_registry(pack)
    one = seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0), "Name-One")

    # A cluster that LOOKS like Name-One to CLIP (same room) but is somebody
    # else entirely in the identity space. Pre-VS-3b this suppressed the
    # question and the second animal was never asked about.
    clip_lookalike = near(basis(0), 1, jitter=0.02)
    assert registry.confirmed_match(clip_lookalike, kind="class-word") is not None, \
        "fixture is wrong: CLIP should match this"
    assert registry.confirmed_match(clip_lookalike, kind="class-word",
                                    identity_vec=id_unit(0.1, 0.1, 0.99)) is None
    # ...and the true one is still suppressed.
    assert registry.confirmed_match(clip_lookalike, kind="class-word",
                                    identity_vec=id_unit(0.99, 0.05, 0.05)) is not None
    assert one.status == psub.STATUS_CONFIRMED
    log("identity says no -> the question is asked, whatever CLIP thinks")


def case_an_exemplar_may_be_gained_without_being_identity_evidence(tmp):
    """The 20260821 paw-close-up finding. A frame the owner truly confirmed
    can carry no answer to WHICH subject it is; refusing it as identity
    evidence must never refuse the exemplar itself."""
    import photo_identity

    pack = make_pack(tmp)
    registry = open_registry(pack)
    subject = registry.create_subject(name="Name-One", who="relation-word",
                                      kind="class-word",
                                      active=["2029-03", "2031-08"])
    source = "/raw/ID_tiny_0001.HEIC"
    tiny = {"status": photo_identity.STATUS_OK, "box_share": "0.004"}
    quality = photo_identity.exemplar_quality(tiny)
    assert quality[0] is False, quality

    added, _dropped = registry.add_exemplar(
        subject.subject_id, near(basis(0), 1), "sha256:tiny-001", source,
        added="2031-02-14", confirmed_by="viewed-image", identity=IDENTITY,
        evidence=look_for(registry, source),
        identity_vector=id_unit(1, 0, 0), identity_space=ID_SPACE,
        identity_quality=quality)

    assert added is True, "the owner's yes must stand"
    assert len(subject.exemplars) == 1, subject.exemplars
    assert registry.identity_vectors_for(subject.subject_id) is None
    assert registry.identity_recognisers == []
    line = json.loads(registry.audit_path.read_text().strip().splitlines()[-1])
    assert line["decision"] == "memorized", line
    assert "not usable as identity evidence" in (line.get("identity_vector") or ""), line
    log("a refused identity vector never refuses the exemplar, and says why")


def case_a_zero_identity_row_is_no_subject_not_a_bad_match(tmp):
    """photo_identity writes a zero row for a frame with no animal in it. That
    is a positive statement and must not be scored — a zero vector scores 0.0
    against everything, which would read as a confident 'nobody'."""
    pack = make_pack(tmp)
    registry = open_registry(pack)
    seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0), "Name-One")

    verdicts = registry.match(
        np.stack([near(basis(0), 99)]), [datetime(2030, 6, 1)], IDENTITY,
        X_identity=np.zeros((1, ID_DIM), dtype=np.float32),
        identity_space=ID_SPACE)
    assert verdicts[0]["space"] == "clip", verdicts[0]
    log("a zero identity row falls back to CLIP rather than scoring as 0.0")


def case_two_identity_pipelines_are_refused(tmp):
    """The same guard `assert_identity` is for CLIP, on its own field: a swap
    of detector or embedding makes every stored vector incomparable, and the
    failure would otherwise be silent."""
    pack = make_pack(tmp)
    registry = open_registry(pack)
    seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0), "Name-One")
    other = dict(ID_SPACE, model_id="a-different-model")
    try:
        registry.match(np.stack([near(basis(0), 1)]), [datetime(2030, 6, 1)],
                       IDENTITY, X_identity=np.stack([id_unit(1, 0, 0)]),
                       identity_space=other)
    except ValueError as exc:
        assert "not comparable" in str(exc), exc
    else:
        raise AssertionError("two identity pipelines were not refused")
    # The CLIP identity is a SEPARATE field: swapping one must not read as the
    # other having changed.
    assert registry.embedding_identity["model_id"] == "ViT-B-32"
    log("an identity-pipeline swap is refused, and is not a CLIP-model swap")


def case_a_confirmed_subject_the_identity_space_cannot_use_is_named(tmp):
    """The measured defect: an owner confirms a subject, every frame they
    confirmed it on held no detected animal, and the subject then leaves the
    identity space at MATCH time with nobody told.

    (a) and (b) are the CORRECT half and are asserted to make sure the report
    did not buy itself a behaviour change: the confirmation stands and the
    subject is still absent from `identity_recognisers`, because a record with
    no identity vector has nothing to score. (c) is the new part — it is now
    named, by id, in the list a run reports."""
    import photo_identity

    pack = make_pack(tmp)
    registry = open_registry(pack)
    speaks = seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0),
                                     "Name-One")

    # The silent one: confirmed on frames photo_identity called `no-subject`.
    silent = registry.create_subject(name="Name-Two", who="relation-word",
                                     kind="class-word",
                                     active=["2029-03", "2031-08"])
    quality = photo_identity.exemplar_quality(
        {"status": photo_identity.STATUS_NO_SUBJECT})
    assert quality[0] is False, quality
    for k in range(2):
        source = f"/raw/ID_silent_{k:04d}.HEIC"
        added, _dropped = registry.add_exemplar(
            silent.subject_id, near(basis(4), k), f"sha256:silent-{k:03d}",
            source, added="2031-02-14", confirmed_by="viewed-image",
            identity=IDENTITY, evidence=look_for(registry, source),
            identity_vector=np.zeros(ID_DIM, dtype=np.float32),
            identity_space=ID_SPACE, identity_quality=quality)
        assert added is True, "the owner's yes must stand"

    # (a) still confirmed, and still a recogniser in the CLIP space.
    assert silent.status == psub.STATUS_CONFIRMED, silent.record
    assert silent.subject_id in [s.subject_id for s in registry.recognisers]
    # (b) still absent from the identity space — this is correct, not the bug.
    assert registry.identity_vectors_for(silent.subject_id) is None
    assert [s.subject_id for s in registry.identity_recognisers] == \
        [speaks.subject_id]
    # (c) ...and now SAID, instead of leaving the list silently.
    assert [s.subject_id for s in registry.identity_silent_recognisers] == \
        [silent.subject_id]
    # the pack itself does speak identity, which is what makes this one
    # subject an owner-actionable defect rather than a pack that never ran
    assert registry.identity_embedding == ID_SPACE_STORED, registry.identity_embedding

    # The complement is exact, and it survives a save/reload: the two lists
    # partition `recognisers` between them with nothing falling down the gap.
    registry.save()
    reloaded = open_registry(pack)
    assert ([s.subject_id for s in reloaded.identity_recognisers]
            + [s.subject_id for s in reloaded.identity_silent_recognisers]
            == [s.subject_id for s in reloaded.recognisers])

    # ⛔ And a withdrawal must empty BOTH lists at once — the silent list is
    # not its own status test, or a withdrawn subject would go on being
    # reported as a defect the owner should re-confirm.
    reloaded.unconfirm(silent.subject_id, by="an operator")
    assert reloaded.identity_silent_recognisers == [], \
        [s.subject_id for s in reloaded.identity_silent_recognisers]
    log("a confirmed subject the identity space cannot use is named, not dropped")


def case_a_pack_that_never_ran_the_identity_stage_is_not_a_defect(tmp):
    """The other cause, and the reason the report needs `identity_embedding`
    beside the list. Here EVERY recogniser is silent and none of them is
    actionable — the owner has nothing to re-confirm, the pack simply predates
    the stage.

    ⚠️ The split is available at PACK granularity only. `identity_embedding`
    is written the first time any exemplar in the pack attaches a vector, so a
    pack whose every identity vector was refused is indistinguishable from one
    that never ran — nothing on an exemplar record carries the refusal."""
    registry = open_registry(make_pack(tmp))
    subject = seeded_subject(registry, basis(0))

    assert registry.identity_recognisers == []
    assert [s.subject_id for s in registry.identity_silent_recognisers] == \
        [subject.subject_id]
    assert registry.identity_embedding is None, registry.identity_embedding

    # ...and it is still only a report: the run scores in the CLIP space and
    # says which space decided it, exactly as before.
    verdicts = registry.match(np.stack([near(basis(0), 99)]),
                              [datetime(2030, 6, 1)], IDENTITY)
    assert verdicts[0]["space"] == "clip", verdicts[0]
    assert verdicts[0]["verdict"] == psub.VERDICT_ACCEPT, verdicts[0]
    log("no identity index -> every recogniser is silent, and none is a defect")


def case_a_rebuilt_index_is_not_a_pipeline_change(tmp):
    """⛔ The mature-pack blocker: `identity-meta.json` carries `created_at`
    and `updated_at` beside the fields that define the space. The guard used
    to compare the two dicts WHOLE, so a freshly built index differed from
    every pack on the timestamps alone and every run was refused — with a
    message naming only model and detector, which are equal, so it printed two
    identical strings and told the operator nothing.

    Found on a real dump: the first run against a pack holding two confirmed
    subjects refused all 16 batches, and the identity space had never been
    reachable with a mature pack at all.
    """
    registry = open_registry(make_pack(tmp))
    seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0), "Name-One")

    # what photo_identity writes: the space, plus when it happened
    rebuilt = {**ID_SPACE, "created_at": "2026-08-29 18:19",
               "updated_at": "2026-08-29 18:21"}
    registry.assert_identity_space(rebuilt)      # must NOT raise

    # ...and a pack seeded BEFORE the projection existed stored the timestamps
    # too, so both sides have to be projected, not just the incoming one.
    registry.data["identity_embedding"] = {**ID_SPACE,
                                           "created_at": "2026-08-27 22:03",
                                           "updated_at": "2026-08-27 22:04"}
    registry.assert_identity_space(rebuilt)      # must NOT raise either
    log("a rebuilt identity index is not mistaken for a pipeline change")


def case_a_real_pipeline_change_is_still_refused(tmp):
    """The positive control. Widening the guard must not disarm it: crops from
    a different detector, or embedded by a different model, are still not
    comparable — and the refusal now NAMES the field that differs, which is
    the half that made the old message useless."""
    registry = open_registry(make_pack(tmp))
    seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0), "Name-One")

    for field, value in (("detector_id", "some-other-detector"),
                         ("model_id", "some-other-model"),
                         ("pipeline_fingerprint", "sha256:different000000"),
                         ("box_pad", 0.30)):
        changed = {**ID_SPACE, field: value,
                   "created_at": "2026-08-29 18:19"}
        try:
            registry.assert_identity_space(changed)
        except ValueError as exc:
            assert field in str(exc), (field, str(exc))
            assert str(value) in str(exc), (field, str(exc))
        else:
            raise AssertionError(f"a changed {field} was accepted")
    log("a real pipeline change is refused, and the message names the field")


def case_a_pack_never_stores_a_build_timestamp_as_its_space(tmp):
    """The write side of the same bug. If the pack goes on storing the raw
    index meta, the guard is projected but the DATA still carries a timestamp
    that means nothing, and the next reader to compare it raw is back where
    this started."""
    registry = open_registry(make_pack(tmp))
    subject = registry.create_subject(name="Name-One", who="relation-word",
                                      kind="class-word",
                                      active=["2029-03", "2031-08"])
    source = "/raw/ID_stamped_0001.HEIC"
    registry.add_exemplar(
        subject.subject_id, near(basis(0), 1), "sha256:stamped-001", source,
        added="2031-02-14", confirmed_by="viewed-image", identity=IDENTITY,
        evidence=look_for(registry, source), identity_vector=id_unit(1, 0, 0),
        identity_space={**ID_SPACE, "created_at": "2026-08-29 18:19",
                        "updated_at": "2026-08-29 18:21"})
    stored = registry.identity_embedding
    assert "created_at" not in stored, stored
    assert "updated_at" not in stored, stored
    assert stored == ID_SPACE_STORED, stored
    log("the pack stores the space, not the moment the index was built")


def case_an_ungated_suppression_is_marked_and_counted(tmp):
    """A19. `confirmed_match` carries no timeline gate, so a suppression can
    land on a subject the file's own date sits years outside — the state
    `match()` refuses outright. The suppression still HAPPENS (that is
    unchanged and deliberate); what this asserts is that the record says which
    kind it was, and that the totals do not move.

    ⛔ The marking is not a filter. Measured on one owner dump, 24 of 24
    suppressions were ungated and 19 of them were CORRECT — dropping them to
    catch the other 5 would have cost more than it saved, and no threshold
    separates the two groups because the wrong scores sit inside the right
    ones' range."""
    pack = make_pack(tmp)
    registry = open_registry(pack)
    one = seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0), "Name-One")
    before_files = int(one.record.get("files", 0))
    before_obs = one.obs_count

    # active is ["2029-03", "2031-08"], so this date is far outside it.
    subject, state = registry.observe_draft_subject(
        near(basis(0), 1, jitter=0.01), kind="class-word", batch=1, files=4,
        dates=["2020-01"], identity=IDENTITY,
        identity_centroid=id_unit(0.99, 0.05, 0.05),
        evidence={"batch": 1, "state": None})
    assert state == "known", state
    assert subject.subject_id == one.subject_id

    entry = one.record["evidence"][-1]
    assert entry["within_timeline"] is False, entry
    assert "suppressed_at" in entry, "the score must still be recorded"
    assert one.record["obs_count_ungated"] == 1
    assert one.record["files_ungated"] == 4
    # The totals mean exactly what they always meant.
    assert int(one.record["files"]) == before_files + 4
    assert one.obs_count == before_obs + 1
    log("ungated suppression: marked, counted apart, totals unchanged")


def case_a_gated_suppression_is_marked_true_and_counts_nothing(tmp):
    """The other branch, and it is asserted for its own sake: `within_timeline`
    is written on BOTH, so a row that lacks the key means "written before
    A19" — which is a different fact from "gated", and telling those apart is
    the whole point of the card."""
    pack = make_pack(tmp)
    registry = open_registry(pack)
    one = seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0), "Name-One")

    subject, state = registry.observe_draft_subject(
        near(basis(0), 1, jitter=0.01), kind="class-word", batch=1, files=3,
        dates=["2030-01"], identity=IDENTITY,
        identity_centroid=id_unit(0.99, 0.05, 0.05),
        evidence={"batch": 1, "state": None})
    assert state == "known", state
    assert one.record["evidence"][-1]["within_timeline"] is True
    assert "obs_count_ungated" not in one.record
    assert "files_ungated" not in one.record
    assert registry.display_files_ungated(one) == 0
    log("gated suppression: marked true, and it adds to no ungated count")


def case_an_undated_cluster_is_ungated_not_unknown(tmp):
    """`eligible_at(None)` is False by decision — an ungated match on an
    undated file is a guess — so a suppression with no usable date is counted
    with the ungated ones rather than given the benefit of the doubt.

    ⛔ Deliberate: a video with no capture date is exactly where a wrong
    attribution is hardest to notice afterwards."""
    pack = make_pack(tmp)
    registry = open_registry(pack)
    one = seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0), "Name-One")

    registry.observe_draft_subject(
        near(basis(0), 1, jitter=0.01), kind="class-word", batch=1, files=2,
        dates=[None], identity=IDENTITY,
        identity_centroid=id_unit(0.99, 0.05, 0.05),
        evidence={"batch": 1, "state": None})
    assert one.record["evidence"][-1]["within_timeline"] is False
    assert one.record["files_ungated"] == 2
    log("no date is not in-range")


def case_the_ungated_share_is_summed_the_way_display_files_is(tmp):
    """A19 item 3 rests on subtracting one number from the other, so the two
    must be built on the same three parts. A record written before A19 carries
    no `files_ungated` and contributes 0 — silence, never a claim that its
    sightings were gated."""
    pack = make_pack(tmp)
    registry = open_registry(pack)
    one = seeded_identity_subject(registry, basis(0), id_unit(1, 0, 0), "Name-One")
    one.record["files"] = 10
    one.record["files_ungated"] = 4
    # A draft the sweep absorbed, carrying its own ungated share...
    one.record["absorbed_drafts"] = [{"subject_id": "subj-9001", "files": 6,
                                      "files_ungated": 2}]
    # ...and a legacy one that predates the counter entirely.
    one.record["absorbed_drafts"].append({"subject_id": "subj-9002", "files": 5})

    assert registry.display_files(one) == 21
    assert registry.display_files_ungated(one) == 6, \
        "4 of its own + 2 absorbed; the legacy row contributes 0, not 5"
    log("same three parts, same basis, legacy rows silent")


def case_group_coherence_flags_two_animals():
    """⭐ THE U2-12 REPRODUCTION. A draft group whose frames are two different
    animals must be reported as incoherent, and must name the pair.

    ⛔ FAILS on the pre-check engine, where nothing compares a group's frames
    against each other at all."""
    same_a = id_unit(1, 0, 0, 0, 0, 0)
    same_b = id_unit(0.96, 0.28, 0, 0, 0, 0)
    other = id_unit(0, 0, 1, 0, 0, 0)
    out = psub.group_coherence(
        [("f1", same_a), ("f2", same_b), ("f9", other)])
    assert out is not None, "three frames with vectors must be checkable"
    assert out["pairs"] == 3, f"3 frames is 3 pairs, got {out['pairs']}"
    assert not out["coherent"], \
        f"a group holding two animals must not read as coherent: {out}"
    assert set(out["worst"]) == {"f1", "f9"} or set(out["worst"]) == {"f2", "f9"}, \
        f"the reported pair must be the one that disagrees, got {out['worst']}"


def case_group_coherence_leaves_one_animal_alone():
    """GUARD, and the expensive direction: a false alarm on every group
    teaches the owner to skip the warning, which costs the real one."""
    out = psub.group_coherence([
        ("f1", id_unit(1, 0, 0, 0, 0, 0)),
        ("f2", id_unit(0.96, 0.28, 0, 0, 0, 0)),
        ("f3", id_unit(0.94, 0.20, 0.27, 0, 0, 0)),
    ])
    assert out is not None and out["coherent"], \
        f"three frames of one animal must not be flagged: {out}"


def case_group_coherence_compares_frames_not_a_centroid():
    """⭐ THE SHAPE OF THE CHECK, not just its verdict. A group split evenly
    between two animals has a centroid sitting BETWEEN them: every frame is
    equally mediocre against it and nothing stands out. Frames against each
    other is what separates them."""
    import numpy as np
    a1, a2 = id_unit(1, 0, 0, 0, 0, 0), id_unit(0.97, 0.24, 0, 0, 0, 0)
    b1, b2 = id_unit(0, 0, 1, 0, 0, 0), id_unit(0, 0.24, 0.97, 0, 0, 0)
    frames = [("a1", a1), ("a2", a2), ("b1", b1), ("b2", b2)]
    centroid = np.mean([v for _k, v in frames], axis=0)
    centroid = centroid / np.linalg.norm(centroid)
    against_centroid = [float(v @ centroid) for _k, v in frames]
    assert max(against_centroid) - min(against_centroid) < 0.05, \
        ("the premise: against the centroid these four frames are "
         f"indistinguishable, got {against_centroid}")
    out = psub.group_coherence(frames)
    assert not out["coherent"], \
        f"frames against each other must still separate them: {out}"


def case_group_coherence_needs_two_vectors():
    """A group the identity index cannot speak about states NOTHING. ⛔ None
    and 'coherent' are different answers: a silent True would render as the
    engine having checked and found nothing wrong."""
    v = id_unit(1, 0, 0, 0, 0, 0)
    assert psub.group_coherence([]) is None
    assert psub.group_coherence([("f1", v)]) is None, \
        "one frame has no pair to compare"
    assert psub.group_coherence([("f1", v), ("f2", None)]) is None, \
        "a frame with no identity vector cannot be half of a comparison"
    import numpy as np
    zero = np.zeros(ID_DIM, dtype=np.float32)
    assert psub.group_coherence([("f1", v), ("f2", zero)]) is None, \
        "a ZERO vector means 'no subject in this frame', never a comparison"


CASES = [
    ("A19 — an ungated suppression is marked and counted apart",
     case_an_ungated_suppression_is_marked_and_counted),
    ("A19 — a gated suppression is marked true and counts nothing",
     case_a_gated_suppression_is_marked_true_and_counts_nothing),
    ("A19 — an undated cluster is ungated, not given the benefit of the doubt",
     case_an_undated_cluster_is_ungated_not_unknown),
    ("A19 — the ungated share sums the way display_files does",
     case_the_ungated_share_is_summed_the_way_display_files_is),

    ("VS-3b — identity vectors ride along and persist",
     case_identity_vectors_ride_along_and_persist),
    ("VS-3b — a rebuilt identity index is not a pipeline change",
     case_a_rebuilt_index_is_not_a_pipeline_change),
    ("VS-3b — a real pipeline change is still refused, and named",
     case_a_real_pipeline_change_is_still_refused),
    ("U2-12 — a group holding two animals is flagged (REPRODUCTION)",
     case_group_coherence_flags_two_animals),
    ("U2-12 — a group of one animal is left alone",
     case_group_coherence_leaves_one_animal_alone),
    ("U2-12 — frames are compared to each other, not to a centroid",
     case_group_coherence_compares_frames_not_a_centroid),
    ("U2-12 — too few identity vectors states nothing",
     case_group_coherence_needs_two_vectors),
    ("VS-3b — a pack never stores a build timestamp as its space",
     case_a_pack_never_stores_a_build_timestamp_as_its_space),
    ("VS-3b — a pack without identity vectors scores in the CLIP space",
     case_a_pack_without_identity_vectors_scores_in_the_clip_space),
    ("VS-3b — the identity space decides on a floor AND a margin",
     case_the_identity_space_decides_on_a_floor_and_a_margin),
    ("VS-3b — identity suppression overrules the CLIP space",
     case_identity_suppression_overrules_the_clip_space),
    ("VS-3b — an exemplar may be gained without being identity evidence",
     case_an_exemplar_may_be_gained_without_being_identity_evidence),
    ("VS-3b — a zero identity row is 'no subject', not a bad match",
     case_a_zero_identity_row_is_no_subject_not_a_bad_match),
    ("VS-3b — two identity pipelines are refused",
     case_two_identity_pipelines_are_refused),
    ("VS-3b — a confirmed subject the identity space cannot use is named",
     case_a_confirmed_subject_the_identity_space_cannot_use_is_named),
    ("VS-3b — a pack that never ran the identity stage is not a defect",
     case_a_pack_that_never_ran_the_identity_stage_is_not_a_defect),

    ("SNS-16 — a draft joins a remembered subject and moves nothing else",
     case_a_draft_joins_a_remembered_subject_and_moves_nothing_else),
    ("SNS-16 — a promotion refuses what it cannot attest",
     case_a_promotion_refuses_what_it_cannot_attest),
    ("step 9 — the partition refusal speaks for the verb",
     case_the_partition_refusal_speaks_for_the_verb),
    ("step 9 — the audit log is provenance, and not pack state",
     case_the_audit_log_is_provenance_and_not_pack_state),
    ("an empty pack is a strict no-op", case_an_empty_pack_is_a_strict_no_op),
    ("only viewed-image provenance may become an exemplar",
     case_only_viewed_image_may_become_an_exemplar),
    ("the exemplar cap is diversity-kept, not oldest-first",
     case_the_cap_is_diversity_kept_not_oldest_first),
    ("the timeline gate reads the file's own date, never a path",
     case_the_timeline_gate_reads_the_files_own_date),
    ("the tolerance widens the gate and does not remove it",
     case_the_tolerance_widens_the_gate_and_does_not_remove_it),
    ("thresholds decide accept / gray / none",
     case_thresholds_decide_accept_gray_and_none),
    ("two lookalike subjects are a question, never a merge",
     case_two_lookalike_subjects_are_a_question_never_a_merge),
    ("F14 — a confirmed subject suppresses a new draft, and merges nothing",
     case_a_confirmed_subject_suppresses_a_new_draft),
    ("the suppression bar is its own parameter, not the dedupe's",
     case_the_suppression_bar_is_its_own_parameter),
    ("suppression keeps the kind guard and the cross-model refusal",
     case_suppression_holds_the_same_guards_as_the_dedupe),
    ("a confirmed subject with no exemplars suppresses nothing",
     case_a_subject_with_no_exemplars_suppresses_nothing),
    ("forms_own_folder is derived and overridable",
     case_forms_own_folder_is_derived_and_overridable),
    ("a rename keeps the key and the ledger resolves it",
     case_a_rename_keeps_the_key_and_the_ledger_resolves),
    ("subject ids are unique and never reused",
     case_subject_ids_are_unique_and_do_not_reuse),
    ("a saved registry reloads with its vectors aligned",
     case_a_saved_registry_reloads_with_its_vectors_aligned),
    ("a registry from another model is refused",
     case_a_registry_from_another_model_is_refused),
    ("review lists, and prune needs --go", case_review_lists_and_prune_needs_go),
    ("SNS-10 — an exemplar carries the capture date, or an explicit null",
     case_an_exemplar_carries_the_capture_date_or_an_explicit_null),
    ("SNS-5 — un-confirm returns a subject to the draft pool, centroid and all",
     case_unconfirm_returns_a_subject_to_the_draft_pool),
    ("a withdrawn subject recognises nothing, on the evidence it kept",
     case_a_withdrawn_subject_recognises_nothing),
    ("re-confirming costs nothing — no dump, no re-derivation",
     case_re_confirming_costs_nothing),
    ("un-confirm refuses what was never confirmed",
     case_unconfirm_refuses_what_was_never_confirmed),
    ("--unconfirm is a dry run until --go",
     case_unconfirm_is_a_dry_run_until_go),
    ("SNS-1b — a draft split across two rows is superseded",
     case_a_draft_split_across_two_rows_is_superseded),
    ("one pick row is never a split, however few frames it names",
     case_one_pick_row_is_never_a_split),
    ("a partition refuses a parent that holds a name",
     case_a_partition_refuses_a_parent_that_holds_a_name),
    ("a child never inherits the parent's centroid",
     case_a_child_never_inherits_the_parents_centroid),
    ("a partition refuses frames it cannot place",
     case_a_partition_refuses_frames_it_cannot_place),
    ("OA-19 — the shared refusal teaches the two-row answer",
     case_the_shared_refusal_teaches_the_two_row_answer),
    ("F-o: the shared refusal names every bad row (REPRO)",
     case_the_shared_refusal_names_every_bad_row),
    ("a superseded parent is not revivable",
     case_a_superseded_parent_is_not_revivable),
    ("a superseded parent cannot be promoted onto",
     case_a_superseded_parent_cannot_be_promoted_onto),
    ("a superseded parent cannot be renamed",
     case_a_superseded_parent_cannot_be_renamed),
    ("OA-14 — a rejection suppresses on its retained centroid",
     case_a_rejection_suppresses_on_its_retained_centroid),
    ("a live draft outscores a rejection",
     case_a_live_draft_outscores_a_rejection),
    ("OA-16 — a rejected record holds no name and gains nothing",
     case_a_rejected_record_holds_no_name_and_gains_nothing),
    ("a rejection is taken back by revive alone",
     case_a_rejection_is_taken_back_by_revive_alone),
    ("--revive is a dry run until --go",
     case_revive_is_a_dry_run_until_go),
    ("SNS-5 — taking a decision back flags the record for the question loop",
     case_taking_a_decision_back_flags_it_for_the_question_loop),
    ("SNS-9 — the re-confirmation frame budget is its own number",
     case_the_reconfirmation_frame_budget_is_its_own_number),
    ("SNS-15 — the sweep bar is its own parameter, and keeps the kind guard",
     case_the_sweep_bar_is_its_own_parameter_and_keeps_the_kind_guard),
    ("SNS-15 — an absorbed record cannot be renamed",
     case_an_absorbed_record_cannot_be_renamed),
    ("SNS-14 — the fold keeps the earlier id and joins the exemplars",
     case_the_fold_keeps_the_earlier_id_and_joins_the_exemplars),
    ("SNS-14 — a chained fold never points a tombstone at a tombstone",
     case_a_chained_fold_never_points_a_tombstone_at_a_tombstone),
    ("SNS-14 — a fold is refused across kinds and onto a closed record",
     case_a_fold_is_refused_across_kinds_and_onto_a_closed_record),
    ("SNS-14 — a tombstone refuses every verb and never moves the winner",
     case_a_tombstone_refuses_every_verb_and_never_moves_the_winner),
    ("the rename ledger resolves by precedence, not by list order",
     case_the_rename_ledger_resolves_by_precedence_not_by_order),
    ("SNS-15 — the absorbed count is summed at read time and un-summed",
     case_the_absorbed_count_is_summed_at_read_time_and_un_summed),
    ("the shipped template holds no subjects",
     case_the_shipped_template_holds_no_subjects),
    ("card (c) — an absorb records the space it ran in",
     case_an_absorb_records_the_space_it_ran_in),
    ("card (c) — the recorded space is the one that ran",
     case_the_swept_space_is_the_one_that_ran),
    ("card (c) — an unrecorded space is never guessed",
     case_an_unrecorded_space_is_never_guessed),
    ("card (c) — an owner-answered absorb claims no space",
     case_an_owner_answered_absorb_claims_no_space),
    ("card (c) — a release keeps the space it was absorbed in",
     case_a_release_keeps_the_space_it_was_absorbed_in),
    ("D-25 route — the pack binds by --profile", case_route_profile_flag),
    ("D-25 route — the pack binds by $PHOTO_PROFILE",
     case_route_photo_profile_env),
    ("D-25 route — the pack binds by collection.json via the work dir",
     case_route_collection_json_via_workdir),
    ("D-25 route — the pack binds by collection.json from the workspace folder",
     case_route_collection_json_from_the_workspace_folder),
    ("D-25 route — nothing bound, off a workspace: still fails closed",
     case_route_none_still_fails_closed),
    ("U-1 — --merge rejoins one animal held under two confirmed ids",
     case_merge_rejoins_one_animal_held_under_two_confirmed_ids),
    ("U-1 — the merged vector rows stay in step with the exemplars",
     case_merge_keeps_the_vector_rows_in_step_with_the_exemplars),
    ("U-1 — --merge is a dry run until --go",
     case_merge_is_a_dry_run_until_go),
    ("U-1 — a refused merge exits 2 and writes nothing",
     case_merge_refuses_and_exits_2_without_writing),
    ("U-1 — a merge applies the exemplar cap the way --prune does",
     case_merge_applies_the_cap_the_way_prune_does),
]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    passed = 0
    for name, fn in CASES:
        tmp = None
        try:
            if name in NEEDS_TMP:
                tmp = Path(tempfile.mkdtemp(prefix="photo_subjects_"))
                fn(tmp)
            else:
                fn()
        except Exception as exc:
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"  ok    {name}")
            passed += 1
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{passed}/{len(CASES)} photo_subjects cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
