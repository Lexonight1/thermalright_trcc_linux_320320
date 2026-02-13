"""FastAPI REST API — Driving adapter for headless/remote control.

Endpoints:
    GET  /health              — Server status
    GET  /devices             — List detected devices
    POST /devices/detect      — Rescan for devices
    POST /devices/{id}/select — Select a device
    POST /devices/{id}/send   — Send image to device LCD
    GET  /devices/{id}        — Get device details
    GET  /themes              — List available themes

Security:
    - Localhost-only by default (bind 127.0.0.1)
    - Optional token auth via --token flag (X-API-Token header)
    - 10 MB upload limit with PIL format validation
"""
from __future__ import annotations

import io
import logging

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel

from trcc.__version__ import __version__
from trcc.services import DeviceService, ImageService, ThemeService

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

app = FastAPI(title="TRCC Linux", version=__version__)

# ── Shared service instances ──────────────────────────────────────────

_device_svc = DeviceService()

# ── Token auth middleware (optional, enabled via --token) ─────────────

_api_token: str | None = None


def configure_auth(token: str | None) -> None:
    """Set the API token. Called by CLI serve command."""
    global _api_token  # noqa: PLW0603
    _api_token = token


@app.middleware("http")
async def check_token(request: Request, call_next):
    """Reject requests without valid token (if token is configured)."""
    if _api_token and request.url.path != "/health":
        if request.headers.get("X-API-Token") != _api_token:
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})
    return await call_next(request)


# ── Pydantic models ──────────────────────────────────────────────────

class DeviceResponse(BaseModel):
    id: int
    name: str
    vid: int
    pid: int
    protocol: str
    resolution: tuple[int, int]
    path: str


class ThemeResponse(BaseModel):
    name: str
    category: str
    is_animated: bool
    has_config: bool


# ── Helpers ───────────────────────────────────────────────────────────

def _device_to_response(idx: int, dev) -> DeviceResponse:
    return DeviceResponse(
        id=idx,
        name=dev.name,
        vid=dev.vid,
        pid=dev.pid,
        protocol=dev.protocol or "scsi",
        resolution=dev.resolution or (0, 0),
        path=dev.path or "",
    )


def _get_device_by_id(device_id: int):
    """Look up device by index, raise 404 if not found."""
    devices = _device_svc.devices
    if device_id < 0 or device_id >= len(devices):
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
    return devices[device_id]


# ── Endpoints ────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    """Health check (always accessible, no auth required)."""
    return {"status": "ok", "version": __version__}


@app.get("/devices")
def list_devices() -> list[DeviceResponse]:
    """List currently known devices."""
    return [_device_to_response(i, d) for i, d in enumerate(_device_svc.devices)]


@app.post("/devices/detect")
def detect_devices() -> list[DeviceResponse]:
    """Rescan USB for LCD devices."""
    _device_svc.detect()
    return [_device_to_response(i, d) for i, d in enumerate(_device_svc.devices)]


@app.post("/devices/{device_id}/select")
def select_device(device_id: int) -> dict:
    """Select a device by index."""
    dev = _get_device_by_id(device_id)
    _device_svc.select(dev)
    return {"selected": dev.name, "resolution": dev.resolution}


@app.get("/devices/{device_id}")
def get_device(device_id: int) -> DeviceResponse:
    """Get details for a specific device."""
    dev = _get_device_by_id(device_id)
    return _device_to_response(device_id, dev)


@app.post("/devices/{device_id}/send")
async def send_image(device_id: int, image: UploadFile, rotation: int = 0,
                     brightness: int = 100) -> dict:
    """Send an image to the device LCD.

    Accepts image file upload. Validates size and format before processing.
    """
    dev = _get_device_by_id(device_id)
    _device_svc.select(dev)

    # Read and validate upload
    data = await image.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds 10 MB limit")

    try:
        img = Image.open(io.BytesIO(data))
        img.load()  # Force decode to catch corrupt files
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image format")

    # Apply rotation and brightness
    if rotation:
        img = ImageService.apply_rotation(img, rotation)
    if brightness != 100:
        img = ImageService.apply_brightness(img, brightness)

    # Resize to device resolution
    w, h = dev.resolution or (320, 320)
    img = ImageService.resize(img, w, h)

    # Convert and send
    byte_order = ImageService.byte_order_for(
        dev.protocol or "scsi", (w, h)
    )
    rgb565 = ImageService.to_rgb565(img, byte_order)
    ok = _device_svc.send_rgb565(rgb565, w, h)

    if not ok:
        raise HTTPException(status_code=500, detail="Send failed (device busy or error)")

    return {"sent": True, "resolution": (w, h)}


@app.get("/themes")
def list_themes(resolution: str = "320x320") -> list[ThemeResponse]:
    """List available local themes for a given resolution."""
    try:
        parts = resolution.split("x")
        w, h = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid resolution format (use WxH)")

    from pathlib import Path

    from trcc.paths import get_theme_dir
    theme_dir = Path(get_theme_dir(w, h))
    themes = ThemeService.discover_local(theme_dir, (w, h))
    return [
        ThemeResponse(
            name=t.name,
            category=t.category or "",
            is_animated=t.is_animated,
            has_config=t.config_path is not None,
        )
        for t in themes
    ]
