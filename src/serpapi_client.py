"""Appels à l'API Google Flights de SerpApi (https://serpapi.com/google-flights-api)."""
from __future__ import annotations

import requests

from common import TRAVEL_CLASS, hhmm_to_minutes

SEARCH_URL = "https://serpapi.com/search.json"
ACCOUNT_URL = "https://serpapi.com/account.json"


def time_window(option: dict) -> str | None:
    """Convertit depart_after / depart_before en valeur outbound_times (ex. "20,23").

    Format SerpApi : deux heures (0-23) ; "4,18" = départ entre 4:00 et 18:59.
    """
    after = hhmm_to_minutes(option.get("depart_after"))
    before = hhmm_to_minutes(option.get("depart_before"))
    if after is None and before is None:
        return None
    start = (after or 0) // 60
    if before is None:
        end = 23
    else:
        end = before // 60 if before % 60 else before // 60 - 1
    end = max(start, min(23, end))
    return f"{start},{end}"


def base_params(trip: dict) -> dict:
    p = {
        "engine": "google_flights",
        "adults": trip["adults"],
        "travel_class": TRAVEL_CLASS.get(trip["travel_class"], 1),
        "currency": trip["currency"],
        "hl": trip["language"],
        "gl": trip["country"],
    }
    if trip["nonstop_only"]:
        p["stops"] = 1  # 1 = sans escale uniquement
    if trip["carry_on_bags"]:
        p["bags"] = trip["carry_on_bags"]
    return p


class SerpApiClient:
    def __init__(self, api_key: str, budget, timeout: int = 90):
        self.api_key = api_key
        self.budget = budget
        self.timeout = timeout

    def _scrub(self, text: str) -> str:
        return text.replace(self.api_key, "***") if self.api_key else text

    def account(self) -> dict | None:
        """API Account : gratuite, ne compte pas dans le quota."""
        try:
            r = requests.get(ACCOUNT_URL, params={"api_key": self.api_key}, timeout=30)
            if r.status_code == 200:
                return r.json()
            print(f"[budget] API Account indisponible (HTTP {r.status_code}).")
        except Exception as e:  # noqa: BLE001
            print(f"[budget] API Account indisponible : {self._scrub(str(e))}")
        return None

    def search(self, params: dict) -> tuple[str, dict | None, str]:
        """Renvoie (statut, données, message d'erreur). Ne lève jamais d'exception."""
        if not self.budget.can_spend(1):
            return "skipped_budget", None, "plafond de recherches atteint"
        self.budget.spend(1)  # compté AVANT l'appel : on reste du côté prudent
        try:
            r = requests.get(SEARCH_URL, params={**params, "api_key": self.api_key}, timeout=self.timeout)
        except Exception as e:  # noqa: BLE001
            return "error", None, self._scrub(f"réseau : {e}")[:300]
        try:
            data = r.json()
        except ValueError:
            return "error", None, f"réponse illisible (HTTP {r.status_code})"
        err = data.get("error")
        if err:
            if "hasn't returned any results" in err or "no results" in err.lower():
                return "no_results", data, self._scrub(err)[:300]
            return "error", data, self._scrub(err)[:300]
        if r.status_code >= 400:
            return "error", data, f"HTTP {r.status_code}"
        return "ok", data, ""
