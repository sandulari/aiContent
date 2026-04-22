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


async def _download_via_browser(url: str, output_path: str, timeout_ms: int = 60000) -> dict | None:
    """Launch headless browser, play video, download the stream WITHIN the browser context."""
    from playwright.async_api import async_playwright

    result = {"title": "", "duration": 0, "downloaded": False}
    video_chunks = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu", "--autoplay-policy=no-user-gesture-required"],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        # Set YouTube consent cookie to bypass the consent dialog
        await ctx.add_cookies([
            {"name": "SOCS", "value": "CAISHAgCEhJnd3NfMjAyNDA4MjgtMF9SQzIaAmVuIAEaBgiA_eSzBg", "domain": ".youtube.com", "path": "/"},
            {"name": "CONSENT", "value": "PENDING+987", "domain": ".youtube.com", "path": "/"},
        ])
        page = await ctx.new_page()

        # Capture video stream URLs (not bodies — YouTube uses range requests)
        video_stream_urls = []

        async def handle_response(response):
            try:
                u = response.url
                if "googlevideo.com" in u and "videoplayback" in u:
                    video_stream_urls.append(u)
                elif "tiktokcdn.com" in u and ".mp4" in u:
                    video_stream_urls.append(u)
                elif "v16-webapp" in u and ".mp4" in u:
                    video_stream_urls.append(u)
            except:
                pass

        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(2000)

            # Dismiss YouTube consent/cookie dialog if present
            if "youtube.com" in url:
                for selector in [
                    "button[aria-label*='Accept']",
                    "button[aria-label*='Reject']",
                    "button.yt-spec-button-shape-next--call-to-action",
                    "[aria-label*='consent'] button",
                    "form[action*='consent'] button",
                    "tp-yt-paper-dialog button.yt-spec-button-shape-next",
                ]:
                    try:
                        btn = page.locator(selector).first
                        if await btn.is_visible(timeout=1000):
                            await btn.click()
                            await page.wait_for_timeout(1500)
                            break
                    except:
                        continue

            result["title"] = await page.title()

            # Click play button
            if "youtube.com" in url:
                try:
                    play = page.locator("button.ytp-large-play-button")
                    if await play.is_visible(timeout=2000):
                        await play.click()
                except:
                    pass
                # Also try clicking the video element directly
                try:
                    video = page.locator("video").first
                    if await video.is_visible(timeout=1000):
                        await video.click()
                except:
                    pass

            # Wait for video to buffer
            await page.wait_for_timeout(10000)

            # Get duration
            try:
                dur = await page.evaluate("() => { const v = document.querySelector('video'); return v ? v.duration : 0; }")
                result["duration"] = float(dur) if dur else 0
            except:
                pass

            # Download the video INSIDE the browser using JavaScript fetch
            if video_stream_urls:
                stream_url = max(video_stream_urls, key=len)
                logger.info("Downloading stream inside browser: %s", stream_url[:80])

                # Use the browser's fetch to download (same session = no 403)
                video_base64 = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const resp = await fetch("{stream_url}", {{
                                headers: {{ "Range": "bytes=0-" }}
                            }});
                            const blob = await resp.blob();
                            const reader = new FileReader();
                            return new Promise((resolve) => {{
                                reader.onloadend = () => resolve(reader.result.split(',')[1]);
                                reader.readAsDataURL(blob);
                            }});
                        }} catch(e) {{
                            return null;
                        }}
                    }}
                """)

                if video_base64:
                    import base64
                    video_bytes = base64.b64decode(video_base64)
                    if len(video_bytes) > 50000:
                        with open(output_path, "wb") as f:
                            f.write(video_bytes)
                        result["downloaded"] = True
                        result["file_size"] = len(video_bytes)

        except Exception as e:
            logger.warning("Playwright navigation failed for %s: %s", url, e)
        finally:
            await browser.close()

    return result if result.get("downloaded") else None


def download_via_playwright(url: str, video_id: str) -> dict | None:
    """Download a video using Playwright headless browser.

    Intercepts the video stream response body directly inside the browser
    context — no separate HTTP download needed, bypasses YouTube's
    stream URL validation that returns 403 on external requests.
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    output_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")

    if os.path.exists(output_path) and os.path.getsize(output_path) > 50000:
        return {"file_path": output_path, "title": "", "duration": 0, "file_size": os.path.getsize(output_path)}

    logger.info("Playwright download starting for %s (%s)", video_id, url)

    result = asyncio.run(_download_via_browser(url, output_path))

    if not result or not result.get("downloaded"):
        logger.warning("Playwright download failed for %s", url)
        return None

    logger.info("Playwright download SUCCESS: %s (%d bytes)", output_path, result.get("file_size", 0))

    return {
        "file_path": output_path,
        "title": result.get("title", ""),
        "duration": result.get("duration", 0),
        "file_size": result.get("file_size", 0),
    }
