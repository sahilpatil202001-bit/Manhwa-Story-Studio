"""
Unit tests for the Chapter Cleaner & Unpacker.
"""

import zipfile
from pathlib import Path
from manhwa_studio.ingestion.chapter_cleaner import (
    is_valid_chapter_image,
    extract_page_number,
    process_chapter_zip,
    clean_and_unpack_inbox,
)


def test_is_valid_chapter_image():
    # Valid chapter page numbers
    assert is_valid_chapter_image("001.webp") == (True, "001.webp")
    assert is_valid_chapter_image("14.jpg") == (True, "14.jpg")
    assert is_valid_chapter_image("005.webp. ") == (True, "005.webp")
    assert is_valid_chapter_image("subfolder/008.png") == (True, "008.png")

    # Junk files, ads, duplicates, svgs
    assert is_valid_chapter_image("001_1.webp")[0] is False
    assert is_valid_chapter_image("001_copy.webp")[0] is False
    assert is_valid_chapter_image("discord_banner.jpg")[0] is False
    assert is_valid_chapter_image("logo.svg")[0] is False
    assert is_valid_chapter_image("credits.png")[0] is False


def test_process_chapter_zip_extract_and_cleanup(tmp_path: Path):
    ch_dir = tmp_path / "The Greatest Estate Developer" / "ch11"
    ch_dir.mkdir(parents=True)
    zip_path = ch_dir / "chapter11.zip"

    # Create dummy zip with good pages and junk
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("001.webp", b"page 1 binary data")
        zf.writestr("002.webp", b"page 2 binary data")
        zf.writestr("001_1.webp", b"duplicate page")
        zf.writestr("ad_banner.png", b"advertisement")
        zf.writestr("icon.svg", b"<svg></svg>")

    success = process_chapter_zip(zip_path, delete_zip=True, dry_run=False)
    assert success is True

    # Check that only valid files were extracted
    assert (ch_dir / "001.webp").exists()
    assert (ch_dir / "002.webp").exists()
    assert not (ch_dir / "001_1.webp").exists()
    assert not (ch_dir / "ad_banner.png").exists()

    # Check that zip was deleted
    assert not zip_path.exists()


def test_clean_and_unpack_inbox(tmp_path: Path):
    inbox_dir = tmp_path / "inbox"
    ch1 = inbox_dir / "Series A" / "ch1"
    ch1.mkdir(parents=True)
    zip1 = ch1 / "ch1.zip"

    with zipfile.ZipFile(zip1, "w") as zf:
        zf.writestr("001.webp", b"img 1")
        zf.writestr("promo.jpg", b"promo")

    cleaned = clean_and_unpack_inbox(inbox_dir)
    assert cleaned == 1
    assert (ch1 / "001.webp").exists()
    assert not zip1.exists()
