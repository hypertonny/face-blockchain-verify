"""Local-chain tests for the registry — ephemeral eth-tester, no network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import polygon as pg  # noqa: E402
from web3 import Web3  # noqa: E402
from web3.providers.eth_tester import EthereumTesterProvider  # noqa: E402

ZERO = "00" * 32


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


def _anchor(web3, reg, acct, hexhash, url, prev):
    txh = reg.functions.anchor(bytes.fromhex(hexhash), url,
                               bytes.fromhex(prev)).transact({"from": acct})
    assert web3.eth.get_transaction_receipt(txh)["status"] == 1
    return txh


def test_anchor_roundtrip():
    web3, reg, acct = _local()
    _anchor(web3, reg, acct, "ab" * 32, "https://x.com/u/status/1", ZERO)
    sub, ts, got_url, prev, exists = reg.functions.get(
        bytes.fromhex("ab" * 32)).call()
    assert (sub, got_url, exists) == (acct, "https://x.com/u/status/1", True)
    assert ts > 0 and prev.hex() == ZERO


def test_hash_chain_links_tasks():
    web3, reg, acct = _local()
    _anchor(web3, reg, acct, "aa" * 32, "https://a.b/1", ZERO)
    assert reg.functions.latestBySubmitter(acct).call().hex() == "aa" * 32
    _anchor(web3, reg, acct, "bb" * 32, "https://a.b/2", "aa" * 32)
    got = reg.functions.get(bytes.fromhex("bb" * 32)).call()
    assert got[3].hex() == "aa" * 32  # task 2 points at task 1's hash
    assert reg.functions.latestBySubmitter(acct).call().hex() == "bb" * 32


def test_wrong_prev_reverts():
    web3, reg, acct = _local()
    _anchor(web3, reg, acct, "aa" * 32, "https://a.b/1", ZERO)
    try:
        _anchor(web3, reg, acct, "bb" * 32, "https://a.b/2", "cc" * 32)
        raise AssertionError("wrong prev hash should revert")
    except Exception as e:  # noqa: BLE001
        assert "AssertionError" not in str(type(e)), e
    # ...but the correct link still works afterwards
    _anchor(web3, reg, acct, "bb" * 32, "https://a.b/2", "aa" * 32)


def test_double_anchor_reverts():
    web3, reg, acct = _local()
    _anchor(web3, reg, acct, "cd" * 32, "https://a.b/", ZERO)
    try:
        _anchor(web3, reg, acct, "cd" * 32, "https://a.b/", "cd" * 32)
        raise AssertionError("second anchor should revert")
    except Exception as e:  # noqa: BLE001
        assert "AssertionError" not in str(type(e)), e


def test_unknown_hash_absent():
    _, reg, _ = _local()
    assert reg.functions.get(bytes.fromhex("ff" * 32)).call()[4] is False


def test_record_hash_fits_bytes32():
    import hashlib
    h = hashlib.sha256(b"canonical-record").hexdigest()
    assert len(bytes.fromhex(h)) == 32  # pipeline digests fit the type
