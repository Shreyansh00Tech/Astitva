"""Simulated resource workspaces (models, datasets, databases) behind each user's own active grants.

Every route re-checks the caller's live grant and the exact permission the action needs. Hiding buttons in
the UI is only a convenience: these checks are the enforcement.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.api.serializers import user_brief
from app.core.catalog import purpose_label
from app.core.db import get_db
from app.models import AccessGrant, AuditEvent, utcnow
from app.services import mock_catalog as cat
from app.services import workspace as ws

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def _fail(db: Session, cu: CurrentUser, e: ws.WorkspaceError, action: str, acc: ws.Access | None = None,
          resource_ref: str | None = None):
    if e.status == 403:
        res = acc.resource if acc else ws.find_resource(db, resource_ref) if resource_ref else None
        ws.log(db, cu.actor, acc, res, action, False, e.message, {"code": e.code})
        db.commit()
    raise HTTPException(e.status, {"code": e.code, "message": e.message})


def _access(db: Session, cu: CurrentUser, resource_id: str, action: str, perm: str | None = None) -> ws.Access:
    try:
        acc = ws.resolve(db, cu.user, resource_id)
    except ws.WorkspaceError as e:
        _fail(db, cu, e, action, resource_ref=resource_id)
    if perm:
        try:
            ws.need(acc, perm)
        except ws.WorkspaceError as e:
            _fail(db, cu, e, action, acc)
    return acc


def _run(db: Session, cu: CurrentUser, acc: ws.Access, action: str, fn):
    try:
        return fn()
    except ws.WorkspaceError as e:
        db.rollback()
        _fail(db, cu, e, action, acc)


def _actions(perms: list[str], kind: str) -> dict:
    has = set(perms)
    return {"view": "READ" in has,
            "run_prediction": kind == "MODEL" and "EXECUTE" in has,
            "run_query": kind != "MODEL" and "EXECUTE" in has,
            "edit_metadata": kind == "MODEL" and "WRITE" in has,
            "add_record": kind != "MODEL" and "WRITE" in has,
            "edit_record": kind != "MODEL" and "WRITE" in has,
            "delete_record": kind != "MODEL" and "DELETE" in has,
            "admin": "ADMIN" in has}


def _table_info(db: Session, acc: ws.Access, table: str) -> dict:
    rows = ws.live_rows(db, acc.resource, table)
    last = max((r.updated_at for r in rows), default=None)
    return {"name": table, "label": cat.TABLES[table]["label"], "columns": cat.TABLES[table]["columns"],
            "records": len(rows), "last_updated": last}


@router.get("/{resource_id}")
def overview(resource_id: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = _access(db, cu, resource_id, "OPEN")
    res, kind = acc.resource, cat.kind_for(acc.resource.code)
    g = acc.primary
    can_read = "READ" in acc.permissions
    out: dict[str, Any] = {
        "resource": {"id": res.id, "code": res.code, "name": res.name, "type": res.resource_type,
                     "sensitivity": res.sensitivity, "department": res.department.name if res.department else None,
                     "description": res.description},
        "kind": kind, "permissions": acc.permissions, "available_permissions": res.available_permissions,
        "expires_at": acc.expires_at, "actions": _actions(acc.permissions, kind), "disclaimer": cat.DISCLAIMER,
        "grant": {"id": g.id, "purpose": g.purpose, "purpose_label": purpose_label(g.purpose), "granted_at": g.granted_at,
                  "expires_at": g.expires_at, "request_id": g.request_id, "is_emergency": g.is_emergency,
                  "source": g.source},
        "read_restricted": not can_read,
    }
    if kind == "MODEL":
        spec = cat.MODELS[res.code]
        meta = ws.model_meta(db, res)
        out["model"] = {"algorithm": spec["algorithm"], "task": spec["task"], "version": spec["version"],
                        "owner_team": spec["owner_team"], "created": spec["created"], "updated": meta["edited_at"] or spec["updated"],
                        "status": "DEMO ONLY", "status_note": "Simulated model; no real inference engine connected",
                        "target": spec["target"], "description": meta["description"]}
        if can_read:
            out["model"].update({
                "metrics": [{"name": n, "value": v} for n, v in spec["metrics"]],
                "metrics_label": "SIMULATED METRICS — NOT VALIDATED",
                "samples": {"columns": spec["sample_columns"], "rows": spec["samples"],
                            "label": "Pre-generated examples, not predictions from a working model"},
                "features": [{"name": n, "importance": v} for n, v in spec["features"]],
                "features_label": "Illustrative feature importance — simulated",
                "monitoring_notes": meta["monitoring_notes"], "decision_threshold": meta["decision_threshold"],
            })
        if "EXECUTE" in acc.permissions:
            out["model"]["playground"] = {"inputs": spec["inputs"], "presets": spec["presets"]}
    else:
        tables = [_table_info(db, acc, t) for t in cat.tables_for(res.code)] if can_read else []
        if kind == "DATASET":
            spec = cat.DATASETS[res.code]
            t = tables[0] if tables else None
            out["dataset"] = {"dataset_id": spec["dataset_id"], "purpose": spec["purpose"], "owner_team": spec["owner_team"],
                              "status": "DEMO DATA ONLY", "chart_column": spec["chart_column"], "tables": tables,
                              "records": t["records"] if t else None, "columns": len(t["columns"]) if t else None,
                              "last_updated": t["last_updated"] if t else None}
        else:
            spec = cat.DATABASES[res.code]
            out["database"] = {"engine": spec["engine"], "schema": spec["schema"], "owner_team": spec["owner_team"],
                               "status": "DEMO DATA ONLY", "tables": tables}
        out["masked"] = ws.masked_for(db, acc)
    ws.log(db, cu.actor, acc, res, "OPEN", True, "Opened simulated workspace")
    db.commit()
    return out


@router.get("/{resource_id}/records")
def records(resource_id: str, table: str | None = None, q: str | None = Query(None, max_length=80),
            sort: str | None = None, dir: str = Query("asc", pattern="^(asc|desc)$"),
            page: int = Query(1, ge=1, le=1000), size: int = Query(10, ge=5, le=50),
            cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = _access(db, cu, resource_id, "READ", "READ")
    out = _run(db, cu, acc, "READ", lambda: ws.browse(db, acc, ws.check_table(acc.resource, table), q, sort, dir == "desc", page, size))
    db.commit()
    return out


@router.get("/{resource_id}/stats")
def stats(resource_id: str, table: str | None = None, cu: CurrentUser = Depends(get_current_user),
          db: Session = Depends(get_db)):
    acc = _access(db, cu, resource_id, "READ", "READ")
    out = _run(db, cu, acc, "READ", lambda: ws.table_stats(db, acc, ws.check_table(acc.resource, table)))
    db.commit()
    return out


class RecordIn(BaseModel):
    table: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


@router.post("/{resource_id}/records", status_code=201)
def add_record(resource_id: str, body: RecordIn, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = _access(db, cu, resource_id, "WRITE", "WRITE")
    table = _run(db, cu, acc, "WRITE", lambda: ws.check_table(acc.resource, body.table))
    r = _run(db, cu, acc, "WRITE", lambda: ws.add_record(db, acc, cu.user, table, body.values))
    ws.log(db, cu.actor, acc, acc.resource, "WRITE", True, f"Added synthetic record {r.record_key}",
           {"table": table, "record": r.record_key, "values": r.data})
    db.commit()
    return ws.row_out(r, cat.TABLES[table]["columns"], ws.masked_for(db, acc))


@router.patch("/{resource_id}/records/{record_id}")
def edit_record(resource_id: str, record_id: str, body: RecordIn, cu: CurrentUser = Depends(get_current_user),
                db: Session = Depends(get_db)):
    acc = _access(db, cu, resource_id, "WRITE", "WRITE")
    table = _run(db, cu, acc, "WRITE", lambda: ws.check_table(acc.resource, body.table))
    r, prev = _run(db, cu, acc, "WRITE", lambda: ws.edit_record(db, acc, cu.user, table, record_id, body.values))
    ws.log(db, cu.actor, acc, acc.resource, "WRITE", True, f"Edited synthetic record {r.record_key}",
           {"table": table, "record": r.record_key, "before": prev, "after": {k: r.data.get(k) for k in prev}})
    db.commit()
    return ws.row_out(r, cat.TABLES[table]["columns"], ws.masked_for(db, acc))


@router.delete("/{resource_id}/records/{record_id}")
def delete_record(resource_id: str, record_id: str, table: str | None = None,
                  cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = _access(db, cu, resource_id, "DELETE", "DELETE")
    t = _run(db, cu, acc, "DELETE", lambda: ws.check_table(acc.resource, table))
    r = _run(db, cu, acc, "DELETE", lambda: ws.delete_record(db, acc, t, record_id))
    ws.log(db, cu.actor, acc, acc.resource, "DELETE", True, f"Deleted synthetic record {r.record_key}",
           {"table": t, "record": r.record_key})
    db.commit()
    return {"deleted": r.record_key}


class FilterIn(BaseModel):
    column: str
    op: str
    value: Any = None


class QueryIn(BaseModel):
    table: str | None = None
    filters: list[FilterIn] = Field(default_factory=list, max_length=5)
    group_by: str | None = None
    metric: str = "count"
    metric_column: str | None = None
    limit: int = Field(20, ge=1, le=50)


@router.post("/{resource_id}/query")
def query(resource_id: str, body: QueryIn, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = _access(db, cu, resource_id, "EXECUTE", "EXECUTE")
    if cat.kind_for(acc.resource.code) == "MODEL":
        raise HTTPException(404, {"code": "NOT_A_DATASET", "message": "Use the prediction playground for models."})
    table = _run(db, cu, acc, "EXECUTE", lambda: ws.check_table(acc.resource, body.table))
    out = _run(db, cu, acc, "EXECUTE", lambda: ws.run_query(db, acc, table, [f.model_dump() for f in body.filters],
                                                            body.group_by, body.metric, body.metric_column, body.limit))
    ws.log(db, cu.actor, acc, acc.resource, "EXECUTE", True, "Ran simulated query", {"sql": out["sql"]})
    db.commit()
    return out


class PredictIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


@router.post("/{resource_id}/predict")
def predict(resource_id: str, body: PredictIn, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = _access(db, cu, resource_id, "EXECUTE", "EXECUTE")
    if cat.kind_for(acc.resource.code) != "MODEL":
        raise HTTPException(404, {"code": "NOT_A_MODEL", "message": "Only models have a prediction playground."})
    out = _run(db, cu, acc, "EXECUTE", lambda: ws.predict(db, acc.resource, body.values))
    ws.log(db, cu.actor, acc, acc.resource, "EXECUTE", True, "Ran simulated prediction",
           {"inputs": out["inputs"], "result": out["predicted_class"]})
    db.commit()
    return out


class MetadataIn(BaseModel):
    description: str | None = Field(None, min_length=5, max_length=600)
    monitoring_notes: str | None = Field(None, max_length=600)
    decision_threshold: float | None = Field(None, ge=0.05, le=0.95)


@router.patch("/{resource_id}/metadata")
def edit_metadata(resource_id: str, body: MetadataIn, cu: CurrentUser = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    acc = _access(db, cu, resource_id, "WRITE", "WRITE")
    if cat.kind_for(acc.resource.code) != "MODEL":
        raise HTTPException(404, {"code": "NOT_A_MODEL", "message": "Metadata editing is for models."})
    changes = body.model_dump(exclude_none=True)
    if "decision_threshold" in changes and cat.MODELS[acc.resource.code]["default_threshold"] is None:
        raise HTTPException(422, {"code": "INVALID_FIELD", "message": "This model has no decision threshold."})
    if not changes:
        raise HTTPException(422, {"code": "NO_CHANGES", "message": "Nothing to change."})
    before = {k: v for k, v in ws.model_meta(db, acc.resource).items() if k in changes}
    ws.save_settings(db, acc.resource, cu.user, {**changes, "edited_at": utcnow().isoformat(), "edited_by": cu.user.full_name})
    ws.log(db, cu.actor, acc, acc.resource, "WRITE", True, "Edited simulated model metadata", {"before": before, "after": changes})
    db.commit()
    return ws.model_meta(db, acc.resource)


@router.get("/{resource_id}/admin")
def admin_panel(resource_id: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """ADMIN holders see who holds access and recent workspace activity. Revoking stays with the Manager and
    Security Manager under the existing policy."""
    acc = _access(db, cu, resource_id, "ADMIN", "ADMIN")
    res = acc.resource
    grants = db.execute(select(AccessGrant).where(AccessGrant.resource_id == res.id, AccessGrant.status == "ACTIVE")
                        .order_by(AccessGrant.granted_at.desc())).scalars().all()
    events = db.execute(select(AuditEvent).where(AuditEvent.resource_id == res.id,
                                                 AuditEvent.action.in_(["WORKSPACE_ACTION_ALLOWED", "WORKSPACE_ACTION_DENIED"]))
                        .order_by(AuditEvent.occurred_at.desc()).limit(25)).scalars().all()
    s = ws.settings(db, res)
    ws.log(db, cu.actor, acc, res, "ADMIN", True, "Viewed workspace administration")
    db.commit()
    return {
        "holders": [{"user": user_brief(g.user), "permissions": g.permissions, "purpose_label": purpose_label(g.purpose),
                     "expires_at": g.expires_at, "granted_at": g.granted_at} for g in grants],
        "activity": [{"at": e.occurred_at, "actor": e.actor_name, "allowed": e.action == "WORKSPACE_ACTION_ALLOWED",
                      "action": (e.new_state or {}).get("action"), "reason": e.reason} for e in events],
        "settings": {"mask_identifiers": bool(s.get("mask_identifiers")), "inference_logging": s.get("inference_logging", True)},
        "settings_apply": "MODEL" if cat.kind_for(res.code) == "MODEL" else "DATA",
        "policy_note": "Revoking or narrowing access stays with the employee's Manager and the Security Manager.",
    }


class SettingsIn(BaseModel):
    mask_identifiers: bool | None = None
    inference_logging: bool | None = None


@router.patch("/{resource_id}/settings")
def admin_settings(resource_id: str, body: SettingsIn, cu: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    acc = _access(db, cu, resource_id, "ADMIN", "ADMIN")
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, {"code": "NO_CHANGES", "message": "Nothing to change."})
    before = {k: ws.settings(db, acc.resource).get(k) for k in changes}
    s = ws.save_settings(db, acc.resource, cu.user, changes)
    ws.log(db, cu.actor, acc, acc.resource, "ADMIN", True, "Changed simulated workspace settings",
           {"before": before, "after": changes})
    db.commit()
    return {"mask_identifiers": bool(s.get("mask_identifiers")), "inference_logging": s.get("inference_logging", True)}
