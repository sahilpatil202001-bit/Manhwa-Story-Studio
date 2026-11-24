# check_environment.ps1 - Environment verification for Manhwa Story Studio
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Manhwa Story Studio - Environment Check" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Check Python
$pythonCmd = "python"
if (Get-Command $pythonCmd -ErrorAction SilentlyContinue) {
    $pyVer = & $pythonCmd --version
    Write-Host "[OK] Python detected: $pyVer" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Python not found in PATH." -ForegroundColor Red
}

# 2. Check Virtual Environment
if (Test-Path ".venv\Scripts\python.exe") {
    $venvPy = & ".\.venv\Scripts\python.exe" --version
    Write-Host "[OK] Local .venv detected: $venvPy" -ForegroundColor Green
} else {
    Write-Host "[WARN] Local .venv not found. Create one with: python -m venv .venv" -ForegroundColor Yellow
}

# 3. Check FFmpeg
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    $ffmpegVer = & ffmpeg -version | Select-Object -First 1
    Write-Host "[OK] FFmpeg detected: $ffmpegVer" -ForegroundColor Green
} else {
    Write-Host "[FAIL] FFmpeg is missing from PATH. Required for video rendering." -ForegroundColor Red
}

# 4. Check FFprobe
if (Get-Command ffprobe -ErrorAction SilentlyContinue) {
    $ffprobeVer = & ffprobe -version | Select-Object -First 1
    Write-Host "[OK] FFprobe detected: $ffprobeVer" -ForegroundColor Green
} else {
    Write-Host "[FAIL] FFprobe is missing from PATH. Required for media validation." -ForegroundColor Red
}

# 5. Check Package Imports in .venv
if (Test-Path ".\.venv\Scripts\python.exe") {
    $testImports = "import pydantic, yaml, typer, rich, PIL, edge_tts, pytest; print('All core modules imported successfully')"
    $importResult = & ".\.venv\Scripts\python.exe" -c $testImports 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Python core packages: $importResult" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Package import issue: $importResult" -ForegroundColor Yellow
    }
}

Write-Host "==========================================" -ForegroundColor Cyan
