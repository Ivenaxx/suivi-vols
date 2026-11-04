"""Génère site/data.json à partir des fichiers CSV de data/.

Utilisation : python src/build_site.py
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict

from common import (COMBOS_CSV, FLIGHTS_CSV, HISTORY_CSV, SEARCHES_CSV, SITE, USAGE_JSON, WEEKDAYS_FR,
                    all_combinations, combo_id, is_purchased, load_config, load_trips, now_iso, parse_date,
                    read_json, read_rows, to_float, today_utc)
from planner import trip_status

STATUS_FR = {"purchased": "acheté", "not_started": "pas encore commencé", "finished": "terminé (départ passé)",
             "stopped": "arrêté (date limite passée)", "reduced": "mode réduit (aller-retour seulement)",
             "active": "actif"}
DAY_BUCKETS = [(0, 6), (7, 13), (14, 20), (21, 27), (28, 41), (42, 55), (56, 89), (90, 179), (180, 10_000)]


def bucket_label(lo, hi):
    return f"{lo}+ j" if hi >= 10_000 else f"{lo}–{hi} j"


def combo_value(row) -> tuple[float | None, str]:
    rt = to_float(row["round_trip_price"])
    ow = to_float(row["one_way_total"])
    if rt is None and ow is None:
        return None, ""
    if ow is not None and (rt is None or ow < rt):
        return ow, "allers_simples"
    return rt, "aller_retour"


def verdict(price, target, days_to_deadline, min_observed, purchased):
    if purchased:
        return "Acheté", "Le prix d'achat est renseigné : le suivi est arrêté."
    if price is None:
        return "Attendre", "Pas encore de prix relevé."
    if days_to_deadline is not None and days_to_deadline < 0:
        return "Acheter", "La date limite d'achat est dépassée."
    if target is not None and price <= target:
        return "Acheter", "Le prix est au niveau du prix cible ou en dessous."
    if days_to_deadline is not None and days_to_deadline <= 1:
        return "Acheter", "La date limite est aujourd'hui ou demain."
    if min_observed and price <= min_observed * 1.02 and days_to_deadline is not None and days_to_deadline <= 7:
        return "Acheter", "Prix proche du minimum observé et date limite proche."
    if (target is not None and price <= target * 1.05) or (days_to_deadline is not None and days_to_deadline <= 7):
        return "Surveiller", ("Prix à moins de 5 % du prix cible." if target is not None and price <= target * 1.05
                              else "La date limite approche.")
    return "Attendre", "Le prix est au-dessus du prix cible et il reste du temps."


def main() -> None:
    config = load_config()
    trips = load_trips()
    today = today_utc()
    searches = read_rows(SEARCHES_CSV)
    flights = [f for f in read_rows(FLIGHTS_CSV) if f.get("matches_filters") == "1"]
    combos = read_rows(COMBOS_CSV)
    history = read_rows(HISTORY_CSV)
    usage = read_json(USAGE_JSON, {})
    pct = float(config["suggestions"]["never_within_pct"])
    min_days = int(config["suggestions"]["min_days_observed"])

    out_trips, suggestions = [], []
    for trip in trips:
        tid = trip["id"]
        t_combos = [c for c in combos if c["trip_id"] == tid]
        t_search = [s for s in searches if s["trip_id"] == tid]
        values = [(combo_value(c)[0], c) for c in t_combos]
        values = [(v, c) for v, c in values if v is not None]
        min_observed = min((v for v, _ in values), default=None)

        # ---- meilleur choix actuel (dernier jour de collecte)
        best = None
        if values:
            last_day = max(c["run_date"] for _, c in values)
            day_vals = [(v, c) for v, c in values if c["run_date"] == last_day]
            price, row = min(day_vals, key=lambda x: x[0])
            mode = combo_value(row)[1]
            legs = []
            if mode == "aller_retour":
                same = [f for f in flights if f["trip_id"] == tid and f["run_date"] == last_day
                        and f["combination"] == row["combination"]]
                out = [f for f in same if f["mode"] == "round_trip"]
                ret = [f for f in same if f["mode"] == "return_detail"]
                for group in (out, ret):
                    if group:
                        legs.append(min(group, key=lambda f: to_float(f["price"]) or 1e12))
            else:
                for side, date in (("aller", row["outbound_date"]), ("retour", row["return_date"])):
                    group = [f for f in flights if f["trip_id"] == tid and f["mode"] == "one_way"
                             and f["direction"] == side and f["outbound_date"] == date
                             and f["run_date"] <= last_day]
                    if group:
                        lastd = max(f["run_date"] for f in group)
                        legs.append(min([f for f in group if f["run_date"] == lastd],
                                        key=lambda f: to_float(f["price"]) or 1e12))
            typical = [s for s in t_search if s["mode"] == "round_trip" and s["run_date"] == last_day
                       and s["combination"] == row["combination"]]
            tl = to_float(typical[-1]["typical_low"]) if typical else None
            th = to_float(typical[-1]["typical_high"]) if typical else None
            target = tl if trip["target_price"] in (None, "", "auto") else float(trip["target_price"])
            best = {"date": last_day, "price": price, "mode": mode, "combination": row["combination"],
                    "typical_low": tl, "typical_high": th, "target": target,
                    "legs": [{"direction": "retour" if f["mode"] == "return_detail" else f["direction"],
                              "airlines": f["airlines"], "flight_numbers": f["flight_numbers"],
                              "departure_time": f["departure_time"], "arrival_time": f["arrival_time"],
                              "departure_airport": f["departure_airport"], "arrival_airport": f["arrival_airport"],
                              "price": to_float(f["price"])} for f in legs]}
        dl = (parse_date(trip["purchase_deadline"]) - today).days
        label, reason = verdict(best["price"] if best else None, best["target"] if best else None,
                                dl, min_observed, is_purchased(trip))
        if trip_status(trip, today) in ("finished", "stopped") and not is_purchased(trip):
            label, reason = "Terminé", "Le suivi de ce voyage est terminé."

        # ---- suggestions
        days = sorted({c["run_date"] for _, c in values})
        if len(days) >= min_days:
            daily_min = {d: min(v for v, c in values if c["run_date"] == d) for d in days}
            for o, r in all_combinations(trip):
                cid = combo_id(o, r)
                mine = [(v, c["run_date"]) for v, c in values if c["combination"] == cid]
                if len(mine) >= min_days and all(v > daily_min[d] * (1 + pct / 100) for v, d in mine):
                    suggestions.append({"trip_id": tid, "type": "combinaison", "combination": cid,
                                        "text": f"{cid.replace('_', ' → ')} n'a jamais été à moins de {pct:g} % "
                                                f"du minimum du jour ({len(mine)} jours observés). Tu peux "
                                                f"l'ajouter à excluded_combinations."})
        compared = [c for c in t_combos if c["cheapest_mode"]]
        compared_days = {c["run_date"] for c in compared}
        if trip["modes"]["one_way"] and len(compared_days) >= min_days and \
                not any(c["cheapest_mode"] == "allers_simples" for c in compared):
            suggestions.append({"trip_id": tid, "type": "allers_simples", "combination": "",
                                "text": f"Les deux allers simples n'ont jamais battu l'aller-retour "
                                        f"({len(compared)} comparaisons sur {len(compared_days)} jours). "
                                        f"Tu peux mettre modes.one_way: false pour économiser des recherches."})

        out_trips.append({
            "id": tid, "name": trip["name"], "currency": trip["currency"], "origin": trip["origin"],
            "destination": trip["destination"], "deadline": trip["purchase_deadline"],
            "target_price": trip["target_price"], "purchase": trip["purchase"],
            "status": STATUS_FR[trip_status(trip, today)], "days_to_deadline": dl,
            "combinations": [combo_id(o, r) for o, r in all_combinations(trip)],
            "excluded": trip["excluded_combinations"], "min_observed": min_observed,
            "best": best, "verdict": {"label": label, "reason": reason},
        })

    # ---- analyse transversale (tous les voyages)
    obs = []
    mins = defaultdict(lambda: float("inf"))
    rt_rows = [s for s in searches if s["mode"] == "round_trip" and s["status"] == "ok"
               and to_float(s["lowest_price"]) is not None]
    for s in rt_rows:
        k = (s["trip_id"], s["combination"])
        mins[k] = min(mins[k], to_float(s["lowest_price"]))
    for s in rt_rows:
        m = mins[(s["trip_id"], s["combination"])]
        obs.append({"pct": (to_float(s["lowest_price"]) / m - 1) * 100 if m else 0,
                    "days": int(s["days_before_departure"] or 0), "wd": s["search_weekday"]})

    def agg(items):
        p = [i["pct"] for i in items]
        return {"n": len(p), "mean_pct": round(statistics.mean(p), 1) if p else None,
                "median_pct": round(statistics.median(p), 1) if p else None}

    by_days = [{"label": bucket_label(lo, hi), **agg([o for o in obs if lo <= o["days"] <= hi])}
               for lo, hi in DAY_BUCKETS]
    by_days = [b for b in by_days if b["n"]]
    by_wd = [{"label": wd, **agg([o for o in obs if o["wd"] == wd])} for wd in WEEKDAYS_FR]
    paid = []
    for t in out_trips:
        price = to_float(t["purchase"].get("price"))
        if price is not None:
            m = t["min_observed"]
            paid.append({"trip_id": t["id"], "name": t["name"], "paid": price, "min_observed": m,
                         "date": t["purchase"].get("date"), "currency": t["currency"],
                         "pct_above_min": round((price / m - 1) * 100, 1) if m else None})

    data = {
        "generated_at": now_iso(), "today": today.isoformat(),
        "config": {"never_within_pct": pct},
        "usage": usage,
        "trips": out_trips,
        "searches": [{"d": s["run_date"], "ts": s["timestamp"], "t": s["trip_id"], "m": s["mode"],
                      "dir": s["direction"], "o": s["outbound_date"], "r": s["return_date"],
                      "c": s["combination"], "st": s["status"], "p": to_float(s["lowest_price"]),
                      "lvl": s["price_level"], "tl": to_float(s["typical_low"]),
                      "th": to_float(s["typical_high"]), "err": s.get("error", "")} for s in searches],
        "flights": [{"d": f["run_date"], "t": f["trip_id"], "m": f["mode"], "dir": f["direction"],
                     "o": f["outbound_date"], "r": f["return_date"], "c": f["combination"],
                     "al": f["airlines"], "fn": f["flight_numbers"], "da": f["departure_airport"],
                     "dt": f["departure_time"], "aa": f["arrival_airport"], "at": f["arrival_time"],
                     "dur": to_float(f["duration_min"]), "pl": f["airplanes"], "cls": f["travel_class"],
                     "leg": f["legroom"], "ext": f["extensions"], "fare": f["fare_info"],
                     "p": to_float(f["price"])} for f in flights],
        "combos": [{"d": c["run_date"], "t": c["trip_id"], "c": c["combination"],
                    "rt": to_float(c["round_trip_price"]), "ow": to_float(c["one_way_total"]),
                    "src": c["one_way_source"]} for c in combos],
        "history": [{"t": h["trip_id"], "m": h["mode"], "dir": h["direction"], "o": h["outbound_date"],
                     "r": h["return_date"], "hd": h["history_date"], "p": to_float(h["price"])}
                    for h in history],
        "suggestions": suggestions,
        "analysis": {"by_days": by_days, "by_weekday": by_wd, "paid": paid, "observations": len(obs)},
    }
    SITE.mkdir(exist_ok=True)
    with open(SITE / "data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"site/data.json écrit : {len(data['searches'])} recherches, {len(data['flights'])} options de vol.")


if __name__ == "__main__":
    main()
