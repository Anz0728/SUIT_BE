from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .models import ConversationStatus, MessageMode, Retention, Role
from .security import password_policy_error


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class HealthResponse(APIModel):
    status: str
    version: str


class BootstrapRequest(APIModel):
    organization_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def strong_password(self) -> Self:
        if error := password_policy_error(self.password, str(self.email)):
            raise ValueError(error)
        return self


class LoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class OrganizationResponse(APIModel):
    id: str
    name: str


class UserResponse(APIModel):
    id: str
    organization_id: str
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class MeResponse(UserResponse):
    organization: OrganizationResponse


class UserCreate(APIModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=12, max_length=128)
    role: Role = Role.STAFF

    @model_validator(mode="after")
    def strong_password(self) -> Self:
        if error := password_policy_error(self.password, str(self.email)):
            raise ValueError(error)
        return self


class UserUpdate(APIModel):
    role: Role | None = None
    is_active: bool | None = None


class InvitationCreate(APIModel):
    email: EmailStr
    role: Role = Role.STAFF
    expires_hours: int = Field(default=24, ge=1, le=168)


class InvitationCreated(APIModel):
    id: str
    email: EmailStr
    role: Role
    expires_at: datetime
    token: str


class InvitationAccept(APIModel):
    token: str = Field(min_length=32, max_length=256)
    full_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=12, max_length=128)


class PasswordChange(APIModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class UserPreferenceUpdate(APIModel):
    text_size: Literal["normal", "large", "extra"] | None = None
    language: Literal["ko", "en", "both"] | None = None
    speech: bool | None = None
    face_tracking: bool | None = None
    pose_tracking: bool | None = None
    spatial_tracking: bool | None = None
    confidence_alert: bool | None = None
    confidence_threshold: int | None = Field(default=None, ge=50, le=99)
    ksl_english: bool | None = None
    haptics: bool | None = None
    high_contrast: bool | None = None
    voice_tone: Literal["clear", "calm"] | None = None
    speech_rate: Literal[0.7, 0.9, 1.2] | None = None


class UserPreferenceResponse(APIModel):
    user_id: str
    text_size: str
    language: str
    speech: bool
    face_tracking: bool
    pose_tracking: bool
    spatial_tracking: bool
    confidence_alert: bool
    confidence_threshold: int
    ksl_english: bool
    haptics: bool
    high_contrast: bool
    voice_tone: str
    speech_rate: float
    updated_at: datetime


class OrganizationSettingUpdate(APIModel):
    default_retention: Retention | None = None


class OrganizationSettingResponse(APIModel):
    organization_id: str
    default_retention: Retention
    updated_at: datetime


class ScenarioResponse(APIModel):
    id: str
    title: str
    description: str
    is_active: bool


class PhraseCreate(APIModel):
    scenario_id: str = Field(min_length=1, max_length=40)
    category: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=300)
    english: str = Field(default="", max_length=500)
    subtext: str = Field(default="", max_length=300)


class PhraseUpdate(APIModel):
    category: str | None = Field(default=None, min_length=1, max_length=40)
    text: str | None = Field(default=None, min_length=1, max_length=300)
    english: str | None = Field(default=None, max_length=500)
    subtext: str | None = Field(default=None, max_length=300)
    is_active: bool | None = None


class PhraseResponse(APIModel):
    id: str
    organization_id: str | None
    scenario_id: str
    category: str
    text: str
    english: str
    subtext: str
    is_active: bool


class ConversationCreate(APIModel):
    scenario_id: str = Field(min_length=1, max_length=40)
    retention: Retention | None = None


class ConversationUpdate(APIModel):
    retention: Retention | None = None
    bookmarked: bool | None = None


class MessageCreate(APIModel):
    mode: MessageMode
    text: str = Field(min_length=1, max_length=2000)
    english: str = Field(default="", max_length=3000)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("text")
    @classmethod
    def reject_control_only_text(cls, value: str) -> str:
        if not any(character.isprintable() and not character.isspace() for character in value):
            raise ValueError("Message must contain printable text")
        return value


class MessageUpdate(APIModel):
    text: str = Field(min_length=1, max_length=2000)
    english: str = Field(default="", max_length=3000)


class MessageResponse(APIModel):
    id: str
    conversation_id: str
    mode: MessageMode
    text: str
    english: str
    confidence: float | None
    edited: bool
    created_at: datetime


class ConversationResponse(APIModel):
    id: str
    organization_id: str
    created_by_id: str
    scenario_id: str
    retention: Retention
    status: ConversationStatus
    expires_at: datetime | None
    bookmarked: bool
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = []


class PageInfo(APIModel):
    limit: int
    count: int
    total: int
    next_cursor: str | None = None
    offset: int | None = None


class ConversationList(APIModel):
    items: list[ConversationResponse]
    page: PageInfo


class RecognitionUnavailable(APIModel):
    code: str = "PROVIDER_NOT_CONFIGURED"
    message: str


class EnvironmentAnalyzeRequest(APIModel):
    kind: Literal["menu", "notice", "kiosk", "manual"]
    extracted_text: str = Field(min_length=1, max_length=5000)


class EnvironmentAnalyzeResponse(APIModel):
    kind: str
    title: str
    summary: str
    steps: list[str]
    ksl_gloss: str
    source: str = "text_rules"
    media_stored: bool = False


class SoundClassifyRequest(APIModel):
    transcript: str = Field(min_length=1, max_length=1000)
    wake_name: str = Field(default="", max_length=80)


class SoundClassifyResponse(APIModel):
    event_type: Literal["door", "name", "broadcast", "danger", "unknown"]
    label: str
    urgency: Literal["normal", "attention", "urgent"]
    should_vibrate: bool
    safety_notice: str


class ConnectRoomCreate(APIModel):
    expires_minutes: int = Field(default=60, ge=10, le=1440)


class ConnectRoomCreated(APIModel):
    id: str
    guest_token: str
    expires_at: datetime
    polling_path: str


class ConnectMessageCreate(APIModel):
    sender: Literal["host", "guest"]
    mode: Literal["sign_to_voice", "voice_to_sign", "text"]
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def printable_connect_text(cls, value: str) -> str:
        if not any(character.isprintable() and not character.isspace() for character in value):
            raise ValueError("Message must contain printable text")
        return value


class ConnectMessageResponse(APIModel):
    id: str
    sender: str
    mode: str
    text: str
    ksl_tokens: list[str]
    created_at: datetime


class ConnectRoomResponse(APIModel):
    id: str
    expires_at: datetime
    messages: list[ConnectMessageResponse]


class AuditResponse(APIModel):
    id: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    created_at: datetime

