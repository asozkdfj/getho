import Link from "next/link";

export function Disclaimer({ compact = false }: { compact?: boolean }) {
  return (
    <aside className={compact ? "disclaimer compact" : "disclaimer"} role="note">
      <strong>안내</strong> 모든 확률과 기대값은 통계로 계산한 <em>추정치</em>이며 경기 결과를
      보장하지 않습니다. EPL Edge Lab은 데이터 분석 서비스로 베팅을 중개·실행하지 않습니다.{" "}
      {!compact && <Link href="/methodology">방법론과 한계 보기</Link>}
    </aside>
  );
}
