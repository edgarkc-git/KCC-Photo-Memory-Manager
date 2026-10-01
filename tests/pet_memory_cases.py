#!/usr/bin/env python3
"""Card 8 (pet memory) — owner rulings Q8-a, Q8-b, Q8-c (20260924).

UAT02-03: look-alike street cats photographed ~50 km from home were filed onto
the owner's two confirmed pets with no question (F-21), nothing could take ONE
wrong photo back out (F-23), and a dog in a picture frame or a reflection was
counted as another animal (F-04, F-27). Each case says REPRO (fails on
3a68ccd) or GUARD. Built on `photo_memory_cases`' fixtures, whose default pack
has one home and photographs at it.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
import photo_memory_cases as pmc  # noqa: E402
import photo_memory as pm  # noqa: E402
import photo_profile  # noqa: E402
import photo_subjects as psub  # noqa: E402

# ~55 km north of the fixture home: beyond the 3 km home range.
AWAY = "11.0 20.25"


def confirmed_pet(tmp):
    """A pet confirmed from photos taken at home. -> (pack_dir, subject_id)."""
    pack_dir, workdir = pmc.k_batch_run(tmp, 2)
    subject_id, rc = pmc.answer_the_question(pack_dir, workdir)
    assert rc == 0
    return pack_dir, subject_id


def sighting(tmp, pack_dir, gps, name="dump2", vec=None, away_km=None):
    """The pet's look-alike in a LATER dump, photographed at `gps`."""
    later = tmp / name
    pmc.write_batches(later, 1)
    if away_km is not None:
        batches = json.loads((later / "batches.json").read_text())
        batches["away_km"] = away_km
        (later / "batches.json").write_text(json.dumps(batches))
    report, index, samples = pmc.batch_fixture(
        later, 1, [(vec if vec is not None else pmc.basis(0), 3)],
        month="2029-07", gps=gps)
    summary = pmc.apply_and_memorize(
        later, pmc.open_pack(pack_dir), report, index, samples,
        {report["selected"][0]["path"]: {"label": "Cat", "subject_kind": "cat"}})
    return later, summary


def questions_in(pack_dir, workdir):
    pack = pmc.open_pack(pack_dir)
    questions, _s, _o, _h = pm.build_questions(
        psub.load(pack=pack), workdir, pack, pack.profile,
        photo_profile.review_messages(pack.profile))
    return questions


# ================================================================ Q8-a =====

def case_an_away_sighting_is_asked_not_filed(tmp):
    """REPRO Q8-a — the B6 street cats: recognised as the confirmed pet on
    geometry, written onto its record, and never put to the owner."""
    pack_dir, subject_id = confirmed_pet(tmp)
    before = len(psub.load(pack=pmc.open_pack(pack_dir)).get(subject_id)
                 .record.get("evidence") or [])
    later, summary = sighting(tmp, pack_dir, AWAY)
    assert summary["recognised"] == [], summary["recognised"]
    assert len(summary["asked_away"]) == 1, summary
    registry = psub.load(pack=pmc.open_pack(pack_dir))
    assert len(registry.get(subject_id).record.get("evidence") or []) == before, \
        "the away sighting was written onto the confirmed pet"
    draft = registry.get(summary["asked_away"][0]["subject_id"])
    assert draft.record.get("asked_away") is True, draft.record
    assert questions_in(pack_dir, later), "the away sighting reached no page"


def case_a_sighting_with_no_gps_is_asked(tmp):
    """REPRO Q8-a (ruling 1) — no GPS on any photo is ASKED: the batch's
    place is never borrowed (F-12)."""
    pack_dir, _sid = confirmed_pet(tmp)
    _later, summary = sighting(tmp, pack_dir, "-")
    assert summary["recognised"] == [] and len(summary["asked_away"]) == 1, summary


def case_a_home_sighting_is_still_recognised(tmp):
    """GUARD Q8-a — near a home, today's behaviour stays (F14)."""
    pack_dir, subject_id = confirmed_pet(tmp)
    _later, summary = sighting(tmp, pack_dir, pmc.AT_HOME)
    assert [r["subject_id"] for r in summary["recognised"]] == [subject_id], summary
    assert summary["asked_away"] == [], summary


def case_a_travel_to_home_counts_as_home(tmp):
    """GUARD Q8-a — a `home_range: false` home is still a home for this gate:
    the owner's pets are there."""
    pack_dir, subject_id = confirmed_pet(tmp)
    pmc.add_homes(pack_dir, [dict(pmc.FIXTURE_HOME),
                             {"id": "home-02", "label": None, "lat": 11.0,
                              "lon": 20.25, "home_range": False}])
    _later, summary = sighting(tmp, pack_dir, AWAY)
    assert [r["subject_id"] for r in summary["recognised"]] == [subject_id], summary


def case_the_runs_own_home_range_is_used(tmp):
    """GUARD Q8-a — the range this run cut its batches with (`batches.json`)
    decides, so the gate cannot disagree with the day types beside it."""
    pack_dir, subject_id = confirmed_pet(tmp)
    _later, summary = sighting(tmp, pack_dir, AWAY, away_km=100)
    assert [r["subject_id"] for r in summary["recognised"]] == [subject_id], summary


def case_the_sweep_leaves_an_asked_draft_open(tmp):
    """REPRO Q8-a (a6) — the second silent route: a confirm's SNS-15 sweep
    absorbed an open look-alike draft on geometry, which ends its question."""
    pack_dir = pmc.make_pack(tmp)
    pack = pmc.open_pack(pack_dir)
    workdir = tmp / "dump"
    pmc.write_batches(workdir, 2)
    close = pmc.unit(pmc.basis(0) + 0.67 * pmc.basis(1))
    for batch, vec, gps in ((1, pmc.basis(0), pmc.AT_HOME), (2, close, AWAY)):
        report, index, samples = pmc.batch_fixture(
            workdir, batch, [(vec, 3)], month=f"2029-0{batch}", gps=gps)
        pmc.apply_and_memorize(workdir, pack, report, index, samples,
                               {report["selected"][0]["path"]:
                                {"label": "Cat", "subject_kind": "cat"}})
    registry = psub.load(pack=pmc.open_pack(pack_dir))
    ids = sorted(d.subject_id for d in registry.drafts)
    assert len(ids) == 2, ids
    registry.data.setdefault("defaults", {})["sweep_absorb_tau"] = 0.80
    registry.save()
    named, rc = pmc.answer_the_question(pack_dir, workdir, name="Name-Two")
    assert rc == 0
    other = [i for i in ids if i != named][0]
    left = psub.load(pack=pmc.open_pack(pack_dir)).get(other)
    assert left.status != psub.STATUS_ABSORBED, left.record
    assert other in {d.subject_id for d in
                     psub.load(pack=pmc.open_pack(pack_dir)).drafts}


# ================================================================ Q8-b =====

def remembered(tmp):
    """A named pet shown on a page with its two photos: one is an example of
    what it looks like (refs[0]), one only a sighting (refs[1]).
    -> (pack_dir, workdir, subject_id, refs, page path, {ref: frame n})."""
    pack_dir, workdir, sid, refs = pmc.two_looks_apart(tmp, frames=2)
    page = pmc.review_text(pack_dir, workdir)
    shown = pm.parse_shown(page.read_text())[sid]
    frame_of = {ref: n for ref in refs for n, short in shown.items()
                if short == pm.short_ref(ref)}
    assert len(frame_of) == 2, (shown, refs)
    return pack_dir, workdir, sid, refs, page, frame_of


def answer(page, sid, value):
    text = page.read_text()
    row = f"`recheck:` {sid} ______"
    assert row in text, text
    page.write_text(text.replace(row, f"`recheck:` {sid} {value}"))


def subject_of(pack_dir, sid):
    return psub.load(pack=pmc.open_pack(pack_dir)).get(sid)


def looks_of(subject):
    return {l["vec_ref"] for e in subject.record.get("evidence") or []
            for l in e.get("looks") or []}


def case_not_takes_one_photo_out_and_keeps_the_name(tmp):
    """REPRO Q8-b — `not <frame>` removes that photo from the pet's memory.
    At 3a68ccd the leftover text `not 2` was read as a NEW NAME (A20)."""
    pack_dir, workdir, sid, refs, page, frame_of = remembered(tmp)
    answer(page, sid, f"not {frame_of[refs[1]]}")
    rc, said = pmc.confirm(pack_dir, workdir)
    got = subject_of(pack_dir, sid)
    assert got.name == "Name-Two" and got.status == psub.STATUS_CONFIRMED, (got.record, said)
    assert refs[1] not in looks_of(got) and refs[0] in looks_of(got), got.record
    assert [e["vec_ref"] for e in got.record["not_this"]] == [refs[1]], got.record
    trail = psub.load(pack=pmc.open_pack(pack_dir)).audit_trail()
    assert any(r.get("decision") == "not-this" and r.get("vec_ref") == refs[1]
               for r in trail), trail


def case_not_on_an_example_photo_drops_the_example(tmp):
    """REPRO Q8-b — a photo that was an example of the pet leaves the bank."""
    pack_dir, workdir, sid, refs, page, frame_of = remembered(tmp)
    answer(page, sid, f"not{frame_of[refs[0]]}")
    pmc.confirm(pack_dir, workdir)
    got = subject_of(pack_dir, sid)
    assert refs[0] not in {e["vec_ref"] for e in got.exemplars}, got.exemplars
    assert got.name == "Name-Two"


def case_a_taken_out_photo_does_not_come_back(tmp):
    """REPRO Q8-b — the next memorize of the same photos, at home, files the
    sighting again but never carries the taken-out photo back, and the next
    page does not show it."""
    pack_dir, workdir, sid, refs, page, frame_of = remembered(tmp)
    answer(page, sid, f"not {frame_of[refs[1]]}")
    pmc.confirm(pack_dir, workdir)
    report = json.loads((workdir / "classify" / "batch-02" / "see-report.json")
                        .read_text())
    import photo_see
    index, _identity = photo_see.load_index(workdir)
    summary = pmc.apply_and_memorize(workdir, pmc.open_pack(pack_dir), report, index,
                           workdir / "classify" / "batch-02" / "samples",
                           {report["selected"][0]["path"]:
                            {"label": "Cat", "subject_kind": "cat"}})
    assert [r["subject_id"] for r in summary["recognised"]] == [sid], summary
    got = subject_of(pack_dir, sid)
    assert refs[1] not in looks_of(got), "the taken-out photo came back"
    text = pmc.review_text(pack_dir, workdir, checkpoint=2).read_text()
    assert pm.short_ref(refs[1]) not in json.dumps(pm.parse_shown(text)), text


def case_typos_are_refused_never_a_name(tmp):
    """REPRO Q8-b (ruling 3) — `nto 2` renamed the pet at 3a68ccd. A bare
    number, a bare `not`, a frame from elsewhere and `not` with a name are
    each refused whole, and the refusal says how to type it."""
    for value, want in (("nto 2", "not 2"), ("not", "e.g. `not 3`"),
                        ("not 9", "not among this subject's photos"),
                        ("not 1 Fluffy", "whole answer on its row")):
        sub = tmp / value.replace(" ", "_")
        sub.mkdir()
        pack_dir, workdir, sid, refs, page, _f = remembered(sub)
        answer(page, sid, value)
        rc, said = pmc.confirm(pack_dir, workdir)
        got = subject_of(pack_dir, sid)
        assert got.name == "Name-Two", (value, got.name)
        assert not got.record.get("not_this"), (value, got.record)
        assert want in said, (value, said)


def case_the_forms_of_not_parse_alike(tmp):
    """GUARD Q8-b — `not 1`, `not1`, `not: 1`, `not 1,2`, `not 1 2`."""
    for value, frames in (("not 1", [1]), ("not1", [1]), ("not: 1", [1]),
                          ("not 1,2", [1, 2]), ("not 1 2", [1, 2])):
        rows = pm.parse_representations(f"> - `recheck:` subj-0001 {value}\n")
        assert rows and rows[0]["not_frames"] == frames and not rows[0]["name"], \
            (value, rows)


def case_the_dry_run_writes_nothing(tmp):
    """GUARD Q8-b — the dry run predicts and writes nothing, audits nothing."""
    pack_dir, workdir, sid, refs, page, frame_of = remembered(tmp)
    answer(page, sid, f"not {frame_of[refs[1]]}")
    before = pmc.open_pack(pack_dir).snapshot()
    rc, said = pmc.confirm(pack_dir, workdir, go=False)
    assert "would take 1 photo(s) out" in said, said
    assert pmc.open_pack(pack_dir).snapshot() == before


def case_only_the_owners_pick_lifts_not(tmp):
    """GUARD Q8-b (ruling 2) — an automatic exemplar is refused; the owner's
    own pick of that photo for that pet lifts `not`."""
    pack_dir, workdir, sid, refs, page, frame_of = remembered(tmp)
    registry = psub.load(pack=pmc.open_pack(pack_dir))
    subject = registry.get(sid)
    entry = next(e for e in subject.record["evidence"]
                 if any(l["vec_ref"] == refs[1] for l in e["looks"]))
    look = dict(next(l for l in entry["looks"] if l["vec_ref"] == refs[1]))
    registry.take_out_photos(sid, [refs[1]], by="Test Operator")
    import photo_see
    index, identity = photo_see.load_index(workdir)
    try:
        registry.add_exemplar(sid, index[look["path"]][1], refs[1], look["path"],
                              confirmed_by="viewed-image:", identity=identity,
                              evidence=look)
        raise AssertionError("an automatic exemplar ignored `not`")
    except ValueError as exc:
        assert "not" in str(exc), exc
    subject.record["evidence"].append({"batch": 2, "looks": [look]})
    gained, notes = pm.attach_exemplars(registry, subject, [refs[1]])
    assert not subject.record["not_this"], subject.record["not_this"]
    assert any("lifted" in n for n in notes), notes


# ================================================================ Q8-c =====

def case_a_crop_mark_does_not_set_the_photos_basis(tmp):
    """REPRO Q8-c — the page's combined row `4 confirm, 1.2 not-a-subject`
    recorded frame 4's rejection as "never an animal" (U2-10's stronger
    claim, which the owner did not make)."""
    head = ("**Q1 · Group it — Cat** — affects 2 file(s) / 1 batch(es)\n"
            "> `subjects:` 1=subj-0001, 4=subj-0004\n")
    block = pm.parse_review(head + "> - `skip:` 4 confirm, 1.2 not-a-subject\n")[0]
    assert block["skip_numbers"] == [4] and block["skip_animals_armed"], block
    assert block["skip_basis"] == pm.BASIS_NOT_MINE, block["skip_basis"]
    block = pm.parse_review(
        head + "> - `skip:` 4 not-a-subject confirm, 1.2 not-a-subject\n")[0]
    assert block["skip_basis"] == pm.BASIS_NOT_A_SUBJECT, block


def marks_on_route(tmp, route, with_pack=True):
    """The agent's mark, then the count as a later stage reads it, on ONE pack
    route (A42 / LL-PHO-132). -> (count, stderr)."""
    import contextlib as _c
    import identify_cases as idc
    import photo_identity
    orig = idc.id_dump
    idc.id_dump = lambda t, frames, route_=route, clip=None: orig(
        t, frames, route=route_, clip=clip)
    try:
        wd, pack = shared_dump(tmp)
    finally:
        idc.id_dump = orig
    extra = (["--profile", str(pack / photo_profile.PROFILE_NAME)]
             if route == "profile" else [])
    idc.ix.run("identify", wd, *extra)
    idc.answer(wd, {("TWO_3.jpg", idc.JUNIPER): "not-animal"})
    code, out, _err = idc.go(wd, extra)
    assert code == 0, out
    err = io.StringIO()
    # Card 9 — read the way a stage reads: with the pack IT was given. Only
    # the --profile route has one to pass; the other two bind it themselves.
    stage_pack = ((pack,) if route == "profile" and with_pack else ())
    with _c.redirect_stderr(err):
        by_file, _s = photo_identity.load_detections(wd / "embed", *stage_pack)
    return int(next(iter(by_file.values()))[0][0]["det_count"]), err.getvalue()


def case_marks_are_read_on_the_collection_route(tmp):
    """GUARD Q8-c — collection.json binding: the mark is read."""
    import identify_cases as idc
    with idc.ix.no_env():
        count, _err = marks_on_route(tmp, "collection")
    assert count == 1


def case_marks_are_read_on_the_env_route(tmp):
    """GUARD Q8-c — $PHOTO_PROFILE binding: the mark is read."""
    import identify_cases as idc
    with idc.ix.no_env():
        count, _err = marks_on_route(tmp, "env")
    assert count == 1


def case_marks_are_read_on_the_profile_route(tmp):
    """REPRO Card 9 item 4 — a pack bound by --profile ALONE never reached the
    readers (`photo_index.load(workdir, None)`), so the agent's mark was
    written and every stage still counted two animals."""
    import identify_cases as idc
    with idc.ix.no_env():
        count, err = marks_on_route(tmp, "profile")
    assert count == 1 and "NOT applied" not in err, (count, err)


def case_a_reader_given_no_pack_still_says_so(tmp):
    """GUARD Card 9 item 4 — the last resort stays: a reader handed no pack
    on a --profile-only dump says the marks were not applied, never silent."""
    import identify_cases as idc
    import photo_identity
    photo_identity._MARKS_UNREAD.clear()
    with idc.ix.no_env():
        count, err = marks_on_route(tmp, "profile", with_pack=False)
    assert count == 2 and "NOT applied" in err, (count, err)


def owner_page_on_route(tmp, route):
    """Card 9 item 4 — Q8-c's end-to-end page (below) on ONE pack route: the
    owner's `skip: 1.2 not-a-subject` beside `pick: 1 … Pebble same`, through
    `confirm --page --go` and `apply-page --go`, with the pack reaching every
    stage only the way `route` binds it (LL-PHO-132). -> what to assert on."""
    import argparse
    import csv
    import numpy as np
    import batch_page_cases as bpc
    import identify_cases as idc
    import photo_embed
    import photo_identity
    import photo_onboard_page as op
    saved = photo_embed.convert_to_thumbnail
    photo_embed.convert_to_thumbnail = idc.thumbnail_stub()
    try:
        with bpc.fixture_env():
            wd, pack_dir, extra = bpc.page_dump(tmp, pets=(1,), place_batches=(),
                                                route=route)
            op.declare_pets(str(pack_dir), ["Pebble"])
            src = str(wd / "B1_C0_000.JPG")
            with open(wd / "embed" / "embeddings.csv", newline="") as fh:
                sha = next(r["sha256"] for r in csv.DictReader(fh)
                           if r["SourceFile"] == src)
            embed = wd / "embed"
            rows = [{"SourceFile": src, "sha256": sha, "status": photo_identity.STATUS_OK,
                     "det_index": d, "det_count": 2, "kind": "cat", "det_score": 0.9,
                     "box": box, "box_share": 0.5, "error": ""}
                    for d, box in ((0, "0,0,20,20"), (1, "20,0,40,20"))]
            with open(embed / "identity.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=photo_identity.CSV_FIELDS)
                w.writeheader()
                w.writerows(rows)
            with open(embed / "identity.npy", "wb") as fh:
                np.save(fh, np.stack([idc.e(0), idc.e(1)]))
            (embed / "identity-meta.json").write_text(json.dumps(
                {**photo_identity.meta_identity(idc.DIM),
                 "created_at": "2029-01-01 00:00"}))
            rc_page, said_page = bpc.next_page(wd, extra)
            page = wd / "P-B01.md"
            text = pmc.fill_pick(page.read_text(), [1], who="pet", name="Pebble same")
            page.write_text(text.replace("`skip:` ______",
                                         "`skip:` 1.2 not-a-subject", 1))
            said = io.StringIO()
            with contextlib.redirect_stdout(said):
                try:
                    rc = pm.cmd_confirm(argparse.Namespace(
                        workdir=str(wd), profile=bpc.profile_arg(extra),
                        checkpoint=1, file=None, page="P-B01", sync=False,
                        by="Test Operator", go=True))
                except SystemExit as stop:
                    rc = f"exit: {stop}"
            code, out, err = bpc.apply_page(wd, "P-B01", "--go", *extra)
            index = bpc.index_of(tmp)
            named = bpc.subjects_named(pack_dir, "Pebble")
    finally:
        photo_embed.convert_to_thumbnail = saved
    return {"rc_page": (rc_page, said_page), "rc": rc, "said": said.getvalue(),
            "apply": (code, out, err), "sha": sha,
            "marks": [(m["sha256"], m["det_index"])
                      for m in index.get("not_animals") or []],
            "exemplars": len((named.get("Pebble") or {}).get("exemplars") or [])}


def assert_owner_page(got):
    assert got["rc_page"][0] == pm.PAGE_WRITTEN_RC, got["rc_page"][1]
    assert got["rc"] == 0 and got["apply"][0] == 0, (got["rc"], got["said"],
                                                    got["apply"])
    assert got["marks"] == [(got["sha"], 1)], got["marks"]
    # the SAME confirm reads the mark back: the frame is one animal, so the
    # pick is not a shared-frame row and the photo becomes an exemplar
    assert "2+ animals" not in got["said"], got["said"]
    assert got["exemplars"] >= 1, got["said"]


def case_owner_page_marks_on_the_profile_route(tmp):
    """REPRO Card 9 item 4 — `--profile` only: the mark was written and the
    same confirm read the frame as TWO animals."""
    import identify_cases as idc
    with idc.ix.no_env():
        got = owner_page_on_route(tmp, "profile")
    assert_owner_page(got)


def case_owner_page_marks_on_the_env_route(tmp):
    """GUARD Card 9 item 4 — `$PHOTO_PROFILE` only."""
    import identify_cases as idc
    with idc.ix.no_env():
        got = owner_page_on_route(tmp, "env")
    assert_owner_page(got)


def case_owner_page_marks_on_the_collection_route(tmp):
    """GUARD Card 9 item 4 — `collection.json` only."""
    import identify_cases as idc
    with idc.ix.no_env():
        got = owner_page_on_route(tmp, "collection")
    assert_owner_page(got)


def shared_dump(tmp):
    """One photo, two detections: animal 1 looks like one pet, animal 2 like
    another. Identity rows carry the file's sha, as a real index does.
    -> (work dir, pack dir)."""
    import csv
    import identify_cases as idc
    import photo_identity
    two = ("TWO_3.jpg", 3, [idc.e(0), idc.e(1)], True, None)
    wd, pack, _extra = idc.id_dump(tmp, [two])
    path = wd / "embed" / "identity.csv"
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["sha256"] = "sha256:" + Path(r["SourceFile"]).name
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=photo_identity.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return wd, pack


def agent_marks(tmp, subject_marked):
    """The agent's identify views, with `not-animal` on the row proposing
    `subject_marked`. -> (work dir, exit code, output)."""
    import identify_cases as idc
    wd, _pack = shared_dump(tmp)
    idc.ix.run("identify", wd)
    idc.answer(wd, {("TWO_3.jpg", subject_marked): "not-animal"})
    code, out, _err = idc.go(wd)
    return wd, code, out


def case_the_agent_marks_a_crop_not_an_animal(tmp):
    """REPRO Q8-c — the agent's `not-animal` verdict on one crop drops it from
    the frame's count, so a frame left with ONE animal can be an exemplar."""
    import identify_cases as idc
    import photo_identity
    with idc.ix.no_env():
        wd, code, out = agent_marks(tmp, idc.JUNIPER)
        by_file, _s = photo_identity.load_detections(wd / "embed")
        entries = next(iter(by_file.values()))
        ok, why = photo_identity.exemplar_quality(entries[0][0])
        animals = pm.frame_animals(wd)
    assert code == 0, out
    assert len(entries) == 1 and int(entries[0][0]["det_count"]) == 1, entries
    assert list(animals.values()) == [1], animals
    assert ok, why


def case_marking_the_first_animal_repicks_the_primary(tmp):
    """REPRO Q8-c (trap c5) — `load_index()` kept det_index 0 only; marking it
    must make the remaining animal the file's identity vector, never the fake."""
    import identify_cases as idc
    import numpy as np
    import photo_identity
    with idc.ix.no_env():
        wd, code, out = agent_marks(tmp, idc.LOTUS)
        index, _space = photo_identity.load_index(wd / "embed")
    row, vec = next(iter(index.values()))
    assert int(row["det_index"]) == 1, row
    assert np.allclose(vec, idc.e(1)), vec


def case_a_stale_mark_is_not_applied(tmp):
    """GUARD Q8-c — a mark whose box no longer matches (the photo was detected
    again) is ignored, never moved onto another animal."""
    import photo_identity
    by_file = {"/x/a.jpg": [({"sha256": "sha256:a", "det_index": 0, "det_count": 2,
                              "status": photo_identity.STATUS_OK, "box": "0,0,9,9"}, 0),
                             ({"sha256": "sha256:a", "det_index": 1, "det_count": 2,
                               "status": photo_identity.STATUS_OK, "box": "5,5,9,9"}, 1)]}
    got = photo_identity.apply_marks(by_file, [{"sha256": "sha256:a", "det_index": 1,
                                                "box": "1,1,2,2"}])
    assert got == by_file, got


def case_skip_one_crop_is_not_two_frames(tmp):
    """REPRO Q8-c — `skip: 1.2 not-a-subject` was read as frames 1 AND 2,
    which rejects two subjects nobody skipped."""
    text = ("**Q1 · Group it — Cat** — affects 2 file(s) / 1 batch(es)\n"
            "> `subjects:` 1=subj-0001, 2=subj-0002\n"
            "> - `skip:` 1.2 not-a-subject\n")
    block = pm.parse_review(text)[0]
    assert block["skip_numbers"] == [] and block["skip_animals"] == [(1, 2)], block


def case_the_owner_marks_a_crop_on_the_page(tmp):
    """REPRO Q8-c — the owner's `skip: 1.2 not-a-subject` writes the mark into
    the dump's index (freeze-covered), and the frame counts one animal."""
    import identify_cases as idc
    with idc.ix.no_env():
        wd, _pack = shared_dump(tmp)
        block = {"n": 1, "skip_animals": [(1, 2)], "skip_animals_armed": True,
                 "frames": {1: {"subject_id": "subj-0009",
                                "ref": pm.short_ref("sha256:TWO_3.jpg")}}}
        refusals, changes = pm.RefusalChannel(), []
        marks = pm.mark_not_animals(wd, None, [block], refusals, changes,
                                    "Test Operator", "P-B03.md", True)
        index = idc.index_now(tmp)
        animals = pm.frame_animals(wd)
    assert not list(refusals), list(refusals)
    assert len(marks) == 1 and len(index.get("not_animals") or []) == 1, index
    assert list(animals.values()) == [1], animals
    assert any("marked not a real animal" in e["change"] for e in index["log"])


def case_a_crop_skip_needs_not_a_subject(tmp):
    """GUARD Q8-c — a crop ref only means *not a real animal*; without the
    word it is refused and nothing is marked."""
    block = {"n": 1, "skip_animals": [(1, 2)], "skip_animals_armed": False,
             "frames": {1: {"ref": "abc"}}}
    refusals, changes = pm.RefusalChannel(), []
    marks = pm.mark_not_animals(tmp, None, [block], refusals, changes, "T",
                                "P-B01.md", True)
    assert marks == [] and any("not-a-subject" in r for r in refusals), list(refusals)


def case_a_labelled_crop_still_parses_on_the_html_page(tmp):
    """GUARD Q8-c — `(animal 1.2)` beside the frame number keeps the place
    phrase and the frame number readable to the HTML page (LL-PHO-188)."""
    import photo_review_page as rp
    line = "> ![](review-crops/abc_d1.jpg) [frame 1] (animal 1.2) · taken at Home-A"
    m = rp.RE_IMG.match(line)
    assert m and m.group(2) == "1" and m.group(3) == "taken at Home-A", m
    assert rp.RE_CROP_ANIMAL.search(line).group(1) == "2"


def case_a_shared_frame_page_end_to_end(tmp):
    """Q8-c END TO END (Lead/owner 20260925) — a real batch page over a photo
    with two detections, one real animal and one fake (a picture in a frame),
    answered `pick: 1 … Pebble same` + `skip: 1.2 not-a-subject` on the same
    frame, through `confirm --page` (dry run, then --go) and `apply-page --go`.
    The mark lands in the dump index, the frame recounts to ONE animal, the
    pick names only the real animal, the photo becomes an exemplar, and
    nothing is refused."""
    import csv
    import numpy as np
    import batch_page_cases as bpc
    import identify_cases as idc
    import photo_embed
    import photo_identity
    import photo_onboard_page as op
    import photo_plan
    saved = photo_embed.convert_to_thumbnail
    photo_embed.convert_to_thumbnail = idc.thumbnail_stub()
    try:
        with bpc.fixture_env():
            wd, pack_dir, extra = bpc.page_dump(tmp, pets=(1,), place_batches=())
            op.declare_pets(str(pack_dir), ["Pebble"])
            src = str(wd / "B1_C0_000.JPG")
            with open(wd / "embed" / "embeddings.csv", newline="") as fh:
                sha = next(r["sha256"] for r in csv.DictReader(fh)
                           if r["SourceFile"] == src)
            embed = wd / "embed"
            rows = [{"SourceFile": src, "sha256": sha, "status": photo_identity.STATUS_OK,
                     "det_index": d, "det_count": 2, "kind": "cat", "det_score": 0.9,
                     "box": box, "box_share": 0.5, "error": ""}
                    for d, box in ((0, "0,0,20,20"), (1, "20,0,40,20"))]
            with open(embed / "identity.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=photo_identity.CSV_FIELDS)
                w.writeheader()
                w.writerows(rows)
            with open(embed / "identity.npy", "wb") as fh:
                np.save(fh, np.stack([idc.e(0), idc.e(1)]))
            (embed / "identity-meta.json").write_text(json.dumps(
                {**photo_identity.meta_identity(idc.DIM),
                 "created_at": "2029-01-01 00:00"}))
            rc_page, said_page = bpc.next_page(wd, extra)
            page = wd / "P-B01.md"
            text = page.read_text()
            assert "(animal 1.2)" in text, text
            text = pmc.fill_pick(text, [1], who="pet", name="Pebble same")
            assert "`skip:` ______" in text, text
            page.write_text(text.replace("`skip:` ______",
                                         "`skip:` 1.2 not-a-subject", 1))
            before = json.dumps(bpc.index_of(tmp).get("not_animals"))
            rc_dry, said_dry = pmc.confirm_page(pack_dir, wd, page="P-B01", go=False)
            after_dry = json.dumps(bpc.index_of(tmp).get("not_animals"))
            rc, said = pmc.confirm_page(pack_dir, wd, page="P-B01", go=True)
            code, out, err = bpc.apply_page(wd, "P-B01", "--go")
            index = bpc.index_of(tmp)
            animals = pm.frame_animals(wd)
            by_file, _space = photo_identity.load_detections(embed)
            quality = photo_identity.exemplar_quality(by_file[src][0][0])
            named = bpc.subjects_named(pack_dir, "Pebble")
            pack = photo_profile.resolve_pack(explicit=pack_dir / photo_profile.PROFILE_NAME)
            cell = photo_plan.visual_columns(wd, [1], pack.profile, pack).get(src, {})
    finally:
        photo_embed.convert_to_thumbnail = saved
    assert rc_page == pm.PAGE_WRITTEN_RC, said_page
    assert rc_dry == 0 and before == after_dry, (rc_dry, said_dry)
    assert rc == 0 and code == 0, (rc, said, code, out, err)
    marks = index.get("not_animals") or []
    assert [(m["sha256"], m["det_index"]) for m in marks] == [(sha, 1)], marks
    assert animals[src] == 1, animals
    assert (cell.get("who") or "") == "Pebble", cell
    assert quality[0], quality
    assert "Pebble" in named and len(named["Pebble"].get("exemplars") or []) >= 1, \
        (named, said)
    assert "2+ animals" not in said and "refused" not in said.lower(), said


# ================================================================ HIL-7 ====

def index_looks(workdir, looks, det_count=1):
    """This dump's identity index over `looks`, `det_count` boxes each."""
    import csv
    import numpy as np
    import identify_cases as idc
    import photo_identity
    embed = Path(workdir) / "embed"
    embed.mkdir(parents=True, exist_ok=True)
    rows = [{"SourceFile": look["path"], "sha256": look["vec_ref"],
             "status": photo_identity.STATUS_OK, "det_index": d,
             "det_count": det_count, "kind": "cat", "det_score": 0.9,
             "box": "%d,0,%d,20" % (20 * d, 20 * d + 20), "box_share": 0.5,
             "error": ""} for look in looks for d in range(det_count)]
    with open(embed / "identity.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=photo_identity.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    with open(embed / "identity.npy", "wb") as fh:
        np.save(fh, np.stack([idc.e(i % idc.DIM) for i in range(len(rows))]))
    (embed / "identity-meta.json").write_text(json.dumps(
        {**photo_identity.meta_identity(idc.DIM), "created_at": "2029-01-01 00:00"}))


def end_page_with_index(tmp, det_count=1):
    """-> (the re-presented images on the end page, its text, the looks)."""
    import identify_cases as idc
    import photo_embed
    pack_dir, workdir, sid, refs = pmc.two_looks_apart(tmp, frames=2)
    looks = [l for e in subject_of(pack_dir, sid).record["evidence"]
             for l in e["looks"]]
    index_looks(workdir, looks, det_count)
    saved = photo_embed.convert_to_thumbnail
    photo_embed.convert_to_thumbnail = idc.thumbnail_stub()
    try:
        text = pmc.review_text(pack_dir, workdir).read_text()
    finally:
        photo_embed.convert_to_thumbnail = saved
    return pmc.rendered_frames(text), text, looks


def case_the_end_page_shows_the_crop_the_memory_holds(tmp):
    """REPRO HIL-7 — a re-presented frame is the CROP whose vector the pet
    holds. At beb57e9 it was the whole photo: a wrong example (the other cat
    cropped) looked right, because both cats were in the picture."""
    shown, text, looks = end_page_with_index(tmp)
    want = sorted(f"review-crops/{l['vec_ref']}_d0.jpg" for l in looks)
    assert sorted(shown) == want, (shown, want)
    assert all((tmp / "dump-betauser00" / s).is_file() for s in shown), shown


def case_a_shared_remembered_frame_shows_each_crop(tmp):
    """REPRO HIL-7 + frame-13 ruling (Lead 20261001) — a remembered photo
    with two animals holds NO crop of the pet (D-24 kept it out of every
    example space): the WHOLE photo comes first, each crop after it,
    labelled, and one plain line says what the memory holds."""
    shown, text, looks = end_page_with_index(tmp, det_count=2)
    assert sum("/samples/" in s for s in shown) == 2, shown
    assert sorted(s for s in shown if "review-crops/" in s) == sorted(
        f"review-crops/{l['vec_ref']}_d{d}.jpg" for l in looks for d in (0, 1)), shown
    lines = [l for l in text.splitlines() if "[frame" in l]
    firsts = {}
    for l in lines:
        n = l.split("[frame ")[1].split("]")[0]
        firsts.setdefault(n, l)
    assert all("/samples/" in l for l in firsts.values()), firsts
    assert text.count("(animal ") >= 4, text
    note = photo_profile.REVIEW_VOCAB["en"]["review_frame_shared_remembered"]
    said = [l for l in text.splitlines() if pm.SHARED_MARK in l]
    assert sorted(said) == sorted(
        "> " + note.format(n=n, count=2, subject="Name-Two") + " " + pm.SHARED_MARK
        for n in firsts), said


def case_a_remembered_frame_with_no_index_says_it_is_whole(tmp):
    """REPRO Q3 (Lead 20261001, replaces 20260929) — a look no index covers
    renders whole, and the page SAYS so beside it. Never a silent fallback."""
    pack_dir, workdir, sid, refs = pmc.two_looks_apart(tmp, frames=2)
    text = pmc.review_text(pack_dir, workdir).read_text()
    shown = pmc.rendered_frames(text)
    assert len(shown) == 2 and all("/samples/" in s for s in shown), shown
    note = photo_profile.REVIEW_VOCAB["en"]["review_frame_whole_note"]
    said = [l for l in text.splitlines() if pm.WHOLE_MARK in l]
    assert sorted(said) == sorted("> " + note.format(n=n) + " " + pm.WHOLE_MARK
                                  for n in (1, 2)), said


def earlier_dump_page(tmp, gone=False):
    """A pet remembered from an EARLIER dump, re-presented on a later one.
    -> (re-presented images, page text, the later work dir, the looks)."""
    import identify_cases as idc
    import photo_embed
    pack_dir, first, sid, refs = pmc.two_looks_apart(tmp, frames=2)
    looks = [l for e in subject_of(pack_dir, sid).record["evidence"]
             for l in e["looks"]]
    index_looks(first, looks)
    later = tmp / "dump-later"
    pmc.write_batches(later, 1)
    if gone:
        shutil.rmtree(first / "embed")
    saved = photo_embed.convert_to_thumbnail
    photo_embed.convert_to_thumbnail = idc.thumbnail_stub()
    try:
        text = pmc.review_text(pack_dir, later).read_text()
    finally:
        photo_embed.convert_to_thumbnail = saved
    return pmc.rendered_frames(text), text, later, looks


def case_an_earlier_dumps_look_shows_its_own_crop(tmp):
    """REPRO Q3 — a mature pet's least-sure photo is often from an earlier
    dump. That dump's own identity index is opened and its crop shown."""
    shown, text, later, looks = earlier_dump_page(tmp)
    want = sorted(f"review-crops/{l['vec_ref']}_d0.jpg" for l in looks)
    assert sorted(shown) == want, (shown, want)
    assert all((later / s).is_file() for s in shown), shown


def case_an_earlier_dump_without_its_index_says_whole(tmp):
    """GUARD Q3 — the earlier dump is still there but its animal index is
    not: the whole photo, with the note, and the page is still written."""
    shown, text, later, looks = earlier_dump_page(tmp, gone=True)
    assert len(shown) == 2 and all("/samples/" in s for s in shown), shown
    assert text.count(pm.WHOLE_MARK) == 2, text


def case_the_recheck_row_shows_a_filled_in_example(tmp):
    """REPRO HIL-5 follow-up — the owner left `recheck:` blank because he did
    not know what to type. The page now shows the row filled in, with THIS
    pet's id and the number of a photo printed above it."""
    pack_dir, workdir, sid, refs, page, frame_of = remembered(tmp)
    text = page.read_text()
    n = min(frame_of.values())
    example = f"`recheck: {sid} not {n}`"
    assert example in text, text.split("Remembered already")[-1]
    assert pm.parse_representations(text) == [], pm.parse_representations(text)


def case_the_example_typed_as_shown_takes_the_photo_out(tmp):
    """GUARD — typing exactly what the example shows is a working answer."""
    pack_dir, workdir, sid, refs, page, frame_of = remembered(tmp)
    n = min(frame_of.values())
    answer(page, sid, f"not {n}")
    rc, said = pmc.confirm(pack_dir, workdir)
    ref = [r for r, k in frame_of.items() if k == n][0]
    assert rc == 0 and ref not in looks_of(subject_of(pack_dir, sid)), said


def case_the_two_steps_say_the_same_in_text_and_on_the_web(tmp):
    """REPRO HIL-4 (owner ruling 20261001) — the page says plainly what to do with a
    photo holding several pets, in two steps, and the text page and the web
    page carry the SAME sentences: one source, printed verbatim."""
    import photo_review_page as rp
    pack_dir, workdir = pmc.k_batch_run(tmp, 2)
    page = pmc.review_text(pack_dir, workdir)
    text = page.read_text()
    vocab = photo_profile.REVIEW_VOCAB["en"]
    steps = [vocab["review_howto_step1"], vocab["review_howto_step2"]]
    assert all(f"> {s} {pm.HOWTO_MARK}" in text for s in steps), text
    assert "Name the animal in the picture shown." in steps[0], steps
    assert "not-a-subject" in steps[1] and "toy" in steps[1], steps
    out = workdir / "page.html"
    rp.main(["render", str(page), "-o", str(out)])
    html = out.read_text(encoding="utf-8")
    key = '<script id="round-data" type="application/json">'
    data = json.loads(html.split(key, 1)[1].split("</script>", 1)[0]
                      .replace("<\\/", "</"))
    assert data.get("howto") == steps, data.get("howto")
    assert "D.howto" in html, "the web page never prints them"


def case_the_examples_in_the_steps_are_never_an_answer(tmp):
    """GUARD HIL-4 — step 2 quotes `skip: 2.1 not-a-subject` and
    `skip: 3 confirm`; an untouched page must still answer nothing."""
    pack_dir, workdir = pmc.k_batch_run(tmp, 2)
    text = pmc.review_text(pack_dir, workdir).read_text()
    assert pm.HOWTO_MARK in text, text
    blocks = pm.parse_review(text)
    assert all(not b["skip_numbers"] and not b["skip_animals"] and not b["answered"]
               for b in blocks), blocks
    rc, said = pmc.confirm(pack_dir, workdir, go=False)
    assert rc == 0 and "0 change(s) would be written, 0 refused" in said, said


CASES = [
    ("HIL-4: the examples in the steps are never an answer (GUARD)",
     case_the_examples_in_the_steps_are_never_an_answer),
    ("HIL-4: the two steps say the same in text and on the web (REPRO)",
     case_the_two_steps_say_the_same_in_text_and_on_the_web),
    ("HIL-5: the recheck row shows a filled-in example (REPRO)",
     case_the_recheck_row_shows_a_filled_in_example),
    ("HIL-5: the example typed as shown takes the photo out (GUARD)",
     case_the_example_typed_as_shown_takes_the_photo_out),
    ("HIL-7: the end page shows the crop the memory holds (REPRO)",
     case_the_end_page_shows_the_crop_the_memory_holds),
    ("HIL-7: a shared remembered frame shows each crop (REPRO)",
     case_a_shared_remembered_frame_shows_each_crop),
    ("Q3: a remembered frame with no index says it is whole (REPRO)",
     case_a_remembered_frame_with_no_index_says_it_is_whole),
    ("Q3: an earlier dump's look shows its own crop (REPRO)",
     case_an_earlier_dumps_look_shows_its_own_crop),
    ("Q3: an earlier dump without its index says whole (GUARD)",
     case_an_earlier_dump_without_its_index_says_whole),
    ("Q8-a: an away sighting is asked, not filed (REPRO)",
     case_an_away_sighting_is_asked_not_filed),
    ("Q8-a: a sighting with no GPS is asked (REPRO)", case_a_sighting_with_no_gps_is_asked),
    ("Q8-a: a home sighting is still recognised (GUARD)",
     case_a_home_sighting_is_still_recognised),
    ("Q8-a: a travel-to home counts as home (GUARD)", case_a_travel_to_home_counts_as_home),
    ("Q8-a: the run's own home range is used (GUARD)", case_the_runs_own_home_range_is_used),
    ("Q8-a: the sweep leaves an asked draft open (REPRO)",
     case_the_sweep_leaves_an_asked_draft_open),
    ("Q8-b: not takes one photo out and keeps the name (REPRO)",
     case_not_takes_one_photo_out_and_keeps_the_name),
    ("Q8-b: not on an example photo drops the example (REPRO)",
     case_not_on_an_example_photo_drops_the_example),
    ("Q8-b: a taken-out photo does not come back (REPRO)",
     case_a_taken_out_photo_does_not_come_back),
    ("Q8-b: typos are refused, never a name (REPRO)", case_typos_are_refused_never_a_name),
    ("Q8-b: the forms of not parse alike (GUARD)", case_the_forms_of_not_parse_alike),
    ("Q8-b: the dry run writes nothing (GUARD)", case_the_dry_run_writes_nothing),
    ("Q8-b: only the owner's pick lifts not (GUARD)", case_only_the_owners_pick_lifts_not),
    ("Q8-c: the agent marks a crop not an animal (REPRO)",
     case_the_agent_marks_a_crop_not_an_animal),
    ("Q8-c: marking the first animal re-picks the primary (REPRO)",
     case_marking_the_first_animal_repicks_the_primary),
    ("Q8-c: a stale mark is not applied (GUARD)", case_a_stale_mark_is_not_applied),
    ("Q8-c: skip one crop is not two frames (REPRO)", case_skip_one_crop_is_not_two_frames),
    ("Q8-c: the owner marks a crop on the page (REPRO)",
     case_the_owner_marks_a_crop_on_the_page),
    ("Q8-c: a crop skip needs not-a-subject (GUARD)", case_a_crop_skip_needs_not_a_subject),
    ("Q8-c: a labelled crop still parses on the HTML page (GUARD)",
     case_a_labelled_crop_still_parses_on_the_html_page),
    ("Q8-c: a crop mark does not set the photo's basis (REPRO)",
     case_a_crop_mark_does_not_set_the_photos_basis),
    ("Q8-c: marks are read on the collection route (GUARD)",
     case_marks_are_read_on_the_collection_route),
    ("Q8-c: marks are read on the env route (GUARD)", case_marks_are_read_on_the_env_route),
    ("Card 9: agent marks are read on the --profile route (REPRO)",
     case_marks_are_read_on_the_profile_route),
    ("Card 9: a reader given no pack still says so (GUARD)",
     case_a_reader_given_no_pack_still_says_so),
    ("Card 9: owner page marks on the --profile route (REPRO)",
     case_owner_page_marks_on_the_profile_route),
    ("Card 9: owner page marks on the $PHOTO_PROFILE route (GUARD)",
     case_owner_page_marks_on_the_env_route),
    ("Card 9: owner page marks on the collection.json route (GUARD)",
     case_owner_page_marks_on_the_collection_route),
    ("Q8-c: a shared-frame page, end to end (REPRO)", case_a_shared_frame_page_end_to_end),
]


def main():
    passed = 0
    for name, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="pet_memory_case_"))
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                fn(tmp)
            print(f"  ok    {name}")
            passed += 1
        except Exception as e:                            # noqa: BLE001
            print(f"  FAIL  {name}: {type(e).__name__}: {str(e)[:500]}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{passed}/{len(CASES)} pet_memory cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
