import pytest
from conftest import ASGITestClient
from pydantic import SecretStr

from suit_backend.config import Settings, get_settings


def test_health_and_security_headers(client: ASGITestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]


def test_bootstrap_is_one_time_and_login_works(client: ASGITestClient, admin_token: str):
    second = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "organization_name": "다른 기관",
            "email": "other@example.com",
            "full_name": "다른 관리자",
            "password": "independent-secure-passphrase",
        },
    )
    assert second.status_code == 409

    bad = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong"},
    )
    assert bad.status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "ADMIN@example.com", "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"


def test_bootstrap_requires_configured_token(client: ASGITestClient):
    settings = get_settings()
    original = settings.bootstrap_token
    settings.bootstrap_token = SecretStr("bootstrap-token-that-is-long-and-independent")
    payload = {
        "organization_name": "보안 테스트 기관",
        "email": "secure-admin@example.com",
        "full_name": "보안 관리자",
        "password": "correct-horse-battery-staple",
    }
    try:
        denied = client.post("/api/v1/auth/bootstrap", json=payload)
        assert denied.status_code == 403
        allowed = client.post(
            "/api/v1/auth/bootstrap",
            headers={"X-Bootstrap-Token": settings.bootstrap_token.get_secret_value()},
            json=payload,
        )
        assert allowed.status_code == 201
    finally:
        settings.bootstrap_token = original


def test_weak_password_is_rejected(client: ASGITestClient):
    response = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "organization_name": "테스트 기관",
            "email": "admin@example.com",
            "full_name": "테스트 관리자",
            "password": "password1234",
        },
    )
    assert response.status_code == 422


def test_admin_user_and_role_enforcement(client: ASGITestClient, auth: dict[str, str]):
    created = client.post(
        "/api/v1/admin/users",
        headers=auth,
        json={
            "email": "staff@example.com",
            "full_name": "현장 직원",
            "password": "independent-field-passphrase",
            "role": "staff",
        },
    )
    assert created.status_code == 201, created.text

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "staff@example.com", "password": "independent-field-passphrase"},
    )
    staff_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied = client.get("/api/v1/admin/users", headers=staff_auth)
    assert denied.status_code == 403

    me = client.get("/api/v1/auth/me", headers=auth).json()
    last_admin = client.patch(
        f"/api/v1/admin/users/{me['id']}",
        headers=auth,
        json={"role": "staff"},
    )
    assert last_admin.status_code == 409


def test_role_or_status_change_revokes_existing_token(
    client: ASGITestClient, auth: dict[str, str]
):
    created = client.post(
        "/api/v1/admin/users",
        headers=auth,
        json={
            "email": "revoke@example.com",
            "full_name": "권한 변경 직원",
            "password": "long-passphrase-for-revocation",
            "role": "staff",
        },
    )
    user_id = created.json()["id"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "revoke@example.com", "password": "long-passphrase-for-revocation"},
    )
    staff_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=staff_auth).status_code == 200
    disabled = client.patch(
        f"/api/v1/admin/users/{user_id}", headers=auth, json={"is_active": False}
    )
    assert disabled.status_code == 200
    assert client.get("/api/v1/auth/me", headers=staff_auth).status_code == 401


def test_staff_cannot_read_another_staff_conversation(
    client: ASGITestClient, auth: dict[str, str]
):
    staff_headers = []
    for index in (1, 2):
        email = f"staff{index}@example.com"
        password = f"safe-staff-password-{index}00"
        created = client.post(
            "/api/v1/admin/users",
            headers=auth,
            json={
                "email": email,
                "full_name": f"현장 직원 {index}",
                "password": password,
                "role": "staff",
            },
        )
        assert created.status_code == 201
        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        staff_headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})

    conversation = client.post(
        "/api/v1/conversations",
        headers=staff_headers[0],
        json={"scenario_id": "hospital", "retention": "24h"},
    )
    conversation_id = conversation.json()["id"]
    assert client.get(
        f"/api/v1/conversations/{conversation_id}", headers=staff_headers[1]
    ).status_code == 404
    assert client.get("/api/v1/conversations", headers=staff_headers[1]).json()["items"] == []


def test_scenarios_and_organization_phrase(client: ASGITestClient, auth: dict[str, str]):
    scenarios = client.get("/api/v1/scenarios", headers=auth)
    assert scenarios.status_code == 200
    assert {item["id"] for item in scenarios.json()} >= {"hospital", "public"}

    phrase = client.post(
        "/api/v1/admin/phrases",
        headers=auth,
        json={
            "scenario_id": "hospital",
            "category": "접수",
            "text": "필기 통역을 부탁드려요.",
            "english": "Please provide written interpretation.",
            "subtext": "필기 지원 요청",
        },
    )
    assert phrase.status_code == 201, phrase.text
    listed = client.get("/api/v1/phrases?scenario_id=hospital", headers=auth)
    assert any(item["text"] == "필기 통역을 부탁드려요." for item in listed.json())


def test_conversation_message_retention_and_delete(
    client: ASGITestClient, auth: dict[str, str]
):
    created = client.post(
        "/api/v1/conversations",
        headers=auth,
        json={"scenario_id": "hospital", "retention": "24h"},
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]
    assert created.json()["expires_at"] is not None

    message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=auth,
        json={
            "mode": "sign",
            "text": "예약하고 왔어요.",
            "english": "I have an appointment.",
            "confidence": 0.92,
        },
    )
    assert message.status_code == 201, message.text

    detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=auth)
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 1

    removed = client.delete(f"/api/v1/conversations/{conversation_id}", headers=auth)
    assert removed.status_code == 204
    assert client.get(f"/api/v1/conversations/{conversation_id}", headers=auth).status_code == 404


def test_no_save_conversation_is_deleted_on_close(
    client: ASGITestClient, auth: dict[str, str]
):
    created = client.post(
        "/api/v1/conversations",
        headers=auth,
        json={"scenario_id": "public", "retention": "none"},
    )
    conversation_id = created.json()["id"]
    closed = client.post(f"/api/v1/conversations/{conversation_id}/close", headers=auth)
    assert closed.status_code == 200
    assert closed.json() is None
    assert client.get(f"/api/v1/conversations/{conversation_id}", headers=auth).status_code == 404


def test_recognition_fails_closed_without_provider(
    client: ASGITestClient, auth: dict[str, str]
):
    response = client.post("/api/v1/recognition/sign", headers=auth)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "PROVIDER_NOT_CONFIGURED"


def test_environment_and_sense_extensions(client: ASGITestClient, auth: dict[str, str]):
    environment = client.post(
        "/api/v1/extensions/environment/analyze",
        headers=auth,
        json={
            "kind": "kiosk",
            "extracted_text": "1. 메뉴 선택 2. 옵션 선택 3. 결제 수단 선택",
        },
    )
    assert environment.status_code == 200, environment.text
    assert environment.json()["title"] == "키오스크"
    assert len(environment.json()["steps"]) == 3
    assert environment.json()["media_stored"] is False

    sound = client.post(
        "/api/v1/extensions/sense/classify",
        headers=auth,
        json={"transcript": "수진 님 택배가 문 앞에 있습니다", "wake_name": "수진"},
    )
    assert sound.status_code == 200
    assert sound.json()["event_type"] == "name"
    assert sound.json()["should_vibrate"] is True


def test_connect_room_guest_flow(client: ASGITestClient, auth: dict[str, str]):
    created = client.post(
        "/api/v1/connect/rooms", headers=auth, json={"expires_minutes": 30}
    )
    assert created.status_code == 201, created.text
    room = created.json()
    path = f"/api/v1/connect/rooms/{room['id']}"

    denied = client.get(f"{path}?token={'x' * 24}")
    assert denied.status_code == 404

    message = client.post(
        f"{path}/messages?token={room['guest_token']}",
        json={
            "sender": "guest",
            "mode": "voice_to_sign",
            "text": "오후 두 시에 다시 연락드릴게요.",
        },
    )
    assert message.status_code == 201, message.text
    assert "오후" in message.json()["ksl_tokens"]

    detail = client.get(f"{path}?token={room['guest_token']}")
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 1


def test_streamed_body_limit_cannot_be_bypassed(client: ASGITestClient):
    async def oversized_chunks():
        yield b"{" + (b"x" * 700_000)
        yield b"x" * 700_000 + b"}"

    response = client.post(
        "/api/v1/auth/login",
        headers={"Content-Type": "application/json"},
        content=oversized_chunks(),
    )
    assert response.status_code == 413


def test_unsafe_production_configuration_is_rejected():
    settings = Settings(
        env="production",
        database_url="sqlite:///./unsafe.db",
        jwt_secret="short",
        access_token_minutes=60,
        cors_origins=["http://localhost:5173"],
        allowed_hosts=["localhost"],
    )
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        settings.validate_runtime_security()


def test_preferences_and_organization_default_retention(
    client: ASGITestClient, auth: dict[str, str]
):
    defaults = client.get("/api/v1/preferences", headers=auth)
    assert defaults.status_code == 200
    assert defaults.json()["confidence_threshold"] == 80

    updated = client.patch(
        "/api/v1/preferences",
        headers=auth,
        json={"text_size": "large", "confidence_threshold": 91},
    )
    assert updated.status_code == 200
    assert updated.json()["text_size"] == "large"

    organization = client.patch(
        "/api/v1/admin/organization-settings",
        headers=auth,
        json={"default_retention": "7d"},
    )
    assert organization.status_code == 200
    created = client.post(
        "/api/v1/conversations",
        headers=auth,
        json={"scenario_id": "hospital"},
    )
    assert created.status_code == 201
    assert created.json()["retention"] == "7d"


def test_invitation_acceptance_logout_and_password_change(
    client: ASGITestClient, auth: dict[str, str]
):
    invitation = client.post(
        "/api/v1/admin/invitations",
        headers=auth,
        json={"email": "invited@example.com", "role": "staff"},
    )
    assert invitation.status_code == 201, invitation.text
    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": invitation.json()["token"],
            "full_name": "초대 직원",
            "password": "field-team-secure-passphrase",
        },
    )
    assert accepted.status_code == 201, accepted.text
    staff_auth = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=staff_auth).status_code == 200

    replay = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": invitation.json()["token"],
            "full_name": "재사용",
            "password": "another-secure-user-passphrase",
        },
    )
    assert replay.status_code == 400

    changed = client.post(
        "/api/v1/auth/password/change",
        headers=staff_auth,
        json={
            "current_password": "field-team-secure-passphrase",
            "new_password": "replacement-secure-passphrase",
        },
    )
    assert changed.status_code == 204
    assert client.get("/api/v1/auth/me", headers=staff_auth).status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "invited@example.com", "password": "replacement-secure-passphrase"},
    )
    new_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.post("/api/v1/auth/logout", headers=new_auth).status_code == 204
    assert client.get("/api/v1/auth/me", headers=new_auth).status_code == 401


def test_idempotency_prevents_duplicate_writes(
    client: ASGITestClient, auth: dict[str, str]
):
    headers = {**auth, "Idempotency-Key": "conversation-request-001"}
    payload = {"scenario_id": "hospital", "retention": "24h"}
    first = client.post("/api/v1/conversations", headers=headers, json=payload)
    second = client.post("/api/v1/conversations", headers=headers, json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]

    conflict = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"scenario_id": "public", "retention": "24h"},
    )
    assert conflict.status_code == 409

    message_headers = {**auth, "Idempotency-Key": "message-request-001"}
    message_payload = {"mode": "text", "text": "중복 저장 방지"}
    path = f"/api/v1/conversations/{first.json()['id']}/messages"
    message_one = client.post(path, headers=message_headers, json=message_payload)
    message_two = client.post(path, headers=message_headers, json=message_payload)
    assert message_one.status_code == 201
    assert message_two.json()["id"] == message_one.json()["id"]


def test_conversation_search_filters_and_cursor_pagination(
    client: ASGITestClient, auth: dict[str, str]
):
    created_ids = []
    for index in range(3):
        conversation = client.post(
            "/api/v1/conversations",
            headers=auth,
            json={"scenario_id": "hospital", "retention": "24h"},
        )
        created_ids.append(conversation.json()["id"])
        client.post(
            f"/api/v1/conversations/{conversation.json()['id']}/messages",
            headers=auth,
            json={"mode": "text", "text": f"검색 문구 {index}"},
        )

    client.patch(
        f"/api/v1/conversations/{created_ids[0]}",
        headers=auth,
        json={"bookmarked": True},
    )
    searched = client.get("/api/v1/conversations?query=문구+1", headers=auth)
    assert searched.status_code == 200
    assert searched.json()["page"]["total"] == 1
    assert searched.json()["items"][0]["id"] == created_ids[1]

    bookmarked = client.get("/api/v1/conversations?bookmarked=true", headers=auth)
    assert bookmarked.json()["page"]["total"] == 1
    first_page = client.get("/api/v1/conversations?limit=2", headers=auth).json()
    assert first_page["page"]["count"] == 2
    assert first_page["page"]["total"] == 3
    assert first_page["page"]["next_cursor"]
    cursor = first_page["page"]["next_cursor"]
    second_page = client.get(f"/api/v1/conversations?limit=2&cursor={cursor}", headers=auth)
    assert second_page.status_code == 200
    assert second_page.json()["page"]["count"] == 1
