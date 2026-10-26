import urllib.request
import json
import sys

base_url = 'http://localhost:8000/api'

get_endpoints = [
    ('/health', 'Health Check'),
    ('/market/overview', 'Market Overview'),
    ('/stocks/search?q=RELIANCE', 'Search RELIANCE'),
    ('/analysis/RELIANCE', 'Stock Analysis RELIANCE'),
    ('/signals/calls', 'Qualified CALL Setups'),
    ('/signals/puts', 'Qualified PUT Setups'),
    ('/ml/models', 'ML Models List'),
    ('/knowledge/documents', 'RAG Knowledge Documents')
]

print('=================================================================')
print('=== 1. TESTING LIVE BACKEND FASTAPI ENDPOINTS (PORT 8000)     ===')
print('=================================================================')
all_passed = True

for ep, name in get_endpoints:
    url = f'{base_url}{ep}'
    try:
        req = urllib.request.urlopen(url, timeout=5)
        status = req.getcode()
        body = json.loads(req.read().decode('utf-8'))
        data = body.get('data') if isinstance(body, dict) and 'data' in body else body
        print(f'[PASS] {name:<26} ({ep}) -> HTTP {status}')
        if ep == '/health':
            print(f'       Status: {data.get("status")}, Provider: {data.get("provider")}, Market Status: {data.get("marketStatus")}')
        elif '/analysis' in ep:
            score_obj = data.get("analysisScore", {})
            prob_obj = data.get("probabilities", {})
            hi_obj = data.get("expectedHigh", {})
            lo_obj = data.get("expectedLow", {})
            print(f'       LTP: Rs. {data.get("currentPrice")}, Score: {score_obj.get("totalScore")}/100 ({score_obj.get("status")}), Trend: {data.get("trend")}, Bias: {data.get("currentBias")}')
            print(f'       Probabilities -> Upside: {prob_obj.get("upside")}%, Downside: {prob_obj.get("downside")}%')
            print(f'       Expected Intraday Range -> High: Rs. {hi_obj.get("min")}-{hi_obj.get("max")} | Low: Rs. {lo_obj.get("min")}-{lo_obj.get("max")}')
        elif ep == '/signals/calls':
            print(f'       Qualified CALL Setups Count: {len(data) if isinstance(data, list) else 0}')
        elif ep == '/signals/puts':
            print(f'       Qualified PUT Setups Count: {len(data) if isinstance(data, list) else 0}')
        elif ep == '/market/overview':
            indices = data if isinstance(data, list) else []
            nifty = next((idx for idx in indices if 'NIFTY 50' in idx.get('name', '') or 'NIFTY 50' in idx.get('symbol', '')), {})
            print(f'       NIFTY 50: Rs. {nifty.get("currentValue")} ({nifty.get("changePercent")}%), Trend: {nifty.get("trend")}, Day High: Rs. {nifty.get("dayHigh")}')
    except Exception as e:
        print(f'[FAIL] {name:<26} ({ep}) -> Error: {e}')
        all_passed = False

# Test POST Knowledge search
try:
    search_url = f'{base_url}/knowledge/search'
    post_data = json.dumps({"query": "breakout camarilla momentum", "topK": 3}).encode('utf-8')
    req = urllib.request.Request(search_url, data=post_data, headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req, timeout=5)
    body = json.loads(resp.read().decode('utf-8'))
    print(f'[PASS] {"RAG Knowledge Search":<26} (/knowledge/search) -> HTTP {resp.getcode()}')
    print(f'       Search query matched {len(body.get("data", []))} vector chunks')
except Exception as e:
    print(f'[FAIL] RAG Knowledge Search (/knowledge/search) -> Error: {e}')
    all_passed = False

print('\n=================================================================')
print('=== 2. TESTING FRONTEND NEXT.JS APPLICATION (PORT 3000)       ===')
print('=================================================================')
frontend_pages = [
    ('/', 'Homepage / Dashboard'),
    ('/stocks/RELIANCE', 'Stock Detail (RELIANCE)'),
    ('/search', 'Stock Search & Scanner'),
    ('/ai-insights', 'AI Insights & RAG Hub')
]

for path, page_name in frontend_pages:
    fe_url = f'http://localhost:3000{path}'
    try:
        req_fe = urllib.request.urlopen(fe_url, timeout=6)
        html = req_fe.read().decode('utf-8')
        has_title = 'AIVOLVE' in html or 'Trading' in html or 'RELIANCE' in html or 'Search' in html
        print(f'[PASS] {page_name:<26} ({path}) -> HTTP {req_fe.getcode()} (Content verified: {has_title})')
    except Exception as e:
        print(f'[FAIL] {page_name:<26} ({path}) -> Error: {e}')
        all_passed = False

print('\n=================================================================')
if all_passed:
    print('>>> ALL SYSTEM INTEGRATION TESTS PASSED 100% SUCCESFULLY! <<<')
else:
    print('>>> SOME CHECKS FAILED - INSPECT LOGS ABOVE <<<')
print('=================================================================')

if not all_passed:
    sys.exit(1)
