"""Shared v3 feature contract. No training or application side effects."""
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

import numpy as np

FEATURES = ['neck', 'trunk', 'head_pitch', 'vis_ear', 'vis_shoulder', 'vis_hip']
WINDOW = 20


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def environment():
    out = {'python': platform.python_version()}
    for name in ('numpy', 'scipy', 'scikit-learn', 'joblib', 'onnxruntime',
                 'mediapipe', 'opencv-python', 'threadpoolctl'):
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return out


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False), encoding='utf-8')


def win_stats(x):
    x = np.asarray(x, dtype=np.float32)
    if x.ndim != 3 or x.shape[1:] != (WINDOW, len(FEATURES)) or not np.isfinite(x).all():
        raise ValueError('Expected finite normalized X with shape [N,20,6]')
    return np.concatenate([x.mean(1), x.std(1), x.min(1), x.max(1)], axis=1)


def load_dataset(path):
    # The original notebook saves G as a Unicode array, so pickle is unnecessary.
    with np.load(path, allow_pickle=False) as data:
        x, y, g = data['X'], data['Y'], data['G']
    win_stats(x)
    if y.shape != (len(x),) or g.shape != y.shape or len(x) == 0:
        raise ValueError('X/Y/G lengths do not match or dataset is empty')
    if set(np.unique(y)) != {0, 1}:
        raise ValueError('Training labels must contain both 0 and 1')
    if g.dtype.kind not in 'US' or any(not str(v).strip() for v in g):
        raise ValueError('G must contain nonempty string person IDs')
    if np.any(x[:, :, 3:] < 0) or np.any(x[:, :, 3:] > 1):
        raise ValueError('Visibility must be in [0,1]')
    return x.astype(np.float32), y.astype(int), g.astype(str)


def check_reference(x, y, g, cfg):
    if cfg['features'] != FEATURES or cfg['window'] != WINDOW or cfg['angle_scale'] != 30:
        raise ValueError('Reference feature/window/normalization contract is incompatible')
    counts = {str(p): int((g == p).sum()) for p in np.unique(g)}
    expected = {p: int(v['n']) for p, v in cfg['loso_transformer'].items()}
    if len(x) != cfg['n_train_windows'] or counts != expected:
        raise ValueError(f'Dataset differs from reference counts: {counts}; expected {expected}')
    if not np.isclose(y.mean(), cfg['bad_ratio'], atol=1e-7, rtol=0):
        raise ValueError('BAD ratio differs from original model configuration')
    return counts
