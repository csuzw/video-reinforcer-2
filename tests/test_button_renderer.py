"""Tests for button_renderer — PIL only, no hardware required."""
import pytest
from PIL import Image

from src.button_renderer import render_blank, render_button


class TestRenderBlank:
    def test_correct_size(self):
        img = render_blank((72, 72))
        assert img.size == (72, 72)

    def test_xl_size(self):
        img = render_blank((96, 96))
        assert img.size == (96, 96)

    def test_all_pixels_black(self):
        img = render_blank((72, 72))
        pixels = list(img.getdata())
        assert all(p == (0, 0, 0) for p in pixels)


class TestRenderColorButton:
    def test_correct_size(self):
        img = render_button((72, 72), style_type="color", color="#FF0000")
        assert img.size == (72, 72)

    def test_red_color(self):
        img = render_button((72, 72), style_type="color", color="#FF0000")
        r, g, b = img.getpixel((36, 10))  # centre, away from any label
        assert r == 255
        assert g == 0
        assert b == 0

    def test_blue_color(self):
        img = render_button((72, 72), style_type="color", color="#0000FF")
        r, g, b = img.getpixel((36, 10))
        assert r == 0
        assert g == 0
        assert b == 255

    def test_invalid_hex_does_not_raise(self):
        img = render_button((72, 72), style_type="color", color="not_a_color")
        assert img.size == (72, 72)

    def test_none_color_does_not_raise(self):
        img = render_button((72, 72), style_type="color", color=None)
        assert img.size == (72, 72)

    def test_xl_key_size(self):
        img = render_button((96, 96), style_type="color", color="#00FF00")
        assert img.size == (96, 96)


class TestRenderImageButton:
    def test_falls_back_to_color_when_file_missing(self):
        img = render_button(
            (72, 72),
            style_type="image",
            image_path="/nonexistent/image.png",
            color="#FF0000",
        )
        # Falls back to solid red
        r, g, b = img.getpixel((36, 10))
        assert r == 255
        assert g == 0
        assert b == 0

    def test_falls_back_when_no_image_path(self):
        img = render_button(
            (72, 72),
            style_type="image",
            image_path=None,
            color="#00FF00",
        )
        r, g, b = img.getpixel((36, 10))
        assert g == 255

    def test_loads_real_image(self, tmp_path):
        # Create a solid blue PNG to load
        source = Image.new("RGB", (200, 200), (0, 0, 255))
        path = str(tmp_path / "btn.png")
        source.save(path)

        img = render_button((72, 72), style_type="image", image_path=path)
        r, g, b = img.getpixel((36, 36))
        assert b == 255
        assert r == 0


class TestLabel:
    def test_label_adds_non_background_pixels_at_bottom(self):
        # Black background so label pixels stand out
        img = render_button((72, 72), style_type="color", color="#000000", label="TEST")
        # Bottom rows should have some non-black pixels (the label text)
        bottom_rows = [img.getpixel((x, y)) for y in range(55, 72) for x in range(72)]
        assert any(p != (0, 0, 0) for p in bottom_rows)

    def test_no_label_leaves_bottom_unchanged(self):
        img_no_label = render_button((72, 72), style_type="color", color="#FF0000")
        img_with_label = render_button((72, 72), style_type="color", color="#FF0000", label="HI")
        # The two images should differ somewhere in the bottom rows
        different = any(
            img_no_label.getpixel((x, y)) != img_with_label.getpixel((x, y))
            for y in range(55, 72)
            for x in range(72)
        )
        assert different
