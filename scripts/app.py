#!/usr/bin/env python3
import os, re, time, shutil
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs
from xml.etree import ElementTree as ET
from yt_dlp import YoutubeDL

TZ = "America/Detroit"
FEED_TITLE = "Majority Report – Fun Half"
FEED_LINK = "https://www.youtube.com/@samSeder"
FEED_DESCRIPTION = "Daily Fun Half links from MR Live"
FEED_URL = "https://cheeseb1234.github.io/fhrss/funhalf.xml"
OUTPUT_DIR = "public"
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "funhalf.xml")
CHANNEL_HANDLE = "@samSeder"
LIVE_TAB_URL = f"https://www.youtube.com/{CHANNEL_HANDLE}/videos?view=2&live_view=502&sort=dd"

ALLOWED_PREFIXES = (
    "https://www.youtube.com/live/",
    "https://youtube.com/live/",
    "https://youtu.be/",
)
FUN_HALF_PATTERN = re.compile(r"fun\s*[\-\u2010-\u2015\u2212]?\s*half", re.IGNORECASE)
YOUTUBE_URL_PATTERN = re.compile(r"https?://(?:www\.)?(?:youtube\.com/live/|youtu\.be/|youtube\.com/watch\?v=)[A-Za-z0-9_-]{6,}")

YDL_OPTS_LIST = {"quiet": True, "skip_download": True, "extract_flat": True, "nocheckcertificate": True}
YDL_OPTS_VIDEO = {
    "quiet": True,
    "skip_download": True,
    "extract_flat": False,
    "nocheckcertificate": True,
    "extractor_args": {"youtube": {"max_comments": ["50"], "player_client": ["android"]}},
}

def now_et():
    return datetime.now(ZoneInfo(TZ))

def is_weekday(dt):
    return dt.weekday() < 5

def previous_weekday(dt):
    d = dt
    while True:
        d -= timedelta(days=1)
        if is_weekday(d):
            return d

def clean_yt_url(url: str) -> str:
    u = url.split('?')[0].split('&')[0]
    if 'watch' in url and 'v=' in url:
        vid = parse_qs(urlparse(url).query).get('v', [''])[0]
        if vid:
            return f"https://youtube.com/live/{vid}"
    return u

def list_recent_live_entries():
    with YoutubeDL(YDL_OPTS_LIST) as ydl:
        info = ydl.extract_info(LIVE_TAB_URL, download=False) or {}
        return info.get('entries', [])

def pick_target_stream(entries, target_date):
    cands = []
    for e in entries:
        title = (e.get('title') or '').lower()
        if any(s in title for s in ["clip", "members", "premiere"]):
            continue
        duration = e.get('duration') or 0
        up = e.get('upload_date')
        et_date = None
        if up:
            dt_utc = datetime.strptime(up, "%Y%m%d").replace(tzinfo=ZoneInfo('UTC'))
            et_date = dt_utc.astimezone(ZoneInfo(TZ)).date()
        cands.append({"id": e.get('id'), "url": e.get('url') or e.get('webpage_url'), "title": e.get('title'), "duration": duration, "et_date": et_date})
    same = [c for c in cands if c['et_date'] == target_date.date()]
    if same:
        return max(same, key=lambda c: c['duration'] or 0)
    prior = [c for c in cands if c['et_date'] and c['et_date'] <= target_date.date()]
    if prior:
        prior.sort(key=lambda c: (c['et_date'], c['duration'] or 0), reverse=True)
        return prior[0]
    return None

def extract_info(video_url):
    with YoutubeDL(YDL_OPTS_VIDEO) as ydl:
        return ydl.extract_info(video_url, download=False)

def extract_funhalf_from_text(text):
    if not text:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if FUN_HALF_PATTERN.search(line):
            for u in YOUTUBE_URL_PATTERN.findall(line):
                cu = clean_yt_url(u)
                if cu.startswith(ALLOWED_PREFIXES):
                    return cu
    return None

def find_funhalf_url_for_video(video_url):
    info = extract_info(video_url) or {}
    desc = info.get('description') or ''
    url = extract_funhalf_from_text(desc)
    if url:
        return url
    comments = info.get('comments') or []
    pinned = next((c for c in comments if c.get('pinned')), None)
    if pinned:
        url = extract_funhalf_from_text(pinned.get('text') or '')
        if url:
            return url
    for c in comments[:50]:
        url = extract_funhalf_from_text(c.get('text') or '')
        if url:
            return url
    return None

# RSS helpers
RSS_NS = "http://www.w3.org/2005/Atom"

def ensure_feed_exists(path):
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    root = ET.Element('rss', version='2.0')
    channel = ET.SubElement(root, 'channel')
    ET.SubElement(channel, 'title').text = FEED_TITLE
    ET.SubElement(channel, 'link').text = FEED_LINK
    ET.SubElement(channel, 'description').text = FEED_DESCRIPTION
    atom_link = ET.SubElement(channel, '{%s}link' % RSS_NS)
    atom_link.set('href', FEED_URL)
    atom_link.set('rel', 'self')
    atom_link.set('type', 'application/rss+xml')
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)

def read_existing_guids(path):
    if not os.path.exists(path):
        return set()
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        guids = set()
        for item in root.findall('./channel/item'):
            guid = (item.findtext('guid') or item.findtext('link') or '').strip()
            if guid:
                guids.add(guid)
        return guids
    except ET.ParseError:
        backup = f"{path}.bak-{int(time.time())}"
        shutil.copy2(path, backup)
        os.remove(path)
        ensure_feed_exists(path)
        return set()

def append_item_to_feed(path, title, link, pub_dt_et):
    ensure_feed_exists(path)
    tree = ET.parse(path)
    root = tree.getroot()
    channel = root.find('channel')
    existing = read_existing_guids(path)
    guid = link
    if guid in existing:
        return False
    item = ET.Element('item')
    ET.SubElement(item, 'title').text = title
    ET.SubElement(item, 'link').text = link
    ET.SubElement(item, 'guid').text = guid
    ET.SubElement(item, 'pubDate').text = pub_dt_et.strftime('%a, %d %b %Y %H:%M:%S %Z')
    items = channel.findall('item')
    if items:
        channel.insert(list(channel).index(items[0]), item)
    else:
        channel.append(item)
    tree.write(path, encoding='utf-8', xml_declaration=True)
    return True

def main():
    now = now_et()
    target = now if is_weekday(now) else previous_weekday(now)

    # Always ensure the output dir and feed file exist so Pages can publish
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ensure_feed_exists(OUTPUT_PATH)
    entries = list_recent_live_entries()
    chosen = pick_target_stream(entries, target)
    if not chosen:
        return 0
    video_url = chosen.get('url') or f"https://www.youtube.com/watch?v={chosen.get('id')}"
    url = find_funhalf_url_for_video(video_url)
    if not url and (now.hour < 12 or (now.hour == 12 and now.minute < 25)):
        # Early run – exit quietly; retry job will handle it
        return 0
    if not url:
        prev = previous_weekday(target)
        prev_chosen = pick_target_stream(entries, prev)
        if prev_chosen:
            prev_url = prev_chosen.get('url') or f"https://www.youtube.com/watch?v={prev_chosen.get('id')}"
            url = find_funhalf_url_for_video(prev_url)
            if url:
                title = f"Fun Half – {prev.date()} (from previous weekday’s live)"
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                append_item_to_feed(OUTPUT_PATH, title, url, now)
                return 0
        return 0
    title = f"Fun Half – {target.date()}"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    append_item_to_feed(OUTPUT_PATH, title, url, now)
    return 0

if __name__ == "__main__":

    raise SystemExit(main())
