"""Test-only: a stage started with this folder on PYTHONPATH ends at once
(exit 137, like a kill) on the N-th call of a copy primitive, named by
$PHOTO_TEST_KILL = `copy2@N` (after the .part is written) or `replace@N`
(after a file is renamed into place; state-file renames are not counted).
Never imported by the engine; works on old and new code alike, so a case
can be shown to fail on the unfixed engine."""

import os
import shutil

_want = os.environ.get("PHOTO_TEST_KILL", "")
_name, _, _nth = _want.partition("@")
_calls = [0]


def _hit():
    _calls[0] += 1
    if _calls[0] >= int(_nth or 1):
        os._exit(137)


if _name == "copy2":
    _copy2 = shutil.copy2

    def copy2(src, dst, *a, **k):
        out = _copy2(src, dst, *a, **k)
        _hit()
        return out
    shutil.copy2 = copy2
elif _name == "replace":
    _replace = os.replace

    def replace(src, dst, *a, **k):
        _replace(src, dst, *a, **k)
        if not str(dst).endswith(".json"):
            _hit()
    os.replace = replace
