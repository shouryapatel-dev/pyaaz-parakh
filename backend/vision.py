"""Classical computer-vision helpers: size calibration and cut-surface analysis."""
import cv2
import numpy as np

from . import config

_DICT = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, config.MARKER_DICT))
_DETECTOR = cv2.aruco.ArucoDetector(_DICT, cv2.aruco.DetectorParameters())


def decode(image_bytes: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not read image")
    return img


def normalize(image_bytes: bytes, max_side: int = 1600) -> bytes:
    """Downscale large phone photos so uploads/inference stay fast."""
    img = decode(image_bytes)
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()


def find_marker(img: np.ndarray) -> dict | None:
    """Locate the printed ArUco marker; returns mm-per-pixel and its corners."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = _DETECTOR.detectMarkers(gray)
    if ids is None:
        return None
    # Prefer our marker id, otherwise take whatever 4x4 marker was found
    idx = next((i for i, v in enumerate(ids.flatten()) if v == config.MARKER_ID), 0)
    pts = corners[idx].reshape(4, 2)
    side_px = np.mean([np.linalg.norm(pts[i] - pts[(i + 1) % 4]) for i in range(4)])
    return {
        "mm_per_px": float(config.MARKER_SIZE_MM / side_px),
        "corners": pts.round(1).tolist(),
    }


def marker_png(side_px: int = 600) -> bytes:
    m = cv2.aruco.generateImageMarker(_DICT, config.MARKER_ID, side_px)
    return cv2.imencode(".png", m)[1].tobytes()


def green_shoots(img: np.ndarray, min_frac: float = 0.00012) -> list[dict]:
    """Find green sprout shoots. Onion bulbs are never saturated green, so a
    green blob touching a bulb means it has sprouted. The detector misses
    sprouts in crowded heaps; colour does not."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hue, sat, val = cv2.split(hsv)
    mask = ((hue >= 36) & (hue <= 90) & (sat >= 90) & (val >= 50)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    min_area = img.shape[0] * img.shape[1] * min_frac
    return [
        {"x1": float(x), "y1": float(y), "x2": float(x + w), "y2": float(y + h)}
        for x, y, w, h, area in stats[1:]
        if area >= min_area
    ]


def shape_stats(img: np.ndarray, box) -> dict | None:
    """Outline one bulb (GrabCut inside its box) and measure how regular it is.
    solidity    = area / convex-hull area  (dents, lumps, crush marks lower it)
    ellipse_fit = overlap of outline with its best-fit ellipse (odd shapes lower it)
    Returns None when the outline cannot be trusted."""
    H, W = img.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    X1, Y1 = int(max(0, x1 - 0.08 * bw)), int(max(0, y1 - 0.08 * bh))
    X2, Y2 = int(min(W, x2 + 0.08 * bw)), int(min(H, y2 + 0.08 * bh))
    crop = img[Y1:Y2, X1:X2]
    if crop.size == 0:
        return None
    s = 128 / max(crop.shape[:2])
    crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    rect = (int((x1 - X1) * s) + 1, int((y1 - Y1) * s) + 1, max(2, int(bw * s) - 2), max(2, int(bh * s) - 2))
    mask = np.zeros(crop.shape[:2], np.uint8)
    try:
        cv2.grabCut(crop, mask, rect, np.zeros((1, 65)), np.zeros((1, 65)), 4, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if len(c) < 5 or area < 0.5 * rect[2] * rect[3]:  # segmentation failed
        return None
    solidity = area / max(1.0, cv2.contourArea(cv2.convexHull(c)))
    ell, own = np.zeros_like(fg), np.zeros_like(fg)
    cv2.ellipse(ell, cv2.fitEllipse(c), 255, -1)
    cv2.drawContours(own, [c], -1, 255, -1)
    fit = ((ell > 0) & (own > 0)).sum() / max(1, ((ell > 0) | (own > 0)).sum())
    return {"solidity": round(float(solidity), 3), "ellipse_fit": round(float(fit), 3)}


def dark_area_ratio(img: np.ndarray, cx: float, cy: float, r: float) -> float:
    """Share of rotten-looking (dark / brown / black) pixels on the cut face.
    The circle is placed by the user; we skip its outer rim (skin edge)."""
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.circle(mask, (int(cx), int(cy)), max(1, int(r * 0.85)), 255, -1)
    inside = mask > 0
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    dark = (val < 70) | ((hue >= 5) & (hue <= 25) & (sat > 110) & (val < 150))
    return float((dark & inside).sum()) / max(1, int(inside.sum()))
