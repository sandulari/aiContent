"""
Discovery engine — functions for finding new theme page candidates.
Layer 1: Hashtag mining
Layer 2: Graph crawl (suggested accounts)
Layer 3: Same-content cross-referencing
"""
import logging
import random
import re
import time
from typing import List, Set

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
]


def _random_delay(min_s: float = 2.0, max_s: float = 6.0):
    time.sleep(random.uniform(min_s, max_s))


def discover_via_hashtags(hashtag: str) -> Set[str]:
    """
    Scrape top posts under a hashtag and extract account usernames.
    Uses instaloader as primary method.
    """
    candidates = set()
    try:
        import instaloader
        L = instaloader.Instaloader(
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            quiet=True,
            user_agent=random.choice(USER_AGENTS),
        )

        ht = instaloader.Hashtag.from_name(L.context, hashtag)
        count = 0
        for post in ht.get_top_posts():
            if count >= 30:
                break
            if post.owner_username:
                candidates.add(post.owner_username)
            count += 1
            _random_delay(1.0, 3.0)

    except Exception as e:
        logger.warning("Hashtag discovery via instaloader failed for #%s: %s", hashtag, e)
        # Fallback: try Playwright
        try:
            candidates = _hashtag_playwright_fallback(hashtag)
        except Exception as e2:
            logger.warning("Hashtag Playwright fallback also failed: %s", e2)

    logger.info("Hashtag #%s yielded %d candidates", hashtag, len(candidates))
    return candidates


def _hashtag_playwright_fallback(hashtag: str) -> Set[str]:
    """Playwright fallback for hashtag mining."""
    from playwright.sync_api import sync_playwright

    candidates = set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(user_agent=random.choice(USER_AGENTS))
        page = context.new_page()

        url = f"https://www.instagram.com/explore/tags/{hashtag}/"
        page.goto(url, wait_until="networkidle", timeout=30000)
        _random_delay(3.0, 5.0)

        # Scroll a few times to load content
        for _ in range(3):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            _random_delay(2.0, 4.0)

        # Extract links to posts, then we'd need to visit each
        links = page.evaluate("""
            () => {
                const anchors = document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]');
                return [...new Set([...anchors].map(a => a.href))].slice(0, 20);
            }
        """)

        for link in links[:15]:
            try:
                page.goto(link, wait_until="networkidle", timeout=15000)
                _random_delay(1.0, 3.0)
                username = page.evaluate("""
                    () => {
                        const el = document.querySelector('header a[href*="/"]');
                        if (el) {
                            const match = el.href.match(/instagram\\.com\\/([^/]+)/);
                            return match ? match[1] : null;
                        }
                        return null;
                    }
                """)
                if username and username not in ("explore", "reels", "p"):
                    candidates.add(username)
            except Exception:
                continue

        browser.close()

    return candidates


def discover_via_graph_crawl(username: str) -> Set[str]:
    """
    Visit a confirmed theme page's profile and extract 'Suggested Accounts'.
    Instagram shows these when you visit a profile.
    """
    candidates = set()
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=random.choice(USER_AGENTS))
            page = context.new_page()

            url = f"https://www.instagram.com/{username}/"
            page.goto(url, wait_until="networkidle", timeout=30000)
            _random_delay(3.0, 6.0)

            # Try to find and click the "Similar accounts" / suggested section
            # Instagram shows a "See All" or chevron for suggested accounts
            try:
                # Look for suggested accounts section
                suggested = page.evaluate("""
                    () => {
                        const links = document.querySelectorAll('a[href*="/"]');
                        const usernames = [];
                        links.forEach(a => {
                            const match = a.href.match(/instagram\\.com\\/([a-zA-Z0-9_.]+)\\/?$/);
                            if (match && match[1] !== '""" + username + """') {
                                usernames.push(match[1]);
                            }
                        });
                        // Filter out common non-username paths
                        const ignore = new Set(['explore', 'reels', 'stories', 'direct', 'accounts', 'p', 'reel', 'about', 'privacy', 'terms']);
                        return [...new Set(usernames.filter(u => !ignore.has(u) && u.length > 1))];
                    }
                """)
                candidates.update(suggested[:20])
            except Exception as e:
                logger.warning("Suggested accounts extraction failed for @%s: %s", username, e)

            browser.close()

    except Exception as e:
        logger.warning("Graph crawl failed for @%s: %s", username, e)

    logger.info("Graph crawl of @%s yielded %d candidates", username, len(candidates))
    return candidates


def discover_via_same_content(caption: str) -> Set[str]:
    """
    Search for other accounts posting similar content using caption keywords.
    Uses instaloader to search related hashtags from the caption.
    """
    candidates = set()
    if not caption:
        return candidates

    # Extract hashtags from caption
    hashtags = re.findall(r"#(\w+)", caption)
    if not hashtags:
        # Use first few words as keyword search
        words = caption.split()[:3]
        hashtags = ["".join(w.lower() for w in words if w.isalpha())]

    try:
        import instaloader
        L = instaloader.Instaloader(
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            quiet=True,
        )

        for tag in hashtags[:2]:
            try:
                ht = instaloader.Hashtag.from_name(L.context, tag)
                count = 0
                for post in ht.get_top_posts():
                    if count >= 10:
                        break
                    if post.owner_username:
                        candidates.add(post.owner_username)
                    count += 1
                    _random_delay(1.0, 2.0)
            except Exception:
                continue

    except Exception as e:
        logger.warning("Same-content discovery failed: %s", e)

    return candidates
