"""Static governance vocabulary: permissions, purposes and sensitivity rules."""

PERMISSIONS = ["READ", "EXECUTE", "WRITE", "DELETE", "ADMIN"]
PERMISSION_RANK = {"READ": 1, "EXECUTE": 2, "WRITE": 3, "DELETE": 4, "ADMIN": 5}

# purpose code -> (label, least-privilege permissions that satisfy it)
PURPOSES: dict[str, tuple[str, list[str]]] = {
    "MODEL_TESTING": ("Model Performance Testing", ["READ", "EXECUTE"]),
    "MODEL_TRAINING": ("Model Training / Retraining", ["READ", "WRITE"]),
    "ANALYTICS_REPORTING": ("Analytics & Reporting", ["READ"]),
    "FRAUD_INVESTIGATION": ("Fraud Investigation", ["READ", "EXECUTE"]),
    "COMPLIANCE_AUDIT": ("Compliance Audit", ["READ"]),
    "FEATURE_DEVELOPMENT": ("Feature Development", ["READ", "WRITE"]),
    "FRONTEND_TESTING": ("Frontend / UI Testing", ["READ"]),
    "DATA_MIGRATION": ("Data Migration", ["READ", "WRITE"]),
    "INCIDENT_RESPONSE": ("Incident Response", ["READ", "WRITE", "EXECUTE"]),
    "PAYROLL_PROCESSING": ("Payroll Processing", ["READ", "WRITE"]),
    "CUSTOMER_SUPPORT": ("Customer Support Case", ["READ"]),
    "SECURITY_REVIEW": ("Security Review", ["READ"]),
}

SENSITIVITY_RANK = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3, "CRITICAL": 4}
SENSITIVITY_POINTS = {"PUBLIC": 0, "INTERNAL": 5, "CONFIDENTIAL": 15, "RESTRICTED": 22, "CRITICAL": 30}
# Maximum duration (hours) the risk engine considers proportionate for each sensitivity level
SENSITIVITY_MAX_HOURS = {"PUBLIC": 720, "INTERNAL": 168, "CONFIDENTIAL": 72, "RESTRICTED": 48, "CRITICAL": 24}
PERMISSION_POINTS = {"READ": 0, "EXECUTE": 5, "WRITE": 12, "DELETE": 18, "ADMIN": 28}


def risk_level(score: int) -> str:
    if score <= 30:
        return "LOW"
    if score <= 60:
        return "MEDIUM"
    if score <= 80:
        return "HIGH"
    return "CRITICAL"


def purpose_label(code: str) -> str:
    return PURPOSES.get(code, (code.replace("_", " ").title(), []))[0]


def sort_perms(perms) -> list[str]:
    return sorted(set(perms), key=lambda p: PERMISSION_RANK.get(p, 99))
