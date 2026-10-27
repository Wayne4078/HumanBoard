# Human Board V0.8 — Agent Tool Contract

## 이번 버전에서 실제로 된 일
- `agent_tool_v08.py`에 AI 에이전트용 `request_human_fieldwork` 함수 도구 정의 추가
- 도구 호출 없이 업무를 진행하는 경우와 사람에게 작업을 제안하는 경우의 5가지 비교 시나리오
- 제안 검증(필드, 금액 한도, 위험 작업, 기존 데이터로 충분한 작업 제외)
- 24개 유닛 테스트 통과 (기존 테스트 포함)
- `tool_results_v0.8.json`에 모의 도구 선택 5/5 기록

## 검증 상태
- 모의 규칙 기반 도구 선택 **5/5**. 이것은 실제 AI의 발주 선택 능력을 측정한 수치가 아닙니다.
- 실제 OpenAI Responses 모델을 연결하는 **코드 경로 준비됨**, 이번 실행 환경에서는 인증 키가 없어 라이브 호출은 수행하지 않음.
- 실제 사람 고용·현장 조사·송금 **0건**. 작업 게시도 이루어지지 않음.
- 인간 승인 `human_authorized=true`가 없는 작업 게시물은 기존 로컬 서버에서 거절됨.

## 실행
Python 3 표준 라이브러리 사용 (외부 패키지 불필요).
```
cd human_board
python -m unittest discover -p 'test_*.py' -v
python agent_tool_v08.py --mode scripted --output tool_results_v0.8.json
# 라이브 모델 시험은 사용자가 직접 키를 환경변수로 설정했을 때만 실행
OPENAI_API_KEY='YOUR_KEY' python agent_tool_v08.py --mode live --model gpt-4.1-mini --output live_results_v0.8.json
```
실제 모델/계정의 API 지원 여부, 모델 이름, API 과금은 별도 확인 필요.

## PM 주의사항
1. 공모전 제출물에는 '24개 테스트 통과'와 'AI 에이전트 자율 발주 검증'을 혼용하지 않는다.
2. 모델 함수 호출은 **작업 초안 제안**이며 구매·지급 권한이 아니다.
3. 업무 안전성, 인증, 공정한 보상, 현장증빙의 신뢰도 및 이의제기 기능은 실제 배포 전에 추가 강화해야 한다.
4. 공모전 시연의 다음 관문은 실제 모델로 5개 시나리오를 실행하여 잘못된 발주·불필요한 발주율을 보고하는 것이다.
