import urllib.request, json

r = urllib.request.urlopen('http://127.0.0.1:8765/bot/state', timeout=10)
d = json.loads(r.read())

print(f"Status: {d['status']}")
print(f"Cycle: {d['cycle']}")
print(f"Warmup: {d['warmup_done']}")
print(f"Markets tracked: {d['markets_tracked']}")
print(f"Signals actifs: {d['n_signals']}")
print(f"Positions: {d['portfolio']['n_positions']}")
print(f"Closed trades: {d['portfolio']['n_closed']}")
print(f"Risk paused: {d['risk']['is_paused']} {d['risk']['pause_reason']}")
print()

# Signals
print("=== SIGNALS ACTIFS ===")
for k, v in d['signals'].items():
    print(f"  {k[:20]}: score={v['score']:.1f} dir={v['direction']} conf={v['confirmations']}")
print()

# Filter stats
markets = d['markets']
passing = [m for m in markets if m['passes_filter']]
print(f"Marches passant filtre: {len(passing)}/{len(markets)}")

# Why markets fail filter
fail_reasons = {}
for m in markets:
    if not m['passes_filter']:
        for r in m.get('filter_reasons', []):
            fail_reasons[r] = fail_reasons.get(r, 0) + 1
print("\n=== RAISONS DE REJET (filtre) ===")
for reason, count in sorted(fail_reasons.items(), key=lambda x: -x[1]):
    print(f"  {reason}: {count}")

# Trend analysis for passing markets
print("\n=== MARCHES QUI PASSENT LE FILTRE ===")
for m in passing[:15]:
    t = m.get('trend', {})
    sig = "SIG" if m.get('has_signal') else "---"
    pos = "POS" if m.get('has_position') else "---"
    print(f"  {sig} {pos} | dir={t.get('direction','?'):>5} mag={t.get('magnitude',0):.4f} "
          f"roc={t.get('roc',0):.4f} consist={t.get('consistency',0):.3f} "
          f"vol_r={t.get('vol_ratio',0):.2f} | spread={m['spread']:.4f} "
          f"yes={m['yes_price']:.2f} hist={m['history_len']} "
          f"| {m['question'][:45]}")

# Recent log entries
print("\n=== DERNIER LOG ===")
for entry in d.get('log', [])[-15:]:
    print(f"  [{entry.get('type','')}] {json.dumps({k:v for k,v in entry.items() if k not in ('type','ts')})[:100]}")

# Positions details
print("\n=== POSITIONS OUVERTES ===")
for pos in d['portfolio'].get('positions', []):
    print(f"  {pos['direction']} @ {pos['entry_price']} -> {pos['current_price']} | "
          f"PnL: ${pos['unrealized_pnl']} | size: ${pos['size']} | "
          f"score: {pos['signal_score']} | {pos['question'][:55]}")

print(f"\nExposure: {d['portfolio']['exposure_pct']}% | Capital: ${d['portfolio']['capital']}")

# Closed trades
if d['portfolio'].get('closed_trades'):
    print("\n=== DERNIERS TRADES FERMES ===")
    for t in d['portfolio']['closed_trades'][-10:]:
        print(f"  {t['direction']} | entry:{t['entry_price']} exit:{t['exit_price']} | "
              f"PnL: ${t['net_pnl']} | reason: {t.get('reason','?')} | {t.get('question','')[:40]}")
