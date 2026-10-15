import Link from "next/link";

export default function NotFound() {
  return (
    <div className="card">
      <h1>페이지를 찾을 수 없습니다</h1>
      <p>
        요청한 경기나 페이지가 없습니다. <Link href="/">경기 목록으로 돌아가기</Link>
      </p>
    </div>
  );
}
