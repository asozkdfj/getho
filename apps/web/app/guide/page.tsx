import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "처음 오셨나요? 초보자 가이드" };

export default function GuidePage() {
  return (
    <article className="prose">
      <h1>처음 오셨나요? 3분 가이드</h1>
      <p className="muted">
        EPL Edge Lab은 경기 결과를 &ldquo;맞혀 주는&rdquo; 곳이 아니라, <strong>통계 모델</strong>이
        보는 가능성과 <strong>시장(배당)</strong>이 보는 가능성을 나란히 비교해 보여 주는 분석
        도구입니다. 아래 용어 여섯 개만 알면 모든 화면을 읽을 수 있습니다.
      </p>

      <nav className="card toc" aria-label="목차">
        <a href="#1x2">1X2</a>
        <a href="#odds">배당</a>
        <a href="#fair">시장 공정확률</a>
        <a href="#model">모델 확률</a>
        <a href="#edge">Edge</a>
        <a href="#ev">EV</a>
        <a href="#read">화면 읽는 법</a>
        <a href="#caution">꼭 기억할 점</a>
      </nav>

      <h2 id="1x2">1. 1X2 — 경기 결과는 세 가지</h2>
      <p>
        축구 한 경기의 결과는 <strong>홈 승(1)</strong>, <strong>무승부(X)</strong>,{" "}
        <strong>원정 승(2)</strong> 셋 중 하나입니다. 세 가능성을 더하면 항상 100%입니다.
      </p>

      <h2 id="odds">2. 배당 — 시장이 매긴 가격</h2>
      <p>
        배당(예: <code>2.50</code>)은 시장이 그 결과를 얼마나 일어날 것 같다고 보는지를 가격으로
        표현한 숫자입니다. <strong>1 ÷ 배당</strong>을 하면 시장이 생각하는 가능성이 나옵니다.
      </p>
      <div className="formula">배당 2.50 → 1 ÷ 2.50 = 0.40 → 약 40%</div>
      <p>배당이 낮을수록(예: 1.30) 시장이 그 결과를 유력하게 본다는 뜻입니다.</p>

      <h2 id="fair">3. 시장 공정확률 — 수수료를 뺀 시장의 생각</h2>
      <p>
        세 결과의 1 ÷ 배당을 더하면 100%가 아니라 105% 정도가 됩니다. 넘치는 5%는 배당을 정하는
        쪽(북메이커)의 수수료(마진)입니다. 이 수수료를 덜어 내 합계를 100%로 맞춘 값이{" "}
        <strong>시장 공정확률</strong>이고, 화면에서 &lsquo;시장&rsquo;이라고 표시합니다.
      </p>

      <h2 id="model">4. 모델 확률 — 통계 모델의 생각</h2>
      <p>
        과거 경기 결과로 팀의 공격력·수비력과 장기 전력(Elo)을 계산해서 각 결과의 가능성을 추정한
        값입니다. 화면 카드의 <strong>큰 숫자</strong>가 모델 확률입니다. AI가 감으로 찍은 숫자가
        아니라 공식으로 계산한 값이며, <Link href="/methodology">방법론</Link>에 계산 방식을
        공개합니다.
      </p>

      <h2 id="edge">5. Edge — 모델과 시장의 차이</h2>
      <div className="formula">Edge = 모델 확률 − 시장 공정확률 (단위 %p)</div>
      <ul>
        <li>
          <span className="positive">+초록</span>: 모델이 시장보다 그 결과를 <em>더 높게</em>{" "}
          봅니다.
        </li>
        <li>
          <span className="negative">−빨강</span>: 모델이 시장보다 <em>더 낮게</em> 봅니다.
        </li>
        <li>±2%p 안쪽이면 둘의 시각이 거의 같다고 보면 됩니다.</li>
      </ul>
      <p>
        차이가 크다고 모델이 옳다는 뜻은 아닙니다. 시장은 부상·이적 같은 최신 정보를 빠르게 반영하기
        때문에, 큰 차이의 상당수는 <strong>모델이 놓친 정보</strong> 때문일 수 있습니다.
      </p>

      <h2 id="ev">6. EV(기대값) — 모델이 맞다고 가정했을 때의 장기 평균</h2>
      <div className="formula">EV = 모델 확률 × 배당 − 1</div>
      <p>
        <strong>예시:</strong> 모델 확률 45%, 배당 2.50이면 EV = 0.45 × 2.50 − 1 ={" "}
        <strong>+12.5%</strong>
        입니다. &ldquo;모델이 정확하다면, 같은 상황이 아주 많이 반복될 때 평균적으로 12.5% 유리한
        가격&rdquo;이라는 뜻입니다.
      </p>
      <p>
        EV는 <strong>모델이 맞다는 가정</strong>에서만 성립합니다. 모델이 틀리면 EV도 틀립니다. 한두
        경기의 결과는 운에 크게 좌우되며, EV가 플러스여도 그 경기에서 그 결과가 나온다는 뜻은 전혀
        아닙니다.
      </p>
      <p>
        <span className="badge">기준 초과</span> 표시는 Edge와 EV가 모두 3% 이상일 때만 붙는{" "}
        <strong>참고 신호</strong>이며, 추천이 아닙니다.
      </p>

      <h2 id="read">7. 화면 읽는 법 — 3단계</h2>
      <ol>
        <li>
          <strong>경기 카드의 큰 숫자</strong>로 모델이 어떤 결과를 유력하게 보는지 확인합니다.
        </li>
        <li>
          바로 아래 <strong>&lsquo;시장 ○○%&rsquo;</strong>와 비교합니다. 비슷하면 모델과 시장의
          시각이 같은 경기입니다.
        </li>
        <li>
          카드를 누르면 상세 화면 맨 위 <strong>&lsquo;한눈에 보기&rsquo;</strong>에서 차이를
          문장으로 설명해 줍니다. 숫자 표는 그다음에 봐도 충분합니다.
        </li>
      </ol>

      <h2 id="caution">8. 꼭 기억할 점</h2>
      <ul>
        <li>모든 숫자는 추정치이며 어떤 결과도 보장하지 않습니다.</li>
        <li>
          모델이 시장보다 낫다는 것은 수백 경기 이상의 기록으로만 판단할 수 있습니다. 아직은 그런
          기록이 쌓이는 중입니다.
        </li>
        <li>EPL Edge Lab은 베팅을 권유·중개·실행하지 않습니다.</li>
        <li>
          스포츠 베팅은 지역에 따라 불법일 수 있습니다. 도박 문제로 어려움이 있다면
          한국도박문제예방치유원(국번 없이 <strong>1336</strong>)에서 무료 상담을 받을 수 있습니다.
        </li>
      </ul>

      <p>
        <Link href="/">경기 목록으로 가기 →</Link>
      </p>
    </article>
  );
}
