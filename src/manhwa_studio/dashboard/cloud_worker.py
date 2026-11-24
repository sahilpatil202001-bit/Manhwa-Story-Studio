"""
Remote Cloud GPU Render Worker (Server + Client) for Manhwa Story Studio Pro.

Run on Google Colab Pro (T4 / L4 GPU) behind a free `cloudflared` tunnel:
    python -m manhwa_studio.dashboard.cloud_worker --port 8766

Your local Windows Dashboard connects to this worker to:
  1. Monitor live Colab GPU telemetry (GPU name, VRAM, GPU %, RAM, Disk Free, Uptime,
     and automatic session/disk limit warnings).
  2. Offload individual chapter Pro Renders (1 job at a time on the Cloud GPU) while
     your local PC stays at 0% GPU — OR run 1 chapter on Cloud T4 + 1 on Local GPU in parallel.
  3. Automatically sync rendered `.mp4` exports, thumbnails, YouTube kits, and newly
     auto-cast locked character voices (`registry.json`) back to your local workspace.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

# ---------------------------------------------------------------------------
# Telemetry & Limit Detection (Runs on Colab GPU)
# ---------------------------------------------------------------------------

_WORKER_START_TS = time.time()


def collect_gpu_and_system_telemetry() -> Dict[str, Any]:
    """Collect live NVIDIA GPU, RAM, Disk, and Colab session uptime telemetry + limit warnings."""
    info: Dict[str, Any] = {
        "gpu_available": False,
        "gpu_name": "Unknown",
        "vram_used_mb": 0,
        "vram_total_mb": 0,
        "gpu_util_pct": 0,
        "gpu_temp_c": 0,
        "disk_free_gb": 0.0,
        "disk_total_gb": 0.0,
        "ram_used_gb": 0.0,
        "ram_total_gb": 0.0,
        "uptime_minutes": round((time.time() - _WORKER_START_TS) / 60.0, 1),
        "warnings": [],
    }

    # 1. NVIDIA GPU via nvidia-smi
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().splitlines()[0].split(",")]
            if len(parts) >= 5:
                info["gpu_available"] = True
                info["gpu_name"] = parts[0]
                info["vram_used_mb"] = int(float(parts[1]))
                info["vram_total_mb"] = int(float(parts[2]))
                info["gpu_util_pct"] = int(float(parts[3]))
                info["gpu_temp_c"] = int(float(parts[4]))
    except Exception:
        pass

    # 2. Disk usage
    try:
        du = shutil.disk_usage(Path.cwd())
        info["disk_free_gb"] = round(du.free / (1024 ** 3), 2)
        info["disk_total_gb"] = round(du.total / (1024 ** 3), 2)
    except Exception:
        pass

    # 3. Linux /proc/meminfo RAM
    try:
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            vals: Dict[str, int] = {}
            for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    num = v.strip().split()[0]
                    if num.isdigit():
                        vals[k.strip()] = int(num)
            total_kb = vals.get("MemTotal", 0)
            avail_kb = vals.get("MemAvailable", vals.get("MemFree", 0))
            if total_kb > 0:
                info["ram_total_gb"] = round(total_kb / (1024 ** 2), 2)
                info["ram_used_gb"] = round((total_kb - avail_kb) / (1024 ** 2), 2)
    except Exception:
        pass

    # 4. Automatic Limit / Reset Warnings
    warnings: List[str] = []
    if not info["gpu_available"]:
        warnings.append("GPU unavailable or disconnected — check Colab Runtime -> Change runtime type -> T4 GPU.")
    if info["disk_free_gb"] > 0 and info["disk_free_gb"] < 3.5:
        warnings.append(f"Low Colab disk space ({info['disk_free_gb']} GB free) — stop & reset runtime soon.")
    if info["uptime_minutes"] >= 600:  # 10+ hours
        warnings.append(f"Session running {info['uptime_minutes']/60:.1f}h — approaching Colab 12h max session limit.")
    if info["vram_total_mb"] > 0 and (info["vram_used_mb"] / info["vram_total_mb"]) > 0.92:
        warnings.append("VRAM >92% full — wait for current render to finish before queueing another.")
    info["warnings"] = warnings
    return info


# ---------------------------------------------------------------------------
# Cloud Worker HTTP Server (Runs on Colab T4/L4)
# ---------------------------------------------------------------------------

class CloudWorkerState:
    def __init__(self, root_dir: Path, token: str):
        self.root_dir = root_dir.resolve()
        self.token = token
        self._lock = threading.RLock()
        self.active_job_id: Optional[str] = None
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.jobs_completed: int = 0
        self.work_root = self.root_dir / "_cloud_worker_jobs"
        self.work_root.mkdir(parents=True, exist_ok=True)


def run_cloud_worker_server(host: str = "0.0.0.0", port: int = 8766, token: Optional[str] = None) -> None:
    """Start the Cloud GPU Render Worker HTTP server on Colab."""
    auth_token = (token or os.environ.get("STUDIO_CLOUD_TOKEN") or "").strip()
    if not auth_token:
        auth_token = secrets.token_hex(12)

    state = CloudWorkerState(Path.cwd(), auth_token)

    class WorkerHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass

        def _check_auth(self) -> bool:
            provided = (self.headers.get("X-Cloud-Token") or "").strip()
            return bool(provided) and secrets.compare_digest(provided, state.token)

        def _send_json(self, data: Any, status: int = HTTPStatus.OK) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if not self._check_auth():
                self._send_json({"ok": False, "error": "Unauthorized (invalid X-Cloud-Token)"}, HTTPStatus.UNAUTHORIZED)
                return

            if self.path == "/health":
                telem = collect_gpu_and_system_telemetry()
                with state._lock:
                    active_id = state.active_job_id
                    active_title = state.jobs[active_id]["title"] if (active_id and active_id in state.jobs) else None
                    done_count = state.jobs_completed
                self._send_json({
                    "ok": True,
                    "busy": active_id is not None,
                    "active_job_id": active_id,
                    "active_job_title": active_title,
                    "jobs_completed": done_count,
                    **telem,
                })
                return

            if self.path.startswith("/job/") and self.path.endswith("/download"):
                job_id = self.path.split("/")[2]
                with state._lock:
                    job = state.jobs.get(job_id)
                if not job or job.get("status") != "succeeded":
                    self._send_json({"ok": False, "error": "Job artifact not ready"}, HTTPStatus.NOT_FOUND)
                    return
                zip_path = Path(job["result_zip"])
                if not zip_path.exists():
                    self._send_json({"ok": False, "error": "Result zip missing"}, HTTPStatus.NOT_FOUND)
                    return
                file_size = zip_path.stat().st_size
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(file_size))
                self.end_headers()
                try:
                    with open(zip_path, "rb") as zf_in:
                        while True:
                            chunk = zf_in.read(1024 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    # Clean up job temp folder only after full streamed transfer succeeds
                    job_dir = Path(job["job_dir"])
                    threading.Thread(
                        target=lambda p=job_dir: (time.sleep(2.0), shutil.rmtree(p, ignore_errors=True)),
                        daemon=True,
                    ).start()
                except Exception:
                    pass
                return

            if self.path.startswith("/job/"):
                job_id = self.path.split("/")[2]
                with state._lock:
                    job = state.jobs.get(job_id)
                    if not job:
                        self._send_json({"ok": False, "error": "Unknown job_id"}, HTTPStatus.NOT_FOUND)
                        return
                    payload = {
                        "ok": True,
                        "job_id": job_id,
                        "status": job["status"],
                        "return_code": job.get("return_code"),
                        "logs": list(job["logs"]),
                    }
                self._send_json(payload)
                return

            self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if not self._check_auth():
                self._send_json({"ok": False, "error": "Unauthorized (invalid X-Cloud-Token)"}, HTTPStatus.UNAUTHORIZED)
                return

            if self.path == "/render-chapter":
                with state._lock:
                    if state.active_job_id is not None:
                        self._send_json(
                            {"ok": False, "error": f"Cloud GPU busy with job {state.active_job_id}"},
                            HTTPStatus.CONFLICT,
                        )
                        return

                content_len = int(self.headers.get("Content-Length", "0") or "0")
                if content_len <= 0:
                    self._send_json({"ok": False, "error": "Empty request body"}, HTTPStatus.BAD_REQUEST)
                    return

                body = self.rfile.read(content_len)
                series_slug = (self.headers.get("X-Series-Slug") or "unknown").strip()
                chapter = int(self.headers.get("X-Chapter") or "1")
                speed = float(self.headers.get("X-Speed") or "1.25")
                cold_open = (self.headers.get("X-Cold-Open") or "1") == "1"
                outro = (self.headers.get("X-Outro") or "0") == "1"
                burn_subs = (self.headers.get("X-Burn-Subtitles") or "0") == "1"
                rebuild = (self.headers.get("X-Rebuild") or "0") == "1"
                panel_layout = (self.headers.get("X-Panel-Layout") or "hybrid").strip()

                job_id = f"cloud_{int(time.time())}_{secrets.token_hex(3)}"
                job_dir = state.work_root / job_id
                chap_dir = job_dir / "chapter"
                chap_dir.mkdir(parents=True, exist_ok=True)

                # Extract uploaded chapter bundle (artwork/, scripts/, project.yaml, optional registry.json)
                with zipfile.ZipFile(io.BytesIO(body), "r") as zf:
                    for member in zf.namelist():
                        norm = member.replace("\\", "/").lstrip("/")
                        if ".." in norm.split("/"):
                            continue
                        if norm == "registry.json":
                            reg_dst = state.root_dir / "configs" / "character_registry" / series_slug / "registry.json"
                            reg_dst.parent.mkdir(parents=True, exist_ok=True)
                            reg_dst.write_bytes(zf.read(member))
                        else:
                            dst = chap_dir / norm
                            if norm.endswith("/"):
                                dst.mkdir(parents=True, exist_ok=True)
                            else:
                                dst.parent.mkdir(parents=True, exist_ok=True)
                                dst.write_bytes(zf.read(member))

                logs_q: Deque[str] = deque(maxlen=800)
                job_rec: Dict[str, Any] = {
                    "job_id": job_id,
                    "title": f"{series_slug} Ch.{chapter} ({speed:g}x)",
                    "status": "running",
                    "return_code": None,
                    "logs": logs_q,
                    "job_dir": str(job_dir),
                    "result_zip": str(job_dir / "result.zip"),
                }
                with state._lock:
                    state.jobs[job_id] = job_rec
                    state.active_job_id = job_id

                def _run_render() -> None:
                    try:
                        cmd = [
                            sys.executable, "-m", "manhwa_studio.cli",
                            "pro-render", "-p", str(chap_dir),
                            "--speed", f"{speed:g}",
                            "--cold-open" if cold_open else "--no-cold-open",
                            "--outro" if outro else "--no-outro",
                        ]
                        if burn_subs:
                            cmd.append("--burn-subtitles")
                        if rebuild:
                            cmd.append("--rebuild-segments")

                        env = os.environ.copy()
                        # Cloud GPU Worker handles Voice (F5-Hindi) + Video Rendering (NVENC) ONLY.
                        # Scriptwriting is done by Gemini API before sending the chapter to the worker.
                        env.pop("GEMINI_API_KEY", None)
                        env.pop("GEMINI_API_KEYS", None)
                        env["TTS_PROVIDER"] = "f5_hindi"
                        env["LLM_PROVIDER"] = "ollama"  # Ensures zero Gemini calls during render/voice stage
                        env["STUDIO_DISABLE_GPU"] = "0"
                        env["STUDIO_PANEL_LAYOUT"] = panel_layout
                        env["STUDIO_AUTO_CLEAN_SEGMENTS"] = "1"
                        env["PYTHONUNBUFFERED"] = "1"

                        logs_q.append(f"[Cloud T4] Starting Pro Render: {series_slug} Ch.{chapter} ({speed:g}x, layout={panel_layout})")
                        proc = subprocess.Popen(
                            cmd,
                            cwd=str(state.root_dir),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            env=env,
                            bufsize=1,
                        )
                        if proc.stdout:
                            for line in proc.stdout:
                                clean = line.rstrip("\r\n")
                                if clean:
                                    logs_q.append(clean)
                        ret = proc.wait()
                        job_rec["return_code"] = ret

                        if ret == 0:
                            # Auto-backup finished exports to Google Drive if mounted (safety net!)
                            drive_exports = Path("/content/drive/MyDrive/manhwa_exports") / f"{series_slug}_ch{chapter:03d}"
                            if Path("/content/drive/MyDrive").exists():
                                try:
                                    drive_exports.mkdir(parents=True, exist_ok=True)
                                    exp_dir = chap_dir / "exports"
                                    if exp_dir.exists():
                                        for ef in exp_dir.glob("*"):
                                            if ef.is_file():
                                                shutil.copy2(ef, drive_exports / ef.name)
                                    logs_q.append(f"[Cloud T4] Backed up exports to Google Drive: {drive_exports}")
                                except Exception as drv_err:
                                    logs_q.append(f"[Cloud T4] Drive backup skipped: {drv_err}")

                            # Package ONLY essential outputs using ZIP_STORED (MP4 is already compressed -> 20x faster & 4x smaller!)
                            res_zip = Path(job_rec["result_zip"])
                            with zipfile.ZipFile(res_zip, "w", zipfile.ZIP_STORED) as ozf:
                                for sub in ("exports", "reports", "subtitles", "scripts"):
                                    sub_dir = chap_dir / sub
                                    if sub_dir.exists():
                                        for f in sub_dir.rglob("*"):
                                            if f.is_file():
                                                ozf.write(f, f.relative_to(chap_dir).as_posix())
                                # Include only the target-speed chapter_body for marathon stitching (skip duplicate final_video copies)
                                renders_dir = chap_dir / "renders"
                                body_name = f"chapter_body_{speed:g}x.mp4" if speed != 1.0 else "chapter_body.mp4"
                                body_file = renders_dir / body_name
                                if body_file.exists():
                                    ozf.write(body_file, body_file.relative_to(chap_dir).as_posix())
                                reg_src = state.root_dir / "configs" / "character_registry" / series_slug / "registry.json"
                                if reg_src.exists():
                                    ozf.write(reg_src, "registry.json")

                            logs_q.append(f"[Cloud T4] Render complete! Packaged {res_zip.stat().st_size / (1024*1024):.1f} MB for download.")
                            with state._lock:
                                job_rec["status"] = "succeeded"
                                state.jobs_completed += 1
                        else:
                            logs_q.append(f"[Cloud T4] Render failed with exit code {ret}")
                            with state._lock:
                                job_rec["status"] = "failed"
                    except Exception as exc:
                        logs_q.append(f"[Cloud T4 ERROR] {exc}")
                        with state._lock:
                            job_rec["status"] = "failed"
                    finally:
                        with state._lock:
                            if state.active_job_id == job_id:
                                state.active_job_id = None

                threading.Thread(target=_run_render, daemon=True).start()
                self._send_json({"ok": True, "job_id": job_id})
                return

            self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

    server = ThreadingHTTPServer((host, port), WorkerHandler)
    print("=" * 68, flush=True)
    print("  Manhwa Story Studio — Cloud GPU Render Worker READY", flush=True)
    print(f"  Listening : http://{host}:{port}", flush=True)
    print(f"  Token     : {auth_token}", flush=True)
    print("  Paste the cloudflared URL + Token into your Local Dashboard!", flush=True)
    print("=" * 68, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# Local Dashboard Client Helpers (Runs on Local Windows PC)
# ---------------------------------------------------------------------------

def load_cloud_worker_config(root_dir: Path) -> Dict[str, str]:
    cfg_file = root_dir / "data" / "cloud_worker_config.json"
    url = os.environ.get("STUDIO_CLOUD_WORKER_URL", "").strip()
    token = os.environ.get("STUDIO_CLOUD_TOKEN", "").strip()
    if cfg_file.exists():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            url = str(data.get("url") or url).strip()
            token = str(data.get("token") or token).strip()
        except Exception:
            pass
    return {"url": url.rstrip("/"), "token": token}


def save_cloud_worker_config(root_dir: Path, url: str, token: str) -> Dict[str, str]:
    cfg_file = root_dir / "data" / "cloud_worker_config.json"
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    clean = {"url": url.strip().rstrip("/"), "token": token.strip()}
    cfg_file.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return clean


def fetch_cloud_worker_health(url: str, token: str, timeout: float = 5.0) -> Dict[str, Any]:
    if not url:
        return {"connected": False, "configured": False, "error": "Cloud Worker URL not set"}
    req = urllib.request.Request(
        f"{url.rstrip('/')}/health",
        headers={"X-Cloud-Token": token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"connected": True, "configured": True, **data}
    except urllib.error.HTTPError as he:
        if he.code in (502, 503, 530):
            return {
                "connected": False,
                "configured": True,
                "limit_alert": True,
                "error": f"Colab tunnel offline (HTTP {he.code}) — Colab session likely timed out or reached its limit. Reconnect Colab!",
            }
        return {"connected": False, "configured": True, "error": f"HTTP {he.code}: {he.reason}"}
    except Exception as exc:
        return {"connected": False, "configured": True, "error": str(exc)}


def execute_cloud_pro_render(
    root_dir: Path,
    series_slug: str,
    chapter: int,
    command_args: List[str],
    log_cb: Callable[[str], None],
    is_cancelled: Callable[[], bool],
) -> int:
    """
    Upload chapter artwork + script to Colab Cloud GPU Worker, stream live logs,
    and download rendered videos + updated locked character registry back locally.
    Returns 0 on success, non-zero on failure.
    """
    cfg = load_cloud_worker_config(root_dir)
    url, token = cfg["url"], cfg["token"]
    if not url or not token:
        log_cb("[CLOUD ERROR] Cloud GPU Worker URL or Token not configured. Set it in the Cloud GPU bar at the top of the dashboard.")
        return 1

    chap_dir = root_dir / "data" / "projects" / series_slug / f"chapter_{chapter:03d}"
    if not (chap_dir / "scripts" / "scene_manifest.json").exists():
        log_cb(f"[CLOUD ERROR] scene_manifest.json not found in {chap_dir}. Run Process Inbox first.")
        return 1

    # Parse flags from command_args
    speed = 1.25
    if "--speed" in command_args:
        try:
            speed = float(command_args[command_args.index("--speed") + 1])
        except Exception:
            pass
    cold_open = "--no-cold-open" not in command_args
    outro = "--outro" in command_args
    burn_subs = "--burn-subtitles" in command_args
    rebuild = "--rebuild-segments" in command_args
    panel_layout = os.environ.get("STUDIO_PANEL_LAYOUT", "hybrid").strip() or "hybrid"

    # 1. Package chapter artwork + scripts + registry into memory zip
    log_cb(f"[Cloud T4] Packaging {series_slug} Ch.{chapter} (artwork + scripts + locked voice registry)...")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in ("artwork", "scripts"):
            sub_dir = chap_dir / sub
            if sub_dir.exists():
                for f in sub_dir.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(chap_dir).as_posix())
        for meta in ("project.yaml", "rights_manifest.json", "state.json"):
            mp = chap_dir / meta
            if mp.exists():
                zf.write(mp, meta)
        reg_file = root_dir / "configs" / "character_registry" / series_slug / "registry.json"
        if reg_file.exists():
            zf.write(reg_file, "registry.json")

    zip_bytes = buf.getvalue()
    log_cb(f"[Cloud T4] Uploading {len(zip_bytes) / (1024 * 1024):.2f} MB to {url} ...")

    req = urllib.request.Request(
        f"{url}/render-chapter",
        data=zip_bytes,
        headers={
            "Content-Type": "application/zip",
            "X-Cloud-Token": token,
            "X-Series-Slug": series_slug,
            "X-Chapter": str(chapter),
            "X-Speed": f"{speed:g}",
            "X-Cold-Open": "1" if cold_open else "0",
            "X-Outro": "1" if outro else "0",
            "X-Burn-Subtitles": "1" if burn_subs else "0",
            "X-Rebuild": "1" if rebuild else "0",
            "X-Panel-Layout": panel_layout,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            start_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as he:
        err_body = he.read().decode("utf-8", errors="ignore")
        if he.code in (502, 503, 530):
            log_cb(f"[CLOUD LIMIT / DISCONNECTED] Colab runtime is offline (HTTP {he.code}). Check your Colab tab to reconnect or reset runtime.")
        else:
            log_cb(f"[CLOUD ERROR] Upload rejected (HTTP {he.code}): {err_body}")
        return 1
    except Exception as exc:
        log_cb(f"[CLOUD ERROR] Could not reach Cloud Worker: {exc}")
        return 1

    remote_job_id = start_data.get("job_id")
    if not remote_job_id:
        log_cb(f"[CLOUD ERROR] Invalid worker response: {start_data}")
        return 1

    log_cb(f"[Cloud T4] Job accepted on Colab GPU (remote id: {remote_job_id}). Streaming logs...")

    # 2. Poll remote job status & stream new log lines
    seen_logs = 0
    consecutive_errors = 0
    while True:
        if is_cancelled():
            log_cb("[Cloud T4] Cancelled locally.")
            return 1
        time.sleep(3.0)
        try:
            poll_req = urllib.request.Request(
                f"{url}/job/{remote_job_id}",
                headers={"X-Cloud-Token": token},
                method="GET",
            )
            with urllib.request.urlopen(poll_req, timeout=20) as resp:
                status_data = json.loads(resp.read().decode("utf-8"))
            consecutive_errors = 0
        except urllib.error.HTTPError as he:
            consecutive_errors += 1
            if consecutive_errors >= 12:
                log_cb(
                    f"[CLOUD LIMIT / DISCONNECTED] Lost connection to Colab after {consecutive_errors} retries (HTTP {he.code}). "
                    f"Colab T4 session likely timed out or hit compute/RAM limit — open Colab to reconnect/reset!"
                )
                return 1
            if consecutive_errors in (1, 4, 8):
                log_cb(f"[Cloud T4] Transient tunnel hiccup (HTTP {he.code}) — waiting for cloudflared reconnect ({consecutive_errors}/12)...")
            time.sleep(2.0)
            continue
        except Exception as exc:
            consecutive_errors += 1
            if consecutive_errors >= 12:
                log_cb(f"[CLOUD LIMIT / DISCONNECTED] Polling failed {consecutive_errors}x ({exc}). Check Colab session.")
                return 1
            if consecutive_errors in (1, 4, 8):
                log_cb(f"[Cloud T4] Transient network hiccup ({exc}) — retrying ({consecutive_errors}/12)...")
            time.sleep(2.0)
            continue

        remote_logs = status_data.get("logs", [])
        if len(remote_logs) > seen_logs:
            for line in remote_logs[seen_logs:]:
                log_cb(line)
            seen_logs = len(remote_logs)

        st = status_data.get("status")
        if st == "succeeded":
            break
        if st == "failed":
            log_cb(f"[Cloud T4] Remote render failed (code {status_data.get('return_code')}).")
            return 1

    # 3. Stream-download rendered artifacts in 1 MB chunks to disk (prevents RAM bloat & read timeouts)
    log_cb("[Cloud T4] Downloading finished video, thumbnail, YouTube kit & locked voices...")
    dl_req = urllib.request.Request(
        f"{url}/job/{remote_job_id}/download",
        headers={"X-Cloud-Token": token},
        method="GET",
    )
    tmp_dl = chap_dir / "_cloud_download.zip"
    chap_dir.mkdir(parents=True, exist_ok=True)
    downloaded_bytes = 0
    try:
        with urllib.request.urlopen(dl_req, timeout=120) as resp, open(tmp_dl, "wb") as out_f:
            total_bytes = int(resp.headers.get("Content-Length") or "0")
            last_log_mb = -50.0
            while True:
                if is_cancelled():
                    log_cb("[Cloud T4] Download cancelled locally.")
                    return 1
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out_f.write(chunk)
                downloaded_bytes += len(chunk)
                cur_mb = downloaded_bytes / (1024 * 1024)
                if cur_mb - last_log_mb >= 25.0:
                    if total_bytes > 0:
                        tot_mb = total_bytes / (1024 * 1024)
                        log_cb(f"[Cloud T4] Downloading: {cur_mb:.1f} / {tot_mb:.1f} MB ({int(downloaded_bytes*100/total_bytes)}%)")
                    else:
                        log_cb(f"[Cloud T4] Downloading: {cur_mb:.1f} MB...")
                    last_log_mb = cur_mb
    except Exception as exc:
        log_cb(f"[CLOUD ERROR] Download failed after {downloaded_bytes/(1024*1024):.1f} MB ({exc}). Check /content/drive/MyDrive/manhwa_exports/ for backup!")
        if tmp_dl.exists():
            tmp_dl.unlink(missing_ok=True)
        return 1

    with zipfile.ZipFile(tmp_dl, "r") as zf:
        for member in zf.namelist():
            norm = member.replace("\\", "/").lstrip("/")
            if ".." in norm.split("/"):
                continue
            if norm == "registry.json":
                reg_dst = root_dir / "configs" / "character_registry" / series_slug / "registry.json"
                reg_dst.parent.mkdir(parents=True, exist_ok=True)
                reg_dst.write_bytes(zf.read(member))
            else:
                dst = chap_dir / norm
                if norm.endswith("/"):
                    dst.mkdir(parents=True, exist_ok=True)
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(zf.read(member))

    tmp_dl.unlink(missing_ok=True)

    # Mirror exports/*_pro.mp4 -> renders/final_video_{speed}x.mp4 locally (0 extra download MB)
    # so the Dashboard Matrix immediately displays the exact 1.25x speed pill
    try:
        pro_exports = list((chap_dir / "exports").glob("*_pro.mp4"))
        if pro_exports:
            renders_dir = chap_dir / "renders"
            renders_dir.mkdir(parents=True, exist_ok=True)
            final_name = f"final_video_{speed:g}x.mp4" if speed != 1.0 else "final_video.mp4"
            final_dst = renders_dir / final_name
            if not final_dst.exists():
                shutil.copy2(pro_exports[0], final_dst)
    except Exception:
        pass

    log_cb(f"[Cloud T4] Synced {downloaded_bytes / (1024 * 1024):.1f} MB back to {chap_dir} — DONE!")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Manhwa Story Studio Cloud GPU Worker Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--token", default=None, help="Shared secret token (or set STUDIO_CLOUD_TOKEN)")
    args = parser.parse_args()
    run_cloud_worker_server(host=args.host, port=args.port, token=args.token)


if __name__ == "__main__":
    main()

