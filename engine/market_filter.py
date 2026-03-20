"""
MarketFilter — Filtre les marchés éligibles au trading.
Applique les critères de volume, liquidité, spread, prix et temps.
"""

import time
from datetime import datetime, timezone

import config


class MarketFilter:

    def filter(self, market_id, feed):
        """
        Retourne (passed: bool, reasons: list[str]).
        passed=True → marché éligible.
        """
        reasons = []

        snap = feed.get_current(market_id)
        meta = feed.get_meta(market_id)
        if not snap or not meta:
            return False, ["no_data"]

        # ── Volume
        if snap["vol"] < config.MIN_VOLUME:
            reasons.append(f"vol_low:{snap['vol']:.0f}")

        # ── Liquidité
        if snap["liq"] < config.MIN_LIQUIDITY:
            reasons.append(f"liq_low:{snap['liq']:.0f}")

        # ── Spread
        if snap["spread"] > config.MAX_SPREAD:
            reasons.append(f"spread:{snap['spread']:.3f}")

        # ── Bornes de prix (pas d'edge près de 0 ou 1)
        if snap["yes"] < config.MIN_PRICE or snap["yes"] > config.MAX_PRICE:
            reasons.append(f"price_bound:{snap['yes']:.2f}")

        # ── Temps avant résolution
        end_date = meta.get("endDate")
        if end_date:
            try:
                end_str = end_date.replace("Z", "+00:00")
                end_dt = datetime.fromisoformat(end_str)
                hours_left = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                if hours_left < config.MIN_HOURS_TO_RESOLVE:
                    reasons.append(f"resolving_soon:{hours_left:.0f}h")
            except Exception:
                pass

        # ── Historique suffisant
        if not feed.has_enough_history(market_id):
            reasons.append("insufficient_history")

        return len(reasons) == 0, reasons
