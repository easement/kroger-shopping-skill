import tempfile
import unittest
from pathlib import Path
import json

from scripts.http_recording import HttpRecorder


class HttpRecordingTests(unittest.TestCase):
    def test_recorder_writes_payload_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            recorder = HttpRecorder(output_dir=Path(tmp_dir), prefix="test-http")
            out_path = recorder.record("https://example.com/path/to/page?q=1", "hello-world")

            self.assertTrue(out_path.exists())
            self.assertIn("test-http-001", out_path.name)
            self.assertEqual(out_path.read_text(), "hello-world")

    def test_recorder_appends_metadata_jsonl_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            metadata_path = tmp_path / "captures.jsonl"
            recorder = HttpRecorder(
                output_dir=tmp_path / "payloads",
                prefix="test-http",
                metadata_file=metadata_path,
                channel="recipe",
            )
            recorder.record("https://example.com/alpha", "first")
            recorder.record("https://example.com/beta", "second")

            lines = metadata_path.read_text().strip().splitlines()
            self.assertEqual(len(lines), 2)
            entry = json.loads(lines[0])
            self.assertEqual(entry["channel"], "recipe")
            self.assertIn("saved_path", entry)


if __name__ == "__main__":
    unittest.main()
