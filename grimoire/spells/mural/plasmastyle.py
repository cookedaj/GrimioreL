"""Generates a black & white Plasma Style (the look of the taskbar, popups and tooltips).

Plasma draws panels and popups from 9-slice SVGs (topleft, top, …, center + hint-*-margin + mask-* for blur).
We write those for widgets/panel-background, dialogs/background, widgets/tooltip and widgets/background;
everything else falls back to Breeze. Text colors come from a Grimoire color scheme.
"""
import gzip
import json
import shutil
from dataclasses import dataclass

from grimoire.paths import HOME
from grimoire.spells.mural import colors
from grimoire.spells.mural.kde import kread, run_tool

THEMES = HOME / ".local/share/plasma/desktoptheme"


@dataclass(frozen=True)
class Look:
    name: str
    fill: str              # svg color
    fill_opacity: float
    stroke: str
    stroke_opacity: float
    stroke_width: float
    radius: int            # panel corner radius (px)
    popup_radius: int
    light: bool = False    # dark text on a light surface


LOOKS = {   # only Onyx is kept (the one in use); community Plasma styles come from the store
    "onyx":  Look("Onyx", "#0a0a0a", 1.0, "#ffffff", 0.0, 0, 4, 8),
}


def nine_slice(look: Look, radius: int, margin: int) -> str:
    """A 9-slice frame SVG (rounded or square corners, optional hairline border, blur mask, margins)."""
    r = max(2, radius)
    L = 10                                   # length of the edge and center tiles
    size = 2 * r + L
    sw = look.stroke_width if look.stroke_opacity > 0 else 0
    h = sw / 2
    fill = f'fill="{look.fill}" fill-opacity="{look.fill_opacity}"'
    line = f'fill="none" stroke="{look.stroke}" stroke-opacity="{look.stroke_opacity}" stroke-width="{sw}"'
    rounded = radius > 2
    # name, cell origin, arc center, arc start, arc end, square-border polyline (3 points)
    corners = [
        ("topleft", (0, 0), (r, r), (0, r), (r, 0), [(h, r), (h, h), (r, h)]),
        ("topright", (r + L, 0), (r + L, r), (r + L, 0), (size, r), [(r + L, h), (size - h, h), (size - h, r)]),
        ("bottomright", (r + L, r + L), (r + L, r + L), (size, r + L), (r + L, size),
         [(size - h, r + L), (size - h, size - h), (r + L, size - h)]),
        ("bottomleft", (0, r + L), (r, r + L), (r, size), (0, r + L), [(r, size - h), (h, size - h), (h, r + L)]),
    ]
    parts, masks = [], []
    for name, (x, y), (cx, cy), (sx, sy), (ex, ey), square in corners:
        if rounded:
            shape = f'd="M{cx},{cy} L{sx},{sy} A{r},{r} 0 0 1 {ex},{ey} Z"'
            body = f'<path {shape} {fill}/>'
            # border arc, pulled in by half the stroke so it isn't clipped
            ix = lambda px: px + (h if px < cx else -h if px > cx else 0)
            iy = lambda py: py + (h if py < cy else -h if py > cy else 0)
            border = (f'<path d="M{ix(sx)},{iy(sy)} A{r - h},{r - h} 0 0 1 {ix(ex)},{iy(ey)}" {line}/>'
                      if sw else "")
            masks.append(f'<path id="mask-{name}" {shape} fill="#000"/>')
        else:
            body = f'<rect x="{x}" y="{y}" width="{r}" height="{r}" {fill}/>'
            pts = " ".join(f"{px},{py}" for px, py in square)
            border = f'<polyline points="{pts}" {line}/>' if sw else ""
            masks.append(f'<rect id="mask-{name}" x="{x}" y="{y}" width="{r}" height="{r}" fill="#000"/>')
        parts.append(f'<g id="{name}">{body}{border}</g>')

    # edge borders are solid strips (a stroked line breaks into dashes when Plasma repeats the tile)
    strip = f'fill="{look.stroke}" fill-opacity="{look.stroke_opacity}"'
    edges = [("top", r, 0, L, r, (r, 0, L, sw)), ("bottom", r, r + L, L, r, (r, size - sw, L, sw)),
             ("left", 0, r, r, L, (0, r, sw, L)), ("right", r + L, r, r, L, (size - sw, r, sw, L))]
    for name, x, y, w, hh, (bx, by, bw, bh) in edges:
        border = f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" {strip}/>' if sw else ""
        parts.append(f'<g id="{name}"><rect x="{x}" y="{y}" width="{w}" height="{hh}" {fill}/>{border}</g>')
        masks.append(f'<rect id="mask-{name}" x="{x}" y="{y}" width="{w}" height="{hh}" fill="#000"/>')
    parts.append(f'<rect id="center" x="{r}" y="{r}" width="{L}" height="{L}" {fill}/>')
    masks.append(f'<rect id="mask-center" x="{r}" y="{r}" width="{L}" height="{L}" fill="#000"/>')
    # mask-* = the region KWin blurs behind translucent looks; drawn below the frame, same shape
    parts.append(f'<g transform="translate(0,{size + 20})">' + "".join(masks) + "</g>")
    parts.append(f'<rect id="hint-stretch-borders" x="{size + 90}" y="0" width="1" height="1" fill="none"/>')
    for k, (name, w, hh) in enumerate((("hint-top-margin", 1, margin), ("hint-bottom-margin", 1, margin),
                                       ("hint-left-margin", margin, 1), ("hint-right-margin", margin, 1))):
        parts.append(f'<rect id="{name}" x="{size + 10 + k * 20}" y="0" width="{w}" height="{hh}" fill="none"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size + 100}" height="{2 * size + 40}">'
            + "".join(parts) + "</svg>")


def build(look_id: str, ident: str):
    """Write the Plasma Style `ident` for this look into ~/.local/share/plasma/desktoptheme."""
    look = LOOKS[look_id]
    dest = THEMES / ident
    if dest.exists():
        shutil.rmtree(dest)
    panel = nine_slice(look, look.radius, 4)
    popup = nine_slice(look, look.popup_radius, 8)
    tooltip = nine_slice(look, min(look.popup_radius, 8), 6)
    files = {"widgets/panel-background": panel, "widgets/tooltip": tooltip,
             "widgets/background": popup, "dialogs/background": popup}
    for variant in ("", "opaque/", "translucent/"):
        for name, svg in files.items():
            path = dest / variant / f"{name}.svgz"            # Plasma's own themes ship gzipped SVGs
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(svg.encode()))
    scheme = "paper" if look.light else "obsidian"
    (dest / "colors").write_text(colors.scheme_text(scheme, colors.DEFAULTS, "Grimoire", "Grimoire"))
    (dest / "plasmarc").write_text(
        "[ContrastEffect]\nenabled=true\ncontrast=1.0\nintensity=1.0\nsaturation=0\n\n"   # grayscale blur
        "[AdaptiveTransparency]\nenabled=true\n")
    (dest / "metadata.json").write_text(json.dumps({           # same shape as Plasma's own themes
        "KPlugin": {"Id": ident, "Name": f"Grimoire {look.name}", "Description": "Black & white style from Grimoire MuraL",
                    "Authors": [{"Name": "cookedaj"}], "Category": "", "EnabledByDefault": True,
                    "License": "GPL-3.0-or-later", "Version": "1.0", "Website": ""},
        "X-Plasma-API": "5.0",
    }, indent=2))


def current() -> str:
    return kread("plasmarc", "Theme", "name") or "default"


def apply(look_id: str) -> str:
    """Build + apply. Alternates between two ids because re-applying the current theme is a no-op."""
    cur = current()
    ident = "grimoire-b" if cur == "grimoire" else "grimoire"
    build(look_id, ident)
    run_tool(["plasma-apply-desktoptheme", ident])
    other = THEMES / ("grimoire" if ident == "grimoire-b" else "grimoire-b")
    shutil.rmtree(other, ignore_errors=True)
    return cur
