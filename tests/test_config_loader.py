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
        assert config.key_map() == {"f1": config.buttons[0], "f2": config.buttons[1]}

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
# playing_border_color
# ---------------------------------------------------------------------------

class TestPlayingBorderColor:
    def test_defaults_to_red(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4"}}})
        assert config.playing_border_color == "#FF0000"

    def test_custom_color(self):
        config = _parse({
            "playing_border_color": "#00ff00",
            "buttons": {"0": {"video": "v.mp4"}},
        })
        assert config.playing_border_color == "#00ff00"

    @pytest.mark.parametrize("bad", ["red", "#FFF", "00FF00", 123, None])
    def test_invalid_color_rejected(self, bad):
        with pytest.raises(ConfigError, match="playing_border_color"):
            _parse({
                "playing_border_color": bad,
                "buttons": {"0": {"video": "v.mp4"}},
            })


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

    def test_deck_only_actions_lists_buttons_and_quit(self):
        config = _parse({
            "quit": {"stream_deck_button": 5},
            "buttons": {
                "3": {"video": "v3.mp4"},
                "0": {"video": "v0.mp4", "key": "1"},
                "1": {"video": "v1.mp4"},
            },
        })
        assert config.deck_only_actions() == ["button 1", "button 3", "quit"]

    def test_deck_only_actions_empty_when_all_have_keys(self):
        config = _parse({"buttons": {"0": {"video": "v.mp4", "key": "1"}}})
        assert config.deck_only_actions() == []


# ---------------------------------------------------------------------------
# Path helpers on ButtonConfig
# ---------------------------------------------------------------------------

class TestButtonPaths:
    def test_video_path_prepends_mount(self, monkeypatch):
        config = _parse({"buttons": {"0": {"video": "videos/clip.mp4"}}}, "/mnt/test")
        assert config.buttons[0].video_path() == "/mnt/test/videos/clip.mp4"

    def test_image_path_prepends_mount_when_image_style(self, monkeypatch):
        config = _parse({"buttons": {"0": {
            "video": "v.mp4",
            "button": {"type": "image", "image": "btn.png"},
        }}}, "/mnt/test")
        assert config.buttons[0].image_path() == "/mnt/test/btn.png"

    def test_image_path_is_none_for_color_style(self, monkeypatch):
        config = _parse({"buttons": {"0": {"video": "v.mp4"}}}, "/mnt/test")
        assert config.buttons[0].image_path() is None


# ---------------------------------------------------------------------------
# load_config — filesystem integration
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_raises_when_config_and_folders_missing(self, tmp_path, monkeypatch):
        with pytest.raises(ConfigError, match="No config.json or Monitor folders"):
            load_config(str(tmp_path))

    def test_raises_on_invalid_json(self, tmp_path, monkeypatch):
        (tmp_path / "config.json").write_text("{ not valid json }")
        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config(str(tmp_path))

    def test_loads_valid_config_from_file(self, tmp_path, monkeypatch):
        data = {"buttons": {"0": {"video": "v.mp4", "monitor": 1}}}
        (tmp_path / "config.json").write_text(json.dumps(data))
        config = load_config(str(tmp_path))
        assert len(config.buttons) == 1


# ---------------------------------------------------------------------------
# Explicit pages and paging keys (config.json)
# ---------------------------------------------------------------------------

_TWO_PAGES = {
    "pages": [
        {"0": {"video": "a.mp4", "monitor": 1}, "1": {"video": "b.mp4", "monitor": 2}},
        {"0": {"video": "c.mp4", "monitor": 1}, "1": {"video": "d.mp4", "monitor": 2}},
    ]
}


class TestPages:
    def test_pages_parsed(self):
        config = _parse(_TWO_PAGES)
        assert len(config.pages) == 2
        assert config.pages[1][0].video == "c.mp4"

    def test_buttons_is_a_single_page(self):
        config = _parse({"buttons": {"0": {"video": "a.mp4"}}})
        assert len(config.pages) == 1

    def test_buttons_and_pages_together_rejected(self):
        with pytest.raises(ConfigError, match="one or the other"):
            _parse({"buttons": {"0": {"video": "a.mp4"}}, "pages": [{"0": {"video": "b.mp4"}}]})

    def test_pages_must_be_a_list(self):
        with pytest.raises(ConfigError, match="list of pages"):
            _parse({"pages": {"0": {"video": "a.mp4"}}})

    def test_empty_page_rejected(self):
        with pytest.raises(ConfigError, match="Page 2"):
            _parse({"pages": [{"0": {"video": "a.mp4"}}, {}]})

    def test_error_names_the_page(self):
        with pytest.raises(ConfigError, match="Page 2 button 0 missing 'video'"):
            _parse({"pages": [{"0": {"video": "a.mp4"}}, {"0": {}}]})

    def test_duplicate_keyboard_key_rejected(self):
        with pytest.raises(ConfigError, match="more than one button"):
            _parse({"pages": [{"0": {"video": "a.mp4", "key": "F1"}},
                              {"0": {"video": "b.mp4", "key": "f1"}}]})

    def test_key_map_covers_all_pages(self):
        config = _parse({"pages": [{"0": {"video": "a.mp4", "key": "1"}},
                                   {"0": {"video": "b.mp4", "key": "2"}}]})
        assert config.key_map()["2"] is config.pages[1][0]

    def test_deck_only_actions_name_the_page(self):
        config = _parse(_TWO_PAGES)
        assert "page 2 button 1" in config.deck_only_actions()

    @pytest.mark.parametrize("bad", ["10", -1, 1.5, True])
    def test_invalid_paging_key_rejected(self, bad):
        with pytest.raises(ConfigError, match="paging.next"):
            _parse(dict(_TWO_PAGES, paging={"next": bad}))


class TestExplicitLayout:
    def test_single_page_has_no_paging_keys(self):
        layout = _parse({"buttons": {"0": {"video": "a.mp4"}}}).layout(15, False)
        assert layout.previous_key is None and layout.next_key is None

    def test_default_paging_keys_are_last_two(self):
        layout = _parse(_TWO_PAGES).layout(15, False)
        assert (layout.previous_key, layout.next_key) == (13, 14)
        assert layout.warnings == []

    def test_paging_keys_from_config(self):
        layout = _parse(dict(_TWO_PAGES, paging={"previous": 10, "next": 4})).layout(15, False)
        assert (layout.previous_key, layout.next_key) == (10, 4)

    def test_hardware_paging_needs_no_keys(self):
        layout = _parse(_TWO_PAGES).layout(8, True)
        assert layout.previous_key is None and layout.next_key is None
        assert len(layout.pages) == 2

    def test_button_under_paging_key_hidden_with_warning(self):
        config = _parse({"pages": [{"5": {"video": "a.mp4"}}, {"0": {"video": "b.mp4"}}]})
        layout = config.layout(6, False)  # Mini: paging keys 4 and 5
        assert 5 not in layout.pages[0]
        assert any("hidden by a page key" in w for w in layout.warnings)

    def test_paging_keys_beyond_deck_warned(self):
        layout = _parse(dict(_TWO_PAGES, paging={"previous": 20, "next": 21})).layout(15, False)
        assert layout.previous_key is None
        assert any("don't fit" in w for w in layout.warnings)

    def test_button_beyond_deck_warned(self):
        config = _parse({"buttons": {"0": {"video": "a.mp4"}, "20": {"video": "b.mp4"}}})
        layout = config.layout(15, False)
        assert any("20" in w and "15 keys" in w for w in layout.warnings)

    def test_no_deck_keeps_all_pages(self):
        layout = _parse(_TWO_PAGES).layout(0, False)
        assert len(layout.pages) == 2
        assert layout.warnings == []


# ---------------------------------------------------------------------------
# Folder mode (no config.json)
# ---------------------------------------------------------------------------

def _touch(root, *paths):
    for p in paths:
        f = root / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"")


class TestFolderMode:
    def test_used_when_no_config_json(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/a.mp4", "Monitor 2/Videos/b.mp4")
        config = load_config(str(tmp_path))
        assert [b.monitor for b in config.auto_buttons] == [1, 2]
        assert config.auto_buttons[0].video_path().endswith("a.mp4")

    def test_config_json_takes_priority(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/a.mp4")
        (tmp_path / "config.json").write_text(json.dumps({"buttons": {"0": {"video": "x.mp4"}}}))
        config = load_config(str(tmp_path))
        assert config.auto_buttons == []
        assert config.buttons[0].video == "x.mp4"

    def test_nothing_on_stick_explains_layout(self, tmp_path):
        with pytest.raises(ConfigError, match="Monitor 1/Videos"):
            load_config(str(tmp_path))

    def test_monitor_folders_without_videos(self, tmp_path):
        (tmp_path / "Monitor 1" / "Videos").mkdir(parents=True)
        with pytest.raises(ConfigError, match="No videos found"):
            load_config(str(tmp_path))

    def test_picture_makes_image_button_with_badge(self, tmp_path):
        _touch(tmp_path, "Monitor 2/Videos/a.mp4", "Monitor 2/Pictures/a.png")
        btn = load_config(str(tmp_path)).auto_buttons[0]
        assert btn.style.type == "image"
        assert btn.image_path().endswith("a.png")
        assert btn.style.badge == "2"
        assert btn.style.label is None

    def test_no_picture_makes_labelled_colour_button(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/02 Train.mp4")
        btn = load_config(str(tmp_path)).auto_buttons[0]
        assert btn.style.type == "color"
        assert btn.style.label == "Train"

    def test_orphan_picture_warning(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/a.mp4", "Monitor 1/Pictures/b.png")
        config = load_config(str(tmp_path))
        assert any("b.png" in w for w in config.warnings)

    def test_always_needs_deck(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/a.mp4")
        assert load_config(str(tmp_path)).requires_deck() is True


class TestAutoLayout:
    def _config(self, tmp_path, n):
        _touch(tmp_path, *[f"Monitor 1/Videos/{i:02d}.mp4" for i in range(n)])
        return load_config(str(tmp_path))

    def test_fits_on_one_page_without_paging_keys(self, tmp_path):
        layout = self._config(tmp_path, 6).layout(6, False)
        assert len(layout.pages) == 1
        assert sorted(layout.pages[0]) == [0, 1, 2, 3, 4, 5]
        assert layout.previous_key is None

    def test_overflow_reserves_last_two_keys(self, tmp_path):
        layout = self._config(tmp_path, 7).layout(6, False)  # Mini: 4 videos per page
        assert (layout.previous_key, layout.next_key) == (4, 5)
        assert [sorted(p) for p in layout.pages] == [[0, 1, 2, 3], [0, 1, 2]]

    def test_order_preserved_across_pages(self, tmp_path):
        config = self._config(tmp_path, 7)
        layout = config.layout(6, False)
        flat = [btn for page in layout.pages for _, btn in sorted(page.items())]
        assert flat == config.auto_buttons

    def test_hardware_paging_uses_every_key(self, tmp_path):
        layout = self._config(tmp_path, 9).layout(8, True)  # Neo
        assert layout.previous_key is None
        assert [len(p) for p in layout.pages] == [8, 1]

    def test_no_deck_has_no_pages(self, tmp_path):
        assert self._config(tmp_path, 3).layout(0, False).pages == []
