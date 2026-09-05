"""Network integration tests — need internet (+ keys for providers).

Run: pytest -m network
SerpApi/Yandex quota and faucet limits apply; keep these few and frugal.
"""
import base64
import os
import sys

import pytest

pytestmark = pytest.mark.network

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_solana_build_sign_simulate(tmp_path):
    """Our hand-rolled memo tx must behave exactly like solders' output.

    Builds the same memo with both serializers and simulates each on
    devnet: whatever the node returns (success with Memo logs, or an
    environmental BlockhashNotFound from Helius routing), both must agree.
    Any structural bug in our bytes would surface as a deserialization
    error that the solders reference does not have.
    """
    solders = pytest.importorskip("solders")
    import nacl.signing
    from blockchain import _b58decode, _rpc, sign_memo_tx

    bh_str = _rpc("getLatestBlockhash", [{"commitment": "confirmed"}])[
        "value"]["blockhash"]

    sk = nacl.signing.SigningKey.generate()
    pub = bytes(sk.verify_key)
    ours = base64.b64encode(sign_memo_tx(sk, pub, bh_str,
                                         "FACEVERIFY|selftest")).decode()

    ref_kp = solders.keypair.Keypair()
    ref_ix = solders.instruction.Instruction(
        solders.pubkey.Pubkey.from_string(
            "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"),
        b"FACEVERIFY|selftest", [])
    ref_tx = solders.transaction.Transaction(
        [ref_kp],
        solders.message.Message([ref_ix], ref_kp.pubkey()),
        solders.hash.Hash(_b58decode(bh_str)))
    ref = base64.b64encode(bytes(ref_tx)).decode()

    results = []
    for tx in (ours, ref):
        try:
            r = _rpc("simulateTransaction",
                     [tx, {"encoding": "base64", "sigVerify": True}],
                     retries=1)
            v = r.get("value") or {}
            results.append((v.get("err"), bool(v.get("logs"))))
        except Exception as e:  # noqa: BLE001
            results.append((f"RPC:{e}", False))
    assert results[0] == results[1], f"ours={results[0]} ref={results[1]}"
    err, has_logs = results[0]
    if err is None:
        assert has_logs  # executed: Memo program ran


def test_yandex_live_search():
    """Yandex CBIR returns live (non-hardcoded) matches for the sample."""
    from reverse_search import yandex_reverse_search
    url = ("https://upload.wikimedia.org/wikipedia/commons/3/34/"
           "Elon_Musk_Royal_Society_%28crop2%29.jpg")
    matches = yandex_reverse_search(url)
    assert len(matches) > 10
    assert any("youtube.com" in m["domain"] or "pinterest.com" in m["domain"]
               for m in matches)


def test_stellar_testnet_horizon():
    """Horizon testnet is reachable and serves transactions."""
    import requests
    r = requests.get("https://horizon-testnet.stellar.org/", timeout=30)
    assert r.status_code == 200
