#!/usr/bin/env bash
# ==============================================================================
# YouTube 24/7 Live Stream Launcher for Linux / Cloud VPS (Ubuntu / Debian / OCI)
# ==============================================================================

VIDEO_PATH="${1:-data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_pro.mp4}"

if [ -z "$YOUTUBE_STREAM_KEY" ]; then
    read -p "Enter your YouTube Stream Key: " YOUTUBE_STREAM_KEY
fi

if [ ! -f "$VIDEO_PATH" ]; then
    echo "[ERROR] Video file not found: $VIDEO_PATH"
    exit 1
fi

echo "======================================================================"
echo "Starting 24/7 Live Stream to YouTube..."
echo "Video: $VIDEO_PATH"
echo "======================================================================"

python3 live_stream/streamer.py -v "$VIDEO_PATH" -k "$YOUTUBE_STREAM_KEY"
