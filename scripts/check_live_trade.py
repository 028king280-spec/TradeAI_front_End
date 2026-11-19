import urllib.request
import urllib.parse
import json

def get_nifty_full():
    url = f"http://127.0.0.1:8000/api/options/NIFTY%2050/next-session/recommendation"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            d = json.loads(resp.read().decode('utf-8'))
            print("=== NIFTY RECOMMENDATION DETAILS ===")
            print("Symbol:", d.get("symbol"))
            print("Stage:", d.get("stage"))
            print("Decision:", d.get("decisionBadge"))
            rec = d.get("recommendation")
            if rec:
                print("Contract:", rec.get("contractSymbol"))
                print("Expiry:", rec.get("expiry"))
                print("Strike:", rec.get("strike"))
                print("Option Type:", rec.get("optionType"))
                print("LTP:", rec.get("lastVerifiedPremium"))
                print("Suggested Entry:", rec.get("suggestedEntryRange"))
                print("SL:", rec.get("stopLossPremium"))
                print("T1:", rec.get("target1Premium"))
                print("T2:", rec.get("target2Premium"))
                print("T3:", rec.get("target3Premium"))
                print("R:R:", rec.get("riskRewardRatio"))
                print("Do-Not-Chase:", rec.get("doNotChaseThreshold"))
                print("Entry Condition:", rec.get("entryConfirmationCondition"))
                print("Invalidation:", rec.get("invalidationCondition"))
                print("Underlying Trigger:", rec.get("underlyingTrigger"))
                print("Max Risk:", rec.get("financialImpact", {}).get("maxRiskINR"))
                print("Potential Reward:", rec.get("financialImpact", {}).get("potentialRewardINR"))
                print("Lot Size:", rec.get("financialImpact", {}).get("lotSize"))
                print("Reasons:", rec.get("reasonsForSelection"))
    except Exception as e:
        print("Rec Error:", e)

def get_intraday_setups():
    for sym in ["NIFTY 50", "BANKNIFTY"]:
        url = f"http://127.0.0.1:8000/api/options/{urllib.parse.quote(sym)}/setups"
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                d = json.loads(resp.read().decode('utf-8'))
                print(f"=== INTRADAY SETUPS: {sym} ===")
                print("Has Qualified:", d.get("hasQualifiedSetups"))
                print("Status:", d.get("statusMessage"))
                setups = d.get("setups", [])
                print(f"Total: {len(setups)}")
                for s in setups:
                    print(f"  {s.get('bias')} {s.get('contractSymbol')} CMP: ₹{s.get('currentPremium')} SL: ₹{s.get('stopLoss')} T1: ₹{s.get('target1')} T2: ₹{s.get('target2')} R:R: {s.get('riskRewardRatio')}")
                    print(f"    Trigger: {s.get('underlyingTrigger')}")
        except Exception as e:
            print(f"Setups Error {sym}:", e)

if __name__ == "__main__":
    get_nifty_full()
    get_intraday_setups()
