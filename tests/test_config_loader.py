"""Tests for config_loader — runs without any hardware or USB stick."""
import json
import pytest

from src.config_loader import ConfigError, _parse, _parse_quit, load_config


# ---------------------------------------------------------------------------
# _parse — button parsing
# ---------------------------------------------------------------------------

class TestParseButtons:
    def test_minimal_valid_config(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4"}}})
        assert len(config.buttons) == 1
        assert config.buttons[0].video == "v.mp4"

    def test_missing_buttons_section(self):
        with pytest.raises(ConfigError, match="missing 'buttons'"):
            _parse({})

    def test_empty_buttons_raises(self):
        with pytest.raises(ConfigError, match="no buttons"):
            _parse({"buttons": {}})

    def test_non_integer_key_raises(self):
        with pytest.raises(ConfigError, match="must be an integer"):
            _parse({"buttons": {"abc": {"video": "v.mp4"}}})

    def test_missing_video_field_raises(self):
        with pytest.raises(ConfigError, match="missing 'video'"):
            _parse({"buttons": {"0": {"monitor": 1}}})

    def test_invalid_monitor_raises(self):
        with pytest.raises(ConfigError, match="monitor must be 1 or 2"):
            _parse({"buttons": {"0": {"video": "v.mp4", "monitor": 3}}})

    def test_default_monitor_is_1(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4"}}})
        assert config.buttons[0].monitor == 1

    def test_monitor_2_accepted(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4", "monitor": 2}}})
        assert config.buttons[0].monitor == 2

    def test_multiple_buttons_all_parsed(self):
        config = _parse({"buttons": {
            "0": {"video": "v1.mp4"},
            "7": {"video": "v2.mp4"},
            "31": {"video": "v3.mp4"},
        }})
        assert len(config.buttons) == 3
        assert 0 in config.buttons
        assert 7 in config.buttons
        assert 31 in config.buttons

    def test_invalid_style_type_raises(self):
        with pytest.raises(ConfigError, match="must be 'color' or 'image'"):
            _parse({"buttons": {"0": {"video": "v.mp4", "button": {"type": "video"}}}})

    def test_default_style_is_color(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4"}}})
        assert config.buttons[0].style.type == "color"

    def test_image_style_parsed(self):
        config = _parse({"buttons": {"0": {
            "video": "v.mp4",
            "button": {"type": "image", "image": "btn.png", "label": "Play"},
        }}})
        assert config.buttons[0].style.type == "image"
        assert config.buttons[0].style.image == "btn.png"
        assert config.buttons[0].style.label == "Play"

    def test_color_style_parsed(self):
        config = _parse({"buttons": {"0": {
            "video": "v.mp4",
            "button": {"type": "color", "color": "#FF0000", "label": "Red"},
        }}})
        assert config.buttons[0].style.color == "#FF0000"
        assert config.buttons[0].style.label == "Red"


# ---------------------------------------------------------------------------
# Keyboard key mapping
# ---------------------------------------------------------------------------

class TestKeyMapping:
    def test_key_normalized_to_lowercase(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4", "key": "F1"}}})
        assert config.buttons[0].key == "f1"

    def test_key_already_lowercase_unchanged(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4", "key": "space"}}})
        assert config.buttons[0].key == "space"

    def test_no_key_is_none(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4"}}})
        assert config.buttons[0].key is None

    def test_key_map_returns_correct_mapping(self):
        config = _parse({"buttons": {
            "0": {"video": "v1.mp4", "key": "F1"},
            "1": {"video": "v2.mp4", "key": "F2"},
            "2": {"video": "v3.mp4"},          # no key
        }})
        assert config.key_map() == {"f1": 0, "f2": 1}

    def test_key_map_empty_when_no_keys_configured(self):
        config = _parse({"buttons": {
            "0": {"video": "v.mp4"},
            "1": {"video": "v2.mp4"},
        }})
        assert config.key_map() == {}


# ---------------------------------------------------------------------------
# Quit config
# ---------------------------------------------------------------------------

class TestQuitConfig:
    def test_no_quit_section_returns_none(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4"}}})
        assert config.quit is None

    def test_quit_stream_deck_button_parsed(self):
        config = _parse({
            "quit": {"stream_deck_button": 5},
            "buttons": {"0": {"video": "v.mp4"}},
        })
        assert config.quit.stream_deck_button == 5

    def test_quit_key_normalized_to_lowercase(self):
        config = _parse({
            "quit": {"key": "F12"},
            "buttons": {"0": {"video": "v.mp4"}},
        })
        assert config.quit.key == "f12"

    def test_quit_escape_key(self):
        config = _parse({
            "quit": {"key": "ESCAPE"},
            "buttons": {"0": {"video": "v.mp4"}},
        })
        assert config.quit.key == "escape"

    def test_quit_default_style_is_red(self):
        config = _parse({
            "quit": {"stream_deck_button": 5},
            "buttons": {"0": {"video": "v.mp4"}},
        })
        assert config.quit.style.color == "#CC0000"
        assert config.quit.style.label == "QUIT"

    def test_quit_custom_style(self):
        config = _parse({
            "quit": {
                "stream_deck_button": 5,
                "button": {"type": "color", "color": "#000000", "label": "EXIT"},
            },
            "buttons": {"0": {"video": "v.mp4"}},
        })
        assert config.quit.style.color == "#000000"
        assert config.quit.style.label == "EXIT"


# ---------------------------------------------------------------------------
# requires_deck()
# ---------------------------------------------------------------------------

class TestRequiresDeck:
    def test_requires_deck_when_button_has_no_key(self):
        config = _parse({"buttons": {
            "0": {"video": "v1.mp4", "key": "1"},
            "1": {"video": "v2.mp4"},  # no key → only reachable via deck
        }})
        assert config.requires_deck() is True

    def test_does_not_require_deck_when_all_buttons_have_keys(self):
        config = _parse({"buttons": {
            "0": {"video": "v1.mp4", "key": "1"},
            "1": {"video": "v2.mp4", "key": "2"},
        }})
        assert config.requires_deck() is False

    def test_requires_deck_when_quit_has_deck_button_but_no_key(self):
        config = _parse({
            "quit": {"stream_deck_button": 5},
            "buttons": {"0": {"video": "v.mp4", "key": "1"}},
        })
        assert config.requires_deck() is True

    def test_does_not_require_deck_when_quit_has_both(self):
        config = _parse({
            "quit": {"stream_deck_button": 5, "key": "q"},
            "buttons": {"0": {"video": "v.mp4", "key": "1"}},
        })
        assert config.requires_deck() is False

    def test_does_not_require_deck_when_quit_key_only(self):
        config = _parse({
            "quit": {"key": "q"},
            "buttons": {"0": {"video": "v.mp4", "key": "1"}},
        })
        assert config.requires_deck() is False

    def test_does_not_require_deck_with_no_quit(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4", "key": "1"}}})
        assert config.requires_deck() is False


# ---------------------------------------------------------------------------
# Path helpers on ButtonConfig
# ---------------------------------------------------------------------------

class TestButtonPaths:
    def test_video_path_prepends_mount(self, monkeypatch):
        monkeypatch.setattr("src.config_loader.USB_MOUNT", "/mnt/test")
        config = _parse({"buttons": {"0": {"video": "videos/clip.mp4"}}})
        assert config.buttons[0].video_path() == "/mnt/test/videos/clip.mp4"

    def test_image_path_prepends_mount_when_image_style(self, monkeypatch):
        monkeypatch.setattr("src.config_loader.USB_MOUNT", "/mnt/test")
        config = _parse({"buttons": {"0": {
            "video": "v.mp4",
            "button": {"type": "image", "image": "btn.png"},
        }}})
        assert config.buttons[0].image_path() == "/mnt/test/btn.png"

    def test_image_path_is_none_for_color_style(self, monkeypatch):
        monkeypatch.setattr("src.config_loader.USB_MOUNT", "/mnt/test")
        config = _parse({"buttons": {"0": {"video": "v.mp4"}}})
        assert config.buttons[0].image_path() is None


# ---------------------------------------------------------------------------
# load_config — filesystem integration
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_raises_when_config_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.config_loader.USB_MOUNT", str(tmp_path))
        with pytest.raises(ConfigError, match="not found"):
            load_config()

    def test_raises_on_invalid_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.config_loader.USB_MOUNT", str(tmp_path))
        (tmp_path / "config.json").write_text("{ not valid json }")
        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config()

    def test_loads_valid_config_from_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.config_loader.USB_MOUNT", str(tmp_path))
        data = {"buttons": {"0": {"video": "v.mp4", "monitor": 1}}}
        (tmp_path / "config.json").write_text(json.dumps(data))
        config = load_config()
        assert len(config.buttons) == 1
