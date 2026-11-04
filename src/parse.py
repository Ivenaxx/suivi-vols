"""Lecture des réponses Google Flights de SerpApi."""
from __future__ import annotations

from common import hhmm_to_minutes


def _clock(value: str | None) -> int | None:
    """'2026-12-16 20:35' -> minutes depuis minuit."""
    if not value or " " not in value:
        return None
    return hhmm_to_minutes(value.split(" ")[1])


def parse_options(data: dict, nonstop_only: bool, window: dict) -> list[dict]:
    """Une entrée par option de vol (best_flights puis other_flights)."""
    after = hhmm_to_minutes(window.get("depart_after"))
    before = hhmm_to_minutes(window.get("depart_before"))
    options = []
    for category in ("best_flights", "other_flights"):
        for rank, it in enumerate(data.get(category) or [], start=1):
            segs = it.get("flights") or []
            if not segs:
                continue
            first, last = segs[0], segs[-1]
            dep = (first.get("departure_airport") or {})
            arr = (last.get("arrival_airport") or {})
            dep_min = _clock(dep.get("time"))
            ok = True
            if nonstop_only and len(segs) > 1:
                ok = False
            if dep_min is not None and after is not None and dep_min < after:
                ok = False
            if dep_min is not None and before is not None and dep_min > before:
                ok = False
            seg_ext = []
            for s in segs:
                seg_ext.extend(s.get("extensions") or [])
            options.append({
                "category": "best" if category == "best_flights" else "other",
                "rank": rank,
                "airlines": " + ".join(dict.fromkeys(s.get("airline", "?") for s in segs)),
                "flight_numbers": " / ".join(s.get("flight_number", "") for s in segs),
                "departure_airport": dep.get("id", ""),
                "departure_time": dep.get("time", ""),
                "arrival_airport": arr.get("id", ""),
                "arrival_time": arr.get("time", ""),
                "duration_min": it.get("total_duration") or sum(s.get("duration") or 0 for s in segs),
                "stops": len(segs) - 1,
                "airplanes": " / ".join(s.get("airplane", "") for s in segs if s.get("airplane")),
                "travel_class": " / ".join(dict.fromkeys(s.get("travel_class", "") for s in segs)),
                "legroom": " / ".join(dict.fromkeys(s.get("legroom", "") for s in segs if s.get("legroom"))),
                "extensions": " | ".join(dict.fromkeys(seg_ext)),
                "fare_info": " | ".join(it.get("extensions") or []),
                "matches_filters": 1 if ok else 0,
                "price": it.get("price"),
                "departure_token": it.get("departure_token"),
            })
    return options


def insights(data: dict) -> dict:
    pi = data.get("price_insights") or {}
    rng = pi.get("typical_price_range") or [None, None]
    return {
        "lowest_price": pi.get("lowest_price"),
        "price_level": pi.get("price_level", ""),
        "typical_low": rng[0] if len(rng) > 0 else None,
        "typical_high": rng[1] if len(rng) > 1 else None,
        "price_history": pi.get("price_history") or [],
    }


def lowest(options: list[dict]) -> float | None:
    prices = [o["price"] for o in options if o["matches_filters"] and isinstance(o.get("price"), (int, float))]
    return min(prices) if prices else None
