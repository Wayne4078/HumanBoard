# ChatGPT 프로젝트 인수인계 — Human Board V1.1

이 저장소에는 사용자가 제공한 V1.0을 검토·수정한 V1.1 소스와 재현 근거가 있습니다. 원본 리뷰는 `REVIEW_KO.md`이며, 현재 구현 상태는 `V1.1_ENGINEERING_REPORT.md`를 기준으로 확인합니다. 구버전 README·결과 파일은 역사적 기록입니다.

## 읽을 자료

1. `V1.1_ENGINEERING_REPORT.md`: 11개 발견 사항 현황, 변경 이유, 검증 한계, PM 결정사항.
2. `human_board/README_V1.1.md`: 실행과 역할별 API 계약.
3. `evidence/v11-full-tests.txt`, `evidence/v11-runtime-validation.json`: 테스트 및 서버 재시작 검증 결과.
4. 실제 구현: `human_board/server.py`, `storage.py`, `policy.py`, `model_protocol.py`와 관련 테스트.

## 현재 확인된 상태

- 전체 로컬 자동 테스트 84/84 통과.
- 기존 11개 발견 사항의 보안 수용 테스트 13개는 원본에서 실패, 수정본에서 통과.
- 8개는 명시된 로컬 수용 기준에서 수정, F04 안전 심사·F07 현장 증빙 신뢰성·F08 감사 보존 체계는 운영 요건이 남아 부분 해결.
- 외부 모델 호출 0, 실제 주민 발주 0, 실제 지급 0원.
- 수동 검수를 AI 검수로 표시하지 않으며 현장 진위·자율 판단 성능·기관 실운영 준비 완료는 검증하지 않음.

## 재검증

Python 3.12+와 표준 라이브러리만 필요합니다. 저장소 루트에서:

```bash
python -B run_tests.py
python -B evidence/validate_runtime.py
```

후자의 시험은 임시 DB·역할별 토큰·로컬 HTTP 서버를 만들고 정리합니다. 외부 모델이나 실제 참여자·결제는 실행하지 않습니다.

## PM의 다음 판단

보고서 마지막 절의 신원/승인, 안전 책임, 증빙/감사, 예산/보상/분쟁, 독립 모델 평가 조건을 확인하세요. 추가 작업의 우선순위를 정할 때 테스트 통과 수와 실제 AI 성능을 구분해야 합니다.
