"""Thin wrapper around Roboflow's hosted inference API."""
import base64

import requests

from . import config


class InferenceError(RuntimeError):
    pass


def detect(image_bytes: bytes) -> list[dict]:
    """Return predictions as [{cls, conf, x1, y1, x2, y2}] in image pixels."""
    if not config.ROBOFLOW_API_KEY:
        raise InferenceError("ROBOFLOW_API_KEY missing in .env")
    resp = requests.post(
        f"{config.ROBOFLOW_URL}/{config.MODEL_ID}",
        params={
            "api_key": config.ROBOFLOW_API_KEY,
            "confidence": int(config.CONFIDENCE * 100),
            "overlap": int(config.OVERLAP * 100),
        },
        data=base64.b64encode(image_bytes),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=60,
    )
    if resp.status_code != 200:
        raise InferenceError(f"Roboflow error {resp.status_code}: {resp.text[:200]}")
    preds = []
    for p in resp.json().get("predictions", []):
        # Roboflow gives box centre + size
        preds.append({
            "cls": p["class"],
            "conf": round(p["confidence"], 3),
            "x1": p["x"] - p["width"] / 2,
            "y1": p["y"] - p["height"] / 2,
            "x2": p["x"] + p["width"] / 2,
            "y2": p["y"] + p["height"] / 2,
        })
    return preds
