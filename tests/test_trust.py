import pytest

from app.schemas.signal import SensorPayload
from app.services.trust import compute_trust_score_stateful


def _payload(accel, gyro, touch=False, motion=0.5):
    return SensorPayload(
        accelerometer=accel,
        gyroscope=gyro,
        overlay=0.1,
        proximity=1.0,
        touch_event=touch,
        motion_delta=motion,
        device_admin_enabled=True,
        accessibility_enabled=True,
        platform="android",
    )


def test_trust_stateful_handles_stable_motion():
    history = [
        _payload([0.05, 0.04, 0.06], [0.05, 0.04, 0.06], touch=False, motion=0.6)
        for _ in range(20)
    ]
    current = _payload([0.05, 0.05, 0.06], [0.05, 0.04, 0.05], touch=False, motion=0.7)

    score, diag = compute_trust_score_stateful(current, history)
    assert score >= 60
    assert diag["touch_entropy"] == pytest.approx(0.0)


def test_trust_stateful_flags_anomalous_flat_activity():
    history = [
        _payload([0.01, 0.01, 0.01], [0.01, 0.01, 0.01], touch=True, motion=0.01)
        for _ in range(50)
    ]
    current = _payload([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], touch=True, motion=0.0)

    score, diag = compute_trust_score_stateful(current, history)
    assert score < 50
    assert diag["touch_entropy"] > 0
