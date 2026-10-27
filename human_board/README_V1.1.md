# Human Board V1.1 — 로컬 검증 기반

Python 3.12+ 표준 라이브러리만 사용합니다. AI는 발주자, 인간은 작업자입니다. 실제 결제·외부 주민 발주 기능은 없습니다. V0.x/V1.0 문서·결과 JSON·showcase는 과거 기록이며 현재 보안 계약은 이 문서와 `../V1.1_ENGINEERING_REPORT.md`를 따릅니다.

## 자동 검증

```bash
# HumanBoard 저장소 루트에서 실행
python -B run_tests.py
```

전체 단위·HTTP 통합·동시성·리뷰 수용 테스트를 실행합니다. 모의 전송기만 사용하며 외부 모델 API를 호출하지 않습니다. 실패 시 종료코드 1입니다. 개별 실행:

```bash
cd human_board
python -B -m unittest discover -p 'test_*.py' -v
python -B ../evidence/verify_review_requirements.py
python -B mission_e2e_v09.py
```

`evidence/reproduce_findings.py`는 수정하지 않은 V1.0 취약 동작의 관찰 스크립트입니다. 이 스크립트의 PASS는 결함 존재를 의미합니다. V1.1 CI는 `verify_review_requirements.py`를 사용합니다. 원본 11개 발견 사항의 안전 요구 13개는 같은 스크립트로 원본/수정본을 비교했습니다. `HB_REVIEW_SOURCE`를 원본 압축 해제 폴더의 `human_board`로 지정하면 원본에 대한 실패를 재현합니다. 수정본 검증에서는 이 변수를 설정하지 않습니다.

## 로컬 서버 초기화 및 재시작

```bash
cd human_board
mkdir -p .local
python -B bootstrap.py --db .local/hb-v11.sqlite3 --org demo --org-budget 100000 --credentials .local/credentials.json
HB_DB="$PWD/.local/hb-v11.sqlite3" HB_HOST=127.0.0.1 HB_PORT=8765 python -B server.py
```

초기화는 새 기관에 한 번만 실행합니다. 재시작은 마지막 서버 명령만 다시 실행합니다. 토큰 파일은 mode 0600으로 생성되고 서버 DB에는 SHA-256 해시만 저장됩니다. 기본 토큰이나 익명 API 권한은 없습니다. 토큰을 채팅·Git·로그·스크린샷에 남기지 마세요. 운영자가 파일에서 필요한 역할의 토큰만 해당 주체에게 전달합니다. 토큰 발급은 로컬 운영자 권한이며 HTTP로 역할을 선택하거나 승격할 수 없습니다. 토큰 폐기는 운영자가 `principals.active=0`으로 관리합니다. 외부 IAM·MFA·회전 자동화·실명 검증은 미구현입니다.

이전 V1.0 DB는 자동 변환하지 않고 거부합니다. 원본을 보존하고 새 DB를 사용하세요. 과거 작업의 신원·승인 근거를 추정해 만들어내지 않습니다. 다른 클라우드 작업에서도 기존 체크아웃을 사용하며, 명시적 요청 없이 Git worktree를 만들 필요가 없습니다.

시작 후 인증 없는 `/api/tasks`가 401인지, 인증한 AI의 목록 조회가 200인지 확인하세요. 준비 상태의 실질 검증은 위 HTTP 통합 테스트와 모의 전체 흐름입니다. 실행 중인 프로세스는 환경 재연결/복구 후 다시 시작해야 합니다. HTTP 기본 서버는 로컬 시험 전용입니다.

## 요청 계약

모든 `/api/*` 요청은 `Authorization: Bearer <역할별 토큰>`을 필요로 합니다. POST 본문은 JSON 객체이며 최대 65,536 bytes입니다. 인증된 기관과 주체를 본문의 `agent`, `worker`, `reviewer`로 바꿀 수 없습니다. `human_authorized=true`는 승인 수단이 아닙니다. CORS 전체 허용은 제거했습니다.

역할별 권한:

| 역할 | 허용 |
|---|---|
| ai_customer | 자기 기관·자신의 승인된 초안 발주, 자신 작업·증빙 조회 |
| worker | 자기 기관의 공개 작업 조회·수락, 본인 배정 작업의 제출·조회 |
| reviewer | 자기 기관 작업·증빙·감사 조회, 원문 확인 후 수동 검수 |
| admin | 자기 기관 임무·예산 등록, 특정 AI 초안 승인, 취소·분쟁 재개, 조회 |

관리자도 검수자 역할을 대신하지 않습니다. 서로 다른 역할의 ID를 발급하더라도 같은 실제 사람이 여러 계정을 공유하지 않도록 하는 운영 절차는 별도 필요합니다.

1. **관리자 `POST /api/register_mission`**

```json
{"mission":"sign-check","budget":10000,"location":"허가된 공공 보행 구역 A","fieldwork_required":true,"authorization_reference":"내부 허가 문서 LOCAL-001"}
```

기존 임무를 덮어쓰지 않습니다. 기관 예산은 로컬 초기화 시, 전체 한도는 새 DB 생성 시 100,000원으로 설정합니다. 임무 예산은 서버 원장입니다. 클라이언트 `budget_krw`는 한도를 변경하지 못합니다. 불필요한 현장 업무는 `fieldwork_required=false`로 등록하며 승인·발주가 거부됩니다.

2. **초안 형식** (`proposal` 공통 객체)

```json
{
  "mission":"sign-check",
  "title":"공공 안내판 가독성 관찰",
  "location":"허가된 공공 보행 구역 A",
  "scope":"공개 보행 구역에서 지정 안내판을 관찰; 출입 제한 구역 접근 제외",
  "evidence_request":"관찰 원문과 방문 시각, 장소가 확인되는 기록",
  "budget":5000,
  "policy":{
    "task_type":"public_observation",
    "access":"public_permitted",
    "access_reference":"내부 허가 문서 LOCAL-001",
    "information_gap":"최신 안내판의 실제 가독성을 원격 자료로 알 수 없음",
    "remote_alternative_checked":true,
    "expertise_required":false,
    "hazardous":false,
    "personal_data":false
  },
  "criteria":["관찰 내용","방문 시간","장소","기록 원문"]
}
```

ID 대신 실제 내용·권한·위험 조건을 검사합니다. 지원 범위는 허가된 공개 관찰뿐입니다. 전문 업무·위험 업무·개인정보 수집·출입권 불명은 거부합니다. 위험 문구 필터는 추가 방어이며 의미 이해나 법적 허가 검증을 보증하지 않습니다. 권한 있는 관리자가 실제 허가 및 대체수단·필요성을 심사한 후에만 승인해야 합니다. 임의의 AI 자기 신고만으로는 게시할 수 없습니다.

3. **관리자 `POST /api/approve_task`**: `{"agent":"demo-ai_customer","proposal":위_객체,"expires_in":900}`

응답의 `approval_id`는 기관·AI·정규화된 초안 전체(금액, 장소, 정책, 기준 포함)·만료시각에 결속되며 한 작업에만 소비됩니다. 최대 유효기간 3,600초입니다. 승인만으로 예산을 예약하지 않으며, 실제 발주 시 예산 부족으로 거부될 수 있습니다.

4. **AI `POST /api/create_task`**: `{"proposal":동일_객체,"approval_id":"AP-...","idempotency_key":"논리발주별-고정키"}`

최초 201, 동일 요청 재시도 200 및 같은 `task_id`, 같은 키로 다른 내용은 409입니다. 키는 기관·AI별 범위입니다. 승인 재사용은 다른 키로도 거부됩니다. 트랜잭션에서 전체/기관/임무 예약과 승인 소비, 작업 생성, 감사를 함께 커밋합니다. DB 경합 시 503/Retry-After를 반환하며 같은 키로 재시도해야 합니다.

5. **작업자 `POST /api/claim_task`**: `{"task_id":"HB-..."}`. 로그인 주체가 배정됩니다.

6. **작업자 `POST /api/submit_evidence`**:

```json
{"task_id":"HB-...","evidence":{
  "observation":"여기에 실제 확인한 관찰 원문을 입력합니다.",
  "observed_at":"2026-10-27T12:00:00+07:00",
  "location":"허가된 공공 보행 구역 A",
  "artifacts":[{"name":"record.txt","media_type":"text/plain","content_base64":"여기에 원문 바이트의 base64"}]
}}
```

위 시간·base64는 설명용이며 그대로 제출하면 유효하지 않을 수 있습니다. 현재 작업 시작 후의 시각·승인된 장소·실제 아티팩트 바이트가 필요합니다. `text/plain`(UTF-8), `image/png`, `image/jpeg`, 파일당 10..32,000 bytes, 최대 4개를 허용합니다. JSON 전체 크기 제한도 적용됩니다. 이미지 서명은 형식의 최소 검사이며 완전한 이미지 디코딩이나 현장 진위 판정이 아닙니다. 증빙 URL은 가져오지 않습니다. 재제출은 새 버전을 추가하며 기존 원문을 덮어쓰지 않습니다.

7. **검수자 `GET /api/tasks/HB-.../evidence?version=1`**: 원문 아티팩트·버전·SHA-256과 검수자에 결속된 `inspection_receipt`를 받습니다. 원문을 직접 확인하세요. `GET /api/tasks/HB-...`는 상태 및 기준을 반환합니다.

8. **검수자 `POST /api/review_task`**:

```json
{"task_id":"HB-...","decision":"accepted","reason":"수동 확인한 구체적인 사유",
 "inspection_receipt":"조회 시 받은 현재 버전의 기록",
 "checks":{"각 승인 기준":{"passed":true,"note":"해당 기준의 확인 근거","artifact_sha256":"조회한 원문 파일 SHA-256"}}}
```

승인은 모든 기준의 실제 항목을 포함해야 합니다. 실패한 항목이 있으면 `needs_revision` 또는 `disputed`로 처리합니다. 조회 기록은 본인·작업·버전과 결속되고 1회 사용됩니다. 이전 버전이나 다른 검수자의 기록으로 승인할 수 없습니다. 본문이 빈 이유, 기준 누락, 파일 참조 불일치는 거부됩니다. 결과는 `MANUAL_REVIEW`, `ground_truth_confirmed=false`, `SIMULATED_NOT_PAID`입니다. 원문을 열었다는 기록만으로 사람이 정직하게 확인했다거나 현장 사실이 맞다는 보장은 하지 않습니다.

9. **관리자 분쟁·취소**:

- `POST /api/resolve_dispute`: `{"task_id":"HB-...","decision":"needs_revision","reason":"재제출 요청 사유"}` 또는 `decision=cancelled`. 분쟁을 바로 accepted로 바꾸는 경로는 없습니다.
- `POST /api/cancel_task`: `{"task_id":"HB-...","reason":"취소 사유"}`. 최종 승인 전 상태에서만 가능합니다.
- 승인 시 reserved → committed(모의 의무액)로 이동하고 취소 시 reserved를 해제합니다. 승인된 committed를 취소 API로 환급하지 않습니다. 실제 지급 기능은 없습니다. 기간별 회계·보상·분쟁 기한·대사는 별도 결정이 필요합니다.

조회: `GET /api/tasks`, `GET /api/audit?task_id=HB-...&after=0&limit=100`, `GET /api/budgets`(관리자). 감사는 기관별 격리와 커서 페이지 조회를 지원하며 제출·검수 당시 버전과 해시를 보존합니다. 원격 변경 불가 감사 저장소나 법적 보존·삭제 체계는 아닙니다.

## 모델 평가

모든 모델 경로에 전달하는 입력은 `mission`, `facts`, `budget_krw`만입니다. `expected`, 진단 ID, 그 밖의 평가 메타데이터는 전송하지 않습니다. 완료되지 않은 응답·오류·거절·미상 도구·빈 결과를 `no_human` 성공으로 집계하지 않습니다. 정상 비발주는 완료된 명시적 JSON 결정과 이유가 필요합니다. 도구 호출도 완료 상태, 인자 스키마와 정책 검증이 필요합니다.

```bash
python -B agent_live_gate_v10.py --check
# 비용·계정·모델을 승인받은 별도 실제 평가에서만:
# python -B agent_live_gate_v10.py --model MODEL --output live_result.json
```

이번 V1.1 검증에서는 외부 모델을 실행하지 않았습니다. 키는 채팅이 아닌 비밀 관리 도구로만 설정합니다. 라벨 누출 제거와 파서 테스트 통과는 모델 판단력·프롬프트 인젝션 내성·새 업무 일반화 검증이 아닙니다. 기존 공개된 합성 fixture는 미공개 홀드아웃이 아닙니다. 실패 시 CLI는 비정상 종료하지만 결과 JSON은 보존합니다.
