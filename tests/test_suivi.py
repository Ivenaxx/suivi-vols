"""Tests sans réseau et sans consommer de recherche : python -m unittest discover tests

Les réponses de SerpApi sont simulées. Les données sont écrites dans un dossier temporaire.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="suivi-vols-test-"))
os.environ["SUIVI_VOLS_DATA"] = str(TMP)
os.environ.pop("NTFY_TOPIC", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import common  # noqa: E402
import fetch_prices  # noqa: E402
import planner  # noqa: E402
from budget import Budget, current_cycle  # noqa: E402
from serpapi_client import SerpApiClient, time_window  # noqa: E402


def fake_response(params: dict) -> dict:
    """Réponse Google Flights plausible et reproductible."""
    seed = int(hashlib.md5(repr(sorted(params.items())).encode()).hexdigest()[:8], 16)
    rnd = random.Random(seed)
    rt = params["type"] == 1 and "departure_token" not in params
    base = 1150 if params["type"] == 1 else 620
    start_h = int(params.get("outbound_times", "6,23").split(",")[0])
    opts = []
    for code, name in (("AC", "Air Canada"), ("AF", "Air France"), ("TS", "Air Transat")):
        h = rnd.randint(max(start_h, 17), 23)
        dep, arr = params["departure_id"], params["arrival_id"]
        day = params["outbound_date"] if "departure_token" not in params else params["return_date"]
        if "departure_token" in params:
            dep, arr = arr, dep
        opts.append({
            "flights": [{"departure_airport": {"id": dep, "time": f"{day} {h:02d}:{rnd.choice(['05', '35'])}"},
                         "arrival_airport": {"id": arr, "time": f"{day} 09:10"},
                         "duration": 425, "airplane": "Boeing 787", "airline": name,
                         "flight_number": f"{code} {rnd.randint(800, 899)}", "travel_class": "Économie",
                         "legroom": "79 cm", "extensions": ["Wi-Fi payant"]}],
            "total_duration": 425, "price": base + rnd.randint(-120, 220),
            "extensions": ["1 bagage cabine inclus"], "type": "Aller-retour" if params["type"] == 1 else "Aller simple",
            "departure_token": f"tok-{code}" if rt else None,
        })
    return {
        "best_flights": opts[:1], "other_flights": opts[1:],
        "price_insights": {"lowest_price": min(o["price"] for o in opts), "price_level": "typical",
                           "typical_price_range": [base - 60, base + 250],
                           "price_history": [[1761955200 + 86400 * i, base + 10 * i] for i in range(5)]},
    }


class FakeClient(SerpApiClient):
    calls = 0

    def account(self):
        return None

    def search(self, params):
        if not self.budget.can_spend(1):
            return "skipped_budget", None, "plafond"
        self.budget.spend(1)
        FakeClient.calls += 1
        if params.get("outbound_date") == "2026-12-17" and params["type"] == 2 and FakeClient.calls % 7 == 0:
            raise RuntimeError("panne simulée")
        return "ok", fake_response(params), ""


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fetch_prices.SerpApiClient = FakeClient
        os.environ["SERPAPI_API_KEY"] = "test-key-123"

    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        TMP.mkdir()

    def run_day(self, day: str):
        os.environ["SUIVI_VOLS_TODAY"] = day
        sys.argv = ["fetch_prices.py"]
        self.assertEqual(fetch_prices.main(), 0)

    def test_time_window(self):
        self.assertEqual(time_window({"depart_after": "20:00"}), "20,23")
        self.assertEqual(time_window({"depart_before": "19:00"}), "0,18")
        self.assertIsNone(time_window({}))

    def test_cycle(self):
        s, e = current_cycle(dt.date(2026, 10, 31), dt.date(2026, 11, 4))
        self.assertEqual((s, e), (dt.date(2026, 10, 31), dt.date(2026, 11, 30)))

    def test_plan_noel(self):
        trip = common.load_trips()[0]
        tasks = planner.plan_day(trip, dt.date(2026, 11, 4), 0, [], 2)
        modes = [t["mode"] for t in tasks]
        self.assertEqual(modes.count("round_trip"), 6)
        self.assertEqual(modes.count("one_way"), 5)
        self.assertEqual(modes.count("return_detail"), 1)
        reduced = planner.plan_day(trip, dt.date(2026, 11, 25), 0, [], 2)
        self.assertEqual({t["mode"] for t in reduced}, {"round_trip"})

    def test_full_simulation_never_exceeds_cap(self):
        day = dt.date(2026, 11, 4)
        while day <= dt.date(2026, 12, 20):
            self.run_day(day.isoformat())
            self.run_day(day.isoformat())  # relance manuelle le même jour : ne doit rien refaire
            day += dt.timedelta(days=1)
        usage = common.read_json(common.USAGE_JSON, {})
        for prev in usage.get("previous_cycles", []) + [usage]:
            self.assertLessEqual(prev["used"], 240)
        rows = common.read_rows(common.SEARCHES_CSV)
        self.assertTrue(rows)
        self.assertTrue(any(r["status"] == "error" for r in rows), "la panne simulée doit être enregistrée")
        self.assertTrue(common.read_rows(common.COMBOS_CSV))
        raw = list((TMP / "raw").rglob("*.json.gz"))
        self.assertTrue(raw)
        import gzip
        self.assertNotIn("test-key-123", gzip.open(raw[0], "rt", encoding="utf-8").read())
        import build_site
        build_site.main()


if __name__ == "__main__":
    unittest.main()
