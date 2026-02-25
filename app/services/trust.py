from statistics import mean
from app.schemas.signal import SensorPayload


def compute_trust_score(payload: SensorPayload) -> int:
    # Simplified heuristic: lower movement with high overlay risks score reduction
    movement = mean(abs(x) for x in payload.accelerometer + payload.gyroscope)
    overlay = payload.overlay
    proximity = payload.proximity

    score = 100
    score -= int(movement * 5)
    score -= int(max(overlay - 0.3, 0) * 50)
    score -= int(max(0.5 - proximity, 0) * 40)
    return max(0, min(score, 100))
