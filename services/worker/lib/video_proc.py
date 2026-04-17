"""
Full video processing library: enhancement pipeline and user export rendering.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Dict, Optional

logger = logging.getLogger(__name__)

WORK_DIR = os.environ.get("VRE_WORK_DIR", "/tmp/vre_processing")
REALESRGAN_BIN = os.environ.get("REALESRGAN_BIN", "realesrgan-ncnn-vulkan")
RIFE_BIN = os.environ.get("RIFE_BIN", "rife-ncnn-vulkan")


def get_video_fps(path: str) -> float:
    """Get the FPS of a video file using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            r_frame_rate = streams[0].get("r_frame_rate", "30/1")
            num, den = r_frame_rate.split("/")
            return round(float(num) / float(den), 2)
    except Exception as exc:
        logger.warning("Failed to get FPS for %s: %s", path, exc)
    return 30.0


def get_video_resolution(path: str) -> str:
    """Get the resolution of a video file as 'WIDTHxHEIGHT'."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            w = streams[0].get("width", 0)
            h = streams[0].get("height", 0)
            return f"{w}x{h}"
    except Exception as exc:
        logger.warning("Failed to get resolution for %s: %s", path, exc)
    return "0x0"


def trim_video(input_path: str, output_path: str, start: float, end: float):
    """Trim a video to [start, end] seconds using FFmpeg."""
    duration = end - start
    cmd = [
        "ffmpeg",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",
        "-y",
        output_path,
    ]
    logger.info("Trimming %s [%.1f-%.1f] → %s", input_path, start, end, output_path)
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    except subprocess.CalledProcessError as exc:
        logger.error("Trim failed: %s", exc.stderr[-300:] if exc.stderr else "")
        raise RuntimeError(f"Trim failed: {exc.stderr}") from exc


def _upscale_frames_realesrgan(input_dir: str, output_dir: str, scale: int = 2) -> bool:
    """Upscale frames using Real-ESRGAN. Returns True on success."""
    cmd = [
        REALESRGAN_BIN,
        "-i", input_dir,
        "-o", output_dir,
        "-s", str(scale),
        "-n", "realesrgan-x4plus",
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
        logger.info("Real-ESRGAN upscaling complete")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("Real-ESRGAN failed (will use lanczos fallback): %s", exc)
        return False


def _upscale_frames_lanczos(input_dir: str, output_dir: str, target_w: int = 1080, target_h: int = 1920):
    """Upscale frames using FFmpeg lanczos filter as fallback."""
    os.makedirs(output_dir, exist_ok=True)
    frames = sorted([f for f in os.listdir(input_dir) if f.endswith(".png")])
    for frame in frames:
        in_path = os.path.join(input_dir, frame)
        out_path = os.path.join(output_dir, frame)
        cmd = [
            "ffmpeg",
            "-i", in_path,
            "-vf", f"scale={target_w}:{target_h}:flags=lanczos",
            "-y",
            out_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
        except subprocess.CalledProcessError as exc:
            logger.warning("Lanczos upscale failed for %s: %s", frame, exc)
            shutil.copy2(in_path, out_path)

    logger.info("Lanczos upscaling complete for %d frames", len(frames))


def _interpolate_rife(input_dir: str, output_dir: str, multiplier: int = 2) -> bool:
    """Interpolate frames using RIFE for higher FPS. Returns True on success."""
    cmd = [
        RIFE_BIN,
        "-i", input_dir,
        "-o", output_dir,
        "-m", f"rife-v4.6",
        "-n", str(multiplier),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
        logger.info("RIFE interpolation complete (x%d)", multiplier)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("RIFE interpolation failed (skipping): %s", exc)
        return False


def _normalize_audio(input_path: str, output_path: str):
    """Normalize audio loudness using FFmpeg loudnorm filter."""
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-y",
        output_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
        logger.info("Audio normalization complete")
    except subprocess.CalledProcessError as exc:
        logger.warning("Audio normalization failed, copying original: %s", exc)
        shutil.copy2(input_path, output_path)


def enhance_video(input_path: str, video_id: str) -> str:
    """
    Full enhancement pipeline:
    1. Extract all frames
    2. Upscale with Real-ESRGAN (lanczos fallback)
    3. Optional RIFE frame interpolation
    4. Audio normalization
    5. Final encode to high-quality MP4

    Args:
        input_path: Path to the raw video file.
        video_id: Unique identifier for temp directories.

    Returns:
        Path to the enhanced video file.
    """
    work = os.path.join(WORK_DIR, f"enhance_{video_id}")
    os.makedirs(work, exist_ok=True)

    raw_frames_dir = os.path.join(work, "raw_frames")
    upscaled_dir = os.path.join(work, "upscaled_frames")
    interp_dir = os.path.join(work, "interp_frames")
    os.makedirs(raw_frames_dir, exist_ok=True)
    os.makedirs(upscaled_dir, exist_ok=True)
    os.makedirs(interp_dir, exist_ok=True)

    original_fps = get_video_fps(input_path)
    logger.info("Enhancing video %s (fps=%.2f)", video_id, original_fps)

    # Step 1: Extract all frames
    extract_cmd = [
        "ffmpeg",
        "-i", input_path,
        "-qscale:v", "1",
        "-y",
        os.path.join(raw_frames_dir, "frame_%06d.png"),
    ]
    try:
        subprocess.run(extract_cmd, capture_output=True, text=True, timeout=600, check=True)
    except subprocess.CalledProcessError as exc:
        logger.error("Frame extraction failed for %s: %s", video_id, exc.stderr[-300:] if exc.stderr else "")
        raise RuntimeError(f"Frame extraction failed for {video_id}") from exc

    frame_count = len([f for f in os.listdir(raw_frames_dir) if f.endswith(".png")])
    logger.info("Extracted %d frames from %s", frame_count, video_id)

    # Step 2: Upscale frames
    if not _upscale_frames_realesrgan(raw_frames_dir, upscaled_dir):
        _upscale_frames_lanczos(raw_frames_dir, upscaled_dir)

    # Step 3: Optional RIFE interpolation (double FPS if original < 30)
    final_frames_dir = upscaled_dir
    final_fps = original_fps
    if original_fps < 30:
        if _interpolate_rife(upscaled_dir, interp_dir, multiplier=2):
            final_frames_dir = interp_dir
            final_fps = original_fps * 2

    # Step 4: Extract and normalize audio
    audio_raw = os.path.join(work, "audio_raw.aac")
    audio_norm = os.path.join(work, "audio_norm.aac")

    audio_extract_cmd = [
        "ffmpeg", "-i", input_path, "-vn", "-c:a", "aac", "-b:a", "192k", "-y", audio_raw,
    ]
    has_audio = True
    try:
        subprocess.run(audio_extract_cmd, capture_output=True, text=True, timeout=120, check=True)
        _normalize_audio(audio_raw, audio_norm)
    except subprocess.CalledProcessError:
        logger.warning("No audio track or extraction failed for %s", video_id)
        has_audio = False

    # Step 5: Final encode
    output_path = os.path.join(work, f"{video_id}_enhanced.mp4")

    encode_cmd = [
        "ffmpeg",
        "-framerate", str(final_fps),
        "-i", os.path.join(final_frames_dir, "frame_%06d.png"),
    ]
    if has_audio and os.path.exists(audio_norm):
        encode_cmd.extend(["-i", audio_norm])

    encode_cmd.extend([
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ])

    if has_audio and os.path.exists(audio_norm):
        encode_cmd.extend(["-c:a", "aac", "-b:a", "192k"])

    encode_cmd.extend(["-y", output_path])

    try:
        subprocess.run(encode_cmd, capture_output=True, text=True, timeout=600, check=True)
    except subprocess.CalledProcessError as exc:
        logger.error("Final encode failed for %s: %s", video_id, exc.stderr[-300:] if exc.stderr else "")
        raise RuntimeError(f"Final encode failed for {video_id}") from exc

    # Cleanup raw frames to save disk (keep enhanced output)
    for d in [raw_frames_dir, upscaled_dir, interp_dir]:
        try:
            shutil.rmtree(d)
        except Exception:
            pass

    logger.info("Enhancement complete for %s → %s", video_id, output_path)
    return output_path


# ══════════════════════════════════════════════════════════════════════
# User export rendering
# ══════════════════════════════════════════════════════════════════════
# Consumes the JSONB shape the API + editor actually write:
#   video_trim      = {start_seconds, end_seconds}
#   video_transform = {x, y, w, h, flipH}       (px offsets into 360x640 canvas)
#   headline_text   + headline_style = {fontFamily, fontSize, fontWeight,
#                                       color, alignment, letterSpacing,
#                                       textTransform, shadowEnabled, shadowX,
#                                       shadowY, shadowBlur, shadowColor,
#                                       strokeEnabled, strokeWidth, strokeColor,
#                                       opacity, x (%), y (%)}
#   subtitle_text   + subtitle_style = same shape
#   logo_overrides  = {x (%), y (%), size (px), shape ('circle'|'rounded'|
#                      'square'), objectFit ('contain'|'cover'), transparent,
#                      backgroundColor, borderWidth, borderColor, opacity}
#   audio_config    = {muted, original_volume, custom_audio_key, custom_volume,
#                      fade_in, fade_out}
#
# Text + logo are pre-rendered with Pillow to transparent PNGs sized
# 1080×1920 so FFmpeg just overlays them with a single filter, which
# gives us exact styling control (shadow, stroke, shape mask, object fit)
# that FFmpeg's drawtext can't do on its own.
# ──────────────────────────────────────────────────────────────────────

_CANVAS_W = 1080
_CANVAS_H = 1920
_EDITOR_W = 360
_EDITOR_H = 640
_PX_SCALE_X = _CANVAS_W / _EDITOR_W  # 3.0
_PX_SCALE_Y = _CANVAS_H / _EDITOR_H  # 3.0

# Map UI font family names → (regular_path, bold_path). Files are resolved
# at runtime via fontconfig-style search in common /usr/share/fonts paths,
# with a DejaVu fallback so rendering never crashes on an exotic request.
_FONT_SEARCH_DIRS = [
    "/usr/share/fonts/opentype/inter",  # Inter from fonts-inter package
    "/usr/share/fonts/truetype/vre-ui",  # custom bundled fonts (if present)
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/liberation2",
    "/usr/share/fonts/truetype",
    "/usr/share/fonts",
]

_FONT_FALLBACK_REG = "DejaVuSans.ttf"
_FONT_FALLBACK_BOLD = "DejaVuSans-Bold.ttf"

# Map UI font-family names to the on-disk filenames of the TTF/OTF
# files we ship in the worker image. Covers Inter (the editor default)
# with every weight variant available, plus a few common alternates
# the editor offers in its font picker.
_FONT_FAMILY_MAP: dict[str, dict[int, str]] = {
    "Inter": {
        # Debian fonts-inter package uses variable font; common filenames.
        300: "Inter-Light.otf",
        400: "Inter-Regular.otf",
        500: "Inter-Medium.otf",
        600: "Inter-SemiBold.otf",
        700: "Inter-Bold.otf",
        800: "Inter-ExtraBold.otf",
        900: "Inter-Black.otf",
    },
    "Roboto": {
        300: "Roboto-Light.ttf",
        400: "Roboto-Regular.ttf",
        500: "Roboto-Medium.ttf",
        700: "Roboto-Bold.ttf",
        900: "Roboto-Black.ttf",
    },
    "Open Sans": {
        300: "OpenSans-Light.ttf",
        400: "OpenSans-Regular.ttf",
        600: "OpenSans-Semibold.ttf",
        700: "OpenSans-Bold.ttf",
        800: "OpenSans-ExtraBold.ttf",
    },
    "Lato": {
        300: "Lato-Light.ttf",
        400: "Lato-Regular.ttf",
        700: "Lato-Bold.ttf",
        900: "Lato-Black.ttf",
    },
    "DejaVu Sans": {
        400: "DejaVuSans.ttf",
        700: "DejaVuSans-Bold.ttf",
    },
}


def _find_font_file(name: str) -> str | None:
    for root in _FONT_SEARCH_DIRS:
        if not os.path.isdir(root):
            continue
        for cur, _, files in os.walk(root):
            for f in files:
                if f.lower() == name.lower():
                    return os.path.join(cur, f)
    return None


# Horizontal padding inside a text box, in logical (360-wide) pixels.
# Matches the editor's CSS `padding: 4px 8px` so line wrapping is
# consistent between the editor and the rendered MP4.
_TEXT_PAD_X_EDITOR = 8
# Vertical padding — larger because it needs to leave room for drop
# shadow and stroke outlines.
_TEXT_PAD_Y_EXPORT_MIN = 20


def _resolve_font(family: str, weight: int) -> str:
    """Return the best font path available for a given UI family + weight.

    Order of preference:
    1. Explicit family→weight map (`_FONT_FAMILY_MAP`) — handles Inter
       which ships as `.otf` with weight-suffixed filenames
    2. Convention-based lookup (`{compact}-Bold.ttf`, `{compact}.ttf`)
    3. DejaVu Sans fallback
    4. Any `.ttf`/`.otf` that exists on disk
    """
    fam = (family or "").strip()
    want_bold = weight >= 600

    # 1. Explicit map
    if fam in _FONT_FAMILY_MAP:
        weights = _FONT_FAMILY_MAP[fam]
        # Pick the closest available weight
        available = sorted(weights.keys())
        closest = min(available, key=lambda w: abs(w - weight))
        mapped = weights[closest]
        path = _find_font_file(mapped)
        if path:
            return path

    variants: list[str] = []
    if fam:
        compact = fam.replace(" ", "")
        variants.extend([
            f"{compact}-Bold.otf" if want_bold else f"{compact}-Regular.otf",
            f"{compact}-Bold.ttf" if want_bold else f"{compact}-Regular.ttf",
            f"{compact}.otf",
            f"{compact}.ttf",
        ])
    variants.extend([
        _FONT_FALLBACK_BOLD if want_bold else _FONT_FALLBACK_REG,
        _FONT_FALLBACK_REG,
    ])
    for v in variants:
        path = _find_font_file(v)
        if path:
            return path
    # Absolute last-ditch: return any font
    for root in _FONT_SEARCH_DIRS:
        if os.path.isdir(root):
            for cur, _, files in os.walk(root):
                for f in files:
                    if f.lower().endswith((".ttf", ".otf")):
                        return os.path.join(cur, f)
    raise RuntimeError("No TTF/OTF fonts available in the worker image")


def _hex_to_rgba(hex_str: str, alpha: int = 255) -> tuple[int, int, int, int]:
    """Parse '#RRGGBB' or '#RGB' into an RGBA tuple."""
    if not hex_str:
        return (255, 255, 255, alpha)
    s = hex_str.lstrip("#")
    try:
        if len(s) == 3:
            r, g, b = (int(s[i] * 2, 16) for i in range(3))
        elif len(s) == 6:
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        else:
            return (255, 255, 255, alpha)
    except Exception:
        return (255, 255, 255, alpha)
    return (r, g, b, alpha)


def _apply_text_transform(text: str, style: dict) -> str:
    mode = (style or {}).get("textTransform", "none")
    if mode == "uppercase":
        return text.upper()
    if mode == "lowercase":
        return text.lower()
    return text


def _measure_text(draw, font, s: str) -> int:
    try:
        bbox = draw.textbbox((0, 0), s, font=font)
        return bbox[2] - bbox[0]
    except Exception:
        return len(s) * getattr(font, "size", 10) // 2


def _break_long_word(word: str, font, max_width_px: int, draw) -> list[str]:
    """Break a single word that's wider than the line into multiple
    character-sized chunks so nothing overflows the box."""
    if _measure_text(draw, font, word) <= max_width_px:
        return [word]
    chunks: list[str] = []
    current = ""
    for ch in word:
        candidate = current + ch
        if _measure_text(draw, font, candidate) <= max_width_px or not current:
            current = candidate
        else:
            chunks.append(current)
            current = ch
    if current:
        chunks.append(current)
    return chunks


def _wrap_text_to_width(
    text: str,
    font,
    max_width_px: int,
    draw,
) -> list[str]:
    """Greedy word-wrap that respects hard newlines.

    Splits on whitespace and explicit `\\n`, packs words into lines that
    don't exceed `max_width_px` when measured with the given font.
    Also character-breaks single words that are wider than the line
    so abnormally long tokens never overflow the text box.
    """
    lines: list[str] = []
    paragraphs = (text or "").split("\n")
    for para in paragraphs:
        if not para.strip():
            lines.append("")
            continue
        words = para.split()
        current = ""
        for word in words:
            # If a single word is wider than max_width, break it mid-word
            # into character chunks. Each chunk becomes its own line.
            if _measure_text(draw, font, word) > max_width_px:
                if current:
                    lines.append(current)
                    current = ""
                chunks = _break_long_word(word, font, max_width_px, draw)
                # All chunks except the last become their own line
                for chunk in chunks[:-1]:
                    lines.append(chunk)
                current = chunks[-1]
                continue
            candidate = (current + " " + word).strip() if current else word
            if _measure_text(draw, font, candidate) <= max_width_px or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines or [""]


def _render_text_layer_png(text: str, style: dict, out_path: str) -> bool:
    """Render a single text layer to a transparent 1080×1920 PNG.

    Honors the editor's `w` (box width in logical 360px units), wrapping
    the text inside that width exactly like the editor preview.
    """
    if not text or not text.strip():
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter  # local import
    except Exception as exc:
        logger.warning("Pillow unavailable, skipping text layer: %s", exc)
        return False

    s = style or {}
    text_rendered = _apply_text_transform(text, s)

    try:
        font_size_editor = int(s.get("fontSize") or 48)
    except Exception:
        font_size_editor = 48
    font_size = max(8, int(font_size_editor * _PX_SCALE_X))

    weight = int(s.get("fontWeight") or 700)
    family = s.get("fontFamily") or "Inter"

    try:
        font_path = _resolve_font(family, weight)
        font = ImageFont.truetype(font_path, font_size)
    except Exception as exc:
        logger.warning("font resolve failed (%s %s): %s", family, weight, exc)
        return False

    opacity = max(0, min(100, int(s.get("opacity", 100))))
    alpha = int(round(opacity / 100 * 255))
    color = _hex_to_rgba(s.get("color") or "#FFFFFF", alpha)
    alignment = (s.get("alignment") or "center").lower()

    # Text box width: editor saves `w` in 360-logical pixels; scale 3× for 1080.
    box_w_editor = float(s.get("w") or (_EDITOR_W * 0.85))
    box_w_px = max(60, int(box_w_editor * _PX_SCALE_X))

    # Measurement draw context (off-screen).
    _probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    probe_draw = ImageDraw.Draw(_probe)

    # Horizontal padding: MATCH the editor CSS exactly (8px @ 360w → 24px @ 1080w).
    # This is what guarantees the same line wrapping as the browser.
    pad_x = int(_TEXT_PAD_X_EDITOR * _PX_SCALE_X)
    # Vertical padding: leave room for shadow/stroke.
    pad_y = max(_TEXT_PAD_Y_EXPORT_MIN, int(font_size * 0.4))

    content_w = max(20, box_w_px - pad_x * 2)
    lines = _wrap_text_to_width(text_rendered, font, content_w, probe_draw)

    # Measure line height from the font itself so vertical rhythm is
    # consistent even for lines containing only ascenders/descenders.
    try:
        ascent, descent = font.getmetrics()
        line_height = int((ascent + descent) * 1.15)
    except Exception:
        line_height = int(font_size * 1.2)

    # Compute widest line so the layer can grow to accommodate text
    # that's naturally narrower than the box.
    max_line_w = 0
    line_widths: list[int] = []
    for line in lines:
        try:
            bb = probe_draw.textbbox((0, 0), line, font=font)
            lw = bb[2] - bb[0]
        except Exception:
            lw = len(line) * font_size // 2
        line_widths.append(lw)
        if lw > max_line_w:
            max_line_w = lw

    # Layer dimensions — box_w_px is the canvas width, height grows
    # with line count. Uses separate horizontal and vertical padding.
    layer_w = box_w_px
    layer_h = pad_y * 2 + line_height * len(lines)

    text_layer = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)

    stroke_enabled = bool(s.get("strokeEnabled"))
    stroke_w = int(s.get("strokeWidth") or 0) if stroke_enabled else 0
    stroke_color = _hex_to_rgba(s.get("strokeColor") or "#000000", alpha) if stroke_enabled else None

    def _line_x(line_w: int) -> int:
        if alignment == "left":
            return pad_x
        if alignment == "right":
            return layer_w - pad_x - line_w
        return (layer_w - line_w) // 2  # center

    # ── Shadow pass ───────────────────────────────────────────────
    if s.get("shadowEnabled"):
        shadow_color = _hex_to_rgba(s.get("shadowColor") or "#000000", alpha)
        shadow_x = int(s.get("shadowX") or 0)
        shadow_y = int(s.get("shadowY") or 2)
        shadow_blur = int(s.get("shadowBlur") or 6)
        shadow_layer = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
        sd_draw = ImageDraw.Draw(shadow_layer)
        for i, line in enumerate(lines):
            if not line:
                continue
            lx = _line_x(line_widths[i]) + shadow_x
            ly = pad_y + i * line_height + shadow_y
            try:
                sd_draw.text((lx, ly), line, font=font, fill=shadow_color)
            except Exception as exc:
                logger.warning("shadow draw failed: %s", exc)
        if shadow_blur > 0:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur))
        text_layer = Image.alpha_composite(text_layer, shadow_layer)
        draw = ImageDraw.Draw(text_layer)

    # ── Main text pass ────────────────────────────────────────────
    for i, line in enumerate(lines):
        if not line:
            continue
        lx = _line_x(line_widths[i])
        ly = pad_y + i * line_height
        try:
            if stroke_w > 0 and stroke_color is not None:
                draw.text(
                    (lx, ly),
                    line,
                    font=font,
                    fill=color,
                    stroke_width=stroke_w,
                    stroke_fill=stroke_color,
                )
            else:
                draw.text((lx, ly), line, font=font, fill=color)
        except Exception as exc:
            logger.warning("text draw failed: %s", exc)
            return False

    # ── Composite onto the full 1080×1920 canvas ──────────────────
    canvas = Image.new("RGBA", (_CANVAS_W, _CANVAS_H), (0, 0, 0, 0))
    try:
        x_pct = float(s.get("x", 50)) / 100
        y_pct = float(s.get("y", 65)) / 100
    except Exception:
        x_pct, y_pct = 0.5, 0.65
    center_x = int(x_pct * _CANVAS_W)
    center_y = int(y_pct * _CANVAS_H)
    paste_x = center_x - layer_w // 2
    paste_y = center_y - layer_h // 2
    canvas.alpha_composite(text_layer, (paste_x, paste_y))

    try:
        canvas.save(out_path, "PNG")
    except Exception as exc:
        logger.warning("text png save failed: %s", exc)
        return False
    return True


def _render_logo_layer_png(logo_src: str, overrides: dict, out_path: str) -> bool:
    """Compose the brand logo at the requested size / shape / fit / bg,
    over an otherwise transparent 1080×1920 canvas."""
    if not logo_src or not os.path.exists(logo_src):
        return False
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        logger.warning("Pillow unavailable for logo: %s", exc)
        return False

    o = overrides or {}
    size_editor = int(o.get("size") or 56)
    size_px = max(16, int(size_editor * _PX_SCALE_X))
    shape = (o.get("shape") or "circle").lower()
    fit = (o.get("objectFit") or "contain").lower()
    transparent = o.get("transparent", True)
    bg_color = _hex_to_rgba(o.get("backgroundColor") or "#1a1a2e", 255)
    border_w_editor = int(o.get("borderWidth") or 0)
    border_w = int(border_w_editor * _PX_SCALE_X)
    border_color = _hex_to_rgba(o.get("borderColor") or "#484f58", 255)
    opacity = max(0, min(100, int(o.get("opacity", 100))))

    try:
        src = Image.open(logo_src).convert("RGBA")
    except Exception as exc:
        logger.warning("logo open failed: %s", exc)
        return False

    tile = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))

    if not transparent:
        # Fill the background layer.
        bg = Image.new("RGBA", (size_px, size_px), bg_color)
        tile = Image.alpha_composite(tile, bg)

    # Fit the source image into the tile.
    src_w, src_h = src.size
    if fit == "cover":
        scale = max(size_px / src_w, size_px / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
        x_off = (size_px - new_w) // 2
        y_off = (size_px - new_h) // 2
        inner = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
        inner.alpha_composite(resized, (x_off, y_off))
    else:
        scale = min(size_px / src_w, size_px / src_h)
        new_w = max(1, int(src_w * scale))
        new_h = max(1, int(src_h * scale))
        resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
        x_off = (size_px - new_w) // 2
        y_off = (size_px - new_h) // 2
        inner = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
        inner.alpha_composite(resized, (x_off, y_off))

    tile = Image.alpha_composite(tile, inner)

    # Shape mask
    mask = Image.new("L", (size_px, size_px), 0)
    md = ImageDraw.Draw(mask)
    if shape == "circle":
        md.ellipse((0, 0, size_px - 1, size_px - 1), fill=255)
    elif shape == "rounded":
        radius = max(4, size_px // 8)
        md.rounded_rectangle((0, 0, size_px - 1, size_px - 1), radius=radius, fill=255)
    else:
        md.rectangle((0, 0, size_px - 1, size_px - 1), fill=255)
    shaped = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    shaped.paste(tile, (0, 0), mask)

    # Border
    if border_w > 0:
        bd = ImageDraw.Draw(shaped)
        for i in range(border_w):
            if shape == "circle":
                bd.ellipse((i, i, size_px - 1 - i, size_px - 1 - i), outline=border_color)
            elif shape == "rounded":
                radius = max(4, size_px // 8) - i
                bd.rounded_rectangle((i, i, size_px - 1 - i, size_px - 1 - i), radius=max(1, radius), outline=border_color)
            else:
                bd.rectangle((i, i, size_px - 1 - i, size_px - 1 - i), outline=border_color)

    # Opacity
    if opacity < 100:
        alpha = shaped.split()[-1].point(lambda v: int(v * opacity / 100))
        shaped.putalpha(alpha)

    # Composite onto the 1080×1920 canvas at the requested position.
    canvas = Image.new("RGBA", (_CANVAS_W, _CANVAS_H), (0, 0, 0, 0))
    try:
        x_pct = float(o.get("x", 50)) / 100
        y_pct = float(o.get("y", 8)) / 100
    except Exception:
        x_pct, y_pct = 0.5, 0.08
    cx = int(x_pct * _CANVAS_W)
    cy = int(y_pct * _CANVAS_H)
    canvas.alpha_composite(shaped, (cx - size_px // 2, cy - size_px // 2))

    try:
        canvas.save(out_path, "PNG")
    except Exception as exc:
        logger.warning("logo png save failed: %s", exc)
        return False
    return True


def _build_video_filter_chain(
    video_trim: dict | None,
    video_transform: dict | None,
) -> tuple[str, str, dict]:
    """Build the audio + video filter chains for the export.

    Returns `(video_chain, audio_chain, video_transform_info)`.

    The video chain handles trim, optional flip, and scaling to the
    user's requested dimensions. The caller is responsible for
    compositing the scaled video onto a 1080×1920 black canvas via an
    `overlay` filter, using the offset in `video_transform_info`. This
    two-stage approach is the only way to support user-resized layers
    that extend past the canvas edges without ffmpeg rejecting the
    pad filter (pad can't shrink, and layers larger than the canvas
    must be clipped by the overlay, not the pad).
    """
    vparts: list[str] = []
    aparts: list[str] = []

    start = 0.0
    end: float | None = None
    if isinstance(video_trim, dict):
        try:
            start = float(video_trim.get("start_seconds") or 0)
        except Exception:
            start = 0.0
        try:
            raw_end = video_trim.get("end_seconds")
            end = float(raw_end) if raw_end not in (None, "") else None
        except Exception:
            end = None

    if start > 0 or (end is not None and end > 0):
        trim_expr = [f"start={start}"]
        if end is not None and end > 0:
            trim_expr.append(f"end={end}")
        vparts.append("trim=" + ":".join(trim_expr))
        vparts.append("setpts=PTS-STARTPTS")
        atrim_expr = [f"start={start}"]
        if end is not None and end > 0:
            atrim_expr.append(f"end={end}")
        aparts.append("atrim=" + ":".join(atrim_expr))
        aparts.append("asetpts=PTS-STARTPTS")

    # Parse the user's transform in editor coordinates (0-360 wide, 0-640 tall).
    if isinstance(video_transform, dict):
        try:
            tx = float(video_transform.get("x") or 0)
            ty = float(video_transform.get("y") or 0)
            tw = float(video_transform.get("w") or _EDITOR_W)
            th = float(video_transform.get("h") or _EDITOR_H)
        except Exception:
            tx = ty = 0.0
            tw = _EDITOR_W
            th = _EDITOR_H
    else:
        tx = ty = 0.0
        tw = _EDITOR_W
        th = _EDITOR_H

    # Clamp to sane bounds so malformed API input can't produce
    # gigapixel outputs or negative dimensions that crash ffmpeg.
    tw = max(16.0, min(float(_EDITOR_W) * 3, tw))
    th = max(16.0, min(float(_EDITOR_H) * 3, th))
    tx = max(-float(_EDITOR_W), min(float(_EDITOR_W), tx))
    ty = max(-float(_EDITOR_H), min(float(_EDITOR_H), ty))

    has_transform = (
        abs(tw - _EDITOR_W) > 1
        or abs(th - _EDITOR_H) > 1
        or abs(tx) > 1
        or abs(ty) > 1
    )

    if has_transform:
        target_w = max(16, int(round(tw * _PX_SCALE_X)))
        target_h = max(16, int(round(th * _PX_SCALE_Y)))
        off_x = int(round(tx * _PX_SCALE_X))
        off_y = int(round(ty * _PX_SCALE_Y))
        # Even dimensions for yuv420p
        if target_w % 2 == 1:
            target_w += 1
        if target_h % 2 == 1:
            target_h += 1
        vparts.append(
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=disable"
        )
    else:
        # No transform — scale to fit the canvas keeping aspect ratio.
        # The overlay below will still composite onto the black base.
        vparts.append(
            f"scale={_CANVAS_W}:{_CANVAS_H}:force_original_aspect_ratio=decrease"
        )
        # Ask ffmpeg to round to even dims so libx264 is happy
        vparts.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        target_w = 0  # signal "use overlay=(W-w)/2:(H-h)/2"
        target_h = 0
        off_x = 0
        off_y = 0

    if isinstance(video_transform, dict) and video_transform.get("flipH"):
        vparts.append("hflip")

    video_chain = ",".join(vparts)
    audio_chain = ",".join(aparts)
    info = {
        "has_transform": has_transform,
        "off_x": off_x,
        "off_y": off_y,
        "target_w": target_w,
        "target_h": target_h,
    }
    return video_chain, audio_chain, info


def export_user_video(video_path: str, export_config: Dict) -> str:
    """Render a user's export to a final 1080×1920 MP4.

    Consumes the JSONB shape written by the API/editor. Text and logo
    overlays are pre-rendered with Pillow (so we get full styling control)
    and then composited via FFmpeg.
    """
    export_id = export_config.get("export_id", "export")
    work = os.path.join(WORK_DIR, f"export_{export_id}")
    os.makedirs(work, exist_ok=True)
    output_path = os.path.join(work, f"{export_id}_final.mp4")

    video_trim = export_config.get("video_trim") or {}
    video_transform = export_config.get("video_transform") or {}
    headline_text = export_config.get("headline_text") or ""
    headline_style = export_config.get("headline_style") or {}
    subtitle_text = export_config.get("subtitle_text") or ""
    subtitle_style = export_config.get("subtitle_style") or {}
    logo_overrides = export_config.get("logo_overrides") or {}
    logo_src_path = export_config.get("logo_src_path")  # populated by exporter.py
    audio_config = export_config.get("audio_config") or {}
    custom_audio_path = export_config.get("custom_audio_path")

    # ── Pre-render text + logo overlays ───────────────────────────────
    headline_png = os.path.join(work, "headline.png")
    subtitle_png = os.path.join(work, "subtitle.png")
    logo_png = os.path.join(work, "logo.png")

    has_headline = _render_text_layer_png(headline_text, headline_style, headline_png)
    has_subtitle = _render_text_layer_png(subtitle_text, subtitle_style, subtitle_png)
    has_logo = _render_logo_layer_png(logo_src_path, logo_overrides, logo_png) if logo_src_path else False

    logger.info(
        "export %s overlays: headline=%s subtitle=%s logo=%s",
        export_id, has_headline, has_subtitle, has_logo,
    )

    # ── Build FFmpeg filter graph ─────────────────────────────────────
    video_chain, audio_chain, vt_info = _build_video_filter_chain(
        video_trim, video_transform
    )

    inputs: list[str] = ["-i", video_path]
    overlay_inputs: list[str] = []
    for png_flag, use in (
        (headline_png, has_headline),
        (subtitle_png, has_subtitle),
        (logo_png, has_logo),
    ):
        if use:
            inputs.extend(["-i", png_flag])
            overlay_inputs.append(png_flag)

    # STEP 1: transform the input video via the chain (scale/trim/flip)
    filter_parts = [f"[0:v]{video_chain}[vsrc]"]

    # STEP 2: composite the transformed video onto a 1080×1920 black
    # canvas. We use a synthetic `color` source (not pad) so layers
    # that extend past the canvas edges are clipped correctly — the
    # old approach used `pad` which rejects inputs larger than the
    # target dimensions with "Invalid argument".
    filter_parts.append(f"color=c=black:s={_CANVAS_W}x{_CANVAS_H}:d=1[base]")
    if vt_info["has_transform"]:
        ox = vt_info["off_x"]
        oy = vt_info["off_y"]
        filter_parts.append(f"[base][vsrc]overlay={ox}:{oy}[v0]")
    else:
        # Center the scaled video on the canvas
        filter_parts.append("[base][vsrc]overlay=(W-w)/2:(H-h)/2[v0]")

    # STEP 3: layer each overlay PNG on top. Each PNG is already
    # 1080×1920 with the element positioned correctly in transparent
    # space, so a plain overlay=0:0 is all we need.
    cur_label = "[v0]"
    for idx, _ in enumerate(overlay_inputs, start=1):
        next_label = f"[v{idx}]"
        filter_parts.append(f"{cur_label}[{idx}:v]overlay=0:0{next_label}")
        cur_label = next_label

    # Map the final video label. If there were no PNG overlays we
    # still need to rename [v0] to [outv] for the mapper.
    filter_parts[-1] = filter_parts[-1].replace(cur_label, "[outv]")
    cur_label = "[outv]"

    # ── Audio handling ────────────────────────────────────────────────
    try:
        orig_vol = float(audio_config.get("original_volume") if audio_config.get("original_volume") is not None else 100) / 100
    except Exception:
        orig_vol = 1.0
    muted = bool(audio_config.get("muted"))
    if muted:
        orig_vol = 0.0

    audio_input_idx = None
    custom_vol = 0.0
    if custom_audio_path and os.path.exists(custom_audio_path):
        try:
            custom_vol = float(audio_config.get("custom_volume") or 100) / 100
        except Exception:
            custom_vol = 1.0
        audio_input_idx = len(overlay_inputs) + 1  # after video (0) + overlays (1..N)
        inputs.extend(["-i", custom_audio_path])

    # Fade in/out: read editor flags and compute the target clip
    # duration so afade knows when to start the fade-out.
    fade_in = bool(audio_config.get("fade_in"))
    fade_out = bool(audio_config.get("fade_out"))
    fade_dur = 1.0  # seconds

    # Figure out the clip duration for fade_out. Prefer video_trim end,
    # otherwise fall back to None (let ffmpeg use stream duration).
    trim_start = 0.0
    trim_end = None
    if isinstance(video_trim, dict):
        try:
            trim_start = float(video_trim.get("start_seconds") or 0)
        except Exception:
            trim_start = 0.0
        try:
            raw_end = video_trim.get("end_seconds")
            trim_end = float(raw_end) if raw_end not in (None, "") else None
        except Exception:
            trim_end = None
    clip_dur = (trim_end - trim_start) if (trim_end is not None and trim_end > trim_start) else None

    def _with_fades(chain: str, include_fade_in: bool, include_fade_out: bool) -> str:
        parts: list[str] = [chain] if chain else []
        if include_fade_in and fade_in:
            parts.append(f"afade=t=in:st=0:d={fade_dur}")
        if include_fade_out and fade_out and clip_dur and clip_dur > fade_dur:
            st = max(0.0, clip_dur - fade_dur)
            parts.append(f"afade=t=out:st={st}:d={fade_dur}")
        return ",".join(p for p in parts if p)

    if audio_input_idx is not None:
        # Mix original video audio (possibly muted) with custom track.
        # Fades apply to the final mixed output so they respect both tracks.
        orig_chain = _with_fades(audio_chain, include_fade_in=False, include_fade_out=False)
        audio_filter = (
            f"[0:a]{(orig_chain + ',') if orig_chain else ''}volume={orig_vol}[orig];"
            f"[{audio_input_idx}:a]volume={custom_vol}[bg];"
            f"[orig][bg]amix=inputs=2:duration=first:dropout_transition=2[mixed]"
        )
        # Apply fades to the mixed stream
        fade_chain = _with_fades("", include_fade_in=True, include_fade_out=True)
        if fade_chain:
            audio_filter += f";[mixed]{fade_chain}[outa]"
        else:
            audio_filter = audio_filter.replace("[mixed]", "[outa]")
        filter_parts.append(audio_filter)
        map_audio = "[outa]"
    elif orig_vol != 1.0 or audio_chain or fade_in or fade_out:
        chain_with_vol = (audio_chain + "," if audio_chain else "") + f"volume={orig_vol}"
        full_chain = _with_fades(chain_with_vol, include_fade_in=True, include_fade_out=True)
        filter_parts.append(f"[0:a]{full_chain}[outa]")
        map_audio = "[outa]"
    else:
        map_audio = "0:a?"  # `?` makes the map optional if source has no audio

    filter_complex = ";".join(filter_parts)

    cmd = ["ffmpeg"]
    cmd.extend(inputs)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", cur_label,
        "-map", map_audio,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-r", "30",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-shortest",
        "-y",
        output_path,
    ])

    logger.info("Exporting video %s: %d inputs, %d overlays", export_id, len(inputs) // 2, len(overlay_inputs))
    logger.debug("FFmpeg command: %s", " ".join(cmd))

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=True)
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "")[-1000:]
        logger.error("Export render failed for %s: %s", export_id, stderr_tail)
        raise RuntimeError(f"Export render failed: {stderr_tail}") from exc

    if not os.path.exists(output_path):
        raise FileNotFoundError(f"Rendered export not found: {output_path}")

    file_size = os.path.getsize(output_path)
    logger.info("Export complete for %s: %s (%d bytes)", export_id, output_path, file_size)
    return output_path
