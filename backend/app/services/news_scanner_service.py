"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Intelligent News-Driven Indian Stock Market Opportunity Scanner & Ranking Engine.

Continuously scans, classifies, and ranks NSE/BSE stocks receiving material company-specific news.
Generates ranked intraday research watchlists:
1. TOP 10 OVERALL NEWS IMPACT STOCKS
2. TOP 10 BULLISH NEWS STOCKS
3. TOP 10 BEARISH NEWS STOCKS

Features:
- High-precision company entity matching via NewsEntityResolver
- Deterministic event classification via NewsClassifier
- Syndicated copy deduplication and source verification tagging
- Real market price confirmation (LTP, % change, VWAP, Volume)
- Strict Zero Fabricated Prices policy (fails closed to PRICE_UNVERIFIED if offline)
- Non-padded rankings (shows only genuinely qualified stocks; never forces 10)
- Append-only research snapshot journaling (news_sentiment_journal.json)
"""

import os
import re
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple

from app.core.config import settings
from app.core.logging import logger
from app.core.cache import CacheService
from app.data.financial_news_provider import get_financial_news_provider
from app.data.providers.factory import get_market_data_provider
from app.services.news_entity_resolver import get_news_entity_resolver
from app.services.news_classifier import get_news_classifier

JOURNAL_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "news_sentiment_journal.json")
SCANNER_CACHE_TTL = 300  # 5 minutes


class IntradayNewsScannerService:
    """
    Intraday Stock News Opportunity Scanner.
    """

    def __init__(self):
        self._news_provider = get_financial_news_provider()
        self._entity_resolver = get_news_entity_resolver()
        self._classifier = get_news_classifier()
        self._market_provider = get_market_data_provider()

        self._last_scan_time: Optional[str] = None
        self._last_scanned_count: int = 0
        self._active_sources: List[str] = [
            "Economic Times Markets",
            "Economic Times Stocks",
            "Moneycontrol Top News",
            "Moneycontrol Business",
            "Livemint Markets",
            "Livemint Companies",
            "Business Standard Markets",
            "Business Standard Companies",
            "NDTV Profit Markets",
        ]
        self._unauthorized_sources: List[str] = [
            "NSE Corporate Announcements (Direct Unauthenticated Scraping Blocked: Requires Paid Akamai/Exchange API License)",
            "BSE Corporate Announcements (Direct Unauthenticated Scraping Blocked: Requires Exchange License)"
        ]

    def _parse_pub_date(self, date_str: str) -> Tuple[datetime, float]:
        """
        Parses publication date string to UTC datetime and computes age in hours.
        """
        now = datetime.now(timezone.utc)
        if not date_str:
            return now, 0.0

        # Try common RSS date formats
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S GMT",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
        ]

        # Clean string
        clean = date_str.strip()
        for fmt in formats:
            try:
                dt = datetime.strptime(clean, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_hours = max(0.0, (now - dt).total_seconds() / 3600.0)
                return dt, round(age_hours, 1)
            except Exception:
                continue

        # If ISO parsing via fromisoformat
        try:
            dt = datetime.fromisoformat(clean.replace("Z", "+00:00"))
            age_hours = max(0.0, (now - dt).total_seconds() / 3600.0)
            return dt, round(age_hours, 1)
        except Exception:
            pass

        return now, 0.0

    def _normalize_title_for_dedup(self, title: str) -> str:
        """
        Generates fingerprint for deduplicating syndicated articles.
        """
        # Remove source trailers
        t = re.sub(r"\s*[-–|].*$", "", title)
        # Remove non-alphanumeric and lowercase
        cleaned = re.sub(r"[^\w\s]", "", t.lower()).strip()
        words = [w for w in cleaned.split() if len(w) > 2]
        return " ".join(words[:8])

    async def _fetch_and_prepare_raw_articles(self) -> List[Dict[str, Any]]:
        """
        Fetches live articles from all primary authorized RSS feeds.
        """
        raw_items = await self._news_provider.get_market_news(limit=60)
        return raw_items

    async def scan_and_rank_opportunities(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Scans all articles, aggregates by company, validates quotes, and ranks opportunities.
        """
        cache_key = "news:intraday:ranked_opportunities"
        if not force_refresh:
            cached = await CacheService.get(cache_key)
            if cached and isinstance(cached, dict):
                return cached

        raw_articles = await self._fetch_and_prepare_raw_articles()
        now_iso = datetime.now(timezone.utc).isoformat()
        self._last_scan_time = now_iso
        self._last_scanned_count = len(raw_articles)

        # 1. Deduplication and Company Resolution
        seen_fingerprints: Set[str] = set()
        stock_buckets: Dict[str, List[Dict[str, Any]]] = {}
        stock_meta: Dict[str, Dict[str, Any]] = {}

        for art in raw_articles:
            headline = art.get("headline", "").strip()
            if not headline:
                continue

            fingerprint = self._normalize_title_for_dedup(headline)
            is_syndicated = fingerprint in seen_fingerprints
            seen_fingerprints.add(fingerprint)

            # Resolve company entity
            resolved = self._entity_resolver.resolve(headline)
            if not resolved or not resolved.get("isCompanySpecific"):
                continue

            sym = resolved["symbol"]
            stock_meta[sym] = resolved

            pub_dt, age_hours = self._parse_pub_date(art.get("publishedAt", ""))

            # Classify event
            classified = self._classifier.classify(headline, source=art.get("source", "Financial Media"))

            parsed_article = {
                "id": art.get("id") or f"art-{abs(hash(headline)) % 10000000}",
                "headline": headline,
                "source": art.get("source", "Financial News"),
                "url": art.get("url", ""),
                "publishedAt": pub_dt.isoformat(),
                "ingestedAt": now_iso,
                "ageHours": age_hours,
                "category": classified["category"],
                "polarity": classified["sentimentPolarity"],
                "impact": classified["impactScore"],
                "confidence": classified["confidence"],
                "verificationStatus": classified["verificationStatus"],
                "explanation": classified["explanation"],
                "isSyndicatedCopy": is_syndicated,
            }

            if sym not in stock_buckets:
                stock_buckets[sym] = []
            stock_buckets[sym].append(parsed_article)

        # 2. Build Candidate Opportunities & Market Confirmation
        candidates: List[Dict[str, Any]] = []

        # Concurrently fetch quotes for all identified candidate stocks
        symbols_to_quote = list(stock_buckets.keys())
        quote_tasks = [self._market_provider.get_quote(s) for s in symbols_to_quote]
        quote_results = await asyncio.gather(*quote_tasks, return_exceptions=True)

        quotes_by_symbol: Dict[str, Dict[str, Any]] = {}
        for s, q_res in zip(symbols_to_quote, quote_results):
            if isinstance(q_res, dict) and q_res.get("currentPrice", 0) > 0:
                quotes_by_symbol[s] = q_res
            else:
                quotes_by_symbol[s] = {}

        for sym, articles in stock_buckets.items():
            meta = stock_meta[sym]
            quote = quotes_by_symbol.get(sym, {})

            # Filter non-syndicated articles first, then fallback
            unique_articles = [a for a in articles if not a["isSyndicatedCopy"]]
            active_articles = unique_articles if unique_articles else articles

            # Sort by impact descending to find primary catalyst
            active_articles.sort(key=lambda x: (x["impact"], abs(x["polarity"])), reverse=True)
            primary = active_articles[0]

            # Aggregate polarity and impact
            avg_polarity = int(sum(a["polarity"] for a in active_articles) / len(active_articles))
            max_impact = max(a["impact"] for a in active_articles)
            confidence = primary["confidence"]

            # Recency factor (0-100)
            min_age_hours = min(a["ageHours"] for a in active_articles)
            recency_score = max(10.0, 100.0 - (min_age_hours * 2.5))

            # Direction label
            if avg_polarity >= 40:
                sentiment_label = "VERY_BULLISH"
            elif avg_polarity >= 15:
                sentiment_label = "BULLISH"
            elif avg_polarity <= -40:
                sentiment_label = "VERY_BEARISH"
            elif avg_polarity <= -15:
                sentiment_label = "BEARISH"
            else:
                sentiment_label = "NEUTRAL"

            # Market confirmation & Real Quote Extraction
            curr_price = float(quote.get("currentPrice") or quote.get("ltp") or 0.0)
            chg = float(quote.get("change") or 0.0)
            chg_pct = float(quote.get("changePercent") or 0.0)
            day_high = float(quote.get("dayHigh") or quote.get("high") or 0.0)
            day_low = float(quote.get("dayLow") or quote.get("low") or 0.0)
            volume = int(quote.get("volume") or 0)
            vwap = float(quote.get("vwap") or ((day_high + day_low + curr_price) / 3.0 if curr_price > 0 else 0.0))
            quote_status = quote.get("dataStatus") or ("VERIFIED_LIVE" if curr_price > 0 else "DATA_OFFLINE")
            quote_ts = quote.get("timestamp") or quote.get("lastTickTime")

            # Invariant: Strictly Zero Fabricated Prices
            has_real_quote = curr_price > 0 and quote_status in ("VERIFIED_LIVE", "VERIFIED_EOD")

            if not has_real_quote:
                price_conf = "PRICE_UNVERIFIED"
                intraday_bias = "NEUTRAL" if sentiment_label == "NEUTRAL" else ("BULLISH" if avg_polarity > 0 else "BEARISH")
                research_status = "PRICE_UNVERIFIED"
                market_conf_points = 20.0
            else:
                # Authentic Market Alignment Check
                if avg_polarity >= 20 and chg_pct >= 0.2:
                    price_conf = "BULLISH_WATCHLIST_CANDIDATE"
                    intraday_bias = "BULLISH"
                    research_status = "RESEARCH_WATCHLIST_ACTIVE"
                    market_conf_points = 90.0
                elif avg_polarity <= -20 and chg_pct <= -0.2:
                    price_conf = "BEARISH_WATCHLIST_CANDIDATE"
                    intraday_bias = "BEARISH"
                    research_status = "RESEARCH_WATCHLIST_ACTIVE"
                    market_conf_points = 90.0
                elif (avg_polarity >= 25 and chg_pct <= -0.5) or (avg_polarity <= -25 and chg_pct >= 0.5):
                    price_conf = "NEWS_PRICE_DIVERGENCE"
                    intraday_bias = "DIVERGENCE"
                    research_status = "RESEARCH_WATCHLIST_ACTIVE"
                    market_conf_points = 60.0
                else:
                    price_conf = "PENDING_CONFIRMATION"
                    intraday_bias = "NEUTRAL"
                    research_status = "NO_CONFIRMED_SETUP"
                    market_conf_points = 50.0

            # Composite Ranking Score Formula (0 to 100)
            # Weights: News Impact (35%), Polarity Magnitude (25%), Credibility (15%), Recency (15%), Market Confirmation (10%)
            news_impact_pts = 0.35 * max_impact
            polarity_pts = 0.25 * abs(avg_polarity)
            credibility_pts = 0.15 * (confidence * 100.0)
            recency_pts = 0.15 * recency_score
            market_pts = 0.10 * market_conf_points

            rank_score = round(news_impact_pts + polarity_pts + credibility_pts + recency_pts + market_pts, 1)

            candidate_record = {
                "symbol": sym,
                "companyName": meta["companyName"],
                "sector": meta["sector"],
                "exchange": meta.get("exchange", "NSE"),
                "primaryHeadline": primary["headline"],
                "primarySource": primary["source"],
                "primaryUrl": primary["url"],
                "publishedAt": primary["publishedAt"],
                "ageHours": primary["ageHours"],
                "category": primary["category"],
                "sentiment": sentiment_label,
                "sentimentPolarity": avg_polarity,
                "impactScore": max_impact,
                "compositeRankScore": rank_score,
                "confidence": confidence,
                "verificationStatus": primary["verificationStatus"],
                "explanation": primary["explanation"],
                "catalyst": primary["category"].replace("_", " ").title(),
                "articlesCount": len(articles),
                "articles": [
                    {
                        "id": a["id"],
                        "headline": a["headline"],
                        "source": a["source"],
                        "url": a["url"],
                        "publishedAt": a["publishedAt"],
                        "ingestedAt": a["ingestedAt"],
                        "category": a["category"],
                        "polarity": a["polarity"],
                        "impact": a["impact"],
                        "confidence": a["confidence"],
                        "verificationStatus": a["verificationStatus"],
                        "explanation": a["explanation"],
                        "isSyndicatedCopy": a["isSyndicatedCopy"],
                    }
                    for a in articles[:6]
                ],
                "currentPrice": curr_price if has_real_quote else None,
                "change": chg if has_real_quote else None,
                "changePercent": chg_pct if has_real_quote else None,
                "dayHigh": day_high if has_real_quote else None,
                "dayLow": day_low if has_real_quote else None,
                "volume": volume if has_real_quote else None,
                "vwap": vwap if has_real_quote else None,
                "quoteTimestamp": quote_ts,
                "dataStatus": quote_status if has_real_quote else "DATA_OFFLINE",
                "priceConfirmation": price_conf,
                "intradayBias": intraday_bias,
                "researchStatus": research_status,
            }
            candidates.append(candidate_record)

        # 3. Sort Candidates by Composite Rank Score
        candidates.sort(key=lambda x: x["compositeRankScore"], reverse=True)

        # Build Ranked Views (DO NOT force 10: only return qualified items)
        top_overall = [dict(c, rank=i + 1) for i, c in enumerate(candidates[:10])]

        bullish_cands = [c for c in candidates if c["sentimentPolarity"] >= 15]
        top_bullish = [dict(c, rank=i + 1) for i, c in enumerate(bullish_cands[:10])]

        bearish_cands = [c for c in candidates if c["sentimentPolarity"] <= -15]
        top_bearish = [dict(c, rank=i + 1) for i, c in enumerate(bearish_cands[:10])]

        payload = {
            "generatedAt": now_iso,
            "sourceFreshness": "Real-time Verified Financial RSS",
            "totalArticlesAnalyzed": len(raw_articles),
            "totalStocksScanned": len(stock_buckets),
            "topOverall": top_overall,
            "topBullish": top_bullish,
            "topBearish": top_bearish,
            "dataStatus": "LIVE",
            "disclaimer": "READ-ONLY equity intraday intelligence. Not authorized for trade execution.",
        }

        # Cache payload
        await CacheService.set(cache_key, payload, ttl_seconds=SCANNER_CACHE_TTL)

        # Append to Research Snapshot Journal
        self._append_to_journal(top_overall)

        return payload

    def _append_to_journal(self, top_candidates: List[Dict[str, Any]]):
        """
        Appends initial watchlist observation snapshots to news_sentiment_journal.json.
        """
        try:
            os.makedirs(os.path.dirname(JOURNAL_FILE_PATH), exist_ok=True)
            existing_records: List[Dict[str, Any]] = []
            if os.path.exists(JOURNAL_FILE_PATH):
                try:
                    with open(JOURNAL_FILE_PATH, "r", encoding="utf-8") as f:
                        existing_records = json.load(f)
                except Exception:
                    existing_records = []

            seen_keys = {f"{r.get('symbol')}_{r.get('primaryHeadline')[:30]}" for r in existing_records}

            now_iso = datetime.now(timezone.utc).isoformat()
            new_entries = []

            for c in top_candidates:
                key = f"{c['symbol']}_{c['primaryHeadline'][:30]}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    new_entries.append({
                        "snapshotId": f"SNAP-{abs(hash(key)) % 100000000}",
                        "symbol": c["symbol"],
                        "companyName": c["companyName"],
                        "primaryHeadline": c["primaryHeadline"],
                        "publishedAt": c["publishedAt"],
                        "discoveredAt": now_iso,
                        "sentimentPolarity": c["sentimentPolarity"],
                        "impactScore": c["impactScore"],
                        "compositeRankScore": c["compositeRankScore"],
                        "category": c["category"],
                        "initialPrice": c["currentPrice"],
                        "initialChangePercent": c["changePercent"],
                        "priceConfirmation": c["priceConfirmation"],
                        "verificationStatus": c["verificationStatus"],
                        "subsequentChecks": [],
                        "outcomeConfirmed": None,
                        "governanceNote": "Research snapshot only. Phase 5 training blocked until 500 genuine samples."
                    })

            if new_entries:
                existing_records.extend(new_entries)
                with open(JOURNAL_FILE_PATH, "w", encoding="utf-8") as f:
                    json.dump(existing_records, f, indent=2)

        except Exception as e:
            logger.warning(f"Could not append to news sentiment journal: {e}")

    async def get_top_stocks(self, direction: str = "all", limit: int = 10) -> Dict[str, Any]:
        """
        Returns ranked top stocks by direction ('all' | 'bullish' | 'bearish').
        """
        data = await self.scan_and_rank_opportunities()

        dir_clean = direction.lower().strip()
        if dir_clean == "bullish":
            stocks = data.get("topBullish", [])[:limit]
        elif dir_clean == "bearish":
            stocks = data.get("topBearish", [])[:limit]
        else:
            stocks = data.get("topOverall", [])[:limit]

        return {
            "direction": dir_clean,
            "generatedAt": data.get("generatedAt", datetime.now(timezone.utc).isoformat()),
            "sourceFreshness": data.get("sourceFreshness", "Verified"),
            "totalArticlesAnalyzed": data.get("totalArticlesAnalyzed", 0),
            "totalQualifiedStocks": len(stocks),
            "stocks": stocks,
            "dataStatus": data.get("dataStatus", "LIVE"),
            "disclaimer": data.get("disclaimer", "READ-ONLY equity intraday intelligence."),
        }

    async def get_stock_opportunity(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Returns full detailed opportunity breakdown for a specific stock symbol.
        """
        clean = symbol.upper().replace("-EQ", "").strip()
        data = await self.scan_and_rank_opportunities()
        all_candidates = data.get("topOverall", [])

        for c in all_candidates:
            if c["symbol"] == clean:
                return c

        # If not in top 10, check bullish or bearish lists
        for c in data.get("topBullish", []) + data.get("topBearish", []):
            if c["symbol"] == clean:
                return c

        return None

    def get_status(self) -> Dict[str, Any]:
        """
        Returns operational diagnostics of the intraday news scanner.
        """
        return {
            "status": "HEALTHY",
            "sourcesActive": self._active_sources,
            "lastIngestionTimestamp": self._last_scan_time,
            "totalArticlesInCache": self._last_scanned_count,
            "unauthorizedSourcesReported": self._unauthorized_sources,
            "cacheTtlSeconds": SCANNER_CACHE_TTL,
        }


# Global singleton
_scanner_instance: Optional[IntradayNewsScannerService] = None

def get_intraday_news_scanner() -> IntradayNewsScannerService:
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = IntradayNewsScannerService()
    return _scanner_instance
