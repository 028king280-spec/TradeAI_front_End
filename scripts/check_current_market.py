import urllib.request
import json

req = urllib.request.urlopen('http://127.0.0.1:8000/api/options/overview', timeout=10)
overview = json.loads(req.read().decode())
for idx in overview.get('indices', []):
    print(str(idx.get('symbol')) + ": " + str(idx.get('currentValue')) + " (" + str(idx.get('change')) + ", " + str(idx.get('changePercent')) + "%)")

for sym in ['NIFTY 50', 'BANK NIFTY']:
    url = 'http://127.0.0.1:8000/api/options/' + urllib.parse.quote(sym) + '/setups'
    req_s = urllib.request.urlopen(url, timeout=10)
    s_data = json.loads(req_s.read().decode()).get('todayOptionsSetups', {})
    print('=== ' + sym + ' Setups ===')
    print('Has Qualified:', s_data.get('hasQualifiedSetups'))
    print('Status Message:', s_data.get('statusMessage'))
    print('Confluence Score:', s_data.get('pipelineMetadata', {}).get('confluenceScore'))
    print('Regime:', s_data.get('pipelineMetadata', {}).get('marketRegime'))
    print('Disqualifications:', s_data.get('disqualificationReasons'))
