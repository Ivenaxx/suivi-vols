// Page « Analyse » : croise tous les voyages.
const MIN_N = 20; // sous ce nombre d'observations, on considère que c'est trop peu pour conclure
let A = null;
const charts = {};

function barChart(id, rows) {
  chartDefaults();
  if (charts[id]) charts[id].destroy();
  const solid = css("--s1"), faint = css("--axis");
  charts[id] = new Chart(document.getElementById(id), {
    type: "bar",
    data: {
      labels: rows.map((r) => r.label),
      datasets: [{
        label: "Écart moyen au minimum (%)", data: rows.map((r) => r.mean_pct),
        backgroundColor: rows.map((r) => (r.n >= MIN_N ? solid : faint)),
        borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "bottom", maxBarThickness: 48,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      scales: { y: { beginAtZero: true, ticks: { callback: (v) => `${v} %` }, grid: { color: css("--grid") } }, x: { grid: { display: false } } },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (it) => {
          const r = rows[it.dataIndex];
          return [`Écart moyen : ${r.mean_pct} %`, `Écart médian : ${r.median_pct} %`, `n = ${r.n}${r.n < MIN_N ? " (trop peu)" : ""}`];
        } } },
      },
    },
  });
}

function statTable(id, rows, firstCol) {
  const el = document.getElementById(id);
  if (!rows.some((r) => r.n)) { el.innerHTML = `<div class="empty">Pas encore de données.</div>`; return; }
  el.innerHTML = `<table><thead><tr><th>${firstCol}</th><th class="num">Écart moyen</th><th class="num">Écart médian</th><th class="num">n</th><th></th></tr></thead><tbody>
    ${rows.map((r) => `<tr class="${r.n < MIN_N ? "muted" : ""}"><td>${esc(r.label)}</td>
      <td class="num">${r.mean_pct ?? "—"} %</td><td class="num">${r.median_pct ?? "—"} %</td><td class="num">${r.n}</td>
      <td class="small">${r.n && r.n < MIN_N ? "trop peu de données" : ""}</td></tr>`).join("")}</tbody></table>`;
}

function render() {
  const a = A.analysis;
  document.getElementById("min-n").textContent = `${MIN_N}`;
  document.getElementById("obs").textContent = `${a.observations} observations aller-retour au total, ${A.trips.length} voyage(s).`;
  barChart("c-days", a.by_days);
  statTable("t-days", a.by_days, "Jours avant le départ");
  const wd = a.by_weekday.filter((r) => r.n);
  barChart("c-wd", wd);
  statTable("t-wd", a.by_weekday, "Jour de la recherche");
  const paid = a.paid;
  document.getElementById("t-paid").innerHTML = paid.length
    ? `<table><thead><tr><th>Voyage</th><th>Date d'achat</th><th class="num">Prix payé</th><th class="num">Minimum observé</th><th class="num">Écart</th></tr></thead><tbody>
      ${paid.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.date || "")}</td><td class="num">${money(p.paid, p.currency)}</td>
        <td class="num">${money(p.min_observed, p.currency)}</td><td class="num">${p.pct_above_min != null ? p.pct_above_min + " %" : "—"}</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty">Aucun prix d'achat renseigné pour l'instant (voir le README).</div>`;
}

(async () => {
  try { A = await loadData(); } catch (e) {
    document.querySelector("main").innerHTML = `<div class="card empty">Pas encore de données.</div>`;
    return;
  }
  setupThemeButton(render);
  render();
})();
