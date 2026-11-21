import urllib.request
import json
import time
from datetime import datetime

print(f"[{datetime.now().strftime('%H:%M:%S')}] AIVOLVE Continuous Live Scanner & Auto-Trader Daemon Active.")

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'AIVOLVE-Continuous'})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}

def post(url, data_dict, auth_token='aivolve-internal-operator'):
    try:
        data_bytes = json.dumps(data_dict).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'AIVOLVE-Continuous',
                'X-AIVOLVE-AUTH-TOKEN': auth_token
            }
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}

executed_today = set()

while True:
    now_str = datetime.now().strftime('%H:%M:%S')
    try:
        # 1. Overview
        ov = fetch('http://127.0.0.1:8000/api/options/overview')
        nifty_ltp = 0
        bn_ltp = 0
        if 'indices' in ov:
            for idx in ov['indices']:
                sym = idx.get('symbol', '')
                val = idx.get('currentValue', 0)
                if 'NIFTY 50' in sym or sym == 'NIFTY':
                    nifty_ltp = val
                elif 'BANK' in sym:
                    bn_ltp = val

        # 2. Paper Portfolio status
        port = fetch('http://127.0.0.1:8000/api/paper-trading/portfolio')
        open_pos = port.get('openPositions', []) if port.get('status') == 'SUCCESS' else []
        total_unrealized = sum(p.get('unrealizedGrossPnl', 0) for p in open_pos)
        
        pos_str = f"{len(open_pos)} Active (PnL: +Rs {total_unrealized:,.1f})"
        print(f"[{now_str}] NIFTY: {nifty_ltp} | BANKNIFTY: {bn_ltp} | {pos_str}", flush=True)

        # 3. Scan BANK NIFTY & NIFTY 50 for Fresh Qualified Setups
        for sym_key, display_sym in [('BANKNIFTY', 'BANK NIFTY'), ('NIFTY50', 'NIFTY 50')]:
            analysis = fetch(f'http://127.0.0.1:8000/api/options/{sym_key}/analysis')
            rs = analysis.get('researchSetup', {})
            tos = analysis.get('todayOptionsSetups', {})
            
            # Check if qualified
            is_qual = rs.get('qualified') or tos.get('hasQualifiedSetups')
            setup_data = rs.get('setup') or (tos.get('setups', [None])[0] if tos.get('setups') else None)
            
            if is_qual and setup_data:
                contract = setup_data.get('contract_symbol') or setup_data.get('contractSymbol')
                if contract and contract not in executed_today:
                    print(f"[{now_str}] >>> FRESH QUALIFIED SETUP DETECTED FOR {display_sym}: {contract}!", flush=True)
                    order_payload = {
                        "symbol": display_sym,
                        "contract_symbol": contract,
                        "option_type": setup_data.get('option_type', 'CE'),
                        "strike": float(setup_data.get('strike', 0)),
                        "entry_price": float(setup_data.get('entry_price', 0)),
                        "target_price": float(setup_data.get('target_1', 0)),
                        "stop_loss": float(setup_data.get('stop_loss', 0)),
                        "lots": 1,
                        "action": "BUY",
                        "notes": f"Auto-triggered from live qualified setup ({display_sym})"
                    }
                    res = post('http://127.0.0.1:8000/api/paper-trading/open', order_payload)
                    print(f"[{now_str}] Auto-Execution Order Result: {res}", flush=True)
                    executed_today.add(contract)

    except Exception as e:
        print(f"[{now_str}] Error in monitor loop: {e}", flush=True)

    time.sleep(25)
