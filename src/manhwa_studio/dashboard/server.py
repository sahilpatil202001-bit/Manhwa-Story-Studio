"""
Zero-dependency Multi-Threaded HTTP Server for Manhwa Story Studio Pro Dashboard.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from manhwa_studio.dashboard.job_queue import JobQueueManager
from manhwa_studio.dashboard.scanner import WorkspaceScanner
from manhwa_studio.logging_config import get_logger
from manhwa_studio.studio_pro.series_manager import SeriesManager
from manhwa_studio.utils.paths import safe_slug

logger = get_logger("manhwa_studio.dashboard")


class DashboardAppState:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = (root_dir or Path.cwd()).resolve()
        self.scanner = WorkspaceScanner(root_dir=self.root_dir)
        self.queue = JobQueueManager(root_dir=self.root_dir)
        self.sm = SeriesManager()
        self.static_dir = Path(__file__).parent / "static"


def _resolve_inbox_path(inbox_path: str, series_slug: str, root_dir: Optional[Path]) -> str:
    """Resolve an inbox folder by slug if the literal series-name path does not exist."""
    if not root_dir:
        return inbox_path
    if (root_dir / inbox_path).exists():
        return inbox_path
    inbox_root = root_dir / "assets" / "inbox"
    if inbox_root.is_dir():
        for entry in inbox_root.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            candidate_slug = safe_slug(entry.name.replace("_", " ").strip())
            if candidate_slug == series_slug:
                return f"assets/inbox/{entry.name}"
    return inbox_path


def build_cli_job_spec(payload: Dict[str, Any], root_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Translate high-level dashboard form parameters into exact `manhwa_studio.cli`
    arguments, job title, lane, and chapter locks.
    """
    action = payload.get("action", "")
    series_name = str(payload.get("series_name") or payload.get("series") or "Nano Machine").strip()
    series_slug = str(payload.get("series_slug") or safe_slug(series_name)).strip()

    if action == "process-inbox":
        inbox_path = _resolve_inbox_path(
            str(payload.get("inbox_path") or f"assets/inbox/{series_name}").strip(),
            series_slug,
            root_dir,
        )
        ch_start = payload.get("chapter_start")
        ch_end = payload.get("chapter_end")
        ch_single = payload.get("chapter")
        auto_approve = bool(payload.get("auto_approve", False))
        auto_render = bool(payload.get("auto_render", False))

        args = ["process-inbox", "--inbox", inbox_path, "--series", series_name]
        chapters: List[int] = []
        range_label = "All"

        if ch_single:
            c = int(ch_single)
            args.extend(["--chapter", str(c)])
            chapters = [c]
            range_label = f"Ch.{c}"
        elif ch_start and ch_end:
            s, e = int(ch_start), int(ch_end)
            args.extend(["--chapter-start", str(s), "--chapter-end", str(e)])
            chapters = list(range(s, e + 1))
            range_label = f"Ch.{s}–{e}"

        if auto_approve:
            args.append("--auto-approve")
        if auto_render:
            args.append("--render")

        return {
            "job_type": "process-inbox",
            "title": f"Process Inbox: {series_name} ({range_label})",
            "command_args": args,
            "lane": "script",
            "series_slug": series_slug,
            "chapters": chapters,
        }

    elif action == "pro-render":
        chapter = int(payload.get("chapter", 1))
        project_path = str(payload.get("project_path") or f"data/projects/{series_slug}/chapter_{chapter:03d}")
        speed = float(payload.get("speed", 1.0))
        burn_subs = bool(payload.get("burn_subtitles", False))
        thumb_caps = bool(payload.get("thumbnail_captions", False))
        cold_open = bool(payload.get("cold_open", True))
        outro = bool(payload.get("outro", False))
        rebuild = bool(payload.get("rebuild_segments", False))
        thumb_scene = str(payload.get("thumbnail_scene") or "").strip()

        args = ["pro-render", "-p", project_path]
        if speed != 1.0:
            args.extend(["--speed", f"{speed:g}"])
        if burn_subs:
            args.append("--burn-subtitles")
        if thumb_caps:
            args.append("--thumbnail-captions")
        if cold_open:
            args.append("--cold-open")
        else:
            args.append("--no-cold-open")
        if outro:
            args.append("--outro")
        else:
            args.append("--no-outro")
        if rebuild:
            args.append("--rebuild-segments")
        if thumb_scene:
            args.extend(["--thumbnail-scene", thumb_scene])

        gpu_target = str(payload.get("gpu_target") or "local").strip().lower()
        if gpu_target not in ("local", "cloud"):
            gpu_target = "local"
        gpu_badge = " [☁️ Cloud T4]" if gpu_target == "cloud" else ""

        return {
            "job_type": "pro-render",
            "title": f"Pro Render: {series_name} Ch.{chapter} ({speed:g}x){gpu_badge}",
            "command_args": args,
            "lane": "render_cloud" if gpu_target == "cloud" else "render",
            "gpu_target": gpu_target,
            "series_slug": series_slug,
            "chapters": [chapter],
        }

    elif action == "pro-render-range":
        ch_start = int(payload.get("chapter_start", 1))
        ch_end = int(payload.get("chapter_end", ch_start))
        speed = float(payload.get("speed", 1.25))
        burn_subs = bool(payload.get("burn_subtitles", False))
        thumb_caps = bool(payload.get("thumbnail_captions", False))
        cold_open = bool(payload.get("cold_open", True))
        outro = bool(payload.get("outro", False))
        rebuild = bool(payload.get("rebuild_segments", False))

        args = [
            "pro-render-range",
            "--series", series_slug,
            "--chapter-start", str(ch_start),
            "--chapter-end", str(ch_end),
        ]
        if speed != 1.0:
            args.extend(["--speed", f"{speed:g}"])
        if burn_subs:
            args.append("--burn-subtitles")
        if thumb_caps:
            args.append("--thumbnail-captions")
        if cold_open:
            args.append("--cold-open")
        else:
            args.append("--no-cold-open")
        if outro:
            args.append("--outro")
        else:
            args.append("--no-outro")
        if rebuild:
            args.append("--rebuild-segments")

        return {
            "job_type": "pro-render-range",
            "title": f"Pro Render Range: {series_name} Ch.{ch_start}–{ch_end} ({speed:g}x)",
            "command_args": args,
            "lane": "render",
            "series_slug": series_slug,
            "chapters": list(range(ch_start, ch_end + 1)),
        }

    elif action == "marathon":
        chapters_str = str(payload.get("chapters", "1,2,3")).strip()
        ch_nums = [int(x.strip()) for x in chapters_str.split(",") if x.strip().isdigit()]
        speed = float(payload.get("speed", 1.25))
        no_bumpers = bool(payload.get("no_bumpers", True))
        outro = bool(payload.get("outro", True))
        output_path = str(payload.get("output_path") or "").strip()

        if not output_path and ch_nums:
            sp_suffix = f"_{speed:g}x" if speed != 1.0 else ""
            output_path = f"exports/marathons/{series_slug}_ch{ch_nums[0]}_to_ch{ch_nums[-1]}_movie{sp_suffix}.mp4"

        args = [
            "marathon",
            "--series", series_name,
            "--chapters", ",".join(str(c) for c in ch_nums),
        ]
        if speed != 1.0:
            args.extend(["--speed", f"{speed:g}"])
        if no_bumpers:
            args.append("--no-bumpers")
        else:
            args.append("--bumpers")
        if outro:
            args.append("--outro")
        else:
            args.append("--no-outro")
        if output_path:
            args.extend(["-o", output_path])

        ch_label = f"Ch.{ch_nums[0]}–{ch_nums[-1]}" if ch_nums else chapters_str
        return {
            "job_type": "marathon",
            "title": f"Marathon Movie: {series_name} {ch_label} ({speed:g}x)",
            "command_args": args,
            "lane": "render",
            "series_slug": series_slug,
            "chapters": ch_nums,
        }

    elif action == "speed-video":
        input_video = str(payload.get("input_video", "")).strip()
        speed = float(payload.get("speed", 1.25))
        output_video = str(payload.get("output_video", "")).strip()
        chapter = int(payload.get("chapter", 0))

        args = ["speed-video", "--input", input_video, "--speed", f"{speed:g}"]
        if output_video:
            args.extend(["--output", output_video])

        return {
            "job_type": "speed-video",
            "title": f"Speed Video ({speed:g}x): {Path(input_video).name}",
            "command_args": args,
            "lane": "render",
            "series_slug": series_slug,
            "chapters": [chapter] if chapter else [],
        }

    elif action == "pro-thumbnail":
        chapter = int(payload.get("chapter", 1))
        project_path = str(payload.get("project_path") or f"data/projects/{series_slug}/chapter_{chapter:03d}")
        scene = str(payload.get("scene") or "").strip()
        panel = str(payload.get("panel") or "").strip()
        captions = bool(payload.get("captions", False))
        hook = str(payload.get("hook") or "").strip()

        args = ["pro-thumbnail", "-p", project_path]
        if scene:
            args.extend(["--scene", scene])
        if panel:
            args.extend(["--panel", panel])
        if captions:
            args.append("--captions")
        if hook:
            args.extend(["--hook", hook])

        return {
            "job_type": "pro-thumbnail",
            "title": f"Thumbnail: {series_name} Ch.{chapter} ({scene or panel or 'Auto'})",
            "command_args": args,
            "lane": "script",
            "series_slug": series_slug,
            "chapters": [chapter],
        }

    elif action == "pro-youtube-kit":
        chapter = int(payload.get("chapter", 1))
        project_path = str(payload.get("project_path") or f"data/projects/{series_slug}/chapter_{chapter:03d}")
        args = ["pro-youtube-kit", "-p", project_path]
        return {
            "job_type": "pro-youtube-kit",
            "title": f"YouTube SEO Kit: {series_name} Ch.{chapter}",
            "command_args": args,
            "lane": "script",
            "series_slug": series_slug,
            "chapters": [chapter],
        }

    elif action == "clean-chapters":
        inbox_path = str(payload.get("inbox_path") or f"assets/inbox/{series_name}").strip()
        args = ["clean-chapters", "--path", inbox_path]
        return {
            "job_type": "clean-chapters",
            "title": f"Clean & Unpack Zips: {inbox_path}",
            "command_args": args,
            "lane": "script",
            "series_slug": series_slug,
            "chapters": [],
        }

    elif action == "social-pack":
        chapter = int(payload.get("chapter", 1))
        project_path = str(payload.get("project_path") or f"data/projects/{series_slug}/chapter_{chapter:03d}")
        reel_dur = float(payload.get("reel_duration", 45.0))
        overlays = bool(payload.get("overlays", True))
        args = [
            "social-pack",
            "-p", project_path,
            "--reel-duration", str(reel_dur),
            "--overlays" if overlays else "--clean",
        ]
        if payload.get("reel_start") is not None and str(payload.get("reel_start")).strip() != "":
            args.extend(["--reel-start", str(float(payload["reel_start"]))])
        return {
            "job_type": "social-pack",
            "title": f"YT Post + IG Carousel + 9:16 Reel: {series_name} Ch.{chapter}",
            "command_args": args,
            "lane": "render",
            "series_slug": series_slug,
            "chapters": [chapter],
        }

    elif action == "modernize-scripts":
        mode = str(payload.get("mode") or "rewrite").strip()
        args = ["modernize-scripts", "--series", series_slug, "--mode", mode]
        ch_list: List[int] = []
        if payload.get("chapter"):
            ch = int(payload["chapter"])
            args.extend(["--chapter", str(ch)])
            ch_list = [ch]
            title_str = f"Hinglish Script Upgrade ({mode}): {series_name} Ch.{ch}"
        elif payload.get("chapter_start") and payload.get("chapter_end"):
            c_start = int(payload["chapter_start"])
            c_end = int(payload["chapter_end"])
            args.extend(["--chapter-start", str(c_start), "--chapter-end", str(c_end)])
            ch_list = list(range(c_start, c_end + 1))
            title_str = f"Hinglish Script Upgrade ({mode}): {series_name} Ch.{c_start}–{c_end}"
        else:
            title_str = f"Hinglish Script Upgrade ({mode}): All Unrendered in {series_name}"
        return {
            "job_type": "modernize-scripts",
            "title": title_str,
            "command_args": args,
            "lane": "script",
            "series_slug": series_slug,
            "chapters": ch_list,
        }

    elif action == "instagram-export":
        marathon_file = str(payload.get("marathon_file") or "").strip()
        speed = float(payload.get("speed", 1.25))
        max_minutes = float(payload.get("max_minutes", 18.0))
        aspect = str(payload.get("aspect") or "9x16").strip()
        yt_handle = str(payload.get("yt_handle") or "").strip()
        ig_handle = str(payload.get("ig_handle") or "").strip()
        prefer_cpu = bool(payload.get("prefer_cpu", False))

        args = [
            "instagram-export",
            "--max-minutes", f"{max_minutes:g}",
            "--aspect", aspect,
        ]
        if series_slug:
            args.extend(["--series", series_slug])
        if yt_handle:
            args.extend(["--yt-handle", yt_handle])
        if ig_handle:
            args.extend(["--ig-handle", ig_handle])
        if prefer_cpu:
            args.append("--cpu")

        if marathon_file:
            args.extend(["--marathon-file", marathon_file])
            ch_list = []
            title_str = f"Instagram {aspect} Split: {Path(marathon_file).name} (<={max_minutes:g}m)"
        else:
            c_start = int(payload.get("chapter_start", 1))
            c_end = int(payload.get("chapter_end", c_start))
            args.extend(["--chapter-start", str(c_start), "--chapter-end", str(c_end), "--speed", f"{speed:g}"])
            ch_list = list(range(c_start, c_end + 1))
            title_str = f"Instagram {aspect} Export: {series_name} Ch.{c_start}–{c_end} ({speed:g}x)"

        return {
            "job_type": "instagram-export",
            "title": title_str,
            "command_args": args,
            "lane": "render",
            "series_slug": series_slug,
            "chapters": ch_list,
        }

    elif action == "yt-upload-batch":
        chapters_str = str(payload.get("chapters") or "").strip()
        count = int(payload.get("count", 3))
        speed = float(payload.get("speed", 1.25))
        slots = str(payload.get("slots") or "10:00,16:00,21:00").strip()
        interval_hours = payload.get("interval_hours")
        start_at = str(payload.get("start_at") or "").strip()
        playlist_id = str(payload.get("playlist_id") or "").strip()
        dry_run = bool(payload.get("dry_run", False))

        args = ["yt-upload-batch", "--series", series_slug, "--count", str(count), "--speed", f"{speed:g}"]
        if chapters_str:
            args.extend(["--chapters", chapters_str])
        if interval_hours is not None and str(interval_hours).strip() != "":
            args.extend(["--interval-hours", str(float(interval_hours))])
        elif slots:
            args.extend(["--slots", slots])
        if start_at:
            args.extend(["--start-at", start_at])
        if playlist_id:
            args.extend(["--playlist-id", playlist_id])
        if dry_run:
            args.append("--dry-run")

        mode_label = "Dry Run" if dry_run else "Schedule & Upload"
        target_label = f"Ch.{chapters_str}" if chapters_str else f"Next {count}"
        return {
            "job_type": "yt-upload-batch",
            "title": f"YouTube {mode_label}: {series_name} ({target_label})",
            "command_args": args,
            "lane": "script",
            "series_slug": series_slug,
            "chapters": [],
        }

    elif action == "yt-upload-shorts":
        chapters_str = str(payload.get("chapters") or "").strip()
        count = int(payload.get("count", 3))
        duration = float(payload.get("duration", 90.0))
        slots = str(payload.get("slots") or "12:00,18:00,22:00").strip()
        interval_hours = payload.get("interval_hours")
        start_at = str(payload.get("start_at") or "").strip()
        playlist_id = str(payload.get("playlist_id") or "").strip()
        dry_run = bool(payload.get("dry_run", False))

        args = ["yt-upload-shorts", "--series", series_slug, "--count", str(count), "--duration", f"{duration:g}"]
        if chapters_str:
            args.extend(["--chapters", chapters_str])
        if interval_hours is not None and str(interval_hours).strip() != "":
            args.extend(["--interval-hours", str(float(interval_hours))])
        elif slots:
            args.extend(["--slots", slots])
        if start_at:
            args.extend(["--start-at", start_at])
        if playlist_id:
            args.extend(["--playlist-id", playlist_id])
        if dry_run:
            args.append("--dry-run")

        mode_label = "Dry Run" if dry_run else "Schedule & Upload"
        target_label = f"Ch.{chapters_str}" if chapters_str else f"Next {count}"
        return {
            "job_type": "yt-upload-shorts",
            "title": f"YouTube Shorts {mode_label}: {series_name} ({target_label})",
            "command_args": args,
            "lane": "script",
            "series_slug": series_slug,
            "chapters": [],
        }

    elif action == "yt-upload-marathon":
        marathon_file = str(payload.get("marathon_file") or "").strip()
        if not marathon_file:
            raise ValueError("Missing marathon_file for yt-upload-marathon")
        publish_at = str(payload.get("publish_at") or "").strip()
        slots = str(payload.get("slots") or "18:00").strip()
        playlist_id = str(payload.get("playlist_id") or "").strip()
        title_index = int(payload.get("title_index", 0))
        dry_run = bool(payload.get("dry_run", False))

        args = ["yt-upload-marathon", "--file", marathon_file, "--title-index", str(title_index)]
        if publish_at:
            args.extend(["--publish-at", publish_at])
        elif slots:
            args.extend(["--slots", slots])
        if playlist_id:
            args.extend(["--playlist-id", playlist_id])
        if dry_run:
            args.append("--dry-run")

        mode_label = "Dry Run" if dry_run else "Schedule & Upload"
        return {
            "job_type": "yt-upload-marathon",
            "title": f"YouTube Marathon {mode_label}: {Path(marathon_file).name}",
            "command_args": args,
            "lane": "script",
            "series_slug": series_slug,
            "chapters": [],
        }

    elif action == "ig-upload-batch":
        folder = str(payload.get("folder") or "").strip()
        if not folder:
            raise ValueError("Missing folder for ig-upload-batch")
        count = int(payload.get("count", 2))
        delay_minutes = float(payload.get("delay_minutes", 0.0))
        dry_run = bool(payload.get("dry_run", False))

        args = ["ig-upload-batch", "--folder", folder, "--count", str(count)]
        if delay_minutes > 0:
            args.extend(["--delay-minutes", f"{delay_minutes:g}"])
        if dry_run:
            args.append("--dry-run")

        mode_label = "Dry Run" if dry_run else "Publish Reels"
        return {
            "job_type": "ig-upload-batch",
            "title": f"Instagram {mode_label}: {folder} (Next {count})",
            "command_args": args,
            "lane": "script",
            "series_slug": folder,
            "chapters": [],
        }

    raise ValueError(f"Unsupported job action: '{action}'")


def make_handler_class(app_state: DashboardAppState):
    class DashboardRequestHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # Suppress noisy per-poll HTTP request logs in console
            pass

        def _send_json(self, data: Any, status: int = 200) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _read_json_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body)

        def _serve_file(self, file_path: Path) -> None:
            if not file_path.exists() or not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                return

            ctype, _ = mimetypes.guess_type(str(file_path))
            if not ctype:
                if file_path.suffix.lower() == ".webp":
                    ctype = "image/webp"
                elif file_path.suffix.lower() == ".mp4":
                    ctype = "video/mp4"
                else:
                    ctype = "application/octet-stream"

            file_size = file_path.stat().st_size
            range_header = self.headers.get("Range")

            # Support byte-range requests for smooth HTML5 video scrubbing
            if range_header and range_header.startswith("bytes="):
                try:
                    byte_range = range_header.split("=")[1].split("-")
                    start = int(byte_range[0]) if byte_range[0] else 0
                    end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else file_size - 1
                    end = min(end, file_size - 1)
                    chunk_len = end - start + 1

                    self.send_response(HTTPStatus.PARTIAL_CONTENT)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(chunk_len))
                    self.end_headers()
                    with open(file_path, "rb") as f:
                        f.seek(start)
                        self.wfile.write(f.read(chunk_len))
                    return
                except Exception:
                    pass

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    self.wfile.write(chunk)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            try:
                if path == "/api/state":
                    self._send_json({
                        "system": app_state.scanner.get_system_overview(),
                        "series": app_state.scanner.scan_all_series(),
                        "marathons": app_state.scanner.scan_marathons(),
                        "instagram_exports": app_state.scanner.scan_instagram_exports(),
                        "queue": app_state.queue.get_queue_snapshot(),
                    })
                    return

                if path == "/api/chapter-detail":
                    slug = query.get("series", [""])[0]
                    ch = int(query.get("chapter", ["1"])[0])
                    detail = app_state.scanner.get_chapter_detail(slug, ch)
                    self._send_json(detail)
                    return

                if path == "/api/job-logs":
                    job_id = query.get("job_id", [""])[0]
                    info = app_state.queue.get_job_details(job_id)
                    if not info:
                        self._send_json({"error": "Job not found"}, status=404)
                    else:
                        self._send_json(info)
                    return

                if path == "/api/profiles":
                    slugs = app_state.sm.list_profiles()
                    profiles = []
                    for s in slugs:
                        p = app_state.sm.load_profile(s)
                        if p:
                            profiles.append(p.model_dump())
                    self._send_json({"profiles": profiles})
                    return

                if path == "/api/cloud-gpu/status":
                    from manhwa_studio.dashboard.cloud_worker import (
                        fetch_cloud_worker_health,
                        load_cloud_worker_config,
                    )
                    cfg = load_cloud_worker_config(app_state.root_dir)
                    health = fetch_cloud_worker_health(cfg["url"], cfg["token"], timeout=4.0)
                    self._send_json({
                        "ok": True,
                        "url": cfg["url"],
                        "has_token": bool(cfg["token"]),
                        **health,
                    })
                    return

                if path == "/api/env-config":
                    from manhwa_studio.env_config import get_env_config
                    cfg = get_env_config()
                    self._send_json({"config": cfg.model_dump()})
                    return

                if path == "/api/gemini-keys":
                    keys = _read_dotenv_gemini_keys(app_state.root_dir / ".env")
                    self._send_json({
                        "ok": True,
                        "keys": [_build_key_meta(k, idx) for idx, k in enumerate(keys, start=1)],
                        "total": len(keys),
                    })
                    return

                if path == "/api/social-pack":
                    slug = query.get("series", [""])[0]
                    ch = int(query.get("chapter", ["1"])[0])
                    ch_dir = app_state.scanner.projects_dir / slug / f"chapter_{ch:03d}"
                    social_dir = ch_dir / "social"
                    pack_json = social_dir / "social_pack.json"
                    if not pack_json.exists():
                        self._send_json({"exists": False, "series_slug": slug, "chapter": ch})
                        return

                    data = json.loads(pack_json.read_text(encoding="utf-8"))

                    def _to_rel(p_str: Optional[str]) -> Optional[str]:
                        if not p_str:
                            return None
                        p_obj = Path(p_str)
                        if not p_obj.is_absolute():
                            p_obj = (app_state.root_dir / p_obj).resolve()
                        if p_obj.exists():
                            return str(p_obj.relative_to(app_state.root_dir)).replace("\\", "/")
                        return None

                    kit_txt_content = ""
                    kit_p = social_dir / "social_media_kit.txt"
                    if kit_p.exists():
                        kit_txt_content = kit_p.read_text(encoding="utf-8")

                    self._send_json({
                        "exists": True,
                        "series": data.get("series", slug),
                        "series_slug": slug,
                        "chapter": ch,
                        "yt_post_image": _to_rel(data.get("yt_post_image")),
                        "ig_carousel_images": [r for r in (_to_rel(x) for x in data.get("ig_carousel_images", [])) if r],
                        "reel_video": _to_rel(data.get("reel_video")),
                        "kit_txt_content": kit_txt_content,
                        "copy": data.get("copy", {}),
                    })
                    return

                if path == "/api/media":
                    rel_path = query.get("path", [""])[0]
                    if not rel_path:
                        self.send_error(HTTPStatus.BAD_REQUEST, "Missing path parameter")
                        return
                    target = (app_state.root_dir / rel_path).resolve()
                    # Security check: ensure target is inside workspace root
                    if not str(target).startswith(str(app_state.root_dir)):
                        self.send_error(HTTPStatus.FORBIDDEN, "Access denied outside workspace")
                        return
                    self._serve_file(target)
                    return

                if path == "/api/youtube/status":
                    from manhwa_studio.studio_pro.youtube_uploader import (
                        DEFAULT_TOKEN_PATH,
                        load_upload_history,
                        resolve_client_secrets_path,
                    )

                    try:
                        import googleapiclient  # noqa: F401
                        packages_installed = True
                    except ImportError:
                        packages_installed = False

                    secrets_path = resolve_client_secrets_path()
                    token_exists = DEFAULT_TOKEN_PATH.exists()
                    history = load_upload_history()
                    self._send_json({
                        "packages_installed": packages_installed,
                        "client_secrets_found": secrets_path is not None,
                        "token_connected": token_exists,
                        "history": history[-20:][::-1],
                    })
                    return

                if path == "/api/instagram/status":
                    from manhwa_studio.studio_pro.instagram_publisher import (
                        load_instagram_credentials,
                        load_instagram_history,
                        resolve_cloudflared_path,
                    )

                    creds = load_instagram_credentials()
                    history = load_instagram_history()
                    self._send_json({
                        "credentials_configured": creds is not None,
                        "cloudflared_installed": resolve_cloudflared_path() is not None,
                        "history": history[-20:][::-1],
                    })
                    return

                # Serve static frontend files
                if path == "/" or path == "/index.html":
                    self._serve_file(app_state.static_dir / "index.html")
                    return

                static_candidate = (app_state.static_dir / path.lstrip("/")).resolve()
                if str(static_candidate).startswith(str(app_state.static_dir.resolve())) and static_candidate.is_file():
                    self._serve_file(static_candidate)
                    return

                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            try:
                body = self._read_json_body()

                if path == "/api/cloud-gpu/config":
                    from manhwa_studio.dashboard.cloud_worker import (
                        fetch_cloud_worker_health,
                        save_cloud_worker_config,
                    )
                    url = str(body.get("url", "")).strip()
                    token = str(body.get("token", "")).strip()
                    saved = save_cloud_worker_config(app_state.root_dir, url, token)
                    health = fetch_cloud_worker_health(saved["url"], saved["token"], timeout=5.0)
                    self._send_json({
                        "ok": True,
                        "url": saved["url"],
                        "has_token": bool(saved["token"]),
                        **health,
                    })
                    return

                if path == "/api/jobs/enqueue":
                    # Support single job, chained batch, or per-chapter Cloud / Auto-Split expansion
                    batch_specs = body.get("jobs")
                    items_to_enqueue = batch_specs if isinstance(batch_specs, list) else [body]
                    created_jobs = []
                    for item in items_to_enqueue:
                        g_target = str(item.get("gpu_target") or "local").strip().lower()
                        if item.get("action") == "pro-render-range" and g_target in ("cloud", "auto_split"):
                            c_start = int(item.get("chapter_start", 1))
                            c_end = int(item.get("chapter_end", c_start))
                            for offset, ch_num in enumerate(range(c_start, c_end + 1)):
                                per_gpu = "cloud" if (g_target == "cloud" or offset % 2 == 0) else "local"
                                single_payload = {**item, "action": "pro-render", "chapter": ch_num, "gpu_target": per_gpu}
                                spec = build_cli_job_spec(single_payload, root_dir=app_state.root_dir)
                                rec = app_state.queue.enqueue_job(**spec)
                                created_jobs.append(rec.to_dict())
                        else:
                            spec = build_cli_job_spec(item, root_dir=app_state.root_dir)
                            rec = app_state.queue.enqueue_job(**spec)
                            created_jobs.append(rec.to_dict())
                    self._send_json({"ok": True, "jobs": created_jobs})
                    return

                if path == "/api/jobs/preview":
                    spec = build_cli_job_spec(body, root_dir=app_state.root_dir)
                    quoted = [f'"{a}"' if (" " in a or "," in a) else a for a in spec["command_args"]]
                    cmd_str = ".\\.venv\\Scripts\\python -m manhwa_studio.cli " + " ".join(quoted)
                    self._send_json({"ok": True, "spec": spec, "command": cmd_str})
                    return

                if path == "/api/jobs/cancel":
                    job_id = str(body.get("job_id", ""))
                    ok = app_state.queue.cancel_job(job_id)
                    self._send_json({"ok": ok})
                    return

                if path == "/api/jobs/clear":
                    removed = app_state.queue.clear_finished_jobs()
                    self._send_json({"ok": True, "removed": removed})
                    return

                if path == "/api/jobs/settings":
                    if "paused" in body:
                        app_state.queue.paused = bool(body["paused"])
                    if "wait_for_external" in body:
                        app_state.queue.wait_for_external = bool(body["wait_for_external"])
                    self._send_json({
                        "ok": True,
                        "paused": app_state.queue.paused,
                        "wait_for_external": app_state.queue.wait_for_external,
                    })
                    return

                if path == "/api/open-folder":
                    rel_path = str(body.get("path", "")).strip()
                    target = (app_state.root_dir / rel_path).resolve()
                    if str(target).startswith(str(app_state.root_dir)) and target.exists():
                        folder = target if target.is_dir() else target.parent
                        if os.name == "nt":
                            os.startfile(str(folder))
                        self._send_json({"ok": True, "opened": str(folder)})
                    else:
                        self._send_json({"ok": False, "error": "Path does not exist"}, status=404)
                    return

                if path == "/api/manifest/update":
                    series_slug = str(body.get("series_slug", "")).strip()
                    chapter = int(body.get("chapter", 1))
                    updated_scenes = body.get("scenes", [])
                    new_title = body.get("title")
                    m_file = app_state.scanner.projects_dir / series_slug / f"chapter_{chapter:03d}" / "scripts" / "scene_manifest.json"
                    if not m_file.exists():
                        self._send_json({"ok": False, "error": "scene_manifest.json not found"}, status=404)
                        return

                    m_data = json.loads(m_file.read_text(encoding="utf-8"))
                    if new_title:
                        m_data["title"] = str(new_title).strip()

                    scene_lookup = {s.get("scene_id"): s for s in updated_scenes if isinstance(s, dict) and s.get("scene_id")}
                    for sc in m_data.get("scenes", []):
                        sid = sc.get("scene_id")
                        if sid in scene_lookup:
                            patch = scene_lookup[sid]
                            if "speaker" in patch:
                                sc["speaker"] = str(patch["speaker"]).strip()
                            if "narration_text" in patch:
                                sc["narration_text"] = str(patch["narration_text"]).strip()
                                sc["subtitle_text"] = str(patch["narration_text"]).strip()
                            if "motion_preset" in patch:
                                sc["motion_preset"] = str(patch["motion_preset"]).strip()

                    m_data["approved_by_user"] = True
                    tmp_file = m_file.with_suffix(".tmp")
                    tmp_file.write_text(json.dumps(m_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    tmp_file.replace(m_file)
                    self._send_json({"ok": True, "updated_scenes": len(scene_lookup)})
                    return

                if path == "/api/profiles/save":
                    from manhwa_studio.studio_pro.series_manager import SeriesProfile
                    prof_data = body.get("profile") or body
                    prof = SeriesProfile(**prof_data)
                    saved_path = app_state.sm.save_profile(prof)
                    # Also keep global_voice_defaults.yaml dynamically synced with your latest saved Narrator/BGM settings!
                    app_state.sm.save_global_voice_defaults(
                        voice_id=prof.narrator_voice.voice_id,
                        rate=prof.narrator_voice.rate,
                        pitch=prof.narrator_voice.pitch,
                        bgm_ducking_volume=prof.bgm_ducking_volume,
                        bgm_normal_volume=prof.bgm_normal_volume,
                    )
                    self._send_json({"ok": True, "path": str(saved_path), "profile": prof.model_dump()})
                    return

                if path == "/api/profiles/apply-global":
                    from manhwa_studio.studio_pro.series_manager import VoiceSetting
                    voice_id = str(body.get("voice_id") or "gemini:Puck").strip()
                    rate = str(body.get("rate") or "+2%").strip()
                    pitch = str(body.get("pitch") or "+0Hz").strip()
                    bgm_duck = float(body.get("bgm_ducking_volume", 0.12))
                    bgm_norm = float(body.get("bgm_normal_volume", 0.35))
                    app_state.sm.save_global_voice_defaults(
                        voice_id=voice_id,
                        rate=rate,
                        pitch=pitch,
                        bgm_ducking_volume=bgm_duck,
                        bgm_normal_volume=bgm_norm,
                    )
                    updated_count = 0
                    for slug in app_state.sm.list_profiles():
                        p = app_state.sm.load_profile(slug)
                        if p:
                            p.narrator_voice = VoiceSetting(
                                provider="gemini" if voice_id.startswith("gemini:") else "edge-tts",
                                voice_id=voice_id,
                                rate=rate,
                                pitch=pitch,
                                description=f"Main Narrator ({voice_id})",
                            )
                            for r_name, v_cfg in p.character_voices.items():
                                r_low = r_name.lower()
                                is_fem = any(f in r_low for f in ("lady", "girl", "woman", "queen", "alicia", "countess", "mother", "heroine", "nano", "system", "podong", "poby", "duchess", "princess", "maid", "servant", "mun ku", "lady mun", "lady hwa"))
                                if not is_fem:
                                    v_cfg.provider = "gemini" if voice_id.startswith("gemini:") else "edge-tts"
                                    v_cfg.voice_id = voice_id
                                    v_cfg.rate = rate
                                    v_cfg.pitch = pitch
                            p.bgm_ducking_volume = bgm_duck
                            p.bgm_normal_volume = bgm_norm
                            app_state.sm.save_profile(p)
                            updated_count += 1
                    self._send_json({"ok": True, "updated_profiles": updated_count})
                    return

                if path == "/api/series/onboard":
                    series_name = str(body.get("series_name") or "").strip()
                    genre = str(body.get("genre") or "murim").strip()
                    use_ai_cast = bool(body.get("use_ai_cast", True))
                    if not series_name:
                        self._send_json({"ok": False, "error": "Series name is required"}, status=400)
                        return
                    inbox_root = app_state.root_dir / "assets" / "inbox"
                    # Remove existing cached yaml if user explicitly wants to refresh/upgrade cast
                    if body.get("refresh_existing"):
                        slug = app_state.sm._slugify(series_name)
                        existing_yaml = app_state.sm.profiles_dir / f"{slug}.yaml"
                        if existing_yaml.exists():
                            existing_yaml.unlink(missing_ok=True)
                    prof = app_state.sm.onboard_new_series(
                        series_name=series_name,
                        genre=genre,
                        use_ai_cast=use_ai_cast,
                        inbox_root=inbox_root,
                    )
                    self._send_json({
                        "ok": True,
                        "profile": prof.model_dump(),
                        "inbox_path": f"assets/inbox/{series_name}",
                    })
                    return

                if path == "/api/env-config/save":
                    from manhwa_studio.env_config import update_dotenv_values
                    updates = body.get("config") or body
                    updated = update_dotenv_values(updates, env_path=app_state.root_dir / ".env")
                    self._send_json({"ok": True, "config": updated.model_dump()})
                    return

                if path == "/api/gemini-keys/check":
                    env_path = app_state.root_dir / ".env"
                    env_keys = _read_dotenv_gemini_keys(env_path)
                    env_key_set = set(env_keys)

                    mode = str(body.get("mode") or "").strip().lower()
                    raw_keys = body.get("keys")
                    target_key_id = str(body.get("key_id") or "").strip()

                    if target_key_id:
                        candidates = [k for k in env_keys if _key_fingerprint(k) == target_key_id]
                    elif mode == "env" or not raw_keys:
                        candidates = env_keys
                    else:
                        candidates = _parse_key_tokens(raw_keys)

                    if not candidates:
                        self._send_json({"ok": False, "error": "No Gemini API keys provided to test."}, status=400)
                        return

                    # Check keys concurrently so testing 10 keys finishes in ~3-5 seconds
                    max_workers = min(5, max(1, len(candidates)))
                    with ThreadPoolExecutor(max_workers=max_workers) as pool:
                        results = list(
                            pool.map(
                                lambda item: _probe_gemini_key(item[1], index=item[0], env_keys=env_key_set),
                                enumerate(candidates, start=1),
                            )
                        )

                    self._send_json({
                        "ok": True,
                        "results": results,
                        "summary": {
                            "total": len(results),
                            "tts_ready": sum(1 for r in results if r["tts_ready"]),
                            "tts_supported": sum(1 for r in results if r["tts_supported"]),
                            "script_ready": sum(1 for r in results if r["script_ready"]),
                        },
                    })
                    return

                if path == "/api/gemini-keys/add":
                    env_path = app_state.root_dir / ".env"
                    new_tokens = _parse_key_tokens(body.get("keys"))
                    if not new_tokens:
                        self._send_json({"ok": False, "error": "No valid API key string provided."}, status=400)
                        return

                    existing = _read_dotenv_gemini_keys(env_path)
                    combined = list(existing)
                    added_count = 0
                    skipped_count = 0
                    for tok in new_tokens:
                        if tok not in combined:
                            combined.append(tok)
                            added_count += 1
                        else:
                            skipped_count += 1

                    _write_dotenv_gemini_keys(combined, env_path=env_path)
                    self._send_json({
                        "ok": True,
                        "added": added_count,
                        "skipped_duplicates": skipped_count,
                        "keys": [_build_key_meta(k, idx) for idx, k in enumerate(combined, start=1)],
                        "total": len(combined),
                    })
                    return

                if path == "/api/gemini-keys/remove":
                    env_path = app_state.root_dir / ".env"
                    key_id = str(body.get("key_id") or "").strip()
                    if not key_id:
                        self._send_json({"ok": False, "error": "Missing key_id"}, status=400)
                        return

                    existing = _read_dotenv_gemini_keys(env_path)
                    filtered = [k for k in existing if _key_fingerprint(k) != key_id]
                    if len(filtered) == len(existing):
                        self._send_json({"ok": False, "error": "Key not found in .env"}, status=404)
                        return

                    _write_dotenv_gemini_keys(filtered, env_path=env_path)
                    self._send_json({
                        "ok": True,
                        "keys": [_build_key_meta(k, idx) for idx, k in enumerate(filtered, start=1)],
                        "total": len(filtered),
                    })
                    return

                if path == "/api/social-pack/generate":
                    from manhwa_studio.story.script_writer import load_scene_manifest
                    from manhwa_studio.studio_pro.pro_pipeline import ProPipeline
                    from manhwa_studio.studio_pro.social_media_director import SocialMediaDirector

                    series_slug = str(body.get("series_slug") or "").strip()
                    chapter = int(body.get("chapter", 1))
                    overlays = bool(body.get("overlays", True))
                    reel_duration = float(body.get("reel_duration", 45.0))
                    reel_start_raw = body.get("reel_start")
                    reel_start = float(reel_start_raw) if (reel_start_raw is not None and str(reel_start_raw).strip() != "") else None

                    proj_dir = app_state.scanner.projects_dir / series_slug / f"chapter_{chapter:03d}"
                    m_file = proj_dir / "scripts" / "scene_manifest.json"
                    if not m_file.exists():
                        self._send_json({"ok": False, "error": f"scene_manifest.json not found for {series_slug} Ch.{chapter}"}, status=404)
                        return

                    pipeline = ProPipeline(proj_dir)
                    manifest = load_scene_manifest(m_file)
                    director = SocialMediaDirector(pipeline.profile)
                    res = director.build_complete_social_pack(
                        project_dir=proj_dir,
                        manifest=manifest,
                        include_overlays=overlays,
                        reel_duration=reel_duration,
                        reel_start_sec=reel_start,
                    )
                    self._send_json({"ok": True, "result": res})
                    return

                if path == "/api/instagram-guide/regenerate":
                    from manhwa_studio.studio_pro.instagram_exporter import InstagramExporter

                    folder_name = str(body.get("folder") or "").strip()
                    yt_handle = str(body.get("yt_handle") or "").strip()
                    ig_handle = str(body.get("ig_handle") or "").strip()
                    if not folder_name:
                        self._send_json({"ok": False, "error": "Missing folder name"}, status=400)
                        return

                    exporter = InstagramExporter(root_dir=app_state.root_dir)
                    guide_path = exporter.regenerate_guide_for_folder(
                        folder_name=folder_name,
                        yt_handle=yt_handle,
                        ig_handle=ig_handle,
                    )
                    self._send_json({
                        "ok": True,
                        "guide_path": str(guide_path.relative_to(app_state.root_dir)).replace("\\", "/"),
                    })
                    return

                if path == "/api/youtube/preview":
                    from dataclasses import asdict
                    from datetime import datetime as _dt
                    from manhwa_studio.studio_pro.youtube_uploader import (
                        parse_chapter_selection,
                        run_batch_upload,
                    )

                    series_slug = str(body.get("series_slug") or "").strip()
                    if not series_slug:
                        self._send_json({"ok": False, "error": "Missing series_slug"}, status=400)
                        return

                    chapters_str = str(body.get("chapters") or "").strip()
                    ch_list = parse_chapter_selection(chapters_str) if chapters_str else None
                    count = int(body.get("count", 3))
                    speed = float(body.get("speed", 1.25))
                    slots_str = str(body.get("slots") or "10:00,16:00,21:00").strip()
                    slot_list = [s.strip() for s in slots_str.split(",") if s.strip()] if slots_str else None
                    interval_raw = body.get("interval_hours")
                    interval_hours = float(interval_raw) if interval_raw not in (None, "") else None

                    start_raw = str(body.get("start_at") or "").strip()
                    parsed_start = None
                    if start_raw:
                        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                            try:
                                parsed_start = _dt.strptime(start_raw, fmt)
                                break
                            except ValueError:
                                continue

                    results = run_batch_upload(
                        series_slug=series_slug,
                        chapters=ch_list,
                        auto_next=count,
                        speed=speed,
                        slots=slot_list,
                        interval_hours=interval_hours,
                        start_at=parsed_start,
                        skip_uploaded=not bool(body.get("include_uploaded", False)),
                        dry_run=True,
                    )
                    self._send_json({
                        "ok": True,
                        "items": [asdict(r) for r in results],
                    })
                    return

                if path == "/api/youtube/shorts-preview":
                    from dataclasses import asdict
                    from datetime import datetime as _dt
                    from manhwa_studio.studio_pro.youtube_uploader import (
                        parse_chapter_selection,
                        run_shorts_batch_upload,
                    )

                    series_slug = str(body.get("series_slug") or "").strip()
                    if not series_slug:
                        self._send_json({"ok": False, "error": "Missing series_slug"}, status=400)
                        return

                    chapters_str = str(body.get("chapters") or "").strip()
                    ch_list = parse_chapter_selection(chapters_str) if chapters_str else None
                    count = int(body.get("count", 3))
                    duration = float(body.get("duration", 90.0))
                    slots_str = str(body.get("slots") or "12:00,18:00,22:00").strip()
                    slot_list = [s.strip() for s in slots_str.split(",") if s.strip()] if slots_str else None
                    interval_raw = body.get("interval_hours")
                    interval_hours = float(interval_raw) if interval_raw not in (None, "") else None

                    start_raw = str(body.get("start_at") or "").strip()
                    parsed_start = None
                    if start_raw:
                        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                            try:
                                parsed_start = _dt.strptime(start_raw, fmt)
                                break
                            except ValueError:
                                continue

                    results = run_shorts_batch_upload(
                        series_slug=series_slug,
                        chapters=ch_list,
                        auto_next=count,
                        short_duration=duration,
                        slots=slot_list,
                        interval_hours=interval_hours,
                        start_at=parsed_start,
                        skip_uploaded=not bool(body.get("include_uploaded", False)),
                        dry_run=True,
                    )
                    self._send_json({
                        "ok": True,
                        "items": [asdict(r) for r in results],
                    })
                    return

                if path == "/api/youtube/marathon-preview":
                    from dataclasses import asdict
                    from datetime import datetime as _dt
                    from manhwa_studio.studio_pro.youtube_uploader import (
                        discover_marathon_upload_item,
                        run_marathon_upload,
                    )

                    marathon_file = str(body.get("marathon_file") or "").strip()
                    if not marathon_file:
                        self._send_json({"ok": False, "error": "Missing marathon_file"}, status=400)
                        return

                    pub_raw = str(body.get("publish_at") or "").strip()
                    parsed_dt = None
                    if pub_raw:
                        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                            try:
                                parsed_dt = _dt.strptime(pub_raw, fmt)
                                break
                            except ValueError:
                                continue

                    slots_str = str(body.get("slots") or "18:00").strip()
                    slot_list = [s.strip() for s in slots_str.split(",") if s.strip()] if slots_str else None
                    title_index = int(body.get("title_index", 0))

                    m_path = Path(marathon_file)
                    item = discover_marathon_upload_item(m_path, title_index=title_index)
                    results = run_marathon_upload(
                        marathon_path=m_path,
                        publish_at=parsed_dt,
                        slots=slot_list,
                        title_index=title_index,
                        skip_uploaded=not bool(body.get("include_uploaded", False)),
                        dry_run=True,
                    )
                    self._send_json({
                        "ok": True,
                        "items": [asdict(r) for r in results],
                        "timestamps_count": len(item.timestamps),
                        "hashtags": item.hashtags[:10],
                    })
                    return

                if path == "/api/instagram/preview":
                    from dataclasses import asdict
                    from manhwa_studio.studio_pro.instagram_publisher import run_instagram_batch_publish

                    folder = str(body.get("folder") or "").strip()
                    if not folder:
                        self._send_json({"ok": False, "error": "Missing folder"}, status=400)
                        return
                    count = int(body.get("count", 2))
                    results = run_instagram_batch_publish(
                        folder=folder,
                        count=count,
                        skip_published=not bool(body.get("include_published", False)),
                        dry_run=True,
                    )
                    self._send_json({"ok": True, "items": [asdict(r) for r in results]})
                    return

                if path == "/api/voice-preview":
                    import asyncio
                    from manhwa_studio.schemas import SceneItem
                    from manhwa_studio.studio_pro.series_manager import SeriesProfile, VoiceSetting
                    from manhwa_studio.studio_pro.voice_director import VoiceDirector
                    from manhwa_studio.utils.hashing import compute_string_sha256

                    voice_id = str(body.get("voice_id") or "hi-IN-MadhurNeural").strip()
                    rate = str(body.get("rate") or "+6%").strip()
                    pitch = str(body.get("pitch") or "+0Hz").strip()
                    speaker = str(body.get("speaker") or "Narrator").strip()
                    desc = str(body.get("description") or "").strip()
                    sample_text = str(body.get("text") or "").strip()

                    if not sample_text:
                        spk_l = speaker.lower()
                        vid_l = voice_id.lower()
                        if "nano" in spk_l or "system" in spk_l:
                            sample_text = "Warning Master! आपकी body में deadly poison फैल रहा है, इसलिए मैं तुरंत full meridian scan start कर रही हूँ!"
                        elif "cold" in spk_l or "ruthless" in spk_l or "villain" in spk_l or "lord" in spk_l:
                            sample_text = "तेरी हिम्मत कैसे हुई मुझे challenge करने की? आज तेरा और तेरे पूरे Clan का Game Over होने वाला है!"
                        elif "wounded" in spk_l or "pain" in spk_l or "shocked" in spk_l:
                            sample_text = "अरे भाई, ये कौन सी crazy Power है? इसका Aura तो literally next level है!"
                        elif any(f in vid_l for f in ("swara", "aarohi", "neerja", "ava", "emma", "uzma", "kore", "aoede", "zephyr")) or "girl" in spk_l or "lady" in spk_l or "heroine" in spk_l:
                            sample_text = "तुम बिल्कुल tension मत लो, जब तक मैं यहाँ हूँ, कोई तुम्हें touch भी नहीं कर सकता!"
                        else:
                            sample_text = "भाई, जब सबने उम्मीद छोड़ दी थी, तभी एक ऐसी mysterious Power जागी जिसने पूरे Murim World को हिला के रख दिया!"

                    preview_dir = app_state.root_dir / "data" / "voice_previews"
                    preview_dir.mkdir(parents=True, exist_ok=True)

                    is_gemini = voice_id.lower().startswith("gemini:") or voice_id in ("Puck", "Charon", "Fenrir", "Kore", "Aoede", "Zephyr")
                    safe_pitch = "+0Hz" if is_gemini else VoiceDirector._sanitize_human_pitch(voice_id, pitch)
                    cache_key = compute_string_sha256(f"v4_indian_human|{voice_id}|{rate}|{safe_pitch}|{speaker}|{desc}|{sample_text}")[:16]
                    out_mp3 = preview_dir / f"preview_{cache_key}.mp3"

                    if not out_mp3.exists() or out_mp3.stat().st_size < 500:
                        vs = VoiceSetting(
                            provider="gemini" if is_gemini else "edge-tts",
                            voice_id=voice_id,
                            rate=rate,
                            pitch=safe_pitch,
                            description=desc or speaker,
                        )
                        dummy_prof = SeriesProfile(series_name="Preview", series_slug="preview")
                        vd = VoiceDirector(dummy_prof)
                        mock_scene = SceneItem(
                            scene_id="preview",
                            duration=4.0,
                            image_file="preview.webp",
                            speaker=speaker,
                            narration_text=sample_text,
                        )
                        asyncio.run(vd._synthesize_scene_async(mock_scene, out_mp3, vs))

                    rel_audio = str(out_mp3.relative_to(app_state.root_dir)).replace("\\", "/")
                    self._send_json({
                        "ok": True,
                        "audio_path": rel_audio,
                        "speaker": speaker,
                        "voice_id": voice_id,
                        "rate": rate,
                        "pitch": safe_pitch,
                        "text": sample_text,
                    })
                    return

                if path == "/api/clean-temp-segments":
                    import shutil
                    series_slug = str(body.get("series_slug", "")).strip()
                    chapter = body.get("chapter")
                    freed_bytes = 0
                    cleaned_chapters = 0

                    target_dirs: List[Path] = []
                    if series_slug and chapter:
                        target_dirs.append(app_state.scanner.projects_dir / series_slug / f"chapter_{int(chapter):03d}")
                    elif series_slug:
                        s_dir = app_state.scanner.projects_dir / series_slug
                        if s_dir.exists():
                            target_dirs.extend([d for d in s_dir.iterdir() if d.is_dir() and d.name.startswith("chapter_")])
                    else:
                        if app_state.scanner.projects_dir.exists():
                            for s_dir in app_state.scanner.projects_dir.iterdir():
                                if s_dir.is_dir():
                                    target_dirs.extend([d for d in s_dir.iterdir() if d.is_dir() and d.name.startswith("chapter_")])

                    for ch_dir in target_dirs:
                        renders_dir = ch_dir / "renders"
                        if not renders_dir.exists():
                            continue
                        # Only clean if a verified final_video*.mp4 (>50KB) already exists!
                        has_final = any(f.stat().st_size > 50000 for f in renders_dir.glob("final_video*.mp4"))
                        if not has_final:
                            continue

                        ch_freed = 0
                        seg_dir = renders_dir / "segments"
                        if seg_dir.exists():
                            for f in seg_dir.glob("*"):
                                if f.is_file():
                                    ch_freed += f.stat().st_size
                            shutil.rmtree(seg_dir, ignore_errors=True)

                        for raw_name in ("raw_stitched.mp4", "merged_video.mp4"):
                            rp = renders_dir / raw_name
                            if rp.exists():
                                ch_freed += rp.stat().st_size
                                try:
                                    rp.unlink()
                                except Exception:
                                    pass

                        if ch_freed > 0:
                            freed_bytes += ch_freed
                            cleaned_chapters += 1

                    self._send_json({
                        "ok": True,
                        "cleaned_chapters": cleaned_chapters,
                        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
                    })
                    return

                self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)

    return DashboardRequestHandler


def run_dashboard_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    root_dir: Optional[Path] = None,
) -> None:
    """Start the local Manhwa Story Studio Pro Web Dashboard."""
    app_state = DashboardAppState(root_dir=root_dir)
    handler_cls = make_handler_class(app_state)
    server = ThreadingHTTPServer((host, port), handler_cls)
    url = f"http://{host}:{port}"

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _parse_key_tokens(raw: Any) -> List[str]:
    """Parse single, comma-separated, or newline-separated Gemini API key strings."""
    if not raw:
        return []
    parts = raw if isinstance(raw, list) else re.split(r"[\s,;]+", str(raw))
    seen: List[str] = []
    for p in parts:
        tok = str(p).strip().strip("\"'")
        if tok and tok not in seen:
            seen.append(tok)
    return seen


def _read_dotenv_gemini_keys(env_path: Path) -> List[str]:
    """Read comma-separated Gemini keys from `.env` (falling back to `os.environ`)."""
    raw_parts: List[str] = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            k = k.strip()
            if k in ("GEMINI_API_KEY", "GEMINI_API_KEYS") or k.startswith("GEMINI_API_KEY_"):
                raw_parts.append(v.strip().strip("\"'"))
    if not raw_parts:
        for env_k, env_v in sorted(os.environ.items()):
            if env_k in ("GEMINI_API_KEY", "GEMINI_API_KEYS") or env_k.startswith("GEMINI_API_KEY_"):
                if env_v and env_v.strip():
                    raw_parts.append(env_v.strip().strip("\"'"))

    keys: List[str] = []
    for part in raw_parts:
        for k in _parse_key_tokens(part):
            if k not in keys:
                keys.append(k)
    return keys


def _write_dotenv_gemini_keys(keys: List[str], env_path: Path) -> None:
    """Safely persist updated `GEMINI_API_KEY` list into `.env` and refresh `os.environ`."""
    joined = ",".join(keys)
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    new_lines: List[str] = []
    replaced = False
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s and s.split("=", 1)[0].strip() == "GEMINI_API_KEY":
            new_lines.append(f"GEMINI_API_KEY={joined}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"GEMINI_API_KEY={joined}")

    tmp = env_path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    tmp.replace(env_path)
    os.environ["GEMINI_API_KEY"] = joined


def _key_fingerprint(api_key: str) -> str:
    """Return a stable short hash ID for identifying an API key without exposing the secret."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def _mask_api_key(api_key: str) -> str:
    """Return a masked display representation such as `AQ.Ab8RN...mddwqg`."""
    if len(api_key) <= 14:
        return api_key[:4] + "..." + api_key[-3:]
    return f"{api_key[:8]}...{api_key[-6:]}"


def _build_key_meta(api_key: str, index: int) -> Dict[str, Any]:
    """Describe key type and masked identity without exposing the raw secret."""
    key_type = "AI Studio Auth (AQ.)" if api_key.startswith("AQ.") else (
        "Legacy Standard (AIza)" if api_key.startswith("AIza") else "Custom Key"
    )
    return {
        "index": index,
        "key_id": _key_fingerprint(api_key),
        "masked": _mask_api_key(api_key),
        "key_type": key_type,
    }


def _call_gemini_endpoint(model_name: str, api_key: str, payload: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    """Execute one lightweight Gemini REST call and classify status, latency, and error text."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ms = int((time.time() - t0) * 1000)
            return {"status": "ok", "http_code": 200, "ms": ms, "data": data, "detail": "200 OK"}
    except urllib.error.HTTPError as he:
        ms = int((time.time() - t0) * 1000)
        err_msg = he.reason or f"HTTP {he.code}"
        try:
            body_txt = he.read().decode("utf-8", errors="ignore")
            err_json = json.loads(body_txt)
            err_msg = err_json.get("error", {}).get("message") or err_msg
        except Exception:
            pass
        if he.code == 429:
            status = "quota_429"
        elif he.code == 401:
            status = "unauthorized_401"
        elif he.code == 403:
            status = "forbidden_403"
        elif he.code == 404:
            status = "not_found_404"
        else:
            status = f"http_{he.code}"
        return {"status": status, "http_code": he.code, "ms": ms, "data": None, "detail": str(err_msg)[:180]}
    except Exception as exc:
        ms = int((time.time() - t0) * 1000)
        is_to = "timed out" in str(exc).lower()
        return {"status": "timeout" if is_to else "error", "http_code": 0, "ms": ms, "data": None, "detail": str(exc)[:180]}


def _probe_gemini_key(api_key: str, index: int, env_keys: set[str]) -> Dict[str, Any]:
    """
    Live-check a Gemini API key against Google AI Studio for:
    1. TTS (`gemini-2.5-flash-preview-tts`, Puck hi-IN) — the project's exact locked voice model
    2. Script/Text (`gemini-3.5-flash-lite`) — screenplay, hook, and metadata generation
    """
    meta = _build_key_meta(api_key, index)

    tts_payload = {
        "contents": [{"role": "user", "parts": [{"text": "यह सिस्टम बहुत खतरनाक है, जल्दी आगे बढ़ो।"}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "languageCode": "hi-IN",
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Puck"}},
            },
        },
    }
    tts_res = _call_gemini_endpoint("gemini-2.5-flash-preview-tts", api_key, tts_payload, timeout=22)

    tts_ready = False
    tts_supported = False
    tts_model_used = "gemini-2.5-flash-preview-tts"
    tts_detail = tts_res["detail"]
    tts_status = tts_res["status"]

    if tts_res["status"] == "ok" and tts_res["data"]:
        cand = tts_res["data"].get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0]
        audio_b64 = cand.get("inlineData", {}).get("data", "")
        if audio_b64 and len(audio_b64) > 500:
            tts_ready = True
            tts_supported = True
            tts_detail = f"Puck Audio OK ({len(audio_b64):,} b64 chars)"
        else:
            tts_status = "empty_audio"
            tts_detail = "Returned 200 OK without inlineData audio"
    elif tts_res["status"] == "quota_429":
        tts_supported = True
        tts_detail = "TTS Supported (Daily/RPM quota limit reached today)"
    elif tts_res["http_code"] in (400, 403, 404):
        # Also check gemini-3.8-flash-tts so user sees if key supports newer TTS even when 2.5 is restricted
        alt_res = _call_gemini_endpoint("gemini-3.8-flash-tts", api_key, tts_payload, timeout=20)
        if alt_res["status"] == "ok" and alt_res["data"]:
            tts_status = "tts38_only"
            tts_model_used = "gemini-3.8-flash-tts"
            tts_supported = True
            tts_detail = f"2.5 restricted ({tts_res['http_code']}), supports gemini-3.8-flash-tts"

    script_payload = {
        "contents": [{"role": "user", "parts": [{"text": "Hi"}]}],
        "generationConfig": {"maxOutputTokens": 5},
    }
    script_res = _call_gemini_endpoint("gemini-3.5-flash-lite", api_key, script_payload, timeout=15)
    script_ready = script_res["status"] == "ok"
    script_supported = script_ready or script_res["status"] == "quota_429"

    return {
        **meta,
        "already_in_env": api_key in env_keys,
        "tts_status": tts_status,
        "tts_ready": tts_ready,
        "tts_supported": tts_supported,
        "tts_model": tts_model_used,
        "tts_ms": tts_res["ms"],
        "tts_detail": tts_detail,
        "script_status": script_res["status"],
        "script_ready": script_ready,
        "script_supported": script_supported,
        "script_ms": script_res["ms"],
        "script_detail": script_res["detail"],
    }

