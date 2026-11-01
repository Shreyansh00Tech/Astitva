"""Fictional content behind the simulated resource workspaces.

Everything here is invented for the demo: model metrics were never measured, predictions come from fixed
formulas, and every record is generated from a seeded random generator. No real model, dataset, person,
customer or financial detail is used, and nothing here calls an external service.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

DISCLAIMER = "Simulated demonstration. No real model, dataset or production system is connected."

# --------------------------------------------------------------------------- helpers


def col(name: str, typ: str, description: str, *, options: list | None = None, key: bool = False,
        pii: bool = False, editable: bool = True, nullable: bool = False, minimum: float | None = None,
        maximum: float | None = None) -> dict:
    return {"name": name, "type": typ, "description": description, "options": options, "key": key, "pii": pii,
            "editable": editable and not key, "nullable": nullable, "min": minimum, "max": maximum}


def _d(rnd: random.Random, start: date, span_days: int) -> str:
    return (start + timedelta(days=rnd.randint(0, span_days))).isoformat()


def _pick(rnd: random.Random, weighted: list[tuple[str, int]]) -> str:
    return rnd.choices([v for v, _ in weighted], weights=[w for _, w in weighted])[0]


# --------------------------------------------------------------------------- datasets / databases
SUPPORT_CATS = ["Billing", "Login issue", "Product query", "Refund", "Delivery", "Account update"]


def _gen_tickets(rnd: random.Random, n: int) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        prio = _pick(rnd, [("High", 25), ("Medium", 45), ("Low", 30)])
        status = _pick(rnd, [("Open", 30), ("In progress", 25), ("Closed", 45)])
        hours = None if status != "Closed" else round(rnd.uniform(0.5, 6 if prio == "High" else 30), 1)
        rows.append({"ticket_id": f"DEMO-{i:03d}", "category": rnd.choice(SUPPORT_CATS), "priority": prio,
                     "sentiment": _pick(rnd, [("Positive", 25), ("Neutral", 40), ("Negative", 35)]),
                     "status": status, "resolution_hours": hours})
    return rows


def _gen_transactions(rnd: random.Random, n: int) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        amt = round(rnd.lognormvariate(7.2, 1.0), 2)
        flagged = amt > 9000 and rnd.random() < 0.5 or rnd.random() < 0.04
        rows.append({"txn_id": f"DEMO-TX-{i:04d}", "customer_ref": f"CUST-{rnd.randint(1000, 9999)}",
                     "amount_inr": min(amt, 250000.0), "channel": _pick(rnd, [("UPI", 45), ("Card", 30), ("Wallet", 15), ("NetBanking", 10)]),
                     "merchant_category": rnd.choice(["Groceries", "Electronics", "Travel", "Utilities", "Dining", "Fashion"]),
                     "txn_date": _d(rnd, date(2026, 7, 1), 110), "is_flagged": flagged})
    return rows


def _gen_cases(rnd: random.Random, n: int) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        status = _pick(rnd, [("Open", 25), ("Under review", 30), ("Closed", 45)])
        outcome = None if status != "Closed" else _pick(rnd, [("Confirmed fraud", 40), ("False positive", 45), ("Inconclusive", 15)])
        rows.append({"case_id": f"DEMO-CASE-{i:03d}", "txn_ref": f"DEMO-TX-{rnd.randint(1, 120):04d}",
                     "alert_source": _pick(rnd, [("Model score", 50), ("Rule engine", 30), ("Customer report", 20)]),
                     "fraud_type": rnd.choice(["Card not present", "Account takeover", "Identity mismatch", "Refund abuse", "Mule account"]),
                     "amount_inr": round(rnd.uniform(1500, 180000), 2),
                     "investigator_team": rnd.choice(["Team Alpha", "Team Beta", "Team Gamma"]),
                     "status": status, "outcome": outcome, "opened_on": _d(rnd, date(2026, 6, 1), 140)})
    return rows


def _gen_employees(rnd: random.Random, n: int) -> list[dict]:
    depts = ["Engineering", "Finance", "HR", "Data Science", "Security"]
    return [{"emp_ref": f"EMP-DEMO-{i:03d}", "department": rnd.choice(depts),
             "grade": rnd.choice(["G3", "G4", "G5", "G6", "G7"]), "join_year": rnd.randint(2015, 2026),
             "work_location": rnd.choice(["Bengaluru", "Pune", "Hyderabad", "Remote"]),
             "employment_type": _pick(rnd, [("Full-time", 85), ("Contract", 15)])} for i in range(1, n + 1)]


def _gen_bands(rnd: random.Random, n: int) -> list[dict]:
    out = []
    base = 6.0
    for i, g in enumerate(["G3", "G4", "G5", "G6", "G7"][:n]):
        lo = round(base * (1.45 ** i), 1)
        out.append({"band": g, "min_lpa": lo, "max_lpa": round(lo * 1.6, 1), "review_cycle": "Annual"})
    return out


def _gen_leave(rnd: random.Random, n: int) -> list[dict]:
    return [{"leave_id": f"LV-DEMO-{i:03d}", "emp_ref": f"EMP-DEMO-{rnd.randint(1, 40):03d}",
             "leave_type": rnd.choice(["Earned", "Sick", "Casual"]), "balance_days": rnd.randint(0, 24)}
            for i in range(1, n + 1)]


ACCOUNTS = [("1100", "Cash and bank (demo)", "Asset"), ("1200", "Receivables (demo)", "Asset"),
            ("2100", "Payables (demo)", "Liability"), ("3100", "Retained earnings (demo)", "Equity"),
            ("4100", "Subscription revenue (demo)", "Revenue"), ("5100", "Cloud costs (demo)", "Expense"),
            ("5200", "Salaries (demo)", "Expense")]


def _gen_gl(rnd: random.Random, n: int) -> list[dict]:
    return [{"entry_id": f"GL-DEMO-{i:04d}", "account_code": rnd.choice(ACCOUNTS)[0],
             "entry_type": rnd.choice(["Debit", "Credit"]), "amount_inr": round(rnd.uniform(5000, 900000), 2),
             "cost_centre": rnd.choice(["CC-ENG", "CC-FIN", "CC-HR", "CC-DS"]),
             "posting_date": _d(rnd, date(2026, 7, 1), 115)} for i in range(1, n + 1)]


def _gen_accounts(rnd: random.Random, n: int) -> list[dict]:
    return [{"account_code": c, "account_name": nm, "account_type": t} for c, nm, t in ACCOUNTS[:n]]


def _gen_recon(rnd: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(1, n + 1):
        status = _pick(rnd, [("Matched", 60), ("Variance", 25), ("Pending", 15)])
        out.append({"recon_id": f"REC-DEMO-{i:03d}", "period": f"2026-{rnd.randint(4, 10):02d}",
                    "status": status, "variance_inr": 0.0 if status == "Matched" else round(rnd.uniform(-25000, 25000), 2)})
    return out


def _gen_flags(rnd: random.Random, n: int) -> list[dict]:
    names = ["new_checkout", "dark_mode_v2", "fast_search", "beta_reports", "mfa_prompt_v3", "smart_retry",
             "bulk_export", "audit_banner", "edge_cache", "graph_view", "inline_help", "pdf_preview"]
    return [{"flag_key": names[i % len(names)] + ("" if i < len(names) else f"_{i}"),
             "environment": rnd.choice(["dev", "staging"]), "enabled": rnd.random() < 0.6,
             "rollout_pct": rnd.choice([0, 10, 25, 50, 100])} for i in range(n)]


def _gen_builds(rnd: random.Random, n: int) -> list[dict]:
    return [{"build_id": f"BLD-DEMO-{i:04d}", "service": rnd.choice(["web", "api", "worker", "gateway"]),
             "result": _pick(rnd, [("Passed", 80), ("Failed", 15), ("Cancelled", 5)]),
             "duration_min": round(rnd.uniform(3, 22), 1), "run_date": _d(rnd, date(2026, 9, 1), 60)} for i in range(1, n + 1)]


def _gen_endpoints(rnd: random.Random, n: int) -> list[dict]:
    eps = [("GET", "/v1/metrics/daily"), ("GET", "/v1/metrics/funnel"), ("GET", "/v1/cohorts"), ("POST", "/v1/reports"),
           ("GET", "/v1/events/top"), ("GET", "/v1/experiments")]
    return [{"endpoint": f"{m} {p}", "method": m, "avg_latency_ms": rnd.randint(40, 320),
             "calls_per_day": rnd.randint(200, 20000), "status": _pick(rnd, [("Healthy", 85), ("Degraded", 15)])}
            for m, p in eps[:n]]


TABLES: dict[str, dict] = {
    "support_tickets": {
        "label": "Support tickets", "key_prefix": "DEMO-", "key_width": 3, "count": 100, "gen": _gen_tickets,
        "columns": [
            col("ticket_id", "string", "Fictional ticket identifier", key=True),
            col("category", "category", "Support category", options=SUPPORT_CATS),
            col("priority", "category", "Ticket priority", options=["High", "Medium", "Low"]),
            col("sentiment", "category", "Illustrative sentiment label", options=["Positive", "Neutral", "Negative"]),
            col("status", "category", "Ticket workflow status", options=["Open", "In progress", "Closed"]),
            col("resolution_hours", "number", "Simulated resolution duration (empty while the ticket is not closed)",
                nullable=True, minimum=0, maximum=500),
        ]},
    "transactions": {
        "label": "Transactions", "key_prefix": "DEMO-TX-", "key_width": 4, "count": 120, "gen": _gen_transactions,
        "columns": [
            col("txn_id", "string", "Fictional transaction identifier", key=True),
            col("customer_ref", "string", "Pseudonymous customer reference (not a real customer)", pii=True),
            col("amount_inr", "number", "Simulated amount in INR", minimum=1, maximum=250000),
            col("channel", "category", "Payment channel", options=["UPI", "Card", "Wallet", "NetBanking"]),
            col("merchant_category", "category", "Merchant category",
                options=["Groceries", "Electronics", "Travel", "Utilities", "Dining", "Fashion"]),
            col("txn_date", "date", "Simulated transaction date"),
            col("is_flagged", "boolean", "Flagged by the simulated monitoring rules"),
        ]},
    "fraud_cases": {
        "label": "Fraud cases", "key_prefix": "DEMO-CASE-", "key_width": 3, "count": 80, "gen": _gen_cases,
        "columns": [
            col("case_id", "string", "Fictional case identifier", key=True),
            col("txn_ref", "string", "Linked demo transaction reference", pii=True),
            col("alert_source", "category", "What raised the alert", options=["Model score", "Rule engine", "Customer report"]),
            col("fraud_type", "category", "Suspected fraud pattern",
                options=["Card not present", "Account takeover", "Identity mismatch", "Refund abuse", "Mule account"]),
            col("amount_inr", "number", "Simulated amount at risk in INR", minimum=1, maximum=1000000),
            col("investigator_team", "category", "Fictional investigation team", options=["Team Alpha", "Team Beta", "Team Gamma"]),
            col("status", "category", "Case status", options=["Open", "Under review", "Closed"]),
            col("outcome", "category", "Outcome (empty until closed)", options=["Confirmed fraud", "False positive", "Inconclusive"],
                nullable=True),
            col("opened_on", "date", "Simulated date the case was opened"),
        ]},
    "employees": {
        "label": "employees", "key_prefix": "EMP-DEMO-", "key_width": 3, "count": 40, "gen": _gen_employees,
        "columns": [
            col("emp_ref", "string", "Fictional employee reference (no names are stored)", key=True, pii=True),
            col("department", "category", "Department", options=["Engineering", "Finance", "HR", "Data Science", "Security"]),
            col("grade", "category", "Job grade", options=["G3", "G4", "G5", "G6", "G7"]),
            col("join_year", "integer", "Year joined (simulated)", minimum=2000, maximum=2026),
            col("work_location", "category", "Work location", options=["Bengaluru", "Pune", "Hyderabad", "Remote"]),
            col("employment_type", "category", "Employment type", options=["Full-time", "Contract"]),
        ]},
    "compensation_bands": {
        "label": "compensation_bands", "key_prefix": "G", "key_width": 1, "count": 5, "gen": _gen_bands,
        "columns": [
            col("band", "string", "Grade band", key=True),
            col("min_lpa", "number", "Illustrative minimum (lakh per annum)", minimum=0, maximum=500),
            col("max_lpa", "number", "Illustrative maximum (lakh per annum)", minimum=0, maximum=500),
            col("review_cycle", "category", "Review cycle", options=["Annual", "Half-yearly"]),
        ]},
    "leave_balances": {
        "label": "leave_balances", "key_prefix": "LV-DEMO-", "key_width": 3, "count": 30, "gen": _gen_leave,
        "columns": [
            col("leave_id", "string", "Fictional leave record id", key=True),
            col("emp_ref", "string", "Fictional employee reference", pii=True),
            col("leave_type", "category", "Leave type", options=["Earned", "Sick", "Casual"]),
            col("balance_days", "integer", "Remaining days", minimum=0, maximum=60),
        ]},
    "gl_entries": {
        "label": "gl_entries", "key_prefix": "GL-DEMO-", "key_width": 4, "count": 90, "gen": _gen_gl,
        "columns": [
            col("entry_id", "string", "Fictional journal entry id", key=True),
            col("account_code", "category", "Ledger account", options=[a[0] for a in ACCOUNTS]),
            col("entry_type", "category", "Debit or credit", options=["Debit", "Credit"]),
            col("amount_inr", "number", "Simulated amount in INR", minimum=1, maximum=10000000),
            col("cost_centre", "category", "Cost centre", options=["CC-ENG", "CC-FIN", "CC-HR", "CC-DS"]),
            col("posting_date", "date", "Simulated posting date"),
        ]},
    "accounts": {
        "label": "accounts", "key_prefix": "", "key_width": 4, "count": len(ACCOUNTS), "gen": _gen_accounts,
        "columns": [
            col("account_code", "string", "Account code", key=True),
            col("account_name", "string", "Fictional account name"),
            col("account_type", "category", "Account type", options=["Asset", "Liability", "Equity", "Revenue", "Expense"]),
        ]},
    "reconciliations": {
        "label": "reconciliations", "key_prefix": "REC-DEMO-", "key_width": 3, "count": 24, "gen": _gen_recon,
        "columns": [
            col("recon_id", "string", "Fictional reconciliation id", key=True),
            col("period", "string", "Accounting period (YYYY-MM)"),
            col("status", "category", "Reconciliation status", options=["Matched", "Variance", "Pending"]),
            col("variance_inr", "number", "Simulated unexplained variance", minimum=-10000000, maximum=10000000),
        ]},
    "feature_flags": {
        "label": "feature_flags", "key_prefix": "flag_", "key_width": 2, "count": 12, "gen": _gen_flags,
        "columns": [
            col("flag_key", "string", "Feature flag key", key=True),
            col("environment", "category", "Environment", options=["dev", "staging"]),
            col("enabled", "boolean", "Whether the flag is on"),
            col("rollout_pct", "integer", "Rollout percentage", minimum=0, maximum=100),
        ]},
    "build_runs": {
        "label": "build_runs", "key_prefix": "BLD-DEMO-", "key_width": 4, "count": 40, "gen": _gen_builds,
        "columns": [
            col("build_id", "string", "Fictional CI build id", key=True),
            col("service", "category", "Service", options=["web", "api", "worker", "gateway"]),
            col("result", "category", "Build result", options=["Passed", "Failed", "Cancelled"]),
            col("duration_min", "number", "Simulated duration in minutes", minimum=0, maximum=600),
            col("run_date", "date", "Simulated run date"),
        ]},
    "endpoints": {
        "label": "endpoints", "key_prefix": "", "key_width": 1, "count": 6, "gen": _gen_endpoints,
        "columns": [
            col("endpoint", "string", "Mock endpoint", key=True),
            col("method", "category", "HTTP method", options=["GET", "POST"]),
            col("avg_latency_ms", "integer", "Simulated average latency", minimum=0, maximum=10000),
            col("calls_per_day", "integer", "Simulated daily calls", minimum=0, maximum=10000000),
            col("status", "category", "Simulated health", options=["Healthy", "Degraded"]),
        ]},
}


# --------------------------------------------------------------------------- models
def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _level(score: float) -> str:
    return "High" if score >= 0.7 else "Medium" if score >= 0.4 else "Low"


def _fraud_predict(x: dict, threshold: float) -> dict:
    device = {"Low": 0.0, "Medium": 0.8, "High": 1.8}[x["device_risk"]]
    z = (-4.2 + 1.5 * math.log10(max(x["amount_inr"], 1)) / 2 + 0.22 * x["txns_last_hour"] + device
         + (1.4 if x["location_anomaly"] else 0) - 0.004 * min(x["account_age_days"], 720))
    s = round(_sigmoid(z), 2)
    drivers = []
    if x["amount_inr"] >= 20000:
        drivers.append("high transaction amount")
    if x["txns_last_hour"] >= 5:
        drivers.append("burst of transactions in the last hour")
    if x["device_risk"] != "Low":
        drivers.append(f"{x['device_risk'].lower()} device risk")
    if x["location_anomaly"]:
        drivers.append("unusual location")
    if x["account_age_days"] < 60:
        drivers.append("new account")
    label = "Suspicious" if s >= threshold else "Normal"
    why = ("Score rises with " + ", ".join(drivers) + ".") if drivers else "No risk drivers present in the inputs."
    return {"score": s, "score_label": "Risk score", "predicted_class": label, "level": _level(s),
            "explanation": f"{why} The demo threshold is {threshold:.2f}, so the illustrative result is '{label}'."}


def _finrisk_predict(x: dict, threshold: float) -> dict:
    idx = (0.55 * x["debt_to_income_pct"] + 0.35 * x["credit_utilisation_pct"] + 6 * x["payment_delays_12m"]
           + 1.2 * x["market_volatility_index"] - 0.25 * x["collateral_cover_pct"])
    idx = max(0.0, min(100.0, round(idx / 1.3, 1)))
    band = "Severe" if idx >= 75 else "Elevated" if idx >= 50 else "Moderate" if idx >= 25 else "Low"
    return {"score": idx, "score_label": "Exposure risk index (0-100)", "predicted_class": band,
            "level": "High" if idx >= 60 else "Medium" if idx >= 30 else "Low",
            "explanation": (f"Debt-to-income of {x['debt_to_income_pct']}% and {x['payment_delays_12m']} late payment(s) "
                            f"drive most of the index; collateral cover of {x['collateral_cover_pct']}% pulls it down. "
                            "Bands are fixed demo cut-offs (25 / 50 / 75).")}


PRODUCTS = {
    "Electronics": ["Demo Noise-Cancel Earbuds", "Demo 4K Monitor", "Demo Smart Plug", "Demo Power Bank", "Demo USB-C Hub"],
    "Home": ["Demo Air Purifier", "Demo Cookware Set", "Demo Desk Lamp", "Demo Storage Boxes", "Demo Bedsheet Set"],
    "Fashion": ["Demo Running Shoes", "Demo Denim Jacket", "Demo Travel Backpack", "Demo Wrist Watch", "Demo Sunglasses"],
    "Books": ["Demo Data Science Primer", "Demo Mystery Novel", "Demo Cookbook", "Demo Finance Basics", "Demo Kids Atlas"],
}


def _rec_predict(x: dict, threshold: float) -> dict:
    rnd = random.Random(f"{x['customer_segment']}:{x['category']}:{x['price_band']}")
    items = list(PRODUCTS[x["category"]])
    rnd.shuffle(items)
    base = {"New visitor": 0.55, "Occasional buyer": 0.7, "Loyal customer": 0.85}[x["customer_segment"]]
    recs = [{"item": it, "score": round(base - i * 0.08 - rnd.uniform(0, 0.03), 2)} for i, it in enumerate(items[:5])]
    return {"score": recs[0]["score"], "score_label": "Top recommendation score",
            "predicted_class": recs[0]["item"], "level": None, "recommendations": recs,
            "explanation": (f"For a '{x['customer_segment']}' browsing {x['category']} in the {x['price_band']} band, the demo "
                            "ranks a fixed catalogue of fictional products with a seeded score.")}


def _loan_predict(x: dict, threshold: float) -> dict:
    z = (-6.0 + 0.011 * x["credit_score"] - 0.05 * x["debt_to_income_pct"] + 0.12 * min(x["employment_years"], 15)
         - 0.025 * x["loan_to_value_pct"] - 0.35 * x["existing_loans"])
    p = round(_sigmoid(z), 2)
    label = "Pre-approve" if p >= threshold else "Refer to underwriter" if p >= threshold - 0.25 else "Decline"
    return {"score": p, "score_label": "Approval probability", "predicted_class": label,
            "level": "Low" if p >= threshold else "Medium" if p >= threshold - 0.25 else "High",
            "explanation": (f"Credit score {x['credit_score']} and {x['employment_years']} years of employment raise the "
                            f"probability; debt-to-income {x['debt_to_income_pct']}% and loan-to-value {x['loan_to_value_pct']}% "
                            f"lower it. Demo threshold {threshold:.2f}. A real lending decision would need validated, "
                            "fairness-tested models and a human underwriter.")}


def field(name: str, label: str, typ: str, default, *, options: list | None = None, minimum=None, maximum=None,
          step=None) -> dict:
    return {"name": name, "label": label, "type": typ, "default": default, "options": options, "min": minimum,
            "max": maximum, "step": step}


MODELS: dict[str, dict] = {
    "RES-DS-001": {
        "task": "Binary classification", "algorithm": "Random Forest Classifier", "version": "Demo v1.0",
        "owner_team": "Fraud Intelligence Team", "created": "2026-03-04", "updated": "2026-09-18",
        "target": "is_suspicious (Suspicious / Normal)", "default_threshold": 0.5, "predict": _fraud_predict,
        "metrics": [("Accuracy", "94.2%"), ("Precision", "92.1%"), ("Recall", "89.7%"), ("F1-score", "90.9%"),
                    ("AUC-ROC", "0.96"), ("Evaluation records", "5,000")],
        "features": [("Transaction amount", 32), ("Transaction frequency", 25), ("Device risk indicator", 18),
                     ("Location anomaly indicator", 15), ("Account age", 10)],
        "sample_columns": ["Transaction ID", "Risk Score", "Predicted Result", "Risk Level"],
        "samples": [["DEMO-TX-001", 0.91, "Suspicious", "High"], ["DEMO-TX-002", 0.14, "Normal", "Low"],
                    ["DEMO-TX-003", 0.67, "Suspicious", "Medium"], ["DEMO-TX-004", 0.08, "Normal", "Low"],
                    ["DEMO-TX-005", 0.79, "Suspicious", "High"], ["DEMO-TX-006", 0.33, "Normal", "Low"]],
        "inputs": [field("amount_inr", "Transaction amount (INR)", "number", 4500, minimum=1, maximum=500000, step=100),
                   field("txns_last_hour", "Transactions in the last hour", "integer", 1, minimum=0, maximum=50),
                   field("device_risk", "Device risk indicator", "category", "Low", options=["Low", "Medium", "High"]),
                   field("location_anomaly", "Location anomaly", "boolean", False),
                   field("account_age_days", "Account age (days)", "integer", 400, minimum=0, maximum=5000)],
        "presets": [{"label": "Everyday grocery payment", "values": {"amount_inr": 1850, "txns_last_hour": 1, "device_risk": "Low", "location_anomaly": False, "account_age_days": 900}},
                    {"label": "Late-night electronics burst", "values": {"amount_inr": 64000, "txns_last_hour": 7, "device_risk": "High", "location_anomaly": True, "account_age_days": 21}},
                    {"label": "New account, mid-size spend", "values": {"amount_inr": 18000, "txns_last_hour": 3, "device_risk": "Medium", "location_anomaly": False, "account_age_days": 35}}],
    },
    "RES-FIN-001": {
        "task": "Regression (risk index)", "algorithm": "Gradient Boosting Regressor", "version": "Demo v1.0",
        "owner_team": "Risk Analytics Team", "created": "2026-01-22", "updated": "2026-08-30",
        "target": "90-day exposure risk index (0-100)", "default_threshold": None, "predict": _finrisk_predict,
        "metrics": [("R-squared", "0.87"), ("MAE", "4.2 pts"), ("RMSE", "6.1 pts"), ("MAPE", "7.8%"),
                    ("Evaluation records", "3,200")],
        "features": [("Debt-to-income ratio", 30), ("Credit utilisation", 24), ("Payment delays (12m)", 20),
                     ("Market volatility index", 16), ("Collateral cover", 10)],
        "sample_columns": ["Portfolio ID", "Risk Index", "Risk Band", "Risk Level"],
        "samples": [["DEMO-PF-101", 82.4, "Severe", "High"], ["DEMO-PF-102", 18.9, "Low", "Low"],
                    ["DEMO-PF-103", 47.3, "Moderate", "Medium"], ["DEMO-PF-104", 63.0, "Elevated", "High"],
                    ["DEMO-PF-105", 29.5, "Moderate", "Low"]],
        "inputs": [field("debt_to_income_pct", "Debt-to-income (%)", "number", 35, minimum=0, maximum=100),
                   field("credit_utilisation_pct", "Credit utilisation (%)", "number", 40, minimum=0, maximum=100),
                   field("payment_delays_12m", "Late payments (12 months)", "integer", 1, minimum=0, maximum=12),
                   field("market_volatility_index", "Market volatility index", "number", 18, minimum=0, maximum=80),
                   field("collateral_cover_pct", "Collateral cover (%)", "number", 60, minimum=0, maximum=200)],
        "presets": [{"label": "Stable mid-market borrower", "values": {"debt_to_income_pct": 28, "credit_utilisation_pct": 30, "payment_delays_12m": 0, "market_volatility_index": 15, "collateral_cover_pct": 90}},
                    {"label": "Stretched borrower, volatile market", "values": {"debt_to_income_pct": 62, "credit_utilisation_pct": 85, "payment_delays_12m": 4, "market_volatility_index": 40, "collateral_cover_pct": 20}}],
    },
    "RES-DS-002": {
        "task": "Ranking / recommendation", "algorithm": "Matrix factorisation (ALS collaborative filtering)",
        "version": "Demo v1.0", "owner_team": "Personalisation Team", "created": "2026-02-11", "updated": "2026-10-02",
        "target": "Top-N product ranking per customer segment", "default_threshold": None, "predict": _rec_predict,
        "metrics": [("Precision@10", "0.31"), ("Recall@10", "0.42"), ("NDCG@10", "0.47"), ("MAP@10", "0.29"),
                    ("Catalogue coverage", "68%"), ("Evaluation users", "12,000")],
        "features": [("Purchase history", 35), ("Browsing sessions", 25), ("Category affinity", 20),
                     ("Price band preference", 12), ("Seasonality", 8)],
        "sample_columns": ["Segment", "Category", "Top recommendation", "Score"],
        "samples": [["Loyal customer", "Electronics", "Demo 4K Monitor", 0.83], ["New visitor", "Books", "Demo Cookbook", 0.52],
                    ["Occasional buyer", "Home", "Demo Air Purifier", 0.69], ["Loyal customer", "Fashion", "Demo Running Shoes", 0.81]],
        "inputs": [field("customer_segment", "Customer segment", "category", "Occasional buyer",
                         options=["New visitor", "Occasional buyer", "Loyal customer"]),
                   field("category", "Browsing category", "category", "Electronics", options=list(PRODUCTS)),
                   field("price_band", "Price band", "category", "Mid", options=["Budget", "Mid", "Premium"])],
        "presets": [{"label": "Loyal electronics shopper", "values": {"customer_segment": "Loyal customer", "category": "Electronics", "price_band": "Premium"}},
                    {"label": "First visit, books", "values": {"customer_segment": "New visitor", "category": "Books", "price_band": "Budget"}}],
    },
    "RES-FIN-004": {
        "task": "Binary classification (scorecard)", "algorithm": "Logistic Regression scorecard", "version": "Demo v1.0",
        "owner_team": "Retail Credit Team", "created": "2026-04-15", "updated": "2026-10-12",
        "target": "pre_approve (Pre-approve / Refer / Decline)", "default_threshold": 0.6, "predict": _loan_predict,
        "metrics": [("Accuracy", "88.5%"), ("Precision", "86.3%"), ("Recall", "84.0%"), ("F1-score", "85.1%"),
                    ("AUC-ROC", "0.91"), ("KS statistic", "0.58"), ("Evaluation records", "4,000")],
        "features": [("Credit score", 34), ("Debt-to-income ratio", 26), ("Employment stability", 18),
                     ("Loan-to-value ratio", 14), ("Existing loans", 8)],
        "sample_columns": ["Application ID", "Approval Probability", "Predicted Result", "Risk Level"],
        "samples": [["DEMO-APP-001", 0.86, "Pre-approve", "Low"], ["DEMO-APP-002", 0.41, "Refer to underwriter", "Medium"],
                    ["DEMO-APP-003", 0.12, "Decline", "High"], ["DEMO-APP-004", 0.72, "Pre-approve", "Low"]],
        "inputs": [field("credit_score", "Credit score (300-900)", "integer", 720, minimum=300, maximum=900),
                   field("debt_to_income_pct", "Debt-to-income (%)", "number", 30, minimum=0, maximum=100),
                   field("employment_years", "Years in employment", "integer", 4, minimum=0, maximum=45),
                   field("loan_to_value_pct", "Loan-to-value (%)", "number", 70, minimum=0, maximum=150),
                   field("existing_loans", "Existing loans", "integer", 1, minimum=0, maximum=10)],
        "presets": [{"label": "Strong salaried applicant", "values": {"credit_score": 800, "debt_to_income_pct": 22, "employment_years": 8, "loan_to_value_pct": 60, "existing_loans": 0}},
                    {"label": "Thin file, high leverage", "values": {"credit_score": 610, "debt_to_income_pct": 55, "employment_years": 1, "loan_to_value_pct": 95, "existing_loans": 3}}],
    },
}

DATASETS: dict[str, dict] = {
    "RES-DS-003": {"dataset_id": "DEMO-DS-001", "purpose": "Demonstration of customer-support analytics and assistant evaluation.",
                   "owner_team": "Support Insights Team", "tables": ["support_tickets"], "chart_column": "priority"},
    "RES-FIN-002": {"dataset_id": "DEMO-DS-002", "purpose": "Demonstration of transaction analytics and fraud-rule tuning.",
                    "owner_team": "Payments Analytics Team", "tables": ["transactions"], "chart_column": "channel"},
    "RES-DS-004": {"dataset_id": "DEMO-DS-003", "purpose": "Demonstration of fraud case tracking and investigation outcomes.",
                   "owner_team": "Fraud Intelligence Team", "tables": ["fraud_cases"], "chart_column": "fraud_type"},
}

DATABASES: dict[str, dict] = {
    "RES-HR-001": {"engine": "PostgreSQL 16 (simulated)", "schema": "hr_demo", "owner_team": "People Systems Team",
                   "tables": ["employees", "compensation_bands", "leave_balances"]},
    "RES-FIN-003": {"engine": "PostgreSQL 16 (simulated)", "schema": "ledger_demo", "owner_team": "Financial Control Team",
                    "tables": ["gl_entries", "accounts", "reconciliations"]},
    "RES-ENG-002": {"engine": "PostgreSQL 16 (simulated)", "schema": "dev_demo", "owner_team": "Platform Engineering",
                    "tables": ["feature_flags", "build_runs"]},
    "RES-ENG-001": {"engine": "REST API (simulated)", "schema": "analytics_api_demo", "owner_team": "Product Analytics Team",
                    "tables": ["endpoints"]},
}


def kind_for(code: str) -> str | None:
    if code in MODELS:
        return "MODEL"
    if code in DATASETS:
        return "DATASET"
    if code in DATABASES:
        return "DATABASE"
    return None


def tables_for(code: str) -> list[str]:
    spec = DATASETS.get(code) or DATABASES.get(code)
    return list(spec["tables"]) if spec else []


def generate_rows(code: str, table: str) -> list[dict]:
    t = TABLES[table]
    return t["gen"](random.Random(f"astitva-demo:{code}:{table}"), t["count"])
