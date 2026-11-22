from fastapi import APIRouter
from sqlalchemy.orm import Session

from suit_backend.deps import AdminUser, CurrentUser, DBSession
from suit_backend.models import OrganizationSetting, UserPreference
from suit_backend.schemas import (
    OrganizationSettingResponse,
    OrganizationSettingUpdate,
    UserPreferenceResponse,
    UserPreferenceUpdate,
)
from suit_backend.services import audit

router = APIRouter(tags=["settings"])


def get_or_create_preference(db: Session, user_id: str) -> UserPreference:
    preference = db.get(UserPreference, user_id)
    if preference is None:
        preference = UserPreference(user_id=user_id)
        db.add(preference)
        db.commit()
        db.refresh(preference)
    return preference


def get_or_create_organization_setting(
    db: Session, organization_id: str
) -> OrganizationSetting:
    setting = db.get(OrganizationSetting, organization_id)
    if setting is None:
        setting = OrganizationSetting(organization_id=organization_id)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


@router.get("/preferences", response_model=UserPreferenceResponse)
def read_preferences(current_user: CurrentUser, db: DBSession) -> UserPreference:
    return get_or_create_preference(db, current_user.id)


@router.patch("/preferences", response_model=UserPreferenceResponse)
def update_preferences(
    payload: UserPreferenceUpdate, current_user: CurrentUser, db: DBSession
) -> UserPreference:
    preference = get_or_create_preference(db, current_user.id)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(preference, key, value)
    db.commit()
    db.refresh(preference)
    return preference


@router.get("/admin/organization-settings", response_model=OrganizationSettingResponse)
def read_organization_settings(admin: AdminUser, db: DBSession) -> OrganizationSetting:
    return get_or_create_organization_setting(db, admin.organization_id)


@router.patch("/admin/organization-settings", response_model=OrganizationSettingResponse)
def update_organization_settings(
    payload: OrganizationSettingUpdate, admin: AdminUser, db: DBSession
) -> OrganizationSetting:
    setting = get_or_create_organization_setting(db, admin.organization_id)
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(setting, key, value)
    audit(
        db,
        actor=admin,
        action="organization_settings.update",
        resource_type="organization",
        resource_id=admin.organization_id,
        metadata={
            key: value.value if hasattr(value, "value") else value
            for key, value in changes.items()
        },
    )
    db.commit()
    db.refresh(setting)
    return setting
