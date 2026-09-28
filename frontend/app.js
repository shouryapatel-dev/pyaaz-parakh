// Pyaaz Parakh - single-page mobile app (no framework, no build step)

const CATS = {
  grade_a:    { label: "Grade A",    color: "#1f9d55" },
  rotten:     { label: "Rotten",     color: "#c0392b" },
  damaged:    { label: "Damaged",    color: "#d35400" },
  sprouted:   { label: "Sprouted",   color: "#8e44ad" },
  undersized: { label: "Undersized", color: "#2471a3" },
};
const CUT = {
  healthy:      { label: "Healthy",      color: "#1f9d55" },
  suspect:      { label: "Suspect",      color: "#d4a017" },
  internal_rot: { label: "Internal rot", color: "#c0392b" },
};

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- state ----------
let lot = null;       // current inspection
let cfg = { min_diameter_mm: 45, grade_a_min_pct: 90 };
const newLot = () => ({ info: {}, location: null, lotScans: [], cutScans: [] });

// ---------- helpers ----------
function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => (t.hidden = true), ms);
}
function busy(on, text = "Analysing…") { $("#busy").hidden = !on; $("#busyText").textContent = text; }

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

function loadImage(src) {
  return new Promise((ok, fail) => { const i = new Image(); i.onload = () => ok(i); i.onerror = fail; i.src = src; });
}

// ---------- navigation ----------
const history_ = [];
function show(view, push = true) {
  const cur = $("section.view:not([hidden])")?.dataset.view;
  if (push && cur && cur !== view) history_.push(cur);
  $$("section.view").forEach((s) => (s.hidden = s.dataset.view !== view));
  $("#backBtn").hidden = view === "home";
  window.scrollTo(0, 0);
  if (view === "history") renderHistory();
}
$("#backBtn").onclick = () => show(history_.pop() || "home", false);
document.addEventListener("click", (e) => {
  const go = e.target.closest("[data-go]");
  if (!go) return;
  if (go.dataset.go === "details") startInspection();
  show(go.dataset.go);
});

// ---------- home ----------
$("#legend").innerHTML = Object.values(CATS)
  .map((c) => `<span><i class="dot" style="background:${c.color}"></i>${c.label}</span>`).join("");
api("/api/config").then((c) => {
  cfg = c;
  $$("[data-cfg]").forEach((el) => (el.textContent = c[el.dataset.cfg]));
}).catch(() => {});

// ---------- step 1: details ----------
function startInspection() {
  lot = newLot();
  $("#detailsForm").reset();
  $("#lotScans").innerHTML = ""; $("#cutScans").innerHTML = "";
  $("#lotTotals").hidden = true; $("#toCut").disabled = true;
  const gps = $("#gpsStatus");
  if (!navigator.geolocation) { gps.textContent = "📍 Location not supported on this device"; return; }
  gps.textContent = "📍 Getting location…";
  navigator.geolocation.getCurrentPosition(
    (p) => {
      lot.location = { lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy };
      gps.textContent = `📍 Location captured (±${Math.round(p.coords.accuracy)} m)`;
    },
    () => (gps.textContent = "📍 Location unavailable (allow location access, or open via https)"),
    { enableHighAccuracy: true, timeout: 15000 }
  );
}
$("#detailsForm").onsubmit = (e) => {
  e.preventDefault();
  lot.info = Object.fromEntries(new FormData(e.target));
  show("lot");
};

// ---------- step 2: lot photos ----------
$$('input[data-scan]').forEach((inp) => inp.addEventListener("change", async () => {
  const file = inp.files[0]; inp.value = "";
  if (!file) return;
  if (inp.dataset.scan === "lot") await scanLot(file);
  else openCircleEditor(file);
}));

async function scanLot(file) {
  busy(true, "Detecting onions…");
  try {
    const fd = new FormData(); fd.append("image", file);
    const scan = await api("/api/scan/lot", { method: "POST", body: fd });
    lot.lotScans.push(scan);
    await renderLotScan(scan);
    renderTotals();
  } catch (err) {
    toast("Scan failed: " + err.message);
  } finally { busy(false); }
}

async function drawLot(canvas, scan) {
  const img = await loadImage(`/api/scan/${scan.scan_id}/image`);
  canvas.width = img.width; canvas.height = img.height;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(img, 0, 0);
  const t = Math.max(2, img.width / 350), fs = Math.max(12, img.width / 45);
  ctx.font = `600 ${fs}px system-ui`; ctx.lineWidth = t;
  for (const b of scan.bulbs) {
    const [x1, y1, x2, y2] = b.box, c = CATS[b.category];
    ctx.strokeStyle = c.color; ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    const why = b.category === "damaged" && b.notes?.length ? ` (${b.notes[0]})` : "";
    const label = `${b.id} ${c.label}${why}${b.diameter_mm ? " " + Math.round(b.diameter_mm) + "mm" : ""}`;
    const w = ctx.measureText(label).width + 8;
    ctx.fillStyle = c.color; ctx.fillRect(x1, y1, w, fs + 8);
    ctx.fillStyle = "#fff"; ctx.fillText(label, x1 + 4, y1 + fs + 1);
  }
  if (scan.marker) {
    const p = scan.marker.corners;
    ctx.strokeStyle = "#00bcd4"; ctx.lineWidth = t * 1.5; ctx.beginPath();
    p.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath(); ctx.stroke();
  }
}

async function renderLotScan(scan) {
  const el = document.createElement("div");
  el.className = "card scan";
  const s = scan.summary;
  const chips = Object.entries(s.counts).filter(([, n]) => n)
    .map(([k, n]) => `<span class="chip" style="background:${CATS[k].color}">${n} ${CATS[k].label}</span>`).join("");
  el.innerHTML = `
    <canvas></canvas>
    <div class="meta"><b>${s.total} onions found</b>
      <button class="link-btn">Remove</button></div>
    <div class="chips">${chips || '<span class="muted small">No onions detected</span>'}</div>
    ${s.warnings.length ? `<ul class="warn-list">${s.warnings.map((w) => `<li>⚠ ${esc(w)}</li>`).join("")}</ul>` : ""}`;
  $("#lotScans").appendChild(el);
  $(".link-btn", el).onclick = () => {
    lot.lotScans = lot.lotScans.filter((x) => x !== scan);
    el.remove(); renderTotals();
  };
  await drawLot($("canvas", el), scan);
}

function tally(scans) {
  const counts = Object.fromEntries(Object.keys(CATS).map((k) => [k, 0]));
  let total = 0;
  scans.forEach((s) => s.bulbs.forEach((b) => { counts[b.category]++; total++; }));
  return { counts, total, gradeA: total ? (100 * counts.grade_a) / total : 0 };
}

function renderTotals() {
  const box = $("#lotTotals");
  const { counts, total, gradeA } = tally(lot.lotScans);
  $("#toCut").disabled = total === 0;
  box.hidden = lot.lotScans.length === 0;
  if (box.hidden) return;
  const bars = Object.entries(counts).filter(([, n]) => n)
    .map(([k, n]) => `<div style="width:${(100 * n) / total}%;background:${CATS[k].color}" title="${CATS[k].label}"></div>`).join("");
  box.innerHTML = `
    <h3>Sample so far &middot; ${total} onions in ${lot.lotScans.length} photo(s)</h3>
    <div class="big-numbers">
      <div><b style="color:var(--good)">${gradeA.toFixed(1)}%</b><small>Grade A (external)</small></div>
      <div><b style="color:var(--bad)">${(total ? 100 - gradeA : 0).toFixed(1)}%</b><small>URS</small></div>
    </div>
    <div class="bars">${bars}</div>
    <p class="muted small">Add more photos of <i>different</i> onions to enlarge the sample, or continue.</p>`;
}
$("#toCut").onclick = () => show("cut");

// ---------- step 3: cut test ----------
const editor = { img: null, file: null, cx: 0.5, cy: 0.5, r: 0.35, drag: false };

async function openCircleEditor(file) {
  editor.file = file;
  editor.img = await loadImage(URL.createObjectURL(file));
  Object.assign(editor, { cx: 0.5, cy: 0.5, r: 0.35 });
  $("#circleSize").value = 0.35;
  $("#circleEditor").hidden = false;
  drawCircleEditor();
  $("#circleEditor").scrollIntoView({ behavior: "smooth" });
}

function drawCircleEditor() {
  const c = $("#circleCanvas"), img = editor.img;
  const scale = Math.min(1, 1000 / Math.max(img.width, img.height));
  c.width = img.width * scale; c.height = img.height * scale;
  const ctx = c.getContext("2d");
  ctx.drawImage(img, 0, 0, c.width, c.height);
  const x = editor.cx * c.width, y = editor.cy * c.height, r = editor.r * Math.min(c.width, c.height);
  // dim outside the circle
  ctx.save(); ctx.fillStyle = "rgba(0,0,0,.45)"; ctx.beginPath();
  ctx.rect(0, 0, c.width, c.height); ctx.arc(x, y, r, 0, Math.PI * 2, true); ctx.fill("evenodd"); ctx.restore();
  ctx.strokeStyle = "#fff"; ctx.lineWidth = 3; ctx.setLineDash([10, 6]);
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
}

(function circleDrag() {
  const c = $("#circleCanvas");
  const move = (e) => {
    const rect = c.getBoundingClientRect();
    editor.cx = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    editor.cy = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    drawCircleEditor();
  };
  c.addEventListener("pointerdown", (e) => { editor.drag = true; c.setPointerCapture(e.pointerId); move(e); });
  c.addEventListener("pointermove", (e) => editor.drag && move(e));
  c.addEventListener("pointerup", () => (editor.drag = false));
  $("#circleSize").addEventListener("input", (e) => { editor.r = +e.target.value; drawCircleEditor(); });
})();

$("#cancelCut").onclick = () => ($("#circleEditor").hidden = true);
$("#analyseCut").onclick = async () => {
  busy(true, "Checking cut face…");
  try {
    const fd = new FormData();
    fd.append("image", editor.file);
    fd.append("cx", editor.cx); fd.append("cy", editor.cy); fd.append("r", editor.r);
    const scan = await api("/api/scan/cut", { method: "POST", body: fd });
    lot.cutScans.push(scan);
    $("#circleEditor").hidden = true;
    await renderCutScan(scan);
  } catch (err) {
    toast("Cut test failed: " + err.message);
  } finally { busy(false); }
};

async function renderCutScan(scan) {
  const el = document.createElement("div");
  el.className = "cut-item";
  const s = CUT[scan.status];
  el.innerHTML = `<canvas></canvas><div><span><b style="color:${s.color}">${s.label}</b><br>
    <span class="muted">${scan.dark_area_pct}% dark area</span></span><button class="link-btn">✕</button></div>`;
  $("#cutScans").appendChild(el);
  $(".link-btn", el).onclick = () => { lot.cutScans = lot.cutScans.filter((x) => x !== scan); el.remove(); };
  const img = await loadImage(`/api/scan/${scan.scan_id}/image`);
  const [cx, cy, r] = scan.circle, pad = r * 1.15;
  const c = $("canvas", el); c.width = c.height = 300;
  const ctx = c.getContext("2d");
  ctx.drawImage(img, cx - pad, cy - pad, pad * 2, pad * 2, 0, 0, 300, 300);
  ctx.strokeStyle = s.color; ctx.lineWidth = 6;
  ctx.beginPath(); ctx.arc(150, 150, 150 * (r / pad), 0, Math.PI * 2); ctx.stroke();
}

$("#skipCut").onclick = () => { lot.cutScans = []; $("#cutScans").innerHTML = ""; finishLot(); };
$("#toResult").onclick = () => {
  if (!lot.cutScans.length && !confirm("No cut samples added. Continue without checking for internal rot?")) return;
  finishLot();
};

// ---------- step 4: result ----------
async function finishLot() {
  busy(true, "Generating report…");
  try {
    const res = await api("/api/lots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        info: lot.info,
        location: lot.location,
        lot_scan_ids: lot.lotScans.map((s) => s.scan_id),
        cut_scan_ids: lot.cutScans.map((s) => s.scan_id),
      }),
    });
    renderResult(res, $("#resultBox"));
    show("result");
  } catch (err) {
    toast("Could not create report: " + err.message);
  } finally { busy(false); }
}

function verdictColor(pct) {
  return pct >= cfg.grade_a_min_pct ? "var(--good)" : pct >= 70 ? "var(--warn)" : "var(--bad)";
}

function renderResult(r, box) {
  const f = r.final, s = r.summary;
  const rows = Object.entries(CATS).map(([k, c]) => `
    <tr><td><i class="dot" style="background:${c.color}"></i>${c.label}</td>
    <td>${s.counts[k]} &nbsp;(${s.total ? ((100 * s.counts[k]) / s.total).toFixed(1) : 0}%)</td></tr>`).join("");
  const pdf = `/api/lots/${encodeURIComponent(r.id)}/report.pdf`;
  const verify = `${location.origin}/verify/${encodeURIComponent(r.id)}`;
  box.innerHTML = `
    <div class="verdict" style="background:${verdictColor(f.grade_a_pct)}">
      <h2>${esc(f.verdict)}</h2>
      <div class="big-numbers">
        <div><b>${f.grade_a_pct}%</b><small>Grade A</small></div>
        <div><b>${f.urs_pct}%</b><small>URS</small></div>
      </div>
    </div>
    <div class="card">
      <h3>External inspection &middot; ${s.total} bulbs</h3>
      <table class="breakdown">${rows}</table>
      <p class="small muted">${f.cut_samples
        ? `Cut test: internal rot in ${f.internal_rot_rate_pct}% of ${f.cut_samples} sample(s); Grade A adjusted accordingly.`
        : "Cut test not performed."}</p>
      ${s.warnings.length ? `<ul class="warn-list">${s.warnings.map((w) => `<li>⚠ ${esc(w)}</li>`).join("")}</ul>` : ""}
    </div>
    <div class="card">
      <h3>Digital report</h3>
      <p class="report-id">${esc(r.id)}<br><span class="muted">${esc(r.created_at)}</span></p>
      <div class="actions">
        <a class="btn primary" href="${pdf}" target="_blank">📄 Open PDF report</a>
        <button class="btn" id="shareBtn">📤 Share with farmer</button>
        <a class="btn ghost" href="${verify}" target="_blank">Verify authenticity →</a>
      </div>
    </div>
    <button class="btn" data-go="home">Done</button>`;
  $("#shareBtn", box).onclick = async () => {
    const text = `Onion quality report ${r.id}: Grade A ${f.grade_a_pct}%, URS ${f.urs_pct}% – ${f.verdict}.`;
    const url = location.origin + pdf;
    if (navigator.share) {
      try { await navigator.share({ title: "Onion Quality Report", text, url }); } catch {}
    } else {
      window.open(`https://wa.me/?text=${encodeURIComponent(text + " " + url)}`, "_blank");
    }
  };
}

// ---------- history ----------
async function renderHistory() {
  const list = $("#historyList");
  list.innerHTML = '<p class="muted">Loading…</p>';
  try {
    const rows = await api("/api/lots");
    list.innerHTML = rows.length ? rows.map((r) => `
      <a class="history-item" href="/api/lots/${encodeURIComponent(r.id)}/report.pdf" target="_blank">
        <div><b>${esc(r.farmer || "Unnamed farmer")}</b><small>${esc(r.centre || "")} · ${esc(r.created_at)}</small>
          <small class="report-id">${esc(r.id)}</small></div>
        <span class="pill" style="background:${verdictColor(r.grade_a_pct)}">A ${r.grade_a_pct}%</span>
      </a>`).join("") : '<p class="muted">No reports yet.</p>';
  } catch (err) {
    list.innerHTML = `<p class="muted">Could not load: ${esc(err.message)}</p>`;
  }
}

if ("serviceWorker" in navigator && location.protocol === "https:") {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
