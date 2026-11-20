"""Tests for folder_scanner — builds USB stick layouts in a temp folder."""
from src.folder_scanner import scan


def _touch(root, *paths):
    for p in paths:
        f = root / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"")


class TestMonitorFolders:
    def test_no_monitor_folders(self, tmp_path):
        _touch(tmp_path, "videos/a.mp4")
        result = scan(str(tmp_path))
        assert result.monitor_folders == []
        assert result.videos == []

    def test_forgiving_folder_names(self, tmp_path):
        _touch(tmp_path, "monitor1/VIDEOS/a.mp4", "MONITOR 2/Video/b.mp4")
        result = scan(str(tmp_path))
        assert [v.monitor for v in result.videos] == [1, 2]

    def test_files_directly_in_monitor_folder(self, tmp_path):
        _touch(tmp_path, "Monitor 1/a.mp4", "Monitor 1/a.png")
        result = scan(str(tmp_path))
        assert result.videos[0].path == "Monitor 1/a.mp4"
        assert result.videos[0].picture == "Monitor 1/a.png"

    def test_monitor_3_ignored(self, tmp_path):
        _touch(tmp_path, "Monitor 3/Videos/a.mp4")
        assert scan(str(tmp_path)).videos == []

    def test_monitor_1_listed_before_monitor_2(self, tmp_path):
        _touch(tmp_path, "Monitor 2/Videos/a.mp4", "Monitor 1/Videos/z.mp4")
        result = scan(str(tmp_path))
        assert [v.label for v in result.videos] == ["z", "a"]


class TestMatching:
    def test_picture_matched_by_name_ignoring_case_and_extension(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/Elephant.mp4", "Monitor 1/Pictures/elephant.PNG")
        v = scan(str(tmp_path)).videos[0]
        assert v.path == "Monitor 1/Videos/Elephant.mp4"
        assert v.picture == "Monitor 1/Pictures/elephant.PNG"

    def test_images_folder_name_accepted(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/a.mov", "Monitor 1/Images/a.jpg")
        assert scan(str(tmp_path)).videos[0].picture == "Monitor 1/Images/a.jpg"

    def test_video_without_picture(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/a.mp4")
        assert scan(str(tmp_path)).videos[0].picture is None

    def test_pictures_only_match_their_own_monitor(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/a.mp4", "Monitor 2/Pictures/a.png")
        result = scan(str(tmp_path))
        assert result.videos[0].picture is None
        assert result.orphan_pictures == ["Monitor 2/Pictures/a.png"]

    def test_orphan_picture_reported(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/Elephant.mp4", "Monitor 1/Pictures/Elefant.png")
        assert scan(str(tmp_path)).orphan_pictures == ["Monitor 1/Pictures/Elefant.png"]

    def test_other_files_ignored(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/a.mp4", "Monitor 1/Videos/notes.txt",
               "Monitor 1/Videos/._a.mp4", "Monitor 1/Videos/.DS_Store",
               "Monitor 1/Pictures/Thumbs.db")
        result = scan(str(tmp_path))
        assert [v.path for v in result.videos] == ["Monitor 1/Videos/a.mp4"]
        assert result.orphan_pictures == []


class TestOrderAndLabels:
    def test_numbers_sorted_as_numbers(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/10 c.mp4", "Monitor 1/Videos/2 b.mp4",
               "Monitor 1/Videos/1 a.mp4")
        assert [v.label for v in scan(str(tmp_path)).videos] == ["a", "b", "c"]

    def test_order_prefix_removed_from_label(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/01 - Big Train.mp4")
        assert scan(str(tmp_path)).videos[0].label == "Big Train"

    def test_label_kept_when_name_is_only_a_number(self, tmp_path):
        _touch(tmp_path, "Monitor 1/Videos/01.mp4")
        assert scan(str(tmp_path)).videos[0].label == "01"
