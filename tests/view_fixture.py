#!/usr/bin/env python3
"""A batch that really was looked at — the fixture the memorize rule needs.

VS-4 made `viewed-image:` an evidence claim rather than a string, so any test
that promotes an exemplar has to produce the artifacts a real look leaves
behind: a `see-report.json` naming the file in `selected`, a `see-labels.json`
recording the applied provenance, and a thumbnail in `samples/` with real
image magic bytes. Two suites need that, so it lives here rather than twice.

Everything is synthetic — invented paths, invented class words, four bytes of
JPEG header. Nothing here reads a photo, a pack or a drive.
"""

import json
from pathlib import Path

# Enough to satisfy `photo_evidence.MAGIC`. The guard checks the first bytes,
# not decodability — it holds no image library and must run in a process that
# has none — so a fixture that carries the header is exactly as strong as the
# check it is exercising, and no stronger.
JPEG = b"\xff\xd8\xff\xdb" + b"\x00" * 64


def batch_dir(root, batch=1):
    return Path(root) / "classify" / f"batch-{batch:02d}"


def make_look(root, path, batch=1, sample=None, label="Class-One",
              provenance="viewed-image:", write_labels=True, thumbnail=JPEG,
              extra_selected=()):
    """Write the artifacts one vision-confirmed look leaves, and return the
    evidence dict a caller hands to `Registry.add_exemplar`.

    `thumbnail=None` writes no file at all; pass bytes to forge one."""
    out = batch_dir(root, batch)
    samples = out / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    sample = sample or (Path(path).stem + ".jpg")

    selected = [{"path": str(path), "sample": sample, "rung": 1,
                 "reason": "cluster representative"}]
    selected += [dict(e) for e in extra_selected]
    report = {"engine": "photo_see.py (VS-2 see controller)", "batch": batch,
              "selected": selected, "samples_dir": str(samples),
              "clusters": [], "provisional": []}
    (out / "see-report.json").write_text(json.dumps(report, ensure_ascii=False))

    if write_labels:
        labels = [{"path": str(path), "label": label, "provenance": provenance,
                   "sample": sample}]
        (out / "see-labels.json").write_text(json.dumps(
            {"batch": batch, "labels": labels}, ensure_ascii=False))

    if thumbnail is not None:
        (samples / sample).write_bytes(thumbnail)

    return {"see_report": str(out / "see-report.json"), "batch": batch,
            "path": str(path), "sample": sample, "label": label}
