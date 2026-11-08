import os
import tempfile
import time
import unittest
from pathlib import Path

from catmeowra.recorder import Recorder, Settings


class RecorderTimelineTests(unittest.TestCase):
    def test_hls_playlist_selects_segments_in_the_requested_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root / "settings.json")
            recorder = Recorder(root, settings, segment_seconds=10)
            first = root / "segment-20260101-120000.ts"
            second = root / "segment-20260101-120010.ts"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            old = time.time() - 10
            os.utime(first, (old, old))
            os.utime(second, (old, old))

            start = recorder._segment_time(first).timestamp()
            playlist = recorder.hls_playlist(start, start + 20)

        self.assertIn("/segments/segment-20260101-120000.ts", playlist)
        self.assertIn("/segments/segment-20260101-120010.ts", playlist)
        self.assertIn("#EXT-X-ENDLIST", playlist)


if __name__ == "__main__":
    unittest.main()
