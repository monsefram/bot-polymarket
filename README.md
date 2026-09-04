# bot-polymarket

**FR** — Bot de trading *trend-following* pour les marchés de prédiction **Polymarket**, combinant analyse technique et un analyste **IA** (LLM + recherche web). Fonctionne en **paper trading** (capital virtuel) avec un tableau de bord live.

**EN** — A trend-following trading bot for **Polymarket** prediction markets, combining technical analysis with an **AI analyst** (LLM + web search). Runs in **paper-trading** mode (virtual capital) with a live dashboard.

> ⚠️ **FR** : Projet éducatif. Aucune transaction réelle — aucun argent réel n'est engagé.
> **EN**: Educational project. No real orders are placed — no real money is involved.

---

## Fonctionnalités / Features

- **FR**
  - Détection de tendance : croisement d'EMA (rapide/lente), *Rate of Change*, filtres de bruit et de breakout.
  - Analyste IA multi-fournisseurs (Perplexity, Groq, OpenAI, Anthropic) avec cache, *rate limiting* et pondération IA/technique.
  - Gestion du risque : taille de position, exposition max, *stop* suiveur, *take profit*, coupe-circuits (drawdown, pertes consécutives).
  - Serveur HTTP intégré + tableau de bord temps réel (`dashboard.html`).
- **EN**
  - Trend detection: fast/slow EMA crossover, Rate of Change, noise & breakout filters.
  - Multi-provider AI analyst (Perplexity, Groq, OpenAI, Anthropic) with caching, rate limiting and AI/technical score weighting.
  - Risk management: position sizing, max exposure, trailing stop, take profit, circuit breakers (drawdown, consecutive losses).
  - Built-in HTTP server + real-time dashboard (`dashboard.html`).

## Stack

Python 3 (bibliothèque standard, aucun framework lourd) · API Gamma de Polymarket · APIs LLM.

## Installation & lancement / Setup & run

```bash
# 1. Configurer les clés API (optionnel, pour l'analyste IA)
cp .env.example .env
#   puis renseigner les clés voulues dans .env

# 2. Lancer le serveur + dashboard
python server.py
#   → http://localhost:8765/dashboard
```

**FR** : Toutes les clés sont lues depuis des variables d'environnement (`.env`) — aucune clé n'est stockée dans le code.
**EN**: All keys are read from environment variables (`.env`) — no key is hard-coded.

## Structure

| Fichier / File | Rôle / Role |
|---|---|
| `config.py` | Tous les paramètres (aucun *magic number* dans le code) / All parameters |
| `engine/` | Moteur : signaux, analyste IA, exécution / Engine: signals, AI analyst, execution |
| `server.py` | Serveur HTTP + dashboard live / HTTP server + live dashboard |
| `diag.py`, `test_ai.py` | Diagnostic & tests / Diagnostics & tests |
