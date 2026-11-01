"""NEBULA: build a second playfield for Space Cadet Pinball.

This script is the single source of truth for the second table. It defines the
layout in the engine's world coordinates, renders the matching playfield art
through the same perspective projection the engine uses, and emits a C++ header
with the wall polylines and the hardware offsets.

World coordinates, for reference:
  * +x is towards the *left* of the screen, -x towards the right
  * +y is down the screen, -y is up
  * x spans roughly [-8, 8], y spans [-14, 15]
  * the ball radius is 0.3

Usage:
  python tools/nebula_layout.py            # render art + emit header
  python tools/nebula_layout.py --preview  # also write a preview PNG
"""
import argparse
import math
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DAT = ROOT / "bin" / "CADET.DAT"
ART_OUT = ROOT / "bin" / "themes" / "nebula.bmp"
HDR_OUT = ROOT / "SpaceCadetPinball" / "tablelayout_nebula.inc"

# Playfield bitmap geometry at resolution 2 (the only one the game really uses).
ART_W, ART_H = 583, 751
TABLE_OFF_X, TABLE_OFF_Y = 220, 4     # where the .dat puts the playfield bitmap

# Camera for resolution 2, straight out of camera_info group 4.
CAM = dict(cx=292.0, cy=380.0, d=-640.00116, A=-0.91355, B=0.40674, F=3.7914, G=24.6754)

# Ball geometry.
BALL_R = 0.3


# --------------------------------------------------------------------------- #
# Projection
# --------------------------------------------------------------------------- #
def world_to_screen(x, y):
    """Forward projection of a point on the playfield plane (z = 0)."""
    c = CAM
    yc = c["A"] * y + c["F"]
    zc = -c["B"] * y + c["G"]
    return c["cx"] + c["d"] * x / zc, c["cy"] + c["d"] * yc / zc


def project_poly(points):
    return [world_to_screen(x, y) for x, y in points]


def scale_at(y):
    """Screen pixels per world unit along x at a given depth."""
    zc = -CAM["B"] * y + CAM["G"]
    return abs(CAM["d"] / zc)


# --------------------------------------------------------------------------- #
# Layout helpers
# --------------------------------------------------------------------------- #
def arc(cx, cy, r, a0, a1, steps=None):
    """Points of a circular arc, angles in degrees, y pointing down."""
    if steps is None:
        steps = max(3, int(abs(a1 - a0) / 8))
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / steps)))
            for i in range(steps + 1)]


def chain(*parts):
    out = []
    for part in parts:
        for p in part:
            if not out or math.dist(out[-1], p) > 1e-4:
                out.append(p)
    return out


# --------------------------------------------------------------------------- #
# The table design (world units)
# --------------------------------------------------------------------------- #
TOP = -10.15          # y of the top rail
LANE_OUT = -7.65      # outer wall of the shooter lane (screen right)
LANE_IN = -6.30       # inner wall of the shooter lane
LEFT_RAIL = 7.65      # side rail on the screen left
FLOOR = 13.15         # bottom of the bowl
# The collision surface of a wall sits one ball radius outside the drawn line,
# so the outer rails have to stay clear of the playfield box (x = +-8) or their
# lines end up outside the broad-phase grid.

# Outline of the playing surface: up the left rail, round the far corner,
# across the top, round the other far corner and straight down the outside of
# the shooter lane. This is both the fill mask of the artwork and the first
# half of the bowl wall.
OUTLINE = chain(
    [(LEFT_RAIL, FLOOR)],
    [(LEFT_RAIL, -8.2)],
    arc(5.62, -8.2, LEFT_RAIL - 5.62, 0, -90),
    [(-6.6, TOP)],
    # Chamfered corner. The shooter lane has to stay a straight, open channel:
    # a curved fillet here cuts across it and pins the ball in the lane.
    [(-7.10, -10.02)],
    [(-7.50, -9.72)],
    [(LANE_OUT, -9.30)],
    [(LANE_OUT, FLOOR)],
)

# Inner wall of the shooter lane plus the funnel that feeds the playfield.
# Kept as its own polyline: the bowl doubles back along it, so the two runs
# face opposite ways and each needs its own outward direction for the ball
# radius offset.
LANE_INNER = chain(
    [(LANE_IN, FLOOR)],
    [(LANE_IN, -7.35)],
    [(-5.30, -8.95)],
)

# Inlane guides: the side rails taper down towards the flippers.
INLANE_L = [(LEFT_RAIL, 9.35), (6.05, 11.30), (3.35, 12.40)]
INLANE_R = [(LANE_IN, 9.35), (-5.25, 11.45), (-2.60, 12.40)]

# Slingshot bodies: closed triangles sitting on the inlane guides.
SLING_L = [(7.05, 9.15), (4.30, 11.55), (7.05, 12.0)]
SLING_R = [(-6.10, 9.15), (-3.60, 11.55), (-6.10, 12.0)]

WALLS = [
    ("bowl", OUTLINE, 1),
    ("lane_inner", LANE_INNER, 1),
    ("inlane_l", INLANE_L, 4),
    ("inlane_r", INLANE_R, 4),
    ("sling_l", SLING_L + [SLING_L[0]], 3),
    ("sling_r", SLING_R + [SLING_R[0]], 3),
]

# --------------------------------------------------------------------------- #
# Hardware placement
# --------------------------------------------------------------------------- #
# Parts listed here are moved so their anchor lands on the given world point.
# Parts in KEEP stay exactly where the .dat puts them. Everything else with
# collision geometry is parked outside the playfield.
PARTS = {}
KEEP = {"a_flip1", "a_flip2", "plunger", "drain", "v_bloc1"}

BUMPER_ATTACK = [
    ("a_bump1", 0.0, -8.05),
    ("a_bump2", -2.05, -6.45),
    ("a_bump3", 2.05, -6.45),
    ("a_bump4", 0.0, -4.85),
]
BUMPER_LAUNCH = [
    ("a_bump5", -2.35, -1.95),
    ("a_bump6", 0.0, -1.65),
    ("a_bump7", 2.35, -1.95),
]
for name, x, y in BUMPER_ATTACK + BUMPER_LAUNCH:
    PARTS[name] = (x, y)

# Popup target banks: three groups of three.
for name, y in [("a_targ1", -2.35), ("a_targ2", -1.35), ("a_targ3", -0.35)]:
    PARTS[name] = (6.55, y)                    # left bank
for name, y in [("a_targ4", -2.35), ("a_targ5", -1.35), ("a_targ6", -0.35)]:
    PARTS[name] = (-5.65, y)                   # right bank
for name, x in [("a_targ7", -2.45), ("a_targ8", 0.0), ("a_targ9", 2.45)]:
    PARTS[name] = (x, -9.35)                   # top bank

# Solo targets: one long row under the bumper cluster, plus two side columns.
row_start = -4.8
for i, name in enumerate(["a_targ10", "a_targ11", "a_targ12", "a_targ19",
                          "a_targ20", "a_targ21", "a_targ22"]):
    PARTS[name] = (row_start + i * 1.6, -3.45)
for i, name in enumerate(["a_targ13", "a_targ14", "a_targ15"]):
    PARTS[name] = (6.75, 2.9 + i * 0.85)
for i, name in enumerate(["a_targ16", "a_targ17", "a_targ18"]):
    PARTS[name] = (-5.95, 2.9 + i * 0.85)

# Rollovers: the top entry lane and two mid-field rows.
for i, name in enumerate(["a_roll1", "a_roll2", "a_roll3"]):
    PARTS[name] = (-4.85 + i * 0.85, -8.85)
for i, name in enumerate(["a_roll4", "a_roll5", "a_roll6", "a_roll7", "a_roll8"]):
    PARTS[name] = (-2.30 + i * 1.15, 6.60)
for i, name in enumerate(["a_roll110", "a_roll111", "a_roll112"]):
    PARTS[name] = (-3.45 + i * 0.90, 4.55)
for i, name in enumerate(["a_roll179", "a_roll180", "a_roll181",
                          "a_roll182", "a_roll183", "a_roll184"]):
    PARTS[name] = (2.55 + i * 0.62, 1.5 - i * 0.55)
PARTS["a_roll9"] = (-4.55, -0.9)

# Scoops.
PARTS["a_kout2"] = (-4.95, -8.35)
PARTS["a_kout3"] = (4.95, -8.35)
PARTS["a_kout1"] = (0.0, 9.05)

# One-way gates and lane guides.
PARTS["s_onewy9"] = (-6.10, -8.30)
PARTS["s_onewy10"] = (-3.95, -8.30)
PARTS["v_gate1"] = (3.35, -9.70)
PARTS["v_gate2"] = (-2.65, -9.70)

# Rebounder posts flanking the bumper cluster.
PARTS["v_rebo1"] = (3.15, -4.35)
PARTS["v_rebo2"] = (-3.15, -4.35)


# --------------------------------------------------------------------------- #
# .DAT introspection
# --------------------------------------------------------------------------- #
FIXED_PAYLOAD = {0: 2, 2: 2}


def parse_dat(path):
    data = Path(path).read_bytes()
    group_count, = struct.unpack_from("<H", data, 175)
    off = 183
    groups, names = [], {}
    for gi in range(group_count):
        n = data[off]
        off += 1
        entries = []
        for _ in range(n):
            t = data[off]
            off += 1
            if t in FIXED_PAYLOAD:
                entries.append((t, data[off:off + 2]))
                off += 2
                continue
            size, = struct.unpack_from("<I", data, off)
            off += 4
            payload = data[off:off + size]
            entries.append((t, payload))
            if t == 3:
                names[gi] = payload.rstrip(b"\0").decode("latin-1")
            off += size
        groups.append(entries)
    return groups, names


def group_floats(entries):
    return [[float(v) for v in struct.unpack("<%df" % (len(p) // 4), p)]
            for t, p in entries if t == 11]


def group_bitmap(entries, res=2):
    for t, p in entries:
        if t == 1:
            r, w, h, x, y, sz, fl = struct.unpack_from("<BhhhhIb", p)
            if r == res:
                return dict(w=w, h=h, x=x, y=y, flags=fl)
    return None


def part_anchor(entries):
    """Anchor rule shared with the C++ builder."""
    floats = group_floats(entries)
    for arr in floats:
        if arr and abs(arr[0] - 600) < 1:
            if abs(arr[1] - 1) < 0.01:
                return (arr[2], arr[3])
            pts = arr[2:]
            pairs = [(pts[i], pts[i + 1]) for i in range(0, len(pts) - 1, 2)]
            if pairs:
                return (sum(p[0] for p in pairs) / len(pairs),
                        sum(p[1] for p in pairs) / len(pairs))
            return None
    for arr in floats:
        if arr and abs(arr[0] - 800) < 1:
            return (arr[1], arr[2])
        if arr and abs(arr[0] - 601) < 1:
            return (arr[1], arr[2])
    return None


def collect_parts():
    groups, names = parse_dat(DAT)
    by_name = {name: gi for gi, name in names.items() if name}
    out = {}
    for name in sorted(set(PARTS) | KEEP):
        gi = by_name.get(name)
        if gi is None:
            raise SystemExit(f"part {name!r} is not in the .dat")
        anchor = part_anchor(groups[gi])
        if anchor is None:
            raise SystemExit(f"part {name!r} has no geometric anchor")
        target = PARTS.get(name, anchor)
        sx0, sy0 = world_to_screen(*anchor)
        sx1, sy1 = world_to_screen(*target)
        out[name] = dict(
            anchor=anchor,
            target=target,
            world=(target[0] - anchor[0], target[1] - anchor[1]),
            screen=(sx1 - sx0, sy1 - sy0),
            bmp=group_bitmap(groups[gi]),
        )
    return out


# --------------------------------------------------------------------------- #
# Art
# --------------------------------------------------------------------------- #
SS = 2
FONT_CANDIDATES = [
    "C:/Windows/Fonts/bahnschrift.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

CYAN = (96, 232, 255)
AMBER = (255, 190, 96)
MAGENTA = (255, 96, 150)
VIOLET = (150, 120, 255)


def load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def noise_layer(h, w, rng, scale, octaves=4):
    out = np.zeros((h, w), dtype=np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        size = max(2, int(scale / (2 ** o)))
        small = rng.random((size, size)).astype(np.float32)
        up = np.asarray(Image.fromarray((small * 255).astype(np.uint8)).resize(
            (w, h), Image.BICUBIC), dtype=np.float32) / 255.0
        out += up * amp
        total += amp
        amp *= 0.5
    return out / total


def render_art(parts):
    w, h = ART_W * SS, ART_H * SS
    rng = np.random.default_rng(11)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    v = yy / h

    # ---- backdrop --------------------------------------------------------
    base = np.zeros((h, w, 3), dtype=np.float32)
    base[:, :, 0] = 5 + 8 * (1 - v)
    base[:, :, 1] = 6 + 11 * (1 - v)
    base[:, :, 2] = 14 + 24 * (1 - v)
    cloud = noise_layer(h, w, rng, 42, octaves=5)
    cloud = np.clip((cloud - 0.45) * 2.6, 0, 1)
    base += cloud[:, :, None] * np.array([64.0, 36.0, 120.0], dtype=np.float32) * 0.5
    stars = (rng.random((h, w)) > 0.9997).astype(np.float32)
    stars = np.asarray(Image.fromarray((stars * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(0.5)), dtype=np.float32) / 255.0
    base += stars[:, :, None] * 210.0
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img, "RGBA")

    def P(points):
        return [(x * SS, y * SS) for x, y in points]

    def stroke(points, color, width, joint="curve"):
        draw.line(P(points), fill=color, width=max(1, int(width * SS)), joint=joint)

    # ---- case: side panels ------------------------------------------------
    case_left = project_poly([(LEFT_RAIL, FLOOR), (LEFT_RAIL, -8.2),
                              (LEFT_RAIL + 3.2, -13.6), (LEFT_RAIL + 3.2, 18.0)])
    case_right = project_poly([(LANE_OUT, FLOOR), (LANE_OUT, -9.30),
                               (LANE_OUT - 3.2, -14.2), (LANE_OUT - 3.2, 18.0)])
    for case in (case_left, case_right):
        draw.polygon(P(case), fill=(13, 16, 23, 255))
        stroke(case, (38, 44, 56, 255), 2.6, joint="curve")
        stroke(case, (66, 76, 92, 170), 0.7, joint="curve")

    # ---- playfield surface -------------------------------------------------
    surf = Image.new("L", (w, h), 0)
    ImageDraw.Draw(surf).polygon(P(project_poly(OUTLINE)), fill=255)

    field = np.zeros((h, w, 3), dtype=np.float32)
    cx, cy = world_to_screen(0.0, -1.5)
    r = np.sqrt((xx - cx * SS) ** 2 + (yy - cy * SS) ** 2) / (w * 0.70)
    pool = np.clip(1.0 - r, 0.0, 1.0) ** 2.2
    field += pool[:, :, None] * np.array([16.0, 30.0, 58.0], dtype=np.float32)
    field += (10 + 22 * (1 - v))[:, :, None] * np.array([0.30, 0.44, 0.95], dtype=np.float32)
    field += noise_layer(h, w, rng, 16, octaves=3)[:, :, None] * 8.0
    img = Image.composite(Image.fromarray(np.clip(field, 0, 255).astype(np.uint8)), img,
                          surf.point(lambda p: int(p)))
    draw = ImageDraw.Draw(img, "RGBA")

    # ---- projected world grid ----------------------------------------------
    for gx in np.arange(-7.4, 7.7, 1.0):
        stroke([world_to_screen(gx, -9.9), world_to_screen(gx, 13.0)],
               (66, 116, 176, 30), 0.5, joint=None)
    for gy in np.arange(-10.0, 13.5, 1.0):
        stroke([world_to_screen(-7.6, gy), world_to_screen(7.4, gy)],
               (66, 116, 176, 26), 0.5, joint=None)

    # Star chart rings around the mid-field.
    for rad, alpha in ((1.2, 46), (2.1, 34), (3.1, 24), (4.3, 16)):
        ring = project_poly(arc(0.0, 1.2, rad, 0, 360, steps=64))
        stroke(ring, (86, 200, 255, alpha), 0.7, joint="curve")

    # ---- hardware housings ---------------------------------------------------
    def sprite_rect(name):
        info = parts[name]
        bmp = info["bmp"]
        if not bmp:
            return None
        return (bmp["x"] - TABLE_OFF_X + info["screen"][0],
                bmp["y"] - TABLE_OFF_Y + info["screen"][1], bmp["w"], bmp["h"])

    def centre(name):
        rect = sprite_rect(name)
        if rect:
            x, y, bw, bh = rect
            return x + bw / 2, y + bh / 2, bw, bh
        sx, sy = world_to_screen(*parts[name]["target"])
        return sx, sy, 0, 0

    for name, _x, _y in BUMPER_ATTACK + BUMPER_LAUNCH:
        sx, sy, bw, bh = centre(name)
        rad = max(bw, bh) * 0.42
        draw.ellipse([SS * (sx - rad * 1.30), SS * (sy - rad * 1.30),
                      SS * (sx + rad * 1.30), SS * (sy + rad * 1.30)],
                     fill=(9, 13, 24, 255), outline=(54, 120, 170, 255), width=int(1.3 * SS))
        draw.ellipse([SS * (sx - rad * 1.12), SS * (sy - rad * 1.12),
                      SS * (sx + rad * 1.12), SS * (sy + rad * 1.12)],
                     outline=(110, 214, 255, 110), width=max(1, int(0.6 * SS)))

    for name in [n for n in parts if n.startswith("a_targ")]:
        rect = sprite_rect(name)
        if not rect:
            continue
        x, y, bw, bh = rect
        pad = 3
        draw.rounded_rectangle([SS * (x - pad), SS * (y - pad),
                                SS * (x + bw + pad), SS * (y + bh + pad)],
                               radius=2 * SS, fill=(12, 17, 28, 235),
                               outline=(255, 198, 92, 200), width=max(1, int(0.8 * SS)))

    for name in [n for n in parts if n.startswith("a_roll")]:
        rect = sprite_rect(name)
        if not rect:
            continue
        x, y, bw, bh = rect
        draw.rounded_rectangle([SS * (x - 2), SS * (y - 2), SS * (x + bw + 2), SS * (y + bh + 2)],
                               radius=(bw + 4) * SS / 2, fill=(9, 14, 26, 235),
                               outline=(92, 226, 255, 170), width=max(1, int(0.7 * SS)))

    for name in ("a_kout1", "a_kout2", "a_kout3"):
        if name not in parts:
            continue
        sx, sy, bw, bh = centre(name)
        rad = max(max(bw, bh) * 0.85, 13)
        draw.ellipse([SS * (sx - rad), SS * (sy - rad), SS * (sx + rad), SS * (sy + rad)],
                     fill=(10, 13, 26, 255), outline=(150, 120, 255, 210), width=int(1.1 * SS))
        draw.ellipse([SS * (sx - rad * 0.62), SS * (sy - rad * 0.62),
                      SS * (sx + rad * 0.62), SS * (sy + rad * 0.62)],
                     fill=(30, 18, 50, 255), outline=(126, 92, 220, 150), width=max(1, int(0.5 * SS)))

    for name in ("a_kick1", "a_kick2"):
        if name not in parts:
            continue
        rect = sprite_rect(name)
        if rect:
            x, y, bw, bh = rect
            draw.rounded_rectangle([SS * (x - 2), SS * (y - 2), SS * (x + bw + 2), SS * (y + bh + 2)],
                                   radius=3 * SS, fill=(16, 12, 10, 230),
                                   outline=(255, 150, 90, 190), width=max(1, int(0.7 * SS)))

    # ---- walls ----------------------------------------------------------------
    for _name, poly, _grp in WALLS:
        spts = project_poly(poly)
        stroke(spts, (5, 8, 14, 255), 9.0)
        stroke(spts, (22, 34, 56, 255), 6.6)
        stroke(spts, (52, 84, 128, 255), 3.6)
        stroke(spts, (132, 226, 255, 200), 1.0)
        stroke(spts, (40, 200, 255, 70), 2.4)

    # Slingshot rubber.
    for poly in (SLING_L, SLING_R):
        spts = P(project_poly(poly))
        draw.polygon(spts, fill=(26, 12, 34, 255))
        draw.line(spts + [spts[0]], fill=MAGENTA + (255,), width=int(2.6 * SS), joint="curve")
        draw.line(spts + [spts[0]], fill=(255, 200, 225, 120), width=int(1.0 * SS), joint="curve")

    # ---- shooter lane ----------------------------------------------------------
    stroke([world_to_screen(LANE_IN, -7.2), world_to_screen(LANE_IN, 12.9)],
           (30, 210, 255, 46), 1.0)
    for i in range(11):
        y = 11.6 - i * 1.85
        stroke([world_to_screen(LANE_OUT + 0.10, y), world_to_screen(LANE_IN - 0.10, y)],
               (70, 200, 255, 55), 0.5, joint=None)

    # ---- bottom apron ----------------------------------------------------------
    apron = project_poly([(-6.3, FLOOR), (6.3, FLOOR), (7.0, 15.4), (-7.0, 15.4)])
    draw.polygon(P(apron), fill=(9, 11, 17, 255))
    stroke(apron + [apron[0]], (44, 54, 70, 255), 1.4, joint="curve")
    stroke([world_to_screen(-1.9, FLOOR - 0.02), world_to_screen(1.9, FLOOR - 0.02)],
           (0, 0, 0, 255), 4.0)

    # ---- markings ---------------------------------------------------------------
    font = load_font(int(20 * SS))
    tx, ty = world_to_screen(0.0, -12.85)
    text = "NEBULA"
    tw = draw.textlength(text, font=font)
    draw.text((SS * tx - tw / 2, SS * ty - 10 * SS), text, font=font, fill=(150, 230, 255, 235))
    sub = load_font(int(6.0 * SS))
    small = "DEEP FIELD  //  CLASSIC"
    sw = draw.textlength(small, font=sub)
    draw.text((SS * tx - sw / 2, SS * ty + 12 * SS), small, font=sub, fill=(96, 150, 190, 210))

    for wx, wy, label in ((-5.0, 11.9, "MISSION"), (4.8, 11.9, "LAUNCH")):
        sx, sy = world_to_screen(wx, wy)
        f = load_font(int(5.0 * SS))
        lw = draw.textlength(label, font=f)
        draw.text((SS * sx - lw / 2, SS * sy), label, font=f, fill=(120, 170, 210, 170))

    # ---- glow ---------------------------------------------------------------------
    src = np.asarray(img, dtype=np.float32)
    bright = np.clip((src.max(axis=2) - 118.0) / 137.0, 0, 1)[:, :, None]
    glow = Image.fromarray(np.clip(src * bright, 0, 255).astype(np.uint8))
    glow = glow.filter(ImageFilter.GaussianBlur(8 * SS))
    img = Image.fromarray(np.clip(src + np.asarray(glow, dtype=np.float32) * 0.5, 0, 255).astype(np.uint8))

    vig = 1.0 - 0.5 * np.clip(((xx - w / 2) ** 2 / (w / 2) ** 2 +
                               (yy - h / 2) ** 2 / (h / 2) ** 2) * 0.5, 0, 1)
    img = Image.fromarray(np.clip(np.asarray(img, dtype=np.float32) * vig[:, :, None],
                                  0, 255).astype(np.uint8))
    return img.resize((ART_W, ART_H), Image.LANCZOS).convert("RGB")


# --------------------------------------------------------------------------- #
# C++ output
# --------------------------------------------------------------------------- #
def emit_header(parts):
    flat, starts, acc = [], [], 0
    for _name, poly, _grp in WALLS:
        starts.append(acc)
        for x, y in poly:
            flat.extend((x, y))
            acc += 2
    starts.append(acc)

    lines = [
        "// Generated by tools/nebula_layout.py -- do not edit by hand.",
        "// Playfield geometry and hardware placement for the NEBULA layout.",
        "//",
        "// World holds the translation applied to the part's own coordinates;",
        "// Screen holds the matching pixel offset for its sprites. Both come",
        "// from the same projection, so art and collision stay aligned.",
        "#pragma once",
        "",
        "struct NebulaPartOffset",
        "{",
        "\tconst char* Name;",
        "\tfloat WorldX;",
        "\tfloat WorldY;",
        "\tfloat ScreenX;",
        "\tfloat ScreenY;",
        "};",
        "",
        "static const NebulaPartOffset kNebulaParts[] =",
        "{",
    ]
    for name in sorted(parts):
        info = parts[name]
        wx, wy = info["world"]
        sx, sy = info["screen"]
        lines.append(f'\t{{"{name}", {wx:.4f}f, {wy:.4f}f, {sx:.3f}f, {sy:.3f}f}},')
    lines += [
        "};",
        "",
        "static const int kNebulaPartCount = "
        "static_cast<int>(sizeof(kNebulaParts) / sizeof(kNebulaParts[0]));",
        "",
        "// Wall polylines as x/y pairs; run N spans [Start[N], Start[N + 1]).",
        "static const float kNebulaWallPoints[] =",
        "{",
    ]
    for i in range(0, len(flat), 6):
        lines.append("\t" + ", ".join(f"{val:.4f}f" for val in flat[i:i + 6]) + ",")
    lines += ["};", "", "static const int kNebulaWallStart[] =", "{"]
    for i in range(0, len(starts), 10):
        lines.append("\t" + ", ".join(str(val) for val in starts[i:i + 10]) + ",")
    lines += [
        "};",
        "",
        "static const int kNebulaWallRuns = "
        "static_cast<int>(sizeof(kNebulaWallStart) / sizeof(kNebulaWallStart[0])) - 1;",
        "",
    ]
    HDR_OUT.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()

    parts = collect_parts()
    art = render_art(parts)
    ART_OUT.parent.mkdir(parents=True, exist_ok=True)
    art.save(ART_OUT)
    emit_header(parts)
    print(f"art  -> {ART_OUT}")
    print(f"code -> {HDR_OUT} ({len(parts)} parts, {len(WALLS)} wall runs)")
    if args.preview:
        art.save(ROOT / "nebula-preview.png")


if __name__ == "__main__":
    main()
