from pathlib import Path

from manhwa_studio.dashboard.scanner import WorkspaceScanner
from manhwa_studio.dashboard.server import build_cli_job_spec
from manhwa_studio.studio_pro.instagram_exporter import InstagramExporter, build_aspect_filter


def test_build_aspect_filter_9x16_from_1080p():
    vf = build_aspect_filter(1920, 1080, "9x16")
    assert vf == "crop=608:1080:656:0,scale=1080:1920:flags=lanczos,setsar=1,format=yuv420p"


def test_build_aspect_filter_16x9_returns_none():
    assert build_aspect_filter(1920, 1080, "16x9") is None


def test_write_publishing_guide_and_scanner(tmp_path: Path):
    exporter = InstagramExporter(root_dir=tmp_path)
    out_dir = tmp_path / "exports" / "instagram" / "nano_machine"
    out_dir.mkdir(parents=True, exist_ok=True)
    dummy_mp4 = out_dir / "nano_machine_ch001_1.25x_9x16.mp4"
    dummy_mp4.write_bytes(b"\x00" * 1024)

    guide = exporter.write_publishing_guide(
        out_dir=out_dir,
        series_slug="nano_machine",
        exported_items=[{
            "filename": dummy_mp4.name,
            "path": "exports/instagram/nano_machine/nano_machine_ch001_1.25x_9x16.mp4",
            "duration_sec": 600.0,
            "chapter": 1,
            "part": 1,
            "total_parts": 1,
        }],
        yt_handle="https://youtube.com/@MyManhwaYT",
        ig_handle="@mymanhwaig",
    )
    assert guide.exists()
    content = guide.read_text(encoding="utf-8")
    assert "@mymanhwaig" in content
    assert "https://youtube.com/@MyManhwaYT" in content
    assert "SUBSCRIBE" in content and "FOLLOW" in content

    scanner = WorkspaceScanner(root_dir=tmp_path)
    groups = scanner.scan_instagram_exports()
    assert len(groups) == 1
    assert groups[0]["folder"] == "nano_machine"
    assert len(groups[0]["videos"]) == 1
    assert groups[0]["has_guide"] is True


def test_build_job_spec_instagram_export_chapters_and_marathon():
    spec_ch = build_cli_job_spec({
        "action": "instagram-export",
        "series_slug": "nano_machine",
        "series_name": "Nano Machine",
        "chapter_start": 1,
        "chapter_end": 5,
        "speed": 1.25,
        "max_minutes": 18,
        "aspect": "9x16",
        "yt_handle": "@yt",
        "ig_handle": "@ig",
    })
    assert spec_ch["job_type"] == "instagram-export"
    assert spec_ch["lane"] == "render"
    assert spec_ch["chapters"] == [1, 2, 3, 4, 5]
    assert "--chapter-start" in spec_ch["command_args"]

    spec_m = build_cli_job_spec({
        "action": "instagram-export",
        "marathon_file": "exports/marathons/nano_machine_ch1_to_ch20_movie_1.25x.mp4",
        "max_minutes": 2.75,
        "aspect": "9x16",
    })
    assert spec_m["job_type"] == "instagram-export"
    assert spec_m["lane"] == "render"
    assert "--marathon-file" in spec_m["command_args"]
    assert "2.75" in spec_m["command_args"]


def test_dynamic_context_from_manifest_and_timestamps(tmp_path: Path, monkeypatch):
    import json

    # Set up series profile (murim genre)
    prof_dir = tmp_path / "configs" / "series_profiles"
    prof_dir.mkdir(parents=True)
    (prof_dir / "nano_machine.yaml").write_text("series_name: Nano Machine\ngenre: murim\n", encoding="utf-8")

    # Set up chapter 1 scene_manifest.json
    script_dir = tmp_path / "data" / "projects" / "nano_machine" / "chapter_001" / "scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "scene_manifest.json").write_text(
        json.dumps({
            "scenes": [
                {"speaker": "Narrator", "narration_text": "Cheon Yeo-Woon ne apna haath uthaya!"},
                {"speaker": "Nano", "narration_text": "System activation complete!"},
            ]
        }),
        encoding="utf-8",
    )

    # Set up marathon timestamps
    ts_file = tmp_path / "exports" / "marathons" / "nano_machine_movie.timestamps.txt"
    ts_file.parent.mkdir(parents=True)
    ts_file.write_text("00:00 - Chapter 1: Awakening\n10:00 - Chapter 2: First Fight\n", encoding="utf-8")

    # Ensure no real network call in unit test
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    exporter = InstagramExporter(root_dir=tmp_path)
    out_dir = tmp_path / "exports" / "instagram" / "nano_machine"
    out_dir.mkdir(parents=True)
    guide = exporter.write_publishing_guide(
        out_dir=out_dir,
        series_slug="nano_machine_movie",
        exported_items=[{
            "filename": "nano_machine_part01_9x16.mp4",
            "path": "exports/instagram/nano_machine/nano_machine_part01_9x16.mp4",
            "duration_sec": 300.0,
            "start_sec": 0.0,
            "end_sec": 300.0,
            "part": 1,
            "total_parts": 2,
        }],
        yt_handle="@NanoYT",
        ig_handle="@NanoIG",
        marathon_timestamps_path=ts_file,
    )
    txt = guide.read_text(encoding="utf-8")
    assert "Nano Machine" in txt
    assert "#MurimManhwa" in txt
    assert "Cheon Yeo-Woon ne apna haath uthaya!" in txt
    assert "@NanoIG" in txt
    assert "@NanoYT" in txt
