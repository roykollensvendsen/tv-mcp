# SPDX-License-Identifier: GPL-3.0-or-later
"""The owner's settings file: friendly TV names, and which TVs to leave alone."""

import pytest

from tv_mcp.cli import main
from tv_mcp.settings import AmbiguousTvError, UnknownTvError, find_tv, load_settings

EXAMPLE = """
[jellyfin]
url = "http://192.0.2.5:8096"
api_key = "example-key"

[tvs.living-room]
names = ["the living room", "The Frame"]
address = "192.0.2.10"
mac = "00:00:5E:00:53:01"

[tvs.upstairs]
names = ["upstairs"]
address = "192.0.2.11"
hands_off = true
"""


@pytest.fixture
def settings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(EXAMPLE)
    return load_settings(path)


def test_settings_are_read_from_the_file(settings):
    living = settings.tvs[0]
    assert living.key == "living-room"
    assert living.address == "192.0.2.10"
    assert living.mac == "00:00:5E:00:53:01"
    assert not living.hands_off
    assert settings.tvs[1].hands_off
    assert settings.jellyfin_url == "http://192.0.2.5:8096"


def test_a_missing_file_means_no_tvs(tmp_path):
    settings = load_settings(tmp_path / "absent.toml")
    assert settings.tvs == ()
    assert settings.jellyfin_url is None


def test_a_tv_is_found_by_any_of_its_names_however_it_is_said(settings):
    for said in ("The Frame", "the frame", "  living room ", "Living-Room", "the living room"):
        assert find_tv(settings, said).key == "living-room", said


def test_an_unknown_name_is_refused_with_the_names_there_are(settings):
    with pytest.raises(UnknownTvError, match="the living room"):
        find_tv(settings, "the kitchen")


def test_a_name_that_matches_two_tvs_is_refused(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[tvs.a]\nnames = ["the tv"]\naddress = "192.0.2.1"\n'
        '[tvs.b]\nnames = ["The TV"]\naddress = "192.0.2.2"\n'
    )
    with pytest.raises(AmbiguousTvError):
        find_tv(load_settings(path), "the tv")


def test_features_are_the_default_unless_the_file_names_them(settings, tmp_path):
    assert settings.features is None
    path = tmp_path / "with-features.toml"
    path.write_text('[features]\nenabled = ["status", "setup"]\n')
    assert load_settings(path).features == ("status", "setup")


def test_a_tv_uses_the_samsung_driver_unless_it_names_another(settings, tmp_path):
    assert settings.tvs[0].driver == "samsung-tizen"
    path = tmp_path / "lg.toml"
    path.write_text('[tvs.den]\nnames = ["den"]\ndriver = "lg-webos"\n')
    assert load_settings(path).tvs[0].driver == "lg-webos"


def test_the_jellyfin_key_is_read_from_its_own_file_beside_the_settings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[jellyfin]\nurl = "http://192.0.2.5:8096"\n')
    (tmp_path / "jellyfin-key").write_text("from-the-file\n")
    assert load_settings(path).jellyfin_key == "from-the-file"


def test_an_empty_key_file_means_no_key(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[jellyfin]\nurl = "http://192.0.2.5:8096"\n')
    (tmp_path / "jellyfin-key").write_text("")
    assert load_settings(path).jellyfin_key is None


def test_a_key_in_the_settings_file_wins_over_the_key_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[jellyfin]\nurl = "http://192.0.2.5:8096"\napi_key = "inline"\n')
    (tmp_path / "jellyfin-key").write_text("from-the-file")
    assert load_settings(path).jellyfin_key == "inline"


def test_the_command_line_can_point_at_a_settings_file(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text('[tvs.den]\nnames = ["the den"]\nhands_off = true\n')
    assert main(["status", "--settings", str(path)]) == 0
    assert capsys.readouterr().out == "the den: left alone\n"


NAMED = """
[tvs.downstairs]
location = "down"
names = ["the den"]
description = "The Frame in the living room downstairs"
model = "QE55LS03BAUXXC"
device_name = "Samsung The Frame 55"

[tvs.upstairs]
location = "up"
description = "The Q68CA in the bedroom upstairs"
model = "TQ55Q68CAUXXC"
"""


@pytest.fixture
def named(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(NAMED)
    return load_settings(path)


def test_a_tv_is_called_by_where_it_stands_and_has_a_description(named):
    down = find_tv(named, "down")
    assert down.spoken == "down"
    assert down.description == "The Frame in the living room downstairs"
    assert find_tv(named, "TV down") is down
    assert find_tv(named, "TV-en down") is down
    assert find_tv(named, "the den") is down


def test_a_tv_is_found_by_its_model_and_its_own_device_name(named):
    assert find_tv(named, "qe55ls03bauxxc").key == "downstairs"
    assert find_tv(named, "Samsung The Frame 55").key == "downstairs"
    assert find_tv(named, "TQ55Q68CAUXXC").key == "upstairs"
    assert find_tv(named, "Q68CA").key == "upstairs"


def test_a_brand_two_tvs_share_is_refused_rather_than_guessed(named):
    assert find_tv(named, "TV up").brand == "Samsung"
    with pytest.raises(AmbiguousTvError, match="down and up"):
        find_tv(named, "Samsung")


def test_two_tvs_of_the_same_model_are_told_apart_by_where_they_stand(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[tvs.a]\nlocation = "kitchen"\nmodel = "QE55LS03BAUXXC"\ndevice_id = "uuid:a"\n'
        '[tvs.b]\nlocation = "office"\nmodel = "QE55LS03BAUXXC"\ndevice_id = "uuid:b"\n'
    )
    twins = load_settings(path)
    assert find_tv(twins, "kitchen").device_id == "uuid:a"
    assert find_tv(twins, "office").device_id == "uuid:b"
    with pytest.raises(AmbiguousTvError):
        find_tv(twins, "QE55LS03BAUXXC")


def test_the_users_own_jellyfin_token_is_read_from_its_file_beside_the_settings(tmp_path):
    (tmp_path / "config.toml").write_text('[jellyfin]\nurl = "http://192.0.2.5:8096"\n')
    (tmp_path / "jellyfin-user-token").write_text("user-token\n")
    assert load_settings(tmp_path / "config.toml").jellyfin_user_token == "user-token"  # noqa: S105 - an example
