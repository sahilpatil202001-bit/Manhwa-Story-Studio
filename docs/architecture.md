# Manhwa Story Studio — System Architecture

## Overview

Manhwa Story Studio is an automated, maintainable, single-user video production pipeline that converts authorized manhwa chapter artwork into cinematic story-explainer vertical videos (1080 × 1920, 9:16, 30 FPS H.264/AAC MP4) with original Hindi narration, synchronized subtitles, background music ducking, and motion effects.

## High-Level Architecture

```
Authorized Artwork Panels (JPEG/PNG/WebP)
                  │
                  ▼
         [Image Ingestion] ──── Duplicate & Aspect Analysis ──► Contact Sheet & HTML Review
                  │
                  ▼
         [Story & Outline] ──── 5-Part Narrative Breakdown  ──► Scene Manifest (JSON)
                  │
                  ▼
         [User Approval Gate] ── Mandatory Manual Review
                  │
                  ▼
         [Voice Synthesis] ─── Provider Factory (Mock/Edge) ──► Audio Segments & Cache
                  │
                  ▼
       [Subtitle Generation] ── SRT & ASS with Mobile Margins ──► Subtitle Validator
                  │
                  ▼
       [FFmpeg Scene Engine] ── Motion Presets & Blurred Fill ──► Visual Segments
                  │
                  ▼
         [Audio Mixer] ─────── Narration + Ducked Music + SFX ──► Mixed Audio Track
                  │
                  ▼
       [Final Mux & Burn] ──── Concat + Subtitles + Faststart ──► Master MP4 (1080x1920)
                  │
                  ▼
       [Quality Assurance] ─── FFprobe Stream & Codec Check   ──► Production Report (HTML)
```

## Key Components

1. **Ingestion & Inspection (`manhwa_studio.ingestion`)**:
   - Natural numerical sorting of panels.
   - SHA-256 duplicate detection.
   - Extremely tall strip aspect ratio warnings (< 0.45:1).
   - Thumbnail contact sheets and HTML review reports.

2. **Rights Verification (`manhwa_studio.rights`)**:
   - Enforces explicit rights declarations (`owned`, `licensed`, `permission_granted`, `public_domain_verified`).
   - Rejects `unknown` and `prohibited` assets before any production rendering.
   - SHA-256 integrity verification prevents asset tampering.

3. **Story Analysis & Scene Manifest (`manhwa_studio.story`)**:
   - 5-part narrative arc: Hook, Setup, Conflict, Turning Point, Cliffhanger.
   - SceneManifest Pydantic model storing per-scene duration, image, crop, motion preset, and Hindi narration.
   - Strict `approved_by_user` gate preventing unreviewed audio generation.

4. **Voice Synthesis (`manhwa_studio.voice`)**:
   - Provider abstraction (`BaseTTSProvider`) with `MockTTSProvider` (offline sine PCM) and `EdgeTTSProvider` (free Microsoft Neural Hindi `hi-IN-MadhurNeural`).
   - Hash-based caching: skips re-generating audio when text, voice, and pitch parameters remain unchanged.
   - Duration-aware synchronization adjusting visual scene durations to prevent speech clipping.

5. **Subtitle Pipeline (`manhwa_studio.subtitles`)**:
   - UTF-8 Hindi SRT export and styled ASS export.
   - Mobile safe-zone margins (180px bottom offset to prevent Shorts overlay obstruction).
   - Strict timestamp sequence and non-overlapping validation.

6. **Rendering Engine (`manhwa_studio.rendering`)**:
   - Safe subprocess execution of FFmpeg and FFprobe with argument lists (never raw shell interpolation).
   - 9:16 vertical styling with blurred background fill or black letterboxing.
   - Motion presets: `static`, `slow_zoom_in`, `slow_zoom_out`, `pan_up`, `pan_down`.
   - Concat demuxer assembly and fast-start MP4 encoding.

7. **Quality Assurance (`manhwa_studio.quality`)**:
   - Automatic post-render probe checking width (1080), height (1920), fps (30), video codec (H.264), audio codec (AAC), and duration.
