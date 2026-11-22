# SUIT Backend MVP

SUIT 프론트엔드와 분리해 배포하는 FastAPI 백엔드입니다. 병원 접수와 공공기관 민원 MVP에 필요한 기관 계정, 권한, 표현, 대화 기록, 보관 정책을 제공합니다.

## 폴더 구성

```text
SUIT_BE/
├─ 01_API/                 API 목록과 프론트 연동 규격
├─ 02_기능/                MVP 기능 및 보안 기준
├─ src/suit_backend/       실행 코드
│  ├─ routers/             HTTP API
│  ├─ models.py            DB 모델
│  ├─ schemas.py           요청·응답 검증
│  ├─ security.py          암호 해시·JWT
│  └─ middleware.py        요청 제한·보안 헤더
├─ tests/                  API 자동 테스트
├─ .env.example
├─ Dockerfile
└─ compose.yaml
```

## 로컬 실행

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn suit_backend.main:app --reload
```

- API 문서: `http://127.0.0.1:8000/docs`
- 상태 확인: `GET http://127.0.0.1:8000/health`
- 최초 관리자 생성: `POST /api/v1/auth/bootstrap`

`bootstrap`은 사용자 테이블이 비어 있을 때 한 번만 성공합니다. 운영 배포 후 최초 관리자 생성을 완료하면 해당 엔드포인트에 대한 네트워크 접근도 차단하는 것을 권장합니다.

## 환경변수

운영 환경에서는 다음 값을 반드시 배포 서비스의 Secret으로 설정합니다.

```env
SUIT_ENV=production
SUIT_DATABASE_URL=postgresql+psycopg://...
SUIT_JWT_SECRET=32자 이상의 무작위 비밀값
SUIT_CORS_ORIGINS=["https://suit-woad.vercel.app"]
SUIT_ALLOWED_HOSTS=["api.suit.example.com"]
```

`.env`와 비밀키는 Git에 커밋하지 않습니다. 프론트의 `VITE_*` 환경변수에는 API 기본 주소만 넣고 JWT 비밀키나 DB 접속정보를 넣지 않습니다.

## 인증 사용 원칙

현재 MVP는 짧은 수명의 Bearer access token을 사용합니다. 브라우저에서는 토큰을 메모리에만 보관하고 `localStorage`에 저장하지 마세요. 운영 단계에서는 OIDC 공급자 또는 HttpOnly 쿠키 기반 BFF로 전환하는 것을 권장합니다.

## 데이터 보관

- `none`: 대화가 활성 상태인 동안만 임시 저장되며 종료 시 즉시 삭제됩니다. 비정상 종료 대비 최대 2시간 TTL이 적용됩니다.
- `24h`: 생성 또는 정책 변경 시점부터 24시간
- `7d`: 생성 또는 정책 변경 시점부터 7일
- `keep`: 사용자가 삭제할 때까지

원본 카메라 영상과 음성은 이 MVP 서버에 저장하지 않습니다. `/recognition/sign`, `/recognition/speech`는 실제 AI 공급자가 연결되기 전까지 `503 PROVIDER_NOT_CONFIGURED`를 반환합니다.

## 검증

```powershell
pytest
ruff check .
```

프로덕션에서는 `create_all` 대신 Alembic 마이그레이션, Redis 기반 분산 rate limit, 관리형 PostgreSQL 백업 및 복구 테스트가 추가로 필요합니다.

