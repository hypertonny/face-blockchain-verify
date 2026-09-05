"""Solana devnet tamper-evident record — pure Python, no solders needed.

Writes the match record's SHA-256 digest into a Solana Memo instruction
(MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr) on devnet. Once confirmed,
the memo bytes are immutable and publicly verifiable at
https://explorer.solana.com/tx/<signature>?cluster=devnet.

Deps: requests, base58, pynacl (all in requirements.txt).
"""

import base64
import json as _json
import os
import struct
import time

import requests

RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")
MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
SYSTEM_PROGRAM = "11111111111111111111111111111111"
LAMPORTS_PER_SOL = 1_000_000_000


def _b58decode(s):
    import base58
    return base58.b58decode(s)


def _b58encode(b):
    import base58
    return base58.b58encode(b).decode()


def _shortvec_encode(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def load_keypair(path):
    """Load a Solana keypair file (JSON array of 64 secret-key bytes)."""
    import nacl.signing
    raw = _json.loads(open(path).read())
    seed = bytes(raw[:32])
    sk = nacl.signing.SigningKey(seed)
    pub = bytes(sk.verify_key)
    return sk, pub


def ensure_keypair(path):
    if os.path.exists(path):
        return load_keypair(path)
    import nacl.signing
    sk = nacl.signing.SigningKey.generate()
    with open(path, "w") as f:
        _json.dump(list(bytes(sk) + bytes(sk.verify_key)), f)
    os.chmod(path, 0o600)
    return sk, bytes(sk.verify_key)


def _rpc(method, params=(), timeout=30, retries=6):
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(
                RPC_URL, json={"jsonrpc": "2.0", "id": 1,
                               "method": method, "params": list(params)},
                timeout=timeout)
            if r.status_code in (429, 502, 503, 504):
                last = RuntimeError(f"http {r.status_code} on {method}")
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            body = r.json()
            if body.get("error"):
                err = body["error"]
                # Retriable faucet/node overload messages.
                if any(s in str(err.get("message", "")).lower()
                       for s in ("rate", "throttl", "busy", "overload",
                                 "blockhash not found", "not available")):
                    last = RuntimeError(f"solana rpc {method}: {err}")
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"solana rpc {method}: {err}")
            return body["result"]
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"solana rpc {method} failed after retries: {last}")


def balance(pub_b58):
    try:
        return _rpc("getBalance", [pub_b58])["value"]
    except Exception:  # noqa: BLE001
        return 0


def airdrop(pub_b58, lamports=LAMPORTS_PER_SOL, retries=5):
    for _ in range(retries):
        try:
            sig = _rpc("requestAirdrop", [pub_b58, lamports])
            for _ in range(30):
                time.sleep(2)
                st = _rpc("getSignatureStatuses", [[sig]])["value"][0]
                if st and st.get("confirmationStatus") in (
                        "confirmed", "finalized"):
                    return sig
            return sig
        except Exception as e:  # noqa: BLE001
            # Deterministic faucet exhaustion: retrying is pointless.
            if any(s in str(e).lower()
                   for s in ("limit today", "run dry", "faucet", "http 429")):
                raise
            time.sleep(5)
    raise RuntimeError("devnet airdrop failed (rate-limited?) — fund "
                       f"{pub_b58} manually from https://faucet.solana.com")


def _build_memo_tx(payer_pub, blockhash, memo_text):
    memo_prog = _b58decode(MEMO_PROGRAM)
    accounts = [payer_pub, memo_prog]
    msg = bytearray()
    # header: 1 required signature, 0 readonly-signed, 1 readonly-unsigned
    msg += bytes([1, 0, 1])
    msg += _shortvec_encode(len(accounts))
    for a in accounts:
        msg += a
    msg += _b58decode(blockhash)
    msg += _shortvec_encode(1)  # one instruction
    msg += bytes([1])           # program id index -> memo program
    msg += _shortvec_encode(0)  # no account indices
    data = memo_text.encode("utf-8")
    if len(data) > 566:
        raise ValueError("memo too long for one transaction")
    msg += _shortvec_encode(len(data)) + data
    return bytes(msg)


def send_memo(memo_text, keypair_path, timeout=90):
    """Sign + send a memo transaction. Returns dict with signature etc."""
    sk, pub = ensure_keypair(keypair_path)
    payer = _b58encode(pub)
    if balance(payer) < 5000:
        airdrop(payer)
    bh = _rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
    msg = _build_memo_tx(pub, bh, memo_text)
    sig_bytes = sk.sign(msg).signature
    tx = base64.b64encode(sig_bytes + msg).decode()
    res = _rpc("sendTransaction", [tx, {"encoding": "base64",
                                        "skipPreflight": False}],
               timeout=timeout)
    return {"signature": res, "payer": payer, "blockhash": bh,
            "memo": memo_text, "cluster": "devnet",
            "explorer": f"https://explorer.solana.com/tx/{res}?cluster=devnet"}


def wait_confirmed(signature, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = _rpc("getSignatureStatuses", [[signature]])["value"][0]
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            return st
        if st and st.get("err"):
            raise RuntimeError(f"transaction failed: {st['err']}")
        time.sleep(3)
    raise TimeoutError("confirmation timed out; check explorer URL")


def fetch_memo(signature):
    tx = _rpc("getTransaction", [signature,
                                 {"encoding": "json", "maxSupportedTransactionVersion": 0}])
    if not tx:
        raise RuntimeError("transaction not found (not yet indexed?)")
    # Memo appears in logMessages as 'Program log: <text>'.
    for line in tx["meta"].get("logMessages", []) or []:
        if line.startswith("Program log: "):
            return line[len("Program log: "):]
    # Fallback: scan raw account-data is overkill; logs are authoritative.
    raise RuntimeError("no memo log found in transaction")
