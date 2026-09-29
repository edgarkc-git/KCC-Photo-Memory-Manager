#!/usr/bin/env python3
"""Card 6 (F-jj rule a) — embed writes the U3-06 document check for every
embedded still, so photo_see / photo_sample can hold documents out of vision.

The CLIP judgement is stubbed (a red thumbnail "is a document"): what belongs
to this file is which stills are scored, when a flag is kept, and when it is
scored again. The judgement itself is `photo_onboard_page.document_filter`,
unchanged. Each case says REPRO (fails on c5b6f99) or GUARD.
"""

import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import photo_embed  # noqa: E402
import photo_onboard_page as op  # noqa: E402
from PIL import Image  # noqa: E402

RED, GREY = (220, 10, 10), (90, 90, 90)
CALLS = []


def red_is_document(bundle=None, device=None):
    def judge(raw):
        CALLS.append(1)
        with Image.open(io.BytesIO(raw)) as im:
            r, g, _b = im.convert("RGB").getpixel((0, 0))
        return r > 150 and g < 80
    return judge


def jpeg(path, color):
    Image.new("RGB", (64, 48), color).save(path, "JPEG")
    return path


def row(path, sha, kind="image"):
    return {"SourceFile": str(path), "sha256": sha, "kind": kind,
            "status": "embedded"}


def raw_of(color):
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, "JPEG")
    return buf.getvalue()


def run(embed_dir, rows, fresh):
    return photo_embed.write_document_flags(embed_dir, rows, {}, fresh,
                                            bundle=("t", "m", "p", "d"))


def case_embed_writes_a_flag_per_still(tmp):
    """REPRO — c5b6f99 wrote no document check at embed at all."""
    a, b = jpeg(tmp / "a.jpg", RED), jpeg(tmp / "b.jpg", GREY)
    v = tmp / "c.mov"
    v.write_bytes(b"\x00" * 64)
    rows = [row(a, "s1"), row(b, "s2"), row(v, "s3", kind="video")]
    flags = run(tmp, rows, {str(a): raw_of(RED), str(b): raw_of(GREY)})
    assert flags == {str(a): True, str(b): False}, flags
    body = json.loads((tmp / photo_embed.DOCUMENT_FLAGS_NAME).read_text())
    assert body["documents"] == 1 and str(v) not in body["document"], body
    assert photo_embed.load_document_flags(tmp) == flags


def case_a_resume_keeps_flags_by_content(tmp):
    """GUARD — same content, no new judgement; changed content, judged again."""
    a, b = jpeg(tmp / "a.jpg", RED), jpeg(tmp / "b.jpg", GREY)
    run(tmp, [row(a, "s1"), row(b, "s2")], {str(a): raw_of(RED), str(b): raw_of(GREY)})
    CALLS.clear()
    flags = run(tmp, [row(a, "s1"), row(b, "s2")], {})
    assert CALLS == [] and flags[str(a)] is True, (CALLS, flags)
    jpeg(b, RED)
    flags = run(tmp, [row(a, "s1"), row(b, "s2-changed")], {})
    assert len(CALLS) == 1 and flags[str(b)] is True, (CALLS, flags)


def case_an_old_index_is_filled_from_the_file(tmp):
    """GUARD — a still embedded before this check has no fresh bytes: its
    preview is made again, once, with no --force."""
    a = jpeg(tmp / "a.jpg", RED)
    flags = run(tmp, [row(a, "s1")], {})
    assert flags == {str(a): True}, flags


def case_a_changed_check_scores_everything_again(tmp):
    """GUARD — another margin or prompt set is another check."""
    a = jpeg(tmp / "a.jpg", GREY)
    run(tmp, [row(a, "s1")], {str(a): raw_of(GREY)})
    CALLS.clear()
    before = op.DOCUMENT_MARGIN
    op.DOCUMENT_MARGIN = before + 0.01
    try:
        run(tmp, [row(a, "s1")], {})
    finally:
        op.DOCUMENT_MARGIN = before
    assert CALLS == [1], CALLS


CASES = [
    ("embed writes a document flag per still (REPRO)", case_embed_writes_a_flag_per_still),
    ("a resume keeps flags by content (GUARD)", case_a_resume_keeps_flags_by_content),
    ("an old index is filled from the file (GUARD)", case_an_old_index_is_filled_from_the_file),
    ("a changed check scores everything again (GUARD)",
     case_a_changed_check_scores_everything_again),
]


def main():
    real = op.document_filter
    op.document_filter = red_is_document
    passed = 0
    try:
        for name, fn in CASES:
            tmp = Path(tempfile.mkdtemp(prefix="document_flags_case_"))
            CALLS.clear()
            try:
                fn(tmp)
                print(f"  ok    {name}")
                passed += 1
            except Exception as e:                        # noqa: BLE001
                print(f"  FAIL  {name}: {type(e).__name__}: {e}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    finally:
        op.document_filter = real
    print(f"\n{passed}/{len(CASES)} document_flags cases passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
