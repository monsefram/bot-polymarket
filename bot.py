"""
Polymarket Trend-Following Bot — Orchestrateur principal.

Boucle principale :
  1. Poll les données de marché (DataFeed)
  2. Met à jour les positions ouvertes
  3. Vérifie les conditions de sortie
  4. Analyse les tendances (TrendEngine)
  5. Génère les signaux (SignalEngine)
  6. Applique le risk management (RiskManager)
  7. Exécute les trades paper (Portfolio)
  8. Journalise tout (Journal)
  9. Enregistre l'équité
  10. Sleep → recommence

Architecture :
  DataFeed → MarketFilter → TrendEngine → SignalEngine
      → RiskManager → Portfolio → Journal
"""

import time
import threading

import config
from engine.data_feed import DataFeed
from engine.market_filter import MarketFilter
from engine.trend import TrendEngine
from engine.signals import SignalEngine
from engine.risk import RiskManager
from engine.portfolio import Portfolio
from engine.journal import Journal
from engine.analyst import AIAnalyst


class Bot:

    def __init__(self):
        # Modules
        self.feed      = DataFeed()
        self.filter    = MarketFilter()
        self.trend     = TrendEngine()
        self.signals   = SignalEngine()
        self.risk      = RiskManager()
        self.portfolio = Portfolio()
        self.journal   = Journal()
        self.analyst   = AIAnalyst()

        # État
        self.running         = False
        self._thread         = None
        self.cycle_count     = 0
        self.last_cycle_time = 0.0
        self.status          = "stopped"
        self.warmup_done     = False

        # Données de cycle
        self.active_signals  = {}   # market_id → signal.to_dict()
        self.trend_data      = {}   # market_id → trend dict
        self.filter_results  = {}   # market_id → (passed, reasons)

    # ══════════════════════════════════════════════
    # Contrôle
    # ══════════════════════════════════════════════
    def start(self):
        if self.running:
            return
        self.running = True
        self.status  = "starting"
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.journal.log("bot_start", {
            "capital":       self.portfolio.initial_capital,
            "poll_interval": config.POLL_INTERVAL,
        })
        print("  [BOT] Démarré — paper trading mode")

    def stop(self):
        self.running = False
        self.status  = "stopped"
        self.journal.log("bot_stop", {
            "cycles":   self.cycle_count,
            "equity":   round(self.portfolio.total_equity(), 2),
        })
        print("  [BOT] Arrêté")

    def reset(self):
        """Reset le bot (nouveau portefeuille, clear historique)."""
        was_running = self.running
        if was_running:
            self.stop()
            time.sleep(1)

        self.portfolio     = Portfolio()
        self.risk          = RiskManager()
        self.analyst       = AIAnalyst()
        self.cycle_count   = 0
        self.warmup_done   = False
        self.active_signals = {}
        self.trend_data     = {}
        self.journal.log("bot_reset", {})
        print("  [BOT] Reset — capital: $" + str(self.portfolio.initial_capital))

        if was_running:
            self.start()

    # ══════════════════════════════════════════════
    # Boucle principale
    # ══════════════════════════════════════════════
    def _run_loop(self):
        while self.running:
            try:
                self._cycle()
            except Exception as e:
                self.journal.log("cycle_error", {"error": str(e)})
                print(f"  [BOT] Erreur cycle #{self.cycle_count}: {e}")

            time.sleep(config.POLL_INTERVAL)

    def _cycle(self):
        t0 = time.time()
        self.cycle_count += 1

        # ── 1. Poll données
        updated = self.feed.poll()
        n_tracked = len(self.feed.get_all_tracked())

        # Warmup check
        if not self.warmup_done:
            max_hist = max(
                (self.feed.history_length(mid) for mid in self.feed.get_all_tracked()),
                default=0
            )
            if max_hist >= config.MIN_HISTORY:
                self.warmup_done = True
                self.status = "running"
                self.journal.log("warmup_complete", {"cycles": self.cycle_count})
                print(f"  [BOT] Warmup terminé — {n_tracked} marchés suivis")
            else:
                self.status = "warming_up"
                progress = max_hist / config.MIN_HISTORY * 100
                if self.cycle_count % 3 == 0:
                    print(f"  [BOT] Warmup: {progress:.0f}% "
                          f"({max_hist}/{config.MIN_HISTORY} snapshots)")
                self.last_cycle_time = time.time() - t0
                return

        # ── 2. Mettre à jour les positions ouvertes
        self.portfolio.update_positions(self.feed)

        # ── 3. Vérifier les sorties
        self._check_exits()

        # ── 4. Analyser les tendances et générer les signaux
        signals_found = 0
        for mid in self.feed.get_all_tracked():
            # Filtrer le marché
            passed, reasons = self.filter.filter(mid, self.feed)
            self.filter_results[mid] = (passed, reasons)
            if not passed:
                continue

            # Calculer la tendance
            history = self.feed.get_history(mid)
            trend   = self.trend.analyze(history)
            if not trend:
                continue

            self.trend_data[mid] = trend

            # Générer le signal
            snap = self.feed.get_current(mid)
            meta = self.feed.get_meta(mid)

            # Pas de signal si on a déjà une position sur ce marché
            if mid in self.portfolio.positions:
                continue

            signal = self.signals.evaluate(mid, trend, snap, meta)

            if signal:
                # Signal pending existant → vérifier confirmation
                if mid in self.signals.pending_signals:
                    existing = self.signals.pending_signals[mid]
                    result   = self.signals.confirm(existing, trend)

                    if result is True:
                        # ✓ Signal confirmé → AI analysis + open
                        self._try_open_with_ai(existing, snap, meta)
                        del self.signals.pending_signals[mid]
                        self.active_signals.pop(mid, None)
                    elif result is False:
                        # ✗ Signal invalidé
                        del self.signals.pending_signals[mid]
                        self.active_signals.pop(mid, None)
                        self.journal.log("signal_invalidated", {
                            "market":  mid,
                            "question": (meta or {}).get("question", ""),
                        })
                    else:
                        # En attente de confirmation
                        self.active_signals[mid] = existing.to_dict()
                else:
                    # Nouveau signal → ajouter au pending
                    self.signals.pending_signals[mid] = signal
                    self.active_signals[mid] = signal.to_dict()
                    signals_found += 1
                    self.journal.log("signal_detected", {
                        "market":    mid,
                        "question":  (meta or {}).get("question", ""),
                        "direction": signal.direction,
                        "score":     signal.score,
                        "price":     signal.price,
                        "components": signal.components,
                    })

        # ── 5. Nettoyer les signaux expirés
        now = time.time()
        stale = [mid for mid, s in self.signals.pending_signals.items()
                 if now - s.timestamp > config.MAX_ENTRY_DELAY * config.POLL_INTERVAL]
        for mid in stale:
            del self.signals.pending_signals[mid]
            self.active_signals.pop(mid, None)
            self.journal.log("signal_expired", {"market": mid})

        # ── 5b. AI proactive scan — analyse les top marches sans signal technique
        if (self.analyst.enabled and config.AI_ANALYZE_TOP_MARKETS > 0
                and self.cycle_count % 3 == 0):  # tous les 3 cycles (~90s)
            self._ai_proactive_scan()

        # ── 6. Enregistrer l'équité
        self.portfolio.record_equity()

        # ── 7. Log cycle
        self.last_cycle_time = time.time() - t0

        if self.cycle_count % 5 == 0:
            eq    = self.portfolio.total_equity()
            n_pos = len(self.portfolio.positions)
            pnl   = self.portfolio.total_pnl()
            print(f"  [BOT] #{self.cycle_count:>4} | "
                  f"${eq:>7.0f} ({pnl:+.0f}) | "
                  f"{n_pos} pos | {n_tracked} marchés | "
                  f"{signals_found} sig | {self.last_cycle_time:.1f}s")

    # ══════════════════════════════════════════════
    # Trading
    # ══════════════════════════════════════════════
    def _try_open_with_ai(self, signal, snap, meta):
        """Signal confirme → analyse AI → decision combinee → ouvrir."""
        ai_verdict = None
        combined_score = signal.score

        # ── AI Analysis (si actif)
        if self.analyst.enabled and config.AI_ANALYZE_ON_SIGNAL:
            question = (meta or {}).get("question", "")
            category = (meta or {}).get("category", "")
            end_date = (meta or {}).get("endDate", "")
            volume   = snap.get("vol", 0) if snap else 0

            ai_verdict = self.analyst.analyze(
                market_id=signal.market_id,
                question=question,
                market_price=snap["yes"] if snap else signal.price,
                category=category,
                volume=volume,
                end_date=end_date,
            )

            if ai_verdict:
                # ── Combiner score technique + AI
                ai_confirms = (
                    ai_verdict.direction == signal.direction
                    and ai_verdict.abs_edge >= config.AI_MIN_EDGE_PCT / 100
                    and ai_verdict.confidence >= config.AI_MIN_CONFIDENCE
                )

                if ai_confirms:
                    # AI confirme le signal technique → boost
                    combined_score = (
                        signal.score * config.TECH_WEIGHT
                        + (ai_verdict.abs_edge * 100) * config.AI_WEIGHT
                        + config.AI_SCORE_BOOST
                    )
                    self.journal.log("ai_confirms", {
                        "market":     signal.market_id,
                        "question":   question[:80],
                        "direction":  signal.direction,
                        "ai_prob":    ai_verdict.ai_probability,
                        "mkt_price":  ai_verdict.market_price,
                        "edge":       round(ai_verdict.edge, 4),
                        "confidence": ai_verdict.confidence,
                        "combined":   round(combined_score, 2),
                        "reasoning":  ai_verdict.reasoning[:150],
                    })
                else:
                    # AI contredit ou pas assez de confiance
                    if ai_verdict.direction != signal.direction and ai_verdict.confidence >= 0.5:
                        # AI est confiante dans la direction opposee → BLOQUER
                        self.journal.log("ai_blocks", {
                            "market":    signal.market_id,
                            "question":  question[:80],
                            "tech_dir":  signal.direction,
                            "ai_dir":    ai_verdict.direction,
                            "ai_edge":   round(ai_verdict.edge, 4),
                            "confidence": ai_verdict.confidence,
                            "reasoning": ai_verdict.reasoning[:150],
                        })
                        print(f"  [AI] BLOQUE {signal.direction} sur {question[:50]} "
                              f"(AI dit {ai_verdict.direction}, conf={ai_verdict.confidence:.0%})")
                        return
                    # AI pas confiante → score technique seul, pas de boost
                    combined_score = signal.score

        # ── Proceed with original _try_open logic
        self._try_open(signal, snap, combined_score, ai_verdict)

    def _try_open(self, signal, snap, combined_score=None, ai_verdict=None):
        """Tente d'ouvrir une position à partir d'un signal confirmé."""
        if combined_score is None:
            combined_score = signal.score

        # Risk check
        can_trade, reason = self.risk.check_can_trade(self.portfolio)
        if not can_trade:
            self.risk.total_rejected += 1
            self.journal.log("trade_rejected", {
                "market":  signal.market_id,
                "reason":  reason,
                "question": signal.meta.get("question", ""),
            })
            return

        # Position sizing
        size = self.risk.size_position(signal, self.portfolio, snap)
        if size <= 0:
            self.journal.log("trade_rejected", {
                "market": signal.market_id,
                "reason": "size_zero",
            })
            return

        # Si AI a confirme avec haut edge, augmenter la taille
        if ai_verdict and ai_verdict.abs_edge >= 0.10 and ai_verdict.confidence >= 0.6:
            size = min(size * 1.5, self.portfolio.capital * config.MAX_POSITION_PCT / 100)
            self.journal.log("ai_size_boost", {
                "market": signal.market_id,
                "edge":   round(ai_verdict.abs_edge, 4),
                "new_size": round(size, 2),
            })

        # Exécuter le trade paper
        pos = self.portfolio.open_position(
            market_id=signal.market_id,
            direction=signal.direction,
            entry_price=signal.price,
            size=size,
            signal_score=combined_score,
            meta=signal.meta,
        )

        if pos:
            log_data = {
                "market":    signal.market_id,
                "question":  signal.meta.get("question", ""),
                "direction": signal.direction,
                "price":     round(pos.entry_price, 4),
                "size":      round(size, 2),
                "tech_score": signal.score,
                "combined_score": round(combined_score, 2),
                "capital":   round(self.portfolio.capital, 2),
                "equity":    round(self.portfolio.total_equity(), 2),
            }
            if ai_verdict:
                log_data["ai_edge"]   = round(ai_verdict.edge, 4)
                log_data["ai_conf"]   = ai_verdict.confidence
                log_data["ai_reason"] = ai_verdict.reasoning[:100]
            self.journal.log("trade_opened", log_data)

    def _check_exits(self):
        """Vérifie les conditions de sortie pour toutes les positions."""
        to_close = []

        for mid, pos in list(self.portfolio.positions.items()):
            trend = self.trend_data.get(mid)
            snap  = self.feed.get_current(mid)
            should_exit, reason = pos.should_exit(trend, snap)
            if should_exit:
                to_close.append((mid, reason))

        for mid, reason in to_close:
            result = self.portfolio.close_position(mid)
            if result:
                self.risk.register_trade_result(result["net_pnl"])
                self.journal.log("trade_closed", {
                    "market":    mid,
                    "question":  result.get("question", ""),
                    "reason":    reason,
                    "direction": result["direction"],
                    "entry":     result["entry_price"],
                    "exit":      result["exit_price"],
                    "gross_pnl": result["gross_pnl"],
                    "fees":      result["total_fees"],
                    "net_pnl":   result["net_pnl"],
                    "duration":  result["duration_hours"],
                })
                emoji = "✓" if result["net_pnl"] >= 0 else "✗"
                print(f"  [BOT] {emoji} Ferme {result['direction']} | "
                      f"P&L: ${result['net_pnl']:+.1f} | "
                      f"Raison: {reason} | "
                      f"{result['question'][:50]}")

    def _ai_proactive_scan(self):
        """Scan proactif AI : analyse les meilleurs marches pour trouver des edges.
        Inspiré des top traders du leaderboard qui ont un avantage informationnel."""
        if not self.analyst.enabled:
            return

        # Selectionner les marches les plus interessants a analyser
        candidates = []
        for mid in self.feed.get_all_tracked():
            # Ignorer si deja une position
            if mid in self.portfolio.positions:
                continue
            # Ignorer si deja en cache AI
            if self.analyst.cache.get(mid):
                continue

            passed, _ = self.filter_results.get(mid, (False, []))
            if not passed:
                continue

            snap = self.feed.get_current(mid)
            meta = self.feed.get_meta(mid)
            if not snap or not meta:
                continue

            # Prioriser les marches a prix incertain (30-70%) et fort volume
            price = snap["yes"]
            uncertainty = 1.0 - abs(price - 0.5) * 2  # max a 50%, 0 a 0/100%
            score = uncertainty * snap.get("vol", 0)
            candidates.append((mid, score, snap, meta))

        candidates.sort(key=lambda x: x[1], reverse=True)

        # Analyser les top N
        analyzed = 0
        for mid, _, snap, meta in candidates[:config.AI_ANALYZE_TOP_MARKETS]:
            verdict = self.analyst.analyze(
                market_id=mid,
                question=meta.get("question", ""),
                market_price=snap["yes"],
                category=meta.get("category", ""),
                volume=snap.get("vol", 0),
                end_date=meta.get("endDate", ""),
            )

            if not verdict:
                continue
            analyzed += 1

            # Si l'AI trouve un gros edge, creer un signal AI-only
            if (verdict.abs_edge >= config.AI_MIN_EDGE_PCT / 100
                    and verdict.confidence >= 0.5
                    and mid not in self.signals.pending_signals):

                from engine.signals import Signal
                ai_signal = Signal(
                    market_id=mid,
                    direction=verdict.direction,
                    score=config.AI_SCORE_BOOST + verdict.abs_edge * 10,
                    components={
                        "ai_edge": round(verdict.abs_edge, 4),
                        "ai_confidence": verdict.confidence,
                        "ai_only": True,
                    },
                    price=snap["yes"] if verdict.direction == "YES" else (1 - snap["yes"]),
                    meta=meta,
                )
                ai_signal.confirmation_count = config.CONFIRMATION_PERIODS  # pre-confirme

                self._try_open(ai_signal, snap, ai_signal.score, verdict)

                self.journal.log("ai_proactive_trade", {
                    "market":     mid,
                    "question":   meta.get("question", "")[:80],
                    "direction":  verdict.direction,
                    "ai_prob":    verdict.ai_probability,
                    "mkt_price":  snap["yes"],
                    "edge":       round(verdict.edge, 4),
                    "confidence": verdict.confidence,
                })

        if analyzed > 0:
            print(f"  [AI] Scan proactif: {analyzed} marches analyses")

    # ══════════════════════════════════════════════
    # API — état complet pour le dashboard
    # ══════════════════════════════════════════════
    def get_state(self):
        portfolio_state = self.portfolio.get_state()

        # Marchés suivis avec données de tendance
        tracked_markets = []
        for mid in self.feed.get_all_tracked():
            meta = self.feed.get_meta(mid)
            snap = self.feed.get_current(mid)
            trend = self.trend_data.get(mid)
            passed, reasons = self.filter_results.get(mid, (False, []))

            if not meta or not snap:
                continue

            info = {
                "id":           mid,
                "question":     meta.get("question", ""),
                "category":     meta.get("category", ""),
                "slug":         meta.get("slug", ""),
                "yes_price":    round(snap["yes"], 4),
                "spread":       round(snap["spread"], 4),
                "volume":       round(snap["vol"], 0),
                "liquidity":    round(snap["liq"], 0),
                "passes_filter": passed,
                "filter_reasons": reasons if not passed else [],
                "has_signal":   mid in self.active_signals,
                "has_position": mid in self.portfolio.positions,
                "history_len":  self.feed.history_length(mid),
            }

            if trend:
                info["trend"] = {
                    "direction":   trend["direction"],
                    "roc":         trend["roc"],
                    "velocity":    trend["velocity"],
                    "acceleration": trend["acceleration"],
                    "magnitude":   trend["magnitude"],
                    "consistency": round(max(trend["consistency_up"],
                                             trend["consistency_down"]), 3),
                    "vol_ratio":   trend["vol_ratio"],
                    "ema_bullish": trend["ema_bullish"],
                    "ema_cross":   trend["ema_cross"],
                }

            tracked_markets.append(info)

        # Trier par volume décroissant
        tracked_markets.sort(key=lambda x: x["volume"], reverse=True)

        return {
            "status":          self.status,
            "cycle":           self.cycle_count,
            "cycle_time":      round(self.last_cycle_time, 2),
            "warmup_done":     self.warmup_done,
            "poll_interval":   config.POLL_INTERVAL,
            "risk":            self.risk.get_state(),
            "portfolio":       portfolio_state,
            "signals":         self.active_signals,
            "n_signals":       len(self.active_signals),
            "markets_tracked": len(tracked_markets),
            "markets":         tracked_markets[:40],
            "log":             self.journal.get_recent(80),
            "ai":              self.analyst.get_state(),
        }


# ══════════════════════════════════════════════
# Singleton global
# ══════════════════════════════════════════════
_bot_instance = None

def get_bot():
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = Bot()
    return _bot_instance
