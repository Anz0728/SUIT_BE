from conftest import ASGITestClient


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
            "password": "another-secure-password",
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


def test_admin_user_and_role_enforcement(client: ASGITestClient, auth: dict[str, str]):
    created = client.post(
        "/api/v1/admin/users",
        headers=auth,
        json={
            "email": "staff@example.com",
            "full_name": "현장 직원",
            "password": "safe-staff-password-123",
            "role": "staff",
        },
    )
    assert created.status_code == 201, created.text

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "staff@example.com", "password": "safe-staff-password-123"},
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
