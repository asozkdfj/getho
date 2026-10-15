"use client";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="card" role="alert">
      <h1>데이터를 불러오지 못했습니다</h1>
      <p className="muted">
        API 서버에 연결할 수 없거나 일시적인 오류가 발생했습니다. 확률 데이터가 지연되었을 수 있으니
        잠시 후 다시 시도하세요.
      </p>
      <button type="button" className="btn" onClick={reset}>
        다시 시도
      </button>
    </div>
  );
}
