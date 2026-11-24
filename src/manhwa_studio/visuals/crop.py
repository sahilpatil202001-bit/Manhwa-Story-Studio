"""
Image cropping utilities using normalized coordinates to handle tall manhwa panels.
"""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageChops

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import NormalizedCrop

logger = get_logger("manhwa_studio.visuals.crop")


def trim_empty_gutters(img: Image.Image) -> Image.Image:
    """
    Automatically detect and trim empty white or black webtoon scroll gutters
    from the top and bottom of an image so only real artwork remains.
    """
    import numpy as np

    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]

    # Row is blank if mean is near 255 (white) or near 0 (black) and variance is near 0
    row_means = np.mean(arr, axis=(1, 2))
    row_stds = np.std(arr, axis=(1, 2))

    is_blank = ((row_means > 250) | (row_means < 15)) & (row_stds < 12)
    non_blank = np.where(~is_blank)[0]

    if len(non_blank) == 0:
        return img

    top = int(non_blank[0])
    bottom = int(non_blank[-1]) + 1

    # Only trim if we keep at least 35% of the height
    if (bottom - top) >= int(h * 0.35) and (top > 0 or bottom < h):
        return img.crop((0, top, w, bottom))
    return img


def detect_character_focus(img: Image.Image) -> tuple[int, int]:
    """
    Detect character face or primary visual focus point using OpenCV face cascade
    with skin-tone and visual density fallback.
    """
    w, h = img.size
    try:
        import cv2
        import numpy as np

        rgb = np.array(img.convert("RGB"))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)

        if len(faces) > 0:
            best_face = max(faces, key=lambda f: f[2] * f[3])
            fx, fy, fw, fh = best_face
            return (fx + fw // 2, fy + fh // 2)

        # Fallback to skin tone / character contour
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        skin_mask = cv2.inRange(hsv, (0, 30, 60), (25, 200, 255))
        if np.count_nonzero(skin_mask) > 100:
            y_idxs, x_idxs = np.nonzero(skin_mask)
            return (int(np.median(x_idxs)), int(np.median(y_idxs)))
    except Exception as e:
        logger.debug(f"Focus detection fallback to center: {e}")

    return (w // 2, h // 2)


def smart_frame_character(img: Image.Image, target_aspect: float = 9 / 16) -> Image.Image:
    """
    Preserve 100% of the manhwa panel artwork while trimming exterior blank gutters.
    No destructive interior cropping, bubble slicing, or character cutoff.
    Full panel display and 9:16 vertical framing are handled cleanly by motion.py with blur_background.
    """
    return trim_empty_gutters(img)



def apply_normalized_crop(
    input_image_path: Path,
    crop: Optional[NormalizedCrop],
    output_image_path: Path,
) -> Path:
    """
    Apply smart framing and optional normalized crop to an artwork image.
    """
    output_image_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(input_image_path) as img:
        # Handle RGBA/LA modes
        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (15, 15, 18))
            bg.paste(img, mask=img.split()[-1])
            base_img = bg
        else:
            base_img = img.convert("RGB")

        w, h = base_img.size

        if crop and (crop.x > 0 or crop.y > 0 or crop.width < 1.0 or crop.height < 1.0):
            left = max(0, int(crop.x * w))
            top = max(0, int(crop.y * h))
            right = min(w, int((crop.x + crop.width) * w))
            bottom = min(h, int((crop.y + crop.height) * h))

            if right > left and bottom > top:
                base_img = base_img.crop((left, top, right, bottom))

        # Always apply smart framing to eliminate empty gutters & speech bubbles
        framed = smart_frame_character(base_img)
        framed.save(output_image_path, "JPEG", quality=95)

    return output_image_path

