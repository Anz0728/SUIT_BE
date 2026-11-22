from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from suit_backend.deps import CurrentUser, DBSession
from suit_backend.models import Organization, Role, User
from suit_backend.schemas import (
    BootstrapRequest,
    LoginRequest,
    MeResponse,
    TokenResponse,
)
from suit_backend.security import (
    create_access_token,
    hash_password,
    normalize_email,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
DUMMY_HASH = hash_password("not-a-real-password-used-for-timing")


@router.post("/bootstrap", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def bootstrap(payload: BootstrapRequest, db: DBSession) -> TokenResponse:
    if db.scalar(select(func.count()).select_from(User)):
        raise HTTPException(status_code=409, detail="Bootstrap has already been completed")
    organization = Organization(name=payload.organization_name)
    user = User(
        organization=organization,
        email=normalize_email(str(payload.email)),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=Role.ADMIN,
    )
    db.add_all([organization, user])
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
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DBSession) -> TokenResponse:
    email = normalize_email(str(payload.email))
    user = db.scalar(select(User).where(User.email == email))
    encoded = user.password_hash if user else DUMMY_HASH
    valid = verify_password(payload.password, encoded)
    if user is None or not valid or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires_in = create_access_token(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role.value,
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=MeResponse)
def me(current_user: CurrentUser) -> User:
    return current_user

