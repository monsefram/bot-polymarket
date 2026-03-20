# Polymarket Trend-Following Bot — Context Complet pour Claude

> **Date de dernière mise à jour : 20 mars 2026**
> Ce document contient TOUT le contexte nécessaire pour reprendre le développement de ce projet.

---

## 1. Vue d'ensemble

Bot de **paper trading** automatisé sur **Polymarket** (marché de prédiction crypto).
Stratégie : **trend-following / momentum** sur les micro-mouvements de prix des marchés binaires (YES/NO).

**Stack :** Python 3.14 (stdlib uniquement, zéro dépendance pip), HTTP server natif, frontend vanilla HTML/CSS/JS.

**Architecture :**
```
server.py (HTTP ThreadingHTTPServer :8765)
├── bot.py (orchestrateur principal, thread daemon)
│   ├── engine/data_feed.py   → poll Polymarket API, historique prix
│   ├── engine/market_filter.py → filtre éligibilité marchés
│   ├── engine/trend.py       → EMA logit, ROC, vélocité, accélération
│   ├── engine/signals.py     → scoring 5 composantes, confirmation
│   ├── engine/risk.py        → sizing Kelly, circuit breakers
│   ├── engine/portfolio.py   → positions virtuelles, P&L réaliste
│   └── engine/journal.py     → logging JSONL + mémoire
├── dashboard.html            → dashboard live (poll /bot/state chaque 3s)
├── backtest.html             → backtester sur marchés résolus
└── config.py                 → tous les paramètres centralisés
```

**Endpoints :**
- `http://127.0.0.1:8765/` → Backtester
- `http://127.0.0.1:8765/dashboard` → Dashboard live du bot
- `http://127.0.0.1:8765/bot/state` → API JSON état complet
- `http://127.0.0.1:8765/bot/start|stop|reset` → Contrôle
- `http://127.0.0.1:8765/health` → Healthcheck
- `http://127.0.0.1:8765/scan` → Scanner marchés live
- `http://127.0.0.1:8765/api/markets|events` → Proxy Polymarket (lecture seule)

---

## 2. Cycle de Trading (bot.py → _cycle())

Toutes les **30 secondes** :

1. **Poll API** → data_feed.poll() récupère 150 marchés actifs triés par volume
2. **Warmup check** → besoin de 10 snapshots minimum avant de trader
3. **Update positions** → met à jour les prix courants de chaque position ouverte
4. **Check exits** → 6 conditions de sortie (trailing stop, take profit, time stop, trend reversal, spread blowout, stale data)
5. **Analyse tendances** → pour chaque marché passant le filtre : EMA logit + ROC + vélocité
6. **Génération signaux** → scoring 5 composantes (EMA, momentum, consistance, volume, accélération)
7. **Confirmation** → signal doit persister 1 cycle
8. **Risk check** → circuit breakers, sizing Kelly fractional
9. **Exécution** → ouverture position paper avec slippage + frais réalistes
10. **Journal + equity** → log JSONL, mise à jour courbe d'équité

---

## 3. Configuration Actuelle (config.py)

```python
# DATA FEED
POLL_INTERVAL       = 30        # secondes entre chaque poll
HISTORY_WINDOW      = 360       # snapshots gardés (~3h)
MIN_HISTORY         = 10        # warmup = 10 snapshots = ~5 min

# MARKET FILTERS (très ouvert pour maximiser les trades)
MIN_VOLUME          = 1000      # $1K volume minimum
MIN_LIQUIDITY       = 500       # $500 liquidité minimum
MAX_SPREAD          = 0.08      # 8¢ spread max
MIN_PRICE           = 0.04      # YES > 4¢
MAX_PRICE           = 0.96      # YES < 96¢
MIN_HOURS_TO_RESOLVE = 2        # 2h minimum avant résolution
MAX_MARKETS_TRACKED = 150       # 150 marchés suivis

# TREND DETECTION (sensible aux micro-mouvements Polymarket)
EMA_FAST            = 3         # EMA très rapide
EMA_SLOW            = 8
ROC_PERIOD          = 6
BREAKOUT_THRESHOLD  = 0.005     # 0.5¢ = breakout
NOISE_FILTER        = 0.002     # 0.2¢ = bruit

# ENTRY / EXIT
ENTRY_SCORE_THRESHOLD   = 1.5   # agressif (sur 5)
CONFIRMATION_PERIODS    = 1     # 1 seule confirmation
TRAILING_STOP_DISTANCE  = 0.03  # 3¢
TAKE_PROFIT_DISTANCE    = 0.08  # 8¢
TIME_STOP_HOURS         = 24

# RISK (agressif pour maximiser les trades)
INITIAL_CAPITAL             = 1000.0
RISK_PER_TRADE_PCT          = 5.0
MAX_POSITION_PCT            = 8.0
MAX_CONCURRENT_POSITIONS    = 15
MAX_EXPOSURE_PCT            = 70.0
MAX_DRAWDOWN_PCT            = 15.0
PAUSE_AFTER_CONSECUTIVE_LOSSES = 5

# FEES
FEE_PCT             = 2.0
SLIPPAGE_PCT        = 0.3
MIN_EDGE_PCT        = 0.5

POLYMARKET_API      = "https://gamma-api.polymarket.com"
SERVER_PORT         = 8765
```

---

## 4. Moteur de Tendance (engine/trend.py)

**Spécificité Polymarket :** les prix sont bornés [0, 1] (probabilités). On utilise la **transformation logit** `ln(p/(1-p))` pour que les EMAs fonctionnent correctement près de 0 et 1.

**Indicateurs calculés :**
- EMA fast/slow sur logit(prix) → bullish si fast > slow, détection de cross
- ROC = prix[-1] - prix[-6] (sur 6 périodes)
- Vélocité = mouvement court terme (3 périodes)
- Accélération = changement de vélocité
- Consistance directionnelle = % de périodes up vs down
- Volume ratio = volume récent / volume ancien
- Magnitude = |ROC|
- Direction = "up" si ROC > 0.2¢, "down" si ROC < -0.2¢, sinon "flat"

---

## 5. Moteur de Signaux (engine/signals.py)

**Scoring 5 composantes (0-1 chacune, max ~5.3):**

| Composante | Score 0 | Score 1 | Notes |
|---|---|---|---|
| EMA alignment | EMA pas alignées | Alignées + bonus cross (+0.3) | Max 1.3 |
| Momentum | mag = 0 | mag ≥ 2¢ | Normalisé à 2¢ |
| Consistance | < 35% même dir | ≥ 65% même dir | |
| Volume | ratio < 0.8 | ratio ≥ 1.5 | |
| Accélération | Pas d'accélération | Forte accélération | Normalisé à 0.5¢ |

**Filtres anti-bruit :**
- Magnitude ≥ BREAKOUT_THRESHOLD (0.5¢)
- Score ≥ 1.5/5
- Spread < 2× magnitude
- Edge net ≥ 0.5% après frais

**Confirmation :** 1 cycle de confirmation seulement.

---

## 6. Gestion des Positions (engine/portfolio.py)

**Ouverture :** slippage appliqué à l'entrée, frais d'entrée 2%.

**6 conditions de sortie :**
1. **Trailing stop** — prix tombe à 3¢ sous le peak
2. **Take profit** — prix monte de 8¢ au-dessus de l'entrée
3. **Time stop** — position ouverte > 24h sans mouvement significatif
4. **Trend reversal** — tendance inverse confirmée (magnitude > breakout threshold)
5. **Spread blowout** — spread > 2× le max normal (liquidité sèche)
6. **Stale data** — pas de données récentes (marché peut-être résolu)

**P&L réaliste :** frais entrée (2% du size) + frais sortie (2% de la valeur) + slippage (0.3%)

**Thread-safety :** toutes les méthodes publiques protégées par `threading.Lock()`. Les méthodes `_unlocked` existent pour éviter les deadlocks dans `get_state()`.

---

## 7. Risk Management (engine/risk.py)

**Circuit breakers :**
- Max drawdown 15% → pause totale
- Perte journalière > 8% → pause
- 5 pertes consécutives → pause prolongée
- Cooldown 60s après chaque perte
- Max 15 positions simultanées
- Max 70% exposition

**Position sizing :**
- Base : 5% du capital × poids du score signal
- Kelly fractional : f* = (p×b - q) / b, capped à 8%
- Vérifie le budget d'exposition restant
- Minimum viable : $5

---

## 8. Bugs Résolus (Historique)

### Session 1 — Bugs du backtester original
- ✅ **Vulnérabilité SSRF** dans le proxy `/api/` → restreint aux endpoints `/markets` et `/events`
- ✅ **Cache illimité** → MAX_CACHE=200 avec éviction LRU
- ✅ **Pas de frais modélisés** → ajouté FEE_PCT, SLIPPAGE_PCT, MIN_EDGE_PCT
- ✅ **Kelly criterion cassé** → formule corrigée f* = (p×b - q) / b
- ✅ **Carte résumé cachée** → display:block après backtest

### Session 2 — Construction du bot trend-following
- ✅ Architecture complète de 11 fichiers Python + dashboard HTML
- ✅ Tous les fichiers compilent et les imports fonctionnent
- ✅ Test synthétique validé (trend engine détecte correctement les tendances)

### Session 3 — Serveur qui ne démarre pas
- ✅ **Crash Unicode banner** → caractères box-drawing ╔═║ crashaient Windows console → remplacés par ASCII
- ✅ **Deadlock portfolio.get_state()** → `get_state()` tenait le lock puis appelait des méthodes qui re-prenaient le même lock → créé des méthodes `_unlocked`
- ✅ **HTTPServer mono-thread bloquant** → remplacé par `ThreadingHTTPServer`
- ✅ **Réponses sans Content-Length** → client attendait indéfiniment → ajouté Content-Length + flush

### Session 4 — Zéro trades après 66 cycles
- ✅ **Filtre trop strict** → seulement 4/99 marchés passaient → assoupli (voir config)
- ✅ **Seuils de tendance trop élevés** → BREAKOUT 3¢→0.5¢, NOISE 1¢→0.2¢
- ✅ **Score d'entrée trop exigeant** → de 3.0 à 1.5/5
- ✅ **Confirmation trop longue** → de 3 à 1 période
- ✅ **Normalisation momentum inadaptée** → 10¢→2¢
- ✅ **Edge minimum trop haut** → de 3% à 0.5%
- **Résultat :** 158 marchés, 16 passent le filtre, 1er trade ouvert au cycle 10

---

## 9. Résultats Observés

Après les corrections du 20 mars 2026 :
- 158 marchés suivis (API Polymarket Gamma)
- ~16 marchés passent le filtre à tout instant
- La majorité des marchés sont "flat" (pas de mouvement minute par minute)
- Premier trade ouvert au cycle 10 post-warmup (score 4.29/5)
- Trade fermé par trailing stop quelques cycles plus tard (P&L: -$2.9)
- Nouveaux signaux continuent d'apparaître
- Le bot trade activement mais le volume dépend de la volatilité du marché

---

## 10. Limitations Connues

1. **Polymarket est lent** — les prix bougent peu minute par minute, la plupart des marchés sont "flat"
2. **Paper trading only** — pas d'intégration avec l'API de trading réelle de Polymarket (CLOB)
3. **API Gamma seule source** — pas de données alternatives (news, social, on-chain)
4. **Pas d'IA / LLM** — les décisions sont purement techniques/quantitatives
5. **API rate limiting** — fetch 150 marchés toutes les 30s peut être throttled
6. **Pas de pagination** — ne voit que les 150 premiers marchés par volume
7. **Pas de persistance** — état perdu au redémarrage (pas de save/load)
8. **Console Windows** — éviter les caractères Unicode dans les print()

---

## 11. Pour Lancer

```bash
cd polymarket-bot
python server.py
# Ouvrir http://127.0.0.1:8765/dashboard dans le navigateur
```

Le bot démarre automatiquement en mode paper trading. Warmup ~5 min (10 cycles de 30s).

---

## 12. Structure des Fichiers

| Fichier | Lignes | Rôle |
|---|---|---|
| config.py | ~80 | Tous les paramètres centralisés |
| bot.py | ~400 | Orchestrateur principal, boucle de trading |
| server.py | ~480 | Serveur HTTP, endpoints API, proxy Polymarket |
| engine/data_feed.py | ~150 | Polling API, historique prix par marché |
| engine/market_filter.py | ~60 | Filtrage marchés éligibles |
| engine/trend.py | ~150 | Analyse tendance (EMA logit, ROC, etc.) |
| engine/signals.py | ~180 | Scoring 5 composantes, confirmation |
| engine/risk.py | ~155 | Circuit breakers, sizing Kelly |
| engine/portfolio.py | ~320 | Positions, P&L réaliste, métriques |
| engine/journal.py | ~60 | Logging JSONL + mémoire |
| dashboard.html | ~550 | Dashboard live (polled every 3s) |
| backtest.html | ~3000 | Backtester interactif sur marchés résolus |
| diag.py | ~80 | Script diagnostic CLI |

---

## 13. API Polymarket Utilisée

**Base URL :** `https://gamma-api.polymarket.com`

**Endpoints utilisés :**
- `GET /markets?closed=false&active=true&limit=150&order=volume&ascending=false`
  - Retourne array d'objets marché
  - Champs clés : `id`, `conditionId`, `question`, `category`, `slug`, `outcomePrices` (JSON string `["0.75","0.25"]`), `volume`, `liquidity`, `endDate`
- `GET /markets?closed=true&limit=N&order=volume&ascending=false` (pour le backtester)

---

## 14. Idées d'Amélioration Futures

1. **Ajouter de l'IA (LLM + web search)** pour analyser le contexte des marchés avant de trader
2. **Pagination API** pour suivre plus de marchés
3. **Persistance** (save/load état au redémarrage)
4. **Multi-timeframe** — analyser tendances sur plusieurs échelles
5. **Intégration trading réel** via Polymarket CLOB API
6. **Alertes** (Telegram, Discord) quand un trade s'ouvre/ferme
7. **Backtesting intégré** — tester les paramètres de config sur données historiques
8. **Diversification stratégie** — mean reversion en plus du trend-following
