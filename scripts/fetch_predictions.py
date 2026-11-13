#!/usr/bin/env python3
"""Fetch NOAA tide and current predictions for the Seventy48 2027 planner.

Finds every NOAA current prediction station within REACH_NM of either course line in
data/route.json (NOAA metadata API), keeps the shallowest bin of each, and fetches its max/slack
events for the race window, with the station's mean flood and ebb directions so the planner can
resolve the stream onto the course heading. Also fetches high/low tide predictions for a few tide
stations along the way.

Output: data/stations.json (the stations picked, with where they sit on each course line) and
data/predictions.json (the events).
"""
from __future__ import annotations

import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTE = ROOT / "data" / "route.json"
OUT_ST = ROOT / "data" / "stations.json"
OUT_PRED = ROOT / "data" / "predictions.json"

NOAA = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
MDAPI = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi"
UA = {"User-Agent": "seventy48-2027 planner (github.com/georgeclaudevandam-sketch/Seventy48-2027)"}

# Race: Friday 28 May 2027, 19:00 PDT, 48 h limit. Fetch a few days either side for what-ifs.
BEGIN, END = "20270524", "20270603"
REACH_NM = 1.2
TIDES = [("9446484", "Tacoma"), ("9447130", "Seattle"), ("9444900", "Port Townsend")]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get_json(url: str, params: dict | None = None, tries: int = 4):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            if e.code in (400, 404):
                raise RuntimeError(f"HTTP {e.code} for {url}: {body}") from None
            log(f"  HTTP {e.code}, retry {i + 1}: {url}")
        except Exception as e:
            log(f"  {type(e).__name__} {e}, retry {i + 1}: {url}")
        time.sleep(2 ** (i + 1))
    raise RuntimeError(f"giving up on {url}")


def nm(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0]); dl = math.radians(b[1] - a[1])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(h))


def project(pts, p):
    """(offset nm, along nm) of p projected onto polyline pts."""
    best, cum = (1e9, 0.0), 0.0
    k = math.cos(math.radians(p[0]))
    for a, b in zip(pts, pts[1:]):
        bx, by = (b[1] - a[1]) * k, b[0] - a[0]
        qx, qy = (p[1] - a[1]) * k, p[0] - a[0]
        f = max(0.0, min(1.0, (qx * bx + qy * by) / ((bx * bx + by * by) or 1)))
        q = (a[0] + by * f, a[1] + (b[1] - a[1]) * f)
        d, seg = nm(q, p), nm(a, b)
        if d < best[0]:
            best = (d, cum + seg * f)
        cum += seg
    return best


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    route = json.loads(ROUTE.read_text())
    legs = {l["key"]: l["points"] for l in route["legs"]}

    md = get_json(f"{MDAPI}/stations.json", {"type": "currentpredictions", "units": "english"})
    allst = md.get("stations") or []
    log(f"{len(allst)} current prediction station entries; sample keys: {sorted(allst[0].keys()) if allst else None}")
    near: dict[str, dict] = {}
    for s in allst:
        lat, lon = num(s.get("lat")), num(s.get("lng"))
        if lat is None or not (47.2 < lat < 48.2 and -123.0 < lon < -122.2):
            continue
        on = {}
        for k, pts in legs.items():
            d, along = project(pts, (lat, lon))
            if d <= REACH_NM:
                on[k] = {"along": round(along, 2), "offset": round(d, 2)}
        if not on:
            continue
        depth = num(s.get("depth"))
        cur = near.get(s["id"])
        if cur and (cur["depth"] if cur["depth"] is not None else 1e9) <= (depth if depth is not None else 1e9):
            continue
        near[s["id"]] = {"id": s["id"], "name": s.get("name", s["id"]).strip(), "lat": round(lat, 4), "lon": round(lon, 4),
                         "type": s.get("type"), "bin": s.get("currbin") or s.get("bin"), "depth": depth, "legs": on}
    log(f"{len(near)} stations within {REACH_NM} nm of the course")

    stations, preds = [], {}
    for s in sorted(near.values(), key=lambda s: min(v["along"] for v in s["legs"].values())):
        params = {"product": "currents_predictions", "station": s["id"], "begin_date": BEGIN, "end_date": END,
                  "units": "english", "time_zone": "gmt", "interval": "MAX_SLACK", "format": "json",
                  "application": "seventy48-2027-planner"}
        if s["bin"]:
            params["bin"] = s["bin"]
        try:
            r = get_json(NOAA, params)
        except Exception as e:
            log(f"  {s['id']} {s['name']}: {e}")
            continue
        cp = (r.get("current_predictions") or {}).get("cp") or []
        if not cp:
            log(f"  {s['id']} {s['name']}: no events ({str(r)[:200]})")
            continue
        fl = next((num(e.get("meanFloodDir")) for e in cp if num(e.get("meanFloodDir")) is not None), None)
        eb = next((num(e.get("meanEbbDir")) for e in cp if num(e.get("meanEbbDir")) is not None), None)
        ev = []
        for e in cp:
            typ = (e.get("Type") or "").lower()
            v = num(e.get("Velocity_Major"))
            if typ not in ("flood", "ebb", "slack") or v is None:
                continue
            ev.append({"t": e["Time"].replace(" ", "T") + "Z", "type": typ, "kn": round(abs(v), 2)})
        if not ev:
            log(f"  {s['id']} {s['name']}: events unreadable, first: {cp[0]}")
            continue
        s.update({"key": s["id"], "kind": "current", "flood_dir": fl, "ebb_dir": eb})
        stations.append(s)
        preds[s["id"]] = {"events": ev}
        log(f"  {s['id']:10} {s['name'][:40]:40} bin {s['bin']} {len(ev):3} events  flood {fl} ebb {eb}  {s['legs']}")

    for sid, name in TIDES:
        try:
            r = get_json(NOAA, {"product": "predictions", "station": sid, "begin_date": BEGIN, "end_date": END, "datum": "MLLW",
                                "units": "english", "time_zone": "gmt", "interval": "hilo", "format": "json",
                                "application": "seventy48-2027-planner"})
        except Exception as e:
            log(f"  tide {sid} {name}: {e}")
            continue
        p = r.get("predictions") or []
        if not p:
            continue
        md1 = get_json(f"{MDAPI}/stations/{sid}.json").get("stations", [{}])[0]
        s = {"key": sid, "id": sid, "name": name, "kind": "tide", "lat": round(num(md1.get("lat")) or 0, 4), "lon": round(num(md1.get("lng")) or 0, 4)}
        s["legs"] = {k: {"along": round(a, 2), "offset": round(d, 2)} for k, pts in legs.items() for d, a in [project(pts, (s["lat"], s["lon"]))]}
        stations.append(s)
        preds[sid] = {"events": [{"t": e["t"].replace(" ", "T") + "Z", "type": e["type"].upper(), "ft": round(float(e["v"]), 2)} for e in p]}
        log(f"  tide {sid} {name}: {len(p)} high/low")

    OUT_ST.write_text(json.dumps({"window": [BEGIN, END], "reach_nm": REACH_NM, "stations": stations}, indent=1))
    OUT_PRED.write_text(json.dumps({"source": "NOAA CO-OPS", "units": "knots, feet (MLLW)", "stations": preds}, separators=(",", ":")))
    log(f"wrote {len(stations)} stations")


if __name__ == "__main__":
    main()
