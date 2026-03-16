# Catalog Audiobook Download Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make catalog audiobooks clickable and downloadable in the web UI.

**Architecture:** Add two new Flask routes (`/audiobook/<slug>` for detail page, `/api/download/<slug>` for SSE download) to `app.py`, update existing download guards to be global, and make home page catalog cards link to detail pages. Download loop follows poller's existing pattern.

**Tech Stack:** Flask, requests, mutagen (existing stack — no new dependencies)

**Spec:** `docs/superpowers/specs/2026-03-16-catalog-download-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `rai/web/app.py` | Modify | Add `/audiobook/<slug>` route, `/api/download/<slug>` SSE route, `_is_any_download_active()` helper, update existing download guards |
| `rai/poller.py` | Modify | Add optional `source` parameter to `_save_metadata()` (default `"episodi"`) |
| `rai/web/templates/home.html` | Modify | Wrap catalog cards in `<a>` links |

No new files. No changes to `core.py`, `cli.py`, `tagger.py`, `audiobook.html`.

---

## Chunk 1: Global Download Guard

### Task 1: Add `_is_any_download_active()` helper

**Files:**
- Modify: `rai/web/app.py:22` (after `_active_downloads` declaration)

- [ ] **Step 1: Add the helper function**

In `rai/web/app.py`, after line 22 (`_active_downloads: dict[str, threading.Thread] = {}`), add:

```python

def _is_any_download_active():
    """Check if any download thread is currently running."""
    return any(t.is_alive() for t in _active_downloads.values())
```

- [ ] **Step 2: Update `/api/download/current` guard**

In `rai/web/app.py`, replace line 91:

```python
        if "current" in _active_downloads and _active_downloads["current"].is_alive():
```

with:

```python
        if _is_any_download_active():
```

- [ ] **Step 3: Update `/api/poll` guard**

In `rai/web/app.py`, replace line 130:

```python
        if "current" in _active_downloads and _active_downloads["current"].is_alive():
```

with:

```python
        if _is_any_download_active():
```

- [ ] **Step 4: Update home page `downloading` status check**

In `rai/web/app.py`, the `_fetch_current_audiobook()` function at line 218:

```python
        downloading = "current" in _active_downloads and _active_downloads["current"].is_alive()
```

Replace with:

```python
        downloading = _is_any_download_active()
```

- [ ] **Step 5: Add `source` parameter to `poller._save_metadata()`**

In `rai/poller.py`, replace line 54-55:

```python
def _save_metadata(
    output_dir, title, author, reader, description, cover_url, episodes, completed, session
):
```

with:

```python
def _save_metadata(
    output_dir, title, author, reader, description, cover_url, episodes, completed, session,
    source="episodi",
):
```

And replace line 67:

```python
        "source": "episodi",
```

with:

```python
        "source": source,
```

This is backward-compatible — existing callers (the poller itself) don't pass `source` and get the default `"episodi"`. The new catalog download route will pass `source="catalog"`.

- [ ] **Step 6: Verify the app still starts**

Run: `cd /Users/vito/repos/ad-alta-voce-dl && python -c "from rai.web.app import create_app; app = create_app(); print('OK')"`

Expected: `OK` (no import/syntax errors)

- [ ] **Step 7: Commit**

```bash
git add rai/web/app.py rai/poller.py
git commit -m "refactor(web): add global download guard and source param to _save_metadata"
```

---

## Chunk 2: Audiobook Detail Page Route

### Task 2: Add `GET /audiobook/<slug>` route

**Files:**
- Modify: `rai/web/app.py` (add new route inside `create_app()`, before `return app`)

- [ ] **Step 1: Add the `import time` statement**

In `rai/web/app.py`, add `import time` to the imports. Replace line 6:

```python
import threading
```

with:

```python
import threading
import time
```

- [ ] **Step 2: Add the `import tagger` statement**

In `rai/web/app.py` line 12, change:

```python
from rai import core, poller
```

to:

```python
from rai import core, poller, tagger
```

- [ ] **Step 3: Add the audiobook detail route**

In `rai/web/app.py`, before the `return app` statement (line 182), add:

```python
    @app.route("/audiobook/<slug>")
    def audiobook_detail(slug):
        """Detail page for a catalog audiobook."""
        try:
            data = core.fetch_audiobook(f"/audiolibri/{slug}", _session)
        except Exception:
            return "Audiobook not found", 404

        cards = core.extract_cards(data)
        if not cards:
            return "No episodes found", 404

        title = data.get("title") or data.get("name") or slug

        # Parse author from first episode description
        desc = cards[0].get("description", "")
        reader_name, _, author_name = core.parse_description(desc)

        # Fallback author from podcast_info
        if not author_name:
            pi = data.get("podcast_info", {})
            if isinstance(pi, dict):
                author_name = pi.get("author", "")

        # Cover from catalog card
        catalog_card = core.find_catalog_card(title, _session)
        cover_url = ""
        if catalog_card:
            images = catalog_card.get("images", {})
            cover_url = images.get("square") or images.get("cover") or catalog_card.get("image", "")
            cover_url = core.full_image_url(cover_url)

        # Book description from catalog or podcast_info
        book_description = ""
        if catalog_card:
            book_description = catalog_card.get("description", "")
        if not book_description:
            pi = data.get("podcast_info", {})
            if isinstance(pi, dict):
                book_description = pi.get("description", "")

        # Check download status per episode
        author_clean = core.sanitize_filename(author_name) if author_name else "Ad Alta Voce"
        title_clean = core.sanitize_filename(title)
        output_dir = DOWNLOADS_DIR / author_clean / title_clean

        sorted_cards = sorted(cards, key=lambda c: int(c.get("episode", 0) or 0))
        for i, ep in enumerate(sorted_cards):
            filename = core.build_episode_filename(ep, i)
            ep["_downloaded"] = (output_dir / filename).exists()
            ep["_duration"] = ep.get("literal_duration", ep.get("duration_small_format", ""))

        downloaded_count = sum(1 for e in sorted_cards if e.get("_downloaded"))
        downloading = _is_any_download_active()

        return render_template(
            "audiobook.html",
            title=title,
            author=author_name or "",
            description=book_description,
            cover_url=cover_url,
            slug=slug,
            episodes=sorted_cards,
            total=len(sorted_cards),
            downloaded_count=downloaded_count,
            downloading=downloading,
        )

```

- [ ] **Step 4: Verify the app still starts**

Run: `cd /Users/vito/repos/ad-alta-voce-dl && python -c "from rai.web.app import create_app; app = create_app(); print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add rai/web/app.py
git commit -m "feat(web): add /audiobook/<slug> detail page route"
```

---

## Chunk 3: SSE Download Route

### Task 3: Add `GET /api/download/<slug>` SSE endpoint

**Files:**
- Modify: `rai/web/app.py` (add new route inside `create_app()`, after the audiobook_detail route)

- [ ] **Step 1: Add the download route**

In `rai/web/app.py`, after the `audiobook_detail` route (and before `return app`), add:

```python
    @app.route("/api/download/<slug>")
    def download_audiobook(slug):
        """Stream download of a catalog audiobook via SSE."""
        if _is_any_download_active():
            return Response("Download already in progress", status=409)

        # Fetch audiobook metadata
        try:
            data = core.fetch_audiobook(f"/audiolibri/{slug}", _session)
        except Exception:
            return Response("Audiobook not found", status=404)

        cards = core.extract_cards(data)
        if not cards:
            return Response("No episodes found", status=404)

        title = data.get("title") or data.get("name") or slug

        # Parse author
        desc = cards[0].get("description", "")
        reader_name, _, author_name = core.parse_description(desc)
        if not author_name:
            pi = data.get("podcast_info", {})
            if isinstance(pi, dict):
                author_name = pi.get("author", "")

        # Cover URL
        catalog_card = core.find_catalog_card(title, _session)
        cover_url = ""
        if catalog_card:
            images = catalog_card.get("images", {})
            cover_url = images.get("square") or images.get("cover") or catalog_card.get("image", "")

        author_clean = core.sanitize_filename(author_name) if author_name else "Ad Alta Voce"
        title_clean = core.sanitize_filename(title)
        output_dir = DOWNLOADS_DIR / author_clean / title_clean

        q: Queue = Queue()
        dl_session = core.make_session()
        sorted_cards = sorted(cards, key=lambda c: int(c.get("episode", 0) or 0))

        def do_download():
            total = len(sorted_cards)
            episode_meta_list = []
            try:
                output_dir.mkdir(parents=True, exist_ok=True)

                for idx, card in enumerate(sorted_cards):
                    ep_title = card.get("title", card.get("name", f"episode_{idx + 1}"))
                    ep_num = idx + 1
                    filename = core.build_episode_filename(card, idx)
                    filepath = output_dir / filename

                    episode_meta_list.append(
                        {
                            "episode": ep_num,
                            "title": ep_title,
                            "path_id": card.get("path_id", ""),
                        }
                    )

                    # Skip if already downloaded
                    if filepath.exists() and filepath.stat().st_size > 0:
                        q.put(
                            json.dumps(
                                {
                                    "type": "episode_done",
                                    "episode": ep_num,
                                    "total": total,
                                    "status": "skipped",
                                }
                            )
                        )
                        continue

                    audio_url = core.get_audio_url(card)
                    if not audio_url:
                        q.put(
                            json.dumps(
                                {
                                    "type": "episode_done",
                                    "episode": ep_num,
                                    "total": total,
                                    "status": "error: no audio URL",
                                }
                            )
                        )
                        continue

                    q.put(
                        json.dumps(
                            {
                                "type": "episode_start",
                                "episode": ep_num,
                                "total": total,
                                "title": ep_title,
                            }
                        )
                    )

                    try:
                        direct_url = core.resolve_relinker(audio_url, dl_session)

                        last_emit_time = [0.0]

                        def progress_cb(bytes_dl, total_bytes, _ep=ep_num, _total=total):
                            now = time.monotonic()
                            if now - last_emit_time[0] >= 0.5 or bytes_dl >= total_bytes:
                                last_emit_time[0] = now
                                q.put(
                                    json.dumps(
                                        {
                                            "type": "progress",
                                            "episode": _ep,
                                            "total": _total,
                                            "bytes": bytes_dl,
                                            "total_bytes": total_bytes,
                                        }
                                    )
                                )

                        core.download_file(direct_url, filepath, dl_session, progress_cb)

                        # Tag MP3
                        audiobook_data = {
                            "title": title,
                            "podcast_info": {
                                "author": author_name or "",
                                "genres": (
                                    catalog_card.get("genres", []) if catalog_card else []
                                ),
                                "images": (
                                    catalog_card.get("images", {}) if catalog_card else {}
                                ),
                                "image": cover_url,
                            },
                        }
                        try:
                            tagger.tag_episode(
                                filepath, card, audiobook_data, idx, total, dl_session
                            )
                        except Exception as e:
                            log.warning("Tagging failed for %s: %s", filename, e)

                        q.put(
                            json.dumps(
                                {
                                    "type": "episode_done",
                                    "episode": ep_num,
                                    "total": total,
                                    "status": "downloaded",
                                }
                            )
                        )

                    except Exception as e:
                        tmp = filepath.with_suffix(".tmp")
                        if tmp.exists():
                            tmp.unlink()
                        q.put(
                            json.dumps(
                                {
                                    "type": "episode_done",
                                    "episode": ep_num,
                                    "total": total,
                                    "status": f"error: {e}",
                                }
                            )
                        )

                # Save metadata and cover
                poller._save_metadata(
                    output_dir=output_dir,
                    title=title,
                    author=author_name,
                    reader=reader_name,
                    description=(
                        catalog_card.get("description", "") if catalog_card else ""
                    ),
                    cover_url=cover_url,
                    episodes=episode_meta_list,
                    completed=True,
                    session=dl_session,
                    source="catalog",
                )

            except Exception as e:
                q.put(json.dumps({"type": "error", "message": str(e)}))
            finally:
                q.put(None)

        thread = threading.Thread(target=do_download, daemon=True)
        _active_downloads[slug] = thread
        thread.start()

        def generate():
            while True:
                msg = q.get()
                if msg is None:
                    yield "event: complete\ndata: {}\n\n"
                    break
                yield f"data: {msg}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

```

- [ ] **Step 2: Verify the app still starts**

Run: `cd /Users/vito/repos/ad-alta-voce-dl && python -c "from rai.web.app import create_app; app = create_app(); print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add rai/web/app.py
git commit -m "feat(web): add /api/download/<slug> SSE endpoint for catalog downloads"
```

---

## Chunk 4: Make Catalog Cards Clickable

### Task 4: Wrap catalog cards in links on home page

**Files:**
- Modify: `rai/web/templates/home.html:108-121`

- [ ] **Step 1: Replace the catalog card markup**

In `rai/web/templates/home.html`, replace the catalog card block (lines 108-121):

```html
        {% for book in catalog %}
        <div class="card card-small" data-title="{{ book.title|lower }}">
            <div class="card-img-wrap">
                <img src="{{ book._cover_url }}" alt="{{ book.title }}" loading="lazy">
                {% if book._downloaded %}
                <span class="badge-downloaded" title="Downloaded">&#10003;</span>
                {% endif %}
            </div>
            <div class="card-info">
                <h3>{{ book.title }}</h3>
                {% if book.subtitle %}<p>{{ book.subtitle|truncate(60) }}</p>{% endif %}
            </div>
        </div>
        {% endfor %}
```

with:

```html
        {% for book in catalog %}
        <a href="/audiobook/{{ book._slug }}" class="card card-small" data-title="{{ book.title|lower }}">
            <div class="card-img-wrap">
                <img src="{{ book._cover_url }}" alt="{{ book.title }}" loading="lazy">
                {% if book._downloaded %}
                <span class="badge-downloaded" title="Downloaded">&#10003;</span>
                {% endif %}
            </div>
            <div class="card-info">
                <h3>{{ book.title }}</h3>
                {% if book.subtitle %}<p>{{ book.subtitle|truncate(60) }}</p>{% endif %}
            </div>
        </a>
        {% endfor %}
```

The only changes: `<div class="card card-small"` → `<a href="/audiobook/{{ book._slug }}" class="card card-small"` and `</div>` → `</a>` (the outer wrapper).

- [ ] **Step 2: Commit**

```bash
git add rai/web/templates/home.html
git commit -m "feat(web): make catalog cards link to audiobook detail pages"
```

---

## Chunk 5: Final Verification

### Task 5: End-to-end verification

- [ ] **Step 1: Verify no syntax/import errors**

Run: `cd /Users/vito/repos/ad-alta-voce-dl && python -c "from rai.web.app import create_app; app = create_app(); print('OK')"`

Expected: `OK`

- [ ] **Step 2: Verify ruff passes**

Run: `cd /Users/vito/repos/ad-alta-voce-dl && uvx ruff check rai/web/app.py rai/web/templates/home.html`

Expected: No errors (or only pre-existing ones)

- [ ] **Step 3: Verify all routes are registered**

Run: `cd /Users/vito/repos/ad-alta-voce-dl && python -c "
from rai.web.app import create_app
app = create_app()
for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    print(f'{rule.rule:40s} {rule.endpoint}')
"`

Expected output should include:
```
/audiobook/<slug>                        audiobook_detail
/api/download/<slug>                     download_audiobook
```
alongside existing routes (`/`, `/api/download/current`, `/api/poll`, `/health`, `/downloaded/<author>/<name>`, `/dl-files/<filepath>`).

- [ ] **Step 4: Manual smoke test (if VPN is available)**

Open `http://localhost:5000` in browser. Click any catalog card. Should see audiobook detail page with episodes and a "Download All" button. Clicking the button should start SSE streaming and download episodes.
