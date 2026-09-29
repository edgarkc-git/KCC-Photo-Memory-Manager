#!/usr/bin/env python3
"""Cases for photo_identity.py (R3a) — every animal in the frame, not the
best one.

The reproduction this suite exists for: before R3a a frame holding two cats
produced ONE row, one crop and one vector, so nothing anywhere in the engine
could say the frame was shared. That is D-24 — 3 of the 5 exemplars an owner
confirmed in UAT01 were wrong, two of them because the frame held both
animals and the review page had no way to show it.

⛔ Cases 1-3 FAIL on the pre-R3a engine (`best_animal_box` returns a single
tuple or None). Cases 4-7 are guards: they pass before and after, and are
here so the resume path and the pre-R3a index on an owner's disk cannot
break silently while the reproduction is being fixed.

No model weights and no photographs: `animal_boxes()` takes `torch` and the
detector as ARGUMENTS, so a stub of each is enough to test the selection
rule. The parts that need real weights are exercised by the UAT run, not
here.

  ./.venv/bin/python3 tests/photo_identity_cases.py [-v]
  python3 tests/photo_identity_cases.py [-v]      # numpy is the only need

Exit 0 = pass.
"""

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import photo_identity  # noqa: E402

VERBOSE = False


def log(msg):
    if VERBOSE:
        print(f"       {msg}")


class StubTorch:
    """Only the three names `animal_boxes` touches."""

    class _NoGrad:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    @staticmethod
    def no_grad():
        return StubTorch._NoGrad()

    @staticmethod
    def from_numpy(arr):
        return StubTensor(arr)


class StubTensor:
    def __init__(self, arr):
        self.arr = arr

    def permute(self, *a):
        return self

    def float(self):
        return self

    def __truediv__(self, other):
        return self

    def to(self, device):
        return self


class StubImage:
    """Enough of a PIL image for np.array() to accept it."""

    def __init__(self, width=100, height=100):
        self.width, self.height = width, height

    def __array__(self, dtype=None):
        import numpy as np
        return np.zeros((self.height, self.width, 3), dtype=dtype or np.uint8)


def detector_returning(detections):
    """detections: [(label_id, score, box)] -> a callable detector stub."""
    def detector(_batch):
        return [{"scores": [d[1] for d in detections],
                 "labels": [d[0] for d in detections],
                 "boxes": [d[2] for d in detections]}]
    return detector


# label 1 = cat, 2 = dog, 9 = an unmapped COCO class (a chair, say)
LABELS = {1: "cat", 2: "dog"}


def case_two_animals_are_two_detections():
    """⭐ THE REPRODUCTION. A frame with two cats must produce two detections,
    ranked by score, each with its own box."""
    found = photo_identity.animal_boxes(
        StubTorch, detector_returning([
            (1, 0.71, (10.0, 10.0, 30.0, 30.0)),
            (1, 0.93, (50.0, 50.0, 90.0, 90.0)),
        ]), LABELS, "cpu", StubImage())
    assert isinstance(found, list), \
        f"animal_boxes must return a list of detections, got {type(found)}"
    assert len(found) == 2, \
        f"a frame with two cats must yield 2 detections, got {len(found)}"
    log(f"{[(k, s) for k, s, _ in found]}")
    assert [s for _, s, _ in found] == [0.93, 0.71], \
        "detections must be ordered by score, highest first — det_index 0 has " \
        "to mean the same thing on every row of every run"
    assert found[0][2] == (50.0, 50.0, 90.0, 90.0), "box travels with its score"


def case_a_duplicate_box_is_one_animal():
    """⭐ THE U2-13 REPRODUCTION. A detector that draws two overlapping boxes
    on ONE animal must yield ONE detection, not two.

    ⭐ THE BOXES ARE THE MEASURED ONES, at the thumbnail scale the detector
    actually runs on: one animal lying on its side, returned twice. Their
    containment is 0.67 and their IoU is 0.43 — so this case also refuses the
    obvious WRONG FIX. An IoU gate set anywhere near this threshold leaves
    both boxes standing and the frame still unusable.

    ⛔ FAILS on the un-deduped engine, which returns both boxes."""
    found = photo_identity.animal_boxes(
        StubTorch, detector_returning([
            (1, 0.99, (120.0, 66.0, 1272.0, 623.0)),
            (1, 0.51, (6.0, 47.0, 746.0, 746.0)),
        ]), LABELS, "cpu", StubImage())
    log(f"{[(k, s, b) for k, s, b in found]}")
    assert len(found) == 1, \
        f"two boxes on one animal is ONE animal, got {len(found)} detections"
    assert found[0][1] == 0.99, \
        "the survivor of a duplicate pair is the higher-scoring box"


def case_a_duplicate_box_of_another_class_is_one_animal():
    """⭐ REPRODUCTION, and the half the detector cannot fix itself. Its own
    NMS runs PER CLASS, so one animal returned once as `cat` and once as
    `dog` is the duplicate that always survives to here. ⛔ A per-kind gate
    would pass this test while leaving the case open."""
    found = photo_identity.animal_boxes(
        StubTorch, detector_returning([
            (1, 0.99, (0.0, 0.0, 100.0, 60.0)),
            (2, 0.58, (0.0, 0.0, 65.0, 65.0)),
        ]), LABELS, "cpu", StubImage())
    log(f"{[(k, s) for k, s, _ in found]}")
    assert len(found) == 1, \
        f"a cat also returned as a dog is one animal, got {len(found)}"
    assert found[0][0] == "cat", "the higher-scoring kind survives"


def case_two_animals_survive_deduplication():
    """GUARD, and the one that matters most: over-suppression deletes a real
    animal, which is silent. Two boxes side by side, touching but not nested,
    are two animals and must both survive."""
    found = photo_identity.animal_boxes(
        StubTorch, detector_returning([
            (1, 0.93, (0.0, 0.0, 50.0, 50.0)),
            (1, 0.88, (45.0, 0.0, 95.0, 50.0)),
        ]), LABELS, "cpu", StubImage())
    log(f"{[(k, s) for k, s, _ in found]}")
    assert len(found) == 2, \
        f"two animals standing side by side are two animals, got {len(found)}"


def case_a_suppressed_box_cannot_suppress_a_third():
    """GUARD for the greedy rule. Comparison is against KEPT boxes only. B is
    a duplicate of A and dies; C overlaps B heavily but not A, so C is a
    SECOND ANIMAL and must live. Comparing against everything seen would
    chain one spurious box into deleting a real neighbour."""
    # ⛔ B must OVERLAP A rather than nest inside it: anything nested inside
    # a nested box is nested in the outer one too, so the case cannot be
    # built from three concentric boxes at all.
    a = (0.0, 0.0, 100.0, 100.0)     # kept
    b = (70.0, 0.0, 120.0, 100.0)    # 60% inside A -> suppressed
    c = (100.0, 0.0, 120.0, 100.0)   # 100% inside B, 0% inside A
    assert photo_identity.containment(b, a) > photo_identity.DUPLICATE_CONTAINMENT
    assert photo_identity.containment(c, b) > photo_identity.DUPLICATE_CONTAINMENT
    assert photo_identity.containment(c, a) <= photo_identity.DUPLICATE_CONTAINMENT
    found = photo_identity.animal_boxes(
        StubTorch, detector_returning([
            (1, 0.99, a), (1, 0.80, b), (1, 0.70, c),
        ]), LABELS, "cpu", StubImage())
    log(f"{[(s, bx) for _, s, bx in found]}")
    assert len(found) == 2, \
        f"a box killed as a duplicate must not kill a third, got {len(found)}"
    assert [s for _, s, _ in found] == [0.99, 0.70]


def case_containment_is_not_iou():
    """The metric itself. A small box wholly inside a large one is a
    duplicate at containment 1.0 while its IoU is only 0.25 — an IoU gate at
    any usual threshold cannot see the case this exists for."""
    big = (0.0, 0.0, 100.0, 100.0)
    small = (0.0, 0.0, 50.0, 50.0)
    assert photo_identity.containment(small, big) == 1.0
    assert photo_identity.containment(big, small) == 1.0, "symmetric"
    iou = 2500.0 / 10000.0
    log(f"containment 1.0 vs IoU {iou}")
    assert iou < photo_identity.DUPLICATE_CONTAINMENT, \
        "the point of the case: IoU would not flag what containment does"
    assert photo_identity.containment((0.0, 0.0, 1.0, 1.0),
                                      (5.0, 5.0, 6.0, 6.0)) == 0.0


def case_a_deduplicated_frame_becomes_identity_evidence():
    """⭐ THE ACCEPTANCE TEST, at the row level. The frame that lost an
    owner's most-photographed animal half its identity evidence: one animal,
    two boxes, refused by the `det_count > 1` guard. After deduplication the
    same frame states one animal and is admissible."""
    before = {"status": photo_identity.STATUS_OK, "det_index": 0,
              "det_count": 2, "box_share": 0.71}
    ok, why = photo_identity.exemplar_quality(before)
    assert not ok, "the un-deduped row is the defect and must still be refused"
    log(f"before: {why}")
    found = photo_identity.animal_boxes(
        StubTorch, detector_returning([
            (1, 0.99, (120.0, 66.0, 1272.0, 623.0)),
            (1, 0.51, (6.0, 47.0, 746.0, 746.0)),
        ]), LABELS, "cpu", StubImage())
    after = {**before, "det_count": len(found)}
    ok, why = photo_identity.exemplar_quality(after)
    assert ok, f"a single-animal frame must be admissible evidence, got {why}"


def case_below_threshold_is_dropped():
    found = photo_identity.animal_boxes(
        StubTorch, detector_returning([
            (1, 0.93, (0.0, 0.0, 10.0, 10.0)),
            (1, photo_identity.MIN_DETECTION_SCORE - 0.01, (1.0, 1.0, 2.0, 2.0)),
        ]), LABELS, "cpu", StubImage())
    assert len(found) == 1, f"a sub-threshold box must not be kept: {found}"


def case_non_animal_is_dropped():
    """A chair scoring 0.99 is not a subject. The COCO map is the gate, and
    ⛔ `person` is deliberately not in it (NF-3)."""
    found = photo_identity.animal_boxes(
        StubTorch, detector_returning([
            (9, 0.99, (0.0, 0.0, 99.0, 99.0)),
            (2, 0.66, (5.0, 5.0, 20.0, 20.0)),
        ]), LABELS, "cpu", StubImage())
    assert [k for k, _, _ in found] == ["dog"], \
        f"only mapped animal classes survive, got {found}"
    assert "person" not in photo_identity.COCO_TO_KIND.values(), \
        "the detector must never emit a person (NF-3)"


def case_empty_frame_is_an_empty_list():
    found = photo_identity.animal_boxes(
        StubTorch, detector_returning([]), LABELS, "cpu", StubImage())
    assert found == [], f"no animal is an empty list, not None: {found!r}"


def write_index(embed, rows, dim=4, meta_extra=None):
    import numpy as np
    embed.mkdir(parents=True, exist_ok=True)
    with open(embed / "identity.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=photo_identity.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    np.save(embed / "identity.npy",
            np.array([[float(i + 1)] * dim for i in range(len(rows))],
                     dtype=np.float32))
    meta = {**photo_identity.meta_identity(dim), "created_at": "2029-01-01 00:00"}
    (embed / "identity-meta.json").write_text(json.dumps({**meta,
                                                          **(meta_extra or {})}))


def det_row(path, det_index, det_count, score, sha="s1"):
    return {"SourceFile": path, "sha256": sha,
            "status": photo_identity.STATUS_OK,
            "det_index": det_index, "det_count": det_count, "kind": "cat",
            "det_score": score, "box": "1.0,1.0,9.0,9.0", "box_share": 0.4,
            "error": ""}


def case_load_detections_groups_by_file():
    """The wire R3b reads: every animal, in det_index order."""
    with tempfile.TemporaryDirectory() as tmp:
        embed = Path(tmp) / "embed"
        write_index(embed, [
            det_row("/a.jpg", 1, 2, 0.6),        # deliberately out of order
            det_row("/a.jpg", 0, 2, 0.9),
            {**det_row("/b.jpg", 0, 0, ""), "status": photo_identity.STATUS_NO_SUBJECT},
        ])
        by_file, space = photo_identity.load_detections(embed)
        assert set(by_file) == {"/a.jpg", "/b.jpg"}, by_file.keys()
        assert len(by_file["/a.jpg"]) == 2, "both cats must survive the round trip"
        assert [int(r["det_index"]) for r, _ in by_file["/a.jpg"]] == [0, 1], \
            "entries must come back in det_index order regardless of file order"
        assert by_file["/a.jpg"][0][1][0] == 2.0, \
            "each detection must keep ITS OWN vector, not the file's first row"
        assert len(by_file["/b.jpg"]) == 1, \
            "a file with no animal keeps exactly one row — absent means " \
            "'never indexed', which is a different answer"
        assert space["space"] == "subject-identity"


def case_load_index_is_the_primary_detection_only():
    """The compat contract every pre-R3b consumer is built on."""
    with tempfile.TemporaryDirectory() as tmp:
        embed = Path(tmp) / "embed"
        write_index(embed, [det_row("/a.jpg", 0, 2, 0.9),
                            det_row("/a.jpg", 1, 2, 0.6)])
        index, _ = photo_identity.load_index(embed)
        assert list(index) == ["/a.jpg"], "one entry per FILE, still"
        row, vec = index["/a.jpg"]
        assert int(row["det_index"]) == 0, \
            "load_index must return det_index 0, never the last row it saw"
        assert vec[0] == 1.0, "the primary detection's own vector"


def case_a_pre_r3a_index_is_read_not_rejected():
    """An owner's existing identity.csv has no det_index column. It must stay
    readable — photo_see and photo_memory both load it on a work dir the
    owner has already built — and it must be FLAGGED, never quietly counted
    as multi-detection data it cannot support."""
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        embed = Path(tmp) / "embed"
        embed.mkdir(parents=True)
        legacy_fields = ["SourceFile", "sha256", "status", "kind", "det_score",
                         "box", "box_share", "error"]
        with open(embed / "identity.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=legacy_fields)
            w.writeheader()
            w.writerow({"SourceFile": "/a.jpg", "sha256": "s1",
                        "status": photo_identity.STATUS_OK, "kind": "cat",
                        "det_score": 0.9, "box": "1.0,1.0,9.0,9.0",
                        "box_share": 0.4, "error": ""})
        np.save(embed / "identity.npy", np.array([[1.0] * 4], dtype=np.float32))
        (embed / "identity-meta.json").write_text(json.dumps(
            {**photo_identity.meta_identity(4), "created_at": "2029-01-01 00:00"}))

        rows, vectors, meta = photo_identity.load_existing(embed)
        assert meta.get("legacy_single_detection") is True, \
            "a pre-R3a index must be flagged so run() rebuilds it"
        assert rows[0]["det_index"] == "0", rows[0]
        assert rows[0]["det_count"] == "", \
            "det_count 1 would be a claim this index cannot support — it knows " \
            "an animal was found, never how many were there"
        index, _ = photo_identity.load_index(embed)
        assert "/a.jpg" in index, "a legacy index must still be usable by a consumer"


def case_a_shared_frame_never_becomes_identity_evidence():
    """⭐ THE R3b REPRODUCTION. In UAT01 two of the five exemplars an owner
    confirmed for one cat were frames holding BOTH cats. The exemplar store
    keys on `vec_ref`, the file's content sha, so one photograph cannot bank a
    separate vector for each animal in it — whichever scored higher silently
    became both.

    ⛔ Refused as EVIDENCE only. The owner's yes stands and the file keeps its
    name and its folder — `add_exemplar` never overturns a human answer on
    geometry; it simply does not join the bank the matcher scores against.
    Two subjects in one frame is two names to log, never a frame to refuse
    (owner decision, 20260904)."""
    ok, why = photo_identity.exemplar_quality(det_row("/a.jpg", 0, 2, 0.9))
    assert not ok, "a frame holding two animals must not become an exemplar"
    assert "2 animals" in why, f"the refusal must say what it saw: {why}"
    ok, _ = photo_identity.exemplar_quality(det_row("/a.jpg", 1, 2, 0.6))
    assert not ok, "and not by det_index either — it is the FRAME that is shared"
    ok, why = photo_identity.exemplar_quality(det_row("/b.jpg", 0, 1, 0.9))
    assert ok, f"a solo animal is still bankable: {why}"


def case_the_box_share_gate_still_bites():
    """A guard, not a reproduction: R3b adds a refusal ABOVE this one, and a
    new gate that shadows the gate below it is a silent regression."""
    small = {**det_row("/a.jpg", 0, 1, 0.9), "box_share": 0.001}
    ok, why = photo_identity.exemplar_quality(small)
    assert not ok and "frame" in why, \
        f"the box-share gate must still be reachable: {why}"


CASES = [
    ("two animals are two detections (REPRODUCTION)",
     case_two_animals_are_two_detections),
    ("two boxes on ONE animal are one detection (REPRODUCTION)",
     case_a_duplicate_box_is_one_animal),
    ("a duplicate under another class is one detection (REPRODUCTION)",
     case_a_duplicate_box_of_another_class_is_one_animal),
    ("two real animals survive deduplication", case_two_animals_survive_deduplication),
    ("a suppressed box cannot suppress a third",
     case_a_suppressed_box_cannot_suppress_a_third),
    ("containment sees what IoU cannot", case_containment_is_not_iou),
    ("a de-duplicated frame becomes identity evidence (ACCEPTANCE)",
     case_a_deduplicated_frame_becomes_identity_evidence),
    ("a sub-threshold box is dropped", case_below_threshold_is_dropped),
    ("a non-animal class is dropped, and person is never one",
     case_non_animal_is_dropped),
    ("a frame with no animal is an empty list", case_empty_frame_is_an_empty_list),
    ("load_detections groups every animal by file", case_load_detections_groups_by_file),
    ("load_index still answers with the primary detection",
     case_load_index_is_the_primary_detection_only),
    ("a pre-R3a index is read and flagged, not rejected",
     case_a_pre_r3a_index_is_read_not_rejected),
    ("a shared frame never becomes identity evidence (REPRODUCTION)",
     case_a_shared_frame_never_becomes_identity_evidence),
    ("the box-share gate still bites", case_the_box_share_gate_still_bites),
]


def case_dinov2_is_pinned_only_when_installed():
    """GUARD (FIX8 F8-9). torch.hub asks github.com for the default branch
    whenever the repo string has no ref, even with the model cached. The ref
    is pinned at the CALL only when the repo and the checkpoint are on disk;
    EMBED_SOURCE itself never changes — it is `model_source` in the identity
    space fingerprint, and changing it would make every index incomparable."""
    with tempfile.TemporaryDirectory() as tmp:
        hub = Path(tmp)
        assert photo_identity.dinov2_source(hub) == photo_identity.EMBED_SOURCE
        owner, repo = photo_identity.EMBED_SOURCE.split("/")
        (hub / f"{owner}_{repo}_main").mkdir()
        assert photo_identity.dinov2_source(hub) == photo_identity.EMBED_SOURCE
        (hub / "checkpoints").mkdir()
        (hub / "checkpoints" / f"{photo_identity.EMBED_ID}_pretrain.pth").write_bytes(b"x")
        assert photo_identity.dinov2_source(hub) == f"{photo_identity.EMBED_SOURCE}:main"
    assert photo_identity.EMBED_SOURCE == "facebookresearch/dinov2"
    assert photo_identity.meta_identity(0)["model_source"] == "facebookresearch/dinov2"


CASES.append(("F8-9 — DINOv2 is pinned only when installed (GUARD)",
              case_dinov2_is_pinned_only_when_installed))


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    passed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            print(f"  FAIL  {name}\n        {e}")
        except Exception as e:                            # noqa: BLE001
            print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
        else:
            print(f"  ok    {name}")
            passed += 1
    print(f"\n{passed}/{len(CASES)} photo_identity cases passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
