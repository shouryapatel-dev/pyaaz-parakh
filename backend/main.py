"""FastAPI app: scan endpoints, lot reports, verification and the web app."""
import hashlib
import html
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, grading, report, vision
from .roboflow_client import InferenceError, detect

IST = timezone(timedelta(hours=5, minutes=30))
app = FastAPI(title="Onion Grading API")


@app.middleware("http")
async def no_stale_app(request: Request, call_next):
    """Make phones re-check the app files so updates show up on refresh."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _new_id(prefix):
    return f"{prefix}-{datetime.now(IST):%Y%m%d}-{secrets.token_hex(3).upper()}"


def _load_scan(scan_id):
    path = config.UPLOAD_DIR / f"{scan_id}.json"
    if not scan_id.replace("-", "").isalnum() or not path.exists():
        raise HTTPException(404, f"Scan {scan_id} not found")
    return json.loads(path.read_text())


async def _store_image(file: UploadFile, prefix):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty image")
    try:
        data = vision.normalize(raw)
    except ValueError:
        raise HTTPException(400, "Unsupported image file")
    scan_id = _new_id(prefix)
    (config.UPLOAD_DIR / f"{scan_id}.jpg").write_bytes(data)
    return scan_id, data


def _detect(data):
    try:
        return detect(data)
    except InferenceError as e:
        raise HTTPException(502, str(e))


@app.post("/api/scan/lot")
async def scan_lot(image: UploadFile = File(...)):
    """Grade every visible bulb in a photo of the spread-out sample."""
    scan_id, data = await _store_image(image, "LS")
    img = vision.decode(data)
    marker = vision.find_marker(img)
    bulbs, summary = grading.grade_lot(_detect(data), marker, img)
    scan = {"scan_id": scan_id, "width": img.shape[1], "height": img.shape[0],
            "marker": marker, "bulbs": bulbs, "summary": summary}
    (config.UPLOAD_DIR / f"{scan_id}.json").write_text(json.dumps(scan))
    return scan


@app.post("/api/scan/cut")
async def scan_cut(image: UploadFile = File(...), cx: float = Form(0.5), cy: float = Form(0.5),
                   r: float = Form(0.35)):
    """Cut-test one sample onion. cx, cy are 0-1 fractions of width/height,
    r is a fraction of the shorter image side."""
    scan_id, data = await _store_image(image, "CS")
    img = vision.decode(data)
    h, w = img.shape[:2]
    circle = (cx * w, cy * h, r * min(w, h))
    sample = grading.grade_cut(_detect(data), img, circle)
    scan = {"scan_id": scan_id, "width": w, "height": h, **sample}
    (config.UPLOAD_DIR / f"{scan_id}.json").write_text(json.dumps(scan))
    return scan


class LotIn(BaseModel):
    info: dict = {}
    lot_scan_ids: list[str]
    cut_scan_ids: list[str] = []
    location: dict | None = None


@app.post("/api/lots")
def create_lot(body: LotIn):
    if not body.lot_scan_ids:
        raise HTTPException(400, "At least one lot photo is required")
    lot_scans = [_load_scan(s) for s in body.lot_scan_ids]
    cut_samples = [_load_scan(s) for s in body.cut_scan_ids]

    bulbs = [b for s in lot_scans for b in s["bulbs"]]
    summary = grading.summarize(bulbs, size_measured=all(s["marker"] for s in lot_scans))
    final = grading.combine(summary, cut_samples)

    info = {k: str(v)[:120] for k, v in body.info.items() if v not in (None, "")}
    lot = {
        "id": _new_id("ONI"),
        "created_at": datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "info": info,
        "location": body.location,
        "lot_scans": lot_scans,
        "cut_samples": cut_samples,
        "summary": summary,
        "final": final,
    }
    # Fingerprint = results + every photo, so any edit is detectable
    h = hashlib.sha256(json.dumps(lot, sort_keys=True).encode())
    for s in lot_scans + cut_samples:
        h.update((config.UPLOAD_DIR / f"{s['scan_id']}.jpg").read_bytes())
    lot["hash"] = h.hexdigest()
    db.save_lot(lot)
    return lot


@app.get("/api/lots")
def lots():
    return db.list_lots()


def _get_lot(lot_id):
    lot = db.get_lot(lot_id)
    if not lot:
        raise HTTPException(404, "Report not found")
    return lot


@app.get("/api/lots/{lot_id}")
def lot_detail(lot_id: str):
    return _get_lot(lot_id)


@app.get("/api/lots/{lot_id}/report.pdf")
def lot_pdf(lot_id: str, request: Request):
    lot = _get_lot(lot_id)
    verify_url = str(request.base_url).rstrip("/") + f"/verify/{lot_id}"
    pdf = report.lot_report_pdf(lot, verify_url)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{lot_id}.pdf"'})


@app.get("/api/scan/{scan_id}/image")
def scan_image(scan_id: str):
    _load_scan(scan_id)  # validates id
    return FileResponse(config.UPLOAD_DIR / f"{scan_id}.jpg", media_type="image/jpeg")


@app.get("/api/mat.pdf")
def mat_pdf():
    return Response(report.grading_mat_pdf(), media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="grading-mat.pdf"'})


@app.get("/api/config")
def public_config():
    return {"min_diameter_mm": config.MIN_DIAMETER_MM, "grade_a_min_pct": config.GRADE_A_MIN_PERCENT,
            "marker_mm": config.MARKER_SIZE_MM, "model": config.MODEL_ID}


@app.get("/verify/{lot_id}", response_class=HTMLResponse)
def verify(lot_id: str):
    lot = db.get_lot(lot_id)
    e = html.escape
    if not lot:
        body = "<h2 style='color:#c0392b'>&#10007; No such report</h2><p>This report ID is not in the system.</p>"
    else:
        f, i = lot["final"], lot["info"]
        body = (f"<h2 style='color:#1f9d55'>&#10003; Genuine report</h2>"
                f"<p><b>{e(lot['id'])}</b><br>{e(lot['created_at'])}</p>"
                f"<p>Farmer: {e(i.get('farmer', '-'))}<br>Centre: {e(i.get('centre', '-'))}</p>"
                f"<p style='font-size:1.3em'>Grade A <b>{f['grade_a_pct']}%</b> &middot; URS <b>{f['urs_pct']}%</b>"
                f"<br>{e(f['verdict'])}</p>"
                f"<p style='font-size:.75em;word-break:break-all;color:#666'>Fingerprint: {e(lot['hash'])}</p>"
                f"<p><a href='/api/lots/{e(lot['id'])}/report.pdf'>Open full report (PDF)</a></p>")
    return (f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Verify report</title><body style='font-family:system-ui;max-width:480px;margin:40px auto;"
            f"padding:0 16px'><p style='color:#666'>Onion Quality Report Verification</p>{body}</body>")


# The web app (must be mounted last so /api routes take priority)
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
