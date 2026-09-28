"""Turn raw detections into per-bulb grades and lot-level percentages."""
from . import config
from .vision import dark_area_ratio, green_shoots, shape_stats

CATEGORY_LABELS = {
    "grade_a": "Grade A",
    "rotten": "Rotten",
    "damaged": "Damaged",
    "sprouted": "Sprouted",
    "undersized": "Undersized",
}


def _area(b):
    return max(0.0, b["x2"] - b["x1"]) * max(0.0, b["y2"] - b["y1"])


def _inter(a, b):
    w = min(a["x2"], b["x2"]) - max(a["x1"], b["x1"])
    h = min(a["y2"], b["y2"]) - max(a["y1"], b["y1"])
    return max(0.0, w) * max(0.0, h)


def _iou(a, b):
    i = _inter(a, b)
    return i / max(1e-6, _area(a) + _area(b) - i)


def _dedupe(boxes, thr=0.6):
    """The model sometimes labels one bulb as both BrownOnion and WhiteOnion."""
    kept = []
    for b in sorted(boxes, key=lambda p: -p["conf"]):
        if all(_iou(b, k) < thr for k in kept):
            kept.append(b)
    return kept


def _attach_shoots(bulbs, shoots):
    """Mark the bulb each green shoot grows from as sprouted. Shoots often lie
    across neighbouring bulbs, so grow the box a little and pick the bulb
    with the biggest overlap."""
    for s in shoots:
        pad_x, pad_y = 0.3 * (s["x2"] - s["x1"]), 0.3 * (s["y2"] - s["y1"])
        grown = {"x1": s["x1"] - pad_x, "y1": s["y1"] - pad_y, "x2": s["x2"] + pad_x, "y2": s["y2"] + pad_y}
        host = max(bulbs, key=lambda b: _inter(b, grown), default=None)
        if host is not None and _inter(host, grown) > 0:
            host["defects"].add("sprouted")


def grade_lot(preds, marker, img):
    """Per-bulb grading for a spread-out lot photo."""
    bulbs = _dedupe([p for p in preds if p["cls"] in config.BULB_CLASSES])
    for b in bulbs:
        b["defects"], b["notes"] = set(), []
        if b["cls"] in config.PEELED_CLASSES:
            b["defects"].add("damaged")
            b["notes"].append("peeled")
    defects = [p for p in preds if p["cls"] in config.DEFECT_CLASSES]

    # A defect box either sits on a detected bulb (spot annotation) or covers
    # a bulb the model only saw as "Rot"/"Sprout" (whole-bulb annotation).
    for d in sorted(defects, key=lambda p: -p["conf"]):
        cat = config.DEFECT_CLASSES[d["cls"]]
        host = max(bulbs, key=lambda b: _inter(b, d), default=None)
        # A sprout pokes out of its bulb, so partial overlap is enough
        if host is None or _inter(host, d) / max(1e-6, _area(d)) < 0.3:
            host = {**d, "cls": "Onion", "defects": set(), "notes": []}
            bulbs.append(host)
        host["defects"].add(cat)
        if d["cls"] == "DoubleSplit":
            host["notes"].append("split/double")

    # The model tends to call a sprout "SpringOnion"; count both colour-found
    # shoots and those boxes as sprouts, but never as extra bulbs.
    shoots = green_shoots(img) + [p for p in preds if p["cls"] == "SpringOnion"]
    _attach_shoots(bulbs, shoots)
    shape_checked = _check_shapes(bulbs, img)

    mm_per_px = marker["mm_per_px"] if marker else None
    results = []
    for i, b in enumerate(sorted(bulbs, key=lambda b: (round(b["y1"] / 80), b["x1"])), 1):
        w, h = b["x2"] - b["x1"], b["y2"] - b["y1"]
        diameter = round(float(min(w, h) * mm_per_px), 1) if mm_per_px else None
        if diameter is not None and diameter < config.MIN_DIAMETER_MM:
            b["defects"].add("undersized")
        found = [c for c in config.DEFECT_PRIORITY if c in b["defects"]]
        results.append({
            "id": i,
            "box": [round(b["x1"]), round(b["y1"]), round(b["x2"]), round(b["y2"])],
            "variety": b["cls"],
            "conf": b["conf"],
            "diameter_mm": diameter,
            "defects": found,
            "notes": b["notes"],
            "shape": b.get("shape"),
            "category": found[0] if found else "grade_a",
        })
    summary = summarize(results, size_measured=mm_per_px is not None)
    summary["shape_checked"] = shape_checked
    return results, summary


def _check_shapes(bulbs, img):
    """Flag disfigured (dented, lumpy, crushed, misshapen) bulbs. The outline is
    only reliable for a bulb that is fully visible, so bulbs touching another
    bulb or the photo edge are skipped. Returns how many were checked."""
    h, w = img.shape[:2]
    checked = 0
    for b in bulbs:
        crowded = any(_inter(b, o) > 0.05 * _area(b) for o in bulbs if o is not b)
        at_edge = b["x1"] < 3 or b["y1"] < 3 or b["x2"] > w - 3 or b["y2"] > h - 3
        if crowded or at_edge:
            continue
        stats = shape_stats(img, (b["x1"], b["y1"], b["x2"], b["y2"]))
        if stats is None:
            continue
        checked += 1
        b["shape"] = stats
        if stats["solidity"] < config.SHAPE_MIN_SOLIDITY or stats["ellipse_fit"] < config.SHAPE_MIN_ELLIPSE_FIT:
            b["defects"].add("damaged")
            b["notes"].append("misshapen")
    return checked


def summarize(bulbs, size_measured):
    total = len(bulbs)
    counts = {k: 0 for k in CATEGORY_LABELS}
    for b in bulbs:
        counts[b["category"]] += 1
    grade_a_pct = round(100 * counts["grade_a"] / total, 1) if total else 0.0
    warnings = []
    if not size_measured:
        warnings.append("Size marker not found - undersized onions were not checked.")
    if 0 < total < 20:
        warnings.append(f"Only {total} onions in sample; use 20+ for a reliable lot grade.")
    if total == 0:
        warnings.append("No onions detected. Retake the photo from directly above in good light.")
    return {
        "total": total,
        "counts": counts,
        "grade_a_pct": grade_a_pct,
        "urs_pct": round(100 - grade_a_pct, 1) if total else 0.0,
        "size_measured": size_measured,
        "warnings": warnings,
    }


def grade_cut(preds, img, circle):
    """Inspect the cross-section of one sample onion for hidden (internal) rot.
    `circle` = (cx, cy, r) in pixels, placed by the officer over the cut face."""
    cx, cy, r = circle
    face = {"x1": cx - r, "y1": cy - r, "x2": cx + r, "y2": cy + r}
    model_rot = any(
        config.DEFECT_CLASSES.get(p["cls"]) == "rotten"
        and _inter(face, p) / max(1e-6, _area(p)) >= 0.5
        for p in preds
    )
    dark = dark_area_ratio(img, cx, cy, r)
    if model_rot or dark > config.CUT_DARK_AREA_ROT:
        status = "internal_rot"
    elif dark > config.CUT_DARK_AREA_SUSPECT:
        status = "suspect"
    else:
        status = "healthy"
    return {
        "circle": [round(cx), round(cy), round(r)],
        "dark_area_pct": round(dark * 100, 1),
        "model_rot": model_rot,
        "status": status,
    }


def combine(lot_summary, cut_samples):
    """Apply the cut-test internal-rot rate to the externally 'Grade A' share."""
    n = len(cut_samples)
    rot = sum(s["status"] == "internal_rot" for s in cut_samples)
    rate = rot / n if n else 0.0
    grade_a = round(lot_summary["grade_a_pct"] * (1 - rate), 1)
    total = lot_summary["total"]
    if total == 0:
        verdict = "No result"
    elif grade_a >= config.GRADE_A_MIN_PERCENT:
        verdict = "Grade A (FAQ) - Accept"
    elif grade_a >= 70:
        verdict = "Accept with URS deduction"
    else:
        verdict = "Reject / Re-sort lot"
    return {
        "grade_a_pct": grade_a if total else 0.0,
        "urs_pct": round(100 - grade_a, 1) if total else 0.0,
        "internal_rot_rate_pct": round(rate * 100, 1),
        "cut_samples": n,
        "verdict": verdict,
    }
