"""Dump the artwork stored inside a Space Cadet .DAT file.

The .DAT is a flat sequence of Pascal style records:
  header (183 bytes) -> [entryCount:u8, entry*] * groupCount
Each entry is [type:u8, payload]. Type 0 and 2 carry a fixed 2 byte payload,
everything else is preceded by a u32 length.

8bpp bitmaps are indexed with a single shared 256 colour palette (BGRA) and
stored bottom-up; 16bpp entries are the matching depth maps. Bitmaps flagged
Spliced (1|4) are RLE-ish blocks of (depth:u16, colour:u8) runs whose stride is
expressed in vScreen pixels, so they need tableWidth to be folded back into
sprite-local offsets.

Usage:
  python dat_export.py list   bin/CADET.DAT
  python dat_export.py export bin/CADET.DAT out_dir [--res 2] [--all]
"""
import argparse
import struct
from pathlib import Path

from PIL import Image, ImageOps

HEADER_SIZE = 183
FIXED_PAYLOAD = {0: 2, 2: 2}
BMP_HEADER_SIZE = 14
TABLE_WIDTH = {0: 600, 1: 752, 2: 960}

BITMAP8, GROUP_NAME, PALETTE, BITMAP16 = 1, 3, 5, 12
FLAG_SPLICED = 1 << 2


def parse(path):
    data = Path(path).read_bytes()
    group_count, = struct.unpack_from("<H", data, 175)
    off = HEADER_SIZE
    bitmaps, palette, names = [], None, {}

    for group_index in range(group_count):
        entry_count = data[off]
        off += 1
        for _ in range(entry_count):
            entry_type = data[off]
            off += 1
            if entry_type in FIXED_PAYLOAD:
                off += FIXED_PAYLOAD[entry_type]
                continue
            size, = struct.unpack_from("<I", data, off)
            off += 4
            payload = off
            if entry_type == GROUP_NAME:
                names[group_index] = data[payload:payload + size].rstrip(b"\0").decode("latin-1")
            elif entry_type == BITMAP8:
                res, w, h, x, y, sz, flags = struct.unpack_from("<BhhhhIb", data, payload)
                bitmaps.append(dict(group=group_index, res=res, w=w, h=h, x=x, y=y,
                                    size=sz, flags=flags, data=payload + BMP_HEADER_SIZE))
            elif entry_type == PALETTE and palette is None:
                palette = data[payload:payload + size]
            off += size

    if off != len(data):
        raise SystemExit(f"parse ended at {off}, file is {len(data)} bytes")
    return data, bitmaps, palette, names


def make_palette(raw):
    # Stored BGRA; PIL wants RGB triplets.
    return [(raw[i * 4 + 2], raw[i * 4 + 1], raw[i * 4]) for i in range(256)]


def decode_plain(data, rec, palette):
    w, h, size = rec["w"], rec["h"], rec["size"]
    stride = ((w + 3) // 4) * 4 if w % 4 else w
    if stride * h != size:
        return None
    img = Image.frombytes("P", (w, h), data[rec["data"]:rec["data"] + size], "raw", "P", stride, 1)
    img.putpalette([c for rgb in palette for c in rgb])
    return ImageOps.flip(img.convert("RGB"))


def decode_spliced(data, rec, palette):
    w, h = rec["w"], rec["h"]
    table_width = TABLE_WIDTH.get(rec["res"], 960)
    raw = data[rec["data"]:rec["data"] + rec["size"]]
    index = bytearray(b"\xff" * (w * h))
    pos = dst = 0
    limit = len(raw)

    while pos + 2 <= limit:
        stride = struct.unpack_from("<h", raw, pos)[0]
        pos += 2
        if stride < 0:
            break
        if stride > w:
            stride += w - table_width
        dst += stride
        if pos + 2 > limit:
            break
        count = struct.unpack_from("<H", raw, pos)[0]
        pos += 2
        if count == 0:
            break
        for _ in range(count):
            if pos + 2 > limit:
                break
            pos += 2  # depth, discarded
            if pos >= limit:
                break
            colour = raw[pos]
            pos += 1
            if 0 <= dst < len(index):
                index[dst] = colour
            dst += 1

    img = Image.frombytes("P", (w, h), bytes(index), "raw", "P", w, 1)
    img.putpalette([c for rgb in palette for c in rgb])
    out = ImageOps.flip(img.convert("RGBA"))
    # 0xff is the "not drawn" marker.
    alpha = Image.frombytes("L", (w, h), bytes(0 if v == 0xff else 255 for v in index), "raw", "L", w, 1)
    out.putalpha(ImageOps.flip(alpha))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["list", "export"])
    ap.add_argument("dat")
    ap.add_argument("out_dir", nargs="?")
    ap.add_argument("--res", type=int, default=2)
    ap.add_argument("--all", action="store_true", help="export every resolution")
    args = ap.parse_args()

    data, bitmaps, palette, names = parse(args.dat)
    print(f"{args.dat}: {len(bitmaps)} bitmaps, {len(names)} named groups, palette={'yes' if palette else 'no'}")

    if args.command == "list":
        for rec in sorted(bitmaps, key=lambda r: -r["w"] * r["h"])[:25]:
            kind = "spliced" if rec["flags"] & FLAG_SPLICED else "plain"
            print(f"  res{rec['res']} {rec['w']:4d}x{rec['h']:<4d} group {rec['group']:3d} "
                  f"{kind:8s} {names.get(rec['group'], '')}")
        return

    if not args.out_dir:
        raise SystemExit("export needs an output directory")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    colours = make_palette(palette)
    written = 0
    for rec in bitmaps:
        if not args.all and rec["res"] != args.res:
            continue
        img = (decode_spliced if rec["flags"] & FLAG_SPLICED else decode_plain)(data, rec, colours)
        if img is None:
            continue
        name = names.get(rec["group"], "").replace("/", "_") or f"g{rec['group']:03d}"
        img.save(out / f"res{rec['res']}_{name}_{rec['w']}x{rec['h']}.png")
        written += 1
    print(f"wrote {written} images to {out}")


if __name__ == "__main__":
    main()
