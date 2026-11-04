// Tableau de bord : filtres, meilleur choix, courbe, tableau croisé, options de vol.
let D = null;
let chart = null;
let tableLimit = 300;
let sortKey = "d", sortDir = -1;
const $ = (id) => document.getElementById(id);
const F = () => ({
  trip: $("f-trip").value, combo: $("f-combo").value, mode: $("f-mode").value,
  airline: $("f-airline").value, tFrom: $("f-tfrom").value, tTo: $("f-tto").value,
  dFrom: $("f-dfrom").value, dTo: $("f-dto").value,
});
const MODE_FR = { round_trip: "Aller-retour", one_way: "Aller simple", return_detail: "Retour (détail A/R)" };
const LEVELS = ["normal", "allers simples un jour sur deux", "allers simples un jour sur deux, sans détail du retour",
  "seulement les meilleures combinaisons", "rationnement (budget insuffisant)"];

function trip() { return D.trips.find((t) => t.id === F().trip); }

// ---------------------------------------------------------------- filtres
function fillSelect(el, items, keep) {
  const prev = keep ? el.value : null;
  el.innerHTML = items.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
  if (prev && items.some(([v]) => v === prev)) el.value = prev;
}
function setupFilters() {
  fillSelect($("f-trip"), D.trips.map((t) => [t.id, t.name]));
  $("f-trip").addEventListener("change", () => { refreshTripFilters(); render(); });
  for (const id of ["f-combo", "f-mode", "f-airline", "f-tfrom", "f-tto", "f-dfrom", "f-dto"]) {
    $(id).addEventListener("change", () => { tableLimit = 300; render(); });
  }
  $("f-reset").addEventListener("click", () => {
    for (const id of ["f-tfrom", "f-tto", "f-dfrom", "f-dto"]) $(id).value = "";
    $("f-combo").value = "all"; $("f-mode").value = "all"; $("f-airline").value = "all";
    render();
  });
  refreshTripFilters();
}
function refreshTripFilters() {
  const t = trip();
  fillSelect($("f-combo"), [["all", "Toutes"], ...t.combinations.map((c) => [c, comboLabel(c)])]);
  const airlines = new Set();
  D.flights.filter((f) => f.t === t.id).forEach((f) => f.al.split(" + ").forEach((a) => airlines.add(a)));
  fillSelect($("f-airline"), [["all", "Toutes"], ...[...airlines].sort().map((a) => [a, a])]);
}

function flightPasses(f, flt) {
  if (f.t !== flt.trip) return false;
  if (flt.dFrom && f.d < flt.dFrom) return false;
  if (flt.dTo && f.d > flt.dTo) return false;
  if (flt.airline !== "all" && !f.al.split(" + ").includes(flt.airline)) return false;
  if ((flt.tFrom || flt.tTo) && f.dir === "aller") {
    const hm = (f.dt || "").slice(11, 16);
    if (flt.tFrom && hm < flt.tFrom) return false;
    if (flt.tTo && hm > flt.tTo) return false;
  }
  return true;
}

// Prix par (combinaison, jour) en tenant compte de tous les filtres.
function computeValues(flt, t) {
  const rt = {}, owOut = {}, owRet = {};
  const put = (obj, k, d, p) => { obj[k] ??= {}; if (obj[k][d] === undefined || p < obj[k][d]) obj[k][d] = p; };
  for (const f of D.flights) {
    if (f.p == null || !flightPasses(f, flt)) continue;
    if (f.m === "round_trip") put(rt, f.c, f.d, f.p);
    else if (f.m === "one_way" && f.dir === "aller") put(owOut, f.o, f.d, f.p);
    else if (f.m === "one_way" && f.dir === "retour") put(owRet, f.o, f.d, f.p);
  }
  const combos = flt.combo === "all" ? t.combinations : [flt.combo];
  const days = new Set();
  const values = {};
  for (const c of combos) {
    const [o, r] = c.split("_");
    values[c] = {};
    const allDays = new Set([...Object.keys(rt[c] || {}), ...Object.keys(owOut[o] || {})]);
    for (const d of allDays) {
      const cands = [];
      if (flt.mode !== "ow" && rt[c]?.[d] != null) cands.push({ p: rt[c][d], mode: "Aller-retour" });
      if (flt.mode !== "rt" && owOut[o]?.[d] != null && owRet[r]?.[d] != null)
        cands.push({ p: owOut[o][d] + owRet[r][d], mode: "Deux allers simples" });
      if (cands.length) { values[c][d] = cands.reduce((a, b) => (b.p < a.p ? b : a)); days.add(d); }
    }
  }
  return { values, days: [...days].sort(), combos };
}

// ---------------------------------------------------------------- carte « meilleur choix »
function renderBest(t) {
  const b = t.best, v = t.verdict;
  const cls = { "Acheter": "acheter", "Surveiller": "surveiller", "Attendre": "attendre", "Acheté": "achete", "Terminé": "attendre" }[v.label];
  const icon = { "Acheter": "✔", "Surveiller": "◐", "Attendre": "⏸", "Acheté": "★", "Terminé": "■" }[v.label];
  if (!b) {
    $("best").innerHTML = `<h2>Meilleur choix actuel</h2><div class="empty">Aucun prix relevé pour l'instant.</div>`;
    return;
  }
  const legs = b.legs.map((l) => `<div class="leg"><strong>${l.direction === "aller" ? "Aller" : "Retour"}</strong> ·
      ${esc(l.airlines)} ${esc(l.flight_numbers)}<br>
      <span class="small">${esc(l.departure_airport)} ${esc((l.departure_time || "").slice(0, 16))} →
      ${esc(l.arrival_airport)} ${esc((l.arrival_time || "").slice(11, 16))}${b.mode === "allers_simples" ? " · " + money(l.price, t.currency) : ""}</span></div>`).join("");
  $("best").innerHTML = `
    <h2>Meilleur choix actuel <span class="muted small">(relevé du ${fmtDate(b.date)}, sans filtre)</span></h2>
    <div class="price">${money(b.price, t.currency)}</div>
    <div>${b.mode === "allers_simples" ? "Deux allers simples" : "Aller-retour"} · ${comboLabel(b.combination)}</div>
    <div><span class="badge ${cls}">${icon} ${v.label}</span> <span class="small">${esc(v.reason)}</span></div>
    <div class="small muted">Prix cible : ${b.target != null ? money(b.target, t.currency) : "—"}
      ${t.target_price === "auto" ? "(auto : bas de la fourchette typique de Google)" : "(fixe)"}
      · fourchette typique : ${money(b.typical_low, t.currency)} – ${money(b.typical_high, t.currency)}
      · minimum observé : ${money(t.min_observed, t.currency)}</div>
    <div class="legs">${legs || '<span class="small muted">Détail des vols indisponible.</span>'}</div>`;
}

function renderQuota() {
  const u = D.usage || {};
  if (!u.cap) { $("quota").innerHTML = `<h2>Quota SerpApi</h2><div class="empty">Pas encore de lancement.</div>`; return; }
  const pctUsed = Math.min(100, (u.used / u.cap) * 100);
  const lvl = u.projection ? u.projection.level : 0;
  $("quota").innerHTML = `<h2>Quota SerpApi</h2>
    <div style="font-size:26px;font-weight:700">${u.used} <span class="muted" style="font-size:15px">/ ${u.cap} recherches</span></div>
    <div class="meter ${pctUsed > 90 ? "warn" : ""}"><div style="width:${pctUsed}%"></div></div>
    <p class="small">Cycle du ${fmtDate(u.cycle_start)} au ${fmtDate(u.cycle_end)} (exclu)<br>
      Renouvellement : ${esc(u.anchor_source || "")}<br>
      Mode : <strong>${LEVELS[lvl]}</strong><br>
      ${u.projection ? `Projection jusqu'au renouvellement : ${u.projection.projected} recherches` : ""}
      ${u.account_used != null ? `<br>Compteur SerpApi réel : ${u.account_used}` : ""}</p>`;
}

// ---------------------------------------------------------------- courbe
const deadlinePlugin = {
  id: "deadline",
  afterDatasetsDraw(c, _a, opts) {
    if (opts.index < 0) return;
    const x = c.scales.x.getPixelForValue(opts.index);
    const { top, bottom } = c.chartArea;
    const ctx = c.ctx;
    ctx.save();
    ctx.strokeStyle = css("--critical"); ctx.lineWidth = 1.5; ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
    ctx.setLineDash([]); ctx.fillStyle = css("--text-2"); ctx.font = "12px system-ui";
    ctx.textAlign = x > c.chartArea.right - 80 ? "right" : "left";
    ctx.fillText("Date limite", x + (ctx.textAlign === "right" ? -4 : 4), top + 12);
    ctx.restore();
  },
};

function renderChart(t, flt, vals) {
  chartDefaults();
  const series = SERIES();
  const allDays = vals.days;
  if (chart) { chart.destroy(); chart = null; }
  if (!allDays.length) { $("chart").parentElement.dataset.empty = "1"; }
  const first = allDays[0] || D.today;
  let last = allDays[allDays.length - 1] || D.today;
  if (t.deadline > last && t.deadline <= addDays(last, 30)) last = t.deadline;
  const labels = dateRange(first, last);
  const ds = [];
  if (flt.combo !== "all") {
    const rows = D.searches.filter((s) => s.t === t.id && s.m === "round_trip" && s.c === flt.combo && s.tl != null);
    const lo = {}, hi = {};
    rows.forEach((s) => { lo[s.d] = s.tl; hi[s.d] = s.th; });
    ds.push({ label: "Fourchette typique (bas)", data: labels.map((d) => lo[d] ?? null), borderWidth: 0, pointRadius: 0, spanGaps: true, fill: false, isBand: true });
    ds.push({ label: "Fourchette typique Google", data: labels.map((d) => hi[d] ?? null), borderWidth: 0, pointRadius: 0, spanGaps: true, fill: "-1", backgroundColor: css("--band"), isBand: true });
  }
  vals.combos.forEach((c) => {
    const color = series[t.combinations.indexOf(c) % 8];
    ds.push({ label: comboLabel(c), data: labels.map((d) => vals.values[c][d]?.p ?? null), borderColor: color, backgroundColor: color,
      borderWidth: 2, pointRadius: 3, pointHoverRadius: 6, spanGaps: true, tension: 0.2 });
  });
  if (vals.combos.length > 1) {
    const mins = labels.map((d) => {
      const ps = vals.combos.map((c) => vals.values[c][d]?.p).filter((p) => p != null);
      return ps.length ? Math.min(...ps) : null;
    });
    ds.push({ label: "Minimum du jour", data: mins, borderColor: css("--text"), borderDash: [6, 4], borderWidth: 2, pointRadius: 0, spanGaps: true });
  }
  $("chart-title").textContent = flt.combo === "all" ? "Évolution du prix — toutes les combinaisons" : `Évolution du prix — ${comboLabel(flt.combo)}`;
  chart = new Chart($("chart"), {
    type: "line",
    data: { labels, datasets: ds },
    plugins: [deadlinePlugin],
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { callback: (v) => fmtDate(labels[v]), maxRotation: 0, autoSkipPadding: 12 }, grid: { display: false } },
        y: { ticks: { callback: (v) => money(v, t.currency) }, grid: { color: css("--grid") } },
      },
      plugins: {
        deadline: { index: labels.indexOf(t.deadline) },
        legend: { position: "bottom", labels: { boxWidth: 12, filter: (it, data) => !data.datasets[it.datasetIndex].isBand || it.text === "Fourchette typique Google" } },
        tooltip: {
          callbacks: {
            title: (items) => fmtDate(labels[items[0].dataIndex]),
            label: (it) => {
              if (it.dataset.label === "Fourchette typique (bas)") return null;
              if (it.dataset.label === "Fourchette typique Google") {
                const lo = it.chart.data.datasets[0].data[it.dataIndex];
                return `Fourchette typique : ${money(lo, t.currency)} – ${money(it.raw, t.currency)}`;
              }
              return `${it.dataset.label} : ${money(it.raw, t.currency)}`;
            },
          },
        },
      },
    },
  });
}

// ---------------------------------------------------------------- tableau croisé
function renderHeat(t, vals) {
  if (!vals.days.length) { $("heat").innerHTML = `<div class="empty">Aucune donnée pour ces filtres.</div>`; return; }
  const all = vals.combos.flatMap((c) => Object.values(vals.values[c]).map((v) => v.p));
  const mn = Math.min(...all), mx = Math.max(...all);
  const lo = css("--seq-lo"), hi = css("--seq-hi");
  const mix = (a, b, k) => {
    const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16)), pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
    return pa.map((x, i) => Math.round(x + (pb[i] - x) * k));
  };
  const dark = document.documentElement.getAttribute("data-theme") === "dark" ||
    (!document.documentElement.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
  const rows = [...vals.days].reverse().map((d) => {
    const cells = vals.combos.map((c) => {
      const v = vals.values[c][d];
      if (!v) return `<td class="cell muted">—</td>`;
      const k = mx > mn ? (v.p - mn) / (mx - mn) : 0;
      const [r, g, b] = mix(lo, hi, k);
      const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
      const best = v.p === mn ? " ★" : "";
      return `<td class="cell" style="background:rgb(${r},${g},${b});color:${lum > 0.55 ? "#0b0b0b" : "#ffffff"}"
        title="${esc(comboLabel(c))} · ${esc(v.mode)} · ${money(v.p, t.currency)}">${money(v.p, t.currency)}${best}</td>`;
    }).join("");
    return `<tr><th>${fmtDate(d)}</th>${cells}</tr>`;
  }).join("");
  $("heat").innerHTML = `<table class="heat"><thead><tr><th>Recherche</th>${vals.combos.map((c) => `<th>${esc(comboLabel(c))}</th>`).join("")}</tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="small muted">Plus la case est ${dark ? "claire" : "foncée"}, plus le prix est élevé. ★ = prix le plus bas du tableau.</p>`;
}

// ---------------------------------------------------------------- tableau des options
const COLS = [
  ["d", "Recherche"], ["m", "Mode"], ["dir", "Sens"], ["c", "Dates"], ["al", "Compagnie"], ["fn", "Vol(s)"],
  ["dt", "Départ"], ["at", "Arrivée"], ["dur", "Durée", true], ["pl", "Avion"], ["fare", "Tarif / bagage"], ["p", "Prix", true],
];
function renderTable(t, flt) {
  let rows = D.flights.filter((f) => flightPasses(f, flt));
  if (flt.combo !== "all") {
    const [o, r] = flt.combo.split("_");
    rows = rows.filter((f) => f.c === flt.combo || (f.m === "one_way" && ((f.dir === "aller" && f.o === o) || (f.dir === "retour" && f.o === r))));
  }
  if (flt.mode === "rt") rows = rows.filter((f) => f.m !== "one_way");
  if (flt.mode === "ow") rows = rows.filter((f) => f.m === "one_way");
  rows.sort((a, b) => {
    const x = a[sortKey] ?? "", y = b[sortKey] ?? "";
    return (x < y ? -1 : x > y ? 1 : 0) * sortDir;
  });
  $("tbl-count").textContent = `(${rows.length})`;
  const shown = rows.slice(0, tableLimit);
  $("tbl-more").hidden = rows.length <= tableLimit;
  const head = COLS.map(([k, l, num]) => `<th class="sortable ${num ? "num" : ""}" data-k="${k}">${l}${sortKey === k ? (sortDir > 0 ? " ▲" : " ▼") : ""}</th>`).join("");
  const body = shown.map((f) => `<tr>
    <td>${fmtDate(f.d)}</td><td>${MODE_FR[f.m] || f.m}</td><td>${esc(f.dir)}</td>
    <td>${esc(f.c ? comboLabel(f.c) : fmtDate(f.o))}</td><td>${esc(f.al)}</td><td>${esc(f.fn)}</td>
    <td>${esc((f.dt || "").slice(5, 16))}</td><td>${esc((f.at || "").slice(5, 16))}</td>
    <td class="num">${f.dur ? `${Math.floor(f.dur / 60)} h ${String(f.dur % 60).padStart(2, "0")}` : ""}</td>
    <td>${esc(f.pl)}</td><td title="${esc(f.ext)}">${esc(f.fare)}</td>
    <td class="num"><strong>${money(f.p, t.currency)}</strong></td></tr>`).join("");
  $("tbl").innerHTML = rows.length ? `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>` : `<div class="empty">Aucune option pour ces filtres.</div>`;
  $("tbl").querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.k;
    if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = k === "p" || k === "dur" ? 1 : -1; }
    renderTable(t, F());
  }));
}

function renderSuggestions(t) {
  const list = D.suggestions.filter((s) => s.trip_id === t.id);
  $("sugg").innerHTML = list.length
    ? `<ul class="sugg">${list.map((s) => `<li>${esc(s.text)}</li>`).join("")}</ul>
       <p class="small muted">Rien n'est exclu automatiquement : c'est toi qui décides, dans trips.yaml.</p>`
    : `<p class="small muted">Aucune suggestion pour l'instant (il faut quelques jours de données).</p>`;
}

// ---------------------------------------------------------------- rendu global
function render() {
  const t = trip(), flt = F();
  const purchase = t.purchase && t.purchase.price ? ` · acheté ${money(t.purchase.price, t.currency)} le ${esc(t.purchase.date || "?")}` : "";
  $("trip-info").textContent = `${t.origin} → ${t.destination} · statut : ${t.status} · date limite : ${fmtDate(t.deadline)} ` +
    `(${t.days_to_deadline >= 0 ? `dans ${t.days_to_deadline} j` : "passée"})${purchase}` +
    (t.excluded.length ? ` · ${t.excluded.length} combinaison(s) exclue(s)` : "");
  const vals = computeValues(flt, t);
  renderBest(t);
  renderQuota();
  renderChart(t, flt, vals);
  renderHeat(t, vals);
  renderSuggestions(t);
  renderTable(t, flt);
}

(async () => {
  try {
    D = await loadData();
  } catch (e) {
    document.querySelector("main").innerHTML = `<div class="card empty">Pas encore de données : lance une première collecte (voir le README).</div>`;
    return;
  }
  if (!D.trips.length) { document.querySelector("main").innerHTML = `<div class="card empty">Aucun voyage dans trips.yaml.</div>`; return; }
  $("generated").textContent = `Données générées le ${new Date(D.generated_at).toLocaleString("fr-CA")}.`;
  setupThemeButton(() => render());
  $("tbl-more").addEventListener("click", () => { tableLimit = Infinity; renderTable(trip(), F()); });
  setupFilters();
  render();
})();
