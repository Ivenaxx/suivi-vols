"""Notifications sur le téléphone via ntfy (https://ntfy.sh), gratuit et sans compte."""
from __future__ import annotations

import os

import requests


def send(config: dict, title: str, message: str, tags: list[str] | None = None, priority: int = 3) -> bool:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    print(f"[alerte] {title} — {message}")
    if not topic:
        print("[alerte] NTFY_TOPIC absent : notification non envoyée.")
        return False
    body = {"topic": topic, "title": title, "message": message, "tags": tags or [], "priority": priority}
    if config["alerts"].get("site_url"):
        body["click"] = config["alerts"]["site_url"]
    try:
        # Publication en JSON sur la racine du serveur : gère les accents correctement.
        r = requests.post(config["alerts"]["ntfy_server"].rstrip("/") + "/", json=body, timeout=20)
        return r.status_code < 300
    except Exception as e:  # noqa: BLE001
        print(f"[alerte] échec d'envoi ntfy : {e}")
        return False
