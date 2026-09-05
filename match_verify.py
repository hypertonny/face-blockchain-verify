"""Confirm a reverse-search hit really shows the same face.

Downloads the match's image, encodes its largest face with the same
backend family as face.py, and compares embeddings with cosine similarity.
A social match only counts as *verified* when similarity >= threshold
(default 0.45 — the standard same-person band for ArcFace/SFace cosine).
"""

import cv2
import numpy as np
import requests

from face import detect_and_encode_array

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
MAX_BYTES = 8 * 1024 * 1024
DEFAULT_THRESHOLD = 0.45


def fetch_image(url, timeout=30):
    """Fetch a URL expected to be an image. Returns BGR array or None."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    try:
        r = requests.get(url, timeout=timeout, stream=True,
                         headers={"User-Agent": UA,
                                  "Accept": "image/*,*/*;q=0.8"})
        if r.status_code != 200:
            return None
        if not r.headers.get("Content-Type", "").split(";")[0].startswith(
                "image/"):
            return None
        buf = bytearray()
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) > MAX_BYTES:
                return None
        if not buf:
            return None
        img = cv2.imdecode(np.frombuffer(bytes(buf), np.uint8),
                           cv2.IMREAD_COLOR)
        return img if img is not None and img.size else None
    except Exception:  # noqa: BLE001 — any fetch/decode failure = unverified
        return None


def cosine(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


def verify_match(face_embedding, match_image_url, threshold=DEFAULT_THRESHOLD,
                 timeout=30):
    """Compare the input face embedding against the match image's face."""
    img = fetch_image(match_image_url, timeout=timeout)
    if img is None:
        return {"verified": False, "similarity": None,
                "reason": "match-image-download-failed"}
    try:
        enc = detect_and_encode_array(img)
    except Exception as e:  # noqa: BLE001
        return {"verified": False, "similarity": None,
                "reason": f"match-face-encode-failed: {e}"}
    sim = cosine(face_embedding, enc["embedding"])
    return {"verified": bool(sim >= threshold), "similarity": round(sim, 4),
            "threshold": threshold, "match_backend": enc["backend"],
            "match_bbox": enc["bbox"],
            "reason": "similarity-below-threshold" if sim < threshold else "ok"}
