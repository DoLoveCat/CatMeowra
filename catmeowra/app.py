from __future__ import annotations

import argparse
import json
import os
import signal
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2

from .config import load_config, resolve_project_path
from .detector import CatDetector
from .recorder import Recorder, Settings


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
STATIC_DIR = PACKAGE_DIR / "static"
INDEX_HTML = (STATIC_DIR / "index.html").read_bytes()
HLS_JS = (STATIC_DIR / "vendor" / "hls.min.js").read_bytes()
I18N_JS = (STATIC_DIR / "i18n.js").read_bytes()


class Camera:
    """Read one camera continuously and share the latest JPEG with all clients."""

    def __init__(self, index: int, backend: str, width: int, height: int, quality: int, rotate: str, recorder: Recorder, detector: CatDetector) -> None:
        self.index = index
        self.backend = backend
        self.width = width
        self.height = height
        self.quality = quality
        self.rotate = rotate
        self.recorder = recorder
        self.detector = detector
        self._condition = threading.Condition()
        self._jpeg: bytes | None = None
        self._sequence = 0
        self._error: str | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._capture: cv2.VideoCapture | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        with self._condition:
            self._condition.notify_all()
        if self._thread:
            self._thread.join(timeout=3)
        if self._capture:
            self._capture.release()

    @property
    def status(self) -> tuple[bool, str]:
        with self._condition:
            if self._jpeg is not None:
                return True, "camera is streaming"
            return False, self._error or "waiting for camera"

    def wait_for_frame(self, previous_sequence: int, timeout: float = 5.0) -> tuple[int, bytes | None]:
        with self._condition:
            self._condition.wait_for(
                lambda: self._sequence != previous_sequence or not self._running,
                timeout=timeout,
            )
            return self._sequence, self._jpeg

    def latest_frame(self) -> bytes | None:
        with self._condition:
            return self._jpeg

    def _open(self) -> cv2.VideoCapture:
        backends = {
            "any": cv2.CAP_ANY,
            "msmf": cv2.CAP_MSMF,
            "dshow": cv2.CAP_DSHOW,
        }
        backend_name = self.backend
        if backend_name == "auto":
            backend_name = "msmf" if os.name == "nt" else "any"
        backend = backends[backend_name]
        capture = cv2.VideoCapture(self.index, backend)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        return capture

    def _capture_loop(self) -> None:
        while self._running:
            capture = self._open()
            self._capture = capture
            if not capture.isOpened():
                with self._condition:
                    self._error = f"camera {self.index} is not available; retrying"
                    self._condition.notify_all()
                capture.release()
                time.sleep(2)
                continue

            with self._condition:
                self._error = None

            while self._running and capture.isOpened():
                ok, frame = capture.read()
                if not ok:
                    with self._condition:
                        self._error = "camera frame read failed; reconnecting"
                    break

                if self.rotate == "cw":
                    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                elif self.rotate == "ccw":
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                elif self.rotate == "180":
                    frame = cv2.rotate(frame, cv2.ROTATE_180)

                self.detector.submit(frame)
                frame = self.detector.annotate(frame)
                encoded, buffer = cv2.imencode(
                    ".jpg",
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, self.quality],
                )
                if not encoded:
                    continue

                jpeg = buffer.tobytes()
                self.recorder.submit(jpeg)
                with self._condition:
                    self._jpeg = jpeg
                    self._sequence += 1
                    self._condition.notify_all()

            capture.release()
            self._capture = None
            if self._running:
                time.sleep(1)


class CameraHandler(BaseHTTPRequestHandler):
    camera: Camera
    recorder: Recorder
    detector: CatDetector

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send_bytes(INDEX_HTML, "text/html; charset=utf-8")
        elif path == "/hls.min.js":
            self._send_bytes(HLS_JS, "text/javascript; charset=utf-8")
        elif path == "/i18n.js":
            self._send_bytes(I18N_JS, "text/javascript; charset=utf-8")
        elif path == "/video_feed":
            self._stream_video()
        elif path == "/snapshot.jpg":
            frame = self.camera.latest_frame()
            if frame is None:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Camera is not ready")
            else:
                self._send_bytes(frame, "image/jpeg", no_cache=True)
        elif path == "/api/status":
            healthy, message = self.camera.status
            self._send_json(
                {"camera": healthy, "message": message, **self.recorder.status(), **self.detector.status()}
            )
        elif path == "/api/recordings":
            self._send_json({"recordings": self.recorder.list_recordings()})
        elif path == "/api/timeline":
            self._send_json(self.recorder.timeline())
        elif path == "/api/stream.m3u8":
            try:
                query = parse_qs(parsed.query)
                start = float(query["start"][0])
                end = float(query["end"][0])
                playlist = self.recorder.hls_playlist(start, end)
                self._send_bytes(
                    playlist.encode("utf-8"),
                    "application/vnd.apple.mpegurl; charset=utf-8",
                    no_cache=True,
                )
            except (KeyError, IndexError, ValueError) as error:
                self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif path.startswith("/recordings/"):
            recording = self.recorder.recording_path(path.removeprefix("/recordings/"))
            if recording is None:
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self._send_file(recording, "video/mp4")
        elif path.startswith("/segments/"):
            segment = self.recorder.segment_path(path.removeprefix("/segments/"))
            if segment is None:
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self._send_file(segment, "video/mp2t")
        elif path == "/health":
            healthy, message = self.camera.status
            body = ("ok: " if healthy else "error: ") + message
            self._send_bytes(
                body.encode(),
                "text/plain; charset=utf-8",
                status=HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE,
                no_cache=True,
            )
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/settings":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 4096)
            payload = json.loads(self.rfile.read(length) or b"{}")
            retention_days = int(payload["retention_days"])
            self.recorder.settings.set_retention_days(retention_days)
            deleted = self.recorder.cleanup()
            self._send_json({"ok": True, "retention_days": retention_days, "deleted": deleted})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self._send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {self.client_address[0]} {format % args}")

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
        no_cache: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if no_cache:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status=status,
            no_cache=True,
        )

    def _send_file(self, path: Path, content_type: str) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        response_status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            try:
                requested_start, requested_end = range_header[6:].split("-", 1)
                start = int(requested_start) if requested_start else 0
                end = int(requested_end) if requested_end else size - 1
                if start < 0 or end < start or start >= size:
                    raise ValueError
                end = min(end, size - 1)
                response_status = HTTPStatus.PARTIAL_CONTENT
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return

        self.send_response(response_status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if response_status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        with path.open("rb") as recording:
            recording.seek(start)
            remaining = end - start + 1
            try:
                while remaining:
                    chunk = recording.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def _stream_video(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        sequence = -1
        try:
            while True:
                sequence, frame = self.camera.wait_for_frame(sequence)
                if frame is None:
                    continue
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CatMeowra local camera server")
    parser.add_argument("--config", type=Path, default=PROJECT_DIR / "config.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    server_config = config["server"]
    camera_config = config["camera"]
    recording_config = config["recording"]
    detection_config = config["detection"]

    settings = Settings(PROJECT_DIR / "settings.json", int(recording_config["retention_days"]))
    storage = resolve_project_path(PROJECT_DIR, str(recording_config["storage_directory"]))
    recorder = Recorder(
        storage,
        settings,
        int(recording_config["fps"]),
        int(recording_config["bitrate_kbps"]),
        int(recording_config["segment_seconds"]),
    )
    detector = CatDetector(
        resolve_project_path(PROJECT_DIR, str(detection_config["model"])),
        STATIC_DIR / "images" / "cat_emoji.png",
        float(detection_config["confidence"]),
        float(detection_config["interval_seconds"]),
        int(detection_config["image_size"]),
        str(detection_config["inference_rotation"]),
    )
    camera = Camera(
        int(camera_config["index"]),
        str(camera_config["backend"]),
        int(camera_config["width"]),
        int(camera_config["height"]),
        int(camera_config["jpeg_quality"]),
        str(camera_config["rotation"]),
        recorder,
        detector,
    )
    CameraHandler.camera = camera
    CameraHandler.recorder = recorder
    CameraHandler.detector = detector
    server = ThreadingHTTPServer((str(server_config["host"]), int(server_config["port"])), CameraHandler)

    def shut_down(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shut_down)
    signal.signal(signal.SIGTERM, shut_down)

    recorder.start()
    detector.start()
    camera.start()
    print(f"CatMeowra is running at http://localhost:{server_config['port']}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        camera.stop()
        detector.stop()
        recorder.stop()


if __name__ == "__main__":
    main()
