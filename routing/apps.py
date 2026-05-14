from __future__ import annotations

import logging
import os

from django.apps import AppConfig

log = logging.getLogger(__name__)


class RoutingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "routing"

    def ready(self) -> None:
        # Pre-warm the station index at startup so the first request doesn't pay
        # JSON-load + indexing latency. Skip during management commands that
        # don't serve traffic, by setting SKIP_STATION_PRELOAD=1.
        if os.getenv("SKIP_STATION_PRELOAD") == "1":
            return
        try:
            from .services.stations import get_index

            idx = get_index()
            log.info("Preloaded %s fuel stations.", f"{len(idx.stations):,}")
        except Exception as exc:  # noqa: BLE001 — startup must not crash
            log.warning("Station preload skipped: %s", exc)
