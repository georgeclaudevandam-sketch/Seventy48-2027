#!/usr/bin/env python3
"""Replace the planned course line in data/route.json with the average of the finishers' tracks (YB, 2024 to 2026).

The race rules disqualify a team that enters the Vessel Traffic Lanes, and Colvos Passage is the way everyone goes, so the
line the finishers actually paddled is a better course than the shortest water path. Each finished track's moving pings are projected onto
the current line and binned every 0.2 nm along it; the course is the median position of the tracks in each bin, smoothed over
about a mile, from the start to the finish of the current line. Every finisher passed the Owen Beach checkpoint and went
through the Port Townsend Canal, so the median does too. Run again and it refines against its own last result.

Usage: build_average_route.py [--key colvos] [--iterations 3]
"""
import json, math, sys
from pathlib import Path

import numpy as np
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent.parent
KEY = sys.argv[sys.argv.index("--key") + 1] if "--key" in sys.argv else "colvos"
ITER = int(sys.argv[sys.argv.index("--iterations") + 1]) if "--iterations" in sys.argv else 3
BIN, SMOOTH_NM, MIN_TRACKS = 0.2, 0.5, 30
K = math.cos(math.radians(47.7))


def nm(a, b):
    return math.hypot((b[0] - a[0]) * 60, (b[1] - a[1]) * 60 * K)


def chain(pts):
    cum = [0.0]
    for p, q in zip(pts, pts[1:]):
        cum.append(cum[-1] + nm(p, q))
    return cum


def project_all(ref, cum, P):
    """Distance off and distance along the line ref for every row of P (lat, lon), vectorised."""
    A, B = np.array(ref[:-1]), np.array(ref[1:])
    ax, ay, bx, by = A[:, 1] * K, A[:, 0], B[:, 1] * K, B[:, 0]
    px, py = P[:, 1:2] * K, P[:, 0:1]
    dx, dy = bx - ax, by - ay
    f = np.clip(((px - ax) * dx + (py - ay) * dy) / np.maximum(dx * dx + dy * dy, 1e-12), 0, 1)
    d = np.hypot(px - (ax + f * dx), py - (ay + f * dy)) * 60
    j = d.argmin(axis=1); r = np.arange(len(P))
    c = np.array(cum)
    return d[r, j], c[j] + (c[j + 1] - c[j]) * f[r, j]


def untangle(pts):
    """Cut out loops: where the line crosses itself, drop everything between the two crossing segments."""
    def cross(a, b, c, d):
        o = lambda p, q, r: (q[1] - p[1]) * (r[0] - p[0]) - (q[0] - p[0]) * (r[1] - p[1])
        return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0
    i = 0
    while i < len(pts) - 1:
        for j in range(len(pts) - 2, i + 1, -1):
            if cross(pts[i], pts[i + 1], pts[j], pts[j + 1]):
                pts = pts[:i + 1] + pts[j + 1:]; break
        i += 1
    return pts


def land_polygons():
    """GSHHG full-resolution land near the course (as build_route.py), or None if the coastline package is missing."""
    try:
        import mpl_toolkits.basemap_data as bd
        from shapely.geometry import Polygon, box
        from shapely.ops import unary_union
        clip = box(-123.05, 47.2, -122.25, 48.25)
    except ImportError:
        return None
    d = Path(list(bd.__path__)[0]); fh = open(d / "gshhs_f.dat", "rb"); polys = []
    for line in open(d / "gshhsmeta_f.dat"):
        q = line.split(); lev, s, n, off, nb = int(q[0]), float(q[3]), float(q[4]), int(q[5]), int(q[6])
        if n < 47.2 or s > 48.2 or lev != 1:
            continue
        fh.seek(off); a = np.frombuffer(fh.read(nb), dtype="<f4").reshape(-1, 2)
        if a[:, 0].max() < -123.05 or a[:, 0].min() > -122.25:
            continue
        polys.append(Polygon(a).buffer(0).intersection(clip))   # the continent is one huge polygon: keep only the Sound
    return unary_union(polys)


def main():
    route = json.loads((ROOT / "data/route.json").read_text())
    leg = next(l for l in route["legs"] if l["key"] == KEY)
    marks = {m["key"]: m for m in route["marks"]}
    rows = []   # (track id, lat, lon) of every ping where the boat was moving (over 1.5 kn from the ping before)
    n, own = 0, []
    for f in sorted((ROOT / "data/tracks").glob("seventy48_*.json")):
        for t in json.loads(f.read_text())["teams"]:
            tr = t.get("track") or []
            if t.get("status", "").lower() != "finished" or len(tr) < 50:
                continue
            mv = [(q[1], q[2]) for p, q in zip(tr, tr[1:]) if q[0] > p[0] and nm(p[1:], q[1:]) / ((q[0] - p[0]) / 3600) > 1.5]
            rows += [(n, a, b) for a, b in mv]; own.append(mv)
            n += 1
    R = np.array(rows); P = R[:, 1:]
    print(f"{n} finished tracks, {len(R)} moving pings", file=sys.stderr)
    # first guess, independent of any earlier line: each track resampled at 400 equal steps of its own length, and the median
    # of the tracks at each step. Then refine against that guess, which takes out the drift between tracks of different length.
    G = []
    for mv in own:
        c = chain(mv); c = np.array(c) / (c[-1] or 1); a = np.array(mv)
        x = np.linspace(0, 1, 400); G.append(np.c_[np.interp(x, c, a[:, 0]), np.interp(x, c, a[:, 1])])
    g = np.median(np.array(G), axis=0)
    first = [tuple(leg["points"][0])] + [tuple(p) for p in g[2:-2]] + [tuple(leg["points"][-1])]
    ref = untangle(first)
    for it in range(ITER):
        cum = chain(ref); nb = int(cum[-1] / BIN) + 1
        off, along = project_all(ref, cum, P)
        keep = off <= 2.5   # off course (a bay, a diversion): leave it out
        b = np.minimum(nb - 1, (along / BIN).astype(int))
        # each track's mean position in each bin, then the median over the tracks in the bin
        grp, inv = np.unique(b[keep] * 10000 + R[keep, 0].astype(int), return_inverse=True)
        cnt = np.bincount(inv)
        mlat, mlon = np.bincount(inv, P[keep, 0]) / cnt, np.bincount(inv, P[keep, 1]) / cnt
        gb = grp // 10000
        med = []
        for i in range(nb):
            m = gb == i
            med.append((float(np.median(mlat[m])), float(np.median(mlon[m]))) if m.sum() >= MIN_TRACKS else None)
        # fill gaps (few tracks in a bin) from the reference line, then smooth along the course
        for i, m in enumerate(med):
            if m is None:
                a = (i + 0.5) * BIN; j = max(1, next((k for k in range(1, len(cum)) if cum[k] >= a), len(cum) - 1))
                f = (a - cum[j - 1]) / ((cum[j] - cum[j - 1]) or 1); p, q = ref[j - 1], ref[j]
                med[i] = (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f)
        w = int(SMOOTH_NM / BIN)
        sm = [tuple(np.mean(med[max(0, i - w):i + w + 1], axis=0)) for i in range(len(med))]
        ref = untangle([ref[0]] + sm + [ref[-1]])
        print(f"iteration {it + 1}: {chain(ref)[-1]:.2f} nm, {sum(1 for x in med if x is not None)} bins", file=sys.stderr)
    # take out hairpins (a bin or two where the median doubles back): any point where the line turns more than 100 degrees
    def turn(a, b, c):
        h1 = math.atan2((b[1] - a[1]) * K, b[0] - a[0]); h2 = math.atan2((c[1] - b[1]) * K, c[0] - b[0])
        return abs((math.degrees(h2 - h1) + 180) % 360 - 180)
    changed = True
    while changed:
        changed = False
        for i in range(1, len(ref) - 1):
            if turn(ref[i - 1], ref[i], ref[i + 1]) > 100:
                del ref[i]; changed = True; break
    # stay out of the Vessel Traffic Lanes (entering one disqualifies the team): a point inside the traffic separation scheme
    # (data/lanes.json, scripts/fetch_lanes.py) goes to the nearest point 0.1 nm outside it
    lanes = ROOT / "data/lanes.json"
    if lanes.exists() and json.loads(lanes.read_text()).get("scheme"):
        from shapely.geometry import Point, Polygon
        from shapely.ops import nearest_points
        sch = Polygon([(q[1], q[0]) for q in json.loads(lanes.read_text())["scheme"]]).buffer(0)
        edge = sch.buffer(0.1 / 60 / K).exterior; out = 0
        for _ in range(3):   # again, in case a segment between two fixed points still clips the scheme
            for i, p in enumerate(ref):
                if sch.contains(Point(p[1], p[0])):
                    q = nearest_points(edge, Point(p[1], p[0]))[0]; ref[i] = (q.y, q.x); out += 1
            for i in range(len(ref) - 1, 0, -1):   # densify a segment that cuts across the scheme
                a_, b_ = ref[i - 1], ref[i]
                if sch.intersects(LineString([(a_[1], a_[0]), (b_[1], b_[0])])):
                    ref.insert(i, ((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2))
        print(f"moved {out} points out of the traffic lanes", file=sys.stderr)
    # keep the line off the beach: a point the smoothing put on land (rounding Blake Island, Point No Point) goes to the
    # nearest water 50 m out. The Thea Foss Waterway and the Port Townsend Canal are narrower than the coastline knows.
    land = land_polygons()
    if land is not None:
        from shapely.geometry import Point
        from shapely.ops import nearest_points
        from shapely.prepared import prep
        coast = land.buffer(0.0008).boundary; wet = prep(land.buffer(0.0004)); moved = 0
        canal = marks.get("canal")
        skip = lambda p, a: a < 1.4 or (canal and nm(p, (canal["lat"], canal["lon"])) < 0.6)
        for _ in range(12):   # move points off, then split any segment that still cuts a corner of land, and again
            cum = chain(ref)
            for i, p in enumerate(ref):
                if not skip(p, cum[i]) and wet.contains(Point(p[1], p[0])):
                    q = nearest_points(coast, Point(p[1], p[0]))[0]; ref[i] = (q.y, q.x); moved += 1
            cum = chain(ref)
            for i in range(len(ref) - 1, 0, -1):
                a_, b_ = ref[i - 1], ref[i]
                if not skip(a_, cum[i - 1]) and wet.intersects(LineString([(a_[1], a_[0]), (b_[1], b_[0])])):
                    ref.insert(i, ((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2))
        print(f"moved {moved} points off the land", file=sys.stderr)
    leg["points"] = [[round(p[0], 5), round(p[1], 5)] for p in ref]
    leg["nm"] = round(chain(ref)[-1], 2)
    leg["source"] = f"median of {n} finished YB tracks 2024-2026 (scripts/build_average_route.py)"
    (ROOT / "data/route.json").write_text(json.dumps(route, separators=(",", ":")))
    print(f"wrote {KEY}: {len(ref)} points, {leg['nm']} nm", file=sys.stderr)


if __name__ == "__main__":
    main()
