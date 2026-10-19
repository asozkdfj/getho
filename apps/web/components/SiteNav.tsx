"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isActivePath } from "@/lib/nav";

const ITEMS = [
  { href: "/", label: "경기" },
  { href: "/leagues", label: "리그" },
  { href: "/combinations", label: "조합" },
  { href: "/picks", label: "지난 픽" },
  { href: "/review", label: "복기" },
  { href: "/performance", label: "모델 성과" },
  { href: "/research", label: "연구" },
  { href: "/guide", label: "가이드" },
  { href: "/methodology", label: "방법론" },
] as const;

/** Main menu; marks the section the visitor is in. */
export function SiteNav() {
  const pathname = usePathname() ?? "/";
  return (
    <nav aria-label="주요 메뉴">
      {ITEMS.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={isActivePath(pathname, item.href) ? "page" : undefined}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
