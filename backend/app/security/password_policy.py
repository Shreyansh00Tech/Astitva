import re

COMMON = {
    "password", "password1", "password123", "123456", "12345678", "123456789", "qwerty", "qwerty123",
    "letmein", "welcome", "welcome1", "admin", "admin123", "iloveyou", "monkey", "dragon", "football",
    "abc123", "111111", "passw0rd", "p@ssw0rd", "changeme", "secret", "nexora", "nexora123",
}


def evaluate_password(password: str, email: str | None = None, name: str | None = None) -> dict:
    """Returns {score 0-4, ok, problems[]}. Server-side source of truth for strength."""
    problems: list[str] = []
    if len(password) < 12:
        problems.append("Use at least 12 characters.")
    if len(password) > 128:
        problems.append("Use at most 128 characters.")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        problems.append("Mix at least three of: lowercase, uppercase, digits, symbols.")
    lowered = password.lower()
    if lowered in COMMON or re.sub(r"[^a-z]", "", lowered) in COMMON:
        problems.append("This password is too common.")
    if re.search(r"(.)\1{3,}", password):
        problems.append("Avoid repeating the same character.")
    if email:
        local = email.split("@")[0].lower()
        if len(local) >= 4 and local in lowered:
            problems.append("Do not include your email address.")
    if name:
        for part in name.lower().split():
            if len(part) >= 4 and part in lowered:
                problems.append("Do not include your name.")
                break
    score = min(4, max(0, (len(password) >= 12) + (len(password) >= 16) + (classes >= 3) + (classes == 4)))
    if problems:
        score = min(score, 1)
    return {"score": score, "ok": not problems, "problems": problems}
