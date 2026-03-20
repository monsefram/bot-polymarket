"""
TrendEngine — Moteur de détection de tendances pour Polymarket.

Adapté aux prix bornés [0, 1] (probabilités).
Utilise la transformation logit pour les EMAs afin que les mouvements
près de 0/1 soient traités de manière équivalente à ceux au milieu.

Indicateurs calculés :
  - EMA fast / slow (sur logit du prix)
  - Rate of Change (ROC)
  - Vélocité et accélération
  - Consistance directionnelle
  - Ratio de volume (récent vs ancien)
  - Magnitude du mouvement
"""

import math
import config


class TrendEngine:

    def analyze(self, history):
        """
        Calcule les indicateurs de tendance à partir de l'historique.
        Retourne un dict d'indicateurs, ou None si données insuffisantes.
        """
        if len(history) < config.MIN_HISTORY:
            return None

        prices  = [s["yes"] for s in history]
        volumes = [s["vol"] for s in history]
        spreads = [s["spread"] for s in history]
        n = len(prices)

        # ── 1. EMAs sur logit(prix) — transformation pour prix bornés [0,1]
        logit_prices = [self._safe_logit(p) for p in prices]
        ema_fast_arr = self._ema(logit_prices, config.EMA_FAST)
        ema_slow_arr = self._ema(logit_prices, config.EMA_SLOW)

        ema_f = ema_fast_arr[-1] if ema_fast_arr else 0
        ema_s = ema_slow_arr[-1] if ema_slow_arr else 0

        ema_bullish = ema_f > ema_s
        ema_spread  = ema_f - ema_s

        # Vérifier si l'EMA vient de croiser (signal frais)
        if len(ema_fast_arr) >= 2 and len(ema_slow_arr) >= 2:
            prev_bull = ema_fast_arr[-2] > ema_slow_arr[-2]
            ema_cross = ema_bullish != prev_bull
        else:
            ema_cross = False

        # ── 2. Rate of Change (ROC) — prix brut
        roc_period = min(config.ROC_PERIOD, n - 1)
        roc = prices[-1] - prices[-1 - roc_period] if roc_period > 0 else 0

        # ── 3. Vélocité (ROC court terme, ~3 périodes)
        vel_lookback = min(3, n - 1)
        velocity = prices[-1] - prices[-1 - vel_lookback] if vel_lookback > 0 else 0

        # ── 4. Accélération (changement de vélocité)
        if n >= 7:
            vel_now  = prices[-1] - prices[-4]
            vel_prev = prices[-4] - prices[-7]
            acceleration = vel_now - vel_prev
        elif n >= 4:
            vel_now  = prices[-1] - prices[-3]
            vel_prev = prices[-3] - prices[-min(5, n)]
            acceleration = vel_now - vel_prev
        else:
            acceleration = 0

        # ── 5. Consistance directionnelle
        lookback = min(config.ROC_PERIOD, n - 1)
        if lookback > 0:
            ups = sum(1 for i in range(-lookback, 0)
                      if prices[i] > prices[i - 1])
            consistency_up   = ups / lookback
            consistency_down = 1 - consistency_up
        else:
            consistency_up = consistency_down = 0.5

        # ── 6. Ratio de volume (récent / ancien)
        if len(volumes) >= 10:
            recent_vol = sum(volumes[-5:]) / 5
            older_vol  = sum(volumes[-10:-5]) / 5
            vol_ratio  = recent_vol / older_vol if older_vol > 0 else 1.0
        elif len(volumes) >= 5:
            recent_vol = sum(volumes[-3:]) / 3
            older_vol  = sum(volumes[:-3]) / max(1, len(volumes) - 3)
            vol_ratio  = recent_vol / older_vol if older_vol > 0 else 1.0
        else:
            vol_ratio = 1.0

        # ── 7. Magnitude totale
        magnitude = abs(roc)

        # ── 8. Spread moyen récent
        avg_spread = sum(spreads[-5:]) / min(5, len(spreads))

        # ── Direction
        if roc > config.NOISE_FILTER:
            direction = "up"
        elif roc < -config.NOISE_FILTER:
            direction = "down"
        else:
            direction = "flat"

        return {
            "direction":        direction,
            "ema_bullish":      ema_bullish,
            "ema_spread":       round(ema_spread, 4),
            "ema_cross":        ema_cross,
            "roc":              round(roc, 5),
            "velocity":         round(velocity, 5),
            "acceleration":     round(acceleration, 5),
            "consistency_up":   round(consistency_up, 3),
            "consistency_down": round(consistency_down, 3),
            "vol_ratio":        round(vol_ratio, 3),
            "magnitude":        round(magnitude, 5),
            "avg_spread":       round(avg_spread, 4),
            "current_price":    prices[-1],
            "price_start":      prices[0],
            "price_high":       max(prices[-lookback:]) if lookback > 0 else prices[-1],
            "price_low":        min(prices[-lookback:]) if lookback > 0 else prices[-1],
            "n_periods":        n,
        }

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────
    @staticmethod
    def _safe_logit(p):
        """logit(p) = ln(p / (1-p)), clampé pour éviter inf."""
        p = max(0.01, min(0.99, p))
        return math.log(p / (1 - p))

    @staticmethod
    def _ema(data, period):
        """Exponential Moving Average."""
        if not data or period <= 0:
            return []
        alpha = 2.0 / (period + 1)
        result = [data[0]]
        for i in range(1, len(data)):
            result.append(alpha * data[i] + (1 - alpha) * result[-1])
        return result
