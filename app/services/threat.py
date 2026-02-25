import datetime as dt
from typing import List
from app.schemas.edr import EdrReportIn

MALWARE_HASH_BLACKLIST = {
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # placeholder
    "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
}

RAT_DOMAINS = {
    "c2.evilrat.net",
    "stealth.trojanc2.io",
}

RAT_IPS = {
    "185.199.110.153",
    "45.67.230.12",
}

def compute_risk(report: EdrReportIn) -> tuple[int, str, list[str]]:
    score = 0
    actions: List[str] = []
    sideloaded_present = any(app.sideloaded for app in report.suspicious_apps)

    # Hash blacklist check
    for app in report.suspicious_apps:
        if app.hash_sha256.lower() in MALWARE_HASH_BLACKLIST:
            score += 50
            actions.append(f"blacklist_hit:{app.package}")
        if app.sideloaded:
            score += 15
            actions.append(f"sideloaded:{app.package}")

    perms_lower = {p.lower() for p in report.dangerous_permissions}
    if "sms" in perms_lower:
        score += 10
    if "accessibility" in perms_lower:
        score += 15
    if "device_admin" in perms_lower:
        score += 10

    # Critical combo heuristic
    if sideloaded_present and "sms" in perms_lower and "accessibility" in perms_lower:
        score += 30
        actions.append("combo_sideloaded_sms_accessibility")

    rat_detected = False
    # RAT DNS
    if report.dns_logs:
        for log in report.dns_logs:
            if log.domain in RAT_DOMAINS or log.ip in RAT_IPS:
                score += 40
                rat_detected = True
                actions.append(f"rat_contact:{log.domain or log.ip}")

    if rat_detected:
        risk_level = "critical"
        return min(100, max(score, 80)), risk_level, actions

    risk_level = "low"
    if score >= 80:
        risk_level = "critical"
    elif score >= 50:
        risk_level = "high"
    elif score >= 25:
        risk_level = "medium"

    return min(score, 100), risk_level, actions
