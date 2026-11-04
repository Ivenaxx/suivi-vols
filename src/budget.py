"""Gestion du quota SerpApi : compteur, cycle, projection et réduction automatique."""
from __future__ import annotations

import calendar
import datetime as dt

from common import USAGE_JSON, now_iso, parse_date, read_json, write_json
from planner import plan_day

LEVEL_LABELS = {
    0: "normal",
    1: "allers simples un jour sur deux",
    2: "allers simples un jour sur deux, sans détail du vol retour",
    3: "seulement les meilleures combinaisons",
    4: "rationnement : budget insuffisant même au plus bas",
}


def _same_day_in_month(year: int, month: int, day: int) -> dt.date:
    return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _add_month(d: dt.date, anchor_day: int, n: int = 1) -> dt.date:
    m = d.month - 1 + n
    return _same_day_in_month(d.year + m // 12, m % 12 + 1, anchor_day)


def current_cycle(anchor: dt.date, today: dt.date) -> tuple[dt.date, dt.date]:
    """Cycle mensuel [début, fin) qui contient aujourd'hui, ancré sur le jour du renouvellement."""
    start = _same_day_in_month(today.year, today.month, anchor.day)
    if start > today:
        start = _add_month(start, anchor.day, -1)
    return start, _add_month(start, anchor.day, 1)


class Budget:
    def __init__(self, config: dict, today: dt.date, account: dict | None = None):
        b = config["budget"]
        self.cap = int(b["max_searches_per_cycle"])
        self.best_kept = int(b["best_combinations_kept"])
        self.today = today
        self.daily_allowance: int | None = None
        self.state = read_json(USAGE_JSON, {})
        self.account = account

        anchor = parse_date(b.get("renewal_date"))
        self.anchor_source = "config.yaml"
        if not anchor and account and account.get("plan_renewal_date"):
            try:
                anchor = parse_date(account["plan_renewal_date"])
                self.anchor_source = "API Account SerpApi"
            except ValueError:
                anchor = None
        if not anchor and self.state.get("cycle_start"):
            anchor = parse_date(self.state["cycle_start"])
            self.anchor_source = "cycle précédent"
        if not anchor:
            anchor = today
            self.anchor_source = "inconnue (supposée aujourd'hui)"
        self.cycle_start, self.cycle_end = current_cycle(anchor, today)

        if self.state.get("cycle_start") != self.cycle_start.isoformat():
            # Nouveau cycle : remise à zéro du compteur.
            self.state = {"cycle_start": self.cycle_start.isoformat(), "used": 0, "by_day": {},
                          "reduction_level": 0, "previous_cycles": self.state.get("previous_cycles", [])
                          + ([{"cycle_start": self.state["cycle_start"], "used": self.state.get("used", 0)}]
                             if self.state.get("cycle_start") else [])}
        self.state["cycle_end"] = self.cycle_end.isoformat()
        self.state["cap"] = self.cap
        self.state["anchor_source"] = self.anchor_source
        self.state.setdefault("by_day", {})

        # Alignement prudent sur le vrai compteur de SerpApi.
        if account:
            per_month = account.get("searches_per_month")
            left = account.get("plan_searches_left")
            if isinstance(per_month, int) and isinstance(left, int):
                real_used = per_month - left
                self.state["account_used"] = real_used
                self.state["account_checked_at"] = now_iso()
                if real_used > self.state["used"]:
                    self.state["used"] = real_used
        self.save()

    # -------------------------------------------------- compteur
    @property
    def used(self) -> int:
        return int(self.state["used"])

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)

    def can_spend(self, n: int = 1) -> bool:
        if self.daily_allowance is not None and self.spent_today + n > self.daily_allowance:
            return False
        return self.used + n <= self.cap

    @property
    def spent_today(self) -> int:
        return int(self.state["by_day"].get(self.today.isoformat(), 0))

    def spend(self, n: int = 1) -> None:
        self.state["used"] = self.used + n
        day = self.today.isoformat()
        self.state["by_day"][day] = self.spent_today + n
        self.save()  # enregistré tout de suite : un plantage ne fait pas perdre le compte

    def save(self) -> None:
        write_json(USAGE_JSON, self.state)

    # -------------------------------------------------- projection
    def projected_need(self, trips, rankings, level, best_kept, done_today) -> int:
        total = 0
        day = self.today
        while day < self.cycle_end:
            for trip in trips:
                rk = rankings[trip["id"]]
                tasks = plan_day(trip, day, level, rk["best"], best_kept, rk["recent"])
                if day == self.today:
                    tasks = [t for t in tasks if t["key"] not in done_today]
                total += len(tasks)
            day += dt.timedelta(days=1)
        return total

    def choose_level(self, trips, rankings, done_today, signature: str = "") -> dict:
        """Choisit le plus petit niveau de réduction qui tient dans le budget restant.

        `signature` résume les réglages des voyages : s'ils ont changé, on repart sans tenir
        compte du niveau précédent (la marge anti va-et-vient ne s'applique qu'à réglages égaux)."""
        remaining = self.remaining
        if signature and self.state.get("plan_signature") != signature:
            self.state["plan_signature"] = signature
            self.state["reduction_level"] = 0
            self.state["max_level_notified"] = 0
        previous = int(self.state.get("reduction_level", 0))
        options = [(lvl, self.best_kept) for lvl in (0, 1, 2)]
        options += [(3, k) for k in range(self.best_kept, 0, -1)]
        for lvl, kept in options:
            need = self.projected_need(trips, rankings, lvl, kept, done_today)
            # Pour revenir à un niveau moins réduit, on exige 10 % de marge (évite les va-et-vient).
            margin = 0.9 if lvl < previous else 1.0
            if need <= remaining * margin:
                return {"level": lvl, "best_kept": kept, "projected": need, "remaining": remaining}
        # Même au plus bas, ça ne tient pas : on rationne par jour restant.
        need = self.projected_need(trips, rankings, 3, 1, done_today)
        days_left = max(1, (self.cycle_end - self.today).days)
        self.daily_allowance = self.spent_today + max(0, remaining // days_left) if remaining else 0
        return {"level": 4, "best_kept": 1, "projected": need, "remaining": remaining,
                "daily_allowance": self.daily_allowance}

    def summary(self, choice: dict | None = None) -> dict:
        s = {
            "cap": self.cap, "used": self.used, "remaining": self.remaining,
            "cycle_start": self.cycle_start.isoformat(), "cycle_end": self.cycle_end.isoformat(),
            "anchor_source": self.anchor_source,
        }
        if choice:
            s.update({"reduction_level": choice["level"], "reduction_label": LEVEL_LABELS[choice["level"]],
                      "projected_need": choice["projected"]})
        return s
