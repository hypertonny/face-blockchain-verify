"""Polygon Amoy record — FaceVerifyRegistry.anchor(recordHash, matchUrl).

On-chain stores ONLY the 32-byte record SHA-256 + the public post URL
(≤256 chars): no photo, no embedding. First write wins; history immutable.
Verify at https://amoy.polygonscan.com/tx/<hash>.

Config (env only, never committed):
  POLYGON_RPC_URL    default https://polygon-amoy-bor-rpc.publicnode.com
  POLYGON_REGISTRY   deployed FaceVerifyRegistry address (0x...)
  POLYGON_PRIVATE_KEY  deployer/anchor key — required only for writing.
                       Reads (fetch_record) need no key.
"""

import json as _json
import os

from web3 import Web3

CHAIN_ID = 80002
DEFAULT_RPC = "https://polygon-amoy-bor-rpc.publicnode.com"
EXPLORER_TX = "https://amoy.polygonscan.com/tx/{}"


def compiled():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "contracts", "compiled.json")) as f:
        return _json.load(f)


def w3(rpc_url=None):
    url = rpc_url or os.environ.get("POLYGON_RPC_URL", DEFAULT_RPC)
    return Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 60}))


def registry(web3, address=None):
    addr = address or os.environ.get("POLYGON_REGISTRY", "")
    if not addr:
        raise RuntimeError("POLYGON_REGISTRY not set (deploy first: "
                           "python deploy_polygon.py)")
    return web3.eth.contract(address=Web3.to_checksum_address(addr),
                             abi=compiled()["abi"])


def _fees(web3):
    latest = web3.eth.get_block("latest")
    base = latest.get("baseFeePerGas") or web3.eth.gas_price
    priority = web3.eth.max_priority_fee
    return {"maxFeePerGas": base * 2 + priority,
            "maxPriorityFeePerGas": priority}


def build_anchor_tx(web3, record_sha256, match_url, sender):
    """Unsigned anchor() call. Safe to inspect before signing."""
    reg = registry(web3)
    h = bytes.fromhex(record_sha256)
    if len(h) != 32:
        raise ValueError("record_sha256 must be 32 bytes hex")
    fn = reg.functions.anchor(h, match_url[:256])
    tx = fn.build_transaction({
        "from": Web3.to_checksum_address(sender),
        "chainId": CHAIN_ID,
        "nonce": web3.eth.get_transaction_count(
            Web3.to_checksum_address(sender)),
        **_fees(web3),
    })
    tx["gas"] = web3.eth.estimate_gas(tx)
    return tx


def send_record(record_sha256, match_url, key=None, rpc_url=None,
                timeout=300):
    """Sign (local env key) + broadcast anchor. Returns explorer dict."""
    import time
    key = key or os.environ.get("POLYGON_PRIVATE_KEY", "")
    if not key:
        raise RuntimeError("POLYGON_PRIVATE_KEY not set in env "
                           "(reads need no key; writes do)")
    web3 = w3(rpc_url)
    acct = web3.eth.account.from_key(key)
    tx = build_anchor_tx(web3, record_sha256, match_url, acct.address)
    signed = acct.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction).hex()
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
    if receipt.get("status") != 1:
        raise RuntimeError(f"anchor reverted in tx {tx_hash}")
    return {"signature": tx_hash, "payer": acct.address,
            "contract": registry(web3).address,
            "network": "polygon-amoy", "chain_id": CHAIN_ID,
            "explorer": EXPLORER_TX.format(tx_hash)}


def fetch_record(tx_hash, rpc_url=None):
    """Read back the Anchored event + stored fields for a tx hash."""
    web3 = w3(rpc_url)
    receipt = web3.eth.get_transaction_receipt(tx_hash)
    if not receipt:
        raise RuntimeError("transaction not found (not yet indexed?)")
    reg = registry(web3)
    events = reg.events.Anchored().process_receipt(receipt)
    if not events:
        raise RuntimeError("no Anchored event in transaction")
    ev = events[0]["args"]
    stored = reg.functions.get(ev["recordHash"]).call()
    return {"status": receipt.get("status"), "contract": reg.address,
            "record_hash": ev["recordHash"].hex(),
            "submitter": ev["submitter"],
            "match_url": ev["matchUrl"] or stored[2],
            "timestamp": ev["timestamp"],
            "stored": {"submitter": stored[0], "timestamp": stored[1],
                       "exists": stored[3]}}
