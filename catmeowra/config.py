from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8000},
    "camera": {
        "index": 0,
        "backend": "auto",
        "width": 1280,
        "height": 960,
        "rotation": "ccw",
        "jpeg_quality": 85,
    },
    "recording": {
        "storage_directory": "storage",
        "retention_days": 5,
        "fps": 15,
        "bitrate_kbps": 2500,
        "segment_seconds": 10,
    },
    "detection": {
        "model": "yolo11n.pt",
        "confidence": 0.12,
        "interval_seconds": 0.5,
        "image_size": 960,
        "inference_rotation": "ccw",
    },
}


def load_config(path: Path) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    if path.exists():
        user_config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(user_config, dict):
            raise ValueError("config root must be a JSON object")
        _merge(config, user_config)
    _validate(config)
    return config


def resolve_project_path(project_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_dir / path


def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if key not in target:
            raise ValueError(f"unknown config key: {key}")
        if isinstance(target[key], dict):
            if not isinstance(value, dict):
                raise ValueError(f"config section must be an object: {key}")
            _merge(target[key], value)
        else:
            target[key] = value


def _validate(config: dict[str, Any]) -> None:
    server = config["server"]
    camera = config["camera"]
    recording = config["recording"]
    detection = config["detection"]

    if not 1 <= int(server["port"]) <= 65535:
        raise ValueError("server.port must be between 1 and 65535")
    if camera["rotation"] not in {"none", "cw", "ccw", "180"}:
        raise ValueError("camera.rotation must be one of: none, cw, ccw, 180")
    if camera["backend"] not in {"auto", "any", "msmf", "dshow"}:
        raise ValueError("camera.backend must be one of: auto, any, msmf, dshow")
    if not 1 <= int(camera["jpeg_quality"]) <= 100:
        raise ValueError("camera.jpeg_quality must be between 1 and 100")
    if not 1 <= int(recording["retention_days"]) <= 365:
        raise ValueError("recording.retention_days must be between 1 and 365")
    if int(recording["fps"]) <= 0 or int(recording["segment_seconds"]) <= 0:
        raise ValueError("recording fps and segment_seconds must be positive")
    if not 0 < float(detection["confidence"]) <= 1:
        raise ValueError("detection.confidence must be between 0 and 1")
    if detection["inference_rotation"] not in {"none", "cw", "ccw", "180"}:
        raise ValueError("detection.inference_rotation must be one of: none, cw, ccw, 180")
