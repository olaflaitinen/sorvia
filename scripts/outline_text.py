"""Convert display text set in Gamiya Retro into outlined SVG paths.

Gamiya Retro is licensed for personal use only, so the font file is not part of
this repository and is never served to browsers. Display text (the wordmark,
the slogan) is shipped as vector outlines instead, exactly like a logo.

Usage:
    pip install fonttools uharfbuzz
    python scripts/outline_text.py --font /path/GamiyaRetro-Regular.ttf \
        --text "Soruş, aşkara çıxsın." --out web/src/assets/brand/slogan.svg

The output uses fill="currentColor", so it takes the CSS text colour.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont


def _round(match: re.Match[str]) -> str:
    text = f"{float(match.group(0)):.1f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def outline(font_path: Path, text: str, size: float = 100.0, tracking: float = -0.01) -> str:
    font = TTFont(font_path)
    glyphs = font.getGlyphSet()
    order = font.getGlyphOrder()
    upm = font["head"].unitsPerEm
    face = hb.Face(hb.Blob.from_file_path(str(font_path)))
    hb_font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hb_font, buf, {"kern": True, "liga": True})

    scale = size / upm
    x = 0.0
    paths: list[str] = []
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions, strict=True):
        name = order[info.codepoint]
        matrix = (scale, 0, 0, -scale, x + pos.x_offset * scale, -pos.y_offset * scale)
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(TransformPen(pen, matrix))
        bounds = BoundsPen(glyphs)
        glyphs[name].draw(bounds)
        if bounds.bounds:
            bx0, by0, bx1, by1 = bounds.bounds
            x0, x1 = min(x0, matrix[4] + bx0 * scale), max(x1, matrix[4] + bx1 * scale)
            y0, y1 = min(y0, -by1 * scale), max(y1, -by0 * scale)
        if commands := pen.getCommands():
            paths.append(re.sub(r"-?\d+\.\d+", _round, commands))
        x += pos.x_advance * scale + tracking * size
    w, h = x1 - x0, y1 - y0
    body = "".join(f'<path d="{d}"/>' for d in paths)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}" height="{h:.1f}" '
            f'viewBox="{x0:.1f} {y0:.1f} {w:.1f} {h:.1f}" role="img" aria-label="{text}">'
            f'<g fill="currentColor">{body}</g></svg>\n')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--font", type=Path, required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--size", type=float, default=100.0)
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(outline(args.font, args.text, args.size), encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
