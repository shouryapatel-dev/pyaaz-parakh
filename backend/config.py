"""Central settings. Grading thresholds live here so the team can align them
with official AGMARK / NAFED norms without touching the logic."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "").strip()
MODEL_ID = os.getenv("MODEL_ID", "onion-vi5f2-91jdk/1")
ROBOFLOW_URL = "https://serverless.roboflow.com"
CONFIDENCE = float(os.getenv("CONFIDENCE", "0.35"))  # 0-1
OVERLAP = float(os.getenv("OVERLAP", "0.4"))

DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "onion.db"
FRONTEND_DIR = ROOT / "frontend"
for d in (UPLOAD_DIR, REPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# --- Grading rulebook (VERIFY against official NAFED / AGMARK specs) -------
MIN_DIAMETER_MM = 45.0         # bulbs below this are "undersized"
GRADE_A_MIN_PERCENT = 90.0     # lot is "Grade A (FAQ)" if >= this % bulbs are Grade A
SHAPE_MIN_SOLIDITY = 0.90     # below => dented / lumpy / crushed => "damaged"
SHAPE_MIN_ELLIPSE_FIT = 0.82  # below => misshapen outline => "damaged"
CUT_DARK_AREA_ROT = 0.12      # cut surface: > 12% dark/brown area => internal rot
CUT_DARK_AREA_SUSPECT = 0.05   # 5-12% => suspect

# --- Size calibration marker (printed on the grading mat) ------------------
MARKER_SIZE_MM = 50.0          # side of the printed ArUco square
MARKER_DICT = "DICT_4X4_50"
MARKER_ID = 7

# --- Mapping of model classes -> our categories ----------------------------
BULB_CLASSES = {"BrownOnion", "RedOnion", "WhiteOnion", "FullPeeled Onion", "HalfPeeled Onion"}
# Bulbs that lost their protective outer skin count as damaged
PEELED_CLASSES = {"FullPeeled Onion", "HalfPeeled Onion"}
CUT_CLASSES = {"HalfOnion"}
DEFECT_CLASSES = {
    "Rot": "rotten",
    "Mold": "rotten",
    "Sprout": "sprouted",
    "DoubleSplit": "damaged",
}
IGNORED_CLASSES = {"SpringOnion", "Onionpeel"}

# Priority when a bulb has several defects (worst first)
DEFECT_PRIORITY = ["rotten", "damaged", "sprouted", "undersized"]
