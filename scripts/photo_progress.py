#!/usr/bin/env python3
"""The run progress file (M12, G11): one `run-progress.json` per work dir that
says, for every stage of a dump, pending / running / done, when it started and
ended, and how many items it has done of how many.

⛔ It lives in the WORK DIR, never in the index: `photo_index.freeze_hash()`
covers the whole index but `frozen` and `log`, so a progress write there would
stale every freeze (exit 4).

A stage killed mid-way stays `running`; a re-run starts it again, and each
stage's own resume (embed's index, the copy state) decides what is new work.
A stage that is `done` is skipped by `finish`, and `photo_run.py status` reads
this file to print the exact next command.

Every write is atomic (tmp + os.replace): a kill between two writes leaves the
previous file whole. Stdlib only — `photo_plan`-free stages import it.

Rates: a done stage records its seconds per item and the machine it ran on,
so the next dump on this machine can estimate its picture pass before it
starts (never a hardcoded number).

Test seam: `fault(point)` ends the process at once when $PHOTO_TEST_FAULT names
that point (`point` or `point@N` = its N-th call). Set only by tests.
"""
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

PROGRESS_NAME = "run-progress.json"
STAGES = ("scan", "cluster", "embed", "scene_labels", "identity", "see",
          "pages", "identify", "freeze", "copy", "verify", "rename",
          "after_check")
PENDING, RUNNING, DONE = "pending", "running", "done"
# The picture pass (G11): the two per-file model stages. The agent's own
# viewing in photo_see is not timed here — it is the agent's time, not the
# machine's.
PICTURE_STAGES = ("embed", "identity")

FAULT_ENV = "PHOTO_TEST_FAULT"
FAULT_RC = 137
_fault_calls = {}

# G58 — a forced stop (Ctrl-C, the window closed, kill) ends the whole run.
STOP_RC = 130
STOP_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP")
_stop = {"signal": None, "child": None, "workdir": None}


def _on_stop(signum, _frame):
    import signal
    _stop["signal"] = signal.Signals(signum).name
    child = _stop["child"]
    if child is not None:
        # A `kill <pid>` reaches the conductor only; the stage it runs must
        # hear it too, or it goes on to its own end (C-23, measured).
        try:
            child.send_signal(signum)
        except (OSError, ValueError):
            pass


def catch_stop(workdir=None):
    """Turn every stop signal into a flag the stage checks between files or
    stages. ⛔ Set explicitly, never left to Python's default: a run started
    in the background by a script inherits SIGINT ignored, and Python then
    never raises KeyboardInterrupt (C-23, measured)."""
    import signal
    if workdir is not None:
        _stop["workdir"] = workdir
    for name in STOP_SIGNALS:
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, _on_stop)


def stopped():
    """-> the stop signal's name (SIGINT, ...) once one arrived, else None."""
    return _stop["signal"]


def run_child(cmd, **kw):
    """subprocess.run for a stage under catch_stop(): a stop that reaches only
    this process is passed on to the stage, and a stage that ended on a stop
    of its own (STOP_RC, or killed by a stop signal) stops this run too — a
    `kill` of the stage alone used to start the next plan (C-23). -> rc."""
    import signal
    import subprocess
    with subprocess.Popen(cmd, **kw) as child:
        _stop["child"] = child
        try:
            rc = child.wait()
        finally:
            _stop["child"] = None
    if _stop["signal"] is None:
        by = {getattr(signal, n, None): n for n in STOP_SIGNALS}
        if rc == STOP_RC:
            _stop["signal"] = "the stage's own stop"
        elif rc < 0 and -rc in by:
            _stop["signal"] = by[-rc]
    return rc


def fault(point):
    want = os.environ.get(FAULT_ENV)
    if not want:
        return
    name, _, nth = want.partition("@")
    if name != point:
        return
    _fault_calls[point] = _fault_calls.get(point, 0) + 1
    if _fault_calls[point] >= int(nth or 1):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(FAULT_RC)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def machine():
    """A short hash of the host name: rates are matched per machine, and the
    name itself (often the owner's) is never written."""
    return hashlib.sha256((platform.node() or "unknown").encode()).hexdigest()[:12]


def path(workdir):
    return Path(workdir) / PROGRESS_NAME


def load(workdir):
    try:
        data = json.loads(path(workdir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("stages", {})
    return data


def save(workdir, data):
    p = path(workdir)
    if not p.parent.is_dir():
        return
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def stage(workdir, name):
    return load(workdir)["stages"].get(name) or {}


def state(workdir, name):
    return stage(workdir, name).get("state", PENDING)


def is_done(workdir, name):
    return state(workdir, name) == DONE


def update(workdir, name, **fields):
    data = load(workdir)
    rec = data["stages"].setdefault(name, {"state": PENDING})
    rec.update(fields)
    save(workdir, data)
    return rec


def start(workdir, name, total=None, **extra):
    """-> the stage record. `runs` counts every start, so a case (and the
    Lead) can see whether a stage ran again."""
    data = load(workdir)
    rec = data["stages"].setdefault(name, {"state": PENDING})
    rec.update({"state": RUNNING, "started": now(), "ended": None,
                "done": 0, "total": total, "runs": rec.get("runs", 0) + 1,
                "_t0": time.time()}, **extra)
    save(workdir, data)
    return rec


def tick(workdir, name, done, total=None, **extra):
    fields = {"done": done, **extra}
    if total is not None:
        fields["total"] = total
    return update(workdir, name, **fields)


def finish(workdir, name, done=None, total=None, items=None, **extra):
    """Mark a stage done. `items` = how many items this run really processed;
    with it, the stage's rate (seconds per item) is recorded for estimates."""
    data = load(workdir)
    rec = data["stages"].setdefault(name, {"state": PENDING})
    t0 = rec.pop("_t0", None)
    rec.update({"state": DONE, "ended": now()}, **extra)
    if done is not None:
        rec["done"] = done
    if total is not None:
        rec["total"] = total
    if t0 is not None:
        rec["seconds"] = round(time.time() - t0, 1)
        if items:
            rec["rate_s"] = round(rec["seconds"] / items, 4)
            rec["rate_items"] = items
            rec["machine"] = machine()
    save(workdir, data)
    return rec


def note(workdir, key, value):
    """A run-level fact beside the stages (the map counts, the estimate)."""
    data = load(workdir)
    data[key] = value
    save(workdir, data)


def said_once(workdir, key, text):
    """-> True the first time `text` is said under `key` for this dump, False
    on every later call with the same text (U6-4: a warning once per dump)."""
    data = load(workdir)
    said = data.setdefault("said", {})
    if said.get(key) == text:
        return False
    said[key] = text
    save(workdir, data)
    return True


def already_said(workdir, key, text):
    return (load(workdir).get("said") or {}).get(key) == text


def forget_said(workdir, key):
    data = load(workdir)
    if (data.get("said") or {}).pop(key, None) is not None:
        save(workdir, data)


def recorded_rate(workdir, name):
    """-> (seconds per item, basis text) from the last done run of `name` on
    this machine: this work dir first, then the other work dirs beside it
    (one collection). None when there is none."""
    me = machine()
    best = None
    wd = Path(workdir)
    dirs = [wd] + sorted(p for p in wd.parent.iterdir()
                         if p.is_dir() and p != wd) if wd.parent.is_dir() else [wd]
    for d in dirs:
        rec = stage(d, name)
        if rec.get("state") != DONE or not rec.get("rate_s") or rec.get("machine") != me:
            continue
        if best is None or (rec.get("ended") or "") > (best[1].get("ended") or ""):
            best = (d, rec)
    if best is None:
        return None
    d, rec = best
    return rec["rate_s"], (f"the last {name} run on this machine "
                           f"({d.name}, {rec['rate_items']} files, {rec['ended'][:10]})")


def duration(seconds):
    m = int(round(seconds / 60.0))
    if m < 1:
        return "under 1 min"
    h, m = divmod(m, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def estimate_line(photos, rate, basis):
    return (f"Picture pass: {photos} photos, about {duration(photos * rate)} "
            f"(rate {rate:.2f} s/photo from {basis})")


def picture_estimate(workdir, photos, sample=None, record=True):
    """-> the estimate line for the picture pass, or None when no stage of it
    has a rate yet. `sample` = {stage: (rate, basis)} timed in THIS run; any
    other stage takes its recorded rate on this machine. A stage with neither
    is left out and the basis says so — never a guessed number."""
    parts, bases, missing = [], [], []
    for name in PICTURE_STAGES:
        got = (sample or {}).get(name) or recorded_rate(workdir, name)
        if got:
            parts.append(got[0])
            bases.append(f"{name}: {got[1]}")
        else:
            missing.append(name)
    if not parts:
        return None
    rate = sum(parts)
    basis = "; ".join(bases) + (f"; {', '.join(missing)} not timed yet on this "
                                "machine, not included" if missing else "")
    if record:
        data = load(workdir)
        data.setdefault("estimates", []).append(
            {"photos": photos, "seconds": round(photos * rate),
             "rate_s": round(rate, 4), "basis": basis, "at": now()})
        save(workdir, data)
    return estimate_line(photos, rate, basis)


def picture_actual(workdir):
    """-> seconds the picture pass took, once every timed stage of it is done
    (the sum of their last runs: a killed run's time is not in it)."""
    data = load(workdir)
    recs = [data["stages"].get(s) or {} for s in PICTURE_STAGES]
    if not all(r.get("state") == DONE and "seconds" in r for r in recs):
        return None
    return round(sum(r["seconds"] for r in recs), 1)


def compact_line(workdir, done_what, command=None):
    """⛔ The agent may compact (or the session may end) here: everything
    before this line is on disk. The command is the one `status` prints."""
    if command is None:
        import photo_run  # lazy: photo_run imports this module
        command = photo_run.next_command(workdir)
    return f"SAFE TO COMPACT — {done_what}. Resume with:\n    {command}"
