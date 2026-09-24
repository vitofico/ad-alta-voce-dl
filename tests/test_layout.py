"""Library layout: <Author>/<Title>/ today, <Title>/ from older versions and the CLI."""

import json

import pytest

from rai import core
from rai.web import app as web


def episode(folder, name="001 - Episode.mp3"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"ID3")


@pytest.fixture
def library(tmp_path):
    """One book per layout, plus the clutter a real library carries."""
    episode(tmp_path / "Aldo Palazzeschi" / "Sorelle Materassi")
    episode(tmp_path / "Agostino")
    (tmp_path / "Agostino" / "metadata.json").write_text(json.dumps({"title": "Agostino"}))
    (tmp_path / "Empty Author" / "No Episodes Yet").mkdir(parents=True)
    episode(tmp_path / ".state" / "Hidden")
    return tmp_path


def test_book_dirs_finds_both_layouts(library):
    found = [d.relative_to(library).as_posix() for d in core.book_dirs(library)]
    assert found == ["Agostino", "Aldo Palazzeschi/Sorelle Materassi"]


def test_book_dirs_on_a_missing_library_is_empty(tmp_path):
    assert core.book_dirs(tmp_path / "nope") == []


def test_book_dir_uses_the_legacy_folder_when_that_is_where_the_episodes_are(library):
    assert core.book_dir(library, "Alberto Moravia", "Agostino") == library / "Agostino"


def test_book_dir_prefers_the_current_layout(library):
    episode(library / "Sorelle Materassi")
    expected = library / "Aldo Palazzeschi" / "Sorelle Materassi"
    assert core.book_dir(library, "Aldo Palazzeschi", "Sorelle Materassi") == expected


def test_book_dir_for_a_new_book_is_author_then_title(library):
    assert core.book_dir(library, "Elio Vittorini", "Uomini e no") == (
        library / "Elio Vittorini" / "Uomini e no"
    )
    assert core.book_dir(library, "", "Uomini e no") == library / "Ad Alta Voce" / "Uomini e no"


def test_web_lists_and_opens_legacy_books(library, monkeypatch):
    monkeypatch.setattr(web, "DOWNLOADS_DIR", library)

    books = {b["rel_path"]: b for b in web._get_downloaded_audiobooks()}
    assert set(books) == {"Agostino", "Aldo Palazzeschi/Sorelle Materassi"}
    assert books["Agostino"]["author"] == ""
    assert books["Aldo Palazzeschi/Sorelle Materassi"]["author"] == "Aldo Palazzeschi"
    assert web._downloaded_names() == {"Agostino", "Sorelle Materassi"}

    client = web.create_app().test_client()
    for rel_path in books:
        page = client.get(f"/downloaded/{rel_path}")
        assert page.status_code == 200
        assert "001 - Episode.mp3" in page.get_data(as_text=True)
    assert client.get("/downloaded/..%2F..%2Fetc").status_code in (403, 404)
