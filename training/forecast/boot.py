"""Bootstrap theo NGƯỜI dùng chung cho forecast (C4) và fatigue (D3): cùng cách lấy mẫu, cùng cách tính CI."""
import numpy as np


def resample_people(persons, boot):
    """Sinh `boot["n"]` danh sách người lấy mẫu có hoàn lại (seed cố định theo `boot["seed"]`)."""
    persons = sorted(persons)
    rng = np.random.default_rng(boot["seed"])
    for _ in range(boot["n"]):
        yield [persons[i] for i in rng.integers(0, len(persons), len(persons))]


def percentile_ci(values, boot):
    """CI percentile (bỏ giá trị không hữu hạn); None nếu còn quá ít mẫu hợp lệ (< max(10, n/10))."""
    lo, hi = (1 - boot["ci"]) / 2 * 100, (1 + boot["ci"]) / 2 * 100
    v = np.array(values, float)
    v = v[np.isfinite(v)]
    return None if len(v) < max(10, boot["n"] // 10) else [float(np.percentile(v, lo)), float(np.percentile(v, hi))]
