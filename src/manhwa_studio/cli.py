"""
Command Line Interface for Manhwa Story Studio using Typer and Rich.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from manhwa_studio.config import AppConfig, load_config
from manhwa_studio.ingestion.image_inspector import ImageInspector
from manhwa_studio.logging_config import setup_logging
from manhwa_studio.pipeline import ProductionPipeline
from manhwa_studio.project_manager import ProjectManager
from manhwa_studio.rendering.ffmpeg import get_ffmpeg_path, get_ffprobe_path, is_nvenc_available
from manhwa_studio.rights import RightsManager
from manhwa_studio.schemas import AssetMetadata, RightsStatus
from manhwa_studio.utils.hashing import compute_file_sha256

app = typer.Typer(
    name="manhwa-studio",
    help="Manhwa Story Studio: Cinematic vertical video production pipeline for manhwa story explainers.",
    no_args_is_help=True,
)
console = Console()
logger = setup_logging()


@app.command()
def doctor() -> None:
    """Check environment dependencies: Python, FFmpeg, FFprobe, and TTS providers."""
    table = Table(title="Manhwa Story Studio - Environment Diagnostics", border_style="cyan")
    table.add_column("Component", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    # 1. Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    table.add_row("Python", "[green]OK[/green]", f"Version {py_ver}")

    # 2. FFmpeg
    try:
        ffmpeg_exe = get_ffmpeg_path()
        table.add_row("FFmpeg", "[green]OK[/green]", str(ffmpeg_exe))
    except Exception as e:
        table.add_row("FFmpeg", "[red]MISSING[/red]", str(e))

    # 3. FFprobe
    try:
        ffprobe_exe = get_ffprobe_path()
        table.add_row("FFprobe", "[green]OK[/green]", str(ffprobe_exe))
    except Exception as e:
        table.add_row("FFprobe", "[red]MISSING[/red]", str(e))

    # 4. Pillow
    try:
        import PIL
        table.add_row("Pillow", "[green]OK[/green]", f"Version {PIL.__version__}")
    except Exception as e:
        table.add_row("Pillow", "[red]ERROR[/red]", str(e))

    # 5. Edge-TTS (Hindi Neural Voice)
    try:
        import edge_tts
        table.add_row("Edge-TTS", "[green]OK[/green]", "Neural Hindi voices supported")
    except Exception as e:
        table.add_row("Edge-TTS", "[yellow]OPTIONAL[/yellow]", f"Not installed ({e})")

    # 6. NVIDIA GPU Hardware Acceleration (NVENC)
    try:
        if is_nvenc_available():
            table.add_row("GPU Acceleration (NVENC)", "[bold green]ACTIVE[/bold green]", "h264_nvenc hardware video encoding enabled")
        else:
            table.add_row("GPU Acceleration (NVENC)", "[yellow]CPU FALLBACK[/yellow]", "Using libx264 software encoding")
    except Exception as e:
        table.add_row("GPU Acceleration (NVENC)", "[yellow]UNAVAILABLE[/yellow]", str(e))

    console.print(table)


@app.command()
def check_models(
    api_key: Optional[str] = typer.Option(None, "--key", "-k", help="Optional Gemini API key override"),
) -> None:
    """Inspect and test all Gemini models supported by your API key in real time."""
    import json
    import os
    import time
    import urllib.error
    import urllib.request
    from pathlib import Path

    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        env_p = Path(".env")
        if env_p.exists():
            for line in env_p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == "GEMINI_API_KEY":
                        key = v.strip()
                        break

    if not key:
        console.print("[bold red]Error:[/bold red] GEMINI_API_KEY not found in environment or .env file.")
        raise typer.Exit(1)

    first_key = [k.strip("\"' ") for k in key.split(",") if k.strip()][0]
    console.print(f"[bold cyan]Querying Google Gemini Models API with key ({first_key[:8]}...{first_key[-4:]})[/bold cyan]")
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    try:
        req = urllib.request.Request(url, headers={"x-goog-api-key": first_key})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            all_models = data.get("models", [])
    except Exception as exc:
        console.print(f"[bold red]Failed to fetch models from Google API:[/bold red] {exc}")
        raise typer.Exit(1)

    table = Table(title="Google Gemini Models Availability", border_style="cyan")
    table.add_column("Model Name", style="bold")
    table.add_column("Status")
    table.add_column("Latency / Details")

    candidate_names = [
        "gemini-3.8-flash",
        "gemini-3.8-flash-tts",
        "gemini-3.8-flash-lite-tts",
        "gemini-3.5-flash-lite",
        "gemini-3-flash-preview",
        "gemini-flash-latest",
        "gemini-3.1-flash-tts-preview",
        "gemini-pro-latest",
    ]

    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
        "generationConfig": {"maxOutputTokens": 5},
    }

    for name in candidate_names:
        test_url = f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent"
        t0 = time.time()
        try:
            test_payload = (
                {
                    "contents": [{"role": "user", "parts": [{"text": "नमस्ते"}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "languageCode": "hi-IN",
                            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Puck"}},
                        },
                    },
                }
                if name.endswith("-tts") or "-tts-" in name
                else payload
            )
            treq = urllib.request.Request(
                test_url,
                data=json.dumps(test_payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": first_key},
            )
            with urllib.request.urlopen(treq, timeout=8) as tresp:
                elapsed = round(time.time() - t0, 2)
                table.add_row(name, "[bold green]ACTIVE (Working)[/bold green]", f"Responded in {elapsed}s")
        except urllib.error.HTTPError as he:
            if he.code == 404:
                table.add_row(name, "[red]DEPRECATED (404)[/red]", "Retired by Google for new keys")
            elif he.code == 503:
                table.add_row(name, "[yellow]HIGH DEMAND (503)[/yellow]", "Temporary Google traffic spike")
            elif he.code == 429:
                table.add_row(name, "[red]QUOTA LIMIT (429)[/red]", "Rate or daily limit exceeded")
            else:
                table.add_row(name, f"[red]HTTP {he.code}[/red]", he.reason)
        except Exception as exc:
            table.add_row(name, "[yellow]TIMEOUT / ERROR[/yellow]", str(exc)[:40])

    console.print(table)
    console.print(
        Panel.fit(
            "[bold green]Recommended Action:[/bold green]\n"
            "Use models with [bold green]ACTIVE (Working)[/bold green] status in [cyan]llm_title_generator.py[/cyan].\n"
            "Fastest & most stable: [bold cyan]gemini-3.5-flash-lite[/bold cyan]",
            title="Summary",
        )
    )


@app.command()
def init_project(
    series: str = typer.Option("Myst, Might, Mayhem", "--series", "-s", help="Series name"),
    chapter: int = typer.Option(1, "--chapter", "-c", help="Chapter number"),
    title: str = typer.Option("Prologue", "--title", "-t", help="Chapter title"),
    base_dir: Path = typer.Option(Path("data/projects"), "--base-dir", "-b", help="Base directory for projects"),
) -> None:
    """Initialize a new chapter video project structure and default config."""
    default_cfg = Path("config/default.yaml")
    pm = ProjectManager.create_project(
        base_dir=base_dir,
        series=series,
        chapter=chapter,
        title=title,
        default_config_path=default_cfg if default_cfg.exists() else None,
    )
    console.print(
        Panel.fit(
            f"[bold green]Project Initialized Successfully![/bold green]\n"
            f"Series: [cyan]{series}[/cyan]\n"
            f"Chapter: [cyan]{chapter} ({title})[/cyan]\n"
            f"Directory: [yellow]{pm.project_dir}[/yellow]\n\n"
            f"Next step: Place authorized artwork in:\n"
            f"[dim]{pm.artwork_dir}[/dim]",
            title="Manhwa Story Studio",
        )
    )


@app.command()
def register_artwork(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path"),
    status: RightsStatus = typer.Option(RightsStatus.PERMISSION_GRANTED, "--status", help="Rights authorization status"),
    reference: str = typer.Option("Authorized production materials", "--reference", help="Permission license or contract reference"),
    attribution: str = typer.Option("Original artwork by respective copyright holders", "--attribution", help="Attribution text"),
) -> None:
    """Register and declare rights status for artwork files in project artwork directory."""
    pm = ProjectManager(project)
    rm = RightsManager(pm.rights_path)
    inspector = ImageInspector(pm.artwork_dir)
    images = inspector.discover_images()

    if not images:
        console.print(f"[yellow]No images found in {pm.artwork_dir} to register.[/yellow]")
        return

    from PIL import Image
    registered_count = 0
    for img_path in images:
        h = compute_file_sha256(img_path)
        with Image.open(img_path) as im:
            w, h_dim = im.size
            fmt = im.format or img_path.suffix.lstrip(".").upper()

        meta = AssetMetadata(
            asset_id=img_path.name,
            file_path=str(img_path),
            sha256=h,
            width=w,
            height=h_dim,
            format=fmt,
            source_description=f"Panel from {pm.load_config().project.series}",
            rights_status=status,
            license_reference=reference,
            attribution=attribution,
            allow_commercial=False,
            allow_modifications=True,
        )
        rm.register_asset(meta)
        registered_count += 1

    console.print(f"[green]Registered rights for {registered_count} assets with status: '{status.value}'[/green]")


@app.command()
def inspect_images(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path"),
) -> None:
    """Inspect chapter artwork, check dimensions, detect duplicates and corrupt files."""
    pipeline = ProductionPipeline(project)
    pipeline.run_ingestion()
    console.print("[green]Image inspection complete. Reports generated in project 'reports/' directory.[/green]")


@app.command()
def validate_project(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path"),
) -> None:
    """Check project files, configuration, and rights compliance."""
    pm = ProjectManager(project)
    cfg = pm.load_config()
    rm = RightsManager(pm.rights_path)
    inspector = ImageInspector(pm.artwork_dir)
    images = inspector.discover_images()

    table = Table(title=f"Project Health Check: {cfg.project.series} Ch.{cfg.project.chapter}")
    table.add_column("Check")
    table.add_column("Result")

    table.add_row("Project Config", "[green]VALID[/green]")
    table.add_row("Artwork Count", f"{len(images)} images")

    rights_ok, rights_errs = rm.validate_production_readiness(images)
    if rights_ok:
        table.add_row("Artwork Rights", "[green]AUTHORIZED[/green]")
    else:
        table.add_row("Artwork Rights", f"[red]UNAUTHORIZED ({len(rights_errs)} issues)[/red]")

    manifest_file = pm.scripts_dir / "scene_manifest.json"
    if manifest_file.exists():
        table.add_row("Scene Manifest", "[green]EXISTS[/green]")
    else:
        table.add_row("Scene Manifest", "[yellow]NOT CREATED YET[/yellow]")

    console.print(table)


@app.command()
def create_script(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path"),
    part: int = typer.Option(1, "--part", help="Part number (e.g. 1 or 2)"),
    total_parts: int = typer.Option(1, "--total-parts", help="Total parts to split chapter into (e.g. 2 for 2-min Shorts)"),
) -> None:
    """Generate chapter outline and scene manifest with original Hindi narration."""
    pipeline = ProductionPipeline(project)
    pipeline.run_script(part=part, total_parts=total_parts)
    part_str = f" for Part {part}/{total_parts}" if total_parts > 1 else ""
    console.print(f"[green]Scene manifest generated{part_str}! Review scripts/scene_manifest.json and approve before voice synthesis.[/green]")


@app.command()
def approve_script(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path"),
) -> None:
    """Mark the scene manifest as approved by user for production rendering."""
    pm = ProjectManager(project)
    manifest_file = pm.scripts_dir / "scene_manifest.json"
    if not manifest_file.exists():
        console.print(f"[red]Manifest file not found: {manifest_file}[/red]")
        raise typer.Exit(1)

    from manhwa_studio.story.script_writer import load_scene_manifest, save_scene_manifest
    manifest = load_scene_manifest(manifest_file)
    manifest.approved_by_user = True
    save_scene_manifest(manifest, manifest_file)
    console.print("[green]Scene manifest marked as APPROVED by user.[/green]")


@app.command()
def generate_voice(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path"),
) -> None:
    """Synthesize Hindi narration speech audio for approved scene manifest."""
    pipeline = ProductionPipeline(project)
    pipeline.run_voice()
    console.print("[green]Narration audio synthesized and cached successfully.[/green]")


@app.command()
def create_subtitles(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path"),
) -> None:
    """Generate SRT and styled ASS subtitle files with safe-zone margin."""
    pipeline = ProductionPipeline(project)
    pipeline.run_subtitles()
    console.print("[green]Subtitles generated and validated successfully.[/green]")


@app.command()
def render(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path"),
) -> None:
    """Render 1080x1920 vertical MP4 video through FFmpeg."""
    pipeline = ProductionPipeline(project)
    out_file = pipeline.run_render()
    console.print(f"[bold green]Video rendered successfully:[/bold green] [cyan]{out_file}[/cyan]")


@app.command()
def validate_output(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path"),
) -> None:
    """Run post-render FFprobe verification on the final MP4 output."""
    pipeline = ProductionPipeline(project)
    pipeline.run_validation()
    console.print("[green]Output validation passed! All technical requirements met.[/green]")


@app.command()
def run(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Approve scene manifest automatically for batch/testing"),
    part: int = typer.Option(1, "--part", help="Part number (e.g. 1 or 2)"),
    total_parts: int = typer.Option(1, "--total-parts", help="Total parts to split chapter into"),
) -> None:
    """Execute complete end-to-end production pipeline."""
    pipeline = ProductionPipeline(project)
    pipeline.run_ingestion()
    pipeline.run_script(part=part, total_parts=total_parts)

    if auto_approve:
        from manhwa_studio.story.script_writer import load_scene_manifest, save_scene_manifest
        m_file = pipeline.pm.scripts_dir / "scene_manifest.json"
        manifest = load_scene_manifest(m_file)
        manifest.approved_by_user = True
        save_scene_manifest(manifest, m_file)

    pipeline.run_voice()
    pipeline.run_subtitles()
    pipeline.run_render()
    pipeline.run_validation()
    console.print("[bold green]Complete production pipeline succeeded![/bold green]")


@app.command()
def process_inbox(
    inbox: Path = typer.Option(Path("assets/inbox"), "--inbox", "-i", help="Inbox dropzone directory, specific manhwa folder, or chapter folder path"),
    series: Optional[str] = typer.Option(None, "--series", "-s", help="Series name filter or override"),
    chapter: Optional[int] = typer.Option(None, "--chapter", "-c", help="Process only a specific chapter number (e.g. 1)"),
    chapter_start: Optional[int] = typer.Option(None, "--chapter-start", help="First chapter in an inclusive processing range"),
    chapter_end: Optional[int] = typer.Option(None, "--chapter-end", help="Last chapter in an inclusive processing range"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Automatically approve generated scene manifest"),
    render: bool = typer.Option(False, "--render", "-r", help="Automatically render complete video end-to-end"),
) -> None:
    """Scan inbox for dropped chapter folders, use AI to suggest title & Hindi hook, setup projects, and optionally render."""
    from manhwa_studio.pipeline import process_inbox_batches

    if not inbox.exists():
        inbox.mkdir(parents=True, exist_ok=True)

    console.print(f"[cyan]Scanning inbox dropzone: {inbox.resolve()}[/cyan]")
    projects = process_inbox_batches(
        inbox_dir=inbox,
        series_name=series,
        chapter=chapter,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        auto_approve=auto_approve,
        auto_render=render,
    )

    if not projects:
        console.print(
            Panel.fit(
                "[yellow]No chapter folders found in assets/inbox/.[/yellow]\n\n"
                "To use the inbox workflow:\n"
                "1. Drop a folder like [cyan]assets/inbox/ch1/[/cyan] containing your .webp / .jpg images.\n"
                "2. Run [green]python -m manhwa_studio.cli process-inbox[/green]",
                title="Inbox Dropzone",
            )
        )
        return

    table = Table(title="Processed Inbox Batches")
    table.add_column("Chapter Project Path", style="green")
    table.add_column("Status")

    for proj in projects:
        status_text = "[bold green]RENDERED[/bold green]" if render else "[green]READY FOR REVIEW[/green]"
        table.add_row(str(proj), status_text)

    console.print(table)


@app.command()
def clean_chapters(
    folders: Optional[List[str]] = typer.Argument(None, help="Specific chapter folders or numbers (e.g. ch2 ch3 OR 2 3)"),
    path: Path = typer.Option(Path("assets/inbox"), "--path", "-p", help="Directory where chapter folders are located"),
    keep_zip: bool = typer.Option(False, "--keep-zip", help="Keep source zip archives after extracting"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview actions without extracting or deleting anything"),
) -> None:
    """Extract clean manhwa chapter images from zip archives, filter out ads/junk, and remove zip files."""
    from manhwa_studio.ingestion.chapter_cleaner import clean_and_unpack_inbox

    target_dir = path.resolve()
    console.print(f"[cyan]Scanning for chapter zip archives in: {target_dir}[/cyan]")
    num_cleaned = clean_and_unpack_inbox(
        root_dir=target_dir,
        folders=folders,
        delete_zip=not keep_zip,
        dry_run=dry_run,
    )
    if num_cleaned > 0:
        console.print(f"[bold green]Successfully cleaned and unpacked {num_cleaned} chapter(s)![/bold green]")
    else:
        console.print("[yellow]No zip archives needed cleaning.[/yellow]")


@app.command()
def slice_strips(
    folder: Path = typer.Option(..., "--folder", "-f", help="Folder containing long manhwa strips to slice"),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Backup original long strips to _raw_strips/"),
) -> None:
    """Slice tall scrolling webtoon strips along natural panel gutters into 9:16 vertical panels."""
    from manhwa_studio.ingestion.strip_slicer import slice_chapter_directory

    if not folder.exists():
        console.print(f"[red]Directory not found: {folder}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Analyzing and slicing tall strips in: {folder.resolve()}...[/cyan]")
    panels = slice_chapter_directory(folder, backup_originals=backup)

    if not panels:
        console.print("[yellow]No unsliced strips found or already sliced.[/yellow]")
        return

    console.print(
        Panel.fit(
            f"[bold green]Successfully sliced into {len(panels)} clean panels![/bold green]\n"
            f"Panels: [cyan]panel_001.webp[/cyan] to [cyan]panel_{len(panels):03d}.webp[/cyan]\n"
            f"Original strips backed up in: [dim]{folder / '_raw_strips'}[/dim]",
            title="Smart Strip Slicer",
        )
    )


@app.command()
def batch_generate(
    project: Path = typer.Option(..., "--project", "-p", help="Project directory path (e.g. data/projects/myst_might_mayhem/chapter_001)"),
    total_parts: Optional[int] = typer.Option(None, "--total-parts", help="Total parts to split chapter into (Default: automatically calculated based on chapter panel count)"),
    start_part: int = typer.Option(1, "--start-part", help="Part number to start from (useful when resuming)"),
    export_dir: Path = typer.Option(Path("exports"), "--export-dir", "-e", help="Base export directory for organized output"),
    auto_approve: bool = typer.Option(True, "--auto-approve/--no-auto-approve", help="Automatically approve scripts for unattended batch rendering"),
) -> None:
    """
    Generate all sequence videos, thumbnails, and YouTube metadata for all parts of a chapter in a single command.
    """
    from manhwa_studio.export.publisher import package_chapter_part
    from manhwa_studio.ingestion.image_inspector import ImageInspector
    from manhwa_studio.story.script_writer import load_scene_manifest, save_scene_manifest

    pipeline = ProductionPipeline(project)
    cfg = pipeline.pm.load_config()
    chapter = cfg.project.chapter
    series = cfg.project.series

    pipeline.run_ingestion()

    # Automatically calculate optimal parts based on chapter artwork count
    inspector = ImageInspector(pipeline.pm.artwork_dir)
    images = inspector.discover_images()
    num_panels = len(images)

    if total_parts is None or total_parts <= 0:
        if num_panels <= 110:
            calc_parts = 1
        elif num_panels <= 220:
            calc_parts = 2
        elif num_panels <= 330:
            calc_parts = 3
        else:
            calc_parts = max(1, round(num_panels / 95))
        total_parts = calc_parts
        parts_note = f"[bold green]Auto-detected {num_panels} panels -> Split into {total_parts} parts (~{num_panels // total_parts} panels/part, optimal 2-min Shorts length)[/bold green]"
    else:
        parts_note = f"Manual override: [yellow]{total_parts} parts[/yellow] ({num_panels} total panels)"

    console.print(
        Panel.fit(
            f"[bold cyan]Starting Automated Batch Generation for {series}[/bold cyan]\n"
            f"Chapter: [yellow]{chapter}[/yellow] | Total Panels: [yellow]{num_panels}[/yellow]\n"
            f"Parts Plan: {parts_note}\n"
            f"Export Directory: [green]{export_dir.resolve()}[/green]",
            title="Batch Production Pipeline",
        )
    )

    results = []
    for part in range(start_part, total_parts + 1):
        console.rule(f"[bold yellow]Producing Chapter {chapter} - Part {part}/{total_parts}[/bold yellow]")
        
        # 1. Script generation
        pipeline.run_script(part=part, total_parts=total_parts)

        # 2. Approval
        m_file = pipeline.pm.scripts_dir / "scene_manifest.json"
        manifest = load_scene_manifest(m_file)
        if auto_approve:
            manifest.approved_by_user = True
            save_scene_manifest(manifest, m_file)

        # 3. Voice synthesis
        pipeline.run_voice()

        # 4. Subtitle generation
        pipeline.run_subtitles()

        # 5. Video rendering
        rendered_mp4 = pipeline.run_render()

        # 6. Post-render validation
        pipeline.run_validation()

        # Reload final manifest with updated audio durations
        final_manifest = load_scene_manifest(m_file)

        # 7. Package video, thumbnail, and YouTube metadata
        pkg = package_chapter_part(
            project_dir=project,
            chapter=chapter,
            part=part,
            total_parts=total_parts,
            rendered_mp4=rendered_mp4,
            manifest=final_manifest,
            artwork_dir=pipeline.pm.artwork_dir,
            base_export_dir=export_dir,
        )

        # Mirror inside project's exports folder as well
        package_chapter_part(
            project_dir=project,
            chapter=chapter,
            part=part,
            total_parts=total_parts,
            rendered_mp4=rendered_mp4,
            manifest=final_manifest,
            artwork_dir=pipeline.pm.artwork_dir,
            base_export_dir=project / "exports",
        )

        results.append(pkg)
        console.print(f"[bold green]✓ Part {part}/{total_parts} complete![/bold green]")

    # Print summary table
    summary_table = Table(title=f"All Parts Successfully Generated for {series} (Chapter {chapter})")
    summary_table.add_column("Part", style="cyan")
    summary_table.add_column("Video (MP4)", style="green")
    summary_table.add_column("Thumbnail (JPG)", style="yellow")
    summary_table.add_column("Metadata (TXT)", style="magenta")

    for i, r in enumerate(results, 1):
        summary_table.add_row(
            f"Part {i}",
            str(r["video"].resolve()),
            str(r["thumbnail"].resolve()),
            str(r["metadata"].resolve()),
        )

    console.print(summary_table)
    console.print(f"\n[bold green]All sequence videos, thumbnails, and YouTube metadata ready in: [cyan]{export_dir.resolve()}[/cyan]![/bold green]")


@app.command()
def to_widescreen(
    input_video: Path = typer.Option(..., "--input", "-i", help="Path to 9:16 vertical video"),
    output_video: Optional[Path] = typer.Option(None, "--output", "-o", help="Output 16:9 widescreen video path"),
) -> None:
    """Convert any 9:16 vertical video into standard 16:9 widescreen with cinematic bokeh blur background."""
    import subprocess
    from manhwa_studio.rendering.ffmpeg import get_ffmpeg_path

    if not input_video.exists():
        console.print(f"[bold red]Input video not found:[/bold red] {input_video}")
        raise typer.Exit(1)

    if output_video is None:
        out_dir = input_video.parent.parent.parent / "widescreen_16x9" / input_video.parent.name
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = input_video.stem
        output_video = out_dir / f"{stem}_16x9.mp4"
    else:
        output_video.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe = str(get_ffmpeg_path())
    console.print(f"[bold cyan]Converting to 16:9 Widescreen...[/bold cyan]")
    console.print(f"Source: [yellow]{input_video}[/yellow]")
    console.print(f"Destination: [green]{output_video}[/green]")

    filter_str = (
        "[0:v]scale=480:270:force_original_aspect_ratio=increase,crop=480:270,"
        "boxblur=luma_radius=12:luma_power=2,scale=1920:1080,eq=brightness=-0.15[bg];"
        "[0:v]scale=-1:1080[fg];"
        "[bg][fg]overlay=(W-w)/2:0,format=yuv420p[v]"
    )

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", str(input_video),
        "-filter_complex", filter_str,
        "-map", "[v]",
        "-map", "0:a",
        "-c:v", "h264_nvenc",
        "-preset", "p5",
        "-cq", "21",
        "-c:a", "copy",
        str(output_video),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            # Fallback to libx264 if NVENC is unavailable
            cmd[cmd.index("h264_nvenc")] = "libx264"
            cmd[cmd.index("-cq")] = "-crf"
            cmd[cmd.index("-preset")] = "-preset"
            cmd[cmd.index("p5")] = "faster"
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                console.print(f"[bold red]FFmpeg conversion failed:[/bold red]\n{res.stderr[-500:]}")
                raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[bold red]Error running conversion:[/bold red] {exc}")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold green]16:9 Widescreen Video Ready![/bold green]\n"
        f"File: [cyan]{output_video.resolve()}[/cyan]",
        title="Widescreen Converter"
    ))


def _atempo_filters(speed: float) -> str:
    """Build valid FFmpeg atempo filters for any positive playback speed."""
    factors: list[float] = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={factor:.8g}" for factor in factors)


@app.command("speed-video")
def speed_video(
    input_video: Path = typer.Option(..., "--input", "-i", help="Existing MP4 video to speed up or slow down"),
    speed: float = typer.Option(..., "--speed", "-s", help="Playback-speed multiplier, e.g. 1.5"),
    output_video: Optional[Path] = typer.Option(None, "--output", "-o", help="Output MP4 path; defaults to <name>_<speed>x.mp4"),
) -> None:
    """Change an existing video speed without re-running the Pro render pipeline."""
    import subprocess
    from manhwa_studio.rendering.ffmpeg import get_ffmpeg_path

    if not input_video.exists():
        console.print(f"[bold red]Input video not found:[/bold red] {input_video}")
        raise typer.Exit(1)
    if speed <= 0:
        console.print("[bold red]Speed must be greater than zero.[/bold red]")
        raise typer.Exit(1)

    if output_video is None:
        output_video = input_video.with_name(f"{input_video.stem}_{speed:g}x{input_video.suffix}")
    output_video.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe = str(get_ffmpeg_path())
    filter_str = f"[0:v]setpts=PTS/{speed:g}[v];[0:a]{_atempo_filters(speed)}[a]"
    base_cmd = [
        ffmpeg_exe, "-y", "-i", str(input_video),
        "-filter_complex", filter_str,
        "-map", "[v]", "-map", "[a]",
    ]

    # Use the NVIDIA encoder when available, then fall back to broadly
    # compatible software encoding on systems without NVENC.
    nvenc_cmd = base_cmd + [
        "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21",
        "-c:a", "aac", "-b:a", "192k", str(output_video),
    ]
    result = subprocess.run(nvenc_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        x264_cmd = base_cmd + [
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", str(output_video),
        ]
        result = subprocess.run(x264_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[bold red]Speed conversion failed:[/bold red]\n{result.stderr[-700:]}")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold green]Speed-adjusted video ready![/bold green]\n"
        f"Speed: [magenta]{speed:g}x[/magenta]\n"
        f"File: [cyan]{output_video.resolve()}[/cyan]",
        title="Video Speed Converter",
    ))


@app.command()
def merge_parts(
    folder: Path = typer.Option(..., "--folder", "-f", help="Folder containing sequence videos to merge in alphabetical order"),
    output_video: Optional[Path] = typer.Option(None, "--output", "-o", help="Output merged video path"),
    outro: bool = typer.Option(True, "--outro/--no-outro", help="Append To Be Continued video at the end of the merged video"),
) -> None:
    """Losslessly merge multiple sequence video parts (Part 1 + Part 2) into one full video in seconds."""
    import subprocess
    from manhwa_studio.env_config import get_studio_outro_video_path
    from manhwa_studio.rendering.ffmpeg import get_ffmpeg_path
    from manhwa_studio.studio_pro.marathon_engine import MarathonEngine
    from manhwa_studio.studio_pro.series_manager import SeriesManager

    if not folder.exists():
        console.print(f"[bold red]Folder not found:[/bold red] {folder}")
        raise typer.Exit(1)

    mp4s = sorted(list(folder.glob("*.mp4")))
    # Filter out previously merged full files or prepared outro files if any
    mp4s = [p for p in mp4s if "full" not in p.name.lower() and not p.name.startswith("outro_to_be_continued")]

    if len(mp4s) < 2:
        console.print(f"[yellow]Found fewer than 2 videos in {folder}. At least 2 parts are needed to merge.[/yellow]")
        raise typer.Exit(1)

    if output_video is None:
        output_video = folder / f"{folder.name}_full_chapter.mp4"

    # Optionally append To Be Continued outro at the very end of the merged video
    prepared_outro: Optional[Path] = None
    if outro:
        outro_source = get_studio_outro_video_path()
        if outro_source.exists():
            try:
                sm = SeriesManager()
                engine = MarathonEngine(sm.get_or_create_profile("Default"))
                w, h, audio_sr, audio_layout = engine._probe_video_specs(mp4s[-1])
                prepared_outro = folder / f"outro_to_be_continued_{w}x{h}.tmp.mp4"
                outro_clip = engine.prepare_outro_clip(
                    prepared_outro,
                    width=w,
                    height=h,
                    audio_sr=audio_sr,
                    audio_layout=audio_layout,
                    source_outro=outro_source,
                )
                if outro_clip and outro_clip.exists():
                    mp4s.append(outro_clip)
            except Exception as exc:
                console.print(f"[yellow]Note: Could not prepare outro for merge ({exc}); merging parts without outro.[/yellow]")

    ffmpeg_exe = str(get_ffmpeg_path())
    list_file = folder / "concat_list.tmp.txt"
    lines = [f"file '{p.resolve().as_posix()}'" for p in mp4s]
    list_file.write_text("\n".join(lines), encoding="utf-8")

    console.print(f"[bold cyan]Merging {len(mp4s)} videos seamlessly (zero gap)...[/bold cyan]")
    for p in mp4s:
        console.print(f"  • {p.name}")

    cmd = [
        ffmpeg_exe,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output_video),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if list_file.exists():
            list_file.unlink()
        if prepared_outro and prepared_outro.exists():
            prepared_outro.unlink()
        if res.returncode != 0:
            console.print(f"[bold red]FFmpeg merge failed:[/bold red]\n{res.stderr[-500:]}")
            raise typer.Exit(1)
    except Exception as exc:
        if list_file.exists():
            list_file.unlink()
        if prepared_outro and prepared_outro.exists():
            prepared_outro.unlink()
        console.print(f"[bold red]Error running merge:[/bold red] {exc}")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold green]Full Chapter Video Merged Successfully![/bold green]\n"
        f"File: [cyan]{output_video.resolve()}[/cyan]",
        title="Video Merger"
    ))


@app.command()
def pro_render(
    project: Path = typer.Option(..., "--project", "-p", help="Project chapter directory path (e.g. data/projects/myst_might_mayhem/chapter_001)"),
    profile_name: Optional[str] = typer.Option(None, "--profile", help="Series profile slug or genre (e.g. murim_template, system_hunter_template)"),
    rebuild_segments: bool = typer.Option(False, "--rebuild-segments", "-r", help="Force rebuild all visual segments with dynamic camera FX"),
    burn_subtitles: bool = typer.Option(False, "--burn-subtitles", "-b", help="Burn subtitles into the video (default: False for clean artwork)"),
    thumbnail_captions: bool = typer.Option(False, "--thumbnail-captions", help="Add chapter badge and teaser text on thumbnail (default: False for clean artwork)"),
    thumbnail_scene: Optional[str] = typer.Option(None, "--thumbnail-scene", "-ts", help="Specific scene ID to feature on thumbnail (e.g. scene_055)"),
    thumbnail_panel: Optional[Path] = typer.Option(None, "--thumbnail-panel", "-tp", help="Specific panel file to feature on thumbnail"),
    cold_open: bool = typer.Option(True, "--cold-open/--no-cold-open", help="Prepend a dramatic climax teaser hook (using Gemini Puck voice) to maximize YouTube viewer retention"),
    outro: bool = typer.Option(False, "--outro/--no-outro", help="Append the 'To Be Continued' outro video at the end of this single chapter (default: False; Marathon appends it once at the very end)"),
    export_short: bool = typer.Option(True, "--export-short/--no-short", help="Auto-export a 45s 9:16 Vertical YouTube Short from the chapter climax"),
    speed: float = typer.Option(1.0, "--speed", "-s", help="Playback speed multiplier for the final video (e.g. 1.5 for 50%% faster, 2.0 for double speed). Uses FFmpeg setpts+atempo."),
) -> None:
    """Render with full Pro Suite: multi-voice character dubbing, mood BGM auto-ducking, kinetic pop subtitles, and camera FX."""
    from manhwa_studio.studio_pro.pro_pipeline import ProPipeline
    from manhwa_studio.studio_pro.series_manager import SeriesManager

    if not project.exists():
        console.print(f"[bold red]Project directory not found:[/bold red] {project}")
        raise typer.Exit(1)

    sm = SeriesManager()
    profile = sm.load_profile(profile_name) if profile_name else None

    speed_label = f"{speed}x" if speed != 1.0 else "Normal (1x)"
    console.print(Panel.fit(
        f"[bold cyan]Launching Manhwa Studio Pro Production Suite[/bold cyan]\n"
        f"Project: [yellow]{project.resolve()}[/yellow]\n"
        f"Features: Single Constant Gemini Puck Voice | Dynamic BGM & SFX | Camera FX\n"
        f"Captions in Video: [magenta]{'BURNT-IN' if burn_subtitles else 'CLEAN (None)'}[/magenta] | "
        f"Thumbnail Captions: [magenta]{'YES' if thumbnail_captions else 'CLEAN (None)'}[/magenta] | "
        f"Cold Open Teaser: [magenta]{'ENABLED' if cold_open else 'OFF'}[/magenta] | "
        f"To Be Continued Outro: [magenta]{'ENABLED' if outro else 'OFF'}[/magenta] | "
        f"Speed: [magenta]{speed_label}[/magenta]",
        title="Manhwa Studio Pro"
    ))

    pipeline = ProPipeline(project, series_profile=profile)
    results = pipeline.run_full_pro_production(
        force_rebuild_segments=rebuild_segments,
        burn_subtitles=burn_subtitles,
        include_thumbnail_captions=thumbnail_captions,
        thumbnail_scene_id=thumbnail_scene,
        thumbnail_panel=thumbnail_panel,
        enable_cold_open=cold_open,
        enable_outro=outro,
        export_short=export_short,
        speed=speed,
    )

    short_line = (
        f"• 9:16 Climax Short: [cyan]{results['short_video'].resolve()}[/cyan]\n"
        if "short_video" in results and results["short_video"].exists()
        else ""
    )
    console.print(Panel.fit(
        f"[bold green]Pro Production Suite Rendered Successfully![/bold green]\n\n"
        f"• Final Video ({f'{speed}x speed' if speed != 1.0 else 'normal speed'}): [cyan]{results['video'].resolve()}[/cyan]\n"
        f"{short_line}"
        f"• Master Soundtrack: [cyan]{results['master_audio'].resolve()}[/cyan]\n"
        f"• Kinetic Subtitles: [cyan]{results['subtitles'].resolve()}[/cyan]\n"
        f"• Pro Thumbnail: [cyan]{results['thumbnail'].resolve()}[/cyan]\n"
        f"• YouTube Upload Kit: [yellow]{results['youtube_kit'].resolve()}[/yellow]",
        title="Pro Suite Export Complete"
    ))


@app.command("pro-render-range")
def pro_render_range(
    series_slug: str = typer.Option(..., "--series", "-s", help="Project series folder slug (e.g. the_greatest_estate_developer)"),
    chapter_start: int = typer.Option(..., "--chapter-start", help="First chapter in the inclusive render range"),
    chapter_end: int = typer.Option(..., "--chapter-end", help="Last chapter in the inclusive render range"),
    projects_dir: Path = typer.Option(Path("data/projects"), "--projects-dir", help="Base directory containing series project folders"),
    profile_name: Optional[str] = typer.Option(None, "--profile", help="Series profile slug or genre"),
    rebuild_segments: bool = typer.Option(False, "--rebuild-segments", "-r", help="Force rebuild all visual segments"),
    burn_subtitles: bool = typer.Option(False, "--burn-subtitles", "-b", help="Burn subtitles into videos"),
    thumbnail_captions: bool = typer.Option(False, "--thumbnail-captions", help="Add captions to thumbnails"),
    cold_open: bool = typer.Option(True, "--cold-open/--no-cold-open", help="Add a cold-open teaser"),
    outro: bool = typer.Option(False, "--outro/--no-outro", help="Append the 'To Be Continued' outro video at the end of each standalone chapter (default: False; Marathon appends it once at the very end)"),
    export_short: bool = typer.Option(True, "--export-short/--no-short", help="Auto-export a 45s 9:16 Vertical YouTube Short for each chapter"),
    speed: float = typer.Option(1.0, "--speed", "-p", help="Playback speed multiplier"),
    stop_on_error: bool = typer.Option(False, "--stop-on-error", help="Stop instead of continuing after a failed chapter"),
) -> None:
    """Render an inclusive series chapter range sequentially with the Pro Suite."""
    from manhwa_studio.studio_pro.pro_pipeline import ProPipeline
    from manhwa_studio.studio_pro.series_manager import SeriesManager

    if chapter_start < 1 or chapter_end < chapter_start:
        console.print("[bold red]Chapter range must start at 1 or greater, and end at or after the start.[/bold red]")
        raise typer.Exit(1)

    sm = SeriesManager()
    profile = sm.load_profile(profile_name) if profile_name else None
    completed: list[int] = []
    skipped: list[int] = []
    failed: list[tuple[int, str]] = []

    console.print(
        f"[bold cyan]Sequential Pro render:[/bold cyan] {series_slug}, "
        f"Chapters {chapter_start}–{chapter_end}"
    )

    for chapter in range(chapter_start, chapter_end + 1):
        project = projects_dir / series_slug / f"chapter_{chapter:03d}"
        if not project.exists():
            skipped.append(chapter)
            console.print(f"[yellow]Skipping Ch.{chapter}: project not found at {project}[/yellow]")
            continue

        console.print(f"\n[bold cyan]--- Pro rendering Ch.{chapter} ({len(completed) + len(failed) + 1}/{chapter_end - chapter_start + 1}) ---[/bold cyan]")
        try:
            pipeline = ProPipeline(project, series_profile=profile)
            pipeline.run_full_pro_production(
                force_rebuild_segments=rebuild_segments,
                burn_subtitles=burn_subtitles,
                include_thumbnail_captions=thumbnail_captions,
                enable_cold_open=cold_open,
                enable_outro=outro,
                export_short=export_short,
                speed=speed,
            )
            completed.append(chapter)
            console.print(f"[bold green]✓ Ch.{chapter} Pro render complete.[/bold green]")
        except Exception as exc:
            failed.append((chapter, str(exc)))
            console.print(f"[bold red]Ch.{chapter} failed:[/bold red] {exc}")
            if stop_on_error:
                break

    console.print(
        f"\n[bold]Pro render range finished.[/bold] "
        f"Completed: {completed or 'none'} | Skipped: {skipped or 'none'} | "
        f"Failed: {[chapter for chapter, _ in failed] or 'none'}"
    )
    if failed:
        raise typer.Exit(1)


@app.command()
def pro_thumbnail(
    project: Path = typer.Option(..., "--project", "-p", help="Project chapter directory path (e.g. data/projects/myst_might_mayhem/chapter_001)"),
    scene: Optional[str] = typer.Option(None, "--scene", "-s", help="Specific scene ID to feature (e.g. scene_090 or 90)"),
    panel: Optional[str] = typer.Option(None, "--panel", help="Specific panel file path or name (e.g. panel_090.webp)"),
    captions: bool = typer.Option(False, "--captions", help="Include text badges and teaser captions (default: False for clean artwork)"),
    hook: Optional[str] = typer.Option(None, "--hook", help="Custom Hindi teaser text (only used when --captions is enabled)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Custom output thumbnail JPG path"),
) -> None:
    """Generate or re-generate a YouTube thumbnail from a specific scene without text clutter (clean artwork default)."""
    from manhwa_studio.studio_pro.pro_pipeline import ProPipeline
    from manhwa_studio.story.script_writer import load_scene_manifest

    if not project.exists():
        console.print(f"[bold red]Project directory not found:[/bold red] {project}")
        raise typer.Exit(1)

    pipeline = ProPipeline(project)
    m_file = pipeline.pm.scripts_dir / "scene_manifest.json"
    manifest = load_scene_manifest(m_file)
    thumb = pipeline.run_pro_thumbnail(
        manifest=manifest,
        specific_scene_id=scene,
        specific_panel=panel,
        include_captions=captions,
        custom_hook=hook,
        custom_output=output,
    )
    console.print(Panel.fit(
        f"[bold green]Thumbnail Generated Successfully![/bold green]\n"
        f"• File: [cyan]{thumb.resolve()}[/cyan]\n"
        f"• Mode: [magenta]{'With Captions' if captions else 'Clean Artwork (No text)'}[/magenta]\n"
        f"• Scene / Panel: [yellow]{scene or panel or 'Auto-Detected Dramatic Climax'}[/yellow]",
        title="Pro Thumbnail Ready"
    ))


@app.command()
def pro_youtube_kit(
    project: Path = typer.Option(..., "--project", "-p", help="Project chapter directory path (e.g. data/projects/myst_might_mayhem/chapter_001)"),
    cold_open_seconds: float = typer.Option(0.0, "--cold-open-seconds", help="Duration of cold open teaser in seconds if present"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Custom output txt path"),
) -> None:
    """Generate high-CTR YouTube titles, SEO description, chapter timestamps, and tags."""
    from manhwa_studio.studio_pro.pro_pipeline import ProPipeline
    from manhwa_studio.story.script_writer import load_scene_manifest

    if not project.exists():
        console.print(f"[bold red]Project directory not found:[/bold red] {project}")
        raise typer.Exit(1)

    pipeline = ProPipeline(project)
    m_file = pipeline.pm.scripts_dir / "scene_manifest.json"
    manifest = load_scene_manifest(m_file)
    kit = pipeline.run_youtube_kit(manifest, cold_open_duration=cold_open_seconds, custom_output=output)

    console.print(Panel.fit(
        f"[bold green]YouTube Publishing Kit Generated Successfully![/bold green]\n\n"
        f"• Kit File: [cyan]{kit.resolve()}[/cyan]\n"
        f"• Features: 3 High-CTR Titles | Full SEO Description | Clickable Timestamps | Target Tags",
        title="YouTube Kit Ready"
    ))


@app.command()
def pro_cold_open(
    project: Path = typer.Option(..., "--project", "-p", help="Project chapter directory path"),
    scene: Optional[str] = typer.Option(None, "--scene", "-s", help="Specific climax scene ID (e.g. scene_090)"),
    hook: Optional[str] = typer.Option(None, "--hook", help="Custom dramatic teaser narration text"),
) -> None:
    """Generate a high-tension 8-12s teaser clip with impact zoom, bass drop, and hook voiceover."""
    from manhwa_studio.studio_pro.pro_pipeline import ProPipeline
    from manhwa_studio.story.script_writer import load_scene_manifest

    if not project.exists():
        console.print(f"[bold red]Project directory not found:[/bold red] {project}")
        raise typer.Exit(1)

    pipeline = ProPipeline(project)
    m_file = pipeline.pm.scripts_dir / "scene_manifest.json"
    manifest = load_scene_manifest(m_file)
    teaser, dur = pipeline.run_cold_open(manifest, preferred_scene_id=scene, custom_hook=hook)
    if not teaser:
        console.print("[bold red]Failed to generate cold open.[/bold red]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold green]Cold Open Teaser Video Generated![/bold green]\n\n"
        f"• File: [cyan]{teaser.resolve()}[/cyan]\n"
        f"• Duration: [yellow]{dur:.1f}s[/yellow]\n"
        f"• Purpose: High-retention flash-forward hook for the first 10 seconds of YouTube video.",
        title="Cold Open Teaser Ready"
    ))


@app.command()
def marathon(
    series: str = typer.Option("Myst, Might, Mayhem", "--series", "-s", help="Series name or slug"),
    chapters: str = typer.Option("1,2,3", "--chapters", "-c", help="Comma-separated chapter numbers, e.g. '1,2,3'"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output marathon video file path"),
    no_bumpers: bool = typer.Option(True, "--no-bumpers/--bumpers", help="Disable chapter transition bumpers for seamless zero-gap marathon playback"),
    outro: bool = typer.Option(True, "--outro/--no-outro", help="Append the 'To Be Continued' video at the very end of the marathon"),
    speed: float = typer.Option(1.0, "--speed", help="Select Pro-rendered chapter videos at this speed (e.g. 1.5)"),
) -> None:
    """Compile multiple rendered chapters into a seamless gapless full-movie marathon compilation with YouTube timestamps and 'To Be Continued' ending."""
    from manhwa_studio.studio_pro.marathon_engine import MarathonEngine
    from manhwa_studio.studio_pro.series_manager import SeriesManager

    sm = SeriesManager()
    profile = sm.get_or_create_profile(series)
    engine = MarathonEngine(profile)

    ch_list = [int(x.strip()) for x in chapters.split(",") if x.strip().isdigit()]
    if not ch_list:
        console.print("[bold red]Please provide valid comma-separated chapter numbers, e.g. --chapters 1,2,3[/bold red]")
        raise typer.Exit(1)
    if speed <= 0:
        console.print("[bold red]Speed must be greater than zero.[/bold red]")
        raise typer.Exit(1)

    if output is None:
        out_dir = Path("exports") / "marathons"
        out_dir.mkdir(parents=True, exist_ok=True)
        output = out_dir / f"{profile.series_slug}_marathon_ch{ch_list[0]}_to_ch{ch_list[-1]}.mp4"

    console.print(f"[bold cyan]Compiling Seamless Gapless Marathon Video for '{series}' Chapters {ch_list}...[/bold cyan]")
    out_vid, meta = engine.compile_marathon(
        ch_list,
        output,
        include_bumpers=not no_bumpers,
        include_outro=outro,
        speed=speed,
    )

    console.print(Panel.fit(
        f"[bold green]Full-Movie Marathon Compilation Ready![/bold green]\n\n"
        f"• Video: [cyan]{out_vid.resolve()}[/cyan]\n"
        f"• Gap Between Chapters: [magenta]{'NONE (Seamless Flow)' if no_bumpers else 'Bumper Transitions'}[/magenta]\n"
        f"• Ending Outro: [magenta]{'To Be Continued Appended' if outro else 'None'}[/magenta]\n"
        f"• Timestamps / Metadata: [yellow]{out_vid.with_suffix('.timestamps.txt').resolve()}[/yellow]",
        title="Marathon Engine"
    ))


@app.command()
def live_stream(
    video: Path = typer.Option(..., "--video", "-v", help="Path to MP4 video or marathon file to stream"),
    stream_key: Optional[str] = typer.Option(None, "--key", "-k", help="YouTube RTMP Stream Key (or set in .env)"),
    loop: bool = typer.Option(True, "--loop/--no-loop", help="Loop the video indefinitely for 24/7 continuous broadcast"),
) -> None:
    """Broadcast an exported manhwa video or marathon directly to YouTube Live via RTMP."""
    import os
    from live_stream.streamer import run_stream

    key = stream_key or os.getenv("YOUTUBE_STREAM_KEY")
    if not key:
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("YOUTUBE_STREAM_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not key:
        console.print("[bold red]Please provide your YouTube Stream Key via --key or YOUTUBE_STREAM_KEY in .env[/bold red]")
        raise typer.Exit(1)

    if not video.exists():
        console.print(f"[bold red]Video file not found:[/bold red] {video}")
        raise typer.Exit(1)

    run_stream(video, key, loop=loop)





@app.command()
def series_profile(
    action: str = typer.Argument("list", help="Action: list, show, or create"),
    slug: Optional[str] = typer.Option(None, "--slug", help="Profile slug name"),
    series_name: Optional[str] = typer.Option(None, "--series", help="Full series title"),
    genre: str = typer.Option("murim", "--genre", help="Genre: murim, system_hunter, dark_fantasy, romance_isekai"),
) -> None:
    """Manage series profiles for different manhwa genres, voice casting rosters, and BGM themes."""
    from manhwa_studio.studio_pro.series_manager import SeriesManager

    sm = SeriesManager()

    if action == "list":
        profiles = sm.list_profiles()
        table = Table(title="Available Series Profiles")
        table.add_column("Profile Slug", style="cyan")
        table.add_column("File Path", style="green")

        for p_slug in profiles:
            p_file = sm.profiles_dir / f"{p_slug}.yaml"
            table.add_row(p_slug, str(p_file.resolve()))

        console.print(table)

    elif action == "show":
        if not slug:
            console.print("[bold red]Please specify --slug <name> to show.[/bold red]")
            raise typer.Exit(1)
        profile = sm.load_profile(slug)
        if not profile:
            console.print(f"[bold red]Profile '{slug}' not found.[/bold red]")
            raise typer.Exit(1)

        import yaml
        console.print(Panel.fit(yaml.safe_dump(profile.model_dump(), sort_keys=False, allow_unicode=True), title=f"Profile: {profile.series_name}"))

    elif action == "create":
        if not series_name:
            console.print("[bold red]Please specify --series <title> to create a profile.[/bold red]")
            raise typer.Exit(1)
        created = sm.get_or_create_profile(series_name, genre=genre)
        console.print(f"[bold green]Created series profile for '{created.series_name}' (Genre: {created.genre}) at: {sm.profiles_dir / f'{created.series_slug}.yaml'}[/bold green]")


@app.command("modernize-scripts")
def modernize_scripts(
    series_slug: str = typer.Option(..., "--series", "-s", help="Series project folder slug (e.g. the_greatest_estate_developer, nano_machine)"),
    chapter: Optional[int] = typer.Option(None, "--chapter", "-c", help="Specific chapter number (or omit to upgrade all unrendered scripted chapters)"),
    chapter_start: Optional[int] = typer.Option(None, "--chapter-start", help="Optional range start"),
    chapter_end: Optional[int] = typer.Option(None, "--chapter-end", help="Optional range end"),
    mode: str = typer.Option("rewrite", "--mode", "-m", help="'rewrite' (fast Gemini text rewrite to Hinglish) or 'recreate' (delete & re-run Vision from panels)"),
    projects_dir: Path = typer.Option(Path("data/projects"), "--projects-dir", help="Base projects directory"),
) -> None:
    """Upgrade unrendered chapter scripts from pure/old Hindi into energetic Modern Hinglish (Hindi + English words) and clear old audio."""
    from manhwa_studio.pipeline import ProductionPipeline
    from manhwa_studio.story.llm_title_generator import modernize_existing_manifest_to_hinglish
    from manhwa_studio.story.script_writer import load_scene_manifest, save_scene_manifest

    s_dir = projects_dir / series_slug
    if not s_dir.exists():
        console.print(f"[bold red]Series folder not found:[/bold red] {s_dir}")
        raise typer.Exit(1)

    target_dirs: List[Path] = []
    for ch_dir in sorted(s_dir.iterdir()):
        if not ch_dir.is_dir() or not ch_dir.name.startswith("chapter_"):
            continue
        try:
            ch_num = int(ch_dir.name.split("_")[1])
        except Exception:
            continue

        if chapter is not None and ch_num != chapter:
            continue
        if chapter_start is not None and ch_num < chapter_start:
            continue
        if chapter_end is not None and ch_num > chapter_end:
            continue

        m_file = ch_dir / "scripts" / "scene_manifest.json"
        renders_dir = ch_dir / "renders"
        has_render = renders_dir.exists() and any(f.stat().st_size > 50000 for f in renders_dir.glob("final_video*.mp4"))

        # If no specific chapter was forced, only touch chapters that are NOT rendered yet!
        if chapter is None and chapter_start is None and has_render:
            continue
        if chapter is None and chapter_start is None and mode == "rewrite" and m_file.exists():
            try:
                import json as _json
                if _json.loads(m_file.read_text(encoding="utf-8")).get("modernized_hinglish"):
                    continue
            except Exception:
                pass
        if m_file.exists() or mode == "recreate":
            target_dirs.append(ch_dir)

    if not target_dirs:
        console.print(f"[yellow]No unrendered scripted chapters found for '{series_slug}'.[/yellow]")
        return

    console.print(
        f"[bold cyan]Modernizing {len(target_dirs)} chapter(s) for '{series_slug}' (mode={mode})...[/bold cyan]"
    )
    for idx, ch_dir in enumerate(target_dirs, 1):
        console.print(f"\n[cyan][{idx}/{len(target_dirs)}] Upgrading {ch_dir.name} to Energetic Hinglish...[/cyan]")
        try:
            if mode == "recreate":
                # Delete old script, checkpoint, and cached audio, then re-run Gemini Vision from panels
                for old_f in [
                    ch_dir / "scripts" / "scene_manifest.json",
                    ch_dir / "scripts" / "screenplay_checkpoint.json",
                ]:
                    if old_f.exists():
                        old_f.unlink(missing_ok=True)
                audio_dir = ch_dir / "audio"
                if audio_dir.exists():
                    for mp3 in audio_dir.glob("*.mp3"):
                        mp3.unlink(missing_ok=True)
                pipe = ProductionPipeline(ch_dir)
                pipe.run_script()
                m_file = ch_dir / "scripts" / "scene_manifest.json"
                if m_file.exists():
                    manifest = load_scene_manifest(m_file)
                    manifest.approved_by_user = True
                    save_scene_manifest(manifest, m_file)
                console.print(f"[bold green]✓ Re-created Hinglish script from panels for {ch_dir.name}[/bold green]")
            else:
                count = modernize_existing_manifest_to_hinglish(ch_dir)
                console.print(f"[bold green]✓ Rewrote {count} scenes into Energetic Hinglish for {ch_dir.name}[/bold green]")
        except Exception as ch_err:
            console.print(f"[bold red]✗ Error on {ch_dir.name}: {ch_err} (continuing to next chapter...)[/bold red]")


@app.command("social-pack")
def social_pack(
    project: Path = typer.Option(..., "--project", "-p", help="Project chapter directory path (e.g. data/projects/nano_machine/chapter_001)"),
    overlays: bool = typer.Option(True, "--overlays/--clean", help="Include series badge & headline overlays on post images"),
    reel_duration: float = typer.Option(45.0, "--reel-duration", "-d", help="Duration in seconds for the 9:16 Instagram Reel / YouTube Short video"),
    reel_start: Optional[float] = typer.Option(None, "--reel-start", help="Optional custom start second in the chapter video (auto-detects climax if omitted)"),
) -> None:
    """Generate YouTube Community Post (1:1 Image + Poll), Instagram 4-Slide Carousel (4:5), and 9:16 Vertical Reel/Short video."""
    from manhwa_studio.story.script_writer import load_scene_manifest
    from manhwa_studio.studio_pro.pro_pipeline import ProPipeline
    from manhwa_studio.studio_pro.social_media_director import SocialMediaDirector

    if not project.exists():
        console.print(f"[bold red]Project directory not found:[/bold red] {project}")
        raise typer.Exit(1)

    pipeline = ProPipeline(project)
    m_file = pipeline.pm.scripts_dir / "scene_manifest.json"
    if not m_file.exists():
        console.print(f"[bold red]scene_manifest.json not found in:[/bold red] {m_file}")
        raise typer.Exit(1)

    manifest = load_scene_manifest(m_file)
    director = SocialMediaDirector(pipeline.profile)
    res = director.build_complete_social_pack(
        project_dir=project,
        manifest=manifest,
        include_overlays=overlays,
        reel_duration=reel_duration,
        reel_start_sec=reel_start,
    )

    console.print(
        Panel.fit(
            f"[bold green]Social Media & Reels Pack Generated Successfully![/bold green]\n\n"
            f"• YouTube Community Post (1:1): [cyan]{res['yt_post_image']}[/cyan]\n"
            f"• Instagram 4:5 Carousel Slides: [cyan]{len(res['ig_carousel_images'])} slides[/cyan]\n"
            f"• 9:16 Instagram Reel / YT Short: [magenta]{res.get('reel_video') or 'Skipped (render chapter video first)'}[/magenta]\n"
            f"• Captions, Poll & Hashtags Kit: [yellow]{res['kit_txt']}[/yellow]",
            title="YouTube & Instagram Social Pack",
        )
    )


@app.command("instagram-export")
def instagram_export(
    series: Optional[str] = typer.Option(None, "--series", "-s", help="Series slug (e.g. return_of_the_mount_hua_sect)"),
    chapter_start: int = typer.Option(1, "--chapter-start", help="Start chapter number"),
    chapter_end: int = typer.Option(5, "--chapter-end", help="End chapter number"),
    speed: float = typer.Option(1.25, "--speed", help="Source render speed (1.0, 1.25, 1.5)"),
    max_minutes: float = typer.Option(18.0, "--max-minutes", help="Max duration per part in minutes (18.0 for IG upload cap, 2.75 for Reels Explore reach, 0 for no split)"),
    aspect: str = typer.Option("9x16", "--aspect", help="Target aspect ratio: '9x16' (1080x1920 vertical) or '16x9'"),
    marathon_file: Optional[Path] = typer.Option(None, "--marathon-file", "-m", help="Optional marathon MP4 path to split instead of chapter range"),
    yt_handle: str = typer.Option("", "--yt-handle", help="Optional YouTube channel URL or @handle for the guide"),
    ig_handle: str = typer.Option("", "--ig-handle", help="Optional Instagram @handle for the guide"),
    prefer_cpu: bool = typer.Option(False, "--cpu", help="Use CPU libx264 (4 threads) instead of GPU NVENC"),
) -> None:
    """Convert chapter renders or marathon movies into Instagram-compatible 9:16 MP4s + Publishing Guide."""
    from manhwa_studio.studio_pro.instagram_exporter import InstagramExporter

    exporter = InstagramExporter()
    if marathon_file is not None:
        res = exporter.export_marathon(
            marathon_path=marathon_file,
            series_slug=series,
            max_minutes=max_minutes,
            aspect=aspect,
            yt_handle=yt_handle,
            ig_handle=ig_handle,
            prefer_cpu=prefer_cpu,
        )
    else:
        if not series:
            console.print("[bold red]Please provide --series or --marathon-file[/bold red]")
            raise typer.Exit(1)
        res = exporter.export_chapters(
            series_slug=series,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            speed=speed,
            max_minutes=max_minutes,
            aspect=aspect,
            yt_handle=yt_handle,
            ig_handle=ig_handle,
            prefer_cpu=prefer_cpu,
        )

    console.print(
        Panel.fit(
            f"[bold green]Instagram Export Complete![/bold green]\n\n"
            f"• Output Folder: [cyan]{res['output_dir']}[/cyan]\n"
            f"• Exported Files: [magenta]{len(res['exported_files'])}[/magenta]\n"
            f"• Publishing Guide: [yellow]{res['guide_path']}[/yellow]",
            title="Instagram 9:16 Compatibility",
        )
    )


@app.command()
def dashboard(
    host: str = typer.Option("127.0.0.1", "--host", help="Host address to bind the web dashboard"),
    port: int = typer.Option(8765, "--port", "-p", help="Port number for the web dashboard"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not automatically open the web browser"),
) -> None:
    """Launch the Manhwa Story Studio Pro Web Dashboard & Safe Job Queue Manager."""
    from manhwa_studio.dashboard.server import run_dashboard_server

    url = f"http://{host}:{port}"
    console.print(
        Panel.fit(
            f"[bold green]Manhwa Story Studio Pro — Web Dashboard Active[/bold green]\n\n"
            f"• Dashboard URL: [bold cyan]{url}[/bold cyan]\n"
            f"• Features: Series & Chapter Matrix | 2-Lane Safe Job Queue | External Terminal Detector | Thumbnail Studio\n"
            f"• Press [yellow]Ctrl+C[/yellow] to stop the dashboard server.",
            title="Studio Control Center",
        )
    )
    run_dashboard_server(host=host, port=port, open_browser=not no_browser)


@app.command(name="yt-auth")
def yt_auth(
    client_secrets: Optional[Path] = typer.Option(
        None, "--client-secrets", "-c", help="Path to Google OAuth client_secrets.json"
    ),
) -> None:
    """Authenticate with YouTube Data API v3 (OAuth 2.0) and verify the connected channel."""
    from manhwa_studio.studio_pro.youtube_uploader import (
        authenticate_youtube,
        get_authenticated_channel_info,
    )

    try:
        yt = authenticate_youtube(client_secrets_path=client_secrets)
        info = get_authenticated_channel_info(yt)
        console.print(
            Panel.fit(
                f"[bold green]YouTube OAuth Connected![/bold green]\n\n"
                f"• Channel: [cyan]{info.get('title', 'Unknown')}[/cyan]\n"
                f"• Channel ID: [dim]{info.get('id', 'N/A')}[/dim]\n"
                f"• Subscribers: [magenta]{info.get('subscribers', 'N/A')}[/magenta]",
                title="YouTube Authentication",
            )
        )
    except Exception as exc:
        console.print(f"[bold red]YouTube Auth Error:[/bold red] {exc}")
        raise typer.Exit(1)


@app.command(name="yt-upload-batch")
def yt_upload_batch(
    series: str = typer.Option(..., "--series", "-s", help="Series slug (e.g. return_of_the_mount_hua_sect)"),
    chapters: str = typer.Option(
        "", "--chapters", "-c", help="Chapter list or range (e.g. '1,2,3' or '1-3'). Leave empty to auto-pick next un-uploaded."
    ),
    count: int = typer.Option(3, "--count", "-n", help="Number of next un-uploaded chapters to pick when --chapters is omitted"),
    speed: float = typer.Option(1.25, "--speed", help="Source render speed (1.0, 1.25, 1.5)"),
    slots: str = typer.Option(
        "10:00,16:00,21:00",
        "--slots",
        help="Comma-separated daily local publish times (24h HH:MM, e.g. '10:00,16:00,21:00')",
    ),
    interval_hours: Optional[float] = typer.Option(
        None, "--interval-hours", help="Alternative to --slots: space uploads every N hours (e.g. 6)"
    ),
    start_at: str = typer.Option(
        "", "--start-at", help="Optional start date/time in local time (YYYY-MM-DD or 'YYYY-MM-DD HH:MM')"
    ),
    title_index: int = typer.Option(0, "--title-index", help="Which generated title option to use (0-4)"),
    playlist_id: Optional[str] = typer.Option(None, "--playlist-id", help="Optional YouTube Playlist ID to add videos to"),
    category_id: str = typer.Option("24", "--category-id", help="YouTube category ID (24=Entertainment, 1=Film & Animation)"),
    language: str = typer.Option("hi", "--language", help="Default video & audio language code (e.g. hi, en)"),
    include_uploaded: bool = typer.Option(False, "--include-uploaded", help="Do not skip chapters already in upload history"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview schedule & metadata without uploading to YouTube"),
) -> None:
    """Batch upload 2-3+ chapter videos to YouTube with Title, Description, Timeline, Hashtags & staggered publish times."""
    from datetime import datetime
    from manhwa_studio.studio_pro.youtube_uploader import (
        parse_chapter_selection,
        run_batch_upload,
    )

    ch_list = parse_chapter_selection(chapters) if chapters.strip() else None
    slot_list = [s.strip() for s in slots.split(",") if s.strip()] if slots.strip() else None

    parsed_start = None
    if start_at.strip():
        raw = start_at.strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                parsed_start = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        if parsed_start is None:
            console.print(f"[bold red]Invalid --start-at format:[/bold red] '{raw}'. Use YYYY-MM-DD or 'YYYY-MM-DD HH:MM'.")
            raise typer.Exit(1)

    try:
        results = run_batch_upload(
            series_slug=series,
            chapters=ch_list,
            auto_next=count,
            speed=speed,
            slots=slot_list,
            interval_hours=interval_hours,
            start_at=parsed_start,
            title_index=title_index,
            category_id=category_id,
            language=language,
            playlist_id=playlist_id,
            skip_uploaded=not include_uploaded,
            dry_run=dry_run,
        )
    except Exception as exc:
        console.print(f"[bold red]Batch Upload Error:[/bold red] {exc}")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No pending rendered chapters found to upload.[/yellow]")
        return

    table = Table(
        title=f"YouTube Batch {'Schedule Preview (DRY RUN)' if dry_run else 'Upload Results'} — {series}",
        border_style="cyan",
    )
    table.add_column("Ch", style="bold cyan", justify="right")
    table.add_column("Publish Time (Local)", style="green")
    table.add_column("Title", max_width=46)
    table.add_column("Status", style="bold")
    table.add_column("Video / URL")

    for r in results:
        status_style = {
            "dry_run": "[yellow]DRY RUN[/yellow]",
            "scheduled": "[green]SCHEDULED[/green]",
            "uploaded": "[green]UPLOADED[/green]",
            "failed": "[red]FAILED[/red]",
        }.get(r.status, r.status)
        target = r.url or r.error or Path(r.video_path).name
        table.add_row(f"Ch.{r.chapter}", r.publish_at_local, r.title, status_style, target)

    console.print(table)


@app.command(name="yt-upload-shorts")
def yt_upload_shorts(
    series: str = typer.Option(..., "--series", "-s", help="Series slug (e.g. the_ultimate_of_all_ages)"),
    chapters: str = typer.Option(
        "", "--chapters", "-c", help="Chapter list or range (e.g. '1,2,3' or '1-3'). Leave empty to auto-pick next un-uploaded."
    ),
    count: int = typer.Option(3, "--count", "-n", help="Number of next un-uploaded Shorts to pick when --chapters is omitted"),
    duration: float = typer.Option(90.0, "--duration", "-d", help="Duration in seconds (15–175s) when auto-generating missing 9:16 Shorts"),
    slots: str = typer.Option(
        "12:00,18:00,22:00",
        "--slots",
        help="Comma-separated daily local publish times (24h HH:MM, e.g. '12:00,18:00,22:00')",
    ),
    interval_hours: Optional[float] = typer.Option(
        None, "--interval-hours", help="Alternative to --slots: space Shorts every N hours (e.g. 4)"
    ),
    start_at: str = typer.Option(
        "", "--start-at", help="Optional start date/time in local time (YYYY-MM-DD or 'YYYY-MM-DD HH:MM')"
    ),
    title_index: int = typer.Option(0, "--title-index", help="Which generated title option to use (0-4)"),
    playlist_id: Optional[str] = typer.Option(None, "--playlist-id", help="Optional YouTube Playlist ID to add Shorts to"),
    category_id: str = typer.Option("24", "--category-id", help="YouTube category ID (24=Entertainment)"),
    language: str = typer.Option("hi", "--language", help="Default video & audio language code (e.g. hi, en)"),
    include_uploaded: bool = typer.Option(False, "--include-uploaded", help="Do not skip chapters already uploaded as Shorts"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview Shorts schedule & metadata without uploading"),
) -> None:
    """Batch upload 2-3+ vertical 9:16 YouTube Shorts with #Shorts Title, Description, Hashtags & staggered publish times."""
    from datetime import datetime
    from manhwa_studio.studio_pro.youtube_uploader import (
        parse_chapter_selection,
        run_shorts_batch_upload,
    )

    ch_list = parse_chapter_selection(chapters) if chapters.strip() else None
    slot_list = [s.strip() for s in slots.split(",") if s.strip()] if slots.strip() else None

    parsed_start = None
    if start_at.strip():
        raw = start_at.strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                parsed_start = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        if parsed_start is None:
            console.print(f"[bold red]Invalid --start-at format:[/bold red] '{raw}'. Use YYYY-MM-DD or 'YYYY-MM-DD HH:MM'.")
            raise typer.Exit(1)

    try:
        results = run_shorts_batch_upload(
            series_slug=series,
            chapters=ch_list,
            auto_next=count,
            short_duration=duration,
            slots=slot_list,
            interval_hours=interval_hours,
            start_at=parsed_start,
            title_index=title_index,
            category_id=category_id,
            language=language,
            playlist_id=playlist_id,
            skip_uploaded=not include_uploaded,
            dry_run=dry_run,
        )
    except Exception as exc:
        console.print(f"[bold red]Shorts Batch Upload Error:[/bold red] {exc}")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No pending 9:16 YouTube Shorts found to upload.[/yellow]")
        return

    table = Table(
        title=f"YouTube Shorts {'Schedule Preview (DRY RUN)' if dry_run else 'Upload Results'} — {series}",
        border_style="magenta",
    )
    table.add_column("Ch", style="bold magenta", justify="right")
    table.add_column("Publish Time (Local)", style="green")
    table.add_column("Short Title", max_width=46)
    table.add_column("Status", style="bold")
    table.add_column("Video / URL")

    for r in results:
        status_style = {
            "dry_run": "[yellow]DRY RUN[/yellow]",
            "scheduled": "[green]SCHEDULED[/green]",
            "uploaded": "[green]UPLOADED[/green]",
            "failed": "[red]FAILED[/red]",
        }.get(r.status, r.status)
        target = r.url or r.error or Path(r.video_path).name
        table.add_row(f"Ch.{r.chapter}", r.publish_at_local, r.title, status_style, target)

    console.print(table)


@app.command(name="yt-upload-marathon")
def yt_upload_marathon(
    marathon_file: Path = typer.Option(..., "--file", "-f", help="Path to compiled Marathon MP4 (e.g. exports/marathons/...mp4)"),
    series: Optional[str] = typer.Option(None, "--series", "-s", help="Optional series slug override"),
    publish_at: str = typer.Option("", "--publish-at", help="Optional publish date/time in local time ('YYYY-MM-DD HH:MM')"),
    slots: str = typer.Option("18:00", "--slots", help="Daily local publish slot if --publish-at is omitted (e.g. '18:00')"),
    title_index: int = typer.Option(0, "--title-index", help="Which generated title option to use (0-4)"),
    playlist_id: Optional[str] = typer.Option(None, "--playlist-id", help="Optional YouTube Playlist ID"),
    category_id: str = typer.Option("24", "--category-id", help="YouTube category ID (24=Entertainment)"),
    language: str = typer.Option("hi", "--language", help="Default video & audio language code"),
    include_uploaded: bool = typer.Option(False, "--include-uploaded", help="Upload even if this marathon is already in history"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview Marathon metadata & schedule without uploading"),
) -> None:
    """Upload & schedule a compiled Marathon Movie MP4 with viral Title, Description, Timeline & Hashtags."""
    from datetime import datetime
    from manhwa_studio.studio_pro.youtube_uploader import run_marathon_upload

    parsed_dt = None
    if publish_at.strip():
        raw = publish_at.strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                parsed_dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        if parsed_dt is None:
            console.print(f"[bold red]Invalid --publish-at format:[/bold red] '{raw}'. Use 'YYYY-MM-DD HH:MM'.")
            raise typer.Exit(1)

    slot_list = [s.strip() for s in slots.split(",") if s.strip()] if slots.strip() else None
    try:
        results = run_marathon_upload(
            marathon_path=marathon_file,
            series_slug=series,
            publish_at=parsed_dt,
            slots=slot_list,
            title_index=title_index,
            category_id=category_id,
            language=language,
            playlist_id=playlist_id,
            skip_uploaded=not include_uploaded,
            dry_run=dry_run,
        )
    except Exception as exc:
        console.print(f"[bold red]Marathon Upload Error:[/bold red] {exc}")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]Marathon already uploaded (use --include-uploaded to force).[/yellow]")
        return

    r = results[0]
    console.print(
        Panel.fit(
            f"[bold green]Marathon {'Preview (DRY RUN)' if dry_run else 'Scheduled'}![/bold green]\n\n"
            f"• Title: [cyan]{r.title}[/cyan]\n"
            f"• Publish Time: [green]{r.publish_at_local}[/green]\n"
            f"• Video: [dim]{r.video_path}[/dim]\n"
            f"• Thumbnail: [yellow]{r.thumbnail_path or 'None'}[/yellow]\n"
            f"• Result: [magenta]{r.url or r.error or r.status}[/magenta]",
            title="YouTube Marathon Upload",
        )
    )


@app.command(name="yt-history")
def yt_history(
    series: Optional[str] = typer.Option(None, "--series", "-s", help="Optional filter by series slug"),
) -> None:
    """Show YouTube batch upload & scheduling history."""
    from manhwa_studio.studio_pro.youtube_uploader import load_upload_history

    rows = load_upload_history()
    if series:
        rows = [r for r in rows if r.get("series_slug") == series]

    if not rows:
        console.print("[yellow]No YouTube uploads recorded yet.[/yellow]")
        return

    table = Table(title="YouTube Upload History", border_style="green")
    table.add_column("Series", style="cyan")
    table.add_column("Ch", justify="right")
    table.add_column("Type", style="magenta")
    table.add_column("Publish Time (Local)", style="green")
    table.add_column("Title", max_width=40)
    table.add_column("URL")

    for r in rows[-30:]:
        v_type = "Short" if r.get("video_type") == "short" else "Full"
        table.add_row(
            str(r.get("series_slug", "")),
            f"Ch.{r.get('chapter', '')}",
            v_type,
            str(r.get("publish_at_local", "")),
            str(r.get("title", "")),
            str(r.get("url", "")),
        )
    console.print(table)


@app.command(name="ig-auth")
def ig_auth(
    ig_user_id: Optional[str] = typer.Option(None, "--user-id", help="Instagram Business/Creator Account ID"),
    access_token: Optional[str] = typer.Option(None, "--token", help="Meta Graph API Access Token"),
) -> None:
    """Save and verify Instagram Graph API credentials (IG_USER_ID + IG_ACCESS_TOKEN)."""
    from manhwa_studio.studio_pro.instagram_publisher import (
        get_instagram_account_info,
        load_instagram_credentials,
        save_instagram_credentials,
    )

    if ig_user_id and access_token:
        save_instagram_credentials(ig_user_id, access_token)

    creds = load_instagram_credentials()
    if not creds:
        console.print(
            "[bold red]Missing Instagram credentials.[/bold red] "
            "Pass --user-id and --token, or set IG_USER_ID and IG_ACCESS_TOKEN in .env."
        )
        raise typer.Exit(1)

    try:
        info = get_instagram_account_info(creds)
        console.print(
            Panel.fit(
                f"[bold green]Instagram Graph API Connected![/bold green]\n\n"
                f"• Username: [cyan]@{info.get('username', 'unknown')}[/cyan]\n"
                f"• IG User ID: [dim]{info.get('id', creds.ig_user_id)}[/dim]\n"
                f"• Followers: [magenta]{info.get('followers_count', 'N/A')}[/magenta]",
                title="Instagram Authentication",
            )
        )
    except Exception as exc:
        console.print(f"[bold red]Instagram Auth Error:[/bold red] {exc}")
        raise typer.Exit(1)


@app.command(name="ig-upload-batch")
def ig_upload_batch(
    folder: str = typer.Option(..., "--folder", "-f", help="Folder name inside exports/instagram/ (e.g. return_of_the_mount_hua_sect)"),
    count: int = typer.Option(2, "--count", "-n", help="Number of un-published 9:16 Reels to post"),
    delay_minutes: float = typer.Option(0.0, "--delay-minutes", help="Minutes to wait between posting each Reel"),
    video_base_url: Optional[str] = typer.Option(None, "--video-base-url", help="Optional public HTTPS base URL (if not using cloudflared tunnel)"),
    include_published: bool = typer.Option(False, "--include-published", help="Do not skip parts already in Instagram upload history"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview Reels & captions without publishing"),
) -> None:
    """Auto-publish 9:16 Reels from exports/instagram/<folder>/ via Official Instagram Graph API."""
    from manhwa_studio.studio_pro.instagram_publisher import run_instagram_batch_publish

    try:
        results = run_instagram_batch_publish(
            folder=folder,
            count=count,
            delay_minutes=delay_minutes,
            video_base_url=video_base_url,
            skip_published=not include_published,
            dry_run=dry_run,
        )
    except Exception as exc:
        console.print(f"[bold red]Instagram Publish Error:[/bold red] {exc}")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No pending Instagram Reels found to publish.[/yellow]")
        return

    table = Table(
        title=f"Instagram Reels {'Preview (DRY RUN)' if dry_run else 'Publish Results'} — {folder}",
        border_style="magenta",
    )
    table.add_column("File", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Caption Preview", max_width=46)
    table.add_column("Permalink / Info")

    for r in results:
        st = {
            "dry_run": "[yellow]DRY RUN[/yellow]",
            "published": "[green]PUBLISHED[/green]",
            "failed": "[red]FAILED[/red]",
        }.get(r.status, r.status)
        table.add_row(r.filename, st, r.caption_preview, r.permalink or r.error or r.media_id or "")
    console.print(table)


if __name__ == "__main__":
    app()



