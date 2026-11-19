import json
from unittest.mock import patch
import pytest
from app.options.paper_trading.paper_engine import PaperTradingEngine

def entry():
    return dict(instrument='NIFTY 50',contract_symbol='AUDIT',bias='CE',strike=24000,expiry='TEST',entry_premium=105,lots=2,lot_size=25,stop_loss=90,target_1=135,target_2=165,target_3=190,market_features={'isReplay':True})

@pytest.mark.parametrize('key,value',[('lots',-2),('lots',0),('lots',1.5),('lots',True),('lot_size',-25),('entry_premium',float('nan')),('entry_premium',0),('strike',float('inf'))])
def test_invalid_entry_preserves_cash(tmp_path,key,value):
    e=PaperTradingEngine(storage_path=str(tmp_path/'state.json'));p=entry();p[key]=value
    assert not e.open_position(**p)['success']
    assert e.state['balance']==100000 and not e.state['openPositions']

def test_failed_open_rolls_back_visible_and_durable_state(tmp_path):
    e=PaperTradingEngine(storage_path=str(tmp_path/'state.json'));e.reset_account()
    before=json.loads(json.dumps(e.state))
    with patch('app.options.paper_trading.paper_engine.os.replace',side_effect=OSError('disk failure')):
        with pytest.raises(OSError):e.open_position(**entry())
    assert e.state==before
    assert json.loads((tmp_path/'state.json').read_text())==before
    assert e._state_version==before['stateVersion']

def test_failed_close_retains_open_position(tmp_path):
    e=PaperTradingEngine(storage_path=str(tmp_path/'state.json'));pid=e.open_position(**entry())['position']['id']
    before=json.loads(json.dumps(e.state))
    with patch('app.options.paper_trading.paper_engine.os.replace',side_effect=OSError('disk failure')):
        with pytest.raises(OSError):e.close_position(pid,150)
    assert e.state==before
    assert json.loads((tmp_path/'state.json').read_text())==before
