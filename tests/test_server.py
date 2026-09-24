from rai.web.app import _server_address


def test_listens_on_loopback_port_5000_by_default():
    assert _server_address({}) == ("127.0.0.1", 5000)


def test_host_and_port_come_from_the_environment():
    assert _server_address({"WEB_HOST": "0.0.0.0", "WEB_PORT": "5055"}) == ("0.0.0.0", 5055)
