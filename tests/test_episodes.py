"""Choosing one card per episode, and never writing two files for one number.

The fixtures are RAI feeds recorded on 2026-09-24, trimmed to the fields read here.
"""

import json
from pathlib import Path

import pytest

from rai import core

FIXTURES = Path(__file__).parent / "fixtures"


def feed(name):
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return data["title"], core.extract_cards(data)


def filenames(cards):
    return [core.build_episode_filename(card, i) for i, card in enumerate(cards)]


def test_book_page_drops_the_next_books_episodes():
    # RAI lists "1. Uomini e no" to "5. Uomini e no" on the Sorelle Materassi page.
    title, cards = feed("sorellematerassi")
    assert len(cards) == 25

    episodes = core.select_episodes(cards, title)

    assert [core.episode_number(c) for c in episodes] == list(range(1, 21))
    assert {c["toptitle"].split(". ", 1)[1] for c in episodes} == {"Sorelle Materassi"}
    names = filenames(episodes)
    assert len({n[:3] for n in names}) == len(names) == 20
    assert names[0] == "001 - Ad alta voce del 02032026.mp3"


def test_anthology_whose_episodes_are_named_after_stories_is_kept_whole():
    title, cards = feed("raccontidiluigipirandello")

    episodes = core.select_episodes(cards, title)

    assert episodes == cards
    assert [n[:3] for n in filenames(episodes)] == ["001", "002", "003", "004", "005"]


def test_page_title_that_no_episode_repeats_filters_nothing():
    cards = [
        {"episode": str(n), "episode_title": f"{n}. Panchine di Beppe Sebaste"} for n in (1, 2)
    ]
    assert core.select_episodes(cards, "Panchine. Come uscire dal mondo senza uscirne") == cards


def test_unnumbered_episodes_are_skipped_rather_than_given_a_guessed_number():
    # On 2026-09-24 RAI listed the 22 and 23 September episodes with no number.
    title, cards = feed("adaltavoce-episodi")
    book = core.parse_audiobook_from_episodi(cards)
    assert book == "Pian della Tortilla"

    episodes = core.select_episodes(cards, book)

    assert [core.episode_number(c) for c in episodes] == [1, 2, 3, 4, 5, 8]


def test_a_book_listed_from_two_airings_keeps_the_first_broadcast_of_each_number():
    def card(n, date):
        return {
            "episode": str(n),
            "episode_title": f"{n}. Agostino",
            "title": f"Ad alta voce del {date.replace('-', '/')}",
            "create_date": date,
        }

    later = [card(n, f"0{n}-09-2026") for n in (1, 2)]
    first = [card(n, f"0{n}-03-2014") for n in (1, 2, 3)]

    episodes = core.select_episodes(later + first, "Agostino")

    assert [(core.episode_number(c), c["create_date"][-4:]) for c in episodes] == [
        (1, "2014"),
        (2, "2014"),
        (3, "2014"),
    ]


@pytest.fixture
def book(tmp_path):
    (tmp_path / "001 - Ad alta voce del 02032026.mp3").write_bytes(b"ID3")
    (tmp_path / "002 - Ad alta voce del 03032026.mp3").write_bytes(b"")
    return tmp_path


def test_existing_episode_file_matches_on_the_number_alone(book):
    found = core.existing_episode_file(book, "001 - Ad alta voce del 30032026.mp3")
    assert found == book / "001 - Ad alta voce del 02032026.mp3"
    # An empty file is an interrupted download, not an episode.
    assert core.existing_episode_file(book, "002 - Ad alta voce del 03032026.mp3") is None
    assert core.existing_episode_file(book, "003 - Anything.mp3") is None


def test_download_never_writes_a_second_file_for_a_number(book):
    class NoNetwork:
        def get(self, *args, **kwargs):
            raise AssertionError("should have skipped before downloading")

    target = book / "001 - Ad alta voce del 30032026.mp3"
    assert core.download_file("https://example.invalid/a.mp3", target, NoNetwork()) == "skipped"
    assert not target.exists()
