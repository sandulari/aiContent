#!/usr/bin/env python3
"""Seed theme pages and scrape viral reels for the business niche."""
import httpx
import json
import time
import uuid
import subprocess
import sys

KEY = "bffe6420fbmsh53054b9cd43710bp10895ajsn92e22b32523d"
HOST = "instagram-api-fast-reliable-data-scraper.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": KEY, "x-rapidapi-host": HOST}
NICHE_ID = "078a9feb-44a7-46de-9653-660abf5113a8"

PAGES = [
    ("stoicquotes365", "53784559442"),
    ("cashcoffers", "26533403431"),
    ("dubaifounders", "5584773103"),
    ("officialentrepreneurs", "34100907292"),
    ("billionairebymind", "17330203591"),
    ("billiontools_", "21510303047"),
    ("entrepreneurauthority", "12371448182"),
    ("bizfortunes", "63992428469"),
    ("businessandprofits", "76354113048"),
    ("acquireestate", "47866765246"),
    ("startupskill", "32434839897"),
    ("e.investingforbeginners", "6674661660"),
]

def db(sql):
    r = subprocess.run(
        ["docker", "compose", "-f", "/opt/shadowpages/infra/docker-compose.yml",
         "exec", "-T", "postgres", "psql", "-U", "vre_user", "-d", "vre", "-t", "-c", sql],
        capture_output=True, text=True
    )
    return r.stdout.strip()

def scrape_reels(pk, pages=3):
    all_reels = []
    max_id = ""
    for p in range(pages):
        params = {"user_id": pk}
        if max_id:
            params["max_id"] = max_id
        try:
            resp = httpx.get(f"https://{HOST}/reels", params=params, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                print(f"    Page {p}: HTTP {resp.status_code}")
                break
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            paging = data.get("data", {}).get("paging_info", {})
            for item in items:
                m = item.get("media", item)
                code = m.get("code", "")
                if not code:
                    continue
                views = int(m.get("play_count") or m.get("view_count") or 0)
                likes = int(m.get("like_count", 0))
                comments = int(m.get("comment_count", 0))
                taken = m.get("taken_at")
                cap = m.get("caption", {})
                caption = (cap.get("text", "") if isinstance(cap, dict) else str(cap or ""))[:300]
                thumb = ""
                iv = m.get("image_versions2", {})
                cands = iv.get("candidates", []) if isinstance(iv, dict) else []
                if cands:
                    thumb = cands[0].get("url", "")[:500]
                all_reels.append({
                    "code": code, "views": views, "likes": likes, "comments": comments,
                    "caption": caption, "thumb": thumb, "taken_at": taken,
                })
            if not paging.get("more_available"):
                break
            max_id = paging.get("max_id", "")
            if not max_id:
                break
            time.sleep(1)
        except Exception as e:
            print(f"    Page {p} error: {e}")
            break
    return all_reels

total = 0
for username, pk in PAGES:
    # Insert theme page
    tp_id = str(uuid.uuid4())
    db(f"INSERT INTO theme_pages (id, username, niche_id, is_active, evaluation_status, discovered_via, created_at) "
       f"VALUES ('{tp_id}', '{username}', '{NICHE_ID}', true, 'confirmed', 'manual_seed', NOW()) "
       f"ON CONFLICT (username) DO NOTHING")

    real_tp_id = db(f"SELECT id FROM theme_pages WHERE username = '{username}'").strip()

    # Scrape reels
    reels = scrape_reels(pk)

    # Insert reels
    inserted = 0
    for r in reels:
        rid = str(uuid.uuid4())
        caption = r["caption"].replace("'", "''")
        posted = f"to_timestamp({r['taken_at']})" if r["taken_at"] else "NULL"
        thumb = r["thumb"].replace("'", "''")
        sql = (
            f"INSERT INTO viral_reels (id, theme_page_id, ig_video_id, ig_url, thumbnail_url, "
            f"view_count, like_count, comment_count, caption, posted_at, scraped_at, "
            f"niche_id, status, created_at) VALUES ("
            f"'{rid}', '{real_tp_id}', '{r['code']}', "
            f"'https://www.instagram.com/reel/{r['code']}/', '{thumb}', "
            f"{r['views']}, {r['likes']}, {r['comments']}, '{caption}', "
            f"{posted}, NOW(), '{NICHE_ID}', 'discovered', NOW()) "
            f"ON CONFLICT (ig_video_id) DO UPDATE SET "
            f"view_count=EXCLUDED.view_count, like_count=EXCLUDED.like_count"
        )
        try:
            db(sql)
            inserted += 1
        except:
            pass

    total += inserted
    viral = sum(1 for r in reels if r["views"] >= 500000)
    print(f"@{username}: {len(reels)} scraped, {inserted} inserted, {viral} viral (500K+)")
    time.sleep(1)

print(f"\nTOTAL: {total} reels from {len(PAGES)} theme pages")
print(db("SELECT 'theme_pages' as t, COUNT(*) FROM theme_pages UNION ALL SELECT 'viral_reels', COUNT(*) FROM viral_reels UNION ALL SELECT 'reels_500k+', COUNT(*) FROM viral_reels WHERE view_count >= 500000"))
