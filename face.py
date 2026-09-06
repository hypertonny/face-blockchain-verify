"""Face detection + encoding module.

Tiered backend (first available wins):
  1. InsightFace (buffalo) — best quality, 512-d ArcFace embedding.
  2. ONNX Runtime ArcFace (w600k_r50) + YuNet detector — genuine
     face-recognition embedding, auto-downloaded on first run.
  3. YuNet detection + SFace recognition (built into opencv, ~4 MB
     download) — genuine 128-d face embedding.
  4. OpenCV DNN detector + normalized pixel descriptor fallback — always
     works offline with zero downloads (clearly flagged in output).

Never hardcodes an identity: every embedding is computed from the input
pixels at runtime.
"""

import hashlib
import io
import os
import urllib.request
import warnings
from contextlib import redirect_stderr, redirect_stdout

import cv2
import numpy as np

# Keep third-party chatter out of the pipeline output (clean CLI).
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
warnings.filterwarnings("ignore", module="insightface")
warnings.filterwarnings("ignore", module="onnxruntime")
try:
    import onnxruntime as _ort  # type: ignore
    _ort.set_default_logger_severity(3)  # errors only
except Exception:  # noqa: BLE001
    pass

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".models")

# InsightFace buffalo_l ArcFace model (w600k_r50) — ~166 MB, downloaded once.
ARCFACE_URL = (
    "https://github.com/deepinsight/insightface/releases/download/v0.7/"
    "buffalo_l.zip"
)
ARCFACE_ONNX = os.path.join(MODELS_DIR, "w600k_r50.onnx")

# Lightweight OpenCV DNN face detector (~5 MB total).
DNN_PROTO_URL = (
    "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/"
    "face_detector/deploy_lowres.prototxt"
)
DNN_MODEL_URL = (
    "https://raw.githubusercontent.com/opencv/opencv_3rdparty/"
    "dnn_samples_face_detector_20180205_fp16/"
    "res10_300x300_ssd_iter_140000_fp16.caffemodel"
)
DNN_PROTO = os.path.join(MODELS_DIR, "deploy_lowres.prototxt")
DNN_MODEL = os.path.join(MODELS_DIR, "res10_300x300_ssd_iter_140000_fp16.caffemodel")

# YuNet detector (~300 KB) + SFace recognizer (~4 MB): genuine face
# detection + 128-d face embedding, bundled in opencv-python-headless>=4.5.
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
SFACE_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec.onnx"
)
YUNET_MODEL = os.path.join(MODELS_DIR, "face_detection_yunet_2023mar.onnx")
SFACE_MODEL = os.path.join(MODELS_DIR, "face_recognition_sface_2021dec.onnx")


def _download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    tmp = dest + ".part"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, dest)
    return dest


def _load_image(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"cannot read image: {path}")
    return img


_APP = None  # cached InsightFace session (models load once, not per face)


def _insightface_backend():
    global _APP
    if _APP is not None:
        return _APP or None
    try:
        from insightface.app import FaceAnalysis  # type: ignore
    except Exception:
        _APP = False
        return None
    try:
        # InsightFace prints model-loading banners; silence for clean output.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                app = FaceAnalysis(name="buffalo_s")
                app.prepare(ctx_id=-1, det_size=(640, 640))
        _APP = app
        return app
    except Exception:
        _APP = False
        return None


def _onnx_arcface_session():
    try:
        import onnxruntime as ort  # type: ignore
    except Exception:
        return None
    # buffalo_l.zip contains w600k_r50.onnx; try direct single-file mirrors too.
    if not os.path.exists(ARCFACE_ONNX):
        return None
    try:
        return ort.InferenceSession(ARCFACE_ONNX, providers=["CPUExecutionProvider"])
    except Exception:
        return None


def _ensure_arcface_model():
    """Download buffalo_l bundle and extract w600k_r50.onnx. Returns path or None."""
    import zipfile

    if os.path.exists(ARCFACE_ONNX) and os.path.getsize(ARCFACE_ONNX) > 10_000_000:
        return ARCFACE_ONNX
    os.makedirs(MODELS_DIR, exist_ok=True)
    bundle = os.path.join(MODELS_DIR, "buffalo_l.zip")
    try:
        _download(ARCFACE_URL, bundle)
        with zipfile.ZipFile(bundle) as z:
            for name in z.namelist():
                if name.endswith("w600k_r50.onnx"):
                    z.extract(name, MODELS_DIR)
                    src = os.path.join(MODELS_DIR, name)
                    if src != ARCFACE_ONNX:
                        os.replace(src, ARCFACE_ONNX)
                    return ARCFACE_ONNX
    except Exception:
        return None
    return None


def _detect_dnn(img):
    """OpenCV DNN SSD detector. Returns list of (x1, y1, x2, y2, score)."""
    try:
        _download(DNN_PROTO_URL, DNN_PROTO)
        _download(DNN_MODEL_URL, DNN_MODEL)
        net = cv2.dnn.readNetFromCaffe(DNN_PROTO, DNN_MODEL)
    except Exception:
        return []
    h, w = img.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(img, (300, 300)), 1.0, (300, 300), (104.0, 177.0, 123.0)
    )
    net.setInput(blob)
    out = net.forward()
    boxes = []
    for i in range(out.shape[2]):
        score = float(out[0, 0, i, 2])
        if score > 0.5:
            x1 = int(out[0, 0, i, 3] * w)
            y1 = int(out[0, 0, i, 4] * h)
            x2 = int(out[0, 0, i, 5] * w)
            y2 = int(out[0, 0, i, 6] * h)
            boxes.append((max(0, x1), max(0, y1), min(w, x2), min(h, y2), score))
    return boxes


def _detect_yunet(img):
    """YuNet detector (built into opencv). Returns (x1,y1,x2,y2,score,face)."""
    if not hasattr(cv2, "FaceDetectorYN_create"):
        return []
    try:
        _download(YUNET_URL, YUNET_MODEL)
    except Exception:
        return []
    h, w = img.shape[:2]
    try:
        det = cv2.FaceDetectorYN_create(YUNET_MODEL, "", (w, h))
        det.setScoreThreshold(0.5)
        det.setNMSThreshold(0.3)
        _, faces = det.detect(img)
    except Exception:
        return []
    out = []
    if faces is not None:
        for f in faces:
            x, y, fw, fh = [int(v) for v in f[:4]]
            score = float(f[14])
            if score > 0.3:
                out.append((max(0, x), max(0, y), min(w, x + fw),
                            min(h, y + fh), score, f))
    return out


def _sface_embed(img, yunet_face):
    """SFace 128-d embedding (built into opencv). Returns vector or None."""
    if not hasattr(cv2, "FaceRecognizerSF_create"):
        return None
    try:
        _download(SFACE_URL, SFACE_MODEL)
        rec = cv2.FaceRecognizerSF_create(SFACE_MODEL, "")
        aligned = rec.alignCrop(img, yunet_face)
        feat = rec.feature(aligned).flatten().astype(np.float32)
        norm = np.linalg.norm(feat)
        return feat / norm if norm > 0 else feat
    except Exception:
        return None


def _arcface_embed(session, face_bgr):
    # ArcFace preprocessing: RGB, resize 112x112, normalize.
    rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
    rgb = cv2.resize(rgb, (112, 112)).astype(np.float32)
    rgb = (rgb - 127.5) / 128.0
    blob = np.transpose(rgb, (2, 0, 1))[np.newaxis, :].astype(np.float32)
    name = session.get_inputs()[0].name
    emb = session.run(None, {name: blob})[0][0]
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb.astype(np.float32)


def _pixel_embed(face_bgr):
    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (32, 32)).astype(np.float32).flatten()
    small = (small - small.mean()) / (small.std() + 1e-6)
    return small.astype(np.float32)


def detect_and_encode_array(img):
    """Detect the largest face in a BGR array and compute its embedding.

    Returns dict with bbox, embedding (list), embedding_sha256, backend.
    """
    h, w = img.shape[:2]
    backend = "unknown"
    embedding = None
    box = None
    score = 0.0

    # Tier 1: InsightFace.
    app = _insightface_backend()
    if app is not None:
        try:
            faces = app.get(img)
            if faces:
                f = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) *
                        (f.bbox[3] - f.bbox[1]))
                x1, y1, x2, y2 = [int(v) for v in f.bbox]
                box = (max(0, x1), max(0, y1), min(w, x2), min(h, y2))
                embedding = np.asarray(f.normed_embedding, dtype=np.float32)
                score = float(getattr(f, "det_score", 1.0))
                backend = "insightface-buffalo_s"
        except Exception:
            embedding = None

    # Tier 2: ONNX ArcFace + OpenCV detector.
    if embedding is None:
        model = _ensure_arcface_model() if os.environ.get(
            "FBV_SKIP_MODEL_DOWNLOAD") != "1" else (
                ARCFACE_ONNX if os.path.exists(ARCFACE_ONNX) else None)
        sess = _onnx_arcface_session() if model else None
        boxes = None
        if sess is not None:
            yfaces = _detect_yunet(img)
            boxes = [(x1, y1, x2, y2, s) for (x1, y1, x2, y2, s, _) in yfaces]
            if not boxes:
                boxes = [(x1, y1, x2, y2, s) for
                         (x1, y1, x2, y2, s) in _detect_dnn(img)]
        if boxes and sess is not None:
            x1, y1, x2, y2, score = max(boxes, key=lambda b: (
                b[2] - b[0]) * (b[3] - b[1]))
            box = (x1, y1, x2, y2)
            embedding = _arcface_embed(sess, img[y1:y2, x1:x2])
            backend = "onnx-arcface-w600k_r50+yunet"

    # Tier 3: YuNet detection + SFace recognition (built into opencv,
    # ~4 MB model download, genuine 128-d face embedding).
    if embedding is None and os.environ.get(
            "FBV_SKIP_MODEL_DOWNLOAD") != "1":
        yfaces = _detect_yunet(img)
        if yfaces:
            x1, y1, x2, y2, score, yf = max(yfaces, key=lambda b: (
                b[2] - b[0]) * (b[3] - b[1]))
            emb = _sface_embed(img, yf)
            if emb is not None:
                box = (x1, y1, x2, y2)
                embedding = emb
                backend = "opencv-yunet+sface"

    # Tier 4: offline fallback (DNN detector + pixel descriptor).
    if embedding is None:
        boxes = _detect_dnn(img)
        if not boxes:
            # Last resort: center crop so the pipeline still yields a record.
            cx, cy = w // 2, h // 2
            s = min(w, h) // 2
            boxes = [(cx - s // 2, cy - s // 2, cx + s // 2, cy + s // 2, 0.0)]
            backend = "fallback-center-crop+pixel-embedding"
        else:
            backend = "fallback-opencv-dnn+pixel-embedding"
        x1, y1, x2, y2, score = max(boxes, key=lambda b: (
            b[2] - b[0]) * (b[3] - b[1]))
        box = (x1, y1, x2, y2)
        embedding = _pixel_embed(img[y1:y2, x1:x2])

    emb = np.asarray(embedding, dtype=np.float32)
    digest = hashlib.sha256(emb.tobytes()).hexdigest()
    x1, y1, x2, y2 = box
    result = {
        "backend": backend,
        "bbox": [x1, y1, x2, y2],
        "det_score": float(score),
        "embedding_dim": int(emb.shape[0]),
        "embedding_sha256": digest,
        "embedding": [float(v) for v in emb],
        "image_width": w,
        "image_height": h,
    }
    return result


def detect_and_encode(image_path, out_dir=None):
    """Detect the largest face in an image file (see detect_and_encode_array)."""
    img = _load_image(image_path)
    result = detect_and_encode_array(img)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        x1, y1, x2, y2 = result["bbox"]
        crop = img[y1:y2, x1:x2]
        if crop.size:
            cv2.imwrite(os.path.join(out_dir, "face_crop.jpg"), crop)
    return result
