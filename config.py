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
# AI ANALYST (LLM + web search)
# ═══════════════════════════════════════════════════════════
AI_ENABLED              = True      # activer l'analyse IA
AI_PERPLEXITY_MODEL     = "sonar"   # Perplexity : sonar (avec web search)
AI_OPENAI_MODEL         = "gpt-4o"  # OpenAI fallback
AI_ANTHROPIC_MODEL      = "claude-sonnet-4-20250514"

AI_MIN_EDGE_PCT         = 5.0       # edge minimum AI pour trader (5%)
AI_MIN_CONFIDENCE       = 0.3       # confiance minimum de l'IA
AI_WEIGHT               = 0.50      # poids du score IA dans la decision (50%)
TECH_WEIGHT             = 0.50      # poids du score technique (50%)

AI_MAX_CALLS_PER_MIN    = 10        # max 10 appels API par minute
AI_MIN_DELAY_SEC        = 3         # min 3s entre chaque appel
AI_CACHE_SIZE           = 100       # verdicts en cache
AI_CACHE_TTL            = 600       # 10 min de cache par verdict

AI_ANALYZE_ON_SIGNAL    = True      # analyser quand signal technique detecte
AI_ANALYZE_TOP_MARKETS  = 5         # analyser les N meilleurs marches par cycle
AI_SCORE_BOOST          = 2.0       # bonus score quand AI confirme le technique

# ═══════════════════════════════════════════════════════════
# API & SERVER
# ═══════════════════════════════════════════════════════════
POLYMARKET_API      = "https://gamma-api.polymarket.com"
SERVER_PORT         = 8765
