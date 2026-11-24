"""
YouTube Batch Uploader & Staggered Scheduler.

Automates uploading 2-3+ chapter (or marathon) videos to YouTube with:
- Proper high-CTR Title (<= 100 chars)
- Full SEO Description with Clickable Timeline/Timestamps & Hashtags (<= 5000 chars)
- Targeted Keyword Tags (<= 500 chars total)
- Custom Thumbnail upload (when available)
- Staggered `publishAt` scheduling across different time periods (e.g. 10:00, 16:00, 21:00
  or every N hours)
- Duplicate prevention via `data/youtube_upload_history.json`
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest
from manhwa_studio.studio_pro.series_manager import SeriesManager, SeriesProfile
from manhwa_studio.studio_pro.youtube_kit import YouTubeKitGenerator

logger = get_logger("manhwa_studio.pro.youtube_uploader")

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
]

DEFAULT_TIME_SLOTS = ["10:00", "16:00", "21:00"]
DEFAULT_HISTORY_PATH = Path("data") / "youtube_upload_history.json"
DEFAULT_CLIENT_SECRETS_PATHS = [
    Path("config") / "youtube_client_secrets.json",
    Path("client_secrets.json"),
]
DEFAULT_TOKEN_PATH = Path("config") / "youtube_token.json"


@dataclass
class ParsedYouTubeMetadata:
    """Structured YouTube metadata parsed from a youtube_upload_kit.txt file."""

    titles: List[str] = field(default_factory=list)
    description: str = ""
    tags: List[str] = field(default_factory=list)
    timestamps: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)

    @property
    def primary_title(self) -> str:
        return self.titles[0] if self.titles else ""


@dataclass
class UploadItem:
    """A single video ready for YouTube batch upload & scheduling."""

    series_slug: str
    series_name: str
    chapter: int
    video_path: Path
    thumbnail_path: Optional[Path]
    kit_path: Optional[Path]
    title: str
    description: str
    tags: List[str]
    timestamps: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    title_index: int = 0
    is_marathon: bool = False


@dataclass
class ScheduledUploadResult:
    """Result for one video in a batch upload/schedule run."""

    series_slug: str
    chapter: int
    title: str
    video_path: str
    thumbnail_path: Optional[str]
    publish_at_local: str
    publish_at_utc: str
    status: str  # "dry_run" | "scheduled" | "uploaded" | "failed"
    video_id: Optional[str] = None
    url: Optional[str] = None
    thumbnail_uploaded: bool = False
    error: Optional[str] = None


def truncate_youtube_title(title: str, max_len: int = 100) -> str:
    """Truncate a YouTube title to <= max_len characters on a clean boundary."""
    clean = re.sub(r"\s+", " ", (title or "").strip())
    if len(clean) <= max_len:
        return clean
    clipped = clean[: max_len - 1].rsplit(" ", 1)[0].strip()
    if not clipped:
        clipped = clean[: max_len - 1].strip()
    return f"{clipped}…"


def fit_youtube_tags(tags: Sequence[str], max_total_chars: int = 480) -> List[str]:
    """
    Filter and trim tags so their total YouTube-counted character length stays <= max_total_chars.
    YouTube enforces a 500-character limit across all tags (including commas/quotes for multi-word tags).
    """
    result: List[str] = []
    seen: Set[str] = set()
    used_chars = 0

    for raw in tags:
        t = re.sub(r"\s+", " ", str(raw or "").strip()).strip(",")
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        # YouTube quotes multi-word tags internally; count worst-case cost
        cost = len(t) + (2 if " " in t else 0) + (1 if result else 0)
        if used_chars + cost > max_total_chars:
            continue
        seen.add(key)
        result.append(t)
        used_chars += cost

    return result


def normalize_description(
    description: str,
    series_name: str,
    chapter: int,
    max_len: int = 5000,
) -> str:
    """Ensure description has hashtags, clean spacing, and fits within YouTube's 5000-char limit."""
    desc = (description or "").strip()
    hashtags = re.findall(r"#\w+", desc)
    if not hashtags:
        clean_series = re.sub(r"[^A-Za-z0-9]", "", series_name)
        default_tags = f"#{clean_series} #{clean_series}Chapter{chapter} #ManhwaInHindi #ManhwaRecap #WebtoonHindi"
        desc = f"{desc}\n\n{default_tags}".strip()

    if len(desc) > max_len:
        desc = desc[: max_len - 3].rstrip() + "..."
    return desc


def parse_youtube_kit_text(text: str) -> ParsedYouTubeMetadata:
    """
    Parse a `youtube_upload_kit.txt` file generated by `YouTubeKitGenerator`
    into structured titles, description, timestamps, hashtags, and tags.
    """
    lines = text.splitlines()
    titles: List[str] = []
    desc_lines: List[str] = []
    tags: List[str] = []

    section: Optional[str] = None
    for line in lines:
        stripped = line.strip()

        if "RECOMMENDED HIGH-CTR TITLES" in line or "VIRAL MARATHON TITLES" in line:
            section = "titles"
            continue
        if "THUMBNAIL 2-WORD" in line:
            section = "badges"
            continue
        if "PINNED COMMENT" in line:
            section = "pinned"
            continue
        if "📝 DESCRIPTION" in line or "DESCRIPTION (Copy & paste" in line:
            section = "description"
            continue
        if "🏷️ TAGS" in line or "TAGS (Comma-separated" in line:
            section = "tags"
            continue

        if stripped and set(stripped) <= {"=", "-"}:
            continue

        if section == "titles":
            m = re.match(r"^\d+\)\s*(.+)$", stripped)
            if m:
                titles.append(m.group(1).strip())
        elif section == "description":
            desc_lines.append(line.rstrip())
        elif section == "tags":
            if stripped:
                for t in stripped.split(","):
                    t_clean = t.strip()
                    if t_clean:
                        tags.append(t_clean)

    description = "\n".join(desc_lines).strip()
    timestamps = re.findall(r"^\d{1,2}:\d{2}(?::\d{2})?\s*[-–].+$", description, flags=re.MULTILINE)
    hashtags = re.findall(r"#\w+", description)

    return ParsedYouTubeMetadata(
        titles=titles,
        description=description,
        tags=tags,
        timestamps=timestamps,
        hashtags=hashtags,
    )


_EXCLUDED_VIDEO_TOKENS = (
    "cold_open",
    "short",
    "teaser",
    "9x16",
    "raw_stitched",
    "chapter_body",
    ".tmp.",
)


def _is_full_chapter_video(path: Path) -> bool:
    """Return True if path looks like a full rendered chapter video (not a cold open or short)."""
    name_low = path.name.lower()
    return not any(tok in name_low for tok in _EXCLUDED_VIDEO_TOKENS)


def _find_chapter_video(chapter_dir: Path, speed: float = 1.25) -> Optional[Path]:
    """Locate the best rendered full-chapter MP4 video (never cold_open or shorts)."""
    speed_tag = f"{speed:g}"
    exports_dir = chapter_dir / "exports"
    renders_dir = chapter_dir / "renders"

    candidates: List[Path] = []
    # 1. Exact speed-matched full renders first
    if renders_dir.exists():
        sp_file = renders_dir / f"final_video_{speed_tag}x.mp4"
        if sp_file.exists():
            candidates.append(sp_file)
    if exports_dir.exists():
        candidates.extend(sorted(p for p in exports_dir.glob(f"*{speed_tag}x*.mp4") if _is_full_chapter_video(p)))

    # 2. Pro export / standard final_video
    if exports_dir.exists():
        candidates.extend(sorted(p for p in exports_dir.glob("*_pro.mp4") if _is_full_chapter_video(p)))
    if renders_dir.exists():
        std_file = renders_dir / "final_video.mp4"
        if std_file.exists():
            candidates.append(std_file)

    # 3. Any other full chapter MP4 in exports or renders
    if exports_dir.exists():
        candidates.extend(sorted(p for p in exports_dir.glob("*.mp4") if _is_full_chapter_video(p)))
    if renders_dir.exists():
        candidates.extend(sorted(p for p in renders_dir.glob("*.mp4") if _is_full_chapter_video(p)))

    for cand in candidates:
        if cand.exists() and cand.is_file() and _is_full_chapter_video(cand):
            return cand
    return None


def _find_chapter_thumbnail(chapter_dir: Path) -> Optional[Path]:
    """Locate the best thumbnail image for a chapter."""
    reports_dir = chapter_dir / "reports"
    exports_dir = chapter_dir / "exports"

    candidates: List[Path] = [
        reports_dir / "pro_thumbnail.jpg",
        reports_dir / "pro_thumbnail.png",
        reports_dir / "thumbnail_16x9.jpg",
        reports_dir / "thumbnail.jpg",
    ]
    if exports_dir.exists():
        candidates.extend(sorted(exports_dir.glob("*thumbnail*.jpg")))
        candidates.extend(sorted(exports_dir.glob("*thumbnail*.png")))

    for cand in candidates:
        if cand.exists() and cand.is_file():
            return cand
    return None


def _load_series_profile(series_slug: str) -> SeriesProfile:
    """Load SeriesProfile or build a sensible fallback profile."""
    mgr = SeriesManager()
    profile = mgr.load_profile(series_slug)
    if profile:
        return profile
    pretty_name = series_slug.replace("_", " ").title()
    return SeriesProfile(series_name=pretty_name, series_slug=series_slug)


def discover_chapter_upload_item(
    series_slug: str,
    chapter_num: int,
    speed: float = 1.25,
    title_index: int = 0,
    projects_base_dir: Optional[Path] = None,
    auto_generate_kit: bool = True,
) -> UploadItem:
    """
    Discover video, thumbnail, and YouTube metadata for a single chapter.
    Automatically generates `youtube_upload_kit.txt` from `scene_manifest.json` if missing.
    """
    base_dir = projects_base_dir or (Path("data") / "projects")
    chapter_dir = base_dir / series_slug / f"chapter_{chapter_num:03d}"
    if not chapter_dir.exists():
        raise FileNotFoundError(f"Chapter directory not found: {chapter_dir}")

    video_path = _find_chapter_video(chapter_dir, speed=speed)
    if not video_path:
        raise FileNotFoundError(
            f"No rendered MP4 video found for {series_slug} chapter {chapter_num} in {chapter_dir}"
        )

    profile = _load_series_profile(series_slug)
    thumbnail_path = _find_chapter_thumbnail(chapter_dir)

    kit_candidates = [
        chapter_dir / "reports" / "youtube_upload_kit.txt",
        chapter_dir / "exports" / f"{series_slug}_ch{chapter_num:03d}_youtube_kit.txt",
    ]
    kit_path = next((k for k in kit_candidates if k.exists()), None)

    if kit_path is None and auto_generate_kit:
        manifest_path = chapter_dir / "scripts" / "scene_manifest.json"
        if manifest_path.exists():
            manifest = SceneManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            kit_out = chapter_dir / "reports" / "youtube_upload_kit.txt"
            kit_gen = YouTubeKitGenerator(profile)
            kit_path = kit_gen.build_youtube_kit(manifest, kit_out, speed=speed)

    parsed = ParsedYouTubeMetadata()
    if kit_path and kit_path.exists():
        parsed = parse_youtube_kit_text(kit_path.read_text(encoding="utf-8"))

    # Select title
    if parsed.titles:
        idx = min(max(0, title_index), len(parsed.titles) - 1)
        raw_title = parsed.titles[idx]
    else:
        raw_title = f"{profile.series_name} Chapter {chapter_num} Full Story Explained in Hindi | Manhwa Recap"

    title = truncate_youtube_title(raw_title, max_len=100)
    description = normalize_description(
        parsed.description
        or f"🔥 {profile.series_name} - Chapter {chapter_num} Full Story Explained in Hindi!\n\n📌 Timestamps:\n00:00 - Chapter {chapter_num}: The Beginning",
        series_name=profile.series_name,
        chapter=chapter_num,
    )
    tags = fit_youtube_tags(
        parsed.tags
        or [
            f"{profile.series_name.lower()} hindi",
            f"{profile.series_name.lower()} chapter {chapter_num}",
            "manhwa recap hindi",
            "manhwa in hindi",
        ]
    )

    timestamps = re.findall(r"^\d{1,2}:\d{2}(?::\d{2})?\s*[-–].+$", description, flags=re.MULTILINE)
    hashtags = re.findall(r"#\w+", description)

    return UploadItem(
        series_slug=series_slug,
        series_name=profile.series_name,
        chapter=chapter_num,
        video_path=video_path,
        thumbnail_path=thumbnail_path,
        kit_path=kit_path,
        title=title,
        description=description,
        tags=tags,
        timestamps=timestamps,
        hashtags=hashtags,
        title_index=title_index,
        is_marathon=False,
    )


def list_available_chapters(
    series_slug: str,
    speed: float = 1.25,
    projects_base_dir: Optional[Path] = None,
) -> List[int]:
    """Return sorted chapter numbers that have a rendered MP4 video ready for upload."""
    base_dir = projects_base_dir or (Path("data") / "projects")
    series_dir = base_dir / series_slug
    if not series_dir.exists():
        return []

    chapters: List[int] = []
    for ch_dir in sorted(series_dir.glob("chapter_*")):
        m = re.match(r"chapter_(\d+)$", ch_dir.name)
        if not m:
            continue
        if _find_chapter_video(ch_dir, speed=speed) is not None:
            chapters.append(int(m.group(1)))
    return sorted(chapters)


def parse_chapter_selection(chapters_expr: str) -> List[int]:
    """
    Parse a chapter expression like '1,2,3' or '1-3' or '1-2,5' into sorted unique ints.
    """
    result: Set[int] = set()
    for part in (chapters_expr or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-", 1)
            start, end = int(bounds[0].strip()), int(bounds[1].strip())
            if end < start:
                start, end = end, start
            for c in range(start, end + 1):
                result.add(c)
        else:
            result.add(int(part))
    return sorted(result)


def compute_publish_schedule(
    count: int,
    slots: Optional[Sequence[str]] = None,
    interval_hours: Optional[float] = None,
    start_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    min_lead_minutes: int = 15,
) -> List[datetime]:
    """
    Compute `count` staggered local timezone-aware publish datetimes.

    Two modes:
    1) `interval_hours` is set: schedules at `start_at`, `start_at + interval_hours`, ...
    2) `slots` (e.g. ["10:00", "16:00", "21:00"]): picks upcoming daily slots in order,
       rolling over to subsequent days as needed.
    """
    if count <= 0:
        return []

    local_tz = datetime.now().astimezone().tzinfo
    ref_now = now.astimezone(local_tz) if now else datetime.now(local_tz)
    earliest = ref_now + timedelta(minutes=min_lead_minutes)

    if interval_hours is not None and interval_hours > 0:
        if start_at is not None:
            cursor = start_at if start_at.tzinfo else start_at.replace(tzinfo=local_tz)
        else:
            # Default: round up to next 15-min mark at least 30 min from now
            base = ref_now + timedelta(minutes=30)
            minute_bucket = ((base.minute // 15) + 1) * 15
            cursor = base.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minute_bucket)

        if cursor < earliest:
            cursor = earliest

        schedule: List[datetime] = []
        step = timedelta(hours=float(interval_hours))
        for i in range(count):
            schedule.append(cursor + i * step)
        return schedule

    # Time-of-day slots mode
    raw_slots = list(slots) if slots else list(DEFAULT_TIME_SLOTS)
    parsed_hm: List[Tuple[int, int]] = []
    for s in raw_slots:
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(s))
        if not m:
            raise ValueError(f"Invalid time slot '{s}'. Expected HH:MM (24-hour format, e.g. 10:00, 16:00, 21:00).")
        hh, mm = int(m.group(1)), int(m.group(2))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(f"Time slot out of range: '{s}'")
        parsed_hm.append((hh, mm))
    parsed_hm.sort()

    base_date = (start_at.astimezone(local_tz) if (start_at and start_at.tzinfo) else (start_at.replace(tzinfo=local_tz) if start_at else ref_now)).date()

    schedule = []
    day_offset = 0
    while len(schedule) < count:
        cur_date = base_date + timedelta(days=day_offset)
        for hh, mm in parsed_hm:
            candidate = datetime(cur_date.year, cur_date.month, cur_date.day, hh, mm, 0, tzinfo=local_tz)
            if candidate >= earliest:
                schedule.append(candidate)
                if len(schedule) >= count:
                    break
        day_offset += 1
        if day_offset > 365:
            raise RuntimeError("Could not compute publish schedule within 365 days.")

    return schedule


def format_utc_iso(dt: datetime) -> str:
    """Format a datetime as ISO-8601 UTC string required by YouTube Data API v3 `publishAt`."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_upload_history(history_path: Path = DEFAULT_HISTORY_PATH) -> List[Dict[str, Any]]:
    """Load the JSON upload history list."""
    if not history_path.exists():
        return []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_upload_history(entry: Dict[str, Any], history_path: Path = DEFAULT_HISTORY_PATH) -> None:
    """Append a single upload record to `data/youtube_upload_history.json`."""
    history = load_upload_history(history_path)
    history.append(entry)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def get_uploaded_chapters(
    series_slug: str,
    history_path: Path = DEFAULT_HISTORY_PATH,
    video_type: str = "full",
) -> Set[int]:
    """Return set of chapter numbers already uploaded/scheduled for `series_slug` and `video_type` ('full' or 'short')."""
    history = load_upload_history(history_path)
    uploaded: Set[int] = set()
    for row in history:
        row_type = row.get("video_type") or "full"
        if (
            row.get("series_slug") == series_slug
            and row_type == video_type
            and row.get("status") in ("scheduled", "uploaded", "public")
        ):
            try:
                uploaded.add(int(row["chapter"]))
            except (KeyError, TypeError, ValueError):
                continue
    return uploaded


def resolve_client_secrets_path(explicit_path: Optional[Path] = None) -> Optional[Path]:
    """Locate YouTube OAuth2 client_secrets.json from arg, env, or default config paths."""
    if explicit_path and explicit_path.exists():
        return explicit_path
    env_val = os.environ.get("YOUTUBE_CLIENT_SECRETS")
    if env_val and Path(env_val).exists():
        return Path(env_val)
    for cand in DEFAULT_CLIENT_SECRETS_PATHS:
        if cand.exists():
            return cand
    return None


def _import_google_youtube_clients():
    """Lazily import Google API client libraries with a clear install message if missing."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        return Request, Credentials, InstalledAppFlow, build, MediaFileUpload
    except ImportError as exc:
        raise RuntimeError(
            "YouTube API packages are not installed. Run:\n"
            "  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        ) from exc


def authenticate_youtube(
    client_secrets_path: Optional[Path] = None,
    token_path: Path = DEFAULT_TOKEN_PATH,
):
    """
    Authenticate with YouTube Data API v3 using OAuth 2.0 and return an authorized `youtube` service.
    Reuses and refreshes `config/youtube_token.json` when available.
    """
    Request, Credentials, InstalledAppFlow, build, _ = _import_google_youtube_clients()

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), YOUTUBE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secrets_file = resolve_client_secrets_path(client_secrets_path)
            if not secrets_file:
                raise FileNotFoundError(
                    "YouTube OAuth client_secrets.json not found.\n"
                    "Download OAuth 2.0 Desktop App credentials from Google Cloud Console and save as:\n"
                    "  config/youtube_client_secrets.json"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_file), YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.info(f"Saved YouTube OAuth token to {token_path}")

    return build("youtube", "v3", credentials=creds)


def get_authenticated_channel_info(youtube) -> Dict[str, Any]:
    """Fetch basic channel id and title for the authenticated YouTube account."""
    resp = youtube.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        return {}
    ch = items[0]
    return {
        "id": ch.get("id"),
        "title": ch.get("snippet", {}).get("title"),
        "subscribers": ch.get("statistics", {}).get("subscriberCount"),
    }


def upload_single_video(
    youtube,
    item: UploadItem,
    publish_at_utc: Optional[str] = None,
    privacy_status: str = "private",
    category_id: str = "24",
    language: str = "hi",
    playlist_id: Optional[str] = None,
    made_for_kids: bool = False,
) -> Dict[str, Any]:
    """
    Upload one video to YouTube with resumable upload, optional scheduled `publishAt`,
    custom thumbnail, and optional playlist insertion.
    """
    _, _, _, _, MediaFileUpload = _import_google_youtube_clients()

    status_body: Dict[str, Any] = {
        "privacyStatus": "private" if publish_at_utc else privacy_status,
        "selfDeclaredMadeForKids": made_for_kids,
    }
    if publish_at_utc:
        status_body["publishAt"] = publish_at_utc

    body = {
        "snippet": {
            "title": item.title,
            "description": item.description,
            "tags": item.tags,
            "categoryId": category_id,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": status_body,
    }

    media = MediaFileUpload(
        str(item.video_path),
        mimetype="video/mp4",
        chunksize=8 * 1024 * 1024,
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    logger.info(f"Uploading Ch.{item.chapter}: '{item.title}' ({item.video_path.name})...")
    response = None
    retries = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.info(f"  Upload progress Ch.{item.chapter}: {pct}%")
        except Exception as exc:
            retries += 1
            if retries > 4:
                raise
            wait_s = min(30, 2 ** retries)
            logger.warning(f"  Transient upload error ({exc}); retrying in {wait_s}s...")
            time.sleep(wait_s)

    video_id = response["id"]
    video_url = f"https://youtu.be/{video_id}"
    logger.info(f"Uploaded Ch.{item.chapter} -> {video_url} (publishAt={publish_at_utc or privacy_status})")

    thumb_ok = False
    if item.thumbnail_path and item.thumbnail_path.exists():
        try:
            thumb_media = MediaFileUpload(str(item.thumbnail_path), mimetype="image/jpeg")
            youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
            thumb_ok = True
            logger.info(f"  Set custom thumbnail: {item.thumbnail_path.name}")
        except Exception as exc:
            logger.warning(f"  Thumbnail upload skipped/failed for {video_id}: {exc}")

    if playlist_id:
        try:
            youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            logger.info(f"  Added {video_id} to playlist {playlist_id}")
        except Exception as exc:
            logger.warning(f"  Playlist insert failed for {video_id}: {exc}")

    return {
        "video_id": video_id,
        "url": video_url,
        "thumbnail_uploaded": thumb_ok,
    }


def _find_chapter_short_video(
    series_slug: str,
    chapter_num: int,
    chapter_dir: Path,
    social_base_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Locate a vertical 9:16 YouTube Short / Reel MP4 for a chapter."""
    exports_dir = chapter_dir / "exports"
    social_dir = (social_base_dir or (Path("exports") / "social")) / series_slug / f"chapter_{chapter_num:03d}"

    candidates: List[Path] = []
    if exports_dir.exists():
        candidates.extend(sorted(exports_dir.glob("*_short_9x16.mp4")))
        candidates.extend(sorted(exports_dir.glob("*short*.mp4")))
    if social_dir.exists():
        candidates.extend(sorted(social_dir.glob("*reel*.mp4")))
        candidates.extend(sorted(social_dir.glob("*short*.mp4")))
        candidates.extend(sorted(social_dir.glob("*.mp4")))

    for cand in candidates:
        if cand.exists() and cand.is_file() and ".tmp." not in cand.name:
            return cand
    return None


def list_available_short_chapters(
    series_slug: str,
    projects_base_dir: Optional[Path] = None,
    social_base_dir: Optional[Path] = None,
    include_generatable: bool = True,
    speed: float = 1.25,
) -> List[int]:
    """
    Return sorted chapter numbers that have a vertical 9:16 Short/Reel MP4 ready
    (or, when `include_generatable=True`, have a rendered full video that can be auto-converted).
    """
    base_dir = projects_base_dir or (Path("data") / "projects")
    series_dir = base_dir / series_slug
    chapters: Set[int] = set()

    if series_dir.exists():
        for ch_dir in sorted(series_dir.glob("chapter_*")):
            m = re.match(r"chapter_(\d+)$", ch_dir.name)
            if m:
                ch_num = int(m.group(1))
                if _find_chapter_short_video(series_slug, ch_num, ch_dir, social_base_dir) is not None:
                    chapters.add(ch_num)
                elif include_generatable and _find_chapter_video(ch_dir, speed=speed) is not None:
                    chapters.add(ch_num)

    s_dir = (social_base_dir or (Path("exports") / "social")) / series_slug
    if s_dir.exists():
        for ch_dir in sorted(s_dir.glob("chapter_*")):
            m = re.match(r"chapter_(\d+)$", ch_dir.name)
            if m and any(ch_dir.glob("*.mp4")):
                chapters.add(int(m.group(1)))

    return sorted(chapters)


def discover_chapter_short_item(
    series_slug: str,
    chapter_num: int,
    title_index: int = 0,
    speed: float = 1.25,
    short_duration: float = 90.0,
    projects_base_dir: Optional[Path] = None,
    social_base_dir: Optional[Path] = None,
    auto_generate_kit: bool = True,
    auto_generate_short: bool = True,
    dry_run: bool = False,
) -> UploadItem:
    """
    Discover a 9:16 Short video and build Shorts-optimized Title, Description, Hashtags, and Tags.
    If no 9:16 Short exists yet and `auto_generate_short=True`, auto-generates a 9:16 Short
    (default 90s, up to 175s) from the chapter's rendered video via `SocialMediaDirector.build_vertical_reel_video()`.
    """
    base_dir = projects_base_dir or (Path("data") / "projects")
    chapter_dir = base_dir / series_slug / f"chapter_{chapter_num:03d}"
    profile = _load_series_profile(series_slug)

    video_path = _find_chapter_short_video(series_slug, chapter_num, chapter_dir, social_base_dir)
    if not video_path:
        full_video = _find_chapter_video(chapter_dir, speed=speed) if chapter_dir.exists() else None
        if not (auto_generate_short and full_video):
            raise FileNotFoundError(
                f"No 9:16 Short/Reel MP4 (or full rendered video to auto-generate from) found for {series_slug} chapter {chapter_num}."
            )

        planned_out = chapter_dir / "exports" / f"{series_slug}_ch{chapter_num:03d}_short_9x16.mp4"
        if dry_run:
            video_path = planned_out
        else:
            from manhwa_studio.studio_pro.social_media_director import SocialMediaDirector

            manifest_path = chapter_dir / "scripts" / "scene_manifest.json"
            manifest = (
                SceneManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists()
                else SceneManifest(series=profile.series_name, chapter=chapter_num, scenes=[])
            )
            logger.info(f"No 9:16 Short found for Ch.{chapter_num}; auto-generating from {full_video.name}...")
            smd = SocialMediaDirector(profile)
            video_path = smd.build_vertical_reel_video(
                source_video=full_video,
                output_reel_mp4=planned_out,
                manifest=manifest,
                speed=speed,
                clip_duration=short_duration,
            )
    kit_candidates = [
        chapter_dir / "reports" / "youtube_upload_kit.txt",
        chapter_dir / "exports" / f"{series_slug}_ch{chapter_num:03d}_youtube_kit.txt",
    ]
    kit_path = next((k for k in kit_candidates if k.exists()), None)

    if kit_path is None and auto_generate_kit and chapter_dir.exists():
        manifest_path = chapter_dir / "scripts" / "scene_manifest.json"
        if manifest_path.exists():
            manifest = SceneManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            kit_out = chapter_dir / "reports" / "youtube_upload_kit.txt"
            kit_path = YouTubeKitGenerator(profile).build_youtube_kit(manifest, kit_out, speed=1.25)

    parsed = ParsedYouTubeMetadata()
    if kit_path and kit_path.exists():
        parsed = parse_youtube_kit_text(kit_path.read_text(encoding="utf-8"))

    if parsed.titles:
        idx = min(max(0, title_index), len(parsed.titles) - 1)
        base_title = parsed.titles[idx].split("|")[0].strip()
    else:
        base_title = f"{profile.series_name} Ch {chapter_num} Epic Moment!"

    title = truncate_youtube_title(f"{base_title} #Shorts", max_len=100)

    clean_series = re.sub(r"[^A-Za-z0-9]", "", profile.series_name)
    hashtags_list = [
        "#Shorts",
        "#YouTubeShorts",
        f"#{clean_series}",
        f"#{clean_series}Ch{chapter_num}",
        "#ManhwaShorts",
        "#ManhwaInHindi",
        "#ManhwaRecap",
        "#AnimeShorts",
    ]
    desc = (
        f"⚡ {profile.series_name} - Chapter {chapter_num} (Hindi Recap Short)\n\n"
        f"🔥 Full Chapter {chapter_num} aur Marathon Movie dekhne ke liye Channel ko SUBSCRIBE karein!\n"
        f"Comment me batayein aapka favorite scene kaunsa tha 👇⚔️\n\n"
        + " ".join(hashtags_list)
    )
    description = normalize_description(desc, series_name=profile.series_name, chapter=chapter_num)
    tags = fit_youtube_tags(
        [
            "shorts",
            "youtube shorts",
            f"{profile.series_name.lower()} shorts",
            f"{profile.series_name.lower()} ch {chapter_num} hindi",
            "manhwa shorts hindi",
            "manhwa recap shorts",
            "manhwa in hindi",
            "anime shorts hindi",
        ]
        + parsed.tags
    )

    return UploadItem(
        series_slug=series_slug,
        series_name=profile.series_name,
        chapter=chapter_num,
        video_path=video_path,
        thumbnail_path=None,  # YouTube Shorts use auto-selected frames
        kit_path=kit_path,
        title=title,
        description=description,
        tags=tags,
        timestamps=[],
        hashtags=hashtags_list,
        title_index=title_index,
        is_marathon=False,
    )


def _execute_batch_upload(
    items: List[UploadItem],
    series_slug: str,
    video_type: str,
    slots: Optional[Sequence[str]] = None,
    interval_hours: Optional[float] = None,
    start_at: Optional[datetime] = None,
    category_id: str = "24",
    language: str = "hi",
    playlist_id: Optional[str] = None,
    dry_run: bool = False,
    client_secrets_path: Optional[Path] = None,
    token_path: Path = DEFAULT_TOKEN_PATH,
    history_path: Path = DEFAULT_HISTORY_PATH,
) -> List[ScheduledUploadResult]:
    """Shared scheduler + upload + history + report runner for full videos and Shorts."""
    schedule_local = compute_publish_schedule(
        count=len(items),
        slots=slots,
        interval_hours=interval_hours,
        start_at=start_at,
    )

    youtube = None
    if not dry_run:
        youtube = authenticate_youtube(client_secrets_path=client_secrets_path, token_path=token_path)

    results: List[ScheduledUploadResult] = []
    for item, pub_local in zip(items, schedule_local):
        pub_utc = format_utc_iso(pub_local)
        pub_local_str = pub_local.strftime("%Y-%m-%d %H:%M %Z")

        if dry_run:
            results.append(
                ScheduledUploadResult(
                    series_slug=item.series_slug,
                    chapter=item.chapter,
                    title=item.title,
                    video_path=str(item.video_path),
                    thumbnail_path=str(item.thumbnail_path) if item.thumbnail_path else None,
                    publish_at_local=pub_local_str,
                    publish_at_utc=pub_utc,
                    status="dry_run",
                )
            )
            continue

        try:
            up = upload_single_video(
                youtube=youtube,
                item=item,
                publish_at_utc=pub_utc,
                category_id=category_id,
                language=language,
                playlist_id=playlist_id,
            )
            res = ScheduledUploadResult(
                series_slug=item.series_slug,
                chapter=item.chapter,
                title=item.title,
                video_path=str(item.video_path),
                thumbnail_path=str(item.thumbnail_path) if item.thumbnail_path else None,
                publish_at_local=pub_local_str,
                publish_at_utc=pub_utc,
                status="scheduled",
                video_id=up["video_id"],
                url=up["url"],
                thumbnail_uploaded=up["thumbnail_uploaded"],
            )
            append_upload_history(
                {
                    "series_slug": item.series_slug,
                    "series_name": item.series_name,
                    "chapter": item.chapter,
                    "video_type": video_type,
                    "video_id": up["video_id"],
                    "url": up["url"],
                    "title": item.title,
                    "publish_at_local": pub_local_str,
                    "publish_at_utc": pub_utc,
                    "status": "scheduled",
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "video_path": str(item.video_path),
                },
                history_path=history_path,
            )
            results.append(res)
        except Exception as exc:
            logger.error(f"Failed to upload Ch.{item.chapter} ({video_type}): {exc}")
            results.append(
                ScheduledUploadResult(
                    series_slug=item.series_slug,
                    chapter=item.chapter,
                    title=item.title,
                    video_path=str(item.video_path),
                    thumbnail_path=str(item.thumbnail_path) if item.thumbnail_path else None,
                    publish_at_local=pub_local_str,
                    publish_at_utc=pub_utc,
                    status="failed",
                    error=str(exc),
                )
            )

    plan_dir = Path("exports") / "youtube"
    plan_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "shorts_batch" if video_type == "short" else "batch"
    plan_file = plan_dir / f"{series_slug}_{suffix}_{stamp}.json"
    plan_file.write_text(
        json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"Saved YouTube {suffix} schedule report to {plan_file}")
    return results


def run_batch_upload(
    series_slug: str,
    chapters: Optional[Sequence[int]] = None,
    auto_next: int = 3,
    speed: float = 1.25,
    slots: Optional[Sequence[str]] = None,
    interval_hours: Optional[float] = None,
    start_at: Optional[datetime] = None,
    title_index: int = 0,
    category_id: str = "24",
    language: str = "hi",
    playlist_id: Optional[str] = None,
    skip_uploaded: bool = True,
    dry_run: bool = False,
    client_secrets_path: Optional[Path] = None,
    token_path: Path = DEFAULT_TOKEN_PATH,
    history_path: Path = DEFAULT_HISTORY_PATH,
    projects_base_dir: Optional[Path] = None,
) -> List[ScheduledUploadResult]:
    """
    Discover 2-3+ full chapter videos, build/load their YouTube SEO kits (Title, Description,
    Timeline, Hashtags, Tags), assign staggered publish times, and upload (or dry-run).
    """
    already_uploaded = get_uploaded_chapters(series_slug, history_path, video_type="full") if skip_uploaded else set()

    if chapters:
        target_chapters = [c for c in chapters if c not in already_uploaded]
    else:
        available = list_available_chapters(series_slug, speed=speed, projects_base_dir=projects_base_dir)
        pending = [c for c in available if c not in already_uploaded]
        target_chapters = pending[: max(1, auto_next)]

    if not target_chapters:
        logger.info(f"No pending chapters to upload for '{series_slug}'.")
        return []

    items = [
        discover_chapter_upload_item(
            series_slug=series_slug,
            chapter_num=ch,
            speed=speed,
            title_index=title_index,
            projects_base_dir=projects_base_dir,
        )
        for ch in target_chapters
    ]
    return _execute_batch_upload(
        items=items,
        series_slug=series_slug,
        video_type="full",
        slots=slots,
        interval_hours=interval_hours,
        start_at=start_at,
        category_id=category_id,
        language=language,
        playlist_id=playlist_id,
        dry_run=dry_run,
        client_secrets_path=client_secrets_path,
        token_path=token_path,
        history_path=history_path,
    )


def _parse_marathon_filename(marathon_path: Path) -> Tuple[str, int, int]:
    """Extract (series_slug, ch_start, ch_end) from a marathon MP4 filename."""
    stem = marathon_path.stem
    m = re.match(r"^(.+?)_(?:marathon_)?ch(\d+)_to_ch(\d+)", stem, flags=re.IGNORECASE)
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3))
    m2 = re.match(r"^(.+?)_ch(\d+)", stem, flags=re.IGNORECASE)
    if m2:
        ch = int(m2.group(2))
        return m2.group(1), ch, ch
    return stem, 1, 1


def _parse_raw_timestamps_file(text: str) -> List[Tuple[str, str]]:
    """Extract (MM:SS or HH:MM:SS, label) pairs from a `.timestamps.txt` file."""
    pairs: List[Tuple[str, str]] = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–]\s*(.+?)\s*$", line)
        if m:
            pairs.append((m.group(1), m.group(2)))
    return pairs


def is_marathon_uploaded(marathon_path: Path, history_path: Path = DEFAULT_HISTORY_PATH) -> bool:
    """Return True if this marathon filename has already been uploaded/scheduled."""
    history = load_upload_history(history_path)
    target_name = marathon_path.name
    for row in history:
        if row.get("video_type") == "marathon" and row.get("status") in ("scheduled", "uploaded", "public"):
            recorded = Path(str(row.get("video_path", ""))).name
            if recorded == target_name:
                return True
    return False


def discover_marathon_upload_item(
    marathon_path: Path,
    series_slug: Optional[str] = None,
    title_index: int = 0,
    projects_base_dir: Optional[Path] = None,
    auto_generate_kit: bool = True,
) -> UploadItem:
    """
    Discover a compiled Marathon MP4 and build/parse its viral Title, SEO Description,
    Clickable Timeline Timestamps, Hashtags, Tags, and Thumbnail.
    """
    if not marathon_path.exists():
        raise FileNotFoundError(f"Marathon video not found: {marathon_path}")

    parsed_slug, ch_start, ch_end = _parse_marathon_filename(marathon_path)
    slug = series_slug or parsed_slug
    profile = _load_series_profile(slug)

    thumb_candidates: List[Path] = [
        marathon_path.with_suffix(".jpg"),
        marathon_path.with_suffix(".png"),
    ]
    thumbs_dir = Path("exports") / "thumbnails"
    if thumbs_dir.exists():
        thumb_candidates.extend(sorted(thumbs_dir.glob(f"*{slug}*youtube_thumbnail*.jpg")))
        thumb_candidates.extend(sorted(thumbs_dir.glob(f"*{slug}*thumbnail*.jpg")))
    base_dir = projects_base_dir or (Path("data") / "projects")
    thumb_candidates.append(base_dir / slug / f"chapter_{ch_start:03d}" / "reports" / "pro_thumbnail.jpg")
    thumbnail_path = next((t for t in thumb_candidates if t.exists() and t.is_file()), None)

    kit_candidates = [
        marathon_path.with_suffix(".youtube_kit.txt"),
        marathon_path.with_suffix(".timestamps.txt"),
    ]
    kit_path = next((k for k in kit_candidates if k.exists() and k.is_file()), None)

    parsed = ParsedYouTubeMetadata()
    if kit_path is not None:
        raw_text = kit_path.read_text(encoding="utf-8")
        if "VIRAL MARATHON TITLES" in raw_text or "RECOMMENDED HIGH-CTR TITLES" in raw_text:
            parsed = parse_youtube_kit_text(raw_text)
        else:
            ts_pairs = _parse_raw_timestamps_file(raw_text)
            if auto_generate_kit:
                kit_out = marathon_path.with_suffix(".youtube_kit.txt")
                kit_gen = YouTubeKitGenerator(profile)
                kit_path = kit_gen.build_marathon_youtube_kit(
                    chapter_nums=list(range(ch_start, ch_end + 1)),
                    timestamps=ts_pairs,
                    output_txt_file=kit_out,
                )
                parsed = parse_youtube_kit_text(kit_path.read_text(encoding="utf-8"))

    if kit_path is None and auto_generate_kit:
        kit_out = marathon_path.with_suffix(".youtube_kit.txt")
        kit_gen = YouTubeKitGenerator(profile)
        kit_path = kit_gen.build_marathon_youtube_kit(
            chapter_nums=list(range(ch_start, ch_end + 1)),
            timestamps=[("00:00", f"Chapter {ch_start}: The Story Begins 🔥")],
            output_txt_file=kit_out,
        )
        parsed = parse_youtube_kit_text(kit_path.read_text(encoding="utf-8"))

    if parsed.titles:
        idx = min(max(0, title_index), len(parsed.titles) - 1)
        raw_title = parsed.titles[idx]
    else:
        raw_title = f"Sabne Use Kamzor Samjha Par Wo Asli Demon Nikla! 🔥 | {profile.series_name} Ch {ch_start}–{ch_end} Full Movie in Hindi"

    title = truncate_youtube_title(raw_title, max_len=100)
    description = normalize_description(
        parsed.description
        or f"🔥 {profile.series_name} (Chapters {ch_start} to {ch_end}) Full Movie Explained in Hindi | Manhwa Marathon",
        series_name=profile.series_name,
        chapter=ch_start,
    )
    tags = fit_youtube_tags(
        parsed.tags
        or [
            f"{profile.series_name.lower()} full movie in hindi",
            f"{profile.series_name.lower()} chapter {ch_start} to {ch_end} in hindi",
            "manhwa full movie in hindi",
            "manhwa marathon hindi",
            "manhwa recap in hindi",
        ]
    )
    timestamps = re.findall(r"^\d{1,2}:\d{2}(?::\d{2})?\s*[-–].+$", description, flags=re.MULTILINE)
    hashtags = re.findall(r"#\w+", description)

    return UploadItem(
        series_slug=slug,
        series_name=profile.series_name,
        chapter=ch_start,
        video_path=marathon_path,
        thumbnail_path=thumbnail_path,
        kit_path=kit_path,
        title=title,
        description=description,
        tags=tags,
        timestamps=timestamps,
        hashtags=hashtags,
        title_index=title_index,
        is_marathon=True,
    )


def run_marathon_upload(
    marathon_path: Path,
    series_slug: Optional[str] = None,
    publish_at: Optional[datetime] = None,
    slots: Optional[Sequence[str]] = None,
    title_index: int = 0,
    category_id: str = "24",
    language: str = "hi",
    playlist_id: Optional[str] = None,
    skip_uploaded: bool = True,
    dry_run: bool = False,
    client_secrets_path: Optional[Path] = None,
    token_path: Path = DEFAULT_TOKEN_PATH,
    history_path: Path = DEFAULT_HISTORY_PATH,
    projects_base_dir: Optional[Path] = None,
) -> List[ScheduledUploadResult]:
    """Upload and schedule a single compiled Marathon Movie MP4 with full SEO Kit & Timestamps."""
    if skip_uploaded and is_marathon_uploaded(marathon_path, history_path=history_path):
        logger.info(f"Marathon '{marathon_path.name}' is already in upload history; skipping.")
        return []

    item = discover_marathon_upload_item(
        marathon_path=marathon_path,
        series_slug=series_slug,
        title_index=title_index,
        projects_base_dir=projects_base_dir,
    )
    return _execute_batch_upload(
        items=[item],
        series_slug=item.series_slug,
        video_type="marathon",
        slots=slots or ["18:00"],
        interval_hours=1.0 if publish_at is not None else None,
        start_at=publish_at,
        category_id=category_id,
        language=language,
        playlist_id=playlist_id,
        dry_run=dry_run,
        client_secrets_path=client_secrets_path,
        token_path=token_path,
        history_path=history_path,
    )


def _parse_marathon_filename(marathon_path: Path) -> Tuple[str, int, int]:
    """Extract (series_slug, ch_start, ch_end) from a marathon MP4 filename."""
    stem = marathon_path.stem
    m = re.match(r"^(.+?)_(?:marathon_)?ch(\d+)_to_ch(\d+)", stem, flags=re.IGNORECASE)
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3))
    m2 = re.match(r"^(.+?)_ch(\d+)", stem, flags=re.IGNORECASE)
    if m2:
        ch = int(m2.group(2))
        return m2.group(1), ch, ch
    return stem, 1, 1


def _parse_raw_timestamps_file(text: str) -> List[Tuple[str, str]]:
    """Extract (MM:SS or HH:MM:SS, label) pairs from a `.timestamps.txt` file."""
    pairs: List[Tuple[str, str]] = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–]\s*(.+?)\s*$", line)
        if m:
            pairs.append((m.group(1), m.group(2)))
    return pairs


def is_marathon_uploaded(marathon_path: Path, history_path: Path = DEFAULT_HISTORY_PATH) -> bool:
    """Return True if this marathon filename has already been uploaded/scheduled."""
    history = load_upload_history(history_path)
    target_name = marathon_path.name
    for row in history:
        if row.get("video_type") == "marathon" and row.get("status") in ("scheduled", "uploaded", "public"):
            recorded = Path(str(row.get("video_path", ""))).name
            if recorded == target_name:
                return True
    return False


def discover_marathon_upload_item(
    marathon_path: Path,
    series_slug: Optional[str] = None,
    title_index: int = 0,
    projects_base_dir: Optional[Path] = None,
    auto_generate_kit: bool = True,
) -> UploadItem:
    """
    Discover a compiled Marathon MP4 and build/parse its viral Title, SEO Description,
    Clickable Timeline Timestamps, Hashtags, Tags, and Thumbnail.
    """
    if not marathon_path.exists():
        raise FileNotFoundError(f"Marathon video not found: {marathon_path}")

    parsed_slug, ch_start, ch_end = _parse_marathon_filename(marathon_path)
    slug = series_slug or parsed_slug
    profile = _load_series_profile(slug)

    thumb_candidates: List[Path] = [
        marathon_path.with_suffix(".jpg"),
        marathon_path.with_suffix(".png"),
    ]
    thumbs_dir = Path("exports") / "thumbnails"
    if thumbs_dir.exists():
        thumb_candidates.extend(sorted(thumbs_dir.glob(f"*{slug}*youtube_thumbnail*.jpg")))
        thumb_candidates.extend(sorted(thumbs_dir.glob(f"*{slug}*thumbnail*.jpg")))
    base_dir = projects_base_dir or (Path("data") / "projects")
    thumb_candidates.append(base_dir / slug / f"chapter_{ch_start:03d}" / "reports" / "pro_thumbnail.jpg")
    thumbnail_path = next((t for t in thumb_candidates if t.exists() and t.is_file()), None)

    kit_candidates = [
        marathon_path.with_suffix(".youtube_kit.txt"),
        marathon_path.with_suffix(".timestamps.txt"),
    ]
    kit_path = next((k for k in kit_candidates if k.exists() and k.is_file()), None)

    parsed = ParsedYouTubeMetadata()
    if kit_path is not None:
        raw_text = kit_path.read_text(encoding="utf-8")
        if "VIRAL MARATHON TITLES" in raw_text or "RECOMMENDED HIGH-CTR TITLES" in raw_text:
            parsed = parse_youtube_kit_text(raw_text)
        else:
            ts_pairs = _parse_raw_timestamps_file(raw_text)
            if auto_generate_kit:
                kit_out = marathon_path.with_suffix(".youtube_kit.txt")
                kit_gen = YouTubeKitGenerator(profile)
                kit_path = kit_gen.build_marathon_youtube_kit(
                    chapter_nums=list(range(ch_start, ch_end + 1)),
                    timestamps=ts_pairs,
                    output_txt_file=kit_out,
                )
                parsed = parse_youtube_kit_text(kit_path.read_text(encoding="utf-8"))

    if kit_path is None and auto_generate_kit:
        kit_out = marathon_path.with_suffix(".youtube_kit.txt")
        kit_gen = YouTubeKitGenerator(profile)
        kit_path = kit_gen.build_marathon_youtube_kit(
            chapter_nums=list(range(ch_start, ch_end + 1)),
            timestamps=[("00:00", f"Chapter {ch_start}: The Story Begins 🔥")],
            output_txt_file=kit_out,
        )
        parsed = parse_youtube_kit_text(kit_path.read_text(encoding="utf-8"))

    if parsed.titles:
        idx = min(max(0, title_index), len(parsed.titles) - 1)
        raw_title = parsed.titles[idx]
    else:
        raw_title = f"Sabne Use Kamzor Samjha Par Wo Asli Demon Nikla! 🔥 | {profile.series_name} Ch {ch_start}–{ch_end} Full Movie in Hindi"

    title = truncate_youtube_title(raw_title, max_len=100)
    description = normalize_description(
        parsed.description
        or f"🔥 {profile.series_name} (Chapters {ch_start} to {ch_end}) Full Movie Explained in Hindi | Manhwa Marathon",
        series_name=profile.series_name,
        chapter=ch_start,
    )
    tags = fit_youtube_tags(
        parsed.tags
        or [
            f"{profile.series_name.lower()} full movie in hindi",
            f"{profile.series_name.lower()} chapter {ch_start} to {ch_end} in hindi",
            "manhwa full movie in hindi",
            "manhwa marathon hindi",
            "manhwa recap in hindi",
        ]
    )
    timestamps = re.findall(r"^\d{1,2}:\d{2}(?::\d{2})?\s*[-–].+$", description, flags=re.MULTILINE)
    hashtags = re.findall(r"#\w+", description)

    return UploadItem(
        series_slug=slug,
        series_name=profile.series_name,
        chapter=ch_start,
        video_path=marathon_path,
        thumbnail_path=thumbnail_path,
        kit_path=kit_path,
        title=title,
        description=description,
        tags=tags,
        timestamps=timestamps,
        hashtags=hashtags,
        title_index=title_index,
        is_marathon=True,
    )


def run_marathon_upload(
    marathon_path: Path,
    series_slug: Optional[str] = None,
    publish_at: Optional[datetime] = None,
    slots: Optional[Sequence[str]] = None,
    title_index: int = 0,
    category_id: str = "24",
    language: str = "hi",
    playlist_id: Optional[str] = None,
    skip_uploaded: bool = True,
    dry_run: bool = False,
    client_secrets_path: Optional[Path] = None,
    token_path: Path = DEFAULT_TOKEN_PATH,
    history_path: Path = DEFAULT_HISTORY_PATH,
    projects_base_dir: Optional[Path] = None,
) -> List[ScheduledUploadResult]:
    """Upload and schedule a single compiled Marathon Movie MP4 with full SEO Kit & Timestamps."""
    if skip_uploaded and is_marathon_uploaded(marathon_path, history_path=history_path):
        logger.info(f"Marathon '{marathon_path.name}' is already in upload history; skipping.")
        return []

    item = discover_marathon_upload_item(
        marathon_path=marathon_path,
        series_slug=series_slug,
        title_index=title_index,
        projects_base_dir=projects_base_dir,
    )
    return _execute_batch_upload(
        items=[item],
        series_slug=item.series_slug,
        video_type="marathon",
        slots=slots or ["18:00"],
        interval_hours=1.0 if publish_at is not None else None,
        start_at=publish_at,
        category_id=category_id,
        language=language,
        playlist_id=playlist_id,
        dry_run=dry_run,
        client_secrets_path=client_secrets_path,
        token_path=token_path,
        history_path=history_path,
    )


def run_shorts_batch_upload(
    series_slug: str,
    chapters: Optional[Sequence[int]] = None,
    auto_next: int = 3,
    short_duration: float = 90.0,
    slots: Optional[Sequence[str]] = None,
    interval_hours: Optional[float] = None,
    start_at: Optional[datetime] = None,
    title_index: int = 0,
    category_id: str = "24",
    language: str = "hi",
    playlist_id: Optional[str] = None,
    skip_uploaded: bool = True,
    dry_run: bool = False,
    client_secrets_path: Optional[Path] = None,
    token_path: Path = DEFAULT_TOKEN_PATH,
    history_path: Path = DEFAULT_HISTORY_PATH,
    projects_base_dir: Optional[Path] = None,
    social_base_dir: Optional[Path] = None,
) -> List[ScheduledUploadResult]:
    """
    Discover 2-3+ vertical 9:16 YouTube Shorts, build Shorts-optimized Title/Description/Hashtags,
    assign staggered publish times, and upload (or dry-run).
    """
    already_uploaded = get_uploaded_chapters(series_slug, history_path, video_type="short") if skip_uploaded else set()

    if chapters:
        target_chapters = [c for c in chapters if c not in already_uploaded]
    else:
        available = list_available_short_chapters(
            series_slug, projects_base_dir=projects_base_dir, social_base_dir=social_base_dir
        )
        pending = [c for c in available if c not in already_uploaded]
        target_chapters = pending[: max(1, auto_next)]

    if not target_chapters:
        logger.info(f"No pending YouTube Shorts found to upload for '{series_slug}'.")
        return []

    items = [
        discover_chapter_short_item(
            series_slug=series_slug,
            chapter_num=ch,
            title_index=title_index,
            short_duration=short_duration,
            projects_base_dir=projects_base_dir,
            social_base_dir=social_base_dir,
            dry_run=dry_run,
        )
        for ch in target_chapters
    ]
    return _execute_batch_upload(
        items=items,
        series_slug=series_slug,
        video_type="short",
        slots=slots,
        interval_hours=interval_hours,
        start_at=start_at,
        category_id=category_id,
        language=language,
        playlist_id=playlist_id,
        dry_run=dry_run,
        client_secrets_path=client_secrets_path,
        token_path=token_path,
        history_path=history_path,
    )


def _parse_marathon_filename(marathon_path: Path) -> Tuple[str, int, int]:
    """Extract (series_slug, ch_start, ch_end) from a marathon MP4 filename."""
    stem = marathon_path.stem
    m = re.match(r"^(.+?)_(?:marathon_)?ch(\d+)_to_ch(\d+)", stem, flags=re.IGNORECASE)
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3))
    m2 = re.match(r"^(.+?)_ch(\d+)", stem, flags=re.IGNORECASE)
    if m2:
        ch = int(m2.group(2))
        return m2.group(1), ch, ch
    return stem, 1, 1


def _parse_raw_timestamps_file(text: str) -> List[Tuple[str, str]]:
    """Extract (MM:SS or HH:MM:SS, label) pairs from a `.timestamps.txt` file."""
    pairs: List[Tuple[str, str]] = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–]\s*(.+?)\s*$", line)
        if m:
            pairs.append((m.group(1), m.group(2)))
    return pairs


def is_marathon_uploaded(marathon_path: Path, history_path: Path = DEFAULT_HISTORY_PATH) -> bool:
    """Return True if this marathon filename has already been uploaded/scheduled."""
    history = load_upload_history(history_path)
    target_name = marathon_path.name
    for row in history:
        if row.get("video_type") == "marathon" and row.get("status") in ("scheduled", "uploaded", "public"):
            recorded = Path(str(row.get("video_path", ""))).name
            if recorded == target_name:
                return True
    return False


def discover_marathon_upload_item(
    marathon_path: Path,
    series_slug: Optional[str] = None,
    title_index: int = 0,
    projects_base_dir: Optional[Path] = None,
    auto_generate_kit: bool = True,
) -> UploadItem:
    """
    Discover a compiled Marathon MP4 and build/parse its viral Title, SEO Description,
    Clickable Timeline Timestamps, Hashtags, Tags, and Thumbnail.
    """
    if not marathon_path.exists():
        raise FileNotFoundError(f"Marathon video not found: {marathon_path}")

    parsed_slug, ch_start, ch_end = _parse_marathon_filename(marathon_path)
    slug = series_slug or parsed_slug
    profile = _load_series_profile(slug)

    thumb_candidates: List[Path] = [
        marathon_path.with_suffix(".jpg"),
        marathon_path.with_suffix(".png"),
    ]
    thumbs_dir = Path("exports") / "thumbnails"
    if thumbs_dir.exists():
        thumb_candidates.extend(sorted(thumbs_dir.glob(f"*{slug}*youtube_thumbnail*.jpg")))
        thumb_candidates.extend(sorted(thumbs_dir.glob(f"*{slug}*thumbnail*.jpg")))
    base_dir = projects_base_dir or (Path("data") / "projects")
    thumb_candidates.append(base_dir / slug / f"chapter_{ch_start:03d}" / "reports" / "pro_thumbnail.jpg")
    thumbnail_path = next((t for t in thumb_candidates if t.exists() and t.is_file()), None)

    kit_candidates = [
        marathon_path.with_suffix(".youtube_kit.txt"),
        marathon_path.with_suffix(".timestamps.txt"),
    ]
    kit_path = next((k for k in kit_candidates if k.exists() and k.is_file()), None)

    parsed = ParsedYouTubeMetadata()
    if kit_path is not None:
        raw_text = kit_path.read_text(encoding="utf-8")
        if "VIRAL MARATHON TITLES" in raw_text or "RECOMMENDED HIGH-CTR TITLES" in raw_text:
            parsed = parse_youtube_kit_text(raw_text)
        else:
            ts_pairs = _parse_raw_timestamps_file(raw_text)
            if auto_generate_kit:
                kit_out = marathon_path.with_suffix(".youtube_kit.txt")
                kit_gen = YouTubeKitGenerator(profile)
                kit_path = kit_gen.build_marathon_youtube_kit(
                    chapter_nums=list(range(ch_start, ch_end + 1)),
                    timestamps=ts_pairs,
                    output_txt_file=kit_out,
                )
                parsed = parse_youtube_kit_text(kit_path.read_text(encoding="utf-8"))

    if kit_path is None and auto_generate_kit:
        kit_out = marathon_path.with_suffix(".youtube_kit.txt")
        kit_gen = YouTubeKitGenerator(profile)
        kit_path = kit_gen.build_marathon_youtube_kit(
            chapter_nums=list(range(ch_start, ch_end + 1)),
            timestamps=[("00:00", f"Chapter {ch_start}: The Story Begins 🔥")],
            output_txt_file=kit_out,
        )
        parsed = parse_youtube_kit_text(kit_path.read_text(encoding="utf-8"))

    if parsed.titles:
        idx = min(max(0, title_index), len(parsed.titles) - 1)
        raw_title = parsed.titles[idx]
    else:
        raw_title = f"Sabne Use Kamzor Samjha Par Wo Asli Demon Nikla! 🔥 | {profile.series_name} Ch {ch_start}–{ch_end} Full Movie in Hindi"

    title = truncate_youtube_title(raw_title, max_len=100)
    description = normalize_description(
        parsed.description
        or f"🔥 {profile.series_name} (Chapters {ch_start} to {ch_end}) Full Movie Explained in Hindi | Manhwa Marathon",
        series_name=profile.series_name,
        chapter=ch_start,
    )
    tags = fit_youtube_tags(
        parsed.tags
        or [
            f"{profile.series_name.lower()} full movie in hindi",
            f"{profile.series_name.lower()} chapter {ch_start} to {ch_end} in hindi",
            "manhwa full movie in hindi",
            "manhwa marathon hindi",
            "manhwa recap in hindi",
        ]
    )
    timestamps = re.findall(r"^\d{1,2}:\d{2}(?::\d{2})?\s*[-–].+$", description, flags=re.MULTILINE)
    hashtags = re.findall(r"#\w+", description)

    return UploadItem(
        series_slug=slug,
        series_name=profile.series_name,
        chapter=ch_start,
        video_path=marathon_path,
        thumbnail_path=thumbnail_path,
        kit_path=kit_path,
        title=title,
        description=description,
        tags=tags,
        timestamps=timestamps,
        hashtags=hashtags,
        title_index=title_index,
        is_marathon=True,
    )


def run_marathon_upload(
    marathon_path: Path,
    series_slug: Optional[str] = None,
    publish_at: Optional[datetime] = None,
    slots: Optional[Sequence[str]] = None,
    title_index: int = 0,
    category_id: str = "24",
    language: str = "hi",
    playlist_id: Optional[str] = None,
    skip_uploaded: bool = True,
    dry_run: bool = False,
    client_secrets_path: Optional[Path] = None,
    token_path: Path = DEFAULT_TOKEN_PATH,
    history_path: Path = DEFAULT_HISTORY_PATH,
    projects_base_dir: Optional[Path] = None,
) -> List[ScheduledUploadResult]:
    """Upload and schedule a single compiled Marathon Movie MP4 with full SEO Kit & Timestamps."""
    if skip_uploaded and is_marathon_uploaded(marathon_path, history_path=history_path):
        logger.info(f"Marathon '{marathon_path.name}' is already in upload history; skipping.")
        return []

    item = discover_marathon_upload_item(
        marathon_path=marathon_path,
        series_slug=series_slug,
        title_index=title_index,
        projects_base_dir=projects_base_dir,
    )
    return _execute_batch_upload(
        items=[item],
        series_slug=item.series_slug,
        video_type="marathon",
        slots=slots or ["18:00"],
        interval_hours=1.0 if publish_at is not None else None,
        start_at=publish_at,
        category_id=category_id,
        language=language,
        playlist_id=playlist_id,
        dry_run=dry_run,
        client_secrets_path=client_secrets_path,
        token_path=token_path,
        history_path=history_path,
    )
