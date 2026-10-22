"""Test-only: a stage started with this folder on PYTHONPATH cannot reach a
network. Every request is written, one JSON line (URL and POST body), to
$PHOTO_TEST_NET_LOG when set, so a case can COUNT what a stage tried to send.
By default each request is refused at once; with PHOTO_TEST_NET_ANSWER=stub
it gets a fixed, nameless-landmark answer instead (Overpass: no elements;
Nominatim: a town), so a case can read what the stage CACHED; with
PHOTO_TEST_NET_ANSWER=overpass502 Overpass answers HTTP 502 and Nominatim the
stub town (a map outage, U6-4). Sleeps are skipped. Never imported by the engine; a case adds this folder itself."""

import io
import json
import os
import time
import urllib.error
import urllib.request

STUB_NOMINATIM = {"name": "Stubtown", "category": "place", "type": "town",
                  "addresstype": "town", "place_rank": 16,
                  "namedetails": {"name": "Stubtown"},
                  "address": {"town": "Stubtown", "country": "Stubland"},
                  "display_name": "Stubtown, Stubland"}


def _answer(req, *a, **k):
    url = getattr(req, "full_url", req)
    data = getattr(req, "data", None)
    log = os.environ.get("PHOTO_TEST_NET_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"url": url,
                                "data": data.decode() if data else None}) + "\n")
    mode = os.environ.get("PHOTO_TEST_NET_ANSWER")
    if mode == "overpass502" and "overpass" in url:
        raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)
    if mode not in ("stub", "overpass502"):
        raise OSError("network refused by the test harness")
    body = {"elements": []} if "overpass" in url else STUB_NOMINATIM
    return _Resp(json.dumps(body).encode())


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


urllib.request.urlopen = _answer
time.sleep = lambda s: None
