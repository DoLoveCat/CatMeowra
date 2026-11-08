from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


class CatDetector:
    """Run cat detection off the capture thread and expose stable recent boxes."""

    def __init__(
        self,
        model_path: Path,
        emoji_path: Path,
        confidence: float = 0.12,
        interval_seconds: float = 0.5,
        image_size: int = 960,
        inference_rotation: str = "ccw",
    ) -> None:
        self.model_path = model_path
        self.confidence = confidence
        self.interval_seconds = interval_seconds
        self.image_size = image_size
        self.inference_rotation = inference_rotation
        self._emoji = cv2.imread(str(emoji_path), cv2.IMREAD_UNCHANGED)
        self._frames: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._boxes: list[tuple[int, int, int, int, float]] = []
        self._misses = 0
        self._ready = False
        self._error: str | None = None
        self._last_submit_at = 0.0
        self._last_seen: str | None = None
        self._inference_ms: int | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="cat-detector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._frames.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=5)

    def submit(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        if not self._ready or now - self._last_submit_at < self.interval_seconds:
            return
        self._last_submit_at = now
        try:
            self._frames.put_nowait(frame.copy())
        except queue.Full:
            pass

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        with self._lock:
            boxes = list(self._boxes)
        if not boxes:
            return frame

        height, width = frame.shape[:2]
        for x1, y1, x2, y2, confidence in boxes:
            x1, x2 = max(0, x1), min(width - 1, x2)
            y1, y2 = max(0, y1), min(height - 1, y2)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (40, 230, 70), 4, cv2.LINE_AA)
            self._draw_emoji(frame, x1, max(0, y1 - 58), 48)
            label = f"{confidence:.0%}"
            cv2.putText(
                frame,
                label,
                (min(width - 70, x1 + 52), max(32, y1 - 18)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (40, 230, 70),
                2,
                cv2.LINE_AA,
            )
        return frame

    def status(self) -> dict[str, object]:
        with self._lock:
            boxes = list(self._boxes)
            return {
                "cat_present": bool(boxes),
                "cat_count": len(boxes),
                "cat_confidence": round(max((box[4] for box in boxes), default=0.0), 3),
                "cat_last_seen": self._last_seen,
                "detector_ready": self._ready,
                "detector_error": self._error,
                "detector_inference_ms": self._inference_ms,
            }

    def _run(self) -> None:
        try:
            model_reference = str(self.model_path if self.model_path.exists() else self.model_path.name)
            model = YOLO(model_reference)
            with self._lock:
                self._ready = True
                self._error = None
        except Exception as error:
            with self._lock:
                self._error = f"model load failed: {error}"
            return

        while not self._stop.is_set():
            try:
                frame = self._frames.get(timeout=1)
            except queue.Empty:
                continue
            if frame is None:
                break
            started = time.perf_counter()
            try:
                inference_frame = self._rotate_for_inference(frame)
                result = model.predict(
                    inference_frame,
                    classes=[15],
                    conf=self.confidence,
                    imgsz=self.image_size,
                    verbose=False,
                    device="cpu",
                )[0]
                boxes = []
                for box in result.boxes:
                    x1, y1, x2, y2 = (int(value) for value in box.xyxy[0])
                    x1, y1, x2, y2 = self._map_box_to_source(frame, x1, y1, x2, y2)
                    boxes.append((x1, y1, x2, y2, float(box.conf[0])))
                with self._lock:
                    self._inference_ms = round((time.perf_counter() - started) * 1000)
                    self._error = None
                    if boxes:
                        self._boxes = boxes
                        self._misses = 0
                        self._last_seen = datetime.now().astimezone().isoformat(timespec="seconds")
                    else:
                        self._misses += 1
                        if self._misses >= 3:
                            self._boxes = []
            except Exception as error:
                with self._lock:
                    self._error = f"detection failed: {error}"

    def _draw_emoji(self, frame: np.ndarray, x: int, y: int, size: int) -> None:
        if self._emoji is None or self._emoji.shape[2] != 4:
            cv2.putText(frame, "CAT", (x, y + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (40, 230, 70), 2)
            return
        emoji = cv2.resize(self._emoji, (size, size), interpolation=cv2.INTER_AREA)
        x2, y2 = min(frame.shape[1], x + size), min(frame.shape[0], y + size)
        if x2 <= x or y2 <= y:
            return
        emoji = emoji[: y2 - y, : x2 - x]
        alpha = emoji[:, :, 3:4].astype(np.float32) / 255.0
        frame[y:y2, x:x2] = (
            emoji[:, :, :3].astype(np.float32) * alpha
            + frame[y:y2, x:x2].astype(np.float32) * (1.0 - alpha)
        ).astype(np.uint8)

    def _rotate_for_inference(self, frame: np.ndarray) -> np.ndarray:
        rotations = {
            "cw": cv2.ROTATE_90_CLOCKWISE,
            "ccw": cv2.ROTATE_90_COUNTERCLOCKWISE,
            "180": cv2.ROTATE_180,
        }
        return cv2.rotate(frame, rotations[self.inference_rotation]) if self.inference_rotation in rotations else frame

    def _map_box_to_source(
        self,
        frame: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
    ) -> tuple[int, int, int, int]:
        height, width = frame.shape[:2]
        if self.inference_rotation == "ccw":
            return width - 1 - y2, x1, width - 1 - y1, x2
        if self.inference_rotation == "cw":
            return y1, height - 1 - x2, y2, height - 1 - x1
        if self.inference_rotation == "180":
            return width - 1 - x2, height - 1 - y2, width - 1 - x1, height - 1 - y1
        return x1, y1, x2, y2
