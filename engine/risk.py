"""
RiskManager — Sizing de position, limites d'exposition, circuit breakers.

Règles principales :
  - Max 3% du capital par trade
  - Max 5% sur un seul marché
  - Max 5 positions simultanées
  - Max 20% d'exposition totale
  - Pause si drawdown > 10%
  - Pause si perte journalière > 5%
  - Cooldown après 3 pertes consécutives
  - Kelly fractional pour le sizing dynamique
"""

import time
import config


class RiskManager:

    def __init__(self):
        self.daily_pnl             = 0.0
        self.daily_reset_time      = time.time()
        self.consecutive_losses    = 0
        self.last_loss_time        = 0.0
        self.is_paused             = False
        self.pause_reason          = ""
        self.total_trades          = 0
        self.total_rejected        = 0

    def check_can_trade(self, portfolio):
        """
        Vérifie si le bot peut ouvrir un nouveau trade.
        Retourne (can_trade: bool, reason: str).
        """
        now = time.time()

        # Reset daily PnL chaque 24h
        if now - self.daily_reset_time > 86400:
            self.daily_pnl = 0.0
            self.daily_reset_time = now

        cap = portfolio.capital

        # ── Circuit breaker : drawdown max
        dd = portfolio.drawdown_pct()
        if dd > config.MAX_DRAWDOWN_PCT:
            self.is_paused = True
            self.pause_reason = f"drawdown:{dd:.1f}%"
            return False, self.pause_reason

        # ── Circuit breaker : perte journalière
        daily_limit = cap * config.MAX_DAILY_LOSS_PCT / 100
        if abs(self.daily_pnl) > daily_limit and self.daily_pnl < 0:
            self.is_paused = True
            self.pause_reason = f"daily_loss:${abs(self.daily_pnl):.0f}"
            return False, self.pause_reason

        # ── Pertes consécutives
        if self.consecutive_losses >= config.PAUSE_AFTER_CONSECUTIVE_LOSSES:
            cooldown = config.COOLDOWN_AFTER_LOSS_SEC * 2
            if now - self.last_loss_time < cooldown:
                return False, f"consecutive_losses:{self.consecutive_losses}"
            else:
                self.consecutive_losses = 0  # reset après cooldown

        # ── Cooldown après perte
        if self.last_loss_time > 0 and now - self.last_loss_time < config.COOLDOWN_AFTER_LOSS_SEC:
            return False, "loss_cooldown"

        # ── Max positions simultanées
        if len(portfolio.positions) >= config.MAX_CONCURRENT_POSITIONS:
            return False, f"max_positions:{len(portfolio.positions)}"

        # ── Max exposition
        exposure = portfolio.total_exposure_pct()
        if exposure >= config.MAX_EXPOSURE_PCT:
            return False, f"max_exposure:{exposure:.1f}%"

        # ── Capital minimum viable
        if cap < 10:
            self.is_paused = True
            self.pause_reason = "capital_depleted"
            return False, self.pause_reason

        self.is_paused = False
        self.pause_reason = ""
        return True, "ok"

    def size_position(self, signal, portfolio, snap):
        """
        Calcule la taille de position optimale.
        Utilise Kelly fractional pondéré par le score du signal.
        """
        cap = portfolio.total_equity()
        if cap <= 0:
            return 0

        # Taille de base : RISK_PER_TRADE_PCT du capital
        base_size = cap * config.RISK_PER_TRADE_PCT / 100

        # Pondération par score (score 3/5 = 60%, score 5/5 = 100%)
        score_weight = min(1.0, signal.score / 5.0)

        # Kelly fractional : f* = (p*b - q) / b
        est_win_prob = min(0.80, 0.30 + score_weight * 0.50)
        payout = (1.0 / signal.price) - 1.0 if signal.price > 0 else 0
        if payout > 0:
            kelly = (est_win_prob * payout - (1 - est_win_prob)) / payout
            kelly = max(0, min(0.08, kelly))  # cap à 8%
        else:
            kelly = 0

        # Blend base sizing avec kelly
        if kelly > 0:
            size = base_size * score_weight * (0.5 + kelly / 0.08 * 0.5)
        else:
            size = base_size * score_weight * 0.5

        # Caps
        max_pos = cap * config.MAX_POSITION_PCT / 100
        size = min(size, max_pos)

        # Budget d'exposition restant
        remaining = (config.MAX_EXPOSURE_PCT / 100 * cap) - portfolio.total_exposure()
        size = min(size, max(0, remaining))

        # Minimum viable
        if size < 5:
            return 0

        return round(size, 2)

    def register_trade_result(self, pnl):
        """Met à jour l'état du risk manager après fermeture d'un trade."""
        self.daily_pnl += pnl
        self.total_trades += 1
        if pnl < 0:
            self.consecutive_losses += 1
            self.last_loss_time = time.time()
        else:
            self.consecutive_losses = 0

    def get_state(self):
        return {
            "is_paused":          self.is_paused,
            "pause_reason":       self.pause_reason,
            "daily_pnl":          round(self.daily_pnl, 2),
            "consecutive_losses": self.consecutive_losses,
            "total_trades":       self.total_trades,
            "total_rejected":     self.total_rejected,
        }
