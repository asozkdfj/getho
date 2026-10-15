/**
 * Plain-language vocabulary shown to users. Technical names stay in code and
 * in the methodology page; screens use these words everywhere so the same idea
 * always has the same name.
 */
export const TERM = {
  model: "분석 확률", // model probability
  market: "시장 예상", // de-vigged (fair) market probability
  gap: "차이", // edge = model - market
  ev: "기대값", // expected value
  implied: "배당 속 확률", // 1 / odds, margin included
  odds: "배당",
  flag: "차이 큼", // edge AND EV above the threshold
} as const;

export const TERM_HELP: Record<keyof typeof TERM, string> = {
  model: "과거 경기 결과로 계산한 통계 분석의 가능성",
  market: "배당에서 수수료를 빼고 계산한, 시장이 보는 가능성",
  gap: "분석 확률 − 시장 예상. 초록이면 분석이 더 높게, 빨강이면 더 낮게 봅니다",
  ev: "분석이 맞다고 가정할 때, 장기 평균으로 얼마나 유리한 가격인지",
  implied: "배당을 그대로 확률로 바꾼 값(수수료 포함)",
  odds: "시장이 결과마다 매긴 가격. 낮을수록 시장이 유력하게 봅니다",
  flag: "차이와 기대값이 모두 3% 이상일 때만 붙는 참고 표시(추천 아님)",
};
