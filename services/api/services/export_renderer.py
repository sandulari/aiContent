"""
Export renderer service — constructs FFmpeg commands for final video export.
Actual rendering happens in the Celery worker; this module builds the render spec.
"""
from typing import Any, Dict
from uuid import UUID


def build_render_spec(
    video_minio_key: str,
    export_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a render specification dict that the exporter worker consumes."""
    spec = {
        "video_key": video_minio_key,
        "output_resolution": export_data.get("export_resolution", "1080x1920"),
        "video_crop": export_data.get("video_crop"),
        "video_trim": export_data.get("video_trim"),
        "audio_config": export_data.get("audio_config"),
        "headline": {
            "text": export_data.get("headline_text", ""),
            "font_family": export_data.get("headline_font_family", "Inter"),
            "font_size": export_data.get("headline_font_size", 48),
            "font_weight": export_data.get("headline_font_weight", 700),
            "color": export_data.get("headline_color", "#FFFFFF"),
            "position": export_data.get("headline_position", {"x": 0.5, "y": 0.75}),
            "text_shadow": export_data.get("headline_text_shadow"),
            "text_stroke": export_data.get("headline_text_stroke"),
            "letter_spacing": export_data.get("headline_letter_spacing"),
            "text_transform": export_data.get("headline_text_transform"),
        },
        "subtitle": {
            "text": export_data.get("subtitle_text", ""),
            "font_family": export_data.get("subtitle_font_family", "Inter"),
            "font_size": export_data.get("subtitle_font_size", 24),
            "font_weight": export_data.get("subtitle_font_weight", 400),
            "color": export_data.get("subtitle_color", "#CCCCCC"),
            "position": export_data.get("subtitle_position", {"x": 0.5, "y": 0.82}),
        },
        "logo": export_data.get("logo_position"),
    }
    return spec
