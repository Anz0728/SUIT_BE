from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import or_, select
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
from suit_backend.services import audit, cleanup_expired, retention_expiry

router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_conversation(db: DBSession, current_user, conversation_id: str) -> Conversation:
    now = datetime.now(UTC)
    query = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(
            Conversation.id == conversation_id,
            Conversation.organization_id == current_user.organization_id,
            or_(Conversation.expires_at.is_(None), Conversation.expires_at > now),
        )
    )
    if current_user.role != Role.ADMIN:
        query = query.where(Conversation.created_by_id == current_user.id)
    conversation = db.scalar(query)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def may_modify(current_user, conversation: Conversation) -> None:
    if current_user.role != Role.ADMIN and conversation.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Conversation access denied")


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate, current_user: CurrentUser, db: DBSession
) -> Conversation:
    cleanup_expired(db)
    scenario = db.get(Scenario, payload.scenario_id)
    if scenario is None or not scenario.is_active:
        raise HTTPException(status_code=404, detail="Scenario not found")
    conversation = Conversation(
        organization_id=current_user.organization_id,
        created_by_id=current_user.id,
        scenario_id=payload.scenario_id,
        retention=payload.retention,
        expires_at=retention_expiry(payload.retention),
    )
    db.add(conversation)
    db.flush()
    audit(
        db,
        actor=current_user,
        action="conversation.create",
        resource_type="conversation",
        resource_id=conversation.id,
        metadata={"scenario_id": conversation.scenario_id, "retention": payload.retention.value},
    )
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("", response_model=ConversationList)
def list_conversations(
    current_user: CurrentUser,
    db: DBSession,
    scenario_id: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ConversationList:
    cleanup_expired(db)
    query = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.organization_id == current_user.organization_id)
    )
    if current_user.role != Role.ADMIN:
        query = query.where(Conversation.created_by_id == current_user.id)
    if scenario_id:
        query = query.where(Conversation.scenario_id == scenario_id)
    items = list(
        db.scalars(query.order_by(Conversation.updated_at.desc()).limit(limit).offset(offset))
    )
    return ConversationList(
        items=items,
        page=PageInfo(limit=limit, offset=offset, count=len(items)),
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
            key: value.value if hasattr(value, "value") else value for key, value in changes.items()
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
) -> Message:
    conversation = get_conversation(db, current_user, conversation_id)
    may_modify(current_user, conversation)
    if conversation.status != ConversationStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Conversation is closed")
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
    db.commit()
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

