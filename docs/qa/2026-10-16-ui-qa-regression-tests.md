# UI QA 8건 — 최신 main 반영 확인과 회귀 테스트

작성일: 2026-10-16 (KST) · 기준: `main` `2d4b1ab` · 원 보고서: `codex/qa-latest-ui-review`의 `docs/qa/2026-10-16-ui-review.md`

## 결론

8건 모두 최신 main에 수정이 들어 있습니다. 이 중 5건(QA-01·03·04·06·08)은 회귀 테스트가 없어서 이번에 추가했습니다.
새 테스트는 **수정을 되돌리면 실패하는지** 하나씩 확인했습니다(아래 "되돌림 확인").
코드 동작은 바꾸지 않았습니다. QA-01·04에서는 테스트할 수 있도록 로직을 함수로 분리만 했습니다.

## 항목별 상태

| ID | 수정 위치 (커밋) | 회귀 테스트 | 되돌림 확인 |
| --- | --- | --- | --- |
| QA-01 이전 조합 응답 표시 | `components/CombinationBuilder.tsx` (`5903f2b`) → 이번에 `lib/latestRequest.ts`, `lib/combination.ts`의 `requestAnalysis`로 분리 | `lib/latestRequest.test.ts`, `lib/combination.test.ts` "analysis requests racing" 4개 | 응답 후 선택 변경 시 버림 검사(`isCurrent`)를 지우면 "drops an answer already received…" 실패 |
| QA-02 선택 배당 ≠ 계산 배당 | API `prediction_odds`, `lib/combination.ts` (`ed82c29`) | 기존: `tests/integration/test_api.py::test_combination_analyze`, `lib/combination.test.ts` "priced odds" | (기존 테스트) |
| QA-03 하이라이트 실패가 페이지를 가림 | `app/page.tsx`, `app/leagues/[id]/page.tsx`, `components/Highlights.tsx` (`5903f2b`) | `components/Highlights.test.tsx`: 실패 시 안내 표시, 두 페이지의 `fetchHighlights`가 모두 `orNull`로 감싸였는지 | 홈 페이지의 `orNull`을 지우면 실패 |
| QA-04 날짜 묶음 ↔ 카드 시각 시간대 | `components/LocalTime.tsx`(`fixed`), `components/FixtureCard.tsx` (`ed82c29`) → `lib/time.ts`의 `displayTimeZone`으로 분리 | `lib/time.test.ts` 2개, `components/FixtureCard.test.tsx` (카드가 `fixed` 시각을 쓰는지 요소 트리로 확인) | `FixtureCard`의 `fixed`를 지우면 실패 |
| QA-05 상세 화면 품질 경고 누락 | `lib/picks.ts`의 `qualityWarnings`, `app/fixtures/[id]/page.tsx` (`ed82c29`) | 기존: `lib/picks.test.ts`. 추가: `app/fixture-page.test.ts` (페이지가 경고를 계산·표시하는지 소스 확인) | (소스 확인) |
| QA-06 빈 하이라이트 단정 문구 | `components/Highlights.tsx` (`5903f2b`) | `components/Highlights.test.tsx`: 빈 목록에서 "비슷하다는 뜻" 문구 없음 | — |
| QA-07 주전 판단 불가·불투명을 비주전으로 안내 | `lib/teamNews.ts` (`5903f2b`) | 기존: `lib/teamNews.test.ts` "never calls an unknown or doubtful regular a non-regular" | (기존 테스트) |
| QA-08 모바일 글자 크기 덮임 | `app/globals.css` (`5903f2b`) | `app/globals.test.ts`: 520px 이하 재정의가 기본 선언보다 뒤에 있는지 | 수정 전 CSS(`6ca6dd2`)로 바꾸면 2개 실패 |

## 테스트 환경 변경

- `apps/web/vitest.config.ts`: `*.test.tsx`도 실행합니다. 컴포넌트는 별도 의존성 없이 `react-dom/server`의 `renderToStaticMarkup`과 요소 트리 검사로 확인합니다(Node 환경 그대로).
- 서버 컴포넌트 페이지(`app/page.tsx` 등)는 API를 호출하는 async 컴포넌트라 직접 렌더링하지 않고, 회귀 지점만 소스로 확인합니다. 렌더링 기반 E2E(Playwright)는 CI에 없습니다(TODO #8).

## 실행하지 못한 검증

- 실제 브라우저에서 느린 네트워크로 조합 요청을 겹치게 하는 수동 재현은 하지 않았습니다(단위 테스트가 같은 순서를 재현).
- 런던 등 다른 시간대 브라우저에서의 화면 확인은 하지 않았습니다(시간대 함수 단위 테스트).
