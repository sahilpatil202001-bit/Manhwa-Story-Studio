"""
Generate YouTube Thumbnail for Pick Me Up Infinite Gacha combining artwork from all 15 chapters.
Produces two versions:
1. Clean 15-Chapter Artwork Composite (No text overlays)
2. High-CTR YouTube Thumbnail (With badging, bold typography, and Hindi hook)
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Tuple
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageStat


def score_crop(crop: Image.Image) -> float:
    """Score a cropped region by color saturation, detail, and contrast."""
    hsv = crop.convert("HSV")
    st_hsv = ImageStat.Stat(hsv)
    sat = st_hsv.mean[1]
    val = st_hsv.mean[2]

    # Penalize blank white or plain black margins
    if (val > 220 and sat < 35) or val < 25:
        return -999.0

    gray = crop.convert("L")
    std = ImageStat.Stat(gray).stddev[0]
    # Balance color vibrancy and edge detail
    return (sat * 1.5) + (std * 2.0)


def extract_best_crop_from_chapter(ch_dir: Path, target_w: int = 500, target_h: int = 500) -> Tuple[Image.Image, float, str]:
    """Find the single most dynamic, high-detail action crop in a chapter."""
    strips = sorted(list(ch_dir.glob("*.webp")) + list(ch_dir.glob("*.jpg")))
    best_score = -9999.0
    best_crop = None
    best_source = ""

    for strip in strips:
        try:
            with Image.open(strip) as img:
                w, h = img.size
                if w < 200 or h < 400:
                    continue

                crop_h = int(w * (target_h / target_w))
                step = max(200, crop_h // 2)

                for y in range(0, max(1, h - crop_h), step):
                    box = (0, y, w, y + crop_h)
                    crop = img.crop(box)
                    score = score_crop(crop)
                    if score > best_score:
                        best_score = score
                        best_crop = crop.copy()
                        best_source = f"{strip.name}@{y}"
        except Exception:
            continue

    if best_crop is None:
        # Fallback dummy crop
        best_crop = Image.new("RGB", (target_w, target_h), (25, 25, 35))
        best_source = "fallback"

    return best_crop, best_score, best_source


def enhance_panel(img: Image.Image) -> Image.Image:
    """Enhance colors, contrast, and sharpness for high-impact thumbnail look."""
    img = ImageEnhance.Color(img).enhance(1.25)
    img = ImageEnhance.Contrast(img).enhance(1.20)
    img = ImageEnhance.Sharpness(img).enhance(1.22)
    return img


def draw_text_with_effects(
    draw: ImageDraw.ImageDraw,
    pos: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill_color: Tuple[int, int, int] = (255, 255, 255),
    outline_color: Tuple[int, int, int] = (0, 0, 0),
    outline_width: int = 4,
    shadow_offset: Tuple[int, int] = (4, 4),
    shadow_color: Tuple[int, int, int] = (0, 0, 0),
):
    x, y = pos
    sx, sy = shadow_offset
    # Draw drop shadow
    draw.text((x + sx, y + sy), text, font=font, fill=shadow_color)
    # Draw outline
    for ox in range(-outline_width, outline_width + 1):
        for oy in range(-outline_width, outline_width + 1):
            if ox != 0 or oy != 0:
                draw.text((x + ox, y + oy), text, font=font, fill=outline_color)
    # Draw main text
    draw.text((x, y), text, font=font, fill=fill_color)


def main():
    root = Path("assets/inbox/Pick Me Up Infinite Gacha")
    out_dir_exports = Path("exports/thumbnails")
    out_dir_inbox = root
    out_dir_exports.mkdir(parents=True, exist_ok=True)

    print("Step 1: Extracting best artwork crops from all 15 chapters...")
    chapter_dirs = sorted([p for p in root.iterdir() if p.is_dir() and p.name.startswith("ch")])
    if len(chapter_dirs) < 15:
        print(f"Found {len(chapter_dirs)} chapters in {root}")

    crops: List[Image.Image] = []
    crop_scores: List[Tuple[float, Image.Image, str, int]] = []

    for idx, ch_dir in enumerate(chapter_dirs[:15]):
        ch_num = idx + 1
        crop, score, src = extract_best_crop_from_chapter(ch_dir, target_w=600, target_h=450)
        crops.append(crop)
        crop_scores.append((score, crop, src, ch_num))
        print(f"  • Ch.{ch_num:02d} ({ch_dir.name}): score {score:.1f} from {src}")

    # Top overall hero shot across all 15 chapters
    crop_scores.sort(key=lambda x: x[0], reverse=True)
    hero_score, hero_crop, hero_src, hero_ch = crop_scores[0]
    print(f"\n[Hero Highlight] Ch.{hero_ch} had the highest-rated climax scene (score: {hero_score:.1f})")

    # Step 2: Build 1920x1080 canvas
    # 3 rows x 5 columns = 15 tiles
    canvas_w = 1920
    canvas_h = 1080
    cols = 5
    rows = 3
    tile_w = canvas_w // cols  # 384
    tile_h = canvas_h // rows  # 360

    base_composite = Image.new("RGB", (canvas_w, canvas_h), (10, 10, 15))

    font_badge = None
    try:
        font_badge = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 26)
    except Exception:
        font_badge = ImageFont.load_default()

    print("\nStep 2: Assembling 15-chapter mosaic layout...")
    for idx, crop in enumerate(crops):
        row = idx // cols
        col = idx % cols
        x = col * tile_w
        y = row * tile_h

        # Resize and center-crop to tile dimensions
        # Crop maintains aspect ratio
        cw, ch = crop.size
        target_aspect = tile_w / tile_h
        current_aspect = cw / ch

        if current_aspect > target_aspect:
            # Crop width
            new_w = int(ch * target_aspect)
            left = (cw - new_w) // 2
            crop_square = crop.crop((left, 0, left + new_w, ch))
        else:
            # Crop height
            new_h = int(cw / target_aspect)
            top = (ch - new_h) // 2
            crop_square = crop.crop((0, top, cw, top + new_h))

        tile = crop_square.resize((tile_w, tile_h), Image.Resampling.LANCZOS)
        tile = enhance_panel(tile)

        # Subtle dark border around tile for sleek comic layout
        tile_draw = ImageDraw.Draw(tile)
        tile_draw.rectangle([0, 0, tile_w - 1, tile_h - 1], outline=(15, 20, 30), width=2)

        # Chapter watermark badge on bottom-right of each tile (e.g. "CH 01")
        ch_label = f"CH {idx + 1:02d}"
        tile_draw.rectangle([tile_w - 80, tile_h - 32, tile_w - 4, tile_h - 4], fill=(0, 0, 0, 180))
        tile_draw.text((tile_w - 74, tile_h - 32), ch_label, font=font_badge, fill=(255, 215, 0))

        base_composite.paste(tile, (x, y))

    # Step 3: Add dramatic cinematic centerpiece overlay (Han Yslat Hero Focus)
    print("Step 3: Creating focal hero centerpiece overlay...")
    hero_w = 680
    hero_h = 780
    # Center-crop hero
    hcw, hch = hero_crop.size
    h_aspect = hero_w / hero_h
    if (hcw / hch) > h_aspect:
        nhw = int(hch * h_aspect)
        left = (hcw - nhw) // 2
        hcrop = hero_crop.crop((left, 0, left + nhw, hch))
    else:
        nhh = int(hcw / h_aspect)
        top = (hch - nhh) // 2
        hcrop = hero_crop.crop((0, top, hcw, top + nhh))

    hero_card = hcrop.resize((hero_w, hero_h), Image.Resampling.LANCZOS)
    hero_card = enhance_panel(hero_card)
    # Extra punch for hero
    hero_card = ImageEnhance.Color(hero_card).enhance(1.15)
    hero_card = ImageEnhance.Contrast(hero_card).enhance(1.18)

    # Position hero slightly to the right of center for optimal YouTube typography balance
    hero_x = (canvas_w - hero_w) // 2 + 180
    hero_y = (canvas_h - hero_h) // 2 - 10

    # Draw neon outer glow / drop shadow behind hero card
    shadow_pad = 20
    glow_box = Image.new("RGBA", (hero_w + shadow_pad * 2, hero_h + shadow_pad * 2), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_box)
    glow_draw.rectangle([shadow_pad - 6, shadow_pad - 6, hero_w + shadow_pad + 6, hero_h + shadow_pad + 6], fill=(0, 220, 255, 140))
    glow_box = glow_box.filter(ImageFilter.GaussianBlur(16))
    base_composite.paste(glow_box, (hero_x - shadow_pad, hero_y - shadow_pad), glow_box)

    # Paste hero card with border
    hero_draw = ImageDraw.Draw(hero_card)
    hero_draw.rectangle([0, 0, hero_w - 1, hero_h - 1], outline=(0, 240, 255), width=4)
    hero_draw.rectangle([4, 4, hero_w - 5, hero_h - 5], outline=(255, 215, 0), width=2)
    base_composite.paste(hero_card, (hero_x, hero_y))

    # Add vignette & gradient overlay to base composite
    print("Step 4: Adding atmospheric vignette and depth gradients...")
    vignette = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)

    # Dark bottom gradient (for subtitle/hook legibility)
    for y in range(canvas_h - 320, canvas_h):
        alpha = int(220 * ((y - (canvas_h - 320)) / 320))
        vdraw.line([(0, y), (canvas_w, y)], fill=(0, 0, 0, alpha))

    # Dark left gradient (for titles & badge legibility)
    for x in range(0, 950):
        alpha = int(200 * (1.0 - (x / 950.0)))
        vdraw.line([(x, 0), (x, canvas_h)], fill=(0, 0, 0, alpha))

    # Top-left dark corner for mega badge
    for r in range(250, 0, -5):
        alpha = int(140 * (1.0 - (r / 250.0)))
        vdraw.ellipse([-50, -50, r * 2, r * 2], fill=(0, 0, 0, alpha))

    clean_art = Image.alpha_composite(base_composite.convert("RGBA"), vignette).convert("RGB")

    # SAVE VERSION 1: CLEAN ARTWORK COMPOSITE
    out_clean_1 = out_dir_exports / "pick_me_up_ch1_to_15_clean_art.jpg"
    out_clean_2 = out_dir_inbox / "pick_me_up_ch1_to_15_clean_art.jpg"
    clean_art.save(out_clean_1, "JPEG", quality=95)
    clean_art.save(out_clean_2, "JPEG", quality=95)
    print(f"\n[Saved Clean Art] {out_clean_1}")
    print(f"[Saved Clean Art] {out_clean_2}")

    # Step 5: BUILD VERSION 2: YOUTUBE HIGH-CTR THUMBNAIL
    print("\nStep 5: Applying viral typography, badges, and Hindi teaser...")
    yt_thumb = clean_art.copy()
    draw = ImageDraw.Draw(yt_thumb)

    # Fonts
    font_impact_huge = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 96)
    font_impact_sub = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 64)
    font_badge_bold = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 40)
    font_hook = None
    try:
        font_hook = ImageFont.truetype("C:/Windows/Fonts/Nirmala.ttc", 48)
    except Exception:
        font_hook = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 46)

    # 1. Top-Left Badge: "MEGA MARATHON | CH 1 - 15"
    badge_x, badge_y = 50, 45
    badge_w, badge_h = 580, 68
    # Glow / shadow
    draw.rounded_rectangle([badge_x - 3, badge_y - 3, badge_x + badge_w + 3, badge_y + badge_h + 3], radius=14, fill=(255, 60, 0))
    draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=12, fill=(220, 20, 20))
    # Inner gold border
    draw.rounded_rectangle([badge_x + 3, badge_y + 3, badge_x + badge_w - 3, badge_y + badge_h - 3], radius=10, outline=(255, 220, 0), width=3)
    draw.text((badge_x + 24, badge_y + 10), "MEGA MARATHON • CH 1 - 15", font=font_badge_bold, fill=(255, 255, 255))

    # 2. Main Title Line 1: "PICK ME UP" (Gold Gradient Look with 3D Shadow)
    title_x = 50
    title_y = 150
    draw_text_with_effects(
        draw,
        pos=(title_x, title_y),
        text="PICK ME UP",
        font=font_impact_huge,
        fill_color=(255, 230, 70),
        outline_color=(0, 0, 0),
        outline_width=8,
        shadow_offset=(7, 7),
        shadow_color=(0, 0, 0),
    )

    # 3. Main Title Line 2: "INFINITE GACHA" (Electric Cyan Glow)
    sub_y = title_y + 105
    draw_text_with_effects(
        draw,
        pos=(title_x, sub_y),
        text="INFINITE GACHA",
        font=font_impact_sub,
        fill_color=(0, 240, 255),
        outline_color=(0, 0, 0),
        outline_width=7,
        shadow_offset=(6, 6),
        shadow_color=(0, 0, 0),
    )

    # 4. Feature Highlights Pill Box (Tactical RPG Badge)
    feat_y = sub_y + 90
    draw.rounded_rectangle([title_x, feat_y, title_x + 480, feat_y + 50], radius=8, fill=(10, 25, 45, 210), outline=(0, 200, 255), width=2)
    font_feat = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 26)
    draw.text((title_x + 20, feat_y + 10), "1-STAR HERO • RANK 5 MASTER", font=font_feat, fill=(255, 220, 80))

    # 5. Bottom Hindi Viral Teaser Hook Bar
    hook_bar_y = canvas_h - 130
    draw.rectangle([0, hook_bar_y, canvas_w, canvas_h], fill=(0, 0, 0, 220))
    draw.line([(0, hook_bar_y), (canvas_w, hook_bar_y)], fill=(255, 215, 0), width=4)

    hook_text = "1-STAR HERO... बनेगा दुनिया का सबसे ख़तरनाक मास्टर!"
    draw_text_with_effects(
        draw,
        pos=(50, hook_bar_y + 24),
        text=hook_text,
        font=font_hook,
        fill_color=(255, 255, 255),
        outline_color=(0, 0, 0),
        outline_width=4,
        shadow_offset=(3, 3),
        shadow_color=(0, 0, 0),
    )

    # English punch tag on the right
    font_tag = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 44)
    draw_text_with_effects(
        draw,
        pos=(canvas_w - 440, hook_bar_y + 28),
        text="FULL RECAP (HINDI)",
        font=font_tag,
        fill_color=(255, 220, 0),
        outline_color=(0, 0, 0),
        outline_width=4,
        shadow_offset=(3, 3),
        shadow_color=(0, 0, 0),
    )

    # SAVE VERSION 2: YOUTUBE THUMBNAIL
    out_yt_1 = out_dir_exports / "pick_me_up_ch1_to_15_youtube_thumbnail.jpg"
    out_yt_2 = out_dir_inbox / "pick_me_up_ch1_to_15_youtube_thumbnail.jpg"
    yt_thumb.save(out_yt_1, "JPEG", quality=95)
    yt_thumb.save(out_yt_2, "JPEG", quality=95)
    print(f"[Saved YouTube Thumbnail] {out_yt_1}")
    print(f"[Saved YouTube Thumbnail] {out_yt_2}")
    print("\nAll 15 chapters successfully combined into high-resolution 1920x1080 thumbnails!")


if __name__ == "__main__":
    main()

