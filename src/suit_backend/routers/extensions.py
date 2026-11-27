import re
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status

from suit_backend.deps import CurrentUser
from suit_backend.schemas import (
    ConnectMessageCreate,
    ConnectMessageResponse,
    ConnectRoomCreate,
    ConnectRoomCreated,
    ConnectRoomResponse,
    EnvironmentAnalyzeRequest,
    EnvironmentAnalyzeResponse,
    SoundClassifyRequest,
    SoundClassifyResponse,
)

router = APIRouter(tags=["extensions"])

KIND_TITLES = {
    "menu": "메뉴판",
    "notice": "안내문",
    "kiosk": "키오스크",
    "manual": "제품 설명서",
}
KIND_PREFIXES = {
    "menu": "메뉴에서 주문에 필요한 정보를 찾았습니다.",
    "notice": "안내문의 일정과 주의사항을 확인하세요.",
    "kiosk": "화면을 다음 순서대로 이용하세요.",
    "manual": "사용 전 핵심 사용법과 안전 내용을 확인하세요.",
}
SAFETY_NOTICE = (
    "소리 인식은 안전 보조 기능이며 모든 소리를 정확히 감지하지 못할 수 있습니다. "
    "기존 경보기와 주변 확인을 함께 사용하세요."
)


def split_information(text: str, kind: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if kind == "kiosk":
        numbered = [item.strip() for item in re.split(r"\s*(?=\d+[.)]\s*)", clean) if item.strip()]
        if len(numbered) > 1:
            return numbered[:6]
    parts = re.split(r"(?<=[.!?])\s+|\s*[·•]\s*", clean)
    return [item.strip() for item in parts if item.strip()][:6]


@router.post("/extensions/environment/analyze", response_model=EnvironmentAnalyzeResponse)
def analyze_environment(
    payload: EnvironmentAnalyzeRequest, _: CurrentUser
) -> EnvironmentAnalyzeResponse:
    """Summarize OCR text without receiving or retaining the original image."""
    steps = split_information(payload.extracted_text, payload.kind)
    selected = steps[:4] or [payload.extracted_text.strip()]
    summary = f"{KIND_PREFIXES[payload.kind]} {' · '.join(selected)}"
    gloss = " / ".join(re.sub(r"[,.!?]", "", item).upper() for item in selected)
    return EnvironmentAnalyzeResponse(
        kind=payload.kind,
        title=KIND_TITLES[payload.kind],
        summary=summary,
        steps=steps,
        ksl_gloss=gloss,
    )


@router.post("/extensions/sense/classify", response_model=SoundClassifyResponse)
def classify_sound(payload: SoundClassifyRequest, _: CurrentUser) -> SoundClassifyResponse:
    text = payload.transcript
    wake_name = payload.wake_name.strip()
    if wake_name and wake_name in text:
        result = ("name", "내 이름 부름", "attention")
    elif re.search(r"경보|위험|대피|화재|경적|빵빵", text):
        result = ("danger", "경보·자동차 경적", "urgent")
    elif re.search(r"안내|알려드립니다|방송|출발|도착", text):
        result = ("broadcast", "안내 방송", "attention")
    elif re.search(r"딩동|똑똑|택배|문 앞", text):
        result = ("door", "초인종·노크", "normal")
    else:
        result = ("unknown", "분류되지 않은 소리", "normal")
    return SoundClassifyResponse(
        event_type=result[0],
        label=result[1],
        urgency=result[2],
        should_vibrate=result[0] != "unknown",
        safety_notice=SAFETY_NOTICE,
    )


@dataclass
class RoomMessage:
    id: str
    sender: str
    mode: str
    text: str
    created_at: datetime


@dataclass
class Room:
    id: str
    token: str
    owner_id: str
    expires_at: datetime
    messages: list[RoomMessage] = field(default_factory=list)


rooms: dict[str, Room] = {}
rooms_lock = threading.RLock()


def cleanup_rooms(now: datetime) -> None:
    for room_id in [key for key, room in rooms.items() if room.expires_at <= now]:
        rooms.pop(room_id, None)


def require_room(room_id: str, token: str) -> Room:
    now = datetime.now(UTC)
    with rooms_lock:
        cleanup_rooms(now)
        room = rooms.get(room_id)
        if room is None or not secrets.compare_digest(room.token, token):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
        return room


def message_response(message: RoomMessage) -> ConnectMessageResponse:
    tokens = re.sub(r"[,.!?]", "", message.text).split()[:12]
    return ConnectMessageResponse(
        id=message.id,
        sender=message.sender,
        mode=message.mode,
        text=message.text,
        ksl_tokens=tokens,
        created_at=message.created_at,
    )


@router.post(
    "/connect/rooms", response_model=ConnectRoomCreated, status_code=status.HTTP_201_CREATED
)
def create_connect_room(
    payload: ConnectRoomCreate, current_user: CurrentUser
) -> ConnectRoomCreated:
    now = datetime.now(UTC)
    room = Room(
        id=secrets.token_hex(4).upper(),
        token=secrets.token_urlsafe(24),
        owner_id=current_user.id,
        expires_at=now + timedelta(minutes=payload.expires_minutes),
    )
    with rooms_lock:
        cleanup_rooms(now)
        rooms[room.id] = room
    return ConnectRoomCreated(
        id=room.id,
        guest_token=room.token,
        expires_at=room.expires_at,
        polling_path=f"/api/v1/connect/rooms/{room.id}",
    )


@router.get("/connect/rooms/{room_id}", response_model=ConnectRoomResponse)
def get_connect_room(
    room_id: str, token: str = Query(min_length=20, max_length=128)
) -> ConnectRoomResponse:
    room = require_room(room_id, token)
    return ConnectRoomResponse(
        id=room.id,
        expires_at=room.expires_at,
        messages=[message_response(message) for message in room.messages],
    )


@router.post(
    "/connect/rooms/{room_id}/messages",
    response_model=ConnectMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_connect_message(
    room_id: str,
    payload: ConnectMessageCreate,
    token: str = Query(min_length=20, max_length=128),
) -> ConnectMessageResponse:
    room = require_room(room_id, token)
    message = RoomMessage(
        id=str(uuid.uuid4()),
        sender=payload.sender,
        mode=payload.mode,
        text=payload.text,
        created_at=datetime.now(UTC),
    )
    with rooms_lock:
        room.messages.append(message)
        if len(room.messages) > 200:
            del room.messages[:-200]
    return message_response(message)
