"""Build custom playfield skins for Space Cadet Pinball.

The skins are drawn from scratch - gradient wash, light bands, grid, rings,
lane markers, rim - so they are genuinely new table art rather than a recolour
of the shipped bitmap. The original table is still loaded from the DAT at
runtime; these files only override its pixels while a skin is active.

Output goes to bin/themes/*.bmp. The DAT is never modified, so switching back
to the stock table is lossless.

Usage:
  python tools/make_themes.py [--out bin/themes] [--preview themes-preview.png]
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

TABLE_W, TABLE_H = 583, 751
SS = 2  # supersampling factor, keeps the hairlines clean


THEMES = {
    "neon-grid": dict(
        top=(9, 14, 32),
        bottom=(3, 3, 9),
        glow=dict(center=(0.50, 0.58), radius=0.72, color=(26, 116, 150), strength=1.0),
        accent=(74, 206, 202),
        texture_gain=0.55,
        accent_dim=(30, 96, 116),
        grid=dict(step=16, alpha=26),
        bands=[(0.20, 0.26, (24, 120, 150), 0.30), (0.78, 0.22, (18, 70, 130), 0.26)],
        rings=(0.50, 0.605, (44, 74, 106, 142, 186), 0.55),
        spots=[
            (0.50, 0.14, 0.30, (20, 90, 130), 0.55),
            (0.28, 0.42, 0.22, (16, 74, 108), 0.35),
            (0.72, 0.46, 0.22, (16, 74, 108), 0.32),
        ],
        ticks=True,
        vignette=0.60,
    ),
    "violet-noir": dict(
        top=(30, 16, 46),
        bottom=(11, 6, 19),
        glow=dict(center=(0.50, 0.52), radius=0.86, color=(96, 34, 132), strength=0.95),
        accent=(206, 158, 255),
        accent_dim=(92, 56, 128),
        texture_gain=0.55,
        grid=dict(step=20, alpha=34),
        bands=[(0.26, 0.30, (72, 26, 104), 0.26), (0.79, 0.22, (52, 20, 86), 0.22)],
        rings=(0.50, 0.605, (56, 104, 152, 210), 0.44),
        spots=[
            (0.50, 0.13, 0.30, (74, 26, 110), 0.50),
            (0.30, 0.42, 0.24, (58, 22, 92), 0.32),
            (0.70, 0.44, 0.24, (58, 22, 92), 0.30),
        ],
        ticks=True,
        vignette=0.52,
    ),
    "amber-dusk": dict(
        top=(24, 12, 7),
        bottom=(7, 4, 3),
        glow=dict(center=(0.50, 0.60), radius=0.58, color=(255, 120, 30), strength=0.80),
        accent=(255, 190, 112),
        texture_gain=0.50,
        accent_dim=(120, 62, 24),
        grid=None,
        bands=[(0.18, 0.30, (190, 88, 26), 0.22), (0.74, 0.26, (120, 54, 18), 0.18)],
        rings=(0.50, 0.605, (58, 104, 156, 214), 0.34),
        spots=[
            (0.50, 0.16, 0.28, (150, 62, 18), 0.45),
            (0.26, 0.44, 0.22, (120, 48, 14), 0.30),
        ],
        ticks=True,
        vignette=0.66,
    ),
}


def base_wash(spec, w, h):
    yy, xx = np.mgrid[0:h, 0:w]
    t = (yy / max(h - 1, 1)).astype(np.float32)[:, :, None]
    top = np.array(spec["top"], dtype=np.float32)
    bottom = np.array(spec["bottom"], dtype=np.float32)
    out = top * (1.0 - t) + bottom * t

    g = spec["glow"]
    cx, cy = g["center"][0] * w, g["center"][1] * h
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (g["radius"] * max(w, h))
    out += np.clip(1.0 - r, 0.0, 1.0)[:, :, None] ** 2.0 * np.array(g["color"], dtype=np.float32) * g["strength"]

    for center, width, color, strength in spec["bands"]:
        pos = (xx * 0.30 + yy * 0.70) / float(h)
        d = np.abs(pos - center) / width
        out += np.clip(1.0 - d, 0.0, 1.0)[:, :, None] ** 2.0 * np.array(color, dtype=np.float32) * strength

    # Soft pools of light break the flat wash into zones, which is what makes the
    # surface read as a playfield with areas rather than a solid backdrop.
    for scx, scy, srad, color, strength in spec.get("spots", []):
        r = np.sqrt((xx - scx * w) ** 2 + (yy - scy * h) ** 2) / (srad * max(w, h))
        out += np.clip(1.0 - r, 0.0, 1.0)[:, :, None] ** 2.5 * np.array(color, dtype=np.float32) * strength

    # Film grain keeps the gradients from looking like plastic.
    rng = np.random.default_rng(7)
    out += rng.normal(0.0, 2.6, (h, w, 1)).astype(np.float32)

    return out


def detail_layer(src, w, h):
    """Emboss the shipped layout into the skin.

    A directional gradient of the original luminance is used as a bump map, so
    the ramps, posts and cut-outs read as pressed-in relief. Colour and overall
    lighting still come entirely from the theme, which keeps the artwork new
    while giving the surface the physical structure it needs.
    """
    lum = src.convert("L").resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.0))
    fine = np.asarray(lum, dtype=np.float32)
    gx = np.gradient(fine, axis=1)
    gy = np.gradient(fine, axis=0)
    emboss = (gx * 0.55 + gy * 0.85) * 2.2
    return np.clip(emboss, -78.0, 78.0)


def draw_skin(spec, w, h, texture=None):
    """Draw one skin at supersampled resolution, return a PIL image."""
    out = base_wash(spec, w, h)
    if texture is not None:
        out += texture[:, :, None] * spec.get("texture_gain", 0.0)
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img, "RGBA")
    accent = spec["accent"]
    dim = spec["accent_dim"]
    sx, sy = w / float(TABLE_W), h / float(TABLE_H)
    px = lambda v: int(round(v * sx))  # noqa: E731
    py = lambda v: int(round(v * sy))  # noqa: E731

    # Grid.
    if spec["grid"]:
        step = spec["grid"]["step"]
        a = spec["grid"]["alpha"]
        for x in range(0, w, step):
            d.line([(x, 0), (x, h)], fill=accent + (a // 3,), width=1)
        for y in range(0, h, step):
            d.line([(0, y), (w, y)], fill=accent + (a // 3,), width=1)
        # Every fourth line is brighter, like drafting paper.
        for x in range(0, w, step * 4):
            d.line([(x, 0), (x, h)], fill=accent + (a,), width=1)
        for y in range(0, h, step * 4):
            d.line([(0, y), (w, y)], fill=accent + (a,), width=1)

    # Concentric rings around the playfield centre.
    cxr, cyr, radii, alpha = spec["rings"]
    cx, cy = cxr * w, cyr * h
    scale = w / float(TABLE_W * SS)
    for i, base_r in enumerate(radii):
        r = base_r * scale
        a = int(255 * alpha * (1.0 - i * 0.15))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=accent + (a,), width=max(1, SS))
    # Crosshair ticks on the outer ring.
    r = radii[-1] * scale
    for ang in range(0, 360, 45):
        rad = np.deg2rad(ang)
        x1, y1 = cx + np.cos(rad) * (r - 6 * SS), cy + np.sin(rad) * (r - 6 * SS)
        x2, y2 = cx + np.cos(rad) * (r + 6 * SS), cy + np.sin(rad) * (r + 6 * SS)
        d.line([(x1, y1), (x2, y2)], fill=accent + (int(255 * alpha),), width=max(1, SS))

    # --- Table furniture, drawn to the real layout so the skin reads as a
    # --- pinball table instead of wallpaper.

    # Launch lane down the right side, with a return hook at the bottom.
    lane_in, lane_out = px(524), px(570)
    d.line([(lane_out, py(46)), (lane_out, py(668))], fill=accent + (170,), width=max(2, 3 * SS))
    d.line([(lane_in, py(94)), (lane_in, py(660))], fill=accent + (110,), width=max(2, 2 * SS))
    d.arc([lane_in, py(596), lane_out, py(724)], 0, 90, fill=accent + (170,), width=max(2, 3 * SS))
    for i in range(10):
        y = py(120 + i * 52)
        d.line([(lane_out - px(8), y), (lane_out - px(1), y - px(9))], fill=accent + (140,),
               width=max(1, SS))
        d.line([(lane_out - px(8), y), (lane_out - px(1), y + px(9))], fill=accent + (140,),
               width=max(1, SS))

    # Funnel towards the flippers: two rails meeting at the drain.
    d.line([(px(120), py(748)), (px(214), py(636))], fill=accent + (120,), width=max(2, 3 * SS))
    d.line([(px(462), py(748)), (px(368), py(636))], fill=accent + (120,), width=max(2, 3 * SS))
    # Outlane guides.
    d.line([(px(96), py(700)), (px(96), py(540))], fill=accent + (90,), width=max(1, 2 * SS))
    d.line([(px(487), py(700)), (px(487), py(540))], fill=accent + (90,), width=max(1, 2 * SS))

    # Upper left lane chevrons, mirroring the ball path into the bumpers.
    for i in range(6):
        x = px(150 + i * 26)
        d.line([(x, py(212)), (x - px(16), py(196))], fill=accent + (120,), width=max(1, 2 * SS))
        d.line([(x, py(212)), (x + px(16), py(196))], fill=accent + (120,), width=max(1, 2 * SS))

    # Exit gate marks around the centre ring.
    for ang in (200, 250, 290, 340):
        rad = np.deg2rad(ang)
        rr = (radii[0] + 26) * scale
        gx, gy = cx + np.cos(rad) * rr, cy + np.sin(rad) * rr
        d.ellipse([gx - 3 * SS, gy - 3 * SS, gx + 3 * SS, gy + 3 * SS], outline=accent + (120,),
                  width=max(1, SS))

    # Bottom tick row, like a ruler.
    if spec["ticks"]:
        y = 0.955 * h
        for x in range(int(0.10 * w), int(0.86 * w), 11 * SS):
            long = (x // (11 * SS)) % 5 == 0
            d.line([(x, y), (x, y + (10 if long else 5) * SS)], fill=dim + (150,), width=max(1, SS))

    # Corner brackets.
    m = 14 * SS
    ln = 26 * SS
    for (x, y, dx, dy) in ((m, m, 1, 1), (w - m, m, -1, 1), (m, h - m, 1, -1), (w - m, h - m, -1, -1)):
        d.line([(x, y), (x + dx * ln, y)], fill=accent + (120,), width=max(1, SS))
        d.line([(x, y), (x, y + dy * ln)], fill=accent + (120,), width=max(1, SS))

    # Rim + pinstripe.
    d.rectangle([6 * SS, 6 * SS, w - 6 * SS, h - 6 * SS], outline=accent + (200,), width=max(2, 2 * SS))
    d.rectangle([16 * SS, 16 * SS, w - 16 * SS, h - 16 * SS], outline=accent + (90,), width=max(1, SS))

    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bin/themes")
    ap.add_argument("--preview", default="themes-preview.png")
    ap.add_argument("--src", default="table-playfield.png", help="optional, for the side by side reference")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    src_path_probe = Path(args.src)
    reference = Image.open(src_path_probe).convert("RGB").resize((TABLE_W, TABLE_H)) \
        if src_path_probe.exists() else None

    w, h = TABLE_W * SS, TABLE_H * SS
    texture = detail_layer(reference, w, h) if reference is not None else None
    built = []
    for name, spec in THEMES.items():
        img = draw_skin(spec, w, h, texture).resize((TABLE_W, TABLE_H), Image.LANCZOS)
        img.save(out_dir / f"{name}.bmp", format="BMP")
        built.append((name, img))
        print(f"wrote {out_dir / (name + '.bmp')}")

    src_path = Path(args.src)
    sheet_items = []
    if src_path.exists():
        sheet_items.append(("Original", reference.resize((TABLE_W, TABLE_H))))
    sheet_items.extend(built)

    pad = 12
    sheet = Image.new("RGB", (len(sheet_items) * (TABLE_W + pad) + pad, TABLE_H + 2 * pad), (22, 22, 26))
    for i, (_, img) in enumerate(sheet_items):
        sheet.paste(img, (pad + i * (TABLE_W + pad), pad))
    sheet.save(args.preview)
    print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
