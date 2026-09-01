import importlib.util
import unittest
from pathlib import Path


path = Path(__file__).parents[1] / "scripts" / "configure_connect_attachments.py"
spec = importlib.util.spec_from_file_location("configure_connect_attachments", path)
attachments = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attachments)


class ConfigureAttachmentsTests(unittest.TestCase):
    def test_normalize_removes_dot_and_duplicates(self):
        self.assertEqual(attachments.normalize_extensions([".MP3", "mp3", "ogg"]), ["mp3", "ogg"])

    def test_invalid_extension_is_rejected(self):
        with self.assertRaises(ValueError):
            attachments.normalize_extensions(["bad extension"])

    def test_merge_preserves_defaults_and_adds_mp3(self):
        current = [{"Extension": "pdf"}, {"Extension": "wav"}]
        self.assertEqual(
            attachments.merge_extensions(current, ["mp3"]),
            [{"Extension": "mp3"}, {"Extension": "pdf"}, {"Extension": "wav"}],
        )


if __name__ == "__main__":
    unittest.main()
