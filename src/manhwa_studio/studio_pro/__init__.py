"""
Manhwa Studio Pro: Advanced Anime & Comic Dub Production Suite.
Features:
- Multi-Voice Character Dubbing (VoiceDirector)
- Dynamic Mood-Adaptive BGM & Sound Effects (AudioDirector)
- Kinetic Animated Anime Subtitles (KineticSubtitleGenerator)
- Camera FX: Screen Shake, Slow Zoom, Webtoon Pan (CameraDirector)
- Viral High-CTR YouTube Thumbnails (ThumbnailDesigner)
- Multi-Chapter Full-Movie Marathon Compilations (MarathonEngine)
- Series Profile Management for Diverse Manhwa (SeriesManager, SeriesProfile)
"""

from manhwa_studio.studio_pro.series_manager import SeriesManager, SeriesProfile, VoiceSetting, SubtitleStyle
from manhwa_studio.studio_pro.voice_director import VoiceDirector
from manhwa_studio.studio_pro.audio_director import AudioDirector
from manhwa_studio.studio_pro.kinetic_subtitles import KineticSubtitleGenerator
from manhwa_studio.studio_pro.camera_director import CameraDirector
from manhwa_studio.studio_pro.thumbnail_designer import ThumbnailDesigner
from manhwa_studio.studio_pro.marathon_engine import MarathonEngine
from manhwa_studio.studio_pro.youtube_kit import YouTubeKitGenerator
from manhwa_studio.studio_pro.cold_open_director import ColdOpenDirector
from manhwa_studio.studio_pro.pro_pipeline import ProPipeline

__all__ = [
    "SeriesManager",
    "SeriesProfile",
    "VoiceSetting",
    "SubtitleStyle",
    "VoiceDirector",
    "AudioDirector",
    "KineticSubtitleGenerator",
    "CameraDirector",
    "ThumbnailDesigner",
    "MarathonEngine",
    "YouTubeKitGenerator",
    "ColdOpenDirector",
    "ProPipeline",
]
