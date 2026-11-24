"""
YouTube 24/7 Live Streamer Engine.
Broadcasts local or marathon MP4 videos to YouTube Live via RTMP with auto-reconnect,
zero re-encoding overhead (-c:v copy), and infinite looping capability.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def get_stream_url(stream_key: str) -> str:
    """Return the full YouTube RTMP endpoint URL."""
    clean_key = stream_key.strip()
    return f"rtmp://a.rtmp.youtube.com/live2/{clean_key}"


def run_stream(
    video_path: Path,
    stream_key: str,
    loop: bool = True,
    max_retries: int = 10,
) -> None:
    """
    Stream video to YouTube Live using FFmpeg stream copy.
    Auto-reconnects if network connection drops.
    """
    if not video_path.exists():
        print(f"[ERROR] Video file does not exist: {video_path}")
        sys.exit(1)

    if not stream_key:
        print("[ERROR] YouTube Stream Key is required.")
        print("Set YOUTUBE_STREAM_KEY in your .env or pass --key <YOUR_KEY>")
        sys.exit(1)

    rtmp_url = get_stream_url(stream_key)
    masked_key = stream_key[:4] + "****" + stream_key[-4:] if len(stream_key) > 8 else "****"

    print("=" * 70)
    print("          YOUTUBE LIVE STREAMING ENGINE")
    print("=" * 70)
    print(f"• Video Source  : {video_path.resolve()}")
    print(f"• Video Size    : {video_path.stat().st_size / (1024 * 1024):.1f} MB")
    print(f"• Stream Target : rtmp://a.rtmp.youtube.com/live2/{masked_key}")
    print(f"• Infinite Loop : {'YES (24/7 Continuous)' if loop else 'NO (One-Time Broadcast)'}")
    print(f"• CPU Mode      : Direct Stream Copy (Near-Zero CPU Usage)")
    print("=" * 70)
    print("Press Ctrl+C at any time to stop streaming.")
    print("-" * 70)

    retry_count = 0

    while retry_count < max_retries:
        cmd = ["ffmpeg", "-re"]

        if loop:
            cmd.extend(["-stream_loop", "-1"])

        cmd.extend([
            "-i", str(video_path.resolve()),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-f", "flv",
            rtmp_url,
        ])

        print(f"\n[INFO] Starting broadcast connection (Attempt {retry_count + 1})...")
        start_time = time.time()

        try:
            process = subprocess.Popen(cmd)
            process.wait()
        except KeyboardInterrupt:
            print("\n[INFO] Stream manually terminated by user. Exiting cleanly.")
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                process.kill()
            sys.exit(0)

        elapsed = time.time() - start_time
        if elapsed > 120:
            # If it ran for more than 2 minutes before disconnecting, reset retry count
            retry_count = 0
        else:
            retry_count += 1

        print(f"[WARNING] Stream connection dropped after {elapsed:.1f}s.")
        if retry_count < max_retries:
            print(f"[INFO] Waiting 5 seconds before reconnecting...")
            time.sleep(5)
        else:
            print("[ERROR] Max reconnection retries reached. Please check your network and stream key.")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Broadcast video to YouTube Live 24/7.")
    parser.add_argument("-v", "--video", type=str, required=True, help="Path to MP4 video file")
    parser.add_argument("-k", "--key", type=str, default=None, help="YouTube Stream Key (or set YOUTUBE_STREAM_KEY in .env)")
    parser.add_argument("--no-loop", action="store_true", help="Play video once instead of 24/7 loop")
    args = parser.parse_args()

    # Try resolving stream key from args or environment / .env
    stream_key = args.key or os.getenv("YOUTUBE_STREAM_KEY")
    if not stream_key:
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("YOUTUBE_STREAM_KEY="):
                    stream_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    video_path = Path(args.video)
    run_stream(video_path, stream_key or "", loop=not args.no_loop)


if __name__ == "__main__":
    main()
