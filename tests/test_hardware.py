"""Tests for hardware detection, against fake sysfs/procfs trees."""
import pytest

from src import hardware
from src.hardware import (
    Monitor,
    detected_audio_device,
    detected_outputs,
    display_card,
    is_output_connected,
    labwc_rc_xml,
    load_overrides,
    resolve_monitors,
)

PI_ASOUND = (
    " 0 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0\n"
    "                      vc4-hdmi-0\n"
    " 1 [vc4hdmi1       ]: vc4-hdmi - vc4-hdmi-1\n"
    "                      vc4-hdmi-1\n"
)


def _fake_drm(tmp_path, connectors, connected=()):
    """Create /sys/class/drm-style connector dirs and /dev/dri nodes."""
    drm = tmp_path / "drm"
    dri = tmp_path / "dri"
    drm.mkdir()
    dri.mkdir()
    for name in connectors:
        d = drm / name
        d.mkdir()
        (d / "status").write_text("connected\n" if name in connected else "disconnected\n")
        (dri / name.split("-")[0]).touch()
    return str(drm), str(dri)


def _cards_file(tmp_path, text):
    p = tmp_path / "cards"
    p.write_text(text)
    return str(p)


PI_CARD1 = ["card1-HDMI-A-1", "card1-HDMI-A-2", "card1-Writeback-1"]


class TestDisplayCard:
    def test_picks_card_with_hdmi_when_vc4_is_card1(self, tmp_path):
        drm, dri = _fake_drm(tmp_path, PI_CARD1)
        (tmp_path / "dri" / "card0").touch()  # v3d: no connectors
        assert display_card(drm, dri).endswith("card1")

    def test_picks_card_with_hdmi_when_vc4_is_card0(self, tmp_path):
        """Pi 4: v3d and vc4 swap numbers between boots."""
        drm, dri = _fake_drm(tmp_path, ["card0-HDMI-A-1", "card0-HDMI-A-2"])
        (tmp_path / "dri" / "card1").touch()
        assert display_card(drm, dri).endswith("card0")

    def test_ignores_card_with_only_writeback_or_internal(self, tmp_path):
        drm, dri = _fake_drm(tmp_path, ["card0-Writeback-1", "card0-eDP-1", "card0-DSI-1"])
        assert display_card(drm, dri) is None

    def test_none_when_device_node_missing(self, tmp_path):
        drm, dri = _fake_drm(tmp_path, PI_CARD1)
        (tmp_path / "dri" / "card1").unlink()
        assert display_card(drm, dri) is None


class TestDetectedOutputs:
    def test_pi_order(self, tmp_path):
        drm, _ = _fake_drm(tmp_path, PI_CARD1)
        assert detected_outputs(drm) == ["HDMI-A-1", "HDMI-A-2"]

    def test_pc_hdmi_before_displayport_numeric_order(self, tmp_path):
        drm, _ = _fake_drm(
            tmp_path,
            ["card0-DP-1", "card0-HDMI-A-10", "card0-HDMI-A-2", "card0-eDP-1"],
        )
        assert detected_outputs(drm) == ["HDMI-A-2", "HDMI-A-10", "DP-1"]

    def test_empty_without_drm(self, tmp_path):
        assert detected_outputs(str(tmp_path / "missing")) == []


class TestIsOutputConnected:
    def test_connected_and_disconnected(self, tmp_path):
        drm, _ = _fake_drm(tmp_path, PI_CARD1, connected={"card1-HDMI-A-2"})
        assert is_output_connected("HDMI-A-2", drm)
        assert not is_output_connected("HDMI-A-1", drm)
        assert not is_output_connected("DP-1", drm)


class TestAudio:
    def test_pi_hdmi_ports_map_to_vc4hdmi_cards(self, tmp_path):
        cards = _cards_file(tmp_path, PI_ASOUND)
        assert detected_audio_device("HDMI-A-1", cards) == "alsa/plughw:CARD=vc4hdmi0,DEV=0"
        assert detected_audio_device("HDMI-A-2", cards) == "alsa/plughw:CARD=vc4hdmi1,DEV=0"

    def test_non_pi_audio_is_default(self, tmp_path):
        cards = _cards_file(tmp_path, " 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n")
        assert detected_audio_device("HDMI-A-1", cards) is None
        assert detected_audio_device("DP-1", cards) is None

    def test_missing_cards_file(self, tmp_path):
        assert detected_audio_device("HDMI-A-1", str(tmp_path / "nope")) is None


class TestOverrides:
    def test_first_existing_file_wins(self, tmp_path):
        second = tmp_path / "b.conf"
        second.write_text("MONITOR_1_OUTPUT=DP-9\n")
        assert load_overrides([str(tmp_path / "a.conf"), str(second)]) == {"MONITOR_1_OUTPUT": "DP-9"}

    def test_windows_file_with_bom_crlf_quotes_comments(self, tmp_path):
        f = tmp_path / "x.conf"
        f.write_bytes(
            b"\xef\xbb\xbf# comment\r\n"
            b"monitor_1_output = \"DP-1\"\r\n"
            b"#MONITOR_2_OUTPUT=HDMI-A-2\r\n"
            b"MONITOR_2_AUDIO=\r\n"
            b"junk line\r\n"
        )
        assert load_overrides([str(f)]) == {"MONITOR_1_OUTPUT": "DP-1"}

    def test_no_files(self, tmp_path):
        assert load_overrides([str(tmp_path / "none")]) == {}


class TestResolveMonitors:
    def test_pi_defaults(self, tmp_path):
        drm, _ = _fake_drm(tmp_path, PI_CARD1)
        cards = _cards_file(tmp_path, PI_ASOUND)
        assert resolve_monitors(drm, cards, []) == {
            1: Monitor(1, "HDMI-A-1", "alsa/plughw:CARD=vc4hdmi0,DEV=0"),
            2: Monitor(2, "HDMI-A-2", "alsa/plughw:CARD=vc4hdmi1,DEV=0"),
        }

    def test_overrides_take_precedence(self, tmp_path):
        drm, _ = _fake_drm(tmp_path, PI_CARD1)
        cards = _cards_file(tmp_path, PI_ASOUND)
        conf = tmp_path / "vr.conf"
        conf.write_text("MONITOR_1_OUTPUT=HDMI-A-2\nMONITOR_2_OUTPUT=HDMI-A-1\nMONITOR_2_AUDIO=alsa/x\n")
        monitors = resolve_monitors(drm, cards, [str(conf)])
        # Swapped output also swaps the detected audio for monitor 1
        assert monitors[1] == Monitor(1, "HDMI-A-2", "alsa/plughw:CARD=vc4hdmi1,DEV=0")
        assert monitors[2] == Monitor(2, "HDMI-A-1", "alsa/x")

    def test_single_output_device_has_only_monitor_1(self, tmp_path):
        drm, _ = _fake_drm(tmp_path, ["card0-HDMI-A-1"])
        monitors = resolve_monitors(drm, _cards_file(tmp_path, ""), [])
        assert list(monitors) == [1]
        assert monitors[1].audio_device is None

    def test_nothing_detected(self, tmp_path):
        assert resolve_monitors(str(tmp_path / "x"), str(tmp_path / "y"), []) == {}


class TestLabwcRcXml:
    def test_rules_target_resolved_outputs(self):
        xml = labwc_rc_xml({
            1: Monitor(1, "DP-1", None),
            2: Monitor(2, "HDMI-A-1", None),
        })
        assert 'identifier="mpv-mon-1"' in xml
        assert 'output="DP-1"' in xml
        assert 'identifier="mpv-mon-2"' in xml
        assert 'output="HDMI-A-1"' in xml
        # MoveToOutput must come before ToggleFullscreen (labwc won't move fullscreen windows)
        assert xml.index("MoveToOutput") < xml.index("ToggleFullscreen")

    def test_valid_xml(self):
        import xml.etree.ElementTree as ET
        ET.fromstring(labwc_rc_xml({1: Monitor(1, "HDMI-A-1", None)}))

    def test_labwc_setup_writes_file_and_prints_card(self, tmp_path, monkeypatch, capsys):
        drm, dri = _fake_drm(tmp_path, PI_CARD1)
        monkeypatch.setattr(hardware, "DRM_ROOT", drm)
        monkeypatch.setattr(hardware, "DEV_DRI", dri)
        monkeypatch.setattr(hardware, "ASOUND_CARDS", _cards_file(tmp_path, PI_ASOUND))
        monkeypatch.setattr(hardware, "CONFIG_PATHS", ())
        rc = tmp_path / "labwc" / "rc.xml"
        assert hardware._labwc_setup(str(rc), wait_seconds=0) == 0
        assert 'output="HDMI-A-2"' in rc.read_text()
        assert capsys.readouterr().out.strip().endswith("card1")
