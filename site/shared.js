// Outils communs aux deux pages : thème, chargement des données, mise en forme.
const THEMES = ["auto", "light", "dark"];
const THEME_LABEL = { auto: "Thème : auto", light: "Thème : clair", dark: "Thème : sombre" };

function getTheme() {
  try { return localStorage.getItem("theme") || "auto"; } catch (e) { return "auto"; }
}
function applyTheme(t) {
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  const b = document.getElementById("theme");
  if (b) b.textContent = THEME_LABEL[t];
}
applyTheme(getTheme());

function setupThemeButton(onChange) {
  const b = document.getElementById("theme");
  b.addEventListener("click", () => {
    const next = THEMES[(THEMES.indexOf(getTheme()) + 1) % THEMES.length];
    try { localStorage.setItem("theme", next); } catch (e) { /* stockage indisponible */ }
    applyTheme(next);
    onChange && onChange();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => onChange && onChange());
}

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
const SERIES = () => [1, 2, 3, 4, 5, 6, 7, 8].map((i) => css(`--s${i}`));

async function loadData() {
  const r = await fetch("data.json", { cache: "no-store" });
  if (!r.ok) throw new Error("data.json introuvable");
  return r.json();
}

function money(v, cur) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  return new Intl.NumberFormat("fr-CA", { style: "currency", currency: cur || "CAD", maximumFractionDigits: 0 }).format(v);
}
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString("fr-CA", { weekday: "short", day: "numeric", month: "short" });
}
function comboLabel(c) {
  if (!c) return "";
  const [o, r] = c.split("_");
  return r ? `${fmtDate(o)} → ${fmtDate(r)}` : fmtDate(o);
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}
function addDays(iso, n) {
  const d = new Date(iso + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
function dateRange(a, b) {
  const out = [];
  for (let d = a; d <= b; d = addDays(d, 1)) out.push(d);
  return out;
}
function chartDefaults() {
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.color = css("--text-2");
  Chart.defaults.borderColor = css("--grid");
}
