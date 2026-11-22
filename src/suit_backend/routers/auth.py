import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from suit_backend.config import get_settings
from suit_backend.deps import CurrentUser, DBSession
from suit_backend.models import BootstrapGuard, Invitation, Organization, Role, User
from suit_backend.schemas import (
    BootstrapRequest,
    InvitationAccept,
    LoginRequest,
    MeResponse,
    PasswordChange,
    TokenResponse,
)
from suit_backend.security import (
    create_access_token,
    hash_one_time_token,
    hash_password,
    normalize_email,
    password_policy_error,
    verify_and_update_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
DUMMY_HASH = hash_password("not-a-real-password-used-for-timing")


@router.post("/bootstrap", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def bootstrap(
    payload: BootstrapRequest,
    db: DBSession,
    bootstrap_token: str | None = Header(default=None, alias="X-Bootstrap-Token"),
) -> TokenResponse:
    settings = get_settings()
    if not settings.bootstrap_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    expected = settings.bootstrap_token.get_secret_value() if settings.bootstrap_token else ""
    if expected and not secrets.compare_digest(bootstrap_token or "", expected):
        raise HTTPException(status_code=403, detail="Bootstrap authorization failed")
    if db.scalar(select(func.count()).select_from(User)):
        raise HTTPException(status_code=409, detail="Bootstrap has already been completed")
    guard = BootstrapGuard(id=1)
    organization = Organization(name=payload.organization_name)
    user = User(
        organization=organization,
        email=normalize_email(str(payload.email)),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=Role.ADMIN,
    )
    db.add_all([guard, organization, user])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Bootstrap could not be completed") from None
    db.refresh(user)
    token, expires_in = create_access_token(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role.value,
        auth_version=user.auth_version,
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DBSession) -> TokenResponse:
    email = normalize_email(str(payload.email))
    user = db.scalar(select(User).where(User.email == email))
    encoded = user.password_hash if user else DUMMY_HASH
    valid, updated_hash = verify_and_update_password(payload.password, encoded)
    if user is None or not valid or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if updated_hash:
        user.password_hash = updated_hash
        db.commit()
    token, expires_in = create_access_token(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role.value,
        auth_version=user.auth_version,
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=MeResponse)
def me(current_user: CurrentUser) -> User:
    return current_user


@router.post("/invitations/accept", response_model=TokenResponse, status_code=201)
def accept_invitation(payload: InvitationAccept, db: DBSession) -> TokenResponse:
    token_hash = hash_one_time_token(payload.token)
    invitation = db.scalar(
        select(Invitation).where(
            Invitation.token_hash == token_hash,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > datetime.now(UTC),
        )
    )
    if invitation is None:
        raise HTTPException(status_code=400, detail="Invitation is invalid or expired")
    if error := password_policy_error(payload.password, invitation.email):
        raise HTTPException(status_code=422, detail=error)
    user = User(
        organization_id=invitation.organization_id,
        email=invitation.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=invitation.role,
    )
    invitation.accepted_at = datetime.now(UTC)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered") from None
    db.refresh(user)
    token, expires_in = create_access_token(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role.value,
        auth_version=user.auth_version,
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/password/change", status_code=204)
def change_password(
    payload: PasswordChange, current_user: CurrentUser, db: DBSession
) -> None:
    valid, _ = verify_and_update_password(payload.current_password, current_user.password_hash)
    if not valid:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if error := password_policy_error(payload.new_password, current_user.email):
        raise HTTPException(status_code=422, detail=error)
    current_user.password_hash = hash_password(payload.new_password)
    current_user.auth_version += 1
    db.commit()


@router.post("/logout", status_code=204)
def logout(current_user: CurrentUser, db: DBSession) -> None:
    current_user.auth_version += 1
    db.commit()

