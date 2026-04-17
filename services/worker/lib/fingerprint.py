"""
Video fingerprinting: keyframe extraction, perceptual hashing, audio segments.
"""

import logging
import os
import subprocess
import tempfile
from typing import List

logger = logging.getLogger(__name__)

KEYFRAME_DIR = os.environ.get("VRE_KEYFRAME_DIR", "/tmp/vre_keyframes")


def extract_keyframes(
    video_path: str,
    video_id: str,
    interval: int = 2,
    max_frames: int = 15,
) -> List[str]:
    """
    Extract keyframes from a video at regular intervals using FFmpeg.

    Args:
        video_path: Path to the video file.
        video_id: Unique ID for organizing output frames.
        interval: Seconds between keyframe captures.
        max_frames: Maximum number of frames to extract.

    Returns:
        List of file paths to extracted keyframe images.
    """
    output_dir = os.path.join(KEYFRAME_DIR, video_id)
    os.makedirs(output_dir, exist_ok=True)

    output_pattern = os.path.join(output_dir, "frame_%04d.png")

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vf", f"fps=1/{interval}",
        "-frames:v", str(max_frames),
        "-q:v", "2",
        "-y",
        output_pattern,
    ]

    logger.info("Extracting keyframes from %s (interval=%ds, max=%d)", video_id, interval, max_frames)

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
    except subprocess.CalledProcessError as exc:
        logger.error("FFmpeg keyframe extraction failed for %s: %s", video_id, exc.stderr[-300:] if exc.stderr else "")
        raise RuntimeError(f"Keyframe extraction failed for {video_id}") from exc

    frames = sorted(
        [os.path.join(output_dir, f) for f in os.listdir(output_dir) if f.endswith(".png")]
    )
    logger.info("Extracted %d keyframes for %s", len(frames), video_id)
    return frames


def compute_phash(image_path: str) -> str:
    """
    Compute perceptual hash (pHash) for an image.

    Returns hex string of the hash.
    """
    try:
        from PIL import Image
        import imagehash

        img = Image.open(image_path)
        h = imagehash.phash(img, hash_size=16)
        return str(h)
    except ImportError:
        logger.warning("imagehash not available, using ffmpeg-based fallback")
        return _phash_ffmpeg_fallback(image_path)


def _phash_ffmpeg_fallback(image_path: str) -> str:
    """Compute a simple hash using FFmpeg thumbnail and raw pixel comparison."""
    import hashlib
    from PIL import Image
    import io

    cmd = [
        "ffmpeg",
        "-i", image_path,
        "-vf", "scale=32:32,format=gray",
        "-frames:v", "1",
        "-f", "rawvideo",
        "-y",
        "pipe:1",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        return hashlib.md5(result.stdout).hexdigest()
    except Exception as exc:
        logger.error("Fallback phash failed for %s: %s", image_path, exc)
        return ""


def extract_audio_segment(
    video_path: str,
    video_id: str,
    duration: int = 30,
) -> str:
    """
    Extract an audio segment from a video for fingerprinting.

    Args:
        video_path: Path to the video file.
        video_id: Unique identifier.
        duration: Duration in seconds to extract.

    Returns:
        Path to the extracted WAV audio file.
    """
    output_dir = os.path.join(KEYFRAME_DIR, video_id)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "audio_segment.wav")

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-t", str(duration),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-y",
        output_path,
    ]

    logger.info("Extracting audio segment from %s (%ds)", video_id, duration)

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
    except subprocess.CalledProcessError as exc:
        logger.error("Audio extraction failed for %s: %s", video_id, exc.stderr[-300:] if exc.stderr else "")
        raise RuntimeError(f"Audio extraction failed for {video_id}") from exc

    if not os.path.exists(output_path):
        raise FileNotFoundError(f"Audio segment not found for {video_id}")

    logger.info("Extracted audio segment: %s", output_path)
    return output_path


def compare_phashes(h1: str, h2: str) -> int:
    """
    Compare two perceptual hashes and return the Hamming distance.

    Lower distance = more similar. 0 = identical.
    """
    if not h1 or not h2:
        return 999

    try:
        import imagehash

        hash1 = imagehash.hex_to_hash(h1)
        hash2 = imagehash.hex_to_hash(h2)
        return hash1 - hash2
    except ImportError:
        # Manual hex comparison fallback
        if len(h1) != len(h2):
            return 999
        try:
            val1 = int(h1, 16)
            val2 = int(h2, 16)
            xor = val1 ^ val2
            return bin(xor).count("1")
        except ValueError:
            return 999
