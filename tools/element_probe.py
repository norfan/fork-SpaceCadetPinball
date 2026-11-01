import sys, subprocess, os
sys.path.insert(0, 'tools')
from analyze_shot import read_bmp, write_png

BIN = 'bin/SpaceCadetPinball.exe'
ENV = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software')

# Element colours from balleffects.cpp (Fire, Ice, Electric, Plasma, Gold)
STYLES = {
    1: ('Fire',     255, 120,  30),
    2: ('Ice',      130, 220, 255),
    3: ('Electric', 175, 130, 255),
    4: ('Plasma',   255,  90, 200),
    7: ('Gold',     255, 210,  90),
}


def shoot(kind, prefix, frame=230, count=3, interval=5):
    out = f'{prefix}.bmp'
    try:
        subprocess.run([BIN, f'-ball={kind}', '-autoplay', f'-screenshot={out}',
                        f'-screenshot-frame={frame}', f'-screenshot-count={count}',
                        f'-screenshot-interval={interval}'],
                       env=ENV, timeout=50, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass
    return sorted(f for f in os.listdir('.') if f.startswith(prefix + '_'))


def count_element(path, er, eg, eb, tol=70):
    """Count pixels that match the element colour closely."""
    w, h, rows = read_bmp(path)
    n = 0
    for y in range(100, h):
        row = rows[y]
        for x in range(w):
            o = x * 4
            r, g, b = row[o], row[o+1], row[o+2]
            if abs(r - er) <= tol and abs(g - eg) <= tol and abs(b - eb) <= tol:
                n += 1
    return n


def crop_best(path, dst, er, eg, eb, rad=60, zoom=3):
    """Crop around the densest cluster of element-coloured pixels."""
    w, h, rows = read_bmp(path)
    hits = []
    for y in range(100, h):
        row = rows[y]
        for x in range(w):
            o = x * 4
            r, g, b = row[o], row[o+1], row[o+2]
            if abs(r - er) <= 70 and abs(g - eg) <= 70 and abs(b - eb) <= 70:
                hits.append((x, y))
    if not hits:
        print('  no element pixels found'); return
    clusters = []
    for p in hits:
        for c in clusters:
            if abs(c[0][0] - p[0]) < 50 and abs(c[0][1] - p[1]) < 50:
                c.append(p); break
        else:
            clusters.append([p])
    clusters.sort(key=len, reverse=True)
    c = clusters[0]
    cx = sum(p[0] for p in c) // len(c)
    cy = sum(p[1] for p in c) // len(c)
    print(f'  cluster at ({cx},{cy}) size={len(c)}')

    x0 = max(0, cx - rad); x1 = min(w, cx + rad + 1)
    y0 = max(0, cy - rad); y1 = min(h, cy + rad + 1)
    out = []
    for y in range(y0, y1):
        base = rows[y]
        line = bytearray()
        for x in range(x0, x1):
            o = x * 4
            line += base[o:o + 4] * zoom
        for _ in range(zoom):
            out.append(bytes(line))
    write_png(dst, (x1 - x0) * zoom, (y1 - y0) * zoom, out)
    print('  wrote', dst)


kind = int(sys.argv[1])
name, er, eg, eb = STYLES[kind]
print(f'=== ball={kind} {name} ({er},{eg},{eb}) ===')
files = shoot(kind, f'el_{kind}')
for f in files:
    print(f'  {f}: element_px={count_element(f, er, eg, eb)}')
if files:
    crop_best(files[0], f'el_ball{kind}.png', er, eg, eb)
