"""Règles d'alerte ntfy. L'état est gardé dans data/alerts_state.json pour éviter les doublons."""
from __future__ import annotations

import datetime as dt

from common import ALERTS_JSON, SEARCHES_CSV, is_purchased, parse_date, read_json, read_rows, to_float, write_json
from notify import send


def _fmt(price, currency) -> str:
    return f"{price:,.0f} {currency}".replace(",", " ")


def target_for(trip: dict, combo_row: dict, searches: list[dict]) -> float | None:
    """Prix cible : montant fixe, ou bas de la fourchette typique de Google (« auto »)."""
    t = trip["target_price"]
    if t not in (None, "", "auto"):
        return float(t)
    if combo_row.get("typical_low") not in (None, ""):
        return float(combo_row["typical_low"])
    # Repli : dernière fourchette connue (3 jours max) pour cette combinaison.
    limit = (parse_date(combo_row["run_date"]) - dt.timedelta(days=3)).isoformat()
    best = None
    for r in searches:
        if (r["trip_id"] == trip["id"] and r["mode"] == "round_trip"
                and r["combination"] == combo_row["combination"] and r["run_date"] >= limit
                and to_float(r["typical_low"]) is not None):
            if best is None or r["timestamp"] > best[0]:
                best = (r["timestamp"], to_float(r["typical_low"]))
    return best[1] if best else None


def check_alerts(config: dict, trips: list[dict], today: dt.date, results: dict) -> None:
    state = read_json(ALERTS_JSON, {})
    searches = read_rows(SEARCHES_CSV)
    for trip in trips:
        if is_purchased(trip):
            continue
        s = state.setdefault(trip["id"], {"min_price": None, "deadline_sent": [], "target": None,
                                           "one_way_cheaper": {}})
        cur = trip["currency"]
        combos = results.get(trip["id"], {}).get("combos", [])

        # 1) Nouveau prix minimum
        candidates = []
        for c in combos:
            if c["round_trip_price"] is not None:
                candidates.append((c["round_trip_price"], c["combination"], "aller-retour"))
            if c["one_way_total"] is not None and c["one_way_source"] == "jour":
                candidates.append((c["one_way_total"], c["combination"], "deux allers simples"))
        if candidates:
            price, combo, mode = min(candidates)
            if s["min_price"] is None or price < s["min_price"]:
                first = s["min_price"] is None
                send(config, f"{trip['name']} : {'premier prix relevé' if first else 'nouveau minimum'}",
                     f"{_fmt(price, cur)} en {mode}, dates {combo.replace('_', ' → ')}"
                     + ("" if first else f" (avant : {_fmt(s['min_price'], cur)})"),
                     tags=["chart_with_downwards_trend"], priority=4)
                s["min_price"] = price

        # 2) Prix cible atteint
        hits = []
        for c in combos:
            target = target_for(trip, c, searches)
            best = min([p for p in (c["round_trip_price"], c["one_way_total"]) if p is not None], default=None)
            if target is not None and best is not None and best <= target:
                hits.append((best, c["combination"], target))
        if hits:
            price, combo, target = min(hits)
            last = s.get("target") or {}
            if not last.get("active") or price < last.get("price", float("inf")):
                send(config, f"{trip['name']} : prix cible atteint",
                     f"{_fmt(price, cur)} pour {combo.replace('_', ' → ')} (cible : {_fmt(target, cur)})",
                     tags=["dart"], priority=5)
            s["target"] = {"active": True, "price": min(price, last.get("price", price)) if last.get("active") else price}
        elif combos:
            s["target"] = {"active": False}

        # 3) Deux allers simples moins chers que l'aller-retour
        for c in combos:
            cheaper = c["cheapest_mode"] == "allers_simples"
            was = s["one_way_cheaper"].get(c["combination"], False)
            if cheaper and not was:
                send(config, f"{trip['name']} : deux allers simples moins chers",
                     f"{c['combination'].replace('_', ' → ')} : {_fmt(c['one_way_total'], cur)} en deux allers "
                     f"simples contre {_fmt(c['round_trip_price'], cur)} en aller-retour.",
                     tags=["twisted_rightwards_arrows"])
            if c["cheapest_mode"]:
                s["one_way_cheaper"][c["combination"]] = cheaper

        # 4) Date limite dans 7 jours puis 1 jour
        left = (parse_date(trip["purchase_deadline"]) - today).days
        for n in (7, 1):
            if 0 <= left <= n and n not in s["deadline_sent"] and (n == 1 or left > 1):
                send(config, f"{trip['name']} : date limite dans {left} jour{'s' if left > 1 else ''}",
                     f"Date limite d'achat : {trip['purchase_deadline']}."
                     + (f" Meilleur prix connu : {_fmt(s['min_price'], cur)}." if s["min_price"] else ""),
                     tags=["alarm_clock"], priority=4)
                s["deadline_sent"].append(n)
    write_json(ALERTS_JSON, state)
