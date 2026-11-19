import urllib.request, json

# Check Research Paper Account
r_acc = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/performance/research-paper', timeout=5).read().decode())
print('Research Open Trades:', len(r_acc.get('openTrades', [])))
for t in r_acc.get('openTrades', []):
    print('  Research Trade:', t.get('contractSymbol'), t.get('entryPremium'), t.get('targetPremium'), t.get('status'))

# Check Setups for both
for sym in ['NIFTY%2050', 'BANK%20NIFTY']:
    s_data = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/options/' + sym + '/setups', timeout=15).read().decode()).get('todayOptionsSetups', {})
    has_q = s_data.get('hasQualifiedSetups')
    score = s_data.get('pipelineMetadata', {}).get('confluenceScore')
    status = s_data.get('statusMessage')
    print(sym + ' -> Qualified: ' + str(has_q) + ' | Score: ' + str(score) + ' | Status: ' + str(status))
    for s in s_data.get('setups', []):
        print('   PROD SETUP: ' + str(s.get('contractSymbol')) + ' ' + str(s.get('bias')) + ' Entry: ' + str(s.get('entryZone')) + ' SL: ' + str(s.get('stopLoss')) + ' T1: ' + str(s.get('target1')))

# Check NIFTY analysis research setup
n_an = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/options/NIFTY%2050/analysis', timeout=20).read().decode()).get('researchSetup', {})
print('NIFTY Research -> Qualified: ' + str(n_an.get('qualified')) + ' | Score: ' + str(n_an.get('score')) + ' | Action: ' + str(n_an.get('action')))
if n_an.get('setup'):
    print('   RESEARCH SETUP: ' + str(n_an.get('setup')))

# Check BANK NIFTY analysis research setup
b_an = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/options/BANK%20NIFTY/analysis', timeout=20).read().decode()).get('researchSetup', {})
print('BANK NIFTY Research -> Qualified: ' + str(b_an.get('qualified')) + ' | Score: ' + str(b_an.get('score')) + ' | Action: ' + str(b_an.get('action')))
if b_an.get('setup'):
    print('   RESEARCH SETUP: ' + str(b_an.get('setup')))
