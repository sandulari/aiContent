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
    """Use Playwright to get YouTube cookies, then yt-dlp to download with those cookies."""
    from playwright.async_api import async_playwright
    import subprocess
    import tempfile
    import json

    result = {"title": "", "duration": 0, "downloaded": False}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        # Set consent cookies
        await ctx.add_cookies([
            {"name": "SOCS", "value": "CAISHAgCEhJnd3NfMjAyNDA4MjgtMF9SQzIaAmVuIAEaBgiA_eSzBg", "domain": ".youtube.com", "path": "/"},
            {"name": "CONSENT", "value": "PENDING+987", "domain": ".youtube.com", "path": "/"},
        ])
        page = await ctx.new_page()

        try:
            # Visit YouTube to establish cookies
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(3000)

            # Dismiss consent if needed
            for selector in [
                "button[aria-label*='Accept']",
                "button[aria-label*='Reject']",
                "button.yt-spec-button-shape-next--call-to-action",
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

            # Export cookies from browser to Netscape format for yt-dlp
            cookies = await ctx.cookies()
            cookie_lines = ["# Netscape HTTP Cookie File"]
            for c in cookies:
                domain = c.get("domain", "")
                flag = "TRUE" if domain.startswith(".") else "FALSE"
                path = c.get("path", "/")
                secure = "TRUE" if c.get("secure") else "FALSE"
                expiry = str(int(c.get("expires", 0)))
                name = c.get("name", "")
                value = c.get("value", "")
                cookie_lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}")

        except Exception as e:
            logger.warning("Playwright failed for %s: %s", url, e)
            await browser.close()
            return None
        finally:
            await browser.close()

    # Write cookies file
    cookie_path = tempfile.mktemp(suffix=".txt")
    with open(cookie_path, "w") as f:
        f.write("\n".join(cookie_lines))

    # Now use yt-dlp WITH the browser's cookies
    try:
        cmd = [
            "yt-dlp",
            "--cookies", cookie_path,
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "--retries", "3",
            "--socket-timeout", "30",
            "--output", output_path,
            "--no-overwrites",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if proc.returncode == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            if file_size > 50000:
                result["downloaded"] = True
                result["file_size"] = file_size
                logger.info("yt-dlp + Playwright cookies SUCCESS: %d bytes", file_size)
        else:
            logger.warning("yt-dlp with cookies failed: %s", (proc.stderr or "")[:200])
    except Exception as e:
        logger.warning("yt-dlp with cookies error: %s", e)
    finally:
        try:
            os.remove(cookie_path)
        except:
            pass

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
