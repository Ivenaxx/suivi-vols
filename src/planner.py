"""Planificateur : décide quelles recherches faire un jour donné, pour un voyage.

Niveaux de réduction du budget (cumulatifs) :
  0 = normal
  1 = allers simples un jour sur deux
  2 = + plus de détail du vol retour
  3 = + seulement les meilleures combinaisons
"""
from __future__ import annotations

import datetime as dt

from common import all_combinations, combo_id, is_purchased, parse_date


def task_key(t: dict) -> str:
    if t["mode"] == "return_detail":
        return f"{t['trip_id']}|return_detail"
    return f"{t['trip_id']}|{t['mode']}|{t['direction']}|{t['outbound_date']}|{t['return_date']}"


def trip_status(trip: dict, day: dt.date) -> str:
    """'purchased', 'not_started', 'finished', 'stopped', 'reduced' ou 'active'."""
    if is_purchased(trip):
        return "purchased"
    if day < parse_date(trip["tracking_start"]):
        return "not_started"
    future = [o for o in trip["outbound_options"] if parse_date(o["date"]) > day]
    if not future:
        return "finished"
    if day > parse_date(trip["purchase_deadline"]):
        return "stopped" if trip["after_deadline"] == "stop" else "reduced"
    return "active"


def phase(trip: dict, day: dt.date) -> str:
    p = trip["phases"]
    since = (day - parse_date(trip["tracking_start"])).days
    to_deadline = (parse_date(trip["purchase_deadline"]) - day).days
    if since < p["exploration_days"]:
        return "exploration"
    if 0 <= to_deadline < p["decision_days"]:
        return "decision"
    return "veille"


def rank_combinations(trip: dict, searches: list[dict]) -> list[str]:
    """Combinaisons triées de la moins chère à la plus chère (dernier prix aller-retour connu)."""
    last: dict[str, tuple[str, float]] = {}
    for r in searches:
        if r.get("trip_id") != trip["id"] or r.get("mode") != "round_trip" or r.get("status") != "ok":
            continue
        try:
            price = float(r["lowest_price"])
        except (TypeError, ValueError):
            continue
        c = r["combination"]
        if c not in last or r["timestamp"] >= last[c][0]:
            last[c] = (r["timestamp"], price)
    combos = [combo_id(o, r) for o, r in all_combinations(trip)]
    return sorted(combos, key=lambda c: (last[c][1] if c in last else float("inf"), combos.index(c)))


def rank_recent(trip: dict, searches: list[dict], today: dt.date, days: int) -> list[str]:
    """Combinaisons triées par meilleur prix aller-retour des `days` derniers jours (aujourd'hui exclu).

    Sans prix récent, une combinaison passe après les autres, triée par son dernier prix connu."""
    since = (today - dt.timedelta(days=days)).isoformat()
    best: dict[str, float] = {}
    for r in searches:
        if (r.get("trip_id") != trip["id"] or r.get("mode") != "round_trip" or r.get("status") != "ok"
                or not (since <= r.get("run_date", "") < today.isoformat())):
            continue
        try:
            price = float(r["lowest_price"])
        except (TypeError, ValueError):
            continue
        best[r["combination"]] = min(price, best.get(r["combination"], price))
    fallback = rank_combinations(trip, searches)
    return sorted(fallback, key=lambda c: (best.get(c, float("inf")), fallback.index(c)))


def _keep_first(combos: list[tuple[str, str]], ranking: list[str], n: int) -> list[tuple[str, str]]:
    """Garde les n combinaisons encore possibles les mieux classées (ordre du fichier si pas de classement)."""
    order = {c: i for i, c in enumerate(ranking)}
    ranked = sorted(combos, key=lambda c: order.get(combo_id(*c), len(order)))
    return ranked[:n]


def plan_day(trip: dict, day: dt.date, level: int, ranking: list[str], best_kept: int,
             reduced_ranking: list[str] | None = None) -> list[dict]:
    status = trip_status(trip, day)
    if status not in ("active", "reduced"):
        return []
    if trip["return_options"]:
        combos = [(o, r) for o, r in all_combinations(trip) if parse_date(o) > day]
    else:  # voyage en aller simple uniquement
        combos = [(o["date"], "") for o in trip["outbound_options"] if parse_date(o["date"]) > day]
    one_way = trip["modes"]["one_way"] or not trip["return_options"]
    detail = trip["return_flight_detail"] == "cheapest_round_trip"

    if status == "reduced":
        one_way, detail = False, False
        if trip["reduced_combinations"] and trip["return_options"]:
            combos = _keep_first(combos, reduced_ranking if reduced_ranking is not None else ranking,
                                 trip["reduced_combinations"])
    else:
        ph = phase(trip, day)
        if ph == "veille":
            p = trip["phases"]
            since = (day - parse_date(trip["tracking_start"])).days - p["exploration_days"]
            if since % p["watch_every_days"] != 0:
                return []
            wanted = p["watch_combinations"]
            if wanted == "best":
                keep = set(ranking[:best_kept])
                combos = [c for c in combos if combo_id(*c) in keep]
            elif isinstance(wanted, list):
                keep = set(map(str, wanted))
                combos = [c for c in combos if combo_id(*c) in keep]

    # Réductions de budget
    if level >= 1 and day.toordinal() % 2 == 1:
        one_way = False
    if level >= 2:
        detail = False
    if level >= 3:
        combos = _keep_first(combos, ranking, best_kept)

    if not combos:
        return []
    tasks: list[dict] = []
    base = {"trip_id": trip["id"]}
    if trip["modes"]["round_trip"]:
        for o, r in combos:
            tasks.append({**base, "mode": "round_trip", "direction": "aller-retour",
                          "outbound_date": o, "return_date": r})
    if one_way:
        for o in sorted({c[0] for c in combos}):
            tasks.append({**base, "mode": "one_way", "direction": "aller",
                          "outbound_date": o, "return_date": ""})
        for r in sorted({c[1] for c in combos if c[1]}):
            tasks.append({**base, "mode": "one_way", "direction": "retour",
                          "outbound_date": r, "return_date": ""})
    if detail and trip["modes"]["round_trip"]:
        tasks.append({**base, "mode": "return_detail", "direction": "retour",
                      "outbound_date": "", "return_date": ""})
    for t in tasks:
        t["key"] = task_key(t)
    return tasks
