#!/usr/bin/env python3
"""Build data/route.json: shortest-water course lines for Seventy48, Tacoma to Port Townsend.

One-off helper, kept for reproducibility. Needs numpy, scipy, scikit-image, pillow, shapely and
basemap-data-hires (pip), which ships the GSHHG full-resolution coastline.

The coastline is rasterised on a ~55 m grid. The Thea Foss Waterway and the Port Townsend Canal are
narrower than that, so a corridor is carved along each. Each option is the cheapest water path through
its via points, where water close to shore costs a little more (keeps the line off the beach), then
simplified as long as the simplified line stays on water.
"""
import json, math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_erosion, distance_transform_edt
from shapely.geometry import LineString, Polygon, box
from skimage.graph import route_through_array
import mpl_toolkits.basemap_data as bd

OUT = Path(__file__).resolve().parent.parent / "data" / "route.json"
X0, X1, Y0, Y1 = -123.05, -122.25, 47.20, 48.20
DY = 0.0005; DX = DY / math.cos(math.radians(47.7))
W, H = int((X1 - X0) / DX), int((Y1 - Y0) / DY)


def gshhs_polys():
    """GSHHG full-resolution land (level 1) and lake (level 2) polygons touching the bbox."""
    d = Path(list(bd.__path__)[0])
    f = open(d / "gshhs_f.dat", "rb")
    for line in open(d / "gshhsmeta_f.dat"):
        p = line.split()
        lev, s, n, off, nb = int(p[0]), float(p[3]), float(p[4]), int(p[5]), int(p[6])
        if n < Y0 or s > Y1 or lev > 2:
            continue
        f.seek(off)
        a = np.frombuffer(f.read(nb), dtype="<f4").reshape(-1, 2)   # lon, lat
        if a[:, 0].max() < X0 or a[:, 0].min() > X1:
            continue
        yield lev, a


def px(x, y): return ((x - X0) / DX, (Y1 - y) / DY)


img = Image.new("L", (W, H), 0); draw = ImageDraw.Draw(img)
for lev, a in gshhs_polys():
    if len(a) > 100000:   # the continent: clip to the bbox first
        g = Polygon(a).buffer(0).intersection(box(X0 - .05, Y0 - .05, X1 + .05, Y1 + .05))
        for q in (g.geoms if hasattr(g, "geoms") else [g]):
            if q.geom_type != "Polygon" or q.is_empty: continue
            draw.polygon([px(*c) for c in q.exterior.coords], fill=255)
            for i in q.interiors: draw.polygon([px(*c) for c in i.coords], fill=0)
    else:
        draw.polygon([px(x, y) for x, y in a], fill=255 if lev == 1 else 0)
land = np.array(img) > 0


def rc(lat, lon): return (int(round((Y1 - lat) / DY)), int(round((lon - X0) / DX)))
def ll(r, c): return (round(Y1 - r * DY, 5), round(X0 + c * DX, 5))


def carve(a, b, w=1):
    for t in np.linspace(0, 1, 3000):
        r, c = rc(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        land[r - w:r + w + 1, c - w:c + w + 1] = False


carve((47.2585, -122.4365), (47.268, -122.4335))                                                  # Thea Foss Waterway
carve((48.0200, -122.7200), (48.0297, -122.7335)); carve((48.0297, -122.7335), (48.0400, -122.7450))  # Port Townsend Canal
core = binary_erosion(land, iterations=1)   # simplified lines may clip a single shore cell
dist = distance_transform_edt(~land) * DY * 60
cost = np.where(land, 1e6, 1 + 3 * np.exp(-dist / 0.15))


def snap(p):
    r, c = rc(*p)
    if not land[r, c]: return p
    ys, xs = np.nonzero(~land[r - 40:r + 41, c - 40:c + 41]); k = np.argmin((ys - 40) ** 2 + (xs - 40) ** 2)
    return ll(r - 40 + ys[k], c - 40 + xs[k])


def on_water(coords):
    for (y0, x0), (y1, x1) in zip(coords, coords[1:]):
        n = int(max(abs(x1 - x0) / DX, abs(y1 - y0) / DY)) + 2
        for t in np.linspace(0, 1, n):
            if core[rc(y0 + (y1 - y0) * t, x0 + (x1 - x0) * t)]: return False
    return True


def route(vias):
    vias = [snap(v) for v in vias]
    pts = []
    for a, b in zip(vias, vias[1:]):
        p, _ = route_through_array(cost, rc(*a), rc(*b), fully_connected=True, geometric=True)
        seg = [ll(*q) for q in p]; pts += seg if not pts else seg[1:]
    ls = LineString([(lo, la) for la, lo in pts])
    for tol in (0.002, 0.001, 0.0005, 0.00025, 0):
        s = [(round(y, 5), round(x, 5)) for x, y in ls.simplify(tol, preserve_topology=False).coords]
        if on_water(s): return s


def nm(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0]); dl = math.radians(b[1] - a[1])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(h))


START, OWEN, FINISH = (47.2585, -122.4365), (47.3150, -122.5320), (48.1165, -122.7520)
NORTH = [(47.6, -122.47), (47.915, -122.53), (47.945, -122.61), (47.99, -122.70), (48.0297, -122.7335), FINISH]
LEGS = [
    ("colvos", "West of Vashon (Colvos Passage)", [START, OWEN, (47.40, -122.535), (47.505, -122.495)] + NORTH),
    ("east", "East of Vashon (East Passage)", [START, OWEN, (47.335, -122.47), (47.39, -122.37), (47.50, -122.42)] + NORTH),
]
MARKS = json.loads(OUT.read_text())["marks"] if OUT.exists() else []

legs = []
for key, name, vias in LEGS:
    pts = route(vias)
    print(key, len(pts), "points", round(sum(nm(a, b) for a, b in zip(pts, pts[1:])), 1), "nm")
    legs.append({"key": key, "name": name, "points": [list(p) for p in pts]})
OUT.write_text(json.dumps({
    "note": "Shortest-water course lines on a ~55 m grid from GSHHG full-resolution coastline (scripts/build_route.py). For distance and ETA only, not navigation.",
    "legs": legs, "marks": MARKS}, indent=1))
