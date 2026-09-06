#!/usr/bin/env python3
"""Deploy FaceVerifyRegistry to Polygon Amoy. YOU sign locally.

The deployer's private key NEVER leaves this machine: it is read from the
POLYGON_PRIVATE_KEY env var at runtime, used once to sign, and never
printed, logged, or committed.

Steps:
  1. Fund your deployer address with free Amoy MATIC:
       https://faucet.polygon.technology/  (select Amoy)
  2. export POLYGON_PRIVATE_KEY="0x..."   # your key, local shell only
     export POLYGON_RPC_URL="https://polygon-amoy-bor-rpc.publicnode.com"  # optional
  3. python deploy_polygon.py
  4. Share the printed contract address -> set POLYGON_REGISTRY for anchoring:
       export POLYGON_REGISTRY="0x..."
       python pipeline.py --image photo.jpg --out out --chain polygon
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from polygon import CHAIN_ID, compiled, w3  # noqa: E402
from web3 import Web3  # noqa: E402


def main():
    key = os.environ.get("POLYGON_PRIVATE_KEY", "")
    if not key:
        sys.exit("POLYGON_PRIVATE_KEY not set. export it locally (see "
                 "header), fund the address at "
                 "https://faucet.polygon.technology/, then re-run.")
    web3 = w3()
    acct = web3.eth.account.from_key(key)
    print(f"network   : Polygon Amoy (chain {CHAIN_ID})")
    print(f"deployer  : {acct.address}")
    bal = web3.eth.get_balance(acct.address)
    print(f"balance   : {web3.from_wei(bal, 'ether')} MATIC")
    if bal == 0:
        sys.exit("balance is zero — fund the deployer at "
                 "https://faucet.polygon.technology/ first.")
    # Never log the key — show only the derived address (already printed).
    del key

    comp = compiled()
    factory = web3.eth.contract(abi=comp["abi"], bytecode=comp["bytecode"])
    latest = web3.eth.get_block("latest")
    base = latest.get("baseFeePerGas") or web3.eth.gas_price
    tx = factory.constructor().build_transaction({
        "from": acct.address, "chainId": CHAIN_ID,
        "nonce": web3.eth.get_transaction_count(acct.address),
        "maxFeePerGas": base * 2 + web3.eth.max_priority_fee,
        "maxPriorityFeePerGas": web3.eth.max_priority_fee,
    })
    tx["gas"] = web3.eth.estimate_gas(tx)
    print(f"est. gas  : {tx['gas']} "
          f"(~{web3.from_wei(tx['gas'] * tx['maxFeePerGas'], 'ether')} MATIC max)")
    signed = acct.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction).hex()
    print(f"deploy tx : {tx_hash}")
    print("waiting for confirmation ...")
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
    addr = receipt.get("contractAddress")
    if receipt.get("status") != 1 or not addr:
        sys.exit(f"deploy failed: {receipt}")
    print(f"CONTRACT  : {addr}")
    print(f"EXPLORER  : https://amoy.polygonscan.com/address/{addr}")
    os.makedirs("out", exist_ok=True)
    with open("out/polygon_deploy.json", "w") as f:
        json.dump({"network": "polygon-amoy", "chain_id": CHAIN_ID,
                   "contract": addr, "deployer": acct.address,
                   "deploy_tx": tx_hash,
                   "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime())}, f, indent=2)
    print("saved     : out/polygon_deploy.json (git-ignored)")
    print("next      : export POLYGON_REGISTRY="
          f"{addr} && python pipeline.py --image <photo> --out out "
          "--chain polygon")


if __name__ == "__main__":
    main()
