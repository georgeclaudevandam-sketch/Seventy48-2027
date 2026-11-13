#!/usr/bin/env python3
"""Fetch past Seventy48 tracks from YB Tracking.

For every candidate YB race key that exists, reads RaceSetup (teams, classes,
finish times) and AllPositions3 (packed binary positions), thins each team's
track and writes data/tracks/<key>.json plus an index at data/tracks/index.json.
Every Seventy48 boat is human powered, so all teams are kept. Pass race keys on
the command line to try others.
"""
from __future__ import annotations

import json
import math
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "tracks"
YB = "https://yb.tl"
UA = {"User-Agent": "seventy48-2027 planner (github.com/georgeclaudevandam-sketch/Seventy48-2027)"}
YEARS = [2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url: str, tries: int = 4, timeout: int = 30):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410, 500):
                return None
            if e.code in (429, 503):
                time.sleep(20 * (i + 1))
            log(f"  HTTP {e.code} retry {i + 1}: {url}")
        except Exception as e:
            log(f"  {type(e).__name__} {e} retry {i + 1}: {url}")
        time.sleep(2 * (i + 1))
    return None


def decode_positions(buf: bytes) -> dict[int, list[tuple[int, float, float]]]:
    """Decode YB AllPositions3: big-endian, newest fix first, later fixes as deltas."""
    flags = buf[0]
    has_alt, has_dtf, has_laps, has_pc = flags & 1, flags & 2, flags & 4, flags & 8
    ref = struct.unpack_from(">I", buf, 1)[0]
    off, teams = 5, {}
    while off + 4 <= len(buf):
        tid, n = struct.unpack_from(">HH", buf, off)
        off += 4
        pts, prev = [], None
        for _ in range(n):
            if buf[off] & 0x80:
                w, dlat, dlon = struct.unpack_from(">Hhh", buf, off)
                off += 6
                if has_alt:
                    off += 2
                if has_dtf:
                    off += 2
                    if has_laps:
                        off += 1
                if has_pc:
                    off += 2
                at, lat, lon = prev[0] - (w & 0x7FFF), prev[1] + dlat, prev[2] + dlon
            else:
                t, lat, lon = struct.unpack_from(">Iii", buf, off)
                off += 12
                if has_alt:
                    off += 2
                if has_dtf:
                    off += 4
                    if has_laps:
                        off += 1
                if has_pc:
                    off += 4
                at = ref + t
            prev = (at, lat, lon)
            pts.append(prev)
        teams[tid] = sorted((a, la / 1e5, lo / 1e5) for a, la, lo in pts)
    return teams


def thin(pts, min_gap_s=300, min_nm=0.1):
    """Keep a fix when min_gap_s seconds or min_nm nm have passed since the last kept one."""
    out = []
    for p in pts:
        if not (40 < p[1] < 60 and -140 < p[2] < -115):
            continue
        if out:
            q = out[-1]
            d = math.hypot((p[1] - q[1]) * 60, (p[2] - q[2]) * 60 * math.cos(math.radians(p[1])))
            if p[0] - q[0] < min_gap_s and d < min_nm:
                continue
        out.append(p)
    if pts and out and out[-1] != pts[-1] and 40 < pts[-1][1] < 60:
        out.append(pts[-1])
    return [[int(a), round(la, 4), round(lo, 4)] for a, la, lo in out]


def race(key: str):
    log(f"{key}: RaceSetup")
    raw = get(f"{YB}/JSON/{key}/RaceSetup")
    if not raw:
        return None
    try:
        setup = json.JSONDecoder(strict=False).raw_decode(raw.decode("utf-8", "replace").strip())[0]
    except ValueError as e:
        log(f"  not JSON ({len(raw)} bytes): {raw[:200]!r}")
        return None
    if not isinstance(setup, dict) or not setup.get("teams"):
        log(f"  no teams; keys {list(setup)[:20] if isinstance(setup, dict) else type(setup).__name__}")
        return None
    tags = {t["id"]: t["name"] for t in setup.get("tags", [])}
    log(f"{key}: '{setup.get('title')}' {len(setup['teams'])} teams, tags {sorted(tags.values())}")
    buf = get(f"{YB}/BIN/{key}/AllPositions3", tries=3, timeout=120)
    if not buf:
        log("  no AllPositions3")
        return None
    pos = decode_positions(buf)
    out = []
    for t in setup["teams"]:
        pts = thin([p for p in pos.get(t["id"], []) if 47.1 < p[1] < 48.3 and -123.1 < p[2] < -122.2])
        tg = [tags[i] for i in t.get("tags") or [] if i in tags and tags[i].lower() != "all teams"]
        start = t.get("start") or setup.get("start")
        fin = t.get("finishedAt")
        status = str(t.get("explain") or t.get("status") or "")
        if "DNF" in status.upper() or "RETIRED" in status.upper():
            fin = None
        elif fin:
            status = "Finished"
        out.append({
            "id": t["id"], "name": t.get("name"), "boat": t.get("model"), "captain": t.get("captain"),
            "class": ", ".join(tg), "status": status,
            "start": start, "finished": fin, "elapsed_h": round((fin - start) / 3600, 2) if fin and start else None,
            "track": pts,
        })
        log(f"  {t.get('name')!r:40} {len(pts):5} pts  {', '.join(tg)[:30]:30} {'%.2f h' % ((fin - start) / 3600) if fin and start else status}")
    return {"key": key, "title": setup.get("title"), "start": setup.get("start"), "stop": setup.get("stop"), "teams": out}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    keys = sys.argv[1:] or [k for y in reversed(YEARS) for k in (f"seventy48{y}", f"seventy48-{y}", f"seventy48_{y}", f"s48{y}", f"seventy{y}")]
    index = []
    for key in dict.fromkeys(keys):
        try:
            r = race(key)
        except Exception as e:  # keep going with other years
            log(f"{key}: FAILED {type(e).__name__}: {e}")
            continue
        if not r or not r["teams"]:
            continue
        (OUT / f"{key}.json").write_text(json.dumps(r, separators=(",", ":")))
        index.append({"key": key, "title": r["title"], "start": r["start"], "teams": len(r["teams"]),
                      "finished": sum(1 for t in r["teams"] if t["finished"])})
        (OUT / "index.json").write_text(json.dumps({"source": "YB Tracking (yb.tl)", "races": index}, indent=1))
    (OUT / "index.json").write_text(json.dumps({"source": "YB Tracking (yb.tl)", "races": index}, indent=1))
    log(f"wrote {len(index)} races")


if __name__ == "__main__":
    main()
