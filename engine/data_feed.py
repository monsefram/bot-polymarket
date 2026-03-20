"""
DataFeed — Polling Polymarket API for live market data.
Construit un historique de prix pour chaque marché suivi.
"""

import time
import json
import urllib.request
import urllib.error
import threading
from collections import defaultdict

import config

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept":     "application/json",
}


class DataFeed:
    def __init__(self):
        self.histories   = defaultdict(list)   # market_id → [snapshots]
        self.current     = {}                   # market_id → dernier snapshot
        self.market_meta = {}                   # market_id → métadonnées statiques
        self._lock       = threading.Lock()
        self.last_poll   = 0
        self.poll_errors = 0

    # ──────────────────────────────────────────────
    # API call
    # ──────────────────────────────────────────────
    def _fetch(self, path):
        url = config.POLYMARKET_API + path
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def fetch_active_markets(self, limit=100, offset=0):
        return self._fetch(
            f"/markets?closed=false&active=true"
            f"&limit={limit}&offset={offset}"
            f"&order=volume&ascending=false"
        )

    # ──────────────────────────────────────────────
    # Polling — appelé chaque POLL_INTERVAL
    # ──────────────────────────────────────────────
    def poll(self):
        now = time.time()
        try:
            raw = self.fetch_active_markets(limit=config.MAX_MARKETS_TRACKED)
            if not isinstance(raw, list):
                raw = []
        except Exception as e:
            self.poll_errors += 1
            print(f"  [FEED] Erreur poll #{self.poll_errors}: {e}")
            return []

        updated = []
        with self._lock:
            for m in raw:
                try:
                    mid = m.get("id") or m.get("conditionId")
                    if not mid:
                        continue

                    op = m.get("outcomePrices")
                    if not op:
                        continue
                    prices = json.loads(op) if isinstance(op, str) else op
                    if not isinstance(prices, list) or len(prices) < 2:
                        continue

                    yes_price = float(prices[0])
                    no_price  = float(prices[1])
                    vol       = float(m.get("volume") or m.get("volumeNum") or 0)
                    liq       = float(m.get("liquidity") or 0)
                    spread    = abs(1.0 - yes_price - no_price)

                    snapshot = {
                        "ts":     now,
                        "yes":    yes_price,
                        "no":     no_price,
                        "vol":    vol,
                        "liq":    liq,
                        "spread": spread,
                    }

                    self.current[mid] = snapshot
                    self.histories[mid].append(snapshot)

                    # Trim historique
                    if len(self.histories[mid]) > config.HISTORY_WINDOW:
                        self.histories[mid] = self.histories[mid][-config.HISTORY_WINDOW:]

                    # Métadonnées statiques
                    self.market_meta[mid] = {
                        "id":        mid,
                        "question":  m.get("question", "Unknown"),
                        "category":  m.get("category") or "Other",
                        "endDate":   m.get("endDate") or "",
                        "slug":      m.get("slug") or "",
                        "volume":    vol,
                        "liquidity": liq,
                    }

                    updated.append(mid)
                except Exception:
                    continue

        self.last_poll = now
        return updated

    # ──────────────────────────────────────────────
    # Accesseurs thread-safe
    # ──────────────────────────────────────────────
    def get_history(self, market_id):
        with self._lock:
            return list(self.histories.get(market_id, []))

    def get_current(self, market_id):
        with self._lock:
            return self.current.get(market_id)

    def get_meta(self, market_id):
        with self._lock:
            return self.market_meta.get(market_id)

    def get_all_tracked(self):
        with self._lock:
            return list(self.current.keys())

    def has_enough_history(self, market_id):
        with self._lock:
            return len(self.histories.get(market_id, [])) >= config.MIN_HISTORY

    def history_length(self, market_id):
        with self._lock:
            return len(self.histories.get(market_id, []))
