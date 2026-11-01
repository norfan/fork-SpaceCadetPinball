import sys
sys.path.insert(0, 'tools')
from analyze_shot import read_bmp, write_png


def find_ball(w, h, rows):
    """The stock chrome ball is a small sphere with a teal cast. Find the
    largest compact cluster of teal pixels below the HUD."""
    hits = []
    for y in range(120, h):
        row = rows[y]
        for x in range(60, w - 60):
            o = x * 4
            r = row[o]; g = row[o+1]; b = row[o+2]
            if g > 140 and b > 140 and r + 30 < g and abs(g - b) < 90:
                hits.append((x, y))
    if not hits:
        return None
    # cluster by proximity
    clusters = []
    for p in hits:
        for c in clusters:
            if abs(c[0][0] - p[0]) < 40 and abs(c[0][1] - p[1]) < 40:
                c.append(p); break
        else:
            clusters.append([p])
    clusters.sort(key=len, reverse=True)
    c = clusters[0]
    xs = [p[0] for p in c]; ys = [p[1] for p in c]
    return sum(xs) // len(xs), sum(ys) // len(ys), len(c)


def crop(src, dst, cx, cy, rad, zoom):
    w, h, rows = read_bmp(src)
    x0 = max(0, cx - rad); x1 = min(w, cx + rad + 1)
    y0 = max(0, cy - rad); y1 = min(h, cy + rad + 1)
    cw, ch = x1 - x0, y1 - y0
    out = []
    for y in range(ch):
        base = rows[y0 + y]
        line = bytearray()
        for x in range(cw):
            o = (x0 + x) * 4
            line += base[o:o + 4] * zoom
        for _ in range(zoom):
            out.append(bytes(line))
    write_png(dst, cw * zoom, ch * zoom, out)


for k in [0, 1, 2, 3, 4, 5, 6, 7]:
    src = f'shot_ball{k}.bmp'
    try:
        w, h, rows = read_bmp(src)
    except FileNotFoundError:
        print(f'ball={k}: missing'); continue
    b = find_ball(w, h, rows)
    if not b:
        print(f'ball={k}: not detected'); continue
    cx, cy, n = b
    print(f'ball={k} at ({cx},{cy}) cluster={n}')
    crop(src, f'crop_ball{k}.png', cx, cy, 50, 3)
