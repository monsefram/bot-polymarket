"""
AI Analyst Engine — Intelligence artificielle pour l'analyse de marches Polymarket.

Architecture :
  1. Recoit un marche (question + prix + contexte)
  2. Cherche des infos en temps reel (Perplexity / web search)
  3. LLM estime une probabilite independante
  4. Compare AI estimate vs prix marche → edge
  5. Retourne un AIVerdict avec confiance + raisonnement

Providers supportes :
  - Perplexity (pplx-api) : LLM + web search integre (RECOMMANDE)
  - OpenAI (gpt-4o) : puissant mais pas de web search natif
  - Anthropic (claude) : alternative

Zero dependance pip — utilise urllib + json de la stdlib.
"""

import json
import time
import threading
import urllib.request
import urllib.error
from collections import OrderedDict

import config


# ══════════════════════════════════════════════════════════════
# AI Verdict — resultat de l'analyse IA
# ══════════════════════════════════════════════════════════════

class AIVerdict:
    """Resultat de l'analyse IA pour un marche."""

    def __init__(self, market_id, question, ai_probability, market_price,
                 confidence, reasoning, sources, provider, latency):
        self.market_id      = market_id
        self.question       = question
        self.ai_probability = ai_probability    # 0.0 - 1.0 (proba estimee par l'IA)
        self.market_price   = market_price      # prix YES actuel du marche
        self.confidence     = confidence        # 0.0 - 1.0
        self.reasoning      = reasoning         # explication courte
        self.sources        = sources           # liste de sources citees
        self.provider       = provider          # "perplexity", "openai", "anthropic"
        self.latency        = latency           # temps de reponse en secondes
        self.timestamp      = time.time()

        # Edge = difference entre AI estimate et prix marche
        self.edge = self.ai_probability - self.market_price
        self.abs_edge = abs(self.edge)

        # Direction suggeree
        if self.edge > 0:
            self.direction = "YES"     # AI pense que YES est sous-evalue
        elif self.edge < 0:
            self.direction = "NO"      # AI pense que NO est sous-evalue
        else:
            self.direction = "NEUTRAL"

    def to_dict(self):
        return {
            "market_id":      self.market_id,
            "question":       self.question[:120],
            "ai_probability": round(self.ai_probability, 4),
            "market_price":   round(self.market_price, 4),
            "edge":           round(self.edge, 4),
            "abs_edge":       round(self.abs_edge, 4),
            "direction":      self.direction,
            "confidence":     round(self.confidence, 3),
            "reasoning":      self.reasoning[:300],
            "sources":        self.sources[:5],
            "provider":       self.provider,
            "latency":        round(self.latency, 2),
            "age_sec":        round(time.time() - self.timestamp),
        }


# ══════════════════════════════════════════════════════════════
# LRU Cache thread-safe pour les verdicts AI
# ══════════════════════════════════════════════════════════════

class VerdictCache:
    """Cache LRU thread-safe pour eviter de re-analyser les memes marches."""

    def __init__(self, max_size=100, ttl=600):
        self._cache = OrderedDict()
        self._lock = threading.Lock()
        self.max_size = max_size
        self.ttl = ttl          # duree de vie en secondes

    def get(self, market_id):
        with self._lock:
            if market_id in self._cache:
                verdict, ts = self._cache[market_id]
                if time.time() - ts < self.ttl:
                    self._cache.move_to_end(market_id)
                    return verdict
                else:
                    del self._cache[market_id]
            return None

    def put(self, market_id, verdict):
        with self._lock:
            if market_id in self._cache:
                del self._cache[market_id]
            self._cache[market_id] = (verdict, time.time())
            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def get_all(self):
        with self._lock:
            now = time.time()
            return {
                mid: v.to_dict()
                for mid, (v, ts) in self._cache.items()
                if now - ts < self.ttl
            }

    def size(self):
        with self._lock:
            return len(self._cache)


# ══════════════════════════════════════════════════════════════
# Prompts — le coeur de l'intelligence
# ══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are an expert prediction market analyst. Your job is to estimate the TRUE probability of events on Polymarket.

CRITICAL RULES:
1. You must return a probability between 0.01 and 0.99 (never 0 or 1)
2. Search for the LATEST news, data, and expert opinions
3. Consider: base rates, recent developments, expert consensus, historical patterns
4. Be contrarian when evidence supports it — markets can be wrong
5. Focus on INFORMATION THE MARKET MIGHT NOT HAVE YET (breaking news, obscure data)

RESPONSE FORMAT (strict JSON only):
{
  "probability": 0.XX,
  "confidence": 0.XX,
  "reasoning": "Brief explanation (2-3 sentences max)",
  "sources": ["source1", "source2"],
  "key_factors": ["factor1", "factor2", "factor3"]
}

probability = your estimate that YES is correct (0.01 to 0.99)
confidence = how confident you are in your estimate (0.0 to 1.0)
  - 0.3 = low (not much data available)
  - 0.5 = medium (some evidence)
  - 0.7 = high (strong evidence)
  - 0.9 = very high (overwhelming evidence)"""


def _build_analysis_prompt(question, market_price, category, volume, end_date):
    """Construit le prompt d'analyse pour un marche specifique."""
    return f"""Analyze this Polymarket prediction market and estimate the TRUE probability:

MARKET: {question}
CURRENT PRICE: YES = {market_price:.1%} (this is what the market thinks)
CATEGORY: {category}
VOLUME: ${volume:,.0f}
END DATE: {end_date or 'Unknown'}

Search for the latest news, statistics, expert opinions, and any relevant data.
Focus on information that might not be reflected in the current market price.
Is the market overpricing or underpricing this event?

Return ONLY valid JSON matching the specified format."""


# ══════════════════════════════════════════════════════════════
# API Calls — zero dependance, stdlib uniquement
# ══════════════════════════════════════════════════════════════

def _call_perplexity(prompt, api_key):
    """Appel Perplexity API (LLM + web search integre)."""
    url = "https://api.perplexity.ai/chat/completions"
    payload = {
        "model": config.AI_PERPLEXITY_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
        "return_related_questions": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    content = result["choices"][0]["message"]["content"]
    citations = result.get("citations", [])
    return content, citations


def _call_openai(prompt, api_key):
    """Appel OpenAI API (GPT-4o)."""
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": config.AI_OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    content = result["choices"][0]["message"]["content"]
    return content, []


def _call_anthropic(prompt, api_key):
    """Appel Anthropic API (Claude)."""
    url = "https://api.anthropic.com/v1/messages"
    payload = {
        "model": config.AI_ANTHROPIC_MODEL,
        "max_tokens": 500,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    content = result["content"][0]["text"]
    return content, []


def _web_search_duckduckgo(query, max_results=5):
    """Recherche web gratuite via DuckDuckGo HTML (zero API key)."""
    try:
        safe_q = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={safe_q}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Parser minimal : extraire les snippets des resultats
        results = []
        # Chercher les blocs de resultats (class="result__snippet")
        parts = html.split('class="result__snippet"')
        for part in parts[1:max_results+1]:
            # Extraire le texte du snippet
            start = part.find('>') + 1
            end = part.find('</a>', start)
            if end == -1:
                end = part.find('</td>', start)
            if end == -1:
                end = start + 300
            snippet = part[start:end]
            # Nettoyer le HTML basique
            import re
            snippet = re.sub(r'<[^>]+>', ' ', snippet).strip()
            snippet = re.sub(r'\s+', ' ', snippet)
            if snippet and len(snippet) > 20:
                results.append(snippet[:200])

        return results
    except Exception as e:
        print(f"  [AI] DuckDuckGo search error: {e}")
        return []


def _call_groq(prompt, api_key, web_context=""):
    """Appel Groq API (GRATUIT — Llama 3 70B ultra-rapide)."""
    url = "https://api.groq.com/openai/v1/chat/completions"

    # Enrichir le prompt avec le contexte web
    enriched_prompt = prompt
    if web_context:
        enriched_prompt = f"""Here is RECENT WEB SEARCH context about this market:
---
{web_context}
---

Now analyze this market using both the web context above and your training knowledge:

{prompt}"""

    payload = {
        "model": config.AI_GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": enriched_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    content = result["choices"][0]["message"]["content"]
    return content, []


def _parse_ai_response(raw_text, citations=None):
    """Parse la reponse JSON du LLM. Tolerant aux erreurs."""
    # Nettoyer le texte (parfois le LLM encadre avec ```json ... ```)
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # Extraire le premier bloc JSON
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end <= start:
        return None

    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError:
        return None

    prob = data.get("probability")
    if prob is None:
        return None

    prob = max(0.01, min(0.99, float(prob)))
    confidence = max(0.0, min(1.0, float(data.get("confidence", 0.3))))
    reasoning = str(data.get("reasoning", "No reasoning provided"))
    sources = data.get("sources", [])
    if citations:
        sources = list(citations) + sources

    key_factors = data.get("key_factors", [])
    if key_factors:
        reasoning += " | Factors: " + ", ".join(str(f) for f in key_factors[:3])

    return {
        "probability": prob,
        "confidence": confidence,
        "reasoning": reasoning,
        "sources": [str(s) for s in sources[:5]],
    }


# ══════════════════════════════════════════════════════════════
# AI Analyst — classe principale
# ══════════════════════════════════════════════════════════════

class AIAnalyst:
    """
    Module d'intelligence artificielle pour analyser les marches Polymarket.

    Workflow:
      1. Le bot detecte un signal technique
      2. AIAnalyst analyse le marche (LLM + web search)
      3. Retourne un AIVerdict avec probabilite estimee + edge
      4. Le bot combine score technique + score AI pour decider

    Rate limiting integre pour eviter les couts excessifs.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.cache = VerdictCache(
            max_size=config.AI_CACHE_SIZE,
            ttl=config.AI_CACHE_TTL,
        )
        self.enabled = False
        self.provider = None        # "perplexity", "openai", "anthropic"
        self.api_key = None

        # Stats
        self.total_calls = 0
        self.total_errors = 0
        self.total_latency = 0.0

        # Rate limiting
        self._call_timestamps = []
        self._last_call_time = 0

        # Charger la config
        self._load_config()

    def _load_config(self):
        """Charge les cles API et determine le provider."""
        # Essayer de charger depuis .env
        env_path = ".env"
        env_vars = {}
        try:
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        env_vars[key.strip()] = val.strip().strip('"').strip("'")
        except FileNotFoundError:
            pass

        # Detecter le provider et la cle (ordre de priorite)
        providers = [
            ("perplexity", "PERPLEXITY_API_KEY"),
            ("groq",       "GROQ_API_KEY"),
            ("openai",     "OPENAI_API_KEY"),
            ("anthropic",  "ANTHROPIC_API_KEY"),
        ]

        for provider_name, env_var in providers:
            key = env_vars.get(env_var, "")
            if key and len(key) > 10:
                self.provider = provider_name
                self.api_key = key
                self.enabled = True
                free_tag = " (GRATUIT!)" if provider_name == "groq" else ""
                print(f"  [AI] Provider: {provider_name}{free_tag} (cle chargee depuis .env)")
                return

        print("  [AI] Aucune cle API trouvee dans .env — mode technique seul")
        self.enabled = False

    def _rate_limit_ok(self):
        """Verifie le rate limiting (max N appels par minute)."""
        now = time.time()
        # Nettoyer les timestamps > 60s
        self._call_timestamps = [t for t in self._call_timestamps if now - t < 60]

        if len(self._call_timestamps) >= config.AI_MAX_CALLS_PER_MIN:
            return False

        # Min delay entre appels
        if now - self._last_call_time < config.AI_MIN_DELAY_SEC:
            return False

        return True

    def analyze(self, market_id, question, market_price, category="", volume=0, end_date=""):
        """
        Analyse un marche avec l'IA.
        Retourne un AIVerdict ou None si indisponible/rate-limited.
        """
        if not self.enabled:
            return None

        # Check cache
        cached = self.cache.get(market_id)
        if cached:
            return cached

        # Rate limit
        if not self._rate_limit_ok():
            return None

        # Construire le prompt
        prompt = _build_analysis_prompt(question, market_price, category, volume, end_date)

        # Appel API
        t0 = time.time()
        try:
            if self.provider == "perplexity":
                raw, citations = _call_perplexity(prompt, self.api_key)
            elif self.provider == "groq":
                # Groq = LLM gratuit + DuckDuckGo web search gratuit
                web_results = _web_search_duckduckgo(
                    question + " latest news " + category,
                    max_results=5,
                )
                web_context = "\n".join(f"- {r}" for r in web_results) if web_results else ""
                raw, citations = _call_groq(prompt, self.api_key, web_context)
                if web_results:
                    citations = ["DuckDuckGo web search"] + web_results[:3]
            elif self.provider == "openai":
                raw, citations = _call_openai(prompt, self.api_key)
            elif self.provider == "anthropic":
                raw, citations = _call_anthropic(prompt, self.api_key)
            else:
                return None

            latency = time.time() - t0

            # Parse response
            parsed = _parse_ai_response(raw, citations)
            if not parsed:
                self.total_errors += 1
                print(f"  [AI] Parse error pour: {question[:60]}")
                return None

            # Creer le verdict
            verdict = AIVerdict(
                market_id=market_id,
                question=question,
                ai_probability=parsed["probability"],
                market_price=market_price,
                confidence=parsed["confidence"],
                reasoning=parsed["reasoning"],
                sources=parsed["sources"],
                provider=self.provider,
                latency=latency,
            )

            # Mettre en cache
            self.cache.put(market_id, verdict)

            # Stats
            with self._lock:
                self.total_calls += 1
                self.total_latency += latency
                self._call_timestamps.append(time.time())
                self._last_call_time = time.time()

            edge_pct = verdict.edge * 100
            print(f"  [AI] {verdict.direction} edge {edge_pct:+.1f}% "
                  f"(AI:{verdict.ai_probability:.0%} vs Mkt:{market_price:.0%}) "
                  f"conf:{verdict.confidence:.0%} | {question[:50]}")

            return verdict

        except urllib.error.HTTPError as e:
            self.total_errors += 1
            body = ""
            try:
                body = e.read().decode()[:200]
            except Exception:
                pass
            print(f"  [AI] HTTP {e.code}: {body}")
            return None
        except Exception as e:
            self.total_errors += 1
            print(f"  [AI] Erreur: {e}")
            return None

    def get_state(self):
        """Etat pour le dashboard."""
        avg_latency = (self.total_latency / self.total_calls
                       if self.total_calls > 0 else 0)
        return {
            "enabled":       self.enabled,
            "provider":      self.provider or "none",
            "total_calls":   self.total_calls,
            "total_errors":  self.total_errors,
            "avg_latency":   round(avg_latency, 2),
            "cache_size":    self.cache.size(),
            "verdicts":      self.cache.get_all(),
        }
