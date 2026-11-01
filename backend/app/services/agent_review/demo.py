"""Agent Review demo: the "Load demo" button on the Agent Review page.

Loads the simulated example data once (see app/showcase.py) and re-creates the two Agent Review examples, both
ordinary disagreements the Security Manager settles:

  1. Rahul -> Customer Transaction Dataset, READ + WRITE for analysis; two of his last three requests were narrowed
              => rule score about 55, AI score about 70 (the band changes), the Security Manager picks.
  2. Neha  -> Finance Ledger Database, READ + WRITE to fix audit findings; two earlier grants were never used
              => rule score about 67, AI score about 83, the Security Manager picks.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.context import Actor
from app.services import audit


def run(db: Session, actor: Actor) -> list[dict]:
    from app import showcase

    out = showcase.Loader(db).agent_cases()
    audit.record(db, actor, "AGENT_REVIEW_DEMO_LOADED", target_type="ACCESS_REQUEST",
                 new_state={"requests": [o["ref"] for o in out]},
                 reason="Security Manager loaded the Agent Review demo (simulated requests).")
    db.commit()
    return out


if __name__ == "__main__":
    from app.core.db import SessionLocal

    with SessionLocal() as s:
        for row in run(s, Actor(actor_type="SYSTEM", name="Agent Review demo")):
            print(row)
