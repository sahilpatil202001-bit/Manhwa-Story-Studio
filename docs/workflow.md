# Step-by-Step Production Workflow

There are two ways to produce videos:
1. **The Fast "Inbox Dropzone" Workflow** (Recommended for batching 5+ videos/day).
2. **The Manual Step-by-Step Workflow** (For custom granular control).

---

## Method A: The Fast Inbox Dropzone Workflow (Recommended)

### Step 1: Drop your chapter folder into the inbox
Create a folder inside `assets/inbox/` for each chapter and put your `.webp`, `.jpg`, or `.png` files inside:
```
assets/inbox/ch1/
    ├── 01.webp
    ├── 02.webp
    └── ...
assets/inbox/ch2/
    ├── 01.webp
    └── ...
```

### Step 2: Run the automated inbox processor
```powershell
python -m manhwa_studio.cli process-inbox
```
**What happens automatically:**
1. AI analyzes the cover/opening panels and chapter theme.
2. Generates an engaging, high-CTR YouTube Shorts title (e.g. *"He's The Purest Psycho In Murim!"*).
3. Creates a dramatic opening Hindi narration hook line.
4. Initializes `data/projects/myst_might_mayhem/chapter_001/` with all subdirectories.
5. Copies panels into `artwork/` and registers rights.
6. Generates thumbnail contact sheets and HTML review reports in `reports/`.
7. Builds the complete `scene_manifest.json` ready for your review.

*Tip:* If you want to automatically approve and render the full video end-to-end directly from the inbox:
```powershell
python -m manhwa_studio.cli process-inbox --auto-approve --render
```

---

## Method B: Manual Step-by-Step Workflow

### Step 1: Environment Check
Run the diagnostic doctor command:
```powershell
python -m manhwa_studio.cli doctor
```
Ensure Python, FFmpeg, FFprobe, and Pillow report `[OK]`.

---

### Step 2: Initialize a New Chapter Project
```powershell
python -m manhwa_studio.cli init-project --series "Myst, Might, Mayhem" --chapter 1 --title "Prologue"
```
This generates the project folder structure at `data/projects/myst_might_mayhem/chapter_001/`.

---

### Step 3: Add and Register Authorized Artwork
Copy authorized panel images into:
`data/projects/myst_might_mayhem/chapter_001/artwork/`

Register rights status:
```powershell
python -m manhwa_studio.cli register-artwork --project data/projects/myst_might_mayhem/chapter_001 --status permission_granted --reference "Contract/License reference"
```

---

### Step 4: Inspect Panels & Review Contact Sheet
```powershell
python -m manhwa_studio.cli inspect-images --project data/projects/myst_might_mayhem/chapter_001
```
Open `reports/artwork_review.html` and `reports/contact_sheet.jpg` in your browser to verify panel sequence and check for duplicate or extremely tall panels.

---

### Step 5: Generate Story Draft & Scene Manifest
```powershell
python -m manhwa_studio.cli create-script --project data/projects/myst_might_mayhem/chapter_001
```
Review `scripts/scene_manifest.json`. Edit narration text or motion presets as desired.

---

### Step 6: Approve the Manifest
Once the script is reviewed:
```powershell
python -m manhwa_studio.cli approve-script --project data/projects/myst_might_mayhem/chapter_001
```

---

### Step 7: Synthesize Hindi Narration Audio
```powershell
python -m manhwa_studio.cli generate-voice --project data/projects/myst_might_mayhem/chapter_001
```
Generates audio files in `audio/segments/` with hash-based caching.

---

### Step 8: Generate Subtitles
```powershell
python -m manhwa_studio.cli create-subtitles --project data/projects/myst_might_mayhem/chapter_001
```
Exports `subtitles/narration.srt` and styled `subtitles/narration.ass`.

---

### Step 9: Render Vertical MP4 Video
```powershell
python -m manhwa_studio.cli render --project data/projects/myst_might_mayhem/chapter_001
```
FFmpeg renders each segment, mixes narration and music with ducking, burns styled subtitles, and encodes the final 1080×1920 MP4 into `renders/`.

---

### Step 10: Validate Final Quality
```powershell
python -m manhwa_studio.cli validate-output --project data/projects/myst_might_mayhem/chapter_001
```
Opens `reports/production_qa_report.html` to confirm stream codecs, frame rate, and timing compliance.
