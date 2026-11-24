from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from manhwa_studio.dashboard.server import build_cli_job_spec
from manhwa_studio.studio_pro.youtube_uploader import (
    append_upload_history,
    compute_publish_schedule,
    fit_youtube_tags,
    format_utc_iso,
    parse_chapter_selection,
    parse_youtube_kit_text,
    run_batch_upload,
    truncate_youtube_title,
)


SAMPLE_KIT = """================================================================================
                    YOUTUBE PUBLISHING METADATA KIT
Series: Return Of The Mount Hua Sect | Chapter: 1
================================================================================

🎯 RECOMMENDED HIGH-CTR TITLES (Curiosity Hook First for Browse Feed CTR):
1) 100 Saal Baad Zinda Hua Sabse Khatarnak Sword Saint?! 🔥 | Return Of The Mount Hua Sect Ch 1 in Hindi
2) Sabne Use Kamzor Samjha Par Wo Asli Demon Nikla! ⚔️ | Return Of The Mount Hua Sect Ch 1 Recap

🖼️ THUMBNAIL 2-WORD TEXT BADGE IDEAS (Use with tight facial expression zoom):
"ZINDA HUA?!" | "LEVEL 999?!"

--------------------------------------------------------------------------------
📝 DESCRIPTION (Copy & paste into YouTube Video Description):
--------------------------------------------------------------------------------
🔥 Return Of The Mount Hua Sect - Chapter 1 Full Story Explained in Hindi | Manhwa Recap

Chung Myung apne sect ko bachane ke liye aakhri ladai ladta hai!

📌 Timestamps:
00:00 - Teaser Hook 🔥
00:45 - The Final Battle on Mount Hua
02:10 - Reincarnation 100 Years Later

#ReturnOfTheMountHuaSect #ManhwaInHindi #ManhwaRecap

--------------------------------------------------------------------------------
🏷️ TAGS (Comma-separated, copy-paste into YouTube Studio Tags box):
--------------------------------------------------------------------------------
return of the mount hua sect hindi, return of the mount hua sect chapter 1, manhwa recap hindi, murim manhwa

================================================================================
"""


def test_parse_youtube_kit_text():
    parsed = parse_youtube_kit_text(SAMPLE_KIT)
    assert len(parsed.titles) == 2
    assert parsed.primary_title.startswith("100 Saal Baad Zinda Hua")
    assert "00:00 - Teaser Hook" in parsed.description
    assert len(parsed.timestamps) == 3
    assert "#ReturnOfTheMountHuaSect" in parsed.hashtags
    assert "#ManhwaInHindi" in parsed.hashtags
    assert "manhwa recap hindi" in parsed.tags


def test_title_and_tags_limits():
    long_title = "This is a very long YouTube title hook that definitely exceeds one hundred characters and needs clean truncation without breaking words"
    clipped = truncate_youtube_title(long_title, max_len=100)
    assert len(clipped) <= 100
    assert clipped.endswith("…")

    many_tags = [f"very long manhwa keyword tag number {i}" for i in range(30)]
    fitted = fit_youtube_tags(many_tags, max_total_chars=480)
    assert len(fitted) > 0
    total_len = sum(len(t) + (2 if " " in t else 0) for t in fitted) + max(0, len(fitted) - 1)
    assert total_len <= 480


def test_parse_chapter_selection():
    assert parse_chapter_selection("1-3") == [1, 2, 3]
    assert parse_chapter_selection("3, 1, 5-6") == [1, 3, 5, 6]


def test_compute_publish_schedule_slots_rollover():
    tz = timezone(timedelta(hours=5, minutes=30))
    now = datetime(2026, 11, 17, 19, 30, 0, tzinfo=tz)

    sched = compute_publish_schedule(
        count=3,
        slots=["10:00", "16:00", "21:00"],
        now=now,
        min_lead_minutes=15,
    )
    assert len(sched) == 3
    # 10:00 and 16:00 already passed on Nov 17, so first slot is Nov 17 21:00, then Nov 18 10:00 & 16:00
    assert (sched[0].day, sched[0].hour, sched[0].minute) == (17, 21, 0)
    assert (sched[1].day, sched[1].hour, sched[1].minute) == (18, 10, 0)
    assert (sched[2].day, sched[2].hour, sched[2].minute) == (18, 16, 0)
    assert format_utc_iso(sched[0]) == "2026-11-17T15:30:00Z"


def test_compute_publish_schedule_interval_hours():
    tz = timezone(timedelta(hours=5, minutes=30))
    start = datetime(2026, 11, 18, 9, 0, 0, tzinfo=tz)
    now = datetime(2026, 11, 17, 19, 30, 0, tzinfo=tz)

    sched = compute_publish_schedule(
        count=3,
        interval_hours=6.0,
        start_at=start,
        now=now,
    )
    assert [s.hour for s in sched] == [9, 15, 21]
    assert all(s.day == 18 for s in sched)


def test_run_batch_upload_dry_run_skips_uploaded_and_picks_next_three(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    series_slug = "test_manhwa"
    for ch in (1, 2, 3, 4):
        ch_dir = projects_dir / series_slug / f"chapter_{ch:03d}"
        (ch_dir / "renders").mkdir(parents=True)
        (ch_dir / "reports").mkdir(parents=True)
        (ch_dir / "renders" / "final_video_1.25x.mp4").write_bytes(b"fake-mp4")
        (ch_dir / "reports" / "pro_thumbnail.jpg").write_bytes(b"fake-jpg")
        (ch_dir / "reports" / "youtube_upload_kit.txt").write_text(SAMPLE_KIT, encoding="utf-8")

    history_path = tmp_path / "youtube_upload_history.json"
    append_upload_history(
        {
            "series_slug": series_slug,
            "chapter": 1,
            "video_id": "abc123",
            "status": "scheduled",
        },
        history_path=history_path,
    )

    results = run_batch_upload(
        series_slug=series_slug,
        auto_next=3,
        speed=1.25,
        slots=["10:00", "16:00", "21:00"],
        dry_run=True,
        history_path=history_path,
        projects_base_dir=projects_dir,
    )

    assert [r.chapter for r in results] == [2, 3, 4]
    assert all(r.status == "dry_run" for r in results)
    assert all(r.thumbnail_path is not None for r in results)
    # Different publish times for each video
    assert len({r.publish_at_utc for r in results}) == 3


def test_find_chapter_video_skips_cold_open_and_shorts(tmp_path: Path):
    from manhwa_studio.studio_pro.youtube_uploader import _find_chapter_video

    ch_dir = tmp_path / "chapter_001"
    (ch_dir / "exports").mkdir(parents=True)
    (ch_dir / "renders").mkdir(parents=True)

    (ch_dir / "exports" / "series_ch001_cold_open.mp4").write_bytes(b"cold-open")
    (ch_dir / "exports" / "series_ch001_short_9x16.mp4").write_bytes(b"short")
    (ch_dir / "exports" / "series_ch001_pro.mp4").write_bytes(b"pro")
    (ch_dir / "renders" / "final_video_1.25x.mp4").write_bytes(b"final-1.25x")

    found_125 = _find_chapter_video(ch_dir, speed=1.25)
    assert found_125 is not None
    assert found_125.name == "final_video_1.25x.mp4"

    # Without final_video_1.25x.mp4, should pick *_pro.mp4, NOT *_cold_open.mp4
    found_10 = _find_chapter_video(ch_dir, speed=1.0)
    assert found_10 is not None
    assert found_10.name == "series_ch001_pro.mp4"


def test_dashboard_build_cli_job_spec_yt_upload_batch():
    spec = build_cli_job_spec(
        {
            "action": "yt-upload-batch",
            "series_slug": "nano_machine",
            "series_name": "Nano Machine",
            "chapters": "1-3",
            "count": 3,
            "speed": 1.25,
            "slots": "10:00,16:00,21:00",
        }
    )
    assert spec["job_type"] == "yt-upload-batch"
    assert spec["command_args"][0] == "yt-upload-batch"
    assert "--chapters" in spec["command_args"]
    assert "1-3" in spec["command_args"]
    assert "--slots" in spec["command_args"]


def test_run_shorts_batch_upload_dry_run(tmp_path: Path):
    from manhwa_studio.studio_pro.youtube_uploader import run_shorts_batch_upload

    projects_dir = tmp_path / "projects"
    series_slug = "test_manhwa"
    for ch in (1, 2, 3):
        ch_dir = projects_dir / series_slug / f"chapter_{ch:03d}"
        (ch_dir / "exports").mkdir(parents=True)
        (ch_dir / "reports").mkdir(parents=True)
        (ch_dir / "exports" / f"{series_slug}_ch{ch:03d}_short_9x16.mp4").write_bytes(b"fake-short")
        (ch_dir / "reports" / "youtube_upload_kit.txt").write_text(SAMPLE_KIT, encoding="utf-8")

    history_path = tmp_path / "youtube_upload_history.json"
    # Even if Ch.1 was uploaded as a FULL video, it should NOT skip Ch.1 for Shorts
    append_upload_history(
        {
            "series_slug": series_slug,
            "chapter": 1,
            "video_type": "full",
            "video_id": "full123",
            "status": "scheduled",
        },
        history_path=history_path,
    )

    results = run_shorts_batch_upload(
        series_slug=series_slug,
        auto_next=3,
        slots=["12:00", "18:00", "22:00"],
        dry_run=True,
        history_path=history_path,
        projects_base_dir=projects_dir,
    )
    assert [r.chapter for r in results] == [1, 2, 3]
    assert all("#Shorts" in r.title for r in results)
    assert all(r.thumbnail_path is None for r in results)
    assert len({r.publish_at_utc for r in results}) == 3

    shorts_spec = build_cli_job_spec(
        {
            "action": "yt-upload-shorts",
            "series_slug": "test_manhwa",
            "series_name": "Test Manhwa",
            "chapters": "1-3",
            "count": 3,
            "slots": "12:00,18:00,22:00",
        }
    )
    assert shorts_spec["job_type"] == "yt-upload-shorts"
    assert shorts_spec["command_args"][0] == "yt-upload-shorts"


def test_run_shorts_batch_upload_auto_plans_missing_shorts_from_full_video(tmp_path: Path):
    from manhwa_studio.studio_pro.youtube_uploader import run_shorts_batch_upload

    projects_dir = tmp_path / "projects"
    series_slug = "test_manhwa"
    for ch in (1, 2):
        ch_dir = projects_dir / series_slug / f"chapter_{ch:03d}"
        (ch_dir / "renders").mkdir(parents=True)
        (ch_dir / "reports").mkdir(parents=True)
        (ch_dir / "renders" / "final_video_1.25x.mp4").write_bytes(b"full-mp4")
        (ch_dir / "reports" / "youtube_upload_kit.txt").write_text(SAMPLE_KIT, encoding="utf-8")

    results = run_shorts_batch_upload(
        series_slug=series_slug,
        auto_next=2,
        slots=["12:00", "18:00"],
        dry_run=True,
        history_path=tmp_path / "youtube_upload_history.json",
        projects_base_dir=projects_dir,
    )
    assert [r.chapter for r in results] == [1, 2]
    assert all(r.video_path.endswith("_short_9x16.mp4") for r in results)


def test_run_marathon_upload_dry_run_and_duplicate_skip(tmp_path: Path):
    from manhwa_studio.studio_pro.youtube_uploader import (
        discover_marathon_upload_item,
        run_marathon_upload,
    )

    m_dir = tmp_path / "marathons"
    m_dir.mkdir()
    m_mp4 = m_dir / "nano_machine_ch1_to_ch5_movie_1.25x.mp4"
    m_mp4.write_bytes(b"fake-marathon")
    (m_dir / "nano_machine_ch1_to_ch5_movie_1.25x.timestamps.txt").write_text(
        "TIMESTAMPS:\n00:00 - Chapter 1: Awakening\n10:30 - Chapter 2: Battle\n",
        encoding="utf-8",
    )

    item = discover_marathon_upload_item(m_mp4)
    assert item.is_marathon is True
    assert "00:00 - Chapter 1: Awakening" in item.description
    assert "10:30 - Chapter 2: Battle" in item.description
    assert any(h.startswith("#") for h in item.hashtags)

    hist = tmp_path / "youtube_upload_history.json"
    res = run_marathon_upload(marathon_path=m_mp4, dry_run=True, history_path=hist)
    assert len(res) == 1
    assert res[0].status == "dry_run"

    # Once recorded in history, duplicate run skips it
    append_upload_history(
        {
            "series_slug": "nano_machine",
            "chapter": 1,
            "video_type": "marathon",
            "video_path": str(m_mp4),
            "status": "scheduled",
        },
        history_path=hist,
    )
    assert run_marathon_upload(marathon_path=m_mp4, dry_run=True, history_path=hist) == []

    spec = build_cli_job_spec({"action": "yt-upload-marathon", "marathon_file": str(m_mp4)})
    assert spec["job_type"] == "yt-upload-marathon"
    assert spec["command_args"][0] == "yt-upload-marathon"

