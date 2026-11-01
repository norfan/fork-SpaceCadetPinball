"""Minimal 32-bit BMP -> PNG converter (no third-party modules).

Only used to eyeball the screenshots the game writes with -screenshot, so it
handles exactly what render::SaveScreenshot produces: a bottom-up 32 bpp BMP.
"""
import struct
import sys
import zlib


def read_bmp(path):
    data = open(path, 'rb').read()
    if data[:2] != b'BM':
        raise SystemExit(f'{path}: not a BMP')
    pixel_offset, = struct.unpack_from('<I', data, 10)
    header_size, = struct.unpack_from('<I', data, 14)
    width, height = struct.unpack_from('<ii', data, 18)
    bpp, = struct.unpack_from('<H', data, 28)
    if bpp not in (24, 32):
        raise SystemExit(f'{path}: unsupported depth {bpp}')
    if header_size < 40:
        raise SystemExit(f'{path}: unsupported header')
    top_down = height < 0
    height = abs(height)

    stride = ((width * bpp // 8) + 3) // 4 * 4
    rows = []
    for y in range(height):
        src_y = y if top_down else height - 1 - y
        row = data[pixel_offset + src_y * stride: pixel_offset + src_y * stride + width * (bpp // 8)]
        if bpp == 24:
            row = b''.join(row[i:i + 3] + b'\xff' for i in range(0, len(row), 3))
        # BMP stores BGRA, PNG wants RGBA
        rows.append(b'\x00' + bytes(row[i + 2 - (0 if i % 4 == 2 else i % 4 * 2) % 4] for i in range(0, 0)) )
    return width, height, stride, data, pixel_offset, top_down, bpp


def convert(src, dst, box=None, scale=1):
    data = open(src, 'rb').read()
    pixel_offset, = struct.unpack_from('<I', data, 10)
    width, height = struct.unpack_from('<ii', data, 18)
    bpp, = struct.unpack_from('<H', data, 28)
    top_down = height < 0
    height = abs(height)
    step = bpp // 8
    stride = (width * step + 3) // 4 * 4

    cx, cy, cw, ch = box if box else (0, 0, width, height)
    raw = bytearray()
    for row in range(ch * scale):
        y = cy + row // scale
        src_y = y if top_down else height - 1 - y
        base = pixel_offset + src_y * stride
        line = bytearray(b'\x00')
        for col in range(cw * scale):
            x = cx + col // scale
            p = base + x * step
            b, g, r = data[p], data[p + 1], data[p + 2]
            a = data[p + 3] if step == 4 else 0xff
            line += bytes((r, g, b, a))
        raw += line

    out_w, out_h = cw * scale, ch * scale

    def chunk(tag, payload):
        return (struct.pack('>I', len(payload)) + tag + payload
                + struct.pack('>I', zlib.crc32(tag + payload) & 0xffffffff))

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', out_w, out_h, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(raw), 6))
           + chunk(b'IEND', b''))
    open(dst, 'wb').write(png)
    print(f'{src} -> {dst} ({out_w}x{out_h} from {cx},{cy} {cw}x{ch} x{scale})')


if __name__ == '__main__':
    args = sys.argv[1:]
    box = None
    scale = 1
    if len(args) >= 6:
        box = tuple(int(v) for v in args[2:6])
        if len(args) >= 7:
            scale = int(args[6])
    convert(args[0], args[1], box, scale)
