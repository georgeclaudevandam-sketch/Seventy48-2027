#!/usr/bin/env python3
"""Vessel Traffic Lanes along the course, for data/lanes.json.

Seventy48 rules: "A team entering the Vessel Traffic Lanes will be automatically disqualified." The Puget Sound Traffic
Separation Scheme (33 CFR 167.1300 onward) runs from Admiralty Inlet to Tacoma. Its lanes, separation zones and precautionary
areas are mapped in OpenStreetMap as seamark:type=separation_lane / separation_zone / separation_boundary / precautionary_area
(OpenSeaMap, from the NOAA charts). This fetches them from Overpass, keeps each as a ring or line, and reports any place the
planned course line enters a lane. Planning aid only: the chart is the authority.
"""
import json, math, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BBOX = (47.22, -122.85, 48.20, -122.25)
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
             "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
UA = {"User-Agent": "seventy48-2027 planner (github.com/georgeclaudevandam-sketch/Seventy48-2027)"}
TYPES = "separation_lane|separation_zone|separation_boundary|separation_line|separation_crossing|separation_roundabout|precautionary_area|inshore_traffic_zone"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def overpass():
    s, w, n, e = BBOX
    q = f'[out:json][timeout:120];(way["seamark:type"~"^({TYPES})$"]({s},{w},{n},{e});relation["seamark:type"~"^({TYPES})$"]({s},{w},{n},{e}););out geom;'
    for ep in ENDPOINTS:
        for i in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(ep, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA), timeout=180) as r:
                    return json.loads(r.read())
            except Exception as ex:
                log(f"  {ep}: {type(ex).__name__} {ex}"); time.sleep(10 * (i + 1))
    return None


def rings(el):
    if el["type"] == "way":
        return [[[round(p["lat"], 5), round(p["lon"], 5)] for p in el["geometry"]]]
    # a relation: join its outer ways into rings
    segs = [[[round(p["lat"], 5), round(p["lon"], 5)] for p in m["geometry"]] for m in el.get("members", []) if m.get("geometry") and m.get("role", "outer") in ("outer", "")]
    out = []
    while segs:
        r = segs.pop(0)
        changed = True
        while changed and r[0] != r[-1]:
            changed = False
            for i, sg in enumerate(segs):
                if sg[0] == r[-1]: r += sg[1:]
                elif sg[-1] == r[-1]: r += sg[::-1][1:]
                elif sg[-1] == r[0]: r = sg[:-1] + r
                elif sg[0] == r[0]: r = sg[::-1][:-1] + r
                else: continue
                segs.pop(i); changed = True; break
        out.append(r)
    return out


def inside(p, ring):
    x, y, c = p[1], p[0], False
    for (y1, x1), (y2, x2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def main():
    d = overpass()
    if not d:
        log("Overpass failed"); sys.exit(1)
    feats = []
    for el in d["elements"]:
        t = el.get("tags", {}).get("seamark:type")
        for r in rings(el):
            if len(r) > 1:
                feats.append({"type": t, "osm": f"{el['type']}/{el['id']}", "closed": r[0] == r[-1] and len(r) > 3, "pts": r})
    log(f"{len(feats)} features: " + ", ".join(f"{t} {sum(1 for f in feats if f['type'] == t)}" for t in sorted({f['type'] for f in feats})))
    (ROOT / "data/lanes.json").write_text(json.dumps({"source": "OpenStreetMap seamarks (OpenSeaMap), via Overpass", "rule": "A team entering the Vessel Traffic Lanes will be automatically disqualified (Seventy48 race packet).", "features": feats}, separators=(",", ":")))
    # where does the course line enter a lane?
    route = json.loads((ROOT / "data/route.json").read_text())
    lanes = [f for f in feats if f["type"] == "separation_lane" and f["closed"]]
    for leg in route["legs"]:
        pts, hits = leg["points"], []
        for p, q in zip(pts, pts[1:]):
            for k in range(11):
                x = [p[0] + (q[0] - p[0]) * k / 10, p[1] + (q[1] - p[1]) * k / 10]
                if any(inside(x, f["pts"]) for f in lanes): hits.append(x)
        log(f"{leg['key']}: {len(hits)} sampled points inside a traffic lane" + (f", first {hits[0]}, last {hits[-1]}" if hits else ""))


if __name__ == "__main__":
    main()
