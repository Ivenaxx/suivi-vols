"""Collecte quotidienne des prix.

Utilisation :
    python src/fetch_prices.py            # collecte réelle (consomme des recherches)
    python src/fetch_prices.py --dry-run  # affiche le plan et la projection, sans aucune recherche
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import re
import sys
import traceback

from alerts import check_alerts
from budget import LEVEL_LABELS, Budget
from common import (COMBO_FIELDS, COMBOS_CSV, FLIGHT_FIELDS, FLIGHTS_CSV, HISTORY_CSV, HISTORY_FIELDS,
                    SEARCH_FIELDS, SEARCHES_CSV, WEEKDAYS_FR, all_combinations, append_rows, combo_id,
                    data_path, load_config, load_trips, now_iso, option_for, parse_date, read_rows,
                    to_float, today_utc)
from notify import send
from parse import insights, lowest, parse_options
from planner import plan_day, rank_combinations
from serpapi_client import SerpApiClient, base_params, time_window

DONE_STATUSES = {"ok", "no_results"}


class Collector:
    def __init__(self, config, client, budget, today, choice):
        self.config = config
        self.client = client
        self.budget = budget
        self.today = today
        self.choice = choice
        self.history_seen = self._load_history_keys()
        self.searches_before = read_rows(SEARCHES_CSV)

    # ------------------------------------------------------------ outils
    @staticmethod
    def _load_history_keys() -> dict:
        last = {}
        for r in read_rows(HISTORY_CSV):
            k = (r["trip_id"], r["mode"], r["direction"], r["outbound_date"], r["return_date"])
            if r["history_date"] > last.get(k, ""):
                last[k] = r["history_date"]
        return last

    def _save_raw(self, trip, task, data) -> None:
        folder = data_path("raw") / self.today.isoformat()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%H%M%S")
        name = "_".join(x for x in [stamp, trip["id"], task["mode"], task["direction"],
                                    task.get("outbound_date"), task.get("return_date")] if x)
        name = re.sub(r"[^A-Za-z0-9_.-]", "-", name)
        text = json.dumps(data, ensure_ascii=False)
        if self.client.api_key:
            text = text.replace(self.client.api_key, "***")
        with gzip.open(folder / f"{name}.json.gz", "wt", encoding="utf-8") as f:
            f.write(text)

    def _params(self, trip, task, token=None) -> dict:
        p = base_params(trip)
        if task["mode"] == "one_way":
            side = task["direction"]
            p.update({"type": 2, "outbound_date": task["outbound_date"],
                      "departure_id": trip["origin"] if side == "aller" else trip["destination"],
                      "arrival_id": trip["destination"] if side == "aller" else trip["origin"]})
            tw = time_window(option_for(trip, task["outbound_date"], side))
            if tw:
                p["outbound_times"] = tw
        else:  # aller-retour (et détail du retour)
            p.update({"type": 1, "departure_id": trip["origin"], "arrival_id": trip["destination"],
                      "outbound_date": task["outbound_date"], "return_date": task["return_date"]})
            tw_out = time_window(option_for(trip, task["outbound_date"], "aller"))
            tw_ret = time_window(option_for(trip, task["return_date"], "retour"))
            if tw_out:
                p["outbound_times"] = tw_out
            if tw_ret:
                p["return_times"] = tw_ret
            if token:
                p["departure_token"] = token
        return p

    # ------------------------------------------------------------ une recherche
    def run_search(self, trip, task, token=None) -> dict:
        """Lance une recherche et enregistre tout. Ne plante jamais."""
        ts = now_iso()
        side = "retour" if task["direction"] == "retour" else "aller"
        flight_date = task["return_date"] if task["mode"] == "return_detail" else task["outbound_date"]
        window = option_for(trip, flight_date, side)
        combo = combo_id(task["outbound_date"], task["return_date"]) if task["return_date"] else ""
        result = {"status": "error", "lowest": None, "options": [], "insights": {}}
        row = {
            "timestamp": ts, "run_date": self.today.isoformat(), "trip_id": trip["id"],
            "mode": task["mode"], "direction": task["direction"],
            "outbound_date": task["outbound_date"], "return_date": task["return_date"],
            "combination": combo,
            "days_before_departure": (parse_date(flight_date) - self.today).days,
            "search_weekday": WEEKDAYS_FR[self.today.weekday()],
            "reduction_level": self.choice["level"],
        }
        try:
            status, data, err = self.client.search(self._params(trip, task, token))
            result["status"] = status
            row.update({"status": status, "error": err})
            if data:
                self._save_raw(trip, task, data)
                options = parse_options(data, trip["nonstop_only"], window)
                ins = insights(data)
                low = lowest(options)
                if low is None and status == "ok" and ins.get("lowest_price") and not trip["nonstop_only"]:
                    low = ins["lowest_price"]
                result.update({"lowest": low, "options": options, "insights": ins})
                row.update({"lowest_price": low, "price_level": ins["price_level"],
                            "typical_low": ins["typical_low"], "typical_high": ins["typical_high"],
                            "num_options": sum(o["matches_filters"] for o in options)})
                append_rows(FLIGHTS_CSV, FLIGHT_FIELDS, [{
                    **{k: row[k] for k in ("timestamp", "run_date", "trip_id", "mode", "outbound_date",
                                           "return_date", "combination")},
                    "direction": "retour" if task["mode"] == "return_detail" else
                                 ("aller" if task["direction"] == "aller-retour" else task["direction"]),
                    **o, "currency": trip["currency"],
                } for o in options])
                self._append_history(trip, task, ins.get("price_history") or [], ts)
        except Exception as e:  # noqa: BLE001 — une erreur ne doit pas arrêter le lancement
            traceback.print_exc()
            row.update({"status": "error", "error": f"{type(e).__name__}: {e}"[:300]})
            result["status"] = "error"
        append_rows(SEARCHES_CSV, SEARCH_FIELDS, [row])
        label = f"{trip['id']} {task['mode']} {task['direction']} {task['outbound_date']} {task['return_date']}"
        print(f"  {label.strip():<60} {row.get('status'):<14} {row.get('lowest_price') or ''}")
        return result

    def _append_history(self, trip, task, history, ts) -> None:
        k = (trip["id"], task["mode"], task["direction"], task["outbound_date"], task["return_date"])
        last = self.history_seen.get(k, "")
        rows = []
        for point in history:
            try:
                day = dt.datetime.fromtimestamp(int(point[0]), dt.timezone.utc).date().isoformat()
                price = point[1]
            except (TypeError, ValueError, IndexError):
                continue
            if day > last:
                rows.append({"timestamp": ts, "run_date": self.today.isoformat(), "trip_id": k[0],
                             "mode": k[1], "direction": k[2], "outbound_date": k[3],
                             "return_date": k[4], "history_date": day, "price": price})
        if rows:
            self.history_seen[k] = max(r["history_date"] for r in rows)
            append_rows(HISTORY_CSV, HISTORY_FIELDS, rows)

    # ------------------------------------------------------------ un voyage
    def _recent_one_way(self, trip, side, date) -> float | None:
        """Dernier prix aller simple connu (2 jours max) si on n'a pas cherché aujourd'hui."""
        limit = (self.today - dt.timedelta(days=2)).isoformat()
        best = None
        for r in self.searches_before:
            if (r["trip_id"] == trip["id"] and r["mode"] == "one_way" and r["direction"] == side
                    and r["outbound_date"] == date and r["status"] == "ok" and r["run_date"] >= limit):
                if best is None or r["timestamp"] > best[0]:
                    best = (r["timestamp"], to_float(r["lowest_price"]))
        return best[1] if best else None

    def run_trip(self, trip, tasks) -> dict:
        rt, ow = {}, {"aller": {}, "retour": {}}
        for task in [t for t in tasks if t["mode"] != "return_detail"]:
            res = self.run_search(trip, task)
            if task["mode"] == "round_trip":
                c = combo_id(task["outbound_date"], task["return_date"])
                cheapest = min((o for o in res["options"] if o["matches_filters"] and o.get("price")
                                and o.get("departure_token")), key=lambda o: o["price"], default=None)
                rt[c] = {"price": res["lowest"], "typical_low": res["insights"].get("typical_low"),
                         "typical_high": res["insights"].get("typical_high"),
                         "token": cheapest["departure_token"] if cheapest else None, "task": task}
            else:
                ow[task["direction"]][task["outbound_date"]] = res["lowest"]

        # Détail du vol retour pour l'aller-retour le moins cher du jour.
        if any(t["mode"] == "return_detail" for t in tasks):
            candidates = [(v["price"], c, v) for c, v in rt.items() if v["price"] and v["token"]]
            if candidates:
                _, c, v = min(candidates, key=lambda x: x[0])
                detail_task = {**v["task"], "mode": "return_detail", "direction": "retour"}
                self.run_search(trip, detail_task, token=v["token"])

        # Comparaison aller-retour / deux allers simples.
        combos_today = []
        for o, r in all_combinations(trip):
            c = combo_id(o, r)
            if c not in rt and o not in ow["aller"] and r not in ow["retour"]:
                continue
            out_p = ow["aller"].get(o)
            ret_p = ow["retour"].get(r)
            source = "jour"
            if trip["modes"]["one_way"]:
                if out_p is None:
                    out_p, source = self._recent_one_way(trip, "aller", o), "récent"
                if ret_p is None:
                    ret_p, source = self._recent_one_way(trip, "retour", r), "récent"
            ow_total = out_p + ret_p if out_p is not None and ret_p is not None else None
            rt_p = rt.get(c, {}).get("price")
            cheapest = diff = ""
            if rt_p is not None and ow_total is not None:
                cheapest = "allers_simples" if ow_total < rt_p else "aller_retour"
                diff = round(rt_p - ow_total, 2)
            row = {"timestamp": now_iso(), "run_date": self.today.isoformat(), "trip_id": trip["id"],
                   "combination": c, "outbound_date": o, "return_date": r, "round_trip_price": rt_p,
                   "one_way_out_price": out_p, "one_way_return_price": ret_p, "one_way_total": ow_total,
                   "one_way_source": source if ow_total is not None else "", "cheapest_mode": cheapest,
                   "difference": diff}
            combos_today.append({**row, "typical_low": rt.get(c, {}).get("typical_low")})
            append_rows(COMBOS_CSV, COMBO_FIELDS, [row])
        return {"combos": combos_today}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="affiche le plan sans faire de recherche")
    args = ap.parse_args()

    config = load_config()
    trips = load_trips()
    today = today_utc()
    api_key = os.environ.get("SERPAPI_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        print("ERREUR : le secret SERPAPI_API_KEY est absent. Voir le README, section « Secrets ».")
        return 1

    client = SerpApiClient(api_key, budget=None)
    account = client.account() if (api_key and config["budget"]["use_account_api"]) else None
    budget = Budget(config, today, account)
    client.budget = budget

    searches = read_rows(SEARCHES_CSV)
    done_today = {f"{r['trip_id']}|return_detail" if r["mode"] == "return_detail" else
                  f"{r['trip_id']}|{r['mode']}|{r['direction']}|{r['outbound_date']}|{r['return_date']}"
                  for r in searches if r["run_date"] == today.isoformat() and r["status"] in DONE_STATUSES}
    rankings = {t["id"]: rank_combinations(t, searches) for t in trips}
    choice = budget.choose_level(trips, rankings, done_today)

    print(f"Date (UTC) : {today}  |  quota : {budget.used}/{budget.cap} utilisées, "
          f"cycle {budget.cycle_start} → {budget.cycle_end} (renouvellement : {budget.anchor_source})")
    print(f"Projection jusqu'au renouvellement : {choice['projected']} recherches pour "
          f"{choice['remaining']} restantes → niveau {choice['level']} ({LEVEL_LABELS[choice['level']]})")

    plans = {}
    for trip in trips:
        tasks = plan_day(trip, today, choice["level"], rankings[trip["id"]], choice["best_kept"])
        plans[trip["id"]] = [t for t in tasks if t["key"] not in done_today]
        print(f"- {trip['id']} : {len(plans[trip['id']])} recherche(s) prévue(s) aujourd'hui")

    if args.dry_run:
        for tid, tasks in plans.items():
            for t in tasks:
                print(f"    {tid} {t['mode']} {t['direction']} {t['outbound_date']} {t['return_date']}")
        return 0

    notified = int(budget.state.get("max_level_notified", 0))  # remis à 0 à chaque nouveau cycle
    budget.state["reduction_level"] = choice["level"]
    budget.state["last_run"] = now_iso()
    budget.state["projection"] = {"date": today.isoformat(), **choice}
    if choice["level"] > notified:
        budget.state["max_level_notified"] = choice["level"]
    budget.save()
    if choice["level"] > notified:
        send(config, "Budget réduit automatiquement",
             f"Projection : {choice['projected']} recherches pour {choice['remaining']} restantes "
             f"d'ici le {budget.cycle_end}. Nouveau mode : {LEVEL_LABELS[choice['level']]}.",
             tags=["warning"], priority=4)

    collector = Collector(config, client, budget, today, choice)
    results = {}
    for trip in trips:
        try:
            results[trip["id"]] = collector.run_trip(trip, plans[trip["id"]])
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            results[trip["id"]] = {"combos": []}

    try:
        check_alerts(config, trips, today, results)
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    print(f"Terminé. Quota : {budget.used}/{budget.cap}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
