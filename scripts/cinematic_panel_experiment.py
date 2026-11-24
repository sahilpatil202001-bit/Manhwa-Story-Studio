"""
Standalone Cinematic Panel Layout Experiment (Non-Destructive Prototype).

Tests high-retention YouTube Manhwa recap layouts without modifying any
production pipeline files:
  1. wide_zoom  : Large zoomed-in single panel (~66% of 16:9 width) with smooth
                  focus-aware vertical scrolling / Ken Burns zoom (Narro Flip style).
  2. dual_panel : Side-by-side 2-panel spread (~90% of 16:9 width) showing
                  previous context panel + active speaking panel (Manhwa Explained style).
  3. hybrid     : Auto-director combining wide_zoom for action/impact/hook beats
                  and dual_panel for dialogue/reaction sequences.

Usage:
    .\\.venv\\Scripts\\python scripts\\cinematic_panel_experiment.py ^
        --project data/projects/nano_machine/chapter_055 ^
        --style hybrid ^
        --scenes 8
"""

from __future__ import annotationsclear


import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Ensure C:\ffmpeg\bin is discoverable if not already on PATH
if not shutil.which("ffmpeg") and Path(r"C:\ffmpeg\bin\ffmpeg.exe").exists():
    os.environ["PATH"] = r"C:\ffmpeg\bin" + os.pathsep + os.environ.get("PATH", "")

# Allow running directly from repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from manhwa_studio.rendering.ffmpeg import get_ffmpeg_path, get_video_encoder_args, is_nvenc_available
from manhwa_studio.visuals.crop import detect_character_focus, trim_empty_gutters

TARGET_W = 1920
TARGET_H = 1080
FPS = 30

IMPACT_WORDS = [
    "धमाका", "वार", "हमला", "तलवार", "काट", "खून", "strike", "blast",
    "slash", "cut", "छींटे", "तोड़", "मौत", "कत्ल", "क्रोध", "हड्डी",
]
REVEAL_WORDS = [
    "रहस्य", "साया", "सच", "अवतार", "शैतान", "राक्षस", "चेओन मा",
    "demon", "secret", "eyes", "खामोशी", "मास्टर", "सिस्टम",
]


def detect_artwork_focus(img: Image.Image) -> Tuple[int, int]:
    """
    Manhwa-aware visual focus detector that ignores white speech bubbles and
    empty margins, snapping directly onto colored character artwork / faces.
    """
    import cv2

    rgb = np.array(img.convert("RGB"))
    h, w = rgb.shape[:2]

    # Mask out white speech bubbles / white gutters and pure black voids
    is_white = (rgb[:, :, 0] > 235) & (rgb[:, :, 1] > 235) & (rgb[:, :, 2] > 235)
    is_black = (rgb[:, :, 0] < 18) & (rgb[:, :, 1] < 18) & (rgb[:, :, 2] < 18)
    content_mask = (~is_white & ~is_black).astype(np.float32)

    # HSV saturation + skin-tone weight (faces/characters have color & skin tones)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sat = hsv[:, :, 1].astype(np.float32) / 255.0
    skin = cv2.inRange(hsv, (0, 25, 65), (28, 190, 255)).astype(np.float32) / 255.0

    # Edge density (detail in eyes, hair, weapons) masked to non-white artwork
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 60, 150).astype(np.float32) / 255.0

    # Combine into a per-pixel visual importance map
    weight_map = content_mask * (0.45 + 1.4 * sat + 1.8 * skin + 0.8 * edges)

    row_weights = weight_map.mean(axis=1)
    total_w = float(row_weights.sum())
    if total_w > 1e-4:
        ys = np.arange(h, dtype=np.float32)
        fy = int(np.sum(ys * row_weights) / total_w)
        col_weights = weight_map.mean(axis=0)
        xs = np.arange(w, dtype=np.float32)
        fx = int(np.sum(xs * col_weights) / max(1e-4, float(col_weights.sum())))
        return (fx, fy)

    return detect_character_focus(img)


def prepare_clean_panel(src_path: Path, cache_dir: Path) -> Tuple[Path, Tuple[int, int], Tuple[int, int]]:
    """
    Trim empty white/black webtoon gutters, convert to high-quality RGB PNG/JPG,
    and detect the primary character/face focus point (fx, fy).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{src_path.stem}_clean.jpg"

    with Image.open(src_path) as raw:
        if raw.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", raw.size, (12, 12, 16))
            bg.paste(raw, mask=raw.split()[-1])
            img = bg
        else:
            img = raw.convert("RGB")

        img = trim_empty_gutters(img)
        w, h = img.size
        fx, fy = detect_artwork_focus(img)

        if not out_path.exists():
            img.save(out_path, "JPEG", quality=95)

    return out_path, (w, h), (fx, fy)


def classify_scene_energy(scene: Dict) -> str:
    """Return 'impact', 'reveal', or 'dialogue' based on narration text."""
    text = f"{scene.get('narration_text', '')} {scene.get('subtitle_text', '')}".lower()
    if any(w in text for w in IMPACT_WORDS):
        return "impact"
    if any(w in text for w in REVEAL_WORDS):
        return "reveal"
    return "dialogue"


def _compute_vertical_pan_window(
    scaled_h: int,
    viewport_h: int,
    focus_y_ratio: float,
    duration: float,
    direction: str = "down",
) -> Tuple[int, int]:
    """
    Compute smooth (y_start, y_end) vertical crop coordinates inside a scaled tall panel
    so the camera glides smoothly across the focal area without rushing or cutting off heads.
    """
    max_y = max(0, scaled_h - viewport_h)
    if max_y <= 4:
        return 0, 0

    # Comfortable scroll speed (~110-150 px/sec) so details stay readable
    max_travel = min(max_y, max(120, int(duration * 145)))

    # Center travel window around the detected character/face focus point
    focus_center = int(focus_y_ratio * scaled_h) - viewport_h // 2
    focus_center = max(0, min(max_y, focus_center))

    win_top = max(0, focus_center - max_travel // 2)
    win_bottom = win_top + max_travel
    if win_bottom > max_y:
        win_bottom = max_y
        win_top = max(0, win_bottom - max_travel)

    if direction == "up":
        return win_bottom, win_top
    return win_top, win_bottom


def build_wide_zoom_filter(
    img_size: Tuple[int, int],
    focus_pt: Tuple[int, int],
    duration: float,
    energy: str,
    motion_preset: str,
    viewport_w: int = 1280,
) -> str:
    """
    Narro Flip-style large zoomed-in single panel (~67% of 16:9 width)
    with true vertical camera scrolling / smooth zoom over a blurred ambient backdrop.
    """
    orig_w, orig_h = img_size
    _, fy = focus_pt
    focus_y_ratio = fy / max(1, orig_h)
    dur = max(0.5, duration)

    # Adapt viewport width for wider/landscape panels so they look even more cinematic
    aspect = orig_w / max(1, orig_h)
    if aspect >= 1.15:
        vp_w = min(1760, int(round(TARGET_H * aspect)))
        vp_w = vp_w - (vp_w % 2)
    else:
        vp_w = viewport_w - (viewport_w % 2)
    vp_h = TARGET_H

    # Scale foreground to cover the wide viewport (width >= vp_w AND height >= vp_h)
    scale_by_w_h = int(round(orig_h * (vp_w / max(1, orig_w))))
    if scale_by_w_h >= vp_h:
        scaled_w = vp_w
        scaled_h = scale_by_w_h + (scale_by_w_h % 2)
    else:
        scaled_h = vp_h
        scaled_w = int(round(orig_w * (vp_h / max(1, orig_h))))
        scaled_w = scaled_w + (scaled_w % 2)

    bg_chain = (
        f"[bg_in]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},boxblur=28:5,eq=brightness=-0.22:saturation=0.90[bg];"
    )

    # Soft dark drop-shadow matte behind the wide panel
    shadow_w = min(TARGET_W, vp_w + 36)
    shadow_x = (TARGET_W - shadow_w) // 2
    panel_x = (TARGET_W - vp_w) // 2

    if energy == "impact":
        # Center on focus + damped screen shake + slight punch-in zoom
        zoom_w = int(round(scaled_w * 1.08))
        zoom_h = int(round(scaled_h * 1.08))
        zoom_w += zoom_w % 2
        zoom_h += zoom_h % 2
        cx = max(0, (zoom_w - vp_w) // 2)
        cy = max(0, min(zoom_h - vp_h, int(focus_y_ratio * zoom_h) - vp_h // 2))
        fg_chain = (
            f"[fg_in]scale={zoom_w}:{zoom_h}:flags=lanczos,"
            f"crop={vp_w}:{vp_h}:{cx}:{cy}[fg];"
        )
        overlay_expr = (
            f"[bg_sh][fg]overlay='{panel_x} + 18*sin(36*PI*t)*exp(-3.5*t)':"
            f"'0 + 14*cos(36*PI*t)*exp(-3.5*t)':eval=frame,fps={FPS},fade=t=in:st=0:d=0.08"
        )
    elif energy == "reveal" or motion_preset in ("slow_zoom", "slow_zoom_in", "zoom_in"):
        # Smooth +6% cinematic push-in centered on focus
        y_start, y_end = _compute_vertical_pan_window(scaled_h, vp_h, focus_y_ratio, dur, direction="down")
        y_mid = (y_start + y_end) // 2
        cx = max(0, (scaled_w - vp_w) // 2)
        fg_chain = (
            f"[fg_in]scale={scaled_w}:{scaled_h}:flags=lanczos,"
            f"crop={vp_w}:{vp_h}:{cx}:{y_mid},"
            f"scale='trunc(iw*(1+0.06*t/{dur:.3f})/2)*2':'trunc(ih*(1+0.06*t/{dur:.3f})/2)*2':eval=frame,"
            f"crop={vp_w}:{vp_h}:'(iw-{vp_w})/2':'(ih-{vp_h})/2'[fg];"
        )
        overlay_expr = f"[bg_sh][fg]overlay={panel_x}:0:eval=frame,fps={FPS},fade=t=in:st=0:d=0.10"
    else:
        # Smooth vertical camera pan across the tall panel inside the wide 1280x1080 window
        direction = "up" if motion_preset == "pan_up" else "down"
        y_start, y_end = _compute_vertical_pan_window(scaled_h, vp_h, focus_y_ratio, dur, direction=direction)
        cx = max(0, (scaled_w - vp_w) // 2)
        if y_start != y_end:
            crop_y = f"'{y_start}+({y_end}-{y_start})*t/{dur:.3f}'"
        else:
            crop_y = "0"
        fg_chain = (
            f"[fg_in]scale={scaled_w}:{scaled_h}:flags=lanczos,"
            f"crop={vp_w}:{vp_h}:{cx}:{crop_y}[fg];"
        )
        overlay_expr = f"[bg_sh][fg]overlay={panel_x}:0:eval=frame,fps={FPS},fade=t=in:st=0:d=0.10"

    shadow_chain = (
        f"[bg]drawbox=x={shadow_x}:y=0:w={shadow_w}:h={TARGET_H}:color=black@0.48:t=fill[bg_sh];"
    )
    return f"split[bg_in][fg_in];{bg_chain}{shadow_chain}{fg_chain}{overlay_expr}"


def build_dual_panel_filter(
    left_size: Tuple[int, int],
    left_focus: Tuple[int, int],
    right_size: Tuple[int, int],
    right_focus: Tuple[int, int],
    duration: float,
    active_side: str = "right",
    motion_preset: str = "pan_down",
) -> str:
    """
    Manhwa Explained-style 2-panel side-by-side spread (~90% of 16:9 width).
    Input [0:v] = left panel, Input [1:v] = right panel.
    The active speaking panel is bright with smooth Ken Burns motion;
    the companion panel stays slightly calmer for instant viewer eye-focus.
    """
    dur = max(0.5, duration)
    slot_w, slot_h = 860, 980
    left_x, left_y = 65, 50
    right_x, right_y = 995, 50

    def _slot_dims(orig_w: int, orig_h: int) -> Tuple[int, int]:
        sh = int(round(orig_h * (slot_w / max(1, orig_w))))
        if sh >= slot_h:
            sw = slot_w
            sh += sh % 2
        else:
            sh = slot_h
            sw = int(round(orig_w * (slot_h / max(1, orig_h))))
            sw += sw % 2
        return sw, sh

    lw, lh = _slot_dims(*left_size)
    rw, rh = _slot_dims(*right_size)
    l_fy = left_focus[1] / max(1, left_size[1])
    r_fy = right_focus[1] / max(1, right_size[1])

    l_cx = max(0, (lw - slot_w) // 2)
    r_cx = max(0, (rw - slot_w) // 2)

    direction = "up" if motion_preset == "pan_up" else "down"

    # Active panel gets smooth scroll/zoom; companion panel stays calm & slightly dimmed
    if active_side == "right":
        ly0, ly1 = _compute_vertical_pan_window(lh, slot_h, l_fy, dur, direction="down")
        l_y = (ly0 + ly1) // 2
        ry0, ry1 = _compute_vertical_pan_window(rh, slot_h, r_fy, dur, direction=direction)
        r_crop_y = f"'{ry0}+({ry1}-{ry0})*t/{dur:.3f}'" if ry0 != ry1 else "0"

        left_chain = (
            f"[0:v]scale={lw}:{lh}:flags=lanczos,crop={slot_w}:{slot_h}:{l_cx}:{l_y},"
            f"eq=brightness=-0.06:saturation=0.90[p_left];"
        )
        right_chain = (
            f"[1:v]split[bg_in][r_in];"
            f"[r_in]scale={rw}:{rh}:flags=lanczos,crop={slot_w}:{slot_h}:{r_cx}:{r_crop_y}[p_right];"
        )
    else:
        ly0, ly1 = _compute_vertical_pan_window(lh, slot_h, l_fy, dur, direction=direction)
        l_crop_y = f"'{ly0}+({ly1}-{ly0})*t/{dur:.3f}'" if ly0 != ly1 else "0"
        ry0, ry1 = _compute_vertical_pan_window(rh, slot_h, r_fy, dur, direction="down")
        r_y = (ry0 + ry1) // 2

        left_chain = (
            f"[0:v]split[bg_in][l_in];"
            f"[l_in]scale={lw}:{lh}:flags=lanczos,crop={slot_w}:{slot_h}:{l_cx}:{l_crop_y}[p_left];"
        )
        right_chain = (
            f"[1:v]scale={rw}:{rh}:flags=lanczos,crop={slot_w}:{slot_h}:{r_cx}:{r_y},"
            f"eq=brightness=-0.06:saturation=0.90[p_right];"
        )

    bg_chain = (
        f"[bg_in]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},boxblur=28:5,eq=brightness=-0.16[bg];"
    )
    # Soft shadows behind both cards
    shadows = (
        f"[bg]drawbox=x={left_x-8}:y={left_y-8}:w={slot_w+16}:h={slot_h+16}:color=black@0.42:t=fill,"
        f"drawbox=x={right_x-8}:y={right_y-8}:w={slot_w+16}:h={slot_h+16}:color=black@0.42:t=fill[bg_sh];"
    )
    compose = (
        f"[bg_sh][p_left]overlay={left_x}:{left_y}[tmp];"
        f"[tmp][p_right]overlay={right_x}:{right_y}:eval=frame,fps={FPS},fade=t=in:st=0:d=0.08[v_out]"
    )
    return f"{left_chain}{right_chain}{bg_chain}{shadows}{compose}"


def render_comparison_image(
    panel_a_path: Path,
    panel_b_path: Path,
    output_path: Path,
) -> Path:
    """
    Create a 3-panel visual comparison graphic:
      Top    : OLD current pipeline (skinny centered panel, ~28-40% width)
      Middle : NEW Wide Zoom (Narro Flip style, ~67% width)
      Bottom : NEW Dual Panel (Manhwa Explained style, ~90% width)
    """
    def _make_bg(img: Image.Image, brightness: float = 0.78) -> Image.Image:
        ar = TARGET_W / TARGET_H
        iw, ih = img.size
        if iw / ih > ar:
            nh = TARGET_H
            nw = int(iw * nh / ih)
        else:
            nw = TARGET_W
            nh = int(ih * nw / iw)
        bg = img.resize((nw, nh), Image.Resampling.LANCZOS)
        left = (nw - TARGET_W) // 2
        top = (nh - TARGET_H) // 2
        bg = bg.crop((left, top, left + TARGET_W, top + TARGET_H))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=28))
        arr = (np.array(bg, dtype=np.float32) * brightness).clip(0, 255).astype(np.uint8)
        return Image.fromarray(arr)

    def _fit_cover(img: Image.Image, tw: int, th: int, fy_ratio: float) -> Image.Image:
        iw, ih = img.size
        scale = max(tw / iw, th / ih)
        nw, nh = int(round(iw * scale)), int(round(ih * scale))
        resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
        cx = max(0, (nw - tw) // 2)
        cy = max(0, min(nh - th, int(fy_ratio * nh) - th // 2))
        return resized.crop((cx, cy, cx + tw, cy + th))

    img_a = trim_empty_gutters(Image.open(panel_a_path).convert("RGB"))
    img_b = trim_empty_gutters(Image.open(panel_b_path).convert("RGB"))
    _, fy_a = detect_artwork_focus(img_a)
    _, fy_b = detect_artwork_focus(img_b)
    fy_a_r = fy_a / max(1, img_a.size[1])
    fy_b_r = fy_b / max(1, img_b.size[1])

    # 1. OLD frame (force_original_aspect_ratio=decrease)
    old_frame = _make_bg(img_b, 0.85)
    scale_old = min(TARGET_W / img_b.size[0], TARGET_H / img_b.size[1])
    ow, oh = int(img_b.size[0] * scale_old), int(img_b.size[1] * scale_old)
    fg_old = img_b.resize((ow, oh), Image.Resampling.LANCZOS)
    old_frame.paste(fg_old, ((TARGET_W - ow) // 2, (TARGET_H - oh) // 2))

    # 2. NEW Wide Zoom frame (Narro Flip style: 1280px wide)
    wide_frame = _make_bg(img_b, 0.72)
    vp_w = 1280
    fg_wide = _fit_cover(img_b, vp_w, TARGET_H, fy_b_r)
    draw_w = ImageDraw.Draw(wide_frame, "RGBA")
    sx = (TARGET_W - (vp_w + 36)) // 2
    draw_w.rectangle([sx, 0, sx + vp_w + 36, TARGET_H], fill=(0, 0, 0, 125))
    wide_frame.paste(fg_wide, ((TARGET_W - vp_w) // 2, 0))

    # 3. NEW Dual Panel frame (Manhwa Explained style: 2 x 860x980)
    dual_frame = _make_bg(img_b, 0.80)
    slot_w, slot_h = 860, 980
    card_l = _fit_cover(img_a, slot_w, slot_h, fy_a_r)
    card_r = _fit_cover(img_b, slot_w, slot_h, fy_b_r)
    # Slight calm dim on left companion card
    card_l = Image.fromarray((np.array(card_l, dtype=np.float32) * 0.90).clip(0, 255).astype(np.uint8))
    draw_d = ImageDraw.Draw(dual_frame, "RGBA")
    draw_d.rectangle([57, 42, 65 + slot_w + 8, 50 + slot_h + 8], fill=(0, 0, 0, 110))
    draw_d.rectangle([987, 42, 995 + slot_w + 8, 50 + slot_h + 8], fill=(0, 0, 0, 110))
    dual_frame.paste(card_l, (65, 50))
    dual_frame.paste(card_r, (995, 50))

    # Stack all 3 scaled down to 960x540 each with clear header banners
    thumb_w, thumb_h = 960, 540
    banner_h = 46
    canvas = Image.new("RGB", (thumb_w, (thumb_h + banner_h) * 3), (18, 18, 24))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arialbd.ttf", 24)
    except Exception:
        font = ImageFont.load_default()

    rows = [
        (f"1. CURRENT PIPELINE  (Panel width: {ow}px / 1920px = {int(ow*100/TARGET_W)}% screen)", old_frame, (220, 90, 90)),
        ("2. NEW WIDE ZOOM — Narro Flip Style  (1280px / 1920px = 67% screen + smooth pan)", wide_frame, (90, 200, 255)),
        ("3. NEW DUAL PANEL — Manhwa Explained Style  (2x860px = 90% screen)", dual_frame, (110, 235, 140)),
    ]
    for i, (label, frame, color) in enumerate(rows):
        y0 = i * (thumb_h + banner_h)
        draw.rectangle([0, y0, thumb_w, y0 + banner_h], fill=(24, 24, 34))
        draw.text((18, y0 + 10), label, fill=color, font=font)
        canvas.paste(frame.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS), (0, y0 + banner_h))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "JPEG", quality=92)
    return output_path


def run_experiment(
    project_dir: Path,
    style: str = "hybrid",
    max_scenes: int = 8,
    output_dir: Optional[Path] = None,
) -> Dict[str, Path]:
    manifest_path = project_dir / "scripts" / "scene_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"scene_manifest.json not found in {project_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])[:max_scenes]
    artwork_dir = project_dir / "artwork"

    out_root = output_dir or (REPO_ROOT / "exports" / "experiments" / f"{project_dir.parent.name}_{project_dir.name}")
    out_root.mkdir(parents=True, exist_ok=True)
    cache_dir = out_root / "_clean_panels"
    seg_dir = out_root / f"_segments_{style}"
    seg_dir.mkdir(parents=True, exist_ok=True)

    v_enc_args = get_video_encoder_args(quality=19, cpu_preset="veryfast", nvenc_preset="p4")
    enc_label = "GPU (h264_nvenc)" if is_nvenc_available() else "CPU (libx264)"
    print(f"[Experiment] Style={style} | Scenes={len(scenes)} | Encoder={enc_label}")

    # Pre-clean panels and gather metadata
    prepared: List[Tuple[Dict, Path, Tuple[int, int], Tuple[int, int]]] = []
    for s in scenes:
        img_p = artwork_dir / s["image_file"]
        if not img_p.exists():
            continue
        clean_p, size, focus = prepare_clean_panel(img_p, cache_dir)
        prepared.append((s, clean_p, size, focus))

    if not prepared:
        raise RuntimeError("No valid scenes found to render.")

    # Save visual comparison preview using first two distinct panels
    panel_a = prepared[0][1]
    panel_b = prepared[1][1] if len(prepared) > 1 else prepared[0][1]
    comparison_img = render_comparison_image(panel_a, panel_b, out_root / "comparison_preview.jpg")
    print(f"[Experiment] Saved comparison preview: {comparison_img}")

    video_segments: List[Path] = []
    audio_segments: List[Path] = []

    for idx, (scene, clean_p, size, focus) in enumerate(prepared):
        dur = float(scene.get("actual_audio_duration") or scene.get("duration") or 3.5)
        energy = classify_scene_energy(scene)
        motion = scene.get("motion_preset") or "pan_down"
        seg_out = seg_dir / f"seg_{idx:03d}_{scene['scene_id']}.mp4"

        # Decide layout for this scene
        use_dual = False
        if style == "dual_panel" and idx > 0:
            use_dual = True
        elif style == "hybrid" and idx > 0:
            aspect = size[0] / max(1, size[1])
            # Use dual_panel for dialogue portrait beats; wide_zoom for impact/reveal/landscape/hook
            if energy == "dialogue" and aspect < 0.95 and (idx % 3 != 0):
                use_dual = True

        if use_dual:
            prev_scene, prev_p, prev_size, prev_focus = prepared[idx - 1]
            # Alternate active side on consecutive dual panels for natural manga flow
            active_side = "right" if (idx % 2 == 1) else "left"
            if active_side == "right":
                left_p, left_sz, left_fc = prev_p, prev_size, prev_focus
                right_p, right_sz, right_fc = clean_p, size, focus
            else:
                left_p, left_sz, left_fc = clean_p, size, focus
                right_p, right_sz, right_fc = prev_p, prev_size, prev_focus

            fc_graph = build_dual_panel_filter(
                left_sz, left_fc, right_sz, right_fc, dur,
                active_side=active_side, motion_preset=motion,
            )
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(left_p),
                "-loop", "1", "-i", str(right_p),
                "-t", f"{dur:.3f}",
                "-filter_complex", fc_graph,
                "-map", "[v_out]",
                *v_enc_args,
                "-an",
                str(seg_out),
            ]
            layout_tag = f"DUAL({active_side})"
        else:
            vf = build_wide_zoom_filter(size, focus, dur, energy=energy, motion_preset=motion)
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(clean_p),
                "-t", f"{dur:.3f}",
                "-vf", vf,
                *v_enc_args,
                "-an",
                str(seg_out),
            ]
            layout_tag = f"WIDE({energy})"

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"  [WARN] GPU/filter failed on {seg_out.name}, retrying libx264: {res.stderr[-220:]}")
            cpu_cmd = [a for a in cmd if a not in ("h264_nvenc", "p4", "-cq", "19", "-rc", "vbr")]
            # Clean fallback with libx264
            if use_dual:
                fallback_cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-i", str(left_p),
                    "-loop", "1", "-i", str(right_p),
                    "-t", f"{dur:.3f}",
                    "-filter_complex", fc_graph,
                    "-map", "[v_out]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                    "-an", str(seg_out),
                ]
            else:
                fallback_cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-i", str(clean_p),
                    "-t", f"{dur:.3f}",
                    "-vf", vf,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                    "-an", str(seg_out),
                ]
            subprocess.run(fallback_cmd, capture_output=True, check=True)

        print(f"  [{idx+1}/{len(prepared)}] {scene['scene_id']} ({dur:.2f}s) -> {layout_tag}")
        video_segments.append(seg_out)

        audio_p = Path(scene.get("actual_audio_path") or "")
        if not audio_p.exists():
            audio_p = project_dir / "audio" / f"{scene['scene_id']}.mp3"
        if audio_p.exists():
            audio_segments.append(audio_p)

    # Concatenate video segments
    v_concat = seg_dir / "v_concat.txt"
    v_concat.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in video_segments), encoding="utf-8")
    raw_video = seg_dir / "raw_video.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(v_concat), "-c", "copy", str(raw_video)],
        capture_output=True, check=True,
    )

    final_video = out_root / f"demo_{style}.mp4"

    # Concatenate matching scene audio if available
    if len(audio_segments) == len(video_segments):
        a_concat = seg_dir / "a_concat.txt"
        a_concat.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in audio_segments), encoding="utf-8")
        merged_audio = seg_dir / "merged_audio.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(a_concat), "-c:a", "libmp3lame", "-b:a", "192k", str(merged_audio)],
            capture_output=True, check=True,
        )
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(raw_video),
                "-i", str(merged_audio),
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                str(final_video),
            ],
            capture_output=True, check=True,
        )
    else:
        raw_video.replace(final_video)

    print(f"[Experiment] DONE! Output video: {final_video}")
    return {"video": final_video, "comparison": comparison_img}


def main() -> None:
    parser = argparse.ArgumentParser(description="Test high-retention wide-zoom & dual-panel manhwa layouts.")
    parser.add_argument("--project", type=Path, required=True, help="Path to chapter project dir (e.g. data/projects/nano_machine/chapter_055)")
    parser.add_argument("--style", choices=["wide_zoom", "dual_panel", "hybrid"], default="hybrid", help="Visual layout style to render")
    parser.add_argument("--scenes", type=int, default=8, help="Number of scenes to render for quick preview (default: 8)")
    parser.add_argument("--output-dir", type=Path, default=None, help="Optional custom output directory")
    args = parser.parse_args()

    run_experiment(args.project, style=args.style, max_scenes=args.scenes, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
