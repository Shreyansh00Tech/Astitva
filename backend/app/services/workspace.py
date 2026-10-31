"""Simulated resource workspaces: what a grant holder can see and do inside a model, dataset or database.

Authorization is evaluated on every call from the caller's own live grants: the grant must belong to the
signed-in user, be ACTIVE, not be past its expiry and carry the permission the action needs. An expired grant
found here is expired on the spot. The UI only mirrors these answers.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.context import SYSTEM, Actor
from app.models import (
    AccessGrant,
    MockRecord,
    Resource,
    ResourceAccessEvent,
    User,
    utcnow,
)
from app.services import audit
from app.services import mock_catalog as cat
from app.services.grants import revoke_grant
from app.services.workflow import check_abac

PERM_ORDER = ["READ", "EXECUTE", "WRITE", "DELETE", "ADMIN"]
META = "_meta"


class WorkspaceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Access:
    resource: Resource
    grants: list[AccessGrant]
    permissions: list[str] = field(default_factory=list)

    @property
    def expires_at(self):
        exp = [g.expires_at for g in self.grants]
        return None if any(e is None for e in exp) else min(exp)

    @property
    def primary(self) -> AccessGrant:
        return self.grants[0]


def find_resource(db: Session, ref: str) -> Resource | None:
    return db.get(Resource, ref) or db.execute(select(Resource).where(Resource.code == ref)).scalar_one_or_none()


def resolve(db: Session, user: User, resource_ref: str) -> Access:
    """The caller's effective permissions on a resource, from their own live grants only."""
    res = find_resource(db, resource_ref)
    if not res or not cat.kind_for(res.code):
        raise WorkspaceError(404, "UNKNOWN_RESOURCE", "This resource has no simulated workspace.")
    now = utcnow()
    live, had_expired, policy = [], False, None
    for g in db.execute(select(AccessGrant).where(AccessGrant.user_id == user.id, AccessGrant.resource_id == res.id,
                                                  AccessGrant.status == "ACTIVE")).scalars().all():
        if g.expires_at and g.expires_at <= now:
            revoke_grant(db, SYSTEM, g, "Grant reached its expiry time", status="EXPIRED")
            had_expired = True
            continue
        denial = None if g.is_emergency else check_abac(user, res)
        if denial:
            policy = denial
            continue
        live.append(g)
    if not live:
        if had_expired:
            db.commit()
            raise WorkspaceError(403, "GRANT_EXPIRED", "Your access to this resource has expired.")
        if policy:
            raise WorkspaceError(403, "POLICY_DENIED", policy)
        raise WorkspaceError(403, "NO_ACTIVE_GRANT", "You do not have an active grant for this resource.")
    perms = {p for g in live for p in g.permissions} & set(res.available_permissions or PERM_ORDER)
    live.sort(key=lambda g: g.granted_at, reverse=True)
    return Access(res, live, [p for p in PERM_ORDER if p in perms])


def log(db: Session, actor: Actor, acc: Access | None, res: Resource | None, action: str, allowed: bool,
        reason: str, detail: dict | None = None) -> None:
    """Every privileged workspace call (and every refusal) is recorded like a gateway decision."""
    g = acc.primary if acc else None
    db.add(ResourceAccessEvent(user_id=actor.user.id if actor.user else None, resource_id=res.id if res else None,
                               grant_id=g.id if g else None, action=action, purpose=g.purpose if g else None,
                               tool="workspace", outcome="ALLOWED" if allowed else "DENIED", reason=reason[:255],
                               ip=actor.ip))
    audit.record(db, actor, "WORKSPACE_ACTION_ALLOWED" if allowed else "WORKSPACE_ACTION_DENIED",
                 resource_id=res.id if res else None, target_type="RESOURCE", target_id=res.code if res else None,
                 request_id=g.request_id if g else None, reason=reason,
                 new_state={"action": action, "simulated": True, **(detail or {})})
    if allowed and g:
        g.last_used_at = utcnow()


def need(acc: Access, perm: str) -> None:
    if perm not in acc.permissions:
        raise WorkspaceError(403, "PERMISSION_NOT_GRANTED",
                             f"{perm} is not among your granted permissions ({', '.join(acc.permissions)}).")


# --------------------------------------------------------------------------- records
def _ensure_table(db: Session, res: Resource, table: str) -> None:
    exists = db.scalar(select(func.count()).select_from(MockRecord)
                       .where(MockRecord.resource_id == res.id, MockRecord.table_name == table))
    if exists:
        return
    key = next(c["name"] for c in cat.TABLES[table]["columns"] if c["key"])
    now = utcnow()
    for i, row in enumerate(cat.generate_rows(res.code, table)):
        db.add(MockRecord(resource_id=res.id, table_name=table, record_key=str(row[key]), position=i, data=row,
                          created_at=now, updated_at=now))
    db.flush()


def check_table(res: Resource, table: str | None) -> str:
    tables = cat.tables_for(res.code)
    if not tables:
        raise WorkspaceError(404, "NO_TABLES", "This resource has no records.")
    table = table or tables[0]
    if table not in tables:
        raise WorkspaceError(404, "UNKNOWN_TABLE", "Unknown table for this resource.")
    return table


def live_rows(db: Session, res: Resource, table: str) -> list[MockRecord]:
    _ensure_table(db, res, table)
    return db.execute(select(MockRecord).where(MockRecord.resource_id == res.id, MockRecord.table_name == table,
                                               MockRecord.deleted_at.is_(None))
                      .order_by(MockRecord.position, MockRecord.created_at)).scalars().all()


def settings(db: Session, res: Resource) -> dict:
    m = db.execute(select(MockRecord).where(MockRecord.resource_id == res.id, MockRecord.table_name == META,
                                            MockRecord.record_key == "settings")).scalar_one_or_none()
    return dict(m.data) if m else {}


def save_settings(db: Session, res: Resource, user: User, changes: dict) -> dict:
    m = db.execute(select(MockRecord).where(MockRecord.resource_id == res.id, MockRecord.table_name == META,
                                            MockRecord.record_key == "settings")).scalar_one_or_none()
    if not m:
        m = MockRecord(resource_id=res.id, table_name=META, record_key="settings", data={}, created_by_id=user.id,
                       created_at=utcnow(), updated_at=utcnow())
        db.add(m)
    m.data = {**(m.data or {}), **changes}
    m.updated_by_id = user.id
    m.updated_at = utcnow()
    db.flush()
    return dict(m.data)


def _mask(v):
    if v is None:
        return None
    s = str(v)
    return s[:5] + "*" * max(len(s) - 5, 3)


def row_out(r: MockRecord, columns: list[dict], masked: bool) -> dict:
    data = {c["name"]: (_mask(r.data.get(c["name"])) if masked and c["pii"] else r.data.get(c["name"])) for c in columns}
    return {"id": r.id, "key": r.record_key, "data": data, "updated_at": r.updated_at,
            "edited": r.updated_by_id is not None or r.created_by_id is not None}


def masked_for(db: Session, acc: Access) -> bool:
    return bool(settings(db, acc.resource).get("mask_identifiers")) and "ADMIN" not in acc.permissions


def _cmp_key(v):
    if v is None:
        return (1, "")
    if isinstance(v, bool):
        return (0, int(v))
    if isinstance(v, (int, float)):
        return (0, v)
    return (0, str(v).lower())


def browse(db: Session, acc: Access, table: str, q: str | None, sort: str | None, desc: bool, page: int,
           size: int) -> dict:
    cols = cat.TABLES[table]["columns"]
    rows = live_rows(db, acc.resource, table)
    masked = masked_for(db, acc)
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if any(needle in str(r.data.get(c["name"], "")).lower()
                                       for c in cols if not (masked and c["pii"]))]
    if sort and any(c["name"] == sort for c in cols):
        rows = sorted(rows, key=lambda r: _cmp_key(r.data.get(sort)), reverse=desc)
    total = len(rows)
    start = (page - 1) * size
    return {"table": table, "total": total, "page": page, "size": size, "pages": max(1, -(-total // size)),
            "masked": masked, "rows": [row_out(r, cols, masked) for r in rows[start:start + size]]}


def _coerce(c: dict, v):
    name, typ = c["name"], c["type"]
    if v is None or v == "":
        if c["nullable"]:
            return None
        raise WorkspaceError(422, "INVALID_VALUE", f"{name} is required.")
    try:
        if typ in ("number", "integer"):
            if isinstance(v, bool):
                raise ValueError
            n = float(v)
            if not math.isfinite(n):
                raise ValueError
            if typ == "integer":
                if n != int(n):
                    raise ValueError
                n = int(n)
            if (c["min"] is not None and n < c["min"]) or (c["max"] is not None and n > c["max"]):
                raise WorkspaceError(422, "INVALID_VALUE", f"{name} must be between {c['min']} and {c['max']}.")
            return round(n, 2) if typ == "number" else n
        if typ == "boolean":
            if isinstance(v, bool):
                return v
            if str(v).lower() in ("true", "false"):
                return str(v).lower() == "true"
            raise ValueError
        if typ == "date":
            return date.fromisoformat(str(v)).isoformat()
        if typ == "category":
            if v not in (c["options"] or []):
                raise WorkspaceError(422, "INVALID_VALUE", f"{name} must be one of: {', '.join(c['options'])}.")
            return v
        s = str(v).strip()
        if not s or len(s) > 120:
            raise ValueError
        return s
    except WorkspaceError:
        raise
    except (ValueError, TypeError):
        raise WorkspaceError(422, "INVALID_VALUE", f"{name} is not a valid {typ}.")


def _validate(table: str, values: dict, partial: bool) -> dict:
    cols = {c["name"]: c for c in cat.TABLES[table]["columns"]}
    unknown = [k for k in values if k not in cols or not cols[k]["editable"]]
    if unknown:
        raise WorkspaceError(422, "INVALID_FIELD", f"Field(s) cannot be set: {', '.join(unknown)}.")
    out = {k: _coerce(cols[k], v) for k, v in values.items()}
    if not partial:
        missing = [c["name"] for c in cols.values() if c["editable"] and not c["nullable"] and c["name"] not in out]
        if missing:
            raise WorkspaceError(422, "MISSING_FIELD", f"Missing field(s): {', '.join(missing)}.")
    return out


def add_record(db: Session, acc: Access, user: User, table: str, values: dict) -> MockRecord:
    clean = _validate(table, values, partial=False)
    _ensure_table(db, acc.resource, table)
    spec = cat.TABLES[table]
    key_col = next(c["name"] for c in spec["columns"] if c["key"])
    n = db.scalar(select(func.count()).select_from(MockRecord).where(MockRecord.resource_id == acc.resource.id,
                                                                     MockRecord.table_name == table)) or 0
    while True:
        n += 1
        key = f"DEMO-NEW-{n:03d}"
        if not db.execute(select(MockRecord.id).where(MockRecord.resource_id == acc.resource.id, MockRecord.table_name == table,
                                                      MockRecord.record_key == key)).first():
            break
    now = utcnow()
    r = MockRecord(resource_id=acc.resource.id, table_name=table, record_key=key, position=n + 10000,
                   data={key_col: key, **clean}, created_by_id=user.id, updated_by_id=user.id, created_at=now, updated_at=now)
    db.add(r)
    db.flush()
    return r


def _get_record(db: Session, acc: Access, table: str, record_id: str) -> MockRecord:
    r = db.get(MockRecord, record_id)
    if not r or r.resource_id != acc.resource.id or r.table_name != table or r.deleted_at is not None:
        raise WorkspaceError(404, "UNKNOWN_RECORD", "Record not found.")
    return r


def edit_record(db: Session, acc: Access, user: User, table: str, record_id: str, values: dict) -> tuple[MockRecord, dict]:
    r = _get_record(db, acc, table, record_id)
    clean = _validate(table, values, partial=True)
    if not clean:
        raise WorkspaceError(422, "NO_CHANGES", "Nothing to change.")
    prev = {k: r.data.get(k) for k in clean}
    r.data = {**r.data, **clean}
    r.updated_by_id = user.id
    r.updated_at = utcnow()
    db.flush()
    return r, prev


def delete_record(db: Session, acc: Access, table: str, record_id: str) -> MockRecord:
    r = _get_record(db, acc, table, record_id)
    r.deleted_at = utcnow()
    db.flush()
    return r


# --------------------------------------------------------------------------- statistics and queries
def table_stats(db: Session, acc: Access, table: str) -> dict:
    """Computed from the live synthetic rows, so the numbers always match the table shown."""
    cols = cat.TABLES[table]["columns"]
    rows = [r.data for r in live_rows(db, acc.resource, table)]
    masked = masked_for(db, acc)
    missing = {c["name"]: sum(1 for r in rows if r.get(c["name"]) in (None, "")) for c in cols}
    cats, nums, bools = {}, {}, {}
    for c in cols:
        vals = [r.get(c["name"]) for r in rows if r.get(c["name"]) not in (None, "")]
        if c["type"] == "category":
            counts = {o: 0 for o in c["options"]}
            for v in vals:
                counts[v] = counts.get(v, 0) + 1
            cats[c["name"]] = [{"value": k, "count": v} for k, v in counts.items()]
        elif c["type"] in ("number", "integer") and vals:
            nums[c["name"]] = {"count": len(vals), "min": min(vals), "max": max(vals),
                               "mean": round(statistics.fmean(vals), 2), "median": round(statistics.median(vals), 2)}
        elif c["type"] == "boolean":
            bools[c["name"]] = {"true": sum(1 for v in vals if v is True), "false": sum(1 for v in vals if v is False)}
    return {"table": table, "records": len(rows), "columns": len(cols), "missing_values": sum(missing.values()),
            "missing_by_column": missing, "categories": cats, "numeric": nums, "booleans": bools, "masked": masked,
            "computed_from": "live synthetic rows"}


OPS = {"eq", "neq", "gt", "lt", "contains"}


def run_query(db: Session, acc: Access, table: str, filters: list[dict], group_by: str | None, metric: str,
              metric_column: str | None, limit: int) -> dict:
    cols = {c["name"]: c for c in cat.TABLES[table]["columns"]}
    masked = masked_for(db, acc)
    rows = [r for r in live_rows(db, acc.resource, table)]

    def ok(d: dict, f: dict) -> bool:
        c, op, v = cols[f["column"]], f["op"], f.get("value")
        x = d.get(c["name"])
        if op == "contains":
            return x is not None and str(v).lower() in str(x).lower()
        if c["type"] in ("number", "integer"):
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise WorkspaceError(422, "INVALID_QUERY", f"{c['name']} needs a number.")
            if x is None:
                return False
        elif c["type"] == "boolean":
            v = str(v).lower() == "true"
        return {"eq": x == v, "neq": x != v, "gt": x is not None and x > v, "lt": x is not None and x < v}[op]

    for f in filters:
        if f.get("column") not in cols or f.get("op") not in OPS:
            raise WorkspaceError(422, "INVALID_QUERY", "Unknown column or operator.")
        if masked and cols[f["column"]]["pii"]:
            raise WorkspaceError(403, "MASKED_COLUMN", "This column is masked by the resource admin.")
        if f["op"] in ("gt", "lt") and cols[f["column"]]["type"] not in ("number", "integer", "date"):
            raise WorkspaceError(422, "INVALID_QUERY", "Greater/less than only works on numbers and dates.")
        rows = [r for r in rows if ok(r.data, f)]
    sql = f"SELECT {'*' if not group_by else group_by + ', ' + metric.upper() + '(' + (metric_column or '*') + ')'} FROM {table}"
    if filters:
        sql += " WHERE " + " AND ".join(f"{f['column']} {dict(eq='=', neq='!=', gt='>', lt='<', contains='ILIKE')[f['op']]} "
                                        f"{('%' + str(f.get('value')) + '%') if f['op'] == 'contains' else f.get('value')!r}" for f in filters)
    if group_by:
        if group_by not in cols or cols[group_by]["type"] not in ("category", "boolean"):
            raise WorkspaceError(422, "INVALID_QUERY", "Group by needs a category or yes/no column.")
        if metric not in ("count", "avg", "sum"):
            raise WorkspaceError(422, "INVALID_QUERY", "Metric must be count, avg or sum.")
        if metric != "count" and (metric_column not in cols or cols[metric_column]["type"] not in ("number", "integer")):
            raise WorkspaceError(422, "INVALID_QUERY", "Average and sum need a numeric column.")
        groups: dict = {}
        for r in rows:
            groups.setdefault(r.data.get(group_by), []).append(r.data)
        out = []
        for k, items in groups.items():
            vals = [i.get(metric_column) for i in items if metric_column and i.get(metric_column) is not None]
            val = len(items) if metric == "count" else round(sum(vals), 2) if metric == "sum" else (round(statistics.fmean(vals), 2) if vals else None)
            out.append({"group": k, "value": val})
        out.sort(key=lambda x: _cmp_key(x["value"]), reverse=True)
        sql += f" GROUP BY {group_by}"
        return {"sql": sql + ";", "mode": "aggregate", "matched": len(rows), "groups": out,
                "label": "SIMULATED QUERY: run on synthetic demo rows only"}
    sql += f" LIMIT {limit}"
    return {"sql": sql + ";", "mode": "rows", "matched": len(rows),
            "rows": [row_out(r, list(cols.values()), masked) for r in rows[:limit]],
            "label": "SIMULATED QUERY: run on synthetic demo rows only"}


# --------------------------------------------------------------------------- models
MODEL_META_FIELDS = {"description", "monitoring_notes", "decision_threshold"}


def model_meta(db: Session, res: Resource) -> dict:
    spec = cat.MODELS[res.code]
    s = settings(db, res)
    return {"description": s.get("description", res.description), "monitoring_notes": s.get("monitoring_notes", ""),
            "decision_threshold": s.get("decision_threshold", spec["default_threshold"]),
            "edited_at": s.get("edited_at"), "edited_by": s.get("edited_by")}


def predict(db: Session, res: Resource, values: dict) -> dict:
    spec = cat.MODELS[res.code]
    clean = {}
    for f in spec["inputs"]:
        v = values.get(f["name"], f["default"])
        c = {"name": f["name"], "type": f["type"], "options": f["options"], "min": f["min"], "max": f["max"],
             "nullable": False}
        clean[f["name"]] = _coerce(c, v)
    thr = model_meta(db, res)["decision_threshold"]
    out = spec["predict"](clean, thr if thr is not None else 0.5)
    return {"inputs": clean, **out, "label": "SIMULATED OUTPUT — NOT A REAL MODEL PREDICTION",
            "engine": "Deterministic demo formula (no ML model, no external call)"}
