@echo off
title YouTube 24/7 Live Streamer
echo ======================================================================
echo                  YOUTUBE 24/7 LIVE STREAM LAUNCHER
echo ======================================================================
echo.

:: Check for video parameter or default to chapter 1 export
set VIDEO_PATH=%1
if "%VIDEO_PATH%"=="" (
    set VIDEO_PATH=data\projects\myst_might_mayhem\chapter_001\exports\myst_might_mayhem_ch001_pro.mp4
)

:: Prompt for Stream Key if not provided in environment
if "%YOUTUBE_STREAM_KEY%"=="" (
    set /p YOUTUBE_STREAM_KEY="Enter your YouTube Stream Key: "
)

echo.
echo Launching stream with:
echo Video: %VIDEO_PATH%
echo.

python live_stream\streamer.py -v "%VIDEO_PATH%" -k "%YOUTUBE_STREAM_KEY%"

pause
