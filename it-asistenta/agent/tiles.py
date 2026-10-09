"""Detectarea dalelor modificate și codarea cadrelor binare (vezi PROTOCOL.md).

Format antet (little-endian): [u8 tip][u32 seq][u16 x][u16 y][u16 w][u16 h][u16 screen_w][u16 screen_h]
tip=1 -> JPEG, tip=2 -> PNG.
"""
from __future__ import annotations

import io
import struct
from typing import Iterable, List, Optional, Tuple

from PIL import Image

try:  # numpy accelerează mult comparația; e opțional
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

HEADER = struct.Struct("<BIHHHHHH")
TYPE_JPEG = 1
TYPE_PNG = 2
TILE = 64

Rect = Tuple[int, int, int, int]  # x, y, w, h


def changed_tile_grid(prev: Optional[Image.Image], cur: Image.Image, tile: int = TILE) -> List[List[bool]]:
    """Returnează o matrice [rând][coloană] de bool: dala diferă față de cadrul anterior."""
    w, h = cur.size
    cols = (w + tile - 1) // tile
    rows = (h + tile - 1) // tile
    if prev is None or prev.size != cur.size or prev.mode != cur.mode:
        return [[True] * cols for _ in range(rows)]
    if _np is not None:
        a = _np.asarray(prev)
        b = _np.asarray(cur)
        diff = a != b
        if diff.ndim == 3:
            diff = diff.any(axis=2)
        ph, pw = rows * tile, cols * tile
        if (ph, pw) != diff.shape:
            padded = _np.zeros((ph, pw), dtype=bool)
            padded[:h, :w] = diff
            diff = padded
        grid = diff.reshape(rows, tile, cols, tile).any(axis=(1, 3))
        return grid.tolist()
    # Variantă fără numpy: comparăm octeții brut, rând cu rând, pe fiecare dală.
    bpp = len(cur.getbands())
    ra, rb = prev.tobytes(), cur.tobytes()
    stride = w * bpp
    grid = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        y0, y1 = r * tile, min(h, (r + 1) * tile)
        for c in range(cols):
            x0, x1 = c * tile * bpp, min(w, (c + 1) * tile) * bpp
            for y in range(y0, y1):
                o = y * stride
                if ra[o + x0:o + x1] != rb[o + x0:o + x1]:
                    grid[r][c] = True
                    break
    return grid


def merge_runs(grid: List[List[bool]], width: int, height: int, tile: int = TILE) -> List[Rect]:
    """Unește dalele modificate consecutive de pe fiecare rând în dreptunghiuri."""
    rects: List[Rect] = []
    for r, row in enumerate(grid):
        c = 0
        n = len(row)
        while c < n:
            if not row[c]:
                c += 1
                continue
            start = c
            while c < n and row[c]:
                c += 1
            x = start * tile
            y = r * tile
            w = min(width, c * tile) - x
            h = min(height, (r + 1) * tile) - y
            rects.append((x, y, w, h))
    return rects


def changed_rects(prev: Optional[Image.Image], cur: Image.Image, tile: int = TILE) -> List[Rect]:
    return merge_runs(changed_tile_grid(prev, cur, tile), cur.size[0], cur.size[1], tile)


def pack_header(kind: int, seq: int, x: int, y: int, w: int, h: int, sw: int, sh: int) -> bytes:
    return HEADER.pack(kind, seq & 0xFFFFFFFF, x, y, w, h, sw, sh)


def unpack_header(data: bytes):
    return HEADER.unpack_from(data, 0)


def encode_rects(img: Image.Image, rects: Iterable[Rect], seq: int, quality: int = 60,
                 png: bool = False) -> List[bytes]:
    """Codează fiecare dreptunghi ca mesaj binar (antet + JPEG/PNG)."""
    sw, sh = img.size
    if img.mode != "RGB":
        img = img.convert("RGB")
    out = []
    for (x, y, w, h) in rects:
        crop = img.crop((x, y, x + w, y + h))
        buf = io.BytesIO()
        if png:
            crop.save(buf, format="PNG", compress_level=1)
            kind = TYPE_PNG
        else:
            crop.save(buf, format="JPEG", quality=int(quality))
            kind = TYPE_JPEG
        out.append(pack_header(kind, seq, x, y, w, h, sw, sh) + buf.getvalue())
    return out


def decode_message(data: bytes):
    """Pentru teste/diagnoză: (antet, imagine PIL)."""
    hdr = unpack_header(data)
    img = Image.open(io.BytesIO(data[HEADER.size:]))
    img.load()
    return hdr, img


def apply_messages(canvas: Optional[Image.Image], messages: Iterable[bytes]) -> Image.Image:
    """Desenează mesajele pe un canvas (ca tehnicianul); creează canvas-ul dacă lipsește."""
    for m in messages:
        (kind, seq, x, y, w, h, sw, sh), tile = decode_message(m)
        if canvas is None or canvas.size != (sw, sh):
            canvas = Image.new("RGB", (sw, sh))
        canvas.paste(tile.convert("RGB"), (x, y))
    return canvas


def scale_image(img: Image.Image, scale: float) -> Image.Image:
    if scale >= 0.999:
        return img
    w = max(1, int(round(img.size[0] * scale)))
    h = max(1, int(round(img.size[1] * scale)))
    return img.resize((w, h), Image.BILINEAR)
