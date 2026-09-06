#!/usr/bin/env python3
"""fbv deploy — deploy FaceVerifyRegistry to Polygon Amoy. YOU sign locally.

The deployer's private key never leaves this machine: it is read from
POLYGON_PRIVATE_KEY at runtime, used to sign, and never printed, logged, or
committed.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui  # noqa: E402
from cliutil import parser as make_parser  # noqa: E402
from polygon import CHAIN_ID, compiled, w3  # noqa: E402


def main(argv=None, prog=None):
    ap = make_parser(
        prog or "deploy_polygon",
        "Deploy FaceVerifyRegistry to Polygon Amoy. You sign locally with "
        "POLYGON_PRIVATE_KEY; the key is never printed or committed.",
        "  export POLYGON_PRIVATE_KEY=0x...   # local shell only\n"
        "  deploy_polygon\n"
        "  export POLYGON_REGISTRY=0x...      # printed contract address")
    ap.add_argument("--rpc-url", default=None,
                    help="Polygon Amoy RPC (default: POLYGON_RPC_URL env or "
                         "public endpoint)")
    args = ap.parse_args(argv)

    key = os.environ.get("POLYGON_PRIVATE_KEY", "")
    if not key:
        ui.die("POLYGON_PRIVATE_KEY not set",
               hint="fund your address at https://faucet.polygon.technology/ "
                    "(Amoy), then export the key locally and retry")
    web3 = w3(args.rpc_url)
    acct = web3.eth.account.from_key(key)
    ui.step(1, 2, "Check Polygon Amoy deployer")
    ui.info(f"address {acct.address}")
    bal = web3.eth.get_balance(acct.address)
    ui.info(f"balance {web3.from_wei(bal, 'ether')} MATIC")
    if bal == 0:
        ui.die("deployer balance is zero",
               hint="fund this address at https://faucet.polygon.technology/ "
                    "(select Amoy) and retry")
    del key  # never retain / print it after deriving the local signer

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
    ui.step(2, 2, "Deploy FaceVerifyRegistry")
    ui.info(f"estimate {tx['gas']} gas · max "
            f"{web3.from_wei(tx['gas'] * tx['maxFeePerGas'], 'ether')} MATIC")
    signed = acct.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction).hex()
    ui.info(f"tx {tx_hash}")
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
    addr = receipt.get("contractAddress")
    if receipt.get("status") != 1 or not addr:
        ui.die("contract deployment reverted", hint=f"inspect tx {tx_hash}")
    os.makedirs("out", exist_ok=True)
    with open("out/polygon_deploy.json", "w") as f:
        json.dump({"network": "polygon-amoy", "chain_id": CHAIN_ID,
                   "contract": addr, "deployer": acct.address,
                   "deploy_tx": tx_hash,
                   "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime())}, f, indent=2)
    ui.ok("FaceVerifyRegistry deployed")
    ui.info(f"contract {addr}")
    ui.info(f"explorer https://amoy.polygonscan.com/address/{addr}")
    ui.info(f"next     export POLYGON_REGISTRY={addr}")


if __name__ == "__main__":
    main()
