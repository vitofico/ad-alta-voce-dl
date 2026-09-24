from rai.core import BASE_URL, resized_image_url

COVER = "/dl/img/2025/08/18/1755521790499_Sorelle%20Materassi%20-2048x2048.jpg"


def test_relative_rai_cover_goes_through_the_resizer():
    assert resized_image_url(COVER, 400) == f"{BASE_URL}/resizegd/400x-{COVER}"


def test_absolute_rai_cover_goes_through_the_resizer():
    assert resized_image_url(BASE_URL + COVER, 600) == f"{BASE_URL}/resizegd/600x-{COVER}"


def test_library_cover_and_empty_url_pass_through():
    assert resized_image_url("/dl-files/Agostino/cover.jpg", 400) == "/dl-files/Agostino/cover.jpg"
    assert resized_image_url("", 400) == ""


def test_other_hosts_pass_through():
    url = "https://example.org/dl/img/cover.jpg"
    assert resized_image_url(url, 400) == url
