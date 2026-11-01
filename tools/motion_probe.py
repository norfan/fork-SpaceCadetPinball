import sys, subprocess, os
sys.path.insert(0, 'tools')
from analyze_shot import read_bmp, write_png

BIN = 'bin/SpaceCadetPinball.exe'
ENV = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software')


def shoot(kind, prefix, frame=250, count=2, interval=4):
    out = f'{prefix}.bmp'
    if os.path.exists(out):
        os.remove(out)
    try:
        subprocess.run([BIN, f'-ball={kind}', '-autoplay', f'-screenshot={out}',
                        f'-screenshot-frame={frame}', f'-screenshot-count={count}',
                        f'-screenshot-interval={interval}'],
                       env=ENV, timeout=45, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass  # the game keeps running; the screenshots are already on disk
    return out


def motion_mask(a, b):
    """Pixels that changed between two frames = the ball plus its trail."""
    w, h, ra = read_bmp(a)
    _, _, rb = read_bmp(b)
    mask = bytearray(w * h)
    for y in range(h):
        row_a, row_b, mrow = ra[y], rb[y], y * w
        for x in range(w):
            o = x * 4
            d = abs(row_a[o]-row_b[o]) + abs(row_a[o+1]-row_b[o+1]) + abs(row_a[o+2]-row_b[o+2])
            if d > 18:
                mask[mrow + x] = min(255, d)
    return w, h, mask


def summarize(w, h, mask):
    total = sum(1 for v in mask if v)
    ys = [i // w for i, v in enumerate(mask) if v]
    xs = [i % w for i, v in enumerate(mask) if v]
    if not ys:
        return total, None
    return total, (min(xs), max(xs), min(ys), max(ys))


for kind in range(8):
    p = shoot(kind, f'mv_{kind}')
    files = sorted(f for f in os.listdir('.') if f.startswith(f'mv_{kind}_'))
    if len(files) < 2:
        print(f'ball={kind}: only {files}'); continue
    w, h, mask = motion_mask(files[0], files[1])
    total, bbox = summarize(w, h, mask)
    print(f'ball={kind}: moving_px={total} bbox={bbox}')
    # save mask as png (white on black)
    rows = []
    for y in range(h):
        line = bytearray()
        for x in range(w):
            v = mask[y*w+x]
            line += bytes((v, v, v, 255))
        rows.append(bytes(line))
    write_png(f'mask_{kind}.png', w, h, rows)
