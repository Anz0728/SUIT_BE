# 01. API

기본 경로는 `/api/v1`이며 `/health`만 버전 경로 밖에 있습니다. 모든 보호 API는 다음 헤더가 필요합니다.

```http
Authorization: Bearer <access-token>
Content-Type: application/json
```

## 인증

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| POST | `/api/v1/auth/bootstrap` | 공개·최초 1회 | 첫 기관과 관리자 생성 |
| POST | `/api/v1/auth/login` | 공개 | 직원 로그인 |
| GET | `/api/v1/auth/me` | 로그인 | 현재 사용자와 기관 확인 |
| POST | `/api/v1/auth/invitations/accept` | 공개 | 일회용 초대 수락 |
| POST | `/api/v1/auth/password/change` | 로그인 | 비밀번호 변경·기존 토큰 폐기 |
| POST | `/api/v1/auth/logout` | 로그인 | 현재 발급분을 포함한 기존 토큰 폐기 |

최초 관리자 생성:

```http
X-Bootstrap-Token: <32자 이상 별도 초기화 토큰>
```

```json
{
  "organization_name": "SUIT 테스트 기관",
  "email": "admin@example.com",
  "full_name": "관리자",
  "password": "12자 이상의 안전한 비밀번호"
}
```

초기화는 환경변수로 명시적으로 활성화한 동안만 동작하며, 완료 후 반드시 `SUIT_BOOTSTRAP_ENABLED=false`로 바꿉니다.

## 기관 직원 관리

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| GET | `/api/v1/admin/users` | 관리자 | 같은 기관 직원 목록 |
| POST | `/api/v1/admin/users` | 관리자 | 직원 또는 관리자 추가 |
| PATCH | `/api/v1/admin/users/{user_id}` | 관리자 | 역할·활성 상태 변경 |
| POST | `/api/v1/admin/invitations` | 관리자 | 직원 초대 토큰 발급 |

`POST /admin/users`는 호환성을 위해 남겨 둔 deprecated API입니다. 새 직원 등록은 초대 API를 우선 사용합니다.

## 사용자·기관 설정

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| GET/PATCH | `/api/v1/preferences` | 로그인 | 접근성·인식·음성 설정 조회/변경 |
| GET/PATCH | `/api/v1/admin/organization-settings` | 관리자 | 기관 기본 보관 정책 조회/변경 |

서버가 로그인 토큰에서 기관을 결정하므로 요청 본문에 `organization_id`를 받지 않습니다.

## 상황·표현

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| GET | `/api/v1/scenarios` | 로그인 | 활성 상황 목록 |
| GET | `/api/v1/phrases?scenario_id=hospital` | 로그인 | 공통+기관 표현 조회 |
| POST | `/api/v1/admin/phrases` | 관리자 | 기관 전용 표현 추가 |
| PATCH | `/api/v1/admin/phrases/{phrase_id}` | 관리자 | 기관 표현 수정 |
| DELETE | `/api/v1/admin/phrases/{phrase_id}` | 관리자 | 기관 표현 삭제 |

공통 표현은 기관 관리자가 수정·삭제할 수 없습니다. 기관이 만든 표현만 변경할 수 있습니다.

## 대화·메시지

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| POST | `/api/v1/conversations` | 로그인 | 대화 생성 |
| GET | `/api/v1/conversations` | 로그인 | 직원은 본인 대화, 관리자는 기관 대화 목록 |
| GET | `/api/v1/conversations/{id}` | 생성자·관리자 | 대화 상세 |
| PATCH | `/api/v1/conversations/{id}` | 생성자·관리자 | 보관·즐겨찾기 변경 |
| POST | `/api/v1/conversations/{id}/messages` | 생성자·관리자 | 메시지 추가 |
| PATCH | `/api/v1/conversations/{id}/messages/{message_id}` | 생성자·관리자 | 확인 문장 수정 |
| POST | `/api/v1/conversations/{id}/close` | 생성자·관리자 | 대화 종료 |
| DELETE | `/api/v1/conversations/{id}` | 생성자·관리자 | 대화 삭제 |

대화 생성:

```json
{
  "scenario_id": "hospital",
  "retention": "24h"
}
```

`retention`을 생략하면 기관 기본 보관 정책을 적용합니다. 대화·메시지 생성에는 8~128자의 `Idempotency-Key` 헤더를 보내면 네트워크 재시도로 같은 요청이 반복되어도 한 번만 저장됩니다. 같은 키를 다른 본문에 재사용하면 `409`입니다.

대화 목록은 `scenario_id`, `bookmarked`, `status`, `query`, `from_at`, `to_at` 필터를 지원합니다. 응답의 `page.next_cursor`를 다음 요청의 `cursor`로 전달하며, 기존 클라이언트용 `offset`도 지원합니다.

메시지 추가:

```json
{
  "mode": "sign",
  "text": "예약하고 왔어요.",
  "english": "I have an appointment.",
  "confidence": 0.92
}
```

`confidence`는 `0~1` 사이이며, 실제 AI 결과가 아닌 경우 생략합니다.

## AI 연결 예약 API

| Method | Path | 현재 동작 |
|---|---|---|
| POST | `/api/v1/recognition/sign` | 공급자 미설정 `503` |
| POST | `/api/v1/recognition/speech` | 공급자 미설정 `503` |

실제 모델 없이 성공 응답을 위조하지 않습니다. 공급자 연결 전에는 미디어를 수신하거나 저장하지 않습니다.

## 관리자 감사 로그

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| GET | `/api/v1/admin/audit-logs` | 관리자 | 기관 내 변경 이력 |

감사 로그에는 메시지 본문, 영상, 음성, 비밀번호, 토큰을 기록하지 않습니다.

