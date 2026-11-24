"""
Read-only workspace scanner for Manhwa Story Studio Pro Dashboard.
Inspects assets/inbox/, data/projects/, exports/marathons/, and configs/series_profiles/
without locking or modifying any active files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from manhwa_studio.ingestion.inbox_scanner import parse_chapter_number
from manhwa_studio.ingestion.image_inspector import SUPPORTED_EXTENSIONS, natural_sort_key
from manhwa_studio.studio_pro.series_manager import SeriesManager
from manhwa_studio.utils.paths import safe_slug


class WorkspaceScanner:
    """Safely inspects workspace directories in read-only mode."""

    def __init__(
        self,
        root_dir: Optional[Path] = None,
        inbox_dir: Optional[Path] = None,
        projects_dir: Optional[Path] = None,
        exports_dir: Optional[Path] = None,
    ):
        self.root_dir = (root_dir or Path.cwd()).resolve()
        self.inbox_dir = (inbox_dir or (self.root_dir / "assets" / "inbox")).resolve()
        self.projects_dir = (projects_dir or (self.root_dir / "data" / "projects")).resolve()
        self.exports_dir = (exports_dir or (self.root_dir / "exports")).resolve()
        self.sm = SeriesManager()

    def get_system_overview(self) -> Dict[str, Any]:
        """Return disk space, API key status, and high-level workspace counts."""
        disk = shutil.disk_usage(self.root_dir)
        has_api_key = bool(os.environ.get("GEMINI_API_KEY"))
        if not has_api_key:
            env_file = self.root_dir / ".env"
            if env_file.exists():
                try:
                    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.strip().startswith("GEMINI_API_KEY=") and len(line.split("=", 1)[1].strip()) > 5:
                            has_api_key = True
                            break
                except Exception:
                    pass

        return {
            "root_dir": str(self.root_dir),
            "disk_free_gb": round(disk.free / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "disk_used_percent": round((disk.used / disk.total) * 100, 1) if disk.total else 0,
            "gemini_key_configured": has_api_key,
            "gpu_nvenc_enabled": self._check_gpu_nvenc(),
            "video_encoder": self._get_video_encoder_name(),
            "timestamp": datetime.now().isoformat(),
        }

    def _check_gpu_nvenc(self) -> bool:
        try:
            from manhwa_studio.rendering.ffmpeg import is_nvenc_available
            return is_nvenc_available()
        except Exception:
            return False

    def _get_video_encoder_name(self) -> str:
        try:
            from manhwa_studio.rendering.ffmpeg import detect_gpu_encoder
            return detect_gpu_encoder()
        except Exception:
            return "libx264"

    def scan_inbox_summary(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Scan assets/inbox/ without unpacking or modifying anything.
        Returns a mapping of series_slug -> list of inbox chapter items.
        """
        result: Dict[str, List[Dict[str, Any]]] = {}
        if not self.inbox_dir.exists():
            return result

        try:
            entries = list(self.inbox_dir.iterdir())
        except Exception:
            return result

        for entry in entries:
            if entry.name.startswith("."):
                continue

            if entry.is_dir():
                # Check if direct chapter folder or series folder
                direct_imgs = [
                    f for f in entry.iterdir()
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                ]
                direct_zips = [
                    f for f in entry.iterdir()
                    if f.is_file() and f.suffix.lower() == ".zip"
                ]

                # Sub-directories (chapters inside a Series folder)
                subdirs = [d for d in entry.iterdir() if d.is_dir() and not d.name.startswith(".")]

                if subdirs or (direct_zips and not direct_imgs):
                    series_name = entry.name.replace("_", " ").strip()
                    slug = safe_slug(series_name)
                    items = result.setdefault(slug, [])

                    for sub in subdirs:
                        try:
                            imgs = [
                                f for f in sub.iterdir()
                                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                            ]
                            zips = [
                                f for f in sub.iterdir()
                                if f.is_file() and f.suffix.lower() == ".zip"
                            ]
                            if not imgs and not zips:
                                continue
                            ch_num = parse_chapter_number(sub.name)
                            items.append({
                                "series_name": series_name,
                                "series_slug": slug,
                                "chapter": ch_num,
                                "folder_name": sub.name,
                                "folder_path": str(sub.relative_to(self.root_dir)),
                                "image_count": len(imgs),
                                "zip_count": len(zips),
                                "is_zip_only": len(imgs) == 0 and len(zips) > 0,
                            })
                        except Exception:
                            continue

                    for zf in direct_zips:
                        ch_num = parse_chapter_number(zf.stem)
                        items.append({
                            "series_name": series_name,
                            "series_slug": slug,
                            "chapter": ch_num,
                            "folder_name": zf.name,
                            "folder_path": str(zf.relative_to(self.root_dir)),
                            "image_count": 0,
                            "zip_count": 1,
                            "is_zip_only": True,
                        })
                elif direct_imgs:
                    ch_num = parse_chapter_number(entry.name)
                    series_name = "Myst, Might, Mayhem"
                    slug = safe_slug(series_name)
                    items = result.setdefault(slug, [])
                    items.append({
                        "series_name": series_name,
                        "series_slug": slug,
                        "chapter": ch_num,
                        "folder_name": entry.name,
                        "folder_path": str(entry.relative_to(self.root_dir)),
                        "image_count": len(direct_imgs),
                        "zip_count": len(direct_zips),
                        "is_zip_only": False,
                    })

        for slug in result:
            result[slug].sort(key=lambda x: x["chapter"])

        return result

    def _inspect_chapter_project(self, series_slug: str, ch_dir: Path) -> Dict[str, Any]:
        """Inspect a single data/projects/{series_slug}/chapter_XXX directory."""
        ch_num = parse_chapter_number(ch_dir.name)
        artwork_dir = ch_dir / "artwork"
        scripts_dir = ch_dir / "scripts"
        audio_dir = ch_dir / "audio"
        renders_dir = ch_dir / "renders"
        exports_dir = ch_dir / "exports"
        reports_dir = ch_dir / "reports"

        # Count artwork
        artwork_count = 0
        if artwork_dir.exists():
            try:
                artwork_count = sum(
                    1 for f in artwork_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                )
            except Exception:
                pass

        # Read manifest safely
        manifest_file = scripts_dir / "scene_manifest.json"
        has_script = manifest_file.exists()
        scene_count = 0
        title = f"Chapter {ch_num}"
        series_name = series_slug.replace("_", " ").title()
        estimated_duration = 0.0
        approved = False

        if has_script:
            try:
                m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                title = m_data.get("title") or title
                series_name = m_data.get("series") or series_name
                approved = bool(m_data.get("approved_by_user", False))
                scenes = m_data.get("scenes", [])
                scene_count = len(scenes)
                for s in scenes:
                    dur = s.get("actual_audio_duration") or s.get("duration") or 0.0
                    estimated_duration += float(dur)
            except Exception:
                pass

        # Check state.json
        state_file = ch_dir / "state.json"
        active_stage = None
        stage_statuses: Dict[str, str] = {}
        updated_at = None
        if state_file.exists():
            try:
                st_data = json.loads(state_file.read_text(encoding="utf-8"))
                updated_at = st_data.get("updated_at")
                for st_name, rec in st_data.get("stages", {}).items():
                    status_val = rec.get("status", "pending")
                    stage_statuses[st_name] = status_val
                    if status_val == "running":
                        active_stage = st_name
            except Exception:
                pass

        # Check audio
        master_audio = audio_dir / "master_soundtrack.mp3"
        has_master_audio = master_audio.exists() and master_audio.stat().st_size > 1000

        # Check rendered videos (1x and speed variants)
        rendered_variants: List[Dict[str, Any]] = []
        temp_segments_mb = 0.0
        if renders_dir.exists():
            try:
                for mp4 in sorted(renders_dir.glob("final_video*.mp4")):
                    if mp4.stat().st_size < 50000:
                        continue
                    stem = mp4.stem
                    speed_tag = "1.0x"
                    m_sp = re.search(r"_(\d+(?:\.\d+)?)x$", stem)
                    if m_sp:
                        speed_tag = f"{m_sp.group(1)}x"
                    rendered_variants.append({
                        "speed": speed_tag,
                        "filename": mp4.name,
                        "path": str(mp4.relative_to(self.root_dir)),
                        "size_mb": round(mp4.stat().st_size / (1024 * 1024), 2),
                        "mtime": datetime.fromtimestamp(mp4.stat().st_mtime).isoformat(),
                    })
                # Calculate intermediate temp segments size
                seg_dir = renders_dir / "segments"
                if seg_dir.exists():
                    temp_segments_mb += sum(f.stat().st_size for f in seg_dir.glob("*.mp4") if f.is_file()) / (1024 * 1024)
                for raw_tmp in ("raw_stitched.mp4", "merged_video.mp4"):
                    rt_path = renders_dir / raw_tmp
                    if rt_path.exists():
                        temp_segments_mb += rt_path.stat().st_size / (1024 * 1024)
            except Exception:
                pass

        # Also check exports_dir if no renders found
        export_video_path = None
        if exports_dir.exists():
            try:
                for mp4 in exports_dir.glob("*_pro.mp4"):
                    if mp4.stat().st_size > 50000:
                        export_video_path = str(mp4.relative_to(self.root_dir))
                        if not any(v["speed"] == "1.0x" for v in rendered_variants):
                            rendered_variants.append({
                                "speed": "1.0x",
                                "filename": mp4.name,
                                "path": export_video_path,
                                "size_mb": round(mp4.stat().st_size / (1024 * 1024), 2),
                                "mtime": datetime.fromtimestamp(mp4.stat().st_mtime).isoformat(),
                            })
            except Exception:
                pass

        # Check thumbnail & YouTube kit
        thumb_candidates = [
            reports_dir / "pro_thumbnail.jpg",
            exports_dir / f"{series_slug}_ch{ch_num:03d}_thumbnail.jpg",
        ]
        thumbnail_path = None
        for tc in thumb_candidates:
            if tc.exists() and tc.stat().st_size > 1000:
                thumbnail_path = str(tc.relative_to(self.root_dir))
                break

        kit_candidates = [
            reports_dir / "youtube_upload_kit.txt",
            exports_dir / f"{series_slug}_ch{ch_num:03d}_youtube_kit.txt",
        ]
        youtube_kit_path = None
        for kc in kit_candidates:
            if kc.exists() and kc.stat().st_size > 10:
                youtube_kit_path = str(kc.relative_to(self.root_dir))
                break

        # Determine overall status badge
        if active_stage:
            overall_status = f"running:{active_stage}"
        elif rendered_variants:
            overall_status = "rendered"
        elif has_master_audio:
            overall_status = "audio_ready"
        elif has_script:
            overall_status = "script_ready"
        elif artwork_count > 0:
            overall_status = "ingested"
        else:
            overall_status = "empty"

        return {
            "chapter": ch_num,
            "title": title,
            "series_name": series_name,
            "series_slug": series_slug,
            "project_path": str(ch_dir.relative_to(self.root_dir)),
            "artwork_count": artwork_count,
            "has_script": has_script,
            "scene_count": scene_count,
            "approved": approved,
            "estimated_duration_sec": round(estimated_duration, 1),
            "has_master_audio": has_master_audio,
            "rendered_variants": rendered_variants,
            "speeds_available": [v["speed"] for v in rendered_variants],
            "temp_segments_mb": round(temp_segments_mb, 1),
            "thumbnail_path": thumbnail_path,
            "youtube_kit_path": youtube_kit_path,
            "overall_status": overall_status,
            "stage_statuses": stage_statuses,
            "updated_at": updated_at,
        }

    def scan_all_series(self) -> List[Dict[str, Any]]:
        """
        Aggregate all series across assets/inbox/, data/projects/, and configs/series_profiles/.
        Returns unified per-series data with chapter matrices.
        """
        inbox_map = self.scan_inbox_summary()
        series_dict: Dict[str, Dict[str, Any]] = {}

        # 1. Discover project series folders
        if self.projects_dir.exists():
            for s_dir in sorted(self.projects_dir.iterdir()):
                if not s_dir.is_dir() or s_dir.name.startswith("."):
                    continue
                slug = s_dir.name
                chapters_map: Dict[int, Dict[str, Any]] = {}
                series_display_name = slug.replace("_", " ").title()

                for ch_dir in sorted(s_dir.iterdir()):
                    if not ch_dir.is_dir() or not ch_dir.name.startswith("chapter_"):
                        continue
                    ch_info = self._inspect_chapter_project(slug, ch_dir)
                    chapters_map[ch_info["chapter"]] = ch_info
                    if ch_info.get("series_name"):
                        series_display_name = ch_info["series_name"]

                series_dict[slug] = {
                    "series_slug": slug,
                    "series_name": series_display_name,
                    "chapters_map": chapters_map,
                }

        # 2. Merge inbox batches into series_dict
        for slug, inbox_items in inbox_map.items():
            if slug not in series_dict:
                s_name = inbox_items[0]["series_name"] if inbox_items else slug.replace("_", " ").title()
                series_dict[slug] = {
                    "series_slug": slug,
                    "series_name": s_name,
                    "chapters_map": {},
                }
            ch_map = series_dict[slug]["chapters_map"]
            for item in inbox_items:
                ch_num = item["chapter"]
                if ch_num in ch_map:
                    ch_map[ch_num]["in_inbox"] = True
                    ch_map[ch_num]["inbox_info"] = item
                else:
                    ch_map[ch_num] = {
                        "chapter": ch_num,
                        "title": f"Chapter {ch_num} (In Inbox)",
                        "series_name": series_dict[slug]["series_name"],
                        "series_slug": slug,
                        "project_path": None,
                        "artwork_count": item["image_count"],
                        "has_script": False,
                        "scene_count": 0,
                        "approved": False,
                        "estimated_duration_sec": 0.0,
                        "has_master_audio": False,
                        "rendered_variants": [],
                        "speeds_available": [],
                        "thumbnail_path": None,
                        "youtube_kit_path": None,
                        "overall_status": "inbox_only",
                        "stage_statuses": {},
                        "updated_at": None,
                        "in_inbox": True,
                        "inbox_info": item,
                    }

        # 3. Format output list with summary metrics
        series_list: List[Dict[str, Any]] = []
        for slug, s_data in sorted(series_dict.items()):
            chapters = [
                ch_val for _, ch_val in sorted(s_data["chapters_map"].items(), key=lambda kv: kv[0])
            ]
            for c in chapters:
                c.setdefault("in_inbox", False)

            total_ch = len(chapters)
            inbox_only_count = sum(1 for c in chapters if c["overall_status"] == "inbox_only")
            script_ready_count = sum(1 for c in chapters if c["has_script"])
            rendered_count = sum(1 for c in chapters if len(c["rendered_variants"]) > 0)
            reclaimable_mb = sum(
                float(c.get("temp_segments_mb", 0.0))
                for c in chapters
                if len(c.get("rendered_variants", [])) > 0
            )

            profile = self.sm.load_profile(slug)
            genre = profile.genre if profile else "murim"

            series_list.append({
                "series_slug": slug,
                "series_name": s_data["series_name"],
                "genre": genre,
                "total_chapters": total_ch,
                "inbox_only_count": inbox_only_count,
                "script_ready_count": script_ready_count,
                "rendered_count": rendered_count,
                "reclaimable_temp_mb": round(reclaimable_mb, 1),
                "chapters": chapters,
            })

        # Sort series with most chapters first
        series_list.sort(key=lambda s: (-s["total_chapters"], s["series_name"]))
        return series_list

    def scan_marathons(self) -> List[Dict[str, Any]]:
        """List all compiled marathon videos and timestamp files in exports/marathons/."""
        marathons_dir = self.exports_dir / "marathons"
        if not marathons_dir.exists():
            return []

        items: List[Dict[str, Any]] = []
        try:
            for mp4 in sorted(marathons_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
                ts_file = mp4.with_suffix(".timestamps.txt")
                has_ts = ts_file.exists()
                ts_preview = ""
                if has_ts:
                    try:
                        ts_preview = ts_file.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        pass
                items.append({
                    "filename": mp4.name,
                    "path": str(mp4.relative_to(self.root_dir)),
                    "size_mb": round(mp4.stat().st_size / (1024 * 1024), 2),
                    "mtime": datetime.fromtimestamp(mp4.stat().st_mtime).isoformat(),
                    "has_timestamps": has_ts,
                    "timestamps_path": str(ts_file.relative_to(self.root_dir)) if has_ts else None,
                    "timestamps_text": ts_preview,
                })
        except Exception:
            pass
        return items

    def scan_instagram_exports(self) -> List[Dict[str, Any]]:
        """List all Instagram-compatible 9:16 exports and guides in exports/instagram/."""
        ig_root = self.exports_dir / "instagram"
        if not ig_root.exists():
            return []

        groups: List[Dict[str, Any]] = []
        try:
            for folder in sorted([d for d in ig_root.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime, reverse=True):
                videos: List[Dict[str, Any]] = []
                for mp4 in sorted(folder.glob("*.mp4"), key=natural_sort_key):
                    videos.append({
                        "filename": mp4.name,
                        "path": str(mp4.relative_to(self.root_dir)).replace("\\", "/"),
                        "size_mb": round(mp4.stat().st_size / (1024 * 1024), 2),
                        "mtime": datetime.fromtimestamp(mp4.stat().st_mtime).isoformat(),
                    })
                guide_file = folder / "INSTAGRAM_PUBLISHING_GUIDE.md"
                guide_text = ""
                if guide_file.exists():
                    try:
                        guide_text = guide_file.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        pass
                if videos or guide_text:
                    groups.append({
                        "folder": folder.name,
                        "dir_path": str(folder.relative_to(self.root_dir)).replace("\\", "/"),
                        "videos": videos,
                        "has_guide": bool(guide_text),
                        "guide_path": str(guide_file.relative_to(self.root_dir)).replace("\\", "/") if guide_file.exists() else None,
                        "guide_text": guide_text,
                    })
        except Exception:
            pass
        return groups

    def get_chapter_detail(self, series_slug: str, chapter: int) -> Dict[str, Any]:
        """Return full scene manifest, panels list, and YouTube kit content for a chapter."""
        ch_dir = self.projects_dir / series_slug / f"chapter_{chapter:03d}"
        if not ch_dir.exists():
            raise FileNotFoundError(f"Chapter directory not found: {ch_dir}")

        base_info = self._inspect_chapter_project(series_slug, ch_dir)

        # Load scenes
        scenes = []
        manifest_file = ch_dir / "scripts" / "scene_manifest.json"
        if manifest_file.exists():
            try:
                m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                scenes = m_data.get("scenes", [])
            except Exception:
                pass

        # Load all panel filenames in artwork/
        artwork_dir = ch_dir / "artwork"
        panels: List[str] = []
        if artwork_dir.exists():
            try:
                img_files = [
                    f for f in artwork_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                ]
                panels = [f.name for f in sorted(img_files, key=natural_sort_key)]
            except Exception:
                pass

        # Load YouTube kit text if present
        yt_kit_text = ""
        if base_info.get("youtube_kit_path"):
            kit_full = self.root_dir / base_info["youtube_kit_path"]
            if kit_full.exists():
                try:
                    yt_kit_text = kit_full.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass

        base_info["scenes"] = scenes
        base_info["panels"] = panels
        base_info["youtube_kit_text"] = yt_kit_text
        return base_info

