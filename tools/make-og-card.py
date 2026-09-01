#!/usr/bin/env python3
"""Render og.png — the 1200x630 link-preview card.

The card is the ring mark beside four lines of type on the page ground:

    SIMON DOLERA
    INDEPENDENT RESEARCHER · AI SYSTEMS, EVALUATION & GOVERNANCE
    The verdict, and the boundary around it.
    simondolera.com

Why this file exists: the previous og.png was a flat raster with no source.
When the site copy changed, the card silently kept July's positioning for two
months, because nothing regenerated it. Change COPY below and re-run.

Faces, by ruling — every one loaded BY FILE PATH from this repo's own assets/,
never by family name, so a missing face cannot silently resolve to a fallback.
Each face is proven from its own name table and every glyph the copy needs is
asserted present in the cmap before a single pixel is drawn. A card rendered in
the wrong face looks almost right, which is worse than producing nothing, so
this exits nonzero and writes nothing if any face or glyph is unproven.

  NAME     Archivo SemiBold Expanded   assets/asset-02.woff2
  ROLE     JetBrains Mono (latin)      assets/asset-08.woff2
  TAGLINE  Source Serif 4              assets/asset-14.woff2
  URL      JetBrains Mono (latin)      assets/asset-08.woff2

The mark is rendered from the inline SVG favicon in index.html via
rsvg-convert, so the card and the favicon can never drift apart, and so the
arcs are not hand-ported into PIL primitives.

Geometry is measured from the July card so the rebuild sits where it sat.
Type is matched on cap height, with tracking solved to fit the right edge.
Note the July card was laid out independently of the stylesheet: .role
specifies letter-spacing 0.18em but the rendered line measures ~0. The
measurement wins here, not the CSS.

Renders at 2x (2400x1260) and downscales LANCZOS to 1200x630.

Run from anywhere:  python3 tools/make-og-card.py
"""

import io
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
OUT = ROOT / "og.png"

# ---- copy -----------------------------------------------------------------
NAME = "SIMON DOLERA"
ROLE = "INDEPENDENT RESEARCHER · AI SYSTEMS, EVALUATION & GOVERNANCE"
TAGLINE = "The verdict, and the boundary around it."
URL = "simondolera.com"
SEP = "·"  # drawn in SIGNAL wherever it appears in ROLE

# ---- palette, from index.html's CSS custom properties ----------------------
INK = (4, 4, 4)        # --ink      page ground
PAPER = (248, 244, 240)  # --paper  wordmark
DIM = (168, 161, 153)  # --dim      role line
MID = (232, 226, 218)  # --mid      tagline
SIGNAL = (234, 126, 35)  # --signal url and separator

# ---- geometry, measured from the July card at 1x --------------------------
W, H = 1200, 630
SCALE = 2                 # render at 2x, downscale LANCZOS
LEFT = 345                # shared left margin of all four lines
RIGHT = 1182              # right edge the longest July line reached
MARK_X, MARK_Y, MARK_SIZE = 7, 142, 346

FONTS = {
    "name":    ("assets/asset-02.woff2", "Archivo SemiBold Expanded SemiBold"),
    "role":    ("assets/asset-08.woff2", "JetBrains Mono"),
    "tagline": ("assets/asset-14.woff2", "Source Serif 4"),
    # asset-05 is the greek subset (U+0370-03FF) and has no latin lowercase;
    # asset-08 is the latin subset. Both declare family "JetBrains Mono", so
    # the name table alone cannot tell them apart — the cmap assertion does.
    "url":     ("assets/asset-08.woff2", "JetBrains Mono"),
}

# slot -> (cap height px at 1x, baseline y at 1x, colour)
SLOTS = {
    "name":    (61, 275, PAPER),
    "role":    (17, 345, DIM),
    "tagline": (20, 409, MID),
    "url":     (18, 533, SIGNAL),
}


def die(msg):
    sys.exit(f"HALT: {msg}")


def load_face(rel, expect_family):
    """Load a woff2 from this repo by path. Prove its family from the name
    table. Return (fontTools font, in-memory sfnt buffer)."""
    path = ROOT / rel
    if not path.exists():
        die(f"{rel} not found — face cannot be loaded by path")
    ft = TTFont(str(path))
    family = ft["name"].getDebugName(1) or "?"
    if family != expect_family:
        die(f"{rel} name table says {family!r}, expected {expect_family!r}")
    print(f"  {rel}: name table {family!r} — matches")
    ft.flavor = None                      # woff2 -> plain sfnt in memory
    buf = io.BytesIO()
    ft.save(buf)
    return ft, buf


def assert_glyphs(ft, text, label):
    cmap = ft.getBestCmap()
    missing = sorted({c for c in text if c != " " and ord(c) not in cmap})
    if missing:
        die(f"{label} lacks glyphs for {[hex(ord(c)) for c in missing]} "
            f"— refusing to render with substituted glyphs")
    print(f"  {label}: all {len(set(text))} distinct glyphs present in cmap")


def size_for_cap(ft, cap_px):
    """Point size whose cap height is cap_px, from the face's own OS/2."""
    cap = getattr(ft["OS/2"], "sCapHeight", None)
    if not cap:
        die("face has no sCapHeight — cannot size by cap height")
    return cap_px * ft["head"].unitsPerEm / cap


def tracked_width(draw, text, font, track):
    return sum(draw.textlength(c, font=font) for c in text) + track * (len(text) - 1)


def solve_track(draw, text, font, max_w):
    """Preserve cap height; tighten only if the line would pass the right
    edge. Positive tracking is never invented."""
    natural = tracked_width(draw, text, font, 0)
    if natural <= max_w or len(text) < 2:
        return 0.0, natural
    track = (max_w - natural) / (len(text) - 1)
    return track, max_w


def draw_tracked(draw, x, baseline, text, font, track, fill, sep_fill=None):
    for c in text:
        draw.text((x, baseline), c, font=font,
                  fill=sep_fill if (sep_fill and c == SEP) else fill, anchor="ls")
        x += draw.textlength(c, font=font) + track


def render_mark(px):
    """Render the inline SVG favicon from index.html to a transparent PNG of
    exactly px by px, cropped to its drawn content."""
    if not INDEX.exists():
        die("index.html not found — the mark is defined there")
    m = re.search(r'href="(data:image/svg\+xml,[^"]+)"', INDEX.read_text())
    if not m:
        die("no inline SVG favicon found in index.html")
    svg = urllib.parse.unquote(m.group(1).split(",", 1)[1])
    # drop the opaque ground rect so the content bbox is the mark itself
    stripped, n = re.subn(r"<rect\b[^>]*/>", "", svg, count=1)
    if n != 1:
        die("expected exactly one background <rect> in the favicon SVG")
    if "<text" in stripped:
        die("favicon SVG contains a <text> element — it must stay text-free")

    exe = subprocess.run(["which", "rsvg-convert"], capture_output=True, text=True)
    if exe.returncode != 0:
        die("rsvg-convert not on PATH — install it or the mark cannot render")

    with tempfile.TemporaryDirectory() as tmp:
        s = Path(tmp) / "mark.svg"
        p = Path(tmp) / "mark.png"
        s.write_text(stripped)
        # render generously, then crop to content and scale to the exact size
        big = px * 3
        r = subprocess.run(
            ["rsvg-convert", "-w", str(big), "-h", str(big), "-o", str(p), str(s)],
            capture_output=True, text=True)
        if r.returncode != 0 or not p.exists():
            die(f"rsvg-convert failed: {r.stderr.strip()}")
        img = Image.open(p).convert("RGBA")
        bbox = img.getbbox()
        if not bbox:
            die("rendered mark is empty")
        img = img.crop(bbox)
        if abs(img.width - img.height) > 2:
            die(f"mark is not square after crop: {img.width}x{img.height}")
        return img.resize((px, px), Image.LANCZOS)


def main():
    print("faces:")
    fts, bufs = {}, {}
    for slot, (rel, family) in FONTS.items():
        fts[slot], bufs[slot] = load_face(rel, family)

    print("glyph coverage:")
    for slot, text in (("name", NAME), ("role", ROLE),
                       ("tagline", TAGLINE), ("url", URL)):
        assert_glyphs(fts[slot], text, slot)

    img = Image.new("RGB", (W * SCALE, H * SCALE), INK)
    draw = ImageDraw.Draw(img)

    mark = render_mark(MARK_SIZE * SCALE)
    img.paste(mark, (MARK_X * SCALE, MARK_Y * SCALE), mark)
    print(f"mark: {mark.width}x{mark.height} at "
          f"({MARK_X * SCALE},{MARK_Y * SCALE}) in {SCALE}x space")

    max_w = (RIGHT - LEFT) * SCALE
    print("type:")
    for slot, text in (("name", NAME), ("role", ROLE),
                       ("tagline", TAGLINE), ("url", URL)):
        cap_px, baseline, fill = SLOTS[slot]
        size = size_for_cap(fts[slot], cap_px * SCALE)
        bufs[slot].seek(0)
        font = ImageFont.truetype(bufs[slot], round(size))
        track, width = solve_track(draw, text, font, max_w)
        draw_tracked(draw, LEFT * SCALE, baseline * SCALE, text, font, track,
                     fill, SIGNAL if slot == "role" else None)
        print(f"  {slot:<8} size={size / SCALE:6.2f}px cap={cap_px}px "
              f"baseline={baseline} width={width / SCALE:7.1f}px "
              f"track={track / SCALE:+.3f}px right={(LEFT * SCALE + width) / SCALE:.0f}")

    img = img.resize((W, H), Image.LANCZOS)
    img.save(OUT, optimize=True)
    print(f"wrote {OUT.relative_to(ROOT)}: {img.size[0]}x{img.size[1]}, "
          f"{OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
