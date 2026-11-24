# 🎬 Manhwa Story Studio Pro: Complete Video Generation Guide

Welcome to the **Manhwa Story Studio Pro** user guide. This document explains how to take raw manhwa chapter images and turn them into a full-length, multi-voice dubbed, YouTube-ready anime recap video.

---

## 🖥️ 0. Launch the Web Control Center Dashboard (Recommended)

You can manage all your series, chapter pipelines, batch renders, custom thumbnails, and marathon compilations from the **Web Studio Dashboard** with a built-in **Safe 2-Lane Job Queue**:

```powershell
# Option A: Double-click start_dashboard.bat in the project folder
.\start_dashboard.bat

# Option B: Run via CLI (opens http://127.0.0.1:8765 automatically)
.\.venv\Scripts\python -m manhwa_studio.cli dashboard --port 8765
```

- **External Terminal Protection:** Automatically detects any `manhwa_studio.cli` commands running in your PowerShell terminals and waits safely so jobs never collide.
- **Series & Chapter Matrix:** Visual status of every chapter (`In Inbox` → `Script Ready` → `Rendered 1.0x / 1.25x / 1.5x`).
- **Scene & Thumbnail Studio:** Browse panels visually, read the Hindi dialogue, and click any scene to generate a custom thumbnail in seconds.

---

## 📁 1. Where to Put Chapter Images

The studio uses an **Inbox Dropzone** system:

```text
assets/
└── inbox/
    ├── The Greatest Estate Developer/    <-- (Recommended) Folder named after your manhwa
    │   ├── ch1/                          <-- Chapter 1 images (.webp, .jpg, .png)
    │   │   ├── 001.webp
    │   │   └── ...
    │   └── ch2/
    │
    └── Myst Might Mayhem/                <-- Other manhwas stay separated
        ├── ch1/
        └── ch2/
```

> [!TIP]
> **Multi-Manhwa Support:** You can create folders named after any manhwa inside `assets/inbox/`. The studio will automatically route each chapter to its correct project and voice cast without any confusion!

> [!NOTE]
> **Zip Archive Support:** You can drop chapter `.zip` files directly into your inbox folders (e.g. `ch6.zip`). The studio automatically extracts only clean chapter pages (001.webp, 002.webp), filters out ads, website banners, and duplicate files, and deletes the zip file before ingestion!
> You can also run the cleaner manually at any time:
> ```powershell
> python clean_chapters.py ch6
> # or via CLI:
> .\.venv\Scripts\python -m manhwa_studio.cli clean-chapters ch6
> ```

---

## ⚡ 2. The 1-Command Automated Workflow

```powershell
# Option A: Process all chapters across all manhwas
.\.venv\Scripts\python -m manhwa_studio.cli process-inbox

# Option B: Process ONLY Chapter 1 of The Greatest Estate Developer
.\.venv\Scripts\python -m manhwa_studio.cli process-inbox --series "The Greatest Estate Developer" --chapter 1

# Option C: Point directly to a specific chapter folder
.\.venv\Scripts\python -m manhwa_studio.cli process-inbox --inbox "assets/inbox/Nano Machine/ch001"
```
.\.venv\Scripts\python -m manhwa_studio.cli process-inbox --inbox "assets/inbox/Nano Machine" --series "Nano Machine" --chapter-start 21 --chapter-end 30


### What this command does automatically:
1. **Discovers Chapters:** Detects `ch1`, `ch2`, etc. in `assets/inbox/` (or filtered by series/chapter).
2. **AI Screenplay Writing:** Uses Gemini to analyze panels, write conversational Hindi narration, and assign character roles.
3. **Creates Project Directory:** Moves assets into `data/projects/{series_slug}/chapter_{number}/`.
-
---

## 🎙️ 3. Rendering Full Pro Video (Multi-Voice + Clean Artwork)

To render the complete high-production video with multi-character casting, dynamic BGM, camera motion, and thumbnail:

```powershell
.\.venv\Scripts\python -m manhwa_studio.cli pro-render -p data/projects/nano_machine/chapter_001
```

.\.venv\Scripts\python -m manhwa_studio.cli pro-render-range `
  --series nano_machine `
  --chapter-start 11 `
  --chapter-end 20 `
  --speed 1.25

  # Example: render at 1.5x speed
.\.venv\Scripts\python -m manhwa_studio.cli pro-render -p data/projects/myst_might_mayhem/chapter_009 --speed 1.25


### Added a direct speed-conversion command. It speeds an existing video without rerunning narration, segments, or the Pro pipeline. ###
.\.venv\Scripts\python -m manhwa_studio.cli speed-video `
  --input "data/projects/myst_might_mayhem/chapter_008/exports/myst_might_mayhem_ch008_pro.mp4" `
  --speed 1.5 `
  --output "data/projects/myst_might_mayhem/chapter_008/renders/final_video_1.5x.mp4"

### ⚙️ Useful Options for `pro-render`:

| Option | Shortcut | Description | Default |
|---|---|---|---|
| `--project` | `-p` | Path to chapter project folder | *(Required)* |
| `--burn-subtitles` | `-b` | Burn subtitles onto video (omit for clean artwork) | `False` (Clean video) |
| `--thumbnail-scene` | `-ts` | Pick a specific scene ID for the thumbnail (e.g. `scene_090` or `90`) | Auto-Detects Climax |
| `--thumbnail-panel` | `-tp` | Pick a specific panel filename (e.g. `panel_090.webp`) | Auto-Detects Climax |
| `--thumbnail-captions` | | Add text badges/Hindi teaser to thumbnail (omit for clean) | `False` (Clean artwork) |
| `--cold-open` | | Generate an 8-12s flash-forward teaser hook | `False` |
| `--rebuild-segments`| `-r` | Force re-render camera motion segments | `False` |

#### Example: Render with a specific thumbnail scene & Cold Open hook
```powershell
.\.venv\Scripts\python -m manhwa_studio.cli pro-render `
  -p data/projects/myst_might_mayhem/chapter_001 `
  -ts scene_090 `
  --cold-open
```

---

## 🖼️ 4. Generating YouTube Thumbnails

You can generate or re-generate clean, high-CTR YouTube thumbnails for any specific scene anytime:

```powershell
# Option A: Pick by Scene ID (Recommended)
.\.venv\Scripts\python -m manhwa_studio.cli pro-thumbnail -p data/projects/myst_might_mayhem/chapter_001 --scene 90

# Option B: Pick by specific panel filename
.\.venv\Scripts\python -m manhwa_studio.cli pro-thumbnail -p data/projects/myst_might_mayhem/chapter_001 --panel panel_173.webp

# Option C: Add Hindi teaser text and chapter badge (if you want text overlay)
.\.venv\Scripts\python -m manhwa_studio.cli pro-thumbnail -p data/projects/myst_might_mayhem/chapter_001 --scene 90 --captions --hook "800 साल पुराना शैतान जाग उठा!"
```

---

## 📝 5. Generating YouTube Upload & SEO Kit

To get copy-paste ready metadata for YouTube Studio (Title, Description, Timestamps, Tags):

```powershell
.\.venv\Scripts\python -m manhwa_studio.cli pro-youtube-kit -p data/projects/myst_might_mayhem/chapter_001
```

### What this produces (`youtube_upload_kit.txt`):
- **3 Click-Worthy Titles** (e.g. *"800 Saal Baad Lauta Sabse Khatarnak Demon King! 🔥 | Myst, Might, Mayhem Ch 1 Recap"*).
- **SEO Description** with plot synopsis, disclaimer, and hashtags.
- **Clickable YouTube Timestamps** (e.g. `00:00 - The Beginning`, `08:18 - Hidden Secrets`, `14:15 - The Climax Confrontation`).
- **Target Keyword Tags** ready to paste into YouTube Studio.

---

## ⚡ 6. Generating Standalone Cold Open Teaser

If you want an 8–12 second dramatic teaser hook clip to post as a YouTube Short, Instagram Reel, or prepend to your video:

```powershell
.\.venv\Scripts\python -m manhwa_studio.cli pro-cold-open -p data/projects/myst_might_mayhem/chapter_001 --scene scene_090
```

---

## 🍿 7. Compiling Full-Movie Marathons

Once you have rendered multiple chapters (e.g. Chapters 1, 2, and 3), compile them into a 1 to 2-hour full movie marathon with animated chapter bumpers and unified timestamps:

```powershell
.\.venv\Scripts\python -m manhwa_studio.cli marathon `
  --series "The Greatest Estate Developer" `
  --chapters "6,7,8,9,10" `
  -o exports/marathons/the_greatest_estate_developer_ch6_to_ch10_movie.mp4
```

.\.venv\Scripts\python -m manhwa_studio.cli marathon `
  --series "Nano Machine" `
  --chapters "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20" `
  --speed 1.25 `
  -o exports/marathons/nano_machine_ch1_to_ch20_movie_1.25x.mp4

---

## 📂 8. Where to Find Your Final Files

All final exports are organized cleanly inside:
`data/projects/{series_slug}/chapter_{number}/exports/`

For example, for Chapter 1:
- 🎬 **Clean Full Video:** [`data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_pro.mp4`](file:///e:/Python/Scapper/manhwa-story-studio/data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_pro.mp4)
- 🖼️ **Clean Thumbnail:** [`data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_thumbnail.jpg`](file:///e:/Python/Scapper/manhwa-story-studio/data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_thumbnail.jpg)
- ⚡ **Teaser Hook Clip:** [`data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_cold_open.mp4`](file:///e:/Python/Scapper/manhwa-story-studio/data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_cold_open.mp4)
- 📄 **YouTube Upload Kit:** [`data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_youtube_kit.txt`](file:///e:/Python/Scapper/manhwa-story-studio/data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_youtube_kit.txt)

---

## 🎭 9. Managing Different Manhwa Genres

The studio supports genre profiles for any manhwa:
- `murim` (Ancient martial arts, demon sects, dramatic strings)
- `system_hunter` (Solo Leveling style, dungeon portals, electronic synth)
- `dark_fantasy` (Gothic demons, deep organs, ominous brass)
- `romance_isekai` (Otome, royal reincarnation, acoustic piano)

```powershell
# List existing profiles:
python -m manhwa_studio.cli series-profile list

# Create a new series profile:
python -m manhwa_studio.cli series-profile create --series "Solo Leveling" --genre system_hunter
```

---

## 🔴 10. YouTube 24/7 Live Streaming

To stream any chapter or full marathon directly to YouTube Live:

```powershell
# Stream in a continuous 24/7 loop:
python -m manhwa_studio.cli live-stream -v data/projects/myst_might_mayhem/chapter_001/exports/myst_might_mayhem_ch001_pro.mp4 --key "YOUR_STREAM_KEY"
```

For full instructions, 1-click Windows batch files, and free Oracle Cloud 24/7 VPS deployment, see **[`live_stream/INSTRUCTIONS.md`](live_stream/INSTRUCTIONS.md)**.

---

## 📋 Quick Cheat Sheet (Daily Workflow)

| Step | Action | Command |
|---|---|---|
| **1** | Drop images | Copy raw chapter panels to `assets/inbox/ch1/` |
| **2** | Write script | `python -m manhwa_studio.cli process-inbox` |
| **3** | Render Video | `python -m manhwa_studio.cli pro-render -p data/projects/<series>/chapter_001` |
| **4** | Custom Thumbnail | `python -m manhwa_studio.cli pro-thumbnail -p data/projects/<series>/chapter_001 --scene 90` |
| **5** | Copy Metadata | Open `exports/<series>_ch001_youtube_kit.txt` and upload to YouTube! |
