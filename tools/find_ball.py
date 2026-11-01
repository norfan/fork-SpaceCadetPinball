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


def find_ball(a, b):
    """The ball is the object that moves the most between two frames. Find the
    strongest motion cluster and return its centre."""
    w, h, ra = read_bmp(a)
    _, _, rb = read_bmp(b)
    hits = []
    for y in range(100, h):
        row_a, row_b = ra[y], rb[y]
        for x in range(w):
            o = x * 4
            d = abs(row_a[o]-row_b[o]) + abs(row_a[o+1]-row_b[o+1]) + abs(row_a[o+2]-row_b[o+2])
            if d > 60:
                hits.append((x, y, d))
    if not hits:
        return None
    # Cluster by proximity; the ball is the tightest, densest cluster.
    clusters = []
    for p in hits:
        for c in clusters:
            if abs(c[0][0]-p[0]) < 45 and abs(c[0][1]-p[1]) < 45:
                c.append(p); break
        else:
            clusters.append([p])
    # Rank by density (pixels per bounding-box area), not raw count: a trail
    # is long but sparse, the ball is round and solid.
    def density(c):
        xs = [p[0] for p in c]; ys = [p[1] for p in c]
        area = max(1, (max(xs)-min(xs)+1) * (max(ys)-min(ys)+1))
        return len(c) / area
    clusters.sort(key=lambda c: (len(c), density(c)), reverse=True)
    c = clusters[0]
    xs = [p[0] for p in c]; ys = [p[1] for p in c]
    # Centre on the median so a long trail cannot drag the centre away.
    xs.sort(); ys.sort()
    return xs[len(xs)//2], ys[len(ys)//2], len(c), (min(xs), max(xs), min(ys), max(ys))


def crop(src, dst, cx, cy, rad=55, zoom=3):
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
        fs = shoot(k, f'fb_{k}')
        if len(fs) < 2:
            print(f'{name}: only {fs}'); continue
        r = find_ball(fs[0], fs[1])
        if not r:
            print(f'{name}: no motion'); continue
        cx, cy, n, bbox = r
        # Count element-coloured pixels around the ball.
        w, h, rows = read_ball = read_bmp(fs[0])
        cnt = 0
        for y in range(max(0, cy-40), min(h, cy+40)):
            row = rows[y]
            for x in range(max(0, cx-40), min(w, cx+40)):
                o = x*4
                if abs(row[o]-er) <= 70 and abs(row[o+1]-eg) <= 70 and abs(row[o+2]-eb) <= 70:
                    cnt += 1
        print(f'{name:9s} ball=({cx},{cy}) cluster={n} bbox={bbox} element_px_near={cnt}')
        crop(fs[0], f'fb_ball{k}.png', cx, cy)
