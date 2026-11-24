# Troubleshooting & FAQ

### 1. `FFmpeg or FFprobe missing from PATH`
**Solution**:
Install FFmpeg from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or winget:
```powershell
winget install Gyan.FFmpeg
```
Alternatively, set the environment variables in your `.env` file:
```env
STUDIO_FFMPEG_PATH=C:\path\to\ffmpeg.exe
STUDIO_FFPROBE_PATH=C:\path\to\ffprobe.exe
```

### 2. `Scene manifest has NOT been approved by the user`
**Solution**:
Before generating voice audio, the pipeline requires explicit confirmation of the story outline:
```powershell
python -m manhwa_studio.cli approve-script --project <path_to_project>
```

### 3. `Artwork rights verification failed: Asset has unauthorized status: 'unknown'`
**Solution**:
Production rendering blocks unknown or prohibited artwork. Run:
```powershell
python -m manhwa_studio.cli register-artwork --project <path_to_project> --status permission_granted --reference "Your authorization source"
```

### 4. `Extremely Tall Strips Warning`
Manhwa chapters often contain continuous vertical webtoon strips (e.g. 800 × 5000 px). Scaling these directly into 1080 × 1920 causes tiny unreadable panels.
**Solution**:
Specify normalized crop coordinates in `scripts/scene_manifest.json`:
```json
"crop": {
  "x": 0.0,
  "y": 0.2,
  "width": 1.0,
  "height": 0.35
}
```

### 5. `ModuleNotFoundError: No module named 'manhwa_studio'`
**Solution**:
Install the package in editable mode within your virtual environment:
```powershell
.\.venv\Scripts\pip install -e .
```
