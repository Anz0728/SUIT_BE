import asyncio
import os
import sys
from pathlib import Path

TEST_DB = Path(__file__).parent / "test_suit.sqlite3"
os.environ["SUIT_ENV"] = "test"
os.environ["SUIT_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SUIT_JWT_SECRET"] = "test-secret-that-is-long-enough-for-suit-tests"
os.environ["SUIT_BOOTSTRAP_ENABLED"] = "true"
os.environ["SUIT_RATE_LIMIT_ENABLED"] = "false"
os.environ["SUIT_ALLOWED_HOSTS"] = '["testserver"]'

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient, Response  # noqa: E402

from suit_backend.database import Base, SessionLocal, engine  # noqa: E402
from suit_backend.main import app  # noqa: E402
from suit_backend.seed import seed_reference_data  # noqa: E402


class ASGITestClient:
    def request(self, method: str, path: str, **kwargs) -> Response:
        async def send() -> Response:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())

    def get(self, path: str, **kwargs) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> Response:
        return self.request("DELETE", path, **kwargs)


@pytest.fixture
def client():
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_reference_data(db)
    yield ASGITestClient()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def admin_token(client: ASGITestClient) -> str:
    response = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "organization_name": "테스트 기관",
            "email": "admin@example.com",
            "full_name": "테스트 관리자",
            "password": "correct-horse-battery-staple",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


@pytest.fixture
def auth(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}

