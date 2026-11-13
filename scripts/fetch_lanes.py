#!/usr/bin/env python3
"""Vessel Traffic Lanes along the course, for data/lanes.json.

Seventy48 rules: "A team entering the Vessel Traffic Lanes will be automatically disqualified." The Puget Sound Traffic
Separation Scheme (33 CFR 167.1300 onward) runs from Admiralty Inlet to Tacoma. Its lanes, separation zones and precautionary
areas are mapped in OpenStreetMap as seamark:type=separation_lane / separation_zone / separation_boundary / precautionary_area
(OpenSeaMap, from the NOAA charts). This fetches them from Overpass, keeps each as a ring or line, joins the two outer
boundaries into one ring for the whole scheme, and reports any place the course line enters it (--check: only the report). Planning aid only: the chart is the authority.
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


def scheme(feats):
    """The whole Traffic Separation Scheme as one ring: the two outer separation boundaries (each an open line running the
    length of the Sound), joined end to end. Lanes and the zone between them all lie inside it."""
    b = sorted((f["pts"] for f in feats if f["type"] == "separation_boundary" and not f["closed"]), key=len, reverse=True)[:2]
    if len(b) < 2:
        return None
    w, e = [x if x[0][0] < x[-1][0] else x[::-1] for x in b]   # both south to north
    if sum(p[1] for p in w) / len(w) > sum(p[1] for p in e) / len(e):
        w, e = e, w
    return w + e[::-1] + [w[0]]


def check(d):
    """Report where each course line enters the scheme or a precautionary area."""
    route = json.loads((ROOT / "data/route.json").read_text())
    rings = ([d["scheme"]] if d.get("scheme") else []) + [f["pts"] for f in d["features"] if f["closed"]]
    for leg in route["legs"]:
        pts, hits, cum = leg["points"], [], 0.0
        for p, q in zip(pts, pts[1:]):
            seg = math.hypot((q[0] - p[0]) * 60, (q[1] - p[1]) * 60 * math.cos(math.radians(p[0])))
            for k in range(11):
                x = [p[0] + (q[0] - p[0]) * k / 10, p[1] + (q[1] - p[1]) * k / 10]
                if any(inside(x, r) for r in rings): hits.append((round(cum + seg * k / 10, 2), x))
            cum += seg
        log(f"{leg['key']}: {len(hits)} sampled points inside the traffic scheme" + (f", nm {hits[0][0]} to {hits[-1][0]}" if hits else ""))
    return hits


def main():
    if "--check" in sys.argv:
        check(json.loads((ROOT / "data/lanes.json").read_text())); return
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
    out = {"source": "OpenStreetMap seamarks (OpenSeaMap), via Overpass", "rule": "A team entering the Vessel Traffic Lanes will be automatically disqualified (Seventy48 race packet).",
           "scheme": scheme(feats), "features": feats}
    (ROOT / "data/lanes.json").write_text(json.dumps(out, separators=(",", ":")))
    check(out)


if __name__ == "__main__":
    main()
