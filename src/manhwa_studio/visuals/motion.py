"""
FFmpeg filter graph construction for motion presets, zoom/pan effects, and 9:16 vertical styling.
"""

from __future__ import annotations

from typing import Tuple
from manhwa_studio.schemas import MotionPreset


def build_scene_visual_filter(
    motion: MotionPreset,
    duration: float,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    fill_mode: str = "blur_background",
    zoom_scale: float = 1.15,
) -> str:
    """
    Generate an ultra-fast, zero-memory-leak FFmpeg filter string for smooth
    9:16 vertical character zoom and pan without letterbox borders or buffer bloat.
    """
    dur = max(0.5, duration)
    # Gentle, safe zoom delta (2% to 4% max) to ensure characters, heads, and weapons never leave frame
    z_amount = max(0.02, min(0.04, (zoom_scale - 1.0) if zoom_scale > 1.0 else 0.03))

    if fill_mode == "blur_background":
        # Background: scaled to fill 1080x1920, heavily blurred and dimmed
        bg_filter = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=25:5,eq=brightness=-0.12[bg];"
        )
        # Base foreground: scaled to fit completely within canvas (width<=1080, height<=1920)
        base_fg = f"[0:v]scale=w={width}:h={height}:force_original_aspect_ratio=decrease[fg_base];"

        slide_offset = 120 # Noticeable, smooth vertical webtoon slide in pixels

        if motion == MotionPreset.PAN_UP:
            # Bottom-to-up vertical webtoon slide
            fg_filter = (
                f"{base_fg}"
                f"[fg_base]scale=iw:ih[fg];"
                f"[bg][fg]overlay=(W-w)/2:'(H-h)/2 + {slide_offset}*(1 - 2*t/{dur:.3f})':eval=frame,fps={fps},trim=duration={dur:.3f}[v_out]"
            )
        elif motion == MotionPreset.PAN_DOWN:
            # Top-to-bottom vertical webtoon slide
            fg_filter = (
                f"{base_fg}"
                f"[fg_base]scale=iw:ih[fg];"
                f"[bg][fg]overlay=(W-w)/2:'(H-h)/2 - {slide_offset}*(1 - 2*t/{dur:.3f})':eval=frame,fps={fps},trim=duration={dur:.3f}[v_out]"
            )
        elif motion == MotionPreset.SLOW_ZOOM_IN:
            # Zoom in combined with gentle upward webtoon glide
            fg_filter = (
                f"{base_fg}"
                f"[fg_base]scale='iw*(1+{z_amount:.3f}*t/{dur:.3f})':'ih*(1+{z_amount:.3f}*t/{dur:.3f})':eval=frame[fg];"
                f"[bg][fg]overlay=(W-w)/2:'(H-h)/2 + 60*(1 - 2*t/{dur:.3f})':eval=frame,fps={fps},trim=duration={dur:.3f}[v_out]"
            )
        elif motion == MotionPreset.SLOW_ZOOM_OUT:
            # Zoom out combined with gentle upward webtoon glide
            fg_filter = (
                f"{base_fg}"
                f"[fg_base]scale='iw*(1+{z_amount:.3f}*(1-t/{dur:.3f}))':'ih*(1+{z_amount:.3f}*(1-t/{dur:.3f}))':eval=frame[fg];"
                f"[bg][fg]overlay=(W-w)/2:'(H-h)/2 + 60*(1 - 2*t/{dur:.3f})':eval=frame,fps={fps},trim=duration={dur:.3f}[v_out]"
            )
        else: # STATIC or fallback: smooth vertical flow
            fg_filter = (
                f"{base_fg}"
                f"[fg_base]scale=iw:ih[fg];"
                f"[bg][fg]overlay=(W-w)/2:'(H-h)/2 + 50*(1 - 2*t/{dur:.3f})':eval=frame,fps={fps},trim=duration={dur:.3f}[v_out]"
            )
        return f"{bg_filter}{fg_filter}"

    # Fallback to direct crop if not blur_background
    crop_z = max(0.08, min(0.20, (zoom_scale - 1.0) if zoom_scale > 1.0 else 0.12))
    if motion == MotionPreset.SLOW_ZOOM_IN:
        motion_filter = (
            f"scale='{width}*(1+{crop_z:.3f}*t/{dur:.3f})':"
            f"'{height}*(1+{crop_z:.3f}*t/{dur:.3f})':eval=frame:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    elif motion == MotionPreset.SLOW_ZOOM_OUT:
        motion_filter = (
            f"scale='{width}*(1+{crop_z:.3f}*(1-t/{dur:.3f}))':"
            f"'{height}*(1+{crop_z:.3f}*(1-t/{dur:.3f}))':eval=frame:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    elif motion == MotionPreset.PAN_DOWN:
        pan_h = int(height * 1.15)
        motion_filter = (
            f"scale={width}:{pan_h}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:'(iw-{width})/2':'(ih-{height})*t/{dur:.3f}'"
        )
    elif motion == MotionPreset.PAN_UP:
        pan_h = int(height * 1.15)
        motion_filter = (
            f"scale={width}:{pan_h}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:'(iw-{width})/2':'(ih-{height})*(1-t/{dur:.3f})'"
        )
    else:
        motion_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )

    return f"[0:v]{motion_filter},fps={fps},trim=duration={dur:.3f}[v_out]"

