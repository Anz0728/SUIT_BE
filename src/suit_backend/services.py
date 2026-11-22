import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .models import AuditLog, Conversation, Retention, User


def retention_expiry(retention: Retention, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(UTC)
    if retention == Retention.NONE:
        return now + timedelta(hours=2)
    if retention == Retention.HOURS_24:
        return now + timedelta(hours=24)
    if retention == Retention.DAYS_7:
        return now + timedelta(days=7)
    return None


def cleanup_expired(db: Session) -> int:
    now = datetime.now(UTC)
    result = db.execute(
        delete(Conversation).where(
            Conversation.expires_at.is_not(None), Conversation.expires_at <= now
        )
    )
    db.commit()
    return int(result.rowcount or 0)


def audit(
    db: Session,
    *,
    actor: User,
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: dict[str, str | bool | int] | None = None,
) -> None:
    # Never put conversation text, tokens, credentials, audio, or video in audit metadata.
    entry = AuditLog(
        organization_id=actor.organization_id,
        actor_id=actor.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
    )
    db.add(entry)

