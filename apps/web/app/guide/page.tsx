import type { Metadata } from "next";
import Link from "next/link";

import { TERM, TERM_HELP } from "@/lib/terms";

export const metadata: Metadata = { title: "처음 오셨나요? 초보자 가이드" };

const GLOSSARY: { key: keyof typeof TERM; example: string }[] = [
  { key: "model", example: "홈승 46% → 우리 분석은 홈팀이 이길 가능성을 46%로 봄" },
  { key: "market", example: "시장 40% → 배당을 보면 시장은 40%로 봄" },
  { key: "gap", example: "+6%p → 분석이 시장보다 6%p 더 높게 봄" },
  { key: "odds", example: "2.50 → 시장이 매긴 가격(낮을수록 유력)" },
  { key: "ev", example: "+10% → 분석이 맞다면 장기 평균으로 10% 유리한 가격" },
];

export default function GuidePage() {
  return (
    <article className="prose">
      <h1>처음 오셨나요? 3분 가이드</h1>
      <p>
        이 사이트는 경기 결과를 <strong>맞혀 주는 곳이 아닙니다.</strong> 두 가지 생각을 나란히 보여
        줄 뿐이에요.
      </p>
      <ul>
        <li>
          <strong>{TERM.model}</strong>: 과거 경기 결과로 계산한 통계 분석의 생각
        </li>
        <li>
          <strong>{TERM.market}</strong>: 배당(시장 가격)에 담긴 시장의 생각
        </li>
      </ul>
      <p>
        둘이 비슷하면 평범한 경기, 많이 다르면 &ldquo;왜 다를까?&rdquo; 하고 볼 만한 경기입니다.
      </p>

      <h2>화면에 나오는 말, 한눈에</h2>
      <div className="table-scroll">
        <table className="glossary">
          <thead>
            <tr>
              <th scope="col">화면 용어</th>
              <th scope="col">뜻</th>
              <th scope="col">예시</th>
            </tr>
          </thead>
          <tbody>
            {GLOSSARY.map(({ key, example }) => (
              <tr key={key}>
                <th scope="row">{TERM[key]}</th>
                <td>{TERM_HELP[key]}</td>
                <td className="muted">{example}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 id="read">경기 카드 읽는 법</h2>
      <ol>
        <li>
          카드에는 <strong>홈승 · 무 · 원정승</strong> 세 칸이 있어요. 세 칸을 더하면 100%입니다.
        </li>
        <li>
          칸마다 <strong>큰 숫자</strong>가 {TERM.model}, 그 아래 &lsquo;시장 ○○%&rsquo;가{" "}
          {TERM.market}입니다.
        </li>
        <li>
          맨 아래 <span className="positive">초록 +</span> /{" "}
          <span className="negative">빨강 −</span> 숫자가 둘의 {TERM.gap}예요. 2%p보다 작으면 생각이
          거의 같은 거예요.
        </li>
        <li>
          카드를 누르면 맨 위 <strong>&lsquo;한눈에 보기&rsquo;</strong>가 이 경기를 한두 문장으로
          설명해 줍니다.
        </li>
      </ol>

      <h2 id="model">{TERM.model}은 어떻게 나오나요?</h2>
      <p>
        팀마다 최근 경기에서 골을 얼마나 넣고 내줬는지, 오래 쌓인 전력 점수가 몇인지를 계산해서 이번
        경기의 가능성을 숫자로 만듭니다. 사람이나 AI가 감으로 찍은 숫자가 아니라 정해진 공식으로
        계산한 값이에요. 자세한 공식은 <Link href="/methodology">방법론</Link>에 공개합니다.
      </p>

      <h2 id="odds">{TERM.odds}는 무엇인가요?</h2>
      <p>
        배당은 시장이 결과마다 매긴 <strong>가격</strong>이에요. <strong>1 ÷ 배당</strong>을 하면
        시장이 생각하는 가능성이 나와요.
      </p>
      <div className="formula">배당 2.50 → 1 ÷ 2.50 = 0.40 → 약 40%</div>
      <p>배당이 낮을수록(예: 1.30) 시장이 그 결과를 유력하게 본다는 뜻입니다.</p>

      <h2 id="market">{TERM.market}은 왜 따로 계산하나요?</h2>
      <p>
        세 결과의 &lsquo;1 ÷ 배당&rsquo;을 더하면 100%가 아니라 105%쯤 돼요. 넘치는 5%는 배당을
        정하는 회사의 <strong>수수료</strong>입니다. 이 수수료를 빼서 합계를 100%로 맞춘 값이{" "}
        {TERM.market}이에요.
      </p>

      <h2 id="gap">{TERM.gap}가 크면 좋은 건가요?</h2>
      <p>
        꼭 그렇지 않아요. {TERM.gap}는 &ldquo;분석과 시장의 생각이 이만큼 다르다&rdquo;는 뜻일 뿐,
        분석이 맞다는 뜻이 아닙니다.
      </p>
      <ul>
        <li>
          시장은 <strong>부상, 이적, 감독 교체</strong> 같은 최신 소식을 빠르게 반영해요. 우리
          분석은 아직 경기 결과만 봅니다.
        </li>
        <li>
          그래서 {TERM.gap}가 아주 크면(10%p 이상) 분석이 무언가를 놓쳤을 가능성이 더 커요. 화면에 ⚠
          표시로 알려 드립니다.
        </li>
        <li>
          <strong>승격팀</strong>(이번 시즌 새로 올라온 팀)은 데이터가 적어서 분석이 덜 정확해요.
        </li>
      </ul>

      <h2 id="ev">{TERM.ev}은 무엇인가요?</h2>
      <p>
        &ldquo;분석이 맞다고 치면, 같은 상황이 아주 여러 번 반복될 때 평균적으로 얼마나 유리한
        가격인가&rdquo;를 숫자로 나타낸 값이에요.
      </p>
      <div className="formula">
        {TERM.ev} = {TERM.model} × 배당 − 1 &nbsp;→&nbsp; 예: 0.45 × 2.50 − 1 = +12.5%
      </div>
      <p>
        중요한 건 <strong>&ldquo;분석이 맞다면&rdquo;</strong>이라는 조건이에요. 분석이 틀리면{" "}
        {TERM.ev}도 틀립니다. 한 경기의 결과는 운에 크게 좌우되니, {TERM.ev}가 플러스여도 그 결과가
        나온다는 뜻은 아닙니다.
      </p>
      <p>
        <span className="badge">{TERM.flag}</span> 표시는 {TERM.gap}와 {TERM.ev}가 모두 3% 이상일
        때만 붙는 참고 표시이며, 추천이 아닙니다.
      </p>

      <h2 id="watch">&lsquo;이번 주 주목할 경기&rsquo;는요?</h2>
      <p>
        이번 주 경기 중에서 분석이 시장보다 <strong>가장 높게 보는</strong> 결과를 최대 3개 모은
        목록이에요. &ldquo;왜 이렇게 다를까?&rdquo; 살펴볼 만한 경기를 골라 둔 것이지, 추천이
        아닙니다. 위에서 말한 이유(최신 소식, 승격팀) 때문에 분석이 틀렸을 가능성도 함께 표시해요.
      </p>

      <h2 id="leagues">여러 리그는 어떻게 분석하나요?</h2>
      <ul>
        <li>
          리그마다 <strong>그 리그의 경기 결과만으로</strong> 같은 방식의 분석을 따로 해요. 다른
          리그 팀끼리는 비교하지 않아요.
        </li>
        <li>
          <strong>컵 대회</strong>(FA컵, 챔피언스리그 등)는 여러 리그 팀이 섞여 있어서 분석 확률을
          내지 않고 시장(배당)만 보여 줘요.
        </li>
        <li>
          <span className="league-badge positive">정확도 검증됨</span> 표시는 과거 실제 경기로
          분석이 기본 비율보다 분명히 정확했는지 확인한 리그예요.{" "}
          <span className="league-badge caution">검증 전</span> 리그는 같은 방식으로 분석하지만 아직
          확인하지 않았으니 더 조심해서 보세요.
        </li>
      </ul>

      <h2 id="pick">&lsquo;오늘의 픽&rsquo;은 어떻게 고르나요?</h2>
      <ol>
        <li>
          매일 아침 9시(한국 시간)에 그날 <strong>정확도가 검증된 리그</strong>의 경기 가운데{" "}
          <strong>데이터 점검</strong>(최근 수집 성공, 배당이 최신, 두 팀 경기 기록 충분, 경기 시작
          전)을 통과한 경기만 봅니다.
        </li>
        <li>
          그중 {TERM.model}이 <strong>가장 높은 결과 하나</strong>를 고릅니다. 그래도 기준 확률보다
          낮으면 그날은 고르지 않아요.
        </li>
        <li>
          한 번 고르면 <strong>바뀌지 않습니다.</strong> 새로고침해도 같고, 결과를 보고 고치지도
          않아요. 경기가 취소되면 &lsquo;무효&rsquo;로 남깁니다.
        </li>
      </ol>
      <p>
        기준 확률은 과거 실제 경기로 시험한 결과를 보고 정했어요(
        <Link href="/performance#daily">모델 성과</Link>에서 확인). 분석 확률이 70%라도 10번 중
        3번은 다른 결과가 나온다는 뜻이에요. 지난 기록은 <Link href="/picks">지난 픽</Link>에서 모두
        볼 수 있습니다.
      </p>

      <h2 id="caution">꼭 기억할 점</h2>
      <ul>
        <li>모든 숫자는 추정치이며 어떤 결과도 보장하지 않습니다.</li>
        <li>
          분석이 시장보다 정확한지는 수백 경기 이상의 기록으로만 판단할 수 있어요. 아직 기록을 쌓는
          중입니다.
        </li>
        <li>EPL Edge Lab은 베팅을 권유·중개·실행하지 않습니다.</li>
        <li>
          스포츠 베팅은 지역에 따라 불법일 수 있습니다. 도박 문제로 어려움이 있다면
          한국도박문제예방치유원(국번 없이 <strong>1336</strong>)에서 무료 상담을 받을 수 있어요.
        </li>
      </ul>

      <p>
        <Link href="/">경기 목록으로 가기 →</Link>
      </p>
    </article>
  );
}
