import sys, subprocess, os
sys.path.insert(0, 'tools')
from analyze_shot import read_bmp

BIN = 'bin/SpaceCadetPinball.exe'
ENV = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software')

# Element colours from balleffects.cpp
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


def shoot(kind, prefix, frame=200, count=6, interval=6):
    out = f'{prefix}.bmp'
    try:
        subprocess.run([BIN, f'-ball={kind}', '-autoplay', f'-screenshot={out}',
                        f'-screenshot-frame={frame}', f'-screenshot-count={count}',
                        f'-screenshot-interval={interval}'],
                       env=ENV, timeout=70, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass


def hue_hist(path, skip_top=120):
    """Count strongly saturated pixels per hue bucket, ignoring the HUD band."""
    w, h, rows = read_bmp(path)
    buckets = {'red': 0, 'orange': 0, 'yellow': 0, 'green': 0, 'cyan': 0,
               'blue': 0, 'purple': 0, 'magenta': 0, 'white': 0}
    for y in range(skip_top, h):
        row = rows[y]
        for x in range(w):
            o = x * 4
            r, g, b = row[o], row[o+1], row[o+2]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx - mn < 55:
                continue
            if mx == r:
                buckets['magenta' if b > g else 'red'] += 1
                if g > 90 and b < 90: buckets['orange'] += 1
            elif mx == g:
                buckets['yellow' if r > 120 else 'green'] += 1
            else:
                buckets['cyan' if g > 120 else ('purple' if r > 110 else 'blue')] += 1
    return buckets


if __name__ == '__main__':
    kinds = [int(x) for x in sys.argv[1:]] or list(range(8))
    for k in kinds:
        shoot(k, f'hue_{k}')
        files = sorted(f for f in os.listdir('.') if f.startswith(f'hue_{k}_'))
        if not files:
            print(f'{STYLES[k][0]}: no shots'); continue
        agg = {}
        for f in files:
            for b, n in hue_hist(f).items():
                agg[b] = agg.get(b, 0) + n
        top = sorted(agg.items(), key=lambda t: -t[1])[:4]
        print(f'{STYLES[k][0]:9s} (expect {STYLES[k][1]},{STYLES[k][2]},{STYLES[k][3]}): ' +
              ' '.join(f'{b}={n}' for b, n in top))
