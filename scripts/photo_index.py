#!/usr/bin/env python3
"""photo-index — the per-dump INDEX (Wave 3, D-I5 / D-I17).

  python3 photo_index.py init   "<Working Files>/<dump>" [--profile <pack>]
                                [--dump-key KEY]                       (G2)
  python3 photo_index.py view   "<Working Files>/<dump>" [--profile <pack>]
  python3 photo_index.py render "<Working Files>/<dump>" [--no-vision]  (G3)
  python3 photo_index.py check  "<Working Files>/<dump>"
  python3 photo_index.py dest   "<Working Files>/<dump>" F003 merge|fill_shell
                                "<existing folder>" [--ref <its work dir>]
                                --reason "..."                 (D6; `new` undoes)
  python3 photo_index.py freeze "<Working Files>/<dump>" [--replace-plans] [--reason "..."]
  python3 photo_index.py verify "<Working Files>/<dump>" [--copied]
  python3 photo_index.py unfreeze "<Working Files>/<dump>" --reason "..."
  python3 photo_index.py recut  "<Working Files>/<dump>" [--reason "..."]  (G4)
  python3 photo_index.py relabel "<Working Files>/<dump>" [--go] [--reason "..."]
  python3 photo_index.py group make-trip "<Working Files>/<dump>" F008 F009 ...
                                --where "<place>" [--what "..."] --reason "..."  (G5)
  python3 photo_index.py group make-fsl-month "<dump>" fsl-0003 2024-12 --reason "..."
  python3 photo_index.py group move  "<dump>" F021 --to F023 --dates 2024-12-11 --reason "..."
  python3 photo_index.py group split "<dump>" F011 --at 2024-10-30 --reason "..."
  python3 photo_index.py group merge "<dump>" F034 --into F033 --reason "..."
  python3 photo_index.py group set-what "<dump>" F044 "<text>" --reason "..." | --clear

`group` (D-I8) is how the agent changes the folder structure, each change with a
reason in the log: day folders become the LEGS of a trip parent or of a monthly
parent for one named frequent place (D-I12; it sits beside the month's other
folders, D-I14); whole days move, split off or merge; a folder takes the agent's
own `[what]`. Every change is by DATE: `photo_plan.route()` stays the only
router — a parent exports as ONE plan whose legs are date ranges, and a day a
folder of another plan holds is an override with a string destination. A file
whose route is not `copy` never moves (G10).

`recut` (D-I1) cuts the batches again with the owner's answers — right after
onboarding, BEFORE any vision pass — and re-homes every file: file ids kept, a
folder whose files are unchanged keeps its id, any other is retired and a new
id issued, every move logged, cluster generation + 1, phase `onb`. It refuses
once anything keyed by a batch NUMBER exists (U3-11) and names each kind.
`relabel` changes no batch: it puts the owner's labels on the folders' place
refs from the day centroids in manifest.csv, read at run time and never
stored, with the geocoder OFF. It is allowed after vision.

The order: see → the batch pages and the agent's identify views (a confirm moves
the pack id) → group → render → check → freeze → `photo_run.py finish --go`,
which copies only from a freeze
that still holds: the same index, the same exported plan files, the same pack.
`freeze` writes plans.json and the plan CSVs by running photo_plan itself,
checks every row against the index, and records one hash over the index and
those files, the pack id, and the SHA-256 of every file to be copied.

`render` settles every file's route with the plan stage's own code
(`photo_plan.settle_rows()` / `settle_no_date_rows()`, against a placeholder
destination, writing nothing) and renders every live folder's name with
`photo_name.render()`: the period from the copied member files' dates, `[where]`
from the place refs, `[who]` from the members' CONFIRMED subjects at
`viewed-image:` (the F12 rule, never a `draft:`), and `[what]` from
`photo_plan.name_phrase()` unless the folder carries its own. init's routes are
provisional; render replaces each one and logs every disagreement.

`index.json` is the ONLY truth; `Index_pscan.md` is a view regenerated from it
after every command and never read back. Both live in the owner PACK, one pair
per dump — `<pack>/photo-index/<dump key>/` — beside the rest of the owner's
photo memory. `photo-index` is not one of `photo_profile.SNAPSHOT_PARTS`, so
writing it never moves the pack id (an open review page stays valid).

`init` (phase pscan00) lists every manifest file, one `day` folder per batch,
and a bucket folder per (bucket key, month) for the routes it may decide. It
decides only the four PACK-INDEPENDENT rules — no date (D13), a sidecar (T0),
an unknown format (D13), a screenshot by FILENAME (T1) — in the order the
engine already applies them. Every other file is `route: null`: dupes need a
plan's destination and paperwork needs the embed stage, and both are decided
by `photo_plan.route()` itself in G3, never by a second rule here. No class
(own / shared) is recorded: with no pack yet, 249 of 291 files of a real dump
read `shared`.

The dump key is the work dir's folder name at the FIRST init, recorded in
`index.json` and in `<work dir>/index-pointer.json`. Later commands read the
pointer and never re-derive the key from a path that can move.

⛔ No coordinate anywhere in either file. A batch `place` that is a raw
   coordinate (photo_cluster writes one when no day could be named) is dropped.
⛔ No pack -> nothing written anywhere, one line, exit 0.

Open for G3/G6, not built: `sha256` is null until G3's freeze. A source folder
that is re-split changes `SourceFile`, so the same bytes read as one missing
file plus one new file with a FRESH `file_id`; anything that pointed at the old
id (G6's `pages[].rows`) then points at a `missing` row. Re-linking the two
needs the SHA, so the two questions are one.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import photo_cluster  # noqa: E402
import photo_evidence  # noqa: E402
import photo_execute  # noqa: E402
from photo_platform import path_key  # noqa: E402
import photo_name  # noqa: E402
import photo_plan  # noqa: E402
import photo_profile  # noqa: E402
import photo_sample  # noqa: E402
import photo_scan  # noqa: E402

INDEX_VERSION = 2
INDEX_DIR = "photo-index"
INDEX_NAME = "index.json"
VIEW_NAME = "Index_pscan.md"
POINTER_NAME = "index-pointer.json"
PHASE_INIT = "pscan00"
COORDINATE = re.compile(r"^\s*-?\d{1,3}(\.\d+)?\s*,\s*-?\d{1,3}(\.\d+)?\s*$")

# A route init decided before any plan code ran, versus one render settled with
# photo_plan.route() itself. Only a settled route counts (G10).
PROVISIONAL = "provisional:"
SETTLED = "settled:"
# render routes every file against this root; nothing is ever written under it.
PLACEHOLDER_ROOT = "/.photo-index-render"
ROUTE_COPY = "copy"
BUCKET_ROUTE = {"screenshots": "screenshot", "to_be_checked": "to_be_checked",
                "others": "others", "ai_images": "ai_images"}
COPIED = {ROUTE_COPY, *BUCKET_ROUTE.values()}
PHASE_FINAL = "final"
# After `recut` (D-I1): the batches were cut again with the owner's answers.
PHASE_ONB = "onb"
RETIRED = "retired"
# plans.json written by freeze carries this; a plans.json without it is a
# hand-written one, which freeze never overwrites unasked.
GENERATED_BY = "photo_index"
# `verify` exits with this when the freeze does not hold; photo_run's finish
# passes it on (nothing copied).
EXIT_STALE = 4
# F-mm / F-bb (Card 6): `verify --copied` when the ONLY change since the
# freeze is the owner pack (a later dump's onboarding, an end-of-dump page).
# The copy check still ran and every copied file matches; the names may
# differ on a re-lock. Never 0 (the freeze does not hold) and never 4 (the
# drive is fine).
EXIT_PACK_MOVED = 6
# What a plan run leaves in plan/; moved aside with a hand-written plans.json.
PLAN_OUTPUTS = ("plan_P*.md", "plan_P*-files.csv", "plan_no-date*",
                "execute-state_*.json", "execution-log_*.md")

# G5 (D-I8) — the kinds a copied file sits in, and the kinds that hold them.
HOLDERS = ("day", "leg")
PARENTS = ("trip", "fsl-month")
AGENT = "agent"
# A place word the agent gave (make-trip --where, R5). Never a label from the
# pack and never re-resolved by relabel.
AGENT_REF = "agent:"
FSL_REF = re.compile(r"^fsl-\d{4,}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GROUP_CMD = "index group"
GROUP_STRUCTURE = ("make-trip", "make-fsl-month", "move", "split", "merge")
# R4 (owner ruling) — the fewest visits in one month that make a monthly
# parent: a pack key, 3 by default. A pack may lower it to the floor of 2.
MIN_VISITS_KEY = "fsl_month_min_visits"
FSL_MONTH_MIN_VISITS_DEFAULT = 3
FSL_MONTH_MIN_VISITS_FLOOR = 2


class Refused(SystemExit):
    pass


# ---------------------------------------------------------------------------
# reading the dump
# ---------------------------------------------------------------------------

def date_source(row, tag):
    """G11 — which rule gave this file its date. `tag` is the column
    `photo_cluster.parse_date_source()` read."""
    if tag is None:
        return None
    if tag == "CreateDateLocal":
        # photo_scan wrote it from the video's own CreationDate when that
        # parses, else from the nearest still — the same test, reused.
        return ("creation_date" if photo_scan._stamp(row.get("CreationDate"))
                else "nearest_still")
    if tag == "CreateDate" and row.get("FileType") in photo_sample.VIDEO_TYPES:
        return "flagged"        # raw UTC stamp, no local time was derivable
    return "exif"


def init_route(row, dated, msg):
    """-> (route, route_source, bucket key) for the four pack-independent
    rules, in the engine's order, or (None, None, None) = not decided yet."""
    if not dated:
        # photo_plan.write_no_date_plan: every no-date file, before anything.
        return "to_be_checked", "D13-no-date", "to_be_checked"
    tier, cls = photo_sample.tier_of(row, None)
    if tier == "T0":
        return "skip_junk", "T0", None
    _name, _note, known = photo_plan.dest_name(row, msg)
    if not known:
        return "others", "D13-format", "others"
    if tier == "T1" and photo_sample.SCREENSHOT_NAME.match(row.get("FileName", "")):
        return "screenshot", "T1-name", "screenshots"
    return None, None, None


def place_labels(pack):
    """label -> [ids] for every home and named place that HAS an id (G1)."""
    out = {}
    for row in photo_profile.labelled_home_points(pack.profile):
        if row[4] and row[5]:
            out.setdefault(row[4], []).append(row[5])
    for row in photo_profile.named_places(pack):
        if row[2] and row[3]:
            out.setdefault(row[2], []).append(row[3])
    return out


def place_refs(place, labels, places, said):
    """A batch `place` string -> [{"ref"}], filling `places`. -> (refs,
    coordinate dropped?)."""
    if not place:
        return [], False
    if COORDINATE.match(place):
        return [], True
    refs = []
    for word in (w.strip() for w in place.split("+")):
        if not word:
            continue
        ids = labels.get(word, [])
        if len(ids) == 1:
            ref = ids[0]
            places.setdefault(ref, {"kind": ref.split("-")[0],
                                    "label_from": "pack"})
        else:
            if len(ids) > 1 and word not in said:
                said.add(word)
                print(f"⚠️ {len(ids)} places in the pack share the label "
                      f"{word!r}; the index keeps it as a map word", file=sys.stderr)
            ref = f"map:{word}"
            places.setdefault(ref, {"kind": "map", "text": word})
        if ref not in [r["ref"] for r in refs]:
            refs.append({"ref": ref})
    return refs, False


# ---------------------------------------------------------------------------
# locating the index
# ---------------------------------------------------------------------------

def index_dir(pack, key):
    return Path(pack.dir) / INDEX_DIR / key


def read_pointer(workdir):
    path = Path(workdir) / POINTER_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def resolve(workdir, profile):
    """-> the pack, or None when no pack is bound (said in one line)."""
    pack = photo_profile.resolve_pack(workdir=workdir, explicit=profile)
    if pack.dir is None:
        print("no owner pack bound to this dump — no index written (a dump "
              "with no pack is legal, and every benchmark is one)")
        return None
    return pack


def write_json(path, data):
    tmp = Path(f"{path}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def index_hash(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def build(workdir, pack, key, old):
    """-> the pscan00 index, keeping `old`'s file ids and log."""
    data = json.loads((workdir / "batches.json").read_text(encoding="utf-8"))
    batches = data.get("batches", [])
    with open(workdir / "manifest.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    in_batch = {r["SourceFile"]: r["_batch"]
                for r in photo_plan.collect_rows(workdir, batches)}
    msg = photo_profile.messages({})
    # ⛔ M14 (ii), Lead 20260922 — init CALLS photo_plan's no-date routing, it
    # does not copy it. It used to key every no-date file by the dump's month
    # itself; render then moved each one into its real bucket and logged a
    # "disagreement" per file (257 on the largest real import, each reading
    # `to_be_checked → to_be_checked`), which teaches a reader that a
    # disagreement can mean nothing. Asking the same function render asks
    # makes the two agree by construction.
    names = photo_profile.buckets(pack.profile)
    words = {w: k for k, w in names.items()}
    by_file_date = photo_plan.routes_by_file_date(rows)

    labels, places, said, dropped = place_labels(pack), {}, set(), 0
    folders, day_folder = [], {}
    for b in batches:
        refs, coord = place_refs(b.get("place"), labels, places, said)
        dropped += coord
        fid = f"F{len(folders) + 1:03d}"
        day_folder[b["batch"]] = fid
        folders.append(new_folder(fid, "day", where=refs, batches=[b["batch"]]))

    old_files = {f["source"]: f for f in (old or {}).get("files", [])}
    next_id = int((old or {}).get("file_id_next") or 1)
    buckets, files, seen = {}, [], set()
    for row in sorted(rows, key=lambda r: r["SourceFile"]):
        src = row["SourceFile"]
        seen.add(src)
        when, tag = photo_cluster.parse_date_source(row)
        route, route_source, bucket_key = init_route(row, when is not None, msg)
        if route == "skip_junk":
            folder = None
        elif bucket_key:
            if when is None:
                bucket_key, month, _base = bucket_of(
                    photo_plan.no_date_dest(row, PLACEHOLDER_ROOT, names,
                                            workdir, by_file_date), words)
            else:
                month = when.strftime("%Y%m")
            if (bucket_key, month) not in buckets:
                buckets[(bucket_key, month)] = None
            folder = (bucket_key, month)
        else:
            folder = day_folder.get(in_batch.get(src))
        if src in old_files:
            file_id = old_files[src]["file_id"]
        else:
            file_id, next_id = f"f-{next_id:04d}", next_id + 1
        files.append({
            "file_id": file_id, "source": src, "sha256": None,
            "kind": ("video" if row.get("FileType") in photo_sample.VIDEO_TYPES
                     else "still"),
            "date": when.isoformat() if when else None,
            "date_source": date_source(row, tag),
            "batch": in_batch.get(src), "cluster_gen": 1,
            "route": route,
            "route_source": PROVISIONAL + route_source if route_source else None,
            "folder": folder, "dest_name": None, "who": [],
            "history": [], "status": "present"})

    # ⛔ The undated bucket has month None; a plain sort would compare None
    # with a string and crash the first time one sits beside a dated bucket.
    for bucket_key, month in sorted(buckets, key=lambda k: (k[0], k[1] or "")):
        fid = f"F{len(folders) + 1:03d}"
        buckets[(bucket_key, month)] = fid
        folders.append(new_folder(fid, "bucket", bucket_key=bucket_key,
                                  month=month))
    for f in files:
        if isinstance(f["folder"], tuple):
            f["folder"] = buckets[f["folder"]]
        f["history"] = [{"phase": PHASE_INIT, "folder": f["folder"]}]
    for src, f in old_files.items():
        if src not in seen:
            gone = dict(f, status="missing", folder=None, route=None,
                        route_source=None)
            gone["history"] = list(f.get("history", [])) + [{
                "phase": PHASE_INIT, "folder": None,
                "reason": "not in the manifest at this init"}]
            files.append(gone)
    files.sort(key=lambda f: f["file_id"])

    present = sum(1 for f in files if f["status"] == "present")
    new = sum(1 for f in files if f["source"] not in old_files)
    missing = len(files) - present
    log = list((old or {}).get("log", [])) + [{
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"), "phase": PHASE_INIT,
        "by": "engine", "cmd": "index init",
        "change": (f"{present} file(s) in {len(folders)} folder(s); {new} new, "
                   f"{missing} missing"
                   + (f"; {dropped} coordinate place(s) dropped" if dropped else "")),
        "reason": "prescan"}]
    return {
        "index_version": INDEX_VERSION, "dump": key, "owner": pack.owner,
        "phase": PHASE_INIT, "cluster_gen": 1,
        "pack_fingerprint": (pack.snapshot() or {}).get("id"),
        "frozen": None, "workdir_name": workdir.name,
        "source": data.get("source"), "file_id_next": next_id,
        "places": places, "folders": folders, "files": files, "pages": [],
        "log": log}, dropped


def new_folder(fid, kind, where=(), bucket_key=None, month=None, batches=()):
    return {"id": fid, "kind": kind, "parent": None, "status": "proposed",
            "merged_into": None, "split_from": None,
            "dest": {"mode": "new", "existing_path": None, "refs": []},
            "where": list(where), "country": None, "what": None,
            "bucket_key": bucket_key, "month": month, "batches": list(batches),
            "days": None, "rendered": None, "validation": None}


def live(index):
    """Folders a file may sit in: every one a re-cut has not retired."""
    return [fo for fo in index["folders"] if fo["status"] != RETIRED]

# ---------------------------------------------------------------------------
# the folder structure (G5): holders, parents, the days each holder holds, and
# the plans the structure exports as
# ---------------------------------------------------------------------------

def holders(index):
    """Folders a copied file sits in: a day folder, or a leg of a parent."""
    return [fo for fo in live(index) if fo["kind"] in HOLDERS]


def parents(index):
    return [fo for fo in live(index) if fo["kind"] in PARENTS]


def legs_of(index, pid):
    return [fo for fo in holders(index) if fo.get("parent") == pid]


def batch_days(index):
    """batch -> the days its present, dated files were taken on."""
    out = {}
    for f in index["files"]:
        if f["status"] == "present" and f["batch"] is not None and f["date"]:
            out.setdefault(f["batch"], set()).add(f["date"][:10])
    return out


def claims(index):
    """holder id -> the days it holds. A holder with no `days` holds every day
    of its batches; one that shares a batch (after a split or a move by date)
    names its days."""
    days = batch_days(index)
    return {fo["id"]: (set(fo["days"]) if fo.get("days") else
                       set().union(set(), *(days.get(b, set())
                                            for b in folder_batches(index, fo))))
            for fo in holders(index)}


def write_claims(index, owned):
    """Store `owned` (holder id -> days) back as each holder's batches, and as
    its `days` only where it shares a batch or holds part of one."""
    days = batch_days(index)
    day_batch = {d: b for b, ds in days.items() for d in ds}
    by_id = {fo["id"]: fo for fo in index["folders"]}
    for fid, ds in owned.items():
        if ds:
            by_id[fid]["batches"] = sorted({day_batch[d] for d in ds if d in day_batch})
    uses = {}
    for fid, ds in owned.items():
        for b in by_id[fid]["batches"] if ds else ():
            uses.setdefault(b, set()).add(fid)
    for fid, ds in owned.items():
        fo = by_id[fid]
        if not ds:
            continue
        whole = set().union(set(), *(days.get(b, set()) for b in fo["batches"]))
        shared = any(len(uses.get(b, ())) > 1 for b in fo["batches"])
        fo["days"] = sorted(ds) if shared or ds != whole else None


def leg_range(fo, owned, by_number):
    """A leg's date range in its parent's plan: its batch span (R1), or its own
    days once it holds part of a batch."""
    if not fo.get("days"):
        spans = [(by_number[b]["from"], by_number[b]["to"])
                 for b in fo.get("batches") or [] if b in by_number]
        if spans:
            return min(s[0] for s in spans), max(s[1] for s in spans)
    days = sorted(owned.get(fo["id"]) or ())
    return (days[0], days[-1]) if days else (None, None)


def structure_problems(index, by_number):
    """-> what makes the structure unexportable: a day two folders hold, a leg
    with no live parent, a parent with no leg, and ⛔ legs of one parent whose
    ranges overlap — photo_plan gives a shared day to the FIRST leg and the
    other receives nothing, silently (measured, G5 case B)."""
    problems, owned, holder_of, pairs = [], claims(index), {}, {}
    for fid, days in owned.items():
        for d in sorted(days):
            other = holder_of.setdefault(d, fid)
            if other != fid:
                pairs.setdefault((other, fid), d)
    problems += [f"{a} and {b} both hold {d} — a day belongs to one folder"
                 for (a, b), d in sorted(pairs.items())]
    by_id = {fo["id"]: fo for fo in live(index)}
    for fo in holders(index):
        pid = fo.get("parent")
        if fo["kind"] == "leg" and (pid not in by_id or by_id[pid]["kind"] not in PARENTS):
            problems.append(f"{fo['id']} is a leg of {pid}, which is not a live parent")
    for p in parents(index):
        legs = [(leg_range(leg, owned, by_number), leg["id"])
                for leg in legs_of(index, p["id"])]
        if not legs:
            problems.append(f"{p['id']} is a parent with no leg")
        for i, ((a0, a1), ida) in enumerate(legs):
            for (b0, b1), idb in legs[i + 1:]:
                if a0 and b0 and a0 <= b1 and b0 <= a1:
                    problems.append(
                        f"{p['id']}: the legs {ida} ({a0} → {a1}) and {idb} "
                        f"({b0} → {b1}) overlap — photo_plan gives a shared day "
                        "to the first leg, the other receives nothing, and "
                        "nothing says so (R1)")
    return problems


def export_units(index, by_number):
    """-> one unit per top-level folder, in folder order: {"top", "batches",
    "legs": [(leg, from, to)], "overrides": [(days, holder)]}.

    ⛔ `photo_plan.route()` stays the only router. A parent is ONE plan whose
    legs are date ranges. A day held by a folder of ANOTHER plan (after a move
    or a split) is an override of the plan that reads its batch, with a STRING
    destination (photo_execute's allowlist cannot read a dict). Each batch is
    read by exactly one plan: the one whose folder holds the batch's first
    day. A unit with no batch exports no plan; its files arrive by override."""
    owned, days = claims(index), batch_days(index)
    by_id = {fo["id"]: fo for fo in index["folders"]}
    uses = {}
    for fo in holders(index):
        for b in fo.get("batches") or []:
            uses.setdefault(b, []).append(fo)
    primary = {}
    for b, users in uses.items():
        first = min(days.get(b) or {""})
        primary[b] = next((u for u in users if first in owned[u["id"]]), users[0])
    units = []
    for top in live(index):
        if not (top["kind"] in PARENTS or (top["kind"] == "day" and not top.get("parent"))):
            continue
        under = legs_of(index, top["id"]) if top["kind"] in PARENTS else [top]
        ids = {u["id"] for u in under}
        batches = sorted(b for b, p in primary.items() if p["id"] in ids)
        over = {}
        for b in batches:
            for u in uses[b]:
                if u is primary[b] or u["id"] in ids:
                    continue
                over.setdefault(u["id"], set()).update(owned[u["id"]] & days.get(b, set()))
        units.append({
            "top": top, "batches": batches,
            "legs": ([(leg, *leg_range(leg, owned, by_number)) for leg in under]
                     if top["kind"] in PARENTS else []),
            "overrides": [(sorted(ds), by_id[fid]) for fid, ds in over.items() if ds]})
    return units


def unit_paths(units, root, real):
    """folder id -> its destination: `root/<top>[/<leg>]`, by rendered name
    (`real`) or by id (render's placeholder); a merge or fill_shell top keeps
    the owner's existing folder."""
    paths = {}
    for u in units:
        top = u["top"]
        if real and top["dest"]["mode"] != "new":
            paths[top["id"]] = top["dest"]["existing_path"]
        else:
            paths[top["id"]] = f"{root}/{top['rendered'] if real else top['id']}"
        for leg, _a, _b in u["legs"]:
            paths[leg["id"]] = f"{paths[top['id']]}/{leg['rendered'] if real else leg['id']}"
    return paths


def unit_plan(u, n, paths, words=None):
    """The plans.json entry photo_plan routes a unit with. `words` (freeze
    only) adds the place words D-I13 compares."""
    top = u["top"]
    plan = {"plan": n, "batches": u["batches"],
            "dest": {"mode": top["dest"]["mode"], "path": paths[top["id"]]}}
    if top["dest"].get("refs"):
        plan["refs"] = top["dest"]["refs"]
    if words:
        plan["where"] = words(top)
    if u["legs"]:
        plan["legs"] = [dict({"from": a, "to": b, "name": Path(paths[leg["id"]]).name},
                             **({"where": words(leg)} if words else {}))
                        for leg, a, b in u["legs"]]
    if u["overrides"]:
        plan["overrides"] = [{"dates": ds, "dest": paths[h["id"]],
                              "reason": f"photo_index: days {h['id']} holds"}
                             for ds, h in u["overrides"]]
    return plan


def cmd_init(args):
    workdir = Path(args.workdir).resolve()
    for need in ("batches.json", "manifest.csv"):
        if not (workdir / need).exists():
            raise Refused(f"no {need} in {workdir} — run prep first")
    pack = resolve(workdir, args.profile)
    if pack is None:
        return 0

    pointer = read_pointer(workdir)
    if pointer:
        if pointer.get("owner") != pack.owner:
            raise Refused(f"this work dir's index belongs to owner "
                          f"{pointer.get('owner')!r}, not {pack.owner!r}")
        key = pointer["dump_key"]
        if args.dump_key and args.dump_key != key:
            raise Refused(f"this work dir's index is already {key!r}; "
                          "--dump-key cannot rename it")
    else:
        key = args.dump_key or workdir.name
    if not key or "/" in key or key in (".", ".."):
        raise Refused(f"not a usable dump key: {key!r}")

    target = index_dir(pack, key)
    old = None
    if (target / INDEX_NAME).exists():
        if not pointer:
            raise Refused(
                f"an index named {key!r} already exists in this pack and this "
                "work dir has none of its own. Two dumps would share one key — "
                "nothing written. Pass --dump-key <another name>.")
        old = json.loads((target / INDEX_NAME).read_text(encoding="utf-8"))
        if old.get("phase") != PHASE_INIT:
            raise Refused(f"this index is at phase {old.get('phase')!r}; init "
                          "only rebuilds an index no later phase has touched")
        # ⛔ render leaves the phase at pscan00 (only freeze and unfreeze move
        # it), so the phase test above never saw a rendered index, and a
        # re-init threw its routes, names and folder ids away in silence.
        rendered = [fo["id"] for fo in old.get("folders", []) if fo.get("rendered")]
        if old.get("render") or rendered:
            raise Refused(
                f"this index was rendered ({len(rendered)} folder name(s)"
                + (f", at {old['render']['at']}" if old.get("render") else "")
                + ") — init would throw the settled routes and names away and "
                "renumber the folders. Nothing written. A new cut of the batches "
                "goes through `photo_index.py recut`.")

    print(f"owner pack: {pack.dir}\nindex: {target}")
    index, dropped = build(workdir, pack, key, old)
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / INDEX_NAME, index)
    write_json(workdir / POINTER_NAME, {"owner": pack.owner, "dump_key": key})
    write_view(target, pack)

    files = [f for f in index["files"] if f["status"] == "present"]
    count = lambda field: sorted(  # noqa: E731
        {v: sum(1 for f in files if f[field] == v)
         for v in {f[field] for f in files}}.items(), key=str)
    print(f"{len(files)} file(s) in {len(index['folders'])} folder(s) "
          f"({sum(1 for f in index['folders'] if f['kind'] == 'day')} day, "
          f"{sum(1 for f in index['folders'] if f['kind'] == 'bucket')} bucket); "
          f"{sum(1 for f in index['files'] if f['status'] == 'missing')} missing")
    print("routes: " + ", ".join(f"{k or 'not decided'} {n}"
                                 for k, n in count("route")))
    print("date sources: " + ", ".join(f"{k or 'none'} {n}"
                                       for k, n in count("date_source")))
    if dropped:
        print(f"{dropped} batch place(s) were a coordinate and were dropped")
    unfiled = [f for f in files if f["folder"] is None and f["route"] != "skip_junk"]
    if unfiled:
        print(f"⚠️ {len(unfiled)} dated file(s) fall in no batch — they have no "
              "folder", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# shared by the G3 commands
# ---------------------------------------------------------------------------

def load(workdir, profile):
    """-> (pack, index dir, index), or None when no pack is bound (said)."""
    pack = resolve(workdir, profile)
    if pack is None:
        return None
    pointer = read_pointer(workdir)
    if not pointer:
        raise Refused(f"no index for {workdir} — run `photo_index.py init` first")
    if pointer.get("owner") != pack.owner:
        raise Refused(f"this work dir's index belongs to owner "
                      f"{pointer.get('owner')!r}, not {pack.owner!r}")
    target = index_dir(pack, pointer["dump_key"])
    if not (target / INDEX_NAME).exists():
        raise Refused(f"the pointer names {pointer['dump_key']!r} and there is "
                      f"no index under {target}")
    return pack, target, json.loads((target / INDEX_NAME).read_text(encoding="utf-8"))


def save(target, pack, index):
    write_json(target / INDEX_NAME, index)
    write_view(target, pack)


def log_entry(index, cmd, change, reason, by="engine"):
    index["log"].append({"at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                         "phase": index["phase"], "by": by, "cmd": cmd,
                         "change": change, "reason": reason})


def pack_id(pack):
    return (pack.snapshot() or {}).get("id")


def pack_env(pack):
    """The environment a stage subprocess needs to resolve THIS pack."""
    env = dict(os.environ)
    env[photo_profile.ENV_VAR] = str((pack.dir / photo_profile.PROFILE_NAME).resolve())
    return env


def id_labels(pack):
    """place id -> the label the pack holds for it NOW (None if unlabelled)."""
    labels = {}
    for row in photo_profile.labelled_home_points(pack.profile):
        if row[5]:
            labels[row[5]] = row[4]
    for row in photo_profile.named_places(pack):
        if row[3]:
            labels[row[3]] = row[2]
    return labels


def folder_batches(index, fo):
    """A day folder's batches: recorded since G3; for an index init'd before,
    read back from each file's first (pscan00) folder."""
    if fo.get("batches"):
        return fo["batches"]
    return sorted({f["batch"] for f in index["files"]
                   if f["batch"] is not None and f.get("history")
                   and f["history"][0].get("folder") == fo["id"]})


def freeze_hash(workdir, index, rels):
    """One hash over the index (less its `frozen` record and its log, which
    later commands append to) and every exported plan file, in order."""
    body = {k: v for k, v in index.items() if k not in ("frozen", "log")}
    h = hashlib.sha256(json.dumps(body, sort_keys=True,
                                  ensure_ascii=False).encode("utf-8"))
    for rel in rels:
        h.update(b"\0" + rel.encode("utf-8") + b"\0")
        h.update((workdir / rel).read_bytes())
    return "sha256:" + h.hexdigest()


def freeze_problem(workdir, pack, index, ignore_pack=False):
    """-> None while the freeze holds, else why it does not. `ignore_pack`
    asks about everything but the owner pack (verify --copied)."""
    frozen = index.get("frozen")
    if not frozen:
        return "the index is not frozen"
    now = pack_id(pack)
    if now != frozen["pack_fingerprint"] and not ignore_pack:
        return (f"the owner pack changed since the freeze "
                f"({frozen['pack_fingerprint']} → {now}: a confirm, a rename or "
                "a pack edit)")
    gone = [rel for rel in frozen["files"] if not (workdir / rel).is_file()]
    if gone:
        return f"an exported plan file is gone: {gone[0]}"
    if freeze_hash(workdir, index, frozen["files"]) != frozen["hash"]:
        return "the index or an exported plan file changed since the freeze"
    return None


def lift(index, cmd, reason, by="engine"):
    frozen = index["frozen"]
    index["phase"] = frozen.get("phase_before") or index["phase"]
    index["frozen"] = None
    log_entry(index, cmd, f"freeze {frozen['hash']} lifted", reason, by=by)


def open_for_change(workdir, pack, index, cmd):
    """D-I16: a freeze that still holds locks the names — refuse. A stale one
    locks nothing the copy would accept any more; lift it, logged."""
    if not index.get("frozen"):
        return
    why = freeze_problem(workdir, pack, index)
    if why is None:
        raise Refused("the index is frozen and the freeze still holds (D-I16) — "
                      "nothing changed. Lift it first, with a reason:\n"
                      f"  {run_line('photo_index.py')} unfreeze \"{workdir}\" "
                      "--reason \"...\"")
    lift(index, cmd, f"the freeze was stale: {why}")


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def next_folder_id(index):
    return f"F{max((int(fo['id'][1:]) for fo in index['folders']), default=0) + 1:03d}"


def bucket_folder(index, key, month):
    for fo in live(index):
        if fo["kind"] == "bucket" and (fo["bucket_key"], fo["month"]) == (key, month):
            return fo
    fo = new_folder(next_folder_id(index), "bucket", bucket_key=key, month=month)
    index["folders"].append(fo)
    return fo


def bucket_of(dest, words):
    """photo_plan's bucket destination -> (bucket key, month, folder name),
    read off the string the plan code built — never a second rule. `month` is
    YYYYMM, or the dump's year span for an undated archive's no-date bucket."""
    # M14 / owner ruling Q10 — the ONE two-level bucket, `_<word>/<import>`:
    # the undated no-EXIF stills. It has NO month (month None), and its
    # rendered name keeps the `/`. ⛔ Exactly two components and an underscore
    # word the pack knows; anything else still falls through to the one-level
    # rule below and is refused. `check` then admits the `/` only when the name
    # equals `photo_plan.undated_rel()` for THIS index — the parse here is not
    # the gate.
    if dest.startswith(PLACEHOLDER_ROOT + "/"):
        parts = dest[len(PLACEHOLDER_ROOT) + 1:].split("/")
        if (len(parts) == 2 and parts[0].startswith("_")
                and parts[0][1:] in words and parts[1]):
            return words[parts[0][1:]], None, "/".join(parts)
    parent, _, base = dest.rpartition("/")
    prefix, _, word = base.partition("_")
    if parent != PLACEHOLDER_ROOT or word not in words:
        raise Refused(f"render cannot place the destination {dest!r}: a route "
                      "this index does not know")
    month = prefix[:6] if re.fullmatch(r"\d{6}00", prefix) else prefix
    return words[word], month, base


def run_dedupe(workdir, fo, pack):
    """OA-3: a folder that merges into or fills an existing one is deduped
    against that folder's own manifest before its routes are settled."""
    cmd = [sys.executable, str(HERE / "photo_dedupe.py"), str(workdir),
           "--batches", ",".join(str(n) for n in fo["batches"])]
    for ref in fo["dest"]["refs"]:
        cmd += ["--ref", ref]
    r = subprocess.run(cmd, capture_output=True, text=True, env=pack_env(pack))
    if r.returncode:
        raise Refused(f"photo_dedupe failed for {fo['id']} — nothing rendered:\n"
                      + (r.stdout + r.stderr)[-600:])


def settle_file(index, f, r, path_ids, words):
    """One file's route, as photo_plan settled it. `path_ids` maps each
    holder's placeholder path to its id (None for the no-date plan)."""
    tags = "+".join(sorted(r.get("_tags") or ()))
    if r["_action"] == ROUTE_COPY and path_ids is not None and r["_dest"] in path_ids:
        route, folder = ROUTE_COPY, path_ids[r["_dest"]]
    elif r["_action"] == ROUTE_COPY:
        key, month, base = bucket_of(r["_dest"], words)
        bucket = bucket_folder(index, key, month)
        bucket["rendered"] = base
        route, folder = BUCKET_ROUTE[key], bucket["id"]
    else:
        route, folder = r["_action"], None
    f.update(route=route, folder=folder, dest_name=r["_name"],
             route_source=SETTLED + (tags or ("no-date" if path_ids is None else "plan")),
             dupe_of=r["_dest"] if route == "skip_dupe" else None)


def at_own_place(members, fo, parent, gps, homes):
    """FIX8 F8-7 (U6-28, owner decision "name from own place") — the members
    whose photo may give this folder its [who] and [what].

    A day is named after its last AWAY stop, so a day with photos at home and
    one outing takes the outing's place word while its home photos stay in it
    and lent it their pet's name. A photo taken at a home (inside
    `PLACE_SUPPRESS_KM`, the ring that already calls a stop home, nearest home
    first) counts only when that home is one of the folder's own places — a
    leg with none of its own uses its parent's. Nothing moves: the file stays
    in the folder and still sets its dates.

    A file with no GPS counts (owner ruling D3). ⚠️ Home against away only: an
    away photo at another away place still counts (0 cases measured)."""
    if not homes:
        return members
    refs = {r["ref"] for r in fo.get("where") or []}
    if not refs and parent is not None:
        refs = {r["ref"] for r in parent.get("where") or []}
    out = []
    for f in members:
        point = gps.get(f["source"])
        home = nearest_home(point, (f.get("date") or "")[:10], homes) if point else None
        if home is None or home[5] in refs:
            out.append(f)
    return out


def nearest_home(point, day, homes):
    """-> the `labelled_home_points()` row `point` sits at on `day`, or None."""
    near = [(photo_cluster.haversine_km(point, (h[0], h[1])), h) for h in homes
            if photo_cluster.within_home_range(point, day, [h[:4]],
                                               photo_cluster.PLACE_SUPPRESS_KM)]
    return min(near, key=lambda x: x[0])[1] if near else None


def who_order(key):
    """H-D (K25, owner ruling 20261003) — a pet's place in `[who]`: the order
    the registry minted its id, which is the order the owner named it on the
    `pets:` line, else the order it was first seen. Never the file count: that
    differs per folder, so two pets swapped places between folders. A subject
    with no id (keyed by name) has no mint time and goes after every id, by
    name. Digits compare as a number: ids are `subj-` + 4 OR MORE digits."""
    import photo_subjects
    m = photo_subjects.SUBJECT_ID_PATTERN.match(key or "")
    return (0, int(key[5:]), "") if m else (1, 0, key or "")


def backed_subjects(members, cells, keep=()):
    """F12 — who a folder may be named after: a CONFIRMED subject at a bare
    `viewed-image:`, on a file copied INTO it. -> [(key, name, kind, files)].

    Order: `keep` first — an ALREADY-COPIED folder's own earlier [who], so its
    name on the drive never needs a rename for the order alone ("new folders
    only", owner 20261004) — then every other subject by `who_order()`."""
    counts, names, kinds = {}, {}, {}
    for f in members:
        seen = set()
        for s in (cells.get(f["source"]) or {}).get(photo_plan.WHO_SUBJECTS) or []:
            if not (s["confirmed"]
                    and photo_evidence.is_view_confirmed(s["provenance"])):
                continue
            key = s.get("subject_id") or s["name"]
            if key in seen:
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
            names[key], kinds[key] = s["name"], s.get("kind")
    kept = [k for k in dict.fromkeys(keep) if k in counts]
    order = kept + sorted((k for k in counts if k not in kept), key=who_order)
    return [(k, names[k], kinds[k], counts[k]) for k in order]


def where_words(fo, labels):
    """-> (the words a folder's place refs render as, refs the pack cannot
    label)."""
    words, unknown = [], []
    for ref in (r["ref"] for r in fo["where"]):
        if ref.startswith("map:"):
            words.append(ref[4:])
        elif ref.startswith(AGENT_REF):
            words.append(ref[len(AGENT_REF):])
        elif labels.get(ref):
            words.append(labels[ref])
        else:
            unknown.append(ref)
    return words, unknown


def agent_what(fo):
    """The folder's own `[what]` (set-what, make-trip --what), or None."""
    return (fo.get("what") or {}).get("text")


def render_holder(fo, members, cells, spans, labels, budget, cap, profile, rmsg,
                  parent_words=None, own=None, keep=()):
    """-> (name, validation) for a day folder, or for a leg when
    `parent_words` (its parent's place words) is given: a leg names its place
    only when it differs from the parent's (D-I13). `own` is the members
    taken at the folder's own place (F8-7); [who] and [what] read only those."""
    hard, soft = budget
    own = members if own is None else own
    dates = sorted(f["date"][:10] for f in members if f["date"])
    if dates:
        start, end = dates[0], dates[-1]
    else:
        # Every file went to a bucket or was a duplicate. The folder still
        # exports — its plan copies its batch's bucket files — and photo_execute
        # creates no folder nothing lands in.
        start, end = min(s[0] for s in spans), max(s[1] for s in spans)
    where, unknown = where_words(fo, labels)
    backed = backed_subjects(own, cells, keep)
    who = (photo_plan.render_who([b[1] for b in backed], [b[2] for b in backed],
                                 cap, profile, rmsg) if backed else "")
    mine = {f["source"]: cells[f["source"]] for f in own if cells.get(f["source"])}
    pick = photo_plan.name_phrase(mine, who=who, hard=hard, soft=soft)
    own = agent_what(fo)
    validation = {"refusals": [], "warnings": [], "copies": len(members),
                  "who": [{"subject_id": k, "name": n, "files": c}
                          for k, n, _kind, c in backed],
                  "what_pick": pick["what"], "what_why": pick["why"],
                  "what_source": AGENT if own else pick.get("provenance"),
                  "what_animal_files": 0}
    if backed and not own and pick["what"]:
        # R7's evidence: frames behind the chosen [what] in which the see
        # stage found an animal. Read off the stage's own subjects — never a
        # word list.
        validation["what_animal_files"] = sum(
            1 for c in mine.values()
            if photo_plan.rests_on_a_look(c)
            and (c.get("what") or "").strip() == pick["what"]
            and c.get(photo_plan.WHO_SUBJECTS))
    if fo["dest"]["mode"] != "new":
        name = Path(fo["dest"]["existing_path"]).name
        _ok, ref, warn = photo_name.validate(name, hard=hard, soft=soft)
        validation["warnings"] = [f"the owner's own folder name, kept (D6): {w}"
                                  for w in ref + warn]
    elif parent_words is not None:
        name = photo_name.render(start, end,
                                 where=[] if where == parent_words else where,
                                 who=[who] if who else [], what=own or pick["what"],
                                 kind=photo_name.NAME_LEG)
        _ok, ref, warn = photo_name.validate(
            name, hard=hard, soft=soft, kind=photo_name.NAME_LEG,
            where=where, parent_where=parent_words)
        validation["refusals"], validation["warnings"] = ref, warn
    else:
        # A folder's own `what` (set-what) wins over the pick.
        name = photo_name.render(start, end, where=where,
                                 who=[who] if who else [],
                                 what=own or pick["what"])
        _ok, ref, warn = photo_name.validate(
            name, place_known=bool(fo["where"]), span=(start, end),
            hard=hard, soft=soft, kind=photo_name.NAME_FOLDER)
        validation["refusals"], validation["warnings"] = ref, warn
    validation["refusals"] += [f"the place {r} has no label in the owner pack"
                               for r in unknown]
    return name, validation


def render_parent(fo, members, labels, budget):
    """-> (name, validation) for a trip (period from its legs' files) or a
    monthly parent (`YYYYMM00_<the place's label>`). A parent's `[where]` is
    never derived and its `[what]` is only the agent's; its legs carry the
    rest."""
    hard, soft = budget
    dates = sorted(f["date"][:10] for f in members if f["date"])
    where, unknown = where_words(fo, labels)
    own = agent_what(fo)
    validation = {"refusals": [], "warnings": [], "copies": len(members), "who": [],
                  "what_pick": None, "what_why": None,
                  "what_source": AGENT if own else None, "what_animal_files": 0}
    if fo["kind"] == "fsl-month":
        name = photo_name.render(f"{fo['month'][:4]}-{fo['month'][4:6]}-01",
                                 where=where, what=own, kind=photo_name.NAME_MONTHLY)
        _ok, ref, warn = photo_name.validate(name, hard=hard, soft=soft,
                                             kind=photo_name.NAME_MONTHLY)
    elif dates:
        name = photo_name.render(dates[0], dates[-1], where=where, what=own)
        _ok, ref, warn = photo_name.validate(
            name, place_known=bool(fo["where"]), span=(dates[0], dates[-1]),
            hard=hard, soft=soft, kind=photo_name.NAME_FOLDER)
    else:
        validation["refusals"] = ["no leg of this trip has a file to copy — its "
                                  "period comes from them"]
        return None, validation
    validation["refusals"], validation["warnings"] = ref, warn
    validation["refusals"] += [f"the place {r} has no label in the owner pack"
                               for r in unknown]
    return name, validation


def name_inputs(index):
    """-> {folder id: what its name is made of}: its files, place refs, [who]
    (subject id -> name, in name order) and [what]. Read before and after a
    render dry run, so each name change can say why (M3)."""
    files = {}
    for f in index["files"]:
        if f["status"] == "present" and f["folder"]:
            files.setdefault(f["folder"], set()).add(f["file_id"])
    out = {}
    for fo in index["folders"]:
        v = fo.get("validation") or {}
        out[fo["id"]] = {
            "files": files.get(fo["id"], set()),
            "where": [r["ref"] for r in fo.get("where") or []],
            "who": [(w.get("subject_id"), w.get("name")) for w in v.get("who") or []],
            "what": agent_what(fo) or v.get("what_pick")}
    return out


def group_changes_since_render(index, fid):
    """-> the `group` log lines about `fid` since the last render. A group
    command clears the names it touches, so this is all a dry run has."""
    last = max((i for i, e in enumerate(index["log"]) if e["cmd"] == "index render"),
               default=-1)
    return [e for e in index["log"][last + 1:]
            if e["cmd"].startswith(GROUP_CMD) and re.search(rf"\b{fid}\b", e["change"])]


def why_renamed(was, now, old_name, grouped=()):
    """One line: what changed between a folder's name inputs before and after.
    `grouped` is the folder's `group` log lines since the last render."""
    if grouped:
        # One line per file moved is in the log; the dry run says the rest.
        said = [e["change"] for e in grouped if not e["change"].startswith("f-")]
        cmds = sorted({e["cmd"][len(GROUP_CMD):].strip() for e in grouped})
        return (f"`group {'/'.join(cmds)}` since the last render: "
                + ("; ".join(said) or f"{len(grouped)} file(s) moved"))
    if not old_name or was is None:
        return "a new folder"
    if now is None:
        return "the folder is gone"
    said = []
    came, went = len(now["files"] - was["files"]), len(was["files"] - now["files"])
    if came or went:
        said.append(f"{came} file(s) moved in, {went} out")
    if now["where"] != was["where"]:
        said.append(f"place {' + '.join(was['where']) or '(none)'} -> "
                    f"{' + '.join(now['where']) or '(none)'}")
    old_who, new_who = dict(was["who"]), dict(now["who"])
    renamed = [f"{old_who[k]} is now {new_who[k]}" for k in old_who
               if k in new_who and old_who[k] != new_who[k]]
    added = [new_who[k] for k in new_who if k not in old_who]
    dropped = [old_who[k] for k in old_who if k not in new_who]
    if renamed:
        said.append("[who] " + ", ".join(renamed))
    if added:
        said.append("[who] adds " + ", ".join(added))
    if dropped:
        said.append("[who] drops " + ", ".join(dropped))
    if not (renamed or added or dropped) and \
            [k for k, _n in now["who"]] != [k for k, _n in was["who"]]:
        said.append("[who] order — the pets now go in the order they were "
                    "first named")
    if now["what"] != was["what"]:
        said.append(f"[what] {was['what'] or '(none)'} -> {now['what'] or '(none)'}")
    return "; ".join(said) or ("the same files, place, pets and [what] — the "
                               "naming rule itself gives a different name now "
                               "(an engine update)")


def cmd_render(args):
    import photo_subjects
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, index = loaded
    dry_run = getattr(args, "dry_run", False)
    names_before = {fo["id"]: fo.get("rendered") for fo in index["folders"]}
    inputs_before = name_inputs(index)
    pack_before = (index.get("render") or {}).get("pack_fingerprint")
    was_frozen = bool(index.get("frozen"))
    if dry_run:
        # FIX7 (U7-3) — nothing is saved, so a holding freeze locks nothing a
        # dry run could change; a stale one is lifted in memory only.
        try:
            open_for_change(workdir, pack, index, "index render")
        except Refused:
            pass
    else:
        open_for_change(workdir, pack, index, "index render")
    profile = pack.profile
    msg = photo_profile.messages(profile)
    words = {w: k for k, w in photo_profile.buckets(profile).items()}
    by_number = {b["batch"]: b for b in json.loads(
        (workdir / "batches.json").read_text(encoding="utf-8")).get("batches", [])}
    by_id = {fo["id"]: fo for fo in index["folders"]}
    held = holders(index)
    for fo in held:
        fo["batches"] = folder_batches(index, fo)
    unseen = photo_plan.batches_without_vision(
        workdir, sorted({n for fo in held for n in fo["batches"]}))
    if unseen and not args.no_vision:
        raise Refused(
            "the see stage has not run for batch(es) "
            + ", ".join(f"B{n}" for n in unseen)
            + " — nothing rendered. [who] and [what] cannot reach a folder name "
            "without it (R1). Run photo_see first, or pass --no-vision to render "
            "those folders from metadata alone. Such a batch stays unseen, so "
            "every later render of this dump (each --dry-run and each re-lock) "
            "needs --no-vision again.")
    for fo in held:
        if fo["dest"]["mode"] != "new" and not Path(fo["dest"]["existing_path"]).is_dir():
            raise Refused(f"{fo['id']}: the {fo['dest']['mode']} target is no longer "
                          f"a directory: {fo['dest']['existing_path']} — nothing "
                          "rendered (`photo_index.py dest` it again)")
        if fo["dest"].get("refs"):
            run_dedupe(workdir, fo, pack)
    broken = structure_problems(index, by_number)
    if broken:
        raise Refused("the folder structure cannot be exported — nothing rendered:\n"
                      + "\n".join(f"  ⛔ {p}" for p in broken[:10]))

    files = {f["source"]: f for f in index["files"] if f["status"] == "present"}
    before = {s: (f["route"], f["folder"], f["route_source"]) for s, f in files.items()}
    for f in files.values():
        f.update(route=None, folder=None, dest_name=None, dupe_of=None, who=[],
                 route_source=SETTLED + "no-plan")
    cells, owner, stray = {}, {}, set()

    def take(r, path_ids, label):
        src = r["SourceFile"]
        f = files.get(src)
        if f is None:
            stray.add(src)
            return
        if src in owner:
            raise Refused(f"{Path(src).name} is settled by both {owner[src]} and "
                          f"{label}: photo_plan assigns files by date range and "
                          "these share a date — nothing rendered")
        owner[src] = label
        settle_file(index, f, r, path_ids, words)

    units = export_units(index, by_number)
    paths = unit_paths(units, PLACEHOLDER_ROOT, real=False)
    path_ids = {p: fid for fid, p in paths.items() if by_id[fid]["kind"] in HOLDERS}
    tops = {p for fid, p in paths.items() if by_id[fid]["kind"] in PARENTS}
    for n, u in enumerate([u for u in units if u["batches"]], 1):
        plan = unit_plan(u, n, paths)
        rows, _cand, _paper, _why = photo_plan.settle_rows(
            workdir, plan, [by_number[b] for b in u["batches"] if b in by_number],
            PLACEHOLDER_ROOT, profile, msg)
        visual = photo_plan.visual_columns(workdir, u["batches"], profile, pack) or {}
        for r in rows:
            if r["_action"] == ROUTE_COPY and r["_dest"] in tops:
                raise Refused(f"{Path(r['SourceFile']).name} ({r['_day']}) falls in "
                              f"no leg of {u['top']['id']} — nothing rendered")
            take(r, path_ids, u["top"]["id"])
            cells[r["SourceFile"]] = visual.get(r["SourceFile"])
            if r["SourceFile"] in files:
                files[r["SourceFile"]]["who"] = [
                    {k: s.get(k) for k in ("subject_id", "confirmed", "provenance",
                                           "by", "view") if k in s}
                    for s in (cells[r["SourceFile"]] or {}).get(
                        photo_plan.WHO_SUBJECTS) or []]
    if (workdir / "no-date-files.csv").exists():
        rows, _counts, _root = photo_plan.settle_no_date_rows(
            workdir, PLACEHOLDER_ROOT, profile, msg)
        for r in rows:
            take(r, None, "the no-date plan")
    if stray:
        raise Refused(f"{len(stray)} file(s) in the manifest are not in this index "
                      "— the dump changed since init. Run `photo_index.py init` "
                      "again. Nothing rendered.")

    # ⛔ Two counts, never one (Lead 20260922). A folder-only move is not a
    # route change, and a total that counts both as "route(s) changed" states
    # the same untruth as a log line reading "X → X" — just as a number.
    # ⚠️ NOT `moved`: the dry-run branch below binds `moved` to the list of
    # folder NAMES that would change — a different fact in the same function.
    rerouted, folder_moves = 0, 0
    for src, f in files.items():
        old_route, old_folder, old_source = before[src]
        if f["folder"] != old_folder:
            f["history"].append({"phase": index["phase"], "folder": f["folder"],
                                 "by": "render"})
        if old_source and old_route and (old_route, old_folder) != (f["route"], f["folder"]):
            if old_route != f["route"]:
                rerouted += 1
            else:
                folder_moves += 1
            was = ("init's provisional route" if old_source.startswith(PROVISIONAL)
                   else "an earlier render")
            # ⛔ Say WHAT changed. This printed the route alone, so a file whose
            # route held and whose FOLDER moved read "X → X" — a line that
            # looks meaningless on its face (M14: 257 of them on one real
            # import). When the route is unchanged, the folder is the change.
            what = (f"{old_route} → {f['route'] or 'not copied'}"
                    if old_route != f["route"] else
                    f"{old_route}, folder {old_folder} → {f['folder']}")
            log_entry(index, "index render",
                      f"{f['file_id']} {Path(src).name}: {what}",
                      f"{was} replaced by photo_plan.route() "
                      f"({f['route_source'][len(SETTLED):]})")

    registry = photo_subjects.load(pack=pack)
    cap = int(registry.defaults.get(      # the cap visual_columns() reads
        "names_per_folder", photo_subjects.DEFAULT_THRESHOLDS["names_per_folder"]))
    budget = photo_profile.name_budget(profile)
    labels = id_labels(pack)
    rmsg = photo_profile.review_messages(profile)
    owned = claims(index)
    homes = photo_profile.labelled_home_points(profile)
    gps = {}
    if homes:
        with open(workdir / "manifest.csv", newline="", encoding="utf-8") as fh:
            gps = {r["SourceFile"]: photo_cluster.gps_point(r.get("GPSPosition") or "")
                   for r in csv.DictReader(fh)}
    copied = set(photo_execute.verified_anywhere(workdir / "plan"))
    for fo in held:
        members = [f for f in files.values()
                   if f["folder"] == fo["id"] and f["route"] == ROUTE_COPY]
        # H-D — a folder already on the drive keeps its [who] order; a
        # missing earlier [who] (an older index) keeps nothing.
        keep = ([w.get("subject_id") for w in
                 (fo.get("validation") or {}).get("who") or []]
                if any(f["source"] in copied for f in members) else ())
        spans = ([(min(owned[fo["id"]]), max(owned[fo["id"]]))] if fo.get("days")
                 else [(by_number[b]["from"], by_number[b]["to"])
                       for b in fo["batches"] if b in by_number])
        parent = by_id.get(fo.get("parent"))
        fo["rendered"], fo["validation"] = render_holder(
            fo, members, cells, spans, labels, budget, cap, profile, rmsg,
            parent_words=where_words(parent, labels)[0] if parent else None,
            own=at_own_place(members, fo, parent, gps, homes), keep=keep)
    grouped = parents(index)
    for p in grouped:
        legs = {leg["id"] for leg in legs_of(index, p["id"])}
        members = [f for f in files.values()
                   if f["folder"] in legs and f["route"] == ROUTE_COPY]
        p["rendered"], p["validation"] = render_parent(p, members, labels, budget)
    for fo in live(index):
        if fo["kind"] == "bucket":
            fo["status"] = ("proposed" if any(f["folder"] == fo["id"]
                                              for f in files.values()) else "empty")
    index["render"] = {"at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "pack_fingerprint": pack_id(pack), "no_vision": bool(unseen)}
    named = held + grouped
    days = [fo for fo in held if fo["kind"] == "day"]
    legs = len(held) - len(days)
    shape = (f", {legs} leg(s) under {len(grouped)} parent(s)" if grouped else "")
    with_who = [fo for fo in named if fo["validation"]["who"]]
    refused = [fo for fo in named if fo["validation"]["refusals"]]
    if dry_run:
        moved = [(fo["id"], names_before.get(fo["id"]), fo.get("rendered"))
                 for fo in index["folders"]
                 if fo.get("rendered") != names_before.get(fo["id"])]
        print(f"render --dry-run: nothing written"
              + (" — the index stays frozen" if was_frozen else ""))
        if moved:
            print(f"{len(moved)} folder name(s) would change:")
            if pack_before and pack_before != pack_id(pack):
                print("  the owner pack changed since the last render (a confirm, "
                      "a rename or a place label)")
            after = name_inputs(index)
            for fid, old, new in moved:
                print(f"  {fid}  {old or '(none)'}  ->  {new or '(none)'}")
                why = why_renamed(inputs_before.get(fid), after.get(fid), old,
                                  group_changes_since_render(index, fid))
                if why == "a new folder":
                    # F-kk (Card 6): say what fills it — a bucket made by a
                    # route (paperwork, to-be-checked) was a bare "new folder".
                    routes = Counter(f.get("route") or "not copied"
                                     for f in index["files"]
                                     if f.get("folder") == fid
                                     and f.get("status") == "present")
                    why += (" — %d file(s): %s" % (sum(routes.values()), ", ".join(
                        f"{n} {r}" for r, n in sorted(routes.items())))
                        if routes else "")
                print(f"        why: {why}")
        else:
            print("no folder name would change")
        if refused:
            print(f"⚠️ {len(refused)} folder name(s) would fail the validator")
        return 0
    log_entry(index, "index render",
              f"{len(days)} day folder(s){shape} rendered, {len(with_who)} with a "
              f"[who]; {rerouted} route(s) changed, {folder_moves} folder-only "
              f"move(s)", "names from the index, the "
              "registry and the pack as they stand now")
    save(target, pack, index)

    routes = {}
    for f in files.values():
        routes[f["route"] or "not copied"] = routes.get(f["route"] or "not copied", 0) + 1
    buckets = [fo for fo in live(index)
               if fo["kind"] == "bucket" and fo["status"] != "empty"]
    print(f"index: {target}")
    print(f"rendered {len(days)} day folder(s){shape} and {len(buckets)} bucket(s); "
          f"{len(with_who)} folder(s) carry a [who]")
    for fo in with_who:
        print(f"  {fo['id']}  {fo['rendered']}")
    print("routes: " + ", ".join(f"{k} {v}" for k, v in sorted(routes.items())))
    if rerouted or folder_moves:
        print(f"{rerouted} route(s) differ from the earlier ones and {folder_moves} "
              "folder-only move(s) — each is in the log")
    if refused:
        print(f"⚠️ {len(refused)} folder name(s) fail the validator — "
              "`photo_index.py check` lists them", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# recut (D-I1) and relabel
# ---------------------------------------------------------------------------

# What photo_classify_set writes into a batch. `photo_cluster --force` wipes it.
BATCH_FIELDS = ("type", "where", "note", "classified_at", "planned_at")
RECUT_REASON = "the owner's onboarding answers are in the pack (D-I1)"


def per_batch_artefacts(workdir, pack, index):
    """-> [(kind, count, blocks)] for everything keyed by a batch NUMBER.

    A re-cut renumbers batches (measured: an away_km answer of 10 km left 0 of
    56 numbers naming the span they named before), so each of these would then
    describe a different set of photographs. Only `status.json` does not
    block: `photo_run.py status` rewrites it from batches.json."""
    import photo_subjects
    workdir = Path(workdir)
    found = []

    def add(kind, n, blocks=True):
        if n:
            found.append((kind, n, blocks))

    add("classify/batch-NN/ (samples, where, see-labels, see-report, decisions)",
        sum(1 for q in workdir.glob("classify/batch-*") if q.is_dir()))
    add("plan/dedupe_batch-NN.json", len(list(workdir.glob("plan/dedupe_batch-*.json"))))
    add("plan/plan_P*.md and plan_P*-files.csv", len(list(workdir.glob("plan/plan_P*"))))
    add("plan/execute-state_*.json", len(list(workdir.glob("plan/execute-state_*.json"))))
    add("plans.json", int((workdir / "plans.json").exists()))
    add("memory-review_C*.md", len(list(workdir.glob("memory-review_C*.md"))))
    add("P-B*.md (batch pages)", len(list(workdir.glob("P-B*.md"))))
    batches = json.loads((workdir / "batches.json").read_text(
        encoding="utf-8")).get("batches", [])
    add("batches.json: batches past `pending` or carrying classify fields",
        sum(1 for b in batches if b.get("status", "pending") != "pending"
            or any(b.get(k) for k in BATCH_FIELDS)))
    # photo_see writes the work dir's name as each evidence entry's `unit`.
    units = {workdir.name, index.get("dump"), index.get("workdir_name")} - {None}
    registry = photo_subjects.load(pack=pack)
    add("owner pack: subject evidence from this dump's batches",
        sum(1 for subject in registry.subjects
            for e in subject.record.get("evidence") or []
            if e.get("batch") is not None and e.get("unit") in units))
    add("index: per-batch pages", len(index.get("pages") or []))
    if index.get("phase") not in (PHASE_INIT, PHASE_ONB):
        add(f"index: phase {index.get('phase')!r}", 1)
    add("status.json (named only: `photo_run.py status` rewrites it)",
        int((workdir / "status.json").exists()), blocks=False)
    return found


def stamped_backup(path, tag):
    """Copy `path` beside itself under a stamped name; never overwrite one."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"{path.name}.bak-{stamp}-{tag}")
    n = 2
    while dest.exists():
        dest = path.with_name(f"{path.name}.bak-{stamp}-{tag}-{n}")
        n += 1
    shutil.copy2(path, dest)
    return dest


def members_of(index):
    out = {}
    for f in index["files"]:
        if f["status"] == "present" and f["folder"]:
            out.setdefault(f["folder"], set()).add(f["source"])
    return out


def folder_identity(fo, members, batches):
    """What makes a folder the SAME folder across two cuts: its kind and its
    files. A folder holding no file is known by its batch span instead."""
    if members:
        return (fo["kind"], fo.get("bucket_key"), fo.get("month"), frozenset(members))
    spans = tuple(sorted((batches[n]["from"], batches[n]["to"])
                         for n in fo.get("batches") or [] if n in batches))
    return ("empty", fo["kind"], fo.get("bucket_key"), fo.get("month"), spans)


def cmd_recut(args):
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, index = loaded
    if index.get("frozen"):
        raise Refused("the index is frozen (D-I16) — a re-cut would move files out "
                      "of the folders the freeze locked. Nothing written. Lift it "
                      f"first:\n  {run_line('photo_index.py')} unfreeze "
                      f"\"{workdir}\" --reason \"...\"")
    grouped = [fo["id"] for fo in live(index) if fo["kind"] in PARENTS]
    parted = [fo["id"] for fo in live(index) if fo.get("days")]
    if grouped or parted or any(e.get("cmd") in {f"{GROUP_CMD} {a}" for a in GROUP_STRUCTURE}
                                for e in index["log"]):
        raise Refused(
            "this index was grouped ("
            + "; ".join(x for x in (
                f"parent(s) {', '.join(grouped)}" if grouped else "",
                f"folder(s) holding part of a batch: {', '.join(parted)}" if parted else "")
                if x) + (")" if grouped or parted else "a move or merge)")
            + " — a re-cut renumbers the batches the grouping is built on and would "
            "retire parents their legs still point at. Nothing written. The re-cut "
            "runs right after onboarding, before any grouping (D-I1).")
    found = per_batch_artefacts(workdir, pack, index)
    blocking = [x for x in found if x[2]]
    if blocking:
        raise Refused(
            "a re-cut renumbers the batches, and these are keyed by batch number "
            "— nothing written (U3-11):\n"
            + "\n".join(f"  ⛔ {kind}: {n}" for kind, n, _b in blocking)
            + "".join(f"\n  ({kind}: {n})" for kind, n, b in found if not b)
            + "\nThe re-cut runs right after onboarding, before any vision pass "
            "(D-I1). A place label that arrives later needs no re-cut: "
            "`photo_index.py relabel`.")

    bpath = workdir / "batches.json"
    old_batches = json.loads(bpath.read_text(encoding="utf-8")).get("batches", [])
    if getattr(args, "dry_run", False):
        # F-s (Card 6): the real cut, in place, then every file photo_cluster
        # writes is put back byte for byte and the index is never saved.
        written = [bpath, workdir / "no-date-files.csv"]
        before = {p: (p.read_bytes() if p.exists() else None) for p in written}
        try:
            return recut(args, workdir, pack, target, index, bpath, old_batches,
                         None, dry_run=True)
        finally:
            for p, data in before.items():
                if data is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(data)
    backup = stamped_backup(bpath, "recut")
    return recut(args, workdir, pack, target, index, bpath, old_batches, backup)


def recut(args, workdir, pack, target, index, bpath, old_batches, backup,
          dry_run=False):
    """The re-cut itself (cmd_recut's checks already passed)."""
    cmd = [sys.executable, str(HERE / "photo_cluster.py"), str(workdir), "--force",
           "--profile", str((pack.dir / photo_profile.PROFILE_NAME).resolve())]
    if args.no_geocode:
        cmd.append("--no-geocode")
    r = subprocess.run(cmd, capture_output=True, text=True, env=pack_env(pack))
    if r.returncode:
        raise Refused(f"photo_cluster failed — the index is unchanged (the cut it "
                      f"replaced is {backup.name if backup else 'untouched'}):\n"
                      + (r.stdout + r.stderr)[-800:])
    for line in r.stderr.splitlines():
        print(f"  photo_cluster: {line}", file=sys.stderr)

    new, _dropped = build(workdir, pack, index["dump"], index)
    new_batches = json.loads(bpath.read_text(encoding="utf-8")).get("batches", [])
    gen = int(index.get("cluster_gen") or 1) + 1
    old_by_num = {b["batch"]: b for b in old_batches}
    new_by_num = {b["batch"]: b for b in new_batches}
    old_members, new_members = members_of(index), members_of(new)
    old_folder_of = {f["source"]: f["folder"] for f in index["files"]
                     if f["status"] == "present"}

    folders = [dict(fo) for fo in index["folders"]]
    by_id = {fo["id"]: fo for fo in folders}
    unmatched = {}
    for fo in live({"folders": folders}):
        unmatched.setdefault(folder_identity(
            fo, old_members.get(fo["id"], set()), old_by_num), fo["id"])
    final, kept, created = {}, [], []
    for nf in new["folders"]:
        key = folder_identity(nf, new_members.get(nf["id"], set()), new_by_num)
        oid = unmatched.pop(key, None)
        if oid:
            by_id[oid].update(where=nf["where"], batches=nf["batches"],
                              rendered=None, validation=None, status="proposed")
            final[nf["id"]] = oid
            kept.append(oid)
        else:
            fid = next_folder_id({"folders": folders})   # max + 1, never reused
            fo = dict(nf, id=fid)
            folders.append(fo)
            by_id[fid] = fo
            final[nf["id"]] = fid
            created.append(fid)
    retired = []
    for fo in live({"folders": folders}):
        if fo["id"] not in kept and fo["id"] not in created:
            fo.update(status=RETIRED)
            retired.append(fo["id"])
    final_members = {final[t]: m for t, m in new_members.items()}
    new_folder_of = {s: fid for fid, m in final_members.items() for s in m}
    for fid in created:
        mem = final_members.get(fid, set())
        sources = {old_folder_of.get(s) for s in mem} - {None}
        if len(sources) == 1:
            src = next(iter(sources))
            if mem < old_members.get(src, set()):
                by_id[fid]["split_from"] = src
    for oid in retired:
        targets = {new_folder_of.get(s) for s in old_members.get(oid, ())} - {None}
        if len(targets) == 1:
            by_id[oid]["merged_into"] = next(iter(targets))

    old_files = {f["source"]: f for f in index["files"]}
    files, moves = [], []
    for nf in new["files"]:
        f = dict(nf)
        prev = old_files.get(f["source"])
        if f["status"] == "present":
            f["folder"] = final.get(f["folder"]) if f["folder"] else None
            f["cluster_gen"] = gen
            before = (prev["folder"] if prev and prev["status"] == "present"
                      else None)
            f["history"] = list(prev["history"]) if prev else []
            if prev is None or before != f["folder"]:
                f["history"].append({"phase": PHASE_ONB, "folder": f["folder"],
                                     "cluster_gen": gen, "by": "recut"})
                moves.append((f, before))
        files.append(f)

    index.update(phase=PHASE_ONB, cluster_gen=gen, pack_fingerprint=pack_id(pack),
                 places=new["places"], folders=folders, files=files,
                 file_id_next=new["file_id_next"], render=None)
    for f, before in moves:
        log_entry(index, "index recut",
                  f"{f['file_id']} {Path(f['source']).name}: {before or '—'} → "
                  f"{f['folder'] or 'no folder'}", f"cluster generation {gen}")
    kinds = {}
    for fo in live(index):
        for ref in fo["where"]:
            k = ref["ref"].split(":")[0].split("-")[0]
            kinds[k] = kinds.get(k, 0) + 1
    refs = ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())) or "none"
    renumbered = sum(1 for b in new_batches
                     if (old_by_num.get(b["batch"]) or {}).get("from") != b["from"]
                     or (old_by_num.get(b["batch"]) or {}).get("to") != b["to"])
    summary = (f"batches {len(old_batches)} → {len(new_batches)} ({renumbered} "
               f"number(s) now name a different span); folders kept {len(kept)}, "
               f"retired {len(retired)}, new {len(created)}; {len(moves)} file(s) "
               f"moved; place refs {refs}")
    if dry_run:
        print(f"cluster generation {gen} (DRY RUN): {summary}")
        for f, before in moves[:20]:
            print(f"  {f['file_id']} {Path(f['source']).name}: {before or '—'} → "
                  f"{f['folder'] or 'no folder'}")
        if len(moves) > 20:
            print(f"  … and {len(moves) - 20} more")
        print("DRY RUN — nothing written (batches.json and the index are as "
              "they were).")
        return 0
    log_entry(index, "index recut", summary, args.reason or RECUT_REASON, by="agent")
    save(target, pack, index)
    print(f"index: {target}")
    print(f"cluster generation {gen}: {summary}")
    print(f"the cut it replaced: {backup.name}")
    print("next: `photo_index.py render` (and the vision pass, which reads the new "
          "batch numbers)")
    return 0


def own_places(workdir, pack, index, ids=None):
    """-> ({folder id: place refs}, new place entries, [(id, unanswered days)],
    unanswered days) for every live day folder or leg (or only `ids`), each
    read from the days its own member files were taken on.

    Each day's centroid is read from manifest.csv at run time through
    `photo_cluster.read_day_files()` — never stored. The words come from
    `photo_cluster.batch_places()` itself, with the pack's own readers and a
    Geocoder that is OFF: this asks the network nothing. A folder with any day
    that neither the pack nor the geocode cache answers keeps the refs it
    has."""
    day_files, _ = photo_cluster.read_day_files(Path(workdir) / "manifest.csv")
    geocoder = photo_cluster.Geocoder(Path(workdir).parent / "geocode-cache.json",
                                      enabled=False,
                                      language=photo_profile.get(pack.profile, "language"))
    all_homes = photo_profile.home_points(pack.profile)
    labelled = photo_profile.labelled_home_points(pack.profile)
    named = photo_profile.named_places(pack)
    place_km = photo_profile.named_place_km(pack.profile)
    labels = place_labels(pack)

    def words(days):
        return photo_cluster.batch_places(days, day_files, geocoder, all_homes,
                                          labelled_homes=labelled,
                                          named_places=named, place_km=place_km)

    days_of = {}
    for f in index["files"]:
        if f["status"] == "present" and f["folder"] and f["date"]:
            days_of.setdefault(f["folder"], set()).add(
                datetime.fromisoformat(f["date"]).date())
    new_places, said = {}, set()
    kept, unanswered, decided = [], 0, {}
    for fo in live(index):
        if fo["kind"] not in HOLDERS or (ids is not None and fo["id"] not in ids):
            continue
        days = sorted(d for d in days_of.get(fo["id"], ())
                      if d in day_files and day_files[d]["centroid"])
        silent = [d for d in days if not words([d])]
        if not days or silent:
            unanswered += len(silent)
            if silent:
                kept.append((fo["id"], len(silent)))
            decided[fo["id"]] = fo["where"]
            continue
        refs, _coord = place_refs("+".join(words(days)), labels, new_places, said)
        decided[fo["id"]] = refs
    return decided, new_places, kept, unanswered


def relabel(workdir, pack, target, index, go=False, reason=None):
    """Put the pack's CURRENT labels on the day folders' place refs. -> a dict.

    Changes no batch boundary and no batch number, so — unlike `recut` — it is
    allowed after the vision pass; G6 calls it after an SNL answer. Refused on
    a freeze that still holds.

    Each folder's days come from its member FILES, and each day's centroid is
    read from manifest.csv at run time through `photo_cluster.read_day_files()`
    — never stored. The words come from `photo_cluster.batch_places()` itself,
    with the pack's own readers and a Geocoder that is OFF: a relabel asks the
    network nothing. A folder with any day that neither the pack nor the
    geocode cache answers keeps the refs it has.
    ⛔ Writes the index only — never batches.json."""
    workdir = Path(workdir)
    open_for_change(workdir, pack, index, "index relabel")
    decided, new_places, kept, unanswered = own_places(workdir, pack, index)
    changed = [(fid, [r["ref"] for r in fo["where"]], [r["ref"] for r in decided[fid]])
               for fid, fo in ((fo["id"], fo) for fo in live(index) if fo["id"] in decided)
               if [r["ref"] for r in decided[fid]] != [r["ref"] for r in fo["where"]]]
    places = {}
    switched = {ref for _fid, _old, new in changed for ref in new}
    for refs in decided.values():
        for r in refs:
            entry = index["places"].get(r["ref"]) or new_places.get(r["ref"]) or {}
            if r["ref"] in switched and r["ref"] not in index["places"] \
                    and entry.get("kind") != "map":
                entry = dict(entry, label_from="relabel")
            places[r["ref"]] = entry
    for p in parents(index):
        # A parent's place is never re-resolved (R8); its ref stays.
        for r in p["where"]:
            places.setdefault(r["ref"], index["places"].get(r["ref"]) or {})
    result = {"changed": changed, "kept": kept, "unanswered_days": unanswered,
              "written": False}
    if go and changed:
        for fo in live(index):
            if fo["id"] in dict((c[0], 1) for c in changed):
                fo.update(where=decided[fo["id"]], rendered=None, validation=None)
        index["places"] = places
        for fid, old, new in changed:
            log_entry(index, "index relabel",
                      f"{fid}: {' + '.join(old) or '—'} → {' + '.join(new)}",
                      reason or "the owner's place labels as the pack holds them now",
                      by="agent")
        save(target, pack, index)
        result["written"] = True
    return result


def cmd_relabel(args):
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, index = loaded
    result = relabel(workdir, pack, target, index, go=args.go, reason=args.reason)
    labels = {k: v for k, v in id_labels(pack).items() if v}
    print(f"relabel: {len(result['changed'])} folder(s) change; "
          f"{len(result['kept'])} kept their refs ({result['unanswered_days']} "
          "day(s) neither the pack nor the geocode cache answers offline); "
          "the geocoder is off")
    for fid, old, new in result["changed"]:
        shown = " + ".join(f"{r} ({labels[r]})" if r in labels else r for r in new)
        print(f"  {fid}: {' + '.join(old) or '—'} → {shown}")
    for fid, n in result["kept"]:
        print(f"  {fid}: kept — {n} day(s) unanswered")
    if result["changed"] and not args.go:
        print("DRY RUN — nothing written. Add --go to write.")
    elif result["written"]:
        print("written; next: `photo_index.py render`")
    return 0


# ---------------------------------------------------------------------------
# apply-page — a confirmed batch page into the index (G6, P2)
# ---------------------------------------------------------------------------

PAGE_CMD = "index apply-page"


def page_subject(registry, frame, name):
    """-> the CONFIRMED record a picked frame now belongs to under the name the
    owner typed, or None — `photo_memory.cmd_confirm`'s own U-3 test, so the
    page trace and see-labels can never disagree about a pick."""
    import photo_memory
    import photo_subjects
    subject = registry.get(frame["subject_id"])
    if (subject is not None and frame.get("ref")
            and subject.status == photo_subjects.STATUS_SUPERSEDED):
        subject = photo_memory.split_child_holding(registry, subject, frame["ref"])
    if (subject is not None and subject.status == photo_subjects.STATUS_ABSORBED
            and subject.record.get("absorbed_by")):
        subject = registry.get(subject.record["absorbed_by"])
    if (subject is not None and subject.status == photo_subjects.STATUS_CONFIRMED
            and subject.name == name):
        return subject
    return None


def shared_frame_subject(workdir, registry, batch, source, name):
    """-> the confirmed subject called `name` whose id `confirm` logged on
    this photo's see-label at frame level (G6-6d), or None."""
    import photo_subjects
    labels = json.loads((workdir / "classify" / f"batch-{batch:02d}" /
                         "see-labels.json").read_text(encoding="utf-8")) \
        if (workdir / "classify" / f"batch-{batch:02d}" / "see-labels.json").exists() else {}
    entry = next((e for e in labels.get("labels") or [] if e.get("path") == source), {})
    for sid in entry.get("subject_ids") or []:
        subject = registry.get(sid)
        if (subject is not None and subject.name == name
                and subject.status == photo_subjects.STATUS_CONFIRMED):
            return subject
    return None


def fsl_month_proposals(index, ref, changed, need):
    """-> the months (YYYY-MM) with at least `need` day folders at `ref`, once
    `changed` (relabel's (id, old, new)) is applied — what `group
    make-fsl-month` would accept. Proposed, never run (D-I12)."""
    wheres = {fo["id"]: [r["ref"] for r in fo["where"]] for fo in live(index)}
    for fid, _old, new in changed:
        wheres[fid] = new
    owned, months = claims(index), {}
    for fo in live(index):
        if fo["kind"] != "day" or fo.get("parent") or ref not in wheres[fo["id"]]:
            continue
        spans = {d[:7] for d in owned.get(fo["id"], ())}
        if len(spans) == 1:
            month = spans.pop()
            months[month] = months.get(month, 0) + 1
    return [m for m, n in sorted(months.items()) if n >= need]


def radius_notices(workdir, pack, index, refs, changed):
    """FIX6 (U6-23) — a day folder that keeps the map word a named place
    replaced on other folders, and why: its days are outside the naming radius.
    A district word is administrative and wider than the radius, so the same
    word can cover a different spot. -> lines to print; distances only."""
    named = {pid: (lat, lon, label)
             for lat, lon, label, pid in photo_profile.named_places(pack)}
    radius = photo_profile.named_place_km(pack.profile)
    moved = {fid for fid, _old, _new in changed}
    day_files, _ = photo_cluster.read_day_files(Path(workdir) / "manifest.csv")
    days_of = {}
    for f in index["files"]:
        if f["status"] == "present" and f["folder"] and f["date"]:
            days_of.setdefault(f["folder"], set()).add(
                datetime.fromisoformat(f["date"]).date())
    out = []
    for ref in dict.fromkeys(refs):
        if ref not in named:
            continue
        lat, lon, label = named[ref]
        words = {o for _fid, old, new in changed if ref in new
                 for o in old if o.startswith("map:")}
        for fo in live(index):
            if fo["id"] in moved or fo["kind"] not in HOLDERS:
                continue
            kept = [r["ref"] for r in fo["where"] if r["ref"] in words]
            km = [photo_cluster.haversine_km(day_files[d]["centroid"], (lat, lon))
                  for d in days_of.get(fo["id"], ())
                  if d in day_files and day_files[d]["centroid"]]
            if kept and km:
                out.append(f"  {fo['id']} keeps its map word {kept[0][len('map:'):]}: "
                           f"its days are {min(km):.1f} km from {label} "
                           f"(naming radius {radius:g} km)")
    return out


def page_row_warnings(index):
    """R11 — a page row that names a file the index now holds as `missing`.
    Reported, never re-linked: nothing can re-link it before the freeze has a
    sha to link by."""
    status = {f["file_id"]: f["status"] for f in index["files"]}
    out = []
    for page in index.get("pages") or []:
        for row in page.get("rows") or []:
            gone = [fid for fid in row.get("file_ids") or []
                    if status.get(fid) != "present"]
            if gone:
                out.append(f"{page['page_id']} row {row['row']} names "
                           f"{len(gone)} file(s) the index holds as missing: "
                           + ", ".join(gone))
    return out


def cmd_apply_page(args):
    import photo_memory
    import photo_onboard_page
    import photo_subjects
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, index = loaded
    page = args.page[:-3] if args.page.endswith(".md") else args.page
    batch = photo_memory.page_batch(f"{page}.md")
    if batch is None:
        raise Refused(f"{args.page!r} is not a batch page name (e.g. P-B03) — "
                      "nothing changed")
    path = workdir / f"{page}.md"
    if not path.is_file():
        raise Refused(f"{path} does not exist — nothing changed")
    text = path.read_text(encoding="utf-8")
    marked = photo_memory.PAGE_MARKER_IN_TEXT.search(text)
    if not marked or marked.group(1) != page:
        raise Refused(f"{path.name} was not written as {page} — nothing changed")
    if any(p.get("page_id") == page for p in index.get("pages") or []):
        raise Refused(f"{page} is already applied — nothing changed")
    open_for_change(workdir, pack, index, PAGE_CMD)
    reason = args.reason or f"the owner's answers on {page}"

    registry = photo_subjects.load(pack=pack)
    blocks = photo_memory.parse_review(text)
    places = photo_memory.parse_places(text)
    report, _bdir = photo_memory.see_reports(workdir).get(batch, (None, None))
    source_of = {e.get("sample"): e.get("path")
                 for e in (report or {}).get("selected") or [] if e.get("sample")}
    file_of = {f["source"]: f["file_id"] for f in index["files"]}
    crop_picks = [f"Q{block['n']}: {unit['crop_refusal']}" for block in blocks
                  for unit in block["picks"] if unit.get("crop_refusal")]
    if crop_picks:
        raise Refused("\n".join(crop_picks) + "\nnothing changed")
    rows, missing = [], []
    for block in blocks:
        for unit in block["picks"]:
            if unit["verb"] != "pick" or not unit["name"]:
                continue
            ids, file_ids = set(), set()
            for number in unit["numbers"]:
                frame = block["frames"].get(number)
                if not frame:
                    continue
                subject = page_subject(registry, frame, unit["name"])
                if subject is None:
                    # G6-6d — a photo with 2+ animals: its names were logged on
                    # the photo itself, and its draft moved nowhere.
                    subject = shared_frame_subject(workdir, registry, batch,
                                                   source_of.get(Path(frame["path"]).name),
                                                   unit["name"])
                if subject is not None:
                    ids.add(subject.subject_id)
                fid = file_of.get(source_of.get(Path(frame["path"]).name))
                if fid:
                    file_ids.add(fid)
            if not ids:
                missing.append(unit["name"])
                continue
            rows.append({"row": len(rows) + 1, "kind": "sns",
                         "answer": "pick " + ",".join(map(str, unit["numbers"]))
                                   + f" name {unit['name']}",
                         "file_ids": sorted(file_ids), "subject_ids": sorted(ids),
                         "by": "owner-picked"})
    by_label = {label.casefold(): ref for ref, label in id_labels(pack).items()
                if label}
    refs = []
    for place in places:
        if not place["name"]:
            continue
        try:
            label = photo_onboard_page._home_answer(
                f"{place['name']} {place['home'] or ''}".strip())["label"]
        except SystemExit:
            label = place["name"]
        ref = by_label.get((label or "").casefold())
        if ref is None:
            missing.append(label or place["name"])
            continue
        refs.append(ref)
        rows.append({"row": len(rows) + 1, "kind": "snl",
                     "answer": f"name {place['name']}"
                               + (f" {place['home']}" if place["home"] else ""),
                     "place_ref": ref, "file_ids": [], "by": "owner"})
    if missing:
        raise Refused(
            f"{page}: {', '.join(missing)} — not in the owner pack as the page "
            "says. Confirm the page first:\n"
            f"  {run_line('photo_memory.py')} confirm \"{workdir}\" --page {page} --go\n"
            "(a row that confirm refused: blank it or correct it, write the page "
            "again with `photo_memory.py review --batch`, and confirm it) — "
            "nothing changed")

    changed = []
    if refs:
        changed = relabel(workdir, pack, target, index, go=args.go,
                          reason=reason)["changed"]
    need = fsl_month_min_visits(pack.profile)
    proposals = [(ref, month) for ref in dict.fromkeys(refs) if FSL_REF.match(ref)
                 for month in fsl_month_proposals(index, ref, changed, need)]
    kinds = (["sns"] if blocks else []) + (["snl"] if places else [])
    # U3-2 — an armed `skip:` is an answer too. `confirm` records it and the
    # index has nothing to apply for it, so it is counted, never a row.
    skips = [block for block in blocks
             if (block.get("skip_armed") and block.get("skip_numbers"))
             or block.get("skip_animals_armed")]
    skipped = {n for block in skips
               for n in ((block.get("skip_numbers") or []) if block.get("skip_armed")
                         else [])
               + [n for n, _a in block.get("skip_animals_armed_refs") or []]
               + [n for n, _a in block.get("skip_animals_mine_refs") or []]}
    entry = {"page_id": page, "batch": batch, "kinds": kinds,
             "status": "answered" if rows or skips else "unanswered",
             "pinned": photo_memory.pinned_snapshot(text), "rows": rows}
    print(f"{page}: batch {batch}, {len(rows)} answered row(s) "
          f"({sum(r['kind'] == 'sns' for r in rows)} animal, "
          f"{sum(r['kind'] == 'snl' for r in rows)} place)"
          + (f", {len(skips)} skip row(s) ({len(skipped)} photo(s)) — "
             "recorded by `confirm`, nothing for the index to apply"
             if skips else ""))
    for fid, old, new in changed:
        print(f"  {fid}: {' + '.join(old) or '—'} → {' + '.join(new)}")
    for ref, month in proposals:
        print(f"  proposed, not run: {run_line('photo_index.py')} group make-fsl-month "
              f"\"{workdir}\" {ref} {month} --reason \"...\"")
    if changed:
        for line in radius_notices(workdir, pack, index, refs, changed):
            print(line)
    if not args.go:
        print("DRY RUN — nothing written. Add --go to write.")
        return 0
    index.setdefault("pages", []).append(entry)
    log_entry(index, PAGE_CMD, f"{page}: {entry['status']}, {len(rows)} row(s)",
              reason, by="owner")
    for ref, month in proposals:
        log_entry(index, PAGE_CMD, f"proposed, not run: group make-fsl-month "
                  f"{ref} {month}", reason)
    save(target, pack, index)
    print("written; next: `photo_run.py finish --go` again (the next page, or "
          "the copy)")
    return 0


# ---------------------------------------------------------------------------
# identify — the agent names pets after the pages (G7, D-I11)
# ---------------------------------------------------------------------------

IDENTIFY_CMD = "index identify"
VIEWS_NAME = "identify-views.md"
# `identify` returns this when it wrote views for the agent to look at;
# photo_run's finish holds a copy (a case holds them equal).
EXIT_VIEWS_WANTED = 13
AGENT_CONFIRMED = "agent-confirmed"
VERDICTS = ("agree", "no", "unsure", "not-animal")
VIEW_ROW = re.compile(r"^- `(I-\d{4,})` · batch (\d+) · `([^`]+)` · `(subj-[^`]+)`"
                      r".*· verdict:\s*(.*?)\s*$")
VIEW_PIN = re.compile(r"`pinned:` (\S+)")
VIEW_EARLIER = re.compile(r"^- earlier · batch (\d+) · `([^`]+)` · `(subj-[^`]+)`")


def identify_decided(index):
    """-> {(source, subject_id)} the agent already gave any verdict on."""
    source = {f["file_id"]: f["source"] for f in index["files"]}
    return {(source.get(r["file_id"]), r["subject_id"])
            for r in index.get("identify") or []}


def next_view_number(index):
    return max((int(r["id"][2:]) for r in index.get("identify") or []), default=0) + 1


def proposals_for(workdir, pack, index):
    import photo_see
    try:
        return photo_see.identify_proposals(workdir, pack, identify_decided(index))
    except ValueError as exc:
        raise Refused(f"recognition cannot run on this work dir: {exc} — nothing "
                      "written")


def shown_before(workdir):
    """-> ({(sample, subject_id)} rows an earlier views file already showed,
    [row] of it still carrying a verdict, highest view number in it). G7g: a
    row left blank is recorded nowhere, so the views file itself is what
    `finish` reads to not ask it again."""
    path = workdir / VIEWS_NAME
    if not path.is_file():
        return set(), [], 0
    text = path.read_text(encoding="utf-8")
    rows = parse_views(text)[1]
    keys = {(r["sample"], r["subject_id"]) for r in rows}
    keys |= {(m.group(2), m.group(3)) for m in map(VIEW_EARLIER.match, text.splitlines())
             if m}
    return (keys, [r for r in rows if r["verdict"]],
            max((int(r["id"][2:]) for r in rows), default=0))


def attach_crops(workdir, index, offered, pack=None):
    """FIX6 (U6-27) — each proposal's own animal, cropped, so the agent can see
    WHICH animal a two-animal photo's row means. Made now, at views-write time,
    through the pages' `FrameCrops` (the identity thumbnail and its stored box,
    never a box drawn on the classify sample). -> sets `crop` on each row; a
    crop that cannot be made leaves the row as it was."""
    import photo_memory
    crops = photo_memory.FrameCrops(workdir, pack)
    sha = {f["source"]: f.get("sha256") for f in index.get("files") or []}
    for p in offered:
        if p.get("det_index") is None:
            continue
        ref = sha.get(p["path"]) or Path(p["path"]).stem
        got = crops.describe({"path": p["path"], "vec_ref": ref}) or {}
        want = f"{photo_memory.CROP_DIR}/{ref}_d{p['det_index']}.jpg"
        if want in (got.get("crops") or []):
            p["crop"] = want


def answers_route(workdir, pack, index, indent):
    """The commands that apply a views file. FIX9 F10: a freeze that holds
    refuses `--answers --go` (D-I16), so the route starts by lifting it."""
    lines = []
    if index.get("frozen") and freeze_problem(workdir, pack, index) is None:
        lines.append(f"{indent}{run_line('photo_index.py')} unfreeze \"{workdir}\" "
                     "--reason \"...\"")
    lines.append(f"{indent}{run_line('photo_index.py')} identify \"{workdir}\" --answers "
                 f"\"{workdir / VIEWS_NAME}\" --go")
    return lines


def views_text(workdir, pack, index, offered, not_offered, first, earlier=()):
    route = answers_route(workdir, pack, index, "    ")
    lines = [
        "# Photos to look at — agent identification (G7)", "",
        f"> `pinned:` {pack_id(pack)} · written {datetime.now():%Y-%m-%d %H:%M}", "",
        "Recognition proposes a pet's name for each photo below. It cannot tell a "
        "look-alike stranger from the pet, so the name is applied ONLY when you "
        "open the photo, look, and agree.", "",
        "A row's `crop:` is the animal the name is proposed for — on a photo with "
        "more than one animal, `animal 2 of 2` says which. Look at the crop first; "
        "the sample is the rest of the photo, for context.", "",
        "- `agree` — you can see it IS that animal: the name goes into the folder.",
        "- `no` — it is not. `unsure` — you cannot tell. Either way nothing is "
        "named, and the photo is not proposed again.",
        "- `not-animal` — the crop is not a real animal (a picture in a frame, a "
        "reflection): it stops counting as an animal in that photo. Nothing is "
        "named.",
        "- Left blank — nothing is recorded and nothing is named. `finish` does "
        "not ask it again; an explicit `photo_index.py identify` run does.",
        "", "Nothing here is learned: an agreed photo never becomes an example of "
        "the animal.", "",
        "When you have written your verdicts:", "", *route,
        *(["", "then render, check and freeze again before copying."]
          if len(route) > 1 else []),
        "", "## Proposed", ""]
    for n, p in enumerate(offered, first):
        box = ("the whole photo" if p["det_index"] is None
               else f"animal {p['det_index'] + 1} of {p['det_count']}")
        crop = f" · crop: `{p['crop']}`" if p.get("crop") else ""
        skipped = (f" · ⚠️ the owner skipped this photo on {p['skipped_on']} as "
                   f"not theirs; it holds {p['det_count']} animals and the skip "
                   "does not say which" if p.get("skipped_on") else "")
        lines.append(f"- `I-{n:04d}` · batch {p['batch']} · `{p['sample']}` · "
                     f"`{p['subject_id']}` {p['name']} · {p['space']} "
                     f"{p['score']} lead {p['lead']} · {box}{crop}{skipped} · verdict: ______")
    if earlier:
        lines += ["", "## Left blank earlier (not asked again by `finish`)", ""]
        lines += [f"- earlier · batch {p['batch']} · `{p['sample']}` · "
                  f"`{p['subject_id']}` {p['name']}" for p in earlier]
    if not_offered:
        lines += ["", "## Not offered (listed, never applied)", ""]
        lines += [f"- batch {p['batch']} · `{p['sample']}` · {p['name']} · "
                  f"{p['space']} {p['verdict']} {p['score']}"
                  + (f" · {p['reason']}" if p.get("reason") else "")
                  for p in not_offered]
    return "\n".join(lines) + "\n"


def parse_views(text):
    """-> (pinned pack id or None, [row]) from an `identify-views.md`."""
    pin = VIEW_PIN.search(text)
    rows = []
    for line in text.splitlines():
        m = VIEW_ROW.match(line)
        if m:
            verdict = m.group(5).strip("_ ").casefold()
            rows.append({"id": m.group(1), "batch": int(m.group(2)),
                         "sample": m.group(3), "subject_id": m.group(4),
                         "verdict": verdict})
    return (pin.group(1) if pin else None), rows


def cmd_identify(args):
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, index = loaded
    offered, not_offered = proposals_for(workdir, pack, index)
    if not args.answers:
        for p in not_offered:
            print(f"  not offered: batch {p['batch']} {Path(p['sample']).name} "
                  f"{p['name']} — {p['space']} {p['verdict']} {p['score']}"
                  + (f" — {p['reason']}" if p.get("reason") else ""))
        first, earlier = next_view_number(index), []
        if args.new_only:
            shown, answered, last = shown_before(workdir)
            stands = {(p["sample"], p["subject_id"]) for p in offered}
            waiting = [r for r in answered if (r["sample"], r["subject_id"]) in stands]
            if waiting and getattr(args, "preview", False):
                print(f"preview: {len(waiting)} verdict(s) in {VIEWS_NAME} wait to "
                      "be applied — nothing written")
                return EXIT_VIEWS_WANTED
            if waiting:
                print(f"identify: {len(waiting)} verdict(s) written in "
                      f"{workdir / VIEWS_NAME} are not applied yet — nothing "
                      "rewritten. Apply them:\n"
                      + "\n".join(answers_route(workdir, pack, index, "  ")))
                return EXIT_VIEWS_WANTED
            earlier = [p for p in offered if (p["sample"], p["subject_id"]) in shown]
            offered = [p for p in offered if (p["sample"], p["subject_id"]) not in shown]
            first = max(first, last + 1)
            if earlier:
                print(f"identify: {len({p['sample'] for p in earlier})} photo(s) were "
                      "left without a verdict and stay unnamed; run "
                      f"`{run_line('photo_index.py', crops=True)} identify "
                      f"\"{workdir}\"` to see them again")
        if not offered:
            print("identify: no photo to view — nothing proposed "
                  f"({len(not_offered)} not offered)")
            return 0
        if getattr(args, "preview", False):
            print(f"preview: identify would ask the agent to view {len(offered)} "
                  f"photo(s) in {VIEWS_NAME} — nothing written")
            return EXIT_VIEWS_WANTED
        attach_crops(workdir, index, offered, pack)
        uncropped = [p for p in offered
                     if p.get("det_index") is not None and not p.get("crop")]
        if uncropped:
            # F-r (Card 6): said, never silent. Measured on UAT02-02: finish
            # started with a python that had no pillow-heif / ffmpeg, so every
            # HEIC and video row lost its crop and only JPEG rows kept one.
            import photo_embed
            print(f"⚠️ {len(uncropped)} of {len(offered)} row(s) have no crop: "
                  "the photo could not be converted here "
                  f"({photo_embed.preview_backend()} backend, this python: "
                  f"{sys.executable}). The agent then sees the whole photo "
                  "only — on a photo with 2+ animals it cannot tell which one "
                  "a row means. Run identify with the repo .venv.")
        (workdir / VIEWS_NAME).write_text(
            views_text(workdir, pack, index, offered, not_offered, first, earlier),
            encoding="utf-8")
        for n, p in enumerate(offered, first):
            print(f"  I-{n:04d} batch {p['batch']} {Path(p['sample']).name}: "
                  f"{p['name']}? ({p['space']} {p['score']})")
        print(f"identify: {len(offered)} photo(s) to view — open {workdir / VIEWS_NAME}, "
              "look at each photo and write a verdict; nothing is named yet")
        return EXIT_VIEWS_WANTED
    return apply_views(args, workdir, pack, target, index, offered)


def not_animal_marks_from(workdir, records, now, pack=None):
    """Q8-c — the agent's `not-animal` verdicts as index marks (the same shape
    `photo_memory.mark_not_animals()` writes for the owner). -> [mark]."""
    import photo_identity
    wanted = [r for r in records if r["verdict"] == "not-animal"]
    if not wanted:
        return []
    by_file, _space = photo_identity.load_detections(Path(workdir) / "embed", pack)
    marks = []
    for r in wanted:
        row = next((row for row, _v in by_file.get(r["path"]) or []
                    if int(row.get("det_index") or 0) == r["det_index"]), None)
        if row is None:
            continue
        marks.append({"sha256": row["sha256"], "det_index": r["det_index"],
                      "box": row.get("box"), "file": Path(r["path"]).name,
                      "by": "agent", "source": f"identify {r['id']}", "at": now})
    return marks


def apply_views(args, workdir, pack, target, index, offered):
    """The agent's verdicts -> `identify[]` records, and on `agree` the name on
    the photo's see-label (through `photo_see`, L2). ⛔ No exemplar, no record
    moved (L3): the registry is only read. A row is honoured only while its
    proposal still STANDS — recomputed here, so a name typed onto a row that
    recognition never proposed, a photo whose thumbnail has gone, or one named
    since, writes nothing."""
    path = Path(args.answers)
    if not path.is_file():
        raise Refused(f"{path} does not exist — nothing written")
    pinned, rows = parse_views(path.read_text(encoding="utf-8"))
    if pinned != pack_id(pack):
        raise Refused(f"{path.name} was written for owner pack {pinned}, and the "
                      f"pack is now {pack_id(pack)} (a confirm, a rename or a pack "
                      "edit) — nothing written. Write the views again:\n"
                      f"  {run_line('photo_index.py', crops=True)} identify \"{workdir}\"")
    bad = [r["id"] for r in rows if r["verdict"] and r["verdict"] not in VERDICTS]
    if bad:
        raise Refused(f"{', '.join(bad)}: a verdict is one of {', '.join(VERDICTS)} "
                      "or blank — nothing written")
    stands = {(p["sample"], p["subject_id"]): p for p in offered}
    known = {r["id"] for r in index.get("identify") or []}
    file_of = {f["source"]: f["file_id"] for f in index["files"]}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    records, refused, blank, seen = [], [], [], set()
    for row in rows:
        if not row["verdict"]:
            blank.append(row["id"])
            continue
        if row["id"] in known:
            continue
        key = (row["sample"], row["subject_id"])
        if key in seen:
            refused.append(f"{row['id']}: {row['subject_id']} is already on another "
                           "row for this photo — an animal is named once (L6)")
            continue
        seen.add(key)
        p = stands.get(key)
        if p is None or file_of.get(p["path"]) is None:
            refused.append(f"{row['id']}: {row['subject_id']} on "
                           f"{Path(row['sample']).name} is not proposed any more "
                           "(not a viewed photo with its thumbnail, already named, "
                           "or recognition no longer accepts it)")
            continue
        if row["verdict"] == "not-animal" and p["det_index"] is None:
            refused.append(f"{row['id']}: `not-animal` marks one CROP, and this "
                           "row is the whole photo")
            continue
        records.append({
            "id": row["id"], "file_id": file_of[p["path"]], "batch": p["batch"],
            "path": p["path"],
            "sample": p["sample"], "subject_id": p["subject_id"],
            "det_index": p["det_index"], "det_count": p["det_count"],
            "proposal": {k: p[k] for k in ("space", "score", "lead",
                                           "runner_up", "verdict")},
            "pinned": pinned, "verdict": row["verdict"], "by": AGENT_CONFIRMED,
            "at": now, "reason": args.reason or "the agent viewed the photo"})
    agreed = [r for r in records if r["verdict"] == "agree"]
    if agreed and args.go:
        import photo_see
        open_for_change(workdir, pack, index, IDENTIFY_CMD)
        out = photo_see.record_confirmed_subject_ids(
            workdir, [(r["sample"], r["subject_id"]) for r in agreed],
            views={(r["sample"], r["subject_id"]): r["id"] for r in agreed})
        failed = set(out["unresolved"]) | set(out["outside_workdir"])
        for r in [r for r in agreed if r["sample"] in failed]:
            refused.append(f"{r['id']}: {Path(r['sample']).name} is not in this work "
                           "dir's see output — nothing written for it")
            records.remove(r)
    counts = {v: sum(1 for r in records if r["verdict"] == v) for v in VERDICTS}
    print(f"identify: {counts['agree']} agree, {counts['no']} no, "
          f"{counts['unsure']} unsure, {counts['not-animal']} not-animal; "
          f"{len(blank)} blank (nothing recorded, left "
          "unnamed; `identify` shows them again)")
    for why in refused:
        print(f"  ⛔ {why} — nothing written for it")
    if not args.go:
        print("DRY RUN — nothing written. Add --go to write.")
        return 1 if refused else 0
    if records:
        if not agreed:
            open_for_change(workdir, pack, index, IDENTIFY_CMD)
        index.setdefault("identify", []).extend(records)
        marks = not_animal_marks_from(workdir, records, now, pack)
        if marks:
            have = {(m.get("sha256"), int(m.get("det_index") or 0))
                    for m in index.get("not_animals") or []}
            index.setdefault("not_animals", []).extend(
                m for m in marks if (m["sha256"], m["det_index"]) not in have)
        log_entry(index, IDENTIFY_CMD,
                  f"{len(records)} view(s): {counts['agree']} agree, {counts['no']} "
                  f"no, {counts['unsure']} unsure, {counts['not-animal']} "
                  "not-animal", args.reason or
                  "D-I11: the agent viewed each photo", by="agent")
        save(target, pack, index)
        print("written; next: `photo_index.py render`, `check`, `freeze`, then "
              "`photo_run.py finish --go`")
    else:
        print("nothing to record")
    return 1 if refused else 0


# ---------------------------------------------------------------------------
# dest — merge into / fill an existing folder (D6)
# ---------------------------------------------------------------------------

def cmd_dest(args):
    """D6: an existing hand-named folder wins. The folder keeps the OWNER's
    name — render never renders over it — and its copy is deduped against the
    folder's own manifest (`--ref`, required for a merge, OA-3). `new` undoes
    it. Logged with the reason, like every change (D-I5)."""
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, index = loaded
    open_for_change(workdir, pack, index, "index dest")
    fo = next((x for x in live(index) if x["id"] == args.folder), None)
    if fo is None or fo["kind"] != "day" or fo.get("days"):
        raise Refused(f"{args.folder} is not a top-level day folder holding whole batches — "
                      "nothing changed")
    if not args.reason.strip():
        raise Refused("--reason is required: every change to the index says why")
    if args.mode == "new":
        if args.path or args.ref:
            raise Refused("`new` takes no path and no --ref")
        dest = {"mode": "new", "existing_path": None, "refs": []}
    else:
        if not args.path:
            raise Refused(f"{args.mode} needs the existing folder's path")
        path = Path(args.path).expanduser().resolve()
        if not path.is_dir():
            raise Refused(f"not an existing directory: {path} — nothing changed")
        refs = []
        for ref in args.ref or []:
            ref_path = Path(ref).expanduser().resolve()
            if not (ref_path / "manifest.csv").exists():
                raise Refused(f"--ref {ref_path} holds no manifest.csv — scan the "
                              "existing folder with photo_scan.py first (it is "
                              "the dedupe reference, OA-3)")
            refs.append(str(ref_path))
        if args.mode == "merge" and not refs:
            raise Refused("a merge needs --ref <the work dir of that folder>: the "
                          "copy is deduped against what it already holds (OA-3)")
        dest = {"mode": args.mode, "existing_path": str(path), "refs": refs}
    old = fo["dest"]["mode"]
    fo.update(dest=dest, rendered=None, validation=None)
    into = f" `{Path(dest['existing_path']).name}`" if dest["existing_path"] else ""
    log_entry(index, "index dest", f"{fo['id']}: {old} → {dest['mode']}{into}",
              args.reason.strip(), by="agent")
    save(target, pack, index)
    print(f"{fo['id']}: {dest['mode']}{into} — run `photo_index.py render` next")
    return 0


# ---------------------------------------------------------------------------
# check — the agent's final check (P4, D-I9)
# ---------------------------------------------------------------------------

COORDINATE_IN_NAME = re.compile(r"-?\d{1,3}\.\d{2,}\s*[, ]\s*-?\d{1,3}\.\d{2,}")


def run_check(workdir, pack, index):
    """-> (problems, warnings). Passes when there are no problems: every copied
    file in one live folder · every name valid · every [who] backed in its own
    folder (the W2-B tree guard, `photo_plan.unbacked_names()` itself) · no
    coordinate and no street address (`photo_cluster.is_address()`, which is
    CJK-only today — a known card) in a name · a structure the export can
    reach: no day two folders hold, no overlapping legs (R1), and no file of a
    batch that no plan settled (R9)."""
    rendered = index.get("render")
    if not rendered:
        return ["the index has not been rendered — run `photo_index.py render`"], []
    problems, warnings = [], page_row_warnings(index)
    r7 = []
    problems += agent_view_problems(workdir, pack, index)
    if rendered["pack_fingerprint"] != pack_id(pack):
        problems.append("the owner pack changed since render (a confirm, a rename "
                        "or a pack edit) — run `photo_index.py render` again")
    files = [f for f in index["files"] if f["status"] == "present"]
    shown = [fo for fo in live(index) if fo["status"] != "empty"]
    live_ids = {fo["id"] for fo in shown}
    unsettled = [f for f in files if not (f["route_source"] or "").startswith(SETTLED)]
    if unsettled:
        problems.append(f"{len(unsettled)} file(s) have no settled route — run "
                        "`photo_index.py render`")
    problems += [f"{Path(f['source']).name} is to be copied but sits in no live folder"
                 for f in files if f["route"] in COPIED and f["folder"] not in live_ids]
    planless = [f for f in files if f["route_source"] == SETTLED + "no-plan"]
    batched = [f for f in planless if f["batch"] is not None]
    if batched:
        # ⛔ R9 — a folder the export does not reach leaves its files here, and
        # they are then simply not copied. It was a warning; it is a problem.
        problems.append(f"{len(batched)} file(s) of a batch were settled by no plan "
                        "— no folder the export reaches holds them, so they would "
                        "not be copied (R9): "
                        + ", ".join(Path(f["source"]).name for f in batched[:5]))
    if len(planless) > len(batched):
        warnings.append(f"{len(planless) - len(batched)} file(s) are in no batch and "
                        "on no no-date list — no plan copies them (as before the index)")
    by_number = {b["batch"]: b for b in json.loads(
        (workdir / "batches.json").read_text(encoding="utf-8")).get("batches", [])}
    problems += structure_problems(index, by_number)

    labels = id_labels(pack)
    names = photo_plan.subject_names(pack)
    by_id = {fo["id"]: fo for fo in index["folders"]}
    first = {}
    for fo in shown:
        name = fo.get("rendered")
        if not name:
            problems.append(f"{fo['id']} has no rendered name — run render")
            continue
        v = fo.get("validation") or {}
        problems += [f"{fo['id']} `{name}`: {r}" for r in v.get("refusals") or []]
        warnings += [f"{fo['id']} `{name}`: {w}" for w in v.get("warnings") or []]
        # ⛔ SURGICAL (M14, Lead ruling 20260922). The `/` rule exists so an
        # UNCHECKED name can never reach the drive. It is excused for exactly
        # ONE name: a bucket whose rendered name IS `photo_plan.undated_rel()`
        # for this index — the same function that built it, so the two cannot
        # drift. Only the `/` test is conditioned: the empty and the
        # stray-space/dot tests below still run on the WHOLE string, and so do
        # the coordinate and street-address checks after this line. It is
        # deliberately NOT an early `continue`, which is how a later edit would
        # silently drop the coordinate check for buckets.
        slash_excused = (fo["kind"] == "bucket" and "/" in name
                         and name == photo_plan.undated_rel(
                             photo_profile.buckets(pack.profile)["to_be_checked"],
                             workdir))
        if (("/" in name and not slash_excused)
                or name.strip(" .") != name or not name):
            problems.append(f"{fo['id']} `{name}` is not a usable folder name")
        if COORDINATE_IN_NAME.search(name):
            problems.append(f"{fo['id']}: a coordinate in the name `{name}` "
                            "(Operational Rule 3)")
        grouped = fo["kind"] != "bucket"
        kept = fo["kind"] == "day" and fo["dest"]["mode"] != "new"
        own = {labels.get(r["ref"]) for r in fo["where"]} if grouped else set()
        for piece in (p for slot in name.split(photo_name.SLOT_SEP)[1:]
                      for p in slot.split(photo_name.NAME_SEP)):
            if not photo_cluster.is_address(piece):
                continue
            if kept or piece in own:
                # ⛔ An owner's own label is USED and warned about, never
                # refused (R13/D-F9) — and so is the owner's own folder name.
                warnings.append(f"{fo['id']}: `{piece}` reads as a street address "
                                "— the owner's own " + ("folder name" if kept else
                                                        "place label") + ", kept")
            else:
                problems.append(f"{fo['id']}: `{piece}` in `{name}` reads as a "
                                "street address")
        if not grouped:
            continue
        parent = by_id.get(fo.get("parent"))
        rel = f"{parent.get('rendered')}/{name}" if parent else name
        if rel in first:
            warnings.append(f"{first[rel]} and {fo['id']} both render `{rel}` — "
                            "their files would land in one folder")
        first.setdefault(rel, fo["id"])
        if parent and parent["kind"] == "fsl-month" and parent["where"] and \
                parent["where"][0]["ref"] not in [r["ref"] for r in fo["where"]]:
            place = parent["where"][0]["ref"]
            warnings.append(f"{fo['id']} `{name}` is a leg of {parent['id']} and is no "
                            f"longer at its place ({labels.get(place) or place}) — a "
                            "relabel moved it (R8)")
        said = what_animal_warning(fo)
        if said:
            r7.append(said)
        path = f"{PLACEHOLDER_ROOT}/{rel}"
        if fo["kind"] in PARENTS:
            legs = {leg["id"]: leg for leg in legs_of(index, fo["id"])}
            rows = [{"SourceFile": f["source"], "_action": "copy",
                     "_dest": f"{path}/{legs[f['folder']]['rendered']}"}
                    for f in files if f["folder"] in legs and f["route"] == ROUTE_COPY]
            batches = sorted({b for leg in legs.values() for b in leg["batches"]})
        else:
            rows = [{"SourceFile": f["source"], "_action": "copy", "_dest": path}
                    for f in files if f["folder"] == fo["id"] and f["route"] == ROUTE_COPY]
            batches = fo["batches"]
        visual = photo_plan.visual_columns(workdir, batches, pack.profile, pack)
        for u in photo_plan.unbacked_names({"dest": {"path": path}}, rows, visual,
                                           names):
            problems.append(f"{fo['id']} `{name}`: {', '.join(u['names'])} — no "
                            "file copied into this folder shows a CONFIRMED "
                            "subject of that name at viewed-image: (F12)")
    said = what_animal_summary(r7)
    if said:
        warnings.append(said)
    return problems, warnings


def agent_view_problems(workdir, pack, index):
    """G7 — every name the AGENT applied rests on its view record: an
    `identify[]` entry of that id, verdict `agree`, the same file and subject,
    and its thumbnail still on disk. ⚠️ The honest limit: this proves a
    thumbnail existed and a verdict was recorded, not that a model looked —
    the same trust `viewed-image:` has always carried."""
    import photo_subjects
    records = {r["id"]: r for r in index.get("identify") or []}
    registry = None
    out = []
    for f in index["files"]:
        for w in f.get("who") or []:
            if w.get("by") != AGENT_CONFIRMED:
                continue
            r = records.get(w.get("view"))
            same = False
            if r is not None and r["file_id"] == f["file_id"]:
                if r["subject_id"] == w.get("subject_id"):
                    same = True
                else:
                    registry = registry or photo_subjects.load(pack=pack)
                    held = registry.get(r["subject_id"])
                    same = held is not None and held.subject_id == w.get("subject_id")
            if not (same and r["verdict"] == "agree"
                    and (workdir / r["sample"]).is_file()):
                out.append(f"{Path(f['source']).name}: {w.get('subject_id')} was named "
                           f"by the agent, and no view record agrees "
                           f"({w.get('view') or 'no view id'}) — a name the agent "
                           "applies rests on a photo it viewed (G7)")
            elif not photo_evidence.is_view_confirmed(w.get("provenance")):
                # G7h — an agreed name the N-4 gate would drop from [who] is
                # said, never lost in silence.
                out.append(f"{Path(f['source']).name}: {w.get('subject_id')} was agreed "
                           f"by the agent ({w.get('view')}), and its provenance is "
                           f"{w.get('provenance')!r}, not a view — it cannot name the "
                           "folder. Record it again: `photo_index.py identify "
                           "--answers ... --go` (G7h)")
    return out


def what_animal_warning(fo):
    """R7 (owner ruling) — a folder carries a [who] and its [what] was picked
    from frames in which the see stage found an animal. -> this folder's entry
    on the one R7 line (`what_animal_summary()`), or None. A WARNING only,
    never a refusal: nothing is dropped and freeze is not blocked. The agent's
    own [what] (set-what) never warns."""
    v = fo.get("validation") or {}
    if not v.get("who") or not v.get("what_animal_files") or agent_what(fo):
        return None
    return (f"{fo['id']} `{fo['rendered']}` ([what] `{v['what_pick']}`, "
            f"{v['what_animal_files']} frame(s))")


def what_animal_summary(entries):
    """W2-8 — ONE line for every R7 folder, with the command once. Per folder
    it fired on clean names: it keys on FRAMES, never on words, because a
    [what] may never be checked against a list (D-F11) — so the line says
    when a change is worth making instead of implying every one is wrong."""
    if not entries:
        return None
    return (f"R7: {len(entries)} folder(s) carry a [who] and a [what] picked from "
            f"frames that show the animal: {'; '.join(entries)}. Change it only if "
            "the keywords describe the pet itself; keywords about the place or "
            "activity are fine. To change one: `photo_index.py group set-what "
            "<work dir> <folder id> \"...\" --reason \"...\"`")


def cmd_check(args):
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, index = loaded
    problems, warnings = run_check(workdir, pack, index)
    for w in warnings:
        print(f"  ⚠️ {w}")
    if problems:
        print(f"check FAILED — {len(problems)} problem(s):")
        for p in problems:
            print(f"  ⛔ {p}")
        log_entry(index, "index check", f"failed: {len(problems)} problem(s)",
                  "; ".join(problems[:3]), by="agent")
        save(target, pack, index)
        return 1
    shown = [fo for fo in live(index) if fo["status"] != "empty"]
    copies = sum(1 for f in index["files"]
                 if f["status"] == "present" and f["route"] in COPIED)
    with_who = sum(1 for fo in shown if (fo.get("validation") or {}).get("who"))
    print(f"check passed: {len(shown)} folder(s), {copies} file(s) to copy, "
          f"{with_who} folder(s) carry a [who], {len(warnings)} warning(s)")
    log_entry(index, "index check", "passed", f"{len(warnings)} warning(s)",
              by="agent")
    save(target, pack, index)
    return 0


# ---------------------------------------------------------------------------
# freeze · verify · unfreeze (D-I16)
# ---------------------------------------------------------------------------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def set_aside_hand_written(workdir, replace):
    """A plans.json freeze did not write is never overwritten unasked; with
    --replace-plans it and every plan file a run left (execute-state included:
    photo_execute would otherwise count those files as copied) move aside."""
    pp = workdir / "plans.json"
    if not pp.exists():
        return
    try:
        old = json.loads(pp.read_text(encoding="utf-8"))
    except ValueError:
        old = {}
    if old.get("generated_by") == GENERATED_BY:
        return
    if not replace:
        raise Refused("this work dir's plans.json was not written by photo_index "
                      "(a hand-written plan) — freezing would overwrite it. "
                      "Nothing written. Pass --replace-plans to move it and its "
                      "plan files aside first.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    aside = workdir / f"plan.bak-{stamp}"
    aside.mkdir()
    shutil.move(str(pp), str(workdir / f"plans.json.bak-{stamp}"))
    moved = 0
    for pattern in PLAN_OUTPUTS:
        for p in sorted((workdir / "plan").glob(pattern)):
            shutil.move(str(p), str(aside / p.name))
            moved += 1
    print(f"moved the hand-written plans.json to plans.json.bak-{stamp} and "
          f"{moved} plan file(s) to {aside.name}/")


def plan_stage(workdir, env, argv, what):
    """Run photo_plan itself: the exported CSVs are written by the real code.
    -> its R12 name-check lines, which it reports and does not stop on."""
    r = subprocess.run([sys.executable, str(HERE / "photo_plan.py"), str(workdir),
                        *argv], capture_output=True, text=True, env=env)
    if r.returncode:
        raise Refused(f"photo_plan refused {what} — nothing frozen:\n"
                      + (r.stdout + r.stderr)[-800:])
    return [f"{what}: {line.strip()}" for line in r.stderr.splitlines()
            if "NAME CHECK FAILED" in line]


def new_folder_name_problems(workdir, index, plans, by_number, expected, profile):
    """B3 — [(name, reason)] for every name the freeze would write that fails
    photo_plan's name check AND is for a folder not yet on the drive.

    The owner's ruling (B3, 20260918): a failed name check stops the freeze. A folder
    already on the drive keeps the report-only path photo_plan has always had
    (D10): its name is the one there — a hand-named merge target, or a folder
    an earlier run of this dump copied into — and refusing it would block a
    re-plan of accepted work. On the drive means: the plan merges into or
    fills an existing folder, a copy recorded in any execute-state already
    landed in it, or the directory exists.

    Each folder is judged on the days it KEEPS (the index's own files), never
    on its batches' span — that is what made a `group split`'s parent fail
    while the pieces, the names that were wrong, went unchecked (B3b)."""
    day = {f["source"]: (f.get("date") or "")[:10] for f in index["files"]}
    rows = [{"_action": a, "_dest": d, "_day": day.get(src, "")}
            for src, (a, d, _n) in expected.items() if day.get(src)]
    landed = {path_key(v["dest"]).rsplit("/", 1)[0] for v in
              photo_execute.verified_anywhere(workdir / "plan").values() if v.get("dest")}
    budget = photo_profile.name_budget(profile)
    out, seen = [], set()
    for plan in plans:
        top = plan["dest"]["path"]
        batches = [by_number[n] for n in plan["batches"] if n in by_number]
        for path, name, refusals, _w in photo_plan.folder_name_checks(
                plan, batches, *budget, rows=rows):
            if path in seen:
                continue
            seen.add(path)
            # ⛔ The work dir's own facts first: an unmounted drive answers
            # is_dir() False and must never turn a folder already copied into
            # a "new" one, so the disk can only ADD an exemption.
            key = path_key(path)
            on_drive = ((plan["dest"]["mode"] != "new"
                         and (path == top or path.startswith(top + "/")))
                        or any(d == key or d.startswith(key + "/") for d in landed)
                        or Path(path).is_dir())
            if not on_drive:
                out += [(name, r) for r in refusals]
    return out


def freeze_outputs(workdir):
    """-> {path: (bytes, mtime)} of every file a freeze or the photo_plan runs
    it makes may write: plans.json, batches.json and its .bak, everything in plan/."""
    paths = [workdir / "plans.json", workdir / "batches.json",
             workdir / "batches.json.bak", *(workdir / "plan").rglob("*")]
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths if p.is_file()}


def expected_rows(index, paths, dest_root):
    """SourceFile -> (action, destination, file name) the freeze promises.
    `paths` is every folder's destination (`unit_paths`)."""
    folders = {fo["id"]: fo for fo in index["folders"]}
    out = {}
    for f in index["files"]:
        if f["status"] != "present":
            continue
        if f["route"] == ROUTE_COPY:
            out[f["source"]] = ("copy", paths[f["folder"]], f["dest_name"])
        elif f["route"] in COPIED:
            out[f["source"]] = ("copy", f"{dest_root}/{folders[f['folder']]['rendered']}",
                                f["dest_name"])
        elif f["route"] == "skip_dupe":
            out[f["source"]] = ("skip_dupe", f["dupe_of"], None)
        elif f["route"] == "skip_junk":
            out[f["source"]] = ("skip_junk", "", None)
    return out


def compare_exports(workdir, expected, csvs):
    """Every row photo_plan wrote must be the row the index holds, once."""
    seen, bad = {}, []
    for rel in csvs:
        with open(workdir / rel, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                src = r["SourceFile"]
                got = (r["action"], r["destination"],
                       r["FileName"] if r["action"] == ROUTE_COPY else None)
                want = expected.get(src)
                if src in seen:
                    bad.append(f"{Path(src).name}: in {seen[src]} and in {rel}")
                elif want is None:
                    bad.append(f"{Path(src).name}: in {rel}, not in the index")
                elif got != want:
                    bad.append(f"{Path(src).name}: the index says {want[0]} → "
                               f"{Path(want[1]).name}/{want[2] or ''}; {rel} says "
                               f"{got[0]} → {Path(got[1]).name}/{got[2] or ''}")
                seen[src] = rel
    bad += [f"{Path(src).name}: in the index, in no plan file"
            for src in expected if src not in seen]
    if bad:
        raise Refused(f"the plan files photo_plan wrote disagree with the index "
                      f"in {len(bad)} place(s) — nothing frozen:\n"
                      + "\n".join(f"  ⛔ {b}" for b in bad[:10]))


RENAMES_MD = "folder-renames.md"


def earlier_copies_elsewhere(workdir, expected, dest_root):
    """FIX8 F8-2 — files an earlier run copied to a folder this freeze names
    differently. photo_execute counts a copied file as done, whichever plan
    copied it, so nothing is copied again; what the owner must do is rename.

    -> (renames, refused). `renames` is [{"old", "new"}] relative to
    dest_root, one line per folder at the HIGHEST level that changed (a
    renamed trip is one line, not one per leg), parents first. `refused` is
    [(old folder, [new folders], [files])] for what a rename cannot express —
    a folder split or merged after its copy (owner ruling D4) — plus
    [(place, [], [files])] for a copy outside dest_root or under another file
    name. Only reads the work dir; the drive is never touched."""
    root = Path(dest_root)
    rows = []
    for sp in sorted((workdir / "plan").glob("execute-state_*.json")):
        verified = json.loads(sp.read_text(encoding="utf-8")).get("verified") or {}
        for src, v in verified.items():
            want = expected.get(src)
            if want and want[0] == ROUTE_COPY:
                rows.append((src, Path(v.get("dest") or ""), Path(want[1]), want[2]))
    if all(old == new / name for _s, old, new, name in rows):
        return [], []

    def parts(path):
        try:
            return path.relative_to(root).parts
        except ValueError:
            return None

    odd, olds, news, files = {}, {}, {}, {}
    for src, old, new, name in rows:
        o, n = parts(old.parent), parts(new)
        if o is None or n is None or len(o) != len(n) or not o or old.name != name:
            if old != new / name:
                odd.setdefault(str(old.parent), []).append(Path(src).name)
            continue
        for i in range(len(o)):
            olds.setdefault(o[:i + 1], set()).add(n[:i + 1])
            news.setdefault(n[:i + 1], set()).add(o[:i + 1])
        files.setdefault(o, []).append(Path(src).name)
    refused = [(k, [], sorted(v)) for k, v in sorted(odd.items())]
    tangled = {o for o, ns in olds.items() if len(ns) > 1}
    tangled |= {o for n, os_ in news.items() if len(os_) > 1 for o in os_}
    for o in sorted(tangled, key=lambda x: (len(x), x)):
        if any(o[:i] in tangled for i in range(1, len(o))):
            continue
        held = sorted(f for k, v in files.items() if k[:len(o)] == o for f in v)
        refused.append(("/".join(o), sorted("/".join(n) for n in olds[o]), held))
    if refused:
        return [], refused
    renames = []
    for o, (n,) in sorted(olds.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if o[-1] != n[-1]:
            renames.append({"old": "/".join(n[:-1] + o[-1:]), "new": "/".join(n)})
    return renames, []


def cmd_freeze(args):
    t0 = time.time()
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, index = loaded
    if index.get("frozen"):
        why = freeze_problem(workdir, pack, index)
        if why is None:
            print(f"already frozen — {index['frozen']['hash']} still holds")
            return 0
        lift(index, "index freeze", f"the freeze was stale: {why}")
    problems, _warnings = run_check(workdir, pack, index)
    if problems:
        raise Refused(f"the check fails — nothing frozen ({len(problems)} "
                      "problem(s); `photo_index.py check` lists them):\n"
                      + "\n".join(f"  ⛔ {p}" for p in problems[:10]))
    by_number = {b["batch"]: b for b in json.loads(
        (workdir / "batches.json").read_text(encoding="utf-8")).get("batches", [])}
    units = export_units(index, by_number)
    for fo in (u["top"] for u in units):
        if fo["dest"]["mode"] != "new" and not Path(fo["dest"]["existing_path"]).is_dir():
            raise Refused(f"{fo['id']}: the {fo['dest']['mode']} target is no "
                          f"longer a directory: {fo['dest']['existing_path']} — "
                          "nothing frozen")
    dest_root = photo_plan.resolve_dest_root(workdir, None, pack.profile)
    labels = id_labels(pack)
    paths = unit_paths(units, dest_root, real=True)
    expected = expected_rows(index, paths, dest_root)
    # FIX8 F8-2 — BEFORE anything is written: a refused freeze leaves plans.json
    # and plan/ exactly as they were.
    renames, refused = earlier_copies_elsewhere(workdir, expected, dest_root)
    if refused:
        n = sum(len(fs) for _o, _n, fs in refused)
        lines = []
        for old, new, fs in refused:
            where = (f'"{old}" -> ' + ", ".join(f'"{x}"' for x in new) if new
                     else f'"{old}" (not a folder this freeze can rename)')
            lines.append(f"  {where}: {', '.join(fs[:10])}"
                         + (f" and {len(fs) - 10} more" if len(fs) > 10 else ""))
        raise Refused(f"{n} file(s) were copied by an earlier run into a folder "
                      "that has since been split or merged (or copied to a place "
                      "this freeze does not name). A folder renamed after its "
                      "copy can be locked; this cannot, and the engine never "
                      "renames or moves anything on the drive. Nothing frozen, "
                      "nothing written:\n" + "\n".join(lines))
    plans = []
    for u in (u for u in units if u["batches"]):
        plan = unit_plan(u, len(plans) + 1, paths,
                         words=lambda fo: where_words(fo, labels)[0])
        plans.append({"plan": plan["plan"], "title": u["top"]["rendered"],
                      "folder": u["top"]["id"], **plan})
    bad_names = new_folder_name_problems(workdir, index, plans, by_number,
                                         expected, pack.profile)
    if bad_names:
        raise Refused(f"{len(bad_names)} folder name(s) this freeze would write "
                      "for the first time fail the name check. Nothing frozen, "
                      "nothing written — change the name (`group`, `relabel`, "
                      "`set-what`, then `render`) and freeze again:\n"
                      + "\n".join(f"  ⛔ {n}: {r}" for n, r in bad_names))
    set_aside_hand_written(workdir, args.replace_plans)
    body = {"generated_by": GENERATED_BY, "index": index["dump"],
            "dest_root": dest_root, "plans": plans}
    if renames:
        body[photo_execute.RENAMES_KEY] = renames
    kept = freeze_outputs(workdir)
    exported, said = ["plans.json"], []
    try:
        write_json(workdir / "plans.json", body)
        env = pack_env(pack)
        extra = ["--no-vision"] if index["render"].get("no_vision") else []
        for p in plans:
            said += plan_stage(workdir, env, ["--plan", str(p["plan"]), *extra],
                               f"P{p['plan']} ({p['folder']})")
            exported.append(f"plan/plan_P{p['plan']}-files.csv")
        if (workdir / "no-date-files.csv").exists():
            said += plan_stage(workdir, env, ["--no-date"], "the no-date plan")
            exported.append("plan/plan_no-date-files.csv")
        compare_exports(workdir, expected, exported[1:])
    except Refused:
        # Everything the freeze and photo_plan write, put back as it was: a
        # refusal writes nothing (FIX8 F8-2). That includes the batch statuses
        # — photo_plan advances each plan's batches as it goes, so a refusal at
        # a later plan used to leave the earlier ones demoted (M5).
        now = freeze_outputs(workdir)
        for p in now:
            if p not in kept:
                p.unlink()
        for p, (data, mtime) in kept.items():
            if now.get(p) != (data, mtime):
                p.write_bytes(data)
                os.utime(p, ns=(mtime, mtime))
        raise
    renames_md = workdir / "plan" / RENAMES_MD
    if renames:
        renames_md.write_text(
            "# Folders to rename by hand\n\n"
            "Copied before their names changed. Rename each one on the drive, "
            f"in this order, under `{dest_root}` — the engine never renames a "
            "folder, and it copies nothing new into one still to rename.\n\n"
            + "".join(f'- "{r["old"]}" -> "{r["new"]}"\n' for r in renames),
            encoding="utf-8")
    elif renames_md.exists():
        renames_md.unlink()

    todo = [f for f in index["files"] if f["status"] == "present" and f["route"] in COPIED]
    for f in todo:
        try:
            f["sha256"] = sha256_file(f["source"])
        except OSError as exc:
            raise Refused(f"cannot read {f['source']}: {exc} — nothing frozen")
    distinct = len({f["sha256"] for f in todo})
    before = index["phase"]
    index["phase"] = PHASE_FINAL
    index["pack_fingerprint"] = pack_id(pack)
    digest = freeze_hash(workdir, index, exported)
    seconds = round(time.time() - t0, 1)
    index["frozen"] = {"hash": digest, "pack_fingerprint": index["pack_fingerprint"],
                       "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "phase_before": before, "dest_root": dest_root,
                       "files": exported, "seconds": seconds,
                       "plans": {str(p["plan"]): p["folder"] for p in plans}}
    log_entry(index, "index freeze",
              f"{len(plans)} plan(s), {len(todo)} file(s) to copy ({distinct} "
              f"distinct SHA-256) in {seconds} s",
              (getattr(args, "reason", None) or "").strip()
              or "the final check passed (D-I9); the names are locked (D-I16)",
              by="agent")
    save(target, pack, index)
    print(f"frozen {digest} in {seconds} s")
    if renames:
        print(f"{len(renames)} folder(s) already copied carry an old name. Rename "
              "each one by hand on the drive, in this order — the engine never "
              "renames a folder:")
        for r in renames:
            print(f'  "{r["old"]}" -> "{r["new"]}"')
        print(f"The list is kept in plan/{RENAMES_MD}.")
    print(f"  {len(plans)} plan(s) exported to plans.json; {len(todo)} file(s) to "
          f"copy, {distinct} distinct SHA-256; dest root {dest_root}")
    for line in said:
        print(f"  photo_plan's own name check: {line}")
    dump = finish_target(workdir)
    print(f"next: photo_run.py finish {dump}        # dry run: previews the copy "
          "and where --go would stop; writes nothing\n"
          f"      photo_run.py finish {dump} --go")
    return 0


def finish_target(workdir):
    """N3 — how to name this dump to `photo_run.py finish`: the dump's own name
    when `finish` run from here resolves that name back to this work dir (a
    collection workspace), else the full path, which always does."""
    for cand in (Path.cwd() / "Working Files", Path.cwd()):
        if (cand / "collection.json").exists():
            if (cand / workdir.name).resolve() == Path(workdir).resolve():
                return f'"{workdir.name}"' if " " in workdir.name else workdir.name
            break
    return f'"{workdir}"'


def copy_check(workdir, index):
    """After the copy: every SHA-256 photo_execute verified is the one frozen."""
    frozen = index["frozen"]
    sha = {f["source"]: f["sha256"] for f in index["files"] if f.get("sha256")}
    labels = [f"P{n}" for n in sorted(frozen["plans"], key=int)]
    if "plan/plan_no-date-files.csv" in frozen["files"]:
        labels.append("no-date")
    copied, wrong, absent = 0, [], []
    # Every state file: a file copied under another plan number is copied
    # (FIX8 F8-2 — a merge after a copy renumbers the plans).
    verified = photo_execute.verified_anywhere(workdir / "plan")
    for label in labels:
        with open(workdir / "plan" / f"plan_{label}-files.csv", newline="",
                  encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["action"] != ROUTE_COPY:
                    continue
                v = verified.get(r["SourceFile"])
                if v is None:
                    absent.append(f"{Path(r['SourceFile']).name} ({label})")
                    continue
                copied += 1
                if v.get("sha256") != sha.get(r["SourceFile"]):
                    wrong.append(f"{Path(r['SourceFile']).name} ({label})")
    print(f"copy check: {copied} file(s) copied; {copied - len(wrong)} match the "
          f"SHA-256 frozen at {frozen['at']}"
          + (f"; {len(absent)} not copied" if absent else ""))
    for w in wrong[:10]:
        print(f"  ⛔ changed since the freeze: {w}")
    for a in absent[:10]:
        print(f"  ⚠️ not copied: {a}")
    plans = json.loads((workdir / "plans.json").read_text(encoding="utf-8"))
    todo = photo_execute.renames_to_do(plans, frozen["dest_root"])
    if todo:
        # Said, not failed: the copy is complete; the owner's renames are a
        # step of their own, and nothing new is copied into those folders
        # until they are done.
        print(f"  ⚠️ {len(todo)} folder rename(s) still to do on the drive "
              f"(plan/{RENAMES_MD}):")
        for old, new in todo:
            print(f'    "{old}" -> "{new}"')
    return 1 if wrong or absent else 0


def cmd_verify(args):
    """-> 0 while the freeze holds, EXIT_STALE when it does not. Read-only."""
    workdir = Path(args.workdir).resolve()
    pointer = read_pointer(workdir)
    if not pointer:
        print("no index for this work dir — nothing to verify")
        return 0
    pack = photo_profile.resolve_pack(workdir=workdir, explicit=args.profile)
    target = index_dir(pack, pointer["dump_key"]) if pack.dir else None
    if (target is None or pointer.get("owner") != pack.owner
            or not (target / INDEX_NAME).exists()):
        print("⛔ this work dir points at an index no bound owner pack holds — "
              "the freeze cannot be checked")
        return EXIT_STALE
    index = json.loads((target / INDEX_NAME).read_text(encoding="utf-8"))
    why = freeze_problem(workdir, pack, index)
    pack_only = why and args.copied and not freeze_problem(
        workdir, pack, index, ignore_pack=True)
    if why and not pack_only:
        print(f"⛔ the freeze does not hold: {why}")
        return EXIT_STALE
    if args.copied:
        rc = copy_check(workdir, index)
        if rc or not pack_only:
            return rc
        # F-mm — the drive is checked and fine; only the pack moved.
        print(f"⚠️ {why}. Every copied file above matches its freeze, so the "
              "drive is fine — but the folder NAMES may differ on a re-lock. "
              "To bring this dump up to the pack: render, check, freeze, "
              f"then verify --copied again (exit {EXIT_PACK_MOVED}, not "
              f"{EXIT_STALE}: nothing here is stale on the drive).")
        return EXIT_PACK_MOVED
    print(f"the freeze holds: {index['frozen']['hash']} · pack "
          f"{index['frozen']['pack_fingerprint']}")
    return 0


def cmd_unfreeze(args):
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, index = loaded
    if not index.get("frozen"):
        print("the index is not frozen")
        return 0
    if not args.reason.strip():
        raise Refused("--reason is required: every change to the index says why")
    lift(index, "index unfreeze", args.reason.strip(), by="agent")
    save(target, pack, index)
    print("freeze lifted — render, check and freeze again before copying")
    return 0


# ---------------------------------------------------------------------------
# view
# ---------------------------------------------------------------------------

def cell(text):
    return str(text).replace("|", "\\|")


def backs_a_name(s):
    return s.get("confirmed") and photo_evidence.is_view_confirmed(s.get("provenance"))


def render_view(index, digest, labels, names):
    files = [f for f in index["files"] if f["status"] == "present"]
    folders = [fo for fo in live(index) if fo["status"] != "empty"]
    by_id = {fo["id"]: fo for fo in index["folders"]}
    by_folder = {}
    for f in files:
        by_folder.setdefault(f["folder"], []).append(f)
    with_who = sum(1 for fo in folders if (fo.get("validation") or {}).get("who"))
    source = [f["route_source"] or "" for f in files]
    settled = sum(1 for s in source if s.startswith(SETTLED))
    provisional = sum(1 for s in source if s.startswith(PROVISIONAL))
    frozen = index.get("frozen")
    out = [f"# Index — {index['dump']}", "",
           "Generated from `index.json`; never read back. Change it only through "
           "`photo_index.py` commands.", "",
           f"- dump `{index['dump']}` · owner `{index['owner']}` · phase "
           f"`{index['phase']}` · cluster generation {index['cluster_gen']}",
           # FIX7 (F5-a): the top-level id is the one init, recut and freeze
           # write, so after a render it still shows the freeze's pack and
           # read as stale. Render's own id is shown beside it; `check` reads
           # that one (`rendered["pack_fingerprint"]`, :2042).
           f"- index `{digest}` · pack `{index['pack_fingerprint']}`"
           + (f" · rendered with pack `{index['render']['pack_fingerprint']}`"
              if (index.get("render") or {}).get("pack_fingerprint") else ""),
           (f"- FROZEN `{frozen['hash']}` at {frozen['at']} — `finish --go` "
            "copies exactly this" if frozen else "- not frozen"),
           f"- files {len(files)} ({len(index['files']) - len(files)} missing) · "
           f"folders {len(folders)} · folders with a [who] {with_who} · routes "
           f"settled {settled}, provisional {provisional}, not yet "
           f"{len(files) - settled - provisional}", "",
           "## Folders", ""]
    for fo in folders:
        legs = [leg for leg in folders if leg.get("parent") == fo["id"]]
        members = sorted((f for leg in legs for f in by_folder.get(leg["id"], []))
                         if fo["kind"] in PARENTS else by_folder.get(fo["id"], []),
                         key=lambda f: (f["date"] or "", f["source"]))
        dates = [f["date"][:10] for f in members if f["date"]]
        span = (f"{min(dates)} → {max(dates)}" if dates and min(dates) != max(dates)
                else (dates[0] if dates else "no date"))
        where = " + ".join(
            (r["ref"][4:] if r["ref"].startswith("map:") else
             f"{r['ref'][len(AGENT_REF):]} (agent)" if r["ref"].startswith(AGENT_REF)
             else f"{labels.get(r['ref'], '(no label)')} [{r['ref']}]")
            for r in fo["where"]) or "—"
        heading = fo["rendered"] or "(not rendered yet)"
        if fo["kind"] == "bucket":
            # M14: the undated stills bucket has no month by design — say
            # so; an owner reading "None" reads a bug.
            title = (f"bucket `{fo['bucket_key']}` · {fo['month']}"
                     if fo['month'] else
                     f"bucket `{fo['bucket_key']}` · no month (undated)")
        elif fo["kind"] in PARENTS:
            title = (f"{fo['kind']} · where: {where} · legs: "
                     f"{', '.join(leg['id'] for leg in legs) or '—'}")
        elif fo["kind"] == "leg":
            parent = by_id.get(fo["parent"]) or {}
            title = f"leg of {fo['parent']} · where: {where}"
            heading = f"{parent.get('rendered') or fo['parent']}/{heading}"
        else:
            title = f"day · where: {where}"
            if fo["dest"]["mode"] != "new":
                title += (f" · {fo['dest']['mode']} into "
                          f"`{Path(fo['dest']['existing_path']).name}`")
        v = fo.get("validation") or {}
        who = ", ".join(f"{w['name']} ({w['files']})" for w in v.get("who") or [])
        what = (f"{agent_what(fo)} (agent)" if agent_what(fo)
                else v.get("what_pick") or "—")
        out += [f"### {fo['id']} · {heading} ({len(members)} file(s))", "",
                f"- {title} · period: {span} (from the files) · who: {who or '—'} "
                f"· what: {what}"]
        out += [f"- ⛔ {cell(r)}" for r in v.get("refusals") or []]
        out += [f"- ⚠️ {cell(w)}" for w in v.get("warnings") or []]
        if fo["kind"] in PARENTS:
            out += ["", "Its files are listed under its legs.", ""]
            continue
        out += ["", "| file | date | date source | route | who |",
                "|---|---|---|---|---|"]
        for f in members:
            shown = ", ".join(names.get(s["subject_id"], s["subject_id"] or "?")
                              for s in f.get("who") or [] if backs_a_name(s))
            route = (f["route"] or "—") + (
                " (provisional)" if (f["route_source"] or "").startswith(PROVISIONAL)
                else "")
            out.append(f"| {cell(Path(f['source']).name)} | {f['date'] or '—'} | "
                       f"{f['date_source'] or '—'} | {route} | {shown or '—'} |")
        out.append("")
    retired = [fo for fo in index["folders"] if fo["status"] == RETIRED]
    if retired:
        out += ["## Retired folders (a re-cut or a grouping replaced them)", ""] + [
            f"- {fo['id']} ({fo['kind']})"
            + (f" → merged into {fo['merged_into']}" if fo.get("merged_into") else "")
            for fo in retired] + [""]
    split = [fo for fo in live(index) if fo.get("split_from")]
    if split:
        out += ["## Split folders", ""] + [
            f"- {fo['id']} split from {fo['split_from']}" for fo in split] + [""]
    skipped = [f for f in files if f["folder"] is None]
    if skipped:
        out += ["## Not copied", ""] + [
            f"- {cell(Path(f['source']).name)} — {f['route'] or 'no folder'}"
            for f in skipped] + [""]
    out += ["## Phase log", "", "| at | phase | by | command | change | reason |",
            "|---|---|---|---|---|---|"]
    out += [f"| {e['at']} | {e['phase']} | {e['by']} | {cell(e['cmd'])} | "
            f"{cell(e['change'])} | {cell(e['reason'])} |" for e in index["log"]]
    named = [fo for fo in folders if fo["kind"] != "bucket"]
    if frozen:
        nxt = ("Frozen. `photo_run.py finish <work dir> --go` copies from this "
               "freeze; a change to the index, the exported plan files or the "
               "pack makes it refuse (exit 4).")
    elif named and all(fo["rendered"] for fo in named):
        nxt = "Rendered. Run `photo_index.py check`, then `photo_index.py freeze`."
    else:
        nxt = ("After the batch pages and the agent's identify views, run "
               "`photo_index.py render`, then `check` and `freeze`; "
               "`finish --go` copies from the freeze.")
    out += ["", "## Next", "", nxt, ""]
    return "\n".join(out)


def write_view(target, pack):
    import photo_subjects
    index = json.loads((target / INDEX_NAME).read_text(encoding="utf-8"))
    labels = {k: v or "(unnamed)" for k, v in id_labels(pack).items()}
    registry = photo_subjects.load(pack=pack)
    names = {}
    for f in index["files"]:
        for s in f.get("who") or []:
            sid = s.get("subject_id")
            if sid and sid not in names:
                known = registry.get(sid)
                names[sid] = known.name if known is not None and known.name else sid
    (target / VIEW_NAME).write_text(
        render_view(index, index_hash(target / INDEX_NAME), labels, names),
        encoding="utf-8")


def cmd_view(args):
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, _index = loaded
    write_view(target, pack)
    print(f"wrote {target / VIEW_NAME}")
    return 0


# ---------------------------------------------------------------------------
# group — the agent adjusts the folder structure (D-I8, G5)
# ---------------------------------------------------------------------------

def fsl_month_min_visits(profile):
    """R4 — the fewest visits in one month that make a monthly parent, from
    the pack (`cluster_defaults.fsl_month_min_visits`) or the code default
    of 3. Never below two: a parent of one leg groups nothing."""
    value = photo_profile.get(profile, "cluster_defaults", MIN_VISITS_KEY,
                              default=None)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return FSL_MONTH_MIN_VISITS_DEFAULT
    return max(value, FSL_MONTH_MIN_VISITS_FLOOR)


def agent_text(text, what, slot):
    """An agent-given name part, checked as a rendered name part is (R5)."""
    text = (text or "").strip()
    seps = (photo_name.SLOT_SEP, "/") + ((photo_name.NAME_SEP,) if slot == "where" else ())
    if not text:
        raise Refused(f"{what} is empty — nothing changed")
    held = [c for c in seps if c in text]
    if held:
        raise Refused(f"{what} {text!r} holds {' '.join(repr(c) for c in held)}, a "
                      "separator of the folder-name grammar — nothing changed")
    if COORDINATE.match(text) or COORDINATE_IN_NAME.search(text):
        raise Refused(f"{what} reads as a coordinate (Operational Rule 3) — "
                      "nothing changed")
    if photo_cluster.is_address(text):
        raise Refused(f"{what} {text!r} reads as a street address — nothing changed")
    return text


def group_target(index, fid, allow=HOLDERS):
    """-> the live folder `fid`, refused unless its kind is in `allow`. ⛔ A
    bucket is refused naming its files' route: a screenshot, a paperwork
    still, a no-date file or an unknown format never moves into an event
    folder (G10)."""
    fo = next((x for x in live(index) if x["id"] == fid), None)
    if fo is None:
        raise Refused(f"{fid} is not a live folder of this index — nothing changed")
    if fo["kind"] == "bucket":
        routes = sorted({f["route"] or "not decided" for f in index["files"]
                         if f["folder"] == fid}) or [BUCKET_ROUTE.get(fo["bucket_key"],
                                                                     fo["bucket_key"])]
        of = (f"of {fo['month']}" if fo['month'] else "with no month (undated)")
        raise Refused(f"{fid} is the `{fo['bucket_key']}` bucket {of}: its "
                      f"files' route is {', '.join(routes)}, and a file whose route is "
                      "not `copy` stays in its bucket (G10) — nothing changed")
    if fo["kind"] not in allow:
        raise Refused(f"{fid} is a {fo['kind']} folder; this command takes "
                      f"{' or '.join(allow)} — nothing changed")
    if fo["dest"]["mode"] != "new":
        raise Refused(f"{fid} goes into an existing folder ({fo['dest']['mode']}, D6) "
                      f"— `photo_index.py dest <work dir> {fid} new` first. Nothing "
                      "changed.")
    return fo


def parse_days(text):
    days = {d.strip() for d in (text or "").split(",") if d.strip()}
    bad = sorted(d for d in days if not DATE.match(d))
    if not days or bad:
        raise Refused(f"--dates takes YYYY-MM-DD[,YYYY-MM-DD...]: {', '.join(bad) or text!r}"
                      " — nothing changed")
    return days


def move_files(index, src, dst, days, cmd, reason):
    """Every present file `src` holds (on `days`, or all) now sits in `dst`,
    with a history entry and a log line each. A file in a bucket or in no
    folder is never touched. -> how many moved."""
    moved = 0
    for f in index["files"]:
        if f["status"] == "present" and f["folder"] == src and (
                days is None or (f["date"] and f["date"][:10] in days)):
            f["folder"] = dst
            f["history"].append({"phase": index["phase"], "folder": dst,
                                 "by": cmd, "reason": reason})
            log_entry(index, cmd, f"{f['file_id']} {Path(f['source']).name}: "
                      f"{src} → {dst}", reason, by="agent")
            moved += 1
    return moved


def settle_structure(index, owned, touched, by_number, cmd, reason):
    """Write the days back, retire a holder left with none and a parent left
    with no leg, clear the names that changed, and refuse (nothing saved) a
    structure the export could not reach."""
    write_claims(index, owned)
    by_id = {fo["id"]: fo for fo in index["folders"]}
    for fid in touched:
        fo = by_id[fid]
        if fo["kind"] in HOLDERS and fo["status"] != RETIRED and not owned.get(fid):
            fo["status"] = RETIRED
            log_entry(index, cmd, f"{fid} retired: it holds no day any more"
                      + (f" (merged into {fo['merged_into']})" if fo.get("merged_into")
                         else ""), reason, by="agent")
    for p in parents(index):
        if not legs_of(index, p["id"]):
            p["status"] = RETIRED
            log_entry(index, cmd, f"{p['id']} retired: it has no leg any more",
                      reason, by="agent")
    lifted = set(touched) | {by_id[t].get("parent") for t in touched} - {None}
    for fid in lifted:
        by_id[fid].update(rendered=None, validation=None)
    broken = structure_problems(index, by_number)
    if broken:
        raise Refused(f"{cmd} would leave a structure the export cannot reach — "
                      "nothing changed:\n" + "\n".join(f"  ⛔ {p}" for p in broken[:10]))


def group_make_trip(index, args, pack, by_number, cmd, reason):
    ids = list(dict.fromkeys(args.folders))
    if len(ids) < 2:
        raise Refused("a trip needs two or more day folders — nothing changed")
    legs = [group_target(index, fid, allow=("day",)) for fid in ids]
    where = agent_text(args.where, "--where", "where")
    what = agent_text(args.what, "--what", "what") if args.what is not None else None
    owned = claims(index)
    pid, ref = next_folder_id(index), AGENT_REF + where
    parent = new_folder(pid, "trip", where=[{"ref": ref}])
    parent["what"] = {"text": what, "source": AGENT} if what else None
    index["folders"].append(parent)
    index["places"].setdefault(ref, {"kind": AGENT, "text": where})
    for leg in legs:
        leg.update(kind="leg", parent=pid)
        log_entry(index, cmd, f"{leg['id']} → a leg of {pid}", reason, by="agent")
    settle_structure(index, owned, [pid] + ids, by_number, cmd, reason)
    log_entry(index, cmd, f"{pid}: a trip at `{where}` with {len(ids)} leg(s) "
              f"({', '.join(ids)})", reason, by="agent")
    return f"{pid}: a trip at {where!r} with legs {', '.join(ids)}"


def group_make_fsl_month(index, args, pack, by_number, cmd, reason):
    ref = args.place.strip()
    if not FSL_REF.match(ref):
        raise Refused(f"{ref!r} is not a frequent place id — a monthly parent is "
                      "made only for a place the owner named (fsl-NNNN), never for "
                      "a map word (R3). Nothing changed.")
    label = id_labels(pack).get(ref)
    if not label:
        raise Refused(f"the owner pack holds no labelled frequent place {ref} — "
                      "nothing changed")
    if not re.fullmatch(r"\d{4}-\d{2}", args.month or ""):
        raise Refused(f"the month is YYYY-MM, not {args.month!r} — nothing changed")
    month = args.month.replace("-", "")
    for p in parents(index):
        if p["kind"] == "fsl-month" and p["month"] == month and \
                [r["ref"] for r in p["where"]] == [ref]:
            raise Refused(f"{p['id']} is already the {args.month} parent of {ref} — "
                          "nothing changed")
    owned = claims(index)
    visits, across = [], []
    for fo in live(index):
        if fo["kind"] != "day" or fo.get("parent") or \
                ref not in [r["ref"] for r in fo["where"]]:
            continue
        months = {d[:7].replace("-", "") for d in owned[fo["id"]]}
        if months == {month}:
            visits.append(fo["id"])
        elif month in months:
            across.append(fo["id"])
    need = fsl_month_min_visits(pack.profile)
    note = (f"; not counted, they run into another month: {', '.join(across)}"
            if across else "")
    if len(visits) < need:
        raise Refused(f"{len(visits)} visit(s) to {ref} ({label}) in {args.month}; a "
                      f"monthly parent needs {need} (the pack's "
                      f"`cluster_defaults.{MIN_VISITS_KEY}`){note} — nothing changed")
    what = agent_text(args.what, "--what", "what") if args.what is not None else None
    legs = [group_target(index, fid, allow=("day",)) for fid in visits]
    pid = next_folder_id(index)
    parent = new_folder(pid, "fsl-month", where=[{"ref": ref}], month=month)
    parent["what"] = {"text": what, "source": AGENT} if what else None
    index["folders"].append(parent)
    for leg in legs:
        leg.update(kind="leg", parent=pid)
        log_entry(index, cmd, f"{leg['id']} → a leg of {pid}", reason, by="agent")
    settle_structure(index, owned, [pid] + visits, by_number, cmd, reason)
    log_entry(index, cmd, f"{pid}: {args.month} at {ref} with {len(visits)} visit(s) "
              f"({', '.join(visits)}){note}", reason, by="agent")
    return f"{pid}: {args.month} at {label} ({ref}) with legs {', '.join(visits)}{note}"


def group_move(index, args, pack, by_number, cmd, reason):
    src, dst = group_target(index, args.source), group_target(index, args.to)
    if src is dst:
        raise Refused("--to is the folder the days are in — nothing changed")
    days = parse_days(args.dates)
    owned = claims(index)
    missing = sorted(days - owned[src["id"]])
    if missing:
        raise Refused(f"{', '.join(missing)}: not a day {src['id']} holds — nothing "
                      "changed")
    owned[src["id"]] -= days
    owned[dst["id"]] |= days
    moved = move_files(index, src["id"], dst["id"], days, cmd, reason)
    if not owned[src["id"]]:
        src["merged_into"] = dst["id"]
    settle_structure(index, owned, [src["id"], dst["id"]], by_number, cmd, reason)
    log_entry(index, cmd, f"{', '.join(sorted(days))}: {src['id']} → {dst['id']} "
              f"({moved} file(s))", reason, by="agent")
    return f"{', '.join(sorted(days))}: {src['id']} → {dst['id']}, {moved} file(s)"


def group_split(index, args, pack, by_number, cmd, reason):
    fo = group_target(index, args.folder)
    at = (args.at or "").strip()
    if not DATE.match(at):
        raise Refused(f"--at is YYYY-MM-DD, not {at!r} — nothing changed")
    owned = claims(index)
    later = {d for d in owned[fo["id"]] if d >= at}
    earlier = owned[fo["id"]] - later
    if not later or not earlier:
        raise Refused(f"{fo['id']} holds no day {'from' if not later else 'before'} "
                      f"{at} — a split leaves days on both sides. Nothing changed.")
    nid = next_folder_id(index)
    new = new_folder(nid, fo["kind"], where=[dict(r) for r in fo["where"]])
    new.update(parent=fo.get("parent"), split_from=fo["id"])
    index["folders"].insert(index["folders"].index(fo) + 1, new)
    owned[fo["id"]], owned[nid] = earlier, later
    moved = move_files(index, fo["id"], nid, later, cmd, reason)
    settle_structure(index, owned, [fo["id"], nid], by_number, cmd, reason)
    log_entry(index, cmd, f"{nid} split from {fo['id']} at {at} ({moved} file(s))",
              reason, by="agent")
    # B3 (owner ruling 20260918) — each side takes the places of its OWN days,
    # the way relabel reads them. The new folder used to inherit the whole
    # batch's words: UAT02-01 split a three-day batch and all three pieces
    # were named after the same two districts.
    decided, new_places, kept, _n = own_places(args.workdir, pack, index,
                                               {fo["id"], nid})
    places = []
    for side in (fo, new):
        refs = decided.get(side["id"], side["where"])
        for r in refs:
            index["places"].setdefault(r["ref"], new_places.get(r["ref"]) or {})
        if [r["ref"] for r in refs] != [r["ref"] for r in side["where"]]:
            log_entry(index, cmd, f"{side['id']}: "
                      f"{' + '.join(r['ref'] for r in side['where']) or '—'} → "
                      f"{' + '.join(r['ref'] for r in refs) or '—'}",
                      "a split piece is named from its own days", by="agent")
            side.update(where=refs)
        places.append(f"{side['id']} at {' + '.join(r['ref'] for r in refs) or '(no place)'}")
    return (f"{nid}: split from {fo['id']} at {at}, {moved} file(s); "
            + "; ".join(places)
            + "".join(f"\n  {fid} kept its place: {k} day(s) neither the pack nor "
                      "the geocode cache answers offline" for fid, k in kept))


def group_merge(index, args, pack, by_number, cmd, reason):
    src, dst = group_target(index, args.source), group_target(index, args.into)
    if src is dst:
        raise Refused("a folder cannot merge into itself — nothing changed")
    if src.get("parent") != dst.get("parent"):
        raise Refused(f"{src['id']} and {dst['id']} are not at one level (both "
                      "top-level day folders, or legs of one parent) — nothing changed")
    owned = claims(index)
    owned[dst["id"]] |= owned[src["id"]]
    owned[src["id"]] = set()
    moved = move_files(index, src["id"], dst["id"], None, cmd, reason)
    src["merged_into"] = dst["id"]
    settle_structure(index, owned, [src["id"], dst["id"]], by_number, cmd, reason)
    log_entry(index, cmd, f"{src['id']} merged into {dst['id']} ({moved} file(s))",
              reason, by="agent")
    return f"{src['id']} → {dst['id']}, {moved} file(s)"


def group_set_what(index, args, pack, by_number, cmd, reason):
    fo = group_target(index, args.folder, allow=HOLDERS + PARENTS)
    old = agent_what(fo)
    if args.clear:
        if args.text:
            raise Refused("--clear takes no text — nothing changed")
        fo["what"] = None
    else:
        fo["what"] = {"text": agent_text(args.text, "the [what]", "what"),
                      "source": AGENT}
    fo.update(rendered=None, validation=None)
    now = agent_what(fo)
    log_entry(index, cmd, f"{fo['id']}: [what] {old or '(the pick)'} → "
              f"{now or '(the pick)'}", reason, by="agent")
    return f"{fo['id']}: [what] {now!r}" if now else f"{fo['id']}: [what] back to the pick"


GROUP_ACTIONS = {"make-trip": group_make_trip, "make-fsl-month": group_make_fsl_month,
                 "move": group_move, "split": group_split, "merge": group_merge,
                 "set-what": group_set_what}


def cmd_group(args):
    workdir = Path(args.workdir).resolve()
    loaded = load(workdir, args.profile)
    if loaded is None:
        return 0
    pack, target, index = loaded
    cmd = f"{GROUP_CMD} {args.action}"
    reason = (args.reason or "").strip()
    if not reason:
        raise Refused("--reason is required: every change to the index says why")
    open_for_change(workdir, pack, index, cmd)
    by_number = {b["batch"]: b for b in json.loads(
        (workdir / "batches.json").read_text(encoding="utf-8")).get("batches", [])}
    said = GROUP_ACTIONS[args.action](index, args, pack, by_number, cmd, reason)
    if getattr(args, "dry_run", False):
        # F-s (Card 6): the same change, decided on the loaded index and not
        # saved — so the preview is the write's own answer.
        print(said)
        print("DRY RUN — nothing written. Run it again without --dry-run to "
              "record it, then `render --dry-run` shows the folder names.")
        return 0
    save(target, pack, index)
    print(said)
    print("next: `photo_index.py render`, then `check`")
    return 0

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    i = sub.add_parser("init", help="build the dump's index (phase pscan00)")
    i.add_argument("workdir")
    i.add_argument("--profile", help="owner pack (else PHOTO_PROFILE / "
                                     "collection.json)")
    i.add_argument("--dump-key", help="the name this dump's index is filed "
                                      "under in the pack (default: the work "
                                      "dir's folder name, at the first init)")
    i.set_defaults(fn=cmd_init)
    v = sub.add_parser("view", help="rewrite Index_pscan.md from index.json")
    v.add_argument("workdir")
    v.add_argument("--profile")
    v.set_defaults(fn=cmd_view)
    r = sub.add_parser("render", help="settle every route with the plan code "
                                      "and render every folder's name")
    r.add_argument("workdir")
    r.add_argument("--profile")
    r.add_argument("--dry-run", action="store_true",
                   help="print which folder names would change and write "
                        "nothing — allowed while the index is frozen")
    r.add_argument("--no-vision", action="store_true",
                   help="render batches the see stage has not run for, from "
                        "metadata alone — [who] and [what] are given up for "
                        "them (R1)")
    r.set_defaults(fn=cmd_render)
    d = sub.add_parser("dest", help="a day folder merges into or fills an "
                                    "existing folder (D6), or is new again")
    d.add_argument("workdir")
    d.add_argument("folder", help="the folder id, e.g. F003")
    d.add_argument("mode", choices=["merge", "fill_shell", "new"])
    d.add_argument("path", nargs="?", help="the existing folder (merge, fill_shell)")
    d.add_argument("--ref", action="append",
                   help="the work dir holding that folder's manifest.csv — the "
                        "dedupe reference; required for merge (repeatable)")
    d.add_argument("--reason", required=True)
    d.add_argument("--profile")
    d.set_defaults(fn=cmd_dest)
    c = sub.add_parser("check", help="the final check (P4): exit 0 passes, 1 fails")
    c.add_argument("workdir")
    c.add_argument("--profile")
    c.set_defaults(fn=cmd_check)
    z = sub.add_parser("freeze", help="lock the names (D-I16): export plans.json "
                                      "and the plan files, record the hash, the "
                                      "pack id and each copied file's SHA-256")
    z.add_argument("workdir")
    z.add_argument("--profile")
    z.add_argument("--replace-plans", action="store_true",
                   help="move a hand-written plans.json and its plan files "
                        "aside (stamped) instead of refusing")
    z.add_argument("--reason",
                   help="why, recorded in the index log (default: the check "
                        "passed and the names are locked)")
    z.set_defaults(fn=cmd_freeze)
    y = sub.add_parser("verify", help=f"exit 0 while the freeze holds, "
                                      f"{EXIT_STALE} when it does not (photo_run "
                                      "calls it before copying)")
    y.add_argument("workdir")
    y.add_argument("--profile")
    y.add_argument("--copied", action="store_true",
                   help="after the copy: compare photo_execute's SHA-256 with "
                        "the frozen ones (exit 1 on any difference). When "
                        "only the owner pack changed since the freeze, the "
                        f"check still runs and exits {EXIT_PACK_MOVED} if it "
                        "passes: the drive is fine, names may differ on a "
                        "re-lock")
    y.set_defaults(fn=cmd_verify)
    u = sub.add_parser("unfreeze", help="lift a freeze that still holds")
    u.add_argument("workdir")
    u.add_argument("--profile")
    u.add_argument("--reason", required=True)
    u.set_defaults(fn=cmd_unfreeze)
    k = sub.add_parser("recut", help="cut the batches again with the owner's "
                                     "answers, before any vision pass (D-I1)")
    k.add_argument("workdir")
    k.add_argument("--profile")
    k.add_argument("--reason")
    k.add_argument("--no-geocode", action="store_true",
                   help="pass --no-geocode to photo_cluster (cached names only)")
    k.add_argument("--dry-run", action="store_true",
                   help="cut, report what would move, then put every file back "
                        "and write nothing")
    k.set_defaults(fn=cmd_recut)
    L = sub.add_parser("relabel", help="put the pack's current place labels on "
                                       "the folders (no batch changes; dry run "
                                       "unless --go)")
    L.add_argument("workdir")
    L.add_argument("--profile")
    L.add_argument("--go", action="store_true")
    L.add_argument("--reason")
    L.set_defaults(fn=cmd_relabel)
    a = sub.add_parser("apply-page", help="record a confirmed batch page (G6): "
                                          "its rows, a named place's refs, a "
                                          "PROPOSED monthly parent (dry run "
                                          "unless --go)")
    a.add_argument("workdir")
    a.add_argument("page", help="the page's name, e.g. P-B03")
    a.add_argument("--profile")
    a.add_argument("--go", action="store_true")
    a.add_argument("--reason")
    a.set_defaults(fn=cmd_apply_page)
    t = sub.add_parser("identify", help="G7: recognition proposes a pet's name on "
                                         "viewed photos; the agent views each and "
                                         f"agrees (exit {EXIT_VIEWS_WANTED} = views "
                                         "wanted; --answers --go records them)")
    t.add_argument("workdir")
    t.add_argument("--profile")
    t.add_argument("--answers", help="the identify-views.md with a verdict on "
                                     "each row")
    t.add_argument("--go", action="store_true")
    t.add_argument("--reason")
    t.add_argument("--preview", action="store_true",
                   help="say whether views would be written, and write nothing "
                        "(M1 — what a `finish` dry run reports)")
    t.add_argument("--new-only", action="store_true",
                   help="G7g (the conductor's): propose only rows no views file "
                        "showed yet; say how many were left blank")
    t.set_defaults(fn=cmd_identify)
    g = sub.add_parser("group", help="change the folder structure: a trip with "
                                     "legs, a monthly parent for a named "
                                     "frequent place, a move, split or merge by "
                                     "date, the agent's own [what] (D-I8)")
    gs = g.add_subparsers(dest="action", required=True)

    def action(name, text):
        p = gs.add_parser(name, help=text)
        p.add_argument("workdir")
        p.add_argument("--profile")
        p.add_argument("--reason", required=True)
        p.add_argument("--dry-run", action="store_true",
                       help="say what this would change and write nothing")
        p.set_defaults(fn=cmd_group)
        return p

    p = action("make-trip", "day folders become the legs of one trip")
    p.add_argument("folders", nargs="+", help="the day folders, e.g. F008 F009")
    p.add_argument("--where", required=True, help="the trip's place word (R5)")
    p.add_argument("--what")
    p = action("make-fsl-month", "one month's visits to a named frequent place "
                                 "become the legs of a monthly parent (D-I12)")
    p.add_argument("place", help="the place's id, e.g. fsl-0003")
    p.add_argument("month", help="YYYY-MM")
    p.add_argument("--what")
    p = action("move", "whole days move from one folder to another")
    p.add_argument("source")
    p.add_argument("--to", required=True)
    p.add_argument("--dates", required=True, help="YYYY-MM-DD[,YYYY-MM-DD...]")
    p = action("split", "the days from --at on become a new folder")
    p.add_argument("folder")
    p.add_argument("--at", required=True, help="YYYY-MM-DD")
    p = action("merge", "a folder's days join another folder's; it is retired")
    p.add_argument("source")
    p.add_argument("--into", required=True)
    p = action("set-what", "the agent's own [what] for a folder, or --clear")
    p.add_argument("folder")
    p.add_argument("text", nargs="?")
    p.add_argument("--clear", action="store_true")
    args = ap.parse_args(argv)
    args.workdir = dump_workdir(args.workdir, getattr(args, "profile", None))
    return args.fn(args)


def run_line(script, crops=False):
    """H-I (HIL01 obs-15) — `<python> <script>` with the script's full path,
    for a printed next step: an agent pasting a bare `photo_index.py ...`
    composed the rest itself and lost the work dir from inside it. A stage
    that makes crops gets the pages' python, or the pasted line is HIL-10
    again by hand."""
    import photo_platform
    import photo_run
    return photo_platform.run_line(
        photo_run.page_python() if crops else photo_run.PY, HERE / script)


def dump_workdir(arg, profile):
    """U5-10: a bare dump name (`202401`) resolves the way `photo_run.py`
    resolves it, through the SAME function, so an agent never composes a work
    dir path by hand. Anything with a separator is a path and is left as
    typed."""
    if len(Path(arg).parts) != 1:
        return arg
    import photo_run
    return str(photo_run.resolve_workdir(
        arg, argparse.Namespace(workdir_root=None, profile=profile)))


if __name__ == "__main__":
    sys.exit(main())
