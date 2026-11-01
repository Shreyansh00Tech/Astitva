"""Simulated service links for the access dependency graph (no real systems are called).

Each row: upstream resource code, dependent resource code (or None for a plain API), name, kind, endpoint,
criticality, description. Used by the seed and by the migration that creates the table, so an existing database
gets the same links without a reset.
"""

DEFAULT_DEPENDENCIES = [
    ("RES-DS-001", None, "Payments Fraud Scoring API", "API", "POST /v1/payments/fraud-score", "CRITICAL",
     "Scores every card payment in real time with the Fraud Detection Model."),
    ("RES-DS-001", None, "Checkout Risk Check API", "API", "POST /v1/checkout/risk", "HIGH",
     "Blocks risky storefront checkouts before payment."),
    ("RES-DS-001", "RES-ENG-001", "Fraud metrics feed", "FEED", None, "MEDIUM",
     "Publishes daily fraud metrics into the Internal Analytics API."),
    ("RES-DS-002", None, "Storefront Recommendations API", "API", "GET /v1/recommendations", "HIGH",
     "Serves product recommendations on the Nexora storefront."),
    ("RES-DS-002", "RES-ENG-001", "Recommendation metrics feed", "FEED", None, "LOW",
     "Click-through metrics for the analytics API."),
    ("RES-FIN-001", None, "Exposure Forecast API", "API", "GET /v1/risk/exposure", "HIGH",
     "Quarterly credit and market exposure forecasts."),
    ("RES-FIN-001", None, "Treasury Dashboard API", "API", "GET /v1/treasury/summary", "MEDIUM",
     "Treasury summary tiles built on the risk model."),
    ("RES-FIN-002", "RES-DS-001", "Fraud model training data", "TRAINING_DATA", None, "HIGH",
     "Transactions used to retrain the Fraud Detection Model."),
    ("RES-FIN-002", "RES-FIN-001", "Risk model training data", "TRAINING_DATA", None, "MEDIUM",
     "Transactions used to calibrate the Financial Risk Prediction Model."),
    ("RES-DS-003", None, "Support Answer API", "API", "POST /v1/support/answer", "MEDIUM",
     "Retrieval endpoint behind the support assistant."),
    ("RES-HR-001", None, "Payroll Export API", "API", "POST /v1/payroll/export", "HIGH",
     "Monthly payroll export to the (simulated) bank file."),
    ("RES-FIN-003", None, "Payments Reconciliation API", "API", "POST /v1/ledger/reconcile", "CRITICAL",
     "Nightly ledger and payments reconciliation."),
    ("RES-ENG-002", None, "Staging Services API", "API", "/staging/*", "LOW",
     "Staging microservices that read the development database."),
    ("RES-ENG-001", None, "Product Metrics Dashboard API", "API", "GET /v1/metrics", "LOW",
     "Dashboards for product managers."),
]
