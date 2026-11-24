"""
Official Instagram Graph API Auto-Publisher (Reels).

Publishes 1080x1920 (9:16) MP4 parts from `exports/instagram/<folder>/` to an
Instagram Professional (Business/Creator) account via the Meta Graph API.

Because Instagram Graph API requires a public HTTPS `video_url` for container creation,
this module supports:
1. Temporary `cloudflared` quick-tunnel serving a single tokenized local HTTP file
   (free, zero external storage needed; automatically shuts down after publishing).
2. An explicit `--video-base-url` / `IG_VIDEO_BASE_URL` if the user hosts files on R2/S3/CDN.

Tracks published parts in `data/instagram_upload_history.json` to prevent duplicates.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import secrets
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from manhwa_studio.logging_config import get_logger

logger = get_logger("manhwa_studio.pro.instagram_publisher")

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
DEFAULT_IG_CREDS_PATH = Path("config") / "instagram_credentials.json"
DEFAULT_IG_HISTORY_PATH = Path("data") / "instagram_upload_history.json"


@dataclass
class InstagramCredentials:
    ig_user_id: str
    access_token: str


@dataclass
class InstagramUploadItem:
    folder: str
    video_path: Path
    filename: str
    caption: str
    hashtags: List[str] = field(default_factory=list)


@dataclass
class InstagramPublishResult:
    folder: str
    filename: str
    caption_preview: str
    status: str  # "dry_run" | "published" | "failed"
    media_id: Optional[str] = None
    permalink: Optional[str] = None
    error: Optional[str] = None


def load_instagram_credentials(
    creds_path: Path = DEFAULT_IG_CREDS_PATH,
) -> Optional[InstagramCredentials]:
    """Resolve Instagram User ID & Access Token from env, `.env`, or `config/instagram_credentials.json`."""
    ig_user_id = os.environ.get("IG_USER_ID", "").strip()
    access_token = os.environ.get("IG_ACCESS_TOKEN", "").strip()

    if (not ig_user_id or not access_token) and Path(".env").exists():
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k == "IG_USER_ID" and not ig_user_id:
                ig_user_id = v
            elif k == "IG_ACCESS_TOKEN" and not access_token:
                access_token = v

    if (not ig_user_id or not access_token) and creds_path.exists():
        try:
            data = json.loads(creds_path.read_text(encoding="utf-8"))
            ig_user_id = ig_user_id or str(data.get("ig_user_id", "")).strip()
            access_token = access_token or str(data.get("access_token", "")).strip()
        except Exception:
            pass

    if ig_user_id and access_token:
        return InstagramCredentials(ig_user_id=ig_user_id, access_token=access_token)
    return None


def save_instagram_credentials(
    ig_user_id: str,
    access_token: str,
    creds_path: Path = DEFAULT_IG_CREDS_PATH,
) -> Path:
    """Persist Instagram credentials to `config/instagram_credentials.json`."""
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text(
        json.dumps(
            {"ig_user_id": ig_user_id.strip(), "access_token": access_token.strip()},
            indent=2,
        ),
        encoding="utf-8",
    )
    return creds_path


def load_instagram_history(history_path: Path = DEFAULT_IG_HISTORY_PATH) -> List[Dict[str, Any]]:
    if not history_path.exists():
        return []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_instagram_history(
    entry: Dict[str, Any],
    history_path: Path = DEFAULT_IG_HISTORY_PATH,
) -> None:
    history = load_instagram_history(history_path)
    history.append(entry)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def get_published_filenames(
    folder: str,
    history_path: Path = DEFAULT_IG_HISTORY_PATH,
) -> Set[str]:
    """Return filenames already published for `folder`."""
    published: Set[str] = set()
    for row in load_instagram_history(history_path):
        if row.get("folder") == folder and row.get("status") == "published":
            fn = str(row.get("filename", "")).strip()
            if fn:
                published.add(fn)
    return published


def parse_instagram_guide_captions(guide_text: str) -> Dict[str, str]:
    """
    Parse per-part captions from `INSTAGRAM_PUBLISHING_GUIDE.md`.
    Returns mapping `{filename: caption_text}` (and `"__default__"` fallback).
    """
    captions: Dict[str, str] = {}
    # Match sections like `### Part 1: `filename.mp4`` or `## ... `filename.mp4``
    part_blocks = re.split(r"(?m)^#{2,3}\s+", guide_text)
    for block in part_blocks:
        fn_match = re.search(r"`([^`]+\.mp4)`", block)
        code_blocks = re.findall(r"```(?:text|markdown)?\s*\n(.*?)```", block, flags=re.DOTALL)
        if fn_match and code_blocks:
            captions[fn_match.group(1).strip()] = code_blocks[0].strip()
        elif code_blocks and "__default__" not in captions:
            captions["__default__"] = code_blocks[0].strip()

    # Also support `**Caption:**` blocks if no fenced blocks matched
    if not captions:
        hashtags = re.findall(r"#\w+", guide_text)
        tag_str = " ".join(dict.fromkeys(hashtags[:12])) or "#ManhwaInHindi #ManhwaReels #AnimeReels"
        captions["__default__"] = f"🔥 Full Hindi Manhwa Recap! Follow & Subscribe for next part!\n\n{tag_str}"

    return captions


def discover_instagram_upload_items(
    folder: str,
    exports_ig_dir: Optional[Path] = None,
) -> List[InstagramUploadItem]:
    """Discover all `.mp4` Reels in `exports/instagram/<folder>/` with their captions."""
    base = (exports_ig_dir or (Path("exports") / "instagram")) / folder
    if not base.exists():
        raise FileNotFoundError(f"Instagram export folder not found: {base}")

    mp4s = sorted(p for p in base.glob("*.mp4") if p.is_file())
    if not mp4s:
        raise FileNotFoundError(f"No .mp4 files found in {base}")

    guide_path = base / "INSTAGRAM_PUBLISHING_GUIDE.md"
    captions_map: Dict[str, str] = {}
    if guide_path.exists():
        captions_map = parse_instagram_guide_captions(guide_path.read_text(encoding="utf-8"))

    pretty_series = folder.replace("_", " ").title()
    items: List[InstagramUploadItem] = []
    for idx, mp4 in enumerate(mp4s, start=1):
        cap = captions_map.get(mp4.name) or captions_map.get("__default__")
        if not cap:
            clean_tag = re.sub(r"[^A-Za-z0-9]", "", pretty_series)
            cap = (
                f"🔥 {pretty_series} (Part {idx}) — Hindi Manhwa Recap!\n"
                f"Full Episode & Marathon on YouTube! Follow for next part 👇⚔️\n\n"
                f"#{clean_tag} #ManhwaInHindi #ManhwaReels #ManhwaRecap #WebtoonHindi #AnimeReels"
            )
        # Instagram caption max length is 2200 chars
        if len(cap) > 2200:
            cap = cap[:2197].rstrip() + "..."
        hashtags = re.findall(r"#\w+", cap)
        items.append(
            InstagramUploadItem(
                folder=folder,
                video_path=mp4,
                filename=mp4.name,
                caption=cap,
                hashtags=hashtags,
            )
        )
    return items


def _graph_request(
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Execute an HTTP request against the Meta Graph API and return parsed JSON."""
    if method.upper() == "GET" and params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(params)}"
        data_bytes = None
    elif params is not None:
        data_bytes = urllib.parse.urlencode(params).encode("utf-8")
    else:
        data_bytes = None

    req = urllib.request.Request(url, data=data_bytes, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Instagram Graph API HTTP {exc.code}: {err_body}") from exc


def get_instagram_account_info(creds: InstagramCredentials) -> Dict[str, Any]:
    """Verify credentials by fetching the Instagram account username and follower count."""
    return _graph_request(
        "GET",
        f"{GRAPH_API_BASE}/{creds.ig_user_id}",
        params={
            "fields": "id,username,followers_count,media_count",
            "access_token": creds.access_token,
        },
    )


def resolve_cloudflared_path() -> Optional[str]:
    """Find `cloudflared` executable on PATH or common Windows install locations."""
    found = shutil.which("cloudflared")
    if found:
        return found
    win_candidates = [
        Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"),
        Path(r"C:\Program Files\cloudflared\cloudflared.exe"),
    ]
    for cand in win_candidates:
        if cand.exists():
            return str(cand)
    return None


class TemporaryTunnelFileHost:
    """
    Serves a single local MP4 file over a tokenized local HTTP endpoint and exposes it
    via a temporary `cloudflared` quick-tunnel (`https://*.trycloudflare.com`).
    """

    def __init__(self, file_path: Path):
        self.file_path = file_path.resolve()
        self.token = secrets.token_urlsafe(16)
        self._httpd: Optional[socketserver.TCPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._tunnel_proc: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None

    def __enter__(self) -> str:
        cf = resolve_cloudflared_path()
        if not cf:
            raise RuntimeError(
                "cloudflared is not installed. To host local MP4s for Instagram Graph API automatically:\n"
                "  winget install Cloudflare.cloudflared\n"
                "Or pass --video-base-url https://your-bucket-url/ if hosting on R2/S3."
            )

        target_file = self.file_path
        expected_path = f"/media/{self.token}/{urllib.parse.quote(target_file.name)}"

        class SingleFileHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_GET(self) -> None:
                if self.path != expected_path:
                    self.send_error(404)
                    return
                size = target_file.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                with target_file.open("rb") as fh:
                    while True:
                        chunk = fh.read(1024 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)

        self._httpd = socketserver.TCPServer(("127.0.0.1", 0), SingleFileHandler)
        port = self._httpd.server_address[1]
        self._server_thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._server_thread.start()

        self._tunnel_proc = subprocess.Popen(
            [cf, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        deadline = time.time() + 25.0
        base_url = None
        while time.time() < deadline:
            if self._tunnel_proc.poll() is not None:
                break
            line = self._tunnel_proc.stdout.readline() if self._tunnel_proc.stdout else ""
            m = re.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", line)
            if m:
                base_url = m.group(0)
                break

        if not base_url:
            self.__exit__(None, None, None)
            raise RuntimeError("Timed out waiting for cloudflared quick-tunnel URL.")

        self.public_url = f"{base_url}{expected_path}"
        logger.info(f"Temporary tunnel active for {target_file.name}: {base_url}")
        # Brief pause for DNS propagation of the trycloudflare subdomain
        time.sleep(2.5)
        return self.public_url

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._tunnel_proc is not None:
            try:
                self._tunnel_proc.terminate()
                self._tunnel_proc.wait(timeout=5)
            except Exception:
                try:
                    self._tunnel_proc.kill()
                except Exception:
                    pass
            self._tunnel_proc = None
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None


def publish_reel_via_url(
    creds: InstagramCredentials,
    video_url: str,
    caption: str,
    share_to_feed: bool = True,
    poll_interval_sec: float = 5.0,
    max_wait_sec: float = 300.0,
) -> Dict[str, Any]:
    """
    Create an Instagram Reels media container, poll until Instagram finishes fetching/processing,
    and publish it to the account.
    """
    create_resp = _graph_request(
        "POST",
        f"{GRAPH_API_BASE}/{creds.ig_user_id}/media",
        params={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": creds.access_token,
        },
    )
    container_id = create_resp.get("id")
    if not container_id:
        raise RuntimeError(f"Failed to create Instagram media container: {create_resp}")

    logger.info(f"Created Instagram container {container_id}; waiting for processing...")
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        status_resp = _graph_request(
            "GET",
            f"{GRAPH_API_BASE}/{container_id}",
            params={"fields": "status_code,status", "access_token": creds.access_token},
        )
        code = status_resp.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram container {container_id} failed: {status_resp}")
        time.sleep(poll_interval_sec)
    else:
        raise TimeoutError(f"Timed out waiting for Instagram container {container_id} to finish.")

    pub_resp = _graph_request(
        "POST",
        f"{GRAPH_API_BASE}/{creds.ig_user_id}/media_publish",
        params={"creation_id": container_id, "access_token": creds.access_token},
    )
    media_id = pub_resp.get("id")
    permalink = None
    if media_id:
        try:
            info = _graph_request(
                "GET",
                f"{GRAPH_API_BASE}/{media_id}",
                params={"fields": "permalink", "access_token": creds.access_token},
            )
            permalink = info.get("permalink")
        except Exception:
            pass

    return {"media_id": media_id, "permalink": permalink}


def run_instagram_batch_publish(
    folder: str,
    count: int = 3,
    delay_minutes: float = 0.0,
    video_base_url: Optional[str] = None,
    skip_published: bool = True,
    dry_run: bool = False,
    exports_ig_dir: Optional[Path] = None,
    history_path: Path = DEFAULT_IG_HISTORY_PATH,
    creds_path: Path = DEFAULT_IG_CREDS_PATH,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> List[InstagramPublishResult]:
    """
    Publish up to `count` un-published 9:16 Reels from `exports/instagram/<folder>/`.
    Optionally spaces multiple posts by `delay_minutes` between uploads.
    """
    all_items = discover_instagram_upload_items(folder=folder, exports_ig_dir=exports_ig_dir)
    already = get_published_filenames(folder, history_path=history_path) if skip_published else set()
    pending = [it for it in all_items if it.filename not in already][: max(1, count)]

    if not pending:
        logger.info(f"No pending Instagram Reels to publish in '{folder}'.")
        return []

    creds = None
    if not dry_run:
        creds = load_instagram_credentials(creds_path=creds_path)
        if not creds:
            raise RuntimeError(
                "Instagram credentials not found. Set IG_USER_ID and IG_ACCESS_TOKEN in .env "
                "or run `manhwa-studio ig-auth`."
            )

    base_url = (video_base_url or os.environ.get("IG_VIDEO_BASE_URL", "")).strip().rstrip("/")
    results: List[InstagramPublishResult] = []

    for idx, item in enumerate(pending):
        if not dry_run and idx > 0 and delay_minutes > 0:
            logger.info(f"Waiting {delay_minutes:g} min before publishing next Reel ({item.filename})...")
            sleep_fn(delay_minutes * 60.0)

        if dry_run:
            results.append(
                InstagramPublishResult(
                    folder=item.folder,
                    filename=item.filename,
                    caption_preview=item.caption[:140].replace("\n", " "),
                    status="dry_run",
                )
            )
            continue

        try:
            if base_url:
                public_url = f"{base_url}/{urllib.parse.quote(item.folder)}/{urllib.parse.quote(item.filename)}"
                pub = publish_reel_via_url(creds=creds, video_url=public_url, caption=item.caption)
            else:
                with TemporaryTunnelFileHost(item.video_path) as tunnel_url:
                    pub = publish_reel_via_url(creds=creds, video_url=tunnel_url, caption=item.caption)

            res = InstagramPublishResult(
                folder=item.folder,
                filename=item.filename,
                caption_preview=item.caption[:140].replace("\n", " "),
                status="published",
                media_id=pub.get("media_id"),
                permalink=pub.get("permalink"),
            )
            append_instagram_history(
                {
                    "folder": item.folder,
                    "filename": item.filename,
                    "media_id": res.media_id,
                    "permalink": res.permalink,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "status": "published",
                },
                history_path=history_path,
            )
            results.append(res)
        except Exception as exc:
            logger.error(f"Failed to publish {item.filename} to Instagram: {exc}")
            results.append(
                InstagramPublishResult(
                    folder=item.folder,
                    filename=item.filename,
                    caption_preview=item.caption[:140].replace("\n", " "),
                    status="failed",
                    error=str(exc),
                )
            )

    return results

