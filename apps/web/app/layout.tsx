import type { Metadata, Viewport } from "next";
import Link from "next/link";

import { SiteNav } from "@/components/SiteNav";
import { ThemeToggle } from "@/components/ThemeToggle";
import { THEME_SCRIPT } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "EPL Edge Lab", template: "%s · EPL Edge Lab" },
  description:
    "축구 리그별 경기마다 통계 분석과 시장(배당)의 생각을 쉬운 말로 비교해 보여 주는 데이터 분석 서비스",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // the theme script may set data-theme before React hydrates
    <html lang="ko" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <header className="site-header">
          <div className="container header-inner">
            <Link href="/" className="brand">
              EPL <span>Edge Lab</span>
            </Link>
            <SiteNav />
            <ThemeToggle />
          </div>
        </header>
        <main className="container">{children}</main>
        <footer className="site-footer">
          <div className="container">
            확률은 통계적 추정치이며 결과를 보장하지 않습니다 · 베팅 중개/실행 기능 없음 · 데이터
            출처는 경기 목록에 표시됩니다
          </div>
        </footer>
      </body>
    </html>
  );
}
