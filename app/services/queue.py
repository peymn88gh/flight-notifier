from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def enqueue_alert(alert_id: str) -> None:
    try:
        from app.worker.tasks import process_alert

        process_alert.delay(alert_id)
    except Exception:
        logger.exception(
            "Could not enqueue alert %s; the due-alert scheduler will retry it",
            alert_id,
        )
