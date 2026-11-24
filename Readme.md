# Project: Manhwa Story Studio — Complete Automated Video Production Pipeline

> 📖 **Quick Guide:** For a step-by-step user guide on how to add images, run commands, and generate videos, see **[HOW_TO_GENERATE_VIDEOS.md](HOW_TO_GENERATE_VIDEOS.md)**.

## 1. Your Role

Act as a senior Python engineer, video automation engineer, media pipeline architect, and QA engineer.

Build a complete, maintainable application that turns **authorized manhwa chapter artwork into cinematic story-explainer videos** with original Hindi narration, synchronized subtitles, background music, sound effects, motion effects, and final vertical MP4 rendering.

Do not only provide suggestions or pseudocode. Inspect the current repository, implement the application, execute it, run tests, fix errors, and document the verified workflow.

Work incrementally. Never claim a feature works unless you have tested it or clearly state why it could not be tested.

## 2. Primary Use Case

Create a video explaining one manhwa chapter per episode.

Initial production profile:

- Series: Myst, Might, Mayhem
- Initial chapter: Chapter 1 — Prologue
- Narration language: Hindi
- Voice style: deep, mature, cinematic, suspenseful
- Target duration: 180 seconds
- Video format: 9:16 vertical
- Resolution: 1080 × 1920
- Frame rate: 30 FPS
- Video codec: H.264
- Audio codec: AAC
- Container: MP4
- Narration style: original storytelling, not a verbatim reading of the chapter
- Music: appropriately licensed cinematic instrumental
- Artwork: only material the user owns, has permission to use, or is otherwise authorized to reproduce
- Initial mode: local, single-user production pipeline
- Operating system: Windows first, with cross-platform-compatible Python code where practical

The target duration must be configurable. A chapter must not be padded with invented story details just to reach 180 seconds. The application should warn when the story cannot support the target duration and offer a shorter cut.

Do not assume the user has permission to reuse artwork merely because an HTML chapter file is available.

## 3. Required Development Principles

1. Inspect the existing project before changing it.
2. Reuse working code where appropriate.
3. Use type hints, clear modules, structured logging, and meaningful exceptions.
4. Use pathlib for filesystem operations.
5. Use subprocess argument lists rather than shell string execution.
6. Validate all input files and external executable dependencies.
7. Avoid hard-coded absolute paths.
8. Avoid unnecessary frameworks and services.
9. Do not require a database for the initial version.
10. Do not use paid APIs unless the user explicitly configures them.
11. Do not download copyrighted artwork automatically from unauthorized sources.
12. Never bypass access controls, watermarks, DRM, or site restrictions.
13. Do not invent a chapter plot, dialogue, character details, or future events.
14. Make every major processing step independently runnable.
15. Build useful automated tests and a repeatable sample workflow.
16. Never overwrite original input files.
17. Make long-running tasks report progress and preserve useful logs.
18. Make failed stages resumable when their inputs have not changed.
19. Separate generated assets from source assets.
20. Implement real functionality rather than placeholder functions that report success.

## 4. Technology Stack

Use:

- Python 3.12 or a compatible supported Python version.
- FFmpeg and FFprobe for rendering, transcoding, audio mixing, and media validation.
- Pillow for image inspection, image preparation, and selected crop processing.
- Pydantic for configuration and scene-manifest validation.
- Typer for a command-line interface.
- pytest for automated tests.
- Ruff for linting and formatting.
- A configurable TTS provider adapter for Hindi speech synthesis.
- A configurable subtitle workflow using SRT and/or ASS.
- Optional MoviePy only if it adds a clear advantage; FFmpeg should remain the final rendering engine.

Use a lockfile or reproducible dependency configuration. Avoid unnecessary dependencies.

## 5. Project Structure

Create a maintainable structure similar to:

manhwa-story-studio/
  pyproject.toml
  README.md
  .env.example
  .gitignore
  config/
    default.yaml
  data/
    projects/
  assets/
    artwork/
    audio/
    fonts/
    sfx/
  output/
  logs/
  src/
    manhwa_studio/
      __init__.py
      cli.py
      config.py
      schemas.py
      logging_config.py
      pipeline.py
      project_manager.py
      rights.py
      ingestion/
        __init__.py
        image_manifest.py
        image_inspector.py
      story/
        __init__.py
        chapter_analyzer.py
        script_writer.py
        script_validator.py
      voice/
        __init__.py
        base.py
        provider_factory.py
        synthesis.py
      subtitles/
        __init__.py
        generate.py
        validate.py
      visuals/
        __init__.py
        crop.py
        motion.py
        transitions.py
      audio/
        __init__.py
        mix.py
        music.py
        sound_effects.py
      rendering/
        __init__.py
        ffmpeg.py
        segments.py
        final_video.py
      quality/
        __init__.py
        media_probe.py
        validate_output.py
      utils/
        __init__.py
        paths.py
        hashing.py
        timecodes.py
  tests/
    unit/
    integration/
    fixtures/
  scripts/
    check_environment.ps1
  docs/
    architecture.md
    workflow.md
    troubleshooting.md
    licensing.md

You may adjust the layout if the existing repository has a better established structure, but retain clear separation of responsibilities.

## 6. CLI Requirements

Implement a real CLI with commands such as:

python -m manhwa_studio.cli doctor

python -m manhwa_studio.cli init-project 
  --series "Myst, Might, Mayhem" 
  --chapter 1 
  --title "Prologue"

python -m manhwa_studio.cli inspect-images 
  --project data/projects/myst_might_mayhem/chapter_001

python -m manhwa_studio.cli validate-project 
  --project data/projects/myst_might_mayhem/chapter_001

python -m manhwa_studio.cli create-script 
  --project data/projects/myst_might_mayhem/chapter_001

python -m manhwa_studio.cli generate-voice 
  --project data/projects/myst_might_mayhem/chapter_001

python -m manhwa_studio.cli create-subtitles 
  --project data/projects/myst_might_mayhem/chapter_001

python -m manhwa_studio.cli render 
  --project data/projects/myst_might_mayhem/chapter_001

python -m manhwa_studio.cli validate-output 
  --project data/projects/myst_might_mayhem/chapter_001

python -m manhwa_studio.cli run 
  --project data/projects/myst_might_mayhem/chapter_001

Implement equivalent Windows-friendly commands if multiline shell syntax differs.

Each command must validate its prerequisites, return a meaningful exit code, and explain failures.

The doctor command must check Python, FFmpeg, FFprobe, writable directories, configured TTS providers, and optional dependencies.

## 7. Project Configuration

Create a validated YAML configuration with fields for:

- Series name
- Chapter number and title
- Target duration
- Width and height
- FPS
- Video codec and quality
- Audio codec and bitrate
- Narration language
- Voice provider and voice identifier
- Speech rate and optional provider-supported style controls
- Music and sound-effect file paths
- Subtitle language, font, size, and position
- Transition defaults
- Crop and motion settings
- Loudness targets
- Output directory
- Artwork authorization status and evidence/reference
- Whether the video is intended for Shorts or standard YouTube
- Whether captions should be burned into the video
- Whether an external subtitle file should also be exported

Never put API keys directly in YAML, Python source, or logs. Read secrets from environment variables or a suitable secret store.

Provide .env.example with variable names and fake example values only.

## 8. Rights and Asset Management

The project must require an explicit rights declaration before production artwork is used.

Store for each source asset:

- Asset identifier
- Local file path
- SHA-256 hash
- Dimensions and format
- Source description
- Rights status
- License or permission reference where applicable
- Attribution requirements
- Whether commercial use is allowed
- Whether modifications are allowed

Possible statuses include:

- owned
- licensed
- permission_granted
- public_domain_verified
- other_authorized_use
- unknown
- prohibited

Unknown and prohibited assets must not be used in a production render. Allow clearly labeled synthetic fixtures for tests, separate from production artwork.

Do not automatically interpret a website URL or downloaded HTML file as proof of authorization.

## 9. Image Ingestion and Inspection

Accept authorized image files from a local directory or a user-prepared image manifest.

Supported image formats should include JPEG, PNG, and WebP.

Implement:

- Image discovery
- Stable deterministic sorting
- Duplicate detection using hashes
- Corrupt-image detection
- Dimension and aspect-ratio reporting
- Extremely tall image warnings
- Transparent-image handling
- Rights-status validation
- A contact sheet or HTML review report
- A JSON report of available images
- Manual selection of panels for the video

Never automatically treat every page as a scene.

Never silently stretch an image to fit 9:16.

For extremely tall pages, support manually defined crops using normalized coordinates in the range 0–1. Preserve the original image and save crop metadata separately.

Optional automated crop suggestions may be added later, but they must be reviewable and must not replace manual approval.

## 10. Story Analysis and Original Script

Implement a structured, human-reviewable workflow.

Input:

- Chapter notes
- Selected panel descriptions
- Character names confirmed by the user
- Optional user-supplied text or OCR output that they are authorized to process
- Desired target duration
- Narration language and style

Output:

- A chapter summary
- A scene outline
- Original narration in Hindi
- Scene-to-panel assignments
- Estimated scene duration
- Subtitle segments
- Opening hook
- Main conflict
- Turning point
- Closing explanation and cliffhanger
- A list of facts requiring verification

Do not claim the application can accurately understand an arbitrary chapter merely by reading HTML metadata.

If no compatible AI model is configured, support a manual-script mode. A configured model provider may assist with summarization, but all generated claims must remain reviewable.

Do not reproduce the full chapter or translate all dialogue verbatim. Produce transformative, concise commentary and original narration. Do not invent unsupported events.

The story validator should flag:

- Missing scene descriptions
- Unresolved character names
- Claims without supporting notes
- Repeated narration
- Empty or excessively long scenes
- Target duration mismatch
- A script that is too short for the configured speech rate

Do not generate final narration audio until the user has approved the script.

## 11. Scene Manifest Schema

Use Pydantic models to validate a JSON scene manifest.

Each scene should support:

- Stable scene ID
- Scene purpose
- Start time or duration
- One or more selected images
- Crop coordinates
- Motion preset
- Transition type
- Narration text
- Audio cues
- Subtitle text
- Optional title overlays
- Supporting panel IDs
- Verification notes

Prefer duration-based scene timing and calculate start times deterministically. Reject overlapping or negative timing values unless explicitly supported by a timeline model.

The manifest must be sufficient to rerender a video without manually editing Python code.

## 12. Hindi Voice Generation

Build a provider-independent TTS interface.

The interface should support:

- Provider configuration
- Voice ID configuration
- Hindi language selection
- Speech rate configuration
- Optional style controls if the provider actually supports them
- Chunked synthesis for long scripts
- Retry logic with bounded retries
- Timeouts
- Cache keys based on text and voice configuration
- Audio format validation
- Provider error handling
- Estimated cost reporting where supported
- A local or prerecorded-audio mode for development

Never assume a provider supports emotional control just because it supports text-to-speech.

Never fake deep cinematic voice effects by silently altering the spoken text.

Provide a mock TTS adapter for unit tests and a real adapter only for a documented provider whose API is configured.

Generate one audio segment per narration unit when possible. Store a manifest mapping narration units to generated audio files.

Measure actual speech duration. Do not assume a fixed words-per-minute rate will perfectly predict TTS timing.

If a provider requires a paid account or API key, explain the setup and do not incur charges without user configuration.

## 13. Narration and Scene Synchronization

Implement duration-aware alignment.

For each narration segment:

1. Generate or load the voice audio.
2. Measure its actual duration.
3. Assign it to the corresponding scene or group of scenes.
4. Compare the audio length with the visual timing.
5. Adjust scene duration where possible.
6. Flag scenes that cannot fit naturally.
7. Never accelerate speech excessively just to hit a fixed target.

Use optional forced alignment or speech-recognition timestamps when available.

If no alignment provider is configured, use explicit timing and provide a manual correction workflow.

The final video should have no unintentionally clipped narration.

## 14. Vertical Visual Composition

Use FFmpeg for final rendering and Pillow for selected image preparation.

Requirements:

- Output 1080 × 1920
- Aspect ratio 9:16
- 30 FPS by default
- High-quality scaling
- No image stretching
- Configurable letterboxing or blurred-background fill
- Configurable slow zoom and pan
- Crop-coordinate support
- Per-scene motion settings
- Configurable transitions
- Correct display of tall panels
- Preservation of key faces and actions
- No accidental black frames between segments
- Stable color and pixel format

Implement a small set of predictable motion presets:

- static
- slow_zoom_in
- slow_zoom_out
- pan_up
- pan_down
- pan_left
- pan_right

Motion must be bounded so the important subject does not move out of frame.

Support static images as the baseline. Avoid excessive transitions and effects.

## 15. Subtitles

Create Hindi subtitles from the approved narration.

Support:

- SRT export
- Optional ASS styling
- Optional burned-in captions
- Configurable font and position
- Safe margins for mobile video
- Sentence-level or phrase-level segments
- Unicode Hindi support
- Subtitle timestamp validation
- Detection of missing, negative, or overlapping timestamps
- Caption readability checks

Do not assume Whisper automatically produces perfect Hindi punctuation or spelling. Provide a review step.

Do not use fonts unless their license permits the intended use. If a configured font is unavailable, provide a clear error or safe fallback.

## 16. Audio Mixing

Mix:

- Narration
- Background music
- Optional sound effects
- Optional ambience

Requirements:

- Narration must remain intelligible.
- Music volume must be configurable.
- Use ducking when available and appropriate.
- Use fades and bounded transitions.
- Avoid clipping.
- Validate all audio durations.
- Prevent accidental repeated narration.
- Handle mono and stereo input correctly.
- Preserve a clean stereo output by default.

Provide a sensible initial mix profile, but measure and listen to the actual output.

Treat loudness values as configurable targets rather than guarantees of perceived quality. Validate true peak and loudness with available FFmpeg tools.

Do not include copyrighted music or effects without permission.

## 17. Rendering Engine

Implement a robust FFmpeg rendering pipeline.

Stages:

1. Validate the project.
2. Prepare selected images and crops.
3. Generate visual scene segments.
4. Validate each segment.
5. Concatenate segments.
6. Prepare narration, music, and sound effects.
7. Mix audio.
8. Render captions.
9. Encode the final MP4.
10. Run post-render validation.
11. Save a production report.

Use subprocess argument lists, not shell interpolation.

Capture stderr and useful diagnostics. Set timeouts where appropriate.

Use deterministic temporary file names and clean up only generated intermediate files.

Preserve source assets.

Avoid unnecessary re-encoding where safe, but prioritize compatibility and correctness over a fragile stream-copy optimization.

Make rendering resumable when inputs and settings have not changed.

## 18. Final Video Specifications

Default profile:

- Resolution: 1080 × 1920
- FPS: 30
- Codec: H.264
- Pixel format: yuv420p
- Audio codec: AAC
- Audio bitrate: 192 kbps
- Fast-start MP4 metadata
- Configurable CRF
- Configurable output duration
- Optional SRT sidecar
- Optional project manifest sidecar

Use FFprobe to validate the rendered result.

The final duration should be within an explicitly configured tolerance of the intended duration. Warn if the rendered result has unintended silent gaps or clipped audio.

Do not classify a video as eligible for Shorts based only on its resolution. Check the current intended platform constraints separately, and never assume that a vertical video is automatically monetizable.

## 19. Quality Assurance

Implement automated validation for:

- Missing source images
- Invalid authorization status
- Invalid configuration
- Missing audio
- Missing fonts
- Broken manifests
- Corrupt media
- Unsupported media formats
- Incorrect resolution
- Incorrect aspect ratio
- Incorrect FPS
- Incorrect video codec
- Missing audio stream
- Audio clipping indicators where measurable
- Incorrect duration
- Unexpected black frames where detection is available
- Missing subtitle file
- Invalid subtitle timing
- Missing narration segments
- Missing output files

Create a human-review report with:

- Scene thumbnails
- Scene durations
- Narration text
- Selected assets
- Rights metadata
- Audio sources
- Validation warnings
- Final media metadata

Automated checks do not replace listening to the narration and watching the finished video.

## 20. Project State and Resumability

Track each stage in a local JSON state file.

Suggested statuses:

- pending
- running
- succeeded
- failed
- needs_review
- skipped

Record:

- Start and completion times
- Input hashes
- Output paths
- Relevant configuration hash
- Error messages
- Tool versions
- Stage duration

Do not rerun expensive TTS synthesis when the text and provider configuration are unchanged and a valid cached result exists.

Invalidate downstream stages when their upstream inputs change.

Write state files atomically to avoid corruption.

## 21. Testing

Use pytest.

Unit tests must cover:

- Configuration validation
- Scene schema validation
- Timecode conversion
- Image sorting
- Image hash calculation
- Rights checks
- Crop-coordinate validation
- Audio duration validation
- Subtitle validation
- Output-path handling
- Resume and cache logic
- FFmpeg command construction

Integration tests should use generated synthetic images and audio, not real copyrighted chapters.

Where FFmpeg is available, render a short synthetic test video and verify it with FFprobe.

Mock paid TTS providers. Do not call external paid services in the automated test suite.

Include a test that verifies the scene durations total the expected duration.

Include a test for missing input files and a test for an unauthorized asset.

## 22. Documentation

Write a complete README covering:

- Project purpose
- Prerequisites
- Windows installation
- FFmpeg and FFprobe installation verification
- Virtual environment setup
- Dependency installation
- Configuration
- Artwork rights declaration
- Project creation
- Image inspection
- Script review
- Hindi TTS configuration
- Subtitle generation
- Rendering
- Quality checks
- Output locations
- Troubleshooting
- Cost considerations
- Licensing and copyright limitations

Document the actual implemented commands. Do not document features that do not exist yet as if they were complete.

Include a short end-to-end example using synthetic, authorized test assets.

## 23. Development Workflow

Follow these phases in order.

### Phase A — Inspect and plan

Inspect the repository, Python version, available FFmpeg executables, existing files, and project conventions.

Produce a short implementation plan and list any blockers.

Do not stop after producing the plan. Continue into implementation.

### Phase B — Foundation

Create the package, configuration, schemas, CLI, logging, project manager, rights validation, and environment diagnostics.

Run unit tests.

### Phase C — Image preparation

Implement image inspection, deterministic sorting, hash-based duplicate detection, manual crop metadata, and contact-sheet generation.

Test with synthetic images.

### Phase D — Story workflow

Implement scene-manifest validation, original script storage, verification notes, and manual approval.

Do not fabricate a plot when no verified chapter analysis is available.

### Phase E — Voice and subtitles

Implement the TTS abstraction, mock provider, audio validation, cache, subtitle export, and review workflow.

Test without paid API calls.

### Phase F — Rendering

Implement FFmpeg scene rendering, transitions, audio mixing, subtitle integration, final encoding, and FFprobe validation.

Render a short synthetic video end to end.

### Phase G — Integration and documentation

Run linting, unit tests, integration tests, and the complete synthetic workflow.

Fix errors before declaring the MVP ready.

Document real commands and remaining limitations.

### Phase H — First real pilot

Prepare a project for Myst, Might, Mayhem Chapter 1 using authorized artwork and a verified scene outline.

If authorization, verified story notes, or configured narration assets are missing, stop before the affected production stage and explain what is needed. Do not bypass those requirements.

## 24. Acceptance Criteria

The MVP is complete only when:

1. The project installs in a clean virtual environment.
2. The doctor command reports real environment status.
3. A project can be initialized from the CLI.
4. The image inspector generates a valid report.
5. Unauthorized production artwork is rejected.
6. A manually approved scene manifest passes validation.
7. A mock TTS provider works in tests.
8. Subtitle export works and timestamps validate.
9. A short synthetic vertical video renders through FFmpeg.
10. Audio mixing produces a valid audio stream.
11. FFprobe confirms the final video's dimensions, frame rate, codecs, and duration.
12. The test suite passes, with unavailable integration tests explicitly identified.
13. Documentation matches the implementation.
14. The pipeline can resume from valid intermediate outputs.
15. No unsupported claim of successful real-chapter production is made.

A full three-minute render of real chapter artwork is a separate pilot acceptance step and must not be claimed complete merely because the synthetic integration test passes.

## 25. Final Report

At the end, report:

- What was implemented
- Actual project tree
- Commands executed
- Tests passed and failed
- FFmpeg version and relevant environment findings
- Whether a synthetic MP4 was successfully generated
- Exact path to any verified output
- Any external configuration still required
- Any features not implemented
- Exact next command the user should run

Do not dump every source file into the final response if the repository contains them. Summarize the implementation and point to the actual files.

Start now by inspecting the existing repository and environment. Then implement the application incrementally, test it, fix issues, and provide the final report.