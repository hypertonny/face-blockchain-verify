"""Local-chain tests for the registry — ephemeral eth-tester, no network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import polygon as pg  # noqa: E402
from web3 import Web3  # noqa: E402
from web3.providers.eth_tester import EthereumTesterProvider  # noqa: E402


def _local():
    tester = __import__("eth_tester", fromlist=["EthereumTester"]).EthereumTester()
    web3 = Web3(EthereumTesterProvider(tester))
    web3.eth.set_gas_price_strategy(lambda w, t: w.to_wei(1, "gwei"))
    comp = pg.compiled()
    factory = web3.eth.contract(abi=comp["abi"], bytecode=comp["bytecode"])
    acct = tester.get_accounts()[0]
    txh = factory.constructor().transact({"from": acct})
    addr = web3.eth.get_transaction_receipt(txh)["contractAddress"]
    return web3, web3.eth.contract(address=addr, abi=comp["abi"]), acct


def test_anchor_roundtrip():
    web3, reg, acct = _local()
    h = bytes.fromhex("ab" * 32)
    url = "https://x.com/u/status/1"
    txh = reg.functions.anchor(h, url).transact({"from": acct})
    assert web3.eth.get_transaction_receipt(txh)["status"] == 1
    sub, ts, got_url, exists = reg.functions.get(h).call()
    assert (sub, got_url, exists) == (acct, url, True) and ts > 0


def test_double_anchor_reverts():
    web3, reg, acct = _local()
    h = bytes.fromhex("cd" * 32)
    reg.functions.anchor(h, "https://a.b/").transact({"from": acct})
    try:
        reg.functions.anchor(h, "https://a.b/").transact({"from": acct})
        raise AssertionError("second anchor should revert")
    except Exception as e:  # noqa: BLE001
        assert "AssertionError" not in str(type(e)), e


def test_unknown_hash_absent():
    _, reg, _ = _local()
    assert reg.functions.get(bytes.fromhex("ff" * 32)).call()[3] is False


def test_record_hash_fits_bytes32():
    import hashlib
    h = hashlib.sha256(b"canonical-record").hexdigest()
    assert len(bytes.fromhex(h)) == 32  # pipeline digests fit the type
