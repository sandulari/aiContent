"""
Instagram scraping with instaloader (primary) and Playwright (fallback).
Anti-detection: random UA rotation, random delays, cookie support.
"""

import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

COOKIE_PATH = os.environ.get("INSTAGRAM_COOKIE_PATH", "/tmp/ig_cookies.json")


@dataclass
class ScrapedVideo:
    video_id: str
    url: str
    thumbnail_url: str
    view_count: int
    like_count: int
    comment_count: int
    duration_seconds: float
    caption: str
    posted_at: Optional[str]  # ISO format or None
    resolution: str


def _parse_count(text: str) -> int:
    """
    Parse human-readable counts like '1.2M', '500K', '12.5k', '3,400'.

    Returns integer count.
    """
    if not text:
        return 0
    text = str(text).strip().replace(",", "").replace(" ", "")
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


def _random_delay(min_s: float = 2.0, max_s: float = 8.0):
    """Sleep for a random duration between min_s and max_s seconds."""
    delay = random.uniform(min_s, max_s)
    logger.debug("Anti-detection delay: %.1fs", delay)
    time.sleep(delay)


def _scrape_with_instaloader(username: str, max_posts: int) -> List[ScrapedVideo]:
    """Layer 1: Use instaloader to scrape profile reels."""
    import instaloader

    loader = instaloader.Instaloader(
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
        user_agent=random.choice(USER_AGENTS),
    )

    # Load session cookies if available
    ig_user = os.environ.get("INSTAGRAM_USERNAME")
    ig_pass = os.environ.get("INSTAGRAM_PASSWORD")
    if ig_user and ig_pass:
        try:
            loader.login(ig_user, ig_pass)
            logger.info("Logged into Instagram as %s", ig_user)
        except Exception as exc:
            logger.warning("Instagram login failed: %s", exc)

    profile = instaloader.Profile.from_username(loader.context, username)
    videos: List[ScrapedVideo] = []
    count = 0

    for post in profile.get_posts():
        if count >= max_posts:
            break
        if not post.is_video:
            continue

        _random_delay(1.0, 3.0)

        videos.append(ScrapedVideo(
            video_id=post.shortcode,
            url=f"https://www.instagram.com/reel/{post.shortcode}/",
            thumbnail_url=post.url or "",
            view_count=post.video_view_count or 0,
            like_count=post.likes or 0,
            comment_count=post.comments or 0,
            duration_seconds=post.video_duration or 0.0,
            caption=post.caption or "",
            posted_at=post.date_utc.isoformat() if post.date_utc else None,
            resolution="",
        ))
        count += 1

    logger.info("Instaloader scraped %d videos from @%s", len(videos), username)
    return videos


def _scrape_with_playwright(username: str, max_posts: int) -> List[ScrapedVideo]:
    """Layer 2: Playwright fallback for scraping Instagram profile."""
    from playwright.sync_api import sync_playwright

    videos: List[ScrapedVideo] = []
    ua = random.choice(USER_AGENTS)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(user_agent=ua, viewport={"width": 1280, "height": 900})

        # Load cookies if available
        if os.path.exists(COOKIE_PATH):
            try:
                with open(COOKIE_PATH, "r") as f:
                    cookies = json.load(f)
                context.add_cookies(cookies)
                logger.info("Loaded Instagram cookies from %s", COOKIE_PATH)
            except Exception as exc:
                logger.warning("Failed to load cookies: %s", exc)

        page = context.new_page()
        profile_url = f"https://www.instagram.com/{username}/reels/"
        logger.info("Playwright navigating to %s", profile_url)
        page.goto(profile_url, wait_until="networkidle", timeout=30000)

        _random_delay(3.0, 6.0)

        # Scroll to load posts
        scroll_count = 0
        max_scrolls = max(3, max_posts // 10)
        while scroll_count < max_scrolls:
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            _random_delay(2.0, 5.0)
            scroll_count += 1

        # Extract reel links
        reel_links = page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href*="/reel/"]');
                return [...new Set([...links].map(a => a.href))];
            }
        """)

        for link in reel_links[:max_posts]:
            _random_delay(2.0, 6.0)
            try:
                shortcode_match = re.search(r"/reel/([^/]+)", link)
                if not shortcode_match:
                    continue
                shortcode = shortcode_match.group(1)

                page.goto(link, wait_until="networkidle", timeout=20000)
                _random_delay(1.0, 3.0)

                # Try to extract metadata from the page
                meta = page.evaluate("""
                    () => {
                        const getText = sel => {
                            const el = document.querySelector(sel);
                            return el ? el.textContent.trim() : '';
                        };
                        // Attempt to get view/like counts from meta or visible elements
                        const viewEl = document.querySelector('[aria-label*="view"], [aria-label*="play"]');
                        const likeEl = document.querySelector('[aria-label*="like"]');
                        const commentEl = document.querySelector('[aria-label*="comment"]');
                        const captionEl = document.querySelector('h1') || document.querySelector('[class*="Caption"]');
                        const timeEl = document.querySelector('time');
                        return {
                            views: viewEl ? viewEl.getAttribute('aria-label') || viewEl.textContent : '0',
                            likes: likeEl ? likeEl.getAttribute('aria-label') || likeEl.textContent : '0',
                            comments: commentEl ? commentEl.getAttribute('aria-label') || commentEl.textContent : '0',
                            caption: captionEl ? captionEl.textContent : '',
                            posted_at: timeEl ? timeEl.getAttribute('datetime') || '' : '',
                        };
                    }
                """)

                videos.append(ScrapedVideo(
                    video_id=shortcode,
                    url=link,
                    thumbnail_url="",
                    view_count=_parse_count(re.sub(r"[^\d.kKmMbB,]", "", meta.get("views", "0"))),
                    like_count=_parse_count(re.sub(r"[^\d.kKmMbB,]", "", meta.get("likes", "0"))),
                    comment_count=_parse_count(re.sub(r"[^\d.kKmMbB,]", "", meta.get("comments", "0"))),
                    duration_seconds=0.0,
                    caption=meta.get("caption", ""),
                    posted_at=meta.get("posted_at") or None,
                    resolution="",
                ))
            except Exception as exc:
                logger.warning("Failed to scrape reel %s: %s", link, exc)
                continue

        # Save cookies for next run
        try:
            cookies = context.cookies()
            os.makedirs(os.path.dirname(COOKIE_PATH) or "/tmp", exist_ok=True)
            with open(COOKIE_PATH, "w") as f:
                json.dump(cookies, f)
        except Exception as exc:
            logger.warning("Failed to save cookies: %s", exc)

        browser.close()

    logger.info("Playwright scraped %d videos from @%s", len(videos), username)
    return videos


def scrape_profile(username: str, max_posts: int = 50) -> List[ScrapedVideo]:
    """
    Scrape Instagram profile for video reels.

    Layer 1: instaloader (fast, API-based).
    Layer 2: Playwright fallback (browser-based).

    Returns list of ScrapedVideo dataclass instances.
    """
    # Layer 1: instaloader
    try:
        logger.info("Attempting instaloader scrape for @%s", username)
        videos = _scrape_with_instaloader(username, max_posts)
        if videos:
            return videos
        logger.warning("Instaloader returned 0 videos, falling back to Playwright")
    except Exception as exc:
        logger.warning("Instaloader failed for @%s: %s — falling back to Playwright", username, exc)

    # Layer 2: Playwright
    try:
        logger.info("Attempting Playwright scrape for @%s", username)
        return _scrape_with_playwright(username, max_posts)
    except Exception as exc:
        logger.error("Both scraping layers failed for @%s: %s", username, exc)
        return []
