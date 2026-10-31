"""Celery worker + beat schedule (docker compose services `worker` and `beat`)."""
from celery import Celery

from app.core.config import get_settings

celery_app = Celery("astitva", broker=get_settings().redis_url, backend=get_settings().redis_url)
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "expire-grants-every-minute": {"task": "astitva.expire", "schedule": 60.0},
    "recertification-hourly": {"task": "astitva.recert", "schedule": 3600.0},
    "drift-scan-every-6h": {"task": "astitva.drift", "schedule": 6 * 3600.0},
}


@celery_app.task(name="astitva.expire")
def expire_task():
    from app.services.maintenance import expire_and_warn

    return expire_and_warn()


@celery_app.task(name="astitva.recert")
def recert_task():
    from app.services.maintenance import recertification

    return recertification()


@celery_app.task(name="astitva.drift")
def drift_task():
    from app.services.maintenance import drift_scan

    return drift_scan()
