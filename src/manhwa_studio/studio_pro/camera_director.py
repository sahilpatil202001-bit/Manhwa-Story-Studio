"""
Camera FX & Hybrid Auto-Director.
Provides high-retention Manhwa recap framing:
  - wide_zoom  : Large zoomed-in single panel (~67% of 16:9 width) with emotion-driven
                 screen-shake on impacts, dramatic zoom-in on revelations, zoom-out on
                 aftermath/wide reveals, and smooth focus-aware vertical panning.
  - dual_panel : Side-by-side 2-panel spread (~90% of 16:9 width) pairing the previous
                 context panel with the active speaking panel.
  - hybrid     : Auto-Director combining wide_zoom for action/impact/reveals/hooks and
                 dual_panel for dialogue/reaction sequences.
  - classic    : Legacy full-panel centered framing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneItem
from manhwa_studio.visuals.crop import detect_character_focus, trim_empty_gutters

logger = get_logger("manhwa_studio.pro.camera")

IMPACT_WORDS = [
    "धमाका", "वार", "हमला", "तलवार", "काट", "खून", "strike", "blast",
    "slash", "cut", "छींटे", "तोड़", "मौत", "कत्ल", "क्रोध", "हड्डी", "चीर",
]
REVEAL_WORDS = [
    "रहस्य", "साया", "सच", "अवतार", "शैतान", "राक्षस", "चेओन मा",
    "demon", "secret", "eyes", "खामोशी", "मास्टर", "सिस्टम", "असली", "ताकत",
]
AFTERMATH_WORDS = [
    "खत्म", "शांत", "हार", "गिर", "अंत", "राख", "तबाह", "बर्बाद", "सन्नाटा",
    "over", "silence", "fallen", "destroyed",
]


def detect_artwork_focus(img: Image.Image) -> Tuple[int, int]:
    """
    Manhwa-aware visual focus detector that ignores white speech bubbles and
    empty margins, snapping directly onto colored character faces & action.
    """
    try:
        import cv2

        rgb = np.array(img.convert("RGB"))
        h, w = rgb.shape[:2]

        is_white = (rgb[:, :, 0] > 235) & (rgb[:, :, 1] > 235) & (rgb[:, :, 2] > 235)
        is_black = (rgb[:, :, 0] < 18) & (rgb[:, :, 1] < 18) & (rgb[:, :, 2] < 18)
        content_mask = (~is_white & ~is_black).astype(np.float32)

        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        sat = hsv[:, :, 1].astype(np.float32) / 255.0
        skin = cv2.inRange(hsv, (0, 25, 65), (28, 190, 255)).astype(np.float32) / 255.0

        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 60, 150).astype(np.float32) / 255.0

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
    except Exception as exc:
        logger.debug(f"Artwork focus fallback to character detector: {exc}")

    return detect_character_focus(img)


def prepare_clean_panel(
    src_path: Path,
    cache_dir: Path,
) -> Tuple[Path, Tuple[int, int], Tuple[int, int]]:
    """
    Trim empty white/black webtoon gutters, save a clean RGB JPEG in `cache_dir`,
    and return `(clean_path, (width, height), (focus_x, focus_y))`.
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


class CameraDirector:
    """Computes advanced cinematic motion & Hybrid Auto-Director filters for FFmpeg rendering."""

    def __init__(self, target_width: Optional[int] = None, target_height: Optional[int] = None):
        from manhwa_studio.env_config import get_env_config
        env_cfg = get_env_config()
        self.target_width = target_width if target_width is not None else env_cfg.pro_width
        self.target_height = target_height if target_height is not None else env_cfg.pro_height

    def classify_scene_energy(self, scene: SceneItem) -> str:
        """
        Classify scene emotional energy for Hybrid Auto-Director framing & camera motion:
          - 'impact'    : Combat, shock, strike -> Wide Zoom + screen-shake + punch-in
          - 'reveal'    : Mystery, power-up, ominous reveal -> Wide Zoom + dramatic slow zoom-in
          - 'aftermath' : Silence, defeat, wide aftermath -> Wide Zoom + slow zoom-out
          - 'dialogue'  : Conversation / reaction -> Dual Panel or smooth vertical pan
        """
        text = f"{scene.narration_text or ''} {scene.subtitle_text or ''}".lower()
        purpose = (getattr(scene, "scene_purpose", "") or "").lower()

        if any(w in text for w in IMPACT_WORDS) or purpose in ("climax", "action"):
            return "impact"
        if any(w in text for w in REVEAL_WORDS) or purpose in ("hook", "cliffhanger", "turning_point"):
            return "reveal"
        if any(w in text for w in AFTERMATH_WORDS) or (scene.motion_preset in ("slow_zoom_out", "zoom_out")):
            return "aftermath"
        return "dialogue"

    def select_camera_preset(self, scene: SceneItem, default_preset: str = "pan_up") -> str:
        """
        Dynamically determine if a scene deserves an impact shake, slow zoom-in, or zoom-out
        based on narration/dialogue intensity.
        """
        energy = self.classify_scene_energy(scene)
        if energy == "impact":
            return "impact_shake"
        if energy == "reveal":
            return "slow_zoom"
        if energy == "aftermath":
            return "slow_zoom_out"

        preset = scene.motion_preset or default_preset
        return preset if preset in ["pan_up", "pan_down", "slow_zoom", "slow_zoom_out", "impact_shake"] else "pan_up"

    def _ambient_aura_tint(self, scene: SceneItem, energy: str) -> str:
        from manhwa_studio.env_config import get_env_config
        env_cfg = get_env_config()
        if not env_cfg.enable_ambient_aura:
            return ""

        sp = (scene.speaker or "").lower()
        txt = f"{scene.narration_text or ''} {scene.subtitle_text or ''}".lower()
        if "nano" in sp or "system" in sp or "analysis" in sp or "warning" in sp:
            return ",colorbalance=bs=0.14:gs=0.05"
        if energy == "impact" or any(k in txt for k in ["खून", "मौत", "हमला", "तलवार", "धमाका", "कत्ल", "क्रोध"]):
            return ",colorbalance=rs=0.15:bs=-0.05"
        if "cold" in sp or "lord" in sp or "dragon" in sp:
            return ",colorbalance=rs=0.08:bs=0.12"
        return ""

    @staticmethod
    def _compute_vertical_pan_window(
        scaled_h: int,
        viewport_h: int,
        focus_y_ratio: float,
        duration: float,
        direction: str = "down",
    ) -> Tuple[int, int]:
        """Compute smooth (y_start, y_end) vertical crop window anchored around artwork focus."""
        max_y = max(0, scaled_h - viewport_h)
        if max_y <= 4:
            return 0, 0

        max_travel = min(max_y, max(120, int(duration * 145)))
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
        self,
        scene: SceneItem,
        img_size: Tuple[int, int],
        focus_pt: Tuple[int, int],
        duration: float,
        fps: int = 30,
        viewport_ratio: float = 0.667,
    ) -> str:
        """
        Large zoomed-in single panel (~67% of 16:9 width) with emotion-driven
        screen-shake, zoom-in, zoom-out, or smooth vertical scroll over an ambient backdrop.
        """
        from manhwa_studio.env_config import get_env_config
        env_cfg = get_env_config()

        tw, th = self.target_width, self.target_height
        orig_w, orig_h = img_size
        focus_y_ratio = focus_pt[1] / max(1, orig_h)
        dur = max(0.5, duration)
        energy = self.classify_scene_energy(scene)
        motion_preset = scene.motion_preset or "pan_down"
        aura_tint = self._ambient_aura_tint(scene, energy)
        fade_suffix = ",fade=t=in:st=0:d=0.09" if (env_cfg.enable_scene_microfade and dur >= 1.0) else ""

        # Wide/landscape panels expand naturally; portrait panels fill ~67% width
        aspect = orig_w / max(1, orig_h)
        if aspect >= 1.15:
            vp_w = min(int(tw * 0.92), int(round(th * aspect)))
        else:
            vp_w = int(round(tw * viewport_ratio))
        vp_w = max(360, vp_w - (vp_w % 2))
        vp_h = th

        scale_by_w_h = int(round(orig_h * (vp_w / max(1, orig_w))))
        if scale_by_w_h >= vp_h:
            scaled_w = vp_w
            scaled_h = scale_by_w_h + (scale_by_w_h % 2)
        else:
            scaled_h = vp_h
            scaled_w = int(round(orig_w * (vp_h / max(1, orig_h))))
            scaled_w += scaled_w % 2

        bg_chain = (
            f"[bg_in]scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th},boxblur=28:5,eq=brightness=-0.22:saturation=0.90{aura_tint}[bg];"
        )
        shadow_w = min(tw, vp_w + 36)
        shadow_x = (tw - shadow_w) // 2
        panel_x = (tw - vp_w) // 2
        shadow_chain = f"[bg]drawbox=x={shadow_x}:y=0:w={shadow_w}:h={th}:color=black@0.48:t=fill[bg_sh];"

        if energy == "impact":
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
                f"'0 + 14*cos(36*PI*t)*exp(-3.5*t)':eval=frame,fps={fps}{fade_suffix}"
            )
        elif energy == "reveal" or motion_preset in ("slow_zoom", "slow_zoom_in", "zoom_in"):
            y0, y1 = self._compute_vertical_pan_window(scaled_h, vp_h, focus_y_ratio, dur, direction="down")
            y_mid = (y0 + y1) // 2
            cx = max(0, (scaled_w - vp_w) // 2)
            fg_chain = (
                f"[fg_in]scale={scaled_w}:{scaled_h}:flags=lanczos,"
                f"crop={vp_w}:{vp_h}:{cx}:{y_mid},"
                f"scale='trunc(iw*(1+0.06*t/{dur:.3f})/2)*2':'trunc(ih*(1+0.06*t/{dur:.3f})/2)*2':eval=frame,"
                f"crop={vp_w}:{vp_h}:'(iw-{vp_w})/2':'(ih-{vp_h})/2'[fg];"
            )
            overlay_expr = f"[bg_sh][fg]overlay={panel_x}:0:eval=frame,fps={fps}{fade_suffix}"
        elif energy == "aftermath":
            y0, y1 = self._compute_vertical_pan_window(scaled_h, vp_h, focus_y_ratio, dur, direction="down")
            y_mid = (y0 + y1) // 2
            cx = max(0, (scaled_w - vp_w) // 2)
            fg_chain = (
                f"[fg_in]scale={scaled_w}:{scaled_h}:flags=lanczos,"
                f"crop={vp_w}:{vp_h}:{cx}:{y_mid},"
                f"scale='trunc(iw*(1.06-0.06*t/{dur:.3f})/2)*2':'trunc(ih*(1.06-0.06*t/{dur:.3f})/2)*2':eval=frame,"
                f"crop={vp_w}:{vp_h}:'(iw-{vp_w})/2':'(ih-{vp_h})/2'[fg];"
            )
            overlay_expr = f"[bg_sh][fg]overlay={panel_x}:0:eval=frame,fps={fps}{fade_suffix}"
        else:
            direction = "up" if motion_preset == "pan_up" else "down"
            y0, y1 = self._compute_vertical_pan_window(scaled_h, vp_h, focus_y_ratio, dur, direction=direction)
            cx = max(0, (scaled_w - vp_w) // 2)
            crop_y = f"'{y0}+({y1}-{y0})*t/{dur:.3f}'" if y0 != y1 else "0"
            fg_chain = (
                f"[fg_in]scale={scaled_w}:{scaled_h}:flags=lanczos,"
                f"crop={vp_w}:{vp_h}:{cx}:{crop_y}[fg];"
            )
            overlay_expr = f"[bg_sh][fg]overlay={panel_x}:0:eval=frame,fps={fps}{fade_suffix}"

        return f"split[bg_in][fg_in];{bg_chain}{shadow_chain}{fg_chain}{overlay_expr}"

    def build_dual_panel_filter(
        self,
        scene: SceneItem,
        left_size: Tuple[int, int],
        left_focus: Tuple[int, int],
        right_size: Tuple[int, int],
        right_focus: Tuple[int, int],
        duration: float,
        active_side: str = "right",
        fps: int = 30,
    ) -> str:
        """
        Side-by-side 2-panel spread (~90% of 16:9 width).
        Input [0:v] = left panel, Input [1:v] = right panel. Outputs `[v_out]`.
        """
        from manhwa_studio.env_config import get_env_config
        env_cfg = get_env_config()

        tw, th = self.target_width, self.target_height
        dur = max(0.5, duration)
        energy = self.classify_scene_energy(scene)
        motion_preset = scene.motion_preset or "pan_down"
        aura_tint = self._ambient_aura_tint(scene, energy)
        fade_suffix = ",fade=t=in:st=0:d=0.08" if (env_cfg.enable_scene_microfade and dur >= 1.0) else ""

        # Proportional 2-card geometry (860x980 cards on 1920x1080)
        slot_w = int(round(tw * 0.448))
        slot_w -= slot_w % 2
        slot_h = int(round(th * 0.907))
        slot_h -= slot_h % 2
        margin_x = int(round((tw - slot_w * 2) * 0.325))
        left_x = margin_x
        right_x = tw - margin_x - slot_w
        top_y = (th - slot_h) // 2

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

        if active_side == "right":
            ly0, ly1 = self._compute_vertical_pan_window(lh, slot_h, l_fy, dur, direction="down")
            l_y = (ly0 + ly1) // 2
            ry0, ry1 = self._compute_vertical_pan_window(rh, slot_h, r_fy, dur, direction=direction)
            r_crop_y = f"'{ry0}+({ry1}-{ry0})*t/{dur:.3f}'" if ry0 != ry1 else "0"

            left_chain = (
                f"[0:v]scale={lw}:{lh}:flags=lanczos,crop={slot_w}:{slot_h}:{l_cx}:{l_y},"
                f"eq=brightness=-0.16:saturation=0.72[p_left];"
            )
            right_chain = (
                f"[1:v]split[bg_in][r_in];"
                f"[r_in]scale={rw}:{rh}:flags=lanczos,crop={slot_w}:{slot_h}:{r_cx}:{r_crop_y}[p_right];"
            )
        else:
            ly0, ly1 = self._compute_vertical_pan_window(lh, slot_h, l_fy, dur, direction=direction)
            l_crop_y = f"'{ly0}+({ly1}-{ly0})*t/{dur:.3f}'" if ly0 != ly1 else "0"
            ry0, ry1 = self._compute_vertical_pan_window(rh, slot_h, r_fy, dur, direction="down")
            r_y = (ry0 + ry1) // 2

            left_chain = (
                f"[0:v]split[bg_in][l_in];"
                f"[l_in]scale={lw}:{lh}:flags=lanczos,crop={slot_w}:{slot_h}:{l_cx}:{l_crop_y}[p_left];"
            )
            right_chain = (
                f"[1:v]scale={rw}:{rh}:flags=lanczos,crop={slot_w}:{slot_h}:{r_cx}:{r_y},"
                f"eq=brightness=-0.16:saturation=0.72[p_right];"
            )

        bg_chain = (
            f"[bg_in]scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th},boxblur=28:5,eq=brightness=-0.16{aura_tint}[bg];"
        )
        active_x = right_x if active_side == "right" else left_x
        shadows = (
            f"[bg]drawbox=x={max(0, left_x-8)}:y={max(0, top_y-8)}:w={slot_w+16}:h={slot_h+16}:color=black@0.42:t=fill,"
            f"drawbox=x={max(0, right_x-8)}:y={max(0, top_y-8)}:w={slot_w+16}:h={slot_h+16}:color=black@0.42:t=fill,"
            f"drawbox=x={max(0, active_x-4)}:y={max(0, top_y-4)}:w={slot_w+8}:h={slot_h+8}:color=0x38bdf8@0.92:t=fill[bg_sh];"
        )
        compose = (
            f"[bg_sh][p_left]overlay={left_x}:{top_y}[tmp];"
            f"[tmp][p_right]overlay={right_x}:{top_y}:eval=frame,fps={fps}{fade_suffix}[v_out]"
        )
        return f"{left_chain}{right_chain}{bg_chain}{shadows}{compose}"

    def build_ffmpeg_filter(
        self,
        scene: SceneItem,
        duration: float,
        fps: int = 30,
    ) -> str:
        """
        Legacy classic single-panel FFmpeg video filtergraph (used when STUDIO_PANEL_LAYOUT=classic).
        Guarantees exact target_width x target_height output.
        """
        tw = self.target_width
        th = self.target_height
        dur = max(0.5, duration)
        energy = self.classify_scene_energy(scene)
        preset = self.select_camera_preset(scene, scene.motion_preset or "pan_up")
        slide_offset = max(40, int(th * 0.06))

        from manhwa_studio.env_config import get_env_config
        env_cfg = get_env_config()
        aura_tint = self._ambient_aura_tint(scene, energy)
        fade_suffix = ",fade=t=in:st=0:d=0.10" if (env_cfg.enable_scene_microfade and dur >= 1.2) else ""

        bg_chain = (
            f"[bg_in]scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th},boxblur=25:5,eq=brightness=-0.15{aura_tint}[bg];"
        )
        fg_base = f"[fg_in]scale=w={tw}:h={th}:force_original_aspect_ratio=decrease[fg_base];"

        if preset == "impact_shake":
            return (
                f"split[bg_in][fg_in];"
                f"{bg_chain}"
                f"{fg_base}"
                f"[bg][fg_base]overlay='(W-w)/2 + 20*sin(35*PI*t)*exp(-3.5*t)':'(H-h)/2 + 20*cos(35*PI*t)*exp(-3.5*t)':eval=frame,fps={fps}{fade_suffix}"
            )
        elif preset in ["slow_zoom", "slow_zoom_in", "zoom_in"]:
            return (
                f"split[bg_in][fg_in];"
                f"{bg_chain}"
                f"{fg_base}"
                f"[fg_base]scale='iw*(1+0.045*t/{dur:.3f})':'ih*(1+0.045*t/{dur:.3f})':eval=frame[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2:eval=frame,fps={fps}{fade_suffix}"
            )
        elif preset in ["slow_zoom_out", "zoom_out"]:
            return (
                f"split[bg_in][fg_in];"
                f"{bg_chain}"
                f"{fg_base}"
                f"[fg_base]scale='iw*(1.045-0.045*t/{dur:.3f})':'ih*(1.045-0.045*t/{dur:.3f})':eval=frame[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2:eval=frame,fps={fps}{fade_suffix}"
            )
        elif preset == "pan_down":
            return (
                f"split[bg_in][fg_in];"
                f"{bg_chain}"
                f"{fg_base}"
                f"[bg][fg_base]overlay=(W-w)/2:'(H-h)/2 - {slide_offset}*(1 - 2*t/{dur:.3f})':eval=frame,fps={fps}{fade_suffix}"
            )
        elif preset == "pan_up":
            return (
                f"split[bg_in][fg_in];"
                f"{bg_chain}"
                f"{fg_base}"
                f"[bg][fg_base]overlay=(W-w)/2:'(H-h)/2 + {slide_offset}*(1 - 2*t/{dur:.3f})':eval=frame,fps={fps}{fade_suffix}"
            )
        else:
            return (
                f"split[bg_in][fg_in];"
                f"{bg_chain}"
                f"{fg_base}"
                f"[bg][fg_base]overlay=(W-w)/2:'(H-h)/2 + 25*(1 - 2*t/{dur:.3f})':eval=frame,fps={fps}{fade_suffix}"
            )

    def render_scene_segment(
        self,
        image_path: Path,
        output_path: Path,
        duration: float,
        motion_preset: str = "slow_zoom_in",
        fps: int = 30,
    ) -> Path:
        """Render a single visual video segment from an image (used by ColdOpenDirector)."""
        import subprocess
        from manhwa_studio.env_config import get_env_config
        from manhwa_studio.rendering.ffmpeg import get_video_encoder_args

        clean_preset = "slow_zoom_in" if motion_preset in ["slow_zoom", "zoom_in", "slow_zoom_in"] else motion_preset
        if clean_preset not in ["static", "slow_zoom_in", "slow_zoom_out", "pan_up", "pan_down", "pan_left", "pan_right"]:
            clean_preset = "pan_up"

        mock_scene = SceneItem(
            scene_id="cold_open",
            duration=duration,
            image_file=image_path.name,
            motion_preset=clean_preset,
        )
        env_cfg = get_env_config()
        render_input = image_path
        if env_cfg.panel_layout != "classic":
            clean_p, size, focus = prepare_clean_panel(image_path, output_path.parent / "_clean_panels")
            render_input = clean_p
            vf_filter = self.build_wide_zoom_filter(mock_scene, size, focus, duration, fps=fps)
        else:
            vf_filter = self.build_ffmpeg_filter(mock_scene, duration, fps=fps)

        v_enc_args = get_video_encoder_args(quality=19, cpu_preset="veryfast", nvenc_preset="p4")
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(render_input),
            "-t", f"{duration:.2f}",
            "-vf", vf_filter,
            *v_enc_args,
            "-an",
            str(output_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            tw, th = self.target_width, self.target_height
            fallback_filter = (
                f"split[bg_in][fg_in];"
                f"[bg_in]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},boxblur=25:5,eq=brightness=-0.15[bg];"
                f"[fg_in]scale=w={tw}:h={th}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={fps}"
            )
            fallback_cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
                "-t", f"{duration:.2f}",
                "-vf", fallback_filter,
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", str(output_path),
            ]
            subprocess.run(fallback_cmd, capture_output=True, check=True)

        return output_path
