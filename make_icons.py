#!/usr/bin/env python3
"""Generate minimal valid PNG icons for the Konnekt PWA."""
import struct, zlib, os

def make_png(size, out_path):
    """Create a solid blue square PNG with a white K."""
    # PNG signature
    sig = b'\x89PNG\r\n\x1a\n'

    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    # IHDR
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)

    # Image data: RGBA rows
    # Background: #3b82f6 (blue), text K: white
    bg = (59, 130, 246)
    fg = (255, 255, 255)

    # Simple K glyph at center (pixel-art style, scaled)
    def draw_k(x, y, sz):
        """Returns set of (px, py) that form a K"""
        pixels = set()
        scale = max(1, sz // 24)
        cx = sz // 2 - scale * 3
        cy = sz // 2 - scale * 5
        # Vertical bar
        for dy in range(10 * scale):
            pixels.add((cx, cy + dy))
            if scale > 1:
                for dx in range(1, scale):
                    pixels.add((cx + dx, cy + dy))
        # Upper diagonal
        for i in range(5 * scale):
            px = cx + scale * 2 + i
            py = cy + i
            for dx in range(scale):
                for dy in range(scale):
                    pixels.add((px + dx, py + dy))
        # Lower diagonal
        for i in range(5 * scale):
            px = cx + scale * 2 + i
            py = cy + 5 * scale + i
            for dx in range(scale):
                for dy in range(scale):
                    pixels.add((px + dx, py + dy))
        return pixels

    k_pixels = draw_k(0, 0, size)

    rows = []
    for y in range(size):
        row = b'\x00'  # filter type None
        for x in range(size):
            if (x, y) in k_pixels:
                row += bytes(fg)
            else:
                row += bytes(bg)
        rows.append(row)

    raw = b''.join(rows)
    compressed = zlib.compress(raw, 9)
    idat = compressed

    png = (sig
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', idat)
        + chunk(b'IEND', b''))

    with open(out_path, 'wb') as f:
        f.write(png)
    print(f"  Created {out_path} ({size}x{size})")

base = os.path.join(os.path.dirname(__file__), 'frontend/public/icons')
os.makedirs(base, exist_ok=True)

for sz in [72, 96, 128, 144, 152, 180, 192, 384, 512]:
    make_png(sz, os.path.join(base, f'icon-{sz}.png'))

print("Done.")
