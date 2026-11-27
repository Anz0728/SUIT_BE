# SUIT Backend MVP

SUIT 프론트엔드와 분리해 배포하는 FastAPI 백엔드입니다. 병원 접수와 공공기관 민원 MVP에 필요한 기관 계정, 권한, 표현, 대화 기록, 보관 정책을 제공합니다.

## 폴더 구성

```text
SUIT_BE/
├─ 01_API/                 API 목록과 프론트 연동 규격
├─ 02_기능/                MVP 기능 및 보안 기준
├─ migrations/             Alembic DB 변경 이력
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
alembic upgrade head
uvicorn suit_backend.main:app --reload
```

- API 문서: `http://127.0.0.1:8000/docs`
- 상태 확인: `GET http://127.0.0.1:8000/health`
- 최초 관리자 생성: `POST /api/v1/auth/bootstrap`

`bootstrap`은 기본적으로 비활성화되어 있습니다. 최초 설정 시에만 `SUIT_BOOTSTRAP_ENABLED=true`와 별도의 32자 이상 무작위 `SUIT_BOOTSTRAP_TOKEN`을 설정하고, 요청에 `X-Bootstrap-Token` 헤더를 넣으세요. 첫 관리자 생성 직후 다시 `false`로 바꾸고 재배포해야 합니다.

## 생활 지원 확장 API

- `POST /api/v1/extensions/environment/analyze` — 이미지 원본을 받거나 저장하지 않고, OCR로 추출된 글자를 메뉴판·안내문·키오스크·설명서 유형에 맞춰 요약합니다.
- `POST /api/v1/extensions/sense/classify` — 음성 받아쓰기 문장을 초인종/노크, 이름 호출, 안내 방송, 경보/경적으로 분류합니다. 응답에는 항상 안전 보조 기능 고지가 포함됩니다.
- `POST /api/v1/connect/rooms` — 인증 사용자가 만료 시간이 있는 링크 대화방을 만듭니다.
- `GET /api/v1/connect/rooms/{room_id}?token=...` — 설치하지 않은 참여자가 방의 변환 문장을 조회합니다.
- `POST /api/v1/connect/rooms/{room_id}/messages?token=...` — 수어→음성, 음성→수어, 문자 메시지를 추가합니다.

Connect 방은 현재 단일 프로세스 메모리에 최대 200개 메시지를 보관하고 만료 시 제거하는 MVP입니다. 다중 인스턴스 배포 전 Redis 또는 데이터베이스 저장소로 교체해야 합니다. 서버는 원본 사진·영상·음성을 보관하지 않습니다.

## 환경변수

운영 환경에서는 다음 값을 반드시 배포 서비스의 Secret으로 설정합니다.

```env
SUIT_ENV=production
SUIT_DATABASE_URL=postgresql+psycopg://...
SUIT_JWT_SECRET=32자 이상의 무작위 비밀값
SUIT_BOOTSTRAP_ENABLED=false
SUIT_CORS_ORIGINS=["https://suit-woad.vercel.app"]
SUIT_ALLOWED_HOSTS=["api.suit.example.com"]
```

`.env`와 비밀키는 Git에 커밋하지 않습니다. 프론트의 `VITE_*` 환경변수에는 API 기본 주소만 넣고 JWT 비밀키나 DB 접속정보를 넣지 않습니다.

## 인증 사용 원칙

현재 MVP는 최대 30분의 Bearer access token을 사용합니다. 토큰마다 `jti`와 사용자 인증 버전이 들어가므로 역할 변경·계정 비활성화 시 기존 토큰이 즉시 거부됩니다. 브라우저에서는 토큰을 메모리에만 보관하고 `localStorage`에 저장하지 마세요. 운영 단계에서는 OIDC 공급자 또는 HttpOnly 쿠키 기반 BFF로 전환하는 것을 권장합니다.

직원 추가는 관리자가 임시 비밀번호를 정하는 방식보다 `POST /api/v1/admin/invitations`로 일회용 초대 토큰을 발급하는 방식을 사용합니다. 토큰 원문은 응답에서 한 번만 노출되고 DB에는 SHA-256 해시만 저장됩니다. 비밀번호 변경과 로그아웃은 인증 버전을 올려 기존 access token을 즉시 무효화합니다.

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
bandit -q -r src
pip-audit .
python scripts/check_secrets.py
```

GitHub Actions는 테스트·린트·정적 보안 분석·의존성 취약점·비밀키 패턴을 자동 검사하며 Dependabot이 Python, Docker, Actions 업데이트를 매주 확인합니다. 프로덕션 시작 시에는 반드시 `alembic upgrade head`를 먼저 실행합니다. `compose.yaml`은 별도 `migrate` 서비스가 성공한 뒤 API를 시작합니다. 여러 API 인스턴스로 확장할 때는 현재 프로세스별 rate limit을 Redis 기반 분산 제한으로 바꾸고, 관리형 PostgreSQL 백업·복구 훈련을 추가해야 합니다.

