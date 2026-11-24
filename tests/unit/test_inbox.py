"""
Unit tests for inbox scanner and LLM title suggestions.
"""

from pathlib import Path
from PIL import Image
import pytest

from manhwa_studio.ingestion.inbox_scanner import parse_chapter_number, scan_inbox
from manhwa_studio.story.llm_title_generator import (
    generate_fallback_suggestion,
    suggest_chapter_title_and_hook,
)


def test_parse_chapter_number():
    assert parse_chapter_number("ch1") == 1
    assert parse_chapter_number("chapter_02") == 2
    assert parse_chapter_number("myst_might_mayhem_ch05") == 5
    assert parse_chapter_number("09") == 9
    assert parse_chapter_number("chapter 12") == 12


def test_scan_inbox(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    ch1 = inbox / "chapter_01"
    ch1.mkdir()
    # Create webp files
    im = Image.new("RGB", (100, 100), (200, 50, 50))
    im.save(ch1 / "01.webp")
    im.save(ch1 / "02.webp")

    ch2 = inbox / "ch_2"
    ch2.mkdir()
    im.save(ch2 / "01.webp")

    batches = scan_inbox(inbox, default_series="Myst, Might, Mayhem")
    assert len(batches) == 2
    assert batches[0].chapter_number == 1
    assert len(batches[0].image_paths) == 2
    assert batches[1].chapter_number == 2


def test_scan_inbox_nested_series(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    estate_ch1 = inbox / "The Greatest Estate Developer" / "ch1"
    estate_ch1.mkdir(parents=True)
    im = Image.new("RGB", (100, 100), (50, 200, 50))
    im.save(estate_ch1 / "01.webp")

    batches = scan_inbox(inbox, default_series="Myst, Might, Mayhem")
    assert len(batches) == 1
    assert batches[0].inferred_series == "The Greatest Estate Developer"
    assert batches[0].chapter_number == 1
    assert len(batches[0].image_paths) == 1


def test_llm_title_generator_fallback():
    suggestion = generate_fallback_suggestion("Myst, Might, Mayhem", chapter=1)
    assert suggestion.title is not None
    assert len(suggestion.alternative_titles) > 0
    assert len(suggestion.hindi_hook) > 0
    assert suggestion.provider == "curated_fallback"
