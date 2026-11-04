"""Outils partagés : chemins, lecture de la configuration, dates, fichiers CSV."""
from __future__ import annotations

import csv
import datetime as dt
import itertools
import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("SUIVI_VOLS_DATA", ROOT / "data"))
SITE = ROOT / "site"

SEARCHES_CSV = "searches.csv"
FLIGHTS_CSV = "flights.csv"
HISTORY_CSV = "price_history.csv"
COMBOS_CSV = "combos.csv"
USAGE_JSON = "usage.json"
ALERTS_JSON = "alerts_state.json"

WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
TRAVEL_CLASS = {"economy": 1, "premium_economy": 2, "business": 3, "first": 4}

# Colonnes des fichiers CSV (l'ordre ne doit jamais changer : on ajoute seulement à la fin).
SEARCH_FIELDS = [
    "timestamp", "run_date", "trip_id", "mode", "direction", "outbound_date", "return_date",
    "combination", "days_before_departure", "search_weekday", "status", "lowest_price",
    "price_level", "typical_low", "typical_high", "num_options", "reduction_level", "error",
]
FLIGHT_FIELDS = [
    "timestamp", "run_date", "trip_id", "mode", "direction", "outbound_date", "return_date",
    "combination", "category", "rank", "airlines", "flight_numbers", "departure_airport",
    "departure_time", "arrival_airport", "arrival_time", "duration_min", "stops", "airplanes",
    "travel_class", "legroom", "extensions", "fare_info", "matches_filters", "price", "currency",
]
HISTORY_FIELDS = [
    "timestamp", "run_date", "trip_id", "mode", "direction", "outbound_date", "return_date",
    "history_date", "price",
]
COMBO_FIELDS = [
    "timestamp", "run_date", "trip_id", "combination", "outbound_date", "return_date",
    "round_trip_price", "one_way_out_price", "one_way_return_price", "one_way_total",
    "one_way_source", "cheapest_mode", "difference",
]


# ---------------------------------------------------------------- dates
def parse_date(value) -> dt.date | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value).strip()[:10])


def today_utc() -> dt.date:
    forced = os.environ.get("SUIVI_VOLS_TODAY")  # utile pour les tests
    return parse_date(forced) if forced else dt.datetime.now(dt.timezone.utc).date()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def combo_id(outbound: str, ret: str) -> str:
    return f"{outbound}_{ret}"


def hhmm_to_minutes(value: str | None) -> int | None:
    if not value:
        return None
    h, m = str(value).strip().split(":")[:2]
    return int(h) * 60 + int(m)


# ---------------------------------------------------------------- configuration
def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> dict:
    cfg = load_yaml(ROOT / "config.yaml")
    cfg.setdefault("budget", {})
    cfg["budget"].setdefault("max_searches_per_cycle", 240)
    cfg["budget"].setdefault("renewal_date", "")
    cfg["budget"].setdefault("use_account_api", True)
    cfg["budget"].setdefault("best_combinations_kept", 2)
    cfg.setdefault("alerts", {})
    cfg["alerts"].setdefault("ntfy_server", "https://ntfy.sh")
    cfg["alerts"].setdefault("site_url", "")
    cfg.setdefault("suggestions", {})
    cfg["suggestions"].setdefault("never_within_pct", 10)
    cfg["suggestions"].setdefault("min_days_observed", 5)
    return cfg


def _norm_options(options) -> list[dict]:
    out = []
    for o in options or []:
        if not isinstance(o, dict):
            o = {"date": o}
        out.append({
            "date": parse_date(o["date"]).isoformat(),
            "depart_after": o.get("depart_after"),
            "depart_before": o.get("depart_before"),
        })
    return out


def normalize_trip(t: dict) -> dict:
    """Ajoute les valeurs par défaut et vérifie les champs indispensables."""
    for key in ("id", "origin", "destination", "outbound_options"):
        if not t.get(key):
            raise ValueError(f"Voyage incomplet : le champ « {key} » est obligatoire ({t.get('id')}).")
    t = dict(t)
    t.setdefault("name", t["id"])
    t.setdefault("nonstop_only", False)
    t.setdefault("adults", 1)
    t.setdefault("travel_class", "economy")
    t.setdefault("carry_on_bags", 0)
    t.setdefault("currency", "CAD")
    t.setdefault("language", "fr")
    t.setdefault("country", "ca")
    t["outbound_options"] = _norm_options(t.get("outbound_options"))
    t["return_options"] = _norm_options(t.get("return_options"))
    modes = t.get("modes") or {}
    t["modes"] = {"round_trip": bool(modes.get("round_trip", True)) and bool(t["return_options"]),
                  "one_way": bool(modes.get("one_way", False))}
    t.setdefault("return_flight_detail", "cheapest_round_trip")
    t.setdefault("target_price", "auto")
    t["purchase_deadline"] = (parse_date(t.get("purchase_deadline")) or
                              parse_date(t["outbound_options"][0]["date"])).isoformat()
    t.setdefault("after_deadline", "reduced")
    purchase = t.get("purchase") or {}
    t["purchase"] = {"price": purchase.get("price"), "date": purchase.get("date")}
    t["tracking_start"] = (parse_date(t.get("tracking_start")) or dt.date(2000, 1, 1)).isoformat()
    phases = t.get("phases") or {}
    t["phases"] = {
        "exploration_days": int(phases.get("exploration_days", 0) or 0),
        "watch_every_days": max(1, int(phases.get("watch_every_days", 1) or 1)),
        "watch_combinations": phases.get("watch_combinations", "all"),
        "decision_days": int(phases.get("decision_days", 0) or 0),
    }
    t["excluded_combinations"] = [str(c).strip() for c in (t.get("excluded_combinations") or [])]
    return t


def load_trips() -> list[dict]:
    raw = load_yaml(ROOT / "trips.yaml").get("trips") or []
    trips = [normalize_trip(t) for t in raw]
    ids = [t["id"] for t in trips]
    if len(ids) != len(set(ids)):
        raise ValueError("Deux voyages ont le même id dans trips.yaml.")
    return trips


def option_for(trip: dict, date: str, side: str) -> dict:
    key = "outbound_options" if side == "aller" else "return_options"
    for o in trip[key]:
        if o["date"] == date:
            return o
    return {"date": date}


def all_combinations(trip: dict) -> list[tuple[str, str]]:
    """Toutes les combinaisons (aller, retour) non exclues."""
    excluded = set(trip["excluded_combinations"])
    return [(o["date"], r["date"])
            for o, r in itertools.product(trip["outbound_options"], trip["return_options"])
            if combo_id(o["date"], r["date"]) not in excluded]


def is_purchased(trip: dict) -> bool:
    return trip["purchase"].get("price") not in (None, "")


# ---------------------------------------------------------------- fichiers
def data_path(name: str) -> Path:
    DATA.mkdir(parents=True, exist_ok=True)
    return DATA / name


def append_rows(name: str, fields: list[str], rows: list[dict]) -> None:
    """Ajoute des lignes à la fin d'un CSV (jamais de réécriture)."""
    if not rows:
        return
    path = data_path(name)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


def read_rows(name: str) -> list[dict]:
    path = data_path(name)
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_json(name: str, default):
    path = data_path(name)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(name: str, obj) -> None:
    path = data_path(name)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def to_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
