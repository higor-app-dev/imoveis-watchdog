#!/usr/bin/env python3
"""Generate PWA icons for Imóveis Watchdog."""

from PIL import Image, ImageDraw, ImageFont
import os

def create_icon(size, output_path):
    """Create a simple house+magnifying glass icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Colors
    primary = (37, 99, 235)       # #2563eb blue
    primary_dark = (29, 78, 216)  # #1d4ed8
    white = (255, 255, 255)
    accent = (59, 130, 246)       # #3b82f6

    bg_color = primary

    # Rounded square background
    margin = int(size * 0.04)
    r = int(size * 0.18)
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=r,
        fill=bg_color,
    )

    cx, cy = size // 2, size // 2
    s = size

    # === House shape ===
    h_color = white
    hx = int(s * 0.32)
    hy = int(s * 0.42)
    hw = int(s * 0.36)
    hh = int(s * 0.32)
    roof_h = int(s * 0.14)

    # Roof (triangle)
    draw.polygon(
        [(hx, hy), (hx + hw // 2, hy - roof_h), (hx + hw, hy)],
        fill=h_color,
    )

    # Walls (rectangle)
    draw.rectangle(
        [hx, hy, hx + hw, hy + hh],
        fill=h_color,
    )

    # Door
    dw = int(s * 0.08)
    dh = int(s * 0.14)
    dx = hx + hw // 2 - dw // 2
    dy = hy + hh - dh
    draw.rectangle([dx, dy, dx + dw, dy + dh], fill=bg_color)

    # === Magnifying glass overlay ===
    mg_cx = int(s * 0.62)
    mg_cy = int(s * 0.58)
    mg_r = int(s * 0.11)
    mg_stroke = int(max(1, s * 0.03))

    # Circle
    draw.ellipse(
        [mg_cx - mg_r, mg_cy - mg_r, mg_cx + mg_r, mg_cy + mg_r],
        outline=h_color,
        width=mg_stroke,
    )

    # Handle
    handle_len = int(s * 0.08)
    handle_w = mg_stroke
    import math
    angle = math.radians(45)
    hx1 = mg_cx + int(mg_r * math.cos(angle))
    hy1 = mg_cy + int(mg_r * math.sin(angle))
    hx2 = hx1 + int(handle_len * math.cos(angle))
    hy2 = hy1 + int(handle_len * math.sin(angle))
    draw.line([hx1, hy1, hx2, hy2], fill=h_color, width=handle_w)

    img.save(output_path, "PNG")
    print(f"✓ Created {output_path} ({size}x{size})")


if __name__ == "__main__":
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")
    os.makedirs(output_dir, exist_ok=True)

    create_icon(192, os.path.join(output_dir, "icon-192.png"))
    create_icon(512, os.path.join(output_dir, "icon-512.png"))

    # Also create apple touch icon
    create_icon(180, os.path.join(output_dir, "apple-touch-icon.png"))

    print("Done! All PWA icons generated.")
