#!/usr/bin/env python3
"""G7 cases — the agent names pets after the pages (`photo_index.py identify`,
D-I11).

Recognition PROPOSES a confirmed pet's name on a viewed photo; the agent views
the photo and agrees before any name is applied. An agent verdict trains
nothing and moves no record (L3), and a name it applies rests on a view record
that `check` verifies.

⛔ THE MOST IMPORTANT CASE IS THE STRANGER. Measured on a real dump
(20260913): after the owner's pages, recognition accepted street cats as a
confirmed pet in identity space, inside the pet's own score band — and an
earlier pack offered one at score 1.0. So the stranger case holds both: four
strangers at a synthetic 1.0 and one inside the band, every one refused by the
agent, and not one name anywhere.

  python3 tests/identify_cases.py [-v]

Exit 0 = pass. Synthetic dumps and packs in a temp dir: invented names, invented
coordinates, invented vectors.
"""

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import index_finish_cases as fin  # noqa: E402
import photo_embed  # noqa: E402
import photo_evidence  # noqa: E402
import photo_identity  # noqa: E402
import photo_index  # noqa: E402
import photo_index_cases as ix  # noqa: E402
import photo_platform  # noqa: E402
import photo_profile  # noqa: E402
import photo_see  # noqa: E402
import photo_subjects  # noqa: E402

DIM = 6
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
CLIP_ID = {"model_id": "ViT-B-32", "pretrained_tag": "test-tag",
           "preprocess_fingerprint": "sha256:test", "embed_dim": DIM}
LOTUS, REX, JUNIPER = "subj-0001", "subj-0002", "subj-0003"

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def e(i):
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def mix(*parts):
    v = sum(w * e(i) for i, w in parts)
    return (v / np.linalg.norm(v)).astype(np.float32)


# A frame: (name, day, identity boxes or None, viewed, named subject or None).
# Boxes are identity-space vectors; a frame with None has no identity row and
# is scored in CLIP from `clip`.
PET = ("PET_3.jpg", 3, [e(0)], True, None)
NAMED = ("IMG_0101.jpg", 1, [e(0)], True, LOTUS)
STRANGERS = [(f"CAT_{k}.jpg", 2, [e(0)], True, None) for k in range(1, 5)] + [
    ("CAT_5.jpg", 2, [mix((0, 0.6), (2, 0.8))], True, None)]


def id_dump(tmp, frames, route="collection", clip=None):
    """-> (work dir, pack dir, extra argv). `clip` maps a frame name to its CLIP
    vector (default: one no subject matches)."""
    root = Path(tmp)
    base = root.resolve() / "raw" / "dump-a"
    base.mkdir(parents=True)
    rows = []
    for k, (name, day, _boxes, _viewed, _named) in enumerate(frames):
        note = name.encode()
        (base / name).write_bytes(JPEG + b"\xff\xfe" + (len(note) + 2).to_bytes(2, "big")
                                  + note + b"\xff\xd9")
        rows.append(ix.row(name, when=f"2024:11:0{day} 10:{k:02d}:00",
                           SourceFile=str(base / name)))
    days = sorted({f[1] for f in frames})
    batches = [{"batch": d, "from": f"2024-11-0{d}", "to": f"2024-11-0{d}",
                "place": "Ford"} for d in days]
    wd = ix.make_dump(root, rows=rows, batches=batches, bind=route == "collection")
    pack = ix.make_pack(root)

    reg = pack / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text())
    data["subjects"] = [
        {**ix.subject(LOTUS, "Lotus"), "exemplars": [{"vec_ref": "sha256:ex-lotus"}]},
        ix.subject(REX, "Rex", "dog", photo_subjects.STATUS_DRAFT),
        {**ix.subject(JUNIPER, "Juniper"), "exemplars": [{"vec_ref": "sha256:ex-juniper"}]}]
    reg.write_text(json.dumps(data))
    for sid, i in ((LOTUS, 0), (JUNIPER, 1)):
        (pack / "photo-subjects" / "vectors").mkdir(exist_ok=True)
        np.save(pack / "photo-subjects" / "vectors" / f"{sid}.npy", e(i)[None, :])
        (pack / "photo-subjects" / "identity-vectors").mkdir(exist_ok=True)
        np.savez(pack / "photo-subjects" / "identity-vectors" / f"{sid}.npz",
                 **{f"sha256:ex-{'lotus' if i == 0 else 'juniper'}": e(i)})

    embed = wd / "embed"
    clip_rows, clip_vecs, id_rows, id_vecs = [], [], [], []
    for name, _day, boxes, _viewed, _named in frames:
        src = str(base / name)
        clip_rows.append({"SourceFile": src, "sha256": f"sha256:{name}", "kind": "image",
                          "status": "embedded", "size": 1, "mtime": 0, "error": ""})
        clip_vecs.append((clip or {}).get(name, e(5)))
        for d, vec in enumerate(boxes or []):
            id_rows.append({"SourceFile": src, "sha256": "", "status": photo_identity.STATUS_OK,
                            "det_index": d, "det_count": len(boxes), "kind": "cat",
                            "det_score": 0.9, "box": "0,0,10,10", "box_share": 0.5,
                            "error": ""})
            id_vecs.append(vec)
    photo_embed.save_index(embed, clip_rows, clip_vecs, dict(CLIP_ID, normalized=True))
    (embed / "paperwork-scores.json").write_text(json.dumps({**CLIP_ID, "scores": {}}))
    with open(embed / "identity.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=photo_identity.CSV_FIELDS)
        w.writeheader()
        w.writerows(id_rows)
    with open(embed / "identity.npy", "wb") as fh:
        np.save(fh, np.stack(id_vecs) if id_vecs else np.zeros((0, DIM), np.float32))
    (embed / "identity-meta.json").write_text(json.dumps(
        {**photo_identity.meta_identity(DIM), "created_at": "2029-01-01 00:00"}))

    for day in days:
        bdir = wd / "classify" / f"batch-{day:02d}"
        (bdir / "samples").mkdir(parents=True)
        selected, labels = [], []
        for k, (name, d, boxes, viewed, named) in enumerate(frames):
            if d != day:
                continue
            src = str(base / name)
            kinds = [{"subject_kind": "cat"} for _ in (boxes or [None])]
            subjects = [{"subject_id": named}] if named else kinds
            if viewed:
                (bdir / "samples" / name).write_bytes(JPEG)
                selected.append({"path": src, "sample": name,
                                 "time": f"2024-11-0{d} 10:{k:02d}"})
            labels.append({"path": src, "label": "a cat on the sofa",
                           "provenance": (photo_evidence.VIEWED if viewed
                                          else photo_evidence.CLIP_PROPAGATED),
                           "sample": name if viewed else None, "subjects": subjects,
                           "subject_provenance": (photo_evidence.VIEWED if viewed
                                                  else photo_evidence.CLIP_PROPAGATED)})
        (bdir / "see-report.json").write_text(json.dumps(
            {"batch": day, "selected": selected, "clusters": [], "provisional": []}))
        (bdir / "see-labels.json").write_text(json.dumps({"batch": day, "labels": labels}))

    profile = pack / photo_profile.PROFILE_NAME
    extra = []
    if route == "env":
        os.environ[photo_profile.ENV_VAR] = str(profile)
    elif route == "profile":
        extra = ["--profile", str(profile)]
    code, _out, err = ix.run("init", wd, *extra)
    if code:
        raise RuntimeError(err[-300:])
    return wd, pack, extra


def views(wd):
    return (wd / photo_index.VIEWS_NAME).read_text()


def rows(wd):
    return photo_index.parse_views(views(wd))[1]


def answer(wd, verdicts):
    """Write a verdict on each row: `verdicts` maps (frame name, subject id) or
    a frame name to a verdict; anything else stays blank."""
    out = []
    for line in views(wd).splitlines():
        m = photo_index.VIEW_ROW.match(line)
        if m:
            frame = Path(m.group(3)).name
            v = verdicts.get((frame, m.group(4)), verdicts.get(frame))
            if v:
                line = line[:line.rindex("verdict:")] + f"verdict: {v}"
        out.append(line)
    (wd / photo_index.VIEWS_NAME).write_text("\n".join(out) + "\n")


def go(wd, extra=(), *more):
    return ix.run("identify", wd, "--answers", wd / photo_index.VIEWS_NAME, "--go",
                  *extra, *more)


def labels(wd, day):
    return {Path(e_["path"]).name: e_ for e_ in json.loads(
        (wd / "classify" / f"batch-{day:02d}" / "see-labels.json").read_text())["labels"]}


def registry_state(pack):
    return ix.tree_state(pack / "photo-subjects")


def index_now(tmp):
    return ix.index_of(tmp)[0]


def folder_of_day(tmp, day):
    return next(fo for fo in index_now(tmp)["folders"]
                if fo["kind"] == "day" and fo.get("batches") == [day])


# ---------------------------------------------------------------------------
# the proposal (dry run)
# ---------------------------------------------------------------------------

def route_case(route):
    """REPRODUCTION of a new capability (nothing proposed on `91ca5e6`), through
    ONE pack route end to end (A42 / LL-PHO-132): the dry run offers the viewed
    pet photo in identity space and writes nothing else; the agreed answer
    written with `--go` names the photo, and render puts the name in `[who]`."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack, extra = id_dump(tmp, [NAMED, PET], route=route)
        before = (registry_state(pack), labels(wd, 3), index_now(tmp).get("identify"))
        code, out, err = ix.run("identify", wd, *extra)
        got = rows(wd) if (wd / photo_index.VIEWS_NAME).exists() else []
        after = (registry_state(pack), labels(wd, 3), index_now(tmp).get("identify"))
        answer(wd, {"PET_3.jpg": "agree"})
        gcode, gout, gerr = go(wd, extra)
        lab = labels(wd, 3)["PET_3.jpg"]
        rcode, _r, rerr = ix.run("render", wd, *extra)
        name = folder_of_day(tmp, 3)["rendered"]
        os.environ.pop(photo_profile.ENV_VAR, None)
    ok = (code == photo_index.EXIT_VIEWS_WANTED and len(got) == 1
          and got[0]["sample"].endswith("PET_3.jpg") and got[0]["subject_id"] == LOTUS
          and before == after and "identity" in out
          and gcode == 0 and (lab.get("identified") or [{}])[0].get("subject_id") == LOTUS
          and rcode == 0 and "Lotus" in name)
    return ok, (f"code={code} rows={got} out={out[-300:]!r} err={err[-300:]!r} "
                f"go={gcode} {gout[-200:]!r}{gerr[-200:]!r} label={lab} "
                f"render={rcode} {rerr[-200:]!r} name={name!r}")


@case
def route_collection_json_proposes_a_viewed_photo():
    return route_case("collection")


@case
def route_env_var_proposes_a_viewed_photo():
    return route_case("env")


@case
def route_explicit_profile_proposes_a_viewed_photo():
    return route_case("profile")


@case
def two_boxes_proposing_one_name_offer_it_once():
    """GUARD (L6). A duplicate box on one animal must not become the same name
    twice: offered once, on the higher-scoring box."""
    same = ("SAME_3.jpg", 3, [mix((0, 0.9), (2, 0.44)), e(0)], True, None)
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [same])
        code, _out, _err = ix.run("identify", wd)
        got, text = rows(wd), views(wd)
    return (code == photo_index.EXIT_VIEWS_WANTED and len(got) == 1
            and "animal 2 of 2" in text), f"{got}"


def thumbnail_stub(make=True):
    """A stand-in for `photo_embed.convert_to_thumbnail` (sips), so a crop can
    be cut from a synthetic frame: a plain 40 px JPEG, or no thumbnail."""
    from PIL import Image

    def thumb(src, dst_dir, stem, kind, filetype):
        if not make:
            return None, "decode_failed"
        out = Path(dst_dir) / f"{stem}.jpg"
        Image.new("RGB", (40, 40), (200, 90, 40)).save(out, "JPEG")
        return out, None
    return thumb


def views_with_thumbnails(frames, make=True):
    saved = photo_embed.convert_to_thumbnail
    photo_embed.convert_to_thumbnail = thumbnail_stub(make)
    try:
        with tempfile.TemporaryDirectory() as tmp, ix.no_env():
            wd, _pack, _ = id_dump(tmp, frames)
            code, _out, _err = ix.run("identify", wd)
            text = views(wd)
            got = rows(wd)
            crop = re.search(r"crop: `([^`]+)`", text)
            exists = bool(crop) and (wd / crop.group(1)).is_file()
    finally:
        photo_embed.convert_to_thumbnail = saved
    return code, text, got, crop, exists


@case
def a_two_animal_row_links_the_crop_of_its_own_animal():
    """REPRODUCTION (FIX6, U6-27). ⛔ FAILS on 0865b82: a row said "box 1 of 2"
    and linked only the whole sample, so on a two-cat photo the agent could not
    see which animal it was asked to agree to (D-I11's guard). The row now
    links a crop of ITS detection, numbered from one."""
    same = ("SAME_3.jpg", 3, [mix((0, 0.9), (2, 0.44)), e(0)], True, None)
    code, text, got, crop, exists = views_with_thumbnails([same])
    return (code == photo_index.EXIT_VIEWS_WANTED and len(got) == 1
            and "animal 2 of 2" in text and crop is not None
            and crop.group(1).endswith("_d1.jpg") and exists), text[-400:]


@case
def a_row_with_no_crop_is_still_written_and_read():
    """GUARD (FIX6). A thumbnail that cannot be made costs the crop, never the
    row: it is written without `crop:` and still parses for its verdict."""
    code, text, got, crop, _exists = views_with_thumbnails([PET], make=False)
    return (code == photo_index.EXIT_VIEWS_WANTED and len(got) == 1
            and crop is None and "animal 1 of 1" in text), text[-400:]


@case
def a_row_with_no_crop_is_said_not_silent():
    """REPRODUCTION (UAT02-02 F-r). ⛔ FAILS on c5b6f99: 29 of 31 rows came
    with no `crop:` and nothing said so — finish had run identify under a
    python with no pillow-heif / ffmpeg. The run now counts them and names
    the interpreter."""
    saved = photo_embed.convert_to_thumbnail
    photo_embed.convert_to_thumbnail = thumbnail_stub(False)
    try:
        with tempfile.TemporaryDirectory() as tmp, ix.no_env():
            wd, _pack, _ = id_dump(tmp, [PET])
            code, out, err = ix.run("identify", wd)
    finally:
        photo_embed.convert_to_thumbnail = saved
    said = out + err
    return (code == photo_index.EXIT_VIEWS_WANTED
            and "1 of 1 row(s) have no crop" in said
            and "the repo .venv" in said), said[-400:]


SKIPPED_ID = "subj-0050"


def owner_skipped(tmp, pack, name, page="P-B09"):
    """The pack as a page `skip:` leaves it: a REJECTED draft (basis
    not-mine) whose look is this photo — keyed by file, no det_index (C10)."""
    reg = pack / "photo-subjects" / "subjects.json"
    data = json.loads(reg.read_text())
    path = str(Path(tmp).resolve() / "raw" / "dump-a" / name)
    data["subjects"].append({
        **ix.subject(SKIPPED_ID, None, "cat", photo_subjects.STATUS_REJECTED),
        "rejected": {"at": "2024-11-30", "by": "owner", "src": f"{page}.md Q1",
                     "basis": "not-mine"},
        "evidence": [{"batch": 3, "looks": [{"path": path, "vec_ref": f"sha256:{name}"}]}]})
    reg.write_text(json.dumps(data))


@case
def a_one_animal_photo_the_owner_skipped_is_not_offered():
    """REPRODUCTION (UAT02-02 F-q, Lead ruling 20260924). ⛔ FAILS on c5b6f99:
    identify offered Lotus on the very sighting the owner skipped as not
    theirs. A one-animal photo IS that animal: listed, with the reason, never
    offered."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack, _ = id_dump(tmp, [PET])
        owner_skipped(tmp, pack, "PET_3.jpg")
        code, out, err = ix.run("identify", wd)
        got = rows(wd) if (wd / photo_index.VIEWS_NAME).is_file() else []
        text = views(wd) if got else ""
    return (not got and "the owner skipped this animal on P-B09" in out
            and code == 0), f"code={code} rows={got} out={out[-300:]!r} err={err[-200:]!r}"


@case
def a_skip_on_a_two_animal_photo_suppresses_neither_animal():
    """GUARD (D-24 / G6-6: one name per animal). The skip is stored per photo,
    so it cannot say WHICH animal was meant: both animals are still offered,
    each row saying the photo was skipped and that the skip does not say
    which."""
    two = ("TWO_3.jpg", 3, [e(0), e(1)], True, None)
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack, _ = id_dump(tmp, [two])
        owner_skipped(tmp, pack, "TWO_3.jpg")
        code, _out, err = ix.run("identify", wd)
        got, text = rows(wd), views(wd)
    return (code == photo_index.EXIT_VIEWS_WANTED
            and sorted(r["subject_id"] for r in got) == sorted([LOTUS, JUNIPER])
            and text.count("the skip does not say which") == 2), \
        f"code={code} rows={got} err={err[-200:]!r}"


@case
def a_revived_skip_is_offered_again():
    """GUARD — `--revive` takes the rejection back, so the row comes back."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack, _ = id_dump(tmp, [PET])
        owner_skipped(tmp, pack, "PET_3.jpg")
        registry = photo_subjects.load(pack=photo_profile.Pack(directory=pack))
        registry.revive(SKIPPED_ID, by="owner", reason="it is ours after all")
        registry.save()
        code, _out, err = ix.run("identify", wd)
        got = rows(wd)
    return (code == photo_index.EXIT_VIEWS_WANTED
            and [r["subject_id"] for r in got] == [LOTUS]), f"code={code} rows={got} err={err[-200:]!r}"


@case
def clip_and_a_question_are_listed_never_offered():
    """GUARD (item 2, item 6). A CLIP accept and an identity question are listed
    with their space and never offered for a view."""
    clip_only = ("CLIP_3.jpg", 3, None, True, None)
    question = ("Q_3.jpg", 3, [mix((0, 1.0), (1, 1.0))], True, None)
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [clip_only, question], clip={"CLIP_3.jpg": e(0)})
        code, out, _err = ix.run("identify", wd)
        listed = [line for line in out.splitlines() if "not offered" in line]
    return (code == 0 and not (wd / photo_index.VIEWS_NAME).exists()
            and any("CLIP_3" in s and "clip" in s for s in listed)
            and any("Q_3" in s and "question" in s for s in listed)), out[-500:]


# ---------------------------------------------------------------------------
# ⭐ the stranger
# ---------------------------------------------------------------------------

@case
def five_strangers_proposed_as_a_pet_stay_unnamed():
    """⭐ REPRODUCTION of the measured shape. Five strangers: four at a synthetic
    identity score 1.0 against the confirmed pet, one inside the band (0.6).
    The agent says `no` or `unsure` on every one -> no name on any label, the
    folder keeps its class word, no exemplar, no record moved, and none of them
    is proposed again."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack, _ = id_dump(tmp, [NAMED] + STRANGERS)
        registry = registry_state(pack)
        code, _out, _err = ix.run("identify", wd)
        proposed = rows(wd)
        answer(wd, {"CAT_1.jpg": "no", "CAT_2.jpg": "no", "CAT_3.jpg": "unsure",
                    "CAT_4.jpg": "no", "CAT_5.jpg": "unsure"})
        gcode, gout, gerr = go(wd)
        named = [n for n, lab in labels(wd, 2).items()
                 if lab.get("identified") or lab.get("subject_ids")
                 or any(s.get("subject_id") for s in lab.get("subjects") or [])]
        ix.run("render", wd)
        name = folder_of_day(tmp, 2)["rendered"]
        records = index_now(tmp).get("identify") or []
        again, again_out, _ = ix.run("identify", wd)
        unchanged = registry == registry_state(pack)
    ok = (code == photo_index.EXIT_VIEWS_WANTED and len(proposed) == 5 and gcode == 0
          and not named and "Lotus" not in name and len(records) == 5
          and {r["verdict"] for r in records} == {"no", "unsure"}
          and unchanged and again == 0)
    return ok, (f"proposed={len(proposed)} go={gcode} named={named} name={name!r} "
                f"records={len(records)} again={again} registry_same={unchanged} "
                f"{gout[-200:]!r} {gerr[-200:]!r} {again_out[-200:]!r}")


# ---------------------------------------------------------------------------
# ⭐ end to end
# ---------------------------------------------------------------------------

@case
def an_agreed_photo_names_the_folder_end_to_end():
    """⭐ REPRODUCTION (D-I11) — a batch after the pages gains `[who]` with no
    owner page: proposed → the agent agrees on a viewed photo → render gives the
    name → check finds the view record → freeze → finish copies into the named
    folder. No exemplar is added."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack, _ = id_dump(tmp, [NAMED, PET])
        registry = registry_state(pack)
        ix.run("identify", wd)
        answer(wd, {"PET_3.jpg": "agree"})
        gcode, gout, gerr = go(wd)
        lab = labels(wd, 3)["PET_3.jpg"]
        rcode, _r, rerr = ix.run("render", wd)
        name = folder_of_day(tmp, 3)["rendered"]
        who = next(f["who"] for f in index_now(tmp)["files"]
                   if f["source"].endswith("PET_3.jpg"))
        ccode, cout, cerr = ix.run("check", wd)
        fcode, _f, ferr = ix.run("freeze", wd)
        r = fin.finish(wd)
        got = fin.copied(tmp)
        unchanged = registry == registry_state(pack)
    ok = (gcode == 0 and lab.get("identified", [{}])[0].get("subject_id") == LOTUS
          and lab["provenance"] == photo_evidence.VIEWED and rcode == 0
          and "Lotus" in name and who and who[0].get("by") == "agent-confirmed"
          and who[0].get("view") == "I-0001" and ccode == 0 and fcode == 0
          and r.returncode == 0 and any("Lotus" in p and p.endswith("PET_3.jpg")
                                        for p in got)
          and unchanged)
    return ok, (f"go={gcode} {gout[-200:]!r}{gerr[-200:]!r} label={lab} render={rcode} "
                f"{rerr[-200:]!r} name={name!r} who={who} check={ccode} {cout[-300:]!r}"
                f"{cerr[-200:]!r} freeze={fcode} {ferr[-200:]!r} finish={r.returncode} "
                f"got={got} {r.stderr[-300:]!r} registry_same={unchanged}")


@case
def two_animals_get_two_names_and_no_exemplar():
    """REPRODUCTION (L6). One photo, two boxes, two confirmed pets: two
    proposals, both agreed -> both names on the photo at frame level and in the
    folder name; no exemplar in any space."""
    two = ("TWO_3.jpg", 3, [e(0), e(1)], True, None)
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack, _ = id_dump(tmp, [two])
        registry = registry_state(pack)
        ix.run("identify", wd)
        proposed = rows(wd)
        answer(wd, {"TWO_3.jpg": "agree"})
        gcode, gout, _ = go(wd)
        lab = labels(wd, 3)["TWO_3.jpg"]
        ix.run("render", wd)
        name = folder_of_day(tmp, 3)["rendered"]
        unchanged = registry == registry_state(pack)
    ok = (len(proposed) == 2 and gcode == 0
          and sorted(lab.get("subject_ids") or []) == [LOTUS, JUNIPER]
          and "Lotus" in name and "Juniper" in name and unchanged)
    return ok, f"proposed={proposed} go={gcode} {gout[-200:]!r} label={lab} name={name!r}"


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------

@case
def an_agreed_photo_whose_thumbnail_is_gone_is_refused():
    """GUARD. A name rests on a viewed photo; a thumbnail gone between the views
    and the answer means nothing is there to have looked at."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [PET])
        ix.run("identify", wd)
        answer(wd, {"PET_3.jpg": "agree"})
        (wd / "classify" / "batch-03" / "samples" / "PET_3.jpg").unlink()
        before = labels(wd, 3)
        gcode, gout, _ = go(wd)
        after = labels(wd, 3)
        records = index_now(tmp).get("identify") or []
    return (gcode == 1 and before == after and not records
            and "not proposed any more" in gout), f"go={gcode} {gout[-300:]!r}"


@case
def a_name_recognition_never_proposed_is_refused():
    """GUARD. The agent may only agree to what recognition proposed: a subject
    typed onto a row by hand writes nothing."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [PET])
        ix.run("identify", wd)
        (wd / photo_index.VIEWS_NAME).write_text(views(wd).replace(LOTUS, JUNIPER))
        answer(wd, {"PET_3.jpg": "agree"})
        before = labels(wd, 3)
        gcode, gout, _ = go(wd)
        after = labels(wd, 3)
    return (gcode == 1 and before == after and "not proposed any more" in gout), \
        f"go={gcode} {gout[-300:]!r}"


@case
def the_same_name_twice_on_one_photo_is_refused():
    """GUARD (L6). The same row copied onto the same photo is one animal named
    twice."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [PET])
        ix.run("identify", wd)
        text = views(wd)
        row = next(line for line in text.splitlines() if line.startswith("- `I-0001`"))
        (wd / photo_index.VIEWS_NAME).write_text(
            text.replace(row, row + "\n" + row.replace("I-0001", "I-0002")))
        answer(wd, {"PET_3.jpg": "agree"})
        gcode, gout, _ = go(wd)
        records = index_now(tmp).get("identify") or []
    return (gcode == 1 and len(records) == 1 and "named once" in gout), \
        f"go={gcode} records={len(records)} {gout[-300:]!r}"


@case
def a_stale_pin_is_refused():
    """GUARD. The pack moved between the views and the answer (a confirm, a
    rename): the proposals were made against another pack — nothing written."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack, _ = id_dump(tmp, [PET])
        ix.run("identify", wd)
        answer(wd, {"PET_3.jpg": "agree"})
        reg = pack / "photo-subjects" / "subjects.json"
        data = json.loads(reg.read_text())
        data["defaults"]["accept"] = 0.83
        reg.write_text(json.dumps(data))
        before = labels(wd, 3)
        gcode, _gout, gerr = go(wd)
        after = labels(wd, 3)
    return (gcode == 1 and before == after and "Write the views again" in gerr), \
        f"go={gcode} {gerr[-300:]!r}"


@case
def a_printed_identify_line_runs_from_any_folder():
    """REPRODUCTION (H-I: a printed line names a bare script). ⛔ FAILS on
    beb57e9: the lines `identify` prints began with a bare `photo_index.py`,
    which runs from no folder as printed. Each now names the python and the
    script by full path: the views file's apply line, and the stale-pin
    refusal's line, which makes crops and so names the pages' python (HIL-10).
    The refusal's line is RUN, as printed, from a folder that is not the
    workspace. ⚠️ HIL01 obs-15's own trigger was a bare DUMP NAME copied from
    the photo-run SKILL and typed inside the work dir; that is fixed in the
    SKILL text only, with no case here."""
    import shlex
    import subprocess
    import photo_run
    script = str(ROOT / "scripts" / "photo_index.py")
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, pack, _ = id_dump(tmp, [PET])
        ix.run("identify", wd)
        head = views(wd).split("## Proposed")[0]
        apply_ = next((ln for ln in head.splitlines() if " --answers " in ln), "")
        answer(wd, {"PET_3.jpg": "agree"})
        reg = pack / "photo-subjects" / "subjects.json"
        data = json.loads(reg.read_text())
        data["defaults"]["accept"] = 0.83
        reg.write_text(json.dumps(data))
        _gcode, _gout, gerr = go(wd)
        again = next((ln for ln in gerr.splitlines()
                      if ln.rstrip().endswith(f'identify "{wd.resolve()}"')), "")
        argv = shlex.split(again)
        elsewhere = Path(tmp) / "elsewhere"
        elsewhere.mkdir()
        ran = (subprocess.run(argv, cwd=elsewhere, capture_output=True, text=True)
               if len(argv) > 1 else None)
    a_argv = shlex.split(apply_)
    ok = (len(a_argv) > 1 and a_argv[1] == script
          and len(argv) > 1 and argv[0] == str(photo_run.page_python())
          and argv[1] == script and ran is not None
          and ran.returncode in (0, photo_index.EXIT_VIEWS_WANTED)
          and "no collection.json" not in ran.stderr + ran.stdout)
    return ok, (f"apply={apply_!r} again={again!r} "
                f"ran={None if ran is None else (ran.returncode, ran.stderr[-200:])}")


@case
def a_second_go_changes_nothing():
    """GUARD (idempotent). The same answers applied twice write nothing the
    second time, and the photo is not proposed again."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [PET])
        ix.run("identify", wd)
        answer(wd, {"PET_3.jpg": "agree"})
        go(wd)
        first = (labels(wd, 3), len(index_now(tmp)["identify"]))
        gcode, gout, _ = go(wd)
        second = (labels(wd, 3), len(index_now(tmp)["identify"]))
        again, _o, _e = ix.run("identify", wd)
    return (gcode == 0 and first == second and again == 0), \
        f"go={gcode} {gout[-200:]!r} same={first == second} again={again}"


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

@case
def check_fails_a_name_the_agent_applied_with_no_view_record():
    """GUARD (item 4). A `by: agent-confirmed` name whose view record is gone —
    and a hand-added `identified` key that never had one — fail check."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [NAMED, PET])
        ix.run("identify", wd)
        answer(wd, {"PET_3.jpg": "agree"})
        go(wd)
        ix.run("render", wd)
        passed, _o, _e = ix.run("check", wd)
        target = ix.index_of(tmp)[2]
        index = json.loads((target / "index.json").read_text())
        index["identify"] = []
        (target / "index.json").write_text(json.dumps(index))
        gone, gone_out, _ = ix.run("check", wd)

        path = wd / "classify" / "batch-01" / "see-labels.json"
        doc = json.loads(path.read_text())
        for lab in doc["labels"]:
            if lab["path"].endswith("IMG_0101.jpg"):
                lab["identified"] = [{"subject_id": LOTUS, "view": "I-0099"}]
        path.write_text(json.dumps(doc))
        ix.run("render", wd)
        forged, forged_out, _ = ix.run("check", wd)
    return (passed == 0 and gone == 1 and "no view record agrees" in gone_out
            and forged == 1 and "I-0099" in forged_out), \
        f"passed={passed} gone={gone} forged={forged} {forged_out[-300:]!r}"


# ---------------------------------------------------------------------------
# the see stage keeps recorded names (the Lead's A45 addition)
# ---------------------------------------------------------------------------

def reapply(tmp, prior, provenance=photo_evidence.VIEWED):
    samples = Path(tmp) / "samples"
    samples.mkdir(parents=True)
    (samples / "a.jpg").write_bytes(JPEG)
    report = {"selected": [{"path": "/raw/a.jpg", "sample": "a.jpg"}],
              "clusters": [{"cluster": 0, "members": ["/raw/a.jpg"]}],
              "provisional": [{"path": "/raw/a.jpg", "label": None, "provenance": None}]}
    was = {"path": "/raw/a.jpg", "label": "a cat", "provenance": provenance,
           "sample": "a.jpg", **prior}
    entries = photo_see.apply_decisions(
        report, {"/raw/a.jpg": {"label": "a cat", "subject_kind": "cat"}}, samples,
        existing=[was])
    return entries[0]


@case
def a_see_re_apply_keeps_the_names_already_recorded():
    """REPRODUCTION. ⛔ FAILS on 91ca5e6 (measured on a real dump: re-applying a
    batch after its page dropped every recorded name). The owner's picks
    (`subject_id`, `subject_ids`) and the agent's `identified` survive a fresh
    look at the frame."""
    with tempfile.TemporaryDirectory() as tmp:
        one = reapply(Path(tmp) / "1",
                      {"subjects": [{"subject_kind": "cat", "subject_id": LOTUS}],
                       "subject_provenance": photo_evidence.VIEWED})
        two = reapply(Path(tmp) / "2",
                      {"subjects": [{"subject_kind": "cat"}, {"subject_kind": "cat"}],
                       "subject_ids": [LOTUS, JUNIPER],
                       "identified": [{"subject_id": JUNIPER, "view": "I-0004"}]})
    ok = ([s.get("subject_id") for s in photo_evidence.subject_list(one)] == [LOTUS]
          and two.get("subject_ids") == [LOTUS, JUNIPER]
          and two.get("identified") == [{"subject_id": JUNIPER, "view": "I-0004"}]
          and not one.get("preserved") and not two.get("preserved"))
    return ok, f"one={one} two={two}"


@case
def the_views_and_the_index_carry_no_coordinate():
    """GUARD (Rule 3). Nothing identify writes holds a place's coordinate."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [PET])
        ix.run("identify", wd)
        answer(wd, {"PET_3.jpg": "agree"})
        go(wd)
        text = views(wd) + json.dumps(index_now(tmp))
    needles = [str(ix.HOME[0]), str(ix.HOME[1]), str(ix.FAR[0]), str(ix.FAR[1])]
    return not any(n in text for n in needles), [n for n in needles if n in text]


# ---------------------------------------------------------------------------
# G7g — blank rows
# ---------------------------------------------------------------------------

def blanks_answered(tmp):
    """identify → agree on the pet, the two strangers left blank → --go."""
    wd, pack, _ = id_dump(tmp, [NAMED, PET] + STRANGERS[:2])
    ix.run("identify", wd)
    answer(wd, {"PET_3.jpg": "agree"})
    gcode, gout, gerr = go(wd)
    return wd, pack, (gcode, gout, gerr)


@case
def blank_rows_do_not_stop_finish_and_are_counted():
    """REPRODUCTION (G7g). ⛔ FAILS on 7a239e8: a blank row was proposed again,
    so `finish` stopped (exit 3) on every run until every row had a verdict.
    Now finish goes on to the copy, says how many photos were left without a
    verdict, and a blank is recorded nowhere (it is not an `unsure`)."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, (gcode, gout, gerr) = blanks_answered(tmp)
        ix.run("render", wd)
        ccode, _c, cerr = ix.run("check", wd)
        fcode, _f, ferr = ix.run("freeze", wd)
        r = fin.finish(wd, "--go")
        got = fin.copied(tmp)
        records = index_now(tmp).get("identify") or []
    ok = (gcode == 0 and ccode == 0 and fcode == 0 and r.returncode == 0
          and "2 photo(s) were left without a verdict" in r.stdout
          and any("Lotus" in p and p.endswith("PET_3.jpg") for p in got)
          and [x["verdict"] for x in records] == ["agree"])
    return ok, (f"go={gcode} {gout[-200:]!r}{gerr[-200:]!r} check={ccode} {cerr[-200:]!r} "
                f"freeze={fcode} {ferr[-200:]!r} finish={r.returncode} "
                f"out={r.stdout[-600:]!r} err={r.stderr[-300:]!r} got={got} "
                f"records={records}")


@case
def an_explicit_identify_run_proposes_the_blank_rows_again():
    """GUARD (G7g). The conductor's run does not ask a blank again; a hand run
    of `identify` does, and the conductor's run still counts them."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _g = blanks_answered(tmp)
        ncode, nout, _n = ix.run("identify", wd, "--new-only")
        again, _a, _e = ix.run("identify", wd)
        shown = sorted(Path(r["sample"]).name for r in rows(wd))
    ok = (ncode == 0 and "2 photo(s) were left without a verdict" in nout
          and again == photo_index.EXIT_VIEWS_WANTED
          and shown == ["CAT_1.jpg", "CAT_2.jpg"])
    return ok, f"new-only={ncode} {nout[-300:]!r} again={again} shown={shown}"


@case
def verdicts_written_but_not_applied_are_not_overwritten():
    """GUARD (G7g). A views file with verdicts never applied is not rewritten
    and not counted as blank: the conductor's run stops and says to apply them,
    so an agreed name is never lost by re-running finish."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [NAMED, PET])
        ix.run("identify", wd)
        answer(wd, {"PET_3.jpg": "agree"})
        before = views(wd)
        ncode, nout, _n = ix.run("identify", wd, "--new-only")
        after = views(wd)
    ok = (ncode == photo_index.EXIT_VIEWS_WANTED and before == after
          and "not applied yet" in nout and "left without a verdict" not in nout)
    return ok, f"new-only={ncode} {nout[-300:]!r} same={before == after}"


# ---------------------------------------------------------------------------
# G7h — a name recorded on a viewed frame rests on that view
# ---------------------------------------------------------------------------

def propagated_subject(wd, day):
    """A cluster conflict: the frame is VIEWED, its subject `clip-propagated:`."""
    path = wd / "classify" / f"batch-{day:02d}" / "see-labels.json"
    doc = json.loads(path.read_text())
    for lab in doc["labels"]:
        lab["subject_provenance"] = photo_evidence.CLIP_PROPAGATED
    path.write_text(json.dumps(doc))


@case
def an_agreed_name_on_a_propagated_subject_names_the_folder():
    """REPRODUCTION (G7h). ⛔ FAILS on 129e7de: measured on mix1 (F019) — the
    agreed name was written, render's N-4 gate read `clip-propagated:` and the
    folder got no `[who]`, and check passed without a word. Now the writer sets
    the view's provenance and the name is in the folder."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [NAMED, PET])
        propagated_subject(wd, 3)
        ix.run("identify", wd)
        answer(wd, {"PET_3.jpg": "agree"})
        gcode, gout, gerr = go(wd)
        lab = labels(wd, 3)["PET_3.jpg"]
        ix.run("render", wd)
        name = folder_of_day(tmp, 3)["rendered"]
        ccode, cout, _c = ix.run("check", wd)
    ok = (gcode == 0 and "Lotus" in name and ccode == 0
          and lab["provenance"] == photo_evidence.VIEWED
          and lab["subject_provenance"] == photo_evidence.VIEWED
          and not lab.get("preserved"))
    return ok, (f"go={gcode} {gout[-200:]!r}{gerr[-200:]!r} name={name!r} "
                f"check={ccode} {cout[-300:]!r} label={lab}")


@case
def an_owner_pick_on_a_propagated_subject_names_the_folder():
    """REPRODUCTION (G7h item 3). ⛔ FAILS on 129e7de: the owner-page writer had
    the same hole, on a one-animal frame and on a shared frame — the picked name
    was recorded and never reached `[who]`."""
    got = {}
    for frame, picks in (("PET_3.jpg", [LOTUS]), ("TWO_3.jpg", [LOTUS, JUNIPER])):
        with tempfile.TemporaryDirectory() as tmp, ix.no_env():
            boxes = [e(0)] if len(picks) == 1 else [e(0), e(1)]
            wd, _pack, _ = id_dump(tmp, [NAMED, (frame, 3, boxes, True, None)])
            propagated_subject(wd, 3)
            photo_see.record_confirmed_subject_ids(
                wd, [(f"classify/batch-03/samples/{frame}", s) for s in picks])
            ix.run("render", wd)
            got[frame] = (folder_of_day(tmp, 3)["rendered"],
                          labels(wd, 3)[frame]["subject_provenance"])
    ok = all("Lotus" in name and prov == photo_evidence.VIEWED
             for name, prov in got.values())
    return ok, f"{got}"


@case
def a_re_apply_carrying_a_name_keeps_it_on_the_view():
    """REPRODUCTION (G7h). ⛔ FAILS on 129e7de: a re-apply whose fresh cluster
    set the subject `clip-propagated:` carried the name and kept that
    provenance, so the name dropped out of `[who]` again."""
    entry = photo_see.carry_recorded_names(
        {"subjects": [{"subject_kind": "cat", "subject_id": LOTUS}],
         "identified": [{"subject_id": LOTUS, "view": "I-0002"}]},
        {"path": "/raw/a.jpg", "provenance": photo_evidence.VIEWED,
         "subjects": [{"subject_kind": "cat"}],
         "subject_provenance": photo_evidence.CLIP_PROPAGATED})
    return (entry["subject_provenance"] == photo_evidence.VIEWED
            and entry["subjects"][0].get("subject_id") == LOTUS), f"{entry}"


@case
def check_fails_an_agent_name_whose_provenance_is_not_a_view():
    """GUARD (G7h item 2). An agent-confirmed who at `clip-propagated:` fails
    check by name, never lost in silence."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [NAMED, PET])
        ix.run("identify", wd)
        answer(wd, {"PET_3.jpg": "agree"})
        go(wd)
        ix.run("render", wd)
        passed, _o, _e = ix.run("check", wd)
        propagated_subject(wd, 3)
        ix.run("render", wd)
        bad, bad_out, bad_err = ix.run("check", wd)
    ok = (passed == 0 and bad == 1 and "not a view" in bad_out + bad_err
          and "I-0001" in bad_out + bad_err)
    return ok, f"passed={passed} bad={bad} {bad_out[-300:]!r}{bad_err[-200:]!r}"


# ---------------------------------------------------------------------------
# FIX9 F10 — the route printed at the identify stop, frozen or not
# ---------------------------------------------------------------------------

def stopped_at_views(tmp, freeze):
    """render, check (and freeze), then `finish --go` stops for the views."""
    wd, pack, _ = id_dump(tmp, [NAMED, PET])
    codes = [ix.run(cmd, wd)[0] for cmd in ("render", "check")
             + (("freeze",) if freeze else ())]
    return wd, pack, codes, fin.finish(wd, "--go")


def printed_route(out):
    """The command lines of the stop message, in order. Their first word is
    how the owner types Python on THIS host (`py` on Windows, RS5)."""
    return [line.strip() for line in out.splitlines()
            if line.startswith(f"     {photo_platform.owner_python()} ")
            and "photo_index.py" in line]


@case
def a_frozen_stop_prints_unfreeze_first_and_the_route_works():
    """⭐ FIX9 F10 REPRODUCTION (UAT01-9). ⛔ FAILS on 0dc797b: at the views stop
    after a freeze, the printed route began `identify --answers --go`, which a
    freeze that holds refuses ("Lift it first"). Now it begins with `unfreeze
    --reason "..."` and names render, check and freeze; followed line by line
    it ends in `finish --go` exit 0 with the agreed name in the folder."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, codes, r = stopped_at_views(tmp, freeze=True)
        route = printed_route(r.stdout)
        answer(wd, {"PET_3.jpg": "agree"})
        steps = []
        for line in route:
            # K3 — the script path is quoted: `…/photo_index.py" <cmd>`.
            cmd = line.split("photo_index.py", 1)[1].lstrip('"').split()[0]
            argv = {"unfreeze": ("unfreeze", wd, "--reason", "the agent's verdicts"),
                    "identify": ("identify", wd, "--answers",
                                 wd / photo_index.VIEWS_NAME, "--go")}.get(cmd, (cmd, wd))
            steps.append((cmd, ix.run(*argv)[0]))
        again = fin.finish(wd, "--go")
        got = fin.copied(tmp)
    order = [s[0] for s in steps]
    ok = (codes == [0, 0, 0] and r.returncode == 3
          and order == ["unfreeze", "identify", "render", "check", "freeze"]
          and '--reason "..."' in route[0] and "--answers" in route[1]
          and all(c == 0 for _s, c in steps) and again.returncode == 0
          and any("Lotus" in p and p.endswith("PET_3.jpg") for p in got))
    return ok, (f"codes={codes} rc={r.returncode} route={route} steps={steps} "
                f"again={again.returncode} {again.stdout[-300:]!r} got={got}")


@case
def a_frozen_views_file_and_the_apply_reminder_name_unfreeze():
    """FIX9 F10 REPRODUCTION (the other two print sites). ⛔ FAILS on 0dc797b:
    the views file header and `identify --new-only`'s "Apply them" named only
    `identify --answers --go`."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, codes, r = stopped_at_views(tmp, freeze=True)
        head = views(wd).split("## Proposed")[0]
        answer(wd, {"PET_3.jpg": "agree"})
        ncode, nout, _n = ix.run("identify", wd, "--new-only")
    wd = wd.resolve()
    line = photo_platform.run_line(photo_platform.owner_python(),
                                   ROOT / "scripts" / "photo_index.py")
    unfreeze = f'{line} unfreeze "{wd}" --reason "..."'
    apply_ = (f'{line} identify "{wd}" --answers '
              f'"{wd / photo_index.VIEWS_NAME}" --go')
    ok = (codes == [0, 0, 0] and r.returncode == 3
          and f"    {unfreeze}\n    {apply_}\n\nthen render, check and freeze again "
              "before copying." in head
          and ncode == photo_index.EXIT_VIEWS_WANTED
          and f"Apply them:\n  {unfreeze}\n  {apply_}" in nout)
    return ok, f"codes={codes} rc={r.returncode} head={head[-400:]!r} new-only={ncode} {nout!r}"


@case
def an_unfrozen_stop_prints_the_route_as_before():
    """GUARD. With no freeze the three prints are the 0dc797b text exactly —
    and the conductor's `verify` question leaves no line in the stop."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, codes, r = stopped_at_views(tmp, freeze=False)
        head = views(wd).split("## Proposed")[0]
        answer(wd, {"PET_3.jpg": "agree"})
        ncode, nout, _n = ix.run("identify", wd, "--new-only")
    tool = ROOT / "scripts" / "photo_index.py"
    wd = wd.resolve()
    vf = wd / photo_index.VIEWS_NAME
    py = photo_platform.owner_python()
    line = photo_platform.run_line(py, tool)
    stop = ("nothing and this command does not ask it again). Then run:\n"
            f"     {line} identify \"{wd}\" --answers \"{vf}\" --go\n"
            f"     {line} render \"{wd}\"   (then check and freeze)\n"
            "   then re-run this command.")
    apply_ = f'{line} identify "{wd}" --answers "{vf}" --go'
    ok = (codes == [0, 0] and r.returncode == 3 and stop in r.stdout
          and "unfreeze" not in r.stdout and "$ photo_index.py verify" not in r.stdout
          and f"When you have written your verdicts:\n\n    {apply_}\n\n" in head
          and "unfreeze" not in head
          and nout.rstrip().endswith(f"Apply them:\n  {apply_}")
          and ncode == photo_index.EXIT_VIEWS_WANTED)
    return ok, f"codes={codes} rc={r.returncode} out={r.stdout[-700:]!r} head={head[-300:]!r} {nout!r}"


@case
def a_dry_run_says_go_would_stop_for_the_views_and_writes_nothing():
    """⭐ REPRODUCTION (M1, UAT01-9 F11 / UAT01-10 F2). ⛔ FAILS on 4739665: the
    dry run only said views "run only with --go", and `--go` then stopped for
    them. It now asks `identify --preview` — the same decision, nothing
    written — and says `--go` would stop; `--go` does."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack, _ = id_dump(tmp, [NAMED, PET])
        codes = [ix.run(cmd, wd)[0] for cmd in ("render", "check", "freeze")]
        before = fin.work_dir_state(wd)
        dry = fin.dry_run(wd)
        changed = fin.changed_files(before, fin.work_dir_state(wd))
        go = fin.finish(wd, "--go")
    ok = (codes == [0, 0, 0] and dry.returncode == 0 and not changed
          and "would STOP here, before copying, for the agent's identify views"
          in dry.stdout and go.returncode == 3)
    return ok, (f"codes={codes} dry={dry.returncode} changed={changed} "
                f"go={go.returncode} out={dry.stdout[-600:]!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    failures = []
    width = max(len(f.__name__) for f in CASES)
    for fn in CASES:
        try:
            ok, detail = fn()
        except Exception as exc:                                # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            failures.append(fn.__name__)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'FAIL'}  "
                  f"{fn.__name__.replace('_', ' ').ljust(width)}"
                  + ("" if ok else f"   {detail}"))
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} identify cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
