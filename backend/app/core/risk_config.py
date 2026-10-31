"""Central, documented weights for the rule-based risk engine.

Every number the risk engine adds comes from here (resource sensitivity and permission points live in
app.core.catalog because routing and the UI use them too). Change a weight here and the explanation text,
the tests and the score all follow. The final score is always clamped to 0-100.
"""

# Time windows (days). All history is bounded at the request's created_at so a request is never scored with
# events that happened after it ("no future leakage").
HISTORY_DAYS = 90          # confirmed violations and alerts
DENIALS_DAYS = 30          # denied operations at the gateway
VELOCITY_DAYS = 7          # recent request burst
VELOCITY_BASELINE_WEEKS = 8  # the requester's own normal pace before the burst window

WEIGHTS = {
    "EXTRA_PERMISSION": 2,            # per permission beyond the highest one
    "EXCESSIVE_PER_PERMISSION": 10,   # per permission the purpose does not need
    "EXCESSIVE_MAX": 25,
    "PURPOSE_MISMATCH": 20,
    "DEPARTMENT_SCOPE": 15,
    "CROSS_DEPARTMENT": 5,
    "LONG_DURATION": 10,              # up to 3x the proportionate maximum
    "VERY_LONG_DURATION": 15,         # beyond 3x
    "WEAK_JUSTIFICATION": 8,
    "WEAK_JUSTIFICATION_WORDS": 8,    # fewer words than this is weak
    "PRIOR_ACCESS": -5,               # positive signal: approved before for this resource
    "FIRST_ACCESS": 3,
    "DEVICE_UNKNOWN": 5,
    "DEVICE_UNTRUSTED": 15,
    # History group (capped together so one incident is not counted three times)
    "CONFIRMED_VIOLATION_EACH": 8,    # alerts a Security Manager resolved as CONFIRMED
    "OPEN_ALERT_EACH": 3,             # alerts not reviewed yet: weaker, they may be false positives
    "OPEN_ALERT_MAX": 6,
    "REPEATED_DENIALS_MIN": 3,        # denied operations (not denied requests) before it counts at all
    "REPEATED_DENIALS": 4,
    "REPEATED_DENIALS_HIGH_MIN": 10,
    "REPEATED_DENIALS_HIGH": 8,
    "HISTORY_GROUP_MAX": 20,
    # Behaviour group (velocity and the Isolation Forest look at overlapping behaviour, so they share a cap)
    "VELOCITY": 8,
    "VELOCITY_MIN_REQUESTS": 5,       # at least this many other requests in the window
    "VELOCITY_BASELINE_FACTOR": 3,    # and at least 3x the requester's own weekly baseline
    "BEHAVIOUR_ANOMALY": 10,
    "BEHAVIOUR_GROUP_MAX": 12,
}

GROUP_CAPS = {"HISTORY": WEIGHTS["HISTORY_GROUP_MAX"], "BEHAVIOUR": WEIGHTS["BEHAVIOUR_GROUP_MAX"]}

# Alert categories that can count as a policy violation once a Security Manager confirms them.
VIOLATION_CATEGORIES = ["POLICY_VIOLATION", "UNAUTHORIZED_ACCESS", "TOKEN_MISUSE", "BREAKGLASS_MISUSE"]

# Isolation Forest (behaviour anomaly). Reference population: every user with access requests or gateway events
# in the 30 days before the start of the request's day (UTC). The model is trained once per day on that
# population and cached; the requester is then scored with their behaviour up to the request time.
ANOMALY = {
    "WINDOW_DAYS": 30,
    "MIN_POPULATION": 12,     # below this the model is not trained and the signal is reported as unavailable
    "N_ESTIMATORS": 100,
    "CONTAMINATION": 0.08,
    "RANDOM_STATE": 42,       # fixed seed: same data gives the same result
}
