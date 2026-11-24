# ☁️ Cloud GPU Setup Guide (Gemini Scripts + Local F5-Hindi Voices + NVENC)

Best-of-both-worlds architecture:
* **Vision & Scriptwriting (`Process Inbox`):** **Gemini API** on your local PC (0% GPU, crisp Hindi screenplay with zero repeated dialogue)
* **Voices (TTS):** **`SPRINGLab/F5-Hindi-24KHz` (`f5_hindi`)** running on Cloud T4 GPU cloning your 6 reference voices (**Zero Gemini API calls for TTS**)
* **Video Rendering:** **Hybrid Auto-Director + FFmpeg `h264_nvenc`** hardware encoding on the Cloud T4 GPU

*(No Ollama install needed on Colab — setup takes under 60 seconds!)*

---

## Step 1: Package Your Project on Windows

Do **not** upload `.venv/`, `.cache/`, `data/`, or `.env`. Create a lightweight `studio_cloud.zip` (~15–30 MB) by running this in PowerShell inside `e:\Python\Scapper\manhwa-story-studio`:

```powershell
Compress-Archive -Path src, config, configs, pyproject.toml, Readme.md, assets\audio, assets\video, exports\demo_gemini_*.wav, exports\voice_refs -DestinationPath studio_cloud.zip -Force
```

Also keep handy the specific chapter folder(s) from `assets\inbox\` that you want to process (for example, `assets\inbox\Nano Machine\ch057`).

---

## Step 2: Choose a Free Cloud GPU Platform (No Credit Card)

### Option A: Google Colab (Easiest — No Phone Verification)
1. Upload `studio_cloud.zip` and your chapter folder (e.g., `ch057`) to **Google Drive** inside a folder named `manhwa_studio/`.
2. Open [colab.research.google.com](https://colab.research.google.com) and create a **New Notebook**.
3. Click **Runtime → Change runtime type → `T4 GPU` → Save**.

> **Colab limits:** Up to 12 hours per session, ~60–90 min idle timeout, and stops if you close the browser tab. Heavy daily usage may trigger a temporary GPU cooldown (24h+).


---

## Step 3: Run These Notebook Cells in Order

### Cell 1 — Unzip Project & Copy Chapter Images

**If using Google Colab:**
```python
from google.colab import drive
drive.mount('/content/drive')

!mkdir -p /content/studio
!unzip -q "/content/drive/MyDrive/manhwa_studio/studio_cloud.zip" -d /content/studio

# Copy the chapter folder(s) you want to render into assets/inbox/
!mkdir -p "/content/studio/assets/inbox/Nano Machine"
!cp -r "/content/drive/MyDrive/manhwa_studio/ch057" "/content/studio/assets/inbox/Nano Machine/"

%cd /content/studio
```



---

### Cell 2 — Install FFmpeg, Fonts & `f5-tts` (Fast: ~45 seconds!)

*(No Ollama needed — scripts come from Gemini on your local PC, and Colab only runs `F5-Hindi-24KHz` + `h264_nvenc`!)*

```bash
# 1. Install FFmpeg, Linux fonts, f5-tts, and your studio package
!apt-get -qq update && apt-get -qq install -y ffmpeg fonts-dejavu-core fonts-noto-core
!pip install -q f5-tts
!pip install -q -e .

# 2. Verify GPU & NVENC
!nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
!ffmpeg -hide_banner -encoders 2>/dev/null | grep nvenc
```

---

### Cell 3 — Configure Environment (100% F5-Hindi Voices + Hybrid Auto-Director, Zero Gemini TTS)

**For Google Colab** *(for Kaggle, change `/content/.cache/...` to `/kaggle/working/.cache/...`)*:

```python
import os

# 1. Strictly F5-Hindi-24KHz cloned voices (Zero Gemini API calls for TTS)
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GEMINI_API_KEYS", None)
os.environ["TTS_PROVIDER"] = "f5_hindi"
os.environ["STUDIO_DEFAULT_MALE_VOICE"] = "gemini:Puck"
os.environ["STUDIO_DEFAULT_FEMALE_VOICE"] = "gemini:Leda"

# 2. Linux paths (overriding Windows paths from .env)
os.environ["HF_HOME"] = "/content/.cache/huggingface"
os.environ["TORCH_HOME"] = "/content/.cache/torch"
os.environ["STUDIO_FONT_LATIN"] = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
os.environ["STUDIO_FONT_HINDI"] = "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"

# 3. Video rendering settings (Hybrid Auto-Director: Wide Zoom + Dual Panel)
os.environ["STUDIO_DISABLE_GPU"] = "0"
os.environ["STUDIO_DEFAULT_SPEED"] = "1.25"
os.environ["STUDIO_PANEL_LAYOUT"] = "hybrid"
```

---


---

## Option B — Connect Colab T4 Directly to Your Local Dashboard (Parallel 2-GPU Rendering!)

Run **1 chapter on your Local GPU** + **1 chapter on Colab T4 GPU at the same time** (strictly 1 job per GPU), with automatic download of finished `.mp4` videos and locked character voices back to your Windows PC!

### Cell 4B — Start Cloud GPU Worker on Colab T4 (instead of manual CLI)
After running Cells 1–3 above, run this cell in Colab Pro:

```bash
# 1. Install cloudflared tunnel
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

# 2. Start Cloud GPU Worker (prints your secret Token in /tmp/cloud_worker.log)
%cd /content/studio
!PYTHONPATH=/content/studio/src STUDIO_CLOUD_TOKEN="manhwa_t4_secret_2026" nohup python -m manhwa_studio.dashboard.cloud_worker --port 8766 > /tmp/cloud_worker.log 2>&1 &
!sleep 2
!cat /tmp/cloud_worker.log

# 3. Expose via free HTTPS tunnel using stable HTTP/2 TCP (copy the https://xxxx.trycloudflare.com URL)
!cloudflared tunnel --protocol http2 --url http://127.0.0.1:8766
```

1. Open your **local Windows Dashboard** (`http://127.0.0.1:8765`).
2. Click the **`Cloud GPU: Off`** pill in the top bar → paste the `https://xxxx.trycloudflare.com` URL and token `manhwa_t4_secret_2026` → click **Save & Connect**.
3. Now you can click **`☁️ Cloud 1.25x`** or **`🖥️ Local 1.25x`** on individual chapters, or select **`⚡ Both GPUs Parallel (Auto-Split 1/GPU)`** in **Pro Render Chapter Range**!

---

## ⚠️ How to Know When Colab T4 Reaches Its Limit (and When to Stop / Reset)

Your local Dashboard automatically monitors the Colab T4 every 25 seconds and turns the top **Cloud GPU** pill **yellow/red** if any limit is close:

1. **Compute Units Running Low (Colab Pro):**
   - Inside Colab, click the **RAM / Disk** bar (top-right) → **View resources**.
   - Check **"Available compute units"** (T4 uses ~**1.9 units/hour**, L4 uses ~**4.8 units/hour**). When units reach `0`, Colab drops to free-tier limits or disconnects the GPU.
2. **Session Time Limit (Max 12h–24h):**
   - Your Dashboard shows `Uptime: X.Xh` and flashes a **yellow warning at 10+ hours** so you can finish your current chapter and cleanly click **Runtime → Disconnect and delete runtime** before Google cuts it mid-render.
3. **Disk Space Limit:**
   - The Cloud Worker auto-cleans temp segments after each chapter downloads, and flashes a **yellow warning if `< 3.5 GB` free**.
4. **Disconnected / Timeout (`HTTP 502 / 530`):**
   - If Colab stops or hits a limit, your Dashboard pill turns **red (`Cloud GPU: LIMIT/OFFLINE`)** and logs `[CLOUD LIMIT / DISCONNECTED]` without touching your local PC jobs. Just reconnect in Colab and re-run Cell 4B!

---

## Quick Checklist Before You Start
- [ ] `studio_cloud.zip` includes `exports/demo_gemini_*.wav` (for your exact cloned voices).
- [ ] `studio_cloud.zip` includes `configs/` and `config/` (for character registries & series voice profiles).
- [ ] On Kaggle, Notebook Sharing is set to **Private** and **Internet** is **On**.
- [ ] Always copy finished `.mp4` files to **Google Drive** (Colab) before closing the tab.

