from __future__ import annotations

from pathlib import Path

from manhwa_studio.dashboard.server import build_cli_job_spec
from manhwa_studio.studio_pro.instagram_publisher import (
    append_instagram_history,
    discover_instagram_upload_items,
    parse_instagram_guide_captions,
    run_instagram_batch_publish,
)


SAMPLE_GUIDE = """# Instagram Publishing Guide

### Part 1: `part_001.mp4`
```text
🔥 Mount Hua Sect Part 1 — Chung Myung Returns!
Full video on YouTube!

#ReturnOfTheMountHuaSect #ManhwaReels #ManhwaInHindi
```

### Part 2: `part_002.mp4`
```text
⚔️ Mount Hua Sect Part 2 — The Battle Begins!

#ReturnOfTheMountHuaSect #ManhwaReels
```
"""


def test_parse_instagram_guide_captions():
    caps = parse_instagram_guide_captions(SAMPLE_GUIDE)
    assert "part_001.mp4" in caps
    assert "Chung Myung Returns" in caps["part_001.mp4"]
    assert "part_002.mp4" in caps
    assert "#ManhwaReels" in caps["part_002.mp4"]


def test_discover_and_dry_run_skips_published(tmp_path: Path):
    ig_dir = tmp_path / "instagram"
    folder_dir = ig_dir / "test_series"
    folder_dir.mkdir(parents=True)

    (folder_dir / "part_001.mp4").write_bytes(b"mp4-1")
    (folder_dir / "part_002.mp4").write_bytes(b"mp4-2")
    (folder_dir / "part_003.mp4").write_bytes(b"mp4-3")
    (folder_dir / "INSTAGRAM_PUBLISHING_GUIDE.md").write_text(SAMPLE_GUIDE, encoding="utf-8")

    items = discover_instagram_upload_items("test_series", exports_ig_dir=ig_dir)
    assert [i.filename for i in items] == ["part_001.mp4", "part_002.mp4", "part_003.mp4"]
    assert "#ManhwaInHindi" in items[0].hashtags

    hist = tmp_path / "instagram_upload_history.json"
    append_instagram_history(
        {"folder": "test_series", "filename": "part_001.mp4", "status": "published"},
        history_path=hist,
    )

    res = run_instagram_batch_publish(
        folder="test_series",
        count=2,
        dry_run=True,
        exports_ig_dir=ig_dir,
        history_path=hist,
    )
    assert [r.filename for r in res] == ["part_002.mp4", "part_003.mp4"]
    assert all(r.status == "dry_run" for r in res)


def test_dashboard_build_cli_job_spec_ig_upload_batch():
    spec = build_cli_job_spec(
        {
            "action": "ig-upload-batch",
            "folder": "return_of_the_mount_hua_sect",
            "count": 2,
            "delay_minutes": 60,
        }
    )
    assert spec["job_type"] == "ig-upload-batch"
    assert spec["command_args"][0] == "ig-upload-batch"
    assert "--delay-minutes" in spec["command_args"]

