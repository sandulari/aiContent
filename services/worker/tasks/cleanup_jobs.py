"""Periodic reaper for the ``jobs`` table.

Tasks already update their job rows to ``'success'`` / ``'failed'`` in
their own except branches, but those handlers can't run if the worker
process is SIGKILLed mid-task (OOM, redeploy, host reboot). The row
then stays ``'running'`` forever and skews dashboards / monitoring.

This task sweeps every ~30 min and marks any row that's been ``running``
longer than the longest legitimate task could plausibly take. Acts only
on the ``jobs`` table — scheduled_reels has its own cleanup_stuck_processing.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from celery_app import app
from lib.db import get_session

logger = logging.getLogger(__name__)


# 1 hour is well above the longest real task we run (deep_discovery
# tops out at ~10–15 min). Anything older is dead.
_STUCK_THRESHOLD = "1 hour"


@app.task(name="tasks.cleanup_jobs.reap_stuck_jobs")
def reap_stuck_jobs():
    """Mark jobs.running rows older than the threshold as failed."""
    with get_session() as session:
        result = session.execute(
            text(
                f"""
                UPDATE jobs
                SET status = 'failed',
                    finished_at = :now,
                    logs = jsonb_build_object(
                        'error',
                        'reaped: stuck in running for >{_STUCK_THRESHOLD}, worker likely SIGKILLed'
                    )
                WHERE status = 'running'
                  AND started_at < NOW() - INTERVAL '{_STUCK_THRESHOLD}'
                RETURNING id, job_type
                """
            ),
            {"now": datetime.now(timezone.utc)},
        )
        rows = result.fetchall()

    if rows:
        by_type: dict[str, int] = {}
        for r in rows:
            by_type[r.job_type] = by_type.get(r.job_type, 0) + 1
        logger.warning(
            "reap_stuck_jobs: marked %d row(s) failed: %s", len(rows), by_type
        )
    return {"reaped": len(rows)}
