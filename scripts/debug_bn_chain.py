import sys
sys.path.append('d:/ReactJs/aivolve-trading-ai/backend')
import json
from app.options.option_chain import generate_index_option_chain
from app.data.quality_validator import DataQualityEngine
from app.data.instrument_master import get_instrument_master

# Test BANK NIFTY chain generation and audit
ltp = 63549.65
master = get_instrument_master()
chain = generate_index_option_chain("BANK NIFTY", ltp, filter_mode="ATM")
print("Strikes count:", len(chain.get("strikes", [])))
for s in chain.get("strikes", []):
    print("Strike:", s.get("strikePrice"), "CE LTP:", s.get("ce", {}).get("ltp"), "PE LTP:", s.get("pe", {}).get("ltp"), "CE OI:", s.get("ce", {}).get("openInterest"))

audit = DataQualityEngine.validate_option_chain("BANK NIFTY", chain.get("strikes", []), ltp)
print("\nAudit result:", audit)
