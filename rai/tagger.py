"""ID3 metadata tagging for downloaded MP3 files."""

from pathlib import Path

from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TRCK, ID3NoHeaderError

from rai import core

# Module-level cover art cache: {url: bytes}
_cover_cache: dict[str, bytes] = {}


def tag_episode(filepath, card, audiobook_data, idx, total, session):
    """Tag an MP3 file with metadata from the RAI API.

    Args:
        filepath: Path to the MP3 file.
        card: Episode card dict from the API.
        audiobook_data: Full audiobook JSON (contains podcast_info).
        idx: 0-based episode index.
        total: Total number of episodes.
        session: requests.Session for downloading cover art.
    """
    podcast_info = audiobook_data.get("podcast_info", {})
    if not isinstance(podcast_info, dict):
        podcast_info = {}

    episode_num = card.get("episode_number") or card.get("episode") or (idx + 1)
    try:
        episode_num = int(episode_num)
    except ValueError, TypeError:
        episode_num = idx + 1

    tag_mp3(
        filepath=Path(filepath),
        title=card.get("title", ""),
        artist=podcast_info.get("author", ""),
        album=audiobook_data.get("title", ""),
        track_number=episode_num,
        total_tracks=total,
        genre=core.first_genre(podcast_info),
        year=core.extract_date(card),
        cover_url=core.best_cover_url(podcast_info),
        session=session,
    )


def tag_mp3(
    filepath,
    title="",
    artist="",
    album="",
    track_number=1,
    total_tracks=1,
    genre="",
    year="",
    cover_url="",
    session=None,
):
    """Write ID3v2.4 tags to an MP3 file."""
    try:
        tags = ID3(filepath)
    except ID3NoHeaderError:
        tags = ID3()

    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=_clean_author(artist)))
    tags.add(TALB(encoding=3, text=album))
    tags.add(TRCK(encoding=3, text=f"{track_number}/{total_tracks}"))

    if genre:
        tags.add(TCON(encoding=3, text=genre))
    if year:
        tags.add(TDRC(encoding=3, text=year))

    if cover_url and session:
        cover_data = _fetch_cover(cover_url, session)
        if cover_data:
            tags.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,  # Cover (front)
                    desc="Cover",
                    data=cover_data,
                )
            )

    tags.save(filepath, v2_version=4)


def _clean_author(author):
    """Clean author string. RAI often prefixes with 'Di '."""
    if not author:
        return ""
    if author.lower().startswith("di "):
        return author[3:]
    return author


def _fetch_cover(url, session):
    """Download cover image, with caching. Returns raw bytes or None."""
    if url in _cover_cache:
        return _cover_cache[url]
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        if len(resp.content) < 100:
            return None
        _cover_cache[url] = resp.content
        return resp.content
    except Exception:
        return None
