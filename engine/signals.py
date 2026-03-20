"""
SignalEngine — Génère des signaux de trading à partir de l'analyse de tendance.

Système de scoring : 5 composantes, chacune 0-1 point.
Score total sur 5. Seuil d'entrée configurable.

Composantes :
  1. EMA alignment  — EMA fast/slow alignées avec la direction
  2. Momentum       — magnitude du mouvement
  3. Consistency     — % de périodes dans la même direction
  4. Volume         — volume récent vs ancien
  5. Acceleration   — la tendance accélère-t-elle ?

Anti-bruit :
  - Magnitude minimum (BREAKOUT_THRESHOLD)
  - Spread vs magnitude check
  - Confirmation sur N périodes avant exécution
"""

import time
import config


class Signal:
    """Représente un signal de trading détecté."""

    def __init__(self, market_id, direction, score, components, price, meta):
        self.market_id   = market_id
        self.direction   = direction      # "YES" ou "NO"
        self.score       = score
        self.components  = components
        self.price       = price          # prix d'entrée estimé
        self.meta        = meta or {}
        self.timestamp   = time.time()
        self.confirmation_count = 0

    def to_dict(self):
        return {
            "market_id":   self.market_id,
            "direction":   self.direction,
            "score":       self.score,
            "components":  self.components,
            "price":       self.price,
            "question":    self.meta.get("question", "Unknown"),
            "category":    self.meta.get("category", "Other"),
            "status":      "confirmed" if self.confirmation_count >= config.CONFIRMATION_PERIODS else "pending",
            "confirmations": self.confirmation_count,
            "age_sec":     round(time.time() - self.timestamp),
        }


class SignalEngine:

    def __init__(self):
        self.pending_signals = {}   # market_id → Signal (en attente de confirmation)

    def evaluate(self, market_id, trend, snap, meta):
        """
        Évalue les indicateurs de tendance et retourne un Signal ou None.
        """
        if not trend or not snap:
            return None

        price  = snap["yes"]
        spread = snap["spread"]

        # Pas de signal pour les marchés plats
        if trend["direction"] == "flat":
            self.pending_signals.pop(market_id, None)
            return None

        # ── Score chaque composante (0-1) ──
        components = {}
        score = 0.0

        # 1. EMA alignment
        if trend["direction"] == "up" and trend["ema_bullish"]:
            components["ema"] = 1.0
        elif trend["direction"] == "down" and not trend["ema_bullish"]:
            components["ema"] = 1.0
        else:
            components["ema"] = 0.0
        score += components["ema"]

        # Bonus si croisement EMA récent
        if trend["ema_cross"]:
            components["ema"] = min(1.0, components["ema"] + 0.3)
            score += 0.3

        # 2. Momentum (magnitude normalisée)
        mom = min(1.0, trend["magnitude"] / 0.02)   # score plein à 2¢ move
        components["momentum"] = round(mom, 3)
        score += mom

        # 3. Consistance directionnelle
        if trend["direction"] == "up":
            cons = trend["consistency_up"]
        else:
            cons = trend["consistency_down"]
        cons_score = max(0.0, (cons - 0.35) / 0.30)  # 0 en dessous de 35%, 1 à 65%+
        components["consistency"] = round(min(1.0, cons_score), 3)
        score += components["consistency"]

        # 4. Volume confirmation
        vr = trend["vol_ratio"]
        vol_score = min(1.0, max(0.0, (vr - 0.80) / 0.70))
        components["volume"] = round(vol_score, 3)
        score += vol_score

        # 5. Accélération
        if trend["direction"] == "up" and trend["acceleration"] > 0:
            acc = min(1.0, trend["acceleration"] / 0.005)
        elif trend["direction"] == "down" and trend["acceleration"] < 0:
            acc = min(1.0, abs(trend["acceleration"]) / 0.005)
        else:
            acc = 0.0
        components["acceleration"] = round(acc, 3)
        score += acc

        score = round(score, 2)

        # ── Direction mapping ──
        if trend["direction"] == "up":
            direction   = "YES"
            entry_price = price + spread / 2    # on achète au ask
        else:
            direction   = "NO"
            entry_price = (1 - price) + spread / 2

        # ── Filtres anti-bruit ──

        # Magnitude trop faible
        if trend["magnitude"] < config.BREAKOUT_THRESHOLD:
            return None

        # Score trop bas
        if score < config.ENTRY_SCORE_THRESHOLD:
            return None

        # Spread trop large par rapport au mouvement (relaxé)
        if spread > 0 and spread > trend["magnitude"] * 2.0:
            return None

        # Edge insuffisant après frais
        gross_edge = trend["magnitude"]
        net_edge   = gross_edge - (config.FEE_PCT / 100) * 0.5 - (config.SLIPPAGE_PCT / 100)
        if net_edge < config.MIN_EDGE_PCT / 100:
            return None

        return Signal(
            market_id=market_id,
            direction=direction,
            score=score,
            components=components,
            price=round(entry_price, 4),
            meta=meta,
        )

    def confirm(self, signal, trend):
        """
        Vérifie si un signal pending est confirmé (tendance tenue N périodes).
        Retourne True (confirmé), False (invalidé), None (en attente).
        """
        if signal.direction == "YES" and trend["direction"] != "up":
            return False
        if signal.direction == "NO" and trend["direction"] != "down":
            return False

        signal.confirmation_count += 1

        if signal.confirmation_count >= config.CONFIRMATION_PERIODS:
            return True
        return None
