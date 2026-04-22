"""
Playwright-based video downloader — bypasses YouTube/TikTok bot detection.

Uses a real headless browser to capture video stream URLs, then downloads
the stream directly. YouTube can't block this because it's indistinguishable
from a real user watching a video.
"""

import asyncio
import logging
import os
import httpx

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.environ.get("VRE_DOWNLOAD_DIR", "/tmp/vre_downloads")


async def _capture_video_stream(url: str, timeout_ms: int = 30000) -> dict | None:
    """Launch headless browser, navigate to URL, capture video stream."""
    from playwright.async_api import async_playwright

    result = {"title": "", "video_url": "", "duration": 0}
    video_urls = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()

        # Capture video stream responses
        def on_response(resp):
            u = resp.url
            if "googlevideo.com" in u and "videoplayback" in u:
                video_urls.append(u)
            elif "tiktokcdn.com" in u and ("video" in u or ".mp4" in u):
                video_urls.append(u)
            elif "v16-webapp" in u and ".mp4" in u:
                video_urls.append(u)

        page.on("response", on_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(5000)

            # Try to click play on YouTube
            if "youtube.com" in url:
                try:
                    play = page.locator("button.ytp-large-play-button")
                    if await play.is_visible(timeout=2000):
                        await play.click()
                        await page.wait_for_timeout(3000)
                except:
                    pass

            result["title"] = await page.title()

            # Get duration from YouTube
            if "youtube.com" in url:
                try:
                    dur = await page.evaluate("""
                        () => {
                            const v = document.querySelector('video');
                            return v ? v.duration : 0;
                        }
                    """)
                    result["duration"] = float(dur) if dur else 0
                except:
                    pass

        except Exception as e:
            logger.warning("Playwright navigation failed for %s: %s", url, e)
        finally:
            await browser.close()

    if video_urls:
        # Pick the best quality stream (longest URL usually has most params = highest quality)
        result["video_url"] = max(video_urls, key=len)
        return result

    return None


def download_via_playwright(url: str, video_id: str) -> dict | None:
    """Download a video using Playwright to bypass bot detection.

    Returns dict with file_path, title, duration on success, None on failure.
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    output_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")

    if os.path.exists(output_path):
        return {"file_path": output_path, "title": "", "duration": 0}

    logger.info("Playwright download starting for %s (%s)", video_id, url)

    # Capture the video stream URL
    result = asyncio.run(_capture_video_stream(url))

    if not result or not result.get("video_url"):
        logger.warning("Playwright failed to capture video stream for %s", url)
        return None

    # Download the video stream directly
    stream_url = result["video_url"]
    logger.info("Downloading video stream (%s) for %s", stream_url[:80], video_id)

    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            with client.stream("GET", stream_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://www.youtube.com/",
            }) as resp:
                if resp.status_code != 200:
                    logger.warning("Stream download failed: HTTP %d", resp.status_code)
                    return None

                with open(output_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)

        file_size = os.path.getsize(output_path)
        logger.info("Playwright download complete: %s (%d bytes)", output_path, file_size)

        if file_size < 10000:
            # Too small — probably an error page
            os.remove(output_path)
            return None

        return {
            "file_path": output_path,
            "title": result.get("title", ""),
            "duration": result.get("duration", 0),
            "file_size": file_size,
        }

    except Exception as e:
        logger.error("Stream download failed for %s: %s", video_id, e)
        if os.path.exists(output_path):
            os.remove(output_path)
        return None
