"""
Polymarket Trend-Following Bot — Configuration centralisée
===========================================================
Tous les paramètres sont ici. Aucun magic number dans le code.
"""

# ═══════════════════════════════════════════════════════════
# DATA FEED
# ═══════════════════════════════════════════════════════════
POLL_INTERVAL       = 30        # secondes entre chaque poll API (plus rapide)
HISTORY_WINDOW      = 360       # snapshots gardés par marché (~3h à 30s)
MIN_HISTORY         = 10        # snapshots min avant de générer des signaux

# ═══════════════════════════════════════════════════════════
# MARKET FILTERS
# ═══════════════════════════════════════════════════════════
MIN_VOLUME          = 1000      # volume 24h minimum (USD) — très ouvert
MIN_LIQUIDITY       = 500       # liquidité carnet d'ordres minimum
MAX_SPREAD          = 0.08      # spread max (8¢)
MIN_PRICE           = 0.04      # ignorer si YES < 4¢
MAX_PRICE           = 0.96      # ignorer si YES > 96¢
MIN_HOURS_TO_RESOLVE = 2        # heures minimum avant résolution
MAX_MARKETS_TRACKED = 150       # marchés max suivis simultanément

# ═══════════════════════════════════════════════════════════
# TREND DETECTION
# ═══════════════════════════════════════════════════════════
EMA_FAST            = 3         # EMA rapide (périodes)
EMA_SLOW            = 8         # EMA lente (périodes)
ROC_PERIOD          = 6         # lookback du Rate of Change
MIN_TREND_STRENGTH  = 0.50      # % min de périodes dans la même direction
BREAKOUT_THRESHOLD  = 0.005     # mouvement min pour breakout (0.5¢)
NOISE_FILTER        = 0.002     # ignorer les mouvements < 0.2¢

# ═══════════════════════════════════════════════════════════
# ENTRY / EXIT
# ═══════════════════════════════════════════════════════════
ENTRY_SCORE_THRESHOLD   = 1.5   # score min pour entrer (sur 5) — agressif
CONFIRMATION_PERIODS    = 1     # 1 seule confirmation = rapide
MAX_ENTRY_DELAY         = 12    # périodes max après signal pour entrer
TRAILING_STOP_DISTANCE  = 0.03  # trailing stop à 3¢ du peak
TAKE_PROFIT_DISTANCE    = 0.08  # take profit à +8¢ (réaliste Polymarket)
TIME_STOP_HOURS         = 24    # fermer si aucun mouvement après 24h
EXIT_SCORE_THRESHOLD    = -1.0  # seuil de sortie sur score

# ═══════════════════════════════════════════════════════════
# RISK MANAGEMENT
# ═══════════════════════════════════════════════════════════
INITIAL_CAPITAL             = 1000.0    # capital initial paper (USDC)
RISK_PER_TRADE_PCT          = 5.0       # max 5% du capital par trade
MAX_POSITION_PCT            = 8.0       # max 8% sur un seul marché
MAX_CONCURRENT_POSITIONS    = 15        # max 15 positions simultanées
MAX_EXPOSURE_PCT            = 70.0      # max 70% du capital exposé
MAX_DAILY_LOSS_PCT          = 8.0       # pause si perte jour > 8%
MAX_DRAWDOWN_PCT            = 15.0      # pause si drawdown > 15%
COOLDOWN_AFTER_LOSS_SEC     = 60        # attendre 1 min après une perte
PAUSE_AFTER_CONSECUTIVE_LOSSES = 5      # pause après 5 pertes consécutives

# ═══════════════════════════════════════════════════════════
# FEES & EXECUTION
# ═══════════════════════════════════════════════════════════
FEE_PCT             = 2.0       # frais par trade (%)
SLIPPAGE_PCT        = 0.3       # slippage estimé (%)
MIN_EDGE_PCT        = 0.5       # edge minimum pour trader (%) — très agressif

# ═══════════════════════════════════════════════════════════
# API & SERVER
# ═══════════════════════════════════════════════════════════
POLYMARKET_API      = "https://gamma-api.polymarket.com"
SERVER_PORT         = 8765
