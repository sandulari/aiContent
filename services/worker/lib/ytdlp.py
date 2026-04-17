"""
yt-dlp wrapper for downloading videos from Instagram, YouTube, TikTok, etc.
"""

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.environ.get("VRE_DOWNLOAD_DIR", "/tmp/vre_downloads")


@dataclass
class DownloadResult:
    file_path: str
    info_json_path: str
    resolution: str
    fps: float
    codec: str
    bitrate: int
    duration: float
    file_size: int


def download_video(url: str, video_id: str) -> DownloadResult:
    """
    Download a video using yt-dlp with best quality settings.

    Args:
        url: The video URL to download.
        video_id: Unique identifier used for the output filename.

    Returns:
        DownloadResult with file metadata.
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    output_template = os.path.join(DOWNLOAD_DIR, f"{video_id}.%(ext)s")

    cmd = [
        "yt-dlp",
        "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--write-info-json",
        "--no-playlist",
        "--retries", "5",
        "--socket-timeout", "30",
        "--output", output_template,
        "--no-overwrites",
        "--no-check-certificates",
        "--max-filesize", "500M",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        url,
    ]

    logger.info("Downloading video %s from %s", video_id, url)
    logger.debug("Command: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
        logger.debug("yt-dlp stdout: %s", result.stdout[-500:] if result.stdout else "")
    except subprocess.CalledProcessError as exc:
        logger.warning("yt-dlp first attempt failed for %s, trying simpler format: %s", video_id, str(exc.stderr)[-200:])
        # Retry with simpler format
        fallback_cmd = [
            "yt-dlp", "--format", "best", "--merge-output-format", "mp4",
            "--write-info-json", "--no-playlist", "--retries", "3",
            "--output", output_template, "--no-overwrites",
            "--no-check-certificates", url,
        ]
        try:
            subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=600, check=True)
        except subprocess.CalledProcessError as exc2:
            logger.error("yt-dlp fallback also failed for %s: %s", video_id, str(exc2.stderr)[-300:])
            raise RuntimeError(f"yt-dlp download failed for {video_id}: {exc2.stderr}") from exc2
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"yt-dlp download timed out for {video_id}") from exc

    # Locate output files
    video_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
    info_json_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.info.json")

    if not os.path.exists(video_path):
        # Sometimes yt-dlp uses a different extension; scan directory
        for fname in os.listdir(DOWNLOAD_DIR):
            if fname.startswith(video_id) and not fname.endswith(".info.json"):
                video_path = os.path.join(DOWNLOAD_DIR, fname)
                break

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Downloaded video not found for {video_id} in {DOWNLOAD_DIR}")

    # Parse info.json for metadata
    resolution = ""
    fps = 0.0
    codec = ""
    bitrate = 0
    duration = 0.0

    if os.path.exists(info_json_path):
        try:
            with open(info_json_path, "r") as f:
                info = json.load(f)
            width = info.get("width", 0) or 0
            height = info.get("height", 0) or 0
            resolution = f"{width}x{height}" if width and height else ""
            fps = float(info.get("fps", 0) or 0)
            codec = info.get("vcodec", "") or ""
            bitrate = int(info.get("tbr", 0) or 0) * 1000  # kbps → bps
            duration = float(info.get("duration", 0) or 0)
        except Exception as exc:
            logger.warning("Failed to parse info.json for %s: %s", video_id, exc)
    else:
        info_json_path = ""

    # Validate the downloaded file is a real video
    try:
        probe_cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=codec_type", "-of", "csv=p=0", video_path]
        probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        if "video" not in (probe.stdout or ""):
            raise RuntimeError(f"Downloaded file is not a valid video: {video_path}")
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe timed out validating %s", video_path)

    file_size = os.path.getsize(video_path)

    logger.info(
        "Downloaded %s: %s, %.1fs, %s, %.0f fps, %d bytes",
        video_id, resolution, duration, codec, fps, file_size,
    )

    return DownloadResult(
        file_path=video_path,
        info_json_path=info_json_path,
        resolution=resolution,
        fps=fps,
        codec=codec,
        bitrate=bitrate,
        duration=duration,
        file_size=file_size,
    )
