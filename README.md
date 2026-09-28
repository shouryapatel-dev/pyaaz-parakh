# Pyaaz Parakh — AI Onion Quality Grading

Smart India Hackathon 2026 · Problem statement **SIH26031** (Department of Consumer Affairs).

A mobile web app that makes onion grading at procurement centres objective and recorded:

1. **Lot scan** – photograph a spread-out sample next to a printed size marker. A YOLO model
   (trained on ~2,600 labelled onion images) finds every bulb and flags **rotten / mould**,
   **damaged** (split, peeled, misshapen), **sprouted** and **undersized** (measured in mm) bulbs.
2. **Cut test** – photograph cut sample onions to catch **internal rot** invisible from outside.
3. **Result** – Grade A % and URS %, verdict, and an instant **PDF report** with photos, GPS,
   timestamp, SHA-256 fingerprint and a QR code for verification.

## Stack
- Frontend: installable PWA (plain HTML/CSS/JS), camera capture
- Backend: FastAPI, OpenCV (ArUco size calibration, GrabCut shape check, colour analysis), ReportLab
- Model: YOLO26-small trained and hosted on Roboflow

## Run locally
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
# put ROBOFLOW_API_KEY=... in .env
.venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
Grading thresholds are in `backend/config.py`.

## Deploy (Render, free)
Render dashboard → **New → Blueprint** → select this repo → enter `ROBOFLOW_API_KEY` → Apply.
