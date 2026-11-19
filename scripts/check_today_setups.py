import urllib.request, urllib.parse, json

req = urllib.request.urlopen('http://127.0.0.1:8000/api/options/overview', timeout=10)
overview = json.loads(req.read().decode())
print('=== Live Indices Overview ===')
for idx in overview.get('indices', []):
    print(str(idx.get('symbol')) + ': ' + str(idx.get('currentValue')) + ' (' + str(idx.get('change')) + ', ' + str(idx.get('changePercent')) + '%)')

for sym in ['NIFTY 50', 'BANK NIFTY']:
    url = 'http://127.0.0.1:8000/api/options/' + urllib.parse.quote(sym) + '/setups'
    try:
        r = urllib.request.urlopen(url, timeout=20)
        data = json.loads(r.read().decode())
        setups_data = data.get('todayOptionsSetups', {})
        research_data = data.get('researchSetup', {})
        print('\n=== ' + sym + ' Production Setup ===')
        print('Has Qualified:', setups_data.get('hasQualifiedSetups'))
        print('Status Message:', setups_data.get('statusMessage'))
        print('Confluence Score:', setups_data.get('pipelineMetadata', {}).get('confluenceScore'))
        print('Market Regime:', setups_data.get('pipelineMetadata', {}).get('marketRegime'))
        print('Disqualifications:', setups_data.get('disqualificationReasons'))
        for s in setups_data.get('setups', []):
            print('  -> Production Setup:', s.get('contractSymbol'), s.get('bias'), 'Entry:', s.get('entryZone'), 'SL:', s.get('stopLoss'), 'T1:', s.get('target1'))
        
        print('=== ' + sym + ' Research Engine (60-pt) ===')
        print('Research Qualified:', research_data.get('qualified'))
        print('Research Score:', research_data.get('confluenceScore'))
        print('Research Reasons:', research_data.get('reasons'))
        cand = research_data.get('candidate')
        if cand:
            print('  -> Candidate:', cand.get('contractSymbol'), cand.get('bias'), 'Ask:', cand.get('entryAsk'), 'SL:', cand.get('stopLoss'), 'Target (+30%):', cand.get('targetPremium'), 'RR:', cand.get('grossRewardRisk'))
    except Exception as e:
        print('Error fetching ' + sym + ':', e)
