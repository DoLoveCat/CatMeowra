# CatMeowra

CatMeowra turns a USB camera into a private, local-first cat monitor. It provides a live browser view, real-time cat detection, rolling H.264 recordings, and seamless timeline playback without requiring a cloud account.

The web interface automatically uses Chinese when the browser language starts with `zh`; all other browsers use English.

## Features

- Live MJPEG camera view with persistent rotation controls
- YOLO-powered cat detection with a green bounding box and 🐱 marker
- H.264/HLS rolling recording with configurable retention
- Start/end time selection and seamless timeline seeking
- Quick playback ranges for the last 1, 6, or 24 hours
- Automatic deletion of recordings older than the retention period
- Responsive bilingual interface (English and Chinese)
- Local-first defaults: the server only listens on `127.0.0.1`

## Requirements

- Python 3.10 or newer
- A UVC-compatible USB camera
- Windows, macOS, or Linux
- Approximately 27 GB per day with the default recording profile

The first run downloads the selected Ultralytics model (about 6 MB). FFmpeg is supplied by `imageio-ffmpeg`.

## Installation

```bash
git clone https://github.com/DoLoveCat/CatMeowra.git
cd CatMeowra
python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install CatMeowra and its dependencies in editable mode:

```bash
python -m pip install -e .
```

Create a personal configuration file:

```powershell
# Windows PowerShell
Copy-Item config.example.json config.json
```

```bash
# macOS / Linux
cp config.example.json config.json
```

Review `config.json`, connect the camera, then start CatMeowra:

```bash
python -m catmeowra --config config.json
```

Open <http://localhost:8000>.

## Configuration

`config.json` is intentionally ignored by Git. The committed `config.example.json` documents every supported setting.

| Setting | Purpose | Default |
|---|---|---:|
| `server.host` | Bind address | `127.0.0.1` |
| `server.port` | HTTP port | `8000` |
| `camera.index` | OpenCV camera index | `0` |
| `camera.backend` | `auto`, `any`, `msmf`, or `dshow` | `auto` |
| `camera.width` / `height` | Requested capture size | `1280 × 960` |
| `camera.rotation` | `none`, `cw`, `ccw`, or `180` | `ccw` |
| `recording.storage_directory` | Recording directory | `storage` |
| `recording.retention_days` | Initial retention period | `5` |
| `recording.fps` | Recording frame rate | `15` |
| `recording.bitrate_kbps` | H.264 target bitrate | `2500` |
| `recording.segment_seconds` | HLS segment length | `10` |
| `detection.model` | Ultralytics model filename/path | `yolo11n.pt` |
| `detection.confidence` | Minimum cat confidence | `0.12` |
| `detection.image_size` | Inference resolution | `960` |
| `detection.inference_rotation` | Rotation applied only during inference | `ccw` |

Changing retention in the web interface writes `settings.json`. That runtime value takes precedence over `recording.retention_days` and is also ignored by Git.

## Storage and playback

The default profile records at approximately 2.5 Mbps:

- roughly 23–27 GB per day;
- roughly 117–135 GB for five days.

Recordings are independent MPEG-TS segments served through a generated HLS playlist. The browser can therefore seek across a selected time range without opening each file manually. Cleanup runs automatically and removes files older than the configured retention period.

## Privacy and remote access

CatMeowra has no authentication layer. Keep the default `127.0.0.1` binding unless access is protected by a private network such as Tailscale. Do not expose the HTTP port directly to the public internet.

Recordings, snapshots, model weights, local settings, and virtual environments are excluded from Git by default.

## Troubleshooting

### The camera is not found

Try another camera index in `config.json`. On Windows, set `camera.backend` to `msmf` or `dshow`; on macOS/Linux, use `auto` or `any`.

### The image is sideways

Use the controls below the live view. The browser remembers the selected display rotation. Use `camera.rotation` for a permanent server-side correction and `detection.inference_rotation` when the detector needs a different orientation.

### Small or distant cats are missed

Lower `detection.confidence` carefully or increase `detection.image_size`. Lower confidence values improve sensitivity but can increase false positives.

## Third-party components

CatMeowra uses Ultralytics, hls.js, OpenCV, FFmpeg, and the Twemoji cat icon. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for project links and license information.

## License

CatMeowra is licensed under the [GNU Affero General Public License v3.0](LICENSE).
