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


def shoot(kind, prefix, frame=140, count=6, interval=8):
    out = f'{prefix}.bmp'
    for f in os.listdir('.'):
        if f.startswith(prefix + '_'):
            os.remove(f)
    try:
        subprocess.run([BIN, f'-ball={kind}', '-autoplay', f'-screenshot={out}',
                        f'-screenshot-frame={frame}', f'-screenshot-count={count}',
                        f'-screenshot-interval={interval}'],
                       env=ENV, timeout=22, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass
    return sorted(f for f in os.listdir('.') if f.startswith(prefix + '_'))


def locate(a, b):
    """The solid ball is redrawn every frame, so the pixels it covers change
    the most. Take the centroid of the top-motion pixels."""
    w, h, ra = read_bmp(a)
    _, _, rb = read_bmp(b)
    scored = []
    for y in range(100, h):
        row_a, row_b = ra[y], rb[y]
        for x in range(w):
            o = x * 4
            d = abs(row_a[o]-row_b[o]) + abs(row_a[o+1]-row_b[o+1]) + abs(row_a[o+2]-row_b[o+2])
            if d > 120:
                scored.append((d, x, y))
    if not scored:
        return None
    scored.sort(reverse=True)
    top = scored[:60]
    xs = [p[1] for p in top]; ys = [p[2] for p in top]
    return sum(xs)//len(xs), sum(ys)//len(ys), len(scored)


def crop(src, dst, cx, cy, rad=26, zoom=9):
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
        fs = shoot(k, f'vb_{k}')
        found = None
        for i in range(len(fs)-1):
            r = locate(fs[i], fs[i+1])
            if r:
                found = (fs[i+1], r[0], r[1], r[2])
                break
        if not found:
            print(f'{name:9s}: not detected'); continue
        src, cx, cy, n = found
        w, h, rows = read_bmp(src)
        patch = []
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                patch.append((rows[cy+dy][(cx+dx)*4], rows[cy+dy][(cx+dx)*4+1], rows[cy+dy][(cx+dx)*4+2]))
        avg = tuple(sum(v[i] for v in patch)//len(patch) for i in range(3))
        print(f'{name:9s} expect=({er},{eg},{eb}) ball=({cx},{cy}) moved={n} avg={avg}')
        crop(src, f'vb_ball{k}.png', cx, cy)
