"""Quick test of AI analyst module."""
from engine.analyst import AIVerdict, _parse_ai_response

# Test 1: Parse valid JSON
raw = '{"probability": 0.72, "confidence": 0.8, "reasoning": "Strong polls", "sources": ["AP"], "key_factors": ["polls"]}'
result = _parse_ai_response(raw)
assert result is not None
assert abs(result["probability"] - 0.72) < 0.001
assert result["confidence"] == 0.8
print("Test 1 OK: basic JSON parse")

# Test 2: Parse markdown-wrapped JSON
raw2 = '```json\n{"probability": 0.45, "confidence": 0.5, "reasoning": "Fair"}\n```'
result2 = _parse_ai_response(raw2)
assert result2 is not None
assert abs(result2["probability"] - 0.45) < 0.001
print("Test 2 OK: markdown wrap parse")

# Test 3: AIVerdict creation + edge calculation
v = AIVerdict("market123", "Will BTC hit 100k?", 0.72, 0.60, 0.8, "Momentum", ["Reuters"], "perplexity", 1.5)
assert abs(v.edge - 0.12) < 0.001  # 72% - 60% = +12%
assert v.direction == "YES"
assert v.abs_edge == abs(v.edge)
print("Test 3 OK: verdict YES edge +12%")

# Test 4: NO direction
v2 = AIVerdict("m2", "Test?", 0.30, 0.55, 0.7, "Unlikely", [], "openai", 2.0)
assert v2.edge < 0  # 30% - 55% = -25%
assert v2.direction == "NO"
print("Test 4 OK: verdict NO edge -25%")

# Test 5: Boundary clamping
raw3 = '{"probability": 1.5, "confidence": 2.0, "reasoning": "test"}'
result3 = _parse_ai_response(raw3)
assert result3["probability"] == 0.99  # clamped
assert result3["confidence"] == 1.0     # clamped
print("Test 5 OK: boundary clamping")

# Test 6: Bad JSON
bad = "This is not JSON at all"
assert _parse_ai_response(bad) is None
print("Test 6 OK: bad JSON returns None")

# Test 7: VerdictCache
from engine.analyst import VerdictCache
cache = VerdictCache(max_size=3, ttl=60)
cache.put("a", v)
cache.put("b", v2)
assert cache.get("a") is v
assert cache.get("nonexistent") is None
assert cache.size() == 2
print("Test 7 OK: cache works")

print("\nAll tests passed!")
