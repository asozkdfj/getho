# 베트맨 프로토 규칙 목록 (`betman-rules-2026-10-20`)

코드: `apps/api/edge_api/betman_rules.py`. 서버에서 `infra/server/edge.sh betman-rules`로 같은 목록을 볼 수 있습니다.

**원칙**
- 확인하지 못한 규칙은 **추정값으로 채우지 않습니다.**
- 그 규칙에 기대는 결과는 `rules_unverified`로 표시합니다.
- 세후 금액은 `tax`가 확인되기 전까지 보여 주지 않습니다.
- 규칙을 바꾸면 버전을 올립니다.

| 키 | 내용 | 상태 | 출처 · 확인 |
| --- | --- | --- | --- |
| `fixed_odds_at_purchase` | 고정배당 상품. 구매 시점 배당으로 지급액 계산 | **확인** | https://sportstoto.co.kr/faq.php · 2026-10-20 · Codex QA(명세 v0.1) |
| `soccer_regular_time_1x2` | 축구 1X2는 정규시간 기준, 무승부는 별도 결과 | **확인** | 같은 출처 · 2026-10-20 · Codex QA(명세 v0.1) |
| `single_allowed` | 어떤 경기를 단일로 살 수 있는지 | 미확인 | 경기별로 입력(`single_allowed`), 모르면 비움 |
| `combination_size` | 한 티켓의 최소·최대 경기 수 | 미확인 | |
| `same_event_restrictions` | 같은 경기의 다른 시장을 한 티켓에 묶는 제한 | 미확인 | |
| `sale_close` | 발매 마감 시점, 발매 중단, 배당 변경 | 미확인 | 회차별 `sale_close_at`, `sale_status`를 입력 |
| `stake_limits` | 최소 금액, 금액 단위, 구매·지급 한도 | 미확인 | |
| `combined_odds_rounding` | 조합 배당과 지급액의 절사·반올림 | 미확인 | |
| `void_and_cancel` | 취소·중단·무효 경기의 정산 | 미확인 | |
| `tax` | 당첨금 과세·공제와 적용 단위 | 미확인 | |

확인 담당자가 출처를 직접 확인하면, 위 표와 코드에 출처 URL, 확인 시각, 적용일, 확인한 사람을 함께 적고 버전을 올립니다.
이 개발 환경에서는 sportstoto.co.kr과 betman.co.kr에 접속할 수 없어, Claude는 규칙을 직접 확인하지 않았습니다.
