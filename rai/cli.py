"""CLI entrypoint for downloading RAI Ad Alta Voce audiobooks."""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from rai import core, tagger


def process_episode(idx, card, session, output_dir, total, audiobook_meta=None):
    """Process a single episode: extract audio URL, resolve relinker, download, tag."""
    card_title = card.get("title", card.get("name", f"episode_{idx + 1}"))
    prefix = f"[{idx + 1}/{total}]"

    audio_url = core.get_audio_url(card)
    if not audio_url:
        print(f"{prefix} SKIP {card_title}: no audio URL")
        return card_title, False, "no audio URL"

    filename = core.build_episode_filename(card, idx)
    filepath = output_dir / filename

    if filepath.exists() and filepath.stat().st_size > 0:
        print(f"{prefix} SKIP {filename} (already exists)")
        return card_title, True, "skipped"

    # Resolve relinker
    try:
        direct_url = core.resolve_relinker(audio_url, session)
    except Exception as e:
        print(f"{prefix} FAIL {card_title}: resolving relinker: {e}")
        return card_title, False, str(e)

    # Download
    try:
        print(f"{prefix} Downloading {filename}")
        status = core.download_file(direct_url, filepath, session)
    except Exception as e:
        tmp = filepath.with_suffix(".tmp")
        if tmp.exists():
            tmp.unlink()
        print(f"{prefix} FAIL {card_title}: download error: {e}")
        return card_title, False, str(e)

    # Tag MP3 metadata
    if status == "downloaded" and audiobook_meta:
        try:
            tagger.tag_episode(filepath, card, audiobook_meta, idx, total, session)
        except Exception as e:
            print(f"{prefix} WARNING: tagging failed: {e}")

    return card_title, True, status


def main():
    parser = argparse.ArgumentParser(
        description="Download RAI Ad Alta Voce audiobooks",
        epilog="Example: python rai_download.py https://www.raiplaysound.it/audiolibri/agostino",
    )
    parser.add_argument("url", help="raiplaysound.it audiobook URL")
    parser.add_argument(
        "-o", "--output", default="/downloads", help="Output directory (default: /downloads)"
    )
    parser.add_argument(
        "-w", "--workers", type=int, default=3, help="Parallel downloads (default: 3)"
    )
    parser.add_argument("--proxy", help="HTTP proxy URL (not needed inside Docker)")
    parser.add_argument(
        "--dump-json", action="store_true", help="Dump raw JSON and exit (for debugging)"
    )
    args = parser.parse_args()

    session = core.make_session(args.proxy)

    # Verify Italian IP
    print("Checking IP geolocation...")
    try:
        ip_info = session.get("https://ipinfo.io/json", timeout=10).json()
        country = ip_info.get("country", "??")
        city = ip_info.get("city", "??")
        ip = ip_info.get("ip", "??")
        print(f"IP: {ip} — {city}, {country}")
        if country != "IT":
            print(
                f"WARNING: Country is {country}, not IT. "
                "Downloads will likely fail due to geo-restriction."
            )
    except Exception as e:
        print(f"Could not check IP: {e} (continuing anyway)")

    # Fetch audiobook metadata
    print(f"\nFetching metadata from {args.url}")
    try:
        data = core.fetch_json(args.url, session)
    except requests.HTTPError as e:
        print(f"Failed to fetch metadata: {e}")
        sys.exit(1)

    if args.dump_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        sys.exit(0)

    title = data.get("title") or data.get("name") or "audiobook"
    cards = core.extract_cards(data)

    if not cards:
        print("No episodes found in JSON response.")
        print(f"Top-level keys: {list(data.keys())}")
        print("Use --dump-json to inspect the full response.")
        sys.exit(1)

    print(f"Found {len(cards)} episodes for: {title}\n")

    # Prepare output directory
    output_dir = Path(args.output) / core.sanitize_filename(title)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save metadata
    metadata = {
        "title": title,
        "url": args.url,
        "description": data.get("podcast_info", {}).get("description", "")
        if isinstance(data.get("podcast_info"), dict)
        else "",
        "episode_count": len(cards),
        "episodes": [
            {
                "title": c.get("title", ""),
                "path_id": c.get("path_id", ""),
                "episode": c.get("episode", ""),
            }
            for c in cards
        ],
    }
    with open(output_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # Download episodes
    results = []
    total = len(cards)

    if args.workers <= 1:
        for idx, card in enumerate(cards):
            result = process_episode(idx, card, session, output_dir, total, data)
            results.append(result)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(process_episode, i, card, session, output_dir, total, data): i
                for i, card in enumerate(cards)
            }
            for future in as_completed(futures):
                results.append(future.result())

    # Summary
    downloaded = sum(1 for _, ok, s in results if ok and s == "downloaded")
    skipped = sum(1 for _, ok, s in results if ok and s == "skipped")
    failed = sum(1 for _, ok, _ in results if not ok)

    print(f"\nDone: {downloaded} downloaded, {skipped} skipped, {failed} failed")
    print(f"Output: {output_dir}")

    if failed:
        print("\nFailed episodes:")
        for title, ok, status in results:
            if not ok:
                print(f"  - {title}: {status}")
        sys.exit(1)
