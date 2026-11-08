from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import imageio_ffmpeg


class Settings:
    def __init__(self, path: Path, default_retention_days: int = 5) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._retention_days = default_retention_days
        self._default_retention_days = default_retention_days
        self._load()

    @property
    def retention_days(self) -> int:
        with self._lock:
            return self._retention_days

    def set_retention_days(self, value: int) -> None:
        if not 1 <= value <= 365:
            raise ValueError("retention_days must be between 1 and 365")
        with self._lock:
            self._retention_days = value
            payload = {"retention_days": value}
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temporary.replace(self.path)

    def _load(self) -> None:
        if not self.path.exists():
            self.set_retention_days(self._default_retention_days)
            return
        try:
            value = int(json.loads(self.path.read_text(encoding="utf-8"))["retention_days"])
            if 1 <= value <= 365:
                self._retention_days = value
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._retention_days = self._default_retention_days


class Recorder:
    """Encode the shared JPEG stream into rolling H.264 MPEG-TS segments for HLS playback."""

    def __init__(
        self,
        storage: Path,
        settings: Settings,
        fps: int = 15,
        bitrate_kbps: int = 2500,
        segment_seconds: int = 10,
    ) -> None:
        self.storage = storage
        self.settings = settings
        self.fps = fps
        self.bitrate_kbps = bitrate_kbps
        self.segment_seconds = segment_seconds
        self.storage.mkdir(parents=True, exist_ok=True)
        self._frames: queue.Queue[bytes | None] = queue.Queue(maxsize=4)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._last_frame_at = 0.0
        self._last_cleanup_at = 0.0
        self._error: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="camera-recorder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._frames.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=10)
        self._close_encoder()

    def submit(self, jpeg: bytes) -> None:
        now = time.monotonic()
        if now - self._last_frame_at < 1 / self.fps:
            return
        self._last_frame_at = now
        try:
            self._frames.put_nowait(jpeg)
        except queue.Full:
            try:
                self._frames.get_nowait()
                self._frames.put_nowait(jpeg)
            except (queue.Empty, queue.Full):
                pass

    def status(self) -> dict[str, object]:
        return {
            "recording": self._process is not None and self._process.poll() is None,
            "error": self._error,
            "fps": self.fps,
            "bitrate_kbps": self.bitrate_kbps,
            "segment_seconds": self.segment_seconds,
            "retention_days": self.settings.retention_days,
        }

    def list_recordings(self, limit: int = 500) -> list[dict[str, object]]:
        """List legacy MP4 recordings created before timeline/HLS recording was enabled."""
        files = sorted(self.storage.glob("recording-*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
        recordings: list[dict[str, object]] = []
        for path in files[:limit]:
            stat = path.stat()
            # The current MP4 has no final index until FFmpeg closes the segment.
            if time.time() - stat.st_mtime < 3:
                continue
            recordings.append(
                {
                    "name": path.name,
                    "url": f"/recordings/{path.name}",
                    "size_mb": round(stat.st_size / 1024 / 1024, 1),
                    "created_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
                }
            )
        return recordings

    def recording_path(self, name: str) -> Path | None:
        if Path(name).name != name or not name.startswith("recording-") or not name.endswith(".mp4"):
            return None
        path = self.storage / name
        return path if path.is_file() else None

    def segment_path(self, name: str) -> Path | None:
        if Path(name).name != name or not name.startswith("segment-") or not name.endswith(".ts"):
            return None
        path = self.storage / name
        return path if path.is_file() else None

    def timeline(self) -> dict[str, object]:
        segments = self._segments()
        if not segments:
            return {"available": False, "count": 0, "start": None, "end": None}
        start = self._segment_time(segments[0])
        end = self._segment_time(segments[-1]).timestamp() + self.segment_seconds
        return {
            "available": True,
            "count": len(segments),
            "start": start.isoformat(timespec="seconds"),
            "end": datetime.fromtimestamp(end).astimezone().isoformat(timespec="seconds"),
        }

    def hls_playlist(self, start_timestamp: float, end_timestamp: float) -> str:
        if end_timestamp <= start_timestamp:
            raise ValueError("end time must be after start time")
        selected: list[tuple[Path, datetime]] = []
        for path in self._segments():
            started = self._segment_time(path)
            if started.timestamp() < end_timestamp and started.timestamp() + self.segment_seconds > start_timestamp:
                selected.append((path, started))
        if not selected:
            raise ValueError("no recordings in the selected time range")

        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{self.segment_seconds + 1}",
            "#EXT-X-PLAYLIST-TYPE:VOD",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-INDEPENDENT-SEGMENTS",
        ]
        for path, started in selected:
            lines.append(f"#EXT-X-PROGRAM-DATE-TIME:{started.isoformat(timespec='milliseconds')}")
            lines.append(f"#EXTINF:{self.segment_seconds:.3f},")
            lines.append(f"/segments/{path.name}")
        lines.append("#EXT-X-ENDLIST")
        return "\n".join(lines) + "\n"

    def cleanup(self) -> int:
        cutoff = time.time() - self.settings.retention_days * 86400
        deleted = 0
        paths = list(self.storage.glob("recording-*.mp4")) + list(self.storage.glob("segment-*.ts"))
        for path in paths:
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    deleted += 1
            except FileNotFoundError:
                pass
        self._last_cleanup_at = time.monotonic()
        return deleted

    def _run(self) -> None:
        self.cleanup()
        while not self._stop.is_set():
            try:
                frame = self._frames.get(timeout=1)
            except queue.Empty:
                self._maybe_cleanup()
                continue
            if frame is None:
                break
            if self._process is None or self._process.poll() is not None:
                self._start_encoder()
            if self._process is None or self._process.stdin is None:
                continue
            try:
                self._process.stdin.write(frame)
                self._process.stdin.flush()
                self._error = None
            except (BrokenPipeError, OSError) as error:
                self._error = f"recorder encoder stopped: {error}"
                self._close_encoder()
            self._maybe_cleanup()
        self._close_encoder()

    def _start_encoder(self) -> None:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        output = str(self.storage / "segment-%Y%m%d-%H%M%S.ts")
        keyframe_expression = f"expr:gte(t,n_forced*{self.segment_seconds})"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "mjpeg",
            "-framerate",
            str(self.fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-b:v",
            f"{self.bitrate_kbps}k",
            "-maxrate",
            f"{int(self.bitrate_kbps * 1.2)}k",
            "-bufsize",
            f"{self.bitrate_kbps * 2}k",
            "-pix_fmt",
            "yuv420p",
            "-force_key_frames",
            keyframe_expression,
            "-f",
            "segment",
            "-segment_time",
            str(self.segment_seconds),
            "-segment_format",
            "mpegts",
            "-segment_format_options",
            "mpegts_flags=+resend_headers",
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
            output,
        ]
        try:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE)
        except OSError as error:
            self._process = None
            self._error = f"could not start recorder: {error}"

    def _close_encoder(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.terminate()

    def _maybe_cleanup(self) -> None:
        if time.monotonic() - self._last_cleanup_at >= 300:
            self.cleanup()

    def _segments(self) -> list[Path]:
        files = sorted(self.storage.glob("segment-*.ts"), key=self._segment_time)
        return [path for path in files if time.time() - path.stat().st_mtime >= 2]

    @staticmethod
    def _segment_time(path: Path) -> datetime:
        value = path.stem.removeprefix("segment-")
        return datetime.strptime(value, "%Y%m%d-%H%M%S").astimezone()
