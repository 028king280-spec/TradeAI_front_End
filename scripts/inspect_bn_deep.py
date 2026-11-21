import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'AIVOLVE-Inspector'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))

data = fetch('http://127.0.0.1:8000/api/options/BANKNIFTY/analysis')

print("=== BANK NIFTY LIVE ANALYSIS ===")
print("LTP:", data.get('marketState', {}).get('contributingFactors', [])[:3])
print("Final Action:", data.get('marketState', {}).get('final_action'))
print("Primary Reason:", data.get('marketState', {}).get('primaryReason'))
print("Reason for No Trade:", data.get('marketState', {}).get('reasonForNoTrade'))
print("Bullish Trigger:", data.get('marketState', {}).get('bullishActivationTrigger'))
print("Bearish Trigger:", data.get('marketState', {}).get('bearishActivationTrigger'))

print("\n--- RESEARCH ENGINE (60-pt hurdle) ---")
rs = data.get('researchSetup', {})
print("Score:", rs.get('score'), "/ 60")
print("Action:", rs.get('action'))
print("Qualified:", rs.get('qualified'))
print("Reasons:", rs.get('reasons'))
print("Stages:", rs.get('stages'))
features = rs.get('features', {})
print("1M Trigger:", features.get('ltf_trigger'))
print("5M Structure:", features.get('itf_structure'))
print("HTF Bias:", features.get('htf_bias'))

print("\n--- MAIN PRODUCTION ENGINE (12-stage pipeline) ---")
tos = data.get('todayOptionsSetups', {})
print("Has Qualified Setups:", tos.get('hasQualifiedSetups'))
print("Status Message:", tos.get('statusMessage'))
print("Disqualification Reasons:", tos.get('disqualificationReasons'))
print("Advice:", tos.get('advice'))
print("Setups count:", len(tos.get('setups', [])))

print("\n--- OPTION CHAIN SUMMARY ---")
ocs = data.get('optionChainSummary', {})
print("OCS keys/status:", ocs)
