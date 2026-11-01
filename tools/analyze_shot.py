import struct, sys, zlib, os

def read_bmp(path):
    with open(path, 'rb') as f:
        data = f.read()
    assert data[:2] == b'BM', 'not bmp'
    pixoff = struct.unpack_from('<I', data, 10)[0]
    hdrsize = struct.unpack_from('<I', data, 14)[0]
    w = struct.unpack_from('<i', data, 18)[0]
    h = struct.unpack_from('<i', data, 22)[0]
    bpp = struct.unpack_from('<H', data, 28)[0]
    flip = h > 0
    h = abs(h)
    assert bpp == 32, bpp
    stride = w * 4
    rows = []
    for y in range(h):
        start = pixoff + y * stride
        row = data[start:start+stride]
        rows.append(row)
    if flip:
        rows.reverse()
    return w, h, rows

def write_png(path, w, h, rows):
    raw = b''.join(b'\x00' + r for r in rows)
    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(raw, 6))
    png += chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)

def px(rows, w, x, y):
    r = rows[y]
    o = x * 4
    return r[o], r[o+1], r[o+2]

if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'diff':
        a = read_bmp(sys.argv[2]); b = read_bmp(sys.argv[3])
        assert a[0] == b[0] and a[1] == b[1]
        w, h = a[0], a[1]
        # accumulate abs diff
        best = []
        for y in range(h):
            ra, rb = a[2][y], b[2][y]
            for x in range(w):
                o = x * 4
                d = abs(ra[o]-rb[o]) + abs(ra[o+1]-rb[o+1]) + abs(ra[o+2]-rb[o+2])
                if d > 30:
                    best.append((x, y, d))
        print('diff pixels:', len(best))
        if best:
            xs = [p[0] for p in best]; ys = [p[1] for p in best]
            print('bbox x:', min(xs), max(xs), 'y:', min(ys), max(ys))
            # cluster by y to see separated blobs
            ys_sorted = sorted(set(ys))
            groups = []
            cur = [ys_sorted[0]]
            for v in ys_sorted[1:]:
                if v - cur[-1] <= 6:
                    cur.append(v)
                else:
                    groups.append((cur[0], cur[-1])); cur=[v]
            groups.append((cur[0], cur[-1]))
            print('y groups:', groups[:20])
    elif mode == 'crop':
        src, dst, cx, cy, rad, zoom = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]), int(sys.argv[7])
        w, h, rows = read_bmp(src)
        x0 = max(0, cx-rad); x1 = min(w, cx+rad+1)
        y0 = max(0, cy-rad); y1 = min(h, cy+rad+1)
        cw, ch = x1-x0, y1-y0
        out = []
        for y in range(ch):
            base = rows[y0+y]
            line = bytearray()
            for x in range(cw):
                o = (x0+x)*4
                p = base[o:o+4]
                line += p * zoom
            for _ in range(zoom):
                out.append(bytes(line))
        write_png(dst, cw*zoom, ch*zoom, out)
        print('wrote', dst, cw*zoom, ch*zoom)
    elif mode == 'full':
        src, dst, scale = sys.argv[2], sys.argv[3], int(sys.argv[4])
        w, h, rows = read_bmp(src)
        out = []
        for y in range(h):
            base = rows[y]
            line = bytearray()
            for x in range(w):
                o = x*4
                line += base[o:o+4] * scale
            for _ in range(scale):
                out.append(bytes(line))
        write_png(dst, w*scale, h*scale, out)
        print('wrote', dst, w*scale, h*scale)
