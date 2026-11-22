import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from suit_backend.deps import AdminUser, DBSession
from suit_backend.models import AuditLog, Invitation, Phrase, Role, Scenario, User
from suit_backend.schemas import (
    AuditResponse,
    InvitationCreate,
    InvitationCreated,
    PhraseCreate,
    PhraseResponse,
    PhraseUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from suit_backend.security import hash_one_time_token, hash_password, normalize_email
from suit_backend.services import audit

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/invitations", response_model=InvitationCreated, status_code=201)
def create_invitation(
    payload: InvitationCreate, admin: AdminUser, db: DBSession
) -> InvitationCreated:
    email = normalize_email(str(payload.email))
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email is already registered")
    if db.scalar(
        select(Invitation.id).where(
            Invitation.organization_id == admin.organization_id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > datetime.now(UTC),
        )
    ):
        raise HTTPException(status_code=409, detail="An active invitation already exists")
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(
        organization_id=admin.organization_id,
        email=email,
        role=payload.role,
        token_hash=hash_one_time_token(raw_token),
        created_by_id=admin.id,
        expires_at=datetime.now(UTC) + timedelta(hours=payload.expires_hours),
    )
    db.add(invitation)
    db.flush()
    audit(
        db,
        actor=admin,
        action="invitation.create",
        resource_type="invitation",
        resource_id=invitation.id,
        metadata={"role": invitation.role.value},
    )
    db.commit()
    db.refresh(invitation)
    return InvitationCreated(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        token=raw_token,
    )


@router.get("/users", response_model=list[UserResponse])
def list_users(admin: AdminUser, db: DBSession) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.organization_id == admin.organization_id)
            .order_by(User.created_at)
        )
    )


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
def create_user(payload: UserCreate, admin: AdminUser, db: DBSession) -> User:
    user = User(
        organization_id=admin.organization_id,
        email=normalize_email(str(payload.email)),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered") from None
    audit(
        db,
        actor=admin,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        metadata={"role": user.role.value},
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: str, payload: UserUpdate, admin: AdminUser, db: DBSession) -> User:
    user = db.scalar(
        select(User).where(User.id == user_id, User.organization_id == admin.organization_id)
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and payload.is_active is False:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own account")
    changes = payload.model_dump(exclude_none=True)
    removes_admin = user.role.value == "admin" and (
        changes.get("is_active") is False
        or (changes.get("role") is not None and changes["role"].value != "admin")
    )
    if removes_admin:
        other_admins = db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.organization_id == admin.organization_id,
                User.role == Role.ADMIN,
                User.is_active.is_(True),
                User.id != user.id,
            )
        )
        if not other_admins:
            raise HTTPException(
                status_code=409,
                detail="At least one active administrator is required",
            )
    for key, value in changes.items():
        setattr(user, key, value)
    if "role" in changes or "is_active" in changes:
        user.auth_version += 1
    audit(
        db,
        actor=admin,
        action="user.update",
        resource_type="user",
        resource_id=user.id,
        metadata={
            key: value.value if hasattr(value, "value") else value
            for key, value in changes.items()
        },
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/phrases", response_model=PhraseResponse, status_code=status.HTTP_201_CREATED)
def create_phrase(payload: PhraseCreate, admin: AdminUser, db: DBSession) -> Phrase:
    if db.get(Scenario, payload.scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    phrase = Phrase(organization_id=admin.organization_id, **payload.model_dump())
    db.add(phrase)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phrase already exists") from None
    audit(
        db,
        actor=admin,
        action="phrase.create",
        resource_type="phrase",
        resource_id=phrase.id,
        metadata={"scenario_id": phrase.scenario_id},
    )
    db.commit()
    db.refresh(phrase)
    return phrase


def get_owned_phrase(db: DBSession, admin: User, phrase_id: str) -> Phrase:
    phrase = db.scalar(
        select(Phrase).where(
            Phrase.id == phrase_id,
            Phrase.organization_id == admin.organization_id,
        )
    )
    if phrase is None:
        raise HTTPException(status_code=404, detail="Phrase not found")
    return phrase


@router.patch("/phrases/{phrase_id}", response_model=PhraseResponse)
def update_phrase(
    phrase_id: str, payload: PhraseUpdate, admin: AdminUser, db: DBSession
) -> Phrase:
    phrase = get_owned_phrase(db, admin, phrase_id)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(phrase, key, value)
    audit(
        db,
        actor=admin,
        action="phrase.update",
        resource_type="phrase",
        resource_id=phrase.id,
        metadata={"scenario_id": phrase.scenario_id},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phrase already exists") from None
    db.refresh(phrase)
    return phrase


@router.delete("/phrases/{phrase_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_phrase(phrase_id: str, admin: AdminUser, db: DBSession) -> Response:
    phrase = get_owned_phrase(db, admin, phrase_id)
    audit(
        db,
        actor=admin,
        action="phrase.delete",
        resource_type="phrase",
        resource_id=phrase.id,
        metadata={"scenario_id": phrase.scenario_id},
    )
    db.delete(phrase)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/audit-logs", response_model=list[AuditResponse])
def list_audit_logs(
    admin: AdminUser,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == admin.organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
