"""PDF generation: the lot quality report and the printable grading mat."""
import io

import cv2
import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import config, vision
from .grading import CATEGORY_LABELS

# BGR colours for the photo overlay, hex for the PDF tables (same palette as the app)
CATEGORY_COLORS = {
    "grade_a": "#1f9d55",
    "rotten": "#c0392b",
    "damaged": "#d35400",
    "sprouted": "#8e44ad",
    "undersized": "#2471a3",
}
CUT_COLORS = {"healthy": "#1f9d55", "suspect": "#d4a017", "internal_rot": "#c0392b"}
CUT_LABELS = {"healthy": "Healthy", "suspect": "Suspect", "internal_rot": "Internal rot"}


def _bgr(hex_color):
    h = hex_color.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def annotate_lot(image_path, bulbs) -> bytes:
    img = cv2.imread(str(image_path))
    t = max(2, img.shape[1] // 400)
    for b in bulbs:
        x1, y1, x2, y2 = b["box"]
        c = _bgr(CATEGORY_COLORS[b["category"]])
        cv2.rectangle(img, (x1, y1), (x2, y2), c, t)
        label = f'{b["id"]} {CATEGORY_LABELS[b["category"]]}'
        if b["category"] == "damaged" and b.get("notes"):
            label += f' ({b["notes"][0]})'
        if b["diameter_mm"]:
            label += f' {b["diameter_mm"]:.0f}mm'
        fs = t * 0.35
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, max(1, t // 2))
        cv2.rectangle(img, (x1, y1), (x1 + tw + 6, y1 + th + 8), c, -1)
        cv2.putText(img, label, (x1 + 3, y1 + th + 4), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), max(1, t // 2))
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def annotate_cut(image_path, sample) -> bytes:
    """Square close-up of the cut face with the inspected circle drawn on."""
    img = cv2.imread(str(image_path))
    cx, cy, r = sample["circle"]
    cv2.circle(img, (cx, cy), r, _bgr(CUT_COLORS[sample["status"]]), max(3, r // 25))
    pad = int(r * 1.15)
    img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    crop = img[cy:cy + 2 * pad, cx:cx + 2 * pad]  # shifted by the border
    crop = cv2.resize(crop, (400, 400), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def _img(jpg_bytes, max_w, max_h):
    h, w = vision.decode(jpg_bytes).shape[:2]
    s = min(max_w / w, max_h / h)
    return Image(io.BytesIO(jpg_bytes), width=w * s, height=h * s)


def _table(rows, widths, header_bg="#3b2a4a"):
    t = Table(rows, colWidths=widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f3f8")]),
    ]))
    return t


def lot_report_pdf(lot: dict, verify_url: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Onion Quality Report {lot['id']}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=17, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8, textColor=colors.HexColor("#555555"))
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9)
    info, final, summ = lot["info"], lot["final"], lot["summary"]
    W = A4[0] - 30 * mm
    story = []

    # Header with QR
    qr = qrcode.make(verify_url, box_size=4, border=1)
    qbuf = io.BytesIO(); qr.save(qbuf, format="PNG"); qbuf.seek(0)
    head = Table([[
        [Paragraph("Onion Quality Assessment Report", h1),
         Paragraph(f"AI-assisted grading &middot; Report ID <b>{lot['id']}</b>", body),
         Paragraph(f"Generated {lot['created_at']}", small)],
        Image(qbuf, width=26 * mm, height=26 * mm),
    ]], colWidths=[W - 30 * mm, 30 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [head, Spacer(1, 4)]

    # Verdict banner
    vcol = "#1f9d55" if final["grade_a_pct"] >= config.GRADE_A_MIN_PERCENT else ("#d4a017" if final["grade_a_pct"] >= 70 else "#c0392b")
    banner = Table([[f"Grade A: {final['grade_a_pct']}%", f"URS: {final['urs_pct']}%", final["verdict"]]],
                   colWidths=[W * 0.25, W * 0.25, W * 0.5])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(vcol)),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [banner, Spacer(1, 6)]

    # Lot details
    loc = lot.get("location")
    loc_txt = f"{loc['lat']:.5f}, {loc['lon']:.5f} (&plusmn;{loc.get('accuracy') or 0:.0f} m)" if loc else "Not available"
    details = [
        ["Farmer", info.get("farmer") or "-", "Farmer ID", info.get("farmer_id") or "-"],
        ["Procurement centre", info.get("centre") or "-", "Officer", info.get("officer") or "-"],
        ["Lot weight (kg)", info.get("lot_weight_kg") or "-", "Variety", info.get("variety") or "-"],
        ["GPS location", Paragraph(loc_txt, body), "Timestamp", lot["created_at"]],
    ]
    t = Table(details, colWidths=[W * 0.2, W * 0.3, W * 0.17, W * 0.33])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f6f3f8")), ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f6f3f8")),
    ]))
    story += [Paragraph("Lot details", h2), t]

    # Sample composition
    story.append(Paragraph("External inspection (sample composition)", h2))
    rows = [["Category", "Bulbs", "Share"]]
    for k, label in CATEGORY_LABELS.items():
        n = summ["counts"][k]
        pct = f"{100 * n / summ['total']:.1f}%" if summ["total"] else "-"
        rows.append([Paragraph(f'<font color="{CATEGORY_COLORS[k]}">&#9632;</font> {label}', body), n, pct])
    rows.append(["Total bulbs inspected", summ["total"], "100%"])
    story.append(_table(rows, [W * 0.5, W * 0.25, W * 0.25]))
    size_note = (f"Size measured with calibration marker; undersized = diameter below {config.MIN_DIAMETER_MM:.0f} mm."
                 if summ["size_measured"] else "Size marker not detected - undersized check skipped.")
    story.append(Paragraph(size_note, small))

    # Cut test
    cuts = lot["cut_samples"]
    story.append(Paragraph("Internal inspection (cut test)", h2))
    if cuts:
        rows = [["Sample", "Dark / rotten area", "Model rot flag", "Result"]]
        for i, s in enumerate(cuts, 1):
            rows.append([f"Cut sample {i}", f"{s['dark_area_pct']}%", "Yes" if s["model_rot"] else "No",
                         Paragraph(f'<font color="{CUT_COLORS[s["status"]]}"><b>{CUT_LABELS[s["status"]]}</b></font>', body)])
        story.append(_table(rows, [W * 0.25] * 4))
        story.append(Paragraph(
            f"Internal rot found in {final['internal_rot_rate_pct']}% of cut samples; the externally-sound Grade A share "
            f"was reduced by this rate.", small))
    else:
        story.append(Paragraph("No cut test performed - internal defects not assessed.", body))

    # Photos
    story += [PageBreak(), Paragraph(f"Evidence photos &middot; {lot['id']}", h2)]
    def grid(cells, cols):
        rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
        rows[-1] += [""] * (cols - len(rows[-1]))
        t = Table(rows, colWidths=[W / cols] * cols)
        t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    scans = lot["lot_scans"]
    cols = 1 if len(scans) == 1 else 2
    lot_photos = [_img(annotate_lot(config.UPLOAD_DIR / f"{s['scan_id']}.jpg", s["bulbs"]), W / cols - 6,
                       (130 if cols == 1 else 95) * mm) for s in scans]
    story.append(grid(lot_photos, cols))
    if cuts:
        cut_cells = [[_img(annotate_cut(config.UPLOAD_DIR / f"{s['scan_id']}.jpg", s), W / 5, W / 5),
                      Paragraph(f"Cut sample {i}: {CUT_LABELS[s['status']]}", small)]
                     for i, s in enumerate(cuts, 1)]
        story.append(grid(cut_cells, 4))

    # Integrity
    story += [Spacer(1, 6), Paragraph(
        f"SHA-256 fingerprint of this report's data and photos:<br/><font name='Courier' size='7'>{lot['hash']}</font><br/>"
        f"Scan the QR code or visit {verify_url} to verify. Any change to the photos or results changes this fingerprint.",
        small),
        Paragraph(f"Grading thresholds: undersized &lt; {config.MIN_DIAMETER_MM:.0f} mm; lot accepted as Grade A (FAQ) if "
                  f"&ge; {config.GRADE_A_MIN_PERCENT:.0f}% bulbs are Grade A. AI result is decision support; the officer "
                  f"remains accountable for the final grade.", small)]
    doc.build(story)
    return buf.getvalue()


def grading_mat_pdf() -> bytes:
    """A4 sheet with the calibration marker printed at exactly MARKER_SIZE_MM."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm)
    ss = getSampleStyleSheet()
    marker = Image(io.BytesIO(vision.marker_png(800)), width=config.MARKER_SIZE_MM * mm,
                   height=config.MARKER_SIZE_MM * mm)
    doc.build([
        Paragraph("Onion Grading Mat - Size Calibration Marker", ss["Title"]),
        Paragraph(f"Print at <b>100% / Actual size</b> (no 'fit to page'). The black square must measure "
                  f"exactly <b>{config.MARKER_SIZE_MM:.0f} mm</b> per side - check with a ruler.", ss["Normal"]),
        Spacer(1, 20 * mm), marker, Spacer(1, 20 * mm),
        Paragraph("How to use: place this sheet flat next to the onions, keep the marker fully visible and "
                  "un-creased, and photograph from directly above (phone parallel to the table).", ss["Normal"]),
    ])
    return buf.getvalue()
