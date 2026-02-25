import math
import statistics
from typing import Iterable, List, Tuple

from app.schemas.signal import SensorPayload

MAX_HISTORY = 100
EMA_ALPHA = 0.2


def _magnitude(vec: Iterable[float]) -> float:
    return sum(abs(x) for x in vec)


def _ema(values: List[float], alpha: float = EMA_ALPHA) -> float:
    if not values:
        return 0.0
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def _entropy_bools(values: List[bool]) -> float:
    if not values:
        return 0.0
    total = len(values)
    p_true = sum(1 for v in values if v) / total
    p_false = 1 - p_true
    entropy = 0.0
    for p in (p_true, p_false):
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy  # max is 1 bit


def _correlation(x: List[float], y: List[float]) -> float:
    if len(x) < 2 or len(x) != len(y):
        return 0.0
    mean_x = statistics.mean(x)
    mean_y = statistics.mean(y)
    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mean_x) ** 2 for a in x) * sum((b - mean_y) ** 2 for b in y))
    if den == 0:
        return 0.0
    return num / den


def compute_trust_score_stateful(current: SensorPayload, history: List[SensorPayload]) -> Tuple[int, dict]:
    """
    Stateful trust score using EMAs, entropy, correlation, and adaptive thresholds.
    Returns (score, diagnostics).
    """
    trimmed_history = history[:MAX_HISTORY]
    accel_series = [_magnitude(p.accelerometer) for p in trimmed_history] + [_magnitude(current.accelerometer)]
    gyro_series = [_magnitude(p.gyroscope) for p in trimmed_history] + [_magnitude(current.gyroscope)]

    accel_ema = _ema(accel_series)
    gyro_ema = _ema(gyro_series)
    accel_std = statistics.pstdev(accel_series) if len(accel_series) > 1 else 0.0
    gyro_std = statistics.pstdev(gyro_series) if len(gyro_series) > 1 else 0.0

    # z-scores vs EMA baseline
    def zscore(value: float, ema: float, std: float) -> float:
        return abs(value - ema) / std if std > 0 else abs(value - ema)

    z_accel = zscore(accel_series[-1], accel_ema, accel_std)
    z_gyro = zscore(gyro_series[-1], gyro_ema, gyro_std)

    touch_entropy = _entropy_bools([p.touch_event for p in trimmed_history] + [current.touch_event])
    accel_gyro_corr = _correlation(accel_series, gyro_series)

    # Normalize component scores to 0-100 (lower z => higher trust)
    accel_score = max(0, 100 - min(100, int(z_accel * 20)))
    gyro_score = max(0, 100 - min(100, int(z_gyro * 20)))
    touch_score = max(0, 100 - int(touch_entropy * 50))  # entropy 1 -> minus 50
    # Approximate network/motion stability using motion_delta (higher delta = better)
    network_spike_score = max(0, min(100, int(current.motion_delta * 100)))

    global_score = int(
        0.4 * accel_score
        + 0.3 * gyro_score
        + 0.15 * touch_score
        + 0.15 * network_spike_score
    )

    diagnostics = {
        "accel_ema": accel_ema,
        "gyro_ema": gyro_ema,
        "accel_std": accel_std,
        "gyro_std": gyro_std,
        "accel_z": z_accel,
        "gyro_z": z_gyro,
        "touch_entropy": touch_entropy,
        "accel_gyro_corr": accel_gyro_corr,
        "network_spike_score": network_spike_score,
    }
    return global_score, diagnostics
