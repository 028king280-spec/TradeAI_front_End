import json

from app.data import instrument_master


def test_bfo_contracts_resolve_with_expiry_and_lot_metadata(tmp_path, monkeypatch):
    records = [
        {"token": "123", "symbol": "SENSEX31DEC9980000CE", "name": "SENSEX",
         "expiry": "31DEC2099", "strike": "8000000", "lotsize": "20",
         "exch_seg": "BFO", "instrumenttype": "OPTIDX"},
        {"token": "123", "symbol": "NIFTY31DEC9924000CE", "name": "NIFTY",
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
    assert master.resolve_token("123", "BFO") == records[0]
    assert master.resolve_token("123", "NFO") == records[1]
    assert master.resolve_token("123", "BSE") is None
    assert master.resolve_option_contract("NIFTY 50", 24000, "CE") == records[1]
    assert master.resolve_option_contract("SENSEX", 80000, "PE") is None


def test_sensex_chain_uses_expiry_contract_lot_size(monkeypatch):
    from app.options import option_chain

    master = instrument_master.InstrumentMaster()
    master._expiries_by_underlying["SENSEX"] = ["31DEC2099"]
    contract = {"token": "123", "symbol": "SENSEX31DEC9980000CE", "lotsize": "20"}
    master._options_by_spec[("SENSEX", "31DEC2099", 80000.0, "CE")] = contract
    monkeypatch.setattr(option_chain, "get_instrument_master", lambda: master)
    assert option_chain.generate_index_option_chain("SENSEX", 80000, 0)["lotSize"] == 20
    contract["lotsize"] = "25"
    assert option_chain.generate_index_option_chain("SENSEX", 80000, 0)["lotSize"] == 25
    contract["lotsize"] = ""
    assert option_chain.generate_index_option_chain("SENSEX", 80000, 0)["lotSize"] is None
