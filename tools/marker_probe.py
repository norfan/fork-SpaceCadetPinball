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


def shoot(kind, prefix, frame=150, extra=()):
    out = f'{prefix}.bmp'
    for f in os.listdir('.'):
        if f.startswith(prefix + '_'):
            os.remove(f)
    args = [BIN, f'-ball={kind}', '-autoplay', f'-screenshot={out}',
            f'-screenshot-frame={frame}', '-screenshot-count=1']
    args.extend(extra)
    try:
        subprocess.run(args, env=ENV, timeout=16, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass
    return sorted(f for f in os.listdir('.') if f.startswith(prefix) and f.endswith('.bmp'))


def find_blue_circle(path):
    """The debug overlay draws the ball marker in pure blue (0,0,255)."""
    w, h, rows = read_bmp(path)
    pts = []
    for y in range(100, h):
        row = rows[y]
        for x in range(w):
            o = x * 4
            if row[o] < 40 and row[o+1] < 40 and row[o+2] > 200:
                pts.append((x, y))
    if not pts:
        return None
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return sum(xs)//len(xs), sum(ys)//len(ys), len(pts), (min(xs), max(xs), min(ys), max(ys))


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
        # -debug turns on the overlay; the grid/edges/sprites overlays are noisy,
        # so the marker must be found by its exact pure-blue colour.
        fs = shoot(k, f'bl_{k}', extra=('-debug',))
        if not fs:
            print(f'{name:9s}: no shot'); continue
        r = find_blue_circle(fs[0])
        if not r:
            print(f'{name:9s}: no blue marker'); continue
        cx, cy, n, bbox = r
        w, h, rows = read_bmp(fs[0])
        # Sample the ball core, a few pixels left of the marker centre.
        patch = []
        for dy in range(-2, 3):
            for dx in range(-6, -1):
                o = ((cy+dy)*w + (cx+dx))*4
                patch.append((rows[cy+dy][(cx+dx)*4], rows[cy+dy][(cx+dx)*4+1], rows[cy+dy][(cx+dx)*4+2]))
        avg = tuple(sum(v[i] for v in patch)//len(patch) for i in range(3))
        print(f'{name:9s} expect=({er},{eg},{eb}) marker=({cx},{cy}) n={n} bbox={bbox} core_avg={avg}')
        crop(fs[0], f'bl_ball{k}.png', cx, cy)
