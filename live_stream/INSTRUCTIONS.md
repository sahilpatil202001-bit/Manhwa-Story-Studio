# 🔴 YouTube 24/7 Live Streaming Guide

This guide explains how to broadcast your manhwa episodes or full-movie marathons as a **continuous 24/7 live stream** on YouTube — both locally from your Windows PC and permanently for **$0/month on a free cloud server**.

---

## 💡 Why Run a 24/7 Live Stream?
- **Massive Organic Traffic:** YouTube heavily pushes active live streams to user homepages and recommendation feeds.
- **Continuous Watch Time:** Viewers drop in and out throughout the day, generating thousands of watch hours towards monetization.
- **Zero CPU Usage:** Our script uses **Stream-Copy** (`-c:v copy`). It does not re-encode frames; it simply sends the existing MP4 packets directly to YouTube via RTMP.

---

## 🔑 Step 1: Get Your YouTube Stream Key

1. Go to [YouTube Studio](https://studio.youtube.com/).
2. In the top-right corner, click **Create (Camera Icon) ➔ Go Live**.
3. In the left sidebar, click **Stream**.
4. You will see:
   - **Stream URL:** `rtmp://a.rtmp.youtube.com/live2`
   - **Stream Key:** `xxxx-xxxx-xxxx-xxxx-xxxx` *(Click **Copy**; keep it secret!)*
5. *(Optional)* Add your key to `.env` in the project root so you never have to type it again:
   ```env
   YOUTUBE_STREAM_KEY=your_copied_key_here
   ```

> [!NOTE]
> If your channel has never live streamed before, YouTube requires a one-time phone verification and a **24-hour activation window** before live streaming is unlocked.

---

## 🖥️ Method A: Stream Locally from Your Windows PC

### Option 1: 1-Click Batch File
1. Double-click [`start_stream.bat`](file:///e:/Python/Scapper/manhwa-story-studio/live_stream/start_stream.bat).
2. Paste your Stream Key when prompted (or leave it blank if saved in `.env`).
3. Your stream will start broadcasting immediately!

### Option 2: Command Line (PowerShell)
```powershell
# Stream Chapter 1 video in an infinite 24/7 loop:
python live_stream/streamer.py -v data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_pro.mp4 -k "your-key-here"

# Or stream a full-movie marathon:
python live_stream/streamer.py -v exports/marathons/myst_might_mayhem_marathon.mp4
```

---

## ☁️ Method B: Stream 24/7 for Free on Oracle Cloud (Always Free VPS)

If you don't want to keep your home PC running 24/7, you can host your stream on **Oracle Cloud Infrastructure (OCI)** for **100% free forever**.

### 1. Create Your Free Cloud Account
1. Go to [oracle.com/cloud/free](https://www.oracle.com/cloud/free/) and sign up.
2. Select your home region.

### 2. Launch an Always-Free Instance
1. Go to **Compute ➔ Instances ➔ Create Instance**.
2. **Image:** Ubuntu 24.04 or 22.04 LTS.
3. **Shape:** Choose **Ampere VM.Standard.A1.Flex** (Free Tier gives up to 4 Cores, 24 GB RAM, 200 GB disk, and 10 TB free monthly bandwidth!).
4. Save your **SSH Private Key** to your computer.
5. Click **Create**. Note your server's **Public IP Address** (e.g., `129.153.xx.xx`).

### 3. Connect & Install FFmpeg
From PowerShell on your PC:
```powershell
ssh -i path\to\your_private_key.key ubuntu@129.153.xx.xx
```

Inside the Linux server, install Python and FFmpeg:
```bash
sudo apt update && sudo apt install -y ffmpeg python3 python3-pip tmux
```

### 4. Upload Your Movie & Streamer Files
From your PC PowerShell, copy the files to your server:
```powershell
# Upload the live_stream folder:
scp -i path\to\your_key.key -r live_stream ubuntu@129.153.xx.xx:/home/ubuntu/

# Upload your marathon video:
scp -i path\to\your_key.key exports/marathons/myst_might_mayhem_marathon.mp4 ubuntu@129.153.xx.xx:/home/ubuntu/
```

### 5. Run 24/7 in Background with TMUX
On your cloud server:
```bash
# Start a detachable background session:
tmux new -s stream

# Start the stream:
python3 live_stream/streamer.py -v myst_might_mayhem_marathon.mp4 -k "YOUR_STREAM_KEY"
```

- To detach from the session (leaves it running 24/7): Press **`Ctrl + B`**, then press **`D`**.
- You can now safely close your terminal or turn off your computer! The cloud server will stream to YouTube 24/7 uninterrupted.
- To check on the stream later: `tmux attach -t stream`.

---

## ⚙️ How the Auto-Reconnect Engine Works

The script ([`streamer.py`](file:///e:/Python/Scapper/manhwa-story-studio/live_stream/streamer.py)) has built-in connection resiliency:
- If your home internet or the cloud network drops for a second, YouTube does not terminate your broadcast immediately (it waits in a buffer window).
- `streamer.py` detects disconnection and automatically retries within 5 seconds without crashing.
- Once you reach the end of the video, it seamlessly loops back to second `00:00` without freezing the stream.
