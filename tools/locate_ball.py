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


def shoot(kind, prefix, frame=200, count=2, interval=3):
    out = f'{prefix}.bmp'
    for f in os.listdir('.'):
        if f.startswith(prefix + '_'):
            os.remove(f)
    try:
        subprocess.run([BIN, f'-ball={kind}', '-autoplay', f'-screenshot={out}',
                        f'-screenshot-frame={frame}', f'-screenshot-count={count}',
                        f'-screenshot-interval={interval}'],
                       env=ENV, timeout=12, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass
    return sorted(f for f in os.listdir('.') if f.startswith(prefix + '_'))


def bright_clusters(path, thr=185):
    """Clusters of near-white pixels: the chrome ball and the bright lamps."""
    w, h, rows = read_bmp(path)
    pts = []
    for y in range(100, h):
        row = rows[y]
        for x in range(w):
            o = x * 4
            if row[o] > thr and row[o+1] > thr and row[o+2] > thr:
                pts.append((x, y))
    clusters = []
    for p in pts:
        for c in clusters:
            if abs(c[0][0]-p[0]) < 14 and abs(c[0][1]-p[1]) < 14:
                c.append(p); break
        else:
            clusters.append([p])
    res = []
    for c in clusters:
        xs = [p[0] for p in c]; ys = [p[1] for p in c]
        res.append((len(c), sum(xs)//len(xs), sum(ys)//len(ys),
                    min(xs), max(xs), min(ys), max(ys)))
    return res


def locate(a, b):
    """The ball is the bright compact blob that moved between the frames."""
    ca = bright_clusters(a)
    cb = bright_clusters(b)
    best = None
    for na, ax, ay, *_ in ca:
        for nb, bx, by, *_ in cb:
            if nb < 6:
                continue
            d = abs(ax-bx) + abs(ay-by)
            moved = 3 < d < 160
            # Prefer compact blobs that moved.
            score = (1 if moved else 0, nb, -d)
            if best is None or score > best[0]:
                best = (score, bx, by, nb)
    return best


def crop(src, dst, cx, cy, rad=30, zoom=8):
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
        fs = shoot(k, f'lb_{k}')
        if len(fs) < 2:
            print(f'{name}: only {fs}'); continue
        r = locate(fs[0], fs[1])
        if not r:
            print(f'{name}: no candidate'); continue
        _, cx, cy, nb = r
        w, h, rows = read_bmp(fs[1])
        o = (cx)*4
        # sample a 5x5 patch around the ball
        vals = []
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                oo = ((cy+dy)*w + (cx+dx))*4
                vals.append((rows[cy+dy][(cx+dx)*4], rows[cy+dy][(cx+dx)*4+1], rows[cy+dy][(cx+dx)*4+2]))
        avg = tuple(sum(v[i] for v in vals)//len(vals) for i in range(3))
        print(f'{name:9s} expect=({er},{eg},{eb}) ball=({cx},{cy}) size={nb} avg_rgb={avg}')
        crop(fs[1], f'lb_ball{k}.png', cx, cy)
