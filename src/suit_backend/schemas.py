from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import ConversationStatus, MessageMode, Retention, Role


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


class UserUpdate(APIModel):
    role: Role | None = None
    is_active: bool | None = None


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
    retention: Retention = Retention.HOURS_24


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
    offset: int
    count: int


class ConversationList(APIModel):
    items: list[ConversationResponse]
    page: PageInfo


class RecognitionUnavailable(APIModel):
    code: str = "PROVIDER_NOT_CONFIGURED"
    message: str


class AuditResponse(APIModel):
    id: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    created_at: datetime

