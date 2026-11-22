import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    AuditLog,
    Conversation,
    IdempotencyRecord,
    Invitation,
    OrganizationSetting,
    Retention,
    User,
)

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


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


def cleanup_maintenance(db: Session) -> dict[str, int]:
    """Remove expired sensitive data and stale replay-protection records."""
    now = datetime.now(UTC)
    conversations = db.execute(
        delete(Conversation).where(
            Conversation.expires_at.is_not(None), Conversation.expires_at <= now
        )
    )
    idempotency = db.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.created_at <= now - timedelta(hours=24)
        )
    )
    invitations = db.execute(
        delete(Invitation).where(
            Invitation.expires_at <= now - timedelta(days=7),
            Invitation.accepted_at.is_(None),
        )
    )
    db.commit()
    return {
        "conversations": int(conversations.rowcount or 0),
        "idempotency_records": int(idempotency.rowcount or 0),
        "invitations": int(invitations.rowcount or 0),
    }


def organization_retention(db: Session, organization_id: str) -> Retention:
    setting = db.get(OrganizationSetting, organization_id)
    return setting.default_retention if setting else Retention.HOURS_24


def payload_hash(payload: BaseModel) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def validate_idempotency_key(key: str | None) -> str | None:
    if key is None:
        return None
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "Idempotency-Key must be 8-128 characters using letters, numbers, '.', '_', ':' or '-'"
        )
    return key


def find_idempotency_record(
    db: Session,
    *,
    actor: User,
    operation: str,
    key: str,
) -> IdempotencyRecord | None:
    return db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.organization_id == actor.organization_id,
            IdempotencyRecord.user_id == actor.id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.idempotency_key == key,
        )
    )


def add_idempotency_record(
    db: Session,
    *,
    actor: User,
    operation: str,
    key: str,
    request_hash: str,
    resource_type: str,
    resource_id: str,
) -> None:
    db.add(
        IdempotencyRecord(
            organization_id=actor.organization_id,
            user_id=actor.id,
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )


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

