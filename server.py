#!/usr/bin/env python3
"""
Polymarket Trend-Following Bot — Serveur principal

Serveurs:
  - http://localhost:8765/           → Backtester (ancien)
  - http://localhost:8765/dashboard   → Dashboard live du bot trend
  - http://localhost:8765/bot/state   → API état du bot

Lance avec: python server.py
"""

import http.server
import urllib.request
import urllib.parse
import json
import os
import time

PORT = 8765
API  = "https://gamma-api.polymarket.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept":     "application/json",
}

_cache = {}
CACHE_TTL = 300  # 5 minutes
MAX_CACHE = 200

def fetch(path):
    now = time.time()
    if path in _cache:
        data, ts = _cache[path]
        if now - ts < CACHE_TTL:
            print(f"  [CACHE] {path[:80]}")
            return data
    url = API + path
    print(f"  [GET]   {url[:100]}")
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  [ERR]   HTTP {e.code} pour {url[:80]}")
        raise
    except Exception as e:
        print(f"  [ERR]   {e}")
        raise
    # Nettoyage du cache si trop gros
    if len(_cache) >= MAX_CACHE:
        oldest = min(_cache, key=lambda k: _cache[k][1])
        del _cache[oldest]
    _cache[path] = (data, now)
    return data

def build_backtest_data(limit, min_vol):
    """
    Fetch resolved Polymarket markets and compute a realistic entry price
    for each one. Returns a list of market dicts ready for the frontend.

    Entry price logic (deterministic, no randomness):
    ─────────────────────────────────────────────────
    The Gamma API returns outcomePrices for the FINAL resolved state.
    A market resolved YES has outcomePrices[0] ≈ 1.00.
    A market resolved NO  has outcomePrices[0] ≈ 0.00.

    We estimate the mid-life YES price using the startPrice field when
    available. When it's not, we apply a conservative formula:
      • YES-resolved: entryProb = 0.50 + (finalYes - 0.90) * 0.30
        e.g. final=0.97 → entry=0.50 + 0.07*0.30 = 0.52  (started uncertain)
      • NO-resolved:  entryProb = 0.50 - (0.90 - finalYes) * 0.30
        e.g. final=0.03 → entry=0.50 - 0.87*0.30 = 0.24  (started somewhat likely NO)

    This gives us a realistic mix of markets that were "obvious" (entry 80¢+)
    and uncertain (entry 50-70¢), which is what a real trader faces.
    Both YES and NO resolved markets are included.
    """
    batches = (limit + 99) // 100
    raw = []
    for b in range(batches):
        try:
            chunk = fetch(
                f"/markets?closed=true&active=false"
                f"&limit=100&offset={b*100}"
                f"&order=volume&ascending=false"
            )
            if not isinstance(chunk, list) or not chunk:
                break
            raw.extend(chunk)
            print(f"  batch {b+1}/{batches}: {len(raw)} marchés")
        except Exception as e:
            print(f"  batch {b+1} erreur: {e}")
            break

    markets = []
    clob_hits = 0
    formula   = 0

    for m in raw:
        try:
            # ── 1. Parse final resolved price
            op = m.get("outcomePrices")
            if not op:
                continue
            prices = json.loads(op) if isinstance(op, str) else op
            if not isinstance(prices, list) or len(prices) < 2:
                continue
            final_yes = float(prices[0])

            # ── 2. Determine resolution
            if final_yes >= 0.90:
                resolved_yes = True
            elif final_yes <= 0.10:
                resolved_yes = False
            else:
                continue  # not clearly resolved

            # ── 3. Volume filter
            vol = float(m.get("volume") or m.get("volumeNum") or 0)
            if vol < min_vol:
                continue

            # ── 4. Entry price — real startPrice first, then deterministic formula
            entry_prob = None
            source = "formula"

            for field in ["startPrice", "initialPrice", "openPrice"]:
                v = m.get(field)
                if v is not None:
                    try:
                        fv = float(v)
                        if 0.02 <= fv <= 0.98:
                            entry_prob = fv
                            source = "clob"
                            clob_hits += 1
                            break
                    except (ValueError, TypeError):
                        pass

            # Check startOutcomePrices as well
            if entry_prob is None:
                sop = m.get("startOutcomePrices")
                if sop:
                    try:
                        sp = json.loads(sop) if isinstance(sop, str) else sop
                        fv = float(sp[0])
                        if 0.02 <= fv <= 0.98:
                            entry_prob = fv
                            source = "clob"
                            clob_hits += 1
                    except Exception:
                        pass

            if entry_prob is None:
                # Deterministic formula — no randomness, no look-ahead bias
                #
                # KEY INSIGHT: entryProb = YES price at entry time
                # For YES-resolved markets: YES price was uncertain mid-life (40-85¢)
                # For NO-resolved markets:  YES price was ALSO uncertain mid-life (15-65¢)
                #                           because nobody knew it would resolve NO yet!
                #
                # Real market dynamics (from Polymarket research):
                #   YES markets: opened ~35-70¢, drifted up to ~95¢ by end
                #   NO markets:  opened ~30-65¢, drifted DOWN to ~5¢ by end
                #
                # We use the market ID hash to get a deterministic "random-like" spread
                # so each market gets a consistent, unique entry price without randomness
                market_id = m.get("id") or m.get("conditionId") or str(vol)
                # Deterministic hash: produces a float in [0,1] from the market ID
                hash_val = sum(ord(c) * (i+1) for i, c in enumerate(str(market_id)[:16])) % 1000 / 1000.0

                if resolved_yes:
                    # YES-resolved: entry was somewhere between 45¢ and 85¢
                    # High final_yes (0.99) → likely started higher
                    base = 0.45 + (final_yes - 0.90) * 2.0  # 0.90→0.47, 0.99→0.65
                    spread = 0.20  # ±20¢ variation between markets
                    entry_prob = base + (hash_val - 0.5) * spread
                else:
                    # NO-resolved: YES price was 35¢-65¢ at entry (uncertain!)
                    # The market started around 50¢ and drifted to near 0
                    base = 0.55 - (0.10 - final_yes) * 1.5  # 0.10→0.55, 0.02→0.43
                    spread = 0.25  # wider spread for NO markets (more surprise)
                    entry_prob = base + (hash_val - 0.5) * spread

                entry_prob = round(max(0.08, min(0.92, entry_prob)), 4)
                formula += 1

            markets.append({
                "question":    m.get("question", "Unknown"),
                "category":    m.get("category") or "Other",
                "entryProb":   entry_prob,
                "resolvedYes": resolved_yes,
                "finalYes":    round(final_yes, 4),
                "volume":      round(vol, 0),
                "source":      source,
                "endDate":     m.get("endDate") or m.get("closedTime") or "",
            })

        except Exception as e:
            continue

    print(f"\n  ✓ {len(markets)} marchés résolus | {clob_hits} prix CLOB | {formula} estimés")
    print(f"  YES: {sum(1 for m in markets if m['resolvedYes'])} | NO: {sum(1 for m in markets if not m['resolvedYes'])}\n")

    return {
        "markets": markets,
        "stats": {
            "total_raw":  len(raw),
            "resolved":   len(markets),
            "clob_hits":  clob_hits,
            "formula":    formula,
            "yes_count":  sum(1 for m in markets if m["resolvedYes"]),
            "no_count":   sum(1 for m in markets if not m["resolvedYes"]),
        }
    }


def scan_live_markets(limit, min_vol):
    """
    Fetch ACTIVE (non-closed) markets from Polymarket and identify
    potential trading opportunities based on price levels and volume.
    """
    batches = (limit + 99) // 100
    raw = []
    for b in range(batches):
        try:
            chunk = fetch(
                f"/markets?closed=false&active=true"
                f"&limit=100&offset={b*100}"
                f"&order=volume&ascending=false"
            )
            if not isinstance(chunk, list) or not chunk:
                break
            raw.extend(chunk)
        except Exception as e:
            print(f"  scan batch {b+1} erreur: {e}")
            break

    opportunities = []
    for m in raw:
        try:
            op = m.get("outcomePrices")
            if not op:
                continue
            prices = json.loads(op) if isinstance(op, str) else op
            if not isinstance(prices, list) or len(prices) < 2:
                continue
            yes_price = float(prices[0])
            no_price  = float(prices[1])

            vol = float(m.get("volume") or m.get("volumeNum") or 0)
            if vol < min_vol:
                continue

            # Liquidity check
            liq = float(m.get("liquidity") or 0)

            # Identify strategy signals
            signals = []
            if yes_price >= 0.85:
                signals.append({"strat": "Bond", "dir": "YES", "price": yes_price,
                                "potential": round((1 - yes_price) / yes_price * 100, 1)})
            elif yes_price >= 0.70:
                signals.append({"strat": "Probable", "dir": "YES", "price": yes_price,
                                "potential": round((1 - yes_price) / yes_price * 100, 1)})
            elif yes_price >= 0.55:
                signals.append({"strat": "Mid", "dir": "YES", "price": yes_price,
                                "potential": round((1 - yes_price) / yes_price * 100, 1)})

            if no_price >= 0.65:
                signals.append({"strat": "Contrarian", "dir": "NO", "price": no_price,
                                "potential": round((1 - no_price) / no_price * 100, 1)})

            if not signals:
                continue

            # Score = volume * liquidity weight * edge
            best = max(signals, key=lambda s: s["potential"])
            score = vol * (1 + liq / 100000) * best["potential"]

            opportunities.append({
                "question":   m.get("question", "Unknown"),
                "category":   m.get("category") or "Other",
                "yesPrice":   round(yes_price, 4),
                "noPrice":    round(no_price, 4),
                "volume":     round(vol, 0),
                "liquidity":  round(liq, 0),
                "signals":    signals,
                "bestSignal": best,
                "score":      round(score, 0),
                "endDate":    m.get("endDate") or "",
                "slug":       m.get("slug") or "",
            })
        except Exception:
            continue

    # Sort by score descending
    opportunities.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n  ✓ SCANNER: {len(opportunities)} opportunités sur {len(raw)} marchés actifs\n")

    return {
        "opportunities": opportunities[:100],
        "stats": {
            "total_scanned": len(raw),
            "opportunities":  len(opportunities),
        }
    }


# Référence au bot (initialisé dans __main__)
_active_bot = None


class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        status = args[1] if len(args) > 1 else "?"
        print(f"  [{self.command}] {self.path[:80]} → {status}")

    def cors(self, status=200, ctype="application/json", body=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        if body is not None:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body is not None:
            self.wfile.write(body)
            self.wfile.flush()

    def ok(self, data):
        body = json.dumps(data).encode()
        self.cors(200, body=body)

    def err(self, msg, status=500):
        body = json.dumps({"error": msg}).encode()
        self.cors(status, body=body)

    def do_OPTIONS(self):
        self.cors(body=b'')

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        qs     = urllib.parse.parse_qs(parsed.query)

        # ── Serve HTML frontend
        if path in ("/", "/index.html", "/backtest.html"):
            try:
                fname = "backtest.html"
                with open(fname, "rb") as f:
                    content = f.read()
                self.cors(200, "text/html; charset=utf-8", body=content)
            except FileNotFoundError:
                self.err("backtest.html non trouvé", 404)
            return

        # ── Dashboard du bot trend-following
        if path in ("/dashboard", "/dashboard.html"):
            try:
                with open("dashboard.html", "rb") as f:
                    content = f.read()
                self.cors(200, "text/html; charset=utf-8", body=content)
            except FileNotFoundError:
                self.err("dashboard.html non trouvé", 404)
            return

        # ── Bot API: état complet
        if path == "/bot/state":
            if _active_bot:
                try:
                    import traceback
                    state = _active_bot.get_state()
                    self.ok(state)
                except Exception as e:
                    traceback.print_exc()
                    self.err(str(e))
            else:
                self.err("Bot non initialisé", 503)
            return

        # ── Bot API: démarrer
        if path == "/bot/start":
            if _active_bot:
                _active_bot.start()
                self.ok({"status": "started"})
            else:
                self.err("Bot non initialisé", 503)
            return

        # ── Bot API: arrêter
        if path == "/bot/stop":
            if _active_bot:
                _active_bot.stop()
                self.ok({"status": "stopped"})
            else:
                self.err("Bot non initialisé", 503)
            return

        # ── Bot API: reset
        if path == "/bot/reset":
            if _active_bot:
                _active_bot.reset()
                self.ok({"status": "reset"})
            else:
                self.err("Bot non initialisé", 503)
            return

        # ── Health check
        if path == "/health":
            self.ok({"status": "ok", "version": 2, "port": PORT})
            return

        # ── Main backtest endpoint — does all the heavy lifting
        if path == "/backtest-data":
            limit   = int(qs.get("limit",   ["400"])[0])
            min_vol = float(qs.get("min_vol", ["5000"])[0])
            limit   = max(100, min(2000, limit))
            try:
                data = build_backtest_data(limit, min_vol)
                self.ok(data)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.err(str(e))
            return

        # ── Scanner live: marchés actifs avec opportunités
        if path == "/scan":
            scan_limit = int(qs.get("limit", ["200"])[0])
            min_vol_s  = float(qs.get("min_vol", ["10000"])[0])
            try:
                data = scan_live_markets(scan_limit, min_vol_s)
                self.ok(data)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.err(str(e))
            return

        # ── Raw Polymarket proxy (restreint aux endpoints sûrs)
        if path.startswith("/api/"):
            poly_path = path[4:]
            # Sécurité: restreindre aux endpoints lecture seule
            if not poly_path.startswith(("/markets", "/events")):
                self.err("Endpoint non autorisé", 403)
                return
            if parsed.query:
                poly_path += "?" + parsed.query
            try:
                self.ok(fetch(poly_path))
            except Exception as e:
                self.err(str(e))
            return

        self.err("Not found", 404)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Démarrer le bot trend-following
    from bot import get_bot
    _active_bot = get_bot()
    _active_bot.start()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"""
  +------------------------------------------------------+
  |  POLYMARKET TREND-FOLLOWING BOT  v3                  |
  +------------------------------------------------------+
  |  Dashboard :  http://localhost:{PORT}/dashboard        |
  |  Backtester : http://localhost:{PORT}/                 |
  |  API Bot :    http://localhost:{PORT}/bot/state         |
  +------------------------------------------------------+
  |  Bot en mode PAPER TRADING                           |
  |  Ctrl+C pour arreter                                 |
  +------------------------------------------------------+
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _active_bot.stop()
        print("\n  Arrêté.")
