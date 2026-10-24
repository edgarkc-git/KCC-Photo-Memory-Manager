#!/usr/bin/env python3
"""M12 cases — a long run (G11, G50): the run progress file, resume after a
kill, the picture-pass estimate, the map request count, and a lookup-failed
warning said once per dump.

Every kill is a real process exit (137) in a stage started as a subprocess:
`tests/kill` ends a copy on its N-th copy primitive, and $PHOTO_TEST_FAULT ends
a stage at a named point (`photo_progress.fault`). After each kill the same
command runs again, and the case checks what the re-run did: no file copied
twice (dest bytes, inode and mtime), every source SHA in the copy state, and
no stage run again (the progress file's `runs` counter).

Needs the repo .venv (the embed case loads CLIP):

  ./.venv/bin/python3 tests/long_run_cases.py [-v]

Exit 0 = pass. Synthetic dumps in a temp dir; no network (tests/offline).
"""

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))
import photo_profile  # noqa: E402
import photo_progress  # noqa: E402
import photo_index_cases as ix  # noqa: E402

PY = sys.executable
KILLED = 137
STOPPED = 130  # G58: the exit code of a run ended by a stop signal
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def env(**extra):
    e = {k: v for k, v in os.environ.items()
         if k not in (photo_profile.ENV_VAR, "PHOTO_TEST_KILL", photo_progress.FAULT_ENV)}
    e.update({k: str(v) for k, v in extra.items()})
    return e


def stage_run(script, *argv, **extra):
    return subprocess.run([PY, str(SCRIPTS / script), *map(str, argv)],
                          capture_output=True, text=True, env=env(**extra))


def frozen_dump(tmp):
    """The two-day indexed dump of photo_index_cases, rendered, checked and
    frozen. -> work dir."""
    wd, _pack = ix.g3_dump(tmp)
    for cmd in ("init", "render", "check", "freeze"):
        code, _out, err = ix.run(cmd, wd)
        if code:
            raise RuntimeError(f"{cmd}: {err[-300:]}")
    return wd


def finish(wd, **extra):
    return stage_run("photo_run.py", "finish", wd, "--go", "--skip-memory", **extra)


def dest_files(tmp):
    root = Path(tmp) / "sorted"
    return {p: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes())
            for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def state_shas(wd):
    shas = set()
    for sp in (Path(wd) / "plan").glob("execute-state_*.json"):
        shas |= {v["sha256"] for v in json.loads(sp.read_text())["verified"].values()}
    return shas


def plan_sources(wd):
    import csv
    out = set()
    for csv_path in (Path(wd) / "plan").glob("plan_*-files.csv"):
        with open(csv_path, newline="") as f:
            out |= {r["SourceFile"] for r in csv.DictReader(f) if r["action"] == "copy"}
    return out


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runs(wd, name):
    return photo_progress.stage(wd, name).get("runs", 0)


def resumed_copy(kill):
    """Kill the copy at `kill`, run finish again, then once more. -> facts."""
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = frozen_dump(tmp)
        r1 = finish(wd, PYTHONPATH=ROOT / "tests" / "kill", PHOTO_TEST_KILL=kill)
        before = dest_files(tmp)
        parts = [p for p in before if p.name.endswith(".part")]
        r2 = finish(wd)
        after = dest_files(tmp)
        kept = {p: v for p, v in before.items() if not p.name.endswith(".part")}
        untouched = all(after.get(p) == v for p, v in kept.items())
        want = {sha(s) for s in plan_sources(wd)}
        copy_runs, verify_runs = runs(wd, "copy"), runs(wd, "verify")
        r3 = finish(wd)
        return {
            "r": (r1.returncode, r2.returncode, r3.returncode),
            "killed_with": len(kept), "parts": len(parts), "untouched": untouched,
            "no_part_left": not [p for p in after if p.name.endswith(".part")],
            "every_sha": want and want <= state_shas(wd),
            "copied": len([p for p in after if p.suffix == ".jpg"]),
            "third_copy_runs": runs(wd, "copy") - copy_runs,
            "third_verify_runs": runs(wd, "verify") - verify_runs,
            "said": "copy: skipped (done)" in r3.stdout,
            "resume_line": "resume P" in r2.stdout,
            "out": (r2.stdout + r2.stderr)[-400:]}


@case
def a_copy_killed_after_a_rename_resumes_with_nothing_copied_twice():
    """⭐ M12 step 3, kill point 1: after `os.replace` of the first file, before
    the copy state records it. The re-run copies the rest, finds that file by
    SHA (same inode, same mtime), every source SHA is in the state, and a
    third run copies nothing and checks nothing again. ⛔ FAILS on 2c1bf34:
    there is no progress file, so a third run re-entered every stage."""
    f = resumed_copy("replace@1")
    ok = (f["r"][0] != 0 and f["r"][1:] == (0, 0) and f["killed_with"] >= 1
          and f["untouched"] and f["every_sha"] and f["no_part_left"]
          and f["third_copy_runs"] == 0 and f["third_verify_runs"] == 0
          and f["said"] and f["resume_line"])
    return ok, {k: v for k, v in f.items() if k != "out"} if not ok else ""


@case
def a_copy_killed_with_a_part_on_disk_resumes_clean():
    """⭐ M12 step 3, kill point 2: a leftover `.part` (killed after the bytes
    were written, before the hash). The re-run leaves no `.part`, every file
    is whole, nothing is copied twice. ⛔ FAILS on 2c1bf34 (no progress file)."""
    f = resumed_copy("copy2@1")
    ok = (f["r"][1:] == (0, 0) and f["parts"] == 1 and f["no_part_left"]
          and f["untouched"] and f["every_sha"] and f["third_copy_runs"] == 0
          and f["said"])
    return ok, {k: v for k, v in f.items() if k != "out"} if not ok else ""


@case
def finish_skips_the_pages_and_views_done_under_the_same_freeze():
    """M12 — a re-run of `finish --go` does not re-enter the pages and views
    done under this freeze; a re-lock (new key) runs them again. ⛔ FAILS on
    2c1bf34: every run entered both."""
    import photo_run
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = frozen_dump(tmp)
        key = photo_run.freeze_key(wd)
        for name in ("pages", "identify"):
            photo_progress.start(wd, name)
            photo_progress.finish(wd, name, key=key)
        same = stage_run("photo_run.py", "finish", wd, "--go")
        for name in ("pages", "identify"):
            photo_progress.update(wd, name, key="sha256:an-older-freeze")
        moved = stage_run("photo_run.py", "finish", wd, "--go")
        ok = (key and same.returncode == 0 and runs(wd, "pages") == 2
              and "skipped (done under this freeze)" in same.stdout
              and "per-batch pages (G6)" not in same.stdout
              and "per-batch pages (G6)" in moved.stdout)
        return ok, f"key={key} rc={same.returncode}/{moved.returncode} " \
                   f"pages runs={runs(wd, 'pages')} {same.stdout[-300:]!r}"


@case
def a_done_skip_never_hides_a_page_waiting_in_the_work_dir():
    """B1-5/B1-6 x M12. A batch page written in the work dir after the pages
    were marked done (`review --next-page` run by hand) moves neither the
    freeze hash nor the pack, so the freeze key holds. `finish --go` must
    still stop for it, as the freeze would (`memory-stops`), never copy past
    it as "done under this freeze". ⛔ FAILS without the memory-stops guard."""
    import photo_run
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = frozen_dump(tmp)
        key = photo_run.freeze_key(wd)
        for name in ("pages", "identify"):
            photo_progress.start(wd, name)
            photo_progress.finish(wd, name, key=key)
        (wd / "P-B01.md").write_text("<!-- sns-page: P-B01 -->\n", encoding="utf-8")
        same_key = photo_run.freeze_key(wd) == key
        got = stage_run("photo_run.py", "finish", wd, "--go")
        ok = (key and same_key and got.returncode == 3
              and "skipped (done under this freeze)" not in got.stdout
              and "still waiting for its answer" in got.stdout)
        return ok, f"key={key} same={same_key} rc={got.returncode} {got.stdout[-400:]!r}"


def jpeg(path, when, lat, lon):
    """A real JPEG with EXIF date and GPS, written by Pillow (no exiftool)."""
    from PIL import Image
    im = Image.new("RGB", (64, 48), (int(lat * 7) % 255, int(lon * 11) % 255, 90))
    exif = Image.Exif()
    exif[0x0110] = "T1"
    exif[0x010F] = "TestCam"
    exif.get_ifd(0x8769)[0x9003] = when

    def dms(v):
        d = int(v)
        m = int((v - d) * 60)
        return (d, m, round(((v - d) * 60 - m) * 60, 2))
    exif.get_ifd(0x8825).update({1: "N", 2: dms(lat), 3: "E", 4: dms(lon)})
    im.save(path, "JPEG", exif=exif)


def small_source(tmp, days=6, per_day=4):
    src = Path(tmp) / "raw" / "dumpz"
    src.mkdir(parents=True)
    for d in range(days):
        for i in range(per_day):
            jpeg(src / f"Z{d}_{i}.jpg", f"2023:06:{d + 1:02d} {9 + i:02d}:00:00",
                 40.5 + d, 10.25 + i * 0.01)
    return src


def collection(tmp):
    root = Path(tmp) / "work"
    root.mkdir()
    (root / "collection.json").write_text(json.dumps(
        {"collection": "z", "dest_root": str(Path(tmp) / "sorted")}))
    return root


def offline(log, answer="stub", **extra):
    return dict(PYTHONPATH=ROOT / "tests" / "offline", PHOTO_TEST_NET_ANSWER=answer,
                PHOTO_TEST_NET_LOG=log, **extra)


@case
def the_map_count_equals_the_requests_sent_and_counts_the_probe_apart():
    """⭐ G50 / SPEC §8 item 6 — the count is kept in the ONE Nominatim and
    the ONE Overpass request point: the network count equals the requests the
    stage really sent (the test harness logs each one), the probe is counted
    on its own, and a warm re-run sends 0 and counts cache hits. ⛔ FAILS on
    2c1bf34: no count existed."""
    with tempfile.TemporaryDirectory() as tmp:
        src, root, log = small_source(tmp), collection(tmp), Path(tmp) / "net.log"
        r = stage_run("photo_run.py", "--workdir-root", root, "prep", src, **offline(log))
        wd = root / src.name
        sent = [json.loads(x)["url"] for x in log.read_text().splitlines()]
        lookups = [u for u in sent if u.rstrip("/") != "https://nominatim.openstreetmap.org"]
        m = photo_progress.load(wd).get("map") or {}
        log.unlink()
        r2 = stage_run("photo_run.py", "cluster", wd, "--force", **offline(log))
        m2 = photo_progress.load(wd).get("map") or {}
        resent = log.read_text().splitlines() if log.exists() else []
        ok = (r.returncode == 0 and r2.returncode == 0 and lookups
              and m.get("cluster", {}).get("network") == len(lookups)
              and m.get("probe") == len(sent) - len(lookups) == 1
              and "map requests:" in r.stderr
              and m2["cluster"]["network"] == 0 == len(resent)
              and m2["cluster"]["cache"] > 0)
        return ok, f"rc={r.returncode}/{r2.returncode} sent={len(sent)} map={m} again={m2}"


@case
def a_cluster_killed_mid_lookups_keeps_what_it_was_answered():
    """⭐ M12 row 2 — killed after 12 lookups (the cache saves every 10), the
    re-run sends fewer requests than a whole run. ⛔ FAILS on 2c1bf34: the
    cache was written once, at the end, and the re-run sent every request
    again."""
    with tempfile.TemporaryDirectory() as tmp:
        src, root = small_source(tmp, days=14, per_day=2), collection(tmp)
        full = Path(tmp) / "full.log"
        stage_run("photo_run.py", "--workdir-root", root, "prep", src, **offline(full))
        whole = len(full.read_text().splitlines()) - 1
        (root / "geocode-cache.json").unlink()
        wd = root / src.name
        for name in ("batches.json", "batches.json.bak", photo_progress.PROGRESS_NAME):
            (wd / name).unlink(missing_ok=True)
        killed = Path(tmp) / "killed.log"
        r1 = stage_run("photo_run.py", "cluster", wd,
                       **offline(killed, **{photo_progress.FAULT_ENV: "map_lookup@12"}))
        again = Path(tmp) / "again.log"
        r2 = stage_run("photo_run.py", "cluster", wd, **offline(again))
        n_again = len(again.read_text().splitlines()) if again.exists() else 0
        ok = (r1.returncode != 0 and r2.returncode == 0
              and (root / "geocode-cache.json").exists() and whole > 12
              and n_again <= whole - 10)
        return ok, f"rc={r1.returncode}/{r2.returncode} whole={whole} re-run sent={n_again}"


@case
def a_map_outage_is_said_once_per_dump():
    """⭐ U6-4 — Overpass answers 502: `cluster` says the lookup failed and
    counts the 5xx answers and retries; the renders and the copy after it do
    not say it again. ⛔ FAILS on 2c1bf34: every render and the copy said it."""
    with tempfile.TemporaryDirectory() as tmp:
        src, root, log = small_source(tmp, days=2, per_day=3), collection(tmp), \
            Path(tmp) / "net.log"
        r = stage_run("photo_run.py", "--workdir-root", root, "prep", src,
                      **offline(log, answer="overpass502"))
        wd = root / src.name
        m = (photo_progress.load(wd).get("map") or {}).get("cluster_by_service", {})
        said_cluster = (r.stdout + r.stderr).count("landmark lookup failed")
        import photo_cluster
        bdata = json.loads((wd / "batches.json").read_text())
        later = [photo_cluster.landmark_failed_once(bdata["batches"], wd) for _ in range(3)]
        ok = (r.returncode == 0 and said_cluster >= 1 and later == [None] * 3
              and m.get("overpass", {}).get("http_5xx", 0) >= 2
              and m["overpass"]["retries"] >= 1 and m["overpass"]["failed"] >= 1)
        return ok, f"rc={r.returncode} said={said_cluster} later={later} map={m}"


@case
def a_second_prep_refuses_before_it_rewrites_the_manifest():
    """⭐ M12 row 1 — `prep` on a dump that has batches.json stops, says the
    next command, and leaves manifest.csv byte-identical. ⛔ FAILS on 2c1bf34:
    it re-scanned and rewrote the manifest, then stopped at cluster."""
    with tempfile.TemporaryDirectory() as tmp:
        src, root, log = small_source(tmp, days=2, per_day=2), collection(tmp), \
            Path(tmp) / "net.log"
        stage_run("photo_run.py", "--workdir-root", root, "prep", src, **offline(log))
        manifest = root / src.name / "manifest.csv"
        before = (manifest.read_bytes(), manifest.stat().st_mtime_ns)
        r = stage_run("photo_run.py", "--workdir-root", root, "prep", src, **offline(log))
        after = (manifest.read_bytes(), manifest.stat().st_mtime_ns)
        ok = (r.returncode != 0 and before == after
              and "already scanned and clustered" in r.stderr
              and "The next step:" in r.stderr and "photo_embed.py" in r.stderr)
        return ok, f"rc={r.returncode} same={before == after} {r.stderr[-300:]!r}"


@case
def the_estimate_uses_this_machines_last_rate_and_says_its_basis():
    """G11 step 4 — a rate recorded by another dump of this collection on
    this machine gives the next dump's estimate before its pass; the basis
    names it; a stage never timed is left out and said. Never a constant.
    A GUARD of photo_progress itself, which 2c1bf34 does not have."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old, new = root / "dump-old", root / "dump-new"
        old.mkdir()
        new.mkdir()
        photo_progress.start(old, "embed")
        rec = photo_progress.finish(old, "embed", items=100)
        data = photo_progress.load(old)
        data["stages"]["embed"].update(rate_s=0.5, seconds=50.0)
        photo_progress.save(old, data)
        line = photo_progress.picture_estimate(new, 3600)
        est = photo_progress.load(new)["estimates"][0]
        ok = (line.startswith("Picture pass: 3600 photos, about 30 min (rate 0.50 s/photo")
              and "dump-old" in line and "identity not timed yet" in line
              and est["seconds"] == 1800 and rec["machine"] == photo_progress.machine()
              and photo_progress.picture_estimate(Path(tmp) / "elsewhere" / "d", 10) is None)
        return ok, line


def images(src, n):
    from PIL import Image
    src.mkdir(parents=True)
    for i in range(n):
        Image.new("RGB", (64, 64), ((i * 37) % 255, (i * 91) % 255, (i * 13) % 255)) \
            .save(src / f"E{i:03d}.jpg", "JPEG")


@case
def an_embed_killed_between_batches_resumes_where_it_stopped():
    """⭐ M12 step 3, kill point 3 (mid-embed, between two saves): the re-run
    embeds only the files after the last save, the progress file says done
    with 2 runs, every file is in the index once, and the estimate line was
    printed from this run's timed sample. ⛔ FAILS on 2c1bf34: no progress
    file and no estimate (the resume itself is older and is guarded)."""
    with tempfile.TemporaryDirectory() as tmp:
        wd = Path(tmp) / "work" / "dumpe"
        wd.mkdir(parents=True)
        src = Path(tmp) / "raw"
        images(src, 70)
        import csv
        with open(wd / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, ["SourceFile", "FileName", "FileType"])
            w.writeheader()
            w.writerows({"SourceFile": str(p), "FileName": p.name, "FileType": "JPEG"}
                        for p in sorted(src.iterdir()))
        r1 = stage_run("photo_embed.py", wd, **{photo_progress.FAULT_ENV: "embed_saved@1"})
        mid = photo_progress.stage(wd, "embed")
        r2 = stage_run("photo_embed.py", wd)
        summary = json.loads(r2.stdout[r2.stdout.index("{"):r2.stdout.rindex("}") + 1])
        with open(wd / "embed" / "embeddings.csv", newline="") as f:
            indexed = [r["SourceFile"] for r in csv.DictReader(f)]
        done = photo_progress.stage(wd, "embed")
        ok = (r1.returncode == KILLED and mid.get("state") == "running"
              and mid.get("done") == 32 and r2.returncode == 0
              and summary["already_embedded"] == 32 and summary["newly_embedded"] == 38
              and len(indexed) == len(set(indexed)) == 70
              and done.get("state") == "done" and done.get("runs") == 2
              and "Picture pass: 70 photos" in r1.stdout
              and "SAFE TO COMPACT" in r2.stdout)
        return ok, f"rc={r1.returncode}/{r2.returncode} mid={mid} summary={summary}"


@case
def a_see_pass_stopped_between_batches_says_the_next_batch():
    """⭐ M12 step 3, kill point 4 (mid-see, between batches): after batch 1's
    labels, the session ends; the progress file holds see as running 1/2 and
    the one next command is batch 2's selection — never batch 1 again, which
    refuses. After batch 2 the stage is done and the next command is finish.
    ⛔ FAILS on 2c1bf34: no progress file and no next command."""
    import photo_run
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd, _pack = ix.g3_dump(tmp, seen=())
        ix.run("init", wd)
        (wd / "embed" / "embeddings.npy").write_bytes(b"")
        batch1 = wd / "classify" / "batch-01"
        batch1.mkdir(parents=True)
        (batch1 / "see-report.json").write_text("{}")
        (batch1 / "see-labels.json").write_text('{"labels": []}')
        import photo_see
        with contextlib.redirect_stdout(io.StringIO()):
            photo_see.see_tick(wd, 1, "applied")
        mid = photo_progress.stage(wd, "see")
        nxt = photo_run.next_command(wd)
        batch2 = wd / "classify" / "batch-02"
        batch2.mkdir(parents=True)
        (batch2 / "see-labels.json").write_text('{"labels": []}')
        photo_see.see_tick(wd, 2, "applied")
        end = photo_progress.stage(wd, "see")
        ok = (mid.get("state") == "running" and (mid.get("done"), mid.get("total")) == (1, 2)
              and nxt.endswith(f'"{wd}" --batch 2') and "photo_see.py" in nxt
              and end.get("state") == "done"
              and photo_run.next_command(wd).endswith(f'finish "{wd}" --go'))
        return ok, f"mid={mid} next={nxt!r} end={end.get('state')}"


def stopped_copy(sig, to):
    """Start `finish --go` the C-23 way (its own session, SIGINT IGNORED as a
    script's `cmd &` leaves it), let P1 copy one slow file, send `sig` to the
    conductor (`pid`), its whole group (`group`: Ctrl-C, a closed window) or
    the copy stage only (`child`), then run finish again. -> facts."""
    import signal
    import time
    with tempfile.TemporaryDirectory() as tmp, ix.no_env():
        wd = frozen_dump(tmp)
        log = Path(tmp) / "finish-1.log"
        cmd = [PY, str(SCRIPTS / "photo_run.py"), "finish", str(wd), "--go", "--skip-memory"]
        with open(log, "w") as out:
            proc = subprocess.Popen(
                cmd, stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN),
                env=env(PYTHONPATH=ROOT / "tests" / "kill", PHOTO_TEST_SLOW_COPY=1.0))
            t_end = time.time() + 120
            while time.time() < t_end and proc.poll() is None and not [
                    p for p in dest_files(tmp) if p.suffix == ".jpg"]:
                time.sleep(0.05)
            if to == "pid":
                os.kill(proc.pid, getattr(signal, sig))
            elif to == "group":
                os.killpg(proc.pid, getattr(signal, sig))
            else:
                kids = subprocess.run(["pgrep", "-P", str(proc.pid)],
                                      capture_output=True, text=True).stdout.split()
                for k in kids:
                    os.kill(int(k), getattr(signal, sig))
            rc1 = proc.wait(timeout=120)
        out1 = log.read_text()
        before = dest_files(tmp)
        copy1, verify1 = (photo_progress.stage(wd, "copy"), photo_progress.stage(wd, "verify"))
        status = stage_run("photo_run.py", "status", wd).stdout
        resume = status.split("resume with:\n", 1)[-1].strip()
        r2 = finish(wd)
        after = dest_files(tmp)
        want = {sha(s) for s in plan_sources(wd)}
        return {
            "rc": (rc1, r2.returncode),
            "copied_before": len([p for p in before if p.suffix == ".jpg"]),
            "p2_started": "===== P2" in out1,
            "stopped_said": "STOPPED (" in out1,
            "resume_said": bool(resume) and f"resume with:\n    {resume}" in out1,
            "copy_state": copy1.get("state"), "verify_ran": bool(verify1),
            "parts": [p.name for p in before if p.name.endswith(".part")],
            "untouched": all(after.get(p) == v for p, v in before.items()),
            "every_sha": bool(want) and want <= state_shas(wd),
            "no_part_left": not [p for p in after if p.name.endswith(".part")],
            "out": out1[-600:]}


def stop_ok(f):
    ok = (f["rc"] == (STOPPED, 0) and 1 <= f["copied_before"] < 3
          and not f["p2_started"] and f["stopped_said"] and f["resume_said"]
          and f["copy_state"] == "running" and not f["verify_ran"]
          and not f["parts"] and f["untouched"] and f["every_sha"]
          and f["no_part_left"])
    return ok, "" if ok else {k: v for k, v in f.items()}


@case
def a_sigint_to_a_background_started_run_ends_the_whole_run():
    """⭐ G58 / C-23, the measured shape: `finish --go` started with SIGINT
    ignored (a script's `cmd &`), `kill -INT <pid>` mid-plan. The run ends
    with 130 after the file in hand, P2 never starts, verify never runs, copy
    stays running, the resume command is printed; the re-run copies only what
    is missing. ⛔ FAILS on 7280c54: the SIGINT is ignored, every plan runs."""
    return stop_ok(stopped_copy("SIGINT", "pid"))


@case
def a_ctrl_c_to_the_run_group_ends_the_whole_run():
    """⭐ G58: Ctrl-C (SIGINT to the whole group) in the same shape."""
    return stop_ok(stopped_copy("SIGINT", "group"))


@case
def a_sigterm_to_the_run_ends_the_whole_run():
    """⭐ G58: `kill <pid>` (SIGTERM) to the conductor only. ⛔ FAILS on
    7280c54: the conductor dies at once and the orphaned copy goes on."""
    return stop_ok(stopped_copy("SIGTERM", "pid"))


@case
def a_closed_window_sighup_ends_the_whole_run():
    """⭐ G58: the window closed (SIGHUP to the whole group)."""
    return stop_ok(stopped_copy("SIGHUP", "group"))


@case
def a_stop_of_the_copy_stage_alone_starts_no_next_plan():
    """⭐ G58 / C-23 cause 2: SIGTERM to photo_execute only (`pkill -P`). ⛔
    FAILS on 7280c54: the plan's non-zero rc is only flagged and the next
    plan starts."""
    return stop_ok(stopped_copy("SIGTERM", "child"))


@case
def a_kill_9_mid_plan_resumes_with_nothing_copied_twice():
    """⭐ G58: `kill -9` of the whole group mid-plan (nothing can be caught).
    The re-run finishes with 0, every source SHA is in the state, no file on
    the drive before the re-run was written again, no `.part` is left."""
    f = stopped_copy("SIGKILL", "group")
    ok = (f["rc"] == (-9, 0) and f["copied_before"] >= 1 and f["untouched"]
          and f["every_sha"] and f["no_part_left"])
    return ok, "" if ok else {k: v for k, v in f.items()}


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
            print(f"  {'ok  ' if ok else 'FAIL'}  {fn.__name__.replace('_', ' ').ljust(width)}"
                  + (f"   {detail}" if not ok else ""))
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} long-run cases passed"
          + ("" if not failures else f" — FAILED: {', '.join(failures)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
