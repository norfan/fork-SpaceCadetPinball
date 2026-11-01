import sys, subprocess, os
sys.path.insert(0, 'tools')
from analyze_shot import read_bmp, write_png

BIN = 'bin/SpaceCadetPinball.exe'
ENV = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software')

STYLES = {
    0: ('Classic',  200, 220, 240),
    1: ('Fire',     255, 120,  30),
    2: ('Ice',      130, 220, 255),
    3: ('Electric', 175, 130, 255),
    4: ('Plasma',   255,  90, 200),
    5: ('Rainbow',  255, 255, 255),
    6: ('Ghost',    205, 235, 255),
    7: ('Gold',     255, 210,  90),
}


def shoot(kind, prefix, frame=120, count=8, interval=10):
    out = f'{prefix}.bmp'
    for f in os.listdir('.'):
        if f.startswith(prefix + '_'):
            os.remove(f)
    try:
        subprocess.run([BIN, f'-ball={kind}', '-autoplay', f'-screenshot={out}',
                        f'-screenshot-frame={frame}', f'-screenshot-count={count}',
                        f'-screenshot-interval={interval}'],
                       env=ENV, timeout=25, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass
    return sorted(f for f in os.listdir('.') if f.startswith(prefix + '_'))


def motion(a, b):
    w, h, ra = read_bmp(a)
    _, _, rb = read_bmp(b)
    pts = []
    for y in range(100, h):
        row_a, row_b = ra[y], rb[y]
        for x in range(w):
            o = x * 4
            d = abs(row_a[o]-row_b[o]) + abs(row_a[o+1]-row_b[o+1]) + abs(row_a[o+2]-row_b[o+2])
            if d > 90:
                pts.append((x, y, d))
    return w, h, pts


def cluster(pts, r=12):
    cs = []
    for p in pts:
        for c in cs:
            if abs(c[0][0]-p[0]) < r and abs(c[0][1]-p[1]) < r:
                c.append(p); break
        else:
            cs.append([p])
    return cs


def pick_ball(pts):
    """The ball is a compact, roughly circular cluster ~ ball-sized. Score by
    fill ratio inside the bounding box (a sphere is round, a trail is not)."""
    best = None
    for c in cluster(pts, 12):
        xs = [p[0] for p in c]; ys = [p[1] for p in c]
        bw = max(xs)-min(xs)+1; bh = max(ys)-min(ys)+1
        if bw < 6 or bh < 6 or bw > 40 or bh > 40:
            continue
        fill = len(c) / float(bw*bh)
        if fill < 0.35:
            continue
        cx = sum(xs)//len(xs); cy = sum(ys)//len(ys)
        score = (fill, len(c))
        if best is None or score > best[0]:
            best = (score, cx, cy, len(c), (min(xs), max(xs), min(ys), max(ys)))
    return best


def crop(src, dst, cx, cy, rad=28, zoom=8):
    w, h, rows = read_bmp(src)
    x0 = max(0, cx-rad); x1 = min(w, cx+rad+1)
    y0 = max(0, cy-rad); y1 = min(h, cy+rad+1)
    out = []
    for y in range(y0, y1):
        base = rows[y]
        line = bytearray()
        for x in range(x0, x1):
            o = (x0+x)*4
            line += base[o:o+4]*zoom
        for _ in range(zoom):
            out.append(bytes(line))
    write_png(dst, (x1-x0)*zoom, (y1-y0)*zoom, out)


if __name__ == '__main__':
    kinds = [int(a) for a in sys.argv[1:]] or list(STYLES)
    for k in kinds:
        name, er, eg, eb = STYLES[k]
        fs = shoot(k, f'pb_{k}')
        hit = None
        for i in range(len(fs)-1):
            w, h, pts = motion(fs[i], fs[i+1])
            if not pts:
                continue
            r = pick_ball(pts)
            if r:
                hit = (fs[i+1], r[1], r[2], r[3])
                break
        if not hit:
            print(f'{name:9s}: ball not detected'); continue
        src, cx, cy, n = hit
        w, h, rows = read_bmp(src)
        patch = []
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                o = ((cy+dy)*w + (cx+dx))*4
                patch.append((rows[cy+dy][(cx+dx)*4], rows[cy+dy][(cx+dx)*4+1], rows[cy+dy][(cx+dx)*4+2]))
        avg = tuple(sum(v[i] for v in patch)//len(patch) for i in range(3))
        print(f'{name:9s} expect=({er},{eg},{eb}) ball=({cx},{cy}) n={n} avg={avg}')
        crop(src, f'pb_ball{k}.png', cx, cy)
