"""Stellar testnet fallback record — open faucet, no API key needed.

Stores the record SHA-256 (plus match URL) in ManageData operations of a
self-payment on Stellar testnet. Immutable once confirmed; verifiable at
https://stellar.expert/explorer/testnet/tx/<hash> or via Horizon:
https://horizon-testnet.stellar.org/transactions/<hash>.

Used automatically when the Solana devnet faucet is rate-limited;
selectable explicitly with --chain stellar.
"""

import json as _json
import os
import time

import requests
from stellar_sdk import (Keypair, ManageData, Network, Server,
                         TransactionBuilder)

HORIZON = os.environ.get("STELLAR_HORIZON_URL",
                         "https://horizon-testnet.stellar.org")
FRIENDBOT = "https://friendbot.stellar.org"
NETWORK = Network.TESTNET_NETWORK_PASSPHRASE


def ensure_keypair(path):
    if os.path.exists(path):
        secret = _json.load(open(path))["secret"]
        kp = Keypair.from_secret(secret)
        return kp
    kp = Keypair.random()
    with open(path, "w") as f:
        _json.dump({"secret": kp.secret, "public": kp.public_key}, f)
    os.chmod(path, 0o600)
    return kp


def _funded(server, address):
    try:
        server.accounts().account_id(address).call()
        return True
    except Exception:  # noqa: BLE001
        return False


def fund(kp, timeout=120):
    server = Server(HORIZON)
    if _funded(server, kp.public_key):
        return True
    r = requests.get(FRIENDBOT, params={"addr": kp.public_key},
                     timeout=timeout)
    r.raise_for_status()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _funded(server, kp.public_key):
            return True
        time.sleep(4)
    raise RuntimeError("friendbot funding did not land in time")


def send_record(record_sha256, match_url, keypair_path, timeout=120):
    """Write record digest + match URL. Returns signature/explorer dict."""
    kp = ensure_keypair(keypair_path)
    server = Server(HORIZON)
    fund(kp, timeout=timeout)
    account = server.load_account(kp.public_key)
    tx = (TransactionBuilder(account, NETWORK, base_fee=100)
          .append_manage_data_op("fbv-record", record_sha256)
          .append_manage_data_op("fbv-match", match_url[:64])
          .set_timeout(60).build())
    tx.sign(kp)
    resp = server.submit_transaction(tx, skip_memo_required_check=True)
    h = resp["hash"]
    return {"signature": h, "payer": kp.public_key,
            "network": "stellar-testnet",
            "explorer": f"https://stellar.expert/explorer/testnet/tx/{h}",
            "horizon": f"https://horizon-testnet.stellar.org/transactions/{h}"}


def fetch_record(tx_hash):
    server = Server(HORIZON)
    tx = server.transactions().transaction(tx_hash).call()
    ops = server.operations().for_transaction(tx_hash).call()["_embedded"]["records"]
    data = {}
    for op in ops:
        if op.get("type") == "manage_data":
            data[op["name"]] = op.get("value")
    return {"ledger": tx.get("ledger"), "successful": tx.get("successful"),
            "manage_data": data}
