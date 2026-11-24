@echo off
title Manhwa Story Studio Pro - Web Dashboard
cd /d "%~dp0"
echo Starting Manhwa Story Studio Pro Dashboard on http://127.0.0.1:8765 ...
.\.venv\Scripts\python -m manhwa_studio.cli dashboard --port 8765
pause

