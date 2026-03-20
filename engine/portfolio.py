"""
Portfolio — Portefeuille virtuel pour le paper trading.

Gère les positions ouvertes, le capital, les P&L, et la courbe d'équité.
Chaque position a un trailing stop, un take profit, et un time stop.
Exécution réaliste : slippage à l'entrée, frais à l'entrée ET à la sortie.
"""

import time
import threading
import config


class Position:
    """Une position ouverte sur un marché."""

    def __init__(self, market_id, direction, entry_price, size, signal_score, meta):
        self.market_id    = market_id
        self.direction    = direction      # "YES" ou "NO"
        self.entry_price  = entry_price
        self.size         = size
        self.shares       = size / entry_price
        self.signal_score = signal_score
        self.meta         = meta or {}
        self.opened_at    = time.time()

        # Trailing stop
        self.peak_price    = entry_price
        self.trailing_stop = entry_price - config.TRAILING_STOP_DISTANCE

        # État courant
        self.current_price   = entry_price
        self.unrealized_pnl  = 0.0
        self.entry_fees      = round(size * config.FEE_PCT / 100, 2)

    def update(self, current_yes_price, spread):
        """Met à jour la position avec le prix courant."""
        if self.direction == "YES":
            self.current_price = current_yes_price
        else:
            self.current_price = 1.0 - current_yes_price

        # Mettre à jour le trailing stop
        if self.current_price > self.peak_price:
            self.peak_price = self.current_price
            self.trailing_stop = self.peak_price - config.TRAILING_STOP_DISTANCE

        # P&L non réalisé (brut - frais d'entrée)
        current_value = self.shares * self.current_price
        self.unrealized_pnl = current_value - self.size - self.entry_fees

    def should_exit(self, trend, snap):
        """
        Vérifie les conditions de sortie.
        Retourne (should_exit: bool, reason: str).
        """
        now = time.time()
        age_hours = (now - self.opened_at) / 3600

        # 1. Trailing stop
        if self.current_price <= self.trailing_stop:
            return True, "trailing_stop"

        # 2. Take profit
        profit_pct = (self.current_price - self.entry_price) / self.entry_price
        if profit_pct >= config.TAKE_PROFIT_DISTANCE:
            return True, "take_profit"

        # 3. Time stop (pas de mouvement après X heures)
        if age_hours >= config.TIME_STOP_HOURS:
            return True, "time_stop"

        # 4. Retournement de tendance confirmé
        if trend:
            if self.direction == "YES" and trend["direction"] == "down":
                if trend["magnitude"] > config.BREAKOUT_THRESHOLD:
                    return True, "trend_reversal"
            elif self.direction == "NO" and trend["direction"] == "up":
                if trend["magnitude"] > config.BREAKOUT_THRESHOLD:
                    return True, "trend_reversal"

        # 5. Explosion du spread (liquidité qui sèche)
        if snap and snap["spread"] > config.MAX_SPREAD * 2:
            return True, "spread_blowout"

        # 6. Données obsolètes (marché peut-être résolu)
        if snap:
            data_age = now - snap.get("ts", now)
            if data_age > config.POLL_INTERVAL * 10 and age_hours > 1:
                return True, "stale_data"

        return False, ""

    def close(self):
        """Ferme la position, calcule le P&L réalisé."""
        # Frais de sortie
        exit_value = self.shares * self.current_price
        exit_fees  = round(exit_value * config.FEE_PCT / 100, 2)
        slippage   = round(self.size * config.SLIPPAGE_PCT / 100, 2)

        gross_pnl = exit_value - self.size
        net_pnl   = gross_pnl - self.entry_fees - exit_fees - slippage

        return {
            "market_id":      self.market_id,
            "direction":      self.direction,
            "entry_price":    round(self.entry_price, 4),
            "exit_price":     round(self.current_price, 4),
            "size":           self.size,
            "shares":         round(self.shares, 4),
            "gross_pnl":      round(gross_pnl, 2),
            "entry_fees":     self.entry_fees,
            "exit_fees":      exit_fees,
            "slippage":       slippage,
            "total_fees":     round(self.entry_fees + exit_fees + slippage, 2),
            "net_pnl":        round(net_pnl, 2),
            "duration_hours": round((time.time() - self.opened_at) / 3600, 1),
            "signal_score":   self.signal_score,
            "question":       self.meta.get("question", "Unknown"),
            "category":       self.meta.get("category", "Other"),
        }

    def to_dict(self):
        return {
            "market_id":     self.market_id,
            "question":      self.meta.get("question", ""),
            "direction":     self.direction,
            "entry_price":   round(self.entry_price, 4),
            "current_price": round(self.current_price, 4),
            "size":          self.size,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "duration_hours": round((time.time() - self.opened_at) / 3600, 1),
            "trailing_stop": round(self.trailing_stop, 4),
            "peak_price":    round(self.peak_price, 4),
            "signal_score":  self.signal_score,
        }


class Portfolio:
    """Portefeuille virtuel — paper trading."""

    def __init__(self, initial_capital=None):
        self.initial_capital = initial_capital or config.INITIAL_CAPITAL
        self.capital         = self.initial_capital
        self.peak_capital    = self.initial_capital
        self.positions       = {}     # market_id → Position
        self.closed_trades   = []
        self.equity_curve    = [{"ts": time.time(), "equity": self.initial_capital}]
        self._lock           = threading.Lock()

    def open_position(self, market_id, direction, entry_price, size, signal_score, meta):
        """Ouvre une position paper."""
        with self._lock:
            if market_id in self.positions:
                return None     # déjà dans ce marché

            # Slippage à l'entrée
            slipped = entry_price * (1 + config.SLIPPAGE_PCT / 100)
            slipped = min(0.99, slipped)

            pos = Position(market_id, direction, slipped, size, signal_score, meta)
            self.positions[market_id] = pos
            self.capital -= size
            return pos

    def close_position(self, market_id):
        """Ferme une position et enregistre le résultat."""
        with self._lock:
            pos = self.positions.pop(market_id, None)
            if not pos:
                return None

            result = pos.close()

            # Retour du capital + P&L
            self.capital += pos.size + result["net_pnl"]

            if self.capital > self.peak_capital:
                self.peak_capital = self.capital

            result["closed_at"] = time.time()
            self.closed_trades.append(result)

            # Point d'équité
            self.equity_curve.append({
                "ts":     time.time(),
                "equity": round(self.total_equity_unlocked(), 2),
            })

            return result

    def update_positions(self, feed):
        """Met à jour toutes les positions avec les prix courants."""
        with self._lock:
            for mid, pos in self.positions.items():
                snap = feed.get_current(mid)
                if snap:
                    pos.update(snap["yes"], snap["spread"])

    def record_equity(self):
        """Enregistre un point d'équité (appelé chaque cycle)."""
        with self._lock:
            self.equity_curve.append({
                "ts":     time.time(),
                "equity": round(self.total_equity_unlocked(), 2),
            })
            # Garder max 2000 points
            if len(self.equity_curve) > 2000:
                self.equity_curve = self.equity_curve[-1500:]

    # ──────────────────────────────────────────────
    # Métriques (appellées AVEC le lock quand from get_state,
    #            ou SANS lock pour usage interne)
    # ──────────────────────────────────────────────
    def total_equity_unlocked(self):
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        invested   = sum(p.size for p in self.positions.values())
        return self.capital + invested + unrealized

    def total_equity(self):
        with self._lock:
            return self.total_equity_unlocked()

    def total_exposure(self):
        with self._lock:
            return self._total_exposure_unlocked()

    # --- Unlocked metric helpers (caller must hold self._lock) ---

    def _total_exposure_unlocked(self):
        return sum(p.size for p in self.positions.values())

    def _total_exposure_pct_unlocked(self):
        eq = self.total_equity_unlocked()
        return (self._total_exposure_unlocked() / eq * 100) if eq > 0 else 0

    def _drawdown_pct_unlocked(self):
        eq = self.total_equity_unlocked()
        if self.peak_capital <= 0:
            return 0
        return max(0, (self.peak_capital - eq) / self.peak_capital * 100)

    def _win_rate_unlocked(self):
        if not self.closed_trades:
            return 0
        wins = sum(1 for t in self.closed_trades if t["net_pnl"] > 0)
        return wins / len(self.closed_trades) * 100

    def _expectancy_unlocked(self):
        if not self.closed_trades:
            return 0
        return sum(t["net_pnl"] for t in self.closed_trades) / len(self.closed_trades)

    def _profit_factor_unlocked(self):
        wins   = sum(t["net_pnl"] for t in self.closed_trades if t["net_pnl"] > 0)
        losses = abs(sum(t["net_pnl"] for t in self.closed_trades if t["net_pnl"] < 0))
        return wins / losses if losses > 0 else float('inf')

    # --- Public locked versions ---

    def total_exposure_pct(self):
        with self._lock:
            return self._total_exposure_pct_unlocked()

    def drawdown_pct(self):
        with self._lock:
            return self._drawdown_pct_unlocked()

    def win_rate(self):
        with self._lock:
            return self._win_rate_unlocked()

    def total_pnl(self):
        with self._lock:
            return self.total_equity_unlocked() - self.initial_capital

    def expectancy(self):
        with self._lock:
            return self._expectancy_unlocked()

    def profit_factor(self):
        with self._lock:
            return self._profit_factor_unlocked()

    def get_state(self):
        """État complet pour l'API / dashboard."""
        with self._lock:
            positions = [pos.to_dict() for pos in self.positions.values()]

            eq = self.total_equity_unlocked()
            pnl = eq - self.initial_capital
            pf = self._profit_factor_unlocked() if self.closed_trades else 0

            return {
                "initial_capital":  self.initial_capital,
                "capital":          round(self.capital, 2),
                "total_equity":     round(eq, 2),
                "total_pnl":        round(pnl, 2),
                "pnl_pct":          round(pnl / self.initial_capital * 100, 2) if self.initial_capital > 0 else 0,
                "peak_capital":     round(self.peak_capital, 2),
                "drawdown_pct":     round(self._drawdown_pct_unlocked(), 2),
                "exposure":         round(self._total_exposure_unlocked(), 2),
                "exposure_pct":     round(self._total_exposure_pct_unlocked(), 2),
                "win_rate":         round(self._win_rate_unlocked(), 1),
                "expectancy":       round(self._expectancy_unlocked(), 2),
                "profit_factor":    round(min(99.99, pf), 2),
                "n_positions":      len(self.positions),
                "n_closed":         len(self.closed_trades),
                "positions":        positions,
                "closed_trades":    self.closed_trades[-50:],
                "equity_curve":     self.equity_curve[-500:],
            }
