import base64
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from suit_backend.deps import CurrentUser, DBSession
from suit_backend.models import (
    Conversation,
    ConversationStatus,
    Message,
    Retention,
    Role,
    Scenario,
)
from suit_backend.schemas import (
    ConversationCreate,
    ConversationList,
    ConversationResponse,
    ConversationUpdate,
    MessageCreate,
    MessageResponse,
    MessageUpdate,
    PageInfo,
)
from suit_backend.services import (
    add_idempotency_record,
    audit,
    find_idempotency_record,
    organization_retention,
    payload_hash,
    retention_expiry,
    validate_idempotency_key,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_conversation(db: DBSession, current_user, conversation_id: str) -> Conversation:
    now = datetime.now(UTC)
    statement = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(
            Conversation.id == conversation_id,
            Conversation.organization_id == current_user.organization_id,
            or_(Conversation.expires_at.is_(None), Conversation.expires_at > now),
        )
    )
    if current_user.role != Role.ADMIN:
        statement = statement.where(Conversation.created_by_id == current_user.id)
    conversation = db.scalar(statement)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def may_modify(current_user, conversation: Conversation) -> None:
    if current_user.role != Role.ADMIN and conversation.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Conversation access denied")


def parse_idempotency_key(key: str | None) -> str | None:
    try:
        return validate_idempotency_key(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def encode_cursor(conversation: Conversation) -> str:
    raw = json.dumps(
        {"updated_at": conversation.updated_at.isoformat(), "id": conversation.id},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
        timestamp = datetime.fromisoformat(data["updated_at"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        resource_id = str(data["id"])
        if not resource_id:
            raise ValueError
        return timestamp, resource_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc


def scoped_query(current_user) -> Select:
    statement = select(Conversation).where(
        Conversation.organization_id == current_user.organization_id,
        or_(Conversation.expires_at.is_(None), Conversation.expires_at > datetime.now(UTC)),
    )
    if current_user.role != Role.ADMIN:
        statement = statement.where(Conversation.created_by_id == current_user.id)
    return statement


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate,
    current_user: CurrentUser,
    db: DBSession,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Conversation:
    key = parse_idempotency_key(idempotency_key)
    digest = payload_hash(payload)
    operation = "conversation.create"
    if key:
        record = find_idempotency_record(db, actor=current_user, operation=operation, key=key)
        if record:
            if record.request_hash != digest:
                raise HTTPException(status_code=409, detail="Idempotency-Key was reused")
            return get_conversation(db, current_user, record.resource_id)

    scenario = db.get(Scenario, payload.scenario_id)
    if scenario is None or not scenario.is_active:
        raise HTTPException(status_code=404, detail="Scenario not found")
    retention = payload.retention or organization_retention(db, current_user.organization_id)
    conversation = Conversation(
        organization_id=current_user.organization_id,
        created_by_id=current_user.id,
        scenario_id=payload.scenario_id,
        retention=retention,
        expires_at=retention_expiry(retention),
    )
    db.add(conversation)
    db.flush()
    audit(
        db,
        actor=current_user,
        action="conversation.create",
        resource_type="conversation",
        resource_id=conversation.id,
        metadata={"scenario_id": conversation.scenario_id, "retention": retention.value},
    )
    if key:
        add_idempotency_record(
            db,
            actor=current_user,
            operation=operation,
            key=key,
            request_hash=digest,
            resource_type="conversation",
            resource_id=conversation.id,
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if key:
            record = find_idempotency_record(
                db, actor=current_user, operation=operation, key=key
            )
            if record and record.request_hash == digest:
                return get_conversation(db, current_user, record.resource_id)
        raise HTTPException(status_code=409, detail="Request could not be committed") from None
    db.refresh(conversation)
    return conversation


@router.get("", response_model=ConversationList)
def list_conversations(
    current_user: CurrentUser,
    db: DBSession,
    scenario_id: str | None = Query(default=None, max_length=40),
    bookmarked: bool | None = None,
    conversation_status: Annotated[
        ConversationStatus | None, Query(alias="status")
    ] = None,
    query: str | None = Query(default=None, min_length=1, max_length=100),
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    cursor: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int | None = Query(default=None, ge=0),
) -> ConversationList:
    statement = scoped_query(current_user)
    if scenario_id:
        statement = statement.where(Conversation.scenario_id == scenario_id)
    if bookmarked is not None:
        statement = statement.where(Conversation.bookmarked == bookmarked)
    if conversation_status is not None:
        statement = statement.where(Conversation.status == conversation_status)
    if from_at is not None:
        statement = statement.where(Conversation.updated_at >= from_at)
    if to_at is not None:
        statement = statement.where(Conversation.updated_at <= to_at)
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.join(Message).where(
            or_(Message.text.ilike(pattern), Message.english.ilike(pattern))
        )

    count_source = statement.with_only_columns(Conversation.id).distinct().subquery()
    total = int(db.scalar(select(func.count()).select_from(count_source)) or 0)
    if cursor:
        if offset:
            raise HTTPException(status_code=400, detail="cursor and offset cannot be combined")
        cursor_time, cursor_id = decode_cursor(cursor)
        statement = statement.where(
            or_(
                Conversation.updated_at < cursor_time,
                (Conversation.updated_at == cursor_time) & (Conversation.id < cursor_id),
            )
        )

    statement = (
        statement.distinct()
        .options(selectinload(Conversation.messages))
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(limit + 1)
    )
    if offset is not None:
        statement = statement.offset(offset)
    rows = list(db.scalars(statement))
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_cursor(items[-1]) if has_more and items else None
    return ConversationList(
        items=items,
        page=PageInfo(
            limit=limit,
            count=len(items),
            total=total,
            next_cursor=next_cursor,
            offset=offset,
        ),
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
def read_conversation(
    conversation_id: str, current_user: CurrentUser, db: DBSession
) -> Conversation:
    return get_conversation(db, current_user, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationResponse)
def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    current_user: CurrentUser,
    db: DBSession,
) -> Conversation:
    conversation = get_conversation(db, current_user, conversation_id)
    may_modify(current_user, conversation)
    changes = payload.model_dump(exclude_none=True)
    if "retention" in changes:
        conversation.retention = changes["retention"]
        conversation.expires_at = retention_expiry(changes["retention"])
    if "bookmarked" in changes:
        conversation.bookmarked = changes["bookmarked"]
    audit(
        db,
        actor=current_user,
        action="conversation.update",
        resource_type="conversation",
        resource_id=conversation.id,
        metadata={
            key: value.value if hasattr(value, "value") else value
            for key, value in changes.items()
        },
    )
    db.commit()
    db.refresh(conversation)
    return conversation


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_message(
    conversation_id: str,
    payload: MessageCreate,
    current_user: CurrentUser,
    db: DBSession,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Message:
    conversation = get_conversation(db, current_user, conversation_id)
    may_modify(current_user, conversation)
    if conversation.status != ConversationStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Conversation is closed")
    key = parse_idempotency_key(idempotency_key)
    digest = payload_hash(payload)
    operation = f"message.create:{conversation.id}"
    if key:
        record = find_idempotency_record(db, actor=current_user, operation=operation, key=key)
        if record:
            if record.request_hash != digest:
                raise HTTPException(status_code=409, detail="Idempotency-Key was reused")
            message = db.get(Message, record.resource_id)
            if message is None:
                raise HTTPException(status_code=409, detail="Original idempotent resource expired")
            return message

    message = Message(conversation_id=conversation.id, **payload.model_dump())
    db.add(message)
    conversation.updated_at = datetime.now(UTC)
    db.flush()
    audit(
        db,
        actor=current_user,
        action="message.create",
        resource_type="message",
        resource_id=message.id,
        metadata={"conversation_id": conversation.id, "mode": message.mode.value},
    )
    if key:
        add_idempotency_record(
            db,
            actor=current_user,
            operation=operation,
            key=key,
            request_hash=digest,
            resource_type="message",
            resource_id=message.id,
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if key:
            record = find_idempotency_record(
                db, actor=current_user, operation=operation, key=key
            )
            if record and record.request_hash == digest:
                existing = db.get(Message, record.resource_id)
                if existing:
                    return existing
        raise HTTPException(status_code=409, detail="Request could not be committed") from None
    db.refresh(message)
    return message


@router.patch("/{conversation_id}/messages/{message_id}", response_model=MessageResponse)
def update_message(
    conversation_id: str,
    message_id: str,
    payload: MessageUpdate,
    current_user: CurrentUser,
    db: DBSession,
) -> Message:
    conversation = get_conversation(db, current_user, conversation_id)
    may_modify(current_user, conversation)
    message = db.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation.id,
        )
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    message.text = payload.text
    message.english = payload.english
    message.edited = True
    conversation.updated_at = datetime.now(UTC)
    audit(
        db,
        actor=current_user,
        action="message.update",
        resource_type="message",
        resource_id=message.id,
        metadata={"conversation_id": conversation.id},
    )
    db.commit()
    db.refresh(message)
    return message


@router.post("/{conversation_id}/close", response_model=ConversationResponse | None)
def close_conversation(
    conversation_id: str, current_user: CurrentUser, db: DBSession
) -> Conversation | None:
    conversation = get_conversation(db, current_user, conversation_id)
    may_modify(current_user, conversation)
    audit(
        db,
        actor=current_user,
        action="conversation.close",
        resource_type="conversation",
        resource_id=conversation.id,
        metadata={"retention": conversation.retention.value},
    )
    if conversation.retention == Retention.NONE:
        db.delete(conversation)
        db.commit()
        return None
    conversation.status = ConversationStatus.CLOSED
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str, current_user: CurrentUser, db: DBSession
) -> Response:
    conversation = get_conversation(db, current_user, conversation_id)
    may_modify(current_user, conversation)
    audit(
        db,
        actor=current_user,
        action="conversation.delete",
        resource_type="conversation",
        resource_id=conversation.id,
    )
    db.delete(conversation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
