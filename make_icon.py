"""Draw the app icon and write icon.icns:  .venv/bin/python make_icon.py"""
import math
import os
import shutil
import subprocess

import Quartz
from Foundation import NSURL

SIZE = 1024


def rgb(hex_color, alpha=1.0):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return Quartz.CGColorCreateGenericRGB(r, g, b, alpha)


def rounded(rect, radius):
    return Quartz.CGPathCreateWithRoundedRect(rect, radius, radius, None)


def radial(ctx, cx, cy, radius, color, alpha):
    space = Quartz.CGColorSpaceCreateDeviceRGB()
    gradient = Quartz.CGGradientCreateWithColors(space, [rgb(color, alpha), rgb(color, 0.0)], [0.0, 1.0])
    Quartz.CGContextDrawRadialGradient(ctx, gradient, (cx, cy), 0, (cx, cy), radius, 0)


def draw():
    space = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(None, SIZE, SIZE, 8, 0, space, Quartz.kCGImageAlphaPremultipliedLast)

    # macOS icon shape: an 824pt rounded square, centred, with a soft drop shadow.
    plate = Quartz.CGRectMake(100, 100, 824, 824)
    shape = rounded(plate, 186)
    Quartz.CGContextSaveGState(ctx)
    Quartz.CGContextSetShadowWithColor(ctx, (0, -12), 28, rgb("#000000", 0.38))
    Quartz.CGContextAddPath(ctx, shape)
    Quartz.CGContextSetFillColorWithColor(ctx, rgb("#0B0B14"))
    Quartz.CGContextFillPath(ctx)
    Quartz.CGContextRestoreGState(ctx)

    Quartz.CGContextSaveGState(ctx)
    Quartz.CGContextAddPath(ctx, shape)
    Quartz.CGContextClip(ctx)

    # Night-sky base, top to bottom.
    base = Quartz.CGGradientCreateWithColors(space, [rgb("#1B1740"), rgb("#0E0D20"), rgb("#07070E")], [0.0, 0.55, 1.0])
    Quartz.CGContextDrawLinearGradient(ctx, base, (0, 924), (0, 100), 0)

    # Aurora spilling out from behind the island.
    island = Quartz.CGRectMake(232, 500, 560, 164)
    cy = Quartz.CGRectGetMidY(island)
    radial(ctx, 330, cy - 30, 430, "#FF4D8D", 0.62)     # pink, left
    radial(ctx, 700, cy - 40, 440, "#4D7CFF", 0.60)     # blue, right
    radial(ctx, 512, cy - 150, 380, "#9B5CFF", 0.50)    # violet, below
    radial(ctx, 512, cy + 40, 250, "#FFFFFF", 0.10)

    # The island: a black capsule with a tight coloured halo and a hairline rim.
    capsule = rounded(island, island.size.height / 2)
    for color, dx in (("#FF5C9A", -18), ("#5C8CFF", 18)):
        Quartz.CGContextSaveGState(ctx)
        Quartz.CGContextSetShadowWithColor(ctx, (dx, -8), 46, rgb(color, 0.95))
        Quartz.CGContextAddPath(ctx, capsule)
        Quartz.CGContextSetFillColorWithColor(ctx, rgb("#000000"))
        Quartz.CGContextFillPath(ctx)
        Quartz.CGContextRestoreGState(ctx)
    Quartz.CGContextAddPath(ctx, capsule)
    Quartz.CGContextSetFillColorWithColor(ctx, rgb("#000000"))
    Quartz.CGContextFillPath(ctx)
    Quartz.CGContextAddPath(ctx, rounded(Quartz.CGRectInset(island, 2, 2), island.size.height / 2 - 2))
    Quartz.CGContextSetStrokeColorWithColor(ctx, rgb("#FFFFFF", 0.16))
    Quartz.CGContextSetLineWidth(ctx, 4)
    Quartz.CGContextStrokePath(ctx)

    # Left: the green "camera in use" dot, glowing.
    dot_x, dot_r = island.origin.x + 92, 24
    Quartz.CGContextSaveGState(ctx)
    Quartz.CGContextSetShadowWithColor(ctx, (0, 0), 30, rgb("#34E36B", 0.95))
    Quartz.CGContextSetFillColorWithColor(ctx, rgb("#34E36B"))
    Quartz.CGContextFillEllipseInRect(ctx, Quartz.CGRectMake(dot_x - dot_r, cy - dot_r, 2 * dot_r, 2 * dot_r))
    Quartz.CGContextRestoreGState(ctx)

    # Right: four audio bars.
    bar_w, gap = 18, 16
    right = island.origin.x + island.size.width - 84
    for i, h in enumerate((44, 84, 60, 30)):
        x = right - (3 - i) * (bar_w + gap) - bar_w
        Quartz.CGContextAddPath(ctx, rounded(Quartz.CGRectMake(x, cy - h / 2, bar_w, h), bar_w / 2))
    Quartz.CGContextSetFillColorWithColor(ctx, rgb("#FF5C9A"))
    Quartz.CGContextFillPath(ctx)

    # Glass highlight along the top edge of the plate.
    shine = Quartz.CGGradientCreateWithColors(space, [rgb("#FFFFFF", 0.14), rgb("#FFFFFF", 0.0)], [0.0, 1.0])
    Quartz.CGContextDrawLinearGradient(ctx, shine, (0, 924), (0, 760), 0)
    Quartz.CGContextRestoreGState(ctx)

    Quartz.CGContextAddPath(ctx, rounded(Quartz.CGRectInset(plate, 1.5, 1.5), 185))
    Quartz.CGContextSetStrokeColorWithColor(ctx, rgb("#FFFFFF", 0.10))
    Quartz.CGContextSetLineWidth(ctx, 3)
    Quartz.CGContextStrokePath(ctx)
    return Quartz.CGBitmapContextCreateImage(ctx)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    master = os.path.join(here, "icon.png")
    dest = Quartz.CGImageDestinationCreateWithURL(NSURL.fileURLWithPath_(master), "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, draw(), None)
    Quartz.CGImageDestinationFinalize(dest)

    iconset = os.path.join(here, "icon.iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    for points in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = "icon_%dx%d%s.png" % (points, points, "@2x" if scale == 2 else "")
            subprocess.run(["sips", "-z", str(points * scale), str(points * scale), master,
                            "--out", os.path.join(iconset, name)], check=True, capture_output=True)
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(here, "icon.icns")], check=True)
    shutil.rmtree(iconset)


if __name__ == "__main__":
    main()
