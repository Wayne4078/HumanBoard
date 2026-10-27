# Human Board V1.1

ChatGPT 프로젝트에서 검토를 이어가려면 [프로젝트 인수인계](CHATGPT_HANDOFF_KO.md)를 먼저 읽어 주세요.

- 구현·초기화·API 계약: [human_board/README_V1.1.md](human_board/README_V1.1.md)
- 결과·11개 발견 사항 현황·남은 위험: [V1.1_ENGINEERING_REPORT.md](V1.1_ENGINEERING_REPORT.md)
- 원본 리뷰: [REVIEW_KO.md](REVIEW_KO.md)
- 전체 오프라인 테스트: `python -B run_tests.py` (Python 3.12+, 외부 의존성 없음)
- 별도 실제 서버 프로세스·재시작 검증: `python -B evidence/validate_runtime.py`

실모델·실제 주민 발주·실제 결제는 실행하지 않았습니다. F04/F07/F08의 운영 신뢰 요건은 부분 해결입니다. 구버전 문서·결과는 역사적 기록이며 최신 사용 계약은 V1.1 문서입니다.
