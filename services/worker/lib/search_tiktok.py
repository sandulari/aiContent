"""
TikTok search using Playwright to scrape TikTok web search results.
"""

import logging
import random
import re
import time
from typing import Dict, List

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


def _parse_tiktok_count(text: str) -> int:
    """Parse TikTok-style counts like '1.2M', '500K'."""
    if not text:
        return 0
    text = text.strip().replace(",", "")
    multipliers = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
    match = re.match(r"^([\d.]+)\s*([kmb])?$", text, re.IGNORECASE)
    if match:
        number = float(match.group(1))
        suffix = (match.group(2) or "").lower()
        return int(number * multipliers.get(suffix, 1))
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return 0


def search_tiktok(keywords: str, max_results: int = 10) -> List[Dict]:
    """
    Search TikTok for videos matching keywords using Playwright.

    Args:
        keywords: Search query string.
        max_results: Maximum results to return.

    Returns:
        List of dicts with: source_type, url, title, thumbnail_url, resolution, duration.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("Playwright not installed, cannot search TikTok")
        return []

    results: List[Dict] = []
    ua = random.choice(USER_AGENTS)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=ua,
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            search_url = f"https://www.tiktok.com/search/video?q={requests_quote(keywords)}"
            logger.info("TikTok search: %s", search_url)

            page.goto(search_url, wait_until="networkidle", timeout=30000)
            time.sleep(random.uniform(3.0, 6.0))

            # Scroll to load more results
            for _ in range(min(3, max_results // 5)):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(random.uniform(1.5, 3.5))

            # Extract video cards
            video_data = page.evaluate("""
                () => {
                    const cards = document.querySelectorAll('[data-e2e="search_top-item"], [class*="DivVideoCard"], [class*="search-card"]');
                    const results = [];
                    cards.forEach(card => {
                        const link = card.querySelector('a[href*="/@"]') || card.querySelector('a');
                        const desc = card.querySelector('[data-e2e="search-card-desc"], [class*="desc"], [class*="caption"]');
                        const thumb = card.querySelector('img');
                        const views = card.querySelector('[class*="play-count"], [class*="views"], [data-e2e="video-views"]');
                        if (link) {
                            results.push({
                                url: link.href,
                                title: desc ? desc.textContent.trim() : '',
                                thumbnail_url: thumb ? thumb.src : '',
                                views: views ? views.textContent.trim() : '0',
                            });
                        }
                    });
                    return results;
                }
            """)

            for item in video_data[:max_results]:
                url = item.get("url", "")
                if not url or "tiktok.com" not in url:
                    continue
                results.append({
                    "source_type": "tiktok",
                    "url": url,
                    "title": item.get("title", ""),
                    "thumbnail_url": item.get("thumbnail_url", ""),
                    "resolution": "1080x1920",
                    "duration": 0.0,
                })

            browser.close()

    except Exception as exc:
        logger.error("TikTok search failed: %s", exc)
        return []

    logger.info("TikTok search returned %d results for: %s", len(results), keywords)
    return results


def requests_quote(text: str) -> str:
    """URL-encode a string."""
    from urllib.parse import quote
    return quote(text)
