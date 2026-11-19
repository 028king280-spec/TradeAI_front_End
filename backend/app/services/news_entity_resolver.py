"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Indian Equity Entity & Symbol Resolver for News Analysis.

Accurately maps company names, brand names, and trading symbols to verified NSE/BSE listed equities.
Prevents generic market news from matching individual stocks, avoids substring collisions,
and validates resolved securities against Angel One InstrumentMaster (OpenAPIScripMaster).
"""

import re
from typing import Dict, List, Optional, Tuple, Set, Any
from app.core.logging import logger
from app.data.instrument_master import get_instrument_master

# Common English words or acronyms that clash with stock symbols
COMMON_WORDS_BLACKLIST = {
    "IT", "FOR", "ON", "CAN", "ALL", "NEW", "TOP", "BIG", "NOW", "KEY", "CAR",
    "BUY", "SELL", "CALL", "PUT", "HOLD", "HIGH", "LOW", "DEAL", "LOSS", "GAIN",
    "CASH", "CARE", "BEST", "TRUE", "FAST", "FUND", "GOLD", "BANK", "NEWS", "RATE",
    "GOOD", "WELL", "MORE", "LESS", "OPEN", "BEAT", "MISS", "RISE", "FALL", "DROP",
    "AUTO", "OIL", "GAS", "TECH", "NET", "DATA", "FREE", "POST", "REAL", "SAFE"
}

# Generic Macro / Market Index markers that must NOT map to individual stocks
GENERIC_MARKET_PATTERNS = [
    r"\bnifty\s*50\b", r"\bsensex\b", r"\bbank\s*nifty\b", r"\bfinnifty\b",
    r"\bindian\s*markets?\b", r"\bdalala?\s*street\b", r"\bwall\s*street\b",
    r"\bfiis?\b", r"\bdiis?\b", r"\brupee\b", r"\bfed\b", r"\brbi\s*mpc\b",
    r"\bglobal\s*cues\b", r"\basian\s*markets?\b", r"\bus\s*stocks?\b",
    r"\bcrude\s*oil\b", r"\bbond\s*yields?\b", r"\bipo\s*listing\b"
]

# Canonical Companies Dictionary (Name, Brand Variants, Sector)
EQUITY_DIRECTORY: List[Dict[str, Any]] = [
    # Mega Caps & Nifty 50
    {"symbol": "RELIANCE", "name": "Reliance Industries Limited", "sector": "Energy & Conglomerate", "aliases": ["RELIANCE", "RELIANCE INDUSTRIES", "RIL", "JIO", "RELIANCE RETAIL"]},
    {"symbol": "TCS", "name": "Tata Consultancy Services Limited", "sector": "Information Technology", "aliases": ["TCS", "TATA CONSULTANCY SERVICES", "TATA CONSULTANCY"]},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Limited", "sector": "Banking & Financials", "aliases": ["HDFC BANK", "HDFCBANK", "HDFC BK"]},
    {"symbol": "INFY", "name": "Infosys Limited", "sector": "Information Technology", "aliases": ["INFOSYS", "INFY"]},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Limited", "sector": "Banking & Financials", "aliases": ["ICICI BANK", "ICICIBANK", "ICICI BK"]},
    {"symbol": "SBIN", "name": "State Bank of India", "sector": "Banking & Financials", "aliases": ["STATE BANK OF INDIA", "SBI", "SBIN", "STATE BANK"]},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Limited", "sector": "Telecom", "aliases": ["BHARTI AIRTEL", "AIRTEL", "BHARTIARTL"]},
    {"symbol": "ITC", "name": "ITC Limited", "sector": "FMCG & Cigarettes", "aliases": ["ITC", "ITC LTD"]},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Limited", "sector": "Banking & Financials", "aliases": ["KOTAK MAHINDRA BANK", "KOTAK BANK", "KOTAKBANK", "KOTAK"]},
    {"symbol": "LT", "name": "Larsen & Toubro Limited", "sector": "Infrastructure & Capital Goods", "aliases": ["LARSEN & TOUBRO", "LARSEN AND TOUBRO", "L&T", "LARSEN", "L AND T"]},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever Limited", "sector": "FMCG", "aliases": ["HINDUSTAN UNILEVER", "HUL", "HINDUNILVR"]},
    {"symbol": "AXISBANK", "name": "Axis Bank Limited", "sector": "Banking & Financials", "aliases": ["AXIS BANK", "AXISBANK", "AXIS BK"]},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Limited", "sector": "NBFC & Financials", "aliases": ["BAJAJ FINANCE", "BAJFINANCE", "BAJAJ FIN"]},
    {"symbol": "BAJAJFINSV", "name": "Bajaj Finserv Limited", "sector": "NBFC & Financials", "aliases": ["BAJAJ FINSERV", "BAJAJFINSV"]},
    {"symbol": "MARUTI", "name": "Maruti Suzuki India Limited", "sector": "Automobiles", "aliases": ["MARUTI SUZUKI", "MARUTI", "MARUTI SUZUKI INDIA"]},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Limited", "sector": "Automobiles", "aliases": ["TATA MOTORS", "TATAMOTORS", "JLR", "JAGUAR LAND ROVER"]},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Limited", "sector": "Pharmaceuticals", "aliases": ["SUN PHARMA", "SUN PHARMACEUTICAL", "SUNPHARMA"]},
    {"symbol": "TATASTEEL", "name": "Tata Steel Limited", "sector": "Metals & Mining", "aliases": ["TATA STEEL", "TATASTEEL"]},
    {"symbol": "NTPC", "name": "NTPC Limited", "sector": "Power Generation", "aliases": ["NTPC", "NTPC LTD"]},
    {"symbol": "POWERGRID", "name": "Power Grid Corporation of India", "sector": "Power Transmission", "aliases": ["POWER GRID", "POWERGRID", "PGCIL"]},
    {"symbol": "ONGC", "name": "Oil and Natural Gas Corporation", "sector": "Oil & Gas", "aliases": ["ONGC", "OIL AND NATURAL GAS"]},
    {"symbol": "TITAN", "name": "Titan Company Limited", "sector": "Consumer Discretionary", "aliases": ["TITAN", "TITAN COMPANY", "TANISHQ"]},
    {"symbol": "ADANIENT", "name": "Adani Enterprises Limited", "sector": "Conglomerate", "aliases": ["ADANI ENTERPRISES", "ADANIENT", "ADANI ENT"]},
    {"symbol": "ADANIPORTS", "name": "Adani Ports and Special Economic Zone", "sector": "Logistics & Ports", "aliases": ["ADANI PORTS", "ADANIPORTS", "APSEZ"]},
    {"symbol": "COALINDIA", "name": "Coal India Limited", "sector": "Metals & Mining", "aliases": ["COAL INDIA", "COALINDIA", "CIL"]},
    {"symbol": "WIPRO", "name": "Wipro Limited", "sector": "Information Technology", "aliases": ["WIPRO", "WIPRO LTD"]},
    {"symbol": "ASIANPAINT", "name": "Asian Paints Limited", "sector": "Paints & Chemicals", "aliases": ["ASIAN PAINTS", "ASIAN PAINT", "ASIANPAINT"]},
    {"symbol": "HCLTECH", "name": "HCL Technologies Limited", "sector": "Information Technology", "aliases": ["HCL TECH", "HCL TECHNOLOGIES", "HCLTECH"]},
    {"symbol": "ULTRACEMCO", "name": "UltraTech Cement Limited", "sector": "Cement & Building Materials", "aliases": ["ULTRATECH CEMENT", "ULTRACEMCO", "ULTRATECH"]},
    {"symbol": "JSWSTEEL", "name": "JSW Steel Limited", "sector": "Metals & Mining", "aliases": ["JSW STEEL", "JSWSTEEL"]},
    {"symbol": "GRASIM", "name": "Grasim Industries Limited", "sector": "Chemicals & Materials", "aliases": ["GRASIM", "GRASIM INDUSTRIES"]},
    {"symbol": "HEROMOTOCO", "name": "Hero MotoCorp Limited", "sector": "Automobiles", "aliases": ["HERO MOTOCORP", "HEROMOTOCO", "HERO HONDA"]},
    {"symbol": "TECHM", "name": "Tech Mahindra Limited", "sector": "Information Technology", "aliases": ["TECH MAHINDRA", "TECHM"]},
    {"symbol": "DIVISLAB", "name": "Divi's Laboratories Limited", "sector": "Pharmaceuticals", "aliases": ["DIVIS LAB", "DIVI'S LAB", "DIVISLAB", "DIVIS LABORATORIES"]},
    {"symbol": "CIPLA", "name": "Cipla Limited", "sector": "Pharmaceuticals", "aliases": ["CIPLA", "CIPLA LTD"]},
    {"symbol": "APOLLOHOSP", "name": "Apollo Hospitals Enterprise Limited", "sector": "Healthcare", "aliases": ["APOLLO HOSPITALS", "APOLLOHOSP", "APOLLO HOSPITAL"]},
    {"symbol": "EICHERMOT", "name": "Eicher Motors Limited", "sector": "Automobiles", "aliases": ["EICHER MOTORS", "EICHERMOT", "ROYAL ENFIELD"]},
    {"symbol": "BPCL", "name": "Bharat Petroleum Corporation Limited", "sector": "Oil & Gas Refining", "aliases": ["BHARAT PETROLEUM", "BPCL"]},
    {"symbol": "LTIM", "name": "LTIMindtree Limited", "sector": "Information Technology", "aliases": ["LTIMINDTREE", "LTIM", "MINDTREE"]},
    {"symbol": "BRITANNIA", "name": "Britannia Industries Limited", "sector": "FMCG", "aliases": ["BRITANNIA", "BRITANNIA INDUSTRIES"]},
    {"symbol": "TATACONSUM", "name": "Tata Consumer Products Limited", "sector": "FMCG", "aliases": ["TATA CONSUMER", "TATACONSUM", "TATA TEA"]},
    {"symbol": "HINDALCO", "name": "Hindalco Industries Limited", "sector": "Metals & Mining", "aliases": ["HINDALCO", "HINDALCO INDUSTRIES", "NOVELIS"]},
    {"symbol": "NESTLEIND", "name": "Nestle India Limited", "sector": "FMCG", "aliases": ["NESTLE INDIA", "NESTLEIND", "NESTLE"]},
    {"symbol": "DRREDDY", "name": "Dr. Reddy's Laboratories Limited", "sector": "Pharmaceuticals", "aliases": ["DR REDDY", "DR REDDYS", "DRREDDY", "DR. REDDY'S"]},
    {"symbol": "M&M", "name": "Mahindra & Mahindra Limited", "sector": "Automobiles", "aliases": ["MAHINDRA & MAHINDRA", "M&M", "MAHINDRA AND MAHINDRA", "MAHINDRA"]},

    # High Momentum, Defense, PSUs, Capital Goods & New Age Leaders
    {"symbol": "BEL", "name": "Bharat Electronics Limited", "sector": "Defense & Electronics", "aliases": ["BHARAT ELECTRONICS", "BEL"]},
    {"symbol": "HAL", "name": "Hindustan Aeronautics Limited", "sector": "Defense & Aerospace", "aliases": ["HINDUSTAN AERONAUTICS", "HAL"]},
    {"symbol": "MAZDOCK", "name": "Mazagon Dock Shipbuilders Limited", "sector": "Defense & Shipbuilding", "aliases": ["MAZAGON DOCK", "MAZDOCK", "MAZAGON DOCK SHIPBUILDERS"]},
    {"symbol": "COCHINSHIP", "name": "Cochin Shipyard Limited", "sector": "Defense & Shipbuilding", "aliases": ["COCHIN SHIPYARD", "COCHINSHIP"]},
    {"symbol": "BDL", "name": "Bharat Dynamics Limited", "sector": "Defense & Missiles", "aliases": ["BHARAT DYNAMICS", "BDL"]},
    {"symbol": "TRENT", "name": "Trent Limited", "sector": "Retail & Fashion", "aliases": ["TRENT", "ZUDIO", "WESTSIDE"]},
    {"symbol": "VEDL", "name": "Vedanta Limited", "sector": "Metals & Mining", "aliases": ["VEDANTA", "VEDL"]},
    {"symbol": "ZOMATO", "name": "Zomato Limited", "sector": "Consumer Internet & Quick Commerce", "aliases": ["ZOMATO", "BLINKIT"]},
    {"symbol": "JIOFIN", "name": "Jio Financial Services Limited", "sector": "Financial Services", "aliases": ["JIO FINANCIAL", "JIO FINANCIAL SERVICES", "JIOFIN", "JFSL"]},
    {"symbol": "BSE", "name": "BSE Limited", "sector": "Capital Markets", "aliases": ["BSE LTD", "BSE LIMITED", "BOMBAY STOCK EXCHANGE"]},
    {"symbol": "SUZLON", "name": "Suzlon Energy Limited", "sector": "Renewable Energy", "aliases": ["SUZLON", "SUZLON ENERGY"]},
    {"symbol": "IREDA", "name": "Indian Renewable Energy Development Agency", "sector": "Renewable Finance", "aliases": ["IREDA", "INDIAN RENEWABLE ENERGY"]},
    {"symbol": "HUDCO", "name": "Housing and Urban Development Corporation", "sector": "Infrastructure Finance", "aliases": ["HUDCO"]},
    {"symbol": "RVNL", "name": "Rail Vikas Nigam Limited", "sector": "Railway Infrastructure", "aliases": ["RAIL VIKAS NIGAM", "RVNL"]},
    {"symbol": "IRFC", "name": "Indian Railway Finance Corporation", "sector": "Railway Finance", "aliases": ["INDIAN RAILWAY FINANCE", "IRFC"]},
    {"symbol": "BHEL", "name": "Bharat Heavy Electricals Limited", "sector": "Heavy Electricals", "aliases": ["BHARAT HEAVY ELECTRICALS", "BHEL"]},
    {"symbol": "NHPC", "name": "NHPC Limited", "sector": "Hydro Power", "aliases": ["NHPC", "NHPC LTD"]},
    {"symbol": "PFC", "name": "Power Finance Corporation", "sector": "Power Finance", "aliases": ["POWER FINANCE CORPORATION", "PFC"]},
    {"symbol": "RECLTD", "name": "REC Limited", "sector": "Power Finance", "aliases": ["REC LIMITED", "RECLTD", "RURAL ELECTRIFICATION"]},
    {"symbol": "TATAPOWER", "name": "Tata Power Company Limited", "sector": "Power & Solar", "aliases": ["TATA POWER", "TATAPOWER"]},
    {"symbol": "ADANIPOWER", "name": "Adani Power Limited", "sector": "Power & Utilities", "aliases": ["ADANI POWER", "ADANIPOWER"]},
    {"symbol": "ADANIGREEN", "name": "Adani Green Energy Limited", "sector": "Renewable Power", "aliases": ["ADANI GREEN", "ADANIGREEN"]},
    {"symbol": "TVSMOTOR", "name": "TVS Motor Company Limited", "sector": "Automobiles", "aliases": ["TVS MOTOR", "TVSMOTOR", "TVS"]},
    {"symbol": "BAJAJ-AUTO", "name": "Bajaj Auto Limited", "sector": "Automobiles", "aliases": ["BAJAJ AUTO", "BAJAJ-AUTO"]},
    {"symbol": "SAMVARDHANA", "name": "Samvardhana Motherson International", "sector": "Auto Ancillary", "aliases": ["MOTHERSON", "SAMVARDHANA MOTHERSON", "MOTHERSON SUMI"]},
    {"symbol": "AMBUJACEM", "name": "Ambuja Cements Limited", "sector": "Cement", "aliases": ["AMBUJA CEMENTS", "AMBUJA CEMENT", "AMBUJACEM"]},
    {"symbol": "ACC", "name": "ACC Limited", "sector": "Cement", "aliases": ["ACC CEMENT", "ACC LIMITED"]},
    {"symbol": "DLF", "name": "DLF Limited", "sector": "Real Estate", "aliases": ["DLF", "DLF LTD"]},
    {"symbol": "GODREJPROP", "name": "Godrej Properties Limited", "sector": "Real Estate", "aliases": ["GODREJ PROPERTIES", "GODREJPROP"]},
    {"symbol": "POLYCAB", "name": "Polycab India Limited", "sector": "Cables & Wires", "aliases": ["POLYCAB", "POLYCAB INDIA"]},
    {"symbol": "DIXON", "name": "Dixon Technologies (India) Limited", "sector": "Electronics Manufacturing", "aliases": ["DIXON", "DIXON TECH", "DIXON TECHNOLOGIES"]},
    {"symbol": "KALYANKJIL", "name": "Kalyan Jewellers India Limited", "sector": "Jewellery", "aliases": ["KALYAN JEWELLERS", "KALYANKJIL"]},
    {"symbol": "MUTHOOTFIN", "name": "Muthoot Finance Limited", "sector": "Gold Loan NBFC", "aliases": ["MUTHOOT FINANCE", "MUTHOOTFIN"]},
    {"symbol": "CHOLAFIN", "name": "Cholamandalam Investment and Finance", "sector": "Vehicle Finance NBFC", "aliases": ["CHOLAMANDALAM", "CHOLAFIN", "CHOLA FINANCE"]},
    {"symbol": "YESBANK", "name": "Yes Bank Limited", "sector": "Banking", "aliases": ["YES BANK", "YESBANK"]},
    {"symbol": "PAYTM", "name": "One97 Communications Limited (Paytm)", "sector": "Fintech", "aliases": ["PAYTM", "ONE97", "ONE 97"]},
    {"symbol": "PNB", "name": "Punjab National Bank", "sector": "Banking & Financials", "aliases": ["PUNJAB NATIONAL BANK", "PNB"]},
    {"symbol": "BANKBARODA", "name": "Bank of Baroda", "sector": "Banking & Financials", "aliases": ["BANK OF BARODA", "BANKBARODA", "BOB"]},
    {"symbol": "CANBK", "name": "Canara Bank", "sector": "Banking & Financials", "aliases": ["CANARA BANK", "CANBK"]},
    {"symbol": "UNIONBANK", "name": "Union Bank of India", "sector": "Banking & Financials", "aliases": ["UNION BANK OF INDIA", "UNION BANK", "UNIONBANK"]},
    {"symbol": "IDFCFIRSTB", "name": "IDFC First Bank Limited", "sector": "Banking & Financials", "aliases": ["IDFC FIRST BANK", "IDFC FIRST", "IDFCFIRSTB"]},
    {"symbol": "INDUSINDBK", "name": "IndusInd Bank Limited", "sector": "Banking & Financials", "aliases": ["INDUSIND BANK", "INDUSINDBK", "INDUSIND"]},
    {"symbol": "SAIL", "name": "Steel Authority of India Limited", "sector": "Metals & Mining", "aliases": ["STEEL AUTHORITY OF INDIA", "SAIL"]},
    {"symbol": "JINDALSTEL", "name": "Jindal Steel & Power Limited", "sector": "Metals & Mining", "aliases": ["JINDAL STEEL", "JINDALSTEL", "JSPL"]},
    {"symbol": "NMDC", "name": "NMDC Limited", "sector": "Metals & Mining", "aliases": ["NMDC", "NMDC LTD"]},
    {"symbol": "GAIL", "name": "GAIL (India) Limited", "sector": "Gas Transmission", "aliases": ["GAIL", "GAIL INDIA"]},
    {"symbol": "LUPIN", "name": "Lupin Limited", "sector": "Pharmaceuticals", "aliases": ["LUPIN", "LUPIN LTD"]},
    {"symbol": "AUROPHARMA", "name": "Aurobindo Pharma Limited", "sector": "Pharmaceuticals", "aliases": ["AUROBINDO PHARMA", "AUROPHARMA", "AUROBINDO"]},
    {"symbol": "BIOCON", "name": "Biocon Limited", "sector": "Biotechnology", "aliases": ["BIOCON", "BIOCON BIOLOGICS"]},
    {"symbol": "MANKIND", "name": "Mankind Pharma Limited", "sector": "Pharmaceuticals", "aliases": ["MANKIND PHARMA", "MANKIND"]},
    {"symbol": "ZYDUSLIFE", "name": "Zydus Lifesciences Limited", "sector": "Pharmaceuticals", "aliases": ["ZYDUS LIFESCIENCES", "ZYDUS LIFE", "ZYDUSLIFE", "CADILA"]},
    {"symbol": "PERSISTENT", "name": "Persistent Systems Limited", "sector": "Information Technology", "aliases": ["PERSISTENT SYSTEMS", "PERSISTENT"]},
    {"symbol": "COFORGE", "name": "Coforge Limited", "sector": "Information Technology", "aliases": ["COFORGE", "NIIT TECH"]},
    {"symbol": "KPITTECH", "name": "KPIT Technologies Limited", "sector": "Auto Software & IT", "aliases": ["KPIT TECH", "KPIT TECHNOLOGIES", "KPITTECH"]},
    {"symbol": "DMART", "name": "Avenue Supermarts Limited (DMart)", "sector": "Retail Supermarkets", "aliases": ["DMART", "AVENUE SUPERMARTS", "D-MART"]},
    {"symbol": "DELHIVERY", "name": "Delhivery Limited", "sector": "Logistics & Supply Chain", "aliases": ["DELHIVERY"]},
    {"symbol": "POLICYBZR", "name": "PB Fintech Limited (PolicyBazaar)", "sector": "Fintech & Insurance", "aliases": ["POLICYBAZAAR", "PB FINTECH", "POLICYBZR"]},
    {"symbol": "NYKAA", "name": "FSN E-Commerce Ventures (Nykaa)", "sector": "Beauty & Fashion E-Commerce", "aliases": ["NYKAA", "FSN E-COMMERCE"]},
]


class NewsEntityResolver:
    """
    High-Precision Company Entity & Symbol Resolver for Indian Equities.
    Maps article headlines and body snippets to verified NSE listed companies.
    """

    def __init__(self):
        self._build_lookup_indices()
        self._instrument_master = get_instrument_master()

    def _build_lookup_indices(self):
        self.symbol_to_meta: Dict[str, Dict[str, Any]] = {}
        # Sorted aliases by length descending so longer phrases match first (e.g. "TATA MOTORS" before "TATA")
        self.alias_patterns: List[Tuple[re.Pattern, str, str]] = []

        for item in EQUITY_DIRECTORY:
            sym = item["symbol"]
            self.symbol_to_meta[sym] = item

            # Sort aliases by word length descending
            sorted_aliases = sorted(item["aliases"], key=lambda x: len(x.split()), reverse=True)
            for alias in sorted_aliases:
                # Compile regex with word boundaries
                escaped = re.escape(alias)
                # Handle special characters like & or '
                pattern_str = rf"(?<!\w){escaped}(?!\w)"
                pat = re.compile(pattern_str, re.IGNORECASE)
                self.alias_patterns.append((pat, sym, item["name"]))

    def is_generic_market_news(self, text: str) -> bool:
        """
        Detects if headline is macro/market-wide commentary without company focus.
        """
        text_lower = text.lower()
        # If text explicitly mentions NIFTY/SENSEX dropping or rising generically
        has_macro_marker = any(re.search(pat, text_lower) for pat in GENERIC_MARKET_PATTERNS)
        return bool(has_macro_marker)

    def resolve(self, headline: str, summary: str = "") -> Optional[Dict[str, Any]]:
        """
        Resolves the primary company in the headline.
        Returns metadata dict if identified and verified, or None.
        """
        full_text = f"{headline} {summary}".strip()
        headline_upper = headline.upper()

        # 1. First priority: Check headline for exact alias matches
        matched_symbols: List[Tuple[str, str, int]] = []  # (symbol, company_name, match_len)

        for pat, sym, company_name in self.alias_patterns:
            m = pat.search(headline)
            if m:
                # Verify match is not blacklisted word
                matched_word = m.group(0).upper()
                if matched_word in COMMON_WORDS_BLACKLIST:
                    continue
                matched_symbols.append((sym, company_name, len(matched_word)))

        # 2. If no direct match in headline, check summary
        if not matched_symbols and summary:
            for pat, sym, company_name in self.alias_patterns:
                m = pat.search(summary)
                if m:
                    matched_word = m.group(0).upper()
                    if matched_word in COMMON_WORDS_BLACKLIST:
                        continue
                    matched_symbols.append((sym, company_name, len(matched_word)))

        if not matched_symbols:
            return None

        # Sort by match length descending (prefer specific company like "TATA MOTORS" over "TATA")
        matched_symbols.sort(key=lambda x: x[2], reverse=True)
        best_sym, best_company, _ = matched_symbols[0]

        meta = self.symbol_to_meta.get(best_sym, {})
        sector = meta.get("sector", "Diversified")
        official_name = meta.get("name", best_company)

        # 3. Cross-validate with InstrumentMaster (OpenAPIScripMaster)
        is_verified_scrip = False
        exchange_token = None
        instrument_type = "EQUITY"

        try:
            eq = self._instrument_master.get_equity(best_sym)
            if eq:
                is_verified_scrip = True
                exchange_token = eq.get("token")
                instrument_type = eq.get("instrumenttype") or "EQUITY"
        except Exception as e:
            logger.warning(f"Error cross-validating {best_sym} with InstrumentMaster: {e}")

        return {
            "symbol": best_sym,
            "companyName": official_name,
            "sector": sector,
            "exchange": "NSE",
            "token": exchange_token,
            "instrumentType": instrument_type,
            "isVerifiedInstrument": is_verified_scrip,
            "isCompanySpecific": True,
        }


# Singleton instance helper
_resolver_instance: Optional[NewsEntityResolver] = None

def get_news_entity_resolver() -> NewsEntityResolver:
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = NewsEntityResolver()
    return _resolver_instance
