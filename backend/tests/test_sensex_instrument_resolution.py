import json

from app.data import instrument_master


def test_bfo_contracts_resolve_with_expiry_and_lot_metadata(tmp_path, monkeypatch):
    records = [
        {"token": "123", "symbol": "SENSEX31DEC9980000CE", "name": "SENSEX",
         "expiry": "31DEC2099", "strike": "8000000", "lotsize": "20",
         "exch_seg": "BFO", "instrumenttype": "OPTIDX"},
        {"token": "456", "symbol": "NIFTY31DEC9924000CE", "name": "NIFTY",
         "expiry": "31DEC2099", "strike": "2400000", "lotsize": "65",
         "exch_seg": "NFO", "instrumenttype": "OPTIDX"},
    ]
    path = tmp_path / "master.json"
    path.write_text(json.dumps(records))
    monkeypatch.setattr(instrument_master, "SCRIP_MASTER_PATH", str(path))
    master = instrument_master.InstrumentMaster()
    master.load()
    assert master.get_expiries("SENSEX") == ["31DEC2099"]
    contract = master.resolve_option_contract("SENSEX", 80000, "CE")
    assert contract == records[0]
    assert master.resolve_option_contract("NIFTY 50", 24000, "CE") == records[1]
    assert master.resolve_option_contract("SENSEX", 80000, "PE") is None
