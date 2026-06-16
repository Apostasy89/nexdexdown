#!/usr/bin/env python3
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


BRAND = "NexDownSave"
TAGLINE = "Fast. Clean. Reliable."
PRIMARY = (76, 247, 255)
PRIMARY_SOFT = (102, 214, 255)
SECONDARY = (201, 231, 255)
SILVER = (171, 188, 214)
BG_TOP = (8, 12, 20)
BG_BOTTOM = (18, 29, 44)
PANEL = (14, 22, 34, 220)
CARD = (11, 18, 28, 235)
WHITE = (245, 250, 255)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/ubuntu/UbuntuSans[wdth,wght].ttf" if bold else "/usr/share/fonts/truetype/ubuntu/Ubuntu[wdth,wght].ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/lato/Lato-Black.ttf" if bold else "/usr/share/fonts/truetype/lato/Lato-Medium.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill, outline=None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def background(size: tuple[int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, BG_TOP)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(height - 1, 1)
        color = (
            int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t),
            int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t),
            int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t),
            255,
        )
        draw.line((0, y, width, y), fill=color)

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for cx, cy, radius, color in (
        (int(width * 0.18), int(height * 0.22), int(min(size) * 0.22), PRIMARY + (38,)),
        (int(width * 0.82), int(height * 0.16), int(min(size) * 0.18), PRIMARY_SOFT + (30,)),
        (int(width * 0.74), int(height * 0.78), int(min(size) * 0.24), (94, 126, 255, 30)),
    ):
        glow_draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(int(min(size) * 0.04)))
    image.alpha_composite(glow)

    grid = Image.new("RGBA", size, (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid)
    step = max(28, min(size) // 26)
    for x in range(0, width, step):
        grid_draw.line((x, 0, x, height), fill=(90, 122, 160, 30), width=1)
    for y in range(0, height, step):
        grid_draw.line((0, y, width, y), fill=(90, 122, 160, 24), width=1)
    image.alpha_composite(grid)
    return image


def waveform(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], color: tuple[int, int, int], width: int, alpha: int = 255) -> None:
    x1, y1, x2, y2 = box
    mid_y = (y1 + y2) / 2
    points: list[tuple[float, float]] = []
    span = x2 - x1
    amp = (y2 - y1) * 0.34
    for i in range(0, 121):
        t = i / 120
        x = x1 + span * t
        wave = math.sin(t * math.pi * 6) * 0.75 + math.sin(t * math.pi * 13) * 0.25
        y = mid_y + amp * wave * math.sin(t * math.pi)
        points.append((x, y))
    draw.line(points, fill=color + (alpha,), width=width, joint="curve")


def glow_line(base: Image.Image, box: tuple[int, int, int, int], color: tuple[int, int, int], width: int) -> None:
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    waveform(overlay_draw, box, color, width, alpha=230)
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(4, width // 3)))
    base.alpha_composite(overlay)
    draw = ImageDraw.Draw(base)
    waveform(draw, box, color, max(2, width // 2), alpha=255)


def icon(base: Image.Image, center: tuple[int, int], scale: int) -> None:
    cx, cy = center
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    ring_r = int(scale * 0.96)
    overlay_draw.ellipse((cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r), outline=PRIMARY + (85,), width=max(8, scale // 18))
    overlay_draw.ellipse((cx - int(scale * 0.72), cy - int(scale * 0.72), cx + int(scale * 0.72), cy + int(scale * 0.72)), outline=PRIMARY_SOFT + (70,), width=max(5, scale // 28))

    plate = (cx - scale, cy - scale, cx + scale, cy + scale)
    rounded(overlay_draw, plate, radius=int(scale * 0.26), fill=(13, 24, 38, 210), outline=PRIMARY + (150,), width=max(6, scale // 20))

    tray = (cx - int(scale * 0.52), cy + int(scale * 0.28), cx + int(scale * 0.52), cy + int(scale * 0.52))
    rounded(overlay_draw, tray, radius=int(scale * 0.12), fill=(15, 33, 50, 240), outline=SECONDARY + (90,), width=max(5, scale // 22))

    arrow = [
        (cx, cy - int(scale * 0.56)),
        (cx, cy + int(scale * 0.08)),
        (cx - int(scale * 0.24), cy - int(scale * 0.12)),
        (cx, cy + int(scale * 0.26)),
        (cx + int(scale * 0.24), cy - int(scale * 0.12)),
        (cx, cy + int(scale * 0.08)),
    ]
    overlay_draw.line(arrow[:2], fill=PRIMARY + (255,), width=max(12, scale // 12))
    overlay_draw.polygon(arrow[2:], fill=PRIMARY + (255,))

    waveform_box = (cx - int(scale * 0.62), cy - int(scale * 0.18), cx + int(scale * 0.62), cy + int(scale * 0.18))
    waveform(overlay_draw, waveform_box, SECONDARY, max(8, scale // 16), alpha=220)
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(3, scale // 28)))
    base.alpha_composite(overlay)

    draw = ImageDraw.Draw(base)
    rounded(draw, plate, radius=int(scale * 0.26), fill=(13, 24, 38, 186), outline=PRIMARY, width=max(5, scale // 24))
    rounded(draw, tray, radius=int(scale * 0.12), fill=(18, 38, 58, 230), outline=SECONDARY, width=max(4, scale // 26))
    draw.line(((cx, cy - int(scale * 0.56)), (cx, cy + int(scale * 0.14))), fill=PRIMARY, width=max(10, scale // 13))
    draw.polygon(
        [
            (cx - int(scale * 0.22), cy - int(scale * 0.02)),
            (cx + int(scale * 0.22), cy - int(scale * 0.02)),
            (cx, cy + int(scale * 0.28)),
        ],
        fill=PRIMARY,
    )
    waveform(draw, waveform_box, WHITE, max(5, scale // 24), alpha=255)


def title(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int, fill=WHITE) -> None:
    x, y = xy
    font_obj = font(size, bold=True)
    shadow = Image.new("RGBA", (1, 1))
    shadow_draw = ImageDraw.Draw(shadow)
    bbox = shadow_draw.textbbox((0, 0), text, font=font_obj)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    overlay = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.text((20, 20), text, font=font_obj, fill=PRIMARY + (155,))
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(3, size // 18)))
    draw._image.alpha_composite(overlay, (x - 20, y - 20))
    draw.text((x, y), text, font=font_obj, fill=fill)


def label_chip(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill_color: tuple[int, int, int], text_color=WHITE) -> int:
    x, y = xy
    font_obj = font(48, bold=True)
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    width = bbox[2] - bbox[0] + 56
    height = bbox[3] - bbox[1] + 34
    rounded(draw, (x, y, x + width, y + height), radius=height // 2, fill=fill_color + (225,), outline=fill_color + (255,), width=2)
    draw.text((x + 28, y + 16), text, font=font_obj, fill=text_color)
    return width


def panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], heading: str, value: str) -> None:
    rounded(draw, box, radius=34, fill=PANEL, outline=(89, 132, 182, 95), width=2)
    font_head = font(34, bold=False)
    font_value = font(44, bold=True)
    x1, y1, _, _ = box
    draw.text((x1 + 28, y1 + 24), heading, font=font_head, fill=SILVER)
    draw.text((x1 + 28, y1 + 72), value, font=font_value, fill=WHITE)


def save(image: Image.Image, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, format="PNG", optimize=True)


def build_logo(out_dir: Path) -> None:
    image = background((2048, 2048))
    icon(image, (1024, 820), 420)
    draw = ImageDraw.Draw(image)
    title(draw, (462, 1435), BRAND, 180)
    draw.text((650, 1620), "premium telegram utility", font=font(60, bold=False), fill=SILVER)
    glow_line(image, (320, 1760, 1728, 1900), PRIMARY, 16)
    save(image, out_dir / "nexdownsave-logo.png")


def build_banner(out_dir: Path) -> None:
    image = background((3200, 1200))
    draw = ImageDraw.Draw(image)
    glow_line(image, (80, 160, 1350, 420), PRIMARY, 16)
    glow_line(image, (1700, 580, 3100, 910), PRIMARY_SOFT, 14)

    rounded(draw, (1780, 220, 2950, 950), radius=66, fill=CARD, outline=(98, 145, 192, 105), width=3)
    panel(draw, (1860, 320, 2400, 500), "QUEUE", "Smart processing")
    panel(draw, (2440, 320, 2870, 500), "FORMAT", "MP3")
    panel(draw, (1860, 560, 2360, 740), "HISTORY", "Searchable")
    panel(draw, (2400, 560, 2870, 740), "FAVORITES", "Pinned")
    icon(image, (2520, 810), 170)

    title(draw, (180, 430), BRAND, 182)
    draw.text((190, 650), "Premium Telegram music utility bot", font=font(64, bold=False), fill=SECONDARY)
    draw.text((190, 760), "Queue-based processing, direct imports, premium UX.", font=font(42, bold=False), fill=SILVER)
    save(image, out_dir / "github-banner.png")


def build_avatar(out_dir: Path) -> None:
    image = background((1024, 1024))
    mask = Image.new("L", (1024, 1024), 0)
    ImageDraw.Draw(mask).ellipse((24, 24, 1000, 1000), fill=255)
    clipped = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    clipped.paste(image, mask=mask)
    image = clipped
    icon(image, (512, 512), 270)
    save(image, out_dir / "telegram-avatar.png")


def build_splash(out_dir: Path) -> None:
    image = background((2048, 1152))
    draw = ImageDraw.Draw(image)
    rounded(draw, (184, 220, 1864, 928), radius=72, fill=(10, 18, 28, 182), outline=(90, 142, 196, 92), width=3)
    glow_line(image, (250, 300, 1800, 470), PRIMARY, 18)
    glow_line(image, (1050, 610, 1760, 860), PRIMARY_SOFT, 12)
    title(draw, (272, 360), BRAND, 148)
    draw.text((282, 560), TAGLINE, font=font(72, bold=False), fill=SECONDARY)
    draw.text((286, 678), "Direct audio links, imported files, smart queue, clean delivery.", font=font(40, bold=False), fill=SILVER)
    panel(draw, (280, 760, 730, 910), "PIPELINE", "Import -> Verify -> MP3")
    panel(draw, (760, 760, 1110, 910), "UX", "History")
    panel(draw, (1140, 760, 1490, 910), "LIBRARY", "Favorites")
    icon(image, (1660, 578), 220)
    save(image, out_dir / "start-splash.png")


def build_promo(out_dir: Path) -> None:
    image = background((1800, 1800))
    draw = ImageDraw.Draw(image)
    rounded(draw, (140, 120, 1660, 1680), radius=72, fill=CARD, outline=(97, 142, 186, 100), width=3)
    title(draw, (240, 230), BRAND, 132)
    draw.text((248, 390), "Telegram music utility bot", font=font(58, bold=False), fill=SECONDARY)
    chip_x = 244
    chip_y = 520
    for text in ("Queue", "MP3", "History", "Favorites"):
        chip_x += label_chip(draw, (chip_x, chip_y), text, PRIMARY if text in {"Queue", "MP3"} else PRIMARY_SOFT) + 26

    panel(draw, (236, 700, 820, 920), "FLOW", "Predictable queue")
    panel(draw, (880, 700, 1560, 920), "IMPORT", "Audio links and files")
    panel(draw, (236, 980, 760, 1200), "METADATA", "Readable result cards")
    panel(draw, (820, 980, 1560, 1200), "OPS", "Healthcheck and backups")

    rounded(draw, (236, 1288, 1560, 1544), radius=48, fill=(12, 24, 36, 228), outline=PRIMARY + (120,), width=2)
    draw.text((290, 1358), "Built for premium Telegram UX, stable delivery, and clean release branding.", font=font(44, bold=False), fill=WHITE)
    icon(image, (1340, 480), 150)
    save(image, out_dir / "promo-card.png")


def build_social_square(out_dir: Path) -> None:
    image = background((1600, 1600))
    draw = ImageDraw.Draw(image)
    rounded(draw, (120, 120, 1480, 1480), radius=88, fill=CARD, outline=(97, 142, 186, 110), width=3)
    icon(image, (800, 490), 250)
    title(draw, (298, 860), BRAND, 124)
    draw.text((438, 1030), "Telegram music utility bot", font=font(54, bold=False), fill=SECONDARY)
    chip_x = 260
    chip_y = 1148
    for text in ("Queue", "MP3", "History"):
        chip_x += label_chip(draw, (chip_x, chip_y), text, PRIMARY if text != "History" else PRIMARY_SOFT) + 22
    rounded(draw, (246, 1292, 1354, 1420), radius=36, fill=(12, 24, 36, 228), outline=PRIMARY + (100,), width=2)
    draw.text((312, 1336), "Clean branding for social previews and announcements.", font=font(40, bold=False), fill=WHITE)
    save(image, out_dir / "social-square.png")


def build_social_wide(out_dir: Path) -> None:
    image = background((2400, 1260))
    draw = ImageDraw.Draw(image)
    glow_line(image, (120, 160, 1060, 390), PRIMARY, 16)
    rounded(draw, (120, 170, 2280, 1090), radius=74, fill=(9, 16, 26, 188), outline=(90, 142, 196, 88), width=3)
    title(draw, (206, 360), BRAND, 156)
    draw.text((216, 580), "Premium Telegram music utility bot", font=font(62, bold=False), fill=SECONDARY)
    draw.text((218, 684), "Queue-driven import, MP3 conversion, premium chat UX.", font=font(42, bold=False), fill=SILVER)
    panel(draw, (214, 786, 670, 950), "QUEUE", "Reliable flow")
    panel(draw, (708, 786, 1118, 950), "OUTPUT", "MP3")
    panel(draw, (1156, 786, 1688, 950), "LIBRARY", "History + favorites")
    icon(image, (1934, 632), 220)
    save(image, out_dir / "social-wide.png")


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    out_dir = base_dir / "assets" / "brand"
    build_logo(out_dir)
    build_banner(out_dir)
    build_avatar(out_dir)
    build_splash(out_dir)
    build_promo(out_dir)
    build_social_square(out_dir)
    build_social_wide(out_dir)
    print(f"Brand assets generated in: {out_dir}")


if __name__ == "__main__":
    main()
