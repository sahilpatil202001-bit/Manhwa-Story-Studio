"""
Job Queue Engine & External Process Monitor for Manhwa Story Studio Pro.
Safely manages background CLI tasks, detects running external terminal commands,
prevents chapter/resource collisions, and streams real-time logs.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional


class JobRecord:
    """Represents a queued, running, or completed Studio CLI job."""

    def __init__(
        self,
        job_id: str,
        job_type: str,
        title: str,
        command_args: List[str],
        lane: str = "render",
        series_slug: Optional[str] = None,
        chapters: Optional[List[int]] = None,
        status: str = "queued",
        created_at: Optional[str] = None,
        gpu_target: str = "local",
    ):
        self.job_id = job_id
        self.job_type = job_type
        self.title = title
        self.command_args = command_args
        self.gpu_target = gpu_target if gpu_target in ("local", "cloud") else "local"
        self.lane = "render_cloud" if self.gpu_target == "cloud" else lane
        self.series_slug = series_slug
        self.chapters = chapters or []
        self.status = status  # queued, running, succeeded, failed, cancelled
        self.created_at = created_at or datetime.datetime.now().isoformat()
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.return_code: Optional[int] = None
        self.pid: Optional[int] = None
        self.logs: Deque[str] = deque(maxlen=600)
        self.process: Optional[subprocess.Popen] = None

    @property
    def display_command(self) -> str:
        """Return copy-pasteable PowerShell command string."""
        quoted = []
        for a in self.command_args:
            if " " in a or "," in a:
                quoted.append(f'"{a}"')
            else:
                quoted.append(a)
        return ".\\.venv\\Scripts\\python -m manhwa_studio.cli " + " ".join(quoted)

    def to_dict(self, include_logs: bool = False) -> Dict[str, Any]:
        d = {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "title": self.title,
            "command_args": self.command_args,
            "display_command": self.display_command,
            "lane": self.lane,
            "gpu_target": self.gpu_target,
            "series_slug": self.series_slug,
            "chapters": self.chapters,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "return_code": self.return_code,
            "pid": self.pid,
            "log_tail": list(self.logs)[-8:] if self.logs else [],
        }
        if include_logs:
            d["logs"] = list(self.logs)
        return d


class JobQueueManager:
    """
    Two-lane background job queue with external terminal process detection.
    - Lane 1 ('script'): process-inbox, clean-chapters, create-script (Gemini / I/O bound)
    - Lane 2 ('render'): pro-render, pro-render-range, marathon, speed-video (FFmpeg / CPU-GPU bound)
    """

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = (root_dir or Path.cwd()).resolve()
        self.state_file = self.root_dir / "data" / "dashboard_jobs.json"
        self.logs_dir = self.root_dir / "data" / "job_logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self.jobs: Dict[str, JobRecord] = {}
        self.job_order: List[str] = []
        self.paused: bool = False
        self.wait_for_external: bool = True  # Wait if an external terminal command is using the same lane

        self._external_cache: List[Dict[str, Any]] = []
        self._external_cache_time: float = 0.0

        self._load_persisted_jobs()

        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._worker_thread.start()

    def _load_persisted_jobs(self) -> None:
        """Load historical job records from data/dashboard_jobs.json."""
        if not self.state_file.exists():
            return
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            for item in raw.get("jobs", [])[-50:]:
                status = item.get("status", "queued")
                if status == "running":
                    status = "failed"  # Interrupted when previous dashboard closed
                rec = JobRecord(
                    job_id=item["job_id"],
                    job_type=item["job_type"],
                    title=item["title"],
                    command_args=item["command_args"],
                    lane=item.get("lane", "render"),
                    series_slug=item.get("series_slug"),
                    chapters=item.get("chapters", []),
                    status=status,
                    created_at=item.get("created_at"),
                    gpu_target=item.get("gpu_target", "local"),
                )
                rec.started_at = item.get("started_at")
                rec.completed_at = item.get("completed_at")
                rec.return_code = item.get("return_code")
                for line in item.get("log_tail", []):
                    rec.logs.append(line)
                self.jobs[rec.job_id] = rec
                self.job_order.append(rec.job_id)
        except Exception:
            pass

    def _save_persisted_jobs(self) -> None:
        """Persist job queue state atomically."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = {
                    "updated_at": datetime.datetime.now().isoformat(),
                    "jobs": [self.jobs[jid].to_dict(include_logs=False) for jid in self.job_order[-60:] if jid in self.jobs],
                }
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.state_file)
        except Exception:
            pass

    def detect_external_processes(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Detect any `manhwa_studio.cli` processes running outside the dashboard
        (e.g., started manually by the user in PowerShell terminals).
        """
        now = time.time()
        if not force_refresh and (now - self._external_cache_time) < 3.5:
            return self._external_cache

        my_pid = os.getpid()
        with self._lock:
            managed_pids = {
                j.pid for j in self.jobs.values()
                if j.status == "running" and j.pid is not None
            }

        external_list: List[Dict[str, Any]] = []
        if os.name == "nt":
            try:
                ps_cmd = (
                    "Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | "
                    "Where-Object { $_.CommandLine -like '*manhwa_studio.cli*' } | "
                    "Select-Object ProcessId, CommandLine, CreationDate | ConvertTo-Json -Compress"
                )
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True,
                    text=True,
                    timeout=4,
                )
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout.strip())
                    if isinstance(data, dict):
                        data = [data]
                    for proc in data:
                        pid = int(proc.get("ProcessId", 0))
                        cmd_line = str(proc.get("CommandLine") or "")
                        if pid == my_pid or pid in managed_pids:
                            continue
                        if "dashboard" in cmd_line:
                            continue

                        # Classify command type & lane
                        subcommand = "unknown"
                        lane = "render"
                        parts = cmd_line.split("manhwa_studio.cli")
                        args_tail = parts[1].strip() if len(parts) > 1 else cmd_line
                        tokens = args_tail.split()
                        if tokens:
                            subcommand = tokens[0]

                        if subcommand in ("process-inbox", "clean-chapters", "create-script", "slice-strips"):
                            lane = "script"

                        external_list.append({
                            "pid": pid,
                            "subcommand": subcommand,
                            "lane": lane,
                            "command_line": cmd_line,
                            "args_summary": args_tail,
                        })
            except Exception:
                pass

        self._external_cache = external_list
        self._external_cache_time = now
        return external_list

    def enqueue_job(
        self,
        job_type: str,
        title: str,
        command_args: List[str],
        lane: Optional[str] = None,
        series_slug: Optional[str] = None,
        chapters: Optional[List[int]] = None,
        gpu_target: str = "local",
    ) -> JobRecord:
        """Add a new CLI job to the safe execution queue."""
        eff_gpu = gpu_target if gpu_target in ("local", "cloud") else "local"
        if eff_gpu == "cloud":
            lane = "render_cloud"
        elif not lane:
            if job_type in ("process-inbox", "clean-chapters", "create-script", "slice-strips"):
                lane = "script"
            else:
                lane = "render"

        job_id = f"job_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"
        record = JobRecord(
            job_id=job_id,
            job_type=job_type,
            title=title,
            command_args=command_args,
            lane=lane,
            series_slug=series_slug,
            chapters=chapters,
            status="queued",
            gpu_target=eff_gpu,
        )
        with self._lock:
            self.jobs[job_id] = record
            self.job_order.append(job_id)
        self._save_persisted_jobs()
        return record

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued job or terminate a running job."""
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            if job.status == "queued":
                job.status = "cancelled"
                job.completed_at = datetime.datetime.now().isoformat()
                self._save_persisted_jobs()
                return True
            if job.status == "running" and job.process:
                try:
                    job.process.terminate()
                except Exception:
                    pass
                job.status = "cancelled"
                job.completed_at = datetime.datetime.now().isoformat()
                self._save_persisted_jobs()
                return True
        return False

    def clear_finished_jobs(self) -> int:
        """Remove completed/failed/cancelled jobs from the queue list."""
        removed = 0
        with self._lock:
            remaining_order = []
            for jid in self.job_order:
                j = self.jobs.get(jid)
                if j and j.status in ("queued", "running"):
                    remaining_order.append(jid)
                else:
                    self.jobs.pop(jid, None)
                    removed += 1
            self.job_order = remaining_order
        self._save_persisted_jobs()
        return removed

    def get_queue_snapshot(self) -> Dict[str, Any]:
        """Return full status of internal queue + external terminal jobs."""
        ext = self.detect_external_processes()
        with self._lock:
            job_list = [self.jobs[jid].to_dict(include_logs=False) for jid in reversed(self.job_order) if jid in self.jobs]
        return {
            "paused": self.paused,
            "wait_for_external": self.wait_for_external,
            "external_processes": ext,
            "jobs": job_list,
        }

    def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            return job.to_dict(include_logs=True)

    def _can_start_job(self, candidate: JobRecord, external_procs: List[Dict[str, Any]]) -> bool:
        """Check lane availability and chapter lock conflicts before starting a job."""
        with self._lock:
            running_jobs = [j for j in self.jobs.values() if j.status == "running"]

        # 1. Check if same lane already has a running job inside dashboard
        for rj in running_jobs:
            if rj.lane == candidate.lane:
                return False
            # Prevent same series+chapter overlap across lanes
            if rj.series_slug and candidate.series_slug and rj.series_slug == candidate.series_slug:
                if set(rj.chapters) & set(candidate.chapters):
                    return False

        # 2. If wait_for_external is enabled, yield if an external terminal command is occupying this lane
        if self.wait_for_external:
            for ext in external_procs:
                if ext.get("lane") == candidate.lane:
                    return False

        return True

    def _scheduler_loop(self) -> None:
        """Background loop that dispatches queued jobs when their lane is free."""
        while not self._stop_event.is_set():
            try:
                if not self.paused:
                    ext_procs = self.detect_external_processes()
                    with self._lock:
                        queued = [
                            self.jobs[jid] for jid in self.job_order
                            if jid in self.jobs and self.jobs[jid].status == "queued"
                        ]

                    for candidate in queued:
                        if self._can_start_job(candidate, ext_procs):
                            self._launch_job_thread(candidate)
            except Exception:
                pass
            time.sleep(1.5)

    def _launch_job_thread(self, job: JobRecord) -> None:
        with self._lock:
            job.status = "running"
            job.started_at = datetime.datetime.now().isoformat()
        self._save_persisted_jobs()

        t = threading.Thread(target=self._execute_job, args=(job,), daemon=True)
        t.start()

    def _execute_job(self, job: JobRecord) -> None:
        """Run the job either on the Remote Cloud GPU Worker or as a local CLI subprocess."""
        log_file = self.logs_dir / f"{job.job_id}.log"

        if job.gpu_target == "cloud" and job.job_type == "pro-render" and job.series_slug and job.chapters:
            from manhwa_studio.dashboard.cloud_worker import execute_cloud_pro_render

            job.logs.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting on Cloud GPU (Colab): {job.title}")
            try:
                with open(log_file, "w", encoding="utf-8", errors="replace") as lf:
                    lf.write(f"Cloud GPU Job: {job.title}\nStarted: {job.started_at}\n" + ("-" * 60) + "\n")
                    lf.flush()

                    def _log(line: str) -> None:
                        job.logs.append(line)
                        lf.write(line + "\n")
                        lf.flush()

                    ret = execute_cloud_pro_render(
                        root_dir=self.root_dir,
                        series_slug=job.series_slug,
                        chapter=job.chapters[0],
                        command_args=job.command_args,
                        log_cb=_log,
                        is_cancelled=lambda: job.status == "cancelled",
                    )
                with self._lock:
                    job.return_code = ret
                    job.completed_at = datetime.datetime.now().isoformat()
                    if job.status != "cancelled":
                        job.status = "succeeded" if ret == 0 else "failed"
                    job.logs.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Cloud job finished with code {ret}")
            except Exception as exc:
                with self._lock:
                    job.completed_at = datetime.datetime.now().isoformat()
                    job.status = "failed"
                    job.logs.append(f"[CLOUD ERROR] {exc}")
            finally:
                self._save_persisted_jobs()
            return

        python_exe = sys.executable
        cmd = [python_exe, "-m", "manhwa_studio.cli"] + job.command_args

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        job.logs.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting: {job.display_command}")

        try:
            with open(log_file, "w", encoding="utf-8", errors="replace") as lf:
                lf.write(f"Command: {job.display_command}\n")
                lf.write(f"Started: {job.started_at}\n" + ("-" * 60) + "\n")
                lf.flush()

                proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.root_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    bufsize=1,
                )
                with self._lock:
                    job.process = proc
                    job.pid = proc.pid

                if proc.stdout:
                    for line in proc.stdout:
                        clean_line = line.rstrip("\r\n")
                        if clean_line:
                            job.logs.append(clean_line)
                            lf.write(clean_line + "\n")
                            lf.flush()

                ret = proc.wait()
                with self._lock:
                    job.return_code = ret
                    job.completed_at = datetime.datetime.now().isoformat()
                    if job.status != "cancelled":
                        job.status = "succeeded" if ret == 0 else "failed"
                    job.logs.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Process exited with code {ret}")
        except Exception as exc:
            with self._lock:
                job.completed_at = datetime.datetime.now().isoformat()
                job.status = "failed"
                job.logs.append(f"[ERROR] Failed to execute job: {exc}")
        finally:
            self._save_persisted_jobs()

