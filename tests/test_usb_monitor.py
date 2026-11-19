"""Tests for the udisks2 helpers in usb_monitor (no real devices needed)."""
from src.usb_monitor import _existing_mount, _parse_mount_output


def _mounts(tmp_path, text):
    p = tmp_path / "mounts"
    p.write_text(text)
    return str(p)


class TestExistingMount:
    def test_finds_udisks_media_mount(self, tmp_path):
        f = _mounts(tmp_path, "/dev/sda1 /media/kiosk/VIDEOS vfat ro 0 0\n")
        assert _existing_mount("/dev/sda1", f) == "/media/kiosk/VIDEOS"

    def test_unescapes_spaces(self, tmp_path):
        f = _mounts(tmp_path, "/dev/sda1 /media/kiosk/MY\\040STICK vfat ro 0 0\n")
        assert _existing_mount("/dev/sda1", f) == "/media/kiosk/MY STICK"

    def test_ignores_system_mounts(self, tmp_path):
        """A USB-booted Pi's root/boot partitions must never be taken for the stick."""
        f = _mounts(tmp_path, "/dev/sda2 / ext4 rw 0 0\n/dev/sda1 /boot/firmware vfat rw 0 0\n")
        assert _existing_mount("/dev/sda2", f) is None
        assert _existing_mount("/dev/sda1", f) is None

    def test_not_mounted(self, tmp_path):
        f = _mounts(tmp_path, "/dev/mmcblk0p2 / ext4 rw 0 0\n")
        assert _existing_mount("/dev/sda1", f) is None

    def test_missing_file(self, tmp_path):
        assert _existing_mount("/dev/sda1", str(tmp_path / "nope")) is None


class TestParseMountOutput:
    def test_udisksctl_output(self):
        assert _parse_mount_output("Mounted /dev/sda1 at /media/kiosk/VIDEOS\n") == "/media/kiosk/VIDEOS"

    def test_older_udisksctl_trailing_dot(self):
        assert _parse_mount_output("Mounted /dev/sda1 at /media/kiosk/VIDEOS.\n") == "/media/kiosk/VIDEOS"

    def test_unexpected_output(self):
        assert _parse_mount_output("something else") is None
