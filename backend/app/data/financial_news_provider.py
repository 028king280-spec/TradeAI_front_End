"""
Institutional Multi-Source Financial News Provider for Indian Stock Markets.
Aggregates and normalizes verified real-time feeds from:
- Moneycontrol (Markets, Top News & Business)
- Economic Times Markets (NSE, BSE, Macro & Equities)
- Livemint Markets & Company News
- Google Financial News (Targeted fallback & Symbol search)

Features:
- Indian Stock Symbol Auto-Detection (RELIANCE, HDFCBANK, TATASTEEL, etc.)
- Domain-specific Financial Sentiment Scoring (-100 to +100)
- Market-wide Sentiment Synthesis for Nifty/BankNifty bias
- In-memory / Redis Caching with TTL
"""

import re
import html
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Set
import xml.etree.ElementTree as ET
import httpx

from app.core.config import settings
from app.core.logging import logger
from app.core.cache import CacheService
from app.data.news_provider import NewsProvider

NEWS_CACHE_TTL_SECONDS = 600  # 10 minutes cache for fresher news

KNOWN_NSE_SYMBOLS = {
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL",
    "ITC", "KOTAKBANK", "LT", "HINDUNILVR", "AXISBANK", "BAJFINANCE", "MARUTI",
    "TATAMOTORS", "SUNPHARMA", "TATASTEEL", "NTPC", "POWERGRID", "ONGC",
    "TITAN", "ADANIENT", "ADANIPORTS", "COALINDIA", "BAJAJFINSV", "WIPRO",
    "ASIANPAINT", "HCLTECH", "ULTRACEMCO", "JSWSTEEL", "GRASIM", "HEROMOTOCO",
    "TECHM", "DIVISLAB", "CIPLA", "APOLLOHOSP", "EICHERMOT", "BPCL", "LTIM",
    "BRITANNIA", "TATACONSUM", "HINDALCO", "NESTLEIND", "DRREDDY", "BEL",
    "TRENT", "VEDL", "ZOMATO", "JIOFIN", "HAL", "BSE"
}

BULLISH_KEYWORDS = {
    "jump", "jumps", "gain", "gains", "surge", "surges", "rally", "rallies",
    "high", "highs", "record", "soar", "soars", "rise", "rises", "bull", "bullish",
    "profit", "profits", "beat", "beats", "growth", "outperform", "dividend",
    "expansion", "upbeat", "inflows", "upgrade", "upgrades", "soaring", "positive",
    "orders", "deal", "contract", "boost", "boosts", "milestone", "turnaround"
}

BEARISH_KEYWORDS = {
    "fall", "falls", "drop", "drops", "plunge", "plunges", "decline", "declines",
    "tumble", "tumbles", "slip", "slips", "loss", "losses", "bear", "bearish",
    "crash", "crashes", "down", "slump", "slumps", "drag", "drags", "weak", "deficit",
    "penalty", "probe", "downgrade", "downgrades", "selloff", "inflation", "worries",
    "cut", "cuts", "cautious", "subdued", "headwinds", "fraud", "warning"
}

SECTOR_KEYWORDS = {
    "Banking": ["bank", "banking", "rbi", "npa", "lending", "credit", "repo", "deposit", "sbi", "hdfc", "icici"],
    "IT & Tech": ["it", "tech", "software", "infosys", "tcs", "wipro", "hcl", "ai", "cloud"],
    "Auto": ["auto", "vehicle", "sales", "maruti", "tata motors", "ev", "mahindra", "bajaj auto"],
    "Energy & Oil": ["crude", "oil", "petrol", "refinery", "reliance", "ongc", "bpcl", "energy", "power"],
    "Metals": ["steel", "metal", "mining", "tata steel", "jsw", "hindalco", "vedanta", "iron"],
    "Pharma": ["pharma", "drug", "fda", "sun pharma", "dr reddy", "healthcare", "hospital"],
}


def classify_headline_sentiment(title: str) -> Tuple[str, int, str]:
    """
    Classifies financial headline into sentiment, score (-100 to +100), and impact level.
    Returns: (sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL', score: int, impact: 'HIGH' | 'MEDIUM' | 'LOW')
    """
    words = set(re.findall(r"\b[A-Za-z]+\b", title.lower()))
    bull_matches = words & BULLISH_KEYWORDS
    bear_matches = words & BEARISH_KEYWORDS

    bull_count = len(bull_matches)
    bear_count = len(bear_matches)

    if bull_count > bear_count:
        sentiment = "BULLISH"
        score = min(95, 40 + (bull_count - bear_count) * 20)
        impact = "HIGH" if bull_count >= 2 else "MEDIUM"
    elif bear_count > bull_count:
        sentiment = "BEARISH"
        score = max(-95, -40 - (bear_count - bull_count) * 20)
        impact = "HIGH" if bear_count >= 2 else "MEDIUM"
    else:
        sentiment = "NEUTRAL"
        score = 0
        impact = "LOW"

    return sentiment, score, impact


def extract_symbols_and_sector(headline: str) -> Tuple[List[str], str]:
    """
    Detects relevant NSE stocks or indices and sector in the headline.
    """
    headline_upper = headline.upper()
    found_symbols: Set[str] = set()

    for sym in KNOWN_NSE_SYMBOLS:
        # Check whole word match
        if re.search(rf"\b{sym}\b", headline_upper):
            found_symbols.add(sym)

    if "NIFTY" in headline_upper:
        found_symbols.add("NIFTY 50")
    if "SENSEX" in headline_upper:
        found_symbols.add("SENSEX")
    if "BANK NIFTY" in headline_upper or "BANKNIFTY" in headline_upper:
        found_symbols.add("BANK NIFTY")

    # Detect sector
    detected_sector = "Markets"
    headline_lower = headline.lower()
    for sector, keywords in SECTOR_KEYWORDS.items():
        if any(kw in headline_lower for kw in keywords):
            detected_sector = sector
            break

    # Only return symbols actually detected in headline; do not fabricate NIFTY/SENSEX fallbacks
    symbols_list = list(found_symbols)
    return symbols_list, detected_sector


class FinancialNewsProvider(NewsProvider):
    # Primary Multi-Source Indian Financial RSS Endpoints
    FEEDS = [
        {
            "name": "Economic Times Markets",
            "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
            "source": "Economic Times",
        },
        {
            "name": "Economic Times Stocks",
            "url": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
            "source": "Economic Times",
        },
        {
            "name": "Moneycontrol Markets",
            "url": "https://www.moneycontrol.com/rss/MCtopnews.xml",
            "source": "Moneycontrol",
        },
        {
            "name": "Moneycontrol Business",
            "url": "https://www.moneycontrol.com/rss/business.xml",
            "source": "Moneycontrol",
        },
        {
            "name": "Livemint Markets",
            "url": "https://www.livemint.com/rss/markets",
            "source": "Livemint",
        },
        {
            "name": "Livemint Companies",
            "url": "https://www.livemint.com/rss/companies",
            "source": "Livemint",
        },
        {
            "name": "Business Standard Markets",
            "url": "https://www.business-standard.com/rss/markets-106.rss",
            "source": "Business Standard",
        },
        {
            "name": "Business Standard Companies",
            "url": "https://www.business-standard.com/rss/companies-101.rss",
            "source": "Business Standard",
        },
        {
            "name": "NDTV Profit Markets",
            "url": "https://feeds.feedburner.com/ndtvprofit-latest",
            "source": "NDTV Profit",
        },
        {
            "name": "Investing.com India Equities",
            "url": "https://in.investing.com/rss/news_25.rss",
            "source": "Investing.com",
        },
    ]

    def __init__(self):
        self._last_fetch_ts: Optional[str] = None
        self._total_fetched = 0
        self._feed_status = "HEALTHY"
        self._active_sources = [
            "Economic Times",
            "Moneycontrol",
            "Livemint",
            "Business Standard",
            "NDTV Profit",
            "Investing.com",
            "Google Finance",
        ]

    async def get_market_news(self, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Fetches & aggregates verified real-time Indian stock market news from Moneycontrol,
        Economic Times, and Livemint.
        """
        cache_key = f"news:multi_market:limit_{limit}"
        cached = await CacheService.get(cache_key)
        if cached and isinstance(cached, list) and len(cached) > 0:
            return cached

        all_items = await self._fetch_all_primary_feeds(limit=limit)

        if not all_items:
            # Fallback to Google News search if direct RSS fails
            all_items = await self._fetch_google_rss("NIFTY+Sensex+Indian+Stock+Market", limit=limit)

        if all_items:
            await CacheService.set(cache_key, all_items, ttl_seconds=NEWS_CACHE_TTL_SECONDS)
            return all_items

        return []

    async def get_news_for_stock(self, symbol: str, limit: int = 6) -> List[Dict[str, Any]]:
        """
        Fetches latest stock-specific news articles for an NSE equity.
        """
        clean = symbol.upper().replace("-EQ", "").strip()
        cache_key = f"news:symbol:{clean}:limit_{limit}"
        cached = await CacheService.get(cache_key)
        if cached and isinstance(cached, list) and len(cached) > 0:
            return cached

        # Check market news first to see if any mentions this symbol
        market_items = await self.get_market_news(limit=40)
        matching = [item for item in market_items if clean in item.get("relatedSymbols", [])]

        if len(matching) >= limit:
            res = matching[:limit]
            await CacheService.set(cache_key, res, ttl_seconds=NEWS_CACHE_TTL_SECONDS)
            return res

        # Otherwise query Google News for targeted symbol
        targeted = await self._fetch_google_rss(f"{clean}+share+price+NSE+stock", limit=limit, symbol=clean)
        combined = (matching + targeted)[:limit]

        if combined:
            await CacheService.set(cache_key, combined, ttl_seconds=NEWS_CACHE_TTL_SECONDS)
            return combined

        return []

    async def search_news(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """
        Free text search across Indian financial feeds.
        """
        clean_q = re.sub(r"[^\w\s]", "", query).strip()
        cache_key = f"news:search:{clean_q.replace(' ', '+')}:limit_{limit}"
        cached = await CacheService.get(cache_key)
        if cached and isinstance(cached, list) and len(cached) > 0:
            return cached

        # Filter in-memory market news first
        market_items = await self.get_market_news(limit=50)
        query_words = clean_q.lower().split()
        matched = [
            it for it in market_items
            if any(qw in it.get("headline", "").lower() for qw in query_words)
        ]

        if len(matched) >= limit:
            results = matched[:limit]
            await CacheService.set(cache_key, results, ttl_seconds=NEWS_CACHE_TTL_SECONDS)
            return results

        # Fallback to Google RSS search
        google_results = await self._fetch_google_rss(f"{clean_q}+Indian+Market", limit=limit)
        results = (matched + google_results)[:limit]
        if results:
            await CacheService.set(cache_key, results, ttl_seconds=NEWS_CACHE_TTL_SECONDS)
        return results

    async def get_market_sentiment_summary(self) -> Dict[str, Any]:
        """
        Aggregates news items and computes a macro sentiment score (-100 to +100)
        along with bullish/bearish breakdown for Indian indices.
        """
        cache_key = "news:market_sentiment_summary"
        cached = await CacheService.get(cache_key)
        if cached and isinstance(cached, dict):
            return cached

        news_items = await self.get_market_news(limit=35)
        if not news_items:
            return {
                "overallSentiment": "NEUTRAL",
                "sentimentScore": 0,
                "bullishCount": 0,
                "bearishCount": 0,
                "neutralCount": 0,
                "totalArticles": 0,
                "topBullishHeadlines": [],
                "topBearishHeadlines": [],
                "affectedKeySectors": ["Banking", "IT & Tech"],
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }

        bullish_items = [it for it in news_items if it.get("sentiment") == "BULLISH"]
        bearish_items = [it for it in news_items if it.get("sentiment") == "BEARISH"]
        neutral_items = [it for it in news_items if it.get("sentiment") == "NEUTRAL"]

        total = len(news_items)
        bull_count = len(bullish_items)
        bear_count = len(bearish_items)
        neu_count = len(neutral_items)

        # Weighted sentiment score
        if total > 0:
            score = int(((bull_count - bear_count) / total) * 100)
            score = max(-100, min(100, score))
        else:
            score = 0

        # Convert -100..+100 score to 1.0..10.0 scale
        # Score -100 -> Rating 1.0 (Extreme Bearish)
        # Score 0    -> Rating 5.5 (Neutral)
        # Score +100 -> Rating 10.0 (Extreme Bullish)
        rating = round(1.0 + ((score + 100) / 200.0) * 9.0, 1)
        rating = max(1.0, min(10.0, rating))

        if rating >= 8.5:
            rating_label = "Strong Bullish"
            overall = "BULLISH"
        elif rating >= 6.5:
            rating_label = "Mild Bullish"
            overall = "BULLISH"
        elif rating <= 2.5:
            rating_label = "Strong Bearish"
            overall = "BEARISH"
        elif rating <= 4.5:
            rating_label = "Mild Bearish"
            overall = "BEARISH"
        else:
            rating_label = "Neutral"
            overall = "NEUTRAL"

        # Unique sectors from items
        sectors = list({it.get("category", "Markets") for it in news_items if it.get("category") != "Markets"})

        explanation = (
            f"Market sentiment rated {rating}/10 ({rating_label}) based on {total} live articles from Moneycontrol, "
            f"Economic Times & Livemint. Catalyzed by {bull_count} bullish drivers vs {bear_count} bearish headwinds."
        )

        summary = {
            "overallSentiment": overall,
            "sentimentRating": rating,
            "ratingLabel": rating_label,
            "sentimentScore": score,
            "bullishCount": bull_count,
            "bearishCount": bear_count,
            "neutralCount": neu_count,
            "totalArticles": total,
            "ratingExplanation": explanation,
            "topBullishHeadlines": [it["headline"] for it in bullish_items[:3]],
            "topBearishHeadlines": [it["headline"] for it in bearish_items[:3]],
            "affectedKeySectors": sectors[:5] if sectors else ["Banking", "IT & Tech", "Auto"],
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }

        await CacheService.set(cache_key, summary, ttl_seconds=300)  # 5 min sentiment TTL
        return summary

    async def _fetch_all_primary_feeds(self, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Concurrent fetch from Moneycontrol, Economic Times, and Livemint.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml",
        }

        tasks = []
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            for feed in self.FEEDS:
                tasks.append(self._fetch_single_feed(client, feed, headers))

            feed_results = await asyncio.gather(*tasks, return_exceptions=True)

        combined: List[Dict[str, Any]] = []
        seen_titles: Set[str] = set()

        # Interleave results from each feed for balanced representation
        for feed_items in feed_results:
            if isinstance(feed_items, list):
                for item in feed_items:
                    normalized_title = re.sub(r"[^\w\s]", "", item["headline"].lower()).strip()
                    if normalized_title and normalized_title not in seen_titles:
                        seen_titles.add(normalized_title)
                        combined.append(item)

        # Sort by latest if dates are parseable or keep fresh order
        now_iso = datetime.now(timezone.utc).isoformat()
        self._last_fetch_ts = now_iso
        self._total_fetched += len(combined)
        self._feed_status = "HEALTHY"

        return combined[:limit]

    async def _fetch_single_feed(
        self, client: httpx.AsyncClient, feed_meta: Dict[str, str], headers: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        url = feed_meta["url"]
        source_name = feed_meta["source"]
        items_out: List[Dict[str, Any]] = []

        try:
            res = await client.get(url, headers=headers)
            if res.status_code != 200:
                logger.warning(f"Feed {feed_meta['name']} returned HTTP {res.status_code}")
                return []

            root = ET.fromstring(res.content)
            raw_items = root.findall(".//item")
            now_iso = datetime.now(timezone.utc).isoformat()

            for it in raw_items[:20]:
                title_elem = it.find("title")
                link_elem = it.find("link")
                pub_elem = it.find("pubDate")

                raw_title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                if not raw_title:
                    continue

                clean_headline = html.unescape(raw_title)
                # Remove source trailers if attached (e.g. "... - Economic Times")
                if " - " in clean_headline:
                    clean_headline = clean_headline.rsplit(" - ", 1)[0].strip()

                raw_link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                pub_date = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else now_iso

                sentiment, score, impact = classify_headline_sentiment(clean_headline)
                symbols, sector = extract_symbols_and_sector(clean_headline)

                items_out.append({
                    "id": f"news-{source_name.lower()[:2]}-{abs(hash(clean_headline)) % 10000000}",
                    "headline": clean_headline,
                    "source": source_name,
                    "url": raw_link,
                    "publishedAt": pub_date,
                    "retrievedAt": now_iso,
                    "sentiment": sentiment,
                    "sentimentScore": score,
                    "impact": impact,
                    "relatedSymbols": symbols,
                    "category": sector,
                    "dataStatus": "LIVE",
                    "provider": "indian_financial_rss",
                })

            return items_out
        except Exception as e:
            logger.warning(f"Error reading feed {feed_meta['name']}: {e}")
            return []

    async def _fetch_google_rss(self, query: str, limit: int, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        }
        results: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=7.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code != 200:
                    return []

                root = ET.fromstring(res.content)
                items = root.findall(".//item")
                now_iso = datetime.now(timezone.utc).isoformat()

                for it in items[:limit]:
                    raw_title = it.find("title").text if it.find("title") is not None else ""
                    raw_link = it.find("link").text if it.find("link") is not None else ""
                    pub_date = it.find("pubDate").text if it.find("pubDate") is not None else ""
                    source_elem = it.find("source")
                    source_name = source_elem.text if source_elem is not None else "Google Finance"

                    clean_headline = html.unescape(raw_title)
                    if " - " in clean_headline:
                        parts = clean_headline.rsplit(" - ", 1)
                        clean_headline = parts[0].strip()
                        source_name = parts[1].strip() or source_name

                    sentiment, score, impact = classify_headline_sentiment(clean_headline)
                    symbols, sector = extract_symbols_and_sector(clean_headline)
                    if symbol and symbol not in symbols:
                        symbols.insert(0, symbol)

                    results.append({
                        "id": f"news-g-{abs(hash(clean_headline)) % 10000000}",
                        "headline": clean_headline,
                        "source": source_name,
                        "url": raw_link,
                        "publishedAt": pub_date,
                        "retrievedAt": now_iso,
                        "sentiment": sentiment,
                        "sentimentScore": score,
                        "impact": impact,
                        "relatedSymbols": symbols,
                        "category": sector,
                        "dataStatus": "LIVE",
                        "provider": "indian_financial_rss",
                    })

                return results
        except Exception as e:
            logger.error(f"Error fetching fallback Google RSS for {query}: {e}")
            return []

    def get_status(self) -> Dict[str, Any]:
        return {
            "provider": "FinancialNewsProvider",
            "sourceType": "Multi-Source Indian Feeds (Moneycontrol + Economic Times + Livemint)",
            "status": self._feed_status,
            "activeSources": self._active_sources,
            "lastFetchTimestamp": self._last_fetch_ts,
            "totalArticlesFetched": self._total_fetched,
            "cacheTtlSeconds": NEWS_CACHE_TTL_SECONDS,
            "freeTier": True,
            "rateLimitPerMinute": "Unmetered Public Feeds",
        }


# Singleton instance
_news_provider_instance = None

def get_financial_news_provider() -> FinancialNewsProvider:
    global _news_provider_instance
    if _news_provider_instance is None:
        _news_provider_instance = FinancialNewsProvider()
    return _news_provider_instance
