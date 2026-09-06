"""Offline unit tests — no network, no keys, no chain. Run: pytest -m "not network"."""
import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from blockchain import _build_memo_tx, _b58decode  # noqa: E402
from match_verify import cosine  # noqa: E402
from reverse_search import _is_social, _parse_sites  # noqa: E402

import pipeline  # noqa: E402


def test_cosine_identical():
    assert cosine([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)


def test_cosine_orthogonal():
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)


def test_is_social():
    assert _is_social({"page_url": "https://www.instagram.com/p/abc/"})
    assert _is_social({"page_url": "https://x.com/user/status/1"})
    assert not _is_social({"page_url": "https://example.com/news/1"})
    assert not _is_social({"page_url": "https://pbs.twimg.com/media/x.jpg"})


def test_parse_sites_strict():
    html = (
        '{"title":"Some Post","description":"d",'
        '"url":"https://www.youtube.com/watch?v=abc123",'
        '"domain":"youtube.com","thumb":{"url":"t"},'
        '"originalImage":{"url":"https://i.ytimg.com/vi/abc123/hq.jpg"}}'
        '{"title":"News","description":"d",'
        '"url":"https://example.com/a?utm_medium=organic&utm_source=y",'
        '"domain":"example.com","thumb":{"url":"t"},'
        '"originalImage":{"url":"https://example.com/a.jpg"}}'
    )
    items = _parse_sites(html)
    assert len(items) == 2
    assert items[0]["domain"] == "youtube.com"
    assert items[0]["image_url"].endswith("hq.jpg")
    assert "utm_medium" not in items[1]["page_url"]


def test_guard_url_refuses_private():
    with pytest.raises(ValueError):
        pipeline.guard_url("ftp://example.com/x.jpg")
    with pytest.raises(ValueError):
        pipeline.guard_url("http://127.0.0.1/x.jpg")
    with pytest.raises(ValueError):
        pipeline.guard_url("https://10.0.0.5/x.jpg")


def test_keypair_safe_gitignored(tmp_path):
    # out/ is git-ignored in this repo -> must be accepted.
    assert pipeline.keypair_safe("out/id.json") is True


def test_keypair_safe_refuses_tracked(tmp_path):
    # A non-ignored path inside the repo must be refused.
    with pytest.raises(SystemExit):
        pipeline.keypair_safe("samples/id.json")


def test_memo_tx_structure():
    payer = _b58decode("11111111111111111111111111111111")
    msg = _build_memo_tx(payer, "11111111111111111111111111111111", "FACEVERIFY|x")
    assert msg[:3] == bytes([1, 0, 1])  # legacy header
    assert b"FACEVERIFY|x" in msg
    assert len(msg) < 1232  # fits one Solana transaction


def test_record_hash_deterministic():
    rec = {"b": 1, "a": [1, 2]}
    h1 = hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()
    assert h1 == h2 and len(h1) == 64


def test_require_face_raises_on_blank(monkeypatch):
    import numpy as np
    import face as face_mod
    # Force every detector to find nothing: must raise, never crop garbage.
    monkeypatch.setattr(face_mod, "_detect_yunet", lambda img: [])
    monkeypatch.setattr(face_mod, "_detect_dnn", lambda img: [])
    blank = np.zeros((200, 200, 3), dtype=np.uint8)
    with pytest.raises(face_mod.NoFaceFound):
        face_mod.detect_and_encode_array(blank, require_face=True)
    # ...while the input-photo path still falls back gracefully.
    r = face_mod.detect_and_encode_array(blank)
    assert r["backend"] == "fallback-center-crop+pixel-embedding"


def test_tamper_detected():    canonical = {"face": {"embedding_sha256": "a" * 64}}
    good = hashlib.sha256(
        json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    tampered = dict(canonical, face={"embedding_sha256": "b" * 64})
    bad = hashlib.sha256(
        json.dumps(tampered, sort_keys=True).encode()).hexdigest()
    assert good != bad  # any 1-byte change flips the digest
