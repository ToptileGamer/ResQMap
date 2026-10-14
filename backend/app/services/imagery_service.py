from __future__ import annotations

import base64
import io
import logging
import zlib
from typing import NamedTuple

import numpy as np
from PIL import Image, ImageEnhance, ImageDraw

from app.models import DisasterZone

logger = logging.getLogger("resqmap.imagery")

MAX_PREVIEW = 560
MAX_MASK = 360


class AerialResult(NamedTuple):
    method: str
    flood_affected_pct: float
    damage_score: float
    image_width: int
    image_height: int
    preview_base64: str
    mask_base64: str


def _to_base64(image: Image.Image, max_side: int, quality: int = 82) -> str:
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _water_mask(arr: np.ndarray) -> np.ndarray:
    """Estimate flooded area by colour segmentation.

    Flood water in aerial shots is typically low-saturation dark/brown or
    blue-dominant. Returns a boolean mask of water-like pixels.
    """
    rgb = arr.astype(np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    val = mx / 255.0

    # Muddy / grey / dark standing water.
    muddy = (val > 0.12) & (val < 0.88) & (sat < 0.38) & ((b - r) < 30)
    # Bright blue/turquoise open water.
    blueish = (b > r + 8) & (b > g) & (val > 0.20) & (val < 0.95)
    # Deep shadow-blue pools.
    dark_blue = (val < 0.35) & (sat < 0.30) & (b >= r)

    return (muddy | blueish | dark_blue)


def _mask_overlay(arr: np.ndarray, mask: np.ndarray) -> Image.Image:
    """Render the detection mask as a cyan overlay on the original frame."""
    img = Image.fromarray(arr.astype(np.uint8)).convert("RGB")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    ys, xs = np.where(mask)
    step = max(1, len(xs) // 40000)
    points = list(zip(xs[::step].tolist(), ys[::step].tolist()))
    if points:
        draw.point(points, fill=(0, 255, 235, 160))
    combined = Image.alpha_composite(overlay, img.convert("RGBA")).convert("RGB")
    return combined


def mask_to_geojson(mask: np.ndarray, center_lat: float, center_lng: float,
                    extent_deg: float = 0.10, patch_rows: int = 14, patch_cols: int = 14) -> dict:
    """Vectorise the detection mask into a GeoJSON polygon layer.

    The mask is down-sampled onto a coarse patch grid and each (mostly-)wet
    patch becomes a rectangle. Patches flooded together in a row are merged
    into a single polygon so the layer stays light for the map. The mask is
    georeferenced to a small geographic extent centred on the zone.
    """
    h, w = mask.shape
    rows = np.linspace(0, h, patch_rows + 1).astype(int)
    cols = np.linspace(0, w, patch_cols + 1).astype(int)
    wet = np.zeros((patch_rows, patch_cols), dtype=bool)
    for r in range(patch_rows):
        for c in range(patch_cols):
            patch = mask[rows[r]:rows[r + 1], cols[c]:cols[c + 1]]
            if patch.size and float(np.mean(patch)) > 0.45:
                wet[r, c] = True

    half_lat = extent_deg / 2
    half_lng = extent_deg / 2 * 0.9  # lng degrees are shorter in km
    cell_lat = extent_deg / patch_rows
    cell_lng = (extent_deg * 0.9) / patch_cols

    features = []
    for r in range(patch_rows):
        c = 0
        while c < patch_cols:
            if not wet[r, c]:
                c += 1
                continue
            c_end = c
            while c_end + 1 < patch_cols and wet[r, c_end + 1]:
                c_end += 1
            lat_top = center_lat + half_lat - r * cell_lat
            lat_bottom = lat_top - cell_lat
            lng_left = center_lng - half_lng + c * cell_lng
            lng_right = center_lng - half_lng + (c_end + 1) * cell_lng
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [round(lng_left, 6), round(lat_bottom, 6)],
                        [round(lng_right, 6), round(lat_bottom, 6)],
                        [round(lng_right, 6), round(lat_top, 6)],
                        [round(lng_left, 6), round(lat_top, 6)],
                        [round(lng_left, 6), round(lat_bottom, 6)],
                    ]],
                },
                "properties": {"flooded": True},
            })
            c = c_end + 1

    return {
        "type": "FeatureCollection",
        "features": features,
        "extent_deg": extent_deg,
        "center": {"lat": center_lat, "lng": center_lng},
    }


def analyze_image(image_bytes: bytes) -> AerialResult:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.asarray(image)
    mask = _water_mask(arr)
    flood_pct = float(np.mean(mask) * 100.0)
    damage = float(np.clip(flood_pct * 0.85 + 5.0, 0, 100))

    preview = _to_base64(image, MAX_PREVIEW)
    mask_img = _mask_overlay(arr, mask)
    mask_b64 = _to_base64(mask_img, MAX_MASK)

    return AerialResult(
        method="color_segmentation",
        flood_affected_pct=round(flood_pct, 1),
        damage_score=round(damage, 1),
        image_width=image.width,
        image_height=image.height,
        preview_base64=preview,
        mask_base64=mask_b64,
    )


def _seeded_rng(zone: DisasterZone) -> np.random.Generator:
    seed = zlib.crc32(zone.id.encode("utf-8")) & 0xFFFFFFFF
    return np.random.default_rng(seed)


def generate_synthetic_frame(zone: DisasterZone) -> bytes:
    """Simulate a drone frame whose flooded fraction tracks the zone severity."""
    rng = _seeded_rng(zone)
    target = np.clip(zone.flood_severity + rng.normal(0, 6), 5, 95)
    side = 512

    land = np.array([152, 138, 112], dtype=np.float32)  # dry earth
    water = np.array([78, 96, 108], dtype=np.float32)  # flooded water
    green = np.array([96, 132, 88], dtype=np.float32)  # vegetation

    frame = np.empty((side, side, 3), dtype=np.float32)
    # Distance from centre -> pond-like water body plus scattered pooling.
    grid = np.mgrid[:side, :side].astype(np.float32)
    dist = np.sqrt((grid[0] - side / 2) ** 2 + (grid[1] - side * 0.62) ** 2) / (side * 0.45)
    prob = np.clip(1.35 - dist * 1.15 + rng.normal(0, 0.42, (side, side)), 0, 1) * (target / 100.0)
    prob += rng.normal(0, 0.10, (side, side)) * (target / 100.0)
    water_region = prob > np.clip(rng.uniform(0.15, 0.35), 0, 1)

    veg = rng.uniform(0, 1, (side, side)) > 0.72
    for i in range(3):
        base = land[i]
        frame[..., i] = np.where(veg, green[i], base)
    frame = np.where(water_region[..., None], water[None, None, :], frame)

    noise = rng.normal(0, 4, (side, side, 3))
    frame = np.clip(frame + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(frame).convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.15)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def analyze_zone_frame(zone: DisasterZone, provided_bytes: bytes | None) -> AerialResult:
    if provided_bytes:
        return analyze_image(provided_bytes)
    synthetic = generate_synthetic_frame(zone)
    return analyze_image(synthetic)


def analyze_zone_frame_with_geojson(zone: DisasterZone, provided_bytes: bytes | None) -> tuple[AerialResult, dict]:
    """Run the aerial analysis and also vectorise the flood mask as GeoJSON."""
    result, mask = _analyze_with_mask(zone, provided_bytes)
    geojson = mask_to_geojson(mask, zone.latitude, zone.longitude)
    return result, geojson


def _analyze_with_mask(zone: DisasterZone, provided_bytes: bytes | None) -> tuple[AerialResult, np.ndarray]:
    if provided_bytes:
        image = Image.open(io.BytesIO(provided_bytes)).convert("RGB")
        arr = np.asarray(image)
        mask = _water_mask(arr)
        return AerialResult(
            method="color_segmentation",
            flood_affected_pct=round(float(np.mean(mask) * 100.0), 1),
            damage_score=round(float(np.clip(np.mean(mask) * 100.0 * 0.85 + 5.0, 0, 100)), 1),
            image_width=image.width,
            image_height=image.height,
            preview_base64=_to_base64(image, MAX_PREVIEW),
            mask_base64=_to_base64(_mask_overlay(arr, mask), MAX_MASK),
        ), mask
    synthetic = generate_synthetic_frame(zone)
    image = Image.open(io.BytesIO(synthetic)).convert("RGB")
    arr = np.asarray(image)
    mask = _water_mask(arr)
    result = analyze_image(synthetic)
    return result, mask