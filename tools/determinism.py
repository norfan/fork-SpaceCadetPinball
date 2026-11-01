import sys, subprocess, os
sys.path.insert(0, 'tools')
from analyze_shot import read_bmp, write_png

BIN = 'bin/SpaceCadetPinball.exe'
ENV = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software')


def shoot(kind, prefix, frame, count=1, interval=1):
    out = f'{prefix}.bmp'
    try:
        subprocess.run([BIN, f'-ball={kind}', '-autoplay', f'-screenshot={out}',
                        f'-screenshot-frame={frame}', f'-screenshot-count={count}',
                        f'-screenshot-interval={interval}'],
                       env=ENV, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass
    return sorted(f for f in os.listdir('.') if f.startswith(prefix + '_'))


def diff(a, b):
    w, h, ra = read_bmp(a)
    _, _, rb = read_bmp(b)
    n = 0
    xs = []; ys = []
    for y in range(h):
        row_a, row_b = ra[y], rb[y]
        for x in range(w):
            o = x * 4
            d = abs(row_a[o]-row_b[o]) + abs(row_a[o+1]-row_b[o+1]) + abs(row_a[o+2]-row_b[o+2])
            if d > 20:
                n += 1; xs.append(x); ys.append(y)
    bbox = (min(xs), max(xs), min(ys), max(ys)) if xs else None
    return n, bbox


def crop(src, dst, cx, cy, rad, zoom):
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
    frame = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    print(f'--- frame {frame} ---')
    shots = {}
    for k in range(8):
        fs = shoot(k, f'dt_{k}', frame)
        if fs:
            shots[k] = fs[0]
    base = shots.get(0)
    for k, f in shots.items():
        if k == 0:
            print(f'ball={k}: {f} (reference)')
            continue
        n, bbox = diff(base, f)
        print(f'ball={k}: {f} diff_px={n} bbox={bbox}')
