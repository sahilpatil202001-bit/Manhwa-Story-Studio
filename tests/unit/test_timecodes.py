"""
Unit tests for timecode conversions and string formatters.
"""

import pytest
from manhwa_studio.utils.timecodes import (
    format_duration,
    seconds_to_ass_timecode,
    seconds_to_srt_timecode,
    srt_timecode_to_seconds,
)


def test_seconds_to_srt_timecode():
    assert seconds_to_srt_timecode(0.0) == "00:00:00,000"
    assert seconds_to_srt_timecode(65.123) == "00:01:05,123"
    assert seconds_to_srt_timecode(3661.05) == "01:01:01,050"


def test_seconds_to_ass_timecode():
    assert seconds_to_ass_timecode(0.0) == "0:00:00.00"
    assert seconds_to_ass_timecode(65.123) == "0:01:05.12"
    assert seconds_to_ass_timecode(3661.5) == "1:01:01.50"


def test_srt_timecode_to_seconds():
    assert srt_timecode_to_seconds("00:00:00,000") == 0.0
    assert abs(srt_timecode_to_seconds("00:01:05,123") - 65.123) < 1e-4
    assert abs(srt_timecode_to_seconds("01:01:01,050") - 3661.05) < 1e-4


def test_format_duration():
    assert format_duration(45.2) == "45.2s"
    assert format_duration(180.0) == "3m 00.0s"
