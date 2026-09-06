"""arq cron jobs for the daily/weekly admin digest emails.

Both are operator-only (see ADMIN_DIGEST_EMAILS in example.env) — there's no
per-user consent or preference involved, so all of this stays server-side.

The daily digest combines DB usage stats with Axiom-derived system-health
stats (log volume by level, top errors) into one email; the weekly digest is
DB stats only over a 7-day window, deliberately a usage-trend rollup rather
than a duplicate of the daily operational-health email.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from src.db.session import SessionLocal
from src.db.models import User, Conversation, Message, SearchAnalytic, WaitlistEntry
from src.utils.email import send_daily_admin_digest_email, send_weekly_admin_digest_email

logger = logging.getLogger(__name__)


def _gather_db_stats(db, since: datetime) -> dict:
    """Counts for everything created at/after `since`. Shared by both
    digests — only the lookback window differs."""
    return {
        "new_users": db.query(User).filter(User.created_at >= since).count(),
        "new_conversations": db.query(Conversation).filter(Conversation.created_at >= since).count(),
        "messages_sent": db.query(Message).filter(
            Message.created_at >= since, Message.role == "user",
        ).count(),
        "fallback_triggered": db.query(SearchAnalytic).filter(
            SearchAnalytic.created_at >= since, SearchAnalytic.fallback_triggered == 1,
        ).count(),
        "waitlist_joined": db.query(WaitlistEntry).filter(WaitlistEntry.created_at >= since).count(),
    }


def _table_rows(table) -> list[dict]:
    """Zip an axiom_py Table's parallel fields/columns into row dicts —
    the raw shape isn't row-oriented (see axiom_py.query.result.Table)."""
    field_names = [f.name for f in table.fields]
    columns = table.columns or []
    rows = []
    for i in range(len(columns[0]) if columns else 0):
        rows.append({name: columns[col_idx][i] for col_idx, name in enumerate(field_names)})
    return rows


def _gather_axiom_stats(hours: int = 24) -> dict | None:
    """Log volume by level and the top error messages over the last `hours`
    hours. Returns None (not raises) if Axiom isn't configured or the query
    fails — the digest still sends without this section rather than never
    sending at all.

    Uses AXIOM_TOKEN_READ, a separate query-scoped token from the
    ingest-only AXIOM_TOKEN_WRITE that src/main.py's logging handler uses —
    Axiom tokens are scoped per-action, and the ingest token this app
    already had did not (and should not) also carry query access."""
    token = os.getenv("AXIOM_TOKEN_READ")
    dataset = os.getenv("AXIOM_DATASET")
    if not token or not dataset:
        return None

    try:
        import axiom_py
        client = axiom_py.Client(token=token)

        by_level_result = client.apl_query(
            f"['{dataset}'] | where _time > ago({hours}h) | summarize count=count() by levelname"
        )
        by_level = {
            row["levelname"]: row["count"]
            for table in (by_level_result.tables or [])
            for row in _table_rows(table)
        }

        top_errors_result = client.apl_query(
            f"['{dataset}'] | where _time > ago({hours}h) and levelname == 'ERROR' "
            "| summarize count=count() by msg | top 5 by count"
        )
        top_errors = [
            row for table in (top_errors_result.tables or []) for row in _table_rows(table)
        ]

        return {"by_level": by_level, "top_errors": top_errors}
    except Exception:
        logger.exception("[admin-digest] Axiom query failed")
        return None


def _render_axiom_section(axiom_stats: dict | None) -> str:
    """Build the pre-rendered HTML fragment for the daily template's
    Axiom section — str.format() has no conditionals, so the "not
    configured / query failed" case is decided here, not in the template."""
    if axiom_stats is None:
        return (
            '<p style="margin:0; color:#888888;">'
            "Axiom not configured, or the query failed — no system-health data available."
            "</p>"
        )

    by_level = axiom_stats.get("by_level") or {}
    if not by_level:
        rows = '<tr><td style="padding:4px 0; color:#888888;">No log activity.</td></tr>'
    else:
        rows = "".join(
            f'<tr><td style="padding:4px 0;">{level}</td>'
            f'<td align="right" style="padding:4px 0; font-weight:bold;">{count}</td></tr>'
            for level, count in sorted(by_level.items())
        )

    top_errors = axiom_stats.get("top_errors") or []
    if top_errors:
        error_lines = "".join(
            f'<li style="margin:0 0 4px 0;">({row.get("count")}) {row.get("msg")}</li>'
            for row in top_errors
        )
        errors_html = (
            '<p style="margin:16px 0 4px 0; font-weight:bold;">Top errors</p>'
            f'<ul style="margin:0; padding-left:20px;">{error_lines}</ul>'
        )
    else:
        errors_html = ""

    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>'
        f"{errors_html}"
    )


async def daily_admin_digest(ctx) -> None:
    """arq cron job — see src/worker.py's WorkerSettings.cron_jobs."""
    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        stats = _gather_db_stats(db, since)
    finally:
        db.close()

    axiom_stats = _gather_axiom_stats(hours=24)

    delivered = await send_daily_admin_digest_email({
        "date": datetime.now(timezone.utc).strftime("%B %d, %Y"),
        **stats,
        "axiom_section": _render_axiom_section(axiom_stats),
    })
    logger.info("[admin-digest] daily digest sent to %d recipient(s)", delivered)


async def weekly_admin_digest(ctx) -> None:
    """arq cron job — see src/worker.py's WorkerSettings.cron_jobs."""
    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        stats = _gather_db_stats(db, since)
        total_users = db.query(User).count()
    finally:
        db.close()

    delivered = await send_weekly_admin_digest_email({
        "date": datetime.now(timezone.utc).strftime("%B %d, %Y"),
        **stats,
        "total_users": total_users,
    })
    logger.info("[admin-digest] weekly digest sent to %d recipient(s)", delivered)
