"""
Image manifest, contact sheet generator, and HTML review report builder.
"""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image, ImageDraw, ImageFont

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import AssetMetadata, RightsStatus

logger = get_logger("manhwa_studio.ingestion.manifest")


def generate_contact_sheet(
    image_paths: List[Path],
    output_path: Path,
    thumb_width: int = 240,
    thumb_height: int = 360,
    columns: int = 4,
) -> Path:
    """
    Generate a thumbnail contact sheet image summarizing all input panels.
    """
    if not image_paths:
        raise ValueError("Cannot create contact sheet: image_paths list is empty.")

    count = len(image_paths)
    rows = math.ceil(count / columns)
    label_height = 30
    cell_w = thumb_width + 10
    cell_h = thumb_height + label_height + 10

    sheet_w = columns * cell_w + 10
    sheet_h = rows * cell_h + 10

    sheet = Image.new("RGB", (sheet_w, sheet_h), color=(26, 26, 32))
    draw = ImageDraw.Draw(sheet)

    for idx, path in enumerate(image_paths):
        c = idx % columns
        r = idx // columns
        x = 10 + c * cell_w
        y = 10 + r * cell_h

        try:
            with Image.open(path) as img:
                # Convert RGBA to RGB with dark background if necessary
                if img.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", img.size, (20, 20, 25))
                    bg.paste(img, mask=img.split()[-1])
                    base_img = bg
                else:
                    base_img = img.convert("RGB")

                base_img.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
                # Center thumbnail in cell
                off_x = (thumb_width - base_img.width) // 2
                off_y = (thumb_height - base_img.height) // 2
                sheet.paste(base_img, (x + off_x, y + off_y))
        except Exception as exc:
            logger.warning(f"Failed to load thumbnail for {path.name}: {exc}")
            draw.rectangle([x, y, x + thumb_width, y + thumb_height], fill=(50, 20, 20))
            draw.text((x + 10, y + 20), "Error loading", fill=(255, 100, 100))

        # Draw filename label
        label = path.name
        if len(label) > 24:
            label = label[:21] + "..."
        draw.text((x + 5, y + thumb_height + 5), f"#{idx+1} {label}", fill=(200, 200, 220))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, "JPEG", quality=85)
    logger.info(f"Generated contact sheet with {count} images at: {output_path}")
    return output_path


def generate_html_review_report(
    report_data: Dict[str, Any],
    output_path: Path,
    relative_image_prefix: str = "../artwork/",
) -> Path:
    """
    Generate an HTML review page displaying image thumbnails, dimensions, duplicate alerts, and crops.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    items_html: List[str] = []
    for item in report_data.get("images", []):
        fn = html.escape(item["filename"])
        dims = f"{item['width']} × {item['height']}"
        aspect = item["aspect_ratio"]
        fmt = item["format"]
        size_kb = item["file_size_bytes"] // 1024

        warning_badge = ""
        if item.get("is_extremely_tall"):
            warning_badge += '<span class="badge badge-warn">Extremely Tall Strip</span> '
        if item.get("has_transparency"):
            warning_badge += '<span class="badge badge-info">Alpha Channel</span> '

        img_url = f"{relative_image_prefix}{fn}"

        items_html.append(f"""
        <div class="panel-card">
            <div class="img-wrap">
                <img src="{img_url}" alt="{fn}" loading="lazy"/>
            </div>
            <div class="meta">
                <div class="filename" title="{fn}">{fn}</div>
                <div class="stats">{dims} | {aspect}:1 | {fmt} | {size_kb} KB</div>
                <div class="badges">{warning_badge}</div>
            </div>
        </div>
        """)

    duplicates_summary = ""
    dupes = report_data.get("duplicate_clusters", {})
    if dupes:
        dupe_rows = "".join(f"<li>Hash {k[:12]}... : {', '.join(v)}</li>" for k, v in dupes.items())
        duplicates_summary = f"""
        <div class="alert alert-warning">
            <strong>Duplicate Artwork Panels Detected:</strong>
            <ul>{dupe_rows}</ul>
        </div>
        """

    tall_summary = ""
    tall = report_data.get("tall_images", [])
    if tall:
        tall_summary = f"""
        <div class="alert alert-info">
            <strong>{len(tall)} Extremely Tall Strips Detected:</strong>
            These panels need manual crop coordinates in the scene manifest to prevent squishing or letterboxing.
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Manhwa Story Studio - Artwork Ingestion Report</title>
    <style>
        :root {{
            --bg: #0d1117;
            --surface: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --heading: #f0f6fc;
            --accent: #58a6ff;
            --warn: #d29922;
        }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 24px;
        }}
        h1, h2 {{ color: var(--heading); }}
        .header {{ margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 16px; }}
        .stats-bar {{ display: flex; gap: 24px; margin-bottom: 24px; }}
        .stat-box {{ background: var(--surface); padding: 12px 20px; border-radius: 6px; border: 1px solid var(--border); }}
        .stat-val {{ font-size: 24px; font-weight: bold; color: var(--accent); }}
        .alert {{ padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; font-size: 14px; }}
        .alert-warning {{ background: #382800; border: 1px solid #7a5400; color: #e3b341; }}
        .alert-info {{ background: #0c2d6b; border: 1px solid #1f6feb; color: #79c0ff; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 16px;
        }}
        .panel-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}
        .img-wrap {{
            height: 280px;
            background: #000;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }}
        .img-wrap img {{
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }}
        .meta {{ padding: 10px; font-size: 12px; }}
        .filename {{ font-weight: bold; color: var(--heading); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .stats {{ color: #8b949e; margin-top: 4px; }}
        .badges {{ margin-top: 6px; }}
        .badge {{ padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; }}
        .badge-warn {{ background: var(--warn); color: #000; }}
        .badge-info {{ background: var(--accent); color: #000; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Artwork Ingestion & Review Report</h1>
        <p>Review panels for selection, aspect ratio, and duplicate detection before scene manifest generation.</p>
    </div>

    <div class="stats-bar">
        <div class="stat-box"><div>Total Scanned</div><div class="stat-val">{report_data.get("total_scanned", 0)}</div></div>
        <div class="stat-box"><div>Valid Panels</div><div class="stat-val">{report_data.get("valid_count", 0)}</div></div>
        <div class="stat-box"><div>Tall Strips</div><div class="stat-val">{report_data.get("tall_images_count", 0)}</div></div>
        <div class="stat-box"><div>Corrupted</div><div class="stat-val">{len(report_data.get("corrupted_files", []))}</div></div>
    </div>

    {duplicates_summary}
    {tall_summary}

    <div class="grid">
        {"".join(items_html)}
    </div>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(f"Generated HTML review report at: {output_path}")
    return output_path
