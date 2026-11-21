import urllib.request
import json

url = 'http://127.0.0.1:8000/api/paper-trading/close'
payload = {
    "positionId": "PT-89B18A85",
    "exitPrice": 120.0,
    "exitReason": "Stale position cleanup"
}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode('utf-8'),
    headers={
        'Content-Type': 'application/json',
        'X-AIVOLVE-AUTH-TOKEN': 'aivolve-internal-operator'
    }
)
try:
    with urllib.request.urlopen(req) as resp:
        print("Closed PT-89B18A85:", json.loads(resp.read().decode('utf-8')))
except Exception as e:
    print("Error:", e)
