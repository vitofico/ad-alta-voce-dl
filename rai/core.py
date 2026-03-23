"""Core download logic shared by CLI and web UI."""

import os
import re
import time

import requests
from tqdm import tqdm

BASE_URL = "https://www.raiplaysound.it"
CATALOG_PATH = "/programmi/adaltavoce/audiolibri"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# In-memory catalog cache
_catalog_cache: dict = {"data": None, "ts": 0}
CACHE_TTL = 600  # 10 minutes


def make_session(proxy=None):
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": f"{BASE_URL}/",
        }
    )
    proxy = proxy or os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def fetch_json(url, session):
    """Fetch JSON metadata by appending .json to the URL."""
    json_url = url.rstrip("/")
    if not json_url.endswith(".json"):
        json_url += ".json"
    resp = session.get(json_url)
    resp.raise_for_status()
    return resp.json()


def extract_cards(data):
    """Find cards in the JSON response (data["cards"] or data["block"]["cards"])."""
    cards = data.get("cards")
    if cards:
        return cards
    block = data.get("block")
    if block and isinstance(block, dict):
        cards = block.get("cards")
        if cards:
            return cards
    return []


def get_audio_url(card):
    """Extract the relinker URL from a card.

    Prefers downloadable_audio.url (direct MP3) over audio.url (may be HLS).
    """
    # Prefer downloadable_audio (direct MP3 relinker, available on newer episodes)
    dl_audio = card.get("downloadable_audio")
    if dl_audio and isinstance(dl_audio, dict):
        url = dl_audio.get("url")
        if url:
            return url

    # Fall back to audio.url (works for older episodes, may be HLS for newer)
    audio = card.get("audio")
    if audio and isinstance(audio, dict):
        url = audio.get("url")
        if url:
            return url

    for key in ("content_url", "audio_url"):
        url = card.get(key)
        if url:
            return url
    return None


def resolve_relinker(url, session):
    """Follow the relinker redirect to get the direct MP3 URL."""
    resp = session.head(url, allow_redirects=True, timeout=30)
    final_url = resp.url
    if "relinker" in final_url:
        resp = session.get(url, allow_redirects=True, stream=True, timeout=30)
        final_url = resp.url
        resp.close()
    return final_url


def sanitize_filename(name):
    """Remove characters that are invalid in filenames."""
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = name.strip(". ")
    return name or "unknown"


def build_episode_filename(card, idx):
    """Build a filename like '001 - Title.mp3' from a card."""
    title = card.get("title", card.get("name", f"episode_{idx + 1}"))
    episode_num = card.get("episode_number") or card.get("episode") or str(idx + 1)
    try:
        episode_num = int(episode_num)
        return f"{episode_num:03d} - {sanitize_filename(title)}.mp3"
    except ValueError, TypeError:
        return f"{idx + 1:03d} - {sanitize_filename(title)}.mp3"


def download_file(url, path, session, progress_callback=None):
    """Download a file with optional progress callback. Skips if already exists.

    Args:
        progress_callback: Optional callable(bytes_so_far, total_bytes).
                          If None, uses tqdm for terminal progress.
    """
    if path.exists() and path.stat().st_size > 0:
        return "skipped"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")

    resp = session.get(url, stream=True, timeout=120)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    with open(tmp_path, "wb") as f:
        if progress_callback:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                progress_callback(downloaded, total)
        else:
            with tqdm(
                total=total,
                unit="B",
                unit_scale=True,
                desc=path.name[:40],
                leave=False,
            ) as pbar:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    pbar.update(len(chunk))

    tmp_path.rename(path)
    return "downloaded"


def fetch_catalog(session):
    """Fetch all audiobooks from the catalog, with caching."""
    now = time.time()
    if _catalog_cache["data"] and (now - _catalog_cache["ts"]) < CACHE_TTL:
        return _catalog_cache["data"]
    data = fetch_json(f"{BASE_URL}{CATALOG_PATH}", session)
    cards = extract_cards(data)
    _catalog_cache["data"] = cards
    _catalog_cache["ts"] = now
    return cards


def fetch_audiobook(path_or_url, session):
    """Fetch audiobook metadata. Accepts path like /audiolibri/agostino or full URL."""
    if path_or_url.startswith("http"):
        url = path_or_url
    else:
        url = f"{BASE_URL}{path_or_url}"
    return fetch_json(url, session)


def full_image_url(path):
    """Convert a relative image path to a full URL."""
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return f"{BASE_URL}{path}"


def extract_slug(weblink):
    """Extract slug from weblink like /audiolibri/agostino → agostino."""
    if not weblink:
        return ""
    return weblink.rstrip("/").rsplit("/", 1)[-1]


def first_genre(podcast_info):
    """Extract the first genre name from podcast_info."""
    genres = podcast_info.get("genres", [])
    if genres and isinstance(genres[0], dict):
        return genres[0].get("name", "Audiobook")
    if genres and isinstance(genres[0], str):
        return genres[0]
    return "Audiobook"


def extract_date(card):
    """Extract full date (YYYY-MM-DD) from a card's date_tracking or create_date.

    date_tracking is already ISO: "2014-07-10"
    create_date is DD-MM-YYYY: "10-07-2014"
    Falls back to year-only if parsing fails.
    """
    # date_tracking is already ISO
    dt = card.get("date_tracking", "")
    if dt and len(dt) == 10 and dt[4] == "-":
        return dt

    # create_date is DD-MM-YYYY
    cd = card.get("create_date", "")
    if cd and len(cd) == 10 and cd[2] == "-" and cd[5] == "-":
        day, month, year = cd.split("-")
        return f"{year}-{month}-{day}"

    # Fallback: extract just the year
    for key in ("date_tracking", "create_date"):
        date = card.get(key, "")
        if date:
            parts = date.split("-")
            for p in parts:
                if len(p) == 4 and p.isdigit():
                    return p
    return ""


def best_cover_url(podcast_info):
    """Get the best cover image URL from podcast_info."""
    images = podcast_info.get("images", {})
    for key in ("square", "cover", "landscape"):
        url = images.get(key)
        if url:
            return full_image_url(url)
    img = podcast_info.get("image", "")
    return full_image_url(img) if img else ""


def fetch_episodi(session):
    """Fetch the currently-airing episodes from the episodi feed."""
    data = fetch_json(f"{BASE_URL}/programmi/adaltavoce", session)
    return data


def parse_audiobook_from_episodi(cards):
    """Extract audiobook name from episodi cards' episode_title field.

    episode_title is like '1. Sorelle Materassi' → 'Sorelle Materassi'.
    """
    for card in cards:
        et = card.get("episode_title", card.get("toptitle", ""))
        if et:
            m = re.match(r"\d+\.\s*(.*)", et)
            if m:
                return m.group(1).strip()
    return None


def parse_description(description):
    """Parse 'Reader legge BookName Di Author' from episode description.

    Returns (reader, book_name, author) or (None, None, None).
    """
    if not description:
        return None, None, None
    m = re.match(r"(.+?)\s+legge\s+(.+?)\s+[Dd]i\s+(.+)", description)
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    return None, None, None


def find_catalog_card(title, session):
    """Find a catalog card matching the given audiobook title."""
    cards = fetch_catalog(session)
    for card in cards:
        if card.get("title", "").lower() == title.lower():
            return card
    return None
